# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable install/uninstall for the packaged NicBim build (D144).

`dist/NicBim` is a relocatable folder (app, embedded Python and runtime). This module copies it to
the user's per-user application folder (no administrator), writes a marker so a later uninstall only
removes a folder this installer owns, and wires the `.nic`/`.ifc` associations from D139. Uninstall
calls `associations.remove()` and deletes the installed tree.

No code signing and no OS-level package: this is a portable wrapper, and `--dry-run` reports the
planned actions without touching anything. macOS is not a target.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
from datetime import datetime, timezone

MARKER = ".kimbim-install.json"
APP_NAMES = ("kimbim-app.exe", "kimbim-app")


def default_source() -> pathlib.Path:
    """The packaged build: `dist/NicBim` in a checkout, or the folder this package lives in when
    running inside an installed/packaged tree."""
    root = pathlib.Path(__file__).resolve().parents[2]
    packaged = root / "dist" / "NicBim"
    if packaged.is_dir():
        return packaged
    return root


def default_dest() -> pathlib.Path:
    if sys.platform.startswith("win"):
        local = os.environ.get("LOCALAPPDATA") or str(pathlib.Path.home() / "AppData" / "Local")
        return pathlib.Path(local) / "Programs" / "NicBim"
    data = pathlib.Path(os.environ.get("XDG_DATA_HOME") or (pathlib.Path.home() / ".local" / "share"))
    return data / "NicBim"


def app_executable(folder: pathlib.Path) -> pathlib.Path:
    for name in APP_NAMES:
        candidate = folder / name
        if candidate.is_file():
            return candidate
    raise ValueError(f"not a NicBim build: no {' or '.join(APP_NAMES)} in {folder}")


def _marker(dest: pathlib.Path) -> dict | None:
    path = dest / MARKER
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def is_installed(dest: pathlib.Path) -> bool:
    return _marker(pathlib.Path(dest)) is not None


def status(dest: pathlib.Path | None = None) -> dict:
    folder = pathlib.Path(dest or default_dest())
    marker = _marker(folder)
    files = sum(1 for _ in folder.rglob("*") if _.is_file()) if folder.is_dir() else 0
    return {"installed": marker is not None, "path": str(folder), "files": files,
            **({"marker": marker} if marker else {})}


def install(source: pathlib.Path | None = None, dest: pathlib.Path | None = None, *,
            force: bool = False, dry_run: bool = False, associations: bool = True,
            associate=None) -> dict:
    """Copy the packaged build to `dest`, write the marker and associate `.nic`/`.ifc`.

    `force` replaces a destination this installer owns (or, with no marker, refuses: never delete an
    arbitrary folder). `associate(exe)` defaults to `associations.apply`. `dry_run` changes nothing.
    """
    src = pathlib.Path(source or default_source()).resolve()
    dst = pathlib.Path(dest or default_dest()).resolve()
    if not src.is_dir():
        raise ValueError(f"no build to install: {src}")
    exe = app_executable(src)
    marker = _marker(dst)
    exists = dst.exists()
    if exists and marker is None:
        raise ValueError(f"{dst} already exists and was not installed by NicBim; choose another --dest")
    if exists and marker is not None and not force:
        raise ValueError(f"{dst} is already installed; use --force to replace it")
    actions = [f"copy {src} -> {dst}", f"write {dst / MARKER}",
               f"associate .nic/.ifc with {exe}" if associations else "skip file associations"]
    if dry_run:
        return {"ok": True, "dry_run": True, "actions": actions, "path": str(dst), "exe": str(exe)}
    if exists:
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)
    installed_exe = app_executable(dst)
    data = {"product": "NicBim", "installed": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": str(src), "app": str(installed_exe), "associations": bool(associations)}
    (dst / MARKER).write_text(json.dumps(data, indent=2), encoding="utf-8")
    if associations:
        if associate is None:
            from . import associations as A

            associate = A.apply
        associate(str(installed_exe))
    return {"ok": True, "dry_run": False, "path": str(dst), "exe": str(installed_exe),
            "actions": actions, "marker": data}


def uninstall(dest: pathlib.Path | None = None, *, dry_run: bool = False, unassociate=None) -> dict:
    """Remove an installation this installer made and its file associations.
    A folder without the marker is refused."""
    folder = pathlib.Path(dest or default_dest()).resolve()
    marker = _marker(folder)
    if marker is None:
        raise ValueError(f"{folder} is not a NicBim installation (no {MARKER})")
    actions = [f"remove file associations", f"delete {folder}"]
    if dry_run:
        return {"ok": True, "dry_run": True, "actions": actions, "path": str(folder), "marker": marker}
    if marker.get("associations"):
        if unassociate is None:
            from . import associations as A

            unassociate = A.remove
        unassociate()
    shutil.rmtree(folder)
    return {"ok": True, "dry_run": False, "path": str(folder), "marker": marker, "actions": actions}
