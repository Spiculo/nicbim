# SPDX-License-Identifier: GPL-3.0-or-later
"""D255: library objects with hand-drawn views are drawn from them in sections and elevations."""
import json

from kimbim import app_bridge as B
from kimbim import authoring as A
from kimbim import drawgen as G
from kimbim import drawings as DR
from kimbim import library


def test_tree_type_has_views_and_elevations_draw_them():
    A.new_project("Views", "IFC4")
    storey = B._model.by_type("IfcBuildingStorey")[0].GlobalId
    wall_type = json.loads(A.wall_types())["types"][0]["guid"]
    assert json.loads(A.create_wall(storey, wall_type, -3.0, 5.0, 6.0, 5.0, 3.0))["ok"]  # something to frame
    out = json.loads(B.place_object(storey, "tree", "", 0.0, 0.0, 0.0))
    assert out.get("ok", True), out
    tree = next(e for e in B._model.by_type("IfcGeographicElement"))
    t = next(iter(tree.IsTypedBy)).RelatingType
    idents = {m.MappedRepresentation.RepresentationIdentifier for m in t.RepresentationMaps}
    assert {"Body", "Annotation", "FrontView"} <= idents
    south = next(d for d in json.loads(DR.drawings())["drawings"] if d.get("side") == "south")
    svg, _ = G.generate(B._model, B._model.by_guid(south["guid"]))
    assert f'data-kind="object" ifc:guid="{tree.GlobalId}"' in svg  # the drawn view, tagged for pens


def test_views_must_be_front_or_side():
    import pytest

    from kimbim import objects
    data = json.loads((library.BUNDLED / "tree.nicobj").read_text(encoding="utf-8"))
    data["views"] = {"top": []}
    with pytest.raises(objects.ObjectError):
        objects.ObjectDef(data)
