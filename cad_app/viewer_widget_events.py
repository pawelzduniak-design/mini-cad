"""Qt event routing, picking, and hover preview for ViewerWidget."""

from __future__ import annotations

import logging
import math

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtWidgets import QMenu

from cad_app.commands import CommandError
from cad_app.sketch import is_sketch_object, is_sketch_profile
from cad_app.types import SelectionKind, SelectionRef

LOGGER = logging.getLogger(__name__)


class ViewerWidgetEventMixin:
    def showEvent(self, event) -> None:
        if not self._viewer.is_initialized:
            self._viewer.initialize(self)
            self._navigation.attach_view(self._viewer.view)
            QTimer.singleShot(0, self._display_initial_scene)
            QTimer.singleShot(100, self._refit_initial_scene)
            QTimer.singleShot(250, self._position_orientation_gizmo_overlay)
        # Qt.Tool top-level overlays (move manipulator, selection box)
        # like to appear together with the parent on the first show
        # event regardless of their __init__ hide(). Force them off
        # until a move/extrude tool actually starts.
        if hasattr(self, "_move_manipulator_overlay"):
            self._move_manipulator_overlay.hide()
        if hasattr(self, "_selection_box_overlay"):
            self._selection_box_overlay.hide()
        if hasattr(self, "_tool_popover"):
            self._tool_popover.hide()
        super().showEvent(event)

    def resizeEvent(self, event) -> None:
        self._viewer.resize()
        self._position_context_hint()
        self._position_edge_dimension_editor()
        self._position_grid_axis_labels_overlay()
        self._position_orientation_gizmo_overlay()
        self._position_move_manipulator_overlay()
        self._position_selection_box_overlay()
        self._position_sketch_plane_chooser()
        self._position_tool_popover()
        super().resizeEvent(event)
        self._schedule_viewport_resize_refresh()

    def focusInEvent(self, event) -> None:
        self._schedule_viewport_activation_refresh()
        super().focusInEvent(event)

    def hideEvent(self, event) -> None:
        self._hide_edge_dimension_editor()
        super().hideEvent(event)

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.ActivationChange and self.window().isActiveWindow():
            self._schedule_viewport_activation_refresh()
        super().changeEvent(event)

    def event(self, event) -> bool:
        if event.type() in {QEvent.WindowActivate, QEvent.ApplicationActivate}:
            self._schedule_viewport_activation_refresh()
        return super().event(event)

    def _schedule_viewport_activation_refresh(self) -> None:
        if not self._viewer.is_initialized:
            return
        self._refresh_viewport_after_activation()
        QTimer.singleShot(0, self._refresh_viewport_after_activation)
        QTimer.singleShot(120, self._refresh_viewport_after_activation)

    def _schedule_viewport_resize_refresh(self) -> None:
        if not self._viewer.is_initialized:
            return
        self._refresh_viewport_after_resize()
        QTimer.singleShot(0, self._refresh_viewport_after_resize)
        QTimer.singleShot(90, self._refresh_viewport_after_resize)
        QTimer.singleShot(240, self._refresh_viewport_after_resize_rebind)
        QTimer.singleShot(420, self._refresh_viewport_after_resize)
        QTimer.singleShot(700, self._refresh_viewport_after_resize_rebind)
        QTimer.singleShot(1100, self._refresh_viewport_after_resize)

    def _refresh_viewport_after_resize(self) -> None:
        if not self._viewer.is_initialized:
            return
        self._viewer.refresh_native_window()
        self._position_edge_dimension_editor()
        self._position_grid_axis_labels_overlay()
        self._position_orientation_gizmo_overlay()
        self._position_move_manipulator_overlay()
        self._position_selection_box_overlay()
        self._position_sketch_plane_chooser()
        self._position_tool_popover()
        self.update()

    def _refresh_viewport_after_resize_rebind(self) -> None:
        if not self._viewer.is_initialized:
            return
        self._viewer.refresh_native_window(rebind=True)
        self._position_grid_axis_labels_overlay()
        self._position_orientation_gizmo_overlay()
        self.update()

    def _refresh_viewport_after_activation(self) -> None:
        if not self._viewer.is_initialized:
            return
        self._viewer.refresh_native_window()
        self._position_edge_dimension_editor()
        self.update()

    def paintEngine(self):
        return None

    def _display_initial_scene(self) -> None:
        if self._initial_scene_displayed or not self._viewer.is_initialized:
            return
        LOGGER.info("Initial scene display started")
        self._viewer.resize()
        self._viewer.display_scene(self._scene)
        self._viewer.update_view()
        if len(self._scene) == 0:
            self._set_context_hint("Start: New Sketch, or import STEP from File")
        else:
            self._set_context_hint("Select geometry, then choose an available action")
        # If we already entered sketch mode before the viewer was ready
        # (the common empty-project startup path), align the camera with
        # the workplane now so the user draws on a flat 2D-looking grid
        # instead of a tilted isometric projection.
        if self._sketch_session is not None:
            self._navigation.view_workplane(self._sketch_session.workplane)
            self._viewer.display_sketch_plane_marker(self._sketch_session.workplane)
        self._navigation.capture_home()
        self._position_grid_axis_labels_overlay()
        self._position_orientation_gizmo_overlay()
        # Make sure no move/extrude affordance leaks into the startup
        # screen. _position_move_manipulator_overlay hides itself when
        # no session owns it.
        self._position_move_manipulator_overlay()
        if hasattr(self, "_selection_box_overlay"):
            self._selection_box_overlay.hide()
        QTimer.singleShot(0, self._position_orientation_gizmo_overlay)
        QTimer.singleShot(0, self._position_move_manipulator_overlay)
        QTimer.singleShot(220, self._finish_initial_scene_display)
        LOGGER.info("Initial scene display queued for native refresh")

    def _finish_initial_scene_display(self) -> None:
        if self._initial_scene_displayed or not self._viewer.is_initialized:
            return
        self._viewer.resize()
        self._viewer.update_view()
        self._viewer.refresh_native_window()
        self._position_grid_axis_labels_overlay()
        self._position_orientation_gizmo_overlay()
        window = self.window()
        if window is not None and window.isVisible():
            window.raise_()
            window.activateWindow()
            self.setFocus()
        self._schedule_viewport_activation_refresh()
        self._initial_scene_displayed = True
        LOGGER.info("Initial scene display finished")

    def _refit_initial_scene(self) -> None:
        if not self._viewer.is_initialized:
            return
        self._viewer.fit_all()
        self._viewer.update_view()
        self._navigation.capture_home()
        self._position_grid_axis_labels_overlay()
        self._position_orientation_gizmo_overlay()
        self._position_sketch_plane_chooser()

    def _position_grid_axis_labels_overlay(self) -> None:
        # Grid labels are native AIS_TextLabel objects. Qt child labels over the
        # native OCC window can black out the viewport after maximize/resize on
        # Windows, so this hook intentionally stays a no-op.
        return

    def _position_orientation_gizmo_overlay(self) -> None:
        if not hasattr(self, "_orientation_gizmo_overlay"):
            return
        if (
            not self._orientation_gizmo_enabled
            or not self._orientation_gizmo_overlay_visible
        ):
            self._orientation_gizmo_overlay.hide()
            return
        left, top, size = self._orientation_gizmo_rect()
        self._orientation_gizmo_overlay.setFixedSize(size, size)
        self._orientation_gizmo_overlay.move(left, top)
        self._orientation_gizmo_overlay.show()
        self._orientation_gizmo_overlay.raise_()

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
            # Shift + left-click during a Rotate session re-picks the
            # rotation pivot from whatever vertex / edge / face is under
            # the cursor, giving the user a "movable pivot" without
            # exiting the tool.
            if (
                event.modifiers() & Qt.ShiftModifier
                and self._move_session.tool == "rotate"
                and self._set_rotate_pivot_from_click(position.x(), position.y())
            ):
                event.accept()
                return
            if hasattr(self, "_set_topology_move_view_fallback"):
                self._set_topology_move_view_fallback()
            self._begin_move_drag(position.x(), position.y())
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            self._selection_press = (position.x(), position.y())
            self._selection_drag_start = None
            self._selection_drag_current = None
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
            if self._move_session is not None and hasattr(
                self, "_refresh_move_manipulator"
            ):
                self._refresh_move_manipulator()
            event.accept()
            return
        if event.buttons() & Qt.RightButton:
            self._navigation.pan_to(position.x(), position.y())
            # Keep manipulator arrows aligned with the camera while the
            # user pans/orbits live; the screen projection of world
            # X/Y/Z changes every frame.
            if self._move_session is not None and hasattr(
                self, "_refresh_move_manipulator"
            ):
                self._refresh_move_manipulator()
            event.accept()
            return
        if event.buttons() & Qt.MiddleButton:
            self._navigation.orbit_to(position.x(), position.y())
            if self._move_session is not None and hasattr(
                self, "_refresh_move_manipulator"
            ):
                self._refresh_move_manipulator()
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
        if self._selection_press is not None and event.buttons() & Qt.LeftButton:
            start_x, start_y = self._selection_press
            distance = math.hypot(position.x() - start_x, position.y() - start_y)
            if self._selection_drag_start is not None or distance >= 5.0:
                self._update_area_selection_drag(position.x(), position.y())
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
                self._show_status("Orbit view")
            else:
                view_target = self._orientation_gizmo_view_at(
                    position.x(),
                    position.y(),
                )
                if view_target is not None:
                    axis, positive, label = view_target
                    self._apply_orientation_gizmo_target(axis, positive, label)
                else:
                    # No Qt-overlay button matched - hand the click to
                    # OCCT so its AIS_ViewCube (rendered in the same
                    # corner) gets the chance to animate to whichever
                    # of its faces was actually clicked. Without this
                    # the cube was visually present but inert.
                    self._forward_click_to_view_cube(
                        position.x(),
                        position.y(),
                    )
            self._orientation_gizmo_press = None
            self._orientation_gizmo_dragging = False
            event.accept()
            return
        if event.button() == Qt.RightButton:
            self._navigation.end_pan()
            self._position_edge_dimension_editor()
            event.accept()
            return
        if event.button() == Qt.MiddleButton:
            self._navigation.end_orbit()
            self._position_edge_dimension_editor()
            event.accept()
            return
        if event.button() == Qt.LeftButton and self._move_session is not None:
            self._commit_move_session()
            event.accept()
            return
        if event.button() == Qt.LeftButton and self._sketch_session is not None:
            snap = bool(event.modifiers() & Qt.ControlModifier)
            self._commit_sketch_drag(position.x(), position.y(), snap=snap)
            event.accept()
            return
        if event.button() == Qt.LeftButton and self._selection_press is not None:
            if self._selection_drag_start is not None:
                self._finish_area_selection_drag(position.x(), position.y())
            else:
                additive = bool(event.modifiers() & Qt.ControlModifier)
                self._select_at(position.x(), position.y(), additive=additive)
            self._selection_press = None
            self._selection_drag_start = None
            self._selection_drag_current = None
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
        self._position_edge_dimension_editor()
        # Zoom changes the on-screen scale of the move manipulator's
        # axis vectors; re-project them so the X/Y/Z arrows stay
        # accurate after a wheel zoom.
        if self._move_session is not None and hasattr(
            self, "_refresh_move_manipulator"
        ):
            self._refresh_move_manipulator()
        event.accept()

    def _refresh_overlays_after_camera_change(self) -> None:
        self._position_edge_dimension_editor()
        self._position_grid_axis_labels_overlay()
        # Re-project the X/Y/Z arrows for the active move/rotate tool.
        # Without this the manipulator stays pinned to its arrows'
        # original screen vectors and ends up pointing the wrong way
        # after the user orbits or zooms the camera.
        if hasattr(self, "_refresh_move_manipulator"):
            self._refresh_move_manipulator()
        else:
            self._position_move_manipulator_overlay()
        if self._move_session is not None:
            self._update_extrude_affordance()
            self._update_move_preview()
            self._show_dimension_overlay(
                self._move_overlay_label(self._move_session),
                self.width() // 2,
                self.height() // 2,
            )
        self._refresh_hud()

    def keyPressEvent(self, event) -> None:
        if self._selection_drag_start is not None:
            if event.key() == Qt.Key_Escape:
                self._cancel_area_selection_drag()
                return
            if event.key() == Qt.Key_Tab:
                self._cycle_selection_filter()
                return
            if event.key() == Qt.Key_B:
                self._set_selection_filter("bodies")
                return
            if event.key() == Qt.Key_F:
                self._set_selection_filter("faces")
                return
            if event.key() == Qt.Key_E:
                self._set_selection_filter("edges")
                return
        if event.key() == Qt.Key_Space and self._handle_spacebar_sketch_start():
            return
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
        if event.key() == Qt.Key_T and not event.modifiers():
            self._toggle_select_through()
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
            if event.modifiers() & Qt.ShiftModifier:
                self._set_sketch_tool("circle_diameter")
            else:
                self._set_sketch_tool("circle")
            return
        if event.key() == Qt.Key_E:
            if event.modifiers() & Qt.ShiftModifier:
                self._extrude_active_top_face(-10.0)
            else:
                self._begin_push_pull_tool()
            return
        if event.key() == Qt.Key_G:
            self._begin_unified_move_tool()
            return
        if event.key() == Qt.Key_M:
            self._begin_unified_move_tool()
            return
        if event.key() == Qt.Key_R:
            self._begin_fillet_chamfer_tool()
            return
        super().keyPressEvent(event)

    def _select_at(self, x: int, y: int, *, additive: bool = False) -> None:
        if not self._viewer.is_initialized:
            return
        view_x, view_y = self._to_view_pixels(x, y)
        filter_name = "all" if self._select_through else self._selection_kind
        LOGGER.debug(
            "Pick requested kind=%s select_through=%s logical=(%d,%d) "
            "view=(%d,%d) dpr=%.2f",
            (
                self._selection_kind.value
                if isinstance(filter_name, SelectionKind)
                else filter_name
            ),
            self._select_through,
            x,
            y,
            view_x,
            view_y,
            self.devicePixelRatioF(),
        )
        if not additive:
            self._viewer.clear_selection_marker(redraw=False)
        self._area_selection = []
        candidates = self._picker.pick_candidates_at(
            self._viewer.view,
            view_x,
            view_y,
            filter_name,
            select_through=self._select_through,
        )
        candidates = self._visible_viewport_candidates(candidates)
        if self._select_through and len(candidates) > 1:
            if self._show_overlapping_selection_menu(candidates, x, y, additive):
                self._show_status("Select Through: choose item")
                return
        candidate = candidates[0] if candidates else None
        pick_result = None if candidate is None else candidate.result
        selection = None if candidate is None else candidate.selection
        self._apply_selection_result(
            selection,
            pick_result,
            x=x,
            y=y,
            view_x=view_x,
            view_y=view_y,
            additive=additive,
        )

    def _apply_selection_result(
        self,
        selection: SelectionRef | None,
        pick_result,
        *,
        x: int | None = None,
        y: int | None = None,
        view_x: int | None = None,
        view_y: int | None = None,
        additive: bool = False,
    ) -> None:
        if additive:
            if selection is None:
                self._show_status("No selection")
                return
            self._toggle_multi_selection(selection, pick_result)
            return
        self._scene.set_selection(selection)
        self._selection_source = "viewport" if selection is not None else None
        if selection is None:
            self._viewer.clear_selection(redraw=False)
            self._viewer.clear_selection_marker(redraw=False)
            self._viewer.clear_hover_marker(redraw=False)
            self._viewer.clear_dimension_label(redraw=False)
            self._hide_edge_dimension_editor()
            self._viewer.update_view()
            self._show_status("No selection")
            if (
                x is not None
                and y is not None
                and view_x is not None
                and view_y is not None
            ):
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
            selected_profile = is_sketch_profile(
                self._scene.get(selection.item_id).meta
            )
            self._active_category = "select"
            self._viewer.clear_selection(redraw=False)
            self._viewer.clear_hover_marker(redraw=False)
            if selected_profile:
                pass
            elif self._box_dimensions_editable(selection.item_id):
                self._show_selected_box_dimensions()
            else:
                self._viewer.clear_dimension_label(redraw=False)
            self._hide_edge_dimension_editor()
            self._viewer.display_selection_marker(
                self._picker.subshape(
                    selection.item_id, selection.kind, selection.index
                )
            )
            if selected_profile:
                self._show_selected_sketch_dimensions()
                dimension_summary = self._selected_sketch_dimension_summary()
                suffix = f" - {dimension_summary }" if dimension_summary else ""
                self._set_context_hint(
                    "Sketch Profile selected - edit, move, extrude, revolve, or delete"
                )
                self._show_status(f"Selected Sketch Profile{suffix }")
            else:
                if self._box_dimensions_editable(selection.item_id):
                    self._set_context_hint(
                        "Face selected - edit dimensions, extrude, or move face"
                    )
                else:
                    self._set_context_hint("Face selected - choose Extrude or Move")
                self._show_status(f"Selected face {selection .index }")
            self._refresh_hud()
            if pick_result is not None:
                LOGGER.info(
                    "Selected face item_id=%s index=%d %s depth=%.2f "
                    "logical=(%s,%s) view=(%s,%s)",
                    selection.item_id,
                    selection.index,
                    self._face_orientation_label(selection.item_id, selection.index),
                    pick_result.depth,
                    x,
                    y,
                    view_x,
                    view_y,
                )
            return
        if selection.kind == SelectionKind.OBJECT:
            self._active_category = "select"
            self._viewer.clear_selection(redraw=False)
            self._viewer.clear_hover_marker(redraw=False)
            if self._box_dimensions_editable(selection.item_id):
                self._show_selected_box_dimensions()
            else:
                self._viewer.clear_dimension_label(redraw=False)
            self._hide_edge_dimension_editor()
            self._viewer.display_selection_marker(
                self._picker.subshape(
                    selection.item_id, selection.kind, selection.index
                )
            )
            if self._box_dimensions_editable(selection.item_id):
                self._set_context_hint("Body selected - choose Move or Rotate")
            else:
                self._set_context_hint("Body selected - choose Move")
            self._show_status(f"Selected body {selection .item_id [:8 ]}")
            self._refresh_hud()
            if pick_result is not None:
                LOGGER.info(
                    "Selected object item_id=%s depth=%.2f",
                    selection.item_id,
                    pick_result.depth,
                )
            return

        self._viewer.clear_selection(redraw=False)
        self._viewer.clear_hover_marker(redraw=False)
        self._viewer.clear_dimension_label(redraw=False)
        self._hide_edge_dimension_editor()
        self._active_category = "select"
        scene_object = self._scene.get(selection.item_id)
        self._viewer.display_selection_marker(
            self._picker.subshape(selection.item_id, selection.kind, selection.index),
            scene_object.meta,
        )
        edge_measurement = None
        if selection.kind == SelectionKind.EDGE:
            edge_measurement = self._selected_edge_measurement()
            if edge_measurement is not None:
                self._display_edge_measurement(edge_measurement)
                self._show_edge_dimension_editor(selection, edge_measurement)
        if selection.kind == SelectionKind.EDGE and edge_measurement is not None:
            if self._selected_edge_is_circular():
                self._set_context_hint(
                    "Circular edge selected - Move, Fillet/Chamfer, or Thread"
                )
            else:
                self._set_context_hint("Edge selected - choose Move or Fillet/Chamfer")
        else:
            self._set_context_hint(
                f"{selection .kind .value .title ()} selected - "
                "choose an available tool"
            )
        if pick_result is not None:
            label = (
                "edge" if selection.kind == SelectionKind.EDGE else selection.kind.value
            )
            measurement_suffix = (
                f", {edge_measurement.length:.2f} mm"
                if edge_measurement is not None
                else ""
            )
            self._show_status(
                f"Selected {label } {selection .index }"
                f"{measurement_suffix}"
                f" ({pick_result .distance_px :.1f}px)"
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

    def _toggle_multi_selection(self, selection: SelectionRef, pick_result) -> None:
        current = list(self._scene.selection_refs())
        if selection in current:
            current.remove(selection)
            action = "removed"
        else:
            current.append(selection)
            action = "added"
        if len(current) <= 1:
            next_selection = current[0] if current else None
            self._apply_selection_result(next_selection, pick_result)
            return

        self._scene.set_selections(tuple(current))
        self._selection_source = "viewport"
        self._hover_selection = None
        self._viewer.clear_selection(redraw=False)
        self._viewer.clear_hover_marker(redraw=False)
        self._viewer.clear_dimension_label(redraw=False)
        self._hide_edge_dimension_editor()
        self._display_current_selection_markers()
        self._apply_multi_selection_context(action=action)

    def _display_current_selection_markers(self) -> None:
        marker_shapes = []
        valid_selections: list[SelectionRef] = []
        for selection in self._scene.selection_refs():
            if selection.item_id not in self._scene:
                continue
            scene_object = self._scene.get(selection.item_id)
            try:
                shape = (
                    scene_object.shape
                    if selection.kind == SelectionKind.OBJECT
                    else self._picker.subshape(
                        selection.item_id,
                        selection.kind,
                        selection.index,
                    )
                )
            except (CommandError, IndexError, ValueError):
                LOGGER.debug(
                    "Selection marker skipped item_id=%s kind=%s index=%s",
                    selection.item_id,
                    selection.kind.value,
                    selection.index,
                    exc_info=True,
                )
                continue
            valid_selections.append(selection)
            marker_shapes.append((shape, scene_object.meta))
        if len(valid_selections) != len(self._scene.selection_refs()):
            self._scene.set_selections(tuple(valid_selections))
        if not marker_shapes:
            self._viewer.clear_selection_marker(redraw=True)
            return
        self._viewer.display_selection_markers(marker_shapes)

    def _apply_multi_selection_context(self, *, action: str = "selected") -> None:
        selections = self._scene.selection_refs()
        if not selections:
            self._selection_source = None
            self._viewer.clear_selection_marker(redraw=False)
            self._viewer.clear_hover_marker(redraw=False)
            self._viewer.clear_dimension_label(redraw=False)
            self._hide_edge_dimension_editor()
            self._viewer.update_view()
            self._show_status("Selection cleared")
            self._refresh_action_state()
            return
        if len(selections) == 1:
            self._apply_selection_result(selections[0], None)
            return

        metas = [self._scene.get(selection.item_id).meta for selection in selections]
        kinds = {selection.kind for selection in selections}
        count = len(selections)
        if all(is_sketch_profile(meta) for meta in metas):
            self._active_category = "select"
            self._selection_kind = SelectionKind.FACE
            self._set_context_hint(
                "Multiple sketch profiles selected - choose Move, Extrude, "
                "New Body, or Delete"
            )
            status = f"Selected {count} sketch profiles"
        elif (
            len(kinds) == 1
            and SelectionKind.OBJECT in kinds
            and all(not is_sketch_object(meta) for meta in metas)
        ):
            self._active_category = "select"
            self._selection_kind = SelectionKind.OBJECT
            self._set_context_hint("Multiple bodies selected - choose Move")
            status = f"Selected {count} bodies"
        elif len(kinds) == 1:
            kind = next(iter(kinds))
            self._active_category = "select"
            self._selection_kind = kind
            self._set_context_hint(
                f"Multiple {kind.value}s selected - choose an available tool"
            )
            status = f"Selected {count} {kind.value}s"
        else:
            self._active_category = "select"
            self._set_context_hint("Multiple mixed items selected")
            status = f"Selected {count} items"
        if action == "removed":
            status = f"{status} (removed one)"
        elif action == "added":
            status = f"{status} (added one)"
        self._show_status(status)
        self._refresh_hud()
        self._refresh_action_state()

    def _show_overlapping_selection_menu(
        self,
        candidates,
        x: int,
        y: int,
        additive: bool = False,
    ) -> bool:
        if not self.isVisible():
            return False
        menu = QMenu(self)
        menu.setObjectName("OverlappingSelectionMenu")
        for candidate in candidates[:14]:
            action = menu.addAction(candidate.label)
            action.triggered.connect(
                lambda _checked=False, current=candidate: (
                    self._apply_selection_candidate(current, additive=additive)
                )
            )
        self._overlapping_selection_menu = menu
        menu.aboutToHide.connect(self._clear_overlapping_selection_menu)
        menu.popup(self.mapToGlobal(QPoint(x, y)))
        return True

    def _clear_overlapping_selection_menu(self) -> None:
        self._overlapping_selection_menu = None

    def _apply_selection_candidate(self, candidate, *, additive: bool = False) -> None:
        self._area_selection = []
        if not additive:
            self._viewer.clear_selection_marker(redraw=False)
        self._apply_selection_result(
            candidate.selection,
            candidate.result,
            additive=additive,
        )
        self._clear_overlapping_selection_menu()

    def _position_selection_box_overlay(self) -> None:
        if not hasattr(self, "_selection_box_overlay"):
            return
        self._selection_box_overlay.setGeometry(self.rect())
        if not self._selection_box_overlay.isHidden():
            self._selection_box_overlay.raise_()

    def _update_area_selection_drag(self, x: int, y: int) -> None:
        if self._selection_press is None:
            return
        started = self._selection_drag_start is None
        if started:
            self._selection_drag_start = self._selection_press
            self._set_context_hint(
                "Area selection: left-to-right contains, right-to-left crosses; "
                "Tab/B/F/E filters"
            )
            filter_label = self._selection_filter_label(self._selection_filter)
            self._show_status(f"Area selection: {filter_label}")
        self._selection_drag_current = (x, y)
        self._selection_box_overlay.update_box(
            self._selection_drag_start,
            self._selection_drag_current,
            self._selection_filter_label(self._selection_filter),
        )

    def _finish_area_selection_drag(self, x: int, y: int) -> None:
        if self._selection_drag_start is None:
            return
        start = self._selection_drag_start
        end = (x, y)
        require_containment = end[0] >= start[0]
        start_view = self._to_view_pixels(*start)
        end_view = self._to_view_pixels(*end)
        selections = self._picker.area_select(
            self._viewer.view,
            start_view,
            end_view,
            self._selection_filter,
            require_containment=require_containment,
        )
        self._selection_box_overlay.clear()
        self._area_selection = selections
        if not selections:
            self._apply_selection_result(None, None)
            self._show_status("Area selected 0 items")
            return

        if len(selections) == 1:
            self._apply_selection_result(selections[0], None)
        else:
            self._scene.set_selections(tuple(selections))
            self._selection_source = "viewport"
            self._hover_selection = None
            self._viewer.clear_selection(redraw=False)
            self._viewer.clear_hover_marker(redraw=False)
            self._viewer.clear_dimension_label(redraw=False)
            self._display_current_selection_markers()
            self._apply_multi_selection_context()
        filter_label = self._selection_filter_label(self._selection_filter)
        mode_label = "inside" if require_containment else "crossing"
        if len(selections) == 1:
            self._set_context_hint(
                f"Area selected 1 item ({filter_label}, {mode_label})"
            )
        elif self._selected_body_count() == len(selections):
            self._set_context_hint(
                f"Area selected {len(selections)} bodies ({filter_label}, "
                f"{mode_label}); choose Move"
            )
        elif self._selected_sketch_profile_count() == len(selections):
            self._set_context_hint(
                f"Area selected {len(selections)} sketch profiles "
                f"({filter_label}, {mode_label}); choose Move, Extrude Sketch, "
                "New Body, or Delete"
            )
        else:
            self._set_context_hint(
                f"Area selected {len(selections)} items ({filter_label}, "
                f"{mode_label})"
            )
        self._show_status(f"Area selected {len(selections)} items")
        LOGGER.info(
            "Area selected count=%d filter=%s mode=%s",
            len(selections),
            self._selection_filter,
            mode_label,
        )

    def _cancel_area_selection_drag(self) -> None:
        self._selection_box_overlay.clear()
        self._selection_press = None
        self._selection_drag_start = None
        self._selection_drag_current = None
        self._show_status("Area selection cancelled")

    def _cycle_selection_filter(self) -> None:
        filters = ("all", "bodies", "faces", "edges")
        index = filters.index(self._selection_filter)
        self._set_selection_filter(filters[(index + 1) % len(filters)])

    def _set_selection_filter(self, filter_name: str) -> None:
        labels = self._selection_filter_labels()
        if filter_name not in labels:
            raise ValueError(f"Unsupported selection filter: {filter_name}")
        self._selection_filter = filter_name
        if (
            self._selection_drag_start is not None
            and self._selection_drag_current is not None
        ):
            self._selection_box_overlay.update_box(
                self._selection_drag_start,
                self._selection_drag_current,
                self._selection_filter_label(filter_name),
            )
        self._show_status(
            f"Selection filter: {self._selection_filter_label(filter_name)}"
        )

    def _selection_filter_label(self, filter_name: str) -> str:
        return self._selection_filter_labels()[filter_name]

    @staticmethod
    def _selection_filter_labels() -> dict[str, str]:
        return {
            "all": "All Items",
            "bodies": "Bodies Only",
            "faces": "Faces Only",
            "edges": "Edges Only",
        }

    def _toggle_select_through(self) -> None:
        self._select_through = not self._select_through
        action = self._actions.get("select_through")
        if action is not None:
            action.setChecked(self._select_through)
        if self._select_through:
            self._set_context_hint(
                "Select Through: click overlapping geometry and choose from the list"
            )
            self._show_status("Select Through on")
        else:
            self._set_context_hint("Select an object, face, edge, or vertex")
            self._show_status("Select Through off")
        self._refresh_action_state()

    def _preview_at(self, x: int, y: int) -> None:
        if not self._viewer.is_initialized:
            return
        view_x, view_y = self._to_view_pixels(x, y)
        candidates = self._visible_viewport_candidates(
            self._picker.pick_candidates_at(
                self._viewer.view,
                view_x,
                view_y,
                self._selection_kind,
            )
        )
        pick_result = None if not candidates else candidates[0].result
        selection = None if pick_result is None else pick_result.selection
        if selection == self._hover_selection:
            return

        self._hover_selection = selection
        self._viewer.clear_hover_marker(redraw=False)
        if selection is None:
            self._viewer.update_view()
            return

        scene_object = self._scene.get(selection.item_id)
        self._viewer.display_hover_marker(
            self._picker.subshape(selection.item_id, selection.kind, selection.index),
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

    def _visible_viewport_candidates(self, candidates):
        if getattr(self._viewer, "show_sketch_geometry", False):
            return candidates
        return [
            candidate
            for candidate in candidates
            if not is_sketch_object(self._scene.get(candidate.selection.item_id).meta)
        ]

    def _to_view_pixels(self, x: int, y: int) -> tuple[int, int]:
        scale = self.devicePixelRatioF()
        return int(round(x * scale)), int(round(y * scale))

    def _face_orientation_label(self, item_id: str, face_index: int) -> str:
        """Return a short tag like 'TOP', 'BOTTOM', or 'side' for the log.

        The numeric face index alone doesn't tell us at a glance which
        physical surface was selected - clicking a cylinder top vs its
        bottom or its lateral wall produces a different index per body.
        Tagging the log with a direction makes "click visible top, get
        bottom" reports diagnosable without re-deriving the topology.
        """
        try:
            from cad_app.commands import face_normal_vector

            shape = self._scene.get(item_id).shape
            normal = face_normal_vector(shape, face_index)
        except Exception:
            return "(orientation n/a)"
        nx, ny, nz = float(normal[0]), float(normal[1]), float(normal[2])
        if nz > 0.95:
            return "TOP(+Z)"
        if nz < -0.95:
            return "BOTTOM(-Z)"
        return f"side(normal={nx:+.2f},{ny:+.2f},{nz:+.2f})"

    def _forward_click_to_view_cube(self, x: int, y: int) -> None:
        """Route a click that landed in the gizmo corner to OCCT so its
        AIS_ViewCube can run its built-in camera animation. We can't
        let the click reach normal Qt event handling (that would
        commit any active Move session) but we still want the cube to
        respond to clicks on its visible faces; OCCT does that for us
        when we call ``context.SelectDetected()`` while the cube is
        under the cursor.
        """
        if not self._viewer.is_initialized:
            return
        view_x, view_y = self._to_view_pixels(x, y)
        try:
            self._viewer.context.MoveTo(
                int(view_x),
                int(view_y),
                self._viewer.view,
                True,
            )
            if self._viewer.context.HasDetectedShape():
                self._viewer.context.SelectDetected()
        except Exception:
            LOGGER.debug("View cube click forwarding failed", exc_info=True)

    def _set_rotate_pivot_from_click(self, x: int, y: int) -> bool:
        """Shift+click while in Rotate: re-pick the pivot from whatever
        vertex / edge / face is under the cursor. Returns True if a pivot
        was set (so the caller knows to consume the event)."""
        if self._move_session is None or self._move_session.tool != "rotate":
            return False
        if not self._viewer.is_initialized:
            return False
        view_x, view_y = self._to_view_pixels(x, y)
        # Prefer the smallest topological feature near the cursor:
        # vertex > edge > face. select_through gives us all hits at once.
        candidates = self._picker.pick_candidates_at(
            self._viewer.view, view_x, view_y, "all", select_through=True
        )
        if not candidates:
            self._show_status("Pivot: no subshape under the cursor")
            return False
        rank = {
            SelectionKind.VERTEX: 0,
            SelectionKind.EDGE: 1,
            SelectionKind.FACE: 2,
        }
        candidates_ranked = sorted(
            (c for c in candidates if c.selection.kind in rank),
            key=lambda c: (rank[c.selection.kind], c.distance_px),
        )
        if not candidates_ranked:
            self._show_status("Pivot: pick a vertex, edge or face")
            return False
        ref = candidates_ranked[0].selection
        pivot = None
        if ref.kind == SelectionKind.FACE:
            try:
                pivot = self._face_center(ref.item_id, ref.index)
            except (CommandError, IndexError, RuntimeError, ValueError):
                pivot = None
        else:
            try:
                shape = self._picker.subshape(ref.item_id, ref.kind, ref.index)
                pivot = self._shape_center(shape)
            except (CommandError, IndexError, RuntimeError, ValueError):
                pivot = None
        if pivot is None:
            self._show_status("Pivot: could not resolve a point from selection")
            return False
        self._move_session.axis_point = pivot
        self._update_move_preview()
        self._refresh_hud()
        self._show_status(
            f"Pivot moved to {ref.kind.value} ({pivot[0]:.1f}, {pivot[1]:.1f}, "
            f"{pivot[2]:.1f})"
        )
        return True
