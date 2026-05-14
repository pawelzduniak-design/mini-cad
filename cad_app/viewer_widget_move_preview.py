"""Move preview shape and vector helpers for ViewerWidget."""

from __future__ import annotations

import logging

from cad_app.commands import (
    CommandError,
    chamfer_edge,
    extrude_face,
    fillet_edge,
    move_edge_controlled,
    move_face_controlled,
    move_vertex_controlled,
    rotated_shape,
    translated_shape,
)
from cad_app.sketch import extrude_profile
from cad_app.sketch_features import revolve_profile
from cad_app.types import SelectionKind
from cad_app.ui_sessions import MoveSession
from cad_app.ui_sessions import axis_vector as _axis_vector

LOGGER = logging.getLogger(__name__)


class ViewerWidgetMovePreviewMixin:
    def _update_move_preview(self) -> None:
        if self._move_session is None:
            return
        distance = self._move_session.distance
        if abs(distance) < 1e-7:
            self._viewer.clear_preview_marker()
            return
        try:
            preview = self._move_preview_shape(self._move_session)
        except (CommandError, IndexError, ValueError) as exc:
            LOGGER.debug("Move preview failed: %s", exc, exc_info=True)
            self._viewer.clear_preview_marker()
            return
        hide_original = self._move_session.tool in {
            "extrude",
            "sketch_extrude",
            "fillet",
            "chamfer",
            "rotate",
            "sketch_revolve",
            "sketch_move",
        } or (
            self._move_session.tool == "move"
            and self._move_session.target_kind == "object"
        )
        LOGGER.debug(
            "Move preview: tool=%s target=%s hide_original=%s "
            "item_id=%s distance=%.2f",
            self._move_session.tool,
            self._move_session.target_kind,
            hide_original,
            self._move_session.item_id,
            self._move_session.distance,
        )
        self._viewer.display_preview_marker(
            preview,
            hide_item_id=(
                self._move_session.item_id
                if hide_original and not self._move_session.item_ids
                else None
            ),
            hide_item_ids=(self._move_session.item_ids if hide_original else ()),
        )

    @staticmethod
    def _move_overlay_label(session: MoveSession) -> str:
        if session.tool == "sketch_extrude" and session.operation == "cut":
            return f"Push/Pull Cut {abs(session .distance) :.2f} mm"
        if session.tool == "sketch_extrude" and session.operation == "new_body":
            return f"New Body {session .distance :.2f} mm"
        if session.tool in {"extrude", "sketch_extrude"}:
            return f"Push/Pull {session .distance :.2f} mm"
        if session.tool == "rotate":
            return f"Rotate {session .axis_name }: {session .distance :.2f} deg"
        if session.tool == "sketch_revolve":
            if abs(session.elevation) > 1e-7:
                return (
                    f"Revolve {session .axis_name }: {session .distance :.2f} deg, "
                    f"Elev {session .elevation :.2f} mm"
                )
            return f"Revolve {session .axis_name }: {session .distance :.2f} deg"
        if session.tool == "fillet":
            return f"Fillet R {session .distance :.2f} mm"
        if session.tool == "chamfer":
            return f"Chamfer {session .distance :.2f} mm"
        if session.axis_name == "View":
            return f"Move {session .distance :.2f} mm"
        if session.axis_name in {"X", "Y", "Z"}:
            return f"d{session .axis_name }: {session .distance :.2f} mm"
        return f"Distance: {session .distance :.2f} mm"

    def _move_preview_shape(self, session: MoveSession):
        if session.tool == "sketch_extrude":
            from OCP.TopoDS import TopoDS

            profile_item_ids = session.item_ids or (session.item_id,)
            distance = self._sketch_extrude_session_distance(session)
            if len(profile_item_ids) == 1:
                return extrude_profile(
                    TopoDS.Face_s(self._scene.get(profile_item_ids[0]).shape),
                    distance,
                )
            return self._compound_shapes(
                [
                    extrude_profile(
                        TopoDS.Face_s(self._scene.get(item_id).shape),
                        distance,
                    )
                    for item_id in profile_item_ids
                ]
            )
        if session.tool == "sketch_revolve":
            from OCP.TopoDS import TopoDS

            if session.axis_point is None:
                raise CommandError("Revolve axis unavailable.")
            return revolve_profile(
                TopoDS.Face_s(self._scene.get(session.item_id).shape),
                session.axis_point,
                session.axis,
                session.distance,
                session.elevation,
            )
        if session.tool == "sketch_move":
            dx, dy, dz = self._move_vector(session)
            item_ids = session.item_ids or (session.item_id,)
            if len(item_ids) > 1:
                return self._compound_shapes(
                    [
                        translated_shape(
                            self._scene.get(item_id).shape,
                            dx,
                            dy,
                            dz,
                        )
                        for item_id in item_ids
                    ]
                )
            return translated_shape(self._scene.get(item_ids[0]).shape, dx, dy, dz)
        if session.tool == "extrude":
            return extrude_face(
                self._scene.get(session.item_id).shape,
                session.index,
                session.distance,
            )
        if session.tool == "rotate":
            center = self._shape_center(self._scene.get(session.item_id).shape)
            if center is None:
                raise CommandError("Rotate center unavailable.")
            return rotated_shape(
                self._scene.get(session.item_id).shape,
                center,
                session.axis,
                session.distance,
            )
        if session.tool == "fillet":
            return fillet_edge(
                self._scene.get(session.item_id).shape,
                session.index,
                session.distance,
            )
        if session.tool == "chamfer":
            return chamfer_edge(
                self._scene.get(session.item_id).shape,
                session.index,
                session.distance,
            )
        if session.target_kind == SelectionKind.EDGE:
            dx, dy, dz = self._edge_move_vector(session)
            return move_edge_controlled(
                self._scene.get(session.item_id).shape,
                session.index,
                dx,
                dy,
                dz,
            )
        if session.target_kind == SelectionKind.VERTEX:
            dx, dy, dz = self._vertex_move_vector(session)
            return move_vertex_controlled(
                self._scene.get(session.item_id).shape,
                session.index,
                dx,
                dy,
                dz,
            )
        if session.target_kind == SelectionKind.FACE:
            dx, dy, dz = self._face_move_vector(session)
            return move_face_controlled(
                self._scene.get(session.item_id).shape,
                session.index,
                dx,
                dy,
                dz,
            )
        dx, dy, dz = self._move_vector(session)
        if session.target_kind == "object":
            item_ids = session.item_ids or (session.item_id,)
            if len(item_ids) > 1:
                return self._compound_shapes(
                    [
                        translated_shape(
                            self._scene.get(item_id).shape,
                            dx,
                            dy,
                            dz,
                        )
                        for item_id in item_ids
                    ]
                )
            shape = self._scene.get(item_ids[0]).shape
        else:
            shape = self._picker.subshape(
                session.item_id,
                SelectionKind(session.target_kind),
                session.index,
            )
        return translated_shape(shape, dx, dy, dz)

    @staticmethod
    def _sketch_extrude_session_distance(session: MoveSession) -> float:
        if session.operation == "cut":
            return -abs(session.distance)
        if session.operation in {"auto", "join"} and session.distance < 0:
            return abs(session.distance)
        return session.distance

    @staticmethod
    def _compound_shapes(shapes):
        from OCP.BRep import BRep_Builder
        from OCP.TopoDS import TopoDS_Compound

        builder = BRep_Builder()
        compound = TopoDS_Compound()
        builder.MakeCompound(compound)
        for shape in shapes:
            builder.Add(compound, shape)
        return compound

    def _move_vector(self, session: MoveSession) -> tuple[float, float, float]:
        if session.vector is not None:
            return session.vector
        return (
            session.axis[0] * session.distance,
            session.axis[1] * session.distance,
            session.axis[2] * session.distance,
        )

    def _edge_move_vector(
        self,
        session: MoveSession,
    ) -> tuple[float, float, float]:
        return self._axis_move_vector(
            session,
            lambda dx, dy, dz: move_edge_controlled(
                self._scene.get(session.item_id).shape,
                session.index,
                dx,
                dy,
                dz,
            ),
        )

    def _face_move_vector(
        self,
        session: MoveSession,
    ) -> tuple[float, float, float]:
        return self._axis_move_vector(
            session,
            lambda dx, dy, dz: move_face_controlled(
                self._scene.get(session.item_id).shape,
                session.index,
                dx,
                dy,
                dz,
            ),
        )

    def _vertex_move_vector(
        self,
        session: MoveSession,
    ) -> tuple[float, float, float]:
        return self._axis_move_vector(
            session,
            lambda dx, dy, dz: move_vertex_controlled(
                self._scene.get(session.item_id).shape,
                session.index,
                dx,
                dy,
                dz,
            ),
        )

    def _axis_move_vector(
        self,
        session: MoveSession,
        validator,
    ) -> tuple[float, float, float]:
        dx, dy, dz = self._move_vector(session)
        if session.axis_name != "View":
            return dx, dy, dz

        components = (dx, dy, dz)
        candidates = [
            vector
            for _length, vector in sorted(
                [
                    (abs(component), _axis_vector(axis_index, component))
                    for axis_index, component in enumerate(components)
                ],
                reverse=True,
            )
            if _length > 1e-7
        ]
        fallback_length = max((abs(component) for component in components), default=0.0)
        if fallback_length <= 1e-7:
            fallback_length = abs(session.distance)
        if fallback_length > 1e-7:
            candidates.extend(
                candidate
                for axis_index in range(3)
                for candidate in (
                    _axis_vector(axis_index, fallback_length),
                    _axis_vector(axis_index, -fallback_length),
                )
            )

        seen: set[tuple[float, float, float]] = set()
        for candidate in candidates:
            key = tuple(round(component, 9) for component in candidate)
            if key in seen:
                continue
            seen.add(key)
            try:
                validator(*candidate)
            except (CommandError, IndexError, ValueError):
                continue
            return candidate
        if candidates:
            return candidates[0]
        return dx, dy, dz
