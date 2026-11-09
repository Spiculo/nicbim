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


def _number(args, _level):
    return B._dump({"ok": True, "value": float(args.get("value", 0) or 0)})


def _arith(fn):
    def run(args, _level):
        return B._dump({"ok": True, "value": fn(float(args.get("a", 0) or 0), float(args.get("b", 0) or 0))})
    return run


OPS = {
    "number": (_number, ("value",)),  # D238: value nodes, so numbers can flow between nodes
    "add": (_arith(lambda a, b: a + b), ("a", "b")),
    "subtract": (_arith(lambda a, b: a - b), ("a", "b")),
    "multiply": (_arith(lambda a, b: a * b), ("a", "b")),
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
        if isinstance(result, dict):  # an element node gives its guid, a value node its value
            return result["guid"] if "guid" in result else result.get("value")
        return result
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
    levels = sorted((s for s in B._model.by_type("IfcBuildingStorey") if not A._is_model(s)), key=A._elevation)
    level = level_guid or (levels[0].GlobalId if levels else "")  # default: the lowest building level
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


# ---------------------------------------------------------------- D238: the node graph

def steps_to_graph(steps_json: str) -> str:
    """A script's steps as a node graph: {"nodes": [{id, op, args, x, y}], "links": [{from, to, arg}]}.
    A "$n" argument is a wire from node n (1-based step); other arguments stay literal values."""
    try:
        steps = json.loads(steps_json) if isinstance(steps_json, str) else list(steps_json)
    except (TypeError, ValueError) as ex:
        return A._fail(f"bad steps: {ex}")
    nodes, links = [], []
    for i, step in enumerate(steps, start=1):
        args = dict(step.get("args") or {})
        for name, value in list(args.items()):
            if isinstance(value, str) and value.startswith("$") and value[1:].isdigit():
                links.append({"from": int(value[1:]), "to": i, "arg": name})
                del args[name]
        pos = step.get("pos") or [40 + 220 * (i - 1), 40]
        nodes.append({"id": i, "op": step.get("op"), "args": args, "x": float(pos[0]), "y": float(pos[1])})
    return B._dump({"ok": True, "nodes": nodes, "links": links})


def graph_to_steps(graph_json: str) -> str:
    """The script a node graph runs: nodes in dependency order (a node after every node wired into it),
    each wire written as "$n", positions kept. A cycle or a wire to an unknown node is refused."""
    try:
        graph = json.loads(graph_json) if isinstance(graph_json, str) else dict(graph_json)
        nodes = {n["id"]: n for n in graph.get("nodes", [])}
        links = list(graph.get("links", []))
    except (TypeError, ValueError, KeyError) as ex:
        return A._fail(f"bad graph: {ex}")
    if not nodes:
        return A._fail("the graph has no nodes")
    inputs: dict = {i: [] for i in nodes}
    for link in links:
        if link.get("from") not in nodes or link.get("to") not in nodes:
            return A._fail("a wire joins a node that is not in the graph")
        if link["from"] == link["to"]:
            return A._fail("a node cannot feed itself")
        inputs[link["to"]].append(link)
    order, state = [], {}

    def visit(i):
        if state.get(i) == "done":
            return True
        if state.get(i) == "busy":
            return False  # a loop
        state[i] = "busy"
        for link in sorted(inputs[i], key=lambda l: str(l["arg"])):
            if not visit(link["from"]):
                return False
        state[i] = "done"
        order.append(i)
        return True

    for i in sorted(nodes, key=lambda i: (nodes[i].get("x", 0), nodes[i].get("y", 0), i)):  # left to right
        if not visit(i):
            return A._fail("the wires make a loop: a node cannot depend on itself")
    index = {node_id: n for n, node_id in enumerate(order, start=1)}
    steps = []
    for node_id in order:
        node = nodes[node_id]
        args = dict(node.get("args") or {})
        for link in inputs[node_id]:
            args[link["arg"]] = f"${index[link['from']]}"
        steps.append({"op": node.get("op"), "args": args, "pos": [node.get("x", 0), node.get("y", 0)]})
    error = _steps_error(steps)
    if error:
        return A._fail(error)
    return B._dump({"ok": True, "steps": steps})


def save_graph(name: str, graph_json: str) -> str:
    """Save a node graph as a visual script (its steps in dependency order, see graph_to_steps)."""
    r = json.loads(graph_to_steps(graph_json))
    if not r.get("ok"):
        return B._dump(r)
    return save_pipeline(name, json.dumps(r["steps"]))

