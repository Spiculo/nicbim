# SPDX-License-Identifier: GPL-3.0-or-later
"""D202: permanent guide lines (doc 14 §5) — construction references the drawing tools snap to."""
import json

from kimbim import app_bridge as b


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def test_guide_lines_snap_and_are_removed():
    assert call("new_project", "Guides")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    r = call("add_guide", 0, 0, 10, 0)
    assert r["ok"], r
    guide = r["guide"]
    assert guide["x2"] == 10.0
    grid = call("snap_data", level)["grid"]
    assert any(line["guid"] == guide["id"] and line["x1"] == 0 and line["x2"] == 10 for line in grid)

    assert not call("add_guide", 2, 3, 2, 3)["ok"]  # no length
    assert call("add_guide", 0, 5, 10, 5)["ok"]
    assert len(call("guides")["guides"]) == 2
    assert call("remove_guide", guide["id"])["ok"]
    assert not call("remove_guide", "nope")["ok"]
    assert call("clear_guides")["ok"]
    assert call("guides")["guides"] == []
    assert call("snap_data", level)["grid"] == []
