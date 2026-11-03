# SPDX-License-Identifier: GPL-3.0-or-later
"""Plugins / add-ons (D212, doc 14 §20): user Python files in the app's `plugins` folder.

A plugin is a `.py` file in `<app data>/plugins`; it may define `register(api)`, where `api` is the
`kimbim.app_bridge` module (the same functions the app and the agent use). Files run when the app
starts and when Help > Plugins > Reload is pressed; an error in one is reported without stopping the
others.
"""
from __future__ import annotations

import pathlib
import runpy

from . import app_bridge as B

_loaded: dict[str, dict] = {}


def folder() -> pathlib.Path:
    from . import documents

    return documents.data_dir() / "plugins"


def plugins_folder() -> str:
    """The plugins folder (created if needed)."""
    path = folder()
    path.mkdir(parents=True, exist_ok=True)
    return B._dump({"ok": True, "folder": str(path)})


def plugins_state() -> str:
    """The plugin files and whether the last load succeeded."""
    path = folder()
    files = sorted(path.glob("*.py")) if path.is_dir() else []
    out = []
    for f in files:
        state = _loaded.get(f.name, {})
        out.append({"name": f.name, "path": str(f), "loaded": state.get("ok") is True,
                    "error": state.get("error", "")})
    return B._dump({"ok": True, "folder": str(path), "plugins": out})


def load_plugins() -> str:
    """Run every plugin file, in name order; failures are reported but do not stop the rest."""
    path = folder()
    path.mkdir(parents=True, exist_ok=True)
    _loaded.clear()
    plugins, errors = [], []
    for f in sorted(path.glob("*.py")):
        try:
            namespace = runpy.run_path(str(f), run_name=f"kimbim_plugin_{f.stem}")
            register = namespace.get("register")
            if callable(register):
                register(B)
            _loaded[f.name] = {"ok": True, "error": ""}
            plugins.append({"name": f.name, "path": str(f), "ok": True, "error": ""})
        except Exception as ex:  # a plugin must not take the others (or the app) down
            message = f"{type(ex).__name__}: {ex}"
            _loaded[f.name] = {"ok": False, "error": message}
            errors.append({"name": f.name, "path": str(f), "ok": False, "error": message})
    return B._dump({"ok": True, "folder": str(path), "plugins": plugins, "errors": errors})
