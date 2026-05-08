from importlib.util import find_spec

import pytest


def test_step_roundtrip_when_dependencies_exist(tmp_path) -> None:
    if find_spec("build123d") is None or find_spec("OCP") is None:
        pytest.skip("OCP/build123d are not installed in the active environment.")

    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopoDS import TopoDS_Shape

    from cad_app.engine import make_box
    from cad_app.io_step import export_step, import_step

    path = tmp_path / "box.step"
    export_step(make_box(10, 20, 30), path)

    imported_shape = import_step(path)
    assert path.exists()
    assert isinstance(imported_shape, TopoDS_Shape)
    assert BRepCheck_Analyzer(imported_shape).IsValid()


def test_import_step_rejects_missing_file(tmp_path) -> None:
    if find_spec("OCP") is None:
        pytest.skip("OCP is not installed in the active environment.")

    from cad_app.io_step import StepIOError, import_step

    with pytest.raises(StepIOError, match="STEP read failed"):
        import_step(tmp_path / "missing.step")
