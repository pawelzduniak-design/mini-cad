"""Planar sketch profiles backed by real OCCT topology."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from cad_app import sketch_regions
from cad_app.commands import (
    CommandError,
    UnsupportedTopologyError,
    cleanup_shape,
    validate_shape,
)
from cad_app.workplane import Workplane

if TYPE_CHECKING:
    from OCP.TopoDS import TopoDS_Face, TopoDS_Shape


SKETCH_META_KIND = "sketch_profile"
SKETCH_ENTITY_META_KIND = "sketch_entity"
ProfileRegionSplit = sketch_regions.ProfileRegionSplit
split_profile_regions = sketch_regions.split_profile_regions
subtract_profile_regions = sketch_regions.subtract_profile_regions


def is_sketch_profile(meta: dict[str, object]) -> bool:
    """Return whether scene metadata describes a lightweight sketch profile."""
    return meta.get("kind") == SKETCH_META_KIND


def is_sketch_entity(meta: dict[str, object]) -> bool:
    """Return whether scene metadata describes open sketch construction geometry."""
    return meta.get("kind") == SKETCH_ENTITY_META_KIND


def is_sketch_object(meta: dict[str, object]) -> bool:
    """Return whether scene metadata describes any sketch-owned object."""
    return is_sketch_profile(meta) or is_sketch_entity(meta)


def make_rectangle_profile(
    workplane: Workplane,
    width: float = 60.0,
    height: float = 40.0,
) -> TopoDS_Face:
    """Create a closed planar rectangular face on a workplane."""
    if width <= 0 or height <= 0:
        raise ValueError("Rectangle profile dimensions must be positive.")

    return make_rectangle_profile_from_corners(
        workplane,
        (-width / 2.0, -height / 2.0),
        (width / 2.0, height / 2.0),
    )


def make_rectangle_profile_from_corners(
    workplane: Workplane,
    first: tuple[float, float],
    second: tuple[float, float],
) -> TopoDS_Face:
    """Create a rectangular sketch face from two local workplane corners."""
    if abs(first[0] - second[0]) < 1e-7 or abs(first[1] - second[1]) < 1e-7:
        raise ValueError("Rectangle profile needs non-zero width and height.")

    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon

    min_u = min(first[0], second[0])
    max_u = max(first[0], second[0])
    min_v = min(first[1], second[1])
    max_v = max(first[1], second[1])
    polygon = BRepBuilderAPI_MakePolygon()
    polygon.Add(_point_on_workplane(workplane, min_u, min_v))
    polygon.Add(_point_on_workplane(workplane, max_u, min_v))
    polygon.Add(_point_on_workplane(workplane, max_u, max_v))
    polygon.Add(_point_on_workplane(workplane, min_u, max_v))
    polygon.Close()
    if not polygon.IsDone():
        raise UnsupportedTopologyError("Rectangle profile wire could not be built.")

    face = BRepBuilderAPI_MakeFace(polygon.Wire(), True).Face()
    validate_shape(face)
    return face


def make_rectangle_with_circle_cutout_profile(
    workplane: Workplane,
    first: tuple[float, float],
    second: tuple[float, float],
    circle_center: tuple[float, float],
    circle_radius: float,
) -> TopoDS_Face:
    """Create one planar profile for a rectangle with a circular inner loop."""
    if abs(first[0] - second[0]) < 1e-7 or abs(first[1] - second[1]) < 1e-7:
        raise ValueError("Outer rectangle needs non-zero width and height.")
    if circle_radius <= 0:
        raise ValueError("Inner circle radius must be positive.")

    min_u = min(first[0], second[0])
    max_u = max(first[0], second[0])
    min_v = min(first[1], second[1])
    max_v = max(first[1], second[1])
    if (
        circle_center[0] - circle_radius <= min_u
        or circle_center[0] + circle_radius >= max_u
        or circle_center[1] - circle_radius <= min_v
        or circle_center[1] + circle_radius >= max_v
    ):
        raise ValueError("Inner circle must be fully inside the rectangle.")

    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace

    outer_wire = _rectangle_wire(workplane, (min_u, min_v), (max_u, max_v))
    inner_wire = _circle_wire(workplane, circle_center, circle_radius)
    inner_wire.Reverse()
    face_builder = BRepBuilderAPI_MakeFace(outer_wire, True)
    if not face_builder.IsDone():
        raise UnsupportedTopologyError("Outer rectangle wire could not be built.")
    face_builder.Add(inner_wire)

    face = face_builder.Face()
    validate_shape(face)
    return face


def add_circle_cutout_to_profile(
    profile_face: TopoDS_Face,
    workplane: Workplane,
    circle_center: tuple[float, float],
    circle_radius: float,
) -> TopoDS_Face:
    """Add a circular inner loop to an existing planar sketch profile."""
    if circle_radius <= 0:
        raise ValueError("Inner circle radius must be positive.")
    inner_profile = make_circle_profile_at(workplane, circle_center, circle_radius)
    return add_profile_cutout_to_profile(profile_face, inner_profile, workplane)


def add_profile_cutout_to_profile(
    profile_face: TopoDS_Face,
    inner_profile_face: TopoDS_Face,
    workplane: Workplane,
) -> TopoDS_Face:
    """Add any closed planar profile as an inner loop of another profile."""
    if not profile_contains_profile(profile_face, inner_profile_face, workplane):
        raise ValueError("Inner profile must be fully inside the profile.")

    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.BRepTools import BRepTools
    from OCP.TopAbs import TopAbs_WIRE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    outer_wire = BRepTools.OuterWire_s(profile_face)
    face_builder = BRepBuilderAPI_MakeFace(outer_wire, True)
    if not face_builder.IsDone():
        raise UnsupportedTopologyError("Existing profile outer wire could not be used.")

    wire_exp = TopExp_Explorer(profile_face, TopAbs_WIRE)
    while wire_exp.More():
        wire = TopoDS.Wire_s(wire_exp.Current())
        if not wire.IsSame(outer_wire):
            face_builder.Add(wire)
        wire_exp.Next()

    inner_wire = BRepTools.OuterWire_s(TopoDS.Face_s(inner_profile_face))
    inner_wire.Reverse()
    face_builder.Add(inner_wire)

    face = face_builder.Face()
    validate_shape(face)
    return face


def profile_contains_profile(
    profile_face: TopoDS_Face,
    inner_profile_face: TopoDS_Face,
    workplane: Workplane,
) -> bool:
    """Return whether one sketch profile lies inside another profile's material."""
    try:
        samples = _profile_sample_uvs(inner_profile_face, workplane)
    except (CommandError, ValueError):
        return False
    return bool(samples) and all(
        profile_contains_uv(profile_face, workplane, sample) for sample in samples
    )


def make_center_rectangle_profile(
    workplane: Workplane,
    center: tuple[float, float],
    corner: tuple[float, float],
) -> TopoDS_Face:
    """Create an axis-aligned rectangular face expanded from a center point."""
    width = abs(corner[0] - center[0]) * 2.0
    height = abs(corner[1] - center[1]) * 2.0
    if width < 1e-7 or height < 1e-7:
        raise ValueError("Center rectangle needs non-zero width and height.")
    return make_rectangle_profile_from_corners(
        workplane,
        (center[0] - width / 2.0, center[1] - height / 2.0),
        (center[0] + width / 2.0, center[1] + height / 2.0),
    )


def make_rectangle_profile_three_point(
    workplane: Workplane,
    first: tuple[float, float],
    second: tuple[float, float],
    third: tuple[float, float],
) -> TopoDS_Face:
    """Create a rotated rectangular face from base points and height point."""
    base_x = second[0] - first[0]
    base_y = second[1] - first[1]
    base_length = (base_x * base_x + base_y * base_y) ** 0.5
    if base_length < 1e-7:
        raise ValueError("3-point rectangle base length must be non-zero.")

    normal_x = -base_y / base_length
    normal_y = base_x / base_length
    height = (third[0] - first[0]) * normal_x + (third[1] - first[1]) * normal_y
    if abs(height) < 1e-7:
        raise ValueError("3-point rectangle height must be non-zero.")

    offset = (normal_x * height, normal_y * height)
    return make_polyline_profile(
        workplane,
        [
            first,
            second,
            (second[0] + offset[0], second[1] + offset[1]),
            (first[0] + offset[0], first[1] + offset[1]),
            first,
        ],
    )


def make_polyline_profile(
    workplane: Workplane,
    points: list[tuple[float, float]],
) -> TopoDS_Face:
    """Create a closed planar face from connected sketch line points."""
    if len(points) < 4:
        raise ValueError("Polyline profile needs at least three segments.")
    if not _same_uv(points[0], points[-1]):
        raise ValueError("Polyline profile must be closed.")

    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon

    polygon = BRepBuilderAPI_MakePolygon()
    for point in points[:-1]:
        polygon.Add(_point_on_workplane(workplane, point[0], point[1]))
    polygon.Close()
    if not polygon.IsDone():
        raise UnsupportedTopologyError("Polyline profile wire could not be built.")

    face = BRepBuilderAPI_MakeFace(polygon.Wire(), True).Face()
    validate_shape(face)
    return face


def make_polyline_preview(
    workplane: Workplane,
    points: list[tuple[float, float]],
):
    """Create passive preview geometry for connected sketch line points."""
    if len(points) < 2:
        raise ValueError("Polyline preview needs at least two points.")

    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.TopoDS import TopoDS_Compound

    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for start, end in zip(points, points[1:]):
        if _same_uv(start, end):
            continue
        edge_builder = BRepBuilderAPI_MakeEdge(
            _point_on_workplane(workplane, start[0], start[1]),
            _point_on_workplane(workplane, end[0], end[1]),
        )
        if edge_builder.IsDone():
            builder.Add(compound, edge_builder.Edge())
    validate_shape(compound)
    return compound


def make_curve_preview(
    workplane: Workplane,
    curve: dict[str, object],
):
    """Create passive preview geometry from a line or arc curve spec."""
    return make_curve_compound_preview(workplane, (curve,))


def make_curve_compound_preview(
    workplane: Workplane,
    curves: list[dict[str, object]] | tuple[dict[str, object], ...],
):
    """Create passive preview geometry from one or more curve specs."""
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    if not curves:
        raise ValueError("Curve preview needs at least one curve.")

    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for curve in curves:
        builder.Add(compound, _edge_from_curve_spec(workplane, curve))
    validate_shape(compound)
    return compound


def make_curve_loop_profile(
    workplane: Workplane,
    curves: list[dict[str, object]] | tuple[dict[str, object], ...],
) -> TopoDS_Face:
    """Create a closed planar face from connected line and arc curve specs."""
    if not curves:
        raise ValueError("Curve loop needs at least one edge.")

    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire

    wire_builder = BRepBuilderAPI_MakeWire()
    for curve in curves:
        wire_builder.Add(_edge_from_curve_spec(workplane, curve))
    if not wire_builder.IsDone():
        raise UnsupportedTopologyError("Curve loop wire could not be built.")

    face = BRepBuilderAPI_MakeFace(wire_builder.Wire(), True).Face()
    validate_shape(face)
    return face


def make_point_marker_preview(
    workplane: Workplane,
    uv: tuple[float, float],
    size: float = 2.5,
):
    """Create a small passive cross marker for a sketch point."""
    if size <= 0:
        raise ValueError("Point marker size must be positive.")

    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.TopoDS import TopoDS_Compound

    segments = (
        ((uv[0] - size, uv[1]), (uv[0] + size, uv[1])),
        ((uv[0], uv[1] - size), (uv[0], uv[1] + size)),
    )
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for start, end in segments:
        edge_builder = BRepBuilderAPI_MakeEdge(
            _point_on_workplane(workplane, start[0], start[1]),
            _point_on_workplane(workplane, end[0], end[1]),
        )
        if edge_builder.IsDone():
            builder.Add(compound, edge_builder.Edge())
    validate_shape(compound)
    return compound


def make_circle_profile(
    workplane: Workplane,
    radius: float = 20.0,
) -> TopoDS_Face:
    """Create a closed circular face on a workplane."""
    return make_circle_profile_at(workplane, (0.0, 0.0), radius)


def make_circle_profile_at(
    workplane: Workplane,
    center: tuple[float, float],
    radius: float = 20.0,
) -> TopoDS_Face:
    """Create a closed circular sketch face from local workplane center/radius."""
    if radius <= 0:
        raise ValueError("Circle profile radius must be positive.")

    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace

    face = BRepBuilderAPI_MakeFace(_circle_wire(workplane, center, radius), True).Face()
    validate_shape(face)
    return face


def make_three_point_arc_edge(
    workplane: Workplane,
    start: tuple[float, float],
    end: tuple[float, float],
    bend: tuple[float, float],
):
    """Create a 3-point arc edge on a workplane."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.GC import GC_MakeArcOfCircle

    if _same_uv(start, end) or _same_uv(start, bend) or _same_uv(end, bend):
        raise ValueError("Arc points must be distinct.")

    arc = GC_MakeArcOfCircle(
        _point_on_workplane(workplane, start[0], start[1]),
        _point_on_workplane(workplane, bend[0], bend[1]),
        _point_on_workplane(workplane, end[0], end[1]),
    )
    edge_builder = BRepBuilderAPI_MakeEdge(arc.Value())
    if not edge_builder.IsDone():
        raise UnsupportedTopologyError("3-point arc edge could not be built.")
    edge = edge_builder.Edge()
    validate_shape(edge)
    return edge


def make_arc_chord_profile(
    workplane: Workplane,
    start: tuple[float, float],
    end: tuple[float, float],
    bend: tuple[float, float],
) -> TopoDS_Face:
    """Create a closed face from a 3-point arc and a straight chord line."""
    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeEdge,
        BRepBuilderAPI_MakeFace,
        BRepBuilderAPI_MakeWire,
    )

    arc_edge = make_three_point_arc_edge(workplane, start, end, bend)
    chord_edge = BRepBuilderAPI_MakeEdge(
        _point_on_workplane(workplane, end[0], end[1]),
        _point_on_workplane(workplane, start[0], start[1]),
    ).Edge()
    wire_builder = BRepBuilderAPI_MakeWire()
    wire_builder.Add(arc_edge)
    wire_builder.Add(chord_edge)
    if not wire_builder.IsDone():
        raise UnsupportedTopologyError("Arc profile wire could not be built.")

    face = BRepBuilderAPI_MakeFace(wire_builder.Wire(), True).Face()
    validate_shape(face)
    return face


def make_arc_polyline_profile(
    workplane: Workplane,
    arc_start: tuple[float, float],
    arc_end: tuple[float, float],
    arc_bend: tuple[float, float],
    line_points: list[tuple[float, float]],
) -> TopoDS_Face:
    """Create a closed face from one arc and connected line segments."""
    if len(line_points) < 2:
        raise ValueError("Arc profile needs at least one line segment.")
    starts_at_arc_start = _same_uv(line_points[0], arc_start) and _same_uv(
        line_points[-1],
        arc_end,
    )
    starts_at_arc_end = _same_uv(line_points[0], arc_end) and _same_uv(
        line_points[-1],
        arc_start,
    )
    if not starts_at_arc_start and not starts_at_arc_end:
        raise ValueError("Line chain must connect both arc endpoints.")

    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeEdge,
        BRepBuilderAPI_MakeFace,
        BRepBuilderAPI_MakeWire,
    )

    wire_builder = BRepBuilderAPI_MakeWire()
    wire_builder.Add(make_three_point_arc_edge(workplane, arc_start, arc_end, arc_bend))
    boundary_points = (
        list(reversed(line_points)) if starts_at_arc_start else list(line_points)
    )
    for first, second in zip(boundary_points, boundary_points[1:]):
        if _same_uv(first, second):
            continue
        edge = BRepBuilderAPI_MakeEdge(
            _point_on_workplane(workplane, first[0], first[1]),
            _point_on_workplane(workplane, second[0], second[1]),
        ).Edge()
        wire_builder.Add(edge)
    if not wire_builder.IsDone():
        raise UnsupportedTopologyError("Arc-line profile wire could not be built.")

    face = BRepBuilderAPI_MakeFace(wire_builder.Wire(), True).Face()
    validate_shape(face)
    return face


def three_point_arc_radius(
    start: tuple[float, float],
    end: tuple[float, float],
    bend: tuple[float, float],
) -> float:
    """Return the circumradius for three 2D arc points."""
    ax, ay = start
    bx, by = bend
    cx, cy = end
    side_a = ((bx - cx) ** 2 + (by - cy) ** 2) ** 0.5
    side_b = ((ax - cx) ** 2 + (ay - cy) ** 2) ** 0.5
    side_c = ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
    area2 = abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax))
    if area2 < 1e-7:
        raise ValueError("Arc points must not be collinear.")
    return side_a * side_b * side_c / (2.0 * area2)


def is_closed_polyline(points: list[tuple[float, float]]) -> bool:
    """Return whether connected line points form a closed profile loop."""
    return len(points) >= 4 and _same_uv(points[0], points[-1])


def profile_contains_uv(
    profile_face: TopoDS_Face,
    workplane: Workplane,
    uv: tuple[float, float],
) -> bool:
    """Return whether a local sketch point lies inside or on a profile face."""
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON
    from OCP.TopoDS import TopoDS

    classifier = BRepClass_FaceClassifier()
    classifier.Perform(
        TopoDS.Face_s(profile_face),
        _point_on_workplane(workplane, uv[0], uv[1]),
        1e-7,
    )
    return classifier.State() in {TopAbs_IN, TopAbs_ON}


def _profile_sample_uvs(
    profile_face: TopoDS_Face,
    workplane: Workplane,
) -> list[tuple[float, float]]:
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepTools import BRepTools
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    face = TopoDS.Face_s(profile_face)
    samples: list[tuple[float, float]] = []
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    center = props.CentreOfMass()
    samples.append(_uv_from_workplane_point(workplane, center))

    outer_wire = BRepTools.OuterWire_s(face)
    edge_exp = TopExp_Explorer(outer_wire, TopAbs_EDGE)
    while edge_exp.More():
        curve = BRepAdaptor_Curve(TopoDS.Edge_s(edge_exp.Current()))
        first = float(curve.FirstParameter())
        last = float(curve.LastParameter())
        if math.isfinite(first) and math.isfinite(last):
            for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
                parameter = first + (last - first) * fraction
                samples.append(
                    _uv_from_workplane_point(workplane, curve.Value(parameter))
                )
        edge_exp.Next()
    return samples


def extrude_profile(profile_face: TopoDS_Face, distance: float) -> TopoDS_Shape:
    """Turn a planar sketch face into a solid by extrusion along its normal."""
    if distance == 0:
        raise ValueError("Sketch extrude distance must be non-zero.")

    validate_shape(profile_face)

    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Vec

    direction = _planar_face_normal(profile_face)
    vector = gp_Vec(direction).Multiplied(distance)
    prism_builder = BRepPrimAPI_MakePrism(profile_face, vector, True, True)
    result = prism_builder.Shape()
    validate_shape(result)
    return cleanup_shape(result)


def apply_profile_feature(
    host_shape: TopoDS_Shape,
    profile_face: TopoDS_Face,
    distance: float,
) -> TopoDS_Shape:
    """Fuse or cut a profile extrusion into an existing body."""
    if distance == 0:
        raise ValueError("Sketch feature distance must be non-zero.")

    validate_shape(host_shape)
    feature = extrude_profile(profile_face, distance)

    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse

    operation_cls = BRepAlgoAPI_Fuse if distance > 0 else BRepAlgoAPI_Cut
    operation = operation_cls(host_shape, feature)
    operation.Build()
    if not operation.IsDone():
        raise UnsupportedTopologyError("Sketch profile feature failed.")

    result = operation.Shape()
    validate_shape(result)
    return cleanup_shape(result)


def project_screen_to_workplane(
    view,
    x: int,
    y: int,
    workplane: Workplane,
) -> tuple[float, float] | None:
    """Project a view pixel onto a workplane and return local UV coordinates."""
    origin_x, origin_y, origin_z, dir_x, dir_y, dir_z = view.ConvertWithProj(
        int(x),
        int(y),
    )
    length_sq = dir_x * dir_x + dir_y * dir_y + dir_z * dir_z
    if length_sq == 0:
        return None
    length = length_sq**0.5
    return ray_to_workplane_uv(
        workplane,
        (float(origin_x), float(origin_y), float(origin_z)),
        (float(dir_x / length), float(dir_y / length), float(dir_z / length)),
    )


def ray_to_workplane_uv(
    workplane: Workplane,
    ray_origin: tuple[float, float, float],
    ray_direction: tuple[float, float, float],
) -> tuple[float, float] | None:
    """Intersect a 3D ray with a workplane and return local UV coordinates."""
    plane_origin = (
        workplane.origin.X(),
        workplane.origin.Y(),
        workplane.origin.Z(),
    )
    normal = (
        workplane.normal.X(),
        workplane.normal.Y(),
        workplane.normal.Z(),
    )
    denominator = _dot(ray_direction, normal)
    if abs(denominator) < 1e-9:
        return None

    origin_to_plane = (
        plane_origin[0] - ray_origin[0],
        plane_origin[1] - ray_origin[1],
        plane_origin[2] - ray_origin[2],
    )
    distance = _dot(origin_to_plane, normal) / denominator
    point = (
        ray_origin[0] + ray_direction[0] * distance,
        ray_origin[1] + ray_direction[1] * distance,
        ray_origin[2] + ray_direction[2] * distance,
    )
    relative = (
        point[0] - plane_origin[0],
        point[1] - plane_origin[1],
        point[2] - plane_origin[2],
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
    return _dot(relative, x_direction), _dot(relative, y_direction)


def _point_on_workplane(workplane: Workplane, u: float, v: float):
    from OCP.gp import gp_Pnt, gp_Vec

    origin = workplane.origin
    vector = gp_Vec(workplane.x_direction).Multiplied(u)
    vector.Add(gp_Vec(workplane.y_direction).Multiplied(v))
    return gp_Pnt(origin.X(), origin.Y(), origin.Z()).Translated(vector)


def _uv_from_workplane_point(workplane: Workplane, point) -> tuple[float, float]:
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
    return _dot(relative, x_direction), _dot(relative, y_direction)


def _edge_from_curve_spec(workplane: Workplane, curve: dict[str, object]):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge

    kind = curve.get("kind")
    start = _curve_spec_point(curve, "start")
    end = _curve_spec_point(curve, "end")
    if kind == "line":
        edge_builder = BRepBuilderAPI_MakeEdge(
            _point_on_workplane(workplane, start[0], start[1]),
            _point_on_workplane(workplane, end[0], end[1]),
        )
        if not edge_builder.IsDone():
            raise UnsupportedTopologyError("Line edge could not be built.")
        return edge_builder.Edge()
    if kind == "arc":
        bend = _curve_spec_point(curve, "bend")
        return make_three_point_arc_edge(workplane, start, end, bend)
    raise ValueError(f"Unsupported curve kind: {kind}")


def _curve_spec_point(
    curve: dict[str, object],
    key: str,
) -> tuple[float, float]:
    value = curve.get(key)
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"Curve spec missing {key}.")
    try:
        return float(value[0]), float(value[1])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Curve spec has invalid {key}.") from exc


def _rectangle_wire(
    workplane: Workplane,
    first: tuple[float, float],
    second: tuple[float, float],
):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon

    min_u = min(first[0], second[0])
    max_u = max(first[0], second[0])
    min_v = min(first[1], second[1])
    max_v = max(first[1], second[1])
    polygon = BRepBuilderAPI_MakePolygon()
    polygon.Add(_point_on_workplane(workplane, min_u, min_v))
    polygon.Add(_point_on_workplane(workplane, max_u, min_v))
    polygon.Add(_point_on_workplane(workplane, max_u, max_v))
    polygon.Add(_point_on_workplane(workplane, min_u, max_v))
    polygon.Close()
    if not polygon.IsDone():
        raise UnsupportedTopologyError("Rectangle profile wire could not be built.")
    return polygon.Wire()


def _circle_wire(
    workplane: Workplane,
    center: tuple[float, float],
    radius: float,
):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    from OCP.gp import gp_Ax2, gp_Circ

    circle = gp_Circ(
        gp_Ax2(
            _point_on_workplane(workplane, center[0], center[1]),
            workplane.normal,
            workplane.x_direction,
        ),
        radius,
    )
    edge = BRepBuilderAPI_MakeEdge(circle).Edge()
    wire_builder = BRepBuilderAPI_MakeWire(edge)
    if not wire_builder.IsDone():
        raise UnsupportedTopologyError("Circle profile wire could not be built.")
    return wire_builder.Wire()


def _same_uv(
    first: tuple[float, float],
    second: tuple[float, float],
    tolerance: float = 1e-6,
) -> bool:
    return (
        abs(first[0] - second[0]) <= tolerance
        and abs(first[1] - second[1]) <= tolerance
    )


def _dot(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> float:
    return first[0] * second[0] + first[1] * second[1] + first[2] * second[2]


def _planar_face_normal(face: TopoDS_Face):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.gp import gp_Dir
    from OCP.TopAbs import TopAbs_REVERSED

    surface = BRepAdaptor_Surface(face)
    if surface.GetType() != GeomAbs_Plane:
        raise UnsupportedTopologyError("Only planar sketch profiles can be extruded.")

    direction = surface.Plane().Axis().Direction()
    if face.Orientation() == TopAbs_REVERSED:
        direction = gp_Dir(-direction.X(), -direction.Y(), -direction.Z())
    return direction
