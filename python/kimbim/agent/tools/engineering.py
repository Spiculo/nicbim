# SPDX-License-Identifier: GPL-3.0-or-later
"""Engineering tools (D242-D248): MEP systems, terminals and runs; airflow, water, drainage and
electrical sizing; structural analysis; the engineering settings. Calculations only read; their
`apply_*`/`save_results` twins write the sizes or results as one undo step."""
from __future__ import annotations

import json

from ... import drainage as D
from ... import electrical as El
from ... import engsettings as E
from ... import finishes as F
from ... import hvac as H
from ... import mep as M
from ... import plumbing as P
from ... import structanalysis as SA
from ..catalogue import bridge, tool

_SYSTEM = {"type": "string", "description": "System name or GlobalId."}
_LEVEL = {"type": "string", "description": "Level (storey) GlobalId."}
_GUIDS = {"type": "array", "items": {"type": "string"}, "description": "GlobalIds of the elements."}
_POINTS3 = {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
            "description": "Points [[x, y, z above the level], ...] in metres."}
_DISCIPLINE = {"type": "string", "enum": list(E.KEYS), "description": "Which engineering settings."}


def _json(value) -> str:
    return value if isinstance(value, str) else json.dumps(value)


@tool("mep.systems", {})
def mep_systems(session):
    """List the MEP distribution systems with their kind, domain, element count and open ports."""
    return bridge(F.mep_systems)


@tool("mep.catalogue", {})
def mep_catalogue(session):
    """List the terminal and equipment kinds (with ports and design values) and the system kinds."""
    return bridge(M.mep_catalogue)


@tool("mep.create_system", {"required": ["name", "kind"], "properties": {
    "name": {"type": "string"}, "kind": {"type": "string", "enum": list(M.SYSTEM_KINDS)}}}, writes=True)
def mep_create_system(session, name, kind):
    """Create a distribution system of a kind (supply_air, cold_water, sanitary, power...)."""
    return bridge(M.create_mep_system, name, kind)


@tool("mep.assign", {"required": ["elements", "system"], "properties": {
    "elements": _GUIDS, "system": _SYSTEM}}, writes=True)
def mep_assign(session, elements, system):
    """Put elements in a system; their ports of its domain take its kind."""
    return bridge(M.assign_to_system, json.dumps(list(elements)), system)


@tool("mep.place", {"required": ["kind", "level", "x", "y"], "properties": {
    "kind": {"type": "string", "enum": list(M.CATALOGUE)}, "level": _LEVEL,
    "x": {"type": "number"}, "y": {"type": "number"},
    "z": {"type": "number", "description": "Base above the level (default: the catalogue height)."},
    "rotation": {"type": "number", "description": "Degrees."}, "system": _SYSTEM}}, writes=True)
def mep_place(session, kind, level, x, y, z=None, rotation=0.0, system=""):
    """Place a terminal or piece of equipment (diffuser, AHU, WC, basin, drain, board, socket, light...)."""
    return bridge(M.place_mep_terminal, kind, level, x, y, "" if z is None else z, rotation, system)


@tool("mep.run", {"required": ["level", "kind", "points"], "properties": {
    "level": _LEVEL, "kind": {"type": "string", "enum": ["duct", "pipe", "cable_tray"]}, "points": _POINTS3,
    "width": {"type": "number", "description": "Width, or a pipe's diameter (m)."},
    "height": {"type": "number"}, "system": _SYSTEM,
    "system_kind": {"type": "string", "enum": list(M.SYSTEM_KINDS), "description": "For a new system."}}},
    writes=True)
def mep_run(session, level, kind, points, width=0.3, height=0.2, system="", system_kind=""):
    """Draw a connected duct/pipe/tray run through 3D points with elbows; its ends join touching ports
    or tee into a segment they land on."""
    return bridge(M.create_mep_run3d, level, kind, json.dumps(points), width, height, system, system_kind)


@tool("mep.drain_run", {"required": ["level", "points", "start_z"], "properties": {
    "level": _LEVEL, "points": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
                                "description": "Plan points [[x, y], ...] downhill."},
    "start_z": {"type": "number", "description": "Height of the first point above the level."},
    "slope": {"type": "number", "description": "Fraction (0.02 = 2 %); default from the settings."},
    "diameter": {"type": "number"}, "system": _SYSTEM}}, writes=True)
def mep_drain_run(session, level, points, start_z, slope=None, diameter=0.11, system=""):
    """Draw a drain pipe falling at a slope through plan points."""
    return bridge(D.create_drain_run, level, json.dumps(points), start_z, "" if slope is None else slope,
                  diameter, system)


@tool("mep.connect", {"properties": {"system": _SYSTEM}}, writes=True)
def mep_connect(session, system=""):
    """Connect every pair of free ports that touch (one system, or the whole model)."""
    return bridge(M.connect_network, system)


@tool("mep.network", {"required": ["system"], "properties": {"system": _SYSTEM}})
def mep_network(session, system):
    """A system's network: its source, tree, unreached elements, open ports and loops."""
    return bridge(M.mep_network, system)


@tool("mep.set_design", {"required": ["element", "values"], "properties": {
    "element": {"type": "string"}, "values": {"type": ["object", "string"],
                                              "description": "Flow (L/s), LoadingUnits, DischargeUnits, Area, ApparentPower..."}}},
      writes=True)
def mep_set_design(session, element, values):
    """Set an MEP element's design values."""
    return bridge(M.set_design_values, element, _json(values))


@tool("hvac.size", {"required": ["system"], "properties": {"system": _SYSTEM}})
def hvac_size(session, system):
    """Room airflows, duct sizes (equal friction, velocity limits), pressure drop and fan duty for an air system."""
    return bridge(H.size_air_system, system, False)


@tool("hvac.apply_sizes", {"required": ["system"], "properties": {"system": _SYSTEM}}, writes=True)
def hvac_apply_sizes(session, system):
    """Write the air system's duct sizes and design flows (one undo step)."""
    return bridge(H.size_air_system, system, True)


@tool("plumbing.size", {"required": ["system"], "properties": {"system": _SYSTEM}})
def plumbing_size(session, system):
    """Peak flows, pipe sizes and the pressure left at each fixture for a cold or hot water system."""
    return bridge(P.size_water_system, system, False)


@tool("plumbing.apply_sizes", {"required": ["system"], "properties": {"system": _SYSTEM}}, writes=True)
def plumbing_apply_sizes(session, system):
    """Write the water system's pipe sizes and design values (one undo step)."""
    return bridge(P.size_water_system, system, True)


@tool("drainage.size", {"required": ["system"], "properties": {"system": _SYSTEM}})
def drainage_size(session, system):
    """Sanitary or storm flows, pipe and stack sizes and slope checks for a drainage system."""
    return bridge(D.size_drainage_system, system, False)


@tool("drainage.apply_sizes", {"required": ["system"], "properties": {"system": _SYSTEM}}, writes=True)
def drainage_apply_sizes(session, system):
    """Write the drainage system's pipe sizes (one undo step)."""
    return bridge(D.size_drainage_system, system, True)


@tool("electrical.circuits", {"properties": {"board": {"type": "string"}}})
def electrical_circuits(session, board=""):
    """List the distribution boards and circuits."""
    return bridge(El.circuits, board)


@tool("electrical.create_circuit", {"required": ["board", "devices"], "properties": {
    "board": {"type": "string"}, "devices": _GUIDS, "name": {"type": "string"},
    "phase": {"type": "string", "enum": list(El.PHASES)}, "kind": {"type": "string", "enum": list(El.KINDS)}}},
      writes=True)
def electrical_create_circuit(session, board, devices, name="", phase="auto", kind=""):
    """Create a circuit from a board to devices."""
    return bridge(El.create_circuit, board, json.dumps(list(devices)), name, phase, kind)


@tool("electrical.panel_schedule", {"required": ["board"], "properties": {"board": {"type": "string"}}})
def electrical_panel_schedule(session, board):
    """A board's circuits with breakers, cables, voltage drop, phase loads and the main breaker."""
    return bridge(El.panel_schedule, board, False)


@tool("electrical.apply_schedule", {"required": ["board"], "properties": {"board": {"type": "string"}}}, writes=True)
def electrical_apply_schedule(session, board):
    """Write the board's chosen breakers, cables and balanced phases to its circuits (one undo step)."""
    return bridge(El.panel_schedule, board, True)


@tool("structure.analyse", {})
def structure_analyse(session):
    """Analyse the structure: loads from the model, a frame solve, member utilisation and deflection checks."""
    return bridge(SA.analyse_structure, False)


@tool("structure.save_results", {}, writes=True)
def structure_save_results(session):
    """Analyse and store the results on the members and the IFC analysis model (one undo step)."""
    return bridge(SA.analyse_structure, True)


@tool("structure.results", {})
def structure_results(session):
    """The stored structural results on the members (from the last applied analysis)."""
    return bridge(SA.structure_results)


@tool("engineering.settings", {"required": ["discipline"], "properties": {"discipline": _DISCIPLINE}})
def engineering_settings(session, discipline):
    """Read a discipline's engineering settings and their defaults."""
    return bridge(E.engineering_settings, discipline)


@tool("engineering.set_settings", {"required": ["discipline", "changes"], "properties": {
    "discipline": _DISCIPLINE, "changes": {"type": ["object", "string"]}}}, writes=True)
def engineering_set_settings(session, discipline, changes):
    """Change some of a discipline's engineering settings (codes, limits, tables)."""
    return bridge(E.set_engineering_settings, discipline, _json(changes))
