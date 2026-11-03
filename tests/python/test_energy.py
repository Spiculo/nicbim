# SPDX-License-Identifier: GPL-3.0-or-later
"""D222: early-stage energy and daylight estimates from the model envelope."""
import json

import pytest

from kimbim import app_bridge as B
from kimbim import energy as E


def call(fn, *args):
    target = getattr(B, fn) if isinstance(fn, str) else fn
    return json.loads(target(*args))


def flat():
    """A 10 x 6 m room of 300 mm exterior walls with one 1.2 x 1.2 m window."""
    assert call("new_project", "Energy")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    ext = next(t for t in call("wall_types")["types"] if t["name"] == "Exterior 300")["guid"]
    points = [(0, 0), (10, 0), (10, 6), (0, 6)]
    walls, last = [], ""
    for i in range(4):
        (x1, y1), (x2, y2) = points[i], points[(i + 1) % 4]
        end = walls[0] if i == 3 else ""
        r = call("create_wall", level, ext, x1, y1, x2, y2, 3.0, last, end)
        assert r["ok"], r
        walls.append(r["guid"])
        last = r["guid"]
    assert call("create_room", level, 5.0, 3.0, "Room")["ok"]
    window_type = next(t["guid"] for t in call("opening_types", "window")["types"]
                       if t["name"] == "Window 1200x1200")
    assert call("insert_opening", "window", walls[0], window_type, 5.0, 1.2, 1.2, 0.9)["ok"]
    return level, walls


def test_energy_and_daylight_from_the_envelope():
    flat()
    report = call(E.energy_report)
    assert report["ok"]
    assert len(report["levels"]) == 1
    row = report["levels"][0]
    assert row["name"] == "Level 1"
    assert 90.0 < row["wall_area"] < 110.0  # four 3 m walls, the joins extend the faces a little
    assert row["window_area"] == pytest.approx(1.44, abs=0.02)
    assert row["floor_area"] == pytest.approx(9.7 * 5.7, abs=0.5)  # inside the 300 mm walls
    assert row["heating_kwh"] > 0 and row["lighting_kwh"] > 0
    assert row["daylight_factor"] > 0
    assert 0.0 < row["glazing_ratio"] < 0.1
    assert report["total"]["floor_area"] == row["floor_area"]
    assert "not a compliance" in report["note"].lower()
    # A room without a window is flagged for daylight.
    assert call("new_project", "Dark")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    ext = next(t for t in call("wall_types")["types"] if t["name"] == "Exterior 300")["guid"]
    points = [(0, 0), (6, 0), (6, 4), (0, 4)]
    for i in range(4):
        (x1, y1), (x2, y2) = points[i], points[(i + 1) % 4]
        call("create_wall", level, ext, x1, y1, x2, y2, 3.0, "", "")
    call("create_room", level, 3.0, 2.0, "Dark room")
    row = call(E.energy_report)["levels"][0]
    assert row["daylight_factor"] == 0.0
    assert any("daylight" in warning for warning in row["warnings"])


def test_energy_inputs_round_trip_and_are_validated():
    flat()
    before = call(E.energy_report)["levels"][0]["heating_kwh"]
    settings = call(E.energy_settings)["settings"]
    assert settings["wall_u"] > 0 and settings["window_u"] > 0
    assert call(E.set_energy_settings, json.dumps({"window_u": 0.0, "air_changes": 0.0}))["ok"]
    after = call(E.energy_report)["levels"][0]["heating_kwh"]
    assert after < before  # no window losses and no ventilation
    assert call(E.energy_settings)["settings"]["window_u"] == 0.0
    assert not call(E.set_energy_settings, json.dumps({"glazing_transmittance": 2.0}))["ok"]
    assert not call(E.set_energy_settings, json.dumps({"wall_u": -1}))["ok"]
    assert not call(E.set_energy_settings, json.dumps({"unrelated": 1}))["ok"]
    assert call(E.energy_settings)["settings"]["window_u"] == 0.0
    # One undoable settings change.
    assert call("undo")["ok"]
    assert call(E.energy_settings)["settings"]["window_u"] > 0
