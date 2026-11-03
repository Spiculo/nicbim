# SPDX-License-Identifier: GPL-3.0-or-later
"""Linked models (Archicad hotlinks): another IFC file shown in this model as a read-only reference.

The linked file is tessellated once, transformed by the link's placement (x, y, z, rotation about Z,
uniform scale) and baked into a single `IfcBuildingElementProxy` (ObjectType "Linked model") with one
triangulated body: IFC4 `IfcTriangulatedFaceSet`, IFC2X3 `IfcShellBasedSurfaceModel` (through
terrain._representation). The proxy is contained in a level and carries `KIMBIM_Link`:

    Path, Name, Transform (JSON), ElementCount, SourceHash (sha1 of the file), Updated (ISO)

`update_link` re-reads the source and rebuilds the body in place (same GlobalId). Every change is one
undo step. Same protocol as app_bridge: strings in, JSON out, never raise.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import math
import pathlib

import ifcopenshell
import ifcopenshell.api.geometry
import ifcopenshell.api.project
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.placement
import numpy as np

from . import app_bridge as B
from . import authoring as A
from . import terrain

PSET = "KIMBIM_Link"
MONITOR_PSET = "KIMBIM_LinkMonitor"
OBJECT_TYPE = "Linked model"
TRANSFORM_KEYS = ("x", "y", "z", "rotation", "scale")


# ---------------------------------------------------------------- options and source geometry

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
    """The link placement: x, y, z (metres), rotation (degrees), uniform scale, visible."""
    out = {"x": 0.0, "y": 0.0, "z": 0.0, "rotation": 0.0, "scale": 1.0, "visible": True}
    for key in TRANSFORM_KEYS:
        if options.get(key) is not None:
            out[key] = _number(options[key], key)
    if out["scale"] <= 0:
        raise ValueError("the scale must be positive")
    if options.get("visible") is not None:
        out["visible"] = bool(options["visible"])
    return out


def _parse_transform(value) -> dict:
    try:
        data = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        data = None
    return _transform(data) if isinstance(data, dict) else _transform({})


def _apply(points, transform: dict) -> list[tuple[float, float, float]]:
    """Scale, rotate about Z and translate the source's world points (metres)."""
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


def _source(path: str):
    """(world points, triangles, element count, sha1) from the linked IFC file, in metres."""
    source = pathlib.Path(path)
    if not source.is_file():
        raise ValueError(f"the linked file does not exist: {path}")
    try:
        data = source.read_bytes()
        f = ifcopenshell.open(str(source))
    except Exception as ex:  # noqa: BLE001 - unreadable or not IFC
        raise ValueError(f"{type(ex).__name__}: {ex}") from None
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    try:
        iterator = ifcopenshell.geom.iterator(settings, f, 1)
        if not iterator.initialize():
            raise ValueError("the linked model has no geometry")
        points, faces, elements = [], [], 0
        while True:
            shape = iterator.get()
            verts = shape.geometry.verts
            triangles = shape.geometry.faces
            if len(triangles):
                offset = len(points)
                points.extend((float(verts[i]), float(verts[i + 1]), float(verts[i + 2]))
                              for i in range(0, len(verts), 3))
                faces.extend((int(triangles[i]) + offset, int(triangles[i + 1]) + offset,
                              int(triangles[i + 2]) + offset) for i in range(0, len(triangles), 3))
                elements += 1
            if not iterator.next():
                break
    except ValueError:
        raise
    except Exception as ex:  # noqa: BLE001
        raise ValueError(f"{type(ex).__name__}: {ex}") from None
    if not faces:
        raise ValueError("the linked model has no geometry")
    return points, faces, elements, hashlib.sha1(data).hexdigest()


def _bounds(points) -> dict:
    return {"min": [round(min(p[i] for p in points), 6) for i in range(3)],
            "max": [round(max(p[i] for p in points), 6) for i in range(3)]}


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- the proxy

def _level(level_guid: str):
    if level_guid:
        storey = A._by_guid(level_guid)
        return storey if storey is not None and storey.is_a("IfcBuildingStorey") else None
    storeys = sorted(B._model.by_type("IfcBuildingStorey"), key=lambda s: s.id())
    return storeys[0] if storeys else None


def _create(level, name: str, path: str, transform: dict, points, faces, elements: int,
            source_hash: str) -> str:
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
            "Path": path,
            "Name": name,
            "Transform": json.dumps(transform),
            "ElementCount": int(elements),
            "SourceHash": source_hash,
            "Updated": _now(),
        })
        made["guid"] = element.GlobalId
        return 1, [element.GlobalId], []

    B._run(action)
    return made["guid"]


def _replace_representation(element, points, faces) -> None:
    """Rebuild the proxy's body in place, dropping its previous representation."""
    f = B._model
    definition = element.Representation
    if definition is not None:
        for representation in list(definition.Representations or ()):
            ifcopenshell.api.geometry.unassign_representation(f, product=element, representation=representation)
            ifcopenshell.api.geometry.remove_representation(f, representation=representation)
    ifcopenshell.api.geometry.assign_representation(f, product=element,
                                                    representation=terrain._representation(points, faces))


def _link(guid: str):
    """(element, KIMBIM_Link values) for a linked model, or (None, None)."""
    element = A._by_guid(guid)
    if element is None or not element.is_a("IfcBuildingElementProxy"):
        return None, None
    data = ifcopenshell.util.element.get_pset(element, PSET)
    return (element, data) if data else (None, None)


def _links() -> list:
    out = []
    for pset in B._model.by_type("IfcPropertySet"):
        if pset.Name != PSET:
            continue
        for element in B._pset_users(pset):
            if element.is_a("IfcBuildingElementProxy"):
                out.append((element, ifcopenshell.util.element.get_pset(element, PSET) or {}))
    return sorted(out, key=lambda pair: pair[0].id())


def _triangles(element) -> int:
    _points, triangles = terrain._mesh(element)
    return triangles


# ---------------------------------------------------------------- copy/monitor

def _transform_matrix(transform: dict) -> np.ndarray:
    angle = math.radians(transform["rotation"])
    c, s, scale = math.cos(angle), math.sin(angle), transform["scale"]
    return np.array([[c * scale, -s * scale, 0.0, transform["x"]],
                     [s * scale, c * scale, 0.0, transform["y"]],
                     [0.0, 0.0, scale, transform["z"]], [0.0, 0.0, 0.0, 1.0]])


def _signature(product) -> str:
    """A stable hash of a product's attributes, types and property sets (for monitor comparisons)."""
    try:
        info = product.get_info(recursive=False)
        # References (Representation, ObjectPlacement, OwnerHistory) are entities whose ids need not
        # survive a rewrite; monitor attributes and properties, which is what copy/monitor syncs.
        info = {k: v for k, v in info.items()
                if k not in ("id", "Representation", "ObjectPlacement", "OwnerHistory")
                and isinstance(v, (str, int, float, bool, type(None)))}
        props = {k: v for k, v in ifcopenshell.util.element.get_psets(product, psets_only=True).items()
                 if not k.startswith("KIMBIM_")}
        payload = json.dumps({"info": info, "psets": props}, sort_keys=True, default=str, separators=(",", ":"))
    except Exception:  # noqa: BLE001 - a malformed product must not break the report
        payload = repr(product)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _apply_source(element, product) -> None:
    """Copy a source product's attributes and non-KimBim property sets onto its host copy."""
    for name, value in product.get_info(recursive=False).items():
        if name in ("id", "type", "GlobalId", "Representation", "ObjectPlacement", "OwnerHistory"):
            continue
        if not isinstance(value, (str, int, float, bool, type(None))):
            continue
        try:
            setattr(element, name, value)
        except (AttributeError, RuntimeError):
            continue
    source_psets = ifcopenshell.util.element.get_psets(product, psets_only=True)
    wanted = {name: {k: v for k, v in props.items() if k != "id"}
              for name, props in source_psets.items() if not name.startswith("KIMBIM_")}
    host_psets = ifcopenshell.util.element.get_psets(element, psets_only=True)
    for name, props in wanted.items():
        pset = B._own_pset(element, name)
        if pset is None:
            pset = ifcopenshell.api.pset.add_pset(B._model, product=element, name=name)
        ifcopenshell.api.pset.edit_pset(B._model, pset=pset, properties=props, should_purge=True)
    for name in host_psets:
        if name.startswith("KIMBIM_") or name in wanted:
            continue
        pset = B._own_pset(element, name)
        if pset is not None:
            ifcopenshell.api.pset.remove_pset(B._model, product=element, pset=pset)


def _monitored() -> list[tuple]:
    """(host element, KIMBIM_LinkMonitor values) for every monitored copy."""
    out = []
    if B._model is None:
        return out
    for pset in B._model.by_type("IfcPropertySet"):
        if pset.Name != MONITOR_PSET:
            continue
        for element in B._pset_users(pset):
            data = ifcopenshell.util.element.get_pset(element, MONITOR_PSET)
            if data:
                out.append((element, data))
    return sorted(out, key=lambda pair: pair[0].id())


def _source_products(model) -> list:
    """The source model's drawable products a monitored copy represents."""
    skip = ("IfcOpeningElement", "IfcSpace", "IfcAnnotation", "IfcGrid", "IfcSite", "IfcBuilding",
            "IfcBuildingStorey", "IfcProject", "IfcTypeObject")
    return [p for p in model.by_type("IfcProduct")
            if p.Representation is not None and not any(p.is_a(c) for c in skip)]


def explode_link(guid: str, options_json: str = "") -> str:
    """Turn a linked IFC into **editable copies**: every product of the source is appended to this
    project as a normal element (Geometry, properties and types included) and tagged with
    `KIMBIM_LinkMonitor` (Source, SourceGuid, SourceClass, SourceName, SourceHash, SourceSignature,
    HostSignature, Synced). The link proxy is removed. Options: {level (name/GlobalId)}; the proxy's
    level is used otherwise. One undo step."""
    if B._model is None:
        return A._fail("no model open")
    element, data = _link(guid)
    if element is None:
        return A._fail("not a linked model")
    try:
        options = _options(options_json)
        path = str(data.get("Path") or "")
        transform = _parse_transform(data.get("Transform"))
        source = ifcopenshell.open(path)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    container = _level(options.get("level") or "") if options.get("level") else \
        ifcopenshell.util.element.get_container(element)
    if container is None:
        return A._fail("the linked model is not on a level")
    source_hash = hashlib.sha1(pathlib.Path(path).read_bytes()).hexdigest()
    products = _source_products(source)
    if not products:
        return A._fail("the linked model has no products to copy")
    matrix = _transform_matrix(transform)
    made = {}

    def action():
        f = B._model
        reuse = {}
        copies = []
        for product in products:
            try:
                new = ifcopenshell.api.project.append_asset(
                    f, library=source, element=product, reuse_identities=reuse,
                    assume_asset_uniqueness_by_name=True)
            except Exception:
                continue
            if new is None or not new.is_a("IfcProduct"):
                continue
            if new.ObjectPlacement is not None:
                local = ifcopenshell.util.placement.get_local_placement(new.ObjectPlacement)
                ifcopenshell.api.geometry.edit_object_placement(
                    f, product=new, matrix=matrix @ local, is_si=True)
            ifcopenshell.api.spatial.assign_container(f, products=[new], relating_structure=container)
            pset = ifcopenshell.api.pset.add_pset(f, product=new, name=MONITOR_PSET)
            ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={
                "Source": path, "SourceGuid": product.GlobalId, "SourceClass": product.is_a(),
                "SourceName": product.Name or "", "SourceHash": source_hash,
                "SourceSignature": _signature(product), "HostSignature": _signature(new),
                "Synced": _now(), "Link": guid})
            copies.append(new)
        if not copies:
            raise ValueError("no source product could be copied")
        ifcopenshell.api.root.remove_product(f, product=element)
        made["guids"] = [c.GlobalId for c in copies]
        return len(copies), made["guids"], [guid]

    try:
        r = B._run(action)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guids": made["guids"], "count": len(made["guids"]), "source": path,
                    "skipped": max(0, len(products) - len(made["guids"]))})


def monitor_status() -> str:
    """Report what changed in every monitored source file: the host copies whose source element
    changed, host copies whose source element is gone, and source elements that were added since the
    copy was made. Nothing is modified."""
    if B._model is None:
        return B._dump({"ok": True, "sources": []})
    by_source: dict[str, list] = {}
    for element, data in _monitored():
        by_source.setdefault(str(data.get("Source") or ""), []).append((element, data))
    sources = []
    for path, entries in sorted(by_source.items()):
        entry = {"path": path, "monitored": len(entries), "changed": False, "missing": False,
                 "changed_elements": [], "removed": [], "added": [], "error": ""}
        try:
            source = ifcopenshell.open(path)
        except Exception as ex:  # noqa: BLE001
            entry.update(changed=True, missing=not pathlib.Path(path).is_file(),
                         error=f"{type(ex).__name__}: {ex}")
            sources.append(entry)
            continue
        source_products = _source_products(source)
        current = {p.GlobalId: p for p in source_products}
        seen = set()
        for element, data in entries:
            source_guid = str(data.get("SourceGuid") or "")
            seen.add(source_guid)
            product = current.get(source_guid)
            if product is None:
                entry["removed"].append({"guid": element.GlobalId, "source_guid": source_guid,
                                         "name": element.Name or ""})
            elif _signature(product) != str(data.get("SourceSignature") or ""):
                entry["changed_elements"].append({"guid": element.GlobalId, "source_guid": source_guid,
                                                  "name": element.Name or "", "class": product.is_a()})
        entry["added"] = [{"source_guid": p.GlobalId, "name": p.Name or "", "class": p.is_a()}
                          for p in source_products if p.GlobalId not in seen]
        entry["changed"] = bool(entry["changed_elements"] or entry["removed"] or entry["added"])
        sources.append(entry)
    return B._dump({"ok": True, "sources": sources})


def sync_monitored(strategy: str = "safe", remove_orphans: bool = False) -> str:
    """Bring host copies up to date with their source files.

    A copy whose source changed but whose host was not edited takes the source's **attributes and
    properties** (not geometry); a copy edited in the host and in the source is a **conflict**:
    `strategy` "safe" leaves it alone, "source" lets the source win, "host" keeps the host edits and
    resolves it. Removed source elements are reported (or their host copies deleted with
    `remove_orphans`); added source elements cannot be matched and are reported. One undo step."""
    if B._model is None:
        return A._fail("no model open")
    strategy = str(strategy or "safe").lower()
    if strategy not in ("safe", "source", "host"):
        return A._fail("strategy is safe, source or host")
    if isinstance(remove_orphans, str):
        remove_orphans = remove_orphans.lower() in ("1", "true", "yes")
    applies, conflicts, removed, added, errors = [], [], [], [], []
    for element, data in _monitored():
        path = str(data.get("Source") or "")
        source_guid = str(data.get("SourceGuid") or "")
        try:
            source = ifcopenshell.open(path)
        except Exception as ex:  # noqa: BLE001
            errors.append({"guid": element.GlobalId, "error": f"{type(ex).__name__}: {ex}"})
            continue
        product = next((p for p in source.by_type("IfcProduct") if p.GlobalId == source_guid), None)
        if product is None:
            removed.append({"guid": element.GlobalId, "source_guid": source_guid, "name": element.Name or ""})
            continue
        source_sig = _signature(product)
        host_sig = _signature(element)
        source_changed = source_sig != str(data.get("SourceSignature") or "")
        host_changed = host_sig != str(data.get("HostSignature") or "")
        if not source_changed:
            continue
        if host_changed and strategy == "safe":
            conflicts.append({"guid": element.GlobalId, "source_guid": source_guid,
                              "name": element.Name or "", "class": product.is_a()})
            continue
        if host_changed and strategy == "host":
            applies.append((element, product, source_sig, "host_kept"))
            continue
        applies.append((element, product, source_sig, "synced"))
    made = {}

    def action():
        for element, product, source_sig, state in applies:
            _apply_source(element, product)
            pset = B._own_pset(element, MONITOR_PSET)
            if pset is not None:
                ifcopenshell.api.pset.edit_pset(B._model, pset=pset, properties={
                    "SourceSignature": source_sig, "HostSignature": _signature(element),
                    "Synced": _now(), "SyncState": state})
        if remove_orphans and removed:
            for item in removed:
                element = B._model.by_guid(item["guid"])
                ifcopenshell.api.root.remove_product(B._model, product=element)
        return len(applies) + (len(removed) if remove_orphans else 0), \
            [e.GlobalId for e, _p, _s, _st in applies], \
            [item["guid"] for item in removed] if remove_orphans else []

    try:
        r = B._run(action)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    made["applied"] = [{"guid": element.GlobalId, "source_guid": product.GlobalId,
                        "name": element.Name or "", "state": state}
                       for element, product, _sig, state in applies]
    try:
        for source in json.loads(monitor_status())["sources"]:
            for item in source.get("added") or []:
                added.append({"path": source["path"], **item})
    except (TypeError, ValueError):
        pass
    return B._dump({**r, "applied": made["applied"], "conflicts": conflicts, "removed": removed,
                    "added": added, "errors": errors})


# ---------------------------------------------------------------- public commands

def link_model(path: str, options_json: str = "") -> str:
    """Link an IFC file as one read-only proxy. Options: {name, level, x, y, z, rotation, scale, visible}."""
    if B._model is None:
        return A._fail("no model open")
    if not isinstance(path, str) or not path.strip():
        return A._fail("no linked file given")
    try:
        options = _options(options_json)
        transform = _transform(options)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    level = _level(options.get("level") or "")
    if level is None:
        return A._fail("unknown level")
    name = str(options.get("name") or "").strip() or pathlib.Path(path).stem
    try:
        points, faces, elements, source_hash = _source(path)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    points = _apply(points, transform)
    try:
        guid = _create(level, name, str(pathlib.Path(path).resolve()), transform, points, faces,
                       elements, source_hash)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({"ok": True, "guid": guid, "elements": elements, "triangles": len(faces),
                    "bounds": _bounds(points)})


def list_links() -> str:
    """Every linked model: GlobalId, name, path, source element count, triangles, transform and update time."""
    if B._model is None:
        return B._dump({"ok": True, "links": []})
    out = []
    for element, data in _links():
        out.append({
            "guid": element.GlobalId,
            "name": element.Name or "",
            "path": str(data.get("Path") or ""),
            "elements": int(data.get("ElementCount") or 0),
            "triangles": _triangles(element),
            "transform": _parse_transform(data.get("Transform")),
            "updated": str(data.get("Updated") or ""),
        })
    return B._dump({"ok": True, "links": out})


def update_link(guid: str) -> str:
    """Re-read a linked file and rebuild its proxy in place (same GlobalId, one undo step)."""
    if B._model is None:
        return A._fail("no model open")
    element, data = _link(guid)
    if element is None:
        return A._fail("not a linked model")
    try:
        points, faces, elements, source_hash = _source(str(data.get("Path") or ""))
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    transform = _parse_transform(data.get("Transform"))
    points = _apply(points, transform)

    def action():
        _replace_representation(element, points, faces)
        pset = B._own_pset(element, PSET)
        if pset is None:
            pset = ifcopenshell.api.pset.add_pset(B._model, product=element, name=PSET)
        ifcopenshell.api.pset.edit_pset(B._model, pset=pset, properties={
            "SourceHash": source_hash, "Updated": _now(), "ElementCount": int(elements)})
        return 1, [guid], []

    try:
        r = B._run(action)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": guid, "elements": elements, "triangles": len(faces),
                    "bounds": _bounds(points)})


def stale_links() -> str:
    """Every linked model whose source file no longer matches the baked geometry: guid, name, path,
    changed (bool), reason ("changed", "missing" or "unreadable")."""
    if B._model is None:
        return B._dump({"ok": True, "links": []})
    out = []
    for element, data in _links():
        path = str(data.get("Path") or "")
        entry = {"guid": element.GlobalId, "name": element.Name or "", "path": path,
                 "changed": False, "reason": ""}
        try:
            source = pathlib.Path(path)
            if not source.is_file():
                entry.update(changed=True, reason="missing")
            elif hashlib.sha1(source.read_bytes()).hexdigest() != str(data.get("SourceHash") or ""):
                entry.update(changed=True, reason="changed")
        except OSError:
            entry.update(changed=True, reason="unreadable")
        out.append(entry)
    return B._dump({"ok": True, "links": out})


def refresh_links(guids_json: str = "") -> str:
    """Re-read every changed linked file (or only the given GlobalIds) and rebuild its proxy in place.
    One undo step per refreshed link; unchanged links are left alone."""
    if B._model is None:
        return A._fail("no model open")
    wanted = None
    if guids_json:
        try:
            data = json.loads(guids_json)
            wanted = set(data) if isinstance(data, list) else None
        except (TypeError, ValueError):
            return A._fail("guids must be a JSON list")
        if wanted is None:
            return A._fail("guids must be a JSON list")
    stale = {entry["guid"]: entry for entry in json.loads(stale_links())["links"] if entry["changed"]}
    refreshed, skipped, errors = [], [], []
    geometry = {"changed": [], "removed": []}
    for element, _data in _links():
        guid = element.GlobalId
        if wanted is not None and guid not in wanted:
            skipped.append(guid)
            continue
        if guid not in stale:
            skipped.append(guid)
            continue
        result = json.loads(update_link(guid))
        if result.get("ok"):
            refreshed.append(guid)
            for key in ("changed", "removed"):
                geometry[key].extend(result.get("geometry", {}).get(key) or [])
        else:
            errors.append({"guid": guid, "error": result.get("error", "")})
    geometry = {k: list(dict.fromkeys(v)) for k, v in geometry.items()}
    return B._dump({"ok": True, "refreshed": refreshed, "skipped": skipped, "errors": errors,
                    "changed": len(stale), "geometry": geometry})


def set_link_transform(guid: str, transform_json: str) -> str:
    """Move, rotate or scale a linked model and rebuild it (one undo step)."""
    if B._model is None:
        return A._fail("no model open")
    element, data = _link(guid)
    if element is None:
        return A._fail("not a linked model")
    try:
        changes = _options(transform_json)
        transform = _parse_transform(data.get("Transform"))
        for key in TRANSFORM_KEYS:
            if changes.get(key) is not None:
                transform[key] = _number(changes[key], key)
        if transform["scale"] <= 0:
            raise ValueError("the scale must be positive")
        if changes.get("visible") is not None:
            transform["visible"] = bool(changes["visible"])
        points, faces, elements, source_hash = _source(str(data.get("Path") or ""))
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    points = _apply(points, transform)

    def action():
        _replace_representation(element, points, faces)
        pset = B._own_pset(element, PSET)
        if pset is None:
            pset = ifcopenshell.api.pset.add_pset(B._model, product=element, name=PSET)
        ifcopenshell.api.pset.edit_pset(B._model, pset=pset, properties={
            "Transform": json.dumps(transform), "Updated": _now(),
            "SourceHash": source_hash, "ElementCount": int(elements)})
        return 1, [guid], []

    try:
        r = B._run(action)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": guid, "elements": elements, "triangles": len(faces),
                    "bounds": _bounds(points)})


def unlink(guid: str) -> str:
    """Remove a linked model's proxy (one undo step). The linked file itself is left alone."""
    if B._model is None:
        return A._fail("no model open")
    element, _data = _link(guid)
    if element is None:
        return A._fail("not a linked model")

    def action():
        ifcopenshell.api.root.remove_product(B._model, product=element)
        return 1, [], [guid]

    try:
        r = B._run(action)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": guid})
