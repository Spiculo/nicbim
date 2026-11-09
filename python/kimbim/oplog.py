# SPDX-License-Identifier: GPL-3.0-or-later
"""The operation log (oplog, doc 03): crash recovery between recovery copies.

The timed recovery copy (D72) is a whole model written every few minutes, so a crash lost the work since
the last one. Every undo step is an ifcopenshell transaction whose operations (create, edit, delete,
with entity ids) are already serialisable: they are what undo and redo replay. The oplog appends each
committed step, undo and redo to `journal.jsonl` in the document's recovery folder, after a base the
replay starts from: the file the session opened or last saved, or the last full recovery copy (each
of these restarts the journal). After a crash, `replay` opens the base, commits the steps in order
(rolling back on an undo, committing again on a redo) and writes the result as the recovery copy, so
reopening loses at most the step being made when it crashed. The project settings travel as a
snapshot with each line, so a settings change (an underlay moved, D92) is recovered too.
"""
from __future__ import annotations

import json
import pathlib
import time

import ifcopenshell

from . import app_bridge as B

JOURNAL = "journal.jsonl"
_state = {"folder": None, "base": "", "lines": 0, "disabled": False}


def _folder() -> pathlib.Path | None:
    from . import documents

    key = documents._recovery_key()
    return documents._recovery_dir(key) if key else None


def _info(folder: pathlib.Path, base: str) -> None:
    from . import documents

    source = documents._doc["source"] or B._path
    (folder / "info.json").write_text(json.dumps({"source": source, "mode": documents._doc["mode"],
                                                  "time": time.time(), "journal": True, "base": base}))


def start(base: str = "") -> None:
    """A new journal: the model now equals `base` on disk (opened, saved, or a full recovery copy). An
    empty base means the folder's own model.ifc (written by write_recovery)."""
    previous = _state.get("folder")
    _state.update(folder=None, base=base, lines=0, disabled=False)
    folder = _folder() if B._model is not None else None
    if previous is not None and previous != folder:  # Save As or another file: the old log is done with
        _drop(previous)
    journal = folder / JOURNAL if folder is not None else None
    if journal is not None and journal.exists():
        journal.unlink()


def _append(entry: dict) -> None:
    if _state["disabled"] or B._model is None:
        return
    folder = _folder()
    if folder is None:
        return
    base = _state["base"] or (str(folder / "model.ifc") if (folder / "model.ifc").exists() else B._path)
    if not base or not pathlib.Path(base).exists():
        return  # nothing to replay from (an untitled model before its first recovery copy)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        from . import settings

        entry["settings"] = json.loads(settings.to_bytes().decode("utf-8") or "{}")
        with open(folder / JOURNAL, "a", encoding="utf-8") as out:
            out.write(json.dumps(entry, separators=(",", ":"), default=_plain) + "\n")
        _state["lines"] += 1
        _state["folder"] = folder
        _info(folder, base)
    except (OSError, TypeError, ValueError):
        _state["disabled"] = True  # never let the log break editing; the timed copy still runs


def _plain(value):
    if isinstance(value, (set, frozenset)):
        return list(value)
    if isinstance(value, bytes):
        return value.decode("latin-1")
    raise TypeError(type(value).__name__)


def committed() -> None:
    """After a new undo step: its operations."""
    if B._model is None or not B._model.history:
        return
    _append({"op": "step", "ops": B._model.history[-1].operations})


def undone() -> None:
    _append({"op": "undo"})


def redone() -> None:
    _append({"op": "redo"})


def lines() -> int:
    return _state["lines"]


def replay(base: str, journal: str, out: str) -> dict:
    """Rebuild the model a journal describes: `base` with every logged step, undo and redo applied, written
    to `out`. Returns {"steps", "settings"} (the last settings snapshot, or None)."""
    import importlib

    Transaction = importlib.import_module("ifcopenshell.file").Transaction  # the module, not the class
    model = ifcopenshell.open(base)
    done, undone_steps = [], []
    steps, settings = 0, None
    with open(journal, encoding="utf-8") as lines_in:
        for line in lines_in:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                break  # a line cut short by the crash: everything before it stands
            settings = entry.get("settings", settings)
            if entry["op"] == "step":
                t = Transaction(model)
                t.operations = entry["ops"]
                t.commit()
                done.append(t)
                undone_steps.clear()
                steps += 1
            elif entry["op"] == "undo" and done:
                t = done.pop()
                t.rollback()
                undone_steps.append(t)
            elif entry["op"] == "redo" and undone_steps:
                t = undone_steps.pop()
                t.commit()
                done.append(t)
    model.write(out)
    return {"steps": steps, "settings": settings}


def _drop(folder: pathlib.Path) -> None:
    """A log that is no longer needed goes, and its folder too unless a timed copy is there."""
    import shutil

    if folder.exists():
        (folder / JOURNAL).unlink(missing_ok=True)
        if not (folder / "model.ifc").exists():
            shutil.rmtree(folder, ignore_errors=True)


def discard_journal() -> str:
    """The app ends normally (no crash): the session's log goes."""
    for folder in {f for f in (_folder() if B._model is not None else None, _state.get("folder")) if f is not None}:
        _drop(folder)
    _state.update(folder=None, base="", lines=0)
    return B._dump({"ok": True})

