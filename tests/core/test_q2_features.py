"""Tests for the Q2 feature batch: project save/load, mirror, rib,
axis-distance measure, workplane corner anchor, and the improved
face-move error message."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from tests.conftest import require_ocp
from tests.helpers.topology import bounding_box

# --- project save / load --------------------------------------------------


def test_project_round_trip_preserves_shape_meta_and_item_ids() -> None:
    require_ocp()

    from cad_app.commands import apply_boolean_bodies, apply_move_object
    from cad_app.engine import make_box
    from cad_app.io_project import load_project, save_project
    from cad_app.scene import Scene

    scene = Scene()
    base_id = scene.add_shape(
        make_box(80, 40, 8),
        meta={"kind": "body", "source": "primitive_box", "width": 80.0},
    )
    wall_id = scene.add_shape(
        make_box(80, 8, 45),
        meta={"kind": "body", "source": "primitive_box"},
    )
    apply_move_object(scene, wall_id, 0, 16, 8)
    apply_boolean_bodies(scene, base_id, wall_id, "union")

    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "lbracket.cadproj.json")
        save_project(scene, path)
        assert Path(path).is_file()

        loaded = load_project(path)

    assert len(loaded) == 1, "tool body was consumed by the union"
    assert base_id in loaded, "saved item ids must round-trip"
    loaded_item = loaded.get(base_id)
    # Meta survives intact.
    assert loaded_item.meta["kind"] == "body"
    assert loaded_item.meta["source"] == "primitive_box"
    assert loaded_item.meta["width"] == pytest.approx(80.0)
    # Geometry round-trips through BREP exactly.
    bb_saved = bounding_box(scene.get(base_id).shape)
    bb_loaded = bounding_box(loaded_item.shape)
    for key in bb_saved:
        assert bb_loaded[key] == pytest.approx(bb_saved[key], abs=1e-4)


def test_project_load_rejects_unknown_format() -> None:
    require_ocp()

    from cad_app.io_project import ProjectIOError, load_project

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "bad.json"
        path.write_text('{"format": "totally not us", "version": 1}', encoding="utf-8")
        with pytest.raises(ProjectIOError):
            load_project(str(path))


def test_project_save_drops_non_json_meta_values_without_failing() -> None:
    require_ocp()

    from cad_app.engine import make_box
    from cad_app.io_project import load_project, save_project
    from cad_app.scene import Scene

    scene = Scene()
    # Meta with one JSON-safe entry and one non-JSON entry (a function
    # object). Save must succeed and drop the non-JSON entry without
    # raising or silently mangling the value.
    item_id = scene.add_shape(
        make_box(10, 10, 10),
        meta={"keep": 1.5, "drop": lambda x: x},
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "p.json")
        save_project(scene, path)
        loaded = load_project(path)
    assert loaded.get(item_id).meta == {"keep": 1.5}


# --- mirror ---------------------------------------------------------------


def test_mirror_yz_creates_new_body_at_opposite_side() -> None:
    require_ocp()

    from cad_app.commands import apply_mirror_body, apply_move_object
    from cad_app.engine import make_box
    from cad_app.scene import Scene

    scene = Scene()
    body_id = scene.add_shape(make_box(20, 10, 10))
    apply_move_object(scene, body_id, 30, 0, 0)  # body fully at X > 0
    new_id = apply_mirror_body(scene, body_id, "yz", (0.0, 0.0, 0.0))

    assert new_id != body_id, "mirror with keep_original=True must add a new body"
    assert len(scene) == 2
    bb_new = bounding_box(scene.get(new_id).shape)
    # Mirrored body should sit at X < 0.
    assert bb_new["xmax"] <= 1e-6
    assert bb_new["xmin"] < bb_new["xmax"]
    # And mirrored about X=0 of the original (Y and Z untouched).
    bb_orig = bounding_box(scene.get(body_id).shape)
    assert abs(bb_new["xmax"] + bb_orig["xmin"]) < 1e-6


def test_mirror_replace_swaps_in_place() -> None:
    require_ocp()

    from cad_app.commands import apply_mirror_body, apply_move_object
    from cad_app.engine import make_box
    from cad_app.scene import Scene

    scene = Scene()
    body_id = scene.add_shape(make_box(20, 10, 10))
    apply_move_object(scene, body_id, 30, 0, 0)
    new_id = apply_mirror_body(
        scene, body_id, "yz", (0.0, 0.0, 0.0), keep_original=False
    )
    assert new_id == body_id, "replace mode keeps the same item_id"
    assert len(scene) == 1


def test_mirror_offset_plane_reflects_about_that_offset() -> None:
    require_ocp()

    from cad_app.commands import apply_mirror_body, apply_move_object
    from cad_app.engine import make_box
    from cad_app.scene import Scene

    scene = Scene()
    body_id = scene.add_shape(make_box(20, 10, 10))
    apply_move_object(scene, body_id, 30, 0, 0)
    # Mirror about YZ at X = 5: bbox of new body should straddle X = 5.
    new_id = apply_mirror_body(scene, body_id, "yz", (5.0, 0.0, 0.0))
    bb_new = bounding_box(scene.get(new_id).shape)
    # Original spans X=[20,40]. Mirror about X=5 -> X=[-30,-10].
    assert bb_new["xmin"] == pytest.approx(-30.0, abs=1e-4)
    assert bb_new["xmax"] == pytest.approx(-10.0, abs=1e-4)


# --- workplane corner anchor ---------------------------------------------


def test_workplane_from_face_corner_anchors_origin_at_bbox_corner() -> None:
    require_ocp()

    from cad_app.command_topology import _face_by_index
    from cad_app.engine import make_box
    from cad_app.picker import Picker
    from cad_app.types import SelectionKind
    from cad_app.workplane import Workplane

    # Make a box centred at origin: X[-40,40], Y[-20,20], Z[0,8].
    box = make_box(80, 40, 8)
    # Find the top face (+Z normal).
    fmap = Picker.indexed_map(box, SelectionKind.FACE)
    top_index = None
    for i in range(1, fmap.Extent() + 1):
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_Plane
        from OCP.TopoDS import TopoDS

        face = TopoDS.Face_s(fmap.FindKey(i))
        surf = BRepAdaptor_Surface(face)
        if surf.GetType() != GeomAbs_Plane:
            continue
        loc = surf.Plane().Location()
        if abs(loc.Z() - 8.0) < 0.05:
            top_index = i
            break
    assert top_index is not None

    centroid_wp = Workplane.from_face(_face_by_index(box, top_index))
    corner_wp = Workplane.from_face_corner(_face_by_index(box, top_index))

    # Centroid sits at (0, 0, 8) for an axis-aligned, centred face.
    assert centroid_wp.origin.X() == pytest.approx(0.0, abs=1e-4)
    assert centroid_wp.origin.Y() == pytest.approx(0.0, abs=1e-4)

    # Corner sits at (-40, -20, 8) — the bottom-left corner in UV.
    assert corner_wp.origin.X() == pytest.approx(-40.0, abs=1e-4)
    assert corner_wp.origin.Y() == pytest.approx(-20.0, abs=1e-4)
    assert corner_wp.origin.Z() == pytest.approx(8.0, abs=1e-4)


# --- axis distance --------------------------------------------------------


def test_distance_between_parallel_and_perpendicular_axes() -> None:
    from cad_app.commands import distance_between_axes

    parallel = distance_between_axes(
        ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        ((20.0, 0.0, 100.0), (0.0, 0.0, 1.0)),
    )
    assert parallel == pytest.approx(20.0, abs=1e-6)

    perpendicular = distance_between_axes(
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        ((0.0, 0.0, 7.0), (0.0, 1.0, 0.0)),
    )
    assert perpendicular == pytest.approx(7.0, abs=1e-6)

    parallel_offset = distance_between_axes(
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        ((100.0, 3.0, 4.0), (1.0, 0.0, 0.0)),
    )
    assert parallel_offset == pytest.approx(5.0, abs=1e-6)


def test_cylinder_and_circle_axis_world_lines_match_geometry() -> None:
    require_ocp()

    from cad_app.commands import (
        circle_axis_world_line,
        cylinder_axis_world_line,
    )
    from cad_app.picker import Picker
    from cad_app.sketch import extrude_profile, make_circle_profile
    from cad_app.types import SelectionKind
    from cad_app.workplane import Workplane

    cylinder = extrude_profile(make_circle_profile(Workplane.world_xy(), 5.0), 30.0)
    fmap = Picker.indexed_map(cylinder, SelectionKind.FACE)
    cyl_index = None
    for i in range(1, fmap.Extent() + 1):
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_Cylinder
        from OCP.TopoDS import TopoDS

        face = TopoDS.Face_s(fmap.FindKey(i))
        if BRepAdaptor_Surface(face).GetType() == GeomAbs_Cylinder:
            cyl_index = i
            break
    assert cyl_index is not None
    centre, direction = cylinder_axis_world_line(cylinder, cyl_index)
    assert centre[0] == pytest.approx(0.0, abs=1e-4)
    assert centre[1] == pytest.approx(0.0, abs=1e-4)
    assert abs(direction[2]) == pytest.approx(1.0, abs=1e-4)

    # The bottom circle rim of that cylinder must give the same axis line.
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Circle
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS as _TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape

    emap = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(cylinder, TopAbs_EDGE, emap)
    rim_index = None
    for i in range(1, emap.Extent() + 1):
        edge = _TopoDS.Edge_s(emap.FindKey(i))
        curve = BRepAdaptor_Curve(edge)
        if curve.GetType() == GeomAbs_Circle:
            rim_index = i
            break
    assert rim_index is not None
    rim_centre, rim_direction = circle_axis_world_line(cylinder, rim_index)
    assert rim_centre[0] == pytest.approx(0.0, abs=1e-4)
    assert rim_centre[1] == pytest.approx(0.0, abs=1e-4)
    # Either +Z or -Z (sign depends on edge orientation); either is fine
    # for axis-line semantics.
    assert abs(rim_direction[2]) == pytest.approx(1.0, abs=1e-4)


# --- rib between perpendicular faces -------------------------------------


def test_rib_between_base_top_and_wall_front_grows_body() -> None:
    require_ocp()

    from cad_app.commands import (
        apply_boolean_bodies,
        apply_move_object,
        apply_rib_between_faces,
        face_normal_vector,
        validate_shape,
    )
    from cad_app.engine import make_box
    from cad_app.picker import Picker
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind

    scene = Scene()
    base = scene.add_shape(make_box(80, 40, 8))
    wall = scene.add_shape(make_box(80, 8, 45))
    apply_move_object(scene, wall, 0, 16, 8)
    apply_boolean_bodies(scene, base, wall, "union")

    shape = scene.get(base).shape
    fmap = Picker.indexed_map(shape, SelectionKind.FACE)
    base_top = wall_front = None
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopoDS import TopoDS

    for i in range(1, fmap.Extent() + 1):
        n = face_normal_vector(shape, i)
        face = TopoDS.Face_s(fmap.FindKey(i))
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        c = props.CentreOfMass()
        if n[2] > 0.95 and abs(c.Z() - 8) < 0.1 and c.Y() < 5:
            base_top = i
        if n[1] < -0.95 and c.Z() > 15:
            wall_front = i
    assert base_top is not None and wall_front is not None

    apply_rib_between_faces(
        scene,
        base,
        base_top,
        wall_front,
        along_base=20,
        along_wall=20,
        thickness=6,
        offset_along_shared_edge=0.0,
    )
    rib_shape = scene.get(base).shape
    validate_shape(rib_shape)
    bb_after = bounding_box(rib_shape)
    # Rib lives inside the L-bracket envelope X[-40,40], Y[-20,20],
    # Z[0,53]; with along_base = along_wall = 20 mm and shared edge
    # at Y = 12, the rib reaches Y = -8 and Z = 28 — well inside.
    assert bb_after["xmin"] == pytest.approx(-40.0, abs=1e-3)
    assert bb_after["xmax"] == pytest.approx(40.0, abs=1e-3)
    assert bb_after["zmax"] == pytest.approx(53.0, abs=1e-3)
    # Face count grew (rib added at least 3 new faces).
    extent_before = 8  # base+wall union
    extent_after = Picker.indexed_map(rib_shape, SelectionKind.FACE).Extent()
    assert extent_after > extent_before


def test_rib_rejects_unrelated_face_pair() -> None:
    require_ocp()

    from cad_app.commands import (
        UnsupportedTopologyError,
        apply_rib_between_faces,
    )
    from cad_app.engine import make_box
    from cad_app.scene import Scene

    scene = Scene()
    body = scene.add_shape(make_box(20, 20, 20))
    # Two opposite faces share NO edge.
    with pytest.raises(UnsupportedTopologyError):
        apply_rib_between_faces(
            scene,
            body,
            1,
            2,
            along_base=5,
            along_wall=5,
            thickness=2,
        )


# --- feature tree labelling ---------------------------------------------


def test_feature_step_label_separates_cut_from_boss_and_numbers_per_kind() -> None:
    from cad_app.feature_history import feature_step_label

    cut = {
        "kind": "sketch_profile_feature",
        "params": {"distance": -10.0},
    }
    boss = {
        "kind": "sketch_profile_feature",
        "params": {"distance": 12.0},
    }
    extrude = {
        "kind": "extrude_face",
        "name": "Extrude Face",
        "params": {"distance": 5.0},
    }
    # No per-kind index -> plain name.
    assert "Sketch Cut" in feature_step_label(cut, 1)
    assert "Sketch Boss" in feature_step_label(boss, 2)
    assert "Extrude Face" in feature_step_label(extrude, 3)
    # With per-kind index -> numbered.
    assert "Sketch Cut 1" in feature_step_label(cut, 1, same_kind_index=1)
    assert "Sketch Cut 2" in feature_step_label(cut, 5, same_kind_index=2)
    assert "Sketch Boss 1" in feature_step_label(boss, 7, same_kind_index=1)


# --- arc closes existing polyline -----------------------------------------


def test_arc_closes_existing_polyline_into_single_profile() -> None:
    """Drawing a polyline, switching to arc, then drawing an arc that
    connects the polyline endpoints used to leave two disconnected
    sketch entities. The fix folds them into one closed arc_polyline
    profile and removes the source polyline."""
    require_ocp()

    from cad_app.sketch import (
        make_arc_polyline_profile,
        make_polyline_preview,
    )
    from cad_app.workplane import Workplane

    # Mimic what the GUI commits as an open polyline entity (a
    # construction line_segments shape plus a meta dict with the UV
    # point list). The fix scans that meta to recognise the chain.
    wp = Workplane.world_xy()
    polyline_points = [(0.0, 0.0), (20.0, 0.0), (20.0, 15.0)]
    preview = make_polyline_preview(wp, polyline_points)
    assert preview is not None

    # The arc that closes the chain: endpoint-to-endpoint, bend point
    # outside so the closed area is non-zero.
    arc_start = (20.0, 15.0)  # polyline last
    arc_end = (0.0, 0.0)  # polyline first
    arc_bend = (10.0, 25.0)
    profile = make_arc_polyline_profile(
        wp, arc_start, arc_end, arc_bend, polyline_points
    )
    # The resulting face is a valid closed planar profile.
    from OCP.BRepCheck import BRepCheck_Analyzer

    assert not profile.IsNull()
    assert BRepCheck_Analyzer(profile).IsValid()


# --- improved face-move error message ------------------------------------


def test_face_move_error_message_mentions_face_move() -> None:
    require_ocp()

    from cad_app.command_topology import _face_by_index
    from cad_app.commands import (
        UnsupportedTopologyError,
        apply_move_face_controlled,
    )
    from cad_app.engine import make_box
    from cad_app.scene import Scene
    from cad_app.sketch import apply_profile_feature, make_circle_profile_at
    from cad_app.workplane import Workplane

    scene = Scene()
    body = scene.add_shape(make_box(40, 40, 20))
    # Punch a through-hole so the body grows a cylindrical face;
    # this triggers the _assert_all_faces_planar guard.
    shape = scene.get(body).shape
    from cad_app.picker import Picker
    from cad_app.types import SelectionKind

    fmap = Picker.indexed_map(shape, SelectionKind.FACE)
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.TopoDS import TopoDS

    top_index = None
    for i in range(1, fmap.Extent() + 1):
        face = TopoDS.Face_s(fmap.FindKey(i))
        surf = BRepAdaptor_Surface(face)
        if surf.GetType() != GeomAbs_Plane:
            continue
        loc = surf.Plane().Location()
        if abs(loc.Z() - 20.0) < 0.05:
            top_index = i
            break
    assert top_index is not None
    wp = Workplane.from_face(_face_by_index(shape, top_index))
    profile = make_circle_profile_at(wp, (0.0, 0.0), 5.0)
    holed = apply_profile_feature(shape, profile, -25.0)
    scene.replace_shape(body, holed)

    # Now try a sideways face move. It should raise with a message
    # that names the face-move command, not "edge/vertex move".
    holed_shape = scene.get(body).shape
    # Find any planar face to attempt the move.
    fmap = Picker.indexed_map(holed_shape, SelectionKind.FACE)
    planar_face = None
    for i in range(1, fmap.Extent() + 1):
        face = TopoDS.Face_s(fmap.FindKey(i))
        surf = BRepAdaptor_Surface(face)
        if surf.GetType() == GeomAbs_Plane:
            planar_face = i
            break
    assert planar_face is not None
    with pytest.raises(UnsupportedTopologyError) as exc_info:
        apply_move_face_controlled(scene, body, planar_face, 5.0, 0.0, 0.0)
    message = str(exc_info.value)
    assert "Sideways face move" in message
    assert "normal direction" in message
    assert "edge/vertex" not in message.lower()
