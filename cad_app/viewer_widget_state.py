"""Selection, command, category, and overlay state for ViewerWidget."""

from __future__ import annotations

import logging
import math

from PySide6.QtCore import Qt

from cad_app.commands import (
    CommandError,
    apply_boolean_bodies,
)
from cad_app.sketch import (
    is_sketch_object,
    is_sketch_profile,
)
from cad_app.types import SelectionKind, SelectionRef
from cad_app.ui_menu import validate_category_id
from cad_app.viewer_widget_state_snapshot import ViewerWidgetStateSnapshotMixin

LOGGER = logging.getLogger(__name__)

BROWSER_ITEM_ID_ROLE = Qt.UserRole
BROWSER_SELECTION_KIND_ROLE = Qt.UserRole + 1
BROWSER_SELECTION_INDEX_ROLE = Qt.UserRole + 2
BROWSER_COMMAND_ROLE = Qt.UserRole + 3


class ViewerWidgetStateMixin(ViewerWidgetStateSnapshotMixin):
    def _set_selection_kind(self, kind: SelectionKind) -> None:
        self._selection_kind = kind
        self._active_category = "select"
        self._hover_selection = None
        self._scene.set_selection(None)
        self._selection_source = None
        self._hide_edge_dimension_editor()
        if self._viewer.is_initialized:
            self._viewer.set_selection_kind(kind)
        self._set_context_hint("Choose Object, Face, Edge, or Vertex selection mode")
        self._show_status(f"Selection: {kind .value }")
        self._refresh_hud()
        self._refresh_action_state()
        LOGGER.info("UI selection mode set to %s", kind.value)

    def _undo(self) -> None:
        if self._scene.undo() is None:
            LOGGER.info("Undo requested but stack is empty")
            return
        self._hover_selection = None
        self._hide_edge_dimension_editor()
        if self._viewer.is_initialized:
            self._viewer.display_scene(self._scene, fit=False)
        self._show_status("Undo")
        LOGGER.info("Undo applied")

    def _redo(self) -> None:
        if self._scene.redo() is None:
            LOGGER.info("Redo requested but stack is empty")
            return
        self._hover_selection = None
        self._hide_edge_dimension_editor()
        if self._viewer.is_initialized:
            self._viewer.display_scene(self._scene, fit=False)
        self._show_status("Redo")
        LOGGER.info("Redo applied")

    def _delete_active_object(self) -> None:
        if self._move_session is not None or self._sketch_session is not None:
            self._show_status("Cancel active tool before deleting")
            return
        if len(self._scene.selection_refs()) > 1:
            self._show_status("Delete supports one body at a time")
            return
        selection = self._scene.selection()
        if selection is not None and selection.kind != SelectionKind.OBJECT:
            self._show_status("Select an object to delete")
            LOGGER.info(
                "Delete object blocked because %s is selected",
                selection.kind.value,
            )
            return
        item_id = (
            selection.item_id if selection is not None else self._scene.active_item_id()
        )
        if item_id is None:
            self._show_status("No active object")
            return
        if is_sketch_object(self._scene.get(item_id).meta):
            self._show_status("Select a body to delete")
            return
        self._scene.remove(item_id)
        self._hover_selection = None
        if self._viewer.is_initialized:
            self._viewer.display_scene(self._scene, fit=False)
        self._show_status("Object deleted")
        LOGGER.info("Object deleted item_id=%s", item_id)

    def _set_boolean_target_from_context(self) -> None:
        item_id = self._selected_or_active_body_item_id()
        if item_id is None:
            body_item_ids = self._body_item_ids()
            if len(body_item_ids) == 1:
                item_id = body_item_ids[0]
            else:
                self._show_status("Select a body target first")
                self._set_context_hint(
                    "Boolean: select the target body, then select the second body"
                )
                return
        self._boolean_target_item_id = item_id
        self._show_status("Boolean target set")
        self._set_context_hint("Boolean target set: select a second body to combine")
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
            apply_boolean_bodies(self._scene, target_item_id, tool_item_id, operation)
        except (CommandError, KeyError, ValueError) as exc:
            LOGGER.warning(
                "Boolean %s failed target=%s tool=%s: %s",
                operation,
                target_item_id,
                tool_item_id,
                exc,
                exc_info=True,
            )
            self._show_status(f"Boolean {operation } failed")
            return
        self._boolean_target_item_id = None
        self._hover_selection = None
        if self._viewer.is_initialized:
            self._viewer.display_scene(self._scene, fit=False)
        self._show_status(f"Boolean {operation } applied")
        LOGGER.info(
            "Boolean %s applied target=%s tool=%s",
            operation,
            target_item_id,
            tool_item_id,
        )

    def _body_item_ids(self) -> list[str]:
        return [item.item_id for item in self._scene if not is_sketch_object(item.meta)]

    def _selected_or_active_body_item_id(self) -> str | None:
        if len(self._scene.selection_refs()) > 1:
            return None
        selection = self._scene.selection()
        item_id = (
            selection.item_id if selection is not None else self._scene.active_item_id()
        )
        if item_id is None or item_id not in self._scene:
            return None
        if is_sketch_object(self._scene.get(item_id).meta):
            return None
        return item_id

    def _selected_body_refs(self) -> tuple[SelectionRef, ...]:
        return tuple(
            selection
            for selection in self._scene.selection_refs()
            if selection.kind == SelectionKind.OBJECT
            and selection.item_id in self._scene
            and not is_sketch_object(self._scene.get(selection.item_id).meta)
        )

    def _selected_body_item_ids(self) -> tuple[str, ...]:
        refs = self._scene.selection_refs()
        body_refs = self._selected_body_refs()
        if not refs or len(body_refs) != len(refs):
            return ()
        return tuple(selection.item_id for selection in body_refs)

    def _selected_body_count(self) -> int:
        return len(self._selected_body_refs())

    def _selected_sketch_profile_refs(self) -> tuple[SelectionRef, ...]:
        return tuple(
            selection
            for selection in self._scene.selection_refs()
            if selection.item_id in self._scene
            and is_sketch_profile(self._scene.get(selection.item_id).meta)
        )

    def _selected_sketch_profile_item_ids(self) -> tuple[str, ...]:
        refs = self._scene.selection_refs()
        profile_refs = self._selected_sketch_profile_refs()
        if not refs or len(profile_refs) != len(refs):
            return ()
        return tuple(selection.item_id for selection in profile_refs)

    def _selected_sketch_profile_count(self) -> int:
        return len(self._selected_sketch_profile_refs())

    def _selected_item_is_sketch_profile(self) -> bool:
        refs = self._scene.selection_refs()
        if not refs:
            return False
        profile_refs = self._selected_sketch_profile_refs()
        if len(refs) > 1:
            return len(profile_refs) == len(refs)
        return bool(profile_refs)

    def _selected_item_is_sketch_object(self) -> bool:
        refs = self._scene.selection_refs()
        if len(refs) != 1:
            return False
        return is_sketch_object(self._scene.get(refs[0].item_id).meta)

    def _valid_boolean_target_item_id(self) -> str | None:
        if (
            self._boolean_target_item_id is None
            or self._boolean_target_item_id not in self._scene
            or is_sketch_object(self._scene.get(self._boolean_target_item_id).meta)
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
        self._show_status(f"Display: {mode }")
        self._refresh_action_state()

    def _show_status(self, message: str) -> None:
        self._last_status_text = message
        window = self.window()
        if hasattr(window, "statusBar"):
            window.statusBar().showMessage(message, 3500)
        self._refresh_hud()

    def _set_context_hint(self, message: str | None) -> None:
        self._context_hint_text = message or ""
        if self._hud_labels and "hint" in self._hud_labels:
            self._hud_labels["hint"].setText(self._context_hint_text)
        if not message:
            self._context_hint_overlay.hide()
            return
        self._context_hint_overlay.setFixedWidth(self._context_hint_width())
        self._context_hint_overlay.setText(message)
        self._context_hint_overlay.adjustSize()
        self._position_context_hint()
        self._context_hint_overlay.hide()

    def _context_hint_width(self) -> int:
        return max(220, min(360, self.width() - 28))

    def _position_context_hint(self) -> None:
        if not hasattr(self, "_context_hint_overlay"):
            return
        margin = 14
        if not self._context_hint_overlay.isHidden():
            self._context_hint_overlay.setFixedWidth(self._context_hint_width())
            self._context_hint_overlay.adjustSize()
        max_x = max(margin, self.width() - self._context_hint_overlay.width() - margin)
        self._context_hint_overlay.move(min(margin, max_x), margin)

    def _is_in_orientation_gizmo(self, x: int, y: int) -> bool:
        if not self._orientation_gizmo_enabled:
            return False
        left, top, size = self._orientation_gizmo_rect()
        return left <= x <= left + size and top <= y <= top + size

    def _orientation_gizmo_view_at(
        self,
        x: int,
        y: int,
    ) -> tuple[str, bool, str] | None:
        left, top, size = self._orientation_gizmo_rect()
        local_x = x - left
        local_y = y - top
        if hasattr(self, "_orientation_gizmo_overlay"):
            target = self._orientation_gizmo_overlay.view_at(local_x, local_y)
            if target is not None:
                return target
        return self._orientation_gizmo_fallback_view(local_x, local_y, size)

    def _orientation_gizmo_axis_at(self, x: int, y: int) -> str | None:
        target = self._orientation_gizmo_view_at(x, y)
        return None if target is None else target[0]

    @staticmethod
    def _orientation_gizmo_fallback_view(
        local_x: int,
        local_y: int,
        size: int,
    ) -> tuple[str, bool, str] | None:
        third = size / 3.0
        if local_y < third:
            return ("z", True, "Top")
        if local_y > size - third:
            return ("z", False, "Bottom")
        if local_x < third:
            return ("x", False, "Left")
        if local_x > size - third:
            return ("x", True, "Right")
        return ("y", False, "Front")

    def _orientation_gizmo_rect(self) -> tuple[int, int, int]:
        margin = 18
        size = 156
        return (
            max(margin, self.width() - size - margin),
            max(margin, self.height() - size - margin),
            size,
        )

    def _show_pending_command(self, command_name: str) -> None:
        self._show_status(f"{command_name }: not implemented yet")
        LOGGER.info("Pending UI command selected: %s", command_name)

    def _activate_sketch_category(self) -> None:
        self._active_category = "sketch"
        self._selection_kind = SelectionKind.FACE
        if self._viewer.is_initialized:
            self._viewer.set_selection_kind(SelectionKind.FACE)
        if self._sketch_session is None:
            self._set_context_hint(
                "Sketch: New Sketch starts on the bottom plane; select a planar "
                "face first to sketch on that face"
            )
            self._show_status("Mode: Sketch")
            self._hide_sketch_plane_chooser()
            self._position_orientation_gizmo_overlay()
        else:
            self._set_context_hint("Choose a sketch tool: Line, Arc, Circle, Rectangle")
            self._show_status("Sketch tools ready")
            self._hide_sketch_plane_chooser()
            self._position_orientation_gizmo_overlay()
        self._refresh_action_state()

    def _set_active_category(self, category: str) -> None:
        category_def = validate_category_id(category)
        if category == "sketch":
            self._activate_sketch_category()
            return
        if self._sketch_session is not None:
            self._finish_sketch_session(
                status="Sketch finished",
                context_hint=category_def.context_hint,
                category=category,
            )
            self._show_status(f"Mode: {category_def.label}")
            return
        self._active_category = category
        self._hide_sketch_plane_chooser()
        self._set_context_hint(category_def.context_hint)
        self._show_status(f"Mode: {category_def.label}")
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
                target_kind = (
                    self._move_session.target_kind
                    if isinstance(self._move_session.target_kind, SelectionKind)
                    else SelectionKind(self._move_session.target_kind)
                )
                center = self._label_anchor_center(
                    self._move_session.item_id,
                    target_kind,
                    self._move_session.index,
                )
                axis = self._move_session.axis
                axis_norm = math.sqrt(sum(c * c for c in axis))
                if axis_norm < 1e-7:
                    return center
                direction = tuple(c / axis_norm for c in axis)
                offset = self._move_session.distance + 8.0
                return tuple(
                    center_component + dir_component * offset
                    for center_component, dir_component in zip(center, direction)
                )
            except (CommandError, IndexError, ValueError):
                LOGGER.debug("Dimension label position fallback", exc_info=True)
        return (0.0, 0.0, 0.0)

    def _label_anchor_center(
        self,
        item_id: str,
        target_kind,
        index: int,
    ) -> tuple[float, float, float]:
        if target_kind == SelectionKind.FACE:
            return self._face_center(item_id, index)
        shape = self._picker.subshape(item_id, target_kind, index)
        return self._shape_center(shape) or (0.0, 0.0, 0.0)
