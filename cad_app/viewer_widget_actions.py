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
from cad_app.ui_chrome import assign_toolbar_button_object_names
from cad_app.ui_menu import (
    BODY_ACTIONS,
    BOOLEAN_ACTIONS,
    CATEGORY_DEFS,
    EDGE_MODIFY_ACTIONS,
    EMPTY_MODIFY_SECTIONS,
    FACE_MODIFY_ACTIONS,
    MULTI_BODY_ACTIONS,
    MULTI_PROFILE_ACTIONS,
    PROFILE_ACTIONS,
    SELECT_ACTIONS,
    SKETCH_DRAW_ACTIONS,
    SKETCH_OBJECT_ACTIONS,
    SKETCH_START_ACTIONS,
    VERTEX_MODIFY_ACTIONS,
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
        if (
            self._move_session.tool == "sketch_extrude"
            and self._move_session.operation == "cut"
        ):
            return (
                f"Tool: Extrude Cut {self ._move_session .axis_name } "
                f"{abs(self ._move_session .distance) :.2f}"
            )
        if self._move_session.tool in {"extrude", "sketch_extrude"}:
            return (
                f"Tool: Extrude {self ._move_session .axis_name } "
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
        if self._move_session.tool == "fillet_chamfer":
            value = self._move_session.distance
            tool_name = "Fillet" if value >= 0.0 else "Chamfer"
            return f"Tool: {tool_name} {abs(value) :.2f}"
        tool_names = {
            "sketch_move": "Move",
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
        hosted_selected_profile = (
            selected_profile
            and not multi_profile
            and self._selected_sketch_profile_has_host()
        )
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
        active_body_without_selection = selection is None and active_body
        body_transform_available = selected_object_body or multi_body
        single_body_transform_available = selected_object_body
        # Rotate accepts an optional "pivot" subshape: exactly one body
        # plus exactly one vertex / edge / face means rotate around that
        # subshape's centre instead of the body's bounding-box centre.
        selected_body_refs = self._selected_body_refs()
        selected_subshape_refs = tuple(
            ref
            for ref in selections
            if ref.kind
            in {SelectionKind.VERTEX, SelectionKind.EDGE, SelectionKind.FACE}
        )
        body_with_pivot = (
            len(selected_body_refs) == 1
            and len(selected_subshape_refs) == 1
            and len(selections) == 2
        )
        rotate_eligible = (
            single_body_transform_available and not multi_body
        ) or body_with_pivot
        # Revolve accepts an optional construction line (open
        # line_segments entity) as the axis. Pair: one profile + one
        # line entity.
        construction_line_refs = tuple(
            ref
            for ref in selections
            if ref.item_id in self._scene
            and self._scene.get(ref.item_id).meta.get("kind") == "sketch_entity"
            and self._scene.get(ref.item_id).meta.get("profile") == "line_segments"
        )
        profile_with_axis_line = (
            selected_profile_count == 1
            and len(construction_line_refs) == 1
            and len(selections) == 2
        )
        revolve_eligible = (
            selected_profile and not multi_profile
        ) or profile_with_axis_line
        selected_position_editable = (
            not tool_active
            and not multi_selection
            and (
                selected_object_body
                or active_body_without_selection
                or selected_sketch_object
                or (not multi_selection and self._selected_item_is_sketch_profile())
            )
        )
        view_move_supported = (
            not multi_selection and self._selection_supports_view_move(selection)
        )
        face_normal_move_supported = (
            selected_face
            and not selected_profile
            and self._selection_supports_face_normal_move(selection)
        )
        local_move_supported = view_move_supported or face_normal_move_supported
        move_action = self._actions.get("move")
        if move_action is not None:
            move_action.setText("Move")
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
        edit_position_action = self._actions.get("edit_position")
        if edit_position_action is not None:
            if selected_sketch_object or (
                not multi_selection and self._selected_item_is_sketch_profile()
            ):
                edit_position_action.setText("Set Sketch Position")
            else:
                edit_position_action.setText("Set Body Position")
        if not hosted_selected_profile and not tool_active:
            self._sketch_extrude_operation = "add"
        sketch_cut_mode_action = self._actions.get("sketch_cut_mode")
        if sketch_cut_mode_action is not None:
            sketch_cut_mode_action.setChecked(
                self._sketch_extrude_operation == "cut" and hosted_selected_profile
            )
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
            # Undo / redo are allowed while a sketch session is active so a
            # beginner can step back through committed sketch profiles
            # (Ctrl+Z right after drawing a rectangle should work). They
            # stay disabled only while a move/extrude/fillet drag is open
            # because cancelling that mid-tool would leave dangling state.
            "undo": self._scene.can_undo() and self._move_session is None,
            "redo": self._scene.can_redo() and self._move_session is None,
            "new_project": True,
            "save_project": not tool_active and len(self._body_item_ids()) > 0,
            "open_project": not tool_active,
            "import_step": not tool_active,
            "add_box": not tool_active,
            "export_step": active_body_without_selection or selected_object_body,
            "delete_object": (
                not tool_active
                and not multi_body
                and (selected_object_body or active_body_without_selection)
            ),
            "select_through": not tool_active,
            "move": (
                (
                    body_transform_available
                    or selected_sketch_geometry
                    or selected_profile
                    or (
                        selection is not None
                        and selection.kind != SelectionKind.OBJECT
                        and local_move_supported
                    )
                )
                and not tool_active
                and boolean_target_item_id is None
            ),
            "move_object": False,
            "move_object_x": False,
            "move_object_y": False,
            "move_object_z": False,
            "edit_box_dimensions": selected_box_dimensions_editable and not tool_active,
            "edit_position": selected_position_editable,
            "move_selection": False,
            "move_selection_normal": False,
            "move_selection_x": False,
            "move_selection_y": False,
            "move_selection_z": False,
            "rotate_body": rotate_eligible
            and not tool_active
            and boolean_target_item_id is None,
            "rotate_body_x": False,
            "rotate_body_y": False,
            "rotate_body_z": False,
            "mirror_body": (
                not tool_active
                and (selected_object_body or active_body_without_selection)
            ),
            "rib_feature": (
                not tool_active
                and selection_count == 2
                and all(sel.kind == SelectionKind.FACE for sel in selections)
                and len({sel.item_id for sel in selections}) == 1
            ),
            "measure_axis_distance": (
                selection_count == 2
                and all(
                    sel.kind in (SelectionKind.FACE, SelectionKind.EDGE)
                    for sel in selections
                )
            ),
            "set_boolean_target": selected_object_body
            and not tool_active
            and boolean_target_item_id is None,
            "clear_boolean_target": boolean_target_item_id is not None,
            "cancel_boolean": boolean_target_item_id is not None,
            "boolean_union": boolean_ready,
            "boolean_subtract": boolean_ready,
            "boolean_intersect": boolean_ready,
            "start_sketch": (not tool_active),
            "new_sketch": (not tool_active or self._sketch_session is not None),
            "sketch_rectangle_tool": sketch_tools_available,
            "sketch_line_tool": sketch_tools_available,
            "sketch_arc_tool": sketch_tools_available,
            "sketch_circle2_tool": sketch_tools_available,
            "sketch_center_radius_tool": sketch_tools_available,
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
            "move_sketch": False,
            "move_sketch_x": False,
            "move_sketch_y": False,
            "move_sketch_z": False,
            "push_pull": False,
            # Extrude / Sketch New Body / Sketch Revolve are the natural way
            # out of a sketch session: _begin_extrude_tool calls
            # _finish_sketch_for_modeling_command internally. Blocking these
            # actions while a sketch is open forces beginners into an extra
            # "Finish Sketch" click that should not be required.
            "extrude": (selected_face or selected_profile)
            and self._move_session is None,
            "sketch_extrude": False,
            "sketch_new_body": selected_profile and self._move_session is None,
            "sketch_cut_mode": False,
            "sketch_revolve": revolve_eligible and self._move_session is None,
            "sketch_revolve_x": False,
            "sketch_revolve_y": False,
            "sketch_revolve_z": False,
            "delete_sketch": selected_sketch_geometry and not tool_active,
            "extrude_reverse": (
                selected_face and not selected_profile and not tool_active
            ),
            "circle_boss": False,
            "circle_cut": False,
            "offset_face": False,
            "remove_face": (selected_face and not selected_profile and not tool_active),
            "fillet_chamfer": selected_edge and not tool_active,
            "fillet": False,
            "chamfer": False,
            "thread": (
                not tool_active
                and (
                    (selected_edge and self._selected_edge_is_circular())
                    or (
                        selected_face
                        and not selected_profile
                        and self._selected_face_is_cylindrical()
                    )
                )
            ),
            "edit_edge_length": selected_edge_length_editable and not tool_active,
            "measure_distance": False,
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

    def _selected_sketch_profile_has_host(self) -> bool:
        refs = self._scene.selection_refs()
        if len(refs) != 1:
            return False
        selection = refs[0]
        if selection.item_id not in self._scene:
            return False
        meta = self._scene.get(selection.item_id).meta
        host_item_id = meta.get("host_item_id")
        return (
            is_sketch_profile(meta)
            and isinstance(host_item_id, str)
            and (host_item_id in self._scene)
        )

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
        def select_sections(
            sections: list[tuple[str, list[str]]] | None = None,
        ) -> list[tuple[str, list[str]]]:
            if self._active_category != "select":
                return sections or []
            return [
                ("Selection Mode", list(SELECT_ACTIONS)),
                *(sections or []),
            ]

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
        boolean_target_item_id = self._valid_boolean_target_item_id()
        if boolean_target_item_id is not None:
            boolean_tool_item_id = self._selected_or_active_body_item_id()
            boolean_ready = (
                boolean_tool_item_id is not None
                and boolean_tool_item_id != boolean_target_item_id
            )
            if boolean_ready:
                return [
                    (
                        "Boolean",
                        [
                            "boolean_union",
                            "boolean_subtract",
                            "boolean_intersect",
                            "cancel_boolean",
                        ],
                    )
                ]
            return select_sections([("Boolean", ["cancel_boolean"])])
        if self._active_category == "select" and not selections:
            return select_sections()
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
                return select_sections([("Profiles", list(MULTI_PROFILE_ACTIONS))])
            if self._selected_body_count() == len(selections):
                return select_sections(
                    [("Bodies", [*MULTI_BODY_ACTIONS, *BOOLEAN_ACTIONS])]
                )
            return select_sections()
        if (
            selection is not None
            and self._sketch_session is None
            and self._selected_item_is_sketch_profile()
        ):
            return select_sections([("Profile", list(PROFILE_ACTIONS))])
        if (
            selection is not None
            and self._sketch_session is None
            and self._selected_item_is_sketch_object()
        ):
            return select_sections([("Sketch", list(SKETCH_OBJECT_ACTIONS))])
        if selection is None:
            return select_sections(
                [
                    (section_name, list(action_names))
                    for section_name, action_names in EMPTY_MODIFY_SECTIONS
                ]
            )
        if selection.kind == SelectionKind.OBJECT:
            if len(selections) > 1 and self._selected_body_count() == len(selections):
                return select_sections(
                    [("Bodies", [*MULTI_BODY_ACTIONS, *BOOLEAN_ACTIONS])]
                )
            return select_sections([("Body", [*BODY_ACTIONS, *BOOLEAN_ACTIONS])])
        if selection.kind == SelectionKind.FACE:
            face_actions = list(FACE_MODIFY_ACTIONS)
            if self._selected_face_is_cylindrical():
                face_actions.append("thread")
            return select_sections([("Face", face_actions)])
        if selection.kind == SelectionKind.EDGE:
            edge_actions = list(EDGE_MODIFY_ACTIONS)
            if self._selected_edge_is_circular():
                edge_actions.append("thread")
            return select_sections([("Edge", edge_actions)])
        if selection.kind == SelectionKind.VERTEX:
            return select_sections([("Vertex", list(VERTEX_MODIFY_ACTIONS))])
        return select_sections()

    def _active_command_action_name(self) -> str | None:
        if self._move_session is None:
            return None
        if self._move_session.tool == "extrude":
            return "extrude"
        if self._move_session.tool == "sketch_extrude":
            if self._move_session.operation == "new_body":
                return "sketch_new_body"
            return "extrude"
        if self._move_session.tool == "move":
            return "move"
        if self._move_session.tool == "sketch_move":
            return "move"
        if self._move_session.tool == "rotate":
            return "rotate_body"
        if self._move_session.tool == "sketch_revolve":
            return "sketch_revolve"
        if self._move_session.tool == "fillet":
            return "fillet_chamfer"
        if self._move_session.tool == "chamfer":
            return "fillet_chamfer"
        if self._move_session.tool == "fillet_chamfer":
            return "fillet_chamfer"
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
        assign_toolbar_button_object_names(self._command_toolbar)
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
