# SPDX-License-Identifier: GPL-3.0-or-later
"""Free-form morphing and push/pull (D220).

Massing boxes (D201) are extruded rectangles: pushing a side or the top/bottom changes the
footprint or the height and keeps the ``KIMBIM_Massing`` property set in step, so the massing
report follows. Elements with a triangulated mesh body (imported meshes, terrain) have the
vertices on the named face moved along the axis; ``move_vertices`` moves chosen vertices for
free-form shaping. Every call is one undo step, and the body change marks the drawings dirty.
"""
from __future__ import annotations

import json

import ifcopenshell.api.geometry
import ifcopenshell.api.pset
import ifcopenshell.util.element
import ifcopenshell.util.placement
import numpy as np

from . import app_bridge as B
from . import authoring as A

FACES = ("+x", "-x", "+y", "-y", "+z", "-z")
AXIS = {"x": 0, "y": 1, "z": 2}
MASSING_PSET = A.MASSING_PSET


def _body_items(element) -> list:
    representation = getattr(element, "Representation", None)
    if representation is None:
        return []
    items = []
    for shape in representation.Representations or ():
        items.extend(shape.Items or ())
    return items


def _massing_box(element) -> tuple[float, float, float] | None:
    data = ifcopenshell.util.element.get_pset(element, MASSING_PSET) or {}
    if data.get("Role") != "massing":
        return None
    try:
        return float(data["Width"]), float(data["Depth"]), float(data["Height"])
    except (KeyError, TypeError, ValueError):
        return None


def _triangulated(element):
    for item in _body_items(element):
        if item.is_a("IfcTriangulatedFaceSet"):
            return item
    return None


def _rect_profile(f, width: float, depth: float):
    s = A._scale()
    return f.createIfcRectangleProfileDef(
        "AREA", None,
        f.createIfcAxis2Placement2D(f.createIfcCartesianPoint((0.0, 0.0)), None),
        width / s, depth / s)


def _element(guid):
    try:
        return B._model.by_guid(str(guid or ""))
    except RuntimeError:
        return None


def _push_pull_box(f, element, face: str, distance: float) -> tuple[int, int]:
    width, depth, height = _massing_box(element)
    matrix = ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement)
    scale = A._scale()
    # Placements are stored in model units; the pset and the call are in metres.
    x, y, z = (float(matrix[i][3]) / scale for i in range(3))
    if face == "+x":
        width += distance
        x += distance / 2.0
    elif face == "-x":
        width += distance
        x -= distance / 2.0
    elif face == "+y":
        depth += distance
        y += distance / 2.0
    elif face == "-y":
        depth += distance
        y -= distance / 2.0
    elif face == "+z":
        height += distance
    else:  # -z: the bottom face moves down and the box grows from there
        height += distance
        z -= distance
    if min(width, depth, height) <= 1e-6:
        raise ValueError("the box would collapse: choose a smaller distance")
    profile = _rect_profile(f, width, depth)
    representation = ifcopenshell.api.geometry.add_profile_representation(
        f, context=A._body_context(), profile=profile, depth=height)
    ifcopenshell.api.geometry.assign_representation(f, product=element, representation=representation)
    matrix[0][3], matrix[1][3], matrix[2][3] = x, y, z
    ifcopenshell.api.geometry.edit_object_placement(f, product=element, matrix=matrix, is_si=True)
    pset = ifcopenshell.util.element.get_pset(element, MASSING_PSET)
    if pset:
        ifcopenshell.api.pset.edit_pset(
            f, pset=f.by_id(pset["id"]), properties={
                "Width": width, "Depth": depth, "Height": height})
    return 1, 1


def _face_vertices(faceset, matrix: np.ndarray, face: str) -> list[int]:
    """Indices of the vertices on the named outer face (within a small tolerance)."""
    coordinates = list(faceset.Coordinates.CoordList or ())
    if not coordinates:
        return []
    s = A._scale()
    local = np.array([[float(v) * s for v in c] for c in coordinates])
    world = (matrix[:3, :3] @ local.T).T + matrix[:3, 3]
    axis = AXIS[face[1]]
    extreme = world[:, axis].max() if face[0] == "+" else world[:, axis].min()
    tolerance = 1e-6 * max(1.0, float(np.ptp(world[:, axis])))
    return [i for i, value in enumerate(world[:, axis]) if abs(value - extreme) <= tolerance]


def _move(faceset, matrix: np.ndarray, indices: list[int], delta: np.ndarray) -> int:
    coordinates = list(faceset.Coordinates.CoordList or ())
    local_delta = matrix[:3, :3].T @ delta
    s = A._scale()
    for i in indices:
        coordinates[i] = tuple(float(v) + float(local_delta[k]) / s
                               for k, v in enumerate(coordinates[i]))
    faceset.Coordinates.CoordList = coordinates
    return len(indices)


def _push_pull_mesh(f, element, faceset, face: str, distance: float) -> tuple[int, int]:
    matrix = ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement)
    indices = _face_vertices(faceset, matrix, face)
    if not indices:
        raise ValueError(f"no vertices lie on the {face} face")
    delta = np.zeros(3)
    delta[AXIS[face[1]]] = distance if face[0] == "+" else -distance
    return _move(faceset, matrix, indices, delta), len(indices)


def push_pull(guid: str, face: str, distance) -> str:
    """Push or pull one face of a massing box or a triangulated mesh (metres).

    ``face`` is one of +x, -x, +y, -y, +z (top), -z (bottom); a negative distance pulls the
    face inward. Returns the moved vertex count for meshes.
    """
    if B._model is None:
        return A._fail("no model open")
    face = str(face or "").strip().lower()
    if face not in FACES:
        return A._fail("the face is one of +x, -x, +y, -y, +z or -z")
    try:
        distance = float(distance)
    except (TypeError, ValueError) as ex:
        return A._fail(f"bad distance: {ex}")
    element = _element(guid)
    if element is None:
        return A._fail("element not found")
    state: dict = {}

    def action():
        f = B._model
        if _massing_box(element) is not None:
            changed, moved = _push_pull_box(f, element, face, distance)
        else:
            faceset = _triangulated(element)
            if faceset is None:
                raise ValueError("this element has no massing box or triangulated mesh to morph")
            changed, moved = _push_pull_mesh(f, element, faceset, face, distance)
        state["moved"] = moved
        return changed, [element.GlobalId], []

    try:
        result = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**result, "guid": element.GlobalId, "face": face,
                    "distance": distance, "moved": state.get("moved", 1)})


def move_vertices(guid: str, indices_json, dx=0.0, dy=0.0, dz=0.0) -> str:
    """Free-form morphing: move the chosen mesh vertices (0-based) by a world-space offset."""
    if B._model is None:
        return A._fail("no model open")
    try:
        indices = json.loads(indices_json) if isinstance(indices_json, str) else list(indices_json)
        indices = [int(i) for i in indices]
        delta = np.array([float(dx), float(dy), float(dz)])
    except (TypeError, ValueError, json.JSONDecodeError) as ex:
        return A._fail(f"bad vertex list or offset: {ex}")
    if not indices:
        return A._fail("choose at least one vertex")
    element = _element(guid)
    if element is None:
        return A._fail("element not found")
    faceset = _triangulated(element)
    if faceset is None:
        return A._fail("this element has no triangulated mesh to morph")
    count = len(list(faceset.Coordinates.CoordList or ()))
    if any(i < 0 or i >= count for i in indices):
        return A._fail(f"vertex indices are 0 to {count - 1}")
    state: dict = {}

    def action():
        matrix = ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement)
        state["moved"] = _move(faceset, matrix, indices, delta)
        return 1, [element.GlobalId], []

    try:
        result = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**result, "guid": element.GlobalId, "moved": state.get("moved", len(indices))})
