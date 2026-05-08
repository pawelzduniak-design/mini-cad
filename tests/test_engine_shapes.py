from importlib.util import find_spec

import pytest


def test_make_box_requires_positive_dimensions() -> None:
    from cad_app.engine import make_box

    with pytest.raises(ValueError, match="positive"):
        make_box(0, 1, 1)


def test_make_wedge_requires_valid_dimensions() -> None:
    from cad_app.engine import make_wedge

    with pytest.raises(ValueError, match="positive"):
        make_wedge(1, -1, 1)

    with pytest.raises(ValueError, match="far_top_height"):
        make_wedge(1, 1, 1, far_top_height=2)


def test_circle_profile_requires_positive_radius() -> None:
    from cad_app.profiles import CircleProfile

    with pytest.raises(ValueError, match="positive"):
        CircleProfile(0)


def test_make_box_returns_ocp_shape_when_dependencies_exist() -> None:
    if find_spec("build123d") is None or find_spec("OCP") is None:
        pytest.skip("OCP/build123d are not installed in the active environment.")

    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopoDS import TopoDS_Shape

    from cad_app.engine import make_box

    shape = make_box(10, 20, 30)
    assert isinstance(shape, TopoDS_Shape)
    assert BRepCheck_Analyzer(shape).IsValid()


def test_make_box_stands_on_world_xy_grid() -> None:
    if find_spec("build123d") is None or find_spec("OCP") is None:
        pytest.skip("OCP/build123d are not installed in the active environment.")

    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    from cad_app.engine import make_box

    bounds = Bnd_Box()
    BRepBndLib.Add_s(make_box(10, 20, 30), bounds)
    _, _, z_min, _, _, z_max = bounds.Get()

    assert z_min == pytest.approx(0.0, abs=1e-6)
    assert z_max == pytest.approx(30.0, abs=1e-6)


def test_make_wedge_returns_valid_ocp_shape_when_dependencies_exist() -> None:
    if find_spec("build123d") is None or find_spec("OCP") is None:
        pytest.skip("OCP/build123d are not installed in the active environment.")

    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopoDS import TopoDS_Shape

    from cad_app.engine import make_wedge
    from cad_app.picker import Picker
    from cad_app.types import SelectionKind

    shape = make_wedge(10, 20, 30, far_top_height=10)
    assert isinstance(shape, TopoDS_Shape)
    assert BRepCheck_Analyzer(shape).IsValid()
    assert Picker.indexed_map(shape, SelectionKind.FACE).Extent() >= 5
