# SPDX-License-Identifier: GPL-3.0-or-later
"""D244: water supply peak flows, pipe sizes and pressure at the fixtures."""
import json

import pytest

from kimbim import app_bridge as B
from kimbim import engsettings as E
from kimbim import mep as M
from kimbim import plumbing as P


def call(fn, *args):
    target = getattr(B, fn) if isinstance(fn, str) else fn
    return json.loads(target(*args))


def bathroom():
    """A water main, a cold main at 0.3 m and drops to a WC, a basin and a shower."""
    assert call("new_project", "Water")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    assert call(M.create_mep_system, "CW", "cold_water")["ok"]
    assert call(M.place_mep_terminal, "water_main", l1, 0, 0, 0.3, 0, "CW")["ok"]  # port (0.15, 0, 0.4)
    assert call(M.create_mep_run3d, l1, "pipe", json.dumps([[0.15, 0, 0.4], [6, 0, 0.4]]), 0.028, 0.028, "CW")["ok"]
    out = []
    for x, kind in ((2, "wc"), (4, "basin"), (6, "shower")):
        t = call(M.place_mep_terminal, kind, l1, x, -1, "", 0, "CW")["guid"]
        port = next(q for p, q in M.port_points(B._model.by_guid(t)) if M.port_kind(p) == "cold_water")
        r = call(M.create_mep_run3d, l1, "pipe", json.dumps([[x, 0, 0.4], [port[0], 0, 0.4], [port[0], port[1], 0.4],
                                                            [port[0], port[1], port[2]]]), 0.015, 0.015, "CW")
        assert r["ok"], r
        out.append(t)
    assert call(M.mep_network, "CW")["unreached"] == []
    return l1, out


def test_peak_flow_formula():
    cfg = E.DEFAULTS["plumbing_settings"]
    assert P.peak_flow(0.1, 0.1, cfg) == 0.1  # one fixture: its own flow
    assert P.peak_flow(1.0, 0.2, cfg) == pytest.approx(1.48 - 0.94)
    assert P.peak_flow(0.3, 0.2, cfg) <= 0.3


def test_a_bathroom_is_sized_and_has_pressure():
    _l1, fixtures = bathroom()
    r = call(P.size_water_system, "CW")
    assert r["ok"], r
    main = max(r["segments"], key=lambda s: s["sum_flow"])
    assert main["sum_flow"] == pytest.approx(0.4)  # WC 0.1 + basin 0.1 + shower 0.2
    assert main["flow"] == pytest.approx(P.peak_flow(0.4, 0.2, E.DEFAULTS["plumbing_settings"]), abs=1e-3)
    for s in r["segments"]:
        assert s["velocity"] <= 2.0
    assert len(r["fixtures"]) == 3 and all(f["status"] == "ok" for f in r["fixtures"])
    assert r["critical_pressure_kpa"] < 300
    assert call(P.size_water_system, "CW", True)["applied"]
    assert M.design_values(B._model.by_guid(main["guid"]))["Nominal"] == main["nominal"]


def test_low_supply_pressure_is_flagged():
    bathroom()
    assert call(E.set_engineering_settings, "plumbing_settings", json.dumps({"supply_pressure_kpa": 100}))["ok"]
    r = call(P.size_water_system, "CW")
    assert any("below" in w for w in r["warnings"])
    assert any(f["status"] == "low pressure" for f in r["fixtures"])


def test_a_system_without_a_source_is_refused():
    assert call("new_project", "Water")["ok"]
    assert call(M.create_mep_system, "CW", "cold_water")["ok"]
    assert not call(P.size_water_system, "CW")["ok"]
