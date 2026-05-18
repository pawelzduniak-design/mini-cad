"""Move drag tracking and preview behavior for ViewerWidget."""

from __future__ import annotations

import logging
import math

from PySide6.QtCore import Qt

from cad_app.commands import (
    CommandError,
    apply_chamfer_edge,
    apply_extrude_face,
    apply_fillet_edge,
    apply_move_edge_controlled,
    apply_move_face_controlled,
    apply_move_face_normal,
    apply_move_object,
    apply_move_vertex_controlled,
    apply_rotate_object,
)
from cad_app.types import SelectionKind
from cad_app.ui_sessions import (
    EXTRUDE_DRAG_FALLBACK_AXIS,
    EXTRUDE_DRAG_PROBE_DISTANCE,
    ROTATE_DRAG_FALLBACK_AXIS,
    MoveSession,
)
from cad_app.ui_sessions import drag_distance_delta as _drag_distance_delta
from cad_app.ui_sessions import normalize_screen_axis as _normalize_screen_axis
from cad_app.viewer_widget_move_preview import ViewerWidgetMovePreviewMixin

LOGGER = logging.getLogger(__name__)

DRAG_SNAP_STEP = 1.0

BROWSER_ITEM_ID_ROLE = Qt.UserRole
BROWSER_SELECTION_KIND_ROLE = Qt.UserRole + 1
BROWSER_SELECTION_INDEX_ROLE = Qt.UserRole + 2
BROWSER_COMMAND_ROLE = Qt.UserRole + 3


class ViewerWidgetMoveDragMixin(ViewerWidgetMovePreviewMixin):
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
            self._set_context_hint("Drag arrow to set height, Enter accept, Esc cancel")
            self._update_extrude_affordance()
            self._show_status("Extrude preview")
        elif self._move_session.tool == "rotate":
            self._show_status("Rotate preview")
        elif self._move_session.tool == "sketch_revolve":
            self._show_status("Revolve preview")
        elif self._move_session.tool in {"fillet", "chamfer", "fillet_chamfer"}:
            self._show_status(f"{self ._move_tool_name (self ._move_session )} preview")
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
                sum(component * component for component in self._move_session.vector)
            )
            if snap:
                snapped = tuple(
                    round(c / DRAG_SNAP_STEP) * DRAG_SNAP_STEP
                    for c in self._move_session.vector
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
        self._move_session.distance = self._move_session.drag_origin_distance + delta
        if self._move_session.tool in {"fillet", "chamfer"}:
            self._move_session.distance = max(0.0, self._move_session.distance)
        if snap:
            self._move_session.distance = (
                round(self._move_session.distance / DRAG_SNAP_STEP) * DRAG_SNAP_STEP
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
        ray = self._picker._view_ray(self._viewer.view, view_x, view_y)
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
        if session.tool in {"fillet", "chamfer", "fillet_chamfer"}:
            return EXTRUDE_DRAG_FALLBACK_AXIS
        if session.tool in {"rotate", "sketch_revolve"}:
            return ROTATE_DRAG_FALLBACK_AXIS
        if session.tool in {"move", "sketch_move"} and session.axis_name != "View":
            if not self._viewer.is_initialized:
                return None
            try:
                anchor = self._move_anchor_point(session)
                if anchor is None:
                    return None
                start_x, start_y = self._viewer.view.Convert(*anchor)
                endpoint = (
                    anchor[0] + session.axis[0] * EXTRUDE_DRAG_PROBE_DISTANCE,
                    anchor[1] + session.axis[1] * EXTRUDE_DRAG_PROBE_DISTANCE,
                    anchor[2] + session.axis[2] * EXTRUDE_DRAG_PROBE_DISTANCE,
                )
                end_x, end_y = self._viewer.view.Convert(*endpoint)
            except (CommandError, IndexError, RuntimeError, ValueError) as exc:
                LOGGER.debug(
                    "Move drag axis projection failed: %s",
                    exc,
                    exc_info=True,
                )
                return None
            return _normalize_screen_axis(end_x - start_x, end_y - start_y)
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
        distance = (
            self._sketch_extrude_session_distance(session)
            if session.tool == "sketch_extrude"
            else session.distance
        )
        sign = -1.0 if distance < 0 else 1.0
        direction = tuple(component * sign for component in session.axis)
        length = max(25.0, min(55.0, 35.0 + abs(distance) * 0.15))
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
            self._picker.subshape(item_id, SelectionKind.FACE, face_index)
        )
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        point = props.CentreOfMass()
        return point.X(), point.Y(), point.Z()

    def _move_anchor_point(
        self,
        session: MoveSession,
    ) -> tuple[float, float, float] | None:
        if session.target_kind == "sketch":
            item_ids = session.item_ids or (session.item_id,)
            if not item_ids:
                return None
            return self._shape_center(self._scene.get(item_ids[0]).shape)
        if session.target_kind == "object":
            return self._shape_center(self._scene.get(session.item_id).shape)
        if session.index is None:
            return None
        if session.target_kind == SelectionKind.FACE:
            return self._face_center(session.item_id, session.index)
        shape = self._picker.subshape(
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

    def _commit_move_session(self) -> None:
        session = self._move_session
        if session is None:
            return
        if abs(session.distance) < 1e-7:
            self._cancel_move_session(
                status=f"{self ._move_tool_name (session )} cancelled"
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
                status=f"{self ._move_tool_name (session )} failed"
            )
            return
        keep_move_active = self._keep_move_session_active_after_commit(session)
        if keep_move_active:
            self._reset_committed_move_session(session)
            self._move_session = session
        else:
            self._move_session = None
            # Same reasoning as _cancel_move_session: release the gizmo
            # axis highlight when there's no longer a Move/Rotate tool
            # owning it, so the red X arrow doesn't stay lit forever.
            if hasattr(self, "_orientation_gizmo_overlay"):
                self._orientation_gizmo_overlay.set_axis_name(None)
        self._hover_selection = None
        self._hide_edge_dimension_editor()
        self._viewer.clear_preview_marker()
        self._hide_dimension_overlay()
        self._viewer.clear_extrude_affordance_marker()
        if self._viewer.is_initialized:
            self._viewer.display_scene(self._scene, fit=False)
            if session.tool in {"sketch_extrude", "sketch_revolve"}:
                # Sketch-on-Face left the camera perpendicular to the
                # workplane via view_workplane(); restore the user's
                # original camera so the new body shows up exactly the
                # way they were looking before the sketch started. If
                # they did not enter a workplane (extrude from an
                # existing body face without a sketch reset), the call
                # is a no-op and their orbit/pan is preserved.
                self._navigation.restore_pre_sketch_view()
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
            self._set_context_hint(
                self._move_continue_hint(session)
                if keep_move_active
                else "Operation applied"
            )
        self._show_status(
            f"{self ._move_tool_name (session )} applied"
            if not keep_move_active
            else f"{self ._move_tool_name (session )} applied - drag again"
        )
        self._refresh_move_manipulator()
        self._refresh_hud()
        self._refresh_action_state()
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
    def _keep_move_session_active_after_commit(session: MoveSession) -> bool:
        return session.tool in {"move", "sketch_move"} and (
            session.target_kind == "object"
            or session.target_kind == SelectionKind.OBJECT
        )

    @staticmethod
    def _reset_committed_move_session(session: MoveSession) -> None:
        session.distance = 0.0
        session.drag_start = None
        session.drag_origin_distance = 0.0
        session.drag_screen_axis = None
        session.vector = None
        session.drag_origin_vector = (0.0, 0.0, 0.0)
        session.drag_view_anchor = None
        session.drag_view_normal = None
        session.drag_view_start_point = None

    @staticmethod
    def _move_continue_hint(session: MoveSession) -> str:
        if session.axis_name == "View":
            return "Move: drag in view again, Enter apply, Esc cancel"
        return f"Move {session.axis_name}: drag again, Enter apply, Esc cancel"

    @staticmethod
    def _move_tool_name(session: MoveSession) -> str:
        if session.tool == "sketch_extrude":
            if session.operation == "cut":
                return "Extrude Cut"
            if session.operation == "new_body":
                return "New Body"
            return "Extrude"
        if session.tool == "extrude":
            return "Extrude"
        if session.tool == "sketch_revolve":
            return "Sketch Revolve"
        if session.tool == "sketch_move":
            return "Move"
        if session.tool == "fillet_chamfer":
            if session.distance >= 0.0:
                return "Fillet"
            return "Chamfer"
        return session.tool.replace("_", " ").title()

    def _apply_move_session(self, session: MoveSession) -> None:
        if session.tool == "sketch_move":
            self._apply_sketch_move(
                session.item_ids or (session.item_id,),
                self._move_vector(session),
            )
            return
        if session.tool == "sketch_revolve":
            if session.axis_point is None:
                raise CommandError("Revolve axis unavailable.")
            self._apply_sketch_revolve(
                session.item_id,
                session.distance,
                session.axis_point,
                session.axis,
                session.elevation,
            )
            return
        if session.tool == "sketch_extrude":
            distance = self._sketch_extrude_session_distance(session)
            if len(session.item_ids) > 1:
                self._apply_multi_sketch_extrude(
                    session.item_ids,
                    distance,
                    new_body=session.operation == "new_body",
                )
                return
            self._apply_sketch_extrude(
                session.item_id,
                distance,
                new_body=session.operation == "new_body",
            )
            return
        if session.tool == "extrude":
            apply_extrude_face(
                self._scene,
                session.item_id,
                session.index,
                session.distance,
            )
            return
        if session.tool == "rotate":
            # Use the session's pivot if the caller set one (e.g. when a
            # vertex / edge / face was selected together with the body to
            # define a custom rotation centre). Otherwise fall back to the
            # body's bounding-box centre, the historical behaviour.
            center = session.axis_point or self._shape_center(
                self._scene.get(session.item_id).shape
            )
            if center is None:
                raise CommandError("Rotate center unavailable.")
            apply_rotate_object(
                self._scene,
                session.item_id,
                center,
                session.axis,
                session.distance,
            )
            return
        if session.tool == "fillet":
            apply_fillet_edge(
                self._scene,
                session.item_id,
                session.index,
                radius=session.distance,
            )
            return
        if session.tool == "chamfer":
            apply_chamfer_edge(
                self._scene,
                session.item_id,
                session.index,
                distance=session.distance,
            )
            return
        if session.tool == "fillet_chamfer":
            if session.distance > 0.0:
                apply_fillet_edge(
                    self._scene,
                    session.item_id,
                    session.index,
                    radius=session.distance,
                )
            else:
                apply_chamfer_edge(
                    self._scene,
                    session.item_id,
                    session.index,
                    distance=abs(session.distance),
                )
            return
        if session.target_kind == "object":
            dx, dy, dz = self._move_vector(session)
            item_ids = session.item_ids or (session.item_id,)
            with self._scene.transaction():
                for item_id in item_ids:
                    apply_move_object(self._scene, item_id, dx, dy, dz)
            return
        if session.target_kind == SelectionKind.FACE:
            if session.axis_name == "Normal":
                apply_move_face_normal(
                    self._scene,
                    session.item_id,
                    session.index,
                    session.distance,
                )
                return
            dx, dy, dz = self._face_move_vector(session)
            # Cylinder cap, sphere segment, or any planar face on a body
            # with curved neighbours rejects the vertex-rebuild path
            # (move_face_controlled assumes all faces planar). When the
            # user picks an X/Y/Z manipulator that happens to align with
            # that face's outward normal, the operation is just a push-
            # pull along the normal and extrude_face handles it cleanly.
            # Route through apply_move_face_normal with the signed
            # projection onto the normal as the push distance.
            normal_distance = self._face_move_along_normal_distance(session, dx, dy, dz)
            if normal_distance is not None:
                apply_move_face_normal(
                    self._scene,
                    session.item_id,
                    session.index,
                    normal_distance,
                )
                return
            apply_move_face_controlled(
                self._scene,
                session.item_id,
                session.index,
                dx,
                dy,
                dz,
            )
            return
        if session.target_kind == SelectionKind.EDGE:
            tdx, tdy, tdz = self._edge_move_vector(session)
            apply_move_edge_controlled(
                self._scene,
                session.item_id,
                session.index,
                tdx,
                tdy,
                tdz,
            )
            return
        if session.target_kind == SelectionKind.VERTEX:
            vdx, vdy, vdz = self._vertex_move_vector(session)
            apply_move_vertex_controlled(
                self._scene,
                session.item_id,
                session.index,
                vdx,
                vdy,
                vdz,
            )
            return
        raise ValueError(f"Unsupported move target: {session .target_kind }")

    def _cancel_move_session(self, status: str = "Move cancelled") -> None:
        if self._move_session is None:
            return
        self._move_session = None
        self._hide_edge_dimension_editor()
        self._viewer.clear_preview_marker()
        self._hide_dimension_overlay()
        self._viewer.clear_extrude_affordance_marker()
        # Clear the gizmo's "active axis" highlight; otherwise the
        # arrow stays bold after the tool ends and the user thinks
        # they're still in a per-axis Move/Rotate session.
        if hasattr(self, "_orientation_gizmo_overlay"):
            self._orientation_gizmo_overlay.set_axis_name(None)
        self._show_status(status)
        self._refresh_hud()

    def _cancel_active_tool(self) -> None:
        if self._sketch_session is not None:
            self._cancel_sketch_session()
            return
        self._cancel_move_session()
