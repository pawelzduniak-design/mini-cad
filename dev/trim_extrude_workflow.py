"""Reproduce the user's "cannot extrude some regions after trim" symptom.

Scenario (mirrors the production log):
1. Draw a center rectangle (profile)
2. Switch to circle, draw a few overlapping circles → regionization
   produces multiple closed profile regions
3. Switch to line, draw a closed polyline overlapping the above
4. Trim a handful of arcs / lines
5. Inspect the scene: how many items are still `sketch_profile`
   (= pickable as a face for Extrude) vs `sketch_entity` (= open
   geometry, not pickable)?

A beginner who drew a complex sketch expects every visible closed
region to still be extrudable. The bug surfaces when, after a few
trims, only one or two regions remain pickable while the rest have
been turned into `sketch_entity` items by the trim apply logic.
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


def _click(widget, uv):
    widget._handle_sketch_click(widget._sketch_session, uv, 0, 0)


def _count(scene):
    profiles = sum(1 for it in scene if it.meta.get("kind") == SKETCH_META_KIND)
    entities = sum(1 for it in scene if it.meta.get("kind") == SKETCH_ENTITY_META_KIND)
    return profiles, entities


def _run(log: _Log) -> None:
    app = QApplication.instance() or QApplication([])
    _ = app
    scene = Scene()
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget
    widget._sketch_session = None
    widget._start_sketch_session(Workplane.world_xy(), "Bottom plane", None)

    # Draw 3 overlapping circles. Regionization makes profile regions.
    widget._set_sketch_tool("circle")
    _click(widget, (-20.0, 0.0))
    _click(widget, (10.0, 0.0))  # circle 1 r=30
    _click(widget, (20.0, 0.0))
    _click(widget, (50.0, 0.0))  # circle 2 r=30
    _click(widget, (0.0, -20.0))
    _click(widget, (30.0, -20.0))  # circle 3 r=30
    profiles, entities = _count(scene)
    log.info(f"After 3 circles: profiles={profiles}, entities={entities}")
    log.require(profiles >= 2, "Regionization produced multiple profile regions")

    # Trim a couple of inner arcs.
    widget._set_sketch_tool("trim")
    trim_points = [
        (-50.0, 0.0),  # outer left of circle 1
        (50.0, 0.0),  # outer right of circle 2
        (15.0, -30.0),  # bottom of circle 3
    ]
    for pt in trim_points:
        before_p, before_e = _count(scene)
        trimmed = widget._trim_segment_graph_at(pt, max_distance=8.0)
        after_p, after_e = _count(scene)
        log.info(
            f"Trim @ {pt}: trimmed={trimmed}, "
            f"profiles {before_p}->{after_p}, entities {before_e}->{after_e}"
        )

    profiles, entities = _count(scene)
    total = profiles + entities
    log.info(f"After trims: total={total}, profiles={profiles}, entities={entities}")

    # The crucial sanity check: at least *some* profiles must remain.
    # Without any pickable profile, the user cannot extrude anything.
    log.require(
        profiles >= 1,
        f"At least one closed profile remains after trim "
        f"(needed for Extrude to work) — got {profiles}",
    )
    # And the ratio profile : total shouldn't be < 20% — that's the
    # symptom from the user log (only 1 of 11 items pickable).
    if total > 0:
        log.require(
            profiles / total >= 0.2,
            f"Profile fraction is reasonable for Extrude pickability: "
            f"{profiles}/{total} = {profiles / total:.0%}",
        )

    # Finish the sketch and check which items remain pickable as a face.
    widget._finish_sketch_sequence()
    if widget._sketch_session is not None:
        widget._finish_sketch_sequence()

    final_profile_items = [
        (it.item_id[:8], it.meta.get("profile"))
        for it in scene
        if it.meta.get("kind") == SKETCH_META_KIND
    ]
    log.info(f"Final sketch_profile items: {final_profile_items}")
    log.require(
        len(final_profile_items) >= 1,
        f"At least one extrudable profile in finished sketch "
        f"({len(final_profile_items)})",
    )

    main_window.window.close()


def main() -> int:
    log = _Log()
    sys.stdout.write("=== TRIM POST-REGION EXTRUDABILITY ===\n")
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
