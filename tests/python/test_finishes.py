# SPDX-License-Identifier: GPL-3.0-or-later
"""Room finishes (floor, skirting, wall), shafts through slabs and straight MEP runs."""
import json

import ifcopenshell.util.element
import ifcopenshell.util.placement
import pytest

from kimbim import app_bridge as b


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


@pytest.fixture
def room():
    """A 6 x 4 m box of walls with a room inside, on the first of two levels."""
    assert call("new_project", "Finishes")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    types = {t["name"]: t["guid"] for t in call("wall_types")["types"]}
    ext = types["Exterior 300"]
    walls, last = [], ""
    corners = [(0, 0), (6, 0), (6, 4), (0, 4)]
    for i in range(4):
        (x1, y1), (x2, y2) = corners[i], corners[(i + 1) % 4]
        walls.append(call("create_wall", l1, ext, x1, y1, x2, y2, 3.0, last, walls[0] if i == 3 else "")["guid"])
        last = walls[-1]
    r = call("create_room", l1, 3.0, 2.0, "Living")
    assert r["ok"], r
    return {"l1": l1, "room": r["guid"]}


def _covering(guid):
    e = b._model.by_guid(guid)
    return e, ifcopenshell.util.element.get_pset(e, "KIMBIM_Finish")


def test_floor_finish_covers_the_room_and_is_replaced_when_made_again(room):
    r = call("make_finish", room["room"], "floor", "0.03")
    assert r["ok"], r
    e, pset = _covering(r["guid"])
    assert e.is_a("IfcCovering") and e.PredefinedType == "FLOORING"
    assert pset["Room"] == room["room"] and pset["Kind"] == "floor" and abs(pset["Thickness"] - 0.03) < 1e-9
    again = call("make_finish", room["room"], "floor", "")
    assert again["ok"] and again["replaced"] == 1
    assert again["guid"] in again["geometry"]["changed"] and r["guid"] in again["geometry"]["removed"]
    assert len([c for c in b._model.by_type("IfcCovering") if c.PredefinedType == "FLOORING"]) == 1
    assert call("undo")["ok"]  # one step: the first finish is back
    assert b._model.by_guid(r["guid"]).is_a("IfcCovering")


def test_skirting_and_wall_finish_are_bands_inside_the_walls(room):
    skirting = call("make_finish", room["room"], "skirting", "0.015", "0.12")
    assert skirting["ok"], skirting
    e, pset = _covering(skirting["guid"])
    assert e.PredefinedType == "SKIRTINGBOARD" and abs(pset["Height"] - 0.12) < 1e-9
    solids = [x for x in b._model.traverse(e) if x.is_a("IfcArbitraryProfileDefWithVoids")]
    assert solids and len(solids[0].InnerCurves) == 1
    wall = call("make_finish", room["room"], "wall", "", "")
    assert wall["ok"], wall
    e, pset = _covering(wall["guid"])
    assert e.PredefinedType == "CLADDING" and pset["Height"] > 2.0  # up to the level above
    assert not call("make_finish", room["room"], "ceiling")["ok"]
    assert not call("make_finish", room["room"], "skirting", "5")["ok"]  # thicker than allowed


def test_finish_rooms_does_each_selected_room(room):
    r = call("finish_rooms", json.dumps([room["room"], "nope"]), "floor")
    assert r["ok"] and len(r["guids"]) == 1 and len(r["failed"]) == 1
    assert not call("finish_rooms", json.dumps([]), "floor")["ok"]


def test_shaft_cuts_every_slab_between_the_levels():
    assert call("new_project", "Shaft")["ok"]
    assert call("add_storey", "Level 2", 3.0)["ok"]
    storeys = sorted(call("storeys")["storeys"], key=lambda s: s["elevation"])
    assert len(storeys) >= 2
    slab_type = call("slab_types")["types"][0]["guid"]
    outline = json.dumps([[0, 0], [8, 0], [8, 6], [0, 6]])
    slabs = [call("create_slab", s["guid"], slab_type, outline, 0)["guid"] for s in storeys[:2]]
    hole = json.dumps([[2, 2], [3, 2], [3, 3.5], [2, 3.5]])
    r = call("create_shaft", hole, storeys[0]["guid"], storeys[1]["guid"])
    assert r["ok"], r
    assert sorted(r["slabs"]) == sorted(slabs) and len(r["openings"]) == 2
    for g in r["openings"]:
        opening = b._model.by_guid(g)
        assert opening.is_a("IfcOpeningElement")
        assert ifcopenshell.util.element.get_pset(opening, "KIMBIM_Shaft")["Shaft"] == r["shaft"]
    assert call("undo")["ok"]  # one step
    assert not any(o.is_a("IfcOpeningElement") and o.Name == "Shaft" for o in b._model.by_type("IfcOpeningElement"))
    far = json.dumps([[50, 50], [51, 50], [51, 51]])
    assert not call("create_shaft", far, storeys[0]["guid"], storeys[1]["guid"])["ok"]


@pytest.mark.parametrize("kind,ifc_class", [("duct", "IfcDuctSegment"), ("pipe", "IfcPipeSegment"),
                                            ("cable_tray", "IfcCableCarrierSegment")])
def test_mep_runs(kind, ifc_class):
    assert call("new_project", "MEP")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    r = call("create_mep_segment", l1, kind, 0, 0, 4, 3, 2.7, 0.4, 0.25)
    assert r["ok"], r
    assert abs(r["length"] - 5.0) < 1e-9
    e = b._model.by_guid(r["guid"])
    assert e.is_a(ifc_class)
    pset = ifcopenshell.util.element.get_pset(e, "KIMBIM_MEP")
    assert pset["Kind"] == kind and abs(pset["Elevation"] - 2.7) < 1e-9
    m = ifcopenshell.util.placement.get_local_placement(e.ObjectPlacement)
    assert abs(m[0][2] - 0.8) < 1e-6 and abs(m[1][2] - 0.6) < 1e-6  # runs along the line
    assert not call("create_mep_segment", l1, kind, 1, 1, 1, 1)["ok"]
    assert not call("create_mep_segment", l1, "sprinkler", 0, 0, 1, 0)["ok"]



def test_mep_run_has_elbows_and_a_system():
    assert call("new_project", "MEP run")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    r = call("create_mep_run", l1, "duct", json.dumps([[0, 0], [5, 0], [5, 4], [9, 4]]), 2.7, 0.4, 0.25, "Supply air")
    assert r["ok"], r
    assert len(r["segments"]) == 3 and len(r["fittings"]) == 2
    assert all(b._model.by_guid(g).is_a("IfcDuctFitting") for g in r["fittings"])
    systems = {s["name"]: s for s in call("mep_systems")["systems"]}
    assert systems["Supply air"]["count"] == 5
    assert json.loads(b.undo_history())["undo"][-1] == "Create mep run"  # one step
    assert call("undo")["ok"]
    assert not call("mep_systems")["systems"] or call("mep_systems")["systems"][0]["count"] == 0
    again = call("create_mep_run", l1, "pipe", json.dumps([[0, 0], [3, 0]]), 1.0, 0.05, 0.05)
    assert again["ok"] and again["system"] == "Pipe system" and again["fittings"] == []
