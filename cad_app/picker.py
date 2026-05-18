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
    is_planar: bool = False


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


@dataclass(frozen=True)
class PickCandidate:
    """Selectable candidate returned for overlapping or select-through picks."""

    selection: SelectionRef
    depth: float
    distance_px: float
    label: str
    result: object


@dataclass
class _FacePickAggregate:
    """Per-face accumulation across the 13 halo sample rays."""

    best_result: FacePickResult
    priority: int
    center_hit: bool
    vote_count: int
    min_distance_px: float
    min_depth: float
    is_planar: bool


# When the halo lands a planar face within this many pixels of the
# cursor, that planar hit beats a curved-face centre hit. This bridges
# the gap between geometric ray-cast and human perception near face
# boundaries: from a low elevation angle, a cylinder's top face appears
# as a thin ellipse, and clicks a few pixels below its silhouette would
# otherwise select the cylindrical side face. With this rule, "almost
# on the top" still selects the top.
_PLANAR_PREFERENCE_PX = 4.0


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
        results = self.pick_object_results_at(view, x, y, tolerance_px)
        if not results:
            return None
        return results[0]

    def pick_object_results_at(
        self,
        view: V3d_View,
        x: int,
        y: int,
        tolerance_px: float = 8.0,
    ) -> list[ObjectPickResult]:
        face_results = self.pick_face_results_at(view, x, y, tolerance_px)
        best_by_item: dict[str, ObjectPickResult] = {}
        for result in face_results:
            item_id = result.selection.item_id
            if item_id in best_by_item:
                continue
            best_by_item[item_id] = ObjectPickResult(
                selection=SelectionRef(
                    item_id=item_id,
                    kind=SelectionKind.OBJECT,
                    index=0,
                ),
                depth=result.depth,
                distance_px=result.distance_px,
            )
        return sorted(
            best_by_item.values(),
            key=lambda result: (
                result.distance_px,
                result.depth,
                result.selection.item_id,
            ),
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
        results = self.pick_face_results_at(view, x, y, tolerance_px)
        if not results:
            return None
        return results[0]

    def pick_face_results_at(
        self,
        view: V3d_View,
        x: int,
        y: int,
        tolerance_px: float = 8.0,
    ) -> list[FacePickResult]:
        # Cast 13 sample rays (center + halo) and track per-face stats:
        # whether the centre ray landed on it, how many rays voted for it,
        # and the smallest offset / depth observed. The centre-hit flag
        # and depth keep the contract that the front face under the
        # cursor wins; vote count is a stable tie-break for genuine
        # ambiguity (e.g. two faces touching the halo at equal depth),
        # so a 1-pixel cursor jitter near a face boundary doesn't flip
        # the choice.
        aggregates: dict[SelectionRef, _FacePickAggregate] = {}
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
            is_center = offset_distance <= 1e-9
            for scene_object in self._scene:
                priority = self._face_pick_priority(scene_object.meta)
                results = self._ray_pick_faces(
                    scene_object.item_id,
                    scene_object.shape,
                    origin,
                    direction,
                    eye,
                    offset_distance,
                )
                for result in results:
                    aggregate = aggregates.get(result.selection)
                    if aggregate is None:
                        aggregates[result.selection] = _FacePickAggregate(
                            best_result=result,
                            priority=priority,
                            center_hit=is_center,
                            vote_count=1,
                            min_distance_px=result.distance_px,
                            min_depth=result.depth,
                            is_planar=result.is_planar,
                        )
                        continue
                    aggregate.vote_count += 1
                    if is_center:
                        aggregate.center_hit = True
                    if priority < aggregate.priority:
                        aggregate.priority = priority
                    if self._is_better_face_pick(
                        result.distance_px,
                        result.depth,
                        priority,
                        aggregate.min_distance_px,
                        aggregate.min_depth,
                        aggregate.priority,
                    ):
                        aggregate.best_result = result
                        aggregate.min_distance_px = result.distance_px
                        aggregate.min_depth = result.depth

        return [
            aggregate.best_result
            for _selection, aggregate in sorted(
                aggregates.items(),
                key=lambda kv: (
                    self._face_pick_tier(kv[1]),
                    kv[1].priority,
                    kv[1].min_distance_px,
                    kv[1].min_depth,
                    -kv[1].vote_count,
                    kv[0].item_id,
                    kv[0].index,
                ),
            )
        ]

    @staticmethod
    def _face_pick_tier(aggregate: _FacePickAggregate) -> int:
        # Tier 0: planar face within the planar-preference radius - wins
        #         over curved-face centre hits so the top/bottom of a
        #         cylinder is preferred over its cylindrical side when
        #         the cursor is near the boundary.
        # Tier 1: anything the centre ray hit. Standard "what's under
        #         the cursor wins" behaviour.
        # Tier 2: everything else - only offset rays touched the face,
        #         and it isn't a planar-preference candidate.
        if aggregate.is_planar and aggregate.min_distance_px <= _PLANAR_PREFERENCE_PX:
            return 0
        if aggregate.center_hit:
            return 1
        return 2

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

    def pick_edge_results_at(
        self,
        view: V3d_View,
        x: int,
        y: int,
        tolerance_px: float = 16.0,
    ) -> list[EdgePickResult]:
        results: list[EdgePickResult] = []
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
                if distance > tolerance_px:
                    continue
                results.append(
                    EdgePickResult(
                        selection=SelectionRef(
                            item_id=scene_object.item_id,
                            kind=SelectionKind.EDGE,
                            index=index,
                        ),
                        distance_px=distance,
                        depth=depth,
                    )
                )
        return sorted(
            results,
            key=lambda result: (
                result.distance_px,
                result.depth,
                result.selection.item_id,
                result.selection.index,
            ),
        )

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

    def pick_vertex_results_at(
        self,
        view: V3d_View,
        x: int,
        y: int,
        tolerance_px: float = 14.0,
    ) -> list[VertexPickResult]:
        results: list[VertexPickResult] = []
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
                if distance > tolerance_px:
                    continue
                results.append(
                    VertexPickResult(
                        selection=SelectionRef(
                            item_id=scene_object.item_id,
                            kind=SelectionKind.VERTEX,
                            index=index,
                        ),
                        distance_px=distance,
                        depth=depth,
                    )
                )
        return sorted(
            results,
            key=lambda result: (
                result.distance_px,
                result.depth,
                result.selection.item_id,
                result.selection.index,
            ),
        )

    def pick_candidates_at(
        self,
        view: V3d_View,
        x: int,
        y: int,
        filter_name: SelectionKind | str,
        *,
        select_through: bool = False,
    ) -> list[PickCandidate]:
        kinds = self._selection_kinds_for_filter(filter_name)
        if not select_through and len(kinds) == 1:
            result = self._pick_first_result_at(view, x, y, kinds[0])
            if result is None:
                return []
            selection = result.selection
            return [
                PickCandidate(
                    selection=selection,
                    depth=result.depth,
                    distance_px=getattr(result, "distance_px", 0.0),
                    label=self._candidate_label(selection),
                    result=result,
                )
            ]

        candidates: list[PickCandidate] = []
        for kind in kinds:
            if kind == SelectionKind.OBJECT:
                results: list[object] = self.pick_object_results_at(view, x, y)
            elif kind == SelectionKind.FACE:
                results = self.pick_face_results_at(view, x, y)
            elif kind == SelectionKind.EDGE:
                results = self.pick_edge_results_at(view, x, y)
            else:
                results = self.pick_vertex_results_at(view, x, y)
            for result in results:
                candidates.append(
                    PickCandidate(
                        selection=result.selection,
                        depth=result.depth,
                        distance_px=getattr(result, "distance_px", 0.0),
                        label=self._candidate_label(result.selection),
                        result=result,
                    )
                )
        candidates.sort(
            key=lambda candidate: (
                candidate.distance_px,
                self._candidate_selection_priority(candidate.selection),
                candidate.depth,
                self._candidate_kind_priority(candidate.selection.kind),
                candidate.selection.item_id,
                candidate.selection.index,
            )
        )
        if select_through:
            return candidates
        return candidates[:1]

    def _pick_first_result_at(
        self,
        view: V3d_View,
        x: int,
        y: int,
        kind: SelectionKind,
    ):
        if kind == SelectionKind.OBJECT:
            return self.pick_object_result_at(view, x, y)
        if kind == SelectionKind.FACE:
            return self.pick_face_result_at(view, x, y)
        if kind == SelectionKind.EDGE:
            return self.pick_edge_result_at(view, x, y)
        return self.pick_vertex_result_at(view, x, y)

    def area_select(
        self,
        view: V3d_View,
        start: tuple[int, int],
        end: tuple[int, int],
        filter_name: str,
        *,
        require_containment: bool,
    ) -> list[SelectionRef]:
        rect = self._normalized_rect(start, end)
        selections: list[SelectionRef] = []
        seen: set[SelectionRef] = set()
        for kind in self._selection_kinds_for_filter(filter_name):
            for selection, points in self._area_selection_entries(view, kind):
                if selection in seen:
                    continue
                if not self._screen_points_match_rect(
                    points,
                    rect,
                    require_containment=require_containment,
                ):
                    continue
                selections.append(selection)
                seen.add(selection)
        return selections

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

    @staticmethod
    def _selection_kinds_for_filter(
        filter_name: SelectionKind | str,
    ) -> tuple[SelectionKind, ...]:
        if isinstance(filter_name, SelectionKind):
            return (filter_name,)
        normalized = str(filter_name).lower().replace(" ", "_")
        if normalized in {"all", "all_items"}:
            return (
                SelectionKind.OBJECT,
                SelectionKind.FACE,
                SelectionKind.EDGE,
                SelectionKind.VERTEX,
            )
        if normalized in {"body", "bodies", "object", "objects"}:
            return (SelectionKind.OBJECT,)
        if normalized in {"face", "faces"}:
            return (SelectionKind.FACE,)
        if normalized in {"edge", "edges"}:
            return (SelectionKind.EDGE,)
        if normalized in {"vertex", "vertices"}:
            return (SelectionKind.VERTEX,)
        return (SelectionKind(filter_name),)

    @staticmethod
    def _candidate_kind_priority(kind: SelectionKind) -> int:
        priorities = {
            SelectionKind.FACE: 0,
            SelectionKind.EDGE: 1,
            SelectionKind.VERTEX: 2,
            SelectionKind.OBJECT: 3,
        }
        return priorities[kind]

    def _candidate_selection_priority(self, selection: SelectionRef) -> int:
        if (
            selection.kind == SelectionKind.FACE
            and self._scene.get(selection.item_id).meta.get("kind") == "sketch_profile"
        ):
            return 0
        return 1

    @staticmethod
    def _candidate_label(selection: SelectionRef) -> str:
        if selection.kind == SelectionKind.OBJECT:
            return f"Body {selection.item_id[:8]}"
        return (
            f"{selection.kind.value.title()} {selection.index} "
            f"on {selection.item_id[:8]}"
        )

    def _area_selection_entries(
        self,
        view: V3d_View,
        kind: SelectionKind,
    ) -> list[tuple[SelectionRef, list[tuple[float, float, float]]]]:
        entries: list[tuple[SelectionRef, list[tuple[float, float, float]]]] = []
        for scene_object in self._scene:
            if kind == SelectionKind.OBJECT:
                entries.append(
                    (
                        SelectionRef(
                            item_id=scene_object.item_id,
                            kind=SelectionKind.OBJECT,
                            index=0,
                        ),
                        self._shape_screen_points(view, scene_object.shape),
                    )
                )
                continue

            indexed_map = self.indexed_map(scene_object.shape, kind)
            for index in range(1, indexed_map.Extent() + 1):
                shape = indexed_map.FindKey(index)
                if kind == SelectionKind.EDGE:
                    points = self._edge_screen_polyline(view, shape)
                elif kind == SelectionKind.VERTEX:
                    point = self._vertex_screen_point(view, shape)
                    points = [] if point is None else [point]
                else:
                    points = self._shape_screen_points(view, shape)
                entries.append(
                    (
                        SelectionRef(
                            item_id=scene_object.item_id,
                            kind=kind,
                            index=index,
                        ),
                        points,
                    )
                )
        return entries

    @staticmethod
    def _normalized_rect(
        start: tuple[int, int],
        end: tuple[int, int],
    ) -> tuple[float, float, float, float]:
        return (
            float(min(start[0], end[0])),
            float(min(start[1], end[1])),
            float(max(start[0], end[0])),
            float(max(start[1], end[1])),
        )

    @classmethod
    def _screen_points_match_rect(
        cls,
        points: list[tuple[float, float, float]],
        rect: tuple[float, float, float, float],
        *,
        require_containment: bool,
    ) -> bool:
        if not points:
            return False
        if require_containment:
            return all(
                cls._point_in_rect((point[0], point[1]), rect) for point in points
            )
        return cls._point_bbox_intersects_rect(points, rect)

    @staticmethod
    def _point_in_rect(
        point: tuple[float, float],
        rect: tuple[float, float, float, float],
    ) -> bool:
        left, top, right, bottom = rect
        return left <= point[0] <= right and top <= point[1] <= bottom

    @staticmethod
    def _point_bbox_intersects_rect(
        points: list[tuple[float, float, float]],
        rect: tuple[float, float, float, float],
    ) -> bool:
        left, top, right, bottom = rect
        point_left = min(point[0] for point in points)
        point_top = min(point[1] for point in points)
        point_right = max(point[0] for point in points)
        point_bottom = max(point[1] for point in points)
        return not (
            point_right < left
            or point_left > right
            or point_bottom < top
            or point_top > bottom
        )

    @staticmethod
    def _shape_screen_points(
        view: V3d_View,
        shape: TopoDS_Shape,
    ) -> list[tuple[float, float, float]]:
        from OCP.Bnd import Bnd_Box
        from OCP.BRepBndLib import BRepBndLib

        bounds = Bnd_Box()
        BRepBndLib.Add_s(shape, bounds)
        if bounds.IsVoid():
            return []
        min_x, min_y, min_z, max_x, max_y, max_z = bounds.Get()
        values = (min_x, min_y, min_z, max_x, max_y, max_z)
        if not all(math.isfinite(float(value)) for value in values):
            return []

        eye = tuple(float(value) for value in view.Eye())
        points: list[tuple[float, float, float]] = []
        for world_x in (min_x, max_x):
            for world_y in (min_y, max_y):
                for world_z in (min_z, max_z):
                    screen_x, screen_y = view.Convert(world_x, world_y, world_z)
                    depth = math.dist(
                        eye,
                        (float(world_x), float(world_y), float(world_z)),
                    )
                    points.append((float(screen_x), float(screen_y), depth))
        return points

    @staticmethod
    def _vertex_screen_point(
        view: V3d_View,
        vertex_shape: TopoDS_Shape,
    ) -> tuple[float, float, float] | None:
        from OCP.BRep import BRep_Tool
        from OCP.TopoDS import TopoDS

        point = BRep_Tool.Pnt_s(TopoDS.Vertex_s(vertex_shape))
        screen_x, screen_y = view.Convert(point.X(), point.Y(), point.Z())
        eye = tuple(float(value) for value in view.Eye())
        depth = math.dist(eye, (point.X(), point.Y(), point.Z()))
        return (float(screen_x), float(screen_y), depth)

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
        results = self._ray_pick_faces(
            item_id,
            shape,
            origin,
            direction,
            eye,
            distance_px,
        )
        if not results:
            return None
        return results[0]

    def _ray_pick_faces(
        self,
        item_id: str,
        shape: TopoDS_Shape,
        origin: tuple[float, float, float],
        direction: tuple[float, float, float],
        eye: tuple[float, float, float],
        distance_px: float = 0.0,
    ) -> list[FacePickResult]:
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
            return []

        results: list[FacePickResult] = []
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
            results.append(
                FacePickResult(
                    selection=selection,
                    depth=depth,
                    distance_px=distance_px,
                    is_planar=self._is_planar_face(intersector.Face(index)),
                )
            )

        return sorted(results, key=lambda result: result.depth)

    @staticmethod
    def _is_planar_face(face_shape: TopoDS_Shape) -> bool:
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_Plane
        from OCP.TopoDS import TopoDS

        try:
            surface = BRepAdaptor_Surface(TopoDS.Face_s(face_shape))
        except (RuntimeError, ValueError):
            return False
        return surface.GetType() == GeomAbs_Plane

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
        from OCP.GeomAbs import GeomAbs_Line
        from OCP.TopoDS import TopoDS

        edge = TopoDS.Edge_s(edge_shape)
        curve = BRepAdaptor_Curve(edge)
        first = curve.FirstParameter()
        last = curve.LastParameter()
        if not math.isfinite(first) or not math.isfinite(last) or first == last:
            return []

        samples = 2 if curve.GetType() == GeomAbs_Line else max(2, sample_count)
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
