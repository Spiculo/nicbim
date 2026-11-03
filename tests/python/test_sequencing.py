# SPDX-License-Identifier: GPL-3.0-or-later
"""D214: construction sequencing (4D) with dated phases and element assignments."""
import json

import ifcopenshell.util.element

from kimbim import app_bridge as b


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def g(*guids):
    return json.dumps(list(guids))


def test_phases_and_element_assignment():
    assert call("new_project", "4D")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    wall_type = next(t for t in call("wall_types")["types"] if t["name"] == "Exterior 300")["guid"]
    wall = call("create_wall", level, wall_type, 0, 0, 10, 0, 3.0, "", "")["guid"]

    r = call("save_phase", "Foundations", "2026-01-05", "2026-01-20")
    assert r["ok"], r
    phase = r["phase"]
    assert call("assign_phase", g(wall), phase["id"])["ok"]
    data = call("phases")
    assert data["phases"][0]["count"] == 1 and wall in data["phases"][0]["elements"]
    assert data["start"] == "2026-01-05" and data["end"] == "2026-01-20"
    pset = ifcopenshell.util.element.get_pset(b._model.by_guid(wall), "KIMBIM_Construction")
    assert pset["Phase"] == phase["id"] and pset["Start"] == "2026-01-05"

    assert not call("save_phase", "Bad", "2026-02-01", "2026-01-01")["ok"]
    assert not call("save_phase", "", "2026-01-01", "2026-01-02")["ok"]
    assert call("assign_phase", g(wall), "")["ok"]
    assert ifcopenshell.util.element.get_pset(b._model.by_guid(wall), "KIMBIM_Construction") is None
    assert call("phases")["phases"][0]["count"] == 0

    assert call("delete_phase", phase["id"])["ok"]
    assert call("phases")["phases"] == []
    assert not call("delete_phase", "nope")["ok"]
    assert not call("assign_phase", g(wall), "nope")["ok"]
