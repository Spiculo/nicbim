# SPDX-License-Identifier: GPL-3.0-or-later
"""D243: airflow from rooms, duct sizing and pressure drop."""
import json

import pytest

from kimbim import app_bridge as B
from kimbim import engsettings as E
from kimbim import hvac as H
from kimbim import mep as M


def call(fn, *args):
    target = getattr(B, fn) if isinstance(fn, str) else fn
    return json.loads(target(*args))


def two_rooms():
    """A 10 x 5 m box split in two rooms, an AHU, a main along y = 2.5 and a diffuser in each room."""
    assert call("new_project", "Air")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    wt = call("wall_types")["types"][0]["guid"]
    for a, b in (((0, 0), (10, 0)), ((10, 0), (10, 5)), ((10, 5), (0, 5)), ((0, 5), (0, 0)), ((5, 0), (5, 5))):
        assert call("create_wall", l1, wt, *a, *b, 3.0)["ok"]
    assert call("create_room", l1, 2.5, 2.5, "Office A")["ok"]
    assert call("create_room", l1, 7.5, 2.5, "Office B")["ok"]
    assert call(M.create_mep_system, "SA", "supply_air")["ok"]
    assert call(M.place_mep_terminal, "ahu", l1, 1.0, 1.0, 0, 0, "SA")["ok"]
    # AHU supply port at (0.5, 1, 1.5): up to 2.75 then along to x = 7.5
    run = call(M.create_mep_run3d, l1, "duct", json.dumps([[0.5, 1, 1.5], [0.5, 1, 2.85], [0.5, 2.5, 2.85],
                                                           [7.5, 2.5, 2.85]]), 0.3, 0.3, "SA")
    assert run["ok"], run
    drop = call(M.create_mep_run3d, l1, "duct", json.dumps([[2.5, 2.5, 2.85], [2.5, 2.5, 2.75]]), 0.2, 0.2, "SA")
    assert drop["ok"] and drop["tees"], drop
    d1 = call(M.place_mep_terminal, "supply_diffuser", l1, 2.5, 2.5, 2.7, 0, "SA")["guid"]
    end = call(M.create_mep_run3d, l1, "duct", json.dumps([[7.5, 2.5, 2.85], [7.5, 2.5, 2.75]]), 0.2, 0.2, "SA")
    assert end["ok"], end
    d2 = call(M.place_mep_terminal, "supply_diffuser", l1, 7.5, 2.5, 2.7, 0, "SA")["guid"]
    net = call(M.mep_network, "SA")
    assert net["unreached"] == [], net
    return l1, d1, d2


def test_room_flows_follow_en16798_and_add_up():
    _l1, d1, d2 = two_rooms()
    r = call(H.size_air_system, "SA")
    assert r["ok"], r
    by = {t["guid"]: t for t in r["terminals"]}
    area = by[d1]["flow"]  # one room: inside the 300 mm walls ~ 4.7 x 4.4 m
    room_area = (area - 0.0) / (7.0 / 10.0 + 0.7)  # 7 L/s per person at 10 m2/person + 0.7 L/s m2
    assert 15 < room_area < 25
    assert r["system_flow"] == pytest.approx(by[d1]["flow"] + by[d2]["flow"], abs=0.02)
    mains = [s for s in r["segments"] if s["role"] == "main"]
    assert mains and max(s["flow"] for s in mains) == pytest.approx(r["system_flow"], abs=0.02)
    for s in r["segments"]:
        if s["flow"] > 0:
            limit = {"main": 6.0, "branch": 4.0, "terminal": 2.5}[s["role"]]
            assert s["velocity"] <= limit + 1e-9 and s["gradient"] <= 1.0 + 1e-9, s
    assert r["fan_pressure"] > 25 and r["critical_terminal"] in (d1, d2)


def test_a_manual_flow_wins_and_apply_resizes_in_one_undo_step():
    _l1, d1, _d2 = two_rooms()
    assert call(M.set_design_values, d1, json.dumps({"Flow": 400.0}))["ok"]
    r = call(H.size_air_system, "SA", True)
    assert r["ok"] and r["applied"]
    assert next(t for t in r["terminals"] if t["guid"] == d1)["flow"] == 400.0
    big = max(r["segments"], key=lambda s: s["flow"])
    seg = B._model.by_guid(big["guid"])
    w, h, shape = M.segment_size(seg)
    assert (w, h) == pytest.approx((big["width"], big["height"]))
    assert w * h >= 0.4 / 6.0 - 1e-9  # 400+ L/s at <= 6 m/s
    assert M.design_values(seg)["SizedBy"] == "hvac"
    assert call("undo")["ok"]
    assert M.segment_size(B._model.by_guid(big["guid"]))[:2] == pytest.approx((0.3, 0.3))


def test_round_ducts_and_settings():
    assert call("new_project", "Air")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    assert call(M.create_mep_system, "EA", "exhaust_air")["ok"]
    assert call(M.place_mep_terminal, "fan", l1, 0, 0, 2.5, 0, "EA")["ok"]
    # the fan's suction port is at (0, -0.25, 2.75); a pipe-like round duct would be "duct" with width only
    assert call(E.set_engineering_settings, "hvac_settings", json.dumps({"friction_pa_m": 0.5}))["ok"]
    assert call(M.create_mep_run3d, l1, "duct", json.dumps([[0, -0.25, 2.75], [0, -4, 2.75]]), 0.2, 0.2, "EA")["ok"]
    t = call(M.place_mep_terminal, "exhaust_valve", l1, 0, -4, 2.7, 0, "EA")["guid"]
    assert call(M.set_design_values, t, json.dumps({"Flow": 50.0}))["ok"]
    r = call(H.size_air_system, "EA")
    assert r["ok"], r
    s = r["segments"][0]
    assert s["flow"] == 50.0 and s["gradient"] <= 0.5
    assert any("0.5 Pa/m" in a for a in r["assumptions"])
    assert H.equivalent_diameter(0.4, 0.2) == pytest.approx(1.30 * (0.08 ** 0.625) / (0.6 ** 0.25))
    assert not call(H.size_air_system, "nope")["ok"]
    assert call(M.create_mep_system, "CW", "cold_water")["ok"]
    assert not call(H.size_air_system, "CW")["ok"]


def test_the_duct_schedule_shows_the_sizing():
    two_rooms()
    assert call(H.size_air_system, "SA", True)["applied"]
    from kimbim import schedules

    r = json.loads(schedules.schedule("ducts"))
    assert r["ok"], r
    text = json.dumps(r)
    assert "Flow (L/s)" in text and "Velocity (m/s)" in text
    fixtures = json.loads(schedules.schedule("fixtures"))
    assert fixtures["ok"] and "Design flow (L/s)" in json.dumps(fixtures)
