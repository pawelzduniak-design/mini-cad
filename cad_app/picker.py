"""Selection picker mapping clicks to shapes."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cad_app.scene import Scene
from cad_app.types import SelectionKind, SelectionRef

if TYPE_CHECKING:
    from OCP.AIS import AIS_InteractiveContext
    from OCP.TopoDS import TopoDS_Shape
    from OCP.TopTools import TopTools_IndexedMapOfShape
    from OCP.V3d import V3d_View


@dataclass(frozen=True)
class EdgePickResult:
    """Detailed edge picking result for UI feedback and diagnostics."""

    selection: SelectionRef
    distance_px: float
    depth: float


@dataclass(frozen=True)
class FacePickResult:
    """Detailed face picking result for UI feedback and diagnostics."""

    selection: SelectionRef
    depth: float
    distance_px: float = 0.0


@dataclass(frozen=True)
class VertexPickResult:
    """Detailed vertex picking result for UI feedback and diagnostics."""

    selection: SelectionRef
    distance_px: float
    depth: float


@dataclass(frozen=True)
class ObjectPickResult:
    """Detailed whole-object picking result for UI feedback and diagnostics."""

    selection: SelectionRef
    depth: float
    distance_px: float = 0.0


class Picker:
    """Maps selected OCP subshapes to stable scene UUID + topology indexes."""

    def __init__(self, scene: Scene | None = None) -> None:
        self.enabled = True
        self._scene = Scene() if scene is None else scene

    def attach_scene(self, scene: Scene) -> None:
        self._scene = scene

    def count_subshapes(self, item_id: str, kind: SelectionKind | str) -> int:
        if self._normalize_kind(kind) == SelectionKind.OBJECT:
            self._scene.get(item_id)
            return 1
        scene_object = self._scene.get(item_id)
        return self.indexed_map(scene_object.shape, kind).Extent()

    def subshape(
        self,
        item_id: str,
        kind: SelectionKind | str,
        index: int,
    ) -> TopoDS_Shape:
        if self._normalize_kind(kind) == SelectionKind.OBJECT:
            if index != 0:
                raise IndexError(f"Object selection index out of range: {index}")
            return self._scene.get(item_id).shape
        indexed_map = self.indexed_map(self._scene.get(item_id).shape, kind)
        if index < 1 or index > indexed_map.Extent():
            raise IndexError(f"Subshape index out of range: {index}")
        return indexed_map.FindKey(index)

    def selection_for_subshape(
        self,
        item_id: str,
        kind: SelectionKind | str,
        subshape: TopoDS_Shape,
    ) -> SelectionRef | None:
        normalized_kind = self._normalize_kind(kind)
        if normalized_kind == SelectionKind.OBJECT:
            return SelectionRef(
                item_id=item_id,
                kind=SelectionKind.OBJECT,
                index=0,
            )
        indexed_map = self.indexed_map(self._scene.get(item_id).shape, normalized_kind)
        index = indexed_map.FindIndex(subshape)
        if index <= 0:
            return None
        return SelectionRef(item_id=item_id, kind=normalized_kind, index=index)

    def pick_at(
        self,
        context: AIS_InteractiveContext,
        view: V3d_View,
        x: int,
        y: int,
        kind: SelectionKind | str,
    ) -> SelectionRef | None:
        normalized_kind = self._normalize_kind(kind)
        if normalized_kind == SelectionKind.OBJECT:
            result = self.pick_object_result_at(view, x, y)
            if result is None:
                return None
            return result.selection
        if normalized_kind == SelectionKind.FACE:
            result = self.pick_face_result_at(view, x, y)
            if result is None:
                return None
            return result.selection
        if normalized_kind == SelectionKind.EDGE:
            return self.pick_edge_at(view, x, y)
        if normalized_kind == SelectionKind.VERTEX:
            result = self.pick_vertex_result_at(view, x, y)
            if result is None:
                return None
            return result.selection

        context.MoveTo(int(x), int(y), view, True)
        if not context.HasDetectedShape():
            return None

        detected_shape = context.DetectedShape()
        for scene_object in self._scene:
            selection = self.selection_for_subshape(
                scene_object.item_id,
                normalized_kind,
                detected_shape,
            )
            if selection is not None:
                context.SelectDetected()
                view.Redraw()
                return selection
        return None

    def pick_object_result_at(
        self,
        view: V3d_View,
        x: int,
        y: int,
        tolerance_px: float = 8.0,
    ) -> ObjectPickResult | None:
        result = self.pick_face_result_at(view, x, y, tolerance_px)
        if result is None:
            return None
        return ObjectPickResult(
            selection=SelectionRef(
                item_id=result.selection.item_id,
                kind=SelectionKind.OBJECT,
                index=0,
            ),
            depth=result.depth,
            distance_px=result.distance_px,
        )

    def pick_face_at(
        self,
        context: AIS_InteractiveContext,
        view: V3d_View,
        x: int,
        y: int,
    ) -> SelectionRef | None:
        return self.pick_at(context, view, x, y, SelectionKind.FACE)

    def pick_face_result_at(
        self,
        view: V3d_View,
        x: int,
        y: int,
        tolerance_px: float = 8.0,
    ) -> FacePickResult | None:
        best_result: FacePickResult | None = None
        best_depth = math.inf
        best_distance = math.inf
        best_priority = math.inf
        for offset_x, offset_y in self._face_pick_offsets(tolerance_px):
            ray = self._view_ray(
                view,
                int(round(x + offset_x)),
                int(round(y + offset_y)),
            )
            if ray is None:
                continue
            origin, direction, eye = ray
            offset_distance = math.hypot(offset_x, offset_y)
            for scene_object in self._scene:
                priority = self._face_pick_priority(scene_object.meta)
                result = self._ray_pick_face(
                    scene_object.item_id,
                    scene_object.shape,
                    origin,
                    direction,
                    eye,
                    offset_distance,
                )
                if result is None:
                    continue
                if not self._is_better_face_pick(
                    result.distance_px,
                    result.depth,
                    priority,
                    best_distance,
                    best_depth,
                    best_priority,
                ):
                    continue
                best_result = result
                best_depth = result.depth
                best_distance = result.distance_px
                best_priority = priority

        return best_result

    def pick_edge_at(
        self,
        view: V3d_View,
        x: int,
        y: int,
        tolerance_px: float = 16.0,
    ) -> SelectionRef | None:
        result = self.pick_edge_result_at(view, x, y, tolerance_px)
        if result is None:
            return None
        return result.selection

    def pick_edge_result_at(
        self,
        view: V3d_View,
        x: int,
        y: int,
        tolerance_px: float = 16.0,
    ) -> EdgePickResult | None:
        best_result: EdgePickResult | None = None
        best_distance = tolerance_px
        best_depth = math.inf

        for scene_object in self._scene:
            edge_map = self.indexed_map(scene_object.shape, SelectionKind.EDGE)
            for index in range(1, edge_map.Extent() + 1):
                metric = self._edge_screen_metric(
                    view,
                    edge_map.FindKey(index),
                    float(x),
                    float(y),
                )
                if metric is None:
                    continue
                distance, depth = metric
                if not self._is_better_edge_pick(
                    distance,
                    depth,
                    best_distance,
                    best_depth,
                ):
                    continue
                best_distance = distance
                best_depth = depth
                best_result = EdgePickResult(
                    selection=SelectionRef(
                        item_id=scene_object.item_id,
                        kind=SelectionKind.EDGE,
                        index=index,
                    ),
                    distance_px=distance,
                    depth=depth,
                )

        return best_result

    def pick_vertex_result_at(
        self,
        view: V3d_View,
        x: int,
        y: int,
        tolerance_px: float = 14.0,
    ) -> VertexPickResult | None:
        best_result: VertexPickResult | None = None
        best_distance = tolerance_px
        best_depth = math.inf

        for scene_object in self._scene:
            vertex_map = self.indexed_map(scene_object.shape, SelectionKind.VERTEX)
            for index in range(1, vertex_map.Extent() + 1):
                metric = self._vertex_screen_metric(
                    view,
                    vertex_map.FindKey(index),
                    float(x),
                    float(y),
                )
                if metric is None:
                    continue
                distance, depth = metric
                if not self._is_better_edge_pick(
                    distance,
                    depth,
                    best_distance,
                    best_depth,
                ):
                    continue
                best_distance = distance
                best_depth = depth
                best_result = VertexPickResult(
                    selection=SelectionRef(
                        item_id=scene_object.item_id,
                        kind=SelectionKind.VERTEX,
                        index=index,
                    ),
                    distance_px=distance,
                    depth=depth,
                )

        return best_result

    @classmethod
    def indexed_map(
        cls,
        shape: TopoDS_Shape,
        kind: SelectionKind | str,
    ) -> TopTools_IndexedMapOfShape:
        from OCP.TopExp import TopExp
        from OCP.TopTools import TopTools_IndexedMapOfShape

        indexed_map = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape, cls._top_abs_kind(kind), indexed_map)
        return indexed_map

    @staticmethod
    def _normalize_kind(kind: SelectionKind | str) -> SelectionKind:
        if isinstance(kind, SelectionKind):
            return kind
        return SelectionKind(kind)

    @classmethod
    def _top_abs_kind(cls, kind: SelectionKind | str):
        from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SHAPE, TopAbs_VERTEX

        normalized_kind = cls._normalize_kind(kind)
        if normalized_kind == SelectionKind.OBJECT:
            return TopAbs_SHAPE
        if normalized_kind == SelectionKind.FACE:
            return TopAbs_FACE
        if normalized_kind == SelectionKind.EDGE:
            return TopAbs_EDGE
        if normalized_kind == SelectionKind.VERTEX:
            return TopAbs_VERTEX
        raise ValueError(f"Unsupported selection kind: {kind}")

    @classmethod
    def _edge_screen_metric(
        cls,
        view: V3d_View,
        edge_shape: TopoDS_Shape,
        x: float,
        y: float,
    ) -> tuple[float, float] | None:
        polyline = cls._edge_screen_polyline(view, edge_shape)
        if len(polyline) < 2:
            return None
        return cls._point_to_polyline_metric((x, y), polyline)

    @staticmethod
    def _vertex_screen_metric(
        view: V3d_View,
        vertex_shape: TopoDS_Shape,
        x: float,
        y: float,
    ) -> tuple[float, float] | None:
        from OCP.BRep import BRep_Tool
        from OCP.TopoDS import TopoDS

        point = BRep_Tool.Pnt_s(TopoDS.Vertex_s(vertex_shape))
        screen_x, screen_y = view.Convert(point.X(), point.Y(), point.Z())
        eye = view.Eye()
        depth = math.dist(eye, (point.X(), point.Y(), point.Z()))
        return math.hypot(float(screen_x) - x, float(screen_y) - y), depth

    def _ray_pick_face(
        self,
        item_id: str,
        shape: TopoDS_Shape,
        origin: tuple[float, float, float],
        direction: tuple[float, float, float],
        eye: tuple[float, float, float],
        distance_px: float = 0.0,
    ) -> FacePickResult | None:
        from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
        from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector

        intersector = IntCurvesFace_ShapeIntersector()
        intersector.Load(shape, 1e-7)
        line = gp_Lin(
            gp_Pnt(*origin),
            gp_Dir(*direction),
        )
        intersector.Perform(line, -1.0e9, 1.0e9)
        if not intersector.IsDone() or intersector.NbPnt() == 0:
            return None

        best_result: FacePickResult | None = None
        best_depth = math.inf
        for index in range(1, intersector.NbPnt() + 1):
            selection = self.selection_for_subshape(
                item_id,
                SelectionKind.FACE,
                intersector.Face(index),
            )
            if selection is None:
                continue

            point = intersector.Pnt(index)
            depth = math.dist(eye, (point.X(), point.Y(), point.Z()))
            if depth >= best_depth:
                continue
            best_depth = depth
            best_result = FacePickResult(
                selection=selection,
                depth=depth,
                distance_px=distance_px,
            )

        return best_result

    @staticmethod
    def _face_pick_priority(meta: dict[str, object]) -> int:
        if meta.get("kind") == "sketch_profile":
            return 0
        return 1

    @staticmethod
    def _is_better_face_pick(
        distance: float,
        depth: float,
        priority: int,
        best_distance: float,
        best_depth: float,
        best_priority: int,
    ) -> bool:
        if distance > best_distance + 1e-7:
            return False
        if abs(distance - best_distance) > 1e-7:
            return True
        if priority != best_priority:
            return priority < best_priority
        return depth < best_depth

    @staticmethod
    def _face_pick_offsets(tolerance_px: float) -> tuple[tuple[float, float], ...]:
        if tolerance_px <= 0:
            return ((0.0, 0.0),)
        half = tolerance_px / 2.0
        return (
            (0.0, 0.0),
            (-half, 0.0),
            (half, 0.0),
            (0.0, -half),
            (0.0, half),
            (-half, -half),
            (half, -half),
            (-half, half),
            (half, half),
            (-tolerance_px, 0.0),
            (tolerance_px, 0.0),
            (0.0, -tolerance_px),
            (0.0, tolerance_px),
        )

    @staticmethod
    def _edge_screen_polyline(
        view: V3d_View,
        edge_shape: TopoDS_Shape,
        sample_count: int = 24,
    ) -> list[tuple[float, float, float]]:
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.TopoDS import TopoDS

        edge = TopoDS.Edge_s(edge_shape)
        curve = BRepAdaptor_Curve(edge)
        first = curve.FirstParameter()
        last = curve.LastParameter()
        if not math.isfinite(first) or not math.isfinite(last) or first == last:
            return []

        samples = max(2, sample_count)
        points: list[tuple[float, float, float]] = []
        eye_x, eye_y, eye_z = view.Eye()
        for offset in range(samples):
            ratio = offset / (samples - 1)
            parameter = first + (last - first) * ratio
            point = curve.Value(parameter)
            screen_x, screen_y = view.Convert(point.X(), point.Y(), point.Z())
            depth = math.dist((eye_x, eye_y, eye_z), (point.X(), point.Y(), point.Z()))
            points.append((float(screen_x), float(screen_y), depth))
        return points

    @classmethod
    def _point_to_polyline_metric(
        cls,
        point: tuple[float, float],
        polyline: list[tuple[float, float, float]],
    ) -> tuple[float, float]:
        metrics = (
            cls._point_to_segment_metric(point, start, end)
            for start, end in zip(polyline, polyline[1:])
        )
        return min(metrics, key=lambda metric: metric[0])

    @staticmethod
    def _point_to_segment_metric(
        point: tuple[float, float],
        start: tuple[float, float, float],
        end: tuple[float, float, float],
    ) -> tuple[float, float]:
        px, py = point
        ax, ay, start_depth = start
        bx, by, end_depth = end
        dx = bx - ax
        dy = by - ay
        segment_length_sq = dx * dx + dy * dy
        if segment_length_sq == 0:
            return math.hypot(px - ax, py - ay), start_depth

        ratio = ((px - ax) * dx + (py - ay) * dy) / segment_length_sq
        clamped_ratio = max(0.0, min(1.0, ratio))
        closest_x = ax + clamped_ratio * dx
        closest_y = ay + clamped_ratio * dy
        depth = start_depth + (end_depth - start_depth) * clamped_ratio
        return math.hypot(px - closest_x, py - closest_y), depth

    @staticmethod
    def _point_to_segment_distance(
        point: tuple[float, float],
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> float:
        distance, _depth = Picker._point_to_segment_metric(
            point,
            (start[0], start[1], 0.0),
            (end[0], end[1], 0.0),
        )
        return distance

    @staticmethod
    def _is_better_edge_pick(
        distance: float,
        depth: float,
        best_distance: float,
        best_depth: float,
        tie_px: float = 2.0,
    ) -> bool:
        if distance < best_distance - tie_px:
            return True
        return abs(distance - best_distance) <= tie_px and depth < best_depth

    @staticmethod
    def _view_ray(
        view: V3d_View,
        x: int,
        y: int,
    ) -> (
        tuple[
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
        ]
        | None
    ):
        origin_x, origin_y, origin_z, dir_x, dir_y, dir_z = view.ConvertWithProj(
            int(x),
            int(y),
        )
        length = math.sqrt(dir_x * dir_x + dir_y * dir_y + dir_z * dir_z)
        if length == 0:
            return None
        eye = tuple(float(value) for value in view.Eye())
        return (
            (float(origin_x), float(origin_y), float(origin_z)),
            (float(dir_x / length), float(dir_y / length), float(dir_z / length)),
            eye,
        )
