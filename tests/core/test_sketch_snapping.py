from __future__ import annotations

from cad_app.sketch_snapping import (
    SnapCandidate,
    choose_snap,
    grid_snapped_uv,
    nearest_point_on_segment,
)


def test_nearest_point_on_segment_projects_inside() -> None:
    # Closest point to (5, 5) on the X axis segment is (5, 0).
    assert nearest_point_on_segment((0.0, 0.0), (10.0, 0.0), (5.0, 5.0)) == (5.0, 0.0)


def test_nearest_point_on_segment_clamps_past_ends() -> None:
    # Projection lands past B, so it clamps to the endpoint.
    assert nearest_point_on_segment((0.0, 0.0), (10.0, 0.0), (20.0, 3.0)) == (
        10.0,
        0.0,
    )


def test_nearest_point_on_segment_degenerate_segment_returns_a() -> None:
    assert nearest_point_on_segment((2.0, 2.0), (2.0, 2.0), (9.0, 9.0)) == (2.0, 2.0)


def test_grid_snapped_uv_rounds_to_step() -> None:
    assert grid_snapped_uv((12.0, -7.0), 10.0) == (10.0, -10.0)


def test_grid_snapped_uv_ignores_nonpositive_step() -> None:
    assert grid_snapped_uv((12.0, -7.0), 0.0) == (12.0, -7.0)


def _identity_to_screen(uv: tuple[float, float]) -> tuple[float, float]:
    # 1 UV unit == 1 pixel for these tests.
    return uv


def test_choose_snap_prefers_stronger_type_over_closer_distance() -> None:
    cursor = (0.0, 0.0)
    candidates = [
        SnapCandidate(uv=(2.0, 0.0), kind="on_edge"),  # 2 px away
        SnapCandidate(uv=(4.0, 0.0), kind="endpoint"),  # 4 px away, stronger
    ]
    chosen = choose_snap(candidates, _identity_to_screen, cursor, pixel_tolerance=12.0)
    assert chosen is not None
    assert chosen.kind == "endpoint"


def test_choose_snap_breaks_type_tie_by_distance() -> None:
    cursor = (0.0, 0.0)
    candidates = [
        SnapCandidate(uv=(6.0, 0.0), kind="endpoint"),
        SnapCandidate(uv=(3.0, 0.0), kind="endpoint"),
    ]
    chosen = choose_snap(candidates, _identity_to_screen, cursor, pixel_tolerance=12.0)
    assert chosen is not None
    assert chosen.uv == (3.0, 0.0)


def test_choose_snap_rejects_candidates_outside_tolerance() -> None:
    cursor = (0.0, 0.0)
    candidates = [SnapCandidate(uv=(20.0, 0.0), kind="endpoint")]
    assert (
        choose_snap(candidates, _identity_to_screen, cursor, pixel_tolerance=12.0)
        is None
    )


def test_choose_snap_skips_unprojectable_candidates() -> None:
    cursor = (0.0, 0.0)
    candidates = [
        SnapCandidate(uv=(1.0, 0.0), kind="endpoint"),
        SnapCandidate(uv=(2.0, 0.0), kind="grid"),
    ]

    def to_screen(uv: tuple[float, float]) -> tuple[float, float] | None:
        if uv == (1.0, 0.0):
            return None  # behind the camera / off-projection
        return uv

    chosen = choose_snap(candidates, to_screen, cursor, pixel_tolerance=12.0)
    assert chosen is not None
    assert chosen.kind == "grid"


def test_choose_snap_empty_returns_none() -> None:
    assert choose_snap([], _identity_to_screen, (0.0, 0.0)) is None
