"""Direct modeling command operations."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from cad_app.picker import Picker
from cad_app.profiles import CircleProfile
from cad_app.types import SelectionKind

_FILLET_HISTORY_KEY = "direct_fillet_history"

if TYPE_CHECKING:
    from OCP.TopoDS import TopoDS_Edge, TopoDS_Face, TopoDS_Shape

    from cad_app.scene import Scene


class CommandError(RuntimeError):
    """Base error for direct modeling command failures."""


class InvalidShapeError(CommandError):
    """Raised when input or result shape is topologically invalid."""


class UnsupportedTopologyError(CommandError):
    """Raised when a command receives unsupported topology."""


class OperationFailedError(CommandError):
    """Raised when OCCT refuses to build the requested operation."""


def validate_shape(shape: TopoDS_Shape) -> None:
    """Validate a TopoDS shape using OCCT's BRepCheck analyzer."""
    from OCP.BRepCheck import BRepCheck_Analyzer

    if shape.IsNull():
        raise InvalidShapeError("Shape is null.")
    if not BRepCheck_Analyzer(shape).IsValid():
        raise InvalidShapeError("Shape is not topologically valid.")


def cleanup_shape(shape: TopoDS_Shape) -> TopoDS_Shape:
    """Merge same-domain faces/edges when OCCT can do it safely."""
    validate_shape(shape)

    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain

    unifier = ShapeUpgrade_UnifySameDomain(shape, True, True, False)
    unifier.SetSafeInputMode(True)
    unifier.Build()
    cleaned = unifier.Shape()
    try:
        validate_shape(cleaned)
    except InvalidShapeError:
        return shape
    return cleaned


def extrude_face(
    shape: TopoDS_Shape,
    face_index: int,
    distance: float,
) -> TopoDS_Shape:
    """Push or pull a planar face along its outward normal."""
    if distance == 0:
        raise ValueError("Extrude distance must be non-zero.")

    validate_shape(shape)
    face = _face_by_index(shape, face_index)
    direction = _planar_face_normal(face)

    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Vec

    vector = gp_Vec(direction).Multiplied(distance)
    prism_builder = BRepPrimAPI_MakePrism(face, vector)
    prism = prism_builder.Shape()
    validate_shape(prism)

    operation_cls = BRepAlgoAPI_Fuse if distance > 0 else BRepAlgoAPI_Cut
    return _run_boolean(
        shape, prism, operation_cls, "Extrude boolean operation failed."
    )


def apply_extrude_face(
    scene: Scene,
    item_id: str,
    face_index: int,
    distance: float,
) -> TopoDS_Shape:
    """Apply extrude to a scene object after successful validation."""
    scene_object = scene.get(item_id)
    result = extrude_face(scene_object.shape, face_index, distance)
    scene.replace_shape(item_id, result)
    return result


def add_circle_feature(
    shape: TopoDS_Shape,
    face_index: int,
    radius: float,
    depth: float,
    cut: bool = False,
) -> TopoDS_Shape:
    """Add or cut a cylindrical circle feature centered on a planar face."""
    profile = CircleProfile(radius)
    if depth <= 0:
        raise ValueError("Circle depth must be positive.")

    validate_shape(shape)
    face = _face_by_index(shape, face_index)
    workplane = _workplane_from_face(face)

    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Vec

    normal = workplane.normal
    base = workplane.origin
    height = depth
    axis_direction = normal
    if cut:
        epsilon = max(depth * 0.01, 0.01)
        base = base.Translated(gp_Vec(normal).Multiplied(epsilon))
        axis_direction = gp_Dir(-normal.X(), -normal.Y(), -normal.Z())
        height = depth + epsilon

    cylinder = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(base.X(), base.Y(), base.Z()), axis_direction),
        profile.radius,
        height,
    ).Shape()
    validate_shape(cylinder)

    operation_cls = BRepAlgoAPI_Cut if cut else BRepAlgoAPI_Fuse
    return _run_boolean(shape, cylinder, operation_cls, "Circle feature failed.")


def apply_circle_feature(
    scene: Scene,
    item_id: str,
    face_index: int,
    radius: float,
    depth: float,
    cut: bool = False,
) -> TopoDS_Shape:
    """Apply a centered circle feature to a scene object."""
    scene_object = scene.get(item_id)
    result = add_circle_feature(scene_object.shape, face_index, radius, depth, cut)
    scene.replace_shape(item_id, result)
    return result


def boolean_bodies(
    target_shape: TopoDS_Shape,
    tool_shape: TopoDS_Shape,
    operation: str,
) -> TopoDS_Shape:
    """Run a boolean operation between two body shapes."""
    validate_shape(target_shape)
    validate_shape(tool_shape)

    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse

    operation_map = {
        "union": (BRepAlgoAPI_Fuse, "Body union failed."),
        "subtract": (BRepAlgoAPI_Cut, "Body subtract failed."),
        "intersect": (BRepAlgoAPI_Common, "Body intersect failed."),
    }
    try:
        operation_cls, error_message = operation_map[operation]
    except KeyError as exc:
        raise ValueError(f"Unsupported boolean operation: {operation}") from exc
    return _run_boolean(target_shape, tool_shape, operation_cls, error_message)


def apply_boolean_bodies(
    scene: Scene,
    target_item_id: str,
    tool_item_id: str,
    operation: str,
) -> TopoDS_Shape:
    """Apply body-body boolean, replacing target and removing the tool body."""
    if target_item_id == tool_item_id:
        raise ValueError("Boolean operation requires two different bodies.")

    target_object = scene.get(target_item_id)
    tool_object = scene.get(tool_item_id)
    result = boolean_bodies(target_object.shape, tool_object.shape, operation)
    with scene.transaction():
        scene.replace_shape(
            target_item_id,
            result,
            meta={
                **target_object.meta,
                "last_boolean_operation": operation,
                "last_boolean_tool_item_id": tool_item_id,
            },
        )
        scene.remove(tool_item_id)
        scene.set_active_item(target_item_id)
        scene.set_selection(None)
    return result


def fillet_edge(
    shape: TopoDS_Shape,
    edge_index: int,
    radius: float,
) -> TopoDS_Shape:
    """Apply a constant-radius fillet to one edge."""
    if radius <= 0:
        raise ValueError("Fillet radius must be positive.")

    validate_shape(shape)
    edge = _edge_by_index(shape, edge_index)
    _assert_sharp_planar_edge(shape, edge)
    round_face_count = _count_cylindrical_faces(shape)

    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet

    builder = BRepFilletAPI_MakeFillet(shape)
    builder.Add(radius, edge)
    _assert_supported_round_contour(builder, edge, "Fillet")
    builder.Build()
    if not builder.IsDone():
        raise OperationFailedError("Fillet operation failed.")

    result = builder.Shape()
    validate_shape(result)
    cleaned = cleanup_shape(result)
    _assert_round_surface_count(round_face_count, cleaned, 1)
    return cleaned


def chamfer_edge(
    shape: TopoDS_Shape,
    edge_index: int,
    distance: float,
) -> TopoDS_Shape:
    """Apply a symmetric chamfer to one edge."""
    if distance <= 0:
        raise ValueError("Chamfer distance must be positive.")

    validate_shape(shape)
    edge = _edge_by_index(shape, edge_index)
    _assert_sharp_planar_edge(shape, edge)

    from OCP.BRepFilletAPI import BRepFilletAPI_MakeChamfer

    builder = BRepFilletAPI_MakeChamfer(shape)
    builder.Add(distance, edge)
    _assert_supported_round_contour(builder, edge, "Chamfer")
    builder.Build()
    if not builder.IsDone():
        raise OperationFailedError("Chamfer operation failed.")

    result = builder.Shape()
    validate_shape(result)
    return cleanup_shape(result)


def apply_fillet_edge(
    scene: Scene,
    item_id: str,
    edge_index: int,
    radius: float,
) -> TopoDS_Shape:
    """Apply fillet to a scene object after successful validation."""
    scene_object = scene.get(item_id)
    try:
        result = fillet_edge(scene_object.shape, edge_index, radius)
        meta = _updated_fillet_history(
            scene_object.shape,
            scene_object.meta,
            edge_index,
            radius,
        )
    except UnsupportedTopologyError:
        result, meta = _try_rebased_fillet(scene_object, edge_index, radius)
    scene.replace_shape(item_id, result, meta=meta)
    return result


def fillet_edges(
    shape: TopoDS_Shape,
    edge_specs: list[tuple[int, float]],
) -> TopoDS_Shape:
    """Apply constant-radius fillets to a controlled set of original edges."""
    if not edge_specs:
        raise ValueError("At least one edge is required.")

    validate_shape(shape)
    round_face_count = _count_cylindrical_faces(shape)

    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet

    builder = BRepFilletAPI_MakeFillet(shape)
    unique_edges: dict[int, float] = {}
    for edge_index, radius in edge_specs:
        if radius <= 0:
            raise ValueError("Fillet radius must be positive.")
        unique_edges[edge_index] = radius

    for edge_index, radius in unique_edges.items():
        edge = _edge_by_index(shape, edge_index)
        _assert_sharp_planar_edge(shape, edge)
        builder.Add(radius, edge)

    builder.Build()
    if not builder.IsDone():
        raise OperationFailedError("Multi-edge fillet operation failed.")

    result = builder.Shape()
    validate_shape(result)
    cleaned = cleanup_shape(result)
    _assert_round_surface_count(round_face_count, cleaned, len(unique_edges))
    return cleaned


def apply_chamfer_edge(
    scene: Scene,
    item_id: str,
    edge_index: int,
    distance: float,
) -> TopoDS_Shape:
    """Apply chamfer to a scene object after successful validation."""
    scene_object = scene.get(item_id)
    result = chamfer_edge(scene_object.shape, edge_index, distance)
    scene.replace_shape(item_id, result)
    return result


def rotate_shape(
    shape: TopoDS_Shape,
    center: tuple[float, float, float],
    axis: tuple[float, float, float],
    angle_degrees: float,
) -> TopoDS_Shape:
    """Rotate an entire shape around a world-space axis."""
    if abs(angle_degrees) < 1e-7:
        raise ValueError("Rotate angle must be non-zero.")
    _validate_rotation_axis(axis)

    validate_shape(shape)
    rotated = rotated_shape(shape, center, axis, angle_degrees)
    validate_shape(rotated)
    return cleanup_shape(rotated)


def apply_rotate_object(
    scene: Scene,
    item_id: str,
    center: tuple[float, float, float],
    axis: tuple[float, float, float],
    angle_degrees: float,
) -> TopoDS_Shape:
    """Apply a whole-object rotation to a scene object."""
    scene_object = scene.get(item_id)
    result = rotate_shape(scene_object.shape, center, axis, angle_degrees)
    scene.replace_shape(item_id, result)
    return result


def move_shape(
    shape: TopoDS_Shape,
    dx: float,
    dy: float,
    dz: float,
) -> TopoDS_Shape:
    """Translate an entire shape by a world-space vector."""
    _validate_move_vector(dx, dy, dz)
    validate_shape(shape)
    moved = translated_shape(shape, dx, dy, dz)
    validate_shape(moved)
    return moved


def rotated_shape(
    shape: TopoDS_Shape,
    center: tuple[float, float, float],
    axis: tuple[float, float, float],
    angle_degrees: float,
) -> TopoDS_Shape:
    """Return a rotated copy of a shape for preview or direct commands."""
    _validate_rotation_axis(axis)

    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf

    transform = gp_Trsf()
    transform.SetRotation(
        gp_Ax1(gp_Pnt(*center), gp_Dir(*axis)),
        math.radians(angle_degrees),
    )
    return BRepBuilderAPI_Transform(shape, transform, True).Shape()


def _validate_rotation_axis(axis: tuple[float, float, float]) -> None:
    if math.sqrt(sum(component * component for component in axis)) < 1e-7:
        raise ValueError("Rotate axis must be non-zero.")


def translated_shape(
    shape: TopoDS_Shape,
    dx: float,
    dy: float,
    dz: float,
) -> TopoDS_Shape:
    """Return a transformed copy of a shape for preview or direct commands."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf, gp_Vec

    transform = gp_Trsf()
    transform.SetTranslation(gp_Vec(dx, dy, dz))
    return BRepBuilderAPI_Transform(shape, transform, True).Shape()


def face_normal_vector(
    shape: TopoDS_Shape,
    face_index: int,
) -> tuple[float, float, float]:
    """Return the outward normal of a planar face as a tuple."""
    validate_shape(shape)
    normal = _planar_face_normal(_face_by_index(shape, face_index))
    return normal.X(), normal.Y(), normal.Z()


def apply_move_object(
    scene: Scene,
    item_id: str,
    dx: float,
    dy: float,
    dz: float,
) -> TopoDS_Shape:
    """Translate a scene object after successful validation."""
    scene_object = scene.get(item_id)
    result = move_shape(scene_object.shape, dx, dy, dz)
    scene.replace_shape(item_id, result)
    return result


def move_face_normal(
    shape: TopoDS_Shape,
    face_index: int,
    distance: float,
) -> TopoDS_Shape:
    """Move a planar face along its normal using controlled push-pull."""
    return extrude_face(shape, face_index, distance)


def apply_move_face_normal(
    scene: Scene,
    item_id: str,
    face_index: int,
    distance: float,
) -> TopoDS_Shape:
    """Apply controlled normal face move to a scene object."""
    scene_object = scene.get(item_id)
    result = move_face_normal(scene_object.shape, face_index, distance)
    scene.replace_shape(item_id, result)
    return result


def move_face_controlled(
    shape: TopoDS_Shape,
    face_index: int,
    dx: float,
    dy: float,
    dz: float,
) -> TopoDS_Shape:
    """Move all vertices of a planar face by a world-space vector."""
    _validate_move_vector(dx, dy, dz)
    validate_shape(shape)
    face = _face_by_index(shape, face_index)
    _assert_all_faces_planar(shape)
    moved_vertex_indexes = _face_vertex_indexes(shape, face)
    return _move_vertices_by_convex_rebuild(shape, moved_vertex_indexes, (dx, dy, dz))


def apply_move_face_controlled(
    scene: Scene,
    item_id: str,
    face_index: int,
    dx: float,
    dy: float,
    dz: float,
) -> TopoDS_Shape:
    """Apply controlled face move to a scene object."""
    scene_object = scene.get(item_id)
    result = move_face_controlled(scene_object.shape, face_index, dx, dy, dz)
    scene.replace_shape(item_id, result)
    return result


def supports_move_face_controlled(shape: TopoDS_Shape, face_index: int) -> bool:
    """Return whether view-plane face move can rebuild this shape."""
    try:
        validate_shape(shape)
        face = _face_by_index(shape, face_index)
        _assert_all_faces_planar(shape)
        _face_vertex_indexes(shape, face)
    except (CommandError, IndexError, TypeError, AttributeError):
        return False
    return True


def move_edge_controlled(
    shape: TopoDS_Shape,
    edge_index: int,
    dx: float,
    dy: float,
    dz: float,
) -> TopoDS_Shape:
    """Move both vertices of an edge on a simple convex planar solid.

    For shapes with up to 8 vertices (simple boxes) convex hull
    vertex rebuild preserves exact topology. For complex/fused
    bodies (>8 vertices) we fall back to face extrude which
    uses boolean operations and works on any topology.
    """
    _validate_move_vector(dx, dy, dz)
    validate_shape(shape)
    edge = _edge_by_index(shape, edge_index)
    _assert_sharp_planar_edge(shape, edge)

    vertex_count = Picker.indexed_map(shape, SelectionKind.VERTEX).Extent()
    if vertex_count > 8:
        return _move_edge_via_best_face(shape, edge_index, edge, dx, dy, dz)

    moved_vertex_indexes = _edge_vertex_indexes(shape, edge)
    return _move_vertices_by_convex_rebuild(shape, moved_vertex_indexes, (dx, dy, dz))


def apply_move_edge_controlled(
    scene: Scene,
    item_id: str,
    edge_index: int,
    dx: float,
    dy: float,
    dz: float,
) -> TopoDS_Shape:
    """Apply controlled edge move to a scene object."""
    scene_object = scene.get(item_id)
    result = move_edge_controlled(scene_object.shape, edge_index, dx, dy, dz)
    scene.replace_shape(item_id, result)
    return result


def supports_move_edge_controlled(shape: TopoDS_Shape, edge_index: int) -> bool:
    """Return whether edge move can rebuild this shape."""
    try:
        validate_shape(shape)
        _assert_all_faces_planar(shape)
        edge = _edge_by_index(shape, edge_index)
        _assert_sharp_planar_edge(shape, edge)
        _edge_vertex_indexes(shape, edge)
    except (CommandError, IndexError, TypeError, AttributeError):
        return False
    return True


def move_vertex_controlled(
    shape: TopoDS_Shape,
    vertex_index: int,
    dx: float,
    dy: float,
    dz: float,
) -> TopoDS_Shape:
    """Move one vertex on a simple convex planar solid."""
    _validate_move_vector(dx, dy, dz)
    validate_shape(shape)
    _vertex_by_index(shape, vertex_index)
    return _move_vertices_by_convex_rebuild(shape, {vertex_index}, (dx, dy, dz))


def apply_move_vertex_controlled(
    scene: Scene,
    item_id: str,
    vertex_index: int,
    dx: float,
    dy: float,
    dz: float,
) -> TopoDS_Shape:
    """Apply controlled vertex move to a scene object."""
    scene_object = scene.get(item_id)
    result = move_vertex_controlled(scene_object.shape, vertex_index, dx, dy, dz)
    scene.replace_shape(item_id, result)
    return result


def supports_move_vertex_controlled(shape: TopoDS_Shape, vertex_index: int) -> bool:
    """Return whether vertex move can rebuild this shape."""
    try:
        validate_shape(shape)
        _assert_all_faces_planar(shape)
        _vertex_by_index(shape, vertex_index)
    except (CommandError, IndexError, TypeError, AttributeError):
        return False
    return True


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


def _validate_move_vector(dx: float, dy: float, dz: float) -> None:
    if dx == 0 and dy == 0 and dz == 0:
        raise ValueError("Move vector must be non-zero.")


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


def _assert_all_faces_planar(shape: TopoDS_Shape) -> None:
    from OCP.TopoDS import TopoDS

    face_map = Picker.indexed_map(shape, SelectionKind.FACE)
    for index in range(1, face_map.Extent() + 1):
        if not _is_planar_face(TopoDS.Face_s(face_map.FindKey(index))):
            raise UnsupportedTopologyError(
                "Edge/vertex move supports only planar-faced solids."
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


def _average_point(
    points: list[tuple[float, float, float]],
) -> tuple[float, float, float]:
    count = float(len(points))
    return (
        sum(point[0] for point in points) / count,
        sum(point[1] for point in points) / count,
        sum(point[2] for point in points) / count,
    )


def _newell_normal(
    points: list[tuple[float, float, float]],
) -> tuple[float, float, float]:
    normal_x = 0.0
    normal_y = 0.0
    normal_z = 0.0
    for current, following in zip(points, [*points[1:], points[0]]):
        normal_x += (current[1] - following[1]) * (current[2] + following[2])
        normal_y += (current[2] - following[2]) * (current[0] + following[0])
        normal_z += (current[0] - following[0]) * (current[1] + following[1])
    return normal_x, normal_y, normal_z


def _sub(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> tuple[float, float, float]:
    return left[0] - right[0], left[1] - right[1], left[2] - right[2]


def _cross(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _dot(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> float:
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2]


def _norm(vector: tuple[float, float, float]) -> float:
    return _dot(vector, vector) ** 0.5


def _normalize(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    length = _norm(vector)
    if length == 0:
        raise UnsupportedTopologyError("Cannot normalize a zero vector.")
    return vector[0] / length, vector[1] / length, vector[2] / length


def _scale(
    vector: tuple[float, float, float],
    factor: float,
) -> tuple[float, float, float]:
    return vector[0] * factor, vector[1] * factor, vector[2] * factor


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
    if not all(_is_planar_face(face) for face in adjacent_faces):
        raise UnsupportedTopologyError(
            "Edge operation is allowed only between planar faces."
        )

    first_normal = _planar_face_normal(adjacent_faces[0])
    second_normal = _planar_face_normal(adjacent_faces[1])
    if abs(first_normal.Dot(second_normal)) > 0.999:
        raise UnsupportedTopologyError("Edge operation requires a sharp planar edge.")


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
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.TopoDS import TopoDS

    face_map = Picker.indexed_map(shape, SelectionKind.FACE)
    return sum(
        1
        for index in range(1, face_map.Extent() + 1)
        if BRepAdaptor_Surface(TopoDS.Face_s(face_map.FindKey(index))).GetType()
        == GeomAbs_Cylinder
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


def _run_boolean(shape_a, shape_b, operation_cls, error_message: str):
    operation = operation_cls(shape_a, shape_b)
    operation.Build()
    if not operation.IsDone():
        raise OperationFailedError(error_message)

    result = operation.Shape()
    validate_shape(result)
    return cleanup_shape(result)


def _workplane_from_face(face: TopoDS_Face):
    from cad_app.workplane import Workplane

    return Workplane.from_face(face)


def _move_edge_via_best_face(
    shape: TopoDS_Shape,
    edge_index: int,
    edge: TopoDS_Edge,
    dx: float,
    dy: float,
    dz: float,
) -> TopoDS_Shape:
    """Apply face extrude to both adjacent faces for edge move on
    complex bodies. Projects the move vector onto each face normal
    and applies sequential boolean push/pull."""
    faces = _edge_adjacent_faces(shape, edge)
    if len(faces) != 2:
        raise UnsupportedTopologyError(
            "Edge operation requires exactly two adjacent faces."
        )

    projections: list[tuple[tuple[float, float, float], float]] = []
    for face in faces:
        normal = _planar_face_normal(face)
        n = (normal.X(), normal.Y(), normal.Z())
        proj = dx * n[0] + dy * n[1] + dz * n[2]
        if abs(proj) > 1e-9:
            projections.append((n, proj))

    if not projections:
        raise UnsupportedTopologyError(
            "Move vector has no projection on adjacent faces."
        )

    from OCP.TopoDS import TopoDS

    result = shape
    for _normal, proj_distance in projections:
        face_map = Picker.indexed_map(result, SelectionKind.FACE)
        best_face_index = 0
        for i in range(1, face_map.Extent() + 1):
            face = TopoDS.Face_s(face_map.FindKey(i))
            try:
                fnormal = _planar_face_normal(face)
                fn = (fnormal.X(), fnormal.Y(), fnormal.Z())
                if _vectors_parallel(fn, _normal):
                    best_face_index = i
                    break
            except UnsupportedTopologyError:
                continue
        if best_face_index == 0:
            continue
        result = extrude_face(result, best_face_index, proj_distance)

    return result


def _vectors_parallel(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
) -> bool:
    return abs(a[0] * b[0] + a[1] * b[1] + a[2] * b[2]) > 0.9999
