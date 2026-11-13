# SPDX-License-Identifier: GPL-3.0-or-later
"""Structural integrity (D247): loads, supports, a frame analysis and member checks.

From the physical model:

* **Members**: columns, beams and structural members become frame members along their section's
  centroid axis (the D224 analytical axis corrected for the profile offset). Ends within
  ``merge_tolerance`` share a node; a beam end inside a column's section snaps to the column's
  axis (and to its top when it sits on it), and members are split where another member's node lies
  on them. Beams are subdivided about every metre so slab loads follow their real distribution.
* **Supports**: the bottom of a column with nothing under it is fixed or pinned
  (``base_support``); a beam end on a load-bearing wall is pinned. Pinned supports get a token
  rotational spring so a member cannot spin about its own axis.
* **Loads** (EN 1991 defaults): G = self-weight of members (density x area) and slabs (density x
  thickness) plus the superimposed dead load, Q = imposed load by use category (per level,
  ``level_use``), S = snow on roofs. A slab's area load goes to its nearest support — a beam under
  or along it, a bearing wall, or a column under it — which is the 45° envelope for a slab on
  beams all round (one-way action for long panels follows from it). What reaches walls is reported
  as wall line loads.
* **Combinations** (EN 1990): ULS 1.35 G + 1.5 Q + 0.75 S and SLS G + Q + 0.5 S (settings).
* **Checks**: steel (EN 1993 cross-section N/A + My/Wy + Mz/Wz with the flexural buckling
  reduction χ from curve b for compression, and shear), timber (the same with its bending
  strength) and concrete (indicative compressive stress only: no reinforcement design), plus
  deflection against L/250 (L/125 cantilevers) in the SLS combination.

Results go to ``KIMBIM_StructuralResult`` on each physical member, and in IFC4 to the analysis
model: supports (IfcStructuralPointConnection + IfcBoundaryNodeCondition), load cases and
combinations (IfcStructuralLoadGroup), member line loads (IfcStructuralCurveAction) and the
support reactions (IfcStructuralPointReaction in an IfcStructuralResultGroup per combination).

This is a design aid for early checks, not a certified calculation.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.guid
import ifcopenshell.util.element
import ifcopenshell.util.placement
import numpy as np

from . import app_bridge as B
from . import authoring as A
from . import engsettings, frame, sections

RESULT_PSET = "KIMBIM_StructuralResult"
TAG = "KIMBIM analysis"
CASES = ("G", "Q", "S")
METHOD = ("Linear-elastic 3D frame (direct stiffness, Euler-Bernoulli members); slab loads to the nearest "
          "support; EN 1990 combinations; EN 1993-1-1 cross-section and flexural buckling (curve b) for steel")
PIN_SPRING = 1.0  # kN·m/rad: keeps pinned members from spinning about their axis
COLOURS = {"pass": "#2e9e44", "warn": "#e0a100", "fail": "#d0312d", "none": "#9a9a9a"}


@dataclass
class Member:
    element: object
    kind: str  # column | beam | member
    a: np.ndarray
    b: np.ndarray
    zref: np.ndarray
    section: dict
    material: dict
    material_name: str
    category: str
    subs: list = field(default_factory=list)  # [(frame member index, t0, t1)]

    @property
    def length(self) -> float:
        return float(np.linalg.norm(self.b - self.a))


@dataclass
class Analysis:
    nodes: list
    members: list  # physical Member
    frame_members: list  # dicts for frame.solve
    supports: dict
    cases: dict  # case -> {"node": {i: 6 values}, "member": [{member, w}]}
    wall_loads: dict  # wall guid -> {case: kN}
    slab_loads: dict  # slab guid -> {case: kN, "area": m2, "dropped": bool}
    warnings: list
    excluded: list  # physical members left out (unsupported parts)
    support_kind: dict  # node -> "fixed" | "pinned" | "wall"


# ---------------------------------------------------------------- geometry

def _scale() -> float:
    return A._scale()


def _body(element):
    rep = getattr(element, "Representation", None)
    for shape in (rep.Representations if rep else ()):
        if shape.RepresentationIdentifier not in (None, "Body", "Facetation"):
            continue
        for item in shape.Items or ():
            if item.is_a("IfcMappedItem"):
                continue
            if item.is_a("IfcExtrudedAreaSolid"):
                return item
    return None


def member_axis(element):
    """(start, end, zref, profile) in metres: the section centroid's line along the extrusion, and the
    profile's Y direction (the section depth) as the member's local z reference."""
    item = _body(element)
    if item is None:
        return None
    s = _scale()
    M = np.array(ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement), float)
    P = np.array(ifcopenshell.util.placement.get_axis2placement(item.Position), float) if item.Position else np.eye(4)
    W = M @ P
    profile = item.SweptArea
    centre = np.zeros(2)
    if getattr(profile, "Position", None) is not None:
        centre = np.array(ifcopenshell.util.placement.get_axis2placement(profile.Position), float)[:2, 3]
    # outlines (arbitrary, L, T, U, C, Z) are not centred on their origin: use their centroid
    pts = sections._curve_points(getattr(profile, "OuterCurve", None), 1.0)
    if not pts:
        pts, _kind = sections._shape_points(profile, 1.0)
    if pts:
        centre = centre + _centroid(np.array(pts, float))
    d = np.array(item.ExtrudedDirection.DirectionRatios, float)
    d = d / np.linalg.norm(d)
    start = W @ np.array([centre[0], centre[1], 0.0, 1.0])
    end = W @ np.array([*(np.array([centre[0], centre[1], 0.0]) + d * float(item.Depth)), 1.0])
    zref = W[:3, :3] @ np.array([0.0, 1.0, 0.0])
    return start[:3] * s, end[:3] * s, zref / np.linalg.norm(zref), profile


def _centroid(pts: np.ndarray) -> np.ndarray:
    x, y = pts[:, 0], pts[:, 1]
    x1, y1 = np.roll(x, -1), np.roll(y, -1)
    c = x * y1 - x1 * y
    a = c.sum() / 2
    if abs(a) < 1e-12:
        return pts.mean(axis=0)
    return np.array([((x + x1) * c).sum() / (6 * a), ((y + y1) * c).sum() / (6 * a)])


def _slab_outline(slab):
    """(2D outline points in metres, z bottom, z top, thickness) of a slab or roof slab."""
    item = _body(slab)
    if item is None:
        return None
    s = _scale()
    M = np.array(ifcopenshell.util.placement.get_local_placement(slab.ObjectPlacement), float)
    P = np.array(ifcopenshell.util.placement.get_axis2placement(item.Position), float) if item.Position else np.eye(4)
    W = M @ P
    profile = item.SweptArea
    pts = sections._curve_points(getattr(profile, "OuterCurve", None), 1.0)
    if not pts and profile.is_a("IfcRectangleProfileDef"):
        x, y = float(profile.XDim) / 2, float(profile.YDim) / 2
        pts = [(-x, -y), (x, -y), (x, y), (-x, y)]
    if len(pts) < 3:
        return None
    if getattr(profile, "Position", None) is not None:
        Pp = np.array(ifcopenshell.util.placement.get_axis2placement(profile.Position), float)
        pts = [tuple((Pp @ np.array([x, y, 0, 1.0]))[:2]) for x, y in pts]
    d = np.array(item.ExtrudedDirection.DirectionRatios, float)
    depth = float(item.Depth)
    bottom = [(W @ np.array([x, y, 0.0, 1.0]))[:3] * s for x, y in pts]
    top = [(W @ np.array([x + d[0] * depth, y + d[1] * depth, d[2] * depth, 1.0]))[:3] * s for x, y in pts]
    z0 = min(min(p[2] for p in bottom), min(p[2] for p in top))
    z1 = max(max(p[2] for p in bottom), max(p[2] for p in top))
    return np.array([p[:2] for p in bottom]), z0, z1, z1 - z0


def _wall_line(wall):
    """(2D axis start, end, thickness, top z, bottom z) of a straight wall, in metres."""
    s = _scale()
    M = np.array(ifcopenshell.util.placement.get_local_placement(wall.ObjectPlacement), float)
    axis = None
    rep = getattr(wall, "Representation", None)
    for shape in (rep.Representations if rep else ()):
        if shape.RepresentationIdentifier == "Axis":
            for item in shape.Items or ():
                pts = sections._curve_points(item, 1.0)
                if len(pts) >= 2:
                    axis = (pts[0], pts[-1])
    item = _body(wall)
    if item is None:
        return None
    depth = float(item.Depth)
    thickness = 0.0
    profile = item.SweptArea
    ppts = sections._curve_points(getattr(profile, "OuterCurve", None), 1.0)
    if profile.is_a("IfcRectangleProfileDef"):
        thickness = float(profile.YDim)
    elif ppts:
        ys = [p[1] for p in ppts]
        thickness = max(ys) - min(ys)
        if axis is None:
            xs = [p[0] for p in ppts]
            mid = (max(ys) + min(ys)) / 2
            axis = ((min(xs), mid), (max(xs), mid))
    if axis is None:
        return None
    a = (M @ np.array([axis[0][0], axis[0][1], 0.0, 1.0]))[:3] * s
    b = (M @ np.array([axis[1][0], axis[1][1], 0.0, 1.0]))[:3] * s
    return a[:2], b[:2], thickness * s, float(a[2] + depth * s), float(a[2])


def _seg_distance(points: np.ndarray, a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Distances of 2D points to segment ab and their parameter t (0..1) along it."""
    ab = b - a
    L2 = float(ab @ ab)
    if L2 < 1e-12:
        return np.linalg.norm(points - a, axis=1), np.zeros(len(points))
    t = np.clip(((points - a) @ ab) / L2, 0.0, 1.0)
    return np.linalg.norm(points - (a + np.outer(t, ab)), axis=1), t


def _inside(points: np.ndarray, poly: np.ndarray) -> np.ndarray:
    x, y = points[:, 0], points[:, 1]
    inside = np.zeros(len(points), bool)
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        cross = ((y0 > y) != (y1 > y))
        with np.errstate(divide="ignore", invalid="ignore"):
            xi = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
        inside ^= cross & (x < xi)
    return inside


def _polygon_area(poly: np.ndarray) -> float:
    x, y = poly[:, 0], poly[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y)) / 2)


# ---------------------------------------------------------------- materials

def _material_names(element) -> list[tuple[str, str]]:
    """[(name, category)] of the element's materials (profile/layer/constituent sets included)."""
    out = []
    mat = ifcopenshell.util.element.get_material(element, should_skip_usage=True)
    if mat is None:
        etype = ifcopenshell.util.element.get_type(element)
        mat = ifcopenshell.util.element.get_material(etype, should_skip_usage=True) if etype else None
    if mat is None:
        return out
    items = []
    if mat.is_a("IfcMaterial"):
        items = [mat]
    elif mat.is_a("IfcMaterialProfileSet"):
        items = [p.Material for p in mat.MaterialProfiles or () if p.Material]
    elif mat.is_a("IfcMaterialLayerSet"):
        items = [l.Material for l in mat.MaterialLayers or () if l.Material]
    elif mat.is_a("IfcMaterialConstituentSet"):
        items = [c.Material for c in mat.MaterialConstituents or () if c.Material]
    elif mat.is_a("IfcMaterialList"):
        items = list(mat.Materials or ())
    for m in items:
        out.append((m.Name or "", getattr(m, "Category", None) or ""))
    return out


CATEGORY_WORDS = {
    "steel": ("steel", "acero", "s235", "s275", "s355", "s420", "s460", "metal", "acier", "stahl"),
    "concrete": ("concrete", "hormig", "concreto", "beton", "c20", "c25", "c30", "c35", "c40", "cement"),
    "timber": ("timber", "wood", "madera", "glulam", "gl24", "gl28", "c16", "c24", "clt", "holz", "bois"),
}


def material_for(element, settings: dict, kind: str, section: dict | None) -> tuple[dict, str, str, str | None]:
    """(properties, name, category, warning) for a member, from its material name or category."""
    table = settings["materials"]
    names = _material_names(element)
    for name, category in names:
        if name in table:
            return table[name], name, _category_of(name, category) or "steel", None
    for name, category in names:
        cat = _category_of(name, category)
        if cat and cat in table:
            return table[cat], name, cat, None
    guess = "steel" if section and section.get("kind") in ("I", "L", "T", "U", "C", "Z", "rectangle_hollow",
                                                             "circle_hollow") else "concrete"
    label = names[0][0] if names else "no material"
    return table[guess], label, guess, (f"{element.Name or element.is_a()}: material '{label}' is not in the "
                                       f"structural materials table, analysed as {guess}")


def _category_of(name: str, category: str) -> str:
    text = f"{name} {category}".lower()
    for cat, words in CATEGORY_WORDS.items():
        if any(w in text for w in words):
            return cat
    return ""


# ---------------------------------------------------------------- building the model

def _physical_members(settings, warnings) -> list[Member]:
    out = []
    f = B._model
    for cls, kind in (("IfcColumn", "column"), ("IfcBeam", "beam"), ("IfcMember", "member")):
        for e in f.by_type(cls):
            axis = member_axis(e)
            if axis is None:
                warnings.append(f"{e.Name or cls}: no straight extruded body, left out of the analysis")
                continue
            a, b, zref, profile = axis
            if np.linalg.norm(b - a) < 0.05:
                continue
            sec = sections.section(profile, _scale())
            if sec is None:
                warnings.append(f"{e.Name or cls}: profile {profile.is_a()} is not supported, left out")
                continue
            props, name, category, warning = material_for(e, settings, kind, sec)
            if warning:
                warnings.append(warning)
            out.append(Member(e, kind, a, b, zref, sec, props, name, category))
    return out


def _snap_to_columns(members: list[Member], tol: float) -> None:
    columns = [m for m in members if m.kind == "column"]
    for m in members:
        if m.kind == "column":
            continue
        for end in ("a", "b"):
            p = getattr(m, end)
            for c in columns:
                d = c.b - c.a
                L = float(np.linalg.norm(d))
                t = float(np.dot(p - c.a, d) / (L * L))
                q = c.a + d * np.clip(t, 0, 1)
                horizontal = np.linalg.norm((p - (c.a + d * t))[:2]) if abs(d[2]) > 0.5 * L else np.linalg.norm(p - q)
                reach = max(c.section["b"], c.section["h"]) / 2 + tol
                above = (t - 1) * L
                if horizontal <= reach and -tol / L <= t and above <= m.section["h"] + tol:
                    setattr(m, end, q.copy())
                    break


def _merge_nodes(points: list[np.ndarray], tol: float) -> tuple[list[np.ndarray], list[int]]:
    nodes: list[np.ndarray] = []
    index = []
    for p in points:
        for i, q in enumerate(nodes):
            if np.linalg.norm(p - q) <= tol:
                index.append(i)
                break
        else:
            nodes.append(p.copy())
            index.append(len(nodes) - 1)
    return nodes, index


def _bearing_walls(settings) -> list:
    mode = settings["bearing_walls"]
    if mode == "none":
        return []
    out = []
    for w in B._model.by_type("IfcWall"):
        common = ifcopenshell.util.element.get_pset(w, "Pset_WallCommon") or {}
        bearing = common.get("LoadBearing")
        if (mode == "marked_only" and bearing is True) or (mode == "unless_marked" and bearing is not False):
            line = _wall_line(w)
            if line is not None:
                out.append((w, *line))
    return out


def build(settings: dict | None = None) -> Analysis:
    """The analysis model of the open model (see the module notes)."""
    settings = settings or engsettings.get("structure_settings")
    tol = float(settings["merge_tolerance"])
    warnings: list[str] = []
    members = _physical_members(settings, warnings)
    _snap_to_columns(members, tol)
    walls = _bearing_walls(settings)
    nodes, index = _merge_nodes([p for m in members for p in (m.a, m.b)], tol)
    end_nodes = [(index[2 * k], index[2 * k + 1]) for k in range(len(members))]
    # split members at nodes lying on them, and subdivide beams about every metre
    frame_members = []
    for k, m in enumerate(members):
        i0, j0 = end_nodes[k]
        d = m.b - m.a
        L = m.length
        cuts = []
        for n_i, q in enumerate(nodes):
            if n_i in (i0, j0):
                continue
            t = float(np.dot(q - m.a, d) / (L * L))
            if tol / L < t < 1 - tol / L and np.linalg.norm(m.a + d * t - q) <= tol:
                cuts.append((t, n_i))
        if m.kind != "column":
            parts = min(8, max(1, math.ceil(L / 1.0)))
            known = [t for t, _ in cuts]
            for p in range(1, parts):
                t = p / parts
                if all(abs(t - c) * L > 0.2 for c in known):
                    nodes.append(m.a + d * t)
                    cuts.append((t, len(nodes) - 1))
        cuts.sort()
        chain = [(0.0, i0)] + cuts + [(1.0, j0)]
        for (t0, n0), (t1, n1) in zip(chain, chain[1:]):
            mat, sec = m.material, m.section
            frame_members.append({"i": n0, "j": n1, "E": mat["E"], "G": mat["G"], "A": sec["A"], "Iy": sec["Iy"],
                                  "Iz": sec["Iz"], "J": max(sec["J"], 1e-9), "zref": m.zref, "phys": k})
            m.subs.append((len(frame_members) - 1, t0, t1))
    # supports
    supports, support_kind = {}, {}
    pinned = settings["base_support"] == "pinned"
    on_top = {}  # nodes that are the top or an interior node of something
    for fm in frame_members:
        lo, hi = (fm["i"], fm["j"]) if nodes[fm["i"]][2] <= nodes[fm["j"]][2] else (fm["j"], fm["i"])
        on_top.setdefault(hi, 0)
        on_top[hi] += 1
    lowest_of_column = {}
    for k, m in enumerate(members):
        if m.kind != "column":
            continue
        sub = m.subs[0] if m.a[2] <= m.b[2] else m.subs[-1]
        fm = frame_members[sub[0]]
        low = fm["i"] if nodes[fm["i"]][2] <= nodes[fm["j"]][2] else fm["j"]
        lowest_of_column[low] = k
    for node in lowest_of_column:
        below = any(node in (fm["i"], fm["j"]) and max(nodes[fm["i"]][2], nodes[fm["j"]][2]) > nodes[node][2] + tol
                    and min(nodes[fm["i"]][2], nodes[fm["j"]][2]) < nodes[node][2] - tol for fm in frame_members)
        lower_member = any(node in (fm["i"], fm["j"]) and min(nodes[fm["i"]][2], nodes[fm["j"]][2]) < nodes[node][2] - tol
                           for fm in frame_members)
        if below or lower_member:
            continue
        if pinned:
            supports[node] = (True, True, True, PIN_SPRING, PIN_SPRING, PIN_SPRING)
            support_kind[node] = "pinned"
        else:
            supports[node] = (True,) * 6
            support_kind[node] = "fixed"
    degree = {}
    for fm in frame_members:
        for n_ in (fm["i"], fm["j"]):
            degree[n_] = degree.get(n_, 0) + 1
    for k, m in enumerate(members):  # beam ends on bearing walls
        if m.kind == "column":
            continue
        for end, p in (("a", m.a), ("b", m.b)):
            node = end_nodes[k][0 if end == "a" else 1]
            if node in supports:
                continue
            for w, wa, wb, thick, top, _bottom in walls:
                dist, _t = _seg_distance(p[None, :2], wa, wb)
                if dist[0] <= thick / 2 + tol + 0.05 and abs(p[2] - top) <= m.section["h"] + 0.3:
                    supports[node] = (True, True, True, PIN_SPRING, PIN_SPRING, PIN_SPRING)
                    support_kind[node] = "wall"
                    break
    analysis = Analysis(nodes=nodes, members=members, frame_members=frame_members, supports=supports,
                        cases={c: {"node": {}, "member": []} for c in CASES}, wall_loads={}, slab_loads={},
                        warnings=warnings, excluded=[], support_kind=support_kind)
    _self_weight(analysis)
    _slab_loads(analysis, settings, walls)
    _drop_unsupported(analysis)
    return analysis


def _self_weight(an: Analysis) -> None:
    for k, m in enumerate(an.members):
        w = m.material["density"] * m.section["A"]
        for idx, _t0, _t1 in m.subs:
            an.cases["G"]["member"].append({"member": idx, "w": (0.0, 0.0, -w)})


def _storey_name(element) -> str:
    container = ifcopenshell.util.element.get_container(element)
    if container is None:
        agg = ifcopenshell.util.element.get_aggregate(element)
        container = ifcopenshell.util.element.get_container(agg) if agg else None
    return (container.Name or "") if container is not None else ""


def _is_roof(slab) -> bool:
    if slab.is_a("IfcRoof"):
        return True
    if getattr(slab, "PredefinedType", None) == "ROOF":
        return True
    agg = ifcopenshell.util.element.get_aggregate(slab)
    return bool(agg is not None and agg.is_a("IfcRoof"))


def _slabs():
    out = []
    for s in B._model.by_type("IfcSlab"):
        if getattr(s, "PredefinedType", None) in ("LANDING", "BASESLAB"):
            continue
        out.append(s)
    return out


def _slab_loads(an: Analysis, settings: dict, walls: list) -> None:
    concrete = settings["materials"].get("concrete", {"density": 25.0})
    use_loads = settings["use_loads"]
    level_use = settings.get("level_use") or {}
    for slab in _slabs():
        outline = _slab_outline(slab)
        if outline is None:
            continue
        poly, z0, z1, thickness = outline
        area = _polygon_area(poly)
        if area < 0.01:
            continue
        roof = _is_roof(slab)
        props, _name, _cat, _w = material_for(slab, settings, "slab", None)
        density = props.get("density", concrete["density"])
        g = density * thickness + float(settings["superimposed_dead"])
        use = level_use.get(_storey_name(slab), settings["default_use"])
        if roof:
            use = "H"
        if use not in use_loads:
            an.warnings.append(f"{slab.Name or 'Slab'}: use category '{use}' has no load, {settings['default_use']} used")
            use = settings["default_use"]
        q = float(use_loads.get(use, 2.0))
        sn = float(settings["snow"]) if roof else 0.0
        # supports of this slab: beams under/along it, bearing walls under it, columns under it
        lines, points = [], []  # (kind, ref, a2, b2) / (node, xy)
        for k, m in enumerate(an.members):
            if m.kind == "column":
                top = m.a if m.a[2] >= m.b[2] else m.b
                if z0 - 0.15 - 0.3 <= top[2] <= z1 + 0.15 and (
                        _inside(top[None, :2], poly)[0] or _seg_dist_poly(top[:2], poly) <= 0.3):
                    top_node = _nearest_node(an, top)
                    points.append(("column", top_node, top[:2]))
                continue
            if abs(m.a[2] - m.b[2]) > 0.25 * m.length:  # sloping members do not carry slabs here
                continue
            zmid = (m.a[2] + m.b[2]) / 2
            if not (z0 - m.section["h"] - 0.15 <= zmid <= z1 + 0.05):
                continue
            mid = (m.a[:2] + m.b[:2]) / 2
            if _inside(mid[None, :], poly)[0] or _seg_dist_poly(mid, poly) <= 0.3:
                lines.append(("beam", k, m.a[:2], m.b[:2]))
        for w, wa, wb, thick, top, _bottom in walls:
            if abs(top - z0) <= 0.3 or (z0 - 0.3 <= top <= z1):
                mid = (wa + wb) / 2
                if _inside(mid[None, :], poly)[0] or _seg_dist_poly(mid, poly) <= thick / 2 + 0.3:
                    lines.append(("wall", w.GlobalId, wa, wb))
        record = {"area": round(area, 3), "G": g * area, "Q": q * area, "S": sn * area, "use": use, "dropped": False}
        an.slab_loads[slab.GlobalId] = record
        if not lines and not points:
            record["dropped"] = True
            an.warnings.append(f"{slab.Name or 'Slab'}: nothing supports it (no beams, bearing walls or columns "
                               f"found under it); its load is not in the analysis")
            continue
        # sample the slab and give each cell to its nearest support
        xmin, ymin = poly.min(axis=0)
        xmax, ymax = poly.max(axis=0)
        cell = max(0.1, math.sqrt(area / 6000.0))
        xs = np.arange(xmin + cell / 2, xmax, cell)
        ys = np.arange(ymin + cell / 2, ymax, cell)
        grid = np.array([(x, y) for y in ys for x in xs]) if len(xs) and len(ys) else np.zeros((0, 2))
        grid = grid[_inside(grid, poly)] if len(grid) else grid
        if not len(grid):
            grid = poly.mean(axis=0)[None, :]
        weight = area / len(grid)  # m2 per sample
        dists, params = [], []
        for _kind, _ref, a2, b2 in lines:
            dd, tt = _seg_distance(grid, a2, b2)
            dists.append(dd)
            params.append(tt)
        for _kind, _node, xy in points:
            dists.append(np.linalg.norm(grid - xy, axis=1))
            params.append(np.zeros(len(grid)))
        D = np.vstack(dists)
        ties = D <= D.min(axis=0) + 1e-9  # a cell equally near several supports is shared between them
        fraction = ties / ties.sum(axis=0)
        for si in range(len(lines) + len(points)):
            mask = fraction[si] > 0
            if not mask.any():
                continue
            cell_share = fraction[si][mask] * weight  # m2 per cell
            share = float(cell_share.sum())  # m2
            if si < len(lines):
                kind, ref, _a2, _b2 = lines[si]
                if kind == "wall":
                    rec = an.wall_loads.setdefault(ref, {c: 0.0 for c in CASES})
                    for c, v in (("G", g), ("Q", q), ("S", sn)):
                        rec[c] += v * share
                    continue
                m = an.members[ref]
                tt = params[si][mask]
                for idx, t0, t1 in m.subs:
                    sel = (tt >= t0) & ((tt < t1) | (t1 >= 1.0))
                    if not sel.any():
                        continue
                    length = (t1 - t0) * m.length
                    a_sub = float(cell_share[sel].sum())
                    for c, v in (("G", g), ("Q", q), ("S", sn)):
                        if v:
                            an.cases[c]["member"].append({"member": idx, "w": (0.0, 0.0, -v * a_sub / length)})
            else:
                _kind, node, _xy = points[si - len(lines)]
                for c, v in (("G", g), ("Q", q), ("S", sn)):
                    if v:
                        load = an.cases[c]["node"].setdefault(node, np.zeros(6))
                        load[2] -= v * share


def _seg_dist_poly(p: np.ndarray, poly: np.ndarray) -> float:
    best = float("inf")
    for i in range(len(poly)):
        d, _t = _seg_distance(p[None, :], poly[i], poly[(i + 1) % len(poly)])
        best = min(best, float(d[0]))
    return best


def _nearest_node(an: Analysis, p: np.ndarray) -> int:
    return int(np.argmin([np.linalg.norm(np.asarray(q) - p) for q in an.nodes]))


def _drop_unsupported(an: Analysis) -> None:
    """Leave out connected parts with no support (they would be mechanisms), with a warning."""
    parent = list(range(len(an.nodes)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for fm in an.frame_members:
        parent[find(fm["i"])] = find(fm["j"])
    supported = {find(n) for n in an.supports}
    keep = [fm for fm in an.frame_members if find(fm["i"]) in supported]
    if len(keep) == len(an.frame_members):
        return
    gone = {fm["phys"] for fm in an.frame_members if find(fm["i"]) not in supported}
    for k in sorted(gone):
        e = an.members[k].element
        an.excluded.append(e.GlobalId)
    names = ", ".join(sorted({an.members[k].element.Name or an.members[k].kind for k in gone}))[:300]
    an.warnings.append(f"{len(gone)} member(s) are not connected to any support and are left out: {names}")
    old_to_new = {}
    frame_members = []
    for old, fm in enumerate(an.frame_members):
        if find(fm["i"]) in supported:
            old_to_new[old] = len(frame_members)
            frame_members.append(fm)
    an.frame_members = frame_members
    for k, m in enumerate(an.members):
        m.subs = [(old_to_new[i], t0, t1) for i, t0, t1 in m.subs if i in old_to_new]
    for case in an.cases.values():
        case["member"] = [{**l, "member": old_to_new[l["member"]]} for l in case["member"] if l["member"] in old_to_new]
        used = {fm["i"] for fm in frame_members} | {fm["j"] for fm in frame_members}
        case["node"] = {n: v for n, v in case["node"].items() if n in used}


# ---------------------------------------------------------------- solving and checking

def combinations(settings: dict) -> dict:
    return {"ULS": dict(settings["uls"]), "SLS": dict(settings["sls"])}


def _solve_cases(an: Analysis, stations: int) -> dict:
    out = {}
    for case in CASES:
        loads = an.cases[case]
        if not loads["member"] and not loads["node"]:
            out[case] = None
            continue
        out[case] = frame.solve(an.nodes, an.frame_members, an.supports, loads["node"], loads["member"], stations)
    return out


def _combine(results: dict, factors: dict, n_members: int, n_nodes: int, supports: dict, stations: int):
    """Superpose case results (linear): member force arrays, deflections via displacement fields."""
    keys = ("N", "Vy", "Vz", "T", "My", "Mz")
    members = [{k: np.zeros(stations + 1) for k in keys} | {"disp": np.zeros((stations + 1, 3))}
               for _ in range(n_members)]
    disp = np.zeros((n_nodes, 6))
    reactions = {n: np.zeros(6) for n in supports}
    for case, r in results.items():
        if r is None:
            continue
        fct = float(factors.get(case, 0.0))
        if not fct:
            continue
        disp += fct * r["displacements"]
        for n, v in r["reactions"].items():
            reactions[n] += fct * v
        for i, mr in enumerate(r["members"]):
            for k in keys:
                members[i][k] += fct * mr[k]
            members[i]["disp"] += fct * mr["disp"]
    return members, disp, reactions


def _buckling_chi(lam_bar: float) -> float:
    alpha = 0.34  # curve b
    phi = 0.5 * (1 + alpha * (lam_bar - 0.2) + lam_bar ** 2)
    return min(1.0, 1.0 / (phi + math.sqrt(max(phi * phi - lam_bar * lam_bar, 0.0))))


def _check_member(m: Member, uls: list[dict], sls_disp: np.ndarray, settings: dict, cantilever: bool) -> dict:
    sec, mat = m.section, m.material
    f = float(mat["f"]) / float(mat.get("gamma", 1.0) or 1.0)
    N = np.concatenate([r["N"] for r in uls])
    My = np.concatenate([np.abs(r["My"]) for r in uls])
    Mz = np.concatenate([np.abs(r["Mz"]) for r in uls])
    V = np.concatenate([np.hypot(r["Vy"], r["Vz"]) for r in uls])
    compression = float(max(0.0, -N.min()))
    tension = float(max(0.0, N.max()))
    i_min = math.sqrt(min(sec["Iy"], sec["Iz"]) / sec["A"])
    lam = m.length / i_min if i_min > 0 else 0.0
    chi = 1.0
    notes = []
    if m.category == "steel":
        eps_lam = 93.9 * math.sqrt(235e3 / float(mat["f"]))
        chi = _buckling_chi(lam / eps_lam) if compression > 0 else 1.0
        if lam > 200 and compression > 0:
            notes.append(f"slenderness {lam:.0f} > 200")
    elif m.category == "timber":
        chi = _buckling_chi(lam / (math.pi * math.sqrt(mat["E"] / mat["f"]))) if compression > 0 else 1.0
    else:
        notes.append("indicative concrete stress only, no reinforcement design")
    if m.category == "concrete":
        sigma = np.abs(N) / sec["A"] + My / sec["Wy"] + Mz / sec["Wz"]
        util = float(sigma.max() / f)
        governing = "stress (concrete, indicative)"
        shear = 0.0
    else:
        axial = np.where(N < 0, -N / (chi * sec["A"] * f), N / (sec["A"] * f))
        combined = axial + My / (sec["Wy"] * f) + Mz / (sec["Wz"] * f)
        shear = float(V.max() / (0.5 * sec["A"] * f / math.sqrt(3)))
        util = float(max(combined.max(), shear))
        governing = "shear" if shear >= combined.max() else ("N + M with buckling" if chi < 1 and compression > 0 else "N + M")
    # deflection: the largest displacement across the member relative to its chord (SLS)
    d = m.b - m.a
    axis = d / np.linalg.norm(d)
    rel = sls_disp - (sls_disp[0] + np.outer(np.linspace(0, 1, len(sls_disp)), sls_disp[-1] - sls_disp[0]))
    if cantilever:
        rel = sls_disp - sls_disp[0]
    perp = rel - np.outer(rel @ axis, axis)
    deflection = float(np.linalg.norm(perp, axis=1).max())
    limit_ratio = float(settings["deflection_cantilever"] if cantilever else settings["deflection_span"])
    limit = m.length / limit_ratio
    if m.kind == "column":
        deflection_util = 0.0
    else:
        deflection_util = deflection / limit if limit > 0 else 0.0
    if deflection_util > util:
        governing = f"deflection (L/{limit_ratio:.0f})"
    worst = max(util, deflection_util)
    warn = float(settings["warn_utilisation"])
    status = "fail" if worst > 1.0 else ("warn" if worst > warn else "pass")
    return {"guid": m.element.GlobalId, "name": m.element.Name or m.kind, "kind": m.kind,
            "material": m.material_name, "category": m.category, "length": round(m.length, 3),
            "utilisation": round(worst, 3), "strength_utilisation": round(util, 3),
            "deflection_utilisation": round(deflection_util, 3), "governing": governing,
            "N_compression": round(compression, 2), "N_tension": round(tension, 2),
            "My": round(float(My.max()), 2), "Mz": round(float(Mz.max()), 2), "V": round(float(V.max()), 2),
            "shear_utilisation": round(shear, 3), "chi": round(chi, 3), "slenderness": round(lam, 1),
            "deflection": round(deflection, 5), "deflection_limit": round(limit, 5), "cantilever": cantilever,
            "status": status, "notes": notes}


def _report_walls_and_slabs(an: Analysis, report: dict, f_uls: dict) -> None:
    for guid, loads in an.wall_loads.items():
        wall = B._model.by_guid(guid)
        line = _wall_line(wall)
        length = float(np.linalg.norm(line[1] - line[0])) if line else 1.0
        total = sum(float(f_uls.get(c, 0.0)) * v for c, v in loads.items())
        report["walls"].append({"guid": guid, "name": wall.Name or "Wall", "uls_kN": round(total, 2),
                                "uls_kN_per_m": round(total / max(length, 0.01), 2)})
    for guid, rec in an.slab_loads.items():
        slab = B._model.by_guid(guid)
        report["slabs"].append({"guid": guid, "name": slab.Name or "Slab", "area": rec["area"], "use": rec["use"],
                                "G": round(rec["G"], 2), "Q": round(rec["Q"], 2), "S": round(rec["S"], 2),
                                "dropped": rec["dropped"]})


def run_analysis(settings: dict | None = None) -> dict:
    """Build, solve and check. Returns the report (no model change)."""
    settings = settings or engsettings.get("structure_settings")
    an = build(settings)
    stations = int(settings["stations"])
    combos = combinations(settings)
    assumptions = [
        f"Supports: column bases {settings['base_support']}; beam ends on bearing walls pinned "
        f"(walls: {settings['bearing_walls'].replace('_', ' ')})",
        f"G: member and slab self-weight + {settings['superimposed_dead']:g} kN/m² superimposed",
        "Q: imposed loads by use " + ", ".join(f"{k} {v:g}" for k, v in settings["use_loads"].items()) + " kN/m²",
        f"S: snow {settings['snow']:g} kN/m² on roofs",
        "ULS " + " + ".join(f"{v:g} {k}" for k, v in combos["ULS"].items()) + "; SLS "
        + " + ".join(f"{v:g} {k}" for k, v in combos["SLS"].items()),
        f"Deflection limits L/{settings['deflection_span']:g} (cantilevers L/{settings['deflection_cantilever']:g})",
        "Slab load to the nearest support (45° envelope); members rigidly connected; linear, first order",
        "Design aid for early checks, not a certified calculation: check with the engineer of record",
    ]
    report = {"ok": True, "method": METHOD, "assumptions": assumptions, "warnings": list(an.warnings),
              "members": [], "reactions": [], "walls": [], "slabs": [], "excluded": an.excluded,
              "combinations": combos, "counts": {}}
    _report_walls_and_slabs(an, report, combos["ULS"])
    report["_analysis"] = an
    if not an.frame_members:
        if an.wall_loads:  # a masonry building: the slabs bear on walls, nothing to solve
            report["warnings"].append("no supported columns or beams to check: the slab loads go to the bearing walls")
            report["total_uls_kN"] = round(sum(w["uls_kN"] for w in report["walls"]), 2)
            report["total_reaction_kN"] = report["total_uls_kN"]
            report["max_utilisation"] = 0.0
            report["counts"] = {"pass": 0, "warn": 0, "fail": 0}
            report["_uls"] = ([], {})
            return report
        report["ok"] = False
        report["error"] = ("there is nothing to analyse: no supported columns or beams"
                           if an.members else "there are no columns or beams to analyse")
        return report
    try:
        results = _solve_cases(an, stations)
    except frame.Unstable as ex:
        report["ok"] = False
        report["error"] = f"the structure is unstable: {ex}"
        return report
    n_members, n_nodes = len(an.frame_members), len(an.nodes)
    uls, uls_disp, uls_react = _combine(results, combos["ULS"], n_members, n_nodes, an.supports, stations)
    sls, sls_disp, _ = _combine(results, combos["SLS"], n_members, n_nodes, an.supports, stations)
    degree = {}
    for fm in an.frame_members:
        for n_ in (fm["i"], fm["j"]):
            degree[n_] = degree.get(n_, 0) + 1
    for k, m in enumerate(an.members):
        if not m.subs:
            continue
        subs = [s[0] for s in m.subs]
        ends = (an.frame_members[subs[0]]["i"], an.frame_members[subs[-1]]["j"])
        cantilever = any(degree.get(n_, 0) == 1 and n_ not in an.supports for n_ in ends)
        disp = np.vstack([sls[i]["disp"] if j == 0 else sls[i]["disp"][1:] for j, i in enumerate(subs)])
        report["members"].append(_check_member(m, [uls[i] for i in subs], disp, settings, cantilever))
    for n, r in uls_react.items():
        report["reactions"].append({"node": n, "point": [round(float(v), 3) for v in an.nodes[n]],
                                    "kind": an.support_kind.get(n, ""),
                                    "force": [round(float(v), 3) for v in r[:3]],
                                    "moment": [round(float(v), 3) for v in r[3:]]})
    f_uls = combos["ULS"]
    total_applied = 0.0
    for case, factor in f_uls.items():
        loads = an.cases[case]
        for l in loads["member"]:
            fm = an.frame_members[l["member"]]
            total_applied += factor * -l["w"][2] * float(np.linalg.norm(np.asarray(an.nodes[fm["j"]]) - an.nodes[fm["i"]]))
        for v in loads["node"].values():
            total_applied += factor * -v[2]
    report["total_uls_kN"] = round(total_applied, 2)
    report["total_reaction_kN"] = round(sum(r["force"][2] for r in report["reactions"]), 2)
    statuses = [m["status"] for m in report["members"]]
    report["counts"] = {s: statuses.count(s) for s in ("pass", "warn", "fail")}
    report["max_utilisation"] = max((m["utilisation"] for m in report["members"]), default=0.0)
    report["_analysis"] = an
    report["_uls"] = (uls, uls_react)
    return report


def _public(report: dict) -> dict:
    return {k: v for k, v in report.items() if not k.startswith("_")}


# ---------------------------------------------------------------- IFC output

def _remove_previous(f) -> None:
    import ifcopenshell.api.root

    for cls in ("IfcStructuralPointReaction", "IfcStructuralCurveAction", "IfcStructuralPointConnection"):
        try:
            found = f.by_type(cls)
        except RuntimeError:
            continue
        for e in found:
            if (e.Description or "") == TAG:
                for rel in list(getattr(e, "AssignedToStructuralItem", ()) or ()) + \
                        list(getattr(e, "ConnectedBy", ()) or ()) + list(getattr(e, "AssignedStructuralActivity", ()) or ()):
                    f.remove(rel)
                ifcopenshell.api.root.remove_product(f, product=e)
    for cls in ("IfcStructuralResultGroup", "IfcStructuralLoadGroup"):
        for g in list(f.by_type(cls)):
            if (g.Description or "") == TAG:
                for rel in list(getattr(g, "IsGroupedBy", ()) or ()):
                    f.remove(rel)
                for rel in list(getattr(g, "HasAssignments", ()) or ()):
                    f.remove(rel)
                f.remove(g)


def _write_ifc(report: dict, model_guid: str) -> None:
    """Inside an action (IFC4/IFC4X3): supports, load groups, member line loads and reactions."""
    import ifcopenshell.api.group
    import ifcopenshell.api.root

    f = B._model
    _remove_previous(f)
    if f.schema == "IFC2X3":
        return
    an: Analysis = report["_analysis"]
    s = _scale()
    model = f.by_guid(model_guid)
    rel_model = []
    ctx = A._body_context()

    def vertex(p):
        return f.createIfcVertexPoint(f.createIfcCartesianPoint(tuple(float(v) / s for v in p)))

    connections = {}
    for node, restraint in an.supports.items():
        conn = ifcopenshell.api.root.create_entity(f, ifc_class="IfcStructuralPointConnection",
                                                   name=f"Support {node} ({an.support_kind.get(node, '')})")
        conn.Description = TAG
        rep = f.createIfcTopologyRepresentation(ctx, "Reference", "Vertex", [vertex(an.nodes[node])])
        conn.Representation = f.createIfcProductDefinitionShape(None, None, [rep])
        flags = [f.create_entity("IfcBoolean", r is True) for r in restraint]
        conn.AppliedCondition = f.createIfcBoundaryNodeCondition(
            f"{an.support_kind.get(node, 'support')}", *flags)
        connections[node] = conn
        rel_model.append(conn)
    case_groups = {}
    for case in CASES:
        g = ifcopenshell.api.root.create_entity(f, ifc_class="IfcStructuralLoadCase",
                                                name={"G": "G dead", "Q": "Q imposed", "S": "S snow"}[case])
        g.Description = TAG
        g.PredefinedType = "LOAD_CASE"
        g.ActionType = "PERMANENT_G" if case == "G" else "VARIABLE_Q"
        g.ActionSource = {"G": "DEAD_LOAD_G", "Q": "LIVE_LOAD_Q", "S": "SNOW_S"}[case]
        case_groups[case] = g
        rel_model.append(g)
    # one line action per physical member and case: the average of its sub-member loads
    curves = {}
    for rel in getattr(model, "IsGroupedBy", ()) or ():
        for item in rel.RelatedObjects:
            if item.is_a("IfcStructuralCurveMember"):
                data = ifcopenshell.util.element.get_pset(item, "KIMBIM_Analytical") or {}
                curves[data.get("SourceGuid")] = item
    for case in CASES:
        per_member: dict[int, float] = {}
        for l in an.cases[case]["member"]:
            fm = an.frame_members[l["member"]]
            L = float(np.linalg.norm(np.asarray(an.nodes[fm["j"]]) - an.nodes[fm["i"]]))
            per_member[fm["phys"]] = per_member.get(fm["phys"], 0.0) + -l["w"][2] * L
        for k, total in per_member.items():
            m = an.members[k]
            curve = curves.get(m.element.GlobalId)
            if curve is None or total <= 1e-9:
                continue
            action = ifcopenshell.api.root.create_entity(f, ifc_class="IfcStructuralCurveAction",
                                                         name=f"{case} on {m.element.Name or m.kind}")
            action.Description = TAG
            action.GlobalOrLocal = "GLOBAL_COORDS"
            action.ProjectedOrTrue = "TRUE_LENGTH"
            action.PredefinedType = "CONST"
            action.AppliedLoad = f.createIfcStructuralLoadLinearForce(
                f"{case} {total / m.length:.2f} kN/m", 0.0, 0.0, -total / m.length * 1000.0, 0.0, 0.0, 0.0)
            f.createIfcRelConnectsStructuralActivity(ifcopenshell.guid.new(), None, None, None, curve, action)
            ifcopenshell.api.group.assign_group(f, products=[action], group=case_groups[case])
    combos = report["combinations"]
    uls, uls_react = report["_uls"]
    for name, factors in combos.items():
        g = ifcopenshell.api.root.create_entity(f, ifc_class="IfcStructuralLoadGroup", name=name)
        g.Description = TAG
        g.PredefinedType = "LOAD_COMBINATION"
        g.ActionType = "NOTDEFINED"
        g.ActionSource = "NOTDEFINED"
        rel_model.append(g)
        for c, v in factors.items():
            if c in case_groups and v:
                f.createIfcRelAssignsToGroupByFactor(ifcopenshell.guid.new(), None, None, None, [case_groups[c]],
                                                     None, g, float(v))
        if name != "ULS":
            continue
        result = ifcopenshell.api.root.create_entity(f, ifc_class="IfcStructuralResultGroup", name=f"{name} results")
        result.Description = TAG
        result.TheoryType = "FIRST_ORDER_THEORY"
        result.ResultForLoadGroup = g
        result.IsLinear = True
        rel_model.append(result)
        for node, r in uls_react.items():
            reaction = ifcopenshell.api.root.create_entity(f, ifc_class="IfcStructuralPointReaction",
                                                           name=f"Reaction {node}")
            reaction.Description = TAG
            reaction.GlobalOrLocal = "GLOBAL_COORDS"
            reaction.AppliedLoad = f.createIfcStructuralLoadSingleForce(
                f"R{node}", *(float(v) * 1000.0 for v in r[:3]), *(float(v) * 1000.0 for v in r[3:]))
            f.createIfcRelConnectsStructuralActivity(ifcopenshell.guid.new(), None, None, None,
                                                     connections[node], reaction)
            ifcopenshell.api.group.assign_group(f, products=[reaction], group=result)
    supports = [e for e in rel_model if e.is_a("IfcStructuralItem")]
    if supports:
        ifcopenshell.api.group.assign_group(f, products=supports, group=model)
    model.LoadedBy = [e for e in rel_model if e.is_a("IfcStructuralLoadGroup")] or None
    model.HasResults = [e for e in rel_model if e.is_a("IfcStructuralResultGroup")] or None


def _write_psets(report: dict) -> list[str]:
    f = B._model
    changed = []
    for row in report["members"]:
        e = f.by_guid(row["guid"])
        pset = ifcopenshell.util.element.get_pset(e, RESULT_PSET)
        pset = f.by_id(pset["id"]) if pset else ifcopenshell.api.pset.add_pset(f, product=e, name=RESULT_PSET)
        ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={
            "MaxUtilisation": float(row["utilisation"]), "Status": row["status"], "GoverningCheck": row["governing"],
            "Combination": "ULS/SLS", "Deflection": float(row["deflection"]),
            "DeflectionLimit": float(row["deflection_limit"]), "Material": row["material"],
            "Category": row["category"], "Updated": _now()})
        changed.append(row["guid"])
    analysed = {row["guid"] for row in report["members"]}
    for cls in ("IfcColumn", "IfcBeam", "IfcMember"):  # members left out: their old results would mislead
        for e in f.by_type(cls):
            if e.GlobalId in analysed:
                continue
            pset = ifcopenshell.util.element.get_pset(e, RESULT_PSET)
            if pset:
                ifcopenshell.api.pset.remove_pset(f, product=e, pset=f.by_id(pset["id"]))
    return changed


def _now() -> str:
    import datetime

    return datetime.datetime.now().replace(microsecond=0).isoformat()


# ---------------------------------------------------------------- bridge

def analyse_structure(apply: bool | str = True) -> str:
    """Analyse the structure: loads from the model, a frame solve, member checks. With `apply` the
    results are written to the members (KIMBIM_StructuralResult) and, in IFC4, to the analytical
    model (supports, load cases and combinations, line loads, reactions), as one undo step."""
    if B._model is None:
        return A._fail("no model open")
    apply = apply if isinstance(apply, bool) else str(apply).lower() not in ("0", "false", "no", "")
    try:
        report = run_analysis()
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    if not report["ok"] or not apply:
        return B._dump(_public(report))
    from . import console, structural

    try:
        with console.edit():
            made = json.loads(structural.create_analysis_model())
            if not made.get("ok"):
                raise RuntimeError(made.get("error"))

            def action():
                _write_ifc(report, made["guid"])
                return len(_write_psets(report)), [], []

            B._run(action, affects_drawings=False)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**_public(report), **B._flags(), "applied": True})


def structure_results() -> str:
    """The stored results on the members (from the last applied analysis)."""
    if B._model is None:
        return A._fail("no model open")
    rows = []
    for cls in ("IfcColumn", "IfcBeam", "IfcMember"):
        for e in B._model.by_type(cls):
            data = ifcopenshell.util.element.get_pset(e, RESULT_PSET)
            if data:
                rows.append({"guid": e.GlobalId, "name": e.Name or "", "utilisation": data.get("MaxUtilisation"),
                             "status": data.get("Status"), "governing": data.get("GoverningCheck"),
                             "updated": data.get("Updated")})
    return B._dump({"ok": True, "members": rows})


def utilisation_colours() -> str:
    """{guid: colour} for the members with stored results: green pass, amber warn, red fail."""
    if B._model is None:
        return A._fail("no model open")
    out = {}
    for row in json.loads(structure_results())["members"]:
        out[row["guid"]] = COLOURS.get(row["status"] or "none", COLOURS["none"])
    return B._dump({"ok": True, "colours": out, "legend": COLOURS})
