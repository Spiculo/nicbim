# SPDX-License-Identifier: GPL-3.0-or-later
"""Studio sessions (D252): a long-running agent that designs and builds with the architect.

One runner process per stored session (D111). It calls the same tool catalogue through `client.request`, which
reaches the app's live host when the project is open there (every write is an undo step the architect sees at
once) and a background worker otherwise. The architect steers it at any time from the CLI (`kimbim studio say`)
or the app's Assistant panel; both write to the session's inbox, which the runner drains before every model call.

Session files, beside the D111 `session.json` and `transcript.jsonl`:

    studio.json   runner pid, state, provider/model/effort, brief, counters, the inbox offset
    inbox.jsonl   what the architect sends: say, task, pause, resume, stop
    plan.md       the agent's plan (studio_plan_write), kept across restarts
    notes.md      the agent's progress notes and decisions (studio_note)
    summary.md    the last context summary, when the runner compacted the conversation itself
    runner.log    the detached runner's output

States: starting, working, waiting (for the architect), paused, stopped, failed, done.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import catalogue, sessions
from .providers import Call, ProviderError, Turn

STATE_FILE, INBOX, PLAN, NOTES, SUMMARY, LOG = ("studio.json", "inbox.jsonl", "plan.md", "notes.md", "summary.md",
                                                "runner.log")
KINDS = ("say", "task", "pause", "resume", "stop")
LIVE_STATES = ("starting", "working", "waiting", "paused")
RESULT_CHARS = 24000      # a tool result longer than this is cut before the model sees it
COMPACT_CHARS = 600_000   # the runner summarises an OpenAI-style history past this size (Anthropic compacts itself)
MAX_HELPERS = 4           # helpers running at once
HELPER_ROUNDS = 400       # a helper that has not finished after this many model calls reports what it has
RETRIES = 8
TOOL_TIMEOUT = 900.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _store() -> sessions.Store:
    return sessions.Store()


def session_dir(session_id: str, store: sessions.Store | None = None) -> pathlib.Path:
    return (store or _store()).dir(session_id)


def read_state(session_id: str, store: sessions.Store | None = None) -> dict:
    path = session_dir(session_id, store) / STATE_FILE
    for _attempt in range(50):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except PermissionError:  # being replaced right now (Windows): try again
            time.sleep(0.02)
        except (OSError, ValueError):
            return {}
    return {}


_state_lock = threading.Lock()


def write_state(session_id: str, store: sessions.Store | None = None, **fields) -> dict:
    """Merge `fields` into studio.json atomically. On Windows a reader holding the file makes the replace fail
    for a moment: retry, and never let a state write stop the agent."""
    path = session_dir(session_id, store) / STATE_FILE
    with _state_lock:
        data = {**read_state(session_id, store), **fields, "updated": _now()}
        tmp = path.with_name(f"{STATE_FILE}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        for attempt in range(50):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                time.sleep(0.02)
        else:
            try:
                tmp.unlink()
            except OSError:
                pass
    return data


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def status(session_id: str, store: sessions.Store | None = None) -> dict:
    """The runner's state; a live-looking state whose process is gone reads as `stopped`."""
    state = read_state(session_id, store)
    if state.get("state") in LIVE_STATES and not _pid_alive(int(state.get("pid") or 0)):
        state["state"] = "stopped"
        state["note"] = "the runner process is not running"
    return state


def send(session_id: str, kind: str, text: str = "", source: str = "cli", store: sessions.Store | None = None) -> dict:
    """Put a message in the session's inbox: the runner reads it before its next model call."""
    if kind not in KINDS:
        raise catalogue.AgentError("bad_input", hint=f"kind must be one of {', '.join(KINDS)}")
    store = store or _store()
    store.get(session_id)  # unknown session -> AgentError
    entry = {"time": _now(), "kind": kind, "text": str(text or ""), "source": source}
    path = session_dir(session_id, store) / INBOX
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    if kind in ("say", "task"):
        store.append(session_id, {"role": "user", "text": text, "source": source, "kind": kind})
    else:
        store.append(session_id, {"role": "status", "text": f"{source}: {kind}"})
    return entry


def read_file(session_id: str, name: str, store: sessions.Store | None = None) -> str:
    try:
        return (session_dir(session_id, store) / name).read_text(encoding="utf-8")
    except OSError:
        return ""


# ---------------------------------------------------------------- prompts and studio tools

SYSTEM = """\
You are the studio agent of NicBim, a BIM application for architects. You design and build a building together
with an architect, in a long session. The architect works in the same model at the same time in the app and sees
each of your changes as soon as you make it; they also send you messages and small tasks while you work.

How to work:
- Start by reading the project (project_info, levels_list) and your plan (studio_plan_read). If there is no plan,
  write one with studio_plan_write: the phases (brief and site, levels and grid, structure and envelope, interiors
  and objects, rooms and schedules, drawings and sheets, delivery) with checkable steps. Keep it current: mark steps
  done and add what you learn.
- Record decisions, assumptions and progress with studio_note, briefly. The plan and notes survive restarts; the
  conversation may be summarised.
- The model can change under you because the architect edits too. Re-read before editing something you read a
  while ago, and never undo their work; build around it and say so.
- Look at your work: take a snapshot (snapshot_take) of plans, sections, elevations and 3D after each phase and
  check it as an architect would: proportions, clearances, alignments, overlaps, what reads wrong on paper.
- Use studio_spawn for independent chunks (one floor's interiors, a set of drawings and sheets, schedules, a
  family of library objects). Give each helper a clear scope that does not overlap another helper's elements,
  and check what it reports. Several studio_spawn calls in one answer run in parallel.
- When a design decision belongs to the architect, ask with studio_ask and continue with a sensible default
  (Archicad's convention, otherwise Revit's), noting the assumption; change it if they answer differently.
- Messages from the architect arrive as text starting with "Architect:". Follow them; a message that changes the
  design comes before your plan.
- Lengths are metres unless you add units ("50cm"). Answer in the language the architect writes in. Be concise
  in messages; put detail in notes.
- Never claim a change you did not make. When a tool fails, read the error, fix the input or take another route.
- Your changes go in one task the runner opened for this session (named below). Do not start or finish tasks
  yourself; save a version (versions_save) at the end of each phase so there is a way back.

NicBim specifics:
- Numbers are in the project's length unit (project_info "unit", normally metres); strings may carry units.
- A new project is placed on the map with site_locate (latitude, longitude, elevation, north angle, CRS; Uruguay:
  EPSG:5382) and named for the title blocks with project_set_info. Check site_get first: it may be located already.
- Before creating walls, slabs, doors or windows, list the types (create_types) and pick by name; walls are drawn
  on their reference line between two points; doors and windows go in a wall by distance along it (create_opening).
- Library objects: objects_library lists them (furniture, sanitary, kitchen, office, education, shops, industrial,
  site); objects_place puts one at a point, objects_set_parameters changes its size.
- Every level has a floor plan; the template has four elevations. Make sections with drawings_create, rooms with
  create_room (they show name, number and area), then sheets: sheets_create (A1/A3), sheets_place_drawing with a
  scale, schedules with sheets_place_schedule.
- The first snapshot of a session can take a minute (the renderer starts); later ones take seconds.
- Deliver with deliver_package into the folder the architect names (default: a "delivery" folder beside the
  project); save a version first so the transmittal names it.
"""

HELPER = """\
You are a helper of the NicBim studio agent. You do one scoped job in a BIM model that an architect and other
agents edit at the same time. Stay inside your scope: touch only the elements your brief names or that you
create. Read before you edit, check your result with a snapshot when it matters, and finish with a short report:
what you made or changed (with GlobalIds when useful), what you could not do and why. Lengths are metres unless
you add units.
"""

STUDIO_TOOLS = [
    {"name": "studio_plan_read", "description": "Read your plan (plan.md) and your latest notes.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "studio_plan_write", "description": "Replace your plan (markdown). Keep phases and checkable steps; "
                                                 "mark done steps [x].",
     "input_schema": {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}}},
    {"name": "studio_note", "description": "Append a short note: a decision, an assumption, progress or a problem.",
     "input_schema": {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}}},
    {"name": "studio_spawn", "description": "Run a helper agent on one scoped job with the same tools, and get its "
                                            "report. Several calls in one answer run in parallel (at most 4 at once).",
     "input_schema": {"type": "object", "required": ["name", "brief"], "properties": {
         "name": {"type": "string", "description": "A short name, e.g. \"level-2 interiors\"."},
         "brief": {"type": "string", "description": "The job: scope, elements, constraints, what to report."},
         "effort": {"type": "string", "enum": ["low", "medium", "high", "xhigh"],
                    "description": "Reasoning effort (default medium)."}}}},
    {"name": "studio_ask", "description": "Ask the architect a question without stopping; the answer arrives later "
                                          "as an Architect: message. Continue with a sensible default meanwhile.",
     "input_schema": {"type": "object", "required": ["question"], "properties": {"question": {"type": "string"}}}},
]
HELPER_EXCLUDED = ("studio_spawn", "studio_plan_write")


def catalogue_tools() -> tuple[list[dict], dict[str, str]]:
    schemas, back = [], {}
    for name, t in catalogue.TOOLS.items():
        if name.startswith("_"):
            continue
        public = name.replace(".", "_")
        back[public] = name
        schemas.append({"name": public, "description": t.description, "input_schema": t.params})
    return schemas, back


def _summary(name: str, envelope: dict) -> str:
    if not envelope.get("ok"):
        err = envelope.get("error") or {}
        return f"{name}: {err.get('message') or err.get('code') or 'failed'} {err.get('hint') or ''}".strip()
    counts = (envelope.get("changes") or {}).get("counts") or {}
    total = sum(int(counts.get(k, 0) or 0) for k in ("added", "modified", "removed"))
    if total:
        return f"{name}: {total} element(s) changed"
    result = envelope.get("result")
    if isinstance(result, dict):
        for key in ("path", "message", "count", "total", "guid", "name"):
            if key in result and not isinstance(result[key], (dict, list)):
                return f"{name}: {result[key]}"
    return name


# ---------------------------------------------------------------- the runner

class Stopped(Exception):
    pass


class Runner:
    """The loop of one studio session. `tool_fn(name, args)` runs a catalogue tool and returns its envelope;
    `provider_factory(system, tools, effort)` makes a provider. Both are injectable for tests."""

    def __init__(self, session_id: str, project: str, *, provider: str = "", model: str = "", effort: str = "high",
                 base_url: str = "", tool_fn=None, provider_factory=None, store: sessions.Store | None = None,
                 exit_when_done: bool = False, poll: float = 1.0, client_name: str = ""):
        self.id, self.project = session_id, os.path.abspath(project) if project else ""
        self.store = store or _store()
        self.provider_name, self.model, self.effort, self.base_url = provider, model, effort or "high", base_url
        self.client_name = client_name or f"studio-{session_id[:6]}"
        self.tool_fn = tool_fn or self._request
        self.provider_factory = provider_factory or self._make_provider
        self.exit_when_done = exit_when_done
        self.poll = poll
        self.schemas, self.back = catalogue_tools()
        self.dir = session_dir(session_id, self.store)
        self._inbox_offset = int(read_state(session_id, self.store).get("inbox_offset") or 0)
        self._lock = threading.Lock()
        self._helper_reports: list[str] = []
        self._helpers = ThreadPoolExecutor(max_workers=MAX_HELPERS, thread_name_prefix="studio-helper")
        self._stop = threading.Event()
        self._task_threads: list[threading.Thread] = []
        self.calls = 0

    # -- plumbing
    def _request(self, name: str, args: dict) -> dict:
        from . import client
        return client.request(self.project, name, args, client=self.client_name, timeout=TOOL_TIMEOUT)

    def _make_provider(self, system: str, tools: list[dict], effort: str):
        from . import providers
        return providers.make(self.provider_name, system, tools, self.model, effort, self.base_url)

    def _log(self, entry: dict) -> None:
        try:
            self.store.append(self.id, entry)
        except OSError:
            pass

    def _state(self, state: str, **fields) -> None:
        write_state(self.id, self.store, state=state, **fields)

    def _drain(self) -> list[dict]:
        path = self.dir / INBOX
        try:
            with path.open("rb") as f:
                f.seek(self._inbox_offset)
                data = f.read()
        except OSError:
            return []
        end = data.rfind(b"\n")
        if end < 0:
            return []
        self._inbox_offset += end + 1
        write_state(self.id, self.store, inbox_offset=self._inbox_offset)
        out = []
        for line in data[:end + 1].splitlines():
            try:
                entry = json.loads(line.decode("utf-8"))
            except ValueError:
                continue
            if isinstance(entry, dict) and entry.get("kind") in KINDS:
                out.append(entry)
        return out

    def _messages(self, block: bool) -> list[str]:
        """Architect text and finished helper reports since the last call; handles pause/stop/task. With
        `block`, waits until there is something to say."""
        while True:
            texts: list[str] = []
            for entry in self._drain():
                kind, text = entry["kind"], entry.get("text", "")
                if kind == "stop":
                    raise Stopped()
                if kind == "pause":
                    self._pause()
                elif kind == "say" and text.strip():
                    texts.append(f"Architect: {text.strip()}")
                elif kind == "task" and text.strip():
                    self._start_task(text.strip())
                    texts.append(f"Architect (small task, a helper is doing it now): {text.strip()}")
            with self._lock:
                texts.extend(self._helper_reports)
                self._helper_reports.clear()
            if texts or not block:
                return texts
            self._state("waiting")
            time.sleep(self.poll)

    def _pause(self) -> None:
        self._state("paused")
        self._log({"role": "status", "text": "Paused"})
        while True:
            for entry in self._drain():
                if entry["kind"] == "stop":
                    raise Stopped()
                if entry["kind"] == "resume":
                    self._state("working")
                    self._log({"role": "status", "text": "Resumed"})
                    return
                if entry["kind"] in ("say", "task") and entry.get("text"):
                    # keep it for after the pause
                    with self._lock:
                        prefix = "Architect" if entry["kind"] == "say" else "Architect (small task)"
                        self._helper_reports.append(f"{prefix}: {entry['text']}")
            time.sleep(self.poll)

    # -- tools
    def _studio_tool(self, call: Call, helper: str = "") -> tuple[str, bool]:
        args = call.args or {}
        if call.name == "studio_plan_read":
            plan = read_file(self.id, PLAN, self.store) or "(no plan yet: write one with studio_plan_write)"
            notes = read_file(self.id, NOTES, self.store)
            return json.dumps({"plan": plan, "notes": notes[-6000:]}, ensure_ascii=False), True
        if call.name == "studio_plan_write":
            (self.dir / PLAN).write_text(str(args.get("text") or ""), encoding="utf-8")
            self._log({"role": "status", "text": "Plan updated", "agent": helper or "main"})
            return '{"ok": true}', True
        if call.name == "studio_note":
            text = " ".join(str(args.get("text") or "").split())
            with self._lock, (self.dir / NOTES).open("a", encoding="utf-8") as f:
                f.write(f"- {_now()[:16]} {('[' + helper + '] ') if helper else ''}{text}\n")
            self._log({"role": "note", "text": text, "agent": helper or "main"})
            return '{"ok": true}', True
        if call.name == "studio_ask":
            question = str(args.get("question") or "").strip()
            self._log({"role": "question", "text": question, "agent": helper or "main"})
            return '{"ok": true, "asked": true}', True
        if call.name == "studio_spawn":
            return self._spawn(str(args.get("name") or "helper"), str(args.get("brief") or ""),
                               str(args.get("effort") or "medium")), True
        return json.dumps({"ok": False, "error": {"code": "unknown_tool", "message": call.name}}), False

    def _run_call(self, call: Call, helper: str = "") -> tuple[Call, str, bool, str]:
        """One call -> (call, body for the model, ok, image path)."""
        if call.name.startswith("studio_"):
            body, ok = self._studio_tool(call, helper)
            return call, body, ok, ""
        name = self.back.get(call.name)
        if name is None:
            envelope = {"ok": False, "error": {"code": "unknown_tool", "message": f"unknown tool {call.name}"}}
        elif "_invalid_json" in (call.args or {}):
            envelope = {"ok": False, "error": {"code": "bad_input", "message": "the arguments were not valid JSON"}}
        else:
            try:
                envelope = self.tool_fn(name, call.args or {})
            except Exception as ex:  # noqa: BLE001 (the model gets the error and carries on)
                envelope = {"ok": False, "error": {"code": "bridge_error", "message": str(ex)}}
        self.calls += 1
        ok = bool(envelope.get("ok"))
        result = envelope.get("result")
        image = str(result.get("path") or "") if name == "snapshot.take" and isinstance(result, dict) else ""
        snapshot = image
        if image:
            try:
                snapshot = self.store.attachment(self.id, image)
            except OSError:
                pass
        self._log({"role": "tool", "name": call.name, "summary": _summary(call.name, envelope), "ok": ok,
                   "snapshot": snapshot, "agent": helper or "main"})
        body = json.dumps(envelope, ensure_ascii=False, default=str)
        if len(body) > RESULT_CHARS:
            body = body[:RESULT_CHARS] + f'... [cut: {len(body)} characters; ask for less, e.g. a filter or a cursor]'
        return call, body, ok, image if ok else ""

    def _run_calls(self, calls: list[Call], helper: str = "") -> list[tuple[Call, str, bool, str]]:
        spawns = [c for c in calls if c.name == "studio_spawn"] if not helper else []
        others = [c for c in calls if c not in spawns]
        results: dict[int, tuple] = {}
        futures = {id(c): self._helpers.submit(self._run_call, c, helper) for c in spawns}
        for c in others:  # the live host runs one request at a time anyway: keep them in order
            results[id(c)] = self._run_call(c, helper)
        for c in spawns:
            results[id(c)] = futures[id(c)].result()
        return [results[id(c)] for c in calls]

    # -- helpers
    def _spawn(self, name: str, brief: str, effort: str) -> str:
        self._log({"role": "status", "text": f"Helper started: {name}", "agent": name})
        try:
            report = self._helper_loop(name, brief, effort)
        except Stopped:
            report = "(stopped by the architect)"
        except ProviderError as ex:
            report = f"(the helper failed: {ex.message})"
        self._log({"role": "assistant", "text": report, "agent": name})
        self._log({"role": "status", "text": f"Helper finished: {name}", "agent": name})
        return json.dumps({"helper": name, "report": report}, ensure_ascii=False)

    def _helper_loop(self, name: str, brief: str, effort: str) -> str:
        tools = self.schemas + [t for t in STUDIO_TOOLS if t["name"] not in HELPER_EXCLUDED]
        provider = self.provider_factory(HELPER, tools, effort)
        provider.add_user(f"Your job ({name}):\n{brief}")
        text = ""
        for _ in range(HELPER_ROUNDS):
            if self._stop.is_set():
                raise Stopped()
            turn = self._step(provider, agent=name)
            text = turn.text.strip() or text
            if not turn.calls:
                return text or "(no report)"
            provider.add_results(self._run_calls(turn.calls, helper=name))
        return (text or "") + "\n(the helper stopped after its round limit; continue the job or split it)"

    def _start_task(self, text: str) -> None:
        def run():
            report = json.loads(self._spawn("task", f"A small task from the architect:\n{text}", "medium"))["report"]
            with self._lock:
                self._helper_reports.append(f"Helper report for the architect's small task \"{text[:80]}\":\n{report}")
        thread = threading.Thread(target=run, name="studio-task", daemon=True)
        self._task_threads.append(thread)
        thread.start()

    # -- model calls
    def _step(self, provider, agent: str = "main") -> Turn:
        delay = 5.0
        for attempt in range(RETRIES):
            try:
                turn = provider.step()
                break
            except ProviderError as ex:
                if not ex.retry or attempt == RETRIES - 1:
                    raise
                self._log({"role": "status", "text": f"Provider busy ({ex.message[:120]}); retrying in {delay:.0f} s",
                           "agent": agent})
                time.sleep(delay)
                delay = min(delay * 2, 300.0)
        if turn.reasoning.strip():
            self._log({"role": "thinking", "text": turn.reasoning.strip()[:4000], "agent": agent})
        if turn.text.strip():
            self._log({"role": "assistant", "text": turn.text.strip(), "agent": agent})
        if agent == "main":
            usage = read_state(self.id, self.store).get("usage") or {}
            for k, v in (turn.usage or {}).items():
                if isinstance(v, (int, float)):
                    usage[k] = usage.get(k, 0) + v
            write_state(self.id, self.store, usage=usage, calls=self.calls)
        return turn

    def _ensure_task(self) -> str:
        """One task for the whole session, so every step builds on the last (option mode would otherwise put
        each implicit task in its own design option, branched from the base without the earlier work)."""
        status = self.tool_fn("task.status", {})
        task = ((status.get("result") or {}).get("task") or {}) if status.get("ok") else {}
        if task.get("status") == "open" and task.get("client") == self.client_name:
            return f"{task.get('id')} ({task.get('mode')} mode)"
        title = self.store.get(self.id).title or "Studio session"
        started = self.tool_fn("task.start", {"title": f"Studio: {title}"[:80], "mode": "direct"})
        if not started.get("ok"):
            self._log({"role": "status", "text": "Could not open the session's task: "
                                                 + str((started.get("error") or {}).get("message", ""))})
            return ""
        task = started.get("result") or {}
        if task.get("mode") == "option":
            self._log({"role": "status", "text": f"The project keeps agent changes in a design option "
                                                 f"({task.get('option')}): switch to it in the app to watch the work, "
                                                 "or set Project settings › Agent changes to “agent decides”."})
        write_state(self.id, self.store, task=task.get("id", ""), task_mode=task.get("mode", ""))
        return f"{task.get('id')} ({task.get('mode')} mode)"

    def _opening(self, brief: str) -> str:
        parts = []
        if getattr(self, "_task", ""):
            parts.append(f"Session task: {self._task}.")
        plan, notes, summary = (read_file(self.id, n, self.store) for n in (PLAN, NOTES, SUMMARY))
        if plan or notes or summary:
            parts.append("You are resuming this session. Your plan, notes and the last summary follow; re-read the "
                         "project before changing it, because the architect may have edited it meanwhile.")
            if summary:
                parts.append("Summary so far:\n" + summary)
            if plan:
                parts.append("Plan:\n" + plan)
            if notes:
                parts.append("Recent notes:\n" + notes[-6000:])
        if brief:
            parts.append("The brief:\n" + brief)
        if not parts:
            parts.append("Read the project and ask the architect what to design.")
        return "\n\n".join(parts)

    def _compact(self, provider, brief: str) -> None:
        provider.add_user("The conversation is getting long. Write a summary for yourself to continue from: what is "
                          "built (levels, main elements, drawings, sheets), decisions and assumptions, what the "
                          "architect asked for, open questions, and the next steps. Do not call tools.")
        turn = self._step(provider)
        summary = turn.text.strip()
        (self.dir / SUMMARY).write_text(summary, encoding="utf-8")
        self._log({"role": "status", "text": "Context summarised"})
        provider.reset(self._opening(brief))

    def run(self, brief: str = "") -> str:
        self._state("starting", pid=os.getpid(), provider=self.provider_name, model=self.model, effort=self.effort,
                    project=self.project, started=_now(), brief=brief[:4000])
        tools = self.schemas + STUDIO_TOOLS
        try:
            provider = self.provider_factory(SYSTEM, tools, self.effort)
        except ProviderError as ex:
            self._state("failed", error=ex.message)
            self._log({"role": "status", "text": f"Could not start: {ex.message}"})
            return "failed"
        self._log({"role": "status", "text": f"Studio agent started ({provider.name} {getattr(provider, 'model', '')})"})
        self._state("working")
        if self.project:  # tests without a project have no task protocol
            try:
                self._task = self._ensure_task()
            except Exception as ex:  # noqa: BLE001 (the agent can still read; writes start implicit tasks)
                self._log({"role": "status", "text": f"Could not open the session's task: {ex}"})
        provider.add_user(self._opening(brief))
        pending: list[tuple] | None = None
        stalled, seen = 0, set()
        final = "stopped"
        try:
            while True:
                texts = self._messages(block=pending is None and self._idle)
                note = "\n\n".join(texts)
                if pending is not None:
                    provider.add_results(pending, note)
                    pending = None
                elif note:
                    provider.add_user(note)
                self._state("working")
                if provider.name != "anthropic" and provider.size() > COMPACT_CHARS:
                    self._compact(provider, brief)
                try:
                    turn = self._step(provider)
                except ProviderError as ex:
                    if self.exit_when_done:
                        raise
                    self._log({"role": "status", "text": f"The provider failed: {ex.message}. Fix it (a new key in "
                                                         "Preferences › Assistant) and send a message to go on."})
                    self._state("waiting", error=ex.message)
                    self._idle = True
                    pending = None
                    # the next message starts a fresh provider (it reads the key again) from plan, notes and brief
                    texts = self._messages(block=True)
                    try:
                        provider = self.provider_factory(SYSTEM, tools, self.effort)
                    except ProviderError as again:
                        self._log({"role": "status", "text": f"Still failing: {again.message}"})
                        continue
                    provider.add_user(self._opening(brief))
                    with self._lock:
                        self._helper_reports[:0] = texts
                    self._idle = False
                    continue
                if not turn.calls:
                    self._idle = True
                    if self.exit_when_done:
                        final = "done"
                        break
                    continue
                self._idle = False
                signatures = [c.name + json.dumps(c.args, sort_keys=True, default=str) for c in turn.calls]
                stalled = stalled + 1 if all(s in seen for s in signatures) else 0
                seen.update(signatures)
                pending = self._run_calls(turn.calls)
                if stalled >= 3:
                    stalled = 0
                    with self._lock:
                        self._helper_reports.append("Runner: you have repeated the same calls three times. Stop, "
                                                    "re-read the project, and take another approach or ask.")
        except Stopped:
            final = "stopped"
        except KeyboardInterrupt:
            final = "stopped"
        except Exception as ex:  # noqa: BLE001
            message = ex.message if isinstance(ex, ProviderError) else f"{type(ex).__name__}: {ex}"
            self._log({"role": "status", "text": f"The runner failed: {message}"})
            self._state("failed", error=message)
            self._stop.set()
            self._helpers.shutdown(wait=False, cancel_futures=True)
            return "failed"
        self._stop.set()
        self._helpers.shutdown(wait=False, cancel_futures=True)
        self._state(final)
        self._log({"role": "status", "text": "Studio agent " + ("finished" if final == "done" else "stopped")})
        return final

    _idle = False
    _task = ""


# ---------------------------------------------------------------- starting a runner

def _app_preferences() -> dict:
    """The app's Assistant preferences (provider, model, base URL), so the CLI uses what the app uses. Qt keeps
    them in its config folder (<LOCALAPPDATA>/NicBim/NicBim on Windows); KIMBIM_PREFERENCES overrides."""
    candidates = []
    if os.environ.get("KIMBIM_PREFERENCES"):
        candidates.append(pathlib.Path(os.environ["KIMBIM_PREFERENCES"]))
    try:
        from .. import documents as D
        base = pathlib.Path(D.data_dir())
        candidates += [base / "NicBim" / "preferences.json", base / "preferences.json"]
    except (ImportError, AttributeError):
        pass
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        candidates.append(pathlib.Path(os.environ["LOCALAPPDATA"]) / "NicBim" / "NicBim" / "preferences.json")
    else:
        candidates.append(pathlib.Path.home() / ".config" / "NicBim" / "NicBim" / "preferences.json")
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            return {k: str(data.get(f"assistant_{k}") or "") for k in ("provider", "model", "base_url")}
    return {}


def start(project: str, brief: str = "", *, title: str = "", session_id: str = "", provider: str = "",
          model: str = "", effort: str = "high", base_url: str = "", foreground: bool = False,
          exit_when_done: bool = False, store: sessions.Store | None = None) -> dict:
    """Create (or reuse) a stored session and run its studio agent, detached unless `foreground`."""
    store = store or _store()
    prefs = _app_preferences()
    provider = provider or prefs.get("provider") or "anthropic"
    if not model and provider == prefs.get("provider"):
        model = prefs.get("model", "")
    if not base_url and provider == prefs.get("provider"):
        base_url = prefs.get("base_url", "")
    if session_id:
        record = store.get(session_id)
        project = project or record.project
        current = status(session_id, store)
        if current.get("state") in LIVE_STATES:
            raise catalogue.AgentError("bad_input", hint=f"session {session_id} is already running "
                                                         f"(pid {current.get('pid')})")
    else:
        record = store.create(project, title or (brief.splitlines()[0][:60] if brief else "Studio session"),
                              provider=provider, model=model)
    if brief and not session_id:
        store.append(record.id, {"role": "user", "text": brief, "source": "brief"})
    options = {"provider": provider, "model": model, "effort": effort, "base_url": base_url,
               "exit_when_done": exit_when_done}
    write_state(record.id, store, state="starting", project=os.path.abspath(project), **options,
                brief=brief[:4000])
    if foreground:
        result = Runner(record.id, project, provider=provider, model=model, effort=effort, base_url=base_url,
                        store=store, exit_when_done=exit_when_done).run(brief)
        return {"session": record.id, "state": result}
    from . import client
    log = session_dir(record.id, store) / LOG
    brief_file = session_dir(record.id, store) / "brief.md"
    brief_file.write_text(brief, encoding="utf-8")
    cmd = [client._python_exe(), "-m", "kimbim.agent.studio", "run", "--session", record.id, "--project",
           os.path.abspath(project), "--provider", provider, "--model", model, "--effort", effort,
           "--base-url", base_url, "--brief-file", str(brief_file)]
    if exit_when_done:
        cmd.append("--exit-when-done")
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    with open(log, "ab") as out:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                close_fds=True, env=client._env(), **kwargs)
    write_state(record.id, store, pid=proc.pid)
    return {"session": record.id, "state": "starting", "pid": proc.pid, "log": str(log)}


def resume(session_id: str, foreground: bool = False, store: sessions.Store | None = None) -> dict:
    """Start a stopped session's runner again; it continues from its plan, notes and summary."""
    store = store or _store()
    state = read_state(session_id, store)
    return start(state.get("project") or store.get(session_id).project, read_file(session_id, "brief.md", store)
                 or state.get("brief", ""), session_id=session_id,
                 provider=state.get("provider", ""), model=state.get("model", ""),
                 effort=state.get("effort", "high"), base_url=state.get("base_url", ""), foreground=foreground,
                 store=store)


def feed(session_id: str, since: int = 0, store: sessions.Store | None = None) -> dict:
    """Transcript entries after index `since` and the runner's state (for the app's panel and `log --follow`)."""
    store = store or _store()
    entries = store.transcript(session_id, limit=0)
    return {"entries": entries[since:], "next": len(entries), "state": status(session_id, store)}


def running(project: str = "", store: sessions.Store | None = None) -> list[dict]:
    store = store or _store()
    out = []
    for record in store.all(project, include_archived=False):
        state = status(record.id, store)
        if not state:
            continue
        out.append({"session": record.id, "title": record.title, "project": record.project,
                    "state": state.get("state", ""), "provider": state.get("provider", ""),
                    "model": state.get("model", ""), "updated": state.get("updated", ""),
                    "calls": state.get("calls", 0)})
    return out


# ---------------------------------------------------------------- app bridge (the Assistant panel's Studio mode)

def _dump(data) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def ui_list(project: str = "") -> str:
    try:
        return _dump({"ok": True, "result": {"sessions": running(project)}})
    except Exception as ex:  # noqa: BLE001
        return _dump({"ok": False, "error": {"code": "bridge_error", "message": str(ex)}})


def ui_feed(session_id: str, since: int = 0) -> str:
    try:
        return _dump({"ok": True, "result": feed(session_id, int(since or 0))})
    except catalogue.AgentError as ex:
        return _dump(ex.envelope())
    except Exception as ex:  # noqa: BLE001
        return _dump({"ok": False, "error": {"code": "bridge_error", "message": str(ex)}})


def ui_send(session_id: str, kind: str, text: str = "") -> str:
    try:
        return _dump({"ok": True, "result": send(session_id, kind, text, source="app")})
    except catalogue.AgentError as ex:
        return _dump(ex.envelope())
    except Exception as ex:  # noqa: BLE001
        return _dump({"ok": False, "error": {"code": "bridge_error", "message": str(ex)}})


def ui_start(project: str, brief: str, effort: str = "high") -> str:
    try:
        return _dump({"ok": True, "result": start(project, brief, effort=effort)})
    except catalogue.AgentError as ex:
        return _dump(ex.envelope())
    except Exception as ex:  # noqa: BLE001
        return _dump({"ok": False, "error": {"code": "bridge_error", "message": str(ex)}})


def ui_resume(session_id: str) -> str:
    try:
        return _dump({"ok": True, "result": resume(session_id)})
    except catalogue.AgentError as ex:
        return _dump(ex.envelope())
    except Exception as ex:  # noqa: BLE001
        return _dump({"ok": False, "error": {"code": "bridge_error", "message": str(ex)}})


# ---------------------------------------------------------------- the detached runner's entry point

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="kimbim.agent.studio")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--session", required=True)
    r.add_argument("--project", required=True)
    r.add_argument("--provider", default="")
    r.add_argument("--model", default="")
    r.add_argument("--effort", default="high")
    r.add_argument("--base-url", default="")
    r.add_argument("--brief-file", default="")
    r.add_argument("--exit-when-done", action="store_true")
    ns = p.parse_args(argv)
    brief = pathlib.Path(ns.brief_file).read_text(encoding="utf-8") if ns.brief_file else ""
    result = Runner(ns.session, ns.project, provider=ns.provider, model=ns.model, effort=ns.effort,
                    base_url=ns.base_url, exit_when_done=ns.exit_when_done).run(brief)
    return 0 if result in ("done", "stopped") else 1


if __name__ == "__main__":
    sys.exit(main())
