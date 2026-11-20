# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent construction and drafting tools (D102, D129): roofs, stairs, ramps, railings, grids, slab
openings, wall heights, drafting shapes and annotations on the sample house."""
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


def test_construction_tools_create_the_elements(s):
    roof = run(s, "create.roof", level="Level 1", points=[[40, 40], [50, 40], [50, 50], [40, 50]],
               kind="gable", pitch=30)
    assert roof["ok"], roof
    assert B._model.by_guid(roof["result"]["guids"][0]).is_a("IfcRoof")

    stair = run(s, "create.stair", level="Level 1", start=[60, 60], end=[64, 60], width="1.2m")
    assert stair["ok"], stair
    assert B._model.by_guid(stair["result"]["guids"][0]).is_a("IfcStair")
    assert stair["result"]["risers"] >= 2

    ramp = run(s, "create.ramp", level="Level 1", start=[70, 60], end=[74, 60], slope=10)
    assert ramp["ok"], ramp
    assert B._model.by_guid(ramp["result"]["guids"][0]).is_a("IfcRamp")

    railing = run(s, "create.railing", level="Level 1", points=[[80, 60], [85, 60]])
    assert railing["ok"], railing
    assert B._model.by_guid(railing["result"]["guids"][0]).is_a("IfcRailing")

    grid = run(s, "create.grid", level="Level 1", origin=[90, 60], across=[4, 4], along=[5, 5])
    assert grid["ok"], grid
    assert B._model.by_guid(grid["result"]["guid"]).is_a("IfcGrid")

    axis = run(s, "create.grid_axis", level="Level 1", start=[90, 70], end=[100, 70], tag="Z")
    assert axis["ok"], axis


def test_slab_opening_and_wall_height(s):
    slab = run(s, "create.slab", level="Level 1", points=[[40, 70], [48, 70], [48, 78], [40, 78]])
    assert slab["ok"], slab
    opening = run(s, "create.slab_opening", slab=slab["result"]["guids"][0],
                  points=[[42, 72], [45, 72], [45, 75], [42, 75]])
    assert opening["ok"], opening

    wall = B._model.by_type("IfcWall")[0]
    resized = run(s, "elements.set_wall_height", walls=[wall.GlobalId], height="4.5m")
    assert resized["ok"], resized
    assert B._model.by_guid(wall.GlobalId).is_a("IfcWall")


def test_drafting_tools(s):
    line = run(s, "draft.add", level="Level 1", kind="line", points=[[30, 30], [35, 30]])
    assert line["ok"] and line["result"]["guids"], line
    rectangle = run(s, "draft.add", level="Level 1", kind="rectangle", points=[[30, 32], [35, 35]])
    assert rectangle["ok"], rectangle
    circle = run(s, "draft.add", level="Level 1", kind="circle", points=[[40, 35], [41, 35]])
    assert circle["ok"], circle
    fill = run(s, "draft.fill_from_shape", shape=rectangle["result"]["guids"][0], pattern="Diagonal",
               show_area=True)
    assert fill["ok"] and fill["result"]["guids"], fill
    patterns = run(s, "draft.patterns")
    assert patterns["ok"] and "Solid" in patterns["result"]["patterns"]


def test_annotation_tools(s):
    text = run(s, "annotation.add", level="Level 1", kind="text", points=[[30, 40]], text="Hola")
    assert text["ok"] and text["result"]["guids"], text
    dimension = run(s, "annotation.add", level="Level 1", kind="dimension",
                    points=[[30, 42], [35, 42], [40, 42]])
    assert dimension["ok"], dimension

    wall = B._model.by_type("IfcWall")[0]
    tag = run(s, "annotation.tag", element=wall.GlobalId, at=[31, 41])
    assert tag["ok"] and tag["result"]["guids"], tag
    north = run(s, "annotation.symbol", level="Level 1", kind="north", points=[[50, 50]])
    assert north["ok"] and north["result"]["guids"], north
    dimensions = run(s, "annotation.auto_dimension", elements=[wall.GlobalId], offset="1m")
    assert dimensions["ok"] and dimensions["result"]["guids"], dimensions

    all_tags = run(s, "annotation.tag_all", level="Level 1")
    assert all_tags["ok"], all_tags
    assert len(B._model.by_type("IfcAnnotation")) >= 4
