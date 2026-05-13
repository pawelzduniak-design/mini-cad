# Product Contract

The app is a practical direct-modeling CAD workspace. The user should always
know what is selected, which command can run, and whether a command affects a
body, a face, an edge, a vertex, or a sketch profile.

The detailed click/selection/menu matrix lives in
`docs/CLICKING_CONTRACT.md`.

## Workspace

- Left rail: category/mode selection only. Create/Box Body is hidden for now.
- Context command panel: commands available for the current mode, selection,
  and active tool.
- Viewport: dominant modeling area.
- Right browser/properties panel: explicit model/sketch selection and context.

## Selection And Commands

- Object selection targets whole-body commands.
- Face, edge, and vertex selection targets local topology commands.
- Sketch profile selection targets profile commands such as sketch extrude,
  new body, revolve, dimensions, edit sketch, move sketch, delete sketch, and
  trim.
- Ctrl-click and area selection can hold multiple selections for every
  selection kind. Multi-body selection exposes only body Move commands, and the
  move operation applies to every selected body. Multi-sketch-profile selection
  exposes sketch Move, Sketch Extrude, New Body, and Delete Sketch.
- Sketch trim is segment-click based. Selecting a full sketch profile and
  activating trim must enter trim mode, not delete the whole profile.
- Body transform commands require a real body. Sketch objects must never unlock
  whole-body move, rotate, mirror, or delete commands.
- `delete_object` is never a fallback for face/edge/vertex selection.
- Body transform commands target bodies only. Sketch Move is a separate sketch
  command and updates the sketch metadata used by dimensions and trimming.
- Boolean commands require an explicit target body and a separate tool body.

## Sketch

- `start_sketch` starts a new independent sketch.
- On empty selection, it uses the bottom/XY plane.
- On selected planar body face, it uses that face as the workplane only.
- Sketch draw tools are unavailable until `start_sketch` has created an active
  sketch session.
- It must not create `host_item_id` metadata.
- Sketch-created profiles and entities carry a stable `sketch_id`; edit, trim,
  and region rebuilds must stay scoped to that sketch, not every profile on the
  same workplane.
- The visible face-plane label is `New Sketch (Face Plane)`.
- `new_sketch` exists only as a hidden compatibility alias.
- A browser-selected sketch can be an explicit edit target, but that is not
  feature-host metadata.

## Direct Modeling

- `extrude`, `move_selection`, `move_selection_normal`, `remove_face`,
  `circle_boss`, and `circle_cut` are face-context commands.
- `fillet`, `chamfer`, and supported edge move are edge-context commands.
- `thread` is an edge-context command for circular edges only. It supports ISO
  and UNC presets, custom pitch/length/depth, external/internal/auto type, and
  modeled or cosmetic representation.
- Sketch Revolve supports numeric Angle and Elevation; non-zero Elevation
  creates a helical body.
- Supported vertex move is a vertex-context command.
- Geometry must remain valid after successful solid operations.
- Undo restores the exact prior scene state; redo restores the result.
- Successful model mutations must not require an initialized viewport; rendering
  is a follow-up display step.

## Parametric History

- Body-generating Sketch Extrude and Sketch Revolve create a feature tree with
  the sketch profile as the rebuild base.
- Face Extrude, hosted Sketch Extrude, and Thread append editable feature steps
  to the target body's feature tree.
- Feature steps store user parameters and a stable-enough topological reference:
  planar faces are remapped by center, normal, and area; circular thread edges
  are remapped by center, axis, and radius.
- Rebuild must be transactional. A failed rebuild must leave the previous body
  geometry intact and report the failure in the History panel.
- History supports explicit rebuild, editing a step's parameters, and rollback
  after a chosen step.

## View And Files

- `fit_all`, `home`, `display_shaded`, and `display_wireframe` change view state
  only.
- STEP export does not mutate the scene.
- STEP import adds a body.

## Planned But Not Implemented

- `offset_face`, `mirror_body`, and measurement tools may be visible but must be
  hidden from invalid context panels, disabled, or report pending behavior
  instead of mutating geometry.
