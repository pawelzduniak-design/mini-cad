"""Real-window mouse interaction tests.

These tests guard the routing from QMouseEvent → mousePressEvent →
mouseReleaseEvent → _select_at → Picker → _apply_selection_result. The
Qt-free contract tests in tests/ui inject selections directly via
scene.set_selection, so a regression in event routing or picking would
slip through them. These tests close that gap by simulating real clicks
on a shown viewport.

Gated by CAD_APP_GUI_TESTS=1.
"""

from __future__ import annotations

import pytest

from tests.conftest import require_gui_enabled
from tests.gui.helpers import create_box_contract_window


def _world_to_widget_point(viewer, widget, world) -> object:
    from PySide6.QtCore import QPoint

    view_x, view_y = viewer.view.Convert(*world)
    scale = widget.devicePixelRatioF()
    return QPoint(round(float(view_x) / scale), round(float(view_y) / scale))


def _sketch_uv_to_widget_point(viewer, widget, workplane, uv) -> object:
    return _world_to_widget_point(
        viewer,
        widget,
        widget._workplane_point(workplane, uv),
    )


def _click_sketch_uv(qapp, viewer, widget, workplane, uv) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    point = _sketch_uv_to_widget_point(viewer, widget, workplane, uv)
    assert widget.rect().contains(point), f"Sketch UV {uv} mapped outside viewport"
    QTest.mouseClick(widget, Qt.LeftButton, Qt.NoModifier, point)
    _settle(qapp)


def _drag_sketch_uv(qapp, viewer, widget, workplane, start_uv, end_uv) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    start = _sketch_uv_to_widget_point(viewer, widget, workplane, start_uv)
    end = _sketch_uv_to_widget_point(viewer, widget, workplane, end_uv)
    assert widget.rect().contains(
        start
    ), f"Sketch UV {start_uv} mapped outside viewport"
    assert widget.rect().contains(end), f"Sketch UV {end_uv} mapped outside viewport"
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(widget, end)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
    _settle(qapp)


def _wait_for_initial_display(qapp, viewer, widget) -> None:
    from PySide6.QtTest import QTest

    for _ in range(80):
        qapp.processEvents()
        if viewer.is_initialized and widget._initial_scene_displayed:
            return
        QTest.qWait(50)
    raise AssertionError("Viewer did not initialize and display the initial scene")


def _settle(qapp, *, ms: int = 120) -> None:
    from PySide6.QtTest import QTest

    qapp.processEvents()
    QTest.qWait(ms)
    qapp.processEvents()


@pytest.mark.gui
def test_left_click_object_mode_selects_body(qapp) -> None:
    require_gui_enabled()

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from cad_app.types import SelectionKind

    fixture = create_box_contract_window()
    main_window = fixture.main_window
    window = main_window.window
    widget = main_window.viewer_widget
    viewer = main_window.viewer
    scene = main_window.scene

    window.resize(960, 640)
    window.show()
    widget.setFocus()

    try:
        _wait_for_initial_display(qapp, viewer, widget)

        scene.set_selection(None)
        widget._selection_kind = SelectionKind.OBJECT
        viewer.set_selection_kind(SelectionKind.OBJECT)
        widget._set_active_category("select")
        widget._fit_all()
        viewer.refresh_native_window()
        _settle(qapp)

        assert scene.selection() is None

        center = QPoint(widget.width() // 2, widget.height() // 2)
        QTest.mouseClick(widget, Qt.LeftButton, Qt.NoModifier, center)
        _settle(qapp)

        selection = scene.selection()
        assert (
            selection is not None
        ), "Left-click in viewport center produced no selection"
        assert selection.item_id == fixture.item_id
        assert selection.kind == SelectionKind.OBJECT
        assert widget.get_ui_state().selection_type == "object"
    finally:
        window.close()
        viewer.close()
        qapp.processEvents()


@pytest.mark.gui
def test_left_click_face_mode_selects_face(qapp) -> None:
    require_gui_enabled()

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from cad_app.types import SelectionKind

    fixture = create_box_contract_window()
    main_window = fixture.main_window
    window = main_window.window
    widget = main_window.viewer_widget
    viewer = main_window.viewer
    scene = main_window.scene

    window.resize(960, 640)
    window.show()
    widget.setFocus()

    try:
        _wait_for_initial_display(qapp, viewer, widget)

        scene.set_selection(None)
        widget._selection_kind = SelectionKind.FACE
        viewer.set_selection_kind(SelectionKind.FACE)
        widget._set_active_category("select")
        widget._fit_all()
        viewer.refresh_native_window()
        _settle(qapp)

        assert scene.selection() is None

        center = QPoint(widget.width() // 2, widget.height() // 2)
        QTest.mouseClick(widget, Qt.LeftButton, Qt.NoModifier, center)
        _settle(qapp)

        selection = scene.selection()
        assert selection is not None, "Left-click in face mode produced no selection"
        assert selection.item_id == fixture.item_id
        assert selection.kind == SelectionKind.FACE
        assert widget.get_ui_state().selection_type == "face"
    finally:
        window.close()
        viewer.close()
        qapp.processEvents()


@pytest.mark.gui
def test_right_click_does_not_mutate_selection_or_scene(qapp) -> None:
    require_gui_enabled()

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from cad_app.types import SelectionKind, SelectionRef
    from tests.helpers.topology import scene_fingerprint

    fixture = create_box_contract_window()
    main_window = fixture.main_window
    window = main_window.window
    widget = main_window.viewer_widget
    viewer = main_window.viewer
    scene = main_window.scene

    window.resize(960, 640)
    window.show()
    widget.setFocus()

    try:
        _wait_for_initial_display(qapp, viewer, widget)

        widget._selection_kind = SelectionKind.OBJECT
        viewer.set_selection_kind(SelectionKind.OBJECT)
        widget._set_active_category("select")
        scene.set_selection(SelectionRef(fixture.item_id, SelectionKind.OBJECT, 0))
        _settle(qapp)

        fingerprint_before = scene_fingerprint(scene)
        selection_before = scene.selection()

        center = QPoint(widget.width() // 2, widget.height() // 2)
        QTest.mousePress(widget, Qt.RightButton, Qt.NoModifier, center)
        QTest.mouseMove(widget, QPoint(center.x() + 50, center.y() + 30))
        QTest.mouseRelease(
            widget,
            Qt.RightButton,
            Qt.NoModifier,
            QPoint(center.x() + 50, center.y() + 30),
        )
        _settle(qapp)

        assert scene_fingerprint(scene) == fingerprint_before
        assert scene.selection() == selection_before
    finally:
        window.close()
        viewer.close()
        qapp.processEvents()


@pytest.mark.gui
def test_real_click_draws_circle_profile_on_sketch_plane(qapp) -> None:
    require_gui_enabled()

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.sketch import SKETCH_META_KIND
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    scene = Scene()
    viewer = Viewer()
    main_window = create_main_window(viewer, scene)
    window = main_window.window
    widget = main_window.viewer_widget
    workplane = Workplane.world_xy()

    window.resize(960, 640)
    window.show()
    widget.setFocus()

    try:
        _wait_for_initial_display(qapp, viewer, widget)

        widget._pending_sketch_tool = "circle"
        widget._start_sketch_session(workplane, "XY", None)
        _settle(qapp)

        _click_sketch_uv(qapp, viewer, widget, workplane, (0.0, 0.0))
        _click_sketch_uv(qapp, viewer, widget, workplane, (40.0, 0.0))

        profiles = [
            item
            for item in scene
            if item.meta.get("kind") == SKETCH_META_KIND
            and item.meta.get("profile") == "circle"
        ]
        assert len(profiles) == 1
        meta = profiles[0].meta
        assert float(meta["radius"]) > 25.0
        assert abs(float(meta["center_u"])) < 2.0
        assert meta.get("workplane") == "XY"
        assert meta.get("workplane_origin") == (0.0, 0.0, 0.0)
        assert widget._sketch_session is not None
        assert widget._sketch_session.tool == "circle"
    finally:
        window.close()
        viewer.close()
        qapp.processEvents()


@pytest.mark.gui
def test_real_click_draws_closed_line_profile_on_sketch_plane(qapp) -> None:
    require_gui_enabled()

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.sketch import SKETCH_META_KIND
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    scene = Scene()
    viewer = Viewer()
    main_window = create_main_window(viewer, scene)
    window = main_window.window
    widget = main_window.viewer_widget
    workplane = Workplane.world_xy()

    window.resize(960, 640)
    window.show()
    widget.setFocus()

    try:
        _wait_for_initial_display(qapp, viewer, widget)

        widget._pending_sketch_tool = "line"
        widget._start_sketch_session(workplane, "XY", None)
        _settle(qapp)

        for uv in (
            (0.0, 0.0),
            (40.0, 0.0),
            (40.0, 20.0),
            (0.0, 20.0),
            (0.0, 0.0),
        ):
            _click_sketch_uv(qapp, viewer, widget, workplane, uv)

        profiles = [
            item
            for item in scene
            if item.meta.get("kind") == SKETCH_META_KIND
            and item.meta.get("profile") == "line_polyline"
        ]
        assert len(profiles) == 1
        assert len(profiles[0].meta.get("segments_uv", ())) == 4
        assert widget._sketch_session is not None
        assert widget._sketch_session.tool == "line"
    finally:
        window.close()
        viewer.close()
        qapp.processEvents()


@pytest.mark.gui
def test_real_drag_line_points_build_the_same_closed_profile(qapp) -> None:
    require_gui_enabled()

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.sketch import SKETCH_META_KIND
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    scene = Scene()
    viewer = Viewer()
    main_window = create_main_window(viewer, scene)
    window = main_window.window
    widget = main_window.viewer_widget
    workplane = Workplane.world_xy()

    window.resize(960, 640)
    window.show()
    widget.setFocus()

    try:
        _wait_for_initial_display(qapp, viewer, widget)

        widget._pending_sketch_tool = "line"
        widget._start_sketch_session(workplane, "XY", None)
        _settle(qapp)

        _drag_sketch_uv(qapp, viewer, widget, workplane, (0.0, 0.0), (40.0, 0.0))
        assert widget._sketch_session is not None
        assert widget._sketch_session.tool == "line"
        assert len(widget._sketch_session.points) == 2
        assert widget._sketch_session.points[0] == pytest.approx(
            (0.0, 0.0),
            abs=0.75,
        )
        assert widget._sketch_session.points[1] == pytest.approx(
            (40.0, 0.0),
            abs=0.75,
        )
        assert not [
            item
            for item in scene
            if item.meta.get("kind") == SKETCH_META_KIND
            and item.meta.get("profile") == "line_polyline"
        ]

        _drag_sketch_uv(qapp, viewer, widget, workplane, (40.0, 0.0), (40.0, 20.0))
        assert len(widget._sketch_session.points) == 3
        assert widget._sketch_session.points[0] == pytest.approx(
            (0.0, 0.0),
            abs=0.75,
        )
        assert widget._sketch_session.points[1] == pytest.approx(
            (40.0, 0.0),
            abs=0.75,
        )
        assert widget._sketch_session.points[2] == pytest.approx(
            (40.0, 20.0),
            abs=0.75,
        )

        _drag_sketch_uv(qapp, viewer, widget, workplane, (40.0, 20.0), (0.0, 0.0))

        profiles = [
            item
            for item in scene
            if item.meta.get("kind") == SKETCH_META_KIND
            and item.meta.get("profile") == "line_polyline"
        ]
        assert len(profiles) == 1
        assert len(profiles[0].meta.get("segments_uv", ())) == 3
        assert widget._sketch_session is not None
        assert widget._sketch_session.tool == "line"
        assert widget._sketch_session.points == []
    finally:
        window.close()
        viewer.close()
        qapp.processEvents()


@pytest.mark.gui
def test_real_click_line_closes_after_camera_rotation(qapp) -> None:
    require_gui_enabled()

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.sketch import SKETCH_META_KIND
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    scene = Scene()
    viewer = Viewer()
    main_window = create_main_window(viewer, scene)
    window = main_window.window
    widget = main_window.viewer_widget
    workplane = Workplane.world_xy()

    window.resize(960, 640)
    window.show()
    widget.setFocus()

    try:
        _wait_for_initial_display(qapp, viewer, widget)

        widget._pending_sketch_tool = "line"
        widget._start_sketch_session(workplane, "XY", None)
        widget._navigation.view_iso()
        viewer.refresh_native_window()
        _settle(qapp)

        for uv in ((0.0, 0.0), (40.0, 0.0), (40.0, 20.0)):
            _click_sketch_uv(qapp, viewer, widget, workplane, uv)

        start = _sketch_uv_to_widget_point(viewer, widget, workplane, (0.0, 0.0))
        close = QPoint(start.x() + 10, start.y() + 8)
        assert widget.rect().contains(close)
        QTest.mouseClick(widget, Qt.LeftButton, Qt.NoModifier, close)
        _settle(qapp)

        profiles = [
            item
            for item in scene
            if item.meta.get("kind") == SKETCH_META_KIND
            and item.meta.get("profile") == "line_polyline"
        ]
        assert len(profiles) == 1
        assert len(profiles[0].meta.get("segments_uv", ())) == 3
    finally:
        window.close()
        viewer.close()
        qapp.processEvents()


@pytest.mark.gui
def test_real_click_draws_arc_entity_on_sketch_plane(qapp) -> None:
    require_gui_enabled()

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.sketch import SKETCH_ENTITY_META_KIND
    from cad_app.sketch_graph import curves_from_meta
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    scene = Scene()
    viewer = Viewer()
    main_window = create_main_window(viewer, scene)
    window = main_window.window
    widget = main_window.viewer_widget
    workplane = Workplane.world_xy()

    window.resize(960, 640)
    window.show()
    widget.setFocus()

    try:
        _wait_for_initial_display(qapp, viewer, widget)

        widget._pending_sketch_tool = "arc"
        widget._start_sketch_session(workplane, "XY", None)
        _settle(qapp)

        for uv in ((-40.0, 0.0), (40.0, 0.0), (0.0, 35.0)):
            _click_sketch_uv(qapp, viewer, widget, workplane, uv)

        arcs = [
            item
            for item in scene
            if item.meta.get("kind") == SKETCH_ENTITY_META_KIND
            and item.meta.get("profile") == "arc"
        ]
        assert len(arcs) == 1
        curves = curves_from_meta(arcs[0].meta)
        assert len(curves) == 1
        assert curves[0].kind == "arc"
        assert float(arcs[0].meta["radius"]) > 0.0
        assert widget._sketch_session is not None
        assert widget._sketch_session.tool == "arc"
    finally:
        window.close()
        viewer.close()
        qapp.processEvents()


@pytest.mark.gui
def test_real_click_trim_two_intersecting_circles_removes_arc(qapp) -> None:
    require_gui_enabled()

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.sketch import SKETCH_ENTITY_META_KIND, SKETCH_META_KIND
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    scene = Scene()
    viewer = Viewer()
    main_window = create_main_window(viewer, scene)
    window = main_window.window
    widget = main_window.viewer_widget
    workplane = Workplane.world_xy()

    window.resize(960, 640)
    window.show()
    widget.setFocus()

    try:
        _wait_for_initial_display(qapp, viewer, widget)

        widget._pending_sketch_tool = "circle"
        widget._start_sketch_session(workplane, "XY", None)
        _settle(qapp)

        for uv in ((-25.0, 0.0), (15.0, 0.0), (25.0, 0.0), (65.0, 0.0)):
            _click_sketch_uv(qapp, viewer, widget, workplane, uv)

        assert {
            item.meta.get("region_role")
            for item in scene
            if item.meta.get("kind") == SKETCH_META_KIND
        } == {"base", "intersection", "tool"}

        widget._set_sketch_tool("trim")
        _settle(qapp)
        _click_sketch_uv(qapp, viewer, widget, workplane, (-65.0, 0.0))

        assert widget._last_status_text == "Sketch segment trimmed"
        assert any(
            item.meta.get("profile") == "arc_segment"
            for item in scene
            if item.meta.get("kind") == SKETCH_ENTITY_META_KIND
        )
        assert any(
            item.meta.get("region_role") in {"intersection", "tool"}
            for item in scene
            if item.meta.get("kind") == SKETCH_META_KIND
        )
    finally:
        window.close()
        viewer.close()
        qapp.processEvents()


@pytest.mark.gui
def test_middle_drag_does_not_mutate_selection_or_scene(qapp) -> None:
    require_gui_enabled()

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from cad_app.types import SelectionKind, SelectionRef
    from tests.helpers.topology import scene_fingerprint

    fixture = create_box_contract_window()
    main_window = fixture.main_window
    window = main_window.window
    widget = main_window.viewer_widget
    viewer = main_window.viewer
    scene = main_window.scene

    window.resize(960, 640)
    window.show()
    widget.setFocus()

    try:
        _wait_for_initial_display(qapp, viewer, widget)

        widget._selection_kind = SelectionKind.OBJECT
        viewer.set_selection_kind(SelectionKind.OBJECT)
        widget._set_active_category("select")
        scene.set_selection(SelectionRef(fixture.item_id, SelectionKind.OBJECT, 0))
        _settle(qapp)

        fingerprint_before = scene_fingerprint(scene)
        selection_before = scene.selection()

        center = QPoint(widget.width() // 2, widget.height() // 2)
        QTest.mousePress(widget, Qt.MiddleButton, Qt.NoModifier, center)
        QTest.mouseMove(widget, QPoint(center.x() + 80, center.y() - 20))
        QTest.mouseRelease(
            widget,
            Qt.MiddleButton,
            Qt.NoModifier,
            QPoint(center.x() + 80, center.y() - 20),
        )
        _settle(qapp)

        assert scene_fingerprint(scene) == fingerprint_before
        assert scene.selection() == selection_before
    finally:
        window.close()
        viewer.close()
        qapp.processEvents()
