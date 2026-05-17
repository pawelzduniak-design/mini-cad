from __future__ import annotations


class _StrictIntView:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []

    def StartRotation(self, x: int, y: int) -> None:
        assert type(x) is int
        assert type(y) is int
        self.calls.append(("start", x, y))

    def Rotation(self, x: int, y: int) -> None:
        assert type(x) is int
        assert type(y) is int
        self.calls.append(("rotate", x, y))

    def Pan(self, dx: int, dy: int) -> None:
        assert type(dx) is int
        assert type(dy) is int
        self.calls.append(("pan", dx, dy))


def test_navigation_casts_qt_float_positions_before_native_view_calls() -> None:
    from cad_app.navigation import NavigationController

    view = _StrictIntView()
    navigation = NavigationController()
    navigation.attach_view(view)

    navigation.begin_orbit(472.6, 551.5)
    navigation.orbit_to(473.2, 552.4)
    navigation.end_orbit()
    navigation.begin_pan(10.4, 20.6)
    navigation.pan_to(17.7, 14.2)

    assert view.calls == [
        ("start", 473, 552),
        ("rotate", 473, 552),
        ("pan", 8, 7),
    ]
