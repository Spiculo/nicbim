# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent tools for drawings, sheets, schedule definitions, wall settings, underlays and saved views
(doc 18 §6: the operations that had no tool)."""
import json
import sys
from pathlib import Path

import pytest

from kimbim import app_bridge as B
from kimbim import configure as CF
from kimbim import documents as D
from kimbim import kimfile as K
from kimbim import layers as LY
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
    out = json.loads(D.import_ifc(str(ifc), str(tmp_path / "house.kim")))
    assert out["ok"]
    D.close_document()
    session = Session.open(str(tmp_path / "house.kim"))
    assert json.loads(S.set_project_settings(json.dumps({"agent_changes": "direct"})))["ok"]
    yield session
    session.close()


def run(s, tool_name, **args):
    return call_tool(s, tool_name, args, client="test")


def ok(s, tool_name, **args):
    r = run(s, tool_name, **args)
    assert r["ok"], r
    return r["result"]


def _walls(s):
    return [i["guid"] for i in ok(s, "elements.find", elements={"kind": "wall"})["items"]]


# ---------------------------------------------------------------- drawings

def test_drawing_rename_view_and_delete(s):
    section = ok(s, "drawings.create", kind="section", line=[[0, 0], [5, 0]])["guid"]
    ok(s, "drawings.rename", drawing=section, name="Section A")
    assert any(d["name"] == "Section A" for d in ok(s, "drawings.list")["drawings"])
    guid = ok(s, "drawings.set_view", drawing="Section A", depth=4, tilt=10, base=1.2, crop=[10, 10, 200, 150])["guid"]
    assert run(s, "drawings.set_view", drawing=guid)["error"]["code"] == "bad_input"
    assert run(s, "drawings.set_view", drawing=guid, tilt=89.5)["error"]["code"] == "bad_input"
    assert run(s, "drawings.rename", drawing=guid, name="  ")["error"]["code"] == "bridge_error"
    sheet = ok(s, "sheets.create", title="Sections")["number"]
    ok(s, "sheets.place_drawing", sheet=sheet, drawing=guid)
    ok(s, "drawings.delete", drawing=guid)
    assert all(d["guid"] != guid for d in ok(s, "drawings.list")["drawings"])
    assert not ok(s, "sheets.get", sheet=sheet)["views"]  # taken off the sheet too
    assert run(s, "drawings.delete", drawing=guid)["error"]["code"] == "not_found"


# ---------------------------------------------------------------- sheets

def test_sheet_data_title_block_and_purpose(s):
    number = ok(s, "sheets.create", title="Plans")["number"]
    assert any(p["name"] == "A3" for p in ok(s, "sheets.papers")["papers"])
    assert ok(s, "sheets.update", sheet=number, title="Ground floor", number="P01", paper="A3")["sheet"] == "P01"
    got = ok(s, "sheets.get", sheet="P01")
    assert (got["title"], got["paper"]) == ("Ground floor", "A3")
    assert run(s, "sheets.update", sheet="P01")["error"]["code"] == "bad_input"
    ok(s, "sheets.set_title_block", sheet="P01", fields={"issued": "For permit"}, at=[200, 240])
    block = ok(s, "sheets.get", sheet="P01")["title_block"]
    assert "For permit" in json.dumps(block)
    assert run(s, "sheets.set_title_block", sheet="P01", fields={"Drawn by": "FL"})["error"]["code"] == "bad_input"
    purposes = ok(s, "graphics.state")
    name = next(iter(purposes.get("purposes") or []), None)
    if isinstance(name, dict):
        name = name.get("name")
    if name:
        assert ok(s, "sheets.set_purpose", sheet="P01", purpose=name)["purpose"] == name
    assert run(s, "sheets.set_purpose", sheet="P01", purpose="No such purpose")["error"]["code"] == "bridge_error"
    ok(s, "sheets.delete", sheet="P01")
    assert all(x["number"] != "P01" for x in ok(s, "sheets.list")["sheets"])


def test_sheet_symbols_legend_and_schedule(s):
    plan = ok(s, "drawings.create", kind="plan", level="Level 1")["guid"]
    number = ok(s, "sheets.create", title="Plan")["number"]
    ok(s, "sheets.place_drawing", sheet=number, drawing=plan)
    north = ok(s, "sheets.place_symbol", sheet=number, kind="north")["id"]
    ok(s, "sheets.place_symbol", sheet=number, kind="scalebar", drawing=plan)
    ok(s, "sheets.place_symbol", sheet=number, kind="text", text="Preliminary", size=5, at=[30, 30])
    assert run(s, "sheets.place_symbol", sheet=number, kind="text")["error"]["code"] == "bridge_error"  # no text
    legend = ok(s, "sheets.place_legend", sheet=number)["id"]
    index = ok(s, "sheets.place_schedule", sheet=number, schedule="doors", width=150)["index"]
    got = ok(s, "sheets.get", sheet=number)
    assert {x["kind"] for x in got["symbols"]} == {"north", "scalebar", "text"}
    assert [x["id"] for x in got["legends"]] == [legend] and len(got["schedules"]) == 1
    ok(s, "sheets.remove_item", sheet=number, item="symbol", id=north)
    ok(s, "sheets.remove_item", sheet=number, item="legend", id=legend)
    ok(s, "sheets.remove_item", sheet=number, item="schedule", index=index)
    got = ok(s, "sheets.get", sheet=number)
    assert len(got["symbols"]) == 2 and not got["legends"] and not got["schedules"]
    assert run(s, "sheets.remove_item", sheet=number, item="schedule")["error"]["code"] == "bad_input"


# ---------------------------------------------------------------- schedule definitions

def test_schedule_definition_save_and_delete(s):
    fields = ok(s, "schedules.fields", classes=["IfcDoor"])
    assert fields  # attributes, quantities and properties for doors
    sid = ok(s, "schedules.save", name="Door sizes", classes=["IfcDoor"], unit="mm",
             fields=[{"source": "info", "name": "type"}, {"source": "quantity", "name": "width"},
                     {"source": "quantity", "name": "height", "label": "H"}],
             group_by=["info:type"])["id"]
    assert any(x["id"] == sid for x in ok(s, "schedules.list")["schedules"])
    rows = ok(s, "schedules.get", schedule="Door sizes")
    assert rows["count"] == 2
    assert run(s, "schedules.save", name="Bad", classes=["IfcDoor"],
               fields=[{"source": "quantity", "name": "nope"}])["error"]["code"] == "bridge_error"
    ok(s, "schedules.delete", schedule=sid)
    assert all(x["id"] != sid for x in ok(s, "schedules.list")["schedules"])


# ---------------------------------------------------------------- walls

def test_wall_options_configure_flip_and_junctions(s):
    o = ok(s, "walls.options")
    assert "Centre" in o["reference_lines"] and "Level above" in o["top_links"]
    walls = _walls(s)
    r = ok(s, "walls.configure", elements=walls[:1], reference_line="Centre", slant=80)
    assert r["changed"] >= 1 and walls[0] in r["guids"]
    wall = B._model.by_guid(walls[0])
    assert CF.reference_of(wall) == "Centre" and abs(CF.slant_of(wall) - 80) < 1e-6
    assert run(s, "walls.configure", elements=walls[:1])["error"]["code"] == "bad_input"
    assert run(s, "walls.configure", elements=walls[:1], slant=20)["error"]["code"] == "bad_input"  # < 45
    assert run(s, "walls.configure", elements=walls[:1], profile="Nope")["error"]["code"] == "bridge_error"
    assert ok(s, "walls.flip", elements=walls[:2])["changed"] == 2
    assert ok(s, "walls.set_junctions", elements=walls[:1], mode="through")["joins"] >= 1
    assert run(s, "walls.set_junctions", elements=walls[:1], mode="sideways")["error"]["code"] == "bad_input"


def test_wall_profile_from_a_drawn_shape(s):
    level = ok(s, "levels.list")["levels"][0]["name"]
    rect = ok(s, "draft.add", level=level, kind="rectangle", points=[[0, 0], [0.3, 2.5]])
    guid = rect.get("guid") or rect["guids"][0]
    assert ok(s, "walls.save_profile", shape=guid, name="Parapet")["name"] == "Parapet"
    assert "Parapet" in ok(s, "walls.options")["profiles"]
    walls = _walls(s)
    ok(s, "walls.configure", elements=walls[:1], profile="Parapet")
    assert CF.profile_of(B._model.by_guid(walls[0])) == "Parapet"
    ok(s, "walls.configure", elements=walls[:1], profile=CF.NO_PROFILE)
    assert not CF.profile_of(B._model.by_guid(walls[0]))


def test_surface_override(s):
    walls = _walls(s)
    assert run(s, "elements.set_surface", elements=walls[:1], side="Top",
               surface="")["error"]["code"] == "bridge_error"  # a wall has no Top
    assert run(s, "elements.set_surface", elements=walls[:1], side="Edges",
               surface="No such surface")["error"]["code"] == "bridge_error"
    assert ok(s, "elements.set_surface", elements=walls[:1], side="Edges", surface="")["changed"] == 1


# ---------------------------------------------------------------- underlays and saved views

def test_underlay_add_update_convert_remove(s, tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 0  # unitless: the tool must be told
    doc.modelspace().add_line((0, 0), (1000, 0))
    doc.modelspace().add_line((1000, 0), (1000, 500))
    path = tmp_path / "survey.dxf"
    doc.saveas(path)
    assert run(s, "underlays.add", path=str(path), level="Level 1")["error"]["code"] == "bridge_error"
    u = ok(s, "underlays.add", path=str(path), level="Level 1", units="mm", at=[2, 3], opacity=0.4)["underlay"]
    assert abs(u["scale"] - 0.001) < 1e-12 and (u["x"], u["y"]) == (2.0, 3.0)
    assert [x["id"] for x in ok(s, "underlays.list", level="Level 1")["underlays"]] == [u["id"]]
    assert not ok(s, "underlays.list", level="Level 2")["underlays"]
    changed = ok(s, "underlays.update", id=u["id"], show_3d=True, tint="#ff0000", rotation=15)["underlay"]
    assert changed["show_3d"] and changed["tint"] == "#ff0000"
    assert run(s, "underlays.update", id=u["id"])["error"]["code"] == "bad_input"
    lines = ok(s, "underlays.convert", id=u["id"])
    assert lines["count"] == 2
    ok(s, "underlays.remove", id=u["id"])
    assert not ok(s, "underlays.list")["underlays"]
    assert run(s, "underlays.remove", id=u["id"])["error"]["code"] == "bridge_error"


def test_saved_views_list_and_delete(s):
    assert json.loads(LY.save_view("North corner", json.dumps({"camera": {"eye": [1, 2, 3]}})))["ok"]
    views = ok(s, "views.list")["views"]
    assert [v["name"] for v in views] == ["North corner"]
    ok(s, "views.delete", name="North corner")
    assert not ok(s, "views.list")["views"]
    assert run(s, "views.delete", name="North corner")["error"]["code"] == "bridge_error"


def test_dwg_export_without_a_converter(s, tmp_path, monkeypatch):
    from kimbim import dwg

    monkeypatch.setattr(dwg, "from_dxf_tool", lambda: None)
    plan = ok(s, "drawings.create", kind="plan", level="Level 1")["guid"]
    r = run(s, "drawings.export", drawing=plan, format="dwg", out=str(tmp_path / "p.dwg"))
    assert r["error"]["code"] == "bridge_error"
    number = ok(s, "sheets.create", title="P")["number"]
    r = run(s, "sheets.export", sheet=number, format="dwg", out=str(tmp_path / "s.dwg"))
    assert r["error"]["code"] == "bridge_error"


def test_dwg_export_with_a_converter(s, tmp_path):
    from kimbim import dwg

    if dwg.from_dxf_tool() is None:
        pytest.skip("no DWG converter (pixi install -e dwg, then KIMBIM_DWG_BIN)")
    plan = ok(s, "drawings.create", kind="plan", level="Level 1")["guid"]
    out = tmp_path / "plan.dwg"
    ok(s, "drawings.export", drawing=plan, format="dwg", out=str(out))
    assert out.read_bytes()[:4] == b"AC10"  # a DWG file's version magic
    number = ok(s, "sheets.create", title="P")["number"]
    ok(s, "sheets.place_drawing", sheet=number, drawing=plan)
    sheet = tmp_path / "sheet.dwg"
    ok(s, "sheets.export", sheet=number, format="dwg", out=str(sheet))
    assert sheet.read_bytes()[:4] == b"AC10"
