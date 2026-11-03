# SPDX-License-Identifier: GPL-3.0-or-later
"""Area plans (D182): gross and rentable areas from a level's rooms.

Gross is the union of the rooms' outlines (the slab footprint when the level has slabs), so overlapping
or duplicated rooms count once; rentable is the sum of the rooms' own areas. Both are square metres.
"""
from __future__ import annotations

import json

import ifcopenshell.util.element
from shapely.geometry import Polygon
from shapely.ops import unary_union

from . import app_bridge as B
from . import authoring as A
from . import rooms as R


def _slab_union(storey) -> float:
    from . import editing

    areas = []
    for slab in (e for e in B._model.by_type("IfcSlab") if A._by_guid(e.GlobalId) is not None):
        if ifcopenshell.util.element.get_container(slab) != storey:
            continue
        outline = editing._slab_outline_world(slab)
        if outline:
            polygon = Polygon([(float(x), float(y)) for x, y in outline])
            if polygon.is_valid and polygon.area > 1e-9:
                areas.append(polygon)
    return unary_union(areas).area if areas else 0.0


def massing_report() -> str:
    """D201: massing boxes with their footprint and volume, plus floor area per level."""
    if B._model is None:
        return A._fail("no model open")
    import ifcopenshell.util.element

    levels = sorted(B._model.by_type("IfcBuildingStorey"), key=A._elevation)
    by_level = {s.GlobalId: 0.0 for s in levels}
    boxes = []
    total_area = total_volume = 0.0
    for box in B._model.by_type("IfcBuildingElementProxy"):
        data = ifcopenshell.util.element.get_pset(box, "KIMBIM_Massing") or {}
        if data.get("Role") != "massing":
            continue
        width = float(data.get("Width") or 0.0)
        depth = float(data.get("Depth") or 0.0)
        height = float(data.get("Height") or 0.0)
        footprint = width * depth
        if footprint <= 0 or height <= 0:
            continue
        container = ifcopenshell.util.element.get_container(box)
        base = A._elevation(container) if container is not None else 0.0
        covered = []
        for level in levels:
            z = A._elevation(level)
            if base - 1e-6 <= z < base + height - 1e-6:
                by_level[level.GlobalId] += footprint
                covered.append(level.Name or "")
        boxes.append({"guid": box.GlobalId, "name": box.Name or "", "width": round(width, 3),
                      "depth": round(depth, 3), "height": round(height, 3),
                      "footprint": round(footprint, 3), "volume": round(footprint * height, 3),
                      "levels": covered})
        total_area += footprint * len(covered)
        total_volume += footprint * height
    return B._dump({"ok": True, "boxes": boxes,
                    "levels": [{"guid": s.GlobalId, "name": s.Name or "",
                                "elevation": round(A._elevation(s), 3),
                                "area": round(by_level[s.GlobalId], 3)} for s in levels],
                    "total_area": round(total_area, 3), "total_volume": round(total_volume, 3)})


def area_plan(storey_guid: str) -> str:
    """{gross, rentable, rooms: [{guid, number, name, area}]} for a level, in m²."""
    if B._model is None:
        return A._fail("no model open")
    storey = A._by_guid(storey_guid)
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return A._fail("unknown level")
    items = json.loads(R.rooms(storey_guid)).get("rooms") or []
    polygons = [Polygon([(float(p[0]), float(p[1])) for p in room.get("points") or []]) for room in items]
    polygons = [p for p in polygons if p.is_valid and p.area > 1e-9]
    gross = _slab_union(storey) or (unary_union(polygons).area if polygons else 0.0)
    rentable = sum(float(room.get("area") or 0.0) for room in items)
    return B._dump({"ok": True, "gross": round(gross, 3), "rentable": round(rentable, 3),
                    "rooms": [{"guid": room.get("guid"), "number": room.get("number") or "",
                               "name": room.get("name") or "",
                               "area": round(float(room.get("area") or 0.0), 3)} for room in items]})
