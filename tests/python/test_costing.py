# SPDX-License-Identifier: GPL-3.0-or-later
"""D213: cost estimating (5D) from rates by type and a bill of quantities."""
import json

import pytest

from kimbim import app_bridge as b


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def test_cost_estimate_from_rates():
    assert call("new_project", "Costs")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    wall_type = next(t for t in call("wall_types")["types"] if t["name"] == "Exterior 300")
    wall = call("create_wall", level, wall_type["guid"], 0, 0, 10, 0, 3.0, "", "")["guid"]
    estimate = call("cost_estimate")
    row = next(r for r in estimate["rows"] if r["type"] == "Exterior 300")
    assert row["unit"] == "m3" and row["quantity"] == pytest.approx(9.0, rel=0.02)
    assert row["cost"] == 0 and estimate["total"] == 0

    assert call("set_cost_rates", json.dumps([{"type": "Exterior 300", "rate": 100, "unit": "m3"}]))["ok"]
    estimate = call("cost_estimate")
    row = next(r for r in estimate["rows"] if r["type"] == "Exterior 300")
    assert row["rate"] == 100 and row["cost"] == pytest.approx(900, rel=0.02)
    assert estimate["total"] == row["cost"]

    door = call("opening_types", "door")["types"][0]
    assert call("insert_opening", "door", wall, door["guid"], 2.0, door["width"], door["height"], door["sill"])["ok"]
    assert call("set_cost_rates", json.dumps([{"type": door["name"], "rate": 50, "unit": "pcs"}]))["ok"]
    estimate = call("cost_estimate")
    door_row = next(r for r in estimate["rows"] if r["type"] == door["name"])
    assert door_row["unit"] == "pcs" and door_row["quantity"] == 1 and door_row["cost"] == 50

    assert not call("set_cost_rates", json.dumps([{"type": "X", "rate": -1, "unit": "m3"}]))["ok"]
    assert not call("set_cost_rates", json.dumps([{"type": "X", "rate": 1, "unit": "kg"}]))["ok"]
    assert call("set_cost_rates", json.dumps([{"type": "Exterior 300", "rate": 0, "unit": "m3"}]))["ok"]
    assert all(r["cost"] == 0 for r in call("cost_estimate")["rows"] if r["type"] == "Exterior 300")
