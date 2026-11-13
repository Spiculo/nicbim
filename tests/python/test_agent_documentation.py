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
    from kimbim import graphics

    names = list(graphics.effective("purposes"))
    assert names, "a project comes with purposes"
    assert ok(s, "sheets.set_purpose", sheet="P01", purpose=names[0])["purpose"] == names[0]
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
    assert "width" in json.dumps(fields) and "Name" in json.dumps(fields)  # quantities and attributes
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


def test_views_save_offline_and_view_needs_app(s):
    ok(s, "views.save", name="Cutaway", level="Level 1", plan=False, hidden_layers=["Furniture"], white_model=True,
       cut_planes=[{"point": [0, 0, 1.5], "normal": [0, 0, 1], "name": "Roof off"}])
    view = next(v for v in ok(s, "views.list")["views"] if v["name"] == "Cutaway")
    plane = view["data"]["planes"][0]
    assert plane["name"] == "Roof off" and plane["point"] == [0, 0, 1.5] and view["data"]["whiteModel"] is True
    assert run(s, "views.save", name="Bad", cut_planes=[{"point": [0, 0, 0], "normal": [0, 0, 0]}]
               )["error"]["code"] == "bad_input"
    for name, args in (("views.apply", {"name": "Cutaway"}), ("view.show_all", {}), ("view.zoom", {}),
                       ("views.save", {"name": "Now", "capture": True})):
        assert run(s, name, **args)["error"]["code"] == "needs_app", name


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


# ---------------------------------------------------------------- placed drawings, pictures, paths, worksheets

def _png(path):
    import struct
    import zlib

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + b"\xff\x00\x00" * 4 for _ in range(2))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 2, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


def test_placed_drawing_symbol_picture_and_background(s, tmp_path):
    plan = ok(s, "drawings.create", kind="plan", level="Level 1")["guid"]
    number = ok(s, "sheets.create", title="Plan")["number"]
    ok(s, "sheets.place_drawing", sheet=number, drawing=plan, scale=100)
    ok(s, "sheets.set_drawing", sheet=number, drawing=plan, at=[40, 30], scale=50)
    view = ok(s, "sheets.get", sheet=number)["views"][0]
    assert (view["x"], view["y"], view["scale"]) == (40, 30, 50)
    assert run(s, "sheets.set_drawing", sheet=number, drawing=plan)["error"]["code"] == "bad_input"
    cloud = ok(s, "sheets.place_symbol", sheet=number, kind="cloud", text="Rev A")["id"]
    ok(s, "sheets.set_symbol", sheet=number, id=cloud, at=[100, 100], text="Rev B", width=80)
    sym = next(x for x in ok(s, "sheets.get", sheet=number)["symbols"] if x["id"] == cloud)
    assert (sym["x"], sym["y"], sym["text"], sym["w"]) == (100, 100, "Rev B", 80)
    pic = ok(s, "sheets.place_picture", sheet=number, path=str(_png(tmp_path / "logo.png")), width=40)["id"]
    assert any(x["id"] == pic and x["kind"] == "image" for x in ok(s, "sheets.get", sheet=number)["symbols"])
    ok(s, "sheets.update", sheet=number, background="#fffbe6")
    assert run(s, "sheets.update", sheet=number, background="yellow")["error"]["code"] == "bridge_error"
    ok(s, "sheets.remove_drawing", sheet=number, drawing=plan)
    assert not ok(s, "sheets.get", sheet=number)["views"]
    assert any(d["guid"] == plan for d in ok(s, "drawings.list")["drawings"])  # the drawing stays


def test_section_path_bend_and_curve(s):
    section = ok(s, "drawings.create", kind="section", line=[[0, 0], [6, 0]])["guid"]
    guid = ok(s, "drawings.set_path", drawing=section, points=[[0, 0], [3, 0], [3, 4]])["guid"]
    guid = ok(s, "drawings.set_path", drawing=guid, points=[[0, 0], [6, 0]], bulges=[0.3])["guid"]
    assert any(d["guid"] == guid for d in ok(s, "drawings.list")["drawings"])
    assert run(s, "drawings.set_path", drawing=guid, points=[[0, 0], [6, 0]],
               bulges=[0, 1])["error"]["code"] == "bad_input"
    assert run(s, "drawings.set_path", drawing=guid, points=[[0, 0]])["error"]["code"] == "bad_input"


def test_worksheets_and_splines(s):
    w = ok(s, "worksheets.create", name="Details")
    assert [x["name"] for x in ok(s, "worksheets.list")["worksheets"]] == ["Details"]
    spline = ok(s, "draft.add", level="Details", kind="spline", points=[[0, 0], [1, 1], [2, 0], [3, 1]])
    assert spline["guids"]
    ok(s, "worksheets.rename", worksheet=w["guid"], name="Wall details")
    assert run(s, "worksheets.create", name="Wall details")["error"]["code"] == "bridge_error"
    ok(s, "worksheets.delete", worksheet="Wall details")
    assert not ok(s, "worksheets.list")["worksheets"]


# ---------------------------------------------------------------- objects: gravity and drafts

def test_object_draft_check_save_and_place(s):
    draft = json.loads((ROOT / "python" / "kimbim" / "bundled_objects" / "base_cabinets.kimobj").read_text(
        encoding="utf-8"))
    draft["id"], draft["name"] = "agent_cabinet", "Agent cabinet"
    assert ok(s, "objects.check_draft", draft=draft) == {"ok": True, "errors": []}
    bad = {**draft, "parameters": "nope"}
    checked = ok(s, "objects.check_draft", draft=bad)
    assert not checked["ok"] and checked["errors"]
    assert run(s, "objects.save_draft", draft=bad)["error"]["code"] == "bad_input"
    ref = ok(s, "objects.save_draft", draft=draft)["ref"]
    assert run(s, "objects.save_draft", draft=draft)["error"]["code"] == "bad_input"  # exists
    assert ok(s, "objects.save_draft", draft=draft, replace=True)["ref"] == ref
    library = json.dumps(ok(s, "objects.library"))
    assert "agent_cabinet" in library or ref in library
    import ifcopenshell.util.placement

    def z(guid):
        import ifcopenshell.util.unit

        scale = ifcopenshell.util.unit.calculate_unit_scale(B._model)  # model units (mm) to metres
        return float(ifcopenshell.util.placement.get_local_placement(B._model.by_guid(guid).ObjectPlacement)[2][3]) * scale

    # a podium 0.5 m above Level 1, away from the house (whose ground slab is flush with the level)
    ok(s, "create.slab", level="Level 1", points=[[20, 20], [23, 20], [23, 23], [20, 23]], offset=0.5)
    floor = ok(s, "objects.place", object=ref, level="Level 1", at=[21, 21])["guids"][0]
    on_slab = ok(s, "objects.place", object=ref, level="Level 1", at=[21, 21], gravity=True)["guids"][0]
    assert abs(z(on_slab) - z(floor) - 0.5) < 0.01  # it stands on the podium's top, not on the level


def test_measure_points(s):
    r = ok(s, "measure.points", points=[[0, 0], [3, 0], [3, 4]])
    assert r["segments"] == [3, 4] and r["length"] == 7 and r["distance"] == 5
    sq = ok(s, "measure.points", points=[[0, 0], [2, 0], [2, 2], [0, 2]], closed=True)
    assert sq["area"] == 4 and sq["perimeter"] == 8
    assert ok(s, "measure.points", points=[[0, 0, 0], ["300cm", 0, "4m"]])["distance"] == 5
    assert run(s, "measure.points", points=[[0, 0]])["error"]["code"] == "bad_input"
    assert run(s, "measure.points", points=[[0, 0], [1, 1]], closed=True)["error"]["code"] == "bad_input"


# ---------------------------------------------------------------- D250: the rest of doc 18 §6

def test_views_save_keeps_a_section_box(s):
    ok(s, "views.save", name="Boxed", plan=False, section_box={"min": [0, 0, 0], "max": [4, 3, 2.5]})
    planes = next(v for v in ok(s, "views.list")["views"] if v["name"] == "Boxed")["data"]["planes"]
    assert [p["name"] for p in planes] == [f"Section box: {a} {e}" for a in "XYZ" for e in ("min", "max")]
    x_max = planes[1]
    assert x_max["point"] == [4, 0, 0] and x_max["normal"] == [-1, 0, 0] and x_max["kind"] == "vertical"
    assert planes[4]["normal"] == [0, 0, 1] and planes[5]["point"] == [0, 0, 2.5]
    bad = run(s, "views.save", name="Flat", section_box={"min": [0, 0, 0], "max": [4, 0, 2]})
    assert bad["error"]["code"] == "bad_input"


def test_live_only_view_tools_need_the_app(s):
    for name, args in (("view.style", {"white_model": True}), ("view.camera", {"eye": [0, -10, 2], "target": [0, 0, 1]}),
                       ("view.trace", {"mode": "below"}), ("view.section_box", {"off": True})):
        assert run(s, name, **args)["error"]["code"] == "needs_app", name
    assert run(s, "view.style")["error"]["code"] == "bad_input"
    assert run(s, "view.section_box", off=True, box={"min": [0, 0, 0], "max": [1, 1, 1]})["error"]["code"] == "bad_input"
    assert run(s, "view.camera", eye=[1, 1, 1], target=[1, 1, 1])["error"]["code"] == "bad_input"


def _a_wall_face(s):
    import math

    level = next(lv for lv in ok(s, "levels.list")["levels"] if lv["name"] == "Level 1")
    walls = json.loads(B.snap_data(level["guid"]))["walls"]
    w = max(walls, key=lambda w: math.hypot(w["x2"] - w["x1"], w["y2"] - w["y1"]))
    length = math.hypot(w["x2"] - w["x1"], w["y2"] - w["y1"])
    along = ((w["x2"] - w["x1"]) / length, (w["y2"] - w["y1"]) / length)
    left = (-along[1], along[0])
    off = w["centre"] + w["thickness"] / 2
    mid = ((w["x1"] + w["x2"]) / 2 + left[0] * off, (w["y1"] + w["y2"]) / 2 + left[1] * off)
    return level, w, along, left, mid


def test_place_fitted_to_a_wall(s):
    import math

    level, wall, along, left, mid = _a_wall_face(s)
    obj = next(o for o in ok(s, "objects.library")["objects"] if o["category"] and o["width_m"] and o["depth_m"])
    at = [mid[0] + left[0] * 0.3, mid[1] + left[1] * 0.3]  # 30 cm in front of the face
    r = ok(s, "objects.place", object=obj["id"], level=level["guid"], at=at, fit_to_walls=True)
    fit = r["fitted"]
    assert fit and fit["wall"] == wall["guid"]
    width, depth = obj["width_m"], obj["depth_m"]
    ux, uy = (-along[0], -along[1]), (-left[0], -left[1])  # the back towards the wall
    expect = [mid[0] - ux[0] * width / 2 - uy[0] * depth, mid[1] - ux[1] * width / 2 - uy[1] * depth]
    assert fit["origin_m"] == pytest.approx(expect, abs=1e-6)
    assert math.radians(fit["angle_deg"]) == pytest.approx(math.atan2(ux[1], ux[0]), abs=1e-9)
    far = ok(s, "objects.place", object=obj["id"], level=level["guid"], at=[mid[0] + left[0] * 5, mid[1] + left[1] * 5],
             fit_to_walls=True)
    assert far["fitted"] is None  # nothing in reach: placed where asked


def test_place_a_picture_in_3d(s, tmp_path):
    level = ok(s, "levels.list")["levels"][0]
    picture = _png(tmp_path / "person.png")  # 4 x 2 pixels
    r = ok(s, "objects.place_picture", path=str(picture), level=level["guid"], at=[1, 2], width=1.2, angle=90,
           elevation=0.1)
    e = B._model.by_guid(r["guids"][0])
    assert e.is_a("IfcBuildingElementProxy") and e.Name.startswith("Picture: person")
    assert run(s, "objects.place_picture", path=str(tmp_path / "nope.txt"), level=level["guid"], at=[0, 0],
               width=1)["error"]["code"] == "bridge_error"
