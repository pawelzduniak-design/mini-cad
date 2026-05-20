from __future__ import annotations

import pytest

from tests.conftest import require_ocp
from tests.helpers.topology import assert_valid_shape, bounding_box, count_subshapes


def _translate(shape, dx: float, dy: float, dz: float):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf, gp_Vec

    transform = gp_Trsf()
    transform.SetTranslation(gp_Vec(dx, dy, dz))
    return BRepBuilderAPI_Transform(shape, transform, True).Shape()


def _fuse(first, second):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse

    operation = BRepAlgoAPI_Fuse(first, second)
    operation.Build()
    assert operation.IsDone()
    return operation.Shape()


def _house_block():
    from cad_app.engine import make_box

    foundation = make_box(200.0, 100.0, 30.0)
    walls = _translate(make_box(160.0, 60.0, 60.0), 0.0, 0.0, 30.0)
    roof = _translate(make_box(180.0, 80.0, 30.0), 0.0, 0.0, 90.0)
    return _fuse(_fuse(foundation, walls), roof)


def _edge_index_by_midpoint(
    shape,
    *,
    axis_name: str,
    x: float | None = None,
    y: float | None = None,
    z: float | None = None,
    tolerance: float = 0.5,
) -> int:
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape

    from cad_app.measurement import edge_measurement

    edge_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_EDGE, edge_map)
    for index in range(1, edge_map.Extent() + 1):
        measurement = edge_measurement(TopoDS.Edge_s(edge_map.FindKey(index)))
        if measurement.axis_name != axis_name:
            continue
        mx, my, mz = measurement.midpoint
        if x is not None and abs(mx - x) > tolerance:
            continue
        if y is not None and abs(my - y) > tolerance:
            continue
        if z is not None and abs(mz - z) > tolerance:
            continue
        return index
    raise AssertionError("Expected edge was not found.")


def _face_index_by_normal_and_z(
    shape,
    *,
    normal_y: float,
    center_z: float,
    tolerance: float = 1.0,
) -> int:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape

    from cad_app.commands import face_normal_vector

    face_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, face_map)
    best: tuple[float, int] | None = None
    for index in range(1, face_map.Extent() + 1):
        nx, ny, nz = face_normal_vector(shape, index)
        if abs(ny - normal_y) > 0.05 or abs(nx) > 0.1 or abs(nz) > 0.1:
            continue
        bounds = Bnd_Box()
        BRepBndLib.AddOptimal_s(TopoDS.Face_s(face_map.FindKey(index)), bounds)
        _xmin, _ymin, zmin, _xmax, _ymax, zmax = bounds.Get()
        score = abs(((zmin + zmax) * 0.5) - center_z)
        if score > tolerance:
            continue
        if best is None or score < best[0]:
            best = (score, index)
    if best is None:
        raise AssertionError("Expected face was not found.")
    return best[1]


def _cut_wall_door_and_window(shape):
    from cad_app.command_topology import _face_by_index
    from cad_app.sketch import apply_profile_feature, make_center_rectangle_profile
    from cad_app.workplane import Workplane

    front_wall_index = _face_index_by_normal_and_z(shape, normal_y=-1.0, center_z=60.0)
    workplane = Workplane.from_face(_face_by_index(shape, front_wall_index))
    door = make_center_rectangle_profile(workplane, (-30.0, -25.0), (12.5, 25.0))
    window = make_center_rectangle_profile(workplane, (30.0, -15.0), (10.0, 10.0))
    wall_cut = apply_profile_feature(shape, door, -20.0)
    return apply_profile_feature(wall_cut, window, -20.0)


def _cut_roof_front(shape):
    from cad_app.command_topology import _face_by_index
    from cad_app.sketch import apply_profile_feature, make_center_rectangle_profile
    from cad_app.workplane import Workplane

    roof_front_index = _face_index_by_normal_and_z(shape, normal_y=-1.0, center_z=105.0)
    workplane = Workplane.from_face(_face_by_index(shape, roof_front_index))
    cutout = make_center_rectangle_profile(workplane, (-30.0, -10.0), (12.5, 10.0))
    return apply_profile_feature(shape, cutout, -20.0)


def _max_z_at_x(shape, x: float) -> float:
    from cad_app.command_topology import _shape_vertex_points

    return max(z for vx, _vy, z in _shape_vertex_points(shape) if abs(vx - x) < 0.5)


def test_move_edge_slopes_box_roof_without_expanding_bounds() -> None:
    require_ocp()

    from cad_app.commands import move_edge_controlled
    from cad_app.engine import make_box

    shape = make_box(40.0, 20.0, 20.0)
    edge_index = _edge_index_by_midpoint(shape, axis_name="Y", x=-20.0, z=20.0)

    moved = move_edge_controlled(shape, edge_index, 0.0, 0.0, -5.0)

    assert_valid_shape(moved)
    box = bounding_box(moved)
    assert box["height"] == pytest.approx(20.0, abs=1e-4)
    assert _max_z_at_x(moved, -20.0) == pytest.approx(15.0, abs=1e-4)
    assert _max_z_at_x(moved, 20.0) == pytest.approx(20.0, abs=1e-4)


def test_move_edge_slopes_house_roof_after_wall_sketch_cuts() -> None:
    require_ocp()

    from cad_app.commands import move_edge_controlled

    shape = _cut_wall_door_and_window(_house_block())
    edge_index = _edge_index_by_midpoint(shape, axis_name="Y", x=-90.0, z=120.0)

    moved = move_edge_controlled(shape, edge_index, 0.0, 0.0, -20.0)

    assert_valid_shape(moved)
    box = bounding_box(moved)
    assert box["width"] == pytest.approx(200.0, abs=1e-3)
    assert box["depth"] == pytest.approx(100.0, abs=1e-3)
    assert box["height"] == pytest.approx(120.0, abs=1e-3)
    assert _max_z_at_x(moved, -90.0) == pytest.approx(100.0, abs=1e-3)
    assert _max_z_at_x(moved, 90.0) == pytest.approx(120.0, abs=1e-3)


def test_move_edge_rejects_roof_cut_that_would_warp_geometry() -> None:
    require_ocp()

    from cad_app.commands import UnsupportedTopologyError, move_edge_controlled

    shape = _cut_roof_front(_house_block())
    edge_index = _edge_index_by_midpoint(shape, axis_name="Y", x=-90.0, z=120.0)
    before = bounding_box(shape)

    with pytest.raises(UnsupportedTopologyError):
        move_edge_controlled(shape, edge_index, 0.0, 0.0, -20.0)

    assert bounding_box(shape) == before


def test_move_face_and_vertex_controlled_keep_single_valid_solid() -> None:
    require_ocp()

    from cad_app.commands import (
        move_face_controlled,
        move_vertex_controlled,
        top_planar_face_index,
    )
    from cad_app.engine import make_box
    from cad_app.picker import Picker
    from cad_app.types import SelectionKind

    shape = make_box(30.0, 20.0, 10.0)
    face_moved = move_face_controlled(
        shape, top_planar_face_index(shape), 4.0, 0.0, 0.0
    )

    assert_valid_shape(face_moved)
    assert count_subshapes(face_moved, "solid") == 1
    assert bounding_box(face_moved)["width"] > bounding_box(shape)["width"]

    vertex_map = Picker.indexed_map(shape, SelectionKind.VERTEX)
    assert vertex_map.Extent() >= 1
    vertex_moved = move_vertex_controlled(shape, 1, 0.0, 0.0, 4.0)

    assert_valid_shape(vertex_moved)
    assert count_subshapes(vertex_moved, "solid") == 1
    assert bounding_box(vertex_moved)["height"] > bounding_box(shape)["height"]


def test_direct_modeling_rejects_zero_vectors_and_bad_round_sizes() -> None:
    require_ocp()

    from cad_app.commands import (
        chamfer_edge,
        fillet_edge,
        move_edge_controlled,
        move_face_controlled,
        move_shape,
        move_vertex_controlled,
    )
    from cad_app.engine import make_box

    shape = make_box(20.0, 20.0, 20.0)

    with pytest.raises(ValueError, match="non-zero"):
        move_shape(shape, 0.0, 0.0, 0.0)
    with pytest.raises(ValueError, match="non-zero"):
        move_face_controlled(shape, 1, 0.0, 0.0, 0.0)
    with pytest.raises(ValueError, match="non-zero"):
        move_edge_controlled(shape, 1, 0.0, 0.0, 0.0)
    with pytest.raises(ValueError, match="non-zero"):
        move_vertex_controlled(shape, 1, 0.0, 0.0, 0.0)
    with pytest.raises(ValueError, match="positive"):
        fillet_edge(shape, 1, 0.0)
    with pytest.raises(ValueError, match="positive"):
        chamfer_edge(shape, 1, -1.0)


def test_boolean_operations_and_scene_apply_contracts() -> None:
    require_ocp()

    from cad_app.commands import apply_boolean_bodies, boolean_bodies
    from cad_app.engine import make_box
    from cad_app.scene import Scene

    target = make_box(30.0, 20.0, 20.0)
    tool = _translate(make_box(30.0, 20.0, 20.0), 15.0, 0.0, 0.0)

    union = boolean_bodies(target, tool, "union")
    subtract = boolean_bodies(target, tool, "subtract")
    intersect = boolean_bodies(target, tool, "intersect")

    assert_valid_shape(union)
    assert_valid_shape(subtract)
    assert_valid_shape(intersect)
    assert bounding_box(union)["width"] > bounding_box(target)["width"]
    assert bounding_box(subtract)["width"] <= bounding_box(target)["width"]
    assert bounding_box(intersect)["width"] == pytest.approx(15.0, abs=1e-3)

    scene = Scene()
    target_id = scene.add_shape(target, meta={"kind": "body"})
    tool_id = scene.add_shape(tool, meta={"kind": "body"})
    result = apply_boolean_bodies(scene, target_id, tool_id, "union")

    assert_valid_shape(result)
    assert target_id in scene
    assert tool_id not in scene
    assert scene.get(target_id).meta["last_boolean_operation"] == "union"


def test_extract_disconnected_solids_separates_compound_into_pieces() -> None:
    """A compound that contains multiple independent solids must be
    reported as a list of those solids - that is the hook
    apply_extrude_face uses to spawn one scene item per piece when an
    extrude (cut) splits a body."""
    require_ocp()

    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    from cad_app.command_geometry import _extract_disconnected_solids, _solid_volume
    from cad_app.engine import make_box

    box_a = make_box(10.0, 10.0, 10.0)
    box_b = _translate(make_box(5.0, 5.0, 5.0), 50.0, 50.0, 50.0)

    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    builder.Add(compound, box_a)
    builder.Add(compound, box_b)

    solids = _extract_disconnected_solids(compound)
    assert len(solids) == 2
    volumes = sorted(_solid_volume(s) for s in solids)
    assert volumes[0] == pytest.approx(125.0, rel=1e-6)
    assert volumes[1] == pytest.approx(1000.0, rel=1e-6)

    single = _extract_disconnected_solids(box_a)
    assert len(single) == 1


def test_apply_boolean_bodies_splits_disconnected_result_into_scene_items(
    monkeypatch,
) -> None:
    """A subtract that severs the target into two pieces must spawn
    extra scene items. The tool body is still removed afterwards."""
    require_ocp()

    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    from cad_app.commands import apply_boolean_bodies
    from cad_app.engine import make_box
    from cad_app.scene import Scene

    target = make_box(40.0, 40.0, 40.0)
    tool = _translate(make_box(20.0, 20.0, 20.0), 10.0, 10.0, 10.0)

    big = make_box(15.0, 15.0, 15.0)
    small = _translate(make_box(5.0, 5.0, 5.0), 60.0, 0.0, 0.0)
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    builder.Add(compound, big)
    builder.Add(compound, small)

    def fake_boolean(_target, _tool, _op):
        return compound

    monkeypatch.setattr("cad_app.commands.boolean_bodies", fake_boolean)

    scene = Scene()
    target_id = scene.add_shape(target, meta={"kind": "body"})
    tool_id = scene.add_shape(tool, meta={"kind": "body"})

    apply_boolean_bodies(scene, target_id, tool_id, "subtract")

    item_ids = set(item.item_id for item in scene)
    assert tool_id not in item_ids, "Tool body must be removed after boolean"
    assert target_id in item_ids, "Target id must persist as the primary piece"
    assert (
        len(item_ids) == 2
    ), f"Expected target + one split-off body, got items={item_ids}"
    new_id = next(iid for iid in item_ids if iid != target_id)
    assert scene.get(new_id).meta.get("source") == "boolean_split"
    assert scene.get(new_id).meta.get("parent_item_id") == target_id


def test_move_face_normal_pushes_cylinder_top_cap() -> None:
    """A cylinder cap is planar but its neighbour (the lateral) is
    curved, so move_face_controlled rejects it. The Move-along-Normal
    path delegates to extrude_face and must succeed - otherwise the
    user can't push or pull a cylinder's top face."""
    require_ocp()

    from cad_app.commands import move_face_normal
    from cad_app.picker import Picker
    from cad_app.sketch import extrude_profile, make_circle_profile
    from cad_app.types import SelectionKind
    from cad_app.workplane import Workplane

    profile = make_circle_profile(Workplane.world_xy(), radius=20.0)
    cylinder = extrude_profile(profile, 50.0)

    top_index = None
    for index in range(
        1, Picker.indexed_map(cylinder, SelectionKind.FACE).Extent() + 1
    ):
        face = Picker.indexed_map(cylinder, SelectionKind.FACE).FindKey(index)
        if not Picker._is_planar_face(face):
            continue
        from cad_app.commands import face_normal_vector

        normal = face_normal_vector(cylinder, index)
        if normal[2] > 0.95:
            top_index = index
            break
    assert top_index is not None, "Cylinder must have a +Z top cap"

    pushed = move_face_normal(cylinder, top_index, 10.0)
    assert_valid_shape(pushed)
    assert bounding_box(pushed)["height"] == pytest.approx(60.0, abs=1e-3)

    pulled = move_face_normal(cylinder, top_index, -10.0)
    assert_valid_shape(pulled)
    assert bounding_box(pulled)["height"] == pytest.approx(40.0, abs=1e-3)


def test_move_face_oblique_shear_shifts_cylinder_top_sideways() -> None:
    """The user wants to drag a cylinder's top cap sideways and get an
    oblique cylinder back, instead of being told 'face on curved body
    only supports its normal axis'. move_face_oblique_shear must loft a
    new body from the stationary bottom cap to the translated top cap,
    keep the height, and extend the X bounds by the shear amount."""
    require_ocp()

    from cad_app.commands import (
        move_face_oblique_shear,
        supports_move_face_oblique_shear,
    )
    from cad_app.picker import Picker
    from cad_app.sketch import extrude_profile, make_circle_profile
    from cad_app.types import SelectionKind
    from cad_app.workplane import Workplane

    profile = make_circle_profile(Workplane.world_xy(), radius=20.0)
    cylinder = extrude_profile(profile, 50.0)

    from cad_app.commands import face_normal_vector

    top_index = None
    for index in range(
        1, Picker.indexed_map(cylinder, SelectionKind.FACE).Extent() + 1
    ):
        face = Picker.indexed_map(cylinder, SelectionKind.FACE).FindKey(index)
        if not Picker._is_planar_face(face):
            continue
        normal = face_normal_vector(cylinder, index)
        if normal[2] > 0.95:
            top_index = index
            break
    assert top_index is not None

    assert supports_move_face_oblique_shear(cylinder, top_index)

    shear_distance = 8.0
    sheared = move_face_oblique_shear(cylinder, top_index, shear_distance, 0.0, 0.0)
    assert_valid_shape(sheared)

    # OCCT's default Bnd_Box is conservative for B-spline lateral
    # surfaces, so use AddOptimal_s for a tight check against the
    # actual sheared geometry.
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    tight = Bnd_Box()
    BRepBndLib.AddOptimal_s(sheared, tight)
    xmin, ymin, zmin, xmax, ymax, zmax = tight.Get()
    # Height preserved (top cap stays at z=50, bottom at z=0).
    assert zmax - zmin == pytest.approx(50.0, abs=1e-3)
    # Y stays at the cylinder's original radius - shear is along X only.
    assert ymin == pytest.approx(-20.0, abs=1e-3)
    assert ymax == pytest.approx(20.0, abs=1e-3)
    # X bound widened by the shear distance; original was -20..+20,
    # sheared top reaches +20 + 8 = +28.
    assert xmin == pytest.approx(-20.0, abs=1e-3)
    assert xmax == pytest.approx(28.0, abs=1e-3)


def test_normal_push_on_already_sheared_cylinder_lowers_walls() -> None:
    """User flow: shear a cylinder top sideways, then press Move along
    the cap's normal expecting to shorten the whole oblique cylinder.
    The pre-fix code routed that push through ``extrude_face`` (boolean
    cut by a STRAIGHT prism), which sliced through the cap but left the
    oblique side walls anchored at the previous height - the user saw
    'face lowers without walls lowering'. ``is_oblique_shear_body``
    detects the pre-existing shear so the apply path re-lofts instead,
    moving the cap AND walls together so the body's overall height
    actually shrinks."""
    require_ocp()

    from cad_app.commands import (
        face_normal_vector,
        is_oblique_shear_body,
        move_face_oblique_shear,
    )
    from cad_app.picker import Picker
    from cad_app.sketch import extrude_profile, make_circle_profile
    from cad_app.types import SelectionKind
    from cad_app.workplane import Workplane

    profile = make_circle_profile(Workplane.world_xy(), radius=20.0)
    cylinder = extrude_profile(profile, 50.0)

    def top_index(shape):
        for index in range(
            1, Picker.indexed_map(shape, SelectionKind.FACE).Extent() + 1
        ):
            face = Picker.indexed_map(shape, SelectionKind.FACE).FindKey(index)
            if not Picker._is_planar_face(face):
                continue
            if face_normal_vector(shape, index)[2] > 0.95:
                return index
        return None

    top = top_index(cylinder)
    assert top is not None
    assert not is_oblique_shear_body(
        cylinder, top
    ), "Straight cylinder must not be classified as already-oblique"

    sheared = move_face_oblique_shear(cylinder, top, 0.0, 15.0, 0.0)
    sheared_top = top_index(sheared)
    assert sheared_top is not None
    assert is_oblique_shear_body(sheared, sheared_top), (
        "Y-sheared cylinder must be detected as already-oblique so a "
        "subsequent normal push re-lofts instead of extrude_face cutting"
    )

    nx, ny, nz = face_normal_vector(sheared, sheared_top)
    pushed = move_face_oblique_shear(
        sheared,
        sheared_top,
        nx * -25.0,
        ny * -25.0,
        nz * -25.0,
    )
    assert_valid_shape(pushed)

    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    tight = Bnd_Box()
    BRepBndLib.AddOptimal_s(pushed, tight)
    xmin, ymin, zmin, xmax, ymax, zmax = tight.Get()
    # Whole body should be 25 mm shorter: walls dropped with the cap.
    assert zmax - zmin == pytest.approx(25.0, abs=1e-3)
    # The remaining body must still reach down to the original bottom
    # cap. If walls had stayed anchored, the bottom would have moved
    # up to z=25 (extrude_face's cut prism leaving the original cap
    # exposed); the lofted rebuild leaves the bottom at z=0.
    assert zmin == pytest.approx(0.0, abs=1e-3)
    assert zmax == pytest.approx(25.0, abs=1e-3)


def test_oblique_shear_works_on_fused_stacked_cylinder_top() -> None:
    """User flow: cylinder, sketch a smaller circle on top, extrude to
    fuse a stacked cap. Previously ``supports_move_face_oblique_shear``
    required exactly two planar caps globally, so the top of the
    stacked feature (which sees 3 planar faces - top, step annulus,
    bottom) was rejected and the user couldn't shear it sideways.

    The fix walks LOCAL topology: from the moved cap find its curved
    lateral neighbours, then form the bottom wire from their non-cap
    edges (skipping seam edges of periodic cylindrical surfaces).
    Subtract the matching ruled solid out of the body and fuse the
    sheared replacement back in, leaving the lower cylinder + step
    untouched while tilting only the local feature.
    """
    require_ocp()

    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    from cad_app.commands import (
        face_normal_vector,
        move_face_oblique_shear,
        supports_move_face_oblique_shear,
    )
    from cad_app.picker import Picker
    from cad_app.sketch import extrude_profile, make_circle_profile
    from cad_app.types import SelectionKind
    from cad_app.workplane import Workplane

    base = extrude_profile(make_circle_profile(Workplane.world_xy(), 20.0), 50.0)
    axis = gp_Ax2(gp_Pnt(0.0, 0.0, 50.0), gp_Dir(0.0, 0.0, 1.0))
    upper = BRepPrimAPI_MakeCylinder(axis, 12.0, 30.0).Shape()
    stacked = BRepAlgoAPI_Fuse(base, upper).Shape()

    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopoDS import TopoDS

    def top_face_index(shape):
        face_map = Picker.indexed_map(shape, SelectionKind.FACE)
        best_index, best_z = None, -1e9
        for index in range(1, face_map.Extent() + 1):
            face = TopoDS.Face_s(face_map.FindKey(index))
            if not Picker._is_planar_face(face):
                continue
            if face_normal_vector(shape, index)[2] < 0.95:
                continue
            props = GProp_GProps()
            BRepGProp.SurfaceProperties_s(face, props)
            z = props.CentreOfMass().Z()
            if z > best_z:
                best_z, best_index = z, index
        return best_index

    top_index = top_face_index(stacked)
    assert top_index is not None
    assert supports_move_face_oblique_shear(
        stacked, top_index
    ), "Stacked-cylinder top must be shear-eligible via local topology walk"

    sheared = move_face_oblique_shear(stacked, top_index, 5.0, 0.0, 0.0)
    assert_valid_shape(sheared)

    # The new top cap must sit at (+5, 0, 80) - the original top
    # circle was at (0, 0, 80), and we asked for a +5 X shift on the
    # cap only. The lower cylinder + step must stay put.
    face_map = Picker.indexed_map(sheared, SelectionKind.FACE)
    cap_centroids = []
    for index in range(1, face_map.Extent() + 1):
        face = TopoDS.Face_s(face_map.FindKey(index))
        if not Picker._is_planar_face(face):
            continue
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        c = props.CentreOfMass()
        cap_centroids.append((c.X(), c.Y(), c.Z()))
    cap_centroids.sort(key=lambda p: p[2])
    # Expect bottom cap at (0,0,0), step annulus at (0,0,50), shifted
    # top at (+5,0,80).
    assert cap_centroids[0] == pytest.approx((0.0, 0.0, 0.0), abs=1e-3)
    assert cap_centroids[1] == pytest.approx((0.0, 0.0, 50.0), abs=1e-3)
    assert cap_centroids[2] == pytest.approx((5.0, 0.0, 80.0), abs=1e-3)


def test_cylindrical_face_thread_helpers_size_to_geometry() -> None:
    """The new face-driven thread flow needs to read diameter + length
    from the picked cylindrical face and find a circular edge to anchor
    the modeled thread on. Verify the helpers return values matching the
    geometry and that an ISO preset auto-matched by diameter applies
    cleanly over the full face length."""
    require_ocp()

    from cad_app.commands import (
        apply_thread_to_edge,
        cylindrical_face_anchor_edge_index,
        cylindrical_face_parameters,
    )
    from cad_app.picker import Picker
    from cad_app.scene import Scene
    from cad_app.sketch import extrude_profile, make_circle_profile
    from cad_app.thread_specs import (
        matching_thread_preset_for_edge_diameter,
        thread_parameters_from_preset,
    )
    from cad_app.types import SelectionKind
    from cad_app.workplane import Workplane

    cylinder = extrude_profile(
        make_circle_profile(Workplane.world_xy(), radius=5.0),
        30.0,
    )

    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.TopoDS import TopoDS

    face_map = Picker.indexed_map(cylinder, SelectionKind.FACE)
    cyl_face_index = None
    for index in range(1, face_map.Extent() + 1):
        face = TopoDS.Face_s(face_map.FindKey(index))
        if BRepAdaptor_Surface(face).GetType() == GeomAbs_Cylinder:
            cyl_face_index = index
            break
    assert cyl_face_index is not None

    _center, _axis, radius, length = cylindrical_face_parameters(
        cylinder, cyl_face_index
    )
    assert radius == pytest.approx(5.0, abs=1e-6)
    assert length == pytest.approx(30.0, abs=1e-6)

    preset = matching_thread_preset_for_edge_diameter(radius * 2.0)
    assert (
        preset is not None and "M10" in preset.name
    ), "Diameter 10 mm should auto-pick an M10 ISO preset"

    anchor = cylindrical_face_anchor_edge_index(cylinder, cyl_face_index)
    assert anchor > 0

    params = thread_parameters_from_preset(preset)
    scene = Scene()
    item_id = scene.add_shape(cylinder)
    apply_thread_to_edge(
        scene,
        item_id,
        anchor,
        pitch=float(params["pitch"]),
        length=length,
        depth=float(params["depth"]),
        mode="modeled",
        thread_type="external",
        standard=str(params["standard"]),
        size=str(params["size"]),
        major_diameter=float(params["major_diameter"]),
        minor_diameter=float(params["minor_diameter"]),
    )
    assert_valid_shape(scene.get(item_id).shape)


def test_thread_defaults_scale_with_diameter_to_avoid_dense_rebuilds() -> None:
    """A custom thread on a large-diameter cylinder must not default to
    a 1 mm pitch. Previously an ~80 mm cylinder fell out of the preset
    table (max M16) and defaulted to pitch=1.0, producing ~80 turns
    over an 80 mm body and a 25-second BRep rebuild. Guard the two
    pieces that fix this:

    * the preset table now covers M20..M64 so common large diameters
      auto-match instead of dropping to Custom;
    * the Custom fallback returns a pitch proportional to diameter
      so the resulting thread is sweepable in a fraction of a second.
    """
    from cad_app.thread_specs import (
        default_thread_pitch_for_diameter,
        matching_thread_preset_for_edge_diameter,
    )

    # M20..M64 in the preset table => the 80 mm diameter we tripped
    # over should auto-match (M48..M64 envelope) instead of falling to
    # Custom with stale defaults.
    preset_for_80 = matching_thread_preset_for_edge_diameter(80.0)
    assert preset_for_80 is not None
    assert preset_for_80.pitch >= 5.0, (
        f"80 mm diameter matched {preset_for_80.name} with pitch "
        f"{preset_for_80.pitch} mm - expected coarse pitch >= 5"
    )

    # Diameter-proportional fallback for sizes that still don't match
    # (very large bodies). Crucially, no diameter we'd realistically
    # thread should default to a 1.0 mm pitch on a 80 mm body.
    pitch_80 = default_thread_pitch_for_diameter(80.0)
    assert pitch_80 >= 5.0, (
        f"Default pitch for 80 mm diameter was {pitch_80} mm - "
        "would produce a punishingly dense thread"
    )
    # Sanity at the small end: M6 territory keeps its 1.0 mm pitch.
    assert default_thread_pitch_for_diameter(6.0) == pytest.approx(1.0)
    # And the proportional fallback above the table stays sensible.
    assert default_thread_pitch_for_diameter(200.0) >= 6.0


def test_apply_extrude_face_splits_disconnected_result_into_scene_items(
    monkeypatch,
) -> None:
    """When extrude_face (cut) produces a compound of multiple solids,
    apply_extrude_face must keep the largest piece on the original
    scene item and add the remaining pieces as new bodies. Without
    this, a cut that visually splits one body into two leaves them
    sharing one item id, so selection and the browser treat them as
    the same object."""
    require_ocp()

    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    from cad_app.commands import apply_extrude_face
    from cad_app.engine import make_box
    from cad_app.scene import Scene

    body = make_box(40.0, 40.0, 40.0)
    big = make_box(20.0, 20.0, 20.0)
    small = _translate(make_box(5.0, 5.0, 5.0), 100.0, 0.0, 0.0)

    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    builder.Add(compound, big)
    builder.Add(compound, small)

    def fake_extrude(_shape, _face_index, _distance):
        return compound

    monkeypatch.setattr("cad_app.commands.extrude_face", fake_extrude)

    scene = Scene()
    item_id = scene.add_shape(body, meta={"kind": "body", "source": "test"})
    before_items = set(item.item_id for item in scene)

    apply_extrude_face(scene, item_id, face_index=1, distance=-30.0)

    after_items = set(item.item_id for item in scene)
    assert len(after_items) == 2, (
        "Disconnected extrude result must spawn a second scene item; "
        f"got items={after_items}"
    )
    new_ids = after_items - before_items
    assert len(new_ids) == 1
    new_id = next(iter(new_ids))
    new_meta = scene.get(new_id).meta
    assert new_meta.get("source") == "extrude_split"
    assert new_meta.get("parent_item_id") == item_id


def test_boolean_rejects_sketch_profile_as_body_operand() -> None:
    require_ocp()

    from cad_app.commands import OperationFailedError, apply_boolean_bodies
    from cad_app.engine import make_box
    from cad_app.scene import Scene
    from cad_app.sketch import SKETCH_META_KIND, make_center_rectangle_profile
    from cad_app.workplane import Workplane

    scene = Scene()
    body_id = scene.add_shape(make_box(), meta={"kind": "body"})
    sketch_id = scene.add_shape(
        make_center_rectangle_profile(Workplane.world_xy(), (0.0, 0.0), (5.0, 5.0)),
        meta={"kind": SKETCH_META_KIND, "profile": "rectangle"},
    )
    before = tuple(item.item_id for item in scene)

    with pytest.raises(OperationFailedError, match="Body union failed"):
        apply_boolean_bodies(scene, body_id, sketch_id, "union")
    with pytest.raises(OperationFailedError, match="Body union failed"):
        apply_boolean_bodies(scene, sketch_id, body_id, "union")

    assert tuple(item.item_id for item in scene) == before


def test_remove_face_returns_valid_open_shell_with_one_less_face() -> None:
    require_ocp()

    from cad_app.commands import remove_face, top_planar_face_index
    from cad_app.engine import make_box

    shape = make_box(20.0, 20.0, 20.0)
    removed = remove_face(shape, top_planar_face_index(shape))

    assert_valid_shape(removed)
    assert count_subshapes(removed, "solid") == 0
    assert count_subshapes(removed, "face") == count_subshapes(shape, "face") - 1


def test_rounding_and_rotation_keep_geometry_valid() -> None:
    require_ocp()

    from cad_app.commands import chamfer_edge, fillet_edge, rotate_shape
    from cad_app.engine import make_box

    shape = make_box(30.0, 20.0, 20.0)
    filleted = fillet_edge(shape, 1, 1.0)
    chamfered = chamfer_edge(shape, 2, 1.0)
    rotated = rotate_shape(shape, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 90.0)

    assert_valid_shape(filleted)
    assert_valid_shape(chamfered)
    assert_valid_shape(rotated)
    assert count_subshapes(filleted, "face") > count_subshapes(shape, "face")
    assert bounding_box(rotated)["width"] == pytest.approx(20.0, abs=1e-3)
    assert bounding_box(rotated)["depth"] == pytest.approx(30.0, abs=1e-3)


def test_fillet_and_chamfer_accept_cylinder_cap_circle_edge() -> None:
    """The top/bottom circles of an extruded circle are the most common
    edge to round in real CAD work (every shaft end, every hole rim).
    Previous guard rejected them because one adjacent face was the
    curved lateral, not planar - which OCCT itself handles fine."""
    require_ocp()

    from cad_app.command_rounding import edge_supports_direct_round
    from cad_app.commands import chamfer_edge, fillet_edge
    from cad_app.picker import Picker
    from cad_app.sketch import extrude_profile, make_circle_profile
    from cad_app.types import SelectionKind
    from cad_app.workplane import Workplane

    profile = make_circle_profile(Workplane.world_xy(), radius=20.0)
    cylinder = extrude_profile(profile, 50.0)

    face_count_before = count_subshapes(cylinder, "face")

    # Find the two circular cap edges (one adjacent face is the planar
    # cap, the other is the curved lateral).
    edge_map = Picker.indexed_map(cylinder, SelectionKind.EDGE)
    circle_edge_indices: list[int] = []
    for index in range(1, edge_map.Extent() + 1):
        if edge_supports_direct_round(cylinder, index):
            circle_edge_indices.append(index)
    assert len(circle_edge_indices) == 2, (
        "An extruded circle has two cap-circle edges; both must support "
        f"fillet/chamfer. Got supported indices={circle_edge_indices}."
    )

    top_filleted = fillet_edge(cylinder, circle_edge_indices[0], 2.0)
    assert_valid_shape(top_filleted)
    assert (
        count_subshapes(top_filleted, "face") > face_count_before
    ), "Fillet on a cap circle must add a torus face."

    top_chamfered = chamfer_edge(cylinder, circle_edge_indices[1], 1.5)
    assert_valid_shape(top_chamfered)
    assert (
        count_subshapes(top_chamfered, "face") > face_count_before
    ), "Chamfer on a cap circle must add a conical face."


def test_sketch_extrude_and_revolve_profiles_are_valid_solids() -> None:
    require_ocp()

    from cad_app.sketch import extrude_profile, make_center_rectangle_profile
    from cad_app.sketch_features import revolve_profile
    from cad_app.workplane import Workplane

    profile = make_center_rectangle_profile(
        Workplane.world_xy(), (20.0, 10.0), (10.0, 5.0)
    )
    extruded = extrude_profile(profile, 15.0)
    revolved = revolve_profile(
        profile,
        (0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        angle_degrees=180.0,
    )

    assert_valid_shape(extruded)
    assert_valid_shape(revolved)
    assert count_subshapes(extruded, "solid") == 1
    assert count_subshapes(revolved, "solid") >= 1


def test_step_roundtrip_preserves_valid_body_after_direct_operations(tmp_path) -> None:
    require_ocp()

    from cad_app.commands import (
        fillet_edge,
        move_face_controlled,
        top_planar_face_index,
    )
    from cad_app.engine import make_box
    from cad_app.io_step import export_step, import_step

    shape = make_box(30.0, 20.0, 10.0)
    moved = move_face_controlled(shape, top_planar_face_index(shape), 0.0, 0.0, 4.0)
    rounded = fillet_edge(moved, 1, 0.75)
    path = tmp_path / "direct_modeling_roundtrip.step"

    export_step(rounded, path)
    imported = import_step(path)

    assert path.stat().st_size > 0
    assert_valid_shape(imported)
    assert count_subshapes(imported, "solid") == 1
    assert bounding_box(imported)["height"] == pytest.approx(
        bounding_box(rounded)["height"], abs=1e-3
    )
