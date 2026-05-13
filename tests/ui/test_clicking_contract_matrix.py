from __future__ import annotations

from tests.conftest import require_ocp


def _command_action_names(main_window) -> tuple[str, ...]:
    return tuple(
        action.objectName()
        for action in main_window.viewer_widget._command_toolbar.actions()
        if action.objectName() and not action.objectName().startswith("context_label_")
    )


def _assert_command_surface_matches_state(main_window) -> None:
    state = main_window.viewer_widget.get_ui_state()
    command_actions = tuple(
        action
        for action in main_window.viewer_widget._command_toolbar.actions()
        if action.objectName() and not action.objectName().startswith("context_label_")
    )

    assert tuple(action.objectName() for action in command_actions) == (
        state.context_actions
    )
    for action in command_actions:
        assert action.isEnabled(), action.objectName()


def _select_topology(widget, scene, item_id, kind, index, category: str):
    from cad_app.types import SelectionRef

    scene.set_selection(SelectionRef(item_id, kind, index))
    widget._selection_kind = kind
    widget._set_active_category(category)
    return widget.get_ui_state()


def test_clicking_contract_body_topology_context_matrix(qapp) -> None:
    require_ocp()

    from cad_app.commands import top_planar_face_index
    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind
    from cad_app.ui_menu import (
        BODY_ACTIONS,
        EDGE_MODIFY_ACTIONS,
        FACE_MODIFY_ACTIONS,
        VERTEX_MODIFY_ACTIONS,
    )
    from cad_app.viewer import Viewer

    scene = Scene()
    shape = make_box()
    item_id = scene.add_shape(
        shape,
        meta={"kind": "body", "source": "primitive_box"},
    )
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget

    state = _select_topology(
        widget,
        scene,
        item_id,
        SelectionKind.OBJECT,
        0,
        "transform",
    )
    assert state.selection_type == "object"
    assert _command_action_names(main_window) == BODY_ACTIONS
    assert state.context_actions == BODY_ACTIONS
    _assert_command_surface_matches_state(main_window)

    state = _select_topology(
        widget,
        scene,
        item_id,
        SelectionKind.FACE,
        top_planar_face_index(shape),
        "modify",
    )
    assert state.selection_type == "face"
    assert _command_action_names(main_window) == tuple(
        action_name
        for action_name in FACE_MODIFY_ACTIONS
        if action_name != "offset_face"
    )
    assert "offset_face" not in state.context_actions
    assert main_window.actions["start_sketch"].text() == "New Sketch (Face Plane)"
    assert main_window.actions["move_selection"].text() == "Move Face"
    _assert_command_surface_matches_state(main_window)

    state = _select_topology(
        widget,
        scene,
        item_id,
        SelectionKind.EDGE,
        1,
        "modify",
    )
    assert state.selection_type == "edge"
    assert _command_action_names(main_window) == EDGE_MODIFY_ACTIONS
    assert state.context_actions == EDGE_MODIFY_ACTIONS
    assert main_window.actions["move_selection"].text() == "Move Edge"
    _assert_command_surface_matches_state(main_window)

    state = _select_topology(
        widget,
        scene,
        item_id,
        SelectionKind.VERTEX,
        1,
        "modify",
    )
    assert state.selection_type == "vertex"
    assert _command_action_names(main_window) == VERTEX_MODIFY_ACTIONS
    assert state.context_actions == VERTEX_MODIFY_ACTIONS
    assert main_window.actions["move_selection"].text() == "Move Vertex"
    _assert_command_surface_matches_state(main_window)


def test_clicking_contract_sketch_profile_context_matrix(qapp) -> None:
    require_ocp()

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.sketch import SKETCH_META_KIND, make_rectangle_profile
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.ui_menu import PROFILE_ACTIONS
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    scene = Scene()
    profile_id = scene.add_shape(
        make_rectangle_profile(Workplane.world_xy()),
        meta={
            "kind": SKETCH_META_KIND,
            "profile": "rectangle",
            "width": 20.0,
            "height": 10.0,
        },
    )
    scene.set_selection(SelectionRef(profile_id, SelectionKind.FACE, 1))
    main_window = create_main_window(Viewer(), scene)
    main_window.viewer_widget._set_active_category("modify")
    state = main_window.viewer_widget.get_ui_state()

    assert state.selection_type == "sketch_profile"
    assert _command_action_names(main_window) == PROFILE_ACTIONS
    assert state.context_actions == PROFILE_ACTIONS
    assert "extrude" not in state.context_actions
    assert not main_window.actions["extrude"].isEnabled()
    assert not main_window.actions["export_step"].isEnabled()
    _assert_command_surface_matches_state(main_window)


def test_selected_sketch_profile_can_reenter_edit_session(qapp) -> None:
    require_ocp()

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.sketch import SKETCH_META_KIND, make_rectangle_profile
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    workplane = Workplane.world_xy()
    scene = Scene()
    profile_id = scene.add_shape(
        make_rectangle_profile(workplane),
        meta={
            "kind": SKETCH_META_KIND,
            "profile": "rectangle",
            "workplane": "XY",
            "workplane_origin": (0.0, 0.0, 0.0),
            "workplane_x_direction": (1.0, 0.0, 0.0),
            "workplane_y_direction": (0.0, 1.0, 0.0),
        },
    )
    scene.set_selection(SelectionRef(profile_id, SelectionKind.FACE, 1))
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget
    widget._set_active_category("modify")

    main_window.actions["edit_sketch"].trigger()

    assert widget._sketch_session is not None
    assert profile_id in widget._sketch_session.profile_ids
    assert widget.get_ui_state().work_mode == "sketch"
    assert widget.get_ui_state().active_tool.startswith("sketch:")


def test_edit_sketch_is_scoped_to_selected_sketch_id(qapp) -> None:
    require_ocp()

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.sketch import SKETCH_META_KIND, make_rectangle_profile_from_corners
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    workplane = Workplane.world_xy()
    frame_meta = {
        "workplane": "XY",
        "workplane_origin": (0.0, 0.0, 0.0),
        "workplane_x_direction": (1.0, 0.0, 0.0),
        "workplane_y_direction": (0.0, 1.0, 0.0),
    }
    scene = Scene()
    first_id = scene.add_shape(
        make_rectangle_profile_from_corners(
            workplane,
            (-10.0, -10.0),
            (10.0, 10.0),
        ),
        meta={
            "kind": SKETCH_META_KIND,
            "profile": "rectangle",
            "sketch_id": "sketch-a",
            **frame_meta,
        },
    )
    second_id = scene.add_shape(
        make_rectangle_profile_from_corners(
            workplane,
            (100.0, 100.0),
            (120.0, 120.0),
        ),
        meta={
            "kind": SKETCH_META_KIND,
            "profile": "rectangle",
            "sketch_id": "sketch-b",
            **frame_meta,
        },
    )
    scene.set_selection(SelectionRef(first_id, SelectionKind.FACE, 1))
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget
    widget._set_active_category("modify")

    main_window.actions["edit_sketch"].trigger()

    assert widget._sketch_session is not None
    assert widget._sketch_session.sketch_id == "sketch-a"
    assert first_id in widget._sketch_session.profile_ids
    assert second_id not in widget._sketch_session.profile_ids


def test_circular_edge_context_exposes_thread_action(qapp) -> None:
    require_ocp()

    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder

    from cad_app.commands import CommandError, circular_edge_parameters
    from cad_app.main_window import create_main_window
    from cad_app.picker import Picker
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    scene = Scene()
    shape = BRepPrimAPI_MakeCylinder(10.0, 30.0).Shape()
    item_id = scene.add_shape(shape, meta={"kind": "body", "source": "cylinder"})
    picker = Picker(scene)
    edge_index = None
    for index in range(1, picker.count_subshapes(item_id, SelectionKind.EDGE) + 1):
        try:
            circular_edge_parameters(shape, index)
        except (CommandError, IndexError, RuntimeError, ValueError):
            continue
        edge_index = index
        break
    assert edge_index is not None

    scene.set_selection(SelectionRef(item_id, SelectionKind.EDGE, edge_index))
    main_window = create_main_window(Viewer(), scene)
    main_window.viewer_widget._selection_kind = SelectionKind.EDGE
    main_window.viewer_widget._set_active_category("modify")
    state = main_window.viewer_widget.get_ui_state()

    assert "thread" in state.context_actions
    assert "thread" in _command_action_names(main_window)
    _assert_command_surface_matches_state(main_window)


def test_clicking_contract_multi_selection_context_matrix(qapp) -> None:
    require_ocp()

    from cad_app.commands import translated_shape
    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.sketch import (
        SKETCH_META_KIND,
        make_circle_profile,
        make_rectangle_profile,
    )
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.ui_menu import MULTI_BODY_ACTIONS, MULTI_PROFILE_ACTIONS
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    scene = Scene()
    first_id = scene.add_shape(make_box(), meta={"kind": "body", "source": "first"})
    second_id = scene.add_shape(
        translated_shape(make_box(), 140.0, 0.0, 0.0),
        meta={"kind": "body", "source": "second"},
    )
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget
    scene.set_selections(
        (
            SelectionRef(first_id, SelectionKind.OBJECT, 0),
            SelectionRef(second_id, SelectionKind.OBJECT, 0),
        )
    )
    widget._selection_kind = SelectionKind.OBJECT
    widget._set_active_category("transform")
    state = widget.get_ui_state()

    assert state.selection_type == "multi_object"
    assert state.context_actions == MULTI_BODY_ACTIONS
    assert _command_action_names(main_window) == MULTI_BODY_ACTIONS
    _assert_command_surface_matches_state(main_window)

    for refs, expected_type in (
        (
            (
                SelectionRef(first_id, SelectionKind.FACE, 1),
                SelectionRef(first_id, SelectionKind.FACE, 2),
            ),
            "multi_face",
        ),
        (
            (
                SelectionRef(first_id, SelectionKind.EDGE, 1),
                SelectionRef(first_id, SelectionKind.EDGE, 2),
            ),
            "multi_edge",
        ),
        (
            (
                SelectionRef(first_id, SelectionKind.VERTEX, 1),
                SelectionRef(first_id, SelectionKind.VERTEX, 2),
            ),
            "multi_vertex",
        ),
        (
            (
                SelectionRef(first_id, SelectionKind.OBJECT, 0),
                SelectionRef(first_id, SelectionKind.FACE, 1),
            ),
            "multi",
        ),
    ):
        scene.set_selections(refs)
        widget._selection_kind = refs[0].kind
        widget._set_active_category("modify")
        state = widget.get_ui_state()

        assert state.selection_type == expected_type
        assert state.context_actions == ()
        assert _command_action_names(main_window) == ()
        _assert_command_surface_matches_state(main_window)

    profile_scene = Scene()
    workplane = Workplane.world_xy()
    rectangle_id = profile_scene.add_shape(
        make_rectangle_profile(workplane),
        meta={"kind": SKETCH_META_KIND, "profile": "rectangle"},
    )
    circle_id = profile_scene.add_shape(
        make_circle_profile(workplane),
        meta={"kind": SKETCH_META_KIND, "profile": "circle"},
    )
    profile_window = create_main_window(Viewer(), profile_scene)
    profile_widget = profile_window.viewer_widget
    profile_scene.set_selections(
        (
            SelectionRef(rectangle_id, SelectionKind.FACE, 1),
            SelectionRef(circle_id, SelectionKind.FACE, 1),
        )
    )
    profile_widget._selection_kind = SelectionKind.FACE
    profile_widget._set_active_category("modify")
    profile_state = profile_widget.get_ui_state()

    assert profile_state.selection_type == "multi_sketch_profile"
    assert profile_state.context_actions == MULTI_PROFILE_ACTIONS
    assert _command_action_names(profile_window) == MULTI_PROFILE_ACTIONS
    _assert_command_surface_matches_state(profile_window)


def test_multi_body_move_applies_to_all_selected_bodies(qapp) -> None:
    require_ocp()

    import pytest

    from cad_app.commands import translated_shape
    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer
    from tests.helpers.topology import bounding_box

    scene = Scene()
    first_id = scene.add_shape(make_box(), meta={"kind": "body", "source": "first"})
    second_id = scene.add_shape(
        translated_shape(make_box(), 140.0, 0.0, 0.0),
        meta={"kind": "body", "source": "second"},
    )
    first_before = bounding_box(scene.get(first_id).shape)
    second_before = bounding_box(scene.get(second_id).shape)
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget
    scene.set_selections(
        (
            SelectionRef(first_id, SelectionKind.OBJECT, 0),
            SelectionRef(second_id, SelectionKind.OBJECT, 0),
        )
    )
    widget._selection_kind = SelectionKind.OBJECT
    widget._set_active_category("transform")

    main_window.actions["move_object_x"].trigger()
    assert widget._move_session is not None
    assert widget._move_session.item_ids == (first_id, second_id)
    widget._move_session.distance = 12.0
    widget._commit_move_session()

    assert bounding_box(scene.get(first_id).shape)["xmin"] == pytest.approx(
        first_before["xmin"] + 12.0
    )
    assert bounding_box(scene.get(second_id).shape)["xmin"] == pytest.approx(
        second_before["xmin"] + 12.0
    )


def test_move_properties_report_transform_operation(qapp) -> None:
    require_ocp()

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    scene = Scene()
    item_id = scene.add_shape(make_box(), meta={"kind": "body", "source": "box"})
    scene.set_selection(SelectionRef(item_id, SelectionKind.OBJECT, 0))
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget
    widget._set_active_category("transform")

    main_window.actions["move_object_x"].trigger()
    properties = widget._browser_lists["properties"]
    texts = [properties.item(index).text() for index in range(properties.count())]

    assert "Operation: Transform" in texts
    assert "Operation: New Body" not in texts


def test_sketch_move_translates_profile_and_dimension_metadata(qapp) -> None:
    require_ocp()

    import pytest

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.sketch import SKETCH_META_KIND, make_center_rectangle_profile
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane
    from tests.helpers.topology import bounding_box

    workplane = Workplane.world_xy()
    scene = Scene()
    profile_id = scene.add_shape(
        make_center_rectangle_profile(workplane, (3.0, 4.0), (13.0, 14.0)),
        meta={
            "kind": SKETCH_META_KIND,
            "profile": "center_rectangle",
            "width": 20.0,
            "height": 20.0,
            "center_u": 3.0,
            "center_v": 4.0,
            "workplane": "XY",
            "workplane_origin": (0.0, 0.0, 0.0),
            "workplane_x_direction": (1.0, 0.0, 0.0),
            "workplane_y_direction": (0.0, 1.0, 0.0),
        },
    )
    before = bounding_box(scene.get(profile_id).shape)
    scene.set_selection(SelectionRef(profile_id, SelectionKind.FACE, 1))
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget
    widget._set_active_category("modify")

    main_window.actions["move_sketch_x"].trigger()
    assert widget._move_session is not None
    assert widget._move_session.tool == "sketch_move"
    assert widget._move_session.item_ids == (profile_id,)

    widget._move_session.distance = 12.0
    widget._commit_move_session()

    after = bounding_box(scene.get(profile_id).shape)
    meta = scene.get(profile_id).meta
    assert after["xmin"] == pytest.approx(before["xmin"] + 12.0)
    assert meta["center_u"] == pytest.approx(15.0)
    assert meta["center_v"] == pytest.approx(4.0)
    assert meta["workplane_origin"] == pytest.approx((0.0, 0.0, 0.0))


def test_delete_sketch_removes_selected_profile(qapp) -> None:
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

    main_window.actions["delete_sketch"].trigger()

    assert profile_id not in scene
    assert main_window.viewer_widget.get_ui_state().selection_type == "none"


def test_multi_sketch_profile_extrude_applies_to_all_selected_profiles(qapp) -> None:
    require_ocp()

    import pytest

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.sketch import (
        SKETCH_META_KIND,
        make_circle_profile_at,
        make_rectangle_profile_from_corners,
    )
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane
    from tests.helpers.topology import bounding_box

    scene = Scene()
    workplane = Workplane.world_xy()
    rectangle_id = scene.add_shape(
        make_rectangle_profile_from_corners(workplane, (-35.0, -15.0), (-5.0, 15.0)),
        meta={"kind": SKETCH_META_KIND, "profile": "rectangle"},
    )
    circle_id = scene.add_shape(
        make_circle_profile_at(workplane, (25.0, 0.0), 12.0),
        meta={"kind": SKETCH_META_KIND, "profile": "circle"},
    )
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget
    scene.set_selections(
        (
            SelectionRef(rectangle_id, SelectionKind.FACE, 1),
            SelectionRef(circle_id, SelectionKind.FACE, 1),
        )
    )
    widget._selection_kind = SelectionKind.FACE
    widget._set_active_category("modify")

    main_window.actions["sketch_extrude"].trigger()
    assert widget._move_session is not None
    assert widget._move_session.item_ids == (rectangle_id, circle_id)
    widget._move_session.distance = 18.0
    widget._commit_move_session()

    assert scene.get(rectangle_id).meta["kind"] == "body"
    assert scene.get(circle_id).meta["kind"] == "body"
    assert bounding_box(scene.get(rectangle_id).shape)["height"] == pytest.approx(18.0)
    assert bounding_box(scene.get(circle_id).shape)["height"] == pytest.approx(18.0)


def test_sketch_category_requires_explicit_new_sketch_before_draw_tools(qapp) -> None:
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.ui_menu import SKETCH_ACTIVE_ACTIONS, SKETCH_DRAW_ACTIONS
    from cad_app.viewer import Viewer

    main_window = create_main_window(Viewer(), Scene())
    widget = main_window.viewer_widget

    main_window.actions["category_sketch"].trigger()
    state = widget.get_ui_state()

    assert _command_action_names(main_window) == ("start_sketch",)
    assert state.context_actions == ("start_sketch",)
    _assert_command_surface_matches_state(main_window)
    for action_name in SKETCH_DRAW_ACTIONS:
        assert not main_window.actions[action_name].isEnabled(), action_name

    main_window.actions["sketch_line_tool"].trigger()
    assert widget._sketch_session is None
    assert _command_action_names(main_window) == ("start_sketch",)
    _assert_command_surface_matches_state(main_window)

    main_window.actions["start_sketch"].trigger()
    state = widget.get_ui_state()

    assert widget._sketch_session is not None
    assert _command_action_names(main_window) == SKETCH_ACTIVE_ACTIONS
    assert state.context_actions == SKETCH_ACTIVE_ACTIONS
    _assert_command_surface_matches_state(main_window)


def test_command_surface_hides_unavailable_actions_across_common_states(qapp) -> None:
    require_ocp()

    from cad_app.commands import top_planar_face_index
    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    empty_window = create_main_window(Viewer(), Scene())
    for category_action in (
        "category_select",
        "category_create",
        "category_modify",
        "category_sketch",
        "category_boolean",
        "category_measure",
        "category_view",
        "category_file",
    ):
        empty_window.actions[category_action].trigger()
        _assert_command_surface_matches_state(empty_window)

    scene = Scene()
    first_shape = make_box()
    second_shape = make_box()
    first_id = scene.add_shape(first_shape, meta={"kind": "body", "source": "first"})
    second_id = scene.add_shape(second_shape, meta={"kind": "body", "source": "second"})
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget

    for kind, index, category in (
        (SelectionKind.OBJECT, 0, "transform"),
        (SelectionKind.FACE, top_planar_face_index(first_shape), "modify"),
        (SelectionKind.EDGE, 1, "modify"),
        (SelectionKind.VERTEX, 1, "modify"),
    ):
        scene.set_selection(SelectionRef(first_id, kind, index))
        widget._selection_kind = kind
        widget._set_active_category(category)
        _assert_command_surface_matches_state(main_window)

    scene.set_selection(SelectionRef(first_id, SelectionKind.OBJECT, 0))
    widget._set_active_category("boolean")
    _assert_command_surface_matches_state(main_window)
    assert _command_action_names(main_window) == ("set_boolean_target",)

    main_window.actions["set_boolean_target"].trigger()
    scene.set_selection(SelectionRef(second_id, SelectionKind.OBJECT, 0))
    widget._set_active_category("boolean")
    _assert_command_surface_matches_state(main_window)
    assert _command_action_names(main_window) == (
        "set_boolean_target",
        "clear_boolean_target",
        "boolean_union",
        "boolean_subtract",
        "boolean_intersect",
    )
