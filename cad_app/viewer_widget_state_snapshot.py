"""Stable UI-state snapshot helpers for ViewerWidget."""

from __future__ import annotations

from cad_app.sketch import SKETCH_ENTITY_META_KIND, is_sketch_profile
from cad_app.types import OperationState, UIState


class ViewerWidgetStateSnapshotMixin:
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
            hint_text=self._context_hint_text,
            overlay_visible=self._ui_overlay_visible(),
            overlay_text=overlay_text,
            manipulator_visible=self._ui_manipulator_visible(),
            right_panel_context=self._ui_right_panel_context(),
        )

    def _ui_selection_type(self) -> str:
        selections = self._scene.selection_refs()
        if len(selections) > 1:
            metas = [
                self._scene.get(selection.item_id).meta for selection in selections
            ]
            if all(is_sketch_profile(meta) for meta in metas):
                return "multi_sketch_profile"
            kinds = {selection.kind.value for selection in selections}
            if len(kinds) == 1:
                return f"multi_{next(iter(kinds))}"
            return "multi"
        selection = self._scene.selection()
        if selection is None:
            return "none"
        selected_meta = self._scene.get(selection.item_id).meta
        if is_sketch_profile(selected_meta):
            return "sketch_profile"
        if selected_meta.get("kind") == SKETCH_ENTITY_META_KIND:
            return "sketch_entity"
        return selection.kind.value

    def _ui_active_tool(self) -> str:
        if self._sketch_session is not None:
            return f"sketch:{self ._sketch_session .tool }"
        if self._move_session is not None:
            return self._move_session.tool
        return "idle"

    def _ui_operation_state(self) -> OperationState:
        if self._sketch_session is not None:
            return OperationState.DRAWING_SKETCH
        if self._move_session is None:
            if self._scene.selection_refs():
                return OperationState.SELECTING
            return OperationState.IDLE
        if self._move_session.tool in {"extrude", "sketch_extrude"}:
            return OperationState.PREVIEWING_EXTRUDE
        if (
            self._move_session.drag_start is not None
            or self._move_session.vector is not None
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
        if self._scene.selection_refs():
            return "selection"
        if self._scene.active_item_id() is not None:
            return "active_body"
        return "model"
