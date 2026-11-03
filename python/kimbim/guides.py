# SPDX-License-Identifier: GPL-3.0-or-later
"""Permanent guide lines (D202, doc 14 §5): straight construction references the drawing tools snap
to, kept in the project settings so they survive saving and versions. Temporary guides (D89) are the
inference lines a snap point throws while drawing; these stay until removed.
"""
from __future__ import annotations

import json
import math
import uuid

from . import app_bridge as B

KEY = "guide_lines"


def _stored() -> list[dict]:
    from . import settings as S

    data = S.current().get(KEY, [])
    return [g for g in data if isinstance(g, dict)] if isinstance(data, list) else []


def guides() -> str:
    """The project's guide lines, in world metres."""
    return B._dump({"ok": True, "guides": _stored()})


def add_guide(x1, y1, x2, y2) -> str:
    """A permanent guide line from (x1, y1) to (x2, y2) (world metres)."""
    from . import authoring as A
    from . import settings as S

    try:
        x1, y1, x2, y2 = (float(v) for v in (x1, y1, x2, y2))
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    if math.dist((x1, y1), (x2, y2)) < 1e-6:
        return A._fail("the guide line needs two different points")
    entry = {"id": uuid.uuid4().hex[:12], "x1": round(x1, 6), "y1": round(y1, 6),
             "x2": round(x2, 6), "y2": round(y2, 6)}
    r = json.loads(S.set_project_settings(json.dumps({KEY: _stored() + [entry]})))
    return B._dump({**r, "guide": entry})


def remove_guide(id: str) -> str:
    """Forget one guide line."""
    from . import app_bridge as B2
    from . import settings as S

    data = _stored()
    kept = [g for g in data if g.get("id") != id]
    if len(kept) == len(data):
        return B2._dump({"ok": False, "error": f"unknown guide line {id}"})
    return S.set_project_settings(json.dumps({KEY: kept}))


def clear_guides() -> str:
    """Remove every guide line."""
    from . import settings as S

    return S.set_project_settings(json.dumps({KEY: []}))


def lines() -> list[dict]:
    """The guide lines as snap lines (the snapper's "grid" list)."""
    return [{"guid": g["id"], "tag": "", "x1": float(g["x1"]), "y1": float(g["y1"]),
             "x2": float(g["x2"]), "y2": float(g["y2"])} for g in _stored()]
