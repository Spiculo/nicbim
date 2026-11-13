# MEP network core (D242) and structural integrity (D247) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make MEP systems connected networks of ports, terminals and equipment, and make the
structural model loadable, solvable and checkable.

**Architecture:** New engine modules `engsettings.py` (shared settings), `mep.py` (ports,
catalogue, network), `sections.py` (profile properties), `frame.py` (pure numpy 3D frame solver)
and `structanalysis.py` (loads, supports, combinations, checks, IFC results), all exposed through
`app_bridge._EXPORTS`, plus an Engineering menu in `app/src/Engineering.cpp`.

**Tech Stack:** Python 3.12, IfcOpenShell 0.9 (`api.system`, `api.structural`), numpy; C++/Qt 6.

**Spec:** `docs/superpowers/specs/2026-11-13-engineering-disciplines-design.md`

## Global Constraints

- Every edit is one undo step (`B._run`, `B._run_settings`, or `console.edit()`).
- IFC2X3, IFC4 and IFC4X3 all work (IFC2X3: `IfcFlowSegment`/`IfcFlowFitting`/`IfcFlowTerminal`, `IfcRelConnectsPortToElement`).
- Lengths m, flows L/s, pressure Pa, loads kN, kN/m, kN/m²; results JSON via `B._dump`.
- Settings keys `mep_settings`, `hvac_settings`, `plumbing_settings`, `drainage_settings`, `electrical_settings`, `structure_settings` store **overrides only**; `engsettings.get(key)` merges code defaults.
- Every UI string EN + ES (`app/translations/*_es.ts`). No new dependencies.
- Reports carry `assumptions: [str]` and `method: str`.

## Review Focus

- A run drawn from the end of an existing run → connected automatically (no open port at the joint). Test in Task 3.
- An IFC opened from elsewhere whose MEP elements have no ports → network reports them as unconnected, never crashes. Test in Task 5.
- A frame with no supports or a mechanism → a clear "unstable: no supports/mechanism" error, not a numpy LinAlgError. Test in Task 9.
- A member whose material or profile is unknown → falls back with a warning in the report. Test in Task 10.
- Undo after connect/analyse → model back exactly (no orphan ports, load groups). Test in Tasks 3 and 11.

---

### Task 1: Engineering settings

**Files:** Create `python/kimbim/engsettings.py`; Modify `python/kimbim/settings.py` (DEFAULTS + `_error`); Test `tests/python/test_engsettings.py`

**Interfaces:** Produces `engsettings.DEFAULTS: dict[key, dict]`, `get(key) -> dict` (deep merge of defaults and overrides), `validate(key, value) -> str | None`, bridge `engineering_settings(key) -> json {ok, settings, defaults}`, `set_engineering_settings(key, json) -> json` (one undoable settings change, unknown keys refused).

- [ ] Test: `get("hvac_settings")["friction_pa_m"] == 1.0`; set `{"friction_pa_m": 2}` then `get` gives 2 and undo restores 1.0; set `{"nope": 1}` fails; set `{"friction_pa_m": -1}` fails.
- [ ] Implement; ranges are a `RANGES[key][name] = (lo, hi)` table, and nested tables (catalogue, materials, use loads) are validated as dicts of numbers.
- [ ] Run `pixi run pytest tests/python/test_engsettings.py -q` → pass. Commit.

### Task 2: Ports and 3D segments

**Files:** Create `python/kimbim/mep.py`; Modify `python/kimbim/finishes.py` (`create_mep_segment` delegates; `create_mep_run` fittings get ports); Test `tests/python/test_mep.py`

**Interfaces:** Produces `mep.add_ports(element, specs: list[dict(point=(x,y,z) world m, direction=SOURCE|SINK|SOURCEANDSINK, type=DUCT|PIPE|CABLE|CABLECARRIER, system_type=str)])`, `mep.port_points(element) -> list[(port, np.array world m)]`, `create_mep_segment3d(storey, kind, x1,y1,z1,x2,y2,z2, width, height, system="") -> json {guid, length}` (z absolute above project zero... no: z above the level, like `elevation`).

- [ ] Test: a 3D pipe from (0,0,0)→(0,0,3) is vertical (placement Z axis up, length 3) and has 2 ports at the ends; `create_mep_segment` still gives `KIMBIM_MEP` and now 2 ports; elbows of a 3-point run have 2 ports each.
- [ ] Implement with `ifcopenshell.api.system.add_port` + `edit_object_placement`; IFC2X3 uses `IfcRelConnectsPortToElement` (api handles it). Segment direction: local Z along the run; for vertical runs local X = world X.
- [ ] Run tests → pass. Commit.

### Task 3: Connections and tees

**Files:** Modify `python/kimbim/mep.py`, `python/kimbim/finishes.py`; Test `tests/python/test_mep.py`

**Interfaces:** Produces `connect_network(system_guid: str = "") -> json {connected: int}` (coincident free ports within `mep_settings.connect_tolerance` 0.005 m), `create_mep_run` connects its own parts and joins existing free ports at its first/last point, and splits a segment it starts/ends on mid-length, adding a tee (`PredefinedType` JUNCTION, 3 ports).

- [ ] Test: a 3-point run has 0 open ports inside it (2 open ends); a second run starting at the first's end leaves 3 open ports total… (2 ends); a run starting at the middle of a segment makes 2 segments + 1 tee, open ports = 3; undo restores the original segment and port count.
- [ ] Implement; ports connect with `api.system.connect_port`.
- [ ] Run → pass. Commit.

### Task 4: Catalogue and terminals/equipment

**Files:** Modify `python/kimbim/mep.py`, `engsettings.py` (`mep_settings.catalogue` overrides); Test `tests/python/test_mep.py`

**Interfaces:** Produces `CATALOGUE: dict[kind, {cls, cls2x3, predefined, size:(w,d,h), ports:[{offset:(x,y,z), direction, type, domain}], design:{...}}]` with kinds: supply_diffuser, return_grille, exhaust_valve, ahu, fan, wc, basin, sink, shower, bath, urinal, washing_machine, dishwasher, floor_drain, roof_drain, water_main, water_heater, pump, board, socket, light, switch, appliance; `mep_catalogue() -> json`, `place_mep_terminal(kind, storey, x, y, z=None, rotation=0, system="") -> json {guid}` (z default per kind: ceiling terminals at level height − 0.3? use `default_z`), design values written to `KIMBIM_MEPDesign` (Flow, LoadingUnits, DischargeUnits, ApparentPower, PowerFactor…).

- [ ] Test: placing a wc in IFC4 gives an `IfcSanitaryTerminal` TOILETPAN with a cold-water SINK port and a drainage SOURCE port and DischargeUnits 2.0; a board is `IfcElectricDistributionBoard`; all kinds place in IFC2X3 too.
- [ ] Run → pass. Commit.

### Task 5: Systems and network traversal

**Files:** Modify `python/kimbim/mep.py`; Test `tests/python/test_mep.py`

**Interfaces:** Produces `SYSTEM_KINDS` (supply_air, return_air, exhaust_air, outside_air, cold_water, hot_water, sanitary, storm, vent, power, lighting, data → domain, predefined, colour), `create_system(name, kind) -> json {guid}`, `assign_to_system(guids_json, system_guid) -> json`, `mep_systems()` (moves from finishes, adds kind/domain), `network(system_guid) -> dict {elements, edges:[(a,b)], sources, tree: {guid: parent}, order: [guid] source-first, unreached, open_ports, loops}` (Python dict for engine use) and `mep_network(system_guid) -> json`. Source = equipment with a SOURCE port in the domain (ahu/fan for air, water_main/water_heater/pump for water, board for electrical; for drainage the *sink* end: the element marked `KIMBIM_MEPDesign.Outlet` or the lowest open pipe end).

- [ ] Test: ahu → duct run → 2 diffusers: tree has the ahu as root, diffusers are leaves, unreached empty; a pipe imported without ports (strip them) shows in `unreached`.
- [ ] Run → pass. Commit.

### Task 6: MEP model checks + bridge + UI

**Files:** Modify `python/kimbim/checks.py` (MODEL_CHECKS += mep_open_ports, mep_no_system, mep_no_source), `python/kimbim/app_bridge.py` (`_EXPORTS["mep"]`, `["engsettings"]`), Create `app/src/Engineering.cpp` (+ declare in MainWindow.h, add to app/CMakeLists), translations; Test `tests/python/test_checks.py` addition, app test `engineeringActionsExist`.

- [ ] Engineering menu with: *MEP systems...* (table: name, kind, elements, open ports; New system, Assign selection), *Place MEP terminal...* (kind list then click), *3D MEP run...* (existing run tool with z per point via typed slope/rise), *Connect network*, and the existing duct/pipe/tray commands moved here.
- [ ] Build `pixi run build-app` and run `pixi run app-test` → pass. Commit.

### Task 7: Section properties

**Files:** Create `python/kimbim/sections.py`; Test `tests/python/test_sections.py`

**Interfaces:** Produces `section(profile, scale) -> dict {A, Iy, Iz, J, Wy, Wz, h, b, kind}` in SI (m², m⁴, m³) for rectangle, circle, rectangle/circle hollow, I, L, T, U, C and arbitrary closed polygons (shoelace moments); `None` for unsupported.

- [ ] Test: rectangle 0.2×0.4 → A 0.08, Iy (strong, about the local X when YDim is depth) 0.2·0.4³/12; circle r=0.1 → πr⁴/4; IPE300-like I (b .15, h .3, tw .0071, tf .0107) A ≈ 0.00538 within 3 %; polygon square = rectangle.
- [ ] Commit.

### Task 8: Frame solver

**Files:** Create `python/kimbim/frame.py`; Test `tests/python/test_frame.py`

**Interfaces:** Produces `solve(nodes: ndarray (n,3), members: list[dict(i, j, E, G, A, Iy, Iz, J, roll_vector)], supports: dict[node, 6 bools], node_loads: dict[node, 6 floats], member_loads: list[dict(member, w: (wx,wy,wz) global kN/m)]) -> dict {displacements (n,6), reactions dict, forces: list[(stations, N, Vy, Vz, T, My, Mz, defl)]}`; raises `frame.Unstable(message)` when the stiffness is singular (rank check) or there are no supports.

- [ ] Tests: cantilever L=3, P=10 kN at tip, E=210e6 kPa, I=8.36e-5 → δ = PL³/3EI within 1 %, base moment 30; simply supported w=5 → midspan M = wL²/8 within 1 %, δ=5wL⁴/384EI; portal frame Σ reactions = Σ loads; no supports → Unstable; a pin-pin-pin mechanism → Unstable.
- [ ] Commit.

### Task 9: Analysis model build (nodes, supports, loads, combinations)

**Files:** Create `python/kimbim/structanalysis.py`; Modify `engsettings.py` (`structure_settings`: support base fixed|pinned, merge_tolerance 0.01, materials table, use loads {A:2,B:3,C:4,D:5,H:0.4}, superimposed 1.5, snow 0, combinations ULS {G:1.35,Q:1.5,S:0.75}, SLS {G:1,Q:1,S:0.5}, deflection L/250, cantilever L/125); Test `tests/python/test_structanalysis.py`

**Interfaces:** Consumes D224 `structural.create_analysis_model`, `sections.section`, `frame.solve`. Produces `build(model) -> Analysis` (dataclass: nodes, members [with source guid, material, section, length], supports, cases {G, G2, Q, S: node/member loads}, warnings), `slab_loads(slab, beams, columns) -> member line loads / node loads` (tributary as spec), `combinations(settings) -> {name: {case: factor}}`.

- [ ] Tests: the D224 frame fixture (column + beam + slab) gets 1 support at the column base; a 4×4 slab on 4 beams with Q 2 kN/m² gives each beam a total of 8 kN (two-way, 45°: total 32 kN shared equally); self-weight of a 0.3×0.5 concrete beam 4 m = 0.15·25·4 = 15 kN; unknown material → steel/concrete default by class with a warning.
- [ ] Commit.

### Task 10: Checks and results

**Files:** Modify `python/kimbim/structanalysis.py`; Test `tests/python/test_structanalysis.py`

**Interfaces:** Produces `analyse_structure(apply: bool = True) -> json {ok, combinations, members:[{guid, name, utilisation, governing, deflection, deflection_limit, status pass|warn|fail}], reactions:[{node, xyz, F, M}], warnings, assumptions, method}`; `apply` writes `KIMBIM_StructuralResult` on physical members and IFC load groups/cases/results (one undo step); `structure_results() -> json` reads them back; `utilisation_colours() -> json {guid: "#rrggbb"}`.

- [ ] Tests: a steel beam with a huge load fails and is red, a light one passes green; steel utilisation = N/(A fy) + M/(W fy) for a hand case; reactions sum = total ULS load; undo removes results and load groups.
- [ ] Commit.

### Task 11: Structure UI

**Files:** Modify `app/src/Engineering.cpp`, translations, bridge `_EXPORTS["structanalysis"]`, `["sections"]`; app test.

- [ ] *Structure ›* Analytical model (moved), Structural settings… (loads, supports, materials, combinations), Analyse… (results table, reactions, warnings, Select failing), Show utilisation (colour override toggle).
- [ ] App build + `pixi run app-test` → pass; targeted pytest (`test_structural test_structanalysis test_frame test_sections test_mep test_finishes test_checks test_imports test_app_bridge`) → pass. Commit.
