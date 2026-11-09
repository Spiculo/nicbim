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


# ---------------------------------------------------------------- D238: the node graph

def test_a_node_graph_becomes_a_script_in_dependency_order():
    import json as _json

    from kimbim import app_bridge as _b

    def c(fn, *a):
        return _json.loads(getattr(_b, fn)(*a))

    assert c("new_project", "Graph")["ok"]
    # drawn right to left on purpose: the massing (x=0) needs the two numbers to its right
    graph = {"nodes": [{"id": 7, "op": "massing", "args": {"x": 0, "y": 0, "depth": 6, "height": 3}, "x": 0, "y": 0},
                       {"id": 3, "op": "number", "args": {"value": 4}, "x": 300, "y": 0},
                       {"id": 5, "op": "multiply", "args": {"b": 2.5}, "x": 600, "y": 0}],
             "links": [{"from": 3, "to": 5, "arg": "a"}, {"from": 5, "to": 7, "arg": "width"}]}
    steps = c("graph_to_steps", _json.dumps(graph))
    assert steps["ok"], steps
    assert [s["op"] for s in steps["steps"]] == ["number", "multiply", "massing"]
    assert steps["steps"][1]["args"]["a"] == "$1" and steps["steps"][2]["args"]["width"] == "$2"
    assert c("save_graph", "Box from numbers", _json.dumps(graph))["ok"]
    run = c("run_pipeline", "Box from numbers", "")
    assert run["ok"], run
    assert run["results"][1]["value"] == 10.0
    box = _b._model.by_guid(run["results"][2]["guid"])
    import ifcopenshell.util.element as U

    assert abs(U.get_pset(box, "KIMBIM_Massing")["Width"] - 10.0) < 1e-6
    back = c("steps_to_graph", _json.dumps(steps["steps"]))
    assert len(back["nodes"]) == 3 and len(back["links"]) == 2
    loop = {"nodes": [{"id": 1, "op": "add", "args": {}}, {"id": 2, "op": "add", "args": {}}],
            "links": [{"from": 1, "to": 2, "arg": "a"}, {"from": 2, "to": 1, "arg": "a"}]}
    assert not c("graph_to_steps", _json.dumps(loop))["ok"]
