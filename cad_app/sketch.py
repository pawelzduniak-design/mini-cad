"""Planar sketch profiles backed by real OCCT topology."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cad_app.commands import UnsupportedTopologyError, cleanup_shape, validate_shape
from cad_app.workplane import Workplane

if TYPE_CHECKING:
    from OCP.TopoDS import TopoDS_Face, TopoDS_Shape


SKETCH_META_KIND = "sketch_profile"
SKETCH_ENTITY_META_KIND = "sketch_entity"


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

    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeEdge,
        BRepBuilderAPI_MakeFace,
        BRepBuilderAPI_MakeWire,
    )
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

    face = BRepBuilderAPI_MakeFace(wire_builder.Wire(), True).Face()
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
