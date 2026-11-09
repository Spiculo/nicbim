# SPDX-License-Identifier: GPL-3.0-or-later
"""Layouts made of many elements at once, each one undo step:

* a beam system: joists or rafters of a beam type at a spacing across an outline, in a direction;
* interior elevations of a room: one elevation per wall, set just inside the room and looking at it;
* lintels: a beam (IfcBeam LINTEL) over each selected door, window or wall opening, bearing on the
  wall either side.
"""
from __future__ import annotations

import json
import math

import ifcopenshell
import ifcopenshell.api.geometry
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.util.element
import ifcopenshell.util.placement
import numpy as np

from . import app_bridge as B
from . import authoring as A
from . import layers, renovation

LINTEL_PSET = "KIMBIM_Lintel"


def _one_step(work):
    """Run `work()` (bridge calls that each make a step) as a single undo step; returns its result."""
    from . import console

    with console.edit():
        return work()


# ---------------------------------------------------------------- beam systems

def beam_lines(outline, spacing: float, angle_deg: float, margin: float | None = None):
    """The beams' plan lines: parallel to `angle_deg`, `spacing` apart, the first and last `margin`
    (default half a spacing) inside the outline, each clipped to it (a concave outline can split a line)."""
    from shapely.geometry import LineString, Polygon

    shape = Polygon(outline)
    if not shape.is_valid or shape.area <= 0:
        return []
    a = math.radians(angle_deg)
    d = np.array([math.cos(a), math.sin(a)])
    n = np.array([-d[1], d[0]])
    pts = np.array(outline, dtype=float)
    across = pts @ n
    along = pts @ d
    lo, hi = float(across.min()), float(across.max())
    reach = float(along.max() - along.min()) + 1.0
    margin = spacing / 2 if margin is None else margin
    lines = []
    k = lo + margin
    while k <= hi - margin + 1e-9:
        base = n * k + d * (float(along.min()) - 0.5)
        cut = shape.intersection(LineString([tuple(base), tuple(base + d * reach)]))
        for piece in getattr(cut, "geoms", [cut]):
            if piece.geom_type == "LineString" and piece.length > 0.05:
                (x1, y1), (x2, y2) = piece.coords[0], piece.coords[-1]
                lines.append((x1, y1, x2, y2))
        k += spacing
    return lines


def create_beam_system(storey_guid: str, type_guid: str, points_json: str, spacing=0.4, angle=0.0, top="") -> str:
    """Beams of a type every `spacing` metres across an outline (plan metres), running at `angle`
    degrees from +X, their tops at `top` (absolute metres; default the level). One undo step."""
    if B._model is None:
        return A._fail("no model open")
    storey = A._by_guid(storey_guid)
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return A._fail("unknown level")
    try:
        outline = A._clean_polygon(json.loads(points_json))
        spacing, angle = float(spacing), float(angle)
        top = A._elevation(storey) if top in (None, "") else float(top)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    if outline is None:
        return A._fail("the outline needs at least 3 points and must not cross itself")
    if not 0.1 <= spacing <= 20:
        return A._fail("the spacing must be between 10 cm and 20 m")
    lines = beam_lines(outline, spacing, angle)
    if not lines:
        return A._fail("no beam fits in that outline")
    if len(lines) > 500:
        return A._fail("that would make more than 500 beams: use a wider spacing")

    def work():
        made = []
        for x1, y1, x2, y2 in lines:
            r = json.loads(A.create_beam(storey_guid, type_guid, x1, y1, x2, y2, top))
            if not r.get("ok"):
                raise RuntimeError(r.get("error") or "a beam could not be made")
            made += r["guids"]
        return made

    try:
        made = _one_step(work)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}" if not isinstance(ex, RuntimeError) else str(ex))
    return B._dump({"ok": True, "guids": made, "count": len(made), **B._flags(),
                    "geometry": {"changed": made, "removed": []}})


# ---------------------------------------------------------------- interior elevations

def interior_elevations(room_guid: str, offset=0.5) -> str:
    """One elevation per wall of a room (edges of 30 cm or more), on a line `offset` inside the room
    and seeing just past the wall face: Archicad's interior elevation. Named "<room> Interior A"..."""
    if B._model is None:
        return A._fail("no model open")
    space = A._by_guid(room_guid)
    if space is None or not space.is_a("IfcSpace"):
        return A._fail("select a room")
    try:
        offset = float(offset)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    if not 0.05 <= offset <= 5:
        return A._fail("the offset must be between 5 cm and 5 m")
    from shapely.geometry import Point, Polygon

    from . import drawings, rooms

    outline = rooms._outline(space)
    if len(outline) < 3:
        return A._fail("the room has no outline")
    shape = Polygon(outline)
    markers = []
    for i in range(len(outline)):
        a, b = np.array(outline[i], dtype=float), np.array(outline[(i + 1) % len(outline)], dtype=float)
        length = float(np.linalg.norm(b - a))
        if length < 0.3:
            continue
        d = (b - a) / length
        n = np.array([-d[1], d[0]])
        mid = (a + b) / 2
        if not shape.contains(Point(*(mid + n * 0.01))):
            n = -n  # point the normal into the room
        p1, p2 = a + n * offset, b + n * offset
        look = mid - n  # towards the wall
        markers.append(([[float(p1[0]), float(p1[1])], [float(p2[0]), float(p2[1])]], [float(look[0]), float(look[1])]))
    if not markers:
        return A._fail("the room's walls are too short")
    label = " ".join(x for x in (space.Name, space.LongName) if x) or "Room"
    made = []

    def action():
        for k, (points, look) in enumerate(markers):
            letter = chr(ord("A") + k) if k < 26 else str(k + 1)
            s = {"kind": "elevation", "points": points, "look": look, "depth": offset + 0.05, "auto": False,
                 "bulges": [0.0], "tilt": 0.0, "base": 0.0}
            made.append(drawings._new(f"{label} Interior {letter}", s).GlobalId)
        return len(made)

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guids": made})


# ---------------------------------------------------------------- lintels

def _opening_of(element):
    if element.is_a("IfcOpeningElement"):
        return element
    for rel in getattr(element, "FillsVoids", ()) or ():
        return rel.RelatingOpeningElement
    return None


def _local_box(product):
    """The min and max corners of a product's body in its own placement (metres)."""
    import ifcopenshell.geom

    settings = ifcopenshell.geom.settings()
    shape = ifcopenshell.geom.create_shape(settings, product)
    v = np.array(shape.geometry.verts, dtype=float).reshape(-1, 3)
    m = np.array(shape.transformation.matrix, dtype=float).reshape(4, 4).T  # verts are local; m places them
    return v.min(axis=0), v.max(axis=0), m


def add_lintels(guids_json: str, bearing=0.15, height=0.2) -> str:
    """A lintel (IfcBeam LINTEL) over each selected door, window or wall opening: as deep as the
    opening goes through the wall, `bearing` metres onto the wall at each side, `height` tall, sitting
    on the opening's head. Openings that already have one are skipped. One undo step."""
    if B._model is None:
        return A._fail("no model open")
    try:
        elements = B._elements(guids_json)
        bearing, height = float(bearing), float(height)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    if not 0.0 <= bearing <= 1.0 or not 0.02 <= height <= 2.0:
        return A._fail("the bearing or height is out of range")
    have = set()
    for pset in B._model.by_type("IfcPropertySet"):
        if pset.Name == LINTEL_PSET:
            for p in pset.HasProperties:
                if p.Name == "Opening":
                    have.add(getattr(p.NominalValue, "wrappedValue", None))
    todo = []
    for e in elements:
        opening = _opening_of(e)
        if opening is None or opening.GlobalId in have or any(o is opening for o, _ in todo):
            continue
        walls = [rel.RelatingBuildingElement for rel in getattr(opening, "VoidsElements", ()) or ()]
        if not walls or not walls[0].is_a("IfcWall"):
            continue
        todo.append((opening, walls[0]))
    if not todo:
        return A._fail("select doors, windows or wall openings without a lintel")
    made = []

    def action():
        f = B._model
        for opening, wall in todo:
            lo, hi, m = _local_box(opening)
            width, depth = float(hi[0] - lo[0]), float(hi[1] - lo[1])
            beam = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBeam", name="Lintel", predefined_type="LINTEL")
            representation = ifcopenshell.api.geometry.add_wall_representation(
                f, context=A._body_context(), length=width + 2 * bearing, height=height, thickness=depth)
            ifcopenshell.api.geometry.assign_representation(f, product=beam, representation=representation)
            corner = m @ np.array([lo[0] - bearing, lo[1], hi[2], 1.0])
            matrix = m.copy()
            matrix[:3, 3] = corner[:3]
            ifcopenshell.api.geometry.edit_object_placement(f, product=beam, matrix=matrix, is_si=True)
            storey = ifcopenshell.util.element.get_container(wall)
            if storey is not None:
                ifcopenshell.api.spatial.assign_container(f, products=[beam], relating_structure=storey)
            pset = ifcopenshell.api.pset.add_pset(f, product=beam, name=LINTEL_PSET)
            ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={
                "Opening": opening.GlobalId, "Bearing": bearing, "Height": height})
            layers.assign_active(beam)
            renovation.stamp_new(beam)
            made.append(beam.GlobalId)
        return len(made), made, []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guids": made})


# ---------------------------------------------------------------- kerbs and planting areas (site)

SITE_PSET = "KIMBIM_Site"


def _site_class(ifc4: str) -> str:
    return ifc4 if B._model.schema != "IFC2X3" else "IfcBuildingElementProxy"


def create_kerb(storey_guid: str, points_json: str, width=0.15, height=0.15, name: str = "Kerb") -> str:
    """A kerb along a path (plan metres): a `width` x `height` band on the level, one box per straight
    segment, as one element (IfcCivilElement; a proxy in IFC2X3). One undo step."""
    if B._model is None:
        return A._fail("no model open")
    storey = A._by_guid(storey_guid)
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return A._fail("unknown level")
    try:
        points = [(float(p[0]), float(p[1])) for p in json.loads(points_json)]
        width, height = float(width), float(height)
    except (TypeError, ValueError, IndexError) as ex:
        return A._fail(str(ex))
    segments = [(a, b) for a, b in zip(points, points[1:]) if math.dist(a, b) > 0.01]
    if not segments:
        return A._fail("draw the kerb with two different points")
    if not 0.02 <= width <= 2 or not 0.01 <= height <= 2:
        return A._fail("the kerb's size is out of range")
    made = {}

    def action():
        f = B._model
        s = A._scale()
        kerb = ifcopenshell.api.root.create_entity(f, ifc_class=_site_class("IfcCivilElement"), name=name)
        items = []
        for (x1, y1), (x2, y2) in segments:
            length = math.dist((x1, y1), (x2, y2))
            d = ((x2 - x1) / length, (y2 - y1) / length)
            # the profile is the band's plan rectangle (centred on the path), extruded up
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            position2d = f.createIfcAxis2Placement2D(f.createIfcCartesianPoint((cx / s, cy / s)),
                                                     f.createIfcDirection((d[0], d[1])))
            profile = f.createIfcRectangleProfileDef("AREA", None, position2d, length / s, width / s)
            position = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None)
            items.append(f.createIfcExtrudedAreaSolid(profile, position, f.createIfcDirection((0.0, 0.0, 1.0)), height / s))
        representation = f.createIfcShapeRepresentation(A._body_context(), "Body", "SweptSolid", items)
        ifcopenshell.api.geometry.assign_representation(f, product=kerb, representation=representation)
        matrix = np.eye(4)
        matrix[2][3] = A._elevation(storey)
        ifcopenshell.api.geometry.edit_object_placement(f, product=kerb, matrix=matrix, is_si=True)
        ifcopenshell.api.spatial.assign_container(f, products=[kerb], relating_structure=storey)
        pset = ifcopenshell.api.pset.add_pset(f, product=kerb, name=SITE_PSET)
        ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={
            "Kind": "kerb", "Width": width, "Height": height,
            "Points": json.dumps([[round(x, 6), round(y, 6)] for x, y in points], separators=(",", ":"))})
        layers.assign_active(kerb)
        renovation.stamp_new(kerb)
        made["guid"] = kerb.GlobalId
        return 1, [kerb.GlobalId], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["guid"]})


def create_planting_area(storey_guid: str, points_json: str, depth=0.3, planting: str = "", name: str = "Planting area") -> str:
    """A planting bed over an outline (plan metres): `depth` of soil on the level, its planting (a
    species or mix) in `KIMBIM_Site`; IfcGeographicElement (a proxy in IFC2X3). One undo step."""
    if B._model is None:
        return A._fail("no model open")
    storey = A._by_guid(storey_guid)
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return A._fail("unknown level")
    try:
        outline = A._clean_polygon(json.loads(points_json))
        depth = float(depth)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    if outline is None:
        return A._fail("the outline needs at least 3 points and must not cross itself")
    if not 0.01 <= depth <= 5:
        return A._fail("the depth is out of range")
    made = {}

    def action():
        f = B._model
        area = ifcopenshell.api.root.create_entity(f, ifc_class=_site_class("IfcGeographicElement"), name=name)
        representation = ifcopenshell.api.geometry.add_slab_representation(
            f, context=A._body_context(), depth=depth, polyline=outline)
        ifcopenshell.api.geometry.assign_representation(f, product=area, representation=representation)
        matrix = np.eye(4)
        matrix[2][3] = A._elevation(storey)
        ifcopenshell.api.geometry.edit_object_placement(f, product=area, matrix=matrix, is_si=True)
        ifcopenshell.api.spatial.assign_container(f, products=[area], relating_structure=storey)
        pset = ifcopenshell.api.pset.add_pset(f, product=area, name=SITE_PSET)
        ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={
            "Kind": "planting", "Depth": depth, "Planting": str(planting or "")})
        layers.assign_active(area)
        renovation.stamp_new(area)
        made["guid"] = area.GlobalId
        return 1, [area.GlobalId], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["guid"]})


# ---------------------------------------------------------------- handrails on walls

HANDRAIL_PSET = "KIMBIM_Handrail"


def wall_handrail(wall_guid: str, side: str = "left", height=0.9, gap=0.05, diameter=0.04, inset=0.1) -> str:
    """A handrail fixed to a wall face: a round rail `diameter` thick, its centre `gap` + radius off the
    face on `side` ("left"/"right" of the wall's axis direction), at `height` above the wall base and
    `inset` short of each end (IfcRailing HANDRAIL). One undo step."""
    if B._model is None:
        return A._fail("no model open")
    wall = A._by_guid(wall_guid)
    if wall is None or not wall.is_a("IfcWall"):
        return A._fail("select a straight wall")
    axis = A._axis_world(wall)
    layer_set = A._layer_set(wall)
    if axis is None or layer_set is None:
        return A._fail("the wall has no axis or layers")
    side = str(side or "left").strip().lower()
    if side not in ("left", "right"):
        return A._fail("the side is left or right")
    try:
        height, gap, diameter, inset = float(height), float(gap), float(diameter), float(inset)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    if not 0.3 <= height <= 2.0 or not 0.0 <= gap <= 0.3 or not 0.02 <= diameter <= 0.1:
        return A._fail("the handrail's height, gap or diameter is out of range")
    (x1, y1), (x2, y2) = axis
    length = math.hypot(x2 - x1, y2 - y1)
    if length <= 2 * inset + 0.1:
        return A._fail("the wall is too short for a handrail")
    d = np.array([(x2 - x1) / length, (y2 - y1) / length, 0.0])
    left = np.array([-d[1], d[0], 0.0])
    thickness = A._thickness(layer_set)
    centre = A._body_centre(wall)  # the body's middle, to the axis' left
    face = centre + thickness / 2 if side == "left" else centre - thickness / 2
    across = face + (gap + diameter / 2) * (1 if side == "left" else -1)
    base = float(ifcopenshell.util.placement.get_local_placement(wall.ObjectPlacement)[2][3]) * A._scale()
    start = np.array([x1, y1, base + height]) + left * across + d * inset
    run = length - 2 * inset
    storey = ifcopenshell.util.element.get_container(wall)
    made = {}

    def action():
        f = B._model
        s = A._scale()
        rail = ifcopenshell.api.root.create_entity(f, ifc_class="IfcRailing", name="Handrail", predefined_type="HANDRAIL")
        profile = f.createIfcCircleProfileDef("AREA", None, f.createIfcAxis2Placement2D(
            f.createIfcCartesianPoint((0.0, 0.0)), None), diameter / 2 / s)
        representation = ifcopenshell.api.geometry.add_profile_representation(
            f, context=A._body_context(), profile=profile, depth=run)
        ifcopenshell.api.geometry.assign_representation(f, product=rail, representation=representation)
        matrix = np.eye(4)
        matrix[:3, 0], matrix[:3, 1], matrix[:3, 2] = left, np.array([0.0, 0.0, 1.0]), d  # extruded along the wall
        matrix[:3, 3] = start
        ifcopenshell.api.geometry.edit_object_placement(f, product=rail, matrix=matrix, is_si=True)
        if storey is not None:
            ifcopenshell.api.spatial.assign_container(f, products=[rail], relating_structure=storey)
        pset = ifcopenshell.api.pset.add_pset(f, product=rail, name=HANDRAIL_PSET)
        ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={
            "Wall": wall.GlobalId, "Side": side, "Height": height, "Diameter": diameter})
        layers.assign_active(rail)
        renovation.stamp_new(rail)
        made["guid"] = rail.GlobalId
        return 1, [rail.GlobalId], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["guid"], "length": round(run, 6)})
