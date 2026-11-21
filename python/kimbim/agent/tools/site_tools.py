# SPDX-License-Identifier: GPL-3.0-or-later
"""Tools about where the project is and what it is called (D253): site.get, site.locate, project.get_info,
project.set_info."""
from __future__ import annotations

import json

from ... import sheets as SH
from ... import site as SITE
from ..catalogue import bridge, tool


@tool("site.get", {})
def site_get(session):
    """Where the project is: the site's latitude, longitude, elevation and address, and its map conversion
    (CRS, eastings, northings, height, rotation) and true north."""
    out = bridge(SITE.site_state)
    out.pop("ok", None)
    return out


@tool("site.locate", {"required": ["latitude", "longitude"], "properties": {
    "latitude": {"type": "number", "description": "Decimal degrees, south negative (Montevideo -34.9)."},
    "longitude": {"type": "number", "description": "Decimal degrees, west negative (Montevideo -56.2)."},
    "elevation": {"type": "number", "description": "Metres above sea level of the project's zero (default 0)."},
    "north": {"type": "number", "description": "Degrees the building's +Y axis is turned clockwise from true "
                                               "north; 0 when +Y points north (default 0)."},
    "crs": {"type": "string", "description": "auto (WGS 84 / UTM of the longitude, the default), EPSG:5382 "
                                             "(SIRGAS-ROU98 / UTM 21S, Uruguay), a UTM EPSG code or \"UTM 21S\"."},
    "site_name": {"type": "string"},
    "address": {"type": "string", "description": "Street and number."},
    "town": {"type": "string"}, "region": {"type": "string"}, "country": {"type": "string"},
    "postal_code": {"type": "string"}}}, writes=True)
def site_locate(session, latitude, longitude, **values):
    """Place the project on the map: sets the site's latitude/longitude/elevation and address, an IFC map
    conversion from the project origin to projected coordinates (eastings/northings computed for the CRS) and
    true north. Exported IFC files are then georeferenced."""
    out = bridge(SITE.locate, json.dumps({"latitude": latitude, "longitude": longitude, **values}))
    out.pop("ok", None)
    return out


@tool("project.get_info", {})
def get_info(session):
    """The project information the title blocks show: number, name, client, address and the like."""
    out = bridge(SH.project_info)
    out.pop("ok", None)
    return out


@tool("project.set_info", {"properties": {
    "number": {"type": "string", "description": "Project number, e.g. \"2026-014\"."},
    "name": {"type": "string", "description": "Project name, e.g. \"Casa Parque Rodó\"."},
    "client_name": {"type": "string", "description": "The client, e.g. \"Familia Pérez\"."},
    "address": {"type": "string"}}}, writes=True)
def set_info(session, client_name=None, **info):
    """Set the project information the title blocks show (number, name, client, address); empty strings clear."""
    if client_name is not None:
        info["client"] = client_name
    bridge(SH.set_project_info, json.dumps(info))
    out = bridge(SH.project_info)
    out.pop("ok", None)
    return out
