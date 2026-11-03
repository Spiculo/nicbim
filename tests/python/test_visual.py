# SPDX-License-Identifier: GPL-3.0-or-later
"""D223: linear visual scripts saved with the project and run as one undo step."""
import json

import ifcopenshell.util.element
import ifcopenshell.util.placement
import pytest

from kimbim import app_bridge as B
from kimbim import visual as V
from kimbim.testing import build_model


def call(fn, *args):
    target = getattr(B, fn) if isinstance(fn, str) else fn
    return json.loads(target(*args))


def open_model():
    f = build_model(schema="IFC4", walls=0)
    B._model = f
    B._reset_history("")
    return f, f.by_type("IfcBuildingStorey")[0].GlobalId


def test_a_script_builds_then_shapes_in_one_undo_step():
    f, level = open_model()
    steps = [
        {"op": "massing", "args": {"x": 0, "y": 0, "width": 4, "depth": 6, "height": 3, "name": "Option A"}},
        {"op": "push_pull", "args": {"guid": "$1", "face": "+z", "distance": 4}},
    ]
    assert call(V.save_pipeline, "Tall block", json.dumps(steps))["ok"]
    assert [p["name"] for p in call(V.pipelines)["pipelines"]] == ["Tall block"]
    r = call(V.run_pipeline, "Tall block", level)
    assert r["ok"] and len(r["results"]) == 2
    guid = r["results"][0]["guid"]
    pset = ifcopenshell.util.element.get_pset(f.by_guid(guid), "KIMBIM_Massing")
    assert pset["Width"] == 4.0 and pset["Height"] == 7.0
    matrix = ifcopenshell.util.placement.get_local_placement(f.by_guid(guid).ObjectPlacement)
    assert matrix[2][3] == 0.0
    # The whole run is one undo step.
    assert call("undo")["ok"]
    with pytest.raises(RuntimeError):
        f.by_guid(guid)


def test_bad_scripts_and_steps_are_refused():
    f, level = open_model()
    assert not call(V.save_pipeline, "", json.dumps([{"op": "massing"}]))["ok"]
    assert not call(V.save_pipeline, "x", "not json")["ok"]
    assert not call(V.save_pipeline, "x", json.dumps([]))["ok"]
    assert not call(V.save_pipeline, "x", json.dumps([{"op": "run_python"}]))["ok"]
    assert not call(V.save_pipeline, "x", json.dumps([{"op": "massing", "args": 3}]))["ok"]
    assert call(V.pipelines)["pipelines"] == []
    # A failing step rolls the whole run back.
    assert call(V.save_pipeline, "Broken", json.dumps([
        {"op": "massing", "args": {"width": 2, "depth": 2, "height": 2}},
        {"op": "push_pull", "args": {"guid": "$9", "face": "+z", "distance": 1}},
    ]))["ok"]
    r = call(V.run_pipeline, "Broken", level)
    assert not r["ok"] and "step 2" in r["error"]
    assert not [e for e in f.by_type("IfcProduct") if e.is_a("IfcBuildingElementProxy")]
    # A missing script and a bad op reported at run time.
    assert not call(V.run_pipeline, "Absent", level)["ok"]
    assert call(V.save_pipeline, "Rooms", json.dumps([{"op": "room", "args": {"x": 0, "y": 0}}]))["ok"]
    assert not call(V.run_pipeline, "Rooms", level)["ok"]  # no walls around the point
    assert call(V.delete_pipeline, "Rooms")["ok"]
    assert call(V.pipelines)["pipelines"] and not call(V.delete_pipeline, "Rooms")["ok"]
    ops = {op["op"] for op in call(V.pipeline_ops)["ops"]}
    assert {"massing", "room", "push_pull", "move_vertices"} <= ops
