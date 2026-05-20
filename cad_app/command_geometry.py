"""Topology, rebuild, and geometry helpers for direct modeling commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cad_app.command_common import (
    CommandError,
    InvalidShapeError,
    OperationFailedError,
    UnsupportedTopologyError,
    cleanup_shape,
    validate_shape,
)
from cad_app.command_convex import _move_vertices_by_convex_rebuild
from cad_app.command_rounding import (
    _assert_round_surface_count,
    _assert_sharp_planar_edge,
    _assert_supported_round_contour,
    _count_cylindrical_faces,
    _try_rebased_fillet,
    _updated_fillet_history,
    edge_supports_direct_round,
)
from cad_app.command_topology import (
    _assert_all_faces_planar,
    _edge_by_index,
    _edge_vertex_indexes,
    _face_by_index,
    _face_vertex_indexes,
    _planar_face_normal,
    _shape_vertex_points,
    _vertex_by_index,
    _workplane_from_face,
    top_planar_face_index,
)
from cad_app.command_vectors import (
    _cross,
    _dot,
    _newell_normal,
    _norm,
    _normalize,
    _sub,
)
from cad_app.picker import Picker
from cad_app.types import SelectionKind

__all__ = [
    "_assert_all_faces_planar",
    "_assert_round_surface_count",
    "_assert_sharp_planar_edge",
    "_assert_supported_round_contour",
    "_count_cylindrical_faces",
    "_edge_by_index",
    "_edge_vertex_indexes",
    "_extract_disconnected_solids",
    "_face_by_index",
    "_face_vertex_indexes",
    "_is_occt_exception",
    "_move_edge_via_best_face",
    "_move_vertices_by_convex_rebuild",
    "_move_vertices_via_face_rebuild",
    "_planar_face_normal",
    "_run_boolean",
    "_solid_volume",
    "_try_rebased_fillet",
    "_updated_fillet_history",
    "_validate_move_vector",
    "_vertex_by_index",
    "_workplane_from_face",
    "edge_supports_direct_round",
    "top_planar_face_index",
]

if TYPE_CHECKING:
    from OCP.TopoDS import TopoDS_Edge, TopoDS_Face, TopoDS_Shape


def _validate_move_vector(dx: float, dy: float, dz: float) -> None:
    if dx == 0 and dy == 0 and dz == 0:
        raise ValueError("Move vector must be non-zero.")


def _run_boolean(shape_a, shape_b, operation_cls, error_message: str):
    operation = operation_cls(shape_a, shape_b)
    operation.Build()
    if not operation.IsDone():
        raise OperationFailedError(error_message)

    result = operation.Shape()
    validate_shape(result)
    return cleanup_shape(result)


def _shape_has_solid(shape) -> bool:
    """True if the shape already contains at least one solid."""
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    return TopExp_Explorer(shape, TopAbs_SOLID).More()


def solidify_open_shell(shape):
    """Best-effort rebuild of a closed solid from an open shell.

    ``remove_face`` intentionally leaves a body as an open shell (see
    cad_app.commands.remove_face). Boolean-based features such as
    extrude/cut then fail because they need a closed solid. This caps
    every *planar* free-boundary loop with a new face, sews the result,
    and builds a solid.

    Returns the shape unchanged if it already has a solid. Raises
    ``UnsupportedTopologyError`` when the opening cannot be sealed - for
    instance when the removed face was curved (e.g. a cylinder's lateral
    wall), which leaves a free boundary no planar cap can close and so
    yields a degenerate, zero-volume result.
    """
    if _shape_has_solid(shape):
        return shape

    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeFace,
        BRepBuilderAPI_MakeSolid,
        BRepBuilderAPI_Sewing,
    )
    from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL, TopAbs_WIRE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    def _explore(target, kind):
        items = []
        explorer = TopExp_Explorer(target, kind)
        while explorer.More():
            items.append(explorer.Current())
            explorer.Next()
        return items

    free_bounds = ShapeAnalysis_FreeBounds(shape, 1e-6, False, False)
    if _explore(free_bounds.GetOpenWires(), TopAbs_WIRE):
        raise UnsupportedTopologyError(
            "Cannot seal this body: it has an open (non-closed) boundary."
        )

    caps = []
    for wire in _explore(free_bounds.GetClosedWires(), TopAbs_WIRE):
        make_face = BRepBuilderAPI_MakeFace(TopoDS.Wire_s(wire), True)
        if not make_face.IsDone():
            raise UnsupportedTopologyError(
                "Cannot seal this body: a removed face left a curved opening "
                "that no flat cap can close."
            )
        caps.append(make_face.Face())

    sewing = BRepBuilderAPI_Sewing(1e-6)
    for face in _explore(shape, TopAbs_FACE):
        sewing.Add(face)
    for cap in caps:
        sewing.Add(cap)
    sewing.Perform()

    shells = _explore(sewing.SewedShape(), TopAbs_SHELL)
    if not shells:
        raise UnsupportedTopologyError("Cannot seal this body into a closed shell.")
    solid_builder = BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(shells[0]))
    if not solid_builder.IsDone():
        raise UnsupportedTopologyError("Cannot seal this body into a solid.")

    solid = cleanup_shape(solid_builder.Solid())
    try:
        validate_shape(solid)
    except InvalidShapeError as exc:
        raise UnsupportedTopologyError(
            "Sealing this body produced invalid geometry."
        ) from exc
    if abs(_solid_volume(solid)) < 1e-6:
        # Two coincident caps over the same loop (e.g. only a cylinder's
        # lateral wall removed) sew without enclosing any volume.
        raise UnsupportedTopologyError(
            "Cannot seal this body: the removed face left no volume to close."
        )
    return solid


def _extract_disconnected_solids(shape):
    """Return every TopoDS_Solid contained in ``shape``.

    Boolean operations (cut, fuse) sometimes leave the result as a
    compound of multiple independent solids - for instance, cutting a
    bar through the middle leaves two pieces. We want those pieces to
    surface as separate scene items so the user can move, hide, and
    select them independently; otherwise face indices stay shared and
    the browser shows one entry for what visually is two bodies.

    For a regular Solid this returns ``[shape]``.
    """
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    solids = []
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    while explorer.More():
        solids.append(TopoDS.Solid_s(explorer.Current()))
        explorer.Next()
    return solids


def _solid_volume(solid) -> float:
    """Return the volume of a solid; used to pick the 'primary' piece
    after a boolean operation splits a body. The largest solid keeps
    the original feature history, the rest become new bodies."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    properties = GProp_GProps()
    BRepGProp.VolumeProperties_s(solid, properties)
    return float(properties.Mass())


def _face_ordered_vertex_indices(face, shape_vertex_map) -> list[int]:
    wire_indices = _face_ordered_wire_vertex_indices(face, shape_vertex_map)
    if not wire_indices:
        return []
    return wire_indices[0]


def _face_ordered_wire_vertex_indices(face, shape_vertex_map) -> list[list[int]]:
    from OCP.BRepTools import BRepTools
    from OCP.TopAbs import TopAbs_WIRE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    outer_wire = BRepTools.OuterWire_s(face)
    wires: list = [outer_wire]
    wire_exp = TopExp_Explorer(face, TopAbs_WIRE)
    while wire_exp.More():
        wire = TopoDS.Wire_s(wire_exp.Current())
        if not wire.IsSame(outer_wire):
            wires.append(wire)
        wire_exp.Next()

    wire_indices = [
        _wire_ordered_vertex_indices(wire, shape_vertex_map) for wire in wires
    ]
    return [indices for indices in wire_indices if len(indices) >= 3]


def _wire_ordered_vertex_indices(wire, shape_vertex_map) -> list[int]:
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_VERTEX
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    edge_exp = TopExp_Explorer(wire, TopAbs_EDGE)
    edge_vertex_pairs: list[tuple[int, int]] = []

    while edge_exp.More():
        edge = TopoDS.Edge_s(edge_exp.Current())
        vert_exp = TopExp_Explorer(edge, TopAbs_VERTEX)
        pair: list[int] = []
        while vert_exp.More():
            vertex = TopoDS.Vertex_s(vert_exp.Current())
            idx = shape_vertex_map.FindIndex(vertex)
            if idx > 0:
                pair.append(idx)
            vert_exp.Next()
        if len(pair) == 2:
            edge_vertex_pairs.append((pair[0], pair[1]))
        edge_exp.Next()

    if len(edge_vertex_pairs) < 3:
        return []

    result = [edge_vertex_pairs[0][0], edge_vertex_pairs[0][1]]
    edge_vertex_pairs = edge_vertex_pairs[1:]

    while edge_vertex_pairs:
        last = result[-1]
        found = False
        for i, (a, b) in enumerate(edge_vertex_pairs):
            if a == last:
                result.append(b)
                edge_vertex_pairs.pop(i)
                found = True
                break
            if b == last:
                result.append(a)
                edge_vertex_pairs.pop(i)
                found = True
                break
        if not found:
            return []

    if result[0] == result[-1]:
        result.pop()

    return result


def _is_occt_exception(exc: Exception) -> bool:
    return exc.__class__.__module__.startswith("OCP.")


def _points_are_coplanar(
    points: list[tuple[float, float, float]],
    tolerance: float = 1e-6,
) -> bool:
    if len(points) < 4:
        return True

    base = points[0]
    normal: tuple[float, float, float] | None = None
    for first in range(1, len(points) - 1):
        for second in range(first + 1, len(points)):
            candidate = _cross(
                _sub(points[first], base),
                _sub(points[second], base),
            )
            if _norm(candidate) > tolerance:
                normal = _normalize(candidate)
                break
        if normal is not None:
            break

    if normal is None:
        return False

    return all(abs(_dot(normal, _sub(point, base))) <= tolerance for point in points)


def _point_bounds(
    points: list[tuple[float, float, float]],
) -> tuple[float, float, float, float, float, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    zs = [point[2] for point in points]
    return min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)


def _shape_optimal_bounds(
    shape: TopoDS_Shape,
) -> tuple[float, float, float, float, float, float]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    bounds = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, bounds)
    if bounds.IsVoid():
        raise UnsupportedTopologyError("Move rebuild produced empty bounds.")
    return bounds.Get()


def _assert_rebuild_bounds_match_vertices(
    shape: TopoDS_Shape,
    expected_points: list[tuple[float, float, float]],
) -> None:
    expected = _point_bounds(expected_points)
    actual = _shape_optimal_bounds(shape)
    span = max(
        expected[3] - expected[0],
        expected[4] - expected[1],
        expected[5] - expected[2],
        1.0,
    )
    tolerance = max(1e-4, span * 1e-6)

    for axis, actual_min, expected_min, actual_max, expected_max in zip(
        ("X", "Y", "Z"),
        actual[:3],
        expected[:3],
        actual[3:],
        expected[3:],
    ):
        if (
            actual_min < expected_min - tolerance
            or actual_min > expected_min + tolerance
            or actual_max < expected_max - tolerance
            or actual_max > expected_max + tolerance
        ):
            raise UnsupportedTopologyError(
                "Move rebuild produced geometry outside the moved vertices "
                f"on {axis}."
            )


def _make_wire_from_points(
    points: list[tuple[float, float, float]],
    target_normal: tuple[float, float, float],
    *,
    outer: bool,
):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
    from OCP.gp import gp_Pnt

    wire_points = list(points)
    same_direction = _dot(_newell_normal(wire_points), target_normal) >= 0
    if (outer and not same_direction) or (not outer and same_direction):
        wire_points.reverse()

    polygon = BRepBuilderAPI_MakePolygon()
    for point in wire_points:
        polygon.Add(gp_Pnt(*point))
    polygon.Close()
    return polygon.Wire()


def _make_polygon_face(
    points: list[tuple[float, float, float]],
    target_normal: tuple[float, float, float],
):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace

    if len(points) < 3:
        raise UnsupportedTopologyError("Moved face requires at least three vertices.")

    wire = _make_wire_from_points(points, target_normal, outer=True)
    face_builder = BRepBuilderAPI_MakeFace(wire, True)
    if not face_builder.IsDone():
        raise UnsupportedTopologyError("Failed to rebuild a moved face.")

    face = face_builder.Face()
    try:
        validate_shape(face)
    except InvalidShapeError as exc:
        raise UnsupportedTopologyError("Failed to rebuild a moved face.") from exc
    return face


def _make_face_with_inner_wires(
    wire_points: list[list[tuple[float, float, float]]],
    target_normal: tuple[float, float, float],
):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace

    if len(wire_points) < 2:
        return _make_polygon_face(wire_points[0], target_normal)

    outer_wire = _make_wire_from_points(wire_points[0], target_normal, outer=True)
    face_builder = BRepBuilderAPI_MakeFace(outer_wire, True)
    if not face_builder.IsDone():
        raise UnsupportedTopologyError("Failed to rebuild a moved face.")

    for points in wire_points[1:]:
        inner_wire = _make_wire_from_points(points, target_normal, outer=False)
        face_builder.Add(inner_wire)

    face = face_builder.Face()
    try:
        validate_shape(face)
    except InvalidShapeError as exc:
        raise UnsupportedTopologyError("Failed to rebuild a moved face.") from exc
    return face


def _add_filled_face_to_sewing(
    sewing,
    points: list[tuple[float, float, float]],
    target_normal: tuple[float, float, float],
) -> None:
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.BRepFill import BRepFill_Filling
    from OCP.GeomAbs import GeomAbs_C0
    from OCP.gp import gp_Pnt

    wire_points = list(points)
    if _dot(_newell_normal(wire_points), target_normal) < 0:
        wire_points.reverse()

    filling = BRepFill_Filling()
    for start, end in zip(wire_points, [*wire_points[1:], wire_points[0]]):
        edge_builder = BRepBuilderAPI_MakeEdge(gp_Pnt(*start), gp_Pnt(*end))
        if not edge_builder.IsDone():
            raise UnsupportedTopologyError("Failed to rebuild a moved face edge.")
        filling.Add(edge_builder.Edge(), GeomAbs_C0, True)

    filling.Build()
    if not filling.IsDone():
        raise UnsupportedTopologyError("Failed to fill a moved non-planar face.")

    face = filling.Face()
    try:
        validate_shape(face)
    except InvalidShapeError as exc:
        raise UnsupportedTopologyError("Filled moved face is invalid.") from exc
    if _dot(_newell_normal(wire_points), target_normal) < 0:
        face.Reverse()
    sewing.Add(face)


def _add_rebuilt_face_to_sewing(
    sewing,
    face: TopoDS_Face,
    wire_points: list[list[tuple[float, float, float]]],
    *,
    allow_nonplanar_faces: bool,
) -> None:
    try:
        target_direction = _planar_face_normal(face)
        target_normal = (
            target_direction.X(),
            target_direction.Y(),
            target_direction.Z(),
        )
    except UnsupportedTopologyError:
        if not allow_nonplanar_faces or not _is_rebuildable_nonplanar_face(face):
            raise
        target_normal = _newell_normal(wire_points[0])
        if _norm(target_normal) < 1e-9:
            raise UnsupportedTopologyError("Moved face is degenerate.")
    all_points = [point for points in wire_points for point in points]
    if _points_are_coplanar(all_points):
        sewing.Add(_make_face_with_inner_wires(wire_points, target_normal))
        return
    if len(wire_points) > 1:
        raise UnsupportedTopologyError(
            "Move cannot make a face with inner wires non-planar."
        )
    if not allow_nonplanar_faces:
        raise UnsupportedTopologyError("Move would make an affected face non-planar.")
    try:
        _add_filled_face_to_sewing(sewing, wire_points[0], target_normal)
    except CommandError:
        raise
    except Exception as exc:
        if not _is_occt_exception(exc):
            raise
        raise UnsupportedTopologyError(
            "Failed to fill a moved non-planar face."
        ) from exc


def _is_rebuildable_nonplanar_face(face: TopoDS_Face) -> bool:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_BSplineSurface

    return BRepAdaptor_Surface(face).GetType() == GeomAbs_BSplineSurface


def _move_edge_via_face_rebuild(
    shape: TopoDS_Shape,
    edge: TopoDS_Edge,
    dx: float,
    dy: float,
    dz: float,
) -> TopoDS_Shape:
    moved_vertex_indexes = _edge_vertex_indexes(shape, edge)
    return _move_vertices_via_face_rebuild(
        shape,
        moved_vertex_indexes,
        dx,
        dy,
        dz,
        allow_nonplanar_faces=True,
    )


def _move_vertices_via_face_rebuild(
    shape: TopoDS_Shape,
    moved_vertex_indexes: set[int],
    dx: float,
    dy: float,
    dz: float,
    *,
    allow_nonplanar_faces: bool,
) -> TopoDS_Shape:
    old_points = _shape_vertex_points(shape)
    new_points = [
        (x + dx, y + dy, z + dz) if idx in moved_vertex_indexes else (x, y, z)
        for idx, (x, y, z) in enumerate(old_points, start=1)
    ]

    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.TopoDS import TopoDS

    face_map = Picker.indexed_map(shape, SelectionKind.FACE)
    vertex_map = Picker.indexed_map(shape, SelectionKind.VERTEX)

    sewing = BRepBuilderAPI_Sewing(1e-7)

    for face_idx in range(1, face_map.Extent() + 1):
        face = TopoDS.Face_s(face_map.FindKey(face_idx))
        ordered_wire_indices = _face_ordered_wire_vertex_indices(face, vertex_map)
        if not ordered_wire_indices:
            sewing.Add(face)
            continue

        any_moved = any(
            bool(set(ordered_indices) & moved_vertex_indexes)
            for ordered_indices in ordered_wire_indices
        )
        if not any_moved:
            sewing.Add(face)
            continue

        new_wire_points = [
            [new_points[i - 1] for i in ordered_indices]
            for ordered_indices in ordered_wire_indices
        ]
        for points in new_wire_points:
            normal = _newell_normal(points)
            if _norm(normal) < 1e-9:
                raise UnsupportedTopologyError("Moved face is degenerate.")
        _add_rebuilt_face_to_sewing(
            sewing,
            face,
            new_wire_points,
            allow_nonplanar_faces=allow_nonplanar_faces,
        )

    sewing.Perform()
    try:
        shell = TopoDS.Shell_s(sewing.SewedShape())
    except Exception as exc:
        if not _is_occt_exception(exc):
            raise
        raise UnsupportedTopologyError("Move rebuild produced an open shell.") from exc

    solid_builder = BRepBuilderAPI_MakeSolid(shell)
    if not solid_builder.IsDone():
        raise UnsupportedTopologyError("Move rebuild produced an open shell.")

    solid = solid_builder.Solid()
    try:
        validate_shape(solid)
        cleaned = cleanup_shape(solid)
        _assert_rebuild_bounds_match_vertices(cleaned, new_points)
        return cleaned
    except InvalidShapeError as exc:
        raise UnsupportedTopologyError(
            "Vertex/edge move supports only rebuildable planar-faced solids "
            "or previously filled move faces."
        ) from exc


def _move_edge_via_best_face(
    shape: TopoDS_Shape,
    edge_index: int,
    edge: TopoDS_Edge,
    dx: float,
    dy: float,
    dz: float,
) -> TopoDS_Shape:
    """Move edge vertices on non-convex bodies via face rebuild.
    Raises when the operation cannot be rebuilt safely."""
    try:
        return _move_edge_via_face_rebuild(shape, edge, dx, dy, dz)
    except CommandError:
        raise
    except Exception as exc:
        if not _is_occt_exception(exc):
            raise
        raise UnsupportedTopologyError("Edge move rebuild failed.") from exc
