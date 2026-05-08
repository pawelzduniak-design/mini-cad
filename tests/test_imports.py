import pytest

import cad_app
from cad_app import (
    app,
    commands,
    config,
    engine,
    env,
    io_step,
    main_window,
    navigation,
    picker,
    profiles,
    scene,
    sketch,
    types,
    viewer,
    workplane,
)


def test_imports() -> None:
    assert cad_app is not None
    assert app is not None
    assert commands is not None
    assert config is not None
    assert engine is not None
    assert env is not None
    assert io_step is not None
    assert main_window is not None
    assert navigation is not None
    assert picker is not None
    assert profiles is not None
    assert scene is not None
    assert sketch is not None
    assert types is not None
    assert viewer is not None
    assert workplane is not None


def test_initial_scene_starts_empty_for_sketch_workflow() -> None:
    from cad_app.app import create_initial_scene

    scene = create_initial_scene()

    assert len(scene) == 0
    assert scene.active_item_id() is None


def test_main_window_can_be_created_without_qt_import_at_module_load() -> None:
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication

    from cad_app.main_window import create_main_window
    from cad_app.viewer import Viewer

    app_instance = QApplication.instance() or QApplication([])

    main_window = create_main_window(Viewer())
    assert app_instance is not None
    assert main_window.scene is not None
    assert main_window.navigation is not None
    assert main_window.picker is not None


def test_main_window_preserves_passed_scene() -> None:
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.viewer import Viewer

    app_instance = QApplication.instance() or QApplication([])
    scene = Scene()
    item_id = scene.add_shape("shape")

    main_window = create_main_window(Viewer(), scene)

    assert app_instance is not None
    assert main_window.scene is scene
    assert main_window.scene.active_item_id() == item_id
    assert main_window.picker is not None


def test_main_window_preserves_passed_empty_scene() -> None:
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.viewer import Viewer

    app_instance = QApplication.instance() or QApplication([])
    scene = Scene()

    main_window = create_main_window(Viewer(), scene)

    assert app_instance is not None
    assert main_window.scene is scene
    assert len(main_window.scene) == 0


def test_main_window_exposes_menu_toolbar_actions() -> None:
    pytest.importorskip("PySide6")

    from PySide6.QtCore import QSize, Qt
    from PySide6.QtWidgets import (
        QApplication,
        QDockWidget,
        QLabel,
        QListWidget,
        QToolBar,
    )

    from cad_app.main_window import ICON_ASSET_DIR, create_main_window
    from cad_app.types import SelectionKind
    from cad_app.viewer import Viewer

    app_instance = QApplication.instance() or QApplication([])
    main_window = create_main_window(Viewer())

    assert app_instance is not None
    assert {
        "select_object",
        "select_face",
        "select_edge",
        "select_vertex",
        "axis_x",
        "move_object",
        "move_object_x",
        "move_object_y",
        "move_object_z",
        "rotate_body",
        "mirror_body",
        "move_selection_normal",
        "move_selection_x",
        "move_selection_y",
        "move_selection_z",
        "add_box",
        "start_sketch",
        "new_sketch",
        "sketch_line_tool",
        "sketch_arc_tool",
        "sketch_circle_tool",
        "sketch_rectangle3_tool",
        "sketch_center_rectangle_tool",
        "sketch_rectangle_tool",
        "sketch_extrude",
        "sketch_new_body",
        "offset_face",
        "fit_all",
        "delete_object",
        "display_shaded",
        "display_wireframe",
        "save_project",
        "redo",
        "category_select",
        "category_sketch",
        "category_create",
        "category_modify",
        "category_transform",
        "category_measure",
        "set_boolean_target",
        "boolean_union",
        "boolean_subtract",
        "boolean_intersect",
    } <= set(main_window.actions)
    top_toolbar = main_window.window.findChild(QToolBar, "TopToolbar")
    category_toolbar = main_window.window.findChild(QToolBar, "CategoryToolbar")
    selection_mode_toolbar = main_window.window.findChild(
        QToolBar,
        "SelectionModeToolbar",
    )
    command_toolbar = main_window.window.findChild(QToolBar, "CommandToolbar")
    assert top_toolbar is not None
    assert category_toolbar is not None
    assert selection_mode_toolbar is not None
    assert command_toolbar is not None
    assert main_window.window.toolBarArea(top_toolbar) == Qt.TopToolBarArea
    assert main_window.window.toolBarArea(category_toolbar) == Qt.LeftToolBarArea
    assert main_window.window.toolBarArea(selection_mode_toolbar) == Qt.LeftToolBarArea
    assert main_window.window.toolBarArea(command_toolbar) == Qt.TopToolBarArea
    assert top_toolbar.iconSize() == QSize(20, 20)
    assert category_toolbar.iconSize() == QSize(40, 40)
    assert selection_mode_toolbar.iconSize() == QSize(40, 40)
    assert command_toolbar.iconSize() == QSize(22, 22)
    top_action_names = [action.objectName() for action in top_toolbar.actions()]
    assert "undo" in top_action_names
    assert "redo" in top_action_names
    assert "save_project" in top_action_names
    assert "export_step" in top_action_names
    assert "border-radius" in command_toolbar.styleSheet()
    assert main_window.window.findChild(QLabel, "DimensionOverlay") is not None
    assert main_window.window.findChild(QLabel, "ContextHintOverlay") is not None
    assert callable(main_window.viewer.display_orientation_gizmo)
    assert callable(main_window.viewer.display_extrude_affordance)
    assert main_window.window.findChild(QLabel, "ProjectLabel") is not None
    assert main_window.window.findChild(QDockWidget, "BrowserDock") is not None
    assert main_window.window.findChild(QListWidget, "ModelList") is not None
    assert main_window.window.findChild(QListWidget, "BodiesList") is not None
    assert main_window.window.findChild(QListWidget, "SketchesList") is not None
    assert main_window.window.findChild(QListWidget, "HistoryList") is not None
    assert main_window.window.findChild(QListWidget, "PropertiesList") is not None
    assert main_window.window.findChild(QToolBar, "CategoryToolbar") is not None
    assert main_window.window.findChild(QToolBar, "SelectionModeToolbar") is not None
    assert main_window.window.findChild(QToolBar, "SketchToolbar") is not None
    assert main_window.window.findChild(QToolBar, "ViewToolbar") is not None
    assert main_window.window.findChild(QToolBar, "CommandToolbar") is not None
    for action_name in (
        "category_select",
        "category_sketch",
        "category_create",
        "category_modify",
        "category_transform",
        "category_measure",
        "new_sketch",
        "select_object",
        "select_face",
        "select_edge",
        "select_vertex",
        "sketch_line_tool",
        "sketch_arc_tool",
        "sketch_circle_tool",
        "sketch_rectangle3_tool",
        "sketch_center_rectangle_tool",
        "sketch_new_body",
        "extrude",
        "move_selection_x",
        "delete_object",
    ):
        assert not main_window.actions[action_name].icon().isNull()
    for icon_name in (
        "01_select.png",
        "02_sketch.png",
        "03_line.png",
        "04_rectangle.png",
        "05_circle.png",
        "06_arc.png",
        "07_extrude.png",
        "08_push_pull.png",
        "09_move.png",
        "13_fillet.png",
        "14_chamfer.png",
        "18_vertex_mode.png",
        "19_edge_mode.png",
        "20_face_mode.png",
    ):
        assert (ICON_ASSET_DIR / icon_name).is_file()
    assert _command_action_names(main_window) == []
    assert not main_window.actions["category_transform"].isEnabled()
    assert main_window.actions["display_shaded"].isChecked()
    assert main_window.viewer_widget._selection_kind == SelectionKind.OBJECT
    assert main_window.actions["select_object"].shortcut().toString() == "1"
    assert main_window.actions["select_face"].shortcut().toString() == "2"
    assert main_window.actions["select_edge"].shortcut().toString() == "3"
    assert main_window.actions["select_vertex"].shortcut().toString() == "4"

    main_window.actions["select_edge"].trigger()
    assert main_window.viewer_widget._selection_kind == SelectionKind.EDGE
    assert main_window.actions["select_edge"].isChecked()

    main_window.actions["axis_y"].trigger()
    assert main_window.viewer_widget._move_axis_name == "Y"
    assert main_window.actions["axis_y"].isChecked()


def test_dynamic_command_toolbar_reacts_to_selection_context() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    app_instance = QApplication.instance() or QApplication([])
    scene = Scene()
    item_id = scene.add_shape(make_box())
    main_window = create_main_window(Viewer(), scene)

    assert app_instance is not None
    assert _command_action_names(main_window) == []

    main_window.viewer_widget._set_active_category("transform")
    assert _command_action_names(main_window) == [
        "move_object",
        "rotate_body",
        "mirror_body",
    ]

    scene.set_selection(SelectionRef(item_id=item_id, kind=SelectionKind.FACE, index=1))
    main_window.viewer_widget._set_active_category("modify")
    main_window.viewer_widget._refresh_action_state()
    assert _command_action_names(main_window) == [
        "start_sketch",
        "extrude",
        "move_selection",
        "offset_face",
    ]
    assert main_window.actions["start_sketch"].text() == "Sketch on Face"
    assert main_window.actions["extrude"].isEnabled()
    assert main_window.actions["offset_face"].isEnabled()
    assert not main_window.actions["delete_object"].isEnabled()
    assert not main_window.actions["fillet"].isEnabled()

    scene.set_selection(SelectionRef(item_id=item_id, kind=SelectionKind.EDGE, index=1))
    main_window.viewer_widget._set_active_category("modify")
    main_window.viewer_widget._refresh_action_state()
    assert _command_action_names(main_window) == [
        "fillet",
        "chamfer",
        "move_selection",
    ]
    assert not main_window.actions["extrude"].isEnabled()
    assert main_window.actions["fillet"].isEnabled()
    assert not main_window.actions["category_transform"].isEnabled()

    scene.set_selection(
        SelectionRef(item_id=item_id, kind=SelectionKind.OBJECT, index=0)
    )
    main_window.viewer_widget._set_active_category("transform")
    main_window.viewer_widget._refresh_action_state()
    assert _command_action_names(main_window)[:3] == [
        "move_object",
        "rotate_body",
        "mirror_body",
    ]


def test_dynamic_command_toolbar_promotes_sketch_profile_extrude() -> None:
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.sketch import SKETCH_META_KIND
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    app_instance = QApplication.instance() or QApplication([])
    scene = Scene()
    item_id = scene.add_shape("profile", meta={"kind": SKETCH_META_KIND})
    scene.set_selection(SelectionRef(item_id=item_id, kind=SelectionKind.FACE, index=1))

    main_window = create_main_window(Viewer(), scene)
    main_window.viewer_widget._set_active_category("modify")

    assert app_instance is not None
    assert _command_action_names(main_window) == ["sketch_extrude", "sketch_new_body"]
    assert main_window.actions["sketch_extrude"].isEnabled()
    assert main_window.actions["sketch_new_body"].isEnabled()
    assert not main_window.actions["circle_boss"].isEnabled()


def test_dynamic_command_toolbar_hides_edge_move_on_curved_topology() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication

    from cad_app.commands import fillet_edge
    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    app_instance = QApplication.instance() or QApplication([])
    scene = Scene()
    item_id = scene.add_shape(fillet_edge(make_box(40, 40, 40), edge_index=1, radius=3))
    scene.set_selection(SelectionRef(item_id=item_id, kind=SelectionKind.EDGE, index=1))
    main_window = create_main_window(Viewer(), scene)
    main_window.viewer_widget._set_active_category("modify")

    assert app_instance is not None
    assert "move_selection" not in _command_action_names(main_window)
    assert not main_window.actions["move_selection"].isEnabled()


def test_sketch_context_toolbar_exposes_new_sketch_tools() -> None:
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QLabel

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.viewer import Viewer

    app_instance = QApplication.instance() or QApplication([])
    main_window = create_main_window(Viewer(), Scene())

    main_window.actions["category_sketch"].trigger()

    assert app_instance is not None
    assert _command_action_names(main_window) == [
        "sketch_line_tool",
        "sketch_arc_tool",
        "sketch_circle_tool",
        "sketch_rectangle3_tool",
        "sketch_center_rectangle_tool",
        "cancel_tool",
    ]
    assert main_window.viewer_widget._sketch_session is not None
    assert main_window.viewer_widget._active_category == "sketch"
    assert "Mode: Sketch" in main_window.viewer_widget._hud_labels["mode"].text()
    assert main_window.actions["sketch_center_rectangle_tool"].isChecked()
    assert not main_window.window.findChild(QLabel, "ContextHintOverlay").isHidden()
    assert main_window.actions["category_sketch"].isVisible()
    assert not main_window.actions["category_select"].isVisible()
    assert not main_window.actions["category_create"].isVisible()
    assert not main_window.actions["category_transform"].isVisible()

    main_window.actions["sketch_line_tool"].trigger()

    assert main_window.actions["sketch_line_tool"].isChecked()
    assert not main_window.actions["sketch_center_rectangle_tool"].isChecked()


def test_sketch_click_matches_s_shortcut_on_empty_scene() -> None:
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind
    from cad_app.viewer import Viewer

    app_instance = QApplication.instance() or QApplication([])
    main_window = create_main_window(Viewer(), Scene())

    main_window.actions["category_sketch"].trigger()

    assert app_instance is not None
    assert main_window.viewer_widget._sketch_session is not None
    assert main_window.viewer_widget._active_category == "sketch"
    assert main_window.viewer_widget._selection_kind == SelectionKind.FACE
    assert main_window.actions["sketch_center_rectangle_tool"].isChecked()


def test_new_sketch_on_selected_face_is_independent_from_host() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication

    from cad_app.commands import top_planar_face_index
    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    app_instance = QApplication.instance() or QApplication([])
    scene = Scene()
    body = make_box()
    item_id = scene.add_shape(body)
    face_index = top_planar_face_index(body)
    scene.set_selection(SelectionRef(item_id, SelectionKind.FACE, face_index))
    main_window = create_main_window(Viewer(), scene)

    main_window.actions["new_sketch"].trigger()

    assert app_instance is not None
    assert main_window.viewer_widget._sketch_session is not None
    assert main_window.viewer_widget._sketch_session.host is None
    assert main_window.viewer_widget._active_workplane_host is None
    assert "new sketch" in main_window.viewer_widget._hud_labels["sketch"].text()
    meta = main_window.viewer_widget._sketch_profile_meta(profile="circle")
    assert meta["sketch_mode"] == "independent"
    assert "host_item_id" not in meta


def test_feature_sketch_on_selected_face_keeps_host_and_offers_new_sketch() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication

    from cad_app.commands import top_planar_face_index
    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    app_instance = QApplication.instance() or QApplication([])
    scene = Scene()
    body = make_box()
    item_id = scene.add_shape(body)
    face_index = top_planar_face_index(body)
    scene.set_selection(SelectionRef(item_id, SelectionKind.FACE, face_index))
    main_window = create_main_window(Viewer(), scene)

    main_window.actions["category_sketch"].trigger()

    assert app_instance is not None
    assert main_window.viewer_widget._sketch_session is not None
    assert main_window.viewer_widget._sketch_session.host == (item_id, face_index)
    assert "new_sketch" in _command_action_names(main_window)
    meta = main_window.viewer_widget._sketch_profile_meta(profile="circle")
    assert meta["sketch_mode"] == "feature"
    assert meta["host_item_id"] == item_id


def test_dynamic_command_toolbar_guides_body_boolean_workflow() -> None:
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.viewer import Viewer

    app_instance = QApplication.instance() or QApplication([])
    scene = Scene()
    target_id = scene.add_shape("target", meta={"kind": "body"})
    tool_id = scene.add_shape("tool", meta={"kind": "body"})
    scene.set_active_item(target_id)
    main_window = create_main_window(Viewer(), scene)
    main_window.viewer_widget._set_active_category("transform")

    assert app_instance is not None
    assert "set_boolean_target" in _command_action_names(main_window)
    assert "boolean_union" not in _command_action_names(main_window)

    main_window.actions["set_boolean_target"].trigger()
    scene.set_active_item(tool_id)
    scene.set_selection(None)
    main_window.viewer_widget._refresh_action_state()

    command_names = _command_action_names(main_window)
    assert "boolean_union" in command_names
    assert "boolean_subtract" in command_names
    assert "boolean_intersect" in command_names
    assert main_window.actions["boolean_union"].isEnabled()


def test_browser_panel_lists_bodies_sketches_and_history() -> None:
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QListWidget

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.sketch import SKETCH_META_KIND
    from cad_app.types import SelectionKind
    from cad_app.viewer import Viewer

    app_instance = QApplication.instance() or QApplication([])
    scene = Scene()
    body_id = scene.add_shape("body", meta={"kind": "body", "source": "fixture"})
    sketch_id = scene.add_shape(
        "profile",
        meta={"kind": SKETCH_META_KIND, "profile": "rectangle"},
    )
    main_window = create_main_window(Viewer(), scene)

    bodies = main_window.window.findChild(QListWidget, "BodiesList")
    sketches = main_window.window.findChild(QListWidget, "SketchesList")
    history = main_window.window.findChild(QListWidget, "HistoryList")
    model = main_window.window.findChild(QListWidget, "ModelList")
    properties = main_window.window.findChild(QListWidget, "PropertiesList")

    assert app_instance is not None
    assert bodies is not None
    assert sketches is not None
    assert history is not None
    assert model is not None
    assert properties is not None
    assert bodies.count() == 1
    assert sketches.count() == 1
    assert model.item(0).text() == "Model"
    assert model.item(1).text() == "Bodies (1)"
    assert properties.item(0).text() == "Properties"
    assert properties.item(1).text() == "Mode: Select"
    assert "Body 1: fixture" in bodies.item(0).text()
    assert "Sketch 1: rectangle" in sketches.item(0).text()
    assert history.item(0).text() == "Undo last change (2)"

    bodies.itemClicked.emit(bodies.item(0))
    assert scene.selection().item_id == body_id
    assert scene.selection().kind == SelectionKind.OBJECT

    sketches.itemClicked.emit(sketches.item(0))
    assert scene.selection().item_id == sketch_id
    assert scene.selection().kind == SelectionKind.FACE
    assert scene.selection().index == 1

    history.itemClicked.emit(history.item(0))
    assert sketch_id not in scene
    assert len(scene) == 1

    main_window.actions["add_box"].trigger()

    assert bodies.count() == 2


def test_dimension_overlay_updates_position_text_and_visibility() -> None:
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.viewer import Viewer

    app_instance = QApplication.instance() or QApplication([])
    main_window = create_main_window(Viewer(), Scene())
    overlay = main_window.viewer_widget._dimension_overlay

    main_window.viewer_widget._show_dimension_overlay("Distance: 12.50 mm", 30, 40)

    assert app_instance is not None
    assert overlay.text() == "Distance: 12.50 mm"
    assert overlay.pos().x() >= 30
    assert overlay.pos().y() >= 40
    assert not overlay.isHidden()

    main_window.viewer_widget._show_dimension_overlay("Extrude 20.00 mm", 50, 60)

    assert overlay.text() == "Extrude 20.00 mm"
    assert overlay.pos().x() >= 50
    assert overlay.pos().y() >= 60

    main_window.viewer_widget._hide_dimension_overlay()

    assert overlay.isHidden()


def test_add_box_action_creates_second_body() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.viewer import Viewer

    app_instance = QApplication.instance() or QApplication([])
    scene = Scene()
    main_window = create_main_window(Viewer(), scene)

    main_window.actions["add_box"].trigger()
    main_window.actions["add_box"].trigger()

    assert app_instance is not None
    assert len(scene) == 2
    assert all(item.meta.get("kind") == "body" for item in scene)


def test_delete_object_action_removes_active_item_and_undo_restores_it() -> None:
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.viewer import Viewer

    app_instance = QApplication.instance() or QApplication([])
    scene = Scene()
    item_id = scene.add_shape("body")
    main_window = create_main_window(Viewer(), scene)

    main_window.actions["delete_object"].trigger()

    assert app_instance is not None
    assert item_id not in scene
    assert len(scene) == 0

    main_window.actions["undo"].trigger()

    assert item_id in scene
    assert scene.get(item_id).shape == "body"


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


def test_viewer_wraps_integer_window_handle_as_capsule() -> None:
    from cad_app.viewer import Viewer

    capsule = Viewer._create_native_handle_capsule(1)
    assert type(capsule).__name__ == "PyCapsule"
