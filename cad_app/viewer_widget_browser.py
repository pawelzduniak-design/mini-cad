"""Browser, properties, and HUD panels for ViewerWidget."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QInputDialog,
    QListWidgetItem,
)

from cad_app.feature_history import (
    FeatureRebuildError,
    feature_history,
    feature_history_steps,
    feature_step_label,
    mark_scene_item_feature_history_failed,
    rebuild_scene_item_feature_history,
    rollback_scene_item_feature_history,
    update_scene_item_feature_step,
)
from cad_app.sketch import (
    is_sketch_object,
    is_sketch_profile,
)
from cad_app.types import SelectionKind, SelectionRef
from cad_app.ui_sessions import (
    MoveSession,
)

LOGGER = logging.getLogger(__name__)

BROWSER_ITEM_ID_ROLE = Qt.UserRole
BROWSER_SELECTION_KIND_ROLE = Qt.UserRole + 1
BROWSER_SELECTION_INDEX_ROLE = Qt.UserRole + 2
BROWSER_COMMAND_ROLE = Qt.UserRole + 3


class ViewerWidgetBrowserMixin:
    def _refresh_hud(self) -> None:
        if self._hud_labels:
            self._hud_labels["mode"].setText(
                f"Mode: {self ._active_category .title ()}"
            )
            self._hud_labels["selection"].setText(self._selection_label())
            self._hud_labels["axis"].setText(f"Select: {self ._selection_kind .value }")
            self._hud_labels["tool"].setText(self._tool_label())
            self._hud_labels["sketch"].setText(self._sketch_label())
            if "hint" in self._hud_labels:
                self._hud_labels["hint"].setText(self._context_hint_text)
        self._refresh_tool_popover()
        if hasattr(self, "_refresh_move_manipulator"):
            self._refresh_move_manipulator()
        if not self._is_live_drag_refresh():
            self._refresh_action_state()
            self._refresh_browser()

    def _is_live_drag_refresh(self) -> bool:
        if self._move_session is not None and self._move_session.drag_start is not None:
            return True
        return (
            self._sketch_session is not None
            and self._sketch_session.drag_start_screen is not None
            and self._sketch_session.tool != "trim"
        )

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
            active_item_id = self._scene.active_item_id()
            scene_items = list(self._scene)
            body_items = [
                item for item in scene_items if not is_sketch_object(item.meta)
            ]
            sketch_items = [item for item in scene_items if is_sketch_object(item.meta)]
            if model_list is not None:
                self._add_browser_item(model_list, "Model", enabled=False)
                self._add_browser_item(
                    model_list,
                    f"Bodies ({len (body_items )})",
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
                        f"  {label }",
                    )
                self._add_browser_item(
                    model_list,
                    f"Sketches ({len (sketch_items )})",
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
                        f"  {label }",
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
                        f"Active sketch: {self ._sketch_session .tool } "
                        f"on {self ._sketch_session .label }"
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
        return f"{prefix }Body {index }: {source } {item .item_id [:8 ]}"

    @staticmethod
    def _sketch_browser_label(item, index: int, active_item_id: str | None) -> str:
        prefix = "* " if item.item_id == active_item_id else "  "
        profile = item.meta.get("profile", "profile")
        return f"{prefix }Sketch {index }: {profile } {item .item_id [:8 ]}"

    def _populate_history_panel(self, history_list) -> None:
        active_item_id = self._scene.active_item_id()
        if active_item_id is not None and active_item_id in self._scene:
            active = self._scene.get(active_item_id)
            active_history = feature_history(active.meta)
            if active_history is not None and not is_sketch_object(active.meta):
                status = active_history.get("status", "ok")
                self._add_browser_item(
                    history_list,
                    f"Feature tree: {status}",
                    enabled=False,
                )
                if active_history.get("error"):
                    self._add_browser_item(
                        history_list,
                        f"Rebuild error: {active_history['error']}",
                        enabled=False,
                    )
                self._add_browser_item(
                    history_list,
                    "Rebuild feature tree",
                    command=f"rebuild_history:{active_item_id}",
                    tooltip="Rebuild the active body from stored feature parameters.",
                )
                for index, step in enumerate(
                    feature_history_steps(active.meta),
                    start=1,
                ):
                    step_index = index - 1
                    self._add_browser_item(
                        history_list,
                        feature_step_label(step, index),
                        command=f"edit_feature:{active_item_id}:{step_index}",
                        tooltip="Edit this feature step and rebuild downstream steps.",
                    )
                    self._add_browser_item(
                        history_list,
                        f"  Rollback after step {index}",
                        command=f"rollback_history:{active_item_id}:{index}",
                        tooltip="Drop later features and rebuild to this point.",
                    )
        if self._move_session is not None or self._sketch_session is not None:
            active_tool = (
                self._sketch_session.tool
                if self._sketch_session is not None
                else self._move_session.tool
            )
            self._add_browser_item(
                history_list,
                f"Active operation: {active_tool }",
                enabled=False,
            )
            self._add_browser_item(
                history_list,
                "Cancel active tool",
                command="cancel_tool",
                tooltip="Cancel the active operation.",
            )
        undo_depth = self._scene.undo_depth()
        redo_depth = self._scene.redo_depth()
        if undo_depth > 0:
            self._add_browser_item(
                history_list,
                f"Undo last change ({undo_depth })",
                command="undo",
                tooltip="Click to undo one scene change.",
            )
        if redo_depth > 0:
            self._add_browser_item(
                history_list,
                f"Redo change ({redo_depth })",
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
                else (
                    "Push/Pull Cut"
                    if self._move_session.operation == "cut"
                    else self._move_session.tool.replace("_", " ").title()
                )
            )
            operation = "New Body"
            if self._move_session.tool == "extrude":
                tool_name = "Push/Pull"
                operation = "Push/Pull"
            elif self._move_session.tool == "sketch_extrude":
                if self._move_session.operation == "new_body":
                    operation = "New Body"
                elif self._move_session.operation == "cut":
                    tool_name = "Push/Pull Cut"
                    operation = "Cut"
                else:
                    tool_name = "Push/Pull"
                    operation = "Add"
            elif self._move_session.tool == "rotate":
                operation = "Transform"
            elif self._move_session.tool in {"move", "sketch_move"}:
                operation = "Transform"
            elif self._move_session.tool == "sketch_revolve":
                operation = (
                    "Helix" if abs(self._move_session.elevation) > 1e-7 else "Revolve"
                )
            elif self._move_session.tool == "fillet":
                operation = "Round"
            elif self._move_session.tool == "chamfer":
                operation = "Bevel"
            self._add_browser_item(
                properties_list,
                f"Type: {tool_name }",
                enabled=False,
            )
            self._add_browser_item(
                properties_list,
                f"Selection: {self ._selection_label ()}",
                enabled=False,
            )
            self._add_browser_item(
                properties_list,
                f"{self ._move_axis_property_label (self ._move_session )}",
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
            if self._move_session.tool == "sketch_revolve":
                self._add_browser_item(
                    properties_list,
                    f"Elevation: {self ._move_session .elevation :.2f} mm",
                    enabled=False,
                )
            self._add_browser_item(
                properties_list,
                f"Operation: {operation }",
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
                f"Workplane: {self ._sketch_session .label }",
                enabled=False,
            )
            self._add_browser_item(
                properties_list,
                f"Tool: {self ._sketch_session .tool }",
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
            f"Mode: {self ._active_category .title ()}",
            enabled=False,
        )
        self._add_browser_item(
            properties_list,
            f"Selection mode: {self ._selection_kind .value }",
            enabled=False,
        )
        self._add_browser_item(
            properties_list,
            self._selection_label(),
            enabled=False,
        )
        selection = self._scene.selection()
        if selection is not None and selection.kind == SelectionKind.EDGE:
            measurement = self._selected_edge_measurement()
            if measurement is not None:
                self._add_browser_item(
                    properties_list,
                    f"Edge Length: {measurement.length :.2f} mm",
                    enabled=False,
                )
                if measurement.axis_name is not None:
                    self._add_browser_item(
                        properties_list,
                        f"Edge Axis: {measurement.axis_name}",
                        enabled=False,
                    )
        active_item_id = self._scene.active_item_id()
        if active_item_id is not None and active_item_id in self._scene:
            active = self._scene.get(active_item_id)
            self._add_browser_item(
                properties_list,
                f"Active ID: {active .item_id [:8 ]}",
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
                    f"Profile: {active .meta .get ('profile','profile')}",
                    enabled=False,
                )
                width = self._sketch_meta_float(active.meta, "width")
                height = self._sketch_meta_float(active.meta, "height")
                radius = self._sketch_meta_float(active.meta, "radius")
                inner_radius = self._sketch_meta_float(
                    active.meta,
                    "inner_circle_radius",
                )
                if width is not None:
                    self._add_browser_item(
                        properties_list,
                        f"Width: {width :.2f} mm",
                        enabled=False,
                    )
                if height is not None:
                    self._add_browser_item(
                        properties_list,
                        f"Height: {height :.2f} mm",
                        enabled=False,
                    )
                if radius is not None:
                    self._add_browser_item(
                        properties_list,
                        f"Radius: {radius :.2f} mm",
                        enabled=False,
                    )
                if inner_radius is not None:
                    self._add_browser_item(
                        properties_list,
                        f"Inner Radius: {inner_radius :.2f} mm",
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
                    f"Source: {active .meta .get ('source','body')}",
                    enabled=False,
                )
        self._populate_property_actions(properties_list)

    @staticmethod
    def _move_axis_property_label(session: MoveSession) -> str:
        if session.tool in {"rotate", "sketch_revolve"}:
            return f"Axis: {session .axis_name }"
        if session.tool in {"fillet", "chamfer"}:
            return f"Edge: {session .index }"
        return f"Direction: {session .axis_name }"

    @staticmethod
    def _move_value_property_label(session: MoveSession) -> str:
        if session.tool in {"rotate", "sketch_revolve"}:
            return f"Angle: {session .distance :.2f} deg"
        if session.tool == "fillet":
            return f"Radius: {session .distance :.2f} mm"
        if session.tool == "chamfer":
            return f"Distance: {session .distance :.2f} mm"
        if session.tool == "sketch_extrude" and session.operation == "cut":
            return f"Depth: {abs(session .distance) :.2f} mm"
        return f"Distance: {session .distance :.2f} mm"

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
        if command.startswith("rebuild_history:"):
            self._rebuild_feature_tree(command.removeprefix("rebuild_history:"))
            return
        if command.startswith("edit_feature:"):
            _prefix, item_id, step_index = command.split(":", 2)
            self._edit_feature_step(item_id, int(step_index))
            return
        if command.startswith("rollback_history:"):
            _prefix, item_id, step_count = command.split(":", 2)
            self._rollback_feature_tree(item_id, int(step_count))
            return
        action = self._actions.get(command)
        if action is not None and action.isEnabled():
            action.trigger()
            return
        self._show_status("Action unavailable")

    def _rebuild_feature_tree(self, item_id: str) -> None:
        if item_id not in self._scene:
            self._show_status("Feature body unavailable")
            return
        try:
            rebuild_scene_item_feature_history(self._scene, item_id)
        except FeatureRebuildError as exc:
            LOGGER.warning("Feature rebuild failed: %s", exc, exc_info=True)
            self._mark_feature_tree_failed(item_id, exc)
            self._show_status("Feature rebuild failed")
            return
        self._after_feature_history_change(item_id, "Feature tree rebuilt")

    def _rollback_feature_tree(self, item_id: str, step_count: int) -> None:
        if item_id not in self._scene:
            self._show_status("Feature body unavailable")
            return
        try:
            rollback_scene_item_feature_history(self._scene, item_id, step_count)
        except (FeatureRebuildError, IndexError) as exc:
            LOGGER.warning("Feature rollback failed: %s", exc, exc_info=True)
            self._mark_feature_tree_failed(item_id, exc)
            self._show_status("Feature rollback failed")
            return
        self._after_feature_history_change(item_id, "Feature tree rolled back")

    def _edit_feature_step(self, item_id: str, step_index: int) -> None:
        if item_id not in self._scene:
            self._show_status("Feature body unavailable")
            return
        steps = feature_history_steps(self._scene.get(item_id).meta)
        if step_index < 0 or step_index >= len(steps):
            self._show_status("Feature step unavailable")
            return
        step = steps[step_index]
        params = self._feature_edit_parameters(step)
        if params is None:
            return
        try:
            update_scene_item_feature_step(self._scene, item_id, step_index, params)
        except (FeatureRebuildError, IndexError, ValueError) as exc:
            LOGGER.warning("Feature edit failed: %s", exc, exc_info=True)
            self._mark_feature_tree_failed(item_id, exc)
            self._show_status("Feature edit failed")
            return
        self._after_feature_history_change(item_id, "Feature step updated")

    def _mark_feature_tree_failed(self, item_id: str, exc: Exception) -> None:
        try:
            mark_scene_item_feature_history_failed(self._scene, item_id, str(exc))
        except (FeatureRebuildError, KeyError):
            return
        self._refresh_hud()

    def _feature_edit_parameters(self, step: dict) -> dict | None:
        kind = step.get("kind")
        params = dict(step.get("params", {}))
        if kind in {"extrude_face", "sketch_extrude", "sketch_profile_feature"}:
            distance, ok = QInputDialog.getDouble(
                self,
                "Edit Feature",
                "Distance (mm)",
                float(params.get("distance", 10.0)),
                -1_000_000.0,
                1_000_000.0,
                2,
            )
            if not ok:
                return None
            return {"distance": distance}
        if kind == "sketch_revolve":
            angle, ok = QInputDialog.getDouble(
                self,
                "Edit Revolve",
                "Angle (deg)",
                float(params.get("angle_degrees", 360.0)),
                -36000.0,
                36000.0,
                2,
            )
            if not ok:
                return None
            elevation, ok = QInputDialog.getDouble(
                self,
                "Edit Revolve",
                "Elevation (mm)",
                float(params.get("elevation", 0.0)),
                -1_000_000.0,
                1_000_000.0,
                2,
            )
            if not ok:
                return None
            return {"angle_degrees": angle, "elevation": elevation}
        if kind == "thread":
            mode, ok = QInputDialog.getItem(
                self,
                "Edit Thread",
                "Representation",
                ["modeled", "cosmetic"],
                0 if params.get("mode", "modeled") == "modeled" else 1,
                False,
            )
            if not ok:
                return None
            thread_type, ok = QInputDialog.getItem(
                self,
                "Edit Thread",
                "Thread Type",
                ["auto", "external", "internal"],
                ["auto", "external", "internal"].index(
                    str(params.get("thread_type", "auto"))
                ),
                False,
            )
            if not ok:
                return None
            pitch, ok = QInputDialog.getDouble(
                self,
                "Edit Thread",
                "Pitch (mm)",
                float(params.get("pitch", 1.0)),
                0.001,
                1_000_000.0,
                3,
            )
            if not ok:
                return None
            length, ok = QInputDialog.getDouble(
                self,
                "Edit Thread",
                "Length (mm)",
                float(params.get("length", 10.0)),
                0.001,
                1_000_000.0,
                2,
            )
            if not ok:
                return None
            depth, ok = QInputDialog.getDouble(
                self,
                "Edit Thread",
                "Depth (mm)",
                float(params.get("depth", 0.5)),
                0.001,
                1_000_000.0,
                3,
            )
            if not ok:
                return None
            return {
                "mode": mode,
                "thread_type": thread_type,
                "pitch": pitch,
                "length": length,
                "depth": depth,
            }
        self._show_status("Feature step is not editable")
        return None

    def _after_feature_history_change(self, item_id: str, status: str) -> None:
        self._scene.set_active_item(item_id)
        self._scene.set_selection(
            SelectionRef(item_id=item_id, kind=SelectionKind.OBJECT, index=0)
        )
        self._hover_selection = None
        if self._viewer.is_initialized:
            self._viewer.display_scene(self._scene, fit=False)
        self._show_status(status)
        self._set_context_hint(status)
        self._refresh_hud()

    def _select_scene_item_from_browser(
        self,
        item_id: str,
        selection_kind: SelectionKind,
        selection_index: int,
    ) -> None:
        if item_id not in self._scene:
            self._refresh_browser()
            return
        scene_object = self._scene.get(item_id)
        self._scene.set_selection(
            SelectionRef(
                item_id=item_id,
                kind=selection_kind,
                index=selection_index,
            )
        )
        self._selection_source = "browser"
        self._selection_kind = selection_kind
        self._hover_selection = None
        self._active_category = (
            "modify" if selection_kind != SelectionKind.OBJECT else "transform"
        )
        self._hide_edge_dimension_editor()
        if self._viewer.is_initialized:
            self._viewer.set_selection_kind(selection_kind)
            self._viewer.display_scene(self._scene, fit=False)
            self._viewer.display_selection_marker(
                scene_object.shape,
                scene_object.meta,
            )
        if is_sketch_profile(scene_object.meta):
            self._show_selected_sketch_dimensions()
            dimension_summary = self._selected_sketch_dimension_summary()
            suffix = f" - {dimension_summary }" if dimension_summary else ""
            self._set_context_hint(
                "Sketch Profile selected - edit, move, extrude, revolve, or delete"
            )
            self._show_status(f"Selected Sketch Profile{suffix }")
        elif is_sketch_object(scene_object.meta):
            if self._viewer.is_initialized:
                self._viewer.clear_dimension_label()
            self._set_context_hint("Sketch entity selected")
            self._show_status("Selected Sketch")
        elif selection_kind == SelectionKind.EDGE:
            measurement = self._selected_edge_measurement()
            current_selection = self._scene.selection()
            if measurement is not None and current_selection is not None:
                self._display_edge_measurement(measurement)
                self._show_edge_dimension_editor(
                    current_selection,
                    measurement,
                )
                if self._selected_edge_is_circular():
                    self._set_context_hint(
                        "Circular edge selected - Thread, Measure, Fillet, or Chamfer"
                    )
                else:
                    self._set_context_hint(
                        "Edge selected - Measure, Edit Length, Fillet, Chamfer, or Move"
                    )
                self._show_status(
                    f"Selected edge {selection_index} - " f"{measurement.length:.2f} mm"
                )
            else:
                self._set_context_hint("Edge selected")
                self._show_status(f"Selected edge {selection_index}")
        elif self._box_dimensions_editable(item_id):
            if self._viewer.is_initialized:
                self._show_selected_box_dimensions()
            self._set_context_hint("Box selected - edit dimensions or move")
            self._show_status(f"Selected box {item_id [:8 ]}")
        else:
            if self._viewer.is_initialized:
                self._viewer.clear_dimension_label()
            self._set_context_hint("Body selected - choose Move or Modify")
            self._show_status(f"Selected body {item_id [:8 ]}")
        self._refresh_hud()
