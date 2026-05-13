from __future__ import annotations

import pytest

from tests.conftest import require_ocp
from tests.helpers.topology import assert_valid_shape, bounding_box, count_subshapes


def test_rectangle_sketch_profile_extrudes_to_solid() -> None:
    require_ocp()

    from cad_app.sketch import extrude_profile, make_center_rectangle_profile
    from cad_app.workplane import Workplane

    profile = make_center_rectangle_profile(
        Workplane.world_xy(),
        center=(0.0, 0.0),
        corner=(30.0, 15.0),
    )
    solid = extrude_profile(profile, 20.0)

    assert_valid_shape(profile)
    assert count_subshapes(profile, "face") == 1
    assert_valid_shape(solid)
    assert count_subshapes(solid, "solid") == 1
    assert bounding_box(solid)["height"] > 0.0


def test_revolve_profile_supports_partial_angle_and_elevation() -> None:
    require_ocp()

    from cad_app.sketch import make_rectangle_profile
    from cad_app.sketch_features import revolve_profile
    from cad_app.workplane import Workplane

    profile = make_rectangle_profile(Workplane.world_xy(), width=10.0, height=5.0)
    partial = revolve_profile(
        profile,
        axis_point=(0.0, -2.5, 0.0),
        axis_direction=(1.0, 0.0, 0.0),
        angle_degrees=180.0,
    )
    helical = revolve_profile(
        profile,
        axis_point=(0.0, -2.5, 0.0),
        axis_direction=(1.0, 0.0, 0.0),
        angle_degrees=720.0,
        elevation=20.0,
    )

    assert_valid_shape(partial)
    assert count_subshapes(partial, "solid") == 1
    assert_valid_shape(helical)
    assert count_subshapes(helical, "solid") == 1
    assert bounding_box(helical)["width"] == pytest.approx(30.0, abs=0.5)
