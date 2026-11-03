# SPDX-License-Identifier: GPL-3.0-or-later
"""Graphics and attribute tools (D102): layers, purposes and overrides, materials and classifications.
Model changes are one undo step; view state (purpose, pen) is a display change."""
from __future__ import annotations

import json

from ... import classifications as C
from ... import graphics as G
from ... import layers as L
from ... import materials as M
from ..catalogue import bridge, tool

_NAME = {"type": "string", "description": "Name."}
_GUIDS = {"type": "array", "items": {"type": "string"}, "description": "GlobalIds of the elements."}
_CHANGES = {"type": ["object", "string"], "description": "The changes to apply."}


def _json(value) -> str:
    return value if isinstance(value, str) else json.dumps(value or {})


@tool("layers.list", {})
def layers_list(session):
    """List the project's layers, their visibility and lock state."""
    return bridge(L.layers)


@tool("layers.create", {"required": ["name"], "properties": {"name": _NAME}}, writes=True)
def layers_create(session, name):
    """Create a layer."""
    return bridge(L.create_layer, name)


@tool("layers.rename", {"required": ["name", "new_name"], "properties": {
    "name": _NAME, "new_name": _NAME}}, writes=True)
def layers_rename(session, name, new_name):
    """Rename a layer (the elements on it follow)."""
    return bridge(L.rename_layer, name, new_name)


@tool("layers.delete", {"required": ["name"], "properties": {"name": _NAME}}, writes=True)
def layers_delete(session, name):
    """Delete an empty layer; refuse when it still has elements."""
    return bridge(L.delete_layer, name)


@tool("layers.assign", {"required": ["elements", "layer"], "properties": {
    "elements": _GUIDS, "layer": _NAME}}, writes=True)
def layers_assign(session, elements, layer):
    """Put elements on a layer (one undo step)."""
    return bridge(L.assign_layer, json.dumps(list(elements)), layer)


@tool("graphics.state", {})
def graphics_state(session):
    """The current pen, purpose and graphics state of the model."""
    return bridge(G.graphics_state)


@tool("graphics.tables", {})
def graphics_tables(session):
    """The project's pens, line types, fills, element styles, overrides, purposes and filters."""
    return bridge(G.graphics_tables)


@tool("graphics.purpose", {"required": ["name"], "properties": {
    "name": {"type": "string", "description": "Purpose name (Existing, Demolition, New construction...)."}}})
def graphics_purpose(session, name):
    """Switch the view to a graphic purpose (renovation filter, visibility and overrides)."""
    return bridge(G.set_purpose, name)


@tool("graphics.set", {"properties": {"changes": _CHANGES}})
def graphics_set(session, changes=None):
    """Change a graphic setting (pen, visibility, override) in the project's graphics state."""
    return bridge(G.set_graphics, _json(changes))


@tool("materials.list", {})
def materials_list(session):
    """List the building materials and composites in the project."""
    return bridge(M.materials_state)


@tool("materials.assign", {"required": ["elements", "material"], "properties": {
    "elements": _GUIDS, "material": _NAME,
    "kind": {"type": "string", "enum": ["material", "composite"], "description": "Default material."},
    "scope": {"type": "string", "enum": ["", "element", "type"],
              "description": "Columns and beams: element or type scope."}}}, writes=True)
def materials_assign(session, elements, material, kind="material", scope=""):
    """Give elements a building material, or a composite (walls and slabs take its thickness)."""
    return bridge(M.assign_material, json.dumps(list(elements)), kind, material, scope)


@tool("materials.add_standard", {}, writes=True)
def materials_add_standard(session):
    """Add the standard building materials to the project."""
    return bridge(M.add_standard_materials)


@tool("materials.purge", {}, writes=True)
def materials_purge(session):
    """Remove unused materials."""
    return bridge(M.purge_materials)


@tool("classifications.list", {})
def classifications_list(session):
    """List the classification systems and their references."""
    return bridge(C.systems)


@tool("classifications.assign", {"required": ["elements", "references"], "properties": {
    "elements": _GUIDS,
    "references": {"type": "array", "items": {"type": "string"},
                   "description": "Reference ids, or \"System|Code\"."}}}, writes=True)
def classifications_assign(session, elements, references):
    """Assign classification references to elements (one undo step)."""
    return bridge(C.assign_classification, json.dumps(list(elements)), list(references))


@tool("classifications.unassign", {"required": ["elements", "references"], "properties": {
    "elements": _GUIDS, "references": {"type": "array", "items": {"type": "string"}}}}, writes=True)
def classifications_unassign(session, elements, references):
    """Remove classification references from elements."""
    return bridge(C.unassign_classification, json.dumps(list(elements)), list(references))


@tool("classifications.of_element", {"required": ["elements"], "properties": {
    "elements": _GUIDS}})
def classifications_of_element(session, elements):
    """List the classifications assigned to the given elements."""
    return bridge(C.of_element, json.dumps(list(elements)))


@tool("classifications.create_system", {"required": ["name"], "properties": {
    "name": _NAME, "source": {"type": "string"}, "edition": {"type": "string"},
    "description": {"type": "string"}}}, writes=True)
def classifications_create_system(session, name, source="", edition="", description=""):
    """Create a classification system (or use a shipped one by name)."""
    return bridge(C.create_system, name, source, edition, description)


@tool("classifications.add_reference", {"required": ["system", "code"], "properties": {
    "system": {"type": "string", "description": "System name or GlobalId."},
    "code": {"type": "string"}, "name": {"type": "string"}}}, writes=True)
def classifications_add_reference(session, system, code, name=""):
    """Add a code (reference) under a classification system."""
    return bridge(C.add_reference, system, code, name)
