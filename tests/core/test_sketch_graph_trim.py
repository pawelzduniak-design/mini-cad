from __future__ import annotations

from cad_app.sketch_graph import (
    SketchGraphSource,
    circle_curve,
    corner_rectangle_segments,
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
