# SPDX-License-Identifier: GPL-3.0-or-later
"""Underlay and saved-view tools (doc 18 §6 items 5 and 6). Underlays are DXF, DWG, PDF or image files copied
into the project and drawn under a level's plan (D85, D132), optionally in 3D (`show_3d`); converting one turns
its linework into editable 2D elements (D200). Saved views are the project's named views; applying one, hiding,
isolating and zooming change the running app's view only (live mode), after the call, and never the model."""
from __future__ import annotations

import json

from ... import layers as LY
from ... import underlays as U
from ..catalogue import SELECTOR, AgentError, bridge, tool
from .common import lengths, level_guid, point

_AFTER_ADD = ("visible", "locked", "clip")
_METRES = {"mm": 0.001, "cm": 0.01, "m": 1.0, "in": 0.0254, "ft": 0.3048}
_ID = {"type": "string", "description": "The underlay id (underlays.list lists them)."}
_DISPLAY = {
    "name": {"type": "string"},
    "opacity": {"type": "number", "minimum": 0, "maximum": 1},
    "greyscale": {"type": "boolean"},
    "tint": {"type": "string", "description": "A #rrggbb colour, or \"\" for none."},
    "visible": {"type": "boolean"},
    "locked": {"type": "boolean"},
    "show_3d": {"type": "boolean", "description": "Also draw it in the 3D view, at its level."},
    "rotation": {"type": "number", "description": "Degrees, anticlockwise."},
    "scale": {"type": "number", "minimum": 0.000001,
              "description": "Metres per drawing unit (0.001 for a DXF in mm); the file's units set it, so "
                             "leave it out unless they are wrong. Not a drawing scale like 1:100."},
    "page": {"type": "integer", "minimum": 0, "description": "PDF: which page (0 = first)."},
    "vector": {"type": "boolean", "description": "PDF: read its linework (needed for underlays.convert) "
                                                "instead of a picture of the page."},
    "clip": {"type": "array", "items": {"type": "number"},
             "description": "[x1, y1, x2, y2] in drawing units: linework outside is not shown or snapped; [] clears."}}


def _changes(session, values: dict) -> dict:
    out = {k: v for k, v in values.items() if v is not None and k not in ("at", "level")}
    if values.get("at") is not None:
        out["x"], out["y"] = point(session, values["at"], "at")
    if values.get("level"):
        out["storey"] = level_guid(values["level"])
    return out


@tool("underlays.list", {"properties": {
    "level": {"type": "string", "description": "Only the underlays on this level (name or GlobalId)."}}})
def list_(session, level=""):
    """List the project's underlays: id, file, level, placement and display settings."""
    return {"underlays": bridge(U.underlays, level_guid(level) if level else "")["underlays"]}


@tool("underlays.add", {"required": ["path", "level"], "properties": {
    "path": {"type": "string", "description": "A DXF, DWG, PDF, PNG or JPEG file; it is copied into the project."},
    "level": {"type": "string", "description": "The level it lies on (name or GlobalId)."},
    "at": {"type": "array", "items": {"type": "number"},
           "description": "[x, y] where its origin goes, in project units (default: the level's origin)."},
    "units": {"type": "string", "enum": ["mm", "cm", "m", "in", "ft"],
              "description": "DXF without units: the unit it was drawn in."},
    **_DISPLAY}}, writes=True)
def add(session, path, level, at=None, units=None, **display):
    """Place a DXF, DWG, PDF or image file as an underlay on a level, to trace over or convert."""
    options = _changes(session, {**display, "at": at, "level": level})
    if units:
        options["units"] = _METRES[units]
    later = {k: options.pop(k) for k in _AFTER_ADD if k in options}  # add_underlay does not take these
    underlay = bridge(U.add_underlay, path, json.dumps(options))["underlay"]
    if later:
        underlay = bridge(U.set_underlay, underlay["id"], json.dumps(later))["underlay"]
    return {"underlay": underlay}


@tool("underlays.update", {"required": ["id"], "properties": {
    "id": _ID,
    "at": {"type": "array", "items": {"type": "number"}, "description": "[x, y] new origin, in project units."},
    "level": {"type": "string", "description": "Move it to this level (name or GlobalId)."},
    **_DISPLAY}}, writes=True)
def update(session, id, at=None, level=None, **display):
    """Move an underlay or change how it is shown (opacity, tint, clip, 3D, visibility...)."""
    changes = _changes(session, {**display, "at": at, "level": level})
    if not changes:
        raise AgentError("bad_input", hint="give at least one change")
    return {"underlay": bridge(U.set_underlay, id, json.dumps(changes))["underlay"]}


@tool("underlays.remove", {"required": ["id"], "properties": {"id": _ID}}, writes=True)
def remove(session, id):
    """Remove an underlay from the project (and its copied file once nothing uses it)."""
    bridge(U.remove_underlay, id)
    return {"id": id}


@tool("underlays.convert", {"required": ["id"], "properties": {
    "id": _ID,
    "pen": {"type": "integer", "minimum": 1, "description": "Pen of the new lines (default: the current pen)."},
    "text": {"type": "boolean", "description": "PDF: also convert its text (default true)."}}}, writes=True)
def convert(session, id, pen=None, text=None):
    """Turn a DXF, DWG or vector-PDF underlay's linework (and PDF text) into editable 2D elements on its level."""
    options = {k: v for k, v in (("pen", pen), ("text", text)) if v is not None}
    r = bridge(U.convert_to_drafting, id, json.dumps(options))
    return {"count": r.get("count", 0), "guids": r.get("guids", [])}


# ---------------------------------------------------------------- saved views and the app's view

_PLANE = {"type": "object", "required": ["point", "normal"], "properties": {
    "point": {"type": "array", "items": {"type": "number"}, "description": "[x, y, z] on the plane, project units."},
    "normal": {"type": "array", "items": {"type": "number"},
               "description": "[x, y, z]: the side it points to is cut away."},
    "name": {"type": "string"},
    "enabled": {"type": "boolean"}}, "additionalProperties": False}


def _plane_frame(normal) -> dict:
    """normal, direction, kind and angle of a cut plane as the app's faceCutPlane makes them (CutPlanes.cpp)."""
    import math

    length = math.sqrt(sum(float(v) ** 2 for v in normal))
    nx, ny, nz = (float(v) / length for v in normal)
    if abs(nz) > 0.9999:
        direction = [1.0, 0.0, 0.0]
    else:  # Z x n: a level line in the plane
        d = (-ny, nx, 0.0)
        dl = math.hypot(d[0], d[1])
        direction = [d[0] / dl, d[1] / dl, 0.0]
    if abs(nz) < 1e-9:
        kind, angle = "vertical", 0.0
    elif abs(nz) > 1 - 1e-9:
        kind, angle = "horizontal", 0.0
    else:
        kind, angle = "oblique", math.degrees(math.asin(max(-1.0, min(1.0, nz))))
    return {"normal": [nx, ny, nz], "direction": direction, "kind": kind, "angle": angle}


def _app_view(session, command: dict) -> None:
    if session._view is None:
        raise AgentError("needs_app")
    session._view(command)


def _guids(session, elements) -> list[str]:
    guids = session.resolve(elements)
    if not guids:
        raise AgentError("no_match")
    return guids


@tool("views.list", {})
def views_list(session):
    """List the project's saved views by name, with what each stores (level, plan or 3D, cuts, layers, style)."""
    return {"views": bridge(LY.views)["views"]}


@tool("views.save", {"required": ["name"], "properties": {
    "name": {"type": "string"},
    "capture": {"type": "boolean", "description": "Save what the app shows now (needs the app; the other "
                                                 "settings are then ignored)."},
    "level": {"type": "string", "description": "The active level (name or GlobalId)."},
    "plan": {"type": "boolean", "description": "A plan view (true) or the 3D view (false)."},
    "cut": {"type": "number", "description": "Plan cut height above the level, in project units; omit for no cut."},
    "cut_planes": {"type": "array", "items": _PLANE, "description": "3D cut planes (Archicad's 3D Cutaway)."},
    "hidden_layers": {"type": "array", "items": {"type": "string"}},
    "lines_only": {"type": "boolean"}, "white_model": {"type": "boolean"}, "shadows": {"type": "boolean"},
    "purpose": {"type": "string", "description": "A purpose (graphics.state lists them)."}}}, writes=True)
def views_save(session, name, capture=False, level="", plan=None, cut=None, cut_planes=None, hidden_layers=None,
               lines_only=None, white_model=None, shadows=None, purpose=""):
    """Save a named view: the level, plan or 3D, the plan cut, 3D cut planes, hidden layers and style."""
    if not name.strip():
        raise AgentError("bad_input", hint="a view needs a name")
    if capture:
        _app_view(session, {"action": "save", "name": name.strip()})
        return {"name": name.strip(), "captured": True}
    data: dict = {"hidden": list(hidden_layers or []), "locked": []}
    if level:
        data["level"] = level_guid(level)
    if plan is not None:
        data["plan"] = bool(plan)
    data["cut"] = lengths(session, cut)[0] if cut is not None else None  # None: the plan cut is off
    planes = []
    for i, p in enumerate(cut_planes or []):
        if len(p["point"]) != 3 or len(p["normal"]) != 3 or not any(p["normal"]):
            raise AgentError("bad_input", hint=f"cut_planes[{i}]: point and normal must be [x, y, z], normal not zero")
        planes.append({"name": p.get("name") or f"Cut {i + 1}", "enabled": p.get("enabled", True), "visible": True,
                       "point": lengths(session, *p["point"]), **_plane_frame(p["normal"])})
    data["planes"] = planes
    for key, value in (("linesOnly", lines_only), ("whiteModel", white_model), ("shadows", shadows)):
        if value is not None:
            data[key] = bool(value)
    if purpose:
        data["purpose"] = purpose
    bridge(LY.save_view, name.strip(), json.dumps(data))
    return {"name": name.strip(), "captured": False}


@tool("views.apply", {"required": ["name"], "properties": {"name": {"type": "string"}}}, writes=True,
      needs_task=False)
def views_apply(session, name):
    """Show a saved view in the app (its level, cuts, layers and style). It also makes the view's purpose and
    layer states the project's current ones, as the app's own Views menu does. Needs the app."""
    if not any(v["name"] == name for v in bridge(LY.views)["views"]):
        raise AgentError("not_found", what=name)
    _app_view(session, {"action": "apply", "name": name})
    return {"name": name}


@tool("views.delete", {"required": ["name"], "properties": {"name": {"type": "string"}}}, writes=True)
def views_delete(session, name):
    """Delete a saved view."""
    bridge(LY.delete_view, name)
    return {"name": name}


@tool("view.hide", {"required": ["elements"], "properties": {"elements": SELECTOR}})
def view_hide(session, elements):
    """Hide elements in the app's view (display only: the model does not change). Needs the app."""
    guids = _guids(session, elements)
    _app_view(session, {"action": "hide", "elements": guids})
    return {"hidden": len(guids)}


@tool("view.isolate", {"required": ["elements"], "properties": {"elements": SELECTOR}})
def view_isolate(session, elements):
    """Show only these elements in the app's view (display only). Needs the app."""
    guids = _guids(session, elements)
    _app_view(session, {"action": "isolate", "elements": guids})
    return {"shown": len(guids)}


@tool("view.show_all", {})
def view_show_all(session):
    """Show every element again in the app's view. Needs the app."""
    _app_view(session, {"action": "show_all"})
    return {}


@tool("view.zoom", {"properties": {"elements": SELECTOR}})
def view_zoom(session, elements=None):
    """Zoom the app's view to these elements, or to the whole model when none are given. Needs the app."""
    guids = _guids(session, elements) if elements is not None else []
    _app_view(session, {"action": "fit", "elements": guids})
    return {"elements": len(guids)}


# ---------------------------------------------------------------- measure (read-only)

@tool("measure.points", {"required": ["points"], "properties": {
    "points": {"type": "array", "items": {"type": "array"},
               "description": "[[x, y] or [x, y, z], ...] in project units (or strings with units)."},
    "closed": {"type": "boolean", "description": "Treat the points as a closed outline: also give its plan area "
                                                "and perimeter (default false)."}}})
def measure_points(session, points, closed=False):
    """Measure through points like the Measure tool: each segment, the total length, the 3D distance between
    the first and last point and, for a closed outline, its plan area and perimeter (metres)."""
    if len(points) < 2:
        raise AgentError("bad_input", hint="give at least two points")
    pts = []
    for i, p in enumerate(points):
        if not isinstance(p, list) or len(p) not in (2, 3):
            raise AgentError("bad_input", hint=f"points[{i}] must be [x, y] or [x, y, z]")
        v = lengths(session, *p)
        pts.append((v[0], v[1], v[2] if len(v) == 3 else 0.0))
    seg = [sum((a - b) ** 2 for a, b in zip(pts[i], pts[i + 1])) ** 0.5 for i in range(len(pts) - 1)]
    out = {"segments": [round(s, 6) for s in seg], "length": round(sum(seg), 6),
           "distance": round(sum((a - b) ** 2 for a, b in zip(pts[0], pts[-1])) ** 0.5, 6), "unit": "m"}
    if closed:
        if len(pts) < 3:
            raise AgentError("bad_input", hint="a closed outline needs at least three points")
        twice = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                    for i in range(len(pts)))
        closing = sum((a - b) ** 2 for a, b in zip(pts[-1][:2], pts[0][:2])) ** 0.5
        out["area"] = round(abs(twice) / 2, 6)
        out["perimeter"] = round(sum(((pts[i][0] - pts[i + 1][0]) ** 2 + (pts[i][1] - pts[i + 1][1]) ** 2) ** 0.5
                                     for i in range(len(pts) - 1)) + closing, 6)
    return out
