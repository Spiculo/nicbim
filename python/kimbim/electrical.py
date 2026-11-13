# SPDX-License-Identifier: GPL-3.0-or-later
"""Electrical circuits, breaker and cable sizing, voltage drop and the panel schedule (D246).

A circuit (``IfcDistributionCircuit``; ``IfcElectricalCircuit`` in IFC2X3) groups the devices a
distribution board feeds. ``KIMBIM_Circuit`` records its board, kind (power or lighting), phase
(L1, L2, L3, 3P or auto) and an optional typed cable length.

For each circuit (IEC 60364 defaults, all settings):

* load: the devices' apparent power (``ApparentPower`` VA) times the demand factor of their load
  class (lighting 1.0, power 0.5, appliances 0.8, hvac 1.0);
* design current I_b = S / U single-phase, S / (√3 U) three-phase;
* breaker I_n: the next standard rating at or above I_b;
* cable: the smallest copper cross-section whose rating (IEC 60364-5-52 table B.52.4, method C, PVC;
  x 0.87 for three loaded conductors; x the correction factor) is at least I_n, and at least
  1.5 mm² for lighting / 2.5 mm² for power;
* length: typed, or the board-to-devices route (Manhattan, nearest device next) x the routing
  factor; voltage drop ΔU = b L I_b ρ cosφ / S with b = 2 single-phase, √3 three-phase, the whole
  current over the whole length (conservative). A cable over the limit (3 % lighting, 5 % other)
  is enlarged up to five sizes.

Single-phase circuits on ``auto`` are spread over L1-L3 largest first to balance the board.
"""
from __future__ import annotations

import json
import math

import ifcopenshell.api.group
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.util.element

from . import app_bridge as B
from . import authoring as A
from . import engsettings, mep

CIRCUIT_PSET = "KIMBIM_Circuit"
PHASES = ("L1", "L2", "L3", "3P", "auto")
KINDS = ("power", "lighting")


def _circuit_class() -> str:
    return "IfcElectricalCircuit" if B._model.schema == "IFC2X3" else "IfcDistributionCircuit"


def _circuits(board_guid: str = "") -> list:
    out = []
    try:
        found = B._model.by_type(_circuit_class())
    except RuntimeError:
        return out
    for c in found:
        data = ifcopenshell.util.element.get_pset(c, CIRCUIT_PSET) or {}
        if board_guid and data.get("Board") != board_guid:
            continue
        out.append((c, data))
    return out


def _is_board(e) -> bool:
    return e is not None and (e.is_a("IfcElectricDistributionBoard") or e.is_a("IfcElectricDistributionPoint")
                              or mep.design_values(e).get("Kind") == "board")


def create_circuit(board_guid: str, guids_json: str, name: str = "", phase: str = "auto", kind: str = "") -> str:
    """A circuit from a board to the selected devices (one undo step)."""
    if B._model is None:
        return A._fail("no model open")
    board = A._by_guid(board_guid)
    if not _is_board(board):
        return A._fail("choose a distribution board")
    try:
        devices = [A._by_guid(g) for g in json.loads(guids_json)]
    except ValueError as ex:
        return A._fail(str(ex))
    devices = [d for d in devices if d is not None and d != board]
    if not devices:
        return A._fail("select the devices the circuit feeds")
    phase = (phase or "auto").strip()
    if phase not in PHASES:
        return A._fail(f"the phase is one of {', '.join(PHASES)}")
    if not kind:
        kind = "lighting" if all(mep.design_values(d).get("LoadClass") == "lighting" for d in devices) else "power"
    if kind not in KINDS:
        return A._fail("the circuit is power or lighting")
    existing = {c.Name for c, _ in _circuits(board_guid)}
    if not name:
        n = len(existing) + 1
        while f"{board.Name or 'DB'}-{n}" in existing:
            n += 1
        name = f"{board.Name or 'DB'}-{n}"
    made = {}

    def action():
        f = B._model
        cls = _circuit_class()
        circuit = ifcopenshell.api.root.create_entity(f, ifc_class=cls, name=name)
        if hasattr(circuit, "PredefinedType"):
            circuit.PredefinedType = "LIGHTING" if kind == "lighting" else "ELECTRICAL"
        pset = ifcopenshell.api.pset.add_pset(f, product=circuit, name=CIRCUIT_PSET)
        ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={"Board": board.GlobalId, "Phase": phase,
                                                                   "Kind": kind, "Length": 0.0})
        mep_pset = ifcopenshell.api.pset.add_pset(f, product=circuit, name=mep.SYSTEM_PSET)
        ifcopenshell.api.pset.edit_pset(f, pset=mep_pset, properties={"Kind": kind})
        ifcopenshell.api.group.assign_group(f, products=devices, group=circuit)
        made["guid"] = circuit.GlobalId
        return len(devices)

    try:
        r = B._run(action, affects_drawings=False)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["guid"], "name": name})


def edit_circuit(circuit_guid: str, values_json: str) -> str:
    """Change a circuit's phase, kind or typed cable length (0 = measured)."""
    if B._model is None:
        return A._fail("no model open")
    circuit = A._by_guid(circuit_guid)
    if circuit is None or not circuit.is_a(_circuit_class()):
        return A._fail("unknown circuit")
    try:
        values = json.loads(values_json)
    except ValueError as ex:
        return A._fail(str(ex))
    clean = {}
    for k, v in values.items():
        if k == "Phase" and v in PHASES:
            clean[k] = v
        elif k == "Kind" and v in KINDS:
            clean[k] = v
        elif k == "Length" and isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 10000:
            clean[k] = float(v)
        else:
            return A._fail(f"bad circuit value {k}")

    def action():
        f = B._model
        pset = ifcopenshell.util.element.get_pset(circuit, CIRCUIT_PSET)
        ifcopenshell.api.pset.edit_pset(f, pset=f.by_id(pset["id"]), properties=clean)
        return 1

    try:
        r = B._run(action, affects_drawings=False)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump(r)


def remove_circuit(circuit_guid: str) -> str:
    """Delete a circuit (its devices stay)."""
    if B._model is None:
        return A._fail("no model open")
    circuit = A._by_guid(circuit_guid)
    if circuit is None or not circuit.is_a(_circuit_class()):
        return A._fail("unknown circuit")
    def action():
        mep.delete_group(circuit)
        return 1

    try:
        r = B._run(action, affects_drawings=False)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump(r)


def _route_length(board, devices) -> float:
    """Manhattan route from the board through the devices, nearest first (metres, before the factor)."""
    here = mep._matrix(board)[:3, 3]
    left = [mep._matrix(d)[:3, 3] for d in devices]
    total = 0.0
    while left:
        i = min(range(len(left)), key=lambda k: float(abs(left[k] - here).sum()))
        total += float(abs(left[i] - here).sum())
        here = left.pop(i)
    return total


def _breakers(cfg) -> list[float]:
    return sorted(float(x) for x in str(cfg["breakers"]).replace(",", " ").split() if x.strip())


def _cables(cfg) -> list[tuple[float, float]]:
    return sorted((float(k), float(v)) for k, v in cfg["cable_rating"].items())


def size_circuit(load_va: float, length: float, three_phase: bool, kind: str, cfg: dict,
                 power_factor: float | None = None) -> dict:
    """Breaker, cable and voltage drop for one circuit."""
    pf = power_factor or cfg["power_factor"]
    u = cfg["voltage_three"] if three_phase else cfg["voltage_single"]
    ib = load_va / (math.sqrt(3) * u) if three_phase else load_va / u
    breakers = _breakers(cfg)
    breaker = next((b for b in breakers if b >= ib), None)
    status = "ok"
    if breaker is None:
        breaker, status = breakers[-1], "load above the largest breaker"
    derate = cfg["correction_factor"] * (0.87 if three_phase else 1.0)
    cables = _cables(cfg)
    minimum = cfg["min_cable_lighting"] if kind == "lighting" else cfg["min_cable_power"]
    index = next((i for i, (s, iz) in enumerate(cables) if s >= minimum and iz * derate >= breaker), None)
    if index is None:
        index, status = len(cables) - 1, "no cable in the table carries the breaker's current"
    b = math.sqrt(3) if three_phase else 2.0
    limit = cfg["drop_lighting"] if kind == "lighting" else cfg["drop_other"]

    def drop(i):
        return b * length * ib * cfg["resistivity"] / cables[i][0] * pf / u

    tries = 0
    while drop(index) > limit and index < len(cables) - 1 and tries < 5:
        index += 1
        tries += 1
    if drop(index) > limit and status == "ok":
        status = "voltage drop over the limit"
    section, rating = cables[index]
    return {"design_current": round(ib, 2), "breaker": breaker, "cable": section,
            "cable_rating": round(rating * derate, 1), "voltage_drop": round(drop(index) * 100, 2),
            "drop_limit": limit * 100, "status": status, "upsized": tries}


def panel_schedule(board_guid: str, apply=False) -> str:
    """The board's circuits sized (breakers, cables, voltage drop) with phase loads and the main
    breaker. With `apply`, chosen sizes and auto phases are written to the circuits (one undo step)."""
    if B._model is None:
        return A._fail("no model open")
    board = A._by_guid(board_guid)
    if not _is_board(board):
        return A._fail("choose a distribution board")
    apply = apply if isinstance(apply, bool) else str(apply).lower() in ("1", "true", "yes")
    cfg = engsettings.get("electrical_settings")
    phases_on_board = int(float(mep.design_values(board).get("Phases") or 3))
    rows, warnings = [], []
    for circuit, data in _circuits(board.GlobalId):
        devices = [e for e in mep.system_members(circuit) if e.is_a("IfcElement")]
        kind = data.get("Kind") or "power"
        load, connected = 0.0, 0.0
        pf_weighted = 0.0
        for d in devices:
            dv = mep.design_values(d)
            va = float(dv.get("ApparentPower") or 0.0)
            demand = float(cfg["demand"].get(dv.get("LoadClass") or kind, 1.0))
            connected += va
            load += va * demand
            pf_weighted += va * demand * float(dv.get("PowerFactor") or cfg["power_factor"])
        pf = pf_weighted / load if load > 0 else cfg["power_factor"]
        phase = data.get("Phase") or "auto"
        three = phase == "3P" and phases_on_board == 3
        typed = float(data.get("Length") or 0.0)
        length = typed if typed > 0 else _route_length(board, devices) * cfg["routing_factor"]
        sized = size_circuit(load, length, three, kind, cfg, pf)
        if sized["status"] != "ok":
            warnings.append(f"{circuit.Name}: {sized['status']}")
        rows.append({"guid": circuit.GlobalId, "name": circuit.Name or "", "kind": kind, "phase": phase,
                     "devices": len(devices), "connected_va": round(connected, 1), "demand_va": round(load, 1),
                     "power_factor": round(pf, 3), "length": round(length, 2), "length_typed": typed > 0, **sized})
    # phase balance: single-phase circuits on auto go to the least loaded phase, largest first
    loads = {"L1": 0.0, "L2": 0.0, "L3": 0.0}
    for r in rows:
        if r["phase"] == "3P":
            for p in loads:
                loads[p] += r["demand_va"] / 3
        elif r["phase"] in loads:
            loads[r["phase"]] += r["demand_va"]
    for r in sorted((r for r in rows if r["phase"] == "auto"), key=lambda r: -r["demand_va"]):
        target = "L1" if phases_on_board == 1 else min(loads, key=loads.get)
        r["phase_assigned"] = target
        loads[target] += r["demand_va"]
    total = sum(loads.values())
    mean = total / 3 if phases_on_board == 3 else total
    imbalance = (max(loads.values()) - min(loads.values())) / mean if phases_on_board == 3 and mean > 0 else 0.0
    if phases_on_board == 3:
        main_current = max(loads.values()) / cfg["voltage_single"]
    else:
        main_current = total / cfg["voltage_single"]
    main = next((b for b in _breakers(cfg) if b >= main_current), _breakers(cfg)[-1])
    if imbalance > 0.2:
        warnings.append(f"phase imbalance {imbalance * 100:.0f} %: move circuits between phases")
    report = {"ok": True, "board": board.GlobalId, "board_name": board.Name or "", "phases": phases_on_board,
              "circuits": rows, "phase_loads": {k: round(v, 1) for k, v in loads.items()},
              "total_demand_va": round(total, 1), "imbalance": round(imbalance, 3),
              "main_current": round(main_current, 2), "main_breaker": main, "warnings": warnings,
              "method": "IEC 60364: demand load, next standard breaker, cable by rating (method C), voltage drop",
              "assumptions": [
                  f"{cfg['voltage_single']:g} V single-phase / {cfg['voltage_three']:g} V three-phase, cos φ "
                  f"{cfg['power_factor']:g} unless the device gives one",
                  "Demand factors " + ", ".join(f"{k} {v:g}" for k, v in cfg["demand"].items()),
                  f"Copper, ρ {cfg['resistivity']:g} Ω·mm²/m; route x {cfg['routing_factor']:g}; drop limits "
                  f"{cfg['drop_lighting'] * 100:g} % lighting, {cfg['drop_other'] * 100:g} % other",
                  "The whole circuit current over the whole cable length (conservative)",
                  "Design aid: check with the electrical engineer"]}
    if apply:
        def action():
            f = B._model
            for r in rows:
                circuit = f.by_guid(r["guid"])
                pset = ifcopenshell.util.element.get_pset(circuit, CIRCUIT_PSET)
                values = {"Breaker": float(r["breaker"]), "Cable": float(r["cable"]),
                          "DesignCurrent": float(r["design_current"]), "VoltageDrop": float(r["voltage_drop"]),
                          "MeasuredLength": float(r["length"])}
                if r.get("phase_assigned"):
                    values["Phase"] = r["phase_assigned"]
                ifcopenshell.api.pset.edit_pset(f, pset=f.by_id(pset["id"]), properties=values)
            return len(rows)

        try:
            report.update(B._run(action, affects_drawings=False))
        except Exception as ex:  # noqa: BLE001
            return A._fail(f"{type(ex).__name__}: {ex}")
        report["applied"] = True
    return B._dump(report)


def circuits(board_guid: str = "") -> str:
    """The circuits (of one board, or all) with their devices."""
    if B._model is None:
        return A._fail("no model open")
    out = []
    for c, data in _circuits(board_guid):
        out.append({"guid": c.GlobalId, "name": c.Name or "", "board": data.get("Board"), "phase": data.get("Phase"),
                    "kind": data.get("Kind"), "length": data.get("Length"),
                    "devices": [e.GlobalId for e in mep.system_members(c)]})
    boards = [{"guid": e.GlobalId, "name": e.Name or ""} for e in B._model.by_type("IfcElement") if _is_board(e)]
    return B._dump({"ok": True, "circuits": out, "boards": boards})
