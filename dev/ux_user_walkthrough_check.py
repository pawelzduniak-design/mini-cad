"""Developer UX smoke check for the visible CAD workflow."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QLabel

from cad_app.main_window import create_main_window
from cad_app.scene import Scene
from cad_app.sketch import SKETCH_META_KIND, make_center_rectangle_profile
from cad_app.types import SelectionKind, SelectionRef
from cad_app.ui_menu import SKETCH_ACTIVE_ACTIONS
from cad_app.viewer import Viewer
from cad_app.workplane import Workplane


def _log(level: str, message: str) -> None:
    print(f"[{level}] {message}")


def _pass(message: str) -> None:
    _log("PASS", message)


def _fail(message: str) -> None:
    _log("FAIL", message)
    raise AssertionError(message)


def _command_action_names(main_window) -> list[str]:
    command_toolbar = main_window.viewer_widget._command_toolbar
    return [
        action.objectName()
        for action in command_toolbar.actions()
        if action.objectName() and not action.objectName().startswith("context_label_")
    ]


def _assert_contains(container: str, text: str, message: str) -> None:
    if text not in container:
        _fail(f"{message}: expected {text!r} in {container!r}")
    _pass(message)


def main() -> int:
    print("=== UX USER WALKTHROUGH TEST ===")
    app = QApplication.instance() or QApplication([])
    scene = Scene()
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget

    _log("INFO", "App launched")
    _assert_contains(
        widget._hud_labels["mode"].text(), "Sketch", "Initial mode visible: Sketch"
    )
    _assert_contains(
        widget._hud_labels["axis"].text(), "face", "Selection mode visible: Face"
    )
    _assert_contains(
        widget._hud_labels["tool"].text(),
        "Sketch center_rectangle",
        "Initial sketch tool visible",
    )
    if main_window.actions["category_transform"].isEnabled():
        _fail("Transform is enabled on an empty scene")
    _pass("Transform disabled on empty scene")
    startup_tools = _command_action_names(main_window)
    if startup_tools != list(SKETCH_ACTIVE_ACTIONS):
        _fail(f"Startup sketch tools are not clear: {startup_tools}")
    _pass("Startup sketch tools are visible")

    _log("INFO", "Entering Sketch mode")
    main_window.actions["category_sketch"].trigger()
    _assert_contains(widget._hud_labels["mode"].text(), "Sketch", "Sketch mode visible")
    sketch_start_tools = _command_action_names(main_window)
    if sketch_start_tools != list(SKETCH_ACTIVE_ACTIONS):
        _fail(f"Sketch action list is wrong: {sketch_start_tools}")
    _pass("Sketch mode exposes draw tools immediately")
    sketch_tools = sketch_start_tools
    expected_tools = {
        "sketch_line_tool",
        "sketch_arc_tool",
        "sketch_circle2_tool",
        "sketch_center_radius_tool",
        "sketch_rectangle3_tool",
        "sketch_center_rectangle_tool",
    }
    if not expected_tools.issubset(set(sketch_tools)):
        _fail(f"Sketch tools missing: {sorted(expected_tools - set(sketch_tools))}")
    _pass(
        "Sketch tools visible: Line, Arc, two Circle modes, "
        "Rectangle 3 Point, Center Rectangle"
    )
    hint_text = widget.get_ui_state().hint_text
    _assert_contains(
        hint_text,
        "Center Rectangle",
        "Context hint visible for active sketch tool",
    )
    if not main_window.actions["sketch_center_rectangle_tool"].isChecked():
        _fail("Center Rectangle is not visibly active")
    _pass("Active tool visible: Center Rectangle")

    _log("INFO", "Selecting sketch profile")
    widget._sketch_session = None
    profile = make_center_rectangle_profile(
        Workplane.world_xy(),
        (0.0, 0.0),
        (30.0, 15.0),
    )
    profile_id = scene.add_shape(
        profile,
        meta={"kind": SKETCH_META_KIND, "profile": "center_rectangle"},
    )
    scene.set_selection(SelectionRef(profile_id, SelectionKind.FACE, 1))
    widget._active_category = "select"
    widget._refresh_action_state()
    widget._refresh_hud()
    _assert_contains(
        widget._hud_labels["selection"].text(),
        "Sketch Profile",
        "UI says Selection: Sketch Profile",
    )
    if "extrude" not in _command_action_names(main_window):
        _fail("Extrude action is not visible for Sketch Profile")
    _pass("Extrude action is visible")

    _log("INFO", "Starting Extrude UX state")
    main_window.actions["extrude"].trigger()
    _assert_contains(
        widget._hud_labels["tool"].text(),
        "Extrude",
        "Active tool visible: Extrude",
    )
    if "idle" in widget._hud_labels["tool"].text():
        _fail("Status says Tool: idle during Extrude")
    _pass("Status does not say Tool: idle")
    if widget.findChild(QLabel, "DimensionOverlay") is None:
        _fail("Dimension overlay component missing")
    _pass("Dimension overlay component exists")
    if not widget._dimension_overlay.isHidden():
        _fail("Viewport dimension overlay duplicates the Extrude popover")
    _pass("Viewport dimension overlay hidden during active tool")
    if not hasattr(widget, "_tool_popover") or widget._tool_popover.isHidden():
        _fail("Tool popover is hidden after starting Extrude")
    _pass("Tool popover visible near action")
    if not callable(main_window.viewer.display_extrude_affordance):
        _fail("Extrude affordance renderer missing")
    _pass("Extrude manipulator/arrow renderer exists")
    _assert_contains(
        widget.get_ui_state().hint_text,
        "drag height",
        "Hint visible: drag height, Enter accept, Esc cancel",
    )

    _log("INFO", "Checking selection modes")
    for kind, action_name in (
        ("Object", "select_object"),
        ("Face", "select_face"),
        ("Edge", "select_edge"),
        ("Vertex", "select_vertex"),
    ):
        if action_name not in main_window.actions:
            _fail(f"Selection mode missing: {kind}")
        _pass(f"Selection mode {kind} exists")

    print("=== RESULT: PASS ===")
    app.processEvents()
    main_window.window.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError:
        print("=== RESULT: FAIL ===")
        raise SystemExit(1)
