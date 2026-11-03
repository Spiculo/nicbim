# SPDX-License-Identifier: GPL-3.0-or-later
"""Revisions and issue management for sheets (D171).

A revision is a project record (`revisions` setting): {code, date, description}. A sheet's revision
is stored in its title block's `revision` field, so it prints in the title block and travels with the
sheet. Revisions are project data (versioned with the settings), not a separate file.
"""
from __future__ import annotations

import datetime
import json

from . import app_bridge as B
from . import settings
from . import sheets

KEY = "revisions"


def _rows() -> list:
    rows = settings.current().get(KEY, [])
    return [dict(r) for r in rows if isinstance(r, dict) and str(r.get("code") or "").strip()]


def revisions() -> str:
    """The project's revisions, sorted by code."""
    return B._dump({"ok": True, "revisions": sorted(_rows(), key=lambda r: str(r["code"]))})


def save_revision(code: str, date: str = "", description: str = "") -> str:
    """Add or change a revision; an empty date becomes today. One undo step."""
    code = str(code or "").strip()
    if not code:
        return B._dump({"ok": False, "error": "type a revision code"})
    rows = [r for r in _rows() if str(r["code"]) != code]
    entry = {"code": code, "date": str(date or "").strip() or datetime.date.today().isoformat(),
             "description": str(description or "").strip()}
    rows.append(entry)
    rows.sort(key=lambda r: r["code"])
    r = json.loads(settings.set_project_settings(json.dumps({KEY: rows})))
    return B._dump({**r, "revision": entry})


def delete_revision(code: str) -> str:
    """Remove a revision from the project (sheets keep their title block text)."""
    code = str(code or "").strip()
    rows = [r for r in _rows() if str(r["code"]) != code]
    if len(rows) == len(_rows()):
        return B._dump({"ok": False, "error": "unknown revision"})
    return settings.set_project_settings(json.dumps({KEY: rows}))


def set_sheet_revision(number: str, code: str) -> str:
    """Set (or clear, with an empty code) a sheet's revision; the code must be in the project."""
    code = str(code or "").strip()
    if code and not any(str(r["code"]) == code for r in _rows()):
        return B._dump({"ok": False, "error": f"unknown revision {code}"})
    return sheets.set_title_block(number, json.dumps({"fields": {"revision": code}}))


def sheet_revision(number: str) -> str:
    """The revision a sheet's title block shows."""
    sheet = sheets._sheet(number) if B._model is not None else None
    if sheet is None:
        return B._dump({"ok": False, "error": "unknown sheet"})
    return B._dump({"ok": True, "revision": sheets._title_block_fields(sheet).get("revision") or ""})
