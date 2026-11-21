# SPDX-License-Identifier: GPL-3.0-or-later
"""The delivery package (D254) and the site/project-info tools (D253) through the agent catalogue."""
import json
import sys
import zipfile
from pathlib import Path

import pytest

from kimbim import documents as D
from kimbim import nicfile as K
from kimbim import settings as S
from kimbim.agent import render
from kimbim.agent.catalogue import call_tool
from kimbim.agent.session import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import make_house  # noqa: E402


@pytest.fixture
def s(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_data_dir", tmp_path / "data")
    monkeypatch.setattr(K, "display_user", "")
    ifc = tmp_path / "house.ifc"
    make_house.build(str(ifc))
    assert json.loads(D.import_ifc(str(ifc), str(tmp_path / "house.nic")))["ok"]
    D.close_document()
    session = Session.open(str(tmp_path / "house.nic"))
    assert json.loads(S.set_project_settings(json.dumps({"agent_changes": "direct"})))["ok"]
    yield session
    session.close()


def run(s, tool_name, **args):
    return call_tool(s, tool_name, args, client="test")


def test_site_tools_and_project_info(s):
    r = run(s, "site.locate", latitude=-34.9145, longitude=-56.164, elevation=22, north=18, crs="EPSG:5382",
            address="Br. España 2200", town="Montevideo", country="Uruguay")
    assert r["ok"], r
    assert r["result"]["crs"] == "EPSG:5382" and 576_000 < r["result"]["eastings"] < 577_000
    got = run(s, "site.get")["result"]
    assert got["latitude"] == pytest.approx(-34.9145) and got["georeference"]["true_north"] == pytest.approx(18)
    r = run(s, "project.set_info", number="2026-001", name="Casa Parque Rodó", client_name="Familia Pérez")
    assert r["ok"], r
    info = run(s, "project.get_info")["result"]
    assert info["number"] == "2026-001" and info["client"] == "Familia Pérez"


def test_package_without_pdf(s, tmp_path):
    run(s, "project.set_info", number="M4-01", name="Casa")
    out = tmp_path / "delivery"
    r = run(s, "deliver.package", out=str(out), pdf=False, note="Anteproyecto")
    assert r["ok"], r
    kinds = {f["kind"] for f in json.loads((out / "transmittal.json").read_text(encoding="utf-8"))["files"]}
    assert {"sheet dxf", "ifc", "schedule"} <= kinds
    md = (out / "transmittal.md").read_text(encoding="utf-8")
    assert "Anteproyecto" in md and "| ifc/M4-01 Casa.ifc | ifc |" in md
    with zipfile.ZipFile(r["result"]["zip"]) as z:
        assert "transmittal.json" in z.namelist() and "ifc/M4-01 Casa.ifc" in z.namelist()


def test_package_refuses_unknown_sheets(s, tmp_path):
    r = run(s, "deliver.package", out=str(tmp_path / "d"), sheets=["Z99"])
    assert not r["ok"] and r["error"]["code"] == "not_found"


@pytest.mark.skipif(render.app_binary() is None, reason="needs the NicBim app binary for PDF sheets")
def test_package_with_the_drawing_set(s, tmp_path):
    out = tmp_path / "delivery"
    r = run(s, "deliver.package", out=str(out), dxf=False, schedules=False, checks=False, zip=False)
    assert r["ok"], r
    assert not r["result"]["problems"], r["result"]["problems"]
    sets = list(out.glob("* - drawing set.pdf"))
    assert sets and sets[0].stat().st_size > 1000
