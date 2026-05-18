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
