from __future__ import annotations

from tests.conftest import require_ocp


def _add_rectangle_and_circle(scene, workplane) -> tuple[str, str]:
    from cad_app.sketch import (
        SKETCH_META_KIND,
        make_circle_profile_at,
        make_rectangle_profile_from_corners,
    )

    rect_id = scene.add_shape(
        make_rectangle_profile_from_corners(
            workplane,
            (-100.0, -50.0),
            (50.0, 50.0),
        ),
        meta={
            "kind": SKETCH_META_KIND,
            "profile": "rectangle",
            "width": 150.0,
            "height": 100.0,
            "center_u": -25.0,
            "center_v": 0.0,
            "workplane": "XY",
        },
    )
    circle_id = scene.add_shape(
        make_circle_profile_at(workplane, (20.0, -20.0), radius=65.0),
        meta={
            "kind": SKETCH_META_KIND,
            "profile": "circle",
            "radius": 65.0,
            "center_u": 20.0,
            "center_v": -20.0,
            "workplane": "XY",
        },
    )
    return rect_id, circle_id


def _draw_regionized_rectangle_and_circle(widget, workplane):
    from cad_app.ui_sessions import SketchSession

    session = SketchSession(workplane, "XY", None, tool="center_rectangle")
    widget._sketch_session = session
    widget._active_workplane = workplane
    widget._active_workplane_label = "XY"
    widget._handle_two_point_profile_click(session, (0.0, 0.0), 30, 30)
    widget._handle_two_point_profile_click(session, (50.0, 50.0), 80, 80)
    widget._set_sketch_tool("circle")
    widget._handle_two_point_profile_click(session, (20.0, -20.0), 80, 50)
    widget._handle_two_point_profile_click(session, (85.0, -20.0), 145, 50)
    return session


def _add_open_line(scene) -> str:
    from cad_app.sketch import SKETCH_ENTITY_META_KIND
    from cad_app.sketch_graph import segments_meta

    return scene.add_shape(
        "line-shape",
        meta={
            "kind": SKETCH_ENTITY_META_KIND,
            "profile": "line_segment",
            "workplane": "XY",
            **segments_meta((((-10.0, 0.0), (10.0, 0.0)),)),
        },
    )


def _patch_initialized_viewer(widget) -> None:
    widget._viewer.is_initialized = True
    for name in (
        "clear_selection_marker",
        "clear_hover_marker",
        "clear_preview_marker",
        "clear_dimension_label",
        "display_scene",
        "display_shape",
        "erase_shape",
        "update_view",
        "set_selection_kind",
        "display_selection_marker",
    ):
        setattr(widget._viewer, name, lambda *args, **kwargs: None)


def _screen_uv_with_small_offset(x: int, y: int, snap: bool = False):
    del snap
    return ((x - 50) * 0.2, (y - 50) * 0.2)


def _nearest_segment_distance(scene, uv: tuple[float, float]) -> float | None:
    from cad_app.sketch_graph import (
        SketchGraphSource,
        _point_atomic_distance,
        curves_from_meta,
        segments_from_meta,
        split_sources_at_intersections,
    )

    sources = tuple(
        SketchGraphSource(
            item.item_id,
            segments_from_meta(item.meta),
            dict(item.meta),
            curves_from_meta(item.meta),
        )
        for item in scene
    )
    atomic = split_sources_at_intersections(sources)
    if not atomic:
        return None
    return min(_point_atomic_distance(uv, segment) for segment in atomic)


def test_trim_click_on_circle_crossing_rectangle_keeps_remaining_arc(qapp) -> None:
    require_ocp()

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.sketch import SKETCH_ENTITY_META_KIND, SKETCH_META_KIND
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    scene = Scene()
    workplane = Workplane.world_xy()
    rect_id, circle_id = _add_rectangle_and_circle(scene, workplane)
    main_window = create_main_window(Viewer(), scene)

    assert main_window.viewer_widget._trim_segment_graph_at((80.0, -20.0))

    assert rect_id in scene
    assert circle_id in scene
    profile_items = [
        item for item in scene if item.meta.get("kind") == SKETCH_META_KIND
    ]
    entity_items = [
        item for item in scene if item.meta.get("kind") == SKETCH_ENTITY_META_KIND
    ]
    assert [item.item_id for item in profile_items] == [rect_id]
    assert [item.item_id for item in entity_items] == [circle_id]
    assert entity_items[0].meta["profile"] == "arc_segment"
    assert entity_items[0].meta["curves_uv"][0]["kind"] == "arc"


def test_trim_regionized_circle_does_not_remove_all_circle_regions(qapp) -> None:
    require_ocp()

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.sketch import SKETCH_ENTITY_META_KIND, SKETCH_META_KIND
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    scene = Scene()
    workplane = Workplane.world_xy()
    main_window = create_main_window(Viewer(), scene)
    _draw_regionized_rectangle_and_circle(main_window.viewer_widget, workplane)

    assert {
        item.meta.get("region_role")
        for item in scene
        if item.meta.get("kind") == SKETCH_META_KIND
    } == {"base", "intersection", "tool"}

    assert main_window.viewer_widget._trim_segment_graph_at(
        (80.0, -20.0),
        max_distance=10.0,
    )

    profiles = [item for item in scene if item.meta.get("kind") == SKETCH_META_KIND]
    entities = [
        item for item in scene if item.meta.get("kind") == SKETCH_ENTITY_META_KIND
    ]
    assert any(item.meta.get("region_role") == "intersection" for item in profiles)
    assert any(item.meta.get("radius") == 65.0 for item in profiles)
    assert len(entities) >= 1


def test_trim_shared_region_edge_removes_visible_duplicate_on_first_click(qapp) -> None:
    require_ocp()

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    scene = Scene()
    workplane = Workplane.world_xy()
    main_window = create_main_window(Viewer(), scene)
    _draw_regionized_rectangle_and_circle(main_window.viewer_widget, workplane)

    assert _nearest_segment_distance(scene, (50.0, 0.0)) == 0.0

    assert main_window.viewer_widget._trim_segment_graph_at(
        (50.0, 0.0),
        max_distance=10.0,
    )

    distance = _nearest_segment_distance(scene, (50.0, 0.0))
    assert distance is None or distance > 10.0


def test_trim_updates_viewer_incrementally_without_full_scene_redisplay(qapp) -> None:
    require_ocp()

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.ui_sessions import SketchSession
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    scene = Scene()
    line_id = _add_open_line(scene)
    workplane = Workplane.world_xy()
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget
    widget._sketch_session = SketchSession(workplane, "XY", None, tool="trim")
    widget._viewer.is_initialized = True
    calls: list[tuple[str, str | None]] = []

    for name in (
        "clear_selection_marker",
        "clear_hover_marker",
        "clear_preview_marker",
        "clear_dimension_label",
        "display_selection_marker",
    ):
        setattr(widget._viewer, name, lambda *args, **kwargs: None)
    widget._viewer.display_scene = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("Trim must not redisplay the whole scene")
    )
    widget._viewer.erase_shape = lambda item_id, **kwargs: calls.append(
        ("erase", item_id)
    )
    widget._viewer.display_shape = lambda item_id, *args, **kwargs: calls.append(
        ("display", item_id)
    )
    widget._viewer.set_selection_kind = lambda *args, **kwargs: calls.append(
        ("selection_kind", None)
    )
    widget._viewer.update_view = lambda *args, **kwargs: calls.append(("update", None))

    assert widget._trim_segment_graph_at((0.0, 0.0), max_distance=10.0)

    assert ("erase", line_id) in calls
    assert ("update", None) in calls


def test_trim_single_click_uses_press_location_when_release_drifts(qapp) -> None:
    require_ocp()

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.ui_sessions import SketchSession
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    scene = Scene()
    line_id = _add_open_line(scene)
    workplane = Workplane.world_xy()
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget
    widget._sketch_session = SketchSession(workplane, "XY", None, tool="trim")
    widget._screen_to_sketch_uv = _screen_uv_with_small_offset
    widget._sketch_session.drag_start_screen = (50, 50)
    _patch_initialized_viewer(widget)

    widget._commit_sketch_drag(50, 56)

    assert line_id not in scene
    assert widget._last_status_text == "Sketch segment trimmed"


def test_trim_single_click_accepts_small_screen_offset(qapp) -> None:
    require_ocp()

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.ui_sessions import SketchSession
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    scene = Scene()
    line_id = _add_open_line(scene)
    workplane = Workplane.world_xy()
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget
    widget._sketch_session = SketchSession(workplane, "XY", None, tool="trim")
    widget._screen_to_sketch_uv = _screen_uv_with_small_offset
    _patch_initialized_viewer(widget)

    assert widget._trim_sketch_at(50, 56)

    assert line_id not in scene


def test_selected_trim_does_not_delete_whole_circle_profile(qapp) -> None:
    require_ocp()

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.ui_sessions import SketchSession
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    scene = Scene()
    workplane = Workplane.world_xy()
    rect_id, circle_id = _add_rectangle_and_circle(scene, workplane)
    scene.set_selection(SelectionRef(circle_id, SelectionKind.FACE, 1))
    main_window = create_main_window(Viewer(), scene)
    session = SketchSession(workplane, "XY", None, tool="trim")
    session.profile_ids.extend([rect_id, circle_id])
    main_window.viewer_widget._sketch_session = session

    assert not main_window.viewer_widget._trim_selected_sketch()

    assert rect_id in scene
    assert circle_id in scene
    assert circle_id in session.profile_ids
    assert scene.selection() is None
    assert main_window.viewer_widget._sketch_session is session
    assert main_window.viewer_widget._sketch_session.tool == "trim"
    assert (
        main_window.viewer_widget._last_status_text == "Trim: click segment to remove"
    )
