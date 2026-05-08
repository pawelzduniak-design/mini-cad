"""Camera navigation controller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class HomeView:
    eye: tuple[float, float, float]
    at: tuple[float, float, float]
    up: tuple[float, float, float]
    scale: float


class NavigationController:
    """Navigation controller with orbit, pan, zoom, and home view."""

    def __init__(self) -> None:
        self.enabled = True
        self.zoom_min = 0.01
        self.zoom_max = 1000.0
        self.zoom_speed = 1.1
        self.max_zoom_steps_per_event = 2.0
        self.rotate_speed = 1.0
        self.pan_speed = 1.0

        self._view: Any | None = None
        self._home: HomeView | None = None
        self._is_orbiting = False
        self._is_panning = False
        self._last_pos: tuple[int, int] | None = None

    def attach_view(self, view: Any) -> None:
        self._view = view

    def capture_home(self) -> None:
        if self._view is None:
            return
        if not all(hasattr(self._view, name) for name in ("Eye", "At", "Up", "Scale")):
            return
        eye = self._view.Eye()
        at = self._view.At()
        up = self._view.Up()
        scale = float(self._view.Scale())
        self._home = HomeView(eye, at, up, scale)

    def go_home(self) -> None:
        if self._view is None or self._home is None:
            return
        if hasattr(self._view, "SetEye"):
            self._view.SetEye(*self._home.eye)
        if hasattr(self._view, "SetAt"):
            self._view.SetAt(*self._home.at)
        if hasattr(self._view, "SetUp"):
            self._view.SetUp(*self._home.up)
        if hasattr(self._view, "SetScale"):
            self._view.SetScale(self._home.scale)
        if hasattr(self._view, "Redraw"):
            self._view.Redraw()

    def fit_all(self) -> None:
        if self._view is None or not hasattr(self._view, "FitAll"):
            return
        self._view.FitAll()
        if hasattr(self._view, "Redraw"):
            self._view.Redraw()

    def view_workplane(self, workplane: Any) -> None:
        """Orient the camera perpendicular to a sketch workplane."""
        if self._view is None or not hasattr(self._view, "SetProj"):
            return
        normal = workplane.normal
        y_direction = workplane.y_direction
        self._view.SetProj(normal.X(), normal.Y(), normal.Z())
        if hasattr(self._view, "SetUp"):
            self._view.SetUp(y_direction.X(), y_direction.Y(), y_direction.Z())
        if hasattr(self._view, "ZFitAll"):
            self._view.ZFitAll()
        if hasattr(self._view, "Redraw"):
            self._view.Redraw()

    def view_axis(self, axis: str, positive: bool = True) -> None:
        """Orient the camera along one world axis."""
        if self._view is None or not hasattr(self._view, "SetProj"):
            return
        axis_key = axis.lower()
        if axis_key not in {"x", "y", "z"}:
            raise ValueError(f"Unsupported view axis: {axis}")
        sign = 1.0 if positive else -1.0
        directions = {
            "x": (sign, 0.0, 0.0),
            "y": (0.0, sign, 0.0),
            "z": (0.0, 0.0, sign),
        }
        up_vectors = {
            "x": (0.0, 0.0, 1.0),
            "y": (0.0, 0.0, 1.0),
            "z": (0.0, 1.0, 0.0),
        }
        self._view.SetProj(*directions[axis_key])
        if hasattr(self._view, "SetUp"):
            self._view.SetUp(*up_vectors[axis_key])
        if hasattr(self._view, "ZFitAll"):
            self._view.ZFitAll()
        if hasattr(self._view, "Redraw"):
            self._view.Redraw()

    def _clamp_scale(self, scale: float) -> float:
        return max(self.zoom_min, min(self.zoom_max, scale))

    def is_interacting(self) -> bool:
        return self._is_orbiting or self._is_panning

    def _zoom_steps(self, delta: int) -> float:
        steps = -delta / 120.0
        return max(
            -self.max_zoom_steps_per_event,
            min(self.max_zoom_steps_per_event, steps),
        )

    def zoom_at_cursor(
        self,
        delta: int,
        x: int | None = None,
        y: int | None = None,
    ) -> None:
        if self._view is None or not hasattr(self._view, "Scale"):
            return
        if delta == 0 or self.is_interacting():
            return

        steps = self._zoom_steps(delta)
        factor = self.zoom_speed**steps
        current = float(self._view.Scale())
        target = self._clamp_scale(current / factor)
        if hasattr(self._view, "SetScale"):
            self._view.SetScale(target)
        if hasattr(self._view, "Redraw"):
            self._view.Redraw()

    def begin_orbit(self, x: int, y: int) -> None:
        if self._view is None or not hasattr(self._view, "StartRotation"):
            return
        self._is_orbiting = True
        self._last_pos = (x, y)
        self._view.StartRotation(x, y)

    def orbit_to(self, x: int, y: int) -> None:
        if not self._is_orbiting or self._view is None:
            return
        if hasattr(self._view, "Rotation"):
            self._view.Rotation(x, y)
        self._last_pos = (x, y)

    def end_orbit(self) -> None:
        self._is_orbiting = False
        self._last_pos = None

    def begin_pan(self, x: int, y: int) -> None:
        self._is_panning = True
        self._last_pos = (x, y)

    def pan_to(self, x: int, y: int) -> None:
        if not self._is_panning or self._view is None or self._last_pos is None:
            return
        if not hasattr(self._view, "Pan"):
            return
        dx = int(round((x - self._last_pos[0]) * self.pan_speed))
        dy = int(round((self._last_pos[1] - y) * self.pan_speed))
        self._view.Pan(dx, dy)
        if hasattr(self._view, "Redraw"):
            self._view.Redraw()
        self._last_pos = (x, y)

    def end_pan(self) -> None:
        self._is_panning = False
        self._last_pos = None
