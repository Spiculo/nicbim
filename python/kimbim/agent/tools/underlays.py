# SPDX-License-Identifier: GPL-3.0-or-later
"""Underlay and saved-view tools (doc 18 §6 items 5 and 6). Underlays are DXF, DWG, PDF or image files copied
into the project and drawn under a level's plan (D85, D132), optionally in 3D (`show_3d`); converting one turns
its linework into editable 2D elements (D200). Saved views are the project's named views; applying one moves
the app's camera, which stays the owner's, so the agent can list and delete them but not apply them."""
from __future__ import annotations

import json

from ... import layers as LY
from ... import underlays as U
from ..catalogue import AgentError, bridge, tool
from .common import level_guid, point

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
    "scale": {"type": "number", "minimum": 0.000001},
    "page": {"type": "integer", "minimum": 0, "description": "PDF: which page (0 = first)."},
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
    return {"underlay": bridge(U.add_underlay, path, json.dumps(options))["underlay"]}


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


# ---------------------------------------------------------------- saved views

@tool("views.list", {})
def views_list(session):
    """List the project's saved views by name, with what each stores (camera, cuts, section box, style)."""
    return {"views": bridge(LY.views)["views"]}


@tool("views.delete", {"required": ["name"], "properties": {"name": {"type": "string"}}}, writes=True)
def views_delete(session, name):
    """Delete a saved view."""
    bridge(LY.delete_view, name)
    return {"name": name}
