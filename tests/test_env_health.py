from importlib.util import find_spec

import pytest

from cad_app.env import Dependency, ensure_runtime_dependencies, missing_dependencies


def test_runtime_dependency_metadata_uses_import_and_install_names() -> None:
    missing = missing_dependencies((Dependency("module_that_does_not_exist", "pkg"),))
    assert missing == (Dependency("module_that_does_not_exist", "pkg"),)


def test_runtime_dependency_error_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cad_app.env.missing_dependencies",
        lambda: (Dependency("MissingModule", "missing-package"),),
    )

    with pytest.raises(RuntimeError, match="missing-package"):
        ensure_runtime_dependencies()


def test_ocp_and_build123d_available_when_installed() -> None:
    if find_spec("build123d") is None or find_spec("OCP") is None:
        pytest.skip("OCP/build123d are not installed in the active environment.")

    from build123d import Box
    from OCP.TopoDS import TopoDS_Shape

    box = Box(1, 2, 3)
    shape = box.wrapped
    assert isinstance(shape, TopoDS_Shape)
