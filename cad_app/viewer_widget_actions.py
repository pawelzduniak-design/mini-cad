"""Action enablement and contextual command surface for ViewerWidget."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction

from cad_app.sketch import (
    is_sketch_object,
    is_sketch_profile,
)
from cad_app.types import SelectionKind
from cad_app.ui_menu import (
    BODY_ACTIONS,
    BOOLEAN_ACTIONS,
    CATEGORY_DEFS,
    CREATE_ACTIONS,
    EDGE_MODIFY_ACTIONS,
    EMPTY_MODIFY_SECTIONS,
    FACE_MODIFY_ACTIONS,
    FILE_ACTIONS,
    MEASURE_ACTIONS,
    MULTI_BODY_ACTIONS,
    MULTI_PROFILE_ACTIONS,
    PROFILE_ACTIONS,
    SELECT_ACTIONS,
    SKETCH_DRAW_ACTIONS,
    SKETCH_OBJECT_ACTIONS,
    SKETCH_START_ACTIONS,
    VERTEX_MODIFY_ACTIONS,
    VIEW_ACTIONS,
)

LOGGER = logging.getLogger(__name__)

BROWSER_ITEM_ID_ROLE = Qt.UserRole
BROWSER_SELECTION_KIND_ROLE = Qt.UserRole + 1
BROWSER_SELECTION_INDEX_ROLE = Qt.UserRole + 2
BROWSER_COMMAND_ROLE = Qt.UserRole + 3


class ViewerWidgetActionsMixin:
    def _selection_label(self) -> str:
        selections = self._scene.selection_refs()
        if len(selections) > 1:
            kinds = {selection.kind for selection in selections}
            if len(kinds) == 1:
                kind = next(iter(kinds)).value
                if self._selected_sketch_profile_count() == len(selections):
                    return f"Selection: Sketch Profiles ({len(selections)})"
                return f"Selection: {kind}s ({len(selections)})"
            return f"Selection: mixed ({len(selections)})"
        selection = self._scene.selection()
        if selection is None:
            return "Selection: none"
        meta = self._scene.get(selection.item_id).meta
        if is_sketch_profile(meta):
            return "Selection: Sketch Profile"
        if is_sketch_object(meta):
            return "Selection: Sketch"
        return f"Selection: {selection .kind .value } {selection .index }"

    def _tool_label(self) -> str:
        if self._sketch_session is not None:
            return f"Tool: Sketch {self ._sketch_session .tool }"
        if self._move_session is None:
            return "Tool: idle"
        if (
            self._move_session.tool == "sketch_extrude"
            and self._move_session.operation == "new_body"
        ):
            return (
                f"Tool: New Body {self ._move_session .axis_name } "
                f"{self ._move_session .distance :.2f}"
            )
        if self._move_session.tool == "rotate":
            return (
                f"Tool: Rotate {self ._move_session .axis_name } "
                f"{self ._move_session .distance :.2f} deg"
            )
        if self._move_session.tool == "sketch_revolve":
            suffix = (
                f", elev {self ._move_session .elevation :.2f}"
                if abs(self._move_session.elevation) > 1e-7
                else ""
            )
            return (
                f"Tool: Revolve {self ._move_session .axis_name } "
                f"{self ._move_session .distance :.2f} deg{suffix}"
            )
        if self._move_session.tool == "fillet":
            return f"Tool: Fillet R {self ._move_session .distance :.2f}"
        if self._move_session.tool == "chamfer":
            return f"Tool: Chamfer {self ._move_session .distance :.2f}"
        tool_names = {
            "sketch_extrude": "Sketch Extrude",
            "sketch_move": "Sketch Move",
            "extrude": "Extrude",
            "move": "Move",
        }
        tool_name = tool_names.get(
            self._move_session.tool,
            self._move_session.tool.title(),
        )
        return (
            f"Tool: {tool_name } {self ._move_session .axis_name } "
            f"{self ._move_session .distance :.2f}"
        )

    def _sketch_label(self) -> str:
        if self._sketch_session is None:
            return "Sketch: none"
        label = f"Sketch: {self ._sketch_session .label }"
        if self._sketch_session.drag_dimensions is not None:
            return f"{label } {self ._sketch_session .drag_dimensions }"
        return label

    def _refresh_action_state(self) -> None:
        if not self._actions:
            return
        sketch_active = self._sketch_session is not None
        tool_active = self._move_session is not None or sketch_active
        selection = self._scene.selection()
        selections = self._scene.selection_refs()
        selection_count = len(selections)
        multi_selection = selection_count > 1
        sketch_tools_available = sketch_active
        selected_face = (
            not multi_selection
            and selection is not None
            and selection.kind == SelectionKind.FACE
        )
        selected_object = (
            not multi_selection
            and selection is not None
            and selection.kind == SelectionKind.OBJECT
        )
        selected_edge = (
            not multi_selection
            and selection is not None
            and selection.kind == SelectionKind.EDGE
        )
        selected_vertex = (
            not multi_selection
            and selection is not None
            and selection.kind == SelectionKind.VERTEX
        )
        selected_edge_length_editable = (
            selected_edge and self._selected_edge_length_editable()
        )
        selected_box_dimensions_editable = (
            not multi_selection
            and selection is not None
            and self._box_dimensions_editable(selection.item_id)
        )
        selected_profile_count = self._selected_sketch_profile_count()
        selected_body_count = self._selected_body_count()
        multi_profile = multi_selection and selected_profile_count == selection_count
        multi_body = multi_selection and selected_body_count == selection_count
        selected_profile = (
            not multi_selection and self._selected_item_is_sketch_profile()
        ) or multi_profile
        selected_sketch_object = (
            not multi_selection and self._selected_item_is_sketch_object()
        )
        selected_sketch_geometry = selected_sketch_object or multi_profile
        body_count = len(self._body_item_ids())
        boolean_target_item_id = self._valid_boolean_target_item_id()
        boolean_tool_item_id = (
            None if multi_selection else self._selected_or_active_body_item_id()
        )
        boolean_ready = (
            boolean_target_item_id is not None
            and boolean_tool_item_id is not None
            and boolean_tool_item_id != boolean_target_item_id
            and not tool_active
        )
        active_item_id = self._scene.active_item_id()
        active_body = (
            not multi_selection
            and active_item_id is not None
            and not is_sketch_object(self._scene.get(active_item_id).meta)
        )
        selected_object_body = (
            selected_object
            and selection is not None
            and not is_sketch_object(self._scene.get(selection.item_id).meta)
        )
        view_move_supported = (
            not multi_selection and self._selection_supports_view_move(selection)
        )
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
            start_sketch_action.setText(
                "New Sketch (Face Plane)" if selected_face else "New Sketch (Bottom)"
            )
        for category in CATEGORY_DEFS:
            action = self._actions.get(category.action_name)
            if action is not None:
                action.setChecked(self._active_category == category.category_id)
        for kind, action_name in (
            (SelectionKind.OBJECT, "select_object"),
            (SelectionKind.FACE, "select_face"),
            (SelectionKind.EDGE, "select_edge"),
            (SelectionKind.VERTEX, "select_vertex"),
        ):
            action = self._actions.get(action_name)
            if action is not None:
                action.setChecked(self._selection_kind == kind)
        select_through_action = self._actions.get("select_through")
        if select_through_action is not None:
            select_through_action.setChecked(self._select_through)
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
        move_active = self._move_session is not None or self._sketch_session is not None
        cancel_action = self._actions.get("cancel_tool")
        if cancel_action is not None:
            cancel_action.setEnabled(move_active)
        category_enabled = self._move_session is None
        category_enabled_by_action = {
            category.action_name: category_enabled for category in CATEGORY_DEFS
        }
        category_enabled_by_action["category_transform"] = (
            category_enabled and body_count > 0
        )
        enabled_by_context = {
            **category_enabled_by_action,
            "undo": self._scene.can_undo() and not tool_active,
            "redo": self._scene.can_redo() and not tool_active,
            "save_project": True,
            "import_step": not tool_active,
            "add_box": not tool_active,
            "export_step": active_body or selected_object_body,
            "delete_object": (
                not tool_active
                and not multi_body
                and (selected_object_body or (selection is None and active_body))
            ),
            "select_through": not tool_active,
            "move_object": (active_body or selected_object_body or multi_body)
            and not tool_active,
            "move_object_x": (active_body or selected_object_body or multi_body)
            and not tool_active,
            "move_object_y": (active_body or selected_object_body or multi_body)
            and not tool_active,
            "move_object_z": (active_body or selected_object_body or multi_body)
            and not tool_active,
            "edit_box_dimensions": selected_box_dimensions_editable and not tool_active,
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
            "rotate_body": (active_body or selected_object_body)
            and not multi_body
            and not tool_active,
            "rotate_body_x": (active_body or selected_object_body)
            and not multi_body
            and not tool_active,
            "rotate_body_y": (active_body or selected_object_body)
            and not multi_body
            and not tool_active,
            "rotate_body_z": (active_body or selected_object_body)
            and not multi_body
            and not tool_active,
            "mirror_body": (active_body or selected_object_body)
            and not multi_body
            and not tool_active,
            "set_boolean_target": (
                body_count >= 2 and boolean_tool_item_id is not None and not tool_active
            ),
            "clear_boolean_target": boolean_target_item_id is not None,
            "boolean_union": boolean_ready,
            "boolean_subtract": boolean_ready,
            "boolean_intersect": boolean_ready,
            "start_sketch": (not tool_active),
            "new_sketch": (not tool_active or self._sketch_session is not None),
            "sketch_rectangle_tool": sketch_tools_available,
            "sketch_line_tool": sketch_tools_available,
            "sketch_arc_tool": sketch_tools_available,
            "sketch_rectangle3_tool": sketch_tools_available,
            "sketch_center_rectangle_tool": sketch_tools_available,
            "sketch_circle_tool": sketch_tools_available,
            "sketch_trim": (
                sketch_tools_available
                or (selected_sketch_object and self._move_session is None)
            ),
            "edit_sketch": (
                selected_sketch_object and not multi_profile and not tool_active
            ),
            "finish_sketch": sketch_active,
            "edit_sketch_dimensions": (
                selected_profile
                and not multi_profile
                and self._move_session is None
                and self._selected_sketch_profile_dimensions_editable()
            ),
            "move_sketch": selected_sketch_geometry and not tool_active,
            "move_sketch_x": selected_sketch_geometry and not tool_active,
            "move_sketch_y": selected_sketch_geometry and not tool_active,
            "move_sketch_z": selected_sketch_geometry and not tool_active,
            "sketch_extrude": selected_profile and not tool_active,
            "sketch_new_body": selected_profile and not tool_active,
            "sketch_revolve": selected_profile
            and not multi_profile
            and not tool_active,
            "sketch_revolve_x": (
                selected_profile and not multi_profile and not tool_active
            ),
            "sketch_revolve_y": (
                selected_profile and not multi_profile and not tool_active
            ),
            "sketch_revolve_z": (
                selected_profile and not multi_profile and not tool_active
            ),
            "delete_sketch": selected_sketch_geometry and not tool_active,
            "extrude": selected_face and not selected_profile and not tool_active,
            "extrude_reverse": (
                selected_face and not selected_profile and not tool_active
            ),
            "circle_boss": (selected_face and not selected_profile and not tool_active),
            "circle_cut": (selected_face and not selected_profile and not tool_active),
            "offset_face": False,
            "remove_face": (selected_face and not selected_profile and not tool_active),
            "fillet": selected_edge and not tool_active,
            "chamfer": selected_edge and not tool_active,
            "thread": (
                selected_edge and self._selected_edge_is_circular() and not tool_active
            ),
            "edit_edge_length": selected_edge_length_editable and not tool_active,
            "measure_distance": selected_edge and not tool_active,
            "measure_angle": False,
            "measure_radius": False,
        }
        active_command_action = self._active_command_action_name()
        if active_command_action is not None:
            enabled_by_context[active_command_action] = True
        for action_name, enabled in enabled_by_context.items():
            action = self._actions.get(action_name)
            if action is not None:
                action.setEnabled(bool(enabled))
        self._refresh_command_surface()
        if self._sketch_toolbar is not None:
            sketch_active = (
                self._active_category == "sketch" or self._sketch_session is not None
            )
            self._sketch_toolbar.setVisible(sketch_active)

    def _selected_item_is_sketch_profile(self) -> bool:
        if self._selected_sketch_profile_count() > 0:
            return True
        selection = self._scene.selection()
        if selection is None:
            return False
        return is_sketch_profile(self._scene.get(selection.item_id).meta)

    def _selected_sketch_profile_refs(self) -> tuple:
        return tuple(
            selection
            for selection in self._scene.selection_refs()
            if selection.item_id in self._scene
            and is_sketch_profile(self._scene.get(selection.item_id).meta)
        )

    def _selected_sketch_profile_count(self) -> int:
        return len(self._selected_sketch_profile_refs())

    def _selected_body_refs(self) -> tuple:
        return tuple(
            selection
            for selection in self._scene.selection_refs()
            if selection.kind == SelectionKind.OBJECT
            and selection.item_id in self._scene
            and not is_sketch_object(self._scene.get(selection.item_id).meta)
        )

    def _selected_body_count(self) -> int:
        return len(self._selected_body_refs())

    def _selected_item_is_sketch_object(self) -> bool:
        selection = self._scene.selection()
        if selection is None:
            return False
        return is_sketch_object(self._scene.get(selection.item_id).meta)

    def _context_command_sections(self) -> list[tuple[str, list[str]]]:
        if self._sketch_session is not None:
            sketch_actions = list(SKETCH_DRAW_ACTIONS)
            sections = [
                (
                    "Sketch",
                    sketch_actions,
                )
            ]
            if self._selected_sketch_profile_dimensions_editable():
                sections.append(("Selected Profile", ["edit_sketch_dimensions"]))
            sections.append(("Finish", ["finish_sketch"]))
            return [
                *sections,
            ]
        if self._move_session is not None:
            active_action = self._active_command_action_name()
            actions = [action for action in (active_action, "cancel_tool") if action]
            return [("Active Tool", actions)]

        selection = self._scene.selection()
        selections = self._scene.selection_refs()
        if self._active_category == "select":
            return [("Selection Mode", list(SELECT_ACTIONS))]
        if self._active_category == "sketch":
            if self._sketch_session is None:
                return [
                    ("Start", list(SKETCH_START_ACTIONS)),
                ]
            return [
                ("Sketch", list(SKETCH_DRAW_ACTIONS)),
                ("Finish", ["finish_sketch"]),
            ]
        if len(selections) > 1:
            if self._selected_sketch_profile_count() == len(selections):
                return [("Profiles", list(MULTI_PROFILE_ACTIONS))]
            if self._selected_body_count() == len(selections):
                return [("Bodies", list(MULTI_BODY_ACTIONS))]
            return []
        if (
            selection is not None
            and self._sketch_session is None
            and self._selected_item_is_sketch_profile()
        ):
            return [
                (
                    "Profile",
                    list(PROFILE_ACTIONS),
                ),
            ]
        if (
            selection is not None
            and self._sketch_session is None
            and self._selected_item_is_sketch_object()
        ):
            return [
                (
                    "Sketch",
                    list(SKETCH_OBJECT_ACTIONS),
                ),
            ]
        if self._active_category == "create":
            return [("Create", list(CREATE_ACTIONS))]

        boolean_target_item_id = self._valid_boolean_target_item_id()
        boolean_tool_item_id = self._selected_or_active_body_item_id()
        boolean_section = list(BOOLEAN_ACTIONS)
        active_boolean_section = ["set_boolean_target"]
        if boolean_target_item_id is not None:
            active_boolean_section.append("clear_boolean_target")
        if (
            boolean_target_item_id is not None
            and boolean_tool_item_id is not None
            and boolean_tool_item_id != boolean_target_item_id
        ):
            active_boolean_section.extend(
                ["boolean_union", "boolean_subtract", "boolean_intersect"]
            )
        if self._active_category == "boolean":
            return [("Boolean", boolean_section)]
        if self._active_category == "transform":
            if len(selections) > 1 and self._selected_body_count() == len(selections):
                return [("Bodies", list(MULTI_BODY_ACTIONS))]
            if len(self._body_item_ids()) == 0:
                return [
                    (
                        "Body",
                        list(BODY_ACTIONS),
                    )
                ]
            if (
                selection is not None
                and selection.kind != SelectionKind.OBJECT
                and not self._selected_item_is_sketch_profile()
            ):
                return [
                    (
                        "Body",
                        list(BODY_ACTIONS),
                    )
                ]
            return [
                (
                    "Body",
                    list(BODY_ACTIONS) + active_boolean_section,
                ),
            ]
        if self._active_category == "view":
            return [
                (
                    "View",
                    list(VIEW_ACTIONS),
                )
            ]
        if self._active_category == "file":
            return [("File", list(FILE_ACTIONS))]
        if self._active_category == "measure":
            return [("Measure", list(MEASURE_ACTIONS))]
        if selection is None:
            return [
                (section_name, list(action_names))
                for section_name, action_names in EMPTY_MODIFY_SECTIONS
            ]
        if selection.kind == SelectionKind.OBJECT:
            if len(selections) > 1 and self._selected_body_count() == len(selections):
                return [("Bodies", list(MULTI_BODY_ACTIONS))]
            return [
                (
                    "Body",
                    list(BODY_ACTIONS) + active_boolean_section,
                )
            ]
        if selection.kind == SelectionKind.FACE:
            return [("Face", list(FACE_MODIFY_ACTIONS))]
        if selection.kind == SelectionKind.EDGE:
            edge_actions = list(EDGE_MODIFY_ACTIONS)
            if self._selected_edge_is_circular():
                edge_actions.insert(3, "thread")
            return [("Edge", edge_actions)]
        if selection.kind == SelectionKind.VERTEX:
            return [("Vertex", list(VERTEX_MODIFY_ACTIONS))]
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
        if self._move_session.tool == "sketch_move":
            return "move_sketch"
        if self._move_session.tool == "rotate":
            return "rotate_body"
        if self._move_session.tool == "sketch_revolve":
            return "sketch_revolve"
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
        for section_index, (section_name, action_names) in enumerate(sections):
            enabled_actions = [
                action
                for action_name in action_names
                if (action := self._actions.get(action_name)) is not None
                and action.isEnabled()
            ]
            if not enabled_actions:
                continue
            if section_index > 0:
                self._command_menu.addSeparator()
                self._command_toolbar.addSeparator()
            label_action = self._make_command_section_label(section_name)
            self._command_menu.addAction(label_action)
            for action in enabled_actions:
                self._command_menu.addAction(action)
                self._command_toolbar.addAction(action)
        self._command_toolbar.setVisible(True)

    def _make_command_section_label(self, text: str):

        existing = self._command_section_actions.get(text)
        if existing is not None:
            return existing
        action = QAction(text, self)
        action.setObjectName(f"context_label_{text .lower ().replace (' ','_')}")
        action.setEnabled(False)
        self._command_section_actions[text] = action
        return action
