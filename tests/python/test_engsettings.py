# SPDX-License-Identifier: GPL-3.0-or-later
"""D242-D247: engineering settings are stored as overrides and merged over code defaults."""
import json

from kimbim import app_bridge as B
from kimbim import engsettings as E


def call(fn, *args):
    target = getattr(B, fn) if isinstance(fn, str) else fn
    return json.loads(target(*args))


def test_defaults_overrides_and_undo():
    assert call("new_project", "Eng")["ok"]
    assert E.get("hvac_settings")["friction_pa_m"] == 1.0
    r = call(E.set_engineering_settings, "hvac_settings", json.dumps({"friction_pa_m": 2}))
    assert r["ok"] and r["settings"]["friction_pa_m"] == 2
    assert E.get("hvac_settings")["friction_pa_m"] == 2
    assert E.get("hvac_settings")["velocity_main"] == 6.0  # untouched defaults still merge
    assert call("undo")["ok"]
    assert E.get("hvac_settings")["friction_pa_m"] == 1.0


def test_bad_values_are_refused():
    assert call("new_project", "Eng")["ok"]
    for key, changes in (("hvac_settings", {"nope": 1}), ("hvac_settings", {"friction_pa_m": -1}),
                         ("hvac_settings", {"method": "magic"}), ("structure_settings", {"uls": {"G": "x"}}),
                         ("structure_settings", {"materials": {"steel": {"E": "soft"}}}), ("nope", {})):
        assert not call(E.set_engineering_settings, key, json.dumps(changes))["ok"], (key, changes)


def test_open_tables_take_new_entries():
    assert call("new_project", "Eng")["ok"]
    r = call(E.set_engineering_settings, "structure_settings",
             json.dumps({"materials": {"S460": {"E": 210e6, "G": 81e6, "density": 78.5, "f": 460e3, "gamma": 1.0}},
                         "use_loads": {"F": 2.5}}))
    assert r["ok"], r
    got = E.get("structure_settings")
    assert "S460" in got["materials"] and "steel" in got["materials"] and got["use_loads"]["F"] == 2.5
    assert call(E.reset_engineering_settings, "structure_settings")["ok"]
    assert "S460" not in E.get("structure_settings")["materials"]
