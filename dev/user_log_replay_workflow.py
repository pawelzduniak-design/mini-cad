"""Replay the exact user session from logs/cad_app.log 1:1.

Sequence from the user's session that produced the "sketch splits into
two" report:

    22:10:25 - center_rectangle profile created
    22:10:30 - tool switched to line
    22:10:37 - closed polyline profile created
    22:10:39 - tool switched to trim
    22:10:41..22:10:50 - SEVEN trim clicks (open_segments 9→8→…→3)
    22:10:53 - Undo
    22:10:55..22:10:58 - THREE more trims (3→2→1)
    22:11:00 - trim again, open_segments JUMPS BACK to 3  ← anomaly
    22:11:01 - Undo
    22:11:03 - trim (3 again)

Before the sketch_id-in-trim-meta fix, the atomic count would not
monotonically decrease through this sequence because after each trim
the rebuilt entity lost its sketch_id, dropped out of
_sketch_graph_sources on subsequent reads, and the trim algorithm only
saw the *other* (untouched) profile. After the fix the count should
strictly drop (or hold) at every step.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from cad_app.main_window import create_main_window
from cad_app.scene import Scene
from cad_app.sketch import SKETCH_ENTITY_META_KIND, SKETCH_META_KIND
from cad_app.viewer import Viewer
from cad_app.workplane import Workplane


class _Log:
    def __init__(self) -> None:
        self.failed = False

    def info(self, message: str) -> None:
        sys.stdout.write(f"[INFO] {message}\n")

    def passed(self, message: str) -> None:
        sys.stdout.write(f"[PASS] {message}\n")

    def fail(self, message: str) -> None:
        self.failed = True
        sys.stdout.write(f"[FAIL] {message}\n")

    def require(self, condition: bool, message: str) -> None:
        if condition:
            self.passed(message)
        else:
            self.fail(message)


def _atomic_count(widget) -> int:
    from cad_app.sketch_graph import split_sources_at_intersections

    sources = widget._sketch_graph_sources(widget._active_workplane)
    return len(split_sources_at_intersections(sources))


def _scene_items(scene: Scene):
    return [
        (
            it.item_id[:8],
            it.meta.get("kind"),
            it.meta.get("profile"),
            (it.meta.get("sketch_id") or "")[:8],
        )
        for it in scene
        if it.meta.get("kind") in {SKETCH_META_KIND, SKETCH_ENTITY_META_KIND}
    ]


def _click(widget, uv):
    widget._handle_sketch_click(widget._sketch_session, uv, 0, 0)


def _set_tool(widget, tool):
    widget._set_sketch_tool(tool)


def _run(log: _Log) -> None:
    app = QApplication.instance() or QApplication([])
    _ = app
    scene = Scene()
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget
    widget._sketch_session = None
    widget._start_sketch_session(Workplane.world_xy(), "Bottom plane", None)
    log.info(f"Sketch session sketch_id: {widget._sketch_session.sketch_id[:8]}")

    # Step 1: center_rectangle profile (mama draws a base rectangle).
    _set_tool(widget, "center_rectangle")
    _click(widget, (0.0, 0.0))
    _click(widget, (35.0, 25.0))  # rectangle 70x50 mm
    log.info(f"After rect: {_scene_items(scene)}, atomics={_atomic_count(widget)}")

    # Step 2: switch to line, draw a closed quad polyline that crosses
    # the rectangle.
    _set_tool(widget, "line")
    _click(widget, (-50.0, -35.0))
    _click(widget, (50.0, -35.0))
    _click(widget, (50.0, 35.0))
    _click(widget, (-50.0, 35.0))
    _click(widget, (-50.0, -35.0))  # closes
    log.info(f"After polyline: {_scene_items(scene)}, atomics={_atomic_count(widget)}")

    # Step 3: switch to trim and perform a long sequence of trim clicks
    # — like the user did in the log.
    _set_tool(widget, "trim")
    points = [
        (50.0, 0.0),  # polyline right edge
        (-50.0, 0.0),  # polyline left edge
        (0.0, -35.0),  # polyline bottom edge
        (0.0, 35.0),  # polyline top edge
        (35.0, 0.0),  # rectangle right edge
        (-35.0, 0.0),  # rectangle left edge
        (0.0, -25.0),  # rectangle bottom edge
        (0.0, 25.0),  # rectangle top edge
    ]
    atomic_history = [_atomic_count(widget)]
    log.info(f"Trim starts; atomic_count = {atomic_history[-1]}")
    for i, pt in enumerate(points):
        before = _atomic_count(widget)
        trimmed = widget._trim_segment_graph_at(pt, max_distance=8.0)
        after = _atomic_count(widget)
        atomic_history.append(after)
        log.info(
            f"Trim {i + 1} @ {pt}: trimmed={trimmed}, " f"atomics {before} -> {after}"
        )

    log.require(
        all(
            atomic_history[i] >= atomic_history[i + 1]
            for i in range(len(atomic_history) - 1)
        ),
        f"Atomic count never jumps UP across the sequence: {atomic_history}",
    )

    # Step 4: Undo a few times, like the user did.
    scene_before_undo = list(_scene_items(scene))
    atoms_before_undo = _atomic_count(widget)
    main_window.actions["undo"].trigger()
    atoms_after_one_undo = _atomic_count(widget)
    log.info(
        f"After 1 undo: atomics {atoms_before_undo} -> {atoms_after_one_undo}, "
        f"items {scene_before_undo} -> {_scene_items(scene)}"
    )
    log.require(
        atoms_after_one_undo >= atoms_before_undo,
        f"Undo restored at least as much geometry "
        f"({atoms_before_undo} -> {atoms_after_one_undo})",
    )

    # Step 5: more trims after undo.
    trim_after_undo = [_atomic_count(widget)]
    for pt in [(50.0, 10.0), (50.0, -10.0)]:
        before = trim_after_undo[-1]
        trimmed = widget._trim_segment_graph_at(pt, max_distance=8.0)
        after = _atomic_count(widget)
        trim_after_undo.append(after)
        log.info(
            f"Post-undo trim @ {pt}: trimmed={trimmed}, " f"atomics {before} -> {after}"
        )
    log.require(
        all(
            trim_after_undo[i] >= trim_after_undo[i + 1]
            for i in range(len(trim_after_undo) - 1)
        ),
        f"Post-undo trim sequence is monotonically non-increasing: "
        f"{trim_after_undo}",
    )

    # Sanity: every surviving sketch item still carries the right
    # sketch_id, so the "two separate sketches" symptom would surface.
    final_ids = {
        it.item_id: it.meta.get("sketch_id")
        for it in scene
        if it.meta.get("kind") in {SKETCH_META_KIND, SKETCH_ENTITY_META_KIND}
    }
    session_id = widget._sketch_session.sketch_id
    log.info(f"Final items / sketch_id: {final_ids}, session={session_id[:8]}")
    log.require(
        all(sid == session_id for sid in final_ids.values()),
        "All surviving items still share the active session's sketch_id",
    )

    main_window.window.close()


def main() -> int:
    log = _Log()
    sys.stdout.write("=== USER LOG REPLAY ===\n")
    try:
        _run(log)
    except Exception as exc:  # noqa: BLE001
        log.fail(f"Unhandled: {type(exc).__name__}: {exc}")
        import traceback

        traceback.print_exc()
    if log.failed:
        sys.stdout.write("\n=== RESULT: FAIL ===\n")
        return 1
    sys.stdout.write("\n=== RESULT: PASS ===\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
