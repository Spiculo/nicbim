# SPDX-License-Identifier: GPL-3.0-or-later
"""D98: Archicad's Automatic Dimensioning of walls and their openings."""
import json

import pytest

from kimbim import app_bridge as b


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


@pytest.fixture
def project():
    assert call("new_project", "Dims")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    types = {t["name"]: t["guid"] for t in call("wall_types")["types"]}
    return {"level": level, **types}


def test_automatic_wall_dimensions(project):
    """D98: Archicad's Automatic Dimensioning: the wall's ends and its doors' edges, outside its face."""
    t = project["Exterior 300"]
    w = call("create_wall", project["level"], t, 0, 0, 6, 0, 3.0, "", "", "Outside face")["guid"]
    door = call("opening_types", "door")["types"][0]
    assert call("insert_opening", "door", w, door["guid"], 2.0, 1.0, door["height"], door["sill"])["ok"]
    r = call("auto_dimension", json.dumps([w]), 0.8)
    assert r["ok"] and len(r["guids"]) == 1, r
    dim = next(a for a in call("annotations", project["level"])["annotations"] if a["guid"] == r["guids"][0])
    assert dim["kind"] == "dimension"
    xs = [round(p[0], 6) for p in dim["points"][:-1]]
    assert xs == [0.0, 1.5, 2.5, 6.0]
    assert {round(p[1], 6) for p in dim["points"][:-1]} == {0.0}  # on the outside face (the drawn line)
    assert dim["points"][-1][1] == pytest.approx(-0.8)  # outside it, away from the body (y 0 to 0.3)
    assert dim["text"].split() == ["1.50", "1.00", "3.50"]
    assert not call("auto_dimension", json.dumps([]), 0.8)["ok"]


def test_overall_dimension_spans_the_selection(project):
    """D158: one dimension across the combined bounds, on X, Y or the longer side."""
    t = project["Exterior 300"]
    pts = [(0, 0), (8, 0), (8, 6), (0, 6)]
    walls, last = [], ""
    for i in range(4):
        (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % 4]
        end = walls[0] if i == 3 else ""
        r = call("create_wall", project["level"], t, x1, y1, x2, y2, 3.0, last, end)
        assert r["ok"], r
        walls.append(r["guid"])
        last = r["guid"]
    r = call("overall_dimension", json.dumps(walls), 0.8, "x")
    assert r["ok"] and r["axis"] == "x", r
    dim = next(a for a in call("annotations", project["level"])["annotations"] if a["guid"] == r["guid"])
    assert dim["kind"] == "dimension"
    start, end, through = dim["points"]
    assert start[1] == pytest.approx(end[1])
    assert through[0] == pytest.approx(start[0])
    assert through[1] == pytest.approx(start[1] + 0.8)
    assert end[0] - start[0] > 7.9  # spans the 8 m loop
    assert float(dim["text"]) == pytest.approx(end[0] - start[0], abs=1e-2)
    y = call("overall_dimension", json.dumps(walls), 0.5, "y")
    assert y["ok"] and y["axis"] == "y", y
    auto = call("overall_dimension", json.dumps(walls), 0.5, "auto")
    assert auto["ok"] and auto["axis"] == "x", auto  # 8 m beats 6 m
    assert not call("overall_dimension", json.dumps([]), 0.8, "x")["ok"]
    assert not call("overall_dimension", json.dumps(walls), 0.8, "z")["ok"]
