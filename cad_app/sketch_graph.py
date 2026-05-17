"""Sketch curve graph utilities for trim and loop rebuilding."""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, hypot, isfinite, pi, sin, sqrt
from typing import Any

from cad_app.workplane import Workplane

PointUV = tuple[float, float]
SegmentUV = tuple[PointUV, PointUV]

EPSILON = 1e-7
INTERSECTION_EPSILON = 1e-5
POINT_PRECISION = 7
TAU = 2.0 * pi


@dataclass(frozen=True)
class SketchCurve:
    kind: str
    start: PointUV | None = None
    end: PointUV | None = None
    center: PointUV | None = None
    radius: float | None = None
    ccw: bool = True


@dataclass(frozen=True)
class SketchGraphSource:
    item_id: str
    segments: tuple[SegmentUV, ...]
    meta: dict[str, object]
    curves: tuple[SketchCurve, ...] = ()


@dataclass(frozen=True)
class AtomicSketchSegment:
    start: PointUV
    end: PointUV
    source_item_id: str
    kind: str = "line"
    center: PointUV | None = None
    radius: float | None = None
    ccw: bool = True
    source_item_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SketchTrimGraphResult:
    removed_segment: AtomicSketchSegment
    loops: tuple[tuple[PointUV, ...], ...]
    open_segments: tuple[AtomicSketchSegment, ...]
    source_item_ids: tuple[str, ...]
    loop_segments: tuple[tuple[AtomicSketchSegment, ...], ...] = ()
    # Other open entities (sketch_entity kind) that share an endpoint
    # with the removed atomic and should be split into separate
    # atomic-line entities so each "arm" of the intersection becomes
    # selectable on its own.
    crossing_split_sources: tuple[tuple[str, tuple[AtomicSketchSegment, ...]], ...] = ()


@dataclass(frozen=True)
class _CurveRecord:
    item_ids: tuple[str, ...]
    curve: SketchCurve


def center_rectangle_segments(
    center: PointUV,
    width: float,
    height: float,
) -> tuple[SegmentUV, ...]:
    half_width = width / 2.0
    half_height = height / 2.0
    min_u = center[0] - half_width
    max_u = center[0] + half_width
    min_v = center[1] - half_height
    max_v = center[1] + half_height
    points = (
        (min_u, min_v),
        (max_u, min_v),
        (max_u, max_v),
        (min_u, max_v),
    )
    return polyline_segments((*points, points[0]))


def corner_rectangle_segments(first: PointUV, second: PointUV) -> tuple[SegmentUV, ...]:
    min_u = min(first[0], second[0])
    max_u = max(first[0], second[0])
    min_v = min(first[1], second[1])
    max_v = max(first[1], second[1])
    points = (
        (min_u, min_v),
        (max_u, min_v),
        (max_u, max_v),
        (min_u, max_v),
    )
    return polyline_segments((*points, points[0]))


def three_point_rectangle_segments(
    first: PointUV,
    second: PointUV,
    third: PointUV,
) -> tuple[SegmentUV, ...]:
    base_x = second[0] - first[0]
    base_y = second[1] - first[1]
    base_length = hypot(base_x, base_y)
    if base_length <= EPSILON:
        return ()
    normal_x = -base_y / base_length
    normal_y = base_x / base_length
    height = (third[0] - first[0]) * normal_x + (third[1] - first[1]) * normal_y
    if abs(height) <= EPSILON:
        return ()
    offset = (normal_x * height, normal_y * height)
    points = (
        first,
        second,
        (second[0] + offset[0], second[1] + offset[1]),
        (first[0] + offset[0], first[1] + offset[1]),
        first,
    )
    return polyline_segments(points)


def polyline_segments(
    points: tuple[PointUV, ...] | list[PointUV],
) -> tuple[SegmentUV, ...]:
    segments: list[SegmentUV] = []
    for start, end in zip(points, points[1:]):
        if _distance(start, end) > EPSILON:
            segments.append((_normalize_point(start), _normalize_point(end)))
    return tuple(segments)


def circle_curve(center: PointUV, radius: float) -> SketchCurve | None:
    if radius <= EPSILON:
        return None
    return SketchCurve(
        kind="circle",
        center=_normalize_point(center),
        radius=float(radius),
        ccw=True,
    )


def arc_curve(start: PointUV, end: PointUV, bend: PointUV) -> SketchCurve | None:
    if (
        _distance(start, end) <= EPSILON
        or _distance(start, bend) <= EPSILON
        or _distance(end, bend) <= EPSILON
    ):
        return None
    center = _circumcenter(start, bend, end)
    if center is None:
        return None
    radius = _distance(center, start)
    start_angle = _angle_from(center, start)
    bend_angle = _angle_from(center, bend)
    end_angle = _angle_from(center, end)
    return SketchCurve(
        kind="arc",
        start=_normalize_point(start),
        end=_normalize_point(end),
        center=_normalize_point(center),
        radius=radius,
        ccw=_angle_on_ccw_span(start_angle, end_angle, bend_angle),
    )


def segments_meta(
    segments: tuple[SegmentUV, ...] | list[SegmentUV],
) -> dict[str, object]:
    normalized = tuple(_normalize_segment(segment) for segment in segments)
    return {
        "segment_graph": bool(normalized),
        "segments_uv": normalized,
    }


def curves_meta(
    curves: tuple[SketchCurve, ...] | list[SketchCurve | None],
) -> dict[str, object]:
    serialized = tuple(
        curve_meta
        for curve in curves
        if curve is not None
        for curve_meta in (_curve_to_meta(curve),)
        if curve_meta is not None
    )
    return {
        "segment_graph": bool(serialized),
        "curves_uv": serialized,
    }


def graph_meta_from_edges(
    edges: tuple[AtomicSketchSegment, ...] | list[AtomicSketchSegment],
) -> dict[str, object]:
    line_segments = tuple(
        (edge.start, edge.end) for edge in edges if edge.kind == "line"
    )
    curve_specs = tuple(
        spec
        for edge in edges
        if edge.kind != "line"
        for spec in (_curve_spec_from_edge(edge),)
        if spec is not None
    )
    return {
        "segment_graph": bool(line_segments or curve_specs),
        "segments_uv": tuple(_normalize_segment(segment) for segment in line_segments),
        "curves_uv": curve_specs,
    }


def curve_specs_from_edges(
    edges: tuple[AtomicSketchSegment, ...] | list[AtomicSketchSegment],
) -> tuple[dict[str, object], ...]:
    specs: list[dict[str, object]] = []
    for edge in edges:
        if edge.kind == "line":
            specs.append(
                {
                    "kind": "line",
                    "start": _normalize_point(edge.start),
                    "end": _normalize_point(edge.end),
                }
            )
            continue
        spec = _curve_spec_from_edge(edge)
        if spec is not None:
            specs.append(spec)
    return tuple(specs)


def shape_graph_meta(shape: Any, workplane: Workplane) -> dict[str, object]:
    segments, curves = _geometry_from_shape(shape, workplane)
    meta = segments_meta(segments)
    curve_meta = curves_meta(curves)
    return {
        **meta,
        **curve_meta,
        "segment_graph": bool(segments or curves),
    }


def segments_from_meta(meta: dict[str, object]) -> tuple[SegmentUV, ...]:
    explicit_segments = _explicit_segments_from_meta(meta)
    if explicit_segments:
        return explicit_segments

    profile = meta.get("profile")
    width = _meta_float(meta, "width")
    height = _meta_float(meta, "height")
    if profile in {
        "rectangle",
        "center_rectangle",
        "rectangle_corners",
        "profile_with_circle_cutout",
    }:
        if width is None or height is None:
            return ()
        center_u = _meta_float(meta, "center_u") or 0.0
        center_v = _meta_float(meta, "center_v") or 0.0
        return center_rectangle_segments((center_u, center_v), width, height)
    return ()


def curves_from_meta(meta: dict[str, object]) -> tuple[SketchCurve, ...]:
    explicit_curves = _explicit_curves_from_meta(meta)
    if explicit_curves:
        return explicit_curves

    profile = meta.get("profile")
    if profile == "circle":
        radius = _meta_float(meta, "radius")
        if radius is None:
            return ()
        center_u = _meta_float(meta, "center_u") or 0.0
        center_v = _meta_float(meta, "center_v") or 0.0
        curve = circle_curve((center_u, center_v), radius)
        return (curve,) if curve is not None else ()
    if profile == "arc":
        curve = _arc_curve_from_meta(meta)
        return (curve,) if curve is not None else ()
    if profile == "profile_with_circle_cutout":
        radius = _meta_float(meta, "inner_circle_radius")
        if radius is None:
            return ()
        center_u = _meta_float(meta, "inner_circle_center_u")
        center_v = _meta_float(meta, "inner_circle_center_v")
        if center_u is None:
            center_u = _meta_float(meta, "center_u") or 0.0
        if center_v is None:
            center_v = _meta_float(meta, "center_v") or 0.0
        curve = circle_curve((center_u, center_v), radius)
        return (curve,) if curve is not None else ()
    return ()


def linear_segments_from_shape(
    shape: Any, workplane: Workplane
) -> tuple[SegmentUV, ...]:
    segments, _curves = _geometry_from_shape(shape, workplane)
    return segments


def trim_segment_graph(
    sources: tuple[SketchGraphSource, ...] | list[SketchGraphSource],
    uv: PointUV,
    *,
    max_distance: float = 5.0,
) -> SketchTrimGraphResult | None:
    atomic_segments = split_sources_at_intersections(sources)
    if not atomic_segments:
        return None
    nearest = min(
        atomic_segments,
        key=lambda segment: _point_atomic_distance(uv, segment),
    )
    if _point_atomic_distance(uv, nearest) > max_distance:
        return None
    target_sources = _trim_target_sources(sources, nearest)
    if not target_sources:
        return None
    # Also split any source that shares an endpoint with the removed
    # atomic (i.e. an entity crossing through this intersection): in
    # the UI the user expects "click one arm of a cross, the other arm
    # also breaks into separate pieces at the intersection point" so
    # each surviving arm becomes its own selectable entity rather than
    # a single unsegmented line that still passes through the deleted
    # spot.
    primary_ids = {source.item_id for source in target_sources}
    removed_endpoints = (nearest.start, nearest.end)
    crossing_split_sources: list[tuple[str, tuple[AtomicSketchSegment, ...]]] = []
    for source in sources:
        if source.item_id in primary_ids:
            continue
        # Only split _open_ sketch entities at the intersection.
        # Closed profile regions produced by the regionization pipeline
        # (base / intersection / tool) already share endpoints with
        # everything else and must not be re-emitted as atomics — that
        # would dissolve the regions the user explicitly built.
        if source.meta.get("kind") != "sketch_entity":
            continue
        source_atomics: list[AtomicSketchSegment] = []
        for segment in atomic_segments:
            if source.item_id not in _atomic_segment_owner_ids(sources, segment):
                continue
            source_atomics.append(_retarget_atomic_source(segment, source.item_id))
        if not source_atomics:
            continue
        # Only split when the open entity actually has more than one
        # atomic — single-atomic entities have no crossing to dissolve.
        if len(source_atomics) < 2:
            continue
        touches_removed = any(
            _same_point(endpoint, atomic.start) or _same_point(endpoint, atomic.end)
            for atomic in source_atomics
            for endpoint in removed_endpoints
        )
        if touches_removed:
            crossing_split_sources.append((source.item_id, tuple(source_atomics)))
    removed_key = _atomic_geometry_key(nearest)
    loop_segments: list[tuple[AtomicSketchSegment, ...]] = []
    open_segments: list[AtomicSketchSegment] = []
    for source in target_sources:
        target_segments = tuple(
            _retarget_atomic_source(segment, source.item_id)
            for segment in atomic_segments
            if source.item_id in _atomic_segment_owner_ids(sources, segment)
        )
        remaining = [
            segment
            for segment in target_segments
            if _atomic_geometry_key(segment) != removed_key
        ]
        source_loop_segments = _positive_face_loops(remaining)
        loop_segments.extend(source_loop_segments)
        loop_edges = {
            _atomic_geometry_key(edge) for loop in source_loop_segments for edge in loop
        }
        open_segments.extend(
            segment
            for segment in remaining
            if _atomic_geometry_key(segment) not in loop_edges
        )
    # Fallback for regionized sketches with multiple primary target
    # sources (typical for 3+ overlapping circles or rect+circle
    # arrangements where regionization gives the user many adjacent
    # closed regions sharing edges): if the per-source walk left any
    # edges open, try forming closures by mixing them with atomics from
    # OTHER (non-target) sources. This recovers regions whose boundary
    # crosses several entities — the "after trim only one of seven
    # regions remained extrudable" symptom in the user's log.
    #
    # We skip this fallback for single-target trims (the canonical
    # "two circles" workflow) where preserving an open arc_segment is
    # the documented, tested behaviour.
    if open_segments and len(target_sources) > 1:
        already_in_loops = {
            _atomic_geometry_key(edge) for loop in loop_segments for edge in loop
        }
        non_target_atomics = [
            _retarget_atomic_source(segment, "")
            for segment in atomic_segments
            if _atomic_geometry_key(segment) != removed_key
            and _atomic_geometry_key(segment) not in already_in_loops
            and not any(
                source.item_id in _atomic_segment_owner_ids(sources, segment)
                for source in target_sources
            )
        ]
        if non_target_atomics:
            combined = list(open_segments) + non_target_atomics
            extra_loops = _positive_face_loops(combined)
            extra_loop_keys: set[tuple] = set()
            for loop in extra_loops:
                if all(
                    _atomic_geometry_key(edge) not in already_in_loops for edge in loop
                ):
                    loop_segments.append(loop)
                    for edge in loop:
                        extra_loop_keys.add(_atomic_geometry_key(edge))
            if extra_loop_keys:
                open_segments = [
                    seg
                    for seg in open_segments
                    if _atomic_geometry_key(seg) not in extra_loop_keys
                ]
    return SketchTrimGraphResult(
        removed_segment=nearest,
        loops=tuple(tuple(edge.start for edge in loop) for loop in loop_segments),
        open_segments=tuple(open_segments),
        source_item_ids=tuple(source.item_id for source in target_sources),
        loop_segments=tuple(loop_segments),
        crossing_split_sources=tuple(crossing_split_sources),
    )


def split_sources_at_intersections(
    sources: tuple[SketchGraphSource, ...] | list[SketchGraphSource],
) -> tuple[AtomicSketchSegment, ...]:
    raw_curves: list[_CurveRecord] = []
    for source in sources:
        for segment in source.segments:
            normalized = _normalize_segment(segment)
            if _distance(*normalized) > EPSILON:
                raw_curves.append(
                    _CurveRecord(
                        (source.item_id,),
                        SketchCurve(
                            kind="line",
                            start=normalized[0],
                            end=normalized[1],
                        ),
                    )
                )
        for curve in source.curves:
            if _curve_valid(curve):
                raw_curves.append(_CurveRecord((source.item_id,), curve))

    raw_curves = _heal_curve_records(raw_curves)
    split_parameters: list[list[float]] = [
        _initial_split_parameters(record.curve) for record in raw_curves
    ]
    for first_index, first_record in enumerate(raw_curves):
        for second_index in range(first_index + 1, len(raw_curves)):
            second_record = raw_curves[second_index]
            for first_t, second_t in _curve_intersections(
                first_record.curve,
                second_record.curve,
            ):
                split_parameters[first_index].append(first_t)
                split_parameters[second_index].append(second_t)

    atomic: list[AtomicSketchSegment] = []
    seen: set[tuple[object, ...]] = set()
    for record, parameters in zip(raw_curves, split_parameters):
        curve_segments = _split_curve(record.item_ids, record.curve, parameters)
        for segment in curve_segments:
            key = _atomic_geometry_key(segment)
            if key in seen:
                continue
            seen.add(key)
            atomic.append(segment)
    return tuple(atomic)


def _geometry_from_shape(
    shape: Any,
    workplane: Workplane,
) -> tuple[tuple[SegmentUV, ...], tuple[SketchCurve, ...]]:
    try:
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Line
        from OCP.TopAbs import TopAbs_EDGE
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopoDS import TopoDS
    except ModuleNotFoundError:
        return (), ()

    segments: list[SegmentUV] = []
    curves: list[SketchCurve] = []
    explorer = TopExp_Explorer(shape, TopAbs_EDGE)
    while explorer.More():
        edge = TopoDS.Edge_s(explorer.Current())
        curve = BRepAdaptor_Curve(edge)
        first = float(curve.FirstParameter())
        last = float(curve.LastParameter())
        if not isfinite(first) or not isfinite(last):
            explorer.Next()
            continue
        if curve.GetType() == GeomAbs_Line:
            start = _uv_from_workplane_point(workplane, curve.Value(first))
            end = _uv_from_workplane_point(workplane, curve.Value(last))
            if _distance(start, end) > EPSILON:
                segments.append((_normalize_point(start), _normalize_point(end)))
        elif curve.GetType() == GeomAbs_Circle:
            circle = curve.Circle()
            center = _uv_from_workplane_point(workplane, circle.Location())
            radius = float(circle.Radius())
            start = _uv_from_workplane_point(workplane, curve.Value(first))
            end = _uv_from_workplane_point(workplane, curve.Value(last))
            span = abs(last - first)
            if _distance(start, end) <= INTERSECTION_EPSILON and span >= TAU - 1e-4:
                graph_curve = circle_curve(center, radius)
            else:
                bend = _uv_from_workplane_point(
                    workplane,
                    curve.Value(first + (last - first) / 2.0),
                )
                graph_curve = arc_curve(start, end, bend)
            if graph_curve is not None:
                curves.append(graph_curve)
        explorer.Next()
    return tuple(segments), tuple(curves)


def _explicit_segments_from_meta(meta: dict[str, object]) -> tuple[SegmentUV, ...]:
    raw_segments = meta.get("segments_uv")
    if not isinstance(raw_segments, (list, tuple)):
        return ()
    segments: list[SegmentUV] = []
    for raw_segment in raw_segments:
        if not isinstance(raw_segment, (list, tuple)) or len(raw_segment) != 2:
            continue
        start = _point_from_object(raw_segment[0])
        end = _point_from_object(raw_segment[1])
        if start is None or end is None or _distance(start, end) <= EPSILON:
            continue
        segments.append((_normalize_point(start), _normalize_point(end)))
    return tuple(segments)


def _explicit_curves_from_meta(meta: dict[str, object]) -> tuple[SketchCurve, ...]:
    raw_curves = meta.get("curves_uv")
    if not isinstance(raw_curves, (list, tuple)):
        return ()
    curves: list[SketchCurve] = []
    for raw_curve in raw_curves:
        if not isinstance(raw_curve, dict):
            continue
        kind = raw_curve.get("kind")
        if kind == "circle":
            center = _point_from_object(raw_curve.get("center"))
            radius = _object_float(raw_curve.get("radius"))
            if center is None or radius is None:
                continue
            curve = circle_curve(center, radius)
        elif kind == "arc":
            start = _point_from_object(raw_curve.get("start"))
            end = _point_from_object(raw_curve.get("end"))
            bend = _point_from_object(raw_curve.get("bend"))
            center = _point_from_object(raw_curve.get("center"))
            radius = _object_float(raw_curve.get("radius"))
            ccw = bool(raw_curve.get("ccw", True))
            if start is None or end is None:
                continue
            if center is not None and radius is not None:
                curve = SketchCurve(
                    kind="arc",
                    start=_normalize_point(start),
                    end=_normalize_point(end),
                    center=_normalize_point(center),
                    radius=radius,
                    ccw=ccw,
                )
            elif bend is not None:
                curve = arc_curve(start, end, bend)
            else:
                continue
        else:
            continue
        if curve is not None:
            curves.append(curve)
    return tuple(curves)


def _arc_curve_from_meta(meta: dict[str, object]) -> SketchCurve | None:
    start_u = _meta_float(meta, "start_u")
    start_v = _meta_float(meta, "start_v")
    end_u = _meta_float(meta, "end_u")
    end_v = _meta_float(meta, "end_v")
    bend_u = _meta_float(meta, "bend_u")
    bend_v = _meta_float(meta, "bend_v")
    if (
        start_u is None
        or start_v is None
        or end_u is None
        or end_v is None
        or bend_u is None
        or bend_v is None
    ):
        return None
    return arc_curve((start_u, start_v), (end_u, end_v), (bend_u, bend_v))


def _curve_to_meta(curve: SketchCurve) -> dict[str, object] | None:
    if curve.kind == "circle":
        if curve.center is None or curve.radius is None:
            return None
        return {
            "kind": "circle",
            "center": _normalize_point(curve.center),
            "radius": float(curve.radius),
        }
    if curve.kind == "arc":
        if (
            curve.start is None
            or curve.end is None
            or curve.center is None
            or curve.radius is None
        ):
            return None
        edge = AtomicSketchSegment(
            start=curve.start,
            end=curve.end,
            source_item_id="meta",
            kind="arc",
            center=curve.center,
            radius=curve.radius,
            ccw=curve.ccw,
        )
        return _curve_spec_from_edge(edge)
    return None


def _curve_spec_from_edge(edge: AtomicSketchSegment) -> dict[str, object] | None:
    if edge.kind != "arc" or edge.center is None or edge.radius is None:
        return None
    return {
        "kind": "arc",
        "start": _normalize_point(edge.start),
        "end": _normalize_point(edge.end),
        "bend": _point_at_atomic(edge, 0.5),
        "center": _normalize_point(edge.center),
        "radius": float(edge.radius),
        "ccw": bool(edge.ccw),
    }


def _curve_valid(curve: SketchCurve) -> bool:
    if curve.kind == "line":
        return (
            curve.start is not None
            and curve.end is not None
            and _distance(curve.start, curve.end) > EPSILON
        )
    if curve.kind == "circle":
        return (
            curve.center is not None
            and curve.radius is not None
            and curve.radius > EPSILON
        )
    if curve.kind == "arc":
        return (
            curve.start is not None
            and curve.end is not None
            and curve.center is not None
            and curve.radius is not None
            and curve.radius > EPSILON
            and _distance(curve.start, curve.end) > EPSILON
        )
    return False


def _initial_split_parameters(curve: SketchCurve) -> list[float]:
    if curve.kind == "circle":
        return []
    return [0.0, 1.0]


def _split_curve(
    item_ids: tuple[str, ...],
    curve: SketchCurve,
    parameters: list[float],
) -> tuple[AtomicSketchSegment, ...]:
    item_id = item_ids[0] if item_ids else ""
    if curve.kind == "circle":
        sorted_parameters = _unique_sorted_cycle(parameters)
        if len(sorted_parameters) < 2:
            return ()
        segments: list[AtomicSketchSegment] = []
        wrapped = [*sorted_parameters, sorted_parameters[0] + 1.0]
        for start_t, end_t in zip(wrapped, wrapped[1:]):
            if end_t - start_t <= EPSILON:
                continue
            segment = _atomic_from_curve_slice(item_id, curve, start_t, end_t)
            if segment is not None:
                segments.append(_with_source_item_ids(segment, item_ids))
        return tuple(segments)

    sorted_parameters = _unique_sorted(parameters)
    segments = []
    for start_t, end_t in zip(sorted_parameters, sorted_parameters[1:]):
        if end_t - start_t <= EPSILON:
            continue
        segment = _atomic_from_curve_slice(item_id, curve, start_t, end_t)
        if segment is not None:
            segments.append(_with_source_item_ids(segment, item_ids))
    return tuple(segments)


def _fallback_source_loops(
    sources: tuple[SketchGraphSource, ...] | list[SketchGraphSource],
    remaining: list[AtomicSketchSegment],
    removed: AtomicSketchSegment,
) -> tuple[tuple[AtomicSketchSegment, ...], ...]:
    removed_source_ids = set(_edge_source_item_ids(removed))
    remaining_source_ids = {
        item_id for edge in remaining for item_id in _edge_source_item_ids(edge)
    }
    loops: list[tuple[AtomicSketchSegment, ...]] = []
    for source in sources:
        if source.item_id in removed_source_ids:
            continue
        if source.item_id not in remaining_source_ids:
            continue
        loop = _source_line_loop(source)
        if loop:
            loops.append(loop)
    return tuple(loops)


def _source_line_loop(
    source: SketchGraphSource,
) -> tuple[AtomicSketchSegment, ...]:
    remaining = [
        _normalize_segment(segment)
        for segment in source.segments
        if _distance(*_normalize_segment(segment)) > EPSILON
    ]
    if len(remaining) < 3:
        return ()

    first = remaining.pop(0)
    ordered = [first]
    current = first[1]
    while remaining:
        match_index = None
        next_segment = None
        for index, candidate in enumerate(remaining):
            if _same_point(candidate[0], current):
                match_index = index
                next_segment = candidate
                break
            if _same_point(candidate[1], current):
                match_index = index
                next_segment = (candidate[1], candidate[0])
                break
        if match_index is None or next_segment is None:
            return ()
        ordered.append(next_segment)
        current = next_segment[1]
        remaining.pop(match_index)

    if not _same_point(current, ordered[0][0]):
        return ()

    loop = tuple(
        AtomicSketchSegment(
            start=segment[0],
            end=segment[1],
            source_item_id=source.item_id,
            source_item_ids=(source.item_id,),
        )
        for segment in ordered
    )
    if _sampled_loop_area(list(loop)) < 0.0:
        return tuple(_reverse_atomic(edge) for edge in reversed(loop))
    return loop


def _heal_curve_records(records: list[_CurveRecord]) -> list[_CurveRecord]:
    records = _dedupe_curve_records(records)
    changed = True
    while changed:
        changed = False
        endpoint_degrees = _curve_endpoint_degrees(records)
        for first_index, first in enumerate(records):
            for second_index in range(first_index + 1, len(records)):
                merged = _merge_curve_records(
                    first,
                    records[second_index],
                    endpoint_degrees,
                )
                if merged is None:
                    continue
                records = [
                    record
                    for index, record in enumerate(records)
                    if index not in {first_index, second_index}
                ]
                records.append(merged)
                records = _dedupe_curve_records(records)
                changed = True
                break
            if changed:
                break
    return records


def _dedupe_curve_records(records: list[_CurveRecord]) -> list[_CurveRecord]:
    by_key: dict[tuple[object, ...], _CurveRecord] = {}
    for record in records:
        key = _curve_record_key(record.curve)
        if key is None:
            continue
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = record
            continue
        by_key[key] = _CurveRecord(
            _merge_source_item_ids(existing.item_ids, record.item_ids),
            existing.curve,
        )
    return list(by_key.values())


def _curve_endpoint_degrees(records: list[_CurveRecord]) -> dict[PointUV, int]:
    degrees: dict[PointUV, int] = {}
    for record in records:
        endpoints = _curve_endpoints(record.curve)
        if endpoints is None:
            continue
        for point in endpoints:
            normalized = _normalize_point(point)
            degrees[normalized] = degrees.get(normalized, 0) + 1
    return degrees


def _merge_curve_records(
    first: _CurveRecord,
    second: _CurveRecord,
    endpoint_degrees: dict[PointUV, int],
) -> _CurveRecord | None:
    first_endpoints = _curve_endpoints(first.curve)
    second_endpoints = _curve_endpoints(second.curve)
    if first_endpoints is None or second_endpoints is None:
        return None
    shared = {_normalize_point(point) for point in first_endpoints}.intersection(
        _normalize_point(point) for point in second_endpoints
    )
    if len(shared) == 1:
        shared_point = next(iter(shared))
    elif len(shared) == 2 and first.curve.kind == "arc" and second.curve.kind == "arc":
        if any(endpoint_degrees.get(point, 0) != 2 for point in shared):
            return None
        shared_point = next(iter(shared))
    else:
        return None
    if endpoint_degrees.get(shared_point, 0) != 2:
        return None
    if first.curve.kind == "line" and second.curve.kind == "line":
        merged_curve = _merge_line_curves(first.curve, second.curve, shared_point)
    elif first.curve.kind == "arc" and second.curve.kind == "arc":
        merged_curve = _merge_arc_curves(first.curve, second.curve, shared_point)
    else:
        return None
    if merged_curve is None:
        return None
    return _CurveRecord(
        _merge_source_item_ids(first.item_ids, second.item_ids),
        merged_curve,
    )


def _merge_line_curves(
    first: SketchCurve,
    second: SketchCurve,
    shared_point: PointUV,
) -> SketchCurve | None:
    if (
        first.start is None
        or first.end is None
        or second.start is None
        or second.end is None
    ):
        return None
    first_other = first.end if _same_point(first.start, shared_point) else first.start
    second_other = (
        second.end if _same_point(second.start, shared_point) else second.start
    )
    first_vector = (
        first_other[0] - shared_point[0],
        first_other[1] - shared_point[1],
    )
    second_vector = (
        second_other[0] - shared_point[0],
        second_other[1] - shared_point[1],
    )
    if abs(_cross(first_vector, second_vector)) > INTERSECTION_EPSILON:
        return None
    if _distance(first_other, second_other) <= EPSILON:
        return None
    return SketchCurve(
        kind="line",
        start=_normalize_point(first_other),
        end=_normalize_point(second_other),
    )


def _merge_arc_curves(
    first: SketchCurve,
    second: SketchCurve,
    shared_point: PointUV,
) -> SketchCurve | None:
    if (
        first.center is None
        or first.radius is None
        or first.start is None
        or first.end is None
        or second.center is None
        or second.radius is None
        or second.start is None
        or second.end is None
    ):
        return None
    if not _same_point(first.center, second.center):
        return None
    if abs(first.radius - second.radius) > INTERSECTION_EPSILON:
        return None

    for left in (first, _reverse_curve(first)):
        for right in (second, _reverse_curve(second)):
            if left.ccw != right.ccw:
                continue
            if not _same_point(left.end, shared_point):
                continue
            if not _same_point(right.start, shared_point):
                continue
            span = _arc_span(left) + _arc_span(right)
            if span >= TAU - INTERSECTION_EPSILON:
                return circle_curve(left.center, left.radius)
            if _distance(left.start, right.end) <= EPSILON:
                continue
            return SketchCurve(
                kind="arc",
                start=_normalize_point(left.start),
                end=_normalize_point(right.end),
                center=_normalize_point(left.center),
                radius=left.radius,
                ccw=left.ccw,
            )
    return None


def _curve_endpoints(curve: SketchCurve) -> tuple[PointUV, PointUV] | None:
    if curve.kind not in {"line", "arc"}:
        return None
    if curve.start is None or curve.end is None:
        return None
    return _normalize_point(curve.start), _normalize_point(curve.end)


def _curve_record_key(curve: SketchCurve) -> tuple[object, ...] | None:
    if curve.kind == "line":
        if curve.start is None or curve.end is None:
            return None
        return ("line", *_segment_key(curve.start, curve.end))
    if curve.kind == "circle":
        if curve.center is None or curve.radius is None:
            return None
        return (
            "circle",
            _normalize_point(curve.center),
            round(float(curve.radius), POINT_PRECISION),
        )
    if curve.kind == "arc":
        if (
            curve.start is None
            or curve.end is None
            or curve.center is None
            or curve.radius is None
        ):
            return None
        return _atomic_geometry_key(
            AtomicSketchSegment(
                start=curve.start,
                end=curve.end,
                source_item_id="",
                kind="arc",
                center=curve.center,
                radius=curve.radius,
                ccw=curve.ccw,
            )
        )
    return None


def _reverse_curve(curve: SketchCurve) -> SketchCurve:
    if curve.kind == "line":
        return SketchCurve(kind="line", start=curve.end, end=curve.start)
    if curve.kind == "arc":
        return SketchCurve(
            kind="arc",
            start=curve.end,
            end=curve.start,
            center=curve.center,
            radius=curve.radius,
            ccw=not curve.ccw,
        )
    return curve


def _merge_source_item_ids(
    first: tuple[str, ...],
    second: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*first, *second)))


def _with_source_item_ids(
    segment: AtomicSketchSegment,
    item_ids: tuple[str, ...],
) -> AtomicSketchSegment:
    return AtomicSketchSegment(
        start=segment.start,
        end=segment.end,
        source_item_id=segment.source_item_id,
        kind=segment.kind,
        center=segment.center,
        radius=segment.radius,
        ccw=segment.ccw,
        source_item_ids=item_ids,
    )


def _atomic_from_curve_slice(
    item_id: str,
    curve: SketchCurve,
    start_t: float,
    end_t: float,
) -> AtomicSketchSegment | None:
    start = _point_at_curve_parameter(curve, start_t)
    end = _point_at_curve_parameter(curve, end_t)
    if _distance(start, end) <= EPSILON:
        return None
    if curve.kind == "line":
        return AtomicSketchSegment(start, end, item_id)
    if curve.kind in {"arc", "circle"}:
        return AtomicSketchSegment(
            start=start,
            end=end,
            source_item_id=item_id,
            kind="arc",
            center=curve.center,
            radius=curve.radius,
            ccw=curve.ccw if curve.kind == "arc" else True,
        )
    return None


def _curve_intersections(
    first: SketchCurve,
    second: SketchCurve,
) -> tuple[tuple[float, float], ...]:
    if first.kind == "line" and second.kind == "line":
        if (
            first.start is None
            or first.end is None
            or second.start is None
            or second.end is None
        ):
            return ()
        parameters = _segment_intersection_parameters(
            (first.start, first.end),
            (second.start, second.end),
        )
        return (parameters,) if parameters is not None else ()
    if first.kind == "line" and _is_circle_like(second):
        return _line_curve_intersections(first, second)
    if second.kind == "line" and _is_circle_like(first):
        return tuple(
            (curve_t, line_t)
            for line_t, curve_t in _line_curve_intersections(second, first)
        )
    if _is_circle_like(first) and _is_circle_like(second):
        return _circle_curve_intersections(first, second)
    return ()


def _line_curve_intersections(
    line: SketchCurve,
    curve: SketchCurve,
) -> tuple[tuple[float, float], ...]:
    if (
        line.start is None
        or line.end is None
        or curve.center is None
        or curve.radius is None
    ):
        return ()
    sx, sy = line.start
    ex, ey = line.end
    dx = ex - sx
    dy = ey - sy
    fx = sx - curve.center[0]
    fy = sy - curve.center[1]
    a = dx * dx + dy * dy
    if a <= EPSILON:
        return ()
    b = 2.0 * (fx * dx + fy * dy)
    c = fx * fx + fy * fy - curve.radius * curve.radius
    discriminant = b * b - 4.0 * a * c
    if discriminant < -INTERSECTION_EPSILON:
        return ()
    discriminant_sqrt = sqrt(max(discriminant, 0.0))
    roots = (
        (-b / (2.0 * a),)
        if abs(discriminant) <= INTERSECTION_EPSILON
        else (
            (-b - discriminant_sqrt) / (2.0 * a),
            (-b + discriminant_sqrt) / (2.0 * a),
        )
    )
    intersections: list[tuple[float, float]] = []
    for line_t in roots:
        if line_t < -INTERSECTION_EPSILON or line_t > 1.0 + INTERSECTION_EPSILON:
            continue
        line_t = _clamp01(line_t)
        point = _point_at((line.start, line.end), line_t)
        curve_t = _curve_parameter_at_point(curve, point)
        if curve_t is not None:
            intersections.append((line_t, curve_t))
    return tuple(_unique_intersections(intersections))


def _circle_curve_intersections(
    first: SketchCurve,
    second: SketchCurve,
) -> tuple[tuple[float, float], ...]:
    if (
        first.center is None
        or first.radius is None
        or second.center is None
        or second.radius is None
    ):
        return ()
    points = _circle_circle_intersection_points(
        first.center,
        first.radius,
        second.center,
        second.radius,
    )
    intersections: list[tuple[float, float]] = []
    for point in points:
        first_t = _curve_parameter_at_point(first, point)
        second_t = _curve_parameter_at_point(second, point)
        if first_t is not None and second_t is not None:
            intersections.append((first_t, second_t))
    return tuple(_unique_intersections(intersections))


def _circle_circle_intersection_points(
    first_center: PointUV,
    first_radius: float,
    second_center: PointUV,
    second_radius: float,
) -> tuple[PointUV, ...]:
    dx = second_center[0] - first_center[0]
    dy = second_center[1] - first_center[1]
    distance = hypot(dx, dy)
    if distance <= INTERSECTION_EPSILON:
        return ()
    if distance > first_radius + second_radius + INTERSECTION_EPSILON:
        return ()
    if distance < abs(first_radius - second_radius) - INTERSECTION_EPSILON:
        return ()
    a = (
        first_radius * first_radius
        - second_radius * second_radius
        + distance * distance
    ) / (2.0 * distance)
    h_sq = first_radius * first_radius - a * a
    if h_sq < -INTERSECTION_EPSILON:
        return ()
    h = sqrt(max(h_sq, 0.0))
    mid_x = first_center[0] + a * dx / distance
    mid_y = first_center[1] + a * dy / distance
    rx = -dy * h / distance
    ry = dx * h / distance
    first = _normalize_point((mid_x + rx, mid_y + ry))
    second = _normalize_point((mid_x - rx, mid_y - ry))
    if _distance(first, second) <= INTERSECTION_EPSILON:
        return (first,)
    return first, second


def _connected_component(
    segments: tuple[AtomicSketchSegment, ...],
    seed: AtomicSketchSegment,
) -> tuple[AtomicSketchSegment, ...]:
    seed_key = _atomic_geometry_key(seed)
    edge_by_key = {_atomic_geometry_key(segment): segment for segment in segments}
    vertex_edges: dict[PointUV, set[tuple[object, ...]]] = {}
    for segment in segments:
        key = _atomic_geometry_key(segment)
        vertex_edges.setdefault(_normalize_point(segment.start), set()).add(key)
        vertex_edges.setdefault(_normalize_point(segment.end), set()).add(key)

    seen: set[tuple[object, ...]] = set()
    pending = [seed_key]
    while pending:
        key = pending.pop()
        if key in seen:
            continue
        seen.add(key)
        segment = edge_by_key.get(key)
        if segment is None:
            continue
        for vertex in (_normalize_point(segment.start), _normalize_point(segment.end)):
            pending.extend(vertex_edges.get(vertex, set()) - seen)
    return tuple(
        segment for segment in segments if _atomic_geometry_key(segment) in seen
    )


def _positive_face_loops(
    segments: tuple[AtomicSketchSegment, ...] | list[AtomicSketchSegment],
) -> tuple[tuple[AtomicSketchSegment, ...], ...]:
    outgoing: dict[PointUV, list[AtomicSketchSegment]] = {}
    for segment in segments:
        normalized = _normalize_atomic(segment)
        outgoing.setdefault(normalized.start, []).append(normalized)
        outgoing.setdefault(normalized.end, []).append(_reverse_atomic(normalized))
    if not outgoing:
        return ()

    for point, edges in outgoing.items():
        outgoing[point] = sorted(edges, key=_outgoing_angle)

    visited: set[tuple[object, ...]] = set()
    loops: list[tuple[AtomicSketchSegment, ...]] = []
    loop_keys: set[tuple[tuple[object, ...], ...]] = set()
    edge_count = sum(len(edges) for edges in outgoing.values())
    for edges in outgoing.values():
        for edge in edges:
            edge_key = _directed_edge_key(edge)
            if edge_key in visited:
                continue
            face: list[AtomicSketchSegment] = []
            current = edge
            for _step in range(edge_count * 2 + 4):
                current_key = _directed_edge_key(current)
                if current_key in visited:
                    break
                visited.add(current_key)
                face.append(current)
                neighbors = outgoing.get(current.end, [])
                reverse_key = _directed_edge_key(_reverse_atomic(current))
                try:
                    back_index = next(
                        index
                        for index, neighbor in enumerate(neighbors)
                        if _directed_edge_key(neighbor) == reverse_key
                    )
                except StopIteration:
                    break
                current = neighbors[(back_index - 1) % len(neighbors)]
                if _directed_edge_key(current) == edge_key:
                    if len(face) >= 2 and _sampled_loop_area(face) > EPSILON:
                        key = _loop_edges_key(face)
                        if key not in loop_keys:
                            loop_keys.add(key)
                            loops.append(tuple(face))
                    break
    return tuple(loops)


def _normalize_atomic(edge: AtomicSketchSegment) -> AtomicSketchSegment:
    return AtomicSketchSegment(
        start=_normalize_point(edge.start),
        end=_normalize_point(edge.end),
        source_item_id=edge.source_item_id,
        kind=edge.kind,
        center=_normalize_point(edge.center) if edge.center is not None else None,
        radius=float(edge.radius) if edge.radius is not None else None,
        ccw=edge.ccw,
        source_item_ids=edge.source_item_ids,
    )


def _reverse_atomic(edge: AtomicSketchSegment) -> AtomicSketchSegment:
    return AtomicSketchSegment(
        start=edge.end,
        end=edge.start,
        source_item_id=edge.source_item_id,
        kind=edge.kind,
        center=edge.center,
        radius=edge.radius,
        ccw=not edge.ccw if edge.kind == "arc" else edge.ccw,
        source_item_ids=edge.source_item_ids,
    )


def _edge_source_item_ids(edge: AtomicSketchSegment) -> tuple[str, ...]:
    return edge.source_item_ids or (edge.source_item_id,)


def _trim_target_sources(
    sources: tuple[SketchGraphSource, ...] | list[SketchGraphSource],
    edge: AtomicSketchSegment,
) -> tuple[SketchGraphSource, ...]:
    source_ids = _atomic_segment_owner_ids(sources, edge)
    if not source_ids:
        return ()
    return tuple(source for source in sources if source.item_id in source_ids)


def _atomic_segment_owner_ids(
    sources: tuple[SketchGraphSource, ...] | list[SketchGraphSource],
    edge: AtomicSketchSegment,
) -> tuple[str, ...]:
    contained = tuple(
        source.item_id
        for source in sources
        if _source_contains_atomic_segment(source, edge)
    )
    if contained:
        return contained
    fallback = edge.source_item_id or next(iter(edge.source_item_ids), "")
    return (fallback,) if fallback else ()


def _source_contains_atomic_segment(
    source: SketchGraphSource,
    edge: AtomicSketchSegment,
) -> bool:
    points = tuple(
        _point_at_atomic(edge, parameter) for parameter in (0.0, 0.25, 0.5, 0.75, 1.0)
    )
    return all(_source_contains_atomic_point(source, edge, point) for point in points)


def _source_contains_atomic_point(
    source: SketchGraphSource,
    edge: AtomicSketchSegment,
    point: PointUV,
) -> bool:
    if edge.kind == "line":
        for segment in source.segments:
            start, end = _normalize_segment(segment)
            if _point_segment_distance(point, start, end) <= INTERSECTION_EPSILON:
                return True
        return any(_curve_contains_point(curve, point) for curve in source.curves)
    return any(
        _curve_contains_point(curve, point, edge=edge) for curve in source.curves
    )


def _curve_contains_point(
    curve: SketchCurve,
    point: PointUV,
    *,
    edge: AtomicSketchSegment | None = None,
) -> bool:
    if edge is not None and (
        curve.center is None
        or curve.radius is None
        or edge.center is None
        or edge.radius is None
        or not _same_point(curve.center, edge.center)
        or abs(curve.radius - edge.radius) > INTERSECTION_EPSILON
    ):
        return False
    return _curve_parameter_at_point(curve, point) is not None


def _retarget_atomic_source(
    edge: AtomicSketchSegment,
    source_item_id: str,
) -> AtomicSketchSegment:
    return AtomicSketchSegment(
        start=edge.start,
        end=edge.end,
        source_item_id=source_item_id,
        kind=edge.kind,
        center=edge.center,
        radius=edge.radius,
        ccw=edge.ccw,
        source_item_ids=(source_item_id,),
    )


def _directed_edge_key(edge: AtomicSketchSegment) -> tuple[object, ...]:
    return (
        _normalize_point(edge.start),
        _normalize_point(edge.end),
        *_edge_shape_key(edge),
    )


def _atomic_geometry_key(edge: AtomicSketchSegment) -> tuple[object, ...]:
    if edge.kind == "line":
        return ("line", *_segment_key(edge.start, edge.end))
    return (
        "arc",
        *_segment_key(edge.start, edge.end),
        _normalize_point(edge.center) if edge.center is not None else None,
        round(float(edge.radius or 0.0), POINT_PRECISION),
        _point_at_atomic(edge, 0.5),
    )


def _edge_shape_key(edge: AtomicSketchSegment) -> tuple[object, ...]:
    if edge.kind == "line":
        return ("line",)
    return (
        "arc",
        _normalize_point(edge.center) if edge.center is not None else None,
        round(float(edge.radius or 0.0), POINT_PRECISION),
        _point_at_atomic(edge, 0.5),
    )


def _loop_edges_key(
    edges: tuple[AtomicSketchSegment, ...] | list[AtomicSketchSegment],
) -> tuple[tuple[object, ...], ...]:
    keys = tuple(_atomic_geometry_key(edge) for edge in edges)
    rotations = [keys[index:] + keys[:index] for index in range(len(keys))]
    reversed_keys = tuple(reversed(keys))
    rotations.extend(
        reversed_keys[index:] + reversed_keys[:index] for index in range(len(keys))
    )
    return min(rotations)


def _outgoing_angle(edge: AtomicSketchSegment) -> float:
    if edge.kind == "arc" and edge.center is not None:
        radial = _angle_from(edge.center, edge.start)
        return radial + pi / 2.0 if edge.ccw else radial - pi / 2.0
    return atan2(edge.end[1] - edge.start[1], edge.end[0] - edge.start[0])


def _sampled_loop_area(edges: list[AtomicSketchSegment]) -> float:
    points: list[PointUV] = []
    for edge in edges:
        if not points:
            points.append(edge.start)
        sample_count = 8 if edge.kind == "arc" else 1
        for index in range(1, sample_count + 1):
            points.append(_point_at_atomic(edge, index / sample_count))
    return _polygon_area(points)


def _segment_intersection_parameters(
    first: SegmentUV,
    second: SegmentUV,
) -> tuple[float, float] | None:
    p = first[0]
    r = (first[1][0] - first[0][0], first[1][1] - first[0][1])
    q = second[0]
    s = (second[1][0] - second[0][0], second[1][1] - second[0][1])
    denominator = _cross(r, s)
    if abs(denominator) <= EPSILON:
        return None
    qp = (q[0] - p[0], q[1] - p[1])
    first_t = _cross(qp, s) / denominator
    second_t = _cross(qp, r) / denominator
    if -EPSILON <= first_t <= 1.0 + EPSILON and -EPSILON <= second_t <= 1.0 + EPSILON:
        return _clamp01(first_t), _clamp01(second_t)
    return None


def _point_atomic_distance(point: PointUV, edge: AtomicSketchSegment) -> float:
    if edge.kind == "line":
        return _point_segment_distance(point, edge.start, edge.end)
    if edge.center is None or edge.radius is None:
        return min(_distance(point, edge.start), _distance(point, edge.end))
    point_angle = _angle_from(edge.center, point)
    curve = SketchCurve(
        kind="arc",
        start=edge.start,
        end=edge.end,
        center=edge.center,
        radius=edge.radius,
        ccw=edge.ccw,
    )
    if _curve_parameter_at_angle(curve, point_angle) is not None:
        radial_distance = _distance(point, edge.center)
        return abs(radial_distance - edge.radius)
    return min(_distance(point, edge.start), _distance(point, edge.end))


def _point_segment_distance(point: PointUV, start: PointUV, end: PointUV) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= EPSILON:
        return _distance(point, start)
    t = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq
    t = _clamp01(t)
    closest = (start[0] + dx * t, start[1] + dy * t)
    return _distance(point, closest)


def _point_at(segment: SegmentUV, parameter: float) -> PointUV:
    start, end = segment
    return _normalize_point(
        (
            start[0] + (end[0] - start[0]) * parameter,
            start[1] + (end[1] - start[1]) * parameter,
        )
    )


def _point_at_curve_parameter(curve: SketchCurve, parameter: float) -> PointUV:
    if curve.kind == "line":
        if curve.start is None or curve.end is None:
            return (0.0, 0.0)
        return _point_at((curve.start, curve.end), parameter)
    if curve.center is None or curve.radius is None:
        return (0.0, 0.0)
    if curve.kind == "circle":
        angle = _normalize_angle(parameter * TAU)
    else:
        if curve.start is None or curve.end is None:
            return (0.0, 0.0)
        start_angle = _angle_from(curve.center, curve.start)
        span = _arc_span(curve)
        angle = (
            start_angle + span * parameter
            if curve.ccw
            else start_angle - span * parameter
        )
    return _normalize_point(
        (
            curve.center[0] + cos(angle) * curve.radius,
            curve.center[1] + sin(angle) * curve.radius,
        )
    )


def _point_at_atomic(edge: AtomicSketchSegment, parameter: float) -> PointUV:
    if edge.kind == "line":
        return _point_at((edge.start, edge.end), parameter)
    return _point_at_curve_parameter(
        SketchCurve(
            kind="arc",
            start=edge.start,
            end=edge.end,
            center=edge.center,
            radius=edge.radius,
            ccw=edge.ccw,
        ),
        parameter,
    )


def _curve_parameter_at_point(curve: SketchCurve, point: PointUV) -> float | None:
    if curve.kind == "line":
        if curve.start is None or curve.end is None:
            return None
        length = _distance(curve.start, curve.end)
        if length <= EPSILON:
            return None
        t = _distance(curve.start, point) / length
        if (
            _point_segment_distance(point, curve.start, curve.end)
            <= INTERSECTION_EPSILON
        ):
            return _clamp01(t)
        return None
    if curve.center is None or curve.radius is None:
        return None
    if abs(_distance(curve.center, point) - curve.radius) > INTERSECTION_EPSILON:
        return None
    angle = _angle_from(curve.center, point)
    if curve.kind == "circle":
        return _normalize_angle(angle) / TAU
    return _curve_parameter_at_angle(curve, angle)


def _curve_parameter_at_angle(curve: SketchCurve, angle: float) -> float | None:
    if curve.center is None or curve.start is None or curve.end is None:
        return None
    start_angle = _angle_from(curve.center, curve.start)
    span = _arc_span(curve)
    if span <= EPSILON:
        return None
    delta = (
        _normalize_angle(angle - start_angle)
        if curve.ccw
        else _normalize_angle(start_angle - angle)
    )
    if delta > span + INTERSECTION_EPSILON:
        return None
    return _clamp01(delta / span)


def _arc_span(curve: SketchCurve) -> float:
    if curve.center is None or curve.start is None or curve.end is None:
        return 0.0
    start_angle = _angle_from(curve.center, curve.start)
    end_angle = _angle_from(curve.center, curve.end)
    return (
        _normalize_angle(end_angle - start_angle)
        if curve.ccw
        else _normalize_angle(start_angle - end_angle)
    )


def _unique_sorted(values: list[float]) -> list[float]:
    sorted_values = sorted(_clamp01(value) for value in values)
    unique: list[float] = []
    for value in sorted_values:
        if not unique or abs(unique[-1] - value) > EPSILON:
            unique.append(value)
    return unique


def _unique_sorted_cycle(values: list[float]) -> list[float]:
    sorted_values = sorted(_normalize_cycle_parameter(value) for value in values)
    unique: list[float] = []
    for value in sorted_values:
        if not unique or abs(unique[-1] - value) > EPSILON:
            unique.append(value)
    if len(unique) > 1 and abs((unique[0] + 1.0) - unique[-1]) <= EPSILON:
        unique.pop()
    return unique


def _unique_intersections(
    intersections: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    unique: list[tuple[float, float]] = []
    for first, second in intersections:
        normalized = (_clamp01(first), _clamp01(second))
        if any(
            abs(existing[0] - normalized[0]) <= EPSILON
            and abs(existing[1] - normalized[1]) <= EPSILON
            for existing in unique
        ):
            continue
        unique.append(normalized)
    return unique


def _segment_key(start: PointUV, end: PointUV) -> tuple[PointUV, PointUV]:
    first = _normalize_point(start)
    second = _normalize_point(end)
    return (first, second) if first <= second else (second, first)


def _normalize_segment(segment: SegmentUV) -> SegmentUV:
    return _normalize_point(segment[0]), _normalize_point(segment[1])


def _normalize_point(point: PointUV) -> PointUV:
    return (
        round(float(point[0]), POINT_PRECISION),
        round(float(point[1]), POINT_PRECISION),
    )


def _normalize_angle(angle: float) -> float:
    return angle % TAU


def _normalize_cycle_parameter(value: float) -> float:
    normalized = value % 1.0
    return 0.0 if abs(normalized - 1.0) <= EPSILON else normalized


def _point_from_object(value: object) -> PointUV | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        return float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None


def _uv_from_workplane_point(workplane: Workplane, point: Any) -> PointUV:
    relative = (
        point.X() - workplane.origin.X(),
        point.Y() - workplane.origin.Y(),
        point.Z() - workplane.origin.Z(),
    )
    x_direction = (
        workplane.x_direction.X(),
        workplane.x_direction.Y(),
        workplane.x_direction.Z(),
    )
    y_direction = (
        workplane.y_direction.X(),
        workplane.y_direction.Y(),
        workplane.y_direction.Z(),
    )
    return (
        _dot(relative, x_direction),
        _dot(relative, y_direction),
    )


def _meta_float(meta: dict[str, object], key: str) -> float | None:
    return _object_float(meta.get(key))


def _object_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _distance(first: PointUV, second: PointUV) -> float:
    return hypot(first[0] - second[0], first[1] - second[1])


def _same_point(first: PointUV, second: PointUV) -> bool:
    return _distance(first, second) <= INTERSECTION_EPSILON


def _polygon_area(points: list[PointUV]) -> float:
    area = 0.0
    for first, second in zip(points, (*points[1:], points[0])):
        area += first[0] * second[1] - second[0] * first[1]
    return area / 2.0


def _cross(first: PointUV, second: PointUV) -> float:
    return first[0] * second[1] - first[1] * second[0]


def _dot(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> float:
    return first[0] * second[0] + first[1] * second[1] + first[2] * second[2]


def _clamp01(value: float) -> float:
    return min(max(value, 0.0), 1.0)


def _is_circle_like(curve: SketchCurve) -> bool:
    return curve.kind in {"arc", "circle"}


def _angle_from(center: PointUV, point: PointUV) -> float:
    return atan2(point[1] - center[1], point[0] - center[0])


def _angle_on_ccw_span(start_angle: float, end_angle: float, angle: float) -> bool:
    return _normalize_angle(angle - start_angle) <= _normalize_angle(
        end_angle - start_angle
    )


def _circumcenter(first: PointUV, second: PointUV, third: PointUV) -> PointUV | None:
    ax, ay = first
    bx, by = second
    cx, cy = third
    denominator = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(denominator) <= EPSILON:
        return None
    ux = (
        (ax * ax + ay * ay) * (by - cy)
        + (bx * bx + by * by) * (cy - ay)
        + (cx * cx + cy * cy) * (ay - by)
    ) / denominator
    uy = (
        (ax * ax + ay * ay) * (cx - bx)
        + (bx * bx + by * by) * (ax - cx)
        + (cx * cx + cy * cy) * (bx - ax)
    ) / denominator
    return ux, uy
