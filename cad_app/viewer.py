"""Viewer bridge to OCP rendering."""

from __future__ import annotations

import ctypes
import logging
import math
from time import perf_counter
from typing import TYPE_CHECKING, Any

from cad_app import theme
from cad_app.types import SelectionKind

LOGGER = logging.getLogger(__name__)
SKETCH_DISPLAY_OFFSET = 1.5
SKETCH_ENTITY_DISPLAY_OFFSET = 2.5
SKETCH_PLANE_OFFSET = 1.5
SKETCH_MARKER_OFFSET = 2.2
SKETCH_PREVIEW_OFFSET = 2.5
PREVIEW_POLYGON_OFFSET_FACTOR = -8.0
PREVIEW_POLYGON_OFFSET_UNITS = -8.0

if TYPE_CHECKING:
    from OCP.AIS import AIS_InteractiveContext, AIS_Shape
    from OCP.Aspect import Aspect_DisplayConnection
    from OCP.OpenGl import OpenGl_GraphicDriver
    from OCP.TopoDS import TopoDS_Shape
    from OCP.V3d import V3d_View, V3d_Viewer
    from OCP.WNT import WNT_Window


class Viewer:
    """OCP viewer that maps UUIDs to AIS shapes."""

    def __init__(self) -> None:
        self._display: Aspect_DisplayConnection | None = None
        self._driver: OpenGl_GraphicDriver | None = None
        self._viewer: V3d_Viewer | None = None
        self._view: V3d_View | None = None
        self._context: AIS_InteractiveContext | None = None
        self._window: WNT_Window | None = None
        self._window_handle_capsule: Any | None = None
        self._ais_map: dict[str, AIS_Shape] = {}
        self._edge_map: dict[str, AIS_Shape] = {}
        self._selection_marker: AIS_Shape | None = None
        self._hover_marker: AIS_Shape | None = None
        self._preview_marker: AIS_Shape | None = None
        self._extrude_affordance_marker: AIS_Shape | None = None
        self._dimension_label: Any | None = None
        self._sketch_plane_marker: AIS_Shape | None = None
        self._grid_objects: list[Any] = []
        self._grid_enabled = True
        self._selection_kind = SelectionKind.OBJECT
        self._display_mode = "shaded"
        self._preview_hidden_items: set[str] = set()
        self.is_initialized = False

    @property
    def context(self) -> AIS_InteractiveContext:
        if self._context is None:
            raise RuntimeError("Viewer is not initialized.")
        return self._context

    @property
    def view(self) -> V3d_View:
        if self._view is None:
            raise RuntimeError("Viewer is not initialized.")
        return self._view

    def initialize(self, widget: Any) -> None:
        from OCP.AIS import AIS_InteractiveContext
        from OCP.Aspect import Aspect_DisplayConnection, Aspect_GFM_DIAG2
        from OCP.OpenGl import OpenGl_GraphicDriver
        from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
        from OCP.V3d import V3d_Viewer
        from OCP.WNT import WNT_Window

        if self.is_initialized:
            return

        start = perf_counter()
        LOGGER.info("Viewer initialization started")
        self._display = Aspect_DisplayConnection()
        self._driver = OpenGl_GraphicDriver(self._display)
        self._viewer = V3d_Viewer(self._driver)
        self._viewer.SetDefaultLights()
        self._viewer.SetLightOn()

        self._context = AIS_InteractiveContext(self._viewer)
        self._view = self._viewer.CreateView()

        self._window_handle_capsule = self._create_native_handle_capsule(widget.winId())
        self._window = WNT_Window(self._window_handle_capsule)
        self._view.SetWindow(self._window)
        if not self._window.IsMapped():
            self._window.Map()

        self._view.SetBackgroundColor(
            Quantity_Color(*theme.VIEWPORT_BG, Quantity_TOC_RGB)
        )
        if hasattr(self._view, "SetBgGradientColors"):
            self._view.SetBgGradientColors(
                Quantity_Color(*theme.VIEWPORT_BG_CENTER, Quantity_TOC_RGB),
                Quantity_Color(*theme.VIEWPORT_BG, Quantity_TOC_RGB),
                Aspect_GFM_DIAG2,
                True,
            )
        self._configure_initial_camera()
        self._view.MustBeResized()
        self.is_initialized = True
        elapsed_ms = (perf_counter() - start) * 1000.0
        LOGGER.info("Viewer initialization finished in %.1f ms", elapsed_ms)

    def resize(self) -> None:
        if not self.is_initialized:
            return
        self.view.MustBeResized()

    def clear(self) -> None:
        if not self.is_initialized:
            return
        self.clear_selection_marker()
        self.clear_hover_marker()
        self.clear_preview_marker()
        self.clear_extrude_affordance_marker()
        self.clear_dimension_label()
        self.clear_sketch_plane_marker()
        self._grid_objects.clear()
        self._ais_map.clear()
        self._edge_map.clear()
        self.context.RemoveAll(True)

    def display_shape(
        self,
        item_id: str,
        shape: TopoDS_Shape,
        meta: dict[str, object] | None = None,
    ) -> None:
        from OCP.AIS import AIS_DisplayMode, AIS_Shape
        from OCP.Graphic3d import (
            Graphic3d_MaterialAspect,
            Graphic3d_NameOfMaterial_Steel,
        )
        from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB

        if not self.is_initialized:
            raise RuntimeError("Viewer is not initialized.")
        self.erase_shape(item_id)
        meta = meta or {}
        object_kind = meta.get("kind")
        display_shape = self._display_shape_for_meta(shape, meta)
        ais = AIS_Shape(display_shape)
        if object_kind == "sketch_profile":
            ais.SetColor(Quantity_Color(*theme.SKETCH_PROFILE, Quantity_TOC_RGB))
            ais.SetWidth(3.2)
            ais.SetDisplayMode(AIS_DisplayMode.AIS_WireFrame)
        elif object_kind == "sketch_entity":
            ais.SetColor(Quantity_Color(*theme.SKETCH_ENTITY, Quantity_TOC_RGB))
            ais.SetWidth(4.5)
            ais.SetDisplayMode(AIS_DisplayMode.AIS_WireFrame)
        else:
            ais.SetColor(Quantity_Color(*theme.BODY_DEFAULT, Quantity_TOC_RGB))
            ais.SetMaterial(Graphic3d_MaterialAspect(Graphic3d_NameOfMaterial_Steel))
            ais.SetWidth(1.5)
            ais.SetDisplayMode(self._ais_display_mode())
        self._ais_map[item_id] = ais
        self.context.Display(ais, True)
        self._activate_selection_kind(ais, self._selection_kind)
        if object_kind not in {"sketch_profile", "sketch_entity"}:
            edge_ais = self._display_shape_edges(item_id, display_shape, meta)
            if edge_ais is not None:
                self._edge_map[item_id] = edge_ais
        LOGGER.debug("Displayed shape item_id=%s", item_id)

    def _display_shape_for_meta(
        self,
        shape: TopoDS_Shape,
        meta: dict[str, object],
        normal_offset: float = SKETCH_DISPLAY_OFFSET,
    ) -> TopoDS_Shape:
        object_kind = meta.get("kind")
        if object_kind not in {"sketch_profile", "sketch_entity"}:
            return shape
        if object_kind == "sketch_entity" and normal_offset == SKETCH_DISPLAY_OFFSET:
            normal_offset = SKETCH_ENTITY_DISPLAY_OFFSET
        normal = meta.get("display_normal")
        if not self._is_vector3(normal):
            normal = self._first_face_normal(shape)
        if not self._is_vector3(normal):
            return shape
        return self._translated_shape(
            shape,
            float(normal[0]) * normal_offset,
            float(normal[1]) * normal_offset,
            float(normal[2]) * normal_offset,
        )

    def erase_shape(self, item_id: str) -> None:
        if not self.is_initialized:
            return
        ais = self._ais_map.pop(item_id, None)
        edge_ais = self._edge_map.pop(item_id, None)
        if ais is not None:
            self.context.Remove(ais, False)
        if edge_ais is not None:
            self.context.Remove(edge_ais, False)
        self.update_view()
        LOGGER.debug("Erased shape item_id=%s", item_id)

    def update_view(self) -> None:
        if not self.is_initialized:
            return
        self.view.Redraw()

    def clear_selection(self) -> None:
        if not self.is_initialized:
            return
        self.context.ClearDetected(False)
        self.context.ClearSelected(True)

    def clear_selection_marker(self) -> None:
        if not self.is_initialized:
            self._selection_marker = None
            return
        if self._selection_marker is None:
            return
        self.context.Remove(self._selection_marker, True)
        self._selection_marker = None

    def clear_hover_marker(self) -> None:
        if not self.is_initialized:
            self._hover_marker = None
            return
        if self._hover_marker is None:
            return
        self.context.Remove(self._hover_marker, True)
        self._hover_marker = None

    def clear_preview_marker(self) -> None:
        self._restore_preview_hidden_items()
        if not self.is_initialized:
            self._preview_marker = None
            return
        if self._preview_marker is None:
            return
        self.context.Remove(self._preview_marker, True)
        self._preview_marker = None

    def clear_extrude_affordance_marker(self) -> None:
        if not self.is_initialized:
            self._extrude_affordance_marker = None
            return
        if self._extrude_affordance_marker is None:
            return
        self.context.Remove(self._extrude_affordance_marker, True)
        self._extrude_affordance_marker = None

    def clear_dimension_label(self) -> None:
        if not self.is_initialized:
            self._dimension_label = None
            return
        if self._dimension_label is None:
            return
        self.context.Remove(self._dimension_label, True)
        self._dimension_label = None

    def clear_sketch_plane_marker(self) -> None:
        if not self.is_initialized:
            self._sketch_plane_marker = None
            return
        if self._sketch_plane_marker is None:
            return
        self.context.Remove(self._sketch_plane_marker, True)
        self._sketch_plane_marker = None

    def display_selection_marker(
        self,
        shape: TopoDS_Shape,
        meta: dict[str, object] | None = None,
    ) -> None:
        from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB

        if not self.is_initialized:
            return
        self.clear_selection_marker()
        object_kind = (meta or {}).get("kind")
        sketch_marker = object_kind in {"sketch_profile", "sketch_entity"}
        marker_color = theme.SKETCH_PROFILE if sketch_marker else theme.FACE_SELECTED
        marker_shape = (
            self._display_shape_for_meta(
                shape,
                meta or {},
                normal_offset=SKETCH_MARKER_OFFSET,
            )
            if sketch_marker
            else self._display_shape_for_meta(shape, meta or {})
        )
        self._selection_marker = self._display_marker(
            marker_shape,
            Quantity_Color(*marker_color, Quantity_TOC_RGB),
            width=5.0,
            transparency=0.0 if sketch_marker else 0.22,
            wireframe=sketch_marker,
            topmost=sketch_marker,
            polygon_offset=not sketch_marker,
        )

    def display_hover_marker(
        self,
        shape: TopoDS_Shape,
        meta: dict[str, object] | None = None,
    ) -> None:
        from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB

        if not self.is_initialized:
            return
        self.clear_hover_marker()
        object_kind = (meta or {}).get("kind")
        sketch_marker = object_kind in {"sketch_profile", "sketch_entity"}
        marker_color = theme.SKETCH_ENTITY if sketch_marker else theme.FACE_HOVER
        marker_shape = (
            self._display_shape_for_meta(
                shape,
                meta or {},
                normal_offset=SKETCH_MARKER_OFFSET,
            )
            if sketch_marker
            else self._display_shape_for_meta(shape, meta or {})
        )
        self._hover_marker = self._display_marker(
            marker_shape,
            Quantity_Color(*marker_color, Quantity_TOC_RGB),
            width=4.0,
            transparency=0.0 if sketch_marker else 0.48,
            wireframe=sketch_marker,
            topmost=sketch_marker,
            polygon_offset=not sketch_marker,
        )

    def display_preview_marker(
        self,
        shape: TopoDS_Shape,
        hide_item_id: str | None = None,
    ) -> None:
        from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB

        if not self.is_initialized:
            return
        self.clear_preview_marker()
        if hide_item_id is not None:
            self._hide_item_for_preview(hide_item_id)
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
        preview_shape = self._translated_shape(
            shape,
            normal[0] * SKETCH_PREVIEW_OFFSET,
            normal[1] * SKETCH_PREVIEW_OFFSET,
            normal[2] * SKETCH_PREVIEW_OFFSET,
        )
        edge_shape = self._edge_compound(preview_shape)
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
            self._build_arrow_shape(start, direction, length),
            Quantity_Color(*theme.PREVIEW_BLUE, Quantity_TOC_RGB),
            width=6.0,
            topmost=True,
        )

    def display_dimension_label(
        self,
        text: str,
        position: tuple[float, float, float],
    ) -> None:
        from OCP.AIS import AIS_TextLabel
        from OCP.gp import gp_Pnt
        from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
        from OCP.TCollection import TCollection_ExtendedString

        if not self.is_initialized:
            return
        self.clear_dimension_label()
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
        self._dimension_label = label
        self.view.Redraw()

    def display_sketch_plane_marker(
        self,
        workplane: Any,
        size: float = 160.0,
    ) -> None:
        from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB

        if not self.is_initialized:
            return
        self.clear_sketch_plane_marker()
        self._sketch_plane_marker = self._display_marker(
            self._build_workplane_overlay_shape(workplane, size),
            Quantity_Color(*theme.GRID_MAJOR, Quantity_TOC_RGB),
            width=1.0,
            wireframe=True,
            topmost=True,
        )
        LOGGER.info("Displayed sketch plane marker size=%.1f", size)

    def display_grid(
        self,
        size: float = 200.0,
        step: float = 10.0,
        z_offset: float = -0.02,
    ) -> None:
        from OCP.AIS import AIS_Shape, AIS_TextLabel
        from OCP.gp import gp_Pnt
        from OCP.Quantity import (
            Quantity_Color,
            Quantity_TOC_RGB,
        )
        from OCP.TCollection import TCollection_ExtendedString

        if not self.is_initialized or not self._grid_enabled:
            return
        self.clear_grid()

        grid_color = Quantity_Color(*theme.GRID_MINOR, Quantity_TOC_RGB)
        major_color = Quantity_Color(*theme.GRID_MAJOR, Quantity_TOC_RGB)
        grid = AIS_Shape(self._build_grid_shape(size, step, z_offset))
        grid.SetColor(grid_color)
        grid.SetWidth(1.0)
        self._display_passive_object(grid)

        x_axis = AIS_Shape(self._build_axis_shape("x", size, z_offset))
        x_axis.SetColor(Quantity_Color(*theme.AXIS_X, Quantity_TOC_RGB))
        x_axis.SetWidth(2.0)
        self._display_passive_object(x_axis)

        y_axis = AIS_Shape(self._build_axis_shape("y", size, z_offset))
        y_axis.SetColor(Quantity_Color(*theme.AXIS_Y, Quantity_TOC_RGB))
        y_axis.SetWidth(2.0)
        self._display_passive_object(y_axis)

        for value in range(int(-size), int(size) + 1, int(step * 5)):
            if value == 0:
                continue
            for text, position in (
                (f"X {value}", gp_Pnt(value, 0, z_offset)),
                (f"Y {value}", gp_Pnt(0, value, z_offset)),
            ):
                label = AIS_TextLabel()
                label.SetText(TCollection_ExtendedString(text))
                label.SetPosition(position)
                label.SetHeight(10.0)
                label.SetColor(major_color)
                self._display_passive_object(label)

        self.update_view()
        LOGGER.info("Displayed coordinate grid size=%.1f step=%.1f", size, step)

    def clear_grid(self) -> None:
        if not self.is_initialized:
            self._grid_objects.clear()
            return
        for grid_object in self._grid_objects:
            self.context.Remove(grid_object, False)
        self._grid_objects.clear()

    def set_selection_kind(self, kind: SelectionKind | str) -> None:
        self._selection_kind = SelectionKind(kind)
        if not self.is_initialized:
            return
        self.clear_selection()
        self.clear_selection_marker()
        self.clear_hover_marker()
        self.clear_preview_marker()
        for ais in self._ais_map.values():
            self._activate_selection_kind(ais, self._selection_kind)
        self.update_view()
        LOGGER.info("Selection mode set to %s", self._selection_kind.value)

    @property
    def display_mode(self) -> str:
        return self._display_mode

    def set_display_mode(self, mode: str) -> None:
        if mode not in {"shaded", "wireframe"}:
            raise ValueError(f"Unsupported display mode: {mode}")
        self._display_mode = mode
        if not self.is_initialized:
            return
        display_mode = self._ais_display_mode()
        for ais in self._ais_map.values():
            ais.SetDisplayMode(display_mode)
            if hasattr(self.context, "Redisplay"):
                self.context.Redisplay(ais, False)
        self.update_view()
        LOGGER.info("Display mode set to %s", mode)

    def fit_all(self) -> None:
        if not self.is_initialized:
            return
        self.view.MustBeResized()
        self.view.FitAll(0.08, True)
        if hasattr(self.view, "ZFitAll"):
            self.view.ZFitAll()
        self.view.Redraw()

    def display_scene(self, scene, fit: bool = True) -> None:
        if not self.is_initialized:
            raise RuntimeError("Viewer is not initialized.")
        self.clear()
        for item in scene:
            self.display_shape(item.item_id, item.shape, item.meta)
        if fit and len(scene) > 0:
            self.fit_all()
        self.display_grid()
        self.display_orientation_gizmo()
        LOGGER.info("Displayed scene with %d item(s)", len(scene))

    def display_orientation_gizmo(self) -> None:
        """Display the built-in OCP triedron in the viewport corner."""
        if not self.is_initialized:
            return
        from OCP.Aspect import Aspect_TOTP_RIGHT_LOWER
        from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
        from OCP.V3d import V3d_ZBUFFER

        if hasattr(self.view, "ZBufferTriedronSetup"):
            self.view.ZBufferTriedronSetup(
                Quantity_Color(*theme.AXIS_X, Quantity_TOC_RGB),
                Quantity_Color(*theme.AXIS_Y, Quantity_TOC_RGB),
                Quantity_Color(*theme.AXIS_Z, Quantity_TOC_RGB),
                0.8,
                0.05,
                12,
            )
        self.view.TriedronDisplay(
            Aspect_TOTP_RIGHT_LOWER,
            Quantity_Color(0.92, 0.95, 0.98, Quantity_TOC_RGB),
            0.08,
            V3d_ZBUFFER,
        )

    def close(self) -> None:
        if self.is_initialized:
            self.clear()
        self._window = None
        self._context = None
        self._view = None
        self._viewer = None
        self._driver = None
        self._display = None
        self._window_handle_capsule = None
        self.is_initialized = False
        LOGGER.info("Viewer closed")

    def _hide_item_for_preview(self, item_id: str) -> None:
        if not self.is_initialized:
            return
        ais = self._ais_map.get(item_id)
        if ais is not None:
            self.context.Erase(ais, False)
        edge_ais = self._edge_map.get(item_id)
        if edge_ais is not None:
            self.context.Erase(edge_ais, False)
        self._preview_hidden_items.add(item_id)

    def _restore_preview_hidden_items(self) -> None:
        if not self.is_initialized:
            self._preview_hidden_items.clear()
            return
        for item_id in self._preview_hidden_items:
            ais = self._ais_map.get(item_id)
            if ais is not None:
                self.context.Display(ais, False)
            edge_ais = self._edge_map.get(item_id)
            if edge_ais is not None:
                self.context.Display(edge_ais, False)
        self._preview_hidden_items.clear()

    def _configure_initial_camera(self) -> None:
        from OCP.V3d import V3d_TypeOfOrientation_Zup_AxoRight

        self.view.SetAutoZFitMode(True)
        self.view.SetProj(V3d_TypeOfOrientation_Zup_AxoRight)

    def _activate_selection_kind(self, ais: AIS_Shape, kind: SelectionKind) -> None:
        mode = self._selection_mode(kind)
        self.context.Deactivate(ais)
        self.context.Activate(ais, mode, True)
        self.context.SetSelectionSensitivity(
            ais,
            mode,
            self._selection_sensitivity(kind),
        )

    @staticmethod
    def _selection_mode(kind: SelectionKind) -> int:
        from OCP.AIS import AIS_Shape
        from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX

        if kind == SelectionKind.OBJECT:
            return 0
        if kind == SelectionKind.FACE:
            return AIS_Shape.SelectionMode_s(TopAbs_FACE)
        if kind == SelectionKind.EDGE:
            return AIS_Shape.SelectionMode_s(TopAbs_EDGE)
        if kind == SelectionKind.VERTEX:
            return AIS_Shape.SelectionMode_s(TopAbs_VERTEX)
        raise ValueError(f"Unsupported selection kind: {kind}")

    def _display_marker(
        self,
        shape: TopoDS_Shape,
        color_name,
        width: float,
        transparency: float = 0.0,
        wireframe: bool = False,
        topmost: bool = False,
        polygon_offset: bool = False,
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
        self.view.Redraw()
        return marker

    @staticmethod
    def _set_preview_polygon_offset(marker: AIS_Shape) -> None:
        from OCP.Aspect import Aspect_POM_Fill

        marker.Attributes().SetupOwnShadingAspect()
        marker.Attributes().ShadingAspect().Aspect().SetPolygonOffsets(
            Aspect_POM_Fill,
            PREVIEW_POLYGON_OFFSET_FACTOR,
            PREVIEW_POLYGON_OFFSET_UNITS,
        )

    def _ais_display_mode(self) -> int:
        from OCP.AIS import AIS_DisplayMode

        if self._display_mode == "shaded":
            return AIS_DisplayMode.AIS_Shaded
        return AIS_DisplayMode.AIS_WireFrame

    def _display_passive_object(self, interactive_object: Any) -> None:
        self.context.Display(interactive_object, False)
        self.context.Deactivate(interactive_object)
        self._grid_objects.append(interactive_object)

    def _display_shape_edges(
        self,
        item_id: str,
        shape: TopoDS_Shape,
        meta: dict[str, object] | None = None,
    ) -> AIS_Shape | None:
        from OCP.AIS import AIS_DisplayMode, AIS_Shape
        from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB

        edge_shape = self._edge_compound(shape)
        if edge_shape is None:
            return None
        object_kind = (meta or {}).get("kind")
        if object_kind == "sketch_profile":
            color = Quantity_Color(*theme.SKETCH_PROFILE, Quantity_TOC_RGB)
            width = 2.8
        elif object_kind == "sketch_entity":
            color = Quantity_Color(*theme.SKETCH_ENTITY, Quantity_TOC_RGB)
            width = 3.0
        else:
            color = Quantity_Color(*theme.BODY_EDGE, Quantity_TOC_RGB)
            width = 1.4
        edge_ais = AIS_Shape(edge_shape)
        edge_ais.SetColor(color)
        edge_ais.SetWidth(width)
        edge_ais.SetDisplayMode(AIS_DisplayMode.AIS_WireFrame)
        self.context.Display(edge_ais, False)
        self.context.Deactivate(edge_ais)
        LOGGER.debug("Displayed shape edge overlay item_id=%s", item_id)
        return edge_ais

    @staticmethod
    def _build_arrow_shape(
        start: tuple[float, float, float],
        direction: tuple[float, float, float],
        length: float,
    ):
        from OCP.BRep import BRep_Builder
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
        from OCP.gp import gp_Pnt
        from OCP.TopoDS import TopoDS_Compound

        direction = Viewer._normalized(direction) or (0.0, 0.0, 1.0)
        reference = (0.0, 0.0, 1.0)
        if abs(direction[2]) > 0.85:
            reference = (1.0, 0.0, 0.0)
        side = Viewer._normalized(Viewer._cross(direction, reference))
        if side is None:
            side = (1.0, 0.0, 0.0)

        end = Viewer._add(start, Viewer._scale(direction, length))
        head_length = max(5.0, min(11.0, length * 0.25))
        head_width = head_length * 0.45
        head_base = Viewer._add(end, Viewer._scale(direction, -head_length))
        head_left = Viewer._add(head_base, Viewer._scale(side, head_width))
        head_right = Viewer._add(head_base, Viewer._scale(side, -head_width))

        builder = BRep_Builder()
        compound = TopoDS_Compound()
        builder.MakeCompound(compound)
        for first, second in ((start, end), (end, head_left), (end, head_right)):
            edge = BRepBuilderAPI_MakeEdge(
                gp_Pnt(*first),
                gp_Pnt(*second),
            ).Edge()
            builder.Add(compound, edge)
        return compound

    @staticmethod
    def _translated_shape(
        shape: TopoDS_Shape,
        dx: float,
        dy: float,
        dz: float,
    ) -> TopoDS_Shape:
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
        from OCP.gp import gp_Trsf, gp_Vec

        transform = gp_Trsf()
        transform.SetTranslation(gp_Vec(dx, dy, dz))
        builder = BRepBuilderAPI_Transform(shape, transform, True)
        return builder.Shape()

    @staticmethod
    def _first_face_normal(
        shape: TopoDS_Shape,
    ) -> tuple[float, float, float] | None:
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_Plane
        from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
        from OCP.TopExp import TopExp
        from OCP.TopoDS import TopoDS
        from OCP.TopTools import TopTools_IndexedMapOfShape

        face_map = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape, TopAbs_FACE, face_map)
        if face_map.Extent() < 1:
            return None
        face = TopoDS.Face_s(face_map.FindKey(1))
        surface = BRepAdaptor_Surface(face)
        if surface.GetType() != GeomAbs_Plane:
            return None
        normal = surface.Plane().Axis().Direction()
        if face.Orientation() == TopAbs_REVERSED:
            return -normal.X(), -normal.Y(), -normal.Z()
        return normal.X(), normal.Y(), normal.Z()

    @staticmethod
    def _is_vector3(value: object) -> bool:
        if not isinstance(value, tuple) or len(value) != 3:
            return False
        return all(isinstance(component, int | float) for component in value)

    @staticmethod
    def _normalized(
        vector: tuple[float, float, float],
    ) -> tuple[float, float, float] | None:
        length = math.sqrt(sum(component * component for component in vector))
        if length < 1e-7:
            return None
        return tuple(component / length for component in vector)

    @staticmethod
    def _cross(
        first: tuple[float, float, float],
        second: tuple[float, float, float],
    ) -> tuple[float, float, float]:
        return (
            first[1] * second[2] - first[2] * second[1],
            first[2] * second[0] - first[0] * second[2],
            first[0] * second[1] - first[1] * second[0],
        )

    @staticmethod
    def _scale(
        vector: tuple[float, float, float],
        scalar: float,
    ) -> tuple[float, float, float]:
        return tuple(component * scalar for component in vector)

    @staticmethod
    def _add(
        first: tuple[float, float, float],
        second: tuple[float, float, float],
    ) -> tuple[float, float, float]:
        return tuple(
            first_component + second_component
            for first_component, second_component in zip(first, second)
        )

    @staticmethod
    def _build_grid_shape(
        size: float,
        step: float,
        z_offset: float = 0.0,
    ) -> TopoDS_Shape:
        segments = []
        count = int(size / step)
        for index in range(-count, count + 1):
            value = index * step
            if value == 0:
                continue
            segments.append(((-size, value, z_offset), (size, value, z_offset)))
            segments.append(((value, -size, z_offset), (value, size, z_offset)))
        return Viewer._compound_from_segments(segments)

    @staticmethod
    def _build_axis_shape(
        axis: str,
        size: float,
        z_offset: float = 0.0,
    ) -> TopoDS_Shape:
        if axis == "x":
            return Viewer._compound_from_segments(
                [((-size, 0.0, z_offset), (size, 0.0, z_offset))]
            )
        if axis == "y":
            return Viewer._compound_from_segments(
                [((0.0, -size, z_offset), (0.0, size, z_offset))]
            )
        raise ValueError(f"Unsupported grid axis: {axis}")

    @staticmethod
    def _build_workplane_overlay_shape(
        workplane: Any,
        size: float,
        normal_offset: float = SKETCH_PLANE_OFFSET,
    ) -> TopoDS_Shape:
        half_size = size / 2.0
        tick = size * 0.1
        cross = size * 0.28
        segments = [
            ((-half_size, -half_size), (-half_size + tick, -half_size)),
            ((-half_size, -half_size), (-half_size, -half_size + tick)),
            ((half_size, -half_size), (half_size - tick, -half_size)),
            ((half_size, -half_size), (half_size, -half_size + tick)),
            ((half_size, half_size), (half_size - tick, half_size)),
            ((half_size, half_size), (half_size, half_size - tick)),
            ((-half_size, half_size), (-half_size + tick, half_size)),
            ((-half_size, half_size), (-half_size, half_size - tick)),
            ((-cross, 0.0), (cross, 0.0)),
            ((0.0, -cross), (0.0, cross)),
        ]
        return Viewer._compound_from_segments(
            [
                (
                    Viewer._workplane_point(
                        workplane, start[0], start[1], normal_offset
                    ),
                    Viewer._workplane_point(workplane, end[0], end[1], normal_offset),
                )
                for start, end in segments
            ]
        )

    @staticmethod
    def _workplane_point(
        workplane: Any,
        u: float,
        v: float,
        normal_offset: float,
    ) -> tuple[float, float, float]:
        from OCP.gp import gp_Pnt, gp_Vec

        vector = gp_Vec(workplane.x_direction).Multiplied(u)
        vector.Add(gp_Vec(workplane.y_direction).Multiplied(v))
        vector.Add(gp_Vec(workplane.normal).Multiplied(normal_offset))
        point = gp_Pnt(
            workplane.origin.X(),
            workplane.origin.Y(),
            workplane.origin.Z(),
        ).Translated(vector)
        return point.X(), point.Y(), point.Z()

    @staticmethod
    def _compound_from_segments(
        segments: list[tuple[tuple[float, float, float], tuple[float, float, float]]],
    ) -> TopoDS_Shape:
        from OCP.BRep import BRep_Builder
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
        from OCP.gp import gp_Pnt
        from OCP.TopoDS import TopoDS_Compound

        builder = BRep_Builder()
        compound = TopoDS_Compound()
        builder.MakeCompound(compound)
        for start, end in segments:
            edge = BRepBuilderAPI_MakeEdge(gp_Pnt(*start), gp_Pnt(*end)).Edge()
            builder.Add(compound, edge)
        return compound

    @staticmethod
    def _edge_compound(shape: TopoDS_Shape) -> TopoDS_Shape | None:
        from OCP.BRep import BRep_Builder
        from OCP.TopAbs import TopAbs_EDGE
        from OCP.TopExp import TopExp
        from OCP.TopoDS import TopoDS_Compound
        from OCP.TopTools import TopTools_IndexedMapOfShape

        edge_map = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape, TopAbs_EDGE, edge_map)
        if edge_map.Extent() == 0:
            return None

        builder = BRep_Builder()
        compound = TopoDS_Compound()
        builder.MakeCompound(compound)
        for index in range(1, edge_map.Extent() + 1):
            builder.Add(compound, edge_map.FindKey(index))
        return compound

    @staticmethod
    def _selection_sensitivity(kind: SelectionKind) -> int:
        if kind == SelectionKind.OBJECT:
            return 4
        if kind == SelectionKind.FACE:
            return 4
        if kind == SelectionKind.EDGE:
            return 12
        if kind == SelectionKind.VERTEX:
            return 14
        raise ValueError(f"Unsupported selection kind: {kind}")

    @staticmethod
    def _create_native_handle_capsule(win_id: Any) -> Any:
        if type(win_id).__name__ == "PyCapsule":
            return win_id

        ctypes.pythonapi.PyCapsule_New.restype = ctypes.py_object
        ctypes.pythonapi.PyCapsule_New.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_void_p,
        ]
        return ctypes.pythonapi.PyCapsule_New(ctypes.c_void_p(int(win_id)), None, None)
