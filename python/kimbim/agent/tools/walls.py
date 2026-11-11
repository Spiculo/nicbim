# SPDX-License-Identifier: GPL-3.0-or-later
"""Wall configuration tools (doc 18 §6 item 1, D97): reference line, slant, top link, complex profiles, flip,
junctions and surface overrides. Each write is one undo step and regenerates the walls joined to the ones
changed."""
from __future__ import annotations

import json

from ... import configure as CF
from ..catalogue import SELECTOR, AgentError, bridge, tool


def _setting(session, elements, group: str, name: str, value) -> dict:
    guids = session.resolve(elements)
    if not guids:
        raise AgentError("no_match")
    return _result(bridge(CF.set_element_setting, json.dumps(guids), group, name, value))


def _result(r: dict, key: str = "changed") -> dict:
    """A bridge `_run` reply as the count and the GlobalIds whose geometry was rebuilt."""
    return {key: int(r.get("changed", 0)), "guids": list((r.get("geometry") or {}).get("changed", []))}


@tool("walls.options", {})
def options(session):
    """List the choices the wall settings take: reference lines (and the project default), top links,
    wall profiles and the surface sides of walls and slabs."""
    o = bridge(CF.wall_options)
    return {"reference_lines": o["references"], "default_reference_line": o["default"],
            "top_links": list(CF.TOP_LINKS), "profiles": sorted(CF.profiles()),
            "wall_sides": list(CF.WALL_SIDES), "slab_sides": list(CF.SLAB_SIDES),
            "other_sides": list(CF.ALL_SIDES)}


@tool("walls.configure", {"required": ["elements"], "properties": {
    "elements": SELECTOR,
    "reference_line": {"type": "string", "enum": list(CF.REFERENCES),
                       "description": "Which line of the wall is its drawn line; the line stays, the layers move."},
    "slant": {"type": "number", "minimum": CF.SLANT_MIN, "maximum": CF.SLANT_MAX, "description": "The wall's lean in degrees (90 = upright)."},
    "opposite_slant": {"type": "number", "minimum": CF.SLANT_MIN, "maximum": CF.SLANT_MAX,
                       "description": "The other face's angle; differing from slant makes the wall double slanted."},
    "top_link": {"type": "string", "enum": list(CF.TOP_LINKS),
                 "description": "What the wall's top follows."},
    "top_offset": {"type": "number", "description": "Metres above (or below) the linked top."},
    "profile": {"type": "string", "description": "A wall profile name (walls.options), or \"(none)\" for a "
                                                "plain wall again."}}}, writes=True)
def configure(session, elements, reference_line=None, slant=None, opposite_slant=None, top_link=None,
              top_offset=None, profile=None):
    """Change wall settings: reference line, slant, top link and offset, or a complex profile."""
    steps = [("Reference line", reference_line), ("Slant angle", slant), ("Opposite slant angle", opposite_slant),
             ("Top link", top_link), ("Top offset", top_offset), ("Profile", profile)]
    steps = [(n, v) for n, v in steps if v is not None]
    if not steps:
        raise AgentError("bad_input", hint="give at least one setting")
    out: dict = {"changed": 0, "guids": []}
    for name, value in steps:
        r = _setting(session, elements, CF.GEOMETRY, name, value)
        out["changed"] = max(out["changed"], r["changed"])
        out["guids"] = sorted(set(out["guids"]) | set(r["guids"]))
    return out


@tool("walls.flip", {"required": ["elements"], "properties": {"elements": SELECTOR}}, writes=True)
def flip(session, elements):
    """Mirror layered walls' layers about their reference lines (inside becomes outside)."""
    guids = session.resolve(elements)
    return _result(bridge(CF.flip_walls, json.dumps(guids)))


@tool("walls.set_junctions", {"required": ["elements", "mode"], "properties": {
    "elements": SELECTOR,
    "mode": {"type": "string", "enum": list(CF.JUNCTIONS),
             "description": "through: these walls' layers run through at their joins; butt: they stop; "
                            "materials: the layer priorities decide."}}}, writes=True)
def set_junctions(session, elements, mode):
    """Override how walls meet at their joins: run through, butt, or by material priority."""
    guids = session.resolve(elements)
    return _result(bridge(CF.set_junctions, json.dumps(guids), mode), "joins")


@tool("walls.save_profile", {"required": ["shape", "name"], "properties": {
    "shape": {"type": "string", "description": "GlobalId of a closed polyline, rectangle or fill drawn as the "
                                               "section: its lowest left corner is the wall's base on its "
                                               "reference line, x across the wall, y up."},
    "name": {"type": "string", "description": "The profile name walls.configure uses."}}}, writes=True)
def save_profile(session, shape, name):
    """Save a closed 2D shape as a named wall profile (a project setting)."""
    r = bridge(CF.save_wall_profile, shape, name)
    return {"name": r["name"], "points": r.get("points", [])}


@tool("elements.set_surface", {"required": ["elements", "side"], "properties": {
    "elements": SELECTOR,
    "side": {"type": "string", "description": "Reference side, Opposite side or Edges (walls); Top, Bottom or "
                                              "Edges (slabs, roofs); All faces (anything else)."},
    "surface": {"type": "string", "description": "A surface name (attributes.catalogue lists them); \"\" goes "
                                                 "back to the building material's surface."}}}, writes=True)
def set_surface(session, elements, side, surface=""):
    """Override the surface (3D colour and texture) of one side of the elements."""
    return _setting(session, elements, CF.SURFACES, side, surface)
