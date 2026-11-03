# SPDX-License-Identifier: GPL-3.0-or-later
"""Live mesh links from Rhino / Grasshopper (D221).

Rhino and Grasshopper cannot be embedded without their SDK, so the link is file based: the
designer exports the Rhino/Grasshopper geometry as a mesh (OBJ, STL, PLY, COLLADA, glTF/GLB or
FBX), and this module keeps that export in the model. The proxy carries ``KIMBIM_MeshLink``
(Path, Format, Transform, Triangles, SourceHash, Updated); when the designer saves the export
again the hash changes, and ``refresh_mesh_links`` rebuilds the body in place (same GlobalId),
so the plan, sections and drawings follow without re-importing by hand. The model is read-only
towards Rhino: pushing edits back needs Rhino itself.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib

import ifcopenshell.api.geometry
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.util.element

from . import app_bridge as B
from . import authoring as A
from . import links as L
from . import meshimport as MI

PSET = "KIMBIM_MeshLink"


def _now() -> str:
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def _hash(path: str) -> str:
    try:
        with open(path, "rb") as handle:
            return hashlib.sha1(handle.read()).hexdigest()
    except OSError:
        return ""


def _link(guid: str):
    element = A._by_guid(guid)
    if element is None or not element.is_a("IfcBuildingElementProxy"):
        return None, None
    data = ifcopenshell.util.element.get_pset(element, PSET)
    return (element, data) if data else (None, None)


def _links() -> list[tuple]:
    out = []
    for pset in B._model.by_type("IfcPropertySet"):
        if pset.Name != PSET:
            continue
        for element in B._pset_users(pset):
            if element.is_a("IfcBuildingElementProxy"):
                out.append((element, ifcopenshell.util.element.get_pset(element, PSET) or {}))
    return sorted(out, key=lambda pair: pair[0].id())


def _entry(element, data: dict) -> dict:
    path = str(data.get("Path") or "")
    return {
        "guid": element.GlobalId,
        "name": element.Name or "",
        "path": path,
        "format": data.get("Format") or "",
        "triangles": int(data.get("Triangles") or 0),
        "updated": data.get("Updated") or "",
        "stale": not path or not os.path.isfile(path) or _hash(path) != (data.get("SourceHash") or ""),
    }


def add_mesh_link(path: str, level_guid: str = "", options_json: str = "") -> str:
    """Import a Rhino/Grasshopper mesh export as a live link on a level.

    Options are the mesh importer's: ``{name, scale, rotation, x, y, z}``.
    """
    if B._model is None:
        return A._fail("no model open")
    if not isinstance(path, str) or not path.strip():
        return A._fail("no mesh file given")
    source = str(pathlib.Path(path).resolve())
    if not os.path.isfile(source):
        return A._fail("the mesh file does not exist")
    level = MI._level(level_guid)
    if level is None:
        return A._fail("unknown level")
    try:
        options = MI._options(options_json)
        transform = MI._transform(options)
        points, faces, fmt = MI._read(source)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    name = str(options.get("name") or "").strip() or pathlib.Path(source).stem or "Mesh link"
    points = MI._apply(points, transform)
    made: dict = {}

    def action():
        f = B._model
        guid = MI._create(level, name, source, fmt, transform, points, faces)
        element = f.by_guid(guid)
        pset = ifcopenshell.api.pset.add_pset(f, product=element, name=PSET)
        ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={
            "Path": source,
            "Format": fmt,
            "Transform": json.dumps(transform, separators=(",", ":")),
            "Triangles": len(faces),
            "SourceHash": _hash(source),
            "Updated": _now(),
        })
        made["guid"] = guid
        return 1, [guid], []

    try:
        B._run(action)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({"ok": True, "guid": made["guid"], "name": name, "triangles": len(faces),
                    "format": fmt})


def mesh_links() -> str:
    """The live Rhino/Grasshopper mesh links with their stale state."""
    if B._model is None:
        return A._fail("no model open")
    links = [_entry(element, data) for element, data in _links()]
    return B._dump({"ok": True, "links": links, "stale": sum(1 for link in links if link["stale"])})


def stale_mesh_links() -> str:
    """The mesh links whose file is missing or changed since the last import."""
    if B._model is None:
        return A._fail("no model open")
    links = [_entry(element, data) for element, data in _links()]
    return B._dump({"ok": True, "links": [link for link in links if link["stale"]]})


def refresh_mesh_links(guid: str = "") -> str:
    """Re-read stale mesh links (or one link) and rebuild their bodies; one undo step."""
    if B._model is None:
        return A._fail("no model open")
    targets, errors = [], []
    for element, data in _links():
        if guid and element.GlobalId != guid:
            continue
        path = str(data.get("Path") or "")
        if not guid and path and _hash(path) == (data.get("SourceHash") or ""):
            continue  # not stale
        try:
            transform = json.loads(data.get("Transform") or "{}")
            if not isinstance(transform, dict):
                raise ValueError("bad transform")
            points, faces, fmt = MI._read(path)
            points = MI._apply(points, transform)
        except (OSError, TypeError, ValueError) as ex:
            errors.append({"guid": element.GlobalId, "error": str(ex)})
            continue
        targets.append((element, points, faces, fmt, path))
    if not targets:
        return B._dump({"ok": True, "updated": [], "errors": errors})

    def action():
        for element, points, faces, fmt, path in targets:
            L._replace_representation(element, points, faces)
            pset = B._own_pset(element, PSET)
            if pset is not None:
                ifcopenshell.api.pset.edit_pset(B._model, pset=pset, properties={
                    "Format": fmt, "Triangles": len(faces),
                    "SourceHash": _hash(path), "Updated": _now()})
        return len(targets), [element.GlobalId for element, *_ in targets], []

    try:
        result = B._run(action)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**result, "updated": [element.GlobalId for element, *_ in targets],
                    "errors": errors})


def remove_mesh_link(guid: str) -> str:
    """Remove a live mesh link (the source file is untouched)."""
    if B._model is None:
        return A._fail("no model open")
    element, data = _link(guid)
    if element is None:
        return A._fail("mesh link not found")

    def action():
        B._model.remove(element)
        return 1, [], []

    try:
        result = B._run(action)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**result, "guid": guid})
