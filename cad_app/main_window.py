"""UI shell for the application."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cad_app import theme
from cad_app.commands import (
    CommandError,
    apply_boolean_bodies,
    apply_chamfer_edge,
    apply_circle_feature,
    apply_extrude_face,
    apply_fillet_edge,
    apply_move_edge_controlled,
    apply_move_face_controlled,
    apply_move_face_normal,
    apply_move_object,
    apply_move_vertex_controlled,
    apply_rotate_object,
    chamfer_edge,
    extrude_face,
    face_normal_vector,
    fillet_edge,
    rotated_shape,
    supports_move_edge_controlled,
    supports_move_face_controlled,
    supports_move_vertex_controlled,
    translated_shape,
)
from cad_app.engine import make_box
from cad_app.io_step import StepIOError, export_step, import_step
from cad_app.navigation import NavigationController
from cad_app.picker import Picker
from cad_app.scene import Scene
from cad_app.sketch import (
    SKETCH_ENTITY_META_KIND,
    SKETCH_META_KIND,
    apply_profile_feature,
    extrude_profile,
    is_closed_polyline,
    is_sketch_object,
    is_sketch_profile,
    make_center_rectangle_profile,
    make_circle_profile,
    make_circle_profile_at,
    make_point_marker_preview,
    make_polyline_preview,
    make_polyline_profile,
    make_rectangle_profile,
    make_rectangle_profile_from_corners,
    make_rectangle_profile_three_point,
    make_three_point_arc_edge,
    project_screen_to_workplane,
    three_point_arc_radius,
)
from cad_app.types import OperationState, SelectionKind, SelectionRef, UIState
from cad_app.viewer import Viewer
from cad_app.workplane import Workplane

LOGGER = logging.getLogger(__name__)

ICON_ASSET_DIR = Path(__file__).resolve().parent / "assets" / "icons"
EXTRUDE_DRAG_FALLBACK_AXIS = (0.0, -1.0)
EXTRUDE_DRAG_PROBE_DISTANCE = 25.0
DEFAULT_EDGE_PARAMETER = 4.0
ROTATE_DRAG_FALLBACK_AXIS = (1.0, 0.0)


def _normalize_screen_axis(
    dx: float,
    dy: float,
) -> tuple[float, float] | None:
    length = math.hypot(dx, dy)
    if length < 2.0:
        return None
    return dx / length, dy / length


def _drag_distance_delta(
    dx: float,
    dy: float,
    scale: float,
    screen_axis: tuple[float, float] | None = None,
) -> float:
    if screen_axis is None:
        return dx * scale
    return (dx * screen_axis[0] + dy * screen_axis[1]) * scale


def _sketch_dimension_label(
    tool: str,
    start_uv: tuple[float, float],
    end_uv: tuple[float, float],
) -> str:
    if tool == "rectangle":
        width = abs(end_uv[0] - start_uv[0])
        height = abs(end_uv[1] - start_uv[1])
        return f"{width:.1f} x {height:.1f}"
    if tool == "center_rectangle":
        width = abs(end_uv[0] - start_uv[0]) * 2.0
        height = abs(end_uv[1] - start_uv[1]) * 2.0
        return f"{width:.1f} x {height:.1f}"
    if tool == "circle":
        radius = math.hypot(end_uv[0] - start_uv[0], end_uv[1] - start_uv[1])
        return f"R {radius:.1f}"
    raise ValueError(f"Unsupported sketch tool: {tool}")


@dataclass
class MainWindow:
    """Wrapper for the Qt main window and viewer widget."""

    window: Any
    viewer_widget: Any
    viewer: Viewer
    scene: Scene
    navigation: NavigationController
    picker: Picker
    actions: dict[str, Any]


@dataclass
class MoveSession:
    """UI-only state for an active drag move operation."""

    tool: str
    target_kind: SelectionKind | str
    item_id: str
    index: int | None
    axis_name: str
    axis: tuple[float, float, float]
    operation: str = "auto"
    distance: float = 0.0
    drag_start: tuple[int, int] | None = None
    drag_origin_distance: float = 0.0
    drag_screen_axis: tuple[float, float] | None = None
    vector: tuple[float, float, float] | None = None
    drag_origin_vector: tuple[float, float, float] = (0.0, 0.0, 0.0)
    drag_view_anchor: tuple[float, float, float] | None = None
    drag_view_normal: tuple[float, float, float] | None = None
    drag_view_start_point: tuple[float, float, float] | None = None


@dataclass
class SketchSession:
    """UI-only state for drawing profiles on a workplane."""

    workplane: Workplane
    label: str
    host: tuple[str, int] | None
    tool: str = "center_rectangle"
    start_uv: tuple[float, float] | None = None
    points: list[tuple[float, float]] = field(default_factory=list)
    drag_start_screen: tuple[int, int] | None = None
    drag_moved: bool = False
    drag_dimensions: str | None = None


def create_main_window(viewer: Viewer, scene: Scene | None = None) -> MainWindow:
    if scene is None:
        scene = Scene()
    navigation = NavigationController()
    picker = Picker(scene)

    from PySide6.QtCore import QSize, Qt, QTimer
    from PySide6.QtGui import (
        QAction,
        QActionGroup,
        QColor,
        QIcon,
        QKeySequence,
        QPainter,
        QPen,
        QPixmap,
    )
    from PySide6.QtWidgets import (
        QDockWidget,
        QFileDialog,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QTabWidget,
        QToolBar,
        QVBoxLayout,
        QWidget,
    )

    BROWSER_ITEM_ID_ROLE = Qt.UserRole
    BROWSER_SELECTION_KIND_ROLE = Qt.UserRole + 1
    BROWSER_SELECTION_INDEX_ROLE = Qt.UserRole + 2
    BROWSER_COMMAND_ROLE = Qt.UserRole + 3

    class ViewerWidget(QWidget):
        def __init__(self, owner: Viewer, navigator: NavigationController) -> None:
            super().__init__()
            self._viewer = owner
            self._navigation = navigator
            self._initial_scene_displayed = False
            self._selection_kind = SelectionKind.OBJECT
            self._hover_selection = None
            self._move_session: MoveSession | None = None
            self._move_axis = (1.0, 0.0, 0.0)
            self._move_axis_name = "X"
            self._move_pixels_to_units = 0.2
            self._sketch_session: SketchSession | None = None
            self._active_workplane = Workplane.world_xy()
            self._active_workplane_label = "XY"
            self._active_workplane_host: tuple[str, int] | None = None
            self._hud_labels: dict[str, QLabel] = {}
            self._actions: dict[str, QAction] = {}
            self._command_menu = None
            self._command_toolbar = None
            self._command_section_actions: dict[str, Any] = {}
            self._sketch_toolbar: Any = None
            self._browser_lists: dict[str, Any] = {}
            self._boolean_target_item_id: str | None = None
            self._active_category = "select"
            self._last_status_text = "Ready"
            self._orientation_gizmo_press: tuple[int, int] | None = None
            self._orientation_gizmo_dragging = False
            self._dimension_overlay = QLabel(self)
            self._dimension_overlay.setObjectName("DimensionOverlay")
            self._dimension_overlay.setStyleSheet(theme.overlay_stylesheet())
            self._dimension_overlay.hide()
            self._context_hint_overlay = QLabel(self)
            self._context_hint_overlay.setObjectName("ContextHintOverlay")
            self._context_hint_overlay.setStyleSheet(theme.overlay_stylesheet())
            self._context_hint_overlay.hide()
            self.setAttribute(Qt.WA_NativeWindow)
            self.setAttribute(Qt.WA_PaintOnScreen)
            self.setFocusPolicy(Qt.StrongFocus)

        def attach_hud(self, labels: dict[str, QLabel]) -> None:
            self._hud_labels = labels
            self._refresh_hud()

        def attach_actions(self, actions: dict[str, QAction]) -> None:
            self._actions = actions
            self._refresh_action_state()

        def attach_command_surface(self, menu, toolbar) -> None:
            self._command_menu = menu
            self._command_toolbar = toolbar
            self._refresh_action_state()

        def attach_browser(self, browser_lists: dict[str, Any]) -> None:
            self._browser_lists = browser_lists
            for browser_list in browser_lists.values():
                browser_list.itemClicked.connect(self._handle_browser_item_clicked)
            self._refresh_browser()

        def showEvent(self, event) -> None:
            if not self._viewer.is_initialized:
                self._viewer.initialize(self)
                self._navigation.attach_view(self._viewer.view)
                QTimer.singleShot(0, self._display_initial_scene)
                QTimer.singleShot(100, self._refit_initial_scene)
            super().showEvent(event)

        def resizeEvent(self, event) -> None:
            self._viewer.resize()
            self._position_context_hint()
            super().resizeEvent(event)

        def paintEngine(self):
            return None

        def _display_initial_scene(self) -> None:
            if self._initial_scene_displayed or not self._viewer.is_initialized:
                return
            LOGGER.info("Initial scene display started")
            self._viewer.resize()
            self._viewer.display_scene(scene)
            if len(scene) == 0:
                self._set_context_hint("Start: Sketch on the grid or Create a body")
            self._navigation.capture_home()
            self._initial_scene_displayed = True
            LOGGER.info("Initial scene display finished")

        def _refit_initial_scene(self) -> None:
            if not self._viewer.is_initialized:
                return
            self._viewer.fit_all()
            self._navigation.capture_home()

        def mousePressEvent(self, event) -> None:
            position = event.position().toPoint()
            if event.button() == Qt.LeftButton and self._is_in_orientation_gizmo(
                position.x(), position.y()
            ):
                self._orientation_gizmo_press = (position.x(), position.y())
                self._orientation_gizmo_dragging = False
                event.accept()
                return
            if event.button() == Qt.RightButton and self._sketch_session is not None:
                self._finish_sketch_sequence()
                event.accept()
                return
            if event.button() == Qt.RightButton:
                self._navigation.begin_pan(position.x(), position.y())
                event.accept()
                return
            if event.button() == Qt.MiddleButton:
                self._navigation.begin_orbit(position.x(), position.y())
                event.accept()
                return
            if event.button() == Qt.LeftButton and self._sketch_session is not None:
                self._begin_sketch_drag(position.x(), position.y())
                event.accept()
                return
            if event.button() == Qt.LeftButton and self._move_session is not None:
                self._begin_move_drag(position.x(), position.y())
                event.accept()
                return
            if event.button() == Qt.LeftButton:
                self._select_at(position.x(), position.y())
                event.accept()
                return
            super().mousePressEvent(event)

        def mouseMoveEvent(self, event) -> None:
            position = event.position().toPoint()
            if self._orientation_gizmo_press is not None:
                start_x, start_y = self._orientation_gizmo_press
                if not self._orientation_gizmo_dragging:
                    if math.hypot(position.x() - start_x, position.y() - start_y) < 4.0:
                        event.accept()
                        return
                    self._orientation_gizmo_dragging = True
                    self._navigation.begin_orbit(start_x, start_y)
                self._navigation.orbit_to(position.x(), position.y())
                event.accept()
                return
            if event.buttons() & Qt.RightButton:
                self._navigation.pan_to(position.x(), position.y())
                event.accept()
                return
            if event.buttons() & Qt.MiddleButton:
                self._navigation.orbit_to(position.x(), position.y())
                event.accept()
                return
            if self._move_session is not None and event.buttons() & Qt.LeftButton:
                fine = bool(event.modifiers() & Qt.ShiftModifier)
                snap = bool(event.modifiers() & Qt.ControlModifier)
                self._drag_move_to(position.x(), position.y(), fine=fine, snap=snap)
                event.accept()
                return
            if self._sketch_session is not None and event.buttons() & Qt.LeftButton:
                snap = bool(event.modifiers() & Qt.ControlModifier)
                self._drag_sketch_to(position.x(), position.y(), snap=snap)
                event.accept()
                return
            if self._sketch_session is not None:
                snap = bool(event.modifiers() & Qt.ControlModifier)
                self._preview_sketch_to(position.x(), position.y(), snap=snap)
                event.accept()
                return
            if self._move_session is None:
                self._preview_at(position.x(), position.y())
            super().mouseMoveEvent(event)

        def mouseReleaseEvent(self, event) -> None:
            position = event.position().toPoint()
            if (
                event.button() == Qt.LeftButton
                and self._orientation_gizmo_press is not None
            ):
                if self._orientation_gizmo_dragging:
                    self._navigation.end_orbit()
                else:
                    axis = self._orientation_gizmo_axis_at(position.x(), position.y())
                    if axis is not None:
                        self._navigation.view_axis(axis)
                self._orientation_gizmo_press = None
                self._orientation_gizmo_dragging = False
                event.accept()
                return
            if event.button() == Qt.RightButton:
                self._navigation.end_pan()
                event.accept()
                return
            if event.button() == Qt.MiddleButton:
                self._navigation.end_orbit()
                event.accept()
                return
            if event.button() == Qt.LeftButton and self._move_session is not None:
                self._commit_move_session()
                event.accept()
                return
            if event.button() == Qt.LeftButton and self._sketch_session is not None:
                self._commit_sketch_drag(position.x(), position.y())
                event.accept()
                return
            super().mouseReleaseEvent(event)

        def wheelEvent(self, event) -> None:
            position = event.position().toPoint()
            self._navigation.zoom_at_cursor(
                event.angleDelta().y(),
                position.x(),
                position.y(),
            )
            event.accept()

        def keyPressEvent(self, event) -> None:
            if event.key() == Qt.Key_F:
                self._fit_all()
                return
            if event.key() == Qt.Key_H:
                self._navigation.go_home()
                return
            if event.key() == Qt.Key_Z and event.modifiers() & Qt.ControlModifier:
                self._undo()
                return
            if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
                self._delete_active_object()
                return
            if event.key() == Qt.Key_Escape:
                if self._sketch_session is not None:
                    self._finish_sketch_sequence()
                else:
                    self._cancel_move_session()
                return
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if self._sketch_session is not None:
                    self._finish_sketch_sequence()
                    return
                self._commit_move_session()
                return
            if event.key() == Qt.Key_1:
                self._set_selection_kind(SelectionKind.OBJECT)
                return
            if event.key() == Qt.Key_2:
                self._set_selection_kind(SelectionKind.FACE)
                return
            if event.key() == Qt.Key_3:
                self._set_selection_kind(SelectionKind.EDGE)
                return
            if event.key() == Qt.Key_4:
                self._set_selection_kind(SelectionKind.VERTEX)
                return
            if event.key() == Qt.Key_X and not event.modifiers():
                self._set_move_axis("X", (1.0, 0.0, 0.0))
                return
            if event.key() == Qt.Key_Y and not event.modifiers():
                self._set_move_axis("Y", (0.0, 1.0, 0.0))
                return
            if event.key() == Qt.Key_Z and not event.modifiers():
                self._set_move_axis("Z", (0.0, 0.0, 1.0))
                return
            if event.key() == Qt.Key_S:
                self._start_sketch_on_selection()
                return
            if self._sketch_session is not None and event.key() == Qt.Key_L:
                self._set_sketch_tool("line")
                return
            if self._sketch_session is not None and event.key() == Qt.Key_A:
                self._set_sketch_tool("arc")
                return
            if self._sketch_session is not None and event.key() == Qt.Key_R:
                self._set_sketch_tool("center_rectangle")
                return
            if self._sketch_session is not None and event.key() == Qt.Key_C:
                self._set_sketch_tool("circle")
                return
            if event.key() == Qt.Key_E:
                if event.modifiers() & Qt.ShiftModifier:
                    self._extrude_active_top_face(-10.0)
                else:
                    self._begin_extrude_tool()
                return
            if event.key() == Qt.Key_G:
                self._begin_context_move_tool()
                return
            if event.key() == Qt.Key_M:
                self._begin_selected_move_tool()
                return
            if event.key() == Qt.Key_R:
                self._begin_fillet_tool()
                return
            if event.key() == Qt.Key_C:
                self._begin_chamfer_tool()
                return
            if event.key() == Qt.Key_O:
                cut = bool(event.modifiers() & Qt.ShiftModifier)
                self._circle_feature_on_selected_face(cut=cut)
                return
            super().keyPressEvent(event)

        def _extrude_active_top_face(self, distance: float) -> None:
            item_id, face_index = self._selected_face()
            if item_id is None or face_index is None:
                self._show_status("Select a face first")
                LOGGER.info("Extrude ignored because no face is selected")
                return
            try:
                apply_extrude_face(scene, item_id, face_index, distance)
            except (CommandError, IndexError, ValueError) as exc:
                LOGGER.warning(
                    "Extrude failed item_id=%s face=%s distance=%.2f: %s",
                    item_id,
                    face_index,
                    distance,
                    exc,
                    exc_info=True,
                )
                self._show_status("Extrude failed")
                return
            scene.set_selection(None)
            self._hover_selection = None
            self._viewer.display_scene(scene, fit=False)
            self._show_status("Extrude applied")
            LOGGER.info(
                "Extrude applied item_id=%s face=%d distance=%.2f",
                item_id,
                face_index,
                distance,
            )

        def _import_step_dialog(self) -> None:
            path, _ = QFileDialog.getOpenFileName(
                self.window(),
                "Import STEP",
                "",
                "STEP files (*.step *.stp);;All files (*.*)",
            )
            if not path:
                return
            try:
                shape = import_step(path)
            except StepIOError as exc:
                LOGGER.warning(
                    "STEP import failed path=%s: %s",
                    path,
                    exc,
                    exc_info=True,
                )
                self._show_status("STEP import failed")
                return
            item_id = scene.add_shape(shape, meta={"source": path})
            scene.set_active_item(item_id)
            scene.set_selection(None)
            self._hover_selection = None
            self._viewer.display_scene(scene, fit=True)
            self._navigation.capture_home()
            self._show_status("STEP imported")
            LOGGER.info("STEP imported path=%s item_id=%s", path, item_id)

        def _export_step_dialog(self) -> None:
            item_id = scene.active_item_id()
            if item_id is None:
                self._show_status("No active object")
                return
            path, _ = QFileDialog.getSaveFileName(
                self.window(),
                "Export STEP",
                "",
                "STEP files (*.step *.stp);;All files (*.*)",
            )
            if not path:
                return
            try:
                export_step(scene.get(item_id).shape, path)
            except StepIOError as exc:
                LOGGER.warning(
                    "STEP export failed path=%s: %s",
                    path,
                    exc,
                    exc_info=True,
                )
                self._show_status("STEP export failed")
                return
            self._show_status("STEP exported")
            LOGGER.info("STEP exported path=%s item_id=%s", path, item_id)

        def _add_box_body(self) -> None:
            body_count = len(self._body_item_ids())
            shape = translated_shape(
                make_box(60.0, 50.0, 45.0), body_count * 35.0, 0.0, 0.0
            )
            item_id = scene.add_shape(
                shape,
                meta={
                    "kind": "body",
                    "source": "primitive_box",
                    "body_index": body_count + 1,
                },
            )
            scene.set_active_item(item_id)
            scene.set_selection(None)
            self._hover_selection = None
            if self._viewer.is_initialized:
                self._viewer.display_scene(scene, fit=True)
                self._navigation.capture_home()
            self._show_status("Box body added")
            LOGGER.info("Box body added item_id=%s index=%d", item_id, body_count + 1)

        def _select_at(self, x: int, y: int) -> None:
            if not self._viewer.is_initialized:
                return
            view_x, view_y = self._to_view_pixels(x, y)
            LOGGER.debug(
                "Pick requested kind=%s logical=(%d,%d) view=(%d,%d) dpr=%.2f",
                self._selection_kind.value,
                x,
                y,
                view_x,
                view_y,
                self.devicePixelRatioF(),
            )
            self._viewer.clear_selection_marker()
            if self._selection_kind == SelectionKind.OBJECT:
                pick_result = picker.pick_object_result_at(
                    self._viewer.view,
                    view_x,
                    view_y,
                )
                selection = None if pick_result is None else pick_result.selection
            elif self._selection_kind == SelectionKind.EDGE:
                pick_result = picker.pick_edge_result_at(
                    self._viewer.view,
                    view_x,
                    view_y,
                )
                selection = None if pick_result is None else pick_result.selection
            elif self._selection_kind == SelectionKind.FACE:
                pick_result = picker.pick_face_result_at(
                    self._viewer.view,
                    view_x,
                    view_y,
                )
                selection = None if pick_result is None else pick_result.selection
            else:
                pick_result = None
                selection = picker.pick_at(
                    self._viewer.context,
                    self._viewer.view,
                    view_x,
                    view_y,
                    self._selection_kind,
                )
            scene.set_selection(selection)
            if selection is None:
                self._viewer.clear_selection()
                self._set_context_hint(f"No {self._selection_kind.value} under cursor")
                self._show_status("No selection")
                LOGGER.info(
                    "Pick missed kind=%s logical=(%d,%d) view=(%d,%d)",
                    self._selection_kind.value,
                    x,
                    y,
                    view_x,
                    view_y,
                )
                return
            if selection.kind == SelectionKind.FACE:
                selected_profile = is_sketch_profile(scene.get(selection.item_id).meta)
                self._active_category = "modify"
                self._viewer.clear_selection()
                self._viewer.clear_hover_marker()
                self._viewer.display_selection_marker(
                    picker.subshape(selection.item_id, selection.kind, selection.index)
                )
                if selected_profile:
                    self._set_context_hint(
                        "Sketch Profile selected - Extrude is available"
                    )
                    self._show_status("Selected Sketch Profile")
                else:
                    self._set_context_hint(
                        "Face selected - choose Extrude Face or Move Face"
                    )
                    self._show_status(f"Selected face {selection.index}")
                self._refresh_hud()
                if pick_result is not None:
                    LOGGER.info(
                        "Selected face item_id=%s index=%d depth=%.2f",
                        selection.item_id,
                        selection.index,
                        pick_result.depth,
                    )
                return
            if selection.kind == SelectionKind.OBJECT:
                self._active_category = "transform"
                self._viewer.clear_selection()
                self._viewer.clear_hover_marker()
                self._viewer.display_selection_marker(
                    picker.subshape(selection.item_id, selection.kind, selection.index)
                )
                self._set_context_hint("Body selected - choose Move")
                self._show_status(f"Selected body {selection.item_id[:8]}")
                self._refresh_hud()
                if pick_result is not None:
                    LOGGER.info(
                        "Selected object item_id=%s depth=%.2f",
                        selection.item_id,
                        pick_result.depth,
                    )
                return

            self._viewer.clear_selection()
            self._viewer.clear_hover_marker()
            self._active_category = "modify"
            scene_object = scene.get(selection.item_id)
            self._viewer.display_selection_marker(
                picker.subshape(selection.item_id, selection.kind, selection.index),
                scene_object.meta,
            )
            self._set_context_hint(
                f"{selection.kind.value.title()} selected - choose an available tool"
            )
            if pick_result is not None:
                label = (
                    "edge"
                    if selection.kind == SelectionKind.EDGE
                    else selection.kind.value
                )
                self._show_status(
                    f"Selected {label} {selection.index}"
                    f" ({pick_result.distance_px:.1f}px)"
                )
                LOGGER.info(
                    "Selected %s item_id=%s index=%d distance_px=%.2f depth=%.2f",
                    selection.kind.value,
                    selection.item_id,
                    selection.index,
                    pick_result.distance_px,
                    pick_result.depth,
                )
            self._refresh_hud()

        def _preview_at(self, x: int, y: int) -> None:
            if not self._viewer.is_initialized:
                return
            view_x, view_y = self._to_view_pixels(x, y)
            if self._selection_kind == SelectionKind.OBJECT:
                pick_result = picker.pick_object_result_at(
                    self._viewer.view,
                    view_x,
                    view_y,
                )
            elif self._selection_kind == SelectionKind.FACE:
                pick_result = picker.pick_face_result_at(
                    self._viewer.view,
                    view_x,
                    view_y,
                )
            elif self._selection_kind == SelectionKind.EDGE:
                pick_result = picker.pick_edge_result_at(
                    self._viewer.view,
                    view_x,
                    view_y,
                )
            else:
                pick_result = picker.pick_vertex_result_at(
                    self._viewer.view,
                    view_x,
                    view_y,
                )
            selection = None if pick_result is None else pick_result.selection
            if selection == self._hover_selection:
                return

            self._hover_selection = selection
            self._viewer.clear_hover_marker()
            if selection is None:
                return

            scene_object = scene.get(selection.item_id)
            self._viewer.display_hover_marker(
                picker.subshape(selection.item_id, selection.kind, selection.index),
                scene_object.meta,
            )
            if is_sketch_profile(scene_object.meta):
                self._set_context_hint("Sketch Profile - click inside to select")
            LOGGER.debug(
                "Hover %s item_id=%s index=%d distance_px=%.2f depth=%.2f",
                selection.kind.value,
                selection.item_id,
                selection.index,
                getattr(pick_result, "distance_px", -1.0),
                pick_result.depth,
            )

        def _to_view_pixels(self, x: int, y: int) -> tuple[int, int]:
            scale = self.devicePixelRatioF()
            return int(round(x * scale)), int(round(y * scale))

        def _circle_feature_on_selected_face(self, cut: bool) -> None:
            item_id, face_index = self._selected_face()
            if item_id is None or face_index is None:
                self._show_status("Select a face first")
                LOGGER.info("Circle feature ignored because no face is selected")
                return
            try:
                apply_circle_feature(
                    scene,
                    item_id,
                    face_index,
                    radius=8.0,
                    depth=30.0,
                    cut=cut,
                )
            except (CommandError, IndexError, ValueError) as exc:
                LOGGER.warning(
                    "Circle feature failed item_id=%s face=%s cut=%s: %s",
                    item_id,
                    face_index,
                    cut,
                    exc,
                    exc_info=True,
                )
                self._show_status("Circle feature failed")
                return
            scene.set_selection(None)
            self._hover_selection = None
            self._viewer.display_scene(scene, fit=False)
            self._show_status("Circle cut applied" if cut else "Circle boss applied")
            LOGGER.info(
                "Circle feature applied item_id=%s face=%d cut=%s",
                item_id,
                face_index,
                cut,
            )

        def _start_sketch_on_selection(self) -> None:
            item_id, face_index = self._selected_face()
            if item_id is None or face_index is None:
                if len(scene) == 0:
                    self._start_sketch_session(
                        Workplane.world_xy(),
                        "XY",
                        None,
                    )
                    return
                self._show_status("Select a planar face, then press S")
                self._set_context_hint(
                    "Select a planar face, then click Sketch or press S"
                )
                LOGGER.info("Sketch start ignored because no face is selected")
                return
            try:
                from OCP.TopoDS import TopoDS

                face = TopoDS.Face_s(
                    picker.subshape(item_id, SelectionKind.FACE, face_index)
                )
                workplane = Workplane.from_face(face)
            except (CommandError, IndexError, ValueError) as exc:
                LOGGER.warning(
                    "Sketch start failed item_id=%s face=%s: %s",
                    item_id,
                    face_index,
                    exc,
                    exc_info=True,
                )
                self._show_status("Planar face required")
                return
            self._start_sketch_session(
                workplane,
                f"face {face_index}",
                (item_id, face_index),
            )

        def _start_new_sketch_on_selection(self) -> None:
            if self._sketch_session is not None:
                self._start_sketch_session(
                    self._sketch_session.workplane,
                    f"new sketch on {self._sketch_session.label}",
                    None,
                )
                return
            item_id, face_index = self._selected_face()
            if item_id is None or face_index is None:
                if len(scene) == 0:
                    self._start_sketch_session(
                        Workplane.world_xy(),
                        "new sketch XY",
                        None,
                    )
                    return
                self._show_status("Select a planar face for New Sketch")
                self._set_context_hint("Select a planar face, then choose New Sketch")
                LOGGER.info("New sketch ignored because no face is selected")
                return
            try:
                from OCP.TopoDS import TopoDS

                face = TopoDS.Face_s(
                    picker.subshape(item_id, SelectionKind.FACE, face_index)
                )
                workplane = Workplane.from_face(face)
            except (CommandError, IndexError, ValueError) as exc:
                LOGGER.warning(
                    "New sketch failed item_id=%s face=%s: %s",
                    item_id,
                    face_index,
                    exc,
                    exc_info=True,
                )
                self._show_status("Planar face required")
                return
            self._start_sketch_session(
                workplane,
                f"new sketch on face {face_index}",
                None,
            )

        def _start_sketch_session(
            self,
            workplane: Workplane,
            label: str,
            host: tuple[str, int] | None,
        ) -> None:
            self._cancel_move_session(status="Move cancelled")
            self._sketch_session = SketchSession(
                workplane=workplane,
                label=label,
                host=host,
                tool="center_rectangle",
            )
            self._active_workplane = workplane
            self._active_workplane_label = label
            self._active_workplane_host = host
            self._active_category = "sketch"
            self._selection_kind = SelectionKind.FACE
            self._hover_selection = None
            if self._viewer.is_initialized:
                self._viewer.set_selection_kind(SelectionKind.FACE)
                self._navigation.view_workplane(workplane)
                self._viewer.display_sketch_plane_marker(workplane)
            self._set_sketch_tool("center_rectangle", clear_points=False)
            if host is None:
                self._set_context_hint(
                    "New Sketch - Center Rectangle: click center, drag size, "
                    "then use New Body or Extrude Sketch"
                )
                self._show_status("New Sketch: center rectangle tool")
            else:
                self._set_context_hint(
                    "Feature Sketch - Center Rectangle: click center, drag size; "
                    "Extrude edits body, New Body creates a separate body"
                )
                self._show_status("Feature Sketch: center rectangle tool")
            self._refresh_hud()
            LOGGER.info("Sketch started workplane=%s host=%s", label, host)

        def _set_sketch_tool(self, tool: str, clear_points: bool = True) -> None:
            if self._sketch_session is None:
                return
            if tool not in {
                "line",
                "arc",
                "circle",
                "rectangle_3_point",
                "center_rectangle",
            }:
                raise ValueError(f"Unsupported sketch tool: {tool}")
            self._sketch_session.tool = tool
            self._sketch_session.start_uv = None
            self._sketch_session.drag_start_screen = None
            self._sketch_session.drag_moved = False
            if clear_points:
                self._sketch_session.points.clear()
                self._sketch_session.drag_dimensions = None
            self._viewer.clear_preview_marker()
            self._hide_dimension_overlay()
            self._set_context_hint(self._sketch_tool_hint(tool))
            self._show_status(f"Sketch: {tool} tool")
            for action_name, action_tool in {
                "sketch_line_tool": "line",
                "sketch_arc_tool": "arc",
                "sketch_circle_tool": "circle",
                "sketch_rectangle3_tool": "rectangle_3_point",
                "sketch_center_rectangle_tool": "center_rectangle",
                "sketch_rectangle_tool": "center_rectangle",
            }.items():
                action = self._actions.get(action_name)
                if action is not None:
                    action.setChecked(tool == action_tool)
            self._refresh_hud()
            LOGGER.info("Sketch tool set to %s", tool)

        @staticmethod
        def _sketch_tool_hint(tool: str) -> str:
            hints = {
                "line": "Line: click points, Enter/Esc to finish",
                "arc": "Arc: click start, click end, click bend point",
                "circle": "Circle: click center, set radius, click to confirm",
                "rectangle_3_point": "Rectangle 3 Point: base points, then height",
                "center_rectangle": "Center Rectangle: click center, drag size",
            }
            return hints.get(tool, "Sketch: choose points in the viewport")

        def _begin_sketch_drag(self, x: int, y: int) -> None:
            if self._sketch_session is None or not self._viewer.is_initialized:
                return
            uv = self._screen_to_sketch_uv(x, y)
            if uv is None:
                self._show_status("Sketch point unavailable")
                LOGGER.info("Sketch drag ignored because workplane projection failed")
                return
            self._sketch_session.start_uv = uv
            self._sketch_session.drag_start_screen = (x, y)
            self._sketch_session.drag_moved = False
            self._sketch_session.drag_dimensions = None
            self._refresh_hud()
            LOGGER.debug(
                "Sketch drag started tool=%s uv=(%.3f,%.3f)",
                self._sketch_session.tool,
                uv[0],
                uv[1],
            )

        def _drag_sketch_to(self, x: int, y: int, snap: bool = False) -> None:
            if self._sketch_session is None or self._sketch_session.start_uv is None:
                return
            if self._sketch_session.drag_start_screen is not None:
                self._sketch_session.drag_moved = (
                    math.dist(self._sketch_session.drag_start_screen, (x, y)) > 3.0
                )
            self._preview_sketch_to(x, y, snap=snap)

        def _preview_sketch_to(self, x: int, y: int, snap: bool = False) -> None:
            if self._sketch_session is None:
                return
            uv = self._screen_to_sketch_uv(x, y, snap=snap)
            if uv is None:
                self._viewer.clear_preview_marker()
                self._hide_dimension_overlay()
                return
            try:
                preview = self._sketch_preview_shape(self._sketch_session, uv)
            except ValueError:
                self._viewer.clear_preview_marker()
                self._sketch_session.drag_dimensions = None
                self._hide_dimension_overlay()
                self._refresh_hud()
                return
            if preview is None:
                return
            shape, hud_label, overlay_label = preview
            self._sketch_session.drag_dimensions = hud_label
            self._viewer.display_sketch_preview_marker(
                shape,
                self._workplane_normal_tuple(self._sketch_session.workplane),
            )
            self._show_dimension_overlay(overlay_label, x, y)
            self._refresh_hud()

        def _commit_sketch_drag(self, x: int, y: int) -> None:
            if self._sketch_session is None or self._sketch_session.start_uv is None:
                return
            session = self._sketch_session
            uv = self._screen_to_sketch_uv(x, y)
            if uv is None:
                session.start_uv = None
                session.drag_dimensions = None
                self._viewer.clear_preview_marker()
                self._hide_dimension_overlay()
                self._show_status("Sketch cancelled")
                return
            if not session.drag_moved:
                self._handle_sketch_click(session, uv, x, y)
                return
            try:
                profile = self._sketch_profile_from_uv(
                    session,
                    session.start_uv,
                    uv,
                )
            except ValueError:
                session.start_uv = None
                session.drag_dimensions = None
                self._viewer.clear_preview_marker()
                self._hide_dimension_overlay()
                self._show_status("Sketch too small")
                return
            item_id = self._add_sketch_profile(
                profile,
                self._sketch_profile_meta(
                    profile=session.tool,
                    workplane=session.label,
                ),
            )
            self._sketch_session = None
            self._viewer.clear_preview_marker()
            self._viewer.clear_sketch_plane_marker()
            self._hide_dimension_overlay()
            self._set_context_hint(
                "Closed profile ready - click inside it or press E to extrude"
            )
            self._show_status("Sketch profile created")
            LOGGER.info(
                "Sketch profile created item_id=%s tool=%s",
                item_id,
                session.tool,
            )

        def _screen_to_sketch_uv(
            self, x: int, y: int, snap: bool = False
        ) -> tuple[float, float] | None:
            if self._sketch_session is None:
                return None
            view_x, view_y = self._to_view_pixels(x, y)
            uv = project_screen_to_workplane(
                self._viewer.view,
                view_x,
                view_y,
                self._sketch_session.workplane,
            )
            if uv is not None and snap:
                uv = (round(uv[0] / 10.0) * 10.0, round(uv[1] / 10.0) * 10.0)
            return uv

        def _sketch_profile_from_uv(
            self,
            session: SketchSession,
            start_uv: tuple[float, float],
            end_uv: tuple[float, float],
        ):
            if session.tool in {"rectangle", "center_rectangle"}:
                return make_center_rectangle_profile(
                    session.workplane,
                    start_uv,
                    end_uv,
                )
            if session.tool == "rectangle_corners":
                return make_rectangle_profile_from_corners(
                    session.workplane,
                    start_uv,
                    end_uv,
                )
            if session.tool == "circle":
                radius = (
                    (end_uv[0] - start_uv[0]) ** 2 + (end_uv[1] - start_uv[1]) ** 2
                ) ** 0.5
                return make_circle_profile_at(session.workplane, start_uv, radius)
            raise ValueError(f"Unsupported sketch tool: {session.tool}")

        def _sketch_preview_shape(
            self,
            session: SketchSession,
            uv: tuple[float, float],
        ):
            if session.tool == "line":
                if not session.points:
                    return None
                points = [*session.points, uv]
                length = math.dist(session.points[-1], uv)
                return (
                    make_polyline_preview(session.workplane, points),
                    f"Length {length:.1f}",
                    f"Length: {length:.2f} mm",
                )
            if session.tool == "arc":
                if len(session.points) == 1:
                    length = math.dist(session.points[0], uv)
                    return (
                        make_polyline_preview(
                            session.workplane,
                            [session.points[0], uv],
                        ),
                        f"Arc base {length:.1f}",
                        f"Distance: {length:.2f} mm",
                    )
                if len(session.points) == 2:
                    radius = three_point_arc_radius(
                        session.points[0],
                        session.points[1],
                        uv,
                    )
                    return (
                        make_three_point_arc_edge(
                            session.workplane,
                            session.points[0],
                            session.points[1],
                            uv,
                        ),
                        f"Arc R {radius:.1f}",
                        f"Arc R: {radius:.2f} mm",
                    )
                return None
            if session.tool == "rectangle_3_point":
                if len(session.points) == 1:
                    length = math.dist(session.points[0], uv)
                    return (
                        make_polyline_preview(
                            session.workplane,
                            [session.points[0], uv],
                        ),
                        f"Base {length:.1f}",
                        f"Distance: {length:.2f} mm",
                    )
                if len(session.points) == 2:
                    profile = make_rectangle_profile_three_point(
                        session.workplane,
                        session.points[0],
                        session.points[1],
                        uv,
                    )
                    width = math.dist(session.points[0], session.points[1])
                    height = abs(
                        self._rectangle_three_point_height(
                            session.points[0],
                            session.points[1],
                            uv,
                        )
                    )
                    return (
                        profile,
                        f"{width:.1f} x {height:.1f}",
                        f"W: {width:.2f} mm, H: {height:.2f} mm",
                    )
                return None
            if session.start_uv is None:
                return None
            profile = self._sketch_profile_from_uv(session, session.start_uv, uv)
            hud_label = _sketch_dimension_label(session.tool, session.start_uv, uv)
            return (
                profile,
                hud_label,
                self._sketch_overlay_label(session.tool, session.start_uv, uv),
            )

        @staticmethod
        def _rectangle_three_point_height(
            first: tuple[float, float],
            second: tuple[float, float],
            third: tuple[float, float],
        ) -> float:
            base_x = second[0] - first[0]
            base_y = second[1] - first[1]
            base_length = math.hypot(base_x, base_y)
            if base_length < 1e-7:
                return 0.0
            normal_x = -base_y / base_length
            normal_y = base_x / base_length
            return (third[0] - first[0]) * normal_x + (third[1] - first[1]) * normal_y

        @staticmethod
        def _sketch_overlay_label(
            tool: str,
            start_uv: tuple[float, float],
            end_uv: tuple[float, float],
        ) -> str:
            if tool in {"center_rectangle", "rectangle"}:
                width = abs(end_uv[0] - start_uv[0]) * 2.0
                height = abs(end_uv[1] - start_uv[1]) * 2.0
                return f"W: {width:.2f} mm, H: {height:.2f} mm"
            if tool == "circle":
                radius = math.dist(start_uv, end_uv)
                return f"R: {radius:.2f} mm"
            return _sketch_dimension_label(tool, start_uv, end_uv)

        def _handle_sketch_click(
            self,
            session: SketchSession,
            uv: tuple[float, float],
            x: int,
            y: int,
        ) -> None:
            session.start_uv = None
            session.drag_start_screen = None
            session.drag_moved = False
            if session.tool == "line":
                self._handle_line_click(session, uv, x, y)
                return
            if session.tool == "arc":
                self._handle_arc_click(session, uv, x, y)
                return
            if session.tool == "rectangle_3_point":
                self._handle_rectangle_three_point_click(session, uv, x, y)
                return
            if session.tool in {"center_rectangle", "circle"}:
                self._handle_two_point_profile_click(session, uv, x, y)
                return
            self._show_status(f"Unsupported sketch tool: {session.tool}")

        def _handle_line_click(
            self,
            session: SketchSession,
            uv: tuple[float, float],
            x: int,
            y: int,
        ) -> None:
            if not session.points:
                session.points.append(uv)
                self._viewer.display_sketch_preview_marker(
                    make_point_marker_preview(session.workplane, uv),
                    self._workplane_normal_tuple(session.workplane),
                )
                self._show_dimension_overlay("Line start", x, y)
                self._set_context_hint("Line: click next point, Enter/Esc to finish")
                self._show_status("Line: next point")
                self._refresh_hud()
                return
            next_uv = self._closed_line_point(session.points, uv)
            if next_uv is None:
                next_uv = uv
            if math.dist(session.points[-1], next_uv) < 1e-7:
                return
            session.points.append(next_uv)
            if is_closed_polyline(session.points):
                self._commit_polyline_profile(session)
                return
            length = math.dist(session.points[-2], session.points[-1])
            self._viewer.display_sketch_preview_marker(
                make_polyline_preview(session.workplane, session.points),
                self._workplane_normal_tuple(session.workplane),
            )
            session.drag_dimensions = f"Length {length:.1f}"
            self._show_dimension_overlay(f"Length: {length:.2f} mm", x, y)
            self._set_context_hint(
                "Line segment added - click next point or close loop"
            )
            self._show_status("Line segment added")
            self._refresh_hud()

        @staticmethod
        def _closed_line_point(
            points: list[tuple[float, float]],
            uv: tuple[float, float],
            tolerance: float = 1.5,
        ) -> tuple[float, float] | None:
            if len(points) < 3:
                return None
            if math.dist(points[0], uv) <= tolerance:
                return points[0]
            return None

        def _commit_polyline_profile(self, session: SketchSession) -> None:
            try:
                profile = make_polyline_profile(session.workplane, session.points)
            except (CommandError, ValueError) as exc:
                LOGGER.warning("Polyline profile failed: %s", exc, exc_info=True)
                self._show_status("Polyline profile failed")
                return
            item_id = self._add_sketch_profile(
                profile,
                self._sketch_profile_meta(
                    profile="line_polyline",
                    segments=len(session.points) - 1,
                    workplane=session.label,
                ),
            )
            self._sketch_session = None
            self._viewer.clear_preview_marker()
            self._viewer.clear_sketch_plane_marker()
            self._hide_dimension_overlay()
            self._set_context_hint(
                "Closed profile ready - click inside it or press E to extrude"
            )
            self._show_status("Closed sketch profile created")
            LOGGER.info("Closed polyline profile created item_id=%s", item_id)

        def _handle_arc_click(
            self,
            session: SketchSession,
            uv: tuple[float, float],
            x: int,
            y: int,
        ) -> None:
            session.points.append(uv)
            if len(session.points) < 3:
                if len(session.points) == 1:
                    preview_shape = make_point_marker_preview(session.workplane, uv)
                else:
                    preview_shape = make_polyline_preview(
                        session.workplane,
                        session.points,
                    )
                self._viewer.display_sketch_preview_marker(
                    preview_shape,
                    self._workplane_normal_tuple(session.workplane),
                )
                self._show_dimension_overlay(f"Arc point {len(session.points)}", x, y)
                self._set_context_hint("Arc: set the next arc point")
                self._show_status("Arc: set next point")
                self._refresh_hud()
                return
            try:
                edge = make_three_point_arc_edge(
                    session.workplane,
                    session.points[0],
                    session.points[1],
                    session.points[2],
                )
                radius = three_point_arc_radius(
                    session.points[0],
                    session.points[1],
                    session.points[2],
                )
            except (CommandError, ValueError) as exc:
                LOGGER.warning("Arc failed: %s", exc, exc_info=True)
                session.points.clear()
                self._viewer.clear_preview_marker()
                self._hide_dimension_overlay()
                self._show_status("Arc failed")
                return
            item_id = self._add_sketch_entity(
                edge,
                self._sketch_profile_meta(
                    profile="arc",
                    radius=radius,
                    workplane=session.label,
                ),
            )
            session.points.clear()
            session.drag_dimensions = f"Arc R {radius:.1f}"
            self._show_dimension_overlay(f"Arc R: {radius:.2f} mm", x, y)
            self._set_context_hint(
                "Arc created - choose another sketch tool or continue"
            )
            self._show_status("Arc created")
            self._refresh_hud()
            LOGGER.info("Sketch arc entity created item_id=%s", item_id)

        def _handle_rectangle_three_point_click(
            self,
            session: SketchSession,
            uv: tuple[float, float],
            x: int,
            y: int,
        ) -> None:
            session.points.append(uv)
            if len(session.points) < 3:
                self._show_dimension_overlay(
                    f"Rectangle point {len(session.points)}",
                    x,
                    y,
                )
                self._set_context_hint("Rectangle 3 Point: set the next point")
                self._show_status("Rectangle 3 point: set next point")
                self._refresh_hud()
                return
            try:
                profile = make_rectangle_profile_three_point(
                    session.workplane,
                    session.points[0],
                    session.points[1],
                    session.points[2],
                )
            except (CommandError, ValueError) as exc:
                LOGGER.warning("3-point rectangle failed: %s", exc, exc_info=True)
                session.points.clear()
                self._viewer.clear_preview_marker()
                self._hide_dimension_overlay()
                self._show_status("Rectangle failed")
                return
            item_id = self._add_sketch_profile(
                profile,
                self._sketch_profile_meta(
                    profile="rectangle_3_point",
                    workplane=session.label,
                ),
            )
            self._sketch_session = None
            self._viewer.clear_preview_marker()
            self._viewer.clear_sketch_plane_marker()
            self._hide_dimension_overlay()
            self._set_context_hint(
                "Closed profile ready - click inside it or press E to extrude"
            )
            self._show_status("Rectangle sketch profile created")
            LOGGER.info("3-point rectangle profile created item_id=%s", item_id)

        def _handle_two_point_profile_click(
            self,
            session: SketchSession,
            uv: tuple[float, float],
            x: int,
            y: int,
        ) -> None:
            if not session.points:
                session.points.append(uv)
                self._show_dimension_overlay("Start point", x, y)
                self._set_context_hint("Move mouse to set size, then click to confirm")
                self._show_status(f"{session.tool}: set size")
                self._refresh_hud()
                return
            start_uv = session.points[0]
            try:
                profile = self._sketch_profile_from_uv(session, start_uv, uv)
            except (CommandError, ValueError) as exc:
                LOGGER.warning("Sketch profile failed: %s", exc, exc_info=True)
                session.points.clear()
                self._viewer.clear_preview_marker()
                self._hide_dimension_overlay()
                self._show_status("Sketch too small")
                return
            item_id = self._add_sketch_profile(
                profile,
                self._sketch_profile_meta(
                    profile=session.tool,
                    workplane=session.label,
                ),
            )
            self._sketch_session = None
            self._viewer.clear_preview_marker()
            self._viewer.clear_sketch_plane_marker()
            self._hide_dimension_overlay()
            self._set_context_hint(
                "Closed profile ready - click inside it or press E to extrude"
            )
            self._show_status("Sketch profile created")
            LOGGER.info(
                "Sketch profile created item_id=%s tool=%s",
                item_id,
                session.tool,
            )

        def _cancel_sketch_session(self) -> None:
            if self._sketch_session is None:
                return
            self._sketch_session = None
            self._viewer.clear_preview_marker()
            self._viewer.clear_sketch_plane_marker()
            self._hide_dimension_overlay()
            self._set_context_hint("Sketch cancelled")
            self._show_status("Sketch cancelled")
            self._refresh_hud()
            LOGGER.info("Sketch cancelled")

        def _finish_sketch_sequence(self) -> None:
            if self._sketch_session is None:
                return
            if self._sketch_session.points:
                self._sketch_session.points.clear()
                self._sketch_session.start_uv = None
                self._sketch_session.drag_dimensions = None
                self._viewer.clear_preview_marker()
                self._hide_dimension_overlay()
                self._show_status("Sketch sequence ended")
                self._refresh_hud()
                LOGGER.info("Sketch sequence ended")
                return
            self._cancel_sketch_session()

        def _set_world_xy_workplane(self) -> None:
            self._active_workplane = Workplane.world_xy()
            self._active_workplane_label = "XY"
            self._active_workplane_host = None
            self._show_status("Sketch workplane: XY")
            LOGGER.info("Sketch workplane set to world XY")

        def _set_workplane_from_selected_face(self) -> None:
            item_id, face_index = self._selected_face()
            if item_id is None or face_index is None:
                self._show_status("Select a planar face first")
                LOGGER.info("Sketch workplane ignored because no face is selected")
                return
            try:
                from OCP.TopoDS import TopoDS

                face = TopoDS.Face_s(
                    picker.subshape(item_id, SelectionKind.FACE, face_index)
                )
                self._active_workplane = Workplane.from_face(face)
            except (CommandError, IndexError, ValueError) as exc:
                LOGGER.warning(
                    "Sketch workplane from face failed item_id=%s face=%s: %s",
                    item_id,
                    face_index,
                    exc,
                    exc_info=True,
                )
                self._show_status("Planar face required")
                return
            self._active_workplane_label = f"face {face_index}"
            self._active_workplane_host = (item_id, face_index)
            self._show_status(f"Sketch workplane: face {face_index}")
            LOGGER.info(
                "Sketch workplane set from face item_id=%s face=%d",
                item_id,
                face_index,
            )

        def _add_rectangle_profile(self) -> None:
            try:
                profile = make_rectangle_profile(self._active_workplane)
            except (CommandError, ValueError) as exc:
                LOGGER.warning("Rectangle profile failed: %s", exc, exc_info=True)
                self._show_status("Rectangle profile failed")
                return
            item_id = self._add_sketch_profile(
                profile,
                self._sketch_profile_meta(
                    profile="rectangle",
                    width=60.0,
                    height=40.0,
                    workplane=self._active_workplane_label,
                ),
            )
            self._show_status("Rectangle sketch profile")
            LOGGER.info("Rectangle sketch profile added item_id=%s", item_id)

        def _add_circle_profile(self) -> None:
            try:
                profile = make_circle_profile(self._active_workplane)
            except (CommandError, ValueError) as exc:
                LOGGER.warning("Circle profile failed: %s", exc, exc_info=True)
                self._show_status("Circle profile failed")
                return
            item_id = self._add_sketch_profile(
                profile,
                self._sketch_profile_meta(
                    profile="circle",
                    radius=20.0,
                    workplane=self._active_workplane_label,
                ),
            )
            self._show_status("Circle sketch profile")
            LOGGER.info("Circle sketch profile added item_id=%s", item_id)

        def _sketch_profile_meta(self, **meta: object) -> dict[str, object]:
            meta = {
                "display_normal": self._workplane_normal_tuple(self._active_workplane),
                **meta,
            }
            if self._active_workplane_host is None:
                return {**meta, "sketch_mode": "independent"}
            host_item_id, host_face_index = self._active_workplane_host
            return {
                **meta,
                "sketch_mode": "feature",
                "host_item_id": host_item_id,
                "host_face_index": host_face_index,
            }

        @staticmethod
        def _workplane_normal_tuple(
            workplane: Workplane,
        ) -> tuple[float, float, float]:
            normal = workplane.normal
            return normal.X(), normal.Y(), normal.Z()

        def _add_sketch_profile(
            self,
            profile,
            meta: dict[str, object],
        ) -> str:
            profile_meta = {"kind": SKETCH_META_KIND, **meta}
            item_id = scene.add_shape(profile, meta=profile_meta)
            scene.set_active_item(item_id)
            scene.set_selection(
                SelectionRef(item_id=item_id, kind=SelectionKind.FACE, index=1)
            )
            self._selection_kind = SelectionKind.FACE
            self._hover_selection = None
            if self._viewer.is_initialized:
                self._viewer.set_selection_kind(SelectionKind.FACE)
                self._viewer.display_scene(scene, fit=False)
                self._viewer.display_selection_marker(profile, profile_meta)
            self._refresh_hud()
            return item_id

        def _add_sketch_entity(
            self,
            shape,
            meta: dict[str, object],
        ) -> str:
            item_id = scene.add_shape(
                shape,
                meta={"kind": SKETCH_ENTITY_META_KIND, **meta},
            )
            scene.set_active_item(item_id)
            scene.set_selection(None)
            self._hover_selection = None
            if self._viewer.is_initialized:
                self._viewer.display_scene(scene, fit=False)
                self._viewer.display_selection_marker(shape, scene.get(item_id).meta)
            self._refresh_hud()
            return item_id

        def _begin_sketch_extrude_tool(self) -> None:
            self._begin_sketch_profile_extrude_tool("auto")

        def _begin_sketch_new_body_tool(self) -> None:
            self._begin_sketch_profile_extrude_tool("new_body")

        def _begin_sketch_profile_extrude_tool(self, operation: str) -> None:
            selection = scene.selection()
            if selection is None:
                self._show_status("Select a sketch profile first")
                LOGGER.info("Sketch extrude ignored because nothing is selected")
                return
            if not is_sketch_profile(scene.get(selection.item_id).meta):
                self._show_status("Select a sketch profile first")
                LOGGER.info(
                    "Sketch extrude ignored for non-sketch item_id=%s",
                    selection.item_id,
                )
                return
            if selection.kind == SelectionKind.OBJECT:
                scene.set_selection(
                    SelectionRef(
                        item_id=selection.item_id,
                        kind=SelectionKind.FACE,
                        index=1,
                    )
                )
            self._begin_extrude_tool(sketch_operation=operation)

        def _apply_sketch_extrude(
            self,
            item_id: str,
            distance: float,
            *,
            new_body: bool = False,
        ):
            scene_object = scene.get(item_id)
            if not is_sketch_profile(scene_object.meta):
                raise CommandError("Selected item is not a sketch profile.")

            from OCP.TopoDS import TopoDS

            profile_face = TopoDS.Face_s(scene_object.shape)
            host_item_id = scene_object.meta.get("host_item_id")
            host_available = isinstance(host_item_id, str) and host_item_id in scene
            if host_available and not new_body:
                result = apply_profile_feature(
                    scene.get(host_item_id).shape,
                    profile_face,
                    distance,
                )
                with scene.transaction():
                    scene.replace_shape(
                        host_item_id,
                        result,
                        meta={
                            **scene.get(host_item_id).meta,
                            "last_sketch_feature": scene_object.meta.get("profile"),
                        },
                    )
                    scene.remove(item_id)
                    scene.set_active_item(host_item_id)
                return result

            result = extrude_profile(profile_face, distance)
            with scene.transaction():
                scene.replace_shape(
                    item_id,
                    result,
                    meta={
                        "kind": "body",
                        "source": ("sketch_new_body" if new_body else "sketch_extrude"),
                        "distance": distance,
                        "profile": scene_object.meta.get("profile"),
                    },
                )
                scene.set_active_item(item_id)
                scene.set_selection(
                    SelectionRef(
                        item_id=item_id,
                        kind=SelectionKind.OBJECT,
                        index=0,
                    )
                )
            if new_body and host_available:
                self._boolean_target_item_id = str(host_item_id)
                self._active_category = "transform"
            return result

        def _selected_face(self) -> tuple[str | None, int | None]:
            selection = scene.selection()
            if selection is not None and selection.kind == SelectionKind.FACE:
                return selection.item_id, selection.index
            return None, None

        def _selected_edge(self) -> tuple[str | None, int | None]:
            selection = scene.selection()
            if selection is None or selection.kind != SelectionKind.EDGE:
                return None, None
            return selection.item_id, selection.index

        def _begin_fillet_tool(self) -> None:
            item_id, edge_index = self._selected_edge()
            if item_id is None or edge_index is None:
                self._show_status("Select an edge first")
                return
            self._begin_edge_parameter_tool("fillet", item_id, edge_index)

        def _begin_chamfer_tool(self) -> None:
            item_id, edge_index = self._selected_edge()
            if item_id is None or edge_index is None:
                self._show_status("Select an edge first")
                return
            self._begin_edge_parameter_tool("chamfer", item_id, edge_index)

        def _begin_edge_parameter_tool(
            self,
            tool: str,
            item_id: str,
            edge_index: int,
        ) -> None:
            self._move_session = MoveSession(
                tool=tool,
                target_kind=SelectionKind.EDGE,
                item_id=item_id,
                index=edge_index,
                axis_name="Parameter",
                axis=(0.0, 0.0, 1.0),
                distance=DEFAULT_EDGE_PARAMETER,
            )
            self._viewer.clear_preview_marker()
            self._update_move_preview()
            self._show_dimension_overlay(
                self._move_overlay_label(self._move_session),
                self.width() // 2,
                self.height() // 2,
            )
            action_name = "Fillet" if tool == "fillet" else "Chamfer"
            self._set_context_hint(
                f"{action_name}: drag to set value, Enter apply, Esc cancel"
            )
            self._show_status(f"{action_name}: drag value")
            self._refresh_hud()
            LOGGER.info("%s tool started item_id=%s edge=%d", tool, item_id, edge_index)

        def _move_selected(self, distance: float) -> None:
            selection = scene.selection()
            if selection is None:
                self._show_status("Select topology first")
                LOGGER.info("Move selected ignored because nothing is selected")
                return
            if selection.kind == SelectionKind.FACE:
                self._move_selected_face(distance)
                return
            if selection.kind == SelectionKind.EDGE:
                self._move_selected_edge(selection.item_id, selection.index, distance)
                return
            if selection.kind == SelectionKind.VERTEX:
                self._move_selected_vertex(selection.item_id, selection.index, distance)

        def _begin_object_move_tool(self) -> None:
            self._begin_object_move_tool_on_axis(
                "View",
                (0.0, 0.0, 0.0),
            )

        def _begin_object_move_tool_on_axis(
            self,
            axis_name: str,
            axis: tuple[float, float, float],
        ) -> None:
            selection = scene.selection()
            if selection is not None and selection.kind != SelectionKind.OBJECT:
                self._show_status("Use Modify tools for selected topology")
                LOGGER.info(
                    "Object move ignored because %s is selected",
                    selection.kind.value,
                )
                return
            item_id = (
                selection.item_id if selection is not None else scene.active_item_id()
            )
            if item_id is None:
                self._show_status("No active object")
                return
            if item_id not in scene or is_sketch_object(scene.get(item_id).meta):
                self._show_status("Select a body first")
                return
            self._move_session = MoveSession(
                tool="move",
                target_kind="object",
                item_id=item_id,
                index=None,
                axis_name=axis_name,
                axis=axis,
            )
            self._viewer.clear_preview_marker()
            if axis_name == "View":
                self._show_status("Move body: drag in view, Enter apply, Esc cancel")
            else:
                self._show_status(
                    f"Move object {axis_name}: drag, Enter apply, Esc cancel"
                )
            self._refresh_hud()
            LOGGER.info(
                "Move tool started for object item_id=%s axis=%s",
                item_id,
                axis_name,
            )

        def _begin_object_rotate_tool(self) -> None:
            selection = scene.selection()
            if selection is not None and selection.kind != SelectionKind.OBJECT:
                self._show_status("Select a body to rotate")
                return
            item_id = (
                selection.item_id if selection is not None else scene.active_item_id()
            )
            if item_id is None:
                self._show_status("Select a body first")
                return
            if item_id not in scene or is_sketch_object(scene.get(item_id).meta):
                self._show_status("Select a body first")
                return
            self._move_session = MoveSession(
                tool="rotate",
                target_kind="object",
                item_id=item_id,
                index=None,
                axis_name=self._move_axis_name,
                axis=self._move_axis,
            )
            self._viewer.clear_preview_marker()
            self._show_dimension_overlay(
                self._move_overlay_label(self._move_session),
                self.width() // 2,
                self.height() // 2,
            )
            self._set_context_hint("Rotate: drag to set angle, Enter apply, Esc cancel")
            self._show_status(f"Rotate body {self._move_axis_name}: drag angle")
            self._refresh_hud()
            LOGGER.info(
                "Rotate tool started item_id=%s axis=%s",
                item_id,
                self._move_axis_name,
            )

        def _begin_selected_move_tool(self) -> None:
            self._begin_selected_move_tool_on_axis(
                "View",
                (0.0, 0.0, 0.0),
            )

        def _begin_selected_move_tool_on_axis(
            self,
            axis_name: str,
            axis: tuple[float, float, float],
        ) -> None:
            selection = scene.selection()
            if selection is None:
                self._show_status("Select topology first")
                LOGGER.info("Move tool ignored because nothing is selected")
                return
            if selection.kind == SelectionKind.OBJECT:
                self._begin_object_move_tool_on_axis(axis_name, axis)
                return
            if selection.kind == SelectionKind.FACE:
                axis_name = "Normal" if axis_name == "Normal" else axis_name
            if axis_name != "Normal" and not self._selection_supports_view_move(
                selection
            ):
                self._show_status(
                    f"Move {selection.kind.value} unavailable for curved topology"
                )
                self._set_context_hint(
                    "This local move is available only on planar-faced solids"
                )
                LOGGER.info(
                    "Move tool blocked kind=%s item_id=%s index=%s: "
                    "unsupported topology",
                    selection.kind.value,
                    selection.item_id,
                    selection.index,
                )
                return
            self._move_session = MoveSession(
                tool="move",
                target_kind=selection.kind,
                item_id=selection.item_id,
                index=selection.index,
                axis_name=axis_name,
                axis=axis,
            )
            self._viewer.clear_preview_marker()
            if axis_name == "View":
                self._show_status(
                    f"Move {selection.kind.value}: drag in view, "
                    "Enter apply, Esc cancel"
                )
            else:
                self._show_status(
                    f"Move {selection.kind.value} {axis_name}: "
                    "drag, Enter apply, Esc cancel"
                )
            self._refresh_hud()
            LOGGER.info(
                "Move tool started kind=%s item_id=%s index=%s axis=%s",
                selection.kind.value,
                selection.item_id,
                selection.index,
                axis_name,
            )

        def _selection_supports_view_move(self, selection: SelectionRef | None) -> bool:
            if selection is None or selection.kind == SelectionKind.OBJECT:
                return False
            scene_object = scene.get(selection.item_id)
            if is_sketch_profile(scene_object.meta):
                return False
            if selection.kind == SelectionKind.FACE:
                return supports_move_face_controlled(
                    scene_object.shape,
                    selection.index,
                )
            if selection.kind == SelectionKind.EDGE:
                return supports_move_edge_controlled(
                    scene_object.shape,
                    selection.index,
                )
            if selection.kind == SelectionKind.VERTEX:
                return supports_move_vertex_controlled(
                    scene_object.shape,
                    selection.index,
                )
            return False

        def _begin_selected_move_normal_tool(self) -> None:
            selection = scene.selection()
            if selection is None or selection.kind != SelectionKind.FACE:
                self._show_status("Select a face first")
                return
            try:
                axis_name = "Normal"
                axis = self._face_normal(selection.item_id, selection.index)
            except (CommandError, IndexError, ValueError) as exc:
                LOGGER.warning(
                    "Face normal move failed to start item_id=%s face=%s: %s",
                    selection.item_id,
                    selection.index,
                    exc,
                    exc_info=True,
                )
                self._show_status("Face normal unavailable")
                return
            self._begin_selected_move_tool_on_axis(axis_name, axis)

        def _begin_context_move_tool(self) -> None:
            selection = scene.selection()
            if selection is not None and selection.kind != SelectionKind.OBJECT:
                self._begin_selected_move_tool_on_axis(
                    "View",
                    (0.0, 0.0, 0.0),
                )
                return
            self._begin_object_move_tool_on_axis(
                "View",
                (0.0, 0.0, 0.0),
            )

        def _begin_extrude_tool(self, sketch_operation: str = "auto") -> None:
            item_id, face_index = self._selected_face()
            if item_id is None or face_index is None:
                self._show_status("Select a face first")
                LOGGER.info("Extrude tool ignored because no face is selected")
                return
            is_profile = is_sketch_profile(scene.get(item_id).meta)
            axis = self._face_normal(item_id, face_index)
            self._move_session = MoveSession(
                tool="sketch_extrude" if is_profile else "extrude",
                target_kind=SelectionKind.FACE,
                item_id=item_id,
                index=face_index,
                axis_name="Normal",
                axis=axis,
                operation=sketch_operation if is_profile else "auto",
            )
            self._viewer.clear_preview_marker()
            if is_profile and sketch_operation == "new_body":
                self._set_context_hint(
                    "Drag arrow to create a separate body, Enter accept, Esc cancel"
                )
                self._show_status("New body: drag arrow, Enter apply, Esc cancel")
            elif is_profile:
                self._set_context_hint(
                    "Drag arrow to extrude, Enter accept, Esc cancel"
                )
                self._show_status("Sketch extrude: drag arrow, Enter apply, Esc cancel")
            else:
                self._set_context_hint(
                    "Drag arrow to push/pull face, Enter accept, Esc cancel"
                )
                self._show_status("Extrude: drag arrow, Enter apply, Esc cancel")
            self._show_dimension_overlay(
                self._move_overlay_label(self._move_session),
                self.width() // 2,
                self.height() // 2,
            )
            self._update_extrude_affordance()
            self._refresh_hud()
            LOGGER.info(
                "%s tool started item_id=%s face=%s",
                "Sketch extrude" if is_profile else "Extrude",
                item_id,
                face_index,
            )

        def _begin_move_drag(self, x: int, y: int) -> None:
            if self._move_session is None:
                return
            self._move_session.drag_start = (x, y)
            self._move_session.drag_origin_distance = self._move_session.distance
            self._move_session.drag_origin_vector = self._move_session.vector or (
                0.0,
                0.0,
                0.0,
            )
            self._move_session.drag_screen_axis = self._screen_axis_for_session(
                self._move_session
            )
            self._begin_view_drag(self._move_session, x, y)
            self._show_dimension_overlay(
                self._move_overlay_label(self._move_session),
                x,
                y,
            )
            if self._move_session.tool in {"extrude", "sketch_extrude"}:
                self._set_context_hint(
                    "Drag arrow to set height, Enter accept, Esc cancel"
                )
                self._update_extrude_affordance()
                self._show_status("Extrude preview")
            elif self._move_session.tool == "rotate":
                self._show_status("Rotate preview")
            elif self._move_session.tool in {"fillet", "chamfer"}:
                self._show_status(f"{self._move_session.tool.title()} preview")
            else:
                self._show_status("Move preview")

        def _drag_move_to(
            self, x: int, y: int, fine: bool = False, snap: bool = False
        ) -> None:
            if self._move_session is None or self._move_session.drag_start is None:
                return
            if self._move_session.axis_name == "View":
                vector_delta = self._view_drag_delta(self._move_session, x, y)
                if vector_delta is None:
                    return
                if fine:
                    vector_delta = tuple(component * 0.25 for component in vector_delta)
                self._move_session.vector = tuple(
                    origin_component + delta_component
                    for origin_component, delta_component in zip(
                        self._move_session.drag_origin_vector,
                        vector_delta,
                    )
                )
                self._move_session.distance = math.sqrt(
                    sum(
                        component * component for component in self._move_session.vector
                    )
                )
                if snap:
                    snapped = tuple(
                        round(c / 10.0) * 10.0 for c in self._move_session.vector
                    )
                    self._move_session.vector = snapped
                    self._move_session.distance = math.sqrt(sum(c * c for c in snapped))
                self._update_move_preview()
                self._show_dimension_overlay(
                    self._move_overlay_label(self._move_session),
                    x,
                    y,
                )
                self._refresh_hud()
                return
            scale = self._move_pixels_to_units * (0.25 if fine else 1.0)
            dx = x - self._move_session.drag_start[0]
            dy = y - self._move_session.drag_start[1]
            delta = _drag_distance_delta(
                dx,
                dy,
                scale,
                self._move_session.drag_screen_axis,
            )
            self._move_session.distance = (
                self._move_session.drag_origin_distance + delta
            )
            if self._move_session.tool in {"fillet", "chamfer"}:
                self._move_session.distance = max(0.0, self._move_session.distance)
            if snap:
                self._move_session.distance = (
                    round(self._move_session.distance / 10.0) * 10.0
                )
            self._update_move_preview()
            self._update_extrude_affordance()
            self._show_dimension_overlay(
                self._move_overlay_label(self._move_session),
                x,
                y,
            )
            self._refresh_hud()

        def _begin_view_drag(self, session: MoveSession, x: int, y: int) -> None:
            if session.axis_name != "View" or not self._viewer.is_initialized:
                return
            ray = self._view_ray_at(x, y)
            anchor = self._move_anchor_point(session)
            if ray is None or anchor is None:
                return
            origin, direction = ray
            start_point = self._ray_plane_intersection(
                origin,
                direction,
                anchor,
                direction,
            )
            if start_point is None:
                return
            session.drag_view_anchor = anchor
            session.drag_view_normal = direction
            session.drag_view_start_point = start_point

        def _view_drag_delta(
            self,
            session: MoveSession,
            x: int,
            y: int,
        ) -> tuple[float, float, float] | None:
            if (
                session.drag_view_anchor is None
                or session.drag_view_normal is None
                or session.drag_view_start_point is None
            ):
                return None
            ray = self._view_ray_at(x, y)
            if ray is None:
                return None
            origin, direction = ray
            current_point = self._ray_plane_intersection(
                origin,
                direction,
                session.drag_view_anchor,
                session.drag_view_normal,
            )
            if current_point is None:
                return None
            return tuple(
                current_component - start_component
                for current_component, start_component in zip(
                    current_point,
                    session.drag_view_start_point,
                )
            )

        def _view_ray_at(
            self,
            x: int,
            y: int,
        ) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
            view_x, view_y = self._to_view_pixels(x, y)
            ray = picker._view_ray(self._viewer.view, view_x, view_y)
            if ray is None:
                return None
            origin, direction, _eye = ray
            return origin, direction

        @staticmethod
        def _ray_plane_intersection(
            ray_origin: tuple[float, float, float],
            ray_direction: tuple[float, float, float],
            plane_point: tuple[float, float, float],
            plane_normal: tuple[float, float, float],
        ) -> tuple[float, float, float] | None:
            denominator = sum(
                direction_component * normal_component
                for direction_component, normal_component in zip(
                    ray_direction,
                    plane_normal,
                )
            )
            if abs(denominator) < 1e-7:
                return None
            distance = (
                sum(
                    (plane_component - origin_component) * normal_component
                    for plane_component, origin_component, normal_component in zip(
                        plane_point,
                        ray_origin,
                        plane_normal,
                    )
                )
                / denominator
            )
            return tuple(
                origin_component + direction_component * distance
                for origin_component, direction_component in zip(
                    ray_origin,
                    ray_direction,
                )
            )

        def _screen_axis_for_session(
            self,
            session: MoveSession,
        ) -> tuple[float, float] | None:
            if session.tool in {"fillet", "chamfer"}:
                return EXTRUDE_DRAG_FALLBACK_AXIS
            if session.tool == "rotate":
                return ROTATE_DRAG_FALLBACK_AXIS
            if session.tool not in {"extrude", "sketch_extrude"}:
                return None
            if not self._viewer.is_initialized or session.index is None:
                return EXTRUDE_DRAG_FALLBACK_AXIS
            try:
                center = self._face_center(session.item_id, session.index)
                start_x, start_y = self._viewer.view.Convert(*center)
                end = (
                    center[0] + session.axis[0] * EXTRUDE_DRAG_PROBE_DISTANCE,
                    center[1] + session.axis[1] * EXTRUDE_DRAG_PROBE_DISTANCE,
                    center[2] + session.axis[2] * EXTRUDE_DRAG_PROBE_DISTANCE,
                )
                end_x, end_y = self._viewer.view.Convert(*end)
            except (CommandError, IndexError, RuntimeError, ValueError) as exc:
                LOGGER.debug(
                    "Extrude drag axis projection failed: %s",
                    exc,
                    exc_info=True,
                )
                return EXTRUDE_DRAG_FALLBACK_AXIS
            return (
                _normalize_screen_axis(end_x - start_x, end_y - start_y)
                or EXTRUDE_DRAG_FALLBACK_AXIS
            )

        def _update_extrude_affordance(self) -> None:
            session = self._move_session
            if (
                session is None
                or session.tool not in {"extrude", "sketch_extrude"}
                or session.index is None
                or not self._viewer.is_initialized
            ):
                self._viewer.clear_extrude_affordance_marker()
                return
            try:
                center = self._face_center(session.item_id, session.index)
            except (CommandError, IndexError, RuntimeError, ValueError) as exc:
                LOGGER.debug("Extrude affordance failed: %s", exc, exc_info=True)
                self._viewer.clear_extrude_affordance_marker()
                return
            sign = -1.0 if session.distance < 0 else 1.0
            direction = tuple(component * sign for component in session.axis)
            length = max(25.0, min(55.0, 35.0 + abs(session.distance) * 0.15))
            self._viewer.display_extrude_affordance(center, direction, length)

        def _face_center(
            self,
            item_id: str,
            face_index: int,
        ) -> tuple[float, float, float]:
            from OCP.BRepGProp import BRepGProp
            from OCP.GProp import GProp_GProps
            from OCP.TopoDS import TopoDS

            face = TopoDS.Face_s(
                picker.subshape(item_id, SelectionKind.FACE, face_index)
            )
            props = GProp_GProps()
            BRepGProp.SurfaceProperties_s(face, props)
            point = props.CentreOfMass()
            return point.X(), point.Y(), point.Z()

        def _move_anchor_point(
            self,
            session: MoveSession,
        ) -> tuple[float, float, float] | None:
            if session.target_kind == "object":
                return self._shape_center(scene.get(session.item_id).shape)
            if session.index is None:
                return None
            if session.target_kind == SelectionKind.FACE:
                return self._face_center(session.item_id, session.index)
            shape = picker.subshape(
                session.item_id,
                SelectionKind(session.target_kind),
                session.index,
            )
            return self._shape_center(shape)

        @staticmethod
        def _shape_center(shape) -> tuple[float, float, float] | None:
            from OCP.Bnd import Bnd_Box
            from OCP.BRepBndLib import BRepBndLib

            bounds = Bnd_Box()
            BRepBndLib.Add_s(shape, bounds)
            if bounds.IsVoid():
                return None
            x_min, y_min, z_min, x_max, y_max, z_max = bounds.Get()
            return (
                (x_min + x_max) * 0.5,
                (y_min + y_max) * 0.5,
                (z_min + z_max) * 0.5,
            )

        def _update_move_preview(self) -> None:
            if self._move_session is None:
                return
            distance = self._move_session.distance
            if abs(distance) < 1e-7:
                self._viewer.clear_preview_marker()
                return
            try:
                preview = self._move_preview_shape(self._move_session)
            except (CommandError, IndexError, ValueError) as exc:
                LOGGER.debug("Move preview failed: %s", exc, exc_info=True)
                self._viewer.clear_preview_marker()
                return
            hide_original = self._move_session.tool in {
                "extrude",
                "sketch_extrude",
                "fillet",
                "chamfer",
                "rotate",
            } or (
                self._move_session.tool == "move"
                and self._move_session.target_kind == "object"
            )
            LOGGER.debug(
                "Move preview: tool=%s target=%s hide_original=%s "
                "item_id=%s distance=%.2f",
                self._move_session.tool,
                self._move_session.target_kind,
                hide_original,
                self._move_session.item_id,
                self._move_session.distance,
            )
            self._viewer.display_preview_marker(
                preview,
                hide_item_id=(self._move_session.item_id if hide_original else None),
            )

        @staticmethod
        def _move_overlay_label(session: MoveSession) -> str:
            if session.tool == "sketch_extrude" and session.operation == "new_body":
                return f"New Body {session.distance:.2f} mm"
            if session.tool in {"extrude", "sketch_extrude"}:
                return f"Extrude {session.distance:.2f} mm"
            if session.tool == "rotate":
                return f"Rotate {session.axis_name}: {session.distance:.2f} deg"
            if session.tool == "fillet":
                return f"Fillet R {session.distance:.2f} mm"
            if session.tool == "chamfer":
                return f"Chamfer {session.distance:.2f} mm"
            if session.axis_name == "View":
                return f"Move {session.distance:.2f} mm"
            if session.axis_name in {"X", "Y", "Z"}:
                return f"d{session.axis_name}: {session.distance:.2f} mm"
            return f"Distance: {session.distance:.2f} mm"

        def _move_preview_shape(self, session: MoveSession):
            if session.tool == "sketch_extrude":
                from OCP.TopoDS import TopoDS

                return extrude_profile(
                    TopoDS.Face_s(scene.get(session.item_id).shape),
                    session.distance,
                )
            if session.tool == "extrude":
                return extrude_face(
                    scene.get(session.item_id).shape,
                    session.index,
                    session.distance,
                )
            if session.tool == "rotate":
                center = self._shape_center(scene.get(session.item_id).shape)
                if center is None:
                    raise CommandError("Rotate center unavailable.")
                return rotated_shape(
                    scene.get(session.item_id).shape,
                    center,
                    session.axis,
                    session.distance,
                )
            if session.tool == "fillet":
                return fillet_edge(
                    scene.get(session.item_id).shape,
                    session.index,
                    session.distance,
                )
            if session.tool == "chamfer":
                return chamfer_edge(
                    scene.get(session.item_id).shape,
                    session.index,
                    session.distance,
                )
            dx, dy, dz = self._move_vector(session)
            if session.target_kind == "object":
                shape = scene.get(session.item_id).shape
            else:
                shape = picker.subshape(
                    session.item_id,
                    SelectionKind(session.target_kind),
                    session.index,
                )
            return translated_shape(shape, dx, dy, dz)

        def _move_vector(self, session: MoveSession) -> tuple[float, float, float]:
            if session.vector is not None:
                return session.vector
            return (
                session.axis[0] * session.distance,
                session.axis[1] * session.distance,
                session.axis[2] * session.distance,
            )

        def _commit_move_session(self) -> None:
            session = self._move_session
            if session is None:
                return
            if abs(session.distance) < 1e-7:
                self._cancel_move_session(
                    status=f"{self._move_tool_name(session)} cancelled"
                )
                return
            LOGGER.debug(
                "Apply move session: tool=%s target=%s item_id=%s "
                "index=%s distance=%.2f axis=%s vector=%s",
                session.tool,
                session.target_kind,
                session.item_id,
                session.index,
                session.distance,
                session.axis_name,
                session.vector,
            )
            try:
                self._apply_move_session(session)
            except (CommandError, IndexError, ValueError) as exc:
                LOGGER.warning(
                    "%s tool failed kind=%s item_id=%s index=%s distance=%.2f: %s",
                    session.tool.title(),
                    session.target_kind,
                    session.item_id,
                    session.index,
                    session.distance,
                    exc,
                    exc_info=True,
                )
                self._cancel_move_session(
                    status=f"{self._move_tool_name(session)} failed"
                )
                return
            self._move_session = None
            scene.set_selection(None)
            self._hover_selection = None
            self._viewer.clear_preview_marker()
            self._hide_dimension_overlay()
            self._viewer.clear_extrude_affordance_marker()
            if self._viewer.is_initialized:
                self._viewer.display_scene(scene, fit=False)
            if (
                session.tool == "sketch_extrude"
                and session.operation == "new_body"
                and self._valid_boolean_target_item_id() is not None
            ):
                self._set_context_hint(
                    "New body created. Boolean target is set; choose Union, "
                    "Subtract, or Intersect."
                )
            else:
                self._set_context_hint("Operation applied")
            self._show_status(f"{self._move_tool_name(session)} applied")
            LOGGER.info(
                "%s tool applied kind=%s item_id=%s index=%s distance=%.2f axis=%s",
                self._move_tool_name(session),
                session.target_kind,
                session.item_id,
                session.index,
                session.distance,
                session.axis_name,
            )

        @staticmethod
        def _move_tool_name(session: MoveSession) -> str:
            if session.tool == "sketch_extrude":
                return "Sketch Extrude"
            return session.tool.replace("_", " ").title()

        def _apply_move_session(self, session: MoveSession) -> None:
            if session.tool == "sketch_extrude":
                self._apply_sketch_extrude(
                    session.item_id,
                    session.distance,
                    new_body=session.operation == "new_body",
                )
                return
            if session.tool == "extrude":
                apply_extrude_face(
                    scene,
                    session.item_id,
                    session.index,
                    session.distance,
                )
                return
            if session.tool == "rotate":
                center = self._shape_center(scene.get(session.item_id).shape)
                if center is None:
                    raise CommandError("Rotate center unavailable.")
                apply_rotate_object(
                    scene,
                    session.item_id,
                    center,
                    session.axis,
                    session.distance,
                )
                return
            if session.tool == "fillet":
                apply_fillet_edge(
                    scene,
                    session.item_id,
                    session.index,
                    radius=session.distance,
                )
                return
            if session.tool == "chamfer":
                apply_chamfer_edge(
                    scene,
                    session.item_id,
                    session.index,
                    distance=session.distance,
                )
                return
            if session.target_kind == "object":
                dx, dy, dz = self._move_vector(session)
                apply_move_object(scene, session.item_id, dx, dy, dz)
                return
            if session.target_kind == SelectionKind.FACE:
                if session.axis_name == "Normal":
                    apply_move_face_normal(
                        scene,
                        session.item_id,
                        session.index,
                        session.distance,
                    )
                else:
                    dx, dy, dz = self._move_vector(session)
                    apply_move_face_controlled(
                        scene,
                        session.item_id,
                        session.index,
                        dx,
                        dy,
                        dz,
                    )
                return
            dx, dy, dz = self._move_vector(session)
            if session.target_kind == SelectionKind.EDGE:
                apply_move_edge_controlled(
                    scene,
                    session.item_id,
                    session.index,
                    dx,
                    dy,
                    dz,
                )
                return
            if session.target_kind == SelectionKind.VERTEX:
                apply_move_vertex_controlled(
                    scene,
                    session.item_id,
                    session.index,
                    dx,
                    dy,
                    dz,
                )
                return
            raise ValueError(f"Unsupported move target: {session.target_kind}")

        def _cancel_move_session(self, status: str = "Move cancelled") -> None:
            if self._move_session is None:
                return
            self._move_session = None
            self._viewer.clear_preview_marker()
            self._hide_dimension_overlay()
            self._viewer.clear_extrude_affordance_marker()
            self._show_status(status)
            self._refresh_hud()

        def _cancel_active_tool(self) -> None:
            if self._sketch_session is not None:
                self._cancel_sketch_session()
                return
            self._cancel_move_session()

        def _face_normal(
            self,
            item_id: str,
            face_index: int,
        ) -> tuple[float, float, float]:
            return face_normal_vector(scene.get(item_id).shape, face_index)

        def _move_active_object(self, distance: float) -> None:
            item_id = scene.active_item_id()
            if item_id is None:
                return
            dx, dy, dz = self._scaled_move_axis(distance)
            try:
                apply_move_object(scene, item_id, dx, dy, dz)
            except (CommandError, IndexError, ValueError) as exc:
                LOGGER.warning(
                    "Move object failed item_id=%s vector=(%.2f,%.2f,%.2f): %s",
                    item_id,
                    dx,
                    dy,
                    dz,
                    exc,
                    exc_info=True,
                )
                self._show_status("Move object failed")
                return
            scene.set_selection(None)
            self._hover_selection = None
            self._viewer.display_scene(scene, fit=False)
            self._show_status(f"Object moved {self._move_axis_name}")
            LOGGER.info(
                "Move object applied item_id=%s vector=(%.2f,%.2f,%.2f)",
                item_id,
                dx,
                dy,
                dz,
            )

        def _move_selected_face(self, distance: float) -> None:
            item_id, face_index = self._selected_face()
            if item_id is None or face_index is None:
                self._show_status("Select a face first")
                LOGGER.info("Move face ignored because no face is selected")
                return
            try:
                apply_move_face_normal(scene, item_id, face_index, distance)
            except (CommandError, IndexError, ValueError) as exc:
                LOGGER.warning(
                    "Move face failed item_id=%s face=%s distance=%.2f: %s",
                    item_id,
                    face_index,
                    distance,
                    exc,
                    exc_info=True,
                )
                self._show_status("Move face failed")
                return
            scene.set_selection(None)
            self._hover_selection = None
            self._viewer.display_scene(scene, fit=False)
            self._show_status("Move face applied")
            LOGGER.info(
                "Move face applied item_id=%s face=%d distance=%.2f",
                item_id,
                face_index,
                distance,
            )

        def _move_selected_edge(
            self,
            item_id: str,
            edge_index: int,
            distance: float,
        ) -> None:
            dx, dy, dz = self._scaled_move_axis(distance)
            try:
                apply_move_edge_controlled(scene, item_id, edge_index, dx, dy, dz)
            except (CommandError, IndexError, ValueError) as exc:
                LOGGER.warning(
                    "Move edge failed item_id=%s edge=%s vector=(%.2f,%.2f,%.2f): %s",
                    item_id,
                    edge_index,
                    dx,
                    dy,
                    dz,
                    exc,
                    exc_info=True,
                )
                self._show_status("Move edge failed")
                return
            scene.set_selection(None)
            self._hover_selection = None
            self._viewer.display_scene(scene, fit=False)
            self._show_status(f"Edge moved {self._move_axis_name}")
            LOGGER.info(
                "Move edge applied item_id=%s edge=%d vector=(%.2f,%.2f,%.2f)",
                item_id,
                edge_index,
                dx,
                dy,
                dz,
            )

        def _move_selected_vertex(
            self,
            item_id: str,
            vertex_index: int,
            distance: float,
        ) -> None:
            dx, dy, dz = self._scaled_move_axis(distance)
            try:
                apply_move_vertex_controlled(
                    scene,
                    item_id,
                    vertex_index,
                    dx,
                    dy,
                    dz,
                )
            except (CommandError, IndexError, ValueError) as exc:
                LOGGER.warning(
                    "Move vertex failed item_id=%s vertex=%s "
                    "vector=(%.2f,%.2f,%.2f): %s",
                    item_id,
                    vertex_index,
                    dx,
                    dy,
                    dz,
                    exc,
                    exc_info=True,
                )
                self._show_status("Move vertex failed")
                return
            scene.set_selection(None)
            self._hover_selection = None
            self._viewer.display_scene(scene, fit=False)
            self._show_status(f"Vertex moved {self._move_axis_name}")
            LOGGER.info(
                "Move vertex applied item_id=%s vertex=%d vector=(%.2f,%.2f,%.2f)",
                item_id,
                vertex_index,
                dx,
                dy,
                dz,
            )

        def _scaled_move_axis(self, distance: float) -> tuple[float, float, float]:
            return (
                self._move_axis[0] * distance,
                self._move_axis[1] * distance,
                self._move_axis[2] * distance,
            )

        def _set_move_axis(
            self,
            name: str,
            axis: tuple[float, float, float],
        ) -> None:
            self._move_axis_name = name
            self._move_axis = axis
            self._show_status(f"Move axis: {name}")
            self._refresh_hud()
            self._refresh_action_state()
            LOGGER.info("Move axis set to %s", name)

        def _set_selection_kind(self, kind: SelectionKind) -> None:
            self._selection_kind = kind
            self._hover_selection = None
            scene.set_selection(None)
            if self._viewer.is_initialized:
                self._viewer.set_selection_kind(kind)
            self._show_status(f"Selection: {kind.value}")
            self._refresh_hud()
            self._refresh_action_state()
            LOGGER.info("UI selection mode set to %s", kind.value)

        def _undo(self) -> None:
            if scene.undo() is None:
                LOGGER.info("Undo requested but stack is empty")
                return
            self._hover_selection = None
            if self._viewer.is_initialized:
                self._viewer.display_scene(scene, fit=False)
            self._show_status("Undo")
            LOGGER.info("Undo applied")

        def _redo(self) -> None:
            if scene.redo() is None:
                LOGGER.info("Redo requested but stack is empty")
                return
            self._hover_selection = None
            if self._viewer.is_initialized:
                self._viewer.display_scene(scene, fit=False)
            self._show_status("Redo")
            LOGGER.info("Redo applied")

        def _delete_active_object(self) -> None:
            if self._move_session is not None or self._sketch_session is not None:
                self._show_status("Cancel active tool before deleting")
                return
            selection = scene.selection()
            if selection is not None and selection.kind != SelectionKind.OBJECT:
                self._show_status("Select an object to delete")
                LOGGER.info(
                    "Delete object blocked because %s is selected",
                    selection.kind.value,
                )
                return
            item_id = (
                selection.item_id if selection is not None else scene.active_item_id()
            )
            if item_id is None:
                self._show_status("No active object")
                return
            if is_sketch_object(scene.get(item_id).meta):
                self._show_status("Select a body to delete")
                return
            scene.remove(item_id)
            self._hover_selection = None
            if self._viewer.is_initialized:
                self._viewer.display_scene(scene, fit=False)
            self._show_status("Object deleted")
            LOGGER.info("Object deleted item_id=%s", item_id)

        def _set_boolean_target_from_context(self) -> None:
            item_id = self._selected_or_active_body_item_id()
            if item_id is None:
                self._show_status("Select a body first")
                return
            self._boolean_target_item_id = item_id
            self._show_status("Boolean target set")
            self._refresh_action_state()
            LOGGER.info("Boolean target set item_id=%s", item_id)

        def _clear_boolean_target(self) -> None:
            self._boolean_target_item_id = None
            self._show_status("Boolean target cleared")
            self._refresh_action_state()

        def _apply_boolean_tool(self, operation: str) -> None:
            target_item_id = self._valid_boolean_target_item_id()
            tool_item_id = self._selected_or_active_body_item_id()
            if target_item_id is None:
                self._show_status("Set boolean target first")
                return
            if tool_item_id is None or tool_item_id == target_item_id:
                self._show_status("Select a second body")
                return
            try:
                apply_boolean_bodies(scene, target_item_id, tool_item_id, operation)
            except (CommandError, KeyError, ValueError) as exc:
                LOGGER.warning(
                    "Boolean %s failed target=%s tool=%s: %s",
                    operation,
                    target_item_id,
                    tool_item_id,
                    exc,
                    exc_info=True,
                )
                self._show_status(f"Boolean {operation} failed")
                return
            self._boolean_target_item_id = None
            self._hover_selection = None
            if self._viewer.is_initialized:
                self._viewer.display_scene(scene, fit=False)
            self._show_status(f"Boolean {operation} applied")
            LOGGER.info(
                "Boolean %s applied target=%s tool=%s",
                operation,
                target_item_id,
                tool_item_id,
            )

        def _body_item_ids(self) -> list[str]:
            return [item.item_id for item in scene if not is_sketch_object(item.meta)]

        def _selected_or_active_body_item_id(self) -> str | None:
            selection = scene.selection()
            item_id = (
                selection.item_id if selection is not None else scene.active_item_id()
            )
            if item_id is None or item_id not in scene:
                return None
            if is_sketch_object(scene.get(item_id).meta):
                return None
            return item_id

        def _valid_boolean_target_item_id(self) -> str | None:
            if (
                self._boolean_target_item_id is None
                or self._boolean_target_item_id not in scene
                or is_sketch_object(scene.get(self._boolean_target_item_id).meta)
            ):
                self._boolean_target_item_id = None
                return None
            return self._boolean_target_item_id

        def _fit_all(self) -> None:
            self._navigation.fit_all()
            self._navigation.capture_home()
            self._show_status("Fit all")

        def _home_view(self) -> None:
            self._navigation.go_home()
            self._show_status("Home view")

        def _set_display_mode(self, mode: str) -> None:
            self._viewer.set_display_mode(mode)
            self._show_status(f"Display: {mode}")
            self._refresh_action_state()

        def _show_status(self, message: str) -> None:
            self._last_status_text = message
            window = self.window()
            if hasattr(window, "statusBar"):
                window.statusBar().showMessage(message, 3500)
            self._refresh_hud()

        def _set_context_hint(self, message: str | None) -> None:
            if not message:
                self._context_hint_overlay.hide()
                return
            self._context_hint_overlay.setText(message)
            self._context_hint_overlay.adjustSize()
            self._position_context_hint()
            self._context_hint_overlay.show()
            self._context_hint_overlay.raise_()

        def get_ui_state(self) -> UIState:
            """Return a stable UI state snapshot without requiring a shown window."""
            overlay_text = self._dimension_overlay.text()
            if not overlay_text and self._move_session is not None:
                overlay_text = self._move_overlay_label(self._move_session)
            return UIState(
                work_mode=self._active_category,
                selection_mode=self._selection_kind.value,
                selection_type=self._ui_selection_type(),
                active_tool=self._ui_active_tool(),
                active_operation=self._ui_operation_state(),
                context_actions=self._ui_context_actions(),
                status_text=self._last_status_text,
                hint_text=(
                    self._context_hint_overlay.text()
                    if not self._context_hint_overlay.isHidden()
                    else ""
                ),
                overlay_visible=self._ui_overlay_visible(),
                overlay_text=overlay_text,
                manipulator_visible=self._ui_manipulator_visible(),
                right_panel_context=self._ui_right_panel_context(),
            )

        def _ui_selection_type(self) -> str:
            selection = scene.selection()
            if selection is None:
                return "none"
            selected_meta = scene.get(selection.item_id).meta
            if is_sketch_profile(selected_meta):
                return "sketch_profile"
            if selected_meta.get("kind") == SKETCH_ENTITY_META_KIND:
                return "sketch_entity"
            return selection.kind.value

        def _ui_active_tool(self) -> str:
            if self._sketch_session is not None:
                return f"sketch:{self._sketch_session.tool}"
            if self._move_session is not None:
                return self._move_session.tool
            return "idle"

        def _ui_operation_state(self) -> OperationState:
            if self._sketch_session is not None:
                return OperationState.DRAWING_SKETCH
            if self._move_session is None:
                if scene.selection() is not None:
                    return OperationState.SELECTING
                return OperationState.IDLE
            if self._move_session.tool in {"extrude", "sketch_extrude"}:
                return OperationState.PREVIEWING_EXTRUDE
            if (
                self._move_session.drag_start is not None
                or self._move_session.vector is not None
                or self._move_session.distance != 0
            ):
                return OperationState.DRAGGING_TRANSFORM
            return OperationState.COMMAND_PENDING

        def _ui_context_actions(self) -> tuple[str, ...]:
            action_names: list[str] = []
            for _section_name, section_action_names in self._context_command_sections():
                for action_name in section_action_names:
                    action = self._actions.get(action_name)
                    if action is not None and action.isEnabled():
                        action_names.append(action_name)
            return tuple(action_names)

        def _ui_overlay_visible(self) -> bool:
            return bool(
                not self._dimension_overlay.isHidden()
                or (
                    self._move_session is not None
                    and self._move_session.tool in {"extrude", "sketch_extrude"}
                )
            )

        def _ui_manipulator_visible(self) -> bool:
            return bool(
                self._move_session is not None
                and self._move_session.tool in {"extrude", "sketch_extrude"}
            )

        def _ui_right_panel_context(self) -> str:
            if self._move_session is not None:
                return "active_operation"
            if self._sketch_session is not None:
                return "sketch"
            if scene.selection() is not None:
                return "selection"
            if scene.active_item_id() is not None:
                return "active_body"
            return "model"

        def _position_context_hint(self) -> None:
            if not hasattr(self, "_context_hint_overlay"):
                return
            margin = 14
            max_x = max(
                margin, self.width() - self._context_hint_overlay.width() - margin
            )
            self._context_hint_overlay.move(min(margin, max_x), margin)

        def _is_in_orientation_gizmo(self, x: int, y: int) -> bool:
            left, top, size = self._orientation_gizmo_rect()
            return left <= x <= left + size and top <= y <= top + size

        def _orientation_gizmo_axis_at(self, x: int, y: int) -> str | None:
            left, top, size = self._orientation_gizmo_rect()
            local_x = x - left
            local_y = y - top
            third = size / 3.0
            if local_y < third:
                return "z"
            if local_x > size - third:
                return "y"
            if local_y > size - third or local_x > third:
                return "x"
            return None

        def _orientation_gizmo_rect(self) -> tuple[int, int, int]:
            margin = 14
            size = 118
            return (
                max(margin, self.width() - size - margin),
                max(margin, self.height() - size - margin),
                size,
            )

        def _show_pending_command(self, command_name: str) -> None:
            self._show_status(f"{command_name}: not implemented yet")
            LOGGER.info("Pending UI command selected: %s", command_name)

        def _activate_sketch_category(self) -> None:
            self._active_category = "sketch"
            if self._sketch_session is None:
                selection = scene.selection()
                can_start_on_face = (
                    selection is not None
                    and selection.kind == SelectionKind.FACE
                    and not self._selected_item_is_sketch_profile()
                )
                if len(scene) == 0 or can_start_on_face:
                    self._start_sketch_on_selection()
                    return
                self._set_context_hint(
                    "Select a planar face, then click Sketch or press S"
                )
                self._show_status("Sketch: select a planar face first")
            else:
                self._set_context_hint(
                    "Choose a sketch tool: Line, Arc, Circle, Rectangle"
                )
                self._show_status("Sketch tools ready")
            self._refresh_action_state()

        def _set_active_category(self, category: str) -> None:
            if category not in {
                "select",
                "sketch",
                "create",
                "modify",
                "transform",
                "measure",
            }:
                raise ValueError(f"Unsupported tool category: {category}")
            if category == "sketch":
                self._activate_sketch_category()
                return
            self._active_category = category
            if category == "select":
                self._set_context_hint("Select an object, face, edge, or vertex")
            elif category == "create":
                self._set_context_hint("Create a body or import geometry")
            elif category == "modify":
                self._set_context_hint("Select a face, edge, vertex, or sketch profile")
            elif category == "transform":
                self._set_context_hint("Select a body, then choose Move")
            else:
                self._set_context_hint(None)
            self._show_status(f"Mode: {category.title()}")
            self._refresh_action_state()

        def _show_dimension_overlay(self, text: str, x: int, y: int) -> None:
            self._dimension_overlay.setText(text)
            if self._viewer.is_initialized:
                self._dimension_overlay.hide()
                self._viewer.display_dimension_label(
                    text,
                    self._dimension_label_position(x, y),
                )
                return
            self._dimension_overlay.adjustSize()
            margin = 12
            max_x = self.width() - self._dimension_overlay.width() - margin
            max_y = self.height() - self._dimension_overlay.height() - margin
            next_x = min(max(x + 14, margin), max_x)
            next_y = min(max(y + 14, margin), max_y)
            self._dimension_overlay.move(next_x, next_y)
            self._dimension_overlay.show()
            self._dimension_overlay.raise_()

        def _hide_dimension_overlay(self) -> None:
            self._dimension_overlay.hide()
            self._viewer.clear_dimension_label()

        def _dimension_label_position(
            self,
            x: int,
            y: int,
        ) -> tuple[float, float, float]:
            if self._sketch_session is not None:
                uv = self._screen_to_sketch_uv(x, y)
                if uv is not None:
                    return self._workplane_point(self._sketch_session.workplane, uv)
            if self._move_session is not None and self._move_session.index is not None:
                try:
                    center = self._face_center(
                        self._move_session.item_id,
                        self._move_session.index,
                    )
                    offset = self._move_session.distance + 8.0
                    return tuple(
                        center_component + axis_component * offset
                        for center_component, axis_component in zip(
                            center,
                            self._move_session.axis,
                        )
                    )
                except (CommandError, IndexError, ValueError):
                    LOGGER.debug("Dimension label position fallback", exc_info=True)
            return (0.0, 0.0, 0.0)

        @staticmethod
        def _workplane_point(
            workplane: Workplane,
            uv: tuple[float, float],
        ) -> tuple[float, float, float]:
            origin = workplane.origin
            x_dir = workplane.x_direction
            y_dir = workplane.y_direction
            return (
                origin.X() + x_dir.X() * uv[0] + y_dir.X() * uv[1],
                origin.Y() + x_dir.Y() * uv[0] + y_dir.Y() * uv[1],
                origin.Z() + x_dir.Z() * uv[0] + y_dir.Z() * uv[1],
            )

        def _refresh_hud(self) -> None:
            if self._hud_labels:
                self._hud_labels["mode"].setText(
                    f"Mode: {self._active_category.title()}"
                )
                self._hud_labels["selection"].setText(self._selection_label())
                self._hud_labels["axis"].setText(
                    f"Select: {self._selection_kind.value}"
                )
                self._hud_labels["tool"].setText(self._tool_label())
                self._hud_labels["sketch"].setText(self._sketch_label())
            self._refresh_action_state()
            self._refresh_browser()

        def _refresh_browser(self) -> None:
            if not self._browser_lists:
                return
            body_list = self._browser_lists.get("bodies")
            sketch_list = self._browser_lists.get("sketches")
            history_list = self._browser_lists.get("history")
            model_list = self._browser_lists.get("model")
            properties_list = self._browser_lists.get("properties")
            if body_list is None or sketch_list is None or history_list is None:
                return

            browser_lists = (
                body_list,
                sketch_list,
                history_list,
                model_list,
                properties_list,
            )
            self._clear_browser_lists(*browser_lists)
            try:
                active_item_id = scene.active_item_id()
                scene_items = list(scene)
                body_items = [
                    item for item in scene_items if not is_sketch_object(item.meta)
                ]
                sketch_items = [
                    item for item in scene_items if is_sketch_object(item.meta)
                ]
                if model_list is not None:
                    self._add_browser_item(model_list, "Model", enabled=False)
                    self._add_browser_item(
                        model_list,
                        f"Bodies ({len(body_items)})",
                        enabled=False,
                    )
                    for index, item in enumerate(body_items, start=1):
                        label = self._body_browser_label(
                            item,
                            index,
                            active_item_id,
                        )
                        self._add_scene_browser_item(
                            model_list,
                            item,
                            f"  {label}",
                        )
                    self._add_browser_item(
                        model_list,
                        f"Sketches ({len(sketch_items)})",
                        enabled=False,
                    )
                    for index, item in enumerate(sketch_items, start=1):
                        label = self._sketch_browser_label(
                            item,
                            index,
                            active_item_id,
                        )
                        self._add_scene_browser_item(
                            model_list,
                            item,
                            f"  {label}",
                        )
                    if len(scene_items) == 0:
                        self._add_browser_item(
                            model_list,
                            "No bodies or sketches",
                            enabled=False,
                        )
                if properties_list is not None:
                    self._populate_properties_panel(properties_list)

                for index, item in enumerate(body_items, start=1):
                    self._add_scene_browser_item(
                        body_list,
                        item,
                        self._body_browser_label(item, index, active_item_id),
                    )
                if not body_items:
                    self._add_browser_item(body_list, "No bodies", enabled=False)

                if self._sketch_session is not None:
                    self._add_browser_item(
                        sketch_list,
                        (
                            f"Active sketch: {self._sketch_session.tool} "
                            f"on {self._sketch_session.label}"
                        ),
                        command="cancel_tool",
                        tooltip="Click to cancel the active sketch.",
                    )
                for index, item in enumerate(sketch_items, start=1):
                    self._add_scene_browser_item(
                        sketch_list,
                        item,
                        self._sketch_browser_label(item, index, active_item_id),
                    )
                if not sketch_items and self._sketch_session is None:
                    self._add_browser_item(sketch_list, "No sketches", enabled=False)

                self._populate_history_panel(history_list)
            finally:
                self._unblock_browser_lists(*browser_lists)

        def _clear_browser_lists(self, *browser_lists) -> None:
            for browser_list in browser_lists:
                if browser_list is None:
                    continue
                browser_list.blockSignals(True)
                browser_list.clear()

        @staticmethod
        def _unblock_browser_lists(*browser_lists) -> None:
            for browser_list in browser_lists:
                if browser_list is not None:
                    browser_list.blockSignals(False)

        def _add_browser_item(
            self,
            browser_list,
            text: str,
            *,
            item_id: str | None = None,
            selection_kind: SelectionKind | None = None,
            selection_index: int = 0,
            command: str | None = None,
            enabled: bool = True,
            tooltip: str | None = None,
        ):
            item = QListWidgetItem(text)
            if item_id is not None:
                item.setData(BROWSER_ITEM_ID_ROLE, item_id)
            if selection_kind is not None:
                item.setData(BROWSER_SELECTION_KIND_ROLE, selection_kind.value)
                item.setData(BROWSER_SELECTION_INDEX_ROLE, selection_index)
            if command is not None:
                item.setData(BROWSER_COMMAND_ROLE, command)
            if tooltip:
                item.setToolTip(tooltip)
            if not enabled:
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            browser_list.addItem(item)
            return item

        def _add_scene_browser_item(self, browser_list, item, label: str) -> None:
            if is_sketch_profile(item.meta):
                selection_kind = SelectionKind.FACE
                selection_index = 1
                tooltip = "Click to select this sketch profile for extrusion."
            elif is_sketch_object(item.meta):
                selection_kind = SelectionKind.OBJECT
                selection_index = 0
                tooltip = "Click to select this sketch entity."
            else:
                selection_kind = SelectionKind.OBJECT
                selection_index = 0
                tooltip = "Click to select this body."
            self._add_browser_item(
                browser_list,
                label,
                item_id=item.item_id,
                selection_kind=selection_kind,
                selection_index=selection_index,
                tooltip=tooltip,
            )

        @staticmethod
        def _body_browser_label(item, index: int, active_item_id: str | None) -> str:
            prefix = "* " if item.item_id == active_item_id else "  "
            source = item.meta.get("source", "body")
            return f"{prefix}Body {index}: {source} {item.item_id[:8]}"

        @staticmethod
        def _sketch_browser_label(item, index: int, active_item_id: str | None) -> str:
            prefix = "* " if item.item_id == active_item_id else "  "
            profile = item.meta.get("profile", "profile")
            return f"{prefix}Sketch {index}: {profile} {item.item_id[:8]}"

        def _populate_history_panel(self, history_list) -> None:
            if self._move_session is not None or self._sketch_session is not None:
                active_tool = (
                    self._sketch_session.tool
                    if self._sketch_session is not None
                    else self._move_session.tool
                )
                self._add_browser_item(
                    history_list,
                    f"Active operation: {active_tool}",
                    enabled=False,
                )
                self._add_browser_item(
                    history_list,
                    "Cancel active tool",
                    command="cancel_tool",
                    tooltip="Cancel the active operation.",
                )
            undo_depth = scene.undo_depth()
            redo_depth = scene.redo_depth()
            if undo_depth > 0:
                self._add_browser_item(
                    history_list,
                    f"Undo last change ({undo_depth})",
                    command="undo",
                    tooltip="Click to undo one scene change.",
                )
            if redo_depth > 0:
                self._add_browser_item(
                    history_list,
                    f"Redo change ({redo_depth})",
                    command="redo",
                    tooltip="Click to redo one scene change.",
                )
            if undo_depth == 0 and redo_depth == 0:
                self._add_browser_item(history_list, "No undo history", enabled=False)

        def _populate_properties_panel(self, properties_list) -> None:
            self._add_browser_item(properties_list, "Properties", enabled=False)
            if self._move_session is not None:
                tool_name = (
                    "New Body"
                    if self._move_session.operation == "new_body"
                    else self._move_session.tool.replace("_", " ").title()
                )
                operation = "New Body"
                if self._move_session.tool == "extrude":
                    operation = "Add / Cut"
                elif self._move_session.tool == "sketch_extrude":
                    operation = (
                        "New Body"
                        if self._move_session.operation == "new_body"
                        else "Feature"
                    )
                elif self._move_session.tool == "rotate":
                    operation = "Transform"
                elif self._move_session.tool == "fillet":
                    operation = "Round"
                elif self._move_session.tool == "chamfer":
                    operation = "Bevel"
                self._add_browser_item(
                    properties_list,
                    f"Type: {tool_name}",
                    enabled=False,
                )
                self._add_browser_item(
                    properties_list,
                    f"Selection: {self._selection_label()}",
                    enabled=False,
                )
                self._add_browser_item(
                    properties_list,
                    f"{self._move_axis_property_label(self._move_session)}",
                    enabled=False,
                )
                self._add_browser_item(
                    properties_list,
                    self._move_value_property_label(self._move_session),
                    enabled=False,
                )
                if self._move_session.tool in {"extrude", "sketch_extrude"}:
                    self._add_browser_item(
                        properties_list,
                        "Taper Angle: 0 deg",
                        enabled=False,
                    )
                self._add_browser_item(
                    properties_list,
                    f"Operation: {operation}",
                    enabled=False,
                )
                self._populate_property_actions(properties_list)
                return

            if self._sketch_session is not None:
                self._add_browser_item(
                    properties_list,
                    "Type: Sketch",
                    enabled=False,
                )
                self._add_browser_item(
                    properties_list,
                    f"Workplane: {self._sketch_session.label}",
                    enabled=False,
                )
                self._add_browser_item(
                    properties_list,
                    f"Tool: {self._sketch_session.tool}",
                    enabled=False,
                )
                self._add_browser_item(
                    properties_list,
                    "Operation: Profile",
                    enabled=False,
                )
                self._populate_property_actions(properties_list)
                return
            self._add_browser_item(
                properties_list,
                f"Mode: {self._active_category.title()}",
                enabled=False,
            )
            self._add_browser_item(
                properties_list,
                f"Selection mode: {self._selection_kind.value}",
                enabled=False,
            )
            self._add_browser_item(
                properties_list,
                self._selection_label(),
                enabled=False,
            )
            active_item_id = scene.active_item_id()
            if active_item_id is not None and active_item_id in scene:
                active = scene.get(active_item_id)
                self._add_browser_item(
                    properties_list,
                    f"Active ID: {active.item_id[:8]}",
                    enabled=False,
                )
                if is_sketch_object(active.meta):
                    self._add_browser_item(
                        properties_list,
                        "Type: Sketch",
                        enabled=False,
                    )
                    self._add_browser_item(
                        properties_list,
                        f"Profile: {active.meta.get('profile', 'profile')}",
                        enabled=False,
                    )
                else:
                    self._add_browser_item(
                        properties_list,
                        "Type: Body",
                        enabled=False,
                    )
                    self._add_browser_item(
                        properties_list,
                        f"Source: {active.meta.get('source', 'body')}",
                        enabled=False,
                    )
            self._populate_property_actions(properties_list)

        @staticmethod
        def _move_axis_property_label(session: MoveSession) -> str:
            if session.tool == "rotate":
                return f"Axis: {session.axis_name}"
            if session.tool in {"fillet", "chamfer"}:
                return f"Edge: {session.index}"
            return f"Direction: {session.axis_name}"

        @staticmethod
        def _move_value_property_label(session: MoveSession) -> str:
            if session.tool == "rotate":
                return f"Angle: {session.distance:.2f} deg"
            if session.tool == "fillet":
                return f"Radius: {session.distance:.2f} mm"
            if session.tool == "chamfer":
                return f"Distance: {session.distance:.2f} mm"
            return f"Distance: {session.distance:.2f} mm"

        def _populate_property_actions(self, properties_list) -> None:
            action_names = self._ui_context_actions()
            if not action_names:
                self._add_browser_item(
                    properties_list,
                    "No actions for current selection",
                    enabled=False,
                )
                return
            self._add_browser_item(properties_list, "Actions", enabled=False)
            for action_name in action_names:
                action = self._actions.get(action_name)
                if action is None:
                    continue
                self._add_browser_item(
                    properties_list,
                    action.text().replace("&", ""),
                    command=action_name,
                    tooltip=action.toolTip(),
                )

        def _handle_browser_item_clicked(self, item) -> None:
            command = item.data(BROWSER_COMMAND_ROLE)
            if isinstance(command, str):
                self._run_browser_command(command)
                return
            item_id = item.data(BROWSER_ITEM_ID_ROLE)
            if not isinstance(item_id, str):
                return
            selection_kind_value = item.data(BROWSER_SELECTION_KIND_ROLE)
            selection_index = item.data(BROWSER_SELECTION_INDEX_ROLE)
            try:
                selection_kind = SelectionKind(selection_kind_value)
            except ValueError:
                return
            self._select_scene_item_from_browser(
                item_id,
                selection_kind,
                int(selection_index or 0),
            )

        def _run_browser_command(self, command: str) -> None:
            if command == "undo":
                self._undo()
                return
            if command == "redo":
                self._redo()
                return
            if command == "cancel_tool":
                self._cancel_active_tool()
                return
            action = self._actions.get(command)
            if action is not None and action.isEnabled():
                action.trigger()
                return
            self._show_status("Action unavailable")

        def _select_scene_item_from_browser(
            self,
            item_id: str,
            selection_kind: SelectionKind,
            selection_index: int,
        ) -> None:
            if item_id not in scene:
                self._refresh_browser()
                return
            scene_object = scene.get(item_id)
            scene.set_selection(
                SelectionRef(
                    item_id=item_id,
                    kind=selection_kind,
                    index=selection_index,
                )
            )
            self._selection_kind = selection_kind
            self._hover_selection = None
            self._active_category = (
                "modify" if selection_kind != SelectionKind.OBJECT else "transform"
            )
            if self._viewer.is_initialized:
                self._viewer.set_selection_kind(selection_kind)
                self._viewer.display_scene(scene, fit=False)
                self._viewer.display_selection_marker(
                    scene_object.shape,
                    scene_object.meta,
                )
            if is_sketch_profile(scene_object.meta):
                self._set_context_hint("Sketch Profile selected - Extrude is available")
                self._show_status("Selected Sketch Profile")
            elif is_sketch_object(scene_object.meta):
                self._set_context_hint("Sketch entity selected")
                self._show_status("Selected Sketch")
            else:
                self._set_context_hint("Body selected - choose Move or Modify")
                self._show_status(f"Selected body {item_id[:8]}")
            self._refresh_hud()

        def _selection_label(self) -> str:
            selection = scene.selection()
            if selection is None:
                return "Selection: none"
            if is_sketch_profile(scene.get(selection.item_id).meta):
                return "Selection: Sketch Profile"
            return f"Selection: {selection.kind.value} {selection.index}"

        def _tool_label(self) -> str:
            if self._sketch_session is not None:
                return f"Tool: Sketch {self._sketch_session.tool}"
            if self._move_session is None:
                return "Tool: idle"
            if (
                self._move_session.tool == "sketch_extrude"
                and self._move_session.operation == "new_body"
            ):
                return (
                    f"Tool: New Body {self._move_session.axis_name} "
                    f"{self._move_session.distance:.2f}"
                )
            if self._move_session.tool == "rotate":
                return (
                    f"Tool: Rotate {self._move_session.axis_name} "
                    f"{self._move_session.distance:.2f} deg"
                )
            if self._move_session.tool == "fillet":
                return f"Tool: Fillet R {self._move_session.distance:.2f}"
            if self._move_session.tool == "chamfer":
                return f"Tool: Chamfer {self._move_session.distance:.2f}"
            tool_names = {
                "sketch_extrude": "Sketch Extrude",
                "extrude": "Extrude",
                "move": "Move",
            }
            tool_name = tool_names.get(
                self._move_session.tool,
                self._move_session.tool.title(),
            )
            return (
                f"Tool: {tool_name} {self._move_session.axis_name} "
                f"{self._move_session.distance:.2f}"
            )

        def _sketch_label(self) -> str:
            if self._sketch_session is None:
                return "Sketch: none"
            label = f"Sketch: {self._sketch_session.label}"
            if self._sketch_session.drag_dimensions is not None:
                return f"{label} {self._sketch_session.drag_dimensions}"
            return label

        def _refresh_action_state(self) -> None:
            if not self._actions:
                return
            sketch_active = self._sketch_session is not None
            tool_active = self._move_session is not None or sketch_active
            selection = scene.selection()
            selected_face = (
                selection is not None and selection.kind == SelectionKind.FACE
            )
            selected_object = (
                selection is not None and selection.kind == SelectionKind.OBJECT
            )
            selected_edge = (
                selection is not None and selection.kind == SelectionKind.EDGE
            )
            selected_vertex = (
                selection is not None and selection.kind == SelectionKind.VERTEX
            )
            selected_profile = self._selected_item_is_sketch_profile()
            body_count = len(self._body_item_ids())
            boolean_target_item_id = self._valid_boolean_target_item_id()
            boolean_tool_item_id = self._selected_or_active_body_item_id()
            boolean_ready = (
                boolean_target_item_id is not None
                and boolean_tool_item_id is not None
                and boolean_tool_item_id != boolean_target_item_id
                and not tool_active
            )
            active_item_id = scene.active_item_id()
            active_body = active_item_id is not None and not is_sketch_object(
                scene.get(active_item_id).meta
            )
            selected_object_body = selected_object and not is_sketch_object(
                scene.get(selection.item_id).meta
            )
            view_move_supported = self._selection_supports_view_move(selection)
            move_selection_action = self._actions.get("move_selection")
            if move_selection_action is not None:
                if selected_face and not selected_profile:
                    move_selection_action.setText("Move Face")
                elif selected_edge:
                    move_selection_action.setText("Move Edge")
                elif selected_vertex:
                    move_selection_action.setText("Move Vertex")
                else:
                    move_selection_action.setText("Move Selection")
            move_object_action = self._actions.get("move_object")
            if move_object_action is not None:
                move_object_action.setText("Move")
            start_sketch_action = self._actions.get("start_sketch")
            if start_sketch_action is not None:
                if selected_face and not selected_profile:
                    start_sketch_action.setText("Sketch on Face")
                else:
                    start_sketch_action.setText("Start Sketch")
            for category, action_name in (
                ("select", "category_select"),
                ("sketch", "category_sketch"),
                ("create", "category_create"),
                ("modify", "category_modify"),
                ("transform", "category_transform"),
                ("measure", "category_measure"),
            ):
                action = self._actions.get(action_name)
                if action is not None:
                    action.setChecked(self._active_category == category)
            for kind, action_name in (
                (SelectionKind.OBJECT, "select_object"),
                (SelectionKind.FACE, "select_face"),
                (SelectionKind.EDGE, "select_edge"),
                (SelectionKind.VERTEX, "select_vertex"),
            ):
                action = self._actions.get(action_name)
                if action is not None:
                    action.setChecked(self._selection_kind == kind)
            for axis_name, action_name in (
                ("X", "axis_x"),
                ("Y", "axis_y"),
                ("Z", "axis_z"),
            ):
                action = self._actions.get(action_name)
                if action is not None:
                    action.setChecked(self._move_axis_name == axis_name)
            for display_mode, action_name in (
                ("shaded", "display_shaded"),
                ("wireframe", "display_wireframe"),
            ):
                action = self._actions.get(action_name)
                if action is not None:
                    action.setChecked(self._viewer.display_mode == display_mode)
            move_active = (
                self._move_session is not None or self._sketch_session is not None
            )
            cancel_action = self._actions.get("cancel_tool")
            if cancel_action is not None:
                cancel_action.setEnabled(move_active)
            enabled_by_context = {
                "undo": scene.can_undo() and not tool_active,
                "redo": scene.can_redo() and not tool_active,
                "save_project": True,
                "category_select": not tool_active,
                "category_sketch": not tool_active,
                "category_create": not tool_active,
                "category_modify": selection is not None and not tool_active,
                "category_transform": (
                    body_count > 0
                    and not tool_active
                    and (
                        selection is None
                        or selection.kind == SelectionKind.OBJECT
                        or selected_profile
                    )
                ),
                "add_box": not tool_active,
                "export_step": active_item_id is not None,
                "delete_object": (
                    not tool_active
                    and (selected_object_body or (selection is None and active_body))
                ),
                "move_object": (active_body or selected_object) and not tool_active,
                "move_object_x": (active_body or selected_object) and not tool_active,
                "move_object_y": (active_body or selected_object) and not tool_active,
                "move_object_z": (active_body or selected_object) and not tool_active,
                "move_selection": (
                    selection is not None
                    and selection.kind != SelectionKind.OBJECT
                    and view_move_supported
                    and not tool_active
                ),
                "move_selection_normal": (
                    selected_face and not selected_profile and not tool_active
                ),
                "move_selection_x": (
                    selection is not None
                    and selection.kind != SelectionKind.OBJECT
                    and not selected_profile
                    and view_move_supported
                    and not tool_active
                ),
                "move_selection_y": (
                    selection is not None
                    and selection.kind != SelectionKind.OBJECT
                    and not selected_profile
                    and view_move_supported
                    and not tool_active
                ),
                "move_selection_z": (
                    selection is not None
                    and selection.kind != SelectionKind.OBJECT
                    and not selected_profile
                    and view_move_supported
                    and not tool_active
                ),
                "rotate_body": (active_body or selected_object) and not tool_active,
                "mirror_body": (active_body or selected_object) and not tool_active,
                "set_boolean_target": (
                    body_count >= 2
                    and boolean_tool_item_id is not None
                    and not tool_active
                ),
                "clear_boolean_target": boolean_target_item_id is not None,
                "boolean_union": boolean_ready,
                "boolean_subtract": boolean_ready,
                "boolean_intersect": boolean_ready,
                "start_sketch": (
                    not tool_active
                    and (len(scene) == 0 or (selected_face and not selected_profile))
                ),
                "new_sketch": (
                    self._move_session is None
                    and (
                        len(scene) == 0
                        or (selected_face and not selected_profile)
                        or self._sketch_session is not None
                    )
                ),
                "sketch_rectangle_tool": sketch_active,
                "sketch_line_tool": sketch_active,
                "sketch_arc_tool": sketch_active,
                "sketch_rectangle3_tool": sketch_active,
                "sketch_center_rectangle_tool": sketch_active,
                "sketch_circle_tool": sketch_active,
                "sketch_extrude": selected_profile and not tool_active,
                "sketch_new_body": selected_profile and not tool_active,
                "extrude": selected_face and not tool_active,
                "extrude_reverse": (
                    selected_face and not selected_profile and not tool_active
                ),
                "circle_boss": (
                    selected_face and not selected_profile and not tool_active
                ),
                "circle_cut": (
                    selected_face and not selected_profile and not tool_active
                ),
                "offset_face": (
                    selected_face and not selected_profile and not tool_active
                ),
                "fillet": selected_edge and not tool_active,
                "chamfer": selected_edge and not tool_active,
            }
            active_command_action = self._active_command_action_name()
            if active_command_action is not None:
                enabled_by_context[active_command_action] = True
            for action_name, enabled in enabled_by_context.items():
                action = self._actions.get(action_name)
                if action is not None:
                    action.setEnabled(bool(enabled))
            for category_action_name in (
                "category_select",
                "category_sketch",
                "category_create",
                "category_modify",
                "category_transform",
            ):
                action = self._actions.get(category_action_name)
                if action is not None:
                    action.setVisible(action.isEnabled() or action.isChecked())
            self._refresh_command_surface()
            if self._sketch_toolbar is not None:
                sketch_active = (
                    self._active_category == "sketch"
                    or self._sketch_session is not None
                )
                self._sketch_toolbar.setVisible(sketch_active)

        def _selected_item_is_sketch_profile(self) -> bool:
            selection = scene.selection()
            if selection is None:
                return False
            return is_sketch_profile(scene.get(selection.item_id).meta)

        def _context_command_sections(self) -> list[tuple[str, list[str]]]:
            if self._sketch_session is not None:
                sketch_actions = [
                    "sketch_line_tool",
                    "sketch_arc_tool",
                    "sketch_circle_tool",
                    "sketch_rectangle3_tool",
                    "sketch_center_rectangle_tool",
                ]
                if self._sketch_session.host:
                    sketch_actions.insert(0, "new_sketch")
                return [
                    (
                        "Sketch",
                        sketch_actions,
                    ),
                    ("Active Tool", ["cancel_tool"]),
                ]
            if self._move_session is not None:
                active_action = self._active_command_action_name()
                actions = [
                    action for action in (active_action, "cancel_tool") if action
                ]
                return [("Active Tool", actions)]

            selection = scene.selection()
            if (
                selection is not None
                and self._sketch_session is None
                and self._selected_item_is_sketch_profile()
            ):
                return [("Profile", ["sketch_extrude", "sketch_new_body"])]
            if self._active_category == "select":
                return []
            if self._active_category == "sketch":
                if self._sketch_session is None:
                    return [("Sketch", ["start_sketch", "new_sketch"])]
                return [
                    (
                        "Sketch",
                        [
                            "sketch_line_tool",
                            "sketch_arc_tool",
                            "sketch_circle_tool",
                            "sketch_rectangle3_tool",
                            "sketch_center_rectangle_tool",
                        ],
                    ),
                    ("Active Tool", ["cancel_tool"]),
                ]
            if self._active_category == "create":
                return [("Create", ["add_box", "import_step", "export_step"])]

            boolean_target_item_id = self._valid_boolean_target_item_id()
            boolean_tool_item_id = self._selected_or_active_body_item_id()
            boolean_section = ["set_boolean_target"]
            if boolean_target_item_id is not None:
                boolean_section.append("clear_boolean_target")
            if (
                boolean_target_item_id is not None
                and boolean_tool_item_id is not None
                and boolean_tool_item_id != boolean_target_item_id
            ):
                boolean_section.extend(
                    ["boolean_union", "boolean_subtract", "boolean_intersect"]
                )
            if self._active_category == "transform":
                if len(self._body_item_ids()) == 0:
                    return []
                if (
                    selection is not None
                    and selection.kind != SelectionKind.OBJECT
                    and not self._selected_item_is_sketch_profile()
                ):
                    return []
                return [
                    (
                        "Body",
                        [
                            "move_object",
                            "rotate_body",
                            "mirror_body",
                        ]
                        + boolean_section,
                    ),
                ]
            if self._active_category == "measure":
                return []
            if selection is None:
                return []
            if selection.kind == SelectionKind.OBJECT:
                return [
                    (
                        "Body",
                        [
                            "move_object",
                            "rotate_body",
                            "mirror_body",
                        ]
                        + boolean_section,
                    )
                ]
            if selection.kind == SelectionKind.FACE:
                return [
                    (
                        "Face",
                        [
                            "start_sketch",
                            "extrude",
                            "move_selection",
                            "offset_face",
                        ],
                    )
                ]
            if selection.kind == SelectionKind.EDGE:
                return [
                    (
                        "Edge",
                        [
                            "fillet",
                            "chamfer",
                            "move_selection",
                        ],
                    )
                ]
            if selection.kind == SelectionKind.VERTEX:
                return [
                    (
                        "Vertex",
                        [
                            "move_selection",
                        ],
                    )
                ]
            return []

        def _active_command_action_name(self) -> str | None:
            if self._move_session is None:
                return None
            if self._move_session.tool == "extrude":
                return "extrude"
            if self._move_session.tool == "sketch_extrude":
                if self._move_session.operation == "new_body":
                    return "sketch_new_body"
                return "sketch_extrude"
            if self._move_session.tool == "move":
                if self._move_session.target_kind == "object":
                    return "move_object"
                return "move_selection"
            if self._move_session.tool == "rotate":
                return "rotate_body"
            if self._move_session.tool == "fillet":
                return "fillet"
            if self._move_session.tool == "chamfer":
                return "chamfer"
            return None

        def _refresh_command_surface(self) -> None:
            if self._command_menu is None or self._command_toolbar is None:
                return
            self._command_menu.clear()
            self._command_toolbar.clear()
            sections = self._context_command_sections()
            has_visible_actions = False
            for section_index, (section_name, action_names) in enumerate(sections):
                visible_actions = [
                    action
                    for action_name in action_names
                    if (action := self._actions.get(action_name)) is not None
                    and action.isEnabled()
                ]
                if not visible_actions:
                    continue
                has_visible_actions = True
                if section_index > 0:
                    self._command_menu.addSeparator()
                    self._command_toolbar.addSeparator()
                label_action = self._make_command_section_label(section_name)
                self._command_menu.addAction(label_action)
                for action in visible_actions:
                    self._command_menu.addAction(action)
                    self._command_toolbar.addAction(action)
            self._command_toolbar.setVisible(has_visible_actions)

        def _make_command_section_label(self, text: str):
            from PySide6.QtGui import QAction

            existing = self._command_section_actions.get(text)
            if existing is not None:
                return existing
            action = QAction(text, self)
            action.setObjectName(f"context_label_{text.lower().replace(' ', '_')}")
            action.setEnabled(False)
            self._command_section_actions[text] = action
            return action

    window = QMainWindow()
    viewer_widget = ViewerWidget(viewer, navigation)
    window.setCentralWidget(viewer_widget)
    window.setWindowTitle("Direct Modeling CAD")
    window.setStyleSheet(theme.app_stylesheet())
    actions: dict[str, QAction] = {}
    toolbar_icon_size = QSize(theme.SIDEBAR_ICON_SIZE, theme.SIDEBAR_ICON_SIZE)
    context_toolbar_icon_size = QSize(theme.CONTEXT_ICON_SIZE, theme.CONTEXT_ICON_SIZE)
    top_toolbar_icon_size = QSize(theme.TOP_ICON_SIZE, theme.TOP_ICON_SIZE)
    icon_glyphs = {
        "add_box": "+",
        "axis_x": "X",
        "axis_y": "Y",
        "axis_z": "Z",
        "boolean_intersect": "I",
        "boolean_subtract": "-",
        "boolean_union": "U",
        "cancel_tool": "Esc",
        "category_create": "+",
        "category_measure": "R",
        "category_modify": "M",
        "category_select": "S",
        "category_sketch": "K",
        "category_transform": "T",
        "chamfer": "C",
        "circle_boss": "O",
        "circle_cut": "O-",
        "clear_boolean_target": "B-",
        "delete_object": "X",
        "display_shaded": "F",
        "display_wireframe": "W",
        "exit": "Q",
        "export_step": "Ex",
        "extrude": "E",
        "extrude_reverse": "E-",
        "fillet": "F",
        "fit_all": "Fit",
        "home": "H",
        "import_step": "Im",
        "mirror_body": "Mi",
        "new_sketch": "NS",
        "move_object": "M",
        "move_object_x": "MX",
        "move_object_y": "MY",
        "move_object_z": "MZ",
        "move_selection": "M",
        "move_selection_normal": "MN",
        "move_selection_x": "MX",
        "move_selection_y": "MY",
        "move_selection_z": "MZ",
        "offset_face": "Of",
        "redo": "Re",
        "rotate_body": "Ro",
        "save_project": "Sv",
        "select_object": "O",
        "select_edge": "E",
        "select_face": "F",
        "select_vertex": "V",
        "set_boolean_target": "B",
        "sketch_arc_tool": "A",
        "sketch_circle_tool": "C",
        "sketch_center_rectangle_tool": "CR",
        "sketch_extrude": "E",
        "sketch_line_tool": "L",
        "sketch_new_body": "NB",
        "sketch_rectangle3_tool": "3R",
        "sketch_rectangle_tool": "R",
        "start_sketch": "S",
        "undo": "Un",
    }
    icon_asset_files = {
        "boolean_intersect": "17_boolean_intersect.png",
        "boolean_subtract": "16_boolean_subtract.png",
        "boolean_union": "15_boolean_union.png",
        "add_box": "15_boolean_union.png",
        "category_create": "15_boolean_union.png",
        "category_modify": "08_push_pull.png",
        "category_transform": "09_move.png",
        "category_select": "01_select.png",
        "category_sketch": "02_sketch.png",
        "chamfer": "14_chamfer.png",
        "circle_boss": "05_circle.png",
        "circle_cut": "16_boolean_subtract.png",
        "clear_boolean_target": "16_boolean_subtract.png",
        "delete_object": "16_boolean_subtract.png",
        "display_shaded": "20_face_mode.png",
        "display_wireframe": "19_edge_mode.png",
        "extrude": "08_push_pull.png",
        "extrude_reverse": "08_push_pull.png",
        "fillet": "13_fillet.png",
        "mirror_body": "09_move.png",
        "new_sketch": "02_sketch.png",
        "move_object": "09_move.png",
        "move_object_x": "09_move.png",
        "move_object_y": "09_move.png",
        "move_object_z": "09_move.png",
        "move_selection": "09_move.png",
        "move_selection_normal": "09_move.png",
        "move_selection_x": "09_move.png",
        "move_selection_y": "09_move.png",
        "move_selection_z": "09_move.png",
        "offset_face": "12_offset.png",
        "rotate_body": "10_rotate.png",
        "select_edge": "19_edge_mode.png",
        "select_face": "20_face_mode.png",
        "select_object": "01_select.png",
        "select_vertex": "18_vertex_mode.png",
        "set_boolean_target": "15_boolean_union.png",
        "sketch_arc_tool": "06_arc.png",
        "sketch_circle_tool": "05_circle.png",
        "sketch_center_rectangle_tool": "04_rectangle.png",
        "sketch_extrude": "07_extrude.png",
        "sketch_line_tool": "03_line.png",
        "sketch_new_body": "07_extrude.png",
        "sketch_rectangle3_tool": "04_rectangle.png",
        "sketch_rectangle_tool": "04_rectangle.png",
        "start_sketch": "02_sketch.png",
    }
    icon_colors = {
        "select": QColor(62, 94, 140),
        "sketch": QColor(54, 125, 100),
        "create": QColor(142, 98, 45),
        "modify": QColor(135, 74, 88),
        "transform": QColor(87, 91, 120),
        "view": QColor(82, 96, 102),
        "file": QColor(78, 105, 83),
        "default": QColor(88, 88, 88),
    }

    def _icon_group(name: str) -> str:
        if name.startswith("select_") or name == "category_select":
            return "select"
        if "sketch" in name or name in {"start_sketch", "category_sketch"}:
            return "sketch"
        if name in {"add_box", "import_step", "category_create"}:
            return "create"
        if name in {
            "extrude",
            "extrude_reverse",
            "fillet",
            "chamfer",
            "circle_boss",
            "circle_cut",
            "offset_face",
            "category_modify",
        }:
            return "modify"
        if (
            name.startswith("axis_")
            or name.startswith("boolean_")
            or name
            in {
                "move_object",
                "move_object_x",
                "move_object_y",
                "move_object_z",
                "move_selection",
                "move_selection_normal",
                "move_selection_x",
                "move_selection_y",
                "move_selection_z",
                "rotate_body",
                "mirror_body",
                "set_boolean_target",
                "clear_boolean_target",
                "category_transform",
            }
        ):
            return "transform"
        if name in {"display_shaded", "display_wireframe", "fit_all", "home"}:
            return "view"
        if name in {"save_project", "export_step", "exit"}:
            return "file"
        return "default"

    def make_icon(name: str) -> QIcon:
        asset_file = icon_asset_files.get(name)
        if asset_file is not None:
            asset_path = ICON_ASSET_DIR / asset_file
            if asset_path.exists():
                source = QPixmap(str(asset_path))
                if not source.isNull():
                    side = min(source.width(), source.height())
                    icon_source = source.copy(0, 0, side, side)
                    scaled = icon_source.scaled(
                        toolbar_icon_size,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                    pixmap = QPixmap(toolbar_icon_size)
                    pixmap.fill(Qt.transparent)
                    painter = QPainter(pixmap)
                    painter.drawPixmap(
                        (toolbar_icon_size.width() - scaled.width()) // 2,
                        (toolbar_icon_size.height() - scaled.height()) // 2,
                        scaled,
                    )
                    painter.end()
                    return QIcon(pixmap)

        pixmap = QPixmap(toolbar_icon_size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        color = icon_colors[_icon_group(name)]
        painter.setBrush(color)
        painter.setPen(QPen(color.darker(135), 1))
        painter.drawRoundedRect(2, 2, 20, 20, 4, 4)
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, icon_glyphs.get(name, "?"))
        painter.end()
        return QIcon(pixmap)

    def configure_toolbar(toolbar: QToolBar, *, role: str = "sidebar") -> None:
        toolbar.setMovable(False)
        if role == "top":
            toolbar.setIconSize(top_toolbar_icon_size)
            toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            toolbar.setStyleSheet(theme.top_toolbar_stylesheet())
            return
        if role == "context":
            toolbar.setIconSize(context_toolbar_icon_size)
            toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            toolbar.setStyleSheet(theme.context_toolbar_stylesheet())
            return
        toolbar.setIconSize(toolbar_icon_size)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        toolbar.setMinimumWidth(theme.SIDEBAR_WIDTH)
        toolbar.setStyleSheet(theme.sidebar_toolbar_stylesheet())

    def make_sidebar_section_label(text: str) -> QLabel:
        label = QLabel(text, window)
        label.setStyleSheet(f"""
            QLabel {{
                color: {theme.TEXT_SECONDARY};
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 0px;
                padding: 8px 4px 2px 4px;
            }}
            """)
        label.setMinimumWidth(theme.SIDEBAR_WIDTH - 18)
        return label

    def make_action(
        name: str,
        text: str,
        slot,
        shortcut: str | None = None,
        status_tip: str = "",
        checkable: bool = False,
    ) -> QAction:
        action = QAction(make_icon(name), text, window)
        action.setObjectName(name)
        action.setCheckable(checkable)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        if status_tip:
            action.setStatusTip(status_tip)
        action.triggered.connect(lambda _checked=False, callback=slot: callback())
        actions[name] = action
        return action

    file_menu = window.menuBar().addMenu("&File")
    file_menu.addAction(
        make_action(
            "save_project",
            "Save",
            lambda: viewer_widget._show_pending_command("Save"),
            "Ctrl+Shift+S",
            "Save the project.",
        )
    )
    file_menu.addAction(
        make_action(
            "import_step",
            "Import STEP...",
            viewer_widget._import_step_dialog,
            "Ctrl+O",
            "Import a STEP body into the scene.",
        )
    )
    file_menu.addAction(
        make_action(
            "export_step",
            "Export STEP...",
            viewer_widget._export_step_dialog,
            "Ctrl+S",
            "Export the active body as STEP.",
        )
    )
    file_menu.addSeparator()
    file_menu.addAction(
        make_action("exit", "Exit", window.close, "Ctrl+Q", "Close the application.")
    )

    add_menu = window.menuBar().addMenu("&Add")
    add_menu.addAction(
        make_action(
            "add_box",
            "Box Body",
            viewer_widget._add_box_body,
            "B",
            "Add a separate box body.",
        )
    )

    edit_menu = window.menuBar().addMenu("&Edit")
    edit_menu.addAction(
        make_action(
            "undo",
            "Undo",
            viewer_widget._undo,
            "Ctrl+Z",
            "Restore the previous body state.",
        )
    )
    edit_menu.addAction(
        make_action(
            "redo",
            "Redo",
            viewer_widget._redo,
            "Ctrl+Y",
            "Redo the last undone action.",
        )
    )
    edit_menu.addAction(
        make_action(
            "cancel_tool",
            "Cancel Tool",
            viewer_widget._cancel_active_tool,
            "Esc",
            "Cancel the active tool.",
        )
    )
    edit_menu.addAction(
        make_action(
            "delete_object",
            "Delete Object",
            viewer_widget._delete_active_object,
            "Del",
            "Delete the selected or active object.",
        )
    )

    commands_menu = window.menuBar().addMenu("&Commands")
    commands_menu.setObjectName("CommandsMenu")

    boolean_menu = window.menuBar().addMenu("&Boolean")
    for action in (
        make_action(
            "set_boolean_target",
            "Boolean",
            viewer_widget._set_boolean_target_from_context,
            None,
            "Use the current body as the boolean target.",
        ),
        make_action(
            "clear_boolean_target",
            "Clear Boolean Target",
            viewer_widget._clear_boolean_target,
            None,
            "Clear the pending boolean target.",
        ),
        make_action(
            "boolean_union",
            "Union Bodies",
            lambda: viewer_widget._apply_boolean_tool("union"),
            None,
            "Fuse the selected body into the boolean target.",
        ),
        make_action(
            "boolean_subtract",
            "Subtract Body",
            lambda: viewer_widget._apply_boolean_tool("subtract"),
            None,
            "Cut the selected body from the boolean target.",
        ),
        make_action(
            "boolean_intersect",
            "Intersect Bodies",
            lambda: viewer_widget._apply_boolean_tool("intersect"),
            None,
            "Keep only the target/tool overlap.",
        ),
    ):
        boolean_menu.addAction(action)

    selection_group = QActionGroup(window)
    selection_group.setExclusive(True)
    selection_menu = window.menuBar().addMenu("&Selection")
    for action in (
        make_action(
            "select_object",
            "Object",
            lambda: viewer_widget._set_selection_kind(SelectionKind.OBJECT),
            "1",
            "Select whole bodies.",
            checkable=True,
        ),
        make_action(
            "select_face",
            "Face",
            lambda: viewer_widget._set_selection_kind(SelectionKind.FACE),
            "2",
            "Select faces.",
            checkable=True,
        ),
        make_action(
            "select_edge",
            "Edge",
            lambda: viewer_widget._set_selection_kind(SelectionKind.EDGE),
            "3",
            "Select edges.",
            checkable=True,
        ),
        make_action(
            "select_vertex",
            "Vertex",
            lambda: viewer_widget._set_selection_kind(SelectionKind.VERTEX),
            "4",
            "Select vertices.",
            checkable=True,
        ),
    ):
        selection_group.addAction(action)
        selection_menu.addAction(action)

    axis_group = QActionGroup(window)
    axis_group.setExclusive(True)
    axis_menu = window.menuBar().addMenu("&Axis")
    for action in (
        make_action(
            "axis_x",
            "X Axis",
            lambda: viewer_widget._set_move_axis("X", (1.0, 0.0, 0.0)),
            "X",
            "Use world X for object, edge, and vertex moves.",
            checkable=True,
        ),
        make_action(
            "axis_y",
            "Y Axis",
            lambda: viewer_widget._set_move_axis("Y", (0.0, 1.0, 0.0)),
            "Y",
            "Use world Y for object, edge, and vertex moves.",
            checkable=True,
        ),
        make_action(
            "axis_z",
            "Z Axis",
            lambda: viewer_widget._set_move_axis("Z", (0.0, 0.0, 1.0)),
            "Z",
            "Use world Z for object, edge, and vertex moves.",
            checkable=True,
        ),
    ):
        axis_group.addAction(action)
        axis_menu.addAction(action)

    sketch_menu = window.menuBar().addMenu("&Sketch")
    for action in (
        make_action(
            "start_sketch",
            "Start Sketch",
            viewer_widget._start_sketch_on_selection,
            "S",
            "Start sketching on the selected planar face.",
        ),
        make_action(
            "new_sketch",
            "New Sketch",
            viewer_widget._start_new_sketch_on_selection,
            None,
            "Start an independent sketch on the selected face or grid.",
        ),
        make_action(
            "sketch_rectangle_tool",
            "Center Rect",
            lambda: viewer_widget._set_sketch_tool("center_rectangle"),
            None,
            "Draw center rectangles in the active sketch.",
            checkable=True,
        ),
        make_action(
            "sketch_line_tool",
            "Line",
            lambda: viewer_widget._set_sketch_tool("line"),
            None,
            "Draw connected sketch lines.",
            checkable=True,
        ),
        make_action(
            "sketch_arc_tool",
            "Arc",
            lambda: viewer_widget._set_sketch_tool("arc"),
            None,
            "Draw 3-point arcs in the active sketch.",
            checkable=True,
        ),
        make_action(
            "sketch_rectangle3_tool",
            "3-Point Rect",
            lambda: viewer_widget._set_sketch_tool("rectangle_3_point"),
            None,
            "Draw rotated 3-point rectangles.",
            checkable=True,
        ),
        make_action(
            "sketch_center_rectangle_tool",
            "Center Rect",
            lambda: viewer_widget._set_sketch_tool("center_rectangle"),
            None,
            "Draw center rectangles in the active sketch.",
            checkable=True,
        ),
        make_action(
            "sketch_circle_tool",
            "Circle",
            lambda: viewer_widget._set_sketch_tool("circle"),
            None,
            "Draw circles in the active sketch.",
            checkable=True,
        ),
        make_action(
            "sketch_extrude",
            "Extrude Sketch",
            viewer_widget._begin_sketch_extrude_tool,
            None,
            "Drag the selected sketch profile into a solid.",
        ),
        make_action(
            "sketch_new_body",
            "New Body",
            viewer_widget._begin_sketch_new_body_tool,
            None,
            "Extrude the selected sketch profile as a separate body.",
        ),
    ):
        sketch_menu.addAction(action)

    tools_menu = window.menuBar().addMenu("&Tools")
    for action in (
        make_action(
            "move_object",
            "Move",
            viewer_widget._begin_object_move_tool,
            "G",
            "Drag the active object along the selected world axis.",
        ),
        make_action(
            "move_object_x",
            "Move X",
            lambda: viewer_widget._begin_object_move_tool_on_axis(
                "X",
                (1.0, 0.0, 0.0),
            ),
            None,
            "Drag the active object along X.",
        ),
        make_action(
            "move_object_y",
            "Move Y",
            lambda: viewer_widget._begin_object_move_tool_on_axis(
                "Y",
                (0.0, 1.0, 0.0),
            ),
            None,
            "Drag the active object along Y.",
        ),
        make_action(
            "move_object_z",
            "Move Z",
            lambda: viewer_widget._begin_object_move_tool_on_axis(
                "Z",
                (0.0, 0.0, 1.0),
            ),
            None,
            "Drag the active object along Z.",
        ),
        make_action(
            "rotate_body",
            "Rotate",
            viewer_widget._begin_object_rotate_tool,
            None,
            "Drag to rotate the active body around the current axis.",
        ),
        make_action(
            "mirror_body",
            "Mirror",
            lambda: viewer_widget._show_pending_command("Mirror"),
            None,
            "Mirror the active body.",
        ),
        make_action(
            "move_selection",
            "Move Selection",
            viewer_widget._begin_selected_move_tool,
            "M",
            "Drag the selected face, edge, or vertex.",
        ),
        make_action(
            "move_selection_normal",
            "Move Normal",
            viewer_widget._begin_selected_move_normal_tool,
            None,
            "Drag the selected face along its normal.",
        ),
        make_action(
            "move_selection_x",
            "Move X",
            lambda: viewer_widget._begin_selected_move_tool_on_axis(
                "X",
                (1.0, 0.0, 0.0),
            ),
            None,
            "Drag selected topology along X.",
        ),
        make_action(
            "move_selection_y",
            "Move Y",
            lambda: viewer_widget._begin_selected_move_tool_on_axis(
                "Y",
                (0.0, 1.0, 0.0),
            ),
            None,
            "Drag selected topology along Y.",
        ),
        make_action(
            "move_selection_z",
            "Move Z",
            lambda: viewer_widget._begin_selected_move_tool_on_axis(
                "Z",
                (0.0, 0.0, 1.0),
            ),
            None,
            "Drag selected topology along Z.",
        ),
        make_action(
            "extrude",
            "Extrude Face",
            viewer_widget._begin_extrude_tool,
            "E",
            "Drag the selected face along its normal.",
        ),
        make_action(
            "extrude_reverse",
            "Extrude Reverse",
            lambda: viewer_widget._extrude_active_top_face(-10.0),
            "Shift+E",
            "Push/pull the selected face inward.",
        ),
        make_action(
            "circle_boss",
            "Circle Boss",
            lambda: viewer_widget._circle_feature_on_selected_face(cut=False),
            "O",
            "Add a centered cylindrical boss on the selected face.",
        ),
        make_action(
            "circle_cut",
            "Circle Cut",
            lambda: viewer_widget._circle_feature_on_selected_face(cut=True),
            "Shift+O",
            "Cut a centered cylindrical hole from the selected face.",
        ),
        make_action(
            "offset_face",
            "Offset Face",
            lambda: viewer_widget._show_pending_command("Offset Face"),
            None,
            "Offset the selected face.",
        ),
        make_action(
            "fillet",
            "Fillet Edge",
            viewer_widget._begin_fillet_tool,
            "R",
            "Drag to set the selected edge fillet radius.",
        ),
        make_action(
            "chamfer",
            "Chamfer Edge",
            viewer_widget._begin_chamfer_tool,
            "C",
            "Drag to set the selected edge chamfer distance.",
        ),
    ):
        tools_menu.addAction(action)

    view_menu = window.menuBar().addMenu("&View")
    view_menu.addAction(
        make_action("fit_all", "Fit All", viewer_widget._fit_all, "F", "Fit scene.")
    )
    view_menu.addAction(
        make_action("home", "Home View", viewer_widget._home_view, "H", "Home view.")
    )
    display_group = QActionGroup(window)
    display_group.setExclusive(True)
    for action in (
        make_action(
            "display_shaded",
            "Shaded",
            lambda: viewer_widget._set_display_mode("shaded"),
            None,
            "Show filled faces.",
            checkable=True,
        ),
        make_action(
            "display_wireframe",
            "Wireframe",
            lambda: viewer_widget._set_display_mode("wireframe"),
            "W",
            "Show wireframe edges only.",
            checkable=True,
        ),
    ):
        display_group.addAction(action)
        view_menu.addAction(action)

    category_group = QActionGroup(window)
    category_group.setExclusive(True)
    for action in (
        make_action(
            "category_select",
            "Select",
            lambda: viewer_widget._set_active_category("select"),
            None,
            "Select model topology.",
            checkable=True,
        ),
        make_action(
            "category_sketch",
            "Sketch",
            lambda: viewer_widget._set_active_category("sketch"),
            None,
            "Sketch on the active face or XY plane.",
            checkable=True,
        ),
        make_action(
            "category_create",
            "Create",
            lambda: viewer_widget._set_active_category("create"),
            None,
            "Create a new body.",
            checkable=True,
        ),
        make_action(
            "category_modify",
            "Modify",
            lambda: viewer_widget._set_active_category("modify"),
            None,
            "Use face and edge modification tools.",
            checkable=True,
        ),
        make_action(
            "category_transform",
            "Transform",
            lambda: viewer_widget._set_active_category("transform"),
            None,
            "Transform the active body.",
            checkable=True,
        ),
        make_action(
            "category_measure",
            "Measure",
            lambda: viewer_widget._show_pending_command("Measure"),
            None,
            "Measure model geometry.",
            checkable=True,
        ),
    ):
        category_group.addAction(action)
        window.addAction(action)

    actions["category_measure"].setVisible(False)

    for local_tool_menu in (
        add_menu,
        commands_menu,
        boolean_menu,
        selection_menu,
        axis_menu,
        sketch_menu,
        tools_menu,
    ):
        local_tool_menu.menuAction().setVisible(False)

    top_toolbar = QToolBar("Project", window)
    top_toolbar.setObjectName("TopToolbar")
    configure_toolbar(top_toolbar, role="top")
    project_label = QLabel("Direct Modeling CAD", window)
    project_label.setObjectName("ProjectLabel")
    project_label.setMinimumWidth(160)
    top_toolbar.addWidget(project_label)
    top_toolbar.addSeparator()
    top_toolbar.addActions(
        [
            actions["undo"],
            actions["redo"],
            actions["save_project"],
            actions["export_step"],
        ]
    )
    top_toolbar.addSeparator()
    top_toolbar.addActions(
        [
            actions["fit_all"],
            actions["home"],
            actions["display_shaded"],
            actions["display_wireframe"],
        ]
    )
    window.addToolBar(Qt.TopToolBarArea, top_toolbar)

    category_toolbar = QToolBar("Main Menu", window)
    category_toolbar.setObjectName("CategoryToolbar")
    configure_toolbar(category_toolbar)
    category_toolbar.addWidget(make_sidebar_section_label("WORKSPACE"))
    category_toolbar.addActions(
        [
            actions["category_select"],
            actions["category_sketch"],
            actions["category_create"],
            actions["category_modify"],
            actions["category_transform"],
        ]
    )
    window.addToolBar(Qt.LeftToolBarArea, category_toolbar)

    command_toolbar = QToolBar("Adaptive", window)
    command_toolbar.setObjectName("CommandToolbar")
    configure_toolbar(command_toolbar, role="context")
    window.addToolBarBreak(Qt.TopToolBarArea)
    window.addToolBar(Qt.TopToolBarArea, command_toolbar)

    selection_mode_toolbar = QToolBar("Selection Mode", window)
    selection_mode_toolbar.setObjectName("SelectionModeToolbar")
    configure_toolbar(selection_mode_toolbar)
    selection_mode_toolbar.addWidget(make_sidebar_section_label("SELECTION"))
    selection_mode_toolbar.addActions(
        [
            actions["select_object"],
            actions["select_face"],
            actions["select_edge"],
            actions["select_vertex"],
        ]
    )
    window.addToolBar(Qt.LeftToolBarArea, selection_mode_toolbar)

    sketch_toolbar = QToolBar("Sketch", window)
    sketch_toolbar.setObjectName("SketchToolbar")
    configure_toolbar(sketch_toolbar)
    sketch_toolbar.addWidget(make_sidebar_section_label("SKETCH TOOLS"))
    sketch_toolbar.addActions(
        [
            actions["sketch_line_tool"],
            actions["sketch_arc_tool"],
            actions["sketch_circle_tool"],
            actions["sketch_center_rectangle_tool"],
            actions["sketch_rectangle3_tool"],
        ]
    )
    sketch_toolbar.addActions(
        [
            actions["start_sketch"],
            actions["new_sketch"],
        ]
    )
    sketch_toolbar.setVisible(False)
    window.addToolBar(Qt.LeftToolBarArea, sketch_toolbar)
    viewer_widget._sketch_toolbar = sketch_toolbar

    view_toolbar = QToolBar("View", window)
    view_toolbar.setObjectName("ViewToolbar")
    configure_toolbar(view_toolbar)
    view_toolbar.addWidget(make_sidebar_section_label("VIEW"))
    view_toolbar.addActions(
        [
            actions["fit_all"],
            actions["home"],
            actions["display_shaded"],
            actions["display_wireframe"],
        ]
    )
    window.addToolBar(Qt.LeftToolBarArea, view_toolbar)

    browser_dock = QDockWidget("Model", window)
    browser_dock.setObjectName("BrowserDock")
    browser_dock.setMinimumWidth(theme.RIGHT_PANEL_WIDTH)
    browser_tabs = QTabWidget(browser_dock)
    browser_tabs.setObjectName("BrowserTabs")
    model_list = QListWidget(browser_tabs)
    model_list.setObjectName("ModelList")
    bodies_list = QListWidget(browser_tabs)
    bodies_list.setObjectName("BodiesList")
    sketches_list = QListWidget(browser_tabs)
    sketches_list.setObjectName("SketchesList")
    history_list = QListWidget(browser_tabs)
    history_list.setObjectName("HistoryList")
    browser_panel = QWidget(browser_dock)
    browser_panel.setObjectName("BrowserPanel")
    browser_layout = QVBoxLayout(browser_panel)
    browser_layout.setContentsMargins(0, 0, 0, 0)
    browser_layout.setSpacing(0)
    properties_header = QLabel("Properties", browser_panel)
    properties_header.setObjectName("PropertiesHeader")
    properties_header.setStyleSheet(f"""
        QLabel#PropertiesHeader {{
            background: {theme.PANEL_BG};
            color: {theme.TEXT_DARK};
            border-top: 1px solid {theme.PANEL_BORDER};
            padding: 12px 14px 6px 14px;
            font-weight: 700;
        }}
        """)
    properties_list = QListWidget(browser_panel)
    properties_list.setObjectName("PropertiesList")
    browser_tabs.addTab(model_list, "Model")
    browser_tabs.addTab(bodies_list, "Bodies")
    browser_tabs.addTab(sketches_list, "Sketches")
    browser_tabs.addTab(history_list, "History")
    browser_layout.addWidget(browser_tabs, 3)
    browser_layout.addWidget(properties_header)
    browser_layout.addWidget(properties_list, 2)
    browser_dock.setWidget(browser_panel)
    window.addDockWidget(Qt.RightDockWidgetArea, browser_dock)

    status_bar = window.statusBar()
    hud_labels = {
        "mode": QLabel(),
        "selection": QLabel(),
        "axis": QLabel(),
        "tool": QLabel(),
        "sketch": QLabel(),
    }
    for name, label in hud_labels.items():
        label.setObjectName(f"Status{name.title()}")
        label.setMinimumWidth(132 if name != "sketch" else 180)
        status_bar.addPermanentWidget(label)
    viewer_widget.attach_hud(hud_labels)
    viewer_widget.attach_actions(actions)
    viewer_widget.attach_command_surface(commands_menu, command_toolbar)
    viewer_widget.attach_browser(
        {
            "model": model_list,
            "bodies": bodies_list,
            "sketches": sketches_list,
            "history": history_list,
            "properties": properties_list,
        }
    )
    status_bar.showMessage("Ready")
    window.resize(1200, 800)
    return MainWindow(
        window=window,
        viewer_widget=viewer_widget,
        viewer=viewer,
        scene=scene,
        navigation=navigation,
        picker=picker,
        actions=actions,
    )
