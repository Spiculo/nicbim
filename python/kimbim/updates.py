# SPDX-License-Identifier: GPL-3.0-or-later
"""Check GitHub for a newer NicBim release (Preferences > Updates).

The check is optional and off by default. It reads the public releases API; nothing about the user or
the project is sent.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

REPOSITORY = "Spiculo/nicbim"
API = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=20"


def _key(text: str) -> tuple:
    text = (text or "").strip().lstrip("vV")
    main, _, pre = text.partition("-")
    parts = []
    for piece in main.split("."):
        match = re.match(r"\d+", piece)
        parts.append(int(match.group(0)) if match else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts), 0 if pre else 1, pre


def check_for_updates(current: str = "", channel: str = "stable") -> str:
    channel = (channel or "off").strip().lower()
    if channel == "off":
        return json.dumps({"ok": True, "channel": "off", "update": False, "current": current})
    request = urllib.request.Request(API, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "NicBim-update-check",
    })
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            releases = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError) as ex:
        return json.dumps({"ok": False, "error": f"cannot check for updates: {ex}", "current": current})
    candidates = []
    for release in releases if isinstance(releases, list) else []:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        if channel != "beta" and release.get("prerelease"):
            continue
        tag = str(release.get("tag_name") or "")
        if tag:
            candidates.append((_key(tag), release))
    if not candidates:
        return json.dumps({"ok": True, "channel": channel, "update": False, "current": current,
                           "latest": "", "url": ""})
    candidates.sort(key=lambda item: item[0])
    (_, release) = candidates[-1]
    latest = str(release.get("tag_name") or "").lstrip("vV")
    update = bool(current) and _key(latest) > _key(current)
    return json.dumps({"ok": True, "channel": channel, "current": current, "latest": latest,
                       "update": update, "name": release.get("name") or latest,
                       "url": release.get("html_url") or "",
                       "published": release.get("published_at") or "",
                       "prerelease": bool(release.get("prerelease"))})
