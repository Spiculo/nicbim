# SPDX-License-Identifier: GPL-3.0-or-later
"""The operation log: every step after the last recovery copy is replayed after a crash."""
import json
import pathlib

import ifcopenshell
import pytest

from kimbim import app_bridge as b
from kimbim import documents as D
from kimbim import oplog


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_data_dir", tmp_path / "data")
    yield tmp_path


def _names(path):
    return sorted(w.Name for w in ifcopenshell.open(path).by_type("IfcWall"))


def test_steps_undo_and_redo_are_replayed(isolated):
    project = isolated / "house.ifc"
    assert call("new_project", "Log")["ok"]
    assert call("save", str(project))["ok"]  # the log starts from the saved file
    l1 = call("storeys")["storeys"][0]["guid"]
    ext = {t["name"]: t["guid"] for t in call("wall_types")["types"]}["Exterior 300"]
    a = call("create_wall", l1, ext, 0, 0, 5, 0, 3.0, "", "")["guid"]
    bw = call("create_wall", l1, ext, 0, 3, 5, 3, 3.0, "", "")["guid"]
    assert call("set_name", json.dumps([a]), "North")["ok"]
    assert call("set_name", json.dumps([bw]), "South")["ok"]
    assert call("undo")["ok"]  # South is undone
    assert call("redo")["ok"]
    assert call("undo")["ok"]
    assert oplog.lines() == 7
    folder = oplog._folder()
    info = json.loads((folder / "info.json").read_text())
    assert info["journal"] and info["base"] == str(project)
    out = isolated / "replayed.ifc"
    r = oplog.replay(info["base"], str(folder / "journal.jsonl"), str(out))
    assert r["steps"] == 4 and r["settings"] is not None
    names = _names(out)
    assert "North" in names and "South" not in names and len(names) == 2  # as the session left it
    assert sorted(w.GlobalId for w in ifcopenshell.open(str(out)).by_type("IfcWall")) == sorted([a, bw])


def test_recover_replays_the_log(isolated):
    project = isolated / "flat.ifc"
    assert call("new_project", "Log")["ok"]
    assert call("save", str(project))["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    ext = {t["name"]: t["guid"] for t in call("wall_types")["types"]}["Exterior 300"]
    wall = call("create_wall", l1, ext, 0, 0, 4, 0, 3.0, "", "")["guid"]
    assert call("set_name", json.dumps([wall]), "Logged")["ok"]
    folder = oplog._folder()
    assert (folder / "journal.jsonl").exists() and not (folder / "model.ifc").exists()  # no full copy yet
    r = call("recover", folder.name)
    assert r["ok"], r
    assert "Logged" in _names(r["path"])


def test_a_cut_last_line_is_ignored(isolated, tmp_path):
    project = tmp_path / "p.ifc"
    assert call("new_project", "Log")["ok"]
    assert call("save", str(project))["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    ext = {t["name"]: t["guid"] for t in call("wall_types")["types"]}["Exterior 300"]
    call("create_wall", l1, ext, 0, 0, 4, 0, 3.0, "", "")
    journal = oplog._folder() / "journal.jsonl"
    with open(journal, "a", encoding="utf-8") as f:
        f.write('{"op": "step", "ops": [')  # the crash cut it short
    r = oplog.replay(str(project), str(journal), str(tmp_path / "out.ifc"))
    assert r["steps"] == 1
    assert len(ifcopenshell.open(str(tmp_path / "out.ifc")).by_type("IfcWall")) == 1
