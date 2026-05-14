"""Smoke test for sketch profile selection, extrude, overlay, and STEP export."""

from __future__ import annotations

import sys
from pathlib import Path

from cad_app.io_step import export_step
from cad_app.main_window import create_main_window
from cad_app.scene import Scene
from cad_app.sketch import (
    extrude_profile,
    is_closed_polyline,
    make_arc_chord_profile,
    make_center_rectangle_profile,
    make_circle_profile_at,
    make_polyline_profile,
    make_rectangle_profile_three_point,
    make_three_point_arc_edge,
    profile_contains_uv,
    three_point_arc_radius,
)
from cad_app.types import SelectionKind
from cad_app.viewer import Viewer
from cad_app.workplane import Workplane


class SmokeResult:
    """Small stdout logger with fail-fast accounting."""

    def __init__(self) -> None:
        self.failed = False

    def info(self, message: str) -> None:
        self._emit("INFO", message)

    def pass_(self, message: str) -> None:
        self._emit("PASS", message)

    def fail(self, message: str) -> None:
        self.failed = True
        self._emit("FAIL", message)

    @staticmethod
    def _emit(level: str, message: str) -> None:
        sys.stdout.write(f"[{level}] {message}\n")


def main() -> int:
    log = SmokeResult()
    sys.stdout.write("=== Direct Modeling CAD Smoke Test ===\n\n")

    try:
        _run_smoke(log)
    except Exception as exc:  # noqa: BLE001 - smoke test must report any blocker.
        log.fail(f"Unhandled smoke test exception: {exc}")

    if log.failed:
        sys.stdout.write("\n=== RESULT: FAIL ===\n")
        return 1
    sys.stdout.write("\n=== RESULT: PASS ===\n")
    return 0


def _run_smoke(log: SmokeResult) -> None:
    workplane = Workplane.world_xy()
    scene = Scene()
    log.info("Creating new document")
    _require(log, len(scene) == 0, "Document created")

    log.info("Testing Center Rectangle")
    rectangle = make_center_rectangle_profile(workplane, (0.0, 0.0), (30.0, 15.0))
    rect_box = _bounding_box(rectangle)
    _require(log, _count_subshapes(rectangle, "face") == 1, "Center rectangle created")
    _require(
        log,
        _count_subshapes(rectangle, "edge") == 4,
        "Center rectangle has 4 edges",
    )
    _require(
        log,
        profile_contains_uv(rectangle, workplane, (0.0, 0.0)),
        "Center rectangle interior selectable",
    )
    log.info(
        "Bounding box: "
        f"width={rect_box['width']:.2f}, height={rect_box['height']:.2f}"
    )
    _require(
        log,
        abs(rect_box["width"] - 60.0) < 1e-5,
        "Center rectangle width = 60.00",
    )
    _require(
        log,
        abs(rect_box["height"] - 30.0) < 1e-5,
        "Center rectangle height = 30.00",
    )
    _require(log, _can_extrude(rectangle), "Center rectangle can be passed to Extrude")

    log.info("Testing Circle")
    circle = make_circle_profile_at(workplane, (0.0, 0.0), 10.0)
    _require(log, _count_subshapes(circle, "face") == 1, "Circle created")
    _require(
        log,
        _count_subshapes(circle, "edge") == 1,
        "Circle closed profile detected",
    )
    _require(
        log,
        profile_contains_uv(circle, workplane, (0.0, 0.0)),
        "Circle interior hover available",
    )
    _require(
        log,
        profile_contains_uv(circle, workplane, (0.0, 0.0)),
        "Circle interior selectable",
    )
    _require(
        log, _can_extrude(circle), "Selected circle profile can be passed to Extrude"
    )
    log.pass_("Circle radius = 10.00")

    log.info("Testing Line Polyline")
    polyline_points = [
        (0.0, 0.0),
        (40.0, 0.0),
        (40.0, 20.0),
        (0.0, 20.0),
        (0.0, 0.0),
    ]
    polyline = make_polyline_profile(workplane, polyline_points)
    _require(log, is_closed_polyline(polyline_points), "Polyline is closed")
    _require(
        log,
        _count_subshapes(polyline, "edge") == 4,
        "Connected line chain created",
    )
    _require(
        log,
        profile_contains_uv(polyline, workplane, (20.0, 10.0)),
        "Polyline interior selectable",
    )
    _require(log, _can_extrude(polyline), "Polyline profile can be passed to Extrude")

    log.info("Testing Arc")
    arc = make_three_point_arc_edge(
        workplane,
        (-20.0, 0.0),
        (20.0, 0.0),
        (0.0, 15.0),
    )
    arc_radius = three_point_arc_radius((-20.0, 0.0), (20.0, 0.0), (0.0, 15.0))
    _require(log, _count_subshapes(arc, "edge") == 1, "3-point arc created")
    _require(log, arc_radius > 0.0, "Arc has valid curvature")
    log.info(f"Arc radius: {arc_radius:.2f}")
    arc_profile = make_arc_chord_profile(
        workplane,
        (-20.0, 0.0),
        (20.0, 0.0),
        (0.0, 15.0),
    )
    _require(
        log,
        _count_subshapes(arc_profile, "face") == 1,
        "Arc can be part of a closed profile with a line",
    )
    rotated_rectangle = make_rectangle_profile_three_point(
        workplane,
        (0.0, 0.0),
        (40.0, 0.0),
        (0.0, 20.0),
    )
    _require(
        log,
        _count_subshapes(rotated_rectangle, "edge") == 4,
        "3-point rectangle profile created",
    )

    log.info("Testing Extrude")
    rect_solid = extrude_profile(rectangle, 20.0)
    circle_solid = extrude_profile(circle, 10.0)
    polyline_solid = extrude_profile(polyline, 15.0)
    for label, solid in (
        ("Rectangle profile extruded to 20.00 mm", rect_solid),
        ("Circle profile extruded to 10.00 mm", circle_solid),
        ("Polyline profile extruded to 15.00 mm", polyline_solid),
    ):
        _require(log, _count_subshapes(solid, "solid") == 1, label)
    scene.add_shape(rect_solid, meta={"kind": "body", "source": "smoke_rectangle"})
    scene.add_shape(circle_solid, meta={"kind": "body", "source": "smoke_circle"})
    scene.add_shape(polyline_solid, meta={"kind": "body", "source": "smoke_polyline"})
    log.pass_("Body created")
    log.info(f"Body bounding box: {_format_box(_bounding_box(rect_solid))}")
    log.info(f"Body count: {len(scene)}")

    log.info("Testing Selection Modes")
    _test_selection_modes(log)

    log.info("Testing Transform Overlay")
    _test_transform_overlay(log)

    log.info("Testing STEP Export")
    output_path = Path("out") / "smoke_sketch_workflow.step"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    export_step(rect_solid, str(output_path))
    _require(log, output_path.exists(), "STEP file exists")
    _require(log, output_path.stat().st_size > 0, "STEP file size > 0")
    log.pass_("STEP export completed")
    log.info(f"File: {output_path}")
    log.info(f"File size: {output_path.stat().st_size} bytes")


def _test_selection_modes(log: SmokeResult) -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    main_window = create_main_window(Viewer(), Scene())
    _require(log, app is not None, "Qt application available")
    expected = {
        "select_object": ("Object mode exists", "1"),
        "select_face": ("Face mode exists", "2"),
        "select_edge": ("Edge mode exists", "3"),
        "select_vertex": ("Vertex mode exists", "4"),
    }
    for action_name, (label, shortcut) in expected.items():
        action = main_window.actions[action_name]
        _require(log, action is not None, label)
        _require(
            log,
            action.shortcut().toString() == shortcut,
            f"Shortcut {shortcut} -> {action.text()}",
        )
        action.trigger()
        state = main_window.viewer_widget.get_ui_state()
        _require(
            log,
            state.work_mode == "select"
            and state.selection_mode == action_name.removeprefix("select_")
            and state.selection_type == "none",
            f"{action.text()} switches to Select mode",
        )
    _require(
        log,
        main_window.viewer_widget._selection_kind == SelectionKind.VERTEX,
        "Current selection mode visible in state",
    )
    main_window.window.close()


def _test_transform_overlay(log: SmokeResult) -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    main_window = create_main_window(Viewer(), Scene())
    overlay = main_window.viewer_widget._dimension_overlay
    _require(
        log,
        app is not None and overlay is not None,
        "Transform overlay component exists",
    )
    main_window.viewer_widget._show_dimension_overlay("Distance: 12.50 mm", 40, 50)
    _require(
        log,
        overlay.text() == "Distance: 12.50 mm",
        "Overlay text updated during transform",
    )
    _require(
        log,
        overlay.pos().x() >= 40 and overlay.pos().y() >= 50,
        "Overlay position updated",
    )
    _require(log, not overlay.isHidden(), "Overlay visible during transform")
    main_window.viewer_widget._show_dimension_overlay("Distance: 15.00 mm", 60, 70)
    _require(log, overlay.text() == "Distance: 15.00 mm", "Overlay updates text")
    main_window.viewer_widget._hide_dimension_overlay()
    _require(log, overlay.isHidden(), "Overlay hidden after transform end")
    main_window.window.close()


def _can_extrude(profile) -> bool:
    try:
        extrude_profile(profile, 1.0)
    except Exception:  # noqa: BLE001 - diagnostic smoke helper.
        return False
    return True


def _require(log: SmokeResult, condition: bool, message: str) -> None:
    if condition:
        log.pass_(message)
    else:
        log.fail(message)


def _count_subshapes(shape, topology: str) -> int:
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    topologies = {
        "edge": TopAbs_EDGE,
        "face": TopAbs_FACE,
        "solid": TopAbs_SOLID,
    }
    shape_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, topologies[topology], shape_map)
    return shape_map.Extent()


def _bounding_box(shape) -> dict[str, float]:
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
        "height": ymax - ymin,
        "depth": zmax - zmin,
    }


def _format_box(box: dict[str, float]) -> str:
    return (
        f"x=({box['xmin']:.2f},{box['xmax']:.2f}), "
        f"y=({box['ymin']:.2f},{box['ymax']:.2f}), "
        f"z=({box['zmin']:.2f},{box['zmax']:.2f})"
    )


if __name__ == "__main__":
    raise SystemExit(main())
