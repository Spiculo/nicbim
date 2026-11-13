# SPDX-License-Identifier: GPL-3.0-or-later
"""D246: circuits, breakers, cables, voltage drop and the panel schedule."""
import json
import math

import pytest

from kimbim import app_bridge as B
from kimbim import electrical as El
from kimbim import engsettings as E
from kimbim import mep as M


def call(fn, *args):
    target = getattr(B, fn) if isinstance(fn, str) else fn
    return json.loads(target(*args))


def board_with(devices):
    assert call("new_project", "Power")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    board = call(M.place_mep_terminal, "board", l1, 0, 0)["guid"]
    guids = [call(M.place_mep_terminal, kind, l1, x, y)["guid"] for kind, x, y in devices]
    return l1, board, guids


def test_a_circuit_sizes_by_hand():
    cfg = E.DEFAULTS["electrical_settings"]
    r = El.size_circuit(3000.0, 20.0, False, "power", cfg, 1.0)
    ib = 3000 / 230
    assert r["design_current"] == pytest.approx(ib, abs=0.01)
    assert r["breaker"] == 16  # next above 13.04 A
    assert r["cable"] == 2.5  # 27 A >= 16 A
    assert r["voltage_drop"] == pytest.approx(2 * 20 * ib * 0.0225 / 2.5 * 1.0 / 230 * 100, abs=0.01)
    long = El.size_circuit(3000.0, 80.0, False, "power", cfg, 1.0)
    assert long["cable"] > 2.5 and long["upsized"] >= 1 and long["voltage_drop"] <= 5.0


def test_circuits_on_a_board_and_the_schedule():
    _l1, board, devs = board_with([("socket", 3, 0), ("socket", 6, 0), ("light", 3, 3), ("light", 6, 3),
                                   ("appliance", 2, -2)])
    sockets, lights, oven = devs[:2], devs[2:4], devs[4:]
    c1 = call(El.create_circuit, board, json.dumps(sockets))
    assert c1["ok"] and c1["name"].endswith("-1")
    c2 = call(El.create_circuit, board, json.dumps(lights))
    c3 = call(El.create_circuit, board, json.dumps(oven), "Oven", "L1")
    assert c2["ok"] and c3["ok"]
    listed = call(El.circuits, board)
    assert {c["kind"] for c in listed["circuits"]} == {"power", "lighting"}
    r = call(El.panel_schedule, board)
    assert r["ok"], r
    rows = {c["name"]: c for c in r["circuits"]}
    assert rows[c1["name"]]["demand_va"] == pytest.approx(2 * 200 * 0.5)
    assert rows[c2["name"]]["kind"] == "lighting" and rows[c2["name"]]["cable"] >= 1.5
    assert rows["Oven"]["demand_va"] == pytest.approx(2000 * 0.8) and rows["Oven"]["phase"] == "L1"
    assigned = {rows[c1["name"]].get("phase_assigned"), rows[c2["name"]].get("phase_assigned")}
    assert "L1" not in assigned  # the auto circuits go to the phases the oven left empty
    assert r["total_demand_va"] == pytest.approx(sum(c["demand_va"] for c in r["circuits"]))
    assert call(El.panel_schedule, board, True)["applied"]
    assert call(El.circuits, board)["circuits"][0]["phase"] in ("L1", "L2", "L3")


def test_typed_length_and_bad_input():
    _l1, board, devs = board_with([("socket", 1, 0)])
    c = call(El.create_circuit, board, json.dumps(devs))["guid"]
    assert call(El.edit_circuit, c, json.dumps({"Length": 120.0}))["ok"]
    r = call(El.panel_schedule, board)
    assert r["circuits"][0]["length"] == 120.0 and r["circuits"][0]["length_typed"]
    assert not call(El.edit_circuit, c, json.dumps({"Phase": "L9"}))["ok"]
    assert not call(El.create_circuit, devs[0], json.dumps(devs))["ok"]  # not a board
    assert not call(El.create_circuit, board, "[]")["ok"]
    assert call(El.remove_circuit, c)["ok"]
    assert call(El.circuits, board)["circuits"] == []
    assert math.isclose(1, 1)
