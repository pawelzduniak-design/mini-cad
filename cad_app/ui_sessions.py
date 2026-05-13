"""Small UI state objects and math helpers shared by the CAD window."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from cad_app.navigation import NavigationController
from cad_app.scene import Scene
from cad_app.types import SelectionKind
from cad_app.viewer import Viewer
from cad_app.workplane import Workplane

EXTRUDE_DRAG_FALLBACK_AXIS = (0.0, -1.0)
EXTRUDE_DRAG_PROBE_DISTANCE = 25.0
DEFAULT_EDGE_PARAMETER = 4.0
ROTATE_DRAG_FALLBACK_AXIS = (1.0, 0.0)


def normalize_screen_axis(
    dx: float,
    dy: float,
) -> tuple[float, float] | None:
    length = math.hypot(dx, dy)
    if length < 2.0:
        return None
    return dx / length, dy / length


def drag_distance_delta(
    dx: float,
    dy: float,
    scale: float,
    screen_axis: tuple[float, float] | None = None,
) -> float:
    if screen_axis is None:
        return dx * scale
    return (dx * screen_axis[0] + dy * screen_axis[1]) * scale


def axis_vector(axis_index: int, value: float) -> tuple[float, float, float]:
    if axis_index == 0:
        return value, 0.0, 0.0
    if axis_index == 1:
        return 0.0, value, 0.0
    if axis_index == 2:
        return 0.0, 0.0, value
    raise ValueError(f"Unsupported axis index: {axis_index}")


def sketch_dimension_label(
    tool: str,
    start_uv: tuple[float, float],
    end_uv: tuple[float, float],
) -> str:
    if tool == "rectangle":
        width = abs(end_uv[0] - start_uv[0])
        height = abs(end_uv[1] - start_uv[1])
        return f"{width:.1f} x {height:.1f}"
    if tool == "center_rectangle":
        width = abs(end_uv[0] - start_uv[0]) * 2.0
        height = abs(end_uv[1] - start_uv[1]) * 2.0
        return f"{width:.1f} x {height:.1f}"
    if tool == "circle":
        radius = math.hypot(end_uv[0] - start_uv[0], end_uv[1] - start_uv[1])
        return f"R {radius:.1f}"
    raise ValueError(f"Unsupported sketch tool: {tool}")


@dataclass
class MainWindow:
    """Wrapper for the Qt main window and viewer widget."""

    window: Any
    viewer_widget: Any
    viewer: Viewer
    scene: Scene
    navigation: NavigationController
    picker: Any
    actions: dict[str, Any]


@dataclass
class MoveSession:
    """UI-only state for an active drag move operation."""

    tool: str
    target_kind: SelectionKind | str
    item_id: str
    index: int | None
    axis_name: str
    axis: tuple[float, float, float]
    item_ids: tuple[str, ...] = ()
    operation: str = "auto"
    distance: float = 0.0
    drag_start: tuple[int, int] | None = None
    drag_origin_distance: float = 0.0
    drag_screen_axis: tuple[float, float] | None = None
    vector: tuple[float, float, float] | None = None
    drag_origin_vector: tuple[float, float, float] = (0.0, 0.0, 0.0)
    drag_view_anchor: tuple[float, float, float] | None = None
    drag_view_normal: tuple[float, float, float] | None = None
    drag_view_start_point: tuple[float, float, float] | None = None
    axis_point: tuple[float, float, float] | None = None
    elevation: float = 0.0


@dataclass
class SketchSession:
    """UI-only state for drawing profiles on a workplane.

    ``host`` is an explicit browser-selected sketch edit target. It is not
    model host metadata; feature-host metadata is controlled separately by
    ``_active_workplane_host`` and should stay absent for default sketches.
    """

    workplane: Workplane
    label: str
    host: tuple[str, int] | None
    tool: str = "center_rectangle"
    start_uv: tuple[float, float] | None = None
    points: list[tuple[float, float]] = field(default_factory=list)
    snap_points: list[tuple[float, float]] = field(default_factory=list)
    profile_ids: list[str] = field(default_factory=list)
    sketch_id: str | None = None
    drag_start_screen: tuple[int, int] | None = None
    drag_moved: bool = False
    drag_end_uv: tuple[float, float] | None = None
    drag_dimensions: str | None = None
