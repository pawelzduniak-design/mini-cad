# Clicking Contract

This document is the click-behavior map for the CAD UI. It is written as a
duck-review checklist: for every click, verify the selected target, the active
mode, the command panel, the Properties panel, and the mutation boundary.

Source of truth in code:

- `cad_app/viewer_widget_events.py` routes viewport mouse clicks.
- `cad_app/viewer_widget_actions.py` builds the contextual command surface.
- `cad_app/viewer_widget_state_snapshot.py` exposes stable UI state.
- `cad_app/ui_menu.py` defines categories and command groups.
- `tests/ui/test_clicking_contract_matrix.py` checks the matrix below.

## UI Areas

- Left rail has only Select and Sketch. Empty projects enter Sketch immediately
  and show draw tools. File/import/view actions stay in top/global chrome.
- Top toolbar contains global actions: Undo, Redo, Save, Export STEP, Fit All,
  Home View, Shaded, Wireframe.
- Context command panel shows only commands that are enabled for the active
  category, current selection, and active tool.
- Viewport click selects geometry or starts/drags the active tool.
- Right panel shows Model, Bodies, Sketches, History, and Properties. The
  Properties panel mirrors enabled context actions as clickable items.
- Bottom HUD shows Mode, Selection, selection filter, Tool, Sketch, and hint.

## Basic Click Flow

1. User chooses selection mode: Object, Face, Edge, or Vertex. Shortcuts are
   `1`, `2`, `3`, `4`.
2. User clicks the viewport.
3. The picker returns a body, face, edge, vertex, or sketch profile according
   to the current selection mode.
4. The app stores `Scene.selection`.
5. The adaptive command panel is selection-driven. Select remains the public
   work mode unless Sketch is active.
6. The selection marker is redrawn.
7. Context hint, status, Properties, and command panel refresh.

Clicking empty space clears the selection and reports `No selection`.

## Multi-Selection

- `Ctrl` + viewport click toggles the clicked target in the current selection.
- Multi-selection works for bodies, faces, edges, vertices, sketch profiles, and
  mixed picks.
- Left-drag area selection stores all matched targets, not only the first hit.
- Multiple bodies expose only Move plus currently valid Boolean actions.
  Rotate, Mirror, and Delete stay hidden for multi-body selection.
- Multiple sketch profiles expose Move, Extrude, New Body, and Delete Sketch.
- Multiple faces, edges, vertices, or mixed selections show selection state and
  markers, but do not expose single-topology commands until a supported
  multi-command exists.
- Ctrl-clicking an already selected target removes it. If one target remains,
  the UI falls back to the normal single-selection contract.

## Selection Mode Clicks

| Click | Result | Status | Command Panel |
| --- | --- | --- | --- |
| Object mode button or `1` | Clears selection; picker targets whole bodies | `Selection: object` | Object, Face, Edge, Vertex, Select Through |
| Face mode button or `2` | Clears selection; picker targets faces | `Selection: face` | Object, Face, Edge, Vertex, Select Through |
| Edge mode button or `3` | Clears selection; picker targets edges | `Selection: edge` | Object, Face, Edge, Vertex, Select Through |
| Vertex mode button or `4` | Clears selection; picker targets vertices | `Selection: vertex` | Object, Face, Edge, Vertex, Select Through |
| Select Through or `T` | Keeps selection mode, but click can return overlapping candidates | `Select Through on/off` | same selection-mode commands |

If Select Through finds multiple candidates, the app opens
`OverlappingSelectionMenu` at the cursor. Choosing an item applies that exact
candidate.

## Viewport Selection Results

| User Clicks | Active Category | HUD Selection | Context Hint | Status |
| --- | --- | --- | --- | --- |
| Body/object | Select | `Selection: object 0` | `Body selected - choose Move` | `Selected body <id>` |
| Body face | Select | `Selection: face <index>` | `Face selected - choose Extrude or Move` | `Selected face <index>` |
| Body edge | Select | `Selection: edge <index>` | `Edge selected - choose an available tool` | `Selected edge <index> (<px>px)` |
| Body vertex | Select | `Selection: vertex <index>` | `Vertex selected - choose an available tool` | `Selected vertex <index> (<px>px)` |
| Sketch profile | Select | `Selection: Sketch Profile` | `Sketch Profile selected - edit, move, extrude, revolve, or delete` | `Selected Sketch Profile...` |
| Multiple bodies | Select | `Selection: objects (<count>)` | `Multiple bodies selected - choose Move` | `Selected <count> bodies...` |
| Multiple sketch profiles | Select | `Selection: Sketch Profiles (<count>)` | `Multiple sketch profiles selected - choose Move, Extrude, New Body, or Delete` | `Selected <count> sketch profiles...` |
| Sketch entity | Select/browser selection | sketch entity/object selection | `Sketch entity selected` | `Selected Sketch` |

## Context Menus By Selection

These are the command-panel actions after selection. The command panel must
match `get_ui_state().context_actions`: unavailable actions are hidden from the
panel, not shown as inert buttons.

| Selection | Visible Command Panel | Enabled Properties Actions |
| --- | --- | --- |
| No selection, Select category | Object, Face, Edge, Vertex, Select Through | Object, Face, Edge, Vertex, Select Through |
| Body/object | Selection mode controls, then Move, Rotate, Boolean actions when valid | Same list. Move axis is chosen from the viewport manipulator. |
| Multiple bodies | Selection mode controls, then Move, Boolean actions when valid | Same list. Move axis is chosen from the viewport manipulator. |
| Face | Selection mode controls, then Extrude, Move, Remove Face | Same list. Face circles are created in Sketch, then Extruded. |
| Edge | Selection mode controls, then Move, Fillet/Chamfer. Thread appears only for circular edges. | Same list when the topology supports controlled edge move. Positive Fillet/Chamfer values fillet; negative values chamfer. |
| Vertex | Selection mode controls, then Move | Move when the topology supports controlled vertex move. |
| Sketch profile | Selection mode controls, then Edit Sketch, Move, Extrude, New Body, Revolve, Delete Sketch. Hosted profiles expose Cut inside the active Extrude tool popover. | Same list. Revolve exposes numeric Angle and Elevation values. Axis-specific Revolve X/Y/Z actions stay hidden. |
| Multiple sketch profiles | Selection mode controls, then Move, Extrude, New Body, Delete Sketch | Same list. |

The Select panel always keeps Object, Face, Edge, Vertex, and Select Through
visible above selection-specific commands, so a user can recover from selecting
the wrong topology without knowing keyboard shortcuts.

Duck check: a face, edge, vertex, or sketch profile must never silently fall
back to whole-body Delete, Move, Rotate, or Mirror.

## Category Rail Clicks

Category rail clicks change command context only. They must not mutate geometry.

| Category | Command Surface |
| --- | --- |
| Select | Object, Face, Edge, Vertex, Select Through |
| Sketch | Immediately starts a sketch. Active Sketch shows Line, Arc, Circle 2-Point, Center Radius, 3-Point Rect, Center Rect, Trim, Finish Sketch |

Modify, Transform, Boolean, Measure, View, Create, and File are not left-rail
modes. Boolean appears in body context; view/file actions live in top/global
chrome.

## Browser And Properties Clicks

- Clicking a body in the browser selects the body as Object and shows body
  context actions.
- Clicking a sketch profile in the browser selects it as a Face-like profile
  target and shows profile commands.
- Clicking a command row under Properties triggers the same QAction as the
  command panel, but only if that action is enabled.
- History panel rows can run Undo, Redo, Cancel active tool, feature-tree
  Rebuild, feature-step Edit, or rollback after a selected feature step.

## Sketch Clicks

- Entering Sketch immediately starts on the bottom XY plane unless a planar
  face is selected.
- With a selected planar body face, New Sketch uses that face as workplane and
  feature host so Extrude can add to or subtract from that body.
- If the user leaves Sketch without drawing or dragging anything, the empty
  sketch is discarded.
- Circle has two sketch tools: Circle 2-Point and Center Radius.
- Edit Sketch reopens the selected sketch geometry on its saved workplane so
  the user can continue drawing, trimming, or editing dimensions.
- Edit Sketch and Trim are scoped by the selected sketch's `sketch_id`; another
  independent sketch on the same workplane must not be changed.
- While a sketch session is active, left-click/drag draws with the active tool.
- Choosing Sketch creates the sketch session; choosing draw tools only changes
  the active sketch tool.
- Right-click or Enter finishes the sketch sequence.
- Trim is segment-click based. Selecting a whole sketch profile and choosing
  Trim enters trim mode; it must not delete the whole profile.
- Trim must remove the clicked visible segment on the first click and refresh
  incrementally, without full scene redisplay.

## Area Selection And Navigation

- Left drag beyond 5 px starts area selection.
- Left-to-right area selection requires containment.
- Right-to-left area selection uses crossing mode.
- During area selection, `Tab` cycles filters and `B`, `F`, `E` force Bodies,
  Faces, Edges.
- Area selection must preserve all matched selections. It must not silently
  reduce the result to the first item.
- Right mouse pans unless a sketch is active; in sketch mode it finishes the
  sketch sequence.
- Middle mouse or dragging the orientation gizmo orbits.
- Mouse wheel zooms at cursor.
- Clicking orientation gizmo zones changes view axis.

## Active Tool Clicks

When a modeling tool is active, normal selection clicks are suspended:

- Extrude shows a drag arrow/manipulator and dimension value.
- Move shows X/Y/Z viewport arrows. Clicking an arrow constrains the active
  move axis; dragging an arrow moves along that axis. Dragging away from arrows
  uses view-plane movement.
- Move/Rotate/Fillet/Chamfer use left drag to preview and left release or Enter
  to commit. Fillet/Chamfer is one tool: positive values fillet, negative values
  chamfer. Revolve uses Angle for rotation and Elevation for helical bodies.
- Esc cancels active tools.
- The right panel must show `active_operation` context.
- Command panel must show the active command and Cancel Tool.

## Final Duck Checklist

Before changing click behavior, verify all items:

- Selecting a body shows Move, Rotate, and valid Boolean actions, not face/edge commands.
- Selecting a face shows `Extrude`, `Move`, and `Remove Face`.
- Selecting an edge shows `Move` and `Fillet/Chamfer`; circular
  edges also show Thread.
- Thread must ask for a preset or Custom, representation
  (Modeled/Cosmetic), thread type (Auto/External/Internal), and numeric
  pitch/length/depth values before mutating the model.
- Selecting a vertex shows supported `Move` only.
- Selecting a sketch profile shows profile commands and `Extrude`.
- Ctrl-click multi-selection works for bodies, faces, edges, vertices, sketch
  profiles, and mixed picks.
- Multiple selected bodies show Move and valid Boolean actions; Move applies to
  every selected body in one operation.
- Multiple selected sketch profiles show Move, Extrude, New Body, and Delete Sketch.
- Entering Sketch mode starts a sketch and shows draw tools.
- Selection-mode buttons clear selection and do not mutate geometry.
- Category rail clicks do not mutate geometry.
- View/camera/display clicks do not mutate geometry.
- Select Through opens a choice menu only when there are overlapping hits.
- Properties actions match enabled context actions.
- Command panel actions match enabled context actions; unavailable actions are
  hidden, not left as confusing disabled buttons.
- Disabled/planned commands stay outside the context panel or report pending
  behavior from explicit non-context entry points.
- Trim removes segments, not whole profiles, and stays incremental.
