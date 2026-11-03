# SPDX-License-Identifier: GPL-3.0-or-later
"""D215: a sheet shared as a self-contained web page."""
import json

from kimbim import app_bridge as b


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def test_share_a_sheet_as_a_web_page(tmp_path):
    assert call("new_project", "Web")["ok"]
    r = call("add_sheet", "A3", "Ground floor")
    assert r["ok"], r
    number = r["number"]
    page = call("share_html", number)
    assert page["ok"], page
    assert "<svg" in page["html"] and "Ground floor" in page["html"]
    out = tmp_path / "share.html"
    saved = call("export_web", number, str(out))
    assert saved["ok"], saved
    text = out.read_text(encoding="utf-8")
    assert "<svg" in text and "Ground floor" in text and "KimBim sheet" in text
    assert not call("share_html", "nope")["ok"]
