# SPDX-License-Identifier: GPL-3.0-or-later
"""View templates (D186): a named snapshot of the view settings a saved view shares.

The template stores the layer state, drawing scale and purpose of the project's current view; applying
it writes those project settings back, so every open view follows immediately.
"""
from __future__ import annotations

import json

from . import app_bridge as B
from . import settings

KEY = "view_templates"
FIELDS = ("hidden_layers", "locked_layers", "drawing_scale", "purpose", "sheet_paper")


def _stored() -> dict:
    data = settings.current().get(KEY, {})
    return dict(data) if isinstance(data, dict) else {}


def view_templates() -> str:
    """The project's view templates, by name, with the settings each records."""
    return B._dump({"ok": True, "templates": [{"name": name, **{k: data.get(k) for k in FIELDS}}
                                              for name, data in sorted(_stored().items())
                                              if isinstance(data, dict)]})


def save_view_template(name: str) -> str:
    """Save the current layer state, drawing scale and purpose under `name`."""
    name = str(name or "").strip()
    if not name:
        return B._dump({"ok": False, "error": "type a template name"})
    current = settings.current()
    data = _stored()
    data[name] = {k: current.get(k) for k in FIELDS}
    r = json.loads(settings.set_project_settings(json.dumps({KEY: data})))
    return B._dump({**r, "template": {"name": name, **data[name]}})


def apply_view_template(name: str) -> str:
    """Apply a template's settings to the project (every view follows)."""
    data = _stored().get(str(name or "").strip())
    if not isinstance(data, dict):
        return B._dump({"ok": False, "error": "unknown view template"})
    return settings.set_project_settings(json.dumps({k: data[k] for k in FIELDS if k in data}))


def delete_view_template(name: str) -> str:
    """Remove a template (the project's settings stay as they are)."""
    data = _stored()
    if data.pop(str(name or "").strip(), None) is None:
        return B._dump({"ok": False, "error": "unknown view template"})
    return settings.set_project_settings(json.dumps({KEY: data}))
