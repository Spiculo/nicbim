# SPDX-License-Identifier: GPL-3.0-or-later
"""Check findings (clashes...) sent to BCF issues from the Checks panel."""
import json

from kimbim import app_bridge as b


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def test_findings_become_issues_once():
    assert call("new_project", "Clashes")["ok"]
    findings = [{"message": "Wall A clashes with Column 3", "guids": ["g1", "g2"]},
                {"message": "Beam 2 clashes with Duct", "guids": ["g3", "g4"], "group": "Structure x MEP"},
                {"message": "", "guids": ["g5"]}]
    r = call("issues_from_findings", json.dumps(findings), "Clash")
    assert r["ok"] and r["created"] == 2
    issues = {i["title"]: i for i in call("list_issues")["issues"]}
    assert issues["Wall A clashes with Column 3"]["viewpoint"]["components"] == ["g1", "g2"]
    assert issues["Beam 2 clashes with Duct"]["type"] == "Clash"
    assert issues["Beam 2 clashes with Duct"]["description"] == "Structure x MEP"
    again = call("issues_from_findings", json.dumps(findings[:1]))
    assert again["ok"] and again["created"] == 0  # already open
    assert not call("issues_from_findings", "not json")["ok"]
