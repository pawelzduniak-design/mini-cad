"""Human-first startup smoke check for the CAD UI."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cad_app.main_window import create_main_window
from cad_app.scene import Scene
from cad_app.viewer import Viewer


def _log(level: str, message: str) -> None:
    print(f"[{level}] {message}")


def _pass(message: str) -> None:
    _log("PASS", message)


def _fail(message: str) -> None:
    _log("FAIL", message)
    raise AssertionError(message)


def _wait_for_initial_display(app, viewer, widget) -> None:
    for _ in range(80):
        app.processEvents()
        if viewer.is_initialized and widget._initial_scene_displayed:
            return
        QTest.qWait(50)
    _fail("Viewer did not initialize visibly")


def _command_action_names(widget) -> list[str]:
    return [
        action.objectName()
        for action in widget._command_toolbar.actions()
        if action.objectName() and not action.objectName().startswith("context_label_")
    ]


def _sample_visual_energy(image: QImage) -> tuple[int, int]:
    width, height = image.width(), image.height()
    samples = []
    for y in range(height // 3, 2 * height // 3, 12):
        for x in range(width // 3, 2 * width // 3, 12):
            color = image.pixelColor(x, y)
            samples.append((color.red(), color.green(), color.blue()))
    unique_samples = len(set(samples))
    very_dark = sum(
        1 for red, green, blue in samples if red < 15 and green < 15 and blue < 15
    )
    return unique_samples, very_dark


def main() -> int:
    print("=== MAMA OPENS CAD CHECK ===")
    app = QApplication.instance() or QApplication([])
    scene = Scene()
    viewer = Viewer()
    main_window = create_main_window(viewer, scene)
    widget = main_window.viewer_widget
    main_window.window.resize(1280, 820)
    main_window.window.show()
    widget.setFocus()

    try:
        _wait_for_initial_display(app, viewer, widget)
        QTest.qWait(200)
        app.processEvents()

        out = Path("out")
        out.mkdir(exist_ok=True)
        image = (
            widget.screen()
            .grabWindow(int(main_window.window.winId()))
            .toImage()
            .convertToFormat(QImage.Format.Format_RGB32)
        )
        screenshot = out / "mama_opens_cad_initial.png"
        image.save(str(screenshot))

        unique_samples, very_dark = _sample_visual_energy(image)
        if unique_samples < 4:
            _fail("Viewport looks visually flat or empty")
        _pass("Viewport has visible visual structure")
        if very_dark > 0:
            _fail("Viewport contains black-screen-like central samples")
        _pass("Viewport is not black")
        if len(viewer._grid_objects) == 0:
            _fail("Grid/reference objects are not visible")
        _pass("Grid/reference objects are present")

        state = widget.get_ui_state()
        if "Start:" not in state.hint_text:
            _fail(f"Startup hint is not action-oriented: {state.hint_text!r}")
        _pass("Startup hint tells the user what to do first")

        if "Select" not in widget._hud_labels["mode"].text():
            _fail("Initial work mode is not visible as Select")
        _pass("Initial work mode is visible")
        if "object" not in widget._hud_labels["axis"].text():
            _fail("Initial selection mode is not visible as Object")
        _pass("Initial selection mode is visible")
        if set(_command_action_names(widget)) != {
            "select_object",
            "select_face",
            "select_edge",
            "select_vertex",
            "select_through",
        }:
            _fail("Select mode commands are not visible on startup")
        _pass("Select mode commands are visible on startup")

        main_window.actions["category_sketch"].trigger()
        app.processEvents()
        QTest.qWait(150)
        image = (
            widget.screen()
            .grabWindow(int(main_window.window.winId()))
            .toImage()
            .convertToFormat(QImage.Format.Format_RGB32)
        )
        unique_samples, very_dark = _sample_visual_energy(image)
        if unique_samples < 4 or very_dark > 0:
            _fail("Sketch mode introduced a black overlay")
        _pass("Sketch mode does not introduce black viewport boxes")

        print(f"[INFO] Screenshot: {screenshot}")
        print("=== RESULT: PASS ===")
        return 0
    finally:
        main_window.window.close()
        viewer.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError:
        print("=== RESULT: FAIL ===")
        raise SystemExit(1)
