"""End-to-end "beginner builds an open box (jewelry case)" workflow.

A classic CAD warm-up: outer rectangular box, then a smaller rectangle
sketched on the top face and Cut Extruded downwards to leave a hollow
cavity with a solid floor. The flow exercises:

- sketch + Extrude for the outer body
- sketch on a body's top face (hosted profile, feature host wiring)
- negative-distance Extrude on a hosted profile (Cut into host)
- post-cut geometry stays a single valid solid

Every step prints `[PASS]` / `[FAIL] stepN: ...` so a regression points
to the exact UI action that broke. Output goes under out/build_box/.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cad_app.commands import top_planar_face_index, validate_shape
from cad_app.io_step import export_step
from cad_app.main_window import create_main_window
from cad_app.scene import Scene
from cad_app.sketch import make_center_rectangle_profile
from cad_app.types import SelectionKind, SelectionRef
from cad_app.viewer import Viewer

OUT_DIR = Path("out") / "build_box"
STEP_PATH = OUT_DIR / "open_box.step"
SCREENSHOT_ISO_PATH = OUT_DIR / "open_box_iso.png"
SCREENSHOT_TOP_PATH = OUT_DIR / "open_box_top.png"

OUTER_WIDTH = 100.0
OUTER_DEPTH = 60.0
OUTER_HEIGHT = 40.0
INNER_WIDTH = 80.0
INNER_DEPTH = 40.0
CUT_DEPTH = 35.0  # leaves 5 mm bottom floor
WALL_THICKNESS = (OUTER_WIDTH - INNER_WIDTH) / 2.0  # 10 mm walls
LID_THICKNESS = 5.0
LID_OPEN_ANGLE_DEG = -70.0  # negative = rotate backwards around hinge → opens up


class _Log:
    def __init__(self) -> None:
        self.failed = False
        self.current_step: str = "<init>"

    def step(self, step_id: str, headline: str) -> None:
        self.current_step = step_id
        sys.stdout.write(f"\n--- {step_id}: {headline} ---\n")

    def info(self, message: str) -> None:
        sys.stdout.write(f"[INFO] {message}\n")

    def passed(self, message: str) -> None:
        sys.stdout.write(f"[PASS] {message}\n")

    def fail(self, message: str) -> None:
        self.failed = True
        sys.stdout.write(f"[FAIL] {self.current_step}: {message}\n")

    def require(self, condition: bool, message: str) -> None:
        if condition:
            self.passed(message)
        else:
            self.fail(message)


def _wait_for_initial_display(app: QApplication, viewer: Viewer, widget: Any) -> None:
    for _ in range(80):
        app.processEvents()
        if viewer.is_initialized and widget._initial_scene_displayed:
            return
        QTest.qWait(50)
    raise RuntimeError("Viewer did not initialize and display the initial scene")


def _settle(app: QApplication, *, ms: int = 80) -> None:
    app.processEvents()
    QTest.qWait(ms)
    app.processEvents()


def _body_item_ids(scene: Scene) -> list[str]:
    return [item.item_id for item in scene if item.meta.get("kind") == "body"]


def _bbox(shape: Any) -> dict[str, float]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return {
        "xmin": xmin,
        "ymin": ymin,
        "zmin": zmin,
        "xmax": xmax,
        "ymax": ymax,
        "zmax": zmax,
        "width": xmax - xmin,
        "depth": ymax - ymin,
        "height": zmax - zmin,
    }


def _volume(shape: Any) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def _face_count(shape: Any) -> int:
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    face_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, face_map)
    return face_map.Extent()


def _capture(window: Any, widget: Any, path: Path) -> None:
    image = (
        widget.screen()
        .grabWindow(int(window.winId()))
        .toImage()
        .convertToFormat(QImage.Format.Format_RGB32)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(path))


def _extrude_selection(
    app: QApplication, widget: Any, distance: float, *, log: _Log
) -> None:
    action = widget._actions.get("extrude")
    if action is None or not action.isEnabled():
        log.fail("Extrude action is not enabled for the current selection")
        return
    action.trigger()
    _settle(app)
    if widget._move_session is None:
        log.fail("Extrude tool did not start a move session")
        return
    widget._move_session.distance = float(distance)
    widget._update_move_preview()
    widget._tool_done()
    _settle(app, ms=160)


def _add_hosted_rectangle(widget: Any, width: float, depth: float) -> str:
    profile = make_center_rectangle_profile(
        widget._active_workplane, (0.0, 0.0), (width / 2.0, depth / 2.0)
    )
    meta = widget._sketch_profile_meta(
        profile="center_rectangle",
        width=width,
        height=depth,
        center_u=0.0,
        center_v=0.0,
        workplane=widget._active_workplane_label,
    )
    return widget._add_sketch_profile(profile, meta)


def _start_sketch_on_top_face(
    app: QApplication,
    widget: Any,
    scene: Scene,
    body_id: str,
    main_window: Any,
    *,
    log: _Log,
) -> int | None:
    shape = scene.get(body_id).shape
    try:
        face_index = top_planar_face_index(shape)
    except Exception as exc:  # noqa: BLE001
        log.fail(f"Could not find top face: {exc}")
        return None
    widget._selection_kind = SelectionKind.FACE
    widget._viewer.set_selection_kind(SelectionKind.FACE)
    scene.set_selection(SelectionRef(body_id, SelectionKind.FACE, face_index))
    widget._set_active_category("select")
    _settle(app)
    main_window.actions["category_sketch"].trigger()
    _settle(app, ms=160)
    if widget._sketch_session is None:
        log.fail("Sketch session did not start from selected face")
        return None
    if widget._active_workplane_host != (body_id, face_index):
        log.fail(
            "Sketch did not adopt the body face as feature host "
            f"(expected ({body_id}, {face_index}), "
            f"got {widget._active_workplane_host})"
        )
        return None
    return face_index


def _run(log: _Log) -> None:
    app = QApplication.instance() or QApplication([])
    scene = Scene()
    viewer = Viewer()
    main_window = create_main_window(viewer, scene)
    window = main_window.window
    widget = main_window.viewer_widget
    window.resize(1280, 820)
    window.show()
    widget.setFocus()

    try:
        _wait_for_initial_display(app, viewer, widget)
        _settle(app, ms=160)

        # -----------------------------------------------------------------
        log.step("step1", "App opens in Sketch mode on the bottom plane")
        state = widget.get_ui_state()
        log.require(state.work_mode == "sketch", "Work mode is sketch")
        log.require(
            widget._active_workplane_host is None,
            "Bottom-plane sketch (no feature host yet)",
        )

        # -----------------------------------------------------------------
        log.step("step2", f"Draw outer rectangle {OUTER_WIDTH:.0f} x {OUTER_DEPTH:.0f}")
        outer_profile_id = _add_hosted_rectangle(widget, OUTER_WIDTH, OUTER_DEPTH)
        log.require(
            outer_profile_id in scene, "Outer rectangle profile added to the scene"
        )
        scene.set_selection(SelectionRef(outer_profile_id, SelectionKind.FACE, 1))
        widget._set_active_category("select")
        _settle(app)
        log.require(
            widget._actions["extrude"].isEnabled(),
            "Extrude action enabled for the outer profile",
        )

        # -----------------------------------------------------------------
        log.step("step3", f"Extrude the outer box up by {OUTER_HEIGHT:.0f} mm")
        _extrude_selection(app, widget, distance=OUTER_HEIGHT, log=log)
        bodies = _body_item_ids(scene)
        log.require(len(bodies) == 1, f"Outer box body created ({len(bodies)})")
        if not bodies:
            return
        box_id = bodies[0]
        validate_shape(scene.get(box_id).shape)
        bbox = _bbox(scene.get(box_id).shape)
        log.info(
            f"Outer bbox: {bbox['width']:.1f} x {bbox['depth']:.1f} x "
            f"{bbox['height']:.1f}"
        )
        log.require(
            abs(bbox["height"] - OUTER_HEIGHT) < 0.5,
            f"Outer height is {OUTER_HEIGHT:.0f} mm ({bbox['height']:.2f})",
        )
        volume_solid = _volume(scene.get(box_id).shape)
        expected_solid = OUTER_WIDTH * OUTER_DEPTH * OUTER_HEIGHT
        log.require(
            abs(volume_solid - expected_solid) < 1.0,
            f"Outer volume {volume_solid:.0f} ~= "
            f"{OUTER_WIDTH:.0f}x{OUTER_DEPTH:.0f}x{OUTER_HEIGHT:.0f}={expected_solid:.0f}",
        )

        # -----------------------------------------------------------------
        log.step(
            "step4",
            f"Sketch on top face for cavity {INNER_WIDTH:.0f}x{INNER_DEPTH:.0f}",
        )
        face_index = _start_sketch_on_top_face(
            app, widget, scene, box_id, main_window, log=log
        )
        if face_index is None:
            return
        log.info(f"Top face index: {face_index}")
        inner_profile_id = _add_hosted_rectangle(widget, INNER_WIDTH, INNER_DEPTH)
        log.require(
            inner_profile_id in scene, "Inner rectangle profile added (hosted on top)"
        )
        scene.set_selection(SelectionRef(inner_profile_id, SelectionKind.FACE, 1))
        widget._set_active_category("select")
        _settle(app)
        log.require(
            widget._actions["extrude"].isEnabled(),
            "Extrude enabled on the inner hosted profile",
        )

        # -----------------------------------------------------------------
        log.step("step5", f"Cut the cavity down by {CUT_DEPTH:.0f} mm")
        # Negative distance triggers BRepAlgoAPI_Cut in apply_profile_feature
        volume_before = _volume(scene.get(box_id).shape)
        faces_before = _face_count(scene.get(box_id).shape)
        _extrude_selection(app, widget, distance=-CUT_DEPTH, log=log)
        box_id = _body_item_ids(scene)[-1]
        validate_shape(scene.get(box_id).shape)
        bbox = _bbox(scene.get(box_id).shape)
        log.info(
            f"After cut bbox: {bbox['width']:.1f} x {bbox['depth']:.1f} x "
            f"{bbox['height']:.1f}"
        )
        log.require(
            abs(bbox["height"] - OUTER_HEIGHT) < 0.5,
            "Cut did not change outer height (cavity stays inside the body)",
        )
        log.require(
            abs(bbox["width"] - OUTER_WIDTH) < 0.5
            and abs(bbox["depth"] - OUTER_DEPTH) < 0.5,
            "Cut did not change outer footprint",
        )

        volume_after = _volume(scene.get(box_id).shape)
        expected_removed = INNER_WIDTH * INNER_DEPTH * CUT_DEPTH
        actual_removed = volume_before - volume_after
        log.info(
            f"Volume {volume_before:.0f} -> {volume_after:.0f} mm^3 "
            f"(removed {actual_removed:.0f}; expected {expected_removed:.0f})"
        )
        log.require(
            abs(actual_removed - expected_removed) < 5.0,
            f"Cut removed exactly the cavity volume "
            f"({actual_removed:.0f} ~= {expected_removed:.0f})",
        )

        faces_after = _face_count(scene.get(box_id).shape)
        # A cut into a face creates 4 new side faces + 1 new bottom face;
        # the original top face is split into a frame ring.
        log.info(f"Faces {faces_before} -> {faces_after}")
        log.require(
            faces_after >= faces_before + 4,
            f"Cut added enough new faces ({faces_after - faces_before})",
        )

        # -----------------------------------------------------------------
        log.step("step6", "Verify the cavity bottom is at the expected Z")
        # Outer box top = OUTER_HEIGHT; cavity depth = CUT_DEPTH; so the
        # cavity floor should sit at Z = OUTER_HEIGHT - CUT_DEPTH.
        cavity_floor_z = OUTER_HEIGHT - CUT_DEPTH
        from cad_app.command_topology import _shape_vertex_points

        vertices = _shape_vertex_points(scene.get(box_id).shape)
        z_values = sorted({round(z, 3) for _x, _y, z in vertices})
        log.info(f"Distinct Z values in body: {z_values}")
        log.require(
            any(abs(z - cavity_floor_z) < 0.01 for z in z_values),
            f"Cavity floor exists at Z={cavity_floor_z:.1f}",
        )
        log.require(
            any(abs(z - OUTER_HEIGHT) < 0.01 for z in z_values),
            f"Outer top wall at Z={OUTER_HEIGHT:.1f}",
        )

        # -----------------------------------------------------------------
        log.step(
            "step7a",
            f"Sketch a separate lid {OUTER_WIDTH:.0f}x{OUTER_DEPTH:.0f}x"
            f"{LID_THICKNESS:.0f} as a new body",
        )
        # Start a fresh sketch on the bottom plane, off to the side, so the
        # new lid is not interpreted as a feature of the box body.
        scene.set_selection(None)
        widget._set_active_category("select")
        _settle(app)
        main_window.actions["category_sketch"].trigger()
        _settle(app, ms=150)
        log.require(
            widget._sketch_session is not None
            and widget._active_workplane_host is None,
            "Independent sketch session started for the lid",
        )
        # Lay the lid profile off-axis so it does not overlap the box.
        # make_center_rectangle_profile takes ABSOLUTE corner coords, so
        # the corner has to include the centre offset.
        lid_profile_x = 200.0
        lid_profile = make_center_rectangle_profile(
            widget._active_workplane,
            (lid_profile_x, 0.0),
            (lid_profile_x + OUTER_WIDTH / 2.0, OUTER_DEPTH / 2.0),
        )
        lid_profile_id = widget._add_sketch_profile(
            lid_profile,
            widget._sketch_profile_meta(
                profile="center_rectangle",
                width=OUTER_WIDTH,
                height=OUTER_DEPTH,
                center_u=lid_profile_x,
                center_v=0.0,
                workplane=widget._active_workplane_label,
            ),
        )
        log.require(lid_profile_id in scene, "Lid profile added off-axis")

        scene.set_selection(SelectionRef(lid_profile_id, SelectionKind.FACE, 1))
        widget._set_active_category("select")
        _settle(app)
        log.require(
            widget._actions["sketch_new_body"].isEnabled(),
            "New Body action enabled for the independent lid profile",
        )
        main_window.actions["sketch_new_body"].trigger()
        _settle(app)
        if widget._move_session is None:
            log.fail("sketch_new_body did not start a move session")
            return
        widget._move_session.distance = LID_THICKNESS
        widget._update_move_preview()
        widget._tool_done()
        _settle(app, ms=160)
        bodies = _body_item_ids(scene)
        log.require(len(bodies) >= 2, f"Box + lid bodies in scene ({len(bodies)})")
        lid_id = bodies[-1]
        validate_shape(scene.get(lid_id).shape)
        lid_bbox = _bbox(scene.get(lid_id).shape)
        log.info(
            f"Lid bbox: {lid_bbox['width']:.1f} x {lid_bbox['depth']:.1f} x "
            f"{lid_bbox['height']:.1f}"
        )

        # -----------------------------------------------------------------
        log.step("step7b", "Translate the lid onto the box top (closed position)")
        # Move lid so its bottom face matches the box top (Z=OUTER_HEIGHT)
        # and its centre lines up with the box (X=0, Y=0). The lid was
        # extruded from Z=0; we want its base at Z=OUTER_HEIGHT.
        from cad_app.commands import apply_move_object

        dx = -lid_profile_x  # cancel the off-axis offset
        dy = 0.0
        dz = OUTER_HEIGHT  # lid sits on top of the box
        apply_move_object(scene, lid_id, dx, dy, dz)
        viewer.display_scene(scene, fit=False)
        _settle(app, ms=120)
        lid_bbox = _bbox(scene.get(lid_id).shape)
        log.info(
            f"Lid bbox after translate: X[{lid_bbox['xmin']:.1f},"
            f"{lid_bbox['xmax']:.1f}] Y[{lid_bbox['ymin']:.1f},"
            f"{lid_bbox['ymax']:.1f}] Z[{lid_bbox['zmin']:.1f},"
            f"{lid_bbox['zmax']:.1f}]"
        )
        log.require(
            abs(lid_bbox["zmin"] - OUTER_HEIGHT) < 0.5,
            f"Lid bottom sits on box top at Z={OUTER_HEIGHT:.0f}",
        )

        # -----------------------------------------------------------------
        log.step(
            "step7c",
            f"Rotate the lid open by {abs(LID_OPEN_ANGLE_DEG):.0f} deg around hinge",
        )
        # Hinge axis runs along world X at Y=+OUTER_DEPTH/2 (back edge of
        # the box top) and Z=OUTER_HEIGHT. Rotating around this axis with
        # a negative angle swings the lid up and back, exposing the cavity.
        hinge_center = (0.0, OUTER_DEPTH / 2.0, OUTER_HEIGHT)
        hinge_axis = (1.0, 0.0, 0.0)
        from cad_app.commands import apply_rotate_object

        apply_rotate_object(scene, lid_id, hinge_center, hinge_axis, LID_OPEN_ANGLE_DEG)
        viewer.display_scene(scene, fit=True)
        _settle(app, ms=160)
        lid_bbox = _bbox(scene.get(lid_id).shape)
        log.info(
            f"Lid bbox after rotate: X[{lid_bbox['xmin']:.1f},"
            f"{lid_bbox['xmax']:.1f}] Y[{lid_bbox['ymin']:.1f},"
            f"{lid_bbox['ymax']:.1f}] Z[{lid_bbox['zmin']:.1f},"
            f"{lid_bbox['zmax']:.1f}]"
        )
        # An open lid should reach above the box top (free edge swings up)
        log.require(
            lid_bbox["zmax"] > OUTER_HEIGHT + 5.0,
            f"Lid free edge swung above the box top "
            f"(Zmax={lid_bbox['zmax']:.1f} > {OUTER_HEIGHT + 5.0:.1f})",
        )
        # Lid bottom stays anchored at the hinge Z (box top edge).
        log.require(
            abs(lid_bbox["zmin"] - OUTER_HEIGHT) < 0.5,
            f"Hinge corner stays anchored at Z={OUTER_HEIGHT:.0f} "
            f"(Zmin={lid_bbox['zmin']:.1f})",
        )
        # Free edge moved away from the front (negative Y) toward the back.
        log.require(
            lid_bbox["ymin"] > -OUTER_DEPTH / 2.0 + 5.0,
            f"Lid free edge moved away from the front "
            f"(Ymin={lid_bbox['ymin']:.1f} > {-OUTER_DEPTH / 2.0 + 5.0:.1f})",
        )

        # -----------------------------------------------------------------
        log.step("step7", "Export STEP + screenshots (iso + top-down)")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        # Compound the box and the lid so the STEP file contains the whole
        # assembly, not just the box.
        from OCP.BRep import BRep_Builder
        from OCP.TopoDS import TopoDS_Compound

        builder = BRep_Builder()
        compound = TopoDS_Compound()
        builder.MakeCompound(compound)
        for body_id in _body_item_ids(scene):
            builder.Add(compound, scene.get(body_id).shape)
        export_step(compound, str(STEP_PATH))
        log.require(STEP_PATH.exists(), f"STEP exported to {STEP_PATH}")

        widget._fit_all()
        viewer.refresh_native_window()
        _settle(app, ms=250)
        _capture(window, widget, SCREENSHOT_ISO_PATH)
        log.require(
            SCREENSHOT_ISO_PATH.exists(), f"Iso screenshot: {SCREENSHOT_ISO_PATH}"
        )

        # Look straight down to see the inner cavity opening
        widget._navigation.view_axis("z", positive=True)
        widget._navigation.fit_all()
        viewer.refresh_native_window()
        _settle(app, ms=250)
        _capture(window, widget, SCREENSHOT_TOP_PATH)
        log.require(
            SCREENSHOT_TOP_PATH.exists(), f"Top screenshot: {SCREENSHOT_TOP_PATH}"
        )
    finally:
        window.close()
        viewer.close()
        app.processEvents()


def main() -> int:
    log = _Log()
    sys.stdout.write("=== BUILD OPEN BOX WORKFLOW ===\n")
    sys.stdout.write(
        f"Target: {OUTER_WIDTH:.0f} x {OUTER_DEPTH:.0f} x {OUTER_HEIGHT:.0f} mm "
        f"outer; {INNER_WIDTH:.0f} x {INNER_DEPTH:.0f} x {CUT_DEPTH:.0f} mm "
        f"cavity; {WALL_THICKNESS:.0f} mm walls; "
        f"{OUTER_HEIGHT - CUT_DEPTH:.0f} mm floor\n"
    )
    try:
        _run(log)
    except Exception as exc:  # noqa: BLE001
        log.fail(f"Unhandled exception: {type(exc).__name__}: {exc}")
        import traceback

        traceback.print_exc()
    if log.failed:
        sys.stdout.write("\n=== RESULT: FAIL ===\n")
        return 1
    sys.stdout.write("\n=== RESULT: PASS ===\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
