# SPDX-License-Identifier: GPL-3.0-or-later
"""D221: live Rhino/Grasshopper mesh links - add, stale detection, in-place refresh and removal."""
import json

import ifcopenshell.geom
import numpy as np

from kimbim import app_bridge as B
from kimbim import meshlink as ML
from kimbim.testing import build_model

CUBE_VERTICES = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
                 (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.0, 1.0, 1.0)]
CUBE_QUADS = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 4, 7, 3),
              (1, 5, 4, 0), (2, 6, 5, 1), (3, 7, 6, 2)]


def call(fn, *args):
    return json.loads(fn(*args))


def open_model():
    f = build_model(schema="IFC4", walls=0)
    B._model = f
    B._reset_history("")
    return f, f.by_type("IfcBuildingStorey")[0].GlobalId


def obj_cube(top=1.0) -> str:
    lines = [f"v {x} {y} {z * top}" for x, y, z in CUBE_VERTICES]
    lines += ["f " + " ".join(str(i + 1) for i in q) for q in CUBE_QUADS]
    return "\n".join(lines) + "\n"


def world_vertices(guid):
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    shape = ifcopenshell.geom.create_shape(settings, B._model.by_guid(guid))
    return np.array(shape.geometry.verts).reshape(-1, 3)


def test_a_live_mesh_link_follows_its_file(tmp_path):
    f, level = open_model()
    path = tmp_path / "rhino.obj"
    path.write_text(obj_cube(), encoding="utf-8")
    r = call(ML.add_mesh_link, str(path), level, json.dumps({"name": "Rhino mass"}))
    assert r["ok"] and r["triangles"] == 12
    guid = r["guid"]
    links = call(ML.mesh_links)["links"]
    assert len(links) == 1 and links[0]["name"] == "Rhino mass" and not links[0]["stale"]
    assert world_vertices(guid)[:, 2].max() == 1.0
    # The designer exports again: the file hash changes and the link becomes stale.
    path.write_text(obj_cube(top=2.0), encoding="utf-8")
    stale = call(ML.stale_mesh_links)["links"]
    assert len(stale) == 1 and stale[0]["guid"] == guid
    r = call(ML.refresh_mesh_links, "")
    assert r["ok"] and r["updated"] == [guid] and r["errors"] == []
    assert world_vertices(guid)[:, 2].max() == 2.0  # rebuilt in place, same GlobalId
    assert call(ML.refresh_mesh_links, guid)["ok"]  # an explicit update is allowed when not stale
    assert not call(ML.mesh_links)["links"][0]["stale"]
    # Each refresh is one undo step; undo the explicit no-op update, then the file-change one.
    assert call(B.undo)["ok"]
    assert call(B.undo)["ok"]
    assert world_vertices(guid)[:, 2].max() == 1.0


def test_a_bad_source_is_refused_and_removal_works(tmp_path):
    f, level = open_model()
    assert not call(ML.add_mesh_link, str(tmp_path / "absent.obj"), level)["ok"]
    assert not call(ML.add_mesh_link, "", level)["ok"]
    assert not call(ML.add_mesh_link, __file__, "no-such-level")["ok"]
    path = tmp_path / "grasshopper.obj"
    path.write_text(obj_cube(), encoding="utf-8")
    guid = call(ML.add_mesh_link, str(path), level)["guid"]
    path.unlink()  # a missing source is stale and cannot be refreshed
    assert not call(ML.mesh_links)["links"][0]["stale"] is False
    r = call(ML.refresh_mesh_links, "")
    assert r["ok"] and r["updated"] == [] and r["errors"]
    assert call(ML.remove_mesh_link, guid)["ok"]
    assert call(ML.mesh_links)["links"] == []
    assert not call(ML.remove_mesh_link, guid)["ok"]
