# SPDX-License-Identifier: GPL-3.0-or-later
"""Library object tools: the catalogue, versions, placing and changing parameters (D102)."""
from __future__ import annotations

import json
import math

from ... import app_bridge as B
from ... import library as Lib
from ... import objedit as OE
from ... import objversions as OV
from .. import messages, units
from ..catalogue import SELECTOR, AgentError, bridge, tool
from .common import lengths, level_guid, point


def _definition(key: str):
    obj = OV._definition(key)
    if obj is None:
        raise AgentError("not_found", what=key)
    return obj


def _values(session, obj, parameters: dict) -> dict:
    """Parameter values for the bridge: lengths with units become metres; the rest pass through."""
    out = {}
    for name, value in (parameters or {}).items():
        p = obj.param(name)
        out[name] = lengths(session, value)[0] if p is not None and p.kind == "length" else value
    return out


@tool("objects.library", {})
def library(session):
    """List the library objects (furniture, sanitary, kitchen...): id, name, category, IFC class, size (metres)
    and parameters with their kind, default and limits."""
    data = bridge(Lib.library_objects)
    items = [{"id": o["id"], "name": o["name"], "category": o["category"], "ifc_class": o["ifc_class"],
              "width_m": o["width"], "depth_m": o["depth"], "height_m": o["height"],
              "parameters": [{k: p[k] for k in ("key", "label", "kind", "value", "min", "max", "options") if k in p}
                             for p in o["params"]]} for o in data["objects"]]
    return {"objects": items, "unit": "m"}


@tool("objects.versions", {"required": ["object"], "properties": {
    "object": {"type": "string", "description": "A library object id (objects.library)."}}})
def versions(session, object):
    """List the saved versions of a library object (the project's and the office's) and its default values."""
    _definition(object)
    return bridge(OV.object_versions, object)


@tool("objects.place", {"required": ["object", "level", "at"], "properties": {
    "object": {"type": "string", "description": "A library object id (objects.library)."},
    "level": {"type": "string", "description": "Level name or GlobalId."},
    "at": {"type": "array", "items": {"type": ["number", "string"]}, "description": "[x, y] of the object's origin."},
    "angle": {"type": ["number", "string"], "description": "Degrees (90, \"90deg\") or \"1.57rad\"."},
    "version": {"type": "string", "description": "A saved version's id (objects.versions); parameters are then ignored."},
    "parameters": {"type": "object", "description": "{parameter: value}; lengths accept units (\"45cm\")."},
    "gravity": {"type": "boolean", "description": "Stand it on the top of the slab under it, if any (default "
                                                  "false: on the level)."},
    "fit_to_walls": {"type": "boolean", "description": "The app's Fit to walls: `at` is a point in front of a wall "
                                                       "face (within the object's depth, at least 0.6 m); the object "
                                                       "turns its back to that face and stands against it, centred at "
                                                       "the point, and `angle` is ignored. With no face in reach it is "
                                                       "placed at `at` as given (default false)."}}},
    writes=True)
def place(session, object, level, at, angle=0, version="", parameters=None, gravity=False, fit_to_walls=False):
    """Place a library object on a level, optionally standing on the slab under it or fitted against a wall."""
    obj = _definition(object)
    storey = level_guid(level)
    x, y = point(session, at, "at")
    try:
        turn = math.radians(units.parse_angle(angle))
    except ValueError:
        raise AgentError("bad_input", hint=messages.text("hint_bad_angle", value=angle)) from None
    values = _values(session, obj, parameters)
    fit = None
    if fit_to_walls:
        width, depth = _size(object, values)
        fit = Lib.fit_to_wall(storey, x, y, width, depth)
        if fit is not None:
            (x, y), turn = fit["origin"], math.radians(fit["angle"])
    r = bridge(Lib.place_object, storey, object, json.dumps(values), x, y, turn, "1" if gravity else "", version)
    out = {"guids": [r["guid"]], "type": r["type"]}
    if fit_to_walls:
        out["fitted"] = None if fit is None else {"wall": fit["wall"], "origin_m": [round(v, 6) for v in fit["origin"]],
                                                  "angle_deg": round(fit["angle"], 6)}
    return out


def _size(key: str, values: dict) -> tuple[float, float]:
    """The object's plan width and depth in metres with these parameter values (LibraryPanel::currentInfo)."""
    info = next((o for o in bridge(Lib.library_objects)["objects"] if o["id"] == key), {})
    width = float(values.get("width", info.get("width") or 1.0))
    depth = float(values.get("depth", width if "width" in values else info.get("depth") or width))
    return width, depth


@tool("objects.place_picture", {"required": ["path", "level", "at", "width"], "properties": {
    "path": {"type": "string", "description": "A PNG or JPEG file; it is kept with the project."},
    "level": {"type": "string", "description": "Level name or GlobalId."},
    "at": {"type": "array", "items": {"type": ["number", "string"]},
           "description": "[x, y] of the picture's bottom middle."},
    "width": {"type": ["number", "string"], "description": "Width; the height follows the picture's proportions."},
    "angle": {"type": ["number", "string"], "description": "Which way it faces: 0 is seen from the south (-Y), "
                                                           "degrees counter-clockwise."},
    "elevation": {"type": ["number", "string"], "description": "Height of its bottom above the level (default 0)."}}},
    writes=True)
def place_picture(session, path, level, at, width, angle=0, elevation=0):
    """Place a picture standing in the 3D model (Archicad's Picture object): a thin panel showing a PNG or JPEG,
    e.g. a person, a tree or a backdrop."""
    storey = level_guid(level)
    x, y = point(session, at, "at")
    (w, z) = lengths(session, width, elevation)
    try:
        turn = units.parse_angle(angle)
    except ValueError:
        raise AgentError("bad_input", hint=messages.text("hint_bad_angle", value=angle)) from None
    r = bridge("place_picture_3d", storey, path, w, x, y, turn, z)
    return {"guids": [r["guid"]]}


@tool("objects.set_parameters", {"required": ["elements", "parameters"], "properties": {
    "elements": SELECTOR,
    "parameters": {"type": "object", "description": "{parameter: value}; lengths accept units (\"45cm\")."},
    "scope": {"type": "string", "enum": ["all", "selection"], "description":
              "all: every placement of the same type changes; selection: only these. Default: all when these are "
              "every placement of their type, else only these."}}}, writes=True)
def set_parameters(session, elements, parameters, scope=""):
    """Change parameters of placed library objects."""
    guids = session.resolve(elements)
    found = [Lib._object_of(B._model.by_guid(g)) for g in guids]
    objs = [f[0] for f in found if f is not None]
    if not objs:
        raise AgentError("bad_input", hint="none of the elements is a library object")
    for name, value in parameters.items():
        obj = next((o for o in objs if o.param(name) is not None), None)
        if obj is None:
            raise AgentError("bad_input", hint=f"no selected object has a parameter {name}")
        bridge(Lib.set_object_parameter, json.dumps(guids), name, _values(session, obj, {name: value})[name],
               {"all": "type"}.get(scope, scope))
    return {"elements": len(guids), "parameters": list(parameters)}


@tool("objects.assign_version", {"required": ["elements", "version"], "properties": {
    "elements": SELECTOR, "version": {"type": "string", "description": "A version id (objects.versions); \"#default\" for the default."}}},
    writes=True)
def assign_version(session, elements, version):
    """Move placed library objects to a saved version."""
    guids = session.resolve(elements)
    bridge(OV.assign_version, json.dumps(guids), version)
    return {"elements": len(guids)}


@tool("objects.update_from_library", {"properties": {"elements": SELECTOR}}, writes=True)
def update_from_library(session, elements=None):
    """Regenerate placed objects from the library's current definition (all of them when no elements are given)."""
    guids = session.resolve(elements) if elements is not None else []
    given = json.dumps(guids) if guids else ""
    if not Lib._outdated(Lib._targets(given)) and not Lib._outdated_versions_of(given):
        return {"updated": 0}  # already current: the bridge calls that a failure, an agent just wants the state
    bridge(Lib.update_from_library, given)
    return {"updated": len(guids) or "all"}


# ---------------------------------------------------------------- object drafts (D101)

_DRAFT = {"type": "object", "description": "A .kimobj object definition (doc 16): id, name, parameters, parts. "
                                           "objects.library and an object's definition show the format."}


@tool("objects.check_draft", {"required": ["draft"], "properties": {"draft": _DRAFT}})
def check_draft(session, draft):
    """Check a parametric object definition without saving it: every error with the field it is in."""
    r = json.loads(OE.check_draft(json.dumps(draft)))
    return {"ok": bool(r.get("ok")), "errors": r.get("errors", [])}


@tool("objects.save_draft", {"required": ["draft"], "properties": {
    "draft": _DRAFT,
    "replace": {"type": "boolean", "description": "Replace the project object with the same id, and rebuild "
                                                 "every placed copy (default false: refuse)."}}}, writes=True)
def save_draft(session, draft, replace=False):
    """Save a parametric object definition into the project's library; place it with objects.place.
    Office-library saves stay with the owner."""
    text = json.dumps(draft)
    key = str(draft.get("id") or "") if isinstance(draft, dict) else ""
    r = json.loads(OE.save_draft(text, "project", key if replace else ""))
    if r.get("exists"):
        raise AgentError("bad_input", hint=f"the project already has an object {r['exists']}: pass replace=true")
    if not r.get("ok"):
        errors = r.get("errors") or []
        raise AgentError("bad_input", hint="; ".join(str(e) for e in errors) or str(r.get("error") or ""))
    return {"ref": r.get("ref", ""), "types": r.get("types", 1)}
