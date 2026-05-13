"""Selection, hover, preview, and label markers for the OCP viewer."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from cad_app import theme
from cad_app.viewer_constants import (
    PREVIEW_POLYGON_OFFSET_FACTOR,
    PREVIEW_POLYGON_OFFSET_UNITS,
    SKETCH_PREVIEW_OFFSET,
)
from cad_app.viewer_shapes import (
    build_arrow_shape,
    edge_compound,
    translated_shape,
)

LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from OCP.AIS import AIS_Shape
    from OCP.TopoDS import TopoDS_Shape


class ViewerMarkerMixin:
    def clear_selection_marker(self, redraw: bool = True) -> None:
        if not self.is_initialized:
            self._selection_marker = None
            self._selection_markers = []
            return
        if getattr(self, "_selection_markers", None):
            for marker in self._selection_markers:
                self.context.Remove(marker, False)
            self._selection_markers = []
            self._selection_marker = None
            if redraw:
                self.view.Redraw()
            return
        if self._selection_marker is None:
            return
        self.context.Remove(self._selection_marker, redraw)
        self._selection_marker = None

    def clear_hover_marker(self, redraw: bool = True) -> None:
        if not self.is_initialized:
            self._hover_marker = None
            return
        if self._hover_marker is None:
            return
        self.context.Remove(self._hover_marker, redraw)
        self._hover_marker = None

    def clear_preview_marker(self, redraw: bool = True) -> None:
        self._restore_preview_hidden_items()
        if not self.is_initialized:
            self._preview_marker = None
            return
        if self._preview_marker is None:
            return
        self.context.Remove(self._preview_marker, redraw)
        self._preview_marker = None

    def clear_extrude_affordance_marker(self, redraw: bool = True) -> None:
        if not self.is_initialized:
            self._extrude_affordance_marker = None
            return
        if self._extrude_affordance_marker is None:
            return
        self.context.Remove(self._extrude_affordance_marker, redraw)
        self._extrude_affordance_marker = None

    def clear_dimension_label(self, redraw: bool = True) -> None:
        if not self.is_initialized:
            self._dimension_labels.clear()
            self._dimension_label = None
            self._dimension_label_shadow = None
            return
        if self._dimension_labels:
            for label in self._dimension_labels:
                self.context.Remove(label, False)
            self._dimension_labels.clear()
            self._dimension_label = None
            self._dimension_label_shadow = None
            if redraw:
                self.view.Redraw()
            return
        if self._dimension_label is not None:
            self.context.Remove(self._dimension_label, redraw)
            self._dimension_label = None
        if self._dimension_label_shadow is not None:
            self.context.Remove(self._dimension_label_shadow, redraw)
            self._dimension_label_shadow = None

    def clear_sketch_plane_marker(self, redraw: bool = True) -> None:
        if not self.is_initialized:
            self._sketch_plane_marker = None
            return
        if self._sketch_plane_marker is None:
            return
        self.context.Remove(self._sketch_plane_marker, redraw)
        self._sketch_plane_marker = None

    def display_selection_marker(
        self,
        shape: TopoDS_Shape,
        meta: dict[str, object] | None = None,
        *,
        redraw: bool = True,
    ) -> None:
        if not self.is_initialized:
            return
        self.clear_selection_marker(redraw=False)
        self._selection_marker = self._display_selection_marker(
            shape,
            meta,
            redraw=redraw,
        )

    def display_selection_markers(
        self,
        selections: list[tuple[TopoDS_Shape, dict[str, object] | None]],
        *,
        redraw: bool = True,
    ) -> None:
        if not self.is_initialized:
            return
        self.clear_selection_marker(redraw=False)
        self._selection_markers = [
            marker
            for shape, meta in selections
            if (
                marker := self._display_selection_marker(
                    shape,
                    meta,
                    redraw=False,
                )
            )
            is not None
        ]
        self._selection_marker = (
            self._selection_markers[0] if self._selection_markers else None
        )
        if redraw:
            self.view.Redraw()

    def _display_selection_marker(
        self,
        shape: TopoDS_Shape,
        meta: dict[str, object] | None = None,
        *,
        redraw: bool = True,
    ):
        from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB

        object_kind = (meta or {}).get("kind")
        if object_kind == "sketch_entity":
            return
        marker_color = theme.FACE_SELECTED
        if object_kind == "sketch_profile":
            marker_color = theme.PREVIEW_BLUE
        marker_shape = self._display_shape_for_meta(shape, meta or {})
        wireframe_marker = self._prefers_wireframe_marker(marker_shape)
        return self._display_marker(
            marker_shape,
            Quantity_Color(*marker_color, Quantity_TOC_RGB),
            width=5.0,
            transparency=0.0 if wireframe_marker else 0.22,
            wireframe=wireframe_marker,
            polygon_offset=not wireframe_marker,
            redraw=redraw,
        )

    def display_hover_marker(
        self,
        shape: TopoDS_Shape,
        meta: dict[str, object] | None = None,
        *,
        redraw: bool = True,
    ) -> None:
        from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB

        if not self.is_initialized:
            return
        self.clear_hover_marker(redraw=False)
        object_kind = (meta or {}).get("kind")
        if object_kind in {"sketch_profile", "sketch_entity"}:
            return
        marker_color = theme.FACE_HOVER
        marker_shape = self._display_shape_for_meta(shape, meta or {})
        wireframe_marker = self._prefers_wireframe_marker(marker_shape)
        self._hover_marker = self._display_marker(
            marker_shape,
            Quantity_Color(*marker_color, Quantity_TOC_RGB),
            width=4.0,
            transparency=0.0 if wireframe_marker else 0.48,
            wireframe=wireframe_marker,
            polygon_offset=not wireframe_marker,
            redraw=redraw,
        )

    def display_preview_marker(
        self,
        shape: TopoDS_Shape,
        hide_item_id: str | None = None,
        hide_item_ids: tuple[str, ...] = (),
    ) -> None:
        from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB

        if not self.is_initialized:
            return
        self.clear_preview_marker()
        hidden_ids: list[str] = []
        for item_id in (*hide_item_ids, hide_item_id):
            if item_id is None or item_id in hidden_ids:
                continue
            hidden_ids.append(item_id)
        for item_id in hidden_ids:
            LOGGER.debug("Preview marker: hiding original item_id=%s", item_id)
            self._hide_item_for_preview(item_id)
        self._preview_marker = self._display_marker(
            shape,
            Quantity_Color(*theme.PREVIEW_BLUE, Quantity_TOC_RGB),
            width=5.0,
            transparency=0.42,
            polygon_offset=True,
        )

    def display_sketch_preview_marker(
        self,
        shape: TopoDS_Shape,
        normal: tuple[float, float, float],
    ) -> None:
        from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB

        if not self.is_initialized:
            return
        self.clear_preview_marker()
        preview_shape = translated_shape(
            shape,
            normal[0] * SKETCH_PREVIEW_OFFSET,
            normal[1] * SKETCH_PREVIEW_OFFSET,
            normal[2] * SKETCH_PREVIEW_OFFSET,
        )
        edge_shape = edge_compound(preview_shape)
        self._preview_marker = self._display_marker(
            edge_shape if edge_shape is not None else preview_shape,
            Quantity_Color(*theme.SKETCH_PROFILE, Quantity_TOC_RGB),
            width=5.5,
            wireframe=True,
            topmost=True,
        )

    def display_extrude_affordance(
        self,
        start: tuple[float, float, float],
        direction: tuple[float, float, float],
        length: float = 35.0,
    ) -> None:
        from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB

        if not self.is_initialized:
            return
        self.clear_extrude_affordance_marker()
        self._extrude_affordance_marker = self._display_marker(
            build_arrow_shape(start, direction, length),
            Quantity_Color(*theme.PREVIEW_BLUE, Quantity_TOC_RGB),
            width=6.0,
            topmost=True,
        )

    def display_dimension_label(
        self,
        text: str,
        position: tuple[float, float, float],
    ) -> None:
        self.display_dimension_labels([(text, position)])

    def display_dimension_labels(
        self,
        labels: list[tuple[str, tuple[float, float, float]]],
    ) -> None:
        from OCP.AIS import AIS_TextLabel
        from OCP.gp import gp_Pnt
        from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
        from OCP.TCollection import TCollection_ExtendedString

        if not self.is_initialized:
            return
        self.clear_dimension_label(redraw=False)
        for text, position in labels:
            shadow = AIS_TextLabel()
            shadow.SetText(TCollection_ExtendedString(text))
            shadow.SetPosition(gp_Pnt(*position))
            shadow.SetHeight(16.0)
            shadow.SetColor(Quantity_Color(0.06, 0.08, 0.10, Quantity_TOC_RGB))
            if hasattr(shadow, "SetZLayer"):
                from OCP.Graphic3d import Graphic3d_ZLayerId_Topmost

                shadow.SetZLayer(Graphic3d_ZLayerId_Topmost)
            self.context.Display(shadow, False)
            self.context.Deactivate(shadow)
            self._dimension_labels.append(shadow)

            label = AIS_TextLabel()
            label.SetText(TCollection_ExtendedString(text))
            label.SetPosition(gp_Pnt(*position))
            label.SetHeight(16.0)
            label.SetColor(Quantity_Color(*theme.DIMENSION_LABEL, Quantity_TOC_RGB))
            if hasattr(label, "SetZLayer"):
                from OCP.Graphic3d import Graphic3d_ZLayerId_Topmost

                label.SetZLayer(Graphic3d_ZLayerId_Topmost)
            self.context.Display(label, False)
            self.context.Deactivate(label)
            self._dimension_labels.append(label)
            self._dimension_label_shadow = shadow
            self._dimension_label = label
        self.view.Redraw()

    def display_sketch_plane_marker(
        self,
        workplane: Any,
        size: float = 160.0,
    ) -> None:
        self.clear_sketch_plane_marker()
        LOGGER.debug("Sketch plane marker disabled size=%.1f", size)

    def _hide_item_for_preview(self, item_id: str) -> None:
        if not self.is_initialized:
            return
        ais = self._ais_map.get(item_id)
        if ais is not None:
            self.context.Erase(ais, False)
            LOGGER.debug("Preview hide: erased ais item_id=%s from display", item_id)
        edge_ais = self._edge_map.get(item_id)
        if edge_ais is not None:
            self.context.Erase(edge_ais, False)
            LOGGER.debug("Preview hide: erased edge overlay item_id=%s", item_id)
        self._preview_hidden_items.add(item_id)

    def _restore_preview_hidden_items(self) -> None:
        if not self.is_initialized:
            self._preview_hidden_items.clear()
            return
        for item_id in list(self._preview_hidden_items):
            ais = self._ais_map.get(item_id)
            if ais is not None:
                self.context.Display(ais, False)
                LOGGER.debug("Preview restore: re-displayed ais item_id=%s", item_id)
            edge_ais = self._edge_map.get(item_id)
            if edge_ais is not None:
                self.context.Display(edge_ais, False)
                LOGGER.debug("Preview restore: re-displayed edge item_id=%s", item_id)
        self._preview_hidden_items.clear()

    def _display_marker(
        self,
        shape: TopoDS_Shape,
        color_name,
        width: float,
        transparency: float = 0.0,
        wireframe: bool = False,
        topmost: bool = False,
        polygon_offset: bool = False,
        redraw: bool = True,
    ) -> AIS_Shape:
        from OCP.AIS import AIS_DisplayMode, AIS_Shape
        from OCP.Quantity import Quantity_Color

        marker = AIS_Shape(shape)
        if isinstance(color_name, Quantity_Color):
            marker.SetColor(color_name)
        else:
            marker.SetColor(Quantity_Color(color_name))
        marker.SetWidth(width)
        display_mode = (
            AIS_DisplayMode.AIS_WireFrame if wireframe else AIS_DisplayMode.AIS_Shaded
        )
        marker.SetDisplayMode(display_mode)
        if transparency > 0:
            marker.SetTransparency(transparency)
        if polygon_offset:
            self._set_preview_polygon_offset(marker)
        if topmost and hasattr(marker, "SetZLayer"):
            from OCP.Graphic3d import Graphic3d_ZLayerId_Topmost

            marker.SetZLayer(Graphic3d_ZLayerId_Topmost)
        self.context.Display(marker, False)
        self.context.Deactivate(marker)
        if redraw:
            self.view.Redraw()
        return marker

    @staticmethod
    def _prefers_wireframe_marker(shape: TopoDS_Shape) -> bool:
        from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX, TopAbs_WIRE

        return shape.ShapeType() in {
            TopAbs_EDGE,
            TopAbs_FACE,
            TopAbs_VERTEX,
            TopAbs_WIRE,
        }

    @staticmethod
    def _set_preview_polygon_offset(marker: AIS_Shape) -> None:
        from OCP.Aspect import Aspect_POM_Fill

        marker.Attributes().SetupOwnShadingAspect()
        marker.Attributes().ShadingAspect().Aspect().SetPolygonOffsets(
            Aspect_POM_Fill,
            PREVIEW_POLYGON_OFFSET_FACTOR,
            PREVIEW_POLYGON_OFFSET_UNITS,
        )

    def _display_passive_object(self, interactive_object: Any) -> None:
        self.context.Display(interactive_object, False)
        self.context.Deactivate(interactive_object)
        self._grid_objects.append(interactive_object)
