# SPDX-License-Identifier: GPL-3.0-or-later
"""Locating a project on the map (D253) and `kimbim project new`."""
import json
import math

import pytest

from kimbim import app_bridge as B
from kimbim import authoring as A
from kimbim import site as SITE


def test_transverse_mercator_matches_reference_points():
    # Montevideo, Palacio Salvo: UTM 21S, east of the central meridian (57 W) -> negative convergence
    e, n, g = SITE.transverse_mercator(-34.9067, -56.1990, 21, True)
    assert 572_000 < e < 574_500 and 6_136_000 < n < 6_138_000
    assert -0.6 < g < -0.3
    # on the central meridian: easting 500 000, no convergence; equator: northing 0 (north) / 10 000 000 (south)
    e, n, g = SITE.transverse_mercator(0.0, -57.0, 21, False)
    assert e == pytest.approx(500_000, abs=1e-6) and n == pytest.approx(0, abs=1e-6) and g == pytest.approx(0)
    e, n, _ = SITE.transverse_mercator(0.0, -57.0, 21, True)
    assert n == pytest.approx(10_000_000, abs=1e-6)
    # one degree of latitude along the central meridian is ~110.6 km at the equator, scaled by k0
    _, n1, _ = SITE.transverse_mercator(1.0, -57.0, 21, False)
    assert n1 == pytest.approx(110_574.4 * 0.9996, rel=2e-4)


def test_crs_specs():
    assert SITE._crs_info("auto", -34.9, -56.2)["name"] == "EPSG:32721"
    assert SITE._crs_info("EPSG:5382", -34.9, -56.2)["datum"] == "SIRGAS-ROU98"
    assert SITE._crs_info("UTM 21S", -34.9, -56.2)["zone"] == 21
    assert SITE._crs_info("EPSG:31982", -30.0, -51.0)["map_zone"] == "22S"
    with pytest.raises(ValueError):
        SITE._crs_info("EPSG:4326", 0, 0)


def test_compound_angles_round_trip():
    for value in (-34.9145, -56.164, 0.0001, 51.4778):
        assert SITE._degrees(SITE._compound(value)) == pytest.approx(value, abs=1e-9)


def test_locate_sets_site_map_conversion_and_true_north():
    A.new_project("Casa", "IFC4")
    out = json.loads(SITE.locate(json.dumps({"latitude": -34.9145, "longitude": -56.164, "elevation": 22,
                                             "north": 18, "crs": "EPSG:5382", "address": "Br. España 2200",
                                             "town": "Montevideo", "country": "Uruguay"})))
    assert out["ok"], out
    f = B._model
    site = f.by_type("IfcSite")[0]
    assert SITE._degrees(site.RefLatitude) == pytest.approx(-34.9145)
    assert out["elevation"] == pytest.approx(22.0)
    assert site.SiteAddress.Town == "Montevideo"
    conversion = f.by_type("IfcMapConversion")[0]
    assert conversion.TargetCRS.Name == "EPSG:5382"
    assert conversion.TargetCRS.MapUnit.Name == "METRE"
    assert conversion.Scale == pytest.approx(0.001)  # millimetre model -> metre map
    assert conversion.Eastings == pytest.approx(out["eastings"], abs=1e-3)
    # the model's +Y has grid bearing north - convergence: X axis = (cos b, -sin b)
    beta = math.radians(18 - out["convergence"])
    assert conversion.XAxisAbscissa == pytest.approx(math.cos(beta))
    assert conversion.XAxisOrdinate == pytest.approx(-math.sin(beta))
    assert out["georeference"]["true_north"] == pytest.approx(18.0)
    # undo puts it all back as one step
    assert json.loads(B.undo()).get("ok", True)
    assert not f.by_type("IfcMapConversion") or B._model.by_type("IfcSite")[0].RefLatitude is None


def test_locate_refuses_bad_input():
    A.new_project("Casa", "IFC4")
    assert not json.loads(SITE.locate(json.dumps({"latitude": 95, "longitude": 0})))["ok"]
    assert not json.loads(SITE.locate(json.dumps({"longitude": 0})))["ok"]


def test_cli_project_new_makes_a_georeferenced_folder(tmp_path, capsys):
    from kimbim.agent.cli import main

    target = tmp_path / "casa"
    code = main(["--json", "project", "new", str(target), "--name", "Casa", "--number", "2026-001",
                 "--client-name", "Familia", "--lat", "-34.9145", "--lon", "-56.164", "--crs", "EPSG:5382",
                 "--level", "Planta baja=0", "--level", "Planta alta=3"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["crs"] == "EPSG:5382" and out["levels"] == ["Planta baja", "Planta alta"]
    assert any(target.iterdir())
    assert main(["project", "new", str(target)]) == 1  # not empty: refused
