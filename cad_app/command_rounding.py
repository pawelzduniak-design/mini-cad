"""Fillet, chamfer, and rounded-edge command helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cad_app.command_common import (
    CommandError,
    OperationFailedError,
    UnsupportedTopologyError,
    validate_shape,
)
from cad_app.command_topology import (
    _edge_by_index,
    _is_planar_face,
    _planar_face_normal,
)
from cad_app.command_vectors import _cross, _dot, _norm, _normalize, _scale, _sub
from cad_app.picker import Picker
from cad_app.types import SelectionKind

_FILLET_HISTORY_KEY = "direct_fillet_history"

if TYPE_CHECKING:
    from OCP.TopoDS import TopoDS_Edge, TopoDS_Face, TopoDS_Shape


def edge_supports_direct_round(shape: TopoDS_Shape, edge_index: int) -> bool:
    """Return whether fillet/chamfer can target only this edge safely."""
    validate_shape(shape)
    edge = _edge_by_index(shape, edge_index)
    try:
        _assert_sharp_planar_edge(shape, edge)
        _assert_edge_has_single_fillet_contour(shape, edge)
    except CommandError:
        return False
    return True


def _updated_fillet_history(
    shape: TopoDS_Shape,
    meta: dict,
    edge_index: int,
    radius: float,
) -> dict:
    next_meta = dict(meta)
    history = next_meta.get(_FILLET_HISTORY_KEY)
    if not history:
        next_meta[_FILLET_HISTORY_KEY] = {
            "base_shape": shape,
            "edge_specs": [(edge_index, radius)],
        }
        return next_meta

    base_shape = history["base_shape"]
    edge_specs = list(history["edge_specs"])
    mapped_index = _map_edge_index_between_shapes(shape, edge_index, base_shape)
    if mapped_index is None:
        next_meta.pop(_FILLET_HISTORY_KEY, None)
        return next_meta

    _append_unique_edge_spec(edge_specs, mapped_index, radius)
    next_meta[_FILLET_HISTORY_KEY] = {
        "base_shape": base_shape,
        "edge_specs": edge_specs,
    }
    return next_meta


def _try_rebased_fillet(scene_object, edge_index: int, radius: float):
    from cad_app.commands import fillet_edges

    history = scene_object.meta.get(_FILLET_HISTORY_KEY)
    if not history:
        raise UnsupportedTopologyError(
            "Fillet would affect multiple tangent edges; operation cancelled."
        )

    base_shape = history["base_shape"]
    edge_specs = list(history["edge_specs"])
    mapped_index = _map_edge_index_between_shapes(
        scene_object.shape,
        edge_index,
        base_shape,
    )
    if mapped_index is None:
        raise UnsupportedTopologyError(
            "Selected edge cannot be mapped back to the fillet base shape."
        )

    _append_unique_edge_spec(edge_specs, mapped_index, radius)
    result = fillet_edges(base_shape, edge_specs)
    meta = dict(scene_object.meta)
    meta[_FILLET_HISTORY_KEY] = {
        "base_shape": base_shape,
        "edge_specs": edge_specs,
    }
    return result, meta


def _append_unique_edge_spec(
    edge_specs: list[tuple[int, float]],
    edge_index: int,
    radius: float,
) -> None:
    for index, (existing_index, _) in enumerate(edge_specs):
        if existing_index == edge_index:
            edge_specs[index] = (edge_index, radius)
            return
    edge_specs.append((edge_index, radius))


def _map_edge_index_between_shapes(
    source_shape: TopoDS_Shape,
    source_edge_index: int,
    target_shape: TopoDS_Shape,
) -> int | None:
    source_edge = _edge_by_index(source_shape, source_edge_index)
    try:
        source_segment = _line_segment_from_edge(source_edge)
    except UnsupportedTopologyError:
        return None

    target_edges = Picker.indexed_map(target_shape, SelectionKind.EDGE)
    best_index: int | None = None
    best_score: float | None = None
    for index in range(1, target_edges.Extent() + 1):
        target_edge = _edge_by_index(target_shape, index)
        try:
            target_segment = _line_segment_from_edge(target_edge)
        except UnsupportedTopologyError:
            continue
        score = _line_segment_mapping_score(source_segment, target_segment)
        if score is None:
            continue
        if best_score is None or score < best_score:
            best_index = index
            best_score = score
    return best_index


def _line_segment_from_edge(
    edge: TopoDS_Edge,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Line

    curve = BRepAdaptor_Curve(edge)
    if curve.GetType() != GeomAbs_Line:
        raise UnsupportedTopologyError("Only straight edges can be remapped.")
    start = curve.Value(curve.FirstParameter())
    end = curve.Value(curve.LastParameter())
    return (start.X(), start.Y(), start.Z()), (end.X(), end.Y(), end.Z())


def _line_segment_mapping_score(
    source: tuple[tuple[float, float, float], tuple[float, float, float]],
    target: tuple[tuple[float, float, float], tuple[float, float, float]],
) -> float | None:
    tolerance = 1e-5
    source_start, source_end = source
    target_start, target_end = target
    source_direction = _normalize(_sub(source_end, source_start))
    target_vector = _sub(target_end, target_start)
    target_length = _norm(target_vector)
    if target_length <= tolerance:
        return None
    target_direction = _scale(target_vector, 1.0 / target_length)
    if abs(_dot(source_direction, target_direction)) < 0.999:
        return None

    distances = (
        _point_line_distance(source_start, target_start, target_direction),
        _point_line_distance(source_end, target_start, target_direction),
    )
    if max(distances) > tolerance:
        return None

    projections = (
        _dot(_sub(source_start, target_start), target_direction),
        _dot(_sub(source_end, target_start), target_direction),
    )
    if min(projections) < -tolerance or max(projections) > target_length + tolerance:
        return None
    return sum(distances) + abs(min(projections)) * 1e-9


def _point_line_distance(
    point: tuple[float, float, float],
    line_point: tuple[float, float, float],
    line_direction: tuple[float, float, float],
) -> float:
    return _norm(_cross(_sub(point, line_point), line_direction))


def _assert_sharp_planar_edge(shape: TopoDS_Shape, edge: TopoDS_Edge) -> None:
    adjacent_faces = _edge_adjacent_faces(shape, edge)
    if len(adjacent_faces) != 2:
        raise UnsupportedTopologyError(
            "Edge operation requires exactly two adjacent faces."
        )

    # Two planar neighbours: reject co-planar pairs (they don't form a
    # real edge to round). A cylinder's top/bottom circle is between a
    # planar cap and a curved lateral - that's a perfectly valid fillet
    # target, so don't insist BOTH neighbours be planar. OCCT's
    # BRepFilletAPI handles tangent/smooth edges by reporting
    # IsDone()=False or NbEdges()=0, which the downstream contour /
    # validate checks already catch.
    if all(_is_planar_face(face) for face in adjacent_faces):
        first_normal = _planar_face_normal(adjacent_faces[0])
        second_normal = _planar_face_normal(adjacent_faces[1])
        if abs(first_normal.Dot(second_normal)) > 0.999:
            raise UnsupportedTopologyError(
                "Edge operation requires a sharp planar edge."
            )


def _assert_supported_round_contour(
    builder,
    edge: TopoDS_Edge,
    operation_name: str,
) -> None:
    contour_index = builder.Contour(edge)
    if contour_index <= 0:
        raise OperationFailedError(f"{operation_name} contour was not created.")
    edge_count = builder.NbEdges(contour_index)
    if edge_count == 1:
        return
    raise UnsupportedTopologyError(
        f"{operation_name} would affect {edge_count} tangent edges; "
        "operation cancelled."
    )


def _assert_round_surface_count(
    previous_round_count: int,
    shape: TopoDS_Shape,
    expected_added: int,
) -> None:
    round_count = _count_cylindrical_faces(shape)
    if round_count != previous_round_count + expected_added:
        raise UnsupportedTopologyError(
            "Fillet changed an unexpected number of round surfaces; "
            "operation cancelled."
        )


def _count_cylindrical_faces(shape: TopoDS_Shape) -> int:
    # Counts faces a fillet can introduce: a fillet between two planar
    # faces creates a cylindrical strip, but a fillet on a planar/curved
    # circle edge (e.g. top of a cylinder) creates a TORUS. Both are
    # "round surfaces" the post-fillet sanity check expects to see grow
    # by N. Counting any non-planar analytic surface keeps that check
    # alive without falsely failing the cylinder-cap fillet case.
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.TopoDS import TopoDS

    face_map = Picker.indexed_map(shape, SelectionKind.FACE)
    return sum(
        1
        for index in range(1, face_map.Extent() + 1)
        if BRepAdaptor_Surface(TopoDS.Face_s(face_map.FindKey(index))).GetType()
        != GeomAbs_Plane
    )


def _assert_edge_has_single_fillet_contour(
    shape: TopoDS_Shape,
    edge: TopoDS_Edge,
) -> None:
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet

    builder = BRepFilletAPI_MakeFillet(shape)
    builder.Add(1.0, edge)
    _assert_supported_round_contour(builder, edge, "Fillet")


def _edge_adjacent_faces(
    shape: TopoDS_Shape,
    edge: TopoDS_Edge,
) -> list[TopoDS_Face]:
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape

    edge_face_map = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndUniqueAncestors_s(
        shape,
        TopAbs_EDGE,
        TopAbs_FACE,
        edge_face_map,
    )
    if not edge_face_map.Contains(edge):
        raise UnsupportedTopologyError("Edge does not belong to the shape.")
    faces = edge_face_map.FindFromKey(edge)
    return [TopoDS.Face_s(face) for face in faces]
