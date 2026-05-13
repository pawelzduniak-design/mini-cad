"""Build two linked torus bodies like chain links."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cad_app.commands import rotated_shape, translated_shape, validate_shape
from cad_app.io_step import export_step
from cad_app.main_window import create_main_window
from cad_app.scene import Scene
from cad_app.viewer import Viewer

OUT_DIR = Path("out")
CHAIN_STEP = OUT_DIR / "duck_chain_donuts.step"
CHAIN_SCREENSHOT = OUT_DIR / "duck_chain_donuts.png"


def _log(message: str) -> None:
    print(message)


def _pass(message: str) -> None:
    _log(f"[PASS] {message}")


def _make_torus(major_radius: float, minor_radius: float):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeTorus

    builder = BRepPrimAPI_MakeTorus(major_radius, minor_radius)
    shape = builder.Shape()
    validate_shape(shape)
    return shape


def _make_compound(shapes):
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for shape in shapes:
        builder.Add(compound, shape)
    validate_shape(compound)
    return compound


def _minimum_distance(first, second) -> float:
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    distance = BRepExtrema_DistShapeShape(first, second)
    distance.Perform()
    if not distance.IsDone():
        raise RuntimeError("Could not measure distance between chain links.")
    return float(distance.Value())


def _wait_for_initial_display(app: QApplication, viewer: Viewer, widget) -> None:
    for _ in range(80):
        app.processEvents()
        if viewer.is_initialized and widget._initial_scene_displayed:
            return
        QTest.qWait(50)
    raise RuntimeError("Viewer did not initialize.")


def _capture_window(main_window) -> None:
    image = (
        main_window.viewer_widget.screen()
        .grabWindow(int(main_window.window.winId()))
        .toImage()
        .convertToFormat(QImage.Format.Format_RGB32)
    )
    image.save(str(CHAIN_SCREENSHOT))


def _build_chain_links():
    _log("[DUCK] Start with the first donut flat on the XY plane.")
    major_radius = 42.0
    minor_radius = 7.0
    first_link = _make_torus(major_radius, minor_radius)
    _pass("First torus created")

    _log("[DUCK] The second donut must be perpendicular, not fused.")
    second_link = _make_torus(major_radius, minor_radius)
    second_link = rotated_shape(
        second_link,
        center=(0.0, 0.0, 0.0),
        axis=(0.0, 1.0, 0.0),
        angle_degrees=90.0,
    )
    second_link = translated_shape(second_link, 0.0, 32.0, 0.0)
    validate_shape(second_link)
    _pass("Second torus rotated and shifted through the first torus opening")

    clearance = _minimum_distance(first_link, second_link)
    if clearance < 0.5:
        raise RuntimeError(f"Chain links collide or touch too closely: {clearance:.3f}")
    _pass(f"Links remain separate with {clearance:.2f} mm clearance")

    return first_link, second_link


def main() -> int:
    print("=== DUCK CHAIN DONUTS WORKFLOW ===")
    OUT_DIR.mkdir(exist_ok=True)

    first_link, second_link = _build_chain_links()
    assembly = _make_compound((first_link, second_link))
    export_step(assembly, CHAIN_STEP)
    _pass(f"STEP exported: {CHAIN_STEP}")

    app = QApplication.instance() or QApplication([])
    scene = Scene()
    viewer = Viewer()
    main_window = create_main_window(viewer, scene)
    main_window.window.resize(1280, 820)
    main_window.window.show()
    widget = main_window.viewer_widget
    widget.setFocus()

    try:
        _wait_for_initial_display(app, viewer, widget)
        scene.add_shape(
            first_link,
            meta={"kind": "body", "source": "chain_donut_flat_link"},
        )
        scene.add_shape(
            second_link,
            meta={"kind": "body", "source": "chain_donut_vertical_link"},
        )
        viewer.display_scene(scene, fit=True)
        widget._refresh_hud()
        app.processEvents()
        QTest.qWait(300)
        _capture_window(main_window)
        _pass(f"Screenshot exported: {CHAIN_SCREENSHOT}")
        print("=== RESULT: PASS ===")
        return 0
    finally:
        main_window.window.close()
        viewer.close()


if __name__ == "__main__":
    raise SystemExit(main())
