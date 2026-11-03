# SPDX-License-Identifier: GPL-3.0-or-later
"""Early-stage energy and daylight estimate (D222).

A steady-state estimate for comparing options, not a compliance calculation or a dynamic
simulation: envelope areas and rooms come from the model, and U-values, air changes, degree days,
lighting power and occupancy hours come from the `energy_settings` project setting. The daylight
figure is a crude average daylight factor (glazing area x visible transmittance x 0.5 sky factor
over floor area). Results are per level plus a total, so a change of window or wall build-up can
be compared before a full simulation is justified.
"""
from __future__ import annotations

import json

import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.shape
import ifcopenshell.util.unit

from . import app_bridge as B
from . import authoring as A
from . import rooms as R
from . import settings as S


def _inputs() -> dict:
    stored = S.current().get("energy_settings") or {}
    out = {k: float(v) for k, v in S.DEFAULTS["energy_settings"].items()}
    for key in out:
        value = stored.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[key] = float(value)
    return out


def _area_scale() -> float:
    return ifcopenshell.util.unit.calculate_unit_scale(B._model, "AREAUNIT")


def _volume_scale() -> float:
    return ifcopenshell.util.unit.calculate_unit_scale(B._model, "VOLUMEUNIT")


def _qto(element) -> dict:
    values: dict = {}
    for qto in ifcopenshell.util.element.get_psets(element, qtos_only=True).values():
        values.update(qto)
    return values


def _quantity_area(element, keys) -> float | None:
    qto = _qto(element)
    for key in keys:
        value = qto.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return float(value) * _area_scale()
    return None


def _shape_area(element, getter) -> float:
    try:
        shape = ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(), element)
        return max(0.0, float(getter(shape.geometry))) * _area_scale()
    except Exception:  # noqa: BLE001 - an element without a usable shape
        return 0.0


def _wall_area(element) -> float:
    value = _quantity_area(element, ("NetSideArea", "GrossSideArea"))
    return value if value is not None else _shape_area(element, ifcopenshell.util.shape.get_max_side_area)


def _window_area(element) -> float:
    value = _quantity_area(element, ("Area", "GrossArea"))
    if value is not None:
        return value
    width, height = getattr(element, "OverallWidth", None), getattr(element, "OverallHeight", None)
    if width and height:
        s = A._scale()
        return float(width) * s * float(height) * s
    return _shape_area(element, ifcopenshell.util.shape.get_outer_surface_area) / 2.0


def _floor_like_area(element) -> float:
    value = _quantity_area(element, ("GrossArea", "NetArea"))
    return value if value is not None else _shape_area(element, ifcopenshell.util.shape.get_footprint_area)


def _storey_of(element):
    container = ifcopenshell.util.element.get_container(element)
    if container is None:  # rooms are aggregated to the storey, not contained in it
        container = ifcopenshell.util.element.get_aggregate(element)
    return container if container is not None and container.is_a("IfcBuildingStorey") else None


def _new_row(storey) -> dict:
    return {"guid": storey.GlobalId, "name": storey.Name or "", "wall_area": 0.0,
            "window_area": 0.0, "roof_area": 0.0, "floor_area": 0.0, "space_area": 0.0,
            "space_volume": 0.0}


def energy_report() -> str:
    """Per-level envelope, heating, lighting and daylight estimates plus the project total."""
    if B._model is None:
        return A._fail("no model open")
    args = _inputs()
    rows: dict[str, dict] = {}
    for storey in B._model.by_type("IfcBuildingStorey"):
        rows[storey.GlobalId] = _new_row(storey)
    for element in B._model.by_type("IfcProduct"):
        storey = _storey_of(element)
        if storey is None or storey.GlobalId not in rows:
            continue
        row = rows[storey.GlobalId]
        if element.is_a("IfcWall"):
            row["wall_area"] += _wall_area(element)
        elif element.is_a("IfcWindow"):
            row["window_area"] += _window_area(element)
        elif element.is_a("IfcRoof"):
            row["roof_area"] += _floor_like_area(element)
        elif element.is_a("IfcSlab"):
            if getattr(element, "PredefinedType", None) == "ROOF":
                row["roof_area"] += _floor_like_area(element)
            else:
                row["floor_area"] += _floor_like_area(element)
        elif element.is_a("IfcSpace"):
            row["space_area"] += _quantity_area(element, ("NetFloorArea", "GrossFloorArea")) or 0.0
            row["space_volume"] += (_qto(element).get("NetVolume") or 0.0) * _volume_scale()
    storey_height = {storey.GlobalId: R._height(storey) for storey in B._model.by_type("IfcBuildingStorey")}
    result = []
    total = {"heating_kwh": 0.0, "lighting_kwh": 0.0, "floor_area": 0.0, "window_area": 0.0,
             "wall_area": 0.0, "roof_area": 0.0, "volume": 0.0}
    for row in rows.values():
        floor = row["space_area"] or row["floor_area"]
        volume = row["space_volume"] or floor * storey_height.get(row["guid"], 3.0)
        ua = (args["wall_u"] * row["wall_area"] + args["roof_u"] * row["roof_area"]
              + args["floor_u"] * floor + args["window_u"] * row["window_area"]
              + 0.33 * args["air_changes"] * volume)  # W/K, ventilation at 0.33 Wh/(m3 K)
        heating = ua * args["heating_degree_days"] * 24.0 / 1000.0
        lighting = args["lighting_power_density"] * floor * args["occupancy_hours"] / 1000.0
        glazing = row["window_area"] / floor if floor > 0 else 0.0
        daylight = (row["window_area"] * args["glazing_transmittance"] * 0.5 / floor * 100.0
                    if floor > 0 else 0.0)
        warnings = []
        if glazing > 0.4:
            warnings.append("glazing is over 40% of the floor area: check overheating and cost")
        if floor > 0 and daylight < 2.0:
            warnings.append("average daylight factor is below 2%: check window sizes")
        result.append({
            "guid": row["guid"], "name": row["name"],
            "floor_area": round(floor, 2), "volume": round(volume, 2),
            "wall_area": round(row["wall_area"], 2), "window_area": round(row["window_area"], 2),
            "roof_area": round(row["roof_area"], 2), "glazing_ratio": round(glazing, 3),
            "heating_kwh": round(heating, 1), "lighting_kwh": round(lighting, 1),
            "daylight_factor": round(daylight, 2), "warnings": warnings})
        for key, value in (("heating_kwh", heating), ("lighting_kwh", lighting),
                           ("floor_area", floor), ("window_area", row["window_area"]),
                           ("wall_area", row["wall_area"]), ("roof_area", row["roof_area"]),
                           ("volume", volume)):
            total[key] += value
    result.sort(key=lambda r: (-(r["floor_area"] or 0.0), r["name"]))
    total = {k: round(v, 2) for k, v in total.items()}
    total["heating_kwh"] = round(total["heating_kwh"], 1)
    total["lighting_kwh"] = round(total["lighting_kwh"], 1)
    return B._dump({"ok": True, "levels": result, "total": total, "inputs": args,
                    "note": "Steady-state early-stage estimate, not a compliance calculation."})


def energy_settings() -> str:
    """The editable U-values and use figures behind the estimate."""
    if B._model is None:
        return A._fail("no model open")
    return B._dump({"ok": True, "settings": _inputs()})


def set_energy_settings(settings_json: str) -> str:
    """Save the estimate's inputs (one undoable settings change)."""
    if B._model is None:
        return A._fail("no model open")
    try:
        data = json.loads(settings_json) if isinstance(settings_json, str) else dict(settings_json)
    except (TypeError, ValueError) as ex:
        return A._fail(f"bad energy settings: {ex}")
    if not isinstance(data, dict):
        return A._fail("the energy settings are a table")
    unknown = [k for k in data if k not in S.DEFAULTS["energy_settings"]]
    if unknown:
        return A._fail(f"unknown energy setting {unknown[0]}")
    merged = {**_inputs(), **data}
    error = S._error("energy_settings", merged)
    if error:
        return A._fail(error)

    def action():
        S.set_project_settings(json.dumps({"energy_settings": merged}))
        return 0, [], []

    try:
        result = B._run_settings(action)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**result, "settings": _inputs()})
