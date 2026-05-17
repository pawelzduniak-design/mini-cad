from __future__ import annotations

import pytest

from tests.conftest import require_ocp


def _command_action_names(main_window) -> list[str]:
    return [
        action.objectName()
        for action in main_window.viewer_widget._command_toolbar.actions()
        if action.objectName() and not action.objectName().startswith("context_label_")
    ]


class _FakeView:
    def Convert(self, *_args):
        return (120, 160)


class _ProjectedAxisView:
    def Convert(self, x, y, z):
        return (100 + x * 2 - z, 100 - y * 3 - z * 2)


def test_category_rail_and_initial_context(qapp) -> None:
    from PySide6.QtWidgets import QDockWidget, QToolBar

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.ui_menu import CATEGORY_RAIL_ACTIONS, SKETCH_ACTIVE_ACTIONS
    from cad_app.viewer import Viewer

    main_window = create_main_window(Viewer(), Scene())
    category_toolbar = main_window.window.findChild(QToolBar, "left_menu")
    top_toolbar = main_window.window.findChild(QToolBar, "top_bar")

    assert list(main_window.actions) != []
    assert category_toolbar is not None
    assert top_toolbar is not None
    browser_dock = main_window.window.findChild(QDockWidget, "BrowserDock")
    assert browser_dock is not None
    assert browser_dock.isHidden()
    top_actions = [
        action.objectName() for action in top_toolbar.actions() if action.objectName()
    ]
    assert "new_project" in top_actions
    assert "save_project" not in top_actions
    assert not main_window.actions["save_project"].isVisible()
    rail_actions = [
        action.objectName()
        for action in category_toolbar.actions()
        if action.objectName().startswith("category_")
    ]
    assert rail_actions == list(CATEGORY_RAIL_ACTIONS)
    assert "category_create" not in rail_actions
    assert "category_file" not in rail_actions
    assert _command_action_names(main_window) == list(SKETCH_ACTIVE_ACTIONS)
    assert main_window.viewer_widget.get_ui_state().work_mode == "sketch"


def test_move_manipulator_arrows_follow_projected_world_axes(qapp, monkeypatch) -> None:
    from PySide6.QtCore import QPointF

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene, SceneObject
    from cad_app.types import SelectionKind
    from cad_app.ui_sessions import MoveSession
    from cad_app.viewer import Viewer

    main_window = create_main_window(Viewer(), Scene())
    widget = main_window.viewer_widget
    widget._viewer.is_initialized = True
    monkeypatch.setattr(widget._viewer, "_view", _ProjectedAxisView())
    monkeypatch.setattr(widget, "_move_anchor_point", lambda _session: (0.0, 0.0, 0.0))
    widget._scene._items["body"] = SceneObject(item_id="body", shape=None, meta={})
    widget._move_session = MoveSession(
        tool="move",
        target_kind=SelectionKind.OBJECT,
        item_id="body",
        index=0,
        axis_name="X",
        axis=(1.0, 0.0, 0.0),
    )

    directions = widget._move_manipulator_axis_directions()
    assert directions is not None
    assert directions["X"] == pytest.approx((1.0, 0.0))
    assert directions["Y"] == pytest.approx((0.0, -1.0))
    assert directions["Z"] == pytest.approx((-0.4472135955, -0.894427191))
    assert widget._screen_axis_for_session(widget._move_session) == pytest.approx(
        (1.0, 0.0)
    )

    overlay = widget._move_manipulator_overlay
    widget._refresh_move_manipulator()
    center = QPointF(78.0, 78.0)
    assert overlay.axis_at(QPointF(center.x() + 58.0, center.y())) == "X"
    assert overlay.axis_at(QPointF(center.x(), center.y() - 58.0)) == "Y"
    assert overlay.axis_at(QPointF(center.x() - 26.0, center.y() - 52.0)) == "Z"


def test_undo_hides_manipulator_when_target_disappears(qapp, monkeypatch) -> None:
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind
    from cad_app.ui_sessions import MoveSession
    from cad_app.viewer import Viewer

    main_window = create_main_window(Viewer(), Scene())
    widget = main_window.viewer_widget
    widget._viewer.is_initialized = True
    monkeypatch.setattr(widget._viewer, "_view", _ProjectedAxisView())
    monkeypatch.setattr(widget._viewer, "display_scene", lambda *_a, **_k: None)
    monkeypatch.setattr(widget._viewer, "clear_preview_marker", lambda *_a, **_k: None)
    monkeypatch.setattr(
        widget._viewer, "clear_extrude_affordance_marker", lambda *_a, **_k: None
    )
    monkeypatch.setattr(widget, "_move_anchor_point", lambda _session: (0.0, 0.0, 0.0))

    widget._move_session = MoveSession(
        tool="move",
        target_kind=SelectionKind.OBJECT,
        item_id="phantom-body",
        index=0,
        axis_name="X",
        axis=(1.0, 0.0, 0.0),
    )
    widget._refresh_move_manipulator()
    overlay = widget._move_manipulator_overlay

    assert not widget._move_manipulator_active()
    assert overlay.isHidden()

    monkeypatch.setattr(widget._scene, "undo", lambda: object())
    widget._undo()

    assert widget._move_session is None


def test_extrude_from_circle_leaves_body_ready_for_rotate(qapp) -> None:
    require_ocp()

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.sketch import SKETCH_META_KIND
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    main_window = create_main_window(Viewer(), Scene())
    widget = main_window.viewer_widget

    widget._sketch_session = None
    widget._start_sketch_session(Workplane.world_xy(), "Bottom plane", None)
    widget._set_sketch_tool("circle")
    widget._handle_sketch_click(widget._sketch_session, (0.0, 0.0), 0, 0)
    widget._handle_sketch_click(widget._sketch_session, (20.0, 0.0), 0, 0)
    profile_id = next(
        item.item_id
        for item in widget._scene
        if item.meta.get("kind") == SKETCH_META_KIND
    )
    widget._scene.set_selection(
        SelectionRef(item_id=profile_id, kind=SelectionKind.FACE, index=1)
    )
    widget._selection_kind = SelectionKind.FACE
    widget._begin_extrude_tool()
    assert widget._move_session is not None
    widget._move_session.distance = 30.0
    widget._commit_move_session()

    # The new body must be selectable as an OBJECT so the Body context
    # panel keeps Rotate Body reachable without a second click. Prior
    # behavior left _selection_kind=FACE which demoted the selection
    # on the first viewport click.
    assert widget._selection_kind == SelectionKind.OBJECT
    assert widget._active_category == "transform"
    selection = widget._scene.selection()
    assert selection is not None and selection.kind == SelectionKind.OBJECT

    widget._refresh_action_state()
    widget._refresh_command_surface()
    visible = [
        action.objectName()
        for action in widget._command_toolbar.actions()
        if action.objectName()
    ]
    assert "rotate_body" in visible
    assert widget._actions["rotate_body"].isEnabled()

    widget._begin_object_rotate_tool()
    assert widget._move_session is not None and widget._move_session.tool == "rotate"


def test_face_selection_marker_is_filled_not_wireframe() -> None:
    """Face selection must be rendered as a translucent filled overlay
    so a beginner clicking the cylinder side face does not see the
    side face's perimeter (top circle + bottom circle) lit up and
    misread it as "top + bottom face selected"."""
    require_ocp()

    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer

    from cad_app.viewer import Viewer

    cylinder = BRepPrimAPI_MakeCylinder(5.0, 10.0).Shape()
    exp = TopExp_Explorer(cylinder, TopAbs_FACE)
    assert exp.More()
    side_face = exp.Current()
    assert side_face.ShapeType() == TopAbs_FACE

    viewer = Viewer()
    assert viewer._prefers_wireframe_marker(side_face) is False


def test_native_orientation_gizmo_keeps_coordinate_axes(monkeypatch) -> None:
    require_ocp()

    import OCP.AIS as ais

    from cad_app.viewer import Viewer

    draw_axes_calls: list[bool] = []

    class FakeView:
        def TriedronErase(self) -> None:
            return

    class FakeContext:
        def Remove(self, *_args) -> None:
            return

        def Display(self, *_args) -> None:
            return

        def Activate(self, *_args) -> None:
            return

    class FakeViewCube:
        def __getattr__(self, _name):
            return lambda *_args, **_kwargs: None

        def SetDrawAxes(self, value: bool) -> None:
            draw_axes_calls.append(value)

    monkeypatch.setattr(ais, "AIS_ViewCube", FakeViewCube)

    viewer = Viewer()
    viewer.is_initialized = True
    viewer._view = FakeView()
    viewer._context = FakeContext()

    viewer.display_orientation_gizmo()

    assert draw_axes_calls == [True]


def test_qt_orientation_gizmo_does_not_paint_view_buttons(qapp, monkeypatch) -> None:
    from PySide6.QtGui import QPixmap

    from cad_app.viewer_widget_overlays import OrientationGizmoOverlay

    overlay = OrientationGizmoOverlay()
    calls: list[bool] = []
    monkeypatch.setattr(
        overlay, "_draw_view_buttons", lambda _painter: calls.append(True)
    )

    pixmap = QPixmap(overlay.size())
    overlay.render(pixmap)

    assert calls == []
    assert overlay.view_at(78, 18) == ("z", True, "Top")


def test_line_close_can_snap_by_screen_distance_after_view_rotation(
    qapp,
    monkeypatch,
) -> None:
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.ui_sessions import SketchSession
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    class FakeView:
        def Convert(self, *_args):
            return (100.0, 100.0)

    main_window = create_main_window(Viewer(), Scene())
    widget = main_window.viewer_widget
    widget._viewer.is_initialized = True
    monkeypatch.setattr(widget._viewer, "_view", FakeView())
    session = SketchSession(Workplane.world_xy(), "XY", None, tool="line")
    session.points = [(0.0, 0.0), (40.0, 0.0), (40.0, 20.0)]

    assert widget._closed_line_point(session, (8.0, 8.0), 108, 106) == (0.0, 0.0)
    assert widget._closed_line_point(session, (8.0, 8.0), 140, 140) is None


def test_start_sketch_uses_bottom_plane_without_host(qapp) -> None:
    require_ocp()

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.viewer import Viewer

    main_window = create_main_window(Viewer(), Scene())
    widget = main_window.viewer_widget

    assert widget._sketch_session is not None
    assert widget._sketch_session.host is None
    assert widget._active_workplane_host is None
    assert widget.get_ui_state().active_tool.startswith("sketch:")


def test_start_sketch_on_body_face_sets_feature_host(qapp) -> None:
    require_ocp()

    from cad_app.commands import top_planar_face_index
    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    scene = Scene()
    shape = make_box()
    item_id = scene.add_shape(shape, meta={"kind": "body", "source": "primitive_box"})
    face_index = top_planar_face_index(shape)
    scene.set_selection(SelectionRef(item_id, SelectionKind.FACE, face_index))
    main_window = create_main_window(Viewer(), scene)

    main_window.actions["category_sketch"].trigger()
    widget = main_window.viewer_widget

    assert widget._active_workplane_host == (item_id, face_index)


def test_sketch_profile_context_promotes_profile_commands(qapp) -> None:
    require_ocp()

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.sketch import SKETCH_META_KIND, make_rectangle_profile
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    scene = Scene()
    profile_id = scene.add_shape(
        make_rectangle_profile(Workplane.world_xy()),
        meta={"kind": SKETCH_META_KIND, "profile": "rectangle"},
    )
    scene.set_selection(SelectionRef(profile_id, SelectionKind.FACE, 1))
    main_window = create_main_window(Viewer(), scene)
    main_window.viewer_widget._set_active_category("modify")
    actions = _command_action_names(main_window)

    assert "extrude" in actions
    assert "sketch_new_body" in actions
    assert "sketch_revolve" in actions
    assert "push_pull" not in main_window.viewer_widget.get_ui_state().context_actions


def test_hosted_sketch_profile_exposes_cut_and_subtracts_body(qapp) -> None:
    require_ocp()

    from cad_app.commands import top_planar_face_index
    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.picker import Picker
    from cad_app.scene import Scene
    from cad_app.sketch import SKETCH_META_KIND, make_center_rectangle_profile
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane
    from tests.helpers.topology import count_subshapes

    scene = Scene()
    shape = make_box(60.0, 50.0, 40.0)
    body_id = scene.add_shape(shape, meta={"kind": "body", "source": "primitive_box"})
    face_index = top_planar_face_index(shape)
    picker = Picker(scene)
    from OCP.TopoDS import TopoDS

    workplane = Workplane.from_face(
        TopoDS.Face_s(picker.subshape(body_id, SelectionKind.FACE, face_index))
    )
    profile_id = scene.add_shape(
        make_center_rectangle_profile(workplane, (0.0, 0.0), (8.0, 8.0)),
        meta={
            "kind": SKETCH_META_KIND,
            "profile": "center_rectangle",
            "host_item_id": body_id,
            "host_face_index": face_index,
        },
    )
    scene.set_selection(SelectionRef(profile_id, SelectionKind.FACE, 1))
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget
    widget._set_active_category("modify")

    assert "sketch_cut_mode" not in widget.get_ui_state().context_actions
    assert "extrude" in widget.get_ui_state().context_actions
    main_window.actions["extrude"].trigger()
    assert widget._move_session is not None
    assert not widget._tool_cut_mode_checkbox.isHidden()
    widget._tool_cut_mode_checkbox.setChecked(True)
    assert widget._move_session.operation == "cut"
    assert "subtract" in widget.get_ui_state().hint_text
    widget._tool_distance_input.setValue(16.0)
    widget._commit_move_session()

    assert profile_id not in scene
    assert body_id in scene
    assert scene.active_item_id() == body_id
    assert scene.get(body_id).meta["last_sketch_feature"] == "center_rectangle"
    assert count_subshapes(scene.get(body_id).shape, "face") > count_subshapes(
        shape,
        "face",
    )


def test_push_pull_keeps_signed_sketch_distance_and_cut_forces_negative(qapp) -> None:
    from cad_app.types import SelectionKind
    from cad_app.ui_sessions import MoveSession
    from cad_app.viewer_widget_move_preview import ViewerWidgetMovePreviewMixin

    session = MoveSession(
        tool="sketch_extrude",
        target_kind=SelectionKind.FACE,
        item_id="profile",
        index=1,
        axis_name="Normal",
        axis=(0.0, 0.0, 1.0),
        operation="auto",
        distance=-12.0,
    )

    assert ViewerWidgetMovePreviewMixin._sketch_extrude_session_distance(
        session
    ) == pytest.approx(-12.0)

    session.operation = "cut"
    session.distance = 12.0
    assert ViewerWidgetMovePreviewMixin._sketch_extrude_session_distance(
        session
    ) == pytest.approx(-12.0)


def test_push_pull_drag_fallback_maps_up_positive_and_down_negative(qapp) -> None:
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind
    from cad_app.ui_sessions import MoveSession
    from cad_app.viewer import Viewer

    widget = create_main_window(Viewer(), Scene()).viewer_widget
    widget._move_session = MoveSession(
        tool="sketch_extrude",
        target_kind=SelectionKind.FACE,
        item_id="profile",
        index=1,
        axis_name="Normal",
        axis=(0.0, 0.0, 1.0),
    )
    widget._update_move_preview = lambda: None
    widget._update_extrude_affordance = lambda: None
    widget._show_dimension_overlay = lambda *_args, **_kwargs: None

    widget._begin_move_drag(100, 100)
    widget._drag_move_to(100, 80)
    assert widget._move_session.distance > 0

    widget._move_session.distance = 0.0
    widget._begin_move_drag(100, 100)
    widget._drag_move_to(100, 120)
    assert widget._move_session.distance < 0


def test_view_gizmo_click_does_not_reset_active_push_pull_session(qapp) -> None:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind
    from cad_app.ui_sessions import MoveSession
    from cad_app.viewer import Viewer

    widget = create_main_window(Viewer(), Scene()).viewer_widget
    session = MoveSession(
        tool="sketch_extrude",
        target_kind=SelectionKind.FACE,
        item_id="profile",
        index=1,
        axis_name="Normal",
        axis=(0.0, 0.0, 1.0),
        operation="auto",
        distance=-7.0,
    )
    widget._move_session = session
    widget._update_move_preview = lambda: None
    widget._update_extrude_affordance = lambda: None
    widget._show_dimension_overlay = lambda *_args, **_kwargs: None

    left, top, _size = widget._orientation_gizmo_rect()
    point = QPoint(left + 78, top + 18)

    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, point)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, point)

    assert widget._move_session is session
    assert session.axis_name == "Normal"
    assert session.axis == (0.0, 0.0, 1.0)
    assert session.operation == "auto"
    assert session.distance == pytest.approx(-7.0)


def test_push_pull_face_accepts_signed_distance(qapp) -> None:
    require_ocp()

    import pytest

    from cad_app.commands import top_planar_face_index
    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.measurement import axis_aligned_box_dimensions
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    for distance, expected_height in ((10.0, 30.0), (-5.0, 15.0)):
        scene = Scene()
        shape = make_box(20.0, 20.0, 20.0)
        item_id = scene.add_shape(shape, meta={"kind": "body", "source": "box"})
        face_index = top_planar_face_index(shape)
        scene.set_selection(SelectionRef(item_id, SelectionKind.FACE, face_index))
        main_window = create_main_window(Viewer(), scene)
        widget = main_window.viewer_widget
        widget._set_active_category("modify")

        main_window.actions["extrude"].trigger()
        assert widget._move_session is not None
        assert widget.get_ui_state().context_actions == ("extrude", "cancel_tool")
        widget._move_session.distance = distance
        widget._commit_move_session()

        _width, _depth, height, _anchor = axis_aligned_box_dimensions(
            scene.get(item_id).shape
        )
        assert height == pytest.approx(expected_height)


def test_body_context_exposes_target_action_for_single_body(qapp) -> None:
    require_ocp()

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    scene = Scene()
    body_id = scene.add_shape(make_box(), meta={"kind": "body", "source": "box"})
    scene.set_selection(SelectionRef(body_id, SelectionKind.OBJECT, 0))
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget

    assert "set_boolean_target" in _command_action_names(main_window)
    main_window.actions["set_boolean_target"].trigger()

    assert widget._boolean_target_item_id == body_id
    assert "second body" in widget.get_ui_state().hint_text


def test_boolean_ready_context_hides_normal_body_actions(qapp) -> None:
    require_ocp()

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    scene = Scene()
    target_id = scene.add_shape(make_box(), meta={"kind": "body", "source": "target"})
    tool_id = scene.add_shape(make_box(), meta={"kind": "body", "source": "tool"})
    scene.set_selection(SelectionRef(target_id, SelectionKind.OBJECT, 0))
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget

    main_window.actions["set_boolean_target"].trigger()
    scene.set_selection(SelectionRef(tool_id, SelectionKind.OBJECT, 0))
    widget._set_active_category("boolean")
    state = widget.get_ui_state()

    assert state.command_mode == "boolean_target"
    assert state.boolean_target_item_id == target_id
    assert state.context_actions == (
        "boolean_union",
        "boolean_subtract",
        "boolean_intersect",
        "cancel_boolean",
    )
    assert "move" not in _command_action_names(main_window)
    assert "rotate_body" not in _command_action_names(main_window)
    assert not main_window.actions["move"].isEnabled()
    assert not main_window.actions["rotate_body"].isEnabled()


def test_body_rotate_uses_single_context_action_and_ring_gizmo(qapp) -> None:
    require_ocp()

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    scene = Scene()
    body_id = scene.add_shape(make_box(), meta={"kind": "body", "source": "box"})
    scene.set_selection(SelectionRef(body_id, SelectionKind.OBJECT, 0))
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget
    widget._set_active_category("transform")

    assert "rotate_body" in _command_action_names(main_window)
    assert "rotate_body_x" not in _command_action_names(main_window)
    assert "rotate_body_y" not in _command_action_names(main_window)
    assert "rotate_body_z" not in _command_action_names(main_window)

    main_window.actions["rotate_body"].trigger()
    state = widget.get_ui_state()

    assert state.active_tool == "rotate"
    assert state.command_mode == "active_tool"
    assert state.context_actions == ("rotate_body", "cancel_tool")
    assert state.manipulator_visible
    assert "rotate_body_x" not in _command_action_names(main_window)


def test_cylinder_planar_face_move_falls_back_to_normal_only(qapp) -> None:
    require_ocp()

    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder

    from cad_app.commands import top_planar_face_index
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    scene = Scene()
    shape = BRepPrimAPI_MakeCylinder(12.0, 36.0).Shape()
    body_id = scene.add_shape(shape, meta={"kind": "body", "source": "cylinder"})
    face_index = top_planar_face_index(shape)
    scene.set_selection(SelectionRef(body_id, SelectionKind.FACE, face_index))
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget
    widget._set_active_category("modify")

    assert "move" in _command_action_names(main_window)
    assert main_window.actions["move"].isEnabled()

    main_window.actions["move"].trigger()
    state = widget.get_ui_state()

    assert widget._move_session is not None
    assert widget._move_session.axis_name == "Normal"
    assert state.context_actions == ("move", "cancel_tool")
    assert state.manipulator_visible
    assert "normal" in state.hint_text.lower()


def test_new_project_clears_scene_and_returns_to_startup_sketch(qapp) -> None:
    require_ocp()

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    scene = Scene()
    body_id = scene.add_shape(make_box(), meta={"kind": "body", "source": "box"})
    scene.set_selection(SelectionRef(body_id, SelectionKind.OBJECT, 0))
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget
    main_window.actions["move"].trigger()
    assert widget._move_session is not None
    widget._boolean_target_item_id = body_id

    widget._new_project(confirm=False)
    state = widget.get_ui_state()

    assert len(scene) == 0
    assert not scene.can_undo()
    assert not scene.can_redo()
    assert widget._boolean_target_item_id is None
    assert widget._move_session is None
    assert widget._sketch_session is not None
    assert state.work_mode == "sketch"
    assert state.command_mode == "active_tool"
    assert state.active_tool.startswith("sketch:")


def test_active_transform_uses_tool_popover_without_viewport_dimension_duplicate(
    qapp,
) -> None:
    require_ocp()

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    scene = Scene()
    body_id = scene.add_shape(make_box(), meta={"kind": "body", "source": "box"})
    scene.set_selection(SelectionRef(body_id, SelectionKind.OBJECT, 0))
    main_window = create_main_window(Viewer(), scene)

    main_window.actions["move"].trigger()
    exported = main_window.export_ui_state()

    assert exported["state"]["active_tool"] == "move"
    assert exported["overlays"]["tool_popover"]["visible"]
    assert not exported["overlays"]["dimension_overlay"]["visible"]
    assert exported["state"]["overlay_text"].startswith("Move")


def test_body_and_sketch_position_can_be_set_absolutely(qapp) -> None:
    require_ocp()

    import pytest

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.sketch import SKETCH_META_KIND, make_center_rectangle_profile
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    scene = Scene()
    body_id = scene.add_shape(
        make_box(20.0, 20.0, 20.0),
        meta={"kind": "body", "source": "primitive_box"},
    )
    scene.set_selection(SelectionRef(body_id, SelectionKind.OBJECT, 0))
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget
    widget._set_active_category("select")

    assert "edit_position" not in widget.get_ui_state().context_actions
    widget._set_selected_position((40.0, 50.0, 60.0))
    assert widget._shape_center(scene.get(body_id).shape) == pytest.approx(
        (40.0, 50.0, 60.0)
    )

    profile_id = scene.add_shape(
        make_center_rectangle_profile(Workplane.world_xy(), (0.0, 0.0), (5.0, 5.0)),
        meta={
            "kind": SKETCH_META_KIND,
            "profile": "center_rectangle",
            "center_u": 0.0,
            "center_v": 0.0,
        },
    )
    scene.set_selection(SelectionRef(profile_id, SelectionKind.FACE, 1))
    widget._set_active_category("select")

    assert "edit_position" not in widget.get_ui_state().context_actions
    widget._set_selected_position((10.0, 15.0, 0.0))
    assert widget._shape_center(scene.get(profile_id).shape) == pytest.approx(
        (10.0, 15.0, 0.0)
    )
    assert scene.get(profile_id).meta["center_u"] == pytest.approx(10.0)
    assert scene.get(profile_id).meta["center_v"] == pytest.approx(15.0)


def test_revolve_tool_exposes_numeric_angle_and_elevation(qapp) -> None:
    require_ocp()

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.sketch import SKETCH_META_KIND, make_rectangle_profile
    from cad_app.types import OperationState, SelectionKind, SelectionRef
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    scene = Scene()
    profile_id = scene.add_shape(
        make_rectangle_profile(Workplane.world_xy()),
        meta={"kind": SKETCH_META_KIND, "profile": "rectangle"},
    )
    scene.set_selection(SelectionRef(profile_id, SelectionKind.FACE, 1))
    main_window = create_main_window(Viewer(), scene)

    main_window.actions["sketch_revolve"].trigger()
    widget = main_window.viewer_widget
    assert widget._move_session is not None
    assert widget.get_ui_state().active_operation == OperationState.COMMAND_PENDING

    widget._tool_distance_input.setValue(720.0)
    widget._tool_secondary_input.setValue(24.0)

    assert widget._move_session.distance == pytest.approx(720.0)
    assert widget._move_session.elevation == pytest.approx(24.0)
    assert "720.00 deg" in widget.get_ui_state().overlay_text
    assert "Elev 24.00 mm" in widget.get_ui_state().overlay_text


def test_ctrl_snap_uses_absolute_drag_dimensions(qapp) -> None:
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.ui_sessions import SketchSession
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    widget = create_main_window(Viewer(), Scene()).viewer_widget
    session = SketchSession(
        workplane=Workplane.world_xy(),
        label="test",
        host=None,
        tool="center_rectangle",
        start_uv=(2.3, 4.7),
    )

    snapped = widget._dimension_snapped_sketch_uv(session, (15.1, 11.2))
    width = abs(snapped[0] - session.start_uv[0]) * 2.0
    height = abs(snapped[1] - session.start_uv[1]) * 2.0

    assert width == pytest.approx(26.0)
    assert height == pytest.approx(13.0)
    assert snapped == (15.3, 11.2)


def test_selected_box_edge_can_be_measured_and_resized(qapp) -> None:
    require_ocp()

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.measurement import axis_aligned_box_dimensions, edge_measurement
    from cad_app.picker import Picker
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    scene = Scene()
    item_id = scene.add_shape(
        make_box(60.0, 50.0, 45.0),
        meta={"kind": "body", "source": "primitive_box"},
    )
    picker = Picker(scene)
    edge_index = None
    selected_measurement = None
    for index in range(1, picker.count_subshapes(item_id, SelectionKind.EDGE) + 1):
        measurement = edge_measurement(
            picker.subshape(item_id, SelectionKind.EDGE, index)
        )
        if measurement.axis_name == "Z":
            edge_index = index
            selected_measurement = measurement
            break
    assert edge_index is not None
    assert selected_measurement is not None

    selection = SelectionRef(item_id, SelectionKind.EDGE, edge_index)
    scene.set_selection(selection)
    widget = create_main_window(Viewer(), scene).viewer_widget

    assert widget._selected_edge_measurement().length == 45.0
    assert widget._selected_edge_length_editable()

    widget._edge_dimension_editor_selection = selection
    widget._edge_dimension_editor.setValue(80.0)
    widget._commit_edge_dimension_editor()

    width, depth, height, _anchor = axis_aligned_box_dimensions(
        scene.get(item_id).shape
    )
    assert width == pytest.approx(60.0)
    assert depth == pytest.approx(50.0)
    assert height == pytest.approx(80.0)
    assert scene.get(item_id).meta["height"] == 80.0


def test_edge_inline_editor_uses_down_right_offset(qapp, monkeypatch) -> None:
    require_ocp()

    from PySide6.QtCore import QPoint

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.measurement import edge_measurement
    from cad_app.picker import Picker
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    scene = Scene()
    item_id = scene.add_shape(
        make_box(60.0, 50.0, 45.0),
        meta={"kind": "body", "source": "primitive_box"},
    )
    picker = Picker(scene)
    edge_index = 1
    measurement = edge_measurement(
        picker.subshape(item_id, SelectionKind.EDGE, edge_index)
    )
    while measurement.axis_name is None:
        edge_index += 1
        measurement = edge_measurement(
            picker.subshape(item_id, SelectionKind.EDGE, edge_index)
        )
    selection = SelectionRef(item_id, SelectionKind.EDGE, edge_index)
    scene.set_selection(selection)
    widget = create_main_window(Viewer(), scene).viewer_widget
    widget.resize(500, 400)
    monkeypatch.setattr(widget._viewer, "is_initialized", True)
    monkeypatch.setattr(widget._viewer, "_view", _FakeView())

    widget._show_edge_dimension_editor(selection, measurement)

    assert not widget._edge_dimension_editor.isHidden()
    assert widget._inline_dimension_editor_specs["edge"]["offset"] == (28, 14)
    scale = widget.devicePixelRatioF() or 1.0
    expected_x = int(round(120 / scale)) + 28
    expected_y = int(round(160 / scale)) + 14
    max_x = max(0, widget.width() - widget._edge_dimension_editor.width() - 8)
    max_y = max(0, widget.height() - widget._edge_dimension_editor.height() - 8)
    assert widget._edge_dimension_editor.pos() == widget.mapToGlobal(
        QPoint(min(expected_x, max_x), min(expected_y, max_y))
    )
    widget._hide_inline_dimension_editors()


def test_box_inline_dimension_editors_update_body_dimensions(qapp, monkeypatch) -> None:
    require_ocp()

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.measurement import axis_aligned_box_dimensions
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    scene = Scene()
    item_id = scene.add_shape(
        make_box(60.0, 50.0, 45.0),
        meta={"kind": "body", "source": "primitive_box"},
    )
    selection = SelectionRef(item_id, SelectionKind.FACE, 1)
    scene.set_selection(selection)
    widget = create_main_window(Viewer(), scene).viewer_widget
    monkeypatch.setattr(widget._viewer, "is_initialized", True)
    monkeypatch.setattr(widget._viewer, "_view", _FakeView())
    monkeypatch.setattr(
        widget._viewer, "display_dimension_labels", lambda _labels: None
    )
    monkeypatch.setattr(widget._viewer, "display_scene", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        widget._viewer,
        "display_selection_marker",
        lambda *_args, **_kwargs: None,
    )

    widget._show_selected_box_dimensions()
    assert not widget._inline_dimension_editors["box_width"].isHidden()
    assert not widget._inline_dimension_editors["box_depth"].isHidden()
    assert not widget._inline_dimension_editors["box_height"].isHidden()

    widget._inline_dimension_editors["box_height"].setValue(90.0)
    widget._commit_inline_dimension_editor("box_height")

    _width, _depth, height, _anchor = axis_aligned_box_dimensions(
        scene.get(item_id).shape
    )
    assert height == pytest.approx(90.0)
    assert scene.get(item_id).meta["height"] == 90.0


def test_sketch_inline_dimension_editors_update_rectangle_and_circle(
    qapp,
    monkeypatch,
) -> None:
    require_ocp()

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.sketch import (
        SKETCH_META_KIND,
        make_center_rectangle_profile,
        make_circle_profile_at,
    )
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    workplane = Workplane.world_xy()
    frame_meta = {
        "workplane": "XY",
        "workplane_origin": (0.0, 0.0, 0.0),
        "workplane_x_direction": (1.0, 0.0, 0.0),
        "workplane_y_direction": (0.0, 1.0, 0.0),
        "center_u": 0.0,
        "center_v": 0.0,
    }
    scene = Scene()
    rectangle_id = scene.add_shape(
        make_center_rectangle_profile(workplane, (0.0, 0.0), (10.0, 5.0)),
        meta={
            "kind": SKETCH_META_KIND,
            "profile": "center_rectangle",
            "width": 20.0,
            "height": 10.0,
            **frame_meta,
        },
    )
    circle_id = scene.add_shape(
        make_circle_profile_at(workplane, (50.0, 0.0), 8.0),
        meta={
            "kind": SKETCH_META_KIND,
            "profile": "circle",
            "radius": 8.0,
            "center_u": 50.0,
            "center_v": 0.0,
            **{
                key: value
                for key, value in frame_meta.items()
                if key.startswith("workplane")
            },
        },
    )
    widget = create_main_window(Viewer(), scene).viewer_widget
    monkeypatch.setattr(widget._viewer, "is_initialized", True)
    monkeypatch.setattr(widget._viewer, "_view", _FakeView())
    monkeypatch.setattr(
        widget._viewer, "display_dimension_labels", lambda _labels: None
    )
    monkeypatch.setattr(widget._viewer, "display_scene", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        widget._viewer,
        "display_selection_marker",
        lambda *_args, **_kwargs: None,
    )

    scene.set_selection(SelectionRef(rectangle_id, SelectionKind.FACE, 1))
    widget._show_selected_sketch_dimensions()
    assert not widget._inline_dimension_editors["sketch_width"].isHidden()
    assert not widget._inline_dimension_editors["sketch_height"].isHidden()
    widget._inline_dimension_editors["sketch_width"].setValue(44.0)
    widget._commit_inline_dimension_editor("sketch_width")
    assert scene.get(rectangle_id).meta["width"] == pytest.approx(44.0)

    scene.set_selection(SelectionRef(circle_id, SelectionKind.FACE, 1))
    widget._show_selected_sketch_dimensions()
    assert not widget._inline_dimension_editors["sketch_radius"].isHidden()
    widget._inline_dimension_editors["sketch_radius"].setValue(14.0)
    widget._commit_inline_dimension_editor("sketch_radius")
    assert scene.get(circle_id).meta["radius"] == pytest.approx(14.0)


def test_nonparametric_face_hides_inline_dimension_editors(qapp, monkeypatch) -> None:
    require_ocp()

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    scene = Scene()
    item_id = scene.add_shape(
        make_box(60.0, 50.0, 45.0),
        meta={"kind": "body", "source": "imported"},
    )
    scene.set_selection(SelectionRef(item_id, SelectionKind.FACE, 1))
    widget = create_main_window(Viewer(), scene).viewer_widget
    monkeypatch.setattr(widget._viewer, "is_initialized", True)
    monkeypatch.setattr(widget._viewer, "_view", _FakeView())

    widget._show_selected_box_dimensions()

    assert all(
        editor.isHidden() for editor in widget._inline_dimension_editors.values()
    )


def test_sketch_extruded_box_dimensions_are_editable_from_face(qapp) -> None:
    require_ocp()

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.measurement import axis_aligned_box_dimensions
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    scene = Scene()
    item_id = scene.add_shape(
        make_box(60.0, 40.0, 25.0),
        meta={
            "kind": "body",
            "source": "sketch_new_body",
            "profile": "center_rectangle",
        },
    )
    selection = SelectionRef(item_id, SelectionKind.FACE, 1)
    scene.set_selection(selection)
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget
    widget._set_active_category("modify")

    assert widget._box_dimensions_editable(item_id)
    assert "edit_box_dimensions" not in _command_action_names(main_window)
    assert main_window.actions["edit_box_dimensions"].isEnabled()

    widget._resize_box_dimensions(item_id, 90.0, 55.0, 35.0, selection)

    width, depth, height, _anchor = axis_aligned_box_dimensions(
        scene.get(item_id).shape
    )
    assert width == pytest.approx(90.0)
    assert depth == pytest.approx(55.0)
    assert height == pytest.approx(35.0)
    assert scene.get(item_id).meta["width"] == 90.0
    assert scene.get(item_id).meta["depth"] == 55.0
    assert scene.get(item_id).meta["height"] == 35.0
    assert scene.selection() == selection
