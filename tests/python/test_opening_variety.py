# SPDX-License-Identifier: GPL-3.0-or-later
"""D97: Archicad's door and window variety: double, sliding and multi-panel types."""
import json
import re

import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.validate

from kimbim import app_bridge as b


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def test_double_and_sliding_doors_and_panel_windows():
    assert call("new_project", "Doors")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    wt = next(t for t in call("wall_types")["types"] if t["name"] == "Exterior 300")["guid"]
    w = call("create_wall", level, wt, 0, 0, 12, 0, 3.0, "", "", "Outside face")["guid"]
    doors = {t["name"]: t for t in call("opening_types", "door")["types"]}
    windows = {t["name"]: t for t in call("opening_types", "window")["types"]}
    assert {"Double door 1600x2100", "Sliding door 1800x2100", "Double sliding door 2400x2100"} <= set(doors)
    assert {"Window 2400x1200, two panels", "Window 3000x1500, three panels"} <= set(windows)
    placed = {}
    for name, along in (("Double door 1600x2100", 1.5), ("Sliding door 1800x2100", 4.0)):
        d = doors[name]
        r = call("insert_opening", "door", w, d["guid"], along, d["width"], d["height"], d["sill"])
        assert r["ok"], r
        placed[name] = r["guid"]
    win = windows["Window 3000x1500, three panels"]
    r = call("insert_opening", "window", w, win["guid"], 8.5, win["width"], win["height"], win["sill"])
    assert r["ok"], r
    plan = next(d for d in call("drawings")["drawings"] if d["kind"] == "plan")
    svg = call("generate_drawing", plan["guid"], "")["svg"]

    swings = re.findall(r'<g data-kind="swing">(.*?)</g>', svg, re.S)
    assert "".join(swings).count('class="swing"') == 2  # the double door's two arcs; the sliding door has none
    assert sum(g.count("<path") for g in swings) == 2 + 2 + 2  # two leaves and arcs, two sliding panels


def test_a_storefront_type_and_a_skylight():
    """D209: a glazed storefront window type and a horizontal skylight filling a slab opening."""
    assert call("new_project", "Skylight")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    windows = {t["name"]: t for t in call("opening_types", "window")["types"]}
    assert "Storefront 3600x2700" in windows

    wt = next(t for t in call("wall_types")["types"] if t["name"] == "Exterior 300")["guid"]
    wall = call("create_wall", level, wt, 0, 0, 12, 0, 3.0, "", "")["guid"]
    sf = windows["Storefront 3600x2700"]
    r = call("insert_opening", "window", wall, sf["guid"], 3.0, sf["width"], sf["height"], sf["sill"])
    assert r["ok"], r

    slab_type = call("slab_types")["types"][0]["guid"]
    slab = call("create_slab", level, slab_type, json.dumps([[0, 0], [8, 0], [8, 6], [0, 6]]), 0.0)["guid"]
    sky = call("create_skylight", slab, 2.0, 2.0, 1.2, 1.2, "")
    assert sky["ok"], sky
    window = b._model.by_guid(sky["guid"])
    opening = b._model.by_guid(sky["opening"])
    assert window.is_a("IfcWindow") and opening.is_a("IfcOpeningElement")
    assert window.FillsVoids[0].RelatingOpeningElement == opening
    assert opening.VoidsElements[0].RelatingBuildingElement == b._model.by_guid(slab)
    matrix = ifcopenshell.util.placement.get_local_placement(window.ObjectPlacement)
    assert abs(float(matrix[1][2]) + 1.0) < 1e-9  # local Z (the window's height) lies along -Y
    assert not call("create_skylight", wall, 0, 0, 1, 1)["ok"]
    assert not call("create_skylight", slab, 0, 0, 0, 1)["ok"]
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(b._model, logger, express_rules=True)
    assert [s for s in logger.statements if s["level"] == "error"] == []
