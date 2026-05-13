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

- Left rail changes category only: Select, Modify, Sketch, Boolean, Transform,
  Measure, View, File. Create/Box Body is hidden for now.
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
5. The app changes the category automatically:
   - body/object click -> Transform
   - face/edge/vertex click -> Modify
   - sketch profile click -> Modify with profile commands
6. The selection marker is redrawn.
7. Context hint, status, Properties, and command panel refresh.

Clicking empty space clears the selection and reports `No selection`.

## Multi-Selection

- `Ctrl` + viewport click toggles the clicked target in the current selection.
- Multi-selection works for bodies, faces, edges, vertices, sketch profiles, and
  mixed picks.
- Left-drag area selection stores all matched targets, not only the first hit.
- Multiple bodies switch to Transform and expose only Move, Move X, Move Y, and
  Move Z. Rotate, Mirror, Delete, and Boolean commands stay hidden for
  multi-body selection.
- Multiple sketch profiles switch to Modify and expose Move Sketch, Extrude
  Sketch, New Body, and Delete Sketch.
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
| Body/object | Transform | `Selection: object 0` | `Body selected - choose Move` | `Selected body <id>` |
| Body face | Modify | `Selection: face <index>` | `Face selected - choose Extrude Face or Move Face` | `Selected face <index>` |
| Body edge | Modify | `Selection: edge <index>` | `Edge selected - choose an available tool` | `Selected edge <index> (<px>px)` |
| Body vertex | Modify | `Selection: vertex <index>` | `Vertex selected - choose an available tool` | `Selected vertex <index> (<px>px)` |
| Sketch profile | Modify | `Selection: Sketch Profile` | `Sketch Profile selected - edit, move, extrude, revolve, or delete` | `Selected Sketch Profile...` |
| Multiple bodies | Transform | `Selection: objects (<count>)` | `Multiple bodies selected - choose Move` | `Selected <count> bodies...` |
| Multiple sketch profiles | Modify | `Selection: Sketch Profiles (<count>)` | `Multiple sketch profiles selected - choose Move, Extrude Sketch, New Body, or Delete` | `Selected <count> sketch profiles...` |
| Sketch entity | Modify/browser selection | sketch entity/object selection | `Sketch entity selected` | `Selected Sketch` |

## Context Menus By Selection

These are the command-panel actions after selection. The command panel must
match `get_ui_state().context_actions`: unavailable actions are hidden from the
panel, not shown as inert buttons.

| Selection | Visible Command Panel | Enabled Properties Actions |
| --- | --- | --- |
| No selection, Select category | Object, Face, Edge, Vertex, Select Through | Object, Face, Edge, Vertex, Select Through |
| Body/object | Move, Move X, Move Y, Move Z, Rotate, Rotate X, Rotate Y, Rotate Z, Mirror. Boolean target appears only when a valid boolean flow exists. | Same list. |
| Multiple bodies | Move, Move X, Move Y, Move Z | Same list. |
| Face | New Sketch (Face Plane), Extrude Face, Move Face, Move Normal, Remove Face, Circle Boss, Circle Cut | Same list. Offset Face is planned and stays hidden until implemented. |
| Edge | Fillet Edge, Chamfer Edge, Move Edge. Thread appears only for circular edges. | Fillet Edge, Chamfer Edge, Move Edge when the topology supports controlled edge move. Thread appears only for circular edges. |
| Vertex | Move Vertex | Move Vertex when the topology supports controlled vertex move. |
| Sketch profile | Edit Sketch, Edit Dimensions, Trim, Move Sketch, Move Sketch X, Move Sketch Y, Move Sketch Z, Extrude Sketch, New Body, Revolve, Revolve X, Revolve Y, Revolve Z, Delete Sketch | Same list. Revolve exposes numeric Angle and Elevation values. It must not show face `Extrude Face`. |
| Multiple sketch profiles | Move Sketch, Move Sketch X, Move Sketch Y, Move Sketch Z, Extrude Sketch, New Body, Delete Sketch | Same list. |

Duck check: a face, edge, vertex, or sketch profile must never silently fall
back to whole-body Delete, Move, Rotate, or Mirror.

## Category Rail Clicks

Category rail clicks change command context only. They must not mutate geometry.

| Category | Command Surface |
| --- | --- |
| Select | Object, Face, Edge, Vertex, Select Through |
| Modify with no selection | No local modeling commands until topology is selected |
| Sketch | Without an active sketch: New Sketch only. After New Sketch starts: Line, Arc, Circle, 3-Point Rect, Center Rect, Trim, Finish Sketch |
| Boolean | Boolean target/clear/union/subtract/intersect only when the current target/tool state makes them valid |
| Transform | Body transform commands only when a body exists |
| Measure | No command-panel actions until measurement tools are implemented |
| View | Fit All, Home View, Shaded, Wireframe |
| File | Save, Import STEP, Export STEP |

## Browser And Properties Clicks

- Clicking a body in the browser selects the body as Object and switches to
  Transform.
- Clicking a sketch profile in the browser selects it as a Face-like profile
  target and shows profile commands.
- Clicking a command row under Properties triggers the same QAction as the
  command panel, but only if that action is enabled.
- History panel rows can run Undo, Redo, Cancel active tool, feature-tree
  Rebuild, feature-step Edit, or rollback after a selected feature step.

## Sketch Clicks

- In Sketch category without an active sketch, only New Sketch is available.
  Line, Arc, Circle, Rectangle, and Trim must stay hidden/disabled until a
  sketch session exists.
- New Sketch starts on the bottom XY plane unless a planar face is selected.
- With a selected planar face, New Sketch uses that face only as workplane.
  It must not create hosted feature metadata.
- Edit Sketch reopens the selected sketch geometry on its saved workplane so
  the user can continue drawing, trimming, or editing dimensions.
- Edit Sketch and Trim are scoped by the selected sketch's `sketch_id`; another
  independent sketch on the same workplane must not be changed.
- While a sketch session is active, left-click/drag draws with the active tool.
- Choosing a draw tool without an active sketch must not silently create a
  sketch. It may remember the pending tool, but the user must still explicitly
  start New Sketch.
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

- Extrude and Sketch Extrude show a drag arrow/manipulator and dimension value.
- Move/Rotate/Fillet/Chamfer use left drag to preview and left release or Enter
  to commit. Revolve uses Angle for rotation and Elevation for helical bodies.
- Esc cancels active tools.
- The right panel must show `active_operation` context.
- Command panel must show the active command and Cancel Tool.

## Final Duck Checklist

Before changing click behavior, verify all items:

- Selecting a body shows body transform commands, not face/edge commands.
- Selecting a face shows face commands and `New Sketch (Face Plane)`.
- Selecting an edge shows Fillet, Chamfer, and supported Move Edge; circular
  edges also show Thread.
- Thread must ask for a preset or Custom, representation
  (Modeled/Cosmetic), thread type (Auto/External/Internal), and numeric
  pitch/length/depth values before mutating the model.
- Selecting a vertex shows supported Move Vertex only.
- Selecting a sketch profile shows profile commands, not `Extrude Face`.
- Ctrl-click multi-selection works for bodies, faces, edges, vertices, sketch
  profiles, and mixed picks.
- Multiple selected bodies show only Move commands, and Move applies to every
  selected body in one operation.
- Multiple selected sketch profiles show Move Sketch, Extrude Sketch, New Body,
  and Delete Sketch.
- Entering Sketch mode shows New Sketch only; draw tools appear after New Sketch.
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
