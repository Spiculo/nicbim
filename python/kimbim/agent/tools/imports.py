# SPDX-License-Identifier: GPL-3.0-or-later
"""Mesh import tools (D102, D124): read OBJ, STL, PLY, COLLADA, glTF/GLB and FBX files as one proxy
element on a level. The path is a local file; scale is a factor, rotation is degrees about Z and position
is [x, y, z] in project units or strings with units. The bridge takes world metres."""
from __future__ import annotations

import json

from ... import meshimport as M
from ... import pointcloud as P
from ..catalogue import AgentError, bridge, tool
from .common import lengths, level_guid

_NUMBER = {"type": "number", "description": "A number in the file's units."}


def _number(value, name: str) -> float:
    if isinstance(value, bool):
        raise AgentError("bad_input", hint=f"{name} must be a number")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise AgentError("bad_input", hint=f"{name} must be a number") from None


@tool("import.formats", {})
def formats(session):
    """List the mesh file formats the importer reads (OBJ, STL, PLY, COLLADA, glTF/GLB and FBX)."""
    return {"formats": bridge(M.mesh_formats)["formats"]}


@tool("import.mesh", {"required": ["path"], "properties": {
    "path": {"type": "string", "description": "Path of the .obj, .stl, .ply, .dae, .gltf, .glb or .fbx file."},
    "level": {"type": "string", "description": "Level name or GlobalId (default the first level)."},
    "name": {"type": "string", "description": "Object name (default the file name)."},
    "scale": {**_NUMBER, "description": "Uniform scale factor (default 1)."},
    "rotation": {**_NUMBER, "description": "Rotation about Z, in degrees (default 0)."},
    "position": {"type": "array", "items": {"type": ["number", "string"]},
                 "description": "[x, y, z] in project units or strings with units (default the origin)."}}},
    writes=True)
def mesh(session, path, level="", name="", scale=1.0, rotation=0.0, position=None):
    """Import a mesh (OBJ, STL, PLY, COLLADA, glTF/GLB or FBX) as a proxy on a level, scaled,
    rotated about Z and moved."""
    storey = level_guid(level) if level else ""
    options = {"scale": _number(scale, "scale"), "rotation": _number(rotation, "rotation")}
    if name:
        options["name"] = str(name)
    if position is not None:
        if not isinstance(position, (list, tuple)) or len(position) != 3:
            raise AgentError("bad_input", hint="position must be [x, y, z]")
        options["x"], options["y"], options["z"] = lengths(session, *position)
    r = bridge(M.import_mesh, str(path), storey, json.dumps(options))
    return {"guids": [r["guid"]], "name": r["name"], "format": r["format"],
            "triangles": r["triangles"], "bounds_m": r["bounds"]}


@tool("import.pointcloud_formats", {})
def pointcloud_formats(session):
    """List the point-cloud file formats the importer reads (XYZ, PTS, CSV/TXT, LAS and LAZ)."""
    return {"formats": bridge(P.pointcloud_formats)["formats"]}


@tool("import.pointcloud", {"required": ["path"], "properties": {
    "path": {"type": "string", "description": "Path of the .xyz, .pts, .csv, .txt, .las or .laz file."},
    "level": {"type": "string", "description": "Level name or GlobalId (default the first level)."},
    "name": {"type": "string", "description": "Object name (default the file name)."},
    "scale": {**_NUMBER, "description": "Uniform scale factor from the file's units to metres (default 1)."},
    "rotation": {**_NUMBER, "description": "Rotation about Z, in degrees (default 0)."},
    "position": {"type": "array", "items": {"type": ["number", "string"]},
                 "description": "[x, y, z] in project units or strings with units (default the origin)."},
    "max_points": {"type": "integer", "description": "Keep at most this many points (default 20000)."},
    "marker": {"type": ["number", "string"],
               "description": "Marker size (default 3cm); each point becomes a small tetrahedron."}}},
    writes=True)
def pointcloud(session, path, level="", name="", scale=1.0, rotation=0.0, position=None,
               max_points=20000, marker="3cm"):
    """Import a point cloud as a visible proxy on a level, decimated to a marker per point."""
    storey = level_guid(level) if level else ""
    options = {"scale": _number(scale, "scale"), "rotation": _number(rotation, "rotation"),
               "max_points": int(max_points), "marker": lengths(session, marker)[0]}
    if name:
        options["name"] = str(name)
    if position is not None:
        if not isinstance(position, (list, tuple)) or len(position) != 3:
            raise AgentError("bad_input", hint="position must be [x, y, z]")
        options["x"], options["y"], options["z"] = lengths(session, *position)
    r = bridge(P.import_pointcloud, str(path), storey, json.dumps(options))
    return {"guids": [r["guid"]], "name": r["name"], "format": r["format"],
            "points": r["points"], "imported": r["imported"], "triangles": r["triangles"],
            "bounds_m": r["bounds"]}
