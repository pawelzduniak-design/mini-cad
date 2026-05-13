"""Convex solid rebuild fallback for direct modeling commands."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from cad_app.command_common import (
    UnsupportedTopologyError,
    cleanup_shape,
    validate_shape,
)
from cad_app.command_topology import _assert_all_faces_planar, _shape_vertex_points
from cad_app.command_vectors import (
    _average_point,
    _cross,
    _dot,
    _newell_normal,
    _norm,
    _normalize,
    _scale,
    _sub,
)

if TYPE_CHECKING:
    from OCP.TopoDS import TopoDS_Shape


def _move_vertices_by_convex_rebuild(
    shape: TopoDS_Shape,
    moved_vertex_indexes: set[int],
    vector: tuple[float, float, float],
) -> TopoDS_Shape:
    _assert_all_faces_planar(shape)
    points = _shape_vertex_points(shape)
    if len(points) < 4:
        raise UnsupportedTopologyError("Convex rebuild requires at least four points.")

    dx, dy, dz = vector
    moved_points = [
        (x + dx, y + dy, z + dz) if index in moved_vertex_indexes else (x, y, z)
        for index, (x, y, z) in enumerate(points, start=1)
    ]
    rebuilt = _build_convex_polyhedron(moved_points)
    validate_shape(rebuilt)
    return cleanup_shape(rebuilt)


def _build_convex_polyhedron(
    points: list[tuple[float, float, float]],
) -> TopoDS_Shape:
    faces = _convex_hull_faces(points)
    if len(faces) < 4:
        raise UnsupportedTopologyError("Moved points do not form a closed solid.")

    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeFace,
        BRepBuilderAPI_MakePolygon,
        BRepBuilderAPI_MakeSolid,
        BRepBuilderAPI_Sewing,
    )
    from OCP.gp import gp_Pnt
    from OCP.TopoDS import TopoDS

    sewing = BRepBuilderAPI_Sewing(1e-7)
    for face_indexes in faces:
        polygon = BRepBuilderAPI_MakePolygon()
        for point_index in face_indexes:
            polygon.Add(gp_Pnt(*points[point_index]))
        polygon.Close()
        face_builder = BRepBuilderAPI_MakeFace(polygon.Wire(), True)
        if not face_builder.IsDone():
            raise UnsupportedTopologyError("Failed to rebuild a moved face.")
        sewing.Add(face_builder.Face())

    sewing.Perform()
    shell = TopoDS.Shell_s(sewing.SewedShape())
    solid_builder = BRepBuilderAPI_MakeSolid(shell)
    solid = solid_builder.Solid()
    validate_shape(solid)
    return solid


def _convex_hull_faces(points: list[tuple[float, float, float]]) -> list[list[int]]:
    tolerance = 1e-7
    centroid = _average_point(points)
    face_sets: set[frozenset[int]] = set()

    for i in range(len(points) - 2):
        for j in range(i + 1, len(points) - 1):
            for k in range(j + 1, len(points)):
                normal = _cross(
                    _sub(points[j], points[i]),
                    _sub(points[k], points[i]),
                )
                if _norm(normal) < tolerance:
                    continue
                distances = [_dot(normal, _sub(point, points[i])) for point in points]
                if not (
                    all(distance >= -tolerance for distance in distances)
                    or all(distance <= tolerance for distance in distances)
                ):
                    continue

                face_set = frozenset(
                    index
                    for index, distance in enumerate(distances)
                    if abs(distance) <= tolerance
                )
                if len(face_set) >= 3:
                    face_sets.add(face_set)

    return [_ordered_face(points, sorted(face_set), centroid) for face_set in face_sets]


def _ordered_face(
    points: list[tuple[float, float, float]],
    indexes: list[int],
    centroid: tuple[float, float, float],
) -> list[int]:
    face_center = _average_point([points[index] for index in indexes])
    normal = _newell_normal([points[index] for index in indexes])
    if _norm(normal) < 1e-7:
        normal = _cross(
            _sub(points[indexes[1]], points[indexes[0]]),
            _sub(points[indexes[2]], points[indexes[0]]),
        )
    normal = _normalize(normal)
    if _dot(normal, _sub(face_center, centroid)) < 0:
        normal = _scale(normal, -1.0)

    axis_u = _normalize(_sub(points[indexes[0]], face_center))
    axis_v = _cross(normal, axis_u)
    ordered = sorted(
        indexes,
        key=lambda index: _angle_on_plane(points[index], face_center, axis_u, axis_v),
    )
    polygon_normal = _newell_normal([points[index] for index in ordered])
    if _dot(polygon_normal, _sub(face_center, centroid)) < 0:
        ordered.reverse()
    return ordered


def _angle_on_plane(
    point: tuple[float, float, float],
    origin: tuple[float, float, float],
    axis_u: tuple[float, float, float],
    axis_v: tuple[float, float, float],
) -> float:
    vector = _sub(point, origin)
    return math.atan2(_dot(vector, axis_v), _dot(vector, axis_u))
