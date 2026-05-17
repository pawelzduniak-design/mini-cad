# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A desktop direct-modeling CAD prototype built on PySide6 + OpenCASCADE (OCP). The UI has a left rail (Select / Sketch only), a context command panel, a 3D viewport, and a right browser/properties panel.

## Commands

```powershell
.\run.ps1 app          # launch the app
.\run.ps1 test         # normal pytest suite (GUI/perception tests skip)
.\run.ps1 safety       # command routing / mutation guardrail tests only
.\run.ps1 gui          # Qt/OCP window integration tests (sets CAD_APP_GUI_TESTS=1)
.\run.ps1 visual       # screenshot + visual probe (sets CAD_APP_VISUAL_TESTS=1)
.\run.ps1 check        # pytest + ruff + black --check
.\run.ps1 smoke        # safety + sketch workflow + UX walkthrough + visual probe
.\run.ps1 all          # everything
```

Run a single test file:
```powershell
.venv\Scripts\python.exe -m pytest tests\core\test_scene_contracts.py -q
```

Lint and format:
```powershell
.\run.ps1 lint         # ruff check
.\run.ps1 format       # black (mutating)
.\run.ps1 format-check # black --check
```

## Standard Workflow

1. Read `docs/PRODUCT_CONTRACT.md` before touching behavior.
2. Inspect the relevant module before editing.
3. Add or update the smallest contract test covering the change.
4. Run the narrow test group, then `.\run.ps1 check`.
5. Run `.\run.ps1 visual` for any viewport, rendering, GUI, or mode work.

## Architecture

### Model

- `cad_app/scene.py` — authoritative domain state: UUID-addressed `TopoDS` shapes, selection, undo/redo stack. **Never use AIS render objects as model assertions.**
- `cad_app/types.py` — shared dataclasses (`SceneObject`, `SelectionRef`, `UIState`) and enums (`SelectionKind`, `OperationState`).

### Geometry

- `cad_app/commands.py` — public direct-modeling facade (extrude, move, fillet/chamfer, thread, boolean, etc.).
- `cad_app/command_geometry.py`, `command_topology.py`, `command_rounding.py` — geometry helpers; `command_convex.py` is a legacy fallback, use cautiously.
- `cad_app/engine.py` — primitive shape creation.
- `cad_app/sketch.py` / `sketch_features.py` — sketch profiles and sketch-driven solids.
- `cad_app/feature_history.py` — editable feature tree: rebuild, rollback, topological reference remapping.
- `cad_app/thread_specs.py` — ISO/UNC/custom thread presets.
- `cad_app/io_step.py` — STEP import/export.

### UI

- `cad_app/viewer_widget.py` — `ViewerWidget` composed from ~12 mixins. The interaction controller.
- `cad_app/viewer_widget_state.py` / `viewer_widget_state_snapshot.py` — `get_ui_state()` returns the stable `UIState` snapshot used by all contract tests.
- `cad_app/viewer_widget_actions.py` — context panel action enablement (what commands appear for the current selection/mode).
- `cad_app/viewer_widget_events.py` — viewport mouse/keyboard routing.
- `cad_app/viewer_widget_sketch_*.py` — sketch session logic.
- `cad_app/viewer_widget_move_*.py` — move/extrude/fillet/chamfer session logic.
- `cad_app/ui_menu.py` — declarative action group definitions (`SELECT_ACTIONS`, `BODY_ACTIONS`, `FACE_MODIFY_ACTIONS`, etc.).
- `cad_app/ui_actions.py` — QAction creation and shortcuts.
- `cad_app/ui_sessions.py` — transient UI-only sessions for move/sketch tools.
- `cad_app/gui_contract.py` — machine-checkable GUI contract (`GUI_CONTRACT` dict) cross-referenced by tests.

### Rendering

- `cad_app/viewer.py` — OCP/AIS viewer bridge.
- `cad_app/viewer_markers.py` — selection, hover, preview, sketch, and dimension marker rendering.
- `cad_app/viewer_widget_overlays.py` — Qt overlays above the viewport (manipulator, orientation gizmo, selection box, sketch plane chooser).
- `cad_app/theme.py` — visual tokens.

## Where To Put Changes

| What you're changing | Where |
|---|---|
| Menu / category / action names | `ui_menu.py`, `ui_actions.py` |
| Action enablement / context panel | `viewer_widget_actions.py` |
| Sketch sessions | `viewer_widget_sketch_*.py` |
| Move / extrude / fillet / chamfer sessions | `viewer_widget_move_*.py` |
| Geometry behavior | `commands.py` + `command_*` helpers |
| Visual checks | `tests/perception/`, `dev/visual_window_probe.py` |

## Test Layout

- `tests/core/` — pure model, geometry, sketch, STEP contracts (no Qt).
- `tests/safety/` — command routing and mutation guardrails.
- `tests/ui/` — Qt-free or light-Qt UI state/action contracts.
- `tests/gui/` — real Qt/OCP window tests; gated by `CAD_APP_GUI_TESTS=1`.
- `tests/perception/` — screenshot and visual metric checks; gated by `CAD_APP_VISUAL_TESTS=1`.

## Non-Negotiable Contract Rules

- Face, edge, and vertex commands operate on the selected topology — never fall back silently to whole-body delete/move/rotate.
- `delete_object` is never a fallback for face/edge/vertex selection.
- Category rail clicks change mode/context only — they must not mutate geometry.
- View, camera, hover, and selection changes must not mutate model geometry.
- Undo/redo must protect every committed model mutation.
- `Scene` is the model source of truth; AIS objects are render state only.
- Do not weaken tests to make a patch pass — if product behavior changes intentionally, update docs and tests together.
- A passing unit test does not excuse a black/blank viewport; visual failures are real failures.

## Key Behavioral Rules (from PRODUCT_CONTRACT)

- Entering Sketch with no selection starts on the bottom XY plane; with a selected planar face it uses that face as workplane and feature host.
- Leaving Sketch without drawing discards the empty session.
- Fillet/chamfer is one tool: positive → fillet, negative → chamfer.
- Thread requires ISO/UNC/Custom preset, representation (Modeled/Cosmetic), type (Auto/External/Internal), and numeric pitch/length/depth before mutating the model.
- Boolean commands require an explicit target body and a separate tool body; they live in body context, not on the left rail.
- `new_sketch` exists only as a hidden compatibility alias; the visible label is `New Sketch (Face Plane)`.
