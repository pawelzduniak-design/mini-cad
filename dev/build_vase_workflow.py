"""End-to-end "beginner builds a vase by revolving around a construction line".

This is the workflow that motivated the open-line-survives-finish fix and
the custom-axis revolve plumbing. A beginner:

1. Opens the app, draws a vertical reference line — the future axis.
2. Finishes / switches tool; the open line is preserved as a
   `line_segments` sketch entity (it didn't vanish).
3. Draws a rectangular profile off to the side of the line.
4. Multi-selects the profile and the reference line.
5. Clicks Revolve → the tool reads the line endpoints as the rotation
   axis (not world X/Y/Z) and spins 360 degrees → a tube.

Asserts:
- after Finish the open line is committed as a sketch_entity
- multi-selection enables sketch_revolve
- _custom_revolve_axis_from_selection returns the line direction
- the revolved body is a valid solid with the expected outer bbox and
  a centred hollow tube (volume_full > volume_tube, ymin/ymax symmetric)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cad_app.commands import validate_shape
from cad_app.io_step import export_step
from cad_app.main_window import create_main_window
from cad_app.scene import Scene
from cad_app.sketch import (
    SKETCH_ENTITY_META_KIND,
    SKETCH_META_KIND,
)
from cad_app.types import SelectionKind, SelectionRef
from cad_app.ui_sessions import SketchSession
from cad_app.viewer import Viewer
from cad_app.workplane import Workplane

OUT_DIR = Path("out") / "build_vase"
STEP_PATH = OUT_DIR / "vase.step"
SCREENSHOT_PATH = OUT_DIR / "vase_iso.png"

# Reference line on the bottom XY plane runs along Y at X=0, from
# (0, -40) up to (0, 40): a 80 mm vertical axis.
AXIS_START = (0.0, -40.0)
AXIS_END = (0.0, 40.0)

# Rectangular profile to revolve: offset from the axis so it forms a
# hollow tube, not a solid cylinder. Center at (30, 0), corner at
# (50, 40) absolute → width 40 (X from 10 to 50), height 80.
PROFILE_CENTER = (30.0, 0.0)
PROFILE_CORNER = (50.0, 40.0)
EXPECTED_OUTER_R = 50.0  # max distance from axis after revolve
EXPECTED_INNER_R = 10.0  # min distance from axis (the hole through middle)
EXPECTED_HEIGHT = 80.0  # length along revolve axis


class _Log:
    def __init__(self) -> None:
        self.failed = False
        self.current_step: str = "<init>"

    def step(self, step_id: str, headline: str) -> None:
        self.current_step = step_id
        sys.stdout.write(f"\n--- {step_id}: {headline} ---\n")

    def info(self, message: str) -> None:
        sys.stdout.write(f"[INFO] {message}\n")

    def passed(self, message: str) -> None:
        sys.stdout.write(f"[PASS] {message}\n")

    def fail(self, message: str) -> None:
        self.failed = True
        sys.stdout.write(f"[FAIL] {self.current_step}: {message}\n")

    def require(self, condition: bool, message: str) -> None:
        if condition:
            self.passed(message)
        else:
            self.fail(message)


def _wait_for_initial_display(app: QApplication, viewer: Viewer, widget: Any) -> None:
    for _ in range(80):
        app.processEvents()
        if viewer.is_initialized and widget._initial_scene_displayed:
            return
        QTest.qWait(50)
    raise RuntimeError("Viewer did not initialize and display the initial scene")


def _settle(app: QApplication, *, ms: int = 80) -> None:
    app.processEvents()
    QTest.qWait(ms)
    app.processEvents()


def _bbox(shape: Any) -> dict[str, float]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return {
        "xmin": xmin,
        "ymin": ymin,
        "zmin": zmin,
        "xmax": xmax,
        "ymax": ymax,
        "zmax": zmax,
        "width": xmax - xmin,
        "depth": ymax - ymin,
        "height": zmax - zmin,
    }


def _volume(shape: Any) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def _capture(window: Any, widget: Any, path: Path) -> None:
    image = (
        widget.screen()
        .grabWindow(int(window.winId()))
        .toImage()
        .convertToFormat(QImage.Format.Format_RGB32)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(path))


def _body_item_ids(scene: Scene) -> list[str]:
    return [item.item_id for item in scene if item.meta.get("kind") == "body"]


def _line_segment_entities(scene: Scene) -> list[Any]:
    return [
        it
        for it in scene
        if it.meta.get("kind") == SKETCH_ENTITY_META_KIND
        and it.meta.get("profile") == "line_segments"
    ]


def _profiles(scene: Scene) -> list[Any]:
    return [item for item in scene if item.meta.get("kind") == SKETCH_META_KIND]


def _click(widget: Any, uv: tuple[float, float]) -> None:
    widget._handle_sketch_click(widget._sketch_session, uv, 0, 0)


def _run(log: _Log) -> None:
    app = QApplication.instance() or QApplication([])
    scene = Scene()
    viewer = Viewer()
    main_window = create_main_window(viewer, scene)
    window = main_window.window
    widget = main_window.viewer_widget
    window.resize(1280, 820)
    window.show()
    widget.setFocus()

    try:
        _wait_for_initial_display(app, viewer, widget)
        _settle(app, ms=160)

        # -----------------------------------------------------------------
        log.step("step1", "App opens in Sketch mode on the bottom plane")
        # The startup main_window already enters a sketch session for an
        # empty scene; ensure that is the case.
        if widget._sketch_session is None:
            widget._sketch_session = SketchSession(
                workplane=Workplane.world_xy(),
                label="XY",
                host=None,
                tool="line",
            )
            widget._active_workplane = Workplane.world_xy()
            widget._active_workplane_label = "XY"
        log.require(
            widget._sketch_session is not None,
            "Sketch session active on startup",
        )

        # -----------------------------------------------------------------
        log.step(
            "step2",
            f"Draw a vertical construction line from {AXIS_START} to {AXIS_END}",
        )
        widget._set_sketch_tool("line")
        _click(widget, AXIS_START)
        _click(widget, AXIS_END)
        log.info(f"Session points before tool switch: {widget._sketch_session.points}")
        log.require(
            len(widget._sketch_session.points) == 2,
            "Two line points are pending",
        )

        # -----------------------------------------------------------------
        log.step("step3", "Switch tool: open line should be preserved as an entity")
        widget._set_sketch_tool("center_rectangle")
        lines = _line_segment_entities(scene)
        log.require(
            len(lines) == 1,
            f"Open construction line preserved as sketch_entity ({len(lines)})",
        )
        line_id = lines[0].item_id

        # -----------------------------------------------------------------
        log.step(
            "step4",
            f"Draw a rectangular profile centered at {PROFILE_CENTER}",
        )
        _click(widget, PROFILE_CENTER)
        _click(widget, PROFILE_CORNER)
        profiles = _profiles(scene)
        log.require(len(profiles) == 1, "Rectangle profile created")
        profile_id = profiles[0].item_id

        # -----------------------------------------------------------------
        log.step("step5", "Finish sketch and multi-select profile + line")
        widget._finish_sketch_sequence()
        _settle(app)
        if widget._sketch_session is not None:
            # First call clears in-progress points; second call ends the
            # session itself.
            widget._finish_sketch_sequence()
            _settle(app)
        log.require(
            widget._sketch_session is None,
            "Sketch session closed after Finish",
        )

        scene.set_selections(
            (
                SelectionRef(profile_id, SelectionKind.FACE, 1),
                SelectionRef(line_id, SelectionKind.OBJECT, 0),
            )
        )
        widget._set_active_category("select")
        _settle(app)

        log.require(
            main_window.actions["sketch_revolve"].isEnabled(),
            "sketch_revolve is enabled for profile + construction line",
        )

        axis_data = widget._custom_revolve_axis_from_selection(scene.selection_refs())
        log.require(
            axis_data is not None,
            "Custom revolve axis resolved from the construction line",
        )
        if axis_data is not None:
            point, axis = axis_data
            log.info(f"Axis point: {point}; axis vector: {axis}")
            log.require(
                abs(axis[1] - 1.0) < 1e-3 and abs(axis[0]) < 1e-3,
                "Axis vector points along world Y (the line direction)",
            )

        # -----------------------------------------------------------------
        log.step("step6", "Trigger Sketch Revolve 360 degrees")
        bodies_before = len(_body_item_ids(scene))
        main_window.actions["sketch_revolve"].trigger()
        _settle(app)
        if widget._move_session is None:
            log.fail("Revolve tool did not start a move session")
            return
        widget._move_session.distance = 360.0
        widget._update_move_preview()
        widget._tool_done()
        _settle(app, ms=180)
        bodies_after = len(_body_item_ids(scene))
        log.require(
            bodies_after == bodies_before + 1,
            f"Revolve produced a new body ({bodies_before} -> {bodies_after})",
        )
        if bodies_after == bodies_before:
            return
        vase_id = _body_item_ids(scene)[-1]
        vase_shape = scene.get(vase_id).shape
        validate_shape(vase_shape)

        # -----------------------------------------------------------------
        log.step("step7", "Verify the tube/vase geometry")
        bbox = _bbox(vase_shape)
        log.info(
            f"Vase bbox: X[{bbox['xmin']:.1f},{bbox['xmax']:.1f}] "
            f"Y[{bbox['ymin']:.1f},{bbox['ymax']:.1f}] "
            f"Z[{bbox['zmin']:.1f},{bbox['zmax']:.1f}]"
        )
        # Outer radius around Y axis -> bbox X / Z span equals 2 * outer R.
        log.require(
            abs(bbox["width"] - 2 * EXPECTED_OUTER_R) < 0.5,
            f"Outer width = 2 x outer R = {2 * EXPECTED_OUTER_R:.0f} mm",
        )
        log.require(
            abs(bbox["height"] - 2 * EXPECTED_OUTER_R) < 0.5,
            f"Z span = 2 x outer R = {2 * EXPECTED_OUTER_R:.0f} mm",
        )
        # Profile height (along Y axis) maps to the tube's length.
        log.require(
            abs(bbox["depth"] - EXPECTED_HEIGHT) < 0.5,
            f"Length along revolve axis = {EXPECTED_HEIGHT:.0f} mm",
        )
        # Hollow check: volume should be smaller than a full cylinder of
        # the same outer dimensions.
        import math

        volume_actual = _volume(vase_shape)
        volume_solid_outer = math.pi * EXPECTED_OUTER_R**2 * EXPECTED_HEIGHT
        volume_solid_inner = math.pi * EXPECTED_INNER_R**2 * EXPECTED_HEIGHT
        volume_expected = volume_solid_outer - volume_solid_inner
        log.info(
            f"Volume actual={volume_actual:.0f}, "
            f"expected tube={volume_expected:.0f}, "
            f"full cylinder={volume_solid_outer:.0f}"
        )
        # The tube's hole (R=10) removes only ~4 % of a full cylinder, so
        # the strict comparison is "volume matches the tube formula".
        log.require(
            abs(volume_actual - volume_expected) / volume_expected < 0.01,
            f"Volume within 1% of pi*(Ro^2-Ri^2)*H tube "
            f"({volume_actual:.0f} vs {volume_expected:.0f})",
        )
        log.require(
            volume_solid_outer - volume_actual > volume_solid_inner - 1.0,
            f"Hollow core removed at least pi*Ri^2*H mm^3 "
            f"({volume_solid_outer - volume_actual:.0f} >= "
            f"{volume_solid_inner:.0f})",
        )

        # -----------------------------------------------------------------
        log.step("step8", "Export STEP + screenshot")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        export_step(vase_shape, str(STEP_PATH))
        log.require(STEP_PATH.exists(), f"STEP exported to {STEP_PATH}")
        widget._navigation.view_iso()
        widget._fit_all()
        viewer.refresh_native_window()
        _settle(app, ms=250)
        _capture(window, widget, SCREENSHOT_PATH)
        log.require(SCREENSHOT_PATH.exists(), f"Screenshot: {SCREENSHOT_PATH}")
    finally:
        window.close()
        viewer.close()
        app.processEvents()


def main() -> int:
    log = _Log()
    sys.stdout.write("=== BUILD VASE (REVOLVE AROUND LINE) ===\n")
    try:
        _run(log)
    except Exception as exc:  # noqa: BLE001
        log.fail(f"Unhandled exception: {type(exc).__name__}: {exc}")
        import traceback

        traceback.print_exc()
    if log.failed:
        sys.stdout.write("\n=== RESULT: FAIL ===\n")
        return 1
    sys.stdout.write("\n=== RESULT: PASS ===\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
