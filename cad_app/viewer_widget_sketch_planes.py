"""Sketch plane chooser behavior for ViewerWidget."""

from __future__ import annotations

import logging

from cad_app.commands import CommandError
from cad_app.types import SelectionKind
from cad_app.workplane import Workplane

LOGGER = logging.getLogger(__name__)


class ViewerWidgetSketchPlaneMixin:
    def _show_sketch_plane_chooser(self) -> None:
        if not hasattr(self, "_sketch_plane_chooser"):
            return
        self._sketch_plane_chooser.hide()

    def _hide_sketch_plane_chooser(self) -> None:
        if not hasattr(self, "_sketch_plane_chooser"):
            return
        self._sketch_plane_hover = None
        self._sketch_plane_chooser.hide()

    def _set_sketch_plane_hover(self, plane: str | None) -> None:
        self._sketch_plane_hover = plane
        if plane is None:
            return
        self._set_context_hint(f"Sketch plane {self._plane_label(plane)}")

    def _position_sketch_plane_chooser(self) -> None:
        if not hasattr(self, "_sketch_plane_chooser"):
            return
        chooser = self._sketch_plane_chooser
        margin = 18
        x = self.width() // 2 - chooser.width() // 2
        y = self.height() // 2 - chooser.height() // 2
        if self._viewer.is_initialized:
            try:
                origin_x, origin_y = self._viewer.view.Convert(0.0, 0.0, 0.0)
                x = int(origin_x) + 18
                y = int(origin_y) - chooser.height() - 18
            except (RuntimeError, ValueError, TypeError):
                pass
        x = max(margin, min(x, self.width() - chooser.width() - margin))
        y = max(margin, min(y, self.height() - chooser.height() - margin))
        chooser.move(x, y)

    def _choose_sketch_plane(self, plane: str) -> None:
        workplane = self._workplane_for_named_plane(plane)
        self._start_sketch_session(workplane, f"{self._plane_label(plane)} plane", None)

    def _handle_spacebar_sketch_start(self) -> bool:
        if self._sketch_session is not None:
            return False
        if self._active_category != "sketch":
            return False
        if self._start_sketch_on_hovered_face():
            return True
        self._choose_sketch_plane("bottom")
        return True

    def _start_sketch_on_hovered_face(self) -> bool:
        selection = self._hover_selection
        if selection is None or selection.kind != SelectionKind.FACE:
            return False
        try:
            from OCP.TopoDS import TopoDS

            face = TopoDS.Face_s(
                self._picker.subshape(
                    selection.item_id,
                    SelectionKind.FACE,
                    selection.index,
                )
            )
            workplane = Workplane.from_face(face)
        except (CommandError, IndexError, ValueError) as exc:
            LOGGER.debug("Hovered face cannot start sketch: %s", exc, exc_info=True)
            self._show_status("Planar face required")
            return False
        self._start_sketch_session(
            workplane,
            f"new sketch on face plane {selection.index }",
            None,
        )
        return True

    @staticmethod
    def _workplane_for_named_plane(plane: str) -> Workplane:
        normalized = plane.lower()
        if normalized in {"yz", "front"}:
            return Workplane.world_yz()
        if normalized in {"xz", "side", "right"}:
            return Workplane.world_xz()
        return Workplane.world_xy()

    @staticmethod
    def _plane_label(plane: str) -> str:
        normalized = plane.lower()
        if normalized in {"xy", "bottom"}:
            return "Bottom"
        if normalized in {"yz", "front"}:
            return "Front"
        if normalized in {"xz", "side", "right"}:
            return "Side"
        return plane
