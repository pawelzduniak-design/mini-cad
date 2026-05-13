# Architecture

## Entry Points

- `cad_app/app.py`: application startup.
- `cad_app/main_window.py`: public window factory.
- `cad_app/ui_actions.py`: QAction creation and shortcuts.
- `cad_app/ui_layout.py`: shell layout.
- `cad_app/ui_menu.py`: declarative category/action groups.
- `cad_app/viewer_widget.py`: composed interaction controller.

## Model And UI State

- `cad_app/scene.py`: authoritative model state, active item, selection,
  undo/redo snapshots.
- `cad_app/types.py`: shared dataclasses and enums.
- `cad_app/ui_sessions.py`: transient UI-only sessions for move/sketch tools.
- `cad_app/viewer_widget_state_snapshot.py`: stable `get_ui_state()` contract.

`Scene` is the model source of truth. Viewer AIS objects are render state and
should not be used as model assertions.

## Geometry

- `cad_app/engine.py`: primitive shape creation.
- `cad_app/commands.py`: public direct-modeling command facade.
- `cad_app/command_geometry.py`: geometry operation helpers.
- `cad_app/command_topology.py`: subshape lookup and workplane extraction.
- `cad_app/command_rounding.py`: fillet/chamfer support.
- `cad_app/command_convex.py`: legacy fallback support; use cautiously.
- `cad_app/feature_history.py`: editable feature tree steps, rebuild,
  rollback, and topological reference remapping.
- `cad_app/sketch.py`: sketch profiles and profile utilities.
- `cad_app/sketch_features.py`: sketch-driven solid features.
- `cad_app/thread_specs.py`: ISO/UNC/custom thread preset dimensions and
  validation.
- `cad_app/io_step.py`: STEP import/export.

## Rendering

- `cad_app/viewer.py`: OCP viewer bridge.
- `cad_app/viewer_markers.py`: selection, hover, preview, sketch, dimension
  marker rendering.
- `cad_app/viewer_shapes.py`: render helper shapes.
- `cad_app/viewer_widget_overlays.py`: Qt overlays above the viewport.
- `cad_app/theme.py`: UI and viewport visual tokens.

## Where To Put Changes

- Menu/category/action names: `ui_menu.py` and `ui_actions.py`.
- Action enablement/context panel: `viewer_widget_actions.py`.
- Sketch sessions: `viewer_widget_sketch_*.py`.
- Move/extrude/fillet/chamfer sessions: `viewer_widget_move_*.py`.
- Geometry behavior: `commands.py` plus `command_*` helper modules.
- Visual checks: `tests/perception/` and `dev/visual_window_probe.py`.
