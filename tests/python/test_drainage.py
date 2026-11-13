# SPDX-License-Identifier: GPL-3.0-or-later
"""D245: sanitary and storm drainage sizing and slope checks."""
import json
import math

import pytest

from kimbim import app_bridge as B
from kimbim import drainage as D
from kimbim import mep as M


def call(fn, *args):
    target = getattr(B, fn) if isinstance(fn, str) else fn
    return json.loads(target(*args))


def bathroom(slope=0.02):
    """WC, basin and shower branch into a collector at `slope` falling to x = 0, which drops into the outlet."""
    assert call("new_project", "Drain")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    assert call(M.create_mep_system, "WW", "sanitary")["ok"]
    out = call(M.place_mep_terminal, "drain_outlet", l1, 0, 0, -0.5, 0, "WW")["guid"]  # port at z -0.4
    z = lambda x: -0.3 + slope * x  # noqa: E731
    assert call(M.create_mep_run3d, l1, "pipe", json.dumps([[6, 0, z(6)], [0, 0, z(0)], [0, 0, -0.4]]),
                0.11, 0.11, "WW")["ok"]
    fixtures = {}
    for x, kind in ((2, "wc"), (4, "basin"), (6.0, "shower")):
        t = call(M.place_mep_terminal, kind, l1, x, -1, "", 0, "WW")["guid"]
        port = next(q for p, q in M.port_points(B._model.by_guid(t)) if M.port_kind(p) == "sanitary")
        end = [port[0], 0, z(port[0])]
        pts = [list(port), [port[0], port[1], z(port[0]) + 0.02 * abs(port[1])], end]
        if x == 6.0:  # the shower sits at the collector's open end: join it there
            pts = [list(port), [port[0], port[1], z(6) + 0.02 * abs(port[1])], [6, 0, z(6)]]
        r = call(M.create_mep_run3d, l1, "pipe", json.dumps(pts), 0.05, 0.05, "WW")
        assert r["ok"], r
        fixtures[kind] = t
    net = call(M.mep_network, "WW")
    assert net["sources"] == [out] and net["unreached"] == [], net
    return l1, fixtures


def test_part_full_capacity():
    area, radius = D.part_full(0.1, 0.5)
    assert area == pytest.approx(math.pi * 0.1 ** 2 / 8) and radius == pytest.approx(0.1 / 4)
    assert D.capacity(0.1, 0.01, 0.5, 0.011) == pytest.approx(1000 * area * radius ** (2 / 3) * 0.1 / 0.011)


def test_a_bathroom_drains_with_the_wc_governing():
    bathroom()
    r = call(D.size_drainage_system, "WW")
    assert r["ok"], r
    assert r["total_discharge_units"] == pytest.approx(3.1)
    last = max(r["segments"], key=lambda s: s["discharge_units"])
    assert last["flow"] == pytest.approx(2.0)  # 0.5 x sqrt(3.1) < the WC's 2.0
    assert all(s["dn"] >= 90 for s in r["segments"] if s["discharge_units"] >= 2.0)
    horizontal = [s for s in r["segments"] if not s["vertical"]]
    assert horizontal and all(s["status"] == "ok" for s in horizontal), horizontal
    assert any(s["vertical"] for s in r["segments"])
    assert call(D.size_drainage_system, "WW", True)["applied"]


def test_a_pipe_that_rises_to_the_outlet_is_flagged():
    bathroom(slope=-0.02)
    r = call(D.size_drainage_system, "WW")
    assert any("wrong way" in w for w in r["warnings"]), r["warnings"]


def test_a_flat_pipe_is_below_the_minimum_slope():
    bathroom(slope=0.002)
    r = call(D.size_drainage_system, "WW")
    assert any("minimum slope" in w for w in r["warnings"])


def test_storm_drains_take_their_roof_share():
    assert call("new_project", "Storm")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    assert call(M.create_mep_system, "SW", "storm")["ok"]
    out = call(M.place_mep_terminal, "drain_outlet", l1, 0, 0, -1.0, 0, "SW")["guid"]
    t = call(M.place_mep_terminal, "roof_drain", l1, 0, 0, 3.0, 0, "SW")["guid"]
    assert call(M.set_design_values, t, json.dumps({"Area": 100.0}))["ok"]
    assert call(M.set_design_values, out, json.dumps({"Kind": "drain_outlet"}))["ok"]
    assert call(M.create_mep_run3d, l1, "pipe", json.dumps([[0, 0, 3.0], [0, 0, -0.9]]), 0.1, 0.1, "SW")["ok"]
    r = call(D.size_drainage_system, "SW")
    assert r["ok"], r
    assert r["outlet_flow"] == pytest.approx(3.0)  # 0.03 L/s m2 x 100 m2
    assert r["segments"][0]["vertical"] and r["segments"][0]["dn"] >= 90


def test_a_drain_run_falls_at_its_slope():
    assert call("new_project", "Drain")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    r = call(D.create_drain_run, l1, json.dumps([[0, 0], [5, 0], [5, 5]]), -0.2, "", 0.11)
    assert r["ok"], r
    ends = [M.segment_ends(B._model.by_guid(g)) for g in r["segments"]]
    assert ends[-1][1][2] == pytest.approx(-0.2 - 0.02 * 10)
