"""Sketch dimension resize and workplane helpers."""

from __future__ import annotations

import logging

from cad_app.commands import CommandError
from cad_app.sketch import (
    is_sketch_profile,
    make_center_rectangle_profile,
    make_circle_profile_at,
    make_rectangle_with_circle_cutout_profile,
)
from cad_app.types import SelectionKind, SelectionRef
from cad_app.workplane import Workplane

LOGGER = logging.getLogger(__name__)


class ViewerWidgetSketchDimensionResizeMixin:
    @staticmethod
    def _workplane_point(
        workplane: Workplane,
        uv: tuple[float, float],
    ) -> tuple[float, float, float]:
        origin = workplane.origin
        x_dir = workplane.x_direction
        y_dir = workplane.y_direction
        return (
            origin.X() + x_dir.X() * uv[0] + y_dir.X() * uv[1],
            origin.Y() + x_dir.Y() * uv[0] + y_dir.Y() * uv[1],
            origin.Z() + x_dir.Z() * uv[0] + y_dir.Z() * uv[1],
        )

    def _offset_workplane_point(
        self,
        workplane: Workplane,
        uv: tuple[float, float],
        offset: float = 4.0,
    ) -> tuple[float, float, float]:
        point = self._workplane_point(workplane, uv)
        normal = workplane.normal
        return (
            point[0] + normal.X() * offset,
            point[1] + normal.Y() * offset,
            point[2] + normal.Z() * offset,
        )

    def _workplane_from_sketch_meta(self, meta: dict[str, object]) -> Workplane:
        origin = meta.get("workplane_origin")
        x_direction = meta.get("workplane_x_direction")
        y_direction = meta.get("workplane_y_direction")
        if (
            isinstance(origin, tuple)
            and isinstance(x_direction, tuple)
            and isinstance(y_direction, tuple)
            and len(origin) == 3
            and len(x_direction) == 3
            and len(y_direction) == 3
        ):
            try:
                from OCP.gp import gp_Dir, gp_Pnt

                x_dir = gp_Dir(*[float(value) for value in x_direction])
                y_dir = gp_Dir(*[float(value) for value in y_direction])
                normal = x_dir.Crossed(y_dir)
                return Workplane(
                    origin=gp_Pnt(*[float(value) for value in origin]),
                    normal=normal,
                    x_direction=x_dir,
                    y_direction=y_dir,
                )
            except (ModuleNotFoundError, TypeError, ValueError):
                pass
        if meta.get("workplane") == "XY":
            return Workplane.world_xy()
        return self._active_workplane

    def _resize_selected_sketch_profile(
        self,
        *,
        width: float | None = None,
        height: float | None = None,
        radius: float | None = None,
        inner_circle_radius: float | None = None,
    ) -> bool:
        selection = self._scene.selection()
        if selection is None:
            self._show_status("Select a sketch profile first")
            return False
        item = self._scene.get(selection.item_id)
        if not is_sketch_profile(item.meta):
            self._show_status("Select a sketch profile first")
            return False

        meta = dict(item.meta)
        profile = meta.get("profile")
        workplane = self._workplane_from_sketch_meta(meta)
        center_u = self._sketch_meta_float(meta, "center_u") or 0.0
        center_v = self._sketch_meta_float(meta, "center_v") or 0.0

        try:
            if profile in {"rectangle", "center_rectangle", "rectangle_corners"}:
                new_width = (
                    float(width)
                    if width is not None
                    else self._sketch_meta_float(meta, "width")
                )
                new_height = (
                    float(height)
                    if height is not None
                    else self._sketch_meta_float(meta, "height")
                )
                if new_width is None or new_height is None:
                    self._show_status("Sketch dimensions are not editable yet")
                    return False
                shape = make_center_rectangle_profile(
                    workplane,
                    (center_u, center_v),
                    (
                        center_u + new_width / 2.0,
                        center_v + new_height / 2.0,
                    ),
                )
                meta.update(
                    {
                        "width": new_width,
                        "height": new_height,
                        "center_u": center_u,
                        "center_v": center_v,
                    }
                )
            elif profile == "circle":
                new_radius = (
                    float(radius)
                    if radius is not None
                    else self._sketch_meta_float(meta, "radius")
                )
                if new_radius is None:
                    self._show_status("Sketch dimensions are not editable yet")
                    return False
                shape = make_circle_profile_at(
                    workplane,
                    (center_u, center_v),
                    new_radius,
                )
                meta.update(
                    {
                        "radius": new_radius,
                        "center_u": center_u,
                        "center_v": center_v,
                    }
                )
            elif profile == "profile_with_circle_cutout":
                new_width = (
                    float(width)
                    if width is not None
                    else self._sketch_meta_float(meta, "width")
                )
                new_height = (
                    float(height)
                    if height is not None
                    else self._sketch_meta_float(meta, "height")
                )
                new_inner_radius = (
                    float(inner_circle_radius)
                    if inner_circle_radius is not None
                    else self._sketch_meta_float(meta, "inner_circle_radius")
                )
                circle_u = self._sketch_meta_float(
                    meta,
                    "inner_circle_center_u",
                )
                circle_v = self._sketch_meta_float(
                    meta,
                    "inner_circle_center_v",
                )
                if circle_u is None:
                    circle_u = center_u
                if circle_v is None:
                    circle_v = center_v
                if new_width is None or new_height is None or new_inner_radius is None:
                    self._show_status("Sketch dimensions are not editable yet")
                    return False
                shape = make_rectangle_with_circle_cutout_profile(
                    workplane,
                    (
                        center_u - new_width / 2.0,
                        center_v - new_height / 2.0,
                    ),
                    (
                        center_u + new_width / 2.0,
                        center_v + new_height / 2.0,
                    ),
                    (circle_u, circle_v),
                    new_inner_radius,
                )
                meta.update(
                    {
                        "width": new_width,
                        "height": new_height,
                        "center_u": center_u,
                        "center_v": center_v,
                        "inner_circle_radius": new_inner_radius,
                        "inner_circle_center_u": circle_u,
                        "inner_circle_center_v": circle_v,
                    }
                )
            else:
                self._show_status("Sketch dimensions are not editable yet")
                return False
        except (CommandError, ValueError) as exc:
            LOGGER.warning("Sketch dimension edit failed: %s", exc, exc_info=True)
            self._show_status("Sketch dimension edit failed")
            return False

        self._scene.replace_shape(selection.item_id, shape, meta=meta)
        self._scene.set_active_item(selection.item_id)
        self._scene.set_selection(
            SelectionRef(
                item_id=selection.item_id,
                kind=SelectionKind.FACE,
                index=1,
            )
        )
        if self._viewer.is_initialized:
            self._viewer.display_scene(self._scene, fit=False)
            self._viewer.display_selection_marker(shape, meta)
            self._show_selected_sketch_dimensions()
        summary = self._sketch_dimension_summary(meta)
        self._set_context_hint("Sketch dimensions updated")
        self._show_status(f"Sketch dimensions updated - {summary }")
        LOGGER.info(
            "Sketch dimensions updated item_id=%s %s",
            selection.item_id,
            summary,
        )
        return True
