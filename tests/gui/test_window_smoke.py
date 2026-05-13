from __future__ import annotations

import pytest

from tests.conftest import require_gui_enabled


@pytest.mark.gui
def test_real_window_initializes_and_exposes_viewport(qapp) -> None:
    require_gui_enabled()

    from PySide6.QtTest import QTest

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.viewer import Viewer

    scene = Scene()
    scene.add_shape(make_box(), meta={"kind": "body"})
    viewer = Viewer()
    main_window = create_main_window(viewer, scene)
    window = main_window.window
    widget = main_window.viewer_widget
    window.resize(960, 640)
    window.show()
    widget.setFocus()

    try:
        for _ in range(80):
            qapp.processEvents()
            if viewer.is_initialized and widget._initial_scene_displayed:
                break
            QTest.qWait(50)

        assert viewer.is_initialized
        assert widget._initial_scene_displayed
        assert widget.get_ui_state().work_mode == "select"
        assert window.centralWidget() is widget
        assert widget.objectName() == "viewport"
    finally:
        window.close()
        viewer.close()
        qapp.processEvents()
