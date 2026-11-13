# SPDX-License-Identifier: GPL-3.0-or-later
"""Engineering settings for the MEP and structural calculations (D242-D247).

Each discipline has one project-settings key (``mep_settings``, ``hvac_settings``,
``plumbing_settings``, ``drainage_settings``, ``electrical_settings``, ``structure_settings``).
The project stores **overrides only**; :func:`get` deep-merges them over the defaults below, so a
project keeps working when a default is tuned. Every value is checked against the default's shape:
numbers stay numbers (in range when :data:`RANGES` gives one), choices stay in :data:`CHOICES`, and
the *open* tables (catalogue entries, materials, use categories...) take new entries shaped like an
existing one.

The defaults follow the codes named in the design (EN 16798-1, EN 806-3, EN 12056-2, IEC 60364-5-52,
EN 1990/1991/1993/1995); each calculation lists them in its report's assumptions.
"""
from __future__ import annotations

import copy
import json

from . import app_bridge as B

DEFAULTS: dict[str, dict] = {
    "mep_settings": {
        "connect_tolerance": 0.005,  # m: ports this close are joined
        "catalogue": {},  # per-kind overrides of mep.CATALOGUE design values (open table)
    },
    "hvac_settings": {
        "method": "en16798",  # en16798 | ach | per_area
        "per_person": 7.0,  # L/s per person (EN 16798-1 cat. II)
        "per_area": 0.7,  # L/s per m2 (low-polluting building)
        "area_per_person": 10.0,  # m2 per person when the room has no occupancy
        "ach": 4.0,  # air changes per hour (method "ach")
        "friction_pa_m": 1.0,  # equal-friction target
        "velocity_main": 6.0,  # m/s
        "velocity_branch": 4.0,
        "velocity_terminal": 2.5,
        "roughness_mm": 0.09,  # galvanised steel
        "k_elbow": 0.3,
        "k_tee_branch": 1.0,
        "k_tee_straight": 0.2,
        "terminal_pa": 25.0,  # pressure loss of a terminal device
        "max_aspect": 4.0,  # rectangular ducts
        "air_density": 1.2,  # kg/m3
        "air_viscosity": 1.5e-5,  # kinematic, m2/s
    },
    "plumbing_settings": {
        "method": "en806",  # en806 | hunter
        "velocity_main": 2.0,  # m/s
        "velocity_branch": 1.5,
        "roughness_mm": 0.0015,  # copper / plastic
        "fittings_allowance": 0.3,  # fraction added to friction losses
        "supply_pressure_kpa": 300.0,
        "min_flow_pressure_kpa": 100.0,
        "pipe_series": {"15": 0.013, "18": 0.016, "22": 0.020, "28": 0.026, "35": 0.032,
                        "42": 0.039, "54": 0.051, "76": 0.073, "108": 0.105},  # nominal -> inner m
        "water_viscosity": 1.0e-6,
    },
    "drainage_settings": {
        "method": "en12056",  # en12056 | ipc
        "k_factor": 0.5,  # 0.5 dwelling, 0.7 office, 1.0 hospital/restaurant, 1.2 lab
        "default_slope": 0.02,
        "min_slope_large": 0.01,  # DN >= 100
        "min_slope_small": 0.02,
        "max_slope": 0.15,
        "fill_ratio": 0.5,
        "fill_ratio_large": 0.7,  # DN >= 150
        "manning_n": 0.011,  # PVC
        "rain_intensity": 0.03,  # L/s per m2
        "runoff_coefficient": 1.0,
        "vent_du_limit": 10.0,  # DU on a stack without a vent before a warning
        "pipe_series": {"40": 0.036, "50": 0.046, "75": 0.069, "90": 0.083, "110": 0.101,
                        "125": 0.115, "160": 0.147, "200": 0.184, "250": 0.230},  # DN -> inner m
    },
    "electrical_settings": {
        "voltage_single": 230.0,
        "voltage_three": 400.0,
        "power_factor": 0.95,
        "routing_factor": 1.2,
        "correction_factor": 1.0,  # grouping/ambient on the cable rating
        "drop_lighting": 0.03,
        "drop_other": 0.05,
        "resistivity": 0.0225,  # ohm mm2/m, copper at operating temperature
        "demand": {"lighting": 1.0, "power": 0.5, "appliance": 0.8, "hvac": 1.0},  # open table
    },
    "structure_settings": {
        "base_support": "fixed",  # fixed | pinned
        "bearing_walls": "unless_marked",  # walls carry slabs unless Pset_WallCommon.LoadBearing is false | marked_only | none
        "level_use": {},  # storey name -> use category (A, B, C... keys of use_loads); else default_use
        "merge_tolerance": 0.05,  # m: member ends this close share a node
        "superimposed_dead": 1.5,  # kN/m2
        "snow": 0.0,  # kN/m2 on roofs
        "default_use": "A",
        "use_loads": {"A": 2.0, "B": 3.0, "C": 4.0, "D": 5.0, "E": 7.5, "H": 0.4},  # open table, kN/m2
        "uls": {"G": 1.35, "Q": 1.5, "S": 0.75},
        "sls": {"G": 1.0, "Q": 1.0, "S": 0.5},
        "deflection_span": 250.0,  # L/250
        "deflection_cantilever": 125.0,
        "warn_utilisation": 0.9,
        "stations": 10,
        "materials": {  # open table: E, G kN/m2, density kN/m3, f (yield or strength) kN/m2, gamma
            "steel": {"E": 210e6, "G": 81e6, "density": 78.5, "f": 355e3, "gamma": 1.0},
            "concrete": {"E": 31e6, "G": 13e6, "density": 25.0, "f": 16.7e3, "gamma": 1.0},
            "timber": {"E": 11e6, "G": 0.69e6, "density": 4.2, "f": 14.8e3, "gamma": 1.0},
        },
    },
}

RANGES: dict[str, dict[str, tuple[float, float]]] = {
    "mep_settings": {"connect_tolerance": (0.0001, 0.5)},
    "hvac_settings": {"per_person": (0, 100), "per_area": (0, 20), "area_per_person": (0.5, 1000),
                      "ach": (0, 60), "friction_pa_m": (0.05, 20), "velocity_main": (0.5, 30),
                      "velocity_branch": (0.5, 30), "velocity_terminal": (0.3, 20), "roughness_mm": (0, 10),
                      "k_elbow": (0, 10), "k_tee_branch": (0, 10), "k_tee_straight": (0, 10),
                      "terminal_pa": (0, 1000), "max_aspect": (1, 10), "air_density": (0.5, 2),
                      "air_viscosity": (1e-6, 1e-4)},
    "plumbing_settings": {"velocity_main": (0.2, 6), "velocity_branch": (0.2, 6), "roughness_mm": (0, 5),
                          "fittings_allowance": (0, 2), "supply_pressure_kpa": (10, 2000),
                          "min_flow_pressure_kpa": (0, 1000), "water_viscosity": (1e-7, 1e-4)},
    "drainage_settings": {"k_factor": (0.1, 2), "default_slope": (0.001, 0.5), "min_slope_large": (0.001, 0.5),
                          "min_slope_small": (0.001, 0.5), "max_slope": (0.01, 1), "fill_ratio": (0.1, 1),
                          "fill_ratio_large": (0.1, 1), "manning_n": (0.005, 0.05), "rain_intensity": (0, 1),
                          "runoff_coefficient": (0, 1), "vent_du_limit": (0, 1000)},
    "electrical_settings": {"voltage_single": (12, 1000), "voltage_three": (12, 1000), "power_factor": (0.1, 1),
                            "routing_factor": (1, 5), "correction_factor": (0.1, 2), "drop_lighting": (0.001, 0.2),
                            "drop_other": (0.001, 0.2), "resistivity": (0.001, 1)},
    "structure_settings": {"merge_tolerance": (0.0001, 1), "superimposed_dead": (0, 100), "snow": (0, 100),
                           "deflection_span": (10, 10000), "deflection_cantilever": (10, 10000),
                           "warn_utilisation": (0.1, 1), "stations": (2, 100)},
}
CHOICES = {
    ("hvac_settings", "method"): ("en16798", "ach", "per_area"),
    ("plumbing_settings", "method"): ("en806", "hunter"),
    ("drainage_settings", "method"): ("en12056", "ipc"),
    ("structure_settings", "base_support"): ("fixed", "pinned"),
    ("structure_settings", "bearing_walls"): ("unless_marked", "marked_only", "none"),
}
# Tables that take new entries (shaped like an existing entry, or numbers for flat tables)
OPEN = {("mep_settings", "catalogue"), ("plumbing_settings", "pipe_series"), ("drainage_settings", "pipe_series"),
        ("electrical_settings", "demand"), ("structure_settings", "use_loads"), ("structure_settings", "materials")}
KEYS = tuple(DEFAULTS)


def _merge(base, over):
    if isinstance(base, dict) and isinstance(over, dict):
        out = copy.deepcopy(base)
        for k, v in over.items():
            out[k] = _merge(base.get(k), v) if k in base else copy.deepcopy(v)
        return out
    return copy.deepcopy(over)


def get(key: str) -> dict:
    """The discipline's settings: the project's overrides merged over the defaults."""
    from . import settings

    over = settings.current().get(key) or {}
    return _merge(DEFAULTS[key], over if isinstance(over, dict) else {})


def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _shape_error(where: str, default, value) -> str | None:
    if _number(default):
        return None if _number(value) else f"{where} is a number"
    if isinstance(default, str):
        return None if isinstance(value, str) else f"{where} is a text"
    if isinstance(default, dict):
        if not isinstance(value, dict):
            return f"{where} is a table"
        for k, v in value.items():
            if k in default:
                if (e := _shape_error(f"{where}.{k}", default[k], v)) is not None:
                    return e
        return None
    return None


def validate(key: str, value) -> str | None:
    """None when `value` is a valid set of overrides for `key`, else a message."""
    if key not in DEFAULTS:
        return f"unknown engineering settings {key}"
    if not isinstance(value, dict):
        return f"the {key.replace('_', ' ')} are a table"
    defaults = DEFAULTS[key]
    for name, v in value.items():
        if name not in defaults:
            return f"unknown setting {name}"
        default = defaults[name]
        if (key, name) in OPEN:
            if not isinstance(v, dict):
                return f"{name} is a table"
            sample = next(iter(default.values()), None)
            for entry, ev in v.items():
                if not isinstance(entry, str) or not entry.strip():
                    return f"{name} entries need a name"
                shape = default.get(entry, sample)
                if shape is None:  # an empty open table (catalogue): any table of numbers/texts
                    if not isinstance(ev, dict) or not all(_number(x) or isinstance(x, str) for x in ev.values()):
                        return f"{name}.{entry} is a table of values"
                    continue
                if (e := _shape_error(f"{name}.{entry}", shape, ev)) is not None:
                    return e
                if _number(ev) and ev < 0:
                    return f"{name}.{entry} cannot be negative"
            continue
        if (e := _shape_error(name, default, v)) is not None:
            return e
        if (key, name) in CHOICES and v not in CHOICES[(key, name)]:
            return f"{name} is one of {', '.join(CHOICES[(key, name)])}"
        if _number(v) and name in RANGES.get(key, {}):
            lo, hi = RANGES[key][name]
            if not lo <= v <= hi:
                return f"{name} must be between {lo:g} and {hi:g}"
        if isinstance(v, dict):
            for k, x in v.items():
                if _number(x) and x < 0:
                    return f"{name}.{k} cannot be negative"
    return None


def engineering_settings(key: str) -> str:
    """The discipline's settings (merged) and its defaults."""
    if key not in DEFAULTS:
        return B._dump({"ok": False, "error": f"unknown engineering settings {key}"})
    return B._dump({"ok": True, "settings": get(key), "defaults": copy.deepcopy(DEFAULTS[key])})


def set_engineering_settings(key: str, changes_json: str) -> str:
    """Change some of a discipline's settings (one undoable settings change)."""
    from . import settings

    if B._model is None:
        return B._dump({"ok": False, "error": "no model open"})
    try:
        changes = json.loads(changes_json) if isinstance(changes_json, str) else dict(changes_json)
    except (TypeError, ValueError) as ex:
        return B._dump({"ok": False, "error": f"bad input: {ex}"})
    if (err := validate(key, changes)) is not None:
        return B._dump({"ok": False, "error": err})
    stored = settings.current().get(key) or {}
    merged = _merge(stored if isinstance(stored, dict) else {}, changes)

    def action():
        r = json.loads(settings.set_project_settings(json.dumps({key: merged})))
        if not r.get("ok"):
            raise ValueError(r.get("error"))
        return 0, [], []

    try:
        result = B._run_settings(action)
    except Exception as ex:  # noqa: BLE001
        return B._dump({"ok": False, "error": str(ex)})
    return B._dump({**result, "settings": get(key)})


def reset_engineering_settings(key: str) -> str:
    """Back to the defaults for one discipline (one undoable settings change)."""
    from . import settings

    if key not in DEFAULTS:
        return B._dump({"ok": False, "error": f"unknown engineering settings {key}"})

    def action():
        settings.set_project_settings(json.dumps({key: {}}))
        return 0, [], []

    return B._dump({**B._run_settings(action), "settings": get(key)})
