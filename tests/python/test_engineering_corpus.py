# SPDX-License-Identifier: GPL-3.0-or-later
"""D242/D245/D247 on buildingSMART sample files: tessellated members, walls and pipes without ports."""
import json
from pathlib import Path

import pytest

from kimbim import app_bridge as B
from kimbim import drainage as D
from kimbim import mep as M
from kimbim import structanalysis as SA

ROOT = Path(__file__).resolve().parents[2] / "spikes" / "corpus" / "files" / "bsi"
VERSIONS = ("IFC 2.3.0.1 (IFC 2x3 TC1)", "IFC 4.0.2.1 (IFC 4 ADD2 TC1)", "IFC 4.3.2.0 (IFC 4.3 ADD2)")


def sample(version, name):
    path = ROOT / version / "Simple-Scene" / f"{name}.ifc"
    if not path.exists():
        pytest.skip("the buildingSMART corpus is not downloaded (spikes/corpus/fetch.py)")
    assert json.loads(B.open_model(str(path)))["ok"]


@pytest.mark.parametrize("version", VERSIONS)
def test_tessellated_timber_girders_are_analysed(version):
    sample(version, "Building-Structural")
    r = SA.run_analysis()
    assert r["ok"], r.get("error")
    assert len(r["members"]) >= 4 and all(m["category"] == "timber" for m in r["members"])
    assert any("section estimated" in w for w in r["warnings"])
    assert any("mechanism" in w for w in r["warnings"])  # the dangling stubs are left out, not reported as failing
    assert r["counts"]["fail"] == 0
    assert r["total_reaction_kN"] == pytest.approx(r["total_uls_kN"], rel=1e-3)


@pytest.mark.parametrize("version", VERSIONS[:2])
def test_a_sewer_without_ports_is_connected_from_its_geometry(version):
    sample(version, "Infra-Plumbing")
    system = json.loads(M.mep_systems())["systems"][0]
    assert system["kind"] == "sanitary"  # from IFC4's predefined type, or from the name in IFC2X3
    r = json.loads(M.connect_network(system["guid"]))
    assert r["ok"] and r["inferred"] > 40 and r["connected"] > 20
    net = json.loads(M.mep_network(system["guid"]))
    assert net["sources"] and net["loops"] == 0
    d = json.loads(D.size_drainage_system(system["guid"]))
    assert d["ok"] and any("estimated" in w for w in d["warnings"])
    assert not any(s["status"] == "falls the wrong way" for s in d["segments"])
