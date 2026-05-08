from importlib.util import find_spec

import pytest


def _skip_without_cad_dependencies() -> None:
    if find_spec("build123d") is None or find_spec("OCP") is None:
        pytest.skip("OCP/build123d are not installed in the active environment.")


def _volume(shape) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def _count_faces_of_type(shape, surface_type) -> int:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.TopoDS import TopoDS

    from cad_app.picker import Picker
    from cad_app.types import SelectionKind

    face_map = Picker.indexed_map(shape, SelectionKind.FACE)
    return sum(
        1
        for index in range(1, face_map.Extent() + 1)
        if BRepAdaptor_Surface(TopoDS.Face_s(face_map.FindKey(index))).GetType()
        == surface_type
    )


def test_extrude_face_pull_increases_volume() -> None:
    _skip_without_cad_dependencies()

    from cad_app.commands import extrude_face
    from cad_app.engine import make_box

    shape = make_box(10, 20, 30)
    result = extrude_face(shape, face_index=6, distance=10)

    assert _volume(result) == pytest.approx(8000.0)


def test_extrude_face_push_in_decreases_volume() -> None:
    _skip_without_cad_dependencies()

    from cad_app.commands import extrude_face
    from cad_app.engine import make_box

    shape = make_box(10, 20, 30)
    result = extrude_face(shape, face_index=6, distance=-10)

    assert _volume(result) == pytest.approx(4000.0)


def test_extrude_face_rejects_zero_distance() -> None:
    _skip_without_cad_dependencies()

    from cad_app.commands import extrude_face
    from cad_app.engine import make_box

    with pytest.raises(ValueError, match="non-zero"):
        extrude_face(make_box(), face_index=1, distance=0)


def test_extrude_face_rejects_out_of_range_face_index() -> None:
    _skip_without_cad_dependencies()

    from cad_app.commands import extrude_face
    from cad_app.engine import make_box

    with pytest.raises(IndexError, match="out of range"):
        extrude_face(make_box(), face_index=7, distance=10)


def test_apply_extrude_face_replaces_scene_shape_after_success() -> None:
    _skip_without_cad_dependencies()

    from cad_app.commands import apply_extrude_face
    from cad_app.engine import make_box
    from cad_app.scene import Scene

    scene = Scene()
    item_id = scene.add_shape(make_box(10, 20, 30))

    apply_extrude_face(scene, item_id, face_index=6, distance=10)

    assert _volume(scene.get(item_id).shape) == pytest.approx(8000.0)


def test_apply_extrude_face_keeps_scene_shape_after_failure() -> None:
    _skip_without_cad_dependencies()

    from cad_app.commands import apply_extrude_face
    from cad_app.engine import make_box
    from cad_app.scene import Scene

    scene = Scene()
    shape = make_box(10, 20, 30)
    item_id = scene.add_shape(shape)

    with pytest.raises(IndexError):
        apply_extrude_face(scene, item_id, face_index=7, distance=10)

    assert scene.get(item_id).shape.IsSame(shape)


def test_top_planar_face_index_supports_repeated_extrude() -> None:
    _skip_without_cad_dependencies()

    from cad_app.commands import extrude_face, top_planar_face_index
    from cad_app.engine import make_box

    shape = make_box(10, 20, 30)
    first = extrude_face(shape, top_planar_face_index(shape), 10)
    second = extrude_face(first, top_planar_face_index(first), 10)

    assert _volume(first) == pytest.approx(8000.0)
    assert _volume(second) == pytest.approx(10000.0)


def test_cleanup_shape_keeps_valid_shape() -> None:
    _skip_without_cad_dependencies()

    from OCP.BRepCheck import BRepCheck_Analyzer

    from cad_app.commands import cleanup_shape
    from cad_app.engine import make_box

    cleaned = cleanup_shape(make_box(10, 20, 30))
    assert BRepCheck_Analyzer(cleaned).IsValid()


def test_circle_feature_adds_volume_on_selected_face() -> None:
    _skip_without_cad_dependencies()

    from cad_app.commands import add_circle_feature
    from cad_app.engine import make_box

    shape = make_box(40, 40, 40)
    result = add_circle_feature(shape, face_index=6, radius=5, depth=10, cut=False)

    assert _volume(result) > _volume(shape)


def test_circle_feature_cuts_volume_on_selected_face() -> None:
    _skip_without_cad_dependencies()

    from cad_app.commands import add_circle_feature
    from cad_app.engine import make_box

    shape = make_box(40, 40, 40)
    result = add_circle_feature(shape, face_index=6, radius=5, depth=10, cut=True)

    assert _volume(result) < _volume(shape)


def test_boolean_bodies_supports_union_subtract_and_intersect() -> None:
    _skip_without_cad_dependencies()

    from cad_app.commands import boolean_bodies, translated_shape
    from cad_app.engine import make_box

    target = make_box(40, 40, 40)
    tool = translated_shape(make_box(40, 40, 40), 20, 0, 0)

    union = boolean_bodies(target, tool, "union")
    subtract = boolean_bodies(target, tool, "subtract")
    intersect = boolean_bodies(target, tool, "intersect")

    assert _volume(union) > _volume(target)
    assert _volume(subtract) < _volume(target)
    assert 0 < _volume(intersect) < _volume(target)


def test_apply_boolean_bodies_replaces_target_removes_tool_and_undo_restores() -> None:
    _skip_without_cad_dependencies()

    from cad_app.commands import apply_boolean_bodies, translated_shape
    from cad_app.engine import make_box
    from cad_app.scene import Scene

    scene = Scene()
    target_id = scene.add_shape(make_box(40, 40, 40), meta={"kind": "body"})
    tool_id = scene.add_shape(
        translated_shape(make_box(40, 40, 40), 20, 0, 0),
        meta={"kind": "body"},
    )
    target_volume = _volume(scene.get(target_id).shape)

    result = apply_boolean_bodies(scene, target_id, tool_id, "union")

    assert _volume(result) > target_volume
    assert target_id in scene
    assert tool_id not in scene
    assert scene.active_item_id() == target_id

    scene.undo()

    assert target_id in scene
    assert tool_id in scene
    assert _volume(scene.get(target_id).shape) == pytest.approx(target_volume)


def test_apply_circle_feature_supports_undo() -> None:
    _skip_without_cad_dependencies()

    from cad_app.commands import apply_circle_feature
    from cad_app.engine import make_box
    from cad_app.scene import Scene

    scene = Scene()
    item_id = scene.add_shape(make_box(40, 40, 40))
    before = _volume(scene.get(item_id).shape)

    apply_circle_feature(scene, item_id, face_index=6, radius=5, depth=10)
    after = _volume(scene.get(item_id).shape)
    scene.undo()

    assert after > before
    assert _volume(scene.get(item_id).shape) == pytest.approx(before)


def test_fillet_edge_returns_valid_shape() -> None:
    _skip_without_cad_dependencies()

    from OCP.BRepCheck import BRepCheck_Analyzer

    from cad_app.commands import fillet_edge
    from cad_app.engine import make_box

    shape = make_box(40, 40, 40)
    result = fillet_edge(shape, edge_index=1, radius=3)

    assert BRepCheck_Analyzer(result).IsValid()
    assert _volume(result) < _volume(shape)


def test_chamfer_edge_returns_valid_shape() -> None:
    _skip_without_cad_dependencies()

    from OCP.BRepCheck import BRepCheck_Analyzer

    from cad_app.commands import chamfer_edge
    from cad_app.engine import make_box

    shape = make_box(40, 40, 40)
    result = chamfer_edge(shape, edge_index=1, distance=3)

    assert BRepCheck_Analyzer(result).IsValid()
    assert _volume(result) < _volume(shape)


def test_apply_edge_operations_support_undo() -> None:
    _skip_without_cad_dependencies()

    from cad_app.commands import apply_chamfer_edge, apply_fillet_edge
    from cad_app.engine import make_box
    from cad_app.scene import Scene

    scene = Scene()
    item_id = scene.add_shape(make_box(40, 40, 40))
    before = _volume(scene.get(item_id).shape)

    apply_fillet_edge(scene, item_id, edge_index=1, radius=3)
    assert _volume(scene.get(item_id).shape) < before
    scene.undo()
    assert _volume(scene.get(item_id).shape) == pytest.approx(before)

    apply_chamfer_edge(scene, item_id, edge_index=1, distance=3)
    assert _volume(scene.get(item_id).shape) < before
    scene.undo()
    assert _volume(scene.get(item_id).shape) == pytest.approx(before)


def test_fillet_rejects_curved_edges_created_by_previous_fillet() -> None:
    _skip_without_cad_dependencies()

    from cad_app.commands import (
        UnsupportedTopologyError,
        fillet_edge,
    )
    from cad_app.engine import make_box
    from cad_app.picker import Picker
    from cad_app.types import SelectionKind

    first = fillet_edge(make_box(40, 40, 40), edge_index=1, radius=3)
    edge_count = Picker.indexed_map(first, SelectionKind.EDGE).Extent()

    for index in range(1, edge_count + 1):
        try:
            fillet_edge(first, edge_index=index, radius=2)
        except UnsupportedTopologyError as exc:
            if "planar faces" in str(exc):
                return

    pytest.fail("Expected at least one curved fillet boundary edge to be rejected.")


def test_second_fillet_on_remaining_sharp_edge_adds_one_round() -> None:
    _skip_without_cad_dependencies()

    from OCP.GeomAbs import GeomAbs_Cylinder

    from cad_app.commands import edge_supports_direct_round, fillet_edge
    from cad_app.engine import make_box

    first = fillet_edge(make_box(40, 40, 40), edge_index=1, radius=3)
    before_rounds = _count_faces_of_type(first, GeomAbs_Cylinder)

    assert edge_supports_direct_round(first, 3)
    second = fillet_edge(first, edge_index=3, radius=2)

    assert _count_faces_of_type(second, GeomAbs_Cylinder) == before_rounds + 1


def test_fillet_rejects_adjacent_contour_that_would_round_multiple_edges() -> None:
    _skip_without_cad_dependencies()

    from cad_app.commands import (
        UnsupportedTopologyError,
        edge_supports_direct_round,
        fillet_edge,
    )
    from cad_app.engine import make_box

    first = fillet_edge(make_box(40, 40, 40), edge_index=1, radius=3)

    assert not edge_supports_direct_round(first, 1)
    with pytest.raises(UnsupportedTopologyError, match="would affect 3 tangent edges"):
        fillet_edge(first, edge_index=1, radius=2)


def test_apply_fillet_edge_rebases_adjacent_second_fillet_to_two_edges() -> None:
    _skip_without_cad_dependencies()

    from OCP.GeomAbs import GeomAbs_Cylinder

    from cad_app.commands import apply_fillet_edge
    from cad_app.engine import make_box
    from cad_app.scene import Scene

    scene = Scene()
    item_id = scene.add_shape(make_box(40, 40, 40))

    apply_fillet_edge(scene, item_id, edge_index=1, radius=3)
    first_rounds = _count_faces_of_type(scene.get(item_id).shape, GeomAbs_Cylinder)
    apply_fillet_edge(scene, item_id, edge_index=1, radius=2)

    assert first_rounds == 1
    assert _count_faces_of_type(scene.get(item_id).shape, GeomAbs_Cylinder) == 2


def test_move_face_normal_wraps_controlled_push_pull() -> None:
    _skip_without_cad_dependencies()

    from cad_app.commands import move_face_normal
    from cad_app.engine import make_box

    shape = make_box(10, 20, 30)
    result = move_face_normal(shape, face_index=6, distance=10)

    assert _volume(result) == pytest.approx(8000.0)


def test_move_face_controlled_rebuilds_valid_planar_solid() -> None:
    _skip_without_cad_dependencies()

    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepCheck import BRepCheck_Analyzer

    from cad_app.commands import move_face_controlled, top_planar_face_index
    from cad_app.engine import make_box

    shape = make_box(40, 40, 40)
    moved = move_face_controlled(
        shape,
        face_index=top_planar_face_index(shape),
        dx=10,
        dy=0,
        dz=0,
    )
    bounds = Bnd_Box()
    BRepBndLib.Add_s(moved, bounds)

    assert BRepCheck_Analyzer(moved).IsValid()
    assert bounds.Get()[3] == pytest.approx(30.0, abs=1e-6)


def test_move_shape_translates_object_without_changing_volume() -> None:
    _skip_without_cad_dependencies()

    from cad_app.commands import move_shape
    from cad_app.engine import make_box

    shape = make_box(40, 40, 40)
    moved = move_shape(shape, 10, 0, 0)

    assert _volume(moved) == pytest.approx(_volume(shape))


def test_translated_shape_moves_bounds_without_touching_input() -> None:
    _skip_without_cad_dependencies()

    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    from cad_app.commands import translated_shape
    from cad_app.engine import make_box

    shape = make_box(40, 40, 40)
    moved = translated_shape(shape, 10, 0, 0)

    original_bounds = Bnd_Box()
    moved_bounds = Bnd_Box()
    BRepBndLib.Add_s(shape, original_bounds)
    BRepBndLib.Add_s(moved, moved_bounds)

    original_x_min, *_ = original_bounds.Get()
    moved_x_min, *_ = moved_bounds.Get()
    assert moved_x_min - original_x_min == pytest.approx(10.0, abs=1e-6)


def test_rotate_shape_rotates_bounds_without_changing_volume() -> None:
    _skip_without_cad_dependencies()

    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepCheck import BRepCheck_Analyzer

    from cad_app.commands import rotate_shape
    from cad_app.engine import make_box

    shape = make_box(20, 40, 10)
    rotated = rotate_shape(shape, (0.0, 0.0, 5.0), (0.0, 0.0, 1.0), 90.0)

    bounds = Bnd_Box()
    BRepBndLib.Add_s(rotated, bounds)
    x_min, y_min, *_rest, x_max, y_max, _z_max = bounds.Get()

    assert BRepCheck_Analyzer(rotated).IsValid()
    assert _volume(rotated) == pytest.approx(_volume(shape))
    assert x_max - x_min == pytest.approx(40.0, abs=1e-6)
    assert y_max - y_min == pytest.approx(20.0, abs=1e-6)


def test_apply_rotate_object_supports_undo() -> None:
    _skip_without_cad_dependencies()

    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    from cad_app.commands import apply_rotate_object
    from cad_app.engine import make_box
    from cad_app.scene import Scene

    scene = Scene()
    item_id = scene.add_shape(make_box(20, 40, 10))
    before = Bnd_Box()
    BRepBndLib.Add_s(scene.get(item_id).shape, before)

    apply_rotate_object(scene, item_id, (0.0, 0.0, 5.0), (0.0, 0.0, 1.0), 90.0)
    after = Bnd_Box()
    BRepBndLib.Add_s(scene.get(item_id).shape, after)
    scene.undo()
    restored = Bnd_Box()
    BRepBndLib.Add_s(scene.get(item_id).shape, restored)

    assert after.Get()[3] - after.Get()[0] == pytest.approx(40.0, abs=1e-6)
    assert restored.Get()[0] == pytest.approx(before.Get()[0], abs=1e-6)


def test_face_normal_vector_returns_top_face_normal() -> None:
    _skip_without_cad_dependencies()

    from cad_app.commands import face_normal_vector, top_planar_face_index
    from cad_app.engine import make_box

    shape = make_box(40, 40, 40)

    assert face_normal_vector(shape, top_planar_face_index(shape)) == pytest.approx(
        (0.0, 0.0, 1.0)
    )


def test_move_edge_controlled_rebuilds_valid_planar_solid() -> None:
    _skip_without_cad_dependencies()

    from OCP.BRepCheck import BRepCheck_Analyzer

    from cad_app.commands import move_edge_controlled
    from cad_app.engine import make_box

    shape = make_box(40, 40, 40)
    moved = move_edge_controlled(shape, edge_index=1, dx=0, dy=0, dz=10)

    assert BRepCheck_Analyzer(moved).IsValid()
    assert _volume(moved) != pytest.approx(_volume(shape))


def test_move_vertex_controlled_rebuilds_valid_planar_solid() -> None:
    _skip_without_cad_dependencies()

    from OCP.BRepCheck import BRepCheck_Analyzer

    from cad_app.commands import move_vertex_controlled
    from cad_app.engine import make_box

    shape = make_box(40, 40, 40)
    moved = move_vertex_controlled(shape, vertex_index=1, dx=0, dy=0, dz=10)

    assert BRepCheck_Analyzer(moved).IsValid()
    assert _volume(moved) != pytest.approx(_volume(shape))


def test_edge_and_vertex_moves_reject_curved_topology() -> None:
    _skip_without_cad_dependencies()

    from cad_app.commands import (
        UnsupportedTopologyError,
        fillet_edge,
        move_edge_controlled,
        move_vertex_controlled,
        supports_move_edge_controlled,
        supports_move_vertex_controlled,
    )
    from cad_app.engine import make_box
    from cad_app.picker import Picker
    from cad_app.types import SelectionKind

    curved = fillet_edge(make_box(40, 40, 40), edge_index=1, radius=3)
    edge_count = Picker.indexed_map(curved, SelectionKind.EDGE).Extent()
    vertex_count = Picker.indexed_map(curved, SelectionKind.VERTEX).Extent()

    assert not supports_move_edge_controlled(curved, min(edge_count, 2))
    assert not supports_move_vertex_controlled(curved, min(vertex_count, 2))
    with pytest.raises(UnsupportedTopologyError, match="planar"):
        move_edge_controlled(curved, edge_index=min(edge_count, 2), dx=0, dy=0, dz=10)
    with pytest.raises(UnsupportedTopologyError, match="planar-faced"):
        move_vertex_controlled(
            curved,
            vertex_index=min(vertex_count, 2),
            dx=0,
            dy=0,
            dz=10,
        )


def test_move_edge_preserves_two_bodies_in_scene() -> None:
    _skip_without_cad_dependencies()

    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    from cad_app.commands import (
        apply_move_edge_controlled,
        translated_shape,
    )
    from cad_app.engine import make_box
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef

    scene = Scene()
    lower_id = scene.add_shape(make_box(80.0, 80.0, 40.0), meta={"kind": "body"})
    upper_shape = translated_shape(make_box(40.0, 30.0, 20.0), 0.0, 0.0, 40.0)
    upper_id = scene.add_shape(upper_shape, meta={"kind": "body"})
    scene.set_selection(
        SelectionRef(item_id=upper_id, kind=SelectionKind.EDGE, index=2)
    )

    apply_move_edge_controlled(scene, upper_id, 2, 5.0, 0.0, 0.0)

    assert len(scene) == 2
    assert lower_id in scene
    assert upper_id in scene

    lower_bounds = Bnd_Box()
    BRepBndLib.Add_s(scene.get(lower_id).shape, lower_bounds)
    assert lower_bounds.Get()[3] == pytest.approx(40.0, abs=1e-4)

    upper_bounds = Bnd_Box()
    BRepBndLib.Add_s(scene.get(upper_id).shape, upper_bounds)
    assert upper_bounds.Get()[2] == pytest.approx(40.0, abs=1e-4)
    assert upper_bounds.Get()[3] > 20


def test_move_top_front_edge_creates_slanted_box_not_resized_box() -> None:
    _skip_without_cad_dependencies()

    from OCP.BRep import BRep_Tool
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopoDS import TopoDS

    from cad_app.commands import (
        move_edge_controlled,
        translated_shape,
    )
    from cad_app.engine import make_box
    from cad_app.picker import Picker
    from cad_app.types import SelectionKind

    base = make_box(200, 160, 40)
    upper = translated_shape(make_box(100, 80, 60), 0, 0, 40)

    base_vm = Picker.indexed_map(base, SelectionKind.VERTEX)
    _base_before = {
        i: (
            BRep_Tool.Pnt_s(TopoDS.Vertex_s(base_vm.FindKey(i))).X(),
            BRep_Tool.Pnt_s(TopoDS.Vertex_s(base_vm.FindKey(i))).Y(),
            BRep_Tool.Pnt_s(TopoDS.Vertex_s(base_vm.FindKey(i))).Z(),
        )
        for i in range(1, base_vm.Extent() + 1)
    }

    upper_vm = Picker.indexed_map(upper, SelectionKind.VERTEX)
    upper_before = {
        i: (
            BRep_Tool.Pnt_s(TopoDS.Vertex_s(upper_vm.FindKey(i))).X(),
            BRep_Tool.Pnt_s(TopoDS.Vertex_s(upper_vm.FindKey(i))).Y(),
            BRep_Tool.Pnt_s(TopoDS.Vertex_s(upper_vm.FindKey(i))).Z(),
        )
        for i in range(1, upper_vm.Extent() + 1)
    }

    target_edge_idx = None
    edge_map = Picker.indexed_map(upper, SelectionKind.EDGE)
    for idx in range(1, edge_map.Extent() + 1):
        edge = TopoDS.Edge_s(edge_map.FindKey(idx))
        evm = Picker.indexed_map(edge, SelectionKind.VERTEX)
        z_vals = []
        y_vals = []
        for vi in range(1, evm.Extent() + 1):
            p = BRep_Tool.Pnt_s(TopoDS.Vertex_s(evm.FindKey(vi)))
            z_vals.append(p.Z())
            y_vals.append(p.Y())
        if (
            all(abs(z - 100) < 1 for z in z_vals)
            and any(abs(y + 40) < 1 for y in y_vals)
            and len(z_vals) == 2
            and abs(z_vals[0] - z_vals[1]) < 1
        ):
            target_edge_idx = idx
            break

    assert target_edge_idx is not None, "Could not find top-front edge"

    result = move_edge_controlled(upper, target_edge_idx, 0, 0, -30)

    assert BRepCheck_Analyzer(result).IsValid()

    result_vm = Picker.indexed_map(result, SelectionKind.VERTEX)
    result_set = set()
    for i in range(1, result_vm.Extent() + 1):
        p = BRep_Tool.Pnt_s(TopoDS.Vertex_s(result_vm.FindKey(i)))
        result_set.add((round(p.X(), 6), round(p.Y(), 6), round(p.Z(), 6)))

    upper_before_set = set()
    for v in upper_before.values():
        upper_before_set.add((round(v[0], 6), round(v[1], 6), round(v[2], 6)))

    unchanged = upper_before_set & result_set
    changed = result_set - upper_before_set

    assert len(changed) == 2
    for v in changed:
        assert v[2] == pytest.approx(70.0)

    assert len(unchanged) == 6

    for v in changed:
        x = v[0]
        y = v[1]
        found = False
        for bp in upper_before.values():
            if abs(bp[0] - x) < 0.01 and abs(bp[1] - y) < 0.01:
                assert bp[2] == pytest.approx(100.0)
                found = True
                break
        assert found, f"Changed vertex ({x},{y},{v[2]}) has no matching original"

    result_fm = Picker.indexed_map(result, SelectionKind.FACE)
    assert result_fm.Extent() == 6

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(result, props)
    assert props.Mass() != pytest.approx(_volume(upper), rel=1e-6)

    assert _volume(base) == pytest.approx(200 * 160 * 40)


def test_edge_move_on_sketch_extruded_body_creates_wedge() -> None:
    _skip_without_cad_dependencies()

    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.gp import gp_Dir, gp_Pnt
    from OCP.TopoDS import TopoDS

    from cad_app.commands import move_edge_controlled
    from cad_app.engine import make_box
    from cad_app.picker import Picker
    from cad_app.scene import Scene
    from cad_app.sketch import extrude_profile, make_center_rectangle_profile
    from cad_app.types import SelectionKind
    from cad_app.workplane import Workplane

    scene = Scene()
    base = make_box(200, 160, 40)
    scene.add_shape(base, meta={"kind": "body"})

    wp = Workplane(
        origin=gp_Pnt(0, 0, 40),
        normal=gp_Dir(0, 0, 1),
        x_direction=gp_Dir(1, 0, 0),
        y_direction=gp_Dir(0, 1, 0),
    )
    profile = make_center_rectangle_profile(wp, (0, 0), (50, 30))
    profile_face = TopoDS.Face_s(profile)
    upper_shape = extrude_profile(profile_face, 60)
    scene.add_shape(upper_shape, meta={"kind": "body", "source": "sketch_new_body"})

    vm_before = Picker.indexed_map(upper_shape, SelectionKind.VERTEX)
    before_set = set()
    for i in range(1, vm_before.Extent() + 1):
        p = BRep_Tool.Pnt_s(TopoDS.Vertex_s(vm_before.FindKey(i)))
        before_set.add((round(p.X(), 6), round(p.Y(), 6), round(p.Z(), 6)))

    target = None
    em = Picker.indexed_map(upper_shape, SelectionKind.EDGE)
    for idx in range(1, em.Extent() + 1):
        edge = TopoDS.Edge_s(em.FindKey(idx))
        c = BRepAdaptor_Curve(edge)
        s = c.Value(c.FirstParameter())
        e = c.Value(c.LastParameter())
        if (
            abs(s.Z() - e.Z()) < 0.1
            and min(s.Z(), e.Z()) > 95
            and min(s.Y(), e.Y()) < -25
        ):
            target = idx
            break

    assert target is not None, "Could not find top-front edge of upper body"

    result = move_edge_controlled(upper_shape, target, 0, 0, -30)

    assert BRepCheck_Analyzer(result).IsValid()

    after_vm = Picker.indexed_map(result, SelectionKind.VERTEX)
    after_set = set()
    for i in range(1, after_vm.Extent() + 1):
        p = BRep_Tool.Pnt_s(TopoDS.Vertex_s(after_vm.FindKey(i)))
        after_set.add((round(p.X(), 6), round(p.Y(), 6), round(p.Z(), 6)))

    changed = after_set - before_set
    unchanged = before_set & after_set

    assert len(changed) == 2, f"Expected 2 vertices moved, got {len(changed)}"
    assert len(unchanged) == 6, f"Expected 6 vertices unchanged, got {len(unchanged)}"

    for v in changed:
        assert v[2] == pytest.approx(70.0), f"Expected z=70, got z={v[2]:.1f}"

    result_fm = Picker.indexed_map(result, SelectionKind.FACE)
    assert result_fm.Extent() == 6

    assert abs(_volume(result)) == pytest.approx(270000)
    assert _volume(base) == pytest.approx(200 * 160 * 40)
