"""Move, extrude, and direct modeling tool setup for ViewerWidget."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt

from cad_app.commands import (
    CommandError,
    apply_move_edge_controlled,
    apply_move_face_normal,
    apply_move_object,
    apply_move_vertex_controlled,
    face_normal_vector,
    supports_move_edge_controlled,
    supports_move_face_controlled,
    supports_move_vertex_controlled,
)
from cad_app.sketch import (
    is_sketch_object,
    is_sketch_profile,
)
from cad_app.types import SelectionKind, SelectionRef
from cad_app.ui_sessions import (
    DEFAULT_EDGE_PARAMETER,
    MoveSession,
)

LOGGER = logging.getLogger(__name__)

BROWSER_ITEM_ID_ROLE = Qt.UserRole
BROWSER_SELECTION_KIND_ROLE = Qt.UserRole + 1
BROWSER_SELECTION_INDEX_ROLE = Qt.UserRole + 2
BROWSER_COMMAND_ROLE = Qt.UserRole + 3


class ViewerWidgetMoveToolsMixin:
    def _selected_face(self) -> tuple[str | None, int | None]:
        selection = self._scene.selection()
        if selection is not None and selection.kind == SelectionKind.FACE:
            return selection.item_id, selection.index
        return None, None

    def _selected_edge(self) -> tuple[str | None, int | None]:
        selection = self._scene.selection()
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
        if self._block_modeling_command_during_sketch(tool.title()):
            return
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
            f"{action_name }: drag to set value, Enter apply, Esc cancel"
        )
        self._show_status(f"{action_name }: drag value")
        self._refresh_hud()
        LOGGER.info("%s tool started item_id=%s edge=%d", tool, item_id, edge_index)

    def _move_selected(self, distance: float) -> None:
        selection = self._scene.selection()
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
        if self._block_modeling_command_during_sketch("Move"):
            return
        selection = self._scene.selection()
        selected_body_item_ids = self._selected_body_item_ids()
        if len(self._scene.selection_refs()) > 1:
            if not selected_body_item_ids:
                self._show_status("Select bodies to move together")
                return
            item_id = selected_body_item_ids[0]
        elif selection is not None and selection.kind != SelectionKind.OBJECT:
            self._show_status("Use Modify tools for selected topology")
            LOGGER.info(
                "Object move ignored because %s is selected",
                selection.kind.value,
            )
            return
        else:
            item_id = (
                selection.item_id
                if selection is not None
                else self._scene.active_item_id()
            )
            selected_body_item_ids = (item_id,) if item_id is not None else ()
        if item_id is None:
            self._show_status("No active object")
            return
        if item_id not in self._scene or is_sketch_object(
            self._scene.get(item_id).meta
        ):
            self._show_status("Select a body first")
            return
        self._move_session = MoveSession(
            tool="move",
            target_kind="object",
            item_id=item_id,
            index=None,
            axis_name=axis_name,
            axis=axis,
            item_ids=selected_body_item_ids,
        )
        self._viewer.clear_preview_marker()
        body_label = "bodies" if len(selected_body_item_ids) > 1 else "body"
        if axis_name == "View":
            self._set_context_hint(
                f"Move {body_label}: drag in view, Enter apply, Esc cancel"
            )
            self._show_status(
                f"Move {body_label}: drag in view, Enter apply, Esc cancel"
            )
        else:
            self._set_context_hint(
                f"Move {body_label} {axis_name }: drag, Enter apply, Esc cancel"
            )
            self._show_status(
                f"Move {body_label} {axis_name }: drag, Enter apply, Esc cancel"
            )
        self._refresh_hud()
        LOGGER.info(
            "Move tool started for object item_ids=%s axis=%s",
            selected_body_item_ids,
            axis_name,
        )

    def _begin_object_rotate_tool(self) -> None:
        self._begin_object_rotate_tool_on_axis(self._move_axis_name, self._move_axis)

    def _begin_object_rotate_tool_on_axis(
        self,
        axis_name: str,
        axis: tuple[float, float, float],
    ) -> None:
        if self._block_modeling_command_during_sketch("Rotate"):
            return
        selection = self._scene.selection()
        if selection is not None and selection.kind != SelectionKind.OBJECT:
            self._show_status("Select a body to rotate")
            return
        item_id = (
            selection.item_id if selection is not None else self._scene.active_item_id()
        )
        if item_id is None:
            self._show_status("Select a body first")
            return
        if item_id not in self._scene or is_sketch_object(
            self._scene.get(item_id).meta
        ):
            self._show_status("Select a body first")
            return
        self._move_session = MoveSession(
            tool="rotate",
            target_kind="object",
            item_id=item_id,
            index=None,
            axis_name=axis_name,
            axis=axis,
        )
        self._move_axis_name = axis_name
        self._move_axis = axis
        if hasattr(self, "_orientation_gizmo_overlay"):
            self._orientation_gizmo_overlay.set_axis_name(axis_name)
        self._viewer.clear_preview_marker()
        self._show_dimension_overlay(
            self._move_overlay_label(self._move_session),
            self.width() // 2,
            self.height() // 2,
        )
        self._set_context_hint(
            "Rotate: drag to set angle, X/Y/Z changes axis, Enter apply, Esc cancel"
        )
        self._show_status(f"Rotate body {axis_name }: drag angle")
        self._refresh_hud()
        LOGGER.info(
            "Rotate tool started item_id=%s axis=%s",
            item_id,
            axis_name,
        )

    def _begin_selected_move_tool(self) -> None:
        self._begin_selected_move_tool_on_axis(
            "View",
            (0.0, 0.0, 0.0),
        )

    def _begin_sketch_move_tool(self) -> None:
        self._begin_sketch_move_tool_on_axis(
            "View",
            (0.0, 0.0, 0.0),
        )

    def _begin_sketch_move_tool_on_axis(
        self,
        axis_name: str,
        axis: tuple[float, float, float],
    ) -> None:
        if self._sketch_session is not None:
            self._show_status("Finish sketch before moving sketch geometry")
            self._set_context_hint("Finish the active sketch before Move Sketch")
            return
        item_ids = self._selected_sketch_object_item_ids()
        if not item_ids:
            self._show_status("Select sketch geometry first")
            LOGGER.info("Sketch move ignored because no sketch geometry is selected")
            return
        first_id = item_ids[0]
        self._move_session = MoveSession(
            tool="sketch_move",
            target_kind="sketch",
            item_id=first_id,
            index=None,
            axis_name=axis_name,
            axis=axis,
            item_ids=item_ids,
        )
        if hasattr(self, "_orientation_gizmo_overlay"):
            self._orientation_gizmo_overlay.set_axis_name(axis_name)
        self._viewer.clear_preview_marker()
        if axis_name == "View":
            self._set_context_hint("Move Sketch: drag in view, Enter apply, Esc cancel")
            self._show_status("Move Sketch: drag in view")
        else:
            self._set_context_hint(
                f"Move Sketch {axis_name}: drag, Enter apply, Esc cancel"
            )
            self._show_status(f"Move Sketch {axis_name}: drag")
        self._show_dimension_overlay(
            self._move_overlay_label(self._move_session),
            self.width() // 2,
            self.height() // 2,
        )
        self._refresh_hud()
        self._refresh_action_state()
        LOGGER.info("Sketch move started item_ids=%s axis=%s", item_ids, axis_name)

    def _begin_selected_move_tool_on_axis(
        self,
        axis_name: str,
        axis: tuple[float, float, float],
    ) -> None:
        if self._block_modeling_command_during_sketch("Move"):
            return
        selection = self._scene.selection()
        if selection is None:
            self._show_status("Select topology first")
            LOGGER.info("Move tool ignored because nothing is selected")
            return
        if selection.kind == SelectionKind.OBJECT:
            self._begin_object_move_tool_on_axis(axis_name, axis)
            return
        if selection.kind == SelectionKind.FACE:
            axis_name = "Normal" if axis_name == "Normal" else axis_name
        if axis_name != "Normal" and not self._selection_supports_view_move(selection):
            self._show_status(
                f"Move {selection .kind .value } unavailable for curved topology"
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
            self._set_context_hint(
                f"Move {selection .kind .value }: drag in view, "
                "Enter apply, Esc cancel"
            )
            self._show_status(
                f"Move {selection .kind .value }: drag in view, "
                "Enter apply, Esc cancel"
            )
        else:
            self._set_context_hint(
                f"Move {selection .kind .value } {axis_name }: "
                "drag, Enter apply, Esc cancel"
            )
            self._show_status(
                f"Move {selection .kind .value } {axis_name }: "
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
        scene_object = self._scene.get(selection.item_id)
        if is_sketch_profile(scene_object.meta):
            return False
        try:
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
        except (CommandError, IndexError, TypeError, AttributeError):
            return False
        except ModuleNotFoundError:
            return False
        return False

    def _begin_selected_move_normal_tool(self) -> None:
        selection = self._scene.selection()
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
        selection = self._scene.selection()
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
        if self._sketch_session is not None:
            if not self._finish_sketch_for_modeling_command():
                return
        profile_item_ids = self._selected_sketch_profile_item_ids()
        if len(profile_item_ids) > 1:
            first_id = profile_item_ids[0]
            axis = self._face_normal(first_id, 1)
            self._move_session = MoveSession(
                tool="sketch_extrude",
                target_kind=SelectionKind.FACE,
                item_id=first_id,
                index=1,
                axis_name="Normal",
                axis=axis,
                item_ids=profile_item_ids,
                operation=sketch_operation,
            )
            self._viewer.clear_preview_marker()
            if sketch_operation == "new_body":
                self._set_context_hint(
                    "Drag arrow to create separate bodies, Enter accept, Esc cancel"
                )
                self._show_status("New bodies: drag arrow, Enter apply, Esc cancel")
            else:
                self._set_context_hint(
                    "Drag arrow to extrude selected profiles, Enter accept, Esc cancel"
                )
                self._show_status("Sketch profiles extrude: drag arrow")
            self._show_dimension_overlay(
                self._move_overlay_label(self._move_session),
                self.width() // 2,
                self.height() // 2,
            )
            self._update_extrude_affordance()
            self._refresh_hud()
            LOGGER.info(
                "Sketch multi-extrude tool started item_ids=%s",
                profile_item_ids,
            )
            return
        item_id, face_index = self._selected_face()
        if item_id is None or face_index is None:
            self._show_status("Select a face first")
            LOGGER.info("Extrude tool ignored because no face is selected")
            return
        is_profile = is_sketch_profile(self._scene.get(item_id).meta)
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
            self._set_context_hint("Drag arrow to extrude, Enter accept, Esc cancel")
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

    def _face_normal(
        self,
        item_id: str,
        face_index: int,
    ) -> tuple[float, float, float]:
        return face_normal_vector(self._scene.get(item_id).shape, face_index)

    def _move_active_object(self, distance: float) -> None:
        item_id = self._scene.active_item_id()
        if item_id is None:
            return
        dx, dy, dz = self._scaled_move_axis(distance)
        try:
            apply_move_object(self._scene, item_id, dx, dy, dz)
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
        self._scene.set_selection(None)
        self._hover_selection = None
        if self._viewer.is_initialized:
            self._viewer.display_scene(self._scene, fit=False)
        self._show_status(f"Object moved {self ._move_axis_name }")
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
            apply_move_face_normal(self._scene, item_id, face_index, distance)
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
        self._scene.set_selection(None)
        self._hover_selection = None
        if self._viewer.is_initialized:
            self._viewer.display_scene(self._scene, fit=False)
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
            apply_move_edge_controlled(self._scene, item_id, edge_index, dx, dy, dz)
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
        self._scene.set_selection(None)
        self._hover_selection = None
        if self._viewer.is_initialized:
            self._viewer.display_scene(self._scene, fit=False)
        self._show_status(f"Edge moved {self ._move_axis_name }")
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
                self._scene,
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
        self._scene.set_selection(None)
        self._hover_selection = None
        if self._viewer.is_initialized:
            self._viewer.display_scene(self._scene, fit=False)
        self._show_status(f"Vertex moved {self ._move_axis_name }")
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
        if hasattr(self, "_orientation_gizmo_overlay"):
            self._orientation_gizmo_overlay.set_axis_name(name)
        if self._move_session is not None and self._move_session.tool in {
            "rotate",
            "sketch_revolve",
        }:
            if self._move_session.tool == "sketch_revolve":
                self._update_active_revolve_axis(name)
            else:
                self._move_session.axis_name = name
                self._move_session.axis = axis
            self._update_move_preview()
            self._show_dimension_overlay(
                self._move_overlay_label(self._move_session),
                self.width() // 2,
                self.height() // 2,
            )
            tool_name = self._move_tool_name(self._move_session)
            self._show_status(f"{tool_name} axis: {name}")
        else:
            self._show_status(f"Move axis: {name }")
        self._refresh_hud()
        self._refresh_action_state()
        LOGGER.info("Move axis set to %s", name)
