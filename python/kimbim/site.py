# SPDX-License-Identifier: GPL-3.0-or-later
"""Locating a project on the map (D253): latitude/longitude -> IfcSite reference and an IFC map conversion.

The projected coordinates come from our own transverse Mercator (Krüger series, accurate to well under a
millimetre inside a UTM zone), so no projection library is needed. Supported CRSs: WGS 84 / UTM (EPSG:326zz
north, 327zz south), SIRGAS 2000 / UTM (EPSG:31965–31985), SIRGAS-ROU98 / UTM 21S (EPSG:5382, Uruguay) and
SIRGAS-ROU98 / UTM 22S (EPSG:5383). SIRGAS and WGS 84 differ by centimetres, below what a site plan shows.

`locate(...)` sets the IfcSite RefLatitude/RefLongitude/RefElevation (and its address), the map conversion
(project origin -> eastings/northings/height, rotation from the building's north angle and the grid
convergence) and true north, as one undo step.
"""
from __future__ import annotations

import json
import math

from . import app_bridge as B

# WGS 84 / GRS 80 (identical to the millimetre at these scales)
_A = 6378137.0
_F = 1 / 298.257223563
_K0 = 0.9996


def utm_zone(lon: float) -> int:
    return int((lon + 180.0) // 6.0) % 60 + 1


def _crs_info(crs: str, lat: float, lon: float) -> dict:
    """Zone, hemisphere, EPSG name and datum for a CRS spec ("auto", "EPSG:5382", "UTM 21S", ...)."""
    spec = (crs or "auto").strip().upper().replace(" ", "")
    south = lat < 0
    zone = utm_zone(lon)
    datum = "WGS84"
    if spec in ("", "AUTO"):
        code = (32700 if south else 32600) + zone
    elif spec.startswith("EPSG:"):
        code = int(spec[5:])
        if 32601 <= code <= 32660 or 32701 <= code <= 32760:
            zone, south = code % 100, code >= 32700
        elif 31965 <= code <= 31976:  # SIRGAS 2000 / UTM 11N-22N
            zone, south, datum = code - 31954, False, "SIRGAS2000"
        elif 31977 <= code <= 31985:  # SIRGAS 2000 / UTM 17S-25S
            zone, south, datum = code - 31960, True, "SIRGAS2000"
        elif code == 5382:
            zone, south, datum = 21, True, "SIRGAS-ROU98"
        elif code == 5383:
            zone, south, datum = 22, True, "SIRGAS-ROU98"
        else:
            raise ValueError(f"unsupported CRS {crs}: use auto, a UTM EPSG code (326zz/327zz), SIRGAS 2000 / UTM "
                             "(31965-31985) or SIRGAS-ROU98 (5382, 5383)")
    elif spec.startswith("UTM"):
        body = spec[3:]
        zone, south = int(body[:-1]), body[-1] == "S"
        code = (32700 if south else 32600) + zone
    else:
        raise ValueError(f"unsupported CRS {crs}")
    return {"code": code, "name": f"EPSG:{code}", "zone": zone, "south": south, "datum": datum,
            "map_zone": f"{zone}{'S' if south else 'N'}"}


def transverse_mercator(lat: float, lon: float, zone: int, south: bool) -> tuple[float, float, float]:
    """(easting, northing, grid convergence in degrees: the bearing of grid north from true north) in UTM `zone` — Krüger's n-series to n^4."""
    lon0 = math.radians(zone * 6 - 183)
    phi, lam = math.radians(lat), math.radians(lon) - lon0
    n = _F / (2 - _F)
    big_a = _A / (1 + n) * (1 + n ** 2 / 4 + n ** 4 / 64)
    alpha = (n / 2 - 2 * n ** 2 / 3 + 5 * n ** 3 / 16 + 41 * n ** 4 / 180,
             13 * n ** 2 / 48 - 3 * n ** 3 / 5 + 557 * n ** 4 / 1440,
             61 * n ** 3 / 240 - 103 * n ** 4 / 140,
             49561 * n ** 4 / 161280)
    e = math.sqrt(_F * (2 - _F))
    t = math.sinh(math.atanh(math.sin(phi)) - e * math.atanh(e * math.sin(phi)))
    xi_p = math.atan2(t, math.cos(lam))
    eta_p = math.atanh(math.sin(lam) / math.sqrt(1 + t * t))
    xi, eta = xi_p, eta_p
    sigma, tau = 1.0, 0.0
    for j, a in enumerate(alpha, start=1):
        xi += a * math.sin(2 * j * xi_p) * math.cosh(2 * j * eta_p)
        eta += a * math.cos(2 * j * xi_p) * math.sinh(2 * j * eta_p)
        sigma += 2 * j * a * math.cos(2 * j * xi_p) * math.cosh(2 * j * eta_p)
        tau += 2 * j * a * math.sin(2 * j * xi_p) * math.sinh(2 * j * eta_p)
    easting = 500000.0 + _K0 * big_a * eta
    northing = _K0 * big_a * xi + (10000000.0 if south else 0.0)
    gamma = math.atan2(tau * math.sqrt(1 + t * t) + sigma * t * math.tan(lam),
                       sigma * math.sqrt(1 + t * t) - tau * t * math.tan(lam))
    return easting, northing, math.degrees(gamma)


def _compound(value: float) -> list[int]:
    """Degrees -> IfcCompoundPlaneAngleMeasure (degrees, minutes, seconds, millionths), all with one sign."""
    sign = -1 if value < 0 else 1
    v = abs(value)
    d = int(v)
    m = int((v - d) * 60)
    s_full = (v - d - m / 60) * 3600
    s = int(s_full)
    micro = int(round((s_full - s) * 1e6))
    if micro >= 1_000_000:
        s, micro = s + 1, micro - 1_000_000
    return [sign * d, sign * m, sign * s, sign * micro]


def _degrees(compound) -> float | None:
    if not compound:
        return None
    parts = list(compound) + [0, 0, 0, 0]
    return parts[0] + parts[1] / 60 + parts[2] / 3600 + parts[3] / 3.6e9


def _fail(message: str) -> str:
    return B._dump({"ok": False, "error": message})


def site_state() -> str:
    if B._model is None:
        return _fail("no model open")
    from . import georef

    site = next(iter(B._model.by_type("IfcSite")), None)
    out = {"ok": True, "latitude": None, "longitude": None, "elevation": None, "address": {}}
    if site is not None:
        out["latitude"] = _degrees(site.RefLatitude)
        out["longitude"] = _degrees(site.RefLongitude)
        import ifcopenshell.util.unit

        scale = ifcopenshell.util.unit.calculate_unit_scale(B._model)
        out["elevation"] = round(float(site.RefElevation) * scale, 6) if site.RefElevation is not None else None
        out["name"] = site.Name or ""
        address = getattr(site, "SiteAddress", None)
        if address is not None:
            out["address"] = {"lines": list(address.AddressLines or []), "town": address.Town or "",
                              "region": address.Region or "", "country": address.Country or "",
                              "postal_code": address.PostalCode or ""}
    state = json.loads(georef.georef_state())
    state.pop("ok", None)
    # Say the units: a bare "rotation": -0.48 reads as radians to a model (it is degrees, the grid convergence).
    state["units"] = {"eastings": "metres (map unit)", "northings": "metres (map unit)", "height": "metres",
                      "rotation": "degrees; for a north of 0 this is minus the grid convergence at the site",
                      "true_north": "degrees the project's +Y axis is turned clockwise from true north",
                      "scale": "map units per model length unit (0.001 when the model is in millimetres)"}
    out["georeference"] = state
    return B._dump(out)


def locate(values_json: str) -> str:
    """{latitude, longitude, elevation?, north?, crs?, site_name?, address?, town?, region?, country?,
    postal_code?}. `north`: degrees the building's +Y axis is turned clockwise from true north (0: +Y points
    north). `elevation`: metres above sea level of the project's zero."""
    if B._model is None:
        return _fail("no model open")
    try:
        values = json.loads(values_json or "{}")
        lat, lon = float(values["latitude"]), float(values["longitude"])
        if not (-80.0 <= lat <= 84.0) or not (-180.0 <= lon <= 180.0):
            raise ValueError("latitude must be within -80..84 (UTM) and longitude within -180..180")
        elevation = float(values.get("elevation") or 0.0)
        north = float(values.get("north") or 0.0)
        info = _crs_info(str(values.get("crs") or "auto"), lat, lon)
    except (KeyError, TypeError, ValueError) as ex:
        return _fail(f"bad values: {ex}")
    easting, northing, gamma = transverse_mercator(lat, lon, info["zone"], info["south"])

    def action():
        import ifcopenshell.api

        f = B._model
        site = next(iter(f.by_type("IfcSite")), None)
        if site is None:
            raise ValueError("the project has no site")
        site.RefLatitude = _compound(lat)
        site.RefLongitude = _compound(lon)
        import ifcopenshell.util.unit

        site.RefElevation = elevation / ifcopenshell.util.unit.calculate_unit_scale(f)  # project length units
        if values.get("site_name"):
            site.Name = str(values["site_name"])
        lines = values.get("address")
        if any(values.get(k) for k in ("address", "town", "region", "country", "postal_code")):
            address = site.SiteAddress or f.createIfcPostalAddress(Purpose="SITE")
            if lines:
                address.AddressLines = [lines] if isinstance(lines, str) else [str(x) for x in lines]
            for key, attr in (("town", "Town"), ("region", "Region"), ("country", "Country"),
                              ("postal_code", "PostalCode")):
                if values.get(key):
                    setattr(address, attr, str(values[key]))
            site.SiteAddress = address
        if not f.by_type("IfcMapConversion"):
            ifcopenshell.api.georeference.add_georeferencing(f, name=info["name"])
        # The model's +Y has bearing `north` from true north, grid north has bearing `gamma`, so +Y's grid bearing
        # is beta = north - gamma and the model's X axis in map coordinates is (cos beta, -sin beta).
        beta = math.radians(north - gamma)
        ifcopenshell.api.georeference.edit_georeferencing(
            f, coordinate_operation={"Eastings": easting, "Northings": northing, "OrthogonalHeight": elevation,
                                     "XAxisAbscissa": math.cos(beta), "XAxisOrdinate": -math.sin(beta),
                                     "Scale": 1.0},
            projected_crs={"Name": info["name"], "Description": f"{info['datum']} / UTM zone {info['map_zone']}",
                           "GeodeticDatum": info["datum"], "MapProjection": "UTM", "MapZone": info["map_zone"]})
        conversion = f.by_type("IfcMapConversion")[0]
        crs = conversion.TargetCRS
        if getattr(crs, "MapUnit", None) is None:  # eastings/northings/height are metres, whatever the model unit
            crs.MapUnit = f.createIfcSIUnit(UnitType="LENGTHUNIT", Name="METRE")
        conversion.Scale = ifcopenshell.util.unit.calculate_unit_scale(f)  # model units -> metres (map units)
        # True north in model coordinates: +Y turned anticlockwise by `north`.
        a = math.radians(north)
        for ctx in f.by_type("IfcGeometricRepresentationContext"):
            if not ctx.is_a("IfcGeometricRepresentationSubContext") and ctx.ContextType == "Model":
                ctx.TrueNorth = f.createIfcDirection((-math.sin(a), math.cos(a)))
        return 1

    try:
        B._run(action)
    except Exception as ex:  # noqa: BLE001
        return _fail(f"{type(ex).__name__}: {ex}")
    out = json.loads(site_state())
    out["crs"] = info["name"]
    out["eastings"], out["northings"], out["convergence"] = round(easting, 3), round(northing, 3), round(gamma, 6)
    return B._dump(out)
