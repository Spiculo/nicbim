# SPDX-License-Identifier: GPL-3.0-or-later
"""The Undo history panel: labelled steps, renamed by the app, undone and redone several at a time."""
import json

from conftest import build_model

from kimbim import app_bridge


def _open(tmp_path, walls=3):
    f = build_model(walls=walls)
    p = tmp_path / "m.ifc"
    f.write(str(p))
    assert json.loads(app_bridge.open_model(str(p)))["ok"]
    return [w.GlobalId for w in f.by_type("IfcWall")]


def _history():
    return json.loads(app_bridge.undo_history())


def test_steps_are_labelled_and_renamed(tmp_path):
    walls = _open(tmp_path)
    assert _history()["undo"] == []
    assert json.loads(app_bridge.set_name(json.dumps(walls[:1]), "A"))["ok"]
    assert _history()["undo"] == ["Set name"]  # the bridge function, until the app names it
    assert json.loads(app_bridge.label_last_step("Rename wall"))["ok"]
    assert json.loads(app_bridge.set_name(json.dumps(walls[1:2]), "B"))["ok"]
    h = _history()
    assert h["undo"] == ["Rename wall", "Set name"] and h["redo"] == []
    assert json.loads(app_bridge.undo())["ok"]
    h = _history()
    assert h["undo"] == ["Rename wall"] and h["redo"] == ["Set name"]
    assert json.loads(app_bridge.redo())["ok"]
    assert _history()["undo"] == ["Rename wall", "Set name"]
    assert not json.loads(app_bridge.label_last_step("  "))["ok"]


def test_undo_and_redo_several_steps_at_once(tmp_path):
    walls = _open(tmp_path)
    for i, g in enumerate(walls):
        assert json.loads(app_bridge.set_name(json.dumps([g]), f"W{i}"))["ok"]
    r = json.loads(app_bridge.undo_steps("2"))
    assert r["ok"] and r["steps"] == 2 and r["can_undo"] and r["can_redo"]
    h = _history()
    assert len(h["undo"]) == 1 and len(h["redo"]) == 2
    r = json.loads(app_bridge.undo_steps("5"))  # only one left: stops there
    assert r["ok"] and r["steps"] == 1 and not r["can_undo"]
    assert not json.loads(app_bridge.undo_steps("1"))["ok"]
    r = json.loads(app_bridge.redo_steps("3"))
    assert r["ok"] and r["steps"] == 3 and not r["can_redo"]
    assert [json.loads(app_bridge.properties(g))["name"] for g in walls] == ["W0", "W1", "W2"]


def test_a_new_edit_clears_the_redo_labels(tmp_path):
    walls = _open(tmp_path)
    app_bridge.set_name(json.dumps(walls[:1]), "A")
    app_bridge.set_name(json.dumps(walls[:1]), "B")
    app_bridge.undo()
    app_bridge.set_name(json.dumps(walls[:1]), "C")
    h = _history()
    assert h["redo"] == [] and len(h["undo"]) == 2


def test_step_ids_tell_new_steps_from_redone_ones(tmp_path):
    walls = _open(tmp_path)
    assert _history()["max_id"] == 0
    app_bridge.set_name(json.dumps(walls[:1]), "A")
    first = _history()["max_id"]
    app_bridge.undo()
    app_bridge.redo()
    assert _history()["max_id"] == first and _history()["last_id"] == first
    app_bridge.set_name(json.dumps(walls[:1]), "B")
    assert _history()["max_id"] == first + 1
