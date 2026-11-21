# SPDX-License-Identifier: GPL-3.0-or-later
"""Template elevation markers follow the model (D61): made in an empty project, they must not end up inside
the building once it is drawn."""
import json

from kimbim import app_bridge as B
from kimbim import authoring as A
from kimbim import drawings as DR


def test_template_markers_refit_to_the_building():
    A.new_project("Casa", "IFC4")
    storey = B._model.by_type("IfcBuildingStorey")[0].GlobalId
    wall_type = json.loads(A.wall_types())["types"][0]["guid"]
    for (x1, y1), (x2, y2) in (((0.3, 3), (8.4, 3)), ((8.4, 3), (8.4, 15)), ((8.4, 15), (0.3, 15)),
                               ((0.3, 15), (0.3, 3))):
        assert json.loads(A.create_wall(storey, wall_type, x1, y1, x2, y2, 3.0))["ok"]
    by_side = {d["side"]: d for d in json.loads(DR.drawings())["drawings"] if d.get("side")}
    north = by_side["north"]["points"]
    assert min(p[1] for p in north) > 15, north  # beyond the back wall, not inside the house
    south = by_side["south"]["points"]
    assert max(p[1] for p in south) < 3, south
    from kimbim import drawgen as G
    plan = next(d for d in json.loads(DR.drawings())["drawings"] if d["kind"] == "plan")
    svg, _ = G.generate(B._model, B._model.by_guid(plan["guid"]))
    assert "North Elevation" in svg
