# SPDX-License-Identifier: GPL-3.0-or-later
"""Owner gap 4: curtain walls, sloped slabs and slab edges."""
import json
import math

import ifcopenshell.geom
import ifcopenshell.util.placement
import ifcopenshell.util.representation
import numpy as np
import pytest

from kimbim import app_bridge as b
from kimbim import authoring as A
from kimbim import settings


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def members(guid):
    wall = b._model.by_guid(guid)
    return [m for rel in (wall.IsDecomposedBy or ()) for m in (rel.RelatedObjects or ()) if m.is_a("IfcMember")]


def shape(guid):
    settings_ = ifcopenshell.geom.settings()
    settings_.set("use-world-coords", True)
    return np.array(ifcopenshell.geom.create_shape(settings_, b._model.by_guid(guid)).geometry.verts).reshape(-1, 3)


@pytest.fixture
def project():
    assert call("new_project", "Curtain")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    yield {"level": level, "slab_type": call("slab_types")["types"][0]["guid"]}
    b._model = None
    settings.load(None)


def test_curtain_wall_panel_material(project):
    """D169: the panels take a building material, kept across later updates."""
    import ifcopenshell.util.element

    r = call("create_curtain_wall", project["level"], 0, 0, 6, 0, 3.0, 1.5, 0.04)
    assert r["ok"], r
    guid = r["guid"]
    assert call("curtain_wall_info", guid)["panel_material"] == ""
    assert call("update_curtain_wall", guid, json.dumps({"panel_material": "Glass"}))["ok"]
    material = ifcopenshell.util.element.get_material(b._model.by_guid(guid))
    assert material is not None and material.Name == "Glass"
    info = call("curtain_wall_info", guid)
    assert info["panel_material"] == "Glass" and "Glass" in info["material_choices"]
    assert call("update_curtain_wall", guid, json.dumps({"height": 3.5}))["ok"]
    assert call("curtain_wall_info", guid)["panel_material"] == "Glass"


def test_curtain_panel_copy_and_swap(project):
    """D170: a bay's kind and thickness copy to other bays and swap with another."""
    r = call("create_curtain_wall", project["level"], 0, 0, 6, 0, 3.0, 1.5, 0.04)
    assert r["ok"], r
    guid = r["guid"]
    assert call("set_curtain_panel", guid, 0, json.dumps({"kind": "solid", "thickness": 0.1}))["ok"]
    assert call("copy_curtain_panel", guid, 0, json.dumps([2]))["ok"]
    info = call("curtain_wall_info", guid)
    assert info["panels"][2]["kind"] == "solid"
    assert info["panels"][2]["thickness"] == pytest.approx(0.1)
    assert call("swap_curtain_panels", guid, 0, 1)["ok"]
    info = call("curtain_wall_info", guid)
    assert info["panels"][1]["kind"] == "solid"
    assert info["panels"][0]["kind"] == "glass"
    assert not call("copy_curtain_panel", guid, 0, json.dumps([99]))["ok"]
    assert not call("swap_curtain_panels", guid, 0, 99)["ok"]


def test_a_curtain_wall_is_an_ifc_curtain_wall(project):
    r = call("create_curtain_wall", project["level"], 0, 0, 6, 0, 3.0, 1.5, 0.04)
    assert r["ok"], r
    wall = b._model.by_guid(r["guid"])
    assert wall.is_a("IfcCurtainWall") and wall.is_a("IfcElement")
    assert wall.Representation is not None
    info = call("curtain_wall_info", r["guid"])
    assert info["ok"] and info["height"] == 3.0 and info["spacing"] == 1.5
    # It is a product on the level and a type exists.
    assert wall.is_a("IfcProduct") and wall.ContainedInStructure[0].RelatingStructure.GlobalId == project["level"]
    assert any(t.Name == "Curtain Wall" for t in b._model.by_type("IfcCurtainWallType"))
    assert not call("create_curtain_wall", project["level"], 0, 0, 0, 0, 3.0)["ok"]


def test_update_curtain_wall_spacing_rebuilds_the_members(project):
    r = call("create_curtain_wall", project["level"], 0, 0, 6, 0, 3.0, 1.5, 0.04)
    assert r["ok"], r
    before = members(r["guid"])
    assert len(before) == 7  # five mullions and two rails
    updated = json.loads(A.update_curtain_wall(r["guid"], json.dumps({"spacing": 1.0})))
    assert updated["ok"], updated
    after = members(r["guid"])
    assert updated["parts"] == len(after) == 9
    assert len(after) != len(before)
    assert not ({m.GlobalId for m in before} & {m.GlobalId for m in after})  # rebuilt, not edited
    assert b._model.by_guid(r["guid"]).ContainedInStructure[0].RelatingStructure.GlobalId == project["level"]
    info = call("curtain_wall_info", r["guid"])
    assert info["spacing"] == pytest.approx(1.0) and info["height"] == pytest.approx(3.0)


def test_update_curtain_wall_height_changes_the_body(project):
    r = call("create_curtain_wall", project["level"], 0, 0, 6, 0, 3.0, 1.5, 0.04)
    updated = json.loads(A.update_curtain_wall(r["guid"], json.dumps({"height": 4.5})))
    assert updated["ok"] and updated["height"] == pytest.approx(4.5)
    info = call("curtain_wall_info", r["guid"])
    assert info["height"] == pytest.approx(4.5)
    verts = shape(r["guid"])
    assert verts[:, 2].min() == pytest.approx(0.0, abs=1e-6)
    assert verts[:, 2].max() == pytest.approx(4.5, abs=1e-6)
    # the top rail moved with the panel
    top = max(ifcopenshell.util.placement.get_local_placement(m.ObjectPlacement)[2][3] * A._scale()
              for m in members(r["guid"]) if (m.Name or "") == "Curtain wall top rail")
    assert top == pytest.approx(4.45, abs=1e-6)


def test_update_curtain_wall_panel_thickness(project):
    r = call("create_curtain_wall", project["level"], 0, 0, 6, 0, 3.0, 1.5, 0.04)
    updated = json.loads(A.update_curtain_wall(r["guid"], json.dumps({"panel_thickness": 0.08})))
    assert updated["ok"] and updated["panel_thickness"] == pytest.approx(0.08)
    info = call("curtain_wall_info", r["guid"])
    assert info["panel_thickness"] == pytest.approx(0.08)
    verts = shape(r["guid"])
    assert verts[:, 1].max() - verts[:, 1].min() == pytest.approx(0.08, abs=1e-6)


@pytest.mark.parametrize("changes", [
    {"height": 0}, {"height": -2}, {"spacing": 0.05}, {"spacing": 0},
    {"panel_thickness": 0.001}, {"panel_thickness": 0.6},
])
def test_update_curtain_wall_refuses_out_of_range_values(project, changes):
    r = call("create_curtain_wall", project["level"], 0, 0, 6, 0, 3.0, 1.5, 0.04)
    before = call("curtain_wall_info", r["guid"])
    refused = json.loads(A.update_curtain_wall(r["guid"], json.dumps(changes)))
    assert refused["ok"] is False and refused["error"]
    assert call("curtain_wall_info", r["guid"]) == before


def test_update_curtain_wall_errors(project):
    assert json.loads(A.update_curtain_wall("no-such-guid", json.dumps({"height": 4.0})))["ok"] is False
    r = call("create_curtain_wall", project["level"], 0, 0, 6, 0, 3.0)
    assert json.loads(A.update_curtain_wall(r["guid"], "not json"))["ok"] is False
    assert json.loads(A.update_curtain_wall(r["guid"], json.dumps([])))["ok"] is False
    assert json.loads(A.update_curtain_wall(r["guid"], json.dumps({"height": "high"})))["ok"] is False


def test_slabs_tilt_and_return_flat(project):
    points = json.dumps([[0, 0], [4, 0], [4, 3], [0, 3]])
    guid = call("create_slab", project["level"], project["slab_type"], points)["guid"]
    base = ifcopenshell.util.placement.get_local_placement(b._model.by_guid(guid).ObjectPlacement)
    assert call("set_slab_slope", json.dumps([guid]), 0.1, 0.0)["ok"]
    tilted = ifcopenshell.util.placement.get_local_placement(b._model.by_guid(guid).ObjectPlacement)
    assert not math.isclose(float(tilted[0][2]), 0.0, abs_tol=1e-6)  # the placement gained a rotation
    assert call("slab_slope", guid)["slope_x"] == pytest.approx(0.1)
    assert call("set_slab_slope", json.dumps([guid]), 0.0, 0.0)["ok"]
    flat = ifcopenshell.util.placement.get_local_placement(b._model.by_guid(guid).ObjectPlacement)
    assert flat == pytest.approx(base, abs=1e-9)


def test_slab_edges_are_members_aggregated_to_the_slab(project):
    points = json.dumps([[0, 0], [4, 0], [4, 3], [0, 3]])
    slab = call("create_slab", project["level"], project["slab_type"], points)["guid"]
    r = call("add_slab_edge", slab, 0.02, 0.2)
    assert r["ok"] and len(r["edges"]) == 4, r
    members = [b._model.by_guid(g) for g in r["edges"]]
    assert all(m.is_a("IfcMember") for m in members)
    assert all(any(rel.RelatingObject.GlobalId == slab for rel in m.Decomposes) for m in members)
    assert all(ifcopenshell.util.element.get_pset(m, "KIMBIM_SlabEdge")["Slab"] == slab for m in members)

def test_update_curtain_wall_mullion_and_rail_sizes(project):
    r = call("create_curtain_wall", project["level"], 0, 0, 6, 0, 3.0, 1.5, 0.04)
    updated = json.loads(A.update_curtain_wall(r["guid"], json.dumps({
        "mullion_width": 0.10, "mullion_depth": 0.08, "rail_depth": 0.12})))
    assert updated["ok"], updated
    info = call("curtain_wall_info", r["guid"])
    assert info["mullion_width"] == pytest.approx(0.10)
    assert info["mullion_depth"] == pytest.approx(0.08)
    assert info["rail_depth"] == pytest.approx(0.12)
    mullions = [m for m in members(r["guid"]) if m.Name == "Curtain wall mullion"]
    verts = shape(mullions[0].GlobalId)
    assert (verts[:, 0].max() - verts[:, 0].min()) == pytest.approx(0.10, abs=1e-6)
    assert (verts[:, 1].max() - verts[:, 1].min()) == pytest.approx(0.08, abs=1e-6)
    rail = next(m for m in members(r["guid"]) if m.Name == "Curtain wall bottom rail")
    assert (shape(rail.GlobalId)[:, 2].max() - shape(rail.GlobalId)[:, 2].min()) == pytest.approx(0.12, abs=1e-6)


def _panel_solids(guid):
    wall = b._model.by_guid(guid)
    rep = ifcopenshell.util.representation.get_representation(wall, "Model", "Body", "MODEL_VIEW")
    return [e for e in b._model.traverse(rep) if e.is_a("IfcExtrudedAreaSolid")]


def test_a_curtain_wall_lists_its_bays(project):
    r = call("create_curtain_wall", project["level"], 0, 0, 6, 0, 3.0, 1.5, 0.04)
    info = call("curtain_wall_info", r["guid"])
    assert len(info["panels"]) == 4  # 6 m / 1.5 m
    assert [p["kind"] for p in info["panels"]] == ["glass"] * 4
    assert info["panels"][0]["from"] == 0.0 and info["panels"][-1]["to"] == pytest.approx(6.0)


def test_one_panel_can_be_solid_or_open(project):
    r = call("create_curtain_wall", project["level"], 0, 0, 6, 0, 3.0, 1.5, 0.04)
    assert json.loads(A.set_curtain_panel(r["guid"], 1, json.dumps({"kind": "solid", "thickness": 0.12})))["ok"]
    info = call("curtain_wall_info", r["guid"])
    assert info["panels"][1]["kind"] == "solid"
    assert info["panels"][1]["thickness"] == pytest.approx(0.12)
    assert info["panels"][1]["overridden"] is True
    assert len(_panel_solids(r["guid"])) == 4  # still one solid per closed bay

    assert json.loads(A.set_curtain_panel(r["guid"], 2, json.dumps({"kind": "open"})))["ok"]
    info = call("curtain_wall_info", r["guid"])
    assert info["panels"][2]["kind"] == "open"
    assert len(_panel_solids(r["guid"])) == 3  # the open bay has no panel

    assert json.loads(A.set_curtain_panel(r["guid"], 2, json.dumps({"kind": "glass"})))["ok"]
    assert len(_panel_solids(r["guid"])) == 4


def test_all_panels_open_is_still_a_valid_wall(project):
    r = call("create_curtain_wall", project["level"], 0, 0, 6, 0, 3.0, 1.5, 0.04)
    for index in range(4):
        assert json.loads(A.set_curtain_panel(r["guid"], index, json.dumps({"kind": "open"})))["ok"]
    assert _panel_solids(r["guid"]) == []
    assert b._model.by_guid(r["guid"]).Representation is not None
    assert len(members(r["guid"])) == 7


def test_curtain_panel_refuses_bad_bays(project):
    r = call("create_curtain_wall", project["level"], 0, 0, 6, 0, 3.0, 1.5, 0.04)
    for index, change in ((4, {"kind": "open"}), (-1, {"kind": "open"}),
                          (0, {"kind": "brick"}), (0, {"kind": "solid", "thickness": 2.0})):
        refused = json.loads(A.set_curtain_panel(r["guid"], index, json.dumps(change)))
        assert refused["ok"] is False and refused["error"], (index, change)
    assert call("curtain_wall_info", r["guid"])["panels"][0]["kind"] == "glass"


def test_curtain_panel_agent_tool_is_registered():
    from kimbim.agent import catalogue
    from kimbim.agent.tools import create  # noqa: F401

    assert "create.curtain_panel" in catalogue.TOOLS and catalogue.TOOLS["create.curtain_panel"].writes
    assert "create.curtain_wall_info" in catalogue.TOOLS
    assert not catalogue.TOOLS["create.curtain_wall_info"].writes
