# SPDX-License-Identifier: GPL-3.0-or-later
"""Point-cloud import (XYZ, PTS, CSV/TXT, LAS/LAZ and E57): a lightweight, visible scan.

IFC has no point-cloud entity, so the imported scan is one `IfcBuildingElementProxy` (ObjectType
"Imported point cloud") on a level with a tessellated body: each point becomes a small tetrahedron
marker (four triangles), decimated to `max_points` by a uniform stride so a scan stays usable in the
viewport and in drawings. The full point count and the file's bounds are kept in `KIMBIM_PointCloud`:

    Source, Format, Points, Imported, MarkerSize, Bounds (JSON)

LAZ (compressed LAS) is read through lazrs (MIT); E57 through the C++ `e57dump` bridge built on
libe57format (BSD-3). Same protocol as app_bridge: strings in, JSON out, never raise.
"""
from __future__ import annotations

import json
import math
import os
import pathlib
import struct
import subprocess

import ifcopenshell.api.geometry
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import numpy as np

from . import app_bridge as B
from . import authoring as A
from . import terrain

PSET = "KIMBIM_PointCloud"
OBJECT_TYPE = "Imported point cloud"
FORMATS = ("xyz", "pts", "csv", "txt", "las", "laz", "e57")
_DEFAULT_MAX = 20_000


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
    out = {"x": 0.0, "y": 0.0, "z": 0.0, "rotation": 0.0, "scale": 1.0}
    for key in ("scale", "rotation", "x", "y", "z"):
        if options.get(key) is not None:
            out[key] = _number(options[key], key)
    if out["scale"] <= 0:
        raise ValueError("the scale must be positive")
    return out


def _apply(points, transform: dict) -> list[tuple[float, float, float]]:
    angle = math.radians(transform["rotation"])
    cos, sin, scale = math.cos(angle), math.sin(angle), transform["scale"]
    out = []
    for x, y, z in points:
        x, y, z = x * scale, y * scale, z * scale
        out.append((x * cos - y * sin + transform["x"],
                    x * sin + y * cos + transform["y"],
                    z + transform["z"]))
    return out


# ---------------------------------------------------------------- parsers

def _rows(text: str) -> list[tuple[float, float, float]]:
    """XYZ / PTS / CSV text: the first three numbers of each data line (headers are skipped)."""
    points = []
    for line in text.splitlines():
        parts = line.replace(",", " ").replace(";", " ").split()
        if len(parts) == 1 and not points and parts[0].isdigit():
            continue  # PTS starts with the point count
        try:
            values = [float(v) for v in parts[:3]]
        except (TypeError, ValueError):
            continue
        if len(values) == 3:
            points.append(tuple(values))
    return points


def _las_header(data: bytes) -> dict:
    """The LAS 1.2-1.4 header, offset to the points and its LASzip VLR (if any)."""
    if data[:4] != b"LASF":
        raise ValueError("not a LAS file")
    if len(data) < 227:
        raise ValueError("the LAS header is truncated")
    header_size = struct.unpack_from("<H", data, 94)[0]
    offset = struct.unpack_from("<I", data, 96)[0]
    point_format = data[104] & 0x3F
    record_length = struct.unpack_from("<H", data, 105)[0]
    count = struct.unpack_from("<I", data, 107)[0]
    if count == 0 and len(data) >= 255:  # LAS 1.4's 64-bit count
        count = struct.unpack_from("<Q", data, 247)[0]
    sx, sy, sz = struct.unpack_from("<3d", data, 131)
    ox, oy, oz = struct.unpack_from("<3d", data, 155)
    vlr_data = None
    try:
        records = struct.unpack_from("<I", data, 100)[0]
        cursor = header_size
        for _ in range(records):
            user = data[cursor + 2:cursor + 18].split(b"\x00", 1)[0]
            record_id = struct.unpack_from("<H", data, cursor + 18)[0]
            length = struct.unpack_from("<H", data, cursor + 20)[0]
            payload = data[cursor + 54:cursor + 54 + length]
            if record_id == 22204 or user == b"laszip encoded":
                vlr_data = payload
            cursor += 54 + length
    except struct.error:
        raise ValueError("the LAS variable-length records are truncated") from None
    return {"header_size": header_size, "offset": offset, "point_format": point_format,
            "record_length": record_length, "count": count,
            "scale": (sx, sy, sz), "origin": (ox, oy, oz), "vlr": vlr_data}


def _las_records(data: bytes, header: dict) -> list[tuple[float, float, float]]:
    """Decode `count` LAS point records (X, Y, Z are the first three int32 fields)."""
    count, record_length = header["count"], header["record_length"]
    offset = header["offset"]
    if offset < header["header_size"] or not record_length or offset + count * record_length > len(data):
        raise ValueError("the LAS point records are truncated")
    sx, sy, sz = header["scale"]
    ox, oy, oz = header["origin"]
    points = []
    for k in range(count):
        start = offset + k * record_length
        x, y, z = struct.unpack_from("<3i", data, start)
        points.append((x * sx + ox, y * sy + oy, z * sz + oz))
    return points


def _las(data: bytes) -> list[tuple[float, float, float]]:
    """Uncompressed LAS points."""
    return _las_records(data, _las_header(data))


def _laz(data: bytes) -> list[tuple[float, float, float]]:
    """Compressed LAZ points (lazrs, MIT), using the file's LASzip VLR."""
    import io

    header = _las_header(data)
    if not header["vlr"]:
        raise ValueError("the LAZ file has no LASzip variable-length record")
    try:
        import lazrs

        source = io.BytesIO(data[header["offset"]:])
        decompressor = lazrs.LasZipDecompressor(source, header["vlr"])
        raw = bytearray(header["record_length"] * header["count"])
        decompressor.decompress_many(raw)
    except ImportError:
        raise ValueError("LAZ needs the lazrs-python package (not installed)") from None
    except Exception as ex:  # noqa: BLE001
        raise ValueError(f"the LAZ file could not be decompressed: {ex}") from None
    # The decompressed records start at the same layout; point them at a synthetic LAS body.
    return _las_records(bytes(raw), {**header, "offset": 0, "header_size": 0})


def _e57dump() -> str:
    """The E57 bridge: KIMBIM_E57DUMP, the build folder, or the packaged helper."""
    env = (os.environ.get("KIMBIM_E57DUMP") or "").strip()
    if env:
        return env
    root = pathlib.Path(__file__).resolve().parents[2]
    names = ("e57dump.exe", "e57dump") if os.name == "nt" else ("e57dump",)
    for folder in (root / "build" / "e57dump", root / "e57dump", root / "tools" / "e57dump"):
        for name in names:
            candidate = folder / name
            if candidate.is_file():
                return str(candidate)
    return ""


def _e57(path: str) -> list[tuple[float, float, float]]:
    """Read every scan in an E57 file through the C++ libe57format bridge (binary float32 stream)."""
    helper = _e57dump()
    if not helper:
        raise ValueError("E57 needs the e57dump helper (run `pixi run e57dump-build`)")
    try:
        process = subprocess.run([helper, path], capture_output=True)
    except OSError as ex:
        raise ValueError(f"the E57 helper could not run: {ex}") from None
    if process.returncode != 0:
        message = process.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(message or "the E57 file could not be read")
    data = process.stdout
    if len(data) < 8:
        raise ValueError("the E57 helper returned no points")
    count = struct.unpack_from("<Q", data, 0)[0]
    if not count or len(data) < 8 + count * 12:
        raise ValueError("the E57 file has no points")
    values = struct.unpack_from(f"<{count * 3}f", data, 8)
    return [(values[i], values[i + 1], values[i + 2]) for i in range(0, len(values), 3)]


def _read(path: str) -> tuple[list[tuple[float, float, float]], str]:
    suffix = pathlib.Path(path).suffix.lower().lstrip(".")
    if suffix not in FORMATS:
        raise ValueError(f"unsupported point-cloud format: {suffix or 'none'} "
                         f"(expected {', '.join(FORMATS)})")
    source = pathlib.Path(path)
    if not source.is_file():
        raise ValueError(f"the point-cloud file does not exist: {path}")
    data = source.read_bytes()
    if not data.strip():
        raise ValueError("the point-cloud file is empty")
    if suffix == "las":
        return _las(data), suffix
    if suffix == "laz":
        return _laz(data), suffix
    if suffix == "e57":
        return _e57(path), suffix
    return _rows(data.decode("utf-8-sig", errors="replace")), suffix


# ---------------------------------------------------------------- markers and the proxy

def _markers(points, size: float) -> tuple[list, list]:
    """A small tetrahedron per point (four triangles), so the scan is visible and meshable."""
    out, faces = [], []
    for x, y, z in points:
        base = len(out)
        out += [(x - size, y - size, z), (x + size, y - size, z),
                (x, y + size, z), (x, y, z + 2.0 * size)]
        faces += [[base, base + 1, base + 2], [base, base + 1, base + 3],
                  [base + 1, base + 2, base + 3], [base + 2, base, base + 3]]
    return out, faces


def _level(level_guid: str):
    if level_guid:
        storey = A._by_guid(level_guid)
        if storey is None or not storey.is_a("IfcBuildingStorey"):
            return None
        return storey
    storeys = sorted(B._model.by_type("IfcBuildingStorey"), key=lambda s: s.id())
    return storeys[0] if storeys else None


def _create(level, name: str, source: str, fmt: str, transform: dict, total: int, imported: int,
            points, faces) -> str:
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
            "Points": int(total),
            "Imported": int(imported),
            "MarkerSize": float(transform["marker"]),
            "Bounds": json.dumps(terrain._bounds(points), separators=(",", ":")),
        })
        made["guid"] = element.GlobalId
        return 1, [element.GlobalId], []

    B._run(action)
    return made["guid"]


# ---------------------------------------------------------------- public commands

def pointcloud_formats() -> str:
    """The point-cloud file formats the importer reads."""
    return B._dump({"ok": True, "formats": list(FORMATS)})


def import_pointcloud(path: str, level_guid: str = "", options_json: str = "") -> str:
    """Import a point cloud as one proxy. Options: {name, scale, rotation, x, y, z, max_points, marker}."""
    if B._model is None:
        return A._fail("no model open")
    if not isinstance(path, str) or not path.strip():
        return A._fail("no point-cloud file given")
    level = _level(level_guid)
    if level is None:
        return A._fail("unknown level")
    try:
        options = _options(options_json)
        transform = _transform(options)
        max_points = int(_number(options.get("max_points", _DEFAULT_MAX), "max_points"))
        if max_points < 10:
            raise ValueError("max_points must be at least 10")
        transform["marker"] = _number(options.get("marker", 0.03), "marker")
        if not 0.001 <= transform["marker"] <= 2.0:
            raise ValueError("the marker size must be between 1 mm and 2 m")
        raw, fmt = _read(path)
        if not raw:
            raise ValueError("the point-cloud file has no points")
        total = len(raw)
        step = max(1, math.ceil(total / max_points))
        sampled = raw[::step]
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    name = str(options.get("name") or "").strip() or pathlib.Path(path).stem or "Imported point cloud"
    world = _apply(sampled, transform)
    markers, faces = _markers(world, transform["marker"])
    try:
        guid = _create(level, name, str(pathlib.Path(path).resolve()), fmt, transform, total,
                       len(world), markers, faces)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({"ok": True, "guid": guid, "name": name, "format": fmt,
                    "points": total, "imported": len(world), "triangles": len(faces),
                    "bounds": terrain._bounds(markers)})
