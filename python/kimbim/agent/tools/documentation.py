# SPDX-License-Identifier: GPL-3.0-or-later
"""Documentation tools (doc 18 §6 item 3): drawing settings, rename and delete; sheet data, title block,
purpose, legends, symbols and schedules on sheets; schedule definitions. Each write is one undo step."""
from __future__ import annotations

import json

from ... import drawings as DR
from ... import schedules as SC
from ... import sheets as SH
from ..catalogue import AgentError, bridge, tool
from .outputs import _DRAWING, _SHEET, _drawing_guid, _scheme, _sheet_number

_MM = {"type": "number", "description": "Millimetres on the sheet."}
_AT = {"type": "array", "items": {"type": "number"},
       "description": "[x, y] top-left on the sheet in mm; default: a free spot."}


def _at(at) -> tuple[float, float]:
    if at is None:
        return -1.0, -1.0
    if not isinstance(at, list) or len(at) != 2:
        raise AgentError("bad_input", hint="at must be [x, y] in mm")
    return float(at[0]), float(at[1])


# ---------------------------------------------------------------- drawings

@tool("drawings.rename", {"required": ["drawing", "name"], "properties": {
    "drawing": _DRAWING, "name": {"type": "string", "description": "The new name."}}}, writes=True)
def drawings_rename(session, drawing, name):
    """Rename a drawing; its markers and the sheets it is placed on show the new name."""
    guid = _drawing_guid(drawing)
    bridge(DR.rename_drawing, guid, name)
    return {"guid": guid, "name": name.strip()}


@tool("drawings.delete", {"required": ["drawing"], "properties": {"drawing": _DRAWING}}, writes=True)
def drawings_delete(session, drawing):
    """Delete a drawing and its marker; it is also taken off every sheet it was placed on."""
    guid = _drawing_guid(drawing)
    bridge(DR.delete_drawing, guid)
    return {"guid": guid}


@tool("drawings.set_view", {"required": ["drawing"], "properties": {
    "drawing": _DRAWING,
    "depth": {"type": "number", "description": "How far the view looks past the cut, in metres: < 0 for "
                                               "infinite, 0 for the cut only."},
    "tilt": {"type": "number", "minimum": -88.9, "maximum": 88.9,
             "description": "Section/elevation: the cut plane's angle about the marker line in degrees "
                            "(0 = vertical)."},
    "base": {"type": "number", "description": "Section/elevation: the height of the marker line in metres "
                                              "(the pivot of a tilted cut)."},
    "crop": {"type": "array", "items": {"type": "number"},
             "description": "[x0, y0, x1, y1] in paper mm crops the view; [0, 0, 0, 0] clears the crop."}}},
    writes=True)
def drawings_set_view(session, drawing, depth=None, tilt=None, base=None, crop=None):
    """Change a drawing's view: its depth, a section's tilt and base height, or its crop rectangle."""
    guid = _drawing_guid(drawing)
    if depth is None and tilt is None and base is None and crop is None:
        raise AgentError("bad_input", hint="give at least one of depth, tilt, base, crop")
    if crop is not None and len(crop) != 4:
        raise AgentError("bad_input", hint="crop must be [x0, y0, x1, y1] in mm")
    if depth is not None:
        guid = bridge(DR.set_drawing_depth, guid, float(depth)).get("guid", guid)
    if tilt is not None:
        guid = bridge(DR.set_drawing_tilt, guid, float(tilt)).get("guid", guid)
    if base is not None:
        guid = bridge(DR.set_drawing_base, guid, float(base)).get("guid", guid)
    if crop is not None:
        guid = bridge(DR.set_drawing_crop, guid, *[float(v) for v in crop]).get("guid", guid)
    return {"guid": guid}


# ---------------------------------------------------------------- sheets

@tool("sheets.get", {"required": ["sheet"], "properties": {"sheet": _SHEET}})
def sheets_get(session, sheet):
    """Describe one sheet: its drawings, legends, symbols, title block fields and placed tables."""
    number = _sheet_number(sheet)
    s = next(x for x in bridge(SH.sheets)["sheets"] if x["number"] == number)
    tables = bridge(SH.sheet_schedules, number)
    keep = ("number", "title", "paper", "views", "legends", "symbols", "title_block")
    return {**{k: s[k] for k in keep if k in s}, "schedules": tables.get("schedules", []),
            "lists": tables.get("lists", [])}


@tool("sheets.update", {"required": ["sheet"], "properties": {
    "sheet": _SHEET,
    "title": {"type": "string"},
    "number": {"type": "string", "description": "A new sheet number; it must be free."},
    "paper": {"type": "string", "description": "Paper size, e.g. A1, A3, ARCH D (sheets.papers lists them)."}}},
    writes=True)
def sheets_update(session, sheet, title=None, number=None, paper=None):
    """Change a sheet's title, number or paper size."""
    current = _sheet_number(sheet)
    changes = {k: v for k, v in (("title", title), ("number", number), ("paper", paper)) if v is not None}
    if not changes:
        raise AgentError("bad_input", hint="give at least one of title, number, paper")
    bridge(SH.edit_sheet, current, json.dumps(changes))
    return {"sheet": changes.get("number", current)}


@tool("sheets.papers", {})
def sheets_papers(session):
    """List the paper sizes a sheet can use, with their width and height in mm."""
    return bridge(SH.papers)


@tool("sheets.delete", {"required": ["sheet"], "properties": {"sheet": _SHEET}}, writes=True)
def sheets_delete(session, sheet):
    """Delete a sheet; the drawings placed on it are kept."""
    number = _sheet_number(sheet)
    bridge(SH.delete_sheet, number)
    return {"sheet": number}


@tool("sheets.set_title_block", {"required": ["sheet"], "properties": {
    "sheet": _SHEET,
    "fields": {"type": "object", "additionalProperties": False,
               "properties": {f: {"type": "string"} for f in SH.TITLE_FIELDS},
               "description": "Title block fields to override, e.g. {\"issued\": \"For permit\"}; a value "
                              "equal to the one the sheet derives drops the override."},
    "at": {"type": "array", "items": {"type": "number"}, "description": "[x, y] top-left in mm to move it to."}}},
    writes=True)
def sheets_set_title_block(session, sheet, fields=None, at=None):
    """Edit a sheet's title block fields or move the title block."""
    number = _sheet_number(sheet)
    changes: dict = {}
    if fields:
        changes["fields"] = {str(k): str(v) for k, v in fields.items()}
    if at is not None:
        changes["x"], changes["y"] = _at(at)
    if not changes:
        raise AgentError("bad_input", hint="give fields or at")
    bridge(SH.set_title_block, number, json.dumps(changes))
    return {"sheet": number}


@tool("sheets.set_purpose", {"required": ["sheet", "purpose"], "properties": {
    "sheet": _SHEET,
    "purpose": {"type": "string", "description": "A purpose name (graphics.state lists them); \"\" for the "
                                                 "project's current one."}}}, writes=True)
def sheets_set_purpose(session, sheet, purpose):
    """Set the purpose (pen set, styles, renovation filter) a sheet prints with."""
    number = _sheet_number(sheet)
    bridge(SH.set_sheet_purpose, number, purpose)
    return {"sheet": number, "purpose": purpose}


@tool("sheets.place_legend", {"required": ["sheet"], "properties": {"sheet": _SHEET}}, writes=True)
def sheets_place_legend(session, sheet):
    """Place the legend of the sheet's purpose (renovation statuses, fills) at a free spot."""
    number = _sheet_number(sheet)
    return {"sheet": number, "id": bridge(SH.place_legend, number)["id"]}


@tool("sheets.place_symbol", {"required": ["sheet", "kind"], "properties": {
    "sheet": _SHEET,
    "kind": {"type": "string", "enum": ["north", "scalebar", "cloud", "text"],
             "description": "north arrow, scale bar, revision cloud or sheet text."},
    "at": _AT,
    "text": {"type": "string", "description": "cloud: its label; text: what it says (required)."},
    "size": {"type": "number", "minimum": 0.5, "description": "text: height in mm (default 3.5)."},
    "width": _MM, "height": _MM,
    "drawing": {**_DRAWING, "description": "scalebar: the drawing whose scale it shows (default the first)."}}},
    writes=True)
def sheets_place_symbol(session, sheet, kind, at=None, text=None, size=None, width=None, height=None,
                        drawing=None):
    """Place a north arrow, scale bar, revision cloud or a text on a sheet."""
    number = _sheet_number(sheet)
    options: dict = {}
    if at is not None:
        options["x"], options["y"] = _at(at)
    if text is not None:
        options["text"] = text
    if size is not None:
        options["size"] = float(size)
    if width is not None:
        options["w"] = float(width)
    if height is not None:
        options["h"] = float(height)
    if drawing:
        options["drawing"] = _drawing_guid(drawing)
    return {"sheet": number, "id": bridge(SH.place_sheet_symbol, number, kind, json.dumps(options))["id"]}


@tool("sheets.remove_item", {"required": ["sheet", "item"], "properties": {
    "sheet": _SHEET,
    "item": {"type": "string", "enum": ["legend", "symbol", "schedule"]},
    "id": {"type": "string", "description": "legend/symbol: the id sheets.get lists."},
    "index": {"type": "integer", "minimum": 0, "description": "schedule: its index in sheets.get's schedules."}}},
    writes=True)
def sheets_remove_item(session, sheet, item, id="", index=None):
    """Take a legend, symbol or schedule table off a sheet."""
    number = _sheet_number(sheet)
    if item == "schedule":
        if index is None:
            raise AgentError("bad_input", hint="a schedule is removed by index")
        bridge(SH.remove_schedule, number, int(index))
    else:
        if not id:
            raise AgentError("bad_input", hint=f"a {item} is removed by id")
        bridge(SH.remove_legend if item == "legend" else SH.remove_sheet_symbol, number, id)
    return {"sheet": number}


@tool("sheets.place_schedule", {"required": ["sheet", "schedule"], "properties": {
    "sheet": _SHEET,
    "schedule": {"type": "string", "description": "Schedule id or name (schedules.list lists them)."},
    "at": _AT,
    "width": {"type": "number", "minimum": 20, "description": "Table width in mm (default 180)."}}}, writes=True)
def sheets_place_schedule(session, sheet, schedule, at=None, width=180):
    """Place a schedule table on a sheet; it prints with the sheet and updates with the model."""
    number = _sheet_number(sheet)
    x, y = _at(at)
    r = bridge(SH.place_schedule, number, _scheme(schedule)["id"], x, y, float(width))
    return {"sheet": number, "index": r["index"]}


# ---------------------------------------------------------------- schedule definitions

_FIELD = {"type": "object", "required": ["source", "name"], "properties": {
    "source": {"type": "string", "enum": ["attribute", "info", "quantity", "property", "formula"]},
    "name": {"type": "string", "description": "The attribute, info field, quantity or property name; for a "
                                              "formula, the expression."},
    "pset": {"type": "string", "description": "property: its property set."},
    "label": {"type": "string", "description": "Column heading (optional)."}}}


@tool("schedules.fields", {"required": ["classes"], "properties": {
    "classes": {"type": "array", "items": {"type": "string"}, "description": "IFC classes, e.g. [\"IfcDoor\"]."}}})
def schedules_fields(session, classes):
    """List the fields a schedule of these IFC classes can show: attributes, info, quantities and properties."""
    return bridge(SC.schedule_fields, json.dumps(list(classes)))


@tool("schedules.save", {"required": ["name", "classes", "fields"], "properties": {
    "id": {"type": "string", "description": "An existing schedule's id to change; omit for a new one."},
    "name": {"type": "string"},
    "classes": {"type": "array", "items": {"type": "string"}, "description": "IFC classes it lists."},
    "fields": {"type": "array", "items": _FIELD, "description": "Its columns in order (schedules.fields)."},
    "group_by": {"type": "array", "items": {"type": "string"},
                 "description": "Field keys whose equal values share a row, \"source:name\" (e.g. "
                                "\"info:type\", \"quantity:width\", \"property:Pset_DoorCommon:FireRating\")."},
    "unit": {"type": "string", "enum": ["m", "mm", "cm"], "description": "Length unit of its columns."}}},
    writes=True)
def schedules_save(session, name, classes, fields, id="", group_by=None, unit=None):
    """Create or change a schedule definition (stored in the project settings)."""
    scheme: dict = {"name": name, "classes": list(classes), "fields": [dict(f) for f in fields]}
    if id:
        scheme["id"] = _scheme(id)["id"]
    if group_by is not None:
        scheme["group_by"] = list(group_by)
    if unit is not None:
        scheme["unit"] = unit
    return {"id": bridge(SC.save_schedule_scheme, json.dumps(scheme))["id"]}


@tool("schedules.delete", {"required": ["schedule"], "properties": {
    "schedule": {"type": "string", "description": "Schedule id or name."}}}, writes=True)
def schedules_delete(session, schedule):
    """Delete a custom schedule, or reset a built-in one to its default definition."""
    sid = _scheme(schedule)["id"]
    bridge(SC.delete_schedule_scheme, sid)
    return {"id": sid}
