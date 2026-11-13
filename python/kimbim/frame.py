# SPDX-License-Identifier: GPL-3.0-or-later
"""A linear-elastic 3D frame solver (D247): the direct stiffness method with 12-DOF Euler-Bernoulli
members, in numpy.

Units are consistent SI-like engineering units: metres, kN, kN/m², so E and G are kN/m² and the
results are kN, kN·m and metres. Each node has six degrees of freedom (ux, uy, uz, rx, ry, rz).
A member's local x runs from node i to node j; its local z follows ``zref`` (the profile's Y, the
section's depth direction) made perpendicular, and y = z × x. ``Iy`` is about local y (bending in
the x-z plane), ``Iz`` about local z.

Uniform member loads are given in global axes (kN/m) and enter as equivalent nodal loads; the
internal forces at stations along each member come from equilibrium of the member segment, and the
deflection relative to the chord from cubic Hermite shapes plus the fixed-end particular solution,
which is exact for uniform loads.

A structure that cannot carry load (no supports, a mechanism, a free node) raises
:class:`Unstable` instead of returning meaningless numbers.
"""
from __future__ import annotations

import numpy as np


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


def equivalent_loads(w_local: np.ndarray, L: float) -> np.ndarray:
    """Equivalent nodal loads (local) of a uniform load w = (wx, wy, wz) kN/m."""
    wx, wy, wz = w_local
    f = np.zeros(12)
    f[0] = f[6] = wx * L / 2
    f[1] = f[7] = wy * L / 2
    f[5], f[11] = wy * L ** 2 / 12, -wy * L ** 2 / 12
    f[2] = f[8] = wz * L / 2
    f[4], f[10] = -wz * L ** 2 / 12, wz * L ** 2 / 12
    return f


def solve(nodes, members: list[dict], supports: dict, node_loads: dict | None = None,
          member_loads: list[dict] | None = None, stations: int = 10) -> dict:
    """Solve the frame.

    nodes: (n, 3) coordinates (m). members: dicts with i, j, E, G, A, Iy, Iz, J and optional zref.
    supports: {node: six values}: True restrains the DOF, a positive number adds a spring of that
    stiffness (kN/m or kN·m/rad), False/0 leaves it free. node_loads: {node: six values (kN, kN·m)}.
    member_loads: [{member: index, w: (wx, wy, wz) global kN/m}].

    Returns displacements (n, 6), reactions {node: six values}, and per member: x stations, N, Vy, Vz,
    T, My, Mz arrays (tension and the usual right-hand signs), end forces (local, 12) and the largest
    deflection relative to the chord (m).
    """
    nodes = np.asarray(nodes, float)
    n = len(nodes)
    if not members:
        raise Unstable("there are no members to analyse")
    if not supports or not any(v is True for r in supports.values() for v in r):
        raise Unstable("the structure has no supports")
    used = {m["i"] for m in members} | {m["j"] for m in members}
    for node in supports:
        if node not in used:
            raise Unstable(f"support at node {node} is not on any member")
    ndof = 6 * n
    K = np.zeros((ndof, ndof))
    F = np.zeros(ndof)
    for node, load in (node_loads or {}).items():
        F[6 * node:6 * node + 6] += np.asarray(load, float)
    data = []
    for m in members:
        R, L = local_axes(nodes[m["i"]], nodes[m["j"]], m.get("zref"))
        T = _transform(R)
        k = local_stiffness(m["E"], m["G"], m["A"], m["Iy"], m["Iz"], m["J"], L)
        kg = T.T @ k @ T
        dofs = np.r_[6 * m["i"]:6 * m["i"] + 6, 6 * m["j"]:6 * m["j"] + 6]
        K[np.ix_(dofs, dofs)] += kg
        data.append({"R": R, "T": T, "k": k, "L": L, "dofs": dofs, "w": np.zeros(3), "feq": np.zeros(12)})
    for load in member_loads or ():
        d = data[load["member"]]
        w_local = d["R"] @ np.asarray(load["w"], float)
        d["w"] = d["w"] + w_local
        feq = equivalent_loads(w_local, d["L"])
        d["feq"] = d["feq"] + feq
        F[d["dofs"]] += d["T"].T @ feq
    fixed = np.zeros(ndof, bool)
    springs = np.zeros(ndof)
    for node, restrained in supports.items():
        for i, r in enumerate(restrained):
            if r is True:
                fixed[6 * node + i] = True
            elif r and not isinstance(r, bool):
                springs[6 * node + i] = float(r)
    K[np.diag_indices(ndof)] += springs
    unused = [i for i in range(n) if i not in used]
    for node in unused:  # nodes without members carry nothing: take them out of the system
        fixed[6 * node:6 * node + 6] = True
    free = ~fixed
    Kff = K[np.ix_(free, free)]
    try:
        Lc = np.linalg.cholesky(Kff)
    except np.linalg.LinAlgError:
        raise Unstable("the structure is a mechanism: add supports or connections") from None
    pivots = np.diag(Lc) ** 2
    if pivots.size and pivots.min() < 1e-10 * max(1.0, float(np.abs(np.diag(Kff)).max())):
        raise Unstable("the structure is a mechanism: add supports or connections")
    u = np.zeros(ndof)
    y = np.linalg.solve(Lc, F[free])
    u[free] = np.linalg.solve(Lc.T, y)
    full = K @ u - F  # springs included: their force is part of the support's reaction
    reactions = {node: full[6 * node:6 * node + 6].copy() for node in supports}
    results = []
    for m, d in zip(members, data):
        ul = d["T"] @ u[d["dofs"]]
        f = d["k"] @ ul - d["feq"]  # end forces acting on the member, local axes
        L, (wx, wy, wz) = d["L"], d["w"]
        xs = np.linspace(0.0, L, max(2, int(stations)) + 1)
        N = -(f[0] + wx * xs)
        Vy = -(f[1] + wy * xs)
        Vz = -(f[2] + wz * xs)
        Tq = -f[3] * np.ones_like(xs)
        My = -(f[4] + xs * f[2] + wz * xs ** 2 / 2)
        Mz = -(f[5] - xs * f[1] - wy * xs ** 2 / 2)
        xi = xs / L
        h1, h2 = 1 - 3 * xi ** 2 + 2 * xi ** 3, L * (xi - 2 * xi ** 2 + xi ** 3)
        h3, h4 = 3 * xi ** 2 - 2 * xi ** 3, L * (-xi ** 2 + xi ** 3)
        E, Iy, Iz = m["E"], m["Iy"], m["Iz"]
        v = h1 * ul[1] + h2 * ul[5] + h3 * ul[7] + h4 * ul[11] + wy * xs ** 2 * (L - xs) ** 2 / (24 * E * Iz)
        w = h1 * ul[2] - h2 * ul[4] + h3 * ul[8] - h4 * ul[10] + wz * xs ** 2 * (L - xs) ** 2 / (24 * E * Iy)
        axial = ul[0] + (ul[6] - ul[0]) * xi
        disp = (np.vstack([axial, v, w]).T) @ d["R"]  # global displacement at each station
        v_rel = v - (ul[1] + (ul[7] - ul[1]) * xi)
        w_rel = w - (ul[2] + (ul[8] - ul[2]) * xi)
        results.append({"x": xs, "N": N, "Vy": Vy, "Vz": Vz, "T": Tq, "My": My, "Mz": Mz, "end_forces": f,
                        "deflection": float(np.max(np.hypot(v_rel, w_rel))), "length": L, "disp": disp,
                        "tip": float(np.hypot(ul[7] - ul[1], ul[8] - ul[2]))})
    return {"displacements": u.reshape(n, 6), "reactions": reactions, "members": results}
