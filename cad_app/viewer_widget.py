"""Qt viewer widget construction for the CAD main window."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cad_app import theme
from cad_app.navigation import NavigationController
from cad_app.picker import Picker
from cad_app.scene import Scene
from cad_app.types import SelectionKind
from cad_app.ui_sessions import (
    MoveSession,
    SketchSession,
)
from cad_app.viewer import Viewer
from cad_app.viewer_widget_actions import ViewerWidgetActionsMixin
from cad_app.viewer_widget_browser import ViewerWidgetBrowserMixin
from cad_app.viewer_widget_commands import ViewerWidgetCommandsMixin
from cad_app.viewer_widget_events import ViewerWidgetEventMixin
from cad_app.viewer_widget_move_drag import ViewerWidgetMoveDragMixin
from cad_app.viewer_widget_move_tools import ViewerWidgetMoveToolsMixin
from cad_app.viewer_widget_overlays import (
    MoveManipulatorOverlay,
    OrientationGizmoOverlay,
    SelectionBoxOverlay,
    SketchPlaneChooserOverlay,
)
from cad_app.viewer_widget_sketch_dimensions import ViewerWidgetSketchDimensionsMixin
from cad_app.viewer_widget_sketch_operations import ViewerWidgetSketchOperationsMixin
from cad_app.viewer_widget_sketch_planes import ViewerWidgetSketchPlaneMixin
from cad_app.viewer_widget_sketch_revolve import ViewerWidgetSketchRevolveMixin
from cad_app.viewer_widget_state import ViewerWidgetStateMixin
from cad_app.workplane import Workplane

BROWSER_ITEM_ID_ROLE = Qt.UserRole
BROWSER_SELECTION_KIND_ROLE = Qt.UserRole + 1
BROWSER_SELECTION_INDEX_ROLE = Qt.UserRole + 2
BROWSER_COMMAND_ROLE = Qt.UserRole + 3


class ViewerWidget(
    ViewerWidgetEventMixin,
    ViewerWidgetCommandsMixin,
    ViewerWidgetSketchDimensionsMixin,
    ViewerWidgetSketchOperationsMixin,
    ViewerWidgetMoveToolsMixin,
    ViewerWidgetMoveDragMixin,
    ViewerWidgetSketchPlaneMixin,
    ViewerWidgetSketchRevolveMixin,
    ViewerWidgetStateMixin,
    ViewerWidgetBrowserMixin,
    ViewerWidgetActionsMixin,
    QWidget,
):
    def __init__(
        self,
        owner: Viewer,
        scene: Scene,
        navigator: NavigationController,
        picker: Picker,
    ) -> None:
        super().__init__()
        self.setObjectName("viewport")
        self._viewer = owner
        self._scene = scene
        self._picker = picker
        self._navigation = navigator
        self._initial_scene_displayed = False
        self._selection_kind = SelectionKind.OBJECT
        self._hover_selection = None
        self._area_selection = []
        self._selection_press: tuple[int, int] | None = None
        self._selection_drag_start: tuple[int, int] | None = None
        self._selection_drag_current: tuple[int, int] | None = None
        self._selection_filter = "all"
        self._select_through = False
        self._overlapping_selection_menu = None
        self._move_session: MoveSession | None = None
        self._move_axis = (1.0, 0.0, 0.0)
        self._move_axis_name = "X"
        self._move_pixels_to_units = 0.2
        self._sketch_session: SketchSession | None = None
        self._pending_sketch_tool = "center_rectangle"
        self._sketch_extrude_operation = "add"
        self._sketch_plane_hover: str | None = None
        self._active_workplane = Workplane.world_xy()
        self._active_workplane_label = "XY"
        self._active_workplane_host: tuple[str, int] | None = None
        self._selection_source: str | None = None
        self._hud_labels: dict[str, QLabel] = {}
        self._actions: dict[str, QAction] = {}
        self._command_menu = None
        self._command_toolbar = None
        self._command_section_actions: dict[str, Any] = {}
        self._sketch_toolbar: Any = None
        self._tool_popover_updating = False
        self._browser_lists: dict[str, Any] = {}
        self._boolean_target_item_id: str | None = None
        self._active_category = "select"
        self._last_status_text = "Ready"
        self._context_hint_text = ""
        self._orientation_gizmo_enabled = True
        self._orientation_gizmo_overlay_visible = True
        self._orientation_gizmo_press: tuple[int, int] | None = None
        self._orientation_gizmo_dragging = False
        self._dimension_overlay = QLabel(self)
        self._dimension_overlay.setObjectName("DimensionOverlay")
        self._dimension_overlay.setStyleSheet(theme.overlay_stylesheet())
        self._dimension_overlay.hide()
        self._inline_dimension_editors: dict[str, QDoubleSpinBox] = {}
        self._inline_dimension_editor_specs: dict[str, dict[str, Any]] = {}
        self._inline_dimension_editor_updating = False
        self._build_inline_dimension_editors()
        self._edge_dimension_editor = self._inline_dimension_editors["edge"]
        self._edge_dimension_editor_selection = None
        self._edge_dimension_editor_updating = False
        self._context_hint_overlay = QLabel(self)
        self._context_hint_overlay.setObjectName("ContextHintOverlay")
        self._context_hint_overlay.setStyleSheet(theme.overlay_stylesheet())
        self._context_hint_overlay.setWordWrap(True)
        self._context_hint_overlay.hide()
        self._orientation_gizmo_overlay = OrientationGizmoOverlay(self)
        self._orientation_gizmo_overlay.setProperty(
            "perception_object_name",
            "view_cube mini_axes",
        )
        self._orientation_gizmo_overlay.set_axis_name(self._move_axis_name)
        self._orientation_gizmo_overlay.hide()
        self._selection_box_overlay = SelectionBoxOverlay(self)
        self._selection_box_overlay.setProperty(
            "perception_object_name",
            "transform_gizmo",
        )
        self._move_manipulator_overlay = MoveManipulatorOverlay(self)
        self._move_manipulator_overlay.setProperty(
            "perception_object_name",
            "move_manipulator",
        )
        self._sketch_plane_chooser = SketchPlaneChooserOverlay(
            self,
            hover_callback=self._set_sketch_plane_hover,
            activate_callback=self._choose_sketch_plane,
        )
        self._sketch_plane_chooser.hide()
        self._build_tool_popover()
        self.setAttribute(Qt.WA_NativeWindow)
        self.setAttribute(Qt.WA_PaintOnScreen)
        self.setFocusPolicy(Qt.StrongFocus)

    def _build_inline_dimension_editors(self) -> None:
        editor_style = f"""
            QDoubleSpinBox {{
                background: rgba(21, 27, 34, 238);
                color: {theme.TEXT_PRIMARY};
                border: 1px solid rgba(74, 90, 108, 210);
                border-radius: 6px;
                padding: 4px 7px;
                font-weight: 700;
            }}
            """
        for key, label, width in (
            ("edge", "", 150),
            ("box_width", "W", 150),
            ("box_depth", "D", 150),
            ("box_height", "H", 150),
            ("sketch_width", "W", 150),
            ("sketch_height", "H", 150),
            ("sketch_radius", "R", 150),
            ("sketch_inner_radius", "Inner R", 182),
        ):
            editor = QDoubleSpinBox(self)
            object_name = (
                "EdgeDimensionEditor"
                if key == "edge"
                else f"InlineDimensionEditor_{key}"
            )
            editor.setObjectName(object_name)
            editor.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
            editor.setAttribute(Qt.WA_ShowWithoutActivating)
            editor.setFocusPolicy(Qt.ClickFocus)
            editor.setKeyboardTracking(False)
            editor.setDecimals(2)
            editor.setRange(0.001, 1_000_000.0)
            editor.setSuffix(" mm")
            editor.setButtonSymbols(QAbstractSpinBox.NoButtons)
            if label:
                editor.setPrefix(f"{label} ")
            editor.setFixedWidth(width)
            editor.setStyleSheet(editor_style)
            editor.hide()
            editor.editingFinished.connect(
                lambda dimension_key=key: self._commit_inline_dimension_editor(
                    dimension_key
                )
            )
            self._inline_dimension_editors[key] = editor

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

    def _build_tool_popover(self) -> None:
        self._tool_popover = QFrame(self)
        self._tool_popover.setObjectName("tool_popover")
        self._tool_popover.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus
        )
        self._tool_popover.setFrameShape(QFrame.NoFrame)
        self._tool_popover.setAttribute(Qt.WA_StyledBackground, True)
        self._tool_popover.setAttribute(Qt.WA_ShowWithoutActivating)
        self._tool_popover.setStyleSheet(theme.tool_popover_stylesheet())
        self._tool_popover.setFixedWidth(260)
        self._tool_popover_layout_key = None
        layout = QVBoxLayout(self._tool_popover)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        self._tool_popover_title = QLabel("Tool", self._tool_popover)
        self._tool_popover_title.setObjectName("tool_name")
        self._tool_popover_summary = QLabel("", self._tool_popover)
        self._tool_popover_summary.setObjectName("tool_preview_summary")
        self._tool_popover_summary.setWordWrap(True)
        self._tool_distance_label = QLabel("Distance", self._tool_popover)
        self._tool_distance_label.setObjectName("tool_value_label")
        self._tool_distance_input = QDoubleSpinBox(self._tool_popover)
        self._tool_distance_input.setObjectName("tool_distance_input")
        self._tool_distance_input.setDecimals(2)
        self._tool_distance_input.setRange(-1_000_000.0, 1_000_000.0)
        self._tool_distance_input.setSuffix(" mm")
        self._tool_distance_input.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self._tool_distance_input.setKeyboardTracking(False)
        self._tool_distance_input.valueChanged.connect(self._tool_primary_value_changed)
        self._tool_secondary_label = QLabel("Elevation", self._tool_popover)
        self._tool_secondary_label.setObjectName("tool_value_label")
        self._tool_secondary_input = QDoubleSpinBox(self._tool_popover)
        self._tool_secondary_input.setObjectName("tool_secondary_input")
        self._tool_secondary_input.setDecimals(2)
        self._tool_secondary_input.setRange(-1_000_000.0, 1_000_000.0)
        self._tool_secondary_input.setSuffix(" mm")
        self._tool_secondary_input.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self._tool_secondary_input.setKeyboardTracking(False)
        self._tool_secondary_input.valueChanged.connect(
            self._tool_secondary_value_changed
        )
        self._tool_cut_mode_checkbox = QCheckBox("Cut into host", self._tool_popover)
        self._tool_cut_mode_checkbox.setObjectName("tool_cut_mode")
        self._tool_cut_mode_checkbox.toggled.connect(self._tool_cut_mode_changed)

        button_row = QHBoxLayout()
        self._tool_done_button = QPushButton("Done", self._tool_popover)
        self._tool_done_button.setObjectName("tool_done")
        self._tool_done_button.clicked.connect(self._tool_done)
        self._tool_cancel_button = QPushButton("Cancel", self._tool_popover)
        self._tool_cancel_button.setObjectName("tool_cancel")
        self._tool_cancel_button.clicked.connect(self._cancel_active_tool)
        button_row.addWidget(self._tool_done_button)
        button_row.addWidget(self._tool_cancel_button)

        layout.addWidget(self._tool_popover_title)
        layout.addWidget(self._tool_popover_summary)
        layout.addWidget(self._tool_distance_label)
        layout.addWidget(self._tool_distance_input)
        layout.addWidget(self._tool_secondary_label)
        layout.addWidget(self._tool_secondary_input)
        layout.addWidget(self._tool_cut_mode_checkbox)
        layout.addLayout(button_row)
        self._tool_popover.hide()

    def _tool_done(self) -> None:
        if self._sketch_session is not None:
            self._finish_sketch_sequence()
            return
        self._commit_move_session()

    def _refresh_tool_popover(self) -> None:
        if not hasattr(self, "_tool_popover"):
            return
        if self._move_session is None and self._sketch_session is None:
            if not self._tool_popover.isHidden():
                self._tool_popover.hide()
            self._tool_popover_layout_key = None
            return
        was_hidden = self._tool_popover.isHidden()
        if self._move_session is not None:
            layout_key = (
                "move",
                self._move_session.tool,
                self._move_session.target_kind,
                self._move_session.axis_name,
            )
            title = self._move_tool_name(self._move_session)
            if (
                self._move_session.tool == "move"
                and self._move_session.target_kind != "object"
            ):
                title = f"Move {self._move_session.target_kind.value.title()}"
            self._tool_popover_title.setText(title)
            self._tool_popover_summary.setText(
                self._tool_popover_summary_text(self._move_session)
            )
            self._tool_popover_updating = True
            self._configure_primary_tool_input(self._move_session)
            self._configure_secondary_tool_input(self._move_session)
            self._configure_cut_mode_input(self._move_session)
            self._tool_popover_updating = False
            self._tool_distance_label.show()
            self._tool_distance_input.show()
        else:
            layout_key = ("sketch", self._sketch_session.tool)
            self._tool_popover_title.setText(
                f"Sketch {self._sketch_session.tool.replace('_', ' ').title()}"
            )
            self._tool_popover_summary.setText(self._context_hint_text)
            self._tool_distance_label.hide()
            self._tool_distance_input.hide()
            self._tool_secondary_label.hide()
            self._tool_secondary_input.hide()
            self._tool_cut_mode_checkbox.hide()
        if was_hidden or layout_key != self._tool_popover_layout_key:
            self._tool_popover.adjustSize()
            self._tool_popover_layout_key = layout_key
        self._position_tool_popover()
        if was_hidden:
            self._tool_popover.show()
            self._tool_popover.raise_()

    def _position_tool_popover(self) -> None:
        if not hasattr(self, "_tool_popover"):
            return
        margin = 14
        self._tool_popover.adjustSize()
        width = self._tool_popover.width()
        height = self._tool_popover.height()
        bottom_reserved = 70
        candidates = (
            (max(margin, self.width() - width - margin), margin),
            (margin, margin),
            (
                max(margin, self.width() - width - margin),
                max(margin, self.height() - height - margin - bottom_reserved),
            ),
            (margin, max(margin, self.height() - height - margin - bottom_reserved)),
            (max(margin, (self.width() - width) // 2), margin),
        )
        obstacles = self._tool_popover_obstacles()
        x, y = candidates[0]
        best_overlap: int | None = None
        for candidate_x, candidate_y in candidates:
            candidate = QRect(candidate_x, candidate_y, width, height)
            overlap = sum(
                candidate.intersected(obstacle).width()
                * candidate.intersected(obstacle).height()
                for obstacle in obstacles
                if candidate.intersects(obstacle)
            )
            if overlap == 0:
                x, y = candidate_x, candidate_y
                break
            if best_overlap is None or overlap < best_overlap:
                best_overlap = overlap
                x, y = candidate_x, candidate_y
        if self._tool_popover.isWindow():
            self._tool_popover.move(self.mapToGlobal(QPoint(x, y)))
        else:
            self._tool_popover.move(x, y)

    def _tool_popover_obstacles(self) -> list[QRect]:
        obstacles: list[QRect] = []
        for widget_name in (
            "_move_manipulator_overlay",
            "_orientation_gizmo_overlay",
            "_dimension_overlay",
            "_context_hint_overlay",
        ):
            widget = getattr(self, widget_name, None)
            rect = self._child_rect_in_viewport(widget)
            if rect is not None:
                obstacles.append(rect.adjusted(-8, -8, 8, 8))
        for editor in getattr(self, "_inline_dimension_editors", {}).values():
            rect = self._child_rect_in_viewport(editor)
            if rect is not None:
                obstacles.append(rect.adjusted(-8, -8, 8, 8))
        return obstacles

    def _child_rect_in_viewport(self, widget) -> QRect | None:
        if widget is None or widget.isHidden():
            return None
        if widget.isWindow():
            top_left = self.mapFromGlobal(widget.geometry().topLeft())
        else:
            top_left = widget.pos()
        return QRect(top_left, widget.size())

    @staticmethod
    def _tool_popover_summary_text(session: MoveSession) -> str:
        if session.tool in {"extrude", "sketch_extrude"}:
            operation = "cut" if session.operation == "cut" else "extrude"
            if (
                session.tool == "sketch_extrude"
                and session.operation == "auto"
                and session.distance < 0
            ):
                operation = "auto cut"
            return (
                f"Direction: {session.axis_name}; "
                f"{operation} {abs(session.distance):.2f} mm"
            )
        if session.tool == "sketch_revolve":
            return (
                f"Axis: {session.axis_name}; angle {session.distance:.2f} deg; "
                f"elevation {session.elevation:.2f} mm"
            )
        if session.tool == "rotate":
            return f"Axis: {session.axis_name}; angle {session.distance:.2f} deg"
        return f"Direction: {session.axis_name}; distance {session.distance:.2f}"

    def _configure_primary_tool_input(self, session: MoveSession) -> None:
        if session.tool in {"rotate", "sketch_revolve"}:
            self._tool_distance_label.setText("Angle")
            self._tool_distance_input.setRange(-360_000.0, 360_000.0)
            self._tool_distance_input.setSuffix(" deg")
        elif session.tool in {"fillet", "chamfer", "fillet_chamfer"}:
            self._tool_distance_label.setText(
                "Radius/Distance"
                if session.tool == "fillet_chamfer"
                else ("Radius" if session.tool == "fillet" else "Distance")
            )
            self._tool_distance_input.setRange(
                -1_000_000.0 if session.tool == "fillet_chamfer" else 0.001,
                1_000_000.0,
            )
            self._tool_distance_input.setSuffix(" mm")
        else:
            self._tool_distance_label.setText("Distance")
            self._tool_distance_input.setRange(-1_000_000.0, 1_000_000.0)
            self._tool_distance_input.setSuffix(" mm")
        self._tool_distance_input.setValue(float(session.distance))

    def _configure_secondary_tool_input(self, session: MoveSession) -> None:
        if session.tool != "sketch_revolve":
            self._tool_secondary_label.hide()
            self._tool_secondary_input.hide()
            return
        self._tool_secondary_label.setText("Elevation")
        self._tool_secondary_input.setRange(-1_000_000.0, 1_000_000.0)
        self._tool_secondary_input.setSuffix(" mm")
        self._tool_secondary_input.setValue(float(session.elevation))
        self._tool_secondary_label.show()
        self._tool_secondary_input.show()

    def _configure_cut_mode_input(self, session: MoveSession) -> None:
        show_cut_mode = (
            session.tool == "sketch_extrude"
            and session.operation != "new_body"
            and self._selected_sketch_profile_has_host()
        )
        if not show_cut_mode:
            self._tool_cut_mode_checkbox.hide()
            return
        self._tool_cut_mode_checkbox.setChecked(session.operation == "cut")
        self._tool_cut_mode_checkbox.show()

    def _tool_primary_value_changed(self, value: float) -> None:
        if self._tool_popover_updating or self._move_session is None:
            return
        self._move_session.distance = float(value)
        self._update_tool_parameter_preview()

    def _tool_secondary_value_changed(self, value: float) -> None:
        if self._tool_popover_updating or self._move_session is None:
            return
        if self._move_session.tool == "sketch_revolve":
            self._move_session.elevation = float(value)
        self._update_tool_parameter_preview()

    def _tool_cut_mode_changed(self, checked: bool) -> None:
        if self._tool_popover_updating or self._move_session is None:
            return
        if self._move_session.tool != "sketch_extrude":
            return
        self._move_session.operation = "cut" if checked else "auto"
        if checked:
            self._move_session.distance = -abs(self._move_session.distance or 10.0)
            self._set_context_hint("Extrude will subtract from the host body")
        else:
            self._set_context_hint(
                "Extrude auto: outward adds, inward subtracts from the host"
            )
        self._update_tool_parameter_preview()

    def _update_tool_parameter_preview(self) -> None:
        if self._move_session is None:
            return
        self._update_move_preview()
        self._show_dimension_overlay(
            self._move_overlay_label(self._move_session),
            self.width() // 2,
            self.height() // 2,
        )
        self._refresh_hud()


def create_viewer_widget(
    viewer: Viewer,
    scene: Scene,
    navigation: NavigationController,
    picker: Picker,
):
    return ViewerWidget(viewer, scene, navigation, picker)
