# SPDX-License-Identifier: GPL-3.0-or-later
"""Drafting and annotation tools (D102): lines, polylines, arcs, circles, rectangles, fills, text,
dimensions, marks, leaders, tags and the symbol pack. Each write is one undo step."""
from __future__ import annotations

import json

from ... import annotations as N
from ... import drafting as D
from ... import symbols as S
from ... import tags as T
from ..catalogue import AgentError, bridge, tool
from .common import lengths, level_guid, point

_POINT = {"type": "array", "items": {"type": ["number", "string"]},
          "description": "[x, y] in project units or strings with units."}
_POINTS = {"type": "array", "items": _POINT, "description": "World points in project units or strings with units."}
_LEVEL = {"type": "string", "description": "Level name or GlobalId."}
_PEN = {"type": "integer", "description": "Pen number (default the current pen)."}
_LINE_TYPE = {"type": "string", "description": "Line type name (default Solid)."}
_PATTERN = {"type": "string", "description": "Fill pattern name (default Solid)."}


@tool("draft.add", {"required": ["level", "kind", "points"], "properties": {
    "level": _LEVEL,
    "kind": {"type": "string", "enum": ["line", "polyline", "arc", "circle", "rectangle", "fill", "spline"],
             "description": "spline: a smooth curve through the points."},
    "points": _POINTS,
    "closed": {"type": "boolean", "description": "Polyline or spline: close it (default false)."},
    "pen": _PEN, "line_type": _LINE_TYPE,
    "pattern": {**_PATTERN, "description": "Fill: pattern name (default Solid)."},
    "background_pen": {"type": "integer", "description": "Fill: background pen, 0 for none."},
    "show_area": {"type": "boolean", "description": "Fill: show the area as text."}}}, writes=True)
def add(session, level, kind, points, closed=False, pen=None, line_type="", pattern="",
        background_pen=None, show_area=False):
    """Draw a line, polyline, arc, circle, rectangle, fill or spline on a level."""
    path = [list(point(session, p, "points")) for p in points]
    options = {}
    if closed:
        options["closed"] = True
    if pen is not None:
        options["pen"] = int(pen)
    if line_type:
        options["line_type"] = line_type
    if kind == "fill":
        options["pattern"] = pattern or "Solid"
        options["background_pen"] = int(background_pen or 0)
        options["show_area"] = bool(show_area)
    r = bridge(D.add_drafting, level_guid(level), kind, json.dumps(path), json.dumps(options))
    return {"guids": [r["guid"]] if r.get("guid") else [], "points_m": path}


@tool("draft.fill_from_shape", {"required": ["shape"], "properties": {
    "shape": {"type": "string", "description": "GlobalId of a closed polyline, circle or fill."},
    "pattern": _PATTERN, "show_area": {"type": "boolean"}}}, writes=True)
def fill_from_shape(session, shape, pattern="", show_area=False):
    """Fill a closed shape (a polyline, circle or fill) with a pattern, on the same level."""
    options = {}
    if pattern:
        options["pattern"] = pattern
    if show_area:
        options["show_area"] = True
    r = bridge(D.fill_from_shape, shape, json.dumps(options))
    return {"guids": [r["guid"]] if r.get("guid") else []}


@tool("draft.patterns", {})
def patterns(session):
    """List the fill patterns available to draft fills."""
    return {"patterns": bridge(D.fill_patterns)["patterns"]}


@tool("annotation.add", {"required": ["level", "kind", "points"], "properties": {
    "level": _LEVEL,
    "kind": {"type": "string", "enum": ["text", "dimension", "mark", "leader"]},
    "points": _POINTS,
    "text": {"type": "string", "description": "The text, or a dimension's labels separated by |."},
    "size": {"type": ["number", "string"], "description": "Text size in paper mm (default 2.5)."}}},
    writes=True)
def annotation_add(session, level, kind, points, text="", size=None):
    """Add an annotation: text at a point, a dimension chain, a mark or a leader with text."""
    path = [list(point(session, p, "points")) for p in points]
    r = bridge(N.add_annotation, level_guid(level), kind, json.dumps(path), str(text or ""))
    guid = r.get("guid", "")
    if size is not None and guid:
        bridge(N.set_annotation_size, guid, lengths(session, size)[0])
    return {"guids": [guid] if guid else [], "points_m": path}


@tool("annotation.tag", {"required": ["element"], "properties": {
    "element": {"type": "string", "description": "GlobalId of the element to tag."},
    "at": _POINT, "style": {"type": "string", "description": "Tag style name (default the element's kind)."},
    "leader": {"type": "boolean"}, "template": {"type": "string"}}}, writes=True)
def annotation_tag(session, element, at=None, style="", leader=None, template=""):
    """Tag an element with its Mark/size (or a chosen style and template)."""
    options = {}
    if at is not None:
        options["at"] = list(point(session, at, "at"))
    if style:
        options["style"] = style
    if leader is not None:
        options["leader"] = bool(leader)
    if template:
        options["template"] = template
    r = bridge(T.add_tag, element, json.dumps(options))
    return {"guids": [r["guid"]] if r.get("guid") else []}


@tool("annotation.tag_all", {"properties": {
    "level": _LEVEL, "elements": {"type": "array", "items": {"type": "string"}},
    "style": {"type": "string"}, "categories": {"type": "string"}}}, writes=True)
def annotation_tag_all(session, level="", elements=None, style="", categories=""):
    """Tag every untagged door, window and wall on a level (or the given elements)."""
    storey = level_guid(level) if level else ""
    r = bridge(T.tag_all, storey, json.dumps(elements or []), style, categories)
    return {"guids": r.get("guids", []), "count": len(r.get("guids", []))}


@tool("annotation.symbol", {"required": ["level", "kind", "points"], "properties": {
    "level": _LEVEL,
    "kind": {"type": "string", "enum": list(S.KINDS)},
    "points": _POINTS,
    "text": {"type": "string"}, "size": {"type": ["number", "string"]},
    "options": {"type": ["object", "string"],
                "description": "Symbol options: style, shape, leader, scale, auto, pen."}}}, writes=True)
def annotation_symbol(session, level, kind, points, text="", size=None, options=None):
    """Place a tag, north arrow, scale bar, revision cloud, angle/radius/diameter, level or spot symbol."""
    path = [list(point(session, p, "points")) for p in points]
    opts = dict(options) if isinstance(options, dict) else json.loads(options or "{}")
    if text:
        opts["text"] = str(text)
    if size is not None:
        opts["size"] = lengths(session, size)[0]
    r = bridge(S.add_symbol, level_guid(level), kind, json.dumps(path), json.dumps(opts))
    return {"guids": [r["guid"]] if r.get("guid") else [], "points_m": path}


@tool("annotation.auto_dimension", {"required": ["elements"], "properties": {
    "elements": {"type": "array", "items": {"type": "string"}, "description": "GlobalIds to dimension."},
    "offset": {"type": ["number", "string"], "description": "Distance from the elements (default 0.8 m)."}}},
    writes=True)
def auto_dimension(session, elements, offset="0.8m"):
    """Add a dimension chain along a row of aligned elements."""
    r = bridge(N.auto_dimension, json.dumps(list(elements)), lengths(session, offset)[0])
    return {"guids": r.get("guids", [])}


@tool("annotation.overall_dimension", {"required": ["elements"], "properties": {
    "elements": {"type": "array", "items": {"type": "string"}, "description": "GlobalIds to dimension."},
    "offset": {"type": ["number", "string"], "description": "Distance outside the bounds (default 0.8 m)."},
    "axis": {"type": "string", "enum": ["auto", "x", "y"],
             "description": "Which side to measure: x, y or auto (the longer one)."}}}, writes=True)
def overall_dimension(session, elements, offset="0.8m", axis="auto"):
    """Add one overall dimension across the selection's combined plan bounds."""
    r = bridge(N.overall_dimension, json.dumps(list(elements)), lengths(session, offset)[0], axis)
    return {"guids": [r["guid"]], "axis": r.get("axis")}


@tool("annotation.grid_dimension", {"required": ["level"], "properties": {
    "level": _LEVEL,
    "offset": {"type": ["number", "string"], "description": "Distance outside the grid (default 0.8 m)."},
    "axis": {"type": "string", "enum": ["auto", "x", "y"],
             "description": "Which axes to measure: x, y or auto (the one with more axes)."}}}, writes=True)
def grid_dimension(session, level, offset="0.8m", axis="auto"):
    """Add one dimension chain between a level's grid axes."""
    r = bridge(N.grid_dimension, level_guid(level), lengths(session, offset)[0], axis)
    return {"guids": [r["guid"]], "axis": r.get("axis"), "labels": r.get("labels")}
