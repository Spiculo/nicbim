# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared pieces of the MEP calculations (D243-D246): tree sums, friction, resizing, reporting.

A system's :func:`mep.network` is a tree rooted at its source (for drainage, its outlet). Values
put on terminals (flows, loading or discharge units) add up towards the root with
:func:`accumulate`, so every segment carries the sum of what lies beyond it.
"""
from __future__ import annotations

import math

import ifcopenshell.api.pset
import ifcopenshell.util.element
import numpy as np

from . import app_bridge as B
from . import authoring as A
from . import mep


def system_or_error(system: str, domains: tuple[str, ...]):
    """(system entity, None) or (None, message)."""
    if B._model is None:
        return None, "no model open"
    group = mep._find_system(system)
    if group is None:
        return None, f"unknown system {system}"
    kind = mep.system_kind(group)
    domain = mep.SYSTEM_KINDS.get(kind, {}).get("domain")
    if domain not in domains:
        return None, f"{group.Name} is not a {' or '.join(domains)} system"
    return group, None


def post_order(net: dict) -> list[str]:
    """Guids leaves-first (every node after all of its children)."""
    return list(reversed(net["order"]))


def accumulate(net: dict, own: dict[str, float]) -> dict[str, float]:
    """Each reached node's value plus everything beyond it (away from the root)."""
    total = {g: float(own.get(g, 0.0)) for g in net["tree"]}
    for g in post_order(net):
        parent = net["tree"][g]
        if parent is not None:
            total[parent] += total[g]
    return total


def accumulate_max(net: dict, own: dict[str, float]) -> dict[str, float]:
    """The largest value at or beyond each node."""
    best = {g: float(own.get(g, 0.0)) for g in net["tree"]}
    for g in post_order(net):
        parent = net["tree"][g]
        if parent is not None:
            best[parent] = max(best[parent], best[g])
    return best


def count_beyond(net: dict, flags: dict[str, bool]) -> dict[str, int]:
    return {g: int(v) for g, v in accumulate(net, {k: 1.0 for k, f in flags.items() if f}).items()}


def segments(net: dict) -> dict:
    """guid -> element for the straight segments reached in the network."""
    out = {}
    for g in net["tree"]:
        e = net["elements"][g]
        if mep.role(e) == "part" and mep.segment_ends(e) is not None and not _is_fitting(e):
            out[g] = e
    return out


def _is_fitting(e) -> bool:
    return e.is_a("IfcFlowFitting") or e.is_a("IfcDuctFitting") or e.is_a("IfcPipeFitting") \
        or e.is_a("IfcCableCarrierFitting") or (ifcopenshell.util.element.get_pset(e, mep.MEP_PSET) or {}).get("Fitting")


def fittings(net: dict) -> dict:
    return {g: e for g, e in ((g, net["elements"][g]) for g in net["tree"]) if _is_fitting(e)}


def length(e) -> float:
    ends = mep.segment_ends(e)
    return float(np.linalg.norm(ends[1] - ends[0])) if ends else 0.0


def friction_factor(re: float, relative_roughness: float) -> float:
    """Darcy friction factor: 64/Re when laminar, Swamee-Jain (explicit Colebrook) when turbulent."""
    if re <= 0:
        return 0.0
    if re < 2300:
        return 64.0 / re
    return 0.25 / math.log10(relative_roughness / 3.7 + 5.74 / re ** 0.9) ** 2


def gradient(velocity: float, diameter: float, density: float, viscosity: float, roughness: float) -> float:
    """Friction pressure gradient (Pa/m) for a flow at `velocity` in a pipe/duct of hydraulic diameter."""
    if diameter <= 0 or velocity <= 0:
        return 0.0
    re = velocity * diameter / viscosity
    f = friction_factor(re, roughness / diameter)
    return f / diameter * density * velocity ** 2 / 2


def path_totals(net: dict, own: dict[str, float]) -> dict[str, float]:
    """Each node's value summed along the path from the root to it."""
    total = {}
    for g in net["order"]:
        parent = net["tree"][g]
        total[g] = (total[parent] if parent is not None else 0.0) + float(own.get(g, 0.0))
    return total


def terminal_guids(net: dict) -> list[str]:
    return [g for g in net["tree"] if mep.role(net["elements"][g]) == "terminal"]


def room_of(element):
    """The room (IfcSpace) whose outline holds the element's insertion point, or None."""
    from . import structanalysis as SA

    m = mep._matrix(element)
    p = m[:3, 3]
    best = None
    for space in B._model.by_type("IfcSpace"):
        outline = SA._slab_outline(space)
        if outline is None:
            continue
        poly, z0, z1, _t = outline
        if z0 - 0.5 <= p[2] <= z1 + 0.5 and SA._inside(p[None, :2], poly)[0]:
            if best is None or z0 > best[1]:
                best = (space, z0)
    return best[0] if best else None


def room_area_volume(space) -> tuple[float, float]:
    from . import structanalysis as SA

    outline = SA._slab_outline(space)
    if outline is None:
        return 0.0, 0.0
    poly, z0, z1, _t = outline
    area = SA._polygon_area(poly)
    return area, area * max(z1 - z0, 0.0)


def _profile(element):
    rep = getattr(element, "Representation", None)
    for shape in (rep.Representations if rep else ()):
        for item in shape.Items or ():
            if item.is_a("IfcExtrudedAreaSolid"):
                return item
    return None


def _own_profile(item):
    """The extrusion's profile, copied first when another item shares it."""
    f = B._model
    profile = item.SweptArea
    if len([x for x in f.get_inverse(profile) if x.is_a("IfcExtrudedAreaSolid")]) > 1:
        profile = ifcopenshell.util.element.copy(f, profile)
        item.SweptArea = profile
    return profile


def resize_segment(element, width: float, height: float) -> bool:
    """Inside an action: a straight segment's section becomes width x height (a pipe: diameter =
    width). Returns True when the geometry changed."""
    item = _profile(element)
    if item is None:
        return False
    s = A._scale()
    profile = _own_profile(item)
    changed = False
    if profile.is_a("IfcCircleProfileDef"):
        r = width / 2 / s
        if abs(float(profile.Radius) - r) > 1e-9:
            profile.Radius = r
            changed = True
    elif profile.is_a("IfcRectangleProfileDef"):
        if abs(float(profile.XDim) - width / s) > 1e-9 or abs(float(profile.YDim) - height / s) > 1e-9:
            profile.XDim, profile.YDim = width / s, height / s
            changed = True
    pset = ifcopenshell.util.element.get_pset(element, mep.MEP_PSET)
    if pset:
        ifcopenshell.api.pset.edit_pset(B._model, pset=B._model.by_id(pset["id"]), properties={
            "Width": float(width), "Height": float(height)})
    return changed


def resize_fitting(element, size: float, height: float) -> bool:
    item = _profile(element)
    if item is None:
        return False
    s = A._scale()
    profile = _own_profile(item)
    if not profile.is_a("IfcRectangleProfileDef"):
        return False
    old_h = float(item.Depth) * s
    if abs(float(profile.XDim) * s - size) < 1e-9 and abs(old_h - height) < 1e-9:
        return False
    profile.XDim = profile.YDim = size / s
    item.Depth = height / s
    # keep the fitting centred on its ports: its placement is its base, so move it by half the change
    placement = element.ObjectPlacement.RelativePlacement.Location
    coords = list(placement.Coordinates)
    coords[2] = float(coords[2]) - (height - old_h) / 2 / s
    placement.Coordinates = tuple(coords)
    _shift_ports(element, (height - old_h) / 2)
    return True


def _shift_ports(element, dz: float) -> None:
    """Ports are placed relative to the element: moving the element down by dz moves them; put them back."""
    s = A._scale()
    for port, _q in mep.port_points(element):
        loc = port.ObjectPlacement.RelativePlacement.Location
        c = list(loc.Coordinates)
        c[2] = float(c[2]) + dz / s
        loc.Coordinates = tuple(c)


def write_design(element, values: dict) -> None:
    f = B._model
    pset = ifcopenshell.util.element.get_pset(element, mep.DESIGN_PSET)
    pset = f.by_id(pset["id"]) if pset else ifcopenshell.api.pset.add_pset(f, product=element, name=mep.DESIGN_PSET)
    ifcopenshell.api.pset.edit_pset(f, pset=pset, properties=values)


def apply_sizes(rows: list[dict], fitting_rows: list[dict], tag: str) -> dict:
    """Write sizes and design values as one undo step. rows: {guid, width, height, design{...}}."""
    def action():
        changed = []
        for row in rows:
            e = B._model.by_guid(row["guid"])
            if row.get("width"):
                if resize_segment(e, row["width"], row.get("height") or row["width"]):
                    changed.append(row["guid"])
            write_design(e, {**row.get("design", {}), "SizedBy": tag})
        for row in fitting_rows:
            e = B._model.by_guid(row["guid"])
            if resize_fitting(e, row["size"], row["height"]):
                changed.append(row["guid"])
        return len(rows) + len(fitting_rows), changed, []

    return B._run(action)


def fitting_sizes(net: dict, sizes: dict[str, tuple[float, float]]) -> list[dict]:
    """Each fitting takes the largest section of the segments it joins (a little bigger)."""
    out = []
    for g, e in fittings(net).items():
        near = [n for n in net["adjacency"].get(g, []) if n in sizes]
        if not near:
            continue
        w = max(sizes[n][0] for n in near)
        h = max(sizes[n][1] for n in near)
        out.append({"guid": g, "size": max(w, h) * 1.05, "height": h * 1.05})
    return out


def mm(v: float) -> int:
    return int(round(v * 1000))
