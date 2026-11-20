# 22 — Moonshot roadmap: towers, habitats, people and a design partner

Status: **Proposed** (2026-11-19). An intentionally over-ambitious plan; the horizons are an order of work, not
dates. It extends [07](07-roadmap.md) (what is built) and [08](08-future.md) (collaboration). Each track names what
already exists so new work builds on it instead of beside it.

## North star

**NicBim designs, tests and explains any habitable system, from a cabin to a 150-storey tower to a sealed habitat
on the Moon, with an agent that works as a real design partner: it understands the brief, the building, the people
who will use it and the physics around it, and it can help with any task in the project.**

Three ideas make this NicBim's and not anyone else's:

1. **Design options are real branches.** An agent can open a hundred variants, evaluate each one, and leave the
   architect a reviewed shortlist to compare and combine. No other BIM tool has merge-capable object history.
2. **Model states hash the same everywhere** ([02](02-data-model-and-format.md#determinism)). A simulation result
   keyed by state hash is never computed twice, can be shared through NicGit, and proves which model it describes.
3. **Evidence over inference** ([00](00-vision-and-scope.md) principle 6). Engines are the authority; the agent
   proposes, explains and orchestrates. Every claim the agent makes about performance points at an engine result.

## Principles kept (and their anti-goals)

| Kept | The failure it prevents |
|------|------------------------|
| Local-first; cloud compute only opt-in | A tower project that cannot open on a plane |
| IFC stays the schema; new data goes in IFC entities or versioned project settings | A private format that only NicBim reads |
| The agent never accepts its own work; changes land in a design option | An AI that silently rewrites a building |
| Simulation results carry their method, inputs, limits and state hash | A heat map presented as a certified permit |
| Every feature reachable from the agent catalogue, the CLI and the UI ([18](18-agent-tools-and-sessions.md)) | Features only a mouse can reach |
| Codes and presets are editable data (D93), never hard-coded | A tool that only works in one country |

## Horizons

| Horizon | Theme | Exit test (the "demo that proves it") |
|---------|-------|---------------------------------------|
| **H1 Foundations** | Scale, simulation jobs, people as data, a sharper agent | A 60-storey residential tower (≈1M objects) opens in < 20 s, orbits at 60 fps, and the agent writes a cited egress and lift report for it |
| **H2 Tall and smart** | Tower design kit, human flow simulation, generative options | From a one-page brief, the agent produces 30 tower options as branches, evaluates structure, lifts, egress, daylight, carbon and cost, and presents a Pareto shortlist the architect combines in an afternoon |
| **H3 Living systems** | Habitable-system modelling, dynamic physics, digital twin | A building runs for a simulated year with occupants, weather, energy, water and air in the loop; predicted vs metered data is compared once it is built |
| **H4 Off-world and city-scale** | Sealed habitats, urban federation, autonomous design studios | A closed-loop lunar habitat for 12 crew passes mass, life-support, radiation, pressure and habitability checks; the same engine plans a 40-block district |

---

## Track A — Scale: from houses to supertall

Today: Rust decomposer, `pixi run bench-100k` as the release gate, models placed on levels (D58), linked models (D117, D140),
float32 precision issues at map coordinates (open follow-up).

- **10M-object target.** Out-of-core records with an LRU working set; the viewer streams tiles by level and zone
  with LOD and GPU instancing for repeated types (a tower has ~40 unique floors and thousands of repeats).
- **Partial checkout.** Open "levels 40–55 and the core" only; sparse Git checkout by zone, level or discipline,
  so the façade team never loads the plumbing.
- **Typical floors done properly.** A typical floor is a model placed on N levels (D58) with **per-level
  overrides** stored as deltas (a column that shrinks every 10 floors, a refuge floor that breaks the pattern).
- **Double-precision placement**, local shifts per tile, and true georeference (fixes the float32 follow-up).
- **Zone locks and parallel editing** for teams of 50: lock by zone/level/discipline, merge by records (D128).
- **Benchmarks as gates:** `bench-1m`, `bench-10m`, time-to-first-pixel, edit latency on a 100-storey model.

## Track B — The tall building kit

Today: frame solver (D247: 560 members in 3.8 s), sections, MEP sizing, curtain walls, sequencing, stairs.

- **Massing to tower in one move.** Floor-plate generator (shape, taper, twist, setbacks), core generator sized
  from lift traffic and egress, live efficiency (net-to-gross, core ratio, lease depth) in the status strip.
- **Lateral systems.** Core + outriggers, belt trusses, tube, diagrid, mega-columns as parametric systems that
  generate members, not drawings.
- **Structural depth.** Shell/plate FE for cores and slabs; modal analysis, response spectrum (seismic), wind
  loads from code profiles and from simulated pressure (Track E); P-delta, drift and acceleration checks
  (occupant comfort in sway). Optional bridges to OpenSees / Code_Aster for second opinions.
- **Vertical transportation.** Lift banks, zoning, sky lobbies, double-deck cars; traffic analysis (up-peak,
  lunch, down-peak; destination dispatch) driven by the population model in Track C. Lift count and core size
  fall out of the analysis instead of rules of thumb.
- **Façade engineering.** Unitized panel rationalisation (how many unique panels?), mullion structural checks,
  solar gain per panel, bird-safe and glare checks, panel schedules for fabrication.
- **Life safety for tall.** Pressurised stairs, refuge floors, fire-fighting lifts, phased evacuation, smoke
  zones; checked as data rules (Track F code engine), simulated in Track C/E.
- **Stack effect and wind at height** for MEP and doors; vertical MEP risers and plant floors.
- **Construction of a tower.** Jump-form core cycle, crane reach/lift plans, floor cycle time, 4D sequence from
  `sequencing.py`, logistics per floor.

## Track C — People: understanding human flow

Today: rooms, doors, stairs, walkthrough cameras (D249), occupancy only as HVAC load figures. This track is new.

- **Navigation graph from the model.** Rooms, doors, stairs, ramps, lifts and their widths become a walkable
  graph plus a navigation mesh, rebuilt incrementally on every edit (cached by state hash).
- **Population model.** Occupant profiles (office worker, resident, child, elderly, wheelchair user, visitor,
  night-shift nurse) with schedules: who is where at 08:45 on a Tuesday. Stored as project settings, editable.
- **Pedestrian simulation.** Agent-based (social-force / velocity-obstacle) movement with doors, queues, lifts
  and stairs; heat maps of density, level-of-service, dwell time and conflicts, drawn on plans and in 3D.
- **Egress.** Code travel distances and exit widths as checks; time-based evacuation (RSET) vs tenability
  (ASET, from Track E smoke); phased and lift-assisted evacuation for towers.
- **Space syntax.** Visibility graphs, integration, connectivity and axial maps: which corridors become streets,
  which rooms are hidden. A "wayfinding score" for a plan.
- **Accessibility as lived experience.** Wheelchair routes with turning circles, reach ranges, step-free paths,
  door forces; the agent walks a persona through the building and reports where they get stuck.
- **"A day in the building".** A walkthrough (D249) rendered with simulated people following their schedules;
  the agent narrates the day for a chosen persona with snapshots.
- **Flow-driven design.** Corridor widths, lobby sizes, lift numbers and stair positions proposed from the
  simulated flow, as design options.

## Track D — Habitable systems

Buildings as **systems that keep people alive and well**, from net-zero homes to sealed habitats.

- **System model.** A versioned graph of stocks and flows (energy, water, air, heat, food, waste, materials,
  carbon, money) attached to IFC systems (D242 MEP core) and spaces. Runs hourly over a year (Track E) or as a
  steady-state balance for early design.
- **Wellbeing metrics.** Daylight autonomy, circadian light, views to sky and nature, acoustic privacy, thermal
  comfort per occupant (PMV/PPD, adaptive), air quality (CO₂ from the population model), crowding. Shown per room
  and per persona.
- **Carbon and circularity.** Embodied carbon (EN 15978 stages) from materials (D96) and quantities, operational
  carbon from Track E, material passports and reuse at end of life; carbon as a first-class option metric.
- **Resilience.** Flood, heat-wave, earthquake, wildfire and grid-outage scenarios: does the building stay
  habitable for 72 hours? Passive survivability as a check.
- **Extreme habitats.** Pressure-vessel shells, radiation shielding (regolith/water thickness vs dose),
  life-support mass balance (ECLSS: O₂, CO₂ scrubbing, water recovery, food production area), crew volume and
  privacy standards, psychological habitability (windows, colour, personal space, circadian lighting), redundancy
  and failure-mode checks. Same engines, different presets: Antarctic station, submarine, Mars base, lunar base.
- **District and city.** Microgrids, district heating, water reuse between buildings, urban heat island, shared
  mobility; many projects federated (Track H).

## Track E — Simulation engine

Today: steady-state energy and daylight (D222), sun shadows (D96/D198), frame analysis (D247), MEP sizing.

- **Simulation jobs.** One job model for every engine: inputs (model state hash + settings + weather), runner
  (local process, local GPU, or opt-in NicGit runners), results stored beside the version and reused by hash.
  Results show in Compare (D56) like geometry changes.
- **Engines through bridges, not rewrites** (D06): EnergyPlus/OpenStudio (dynamic energy), Radiance (daylight
  and glare), OpenFOAM (wind comfort, natural ventilation, wind pressure for Track B), FDS (fire and smoke for
  ASET), acoustic ray tracing, our own pedestrian engine (Track C), structural FE (Track B).
- **Model-to-analysis translators** that build clean analytical models (zones, surfaces, meshes) from IFC,
  with the agent explaining what it simplified.
- **Climate futures.** Run any job against present and 2050/2080 weather files.
- **Surrogate models.** Fast learned approximations trained locally on the project's own job results, so
  generative search (Track F) can screen thousands of options before running the real engines on the finalists.
  Surrogates are labelled as estimates; finalists always get the real engine.

## Track F — The agent as a design partner

Today: 257 tools, tasks and options, snapshots, sessions, MCP; the assistant's default model id is stale
(`claude-sonnet-4-5` in `agent/assistant.py`), which H1 updates to a current model.

**Understanding**
- **Brief to programme.** Read a brief (text, PDF, spreadsheet, a client email) into a room programme with
  areas, adjacencies, constraints and priorities, kept as versioned project data and traced back to its source.
- **Spatial perception.** A semantic scene graph (what touches what, what sees what, who walks where) the agent
  queries instead of guessing; plan reading (raster/PDF to model), sketch-to-model from a photo of a napkin
  sketch, point cloud to model (`pointcloud.py`).
- **Design intent memory.** Why a decision was made is stored with the elements and the version ("column moved
  for the lobby view, D-client 2027-03"), so the agent can explain history and avoid undoing intent.

**Designing**
- **Generative options.** The agent opens many branches, generates layouts, massings or systems, evaluates them
  through Track E jobs and Track C flow, and presents a Pareto front (cost, carbon, daylight, efficiency, flow,
  structure) in a Compare board. The architect picks and combines (D128 merges).
- **Layout solver.** Adjacency graphs, constraint solving and code rules produce plan options that respect the
  structure grid, cores and shafts.
- **Code engine.** Building codes as editable, machine-checkable rules (IDS + rule expressions from
  `objexpr.py`) with clause citations; the agent answers "why does this fail?" with the clause and a fix as an
  option. Region packs ship as presets (D93).
- **Specialist agents.** Structure, MEP, façade, cost, code, flow and sustainability agents each work on their own
  branch; conflicts surface as real merge conflicts the lead agent and the architect resolve.

**Helping with any task**
- Fee proposals, programmes, meeting minutes from BCF issues, specifications from the model, permit packages,
  client presentations and walkthrough videos, emails in the client's language, quantity-based cost plans.
- Office learning: the agent studies the office's past projects (locally) to learn pen sets, details, typical
  wall types and naming, and proposes them as office presets.
- Voice and pen input; the agent beside you in VR when hardware exists ([20](20-vr-feasibility.md)).

**Trust**
- Every performance claim links to an engine result and its limits; unsupported claims are refused, not
  improvised. Changes stay in options with a diff and attribution. Local and company models are first-class
  (execution policy from [08](08-future.md#ai-assistance)); cost and token budgets are visible per task.

## Track G — Outside the box

- **The building over time.** A 4D life-cycle twin: ageing, maintenance, replacements, renovations and climate
  futures over 60 years, with cost and carbon over the life, not just at handover.
- **Persona stories.** "Follow Ana, 78, from the bus stop to her flat on level 23 during a lift outage." The agent
  simulates and narrates it with snapshots and flags the design changes that would help her.
- **Adaptive architecture.** Kinetic façades, movable partitions and day/night configurations modelled as states
  of an element, with simulations per state.
- **Fabrication-ready.** Volumetric modular towers (DfMA kit of parts), CNC/robotic toolpaths, 3D-printed concrete
  paths, panel nesting; the model is the factory input.
- **Open building commons.** Through NicGit: fork an open-source school or clinic design, adapt it to a site, and
  contribute improvements back, with history intact.
- **Post-occupancy loop.** Sensors and meters feed the digital twin; predicted vs real is compared per version,
  and the surrogate models (Track E) learn from reality.
- **Design by negotiation.** Stakeholder agents (client budget, neighbours' light, city planning, accessibility
  advocate) argue on branches; the architect sees the trade-offs instead of guessing them.

## Track H — Platform

- Plugin SDK with stable, versioned tool/engine/job interfaces; plugins can add engines, rules, personas and
  object families, and they appear in the agent catalogue automatically.
- City-scale federation: many projects referenced by placement (links today), shared site and context models.
- Compute: local GPU first, opt-in runners through NicGit for heavy jobs; nothing requires the cloud.
- The code rename (`kimbim` → `nicbim` packages and `KIMBIM_*` identifiers) before external plugin APIs freeze.

---

## H1 in detail (what starts first)

| # | Work | Builds on | Exit criteria |
|---|------|-----------|---------------|
| 1 | Current default model in the assistant; model picker in Preferences | `agent/assistant.py` | No stale model id; the choice is per user |
| 2 | Simulation job model + result cache by state hash | records/state hash, energy (D222) | Re-running an unchanged job is instant; results show in Compare |
| 3 | Navigation graph + egress checks (travel distance, exit width, dead ends) | rooms, doors, stairs, checks (D81) | Egress check on the sample house and Clinic with cited rules |
| 4 | Population model (profiles + schedules) as project settings | settings (D72), HVAC occupancy | Agent tools read/write it; schedules drive CO₂ and lift demand |
| 5 | Typical floors with per-level overrides | models on levels (D58) | 60-storey tower from one typical floor + 3 exceptions |
| 6 | `bench-1m` and streaming tiles by level | Rust decomposer, viewer | 1M objects open < 20 s, 60 fps orbit |
| 7 | Brief-to-programme tool and a programme panel | agent catalogue, schedules | A brief PDF becomes an editable programme with sources |
| 8 | Code rename `kimbim` → `nicbim` | — | No `kimbim` identifiers left; suites green |

H2 starts with the pedestrian engine, lift traffic, the generative Compare board and the first EnergyPlus and
Radiance bridges.

## Risks

- **Scope.** This is a decade of work for a team. Each horizon must leave a shippable app; nothing waits for H4.
- **Trust.** One wrong "it complies" from the agent costs more than every feature gains; the code engine cites or
  refuses.
- **Performance debt.** Simulation and flow on every edit must be incremental and cached, or the editor dies.
- **Engine licences.** Bridges stay optional processes so GPL/AGPL/BSD engines do not leak into the core licence
  ([06](06-reuse-and-licensing.md)).
- **Liability.** Results are design aids unless a licensed professional signs them; the UI says so where it
  matters.
