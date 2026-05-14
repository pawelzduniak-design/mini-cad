"""Sketch session and dimension editing behavior for ViewerWidget."""

from __future__ import annotations

import logging
import math
from uuid import uuid4

from PySide6.QtCore import Qt

from cad_app.commands import (
    CommandError,
)
from cad_app.sketch import (
    is_sketch_profile,
    make_center_rectangle_profile,
    make_circle_profile_at,
    make_polyline_preview,
    make_rectangle_profile_from_corners,
    make_rectangle_profile_three_point,
    make_three_point_arc_edge,
    project_screen_to_workplane,
    three_point_arc_radius,
)
from cad_app.sketch_graph import (
    center_rectangle_segments,
    corner_rectangle_segments,
    segments_meta,
)
from cad_app.types import SelectionKind
from cad_app.ui_sessions import (
    SketchSession,
)
from cad_app.ui_sessions import sketch_dimension_label as _sketch_dimension_label
from cad_app.viewer_widget_sketch_dimension_ui import (
    ViewerWidgetSketchDimensionUIMixin,
)
from cad_app.workplane import Workplane

LOGGER = logging.getLogger(__name__)

SKETCH_DRAG_SNAP_STEP = 1.0

BROWSER_ITEM_ID_ROLE = Qt.UserRole
BROWSER_SELECTION_KIND_ROLE = Qt.UserRole + 1
BROWSER_SELECTION_INDEX_ROLE = Qt.UserRole + 2
BROWSER_COMMAND_ROLE = Qt.UserRole + 3


class ViewerWidgetSketchDimensionsMixin(ViewerWidgetSketchDimensionUIMixin):
    def _start_sketch_on_selection(self) -> None:
        edit_target: tuple[str, int] | None = None
        feature_host: tuple[str, int] | None = None
        item_id, face_index = self._selected_face()
        if item_id is None or face_index is None:
            self._start_sketch_session(
                Workplane.world_xy(),
                "Bottom plane",
                None,
            )
            return
        try:
            from OCP.TopoDS import TopoDS

            selected_object = self._scene.get(item_id)
            face = TopoDS.Face_s(
                self._picker.subshape(item_id, SelectionKind.FACE, face_index)
            )
            workplane = Workplane.from_face(face)
            if self._selection_source == "browser" and is_sketch_profile(
                selected_object.meta
            ):
                edit_target = (item_id, face_index)
            elif not is_sketch_profile(selected_object.meta):
                feature_host = (item_id, face_index)
        except (CommandError, IndexError, ValueError) as exc:
            LOGGER.warning(
                "Sketch start failed item_id=%s face=%s: %s",
                item_id,
                face_index,
                exc,
                exc_info=True,
            )
            self._show_status("Planar face required")
            return
        self._start_sketch_session(
            workplane,
            f"new sketch on face plane {face_index }",
            edit_target,
        )
        self._active_workplane_host = feature_host

    def _start_new_sketch_on_selection(self) -> None:
        self._start_sketch_on_selection()

    def _start_sketch_session(
        self,
        workplane: Workplane,
        label: str,
        edit_target: tuple[str, int] | None,
    ) -> None:
        self._cancel_move_session(status="Move cancelled")
        tool = self._pending_sketch_tool
        sketch_id = None
        if edit_target is not None and edit_target[0] in self._scene:
            source_meta = self._scene.get(edit_target[0]).meta
            sketch_id = self._sketch_id_from_meta(edit_target[0], source_meta)
        if sketch_id is None:
            sketch_id = str(uuid4())
        self._sketch_session = SketchSession(
            workplane=workplane,
            label=label,
            host=edit_target,
            tool=tool,
            sketch_id=sketch_id,
        )
        self._active_workplane = workplane
        self._active_workplane_label = label
        self._active_workplane_host = None
        self._active_category = "sketch"
        self._selection_kind = SelectionKind.FACE
        self._hover_selection = None
        if self._viewer.is_initialized:
            self._viewer.show_sketch_geometry = True
            self._viewer.set_selection_kind(SelectionKind.FACE)
            self._navigation.view_workplane(workplane)
            self._viewer.display_scene(self._scene, fit=False)
            self._viewer.display_sketch_plane_marker(workplane)
        self._hide_sketch_plane_chooser()
        self._set_sketch_tool(tool, clear_points=False)
        if edit_target is None:
            self._set_context_hint(
                f"New Sketch - {tool.replace('_', ' ').title()}: draw on the "
                "active plane, then use New Body or Extrude Sketch"
            )
            self._show_status(f"New Sketch: {tool } tool")
        else:
            self._set_context_hint(
                f"Selected Sketch - {tool.replace('_', ' ').title()}: add geometry "
                "to selected sketch"
            )
            self._show_status(f"Selected Sketch: {tool } tool")
        self._refresh_hud()
        self._refresh_action_state()
        LOGGER.info("Sketch started workplane=%s edit_target=%s", label, edit_target)

    def _set_sketch_tool(self, tool: str, clear_points: bool = True) -> None:
        if tool not in {
            "line",
            "arc",
            "circle",
            "rectangle_3_point",
            "center_rectangle",
            "trim",
        }:
            raise ValueError(f"Unsupported sketch tool: {tool }")
        self._pending_sketch_tool = tool
        if self._sketch_session is None:
            self._set_pending_sketch_tool_action(tool)
            self._active_category = "sketch"
            self._set_context_hint(
                f"{tool.replace('_', ' ').title()}: click New Sketch first"
            )
            self._show_status("Start New Sketch before choosing draw tools")
            self._refresh_action_state()
            return
        self._sketch_session.tool = tool
        self._sketch_session.start_uv = None
        self._sketch_session.drag_start_screen = None
        self._sketch_session.drag_moved = False
        self._sketch_session.drag_end_uv = None
        if clear_points:
            self._sketch_session.points.clear()
            self._sketch_session.drag_dimensions = None
        self._viewer.clear_preview_marker()
        self._hide_dimension_overlay()
        self._set_context_hint(self._sketch_tool_hint(tool))
        self._show_status(f"Sketch: {tool } tool")
        self._set_pending_sketch_tool_action(tool)
        self._refresh_hud()
        LOGGER.info("Sketch tool set to %s", tool)

    def _set_pending_sketch_tool_action(self, tool: str) -> None:
        for action_name, action_tool in {
            "sketch_line_tool": "line",
            "sketch_arc_tool": "arc",
            "sketch_circle_tool": "circle",
            "sketch_rectangle3_tool": "rectangle_3_point",
            "sketch_center_rectangle_tool": "center_rectangle",
            "sketch_rectangle_tool": "center_rectangle",
            "sketch_trim": "trim",
        }.items():
            action = self._actions.get(action_name)
            if action is not None:
                action.setChecked(tool == action_tool)

    @staticmethod
    def _sketch_tool_hint(tool: str) -> str:
        hints = {
            "line": "Line: click points, Enter/Esc to finish",
            "arc": "Arc: click start, click end, click bend point",
            "circle": "Circle: click center, set radius, click to confirm",
            "rectangle_3_point": "Rectangle 3 Point: base points, then height",
            "center_rectangle": "Center Rectangle: click center, drag size",
            "trim": "Trim: click directly on a sketch segment",
        }
        return hints.get(tool, "Sketch: choose points in the viewport")

    def _begin_sketch_drag(self, x: int, y: int) -> None:
        if self._sketch_session is None or not self._viewer.is_initialized:
            return
        if self._sketch_session.tool == "trim":
            self._sketch_session.start_uv = None
            self._sketch_session.drag_start_screen = (x, y)
            self._sketch_session.drag_moved = False
            self._sketch_session.drag_end_uv = None
            self._sketch_session.drag_dimensions = None
            return
        uv = self._screen_to_sketch_uv(x, y)
        if uv is None:
            self._show_status("Sketch point unavailable")
            LOGGER.info("Sketch drag ignored because workplane projection failed")
            return
        self._sketch_session.start_uv = uv
        self._sketch_session.drag_start_screen = (x, y)
        self._sketch_session.drag_moved = False
        self._sketch_session.drag_end_uv = None
        self._sketch_session.drag_dimensions = None
        self._refresh_hud()
        LOGGER.debug(
            "Sketch drag started tool=%s uv=(%.3f,%.3f)",
            self._sketch_session.tool,
            uv[0],
            uv[1],
        )

    def _drag_sketch_to(self, x: int, y: int, snap: bool = False) -> None:
        if self._sketch_session is not None and self._sketch_session.tool == "trim":
            return
        if self._sketch_session is None or self._sketch_session.start_uv is None:
            return
        if self._sketch_session.drag_start_screen is not None:
            self._sketch_session.drag_moved = (
                math.dist(self._sketch_session.drag_start_screen, (x, y)) > 3.0
            )
        self._preview_sketch_to(x, y, snap=snap)

    def _preview_sketch_to(self, x: int, y: int, snap: bool = False) -> None:
        if self._sketch_session is None:
            return
        if self._sketch_session.tool == "trim":
            return
        uv = self._screen_to_sketch_uv(x, y, snap=snap)
        if uv is None:
            self._viewer.clear_preview_marker()
            self._hide_dimension_overlay()
            return
        self._sketch_session.drag_end_uv = uv
        try:
            preview = self._sketch_preview_shape(self._sketch_session, uv)
        except ValueError:
            self._viewer.clear_preview_marker()
            self._sketch_session.drag_end_uv = None
            self._sketch_session.drag_dimensions = None
            self._hide_dimension_overlay()
            self._refresh_hud()
            return
        if preview is None:
            return
        shape, hud_label, overlay_label = preview
        self._sketch_session.drag_dimensions = hud_label
        self._viewer.display_sketch_preview_marker(
            shape,
            self._workplane_normal_tuple(self._sketch_session.workplane),
        )
        self._show_dimension_overlay(overlay_label, x, y)
        self._refresh_hud()

    def _commit_sketch_drag(self, x: int, y: int, snap: bool = False) -> None:
        if self._sketch_session is None:
            return
        if self._sketch_session.tool == "trim":
            trim_x, trim_y = self._sketch_session.drag_start_screen or (x, y)
            self._trim_sketch_at(trim_x, trim_y)
            self._sketch_session.drag_start_screen = None
            self._sketch_session.drag_moved = False
            self._sketch_session.drag_end_uv = None
            self._sketch_session.drag_dimensions = None
            return
        if self._sketch_session.start_uv is None:
            return
        session = self._sketch_session
        uv = session.drag_end_uv
        if uv is None:
            uv = self._screen_to_sketch_uv(x, y, snap=snap)
        if uv is None:
            session.start_uv = None
            session.drag_end_uv = None
            session.drag_dimensions = None
            self._viewer.clear_preview_marker()
            self._hide_dimension_overlay()
            self._show_status("Sketch cancelled")
            return
        if not session.drag_moved:
            self._handle_sketch_click(session, uv, x, y)
            return
        try:
            profile = self._sketch_profile_from_uv(
                session,
                session.start_uv,
                uv,
            )
        except ValueError:
            session.start_uv = None
            session.drag_end_uv = None
            session.drag_dimensions = None
            self._viewer.clear_preview_marker()
            self._hide_dimension_overlay()
            self._show_status("Sketch too small")
            return
        profile_meta = self._sketch_profile_meta(
            profile=session.tool,
            workplane=session.label,
            **self._sketch_dimension_meta(
                session.tool,
                session.start_uv,
                uv,
            ),
            **self._sketch_segment_meta(session.tool, session.start_uv, uv),
        )
        if self._try_regionize_profile_with_existing(
            session,
            profile,
            profile_meta,
        ):
            return
        item_id = self._add_sketch_profile(
            profile,
            profile_meta,
        )
        self._continue_sketch_after_profile(session, "Sketch profile created")
        LOGGER.info(
            "Sketch profile created item_id=%s tool=%s",
            item_id,
            session.tool,
        )

    def _screen_to_sketch_uv(
        self, x: int, y: int, snap: bool = False
    ) -> tuple[float, float] | None:
        if self._sketch_session is None:
            return None
        view_x, view_y = self._to_view_pixels(x, y)
        uv = project_screen_to_workplane(
            self._viewer.view,
            view_x,
            view_y,
            self._sketch_session.workplane,
        )
        if uv is not None and snap:
            uv = self._dimension_snapped_sketch_uv(self._sketch_session, uv)
        return uv

    def _dimension_snapped_sketch_uv(
        self,
        session: SketchSession,
        uv: tuple[float, float],
    ) -> tuple[float, float]:
        if session.tool == "line" and session.points:
            return self._snap_radial_uv(session.points[-1], uv)
        if session.tool == "circle" and session.start_uv is not None:
            return self._snap_radial_uv(session.start_uv, uv)
        if session.tool in {"center_rectangle", "rectangle"}:
            if session.start_uv is None:
                return uv
            return self._snap_center_rectangle_uv(session.start_uv, uv)
        if session.tool == "rectangle_3_point":
            if len(session.points) == 1:
                return self._snap_radial_uv(session.points[0], uv)
            if len(session.points) >= 2:
                return self._snap_three_point_rectangle_height_uv(
                    session.points[0],
                    session.points[1],
                    uv,
                )
        return uv

    @staticmethod
    def _snap_scalar(value: float, step: float = SKETCH_DRAG_SNAP_STEP) -> float:
        return round(value / step) * step

    @classmethod
    def _snap_radial_uv(
        cls,
        anchor: tuple[float, float],
        uv: tuple[float, float],
    ) -> tuple[float, float]:
        delta_u = uv[0] - anchor[0]
        delta_v = uv[1] - anchor[1]
        length = math.hypot(delta_u, delta_v)
        if length < 1e-7:
            return uv
        snapped_length = cls._snap_scalar(length)
        return (
            anchor[0] + delta_u / length * snapped_length,
            anchor[1] + delta_v / length * snapped_length,
        )

    @classmethod
    def _snap_center_rectangle_uv(
        cls,
        center: tuple[float, float],
        uv: tuple[float, float],
    ) -> tuple[float, float]:
        delta_u = uv[0] - center[0]
        delta_v = uv[1] - center[1]
        width = cls._snap_scalar(abs(delta_u) * 2.0)
        height = cls._snap_scalar(abs(delta_v) * 2.0)
        sign_u = -1.0 if delta_u < 0 else 1.0
        sign_v = -1.0 if delta_v < 0 else 1.0
        return (
            center[0] + sign_u * width / 2.0,
            center[1] + sign_v * height / 2.0,
        )

    @classmethod
    def _snap_three_point_rectangle_height_uv(
        cls,
        first: tuple[float, float],
        second: tuple[float, float],
        uv: tuple[float, float],
    ) -> tuple[float, float]:
        base_u = second[0] - first[0]
        base_v = second[1] - first[1]
        base_length = math.hypot(base_u, base_v)
        if base_length < 1e-7:
            return uv
        axis_u = base_u / base_length
        axis_v = base_v / base_length
        normal_u = -axis_v
        normal_v = axis_u
        rel_u = uv[0] - first[0]
        rel_v = uv[1] - first[1]
        along = rel_u * axis_u + rel_v * axis_v
        height = rel_u * normal_u + rel_v * normal_v
        snapped_height = cls._snap_scalar(height)
        return (
            first[0] + axis_u * along + normal_u * snapped_height,
            first[1] + axis_v * along + normal_v * snapped_height,
        )

    def _sketch_profile_from_uv(
        self,
        session: SketchSession,
        start_uv: tuple[float, float],
        end_uv: tuple[float, float],
    ):
        if session.tool in {"rectangle", "center_rectangle"}:
            return make_center_rectangle_profile(
                session.workplane,
                start_uv,
                end_uv,
            )
        if session.tool == "rectangle_corners":
            return make_rectangle_profile_from_corners(
                session.workplane,
                start_uv,
                end_uv,
            )
        if session.tool == "circle":
            radius = (
                (end_uv[0] - start_uv[0]) ** 2 + (end_uv[1] - start_uv[1]) ** 2
            ) ** 0.5
            return make_circle_profile_at(session.workplane, start_uv, radius)
        raise ValueError(f"Unsupported sketch tool: {session .tool }")

    def _sketch_preview_shape(
        self,
        session: SketchSession,
        uv: tuple[float, float],
    ):
        if session.tool == "line":
            if not session.points:
                return None
            points = [*session.points, uv]
            length = math.dist(session.points[-1], uv)
            return (
                make_polyline_preview(session.workplane, points),
                f"Length {length :.1f}",
                f"Length: {length :.2f} mm",
            )
        if session.tool == "arc":
            if len(session.points) == 1:
                length = math.dist(session.points[0], uv)
                return (
                    make_polyline_preview(
                        session.workplane,
                        [session.points[0], uv],
                    ),
                    f"Arc base {length :.1f}",
                    f"Distance: {length :.2f} mm",
                )
            if len(session.points) == 2:
                radius = three_point_arc_radius(
                    session.points[0],
                    session.points[1],
                    uv,
                )
                return (
                    make_three_point_arc_edge(
                        session.workplane,
                        session.points[0],
                        session.points[1],
                        uv,
                    ),
                    f"Arc R {radius :.1f}",
                    f"Arc R: {radius :.2f} mm",
                )
            return None
        if session.tool == "rectangle_3_point":
            if len(session.points) == 1:
                length = math.dist(session.points[0], uv)
                return (
                    make_polyline_preview(
                        session.workplane,
                        [session.points[0], uv],
                    ),
                    f"Base {length :.1f}",
                    f"Distance: {length :.2f} mm",
                )
            if len(session.points) == 2:
                profile = make_rectangle_profile_three_point(
                    session.workplane,
                    session.points[0],
                    session.points[1],
                    uv,
                )
                width = math.dist(session.points[0], session.points[1])
                height = abs(
                    self._rectangle_three_point_height(
                        session.points[0],
                        session.points[1],
                        uv,
                    )
                )
                return (
                    profile,
                    f"{width :.1f} x {height :.1f}",
                    f"W: {width :.2f} mm, H: {height :.2f} mm",
                )
            return None
        if session.start_uv is None:
            return None
        profile = self._sketch_profile_from_uv(session, session.start_uv, uv)
        hud_label = _sketch_dimension_label(session.tool, session.start_uv, uv)
        return (
            profile,
            hud_label,
            self._sketch_overlay_label(session.tool, session.start_uv, uv),
        )

    @staticmethod
    def _sketch_segment_meta(
        tool: str,
        start_uv: tuple[float, float],
        end_uv: tuple[float, float],
    ) -> dict[str, object]:
        if tool in {"rectangle", "center_rectangle"}:
            width = abs(end_uv[0] - start_uv[0]) * 2.0
            height = abs(end_uv[1] - start_uv[1]) * 2.0
            return segments_meta(
                center_rectangle_segments(start_uv, width, height),
            )
        if tool == "rectangle_corners":
            return segments_meta(corner_rectangle_segments(start_uv, end_uv))
        return {}

    @staticmethod
    def _rectangle_three_point_height(
        first: tuple[float, float],
        second: tuple[float, float],
        third: tuple[float, float],
    ) -> float:
        base_x = second[0] - first[0]
        base_y = second[1] - first[1]
        base_length = math.hypot(base_x, base_y)
        if base_length < 1e-7:
            return 0.0
        normal_x = -base_y / base_length
        normal_y = base_x / base_length
        return (third[0] - first[0]) * normal_x + (third[1] - first[1]) * normal_y
