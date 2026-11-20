# SPDX-License-Identifier: GPL-3.0-or-later
"""Everyday editing (Slice 17), after Archicad's Edit menu: copy with an offset or onto another level
(copy/paste, drag with Ctrl), Duplicate, Mirror (in place, or a copy), Multiply (linear and polar
arrays) and Offset. Copies get new GlobalIds and keep their layers; walls bring their doors/windows
and the joins between copied walls are copied. Same protocol as app_bridge.
"""
from __future__ import annotations

import json
import math
import os

import ifcopenshell.api.geometry
import ifcopenshell.api.project
import ifcopenshell.api.pset
import ifcopenshell.api.spatial
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.representation
import ifcopenshell.util.unit
import numpy as np

from . import app_bridge as B
from . import authoring as A

DUPLICATE_OFFSET = (1.0, 1.0)  # metres: Archicad's Duplicate places the copy at an offset


def _translation(dx, dy, dz=0.0):
    t = np.eye(4)
    t[:3, 3] = [dx / A._scale(), dy / A._scale(), dz / A._scale()]
    return t


def _check(guids_json):
    elements = A._copyable(guids_json)
    if not elements:
        return None, A._fail("select the elements to copy (doors and windows come with their wall)")
    for e in elements:
        container = ifcopenshell.util.element.get_container(e)
        if container is None or not container.is_a("IfcBuildingStorey"):
            return None, A._fail(f"{e.GlobalId} is not on a level")
    return elements, None


def _copies(elements, transform, target=None):
    """Inside an action: copy each level's elements with `transform` (project units), onto `target`
    (a storey, keeping the height above the level) or their own level."""
    pairs = []
    by_level = {}
    for e in elements:
        by_level.setdefault(ifcopenshell.util.element.get_container(e), []).append(e)
    for level, group in by_level.items():
        t = transform.copy()
        if target is not None:
            t = _translation(0, 0, A._elevation(target) - A._elevation(level)) @ t
        pairs += A._copy_elements(group, target or level, t)
    return pairs


def _run_copy(elements, make_pairs):
    made = {}

    def action():
        pairs = make_pairs()
        made["copies"] = [c.GlobalId for e, c in pairs if e in elements]
        return len(made["copies"]), [c.GlobalId for _, c in pairs], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guids": made["copies"]})


def copy_elements(guids_json: str, dx, dy, dz=0.0, storey_guid: str = "") -> str:
    """Copy elements moved by (dx, dy, dz) metres; onto another level when `storey_guid` is given
    (paste on another level keeps the plan position, as in Archicad)."""
    if B._model is None:
        return A._fail("no model open")
    elements, error = _check(guids_json)
    if error:
        return error
    try:
        t = _translation(float(dx), float(dy), float(dz or 0.0))
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    target = A._by_guid(storey_guid) if storey_guid else None
    if storey_guid and (target is None or not target.is_a("IfcBuildingStorey")):
        return A._fail("unknown level")
    return _run_copy(elements, lambda: _copies(elements, t, target))


def duplicate_elements(guids_json: str) -> str:
    """Archicad's Duplicate (Ctrl+D): a copy next to the original, offset by 1 m in x and y."""
    return copy_elements(guids_json, *DUPLICATE_OFFSET)


def paste_from_project(path: str, guids_json: str, storey_guid: str = "") -> str:
    """D193: paste elements copied in another project, with their types, materials, properties and
    geometry. They land on `storey_guid` at their own plan position and level height. One undo step."""
    if B._model is None:
        return A._fail("no model open")
    try:
        guids = json.loads(guids_json)
    except ValueError:
        return A._fail("bad list of elements")
    if not isinstance(guids, list) or not guids:
        return A._fail("nothing to paste")
    if not path or not os.path.isfile(path):
        return A._fail("the copied project is no longer there")
    target = A._by_guid(storey_guid) if storey_guid else None
    if target is None or not target.is_a("IfcBuildingStorey"):
        return A._fail("unknown level")
    try:
        source = ifcopenshell.open(path)
    except Exception as ex:
        return A._fail(f"could not open the copied project: {ex}")
    source_scale = ifcopenshell.util.unit.calculate_unit_scale(source)

    def elevation(storey) -> float:
        if storey is None:
            return 0.0
        if storey.ObjectPlacement is not None:
            return float(ifcopenshell.util.placement.get_local_placement(storey.ObjectPlacement)[2][3]) * source_scale
        return float(storey.Elevation or 0.0) * source_scale

    wanted = []
    for guid in guids:
        try:
            e = source.by_guid(guid)
        except (RuntimeError, TypeError):
            continue
        if e is not None and e.is_a("IfcProduct") and not e.is_a("IfcOpeningElement"):
            wanted.append(e)
    if not wanted:
        return A._fail("the copied elements are not in that project")
    target_z, scale = A._elevation(target), A._scale()
    reuse: dict = {}
    made = []

    def action():
        for e in wanted:
            source_type = ifcopenshell.util.element.get_type(e)
            if source_type is not None:  # bring the shared type (and its material) once
                ifcopenshell.api.project.append_asset(B._model, library=source, element=source_type,
                                                       reuse_identities=reuse)
            container = ifcopenshell.util.element.get_container(e)
            src_z = elevation(container) if container is not None and container.is_a("IfcBuildingStorey") else 0.0
            c = ifcopenshell.api.project.append_asset(B._model, library=source, element=e, reuse_identities=reuse)
            if c is None:
                continue
            if c.ObjectPlacement is not None and abs(target_z - src_z) > 1e-9:
                m = ifcopenshell.util.placement.get_local_placement(c.ObjectPlacement)
                m[2][3] += (target_z - src_z) / scale
                ifcopenshell.api.geometry.edit_object_placement(B._model, product=c, matrix=m, is_si=False)
            ifcopenshell.api.spatial.assign_container(B._model, products=[c], relating_structure=target)
            made.append(c.GlobalId)
        return len(made), made, []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guids": made})


def array_elements(guids_json: str, kind: str, params_json: str) -> str:
    """Multiply (Archicad): `linear` {dx, dy, count}: count copies, each (dx, dy) further; `polar`
    {cx, cy, angle, count}: count copies, each turned `angle` radians further around (cx, cy);
    `rectangular` {dx, dy, nx, ny}: an nx by ny grid of copies (the original is the first cell)."""
    if B._model is None:
        return A._fail("no model open")
    elements, error = _check(guids_json)
    if error:
        return error
    try:
        p = json.loads(params_json)
        if kind == "rectangular":
            dx, dy = float(p["dx"]), float(p["dy"])
            nx, ny = int(p["nx"]), int(p["ny"])
            count = nx * ny - 1
            if nx < 1 or ny < 1:
                return A._fail("the grid must have at least one row and one column")
        else:
            count = int(p["count"])
            if kind == "linear":
                dx, dy = float(p["dx"]), float(p["dy"])
            elif kind == "polar":
                cx, cy, angle = float(p["cx"]), float(p["cy"]), float(p["angle"])
            else:
                return A._fail(f"unknown array kind {kind}")
    except (KeyError, TypeError, ValueError) as ex:
        return A._fail(f"bad parameters: {ex}")
    if not 1 <= count <= 1000:
        return A._fail("the number of copies must be between 1 and 1000")

    def make():
        pairs = []
        if kind == "rectangular":
            for i in range(nx):
                for j in range(ny):
                    if i == 0 and j == 0:
                        continue  # the original
                    pairs += _copies(elements, _translation(dx * i, dy * j))
            return pairs
        for i in range(1, count + 1):
            if kind == "linear":
                t = _translation(dx * i, dy * i)
            else:
                a = angle * i
                rot = np.array([[math.cos(a), -math.sin(a), 0, 0], [math.sin(a), math.cos(a), 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
                t = _translation(cx, cy) @ rot @ _translation(-cx, -cy)
            pairs += _copies(elements, t)
        return pairs

    return _run_copy(elements, make)


# ---------------------------------------------------------------- mirror

def _annotations():
    from . import annotations

    return annotations


def _stairs():
    from . import stairs

    return stairs


def _reflection(x1, y1, x2, y2):
    """2D reflection across the line through (x1, y1)-(x2, y2), as a function on (x, y) metres and
    on directions."""
    d = np.array([x2 - x1, y2 - y1], dtype=float)
    d /= np.linalg.norm(d)
    o = np.array([x1, y1], dtype=float)

    def point(p):
        v = np.asarray(p[:2], dtype=float) - o
        return o + 2 * np.dot(v, d) * d - v

    def direction(v):
        v = np.asarray(v[:2], dtype=float)
        return 2 * np.dot(v, d) * d - v

    return point, direction


def _mirror_placement(e, point, direction):
    """Reflect an element's position and heading (it stays upright and right-handed; its own shape is
    not reflected — fine for symmetric profiles such as columns and beams)."""
    s = A._scale()
    m = ifcopenshell.util.placement.get_local_placement(e.ObjectPlacement)
    origin = point(m[:2, 3] * s) / s
    x = direction(m[:2, 0])
    matrix = np.eye(4)
    matrix[:2, 0] = x
    matrix[:2, 1] = [-x[1], x[0]]
    matrix[:2, 3] = origin
    matrix[2, 3] = m[2, 3]
    ifcopenshell.api.geometry.edit_object_placement(B._model, product=e, matrix=matrix, is_si=False)


def _flip_hand(door):
    """A mirrored door swings the other way: LEFT <-> RIGHT in its operation type."""
    op = getattr(door, "OperationType", None)
    if not op or op == "NOTDEFINED":
        door_type = ifcopenshell.util.element.get_type(door)
        op = getattr(door_type, "OperationType", None) or "SINGLE_SWING_LEFT"
    flipped = op.replace("LEFT", "\0").replace("RIGHT", "LEFT").replace("\0", "RIGHT")
    if flipped != op and hasattr(door, "OperationType"):
        door.OperationType = flipped


def _mirror(elements, point, direction):
    """Inside an action: mirror elements in place (GlobalIds kept). Walls are reversed so their
    layers land on the mirrored side; their doors/windows move to the mirrored spot (and swing the
    other way); slab outlines are reflected; other elements get a reflected position and heading.
    Returns the other elements it changed: the moved doors/windows and the walls that lost a join."""
    f = B._model
    walls = [e for e in elements if e.is_a("IfcWall") and A._axis_world(e) is not None]
    # Openings first read in the original walls (their distance from the wall start).
    hosted = []
    for w in walls:
        length = float(np.linalg.norm(np.subtract(*A._axis_world(w))))
        for rel in getattr(w, "HasOpenings", ()) or ():
            for fill in getattr(rel.RelatedOpeningElement, "HasFillings", ()) or ():
                info = A._opening_info(fill.RelatedBuildingElement)
                if info is not None:
                    hosted.append((fill.RelatedBuildingElement, w, length, info))
    released = []
    for w in walls:
        p1, p2 = A._axis_world(w)
        # Joins to walls that are not mirrored are dropped (they would no longer meet); those walls
        # lose their corner, so they are rebuilt below.
        for rel in list(getattr(w, "ConnectedTo", ()) or ()) + list(getattr(w, "ConnectedFrom", ()) or ()):
            if rel.is_a("IfcRelConnectsPathElements"):
                other = rel.RelatedElement if rel.RelatingElement == w else rel.RelatingElement
                if other not in walls:
                    f.remove(rel)
                    if other.is_a("IfcWall") and other not in released:
                        released.append(other)
        A._reaxis(w, point(p2), point(p1))  # reversed: start <-> end
    for w in walls:  # joins between mirrored walls: their ends swapped
        for rel in getattr(w, "ConnectedTo", ()) or ():
            if rel.is_a("IfcRelConnectsPathElements"):
                swap = {"ATSTART": "ATEND", "ATEND": "ATSTART"}
                rel.RelatingConnectionType = swap.get(rel.RelatingConnectionType, rel.RelatingConnectionType)
                rel.RelatedConnectionType = swap.get(rel.RelatedConnectionType, rel.RelatedConnectionType)
    for w in walls + released:
        if A._layer_set(w) is not None:
            A._regenerate(f, w)
    for element, wall, length, (opening, _, along, width, height, sill) in hosted:
        A._apply_opening_edit(element, opening, wall, length - along, width, height, sill)
        if element.is_a("IfcDoor"):
            _flip_hand(element)
    for e in elements:
        if e in walls:
            continue
        if e.is_a("IfcSlab") and _slab_outline_world(e):
            outline = [point(p) for p in _slab_outline_world(e)]
            _set_slab_outline(e, list(reversed(outline)))
        elif e.is_a("IfcAnnotation") and _annotations().mirror(e, point):
            pass  # plan annotations and drafting shapes: their points reflected (text stays readable)
        elif _stairs().mirror(e, point, direction):
            pass  # D88: stairs and ramps turn the other way, railings' paths are reflected
        else:
            _mirror_placement(e, point, direction)
    return [h[0] for h in hosted] + released


def mirror_elements(guids_json: str, x1, y1, x2, y2, copy=False) -> str:
    """Mirror across the line (x1, y1)-(x2, y2) (metres). `copy`: mirror a copy and keep the
    originals (Archicad: Ctrl while mirroring)."""
    if B._model is None:
        return A._fail("no model open")
    elements, error = _check(guids_json)
    if error:
        return error
    try:
        x1, y1, x2, y2 = float(x1), float(y1), float(x2), float(y2)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    if math.hypot(x2 - x1, y2 - y1) < 1e-9:
        return A._fail("the mirror line needs two different points")
    point, direction = _reflection(x1, y1, x2, y2)
    copy = A._truthy(copy)
    made = {}

    def action():
        if copy:
            pairs = _copies(elements, np.eye(4))
            targets = [c for e, c in pairs if e in elements]
            made["copies"] = [c.GlobalId for c in targets]
        else:
            targets = list(elements)
            made["copies"] = []
        fills = _mirror(targets, point, direction)
        changed = [t.GlobalId for t in targets] + [x.GlobalId for x in fills]
        for w in targets:  # walls joined to mirrored ones were re-shaped too
            changed += [n.GlobalId for n in A._connected_walls(w)] if w.is_a("IfcWall") else []
        return len(targets), list(dict.fromkeys(changed)), []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guids": made["copies"]})


# ---------------------------------------------------------------- slabs: outlines

def _slab_solid(slab):
    body = ifcopenshell.util.representation.get_representation(slab, "Model", "Body", "MODEL_VIEW")
    for item in (body.Items if body is not None else ()):
        if item.is_a("IfcExtrudedAreaSolid") and item.SweptArea.is_a("IfcArbitraryClosedProfileDef"):
            return item
    return None


def _curve_points(curve):
    if curve.is_a("IfcPolyline"):
        return [tuple(float(c) for c in p.Coordinates[:2]) for p in curve.Points]
    if curve.is_a("IfcIndexedPolyCurve"):
        return [tuple(float(c) for c in p[:2]) for p in curve.Points.CoordList]
    return []


SLAB_PSET = "KIMBIM_Slab"  # Points (world metres) and Bulges (D218)


def _slab_control_outline(slab) -> tuple[list, list]:
    """(points, bulges) of a slab's editable outline: the pset's control points, or the body's
    outline (no bulges) for a slab made before D218."""
    pset = ifcopenshell.util.element.get_pset(slab, SLAB_PSET) or {}
    raw = pset.get("Points")
    if raw:
        try:
            pts = [(float(p[0]), float(p[1])) for p in json.loads(raw)]
        except (TypeError, ValueError, IndexError):
            pts = []
        if len(pts) >= 3:
            bulges = []
            try:
                values = json.loads(pset.get("Bulges") or "[]")
                if isinstance(values, list) and len(values) == len(pts):
                    bulges = [float(v) for v in values]
            except (TypeError, ValueError):
                bulges = []
            # Only a curved outline is authoritative here: straight slabs keep their body's outline,
            # so mirror, offset, fillet and resize keep working without a second copy to update.
            if bulges and any(abs(b) > 1e-9 for b in bulges):
                return pts, bulges
    return _body_slab_outline(slab), []


def _body_slab_outline(slab):
    """A slab's body outline in world metres (closing point dropped), or [] if it has no simple profile."""
    solid = _slab_solid(slab)
    if solid is None:
        return []
    s = A._scale()
    pts = _curve_points(solid.SweptArea.OuterCurve)
    if len(pts) > 1 and np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    m = ifcopenshell.util.placement.get_local_placement(slab.ObjectPlacement)
    position = ifcopenshell.util.placement.get_axis2placement(solid.Position) if solid.Position else np.eye(4)
    full = m @ position
    return [tuple((full @ np.array([x, y, 0.0, 1.0]))[:2] * s) for x, y in pts]


def _slab_outline_world(slab):
    """A slab's outline with curved edges tessellated, in world metres (closing point dropped)."""
    from . import drafting

    pts, bulges = _slab_control_outline(slab)
    if not pts:
        return []
    if bulges and any(abs(b) > 1e-9 for b in bulges):
        poly = drafting.bulge_points(pts, bulges, True)
        return poly[:-1] if len(poly) > 1 else poly
    return pts


def _set_slab_outline(slab, outline):
    """Inside an action: rebuild a slab's body with a new outline (world metres), same thickness."""
    f = B._model
    s = A._scale()
    m = ifcopenshell.util.placement.get_local_placement(slab.ObjectPlacement)
    inverse = np.linalg.inv(m)
    local = [tuple((inverse @ np.array([x / s, y / s, 0.0, 1.0]))[:2] * s) for x, y in outline]
    solid = _slab_solid(slab)
    depth = float(solid.Depth) * s if solid is not None else 0.2
    representation = ifcopenshell.api.geometry.add_slab_representation(
        f, context=A._body_context(), depth=depth, polyline=local)
    A._replace_body(slab, representation)


def slab_outlines(storey_guid: str) -> str:
    """[{guid, points, bulges}]: the control outlines of a level's slabs (world metres), for editing
    their corners and curved edges (D218)."""
    storey = A._by_guid(storey_guid) if B._model is not None else None
    out = []
    for e in (A._contained(storey) if storey is not None else ()):
        if e.is_a("IfcSlab"):
            pts, bulges = _slab_control_outline(e)
            if pts:
                out.append({"guid": e.GlobalId,
                            "points": [[round(x, 6), round(y, 6)] for x, y in pts],
                            "bulges": [round(b, 9) for b in bulges]})
    return B._dump({"slabs": out})


def set_slab_outline(guid: str, points_json: str, bulges_json: str = "") -> str:
    """A slab's outline from new control points (world metres, D98: a corner moved, added or deleted)
    and optional bulges (one per edge, so an edge may be an arc; D218), its thickness and level kept
    (one undo step). At least three points, not crossing itself."""
    from . import drafting

    slab = A._by_guid(guid) if B._model is not None else None
    if slab is None or not slab.is_a("IfcSlab") or not _slab_outline_world(slab):
        return A._fail("not a slab with an outline")
    try:
        points = [(float(x), float(y)) for x, y in json.loads(points_json)]
        bulges = [float(b) for b in json.loads(bulges_json)] if bulges_json else []
    except (TypeError, ValueError) as ex:
        return A._fail(f"bad points: {ex}")
    if len(points) < 3:
        return A._fail("a slab needs at least three corners")
    if not drafting.is_simple(points) or abs(drafting.area(points)) < 1e-6:
        return A._fail("the outline would cross itself")
    if bulges and len(bulges) != len(points):
        return A._fail("a bulge for each edge")
    edges = bulges or [0.0] * len(points)
    tessellated = drafting.bulge_points(points, edges, True)
    if len(tessellated) > 1 and np.allclose(tessellated[0], tessellated[-1]):
        tessellated = tessellated[:-1]
    if not drafting.is_simple(tessellated) or abs(drafting.area(tessellated)) < 1e-6:
        return A._fail("the curved outline would cross itself")

    def action():
        f = B._model
        pset = ifcopenshell.util.element.get_pset(slab, SLAB_PSET)
        pset = f.by_id(pset["id"]) if pset else ifcopenshell.api.pset.add_pset(f, product=slab, name=SLAB_PSET)
        ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={
            "Points": json.dumps([[round(x, 6), round(y, 6)] for x, y in points], separators=(",", ":")),
            "Bulges": json.dumps([round(b, 9) for b in edges], separators=(",", ":"))})
        _set_slab_outline(slab, tessellated)
        return 1, [slab.GlobalId], []

    return B._dump(B._run(action))


def slab_outline(guid: str) -> str:
    slab = A._by_guid(guid) if B._model is not None else None
    if slab is None or not slab.is_a("IfcSlab"):
        return A._fail("not a slab")
    return B._dump({"ok": True, "points": [[round(x, 6), round(y, 6)] for x, y in _slab_outline_world(slab)]})


def _offset_polygon(points, distance):
    """Offset a simple polygon's edges outwards by `distance` (inwards if negative), mitred corners."""
    pts = [np.array(p, dtype=float) for p in points]
    n = len(pts)
    area = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n)) / 2
    sign = 1.0 if area > 0 else -1.0  # counter-clockwise: outwards is to the right of each edge
    lines = []
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        d = (b - a) / np.linalg.norm(b - a)
        normal = np.array([d[1], -d[0]]) * sign
        lines.append((a + normal * distance, d))
    out = []
    for i in range(n):
        (p, u), (q, v) = lines[i - 1], lines[i]
        den = u[0] * v[1] - u[1] * v[0]
        if abs(den) < 1e-12:
            out.append(tuple(q))
            continue
        t = ((q[0] - p[0]) * v[1] - (q[1] - p[1]) * v[0]) / den
        out.append(tuple(p + u * t))
    return out


FILLET_STEP_DEGREES = 10.0  # a fillet's arc as segments of at most this angle


def round_corners(points, closed: bool, size: float, mode: str = "fillet"):
    """Archicad's Fillet/Chamfer: every corner of a polyline (both ends kept when open) rounded with an
    arc of radius `size` (segments) or cut `size` back along each edge. A corner whose edges are too
    short takes the largest size that fits (half of each edge); straight corners are left alone."""
    pts = [np.array(p, dtype=float) for p in points]
    n = len(pts)
    out = []
    for i in range(n):
        if not closed and (i == 0 or i == n - 1):
            out.append(tuple(pts[i]))
            continue
        p, a, b = pts[i], pts[i - 1], pts[(i + 1) % n]
        la, lb = np.linalg.norm(a - p), np.linalg.norm(b - p)
        if la < 1e-9 or lb < 1e-9:
            out.append(tuple(p))
            continue
        u, v = (a - p) / la, (b - p) / lb
        turn = math.acos(max(-1.0, min(1.0, float(u @ v))))  # the corner's inside angle
        if turn > math.pi - 1e-6 or turn < 1e-6:
            out.append(tuple(p))
            continue
        if mode == "chamfer":
            t = min(size, la / 2, lb / 2)
            out += [tuple(p + u * t), tuple(p + v * t)]
            continue
        t = min(size / math.tan(turn / 2), la / 2, lb / 2)  # the tangent points' distance from the corner
        r = t * math.tan(turn / 2)
        bis = (u + v) / np.linalg.norm(u + v)
        centre = p + bis * (r / math.sin(turn / 2))
        s0, s1 = p + u * t - centre, p + v * t - centre
        a0, a1 = math.atan2(s0[1], s0[0]), math.atan2(s1[1], s1[0])
        sweep = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi  # the short way round
        steps = max(1, math.ceil(abs(math.degrees(sweep)) / FILLET_STEP_DEGREES))
        out += [tuple(centre + r * np.array([math.cos(a0 + sweep * k / steps), math.sin(a0 + sweep * k / steps)]))
                for k in range(steps + 1)]
    return [(round(float(x), 6), round(float(y), 6)) for x, y in out]


def _wall_corner(w1, w2):
    """Where two straight walls' axes meet: (corner, u, v, end1, end2), u and v pointing from the corner
    along each wall, endN "start" or "end" (the end at the corner); None when they are parallel."""
    (a1, b1), (a2, b2) = (tuple(np.array(p, dtype=float) for p in A._axis_world(w)) for w in (w1, w2))
    d1, d2 = b1 - a1, b2 - a2
    den = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(den) < 1e-9:
        return None
    t = ((a2[0] - a1[0]) * d2[1] - (a2[1] - a1[1]) * d2[0]) / den
    corner = a1 + d1 * t
    out = [corner]
    for a, b in ((a1, b1), (a2, b2)):
        near_end = np.linalg.norm(b - corner) < np.linalg.norm(a - corner)
        far = a if near_end else b
        out.append((far - corner) / np.linalg.norm(far - corner))
    ends = ["end" if np.linalg.norm(b - corner) < np.linalg.norm(a - corner) else "start" for a, b in ((a1, b1), (a2, b2))]
    return out[0], out[1], out[2], ends[0], ends[1]


def _fillet_walls(w1, w2, size: float, mode: str) -> str:
    """Archicad's Fillet/Chamfer on two walls meeting at a corner: both pulled back from it and a
    curved wall tangent to both (fillet, radius `size` on the axes) or a straight one (chamfer, `size`
    back along each) between them, its layers continuing the first wall's (one undo step)."""
    from . import configure, curved_walls, layers, renovation

    corner = _wall_corner(w1, w2)
    if corner is None:
        return A._fail("the two walls are parallel: they have no corner")
    p, u, v, end1, end2 = corner
    turn = math.acos(max(-1.0, min(1.0, float(u @ v))))
    if turn < 1e-3 or turn > math.pi - 1e-3:
        return A._fail("the walls are in line: there is no corner to round")
    (a1, b1), (a2, b2) = (tuple(np.array(q, dtype=float) for q in A._axis_world(w)) for w in (w1, w2))
    room = min(np.linalg.norm((a1 if end1 == "end" else b1) - p), np.linalg.norm((a2 if end2 == "end" else b2) - p))
    t = size if mode == "chamfer" else size / math.tan(turn / 2)
    if t >= room - A.MIN_WALL_LENGTH:
        return A._fail(f"too big for these walls: at most {room * (1 if mode == 'chamfer' else math.tan(turn / 2)):.3f} m")
    q1, q2 = p + u * t, p + v * t
    storey = ifcopenshell.util.element.get_container(w1)
    wall_type = ifcopenshell.util.element.get_type(w1)
    height = A._wall_height(w1) or 3.0
    # walking w1 towards the corner, then on to w2: the new wall continues w1's faces
    usage = configure.usage_of(w1, reversed_=(end1 == "start"))
    made = {}

    def action():
        f = B._model
        for rel in list(A._path_joins(w1)):  # the corner's join goes; the walls now end at the new wall
            others = {rel.RelatingElement, rel.RelatedElement}
            if w2 in others:
                f.remove(rel)
        for w, end, q in ((w1, end1, q1), (w2, end2, q2)):
            a, b = (np.array(x, dtype=float) for x in A._axis_world(w))
            A._reaxis(w, q if end == "start" else a, b if end == "start" else q)
            A._regenerate(f, w, length=float(np.linalg.norm(b - a)), height=A._wall_height(w) or height)
        if mode == "chamfer":
            new = A._new_wall(storey, wall_type, q1, q2, height, usage_from=usage)
            for other, point in ((w1, q1), (w2, q2)):
                ifcopenshell.api.geometry.connect_wall(f, wall1=new, wall2=other, is_atpath=False)
            for w in (new, w1, w2):
                A._regenerate(f, w, length=float(np.linalg.norm(q2 - q1)), height=height)
        else:
            r = t * math.tan(turn / 2)
            bis = (u + v) / np.linalg.norm(u + v)
            centre = p + bis * (r / math.sin(turn / 2))
            through = centre - bis * r
            new = curved_walls.new_curved_wall(storey, wall_type, q1, q2, through, height, usage_from=usage)
        layers.assign_active(new)
        renovation.stamp_new(new)
        made["wall"] = new
        return 1, [w1.GlobalId, w2.GlobalId, new.GlobalId], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(str(ex) if isinstance(ex, ValueError) else f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["wall"].GlobalId})


def fillet_corners(guids_json: str, size, mode: str = "fillet") -> str:
    """Fillet or chamfer the corners of the selected slabs and 2D polylines and fills (one undo step)."""
    from . import annotations as N

    if B._model is None:
        return A._fail("no model open")
    if mode not in ("fillet", "chamfer"):
        return A._fail(f"unknown mode {mode}")
    try:
        size = float(size)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    if size <= 0:
        return A._fail("the radius or distance must be more than zero")
    walls = [e for e in B._elements(guids_json) if e.is_a("IfcWall")]
    pinned = A.locked(walls)
    if pinned:
        return A._fail(f"{len(pinned)} element(s) are locked")
    if walls:  # D97: two walls meeting at a corner: a curved (fillet) or straight (chamfer) wall between
        from . import curved_walls

        if len(walls) != 2:
            return A._fail("select the two walls of the corner")
        if (why := curved_walls.refusal(walls)) is not None:
            return A._fail(why)
        if any(A._axis_world(w) is None or A._layer_set(w) is None for w in walls):
            return A._fail("select two layered walls drawn by NicBim")
        return _fillet_walls(walls[0], walls[1], size, mode)
    slabs, shapes = [], []
    for e in B._elements(guids_json):
        if e.is_a("IfcSlab") and _slab_outline_world(e):
            slabs.append(e)
        elif e.is_a("IfcAnnotation"):
            data = N._read(e)
            if data and data[0] in ("polyline", "fill"):
                shapes.append((e, data[0] == "fill" or bool(N.extra_of(e).get("Closed"))))
    if not slabs and not shapes:
        return A._fail("select slabs, polylines or fills")
    pinned = A.locked([*slabs, *(e for e, _closed in shapes)])
    if pinned:
        return A._fail(f"{len(pinned)} element(s) are locked")

    def action():
        changed = []
        for slab in slabs:
            _set_slab_outline(slab, round_corners(_slab_outline_world(slab), True, size, mode))
            changed.append(slab.GlobalId)
        for a, closed in shapes:
            world = [(float(p[0]), float(p[1])) for p in N.world_points(a)]
            if closed and len(world) > 1 and np.allclose(world[0], world[-1]):
                world = world[:-1]
            N.replace_points(a, round_corners(world, closed, size, mode))
            changed.append(a.GlobalId)
        return len(changed), changed, []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump(r)


def offset_elements(guids_json: str, distance) -> str:
    """Offset (Archicad): walls get a parallel copy `distance` metres to the left of their axis
    (negative: to the right); slabs grow (shrink if negative) their outline in place."""
    if B._model is None:
        return A._fail("no model open")
    elements = [e for e in B._elements(guids_json) if e.is_a("IfcWall") or e.is_a("IfcSlab")]
    if not elements:
        return A._fail("select walls or slabs to offset")
    pinned = A.locked(elements)
    if pinned:
        return A._fail(f"{len(pinned)} element(s) are locked")
    try:
        distance = float(distance)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    if abs(distance) < 1e-9:
        return A._fail("the offset distance must not be zero")
    walls = [e for e in elements if e.is_a("IfcWall") and A._axis_world(e) is not None]
    slabs = [e for e in elements if e.is_a("IfcSlab") and _slab_outline_world(e)]
    made = {}

    def action():
        copies, changed = [], []
        for w in walls:
            (x1, y1), (x2, y2) = A._axis_world(w)
            length = math.hypot(x2 - x1, y2 - y1)
            nx, ny = -(y2 - y1) / length, (x2 - x1) / length
            pairs = A._copy_elements([w], ifcopenshell.util.element.get_container(w),
                                     _translation(nx * distance, ny * distance))
            copies += [c for e, c in pairs if e is w]
            changed += [c.GlobalId for _, c in pairs]
        for slab in slabs:
            outline = _offset_polygon(_slab_outline_world(slab), distance)
            _set_slab_outline(slab, outline)
            changed.append(slab.GlobalId)
        made["copies"] = [c.GlobalId for c in copies]
        return len(walls) + len(slabs), changed, []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guids": made["copies"]})


def _element_bounds(element):
    """(min, max) world points from the element's mesh; its placement point when it has no shape."""
    try:
        settings = ifcopenshell.geom.settings()
        settings.set("use-world-coords", True)
        shape = ifcopenshell.geom.create_shape(settings, element)
        verts = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
        if len(verts):
            return verts.min(axis=0), verts.max(axis=0)
    except Exception:  # noqa: BLE001 - an element without a mesh still has a placement
        pass
    if getattr(element, "ObjectPlacement", None) is None:
        return None
    matrix = ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement)
    point = matrix[:3, 3] * ifcopenshell.util.unit.calculate_unit_scale(element.file)
    return point, point


def align_elements(guids_json: str, axis: str, mode: str, reference_guid: str = "") -> str:
    """Align the selected elements on X, Y or Z at their min, max or center.

    The target is the combined bounds of the selection, or `reference_guid`'s bounds (that element
    stays put). Elements carried by another selected element (a door in a selected wall) are not moved
    twice. One undo step."""
    if B._model is None:
        return A._fail("no model open")
    axis = str(axis or "").lower()
    mode = str(mode or "").lower()
    if axis not in ("x", "y", "z") or mode not in ("min", "max", "center"):
        return A._fail("axis must be x, y or z and mode min, max or center")
    selected = [e for e in B._elements(json.dumps(guids_json) if isinstance(guids_json, list) else guids_json)
                if e.is_a("IfcProduct") and getattr(e, "ObjectPlacement", None) is not None]
    if not selected:
        return A._fail("select elements to align")
    pinned = A.locked(selected)
    if pinned:
        return A._fail(f"{len(pinned)} element(s) are locked")
    selected_set = set(selected)
    elements = []
    for e in selected:
        parent = A._placement_parent(e)
        if parent is not None and parent in selected_set:
            continue  # the parent's move carries it
        elements.append(e)
    bounds = {}
    for e in elements:
        b = _element_bounds(e)
        if b is not None:
            bounds[e] = b
    if not bounds:
        return A._fail("the selection has no geometry or placement")
    reference = None
    if reference_guid:
        reference = A._by_guid(reference_guid)
        if reference not in bounds:
            return A._fail("the reference is not a positioned element")
    index = {"x": 0, "y": 1, "z": 2}[axis]
    if reference is not None:
        lo, hi = bounds[reference]
        target = lo[index] if mode == "min" else hi[index] if mode == "max" else (lo[index] + hi[index]) / 2
    else:
        lows = [b[0][index] for b in bounds.values()]
        highs = [b[1][index] for b in bounds.values()]
        target = min(lows) if mode == "min" else max(highs) if mode == "max" \
            else (min(lows) + max(highs)) / 2
    deltas = {}
    for e, (lo, hi) in bounds.items():
        if e is reference:
            continue
        value = lo[index] if mode == "min" else hi[index] if mode == "max" else (lo[index] + hi[index]) / 2
        delta = target - value
        if abs(delta) > 1e-9:
            deltas[e] = delta
    if not deltas:
        return B._dump({"ok": True, "changed": [], "delta": 0.0})

    def action():
        scale = ifcopenshell.util.unit.calculate_unit_scale(B._model)
        for e, delta in deltas.items():
            matrix = ifcopenshell.util.placement.get_local_placement(e.ObjectPlacement).copy()
            matrix[:3, 3] *= scale
            matrix[index, 3] += delta
            ifcopenshell.api.geometry.edit_object_placement(B._model, product=e, matrix=matrix, is_si=True)
        return len(deltas), [e.GlobalId for e in deltas], []

    try:
        r = B._run(action)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "changed": [e.GlobalId for e in deltas], "delta": target})


def resize_elements(guids_json: str, cx, cy, factor) -> str:
    """Archicad's Resize: the selection scaled by `factor` about (cx, cy) in plan (metres). Walls,
    slabs and 2D shapes take the new lengths and outlines (thicknesses and heights stay); doors and
    windows keep their size, their place along the wall scaled; other elements move (one undo step)."""
    from . import annotations as N
    from . import curved_walls, drafting

    if B._model is None:
        return A._fail("no model open")
    picked = [e for e in B._elements(guids_json) if e.is_a("IfcProduct")]
    pinned = A.locked(picked)
    if pinned:
        return A._fail(f"{len(pinned)} element(s) are locked")
    try:
        k = float(factor)
        if str(cx).strip() == "" or str(cy).strip() == "":  # about the selection's middle
            pts = []
            for e in picked:
                if e.is_a("IfcWall") and A._axis_world(e) is not None:
                    pts += list(A._axis_world(e))
                elif getattr(e, "ObjectPlacement", None) is not None:
                    pts.append(tuple(ifcopenshell.util.placement.get_local_placement(e.ObjectPlacement)[:2, 3] * A._scale()))
            pts = np.array(pts, dtype=float) if pts else np.zeros((1, 2))
            c = (pts.min(axis=0) + pts.max(axis=0)) / 2
        else:
            c = np.array([float(cx), float(cy)])
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    if k <= 0 or abs(k - 1.0) < 1e-12:
        return A._fail("the factor must be more than 0 and not 1")
    hosted = {x for e in picked for x in A._hosted(e)}
    elements = [e for e in picked if e not in hosted]
    if not elements:
        return A._fail("select what to resize")
    scaled = lambda p: c + (np.asarray(p, dtype=float)[:2] - c) * k  # noqa: E731
    plans = []
    for e in elements:
        if e.is_a("IfcWall") and curved_walls.is_curved(e):
            plans.append(("curved", e, None))
        elif e.is_a("IfcWall") and A._axis_world(e) is not None and A._layer_set(e) is not None:
            a, b = (np.array(p, dtype=float) for p in A._axis_world(e))
            if np.linalg.norm(b - a) * k < A.MIN_WALL_LENGTH:
                return A._fail(f"{e.Name or 'a wall'} would have no length")
            plans.append(("wall", e, (scaled(a), scaled(b))))
        elif e.is_a("IfcSlab") and _slab_outline_world(e):
            plans.append(("slab", e, [tuple(scaled(p)) for p in _slab_outline_world(e)]))
        elif e.is_a("IfcAnnotation") and (data := N._read(e)) and data[0] in drafting.KINDS + ("dimension",):
            plans.append(("shape", e, [tuple(scaled(p)) for p in N.world_points(e)]))
        elif getattr(e, "ObjectPlacement", None) is not None:
            plans.append(("move", e, None))
    openings = {}
    for kind, e, _ in plans:
        if kind in ("wall", "curved"):
            openings[e] = [(fill, opening, along, width) + tuple(A._opening_info(fill)[4:])
                           for fill, opening, along, width in _fills(e)]

    def action():
        f = B._model
        s = A._scale()
        walls = []
        for kind, e, data in plans:
            if kind == "wall":
                A._reaxis(e, *data)
                walls.append(e)
            elif kind == "curved":
                m = ifcopenshell.util.placement.get_local_placement(e.ObjectPlacement)
                inverse = np.linalg.inv(m)
                local = []
                for x, y in curved_walls.arc_of(e):
                    w = (m @ np.array([x / s, y / s, 0.0, 1.0]))[:2] * s
                    w = scaled(w)
                    local.append(list((inverse @ np.array([w[0] / s, w[1] / s, 0.0, 1.0]))[:2] * s))
                from . import configure

                configure._write_pset(e, curved_walls.WALL_PSET, {"Arc": json.dumps(local)})
                walls.append(e)
            elif kind == "slab":
                _set_slab_outline(e, data)
            elif kind == "shape":
                N.replace_points(e, data)
                read = N._read(e)
                if read[0] == "dimension":  # it measures again
                    origin = data[0]
                    local = [(x - origin[0], y - origin[1]) for x, y in data]
                    text = N._measure(local)
                    N._set(e, read[0], text, local, read[3], read[4])
                    e.Name = text[:60]
            else:
                m = ifcopenshell.util.placement.get_local_placement(e.ObjectPlacement)
                moved = m.copy()
                moved[:2, 3] = scaled(m[:2, 3] * s) / s
                ifcopenshell.api.geometry.edit_object_placement(f, product=e, matrix=moved, is_si=False,
                                                                should_transform_children=True)
        for w in walls:
            A._regenerate(f, w, length=A._wall_length(w), height=A._wall_height(w) or 3.0)
        for w in walls:
            for fill, opening, along, width, height, sill in openings.get(w, ()):
                along = min(max(along * k, width / 2), A._wall_length(w) - width / 2)
                A._apply_opening_edit(fill, opening, w, along, width, height, sill)
        return len(plans), [e.GlobalId for _, e, _ in plans] + [x.GlobalId for e in walls for x in A._hosted(e)
                                                               if not x.is_a("IfcOpeningElement")], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(str(ex) if isinstance(ex, ValueError) else f"{type(ex).__name__}: {ex}")
    return B._dump(r)


def _fills(wall):
    """(door/window, opening, along, width) in a wall."""
    out = []
    for rel in getattr(wall, "HasOpenings", ()) or ():
        opening = rel.RelatedOpeningElement
        for fill in getattr(opening, "HasFillings", ()) or ():
            info = A._opening_info(fill.RelatedBuildingElement)
            if info is not None:
                out.append((fill.RelatedBuildingElement, opening, info[2], info[3]))
    return out
