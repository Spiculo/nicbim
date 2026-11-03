# SPDX-License-Identifier: GPL-3.0-or-later
"""Generic mesh import (SketchUp, Rhino, OBJ, STL, PLY, COLLADA, glTF and ASCII FBX): a triangulated
object from a mesh file.

The file is parsed here (no extra dependency), polygons are fanned into triangles, COLLADA/glTF node
transforms are applied and glTF's Y-up is turned into IFC's Z-up, then the points are scaled, rotated
about Z and translated into world metres. The object is one `IfcBuildingElementProxy` (ObjectType
"Imported mesh", IFC4 and IFC2X3) with a tessellated body: IFC4 `IfcTriangulatedFaceSet`, IFC2X3
`IfcShellBasedSurfaceModel` (through terrain._representation). It is contained in a level and carries
`KIMBIM_MeshImport`:

    Source, Format (obj/stl/ply/dae/gltf/glb/fbx), Triangles, Scale, Rotation, Bounds (JSON)

Same protocol as app_bridge: strings in, JSON out, never raise.
"""
from __future__ import annotations

import base64
import json
import math
import pathlib
import re
import struct
import xml.etree.ElementTree as ET

import ifcopenshell.api.geometry
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import numpy as np

from . import app_bridge as B
from . import authoring as A
from . import terrain

PSET = "KIMBIM_MeshImport"
OBJECT_TYPE = "Imported mesh"
FORMATS = ("obj", "stl", "ply", "dae", "gltf", "glb", "fbx")

_FLOAT = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


# ---------------------------------------------------------------- options and transform

def _options(options_json: str) -> dict:
    if not options_json:
        return {}
    data = json.loads(options_json)
    if not isinstance(data, dict):
        raise ValueError("options must be an object")
    return data


def _number(value, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number") from None


def _transform(options: dict) -> dict:
    """The import placement: x, y, z (metres), rotation (degrees about Z), uniform scale."""
    out = {"x": 0.0, "y": 0.0, "z": 0.0, "rotation": 0.0, "scale": 1.0}
    for key in ("scale", "rotation", "x", "y", "z"):
        if options.get(key) is not None:
            out[key] = _number(options[key], key)
    if out["scale"] <= 0:
        raise ValueError("the scale must be positive")
    return out


def _apply(points, transform: dict) -> list[tuple[float, float, float]]:
    """Scale, rotate about Z and translate the file's points into world metres."""
    angle = math.radians(transform["rotation"])
    cos, sin = math.cos(angle), math.sin(angle)
    scale = transform["scale"]
    out = []
    for x, y, z in points:
        x, y, z = x * scale, y * scale, z * scale
        out.append((x * cos - y * sin + transform["x"],
                    x * sin + y * cos + transform["y"],
                    z + transform["z"]))
    return out


# ---------------------------------------------------------------- parsers

def _float(token: str, what: str) -> float:
    try:
        return float(token)
    except (TypeError, ValueError):
        raise ValueError(f"{what} is not a number: {token}") from None


def _index(token: str, count: int, what: str, base: int = 1) -> int:
    try:
        i = int(token)
    except (TypeError, ValueError):
        raise ValueError(f"{what} is not a whole number: {token}") from None
    if base == 1:  # OBJ is 1-based and its negative indices count from the end
        if i == 0:
            raise ValueError(f"{what} is zero")
        i = i - 1 if i > 0 else count + i
    if not 0 <= i < count:
        raise ValueError(f"{what} {token} is outside the vertex list")
    return i


def _fan(corners: list[int]) -> list[list[int]]:
    """A polygon as triangles around its first vertex."""
    return [[corners[0], corners[k], corners[k + 1]] for k in range(1, len(corners) - 1)]


def _triangles(vertices) -> tuple[list, list]:
    """Points and triangles from a flat run of triangle vertices (STL), merging repeated points."""
    points, index, faces = [], {}, []
    for start in range(0, len(vertices), 3):
        corners = []
        for point in vertices[start:start + 3]:
            key = (round(point[0], 9), round(point[1], 9), round(point[2], 9))
            if key not in index:
                index[key] = len(points)
                points.append(point)
            corners.append(index[key])
        faces.append(corners)
    return points, faces


def _obj(text: str) -> tuple[list, list]:
    points, faces = [], []
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        tag = parts[0].lower()
        if tag == "v":
            if len(parts) < 4:
                raise ValueError("an OBJ vertex needs three coordinates")
            points.append(tuple(_float(v, "an OBJ vertex coordinate") for v in parts[1:4]))
        elif tag == "f":
            corners = []
            for token in parts[1:]:
                corners.append(_index(token.split("/")[0], len(points), "an OBJ face index"))
            if len(corners) < 3:
                raise ValueError("an OBJ face needs at least three vertices")
            faces.extend(_fan(corners))
    return points, faces


def _stl_binary(data: bytes, count: int) -> tuple[list, list]:
    vertices = []
    for n in range(count):
        base = 84 + n * 50
        for k in range(3):
            x, y, z = struct.unpack_from("<3f", data, base + 12 + k * 12)
            vertices.append((float(x), float(y), float(z)))
    return _triangles(vertices)


def _stl_ascii(text: str) -> tuple[list, list]:
    vertices = []
    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0].lower() == "vertex":
            if len(parts) < 4:
                raise ValueError("an STL vertex needs three coordinates")
            vertices.append(tuple(_float(v, "an STL vertex coordinate") for v in parts[1:4]))
    if len(vertices) % 3:
        raise ValueError("the STL file does not hold whole facets")
    return _triangles(vertices)


def _stl(data: bytes) -> tuple[list, list]:
    if len(data) >= 84:
        count = struct.unpack_from("<I", data, 80)[0]
        if count and 84 + count * 50 == len(data):
            return _stl_binary(data, count)
    text = data.decode("utf-8", errors="replace")
    if "facet" not in text.lower() and len(data) >= 84:  # a binary file with trailing bytes
        count = struct.unpack_from("<I", data, 80)[0]
        if count and 84 + count * 50 <= len(data):
            return _stl_binary(data, count)
    return _stl_ascii(text)


def _ply(text: str) -> tuple[list, list]:
    lines = text.splitlines()
    if not lines or lines[0].strip().lower() != "ply":
        raise ValueError("not a PLY file")
    fmt, elements, cursor = None, [], 1
    ended = False
    while cursor < len(lines):
        line = lines[cursor].strip()
        cursor += 1
        if not line or line.startswith(("comment", "obj_info")):
            continue
        parts = line.split()
        if parts[0] == "format":
            fmt = parts[1].lower() if len(parts) > 1 else ""
        elif parts[0] == "element":
            if len(parts) < 3:
                raise ValueError("a PLY element needs a name and a count")
            elements.append({"name": parts[1].lower(),
                             "count": int(parts[2]), "properties": []})
        elif parts[0] == "property":
            if not elements:
                raise ValueError("a PLY property needs an element")
            elements[-1]["properties"].append(parts[1:])
        elif parts[0] == "end_header":
            ended = True
            break
    if not ended:
        raise ValueError("the PLY header has no end_header")
    if fmt != "ascii":
        raise ValueError(f"only ASCII PLY is supported (this file is {fmt or 'unknown'})")

    points, faces = [], []
    for element in elements:
        scalar = [p[1].lower() for p in element["properties"] if p and p[0] != "list"]
        vertex = element["name"] == "vertex"
        if vertex:
            missing = [axis for axis in ("x", "y", "z") if axis not in scalar]
            if missing:
                raise ValueError("the PLY vertices need x, y and z")
            axes = [scalar.index(axis) for axis in ("x", "y", "z")]
        for _ in range(element["count"]):
            while cursor < len(lines) and not lines[cursor].strip():
                cursor += 1
            if cursor >= len(lines):
                raise ValueError("the PLY file ends before its data")
            parts = lines[cursor].split()
            cursor += 1
            if vertex:
                if len(parts) < len(scalar):
                    raise ValueError("a PLY vertex has too few values")
                points.append(tuple(_float(parts[i], "a PLY vertex coordinate") for i in axes))
            elif element["name"] == "face":
                values = [int(v) for v in parts]
                n = values[0] if values else 0
                if n < 3 or len(values) < n + 1:
                    raise ValueError("a PLY face needs at least three vertices")
                corners = [_index(str(v), len(points), "a PLY face index", base=0)
                           for v in values[1:n + 1]]
                faces.extend(_fan(corners))
    return points, faces


# ---------------------------------------------------------------- COLLADA (.dae)

def _local(tag: str) -> str:
    """An XML tag without its namespace."""
    return tag.rsplit("}", 1)[-1]


def _mat(values, count: int = 16) -> np.ndarray:
    return np.array([float(v) for v in values], dtype=float).reshape(4, 4)


def _dae_transform(node) -> np.ndarray:
    """A COLLADA node's local matrix (matrix, or translate/rotate/scale)."""
    matrix = np.eye(4)
    for child in node:
        tag = _local(child.tag)
        text = (child.text or "").split()
        if tag == "matrix" and len(text) >= 16:
            matrix = matrix @ _mat(text[:16])
        elif tag == "translate" and len(text) >= 3:
            t = np.eye(4)
            t[:3, 3] = [float(v) for v in text[:3]]
            matrix = matrix @ t
        elif tag == "rotate" and len(text) >= 4:
            axis = np.array([float(v) for v in text[:3]], dtype=float)
            length = np.linalg.norm(axis)
            if not length:
                continue
            axis /= length
            angle = math.radians(float(text[3]))
            c, s = math.cos(angle), math.sin(angle)
            r = np.eye(4)
            x, y, z = axis
            r[:3, :3] = [[c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
                         [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
                         [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)]]
            matrix = matrix @ r
        elif tag == "scale" and len(text) >= 3:
            s = np.diag([float(v) for v in text[:3]] + [1.0])
            matrix = matrix @ s
    return matrix


def _dae_points(points: list, faces: list, positions, groups: list, world: np.ndarray) -> None:
    """Append one primitive's positions and triangles, transformed by `world`."""
    base = len(points)
    for x, y, z in positions:
        points.append(tuple(world @ np.array([x, y, z, 1.0]))[:3])
    for corners in groups:
        faces.append([base + corners[k] for k in range(len(corners))])


def _dae_primitive(el, sources, vertices, points, faces, world) -> None:
    inputs = [(i.get("semantic"), (i.get("source") or "").lstrip("#"), int(i.get("offset", "0")))
              for i in el if _local(i.tag) == "input"]
    vertex = next((i for i in inputs if i[0] == "VERTEX"), None)
    if vertex is None:
        return
    source = vertices.get(vertex[1]) or sources.get(vertex[1])
    if not source:
        return
    stride = max((i[2] for i in inputs), default=0) + 1
    p = next((c for c in el if _local(c.tag) == "p"), None)
    if p is None:
        return
    values = [int(v) for v in (p.text or "").split()]
    off = vertex[2]
    tag = _local(el.tag)
    groups = []
    if tag == "triangles":
        for start in range(0, len(values) - stride * 3 + 1, stride * 3):
            groups.append([values[start + off], values[start + stride + off], values[start + 2 * stride + off]])
    elif tag == "polylist":
        counts = next((c for c in el if _local(c.tag) == "vcount"), None)
        cursor = 0
        for count in [int(v) for v in (counts.text or "").split()] if counts is not None else []:
            corners = [values[cursor + k * stride + off] for k in range(count)]
            cursor += count * stride
            groups.extend(_fan(corners))
    elif tag in ("trifans", "tristrips"):
        count = len(values) // stride
        corners = [values[k * stride + off] for k in range(count)]
        if tag == "trifans":
            groups.extend(_fan(corners))
        else:
            for k in range(len(corners) - 2):
                groups.append([corners[k], corners[k + 1], corners[k + 2]] if k % 2 == 0
                              else [corners[k + 1], corners[k], corners[k + 2]])
    if not groups:
        return
    limit = len(source)
    if any(i < 0 or i >= limit for group in groups for i in group):
        raise ValueError("a COLLADA face index is outside its vertex list")
    _dae_points(points, faces, source, groups, world)


def _dae(text: str) -> tuple[list, list]:
    """COLLADA 1.4/1.5 meshes: positions, triangles/polylists/fans/strips and the node transforms."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as ex:
        raise ValueError(f"not a COLLADA file: {ex}") from None
    sources, vertices, geometries = {}, {}, {}
    for el in root.iter():
        tag = _local(el.tag)
        if tag != "source":
            continue
        source_id = el.get("id")
        array = next((c for c in el if _local(c.tag) == "float_array"), None)
        if not source_id or array is None:
            continue
        stride = next((int(a.get("stride", "3")) for a in el.iter() if _local(a.tag) == "accessor"), 3)
        values = [float(v) for v in (array.text or "").split()]
        sources[source_id] = [tuple(values[k:k + 3])
                              for k in range(0, len(values) - stride + 1, stride)]
    for el in root.iter():
        tag = _local(el.tag)
        if tag == "vertices" and el.get("id"):
            position = next((i for i in el if _local(i.tag) == "input"
                             and i.get("semantic") == "POSITION"), None)
            if position is not None:
                vertices[el.get("id")] = sources.get((position.get("source") or "").lstrip("#"))
        elif tag == "geometry" and el.get("id"):
            mesh = next((c for c in el if _local(c.tag) == "mesh"), None)
            if mesh is not None:
                geometries[el.get("id")] = mesh
    points, faces = [], []
    if not geometries:
        raise ValueError("the COLLADA file has no mesh geometry")

    def mesh_triangles(mesh, world):
        for primitive in mesh:
            if _local(primitive.tag) in ("triangles", "polylist", "trifans", "tristrips"):
                _dae_primitive(primitive, sources, vertices, points, faces, world)

    def walk(node, parent):
        world = parent @ _dae_transform(node)
        for child in node:
            tag = _local(child.tag)
            if tag == "instance_geometry":
                mesh = geometries.get((child.get("url") or "").lstrip("#"))
                if mesh is not None:
                    mesh_triangles(mesh, world)
            elif tag == "instance_node":
                for candidate in root.iter():
                    if _local(candidate.tag) == "node" and candidate.get("id") == (child.get("url") or "").lstrip("#"):
                        walk(candidate, world)
            elif tag == "node":
                walk(child, world)

    scenes = [el for el in root.iter() if _local(el.tag) == "visual_scene"]
    if scenes:
        for scene in scenes:
            for node in scene:
                if _local(node.tag) == "node":
                    walk(node, np.eye(4))
    else:  # no scene: every node or, failing that, every geometry at the origin
        nodes = [el for el in root.iter() if _local(el.tag) == "node"]
        if nodes:
            for node in nodes:
                walk(node, np.eye(4))
        else:
            for mesh in geometries.values():
                mesh_triangles(mesh, np.eye(4))
    if not faces:
        raise ValueError("the COLLADA file has no triangles")
    return points, faces


# ---------------------------------------------------------------- glTF 2.0 (.gltf/.glb)

_GLTF_COMPONENT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16,
                   5125: np.uint32, 5126: np.float32}
_GLTF_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}


def _gltf_buffers(document: dict, path: str, binary: bytes | None) -> list[bytes]:
    out = []
    for k, buffer in enumerate(document.get("buffers") or []):
        uri = buffer.get("uri")
        if not uri:
            out.append(binary if k == 0 and binary is not None else b"")
        elif uri.startswith("data:"):
            out.append(base64.b64decode(uri.split(",", 1)[1]))
        else:
            out.append((pathlib.Path(path).parent / uri).read_bytes())
    return out


def _gltf_accessor(document: dict, buffers: list[bytes], index: int):
    accessor = document["accessors"][index]
    width = _GLTF_WIDTH[accessor["type"]]
    dtype = np.dtype(_GLTF_COMPONENT[accessor["componentType"]]).newbyteorder("<")
    view = document["bufferViews"][accessor["bufferView"]]
    data = buffers[view.get("buffer", 0)]
    offset = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    stride = view.get("byteStride") or dtype.itemsize * width
    count = accessor["count"]
    if stride == dtype.itemsize * width:
        return np.frombuffer(data, dtype=dtype, count=count * width, offset=offset).reshape(count, width)
    rows = [np.frombuffer(data, dtype=dtype, count=width, offset=offset + k * stride) for k in range(count)]
    return np.array(rows)


def _glb(data: bytes) -> tuple[dict, bytes | None]:
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError("not a GLB file")
    version, _length = struct.unpack_from("<II", data, 4)
    if version != 2:
        raise ValueError(f"only glTF 2.0 is supported (this file is glTF {version})")
    cursor, document, binary = 12, None, None
    while cursor + 8 <= len(data):
        length, kind = struct.unpack_from("<II", data, cursor)
        chunk = data[cursor + 8:cursor + 8 + length]
        if kind == 0x4E4F534A:
            document = json.loads(chunk.decode("utf-8-sig"))
        elif kind == 0x004E4942:
            binary = chunk
        cursor += 8 + length + (-length % 4)
    if document is None:
        raise ValueError("the GLB file has no JSON chunk")
    return document, binary


def _gltf_matrix(node: dict) -> np.ndarray:
    if "matrix" in node:
        return _mat(node["matrix"]).T  # glTF stores matrices column-major
    t = np.eye(4)
    t[:3, 3] = node.get("translation") or [0, 0, 0]
    r = np.eye(4)
    if "rotation" in node:
        x, y, z, w = node["rotation"]
        r[:3, :3] = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    s = np.diag([*(node.get("scale") or [1, 1, 1]), 1.0])
    return t @ r @ s


def _gltf(data: bytes, path: str) -> tuple[list, list]:
    """glTF 2.0 .gltf or .glb: indexed triangles from every mesh, with node transforms, Y-up to Z-up."""
    is_glb = data[:4] == b"glTF"
    if is_glb:
        document, binary = _glb(data)
    else:
        document, binary = json.loads(data.decode("utf-8-sig")), None
    if document.get("asset", {}).get("version", "2").split(".")[0] != "2":
        raise ValueError("only glTF 2.0 is supported")
    buffers = _gltf_buffers(document, path, binary)
    nodes = document.get("nodes") or []
    scene = (document.get("scenes") or [{}])[document.get("scene", 0)]
    world = {k: _gltf_matrix(n) for k, n in enumerate(nodes)}
    done = set()

    def place(k, parent):
        if k in done:
            return
        done.add(k)
        world[k] = parent @ world[k]
        for child in nodes[k].get("children") or []:
            place(child, world[k])

    for k in scene.get("nodes") or list(range(len(nodes))) if (scene or nodes) else []:
        if k < len(nodes):
            place(k, np.eye(4))

    # glTF is Y-up: (x, y, z) -> (x, -z, y) in IFC's Z-up world.
    up = np.array([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=float)
    points, faces = [], []
    for k, node in enumerate(nodes):
        mesh = document.get("meshes", [])[node["mesh"]] if "mesh" in node else None
        if mesh is None:
            continue
        matrix = up @ world[k]
        for primitive in mesh.get("primitives") or []:
            attributes = primitive.get("attributes") or {}
            if "POSITION" not in attributes:
                continue
            mode = primitive.get("mode", 4)
            if mode not in (4, 5, 6):
                continue  # points and lines are not triangles
            vertices = _gltf_accessor(document, buffers, attributes["POSITION"])
            if "indices" in primitive:
                indices = _gltf_accessor(document, buffers, primitive["indices"]).reshape(-1).tolist()
            else:
                indices = list(range(len(vertices)))
            base = len(points)
            for x, y, z in vertices[:, :3]:
                points.append(tuple(matrix @ np.array([float(x), float(y), float(z), 1.0]))[:3])
            if mode == 4:
                for start in range(0, len(indices) - 2, 3):
                    faces.append([base + int(indices[start]), base + int(indices[start + 1]),
                                  base + int(indices[start + 2])])
            elif mode == 5:
                for start in range(len(indices) - 2):
                    a, b, c = indices[start:start + 3]
                    faces.append([base + int(a), base + int(b), base + int(c)] if start % 2 == 0
                                 else [base + int(b), base + int(a), base + int(c)])
            else:
                for start in range(len(indices) - 2):
                    faces.append([base + int(indices[0]), base + int(indices[start + 1]),
                                  base + int(indices[start + 2])])
    if not faces:
        raise ValueError("the glTF file has no triangles")
    return points, faces


# ---------------------------------------------------------------- ASCII FBX

def _fbx_array(block: str, name: str) -> list[float]:
    match = re.search(rf"{name}\s*:\s*\*\d+\s*\{{(.*?)\}}", block, re.S)
    if match is None:
        return []
    body = re.sub(r"\ba\s*:", "", match.group(1))
    return [float(v) for v in re.split(r"[,\s]+", body.strip()) if v]


def _fbx(text: str) -> tuple[list, list]:
    """ASCII FBX: vertices and polygon indices (the binary format is refused with a clear message)."""
    if text[:23].startswith("Kaydara FBX Binary") or "\x00" in text[:200]:
        raise ValueError("binary FBX is not supported; export the model as ASCII FBX or glTF")
    lines = text.splitlines()
    points, faces = [], []
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("Geometry:"):
            continue
        depth, started, block = 0, False, []
        for current in lines[index:]:
            depth += current.count("{") - current.count("}")
            block.append(current)
            started = started or "{" in current
            if started and depth <= 0:
                break
        body = "\n".join(block)
        vertices = _fbx_array(body, "Vertices")
        indices = _fbx_array(body, "PolygonVertexIndex")
        if not vertices or not indices:
            continue
        base = len(points)
        points.extend(tuple(vertices[k:k + 3]) for k in range(0, len(vertices) - 2, 3))
        corners = []
        for value in indices:
            value = int(value)
            if value < 0:  # the last vertex of an FBX polygon is bitwise-noted
                corners.append(~value)
                if len(corners) >= 3 and max(corners) < len(points) - base:
                    faces.extend([[base + i for i in triangle] for triangle in _fan(corners)])
                corners = []
            else:
                corners.append(value)
    if not faces:
        raise ValueError("the FBX file has no polygon geometry")
    return points, faces


def _format(path: str) -> str:
    suffix = pathlib.Path(path).suffix.lower().lstrip(".")
    if suffix not in FORMATS:
        raise ValueError(f"unsupported mesh format: {suffix or 'none'} (expected {', '.join(FORMATS)})")
    return suffix


def _read(path: str) -> tuple[list, list, str]:
    """(points, triangles, format) from an OBJ, STL or PLY file, in the file's own units."""
    fmt = _format(path)
    source = pathlib.Path(path)
    if not source.is_file():
        raise ValueError(f"the mesh file does not exist: {path}")
    data = source.read_bytes()
    if not data.strip():
        raise ValueError("the mesh file is empty")
    try:
        if fmt == "obj":
            points, faces = _obj(data.decode("utf-8-sig", errors="replace"))
        elif fmt == "stl":
            points, faces = _stl(data)
        elif fmt == "ply":
            points, faces = _ply(data.decode("utf-8-sig", errors="replace"))
        elif fmt == "dae":
            points, faces = _dae(data.decode("utf-8-sig", errors="replace"))
        elif fmt in ("gltf", "glb"):
            points, faces = _gltf(data, path)
        else:
            points, faces = _fbx(data.decode("utf-8-sig", errors="replace"))
    except ValueError:
        raise
    except Exception as ex:  # noqa: BLE001 - a malformed file must never raise
        raise ValueError(f"{type(ex).__name__}: {ex}") from None
    if len(points) < 3 or not faces:
        raise ValueError("the mesh file has no triangles")
    return points, faces, fmt


# ---------------------------------------------------------------- the proxy

def _level(level_guid: str):
    """The level to contain the object: the given storey, or the first one."""
    if level_guid:
        storey = A._by_guid(level_guid)
        if storey is None or not storey.is_a("IfcBuildingStorey"):
            return None
        return storey
    storeys = sorted(B._model.by_type("IfcBuildingStorey"), key=lambda s: s.id())
    return storeys[0] if storeys else None


def _create(level, name: str, source: str, fmt: str, transform: dict, points, faces) -> str:
    made = {}

    def action():
        f = B._model
        element = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingElementProxy", name=name)
        element.ObjectType = OBJECT_TYPE
        ifcopenshell.api.spatial.assign_container(f, products=[element], relating_structure=level)
        ifcopenshell.api.geometry.edit_object_placement(f, product=element, matrix=np.eye(4), is_si=True)
        representation = terrain._representation(points, faces)
        ifcopenshell.api.geometry.assign_representation(f, product=element, representation=representation)
        pset = ifcopenshell.api.pset.add_pset(f, product=element, name=PSET)
        ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={
            "Source": source,
            "Format": fmt,
            "Triangles": len(faces),
            "Scale": float(transform["scale"]),
            "Rotation": float(transform["rotation"]),
            "Bounds": json.dumps(terrain._bounds(points), separators=(",", ":")),
        })
        made["guid"] = element.GlobalId
        return 1, [element.GlobalId], []

    B._run(action)
    return made["guid"]


# ---------------------------------------------------------------- public commands

def mesh_formats() -> str:
    """The mesh file formats the importer reads."""
    return B._dump({"ok": True, "formats": list(FORMATS)})


def import_mesh(path: str, level_guid: str = "", options_json: str = "") -> str:
    """Import a mesh file (OBJ, STL, PLY, COLLADA, glTF/GLB, ASCII FBX) as one proxy.
    Options: {name, scale, rotation, x, y, z}."""
    if B._model is None:
        return A._fail("no model open")
    if not isinstance(path, str) or not path.strip():
        return A._fail("no mesh file given")
    level = _level(level_guid)
    if level is None:
        return A._fail("unknown level")
    try:
        options = _options(options_json)
        transform = _transform(options)
        points, faces, fmt = _read(path)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    name = str(options.get("name") or "").strip() or pathlib.Path(path).stem or "Imported mesh"
    points = _apply(points, transform)
    try:
        guid = _create(level, name, str(pathlib.Path(path).resolve()), fmt, transform, points, faces)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({"ok": True, "guid": guid, "name": name, "triangles": len(faces),
                    "bounds": terrain._bounds(points), "format": fmt})
