# SPDX-License-Identifier: GPL-3.0-or-later
"""Linear visual scripts (D223).

Grasshopper, Dynamo and Marionette are node graphs; KimBim's visual script is a linear stack of
engine operations (a massing, a room, a push/pull, a mesh vertex move) saved with the project
under ``visual_scripts``. A step is ``{op, args}`` and can refer to an earlier step's new element
with ``"$1"`` (the first step), so a short program can build then shape. Only whitelisted
operations run - a saved script is data, not Python - and a whole run is one undo step.
"""
from __future__ import annotations

import json

from kimbim import authoring as A
from kimbim import app_bridge as B
from kimbim import morph as M
from kimbim import rooms as R
from kimbim import settings as S


def _massing(args, level):
    return A.create_massing(level, args.get("x", 0), args.get("y", 0), args.get("width", 10),
                            args.get("depth", 10), args.get("height", 3),
                            str(args.get("name") or "Massing"))


def _room(args, level):
    return R.create_room(level, args.get("x", 0), args.get("y", 0), str(args.get("name") or "Room"))


def _push_pull(args, _level):
    return M.push_pull(str(args.get("guid") or ""), str(args.get("face") or "+z"),
                       args.get("distance", 1))


def _move_vertices(args, _level):
    return M.move_vertices(str(args.get("guid") or ""), json.dumps(args.get("indices") or []),
                           args.get("dx", 0), args.get("dy", 0), args.get("dz", 0))


OPS = {
    "massing": (_massing, ("x", "y", "width", "depth", "height", "name")),
    "room": (_room, ("x", "y", "name")),
    "push_pull": (_push_pull, ("guid", "face", "distance")),
    "move_vertices": (_move_vertices, ("guid", "indices", "dx", "dy", "dz")),
}


def _stored() -> dict:
    data = S.current().get("visual_scripts", {})
    return data if isinstance(data, dict) else {}


def _steps(name: str) -> list | None:
    steps = _stored().get(name)
    return steps if isinstance(steps, list) else None


def pipeline_ops() -> str:
    """The operations a visual script may use, with their argument names."""
    return B._dump({"ok": True, "ops": [{"op": op, "args": list(args)} for op, (_, args) in OPS.items()]})


def pipelines() -> str:
    """The saved visual scripts, in name order."""
    out = [{"name": name, "steps": steps} for name, steps in sorted(_stored().items())]
    return B._dump({"ok": True, "pipelines": out})


def save_pipeline(name: str, steps_json: str) -> str:
    """Add or replace a visual script; steps are a list of {op, args}."""
    name = str(name or "").strip()
    if not name:
        return A._fail("type a script name")
    try:
        steps = json.loads(steps_json) if isinstance(steps_json, str) else list(steps_json)
    except (TypeError, ValueError) as ex:
        return A._fail(f"bad steps: {ex}")
    error = _steps_error(steps)
    if error:
        return A._fail(error)
    scripts = {**_stored(), name: steps}

    def action():
        S.set_project_settings(json.dumps({"visual_scripts": scripts}))
        return 0, [], []

    try:
        result = B._run_settings(action)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**result, "name": name, "steps": steps})


def _steps_error(steps) -> str | None:
    if not isinstance(steps, list) or not steps:
        return "a visual script needs at least one step"
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict) or not isinstance(step.get("op"), str):
            return f"step {index} needs an op"
        if step["op"] not in OPS:
            return f"step {index}: unknown op {step['op']!r}"
        if step.get("args") is not None and not isinstance(step.get("args"), dict):
            return f"step {index}: args is a table"
    return None


def delete_pipeline(name: str) -> str:
    """Remove a visual script."""
    scripts = dict(_stored())
    if name not in scripts:
        return A._fail("script not found")
    scripts.pop(name)

    def action():
        S.set_project_settings(json.dumps({"visual_scripts": scripts}))
        return 0, [], []

    try:
        result = B._run_settings(action)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**result, "name": name})


def _resolve(value, results):
    """Replace "$n" (1-based) with the guid or value produced by that step, recursively."""
    if isinstance(value, str) and value.startswith("$") and value[1:].isdigit():
        index = int(value[1:]) - 1
        if index < 0 or index >= len(results):
            raise ValueError(f"step reference {value} is not available yet")
        result = results[index]
        return result.get("guid") if isinstance(result, dict) else result
    if isinstance(value, list):
        return [_resolve(v, results) for v in value]
    if isinstance(value, dict):
        return {k: _resolve(v, results) for k, v in value.items()}
    return value


def run_pipeline(name: str, level_guid: str = "") -> str:
    """Run a saved script from top to bottom as one undo step and return each step's result."""
    if B._model is None:
        return A._fail("no model open")
    steps = _steps(name)
    if steps is None:
        return A._fail("script not found")
    level = level_guid or (sorted(B._model.by_type("IfcBuildingStorey"), key=lambda s: s.elevation or 0.0)[0].GlobalId
                           if B._model.by_type("IfcBuildingStorey") else "")
    if not level:
        return A._fail("the project has no level")
    results: list = []
    from . import console

    try:
        B._begin()
        B._step = ([], [])  # every operation joins this one undo step
        try:
            for index, step in enumerate(steps, start=1):
                op = step.get("op")
                fn = OPS[op][0]
                try:
                    args = _resolve(step.get("args") or {}, results)
                    raw = fn(args, level)
                except Exception as ex:  # noqa: BLE001 - report the step and roll the whole run back
                    raise ValueError(f"step {index} ({op}): {ex}") from ex
                try:
                    payload = json.loads(raw)
                except (TypeError, ValueError):
                    payload = {"ok": False, "error": str(raw)}
                if not payload.get("ok"):
                    raise ValueError(f"step {index} ({op}): {payload.get('error', 'failed')}")
                results.append(payload)
        except BaseException as failure:
            B._step = None
            B._abort(failure)
            raise
        console._finish_step()
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    guids = [r.get("guid") for r in results if r.get("guid")]
    return B._dump({"ok": True, "changed": len(results), "name": name, "results": results,
                    "geometry": {"changed": guids, "removed": []}})
