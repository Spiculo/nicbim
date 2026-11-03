# SPDX-License-Identifier: GPL-3.0-or-later
"""D220: free-form morphing - push/pull massing boxes and mesh faces, and move mesh vertices."""
import json

import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.placement
import numpy as np

from kimbim import app_bridge as B
from kimbim import authoring as A
from kimbim import meshimport as MI
from kimbim import morph as M
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


def obj_cube() -> str:
    lines = [f"v {x} {y} {z}" for x, y, z in CUBE_VERTICES]
    lines += ["f " + " ".join(str(i + 1) for i in q) for q in CUBE_QUADS]
    return "\n".join(lines) + "\n"


def world_vertices(guid):
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    shape = ifcopenshell.geom.create_shape(settings, B._model.by_guid(guid))
    return np.array(shape.geometry.verts).reshape(-1, 3)


def test_push_pull_a_massing_box():
    """A side grows the footprint and shifts the centre; the top/bottom grow the height."""
    f, level = open_model()
    guid = call(A.create_massing, level, 0, 0, 4, 6, 3)["guid"]
    box = f.by_guid(guid)
    r = call(M.push_pull, guid, "+x", 2)
    assert r["ok"] and r["moved"] == 1
    pset = ifcopenshell.util.element.get_pset(box, "KIMBIM_Massing")
    assert pset["Width"] == 6.0 and pset["Depth"] == 6.0 and pset["Height"] == 3.0
    matrix = ifcopenshell.util.placement.get_local_placement(box.ObjectPlacement)
    scale = ifcopenshell.util.unit.calculate_unit_scale(f)
    assert matrix[0][3] * scale == 1.0  # the centre followed the face by half the distance
    assert call(M.push_pull, guid, "+z", 2)["ok"]
    assert call(M.push_pull, guid, "-z", 1)["ok"]
    pset = ifcopenshell.util.element.get_pset(box, "KIMBIM_Massing")
    assert pset["Height"] == 6.0
    matrix = ifcopenshell.util.placement.get_local_placement(box.ObjectPlacement)
    assert matrix[2][3] * scale == -1.0  # the bottom moved down, so the box starts lower
    # One undo step per call.
    assert call(B.undo)["ok"]
    assert ifcopenshell.util.element.get_pset(box, "KIMBIM_Massing")["Height"] == 5.0


def test_bad_faces_and_collapse_are_refused():
    f, level = open_model()
    guid = call(A.create_massing, level, 0, 0, 4, 6, 3)["guid"]
    assert not call(M.push_pull, guid, "+w", 1)["ok"]
    assert not call(M.push_pull, guid, "+x", "wide")["ok"]
    assert not call(M.push_pull, "no-such-guid", "+x", 1)["ok"]
    assert not call(M.push_pull, guid, "+x", -4)["ok"]  # would collapse the width
    pset = ifcopenshell.util.element.get_pset(f.by_guid(guid), "KIMBIM_Massing")
    assert pset["Width"] == 4.0  # unchanged
    wall = f.by_type("IfcWall")[0] if f.by_type("IfcWall") else None
    if wall is not None:
        assert not call(M.push_pull, wall.GlobalId, "+x", 1)["ok"]


def test_push_pull_a_mesh_face_and_move_vertices(tmp_path):
    f, level = open_model()
    path = tmp_path / "cube.obj"
    path.write_text(obj_cube(), encoding="utf-8")
    guid = call(MI.import_mesh, str(path), level)["guid"]
    start = world_vertices(guid)
    assert start[:, 2].max() == 1.0
    r = call(M.push_pull, guid, "+z", 2)
    assert r["ok"] and r["moved"] >= 3  # the triangles on the top face
    lifted = world_vertices(guid)
    assert lifted[:, 2].max() == 3.0
    assert lifted[:, 2].min() == 0.0
    # Free-form: move one bottom vertex down and sideways.
    index = int(np.argmin(start[:, 2]))
    r = call(M.move_vertices, guid, json.dumps([index]), 0.5, 0.0, -0.5)
    assert r["ok"] and r["moved"] == 1
    moved = world_vertices(guid)
    assert moved[:, 2].min() == -0.5
    assert np.isclose(moved[:, 0], 0.5).any()  # the moved vertex also went +0.5 in x
    # Undo restores the vertex; bad indices are refused.
    assert not call(M.move_vertices, guid, json.dumps([9999]), 0, 0, 1)["ok"]
    assert not call(M.move_vertices, guid, json.dumps([]), 0, 0, 1)["ok"]
    assert call(B.undo)["ok"]
    assert world_vertices(guid)[:, 2].min() == 0.0
    assert call(B.undo)["ok"]
    assert world_vertices(guid)[:, 2].max() == 1.0
