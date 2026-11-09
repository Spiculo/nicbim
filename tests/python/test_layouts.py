# SPDX-License-Identifier: GPL-3.0-or-later
"""Beam systems, interior elevations of a room and lintels over openings."""
import json

import ifcopenshell.util.element
import ifcopenshell.util.placement
import pytest

from kimbim import app_bridge as b
from kimbim import layouts


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


@pytest.fixture
def box():
    """A 6 x 4 m box of walls with a room inside."""
    assert call("new_project", "Layouts")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    ext = {t["name"]: t["guid"] for t in call("wall_types")["types"]}["Exterior 300"]
    walls, last = [], ""
    corners = [(0, 0), (6, 0), (6, 4), (0, 4)]
    for i in range(4):
        (x1, y1), (x2, y2) = corners[i], corners[(i + 1) % 4]
        walls.append(call("create_wall", l1, ext, x1, y1, x2, y2, 3.0, last, walls[0] if i == 3 else "")["guid"])
        last = walls[-1]
    room = call("create_room", l1, 3.0, 2.0, "Living")
    assert room["ok"], room
    return {"l1": l1, "walls": walls, "room": room["guid"]}


def test_beam_lines_are_spaced_and_clipped():
    lines = layouts.beam_lines([(0, 0), (6, 0), (6, 4), (0, 4)], 1.0, 0.0)
    assert [round(l[1], 6) for l in lines] == [0.5, 1.5, 2.5, 3.5]
    assert all(abs(l[0]) < 1e-9 and abs(l[2] - 6) < 1e-9 for l in lines)
    # an L-shaped outline splits nothing but shortens the lines in its notch
    ell = layouts.beam_lines([(0, 0), (6, 0), (6, 2), (2, 2), (2, 4), (0, 4)], 1.0, 0.0)
    assert len(ell) == 4 and abs(ell[-1][2] - 2) < 1e-9
    assert len(layouts.beam_lines([(0, 0), (6, 0), (6, 4), (0, 4)], 1.0, 90.0)) == 6


def test_beam_system_is_one_undo_step(box):
    beam_type = call("beam_types")["types"][0]["guid"]
    outline = json.dumps([[0, 0], [6, 0], [6, 4], [0, 4]])
    r = call("create_beam_system", box["l1"], beam_type, outline, "1.0", "0", "")
    assert r["ok"], r
    assert r["count"] == 4
    assert all(b._model.by_guid(g).is_a("IfcBeam") for g in r["guids"])
    assert json.loads(b.undo_history())["undo"][-1] == "Create beam system"
    assert call("undo")["ok"]
    assert not [e for e in b._model.by_type("IfcBeam") if e.GlobalId in r["guids"]]
    assert not call("create_beam_system", box["l1"], beam_type, outline, "0.01")["ok"]


def test_interior_elevations_one_per_wall(box):
    r = call("interior_elevations", box["room"], "0.5")
    assert r["ok"], r
    assert len(r["guids"]) == 4
    names = sorted(b._model.by_guid(g).Name for g in r["guids"])
    assert names[0].endswith("Interior A") and names[-1].endswith("Interior D")
    from kimbim import drawgen as G

    for g in r["guids"]:
        s = G.settings_of(b._model.by_guid(g))
        assert s["kind"] == "elevation" and abs(s["depth"] - 0.55) < 1e-9
    assert not call("interior_elevations", box["walls"][0])["ok"]


def test_lintels_over_doors(box):
    door_type = call("opening_types", "door")["types"][0]["guid"]
    door = call("insert_opening", "door", box["walls"][0], door_type, 3.0, 0.9, 2.1, 0.0)
    assert door["ok"], door
    r = call("add_lintels", json.dumps([door["guid"]]), "0.15", "0.2")
    assert r["ok"], r
    lintel = b._model.by_guid(r["guids"][0])
    assert lintel.is_a("IfcBeam") and lintel.PredefinedType == "LINTEL"
    m = ifcopenshell.util.placement.get_local_placement(lintel.ObjectPlacement)
    from kimbim import authoring

    assert abs(m[2][3] * authoring._scale() - 2.1) < 0.02  # on the door's head (placement in model units)
    assert not call("add_lintels", json.dumps([door["guid"]]))["ok"]  # it has one already




def test_kerb_and_planting_area(box):
    kerb = call("create_kerb", box["l1"], json.dumps([[0, -2], [6, -2], [6, -5]]), "0.15", "0.12")
    assert kerb["ok"], kerb
    e = b._model.by_guid(kerb["guid"])
    assert e.is_a("IfcCivilElement")
    solids = [x for x in b._model.traverse(e) if x.is_a("IfcExtrudedAreaSolid")]
    assert len(solids) == 2  # one box per segment
    assert ifcopenshell.util.element.get_pset(e, "KIMBIM_Site")["Kind"] == "kerb"
    bed = call("create_planting_area", box["l1"], json.dumps([[8, 0], [10, 0], [10, 3], [8, 3]]), "0.4", "Lavender")
    assert bed["ok"], bed
    e = b._model.by_guid(bed["guid"])
    assert e.is_a("IfcGeographicElement")
    assert ifcopenshell.util.element.get_pset(e, "KIMBIM_Site")["Planting"] == "Lavender"
    assert not call("create_kerb", box["l1"], json.dumps([[0, 0]]))["ok"]
    assert not call("create_planting_area", box["l1"], json.dumps([[0, 0], [1, 1]]))["ok"]


def test_handrail_on_a_wall_face(box):
    r = call("wall_handrail", box["walls"][0], "left", "0.9")
    assert r["ok"], r
    rail = b._model.by_guid(r["guid"])
    assert rail.is_a("IfcRailing") and rail.PredefinedType == "HANDRAIL"
    assert abs(r["length"] - 5.8) < 1e-6  # 6 m wall, 10 cm short of each end
    from kimbim import authoring

    m = ifcopenshell.util.placement.get_local_placement(rail.ObjectPlacement)
    assert abs(m[2][3] * authoring._scale() - 0.9) < 1e-6
    assert not call("wall_handrail", box["walls"][0], "up")["ok"]
    assert not call("wall_handrail", box["room"])["ok"]


def test_sills_and_reveals(box):
    window_type = call("opening_types", "window")["types"][0]["guid"]
    window = call("insert_opening", "window", box["walls"][0], window_type, 3.0, 1.2, 1.2, 0.9)
    assert window["ok"], window
    sill = call("add_sills", json.dumps([window["guid"]]))
    assert sill["ok"], sill
    e = b._model.by_guid(sill["guids"][0])
    assert e.is_a("IfcCovering") and e.PredefinedType == "MOLDING"
    from kimbim import authoring

    m = ifcopenshell.util.placement.get_local_placement(e.ObjectPlacement)
    assert abs(m[2][3] * authoring._scale() - (0.9 - 0.03)) < 0.02  # under the window's bottom
    assert not call("add_sills", json.dumps([window["guid"]]))["ok"]  # it has one
    reveals = call("add_reveals", json.dumps([window["guid"]]), "0.02")
    assert reveals["ok"] and len(reveals["guids"]) == 3  # two jambs and the head
    assert call("undo")["ok"]
    assert not [g for g in reveals["guids"] if _exists(g)]


def _exists(guid):
    try:
        b._model.by_guid(guid)
        return True
    except RuntimeError:
        return False


def test_road_markings():
    from kimbim import layouts as L

    dashed = L._strips([(0, 0), (10, 0)], "dashed", 0.12, 3.0, 3.0)
    assert [round(l, 6) for _c, _d, l, _o in dashed] == [3.0, 3.0]  # 0-3 and 6-9
    double = L._strips([(0, 0), (10, 0)], "double", 0.12, 3.0, 3.0)
    assert len(double) == 2 and {o for *_x, o in double} == {-0.12, 0.12}
    corner = L._strips([(0, 0), (4, 0), (4, 4)], "dashed", 0.1, 3.0, 3.0)  # 0-3, then 6-8 round the corner
    assert [round(l, 6) for _c, _d, l, _o in corner] == [3.0, 2.0]
    assert call("new_project", "Road")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    r = call("create_road_marking", l1, json.dumps([[0, 0], [30, 0]]), "dashed")
    assert r["ok"] and r["strips"] == 5, r
    assert b._model.by_guid(r["guid"]).ObjectType == "Road marking"
    assert not call("create_road_marking", l1, json.dumps([[0, 0], [1, 0]]), "zigzag")["ok"]
