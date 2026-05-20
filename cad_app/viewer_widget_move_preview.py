"""Move preview shape and vector helpers for ViewerWidget."""

from __future__ import annotations

import logging
import math

from cad_app.commands import (
    CommandError,
    chamfer_edge,
    extrude_face,
    face_normal_vector,
    fillet_edge,
    is_oblique_shear_body,
    move_edge_controlled,
    move_face_controlled,
    move_face_oblique_shear,
    move_vertex_controlled,
    rotated_shape,
    supports_move_face_oblique_shear,
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
            self._note_move_preview_failed(self._move_session, distance)
            return
        # Preview succeeded - remember this radius / distance as the
        # latest known-good value so commit-time can suggest it.
        self._move_session.last_successful_preview_distance = float(distance)
        if self._move_session.last_preview_failed:
            self._move_session.last_preview_failed = False
            if self._move_session.tool in {"fillet", "chamfer", "fillet_chamfer"}:
                self._show_status(
                    f"Fillet/Chamfer feasible again at {abs(distance):.2f} mm"
                )
        hide_original = self._move_session.tool in {
            "extrude",
            "sketch_extrude",
            "fillet",
            "chamfer",
            "fillet_chamfer",
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

    def _note_move_preview_failed(self, session: MoveSession, distance: float) -> None:
        """When fillet/chamfer preview silently fails the user sees the
        original body and doesn't know they're past the feasible
        radius. Surface a one-time status warning so the drag has
        real-time feedback instead of going dark."""
        if session.tool not in {"fillet", "chamfer", "fillet_chamfer"}:
            return
        if session.last_preview_failed:
            return
        session.last_preview_failed = True
        last_ok = session.last_successful_preview_distance
        if last_ok is not None:
            self._show_status(
                f"Fillet/Chamfer R={abs(distance):.2f} mm exceeds max for "
                f"this edge (last working: {abs(last_ok):.2f} mm)"
            )
        else:
            self._show_status(
                f"Fillet/Chamfer R={abs(distance):.2f} mm too large for "
                "this edge — try smaller"
            )

    @staticmethod
    def _move_overlay_label(session: MoveSession) -> str:
        if session.tool == "sketch_extrude" and session.operation == "cut":
            return f"Extrude Cut {abs(session .distance) :.2f} mm"
        if session.tool == "sketch_extrude" and session.operation == "new_body":
            return f"New Body {session .distance :.2f} mm"
        if session.tool in {"extrude", "sketch_extrude"}:
            return f"Extrude {session .distance :.2f} mm"
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
        if session.tool == "fillet_chamfer":
            if session.distance >= 0.0:
                return f"Fillet R {session .distance :.2f} mm"
            return f"Chamfer {abs(session .distance) :.2f} mm"
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
        if session.tool == "fillet_chamfer":
            if session.distance >= 0.0:
                return fillet_edge(
                    self._scene.get(session.item_id).shape,
                    session.index,
                    session.distance,
                )
            return chamfer_edge(
                self._scene.get(session.item_id).shape,
                session.index,
                abs(session.distance),
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
            shape = self._scene.get(session.item_id).shape
            face_index = session.index
            already_oblique = is_oblique_shear_body(shape, face_index)
            if session.axis_name == "Normal":
                if already_oblique:
                    nx, ny, nz = face_normal_vector(shape, face_index)
                    return move_face_oblique_shear(
                        shape,
                        face_index,
                        nx * session.distance,
                        ny * session.distance,
                        nz * session.distance,
                    )
                from cad_app.commands import move_face_normal

                return move_face_normal(
                    shape,
                    face_index,
                    session.distance,
                )
            dx, dy, dz = self._face_move_vector(session)
            # Mirror the apply-time routing: when the move vector lines
            # up with the planar face's normal, do a push-pull so the
            # preview also works on curved-body shells where
            # move_face_controlled would fail (cylinder/torus caps).
            normal_distance = self._face_move_along_normal_distance(session, dx, dy, dz)
            if normal_distance is not None and not already_oblique:
                from cad_app.commands import move_face_normal

                return move_face_normal(
                    shape,
                    face_index,
                    normal_distance,
                )
            if supports_move_face_oblique_shear(shape, face_index):
                return move_face_oblique_shear(
                    shape,
                    face_index,
                    dx,
                    dy,
                    dz,
                )
            return move_face_controlled(
                shape,
                face_index,
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

    def _face_move_along_normal_distance(
        self,
        session: MoveSession,
        dx: float,
        dy: float,
        dz: float,
    ) -> float | None:
        """Return the signed push-pull distance if ``(dx, dy, dz)`` is
        approximately parallel to the selected face's planar normal.

        Returning a non-None value tells the apply path to route the
        move through extrude_face, which works on bodies with curved
        neighbour faces (cylinder caps, filleted edges) where the
        all-planar vertex-rebuild path can't help. Returns ``None`` if
        the face isn't planar, or if the move has a real lateral
        component that would actually shear the body.
        """
        try:
            from cad_app.commands import face_normal_vector
        except ModuleNotFoundError:
            return None
        try:
            nx, ny, nz = face_normal_vector(
                self._scene.get(session.item_id).shape,
                session.index,
            )
        except Exception:
            return None

        length_squared = dx * dx + dy * dy + dz * dz
        if length_squared <= 1e-12:
            return None
        normal_length = math.sqrt(nx * nx + ny * ny + nz * nz)
        if normal_length <= 1e-9:
            return None
        nx, ny, nz = nx / normal_length, ny / normal_length, nz / normal_length

        projection = dx * nx + dy * ny + dz * nz
        # The lateral component must vanish to within numerical noise -
        # otherwise the click really did ask for an off-axis push, and
        # extrude_face would silently drop that component.
        lateral_squared = length_squared - projection * projection
        if lateral_squared > 1e-6 * length_squared:
            return None
        return projection

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
