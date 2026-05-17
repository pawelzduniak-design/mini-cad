"""Stress-test the sketch trim tool against multiple problem shapes.

trim_circles_workflow already covers the canonical "two circles" case.
This script runs cases that the production logs say `loops=0` for or
that beginners hit repeatedly:

A) Two crossing straight lines (open polylines), trim at the cross
B) A straight line crossing a circle, trim the line piece outside
C) A line crossing a circle, trim the arc inside the line's reach
D) Three overlapping circles (multiple intersections)
E) Click far from any geometry (should be a no-op, never fail)
F) Click on the cross-vertex itself (no segment under the cursor)
G) Trim on a freshly drawn open line entity (line_segments kind)
H) Two collinear segments meeting end-to-end (degenerate "intersection")

For every case we print before/after counts and either PASS or FAIL so
a regression in `trim_segment_graph` immediately surfaces.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from cad_app.main_window import create_main_window
from cad_app.scene import Scene
from cad_app.sketch import SKETCH_ENTITY_META_KIND, SKETCH_META_KIND
from cad_app.ui_sessions import SketchSession
from cad_app.viewer import Viewer
from cad_app.workplane import Workplane


class _Log:
    def __init__(self) -> None:
        self.failed = False
        self.current_case: str = "<init>"

    def case(self, case_id: str, headline: str) -> None:
        self.current_case = case_id
        sys.stdout.write(f"\n--- {case_id}: {headline} ---\n")

    def info(self, message: str) -> None:
        sys.stdout.write(f"[INFO] {message}\n")

    def passed(self, message: str) -> None:
        sys.stdout.write(f"[PASS] {message}\n")

    def fail(self, message: str) -> None:
        self.failed = True
        sys.stdout.write(f"[FAIL] {self.current_case}: {message}\n")

    def require(self, condition: bool, message: str) -> None:
        if condition:
            self.passed(message)
        else:
            self.fail(message)


def _fresh_widget():
    scene = Scene()
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget
    wp = Workplane.world_xy()
    widget._sketch_session = SketchSession(wp, "XY", None, tool="line")
    widget._active_workplane = wp
    widget._active_workplane_label = "XY"
    return scene, widget, main_window


def _click(widget, uv):
    widget._handle_sketch_click(widget._sketch_session, uv, 0, 0)


def _set_tool(widget, tool):
    widget._sketch_session.tool = tool
    widget._sketch_session.points.clear()
    widget._sketch_session.start_uv = None


def _count_sketch_items(scene: Scene) -> dict[str, int]:
    profiles = sum(1 for it in scene if it.meta.get("kind") == SKETCH_META_KIND)
    entities = sum(1 for it in scene if it.meta.get("kind") == SKETCH_ENTITY_META_KIND)
    return {"profile": profiles, "entity": entities, "total": profiles + entities}


def _nearest_distance_to_geometry(widget, uv) -> float | None:
    """Distance from uv to the nearest atomic segment in the current
    sketch (mirrors the picker used internally by trim_segment_graph)."""
    from cad_app.sketch_graph import (
        _point_atomic_distance,
        split_sources_at_intersections,
    )

    workplane = widget._active_workplane
    sources = widget._sketch_graph_sources(workplane)
    atomics = split_sources_at_intersections(sources)
    if not atomics:
        return None
    return min(_point_atomic_distance(uv, seg) for seg in atomics)


def _total_atomic_length(widget) -> float:
    """Sum of every atomic segment's length in the current sketch. After
    a successful trim this should drop by the length of the removed
    atomic. If it stays the same, nothing was actually cut."""
    import math

    from cad_app.sketch_graph import split_sources_at_intersections

    workplane = widget._active_workplane
    sources = widget._sketch_graph_sources(workplane)
    atomics = split_sources_at_intersections(sources)
    total = 0.0
    for seg in atomics:
        sx, sy = seg.start
        ex, ey = seg.end
        total += math.hypot(ex - sx, ey - sy)
    return total


def _atomic_count(widget) -> int:
    from cad_app.sketch_graph import split_sources_at_intersections

    workplane = widget._active_workplane
    sources = widget._sketch_graph_sources(workplane)
    return len(split_sources_at_intersections(sources))


def _try_trim(widget, uv, *, max_distance=5.0) -> bool:
    return widget._trim_segment_graph_at(uv, max_distance=max_distance)


def _case_a(log: _Log) -> None:
    log.case("A", "Two crossing lines, trim at the crossing")
    scene, widget, main_window = _fresh_widget()
    _set_tool(widget, "line")
    # Draw line 1: (-40, 0) -> (40, 0), length 80
    _click(widget, (-40.0, 0.0))
    _click(widget, (40.0, 0.0))
    widget._set_sketch_tool("line")  # commit open line, restart
    # Draw line 2: (0, -40) -> (0, 40), length 80
    _click(widget, (0.0, -40.0))
    _click(widget, (0.0, 40.0))
    widget._set_sketch_tool("trim")
    before_count = _atomic_count(widget)
    before_len = _total_atomic_length(widget)
    log.info(
        f"Before trim: {_count_sketch_items(scene)}, atomic_count={before_count}, "
        f"total_len={before_len:.1f}"
    )
    trimmed = _try_trim(widget, (5.0, 0.0), max_distance=8.0)
    after_count = _atomic_count(widget)
    after_len = _total_atomic_length(widget)
    log.info(f"After trim: atomic_count={after_count}, total_len={after_len:.1f}")
    log.require(trimmed, "Trim returned success at the crossing")
    # Trim removes ONE atomic. Two crossing 80-mm lines split into four
    # 40-mm atomics. After trimming one, total length should drop by 40.
    expected_drop = 40.0
    drop = before_len - after_len
    log.require(
        abs(drop - expected_drop) < 0.5,
        f"Total atomic length dropped by ~40 mm (actual {drop:.1f})",
    )
    log.require(
        after_count == before_count - 1,
        f"Atomic count dropped by exactly 1 ({before_count} -> {after_count})",
    )
    main_window.window.close()


def _case_b(log: _Log) -> None:
    log.case("B", "Line + circle, trim the line piece outside the circle")
    scene, widget, main_window = _fresh_widget()
    _set_tool(widget, "circle")
    _click(widget, (0.0, 0.0))
    _click(widget, (20.0, 0.0))  # circle radius 20 at origin
    _set_tool(widget, "line")
    _click(widget, (-50.0, 0.0))
    _click(widget, (50.0, 0.0))  # line 100 mm
    widget._set_sketch_tool("trim")
    before_count = _atomic_count(widget)
    before_len = _total_atomic_length(widget)
    # Pick a point on the line clearly outside the circle (X=40):
    # that stub is 30 mm long (from X=20 to X=50).
    trimmed = _try_trim(widget, (40.0, 0.0), max_distance=8.0)
    after_count = _atomic_count(widget)
    after_len = _total_atomic_length(widget)
    log.info(
        f"Before atomic_count={before_count}, total_len={before_len:.1f}; "
        f"after atomic_count={after_count}, total_len={after_len:.1f}"
    )
    log.require(trimmed, "Trim succeeded on the outer line stub")
    expected_drop = 30.0
    drop = before_len - after_len
    log.require(
        abs(drop - expected_drop) < 0.5,
        f"Outer stub of ~30 mm removed (actual {drop:.1f})",
    )
    main_window.window.close()


def _case_c(log: _Log) -> None:
    log.case("C", "Line + circle, trim the arc segment inside the line")
    scene, widget, main_window = _fresh_widget()
    _set_tool(widget, "circle")
    _click(widget, (0.0, 0.0))
    _click(widget, (20.0, 0.0))
    _set_tool(widget, "line")
    _click(widget, (-50.0, 0.0))
    _click(widget, (50.0, 0.0))
    widget._set_sketch_tool("trim")
    # Pick a point on the top half of the circle (X=0, Y=20).
    distance = _nearest_distance_to_geometry(widget, (0.0, 20.0))
    log.info(f"Top arc distance: {distance}")
    trimmed = _try_trim(widget, (0.0, 20.0), max_distance=8.0)
    log.require(trimmed, "Trim of the upper arc succeeded")
    main_window.window.close()


def _case_d(log: _Log) -> None:
    log.case("D", "Three overlapping circles, trim a middle arc")
    scene, widget, main_window = _fresh_widget()
    _set_tool(widget, "circle")
    _click(widget, (-25.0, 0.0))
    _click(widget, (15.0, 0.0))  # circle 1: center (-25,0), r=40
    _click(widget, (25.0, 0.0))
    _click(widget, (65.0, 0.0))  # circle 2: center (25,0), r=40
    _click(widget, (0.0, -30.0))
    _click(widget, (0.0, 10.0))  # circle 3: center (0,-30), r=40
    widget._set_sketch_tool("trim")
    before = _count_sketch_items(scene)
    log.info(f"Before trim: {before}")
    # Pick a point near the bottom of circle 1 — should be in the
    # overlap region.
    trimmed = _try_trim(widget, (-65.0, 5.0), max_distance=8.0)
    log.require(trimmed, "Trim of one arc among three circles succeeded")
    main_window.window.close()


def _case_e(log: _Log) -> None:
    log.case("E", "Click far from any geometry -> no-op")
    scene, widget, main_window = _fresh_widget()
    _set_tool(widget, "circle")
    _click(widget, (0.0, 0.0))
    _click(widget, (10.0, 0.0))
    widget._set_sketch_tool("trim")
    before = _count_sketch_items(scene)
    trimmed = _try_trim(widget, (200.0, 200.0), max_distance=5.0)
    after = _count_sketch_items(scene)
    log.require(not trimmed, "Trim correctly reports no-op far from geometry")
    log.require(before == after, f"Scene unchanged ({before} -> {after})")
    main_window.window.close()


def _case_f(log: _Log) -> None:
    log.case("F", "Click directly on the crossing vertex of two lines")
    scene, widget, main_window = _fresh_widget()
    _set_tool(widget, "line")
    _click(widget, (-40.0, 0.0))
    _click(widget, (40.0, 0.0))
    widget._set_sketch_tool("line")
    _click(widget, (0.0, -40.0))
    _click(widget, (0.0, 40.0))
    widget._set_sketch_tool("trim")
    distance = _nearest_distance_to_geometry(widget, (0.0, 0.0))
    log.info(f"Distance from cross vertex (0,0) to nearest segment: {distance}")
    trimmed = _try_trim(widget, (0.0, 0.0), max_distance=5.0)
    log.info(f"Trim on vertex result: {trimmed}")
    # Either succeed (picking one of the four adjoining arms) or
    # cleanly no-op — but never crash.
    log.require(True, "Trim on a vertex did not crash")
    main_window.window.close()


def _case_g(log: _Log) -> None:
    log.case("G", "Trim on a freshly drawn open line entity (not a profile)")
    scene, widget, main_window = _fresh_widget()
    _set_tool(widget, "line")
    _click(widget, (-30.0, -20.0))
    _click(widget, (30.0, 20.0))
    widget._set_sketch_tool("line")  # commit as line_segments entity
    line_entities = [
        it
        for it in scene
        if it.meta.get("kind") == SKETCH_ENTITY_META_KIND
        and it.meta.get("profile") == "line_segments"
    ]
    log.require(len(line_entities) == 1, "One open line entity in scene")
    _set_tool(widget, "circle")
    _click(widget, (0.0, 0.0))
    _click(widget, (15.0, 0.0))  # circle r=15 crossing the line
    widget._set_sketch_tool("trim")
    distance = _nearest_distance_to_geometry(widget, (20.0, 13.0))
    log.info(f"Distance from line tip to nearest segment: {distance}")
    trimmed = _try_trim(widget, (20.0, 13.0), max_distance=10.0)
    log.require(trimmed, "Trim works on an open line entity + circle mix")
    main_window.window.close()


def _case_i(log: _Log) -> None:
    log.case(
        "I",
        "Repeated trim: cut twice in a row should monotonically remove",
    )
    scene, widget, main_window = _fresh_widget()
    # Build the canonical "two crossing lines + circle" mess, then trim
    # three different points in sequence. Each trim should strictly
    # reduce the total atomic length.
    _set_tool(widget, "line")
    _click(widget, (-50.0, 0.0))
    _click(widget, (50.0, 0.0))
    widget._set_sketch_tool("line")
    _click(widget, (0.0, -50.0))
    _click(widget, (0.0, 50.0))
    widget._set_sketch_tool("circle")
    _click(widget, (0.0, 0.0))
    _click(widget, (25.0, 0.0))  # circle r=25
    widget._set_sketch_tool("trim")
    measurements = []
    points = [(40.0, 0.0), (0.0, 40.0), (-25.0, 0.0)]
    for i, pt in enumerate(points):
        before_len = _total_atomic_length(widget)
        before_count = _atomic_count(widget)
        trimmed = _try_trim(widget, pt, max_distance=8.0)
        after_len = _total_atomic_length(widget)
        after_count = _atomic_count(widget)
        log.info(
            f"Iter {i + 1} click {pt}: trimmed={trimmed}, "
            f"count {before_count} -> {after_count}, "
            f"len {before_len:.1f} -> {after_len:.1f}"
        )
        measurements.append(
            (
                trimmed,
                before_count,
                after_count,
                before_len,
                after_len,
            )
        )
    log.require(
        all(m[0] for m in measurements),
        "All 3 sequential trims returned success",
    )
    # The total length must monotonically decrease, never grow.
    lens = [m[3] for m in measurements] + [measurements[-1][4]]
    monotonic = all(lens[i] >= lens[i + 1] - 1e-6 for i in range(len(lens) - 1))
    log.require(
        monotonic,
        f"Total atomic length monotonically non-increasing: {lens}",
    )
    log.require(
        measurements[-1][4] < measurements[0][3] - 1.0,
        "Final length strictly smaller than initial (something was cut)",
    )
    main_window.window.close()


def _case_l(log: _Log) -> None:
    log.case(
        "L",
        "Trim a cross of two lines: crossing entity also splits at intersection",
    )
    scene, widget, main_window = _fresh_widget()
    widget._sketch_session = None
    widget._start_sketch_session(Workplane.world_xy(), "Bottom plane", None)
    widget._set_sketch_tool("line")
    _click(widget, (-40.0, 0.0))
    _click(widget, (40.0, 0.0))
    widget._set_sketch_tool("line")  # commit line 1 as open polyline
    _click(widget, (0.0, -40.0))
    _click(widget, (0.0, 40.0))
    widget._set_sketch_tool("trim")  # commit line 2 + enter trim mode
    # Two line_segments entities, 4 atomics total, cross at (0,0).
    sketch_items_before = [
        it
        for it in scene
        if it.meta.get("kind") in {SKETCH_META_KIND, SKETCH_ENTITY_META_KIND}
    ]
    log.info(f"Before trim: {len(sketch_items_before)} sketch items")
    log.require(len(sketch_items_before) == 2, "Two line entities present")

    # Click on the right arm of line 1
    trimmed = _try_trim(widget, (20.0, 0.0), max_distance=8.0)
    log.require(trimmed, "Trim succeeded")
    sketch_items_after = [
        it
        for it in scene
        if it.meta.get("kind") in {SKETCH_META_KIND, SKETCH_ENTITY_META_KIND}
    ]
    log.info(
        f"After trim: {len(sketch_items_after)} sketch items: "
        f"{[(it.item_id[:8], it.meta.get('profile')) for it in sketch_items_after]}"
    )
    log.require(
        len(sketch_items_after) >= 3,
        f"Cross split into at least 3 separate entities "
        f"(remaining arm of line 1 + 2 halves of line 2); "
        f"got {len(sketch_items_after)}",
    )
    main_window.window.close()


def _case_k(log: _Log) -> None:
    log.case(
        "K",
        "Self-intersecting polyline does not crash, kept as construction",
    )
    scene, widget, main_window = _fresh_widget()
    widget._sketch_session = None
    widget._start_sketch_session(Workplane.world_xy(), "Bottom plane", None)
    widget._set_sketch_tool("line")
    # Draw a "figure 8": four corners ordered so opposite ones connect,
    # producing a self-crossing wire when closed.
    _click(widget, (-30.0, -20.0))
    _click(widget, (30.0, 20.0))
    _click(widget, (30.0, -20.0))
    _click(widget, (-30.0, 20.0))
    _click(widget, (-30.0, -20.0))  # close → self-intersecting
    profiles = sum(1 for it in scene if it.meta.get("kind") == SKETCH_META_KIND)
    entities = sum(1 for it in scene if it.meta.get("kind") == SKETCH_ENTITY_META_KIND)
    log.info(f"After figure-8 close: profiles={profiles}, entities={entities}")
    log.require(
        profiles == 0,
        f"No profile produced for self-intersecting polyline ({profiles})",
    )
    log.require(
        entities >= 1,
        f"Lines kept as a sketch_entity reference ({entities})",
    )
    main_window.window.close()


def _case_j(log: _Log) -> None:
    log.case(
        "J",
        "User scenario: center_rectangle + crossing closed polyline, trim",
    )
    scene, widget, main_window = _fresh_widget()
    # Use a proper started session so sketch_id is a real uuid, exactly
    # like the production startup path.
    widget._sketch_session = None
    widget._start_sketch_session(Workplane.world_xy(), "Bottom plane", None)
    _set_tool(widget, "center_rectangle")
    _click(widget, (0.0, 0.0))
    _click(widget, (40.0, 25.0))  # rect 80x50
    rect_count = sum(1 for it in scene if it.meta.get("kind") == SKETCH_META_KIND)
    log.info(f"After rectangle: profile count = {rect_count}")
    log.require(rect_count == 1, "Rectangle profile exists")

    # Now mama switches to line and draws a closed quad crossing the rect.
    widget._set_sketch_tool("line")
    _click(widget, (-50.0, -30.0))
    _click(widget, (50.0, -30.0))
    _click(widget, (50.0, 30.0))
    _click(widget, (-50.0, 30.0))
    _click(widget, (-50.0, -30.0))  # closes
    profile_count_after = sum(
        1 for it in scene if it.meta.get("kind") == SKETCH_META_KIND
    )
    log.info(f"After closing polyline: profile count = {profile_count_after}")
    log.require(profile_count_after >= 2, "Both rectangle and closed polyline present")

    # Capture both items' sketch_id and meta state.
    sketches = [it for it in scene if it.meta.get("kind") == SKETCH_META_KIND]
    sketch_ids = [it.meta.get("sketch_id") for it in sketches]
    log.info(f"Per-item sketch_id: {sketch_ids}")
    log.info(
        f"Per-item has segment_graph: "
        f"{[bool(it.meta.get('segment_graph')) for it in sketches]}"
    )
    log.require(
        len(set(sketch_ids)) == 1,
        f"All sketches share the same sketch_id ({sketch_ids})",
    )

    # Now switch to trim and check sources count - the bug user reports.
    widget._set_sketch_tool("trim")
    sources = widget._sketch_graph_sources(widget._active_workplane)
    log.info(f"Trim source count: {len(sources)}")
    log.require(
        len(sources) == len(sketches),
        f"Trim sees all {len(sketches)} sketch items as sources "
        f"(saw {len(sources)})",
    )

    # Click where the polyline crosses the rectangle: (45, 0)
    # is on the polyline's right edge AND on the rectangle's right edge.
    before_count = _atomic_count(widget)
    before_len = _total_atomic_length(widget)
    log.info(f"Before trim: atomic_count={before_count}, total_len={before_len:.1f}")
    before_ids = {
        it.item_id: (
            it.meta.get("kind"),
            it.meta.get("profile"),
            it.meta.get("sketch_id"),
        )
        for it in scene
    }
    log.info(f"Before items: {before_ids}")
    trimmed = _try_trim(widget, (45.0, 0.0), max_distance=8.0)
    after_count = _atomic_count(widget)
    after_len = _total_atomic_length(widget)
    after_ids = {
        it.item_id: (
            it.meta.get("kind"),
            it.meta.get("profile"),
            it.meta.get("sketch_id"),
        )
        for it in scene
    }
    log.info(f"After trim: atomic_count={after_count}, total_len={after_len:.1f}")
    log.info(f"After items: {after_ids}")
    # Show what changed
    removed_ids = set(before_ids) - set(after_ids)
    added_ids = set(after_ids) - set(before_ids)
    log.info(f"Removed: {len(removed_ids)} items; added: {len(added_ids)} items")
    log.require(trimmed, "Trim succeeded on the rect+polyline overlap")
    log.require(
        after_count == before_count - 1,
        f"Trim removed exactly one atomic ({before_count} -> {after_count})",
    )
    main_window.window.close()


def _case_h(log: _Log) -> None:
    log.case("H", "Two collinear line segments meeting end-to-end")
    scene, widget, main_window = _fresh_widget()
    _set_tool(widget, "line")
    _click(widget, (-40.0, 0.0))
    _click(widget, (0.0, 0.0))
    widget._set_sketch_tool("line")  # commit first segment
    _click(widget, (0.0, 0.0))
    _click(widget, (40.0, 0.0))
    widget._set_sketch_tool("trim")
    before = _count_sketch_items(scene)
    distance = _nearest_distance_to_geometry(widget, (20.0, 0.0))
    log.info(f"Distance to right-hand segment: {distance}")
    trimmed = _try_trim(widget, (20.0, 0.0), max_distance=5.0)
    after = _count_sketch_items(scene)
    log.info(f"Before {before}, after {after}, trimmed={trimmed}")
    log.require(
        trimmed,
        "Trim works on collinear end-to-end segments",
    )
    main_window.window.close()


def main() -> int:
    app = QApplication.instance() or QApplication([])
    _ = app
    log = _Log()
    sys.stdout.write("=== TRIM STRESS WORKFLOW ===\n")
    for case in (
        _case_a,
        _case_b,
        _case_c,
        _case_d,
        _case_e,
        _case_f,
        _case_g,
        _case_h,
        _case_i,
        _case_j,
        _case_k,
        _case_l,
    ):
        try:
            case(log)
        except Exception as exc:  # noqa: BLE001
            log.fail(f"Crashed: {type(exc).__name__}: {exc}")
            import traceback

            traceback.print_exc()
    if log.failed:
        sys.stdout.write("\n=== RESULT: FAIL ===\n")
        return 1
    sys.stdout.write("\n=== RESULT: PASS ===\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
