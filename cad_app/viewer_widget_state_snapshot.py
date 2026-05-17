"""Stable UI-state snapshot helpers for ViewerWidget."""

from __future__ import annotations

from enum import Enum

from cad_app.gui_contract import LAYOUT_REGIONS
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
            command_mode=self._ui_command_mode(),
            boolean_target_item_id=self._valid_boolean_target_item_id(),
            active_operation=self._ui_operation_state(),
            context_actions=self._ui_context_actions(),
            status_text=self._last_status_text,
            hint_text=self._context_hint_text,
            overlay_visible=self._ui_overlay_visible(),
            overlay_text=overlay_text,
            manipulator_visible=self._ui_manipulator_visible(),
            right_panel_context=self._ui_right_panel_context(),
        )

    def export_ui_state(self) -> dict:
        """Return a JSON-serializable GUI contract snapshot."""
        state = self.get_ui_state()
        return {
            "schema": "cad_gui_state.v1",
            "state": {
                "work_mode": state.work_mode,
                "selection_mode": state.selection_mode,
                "selection_type": state.selection_type,
                "active_tool": state.active_tool,
                "command_mode": state.command_mode,
                "boolean_target_item_id": state.boolean_target_item_id,
                "active_operation": self._json_value(state.active_operation),
                "context_actions": list(state.context_actions),
                "status_text": state.status_text,
                "hint_text": state.hint_text,
                "overlay_visible": state.overlay_visible,
                "overlay_text": state.overlay_text,
                "manipulator_visible": state.manipulator_visible,
                "right_panel_context": state.right_panel_context,
            },
            "regions": self._export_layout_regions(),
            "actions": self._export_action_states(),
            "overlays": self._export_overlay_states(),
            "context_tool_panel": self._export_context_tool_panel(),
            "hud": self._export_hud_state(),
        }

    def _export_layout_regions(self) -> dict[str, dict]:
        from PySide6.QtWidgets import QToolBar, QWidget

        window = self.window()
        regions: dict[str, dict] = {}
        for object_name in LAYOUT_REGIONS:
            widget = window.findChild(QWidget, object_name)
            toolbar_actions = []
            if isinstance(widget, QToolBar):
                toolbar_actions = [
                    entry
                    for entry in self._toolbar_action_entries(widget)
                    if not entry["is_section_label"]
                ]
            regions[object_name] = {
                "object_name": widget.objectName() if widget is not None else "",
                "class": widget.metaObject().className() if widget is not None else "",
                "present": widget is not None,
                "visible": False if widget is None else not widget.isHidden(),
                "enabled": False if widget is None else widget.isEnabled(),
                "actions": toolbar_actions,
            }
        return regions

    def _export_action_states(self) -> dict[str, dict]:
        context_action_names = {
            entry["name"]
            for entry in self._export_context_tool_panel()["entries"]
            if not entry["is_section_label"]
        }
        context_button_names = {
            entry["name"]: entry["button_object_name"]
            for entry in self._export_context_tool_panel()["entries"]
            if not entry["is_section_label"]
        }
        return {
            action_name: {
                "object_name": action.objectName(),
                "text": action.text().replace("&", ""),
                "enabled": action.isEnabled(),
                "checked": action.isCheckable() and action.isChecked(),
                "checkable": action.isCheckable(),
                "visible": action.isVisible(),
                "status_tip": action.statusTip(),
                "in_context_tool_panel": action_name in context_action_names,
                "button_object_name": context_button_names.get(action_name, ""),
            }
            for action_name, action in self._actions.items()
        }

    def _export_context_tool_panel(self) -> dict:
        from PySide6.QtWidgets import QToolBar

        toolbar = self.window().findChild(QToolBar, "context_tool_panel")
        entries = [] if toolbar is None else self._toolbar_action_entries(toolbar)
        return {
            "object_name": "" if toolbar is None else toolbar.objectName(),
            "present": toolbar is not None,
            "visible": False if toolbar is None else not toolbar.isHidden(),
            "enabled": False if toolbar is None else toolbar.isEnabled(),
            "entries": entries,
            "sections": self._context_sections_from_toolbar_entries(entries),
            "actions": [
                entry["name"] for entry in entries if not entry["is_section_label"]
            ],
        }

    @staticmethod
    def _context_sections_from_toolbar_entries(
        entries: list[dict],
    ) -> list[dict[str, object]]:
        sections: list[dict[str, object]] = []
        current_section: dict[str, object] | None = None
        for entry in entries:
            if entry["is_section_label"]:
                current_section = {"name": entry["text"], "actions": []}
                sections.append(current_section)
                continue
            if current_section is None:
                current_section = {"name": "", "actions": []}
                sections.append(current_section)
            current_section["actions"].append(entry["name"])
        return sections

    @staticmethod
    def _toolbar_action_entries(toolbar) -> list[dict]:
        entries = []
        for action in toolbar.actions():
            action_name = action.objectName()
            if not action_name:
                continue
            button = toolbar.widgetForAction(action)
            entries.append(
                {
                    "name": action_name,
                    "text": action.text().replace("&", ""),
                    "enabled": action.isEnabled(),
                    "checked": action.isCheckable() and action.isChecked(),
                    "checkable": action.isCheckable(),
                    "visible": action.isVisible(),
                    "is_section_label": action_name.startswith("context_label_"),
                    "button_object_name": (
                        "" if button is None else button.objectName()
                    ),
                }
            )
        return entries

    def _export_hud_state(self) -> dict[str, dict]:
        return {
            name: {
                "object_name": label.objectName(),
                "text": label.text(),
                "visible": not label.isHidden(),
                "enabled": label.isEnabled(),
            }
            for name, label in self._hud_labels.items()
        }

    def _export_overlay_states(self) -> dict[str, dict]:
        overlays = {
            "dimension_overlay": self._widget_overlay_state(self._dimension_overlay),
            "tool_popover": self._widget_overlay_state(
                getattr(self, "_tool_popover", None)
            ),
            "move_manipulator": self._widget_overlay_state(
                getattr(self, "_move_manipulator_overlay", None)
            ),
            "view_cube": self._widget_overlay_state(
                getattr(self, "_orientation_gizmo_overlay", None)
            ),
            "context_hint": self._widget_overlay_state(
                getattr(self, "_context_hint_overlay", None)
            ),
            "grid_axis_labels": self._grid_axis_labels_state(),
            "inline_dimension_editors": {
                key: self._widget_overlay_state(editor)
                for key, editor in getattr(
                    self,
                    "_inline_dimension_editors",
                    {},
                ).items()
            },
        }
        return overlays

    def _grid_axis_labels_state(self) -> dict:
        values = (-200, -150, -100, -50, 50, 100, 150, 200)
        labels = tuple(f"{axis} {value}" for axis in ("X", "Y") for value in values)
        visible = bool(
            getattr(self._viewer, "is_initialized", False)
            and getattr(self._viewer, "_grid_enabled", False)
        )
        viewport_rect = self.rect()
        return {
            "object_name": "grid_axis_labels",
            "visible": visible,
            "rect": {
                "x": viewport_rect.x(),
                "y": viewport_rect.y(),
                "width": viewport_rect.width(),
                "height": viewport_rect.height(),
            },
            "text": " ".join(labels),
            "labels": [
                {
                    "object_name": f"native_grid_label_{index}",
                    "visible": visible,
                    "rect": {"x": 0, "y": 0, "width": 0, "height": 0},
                    "text": text,
                }
                for index, text in enumerate(labels)
            ],
        }

    def _widget_overlay_state(self, widget) -> dict:
        if widget is None:
            return {
                "object_name": "",
                "visible": False,
                "rect": {"x": 0, "y": 0, "width": 0, "height": 0},
                "text": "",
            }
        rect = self._child_rect_in_viewport(widget)
        if rect is None:
            rect = widget.rect()
        text = widget.text() if hasattr(widget, "text") else ""
        return {
            "object_name": widget.objectName(),
            "visible": not widget.isHidden(),
            "rect": {
                "x": rect.x(),
                "y": rect.y(),
                "width": rect.width(),
                "height": rect.height(),
            },
            "text": text,
        }

    @staticmethod
    def _json_value(value):
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, tuple):
            return [ViewerWidgetStateSnapshotMixin._json_value(item) for item in value]
        if isinstance(value, list):
            return [ViewerWidgetStateSnapshotMixin._json_value(item) for item in value]
        if isinstance(value, dict):
            return {
                key: ViewerWidgetStateSnapshotMixin._json_value(item)
                for key, item in value.items()
            }
        return value

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

    def _ui_command_mode(self) -> str:
        if self._sketch_session is not None or self._move_session is not None:
            return "active_tool"
        if self._valid_boolean_target_item_id() is not None:
            return "boolean_target"
        return "normal"

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
            or (hasattr(self, "_tool_popover") and not self._tool_popover.isHidden())
            or (
                self._move_session is not None
                and self._move_session.tool in {"extrude", "sketch_extrude"}
            )
        )

    def _ui_manipulator_visible(self) -> bool:
        return bool(
            self._move_session is not None
            and self._move_session.tool
            in {"extrude", "sketch_extrude", "move", "sketch_move", "rotate"}
        )

    def _ui_right_panel_context(self) -> str:
        if self._move_session is not None:
            return "active_operation"
        if self._sketch_session is not None:
            return "sketch"
        if self._valid_boolean_target_item_id() is not None:
            return "boolean"
        if self._scene.selection_refs():
            return "selection"
        if self._scene.active_item_id() is not None:
            return "active_body"
        return "model"
