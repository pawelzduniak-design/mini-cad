from importlib.util import find_spec

import pytest


def _skip_without_cad_dependencies() -> None:
    if find_spec("OCP") is None:
        pytest.skip("OCP is not installed in the active environment.")


def _count_subshapes(shape, topology) -> int:
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    shape_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, topology, shape_map)
    return shape_map.Extent()


def _volume(shape) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def _top_face(shape):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopoDS import TopoDS

    from cad_app.picker import Picker
    from cad_app.types import SelectionKind

    face_map = Picker.indexed_map(shape, SelectionKind.FACE)
    top_face = None
    top_z = -float("inf")
    for index in range(1, face_map.Extent() + 1):
        face = TopoDS.Face_s(face_map.FindKey(index))
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        z_value = props.CentreOfMass().Z()
        if z_value > top_z:
            top_z = z_value
            top_face = face
    assert top_face is not None
    return top_face


def test_world_xy_workplane_has_expected_axes() -> None:
    _skip_without_cad_dependencies()

    from cad_app.workplane import Workplane

    workplane = Workplane.world_xy()

    assert workplane.origin.Z() == pytest.approx(0.0)
    assert workplane.normal.Z() == pytest.approx(1.0)
    assert workplane.x_direction.X() == pytest.approx(1.0)
    assert workplane.y_direction.Y() == pytest.approx(1.0)


def test_rectangle_profile_is_valid_planar_face() -> None:
    _skip_without_cad_dependencies()

    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE

    from cad_app.sketch import make_rectangle_profile
    from cad_app.workplane import Workplane

    profile = make_rectangle_profile(Workplane.world_xy(), width=60.0, height=40.0)

    assert _count_subshapes(profile, TopAbs_FACE) == 1
    assert _count_subshapes(profile, TopAbs_EDGE) == 4


def test_point_marker_preview_draws_two_visible_edges() -> None:
    _skip_without_cad_dependencies()

    from OCP.TopAbs import TopAbs_EDGE

    from cad_app.sketch import make_point_marker_preview
    from cad_app.workplane import Workplane

    marker = make_point_marker_preview(Workplane.world_xy(), (4.0, -2.0), size=3.0)

    assert _count_subshapes(marker, TopAbs_EDGE) == 2


def test_rectangle_profile_from_drag_corners_is_valid() -> None:
    _skip_without_cad_dependencies()

    from OCP.TopAbs import TopAbs_EDGE

    from cad_app.sketch import make_rectangle_profile_from_corners
    from cad_app.workplane import Workplane

    profile = make_rectangle_profile_from_corners(
        Workplane.world_xy(),
        (10.0, 5.0),
        (-20.0, -15.0),
    )

    assert _count_subshapes(profile, TopAbs_EDGE) == 4


def test_center_rectangle_profile_expands_from_center() -> None:
    _skip_without_cad_dependencies()

    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.TopAbs import TopAbs_EDGE

    from cad_app.sketch import make_center_rectangle_profile
    from cad_app.workplane import Workplane

    profile = make_center_rectangle_profile(
        Workplane.world_xy(),
        (0.0, 0.0),
        (30.0, 15.0),
    )
    box = Bnd_Box()
    BRepBndLib.Add_s(profile, box)
    xmin, ymin, _zmin, xmax, ymax, _zmax = box.Get()

    assert _count_subshapes(profile, TopAbs_EDGE) == 4
    assert xmax - xmin == pytest.approx(60.0)
    assert ymax - ymin == pytest.approx(30.0)


def test_three_point_rectangle_profile_can_be_rotated() -> None:
    _skip_without_cad_dependencies()

    from OCP.TopAbs import TopAbs_EDGE

    from cad_app.sketch import make_rectangle_profile_three_point
    from cad_app.workplane import Workplane

    profile = make_rectangle_profile_three_point(
        Workplane.world_xy(),
        (0.0, 0.0),
        (40.0, 0.0),
        (0.0, 20.0),
    )

    assert _count_subshapes(profile, TopAbs_EDGE) == 4


def test_closed_polyline_profile_and_interior_detection() -> None:
    _skip_without_cad_dependencies()

    from OCP.TopAbs import TopAbs_EDGE

    from cad_app.sketch import (
        is_closed_polyline,
        make_polyline_profile,
        profile_contains_uv,
    )
    from cad_app.workplane import Workplane

    workplane = Workplane.world_xy()
    points = [(0.0, 0.0), (40.0, 0.0), (40.0, 20.0), (0.0, 20.0), (0.0, 0.0)]
    profile = make_polyline_profile(workplane, points)

    assert is_closed_polyline(points)
    assert _count_subshapes(profile, TopAbs_EDGE) == 4
    assert profile_contains_uv(profile, workplane, (20.0, 10.0))
    assert not profile_contains_uv(profile, workplane, (80.0, 80.0))


def test_circle_profile_is_valid_planar_face() -> None:
    _skip_without_cad_dependencies()

    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE

    from cad_app.sketch import make_circle_profile
    from cad_app.workplane import Workplane

    profile = make_circle_profile(Workplane.world_xy(), radius=20.0)

    assert _count_subshapes(profile, TopAbs_FACE) == 1
    assert _count_subshapes(profile, TopAbs_EDGE) == 1


def test_circle_profile_from_drag_center_is_valid() -> None:
    _skip_without_cad_dependencies()

    from OCP.TopAbs import TopAbs_EDGE

    from cad_app.sketch import make_circle_profile_at
    from cad_app.workplane import Workplane

    profile = make_circle_profile_at(Workplane.world_xy(), (10.0, -5.0), radius=12.0)

    assert _count_subshapes(profile, TopAbs_EDGE) == 1


def test_circle_profile_interior_detection() -> None:
    _skip_without_cad_dependencies()

    from cad_app.sketch import make_circle_profile_at, profile_contains_uv
    from cad_app.workplane import Workplane

    workplane = Workplane.world_xy()
    profile = make_circle_profile_at(workplane, (0.0, 0.0), radius=10.0)

    assert profile_contains_uv(profile, workplane, (0.0, 0.0))
    assert not profile_contains_uv(profile, workplane, (30.0, 0.0))


def test_three_point_arc_edge_has_radius() -> None:
    _skip_without_cad_dependencies()

    from OCP.TopAbs import TopAbs_EDGE

    from cad_app.sketch import (
        make_arc_chord_profile,
        make_three_point_arc_edge,
        profile_contains_uv,
        three_point_arc_radius,
    )
    from cad_app.workplane import Workplane

    workplane = Workplane.world_xy()
    edge = make_three_point_arc_edge(
        workplane,
        (-20.0, 0.0),
        (20.0, 0.0),
        (0.0, 15.0),
    )
    profile = make_arc_chord_profile(
        workplane,
        (-20.0, 0.0),
        (20.0, 0.0),
        (0.0, 15.0),
    )

    assert _count_subshapes(edge, TopAbs_EDGE) == 1
    assert _count_subshapes(profile, TopAbs_EDGE) == 2
    assert profile_contains_uv(profile, workplane, (0.0, 5.0))
    assert three_point_arc_radius((-20.0, 0.0), (20.0, 0.0), (0.0, 15.0)) > 0


def test_ray_to_workplane_uv_projects_to_local_coordinates() -> None:
    _skip_without_cad_dependencies()

    from cad_app.sketch import ray_to_workplane_uv
    from cad_app.workplane import Workplane

    uv = ray_to_workplane_uv(
        Workplane.world_xy(),
        ray_origin=(12.0, -8.0, 100.0),
        ray_direction=(0.0, 0.0, -1.0),
    )

    assert uv == pytest.approx((12.0, -8.0))


def test_extrude_profile_turns_rectangle_into_solid() -> None:
    _skip_without_cad_dependencies()

    from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID

    from cad_app.sketch import extrude_profile, make_rectangle_profile
    from cad_app.workplane import Workplane

    profile = make_rectangle_profile(Workplane.world_xy(), width=60.0, height=40.0)
    solid = extrude_profile(profile, distance=25.0)

    assert _count_subshapes(solid, TopAbs_SOLID) == 1
    assert _count_subshapes(solid, TopAbs_FACE) == 6
    assert _volume(solid) == pytest.approx(60.0 * 40.0 * 25.0)


def test_profile_feature_fuses_or_cuts_host_body() -> None:
    _skip_without_cad_dependencies()

    from cad_app.engine import make_box
    from cad_app.sketch import apply_profile_feature, make_circle_profile
    from cad_app.workplane import Workplane

    body = make_box(80.0, 80.0, 40.0)
    profile = make_circle_profile(Workplane.from_face(_top_face(body)), radius=10.0)

    boss = apply_profile_feature(body, profile, distance=15.0)
    cut = apply_profile_feature(body, profile, distance=-15.0)

    assert _volume(boss) > _volume(body)
    assert _volume(cut) < _volume(body)


def test_sketch_profile_meta_predicate() -> None:
    from cad_app.sketch import (
        SKETCH_ENTITY_META_KIND,
        SKETCH_META_KIND,
        is_sketch_entity,
        is_sketch_object,
        is_sketch_profile,
    )

    assert is_sketch_profile({"kind": SKETCH_META_KIND})
    assert not is_sketch_profile({"kind": SKETCH_ENTITY_META_KIND})
    assert is_sketch_entity({"kind": SKETCH_ENTITY_META_KIND})
    assert is_sketch_object({"kind": SKETCH_META_KIND})
    assert is_sketch_object({"kind": SKETCH_ENTITY_META_KIND})
    assert not is_sketch_profile({"kind": "body"})
