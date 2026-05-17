"""Workflow smoke for trimming two intersecting sketch circles."""

from __future__ import annotations

import math
import sys

from PySide6.QtWidgets import QApplication

from cad_app.main_window import create_main_window
from cad_app.scene import Scene
from cad_app.sketch import SKETCH_ENTITY_META_KIND, SKETCH_META_KIND
from cad_app.sketch_graph import (
    SketchGraphSource,
    _point_atomic_distance,
    curves_from_meta,
    segments_from_meta,
    split_sources_at_intersections,
)
from cad_app.ui_sessions import SketchSession
from cad_app.viewer import Viewer
from cad_app.workplane import Workplane

INTERSECTION_V = math.sqrt(40.0**2 - 25.0**2)


class WorkflowLog:
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
    log = WorkflowLog()
    sys.stdout.write("=== Trim Circles Workflow Smoke ===\n\n")
    try:
        _run(log)
    except Exception as exc:  # noqa: BLE001 - workflow smoke must report blockers.
        log.fail(f"Unhandled workflow exception: {type(exc).__name__}: {exc}")
    if log.failed:
        sys.stdout.write("\n=== RESULT: FAIL ===\n")
        return 1
    sys.stdout.write("\n=== RESULT: PASS ===\n")
    return 0


def _run(log: WorkflowLog) -> None:
    app = QApplication.instance() or QApplication([])
    _require(log, app is not None, "Qt application available")

    scene, widget = _new_circle_scene()
    log.info("Draw two intersecting circles and split them into regions")
    _require(
        log,
        _profile_roles(scene) == {"base", "intersection", "tool"},
        "Two-circle regionization produced base/intersection/tool",
    )
    atomic = _atomic_segments(scene)
    _require(log, len(atomic) == 4, "Two circles split into four atomic arcs")
    _require(log, all(edge.kind == "arc" for edge in atomic), "All atomics are arcs")
    _require(log, _session_ids_are_live(widget, scene), "Sketch session IDs are live")

    log.info("Trim the left outer arc")
    _require(
        log,
        widget._trim_segment_graph_at((-65.0, 0.0), max_distance=8.0),
        "Left outer arc trim returned success",
    )
    _require(log, _has_arc_segment(scene), "Left trim preserved an open arc segment")
    _require(
        log,
        {"intersection", "tool"} <= _profile_roles(scene),
        "Left trim kept the overlap and right-circle regions",
    )
    _require(log, _all_sketch_meta_valid(scene), "Left trim metadata is complete")
    _require(log, _session_ids_are_live(widget, scene), "Session IDs survived trim")

    log.info("Trim the right outer arc after the first trim")
    _require(
        log,
        widget._trim_segment_graph_at((65.0, 0.0), max_distance=8.0),
        "Right outer arc trim returned success",
    )
    _require(log, len(_sketch_objects(scene)) > 0, "Repeated trim kept sketch objects")
    _require(log, _all_sketch_meta_valid(scene), "Repeated trim metadata is complete")

    log.info("Trim a shared overlap arc in a fresh scene")
    shared_scene, shared_widget = _new_circle_scene()
    shared_click = (15.0, 0.0)
    _require(
        log,
        _nearest_distance(shared_scene, shared_click) < 1e-5,
        "Shared arc click starts on sketch geometry",
    )
    _require(
        log,
        shared_widget._trim_segment_graph_at(shared_click, max_distance=8.0),
        "Shared arc trim returned success",
    )
    _require(
        log,
        _nearest_distance(shared_scene, shared_click) > 8.0,
        "Shared arc was removed from the clicked location",
    )
    _require(
        log,
        len(_sketch_objects(shared_scene)) >= 2,
        "Shared trim did not delete both circles",
    )
    _require(
        log,
        _all_sketch_meta_valid(shared_scene),
        "Shared trim metadata is complete",
    )

    log.info("Click the empty overlap center")
    noop_scene, noop_widget = _new_circle_scene()
    before = _scene_fingerprint(noop_scene)
    _require(
        log,
        not noop_widget._trim_segment_graph_at((0.0, 0.0), max_distance=8.0),
        "Empty overlap center is not trimmed",
    )
    _require(
        log,
        _scene_fingerprint(noop_scene) == before,
        "Empty overlap center leaves scene unchanged",
    )

    for window in (
        widget.window(),
        shared_widget.window(),
        noop_widget.window(),
    ):
        window.close()


def _new_circle_scene():
    scene = Scene()
    workplane = Workplane.world_xy()
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget
    session = SketchSession(workplane, "XY", None, tool="circle")
    widget._sketch_session = session
    widget._active_workplane = workplane
    widget._active_workplane_label = "XY"
    widget._handle_two_point_profile_click(session, (-25.0, 0.0), 30, 30)
    widget._handle_two_point_profile_click(session, (15.0, 0.0), 70, 30)
    widget._handle_two_point_profile_click(session, (25.0, 0.0), 80, 30)
    widget._handle_two_point_profile_click(session, (65.0, 0.0), 120, 30)
    return scene, widget


def _require(log: WorkflowLog, condition: bool, message: str) -> None:
    if condition:
        log.pass_(message)
    else:
        log.fail(message)


def _profile_roles(scene: Scene) -> set[object]:
    return {
        item.meta.get("region_role")
        for item in scene
        if item.meta.get("kind") == SKETCH_META_KIND
    }


def _sketch_objects(scene: Scene):
    return [
        item
        for item in scene
        if item.meta.get("kind") in {SKETCH_META_KIND, SKETCH_ENTITY_META_KIND}
    ]


def _sketch_sources(scene: Scene) -> tuple[SketchGraphSource, ...]:
    return tuple(
        SketchGraphSource(
            item.item_id,
            segments_from_meta(item.meta),
            dict(item.meta),
            curves_from_meta(item.meta),
        )
        for item in _sketch_objects(scene)
    )


def _atomic_segments(scene: Scene):
    return split_sources_at_intersections(_sketch_sources(scene))


def _nearest_distance(scene: Scene, uv: tuple[float, float]) -> float:
    return min(_point_atomic_distance(uv, edge) for edge in _atomic_segments(scene))


def _has_arc_segment(scene: Scene) -> bool:
    return any(
        item.meta.get("kind") == SKETCH_ENTITY_META_KIND
        and item.meta.get("profile") == "arc_segment"
        for item in scene
    )


def _all_sketch_meta_valid(scene: Scene) -> bool:
    for item in _sketch_objects(scene):
        if item.meta.get("workplane") != "XY":
            return False
        if "display_normal" not in item.meta:
            return False
        if "workplane_origin" not in item.meta:
            return False
        if "workplane_x_direction" not in item.meta:
            return False
        if "workplane_y_direction" not in item.meta:
            return False
        if not (item.meta.get("segments_uv") or item.meta.get("curves_uv")):
            return False
    return True


def _session_ids_are_live(widget, scene: Scene) -> bool:
    session = widget._sketch_session
    if session is None:
        return False
    return len(session.profile_ids) == len(set(session.profile_ids)) and all(
        item_id in scene for item_id in session.profile_ids
    )


def _scene_fingerprint(scene: Scene) -> tuple[tuple[str, object, object], ...]:
    return tuple(
        sorted(
            (
                item.item_id,
                item.meta.get("kind"),
                item.meta.get("profile"),
            )
            for item in scene
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
