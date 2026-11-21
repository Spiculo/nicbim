<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# 23 — Studio session playbook: an architect and the agent build a project together

How to run a design-and-build session where the architect works in NicBim and a **studio agent** (D252) works
in the same model at the same time: deciding the design, making a geolocated IFC from scratch, drawing, laying out
sheets and delivering. The five benchmark briefs are in [briefs/](briefs/).

## Before the session (once)

1. **A model provider key.** Preferences › Assistant: provider (Anthropic or OpenAI-compatible), model and key.
   The studio agent uses the same settings; `kimbim studio start --provider/--model` overrides them. For
   Anthropic the default model is `claude-opus-5-5` with adaptive reasoning. Check the key works: a 401
   `expired_secret_key` in the agent's feed means the key must be replaced.
2. The app is built (`pixi run app-build`) so sheet PDFs can be rendered.

## 1. Create the project on the map

```sh
kimbim project new "C:/Proyectos/Casa Parque Rodo" --name "Casa Parque Rodó" --number 2026-001 \
  --client-name "Familia Pérez" --address "Br. España 2200" --town Montevideo --country Uruguay \
  --lat -34.9145 --lon -56.1640 --elevation 22 --north 18 --crs EPSG:5382 \
  --level "Planta baja=0" --level "Planta alta=3" --level "Azotea=6"
```

This makes a versioned folder project with site, building and levels, georeferenced (IfcSite reference, map
conversion to SIRGAS-ROU98 / UTM 21S, true north) and with `agent_changes = agent_decides`, so the agent works in
the model and the architect sees every change at once. (`--agent-changes option` keeps the agent's work in a design
option to review instead.)

Open the folder in NicBim (File › Open folder). The app starts its live agent session ("Agent: live" in the status
bar).

## 2. Start the agent

From the app: **View › Panels › Studio**, paste the brief, choose the effort, press **Start**.
From a terminal:

```sh
cd "C:/Proyectos/Casa Parque Rodo"
kimbim studio start @<nicbim>/docs/briefs/01-casa-urbana.md   # prints the session id
kimbim studio log <id> -f                                 # watch it work
```

The agent reads the project, writes a plan (phases with checkable steps), and starts building. Every write is one
undo step in the app; the views redraw as it goes. It opens **one task** for the whole session and saves a version
at the end of each phase.

## 3. Work in parallel and steer

- **Say something** (it reads it before its next step, without stopping):
  `kimbim studio say <id> "Make the patio window 5 m wide and keep the kitchen island centred"` — or type in the
  Studio panel and press Send.
- **Give it a small task** that a helper does in parallel while the main agent carries on:
  `kimbim studio task <id> "Add door and window tags on both plans"` — or tick "As a small task".
- **Answer its questions**: questions appear highlighted in the feed (`QUESTION:` in the log); reply with `say`.
  Meanwhile it continues with a sensible default (Archicad's, else Revit's) and notes the assumption.
- **Pause / resume / stop**: `kimbim studio pause|resume|stop <id>` or the panel's buttons. A stopped agent
  restarts with `kimbim studio resume <id>` and continues from its plan, notes and last summary.
- **See its plan and notes**: `kimbim studio status <id>`.
- The architect keeps modelling meanwhile. The agent re-reads before editing and builds around the architect's
  work; Ctrl+Z undoes any step, the agent's included.

The agent splits independent work across **helpers** (`studio_spawn`): for example one per floor's interiors, one
for the sheets, one for schedules. Each has its own scope; their reports come back to the main agent.

## 4. Drawings, sheets and delivery

Typical requests, in the order a session reaches them:

1. "Create the plans at 1:50 with rooms and areas, a section through the stair and the street and patio
   elevations." (drawings.create, create.room, annotation.*)
2. "Lay out three A1 sheets: plans; sections and elevations; schedules and a 3D view." (sheets.*)
3. "Check the model and fix what it finds." (checks.run)
4. "Save a version and make the delivery package for the client." → `deliver.package`: the drawing set as one
   PDF and per sheet, DXF sheets, the geolocated IFC, schedules as CSV and a transmittal, zipped.

The same package from a terminal at any time: `kimbim deliver package --out "C:/Entregas/2026-001"`.

## 5. The design change (every brief has one)

Ask for the change in one message (the brief names it). The agent edits the model; the plans, sections,
schedules and sheets follow because they are views of the model; then ask for a new delivery package and compare
the transmittals.

## Limits to know

- A `.nic` project or a plain IFC works too, but the folder is best: versions, worktrees and the agent's helpers
  are fastest there.
- Two studio agents on the same model at once share it through the app's queue; give them separate scopes.
- Stairs with many risers take tens of seconds to build; the feed shows the call running.
- Deleting a project folder while its background worker runs and creating a new one at the same path can serve
  the old model until the worker exits (stop it with `kimbim studio stop` or close the app); use a new path.
