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


_BOX = {"type": "object", "required": ["min", "max"], "additionalProperties": False, "properties": {
    "min": {"type": "array", "items": {"type": ["number", "string"]}, "description": "[x, y, z], project units."},
    "max": {"type": "array", "items": {"type": ["number", "string"]}, "description": "[x, y, z], project units."}},
    "description": "A section box (the app's View > Section box, D217): six cut planes around min..max."}

# D217's six faces, as MainWindow's Section box makes them: name, axis, which end, the face's direction.
_BOX_FACES = (("X min", 0, 0, [0.0, 1.0, 0.0]), ("X max", 0, 1, [0.0, 1.0, 0.0]),
              ("Y min", 1, 0, [1.0, 0.0, 0.0]), ("Y max", 1, 1, [1.0, 0.0, 0.0]),
              ("Z min", 2, 0, [1.0, 0.0, 0.0]), ("Z max", 2, 1, [1.0, 0.0, 0.0]))


def _box(session, box) -> tuple[list[float], list[float]]:
    low, high = lengths(session, *box["min"]), lengths(session, *box["max"])
    if len(low) != 3 or len(high) != 3:
        raise AgentError("bad_input", hint="section_box min and max are [x, y, z]")
    if any(h <= lo for lo, h in zip(low, high)):
        raise AgentError("bad_input", hint="section_box max must be above min on every axis")
    return low, high


def section_box_planes(low, high) -> list[dict]:
    """The six cut planes (in the app's cutPlaneToJson form) of a section box, normals pointing inwards."""
    out = []
    for name, axis, end, direction in _BOX_FACES:
        point = [0.0, 0.0, 0.0]
        point[axis] = (high if end else low)[axis]
        normal = [0.0, 0.0, 0.0]
        normal[axis] = -1.0 if end else 1.0
        out.append({"name": f"Section box: {name}", "enabled": True, "visible": True,
                    "kind": "horizontal" if axis == 2 else "vertical", "point": point, "normal": normal,
                    "direction": direction, "angle": 0.0})
    return out


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
    "section_box": _BOX,
    "hidden_layers": {"type": "array", "items": {"type": "string"}},
    "lines_only": {"type": "boolean"}, "white_model": {"type": "boolean"}, "shadows": {"type": "boolean"},
    "purpose": {"type": "string", "description": "A purpose (graphics.state lists them)."}}}, writes=True)
def views_save(session, name, capture=False, level="", plan=None, cut=None, cut_planes=None, section_box=None,
               hidden_layers=None, lines_only=None, white_model=None, shadows=None, purpose=""):
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
    if section_box is not None:
        planes += section_box_planes(*_box(session, section_box))
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


@tool("view.style", {"properties": {
    "lines_only": {"type": "boolean"}, "white_model": {"type": "boolean"}, "sketch": {"type": "boolean"},
    "xray": {"type": "boolean"}, "shadows": {"type": "boolean"},
    "perspective": {"type": "boolean", "description": "3D views only (plans stay parallel)."}}})
def view_style(session, lines_only=None, white_model=None, sketch=None, xray=None, shadows=None, perspective=None):
    """Switch the app's view modes as the View menu does: lines only, white model, sketch style, x-ray, sun shadows
    and perspective. Only the modes given change (display only). Needs the app."""
    modes = {k: bool(v) for k, v in (("lines_only", lines_only), ("white_model", white_model), ("sketch", sketch),
                                     ("xray", xray), ("shadows", shadows), ("perspective", perspective))
             if v is not None}
    if not modes:
        raise AgentError("bad_input", hint="give at least one mode")
    _app_view(session, {"action": "style", **modes})
    return modes


@tool("view.camera", {"required": ["eye", "target"], "properties": {
    "eye": {"type": "array", "items": {"type": ["number", "string"]}, "description": "[x, y, z], project units."},
    "target": {"type": "array", "items": {"type": ["number", "string"]}, "description": "[x, y, z] it looks at."},
    "fov": {"type": "number", "minimum": 1, "maximum": 170, "description": "Degrees (default 60)."}}})
def view_camera(session, eye, target, fov=60):
    """Put the app's 3D view camera at `eye` looking at `target`, in perspective (display only). Needs the app."""
    e, t = lengths(session, *eye), lengths(session, *target)
    if len(e) != 3 or len(t) != 3 or e == t:
        raise AgentError("bad_input", hint="eye and target are different [x, y, z] points")
    _app_view(session, {"action": "camera", "eye": e, "target": t, "up": [0.0, 0.0, 1.0], "fov": float(fov)})
    return {"eye_m": e, "target_m": t, "fov": float(fov)}


@tool("view.trace", {"required": ["mode"], "properties": {
    "mode": {"type": "string", "enum": ["off", "below", "above"]}}})
def view_trace(session, mode):
    """Trace reference in the app's plan view (Archicad's Trace & Reference): show the plan of the level below or
    above faintly under the active one, or turn it off (display only). Needs the app."""
    _app_view(session, {"action": "trace", "mode": "" if mode == "off" else mode})
    return {"mode": mode}


@tool("view.section_box", {"properties": {
    "elements": {**SELECTOR, "description": "Draw the box around these elements (10 cm margin)."},
    "box": {**_BOX, "description": "Or an explicit box."},
    "off": {"type": "boolean", "description": "Remove the section box."}}})
def view_section_box(session, elements=None, box=None, off=False):
    """Cut the app's 3D view to a section box (D217: six cut planes with drag handles) around elements or an
    explicit box, or remove it (display only; views.save keeps a box with `section_box`). Needs the app."""
    if sum(x is not None and x is not False for x in (elements, box, off or None)) != 1:
        raise AgentError("bad_input", hint="give one of elements, box or off")
    if off:
        _app_view(session, {"action": "section_box", "off": True})
        return {"off": True}
    if box is not None:
        low, high = _box(session, box)
        _app_view(session, {"action": "section_box", "min": low, "max": high})
        return {"min_m": low, "max_m": high}
    guids = _guids(session, elements)
    _app_view(session, {"action": "section_box", "elements": guids})
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
