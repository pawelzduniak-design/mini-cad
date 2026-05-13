# Visual Testing

Visual tests protect the real user experience: window composition, visible
viewport content, nonblank screenshots, overlays, and mode clarity.

## What Counts As Visual Risk

- Viewport is black, blank, or mostly empty.
- Geometry exists in the model but is off-camera or not displayed.
- Category/context UI overlaps or hides commands.
- Sketch/selection/extrude mode is unclear in the HUD or context actions.
- Orientation gizmo, grid, markers, or overlays disappear unexpectedly.

## Test Layers

- `tests/gui/`: verifies the actual Qt/OCP window can initialize and react to
  basic actions.
- `tests/perception/`: captures screenshots and checks visual metrics.
- `dev/visual_window_probe.py`: richer manual/CI probe that saves screenshots
  and a JSON report under `out/visual_probe/`.

## Running Visual Checks

```powershell
.\run.ps1 gui
.\run.ps1 visual
```

`wglMakeCurrent() has failed` can appear during OCP/OpenGL teardown. Treat it as
noise only when pytest exits passing and screenshots are valid.
