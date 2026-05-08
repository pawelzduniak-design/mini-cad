import pytest

from cad_app.navigation import NavigationController


class FakeView:
    def __init__(self, scale: float = 1.0) -> None:
        self._scale = scale
        self.last_pan = None
        self.redraw_calls = 0
        self.proj = None
        self.z_fit_calls = 0
        self._eye = (0.0, 0.0, 10.0)
        self._at = (0.0, 0.0, 0.0)
        self._up = (0.0, 1.0, 0.0)

    def Scale(self) -> float:
        return self._scale

    def SetScale(self, value: float) -> None:
        self._scale = value

    def Pan(self, dx: int, dy: int) -> None:
        if not isinstance(dx, int) or not isinstance(dy, int):
            raise TypeError("Pan expects integer pixel deltas.")
        self.last_pan = (dx, dy)

    def Redraw(self) -> None:
        self.redraw_calls += 1

    def SetProj(self, x: float, y: float, z: float) -> None:
        self.proj = (x, y, z)

    def ZFitAll(self) -> None:
        self.z_fit_calls += 1

    def Eye(self):
        return self._eye

    def At(self):
        return self._at

    def Up(self):
        return self._up

    def SetEye(self, x: float, y: float, z: float) -> None:
        self._eye = (x, y, z)

    def SetAt(self, x: float, y: float, z: float) -> None:
        self._at = (x, y, z)

    def SetUp(self, x: float, y: float, z: float) -> None:
        self._up = (x, y, z)


class FakeCursorZoomView(FakeView):
    def __init__(self, scale: float = 1.0) -> None:
        super().__init__(scale)
        self.zoom_start = None
        self.zoom_end = None

    def StartZoomAtPoint(self, x: int, y: int) -> None:
        self.zoom_start = (x, y)

    def ZoomAtPoint(self, x1: int, y1: int, x2: int, y2: int) -> None:
        self.zoom_end = (x1, y1, x2, y2)


def test_zoom_clamps_scale() -> None:
    view = FakeView(scale=1.0)
    nav = NavigationController()
    nav.attach_view(view)
    nav.zoom_min = 0.5
    nav.zoom_max = 2.0

    nav.zoom_at_cursor(120)
    assert view.Scale() > 1.0

    view.SetScale(0.6)
    nav.zoom_at_cursor(-12000)
    assert view.Scale() == 0.5

    view.SetScale(1.8)
    nav.zoom_at_cursor(12000)
    assert view.Scale() == 2.0


def test_zoom_uses_cursor_when_view_supports_it() -> None:
    view = FakeCursorZoomView(scale=1.0)
    nav = NavigationController()
    nav.attach_view(view)

    nav.zoom_at_cursor(120, 30, 40)
    assert view.zoom_start is None
    assert view.zoom_end is None
    assert view.Scale() > 1.0


def test_zoom_ignores_wheel_delta_during_navigation_drag() -> None:
    view = FakeView(scale=1.0)
    nav = NavigationController()
    nav.attach_view(view)

    nav.begin_pan(10, 20)
    nav.zoom_at_cursor(120, 30, 40)

    assert view.Scale() == 1.0


def test_zoom_limits_steps_per_event_to_avoid_jumps() -> None:
    view = FakeView(scale=10.0)
    nav = NavigationController()
    nav.attach_view(view)

    nav.zoom_at_cursor(-12000)

    assert view.Scale() == pytest.approx(10.0 / (nav.zoom_speed**2.0))


def test_pan_uses_delta() -> None:
    view = FakeView()
    nav = NavigationController()
    nav.attach_view(view)
    nav.begin_pan(10, 20)
    nav.pan_to(15, 25)
    assert view.last_pan == (5, -5)


def test_pan_drag_up_moves_model_up() -> None:
    view = FakeView()
    nav = NavigationController()
    nav.attach_view(view)
    nav.begin_pan(10, 20)
    nav.pan_to(10, 15)
    assert view.last_pan == (0, 5)


def test_home_capture_and_restore() -> None:
    view = FakeView()
    nav = NavigationController()
    nav.attach_view(view)
    nav.capture_home()
    view.SetEye(1.0, 2.0, 3.0)
    view.SetAt(4.0, 5.0, 6.0)
    view.SetUp(0.0, 0.0, 1.0)
    view.SetScale(5.0)

    nav.go_home()
    assert view.Eye() == (0.0, 0.0, 10.0)
    assert view.At() == (0.0, 0.0, 0.0)
    assert view.Up() == (0.0, 1.0, 0.0)
    assert view.Scale() == 1.0


def test_view_workplane_sets_projection_and_up_vector() -> None:
    pytest.importorskip("OCP")

    from cad_app.workplane import Workplane

    view = FakeView()
    nav = NavigationController()
    nav.attach_view(view)

    nav.view_workplane(Workplane.world_xy())

    assert view.proj == (0.0, 0.0, 1.0)
    assert view.Up() == (0.0, 1.0, 0.0)
    assert view.z_fit_calls == 1
    assert view.redraw_calls == 1


def test_view_axis_sets_projection_and_stable_up_vector() -> None:
    view = FakeView()
    nav = NavigationController()
    nav.attach_view(view)

    nav.view_axis("x")

    assert view.proj == (1.0, 0.0, 0.0)
    assert view.Up() == (0.0, 0.0, 1.0)
    assert view.z_fit_calls == 1
    assert view.redraw_calls == 1
