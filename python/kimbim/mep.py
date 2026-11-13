# SPDX-License-Identifier: GPL-3.0-or-later
"""MEP network core (D242): ports, connections, terminals and equipment, systems, traversal.

Every MEP element NicBim makes carries ``IfcDistributionPort``s at its connection points. A port is
placed relative to its element (so it moves with it) and records its flow direction, its port type
(DUCT, PIPE, CABLE...) and the *system kind* it belongs to (supply air, cold water, sanitary...) in
``SystemType`` plus ``Description`` (IFC2X3 ports only have a flow direction, so the kind lives in
``Description`` there). Ports that touch are connected with ``IfcRelConnectsPorts``.

A distribution system (``IfcDistributionSystem``; ``IfcSystem`` in IFC2X3) has a kind from
:data:`SYSTEM_KINDS`. :func:`network` walks a system from its source (an air handler, the water
main, a water heater, a distribution board, or for drainage the outlet to the sewer) and reports
the tree, the parts it cannot reach and the open ports. The calculations (hvac, plumbing,
drainage, electrical) run on that tree.

Lengths are metres. Every edit is one undo step.
"""
from __future__ import annotations

import copy
import json
import math

import ifcopenshell
import ifcopenshell.api.geometry
import ifcopenshell.api.group
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.system
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.system
import numpy as np

from . import app_bridge as B
from . import authoring as A

MEP_PSET = "KIMBIM_MEP"
DESIGN_PSET = "KIMBIM_MEPDesign"
SYSTEM_PSET = "KIMBIM_System"

# kind -> domain, IFC IfcDistributionSystemEnum value, colour, English label
SYSTEM_KINDS: dict[str, dict] = {
    "supply_air": {"domain": "air", "predefined": "AIRCONDITIONING", "colour": "#2f7fe0", "label": "Supply air"},
    "return_air": {"domain": "air", "predefined": "VENTILATION", "colour": "#9b51e0", "label": "Return air"},
    "exhaust_air": {"domain": "air", "predefined": "EXHAUST", "colour": "#d4a017", "label": "Exhaust air"},
    "outside_air": {"domain": "air", "predefined": "VENTILATION", "colour": "#27ae60", "label": "Outside air"},
    "cold_water": {"domain": "water", "predefined": "DOMESTICCOLDWATER", "colour": "#1abc9c", "label": "Domestic cold water"},
    "hot_water": {"domain": "water", "predefined": "DOMESTICHOTWATER", "colour": "#e74c3c", "label": "Domestic hot water"},
    "sanitary": {"domain": "drainage", "predefined": "SEWAGE", "colour": "#8d6e63", "label": "Sanitary drainage"},
    "storm": {"domain": "drainage", "predefined": "STORMWATER", "colour": "#5d8aa8", "label": "Storm water"},
    "vent": {"domain": "drainage", "predefined": "VENT", "colour": "#95a5a6", "label": "Vent"},
    "power": {"domain": "electrical", "predefined": "ELECTRICAL", "colour": "#e67e22", "label": "Power"},
    "lighting": {"domain": "electrical", "predefined": "LIGHTING", "colour": "#f1c40f", "label": "Lighting"},
    "data": {"domain": "electrical", "predefined": "DATA", "colour": "#34495e", "label": "Data"},
}
DOMAIN_PORT_TYPE = {"air": "DUCT", "water": "PIPE", "drainage": "PIPE", "electrical": "CABLE"}
SEGMENT_DOMAINS = {"duct": ("air",), "pipe": ("water", "drainage"), "cable_tray": ("electrical",)}
SEGMENT_DEFAULT_KIND = {"duct": "supply_air", "pipe": "cold_water", "cable_tray": "power"}
SEGMENT_CLASSES = {"duct": ("IfcDuctSegment", "Duct"), "pipe": ("IfcPipeSegment", "Pipe"),
                   "cable_tray": ("IfcCableCarrierSegment", "Cable tray")}
FITTING_CLASSES = {"duct": "IfcDuctFitting", "pipe": "IfcPipeFitting", "cable_tray": "IfcCableCarrierFitting"}
# IFC4 class -> IFC2X3 class (IFC2X3 has only the generic distribution flow elements)
IFC2X3_CLASS = {
    "IfcDuctSegment": "IfcFlowSegment", "IfcPipeSegment": "IfcFlowSegment", "IfcCableCarrierSegment": "IfcFlowSegment",
    "IfcDuctFitting": "IfcFlowFitting", "IfcPipeFitting": "IfcFlowFitting", "IfcCableCarrierFitting": "IfcFlowFitting",
    "IfcAirTerminal": "IfcFlowTerminal", "IfcSanitaryTerminal": "IfcFlowTerminal", "IfcWasteTerminal": "IfcFlowTerminal",
    "IfcOutlet": "IfcFlowTerminal", "IfcLightFixture": "IfcFlowTerminal", "IfcElectricAppliance": "IfcFlowTerminal",
    "IfcUnitaryEquipment": "IfcEnergyConversionDevice", "IfcBoiler": "IfcEnergyConversionDevice",
    "IfcFan": "IfcFlowMovingDevice", "IfcPump": "IfcFlowMovingDevice", "IfcFlowMeter": "IfcFlowController",
    "IfcElectricDistributionBoard": "IfcElectricDistributionPoint", "IfcSwitchingDevice": "IfcFlowController",
}
SOURCE_CLASSES = ("IfcUnitaryEquipment", "IfcFan", "IfcBoiler", "IfcFlowMeter", "IfcElectricDistributionBoard",
                  "IfcElectricDistributionPoint", "IfcAirToAirHeatRecovery", "IfcChiller", "IfcTank")


def _p(system, x=0.0, y=0.0, z=0.0, direction="SINK"):
    return {"system": system, "offset": [x, y, z], "direction": direction}


# Terminals and equipment. size = (width x, depth y, height z) of a box whose base centre is the
# insertion point; port offsets are in that local frame (rotated with the element). `z` is the
# default height of the base above the level. Design values follow EN 806-3 (LoadingUnits),
# EN 12056-2 system I (DischargeUnits), IPC (WSFU, DFU) and typical loads (VA).
CATALOGUE: dict[str, dict] = {
    "supply_diffuser": {"label": "Supply diffuser", "cls": "IfcAirTerminal", "predefined": "DIFFUSER",
                        "size": (0.6, 0.6, 0.05), "z": 2.7, "role": "terminal",
                        "ports": [_p("supply_air", 0, 0, 0.05)], "design": {"Flow": 0.0, "NeckDiameter": 0.2}},
    "return_grille": {"label": "Return grille", "cls": "IfcAirTerminal", "predefined": "GRILLE",
                      "size": (0.6, 0.3, 0.05), "z": 2.7, "role": "terminal",
                      "ports": [_p("return_air", 0, 0, 0.05, "SOURCE")], "design": {"Flow": 0.0, "NeckDiameter": 0.2}},
    "exhaust_valve": {"label": "Exhaust valve", "cls": "IfcAirTerminal", "predefined": "REGISTER",
                      "size": (0.2, 0.2, 0.05), "z": 2.7, "role": "terminal",
                      "ports": [_p("exhaust_air", 0, 0, 0.05, "SOURCE")], "design": {"Flow": 0.0, "NeckDiameter": 0.125}},
    "ahu": {"label": "Air handling unit", "cls": "IfcUnitaryEquipment", "predefined": "AIRHANDLER",
            "size": (2.0, 1.0, 1.5), "z": 0.0, "role": "source",
            "ports": [_p("supply_air", -0.5, 0, 1.5, "SOURCE"), _p("return_air", 0.5, 0, 1.5, "SINK"),
                      _p("power", 1.0, 0, 0.3, "SINK")],
            "design": {"ApparentPower": 3000.0, "LoadClass": "hvac"}},
    "fan": {"label": "Fan", "cls": "IfcFan", "predefined": "CENTRIFUGALFORWARDCURVED", "size": (0.5, 0.5, 0.5),
            "z": 2.5, "role": "source",
            "ports": [_p("exhaust_air", 0, -0.25, 0.25, "SINK"), _p("exhaust_air", 0, 0.25, 0.25, "SOURCE"),
                      _p("power", 0.25, 0, 0.25, "SINK")],
            "design": {"ApparentPower": 500.0, "LoadClass": "hvac"}},
    "wc": {"label": "WC", "cls": "IfcSanitaryTerminal", "predefined": "TOILETPAN", "size": (0.4, 0.7, 0.4),
           "z": 0.0, "role": "terminal",
           "ports": [_p("cold_water", 0.1, 0.3, 0.2), _p("sanitary", 0, 0.25, 0.0, "SOURCE")],
           "design": {"LoadingUnits": 1.0, "SupplyFlow": 0.1, "DischargeUnits": 2.0, "WSFU": 2.2, "DFU": 3.0,
                      "DrainDN": 90.0}},
    "basin": {"label": "Wash basin", "cls": "IfcSanitaryTerminal", "predefined": "WASHHANDBASIN",
              "size": (0.6, 0.45, 0.15), "z": 0.8, "role": "terminal",
              "ports": [_p("cold_water", -0.1, 0.2, 0.0), _p("hot_water", 0.1, 0.2, 0.0),
                        _p("sanitary", 0, 0.15, 0.0, "SOURCE")],
              "design": {"LoadingUnits": 1.0, "SupplyFlow": 0.1, "DischargeUnits": 0.5, "WSFU": 1.0, "DFU": 1.0,
                         "DrainDN": 40.0}},
    "sink": {"label": "Kitchen sink", "cls": "IfcSanitaryTerminal", "predefined": "SINK", "size": (0.8, 0.5, 0.2),
             "z": 0.7, "role": "terminal",
             "ports": [_p("cold_water", -0.1, 0.22, 0.0), _p("hot_water", 0.1, 0.22, 0.0),
                       _p("sanitary", 0, 0.15, 0.0, "SOURCE")],
             "design": {"LoadingUnits": 2.0, "SupplyFlow": 0.2, "DischargeUnits": 0.8, "WSFU": 1.4, "DFU": 2.0,
                        "DrainDN": 50.0}},
    "shower": {"label": "Shower", "cls": "IfcSanitaryTerminal", "predefined": "SHOWER", "size": (0.9, 0.9, 0.05),
               "z": 0.0, "role": "terminal",
               "ports": [_p("cold_water", -0.1, 0.42, 1.0), _p("hot_water", 0.1, 0.42, 1.0),
                         _p("sanitary", 0, 0, 0.0, "SOURCE")],
               "design": {"LoadingUnits": 2.0, "SupplyFlow": 0.2, "DischargeUnits": 0.6, "WSFU": 1.4, "DFU": 2.0,
                          "DrainDN": 50.0}},
    "bath": {"label": "Bath", "cls": "IfcSanitaryTerminal", "predefined": "BATH", "size": (1.7, 0.7, 0.55),
             "z": 0.0, "role": "terminal",
             "ports": [_p("cold_water", -0.75, -0.1, 0.55), _p("hot_water", -0.75, 0.1, 0.55),
                       _p("sanitary", -0.7, 0, 0.0, "SOURCE")],
             "design": {"LoadingUnits": 4.0, "SupplyFlow": 0.4, "DischargeUnits": 0.8, "WSFU": 1.4, "DFU": 2.0,
                        "DrainDN": 50.0}},
    "urinal": {"label": "Urinal", "cls": "IfcSanitaryTerminal", "predefined": "URINAL", "size": (0.35, 0.3, 0.6),
               "z": 0.5, "role": "terminal",
               "ports": [_p("cold_water", 0, 0.15, 0.6), _p("sanitary", 0, 0.1, 0.0, "SOURCE")],
               "design": {"LoadingUnits": 3.0, "SupplyFlow": 0.3, "DischargeUnits": 0.5, "WSFU": 5.0, "DFU": 2.0,
                          "DrainDN": 50.0}},
    "washing_machine": {"label": "Washing machine", "cls": "IfcElectricAppliance", "predefined": "WASHINGMACHINE",
                        "size": (0.6, 0.6, 0.85), "z": 0.0, "role": "terminal",
                        "ports": [_p("cold_water", 0, 0.3, 0.8), _p("sanitary", 0.1, 0.3, 0.5, "SOURCE"),
                                  _p("power", -0.2, 0.3, 0.3)],
                        "design": {"LoadingUnits": 2.0, "SupplyFlow": 0.2, "DischargeUnits": 0.8, "WSFU": 4.0,
                                   "DFU": 3.0, "DrainDN": 50.0, "ApparentPower": 2200.0, "LoadClass": "appliance"}},
    "dishwasher": {"label": "Dishwasher", "cls": "IfcElectricAppliance", "predefined": "DISHWASHER",
                   "size": (0.6, 0.6, 0.85), "z": 0.0, "role": "terminal",
                   "ports": [_p("cold_water", 0, 0.3, 0.1), _p("sanitary", 0.1, 0.3, 0.4, "SOURCE"),
                             _p("power", -0.2, 0.3, 0.3)],
                   "design": {"LoadingUnits": 2.0, "SupplyFlow": 0.2, "DischargeUnits": 0.8, "WSFU": 1.4, "DFU": 2.0,
                              "DrainDN": 50.0, "ApparentPower": 2000.0, "LoadClass": "appliance"}},
    "floor_drain": {"label": "Floor drain", "cls": "IfcWasteTerminal", "predefined": "FLOORTRAP",
                    "size": (0.15, 0.15, 0.05), "z": 0.0, "role": "terminal",
                    "ports": [_p("sanitary", 0, 0, 0.0, "SOURCE")],
                    "design": {"DischargeUnits": 0.8, "DFU": 2.0, "DrainDN": 50.0}},
    "roof_drain": {"label": "Roof drain", "cls": "IfcWasteTerminal", "predefined": "ROOFDRAIN",
                   "size": (0.3, 0.3, 0.1), "z": 0.0, "role": "terminal",
                   "ports": [_p("storm", 0, 0, 0.0, "SOURCE")], "design": {"Area": 0.0, "DrainDN": 75.0}},
    "drain_outlet": {"label": "Drain outlet (to sewer)", "cls": "IfcPipeFitting", "predefined": "CONNECTOR",
                     "size": (0.2, 0.2, 0.2), "z": -0.5, "role": "source",
                     "ports": [_p("sanitary", 0, 0, 0.1, "SINK")], "design": {}},
    "water_main": {"label": "Water main / meter", "cls": "IfcFlowMeter", "predefined": "WATERMETER",
                   "size": (0.3, 0.2, 0.2), "z": 0.3, "role": "source",
                   "ports": [_p("cold_water", 0.15, 0, 0.1, "SOURCE")], "design": {"Pressure": 0.0}},
    "water_heater": {"label": "Water heater", "cls": "IfcBoiler", "predefined": "WATER", "size": (0.5, 0.5, 1.2),
                     "z": 0.0, "role": "source",
                     "ports": [_p("cold_water", -0.1, 0, 1.2, "SINK"), _p("hot_water", 0.1, 0, 1.2, "SOURCE"),
                               _p("power", 0.25, 0, 0.3, "SINK")],
                     "design": {"ApparentPower": 3000.0, "LoadClass": "appliance"}},
    "pump": {"label": "Pump", "cls": "IfcPump", "predefined": "ENDSUCTION", "size": (0.4, 0.3, 0.3), "z": 0.0,
             "role": "inline",
             "ports": [_p("cold_water", -0.2, 0, 0.15, "SINK"), _p("cold_water", 0.2, 0, 0.15, "SOURCE"),
                       _p("power", 0, 0.15, 0.15, "SINK")],
             "design": {"ApparentPower": 750.0, "LoadClass": "hvac"}},
    "board": {"label": "Distribution board", "cls": "IfcElectricDistributionBoard", "predefined": "DISTRIBUTIONBOARD",
              "size": (0.5, 0.15, 0.7), "z": 1.2, "role": "source",
              "ports": [_p("power", 0, 0, 0.7, "SOURCE")], "design": {"Phases": 3.0}},
    "socket": {"label": "Socket outlet", "cls": "IfcOutlet", "predefined": "POWEROUTLET", "size": (0.08, 0.04, 0.08),
               "z": 0.3, "role": "terminal", "ports": [_p("power", 0, 0, 0.04)],
               "design": {"ApparentPower": 200.0, "LoadClass": "power"}},
    "light": {"label": "Light fixture", "cls": "IfcLightFixture", "predefined": "POINTSOURCE",
              "size": (0.6, 0.6, 0.08), "z": 2.62, "role": "terminal", "ports": [_p("lighting", 0, 0, 0.08)],
              "design": {"ApparentPower": 40.0, "PowerFactor": 0.9, "LoadClass": "lighting"}},
    "switch": {"label": "Switch", "cls": "IfcSwitchingDevice", "predefined": "TOGGLESWITCH", "size": (0.08, 0.04, 0.08),
               "z": 1.1, "role": "inline", "ports": [_p("lighting", 0, 0, 0.04)], "design": {}},
    "appliance": {"label": "Electric appliance", "cls": "IfcElectricAppliance", "predefined": "NOTDEFINED",
                  "size": (0.6, 0.6, 0.9), "z": 0.0, "role": "terminal", "ports": [_p("power", 0, 0.3, 0.3)],
                  "design": {"ApparentPower": 2000.0, "LoadClass": "appliance"}},
}


def _fail(message: str) -> str:
    return A._fail(message)


def _schema_class(name: str) -> str:
    if B._model.schema == "IFC2X3":
        return IFC2X3_CLASS.get(name, name)
    return name


def _enum_ok(entity: str, attribute: str, value: str) -> bool:
    try:
        decl = ifcopenshell.ifcopenshell_wrapper.schema_by_name(B._model.schema_identifier).declaration_by_name(entity)
        for a in decl.all_attributes():
            if a.name() == attribute:
                t = a.type_of_attribute()
                while hasattr(t, "declared_type"):
                    t = t.declared_type()
                return value in t.enumeration_items()
    except Exception:  # noqa: BLE001
        return False
    return False


def _set_predefined(element, value: str) -> None:
    if not hasattr(element, "PredefinedType") or not value:
        if value and hasattr(element, "ObjectType"):
            element.ObjectType = value
        return
    if _enum_ok(element.is_a(), "PredefinedType", value):
        element.PredefinedType = value
    elif _enum_ok(element.is_a(), "PredefinedType", "USERDEFINED"):
        element.PredefinedType = "USERDEFINED"
        element.ObjectType = value


# ---------------------------------------------------------------- ports

def _matrix(element) -> np.ndarray:
    """The element's placement in metres (rotation unchanged, translation scaled)."""
    m = np.array(ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement), dtype=float)
    m[:3, 3] *= A._scale()
    return m


def port_kind(port) -> str:
    """The port's system kind (`SYSTEM_KINDS` key), from its Description or its SystemType."""
    d = (getattr(port, "Description", None) or "").strip()
    if d in SYSTEM_KINDS:
        return d
    st = getattr(port, "SystemType", None)
    for k, v in SYSTEM_KINDS.items():
        if st and v["predefined"] == st:
            return k
    pt = getattr(port, "PredefinedType", None)
    return {"DUCT": "supply_air", "PIPE": "cold_water", "CABLE": "power", "CABLECARRIER": "power"}.get(pt, "")


def _set_port_kind(port, kind: str) -> None:
    port.Description = kind
    info = SYSTEM_KINDS.get(kind)
    if info is None:
        return
    if hasattr(port, "SystemType") and _enum_ok("IfcDistributionPort", "SystemType", info["predefined"]):
        port.SystemType = info["predefined"]
    if hasattr(port, "PredefinedType"):
        port.PredefinedType = DOMAIN_PORT_TYPE[info["domain"]]


def add_ports(element, specs: list[dict]) -> list:
    """Inside an action: ports on `element` at world points (metres). spec: point, direction, system."""
    f = B._model
    s = A._scale()
    inverse = np.linalg.inv(_matrix(element))
    out = []
    for i, spec in enumerate(specs):
        port = ifcopenshell.api.system.add_port(f, element=element)
        port.Name = f"Port {i + 1}"
        port.FlowDirection = spec.get("direction", "SOURCEANDSINK")
        _set_port_kind(port, spec.get("system", ""))
        local = inverse @ np.array([*map(float, spec["point"]), 1.0])
        axis = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint(tuple(float(v) / s for v in local[:3])), None, None)
        port.ObjectPlacement = f.createIfcLocalPlacement(element.ObjectPlacement, axis)
        out.append(port)
    return out


def port_points(element) -> list:
    """[(port, world point in metres)] for the element's ports."""
    out = []
    s = A._scale()
    for port in ifcopenshell.util.system.get_ports(element):
        if port.ObjectPlacement is None:
            out.append((port, _matrix(element)[:3, 3]))
            continue
        m = np.array(ifcopenshell.util.placement.get_local_placement(port.ObjectPlacement), dtype=float)
        out.append((port, m[:3, 3] * s))
    return out


def _port_element(port):
    return ifcopenshell.util.system.get_port_element(port)


def _connected(port):
    return ifcopenshell.util.system.get_connected_port(port)


def _connect(a, b) -> None:
    """Connect two ports keeping their own flow directions (the api would overwrite them)."""
    da, db = a.FlowDirection, b.FlowDirection
    ifcopenshell.api.system.connect_port(B._model, port1=a, port2=b)
    a.FlowDirection, b.FlowDirection = da, db


def _disconnect(port) -> None:
    if _connected(port) is not None:
        ifcopenshell.api.system.disconnect_port(B._model, port=port)


def _free_ports(exclude=()) -> list:
    """[(port, point)] of every unconnected port in the model, skipping elements in `exclude`."""
    out = []
    skip = {e.id() for e in exclude}
    seen = set()
    for port in B._model.by_type("IfcDistributionPort"):
        if _connected(port) is not None:
            continue
        element = _port_element(port)
        if element is None or element.id() in skip:
            continue
        if element.id() in seen:
            continue
        seen.add(element.id())
        for p, point in port_points(element):
            if _connected(p) is None:
                out.append((p, point))
    return out


def _tolerance() -> float:
    from . import engsettings

    return float(engsettings.get("mep_settings")["connect_tolerance"])


def _compatible(a, b) -> bool:
    ka, kb = port_kind(a), port_kind(b)
    if not ka or not kb:
        return True
    return SYSTEM_KINDS.get(ka, {}).get("domain") == SYSTEM_KINDS.get(kb, {}).get("domain")


def _autoconnect(ports_points: list, exclude=()) -> int:
    """Inside an action: connect each given free port to a free port of another element at the same point."""
    tol = _tolerance()
    others = _free_ports(exclude)
    n = 0
    used = set()
    for port, point in ports_points:
        if _connected(port) is not None:
            continue
        best, best_d = None, tol
        for other, q in others:
            if other.id() in used or other == port or _port_element(other) == _port_element(port):
                continue
            d = float(np.linalg.norm(np.asarray(q) - np.asarray(point)))
            if d <= best_d and _compatible(port, other):
                best, best_d = other, d
        if best is not None:
            _connect(port, best)
            used.add(best.id())
            used.add(port.id())
            n += 1
    return n


# ---------------------------------------------------------------- segments

def _segment_matrix(p1: np.ndarray, d: np.ndarray) -> np.ndarray:
    up = np.array([0.0, 0.0, 1.0])
    side = np.cross(up, d)
    if np.linalg.norm(side) < 1e-6:  # vertical: local X along world X
        side = np.array([1.0, 0.0, 0.0])
    side /= np.linalg.norm(side)
    y = np.cross(d, side)
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = side, y, d, p1
    return m


def _segment_kind(element) -> str:
    data = ifcopenshell.util.element.get_pset(element, MEP_PSET) or {}
    if data.get("Kind") in SEGMENT_CLASSES:
        return data["Kind"]
    for k, (cls, _label) in SEGMENT_CLASSES.items():
        if element.is_a(cls):
            return k
    return "pipe"


def _new_segment(storey, kind: str, p1, p2, width: float, height: float, system_kind: str = ""):
    """Inside an action: a straight segment from p1 to p2 (world metres) with ports at both ends."""
    f = B._model
    s = A._scale()
    p1, p2 = np.asarray(p1, float), np.asarray(p2, float)
    length = float(np.linalg.norm(p2 - p1))
    ifc_class, label = SEGMENT_CLASSES[kind]
    segment = ifcopenshell.api.root.create_entity(f, ifc_class=_schema_class(ifc_class), name=label)
    if hasattr(segment, "PredefinedType") and f.schema != "IFC2X3":
        _set_predefined(segment, "RIGIDSEGMENT" if kind != "cable_tray" else "CABLETRAYSEGMENT")
    origin = f.createIfcAxis2Placement2D(f.createIfcCartesianPoint((0.0, 0.0)), None)
    if kind == "pipe":
        profile = f.createIfcCircleProfileDef("AREA", None, origin, width / 2 / s)
    else:
        profile = f.createIfcRectangleProfileDef("AREA", None, origin, width / s, height / s)
    representation = ifcopenshell.api.geometry.add_profile_representation(
        f, context=A._body_context(), profile=profile, depth=length)
    ifcopenshell.api.geometry.assign_representation(f, product=segment, representation=representation)
    d = (p2 - p1) / length
    ifcopenshell.api.geometry.edit_object_placement(f, product=segment, matrix=_segment_matrix(p1, d), is_si=True)
    ifcopenshell.api.spatial.assign_container(f, products=[segment], relating_structure=storey)
    level = A._elevation(storey)
    horizontal = math.hypot(*(p2 - p1)[:2])
    pset = ifcopenshell.api.pset.add_pset(f, product=segment, name=MEP_PSET)
    ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={
        "Kind": kind, "Width": width, "Height": width if kind == "pipe" else height,
        "Elevation": round(float(p1[2]) - level, 6), "Length": round(length, 6),
        "Slope": round(float(p1[2] - p2[2]) / horizontal, 6) if horizontal > 1e-6 else 0.0})
    system_kind = system_kind or SEGMENT_DEFAULT_KIND[kind]
    add_ports(segment, [{"point": p1, "direction": "SINK", "system": system_kind},
                        {"point": p2, "direction": "SOURCE", "system": system_kind}])
    from . import layers, renovation

    layers.assign_active(segment)
    renovation.stamp_new(segment)
    return segment


def segment_ends(element) -> tuple[np.ndarray, np.ndarray] | None:
    """World start and end of a straight MEP segment (metres); for a tessellated segment, the ends of
    its shape's long axis."""
    m = _matrix(element)
    rep = getattr(element, "Representation", None)
    for shape in (rep.Representations if rep else ()):
        for item in shape.Items or ():
            if item.is_a("IfcExtrudedAreaSolid"):
                start = m[:3, 3]
                return start, start + m[:3, 2] * float(item.Depth) * A._scale()
    if element.is_a("IfcFlowSegment"):
        est = _mesh_estimate(element)
        if est is not None:
            return est[0], est[1]
    return None


def is_estimated(element) -> bool:
    """True when a segment has no extrusion and its ends and size come from its shape."""
    rep = getattr(element, "Representation", None)
    for shape in (rep.Representations if rep else ()):
        for item in shape.Items or ():
            if item.is_a("IfcExtrudedAreaSolid"):
                return False
    return True


def _mesh_estimate(element):
    from . import structanalysis

    try:
        return structanalysis.mesh_member(element)
    except Exception:  # noqa: BLE001 - odd geometry: no estimate
        return None


def segment_size(element) -> tuple[float, float, str]:
    """(width or diameter, height, "round"|"rect") in metres, from the profile."""
    s = A._scale()
    rep = getattr(element, "Representation", None)
    for shape in (rep.Representations if rep else ()):
        for item in shape.Items or ():
            if item.is_a("IfcExtrudedAreaSolid"):
                p = item.SweptArea
                if p.is_a("IfcCircleProfileDef"):
                    return 2 * float(p.Radius) * s, 2 * float(p.Radius) * s, "round"
                if p.is_a("IfcRectangleProfileDef"):
                    return float(p.XDim) * s, float(p.YDim) * s, "rect"
    data = ifcopenshell.util.element.get_pset(element, MEP_PSET) or {}
    if not data and element.is_a("IfcFlowSegment"):
        est = _mesh_estimate(element)
        if est is not None:
            b, h = est[3]["b"], est[3]["h"]
            if _segment_kind(element) == "pipe":
                return max(b, h), max(b, h), "round"
            return b, h, "rect"
    return float(data.get("Width") or 0.1), float(data.get("Height") or 0.1), "round" if _segment_kind(element) == "pipe" else "rect"


def end_ports(segment) -> tuple:
    """((start port, point), (end port, point)) of a straight segment, matched by position."""
    ports = port_points(segment)
    ends = segment_ends(segment)
    if ends is None or len(ports) < 2:
        return tuple(ports[:2])
    a, _b = ends
    ports.sort(key=lambda pq: float(np.linalg.norm(pq[1] - a)))
    return ports[0], ports[-1]


def _storey_and_level(storey_guid):
    storey = A._by_guid(storey_guid)
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return None, 0.0
    return storey, A._elevation(storey)


def create_mep_segment3d(storey_guid: str, kind: str, x1, y1, z1, x2, y2, z2, width=0.3, height=0.2,
                         system: str = "") -> str:
    """A straight duct, pipe or cable tray between two 3D points (z above the level): risers and sloped runs."""
    return _segment3d(storey_guid, kind, x1, y1, z1, x2, y2, z2, width, height, system)


def _segment3d(storey_guid: str, kind: str, x1, y1, z1, x2, y2, z2, width=0.3, height=0.2,
               system: str = "") -> str:
    """A straight duct, pipe or cable tray between two 3D points; z is above the level. Vertical
    (risers) and sloped runs work. Ports at both ends join free ports they touch."""
    if B._model is None:
        return _fail("no model open")
    kind = str(kind or "").strip().lower()
    if kind not in SEGMENT_CLASSES:
        return _fail("the run is a duct, pipe or cable_tray")
    storey, level = _storey_and_level(storey_guid)
    if storey is None:
        return _fail("unknown level")
    try:
        x1, y1, z1, x2, y2, z2, width, height = (float(v) for v in (x1, y1, z1, x2, y2, z2, width, height))
    except (TypeError, ValueError) as ex:
        return _fail(str(ex))
    p1, p2 = np.array([x1, y1, level + z1]), np.array([x2, y2, level + z2])
    if np.linalg.norm(p2 - p1) < 0.01:
        return _fail("the run needs two different points")
    if not 0.005 <= width <= 5 or (kind != "pipe" and not 0.005 <= height <= 5):
        return _fail("the run's size is out of range")
    group = _find_system(system) if system else None
    if system and group is None:
        return _fail(f"unknown system {system}")
    made = {}

    def action():
        segment = _new_segment(storey, kind, p1, p2, width, height, system_kind(group) if group else "")
        if group is not None:
            ifcopenshell.api.group.assign_group(B._model, products=[segment], group=group)
        _autoconnect(port_points(segment), exclude=[segment])
        made["guid"] = segment.GlobalId
        return 1, [segment.GlobalId], []

    try:
        r = B._run(action)
    except Exception as ex:  # noqa: BLE001
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["guid"], "length": round(float(np.linalg.norm(p2 - p1)), 6)})


def _fitting(storey, kind: str, point, size: float, height: float, predefined: str, n_ports: int, system_kind: str):
    """Inside an action: an elbow/tee block centred on `point` with `n_ports` ports there."""
    f = B._model
    cls = _schema_class(FITTING_CLASSES[kind])
    fitting = ifcopenshell.api.root.create_entity(f, ifc_class=cls, name="Elbow" if predefined == "BEND" else "Tee")
    if cls != "IfcFlowFitting":
        _set_predefined(fitting, predefined)
    s = A._scale()
    origin = f.createIfcAxis2Placement2D(f.createIfcCartesianPoint((0.0, 0.0)), None)
    profile = f.createIfcRectangleProfileDef("AREA", None, origin, size / s, size / s)
    representation = ifcopenshell.api.geometry.add_profile_representation(
        f, context=A._body_context(), profile=profile, depth=height)
    ifcopenshell.api.geometry.assign_representation(f, product=fitting, representation=representation)
    m = np.eye(4)
    m[:3, 3] = (point[0], point[1], point[2] - height / 2)
    ifcopenshell.api.geometry.edit_object_placement(f, product=fitting, matrix=m, is_si=True)
    ifcopenshell.api.spatial.assign_container(f, products=[fitting], relating_structure=storey)
    pset = ifcopenshell.api.pset.add_pset(f, product=fitting, name=MEP_PSET)
    ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={"Kind": kind, "Fitting": predefined})
    add_ports(fitting, [{"point": point, "direction": "SOURCEANDSINK", "system": system_kind}] * n_ports)
    from . import layers, renovation

    layers.assign_active(fitting)
    renovation.stamp_new(fitting)
    return fitting


def _segment_hit(point, kind: str, exclude=()):
    """A segment of the same kind whose centreline passes through `point` away from its ends."""
    tol = max(_tolerance(), 0.01)
    skip = {e.id() for e in exclude}
    cls = SEGMENT_CLASSES[kind][0]
    candidates = B._model.by_type(_schema_class(cls))
    for seg in candidates:
        if seg.id() in skip:
            continue
        if B._model.schema == "IFC2X3" and _segment_kind(seg) != kind:
            continue
        ends = segment_ends(seg)
        if ends is None:
            continue
        a, b = ends
        ab = b - a
        L = float(np.linalg.norm(ab))
        if L < 1e-6:
            continue
        t = float(np.dot(np.asarray(point) - a, ab) / (L * L))
        if t * L <= tol or (1 - t) * L <= tol:
            continue
        closest = a + ab * t
        if np.linalg.norm(closest - np.asarray(point)) <= tol:
            return seg, closest
    return None, None


def _split_with_tee(storey, seg, point, system_kind_for_tee: str):
    """Inside an action: cut `seg` at `point` into two segments joined by a tee; returns the tee's
    free (third) port. The far part keeps the original's systems and its far connection."""
    f = B._model
    kind = _segment_kind(seg)
    width, height, _shape = segment_size(seg)
    a, b = segment_ends(seg)
    point = np.asarray(point, float)
    # the original keeps a->point
    end_port = end_ports(seg)[1][0]
    far = _connected(end_port) if end_port is not None else None
    if end_port is not None and far is not None:
        _disconnect(end_port)
    s = A._scale()
    for shape in seg.Representation.Representations:
        for item in shape.Items or ():
            if item.is_a("IfcExtrudedAreaSolid"):
                item.Depth = float(np.linalg.norm(point - a)) / s
    if end_port is not None:
        inverse = np.linalg.inv(_matrix(seg))
        local = inverse @ np.array([*point, 1.0])
        end_port.ObjectPlacement.RelativePlacement.Location.Coordinates = tuple(float(v) / s for v in local[:3])
    pset = ifcopenshell.util.element.get_pset(seg, MEP_PSET)
    if pset:
        ifcopenshell.api.pset.edit_pset(f, pset=f.by_id(pset["id"]),
                                        properties={"Length": round(float(np.linalg.norm(point - a)), 6)})
    seg_kind = port_kind(end_port) if end_port is not None else SEGMENT_DEFAULT_KIND[kind]
    rest = _new_segment(storey, kind, point, b, width, height, seg_kind)
    for group in _groups(seg):
        ifcopenshell.api.group.assign_group(f, products=[rest], group=group)
    rest_ports = end_ports(rest)
    if far is not None:
        _connect(rest_ports[1][0], far)
    size = width if kind == "pipe" else max(width, height)
    tee = _fitting(storey, kind, point, size * 1.05, (width if kind == "pipe" else height) * 1.05, "JUNCTION", 3,
                   seg_kind)
    for group in _groups(seg):
        ifcopenshell.api.group.assign_group(f, products=[tee], group=group)
    tee_ports = [p for p, _q in port_points(tee)]
    if end_port is not None:
        _connect(end_port, tee_ports[0])
    _connect(rest_ports[0][0], tee_ports[1])
    return tee, tee_ports[2], rest


def _groups(element) -> list:
    return [rel.RelatingGroup for rel in getattr(element, "HasAssignments", ()) or ()
            if rel.is_a("IfcRelAssignsToGroup") and rel.RelatingGroup.is_a("IfcSystem")]


def create_mep_run3d(storey_guid: str, kind: str, points_json: str, width=0.3, height=0.2, system: str = "",
                     system_kind: str = "") -> str:
    """A run through 3D points [[x, y, z above the level], ...]: elbows at bends, connected, in a system."""
    return _run3d(storey_guid, kind, points_json, width, height, system, system_kind)


def _run3d(storey_guid: str, kind: str, points_json: str, width=0.3, height=0.2, system: str = "",
           system_kind_name: str = "") -> str:
    """A run of segments through 3D points [[x, y, z above the level], ...] with an elbow at each bend,
    connected port to port, in a system (a name or GlobalId; made when new, of `system_kind_name`).
    Its first and last points join a free port they touch, or tee into a segment they land on."""
    if B._model is None:
        return _fail("no model open")
    kind = str(kind or "").strip().lower()
    if kind not in SEGMENT_CLASSES:
        return _fail("the run is a duct, pipe or cable_tray")
    try:
        pts = [tuple(float(v) for v in p) for p in json.loads(points_json)]
        width, height = float(width), float(height)
    except (TypeError, ValueError) as ex:
        return _fail(str(ex))
    if any(len(p) != 3 for p in pts):
        return _fail("each point is [x, y, z]")
    storey, level = _storey_and_level(storey_guid)
    if storey is None:
        return _fail("unknown level")
    pts = [np.array([x, y, level + z]) for x, y, z in pts]
    pts = [p for i, p in enumerate(pts) if i == 0 or np.linalg.norm(p - pts[i - 1]) > 0.01]
    if len(pts) < 2:
        return _fail("the run needs two different points")
    if not 0.005 <= width <= 5 or (kind != "pipe" and not 0.005 <= height <= 5):
        return _fail("the run's size is out of range")
    sk = (system_kind_name or "").strip()
    if sk and sk not in SYSTEM_KINDS:
        return _fail(f"unknown system kind {sk}")
    if sk and SYSTEM_KINDS[sk]["domain"] not in SEGMENT_DOMAINS[kind]:
        return _fail(f"a {kind.replace('_', ' ')} cannot carry {SYSTEM_KINDS[sk]['label'].lower()}")
    made = {"segments": [], "fittings": [], "tees": []}
    changed: list = []

    def action():
        f = B._model
        group = _find_system(system) if system else None
        if group is None:
            name = (system or "").strip() or f"{SEGMENT_CLASSES[kind][1]} system"
            group = _make_system(name, sk or SEGMENT_DEFAULT_KIND[kind])
        gkind = system_kind(group) or sk or SEGMENT_DEFAULT_KIND[kind]
        segments = [_new_segment(storey, kind, a, b, width, height, gkind) for a, b in zip(pts, pts[1:])]
        size = width if kind == "pipe" else max(width, height)
        h = width if kind == "pipe" else height
        fittings = []
        for (s1, s2), point in zip(zip(segments, segments[1:]), pts[1:-1]):
            d1 = pts[segments.index(s1) + 1] - pts[segments.index(s1)]
            d2 = pts[segments.index(s2) + 1] - pts[segments.index(s2)]
            cos = float(np.dot(d1, d2) / (np.linalg.norm(d1) * np.linalg.norm(d2)))
            if cos > 0.9995:  # straight on: join directly, no elbow
                _connect(end_ports(s1)[1][0], end_ports(s2)[0][0])
                continue
            elbow = _fitting(storey, kind, point, size, h, "BEND", 2, gkind)
            fittings.append(elbow)
            ep = [p for p, _q in port_points(elbow)]
            _connect(end_ports(s1)[1][0], ep[0])
            _connect(ep[1], end_ports(s2)[0][0])
        ifcopenshell.api.group.assign_group(f, products=segments + fittings, group=group)
        own = segments + fittings
        # the run's two open ends: a free port there, else a segment to tee into
        for port, point in (end_ports(segments[0])[0], end_ports(segments[-1])[1]):
            if _autoconnect([(port, point)], exclude=own):
                continue
            hit, closest = _segment_hit(point, kind, exclude=own)
            if hit is not None:
                tee, free, rest = _split_with_tee(storey, hit, closest, gkind)
                _connect(port, free)
                made["tees"].append(tee.GlobalId)
                changed.extend([hit.GlobalId, rest.GlobalId, tee.GlobalId])
                own = own + [tee, rest]
        made["segments"] = [x.GlobalId for x in segments]
        made["fittings"] = [x.GlobalId for x in fittings]
        made["system"] = group.Name
        made["system_guid"] = group.GlobalId
        everything = made["segments"] + made["fittings"] + changed
        return len(everything), everything, []

    try:
        r = B._run(action)
    except Exception as ex:  # noqa: BLE001
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, **made})


# ---------------------------------------------------------------- terminals and equipment

def catalogue() -> dict:
    """The catalogue with the project's design-value overrides (mep_settings.catalogue)."""
    from . import engsettings

    over = engsettings.get("mep_settings").get("catalogue") or {}
    out = copy.deepcopy(CATALOGUE)
    for kind, values in over.items():
        if kind in out and isinstance(values, dict):
            out[kind]["design"].update(values)
    return out


def mep_catalogue() -> str:
    cat = catalogue()
    return B._dump({"ok": True, "kinds": [
        {"kind": k, "label": v["label"], "class": v["cls"], "role": v["role"], "z": v["z"], "size": list(v["size"]),
         "systems": sorted({p["system"] for p in v["ports"]}), "design": v["design"]} for k, v in cat.items()],
        "system_kinds": [{"kind": k, **v} for k, v in SYSTEM_KINDS.items()]})


def _place(storey, kind: str, x: float, y: float, z: float | None, rotation: float):
    """Inside an action: the catalogue element placed with its base centre at (x, y, level + z)."""
    f = B._model
    entry = catalogue()[kind]
    cls = _schema_class(entry["cls"])
    element = ifcopenshell.api.root.create_entity(f, ifc_class=cls, name=entry["label"])
    if cls == entry["cls"]:
        _set_predefined(element, entry["predefined"])
    else:
        element.ObjectType = entry["predefined"]
    s = A._scale()
    w, d, h = entry["size"]
    origin = f.createIfcAxis2Placement2D(f.createIfcCartesianPoint((0.0, 0.0)), None)
    profile = f.createIfcRectangleProfileDef("AREA", None, origin, w / s, d / s)
    representation = ifcopenshell.api.geometry.add_profile_representation(
        f, context=A._body_context(), profile=profile, depth=h)
    ifcopenshell.api.geometry.assign_representation(f, product=element, representation=representation)
    level = A._elevation(storey)
    z = entry["z"] if z is None else z
    a = math.radians(rotation)
    m = np.eye(4)
    m[:3, 0] = (math.cos(a), math.sin(a), 0.0)
    m[:3, 1] = (-math.sin(a), math.cos(a), 0.0)
    m[:3, 3] = (x, y, level + z)
    ifcopenshell.api.geometry.edit_object_placement(f, product=element, matrix=m, is_si=True)
    ifcopenshell.api.spatial.assign_container(f, products=[element], relating_structure=storey)
    pset = ifcopenshell.api.pset.add_pset(f, product=element, name=DESIGN_PSET)
    ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={"Kind": kind, "Role": entry["role"], **entry["design"]})
    specs = []
    for port in entry["ports"]:
        world = m @ np.array([*port["offset"], 1.0])
        specs.append({"point": world[:3], "direction": port["direction"], "system": port["system"]})
    add_ports(element, specs)
    from . import layers, renovation

    layers.assign_active(element)
    renovation.stamp_new(element)
    return element


def place_mep_terminal(kind: str, storey_guid: str, x, y, z="", rotation=0.0, system: str = "") -> str:
    """Place a terminal or piece of equipment from the catalogue; z is its base above the level
    (blank: the catalogue height). With `system` (a name or GlobalId) it joins that system."""
    if B._model is None:
        return _fail("no model open")
    kind = str(kind or "").strip()
    if kind not in CATALOGUE:
        return _fail(f"unknown MEP kind {kind}")
    storey, _level = _storey_and_level(storey_guid)
    if storey is None:
        return _fail("unknown level")
    try:
        x, y, rotation = float(x), float(y), float(rotation or 0)
        zz = None if z in ("", None) else float(z)
    except (TypeError, ValueError) as ex:
        return _fail(str(ex))
    group = _find_system(system) if system else None
    if system and group is None:
        return _fail(f"unknown system {system}")
    made = {}

    def action():
        element = _place(storey, kind, x, y, zz, rotation)
        if group is not None:
            _join(group, [element])
        _autoconnect(port_points(element), exclude=[element])
        made["guid"] = element.GlobalId
        return 1, [element.GlobalId], []

    try:
        r = B._run(action)
    except Exception as ex:  # noqa: BLE001
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["guid"]})


def design_values(element) -> dict:
    return ifcopenshell.util.element.get_pset(element, DESIGN_PSET) or {}


def set_design_values(guid: str, values_json: str) -> str:
    """Change an element's MEP design values (Flow, LoadingUnits, ApparentPower...), one undo step."""
    if B._model is None:
        return _fail("no model open")
    element = A._by_guid(guid)
    if element is None:
        return _fail("unknown element")
    try:
        values = json.loads(values_json)
    except ValueError as ex:
        return _fail(str(ex))
    if not isinstance(values, dict) or not all(isinstance(v, (int, float, str)) and not isinstance(v, bool)
                                               for v in values.values()):
        return _fail("the design values are a table of numbers or texts")

    def action():
        f = B._model
        pset = ifcopenshell.util.element.get_pset(element, DESIGN_PSET)
        pset = f.by_id(pset["id"]) if pset else ifcopenshell.api.pset.add_pset(f, product=element, name=DESIGN_PSET)
        ifcopenshell.api.pset.edit_pset(f, pset=pset, properties=values)
        return 1

    try:
        r = B._run(action, affects_drawings=False)
    except Exception as ex:  # noqa: BLE001
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "values": design_values(element)})


# ---------------------------------------------------------------- systems

def _system_classes() -> tuple:
    return ("IfcDistributionSystem",) if B._model.schema != "IFC2X3" else ("IfcSystem",)


def all_systems() -> list:
    out = []
    for cls in ("IfcDistributionSystem", "IfcSystem"):
        try:
            found = B._model.by_type(cls, include_subtypes=False)
        except RuntimeError:
            continue
        out.extend(found)
    return out


def _find_system(name_or_guid: str):
    key = (name_or_guid or "").strip()
    if not key:
        return None
    for s in all_systems():
        if s.GlobalId == key or s.Name == key:
            return s
    return None


def system_kind(system) -> str:
    if system is None:
        return ""
    data = ifcopenshell.util.element.get_pset(system, SYSTEM_PSET) or {}
    if data.get("Kind") in SYSTEM_KINDS:
        return data["Kind"]
    pt = getattr(system, "PredefinedType", None)
    for k, v in SYSTEM_KINDS.items():
        if pt and v["predefined"] == pt:
            return k
    name = (system.Name or "").lower()  # IFC2X3 and other tools: the name often says
    for words, k in ((("supply air", "impuls"), "supply_air"), (("return air", "retorno"), "return_air"),
                     (("exhaust", "extrac", "flue"), "exhaust_air"), (("outside air", "fresh air"), "outside_air"),
                     (("hot water", "caliente"), "hot_water"), (("cold water", "fría", "fria", "water supply"), "cold_water"),
                     (("storm", "rain", "pluvial"), "storm"), (("waste", "sewage", "sewer", "sanitary", "drain",
                                                             "residual", "saneamiento"), "sanitary"),
                     (("vent",), "vent"), (("lighting", "alumbrado"), "lighting"), (("power", "fuerza"), "power")):
        if any(w in name for w in words):
            return k
    for e in system_members(system):  # an old D234 system: guess from its members' ports
        for port, _q in port_points(e):
            if port_kind(port):
                return port_kind(port)
    return ""


def system_members(system) -> list:
    return [e for rel in getattr(system, "IsGroupedBy", ()) or () for e in rel.RelatedObjects]


def _make_system(name: str, kind: str):
    """Inside an action: a new distribution system of `kind`."""
    f = B._model
    cls = _system_classes()[0]
    system = ifcopenshell.api.root.create_entity(f, ifc_class=cls, name=name)
    info = SYSTEM_KINDS.get(kind)
    if info and hasattr(system, "PredefinedType"):
        if _enum_ok(cls, "PredefinedType", info["predefined"]):
            system.PredefinedType = info["predefined"]
        else:
            system.PredefinedType = "USERDEFINED"
            system.ObjectType = info["label"]
    pset = ifcopenshell.api.pset.add_pset(f, product=system, name=SYSTEM_PSET)
    ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={"Kind": kind})
    return system


def _join(system, elements) -> None:
    """Inside an action: put elements in the system and give their ports of its domain its kind."""
    kind = system_kind(system)
    domain = SYSTEM_KINDS.get(kind, {}).get("domain")
    ifcopenshell.api.group.assign_group(B._model, products=list(elements), group=system)
    if not domain:
        return
    for e in elements:
        ports = port_points(e)
        same = [p for p, _q in ports if SYSTEM_KINDS.get(port_kind(p), {}).get("domain") == domain]
        # equipment with several kinds in one domain (an AHU's supply and return) keeps them
        kinds = {port_kind(p) for p in same}
        if len(kinds) <= 1:
            for p in same:
                _set_port_kind(p, kind)


def create_mep_system(name: str, kind: str) -> str:
    """A new distribution system of a kind (supply_air, cold_water, sanitary, power...)."""
    if B._model is None:
        return _fail("no model open")
    name = (name or "").strip()
    kind = (kind or "").strip()
    if not name:
        return _fail("the system needs a name")
    if kind not in SYSTEM_KINDS:
        return _fail(f"unknown system kind {kind}")
    if _find_system(name) is not None:
        return _fail(f"there is already a system called {name}")
    made = {}

    def action():
        made["guid"] = _make_system(name, kind).GlobalId
        return 1

    try:
        r = B._run(action, affects_drawings=False)
    except Exception as ex:  # noqa: BLE001
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["guid"]})


def assign_to_system(guids_json: str, system: str) -> str:
    """Put elements in a system (a name or GlobalId); their ports of its domain take its kind."""
    if B._model is None:
        return _fail("no model open")
    group = _find_system(system)
    if group is None:
        return _fail(f"unknown system {system}")
    try:
        guids = json.loads(guids_json)
    except ValueError as ex:
        return _fail(str(ex))
    elements = [A._by_guid(g) for g in guids]
    if not elements or any(e is None or not e.is_a("IfcElement") for e in elements):
        return _fail("select MEP elements")

    def action():
        _join(group, elements)
        return len(elements)

    try:
        r = B._run(action, affects_drawings=False)
    except Exception as ex:  # noqa: BLE001
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump(r)


def mep_systems() -> str:
    """The distribution systems: kind, domain, colour, element count and open ports."""
    if B._model is None:
        return _fail("no model open")
    out = []
    for s in all_systems():
        members = system_members(s)
        kind = system_kind(s)
        open_ports = sum(1 for e in members for p, _q in port_points(e) if _connected(p) is None)
        info = SYSTEM_KINDS.get(kind, {})
        out.append({"guid": s.GlobalId, "name": s.Name or "", "count": len(members), "kind": kind,
                    "domain": info.get("domain", ""), "colour": info.get("colour", "#888888"),
                    "label": info.get("label", ""), "open_ports": open_ports})
    return B._dump({"ok": True, "systems": out})


def delete_group(group) -> None:
    """Inside an action: delete a system or circuit and its property sets (its members stay)."""
    f = B._model
    for rel in list(getattr(group, "IsGroupedBy", ()) or ()):
        f.remove(rel)
    for rel in list(getattr(group, "IsDefinedBy", ()) or ()):
        if rel.is_a("IfcRelDefinesByProperties"):
            pset = rel.RelatingPropertyDefinition
            for prop in list(getattr(pset, "HasProperties", ()) or ()):
                f.remove(prop)
            f.remove(rel)
            f.remove(pset)
    f.remove(group)


def remove_mep_system(system: str) -> str:
    """Delete a system (its elements stay)."""
    if B._model is None:
        return _fail("no model open")
    group = _find_system(system)
    if group is None:
        return _fail(f"unknown system {system}")

    def action():
        delete_group(group)
        return 1

    try:
        r = B._run(action, affects_drawings=False)
    except Exception as ex:  # noqa: BLE001
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump(r)


# ---------------------------------------------------------------- network

def role(element) -> str:
    """source | terminal | inline | part (segments and fittings)."""
    data = design_values(element)
    if data.get("Role") in ("source", "terminal", "inline"):
        return data["Role"]
    if any(element.is_a(c) for c in SOURCE_CLASSES):
        return "source"
    if element.is_a("IfcFlowTerminal") or element.is_a("IfcDistributionChamberElement"):
        return "terminal"
    if element.is_a("IfcFlowSegment") or element.is_a("IfcFlowFitting"):
        return "part"
    return "inline"


def network(system) -> dict:
    """The system as a graph walked from its source(s):

    elements: {guid: element}; edges: [(guid, guid)] through connected ports; sources: [guid];
    tree: {guid: parent guid or None}; order: guids source-first (breadth first); unreached: guids;
    open_ports: [{guid, point}]; loops: number of extra connections (a tree has none).
    """
    kind = system_kind(system)
    members = [e for e in system_members(system) if e.is_a("IfcElement")]
    by_guid = {e.GlobalId: e for e in members}
    edges, adjacency = [], {g: [] for g in by_guid}
    open_ports = []
    seen_rel = set()
    for e in members:
        for port, point in port_points(e):
            other = _connected(port)
            if other is None:
                open_ports.append({"guid": e.GlobalId, "point": [round(float(v), 4) for v in point],
                                   "kind": port_kind(port)})
                continue
            oe = _port_element(other)
            if oe is None or oe.GlobalId not in by_guid:
                continue
            key = tuple(sorted((port.id(), other.id())))
            if key in seen_rel:
                continue
            seen_rel.add(key)
            edges.append((e.GlobalId, oe.GlobalId))
            adjacency[e.GlobalId].append(oe.GlobalId)
            adjacency[oe.GlobalId].append(e.GlobalId)
    sources = []
    for e in members:
        if role(e) != "source":
            continue
        ports = port_points(e)
        if not ports:
            continue
        if kind and SYSTEM_KINDS.get(kind, {}).get("domain") == "drainage":
            sources.append(e.GlobalId)  # the outlet: drainage flows towards it
        elif any(p.FlowDirection == "SOURCE" and (not kind or port_kind(p) in ("", kind)) for p, _q in ports):
            sources.append(e.GlobalId)
    if not sources and SYSTEM_KINDS.get(kind, {}).get("domain") == "drainage":
        lowest = min(open_ports, key=lambda o: o["point"][2], default=None)  # the lowest open pipe end
        if lowest is not None and role(by_guid[lowest["guid"]]) == "part":
            sources.append(lowest["guid"])
        else:  # no open end (a manhole network): drainage runs to its lowest point
            ranked = [(min(q[2] for _p, q in port_points(e)), role(e) == "part", g) for g, e in by_guid.items()
                      if port_points(e)]
            if ranked:
                sources.append(min(ranked)[2])
    tree, order = {}, []
    loops = 0
    for root in sources:
        if root in tree:
            continue
        tree[root] = None
        queue = [root]
        while queue:
            g = queue.pop(0)
            order.append(g)
            for n in adjacency[g]:
                if n not in tree:
                    tree[n] = g
                    queue.append(n)
    # loops: connections beyond a spanning tree of the reached part
    reached = set(tree)
    reached_edges = sum(1 for a, b in edges if a in reached and b in reached)
    loops = max(0, reached_edges - (len(reached) - len([s for s in sources if s in reached])))
    unreached = [g for g in by_guid if g not in tree]
    return {"kind": kind, "elements": by_guid, "edges": edges, "sources": sources, "tree": tree, "order": order,
            "unreached": unreached, "open_ports": open_ports, "loops": loops, "adjacency": adjacency}


def children(net: dict) -> dict:
    out = {g: [] for g in net["tree"]}
    for g, parent in net["tree"].items():
        if parent is not None:
            out[parent].append(g)
    return out


def mep_network(system: str) -> str:
    """The system's network: sources, tree, unreached parts, open ports and loops."""
    if B._model is None:
        return _fail("no model open")
    group = _find_system(system)
    if group is None:
        return _fail(f"unknown system {system}")
    net = network(group)
    issues = []
    if not net["sources"]:
        issues.append("the system has no source (an air handler, water main, heater, board or drain outlet)")
    if net["unreached"]:
        issues.append(f"{len(net['unreached'])} element(s) are not connected to the source")
    if net["loops"]:
        issues.append(f"the system has {net['loops']} loop(s); calculations follow one path to each part")
    elements = net["elements"]
    return B._dump({"ok": True, "system": group.Name, "kind": net["kind"], "sources": net["sources"],
                    "tree": net["tree"], "order": net["order"], "unreached": net["unreached"],
                    "open_ports": net["open_ports"], "loops": net["loops"], "issues": issues,
                    "elements": [{"guid": g, "name": e.Name or "", "class": e.is_a(), "role": role(e)}
                                 for g, e in elements.items()]})


def connect_network(system: str = "") -> str:
    """Join every pair of free ports that touch (within mep_settings.connect_tolerance), in one
    system or in the whole model. Elements without ports (files from other tools) get them first,
    inferred from their geometry. One undo step."""
    if B._model is None:
        return _fail("no model open")
    group = _find_system(system) if system else None
    if system and group is None:
        return _fail(f"unknown system {system}")
    made = {"connected": 0, "inferred": 0}

    def action():
        made["inferred"] = _infer_ports(system_members(group) if group is not None else None)
        free = _free_ports()
        if group is not None:
            ids = {e.id() for e in system_members(group)}
            free = [(p, q) for p, q in free if _port_element(p).id() in ids]
        tol = _tolerance()
        used = set()
        for i, (p, q) in enumerate(free):
            if p.id() in used:
                continue
            for p2, q2 in free[i + 1:]:
                if p2.id() in used or _port_element(p2) == _port_element(p):
                    continue
                reach = tol
                if INFERRED in (p.Name or "") or INFERRED in (p2.Name or ""):
                    reach = max(tol, 0.6 * max(_size_at(p), _size_at(p2)))  # meshes meet only roughly
                if np.linalg.norm(np.asarray(q) - np.asarray(q2)) <= reach and _compatible(p, p2):
                    _connect(p, p2)
                    used.update((p.id(), p2.id()))
                    made["connected"] += 1
                    break
        return made["connected"]

    try:
        r = B._run(action, affects_drawings=False)
    except Exception as ex:  # noqa: BLE001
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, **made})


INFERRED = "(inferred)"
INFER_REACH = 1.0  # m: how far from a chamber or terminal a pipe end may stop and still join it


def _size_at(port) -> float:
    e = _port_element(port)
    if e is None or not e.is_a("IfcFlowSegment"):
        return 0.0
    w, h, _shape = segment_size(e)
    return max(w, h)


def _infer_ports(members=None) -> int:
    """Inside an action: ports for MEP elements that have none (files from elsewhere): segments at
    their ends, chambers and terminals at the segment ends that stop near them. Returns how many."""
    f = B._model
    cls = "IfcDistributionElement" if f.schema != "IFC2X3" else "IfcDistributionFlowElement"
    pool = [e for e in (members if members is not None else f.by_type(cls)) if e.is_a(cls)]
    bare = [e for e in pool if not ifcopenshell.util.system.get_ports(e)]
    if not bare:
        return 0
    added = 0
    ends = []
    for e in bare:
        if not e.is_a("IfcFlowSegment"):
            continue
        got = segment_ends(e)
        if got is None:
            continue
        kind = system_kind(_groups(e)[0]) if _groups(e) else ""
        for port in add_ports(e, [{"point": got[0], "direction": "SINK", "system": kind},
                                  {"point": got[1], "direction": "SOURCE", "system": kind}]):
            port.Name = f"{port.Name} {INFERRED}"
            added += 1
        ends.extend([(e, got[0], kind), (e, got[1], kind)])
    for e in pool:  # segments that already had ports count as ends too
        if e.is_a("IfcFlowSegment") and e not in bare:
            ends.extend((e, q, port_kind(p)) for p, q in port_points(e) if _connected(p) is None)
    for e in bare:
        if e.is_a("IfcFlowSegment"):
            continue
        here = _matrix(e)[:3, 3]
        near = [(seg, q, kind) for seg, q, kind in ends if float(np.linalg.norm((q - here)[:2])) <= INFER_REACH]
        if near:
            ports = add_ports(e, [{"point": q, "direction": "SOURCEANDSINK", "system": kind} for _s, q, kind in near])
            for port in ports:
                port.Name = f"{port.Name} {INFERRED}"
            added += len(ports)
    return added


def mep_issues(model) -> dict:
    """For the Checks panel: {check: [(severity, message, elements)]} - parts with open ports, MEP
    elements in no system, and systems without a source."""
    open_ports, no_system, no_source = [], [], []
    previous = B._model
    B._model = model
    try:
        cls = "IfcDistributionElement" if model.schema != "IFC2X3" else "IfcDistributionFlowElement"
        for e in model.by_type(cls):
            ports = port_points(e)
            free = [p for p, _q in ports if _connected(p) is None]
            if free and role(e) == "part":
                open_ports.append(("warning", f"{e.Name or e.is_a()} has {len(free)} open port(s)", [e]))
            if ports and not _groups(e):
                no_system.append(("warning", f"{e.Name or e.is_a()} is in no system", [e]))
        for s in all_systems():
            members = system_members(s)
            if members and not network(s)["sources"]:
                no_source.append(("warning", f"The system {s.Name or ''} has no source", members[:50]))
    finally:
        B._model = previous
    return {"mep_open_ports": open_ports, "mep_no_system": no_system, "mep_no_source": no_source,
            "mep_sizing": _sizing_issues(model)}


def _sizing_issues(model) -> list:
    """Parts drawn smaller than the calculation proposes, and drainage slope problems (D243-D245)."""
    from . import drainage, hvac, plumbing

    out = []
    previous = B._model
    B._model = model
    try:
        for s in all_systems():
            domain = SYSTEM_KINDS.get(system_kind(s), {}).get("domain")
            sizer = {"air": hvac.size_air_system, "water": plumbing.size_water_system,
                     "drainage": drainage.size_drainage_system}.get(domain)
            if sizer is None or not system_members(s) or system_kind(s) == "vent":
                continue
            r = json.loads(sizer(s.GlobalId))
            if not r.get("ok"):
                continue
            for row in r.get("segments", []):
                e = model.by_guid(row["guid"])
                w, h, _shape = segment_size(e)
                want_w = row.get("width") or row.get("diameter") or 0
                want_h = row.get("height") or row.get("diameter") or 0
                if want_w and (w < want_w - 1e-4 or h < want_h - 1e-4):
                    out.append(("warning", f"{e.Name or 'Segment'} in {s.Name} is {round(w * 1000)} mm, the "
                                           f"calculation asks for {round(want_w * 1000)} mm", [e]))
                status = row.get("status", "ok")
                if domain == "drainage" and status not in ("ok", "no flow"):
                    out.append(("error" if "wrong way" in status else "warning",
                                f"{e.Name or 'Pipe'} in {s.Name}: {status}", [e]))
    finally:
        B._model = previous
    return out
