# SPDX-License-Identifier: GPL-3.0-or-later
"""Changing a model's IFC schema (doc 02 "IFC schema version", D30; D241).

NicBim never converts a schema silently: a file is saved in the schema it was opened in. Moving between IFC2X3,
IFC4 and IFC4X3 is this explicit command, done with IfcOpenShell's own `Migrator` (what ifcpatch's Migrate
recipe runs), element by element into a new file of the target schema.

- A versioned project (a .nic, a project folder, or a model versioned in place) changes schema as **a version of
  its own**: the migrated model is committed at once with the message given, and later versions are in the new
  schema. Unsaved edits must be saved as a version first, so the change is never mixed with other work.
- A plain IFC file is written to a new path (never over the file opened, which keeps its schema); the app
  then opens the new file.
"""
from __future__ import annotations

import json
import pathlib
import re

import ifcopenshell
import ifcopenshell.util.schema

from . import app_bridge as B

TARGETS = {"IFC4": "IFC4", "IFC4X3": "IFC4X3_ADD2"}  # what the user picks -> the file's schema identifier


def _fail(message: str) -> str:
    return B._dump({"ok": False, "error": message})


def name_of(model) -> str:
    """The short schema name: IFC2X3, IFC4 or IFC4X3."""
    return "IFC4X3" if str(model.schema).upper().startswith("IFC4X3") else str(model.schema).upper()


def schema_info() -> str:
    """The open model's schema and the schemas it can change to."""
    if B._model is None:
        return _fail("no model open")
    current = name_of(B._model)
    return B._dump({"ok": True, "schema": current, "identifier": B._model.schema_identifier,
                    "targets": [t for t in TARGETS if t != current]})


def migrated(model, target: str):
    """A new file of `target` ("IFC4" or "IFC4X3") holding `model`'s content, with its header kept."""
    import contextlib
    import io

    new = ifcopenshell.file(schema=TARGETS[target])
    migrator = ifcopenshell.util.schema.Migrator()
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):  # it prints each attribute it cannot map: kept as `unmapped`
        for element in model:
            migrator.migrate(element, new)
    new._kimbim_unmapped = _unmapped(model, printed.getvalue())
    _restore_counts(model, new)
    old_header, new_header = model.header, new.header
    for part, fields in (("file_name", ("name", "author", "organization", "authorization", "preprocessor_version",
                                        "originating_system")),
                         ("file_description", ("description",))):
        for field in fields:  # the header's description and authorship travel with the model
            try:
                setattr(getattr(new_header, part), field, getattr(getattr(old_header, part), field))
            except Exception:  # noqa: BLE001 - a header is informative only
                pass
    return new


_UNMAPPED = re.compile(r"Unable to find equivalent attribute of (\w+) to migrate from #(\d+)=")


def _unmapped(model, printed: str) -> list[dict]:
    """The attributes with a value that the Migrator found no place for (an attribute new in the target, unset
    in the source, is no loss)."""
    out, seen = [], set()
    for attr, sid in _UNMAPPED.findall(printed):
        if (attr, sid) in seen:
            continue
        seen.add((attr, sid))
        try:
            element = model.by_id(int(sid))
            value = getattr(element, attr, None)
        except Exception:  # noqa: BLE001
            continue
        if value is None or value == () or value == []:
            continue
        out.append({"id": int(sid), "class": element.is_a(), "attribute": attr,
                    "guid": getattr(element, "GlobalId", "") or "", "name": getattr(element, "Name", "") or "",
                    "before": str(value) if hasattr(value, "is_a") else value})
    return out


def _restore_counts(model, new) -> None:
    """IFC4 -> IFC4X3: a whole-number IfcCountMeasure property becomes IfcCountMeasure again (the Migrator writes
    IfcNumericMeasure, since IFC4X3's count is an INTEGER)."""
    if not str(new.schema).upper().startswith("IFC4X3"):
        return
    for old in model.by_type("IfcPropertySingleValue"):
        value = old.NominalValue
        if value is None or value.is_a() != "IfcCountMeasure" or float(value.wrappedValue) != int(value.wrappedValue):
            continue
        for pset in old.PartOfPset or ():
            try:
                target = new.by_guid(pset.GlobalId)
            except RuntimeError:
                continue
            for prop in target.HasProperties or ():
                if prop.Name == old.Name and prop.is_a("IfcPropertySingleValue") and prop.NominalValue is not None \
                        and prop.NominalValue.is_a() == "IfcNumericMeasure":
                    prop.NominalValue = new.create_entity("IfcCountMeasure", int(value.wrappedValue))


def _counts(model) -> dict:
    return {"products": len(model.by_type("IfcProduct")), "types": len(model.by_type("IfcTypeObject"))}


_ATTRIBUTES = ("Name", "Description", "ObjectType", "PredefinedType", "Tag", "LongName", "ElementType")
LISTED = 200  # changes listed per kind; the totals count them all


def _value(v):
    if isinstance(v, float):  # 9.0 and 9 are the same count (IFC4's REAL count, IFC4X3's INTEGER one)
        return int(v) if v.is_integer() else round(v, 9)
    if isinstance(v, (list, tuple)):
        return [_value(x) for x in v]
    return v


def _properties(element) -> dict:
    """{"Pset.Name": value} for its own property and quantity sets (not inherited from the type); a single
    value carries its measure type ("IfcCountMeasure(9)"), so a changed type is a change."""
    import ifcopenshell.util.element as E

    out = {}
    for pset, props in E.get_psets(element, psets_only=False, qtos_only=False, should_inherit=False).items():
        for name, value in props.items():
            if name != "id":
                out[f"{pset}.{name}"] = _value(value)
    for definition in E.get_psets(element, should_inherit=False).values():
        pset = element.file.by_id(definition["id"])
        for prop in getattr(pset, "HasProperties", None) or ():
            if prop.is_a("IfcPropertySingleValue") and prop.NominalValue is not None:
                out[f"{pset.Name}.{prop.Name}"] = f"{prop.NominalValue.is_a()}({_value(prop.NominalValue.wrappedValue)!r})"
    return out


def _materials(element) -> list[str]:
    import ifcopenshell.util.element as E

    try:
        return sorted(m.Name or "" for m in E.get_materials(element, should_inherit=False))
    except Exception:  # noqa: BLE001 - an odd material assignment is compared as nothing
        return []


def loss_report(before, after) -> dict:
    """What a migration dropped or changed, object by object (by GlobalId): objects missing after it, objects
    whose class changed, and changed direct attributes, properties, quantities and materials. Empty lists mean
    the content survived (geometry is not compared)."""
    report: dict = {"dropped": [], "reclassed": [], "attributes": [], "properties": [], "materials": [],
                    "unmapped": []}
    totals = dict.fromkeys(report, 0)
    for entry in getattr(after, "_kimbim_unmapped", None) or []:  # attributes of any entity (units, point lists)
        totals["unmapped"] += 1
        if len(report["unmapped"]) < LISTED:
            report["unmapped"].append(entry)

    def add(kind, entry):
        totals[kind] += 1
        if len(report[kind]) < LISTED:
            report[kind].append(entry)

    for old in before.by_type("IfcRoot"):
        guid = old.GlobalId
        try:
            new = after.by_guid(guid)
        except RuntimeError:
            new = None
        if new is None:
            add("dropped", {"guid": guid, "class": old.is_a(), "name": getattr(old, "Name", None) or ""})
            continue
        label = {"guid": guid, "class": old.is_a(), "name": getattr(old, "Name", None) or ""}
        if new.is_a() != old.is_a():
            add("reclassed", {**label, "to": new.is_a()})
        old_info, new_info = old.get_info(recursive=False), new.get_info(recursive=False)
        for attr in _ATTRIBUTES:
            if attr in old_info and _value(old_info[attr]) != _value(new_info.get(attr)):
                add("attributes", {**label, "attribute": attr, "before": old_info[attr], "after": new_info.get(attr)})
        if old.is_a("IfcObjectDefinition"):
            a, b = _properties(old), _properties(new)
            for key in sorted(set(a) | set(b)):
                if a.get(key, "<missing>") != b.get(key, "<missing>"):
                    add("properties", {**label, "property": key, "before": a.get(key), "after": b.get(key)})
            if _materials(old) != _materials(new):
                add("materials", {**label, "before": _materials(old), "after": _materials(new)})
    report["totals"] = totals
    report["lossless"] = not any(totals.values())
    return report


def change_schema(target: str, path: str = "", message: str = "", accept_loss: str = "") -> str:
    """Change the open model's schema to `target` ("IFC4" or "IFC4X3").

    Versioned: commits the migrated model as a version (`message`, default "Change IFC schema to X") and
    returns {"reload": working path}. Not versioned: writes it to `path` (required, not the open file) and
    returns {"open": path}. Both report the product and type counts before and after, and `loss`: what the
    migration dropped or changed (loss_report). A migration that loses anything is refused with
    {"needs_confirm": true, "loss"} unless `accept_loss` is "1"; an object with no equivalent in the target
    (an IfcRoad going to IFC4, say) is refused outright by the Migrator."""
    from . import versioning as V

    if B._model is None:
        return _fail("no model open")
    target = str(target or "").strip().upper()
    if target not in TARGETS:
        return _fail("the schema must be IFC4 or IFC4X3")
    current = name_of(B._model)
    if current == target:
        return _fail(f"the model is already {target}")
    versioned = V._project is not None
    if versioned and (B._dirty() or V._unversioned()):
        return _fail("save a version first: the schema change is a version of its own")
    if not versioned:
        if not path:
            return _fail("choose where to write the new file")
        if B._path and pathlib.Path(path).resolve() == pathlib.Path(B._path).resolve():
            return _fail("write the new schema to another file: the open file keeps its schema")
    before = _counts(B._model)
    try:
        new = migrated(B._model, target)
    except NotImplementedError as ex:  # the Migrator: an entity with no equivalent in the target
        return _fail(f"{target} cannot hold everything in this model: {str(ex).split(' Referenced by')[0]}. "
                     "Remove or replace that data first.")
    except Exception as ex:  # noqa: BLE001
        return _fail(f"could not migrate to {target}: {type(ex).__name__}: {ex}")
    after = _counts(new)
    loss = loss_report(B._model, new)
    report = {"from": current, "to": target, "before": before, "after": after, "loss": loss}
    if not loss["lossless"] and str(accept_loss) not in ("1", "true", "yes"):
        n = sum(loss["totals"].values())
        return B._dump({"ok": False, "needs_confirm": True, **report,
                        "error": f"converting to {target} would drop or change {n} item(s): see the list"})
    if not versioned:
        try:
            new.write(path)
        except OSError as ex:
            return _fail(f"could not write {path}: {ex}")
        return B._dump({"ok": True, "open": path, **report})
    working = V._working()
    working.parent.mkdir(parents=True, exist_ok=True)
    new.write(str(working))
    previous, B._model = B._model, new  # the version is committed from the migrated model
    r = json.loads(V.save_version(message or f"Change IFC schema to {target}", "", TARGETS[target]))
    if not r.get("ok"):
        B._model = previous
        previous.write(str(working))
        return B._dump(r)
    reopened = json.loads(V._open_head(V._project))  # ids, undo history and settings start from the version
    if not reopened.get("ok"):
        return B._dump(reopened)
    return B._dump({**r, "ok": True, "reload": reopened["path"], **report})
