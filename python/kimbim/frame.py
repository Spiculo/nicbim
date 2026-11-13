# SPDX-License-Identifier: GPL-3.0-or-later
"""A linear-elastic 3D frame solver (D247): the direct stiffness method with 12-DOF Euler-Bernoulli
members, in numpy.

Units are consistent SI-like engineering units: metres, kN, kN/m², so E and G are kN/m² and the
results are kN, kN·m and metres. Each node has six degrees of freedom (ux, uy, uz, rx, ry, rz).
A member's local x runs from node i to node j; its local z follows ``zref`` (the profile's Y, the
section's depth direction) made perpendicular, and y = z × x. ``Iy`` is about local y (bending in
the x-z plane), ``Iz`` about local z.

Member loads are uniform over the whole member or over a part of it (``a`` to ``b``, fractions of
its length), in global axes (kN/m). They enter as consistent nodal loads, integrated exactly over
the Hermite shape functions; internal forces at stations come from equilibrium of the member
segment, and the deflection relative to the chord from the Hermite shapes of the end displacements
plus the fixed-end beam's own deflection under the loads (integrated numerically from its moment).

Several load cases share one factorisation (:func:`solve_many`). A structure that cannot carry
load (no supports, a mechanism, a free node) raises :class:`Unstable`.
"""
from __future__ import annotations

import numpy as np

SPIN_STIFFNESS = 1e9  # kN·m/rad: a bearing holding a member against turning about its own axis
_GAUSS_X, _GAUSS_W = np.polynomial.legendre.leggauss(4)  # exact for the cubic shapes x constant loads


class Unstable(ValueError):
    """The structure is a mechanism or has no supports."""


def local_axes(pi: np.ndarray, pj: np.ndarray, zref=None) -> tuple[np.ndarray, float]:
    """(3x3 rotation whose rows are local x, y, z in global axes, length)."""
    d = np.asarray(pj, float) - np.asarray(pi, float)
    L = float(np.linalg.norm(d))
    if L < 1e-9:
        raise Unstable("a member has zero length")
    x = d / L
    z0 = np.asarray(zref if zref is not None else (0.0, 0.0, 1.0), float)
    if np.linalg.norm(np.cross(z0, x)) < 1e-6:  # zref along the member (a column with z up): use global X
        z0 = np.array([1.0, 0.0, 0.0]) if abs(x[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    y = np.cross(z0, x)
    y /= np.linalg.norm(y)
    z = np.cross(x, y)
    return np.vstack([x, y, z]), L


def local_stiffness(E, G, A, Iy, Iz, J, L) -> np.ndarray:
    k = np.zeros((12, 12))
    ea, gj = E * A / L, G * J / L
    k[0, 0] = k[6, 6] = ea
    k[0, 6] = k[6, 0] = -ea
    k[3, 3] = k[9, 9] = gj
    k[3, 9] = k[9, 3] = -gj
    # bending in x-y (uy, rz) with Iz
    a, b, c, d = 12 * E * Iz / L ** 3, 6 * E * Iz / L ** 2, 4 * E * Iz / L, 2 * E * Iz / L
    for (r, s), v in {(1, 1): a, (1, 5): b, (1, 7): -a, (1, 11): b, (5, 5): c, (5, 7): -b, (5, 11): d,
                      (7, 7): a, (7, 11): -b, (11, 11): c}.items():
        k[r, s] = k[s, r] = v
    # bending in x-z (uz, ry) with Iy
    a, b, c, d = 12 * E * Iy / L ** 3, 6 * E * Iy / L ** 2, 4 * E * Iy / L, 2 * E * Iy / L
    for (r, s), v in {(2, 2): a, (2, 4): -b, (2, 8): -a, (2, 10): -b, (4, 4): c, (4, 8): b, (4, 10): d,
                      (8, 8): a, (8, 10): b, (10, 10): c}.items():
        k[r, s] = k[s, r] = v
    return k


def _transform(R: np.ndarray) -> np.ndarray:
    T = np.zeros((12, 12))
    for i in range(4):
        T[3 * i:3 * i + 3, 3 * i:3 * i + 3] = R
    return T


def _hermite(xi, L):
    return (1 - 3 * xi ** 2 + 2 * xi ** 3, L * (xi - 2 * xi ** 2 + xi ** 3), 3 * xi ** 2 - 2 * xi ** 3,
            L * (-xi ** 2 + xi ** 3))


def equivalent_loads(w_local: np.ndarray, L: float, a: float = 0.0, b: float = 1.0) -> np.ndarray:
    """Consistent nodal loads (local) of a uniform load w = (wx, wy, wz) kN/m from a·L to b·L."""
    wx, wy, wz = w_local
    f = np.zeros(12)
    if b <= a:
        return f
    half = (b - a) / 2
    for gx, gw in zip(_GAUSS_X, _GAUSS_W):
        xi = a + half * (gx + 1)
        weight = gw * half * L
        h1, h2, h3, h4 = _hermite(xi, L)
        f[0] += wx * (1 - xi) * weight
        f[6] += wx * xi * weight
        f[1] += wy * h1 * weight
        f[5] += wy * h2 * weight
        f[7] += wy * h3 * weight
        f[11] += wy * h4 * weight
        f[2] += wz * h1 * weight
        f[4] -= wz * h2 * weight
        f[8] += wz * h3 * weight
        f[10] -= wz * h4 * weight
    return f


def _load_integrals(xs: np.ndarray, loads: list, L: float):
    """For loads [(w_local, a, b)]: the load taken up to each station (3, n) and its moment-arm
    integral ∫ w (x - s) ds (3, n)."""
    W = np.zeros((3, len(xs)))
    MW = np.zeros((3, len(xs)))
    for w, a, b in loads:
        lo, hi = a * L, b * L
        top = np.clip(xs, lo, hi)
        span = top - lo
        moment = np.where(xs > lo, ((xs - lo) ** 2 - (xs - top) ** 2) / 2, 0.0)
        for c in range(3):
            W[c] += w[c] * span
            MW[c] += w[c] * moment
    return W, MW


def _internal(f: np.ndarray, xs: np.ndarray, loads: list, L: float) -> dict:
    W, MW = _load_integrals(xs, loads, L)
    return {"N": -(f[0] + W[0]), "Vy": -(f[1] + W[1]), "Vz": -(f[2] + W[2]), "T": -f[3] * np.ones_like(xs),
            "My": -(f[4] + xs * f[2] + MW[2]), "Mz": -(f[5] - xs * f[1] - MW[1])}


def _integrate_twice(xs: np.ndarray, curvature: np.ndarray) -> np.ndarray:
    """v with v(0) = v'(0) = 0 and v'' = curvature (trapezoids)."""
    dx = np.diff(xs)
    slope = np.concatenate([[0.0], np.cumsum((curvature[1:] + curvature[:-1]) / 2 * dx)])
    return np.concatenate([[0.0], np.cumsum((slope[1:] + slope[:-1]) / 2 * dx)])


def _particular(feq: np.ndarray, loads: list, L: float, E: float, Iy: float, Iz: float, xs: np.ndarray):
    """The deflection (v, w) of the member fixed at both ends under its own loads."""
    if not loads:
        return np.zeros_like(xs), np.zeros_like(xs)
    fine = np.linspace(0.0, L, 401)
    forces = _internal(-feq, fine, loads, L)  # fixed ends: the end forces are the fixed-end reactions
    v = _integrate_twice(fine, forces["Mz"] / (E * Iz))
    w = _integrate_twice(fine, -forces["My"] / (E * Iy))
    v -= v[-1] * fine / L  # the small drift of the numerical integration: the ends stay at zero
    w -= w[-1] * fine / L
    return np.interp(xs, fine, v), np.interp(xs, fine, w)


def _assemble(nodes, members, supports, spin):
    n = len(nodes)
    ndof = 6 * n
    K = np.zeros((ndof, ndof))
    data = []
    for m in members:
        R, L = local_axes(nodes[m["i"]], nodes[m["j"]], m.get("zref"))
        T = _transform(R)
        k = local_stiffness(m["E"], m["G"], m["A"], m["Iy"], m["Iz"], m["J"], L)
        dofs = np.r_[6 * m["i"]:6 * m["i"] + 6, 6 * m["j"]:6 * m["j"] + 6]
        K[np.ix_(dofs, dofs)] += T.T @ k @ T
        data.append({"R": R, "T": T, "k": k, "L": L, "dofs": dofs})
    fixed = np.zeros(ndof, bool)
    for node, restrained in supports.items():
        for i, r in enumerate(restrained):
            if r is True:
                fixed[6 * node + i] = True
            elif r and not isinstance(r, bool):
                K[6 * node + i, 6 * node + i] += float(r)
    for node, axes in (spin or {}).items():
        r = slice(6 * node + 3, 6 * node + 6)
        for a in axes:
            a = np.asarray(a, float)
            K[r, r] += SPIN_STIFFNESS * np.outer(a, a) / float(a @ a)
    used = {m["i"] for m in members} | {m["j"] for m in members}
    for node in range(n):
        if node not in used:  # nodes without members carry nothing: take them out of the system
            fixed[6 * node:6 * node + 6] = True
    return K, data, fixed


def _check_inputs(members, supports):
    if not members:
        raise Unstable("there are no members to analyse")
    if not supports or not any(v is True for r in supports.values() for v in r):
        raise Unstable("the structure has no supports")
    used = {m["i"] for m in members} | {m["j"] for m in members}
    for node in supports:
        if node not in used:
            raise Unstable(f"support at node {node} is not on any member")


def _factor(Kff):
    try:
        Lc = np.linalg.cholesky(Kff)
    except np.linalg.LinAlgError:
        raise Unstable("the structure is a mechanism: add supports or connections") from None
    pivots = np.diag(Lc) ** 2
    if pivots.size and pivots.min() < 1e-10 * max(1.0, float(np.abs(np.diag(Kff)).max())):
        raise Unstable("the structure is a mechanism: add supports or connections")
    return Lc


def check_stable(nodes, members: list[dict], supports: dict, spin: dict | None = None) -> None:
    """Raise Unstable when the structure cannot carry load."""
    _check_inputs(members, supports)
    K, _data, fixed = _assemble(np.asarray(nodes, float), members, supports, spin)
    free = ~fixed
    _factor(K[np.ix_(free, free)])


def solve_many(nodes, members: list[dict], supports: dict, cases: list[tuple[dict, list]], stations: int = 10,
               spin: dict | None = None) -> list[dict]:
    """Solve several load cases [(node_loads, member_loads)] with one factorisation (see :func:`solve`)."""
    nodes = np.asarray(nodes, float)
    n = len(nodes)
    _check_inputs(members, supports)
    K, data, fixed = _assemble(nodes, members, supports, spin)
    ndof = 6 * n
    free = ~fixed
    Kff = K[np.ix_(free, free)]
    _factor(Kff)  # refuses mechanisms before solving
    F = np.zeros((ndof, len(cases)))
    per_member = [[[] for _ in members] for _ in cases]  # local loads per case and member
    feqs = [[np.zeros(12) for _ in members] for _ in cases]
    for c, (node_loads, member_loads) in enumerate(cases):
        for node, load in (node_loads or {}).items():
            F[6 * node:6 * node + 6, c] += np.asarray(load, float)
        for load in member_loads or ():
            d = data[load["member"]]
            w_local = d["R"] @ np.asarray(load["w"], float)
            a, b = float(load.get("a", 0.0)), float(load.get("b", 1.0))
            feq = equivalent_loads(w_local, d["L"], a, b)
            feqs[c][load["member"]] = feqs[c][load["member"]] + feq
            per_member[c][load["member"]].append((w_local, a, b))
            F[d["dofs"], c] += d["T"].T @ feq
    U = np.zeros((ndof, len(cases)))
    if free.any():
        U[free] = np.linalg.solve(Kff, F[free])  # one factorisation for all the cases
    full = K @ U - F  # springs included: their force is part of the support's reaction
    out = []
    for c in range(len(cases)):
        u = U[:, c]
        reactions = {node: full[6 * node:6 * node + 6, c].copy() for node in supports}
        results = []
        for mi, (m, d) in enumerate(zip(members, data)):
            ul = d["T"] @ u[d["dofs"]]
            f = d["k"] @ ul - feqs[c][mi]  # end forces acting on the member, local axes
            L = d["L"]
            loads = per_member[c][mi]
            xs = np.linspace(0.0, L, max(2, int(stations)) + 1)
            forces = _internal(f, xs, loads, L)
            xi = xs / L
            h1, h2, h3, h4 = _hermite(xi, L)
            pv, pw = _particular(feqs[c][mi], loads, L, m["E"], m["Iy"], m["Iz"], xs)
            v = h1 * ul[1] + h2 * ul[5] + h3 * ul[7] + h4 * ul[11] + pv
            w = h1 * ul[2] - h2 * ul[4] + h3 * ul[8] - h4 * ul[10] + pw
            axial = ul[0] + (ul[6] - ul[0]) * xi
            disp = (np.vstack([axial, v, w]).T) @ d["R"]  # global displacement at each station
            v_rel = v - (ul[1] + (ul[7] - ul[1]) * xi)
            w_rel = w - (ul[2] + (ul[8] - ul[2]) * xi)
            results.append({"x": xs, **forces, "end_forces": f, "deflection": float(np.max(np.hypot(v_rel, w_rel))),
                            "length": L, "disp": disp, "tip": float(np.hypot(ul[7] - ul[1], ul[8] - ul[2]))})
        out.append({"displacements": u.reshape(n, 6), "reactions": reactions, "members": results})
    return out


def solve(nodes, members: list[dict], supports: dict, node_loads: dict | None = None,
          member_loads: list[dict] | None = None, stations: int = 10, spin: dict | None = None) -> dict:
    """Solve the frame.

    nodes: (n, 3) coordinates (m). members: dicts with i, j, E, G, A, Iy, Iz, J and optional zref.
    supports: {node: six values}: True restrains the DOF, a positive number adds a spring of that
    stiffness (kN/m or kN·m/rad), False/0 leaves it free.
    member_loads: [{member: index, w: (wx, wy, wz) global kN/m, a: 0, b: 1}] (a, b: the loaded part as
    fractions of the length). spin: {node: [unit axes]}: the support also holds rotation about each
    axis (torsion restrained at a bearing) and nothing else.

    Returns displacements (n, 6), reactions {node: six values}, and per member: x stations, N, Vy, Vz,
    T, My, Mz arrays (tension and the usual right-hand signs), end forces (local, 12) and the largest
    deflection relative to the chord (m).
    """
    return solve_many(nodes, members, supports, [(node_loads or {}, member_loads or [])], stations, spin)[0]
