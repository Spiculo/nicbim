<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# 17 — Agent tools: the in-app Assistant, the `kimbim` command line and MCP server

An AI agent (Claude, opencode, or any program that speaks MCP) can read, picture and change a NicBim project for
you. You ask *"make every window on the first floor 50 cm wider"*, the agent does it in seconds, and you review the
result in NicBim before anything reaches your model (decision D102,
[spec](superpowers/specs/2026-10-25-agent-tools-design.md)).

The same set of tools is available three ways. The **Assistant panel** inside the app is the main one; the other two
are optional transports for the same catalogue.

- **The Assistant panel** inside the app (View › Panels › Assistant), using your own model provider and API key. It
  loads the whole catalogue, so a new tool needs no setup to appear there.
- **`kimbim`**, a command line, for agents that run shell commands and for you. `kimbim elements find --elements
  '{"kind": "window"}'` is the same call as the MCP tool `elements_find`.
- **`kimbim mcp`**, an optional MCP server. Claude Desktop, Claude Code and opencode connect to it and see the
  tools; not required to add tooling or to use the Assistant.

Agents work **live**, while the project is open in NicBim, or **offline**, with the app closed. In live mode the
app hosts a local session: each write is one undo step, the views redraw, and a review bar lists finished agent
proposals. In offline mode a background worker keeps the project open between commands.

## What an agent can do

- **Read** the project: levels, element counts, settings, any element's type, dimensions, properties, host and
  openings, the drawings, sheets and schedules, the saved versions and design options.
- **Look** at it: a picture of the model in 3D, a floor plan, a section or elevation, any drawing or a sheet, drawn
  by NicBim itself, so it looks like what you see in the app. The picture can colour what the agent changed.
- **Change** it: resize doors and windows, move, rotate, copy, mirror, array, offset, fillet, scale, stretch, split,
  trim, join, rename and delete elements, edit slab outlines, set properties, layers and renovation status, add walls,
  slabs, columns, beams, doors, windows and rooms, place and adjust library objects, add levels, drawings and sheets.
- **Produce** outputs: export drawings (SVG, DXF), sheets (PDF, SVG, DXF), schedules (CSV) and versions (IFC), and
  run the model checks (schema, IDS, clash, model).

Agents never click in the app and never see your screen. Everything goes through these tools.

## Connecting an agent

`kimbim setup` writes the agent's configuration for you. It merges its entry into the existing file and keeps your
other servers and settings. In development, run it as `pixi run kimbim ...`.

| Agent | Command | What it writes |
|-------|---------|----------------|
| Claude Desktop | `kimbim setup claude-desktop` | `claude_desktop_config.json` (in `%APPDATA%\Claude` on Windows) |
| Claude Code | `kimbim setup claude-code --project house.nic` | `.mcp.json` and a short NicBim section in `CLAUDE.md`, in the project's folder |
| opencode | `kimbim setup opencode --project house.nic` | `opencode.json` and a short NicBim section in `AGENTS.md`, in the project's folder |

- With `--project`, the server always works on that project. Without it, the agent names the project in every call.
- `--print` shows the configuration instead of writing it. For Claude Code it prints the `claude mcp add` line.
- The section in `CLAUDE.md` or `AGENTS.md` tells the agent that the `kimbim` command line exists and how to use
  tasks. It sits between `<!-- kimbim:start -->` and `<!-- kimbim:end -->`, and running setup again replaces it
  instead of adding a second copy. Your own text in the file is kept.
- Restart the agent (or reload its MCP servers) after running setup.
- In the app, *Help › Connect an AI agent...* shows the same configuration with a Copy button.

The app starts its live server when a project finishes loading. While it runs, the status bar shows
*Agent: live* with a *Disconnect* button; disconnecting stops accepting commands for that window. The server is
not started for the windowless snapshot helper.

## Tasks and review

Every change an agent makes belongs to a **task**, such as *"Widen first-floor windows"*.

1. The agent starts the task (`task_start` with a title). NicBim creates a **design option** named
   `agent/widen-first-floor-windows` from your latest version. If your project has unsaved changes, NicBim first
   saves them as a version called *Before agent: Widen first-floor windows*, so the agent starts from what you see.
2. The agent makes its changes. They go into the option, never into your option.
3. The agent finishes the task (`task_finish` with a summary). The option gets one new version, authored by
   *"<agent> (agent)"*, with the title and the summary as its message. The task is now *ready for review*.

A write tool called without a task starts one on its own, so nothing skips review.

**Reviewing.** The app lists finished proposals in a bar above the status strip: *"Agent proposal: Widen first-floor
windows (4 changed)"* with **Review**, **Accept** and **Reject**.

| To | Do this |
|----|---------|
| See the proposal | **Review** opens the proposal window on the base option: **Changes** lists every added, modified and removed element and shows the selected element field by field (base vs agent, changed fields highlighted); **Conflicts** shows the common version, the base option and the agent option side by side, with a choice per conflict. *Show in 3D* selects the element in the view |
| Accept it | **Accept** combines the option into its base option, saves the combined version and deletes the agent option. If both sides changed the same property, the proposal window's **Conflicts** tab asks which value to keep before Accept is enabled |
| Reject it | **Reject** deletes the agent option and leaves your model unchanged |

The bar reads the project's ready task files even when the live agent session could not start (for example a
read-only window), so a waiting proposal is never invisible. Review/Accept/Reject try to start the session on
demand and say why if they cannot.

The same review works offline: open the project and the proposal appears. You can also use *Versions › Design
options*, *Combine options...* and *Delete option...* by hand. Agents cannot accept, combine or delete options, and
they cannot change the review rules below.

Compare reports only the elements whose content changed (since the fix of 2026-10-26, see
[03](03-versioning.md#diff-compare)). Widening four windows shows those four windows and their wall openings, not
every element that shares a placement with them.

## Settings only you can change

Two project settings decide how much freedom agents have. Agents can read them, but `project_set_settings` refuses
to change them.

| Setting | Values | Default |
|---------|--------|---------|
| `agent_changes` | `option`: changes go into a design option for review. `direct`: changes go straight into your model, and finishing the task saves them as a version *"<title> (agent)"*, so the version before it is your way back. `agent_decides`: the agent picks per task, option unless it asks for direct | `option` |
| `agent_scripts` | `true` lets agents run Python scripts in the project (`script_run`), like the [console](15-scripting.md) | `false` |

There is no dialog for them yet. Set them in the Python console, then save the project (Ctrl+S):

```python
import kimbim.settings
kimbim.settings.set_project_settings('{"agent_scripts": true}')
```

## Snapshots

`snapshot_take` returns a picture (PNG) to the agent, and the file's path. Over MCP the picture is part of the
answer, so the agent sees it right away. Every field is optional:

| Field | What it does | Default |
|-------|--------------|---------|
| `view` | `3d`, `plan`, `section`, `elevation`, `drawing` or `sheet` | `3d` |
| `level`, `drawing`, `sheet` | Which plan, drawing or sheet | The lowest level, the first drawing or sheet |
| `elements`, `isolate`, `highlight` | Frame on some elements, show only them, or draw some in a highlight colour | The whole model |
| `changes` | `task` colours what the open task changed, like Compare. `{rev_a, rev_b}` compares two versions | None |
| `camera`, `style`, `purpose`, `cut` | 3D camera (a view cube preset or eye and target), style (`shaded`, `white`, `lines`, `textured`), pen set, horizontal cut height | `iso-se` framed on the target, `shaded`, the project's pen set, no cut |
| `size` | Picture size in pixels | 1024 × 768 |
| `format` | `png`, or `svg` for drawings and sheets | `png` |

3D pictures come from the app's own renderer, started without a window. Plans, sections, elevations and sheets
come from the same drawing generator as the *Drawings* tab. The first 3D picture of a session takes a few seconds
longer while the renderer starts. An SVG snapshot is returned as text, not as an image, because many MCP clients do
not display `image/svg+xml`.

## The Assistant panel

*View › Panels › Assistant* docks a chat with the model. It uses the same tools and the same live session as an
external agent, so its changes are undo steps and its tasks appear in the review bar.

Set the provider in *Edit › Preferences › Assistant*: **Anthropic**, or **OpenAI-compatible** (a base URL and a
model name, which covers OpenRouter, DeepSeek, Ollama and similar). The API key is stored in the operating system's
credential store, never in `preferences.json` or the project. The panel sends the current selection and view, and
the current project state (option, recent versions, element counts, unsaved changes) plus a "since your previous
answer" delta, so the model knows the project changed between messages. Tool calls appear as compact lines and
snapshots inline.

The conversation is a **stored session** (D111, [18](18-agent-tools-and-sessions.md#4-sessions)): the picker at
the top lists the project's sessions with *New*, *Rename...*, *Fork*, *Archive* and *Delete...*. *Clear* starts a
new session; the old one stays in the list. The transcript lives in the app's data folder, not in the project. A
versioned folder project gets its own worktree per session, so the Assistant and the architect never write the same
working state; a `.nic`/IFC session uses the app's live document (one at a time). The agent's task and design
option stay in the project, and accepting or rejecting the proposal ends the session.

From the command line, `kimbim sessions list|new|show|rename|archive|delete|fork` manages them, and
`--session ID` (or `$KIMBIM_SESSION`) runs a tool command in one; `kimbim mcp --session ID` does the same over MCP.

## The tools

Tools are named `group_verb` over MCP and `kimbim group verb` on the command line (underscores become hyphens).
`kimbim <group> <verb> --help` lists a tool's parameters. Every write tool also takes `dry_run`: it reports what
would change and changes nothing. This table is the output of `kimbim help --markdown`.

<!-- tools:start -->
| Tool (MCP) | Command line | What it does | Changes the model |
|---|---|---|---|
| `project_info` | `kimbim project info` | Describe the open project: name, schema, levels, element counts per kind, the current option and whether there are unsaved changes. |  |
| `project_set_settings` | `kimbim project set-settings` | Change project settings (units, decimals, display options...) as one undo step. | yes |
| `project_settings` | `kimbim project settings` | Read the project settings (units, decimals, display options...), all or just the named keys. |  |
| `versions_create_option` | `kimbim versions create-option` | Create a design option from the current version and switch to it. | yes |
| `versions_diff` | `kimbim versions diff` | Compare two versions: the elements added, modified and removed from one to the other (WORKING is the open model with its unsaved changes); with detail, each modified element's attributes and properties. |  |
| `versions_element_history` | `kimbim versions element-history` | List the saved versions that changed an element, newest first. |  |
| `versions_export` | `kimbim versions export` | Write a version of the model as an IFC file (HEAD, the latest saved one, by default). |  |
| `versions_log` | `kimbim versions log` | List the saved versions of the current option, newest first: id, message, author, time, milestones. |  |
| `versions_milestone_create` | `kimbim versions milestone-create` | Tag the current version as a milestone. | yes |
| `versions_milestone_delete` | `kimbim versions milestone-delete` | Delete a milestone tag (the version stays). | yes |
| `versions_milestones` | `kimbim versions milestones` | List the milestones (named versions such as Concept or Schematic design). |  |
| `versions_options` | `kimbim versions options` | List the design options of the project and the current one. |  |
| `versions_save` | `kimbim versions save-version` | Save the open model as a new version in the current option (the pre-commit checks run first). | yes |
| `versions_switch_option` | `kimbim versions switch-option` | Switch the open model to another design option. |  |
| `task_abandon` | `kimbim task abandon` | Abandon the task: its changes are thrown away (its design option is deleted). |  |
| `task_finish` | `kimbim task finish` | Finish the task: save its changes as a version (on its option, ready for review, or in place in direct mode) and return what changed. |  |
| `task_start` | `kimbim task start` | Start a task: the changes that follow go in a design option agent/<title> for the architect to review (or straight into the model in direct mode). |  |
| `task_status` | `kimbim task status` | Show the open task (or the named one) with what it changed so far, and every task of the project. |  |
| `elements_align` | `kimbim elements align` | Align the selected elements on an axis at their min/max/center, to the selection or a reference. | yes |
| `elements_array` | `kimbim elements array` | Multiply elements: a linear row, a polar turn, or a rectangular grid of copies. | yes |
| `elements_copy` | `kimbim elements copy` | Copy elements, shifted by dx, dy, dz, optionally onto another level. | yes |
| `elements_copy_to_level` | `kimbim elements copy-to-level` | Copy elements to another level at the same plan position (walls bring their doors and windows). | yes |
| `elements_delete` | `kimbim elements delete` | Delete elements (and the doors/windows they host). | yes |
| `elements_fillet` | `kimbim elements fillet` | Round (fillet) or cut (chamfer) the corners of slabs, 2D polylines/fills, or two meeting walls. | yes |
| `elements_find` | `kimbim elements find` | Find elements and list them: GlobalId, label, kind and level, a page at a time. |  |
| `elements_get` | `kimbim elements get` | Describe elements in full: class, type, level, dimensions (metres), property sets, host and openings. |  |
| `elements_get_slab_outline` | `kimbim elements get-slab-outline` | A slab's outline points in world metres, for moving, adding or deleting corners. |  |
| `elements_get_slab_slope` | `kimbim elements get-slab-slope` | A slab's slope (rise over run). |  |
| `elements_group` | `kimbim elements group` | Group elements so moving or deleting one moves or deletes them all. | yes |
| `elements_join` | `kimbim elements join` | Join two walls (L or T) or merge two collinear walls or beams into the first. | yes |
| `elements_lock` | `kimbim elements lock` | Pin or unpin elements so they refuse moves, deletes and dimension edits. | yes |
| `elements_mirror` | `kimbim elements mirror` | Mirror elements across a line on the plan. | yes |
| `elements_move` | `kimbim elements move` | Move elements by dx, dy, dz. | yes |
| `elements_offset` | `kimbim elements offset` | Offset walls as a parallel copy and grow or shrink slabs in place (negative shrinks). | yes |
| `elements_remove_properties` | `kimbim elements remove-properties` | Remove properties from elements. | yes |
| `elements_rename` | `kimbim elements rename` | Give elements a name. | yes |
| `elements_resize` | `kimbim elements resize` | Scale elements about a point on the plan; thicknesses and heights stay. | yes |
| `elements_rotate` | `kimbim elements rotate` | Rotate elements around a point on the plan; joined walls follow. | yes |
| `elements_set_dimensions` | `kimbim elements set-dimensions` | Change dimensions of elements: width, height and sill of doors/windows, height or length of walls, columns and beams. | yes |
| `elements_set_layer` | `kimbim elements set-layer` | Move elements to a layer. | yes |
| `elements_set_properties` | `kimbim elements set-properties` | Set property values on elements, creating the property set when needed. | yes |
| `elements_set_slab_outline` | `kimbim elements set-slab-outline` | Give a slab a new outline (moving, adding or deleting corners); its thickness and level stay. | yes |
| `elements_set_slab_slope` | `kimbim elements set-slab-slope` | Tilt slabs: 0, 0 returns them to horizontal. | yes |
| `elements_set_status` | `kimbim elements set-status` | Set the renovation status of elements: existing, demolish, new, temporary or auxiliary. | yes |
| `elements_set_surface` | `kimbim elements set-surface` | Override the surface (3D colour and texture) of one side of the elements. | yes |
| `elements_set_wall_height` | `kimbim elements set-wall-height` | Set the height of one or more walls (one undo step). | yes |
| `elements_split` | `kimbim elements split` | Split a wall or beam at a point on its axis; doors and windows stay with the piece they are in. | yes |
| `elements_stretch` | `kimbim elements stretch` | Move one end of a wall to a point, stretching or shortening it; joins at that end are dropped. | yes |
| `elements_trim` | `kimbim elements trim` | Trim or extend a wall or beam to a boundary wall/beam or line, keeping the side the point is on. | yes |
| `elements_trim_corner` | `kimbim elements trim-corner` | Trim or extend two walls or beams to their corner, keeping the side each point is on. | yes |
| `elements_ungroup` | `kimbim elements ungroup` | Break the groups of the selected elements. | yes |
| `elements_unjoin` | `kimbim elements unjoin` | Break the joins between walls or beams (one element: all its joins), giving them plain ends. | yes |
| `create_beam` | `kimbim create beam` | Create a beam between two points on a level. | yes |
| `create_ceiling` | `kimbim create ceiling` | Create an IfcCovering CEILING over an outline at a height above a level. | yes |
| `create_ceiling_from_selection` | `kimbim create ceiling-from-selection` | Create a ceiling over a selected slab's outline or a closed loop of selected walls. | yes |
| `create_column` | `kimbim create column` | Create a column standing on a level. | yes |
| `create_curtain_panel` | `kimbim create curtain-panel` | Change one bay of a curtain wall: make it glass, an opaque solid panel, or open. | yes |
| `create_curtain_panel_copy` | `kimbim create curtain-panel-copy` | Copy one bay's kind and thickness to other bays. | yes |
| `create_curtain_panel_move` | `kimbim create curtain-panel-move` | Swap two bays' kind and thickness. | yes |
| `create_curtain_wall` | `kimbim create curtain-wall` | Create an IfcCurtainWall on a level, with its glazed panel and mullion spacing. | yes |
| `create_curtain_wall_info` | `kimbim create curtain-wall-info` | Read a curtain wall's settings and its bays (index, span, kind, thickness). |  |
| `create_grid` | `kimbim create grid` | Create a rectangular grid system from a corner, with both directions' spacings and labels. | yes |
| `create_grid_axis` | `kimbim create grid-axis` | Add one grid line to a level's grid (letters for the near-vertical, numbers for the others). | yes |
| `create_opening` | `kimbim create opening` | Put a door or window in a wall. | yes |
| `create_railing` | `kimbim create railing` | Create a railing along a path on a level. | yes |
| `create_ramp` | `kimbim create ramp` | Create a ramp rising from start towards end, straight or L, at a slope in percent. | yes |
| `create_roof` | `kimbim create roof` | Create a roof from an eaves outline: flat, shed, gable or hip, with its pitch and thickness. | yes |
| `create_room` | `kimbim create room` | Create a room filling the walled-in space around a point. | yes |
| `create_slab` | `kimbim create slab` | Create a slab on a level from an outline or from a closed loop of walls (the outline follows their outer faces). | yes |
| `create_slab_edge` | `kimbim create slab-edge` | Add a raised edge around a slab, one IfcMember per side. | yes |
| `create_slab_opening` | `kimbim create slab-opening` | Cut a hole through a slab with the given outline. | yes |
| `create_stair` | `kimbim create stair` | Create a stair climbing from start towards end, with landings for L/U or along a walking line. | yes |
| `create_types` | `kimbim create types` | List the types you can create of a kind: GlobalId, name and size (wall thickness, default door/window sizes). |  |
| `create_update_curtain_wall` | `kimbim create update-curtain-wall` | Change a curtain wall's height, mullion spacing or panel thickness and rebuild its members. | yes |
| `create_wall` | `kimbim create wall` | Create a straight wall on a level. | yes |
| `create_wall_opening` | `kimbim create wall-opening` | Cut a rectangular hole through a wall without a door or window filling it. | yes |
| `objects_assign_version` | `kimbim objects assign-version` | Move placed library objects to a saved version. | yes |
| `objects_check_draft` | `kimbim objects check-draft` | Check a parametric object definition without saving it: every error with the field it is in. |  |
| `objects_library` | `kimbim objects library` | List the library objects (furniture, sanitary, kitchen...): id, name, category, IFC class, size (metres) and parameters with their kind, default and limits. |  |
| `objects_place` | `kimbim objects place` | Place a library object on a level, optionally standing on the slab under it or fitted against a wall. | yes |
| `objects_place_picture` | `kimbim objects place-picture` | Place a picture standing in the 3D model (Archicad's Picture object): a thin panel showing a PNG or JPEG, e.g. | yes |
| `objects_save_draft` | `kimbim objects save-draft` | Save a parametric object definition into the project's library; place it with objects.place. | yes |
| `objects_set_parameters` | `kimbim objects set-parameters` | Change parameters of placed library objects. | yes |
| `objects_update_from_library` | `kimbim objects update-from-library` | Regenerate placed objects from the library's current definition (all of them when no elements are given). | yes |
| `objects_versions` | `kimbim objects versions` | List the saved versions of a library object (the project's and the office's) and its default values. |  |
| `drawings_create` | `kimbim drawings create` | Create a drawing. | yes |
| `drawings_delete` | `kimbim drawings delete` | Delete a drawing and its marker; it is also taken off every sheet it was placed on. | yes |
| `drawings_export` | `kimbim drawings export` | Export a drawing as SVG, DXF or DWG (pdf: put it on a sheet and use sheets.export). |  |
| `drawings_list` | `kimbim drawings list` | List the project's drawings: floor plans, sections and elevations with GlobalId, name, kind and level. |  |
| `drawings_rename` | `kimbim drawings rename` | Rename a drawing; its markers and the sheets it is placed on show the new name. | yes |
| `drawings_set_path` | `kimbim drawings set-path` | Replace a section or elevation marker's path: bend it with more points or curve a segment with a bulge. | yes |
| `drawings_set_scale` | `kimbim drawings set-scale` | Set a drawing's scale (1:N); coarser drawings use the project's model view options. | yes |
| `drawings_set_view` | `kimbim drawings set-view` | Change a drawing's view: its depth, a section's tilt and base height, or its crop rectangle. | yes |
| `sheets_create` | `kimbim sheets create` | Create an empty sheet; it gets the next number (A01, A02...). | yes |
| `sheets_delete` | `kimbim sheets delete` | Delete a sheet; the drawings placed on it are kept. | yes |
| `sheets_export` | `kimbim sheets export` | Export a sheet as PDF, SVG, DXF or DWG. |  |
| `sheets_get` | `kimbim sheets get` | Describe one sheet: its drawings, legends, symbols, title block fields and placed tables. |  |
| `sheets_list` | `kimbim sheets list` | List the sheets: number, title, paper size and the drawings placed on each. |  |
| `sheets_papers` | `kimbim sheets papers` | List the paper sizes a sheet can use, with their width and height in mm. |  |
| `sheets_place_drawing` | `kimbim sheets place-drawing` | Put a drawing on a sheet at a scale (1:100 by default). | yes |
| `sheets_place_legend` | `kimbim sheets place-legend` | Place the legend of the sheet's purpose (renovation statuses, fills) at a free spot. | yes |
| `sheets_place_picture` | `kimbim sheets place-picture` | Place a picture (PNG or JPEG) on a sheet, such as a logo, a render or a site photo. | yes |
| `sheets_place_schedule` | `kimbim sheets place-schedule` | Place a schedule table on a sheet; it prints with the sheet and updates with the model. | yes |
| `sheets_place_symbol` | `kimbim sheets place-symbol` | Place a north arrow, scale bar, revision cloud or a text on a sheet. | yes |
| `sheets_remove_drawing` | `kimbim sheets remove-drawing` | Take a drawing off a sheet; the drawing itself is kept. | yes |
| `sheets_remove_item` | `kimbim sheets remove-item` | Take a legend, symbol or schedule table off a sheet. | yes |
| `sheets_set_drawing` | `kimbim sheets set-drawing` | Move a drawing already on a sheet, change its scale there, or retitle it. | yes |
| `sheets_set_purpose` | `kimbim sheets set-purpose` | Set the purpose (pen set, styles, renovation filter) a sheet prints with. | yes |
| `sheets_set_symbol` | `kimbim sheets set-symbol` | Move a sheet symbol or picture, or change its text, size or the drawing a scale bar follows. | yes |
| `sheets_set_title_block` | `kimbim sheets set-title-block` | Edit a sheet's title block fields or move the title block. | yes |
| `sheets_update` | `kimbim sheets update` | Change a sheet's title, number, paper size or background colour. | yes |
| `schedules_delete` | `kimbim schedules delete` | Delete a custom schedule, or reset a built-in one to its default definition. | yes |
| `schedules_export` | `kimbim schedules export` | Export a schedule as a CSV file. |  |
| `schedules_fields` | `kimbim schedules fields` | List the fields a schedule of these IFC classes can show: attributes, info, quantities and properties. |  |
| `schedules_get` | `kimbim schedules get` | Compute a schedule: its columns, rows (with the GlobalIds each row stands for), totals and count. |  |
| `schedules_list` | `kimbim schedules list` | List the schedules (door, window, wall... tables) with the classes and fields of each. |  |
| `schedules_save` | `kimbim schedules save` | Create or change a schedule definition (stored in the project settings). | yes |
| `checks_ids_report` | `kimbim checks ids-report` | Write the report of the last IDS check as a file. |  |
| `checks_run` | `kimbim checks run` | Run model checks: schema (IFC validation), ids (information requirements), clash (collisions) and model (duplicates, rooms, zero-length walls...). |  |
| `levels_add` | `kimbim levels add` | Add a level at an elevation. | yes |
| `levels_delete` | `kimbim levels delete` | Delete a level. | yes |
| `levels_edit` | `kimbim levels edit` | Rename a level or move it to a new elevation. | yes |
| `levels_list` | `kimbim levels list` | List the levels from the lowest: GlobalId, name, elevation, height to the next level and element count. |  |
| `selection_get` | `kimbim selection get` | Read the app's current selection. |  |
| `selection_set` | `kimbim selection set` | Select elements in the app's window. |  |
| `script_run` | `kimbim script run` | Run a Python script in the project's console (the model is `ifc`, NicBim commands are in `bridge`). | yes |
| `snapshot_take` | `kimbim snapshot take` | Take a picture of the model to check your work: a 3D view (optionally framed on elements, with what your task changed coloured as the app's Compare shows it), a floor plan, a section or elevation, any drawing, or a sheet. |  |
| `annotation_add` | `kimbim annotation add` | Add an annotation: text at a point, a dimension chain, a mark or a leader with text. | yes |
| `annotation_auto_dimension` | `kimbim annotation auto-dimension` | Add a dimension chain along a row of aligned elements. | yes |
| `annotation_grid_dimension` | `kimbim annotation grid-dimension` | Add one dimension chain between a level's grid axes. | yes |
| `annotation_overall_dimension` | `kimbim annotation overall-dimension` | Add one overall dimension across the selection's combined plan bounds. | yes |
| `annotation_symbol` | `kimbim annotation symbol` | Place a tag, north arrow, scale bar, revision cloud, angle/radius/diameter, level or spot symbol. | yes |
| `annotation_tag` | `kimbim annotation tag` | Tag an element with its Mark/size (or a chosen style and template). | yes |
| `annotation_tag_all` | `kimbim annotation tag-all` | Tag every untagged door, window and wall on a level (or the given elements). | yes |
| `areas_plan` | `kimbim areas plan` | Gross and rentable areas of a level (m2), with each room's area. |  |
| `attributes_catalogue` | `kimbim attributes catalogue` | List the project's attribute groups with their counts, and its layers, materials, surfaces and composites, so an attribute file can be exported or imported with the right groups selected. |  |
| `attributes_export` | `kimbim attributes export` | Write the project's pens, line types, fill patterns, element styles, visibility and override sets, layer combinations, purposes, renovation styles, layers, materials, surfaces and composites to one self-contained JSON file, to carry the office's standards to another project. |  |
| `attributes_import` | `kimbim attributes import` | Import an attribute file into the open project: settings tables merge by name, IFC layers, materials, surfaces and composites are created where missing (or updated with replace). | yes |
| `classifications_add_reference` | `kimbim classifications add-reference` | Add a code (reference) under a classification system. | yes |
| `classifications_assign` | `kimbim classifications assign` | Assign classification references to elements (one undo step). | yes |
| `classifications_create_system` | `kimbim classifications create-system` | Create a classification system (or use a shipped one by name). | yes |
| `classifications_list` | `kimbim classifications list` | List the classification systems and their references. |  |
| `classifications_of_element` | `kimbim classifications of-element` | List the classifications assigned to the given elements. |  |
| `classifications_unassign` | `kimbim classifications unassign` | Remove classification references from elements. | yes |
| `draft_add` | `kimbim draft add` | Draw a line, polyline, arc, circle, rectangle, fill or spline on a level. | yes |
| `draft_fill_from_shape` | `kimbim draft fill-from-shape` | Fill a closed shape (a polyline, circle or fill) with a pattern, on the same level. | yes |
| `draft_patterns` | `kimbim draft patterns` | List the fill patterns available to draft fills. |  |
| `drainage_apply_sizes` | `kimbim drainage apply-sizes` | Write the drainage system's pipe sizes (one undo step). | yes |
| `drainage_size` | `kimbim drainage size` | Sanitary or storm flows, pipe and stack sizes and slope checks for a drainage system. |  |
| `electrical_apply_schedule` | `kimbim electrical apply-schedule` | Write the board's chosen breakers, cables and balanced phases to its circuits (one undo step). | yes |
| `electrical_circuits` | `kimbim electrical circuits` | List the distribution boards and circuits. |  |
| `electrical_create_circuit` | `kimbim electrical create-circuit` | Create a circuit from a board to devices. | yes |
| `electrical_panel_schedule` | `kimbim electrical panel-schedule` | A board's circuits with breakers, cables, voltage drop, phase loads and the main breaker. |  |
| `engineering_set_settings` | `kimbim engineering set-settings` | Change some of a discipline's engineering settings (codes, limits, tables). | yes |
| `engineering_settings` | `kimbim engineering settings` | Read a discipline's engineering settings and their defaults. |  |
| `export_ifc` | `kimbim export ifc` | Export the model as an IFC file. |  |
| `export_options` | `kimbim export options` | List what an IFC export can include: scopes, product classes with counts, levels and defaults. |  |
| `graphics_purpose` | `kimbim graphics purpose` | Switch the view to a graphic purpose (renovation filter, visibility and overrides). |  |
| `graphics_set` | `kimbim graphics set` | Change a graphic setting (pen, visibility, override) in the project's graphics state. |  |
| `graphics_state` | `kimbim graphics state` | The current pen, purpose and graphics state of the model. |  |
| `graphics_tables` | `kimbim graphics tables` | The project's pens, line types, fills, element styles, overrides, purposes and filters. |  |
| `hvac_apply_sizes` | `kimbim hvac apply-sizes` | Write the air system's duct sizes and design flows (one undo step). | yes |
| `hvac_size` | `kimbim hvac size` | Room airflows, duct sizes (equal friction, velocity limits), pressure drop and fan duty for an air system. |  |
| `import_formats` | `kimbim import formats` | List the mesh file formats the importer reads (OBJ, STL, PLY, COLLADA, glTF/GLB and FBX). |  |
| `import_mesh` | `kimbim import mesh` | Import a mesh (OBJ, STL, PLY, COLLADA, glTF/GLB or FBX) as a proxy on a level, scaled, rotated about Z and moved. | yes |
| `import_pointcloud` | `kimbim import pointcloud` | Import a point cloud as a visible proxy on a level, decimated to a marker per point. | yes |
| `import_pointcloud_formats` | `kimbim import pointcloud-formats` | List the point-cloud file formats the importer reads (XYZ, PTS, CSV/TXT, LAS, LAZ and E57). |  |
| `issues_comment` | `kimbim issues comment` | Add a comment to an issue. | yes |
| `issues_create` | `kimbim issues create` | Create a BCF issue with a viewpoint (camera, selected elements) and optional comments. | yes |
| `issues_export_bcf` | `kimbim issues export-bcf` | Export the project's issues as a BCF 2.1 .bcfzip for another BIM tool. |  |
| `issues_import_bcf` | `kimbim issues import-bcf` | Merge a .bcfzip into the project's issues by topic GUID; components are matched by IFC GlobalId. | yes |
| `issues_list` | `kimbim issues list` | List the project's BCF issues: id, title, type, status, priority, assignee, comments and viewpoint. |  |
| `issues_update` | `kimbim issues update` | Change an issue's title, description, type, status, priority, assignee, viewpoint or comments. | yes |
| `keynotes_delete` | `kimbim keynotes delete` | Remove a keynote from the table; the keynotes already placed keep the text they show. | yes |
| `keynotes_list` | `kimbim keynotes list` | List the project's keynotes: code, text and category, sorted by code. |  |
| `keynotes_place` | `kimbim keynotes place` | Place a keynote on a plan: its text at [x, y], optionally with a leader to another point. | yes |
| `keynotes_refresh` | `kimbim keynotes refresh` | Rewrite every placed keynote's text from the table (one undo step); returns how many changed. | yes |
| `keynotes_save` | `kimbim keynotes save` | Add or change a keynote in the table; run keynotes.refresh to rewrite the keynotes already placed. | yes |
| `layers_assign` | `kimbim layers assign` | Put elements on a layer (one undo step). | yes |
| `layers_create` | `kimbim layers create` | Create a layer. | yes |
| `layers_delete` | `kimbim layers delete` | Delete an empty layer; refuse when it still has elements. | yes |
| `layers_list` | `kimbim layers list` | List the project's layers, their visibility and lock state. |  |
| `layers_rename` | `kimbim layers rename` | Rename a layer (the elements on it follow). | yes |
| `links_add` | `kimbim links add` | Link an IFC file as a read-only reference on a level (default the first), with a placement. | yes |
| `links_explode` | `kimbim links explode` | Turn a linked model into editable copies: every source product becomes a normal element tagged with its source identity; the read-only proxy is removed. | yes |
| `links_list` | `kimbim links list` | List the linked models: GlobalId, name, path, source element count, triangles, transform and update time. |  |
| `links_monitor_status` | `kimbim links monitor-status` | Report changed, removed and newly added source elements for every monitored (exploded) linked model. |  |
| `links_monitor_sync` | `kimbim links monitor-sync` | Apply changed source attributes/properties to unmodified host copies; report or resolve conflicts. | yes |
| `links_push_monitored` | `kimbim links push-monitored` | Write host edits of monitored copies back to their linked source IFC files. | yes |
| `links_refresh` | `kimbim links refresh` | Rebuild every linked model whose source file changed; unchanged links are left alone. | yes |
| `links_remove` | `kimbim links remove` | Remove a linked model from the project (the linked file itself is left alone). | yes |
| `links_set_transform` | `kimbim links set-transform` | Move, rotate or scale a linked model and rebuild it. | yes |
| `links_stale` | `kimbim links stale` | List linked models whose source file changed, is missing or is unreadable since the last update. |  |
| `links_update` | `kimbim links update` | Re-read a linked model's file and rebuild its geometry (same GlobalId). | yes |
| `materials_add_standard` | `kimbim materials add-standard` | Add the standard building materials to the project. | yes |
| `materials_assign` | `kimbim materials assign` | Give elements a building material, or a composite (walls and slabs take its thickness). | yes |
| `materials_list` | `kimbim materials list` | List the building materials and composites in the project. |  |
| `materials_purge` | `kimbim materials purge` | Remove unused materials. | yes |
| `measure_points` | `kimbim measure points` | Measure through points like the Measure tool: each segment, the total length, the 3D distance between the first and last point and, for a closed outline, its plan area and perimeter (metres). |  |
| `mep_assign` | `kimbim mep assign` | Put elements in a system; their ports of its domain take its kind. | yes |
| `mep_catalogue` | `kimbim mep catalogue` | List the terminal and equipment kinds (with ports and design values) and the system kinds. |  |
| `mep_connect` | `kimbim mep connect` | Connect every pair of free ports that touch (one system, or the whole model). | yes |
| `mep_create_system` | `kimbim mep create-system` | Create a distribution system of a kind (supply_air, cold_water, sanitary, power...). | yes |
| `mep_drain_run` | `kimbim mep drain-run` | Draw a drain pipe falling at a slope through plan points. | yes |
| `mep_network` | `kimbim mep network` | A system's network: its source, tree, unreached elements, open ports and loops. |  |
| `mep_place` | `kimbim mep place` | Place a terminal or piece of equipment (diffuser, AHU, WC, basin, drain, board, socket, light...). | yes |
| `mep_run` | `kimbim mep run` | Draw a connected duct/pipe/tray run through 3D points with elbows; its ends join touching ports or tee into a segment they land on. | yes |
| `mep_set_design` | `kimbim mep set-design` | Set an MEP element's design values. | yes |
| `mep_systems` | `kimbim mep systems` | List the MEP distribution systems with their kind, domain, element count and open ports. |  |
| `models_create` | `kimbim models create` | Create an empty model container below the building; draw the unit in it, then place it on levels. | yes |
| `models_explode` | `kimbim models explode` | Unlink an instance: its elements become ordinary elements that no longer follow the model. | yes |
| `models_list` | `kimbim models list` | List the project's models (units drawn once and placed on levels) with their GlobalId, name, elevation and how many places use them. |  |
| `models_place` | `kimbim models place` | Place a model on a building level as one linked instance (a copy of its elements that follows later edits to the model). | yes |
| `models_update` | `kimbim models update` | Apply the model's current content to every place it is used; edits already do this automatically, so this is for a project loaded with stale instances. | yes |
| `plumbing_apply_sizes` | `kimbim plumbing apply-sizes` | Write the water system's pipe sizes and design values (one undo step). | yes |
| `plumbing_size` | `kimbim plumbing size` | Peak flows, pipe sizes and the pressure left at each fixture for a cold or hot water system. |  |
| `structure_analyse` | `kimbim structure analyse` | Analyse the structure: loads from the model, a frame solve, member utilisation and deflection checks. |  |
| `structure_results` | `kimbim structure results` | The stored structural results on the members (from the last applied analysis). |  |
| `structure_save_results` | `kimbim structure save-results` | Analyse and store the results on the members and the IFC analysis model (one undo step). | yes |
| `terrain_clear_pads` | `kimbim terrain clear-pads` | Remove a terrain's building pads and restore the surface kept before the first pad. | yes |
| `terrain_create` | `kimbim terrain create` | Create a terrain mesh from survey points ([x, y, z]) on a level, triangulated in plan. | yes |
| `terrain_delete` | `kimbim terrain delete` | Delete a terrain. | yes |
| `terrain_from_contours` | `kimbim terrain from-contours` | Create a terrain mesh from contour polylines, sampled along each segment before triangulating. | yes |
| `terrain_list` | `kimbim terrain list` | List the terrains: GlobalId, name, point count, triangle count and world bounds. |  |
| `terrain_pad` | `kimbim terrain pad` | Flatten the terrain vertices inside a closed outline to one elevation (a building pad). | yes |
| `terrain_pad_volumes` | `kimbim terrain pad-volumes` | Cut and fill volumes (m3) for each building pad, against the surface before the pads. |  |
| `terrain_pads` | `kimbim terrain pads` | List a terrain's building pads: outline points and elevation. |  |
| `underlays_add` | `kimbim underlays add` | Place a DXF, DWG, PDF or image file as an underlay on a level, to trace over or convert. | yes |
| `underlays_convert` | `kimbim underlays convert` | Turn a DXF, DWG or vector-PDF underlay's linework (and PDF text) into editable 2D elements on its level. | yes |
| `underlays_list` | `kimbim underlays list` | List the project's underlays: id, file, level, placement and display settings. |  |
| `underlays_remove` | `kimbim underlays remove` | Remove an underlay from the project (and its copied file once nothing uses it). | yes |
| `underlays_update` | `kimbim underlays update` | Move an underlay or change how it is shown (opacity, tint, clip, 3D, visibility...). | yes |
| `view_camera` | `kimbim view camera` | Put the app's 3D view camera at `eye` looking at `target`, in perspective (display only). |  |
| `view_hide` | `kimbim view hide` | Hide elements in the app's view (display only: the model does not change). |  |
| `view_isolate` | `kimbim view isolate` | Show only these elements in the app's view (display only). |  |
| `view_section_box` | `kimbim view section-box` | Cut the app's 3D view to a section box (D217: six cut planes with drag handles) around elements or an explicit box, or remove it (display only; views.save keeps a box with `section_box`). |  |
| `view_show_all` | `kimbim view show-all` | Show every element again in the app's view. |  |
| `view_style` | `kimbim view style` | Switch the app's view modes as the View menu does: lines only, white model, sketch style, x-ray, sun shadows and perspective. |  |
| `view_trace` | `kimbim view trace` | Trace reference in the app's plan view (Archicad's Trace & Reference): show the plan of the level below or above faintly under the active one, or turn it off (display only). |  |
| `view_zoom` | `kimbim view zoom` | Zoom the app's view to these elements, or to the whole model when none are given. |  |
| `views_apply` | `kimbim views apply` | Show a saved view in the app (its level, cuts, layers and style). | yes |
| `views_delete` | `kimbim views delete` | Delete a saved view. | yes |
| `views_list` | `kimbim views list` | List the project's saved views by name, with what each stores (level, plan or 3D, cuts, layers, style). |  |
| `views_save` | `kimbim views save` | Save a named view: the level, plan or 3D, the plan cut, 3D cut planes, hidden layers and style. | yes |
| `walkthrough_delete` | `kimbim walkthrough delete` | Delete a saved walkthrough. | yes |
| `walkthrough_list` | `kimbim walkthrough list` | List the project's walkthroughs (camera paths for a video): cameras in metres, duration, frame rate, size and frame count. |  |
| `walkthrough_render` | `kimbim walkthrough render` | Render a saved walkthrough into a video: one picture per frame with the windowless renderer, joined by ffmpeg. |  |
| `walkthrough_save` | `kimbim walkthrough save` | Add or replace a walkthrough: the camera moves along the cameras at an even speed for the duration. | yes |
| `walls_configure` | `kimbim walls configure` | Change wall settings: reference line, slant, top link and offset, or a complex profile. | yes |
| `walls_flip` | `kimbim walls flip` | Mirror layered walls' layers about their reference lines (inside becomes outside). | yes |
| `walls_options` | `kimbim walls options` | List the choices the wall settings take: reference lines (and the project default), top links, wall profiles and the surface sides of walls and slabs. |  |
| `walls_save_profile` | `kimbim walls save-profile` | Save a closed 2D shape as a named wall profile (a project setting). | yes |
| `walls_set_junctions` | `kimbim walls set-junctions` | Override how walls meet at their joins: run through, butt, or by material priority. | yes |
| `worksheets_create` | `kimbim worksheets create` | Create a worksheet: a level of its own for 2D work, with its drawing. | yes |
| `worksheets_delete` | `kimbim worksheets delete` | Delete a worksheet, its 2D elements and its drawing. | yes |
| `worksheets_list` | `kimbim worksheets list` | List the worksheets (2D-only drawing areas for details and sketches) with their drawings. |  |
| `worksheets_rename` | `kimbim worksheets rename` | Rename a worksheet and its drawing. | yes |
<!-- tools:end -->

The list is generated from the catalogue (257 exposed tools today). What is still missing on the agent side — in the
tool surface, the client/transport setup and remote sessions — is listed in
[18 §6](18-agent-tools-and-sessions.md#6-pending-integrations).

Every answer has the same shape: `{"ok": true, "result": ..., "changes": ..., "warnings": [...]}`, or
`{"ok": false, "error": {"code", "message", "hint"}}`. The `code` is in English; the message and the hint follow
the app's language (English or Spanish). On the command line the answer is a one-line summary, or the full JSON with
`--json`. Exit code 0 means it worked, 1 a tool error, 2 a mistake in the command.

## Commands for people

These commands are on the command line only. Agents don't get them.

| Command | What it does |
|---------|--------------|
| `kimbim project init [DIR]` | Makes a folder a NicBim project |
| `kimbim versions save [FILE.ifc] -m MESSAGE` | Saves a version: of an IFC file, or of the project's working model |
| `kimbim versions status FILE.ifc` | What saving that IFC file would change |
| `kimbim versions branch [NAME]`, `switch NAME` | Lists or creates design options, switches to one |
| `kimbim versions tag [NAME] [-m NOTE] [--delete]` | Lists, sets or deletes milestones |
| `kimbim versions merge OPTION [--resolve ID=CHOICE]` | Combines another option into the current one |
| `kimbim versions show KEY [--rev REV]` | Prints one stored record |
| `kimbim versions export-dxf OUT` | Writes a version's drawings and sheets as DXF |
| `kimbim script run FILE [MODEL.ifc]` | Runs a Python script on an IFC file (a batch job), or on the project as the agent tool does |
| `kimbim serve PROJECT` | Keeps a project open for agent commands (started for you when needed) |
| `kimbim mcp [--project P]` | The MCP server (agents start it from their configuration) |
| `kimbim setup CLIENT` | Connects an agent (above) |
| `kimbim help [--markdown]` | The help, or the tool table above |

Every command takes `--project P` (a project folder, a `.nic` or an `.ifc`). Without it, `kimbim` uses the current
folder when it is a project or holds exactly one `.nic`.

## How it runs

When the project is open in NicBim, the app hosts the **live** session: it writes its discovery file next to the
project (`.nic` files get `<name>.nic.agent-live.json`; folders get `.kimbim/agent-live.json`) and runs each call
on its own thread. The CLI and MCP server find it there first, so the same commands work with no worker. The
status bar shows *Agent: live* and a *Disconnect* button.

When no app has the project open, the first command starts a **background worker** (`kimbim serve`). It opens the
project once and keeps it open, so later commands are fast even on large models. While it runs it holds the
project's lock as *NicBim agent*, so the app opens the project read-only. The worker saves and lets go of the
project 10 minutes after the last command (`KIMBIM_AGENT_IDLE` sets other seconds), and it saves when a task
finishes.

Timings on Windows, 2026-10-26. The sample house is the exit check below (`tools/check_agent.py`, each step one
MCP call including the round trip to the worker). The Clinic (13 MB, IFC 2x3, 41,068 elements) was timed with the
same tools called in the worker's process, because two of its steps take longer than the client waits (see the
limits below).

| Step | Sample house (4 windows) | Clinic (10 windows) | Target |
|------|-------------------------:|--------------------:|--------|
| Open (the first call starts the worker) | 1.3 s | 42 s the first time, 1 to 3 s once its cache exists | |
| `elements_find` (windows) | 12 ms | 0.15 to 0.3 s | |
| Write: `elements_set_dimensions` +50 cm | 0.3 s | refused (below) | under 2 s |
| Write: `elements_rename` | | 50 to 75 ms | under 2 s |
| `snapshot_take`, 3D, first picture (starts the renderer) | 6.6 s with `changes: "task"` | 37 s | under 3 s |
| `snapshot_take`, 3D, next pictures | | 3.9 s | under 3 s |
| `snapshot_take`, 3D, `changes: "task"` | | 227 s (the compare alone: 204 s) | under 3 s |
| `task_finish` (saves the version and the .nic) | 3.6 s | 247 s | |

What these show:

- **Writes are fast** on both models. The Clinic's windows can't be resized: all 58 of its Revit windows answer
  *"the opening doesn't fit in the wall"*, even for 1 cm. NicBim measures where a window sits in its wall from the
  opening's placement, as its own windows are built, and Revit's openings are placed differently. The write was
  timed as a rename instead.
- **Pictures** are within a few seconds once the renderer has the model; its first load of a large model takes
  about half a minute.
- **Comparing is the slow part on large models.** Since compare works on content (see [03](03-versioning.md)), a
  compare on the Clinic takes about 200 s. `task_finish` and a snapshot with `changes` both compare, so they take
  minutes there. This is the next thing to speed up.

## Limits

- **Live needs the app open.** The app hosts the session when a project finishes loading; close it and later
  commands use an offline worker instead. `selection_get` and `selection_set` work live and answer `needs_app`
  offline.
- **One open task per client.** A second `task_start` from the same client answers `task_busy`; another client may
  have its own task and option. A stored session on a **versioned folder** project works in its own worktree, so the
  architect's view stays on their option; a `.nic`/IFC session (and every older ad-hoc CLI/MCP call) still shares
  the app's one working model, so each call switches to its task's option and the architect's view follows it.
- **Review is a bar, not a dialog.** A proposal with conflicting property edits opens the existing Combine dialog;
  otherwise Accept combines and saves in one step.
- **Long calls on large models.** The command line and the MCP server wait 120 s for an answer. On the Clinic,
  `task_finish` and a snapshot with `changes` take longer (above), so the agent is told `worker_failed`. The
  worker still completes the call, so the task does finish.
- **Resizing imported doors and windows** works for openings placed the way NicBim places them. Revit's (the
  Clinic's) are refused.
- **Option mode needs versions.** On a plain IFC file or a project without versions, `task_start` says to enable
  versioning or to use direct mode.

## The exit check

`pixi run agent` runs the request from the start of this page against the sample house, through MCP only. It finds
the Level 1 windows, starts *Widen first-floor windows*, makes them 50 cm wider, takes a snapshot of the task's
changes and finishes the task. It then reads the project's history and checks three things. The option
`agent/widen-first-floor-windows` holds one new version, and its difference from `main` is exactly the 4 windows at
1.7 m wide (their wall openings may also appear). `main` has not moved. The snapshot is a real picture (a PNG with
at least 100 colours). It prints one JSON line with the timings.

`test_agent_live` (part of `pixi run app-test`) runs the same request against the app's **live** session: it opens
the sample house, calls the CLI through the live discovery file, finishes a task, finds it in the proposal bar and
clicks **Accept**. It then checks that the combined model holds the change.
