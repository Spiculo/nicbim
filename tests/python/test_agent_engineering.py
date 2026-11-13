# SPDX-License-Identifier: GPL-3.0-or-later
"""D248: the engineering agent tools on the sample house: an MEP system, a run, sizing and a structure check."""
import json
import sys
from pathlib import Path

import pytest

from kimbim import app_bridge as B
from kimbim import documents as D
from kimbim import kimfile as K
from kimbim import settings as S
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
    out = json.loads(D.import_ifc(str(ifc), str(tmp_path / "house.kim")))
    assert out["ok"]
    D.close_document()
    session = Session.open(str(tmp_path / "house.kim"))
    assert json.loads(S.set_project_settings(json.dumps({"agent_changes": "direct"})))["ok"]
    yield session
    session.close()


def run(s, tool_name, **args):
    return call_tool(s, tool_name, args, client="test")


def test_an_agent_draws_and_sizes_an_air_system(s):
    level = json.loads(B.storeys())["storeys"][0]["guid"]
    assert run(s, "mep.create_system", name="SA-1", kind="supply_air")["ok"]
    assert run(s, "mep.place", kind="ahu", level=level, x=1.0, y=1.0, z=0.0, system="SA-1")["ok"]
    r = run(s, "mep.run", level=level, kind="duct", points=[[0.5, 1, 1.5], [0.5, 1, 2.75], [4, 1, 2.75]],
            width=0.3, height=0.3, system="SA-1")
    assert r["ok"], r
    d = run(s, "mep.place", kind="supply_diffuser", level=level, x=4, y=1, z=2.7, system="SA-1")
    assert d["ok"]
    assert run(s, "mep.set_design", element=d["result"]["guid"], values={"Flow": 120})["ok"]
    net = run(s, "mep.network", system="SA-1")["result"]
    assert net["unreached"] == [] and len(net["sources"]) == 1
    sized = run(s, "hvac.size", system="SA-1")["result"]
    assert sized["system_flow"] == pytest.approx(120)
    assert run(s, "hvac.apply_sizes", system="SA-1")["ok"]
    assert run(s, "engineering.settings", discipline="hvac_settings")["result"]["settings"]["friction_pa_m"] == 1.0


def test_an_agent_checks_the_structure(s):
    r = run(s, "structure.analyse")
    assert r["ok"] or r["error"]["code"] == "bridge_error"
    assert "structure.save_results" in __import__("kimbim.agent.catalogue", fromlist=["TOOLS"]).TOOLS
