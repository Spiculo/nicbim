# SPDX-License-Identifier: GPL-3.0-or-later
"""Studio sessions (D252): the long-running runner with a scripted provider, its inbox, helpers and files."""
import json
import threading
import time

import pytest

from kimbim import documents as D
from kimbim.agent import sessions, studio
from kimbim.agent.providers import Call, Turn


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_data_dir", tmp_path / "data")
    monkeypatch.setenv("KIMBIM_DATA_DIR", str(tmp_path / "data"))
    yield tmp_path / "data"


@pytest.fixture
def store(tmp_path):
    return sessions.Store(tmp_path / "sessions")


class Scripted:
    """A provider that plays turns from a script; a callable entry decides from the history."""
    name = "fake"
    model = "scripted"

    def __init__(self, script):
        self.script = list(script)
        self.history = []
        self.lock = threading.Lock()

    def add_user(self, text):
        self.history.append(("user", text))

    def add_results(self, results, note=""):
        self.history.append(("results", [(c.name, body, ok) for c, body, ok, *_ in results], note))

    def size(self):
        return 0

    def reset(self, text):
        self.history = [("user", text)]

    def step(self):
        with self.lock:
            item = self.script.pop(0) if self.script else Turn(text="done")
        return item(self) if callable(item) else item


def make_runner(store, script, tools=None, helper_script=None, **kw):
    record = store.create("", "test")
    calls = []

    def tool_fn(name, args):
        calls.append((name, args))
        return (tools or {}).get(name, {"ok": True, "result": {"name": name}})

    providers = []

    def factory(system, schemas, effort):
        p = Scripted(script if not providers else (helper_script or []))
        providers.append(p)
        return p

    runner = studio.Runner(record.id, "", tool_fn=tool_fn, provider_factory=factory, store=store, poll=0.01, **kw)
    return runner, record, calls, providers


def test_runs_tools_and_finishes(store):
    script = [Turn(text="Reading", calls=[Call("1", "project_info", {})]),
              Turn(text="All built.")]
    runner, record, calls, providers = make_runner(store, script, exit_when_done=True)
    assert runner.run("Build a house") == "done"
    assert calls == [("project.info", {})]
    assert "The brief:\nBuild a house" in providers[0].history[0][1]
    roles = [e["role"] for e in store.transcript(record.id)]
    assert "tool" in roles and "assistant" in roles
    assert studio.read_state(record.id, store)["state"] == "done"


def test_plan_and_notes_survive_and_resume_reads_them(store):
    script = [Turn(calls=[Call("1", "studio_plan_write", {"text": "# Plan\n- [ ] levels"}),
                          Call("2", "studio_note", {"text": "Lot is 8.66 m wide"})]),
              Turn(text="ok")]
    runner, record, _calls, _p = make_runner(store, script, exit_when_done=True)
    runner.run("brief")
    assert studio.read_file(record.id, studio.PLAN, store).startswith("# Plan")
    assert "8.66 m" in studio.read_file(record.id, studio.NOTES, store)
    again = studio.Runner(record.id, "", tool_fn=lambda n, a: {"ok": True}, store=store, exit_when_done=True,
                          provider_factory=lambda s, t, e: Scripted([Turn(text="resumed")]), poll=0.01)
    seen = []
    again.provider_factory = lambda s, t, e: seen.append(Scripted([Turn(text="resumed")])) or seen[-1]
    again.run("brief")
    opening = seen[0].history[0][1]
    assert "resuming" in opening and "# Plan" in opening and "8.66 m" in opening


def test_steering_lands_next_to_tool_results(store):
    def first(p):
        studio.send(runner.id, "say", "Make the stair wider", store=store)
        return Turn(calls=[Call("1", "levels_list", {})])

    script = [first, Turn(text="noted")]
    runner, record, _calls, providers = make_runner(store, script, exit_when_done=True)
    runner.run("brief")
    results = [h for h in providers[0].history if h[0] == "results"]
    assert results and results[0][2] == "Architect: Make the stair wider"


def test_waits_for_the_architect_then_continues_and_stops(store):
    script = [Turn(text="What should I design?"), Turn(text="On it", calls=[Call("1", "project_info", {})]),
              Turn(text="Done for now")]
    runner, record, calls, providers = make_runner(store, script)
    thread = threading.Thread(target=runner.run, args=("",))
    thread.start()
    for _ in range(300):
        if studio.read_state(record.id, store).get("state") == "waiting":
            break
        time.sleep(0.01)
    assert studio.read_state(record.id, store)["state"] == "waiting"
    studio.send(record.id, "say", "A two-storey house", store=store)
    for _ in range(300):
        if calls:
            break
        time.sleep(0.01)
    studio.send(record.id, "stop", store=store)
    thread.join(5)
    assert not thread.is_alive()
    assert calls == [("project.info", {})]
    assert ("user", "Architect: A two-storey house") in providers[0].history
    assert studio.read_state(record.id, store)["state"] == "stopped"


def test_pause_holds_until_resume(store):
    def pausing(p):
        studio.send(runner.id, "pause", store=store)
        return Turn(calls=[Call("1", "project_info", {})])

    script = [pausing, Turn(text="after")]
    runner, record, _calls, providers = make_runner(store, script, exit_when_done=True)
    thread = threading.Thread(target=runner.run, args=("",))
    thread.start()
    for _ in range(300):
        if studio.read_state(record.id, store).get("state") == "paused":
            break
        time.sleep(0.01)
    assert studio.read_state(record.id, store)["state"] == "paused"
    studio.send(record.id, "resume", store=store)
    thread.join(5)
    assert studio.read_state(record.id, store)["state"] == "done"


def test_spawned_helpers_run_in_parallel_and_report(store):
    started = []
    gate = threading.Event()

    def helper_turn(p):
        started.append(1)
        if len(started) >= 2:
            gate.set()
        gate.wait(5)  # both helpers must be running at the same time to get past this
        return Turn(text="helper report")

    script = [Turn(calls=[Call("1", "studio_spawn", {"name": "a", "brief": "level 1"}),
                          Call("2", "studio_spawn", {"name": "b", "brief": "level 2"})]),
              Turn(text="merged")]
    runner, record, _calls, providers = make_runner(store, script, helper_script=[helper_turn],
                                                     exit_when_done=True)
    # every helper gets its own provider with one scripted turn
    base = runner.provider_factory
    runner.provider_factory = lambda s, t, e: base(s, t, e) if not providers else Scripted([helper_turn])
    assert runner.run("") == "done"
    assert gate.is_set()
    results = [h for h in providers[0].history if h[0] == "results"][0][1]
    assert [json.loads(body)["report"] for _n, body, _ok in results] == ["helper report", "helper report"]


def test_small_task_runs_as_a_helper_and_reports_back(store):
    def first(p):
        studio.send(runner.id, "task", "Rename level 1 to Planta baja", store=store)
        return Turn(calls=[Call("1", "project_info", {})])

    def later(p):
        for _ in range(200):  # the task's report reaches the main agent on a later round
            if any("small task" in str(h) and "Helper report" in str(h) for h in p.history):
                return Turn(text="seen")
            time.sleep(0.01)
            return Turn(calls=[Call("x", "levels_list", {})])
        return Turn(text="never")

    script = [first] + [later] * 50
    runner, record, calls, providers = make_runner(store, script, exit_when_done=True)
    base = runner.provider_factory
    runner.provider_factory = lambda s, t, e: base(s, t, e) if not providers else Scripted(
        [Turn(calls=[Call("t", "levels_edit", {"level": "Level 1", "name": "Planta baja"})]), Turn(text="renamed")])
    runner.run("")
    assert ("levels.edit", {"level": "Level 1", "name": "Planta baja"}) in calls
    assert any("Helper report" in str(h) for h in providers[0].history)


def test_long_results_are_cut_and_unknown_tools_fail(store):
    big = {"ok": True, "result": {"items": ["x" * 100] * 1000}}
    script = [Turn(calls=[Call("1", "elements_find", {}), Call("2", "nope", {})]), Turn(text="ok")]
    runner, record, _calls, providers = make_runner(store, script, tools={"elements.find": big},
                                                     exit_when_done=True)
    runner.run("")
    (_n1, body1, ok1), (_n2, body2, ok2) = [h for h in providers[0].history if h[0] == "results"][0][1]
    assert ok1 and "[cut:" in body1 and len(body1) < studio.RESULT_CHARS + 200
    assert not ok2 and "unknown tool" in body2


def test_send_rejects_unknown_kinds_and_sessions(store):
    record = store.create("", "x")
    with pytest.raises(Exception):
        studio.send(record.id, "dance", store=store)
    with pytest.raises(Exception):
        studio.send("missing", "say", "hi", store=store)


def test_status_of_a_dead_runner_reads_stopped(store):
    record = store.create("", "x")
    studio.write_state(record.id, store, state="working", pid=999999)
    assert studio.status(record.id, store)["state"] == "stopped"


class Failing(Scripted):
    def step(self):
        from kimbim.agent.providers import ProviderError
        raise ProviderError("the provider answered 401: expired key")


def test_provider_failure_fails_cleanly_when_unattended(store):
    record = store.create("", "x")
    runner = studio.Runner(record.id, "", tool_fn=lambda n, a: {"ok": True}, store=store, exit_when_done=True,
                           provider_factory=lambda s, t, e: Failing([]), poll=0.01)
    assert runner.run("brief") == "failed"
    assert "expired key" in studio.read_state(record.id, store)["error"]


def test_provider_failure_waits_and_a_message_starts_a_fresh_provider(store):
    record = store.create("", "x")
    made = []

    def factory(s, t, e):
        made.append(1)
        return Failing([]) if len(made) == 1 else Scripted([Turn(text="back")])

    runner = studio.Runner(record.id, "", tool_fn=lambda n, a: {"ok": True}, store=store, provider_factory=factory,
                           poll=0.01)
    thread = threading.Thread(target=runner.run, args=("brief",))
    thread.start()
    for _ in range(300):
        if studio.read_state(record.id, store).get("error"):
            break
        time.sleep(0.01)
    studio.send(record.id, "say", "new key set, go on", store=store)
    for _ in range(300):
        if len(made) >= 2 and any(e.get("text") == "back" for e in store.transcript(record.id)):
            break
        time.sleep(0.01)
    studio.send(record.id, "stop", store=store)
    thread.join(5)
    assert len(made) == 2 and any(e.get("text") == "back" for e in store.transcript(record.id))


def test_one_task_for_the_session(store):
    record = store.create("", "Casa")
    calls = []

    def tool_fn(name, args):
        calls.append((name, args))
        if name == "task.status":
            return {"ok": True, "result": {"task": None}}
        if name == "task.start":
            return {"ok": True, "result": {"id": "t1", "mode": "direct"}}
        return {"ok": True, "result": {}}

    seen = []
    runner = studio.Runner(record.id, "C:/somewhere", tool_fn=tool_fn, store=store, exit_when_done=True,
                           provider_factory=lambda s, t, e: seen.append(Scripted([Turn(text="ok")])) or seen[-1],
                           poll=0.01)
    runner.run("brief")
    assert calls[:2] == [("task.status", {}), ("task.start", {"title": "Studio: Casa", "mode": "direct"})]
    assert "Session task: t1 (direct mode)" in seen[0].history[0][1]
    assert studio.read_state(record.id, store)["task"] == "t1"
