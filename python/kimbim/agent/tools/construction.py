# SPDX-License-Identifier: GPL-3.0-or-later
"""Construction tools (D102): roofs, stairs, ramps, railings, grids, slab openings and wall heights.
They call the modelling engines; each write is one undo step and lengths go through units.parse_length."""
from __future__ import annotations

import json
import math

from ... import authoring as A
from ... import roofs as R
from ... import stairs as ST
from ..catalogue import SELECTOR, AgentError, bridge, tool
from .common import lengths, level_guid, point
from .create import _level_height, _level_info

_LENGTH = {"type": ["number", "string"], "description": "Project units or a string with units (\"50cm\")."}
_POINT = {"type": "array", "items": _LENGTH, "description": "[x, y] in project units or strings with units."}
_LEVEL = {"type": "string", "description": "Level name or GlobalId."}
_ANGLE = {"type": ["number", "string"], "description": "Degrees or a string with a unit (\"90deg\", \"1.57rad\")."}


def _angle(session, value) -> float:
    from .. import units

    try:
        return units.parse_angle(value)
    except ValueError:
        raise AgentError("bad_input", hint=f"bad angle: {value}") from None


def _direction(start, end) -> float:
    return math.atan2(end[1] - start[1], end[0] - start[0])


@tool("create.ceiling", {"required": ["level", "points"], "properties": {
    "level": _LEVEL, "points": {"type": "array", "items": _POINT,
                                 "description": "The ceiling outline, at least three points."},
    "thickness": {**_LENGTH, "description": "Ceiling thickness (default 20 cm)."},
    "offset": {**_LENGTH, "description": "Underside above the level (default 2.7 m)."},
    "name": {"type": "string"}}}, writes=True)
def ceiling(session, level, points, thickness="20cm", offset="2.7m", name="Ceiling"):
    """Create an IfcCovering CEILING over an outline at a height above a level."""
    outline = [list(point(session, p, "points")) for p in points]
    if len(outline) < 3:
        raise AgentError("bad_input", hint="a ceiling needs at least three points")
    r = bridge(A.create_ceiling, level_guid(level), json.dumps(outline),
               lengths(session, thickness)[0], lengths(session, offset)[0], name or "Ceiling")
    return {"guids": [r["guid"]], "points_m": outline}


@tool("create.ceiling_from_selection", {"required": ["elements"], "properties": {
    "elements": SELECTOR,
    "thickness": {**_LENGTH, "description": "Ceiling thickness (default 20 cm)."},
    "offset": {**_LENGTH, "description": "Underside above the level (default 2.7 m)."}}}, writes=True)
def ceiling_from_selection(session, elements, thickness="20cm", offset="2.7m"):
    """Create a ceiling over a selected slab's outline or a closed loop of selected walls."""
    guids = session.resolve(elements)
    r = bridge(A.ceiling_from_selection, json.dumps(guids), lengths(session, thickness)[0],
               lengths(session, offset)[0])
    return {"guids": [r["guid"]]}


@tool("create.roof", {"required": ["level", "points"], "properties": {
    "level": _LEVEL,
    "points": {"type": "array", "items": _POINT, "description": "The eaves outline, at least three points."},
    "kind": {"type": "string", "enum": ["flat", "shed", "gable", "hip"], "description": "Roof shape (default flat)."},
    "pitch": {"type": ["number", "string"], "description": "Slope in degrees (default 30)."},
    "thickness": {**_LENGTH, "description": "Roof build-up (default 20cm)."},
    "offset": {**_LENGTH, "description": "Underside at the eaves above the level (default 0)."},
    "slopes": {"type": "array", "items": {"type": ["number", "null"]},
               "description": "Per-edge slopes in degrees for a custom roof (optional)."}}},
    writes=True)
def roof(session, level, points, kind="flat", pitch=30, thickness="20cm", offset=0, slopes=None):
    """Create a roof from an eaves outline: flat, shed, gable or hip, with its pitch and thickness."""
    outline = [list(point(session, p, "points")) for p in points]
    if len(outline) < 3:
        raise AgentError("bad_input", hint="a roof needs at least three points")
    r = bridge(R.create_roof, level_guid(level), json.dumps(outline), kind,
               _angle(session, pitch), lengths(session, thickness)[0], lengths(session, offset)[0],
               json.dumps(slopes) if slopes is not None else "")
    return {"guids": [r["guid"]], "kind": kind, "points_m": outline}


@tool("create.stair", {"required": ["level", "start", "end"], "properties": {
    "level": _LEVEL, "start": _POINT, "end": _POINT,
    "width": {**_LENGTH, "description": "Flight width (default 1 m)."},
    "height": {**_LENGTH, "description": "Level-to-level height (default the level's height)."},
    "shape": {"type": "string", "enum": ["straight", "L", "U", "sketch"], "description": "Default straight."},
    "turn": {"type": "string", "enum": ["left", "right"]},
    "riser": {**_LENGTH, "description": "Target riser height (default the project setting, 17.5cm)."},
    "tread": {**_LENGTH, "description": "Tread (default the project setting or from 2R+G)."},
    "landing": {**_LENGTH, "description": "Landing depth (0 = the width)."},
    "cut_slab": {"type": "boolean", "description": "Cut an opening in the slab above (default true)."},
    "walking_line": {"type": "array", "items": _POINT,
                     "description": "For shape sketch: the walking line points."}}},
    writes=True)
def stair(session, level, start, end, width="1m", height=None, shape="straight", turn="left",
          riser=None, tread=None, landing=None, cut_slab=True, walking_line=None):
    """Create a stair climbing from start towards end, with landings for L/U or along a walking line."""
    storey = level_guid(level)
    x, y = point(session, start, "start")
    ex, ey = point(session, end, "end")
    h = lengths(session, height)[0] if height is not None else _level_height(_level_info(level))
    options = {"shape": shape, "turn": turn, "cut_slab": bool(cut_slab)}
    if riser is not None:
        options["riser"] = lengths(session, riser)[0]
    if tread is not None:
        options["tread"] = lengths(session, tread)[0]
    if landing is not None:
        options["landing"] = lengths(session, landing)[0]
    if walking_line is not None:
        options["points"] = [list(point(session, p, "walking_line")) for p in walking_line]
    r = bridge(ST.create_stair, storey, x, y, _direction((x, y), (ex, ey)),
               lengths(session, width)[0], h, json.dumps(options))
    return {"guids": [r["guid"]], "height_m": round(h, 6), "risers": r.get("risers"),
            "riser_m": r.get("riser"), "warnings": r.get("warnings", [])}


@tool("create.ramp", {"required": ["level", "start", "end"], "properties": {
    "level": _LEVEL, "start": _POINT, "end": _POINT,
    "width": {**_LENGTH, "description": "Ramp width (default 1 m)."},
    "height": {**_LENGTH, "description": "Rise (default the level's height)."},
    "slope": {"type": ["number", "string"], "description": "Slope in percent (default 8)."},
    "shape": {"type": "string", "enum": ["straight", "L"]},
    "turn": {"type": "string", "enum": ["left", "right"]},
    "landing": {**_LENGTH, "description": "Landing depth (0 = the width)."}}},
    writes=True)
def ramp(session, level, start, end, width="1m", height=None, slope=8, shape="straight",
         turn="left", landing=None):
    """Create a ramp rising from start towards end, straight or L, at a slope in percent."""
    storey = level_guid(level)
    x, y = point(session, start, "start")
    ex, ey = point(session, end, "end")
    h = lengths(session, height)[0] if height is not None else _level_height(_level_info(level))
    options = {"shape": shape, "turn": turn, "slope": float(slope)}
    if landing is not None:
        options["landing"] = lengths(session, landing)[0]
    r = bridge(ST.create_ramp, storey, x, y, _direction((x, y), (ex, ey)),
               lengths(session, width)[0], h, json.dumps(options))
    return {"guids": [r["guid"]], "height_m": round(h, 6), "warnings": r.get("warnings", [])}


@tool("create.railing", {"required": ["level", "points"], "properties": {
    "level": _LEVEL, "points": {"type": "array", "items": _POINT, "description": "The path, at least two points."},
    "height": {**_LENGTH, "description": "Railing height (default 1.1 m)."}}}, writes=True)
def railing(session, level, points, height="1.1m"):
    """Create a railing along a path on a level."""
    path = [list(point(session, p, "points")) for p in points]
    if len(path) < 2:
        raise AgentError("bad_input", hint="a railing needs at least two points")
    r = bridge(ST.create_railing, level_guid(level), json.dumps(path), lengths(session, height)[0])
    return {"guids": [r["guid"]], "points_m": path}


@tool("create.grid", {"required": ["level", "origin"], "properties": {
    "level": _LEVEL, "origin": _POINT, "angle": _ANGLE,
    "across": {"type": "array", "items": _LENGTH, "description": "Distances between the 1, 2, 3... axes."},
    "along": {"type": "array", "items": _LENGTH, "description": "Distances between the A, B, C... axes."},
    "extension": {**_LENGTH, "description": "How far the axes reach past the outermost lines (default 1.5 m)."},
    "across_labels": {"type": "string", "enum": ["numbers", "letters"]},
    "along_labels": {"type": "string", "enum": ["numbers", "letters"]}}}, writes=True)
def grid(session, level, origin, across=None, along=None, angle=0, extension="1.5m",
         across_labels="numbers", along_labels="letters"):
    """Create a rectangular grid system from a corner, with both directions' spacings and labels."""
    x, y = point(session, origin, "origin")
    across = [lengths(session, v)[0] for v in (across or [])]
    along = [lengths(session, v)[0] for v in (along or [])]
    r = bridge(A.add_grid_system, level_guid(level), x, y, _angle(session, angle),
               json.dumps(across), json.dumps(along), lengths(session, extension)[0],
               across_labels, along_labels)
    return {"guid": r.get("guid", ""), "tags": r.get("tags", [])}


@tool("create.grid_axis", {"required": ["level", "start", "end"], "properties": {
    "level": _LEVEL, "start": _POINT, "end": _POINT, "tag": {"type": "string"}}}, writes=True)
def grid_axis(session, level, start, end, tag=""):
    """Add one grid line to a level's grid (letters for the near-vertical, numbers for the others)."""
    x1, y1 = point(session, start, "start")
    x2, y2 = point(session, end, "end")
    r = bridge(A.add_grid_axis, level_guid(level), x1, y1, x2, y2, str(tag or ""))
    return {"guids": [r["guid"]] if r.get("guid") else []}


@tool("create.slab_opening", {"required": ["slab", "points"], "properties": {
    "slab": {"type": "string", "description": "GlobalId of the slab."},
    "points": {"type": "array", "items": _POINT, "description": "The hole's outline."}}}, writes=True)
def slab_opening(session, slab, points):
    """Cut a hole through a slab with the given outline."""
    outline = [list(point(session, p, "points")) for p in points]
    if len(outline) < 3:
        raise AgentError("bad_input", hint="a slab opening needs at least three points")
    return bridge(A.add_slab_opening, slab, json.dumps(outline))


@tool("create.wall_opening", {"required": ["wall", "along", "width", "height"], "properties": {
    "wall": {"type": "string", "description": "GlobalId of the host wall."},
    "along": {**_LENGTH, "description": "Centre along the wall from its axis start."},
    "width": _LENGTH, "height": _LENGTH,
    "sill": {**_LENGTH, "description": "Bottom above the wall base (default 0)."},
    "name": {"type": "string"}}}, writes=True)
def wall_opening(session, wall, along, width, height, sill="0", name="Wall opening"):
    """Cut a rectangular hole through a wall without a door or window filling it."""
    return bridge(A.create_wall_opening, wall, lengths(session, along)[0], lengths(session, width)[0],
                  lengths(session, height)[0], lengths(session, sill)[0], name or "Wall opening")


@tool("elements.set_wall_height", {"required": ["walls", "height"], "properties": {
    "walls": {"type": "array", "items": {"type": "string"}, "description": "GlobalIds of walls."},
    "height": _LENGTH}}, writes=True)
def set_wall_height(session, walls, height):
    """Set the height of one or more walls (one undo step)."""
    return bridge(A.set_wall_height, json.dumps(list(walls)), lengths(session, height)[0])
