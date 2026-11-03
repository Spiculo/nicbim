# SPDX-License-Identifier: GPL-3.0-or-later
"""Cost estimating (5D, D213): rates per type name and a bill of quantities.

Quantities come from the element's Qto_ sets when present, else from its geometry (volume), with a
count as the last resort for doors, windows, furniture and similar. Rates are kept in the project's
`cost_rates` setting, so the estimate travels with the model and versions with it.
"""
from __future__ import annotations

import json

import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.shape

from . import app_bridge as B
from . import authoring as A

KEY = "cost_rates"
UNITS = ("m3", "m2", "m", "pcs")
COUNTED = ("IfcDoor", "IfcWindow", "IfcFurniture", "IfcFurnishingElement", "IfcSanitaryTerminal",
           "IfcElectricAppliance", "IfcLightFixture", "IfcBuildingElementProxy", "IfcGeographicElement")


def _stored() -> dict:
    from . import settings as S

    data = S.current().get(KEY, {})
    return dict(data) if isinstance(data, dict) else {}


def _unit_for(element) -> str:
    if element.is_a() in COUNTED:
        return "pcs"
    if element.is_a("IfcSpace"):
        return "m2"
    if element.is_a() in ("IfcWall", "IfcSlab", "IfcRoof", "IfcColumn", "IfcBeam", "IfcStair",
                          "IfcRamp", "IfcCurtainWall"):
        return "m3"
    return "pcs"


def _quantity(element) -> tuple[float, str]:
    """(quantity, unit) of one element: Qto volume, geometry volume or a count."""
    if element.is_a() in COUNTED:
        return 1.0, "pcs"
    psets = ifcopenshell.util.element.get_psets(element, qtos_only=True)
    if element.is_a("IfcSpace"):
        for qto in psets.values():
            for key in ("NetArea", "GrossArea"):
                value = qto.get(key)
                if isinstance(value, (int, float)) and value > 0:
                    return float(value), "m2"
    for qto in psets.values():
        for key in ("NetVolume", "GrossVolume"):
            value = qto.get(key)
            if isinstance(value, (int, float)) and value > 0:
                return float(value), "m3"
    try:
        shape = ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(), element)
        volume = float(ifcopenshell.util.shape.get_volume(shape.geometry))
        if volume > 1e-9:
            return volume, "m3"
    except Exception:
        pass
    for qto in psets.values():
        for key in ("NetArea", "GrossArea"):
            value = qto.get(key)
            if isinstance(value, (int, float)) and value > 0:
                return float(value), "m2"
    return 1.0, _unit_for(element)


def cost_estimate() -> str:
    """{rows: [{type, unit, quantity, rate, cost}], total, types: [{name, unit, rate}]}."""
    if B._model is None:
        return A._fail("no model open")
    table = _stored()
    grouped: dict[tuple[str, str], float] = {}
    for element in B._model.by_type("IfcProduct"):
        kind = element.is_a()
        if kind in ("IfcOpeningElement", "IfcAnnotation", "IfcGrid") or element.is_a("IfcSpatialStructureElement"):
            continue
        element_type = ifcopenshell.util.element.get_type(element)
        name = (element_type.Name if element_type is not None and element_type.Name else element.is_a())
        quantity, unit = _quantity(element)
        grouped[(name, unit)] = grouped.get((name, unit), 0.0) + quantity
    rows, types, total = [], [], 0.0
    for (name, unit), quantity in sorted(grouped.items()):
        rate = float((table.get(name) or {}).get("rate") or 0.0)
        cost = quantity * rate
        rows.append({"type": name, "unit": unit, "quantity": round(quantity, 3), "rate": rate,
                     "cost": round(cost, 2)})
        types.append({"name": name, "unit": unit, "rate": rate})
        total += cost
    return B._dump({"ok": True, "rows": rows, "types": types, "total": round(total, 2)})


def set_cost_rates(changes_json: str) -> str:
    """Set rates from [{type, rate, unit}]; a zero rate removes the entry."""
    from . import settings as S

    try:
        changes = json.loads(changes_json)
    except ValueError as ex:
        return A._fail(f"bad rates: {ex}")
    if not isinstance(changes, list):
        return A._fail("rates are a list of {type, rate, unit}")
    data = _stored()
    for row in changes:
        if not isinstance(row, dict) or not isinstance(row.get("type"), str) or not row["type"].strip():
            return A._fail("every rate needs a type name")
        name = row["type"].strip()
        try:
            rate = float(row.get("rate") or 0.0)
        except (TypeError, ValueError):
            return A._fail(f"{name}: the rate is a number")
        if rate < 0:
            return A._fail(f"{name}: the rate can't be negative")
        unit = row.get("unit") or "pcs"
        if unit not in UNITS:
            return A._fail(f"{name}: unknown unit {unit}")
        if rate == 0:
            data.pop(name, None)
        else:
            data[name] = {"rate": rate, "unit": unit}
    return S.set_project_settings(json.dumps({KEY: data}))
