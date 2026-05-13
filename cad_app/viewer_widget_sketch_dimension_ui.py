"""Sketch dimension summaries, labels, and edit dialogs."""

from __future__ import annotations

import math

from PySide6.QtWidgets import QInputDialog

from cad_app.sketch import is_sketch_profile
from cad_app.ui_sessions import sketch_dimension_label as _sketch_dimension_label
from cad_app.viewer_widget_sketch_dimension_resize import (
    ViewerWidgetSketchDimensionResizeMixin,
)


class ViewerWidgetSketchDimensionUIMixin(ViewerWidgetSketchDimensionResizeMixin):
    @staticmethod
    def _sketch_overlay_label(
        tool: str,
        start_uv: tuple[float, float],
        end_uv: tuple[float, float],
    ) -> str:
        if tool in {"center_rectangle", "rectangle"}:
            width = abs(end_uv[0] - start_uv[0]) * 2.0
            height = abs(end_uv[1] - start_uv[1]) * 2.0
            return f"W: {width :.2f} mm, H: {height :.2f} mm"
        if tool == "circle":
            radius = math.dist(start_uv, end_uv)
            return f"R: {radius :.2f} mm"
        return _sketch_dimension_label(tool, start_uv, end_uv)

    @staticmethod
    def _sketch_dimension_meta(
        tool: str,
        start_uv: tuple[float, float],
        end_uv: tuple[float, float],
    ) -> dict[str, object]:
        if tool in {"rectangle", "center_rectangle"}:
            width = abs(end_uv[0] - start_uv[0]) * 2.0
            height = abs(end_uv[1] - start_uv[1]) * 2.0
            return {
                "width": width,
                "height": height,
                "center_u": start_uv[0],
                "center_v": start_uv[1],
            }
        if tool == "rectangle_corners":
            return {
                "width": abs(end_uv[0] - start_uv[0]),
                "height": abs(end_uv[1] - start_uv[1]),
                "center_u": (start_uv[0] + end_uv[0]) / 2.0,
                "center_v": (start_uv[1] + end_uv[1]) / 2.0,
            }
        if tool == "circle":
            return {
                "radius": math.dist(start_uv, end_uv),
                "center_u": start_uv[0],
                "center_v": start_uv[1],
            }
        return {}

    @staticmethod
    def _sketch_meta_float(
        meta: dict[str, object],
        key: str,
    ) -> float | None:
        value = meta.get(key)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _sketch_dimension_summary(
        cls,
        meta: dict[str, object],
    ) -> str:
        parts: list[str] = []
        width = cls._sketch_meta_float(meta, "width")
        height = cls._sketch_meta_float(meta, "height")
        radius = cls._sketch_meta_float(meta, "radius")
        inner_radius = cls._sketch_meta_float(meta, "inner_circle_radius")
        if width is not None and height is not None:
            parts.append(f"W {width :.2f} mm")
            parts.append(f"H {height :.2f} mm")
        if radius is not None:
            parts.append(f"R {radius :.2f} mm")
        if inner_radius is not None:
            parts.append(f"Inner R {inner_radius :.2f} mm")
        return " | ".join(parts)

    def _selected_sketch_dimension_summary(self) -> str:
        selection = self._scene.selection()
        if selection is None:
            return ""
        item = self._scene.get(selection.item_id)
        if not is_sketch_profile(item.meta):
            return ""
        return self._sketch_dimension_summary(item.meta)

    @classmethod
    def _sketch_profile_dimensions_editable(
        cls,
        meta: dict[str, object],
    ) -> bool:
        profile = meta.get("profile")
        if profile in {"rectangle", "center_rectangle", "rectangle_corners"}:
            return (
                cls._sketch_meta_float(meta, "width") is not None
                and cls._sketch_meta_float(meta, "height") is not None
            )
        if profile == "circle":
            return cls._sketch_meta_float(meta, "radius") is not None
        if profile == "profile_with_circle_cutout":
            return (
                cls._sketch_meta_float(meta, "width") is not None
                and cls._sketch_meta_float(meta, "height") is not None
                and cls._sketch_meta_float(meta, "inner_circle_radius") is not None
            )
        return False

    def _selected_sketch_profile_dimensions_editable(self) -> bool:
        selection = self._scene.selection()
        if selection is None:
            return False
        item = self._scene.get(selection.item_id)
        return is_sketch_profile(
            item.meta
        ) and self._sketch_profile_dimensions_editable(item.meta)

    def _show_selected_sketch_dimensions(self) -> None:
        if not self._viewer.is_initialized:
            return
        selection = self._scene.selection()
        if selection is None:
            self._viewer.clear_dimension_label()
            return
        item = self._scene.get(selection.item_id)
        if not is_sketch_profile(item.meta):
            self._viewer.clear_dimension_label()
            return
        labels = self._sketch_dimension_labels(item.meta)
        if labels:
            self._viewer.display_dimension_labels(labels)

    def _sketch_dimension_labels(
        self,
        meta: dict[str, object],
    ) -> list[tuple[str, tuple[float, float, float]]]:
        workplane = self._workplane_from_sketch_meta(meta)
        center_u = self._sketch_meta_float(meta, "center_u") or 0.0
        center_v = self._sketch_meta_float(meta, "center_v") or 0.0
        width = self._sketch_meta_float(meta, "width")
        height = self._sketch_meta_float(meta, "height")
        radius = self._sketch_meta_float(meta, "radius")
        inner_radius = self._sketch_meta_float(meta, "inner_circle_radius")
        labels: list[tuple[str, tuple[float, float, float]]] = []
        if width is not None and height is not None:
            labels.append(
                (
                    f"W {width :.2f} mm",
                    self._offset_workplane_point(
                        workplane,
                        (center_u, center_v + height / 2.0 + 6.0),
                    ),
                )
            )
            labels.append(
                (
                    f"H {height :.2f} mm",
                    self._offset_workplane_point(
                        workplane,
                        (center_u + width / 2.0 + 6.0, center_v),
                    ),
                )
            )
        if radius is not None:
            labels.append(
                (
                    f"R {radius :.2f} mm",
                    self._offset_workplane_point(
                        workplane,
                        (center_u + radius + 6.0, center_v),
                    ),
                )
            )
        if inner_radius is not None:
            circle_u = self._sketch_meta_float(meta, "inner_circle_center_u")
            circle_v = self._sketch_meta_float(meta, "inner_circle_center_v")
            labels.append(
                (
                    f"Inner R {inner_radius :.2f} mm",
                    self._offset_workplane_point(
                        workplane,
                        (
                            (circle_u if circle_u is not None else center_u)
                            + inner_radius
                            + 6.0,
                            circle_v if circle_v is not None else center_v,
                        ),
                    ),
                )
            )
        return labels

    def _edit_selected_sketch_dimensions(self) -> None:
        selection = self._scene.selection()
        if selection is None:
            self._show_status("Select a sketch profile first")
            return
        item = self._scene.get(selection.item_id)
        if not is_sketch_profile(item.meta):
            self._show_status("Select a sketch profile first")
            return
        if not self._sketch_profile_dimensions_editable(item.meta):
            self._show_status("Sketch dimensions are not editable yet")
            return

        profile = item.meta.get("profile")
        if profile in {"rectangle", "center_rectangle", "rectangle_corners"}:
            width = self._sketch_meta_float(item.meta, "width") or 1.0
            height = self._sketch_meta_float(item.meta, "height") or 1.0
            new_width, ok = QInputDialog.getDouble(
                self,
                "Sketch Dimensions",
                "Width (mm)",
                width,
                0.001,
                1_000_000.0,
                2,
            )
            if not ok:
                return
            new_height, ok = QInputDialog.getDouble(
                self,
                "Sketch Dimensions",
                "Height (mm)",
                height,
                0.001,
                1_000_000.0,
                2,
            )
            if ok:
                self._resize_selected_sketch_profile(
                    width=new_width,
                    height=new_height,
                )
            return

        if profile == "circle":
            radius = self._sketch_meta_float(item.meta, "radius") or 1.0
            new_radius, ok = QInputDialog.getDouble(
                self,
                "Sketch Dimensions",
                "Radius (mm)",
                radius,
                0.001,
                1_000_000.0,
                2,
            )
            if ok:
                self._resize_selected_sketch_profile(radius=new_radius)
            return

        if profile == "profile_with_circle_cutout":
            width = self._sketch_meta_float(item.meta, "width") or 1.0
            height = self._sketch_meta_float(item.meta, "height") or 1.0
            inner_radius = (
                self._sketch_meta_float(item.meta, "inner_circle_radius") or 1.0
            )
            new_width, ok = QInputDialog.getDouble(
                self,
                "Sketch Dimensions",
                "Outer width (mm)",
                width,
                0.001,
                1_000_000.0,
                2,
            )
            if not ok:
                return
            new_height, ok = QInputDialog.getDouble(
                self,
                "Sketch Dimensions",
                "Outer height (mm)",
                height,
                0.001,
                1_000_000.0,
                2,
            )
            if not ok:
                return
            new_inner_radius, ok = QInputDialog.getDouble(
                self,
                "Sketch Dimensions",
                "Inner radius (mm)",
                inner_radius,
                0.001,
                1_000_000.0,
                2,
            )
            if ok:
                self._resize_selected_sketch_profile(
                    width=new_width,
                    height=new_height,
                    inner_circle_radius=new_inner_radius,
                )
