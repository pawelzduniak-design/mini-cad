"""OCP shape helpers used by the viewer."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from cad_app.types import SelectionKind

if TYPE_CHECKING:
    from OCP.TopoDS import TopoDS_Shape


def build_arrow_shape(
    start: tuple[float, float, float],
    direction: tuple[float, float, float],
    length: float,
):
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.gp import gp_Pnt
    from OCP.TopoDS import TopoDS_Compound

    direction = normalized(direction) or (0.0, 0.0, 1.0)
    reference = (0.0, 0.0, 1.0)
    if abs(direction[2]) > 0.85:
        reference = (1.0, 0.0, 0.0)
    side = normalized(cross(direction, reference))
    if side is None:
        side = (1.0, 0.0, 0.0)

    end = add(start, scale(direction, length))
    head_length = max(5.0, min(11.0, length * 0.25))
    head_width = head_length * 0.45
    head_base = add(end, scale(direction, -head_length))
    head_left = add(head_base, scale(side, head_width))
    head_right = add(head_base, scale(side, -head_width))

    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for first, second in ((start, end), (end, head_left), (end, head_right)):
        edge = BRepBuilderAPI_MakeEdge(
            gp_Pnt(*first),
            gp_Pnt(*second),
        ).Edge()
        builder.Add(compound, edge)
    return compound


def translated_shape(
    shape: TopoDS_Shape,
    dx: float,
    dy: float,
    dz: float,
) -> TopoDS_Shape:
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf, gp_Vec

    transform = gp_Trsf()
    transform.SetTranslation(gp_Vec(dx, dy, dz))
    builder = BRepBuilderAPI_Transform(shape, transform, True)
    return builder.Shape()


def first_face_normal(
    shape: TopoDS_Shape,
) -> tuple[float, float, float] | None:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape

    face_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, face_map)
    if face_map.Extent() < 1:
        return None
    face = TopoDS.Face_s(face_map.FindKey(1))
    surface = BRepAdaptor_Surface(face)
    if surface.GetType() != GeomAbs_Plane:
        return None
    normal = surface.Plane().Axis().Direction()
    if face.Orientation() == TopAbs_REVERSED:
        return -normal.X(), -normal.Y(), -normal.Z()
    return normal.X(), normal.Y(), normal.Z()


def is_vector3(value: object) -> bool:
    if not isinstance(value, tuple) or len(value) != 3:
        return False
    return all(isinstance(component, int | float) for component in value)


def normalized(
    vector: tuple[float, float, float],
) -> tuple[float, float, float] | None:
    length = math.sqrt(sum(component * component for component in vector))
    if length < 1e-7:
        return None
    return tuple(component / length for component in vector)


def cross(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def scale(
    vector: tuple[float, float, float],
    scalar: float,
) -> tuple[float, float, float]:
    return tuple(component * scalar for component in vector)


def add(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> tuple[float, float, float]:
    return tuple(
        first_component + second_component
        for first_component, second_component in zip(first, second)
    )


def build_grid_shape(
    size: float,
    step: float,
    z_offset: float = 0.0,
) -> TopoDS_Shape:
    segments = []
    count = int(size / step)
    for index in range(-count, count + 1):
        value = index * step
        if value == 0:
            continue
        segments.append(((-size, value, z_offset), (size, value, z_offset)))
        segments.append(((value, -size, z_offset), (value, size, z_offset)))
    return compound_from_segments(segments)


def build_axis_shape(
    axis: str,
    size: float,
    z_offset: float = 0.0,
) -> TopoDS_Shape:
    if axis == "x":
        return compound_from_segments([((-size, 0.0, z_offset), (size, 0.0, z_offset))])
    if axis == "y":
        return compound_from_segments([((0.0, -size, z_offset), (0.0, size, z_offset))])
    raise ValueError(f"Unsupported grid axis: {axis}")


def build_workplane_overlay_shape(
    workplane: Any,
    size: float,
    normal_offset: float,
) -> TopoDS_Shape:
    half_size = size / 2.0
    tick = size * 0.1
    cross_size = size * 0.28
    segments = [
        ((-half_size, -half_size), (-half_size + tick, -half_size)),
        ((-half_size, -half_size), (-half_size, -half_size + tick)),
        ((half_size, -half_size), (half_size - tick, -half_size)),
        ((half_size, -half_size), (half_size, -half_size + tick)),
        ((half_size, half_size), (half_size - tick, half_size)),
        ((half_size, half_size), (half_size, half_size - tick)),
        ((-half_size, half_size), (-half_size + tick, half_size)),
        ((-half_size, half_size), (-half_size, half_size - tick)),
        ((-cross_size, 0.0), (cross_size, 0.0)),
        ((0.0, -cross_size), (0.0, cross_size)),
    ]
    return compound_from_segments(
        [
            (
                workplane_point(workplane, start[0], start[1], normal_offset),
                workplane_point(workplane, end[0], end[1], normal_offset),
            )
            for start, end in segments
        ]
    )


def workplane_point(
    workplane: Any,
    u: float,
    v: float,
    normal_offset: float,
) -> tuple[float, float, float]:
    from OCP.gp import gp_Pnt, gp_Vec

    vector = gp_Vec(workplane.x_direction).Multiplied(u)
    vector.Add(gp_Vec(workplane.y_direction).Multiplied(v))
    vector.Add(gp_Vec(workplane.normal).Multiplied(normal_offset))
    point = gp_Pnt(
        workplane.origin.X(),
        workplane.origin.Y(),
        workplane.origin.Z(),
    ).Translated(vector)
    return point.X(), point.Y(), point.Z()


def compound_from_segments(
    segments: list[tuple[tuple[float, float, float], tuple[float, float, float]]],
) -> TopoDS_Shape:
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.gp import gp_Pnt
    from OCP.TopoDS import TopoDS_Compound

    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for start, end in segments:
        edge = BRepBuilderAPI_MakeEdge(gp_Pnt(*start), gp_Pnt(*end)).Edge()
        builder.Add(compound, edge)
    return compound


def edge_compound(shape: TopoDS_Shape) -> TopoDS_Shape | None:
    from OCP.BRep import BRep_Builder
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS_Compound
    from OCP.TopTools import TopTools_IndexedMapOfShape

    edge_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_EDGE, edge_map)
    if edge_map.Extent() == 0:
        return None

    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for index in range(1, edge_map.Extent() + 1):
        builder.Add(compound, edge_map.FindKey(index))
    return compound


def mesh_wire_compound(
    shape: TopoDS_Shape, deflection: float = 6.0
) -> TopoDS_Shape | None:
    """Return a triangle-edge compound for a visible mesh-style wireframe."""
    from OCP.BRep import BRep_Builder, BRep_Tool
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS, TopoDS_Compound

    BRepMesh_IncrementalMesh(shape, deflection)
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    edge_keys: set[tuple[tuple[float, float, float], tuple[float, float, float]]] = (
        set()
    )

    def point_key(point) -> tuple[float, float, float]:
        return (round(point.X(), 6), round(point.Y(), 6), round(point.Z(), 6))

    face_explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while face_explorer.More():
        face = TopoDS.Face_s(face_explorer.Current())
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)
        if triangulation is None:
            face_explorer.Next()
            continue
        transform = location.Transformation()
        for index in range(1, triangulation.NbTriangles() + 1):
            nodes = triangulation.Triangle(index).Get()
            points = [
                triangulation.Node(node_index).Transformed(transform)
                for node_index in nodes
            ]
            for first, second in (
                (points[0], points[1]),
                (points[1], points[2]),
                (points[2], points[0]),
            ):
                first_key = point_key(first)
                second_key = point_key(second)
                key = (
                    (first_key, second_key)
                    if first_key <= second_key
                    else (second_key, first_key)
                )
                if key in edge_keys:
                    continue
                edge_keys.add(key)
                edge_builder = BRepBuilderAPI_MakeEdge(first, second)
                if edge_builder.IsDone():
                    builder.Add(compound, edge_builder.Edge())
        face_explorer.Next()

    if not edge_keys:
        return edge_compound(shape)
    return compound


def selection_sensitivity(kind: SelectionKind) -> int:
    if kind == SelectionKind.OBJECT:
        return 4
    if kind == SelectionKind.FACE:
        return 4
    if kind == SelectionKind.EDGE:
        return 12
    if kind == SelectionKind.VERTEX:
        return 14
    raise ValueError(f"Unsupported selection kind: {kind}")
