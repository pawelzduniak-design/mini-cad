from __future__ import annotations

import pytest

from tests.conftest import require_ocp
from tests.helpers.topology import assert_valid_shape, bounding_box, count_subshapes


def test_box_primitive_is_valid_and_dimensioned() -> None:
    require_ocp()

    from cad_app.engine import make_box

    shape = make_box(100.0, 80.0, 20.0)
    box = bounding_box(shape)

    assert_valid_shape(shape)
    assert count_subshapes(shape, "solid") == 1
    assert box["width"] == pytest.approx(100.0)
    assert box["depth"] == pytest.approx(80.0)
    assert box["height"] == pytest.approx(20.0)


def test_face_extrude_changes_geometry_without_losing_validity() -> None:
    require_ocp()

    from cad_app.commands import extrude_face, top_planar_face_index
    from cad_app.engine import make_box

    shape = make_box(60.0, 40.0, 20.0)
    result = extrude_face(shape, top_planar_face_index(shape), 10.0)

    assert_valid_shape(result)
    assert count_subshapes(result, "solid") == 1
    assert bounding_box(result)["height"] > bounding_box(shape)["height"]


def test_move_object_translates_whole_body() -> None:
    require_ocp()

    from cad_app.commands import move_shape
    from cad_app.engine import make_box

    shape = make_box(20.0, 20.0, 20.0)
    moved = move_shape(shape, 12.0, 0.0, 0.0)

    assert_valid_shape(moved)
    assert bounding_box(moved)["xmin"] == pytest.approx(
        bounding_box(shape)["xmin"] + 12.0
    )


def test_thread_edge_adds_valid_modeled_thread_to_circular_edge() -> None:
    require_ocp()

    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder

    from cad_app.commands import CommandError, circular_edge_parameters, thread_edge
    from cad_app.picker import Picker
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind

    shape = BRepPrimAPI_MakeCylinder(10.0, 30.0).Shape()
    scene = Scene()
    item_id = scene.add_shape(shape, meta={"kind": "body", "source": "cylinder"})
    picker = Picker(scene)
    edge_index = None
    for index in range(1, picker.count_subshapes(item_id, SelectionKind.EDGE) + 1):
        try:
            circular_edge_parameters(shape, index)
        except (CommandError, IndexError, RuntimeError, ValueError):
            continue
        edge_index = index
        break

    assert edge_index is not None
    threaded = thread_edge(shape, edge_index, pitch=3.0, length=30.0, depth=0.8)

    assert_valid_shape(threaded)
    assert count_subshapes(threaded, "solid") == 1
    assert bounding_box(threaded)["width"] > bounding_box(shape)["width"]


def test_helical_revolve_rejects_profiles_with_inner_loops() -> None:
    require_ocp()

    from cad_app.commands import CommandError
    from cad_app.sketch import make_rectangle_with_circle_cutout_profile
    from cad_app.sketch_features import revolve_profile
    from cad_app.workplane import Workplane

    profile = make_rectangle_with_circle_cutout_profile(
        Workplane.world_xy(),
        (-20.0, -20.0),
        (20.0, 20.0),
        (0.0, 0.0),
        5.0,
    )

    with pytest.raises(CommandError, match="inner loops"):
        revolve_profile(
            profile,
            (0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            angle_degrees=720.0,
            elevation=20.0,
        )
