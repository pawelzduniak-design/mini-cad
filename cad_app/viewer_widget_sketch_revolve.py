"""Sketch revolve tool behavior for ViewerWidget."""

from __future__ import annotations

import logging

from cad_app.commands import CommandError
from cad_app.feature_history import (
    capture_sketch_revolve_step,
    create_feature_history,
)
from cad_app.sketch import is_sketch_profile
from cad_app.sketch_features import revolve_profile
from cad_app.types import SelectionKind, SelectionRef
from cad_app.ui_sessions import MoveSession

LOGGER = logging.getLogger(__name__)


class ViewerWidgetSketchRevolveMixin:
    def _begin_sketch_revolve_tool(self) -> None:
        self._begin_sketch_revolve_tool_on_axis(self._move_axis_name)

    def _begin_sketch_revolve_tool_on_axis(self, axis_name: str) -> None:
        if not self._finish_sketch_for_modeling_command():
            return
        selection = self._scene.selection()
        if selection is None:
            self._show_status("Select a sketch profile first")
            return
        scene_object = self._scene.get(selection.item_id)
        if not is_sketch_profile(scene_object.meta):
            self._show_status("Select a sketch profile first")
            return
        axis_point, axis = self._sketch_revolve_axis(scene_object.meta, axis_name)
        self._move_axis_name = axis_name
        self._move_axis = axis
        if hasattr(self, "_orientation_gizmo_overlay"):
            self._orientation_gizmo_overlay.set_axis_name(axis_name)
        self._move_session = MoveSession(
            tool="sketch_revolve",
            target_kind=SelectionKind.FACE,
            item_id=selection.item_id,
            index=1,
            axis_name=axis_name,
            axis=axis,
            distance=360.0,
            axis_point=axis_point,
        )
        self._viewer.clear_preview_marker()
        self._update_move_preview()
        self._show_dimension_overlay(
            self._move_overlay_label(self._move_session),
            self.width() // 2,
            self.height() // 2,
        )
        self._set_context_hint(
            f"Revolve {axis_name}: drag to change angle, X/Y/Z changes axis, "
            "set Elevation for helix, Enter apply, Esc cancel"
        )
        self._show_status(f"Revolve sketch {axis_name}: 360 deg")
        self._refresh_hud()
        self._refresh_action_state()
        LOGGER.info(
            "Sketch revolve started item_id=%s axis=%s",
            selection.item_id,
            axis_name,
        )

    def _sketch_revolve_axis(
        self,
        meta: dict[str, object],
        axis_name: str,
    ) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        workplane = self._workplane_from_sketch_meta(meta)
        center_u = self._sketch_meta_float(meta, "center_u") or 0.0
        center_v = self._sketch_meta_float(meta, "center_v") or 0.0
        axis_u = center_u
        axis_v = center_v
        if axis_name == "X":
            height = self._sketch_meta_float(meta, "height")
            if height is not None:
                axis_v = center_v - height / 2.0
            axis = workplane.x_direction
        elif axis_name == "Y":
            width = self._sketch_meta_float(meta, "width")
            if width is not None:
                axis_u = center_u - width / 2.0
            axis = workplane.y_direction
        else:
            axis = workplane.normal
        axis_point = self._workplane_point(workplane, (axis_u, axis_v))
        return axis_point, (axis.X(), axis.Y(), axis.Z())

    def _update_active_revolve_axis(self, axis_name: str) -> None:
        session = self._move_session
        if session is None or session.tool != "sketch_revolve":
            return
        axis_point, axis = self._sketch_revolve_axis(
            self._scene.get(session.item_id).meta,
            axis_name,
        )
        session.axis_name = axis_name
        session.axis = axis
        session.axis_point = axis_point

    def _apply_sketch_revolve(
        self,
        item_id: str,
        angle_degrees: float,
        axis_point: tuple[float, float, float],
        axis: tuple[float, float, float],
        elevation: float = 0.0,
    ) -> None:
        from OCP.TopoDS import TopoDS

        scene_object = self._scene.get(item_id)
        if not is_sketch_profile(scene_object.meta):
            raise CommandError("Selected item is not a sketch profile.")
        result = revolve_profile(
            TopoDS.Face_s(scene_object.shape),
            axis_point,
            axis,
            angle_degrees,
            elevation,
        )
        profile_face = TopoDS.Face_s(scene_object.shape)
        body_id = self._scene.add_shape(
            result,
            meta=create_feature_history(
                {
                    "kind": "body",
                    "source": "sketch_revolve",
                    "angle_degrees": angle_degrees,
                    "elevation": elevation,
                    "axis": axis,
                    "axis_point": axis_point,
                },
                profile_face,
                capture_sketch_revolve_step(
                    angle_degrees,
                    elevation,
                    axis_point,
                    axis,
                ),
            ),
        )
        self._scene.set_active_item(body_id)
        self._scene.set_selection(
            SelectionRef(item_id=body_id, kind=SelectionKind.OBJECT, index=0)
        )
