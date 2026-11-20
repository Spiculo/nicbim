# SPDX-License-Identifier: GPL-3.0-or-later
"""Share a sheet as a web page (D215, doc 14 §17): a self-contained HTML file with the sheet's SVG.

The page needs no server: it holds the sheet inline with small pan/zoom handlers, so it can be sent
to a client or uploaded to any static host. There is no live view or comment service.
"""
from __future__ import annotations

import json

from . import app_bridge as B
from . import authoring as A

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  html, body {{ margin: 0; height: 100%; background: #e9ebee; font: 14px system-ui, sans-serif; }}
  header {{ padding: 10px 16px; background: #fff; border-bottom: 1px solid #d3d6da; color: #333; }}
  header b {{ color: #111; }}
  #stage {{ position: absolute; inset: 52px 0 0 0; overflow: hidden; cursor: grab; }}
  #stage.grabbing {{ cursor: grabbing; }}
  #sheet {{ transform-origin: 0 0; width: max-content; background: #fff; box-shadow: 0 2px 18px #0003; }}
  #sheet svg {{ display: block; }}
</style>
</head>
<body>
<header><b>{title}</b> &middot; NicBim sheet {number}</header>
<div id="stage"><div id="sheet">{svg}</div></div>
<script>
(function () {{
  const stage = document.getElementById('stage');
  const sheet = document.getElementById('sheet');
  let scale = 1, x = 20, y = 20, drag = null;
  const apply = () => {{ sheet.style.transform = `translate(${{x}}px, ${{y}}px) scale(${{scale}})`; }};
  stage.addEventListener('mousedown', (e) => {{ drag = {{x: e.clientX - x, y: e.clientY - y}}; stage.classList.add('grabbing'); }});
  window.addEventListener('mousemove', (e) => {{ if (!drag) return; x = e.clientX - drag.x; y = e.clientY - drag.y; apply(); }});
  window.addEventListener('mouseup', () => {{ drag = null; stage.classList.remove('grabbing'); }});
  stage.addEventListener('wheel', (e) => {{
    e.preventDefault();
    const factor = Math.exp(-e.deltaY * 0.0015);
    const rect = stage.getBoundingClientRect();
    const px = e.clientX - rect.left, py = e.clientY - rect.top;
    x = px - (px - x) * factor; y = py - (py - y) * factor; scale *= factor; apply();
  }}, {{passive: false}});
  apply();
}})();
</script>
</body>
</html>
"""


def _sheet_title(number: str) -> tuple[str, str]:
    from . import sheets

    for sheet in json.loads(sheets.sheets()).get("sheets", []):
        if sheet.get("number") == number:
            return sheet.get("title") or number, sheet.get("number") or number
    return number, number


def share_html(number: str) -> str:
    """{ok, html, title} for a sheet as a self-contained web page."""
    from . import sheets

    r = json.loads(sheets.sheet_svg(number))
    if not r.get("ok"):
        return A._fail(r.get("error") or "could not generate the sheet")
    title, number = _sheet_title(number)
    return B._dump({"ok": True, "title": title, "number": number,
                    "html": PAGE.format(title=title.replace("&", "&amp;").replace("<", "&lt;"), number=number,
                                        svg=r["svg"])})


def export_web(number: str, path: str) -> str:
    """Write the sheet's web page to `path` (UTF-8 HTML)."""
    r = json.loads(share_html(number))
    if not r.get("ok"):
        return A._fail(r.get("error") or "could not generate the sheet")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(r["html"])
    except OSError as ex:
        return A._fail(f"could not write {path}: {ex}")
    return B._dump({"ok": True, "path": str(path), "title": r["title"]})
