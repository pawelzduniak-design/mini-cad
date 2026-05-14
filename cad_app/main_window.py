"""UI shell for the application."""

from __future__ import annotations

from cad_app import theme
from cad_app.navigation import NavigationController
from cad_app.picker import Picker
from cad_app.scene import Scene
from cad_app.ui_actions import build_main_window_actions
from cad_app.ui_chrome import ICON_ASSET_DIR as ICON_ASSET_DIR
from cad_app.ui_layout import build_main_window_layout
from cad_app.ui_sessions import (
    DEFAULT_EDGE_PARAMETER,
    EXTRUDE_DRAG_FALLBACK_AXIS,
    EXTRUDE_DRAG_PROBE_DISTANCE,
    ROTATE_DRAG_FALLBACK_AXIS,
    MainWindow,
    MoveSession,
    SketchSession,
)
from cad_app.ui_sessions import axis_vector as _axis_vector
from cad_app.ui_sessions import drag_distance_delta as _drag_distance_delta
from cad_app.ui_sessions import normalize_screen_axis as _normalize_screen_axis
from cad_app.ui_sessions import sketch_dimension_label as _sketch_dimension_label
from cad_app.viewer import Viewer
from cad_app.viewer_widget import create_viewer_widget

__all__ = [
    "DEFAULT_EDGE_PARAMETER",
    "EXTRUDE_DRAG_FALLBACK_AXIS",
    "EXTRUDE_DRAG_PROBE_DISTANCE",
    "ICON_ASSET_DIR",
    "MainWindow",
    "MoveSession",
    "ROTATE_DRAG_FALLBACK_AXIS",
    "SketchSession",
    "_axis_vector",
    "_drag_distance_delta",
    "_normalize_screen_axis",
    "_sketch_dimension_label",
    "create_main_window",
]


def create_main_window(viewer: Viewer, scene: Scene | None = None) -> MainWindow:
    if scene is None:
        scene = Scene()
    navigation = NavigationController()
    picker = Picker(scene)

    from PySide6.QtWidgets import QMainWindow

    window = QMainWindow()
    window.setObjectName("app_shell")
    viewer_widget = create_viewer_widget(viewer, scene, navigation, picker)
    window.setCentralWidget(viewer_widget)
    window.setWindowTitle("Direct Modeling CAD")
    window.setStyleSheet(theme.app_stylesheet())
    actions, commands_menu = build_main_window_actions(window, viewer_widget)

    build_main_window_layout(window, viewer_widget, actions, commands_menu)
    if len(scene) == 0:
        viewer_widget._set_active_category("sketch")
    return MainWindow(
        window=window,
        viewer_widget=viewer_widget,
        viewer=viewer,
        scene=scene,
        navigation=navigation,
        picker=picker,
        actions=actions,
    )
