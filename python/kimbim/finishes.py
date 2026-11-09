# SPDX-License-Identifier: GPL-3.0-or-later
"""Room finishes, shafts and basic MEP runs.

* Finishes follow a room's outline: a floor finish (IfcCovering FLOORING) over the whole room, and a
  skirting (SKIRTINGBOARD) or a wall finish (CLADDING) as a band just inside its walls. Making a
  finish again for the same room replaces the old one, so a re-drawn room can be re-finished.
* A shaft cuts the same outline through every slab between two levels, one undo step for all.
* MEP runs are straight duct, pipe or cable-tray segments (IfcDuctSegment, IfcPipeSegment,
  IfcCableCarrierSegment; IfcFlowSegment in IFC2X3) at a centreline height above their level.

Every edit is one undo step; lengths are metres.
"""
from __future__ import annotations

import json
import math

import ifcopenshell
import ifcopenshell.api.geometry
import ifcopenshell.guid
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.util.element
import ifcopenshell.util.placement
import numpy as np

from . import app_bridge as B
from . import authoring as A
from . import layers, renovation

FINISH_PSET = "KIMBIM_Finish"
SHAFT_PSET = "KIMBIM_Shaft"
MEP_PSET = "KIMBIM_MEP"
FINISH_KINDS = {"floor": ("FLOORING", "Floor finish"), "skirting": ("SKIRTINGBOARD", "Skirting"),
                "wall": ("CLADDING", "Wall finish")}
MEP_KINDS = {"duct": ("IfcDuctSegment", "Duct"), "pipe": ("IfcPipeSegment", "Pipe"),
             "cable_tray": ("IfcCableCarrierSegment", "Cable tray")}


# ---------------------------------------------------------------- finishes

def _room(guid):
    space = A._by_guid(guid)
    if space is None or not space.is_a("IfcSpace"):
        return None, None
    storey = ifcopenshell.util.element.get_aggregate(space) or ifcopenshell.util.element.get_container(space)
    return space, storey if storey is not None and storey.is_a("IfcBuildingStorey") else None


def _polyline(f, points, s):
    pts = [f.createIfcCartesianPoint((float(x) / s, float(y) / s)) for x, y in points]
    return f.createIfcPolyline(pts + [pts[0]])


def _ring_solid(f, outer, inner, height, s):
    """An extruded band between two outlines (model units), for skirting and wall finishes."""
    profile = f.createIfcArbitraryProfileDefWithVoids("AREA", None, _polyline(f, outer, s), [_polyline(f, inner, s)])
    position = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None)
    return f.createIfcExtrudedAreaSolid(profile, position, f.createIfcDirection((0.0, 0.0, 1.0)), height / s)


def _existing_finish(space, kind):
    out = []
    for pset in B._model.by_type("IfcPropertySet"):
        if pset.Name != FINISH_PSET:
            continue
        values = {p.Name: getattr(p.NominalValue, "wrappedValue", None) for p in pset.HasProperties}
        if values.get("Room") == space.GlobalId and values.get("Kind") == kind:
            out += [e for e in B._pset_users(pset) if e.is_a("IfcCovering")]
    return out


def make_finish(room_guid: str, kind: str, thickness=None, height=None) -> str:
    """A finish for a room: kind "floor" (thickness, default 2 cm, on the floor), "skirting" (height,
    default 10 cm, thickness 1.5 cm) or "wall" (height, default to the level above, thickness 1.5 cm).
    Replaces the room's earlier finish of the same kind."""
    if B._model is None:
        return A._fail("no model open")
    kind = str(kind or "").strip().lower()
    if kind not in FINISH_KINDS:
        return A._fail("the finish is floor, skirting or wall")
    space, storey = _room(room_guid)
    if space is None:
        return A._fail("select a room")
    if storey is None:
        return A._fail("the room is not on a level")
    from . import rooms

    outline = rooms._outline(space)
    if len(outline) < 3:
        return A._fail("the room has no outline")
    try:
        default_t = 0.02 if kind == "floor" else 0.015
        thickness = float(thickness) if thickness not in (None, "") else default_t
        if kind == "floor":
            height = thickness
        elif height in (None, ""):
            height = 0.1 if kind == "skirting" else rooms._height(storey)
        else:
            height = float(height)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    if not 0.001 <= thickness <= 0.5:
        return A._fail("the finish thickness must be between 1 mm and 50 cm")
    if not 0.001 <= height <= 50:
        return A._fail("the finish height is out of range")
    inner = None
    if kind != "floor":
        from shapely.geometry import Polygon

        band = Polygon(outline).buffer(-thickness, join_style=2)
        if band.is_empty or band.geom_type != "Polygon":
            return A._fail("the room is too small for that finish")
        inner = [tuple(p) for p in band.exterior.coords[:-1]]
    ifc_type, label = FINISH_KINDS[kind]
    old = _existing_finish(space, kind)
    made = {}

    def action():
        f = B._model
        s = A._scale()
        removed = [e.GlobalId for e in old]
        for e in old:
            ifcopenshell.api.root.remove_product(f, product=e)
        covering = ifcopenshell.api.root.create_entity(f, ifc_class="IfcCovering", name=label)
        covering.PredefinedType = ifc_type
        if kind == "floor":
            representation = ifcopenshell.api.geometry.add_slab_representation(
                f, context=A._body_context(), depth=thickness, polyline=outline)
        else:
            solid = _ring_solid(f, outline, inner, height, s)
            representation = f.createIfcShapeRepresentation(A._body_context(), "Body", "SweptSolid", [solid])
        ifcopenshell.api.geometry.assign_representation(f, product=covering, representation=representation)
        matrix = np.eye(4)
        matrix[2][3] = A._elevation(storey)  # on the level (the slab's top)
        ifcopenshell.api.geometry.edit_object_placement(f, product=covering, matrix=matrix, is_si=True)
        ifcopenshell.api.spatial.assign_container(f, products=[covering], relating_structure=storey)
        pset = ifcopenshell.api.pset.add_pset(f, product=covering, name=FINISH_PSET)
        ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={
            "Room": space.GlobalId, "Kind": kind, "Thickness": thickness, "Height": height})
        layers.assign_active(covering)
        renovation.stamp_new(covering)
        made["guid"] = covering.GlobalId
        return 1, [covering.GlobalId], removed

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["guid"], "replaced": len(old)})


def finish_rooms(guids_json: str, kind: str, thickness="", height="") -> str:
    """The same finish for each selected room (one undo step per room); rooms that fail are listed."""
    guids = json.loads(guids_json or "[]")
    made, failed = [], []
    for g in guids:
        r = json.loads(make_finish(g, kind, thickness, height))
        (made if r.get("ok") else failed).append(r.get("guid") if r.get("ok") else {"room": g, "error": r.get("error")})
    if not made:
        return A._fail(failed[0]["error"] if failed else "select one or more rooms")
    return B._dump({"ok": True, "guids": made, "failed": failed,
                    "geometry": {"changed": made, "removed": []}, **B._flags()})


# ---------------------------------------------------------------- shafts

def create_shaft(points_json: str, bottom_storey: str, top_storey: str, name: str = "Shaft") -> str:
    """Cut this outline (plan metres) through every slab on the levels from `bottom_storey` to
    `top_storey` (inclusive) that it overlaps; one undo step. The openings share a shaft id."""
    if B._model is None:
        return A._fail("no model open")
    try:
        outline = A._clean_polygon(json.loads(points_json))
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    if outline is None:
        return A._fail("the outline needs at least 3 points and must not cross itself")
    low, high = A._by_guid(bottom_storey), A._by_guid(top_storey)
    if low is None or high is None or not low.is_a("IfcBuildingStorey") or not high.is_a("IfcBuildingStorey"):
        return A._fail("unknown level")
    z0, z1 = sorted((A._elevation(low), A._elevation(high)))
    from shapely.geometry import Polygon

    from . import editing

    shape = Polygon(outline)
    cuts = []
    for slab in B._model.by_type("IfcSlab"):
        storey = ifcopenshell.util.element.get_container(slab)
        if storey is None or not storey.is_a("IfcBuildingStorey") or A._is_model(storey):
            continue
        if not z0 - 1e-6 <= A._elevation(storey) <= z1 + 1e-6:
            continue
        own = editing._slab_outline_world(slab)
        if len(own) < 3:
            continue
        overlap = shape.intersection(Polygon(own))
        if overlap.is_empty or overlap.area < 1e-6:
            continue
        piece = max(getattr(overlap, "geoms", [overlap]), key=lambda g: g.area)
        cuts.append((slab, [tuple(p) for p in piece.exterior.coords[:-1]]))
    if not cuts:
        return A._fail("the shaft does not cross any slab between those levels")
    shaft_id = ifcopenshell.guid.new()
    made = []

    def action():
        f = B._model
        for slab, cut in cuts:
            opening = A._cut_slab(slab, cut, name=name)
            pset = ifcopenshell.api.pset.add_pset(f, product=opening, name=SHAFT_PSET)
            ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={"Shaft": shaft_id, "Name": name})
            made.append(opening.GlobalId)
        return len(cuts), [slab.GlobalId for slab, _ in cuts], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "shaft": shaft_id, "openings": made, "slabs": [s.GlobalId for s, _ in cuts]})


# ---------------------------------------------------------------- MEP runs

def create_mep_segment(storey_guid: str, kind: str, x1, y1, x2, y2, elevation=2.6, width=0.3, height=0.2) -> str:
    """A straight duct, pipe or cable tray from (x1, y1) to (x2, y2) on a level, its centreline
    `elevation` above the level. Ducts and trays are `width` x `height`; a pipe's diameter is `width`."""
    if B._model is None:
        return A._fail("no model open")
    kind = str(kind or "").strip().lower()
    if kind not in MEP_KINDS:
        return A._fail("the run is a duct, pipe or cable_tray")
    storey = A._by_guid(storey_guid)
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return A._fail("unknown level")
    try:
        x1, y1, x2, y2, elevation, width, height = (float(v) for v in (x1, y1, x2, y2, elevation, width, height))
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    length = math.hypot(x2 - x1, y2 - y1)
    if length < 0.01:
        return A._fail("the run needs two different points")
    if not 0.005 <= width <= 5 or (kind != "pipe" and not 0.005 <= height <= 5):
        return A._fail("the run's size is out of range")
    ifc_class, label = MEP_KINDS[kind]
    if B._model.schema == "IFC2X3":
        ifc_class = "IfcFlowSegment"
    made = {}

    def action():
        f = B._model
        s = A._scale()
        segment = ifcopenshell.api.root.create_entity(f, ifc_class=ifc_class, name=label)
        origin = f.createIfcAxis2Placement2D(f.createIfcCartesianPoint((0.0, 0.0)), None)
        if kind == "pipe":
            profile = f.createIfcCircleProfileDef("AREA", None, origin, width / 2 / s)
        else:
            profile = f.createIfcRectangleProfileDef("AREA", None, origin, width / s, height / s)
        representation = ifcopenshell.api.geometry.add_profile_representation(
            f, context=A._body_context(), profile=profile, depth=length)
        ifcopenshell.api.geometry.assign_representation(f, product=segment, representation=representation)
        d = np.array([(x2 - x1) / length, (y2 - y1) / length, 0.0])  # the extrusion (local Z) runs along it
        up = np.array([0.0, 0.0, 1.0])
        side = np.cross(up, d)  # local X across the run, local Y up
        matrix = np.eye(4)
        matrix[:3, 0], matrix[:3, 1], matrix[:3, 2] = side, up, d
        matrix[:3, 3] = (x1, y1, A._elevation(storey) + elevation)
        ifcopenshell.api.geometry.edit_object_placement(f, product=segment, matrix=matrix, is_si=True)
        ifcopenshell.api.spatial.assign_container(f, products=[segment], relating_structure=storey)
        pset = ifcopenshell.api.pset.add_pset(f, product=segment, name=MEP_PSET)
        ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={
            "Kind": kind, "Width": width, "Height": width if kind == "pipe" else height,
            "Elevation": elevation, "Length": round(length, 6)})
        layers.assign_active(segment)
        renovation.stamp_new(segment)
        made["guid"] = segment.GlobalId
        return 1, [segment.GlobalId], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["guid"], "length": round(length, 6)})
