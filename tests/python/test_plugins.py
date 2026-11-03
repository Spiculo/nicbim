# SPDX-License-Identifier: GPL-3.0-or-later
"""D212: user Python plugins in the app's plugins folder."""
import json

from kimbim import app_bridge as b
from kimbim import plugins


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def test_plugins_load_and_report_errors(tmp_path):
    call("set_app_paths", str(tmp_path / "data"))
    try:
        folder = plugins.folder()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "hello.py").write_text(
            "def register(api):\n    api._plugin_marker = 'loaded'\n", encoding="utf-8")
        (folder / "broken.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")
        r = json.loads(plugins.load_plugins())
        assert r["ok"], r
        assert [p["name"] for p in r["plugins"]] == ["hello.py"]
        assert r["errors"][0]["name"] == "broken.py" and "boom" in r["errors"][0]["error"]
        assert getattr(b, "_plugin_marker", None) == "loaded"
        state = json.loads(plugins.plugins_state())
        assert [p["name"] for p in state["plugins"]] == ["broken.py", "hello.py"]
        assert [p["loaded"] for p in state["plugins"]] == [False, True]
        assert state["folder"] == str(folder)
    finally:
        if hasattr(b, "_plugin_marker"):
            del b._plugin_marker
        call("set_app_paths", "")
