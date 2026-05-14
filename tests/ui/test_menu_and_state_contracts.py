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


def test_category_rail_and_initial_context(qapp) -> None:
    from PySide6.QtWidgets import QToolBar

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.ui_menu import CATEGORY_RAIL_ACTIONS
    from cad_app.viewer import Viewer

    main_window = create_main_window(Viewer(), Scene())
    category_toolbar = main_window.window.findChild(QToolBar, "left_menu")

    assert list(main_window.actions) != []
    assert category_toolbar is not None
    rail_actions = [
        action.objectName()
        for action in category_toolbar.actions()
        if action.objectName().startswith("category_")
    ]
    assert rail_actions == list(CATEGORY_RAIL_ACTIONS)
    assert "category_create" not in rail_actions
    assert "category_file" not in rail_actions
    assert _command_action_names(main_window) == ["start_sketch"]
    assert main_window.viewer_widget.get_ui_state().work_mode == "sketch"


def test_start_sketch_uses_bottom_plane_without_host(qapp) -> None:
    require_ocp()

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.viewer import Viewer

    main_window = create_main_window(Viewer(), Scene())
    main_window.actions["category_sketch"].trigger()
    main_window.actions["start_sketch"].trigger()
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

    main_window.actions["start_sketch"].trigger()
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

    assert "push_pull" in actions
    assert "sketch_new_body" in actions
    assert "sketch_revolve" in actions
    assert "extrude" not in main_window.viewer_widget.get_ui_state().context_actions


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
    assert "push_pull" in widget.get_ui_state().context_actions
    main_window.actions["push_pull"].trigger()
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

        main_window.actions["push_pull"].trigger()
        assert widget._move_session is not None
        assert widget.get_ui_state().context_actions == ("push_pull", "cancel_tool")
        widget._move_session.distance = distance
        widget._commit_move_session()

        _width, _depth, height, _anchor = axis_aligned_box_dimensions(
            scene.get(item_id).shape
        )
        assert height == pytest.approx(expected_height)


def test_boolean_category_exposes_target_action_for_single_body(qapp) -> None:
    require_ocp()

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.viewer import Viewer

    scene = Scene()
    body_id = scene.add_shape(make_box(), meta={"kind": "body", "source": "box"})
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget
    widget._set_active_category("boolean")

    assert _command_action_names(main_window) == ["set_boolean_target"]
    main_window.actions["set_boolean_target"].trigger()

    assert widget._boolean_target_item_id == body_id
    assert "second body" in widget.get_ui_state().hint_text


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
    widget._set_active_category("transform")

    assert "edit_position" in widget.get_ui_state().context_actions
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
    widget._set_active_category("modify")

    assert "edit_position" in widget.get_ui_state().context_actions
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

    main_window.actions["sketch_revolve_x"].trigger()
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
    assert "edit_box_dimensions" in _command_action_names(main_window)
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
