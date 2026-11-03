<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# 21 — Final doc-14 gap checklist

Every tool row in [14](14-tool-inventory.md), classified as **Done**, **Deferred** (future or partial)
or **Blocked** (needs an owner-provided asset or hardware). The status is the row's inventory status
after D123–D194 plus explicit overrides for the final items.

**Summary: 177 done, 29 deferred, 3 blocked.**

## Owner-provided blockers

| Blocked item | What only the owner can provide |
|---|---|
| Actual code signing | A `.pfx`/`.p12` certificate and its password (`KIMBIM_SIGN_PASSWORD`); the wrapper is tested with a fake runner |
| SketchUp `.skp` import | Trimble SketchUp SDK access/licence and a redistribution decision |
| VR | An OpenXR runtime and headset for testing, and a decision that VR is in scope |

## Future scope (deferred, not blocked)

- Deeper visualisation beyond the current ray/path-traced exports: offline render farm, animation, walkthrough video.

## Every item

| Section | Item | Status | Notes |
|---|---|---|---|
| 1. Project and files | Open / save IFC | **Done** | IFC4; IFC2X3 opens, edits and saves (Duplex and Clinic corpus files; `test_e2e`, `test_levels`, `test_dxf`) |
| 1. Project and files | Installer / portable build | **Blocked** | Portable install/uninstall (D144) and the signing wrapper (D145) are done; actual signing needs the owner's certificate. |
| 1. Project and files | New project | **Done** | IFC4 in mm, levels |
| 1. Project and files | Project templates (units, levels, types, views, title blocks) | **Done** | D72: office templates (File › New from template, Save as template) |
| 1. Project and files | Autosave, crash recovery | **Done** | D72: recovery copies on a timer, offered again after a crash; no oplog yet ([03](03-versioning.md)) |
| 1. Project and files | Recent projects | **Done** | File › Recent files |
| 1. Project and files | Imperial units, unit preferences | **Done** | D108: project length units m/cm/mm/**ft/in** and areas m²/cm²/mm²/**ft²/in²**, in Project settings, every length/area field and format; the model stays in metres |
| 1. Project and files | Project info (address, client, number) used in title blocks | **Done** | Slice 16: *File › Project info…*, in IFC fields (D63) |
| 1. Project and files | Survey point, project base point, georeferencing | **Done** | D115: File › Georeferencing... (eastings, northings, height, rotation, scale, projected CRS and true north; `IfcMapConversion`/`IfcProjectedCRS`) |
| 1. Project and files | Story settings (levels table: edit heights, insert/delete) | **Done** | D79: Model › Levels..., one undo step; elements follow. D123: imported storeys without a Name are numbered "Level 1", "Level 2"... in the level list and plan tabs |
| 1. Project and files | Purge unused types/materials | **Done** | D96: Graphics › Purge unused materials (surfaces, materials, composites); D115: Model › Purge unused types |
| 2. Viewing and navigation | Orbit, pan, zoom, fit all | **Done** | D48 preset |
| 2. Viewing and navigation | Plan view and 3D view | **Done** | P / 3 |
| 2. Viewing and navigation | View cube | **Done** | D76: OCCT AIS_ViewCube, home button, drag to turn |
| 2. Viewing and navigation | Preset views (front, back, sides, isometric) | **Done** | D76: View › Views, Alt+1…Alt+0 |
| 2. Viewing and navigation | Perspective camera | **Done** | D76: View › Perspective (Shift+P), per view |
| 2. Viewing and navigation | Touchpad navigation | **Done** | D89: two-finger scroll pans, Shift orbits, pinch zooms; scroll preference |
| 2. Viewing and navigation | Walk / fly mode | **Done** | D152: View > *Walk mode* (Shift+W): first-person perspective at the current camera, WASD/arrows move, Q/E or PageUp/PageDown fly up/down, Shift runs, drag looks, Esc exits; a plan view refuses it and switching views stops it |
| 2. Viewing and navigation | Hide, isolate, show all (per element, per level) | **Done** |  |
| 2. Viewing and navigation | Hide / isolate by class or type | **Done** | View › Hide / Isolate selected (I); Edit › Select all of this class / Select similar first |
| 2. Viewing and navigation | Plan cut height | **Done** | Slider beside the view |
| 2. Viewing and navigation | Poché on cut elements | **Done** | D96: fill from the building material; composites cut layer by layer |
| 2. Viewing and navigation | Section box | **Deferred** | Core done; remainder deferred. Around the selection; no drag handles |
| 2. Viewing and navigation | Free clipping planes, several at once | **Done** | D95: the Cut planes panel (several, oblique, flip, offset) |
| 2. Viewing and navigation | Saved views (layers, level, plan/3D, cut) | **Done** | D57 |
| 2. Viewing and navigation | Lines-only / hidden-line display | **Done** | L |
| 2. Viewing and navigation | Visual styles: shaded, textured, sketch, X-ray | **Deferred** | Core done; remainder deferred. Shaded, textured (D96), white model, lines only; no sketch or X-ray |
| 2. Viewing and navigation | Shadows and sun position | **Done** | D96: View › Sun shadows, View › Sun... (azimuth/altitude or place, date, time), White model |
| 2. Viewing and navigation | Hover info (name, type, level) | **Done** |  |
| 2. Viewing and navigation | Colour by property, class or type | **Done** | D73 override rules (property, class, kind, layer, material) |
| 2. Viewing and navigation | Show multiple levels at once (ghost story / underlay) | **Done** | D98: View › Trace reference (level below or above, snappable); Level above/below Ctrl+Up/Down |
| 2. Viewing and navigation | Split views / several windows side by side | **Done** | D153: View > *Split view side by side* (Ctrl+\\) duplicates the active 3D or plan view in a new area, copying its camera/plan and cuts; drawings and sheets are not split. |
| 2. Viewing and navigation | Navigator / project browser (tree of views, sheets) | **Done** | D163: Model tree, levels and views; a *Sheets* heading lists every sheet (number and title), double-click or *Open* opens it. Drawings and other views stay in their own panels. |
| 3. Selection | Click, Ctrl/Shift add and toggle | **Done** |  |
| 3. Selection | Box selection (visible only; Alt goes through) | **Done** | D52 |
| 3. Selection | Crossing vs window box (direction decides) | **Done** | D78: right to left crosses (dashed band) |
| 3. Selection | Select similar (same type or class) | **Done** | D78: Ctrl+Shift+A (type), Select all of this class |
| 3. Selection | Find & Select / query (by property values) | **Done** | D78: Ctrl+F panel; class, kind, type, property, layer, level, status, material; AND/OR; saved criteria |
| 3. Selection | Selection sets (saved selections) | **Done** | D78: in the project settings (versioned) |
| 3. Selection | Marquee (area selection for 2D export or editing) | **Done** | D155: Edit > *Marquee selection* makes a dragged rectangle a crossing selection that includes touched hidden elements; off restores normal box selection. |
| 3. Selection | Magic wand (pick a shape from existing lines or edges) | **Done** | D84/D165: Model > *Fill from selected shape* fills a selected closed polyline, circle or fill (magic wand); the Fill tool's Alt+click fills the closed shape around the click (`fill_at`). |
| 3. Selection | Tab cycling through overlapping elements | **Done** | D89: Tab / Shift+Tab, the click selects the highlighted one |
| 4. Editing tools (general) | Undo / redo | **Done** |  |
| 4. Editing tools (general) | Move, drag to move | **Done** | Joined walls follow; Ctrl detaches (D54) |
| 4. Editing tools (general) | Rotate | **Done** |  |
| 4. Editing tools (general) | Stretch / extend a wall end | **Done** |  |
| 4. Editing tools (general) | Copy / paste in the project | **Done** | Slice 17 (Ctrl+C / Ctrl+V onto the active level) |
| 4. Editing tools (general) | Duplicate, drag a copy (Ctrl+drag) | **Done** | Slice 17 (Ctrl+D, Ctrl+drag) |
| 4. Editing tools (general) | Copy to another level | **Done** |  |
| 4. Editing tools (general) | Mirror | **Done** | Slice 17 (Ctrl+M; Ctrl mirrors a copy) |
| 4. Editing tools (general) | Array: linear, rectangular, polar | **Done** | Slice 17: linear and polar (Ctrl+U); D115: rectangular grid (nx by ny, the original in the first cell) |
| 4. Editing tools (general) | Offset (parallel copy) | **Done** | Slice 17: walls (parallel copy), slabs (grow/shrink) |
| 4. Editing tools (general) | Trim, extend to boundary, split, join | **Done** | D80: walls and beams (split, trim/extend to an element, a grid line or a corner, join/merge, unjoin; Shift+S, Shift+T, Shift+J); D98: curved walls split; D191: 2D drafting lines trim/extend, split and corner, and curved walls trim/extend on their arc |
| 4. Editing tools (general) | Align (to an edge or face) | **Done** | D154: Edit > *Align...* aligns on X/Y/Z at min/max/centre to the selection's combined bounds (or a reference element); one undo step. |
| 4. Editing tools (general) | Elevate (change vertical position) | **Done** | D159: Edit > *Elevate...* moves the selection up or down by a distance without changing its plan position (hosted doors/windows follow); the `move_elements` `dz` path. |
| 4. Editing tools (general) | Resize / scale | **Done** | D98: Edit › Resize (about the selection's middle) |
| 4. Editing tools (general) | Pick up and inject settings (eyedropper / match properties) | **Done** | D97: Edit › Pick up / Inject settings (Ctrl+Alt+C / V) |
| 4. Editing tools (general) | Edit by polygon points (add, move, delete vertices; curve an edge) | **Deferred** | Core done; remainder deferred. D98: Stretch tool on slabs and 2D shapes: move, add at an edge's middle, Ctrl+click delete; no curved edges |
| 4. Editing tools (general) | Solid element operations (subtract, intersect, add) | **Done** | Cut, intersection and union with one or more tools; `boolean_batch` and the selection-set batch; covered by `tests/python/test_solid_operations.py` (4 tests) and the app action checks. |
| 4. Editing tools (general) | Lock / pin elements | **Done** | D160: Edit > *Lock selection* / *Unlock selection* writes `KIMBIM_Lock` (`Locked`); locked elements refuse moves, deletes, align/resize/offset/fillet and dimension edits until unlocked; agent `elements.lock`. |
| 4. Editing tools (general) | Group / ungroup | **Done** | D162: Edit > *Group* / *Ungroup* stores a `KIMBIM_Group` id (agent `elements.group` / `elements.ungroup`); moving or deleting one member moves/deletes the whole group. Models (D58) remain the repeated-unit tool. |
| 5. Input aids | Snapping (endpoint, midpoint, on element, grid) | **Done** |  |
| 5. Input aids | Ortho / angle steps | **Done** | 15° steps, Shift = ortho |
| 5. Input aids | Typed lengths | **Done** |  |
| 5. Input aids | Typed angles | **Done** | D89: the tracker's angle box (`<`), locks the direction |
| 5. Input aids | Coordinate input (absolute and relative x, y; polar) | **Done** | D89: tracker beside the cursor in every point tool; Tab between boxes, `a`/`#` absolute |
| 5. Input aids | Guide lines, temporary references, inference lines | **Deferred** | Core done; remainder deferred. D89: temporary guides (rest 0.5 s on a snap point), extensions and parallels; no dragged or permanent guide lines |
| 5. Input aids | Snap to perpendicular, tangent, intersection, wall faces | **Done** | D89 intersections and parallels; D188 tangent snapping from the previous point to drafting circles/arcs (`snap_data.circles` + `Snap::Tangent`); wall-face snapping is the dimension option. |
| 5. Input aids | Work planes (custom drawing planes) | **Deferred** | Core done; remainder deferred. Free horizontal work plane at a user height independent of the active level: `work_plane` / `set_work_plane` in the bridge, kept in project settings (height, enabled, angle), and the viewport uses it for drawing/snapping when enabled. View > *Free work plane...* sets the height, View > *Work plane rotation...* rotates the pl... |
| 5. Input aids | Tool presets / favourites (saved tool settings) | **Done** | D97: the Favourites button in the tool strip, kept in the project |
| 6. Building elements | Walls: straight, layered, L/T joins | **Done** |  |
| 6. Building elements | Walls: curved | **Done** | D97: Wall tool › Curved (3 points), layered, doors/windows, stretch, split, fillet, mitred joins with straight and curved walls |
| 6. Building elements | Walls: slanted, trapezoid, custom profile | **Done** | D97: slant angle, double slant, complex profiles (Model › Save shape as wall profile) |
| 6. Building elements | Wall flip, reference line (core / face) | **Done** | D97: six reference lines (outside face default), Model › Flip walls |
| 6. Building elements | Junction priorities (which layers run through) | **Done** | D97: building-material priority → `IfcMaterialLayer.Priority`, used by the wall regenerator; Model › Wall junctions overrides per wall |
| 6. Building elements | Wall attached to a slab or roof above | **Done** | D97: top linked to the level above (Properties › Geometry › Top link); D164 adds *Slab or roof above*, which follows the underside of the lowest slab/roof over the wall; Model › Trim walls to roof. |
| 6. Building elements | Slabs by outline or from walls | **Done** |  |
| 6. Building elements | Slab openings | **Done** |  |
| 6. Building elements | Sloped slabs, slab edges | **Done** | D109: `elements.set_slab_slope` tilts a slab about its local X/Y (rise over run; 0 returns flat, base kept in `KIMBIM_Slab`) and `create.slab_edge` adds `IfcMember` edges around a slab. D168 adds slope X/Y and an Edge checkbox to the Slab tool strip, applied to each new slab. |
| 6. Building elements | Doors and windows in walls (parametric) | **Done** | Basic types |
| 6. Building elements | Door/window variety: sliding, double, corner window, skylight, storefront | **Deferred** | Core done; remainder deferred. D97: double, sliding, double sliding doors; two- and three-panel windows; no corner windows, skylights or storefronts |
| 6. Building elements | Door swing and window symbols in plan | **Done** | Door leaves and swing arcs in plan drawings (drawgen.door_swings) |
| 6. Building elements | Generic opening (wall or slab hole without a filling) | **Done** | D157: Model > *Wall opening...* cuts a rectangular hole through a selected wall with no door or window filling it (along, width, height, sill); slab holes are `add_slab_opening`; agent `create.wall_opening`. |
| 6. Building elements | Columns, beams from profiles | **Done** |  |
| 6. Building elements | Slanted, tapered, segmented columns and beams | **Deferred** |  |
| 6. Building elements | Grids | **Done** | D98: Grid system (numbered and lettered axes at once) |
| 6. Building elements | Stairs: straight flight | **Done** |  |
| 6. Building elements | Stairs: landings, L/U shapes, spiral, by sketch | **Deferred** | Core done; remainder deferred. D88: L, U, by sketch with landings, risers from the height, code warnings, floor opening, plan symbol; no winders or spiral yet |
| 6. Building elements | Railings | **Done** | D88: on a stair or ramp's sides (they follow it) or by path; posts, top rail, balusters |
| 6. Building elements | Ramps | **Done** | D88: straight and L, slope with a 1:12 warning, plan arrow |
| 6. Building elements | Roofs: flat | **Done** | Slice 19 (D66) |
| 6. Building elements | Roofs: pitched, hip, gable, multi-plane, by footprint | **Done** | Slice 19 (D66): shed, gable, hip, a slope per edge; walls trimmed to the roof |
| 6. Building elements | Shell / free-form roof | **Deferred** |  |
| 6. Building elements | Curtain walls (grids, mullions, panels) | **Done** | D109/D116/D126/D169/D170: curtain wall with mullions and rails, settings dialog, per-bay Glass/Solid/Open panels with their own thickness, a panel building material, and copy-to-all/move-bay panel commands. |
| 6. Building elements | Ceilings | **Done** | D156: Model > *Ceiling...* makes an `IfcCovering` (CEILING) over a selected slab or a closed loop of walls, or a drawn outline; underside at level + offset (default 2.7 m), thickness default 20 cm, `KIMBIM_Ceiling`, one undo step. |
| 6. Building elements | Zones / rooms / spaces (auto from walls, area, name, number) | **Done** | Slice 18 (D65): Room tool (Z), stamps, room schedule |
| 6. Building elements | Area plans (gross, rentable) | **Done** | D182: File > *Area plan...* shows the level's gross area (rooms' union or slab footprint) and rentable area (sum of rooms), with each room's area (`area_plan`, agent `areas.plan`). |
| 6. Building elements | Generic object (extrusion, revolve, mesh import) | **Deferred** | Core done; remainder deferred. D120: File > *Import mesh...* brings OBJ, ASCII/binary STL and ASCII PLY as `IfcBuildingElementProxy` bodies (scale/rotation/position); extrusion/revolve authoring is still part of the parametric object system ([16](16-parametric-objects.md)) |
| 6. Building elements | Morph / free-form modelling, push/pull | **Deferred** | Massing and odd shapes |
| 6. Building elements | Conceptual massing with floor areas | **Deferred** |  |
| 6. Building elements | Models / modules placed on several levels | **Done** | D58 (Archicad Hotlinked Modules, Revit Groups) |
| 7. Site | Terrain from survey points or contours | **Done** | D114: Model > Terrain... (points or contour polylines, spacing; IFC4 `IfcGeographicElement`/`IfcTriangulatedFaceSet`, IFC2X3 shell model); D116: Model > *Building pad...* flattens a polygon and restores the base mesh; agent tools. No interactive point tool yet |
| 7. Site | Building pad / cut-and-fill | **Done** | D116 flattens a polygonal terrain part to an elevation and stores/clears pads; D178 adds the automatic cut and fill volumes (m³) per pad against the pre-pad surface (`pad_cut_fill`, agent `terrain.pad_volumes`), shown in the dialog's status line. |
| 7. Site | Hardscape, paths, parking | **Done** | D194: bundled *Paving*, *Path* and *Parking space* objects in the site category (IFC geographic/proxy types, thin box bodies and plan symbols); hardscape areas are placed and edited like any library object |
| 7. Site | Plants and landscape | **Done** | D192: bundled *Shrub* and *Hedge* objects in the site category (tree was already there), with IFC geographic/proxy types, body and plan symbol; plant objects place on any level like the rest of the library |
| 7. Site | North direction, sun study | **Done** | D87: north arrow from IFC TrueNorth; D96: View › Sun... by place, date and time; no animation (§16) |
| 8. Objects and libraries | Library browser (thumbnails, search, categories) | **Done** | D86: Library panel |
| 8. Objects and libraries | Bundled library: furniture, sanitary, kitchen, lighting, people, trees, cars | **Done** | D86/D99: 23 objects as `.kimobj`, a material per part (D97); the chair fully customisable; D167 adds a *Lighting* category with floor and table lamps (IfcLightFixtureType). |
| 8. Objects and libraries | Place a library object | **Done** | D86: Object tool (Shift+O), Tab turns |
| 8. Objects and libraries | Object settings dialog with live preview; place or edit a placed object | **Done** | D100: Library panel right click, Properties *Edit...*; modify all or create a new type |
| 8. Objects and libraries | Saved object versions (project types, shared through the office library, quick switcher, last used) | **Done** | D100: `kimbim-versions.ifc` in the office folder; a click places the last version, a right click in the Object tool switches |
| 8. Objects and libraries | Parametric object authoring | **Done** | D99: `.kimobj` definitions (parameters, formulas, parts, anchors, repeats, variants), stored on their types; D101: the Object Editor (new objects, edit office and project objects, *Customise a copy* of bundled or placed ones, save to the project or the office library). Archicad GDL, Revit Family Editor, Vectorworks plug-in objects. Design: [16](16-paramet... |
| 8. Objects and libraries | Office libraries (shared folder or repo) | **Done** | D99: a configured folder of `.kimobj` files and IFC type files, listed, placed and versioned; a git repo is a normal folder synchronized by git. Tested by `tests/python/test_library.py::test_office_library_kimobj_and_ifc_types`. |
| 8. Objects and libraries | Online object catalogues (BIMobject and others) | **Deferred** |  |
| 8. Objects and libraries | Paste between projects (with types and materials) | **Done** | D193: Ctrl+C records the source project; Ctrl+V in another project appends the elements with their types, materials, properties and geometry through `project.append_asset`, places them on the active level at their plan position and level height, and undoes in one step |
| 9. Organising the model | Layers (shown, locked, active) | **Done** | D57 |
| 9. Organising the model | Layer combinations / view templates | **Done** | D73 layer combinations/purposes and saved-view layer states; D186 adds named view templates (layer state, drawing scale, purpose) saved and applied from View › View templates, deletable. |
| 9. Organising the model | Graphic overrides / view filters (rules by property) | **Done** | D73: override rules by property, class, kind, layer, material, chosen per purpose |
| 9. Organising the model | Classifications (Uniclass, OmniClass, local) | **Done** | D106: Model › Classifications..., `IfcClassificationReference` assignment, `classifications.*` bridge/CLI tools; shipped system metadata (Uniclass 2015, OmniClass, Local), codes typed by the office |
| 9. Organising the model | Element types: assign, edit type, update all | **Done** | D50 type values and overrides; D106 type manager (Model › Type manager...): list, create from selection, assign, edit name/description/tag and properties, update all removes overrides |
| 9. Organising the model | Property editing, psets, bulk edit | **Done** |  |
| 9. Organising the model | Dimensions group (length, height… edits the shape) | **Done** |  |
| 9. Organising the model | Expression / calculated properties | **Done** | D181: schedule fields with `source: formula` evaluate a safe expression over the row's earlier fields (`{quantity:volume} * 2`; numbers, + - * / // % **, min, max, round, abs), added with the schedule editor's *Formula...* button. |
| 9. Organising the model | Renovation status (existing / demolish / new) and filters | **Done** | D74: Archicad statuses, renovation filters in purposes, legends; Revit phases not done |
| 9. Organising the model | Design options | **Done** | KimBim uses branches (D56); Archicad and Revit store options inside one file |
| 10. Attributes and graphics standards | Layered (composite) wall and slab types | **Done** |  |
| 10. Attributes and graphics standards | Material editor (cut fill, surface, physical data) | **Done** | D96: Graphics › Building materials / Surfaces / Composites; IFC materials, styles and psets |
| 10. Attributes and graphics standards | Pen sets / line weights by scale | **Done** | D73 pen sets, element styles and purposes; the pen keeps its paper weight at any drawing or placed scale (the sheet divides by its scaling factor), tested by `tests/python/test_sheets.py::test_sheet_weights_do_not_scale`. |
| 10. Attributes and graphics standards | Graphic overrides and model view options (visibility by kind, rules) | **Done** | D73: visibility sets, override rules (property, layer, material), layer combinations in purposes. D138: model view options hide small furnishings at coarse drawing scales |
| 10. Attributes and graphics standards | Line types and fill patterns (hatches) | **Done** | D73: line types (dash patterns in mm); D84: fill patterns; D96: cut fills hatched on screen, in print and DXF |
| 10. Attributes and graphics standards | Surfaces / textures for 3D and rendering | **Done** | D96: surfaces (colour, transparency, shine, picture texture, box-mapped) per face in 3D, per-side overrides (D97); no rendering |
| 10. Attributes and graphics standards | Attribute manager (import/export standards between projects) | **Done** | D121: Graphics > *Attribute manager...* exports/imports pens, line types, fills, styles, purposes, layers, materials, surfaces and composites (merge or replace, group selection) |
| 11. Drawings (views made from the model) | Floor plan drawings (one per story, cut plane, symbols) | **Done** | Slice 15: cut at 1.10 m (Archicad), door swings, window glass, annotations and markers drawn on |
| 11. Drawings (views made from the model) | Section views (marker in plan, linked view) | **Done** | Slice 14: Section tool (V), Archicad's three clicks; D110: Line, Polyline (bent) and Curve markers, unfolded strip by strip, and oblique tilt; D138 scale and detail level; D190 the drawing scale in generation and a hand crop (View > *Crop drawing...*). SVG from IfcOpenShell's serializer, in a tab (D60, D61) |
| 11. Drawings (views made from the model) | Elevations (building, interior) | **Done** | Template N/S/E/W elevations, *Create elevations*, Elevation tool (Shift+V); D173 adds the depth choice to the tool strip (infinite, cut only or a limited depth, the last being an interior elevation). |
| 11. Drawings (views made from the model) | Detail views (enlarged, cropped, with extra 2D) | **Done** | D98: worksheets (independent 2D, figures, on sheets); D112: linked detail drawings (region, 1:20 default, plan marker, sheet placement); D116: the View palette Detail tool draws the region and scale. No extra 2D on the detail yet |
| 11. Drawings (views made from the model) | Drafting views (2D only) | **Done** | D98: worksheets |
| 11. Drawings (views made from the model) | 3D documents / axonometric drawings | **Done** | D137: View > *3D document...* makes an orthographic axonometric from the active 3D view's direction and screen up, with hidden-line removal from the app's meshes; the camera is stored with the drawing, so it regenerates when the model changes and places on sheets like any drawing |
| 11. Drawings (views made from the model) | Crop regions, view range, depth | **Done** | D61 depth, D134 crop region with four clipping planes (and Clear), D136 per-view cut height/bottom limit, D138 model view options by scale; generated plans/details already use the per-view depth (view → level → project) in the generation job and camera, tested by `tests/python/test_drawings.py`. |
| 11. Drawings (views made from the model) | Model view options (detail level by scale) | **Done** | D138: every drawing has a scale (1–1000); at 1:200 and coarser the project's `model_view_options.coarse_hidden_classes` (default furniture, furnishings, sanitary and appliances) are left out of plans, sections, elevations and 3D documents. Finer drawings keep everything; the table is a versioned project setting |
| 11. Drawings (views made from the model) | Drawings update when the model changes | **Done** | Every edit marks the affected drawings stale; the out-of-date bar offers *Regenerate* and a drawing regenerates when brought to the front. `tests/python/test_drawings.py::test_editing_a_wall_makes_drawings_stale_and_regenerating_shows_it` checks stale → regenerate → undo. |
| 12. 2D drafting | Lines, polylines, arcs, circles, splines | **Done** | D84: line, polyline, arc/circle, rectangle; D98: splines; snaps, typed lengths, grips; in plans, drawings, sheets, DXF |
| 12. 2D drafting | Fills / hatches (regions) | **Done** | D84: IfcAnnotationFillArea + IfcFillAreaStyleHatching; pattern table in project settings; pens fg/bg; area label; magic wand (Alt+click) |
| 12. 2D drafting | 2D symbols / blocks | **Deferred** |  |
| 12. 2D drafting | Detail components (repeating patterns such as insulation, brick) | **Deferred** |  |
| 12. 2D drafting | Image and PDF underlays (trace over a scan) | **Done** | D85: PDF page (pypdfium2) or PNG/JPEG on a level at 1:N, calibrated by two points; opacity, greyscale, tint, layer, lock, also in 3D; stored in the project and its versions |
| 13. Annotation | Text labels | **Done** | Screen-sized; paper-unit size is open (doc 13) |
| 13. Annotation | Linear dimension (two points) | **Done** |  |
| 13. Annotation | Marks (circle with a tag) | **Done** |  |
| 13. Annotation | Dimension chains, overall dimensions | **Done** | D158: Slice 15 chains (Shift+click); Model > *Overall dimension...* adds one dimension across the selected elements' combined bounds on X, Y or the longer side, offset outside; agent `annotation.overall_dimension`. |
| 13. Annotation | Snap dimensions to wall faces, openings and layers | **Done** | Slice 15 wall faces; D179 adds door/window jambs and wall layer boundary points at both wall ends to `snap_data`, so dimensions and the other drawing tools snap to openings and layer lines. |
| 13. Annotation | Automatic dimensioning of walls and openings | **Done** | D98: Model › *Dimension selected walls* (a chain per straight wall: ends and openings); D158 adds the selection's overall dimension; D166 adds *Dimension grid* (a chain between the level's grid axes, offset outside). |
| 13. Annotation | Angle, radius, arc-length, level and spot-elevation dimensions | **Done** | D87: angle, radius, diameter, level and spot elevation; D161 adds the arc-length mode of the angle-dimension tool (start, a point on the arc, end, text point). |
| 13. Annotation | Associative labels and tags (show a property, follow the element) | **Done** | D87: Tag tool and Tag all; templates of schedule fields; styles (door/window marker, wall tag, room stamp, mark, label) in project settings; IfcRelAssignsToProduct |
| 13. Annotation | Leaders and arrows | **Done** | Slice 15: Leader tool (Shift+A) |
| 13. Annotation | Revision clouds | **Done** | D87: on plans and sheets, revision in a triangle; no revision schedule yet |
| 13. Annotation | Section, elevation and detail markers | **Done** | Section and elevation markers in plan (Slice 14); D112: detail markers (bubble, leader, linked drawing) |
| 13. Annotation | North arrow, scale bar | **Done** | D87: on plans and sheets; north follows IFC TrueNorth; the sheet's bar shows its drawing's scale |
| 13. Annotation | Keynotes | **Done** | D122: Model > *Keynotes...* table (code/text/category), `place_keynote` with optional leader, and refresh of placed keynotes from the table |
| 13. Annotation | Room / zone stamps (name, number, area) | **Done** | Slice 18; D87: their text is the Room stamp tag style |
| 14. Sheets and output | Sheets / layouts with drawings placed at scale | **Done** | Slice 16 (M4 exit): A1/A3, numbered, drag to place (D62) |
| 14. Sheets and output | Title blocks filled from project data | **Done** | Slice 16: a built-in title block; D118: title block templates / master layouts (position, field overrides and paper in project settings; save, apply, rename, delete) |
| 14. Sheets and output | Drawing and sheet lists (auto-numbered) | **Done** | D112: Sheets › Place drawing list / Place sheet list (natural sort, live from the project; dragged and removed like drawings) |
| 14. Sheets and output | Revisions / issue management | **Done** | D171: Project > *New revision...* stores revision records (`revisions` setting: code, date, description); a sheet's revision is set in its title block (*Revision:* field) and prints in the title block. Versions and milestones remain the history tools. |
| 14. Sheets and output | Print, PDF export | **Done** | Slice 16: PDF and SVG per sheet (Qt, vector) |
| 14. Sheets and output | Batch publishing (sets of sheets to PDF/DWG) | **Done** | Export all sheets as PDF (one per sheet), headless `--export-sheets`, and DXF/DWG batch export are in; D172 adds *Publish sheet set...* with named sheet subsets (`sheet_sets`/`save_sheet_set`/`delete_sheet_set`). DWG needs LibreDWG installed (DXF always works). |
| 14. Sheets and output | DWG/DXF export | **Done** | D83 DXF export (model space and paper-space sheets); D180: DWG through LibreDWG when installed, verified by `tests/python/test_batch_dwg.py` (two sheets, DWG headers). DXF always works. |
| 15. Schedules and quantities | Element schedules (doors, windows, walls), editable | **Done** | D77: built-in and custom schemes, rows select elements, Name/Mark/property cells edit the model (one undo step) |
| 15. Schedules and quantities | Room / area schedules | **Done** | D77: the Rooms schedule (every IfcSpace) |
| 15. Schedules and quantities | Material take-off, quantities (area, volume, length) | **Done** | D77 quantities plus D96's *Building materials* take-off: one row per material layer (material, thickness, area, volume, count), tested by `tests/python/test_materials.py::test_material_takeoff_schedule`. |
| 15. Schedules and quantities | Schedule on a sheet | **Done** | D112: Sheets › Place schedule... (scheme, width, merge; vector table in PDF/SVG) |
| 15. Schedules and quantities | Export to CSV / XLSX | **Done** | D77 (openpyxl) |
| 15. Schedules and quantities | Cost estimating (5D) | **Deferred** | Bonsai has it |
| 15. Schedules and quantities | Construction sequencing (4D) | **Deferred** | Bonsai has it |
| 16. Visualisation | Real-time textured 3D | **Done** | D96: surface pictures box-mapped; drawn defaults for brick, timber, tiles, stone, roof tiles |
| 16. Visualisation | Photorealistic rendering | **Done** | D146 image export, D147 ray tracing, D149 path tracing. Offline CPU render farm is future. |
| 16. Visualisation | AI visualiser (sketch to image) | **Deferred** |  |
| 16. Visualisation | Sun / shadow studies, animations | **Deferred** | Core done; remainder deferred. D96: sun shadows for a place, date and time; no animations |
| 16. Visualisation | Walkthrough video, VR | **Blocked** | OpenXR SDK is available, but there is no runtime/headset in the environment; deferred (docs/20-vr-feasibility.md). |
| 17. Collaboration and versions | Save version, History, Compare (colours and list) | **Done** | KimBim's own feature (Slice 8). Competitors have backups and Revit compare add-ins at most. D105: property-level attributes and properties, categories and the level tree in `versions diff --detail` (JSON or text) |
| 17. Collaboration and versions | Milestones, object history, before/after | **Done** | Slice 20 (M5) |
| 17. Collaboration and versions | Combine options with conflict UI | **Done** | Slice 22 (D69), M5 exit |
| 17. Collaboration and versions | Several people on one project (Teamwork, Worksharing, Project Sharing) | **Deferred** | Git remotes first ([08](08-future.md)) |
| 17. Collaboration and versions | External references (link another IFC/project, hotlinks, xrefs) | **Done** | Links, live refresh, editable copies, copy/monitor, attribute/property/geometry sync are done. D151 pushes host edits back to the source IFC; the read-only proxy remains a reference. |
| 17. Collaboration and versions | Copy / monitor linked elements | **Done** | D141 explode, D142 sync/conflicts, D143 geometry sync, D151 push-back to source. |
| 17. Collaboration and versions | BCF issues (import, export, viewpoints) | **Done** | D113: Model > Issues... (topics, status, priority, assignee, comments, viewpoint from the selection; BCF 2.1 import/export, merged by topic GUID); D119: *Show viewpoint* restores the camera and selects the components |
| 17. Collaboration and versions | Markups and comments in the model | **Done** | D113 BCF 2.1 issues with viewpoints (camera + selected components), threaded comments and import/export (Issues dialog); D87 in-model revision clouds and text markups. `tests/python/test_bcf.py` checks the exports with bcf-client. |
| 17. Collaboration and versions | Cloud sharing with clients (web viewer) | **Deferred** | [08](08-future.md) |
| 18. Interoperability | IFC export, valid against the schema | **Done** | Checked in CI: IfcOpenShell validator (schema + EXPRESS rules), web-ifc geometry and the independent xBIM .NET parser (`pixi run interop`, `pixi run interop-xbim`) |
| 18. Interoperability | IFC export settings (what to export, property mapping) | **Done** | D117: File > *Export IFC...* (all, selection, levels or classes; annotations/spaces/openings; property renames) through `ifcexport.export_ifc` |
| 18. Interoperability | Re-import with reconciliation report | **Done** | D104: `kimbim versions import` matches by GlobalId, Tag, then a reviewed heuristic; dry run and JSON report |
| 18. Interoperability | DWG/DXF import (underlay and convert) | **Deferred** | Core done; remainder deferred. D85: DXF as an underlay (units, exploded blocks, snapping to ends, midpoints, crossings). No DWG yet, no convert to 2D elements. Architects receive most survey and consultant data as DWG |
| 18. Interoperability | PDF import | **Deferred** | Core done; remainder deferred. D85: a PDF page as an underlay (an image); D132: a PDF can be placed as **vector linework** (PyMuPDF paths, selectable/snappable, no text) instead of a rendered page |
| 18. Interoperability | SketchUp, Rhino, OBJ, FBX import | **Blocked** | OBJ/STL/PLY, COLLADA, glTF/GLB and ASCII/binary FBX are done; SketchUp `.skp` needs Trimble's proprietary SDK. |
| 18. Interoperability | Point clouds | **Done** | D125 XYZ/PTS/CSV/LAS, D132 LAZ, D148 E57. |
| 18. Interoperability | Rhino / Grasshopper live link | **Deferred** |  |
| 19. Analysis and checking | Measure distance, angle, area | **Done** | D79: Shift+M, snaps, 3D surfaces, copy to clipboard |
| 19. Analysis and checking | IFC schema validation in the app | **Done** | Checks panel, EXPRESS rules included (D81) |
| 19. Analysis and checking | IDS checks | **Done** | IfcTester; IDS files kept in the project; HTML/JSON report (D81) |
| 19. Analysis and checking | Clash detection | **Done** | Hard and clearance between classes or Find & Select criteria (D81); no BCF yet |
| 19. Analysis and checking | Model checks (duplicates, overlaps, rooms without a number) | **Done** | Duplicates, rooms, zero-length walls, not on a level, hostless openings (D81) |
| 19. Analysis and checking | Energy evaluation, daylight | **Deferred** |  |
| 19. Analysis and checking | Structural analytical model | **Deferred** | Probably out of scope for architects |
| 20. Automation and customisation | Python console with the model API | **Done** | D82: Console panel, `edit()` as one undo step, Stop; [15](15-scripting.md) |
| 20. Automation and customisation | Visual programming | **Deferred** | Grasshopper, Dynamo, Marionette |
| 20. Automation and customisation | Plugins / add-ons | **Deferred** |  |
| 20. Automation and customisation | Customisable shortcuts, toolbars and workspaces | **Done** | Help › *Keyboard shortcuts* lists, rebinds and resets keys (per user); View › *Workspaces* saves and reapplies panel layouts (D131); View › *Toolbars* shows/hides and remembers them (D135). `test_shortcuts.cpp` and `test_preferences.cpp` verify all three. |
| 20. Automation and customisation | UI languages | **Done** | English and Spanish |
| 20. Automation and customisation | AI assistant | **Deferred** | [08](08-future.md) |
