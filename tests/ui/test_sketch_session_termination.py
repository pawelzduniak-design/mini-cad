"""Session-end audit: every path that closes a sketch must respect the
"preserve pending geometry" policy.

User report (mama scenario): drew an arc on a face, then a line from
one arc endpoint to a middle point, then a line back to the other arc
endpoint — wanted a pie-slice/wedge profile. The arc stayed but the
lines vanished. Root cause: ``_finish_sketch_session`` silently
discarded ``session.points`` when the closing clicks missed the snap
tolerance and the user finished the sketch via a rail click.

These contracts pin the policy:

1. Tool switch keeps an open line chain as a construction entity.
2. Finish-via-rail/category change keeps an open line chain.
3. Finish-via-Enter (``_finish_sketch_sequence``) keeps it.
4. Cancel (Esc) is the ONLY path that intentionally discards.
"""

from __future__ import annotations

from tests.conftest import require_ocp


def _start_widget_with_arc(qapp):
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    main_window = create_main_window(Viewer(), Scene())
    widget = main_window.viewer_widget
    widget._sketch_session = None
    widget._start_sketch_session(Workplane.world_xy(), "Bottom plane", None)
    widget._set_sketch_tool("arc")
    widget._handle_sketch_click(widget._sketch_session, (0.0, 0.0), 0, 0)
    widget._handle_sketch_click(widget._sketch_session, (20.0, 0.0), 0, 0)
    widget._handle_sketch_click(widget._sketch_session, (10.0, 10.0), 0, 0)
    return main_window, widget


def _entities_by_profile(scene) -> dict[str, int]:
    from cad_app.sketch import SKETCH_ENTITY_META_KIND, SKETCH_META_KIND

    counts: dict[str, int] = {}
    for item in scene:
        kind = item.meta.get("kind")
        profile = item.meta.get("profile")
        if kind in (SKETCH_META_KIND, SKETCH_ENTITY_META_KIND) and profile:
            counts[profile] = counts.get(profile, 0) + 1
    return counts


def test_finish_via_category_change_keeps_pending_lines(qapp) -> None:
    require_ocp()

    main_window, widget = _start_widget_with_arc(qapp)
    widget._set_sketch_tool("line")
    # Clicks deliberately off the arc endpoints (> snap tolerance) so
    # the chain stays open: this is the "lines vanish" path the user
    # reported.
    widget._handle_sketch_click(widget._sketch_session, (-2.0, -2.0), 0, 0)
    widget._handle_sketch_click(widget._sketch_session, (10.0, -5.0), 0, 0)
    widget._handle_sketch_click(widget._sketch_session, (22.0, 2.0), 0, 0)
    assert widget._sketch_session is not None
    assert widget._sketch_session.points

    widget._set_active_category("select")
    assert widget._sketch_session is None

    counts = _entities_by_profile(widget._scene)
    assert counts.get("arc") == 1
    assert counts.get("line_segments") == 1
    main_window.window.close()


def test_finish_via_enter_keeps_pending_lines(qapp) -> None:
    require_ocp()

    main_window, widget = _start_widget_with_arc(qapp)
    widget._set_sketch_tool("line")
    widget._handle_sketch_click(widget._sketch_session, (-2.0, -2.0), 0, 0)
    widget._handle_sketch_click(widget._sketch_session, (10.0, -5.0), 0, 0)

    widget._finish_sketch_sequence()
    counts = _entities_by_profile(widget._scene)
    assert counts.get("arc") == 1
    assert counts.get("line_segments") == 1
    main_window.window.close()


def test_cancel_discards_pending_lines(qapp) -> None:
    require_ocp()

    main_window, widget = _start_widget_with_arc(qapp)
    widget._set_sketch_tool("line")
    widget._handle_sketch_click(widget._sketch_session, (-2.0, -2.0), 0, 0)
    widget._handle_sketch_click(widget._sketch_session, (10.0, -5.0), 0, 0)

    widget._cancel_sketch_session()
    counts = _entities_by_profile(widget._scene)
    assert counts.get("arc") == 1
    assert "line_segments" not in counts
    main_window.window.close()


def test_arc_plus_line_clicks_on_endpoints_close_to_wedge(qapp) -> None:
    """Snap-hit path: lines that exactly touch arc endpoints close into a
    filled arc_polyline profile (the user's intended pie-slice)."""
    require_ocp()

    main_window, widget = _start_widget_with_arc(qapp)
    widget._set_sketch_tool("line")
    widget._handle_sketch_click(widget._sketch_session, (0.0, 0.0), 0, 0)
    widget._handle_sketch_click(widget._sketch_session, (10.0, -5.0), 0, 0)
    widget._handle_sketch_click(widget._sketch_session, (20.0, 0.0), 0, 0)

    counts = _entities_by_profile(widget._scene)
    assert counts.get("arc") == 1
    assert counts.get("arc_polyline") == 1
    main_window.window.close()


def test_drain_helper_audit_records_what_happened(qapp) -> None:
    require_ocp()

    main_window, widget = _start_widget_with_arc(qapp)
    widget._set_sketch_tool("line")
    widget._handle_sketch_click(widget._sketch_session, (-2.0, -2.0), 0, 0)
    widget._handle_sketch_click(widget._sketch_session, (10.0, -5.0), 0, 0)

    audit = widget._drain_pending_sketch_geometry(
        widget._sketch_session,
        preserve=True,
        reason="probe",
    )
    assert audit.reason == "probe"
    assert audit.tool == "line"
    assert audit.pending_point_count == 2
    assert audit.committed_item_id is not None
    assert audit.discarded is False

    audit_cancel = widget._drain_pending_sketch_geometry(
        widget._sketch_session,
        preserve=False,
        reason="probe_cancel",
    )
    # The helper does NOT mutate session.points — that's the caller's
    # responsibility. With preserve=False the audit records that the
    # pending geometry was dropped on the floor.
    assert audit_cancel.tool == "line"
    assert audit_cancel.committed_item_id is None
    assert audit_cancel.discarded is True
    main_window.window.close()
