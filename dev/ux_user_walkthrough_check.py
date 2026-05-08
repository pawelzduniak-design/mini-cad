"""Developer UX smoke check for the visible CAD workflow."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QLabel

from cad_app.main_window import create_main_window
from cad_app.scene import Scene
from cad_app.sketch import SKETCH_META_KIND, make_center_rectangle_profile
from cad_app.types import SelectionKind, SelectionRef
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
        widget._hud_labels["mode"].text(), "Select", "Initial mode visible: Select"
    )
    _assert_contains(
        widget._hud_labels["axis"].text(), "object", "Selection mode visible: Object"
    )
    _assert_contains(
        widget._hud_labels["tool"].text(), "idle", "No conflicting active tools"
    )
    if main_window.actions["category_transform"].isEnabled():
        _fail("Transform is enabled on an empty scene")
    _pass("Transform disabled on empty scene")

    _log("INFO", "Entering Sketch mode")
    main_window.actions["category_sketch"].trigger()
    _assert_contains(widget._hud_labels["mode"].text(), "Sketch", "Sketch mode visible")
    sketch_tools = _command_action_names(main_window)
    expected_tools = {
        "sketch_line_tool",
        "sketch_arc_tool",
        "sketch_circle_tool",
        "sketch_rectangle3_tool",
        "sketch_center_rectangle_tool",
    }
    if not expected_tools.issubset(set(sketch_tools)):
        _fail(f"Sketch tools missing: {sorted(expected_tools - set(sketch_tools))}")
    _pass(
        "Sketch tools visible: Line, Arc, Circle, Rectangle 3 Point, Center Rectangle"
    )
    hint = widget.findChild(QLabel, "ContextHintOverlay")
    if hint is None or hint.isHidden():
        _fail("Context hint is not visible after entering Sketch")
    _assert_contains(
        hint.text(), "Center Rectangle", "Context hint visible for active sketch tool"
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
    profile_id = scene.add_shape(profile, meta={"kind": SKETCH_META_KIND})
    scene.set_selection(SelectionRef(profile_id, SelectionKind.FACE, 1))
    widget._active_category = "modify"
    widget._refresh_hud()
    _assert_contains(
        widget._hud_labels["selection"].text(),
        "Sketch Profile",
        "UI says Selection: Sketch Profile",
    )
    if "sketch_extrude" not in _command_action_names(main_window):
        _fail("Extrude action is not visible for Sketch Profile")
    _pass("Extrude action is visible")

    _log("INFO", "Starting Extrude UX state")
    main_window.actions["sketch_extrude"].trigger()
    _assert_contains(
        widget._hud_labels["tool"].text(),
        "Sketch Extrude",
        "Active tool visible: Extrude",
    )
    if "idle" in widget._hud_labels["tool"].text():
        _fail("Status says Tool: idle during Extrude")
    _pass("Status does not say Tool: idle")
    if widget.findChild(QLabel, "DimensionOverlay") is None:
        _fail("Dimension overlay component missing")
    _pass("Dimension overlay component exists")
    if widget._dimension_overlay.isHidden():
        _fail("Dimension overlay is hidden after starting Extrude")
    _pass("Overlay visible near action")
    if not callable(main_window.viewer.display_extrude_affordance):
        _fail("Extrude affordance renderer missing")
    _pass("Extrude manipulator/arrow renderer exists")
    _assert_contains(
        hint.text(), "Drag arrow", "Hint visible: Drag arrow, Enter accept, Esc cancel"
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
