from __future__ import annotations

import pytest

from tests.conftest import require_ocp


def _command_action_names(main_window) -> list[str]:
    return [
        action.objectName()
        for action in main_window.viewer_widget._command_toolbar.actions()
        if action.objectName() and not action.objectName().startswith("context_label_")
    ]


def test_category_rail_and_initial_context(qapp) -> None:
    from PySide6.QtWidgets import QToolBar

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.ui_menu import CATEGORY_RAIL_ACTIONS, SELECT_ACTIONS
    from cad_app.viewer import Viewer

    main_window = create_main_window(Viewer(), Scene())
    category_toolbar = main_window.window.findChild(QToolBar, "CategoryToolbar")

    assert list(main_window.actions) != []
    assert category_toolbar is not None
    rail_actions = [
        action.objectName()
        for action in category_toolbar.actions()
        if action.objectName().startswith("category_")
    ]
    assert rail_actions == list(CATEGORY_RAIL_ACTIONS)
    assert "category_create" not in rail_actions
    assert _command_action_names(main_window) == list(SELECT_ACTIONS)
    assert main_window.viewer_widget.get_ui_state().work_mode == "select"


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

    assert "sketch_extrude" in actions
    assert "sketch_new_body" in actions
    assert "sketch_revolve" in actions
    assert "extrude" not in main_window.viewer_widget.get_ui_state().context_actions


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
