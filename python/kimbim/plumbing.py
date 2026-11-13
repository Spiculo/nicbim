# SPDX-License-Identifier: GPL-3.0-or-later
"""Water supply pipe sizing (D244).

* Each fixture has a design flow ``SupplyFlow`` (L/s, EN 806-3: 0.1 L/s per loading unit) and its
  loading units ``LoadingUnits``. A pipe carries the summed design flows of the fixtures beyond it,
  reduced for simultaneity by the DIN 1988-300 peak-flow formula Q = a (ΣQ)^b - c (residential
  a = 1.48, b = 0.19, c = 0.94; settings), and never less than its largest single fixture nor more
  than the plain sum.
* Pipes are sized by velocity (mains 2.0, branches 1.5 m/s) over the project's pipe series.
* Pressure: Darcy-Weisbach friction (Swamee-Jain) plus a fittings allowance (30 %) and the
  static head of rising to the fixture; the pressure left at the critical fixture is compared with
  the minimum flow pressure.

The cold system's source is the water main; a hot system's is the water heater. Hot and cold are
sized separately, each on its own ports of the fixtures.
"""
from __future__ import annotations

import math

from . import app_bridge as B
from . import authoring as A
from . import engsettings, mep, mepcalc

RHO, G = 1000.0, 9.81


def peak_flow(sum_q: float, largest: float, cfg: dict) -> float:
    """Simultaneous peak flow (L/s) from the summed design flows of the fixtures served."""
    if sum_q <= 0.2:
        return sum_q
    q = cfg["simultaneity_a"] * sum_q ** cfg["simultaneity_b"] - cfg["simultaneity_c"]
    return min(sum_q, max(q, largest))


def _series(cfg) -> list[tuple[str, float]]:
    return sorted(((k, float(v)) for k, v in cfg["pipe_series"].items()), key=lambda kv: kv[1])


def size_water_system(system: str, apply=False) -> str:
    """Peak flows, pipe sizes and pressure at the fixtures of a cold or hot water system."""
    group, error = mepcalc.system_or_error(system, ("water",))
    if error:
        return A._fail(error)
    apply = apply if isinstance(apply, bool) else str(apply).lower() in ("1", "true", "yes")
    cfg = engsettings.get("plumbing_settings")
    net = mep.network(group)
    if not net["sources"]:
        return A._fail(f"{group.Name} has no source: place a water main or a water heater and connect it")
    warnings = []
    if net["unreached"]:
        warnings.append(f"{len(net['unreached'])} element(s) are not connected to the source and are not sized")
    own_q, own_lu = {}, {}
    for g in mepcalc.terminal_guids(net):
        d = mep.design_values(net["elements"][g])
        own_q[g] = float(d.get("SupplyFlow") or 0.1 * float(d.get("LoadingUnits") or 0.0))
        own_lu[g] = float(d.get("LoadingUnits") or own_q[g] * 10)
        if own_q[g] <= 0:
            warnings.append(f"{net['elements'][g].Name or 'Fixture'} has no supply flow")
    sum_q = mepcalc.accumulate(net, own_q)
    sum_lu = mepcalc.accumulate(net, own_lu)
    largest = mepcalc.accumulate_max(net, own_q)
    fixtures_beyond = mepcalc.count_beyond(net, {g: True for g in own_q})
    total = peak_flow(sum(own_q.values()), max(own_q.values(), default=0.0), cfg)
    series = _series(cfg)
    rows, sizes, dp = [], {}, {}
    for g, e in mepcalc.segments(net).items():
        q_ls = peak_flow(sum_q.get(g, 0.0), largest.get(g, 0.0), cfg)
        q = q_ls / 1000
        role = "main" if q_ls >= 0.5 * total and fixtures_beyond.get(g, 0) > 1 else "branch"
        vmax = cfg["velocity_main"] if role == "main" else cfg["velocity_branch"]
        length = mepcalc.length(e)
        chosen = series[-1]
        for name, d in series:
            if q <= 0 or q / (math.pi * d * d / 4) <= vmax:
                chosen = (name, d)
                break
        name, d = chosen
        v = q / (math.pi * d * d / 4) if q > 0 else 0.0
        r = mepcalc.gradient(v, d, RHO, cfg["water_viscosity"], cfg["roughness_mm"] / 1000)
        drop = r * length * (1 + cfg["fittings_allowance"])
        dp[g] = drop
        sizes[g] = (d, d)
        status = "ok" if v <= vmax * 1.001 else "largest size exceeded"
        rows.append({"guid": g, "name": e.Name or "Pipe", "loading_units": round(sum_lu.get(g, 0.0), 1),
                     "sum_flow": round(sum_q.get(g, 0.0), 3), "flow": round(q_ls, 3), "role": role,
                     "nominal": name, "diameter": d, "velocity": round(v, 2), "gradient": round(r, 1),
                     "length": round(length, 3), "pressure_drop": round(drop, 1),
                     "status": status})
    path = mepcalc.path_totals(net, dp)
    supply = cfg["supply_pressure_kpa"] * 1000
    source = net["elements"][net["sources"][0]]
    kind = net["kind"]

    def port_z(element):
        zs = [q[2] for p, q in mep.port_points(element) if mep.port_kind(p) == kind] or              [q[2] for _p, q in mep.port_points(element)]
        return float(max(zs)) if zs else float(mep._matrix(element)[2, 3])

    z_source = port_z(source)
    fixture_rows = []
    for g in own_q:
        e = net["elements"][g]
        static = RHO * G * (port_z(e) - z_source)  # rising to the fixture costs pressure
        left = supply - path.get(g, 0.0) - static
        fixture_rows.append({"guid": g, "name": e.Name or "Fixture", "flow": own_q[g], "loading_units": own_lu[g],
                             "pressure_kpa": round(left / 1000, 1),
                             "status": "ok" if left >= cfg["min_flow_pressure_kpa"] * 1000 else "low pressure"})
    critical = min(fixture_rows, key=lambda x: x["pressure_kpa"], default=None)
    if critical and critical["status"] != "ok":
        warnings.append(f"{critical['name']} gets {critical['pressure_kpa']:g} kPa, below the "
                        f"{cfg['min_flow_pressure_kpa']:g} kPa it needs: raise the supply pressure or enlarge pipes")
    report = {"ok": True, "system": group.Name, "kind": net["kind"], "segments": rows, "fixtures": fixture_rows,
              "peak_flow": round(total, 3), "critical_fixture": critical["guid"] if critical else None,
              "critical_pressure_kpa": critical["pressure_kpa"] if critical else None, "warnings": warnings,
              "method": "Peak flow by simultaneity (DIN 1988-300 formula over EN 806-3 design flows); velocity "
                        "sizing; Darcy-Weisbach friction",
              "assumptions": [
                  f"Peak flow Q = {cfg['simultaneity_a']:g} (ΣQ)^{cfg['simultaneity_b']:g} - "
                  f"{cfg['simultaneity_c']:g} L/s (ΣQ > 0.2 L/s), at least the largest fixture",
                  f"Velocity limits main {cfg['velocity_main']:g}, branch {cfg['velocity_branch']:g} m/s",
                  f"Roughness {cfg['roughness_mm']:g} mm; fittings +{cfg['fittings_allowance'] * 100:g} % of friction",
                  f"Supply {cfg['supply_pressure_kpa']:g} kPa; fixtures need {cfg['min_flow_pressure_kpa']:g} kPa",
                  "Design aid: check with the plumbing engineer"]}
    if apply:
        seg_rows = [{"guid": r["guid"], "width": r["diameter"], "height": r["diameter"],
                     "design": {"Flow": float(r["flow"]), "Velocity": float(r["velocity"]), "Nominal": r["nominal"],
                                "PressureDrop": float(r["pressure_drop"])}} for r in rows]
        try:
            report.update(mepcalc.apply_sizes(seg_rows, mepcalc.fitting_sizes(net, sizes), "plumbing"))
        except Exception as ex:  # noqa: BLE001
            return A._fail(f"{type(ex).__name__}: {ex}")
        report["applied"] = True
    return B._dump(report)
