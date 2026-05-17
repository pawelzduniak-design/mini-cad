from __future__ import annotations

import pytest

from cad_app.sketch_graph import (
    SketchGraphSource,
    arc_curve,
    circle_curve,
    corner_rectangle_segments,
    split_sources_at_intersections,
    trim_segment_graph,
)


def test_trim_circle_crossing_rectangle_removes_only_clicked_arc() -> None:
    circle = circle_curve((20.0, -20.0), 65.0)
    assert circle is not None
    sources = (
        SketchGraphSource(
            "rect",
            corner_rectangle_segments((-100.0, -50.0), (50.0, 50.0)),
            {},
        ),
        SketchGraphSource("circle", (), {}, (circle,)),
    )

    result = trim_segment_graph(sources, (80.0, -20.0), max_distance=10.0)

    assert result is not None
    assert result.removed_segment.kind == "arc"
    assert result.removed_segment.source_item_id == "circle"
    assert result.source_item_ids == ("circle",)
    assert result.loop_segments == ()
    assert len(result.open_segments) == 1
    assert result.open_segments[0].kind == "arc"


def test_trim_line_crossing_circle_keeps_circle_when_line_was_clicked() -> None:
    circle = circle_curve((0.0, 100.0), 65.0)
    assert circle is not None
    sources = (
        SketchGraphSource(
            "rect",
            corner_rectangle_segments((-50.0, -50.0), (50.0, 70.0)),
            {},
        ),
        SketchGraphSource("circle", (), {}, (circle,)),
    )

    result = trim_segment_graph(sources, (-50.0, 65.0), max_distance=10.0)

    assert result is not None
    assert result.removed_segment.kind == "line"
    assert result.removed_segment.source_item_id == "rect"
    assert result.source_item_ids == ("rect",)
    assert all(segment.source_item_id == "rect" for segment in result.open_segments)
    assert all(segment.kind == "line" for segment in result.open_segments)


def test_trim_shared_internal_edge_targets_all_owners() -> None:
    sources = (
        SketchGraphSource(
            "left_region",
            (
                ((0.0, 0.0), (10.0, 0.0)),
                ((10.0, 0.0), (10.0, 10.0)),
            ),
            {},
        ),
        SketchGraphSource(
            "right_region",
            (
                ((0.0, 0.0), (10.0, 0.0)),
                ((0.0, 0.0), (0.0, 10.0)),
            ),
            {},
        ),
    )

    result = trim_segment_graph(sources, (5.0, 0.0), max_distance=1.0)

    assert result is not None
    assert result.source_item_ids == ("left_region", "right_region")
    assert all(
        segment.start != (0.0, 0.0) or segment.end != (10.0, 0.0)
        for segment in result.open_segments
    )


def _two_intersecting_circle_sources():
    left = circle_curve((-25.0, 0.0), 40.0)
    right = circle_curve((25.0, 0.0), 40.0)
    assert left is not None
    assert right is not None
    return (
        SketchGraphSource("left_circle", (), {}, (left,)),
        SketchGraphSource("right_circle", (), {}, (right,)),
    )


def test_split_two_intersecting_circles_into_four_arcs() -> None:
    atomic = split_sources_at_intersections(_two_intersecting_circle_sources())

    assert len(atomic) == 4
    assert {segment.source_item_id for segment in atomic} == {
        "left_circle",
        "right_circle",
    }
    assert all(segment.kind == "arc" for segment in atomic)
    assert {round(abs(segment.start[1]), 5) for segment in atomic} == {31.22499}
    assert {round(abs(segment.end[1]), 5) for segment in atomic} == {31.22499}


@pytest.mark.parametrize(
    ("uv", "source_id"),
    [
        ((-65.0, 0.0), "left_circle"),
        ((65.0, 0.0), "right_circle"),
    ],
)
def test_trim_two_intersecting_circles_removes_clicked_outer_arc(
    uv: tuple[float, float],
    source_id: str,
) -> None:
    result = trim_segment_graph(
        _two_intersecting_circle_sources(),
        uv,
        max_distance=10.0,
    )

    assert result is not None
    assert result.removed_segment.kind == "arc"
    assert result.removed_segment.source_item_id == source_id
    assert result.source_item_ids == (source_id,)
    assert result.loop_segments == ()
    assert len(result.open_segments) == 1
    assert result.open_segments[0].source_item_id == source_id


@pytest.mark.parametrize(
    "uv",
    [
        (0.0, 0.0),
    ],
)
def test_trim_two_intersecting_circles_ignores_empty_interior_clicks(
    uv: tuple[float, float],
) -> None:
    result = trim_segment_graph(
        _two_intersecting_circle_sources(),
        uv,
        max_distance=10.0,
    )

    assert result is None


@pytest.mark.parametrize(
    ("uv", "source_id"),
    [
        ((-25.0, 0.0), "right_circle"),
        ((25.0, 0.0), "left_circle"),
    ],
)
def test_trim_two_intersecting_circles_center_click_hits_other_circle_only(
    uv: tuple[float, float],
    source_id: str,
) -> None:
    result = trim_segment_graph(
        _two_intersecting_circle_sources(),
        uv,
        max_distance=10.0,
    )

    assert result is not None
    assert result.source_item_ids == (source_id,)


@pytest.mark.parametrize(
    "uv",
    [
        (0.0, 31.22499),
        (0.0, -31.22499),
    ],
)
def test_trim_two_intersecting_circles_at_intersection_is_deterministic(
    uv: tuple[float, float],
) -> None:
    result = trim_segment_graph(
        _two_intersecting_circle_sources(),
        uv,
        max_distance=1.0,
    )

    assert result is not None
    assert result.removed_segment.kind == "arc"
    assert result.source_item_ids in (("left_circle",), ("right_circle",))
    assert len(result.open_segments) == 1


def test_repeated_trim_of_two_circles_keeps_remaining_arc_stable() -> None:
    sources = _two_intersecting_circle_sources()
    first = trim_segment_graph(sources, (-65.0, 0.0), max_distance=10.0)
    assert first is not None

    second_sources = (
        SketchGraphSource(
            "left_remainder",
            (),
            {},
            tuple(
                circle_curve(segment.center, segment.radius)
                for segment in first.open_segments
                if segment.center is not None and segment.radius is not None
            ),
        ),
        sources[1],
    )
    second = trim_segment_graph(second_sources, (65.0, 0.0), max_distance=10.0)

    assert second is not None
    assert second.removed_segment.source_item_id == "right_circle"


@pytest.mark.parametrize(
    "distance",
    [80.0, 80.000001, 120.0, 0.0],
)
def test_circle_circle_edge_cases_do_not_create_invalid_atomic_segments(
    distance: float,
) -> None:
    first = circle_curve((0.0, 0.0), 40.0)
    second = circle_curve((distance, 0.0), 40.0)
    assert first is not None
    assert second is not None

    atomic = split_sources_at_intersections(
        (
            SketchGraphSource("first", (), {}, (first,)),
            SketchGraphSource("second", (), {}, (second,)),
        )
    )

    assert all(segment.kind == "arc" for segment in atomic)
    assert all(segment.start != segment.end for segment in atomic)
    if distance in {80.0, 80.000001, 120.0, 0.0}:
        assert atomic == ()


def test_trim_respects_max_distance_boundary_for_circle_arc() -> None:
    sources = _two_intersecting_circle_sources()

    assert trim_segment_graph(sources, (-65.0, 0.0), max_distance=0.01) is not None
    assert trim_segment_graph(sources, (-65.0, 16.0), max_distance=2.0) is None


def test_trim_line_arc_intersections_split_both_entities() -> None:
    arc = arc_curve((-40.0, 0.0), (40.0, 0.0), (0.0, 40.0))
    assert arc is not None
    sources = (
        SketchGraphSource("line", (((-50.0, 20.0), (50.0, 20.0)),), {}, ()),
        SketchGraphSource("arc", (), {}, (arc,)),
    )

    atomic = split_sources_at_intersections(sources)
    assert len(atomic) == 6

    line_trim = trim_segment_graph(sources, (0.0, 20.0), max_distance=5.0)
    assert line_trim is not None
    assert line_trim.removed_segment.source_item_id == "line"
    assert line_trim.removed_segment.kind == "line"
    assert len(line_trim.open_segments) == 2

    arc_trim = trim_segment_graph(sources, (0.0, 40.0), max_distance=5.0)
    assert arc_trim is not None
    assert arc_trim.removed_segment.source_item_id == "arc"
    assert arc_trim.removed_segment.kind == "arc"
    assert len(arc_trim.open_segments) == 2


def test_trim_crossing_lines_removes_only_clicked_half_segment() -> None:
    sources = (
        SketchGraphSource("horizontal", (((-40.0, 0.0), (40.0, 0.0)),), {}, ()),
        SketchGraphSource("vertical", (((0.0, -40.0), (0.0, 40.0)),), {}, ()),
    )

    atomic = split_sources_at_intersections(sources)
    assert len(atomic) == 4

    result = trim_segment_graph(sources, (20.0, 0.0), max_distance=5.0)

    assert result is not None
    assert result.removed_segment.source_item_id == "horizontal"
    assert result.removed_segment.start == (0.0, 0.0)
    assert result.removed_segment.end == (40.0, 0.0)
    assert len(result.open_segments) == 1
    assert result.open_segments[0].start == (-40.0, 0.0)
    assert result.open_segments[0].end == (0.0, 0.0)


def test_trim_crossing_arcs_removes_clicked_arc_section() -> None:
    upper = arc_curve((-40.0, 0.0), (40.0, 0.0), (0.0, 40.0))
    lower = arc_curve((-40.0, 20.0), (40.0, 20.0), (0.0, -20.0))
    assert upper is not None
    assert lower is not None
    sources = (
        SketchGraphSource("upper", (), {}, (upper,)),
        SketchGraphSource("lower", (), {}, (lower,)),
    )

    atomic = split_sources_at_intersections(sources)
    assert len(atomic) == 6

    result = trim_segment_graph(sources, (0.0, 40.0), max_distance=6.0)

    assert result is not None
    assert result.removed_segment.source_item_id == "upper"
    assert result.removed_segment.kind == "arc"
    assert len(result.open_segments) == 2
