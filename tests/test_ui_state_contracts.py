from importlib.util import find_spec

import pytest

from cad_app.types import OperationState, SelectionKind, SelectionRef


def _skip_without_gui_dependencies() -> None:
    if find_spec("OCP") is None or find_spec("PySide6") is None:
        pytest.skip("OCP/PySide6 are not installed in the active environment.")


def test_face_context_actions_offer_sketch_and_not_delete_object() -> None:
    _skip_without_gui_dependencies()

    from PySide6.QtWidgets import QApplication

    from cad_app.commands import top_planar_face_index
    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.viewer import Viewer

    QApplication.instance() or QApplication([])
    scene = Scene()
    shape = make_box(60.0, 40.0, 20.0)
    item_id = scene.add_shape(shape, meta={"kind": "body"})
    scene.set_selection(
        SelectionRef(
            item_id=item_id,
            kind=SelectionKind.FACE,
            index=top_planar_face_index(shape),
        )
    )
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget
    widget._active_category = "modify"
    widget._refresh_action_state()

    state = widget.get_ui_state()

    assert state.selection_type == "face"
    assert "start_sketch" in state.context_actions
    assert "delete_object" not in state.context_actions
    assert main_window.actions["start_sketch"].text() == "Sketch on Face"


def test_delete_object_ui_command_is_blocked_for_face_selection() -> None:
    _skip_without_gui_dependencies()

    from PySide6.QtWidgets import QApplication

    from cad_app.commands import top_planar_face_index
    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.viewer import Viewer

    QApplication.instance() or QApplication([])
    scene = Scene()
    shape = make_box(60.0, 40.0, 20.0)
    item_id = scene.add_shape(shape, meta={"kind": "body"})
    scene.set_selection(
        SelectionRef(
            item_id=item_id,
            kind=SelectionKind.FACE,
            index=top_planar_face_index(shape),
        )
    )
    main_window = create_main_window(Viewer(), scene)

    main_window.viewer_widget._delete_active_object()

    assert item_id in scene
    assert len(scene) == 1
    assert main_window.viewer_widget.get_ui_state().status_text == (
        "Select an object to delete"
    )


def test_ui_state_reports_active_extrude_as_not_idle() -> None:
    _skip_without_gui_dependencies()

    from PySide6.QtWidgets import QApplication

    from cad_app.commands import top_planar_face_index
    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.viewer import Viewer

    QApplication.instance() or QApplication([])
    scene = Scene()
    shape = make_box(60.0, 40.0, 20.0)
    item_id = scene.add_shape(shape, meta={"kind": "body"})
    scene.set_selection(
        SelectionRef(
            item_id=item_id,
            kind=SelectionKind.FACE,
            index=top_planar_face_index(shape),
        )
    )
    main_window = create_main_window(Viewer(), scene)

    main_window.viewer_widget._begin_extrude_tool()
    state = main_window.viewer_widget.get_ui_state()

    assert state.active_tool == "extrude"
    assert state.active_operation == OperationState.PREVIEWING_EXTRUDE
    assert state.overlay_visible
    assert state.manipulator_visible
    assert "Enter" in state.hint_text
