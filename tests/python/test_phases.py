# SPDX-License-Identifier: GPL-3.0-or-later
"""Revit-style phases: elements created and demolished in phases, and the views' phase filter."""
import json

from conftest import build_model

from kimbim import app_bridge as b
from kimbim import phases as P


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def test_states():
    assert P.state(0, None, 1) == "existing"
    assert P.state(1, None, 1) == "new"
    assert P.state(0, 1, 1) == "demolished"
    assert P.state(0, 0, 1) == "gone"
    assert P.state(2, None, 1) == "future"


def test_phase_filters(tmp_path):
    f = build_model(walls=3)
    path = tmp_path / "p.ifc"
    f.write(str(path))
    assert call("open_model", str(path))["ok"]
    old, demo, new = [w.GlobalId for w in f.by_type("IfcWall")]
    assert call("set_phases", json.dumps(["Existing", "Stage 1", "Stage 2"]))["ok"]
    assert call("assign_building_phase", json.dumps([demo]), "Existing", "Stage 1")["ok"]
    assert call("assign_building_phase", json.dumps([new]), "Stage 1")["ok"]
    assert not call("assign_building_phase", json.dumps([new]), "Stage 1", "Existing")["ok"]  # demolished before built
    r = call("phase_filter", "Stage 1", "all")
    assert r["demolished"] == [demo] and r["new"] == [new] and r["hidden"] == []
    assert call("phase_filter", "Stage 1", "complete")["hidden"] == [demo]
    only_new = call("phase_filter", "Stage 1", "new")
    assert new not in only_new["hidden"] and demo in only_new["hidden"] and old in only_new["hidden"]
    assert call("phase_filter", "Stage 1", "existing")["hidden"] == [new]
    assert call("phase_filter", "Existing", "all")["hidden"] == [new]  # not built yet
    assert set(call("phase_filter", "Stage 2", "all")["hidden"]) == {demo}  # gone by then
    assert call("set_phase_view", "Stage 2", "complete")["ok"]
    assert call("building_phases")["phase"] == "Stage 2" and call("building_phases")["filter"] == "complete"
    assert not call("set_phase_view", "Nope", "all")["ok"]
    assert not call("set_phases", json.dumps(["A", "A"]))["ok"]
