"""Build a pot model through the intended sketch/extrude/boolean/revolve flow."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cad_app.commands import boolean_bodies, validate_shape
from cad_app.io_step import export_step
from cad_app.main_window import create_main_window
from cad_app.scene import Scene
from cad_app.sketch import (
    _circle_wire,
    extrude_profile,
    make_arc_polyline_profile,
    make_circle_profile_at,
)
from cad_app.sketch_features import revolve_profile
from cad_app.viewer import Viewer
from cad_app.workplane import Workplane

OUT_DIR = Path("out")
POT_STEP = OUT_DIR / "duck_pot.step"
POT_SCREENSHOT = OUT_DIR / "duck_pot.png"


def _log(message: str) -> None:
    print(message)


def _pass(message: str) -> None:
    _log(f"[PASS] {message}")


def _make_annulus_profile(
    workplane: Workplane,
    inner_radius: float,
    outer_radius: float,
):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace

    if inner_radius <= 0.0 or outer_radius <= inner_radius:
        raise ValueError("Annulus needs positive inner radius below outer radius.")

    outer_wire = _circle_wire(workplane, (0.0, 0.0), outer_radius)
    inner_wire = _circle_wire(workplane, (0.0, 0.0), inner_radius)
    inner_wire.Reverse()
    face_builder = BRepBuilderAPI_MakeFace(outer_wire, True)
    face_builder.Add(inner_wire)
    if not face_builder.IsDone():
        raise RuntimeError("Annulus profile could not be built.")
    profile = face_builder.Face()
    validate_shape(profile)
    return profile


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
    image.save(str(POT_SCREENSHOT))


def _build_pot_shapes():
    xy = Workplane.world_xy()
    xz = Workplane.world_xz()

    _log("[DUCK] Start from the ring: two circles, material between them.")
    wall_profile = _make_annulus_profile(xy, inner_radius=43.0, outer_radius=55.0)
    wall = extrude_profile(wall_profile, 80.0)
    validate_shape(wall)
    _pass("Annular pot wall extruded")

    _log("[DUCK] The bottom must actually close the hollow ring.")
    base_profile = make_circle_profile_at(xy, (0.0, 0.0), 55.0)
    base = extrude_profile(base_profile, 8.0)
    validate_shape(base)
    _pass("Circular base extruded to match the outer pot footprint")

    _log("[DUCK] Fuse the base with the annular wall before adding the lid.")
    pot_body = boolean_bodies(wall, base, "union")
    validate_shape(pot_body)
    _pass("Pot wall and base fused with boolean union")

    _log("[DUCK] Lid is a vertical arc profile revolved around the Z axis.")
    lid_profile = make_arc_polyline_profile(
        xz,
        arc_start=(0.0, 102.0),
        arc_end=(55.0, 82.0),
        arc_bend=(28.0, 98.0),
        line_points=[(0.0, 102.0), (0.0, 82.0), (55.0, 82.0)],
    )
    lid = revolve_profile(
        lid_profile,
        axis_point=(0.0, 0.0, 0.0),
        axis_direction=(0.0, 0.0, 1.0),
        angle_degrees=360.0,
    )
    validate_shape(lid)
    _pass("Arc lid revolved into a solid")

    return pot_body, lid


def main() -> int:
    print("=== DUCK POT WORKFLOW ===")
    OUT_DIR.mkdir(exist_ok=True)

    pot_body, lid = _build_pot_shapes()
    assembly = _make_compound((pot_body, lid))
    export_step(assembly, POT_STEP)
    _pass(f"STEP exported: {POT_STEP}")

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
            pot_body,
            meta={
                "kind": "body",
                "source": "duck_pot_wall_base_boolean_union",
            },
        )
        scene.add_shape(
            lid,
            meta={
                "kind": "body",
                "source": "duck_pot_arc_revolve_lid",
            },
        )
        viewer.display_scene(scene, fit=True)
        widget._refresh_hud()
        app.processEvents()
        QTest.qWait(300)
        _capture_window(main_window)
        _pass(f"Screenshot exported: {POT_SCREENSHOT}")
        print("=== RESULT: PASS ===")
        return 0
    finally:
        main_window.window.close()
        viewer.close()


if __name__ == "__main__":
    raise SystemExit(main())
