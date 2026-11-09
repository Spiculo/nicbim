# SPDX-License-Identifier: GPL-3.0-or-later
"""Models (D58) edited in place and shared across projects (D237).

* Editing in place (Archicad's hotlinked module edit, Revit's Edit Group): while one instance is being
  edited, changes to its elements are mapped back through the inverse of the instance's placement to
  the model's own elements, elements drawn on the instance's level join the model, and deleting an
  instance element deletes it from the model; every instance then follows, in the same undo step.
* The model library: a model saved as a small IFC in a folder (the office library, D99) and loaded
  into another project as a new model, with its types and materials.

Nested models (a model placed inside another) are in authoring.place_model / _follow_model_edits.
"""
from __future__ import annotations

import json
import os
import pathlib

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.project
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.type
import ifcopenshell.api.unit
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.unit
import numpy as np

from . import app_bridge as B
from . import authoring as A

_edit = {"instance": None, "members": {}}  # instance being edited; its element -> model element


def _instance(instance_id):
    elements = A._instances().get(instance_id, [])
    if not elements:
        return None
    info = A._instance_info(elements[0])
    model = A._by_guid(info.get("Model", ""))
    target = ifcopenshell.util.element.get_container(next(e for e in elements if not getattr(e, "FillsVoids", None)))
    return {"elements": elements, "info": info, "model": model, "target": target}


def _snapshot(instance_id) -> dict:
    inst = _instance(instance_id)
    return {e.GlobalId: A._instance_info(e).get("Source") for e in inst["elements"]} if inst else {}


def begin_edit_in_place(instance_id: str) -> str:
    """Start editing an instance where it is placed: its edits go back to its model (and every instance)."""
    if B._model is None:
        return A._fail("no model open")
    inst = _instance(instance_id)
    if inst is None or inst["model"] is None:
        return A._fail("no such model instance")
    _edit["instance"] = instance_id
    _edit["members"] = _snapshot(instance_id)
    return B._dump({"ok": True, "instance": instance_id, "model": inst["model"].GlobalId,
                    "name": inst["model"].Name or "", "guids": sorted(_edit["members"])})


def end_edit_in_place() -> str:
    _edit["instance"], _edit["members"] = None, {}
    return B._dump({"ok": True})


def editing_in_place() -> str:
    return B._dump({"ok": True, "instance": _edit["instance"] or ""})


def _host_wall(e):
    """A door/window or opening's wall (walls carry their openings when copied)."""
    if e.is_a("IfcOpeningElement"):
        rels = getattr(e, "VoidsElements", ()) or ()
        return rels[0].RelatingBuildingElement if rels else None
    for rel in getattr(e, "FillsVoids", ()) or ():
        return _host_wall(rel.RelatingOpeningElement)
    return e


def _map_back(changed, removed) -> list:
    """AFTER_ACTION while editing in place: mirror the instance's edits in its model, then update."""
    instance_id = _edit["instance"]
    if not instance_id or B._model is None or (not changed and not removed):
        return []
    inst = _instance(instance_id)
    if inst is None or inst["model"] is None or inst["target"] is None:
        _edit["instance"] = None
        return []
    model, target, info = inst["model"], inst["target"], inst["info"]
    to_level = A._instance_transform(model, target, info.get("X", 0.0), info.get("Y", 0.0), info.get("Angle", 0.0))
    back = np.linalg.inv(to_level)
    members = _edit["members"]
    touched = []
    seen = set()
    for guid in dict.fromkeys(changed):
        e = A._by_guid(guid)
        if e is None or e.is_a("IfcAnnotation") and A._instance_info(e).get("Instance") != instance_id:
            continue
        host = _host_wall(e)
        if host is None or host.id() in seen:
            continue
        seen.add(host.id())
        link = A._instance_info(host)
        if link.get("Instance") == instance_id:  # an edited instance element: it replaces its source
            source = A._by_guid(link.get("Source", ""))
            pairs = A._copy_elements([host], model, back)
            for _old, c in pairs:
                existing = ifcopenshell.util.element.get_pset(c, A.INSTANCE_PSET)
                if existing:
                    ifcopenshell.api.pset.remove_pset(B._model, product=c, pset=B._model.by_id(existing["id"]))
            if source is not None:
                keep = source.GlobalId
                A._remove_products([source])
                pairs[0][1].GlobalId = keep
            touched += [c.GlobalId for _o, c in pairs]
        elif (ifcopenshell.util.element.get_container(host) == target and not link
              and host.is_a("IfcElement") and guid not in members):  # drawn while editing: it joins the model
            pairs = A._copy_elements([host], model, back)
            A._remove_products([host])
            touched += [c.GlobalId for _o, c in pairs]
    for guid in removed:  # an instance element deleted: gone from the model too
        source = A._by_guid(members.get(guid) or "")
        if source is not None and ifcopenshell.util.element.get_container(source) == model:
            A._remove_products([source])
            touched.append(source.GlobalId)
    if not touched:
        return []
    out = touched + A._update_model_in_action(model)
    _edit["members"] = _snapshot(instance_id)
    return out


B.AFTER_ACTION.append(_map_back)


# ---------------------------------------------------------------- the model library

def _by_guid(f, guid):
    try:
        return f.by_guid(guid)
    except RuntimeError:
        return None


def save_model_to_library(model_guid: str, folder: str) -> str:
    """Write a model as `<folder>/<name>.ifc`: its elements, types and materials in a small project
    whose one level is the model. Another project loads it with load_model_from_library."""
    if B._model is None:
        return A._fail("no model open")
    model = A._by_guid(model_guid)
    if model is None or not A._is_model(model):
        return A._fail("not a model")
    elements = [e for e in A._contained(model) if not getattr(e, "FillsVoids", None)
                and not e.is_a("IfcOpeningElement")]
    if not elements:
        return A._fail("the model is empty")
    if not folder or not os.path.isdir(folder):
        return A._fail("choose a library folder")
    name = (model.Name or "Model").strip()
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip() or "Model"
    out = ifcopenshell.api.project.create_file(version=B._model.schema)
    project = ifcopenshell.api.root.create_entity(out, ifc_class="IfcProject", name=name)
    scale = A._scale()  # the library keeps the project's length unit, so placements copy as they are
    raw = {0.001: ("MILLIMETERS", True), 0.01: ("CENTIMETERS", True), 1.0: ("METERS", True),
           0.3048: ("FEET", False), 0.0254: ("INCHES", False)}.get(round(scale, 6), ("MILLIMETERS", True))
    ifcopenshell.api.unit.assign_unit(out, length={"is_metric": raw[1], "raw": raw[0]})
    context = ifcopenshell.api.context.add_context(out, context_type="Model")
    ifcopenshell.api.context.add_context(out, context_type="Model", context_identifier="Body",
                                         target_view="MODEL_VIEW", parent=context)
    site = ifcopenshell.api.root.create_entity(out, ifc_class="IfcSite", name="Library")
    building = ifcopenshell.api.root.create_entity(out, ifc_class="IfcBuilding", name="Library")
    storey = ifcopenshell.api.root.create_entity(out, ifc_class="IfcBuildingStorey", name=name)
    ifcopenshell.api.aggregate.assign_object(out, products=[site], relating_object=project)
    ifcopenshell.api.aggregate.assign_object(out, products=[building], relating_object=site)
    ifcopenshell.api.aggregate.assign_object(out, products=[storey], relating_object=building)
    pset = ifcopenshell.api.pset.add_pset(out, product=storey, name=A.MODEL_PSET)
    ifcopenshell.api.pset.edit_pset(out, pset=pset, properties={"IsModel": True})
    reuse: dict = {}
    base = A._elevation(model) / A._scale()
    for e in elements:
        t = ifcopenshell.util.element.get_type(e)
        tc = ifcopenshell.api.project.append_asset(out, library=B._model, element=t, reuse_identities=reuse) if t else None
        c = ifcopenshell.api.project.append_asset(out, library=B._model, element=e, reuse_identities=reuse)
        if c is None:
            continue
        tc = tc or (_by_guid(out, t.GlobalId) if t is not None else None)  # appended before: reuse it
        if tc is not None and ifcopenshell.util.element.get_type(c) is None:
            ifcopenshell.api.type.assign_type(out, related_objects=[c], relating_type=tc)
        if c.ObjectPlacement is not None:  # the model's level becomes the library level, at zero
            m = ifcopenshell.util.placement.get_local_placement(c.ObjectPlacement)
            m[2][3] -= base
            ifcopenshell.api.geometry.edit_object_placement(out, product=c, matrix=m, is_si=False)
        ifcopenshell.api.spatial.assign_container(out, products=[c], relating_structure=storey)
    path = pathlib.Path(folder) / f"{safe}.kimmodel.ifc"
    out.write(str(path))
    return B._dump({"ok": True, "path": str(path), "elements": len(elements)})


def library_models(folder: str) -> str:
    """The models saved in a library folder: [{name, path}]."""
    items = []
    if folder and os.path.isdir(folder):
        for p in sorted(pathlib.Path(folder).glob("*.kimmodel.ifc")):
            items.append({"name": p.name[: -len(".kimmodel.ifc")], "path": str(p)})
    return B._dump({"ok": True, "models": items})


def load_model_from_library(path: str, name: str = "") -> str:
    """Bring a library model into this project as a new model (its types and materials with it); place
    it on levels like any model. One undo step for the content (the model level is its own step)."""
    if B._model is None:
        return A._fail("no model open")
    try:
        library = ifcopenshell.open(path)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"could not open the library model: {ex}")
    levels = [s for s in library.by_type("IfcBuildingStorey") if A.MODEL_PSET in ifcopenshell.util.element.get_psets(s)]
    if not levels:
        return A._fail("that file is not a NicBim library model")
    source = levels[0]
    wanted = [e for rel in getattr(source, "ContainsElements", ()) or () for e in rel.RelatedElements
              if not getattr(e, "FillsVoids", None) and not e.is_a("IfcOpeningElement")]
    name = (name or source.Name or pathlib.Path(path).stem).strip()
    taken = {s.Name for s in B._model.by_type("IfcBuildingStorey")}
    base, n = name, 2
    while name in taken:
        name, n = f"{base} {n}", n + 1
    made = json.loads(A.create_model(name))
    if not made.get("ok"):
        return B._dump(made)
    model = A._by_guid(made["guid"])
    lib_scale = ifcopenshell.util.unit.calculate_unit_scale(library)
    z, scale = A._elevation(model), A._scale()
    reuse: dict = {}
    guids = []

    def action():
        for e in wanted:
            t = ifcopenshell.util.element.get_type(e)
            tc = (ifcopenshell.api.project.append_asset(B._model, library=library, element=t, reuse_identities=reuse)
                  if t is not None else None)
            c = ifcopenshell.api.project.append_asset(B._model, library=library, element=e, reuse_identities=reuse)
            if c is None:
                continue
            tc = tc or (_by_guid(B._model, t.GlobalId) if t is not None else None)
            if tc is not None and ifcopenshell.util.element.get_type(c) is None:
                ifcopenshell.api.type.assign_type(B._model, related_objects=[c], relating_type=tc)
            if c.ObjectPlacement is not None:
                m = ifcopenshell.util.placement.get_local_placement(c.ObjectPlacement)
                m[:3, 3] *= lib_scale / scale
                m[2][3] += z / scale
                ifcopenshell.api.geometry.edit_object_placement(B._model, product=c, matrix=m, is_si=False)
            ifcopenshell.api.spatial.assign_container(B._model, products=[c], relating_structure=model)
            guids.append(c.GlobalId)
        return len(guids), guids, []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "model": model.GlobalId, "name": name, "guids": guids})

