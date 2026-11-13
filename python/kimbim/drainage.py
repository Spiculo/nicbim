# SPDX-License-Identifier: GPL-3.0-or-later
"""Drainage: sanitary and storm pipe sizing and slope checks (D245).

* **Sanitary flow** (EN 12056-2 system I): Q = K·√ΣDU with the building's frequency factor K
  (0.5 dwellings, 0.7 offices and schools, 1.0 hospitals and restaurants, 1.2 laboratories); never
  less than the largest single fixture's discharge units beyond the pipe.
* **Storm flow**: Q = r·A·C per roof drain, with the drain's design ``Area`` or, when it has none,
  its share of the roof it sits on.
* **Horizontal pipes** run downhill to the outlet. Capacity is Manning's formula part-full
  (fill 50 %, 70 % from DN 150; n = 0.011), at the pipe's own slope. A pipe is at least as big as
  the largest fixture drain beyond it and never smaller than the pipes feeding it. Slopes under the
  minimum (1 % from DN 100, 2 % below), over the maximum, or falling the wrong way are reported.
* **Stacks** (vertical pipes) take the EN 12056-2 table 11 capacities. A stack carrying more than
  ``vent_du_limit`` DU in a model without a vent system gets a warning (venting is not sized).

The network is walked from the outlet (a ``drain_outlet``), or from the lowest open pipe end.
"""
from __future__ import annotations

import json
import math

import numpy as np

from . import app_bridge as B
from . import authoring as A
from . import engsettings, mep, mepcalc


def part_full(diameter: float, fill: float) -> tuple[float, float]:
    """(flow area m², hydraulic radius m) of a round pipe filled to `fill` x diameter."""
    theta = 2 * math.acos(1 - 2 * fill)
    area = diameter ** 2 / 8 * (theta - math.sin(theta))
    perimeter = diameter * theta / 2
    return area, area / perimeter


def capacity(diameter: float, slope: float, fill: float, n: float) -> float:
    """Manning capacity (L/s) of a round pipe at a slope, part-full."""
    if slope <= 0:
        return 0.0
    area, radius = part_full(diameter, fill)
    return 1000 * area * radius ** (2 / 3) * math.sqrt(slope) / n


def _series(cfg) -> list[tuple[int, float]]:
    return sorted((int(k), float(v)) for k, v in cfg["pipe_series"].items())


def _downstream_end(net, g, e):
    """(upstream point, downstream point) of a drain pipe: downstream is towards the outlet."""
    (p_start, a), (p_end, b) = mep.end_ports(e)
    parent = net["tree"].get(g)
    if parent is None:  # the root pipe: its open lower end is the outlet
        return (a, b) if a[2] >= b[2] else (b, a)
    other = mep._connected(p_end)
    if other is not None and mep._port_element(other) is not None and \
            mep._port_element(other).GlobalId == parent:
        return a, b
    other = mep._connected(p_start)
    if other is not None and mep._port_element(other) is not None and \
            mep._port_element(other).GlobalId == parent:
        return b, a
    return (a, b) if a[2] >= b[2] else (b, a)


def _roof_areas(net, drains: list[str], warnings: list) -> dict[str, float]:
    """Area each roof drain serves: its design Area, else an equal share of the roof under it."""
    from . import structanalysis as SA

    out, by_roof = {}, {}
    roofs = []
    for s in B._model.by_type("IfcSlab") + B._model.by_type("IfcRoof"):
        if SA._is_roof(s):
            o = SA._slab_outline(s)
            if o is not None:
                roofs.append((s, o))
    for g in drains:
        e = net["elements"][g]
        area = float(mep.design_values(e).get("Area") or 0.0)
        if area > 0:
            out[g] = area
            continue
        p = mep._matrix(e)[:3, 3]
        found = None
        for s, (poly, z0, z1, _t) in roofs:
            if SA._inside(p[None, :2], poly)[0] and z0 - 1.0 <= p[2] <= z1 + 1.0:
                found = (s, poly)
                break
        if found is None:
            warnings.append(f"{e.Name or 'Roof drain'} has no design area and is on no roof: 0 L/s")
            out[g] = 0.0
            continue
        by_roof.setdefault(found[0].id(), (found[1], []))[1].append(g)
    for poly, guids in by_roof.values():
        share = SA._polygon_area(poly) / len(guids)
        for g in guids:
            out[g] = share
    return out


def size_drainage_system(system: str, apply=False) -> str:
    """Flows, pipe sizes and slope checks for a sanitary or storm drainage system."""
    group, error = mepcalc.system_or_error(system, ("drainage",))
    if error:
        return A._fail(error)
    apply = apply if isinstance(apply, bool) else str(apply).lower() in ("1", "true", "yes")
    cfg = engsettings.get("drainage_settings")
    net = mep.network(group)
    kind = net["kind"]
    if kind == "vent":
        return A._fail("vent systems are checked with their stacks, not sized")
    if not net["sources"]:
        return A._fail(f"{group.Name} has no outlet: place a drain outlet or leave the lowest pipe end open")
    warnings = []
    if net["unreached"]:
        warnings.append(f"{len(net['unreached'])} element(s) are not connected to the outlet and are not sized")
    terminals = mepcalc.terminal_guids(net)
    own_du, own_min_dn, own_flow = {}, {}, {}
    if kind == "storm":
        areas = _roof_areas(net, terminals, warnings)
        for g in terminals:
            own_flow[g] = cfg["rain_intensity"] * areas[g] * cfg["runoff_coefficient"]
            own_min_dn[g] = float(mep.design_values(net["elements"][g]).get("DrainDN") or 75.0)
    else:
        for g in terminals:
            d = mep.design_values(net["elements"][g])
            own_du[g] = float(d.get("DischargeUnits") or 0.0)
            own_min_dn[g] = float(d.get("DrainDN") or 50.0)
    sum_du = mepcalc.accumulate(net, own_du)
    largest_du = mepcalc.accumulate_max(net, own_du)
    sum_flow = mepcalc.accumulate(net, own_flow)
    min_dn = mepcalc.accumulate_max(net, own_min_dn)
    series = _series(cfg)
    stack_cap = sorted((int(k), float(v)) for k, v in cfg["stack_capacity"].items())
    vent_exists = any(mep.system_kind(s) == "vent" for s in mep.all_systems())
    segs = mepcalc.segments(net)
    chosen: dict[str, int] = {}
    rows = {}
    for g in mepcalc.post_order(net):
        if g not in segs:
            continue
        e = segs[g]
        if kind == "storm":
            q = sum_flow.get(g, 0.0)
        else:
            q = max(cfg["k_factor"] * math.sqrt(sum_du.get(g, 0.0)), largest_du.get(g, 0.0)) if sum_du.get(g) else 0.0
        up, down = _downstream_end(net, g, e)
        horizontal = float(np.linalg.norm((up - down)[:2]))
        length = float(np.linalg.norm(up - down))
        vertical = horizontal < 0.1 * length
        # pipes feeding this one (children in the tree, through fittings)
        feeding = []
        stack = [c for c in net["adjacency"].get(g, []) if net["tree"].get(c) == g]
        while stack:
            c = stack.pop()
            if c in chosen:
                feeding.append(chosen[c])
            elif c not in segs:
                stack.extend(x for x in net["adjacency"].get(c, []) if net["tree"].get(x) == c)
        floor_dn = max([min_dn.get(g, 0.0)] + feeding)
        status, slope = "ok", None
        if vertical:
            dn = next((d for d, cap in stack_cap if cap >= q and d >= floor_dn), None)
            if dn is None:
                dn, status = stack_cap[-1][0], "largest stack exceeded"
            if kind != "storm" and sum_du.get(g, 0.0) > cfg["vent_du_limit"] and not vent_exists:
                warnings.append(f"{e.Name or 'Stack'} carries {sum_du[g]:.1f} DU and the model has no vent system")
            fill = None
        else:
            slope = (up[2] - down[2]) / horizontal
            dn = None
            for d_nom, inner in series:
                if d_nom < floor_dn:
                    continue
                fill = cfg["fill_ratio_large"] if d_nom >= 150 else cfg["fill_ratio"]
                if capacity(inner, max(slope, 1e-9), fill, cfg["manning_n"]) >= q:
                    dn = d_nom
                    break
            if dn is None:
                dn, status = series[-1][0], "largest size exceeded"
            fill = cfg["fill_ratio_large"] if dn >= 150 else cfg["fill_ratio"]
            minimum = cfg["min_slope_large"] if dn >= 100 else cfg["min_slope_small"]
            if slope < -1e-6:
                status = "falls the wrong way"
            elif slope < minimum - 1e-9:
                status = f"below the {minimum * 100:g} % minimum slope"
            elif slope > cfg["max_slope"]:
                status = f"steeper than {cfg['max_slope'] * 100:g} %"
        chosen[g] = dn
        inner = dict(series).get(dn, dn / 1000)
        rows[g] = {"guid": g, "name": e.Name or "Pipe", "discharge_units": round(sum_du.get(g, 0.0), 2),
                   "flow": round(q, 3), "vertical": vertical, "slope": round(slope, 4) if slope is not None else None,
                   "dn": dn, "diameter": dn / 1000, "inner": inner,
                   "capacity": round(capacity(inner, max(slope or 0, 1e-9), fill, cfg["manning_n"]), 3)
                   if not vertical else dict(stack_cap).get(dn), "length": round(length, 3), "status": status}
    out_rows = [rows[g] for g in net["order"] if g in rows]
    for r in out_rows:
        if r["status"] != "ok":
            warnings.append(f"{r['name']}: {r['status']}")
    report = {"ok": True, "system": group.Name, "kind": kind, "segments": out_rows, "warnings": warnings,
              "outlet_flow": round(max((r["flow"] for r in out_rows), default=0.0), 3),
              "total_discharge_units": round(sum(own_du.values()), 2),
              "terminals": [{"guid": g, "name": net["elements"][g].Name or "", "discharge_units": own_du.get(g),
                             "flow": round(own_flow.get(g, 0.0), 3)} for g in terminals],
              "method": ("Q = K√ΣDU (EN 12056-2 system I)" if kind != "storm" else "Q = r·A·C") +
                        "; Manning part-full capacity; stacks by EN 12056-2 table 11",
              "assumptions": [
                  f"K = {cfg['k_factor']:g}" if kind != "storm" else
                  f"Rain {cfg['rain_intensity']:g} L/s·m², run-off coefficient {cfg['runoff_coefficient']:g}",
                  f"Manning n {cfg['manning_n']:g}; fill {cfg['fill_ratio'] * 100:g} % (DN ≥ 150: "
                  f"{cfg['fill_ratio_large'] * 100:g} %)",
                  f"Minimum slope {cfg['min_slope_large'] * 100:g} % from DN 100, {cfg['min_slope_small'] * 100:g} % below",
                  "Design aid: check with the drainage engineer"]}
    if apply:
        seg_rows = [{"guid": r["guid"], "width": r["diameter"], "height": r["diameter"],
                     "design": {"Flow": float(r["flow"]), "Nominal": str(r["dn"]),
                                "Slope": float(r["slope"]) if r["slope"] is not None else 0.0}} for r in out_rows]
        sizes = {r["guid"]: (r["diameter"], r["diameter"]) for r in out_rows}
        try:
            report.update(mepcalc.apply_sizes(seg_rows, mepcalc.fitting_sizes(net, sizes), "drainage"))
        except Exception as ex:  # noqa: BLE001
            return A._fail(f"{type(ex).__name__}: {ex}")
        report["applied"] = True
    return B._dump(report)


def create_drain_run(storey_guid: str, points_json: str, start_z, slope="", diameter=0.11, system: str = "") -> str:
    """A drain pipe through plan points [[x, y], ...] falling at `slope` (blank: the default slope)
    from `start_z` above the level at the first point, downhill in the drawing direction."""
    cfg = engsettings.get("drainage_settings") if B._model is not None else None
    try:
        pts = [(float(p[0]), float(p[1])) for p in json.loads(points_json)]
        z = float(start_z)
        s = cfg["default_slope"] if slope in ("", None) else float(slope)
    except (TypeError, ValueError, IndexError) as ex:
        return A._fail(str(ex))
    if cfg is None:
        return A._fail("no model open")
    if not 0 <= s <= 1:
        return A._fail("the slope is a fraction between 0 and 1 (2 % = 0.02)")
    out = [[pts[0][0], pts[0][1], z]]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        z -= s * math.hypot(x1 - x0, y1 - y0)
        out.append([x1, y1, z])
    return mep._run3d(storey_guid, "pipe", json.dumps(out), diameter, diameter, system, "sanitary" if not system else "")
