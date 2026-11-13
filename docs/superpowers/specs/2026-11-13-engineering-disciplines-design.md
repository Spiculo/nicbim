# Engineering disciplines: structure, HVAC, water, drainage, electrical (design)

Status: design, 2026-11-13. Decisions D242–D248 (agent calls under D92: Archicad/Revit-style
default, behaviour configurable, owner not asked).

## Intent

The owner: "we are pretty much done with the simple features, we need to expand to more complex
ones, structural integrity, airflow, tubing, electrical, drainage, etc. Full BIM."

Today NicBim models *where* engineering elements are, not *whether they work*:

* MEP (D231/D234) draws ducts, pipes and trays with elbows, grouped in a named
  `IfcDistributionSystem`. There are no ports, no connections between parts, no terminals or
  equipment, no flows, no sizes derived from anything, and runs are horizontal only.
* Structure (D224) derives an `IfcStructuralAnalysisModel` with geometry only: no loads, no
  supports, no solve, no checks.

"Full BIM" here means each discipline becomes a **connected, calculated model**. Systems know
their parts and how they connect, flows and loads are computed from the architecture, sizes are
proposed and checked, and the results live in the IFC so other tools can read them.

## Goals

1. **One MEP network core** shared by every system: ports, connections, terminals and
   equipment, 3D (vertical and sloped) segments, network traversal, and "what's disconnected?".
2. **HVAC airflow**: air terminals get design flows from their rooms. Flows add up through the
   duct tree, ducts are sized by equal friction with a velocity limit, and the pressure drop and
   critical path are reported.
3. **Water supply (tubing)**: sanitary fixtures get loading units. Design flows come from the
   simultaneity curve, pipes are sized by velocity, and the pressure at the critical fixture is
   checked. Cold and hot water are separate systems.
4. **Drainage**: discharge units per fixture, flow from the K·√ΣDU formula, sizing by the
   fixture-unit and fill tables, and sloped gravity pipes with slope checks. Storm water is sized
   from roof area × rainfall intensity.
5. **Electrical**: distribution boards, circuits, devices with loads (lights, sockets,
   appliances). Circuit current, breaker and cable sizing, voltage drop, phase balance and a
   panel schedule.
6. **Structural integrity**: loads (self-weight from materials, area loads on slabs by use),
   supports, combinations, a 3D frame solve, member utilisation and deflection checks, and the
   results stored in IFC and shown in colour in the 3D view.
7. Every calculation reports its **inputs, method and assumptions** next to the numbers.

## Non-goals

* Certified or stamped calculations. Every report says "design aid, check with the engineer of
  record", in the spirit of D222's "not a compliance calculation".
* FEM plates/shells, dynamic, seismic or nonlinear analysis, buckling beyond a slenderness
  warning, or reinforcement design.
* CFD, thermal load calculation per room (the D222 energy estimate stays), lighting lux
  simulation, short-circuit studies, fire sprinkler hydraulics. These can come later on the same
  network core.
* Automatic routing of runs between terminals ("route this for me"). We do connect, size and
  check what the user draws.

## Anti-goals (failure even if it "works")

* Numbers without stated assumptions. A user must always see which code, table and setting
  produced a size.
* A silent model change. Resizing ducts or pipes is a proposal the user applies, as one undo
  step.
* Calculations that only live in NicBim. Sizes, flows, loads and results go into standard IFC
  (ports, `Pset_*Common`, `IfcStructuralLoad*`, result groups) plus `KIMBIM_*` psets for what IFC
  has no slot for.
* A slow app. Calculations run on demand (a menu command or a check), never on every edit.

## Constraints

* Python engine modules over IfcOpenShell (`ifcopenshell.api.system`, `api.structural`) plus
  numpy. No new dependencies, and own implementations of the published formulas (GPL-safe).
* IFC2X3, IFC4 and IFC4X3 all work. IFC2X3 lacks `IfcDuctSegment` and similar classes and uses
  `IfcFlowSegment`, `IfcRelConnectsPortToElement` and `IfcElectricalCircuit`, the same fallbacks
  `finishes.py` uses.
* Every edit is one undo step through `B._run` or `console.edit()`. Every UI string is EN + ES.
  Public functions go in `app_bridge._EXPORTS`.
* Settings live in project settings (`settings.json` per version), with defaults, validation
  and one undoable change, like `energy_settings`.
* Lengths are metres; flows are L/s, pressures Pa, loads kN, kN/m and kN/m².

## Design decisions (agent calls)

### D242 MEP network core (`mep.py`)

* **Ports.** Every MEP element made by NicBim carries `IfcDistributionPort`s at its connection
  points (`api.system.add_port` + placement): two on a segment, two (or three for a tee) on a
  fitting, one on a terminal, and one or more on equipment. Each port has a `FlowDirection`
  (SOURCE/SINK/SOURCEANDSINK), a `PredefinedType` (DUCT/PIPE/CABLE/CABLECARRIER) and a
  `SystemType`.
* **Connections.** `connect_network(system)` links ports whose positions coincide within 5 mm
  (setting `mep.connect_tolerance`) with `api.system.connect_port`. Drawing a run connects as it
  goes: a run that starts or ends on an existing port, or on a segment's centreline, joins it. A
  segment hit mid-length is split and gets a **tee**.
* **3D segments.** `create_mep_segment3d(x1,y1,z1,x2,y2,z2,...)` generalises the horizontal
  segment, so risers and sloped pipes become possible. The existing 2D functions call it.
* **System kinds** (configurable list `mep.system_kinds`, defaults below), each with a domain
  (air, water, drainage, electrical), an IFC `PredefinedType` and a colour:
  supply air, return air, exhaust air, outside air, domestic cold water, domestic hot water,
  sanitary drainage (sewage), storm water, vent, power, lighting, data.
* **Terminals and equipment** come from one catalogue (`mep.catalogue`, project-editable), each
  entry giving an IFC class/type, a box or cylinder geometry, ports and default engineering
  values:
  * air: supply diffuser, return grille, exhaust valve (IfcAirTerminal), air handling unit
    (IfcUnitaryEquipment AIRHANDLER), fan (IfcFan);
  * water/drainage: WC, wash basin, sink, shower, bath, urinal, washing machine, dishwasher
    (IfcSanitaryTerminal or IfcElectricAppliance with water ports), floor drain (IfcWasteTerminal
    FLOORTRAP), roof drain (IfcWasteTerminal ROOFDRAIN), water meter/main (IfcFlowMeter),
    water heater (IfcElectricFlowStorageDevice or IfcTank), pump (IfcPump);
  * electrical: distribution board (IfcElectricDistributionBoard; IfcElectricDistributionPoint
    in IFC2X3), socket outlet (IfcOutlet), light fixture (IfcLightFixture), switch
    (IfcSwitchingDevice), appliance (IfcElectricAppliance).
  Placed with `place_mep_terminal(kind, storey, x, y, z, rotation, system)`.
* **Traversal.** `network(system)` returns the graph (elements, port-to-port edges), the
  source(s) (equipment or a marked main), and the tree from the source. It reports loops,
  disconnected parts and terminals not reached.
* **Model checks** join the Checks panel (D81): open ports, elements in no system, systems
  without a source, and (D244/D245/D246) undersized parts and slopes out of range.

### D243 HVAC airflow (`hvac.py`)

* **Terminal flows.** A terminal's design flow (`KIMBIM_MEPDesign.Flow`, L/s) is typed directly
  or derived from the room it sits in. The default method is EN 16798-1 category II: 7 L/s per
  person + 0.7 L/s·m² (low-polluting building), with occupancy from area/person by space use.
  Alternatives are an air-change rate (ACH × volume) or a flow per area. The room's flow is shared
  equally among its supply terminals; return/exhaust terminals balance it. All of this is
  configurable in `hvac_settings`.
* **Accumulation.** From the network tree, each segment's flow is the sum of the terminals
  downstream.
* **Sizing**: equal friction (default 1.0 Pa/m) capped by velocity (mains 6 m/s, branches
  4 m/s, terminal connections 2.5 m/s). Round ducts come from the standard diameter series
  (100…1250 mm). Rectangular ducts keep the drawn height (or an aspect ratio ≤ 4) and take widths
  in 50 mm steps, using the equivalent diameter (Huebscher). This mirrors Revit's friction/velocity
  sizing.
* **Pressure drop**: Darcy–Weisbach with Swamee–Jain friction (roughness 0.09 mm galvanised),
  plus fittings by K factor (elbow 0.3, tee branch 1.0, tee straight 0.2, terminal 25 Pa
  default). The critical path is the largest total from source to terminal; the report gives the
  fan's required external pressure and flow.
* **Applying sizes.** `size_air_system(system, apply=False)` returns the table. `apply=True`
  rebuilds the segment profiles and fittings (one undo step) and writes
  `Pset_DuctSegmentTypeCommon`-style values plus `KIMBIM_MEPDesign` (Flow, Velocity,
  PressureDrop, SizedBy).

### D244 Water supply (`plumbing.py`)

* **Loading units**: EN 806-3 by default (WC cistern 1 LU, basin 1, shower 2, bath 4, sink 2,
  urinal 1, washing machine 2, dishwasher 1). The design flow follows EN 806-3's curve from ΣLU
  (the table is tabulated and interpolated). IPC/UPC Hunter water supply fixture units are an
  alternative (`plumbing_settings.method = "hunter"`).
* **Sizing** by maximum velocity (default 2.0 m/s mains, 1.5 m/s branches) over the nominal
  copper/PEX/PPR series in the setting `plumbing_settings.pipe_series`. Pressure drop comes from
  Darcy–Weisbach (roughness by material), plus 30 % for fittings (configurable) and the static
  head from height differences.
* **Pressure check**: available pressure at the source (default 300 kPa) minus losses must leave
  the fixture's minimum flow pressure (default 100 kPa) at the critical fixture, else a warning.
* Hot water is its own system (the same method on the hot ports of fixtures). A water heater is
  the hot system's source and a sink on cold.

### D245 Drainage (`drainage.py`)

* **Discharge units**: EN 12056-2 system I by default (WC 2.0, basin 0.5, shower 0.6, bath 0.8,
  sink 0.8, urinal 0.5, washing machine 0.8, dishwasher 0.8, floor drain DN50 0.8). Flow is
  Q = K·√ΣDU with K from building use (0.5 dwelling, 0.7 office/school, 1.0 hospital/restaurant,
  1.2 lab), floored at the largest single fixture. IPC DFU tables are the alternative.
* **Gravity pipes.** Drainage segments are drawn sloped. The run tool takes a slope (default
  2 %, setting) and lowers each point downstream from the first click. `check_slopes` flags pipes
  under the minimum (1 % DN ≥ 100, 2 % smaller) or sloping the wrong way (flowing uphill relative
  to the network direction).
* **Sizing**: a horizontal branch's capacity comes from Manning at 50 % fill (70 % for drains
  DN ≥ 150; settings) for its slope. Stacks are sized by the EN table of maximum Q per DN. The
  minimum DN per fixture applies (WC DN100/DN90…), and a pipe never shrinks downstream.
* **Storm water**: roof drains get Q = r · A · C. The intensity r (default 0.03 L/s·m²) and the
  run-off coefficient C (1.0 roofs) are settings, and A is the roof area each drain serves (the
  nearest drain on the same roof, or typed). Downpipes and collectors are sized the same way.
* **Vent check**: a stack with more than a set number of DU and no vent system connected gets a
  warning, not sizing.

### D246 Electrical (`electrical.py`)

* **Circuits.** `IfcDistributionCircuit` (IFC4+; `IfcElectricalCircuit` in IFC2X3) is a
  sub-system fed by a board, with devices assigned (Revit-style "create circuit from selection").
  Each circuit has a voltage (230 V single-phase / 400 V three-phase, settings), a phase (L1/L2/L3
  or 3P) and a cable length. The length is measured from the board along the device positions
  (Manhattan path, × 1.2 routing factor, setting) unless typed or drawn as a cable tray/conduit
  run.
* **Loads**: each device has an apparent power (VA) and power factor (catalogue defaults: socket
  outlet 200 VA × diversity, light fixture as typed (default 36 W), appliances by kind).
  Diversity/demand factors per load class come from settings.
* **Sizing (IEC 60364 defaults).** Design current I_b = S/(U·√phases) after demand. Breaker
  I_n is the next standard rating ≥ I_b (6, 10, 13, 16, 20, 25, 32, 40, 50, 63, 80, 100, 125 A).
  Cable is the smallest copper PVC cross-section whose I_z (installation method C table, ×
  correction factor setting) ≥ I_n. Voltage drop is ΔU = b·ρ·L·I_b·cosφ/S. Limits: 3 % lighting
  and 5 % other (settings); a failing cable is upsized up to 5 steps.
* **Board**: the panel schedule lists circuits, phases and loads, with the phase imbalance and
  the board's total demand and main breaker. It is available as a schedule and on sheets through
  the existing schedule machinery (D77).

### D247 Structural integrity (`structanalysis.py`, extends D224)

* **Physical → analytical.** D224's members are reused. Members gain nodes
  (`IfcStructuralPointConnection`): ends within 10 mm merge, and a beam end within a column's
  section snaps to the column axis. Column bases on the lowest level (or with nothing beneath)
  get supports, fixed by default (setting: pinned/fixed) via `IfcBoundaryNodeCondition`.
* **Materials**: E, G, density, fy/fck and γM come from a materials table keyed by the
  element's material name and category: steel S235/S275/S355, concrete C20/25…C40/50, timber
  C24/GL24h. Unknown materials fall back to the category's default with a warning. The table
  extends the D96 material library through `structure_settings.materials`.
* **Sections**: area, I_y, I_z, J, W_y and W_z come from the profile (rectangle, circle, hollow
  rectangle/circle, IfcIShapeProfileDef, IfcLShape/TShape/UShape where easy, and arbitrary
  polygons by polygon integration).
* **Loads (EN 1991 defaults).** Load cases: G self-weight (computed), G2 superimposed dead (area
  setting, default 1.5 kN/m²), Q imposed by use category (A 2.0, B 3.0, C 4.0, D 5.0, roof H 0.4
  kN/m²; each slab's category from its level's or room's use, else A), and S snow (setting, 0
  default). User point/line loads can be added on members.
* **Load path.** Slab area loads go to the beams that support the slab's edges by tributary
  area (two-way: the 45° envelope; one-way when the aspect ratio is > 2), as line loads. A slab
  with no beams goes to columns under it by tributary (Voronoi-lite: nearest column), as point
  loads. Walls marked load-bearing (`Pset_WallCommon.LoadBearing`) become line supports for slabs
  and transfer to the level below as a line load (bearing-wall take-down). Bearing walls are not
  solved as plates.
* **Combinations (EN 1990)**: ULS 1.35G + 1.5Q (+ ψ0 S) and SLS characteristic G + Q. Factors
  are settings, so ASCE 7 1.2D + 1.6L is a preset.
* **Solver**: a linear 3D frame by the direct stiffness method, 12 DOF Euler–Bernoulli elements
  with local axes from the member's placement (numpy dense up to 3000 DOF, scipy-free banded
  fallback not needed at this size). Distributed loads go in as equivalent nodal loads; results
  are recovered at the ends and 10 internal stations.
* **Checks.** Steel uses EN 1993 cross-section: N/A·fy + M/W·fy combined linearly ≤ 1/γM0, plus
  shear and a slenderness (λ) warning. Timber uses an EN 1995 simplified combined check.
  Concrete members are checked only for indicative stress and deflection, with an explicit "no
  reinforcement design" note. Deflection limits are L/250 total and L/300 cantilever/span
  (settings). Utilisation > 1 fails, > 0.9 warns.
* **Output**: `IfcStructuralLoadGroup`/`LoadCase` per case and combination, actions on members,
  reactions on supports, and an `IfcStructuralResultGroup` per combination, plus
  `KIMBIM_StructuralResult` on each physical member (MaxUtilisation, GoverningCheck, Combination,
  Deflection). Re-running replaces them.
* **View**: *Structure › Show utilisation* colours members green/amber/red in 3D through the
  existing colour-override path (same mechanism as Compare colours); a report dialog lists
  members, reactions and failures.

### D248 Discipline UI and integration

* A new top-level **Engineering** menu (EN "Engineering" / ES "Ingeniería") holds MEP
  (Systems…, Place terminal/equipment…, Run (3D)…, Connect network, Network check), HVAC
  (Airflow and sizing…), Plumbing (Water supply sizing…, Drainage sizing…, Storm water…),
  Electrical (Circuits…, Panel schedule…), and Structure (Analytical model (D224 moves here),
  Loads and supports…, Analyse…, Show utilisation, Results…). The existing MEP and analysis
  commands in the Model menu move here.
* Each calculation dialog is a table of results with a *Settings* box (the energy dialog
  pattern, D222), *Apply sizes* where relevant, and *Select failing*.
* The agent gets tools for each calculation (read-only by default; apply as an edit), in the
  `agent` tool table (doc 17).
* Schedules gain duct, pipe, fixture, circuit and panel schedule templates.

## Order of building (each a slice, verified before the next)

1. D242 MEP network core (everything else depends on it)
2. D247 structure (independent of MEP; the largest user value per the owner's first word)
3. D243 HVAC airflow
4. D244 water supply + D245 drainage (shared fixture catalogue)
5. D246 electrical
6. D248 Engineering menu, dialogs, checks, schedules, agent tools, docs (the UI grows with each
   slice; the menu reorganisation is finished last)

## Left to the builder

* Exact table values beyond those given above (they come from the cited standards; cite the
  table in code comments).
* Geometry details of terminals/equipment (simple boxes and cylinders with the right ports are
  enough).
* Performance tuning, as long as a 500-member frame solves in under 5 s and a 300-element system
  sizes in under 2 s.

## Testing

Each module gets `tests/python/test_<module>.py` with hand-checked cases: a cantilever and a
simply supported beam against closed-form results (δ = PL³/3EI, M = wL²/8), a two-bay portal
frame equilibrium (Σ reactions = Σ loads), duct and pipe sizing on small trees against
hand-computed tables, a drainage stack, and a circuit with a known voltage drop. App tests check
that the new actions exist and that the dialogs open on a sample model. Each slice must pass its
own tests and the targeted suites (`test_finishes`, `test_structural`, `test_checks`,
`test_imports`, `test_app_bridge`).
