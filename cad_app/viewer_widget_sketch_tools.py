"""Interactive sketch drawing tool handlers for ViewerWidget."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from cad_app.commands import CommandError
from cad_app.sketch import (
    SKETCH_ENTITY_META_KIND,
    is_closed_polyline,
    make_arc_polyline_profile,
    make_point_marker_preview,
    make_polyline_preview,
    make_polyline_profile,
    make_rectangle_profile_three_point,
    make_three_point_arc_edge,
    three_point_arc_radius,
)
from cad_app.sketch_graph import (
    arc_curve,
    curves_meta,
    polyline_segments,
    segments_meta,
    three_point_rectangle_segments,
)
from cad_app.ui_sessions import SketchSession

LOGGER = logging.getLogger(__name__)


@dataclass
class SketchTerminationAudit:
    """Records what happened to in-progress sketch geometry on session end.

    Every session-end path (Finish Sketch, Enter, tool switch, category
    switch, Cancel) must funnel through ``_drain_pending_sketch_geometry``
    so the policy is auditable. A populated ``committed_item_id`` means
    the pending geometry was preserved as a sketch_entity (open polyline
    construction reference). ``discarded=True`` means the caller asked
    for an intentional cancel.
    """

    reason: str
    tool: str
    pending_point_count: int
    committed_item_id: str | None = None
    discarded: bool = False

    def describe(self) -> str:
        if self.committed_item_id is not None:
            return (
                f"reason={self.reason} tool={self.tool} "
                f"points={self.pending_point_count} "
                f"committed_id={self.committed_item_id[:8]}"
            )
        return (
            f"reason={self.reason} tool={self.tool} "
            f"points={self.pending_point_count} discarded={self.discarded}"
        )


class ViewerWidgetSketchToolMixin:
    def _handle_sketch_click(
        self,
        session: SketchSession,
        uv: tuple[float, float],
        x: int,
        y: int,
    ) -> None:
        session.start_uv = None
        session.drag_start_screen = None
        session.drag_moved = False
        session.drag_end_uv = None
        if session.tool == "trim":
            self._trim_sketch_at(x, y)
            return
        if session.tool == "line":
            self._handle_line_click(session, uv, x, y)
            return
        if session.tool == "arc":
            self._handle_arc_click(session, uv, x, y)
            return
        if session.tool == "rectangle_3_point":
            self._handle_rectangle_three_point_click(session, uv, x, y)
            return
        if session.tool in {"center_rectangle", "circle", "circle_diameter"}:
            self._handle_two_point_profile_click(session, uv, x, y)
            return
        self._show_status(f"Unsupported sketch tool: {session .tool }")

    def _drain_pending_sketch_geometry(
        self,
        session: SketchSession,
        *,
        preserve: bool,
        reason: str,
    ) -> SketchTerminationAudit:
        """Single funnel for "what survives a session end" decisions.

        Centralises the rule: any pending open line chain (tool=="line"
        with >= 2 distinct points and not closed) is preserved as a
        construction sketch_entity when ``preserve`` is True. Other
        tools have no in-flight geometry to drain (arc commits per
        third click; circle / rectangle / trim never leave pending
        committable points). The returned audit lets callers log
        precisely what survived — useful when a beginner expected
        their lines to stay and they did not.
        """
        audit = SketchTerminationAudit(
            reason=reason,
            tool=session.tool,
            pending_point_count=len(session.points),
        )
        if not preserve:
            audit.discarded = bool(session.points)
            LOGGER.info("Sketch geometry drained: %s", audit.describe())
            return audit
        if session.tool == "line":
            item_id = self._commit_open_polyline_as_entity(session)
            if item_id is not None:
                audit.committed_item_id = item_id
        LOGGER.info("Sketch geometry drained: %s", audit.describe())
        return audit

    def _commit_open_polyline_as_entity(self, session: SketchSession) -> str | None:
        """Persist an in-progress open line chain as a sketch_entity so it
        survives Finish Sketch, tool switches, and clicks that miss snap
        targets.

        Beginners often draw construction lines as references for later
        Revolve axes, Mirror planes, or as snap targets. Discarding them
        whenever the polyline does not close itself made the tool feel
        unforgiving. We commit anything with at least two distinct points
        as an open polyline entity; the user can still delete it later
        from the browser.
        """
        if not session.points or len(session.points) < 2:
            return None
        if is_closed_polyline(session.points):
            return None
        try:
            preview = make_polyline_preview(session.workplane, session.points)
        except (CommandError, ValueError):
            return None
        segments = polyline_segments(session.points)
        if not segments:
            return None
        points_uv = [(float(u), float(v)) for u, v in session.points]
        item_id = self._add_sketch_entity(
            preview,
            {
                **self._sketch_profile_meta(
                    profile="line_segments",
                    segments=len(segments),
                    workplane=session.label,
                ),
                **segments_meta(segments),
                "points_uv": points_uv,
            },
        )
        LOGGER.info(
            "Open polyline kept as sketch entity item_id=%s segments=%d",
            item_id,
            len(segments),
        )
        return item_id

    def _handle_line_click(
        self,
        session: SketchSession,
        uv: tuple[float, float],
        x: int,
        y: int,
    ) -> None:
        uv = self._snapped_sketch_uv(session, uv)
        if not session.points:
            session.points.append(uv)
            self._remember_sketch_snap_point(session, uv)
            self._viewer.display_sketch_preview_marker(
                make_point_marker_preview(session.workplane, uv),
                self._workplane_normal_tuple(session.workplane),
            )
            self._show_dimension_overlay("Line start", x, y)
            self._set_context_hint("Line: click next point, Enter/Esc to finish")
            self._show_status("Line: next point")
            self._refresh_hud()
            return
        next_uv = self._closed_line_point(session, uv, x, y)
        if next_uv is None:
            next_uv = uv
        if math.dist(session.points[-1], next_uv) < 1e-7:
            return
        session.points.append(next_uv)
        self._remember_sketch_snap_point(session, next_uv)
        if self._try_commit_arc_line_profile(session):
            return
        if is_closed_polyline(session.points):
            self._commit_polyline_profile(session)
            return
        length = math.dist(session.points[-2], session.points[-1])
        self._viewer.display_sketch_preview_marker(
            make_polyline_preview(session.workplane, session.points),
            self._workplane_normal_tuple(session.workplane),
        )
        session.drag_dimensions = f"Length {length :.1f}"
        self._show_dimension_overlay(f"Length: {length :.2f} mm", x, y)
        self._set_context_hint("Line segment added - click next point or close loop")
        self._show_status("Line segment added")
        self._refresh_hud()

    def _closed_line_point(
        self,
        session: SketchSession,
        uv: tuple[float, float],
        x: int,
        y: int,
        uv_tolerance: float = 1.5,
        screen_tolerance_px: float = 14.0,
    ) -> tuple[float, float] | None:
        points = session.points
        if len(points) < 3:
            return None
        if math.dist(points[0], uv) <= uv_tolerance:
            return points[0]
        if not self._viewer.is_initialized:
            return None
        try:
            start_world = self._workplane_point(session.workplane, points[0])
            start_x, start_y = self._viewer.view.Convert(*start_world)
            scale = self.devicePixelRatioF() or 1.0
            start_widget = (float(start_x) / scale, float(start_y) / scale)
        except (RuntimeError, ValueError):
            LOGGER.debug("Line close screen snap failed", exc_info=True)
            return None
        if math.dist(start_widget, (float(x), float(y))) <= screen_tolerance_px:
            return points[0]
        return None

    @staticmethod
    def _snapped_sketch_uv(
        session: SketchSession,
        uv: tuple[float, float],
        tolerance: float = 1.5,
    ) -> tuple[float, float]:
        candidates = [*session.points, *session.snap_points]
        if not candidates:
            return uv
        closest = min(candidates, key=lambda point: math.dist(point, uv))
        if math.dist(closest, uv) <= tolerance:
            return closest
        return uv

    @staticmethod
    def _remember_sketch_snap_point(
        session: SketchSession,
        uv: tuple[float, float],
        tolerance: float = 1e-6,
    ) -> None:
        if any(
            math.dist(existing, uv) <= tolerance for existing in session.snap_points
        ):
            return
        session.snap_points.append(uv)

    @staticmethod
    def _uv_matches(
        first: tuple[float, float],
        second: tuple[float, float],
        tolerance: float = 1.5,
    ) -> bool:
        return math.dist(first, second) <= tolerance

    def _arc_meta_points(
        self,
        meta: dict[str, object],
    ) -> (
        tuple[
            tuple[float, float],
            tuple[float, float],
            tuple[float, float],
        ]
        | None
    ):
        start_u = self._sketch_meta_float(meta, "start_u")
        start_v = self._sketch_meta_float(meta, "start_v")
        end_u = self._sketch_meta_float(meta, "end_u")
        end_v = self._sketch_meta_float(meta, "end_v")
        bend_u = self._sketch_meta_float(meta, "bend_u")
        bend_v = self._sketch_meta_float(meta, "bend_v")
        if (
            start_u is None
            or start_v is None
            or end_u is None
            or end_v is None
            or bend_u is None
            or bend_v is None
        ):
            return None
        return (start_u, start_v), (end_u, end_v), (bend_u, bend_v)

    def _matching_arc_for_line_chain(
        self,
        session: SketchSession,
    ) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]] | None:
        if len(session.points) < 2:
            return None
        first = session.points[0]
        last = session.points[-1]
        for item in self._scene:
            if (
                item.meta.get("kind") != SKETCH_ENTITY_META_KIND
                or item.meta.get("profile") != "arc"
            ):
                continue
            arc_points = self._arc_meta_points(item.meta)
            if arc_points is None:
                continue
            arc_start, arc_end, arc_bend = arc_points
            if (
                self._uv_matches(first, arc_start) and self._uv_matches(last, arc_end)
            ) or (
                self._uv_matches(first, arc_end) and self._uv_matches(last, arc_start)
            ):
                return arc_start, arc_end, arc_bend
        return None

    def _try_commit_arc_line_profile(self, session: SketchSession) -> bool:
        arc_points = self._matching_arc_for_line_chain(session)
        if arc_points is None:
            return False
        arc_start, arc_end, arc_bend = arc_points
        try:
            profile = make_arc_polyline_profile(
                session.workplane,
                arc_start,
                arc_end,
                arc_bend,
                session.points,
            )
        except (CommandError, ValueError) as exc:
            LOGGER.warning("Arc-line profile failed: %s", exc, exc_info=True)
            self._show_status("Arc-line profile failed")
            return False
        graph_meta = {
            **segments_meta(polyline_segments(session.points)),
            **curves_meta((arc_curve(arc_start, arc_end, arc_bend),)),
        }
        item_id = self._add_sketch_profile(
            profile,
            {
                **self._sketch_profile_meta(
                    profile="arc_polyline",
                    segments=len(session.points) - 1,
                    workplane=session.label,
                ),
                **graph_meta,
            },
        )
        self._continue_sketch_after_profile(
            session,
            "Arc-line sketch profile created",
        )
        LOGGER.info("Arc-line sketch profile created item_id=%s", item_id)
        return True

    def _commit_polyline_profile(self, session: SketchSession) -> None:
        try:
            profile = make_polyline_profile(session.workplane, session.points)
        except (CommandError, ValueError) as exc:
            LOGGER.warning("Polyline profile failed: %s", exc, exc_info=True)
            # Self-intersecting / degenerate loops can't become a face,
            # but the work the user did should not vanish. Drop the
            # closing duplicate and keep what they drew as a
            # construction line_segments entity so it can be edited,
            # trimmed, or used as a reference instead of disappearing.
            open_points = (
                list(session.points[:-1])
                if (
                    len(session.points) >= 2 and session.points[0] == session.points[-1]
                )
                else list(session.points)
            )
            saved_points = list(session.points)
            session.points[:] = open_points
            self._commit_open_polyline_as_entity(session)
            session.points[:] = saved_points
            self._show_status("Polyline self-intersects: kept as construction line")
            self._set_context_hint(
                "Self-intersecting polyline cannot close into a face. "
                "Lines kept as a reference entity."
            )
            self._continue_sketch_after_profile(
                session,
                "Polyline kept as reference",
            )
            return
        item_id = self._add_sketch_profile(
            profile,
            {
                **self._sketch_profile_meta(
                    profile="line_polyline",
                    segments=len(session.points) - 1,
                    workplane=session.label,
                ),
                **segments_meta(polyline_segments(session.points)),
            },
        )
        self._continue_sketch_after_profile(
            session,
            "Closed sketch profile created",
        )
        LOGGER.info("Closed polyline profile created item_id=%s", item_id)

    def _handle_arc_click(
        self,
        session: SketchSession,
        uv: tuple[float, float],
        x: int,
        y: int,
    ) -> None:
        uv = self._snapped_sketch_uv(session, uv)
        session.points.append(uv)
        if len(session.points) < 3:
            self._remember_sketch_snap_point(session, uv)
            if len(session.points) == 1:
                preview_shape = make_point_marker_preview(session.workplane, uv)
            else:
                preview_shape = make_polyline_preview(
                    session.workplane,
                    session.points,
                )
            self._viewer.display_sketch_preview_marker(
                preview_shape,
                self._workplane_normal_tuple(session.workplane),
            )
            self._show_dimension_overlay(f"Arc point {len (session .points )}", x, y)
            self._set_context_hint("Arc: set the next arc point")
            self._show_status("Arc: set next point")
            self._refresh_hud()
            return
        try:
            edge = make_three_point_arc_edge(
                session.workplane,
                session.points[0],
                session.points[1],
                session.points[2],
            )
            radius = three_point_arc_radius(
                session.points[0],
                session.points[1],
                session.points[2],
            )
        except (CommandError, ValueError) as exc:
            LOGGER.warning("Arc failed: %s", exc, exc_info=True)
            session.points.clear()
            self._viewer.clear_preview_marker()
            self._hide_dimension_overlay()
            self._show_status("Arc failed")
            return
        item_id = self._add_sketch_entity(
            edge,
            self._sketch_profile_meta(
                profile="arc",
                radius=radius,
                start_u=session.points[0][0],
                start_v=session.points[0][1],
                end_u=session.points[1][0],
                end_v=session.points[1][1],
                bend_u=session.points[2][0],
                bend_v=session.points[2][1],
                workplane=session.label,
            ),
        )
        self._remember_sketch_snap_point(session, session.points[0])
        self._remember_sketch_snap_point(session, session.points[1])
        session.points.clear()
        # Drop the in-progress preview line/arc marker now that the
        # entity is committed — otherwise it lingers on top of the new
        # arc and the user sees the freshly-drawn shape "disappear"
        # under the stale preview until they click somewhere else.
        self._viewer.clear_preview_marker()
        session.drag_dimensions = f"Arc R {radius :.1f}"
        self._show_dimension_overlay(f"Arc R: {radius :.2f} mm", x, y)
        self._set_context_hint("Arc created - choose another sketch tool or continue")
        self._show_status("Arc created")
        self._refresh_hud()
        LOGGER.info("Sketch arc entity created item_id=%s", item_id)

    def _handle_rectangle_three_point_click(
        self,
        session: SketchSession,
        uv: tuple[float, float],
        x: int,
        y: int,
    ) -> None:
        session.points.append(uv)
        if len(session.points) < 3:
            self._show_dimension_overlay(
                f"Rectangle point {len (session .points )}",
                x,
                y,
            )
            self._set_context_hint("Rectangle 3 Point: set the next point")
            self._show_status("Rectangle 3 point: set next point")
            self._refresh_hud()
            return
        try:
            profile = make_rectangle_profile_three_point(
                session.workplane,
                session.points[0],
                session.points[1],
                session.points[2],
            )
        except (CommandError, ValueError) as exc:
            LOGGER.warning("3-point rectangle failed: %s", exc, exc_info=True)
            session.points.clear()
            self._viewer.clear_preview_marker()
            self._hide_dimension_overlay()
            self._show_status("Rectangle failed")
            return
        width = math.dist(session.points[0], session.points[1])
        signed_height = self._rectangle_three_point_height(
            session.points[0],
            session.points[1],
            session.points[2],
        )
        base_x = session.points[1][0] - session.points[0][0]
        base_y = session.points[1][1] - session.points[0][1]
        normal_x = -base_y / width
        normal_y = base_x / width
        center_uv = (
            (session.points[0][0] + session.points[1][0]) / 2.0
            + normal_x * signed_height / 2.0,
            (session.points[0][1] + session.points[1][1]) / 2.0
            + normal_y * signed_height / 2.0,
        )
        item_id = self._add_sketch_profile(
            profile,
            {
                **self._sketch_profile_meta(
                    profile="rectangle_3_point",
                    width=width,
                    height=abs(signed_height),
                    center_u=center_uv[0],
                    center_v=center_uv[1],
                    workplane=session.label,
                ),
                **segments_meta(
                    three_point_rectangle_segments(
                        session.points[0],
                        session.points[1],
                        session.points[2],
                    )
                ),
            },
        )
        self._continue_sketch_after_profile(
            session,
            "Rectangle sketch profile created",
        )
        LOGGER.info("3-point rectangle profile created item_id=%s", item_id)

    def _handle_two_point_profile_click(
        self,
        session: SketchSession,
        uv: tuple[float, float],
        x: int,
        y: int,
    ) -> None:
        if not session.points:
            session.points.append(uv)
            self._remember_sketch_snap_point(session, uv)
            self._show_dimension_overlay("Start point", x, y)
            self._set_context_hint("Move mouse to set size, then click to confirm")
            self._show_status(f"{session .tool }: set size")
            self._refresh_hud()
            return
        start_uv = session.points[0]
        try:
            profile = self._sketch_profile_from_uv(session, start_uv, uv)
        except (CommandError, ValueError) as exc:
            LOGGER.warning("Sketch profile failed: %s", exc, exc_info=True)
            session.points.clear()
            self._viewer.clear_preview_marker()
            self._hide_dimension_overlay()
            self._show_status("Sketch too small")
            return
        profile_meta = self._sketch_profile_meta(
            profile=self._sketch_profile_kind_for_tool(session.tool),
            workplane=session.label,
            **self._sketch_dimension_meta(session.tool, start_uv, uv),
            **self._sketch_segment_meta(session.tool, start_uv, uv),
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

    def _try_add_circle_cutout_to_host_profile(
        self,
        session: SketchSession,
        center_uv: tuple[float, float],
        radius_uv: tuple[float, float],
    ) -> bool:
        radius = math.dist(center_uv, radius_uv)
        try:
            profile = self._sketch_profile_from_uv(session, center_uv, radius_uv)
        except (CommandError, ValueError):
            return False
        profile_meta = self._sketch_profile_meta(
            profile="circle",
            workplane=session.label,
            radius=radius,
            center_u=center_uv[0],
            center_v=center_uv[1],
        )
        return self._try_regionize_profile_with_existing(
            session,
            profile,
            profile_meta,
        )
