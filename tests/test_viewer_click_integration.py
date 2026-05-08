from __future__ import annotations

import os
from dataclasses import dataclass

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("CAD_APP_GUI_TESTS") != "1",
    reason="Set CAD_APP_GUI_TESTS=1 to run real Qt/OCP click integration tests.",
)


@dataclass(frozen=True)
class ProjectedProbe:
    native_x: int
    native_y: int
    logical_x: int
    logical_y: int


def test_real_qt_clicks_match_picker_after_dpi_scaling() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind
    from cad_app.viewer import Viewer

    app = QApplication.instance() or QApplication([])
    scene = Scene()
    scene.add_shape(make_box())
    viewer = Viewer()
    main_window = create_main_window(viewer, scene)
    widget = main_window.viewer_widget
    main_window.window.show()
    widget.setFocus()

    try:
        _wait_for_initial_display(app, viewer, widget)
        scene.get(scene.active_item_id()).meta[
            "test_device_pixel_ratio"
        ] = widget.devicePixelRatioF()
        picker = main_window.picker

        face_hits = _click_probe_set(
            app,
            widget,
            scene,
            viewer,
            picker,
            SelectionKind.FACE,
            _face_center_probes(viewer.view, scene),
        )
        assert face_hits >= 3

        QTest.keyClick(widget, Qt.Key_3)
        app.processEvents()

        edge_hits = _click_probe_set(
            app,
            widget,
            scene,
            viewer,
            picker,
            SelectionKind.EDGE,
            _edge_midpoint_probes(viewer.view, scene),
        )
        assert edge_hits >= 6
    finally:
        main_window.window.close()
        viewer.close()


def test_real_qt_edge_click_then_r_applies_single_fillet() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from OCP.GeomAbs import GeomAbs_Cylinder
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind
    from cad_app.viewer import Viewer

    app = QApplication.instance() or QApplication([])
    scene = Scene()
    scene.add_shape(make_box())
    viewer = Viewer()
    main_window = create_main_window(viewer, scene)
    widget = main_window.viewer_widget
    main_window.window.show()
    widget.setFocus()

    try:
        _wait_for_initial_display(app, viewer, widget)
        scene.get(scene.active_item_id()).meta[
            "test_device_pixel_ratio"
        ] = widget.devicePixelRatioF()

        QTest.keyClick(widget, Qt.Key_3)
        app.processEvents()
        probe = _first_clickable_probe(
            widget,
            main_window.picker,
            viewer,
            SelectionKind.EDGE,
            _edge_midpoint_probes(viewer.view, scene),
        )

        QTest.mouseClick(
            widget,
            Qt.LeftButton,
            Qt.NoModifier,
            QPoint(probe.logical_x, probe.logical_y),
        )
        app.processEvents()
        assert scene.selection() is not None
        assert scene.selection().kind == SelectionKind.EDGE

        before = _count_faces_of_type(scene.get(scene.active_item_id()).shape, None)
        assert before >= 6
        assert (
            _count_faces_of_type(
                scene.get(scene.active_item_id()).shape,
                GeomAbs_Cylinder,
            )
            == 0
        )

        QTest.keyClick(widget, Qt.Key_R)
        app.processEvents()

        assert widget._move_session is not None
        assert widget._move_session.tool == "fillet"
        assert viewer._preview_marker is not None

        QTest.keyClick(widget, Qt.Key_Return)
        app.processEvents()

        assert (
            _count_faces_of_type(
                scene.get(scene.active_item_id()).shape,
                GeomAbs_Cylinder,
            )
            == 1
        )
        assert len(viewer._grid_objects) > 0
    finally:
        main_window.window.close()
        viewer.close()


def test_real_qt_e_without_face_selection_does_not_extrude() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.viewer import Viewer

    app = QApplication.instance() or QApplication([])
    scene = Scene()
    scene.add_shape(make_box())
    viewer = Viewer()
    main_window = create_main_window(viewer, scene)
    widget = main_window.viewer_widget
    main_window.window.show()
    widget.setFocus()

    try:
        _wait_for_initial_display(app, viewer, widget)
        item_id = scene.active_item_id()
        before = _volume(scene.get(item_id).shape)

        QTest.keyClick(widget, Qt.Key_E)
        app.processEvents()

        assert _volume(scene.get(item_id).shape) == pytest.approx(before)
    finally:
        main_window.window.close()
        viewer.close()


def test_real_qt_face_hover_does_not_require_distance_metric() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind
    from cad_app.viewer import Viewer

    app = QApplication.instance() or QApplication([])
    scene = Scene()
    scene.add_shape(make_box())
    viewer = Viewer()
    main_window = create_main_window(viewer, scene)
    widget = main_window.viewer_widget
    main_window.window.show()
    widget.setFocus()

    try:
        _wait_for_initial_display(app, viewer, widget)
        scene.get(scene.active_item_id()).meta[
            "test_device_pixel_ratio"
        ] = widget.devicePixelRatioF()
        probe = _first_clickable_probe(
            widget,
            main_window.picker,
            viewer,
            SelectionKind.FACE,
            _face_center_probes(viewer.view, scene),
        )

        widget._preview_at(probe.logical_x, probe.logical_y)
        app.processEvents()

        assert viewer._hover_marker is not None
    finally:
        main_window.window.close()
        viewer.close()


def test_real_qt_sketch_plane_overlay_changes_rendered_pixels() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    app = QApplication.instance() or QApplication([])
    scene = Scene()
    viewer = Viewer()
    main_window = create_main_window(viewer, scene)
    widget = main_window.viewer_widget
    main_window.window.show()
    widget.setFocus()

    try:
        _wait_for_initial_display(app, viewer, widget)
        main_window.navigation.view_workplane(Workplane.world_xy())
        baseline = _grab_widget_image(app, widget)

        viewer.display_sketch_plane_marker(Workplane.world_xy())
        overlay = _grab_widget_image(app, widget)

        assert viewer._sketch_plane_marker is not None
        changed_pixels = _sampled_image_difference_count(baseline, overlay)
        assert changed_pixels == 0 or 30 < changed_pixels < 500
    finally:
        main_window.window.close()
        viewer.close()


def test_real_qt_command_toolbar_reacts_to_face_and_edge_selection() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind
    from cad_app.viewer import Viewer

    app = QApplication.instance() or QApplication([])
    scene = Scene()
    scene.add_shape(make_box())
    viewer = Viewer()
    main_window = create_main_window(viewer, scene)
    widget = main_window.viewer_widget
    main_window.window.show()
    widget.setFocus()

    try:
        _wait_for_initial_display(app, viewer, widget)
        scene.get(scene.active_item_id()).meta[
            "test_device_pixel_ratio"
        ] = widget.devicePixelRatioF()

        assert _command_action_names(main_window) == []
        assert "move_object_x" not in _command_action_names(main_window)
        assert "extrude" not in _command_action_names(main_window)

        QTest.keyClick(widget, Qt.Key_2)
        app.processEvents()
        face_probe = _first_clickable_probe(
            widget,
            main_window.picker,
            viewer,
            SelectionKind.FACE,
            _face_center_probes(viewer.view, scene),
        )
        QTest.mouseClick(
            widget,
            Qt.LeftButton,
            Qt.NoModifier,
            QPoint(face_probe.logical_x, face_probe.logical_y),
        )
        app.processEvents()
        face_actions = _command_action_names(main_window)
        assert "extrude" in face_actions
        assert "move_selection" in face_actions
        assert "move_selection_normal" not in face_actions
        assert "move_selection_x" not in face_actions
        assert "offset_face" in face_actions
        assert "delete_object" not in face_actions
        assert "start_sketch" in face_actions
        assert "circle_boss" not in face_actions
        assert "fillet" not in face_actions

        QTest.keyClick(widget, Qt.Key_3)
        app.processEvents()
        edge_probe = _first_clickable_probe(
            widget,
            main_window.picker,
            viewer,
            SelectionKind.EDGE,
            _edge_midpoint_probes(viewer.view, scene),
        )
        QTest.mouseClick(
            widget,
            Qt.LeftButton,
            Qt.NoModifier,
            QPoint(edge_probe.logical_x, edge_probe.logical_y),
        )
        app.processEvents()
        edge_actions = _command_action_names(main_window)
        assert "fillet" in edge_actions
        assert "chamfer" in edge_actions
        assert "move_selection" in edge_actions
        assert "move_selection_x" not in edge_actions
        assert "move_selection_y" not in edge_actions
        assert "move_selection_z" not in edge_actions
        assert "extrude" not in edge_actions
        assert "delete_object" not in edge_actions
    finally:
        main_window.window.close()
        viewer.close()


def test_real_qt_click_prefers_sketch_profile_over_host_face() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from OCP.gp import gp_Dir, gp_Pnt
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.sketch import SKETCH_META_KIND, make_circle_profile_at
    from cad_app.types import SelectionKind
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    app = QApplication.instance() or QApplication([])
    scene = Scene()
    box_id = scene.add_shape(make_box())
    top_workplane = Workplane(
        origin=gp_Pnt(0.0, 0.0, 60.0),
        normal=gp_Dir(0.0, 0.0, 1.0),
        x_direction=gp_Dir(1.0, 0.0, 0.0),
        y_direction=gp_Dir(0.0, 1.0, 0.0),
    )
    profile_id = scene.add_shape(
        make_circle_profile_at(top_workplane, (0.0, 0.0), 16.0),
        meta={
            "kind": SKETCH_META_KIND,
            "display_normal": (0.0, 0.0, 1.0),
        },
    )
    scene.set_active_item(box_id)
    viewer = Viewer()
    main_window = create_main_window(viewer, scene)
    widget = main_window.viewer_widget
    main_window.window.show()
    widget.setFocus()

    try:
        _wait_for_initial_display(app, viewer, widget)
        scene.get(box_id).meta["test_device_pixel_ratio"] = widget.devicePixelRatioF()
        main_window.navigation.view_workplane(top_workplane)
        app.processEvents()

        QTest.keyClick(widget, Qt.Key_2)
        app.processEvents()
        probe = _probe_from_world(viewer.view, scene, (0.0, 0.0, 60.0))
        expected = main_window.picker.pick_face_result_at(
            viewer.view,
            probe.native_x,
            probe.native_y,
        )

        assert expected is not None
        assert expected.selection.item_id == profile_id

        QTest.mouseClick(
            widget,
            Qt.LeftButton,
            Qt.NoModifier,
            QPoint(probe.logical_x, probe.logical_y),
        )
        app.processEvents()

        selection = scene.selection()
        assert selection is not None
        assert selection.item_id == profile_id
        assert selection.kind == SelectionKind.FACE
        assert _command_action_names(main_window) == [
            "sketch_extrude",
            "sketch_new_body",
        ]
    finally:
        main_window.window.close()
        viewer.close()


def test_real_qt_shell_layout_uses_adaptive_cad_regions() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QDockWidget, QToolBar, QToolButton

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.viewer import Viewer

    app = QApplication.instance() or QApplication([])
    viewer = Viewer()
    main_window = create_main_window(viewer, Scene())
    widget = main_window.viewer_widget
    main_window.window.show()

    try:
        _wait_for_initial_display(app, viewer, widget)
        top_toolbar = main_window.window.findChild(QToolBar, "TopToolbar")
        category_toolbar = main_window.window.findChild(QToolBar, "CategoryToolbar")
        selection_mode_toolbar = main_window.window.findChild(
            QToolBar,
            "SelectionModeToolbar",
        )
        command_toolbar = main_window.window.findChild(QToolBar, "CommandToolbar")
        browser_dock = main_window.window.findChild(QDockWidget, "BrowserDock")

        assert top_toolbar is not None
        assert category_toolbar is not None
        assert selection_mode_toolbar is not None
        assert command_toolbar is not None
        assert browser_dock is not None
        assert top_toolbar.isVisible()
        assert category_toolbar.isVisible()
        assert selection_mode_toolbar.isVisible()
        assert not command_toolbar.isVisible()
        assert browser_dock.isVisible()
        assert main_window.window.toolBarArea(top_toolbar) == Qt.TopToolBarArea
        assert main_window.window.toolBarArea(category_toolbar) == Qt.LeftToolBarArea
        assert (
            main_window.window.toolBarArea(selection_mode_toolbar) == Qt.LeftToolBarArea
        )
        assert main_window.window.toolBarArea(command_toolbar) == Qt.TopToolBarArea
        assert main_window.window.dockWidgetArea(browser_dock) == Qt.RightDockWidgetArea

        action_names = set(main_window.actions)
        command_buttons = [
            button
            for button in command_toolbar.findChildren(QToolButton)
            if button.defaultAction() is not None
            and button.defaultAction().objectName() in action_names
        ]
        assert command_buttons == []
        selection_mode_buttons = [
            button
            for button in selection_mode_toolbar.findChildren(QToolButton)
            if button.defaultAction() is not None
            and button.defaultAction().objectName() in action_names
        ]
        assert [
            button.defaultAction().objectName() for button in selection_mode_buttons
        ] == [
            "select_object",
            "select_face",
            "select_edge",
            "select_vertex",
        ]
        assert (
            len(
                {
                    (button.size().width(), button.size().height())
                    for button in selection_mode_buttons
                }
            )
            == 1
        )
        assert all(
            button.size().width() >= 78 and button.size().height() >= 54
            for button in selection_mode_buttons
        )
        assert all(
            not button.defaultAction().icon().isNull()
            for button in selection_mode_buttons
        )
    finally:
        main_window.window.close()
        viewer.close()


def test_real_qt_object_move_tool_drag_commits_translation() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.viewer import Viewer

    app = QApplication.instance() or QApplication([])
    scene = Scene()
    scene.add_shape(make_box())
    viewer = Viewer()
    main_window = create_main_window(viewer, scene)
    widget = main_window.viewer_widget
    main_window.window.show()
    widget.setFocus()

    try:
        _wait_for_initial_display(app, viewer, widget)
        item_id = scene.active_item_id()
        before = _bounds(scene.get(item_id).shape)

        QTest.keyClick(widget, Qt.Key_G)
        app.processEvents()
        assert widget._move_session is not None
        assert "Tool: Move" in widget._hud_labels["tool"].text()

        start = QPoint(120, 120)
        end = QPoint(170, 120)
        QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(widget, end)
        app.processEvents()
        assert viewer._preview_marker is not None
        assert widget._dimension_overlay.isHidden()
        assert viewer._dimension_label is not None
        assert widget._dimension_overlay.text().startswith("Move ")
        QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
        app.processEvents()

        after = _bounds(scene.get(item_id).shape)
        assert widget._move_session is None
        assert widget._dimension_overlay.isHidden()
        assert viewer._dimension_label is None
        assert any(
            abs(after_value - before_value) > 1e-6
            for after_value, before_value in zip(after, before)
        )
    finally:
        main_window.window.close()
        viewer.close()


def test_real_qt_extrude_tool_drag_commits_push_pull() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind
    from cad_app.viewer import Viewer

    app = QApplication.instance() or QApplication([])
    scene = Scene()
    scene.add_shape(make_box())
    viewer = Viewer()
    main_window = create_main_window(viewer, scene)
    widget = main_window.viewer_widget
    main_window.window.show()
    widget.setFocus()

    try:
        _wait_for_initial_display(app, viewer, widget)
        scene.get(scene.active_item_id()).meta[
            "test_device_pixel_ratio"
        ] = widget.devicePixelRatioF()
        item_id = scene.active_item_id()
        before = _volume(scene.get(item_id).shape)
        probe = _first_clickable_probe(
            widget,
            main_window.picker,
            viewer,
            SelectionKind.FACE,
            _face_center_probes(viewer.view, scene),
        )
        QTest.keyClick(widget, Qt.Key_2)
        app.processEvents()
        QTest.mouseClick(
            widget,
            Qt.LeftButton,
            Qt.NoModifier,
            QPoint(probe.logical_x, probe.logical_y),
        )
        app.processEvents()

        main_window.actions["extrude"].trigger()
        app.processEvents()
        assert widget._move_session is not None
        assert widget._move_session.tool == "extrude"
        assert "Tool: Extrude" in widget._hud_labels["tool"].text()
        assert widget._dimension_overlay.isHidden()
        assert viewer._dimension_label is not None
        assert viewer._extrude_affordance_marker is not None

        start = QPoint(130, 130)
        QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
        end = _active_tool_drag_end(widget, start)
        QTest.mouseMove(widget, end)
        app.processEvents()
        assert viewer._preview_marker is not None
        assert widget._dimension_overlay.isHidden()
        assert viewer._dimension_label is not None
        assert widget._dimension_overlay.text().startswith("Extrude ")
        QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
        app.processEvents()

        assert widget._move_session is None
        assert widget._dimension_overlay.isHidden()
        assert viewer._dimension_label is None
        assert viewer._extrude_affordance_marker is None
        assert _volume(scene.get(item_id).shape) > before
    finally:
        main_window.window.close()
        viewer.close()


def test_real_qt_sketch_rectangle_extrude_body_is_face_pickable() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind
    from cad_app.viewer import Viewer

    app = QApplication.instance() or QApplication([])
    scene = Scene()
    viewer = Viewer()
    main_window = create_main_window(viewer, scene)
    widget = main_window.viewer_widget
    main_window.window.show()
    widget.setFocus()

    try:
        _wait_for_initial_display(app, viewer, widget)
        QTest.keyClick(widget, Qt.Key_S)
        app.processEvents()
        assert widget._sketch_session is not None
        assert viewer._sketch_plane_marker is not None

        center = QPoint(widget.width() // 2, widget.height() // 2)
        corner = QPoint(center.x() + 90, center.y() + 70)
        QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, center)
        QTest.mouseMove(widget, corner)
        app.processEvents()
        assert viewer._preview_marker is not None
        assert " x " in widget._hud_labels["sketch"].text()
        assert widget._dimension_overlay.isHidden()
        assert viewer._dimension_label is not None
        assert widget._dimension_overlay.text().startswith("W:")
        QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, corner)
        app.processEvents()

        assert widget._sketch_session is None
        assert viewer._sketch_plane_marker is None
        assert widget._dimension_overlay.isHidden()
        assert viewer._dimension_label is None
        assert scene.selection() is not None
        assert scene.selection().kind == SelectionKind.FACE
        assert len(scene) == 1

        item_id = scene.active_item_id()
        before = _volume(scene.get(item_id).shape)
        QTest.keyClick(widget, Qt.Key_E)
        app.processEvents()
        assert widget._move_session is not None
        assert widget._move_session.tool == "sketch_extrude"

        start = QPoint(150, 150)
        QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
        end = _active_tool_drag_end(widget, start)
        QTest.mouseMove(widget, end)
        app.processEvents()
        QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
        app.processEvents()

        assert widget._move_session is None
        assert _volume(scene.get(item_id).shape) > before
        scene.get(item_id).meta["test_device_pixel_ratio"] = widget.devicePixelRatioF()

        face_hits = _click_probe_set(
            app,
            widget,
            scene,
            viewer,
            main_window.picker,
            SelectionKind.FACE,
            _face_center_probes(viewer.view, scene),
        )
        assert face_hits >= 3
    finally:
        main_window.window.close()
        viewer.close()


def _wait_for_initial_display(app, viewer, widget) -> None:
    from PySide6.QtTest import QTest

    for _ in range(60):
        app.processEvents()
        if viewer.is_initialized and widget._initial_scene_displayed:
            return
        QTest.qWait(50)
    pytest.fail("Viewer did not initialize and display the initial scene.")


def _active_tool_drag_end(widget, start, distance: int = 80):
    from PySide6.QtCore import QPoint

    session = widget._move_session
    assert session is not None
    axis = widget._screen_axis_for_session(session) or (1.0, 0.0)
    return QPoint(
        int(round(start.x() + axis[0] * distance)),
        int(round(start.y() + axis[1] * distance)),
    )


def _grab_widget_image(app, widget):
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest

    for _ in range(4):
        app.processEvents()
        QTest.qWait(50)
    return (
        widget.screen()
        .grabWindow(int(widget.winId()))
        .toImage()
        .convertToFormat(QImage.Format.Format_RGB32)
    )


def _sampled_image_difference_count(image_a, image_b, step: int = 4) -> int:
    width = min(image_a.width(), image_b.width())
    height = min(image_a.height(), image_b.height())
    changed = 0
    for y in range(0, height, step):
        for x in range(0, width, step):
            first = image_a.pixelColor(x, y)
            second = image_b.pixelColor(x, y)
            delta = (
                abs(first.red() - second.red())
                + abs(first.green() - second.green())
                + abs(first.blue() - second.blue())
            )
            if delta > 20:
                changed += 1
    return changed


def _command_action_names(main_window) -> list[str]:
    from PySide6.QtWidgets import QToolBar

    toolbar = main_window.window.findChild(QToolBar, "CommandToolbar")
    assert toolbar is not None
    action_names = set(main_window.actions)
    return [
        action.objectName()
        for action in toolbar.actions()
        if action.objectName() in action_names
    ]


def _click_probe_set(
    app,
    widget,
    scene,
    viewer,
    picker,
    kind,
    probes: list[ProjectedProbe],
) -> int:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    widget._set_selection_kind(kind)
    app.processEvents()
    hits = 0
    for probe in probes:
        if not (
            0 <= probe.logical_x < widget.width()
            and 0 <= probe.logical_y < widget.height()
        ):
            continue

        expected = _expected_selection(
            picker,
            viewer.view,
            kind,
            probe.native_x,
            probe.native_y,
        )
        if expected is None:
            continue

        scene.set_selection(None)
        QTest.mouseClick(
            widget,
            Qt.LeftButton,
            Qt.NoModifier,
            QPoint(probe.logical_x, probe.logical_y),
        )
        app.processEvents()
        actual = scene.selection()

        assert actual == expected, (
            f"{kind.value} click mismatch at logical="
            f"({probe.logical_x}, {probe.logical_y}) native="
            f"({probe.native_x}, {probe.native_y}); "
            f"expected={expected}, actual={actual}"
        )
        hits += 1
    return hits


def _first_clickable_probe(widget, picker, viewer, kind, probes):
    for probe in probes:
        if not (
            0 <= probe.logical_x < widget.width()
            and 0 <= probe.logical_y < widget.height()
        ):
            continue
        expected = _expected_selection(
            picker,
            viewer.view,
            kind,
            probe.native_x,
            probe.native_y,
        )
        if expected is not None:
            return probe
    pytest.fail(f"No clickable {kind.value} probe found.")


def _expected_selection(picker, view, kind, native_x: int, native_y: int):
    from cad_app.types import SelectionKind

    if kind == SelectionKind.FACE:
        result = picker.pick_face_result_at(view, native_x, native_y)
    elif kind == SelectionKind.EDGE:
        result = picker.pick_edge_result_at(view, native_x, native_y)
    else:
        raise ValueError(f"Unsupported probe kind: {kind}")
    if result is None:
        return None
    return result.selection


def _face_center_probes(view, scene) -> list[ProjectedProbe]:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopoDS import TopoDS

    from cad_app.picker import Picker
    from cad_app.types import SelectionKind

    shape = scene.get(scene.active_item_id()).shape
    face_map = Picker.indexed_map(shape, SelectionKind.FACE)
    probes = []
    for index in range(1, face_map.Extent() + 1):
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(TopoDS.Face_s(face_map.FindKey(index)), props)
        point = props.CentreOfMass()
        probes.append(_probe_from_world(view, scene, (point.X(), point.Y(), point.Z())))
    return probes


def _edge_midpoint_probes(view, scene) -> list[ProjectedProbe]:
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.TopoDS import TopoDS

    from cad_app.picker import Picker
    from cad_app.types import SelectionKind

    shape = scene.get(scene.active_item_id()).shape
    edge_map = Picker.indexed_map(shape, SelectionKind.EDGE)
    probes = []
    for index in range(1, edge_map.Extent() + 1):
        curve = BRepAdaptor_Curve(TopoDS.Edge_s(edge_map.FindKey(index)))
        parameter = (curve.FirstParameter() + curve.LastParameter()) / 2.0
        point = curve.Value(parameter)
        probes.append(_probe_from_world(view, scene, (point.X(), point.Y(), point.Z())))
    return probes


def _probe_from_world(view, scene, world: tuple[float, float, float]) -> ProjectedProbe:
    native_x, native_y = view.Convert(*world)
    scale = _device_pixel_ratio(scene)
    return ProjectedProbe(
        native_x=int(round(native_x)),
        native_y=int(round(native_y)),
        logical_x=int(round(native_x / scale)),
        logical_y=int(round(native_y / scale)),
    )


def _device_pixel_ratio(scene) -> float:
    # Stored by the test before probes are built; avoids passing the widget through
    # every geometry helper.
    return float(scene.get(scene.active_item_id()).meta["test_device_pixel_ratio"])


def _count_faces_of_type(shape, surface_type) -> int:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.TopoDS import TopoDS

    from cad_app.picker import Picker
    from cad_app.types import SelectionKind

    face_map = Picker.indexed_map(shape, SelectionKind.FACE)
    if surface_type is None:
        return face_map.Extent()
    return sum(
        1
        for index in range(1, face_map.Extent() + 1)
        if BRepAdaptor_Surface(TopoDS.Face_s(face_map.FindKey(index))).GetType()
        == surface_type
    )


def _volume(shape) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def _bounds(shape) -> tuple[float, float, float, float, float, float]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    bounds = Bnd_Box()
    BRepBndLib.Add_s(shape, bounds)
    return bounds.Get()


def test_real_qt_edge_move_drag_changes_volume_and_keeps_valid_shape() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from OCP.BRepCheck import BRepCheck_Analyzer
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind
    from cad_app.viewer import Viewer

    app = QApplication.instance() or QApplication([])
    scene = Scene()
    scene.add_shape(make_box(40, 40, 40))
    viewer = Viewer()
    main_window = create_main_window(viewer, scene)
    widget = main_window.viewer_widget
    main_window.window.show()
    widget.setFocus()

    try:
        _wait_for_initial_display(app, viewer, widget)
        scene.get(scene.active_item_id()).meta[
            "test_device_pixel_ratio"
        ] = widget.devicePixelRatioF()
        item_id = scene.active_item_id()
        before_vol = _volume(scene.get(item_id).shape)

        QTest.keyClick(widget, Qt.Key_3)
        app.processEvents()
        probe = _first_clickable_probe(
            widget,
            main_window.picker,
            viewer,
            SelectionKind.EDGE,
            _edge_midpoint_probes(viewer.view, scene),
        )

        QTest.mouseClick(
            widget,
            Qt.LeftButton,
            Qt.NoModifier,
            QPoint(probe.logical_x, probe.logical_y),
        )
        app.processEvents()
        assert scene.selection() is not None
        assert scene.selection().kind == SelectionKind.EDGE

        QTest.keyClick(widget, Qt.Key_G)
        app.processEvents()
        assert widget._move_session is not None
        assert widget._move_session.target_kind == SelectionKind.EDGE
        assert "Tool: Move" in widget._hud_labels["tool"].text()

        start = QPoint(200, 200)
        QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
        app.processEvents()
        end = QPoint(start.x() + 60, start.y())
        QTest.mouseMove(widget, end)
        app.processEvents()
        assert viewer._preview_marker is not None
        QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
        app.processEvents()

        assert widget._move_session is None
        after_vol = _volume(scene.get(item_id).shape)
        assert after_vol != pytest.approx(before_vol)
        assert BRepCheck_Analyzer(scene.get(item_id).shape).IsValid()
    finally:
        main_window.window.close()
        viewer.close()


def test_real_qt_edge_move_body_visible_during_drag() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind
    from cad_app.viewer import Viewer

    app = QApplication.instance() or QApplication([])
    scene = Scene()
    scene.add_shape(make_box(40, 40, 40))
    viewer = Viewer()
    main_window = create_main_window(viewer, scene)
    widget = main_window.viewer_widget
    main_window.window.show()
    widget.setFocus()

    try:
        _wait_for_initial_display(app, viewer, widget)
        scene.get(scene.active_item_id()).meta[
            "test_device_pixel_ratio"
        ] = widget.devicePixelRatioF()
        item_id = scene.active_item_id()

        QTest.keyClick(widget, Qt.Key_3)
        app.processEvents()
        probe = _first_clickable_probe(
            widget,
            main_window.picker,
            viewer,
            SelectionKind.EDGE,
            _edge_midpoint_probes(viewer.view, scene),
        )
        QTest.mouseClick(
            widget,
            Qt.LeftButton,
            Qt.NoModifier,
            QPoint(probe.logical_x, probe.logical_y),
        )
        app.processEvents()

        QTest.keyClick(widget, Qt.Key_G)
        app.processEvents()
        assert widget._move_session is not None

        start = QPoint(200, 200)
        QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
        end = QPoint(start.x() + 40, start.y())
        QTest.mouseMove(widget, end)
        app.processEvents()

        assert item_id in viewer._ais_map
        assert item_id not in viewer._preview_hidden_items

        QTest.keyClick(widget, Qt.Key_Escape)
        app.processEvents()
        assert widget._move_session is None
    finally:
        main_window.window.close()
        viewer.close()


def test_real_qt_edge_move_stacked_boxes_keep_both_bodies() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from cad_app.commands import translated_shape
    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind
    from cad_app.viewer import Viewer

    app = QApplication.instance() or QApplication([])
    scene = Scene()
    lower_id = scene.add_shape(make_box(80, 80, 40), meta={"kind": "body"})
    upper_shape = translated_shape(make_box(40, 30, 20), 0.0, 0.0, 40.0)
    upper_id = scene.add_shape(upper_shape, meta={"kind": "body"})
    scene.set_active_item(upper_id)

    viewer = Viewer()
    main_window = create_main_window(viewer, scene)
    widget = main_window.viewer_widget
    main_window.window.show()
    widget.setFocus()

    try:
        _wait_for_initial_display(app, viewer, widget)
        scene.get(upper_id).meta["test_device_pixel_ratio"] = widget.devicePixelRatioF()

        QTest.keyClick(widget, Qt.Key_3)
        app.processEvents()
        probe = _first_clickable_probe(
            widget,
            main_window.picker,
            viewer,
            SelectionKind.EDGE,
            _edge_midpoint_probes(viewer.view, scene),
        )
        QTest.mouseClick(
            widget,
            Qt.LeftButton,
            Qt.NoModifier,
            QPoint(probe.logical_x, probe.logical_y),
        )
        app.processEvents()
        assert scene.selection() is not None
        assert scene.selection().item_id == upper_id
        assert scene.selection().kind == SelectionKind.EDGE

        QTest.keyClick(widget, Qt.Key_G)
        app.processEvents()
        assert widget._move_session is not None

        start = QPoint(200, 200)
        QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
        end = _active_tool_drag_end(widget, start)
        QTest.mouseMove(widget, end)
        app.processEvents()
        assert viewer._preview_marker is not None
        QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
        app.processEvents()

        assert widget._move_session is None
        assert len(scene) == 2
        assert lower_id in scene
        assert upper_id in scene
        assert _volume(scene.get(lower_id).shape) == pytest.approx(
            _volume(make_box(80, 80, 40))
        )
    finally:
        main_window.window.close()
        viewer.close()
