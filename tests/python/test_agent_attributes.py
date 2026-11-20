# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent layers, graphics, materials, classifications and version-control tools (D102, D130)."""
import json
import sys
from pathlib import Path

import pytest

from kimbim import app_bridge as B
from kimbim import documents as D
from kimbim import nicfile as K
from kimbim import settings as S
from kimbim.agent.catalogue import call_tool
from kimbim.agent.session import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import make_house  # noqa: E402


@pytest.fixture
def s(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_data_dir", tmp_path / "data")
    monkeypatch.setattr(K, "display_user", "")
    ifc = tmp_path / "house.ifc"
    make_house.build(str(ifc))
    out = json.loads(D.import_ifc(str(ifc), str(tmp_path / "house.nic")))
    assert out["ok"]
    D.close_document()
    session = Session.open(str(tmp_path / "house.nic"))
    assert json.loads(S.set_project_settings(json.dumps({"agent_changes": "direct"})))["ok"]
    yield session
    session.close()


def run(s, tool_name, **args):
    return call_tool(s, tool_name, args, client="test")


def test_layers_and_graphics(s):
    made = run(s, "layers.create", name="Consultants")
    assert made["ok"], made
    wall = B._model.by_type("IfcWall")[0]
    assigned = run(s, "layers.assign", elements=[wall.GlobalId], layer="Consultants")
    assert assigned["ok"], assigned
    assert any(l["name"] == "Consultants" for l in run(s, "layers.list")["result"]["layers"])

    renamed = run(s, "layers.rename", name="Consultants", new_name="Consultant links")
    assert renamed["ok"], renamed
    empty = run(s, "layers.create", name="Empty")
    assert empty["ok"], empty
    assert run(s, "layers.delete", name="Empty")["ok"]
    removed = run(s, "layers.delete", name="Consultant links")
    assert removed["ok"]  # the wall stays, without a layer

    assert run(s, "graphics.state")["ok"]
    tables = run(s, "graphics.tables")
    assert tables["ok"] and tables["result"]
    assert run(s, "graphics.purpose", name="New construction")["ok"]


def test_materials_and_classifications(s):
    assert run(s, "materials.add_standard")["ok"]
    state = run(s, "materials.list")["result"]
    material = state["materials"][0]["name"]
    wall = B._model.by_type("IfcWall")[0]
    assigned = run(s, "materials.assign", elements=[wall.GlobalId], material=material)
    assert assigned["ok"], assigned

    system = run(s, "classifications.create_system", name="Test system", source="Test")
    assert system["ok"], system
    reference = run(s, "classifications.add_reference", system="Test system", code="T.01", name="Walls")
    assert reference["ok"], reference
    assigned = run(s, "classifications.assign", elements=[wall.GlobalId],
                   references=["Test system|T.01"])
    assert assigned["ok"], assigned
    listed = run(s, "classifications.of_element", elements=[wall.GlobalId])
    assert listed["ok"], listed
    assert "Test system" in json.dumps(listed["result"])


def test_version_tools(s):
    wall = B._model.by_type("IfcWall")[0]
    run(s, "layers.create", name="Master")
    run(s, "layers.assign", elements=[wall.GlobalId], layer="Master")
    saved = run(s, "versions.save", message="Agent: layer test")
    assert saved["ok"] and saved["result"].get("id"), saved

    milestone = run(s, "versions.milestone_create", name="Concept", message="First round")
    assert milestone["ok"], milestone
    assert any(m.get("name") == "Concept" for m in run(s, "versions.milestones")["result"]["milestones"])

    option = run(s, "versions.create_option", name="Facade B")
    assert option["ok"], option
    assert any(o == "Facade B" for o in run(s, "versions.options")["result"]["options"])
