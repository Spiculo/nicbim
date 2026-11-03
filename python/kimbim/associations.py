# SPDX-License-Identifier: GPL-3.0-or-later
"""Open `.kim` and `.ifc` files with KimBim: per-user file associations (D139).

Windows: `HKEY_CURRENT_USER\\Software\\Classes`, no administrator needed. `.kim` maps to
`KimBim.Project` and `.ifc` to `KimBim.Ifc`; each class holds the `open` command and the app icon.
Linux: a `kimbim.desktop` file in `$XDG_DATA_HOME/applications` (or `~/.local/share/applications`) and
`xdg-mime default` for the two MIME types. `associations.plan()` returns the actions without changing
anything; `apply()` performs them and `remove()` undoes them. No installer and no code signing yet.

Same protocol as the rest of the CLI: this module raises `OSError`/`ValueError`, the caller reports.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys

APP_NAME = "KimBim"
PROJECT_CLASS = "KimBim.Project"
IFC_CLASS = "KimBim.Ifc"
PROJECT_MIME = "application/x-kimbim-project"
IFC_MIME = "application/x-ifc"
EXTENSIONS = {".kim": PROJECT_CLASS, ".ifc": IFC_CLASS}
ICON = "kimbim"


def default_exe() -> str:
    """The app executable: KIMBIM_APP, then `kimbim-app` on PATH, then a sibling of this checkout."""
    env = (os.environ.get("KIMBIM_APP") or "").strip()
    if env:
        return env
    for name in ("kimbim-app", "kimbim-app.exe"):
        found = shutil.which(name)
        if found:
            return found
    return ""


def open_command(exe: str, arg: str = "%1") -> str:
    return f'"{exe}" "{arg}"'


def windows_actions(exe: str) -> list[dict]:
    """The registry writes that associate .kim and .ifc with `exe` (HKCU, no admin)."""
    actions = []
    for extension, class_name in EXTENSIONS.items():
        actions.append({"root": "HKCU", "key": rf"Software\Classes\{extension}", "name": "", "value": class_name})
        base = rf"Software\Classes\{class_name}"
        actions += [
            {"root": "HKCU", "key": base, "name": "", "value": f"{APP_NAME} {extension.lstrip('.').upper()} file"},
            {"root": "HKCU", "key": base + r"\DefaultIcon", "name": "", "value": f'"{exe}",0'},
            {"root": "HKCU", "key": base + r"\shell\open\command", "name": "", "value": open_command(exe)},
        ]
    return actions


def _windows_apply(actions: list[dict], remove: bool = False, registry=None) -> list[str]:
    if registry is None:
        import winreg as registry

    written = []
    for action in server_order(actions, remove):
        root = registry.HKEY_CURRENT_USER if action["root"] == "HKCU" else registry.HKEY_LOCAL_MACHINE
        if remove:
            try:
                registry.DeleteKey(root, action["key"])
                written.append(action["key"])
            except FileNotFoundError:
                pass
            except OSError:
                pass  # a key with subkeys: its subkeys are removed in their own actions
            continue
        with registry.CreateKeyEx(root, action["key"], 0, registry.KEY_SET_VALUE) as key:
            registry.SetValueEx(key, action["name"], 0, registry.REG_SZ, action["value"])
        written.append(action["key"])
    return written


def server_order(actions: list[dict], remove: bool) -> list[dict]:
    """On removal the class subkeys go before their parents (the registry deletes leaves only)."""
    if not remove:
        return actions
    return sorted(actions, key=lambda a: a["key"].count("\\"), reverse=True)


def linux_desktop(exe: str) -> str:
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Name=KimBim",
        "Comment=Open BIM authoring and versioning",
        f'Exec="{exe}" %f',
        f"Icon={ICON}",
        f"MimeType={PROJECT_MIME};{IFC_MIME};",
        "Terminal=false",
        "Categories=Graphics;Architecture;",
        "",
    ])


def linux_paths(home: str | None = None) -> tuple[pathlib.Path, pathlib.Path]:
    """(desktop file, MIME package file) under the user's data folder."""
    data = pathlib.Path(os.environ.get("XDG_DATA_HOME") or (pathlib.Path(home or pathlib.Path.home()) / ".local/share"))
    return data / "applications" / "kimbim.desktop", data / "mime" / "packages" / "kimbim.xml"


def linux_mime_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="{PROJECT_MIME}">
    <comment>KimBim project</comment>
    <glob pattern="*.kim"/>
  </mime-type>
  <mime-type type="{IFC_MIME}">
    <comment>Industry Foundation Classes model</comment>
    <glob pattern="*.ifc"/>
  </mime-type>
</mime-info>
"""


def linux_actions(exe: str, home: str | None = None) -> list[dict]:
    desktop, mime = linux_paths(home)
    return [{"path": str(desktop), "content": linux_desktop(exe)},
            {"path": str(mime), "content": linux_mime_xml()}]


def _linux_apply(actions: list[dict]) -> list[str]:
    written = []
    for action in actions:
        path = pathlib.Path(action["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(action["content"], encoding="utf-8")
        written.append(str(path))
    for mime in (PROJECT_MIME, IFC_MIME):
        try:
            subprocess.run(["xdg-mime", "default", "kimbim.desktop", mime], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass  # xdg-utils not installed: the desktop file still declares the MIME types
    return written


def plan(exe: str, home: str | None = None) -> dict:
    """The platform's actions without performing them, for `--print` and tests."""
    if not exe:
        raise ValueError("no KimBim executable: pass --exe (or set KIMBIM_APP)")
    if sys.platform.startswith("win"):
        return {"platform": "windows", "actions": windows_actions(exe), "exe": exe}
    return {"platform": "linux", "actions": linux_actions(exe, home), "exe": exe}


def apply(exe: str, home: str | None = None) -> list[str]:
    """Associate .kim and .ifc with `exe` for this user; returns what was written."""
    if not exe:
        raise ValueError("no KimBim executable: pass --exe (or set KIMBIM_APP)")
    if sys.platform.startswith("win"):
        return _windows_apply(windows_actions(exe))
    return _linux_apply(linux_actions(exe, home))


def remove(home: str | None = None) -> list[str]:
    """Remove the associations this user added (other file associations are left alone)."""
    if sys.platform.startswith("win"):
        return _windows_apply(windows_actions(""), remove=True)
    removed = []
    for path in linux_paths(home):
        try:
            path.unlink()
            removed.append(str(path))
        except FileNotFoundError:
            pass
        except OSError:
            pass
    return removed


def describe(result: dict) -> str:
    """A human-readable description of `plan()` (used by `kimbim setup associations --print`)."""
    lines = []
    for action in result["actions"]:
        if result["platform"] == "windows":
            value = action["value"]
            lines.append(f'HKCU\\{action["key"]}  [{action["name"] or "(default)"}] = {value}')
        else:
            lines.append(f"{action['path']}:")
            lines.append(action["content"].rstrip())
    return "\n".join(lines)
