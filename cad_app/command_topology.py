"""Topology lookup and planar-face helpers for direct modeling commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cad_app.command_common import UnsupportedTopologyError, validate_shape
from cad_app.picker import Picker
from cad_app.types import SelectionKind

if TYPE_CHECKING:
    from OCP.TopoDS import TopoDS_Edge, TopoDS_Face, TopoDS_Shape


def top_planar_face_index(shape: TopoDS_Shape) -> int:
    """Find the highest planar face whose oriented normal points along +Z."""
    validate_shape(shape)
    face_map = Picker.indexed_map(shape, SelectionKind.FACE)
    best_index: int | None = None
    best_z: float | None = None

    from OCP.TopoDS import TopoDS

    for index in range(1, face_map.Extent() + 1):
        face = TopoDS.Face_s(face_map.FindKey(index))
        try:
            normal = _planar_face_normal(face)
        except UnsupportedTopologyError:
            continue
        if normal.Z() < 0.99:
            continue
        center_z = _face_center_z(face)
        if best_z is None or center_z > best_z:
            best_index = index
            best_z = center_z

    if best_index is None:
        raise UnsupportedTopologyError("No upward planar face found.")
    return best_index


def _face_by_index(shape: TopoDS_Shape, face_index: int) -> TopoDS_Face:
    from OCP.TopoDS import TopoDS

    face_map = Picker.indexed_map(shape, SelectionKind.FACE)
    if face_index < 1 or face_index > face_map.Extent():
        raise IndexError(f"Face index out of range: {face_index}")
    return TopoDS.Face_s(face_map.FindKey(face_index))


def _edge_by_index(shape: TopoDS_Shape, edge_index: int) -> TopoDS_Edge:
    from OCP.TopoDS import TopoDS

    edge_map = Picker.indexed_map(shape, SelectionKind.EDGE)
    if edge_index < 1 or edge_index > edge_map.Extent():
        raise IndexError(f"Edge index out of range: {edge_index}")
    return TopoDS.Edge_s(edge_map.FindKey(edge_index))


def _vertex_by_index(shape: TopoDS_Shape, vertex_index: int):
    from OCP.TopoDS import TopoDS

    vertex_map = Picker.indexed_map(shape, SelectionKind.VERTEX)
    if vertex_index < 1 or vertex_index > vertex_map.Extent():
        raise IndexError(f"Vertex index out of range: {vertex_index}")
    return TopoDS.Vertex_s(vertex_map.FindKey(vertex_index))


def _edge_vertex_indexes(shape: TopoDS_Shape, edge: TopoDS_Edge) -> set[int]:
    from OCP.TopAbs import TopAbs_VERTEX
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    shape_vertices = Picker.indexed_map(shape, SelectionKind.VERTEX)
    edge_vertices = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(edge, TopAbs_VERTEX, edge_vertices)
    indexes = {
        shape_vertices.FindIndex(edge_vertices.FindKey(index))
        for index in range(1, edge_vertices.Extent() + 1)
    }
    indexes.discard(0)
    if len(indexes) != 2:
        raise UnsupportedTopologyError("Edge move requires exactly two vertices.")
    return indexes


def _face_vertex_indexes(shape: TopoDS_Shape, face: TopoDS_Face) -> set[int]:
    from OCP.TopAbs import TopAbs_VERTEX
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    shape_vertices = Picker.indexed_map(shape, SelectionKind.VERTEX)
    face_vertices = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(face, TopAbs_VERTEX, face_vertices)
    indexes = {
        shape_vertices.FindIndex(face_vertices.FindKey(index))
        for index in range(1, face_vertices.Extent() + 1)
    }
    indexes.discard(0)
    if len(indexes) < 3:
        raise UnsupportedTopologyError("Face move requires at least three vertices.")
    return indexes


def _assert_all_faces_planar(
    shape: TopoDS_Shape,
    *,
    context: str = "Edge/vertex move",
) -> None:
    """Reject shapes that contain non-planar faces.

    The default error message mentioned only edge/vertex move, which
    misled face-move callers when the same guard rejected their
    request. Callers can pass ``context`` (e.g. ``"Sideways face
    move"``) so the message points at the actual command and hints at
    the workaround.
    """
    from OCP.TopoDS import TopoDS

    face_map = Picker.indexed_map(shape, SelectionKind.FACE)
    for index in range(1, face_map.Extent() + 1):
        if not _is_planar_face(TopoDS.Face_s(face_map.FindKey(index))):
            raise UnsupportedTopologyError(
                f"{context} requires a body whose every face is planar "
                "(no holes, fillets, or revolved surfaces). Push the "
                "face in its normal direction instead."
            )


def _shape_vertex_points(shape: TopoDS_Shape) -> list[tuple[float, float, float]]:
    from OCP.BRep import BRep_Tool
    from OCP.TopoDS import TopoDS

    vertex_map = Picker.indexed_map(shape, SelectionKind.VERTEX)
    points = []
    for index in range(1, vertex_map.Extent() + 1):
        point = BRep_Tool.Pnt_s(TopoDS.Vertex_s(vertex_map.FindKey(index)))
        points.append((point.X(), point.Y(), point.Z()))
    return points


def _is_planar_face(face: TopoDS_Face) -> bool:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane

    return BRepAdaptor_Surface(face).GetType() == GeomAbs_Plane


def _planar_face_normal(face: TopoDS_Face):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.gp import gp_Dir
    from OCP.TopAbs import TopAbs_REVERSED

    surface = BRepAdaptor_Surface(face)
    if surface.GetType() != GeomAbs_Plane:
        raise UnsupportedTopologyError("Only planar faces can be extruded.")

    direction = surface.Plane().Axis().Direction()
    if face.Orientation() == TopAbs_REVERSED:
        direction = gp_Dir(-direction.X(), -direction.Y(), -direction.Z())
    return direction


def _face_center_z(face: TopoDS_Face) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    return props.CentreOfMass().Z()


def _workplane_from_face(face: TopoDS_Face):
    from cad_app.workplane import Workplane

    return Workplane.from_face(face)
