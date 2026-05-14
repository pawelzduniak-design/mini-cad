# CAD Agent Start

This repo is a desktop direct-modeling CAD prototype.

The current source of truth is this documentation set:

1. `docs/PRODUCT_CONTRACT.md` - product behavior that must stay true.
2. `docs/ARCHITECTURE.md` - where code lives.
3. `docs/CLICKING_CONTRACT.md` - click/selection/menu behavior matrix.
4. `docs/TESTING.md` - how the new tests are organized and run.
5. `docs/VISUAL_TESTING.md` - GUI/perception checks.

## Non-Negotiable Rules

- Face, edge, and vertex commands operate on selected topology, not the whole
  body unless the UI explicitly selects a body.
- `start_sketch` creates an independent sketch by default when no body face is
  selected.
- A selected body face provides both sketch plane and feature host so Extrude
  Sketch plus Cut Mode makes add/subtract an explicit body operation.
- Existing sketches are edited only through explicit browser/right-panel intent.
- Category rail clicks change mode/context only. They must not mutate geometry.
- Undo/redo must protect every committed model mutation.
- View, camera, hover, and selection changes must not mutate model geometry.
- Visual regressions count: black/blank/off-camera viewport failures are real
  failures, even if geometry objects exist.

## First Steps For Agents

1. Read `docs/PRODUCT_CONTRACT.md`.
2. Inspect the relevant code module before editing.
3. Add or update the smallest contract test for the behavior.
4. Run the narrow test group, then `.\run.ps1 check`.
5. Run `.\run.ps1 visual` for any viewport, rendering, GUI, or mode work.
