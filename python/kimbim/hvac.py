# SPDX-License-Identifier: GPL-3.0-or-later
"""HVAC airflow and duct sizing (D243).

1. **Terminal flows.** A terminal's flow is its design value ``Flow`` (L/s) when set (> 0);
   otherwise it comes from the room it sits in. EN 16798-1 category II is the default: 7 L/s per
   person + 0.7 L/s per m² (low-polluting building), with the room's ``OccupancyNumber``
   (Pset_SpaceOccupancyRequirements) or its area / ``area_per_person``. The alternatives are an
   air-change rate (ACH x volume) and a flow per m². A room's flow is shared equally by its supply
   terminals, and likewise by its extract (return or exhaust) terminals.
2. **Accumulation.** Every duct carries the sum of the terminals beyond it in the system's tree.
3. **Sizing**: equal friction (``friction_pa_m``) capped by a velocity limit. Mains carry half or
   more of the system's flow, terminal connections serve a single terminal, the rest are branches.
   Round ducts use the standard diameter series. Rectangular ducts keep their drawn height (raised
   when the width would pass ``max_aspect``) and take widths in 50 mm steps, sized on the
   Huebscher equivalent diameter.
4. **Pressure**: Darcy-Weisbach with Swamee-Jain friction, elbows and tees by K factor and a fixed
   loss per terminal. The critical path is the largest total from the source to a terminal, and the
   fan must deliver the system flow at that pressure.
"""
from __future__ import annotations

import math

import ifcopenshell.util.element

from . import app_bridge as B
from . import authoring as A
from . import engsettings, mep, mepcalc

ROUND_MM = (100, 125, 160, 200, 250, 315, 355, 400, 450, 500, 560, 630, 710, 800, 900, 1000, 1120, 1250)
SUPPLY_KINDS = ("supply_air", "outside_air")


def equivalent_diameter(a: float, b: float) -> float:
    """Huebscher: the round duct with the same friction as an a x b rectangle."""
    return 1.30 * (a * b) ** 0.625 / (a + b) ** 0.25


def _room_flow(space, cfg: dict) -> float:
    area, volume = mepcalc.room_area_volume(space)
    method = cfg["method"]
    if method == "ach":
        return cfg["ach"] * volume / 3.6
    if method == "per_area":
        return cfg["per_area"] * area
    occ = (ifcopenshell.util.element.get_pset(space, "Pset_SpaceOccupancyRequirements") or {}).get("OccupancyNumber")
    people = float(occ) if occ else area / cfg["area_per_person"]
    return cfg["per_person"] * people + cfg["per_area"] * area


def terminal_flows(net: dict, cfg: dict, warnings: list) -> tuple[dict, dict]:
    """({terminal guid: L/s}, {terminal guid: room name})."""
    flows, rooms = {}, {}
    by_room: dict = {}
    for g in mepcalc.terminal_guids(net):
        e = net["elements"][g]
        manual = float(mep.design_values(e).get("Flow") or 0.0)
        room = mepcalc.room_of(e)
        rooms[g] = (room.LongName or room.Name or "") if room is not None else ""
        if manual > 0:
            flows[g] = manual
            continue
        if room is None:
            warnings.append(f"{e.Name or 'Terminal'} is in no room and has no design flow: 0 L/s")
            flows[g] = 0.0
            continue
        by_room.setdefault(room.id(), (room, []))[1].append(g)
    for room, guids in by_room.values():
        total = _room_flow(room, cfg)
        for g in guids:
            flows[g] = total / len(guids)
    return flows, rooms


def _round_size(q: float, vmax: float, cfg: dict) -> tuple[float, float, float]:
    """(diameter m, velocity, gradient) of the smallest round duct within both limits."""
    for d_mm in ROUND_MM:
        d = d_mm / 1000
        v = q / (math.pi * d * d / 4)
        r = mepcalc.gradient(v, d, cfg["air_density"], cfg["air_viscosity"], cfg["roughness_mm"] / 1000)
        if v <= vmax and r <= cfg["friction_pa_m"]:
            return d, v, r
    d = ROUND_MM[-1] / 1000
    v = q / (math.pi * d * d / 4)
    return d, v, mepcalc.gradient(v, d, cfg["air_density"], cfg["air_viscosity"], cfg["roughness_mm"] / 1000)


def _rect_size(q: float, vmax: float, height: float, cfg: dict) -> tuple[float, float, float, float]:
    """(width, height, velocity, gradient) of the narrowest rectangle within both limits."""
    h = max(0.1, round(height / 0.05) * 0.05)
    for _ in range(40):
        for w_steps in range(2, 61):
            w = w_steps * 0.05
            if w / h > cfg["max_aspect"]:
                break
            if h / w > cfg["max_aspect"]:
                continue
            v = q / (w * h)
            de = equivalent_diameter(w, h)
            r = mepcalc.gradient(q / (math.pi * de * de / 4), de, cfg["air_density"], cfg["air_viscosity"],
                                 cfg["roughness_mm"] / 1000)
            if v <= vmax and r <= cfg["friction_pa_m"]:
                return w, h, v, r
        h += 0.05
    w = 3.0
    de = equivalent_diameter(w, h)
    return w, h, q / (w * h), mepcalc.gradient(q / (math.pi * de * de / 4), de, cfg["air_density"],
                                               cfg["air_viscosity"], cfg["roughness_mm"] / 1000)


def size_air_system(system: str, apply=False) -> str:
    """Flows, duct sizes and pressure drops for an air system. With `apply` the sizes and design
    values are written to the ducts and fittings (one undo step)."""
    group, error = mepcalc.system_or_error(system, ("air",))
    if error:
        return A._fail(error)
    apply = apply if isinstance(apply, bool) else str(apply).lower() in ("1", "true", "yes")
    cfg = engsettings.get("hvac_settings")
    net = mep.network(group)
    warnings: list[str] = []
    if not net["sources"]:
        return A._fail(f"{group.Name} has no source: place an air handling unit or fan and connect it")
    if net["unreached"]:
        warnings.append(f"{len(net['unreached'])} element(s) are not connected to the source and are not sized")
    flows, rooms = terminal_flows(net, cfg, warnings)
    total_q = mepcalc.accumulate(net, flows)
    terminals_beyond = mepcalc.count_beyond(net, {g: True for g in flows})
    system_flow = sum(flows.values())
    rho = cfg["air_density"]
    segs = mepcalc.segments(net)
    rows, sizes, dp = [], {}, {}
    for g, e in segs.items():
        q_ls = total_q.get(g, 0.0)
        q = q_ls / 1000
        width, height, shape = mep.segment_size(e)
        if q_ls >= 0.5 * system_flow and system_flow > 0:
            vmax, role = cfg["velocity_main"], "main"
        elif terminals_beyond.get(g, 0) <= 1:
            vmax, role = cfg["velocity_terminal"], "terminal"
        else:
            vmax, role = cfg["velocity_branch"], "branch"
        length = mepcalc.length(e)
        if q <= 0:
            rows.append({"guid": g, "name": e.Name or "Duct", "flow": 0.0, "role": role, "shape": shape,
                         "width": width, "height": height, "velocity": 0.0, "gradient": 0.0, "length": length,
                         "pressure_drop": 0.0, "status": "no flow"})
            sizes[g] = (width, height)
            dp[g] = 0.0
            continue
        if shape == "round":
            d, v, r = _round_size(q, vmax, cfg)
            w, h = d, d
        else:
            w, h, v, r = _rect_size(q, vmax, height, cfg)
        drop = r * length
        dp[g] = drop
        sizes[g] = (w, h)
        status = "ok" if v <= vmax * 1.001 and r <= cfg["friction_pa_m"] * 1.001 else "largest size exceeded"
        rows.append({"guid": g, "name": e.Name or "Duct", "flow": round(q_ls, 2), "role": role, "shape": shape,
                     "width": w, "height": h, "velocity": round(v, 2), "gradient": round(r, 3),
                     "length": round(length, 3), "pressure_drop": round(drop, 2), "status": status,
                     "was": [round(width, 3), round(height, 3)]})
    # fittings: elbows K x velocity pressure of the duct they feed; tees branch/straight by flow
    for g, e in mepcalc.fittings(net).items():
        kind = (ifcopenshell.util.element.get_pset(e, mep.MEP_PSET) or {}).get("Fitting") or getattr(e, "PredefinedType", "")
        kids = [c for c in net["adjacency"].get(g, []) if net["tree"].get(c) == g]
        loss = 0.0
        for c in kids:
            row = next((r for r in rows if r["guid"] == c), None)
            if row is None:
                continue
            pv = rho * row["velocity"] ** 2 / 2
            if kind == "JUNCTION":
                biggest = max(kids, key=lambda k: total_q.get(k, 0.0))
                loss = max(loss, (cfg["k_tee_straight"] if c == biggest else cfg["k_tee_branch"]) * pv)
                dp[c] = dp.get(c, 0.0) + (cfg["k_tee_straight"] if c == biggest else cfg["k_tee_branch"]) * pv
            else:
                loss = max(loss, cfg["k_elbow"] * pv)
                dp[c] = dp.get(c, 0.0) + cfg["k_elbow"] * pv
    for g in flows:
        dp[g] = dp.get(g, 0.0) + cfg["terminal_pa"]
    path = mepcalc.path_totals(net, dp)
    terminal_rows = []
    for g, q in flows.items():
        e = net["elements"][g]
        terminal_rows.append({"guid": g, "name": e.Name or "Terminal", "room": rooms.get(g, ""), "flow": round(q, 2),
                              "pressure": round(path.get(g, 0.0), 1),
                              "manual": float(mep.design_values(e).get("Flow") or 0.0) > 0})
    critical = max(terminal_rows, key=lambda t: t["pressure"], default=None)
    report = {"ok": True, "system": group.Name, "kind": net["kind"], "segments": rows, "terminals": terminal_rows,
              "system_flow": round(system_flow, 2), "critical_terminal": critical["guid"] if critical else None,
              "fan_pressure": round(critical["pressure"], 1) if critical else 0.0, "warnings": warnings,
              "method": "Equal friction with velocity limits; Darcy-Weisbach (Swamee-Jain) and K-factor fittings",
              "assumptions": [
                  {"en16798": f"Room flows EN 16798-1 cat. II: {cfg['per_person']:g} L/s per person + "
                              f"{cfg['per_area']:g} L/s·m² (area per person {cfg['area_per_person']:g} m² when "
                              "the room has no occupancy)",
                   "ach": f"Room flows {cfg['ach']:g} air changes per hour",
                   "per_area": f"Room flows {cfg['per_area']:g} L/s per m²"}[cfg["method"]],
                  f"Friction target {cfg['friction_pa_m']:g} Pa/m; velocity limits main {cfg['velocity_main']:g}, "
                  f"branch {cfg['velocity_branch']:g}, terminal {cfg['velocity_terminal']:g} m/s",
                  f"Roughness {cfg['roughness_mm']:g} mm; elbow K {cfg['k_elbow']:g}, tee K straight "
                  f"{cfg['k_tee_straight']:g} / branch {cfg['k_tee_branch']:g}; {cfg['terminal_pa']:g} Pa per terminal",
                  "Design aid: check with the mechanical engineer"]}
    if apply:
        seg_rows = [{"guid": r["guid"], "width": r["width"], "height": r["height"],
                     "design": {"Flow": float(r["flow"]), "Velocity": float(r["velocity"]),
                                "PressureDrop": float(r["pressure_drop"]), "SizingRole": r["role"]}}
                    for r in rows if r["flow"] > 0]
        seg_rows += [{"guid": t["guid"], "design": {"DesignFlow": float(t["flow"])}} for t in terminal_rows]
        try:
            result = mepcalc.apply_sizes(seg_rows, mepcalc.fitting_sizes(net, sizes), "hvac")
        except Exception as ex:  # noqa: BLE001
            return A._fail(f"{type(ex).__name__}: {ex}")
        report.update(result)
        report["applied"] = True
    return B._dump(report)
