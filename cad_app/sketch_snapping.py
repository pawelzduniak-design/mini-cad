"""Pure geometry helpers for sketch snapping.

Kept free of Qt/OCCT so the snap selection math can be unit-tested in
isolation. The widget layer gathers candidates from the host face, other
bodies, and the grid, then asks :func:`choose_snap` to pick the best one
in screen space (consistent feel at any zoom).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

UV = tuple[float, float]

# Lower number wins. A vertex/centre is a stronger target than a point
# anywhere along an edge, which in turn beats the background grid.
SNAP_TYPE_PRIORITY: dict[str, int] = {
    "endpoint": 0,
    "center": 0,
    "midpoint": 1,
    "on_edge": 2,
    "grid": 3,
}

# Human-readable labels for the status line / HUD.
SNAP_TYPE_LABELS: dict[str, str] = {
    "endpoint": "wierzchołek",
    "center": "środek",
    "midpoint": "środek krawędzi",
    "on_edge": "krawędź",
    "grid": "siatka",
}


@dataclass(frozen=True)
class SnapCandidate:
    """A potential snap target expressed in workplane UV coordinates."""

    uv: UV
    kind: str

    @property
    def priority(self) -> int:
        return SNAP_TYPE_PRIORITY.get(self.kind, 99)

    @property
    def label(self) -> str:
        return SNAP_TYPE_LABELS.get(self.kind, self.kind)


def nearest_point_on_segment(a: UV, b: UV, p: UV) -> UV:
    """Return the point on segment ``a``-``b`` closest to ``p`` (clamped)."""
    ax, ay = a
    bx, by = b
    px, py = p
    dx = bx - ax
    dy = by - ay
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-12:
        return a
    t = ((px - ax) * dx + (py - ay) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    return (ax + dx * t, ay + dy * t)


def grid_snapped_uv(uv: UV, step: float) -> UV:
    """Round a UV coordinate to the nearest grid node of ``step``."""
    if step <= 0.0:
        return uv
    return (round(uv[0] / step) * step, round(uv[1] / step) * step)


def choose_snap(
    candidates: list[SnapCandidate],
    to_screen: Callable[[UV], tuple[float, float] | None],
    cursor_screen: tuple[float, float],
    *,
    pixel_tolerance: float = 12.0,
    type_priority: dict[str, int] | None = None,
) -> SnapCandidate | None:
    """Pick the best snap candidate within ``pixel_tolerance`` of the cursor.

    ``to_screen`` maps a UV point to widget pixels (or ``None`` if it cannot
    be projected). Candidates are ranked by (type priority, screen distance):
    a stronger snap type wins even if a weaker one is a few pixels closer.
    Returns ``None`` when nothing falls within tolerance.
    """
    priority = type_priority or SNAP_TYPE_PRIORITY
    best: SnapCandidate | None = None
    best_key: tuple[int, float] | None = None
    for candidate in candidates:
        screen = to_screen(candidate.uv)
        if screen is None:
            continue
        distance = math.hypot(
            screen[0] - cursor_screen[0],
            screen[1] - cursor_screen[1],
        )
        if distance > pixel_tolerance:
            continue
        key = (priority.get(candidate.kind, 99), distance)
        if best_key is None or key < best_key:
            best_key = key
            best = candidate
    return best
