# SPDX-License-Identifier: GPL-3.0-or-later
"""D247: the 3D frame solver against closed-form beam results."""
import numpy as np
import pytest

from kimbim import frame

E, G = 210e6, 81e6  # kN/m2
SEC = {"E": E, "G": G, "A": 5.38e-3, "Iy": 8.36e-5, "Iz": 6.04e-6, "J": 2.0e-7}
FIXED = (True,) * 6
PIN = (True, True, True, False, False, False)


def beam(n=1, L=3.0):
    nodes = [(L * k / n, 0.0, 0.0) for k in range(n + 1)]
    members = [{"i": k, "j": k + 1, **SEC, "zref": (0, 0, 1)} for k in range(n)]
    return nodes, members


def test_a_cantilever_tip_load():
    nodes, members = beam(L=3.0)
    r = frame.solve(nodes, members, {0: FIXED}, {1: (0, 0, -10, 0, 0, 0)})
    tip = r["displacements"][1][2]
    assert tip == pytest.approx(-10 * 3 ** 3 / (3 * E * SEC["Iy"]), rel=1e-6)
    base = r["reactions"][0]
    assert base[2] == pytest.approx(10.0) and abs(base[4]) == pytest.approx(30.0)
    assert abs(r["members"][0]["My"][0]) == pytest.approx(30.0) and abs(r["members"][0]["My"][-1]) < 1e-9


def test_a_simply_supported_uniform_load():
    L, w = 6.0, 5.0
    nodes, members = beam(L=L)
    supports = {0: PIN, 1: (False, True, True, True, False, False)}  # roller, torsion held
    r = frame.solve(nodes, members, supports, member_loads=[{"member": 0, "w": (0, 0, -w)}])
    m = r["members"][0]
    mid = len(m["x"]) // 2
    assert abs(m["My"][mid]) == pytest.approx(w * L ** 2 / 8, rel=1e-6)
    assert m["deflection"] == pytest.approx(5 * w * L ** 4 / (384 * E * SEC["Iy"]), rel=1e-4)
    assert sum(rr[2] for rr in r["reactions"].values()) == pytest.approx(w * L)
    assert abs(m["Vz"][0]) == pytest.approx(w * L / 2)


def test_a_portal_frame_is_in_equilibrium():
    nodes = [(0, 0, 0), (0, 0, 3), (5, 0, 3), (5, 0, 0)]
    members = [{"i": 0, "j": 1, **SEC, "zref": (1, 0, 0)}, {"i": 1, "j": 2, **SEC, "zref": (0, 0, 1)},
               {"i": 3, "j": 2, **SEC, "zref": (1, 0, 0)}]
    r = frame.solve(nodes, members, {0: FIXED, 3: FIXED}, {1: (4, 0, 0, 0, 0, 0)},
                    [{"member": 1, "w": (0, 0, -10)}])
    total = sum(np.asarray(v[:3]) for v in r["reactions"].values())
    assert total == pytest.approx(np.array([-4.0, 0.0, 50.0]), abs=1e-6)


def test_unsupported_and_mechanisms_are_refused():
    nodes, members = beam()
    with pytest.raises(frame.Unstable):
        frame.solve(nodes, members, {}, {1: (0, 0, -1, 0, 0, 0)})
    with pytest.raises(frame.Unstable):  # pinned both ends: free to spin about its own axis
        frame.solve(nodes, members, {0: PIN, 1: PIN}, {1: (0, 0, -1, 0, 0, 0)})
    with pytest.raises(frame.Unstable):
        frame.solve(nodes, [], {0: FIXED})


def test_a_member_split_in_parts_gives_the_same_answer():
    one = frame.solve(*beam(1, 4.0), {0: FIXED}, {1: (0, 0, -7, 0, 0, 0)})
    four = frame.solve(*beam(4, 4.0), {0: FIXED}, {4: (0, 0, -7, 0, 0, 0)})
    assert one["displacements"][1][2] == pytest.approx(four["displacements"][4][2], rel=1e-9)


def test_a_partial_load_and_several_cases_share_one_solve():
    L, w = 6.0, 4.0
    nodes, members = beam(L=L)
    supports = {0: PIN, 1: (False, True, True, True, False, False)}
    half = [{"member": 0, "w": (0, 0, -w), "a": 0.0, "b": 0.5}]  # load on the left half only
    full = [{"member": 0, "w": (0, 0, -w)}]
    r_half, r_full = frame.solve_many(nodes, members, supports, [({}, half), ({}, full)], stations=12)
    total = w * L / 2
    left = r_half["reactions"][0][2]
    assert left == pytest.approx(total * 3 / 4) and r_half["reactions"][1][2] == pytest.approx(total / 4)
    m = r_half["members"][0]
    x0 = left / w  # zero shear: the largest moment
    assert max(abs(v) for v in m["My"]) == pytest.approx(left * x0 - w * x0 ** 2 / 2, rel=0.02)
    assert abs(r_full["members"][0]["My"][6]) == pytest.approx(w * L ** 2 / 8, rel=1e-6)
    # the half-loaded beam's midspan deflection: 5wL^4/768EI (half of the full load's, by symmetry)
    assert m["deflection"] == pytest.approx(5 * w * L ** 4 / (768 * E * SEC["Iy"]), rel=0.02)
