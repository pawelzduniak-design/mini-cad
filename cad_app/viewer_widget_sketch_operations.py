"""Sketch creation and extrusion operations for ViewerWidget."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt

from cad_app.commands import (
    CommandError,
    translated_shape,
)
from cad_app.feature_history import (
    append_feature_step,
    capture_sketch_extrude_step,
    capture_sketch_feature_step,
    create_feature_history,
)
from cad_app.sketch import (
    SKETCH_ENTITY_META_KIND,
    SKETCH_META_KIND,
    apply_profile_feature,
    extrude_profile,
    is_sketch_object,
    is_sketch_profile,
    make_circle_profile,
    make_curve_compound_preview,
    make_curve_loop_profile,
    make_curve_preview,
    make_polyline_preview,
    make_polyline_profile,
    make_rectangle_profile,
)
from cad_app.sketch_graph import (
    SketchGraphSource,
    curve_specs_from_edges,
    curves_from_meta,
    graph_meta_from_edges,
    segments_from_meta,
    trim_segment_graph,
)
from cad_app.types import SelectionKind, SelectionRef
from cad_app.ui_sessions import (
    SketchSession,
)
from cad_app.viewer_widget_sketch_regions import ViewerWidgetSketchRegionMixin
from cad_app.viewer_widget_sketch_tools import ViewerWidgetSketchToolMixin
from cad_app.workplane import Workplane

LOGGER = logging.getLogger(__name__)

BROWSER_ITEM_ID_ROLE = Qt.UserRole
BROWSER_SELECTION_KIND_ROLE = Qt.UserRole + 1
BROWSER_SELECTION_INDEX_ROLE = Qt.UserRole + 2
BROWSER_COMMAND_ROLE = Qt.UserRole + 3


class ViewerWidgetSketchOperationsMixin(
    ViewerWidgetSketchToolMixin,
    ViewerWidgetSketchRegionMixin,
):
    def _edit_selected_sketch(self) -> None:
        if self._move_session is not None:
            self._show_status("Cancel active tool before editing sketch")
            return
        selection = self._scene.selection()
        if selection is None or selection.item_id not in self._scene:
            self._show_status("Select sketch geometry first")
            return
        scene_object = self._scene.get(selection.item_id)
        if not is_sketch_object(scene_object.meta):
            self._show_status("Select sketch geometry first")
            return

        workplane = self._workplane_from_sketch_meta(scene_object.meta)
        label = str(scene_object.meta.get("workplane") or "Sketch")
        tool = self._pending_sketch_tool
        sketch_id = self._sketch_id_from_meta(selection.item_id, scene_object.meta)
        profile_ids = self._sketch_profile_ids_for_sketch(workplane, sketch_id)
        if (
            is_sketch_profile(scene_object.meta)
            and selection.item_id not in profile_ids
        ):
            profile_ids.insert(0, selection.item_id)

        self._sketch_session = SketchSession(
            workplane=workplane,
            label=label,
            host=(selection.item_id, selection.index),
            tool=tool,
            profile_ids=profile_ids,
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
            self._viewer.display_selection_marker(scene_object.shape, scene_object.meta)
        self._hide_sketch_plane_chooser()
        self._set_sketch_tool(tool, clear_points=False)
        self._set_context_hint(
            "Editing Sketch: draw, trim, edit dimensions, or finish the sketch"
        )
        self._show_status("Editing Sketch")
        self._refresh_hud()
        self._refresh_action_state()
        LOGGER.info(
            "Sketch edit started item_id=%s profiles=%d",
            selection.item_id,
            len(profile_ids),
        )

    def _delete_selected_sketch(self) -> None:
        if self._move_session is not None or self._sketch_session is not None:
            self._show_status("Cancel active tool before deleting sketch")
            return
        item_ids = self._selected_sketch_object_item_ids()
        if not item_ids:
            self._show_status("Select sketch geometry first")
            return
        with self._scene.transaction():
            for item_id in item_ids:
                self._scene.remove(item_id)
        self._hover_selection = None
        self._selection_source = None
        if self._viewer.is_initialized:
            self._viewer.display_scene(self._scene, fit=False)
            self._viewer.clear_selection_marker()
            self._viewer.clear_dimension_label()
        self._hide_edge_dimension_editor()
        self._hide_dimension_overlay()
        if len(item_ids) == 1:
            self._show_status("Sketch deleted")
        else:
            self._show_status(f"Deleted {len(item_ids)} sketches")
        self._refresh_hud()
        self._refresh_action_state()
        LOGGER.info("Sketch deleted item_ids=%s", item_ids)

    def _selected_sketch_object_item_ids(self) -> tuple[str, ...]:
        refs = self._scene.selection_refs()
        if not refs:
            return ()
        sketch_refs = tuple(
            selection
            for selection in refs
            if selection.item_id in self._scene
            and is_sketch_object(self._scene.get(selection.item_id).meta)
        )
        if len(sketch_refs) != len(refs):
            return ()
        return tuple(selection.item_id for selection in sketch_refs)

    @staticmethod
    def _sketch_id_from_meta(item_id: str, meta: dict[str, object]) -> str:
        sketch_id = meta.get("sketch_id")
        if isinstance(sketch_id, str) and sketch_id:
            return sketch_id
        return item_id

    def _sketch_item_matches_sketch_id(
        self,
        item_id: str,
        meta: dict[str, object],
        sketch_id: str | None,
    ) -> bool:
        if sketch_id is None:
            return True
        meta_sketch_id = meta.get("sketch_id")
        if isinstance(meta_sketch_id, str) and meta_sketch_id:
            return meta_sketch_id == sketch_id
        return item_id == sketch_id

    def _sketch_item_matches_session(
        self,
        item_id: str,
        meta: dict[str, object],
        session: SketchSession,
    ) -> bool:
        return self._sketch_item_matches_sketch_id(item_id, meta, session.sketch_id)

    def _sketch_profile_ids_for_sketch(
        self,
        workplane: Workplane,
        sketch_id: str | None,
    ) -> list[str]:
        return [
            item.item_id
            for item in self._scene
            if is_sketch_profile(item.meta)
            and self._sketch_meta_matches_workplane(item.meta, workplane)
            and self._sketch_item_matches_sketch_id(item.item_id, item.meta, sketch_id)
        ]

    def _apply_sketch_move(self, item_ids: tuple[str, ...], vector) -> None:
        if not item_ids:
            raise CommandError("No sketch geometry selected.")
        dx, dy, dz = vector
        with self._scene.transaction():
            for item_id in item_ids:
                scene_object = self._scene.get(item_id)
                if not is_sketch_object(scene_object.meta):
                    raise CommandError("Selected item is not sketch geometry.")
                self._scene.replace_shape(
                    item_id,
                    translated_shape(scene_object.shape, dx, dy, dz),
                    meta=self._moved_sketch_meta(scene_object.meta, (dx, dy, dz)),
                )

    def _moved_sketch_meta(
        self,
        meta: dict[str, object],
        vector: tuple[float, float, float],
    ) -> dict[str, object]:
        workplane = self._workplane_from_sketch_meta(meta)
        x_dir = workplane.x_direction
        y_dir = workplane.y_direction
        normal = workplane.normal
        dx, dy, dz = vector
        du = dx * x_dir.X() + dy * x_dir.Y() + dz * x_dir.Z()
        dv = dx * y_dir.X() + dy * y_dir.Y() + dz * y_dir.Z()
        dn = dx * normal.X() + dy * normal.Y() + dz * normal.Z()
        origin = workplane.origin
        moved = dict(meta)

        for u_key, v_key in (
            ("center_u", "center_v"),
            ("start_u", "start_v"),
            ("end_u", "end_v"),
            ("bend_u", "bend_v"),
            ("inner_circle_center_u", "inner_circle_center_v"),
        ):
            if self._sketch_meta_float(moved, u_key) is not None:
                moved[u_key] = float(moved[u_key]) + du
            if self._sketch_meta_float(moved, v_key) is not None:
                moved[v_key] = float(moved[v_key]) + dv

        moved["segments_uv"] = self._translated_segments_uv(
            moved.get("segments_uv"),
            du,
            dv,
        )
        moved["curves_uv"] = self._translated_curves_uv(
            moved.get("curves_uv"),
            du,
            dv,
        )
        moved.update(
            {
                "display_normal": (normal.X(), normal.Y(), normal.Z()),
                "workplane_origin": (
                    origin.X() + normal.X() * dn,
                    origin.Y() + normal.Y() * dn,
                    origin.Z() + normal.Z() * dn,
                ),
                "workplane_x_direction": (x_dir.X(), x_dir.Y(), x_dir.Z()),
                "workplane_y_direction": (y_dir.X(), y_dir.Y(), y_dir.Z()),
            }
        )
        return moved

    @staticmethod
    def _translated_segments_uv(
        raw_segments: object,
        du: float,
        dv: float,
    ) -> tuple[tuple[tuple[float, float], tuple[float, float]], ...]:
        if not isinstance(raw_segments, (list, tuple)):
            return ()
        translated = []
        for raw_segment in raw_segments:
            if not isinstance(raw_segment, (list, tuple)) or len(raw_segment) != 2:
                continue
            start = ViewerWidgetSketchOperationsMixin._translated_uv_point(
                raw_segment[0],
                du,
                dv,
            )
            end = ViewerWidgetSketchOperationsMixin._translated_uv_point(
                raw_segment[1],
                du,
                dv,
            )
            if start is not None and end is not None:
                translated.append((start, end))
        return tuple(translated)

    @staticmethod
    def _translated_curves_uv(
        raw_curves: object,
        du: float,
        dv: float,
    ) -> tuple[dict[str, object], ...]:
        if not isinstance(raw_curves, (list, tuple)):
            return ()
        translated = []
        for raw_curve in raw_curves:
            if not isinstance(raw_curve, dict):
                continue
            curve = dict(raw_curve)
            for point_key in ("start", "end", "bend", "center"):
                point = ViewerWidgetSketchOperationsMixin._translated_uv_point(
                    curve.get(point_key),
                    du,
                    dv,
                )
                if point is not None:
                    curve[point_key] = point
            translated.append(curve)
        return tuple(translated)

    @staticmethod
    def _translated_uv_point(
        raw_point: object,
        du: float,
        dv: float,
    ) -> tuple[float, float] | None:
        if not isinstance(raw_point, (list, tuple)) or len(raw_point) != 2:
            return None
        try:
            return float(raw_point[0]) + du, float(raw_point[1]) + dv
        except (TypeError, ValueError):
            return None

    def _continue_sketch_after_profile(
        self,
        session: SketchSession,
        status: str,
    ) -> None:
        session.points.clear()
        session.start_uv = None
        session.drag_start_screen = None
        session.drag_moved = False
        session.drag_end_uv = None
        session.drag_dimensions = None
        self._sketch_session = session
        self._viewer.clear_preview_marker()
        self._hide_dimension_overlay()
        if self._viewer.is_initialized:
            self._viewer.display_sketch_plane_marker(session.workplane)
        self._show_selected_sketch_dimensions()
        self._set_context_hint(
            f"{status } - continue sketching, press Enter/Esc, "
            "or click Select to finish"
        )
        self._show_status(status)
        self._refresh_hud()

    def _cancel_sketch_session(self) -> None:
        self._finish_sketch_session(
            status="Sketch cancelled",
            context_hint="Sketch cancelled - Select mode",
            category="select",
            preserve_pending=False,
        )

    def _sketch_session_is_empty(self) -> bool:
        session = self._sketch_session
        if session is None:
            return True
        return not (
            session.profile_ids
            or session.points
            or session.start_uv is not None
            or session.drag_moved
            or session.drag_end_uv is not None
        )

    def _finish_sketch_session(
        self,
        *,
        status: str = "Sketch finished",
        context_hint: str = "Sketch finished - select a profile or model face",
        category: str = "select",
        preserve_pending: bool = True,
    ) -> None:
        if self._sketch_session is None:
            return
        # Drain pending in-progress geometry (typically an open line
        # chain). The user expects their lines to remain unless they
        # explicitly cancel — preserve_pending=False is reserved for
        # the Esc/Cancel path and intentional discards.
        self._drain_pending_sketch_geometry(
            self._sketch_session,
            preserve=preserve_pending,
            reason="finish_session",
        )
        self._sketch_session = None
        self._active_category = category
        self._selection_kind = SelectionKind.FACE
        self._viewer.clear_preview_marker()
        self._viewer.clear_sketch_plane_marker()
        self._hide_dimension_overlay()
        self._hide_sketch_plane_chooser()
        if self._viewer.is_initialized:
            self._viewer.show_sketch_geometry = True
            self._viewer.display_scene(self._scene, fit=False)
            self._viewer.set_selection_kind(SelectionKind.FACE)
            # Return to the camera the user had BEFORE the sketch was
            # opened (snapshotted by view_workplane). If they did not
            # enter a workplane, leave the camera alone — orbit/pan
            # they did during the sketch is respected.
            self._navigation.restore_pre_sketch_view()
        self._set_context_hint(context_hint)
        self._show_status(status)
        self._refresh_hud()
        self._refresh_action_state()
        LOGGER.info("Sketch session finished status=%s category=%s", status, category)

    def _finish_active_sketch(self) -> None:
        self._finish_sketch_session()

    def _finish_sketch_sequence(self) -> None:
        if self._sketch_session is None:
            return
        if self._sketch_session.points:
            self._drain_pending_sketch_geometry(
                self._sketch_session,
                preserve=True,
                reason="finish_sequence",
            )
            self._sketch_session.points.clear()
            self._sketch_session.start_uv = None
            self._sketch_session.drag_end_uv = None
            self._sketch_session.drag_dimensions = None
            self._viewer.clear_preview_marker()
            self._hide_dimension_overlay()
            self._show_status("Sketch sequence ended")
            self._refresh_hud()
            LOGGER.info("Sketch sequence ended")
            return
        self._finish_sketch_session()

    def _set_world_xy_workplane(self) -> None:
        self._active_workplane = Workplane.world_xy()
        self._active_workplane_label = "Bottom plane"
        self._active_workplane_host = None
        self._show_status("Sketch workplane: Bottom")
        LOGGER.info("Sketch workplane set to bottom plane")

    def _set_workplane_from_selected_face(self) -> None:
        item_id, face_index = self._selected_face()
        if item_id is None or face_index is None:
            self._show_status("Select a planar face first")
            LOGGER.info("Sketch workplane ignored because no face is selected")
            return
        try:
            from OCP.TopoDS import TopoDS

            face = TopoDS.Face_s(
                self._picker.subshape(item_id, SelectionKind.FACE, face_index)
            )
            self._active_workplane = Workplane.from_face(face)
        except (CommandError, IndexError, ValueError) as exc:
            LOGGER.warning(
                "Sketch workplane from face failed item_id=%s face=%s: %s",
                item_id,
                face_index,
                exc,
                exc_info=True,
            )
            self._show_status("Planar face required")
            return
        self._active_workplane_label = f"face {face_index }"
        if is_sketch_profile(self._scene.get(item_id).meta):
            self._active_workplane_host = None
        else:
            self._active_workplane_host = (item_id, face_index)
        self._show_status(f"Sketch workplane: face {face_index }")
        LOGGER.info(
            "Sketch workplane set from face item_id=%s face=%d",
            item_id,
            face_index,
        )

    def _add_rectangle_profile(self) -> None:
        try:
            profile = make_rectangle_profile(self._active_workplane)
        except (CommandError, ValueError) as exc:
            LOGGER.warning("Rectangle profile failed: %s", exc, exc_info=True)
            self._show_status("Rectangle profile failed")
            return
        item_id = self._add_sketch_profile(
            profile,
            self._sketch_profile_meta(
                profile="rectangle",
                width=60.0,
                height=40.0,
                center_u=0.0,
                center_v=0.0,
                workplane=self._active_workplane_label,
            ),
        )
        self._show_status("Rectangle sketch profile")
        LOGGER.info("Rectangle sketch profile added item_id=%s", item_id)

    def _add_circle_profile(self) -> None:
        try:
            profile = make_circle_profile(self._active_workplane)
        except (CommandError, ValueError) as exc:
            LOGGER.warning("Circle profile failed: %s", exc, exc_info=True)
            self._show_status("Circle profile failed")
            return
        item_id = self._add_sketch_profile(
            profile,
            self._sketch_profile_meta(
                profile="circle",
                radius=20.0,
                center_u=0.0,
                center_v=0.0,
                workplane=self._active_workplane_label,
            ),
        )
        self._show_status("Circle sketch profile")
        LOGGER.info("Circle sketch profile added item_id=%s", item_id)

    def _sketch_profile_meta(self, **meta: object) -> dict[str, object]:
        if self._sketch_session is not None and self._sketch_session.sketch_id:
            meta = {"sketch_id": self._sketch_session.sketch_id, **meta}
        meta = {
            "display_normal": self._workplane_normal_tuple(self._active_workplane),
            "definition_state": "under_defined",
            **self._workplane_frame_meta(self._active_workplane),
            **meta,
        }
        if self._active_workplane_host is None:
            return {**meta, "sketch_mode": "independent"}
        host_item_id, host_face_index = self._active_workplane_host
        return {
            **meta,
            "sketch_mode": "feature",
            "host_item_id": host_item_id,
            "host_face_index": host_face_index,
        }

    @staticmethod
    def _workplane_normal_tuple(
        workplane: Workplane,
    ) -> tuple[float, float, float]:
        normal = workplane.normal
        return normal.X(), normal.Y(), normal.Z()

    @staticmethod
    def _workplane_frame_meta(
        workplane: Workplane,
    ) -> dict[str, tuple[float, float, float]]:
        origin = workplane.origin
        x_direction = workplane.x_direction
        y_direction = workplane.y_direction
        return {
            "workplane_origin": (origin.X(), origin.Y(), origin.Z()),
            "workplane_x_direction": (
                x_direction.X(),
                x_direction.Y(),
                x_direction.Z(),
            ),
            "workplane_y_direction": (
                y_direction.X(),
                y_direction.Y(),
                y_direction.Z(),
            ),
        }

    def _add_sketch_profile(
        self,
        profile,
        meta: dict[str, object],
    ) -> str:
        profile_meta = {"kind": SKETCH_META_KIND, **meta}
        item_id = self._scene.add_shape(profile, meta=profile_meta)
        if self._sketch_session is not None:
            self._sketch_session.profile_ids.append(item_id)
        self._scene.set_active_item(item_id)
        self._scene.set_selection(
            SelectionRef(item_id=item_id, kind=SelectionKind.FACE, index=1)
        )
        self._selection_kind = SelectionKind.FACE
        self._hover_selection = None
        if self._viewer.is_initialized:
            self._viewer.set_selection_kind(SelectionKind.FACE)
            self._viewer.display_scene(self._scene, fit=False)
            self._viewer.display_selection_marker(profile, profile_meta)
            self._show_selected_sketch_dimensions()
        self._refresh_hud()
        return item_id

    def _add_sketch_entity(
        self,
        shape,
        meta: dict[str, object],
    ) -> str:
        item_id = self._scene.add_shape(
            shape,
            meta={"kind": SKETCH_ENTITY_META_KIND, **meta},
        )
        self._scene.set_active_item(item_id)
        self._scene.set_selection(None)
        self._hover_selection = None
        if self._viewer.is_initialized:
            self._viewer.display_scene(self._scene, fit=False)
            self._viewer.display_selection_marker(shape, self._scene.get(item_id).meta)
        self._refresh_hud()
        return item_id

    def _toggle_sketch_cut_mode(self) -> None:
        action = self._actions.get("sketch_cut_mode")
        checked = bool(action.isChecked()) if action is not None else False
        if checked and not self._selected_sketch_profile_has_host():
            if action is not None:
                action.setChecked(False)
            self._sketch_extrude_operation = "add"
            self._show_status("Cut requires a sketch on a body face")
            self._set_context_hint("Start a sketch from a selected body face first")
            self._refresh_action_state()
            return
        self._sketch_extrude_operation = "cut" if checked else "add"
        if checked:
            self._show_status("Extrude mode: Cut")
            self._set_context_hint("Extrude Sketch will subtract from the host body")
        else:
            self._show_status("Extrude mode: Add")
            self._set_context_hint("Extrude Sketch will add material")
        self._refresh_action_state()

    def _begin_sketch_extrude_tool(self) -> None:
        self._begin_sketch_profile_extrude_tool("auto")

    def _begin_sketch_new_body_tool(self) -> None:
        self._begin_sketch_profile_extrude_tool("new_body")

    def _begin_sketch_profile_extrude_tool(self, operation: str) -> None:
        if len(self._scene.selection_refs()) > 1:
            if operation == "cut":
                self._show_status("Cut supports one hosted sketch profile")
                return
            if not self._selected_sketch_profile_item_ids():
                self._show_status("Select sketch profiles first")
                return
            self._begin_extrude_tool(sketch_operation=operation)
            return
        selection = self._scene.selection()
        if selection is None:
            self._show_status("Select a sketch profile first")
            LOGGER.info("Sketch extrude ignored because nothing is selected")
            return
        if not is_sketch_profile(self._scene.get(selection.item_id).meta):
            self._show_status("Select a sketch profile first")
            LOGGER.info(
                "Sketch extrude ignored for non-sketch item_id=%s",
                selection.item_id,
            )
            return
        if operation == "cut" and not self._selected_sketch_profile_has_host():
            self._show_status("Cut requires a sketch on a body face")
            self._set_context_hint("Start a sketch from a selected body face first")
            return
        if selection.kind == SelectionKind.OBJECT:
            self._scene.set_selection(
                SelectionRef(
                    item_id=selection.item_id,
                    kind=SelectionKind.FACE,
                    index=1,
                )
            )
        self._begin_extrude_tool(sketch_operation=operation)

    def _finish_sketch_for_modeling_command(self) -> bool:
        if self._sketch_session is None:
            return True
        if (
            self._sketch_session.points
            or self._sketch_session.start_uv is not None
            or self._sketch_session.drag_start_screen is not None
        ):
            self._set_context_hint(
                "Finish the current sketch segment before starting a modeling tool"
            )
            self._show_status("Finish current sketch segment before extrude")
            return False
        if not self._selected_item_is_sketch_profile():
            self._set_context_hint(
                "Select a closed sketch profile before starting Extrude"
            )
            self._show_status("Select a closed sketch profile first")
            return False
        self._sketch_session = None
        self._active_category = "modify"
        self._viewer.clear_preview_marker()
        self._viewer.clear_sketch_plane_marker()
        self._hide_dimension_overlay()
        if self._viewer.is_initialized:
            self._viewer.show_sketch_geometry = True
            self._viewer.display_scene(self._scene, fit=False)
        self._refresh_hud()
        return True

    def _begin_sketch_trim_tool(self) -> None:
        self._set_sketch_tool("trim")
        self._scene.set_selection(None)
        self._hover_selection = None
        self._selection_source = None
        self._viewer.clear_selection_marker()
        self._viewer.clear_hover_marker()
        self._refresh_hud()

    def _trim_selected_sketch(self) -> bool:
        selection = self._scene.selection()
        if selection is None:
            self._show_status("Select sketch geometry to trim")
            return False
        return self._trim_sketch_item(selection.item_id)

    def _trim_sketch_at(self, x: int, y: int) -> bool:
        if not self._viewer.is_initialized:
            return False
        uv = self._screen_to_sketch_uv(x, y)
        if uv is not None and self._trim_segment_graph_at(
            uv,
            max_distance=self._sketch_trim_hit_tolerance(x, y),
        ):
            return True
        self._show_status("Trim: no segment hit")
        self._set_context_hint("Trim: click directly on a sketch segment")
        return False

    def _sketch_trim_hit_tolerance(self, x: int, y: int) -> float:
        uv = self._screen_to_sketch_uv(x, y)
        if uv is None:
            return 0.75
        samples = []
        sample_pixels = 8.0
        hit_pixels = 8.0
        for dx, dy in ((int(sample_pixels), 0), (0, int(sample_pixels))):
            sample = self._screen_to_sketch_uv(x + dx, y + dy)
            if sample is None:
                continue
            samples.append(((sample[0] - uv[0]) ** 2 + (sample[1] - uv[1]) ** 2) ** 0.5)
        if not samples:
            return 0.75
        screen_scaled_tolerance = max(samples) * (hit_pixels / sample_pixels)
        return max(0.75, min(6.0, screen_scaled_tolerance))

    def _trim_segment_graph_at(
        self,
        uv: tuple[float, float],
        *,
        max_distance: float = 5.0,
    ) -> bool:
        workplane = (
            self._sketch_session.workplane
            if self._sketch_session is not None
            else self._active_workplane
        )
        sources = self._sketch_graph_sources(workplane)
        if not sources:
            return False
        result = trim_segment_graph(sources, uv, max_distance=max_distance)
        if self._sketch_session is not None:
            fallback_sources = self._sketch_graph_sources(
                workplane,
                restrict_to_active_sketch=False,
            )
            if len(fallback_sources) > len(sources):
                fallback_result = trim_segment_graph(
                    fallback_sources,
                    uv,
                    max_distance=max_distance,
                )
                if fallback_result is not None and (
                    result is None
                    or (
                        not result.open_segments
                        and not result.loop_segments
                        and (
                            bool(fallback_result.open_segments)
                            or bool(fallback_result.loop_segments)
                        )
                    )
                ):
                    result = fallback_result
        if result is None:
            return False
        try:
            self._apply_sketch_graph_trim_result(result, workplane)
        except (CommandError, ValueError) as exc:
            LOGGER.warning("Segment graph trim failed: %s", exc, exc_info=True)
            self._show_status("Sketch trim failed")
            return False
        self._show_status("Sketch segment trimmed")
        self._set_context_hint("Trim: segment removed and sketch loops rebuilt")
        LOGGER.info(
            "Sketch segment trimmed sources=%d loops=%d open_segments=%d",
            len(result.source_item_ids),
            len(result.loops),
            len(result.open_segments),
        )
        return True

    def _sketch_graph_sources(
        self,
        workplane: Workplane,
        *,
        restrict_to_active_sketch: bool = True,
    ) -> tuple[SketchGraphSource, ...]:
        sources: list[SketchGraphSource] = []
        active_sketch_id = (
            self._sketch_session.sketch_id if self._sketch_session is not None else None
        )
        for item in self._scene:
            if not is_sketch_object(item.meta):
                continue
            if restrict_to_active_sketch and not self._sketch_item_matches_sketch_id(
                item.item_id,
                item.meta,
                active_sketch_id,
            ):
                continue
            segments = segments_from_meta(item.meta)
            curves = curves_from_meta(item.meta)
            if not segments and not curves:
                continue
            if not self._sketch_meta_matches_workplane(item.meta, workplane):
                continue
            sources.append(
                SketchGraphSource(
                    item_id=item.item_id,
                    segments=segments,
                    meta=dict(item.meta),
                    curves=curves,
                )
            )
        return tuple(sources)

    def _sketch_meta_matches_workplane(
        self,
        meta: dict[str, object],
        workplane: Workplane,
        tolerance: float = 1e-6,
    ) -> bool:
        candidate = self._workplane_from_sketch_meta(meta)

        def vector(direction) -> tuple[float, float, float]:
            return direction.X(), direction.Y(), direction.Z()

        def point(origin) -> tuple[float, float, float]:
            return origin.X(), origin.Y(), origin.Z()

        for first, second in (
            (point(candidate.origin), point(workplane.origin)),
            (vector(candidate.x_direction), vector(workplane.x_direction)),
            (vector(candidate.y_direction), vector(workplane.y_direction)),
        ):
            if any(abs(a - b) > tolerance for a, b in zip(first, second)):
                return False
        return True

    def _apply_sketch_graph_trim_result(
        self,
        result,
        workplane: Workplane,
    ) -> None:
        new_profile_ids: list[str] = []
        new_entity_ids: list[str] = []
        removed_item_ids: list[str] = []
        changed_item_ids: list[str] = []
        preserved_entity_id = self._preserved_trim_source_id(result)
        with self._scene.transaction():
            for item_id in result.source_item_ids:
                if item_id == preserved_entity_id:
                    continue
                if (
                    self._sketch_session is not None
                    and item_id in self._sketch_session.profile_ids
                ):
                    self._sketch_session.profile_ids.remove(item_id)
                if item_id in self._scene:
                    self._scene.remove(item_id)
                    removed_item_ids.append(item_id)

            if preserved_entity_id is not None:
                if (
                    self._sketch_session is not None
                    and preserved_entity_id in self._sketch_session.profile_ids
                ):
                    self._sketch_session.profile_ids.remove(preserved_entity_id)
                self._scene.replace_shape(
                    preserved_entity_id,
                    self._sketch_graph_open_segments_shape(
                        workplane,
                        result.open_segments,
                    ),
                    meta={
                        "kind": SKETCH_ENTITY_META_KIND,
                        **self._sketch_graph_meta(
                            workplane,
                            self._sketch_graph_open_segments_profile(
                                result.open_segments
                            ),
                            result.open_segments,
                        ),
                    },
                )
                new_entity_ids.append(preserved_entity_id)
                changed_item_ids.append(preserved_entity_id)

            for loop_edges in result.loop_segments:
                if all(edge.kind == "line" for edge in loop_edges):
                    points = [edge.start for edge in loop_edges]
                    profile = make_polyline_profile(workplane, [*points, points[0]])
                else:
                    profile = make_curve_loop_profile(
                        workplane,
                        curve_specs_from_edges(loop_edges),
                    )
                item_id = self._scene.add_shape(
                    profile,
                    meta={
                        "kind": SKETCH_META_KIND,
                        **self._sketch_graph_meta(
                            workplane,
                            "segment_loop",
                            loop_edges,
                        ),
                    },
                )
                new_profile_ids.append(item_id)
                changed_item_ids.append(item_id)
                if self._sketch_session is not None:
                    self._sketch_session.profile_ids.append(item_id)

            open_segments_to_add = (
                () if preserved_entity_id is not None else result.open_segments
            )
            for segment in open_segments_to_add:
                shape = (
                    make_polyline_preview(workplane, [segment.start, segment.end])
                    if segment.kind == "line"
                    else make_curve_preview(
                        workplane,
                        curve_specs_from_edges((segment,))[0],
                    )
                )
                item_id = self._scene.add_shape(
                    shape,
                    meta={
                        "kind": SKETCH_ENTITY_META_KIND,
                        **self._sketch_graph_meta(
                            workplane,
                            "line_segment" if segment.kind == "line" else "arc_segment",
                            (segment,),
                        ),
                    },
                )
                new_entity_ids.append(item_id)
                changed_item_ids.append(item_id)

            # Split crossing open entities into separate atomic-line
            # entities so each remaining arm of an intersection is
            # selectable on its own. To preserve identity (selection
            # tests rely on the entity's item_id surviving), keep the
            # first atomic on the original item_id and emit any extra
            # atomics as new entities.
            def _atomic_shape(atomic):
                if atomic.kind == "line":
                    return make_polyline_preview(workplane, [atomic.start, atomic.end])
                return make_curve_preview(
                    workplane, curve_specs_from_edges((atomic,))[0]
                )

            def _atomic_meta(atomic):
                return {
                    "kind": SKETCH_ENTITY_META_KIND,
                    **self._sketch_graph_meta(
                        workplane,
                        ("line_segment" if atomic.kind == "line" else "arc_segment"),
                        (atomic,),
                    ),
                }

            for crossing_id, atomics in result.crossing_split_sources:
                if crossing_id not in self._scene or not atomics:
                    continue
                first = atomics[0]
                self._scene.replace_shape(
                    crossing_id,
                    _atomic_shape(first),
                    meta=_atomic_meta(first),
                )
                changed_item_ids.append(crossing_id)
                for atomic in atomics[1:]:
                    item_id = self._scene.add_shape(
                        _atomic_shape(atomic), meta=_atomic_meta(atomic)
                    )
                    new_entity_ids.append(item_id)
                    changed_item_ids.append(item_id)

            if new_profile_ids:
                self._scene.set_active_item(new_profile_ids[0])
                self._scene.set_selection(
                    SelectionRef(
                        item_id=new_profile_ids[0],
                        kind=SelectionKind.FACE,
                        index=1,
                    )
                )
            elif new_entity_ids:
                self._scene.set_active_item(new_entity_ids[0])
                self._scene.set_selection(None)
            else:
                self._scene.set_selection(None)

        self._hover_selection = None
        self._selection_source = None
        self._viewer.clear_selection_marker(redraw=False)
        self._viewer.clear_hover_marker(redraw=False)
        self._viewer.clear_preview_marker(redraw=False)
        self._viewer.clear_dimension_label(redraw=False)
        if self._viewer.is_initialized:
            self._viewer.show_sketch_geometry = True
            self._selection_kind = SelectionKind.FACE
            self._viewer.set_selection_kind(SelectionKind.FACE, redraw=False)
            for item_id in removed_item_ids:
                self._viewer.erase_shape(item_id, redraw=False)
            for item_id in changed_item_ids:
                if item_id not in self._scene:
                    continue
                item = self._scene.get(item_id)
                self._viewer.display_shape(
                    item.item_id,
                    item.shape,
                    item.meta,
                    redraw=False,
                )
            selection = self._scene.selection()
            if selection is not None:
                selected = self._scene.get(selection.item_id)
                self._viewer.display_selection_marker(
                    selected.shape,
                    selected.meta,
                    redraw=False,
                )
            self._viewer.update_view()
        self._refresh_hud()

    def _preserved_trim_source_id(self, result) -> str | None:
        if result.loop_segments or not result.open_segments:
            return None
        if len(result.source_item_ids) != 1:
            return None
        source_id = result.source_item_ids[0]
        return source_id if source_id in self._scene else None

    def _sketch_graph_open_segments_shape(
        self,
        workplane: Workplane,
        edges,
    ):
        return make_curve_compound_preview(workplane, curve_specs_from_edges(edges))

    def _sketch_graph_open_segments_profile(self, edges) -> str:
        edges = tuple(edges)
        if len(edges) == 1:
            return "line_segment" if edges[0].kind == "line" else "arc_segment"
        return "segment_group"

    def _sketch_graph_meta(
        self,
        workplane: Workplane,
        profile: str,
        edges,
    ) -> dict[str, object]:
        meta: dict[str, object] = {
            "profile": profile,
            "workplane": self._active_workplane_label,
            "display_normal": self._workplane_normal_tuple(workplane),
            "definition_state": "under_defined",
            "dimensions_editable": False,
            **self._workplane_frame_meta(workplane),
            **graph_meta_from_edges(tuple(edges)),
        }
        # Carry the active session's sketch_id so subsequent trim
        # operations still recognise this item as part of the same
        # sketch (without this, _sketch_item_matches_sketch_id falls
        # back to comparing item_id with sketch_id and the item gets
        # filtered out, making the user's sketch "split into two").
        if self._sketch_session is not None and self._sketch_session.sketch_id:
            meta["sketch_id"] = self._sketch_session.sketch_id
        return meta

    def _trim_sketch_item(self, item_id: str) -> bool:
        if item_id not in self._scene:
            self._show_status("Trim: sketch geometry missing")
            return False
        scene_object = self._scene.get(item_id)
        if not is_sketch_object(scene_object.meta):
            self._show_status("Trim works only on sketch geometry")
            return False

        workplane = self._workplane_from_sketch_meta(scene_object.meta)
        sketch_id = self._sketch_id_from_meta(item_id, scene_object.meta)
        if self._sketch_session is None:
            self._sketch_session = SketchSession(
                workplane=workplane,
                label=str(scene_object.meta.get("workplane") or "Sketch"),
                host=(item_id, 1),
                tool="trim",
                profile_ids=self._sketch_profile_ids_for_sketch(
                    workplane,
                    sketch_id,
                ),
                sketch_id=sketch_id,
            )
            self._active_workplane = workplane
            self._active_workplane_label = self._sketch_session.label
            self._active_workplane_host = None
            self._active_category = "sketch"
            self._selection_kind = SelectionKind.FACE
        self._set_sketch_tool("trim")
        self._scene.set_selection(None)
        self._hover_selection = None
        self._selection_source = None
        self._viewer.clear_selection_marker()
        self._viewer.clear_hover_marker()
        self._viewer.clear_preview_marker()
        self._viewer.clear_dimension_label()
        if self._viewer.is_initialized:
            self._viewer.show_sketch_geometry = True
            self._viewer.display_scene(self._scene, fit=False)
            self._viewer.set_selection_kind(SelectionKind.FACE)
        self._set_context_hint("Trim: click directly on a sketch segment")
        self._show_status("Trim: click segment to remove")
        self._refresh_hud()
        LOGGER.info("Sketch trim armed from selected item_id=%s", item_id)
        return False

    def _block_modeling_command_during_sketch(self, command_name: str) -> bool:
        if self._sketch_session is None:
            return False
        self._set_context_hint(
            f"Finish the active sketch before starting {command_name }"
        )
        self._show_status(f"Finish sketch before {command_name }")
        return True

    def _apply_sketch_extrude(
        self,
        item_id: str,
        distance: float,
        *,
        new_body: bool = False,
    ):
        scene_object = self._scene.get(item_id)
        if not is_sketch_profile(scene_object.meta):
            raise CommandError("Selected item is not a sketch profile.")

        from OCP.TopoDS import TopoDS

        profile_face = TopoDS.Face_s(scene_object.shape)
        host_item_id = scene_object.meta.get("host_item_id")
        host_available = isinstance(host_item_id, str) and host_item_id in self._scene
        if host_available and not new_body:
            host_object = self._scene.get(host_item_id)
            step = capture_sketch_feature_step(profile_face, distance)
            result = apply_profile_feature(
                host_object.shape,
                profile_face,
                distance,
            )
            with self._scene.transaction():
                self._scene.replace_shape(
                    host_item_id,
                    result,
                    meta={
                        **append_feature_step(
                            host_object.meta,
                            host_object.shape,
                            step,
                        ),
                        "last_sketch_feature": scene_object.meta.get("profile"),
                    },
                )
                self._scene.remove(item_id)
                self._scene.set_active_item(host_item_id)
            return result

        result = extrude_profile(profile_face, distance)
        source = "sketch_new_body" if new_body else "sketch_extrude"
        meta = create_feature_history(
            {
                "kind": "body",
                "source": source,
                "distance": distance,
                "profile": scene_object.meta.get("profile"),
            },
            profile_face,
            capture_sketch_extrude_step(distance),
        )
        with self._scene.transaction():
            self._scene.replace_shape(
                item_id,
                result,
                meta=meta,
            )
            self._scene.set_active_item(item_id)
            self._scene.set_selection(
                SelectionRef(
                    item_id=item_id,
                    kind=SelectionKind.OBJECT,
                    index=0,
                )
            )
        # Selection now refers to an OBJECT body. If the widget is still
        # in FACE pick mode the user's first click on the new body will
        # demote selection back to a face and the Body context panel
        # (with Rotate Body) vanishes. Align the pick mode with the
        # actual selection kind so Move + Rotate stay reachable.
        self._selection_kind = SelectionKind.OBJECT
        if self._viewer.is_initialized:
            self._viewer.set_selection_kind(SelectionKind.OBJECT)
        self._active_category = "transform"
        if new_body and host_available:
            self._boolean_target_item_id = str(host_item_id)
        return result

    def _apply_multi_sketch_extrude(
        self,
        item_ids: tuple[str, ...],
        distance: float,
        *,
        new_body: bool = False,
    ):
        if not item_ids:
            raise CommandError("No sketch profiles selected.")
        results = []
        body_selections: list[SelectionRef] = []
        with self._scene.transaction():
            for item_id in item_ids:
                scene_object = self._scene.get(item_id)
                if not is_sketch_profile(scene_object.meta):
                    raise CommandError("Selected item is not a sketch profile.")

                from OCP.TopoDS import TopoDS

                profile_face = TopoDS.Face_s(scene_object.shape)
                host_item_id = scene_object.meta.get("host_item_id")
                host_available = (
                    isinstance(host_item_id, str) and host_item_id in self._scene
                )
                if host_available and not new_body:
                    # Hosted profile: fuse/cut into the host body and drop
                    # the profile, matching single-profile sketch extrude.
                    host_object = self._scene.get(host_item_id)
                    step = capture_sketch_feature_step(profile_face, distance)
                    result = apply_profile_feature(
                        host_object.shape,
                        profile_face,
                        distance,
                    )
                    self._scene.replace_shape(
                        host_item_id,
                        result,
                        meta={
                            **append_feature_step(
                                host_object.meta,
                                host_object.shape,
                                step,
                            ),
                            "last_sketch_feature": scene_object.meta.get("profile"),
                        },
                    )
                    self._scene.remove(item_id)
                    results.append(result)
                    body_selections.append(
                        SelectionRef(
                            item_id=host_item_id,
                            kind=SelectionKind.OBJECT,
                            index=0,
                        )
                    )
                    continue
                result = extrude_profile(profile_face, distance)
                source = "sketch_new_body" if new_body else "sketch_extrude"
                meta = create_feature_history(
                    {
                        "kind": "body",
                        "source": source,
                        "distance": distance,
                        "profile": scene_object.meta.get("profile"),
                    },
                    profile_face,
                    capture_sketch_extrude_step(distance),
                )
                self._scene.replace_shape(
                    item_id,
                    result,
                    meta=meta,
                )
                results.append(result)
                body_selections.append(
                    SelectionRef(
                        item_id=item_id,
                        kind=SelectionKind.OBJECT,
                        index=0,
                    )
                )
            # Pick whichever item from body_selections still survives in the
            # scene as the new active item (the first profile may have been
            # removed if it was hosted).
            if body_selections:
                active_id = body_selections[0].item_id
                if active_id in self._scene:
                    self._scene.set_active_item(active_id)
            self._scene.set_selections(tuple(body_selections))
        self._active_category = "transform"
        # Same reasoning as single-profile extrude: align pick mode with
        # the OBJECT selection so the user's next click does not demote
        # the body to a face and hide Rotate Body.
        if body_selections:
            self._selection_kind = SelectionKind.OBJECT
            if self._viewer.is_initialized:
                self._viewer.set_selection_kind(SelectionKind.OBJECT)
        return tuple(results)
