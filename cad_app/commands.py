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
    _shape_has_solid,
    _solid_volume,
    _try_rebased_fillet,
    _updated_fillet_history,
    _validate_move_vector,
    _vertex_by_index,
    _workplane_from_face,
    edge_supports_direct_round,
    solidify_open_shell,
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
    "apply_mirror_body",
    "apply_move_edge_controlled",
    "apply_move_face_controlled",
    "apply_move_face_normal",
    "apply_move_face_oblique_shear",
    "apply_move_object",
    "apply_rib_between_faces",
    "apply_thread_to_edge",
    "apply_move_vertex_controlled",
    "apply_remove_face",
    "apply_rotate_object",
    "boolean_bodies",
    "chamfer_edge",
    "cleanup_shape",
    "cylinder_axis_world_line",
    "edge_supports_direct_round",
    "extrude_face",
    "face_normal_vector",
    "fillet_edge",
    "fillet_edges",
    "circle_axis_world_line",
    "circular_edge_parameters",
    "cylindrical_face_anchor_edge_index",
    "cylindrical_face_parameters",
    "distance_between_axes",
    "is_oblique_shear_body",
    "mirror_shape",
    "move_edge_controlled",
    "move_face_controlled",
    "move_face_normal",
    "move_face_oblique_shear",
    "move_shape",
    "move_vertex_controlled",
    "rotate_shape",
    "rotated_shape",
    "supports_move_edge_controlled",
    "supports_move_face_controlled",
    "supports_move_face_oblique_shear",
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

    # A body left open by Remove Face is a shell, not a solid, so the
    # boolean below would fail. Seal it back into a solid first; the
    # picked face is preserved through sealing, so the prism still lands
    # on it. Raises a clear UnsupportedTopologyError when the opening
    # cannot be capped (e.g. a removed curved wall).
    target = shape if _shape_has_solid(shape) else solidify_open_shell(shape)

    operation_cls = BRepAlgoAPI_Fuse if distance > 0 else BRepAlgoAPI_Cut
    return _run_boolean(
        target, prism, operation_cls, "Extrude boolean operation failed."
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
    # If the body was an open shell (Remove Face) and extrude resealed it,
    # it is a closed solid again - drop the stale open-shell tag.
    if new_meta.get("open_shell") and _shape_has_solid(result):
        new_meta = {
            key: value for key, value in new_meta.items() if key != "open_shell"
        }
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


def cylindrical_face_parameters(
    shape: TopoDS_Shape,
    face_index: int,
) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    float,
    float,
]:
    """Return (axis_anchor, axis_direction, radius, length) for a cylindrical
    face. ``axis_anchor`` is the midpoint of the face along the axis, so it
    sits inside the body and can be used as the thread centre.

    Raises ``UnsupportedTopologyError`` if the selected face isn't a
    cylinder. The face's length along the axis is read from the
    parametric V range (``[vmin, vmax] * radius`` is wrong - the V range
    on an OCCT cylinder is already in axial units), which works whether
    the face is the full body lateral or a trimmed segment.
    """
    validate_shape(shape)
    face = _face_by_index(shape, face_index)

    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder

    surface = BRepAdaptor_Surface(face)
    if surface.GetType() != GeomAbs_Cylinder:
        raise UnsupportedTopologyError("Thread on face requires a cylindrical face.")
    cylinder = surface.Cylinder()
    radius = float(cylinder.Radius())
    if radius <= 1e-7:
        raise UnsupportedTopologyError("Cylindrical face radius is too small.")
    axis_dir = cylinder.Axis().Direction()
    direction = _unit_vector((axis_dir.X(), axis_dir.Y(), axis_dir.Z()))
    location = cylinder.Axis().Location()

    # OCCT cylindrical surfaces parametrise V along the axis (in mm) and
    # U around the circumference (in radians). FirstVParameter /
    # LastVParameter give the axial extent of the trimmed face.
    vmin = float(surface.FirstVParameter())
    vmax = float(surface.LastVParameter())
    length = max(0.0, vmax - vmin)
    if length <= 1e-7:
        raise UnsupportedTopologyError(
            "Cylindrical face has zero length along its axis."
        )
    midv = 0.5 * (vmin + vmax)
    center = (
        location.X() + midv * direction[0],
        location.Y() + midv * direction[1],
        location.Z() + midv * direction[2],
    )
    return center, direction, radius, length


def cylindrical_face_anchor_edge_index(
    shape: TopoDS_Shape,
    face_index: int,
) -> int:
    """Return the index of one of the cylindrical face's circular end
    edges. Threads are built relative to a circular edge, so when the
    user picks the cylindrical FACE we still need an anchor edge for
    ``apply_thread_to_edge``. Returns the lower-along-axis circle so
    external threads start at the base and run upward.
    """
    validate_shape(shape)
    face = _face_by_index(shape, face_index)
    _center, axis, _radius, _length = cylindrical_face_parameters(shape, face_index)

    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Circle
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    edge_map = Picker.indexed_map(shape, SelectionKind.EDGE)
    best_index: int | None = None
    best_projection = float("inf")
    explorer = TopExp_Explorer(face, TopAbs_EDGE)
    while explorer.More():
        edge = TopoDS.Edge_s(explorer.Current())
        curve = BRepAdaptor_Curve(edge)
        if curve.GetType() == GeomAbs_Circle:
            index = edge_map.FindIndex(edge)
            if index > 0:
                # Mid-arc point on the circle, projected onto the axis -
                # the lower one (most negative projection) is the base.
                point = curve.Value(
                    0.5 * (curve.FirstParameter() + curve.LastParameter())
                )
                projection = (
                    point.X() * axis[0] + point.Y() * axis[1] + point.Z() * axis[2]
                )
                if projection < best_projection:
                    best_projection = projection
                    best_index = index
        explorer.Next()
    if best_index is None:
        raise UnsupportedTopologyError(
            "Cylindrical face has no circular edge to anchor the thread."
        )
    return best_index


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
    _assert_all_faces_planar(shape, context="Sideways face move")
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
        _assert_all_faces_planar(shape, context="Sideways face move")
        _face_vertex_indexes(shape, face)
    except (CommandError, IndexError, TypeError, AttributeError):
        return False
    return True


def _is_planar_face(face) -> bool:
    from cad_app.command_topology import _is_planar_face as _impl

    return _impl(face)


def _face_outer_wire(face):
    from OCP.BRepTools import BRepTools

    return BRepTools.OuterWire_s(face)


def _translated_wire(wire, dx: float, dy: float, dz: float):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf, gp_Vec
    from OCP.TopoDS import TopoDS

    transform = gp_Trsf()
    transform.SetTranslation(gp_Vec(dx, dy, dz))
    return TopoDS.Wire_s(BRepBuilderAPI_Transform(wire, transform, True).Shape())


def _local_shear_context(shape: TopoDS_Shape, face_index: int):
    """Walk the topology around ``face_index`` and identify the local
    feature it caps. Returns a dict with the moved face, its outer wire,
    the set of curved lateral faces immediately adjacent to that wire,
    and the wire formed by the OTHER-end edges of those laterals.

    Returns ``None`` if the topology doesn't match a closed cap → curved
    lateral → bottom-wire pattern - e.g. a prism (planar neighbours), a
    sphere (no curved-lateral loop), or a body where the laterals don't
    close back into a single wire on the other side.

    This is the basis for both ``supports_move_face_oblique_shear`` and
    the apply path. Using LOCAL topology (just the moved face and its
    immediate lateral chain) lets the shear work on stacked cylinders /
    fused features where there are more than two planar faces globally
    but the moved cap still tops a single curved-lateral feature.
    """
    try:
        validate_shape(shape)
        moved_face = _face_by_index(shape, face_index)
        if not _is_planar_face(moved_face):
            return None

        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeWire
        from OCP.TopAbs import TopAbs_EDGE, TopAbs_WIRE
        from OCP.TopExp import TopExp, TopExp_Explorer
        from OCP.TopoDS import TopoDS
        from OCP.TopTools import TopTools_IndexedMapOfShape

        # The moved cap must be a single-loop face. A cap with an
        # internal wire (an annulus) would need each loop paired with a
        # matching loop on the bottom; punt on that until needed.
        wire_explorer = TopExp_Explorer(moved_face, TopAbs_WIRE)
        wire_count = 0
        while wire_explorer.More():
            wire_count += 1
            if wire_count > 1:
                return None
            wire_explorer.Next()
        if wire_count != 1:
            return None

        top_wire = _face_outer_wire(moved_face)
        top_edges = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(top_wire, TopAbs_EDGE, top_edges)
        if top_edges.Extent() == 0:
            return None

        face_map = Picker.indexed_map(shape, SelectionKind.FACE)
        lateral_faces = []
        lateral_seen: set[int] = set()
        for fi in range(1, face_map.Extent() + 1):
            if fi == face_index:
                continue
            face = TopoDS.Face_s(face_map.FindKey(fi))
            face_edges = TopTools_IndexedMapOfShape()
            TopExp.MapShapes_s(face, TopAbs_EDGE, face_edges)
            shares_edge = False
            for ei in range(1, top_edges.Extent() + 1):
                if face_edges.Contains(top_edges.FindKey(ei)):
                    shares_edge = True
                    break
            if shares_edge:
                if fi not in lateral_seen:
                    lateral_seen.add(fi)
                    lateral_faces.append(face)
        if not lateral_faces:
            return None

        # A planar neighbour means the moved face borders another flat
        # face directly (prism scenario). ``move_face_controlled``
        # handles those; leaving them out keeps the shear path's
        # responsibility narrow.
        for lateral in lateral_faces:
            if _is_planar_face(lateral):
                return None

        # Collect the OTHER-end edges of the laterals - everything they
        # bound that isn't already on the moved cap. SKIP seam edges of
        # periodic cylindrical surfaces: those only border the lateral
        # face itself (no other face shares them), so they're internal
        # parametric markers, not real geometric boundaries. Including
        # the seam pollutes the bottom wire (it picks up the vertical
        # ruling alongside the bottom circle) and breaks the loft.
        def _edge_is_seam(edge, owning_lateral):
            # Real boundary edges are shared between the lateral and
            # SOME other face in the shape (the moved cap, the step
            # annulus, the bottom cap). Seam edges of a closed periodic
            # surface appear only on the lateral itself - test by
            # checking every other face of the body for the edge.
            for fi in range(1, face_map.Extent() + 1):
                other = TopoDS.Face_s(face_map.FindKey(fi))
                if other.IsSame(owning_lateral):
                    continue
                other_edges = TopTools_IndexedMapOfShape()
                TopExp.MapShapes_s(other, TopAbs_EDGE, other_edges)
                if other_edges.Contains(edge):
                    return False
            return True

        bottom_edges = TopTools_IndexedMapOfShape()
        for lateral in lateral_faces:
            edges = TopTools_IndexedMapOfShape()
            TopExp.MapShapes_s(lateral, TopAbs_EDGE, edges)
            for ei in range(1, edges.Extent() + 1):
                edge = edges.FindKey(ei)
                if top_edges.Contains(edge):
                    continue
                if _edge_is_seam(edge, lateral):
                    continue
                bottom_edges.Add(edge)
        if bottom_edges.Extent() == 0:
            return None

        wire_builder = BRepBuilderAPI_MakeWire()
        for ei in range(1, bottom_edges.Extent() + 1):
            edge = TopoDS.Edge_s(bottom_edges.FindKey(ei))
            wire_builder.Add(edge)
        if not wire_builder.IsDone():
            return None
        bottom_wire = wire_builder.Wire()
        if not bottom_wire.Closed():
            return None

        return {
            "moved_face": moved_face,
            "lateral_faces": lateral_faces,
            "top_wire": top_wire,
            "bottom_wire": bottom_wire,
        }
    except (CommandError, IndexError, TypeError, AttributeError):
        return None


def supports_move_face_oblique_shear(
    shape: TopoDS_Shape,
    face_index: int,
) -> bool:
    """True when ``face_index`` caps a single curved-lateral feature on
    the body. Covers a free-standing cylinder / frustum AND the cap of a
    fused feature on top of another body (sketch + extrude on a
    cylinder), as long as the laterals close back into one wire on the
    bottom of the feature.

    Excludes all-planar bodies (prism / box - handled by
    ``move_face_controlled``), spheres (no lateral chain), and tori
    (laterals don't close into a single wire).
    """
    return _local_shear_context(shape, face_index) is not None


def _face_centroid(face) -> tuple[float, float, float]:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    point = props.CentreOfMass()
    return point.X(), point.Y(), point.Z()


def _wire_centroid(wire) -> tuple[float, float, float] | None:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.LinearProperties_s(wire, props)
    if props.Mass() < 1e-12:
        return None
    point = props.CentreOfMass()
    return point.X(), point.Y(), point.Z()


def is_oblique_shear_body(shape: TopoDS_Shape, face_index: int) -> bool:
    """True when the local feature capped by ``face_index`` already
    leans: the line from the bottom-wire centroid to the moved-face
    centroid is NOT parallel to the moved face's normal.

    Push-pull along the cap normal on such a feature cannot go through
    ``extrude_face`` (boolean prism cut) because the existing lateral
    surface is not the straight prism ``extrude_face`` would subtract.
    Without this detection the user sees the cap slide along the
    normal while the oblique walls stay anchored - "face lowers
    without walls lowering".

    Uses the local feature's bottom wire (not the body's far cap) so
    the detection works on stacked / fused features too, not just on
    a free-standing cylinder.
    """
    context = _local_shear_context(shape, face_index)
    if context is None:
        return False
    try:
        moved_normal = _planar_face_normal(context["moved_face"])
        nx, ny, nz = moved_normal.X(), moved_normal.Y(), moved_normal.Z()
        moved_center = _face_centroid(context["moved_face"])
        bottom_center = _wire_centroid(context["bottom_wire"])
        if bottom_center is None:
            return False
        cx = moved_center[0] - bottom_center[0]
        cy = moved_center[1] - bottom_center[1]
        cz = moved_center[2] - bottom_center[2]
        connector_length_sq = cx * cx + cy * cy + cz * cz
        if connector_length_sq < 1e-12:
            return False
        normal_length_sq = nx * nx + ny * ny + nz * nz
        if normal_length_sq < 1e-12:
            return False
        projection = cx * nx + cy * ny + cz * nz
        projection_sq = projection * projection / normal_length_sq
        return connector_length_sq - projection_sq > 1e-6 * connector_length_sq
    except (CommandError, IndexError, TypeError, AttributeError):
        return False


def _loft_solid_between_wires(bottom_wire, top_wire) -> TopoDS_Shape:
    """Build a ruled solid between two wires. Used to assemble both the
    old upper-section tool (which must match the existing topology so
    Boolean Cut removes it cleanly) and the new sheared upper-section
    tool (which Boolean Fuse adds back in)."""
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections

    # ruled=True keeps the lateral surface as straight rulings between
    # corresponding wire points - the existing upper cylinder is
    # exactly such a ruled surface, so Boolean Cut subtracts it
    # without leaving sliver faces behind.
    loft = BRepOffsetAPI_ThruSections(True, True, 1e-6)
    loft.AddWire(bottom_wire)
    loft.AddWire(top_wire)
    loft.CheckCompatibility(True)
    loft.Build()
    if not loft.IsDone():
        raise OperationFailedError("Oblique face move loft failed.")
    return loft.Shape()


def move_face_oblique_shear(
    shape: TopoDS_Shape,
    face_index: int,
    dx: float,
    dy: float,
    dz: float,
) -> TopoDS_Shape:
    """Shear a planar cap and its curved-lateral feature by translating
    the cap's wire by (dx,dy,dz) and re-lofting the lateral surface.

    Works in two regimes:

    * Whole-body cap (free cylinder / frustum): the local context's
      bottom wire is the body's opposite cap, so the rebuilt loft IS
      the whole new body.
    * Local feature (sketch + extrude fused on top of another body):
      the bottom wire belongs to an internal planar face (the step
      annulus's inner wire). Subtract the old upper-section solid out
      of the body and fuse the new sheared upper-section back in -
      this leaves the lower body intact while tilting only the local
      feature the user clicked.
    """
    _validate_move_vector(dx, dy, dz)
    validate_shape(shape)
    context = _local_shear_context(shape, face_index)
    if context is None:
        raise UnsupportedTopologyError(
            "Oblique face move requires a cap on a body with curved sides."
        )
    top_wire = context["top_wire"]
    bottom_wire = context["bottom_wire"]
    translated_top = _translated_wire(top_wire, dx, dy, dz)

    new_upper = _loft_solid_between_wires(bottom_wire, translated_top)
    validate_shape(new_upper)

    face_map = Picker.indexed_map(shape, SelectionKind.FACE)
    # Free-standing case: the moved cap and its bottom-wire enclose
    # the entire body. Skip the Cut+Fuse round-trip - the loft IS the
    # result. The face-count probe is a cheap way to recognise this
    # (exactly two planar caps + N curved laterals); for any local
    # feature on a larger body there will be additional faces.
    is_free_standing = face_map.Extent() == 1 + len(context["lateral_faces"]) + 1
    if is_free_standing:
        return cleanup_shape(new_upper)

    old_upper = _loft_solid_between_wires(bottom_wire, top_wire)
    validate_shape(old_upper)

    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse

    base = _run_boolean(
        shape,
        old_upper,
        BRepAlgoAPI_Cut,
        "Oblique shear: removing original feature failed.",
    )
    fused = _run_boolean(
        base,
        new_upper,
        BRepAlgoAPI_Fuse,
        "Oblique shear: fusing sheared feature failed.",
    )
    validate_shape(fused)
    return cleanup_shape(fused)


def apply_move_face_oblique_shear(
    scene: Scene,
    item_id: str,
    face_index: int,
    dx: float,
    dy: float,
    dz: float,
) -> TopoDS_Shape:
    """Apply oblique face shear to a scene object."""
    scene_object = scene.get(item_id)
    result = move_face_oblique_shear(scene_object.shape, face_index, dx, dy, dz)
    scene.replace_shape(item_id, result)
    return result


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


# ---------------------------------------------------------------------------
# Mirror, hole, rib, and axis-distance helpers (Q2 features).
# ---------------------------------------------------------------------------


_MIRROR_PLANE_NORMALS: dict[str, tuple[float, float, float]] = {
    "xy": (0.0, 0.0, 1.0),
    "yz": (1.0, 0.0, 0.0),
    "xz": (0.0, 1.0, 0.0),
}


def mirror_shape(
    shape: TopoDS_Shape,
    plane: str = "yz",
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> TopoDS_Shape:
    """Reflect ``shape`` across one of the three world coordinate planes.

    ``plane`` is one of ``"xy"`` / ``"yz"`` / ``"xz"`` and names the
    mirror plane itself, not its normal. The reflection is taken about
    ``origin`` on that plane so users can mirror about an offset plane
    (e.g. mirror about X = -10) without first translating the body.
    """
    plane_normalised = plane.lower().strip()
    if plane_normalised not in _MIRROR_PLANE_NORMALS:
        raise ValueError(
            f"Unsupported mirror plane: {plane!r}. Use 'xy', 'yz', or 'xz'."
        )
    validate_shape(shape)

    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf

    nx, ny, nz = _MIRROR_PLANE_NORMALS[plane_normalised]
    # SetMirror with a gp_Ax2 reflects across the plane defined by
    # that frame; the axis itself is the plane normal.
    frame = gp_Ax2(gp_Pnt(*origin), gp_Dir(nx, ny, nz))
    trsf = gp_Trsf()
    trsf.SetMirror(frame)
    result = BRepBuilderAPI_Transform(shape, trsf, True).Shape()
    validate_shape(result)
    return result


def apply_mirror_body(
    scene: Scene,
    item_id: str,
    plane: str = "yz",
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
    *,
    keep_original: bool = True,
) -> str:
    """Mirror the body identified by ``item_id`` across ``plane``.

    When ``keep_original`` is True (the default) the mirrored body is
    added as a NEW scene item and the original is left in place — this
    matches "Mirror" intent in most CAD apps. Setting it False replaces
    the original in place (sometimes useful for symmetric-feature
    rebuilds).

    Returns the item_id of the mirrored body (new or the original when
    replaced).
    """
    scene_object = scene.get(item_id)
    mirrored = mirror_shape(scene_object.shape, plane, origin)

    if not keep_original:
        scene.replace_shape(
            item_id,
            mirrored,
            meta={
                **scene_object.meta,
                "last_operation": "mirror",
                "mirror_plane": plane,
            },
        )
        return item_id
    meta = dict(scene_object.meta)
    meta.update(
        {
            "source": "mirror",
            "parent_item_id": item_id,
            "mirror_plane": plane,
        }
    )
    return scene.add_shape(mirrored, meta=meta)


# ---------------------------------------------------------------------------
# Axis-distance measurement.
# ---------------------------------------------------------------------------


def cylinder_axis_world_line(
    shape: TopoDS_Shape,
    face_index: int,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Return ``(origin, direction)`` of a cylindrical face's axis."""
    centre, axis, _radius, _length = cylindrical_face_parameters(shape, face_index)
    return centre, _unit_vector(axis)


def circle_axis_world_line(
    shape: TopoDS_Shape,
    edge_index: int,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Return ``(centre, normal)`` of a circular edge's axis line."""
    centre, axis, _radius = circular_edge_parameters(shape, edge_index)
    return centre, _unit_vector(axis)


def distance_between_axes(
    line_a: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
    ],
    line_b: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
    ],
) -> float:
    """Shortest distance between two infinite lines in world space."""
    p1, d1 = line_a
    p2, d2 = line_b
    u = _unit_vector(d1)
    v = _unit_vector(d2)
    w = (p1[0] - p2[0], p1[1] - p2[1], p1[2] - p2[2])
    cross = _cross3(u, v)
    cross_len = (cross[0] ** 2 + cross[1] ** 2 + cross[2] ** 2) ** 0.5
    if cross_len < 1e-9:
        # Parallel axes: distance from p1 to line through p2.
        proj = _dot3(w, v)
        diff = (w[0] - v[0] * proj, w[1] - v[1] * proj, w[2] - v[2] * proj)
        return (diff[0] ** 2 + diff[1] ** 2 + diff[2] ** 2) ** 0.5
    return abs(_dot3(w, cross)) / cross_len


# ---------------------------------------------------------------------------
# Rib tool (triangular bracket between two planar faces).
# ---------------------------------------------------------------------------


def apply_rib_between_faces(
    scene: Scene,
    item_id: str,
    base_face_index: int,
    wall_face_index: int,
    *,
    along_base: float,
    along_wall: float,
    thickness: float,
    offset_along_shared_edge: float = 0.0,
) -> TopoDS_Shape:
    """Add a triangular rib between two perpendicular planar faces.

    The two faces must share an edge in the body; the rib is built in
    the plane perpendicular to that shared edge, with one leg lying
    along the base face for ``along_base`` mm, one leg lying along the
    wall face for ``along_wall`` mm, and a hypotenuse closing the
    triangle. The rib is then thickened by ``thickness`` mm centred on
    ``offset_along_shared_edge`` (0 = centred on the edge's midpoint).
    """
    if along_base <= 0 or along_wall <= 0 or thickness <= 0:
        raise ValueError("Rib dimensions must be positive.")

    from cad_app.command_topology import _face_by_index as _face_at

    scene_object = scene.get(item_id)
    shape = scene_object.shape
    base_face = _face_at(shape, base_face_index)
    wall_face = _face_at(shape, wall_face_index)

    shared_edge = _shared_edge(shape, base_face_index, wall_face_index)
    if shared_edge is None:
        raise UnsupportedTopologyError(
            "Rib requires two faces that share an edge; pick a base "
            "face and a wall face that meet."
        )

    base_normal = _face_outward_normal(base_face)
    wall_normal = _face_outward_normal(wall_face)
    edge_origin, edge_direction = _edge_origin_and_direction(shared_edge)
    edge_unit = _unit_vector(edge_direction)

    # The rib triangle lives in the plane perpendicular to the shared
    # edge. We need two in-plane directions: one along the base face
    # surface, one along the wall face surface, both perpendicular to
    # the shared edge.
    along_base_dir = _unit_vector(_cross3(base_normal, edge_unit))
    along_wall_dir = _unit_vector(_cross3(wall_normal, edge_unit))

    # Pick the signed direction that points AWAY from the wall (along
    # the base surface, into the open side of the L) and AWAY from
    # the base (along the wall surface, upward). The "step outward"
    # test uses the opposing face's outward normal: along_base must
    # have a positive component along the wall's outward normal, and
    # along_wall must have a positive component along the base's
    # outward normal.
    along_base_dir = _orient_away_from(
        along_base_dir, edge_origin, wall_face, wall_normal
    )
    along_wall_dir = _orient_away_from(
        along_wall_dir, edge_origin, base_face, base_normal
    )

    half_thickness = thickness / 2.0
    edge_mid = _midpoint_on_edge(shared_edge)
    rib_centre = (
        edge_mid[0] + edge_unit[0] * offset_along_shared_edge,
        edge_mid[1] + edge_unit[1] * offset_along_shared_edge,
        edge_mid[2] + edge_unit[2] * offset_along_shared_edge,
    )

    p_corner = rib_centre
    p_along_base = (
        rib_centre[0] + along_base_dir[0] * along_base,
        rib_centre[1] + along_base_dir[1] * along_base,
        rib_centre[2] + along_base_dir[2] * along_base,
    )
    p_along_wall = (
        rib_centre[0] + along_wall_dir[0] * along_wall,
        rib_centre[1] + along_wall_dir[1] * along_wall,
        rib_centre[2] + along_wall_dir[2] * along_wall,
    )

    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeFace,
        BRepBuilderAPI_MakePolygon,
    )
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Pnt, gp_Vec

    polygon = BRepBuilderAPI_MakePolygon()
    polygon.Add(gp_Pnt(*p_corner))
    polygon.Add(gp_Pnt(*p_along_base))
    polygon.Add(gp_Pnt(*p_along_wall))
    polygon.Close()
    if not polygon.IsDone():
        raise OperationFailedError("Rib triangle could not be built.")
    face_builder = BRepBuilderAPI_MakeFace(polygon.Wire())
    if not face_builder.IsDone():
        raise OperationFailedError("Rib triangle face build failed.")
    rib_face = face_builder.Face()

    # Centre the prism on the shared edge by first translating the
    # face -half_thickness along the edge direction.
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf

    shift = gp_Trsf()
    shift.SetTranslation(
        gp_Vec(
            -edge_unit[0] * half_thickness,
            -edge_unit[1] * half_thickness,
            -edge_unit[2] * half_thickness,
        )
    )
    rib_face = BRepBuilderAPI_Transform(rib_face, shift, True).Shape()

    prism = BRepPrimAPI_MakePrism(
        rib_face,
        gp_Vec(
            edge_unit[0] * thickness,
            edge_unit[1] * thickness,
            edge_unit[2] * thickness,
        ),
    ).Shape()
    validate_shape(prism)

    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse

    result = _run_boolean(shape, prism, BRepAlgoAPI_Fuse, "Rib fuse failed.")
    meta = {
        **scene_object.meta,
        "last_operation": "rib",
        "rib_along_base": float(along_base),
        "rib_along_wall": float(along_wall),
        "rib_thickness": float(thickness),
    }
    scene.replace_shape(item_id, result, meta=meta)
    return result


def _shared_edge(
    shape: TopoDS_Shape,
    face_index_a: int,
    face_index_b: int,
):
    """Find an edge that bounds both face_index_a and face_index_b."""
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape

    face_map = Picker.indexed_map(shape, SelectionKind.FACE)
    if face_index_a == face_index_b:
        return None
    face_a = TopoDS.Face_s(face_map.FindKey(face_index_a))
    face_b = TopoDS.Face_s(face_map.FindKey(face_index_b))

    edges_a = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(face_a, TopAbs_EDGE, edges_a)
    edges_b = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(face_b, TopAbs_EDGE, edges_b)
    for i in range(1, edges_a.Extent() + 1):
        edge = edges_a.FindKey(i)
        if edges_b.Contains(edge):
            return TopoDS.Edge_s(edge)
    return None


def _face_outward_normal(face) -> tuple[float, float, float]:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.TopAbs import TopAbs_REVERSED

    surface = BRepAdaptor_Surface(face)
    if surface.GetType() != GeomAbs_Plane:
        raise UnsupportedTopologyError("Rib host faces must be planar.")
    normal = surface.Plane().Axis().Direction()
    nx, ny, nz = normal.X(), normal.Y(), normal.Z()
    if face.Orientation() == TopAbs_REVERSED:
        nx, ny, nz = -nx, -ny, -nz
    return (nx, ny, nz)


def _edge_origin_and_direction(edge):
    from OCP.BRepAdaptor import BRepAdaptor_Curve

    curve = BRepAdaptor_Curve(edge)
    p_start = curve.Value(curve.FirstParameter())
    p_end = curve.Value(curve.LastParameter())
    direction = (
        p_end.X() - p_start.X(),
        p_end.Y() - p_start.Y(),
        p_end.Z() - p_start.Z(),
    )
    return (p_start.X(), p_start.Y(), p_start.Z()), direction


def _midpoint_on_edge(edge) -> tuple[float, float, float]:
    from OCP.BRepAdaptor import BRepAdaptor_Curve

    curve = BRepAdaptor_Curve(edge)
    mid_param = (curve.FirstParameter() + curve.LastParameter()) * 0.5
    p = curve.Value(mid_param)
    return (p.X(), p.Y(), p.Z())


def _orient_away_from(
    direction: tuple[float, float, float],
    origin: tuple[float, float, float],
    opposite_face,
    opposite_face_normal: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Flip ``direction`` so that stepping from ``origin`` along it
    moves AWAY from the half-space the opposite face encloses.

    We rely on the opposite face's outward normal: stepping from a
    point on the shared edge in the rib direction should put us on
    the OUTWARD side of the opposite face (positive dot with the
    opposite face's outward normal). If not, flip.
    """
    probe = (
        origin[0] + direction[0],
        origin[1] + direction[1],
        origin[2] + direction[2],
    )
    relative = (
        probe[0] - origin[0],
        probe[1] - origin[1],
        probe[2] - origin[2],
    )
    if _dot3(relative, opposite_face_normal) < 0:
        return (-direction[0], -direction[1], -direction[2])
    return direction
