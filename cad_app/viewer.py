"""Viewer bridge to OCP rendering."""

from __future__ import annotations

import logging
from time import perf_counter
from typing import TYPE_CHECKING, Any

from cad_app import theme
from cad_app.types import SelectionKind
from cad_app.viewer_constants import (
    PREVIEW_POLYGON_OFFSET_FACTOR,
    PREVIEW_POLYGON_OFFSET_UNITS,
    SKETCH_DISPLAY_OFFSET,
    SKETCH_ENTITY_DISPLAY_OFFSET,
    SKETCH_MARKER_OFFSET,
    SKETCH_PLANE_OFFSET,
    SKETCH_PREVIEW_OFFSET,
)
from cad_app.viewer_markers import ViewerMarkerMixin
from cad_app.viewer_native import create_native_handle_capsule
from cad_app.viewer_shapes import (
    add,
    build_arrow_shape,
    build_axis_shape,
    build_grid_shape,
    build_workplane_overlay_shape,
    compound_from_segments,
    cross,
    edge_compound,
    first_face_normal,
    is_vector3,
    mesh_wire_compound,
    normalized,
    scale,
    selection_sensitivity,
    translated_shape,
    workplane_point,
)

LOGGER = logging.getLogger(__name__)

__all__ = [
    "PREVIEW_POLYGON_OFFSET_FACTOR",
    "PREVIEW_POLYGON_OFFSET_UNITS",
    "SKETCH_DISPLAY_OFFSET",
    "SKETCH_ENTITY_DISPLAY_OFFSET",
    "SKETCH_MARKER_OFFSET",
    "SKETCH_PLANE_OFFSET",
    "SKETCH_PREVIEW_OFFSET",
    "Viewer",
]

if TYPE_CHECKING:
    from OCP.AIS import AIS_InteractiveContext, AIS_Shape
    from OCP.Aspect import Aspect_DisplayConnection
    from OCP.OpenGl import OpenGl_GraphicDriver
    from OCP.TopoDS import TopoDS_Shape
    from OCP.V3d import V3d_View, V3d_Viewer
    from OCP.WNT import WNT_Window


class Viewer(ViewerMarkerMixin):
    """OCP viewer that maps UUIDs to AIS shapes."""

    def __init__(self) -> None:
        self._display: Aspect_DisplayConnection | None = None
        self._driver: OpenGl_GraphicDriver | None = None
        self._viewer: V3d_Viewer | None = None
        self._view: V3d_View | None = None
        self._context: AIS_InteractiveContext | None = None
        self._window: WNT_Window | None = None
        self._window_handle_capsule: Any | None = None
        self._native_widget: Any | None = None
        self._ais_map: dict[str, AIS_Shape] = {}
        self._edge_map: dict[str, AIS_Shape] = {}
        self._shape_map: dict[str, Any] = {}
        self._meta_map: dict[str, dict[str, object]] = {}
        self._selection_marker: AIS_Shape | None = None
        self._selection_markers: list[AIS_Shape] = []
        self._hover_marker: AIS_Shape | None = None
        self._preview_marker: AIS_Shape | None = None
        self._extrude_affordance_marker: AIS_Shape | None = None
        self._dimension_labels: list[Any] = []
        self._dimension_label: Any | None = None
        self._dimension_label_shadow: Any | None = None
        self._sketch_plane_marker: AIS_Shape | None = None
        self._grid_objects: list[Any] = []
        self._grid_enabled = True
        self._view_cube: Any | None = None
        self._selection_kind = SelectionKind.OBJECT
        self._display_mode = "shaded"
        self._preview_hidden_items: set[str] = set()
        self.show_sketch_geometry = True
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

        self._native_widget = widget
        self._bind_native_window()

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
        self._resize_native_window()
        self.view.MustBeResized()

    def refresh_native_window(self, *, rebind: bool = False) -> None:
        if not self.is_initialized:
            return
        if rebind:
            self._bind_native_window()
        if self._window is not None and hasattr(self._window, "IsMapped"):
            try:
                if not self._window.IsMapped() and hasattr(self._window, "Map"):
                    self._window.Map()
            except RuntimeError:
                LOGGER.debug("Native viewer window remap check failed", exc_info=True)
        self._resize_native_window()
        self.view.MustBeResized()
        if self._context is not None and hasattr(self._context, "UpdateCurrentViewer"):
            self._context.UpdateCurrentViewer()
        self.view.Redraw()

    def _resize_native_window(self) -> None:
        if self._window is None or not hasattr(self._window, "DoResize"):
            return
        try:
            self._window.DoResize()
        except RuntimeError:
            LOGGER.debug("Native viewer window resize failed", exc_info=True)

    def _bind_native_window(self) -> None:
        if self._native_widget is None or self._view is None:
            return
        from OCP.WNT import WNT_Window

        self._window_handle_capsule = create_native_handle_capsule(
            self._native_widget.winId()
        )
        self._window = WNT_Window(self._window_handle_capsule)
        self._view.SetWindow(self._window)
        if not self._window.IsMapped():
            self._window.Map()

    def clear(self, redraw: bool = True) -> None:
        if not self.is_initialized:
            return
        self.clear_selection_marker(redraw=False)
        self.clear_hover_marker(redraw=False)
        self.clear_preview_marker(redraw=False)
        self.clear_extrude_affordance_marker(redraw=False)
        self.clear_dimension_label(redraw=False)
        self.clear_sketch_plane_marker(redraw=False)
        self._grid_objects.clear()
        self._ais_map.clear()
        self._edge_map.clear()
        self._shape_map.clear()
        self._meta_map.clear()
        self._view_cube = None
        self.context.RemoveAll(redraw)

    def display_shape(
        self,
        item_id: str,
        shape: TopoDS_Shape,
        meta: dict[str, object] | None = None,
        *,
        redraw: bool = True,
    ) -> None:
        from OCP.AIS import AIS_DisplayMode, AIS_Shape
        from OCP.Graphic3d import (
            Graphic3d_MaterialAspect,
            Graphic3d_NameOfMaterial_Steel,
        )
        from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB

        if not self.is_initialized:
            raise RuntimeError("Viewer is not initialized.")
        erased_existing = self.erase_shape(item_id, redraw=False)
        meta = meta or {}
        object_kind = meta.get("kind")
        if object_kind in {"sketch_profile", "sketch_entity"} and (
            not self.show_sketch_geometry
        ):
            if erased_existing and redraw:
                self.update_view()
            LOGGER.debug("Skipped hidden sketch shape item_id=%s", item_id)
            return
        display_shape = self._display_shape_for_meta(shape, meta)
        self._shape_map[item_id] = shape
        self._meta_map[item_id] = dict(meta)
        ais = AIS_Shape(display_shape)
        if object_kind == "sketch_profile":
            ais.SetColor(
                Quantity_Color(*theme.sketch_profile_color(meta), Quantity_TOC_RGB)
            )
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
        self.context.Display(ais, False)
        self._activate_selection_kind(ais, self._selection_kind, redraw=False)
        if object_kind not in {"sketch_profile", "sketch_entity"}:
            edge_ais = self._display_shape_edges(item_id, display_shape, meta)
            if edge_ais is not None:
                self._edge_map[item_id] = edge_ais
        if redraw:
            self.update_view()
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
        if not is_vector3(normal):
            normal = first_face_normal(shape)
        if not is_vector3(normal):
            return shape
        return translated_shape(
            shape,
            float(normal[0]) * normal_offset,
            float(normal[1]) * normal_offset,
            float(normal[2]) * normal_offset,
        )

    def erase_shape(self, item_id: str, *, redraw: bool = True) -> bool:
        if not self.is_initialized:
            return False
        ais = self._ais_map.pop(item_id, None)
        edge_ais = self._edge_map.pop(item_id, None)
        self._shape_map.pop(item_id, None)
        self._meta_map.pop(item_id, None)
        if ais is not None:
            self.context.Remove(ais, False)
        if edge_ais is not None:
            self.context.Remove(edge_ais, False)
        erased = ais is not None or edge_ais is not None
        if erased and redraw:
            self.update_view()
        LOGGER.debug("Erased shape item_id=%s", item_id)
        return erased

    def update_view(self) -> None:
        if not self.is_initialized:
            return
        self.view.Redraw()

    def clear_selection(self, redraw: bool = True) -> None:
        if not self.is_initialized:
            return
        self.context.ClearDetected(False)
        self.context.ClearSelected(redraw)

    def display_grid(
        self,
        size: float = 200.0,
        step: float = 10.0,
        z_offset: float = -0.02,
        *,
        redraw: bool = True,
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
        label_color = Quantity_Color(0.86, 0.91, 0.96, Quantity_TOC_RGB)
        grid = AIS_Shape(build_grid_shape(size, step, z_offset))
        grid.SetColor(grid_color)
        grid.SetWidth(1.0)
        self._display_passive_object(grid)

        x_axis = AIS_Shape(build_axis_shape("x", size, z_offset))
        x_axis.SetColor(Quantity_Color(*theme.AXIS_X, Quantity_TOC_RGB))
        x_axis.SetWidth(2.0)
        self._display_passive_object(x_axis)

        y_axis = AIS_Shape(build_axis_shape("y", size, z_offset))
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
                label.SetHeight(11.0)
                label.SetColor(label_color)
                self._display_passive_object(label)

        if redraw:
            self.update_view()
        LOGGER.info("Displayed coordinate grid size=%.1f step=%.1f", size, step)

    def clear_grid(self) -> None:
        if not self.is_initialized:
            self._grid_objects.clear()
            return
        for grid_object in self._grid_objects:
            self.context.Remove(grid_object, False)
        self._grid_objects.clear()

    def set_selection_kind(
        self,
        kind: SelectionKind | str,
        *,
        redraw: bool = True,
    ) -> None:
        normalized_kind = SelectionKind(kind)
        if self._selection_kind == normalized_kind:
            return
        self._selection_kind = normalized_kind
        if not self.is_initialized:
            return
        self.clear_selection(redraw=False)
        self.clear_selection_marker(redraw=False)
        self.clear_hover_marker(redraw=False)
        self.clear_preview_marker(redraw=False)
        for ais in self._ais_map.values():
            self._activate_selection_kind(ais, self._selection_kind, redraw=False)
        if redraw:
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
        displayed = list(self._shape_map.items())
        for item_id, shape in displayed:
            meta = self._meta_map.get(item_id, {})
            self.display_shape(item_id, shape, meta, redraw=False)
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
        self.clear(redraw=False)
        for item in scene:
            self.display_shape(item.item_id, item.shape, item.meta, redraw=False)
        if fit and len(scene) > 0:
            self.fit_all()
        self.display_grid(redraw=False)
        self.display_orientation_gizmo()
        self.update_view()
        LOGGER.info("Displayed scene with %d item(s)", len(scene))

    def display_orientation_gizmo(self) -> None:
        """Display a native OCP view cube in the viewport corner."""
        if not self.is_initialized:
            return
        from OCP.AIS import AIS_ViewCube
        from OCP.Aspect import Aspect_TOTP_RIGHT_LOWER
        from OCP.Graphic3d import (
            Graphic3d_TMF_TriedronPers,
            Graphic3d_TransformPers,
            Graphic3d_Vec2i,
            Graphic3d_ZLayerId_TopOSD,
        )
        from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
        from OCP.TCollection import TCollection_AsciiString
        from OCP.V3d import (
            V3d_TypeOfOrientation_Zup_Back,
            V3d_TypeOfOrientation_Zup_Bottom,
            V3d_TypeOfOrientation_Zup_Front,
            V3d_TypeOfOrientation_Zup_Left,
            V3d_TypeOfOrientation_Zup_Right,
            V3d_TypeOfOrientation_Zup_Top,
        )

        if hasattr(self.view, "TriedronErase"):
            self.view.TriedronErase()
        if self._view_cube is not None:
            self.context.Remove(self._view_cube, False)

        view_cube = AIS_ViewCube()
        view_cube.SetSize(70.0)
        view_cube.SetYup(False, True)
        view_cube.SetDrawAxes(True)
        view_cube.SetDrawEdges(True)
        view_cube.SetDrawVertices(True)
        view_cube.SetBoxTransparency(0.0)
        view_cube.SetBoxColor(Quantity_Color(0.04, 0.06, 0.08, Quantity_TOC_RGB))
        view_cube.SetInnerColor(Quantity_Color(0.10, 0.14, 0.18, Quantity_TOC_RGB))
        view_cube.SetTextColor(Quantity_Color(1.0, 1.0, 1.0, Quantity_TOC_RGB))
        view_cube.SetFontHeight(16.0)
        view_cube.SetAxesLabels(
            TCollection_AsciiString("X"),
            TCollection_AsciiString("Y"),
            TCollection_AsciiString("Z"),
        )
        for orientation, label in (
            (V3d_TypeOfOrientation_Zup_Top, "Top"),
            (V3d_TypeOfOrientation_Zup_Bottom, "Bottom"),
            (V3d_TypeOfOrientation_Zup_Left, "Left"),
            (V3d_TypeOfOrientation_Zup_Right, "Right"),
            (V3d_TypeOfOrientation_Zup_Front, "Front"),
            (V3d_TypeOfOrientation_Zup_Back, "Back"),
        ):
            view_cube.SetBoxSideLabel(
                orientation,
                TCollection_AsciiString(label),
            )
        view_cube.SetTransformPersistence(
            Graphic3d_TransformPers(
                Graphic3d_TMF_TriedronPers,
                Aspect_TOTP_RIGHT_LOWER,
                Graphic3d_Vec2i(96, 92),
            )
        )
        view_cube.SetZLayer(Graphic3d_ZLayerId_TopOSD)

        self.context.Display(view_cube, False)
        self.context.Activate(view_cube, 0, False)
        self._view_cube = view_cube

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

    def _configure_initial_camera(self) -> None:
        from OCP.V3d import V3d_TypeOfOrientation_Zup_AxoRight

        self.view.SetAutoZFitMode(True)
        self.view.SetProj(V3d_TypeOfOrientation_Zup_AxoRight)

    def _activate_selection_kind(
        self,
        ais: AIS_Shape,
        kind: SelectionKind,
        *,
        redraw: bool = True,
    ) -> None:
        mode = self._selection_mode(kind)
        self.context.Deactivate(ais)
        self.context.Activate(ais, mode, redraw)
        self.context.SetSelectionSensitivity(
            ais,
            mode,
            selection_sensitivity(kind),
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

    def _ais_display_mode(self) -> int:
        from OCP.AIS import AIS_DisplayMode

        if self._display_mode == "shaded":
            return AIS_DisplayMode.AIS_Shaded
        return AIS_DisplayMode.AIS_WireFrame

    def _display_shape_edges(
        self,
        item_id: str,
        shape: TopoDS_Shape,
        meta: dict[str, object] | None = None,
    ) -> AIS_Shape | None:
        from OCP.AIS import AIS_DisplayMode, AIS_Shape
        from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB

        object_kind = (meta or {}).get("kind")
        edge_shape = (
            mesh_wire_compound(shape)
            if object_kind not in {"sketch_profile", "sketch_entity"}
            and self._display_mode == "wireframe"
            else edge_compound(shape)
        )
        if edge_shape is None:
            return None
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
        return build_arrow_shape(start, direction, length)

    @staticmethod
    def _translated_shape(
        shape: TopoDS_Shape,
        dx: float,
        dy: float,
        dz: float,
    ) -> TopoDS_Shape:
        return translated_shape(shape, dx, dy, dz)

    @staticmethod
    def _first_face_normal(
        shape: TopoDS_Shape,
    ) -> tuple[float, float, float] | None:
        return first_face_normal(shape)

    @staticmethod
    def _is_vector3(value: object) -> bool:
        return is_vector3(value)

    @staticmethod
    def _normalized(
        vector: tuple[float, float, float],
    ) -> tuple[float, float, float] | None:
        return normalized(vector)

    @staticmethod
    def _cross(
        first: tuple[float, float, float],
        second: tuple[float, float, float],
    ) -> tuple[float, float, float]:
        return cross(first, second)

    @staticmethod
    def _scale(
        vector: tuple[float, float, float],
        scalar: float,
    ) -> tuple[float, float, float]:
        return scale(vector, scalar)

    @staticmethod
    def _add(
        first: tuple[float, float, float],
        second: tuple[float, float, float],
    ) -> tuple[float, float, float]:
        return add(first, second)

    @staticmethod
    def _build_grid_shape(
        size: float,
        step: float,
        z_offset: float = 0.0,
    ) -> TopoDS_Shape:
        return build_grid_shape(size, step, z_offset)

    @staticmethod
    def _build_axis_shape(
        axis: str,
        size: float,
        z_offset: float = 0.0,
    ) -> TopoDS_Shape:
        return build_axis_shape(axis, size, z_offset)

    @staticmethod
    def _build_workplane_overlay_shape(
        workplane: Any,
        size: float,
        normal_offset: float = SKETCH_PLANE_OFFSET,
    ) -> TopoDS_Shape:
        return build_workplane_overlay_shape(workplane, size, normal_offset)

    @staticmethod
    def _workplane_point(
        workplane: Any,
        u: float,
        v: float,
        normal_offset: float,
    ) -> tuple[float, float, float]:
        return workplane_point(workplane, u, v, normal_offset)

    @staticmethod
    def _compound_from_segments(
        segments: list[tuple[tuple[float, float, float], tuple[float, float, float]]],
    ) -> TopoDS_Shape:
        return compound_from_segments(segments)

    @staticmethod
    def _edge_compound(shape: TopoDS_Shape) -> TopoDS_Shape | None:
        return edge_compound(shape)

    @staticmethod
    def _selection_sensitivity(kind: SelectionKind) -> int:
        return selection_sensitivity(kind)

    @staticmethod
    def _create_native_handle_capsule(win_id: Any) -> Any:
        return create_native_handle_capsule(win_id)
