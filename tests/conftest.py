from __future__ import annotations

import os
from importlib.util import find_spec

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "gui: real Qt/OCP window tests")
    config.addinivalue_line("markers", "visual: screenshot/perception tests")


def require_ocp() -> None:
    if find_spec("OCP") is None:
        pytest.skip("OCP is not installed in the active environment.")


def require_qt() -> None:
    from cad_app.platform_runtime import configure_platform_environment

    configure_platform_environment()
    if find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed in the active environment.")


def require_gui_enabled() -> None:
    require_ocp()
    require_qt()
    if os.environ.get("CAD_APP_GUI_TESTS") != "1":
        pytest.skip("Set CAD_APP_GUI_TESTS=1 to run real GUI tests.")


def require_visual_enabled() -> None:
    require_ocp()
    require_qt()
    if os.environ.get("CAD_APP_VISUAL_TESTS") != "1":
        pytest.skip("Set CAD_APP_VISUAL_TESTS=1 to run visual tests.")


@pytest.fixture
def qapp():
    require_qt()
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
