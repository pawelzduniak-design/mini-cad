"""Integration workflow for the sketch tools (line, arc, circle, rectangle).

This script drives the same code paths a beginner triggers when clicking
in the sketch viewport, but at the UV/workplane level so the test does
not depend on screen pixels or HiDPI scaling. Each step asserts the
scene grew (or shrank) the way a real user would expect; the goal is
to surface regressions in:

- closing a line polyline (snap-back-to-start → profile face)
- arc commit on the third click
- arc + line co-operation (arc chord closed by line polyline)
- two-point profile tools (circle 2-point, center-radius, center rectangle)
- 3-point rectangle profile commit
- trim on top of mixed entities (line + circle, line + rectangle)
- Undo / Redo for sketch additions and trim

Every step prints `[PASS] ...` or `[FAIL] step N: ...`.
"""

from __future__ import annotations

import math
import sys
from typing import Any

from PySide6.QtWidgets import QApplication

from cad_app.main_window import create_main_window
from cad_app.scene import Scene
from cad_app.sketch import (
    SKETCH_ENTITY_META_KIND,
    SKETCH_META_KIND,
)
from cad_app.ui_sessions import SketchSession
from cad_app.viewer import Viewer
from cad_app.workplane import Workplane


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


def _fresh_scene() -> tuple[Scene, Any, Any]:
    """Open a new MainWindow + Scene with a sketch session ready on XY."""
    scene = Scene()
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget
    workplane = Workplane.world_xy()
    session = SketchSession(workplane, "XY", None, tool="line")
    widget._sketch_session = session
    widget._active_workplane = workplane
    widget._active_workplane_label = "XY"
    return scene, widget, main_window


def _profiles(scene: Scene) -> list[Any]:
    return [item for item in scene if item.meta.get("kind") == SKETCH_META_KIND]


def _entities(scene: Scene) -> list[Any]:
    return [item for item in scene if item.meta.get("kind") == SKETCH_ENTITY_META_KIND]


def _click(widget: Any, uv: tuple[float, float]) -> None:
    """Simulate one sketch viewport click at the given workplane UV."""
    widget._handle_sketch_click(widget._sketch_session, uv, 0, 0)


def _set_tool(widget: Any, tool: str) -> None:
    widget._sketch_session.tool = tool
    widget._sketch_session.points.clear()
    widget._sketch_session.start_uv = None


def _run(log: _Log) -> None:
    app = QApplication.instance() or QApplication([])
    _ = app

    # -----------------------------------------------------------------
    log.step("step1", "Line tool: open polyline does NOT create a profile yet")
    scene, widget, main_window = _fresh_scene()
    _set_tool(widget, "line")
    _click(widget, (0.0, 0.0))
    _click(widget, (40.0, 0.0))
    _click(widget, (40.0, 30.0))
    log.require(
        len(_profiles(scene)) == 0 and len(_entities(scene)) == 0,
        "Open polyline has no committed profile/entity",
    )
    log.require(
        len(widget._sketch_session.points) == 3,
        f"Session holds 3 in-progress points "
        f"({len(widget._sketch_session.points)})",
    )

    # -----------------------------------------------------------------
    log.step("step2", "Line tool: closing on first point creates a profile")
    _click(widget, (0.0, 30.0))
    _click(widget, (0.0, 0.0))  # snap back to start
    log.require(
        len(_profiles(scene)) == 1,
        f"Closed quad polyline became a profile ({len(_profiles(scene))})",
    )
    log.require(
        widget._sketch_session is not None and not widget._sketch_session.points,
        "Sketch session reset after profile commit",
    )
    main_window.window.close()

    # -----------------------------------------------------------------
    log.step("step3", "Arc tool: three clicks produce a sketch_entity edge")
    scene, widget, main_window = _fresh_scene()
    _set_tool(widget, "arc")
    _click(widget, (-20.0, 0.0))
    _click(widget, (20.0, 0.0))
    log.require(
        not _entities(scene),
        "Two arc clicks alone do not yet commit",
    )
    _click(widget, (0.0, 15.0))
    arcs = [it for it in _entities(scene) if it.meta.get("profile") == "arc"]
    log.require(
        len(arcs) == 1, f"Third arc click committed an arc entity ({len(arcs)})"
    )
    main_window.window.close()

    # -----------------------------------------------------------------
    log.step("step4", "Arc + line: closing a line chain on an existing arc")
    scene, widget, main_window = _fresh_scene()
    _set_tool(widget, "arc")
    _click(widget, (-30.0, 0.0))
    _click(widget, (30.0, 0.0))
    _click(widget, (0.0, 25.0))
    log.require(
        any(it.meta.get("profile") == "arc" for it in _entities(scene)),
        "Arc entity ready for the closing line chain",
    )
    _set_tool(widget, "line")
    _click(widget, (30.0, 0.0))
    _click(widget, (30.0, -10.0))
    _click(widget, (-30.0, -10.0))
    _click(widget, (-30.0, 0.0))  # land on arc start → arc+line profile
    arc_line_profiles = [
        it for it in _profiles(scene) if it.meta.get("profile") == "arc_polyline"
    ]
    log.require(
        len(arc_line_profiles) == 1,
        f"Arc + line chain produced an arc_polyline profile "
        f"({len(arc_line_profiles)})",
    )
    main_window.window.close()

    # -----------------------------------------------------------------
    log.step("step5", "Circle 2-point: two clicks set diameter")
    scene, widget, main_window = _fresh_scene()
    _set_tool(widget, "circle_diameter")
    _click(widget, (-20.0, 0.0))
    _click(widget, (20.0, 0.0))
    circle2 = [it for it in _profiles(scene) if it.meta.get("profile") == "circle"]
    log.require(len(circle2) == 1, "Circle 2-point committed a circle profile")
    main_window.window.close()

    # -----------------------------------------------------------------
    log.step("step6", "Circle center-radius: center + radius point")
    scene, widget, main_window = _fresh_scene()
    _set_tool(widget, "circle")
    _click(widget, (0.0, 0.0))
    _click(widget, (15.0, 0.0))
    circles = [it for it in _profiles(scene) if it.meta.get("profile") == "circle"]
    log.require(len(circles) == 1, "Circle center-radius committed a circle profile")
    main_window.window.close()

    # -----------------------------------------------------------------
    log.step("step7", "Center rectangle: center + corner")
    scene, widget, main_window = _fresh_scene()
    _set_tool(widget, "center_rectangle")
    _click(widget, (0.0, 0.0))
    _click(widget, (25.0, 15.0))
    rects = [
        it for it in _profiles(scene) if it.meta.get("profile") == "center_rectangle"
    ]
    log.require(len(rects) == 1, "Center rectangle committed a rectangle profile")
    main_window.window.close()

    # -----------------------------------------------------------------
    log.step("step8", "3-point rectangle: three corners produce a profile")
    scene, widget, main_window = _fresh_scene()
    _set_tool(widget, "rectangle_3_point")
    _click(widget, (0.0, 0.0))
    _click(widget, (40.0, 0.0))
    _click(widget, (40.0, 20.0))
    rects3 = [
        it for it in _profiles(scene) if it.meta.get("profile") == "rectangle_3_point"
    ]
    log.require(len(rects3) == 1, "3-point rectangle committed a rectangle profile")
    main_window.window.close()

    # -----------------------------------------------------------------
    log.step("step9", "Trim two intersecting circles, then undo and redo")
    scene, widget, main_window = _fresh_scene()
    _set_tool(widget, "circle")
    # center-radius tool: first click = center, second = radius point.
    _click(widget, (-25.0, 0.0))
    _click(widget, (15.0, 0.0))  # circle 1: center (-25,0), radius 40
    _click(widget, (25.0, 0.0))
    _click(widget, (65.0, 0.0))  # circle 2: center (25,0), radius 40 (overlaps)
    log.require(
        len(_profiles(scene)) >= 2,
        f"Two intersecting circles in scene ({len(_profiles(scene))})",
    )
    fingerprint_before_trim = _fingerprint(scene)

    _set_tool(widget, "trim")
    trimmed = widget._trim_segment_graph_at((-65.0, 0.0), max_distance=8.0)
    log.require(trimmed, "Trim of left outer arc reported success")
    log.require(
        _fingerprint(scene) != fingerprint_before_trim,
        "Scene fingerprint changed after trim",
    )

    log.info("Undo the trim")
    main_window.actions["undo"].trigger()
    log.require(
        _fingerprint(scene) == fingerprint_before_trim,
        "Undo restored the pre-trim scene exactly",
    )

    log.info("Redo brings the trim back")
    main_window.actions["redo"].trigger()
    log.require(
        _fingerprint(scene) != fingerprint_before_trim,
        "Redo re-applied the trim",
    )
    main_window.window.close()

    # -----------------------------------------------------------------
    log.step(
        "step10b",
        "Open line chain survives Finish Sketch as a reference entity",
    )
    scene, widget, main_window = _fresh_scene()
    _set_tool(widget, "line")
    _click(widget, (-20.0, 0.0))
    _click(widget, (20.0, 0.0))
    log.require(not _entities(scene), "Open line not yet persisted")
    widget._finish_sketch_sequence()
    line_entities = [
        it for it in _entities(scene) if it.meta.get("profile") == "line_segments"
    ]
    log.require(
        len(line_entities) == 1,
        "Open line preserved as construction entity after Finish "
        f"({len(line_entities)})",
    )
    main_window.window.close()

    # -----------------------------------------------------------------
    log.step("step10c", "Open line chain survives switching to another tool")
    scene, widget, main_window = _fresh_scene()
    _set_tool(widget, "line")
    _click(widget, (-25.0, -15.0))
    _click(widget, (25.0, -15.0))
    _click(widget, (25.0, 15.0))
    widget._set_sketch_tool("circle")  # tool switch should preserve the open chain
    line_entities = [
        it for it in _entities(scene) if it.meta.get("profile") == "line_segments"
    ]
    log.require(
        len(line_entities) == 1,
        "Open line preserved on tool switch " f"({len(line_entities)})",
    )
    main_window.window.close()

    # -----------------------------------------------------------------
    log.step("step10", "Undo a freshly committed sketch profile")
    scene, widget, main_window = _fresh_scene()
    _set_tool(widget, "center_rectangle")
    _click(widget, (0.0, 0.0))
    _click(widget, (10.0, 10.0))
    log.require(len(_profiles(scene)) == 1, "Rectangle committed")
    main_window.actions["undo"].trigger()
    log.require(
        len(_profiles(scene)) == 0,
        f"Undo removed the rectangle ({len(_profiles(scene))} profile(s) remain)",
    )
    main_window.actions["redo"].trigger()
    log.require(
        len(_profiles(scene)) == 1,
        "Redo restored the rectangle",
    )
    main_window.window.close()


def _fingerprint(scene: Scene) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        sorted(
            (
                item.item_id,
                str(item.meta.get("kind", "")),
                str(item.meta.get("profile", "")),
            )
            for item in scene
        )
    )


def main() -> int:
    log = _Log()
    sys.stdout.write("=== SKETCH TOOLS WORKFLOW ===\n")
    try:
        _run(log)
    except Exception as exc:  # noqa: BLE001
        log.fail(f"Unhandled exception: {type(exc).__name__}: {exc}")
        import traceback

        traceback.print_exc()
    # silence unused
    _ = math
    if log.failed:
        sys.stdout.write("\n=== RESULT: FAIL ===\n")
        return 1
    sys.stdout.write("\n=== RESULT: PASS ===\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
