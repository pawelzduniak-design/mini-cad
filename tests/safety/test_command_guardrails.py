from __future__ import annotations

from tests.conftest import require_ocp
from tests.helpers.topology import scene_fingerprint


def test_face_selection_does_not_enable_whole_body_delete(qapp) -> None:
    require_ocp()

    from cad_app.commands import top_planar_face_index
    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    scene = Scene()
    shape = make_box()
    item_id = scene.add_shape(shape, meta={"kind": "body"})
    scene.set_selection(
        SelectionRef(item_id, SelectionKind.FACE, top_planar_face_index(shape))
    )
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget
    widget._set_active_category("modify")
    state = widget.get_ui_state()

    assert state.selection_type == "face"
    assert "push_pull" in state.context_actions
    assert "start_sketch" in state.context_actions
    assert "delete_object" not in state.context_actions
    assert not main_window.actions["delete_object"].isEnabled()
    assert main_window.actions["start_sketch"].text() == "New Sketch (Face Plane)"


def test_sketch_object_selection_does_not_enable_body_transform(qapp) -> None:
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.sketch import SKETCH_META_KIND
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    scene = Scene()
    profile_id = scene.add_shape(
        "profile-shape",
        meta={"kind": SKETCH_META_KIND, "profile": "rectangle"},
    )
    scene.set_selection(SelectionRef(profile_id, SelectionKind.OBJECT, 0))
    main_window = create_main_window(Viewer(), scene)
    main_window.viewer_widget._set_active_category("transform")

    assert not main_window.actions["move_object"].isEnabled()
    assert not main_window.actions["rotate_body"].isEnabled()
    assert "move_object" not in main_window.viewer_widget.get_ui_state().context_actions


def test_category_clicks_do_not_mutate_scene(qapp) -> None:
    require_ocp()

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.viewer import Viewer

    scene = Scene()
    scene.add_shape(make_box(), meta={"kind": "body"})
    main_window = create_main_window(Viewer(), scene)
    before = scene_fingerprint(scene)

    for action_name in (
        "category_select",
        "category_create",
        "category_modify",
        "category_sketch",
        "category_boolean",
        "category_transform",
        "category_measure",
        "category_view",
        "category_file",
    ):
        main_window.actions[action_name].trigger()
        assert scene_fingerprint(scene) == before, action_name


def test_view_display_actions_do_not_mutate_scene(qapp) -> None:
    require_ocp()

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.viewer import Viewer

    scene = Scene()
    scene.add_shape(make_box(), meta={"kind": "body"})
    main_window = create_main_window(Viewer(), scene)
    before = scene_fingerprint(scene)

    main_window.actions["display_wireframe"].trigger()
    main_window.actions["display_shaded"].trigger()

    assert scene_fingerprint(scene) == before


def test_modeling_command_can_run_before_window_is_shown(qapp) -> None:
    require_ocp()

    from cad_app.commands import top_planar_face_index
    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    scene = Scene()
    shape = make_box(40.0, 30.0, 20.0)
    item_id = scene.add_shape(shape, meta={"kind": "body"})
    scene.set_selection(
        SelectionRef(item_id, SelectionKind.FACE, top_planar_face_index(shape))
    )
    main_window = create_main_window(Viewer(), scene)

    main_window.viewer_widget._extrude_active_top_face(5.0)

    assert item_id in scene
    assert main_window.viewer_widget._last_status_text == "Extrude applied"
