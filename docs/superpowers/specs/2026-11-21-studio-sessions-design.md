<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Studio sessions: an architect and an agent build a project together

Status: approved by the owner's `/goal` (2026-11-21). Decisions D252–D256.

## Intent

The owner wants NicBim ready for a **deep design-and-build session with an architect**, using the five Uruguayan
benchmark projects (casa urbana, vivienda colectiva, escuela, bodega, local comercial + oficinas). In one session they
decide the design, make a **geolocated IFC from scratch**, make the **drawings and sheets**, and **deliver** the
project. The audience is architects and students who would otherwise use Archicad, so the output has to look
professional and the tools have to work.

The work is parallel: an agent **runs on its own** (long sessions, reasoning, tools, helpers it spawns) while the
architect works in the app and **sees every agent change at once**; both the CLI and the app can **steer** the agent
or hand it small tasks without stopping it.

## Goals

1. **Studio agent runtime** (D252): a long-running agent process per session, prompted from the CLI or the app,
   with extended reasoning, the full tool catalogue, a written plan and notes that survive restarts, helper
   subagents running in parallel, and an inbox the architect writes to at any time.
2. **Project from scratch, geolocated** (D253): create a project with site, building and levels; place it on the
   map from latitude/longitude (projected CRS computed, IfcSite reference set, true north); set the title-block
   project info. Available to the agent and the CLI.
3. **Delivery package** (D254): one call produces the deliverable folder: the sheet set as one PDF, the IFC, the
   schedules, DXF drawings, and a transmittal listing what is in it and which version it describes.
4. **Drawings that look right** (D255): curved objects draw their silhouette, not their facets; library objects
   may carry front/side views for elevations and sections; level marks stay clear of the building.
5. **A library that covers the five projects** (D256, owner chose option C): parametric objects for everything
   architects draw and schedule, new shape kinds (rounded box, ellipsoid, loft), CC0 meshes only for entourage
   with drawn symbols.

## Non-goals

- A remote or multi-machine agent service (doc 18 "Remote" stays future).
- Agents driving the GUI. They keep using operations (doc 18 §2 principle).
- Replicating the real reference buildings (Garzón School, Bodega Garzón...): the projects are *inspired by* them.

## Anti-goals

- An agent that silently rewrites the architect's work: every write is still one undo step on the live host and
  every session's changes are reviewable (direct mode makes a way back at start, option mode a design option).
- A session that dies with its terminal or a usage limit and loses its place.
- Steering that has to wait until the agent finishes.

## Approaches considered (D252)

| Approach | Trade-off | Verdict |
|---|---|---|
| A. Extend the in-app Assistant turn (panel thread) | Instant, but the agent lives and dies with one chat turn in the app; no CLI start; long runs block the panel | Rejected |
| B. **A studio runner process per session** that calls tools through the existing client (live host when the app has the project open, worker otherwise); inbox/outbox files in the session store; the app's panel and the CLI read and write them | Reuses D102 live host and D111 sessions; survives app restarts; one code path for CLI and UI | **Chosen** |
| C. Delegate to an external coding agent (Claude Code/opencode) over MCP | Already possible (doc 17), but not steerable from the app and needs a coding agent installed | Kept as an alternative, documented |

## Design

### D252 Studio runtime

- `kimbim.agent.studio` runs the loop; `kimbim.agent.providers` holds two adapters with one interface
  (`step(history, tools) -> Turn{text, calls, reasoning}`): **Anthropic** (official SDK, adaptive thinking with an
  effort, streaming, prompt caching, server-side compaction) and **OpenAI-compatible** (the Responses API with
  reasoning effort, falling back to Chat Completions; the existing raw-HTTP code path and the architect's stored
  key). Provider, model, base URL and effort come from the app's Assistant preferences unless given.
- **Session files** (in the D111 store, `<data>/agent/sessions/<id>/`): `studio.json` (runner pid, state
  `starting|working|waiting|paused|stopped|failed|done`, provider/model, brief, counters), `inbox.jsonl` (what the
  architect sends: `say`, `task`, `pause`, `resume`, `stop`), `plan.md` and `notes.md` (the agent's own, kept across
  restarts), and the existing `transcript.jsonl` (everything shown to the architect).
- **Loop.** Before every model call the runner drains the inbox: messages become an `Architect:` user block
  (appended next to tool results, so steering lands mid-run); `task` items run as a helper subagent so the main
  agent is not interrupted; `pause` waits, `stop` ends cleanly. When the model ends a turn without calls the
  runner marks the session `waiting` and blocks on the inbox; it never exits on its own unless `--exit-when-done`.
- **Studio tools** (only for studio agents, beside the catalogue): `studio_plan_read`, `studio_plan_write`,
  `studio_note` (progress and decisions), `studio_spawn` (a helper with its own brief and effort; several spawns in
  one round run in parallel threads; each returns its final report; helpers can't spawn further, cap 4 at once),
  `studio_ask` (posts a question to the architect without stopping; answers arrive through the inbox).
- **Context.** Anthropic: server-side compaction; OpenAI: when the history passes a threshold the runner asks the
  model for a summary and restarts from plan + notes + summary. Resume after a crash rebuilds from plan, notes and
  the last summary.
- **Live feedback.** Tool calls go through `client.request`, which finds the app's live host when the project is
  open, so each write is an undo step the architect sees immediately. Studio sessions default to **direct** mode
  when the project lets the agent decide (`agent_changes`), otherwise option mode as today.
- **CLI.** `kimbim studio start|say|task|pause|resume|stop|status|log|list`. `start` detaches by default
  (`--foreground` to stay attached); `log --follow` streams the transcript.
- **App.** The Assistant panel gets a *Studio* switch: pick a running session, see its feed live, send messages or
  small tasks, pause/stop, start a new one from a brief. Bridge functions `studio.ui_*` serve the panel.

### D253 Project from scratch, geolocated

- `kimbim project new <path> --name --schema IFC4X3|IFC4 [--lat --lon --elevation --true-north --crs]` creates a
  versioned folder project (or `.nic`) with project, site, building and Level 0.
- Agent tools `site.get`, `site.locate` (lat/lon/elevation/true north/address → IfcSite reference, map conversion
  with eastings/northings in a projected CRS: UTM zone from longitude by default, `crs` to choose, e.g. EPSG:5382
  SIRGAS-ROU98 / UTM 21S for Uruguay; own transverse-Mercator maths, no new dependency), and `project.set_info`
  (number, name, client, address, author for title blocks).

### D254 Delivery package

`deliver.package` (tool and CLI): sheets → one combined PDF plus per-sheet PDFs, IFC export (current version,
geolocated), schedules → CSV, drawings → DXF, `transmittal.md`/`.json` with version id, state hash, date, contents
and open issues; optional zip. Refuses with a clear message when there are no sheets.

### D255 Drawings

- Smooth parts (cylinders, cones, revolves, ellipsoids, sweeps of tubes) draw silhouettes in hidden-line views:
  edges between faces whose normals differ by less than a threshold are dropped (facet stripes gone).
- `views` in `.nicobj` (front/side 2D, like `symbol`) used for elevations/sections when the object is beyond the cut
  and the project setting `object_views` is `drawn` (default `drawn` when the object has views).
- Level marks are placed outside the building's extent.

### D256 Library (option C)

New shapes `rounded_box`, `ellipsoid`, `loft`; about 150 objects grouped by the five briefs; CC0 entourage meshes
with drawn plan/elevation symbols, recorded in THIRD_PARTY.md; per-object picture checks (plan, section, elevation,
3D) in the test suite. Built in waves after D252–D255.

## Left to the builder

Thresholds (facet angle, compaction size), exact UI layout of the Studio switch, the object list per wave.

## Verification

Unit tests with a scripted fake provider (inbox, pause/stop, spawn in parallel, resume from plan/notes); CLI tests;
app self-test for the Studio panel; an end-to-end rehearsal that builds the casa urbana from a brief through the
CLI tools, geolocated in Montevideo, with sheets and a delivery package.
