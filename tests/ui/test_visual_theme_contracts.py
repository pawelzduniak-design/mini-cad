from __future__ import annotations

import math

from cad_app import theme
from cad_app.viewer_markers import (
    selection_marker_color_for_meta,
    sketch_preview_marker_color,
)


def _rgb_distance(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(first, second)))


def test_sketch_and_face_selection_colors_are_distinct() -> None:
    colors = {
        "face_selected": theme.FACE_SELECTED,
        "face_hover": theme.FACE_HOVER,
        "preview_blue": theme.PREVIEW_BLUE,
        "sketch_profile": theme.SKETCH_PROFILE,
        "sketch_selected": theme.SKETCH_PROFILE_SELECTED,
        "sketch_preview": theme.SKETCH_PREVIEW,
    }

    for first_name, first_color in colors.items():
        for second_name, second_color in colors.items():
            if first_name >= second_name:
                continue
            assert _rgb_distance(first_color, second_color) >= 0.20, (
                first_name,
                second_name,
            )


def test_sketch_marker_colors_do_not_reuse_face_or_body_preview_tokens() -> None:
    assert (
        selection_marker_color_for_meta({"kind": "sketch_profile"})
        == theme.SKETCH_PROFILE_SELECTED
    )
    assert selection_marker_color_for_meta({"kind": "body"}) == theme.FACE_SELECTED
    assert (
        selection_marker_color_for_meta({"kind": "sketch_profile"})
        != theme.FACE_SELECTED
    )
    assert (
        selection_marker_color_for_meta({"kind": "sketch_profile"})
        != theme.PREVIEW_BLUE
    )
    assert sketch_preview_marker_color() == theme.SKETCH_PREVIEW
    assert sketch_preview_marker_color() != theme.PREVIEW_BLUE
