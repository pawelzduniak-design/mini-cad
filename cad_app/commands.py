"""Direct modeling command operations."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from cad_app.command_common import (
    CommandError,
    InvalidShapeError,
    OperationFailedError,
    UnsupportedTopologyError,
    cleanup_shape,
    validate_shape,
)
from cad_app.command_geometry import (
    _assert_all_faces_planar,
    _assert_round_surface_count,
    _assert_sharp_planar_edge,
    _assert_supported_round_contour,
    _count_cylindrical_faces,
    _edge_by_index,
    _edge_vertex_indexes,
    _extract_disconnected_solids,
    _face_by_index,
    _face_vertex_indexes,
    _is_occt_exception,
    _move_edge_via_best_face,
    _move_vertices_by_convex_rebuild,
    _move_vertices_via_face_rebuild,
    _planar_face_normal,
    _run_boolean,
    _solid_volume,
    _try_rebased_fillet,
    _updated_fillet_history,
    _validate_move_vector,
    _vertex_by_index,
    _workplane_from_face,
    edge_supports_direct_round,
    top_planar_face_index,
)
from cad_app.feature_history import (
    append_feature_step,
    capture_extrude_face_step,
    capture_thread_step,
)
from cad_app.picker import Picker
from cad_app.profiles import CircleProfile
from cad_app.thread_specs import (
    normalized_thread_parameters,
    validate_thread_edge_profile,
)
from cad_app.types import SelectionKind

__all__ = [
    "CommandError",
    "InvalidShapeError",
    "OperationFailedError",
    "UnsupportedTopologyError",
    "add_circle_feature",
    "apply_boolean_bodies",
    "apply_chamfer_edge",
    "apply_circle_feature",
    "apply_extrude_face",
    "apply_fillet_edge",
    "apply_move_edge_controlled",
    "apply_move_face_controlled",
    "apply_move_face_normal",
    "apply_move_object",
    "apply_thread_to_edge",
    "apply_move_vertex_controlled",
    "apply_remove_face",
    "apply_rotate_object",
    "boolean_bodies",
    "chamfer_edge",
    "cleanup_shape",
    "edge_supports_direct_round",
    "extrude_face",
    "face_normal_vector",
    "fillet_edge",
    "fillet_edges",
    "circular_edge_parameters",
    "move_edge_controlled",
    "move_face_controlled",
    "move_face_normal",
    "move_shape",
    "move_vertex_controlled",
    "rotate_shape",
    "rotated_shape",
    "supports_move_edge_controlled",
    "supports_move_face_controlled",
    "thread_default_length",
    "thread_edge",
    "supports_move_vertex_controlled",
    "top_planar_face_index",
    "translated_shape",
    "validate_shape",
]

if TYPE_CHECKING:
    from OCP.TopoDS import TopoDS_Shape

    from cad_app.scene import Scene


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


def _replace_shape_splitting_disconnected(
    scene: Scene,
    item_id: str,
    shape: TopoDS_Shape,
    meta: dict | None,
    *,
    split_source: str,
) -> TopoDS_Shape:
    """Replace ``item_id`` with ``shape``; if the shape contains more
    than one disconnected solid, keep the largest on the original item
    and add each remaining piece as its own scene body.

    The original item keeps its feature history on the largest piece
    so re-running the recorded step still produces the same compound
    on replay (the split is re-applied here). Smaller pieces become
    new bodies with no history but a ``source`` and ``parent_item_id``
    tag so the browser can show where they came from.
    """
    solids = _extract_disconnected_solids(shape)
    if len(solids) <= 1:
        scene.replace_shape(item_id, shape, meta=meta)
        return shape

    solids_by_size = sorted(solids, key=_solid_volume, reverse=True)
    primary, extras = solids_by_size[0], solids_by_size[1:]
    with scene.transaction():
        scene.replace_shape(item_id, primary, meta=meta)
        for extra in extras:
            scene.add_shape(
                extra,
                meta={
                    "kind": "body",
                    "source": split_source,
                    "parent_item_id": item_id,
                },
            )
    return primary


def apply_extrude_face(
    scene: Scene,
    item_id: str,
    face_index: int,
    distance: float,
) -> TopoDS_Shape:
    """Apply extrude to a scene object after successful validation.

    If the extrude (cut) chops the body into multiple disconnected
    solids, split them into separate scene items so each piece is
    selectable and movable independently.
    """
    scene_object = scene.get(item_id)
    step = capture_extrude_face_step(scene_object.shape, face_index, distance)
    result = extrude_face(scene_object.shape, face_index, distance)
    new_meta = append_feature_step(scene_object.meta, scene_object.shape, step)
    return _replace_shape_splitting_disconnected(
        scene,
        item_id,
        result,
        new_meta,
        split_source="extrude_split",
    )


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


def circular_edge_parameters(
    shape: TopoDS_Shape,
    edge_index: int,
) -> tuple[tuple[float, float, float], tuple[float, float, float], float]:
    """Return center, normal axis, and radius for a circular edge."""
    validate_shape(shape)
    edge = _edge_by_index(shape, edge_index)

    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Circle

    curve = BRepAdaptor_Curve(edge)
    if curve.GetType() != GeomAbs_Circle:
        raise UnsupportedTopologyError("Thread requires a circular edge.")
    circle = curve.Circle()
    center = circle.Location()
    direction = circle.Axis().Direction()
    radius = float(circle.Radius())
    if radius <= 1e-7:
        raise UnsupportedTopologyError("Circular edge radius is too small.")
    return (
        (center.X(), center.Y(), center.Z()),
        _unit_vector((direction.X(), direction.Y(), direction.Z())),
        radius,
    )


def thread_default_length(
    shape: TopoDS_Shape,
    axis: tuple[float, float, float],
    *,
    edge_radius: float | None = None,
) -> float:
    """Return a practical default thread length.

    The raw projected span of the body along the thread axis is a useful
    upper bound, but on its own it is a terrible default for a beginner.
    On a tall body with a shallow hole the dialog used to propose the
    full body height, producing thread coils dangling far past the hole.

    Rule of thumb for fasteners: thread length about 2.5 x major
    diameter (so 5 x edge radius). When we know the edge radius, cap
    the default at that rule. Always cap at the actual body span as
    well, so the thread never escapes the solid.
    """
    min_projection, max_projection = _shape_projection_bounds(shape, axis)
    span = max_projection - min_projection
    if span <= 1e-7:
        span = 20.0

    if edge_radius is not None and edge_radius > 0:
        recommended = max(2.0, edge_radius * 5.0)
        return float(min(span, recommended))

    # Without an edge radius we still cap at a generic 30 mm to keep the
    # default usable on large bodies; the dialog can still let the user
    # raise it manually for through-bolts.
    return float(min(span, 30.0))


def thread_edge(
    shape: TopoDS_Shape,
    edge_index: int,
    pitch: float,
    length: float,
    depth: float,
    *,
    mode: str = "modeled",
    thread_type: str = "auto",
    standard: str = "custom",
    size: str = "custom",
    major_diameter: float | None = None,
    minor_diameter: float | None = None,
) -> TopoDS_Shape:
    """Add an approximate modeled thread from a selected circular edge."""
    params = normalized_thread_parameters(
        pitch=pitch,
        length=length,
        depth=depth,
        mode=mode,
        thread_type=thread_type,
        standard=standard,
        size=size,
        major_diameter=major_diameter,
        minor_diameter=minor_diameter,
    )
    validate_shape(shape)

    center, axis, radius = circular_edge_parameters(shape, edge_index)
    validate_thread_edge_profile(params, radius * 2.0)
    if params["mode"] == "cosmetic":
        return shape
    axis = _axis_toward_shape_span(shape, center, axis)
    internal = (
        _thread_is_internal(shape, center, axis, radius, length)
        if params["thread_type"] == "auto"
        else params["thread_type"] == "internal"
    )
    thread_shape = _thread_solid(
        center,
        axis,
        radius,
        pitch,
        length,
        depth,
        internal=internal,
    )

    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse

    operation_cls = BRepAlgoAPI_Cut if internal else BRepAlgoAPI_Fuse
    return _run_boolean(shape, thread_shape, operation_cls, "Thread failed.")


def apply_thread_to_edge(
    scene: Scene,
    item_id: str,
    edge_index: int,
    pitch: float,
    length: float,
    depth: float,
    *,
    mode: str = "modeled",
    thread_type: str = "auto",
    standard: str = "custom",
    size: str = "custom",
    major_diameter: float | None = None,
    minor_diameter: float | None = None,
) -> TopoDS_Shape:
    """Apply a thread feature to a selected circular edge."""
    scene_object = scene.get(item_id)
    params = normalized_thread_parameters(
        pitch=pitch,
        length=length,
        depth=depth,
        mode=mode,
        thread_type=thread_type,
        standard=standard,
        size=size,
        major_diameter=major_diameter,
        minor_diameter=minor_diameter,
    )
    step = capture_thread_step(scene_object.shape, edge_index, params)
    result = thread_edge(
        scene_object.shape,
        edge_index,
        pitch,
        length,
        depth,
        mode=mode,
        thread_type=thread_type,
        standard=standard,
        size=size,
        major_diameter=major_diameter,
        minor_diameter=minor_diameter,
    )
    meta = {
        **scene_object.meta,
        "last_operation": "thread",
        "thread_pitch": pitch,
        "thread_length": length,
        "thread_depth": depth,
        "thread_mode": mode,
        "thread_type": thread_type,
        "thread_standard": standard,
        "thread_size": size,
    }
    scene.replace_shape(
        item_id,
        result,
        meta=append_feature_step(meta, scene_object.shape, step),
    )
    return result


def _thread_solid(
    center: tuple[float, float, float],
    axis: tuple[float, float, float],
    radius: float,
    pitch: float,
    length: float,
    depth: float,
    *,
    internal: bool,
) -> TopoDS_Shape:
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections

    overlap = max(min(depth * 0.2, radius * 0.05), 0.01)
    if internal:
        root_radius = radius + overlap
        crest_radius = max(radius - depth, 0.001)
    else:
        root_radius = max(radius - overlap, 0.001)
        crest_radius = radius + depth

    turns = length / pitch
    steps = max(18, min(360, int(math.ceil(turns * 24.0))))
    half_pitch = min(pitch * 0.25, length * 0.25)
    basis_u, basis_v = _perpendicular_basis(axis)
    loft = BRepOffsetAPI_ThruSections(True, False, 1e-6)
    for index in range(steps + 1):
        fraction = index / steps
        angle = 2.0 * math.pi * turns * fraction
        axial_distance = length * fraction
        root_before = max(0.0, axial_distance - half_pitch)
        root_after = min(length, axial_distance + half_pitch)
        radial = _radial_direction(basis_u, basis_v, angle)
        polygon = BRepBuilderAPI_MakePolygon()
        polygon.Add(
            _axis_radius_point(
                center,
                axis,
                radial,
                root_before,
                root_radius,
            )
        )
        polygon.Add(
            _axis_radius_point(
                center,
                axis,
                radial,
                axial_distance,
                crest_radius,
            )
        )
        polygon.Add(
            _axis_radius_point(
                center,
                axis,
                radial,
                root_after,
                root_radius,
            )
        )
        polygon.Close()
        if not polygon.IsDone():
            raise OperationFailedError("Thread section could not be built.")
        loft.AddWire(polygon.Wire())

    loft.CheckCompatibility(False)
    loft.Build()
    if not loft.IsDone():
        raise OperationFailedError("Thread sweep failed.")
    result = loft.Shape()
    validate_shape(result)
    return cleanup_shape(result)


def _thread_is_internal(
    shape: TopoDS_Shape,
    center: tuple[float, float, float],
    axis: tuple[float, float, float],
    radius: float,
    length: float,
) -> bool:
    probe_offset = min(length * 0.5, thread_default_length(shape, axis) * 0.5)
    radial, _basis_v = _perpendicular_basis(axis)
    epsilon = max(radius * 0.03, 0.05)
    inner_radius = max(radius - epsilon, 0.001)
    outer_radius = radius + epsilon
    inner_state = _solid_contains_point(
        shape,
        _tuple_axis_radius_point(center, axis, radial, probe_offset, inner_radius),
    )
    outer_state = _solid_contains_point(
        shape,
        _tuple_axis_radius_point(center, axis, radial, probe_offset, outer_radius),
    )
    return bool(outer_state and not inner_state)


def _solid_contains_point(
    shape: TopoDS_Shape,
    point: tuple[float, float, float],
) -> bool:
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON

    classifier = BRepClass3d_SolidClassifier(shape, gp_Pnt(*point), 1e-6)
    return classifier.State() in {TopAbs_IN, TopAbs_ON}


def _axis_toward_shape_span(
    shape: TopoDS_Shape,
    center: tuple[float, float, float],
    axis: tuple[float, float, float],
) -> tuple[float, float, float]:
    min_projection, max_projection = _shape_projection_bounds(shape, axis)
    center_projection = _dot3(center, axis)
    if abs(max_projection - center_projection) < abs(
        center_projection - min_projection
    ):
        return tuple(-component for component in axis)
    return axis


def _shape_projection_bounds(
    shape: TopoDS_Shape,
    axis: tuple[float, float, float],
) -> tuple[float, float]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    bounds = Bnd_Box()
    BRepBndLib.Add_s(shape, bounds)
    if bounds.IsVoid():
        raise ValueError("Shape bounds are empty.")
    x_min, y_min, z_min, x_max, y_max, z_max = bounds.Get()
    projections = [
        _dot3((x, y, z), axis)
        for x in (x_min, x_max)
        for y in (y_min, y_max)
        for z in (z_min, z_max)
    ]
    return min(projections), max(projections)


def _perpendicular_basis(
    axis: tuple[float, float, float],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    reference = (0.0, 0.0, 1.0)
    if abs(_dot3(axis, reference)) > 0.9:
        reference = (1.0, 0.0, 0.0)
    basis_u = _unit_vector(_cross3(axis, reference))
    basis_v = _unit_vector(_cross3(axis, basis_u))
    return basis_u, basis_v


def _axis_radius_point(
    center: tuple[float, float, float],
    axis: tuple[float, float, float],
    radial: tuple[float, float, float],
    axial_distance: float,
    radius: float,
):
    from OCP.gp import gp_Pnt

    return gp_Pnt(
        *_tuple_axis_radius_point(center, axis, radial, axial_distance, radius)
    )


def _tuple_axis_radius_point(
    center: tuple[float, float, float],
    axis: tuple[float, float, float],
    radial: tuple[float, float, float],
    axial_distance: float,
    radius: float,
) -> tuple[float, float, float]:
    return tuple(
        center_component + axis_component * axial_distance + radial_component * radius
        for center_component, axis_component, radial_component in zip(
            center,
            axis,
            radial,
        )
    )


def _radial_direction(
    basis_u: tuple[float, float, float],
    basis_v: tuple[float, float, float],
    angle: float,
) -> tuple[float, float, float]:
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return tuple(
        basis_u_component * cosine + basis_v_component * sine
        for basis_u_component, basis_v_component in zip(basis_u, basis_v)
    )


def _unit_vector(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(sum(component * component for component in vector))
    if length <= 1e-7:
        raise ValueError("Vector must be non-zero.")
    return tuple(component / length for component in vector)


def _cross3(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _dot3(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> float:
    return sum(
        first_component * second_component
        for first_component, second_component in zip(first, second)
    )


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
    """Apply body-body boolean, replacing target and removing the tool body.

    A subtract or intersect can leave the target as multiple
    disconnected solids - those become separate scene items so the
    user can grab each piece on its own.
    """
    if target_item_id == tool_item_id:
        raise ValueError("Boolean operation requires two different bodies.")

    target_object = scene.get(target_item_id)
    tool_object = scene.get(tool_item_id)
    result = boolean_bodies(target_object.shape, tool_object.shape, operation)
    new_meta = {
        **target_object.meta,
        "last_boolean_operation": operation,
        "last_boolean_tool_item_id": tool_item_id,
    }
    with scene.transaction():
        _replace_shape_splitting_disconnected(
            scene,
            target_item_id,
            result,
            new_meta,
            split_source="boolean_split",
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
    return _move_vertices_via_face_rebuild(
        shape,
        moved_vertex_indexes,
        dx,
        dy,
        dz,
        allow_nonplanar_faces=False,
    )


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


def remove_face(shape: TopoDS_Shape, face_index: int) -> TopoDS_Shape:
    """Remove one selected face and leave the remaining body as an open shell."""
    validate_shape(shape)
    face_map = Picker.indexed_map(shape, SelectionKind.FACE)
    if face_index < 1 or face_index > face_map.Extent():
        raise IndexError(f"Face index out of range: {face_index}")
    if face_map.Extent() <= 1:
        raise UnsupportedTopologyError("Remove Face requires at least two faces.")

    from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing

    sewing = BRepBuilderAPI_Sewing(1e-7)
    for index in range(1, face_map.Extent() + 1):
        if index == face_index:
            continue
        sewing.Add(face_map.FindKey(index))
    sewing.Perform()
    result = sewing.SewedShape()
    try:
        validate_shape(result)
    except InvalidShapeError as exc:
        raise UnsupportedTopologyError(
            "Remove Face produced invalid open-shell geometry."
        ) from exc
    return result


def apply_remove_face(
    scene: Scene,
    item_id: str,
    face_index: int,
) -> TopoDS_Shape:
    """Remove one face from a scene object without deleting the object."""
    scene_object = scene.get(item_id)
    result = remove_face(scene_object.shape, face_index)
    meta = {
        **scene_object.meta,
        "open_shell": True,
        "last_operation": "remove_face",
    }
    scene.replace_shape(item_id, result, meta=meta)
    scene.set_selection(None)
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
    """Move both vertices of an edge on a planar-faced solid.

    Always attempts convex hull vertex rebuild first. If the
    result preserves the original vertex count the shape is
    convex and the result is trusted. Otherwise falls back
    to face-by-face rebuild for non-convex bodies.
    """
    _validate_move_vector(dx, dy, dz)
    validate_shape(shape)
    edge = _edge_by_index(shape, edge_index)
    _assert_sharp_planar_edge(shape, edge)

    moved_vertex_indexes = _edge_vertex_indexes(shape, edge)
    original_vertex_count = Picker.indexed_map(shape, SelectionKind.VERTEX).Extent()

    try:
        result = _move_vertices_by_convex_rebuild(
            shape, moved_vertex_indexes, (dx, dy, dz)
        )
        result_vertex_count = Picker.indexed_map(result, SelectionKind.VERTEX).Extent()
        if result_vertex_count == original_vertex_count:
            return result
    except CommandError:
        pass
    except Exception as exc:
        if not _is_occt_exception(exc):
            raise

    return _move_edge_via_best_face(shape, edge_index, edge, dx, dy, dz)


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
    """Move one vertex by rebuilding only the affected faces."""
    _validate_move_vector(dx, dy, dz)
    validate_shape(shape)
    _vertex_by_index(shape, vertex_index)
    return _move_vertices_via_face_rebuild(
        shape,
        {vertex_index},
        dx,
        dy,
        dz,
        allow_nonplanar_faces=True,
    )


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
        _vertex_by_index(shape, vertex_index)
        for dx, dy, dz in (
            (1.0, 0.0, 0.0),
            (-1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, -1.0, 0.0),
            (0.0, 0.0, 1.0),
            (0.0, 0.0, -1.0),
        ):
            try:
                _move_vertices_via_face_rebuild(
                    shape,
                    {vertex_index},
                    dx,
                    dy,
                    dz,
                    allow_nonplanar_faces=True,
                )
                return True
            except CommandError:
                continue
    except (CommandError, IndexError, TypeError, AttributeError):
        return False
    return False
