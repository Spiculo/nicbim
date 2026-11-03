# SPDX-License-Identifier: GPL-3.0-or-later
"""Structural analytical model (D224).

Derives a simple IFC4/IFC2X3 analytical model from the physical members: columns and beams become
``IfcStructuralCurveMember`` edges along their extrusion axis, and slabs and roofs become
``IfcStructuralSurfaceMember`` shells from their footprint. All of them are assigned to one
``IfcStructuralAnalysisModel`` (LOADING_3D), tagged with ``KIMBIM_Analytical`` (SourceGuid, Kind)
so a derivation can be traced back and re-run in place. This is a geometry-only idealisation: no
loads, supports, releases or results are invented, and a structural engineer still defines those.
"""
from __future__ import annotations

import datetime

import ifcopenshell.api.geometry
import ifcopenshell.api.group
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.unit
import numpy as np

from . import app_bridge as B
from . import authoring as A

PSET = "KIMBIM_Analytical"
MODEL_PSET = "KIMBIM_AnalysisModel"


def _now() -> str:
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def _body_items(element) -> list:
    representation = getattr(element, "Representation", None)
    if representation is None:
        return []
    items = []
    for shape in representation.Representations or ():
        items.extend(shape.Items or ())
    return items


def _element_placement(element) -> np.ndarray:
    return ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement)


def _axis(element) -> tuple[np.ndarray, np.ndarray] | None:
    """The member's axis in model units: placement origin to origin + local Z x extrusion depth."""
    matrix = _element_placement(element)
    for item in _body_items(element):
        if item.is_a("IfcExtrudedAreaSolid") or item.is_a("IfcExtrudedAreaSolidTapered"):
            depth = float(item.Depth)
            start = matrix[:3, 3]
            end = start + matrix[:3, 2] * depth
            return start, end
    return None


def _profile_points(profile) -> list[tuple[float, float]]:
    if profile.is_a("IfcRectangleProfileDef"):
        x, y = float(profile.XDim) / 2.0, float(profile.YDim) / 2.0
        return [(-x, -y), (x, -y), (x, y), (-x, y)]
    if profile.is_a("IfcCircleProfileDef"):
        r = float(profile.Radius)
        return [(r * np.cos(t), r * np.sin(t)) for t in np.linspace(0, 2 * np.pi, 13)[:-1]]
    curve = getattr(profile, "OuterCurve", None)
    if curve is not None:
        if curve.is_a("IfcPolyline"):
            return [tuple(float(c) for c in p.Coordinates[:2]) for p in curve.Points]
        if curve.is_a("IfcIndexedPolyCurve") and not curve.Segments:
            return [tuple(float(c) for c in p[:2]) for p in curve.Points.CoordList]
    return []


def _footprint(element) -> list[np.ndarray]:
    """World points of the element's footprint at mid-depth (model units)."""
    matrix = _element_placement(element)
    for item in _body_items(element):
        if item.is_a("IfcExtrudedAreaSolid") or item.is_a("IfcExtrudedAreaSolidTapered"):
            profile = item.SweptArea
            points = _profile_points(profile)
            if not points:
                continue
            z = float(item.Depth) / 2.0
            out = []
            for x, y in points:
                out.append((matrix @ np.array([x, y, z, 1.0]))[:3])
            return out
    return []


def _curve_member(f, model, element, kind: str) -> object | None:
    axis = _axis(element)
    if axis is None:
        return None
    start, end = axis
    member = ifcopenshell.api.root.create_entity(
        f, ifc_class="IfcStructuralCurveMember", name=f"{element.Name or kind} (analytical)")
    member.PredefinedType = "RIGID_JOINED_MEMBER"
    v1 = f.createIfcVertexPoint(f.createIfcCartesianPoint(tuple(float(v) for v in start)))
    v2 = f.createIfcVertexPoint(f.createIfcCartesianPoint(tuple(float(v) for v in end)))
    edge = f.createIfcEdge(v1, v2)
    representation = f.createIfcShapeRepresentation(A._body_context(), "Reference", "Edge", [edge])
    ifcopenshell.api.geometry.assign_representation(f, product=member, representation=representation)
    ifcopenshell.api.geometry.edit_object_placement(f, product=member)
    ifcopenshell.api.group.assign_group(f, products=[member], group=model)
    pset = ifcopenshell.api.pset.add_pset(f, product=member, name=PSET)
    ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={
        "SourceGuid": element.GlobalId, "Kind": kind, "SourceName": element.Name or ""})
    return member


def _surface_member(f, model, element, kind: str) -> object | None:
    points = _footprint(element)
    if len(points) < 3:
        return None
    member = ifcopenshell.api.root.create_entity(
        f, ifc_class="IfcStructuralSurfaceMember", name=f"{element.Name or kind} (analytical)")
    member.PredefinedType = "SHELL"
    loop = f.createIfcPolyLoop([f.createIfcCartesianPoint(tuple(float(v) for v in p)) for p in points])
    bound = f.createIfcFaceOuterBound(loop, True)
    face = f.createIfcFace([bound])
    representation = f.createIfcShapeRepresentation(A._body_context(), "Reference", "Face", [face])
    ifcopenshell.api.geometry.assign_representation(f, product=member, representation=representation)
    ifcopenshell.api.geometry.edit_object_placement(f, product=member)
    ifcopenshell.api.group.assign_group(f, products=[member], group=model)
    pset = ifcopenshell.api.pset.add_pset(f, product=member, name=PSET)
    ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={
        "SourceGuid": element.GlobalId, "Kind": kind, "SourceName": element.Name or ""})
    return member


def _analysis_models() -> list:
    out = []
    for model in B._model.by_type("IfcStructuralAnalysisModel"):
        out.append((model, ifcopenshell.util.element.get_pset(model, MODEL_PSET) or {}))
    return out


def _members(model) -> list:
    out = []
    for rel in getattr(model, "IsGroupedBy", None) or ():
        for member in rel.RelatedObjects or ():
            if member.is_a("IfcStructuralItem"):
                out.append(member)
    return out


def analysis_model() -> str:
    """The derived analytical model and its members, or an empty state."""
    if B._model is None:
        return A._fail("no model open")
    models = _analysis_models()
    if not models:
        return B._dump({"ok": True, "model": None, "members": []})
    model, data = models[0]
    members = _members(model)
    return B._dump({"ok": True, "model": {"guid": model.GlobalId, "name": model.Name or "",
                                          "curves": sum(1 for m in members if m.is_a("IfcStructuralCurveMember")),
                                          "surfaces": sum(1 for m in members if m.is_a("IfcStructuralSurfaceMember")),
                                          "updated": data.get("Updated") or ""},
                    "members": [{"guid": m.GlobalId, "name": m.Name or "", "kind": "curve"
                                 if m.is_a("IfcStructuralCurveMember") else "surface"} for m in members]})


def create_analysis_model(name: str = "Analytical model") -> str:
    """Derive (or re-derive in place) the analytical model from columns, beams, slabs and roofs."""
    if B._model is None:
        return A._fail("no model open")
    name = (name or "Analytical model").strip() or "Analytical model"
    existing = _analysis_models()
    made: dict = {}

    def action():
        f = B._model
        if existing:
            model, _ = existing[0]
            for member in _members(model):
                ifcopenshell.api.group.unassign_group(f, products=[member], group=model)
                f.remove(member)
        else:
            model = ifcopenshell.api.root.create_entity(f, ifc_class="IfcStructuralAnalysisModel", name=name)
            model.PredefinedType = "LOADING_3D"
            ifcopenshell.api.geometry.edit_object_placement(f, product=model)
        curves, surfaces = 0, 0
        for element in f.by_type("IfcProduct"):
            if element.is_a("IfcColumn") or element.is_a("IfcBeam"):
                if _curve_member(f, model, element, "column" if element.is_a("IfcColumn") else "beam"):
                    curves += 1
            elif element.is_a("IfcSlab") or element.is_a("IfcRoof"):
                if _surface_member(f, model, element, "slab" if element.is_a("IfcSlab") else "roof"):
                    surfaces += 1
        pset = ifcopenshell.util.element.get_pset(model, MODEL_PSET)
        pset = f.by_id(pset["id"]) if pset else ifcopenshell.api.pset.add_pset(f, product=model, name=MODEL_PSET)
        ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={
            "Source": "derived", "Curves": curves, "Surfaces": surfaces, "Updated": _now()})
        made.update(guid=model.GlobalId, curves=curves, surfaces=surfaces)
        return 1, [model.GlobalId], []

    try:
        result = B._run(action)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**result, "guid": made["guid"], "curves": made["curves"],
                    "surfaces": made["surfaces"]})


def remove_analysis_model() -> str:
    """Delete the derived analytical model and its members (the physical model is untouched)."""
    if B._model is None:
        return A._fail("no model open")
    models = _analysis_models()
    if not models:
        return A._fail("there is no analytical model")

    def action():
        f = B._model
        model = models[0][0]
        for member in _members(model):
            ifcopenshell.api.group.unassign_group(f, products=[member], group=model)
            f.remove(member)
        f.remove(model)
        return 1, [], []

    try:
        result = B._run(action)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**result, "removed": True})
