"""End-to-end "beginner builds a small house" workflow.

This script drives the CAD UI the same way a first-time user would:
- it starts the app, expects to land in Sketch mode with Center Rectangle
  active;
- it draws a foundation profile and Extrudes it via the toolbar QAction
  (mimicking a click on Extrude, typing a height in the popover, pressing
  Done);
- it picks the top face, starts a hosted sketch on it, draws a smaller
  rectangle for the walls, and Extrudes again;
- it repeats once more for a roof block;
- it asserts the scene grew the way a user expects and exports both a
  STEP file and a screenshot under ``out/build_house/``.

Every step prints either ``[PASS]`` or ``[FAIL] step N: ...`` so when the
script halts we know exactly where the UX breaks. The goal is to surface
regressions in action enablement, sketch session wiring, feature-host
metadata, and Extrude tool commit — things the Qt-free contract suite
cannot catch.
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
from cad_app.sketch import make_center_rectangle_profile, make_circle_profile_at
from cad_app.types import SelectionKind, SelectionRef
from cad_app.viewer import Viewer

EXPECTED_HOUSE_HEIGHT = 120.0  # foundation 30 + walls 60 + roof 30
HEIGHT_TOLERANCE = 0.5

OUT_DIR = Path("out") / "build_house"
STEP_PATH = OUT_DIR / "house.step"
SCREENSHOT_PATH = OUT_DIR / "house.png"
SCREENSHOT_FRONT_PATH = OUT_DIR / "house_front.png"
SCREENSHOT_RIGHT_PATH = OUT_DIR / "house_right.png"


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


def _count_faces(shape: Any) -> int:
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    face_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, face_map)
    return face_map.Extent()


def _solid_volume(shape: Any) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def _bounding_box(shape: Any) -> dict[str, float]:
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
    app: QApplication,
    widget: Any,
    distance: float,
    *,
    log: _Log,
) -> None:
    """Drive the Extrude tool the way the user does.

    The toolbar Extrude action opens the tool; we then set the popover's
    primary value programmatically (the user would type it in the spin
    box) and press Done (the user clicks the Done button).
    """
    actions = widget._actions
    extrude_action = actions.get("extrude")
    if extrude_action is None or not extrude_action.isEnabled():
        log.fail("Extrude action is not enabled for the current selection")
        return
    extrude_action.trigger()
    _settle(app)
    if widget._move_session is None:
        log.fail("Extrude tool did not start a move session")
        return
    widget._move_session.distance = float(distance)
    widget._update_move_preview()
    widget._tool_done()
    _settle(app, ms=160)


def _start_sketch_on_top_face(
    app: QApplication,
    widget: Any,
    scene: Scene,
    body_id: str,
    *,
    log: _Log,
) -> int | None:
    """Pick the top planar face of a body and activate Sketch on it."""
    shape = scene.get(body_id).shape
    try:
        face_index = top_planar_face_index(shape)
    except Exception as exc:  # noqa: BLE001 - diagnostic in workflow script.
        log.fail(f"Could not find top face: {exc}")
        return None
    widget._selection_kind = SelectionKind.FACE
    widget._viewer.set_selection_kind(SelectionKind.FACE)
    scene.set_selection(SelectionRef(body_id, SelectionKind.FACE, face_index))
    widget._set_active_category("select")
    _settle(app)

    sketch_action = widget._actions.get("category_sketch")
    if sketch_action is None or not sketch_action.isEnabled():
        log.fail("Sketch category action is not enabled with a selected face")
        return None
    sketch_action.trigger()
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


def _count_sketch_profiles(scene: Scene) -> int:
    return sum(1 for it in scene if it.meta.get("kind") == "sketch_profile")


def _front_face_of(scene: Scene, body_id: str) -> int | None:
    """Return the face index whose outward normal points along -Y (the
    'front' wall of the house when looking from the default isometric
    camera)."""
    from cad_app.commands import face_normal_vector

    shape = scene.get(body_id).shape
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape

    face_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, face_map)
    best: int | None = None
    best_score: float | None = None
    for idx in range(1, face_map.Extent() + 1):
        try:
            nx, ny, nz = face_normal_vector(shape, idx)
        except Exception:  # noqa: BLE001
            continue
        if ny < -0.95 and abs(nx) < 0.2 and abs(nz) < 0.2:
            bounds = Bnd_Box()
            BRepBndLib.AddOptimal_s(TopoDS.Face_s(face_map.FindKey(idx)), bounds)
            _x_min, _y_min, z_min, _x_max, _y_max, z_max = bounds.Get()
            center_z = (z_min + z_max) * 0.5
            height = z_max - z_min
            wall_height_penalty = 0.0 if height >= 45.0 else 100.0
            score = abs(center_z - 60.0) + wall_height_penalty
            if best_score is None or score < best_score:
                best = idx
                best_score = score
    return best


def _add_hosted_rectangle(
    widget: Any,
    width: float,
    depth: float,
    *,
    log: _Log,
) -> str | None:
    """Insert a center rectangle profile through the same code path the
    Sketch tool uses on drag-commit."""
    try:
        profile = make_center_rectangle_profile(
            widget._active_workplane,
            (0.0, 0.0),
            (width / 2.0, depth / 2.0),
        )
    except Exception as exc:  # noqa: BLE001 - diagnostic in workflow script.
        log.fail(f"Center rectangle profile build failed: {exc}")
        return None
    meta = widget._sketch_profile_meta(
        profile="center_rectangle",
        width=width,
        height=depth,
        center_u=0.0,
        center_v=0.0,
        workplane=widget._active_workplane_label,
    )
    return widget._add_sketch_profile(profile, meta)


def _finish_sketch(app: QApplication, widget: Any) -> None:
    finish = widget._actions.get("finish_sketch")
    if finish is not None and finish.isEnabled():
        finish.trigger()
        _settle(app, ms=120)


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
        log.step("step1", "App opens in Sketch mode with Center Rectangle")
        state = widget.get_ui_state()
        log.require(
            state.work_mode == "sketch",
            f"Work mode is sketch ({state.work_mode})",
        )
        log.require(
            widget._sketch_session is not None,
            "Sketch session active on startup",
        )
        log.require(
            "center_rectangle" in (widget._pending_sketch_tool or ""),
            f"Default sketch tool is Center Rectangle ({widget._pending_sketch_tool})",
        )

        # -----------------------------------------------------------------
        log.step("step2", "Draw foundation rectangle 200 x 100 on bottom plane")
        foundation_profile_id = _add_hosted_rectangle(
            widget, width=200.0, depth=100.0, log=log
        )
        if foundation_profile_id is None:
            return
        log.passed("Foundation profile added")
        _finish_sketch(app, widget)
        scene.set_selection(SelectionRef(foundation_profile_id, SelectionKind.FACE, 1))
        widget._set_active_category("select")
        _settle(app)
        log.require(
            widget._actions["extrude"].isEnabled(),
            "Extrude action is enabled for the foundation profile",
        )

        # -----------------------------------------------------------------
        log.step("step3", "Extrude foundation to 30 mm")
        _extrude_selection(app, widget, distance=30.0, log=log)
        bodies = _body_item_ids(scene)
        log.require(len(bodies) == 1, f"Foundation body exists ({len(bodies)})")
        if not bodies:
            return
        foundation_id = bodies[0]
        validate_shape(scene.get(foundation_id).shape)
        log.passed("Foundation body is a valid solid")
        bbox = _bounding_box(scene.get(foundation_id).shape)
        log.info(
            "Foundation bbox: "
            f"{bbox['width']:.1f} x {bbox['depth']:.1f} x {bbox['height']:.1f}"
        )
        log.require(
            abs(bbox["height"] - 30.0) < HEIGHT_TOLERANCE,
            f"Foundation height is 30 mm ({bbox['height']:.2f})",
        )

        # -----------------------------------------------------------------
        log.step("step4", "Start a Sketch on the top face for walls")
        face_index = _start_sketch_on_top_face(
            app, widget, scene, foundation_id, log=log
        )
        if face_index is None:
            return
        log.passed(f"Sketch hosted on foundation top face #{face_index}")

        # -----------------------------------------------------------------
        log.step("step5", "Draw walls rectangle 160 x 60 on top face")
        walls_profile_id = _add_hosted_rectangle(
            widget, width=160.0, depth=60.0, log=log
        )
        if walls_profile_id is None:
            return
        _finish_sketch(app, widget)
        scene.set_selection(SelectionRef(walls_profile_id, SelectionKind.FACE, 1))
        widget._set_active_category("select")
        _settle(app)
        log.require(
            widget._actions["extrude"].isEnabled(),
            "Extrude is enabled for the hosted walls profile",
        )

        # -----------------------------------------------------------------
        log.step("step6", "Extrude walls up by 60 mm")
        _extrude_selection(app, widget, distance=60.0, log=log)
        bodies = _body_item_ids(scene)
        log.info(f"Body count after walls extrude: {len(bodies)}")
        if not bodies:
            log.fail("No bodies remain after walls extrude")
            return
        bbox = _bounding_box(scene.get(bodies[-1]).shape)
        log.info(
            "After walls bbox: "
            f"{bbox['width']:.1f} x {bbox['depth']:.1f} x {bbox['height']:.1f}"
        )
        log.require(
            abs(bbox["height"] - 90.0) < HEIGHT_TOLERANCE,
            f"House height after walls is 90 mm ({bbox['height']:.2f})",
        )

        # -----------------------------------------------------------------
        log.step("step7", "Sketch and extrude roof on top of the walls")
        walls_body_id = bodies[-1]
        face_index = _start_sketch_on_top_face(
            app, widget, scene, walls_body_id, log=log
        )
        if face_index is None:
            return
        roof_profile_id = _add_hosted_rectangle(
            widget, width=180.0, depth=80.0, log=log
        )
        if roof_profile_id is None:
            return
        _finish_sketch(app, widget)
        scene.set_selection(SelectionRef(roof_profile_id, SelectionKind.FACE, 1))
        widget._set_active_category("select")
        _settle(app)
        _extrude_selection(app, widget, distance=30.0, log=log)
        bodies = _body_item_ids(scene)
        log.info(f"Final body count: {len(bodies)}")
        for body_id in bodies:
            validate_shape(scene.get(body_id).shape)
        log.passed("All resulting bodies are valid solids")
        bbox = _bounding_box(scene.get(bodies[-1]).shape)
        log.info(
            "Final bbox: "
            f"{bbox['width']:.1f} x {bbox['depth']:.1f} x {bbox['height']:.1f}"
        )
        log.require(
            abs(bbox["height"] - EXPECTED_HOUSE_HEIGHT) < HEIGHT_TOLERANCE,
            f"House total height is 120 mm ({bbox['height']:.2f})",
        )

        # -----------------------------------------------------------------
        log.step(
            "step9",
            "Sketch lifecycle: create -> finish -> delete -> recreate -> Edit",
        )
        house_id = bodies[-1]
        scene.set_selection(None)
        widget._set_active_category("select")
        _settle(app)

        main_window.actions["category_sketch"].trigger()
        _settle(app, ms=150)
        log.require(
            widget._sketch_session is not None,
            "Sketch session started for the tree spot",
        )
        log.require(
            widget._active_workplane_host is None,
            "Independent sketch (no body host) on bottom plane",
        )

        sketches_before = _count_sketch_profiles(scene)
        tree_circle = make_circle_profile_at(
            widget._active_workplane, (300.0, 0.0), 30.0
        )
        circle_id = widget._add_sketch_profile(
            tree_circle,
            widget._sketch_profile_meta(
                profile="circle",
                radius=30.0,
                center_u=300.0,
                center_v=0.0,
                workplane=widget._active_workplane_label,
            ),
        )
        log.passed(f"Circle sketch profile added ({circle_id[:8]})")
        _finish_sketch(app, widget)
        log.require(
            widget._sketch_session is None,
            "Sketch session cleared after Finish",
        )

        log.require(
            main_window.actions["delete_sketch"].isEnabled(),
            "Delete Sketch is enabled for the selected profile",
        )
        bodies_before_delete = len(_body_item_ids(scene))
        main_window.actions["delete_sketch"].trigger()
        _settle(app)
        log.require(
            _count_sketch_profiles(scene) == sketches_before,
            f"Circle profile removed ({_count_sketch_profiles(scene)} sketches left)",
        )
        log.require(
            len(_body_item_ids(scene)) == bodies_before_delete,
            "Bodies untouched by Delete Sketch",
        )

        main_window.actions["category_sketch"].trigger()
        _settle(app, ms=150)
        log.require(
            widget._sketch_session is not None,
            "Second sketch started after delete",
        )
        tree_rect = make_center_rectangle_profile(
            widget._active_workplane, (300.0, 0.0), (15.0, 15.0)
        )
        tree_profile_id = widget._add_sketch_profile(
            tree_rect,
            widget._sketch_profile_meta(
                profile="center_rectangle",
                width=30.0,
                height=30.0,
                center_u=300.0,
                center_v=0.0,
                workplane=widget._active_workplane_label,
            ),
        )
        _finish_sketch(app, widget)
        log.require(
            widget._sketch_session is None,
            "Second sketch finished",
        )

        scene.set_selection(SelectionRef(tree_profile_id, SelectionKind.FACE, 1))
        widget._set_active_category("select")
        _settle(app)
        log.require(
            main_window.actions["edit_sketch"].isEnabled(),
            "Edit Sketch is enabled for the chosen profile",
        )
        main_window.actions["edit_sketch"].trigger()
        _settle(app, ms=150)
        log.require(
            widget._sketch_session is not None,
            "Edit Sketch reopened the sketch session",
        )
        _finish_sketch(app, widget)
        log.require(
            widget._sketch_session is None,
            "Sketch closed after second Finish",
        )
        # Mama changes her mind a final time: she does not want this
        # rectangle either. After Finish the profile is still selected, so
        # one more Delete Sketch leaves the scene clean.
        scene.set_selection(SelectionRef(tree_profile_id, SelectionKind.FACE, 1))
        widget._set_active_category("select")
        _settle(app)
        log.require(
            main_window.actions["delete_sketch"].isEnabled(),
            "Delete Sketch is enabled for the leftover profile",
        )
        main_window.actions["delete_sketch"].trigger()
        _settle(app)
        log.require(
            _count_sketch_profiles(scene) == 0,
            "All leftover sketch profiles are gone after lifecycle step",
        )

        # -----------------------------------------------------------------
        log.step("step10", "Cut a door opening through the front wall")
        front_face = _front_face_of(scene, house_id)
        if front_face is None:
            log.fail("Could not find front wall face")
            return
        log.info(f"Front wall face index: {front_face}")
        widget._selection_kind = SelectionKind.FACE
        widget._viewer.set_selection_kind(SelectionKind.FACE)
        scene.set_selection(SelectionRef(house_id, SelectionKind.FACE, front_face))
        widget._set_active_category("select")
        _settle(app)
        main_window.actions["category_sketch"].trigger()
        _settle(app, ms=150)
        log.require(
            widget._sketch_session is not None
            and widget._active_workplane_host == (house_id, front_face),
            "Sketch hosted on front wall face",
        )
        # Door 25 mm wide, 50 mm tall, centered slightly to the left and
        # close to the ground on the workplane (foundation height = 30,
        # walls add 60, so the door spans the lower part of the wall).
        door_profile = make_center_rectangle_profile(
            widget._active_workplane, (-30.0, -25.0), (12.5, 25.0)
        )
        door_id = widget._add_sketch_profile(
            door_profile,
            widget._sketch_profile_meta(
                profile="center_rectangle",
                width=25.0,
                height=50.0,
                center_u=-30.0,
                center_v=-25.0,
                workplane=widget._active_workplane_label,
            ),
        )
        log.passed(f"Door profile added ({door_id[:8]})")
        # Window profile in the same sketch session, before any cut, so the
        # workplane is shared and the profile coordinates are unambiguous.
        # This is also how a real user would do it: draw both openings in
        # one sketch, then commit.
        window_profile = make_center_rectangle_profile(
            widget._active_workplane, (30.0, -15.0), (10.0, 10.0)
        )
        window_id = widget._add_sketch_profile(
            window_profile,
            widget._sketch_profile_meta(
                profile="center_rectangle",
                width=20.0,
                height=20.0,
                center_u=30.0,
                center_v=-15.0,
                workplane=widget._active_workplane_label,
            ),
        )
        log.passed(f"Window profile added ({window_id[:8]})")

        volume_before = _solid_volume(scene.get(house_id).shape)
        faces_before = _count_faces(scene.get(house_id).shape)
        _settle(app)
        # Negative distance triggers the BRepAlgoAPI_Cut branch in
        # apply_profile_feature, so we don't need to set the cut flag.
        # Extrude both selected profiles together with a negative distance.
        scene.set_selections(
            (
                SelectionRef(door_id, SelectionKind.FACE, 1),
                SelectionRef(window_id, SelectionKind.FACE, 1),
            )
        )
        widget._set_active_category("select")
        _settle(app)
        _extrude_selection(app, widget, distance=-20.0, log=log)
        house_id = _body_item_ids(scene)[-1]
        bbox = _bounding_box(scene.get(house_id).shape)
        log.info(
            "After cuts bbox: "
            f"{bbox['width']:.1f} x {bbox['depth']:.1f} x {bbox['height']:.1f}"
        )
        log.require(
            abs(bbox["height"] - 120.0) < HEIGHT_TOLERANCE,
            f"Overall height unchanged by cuts ({bbox['height']:.2f})",
        )
        volume_after = _solid_volume(scene.get(house_id).shape)
        faces_after = _count_faces(scene.get(house_id).shape)
        log.info(
            f"Volume {volume_before:.0f} -> {volume_after:.0f} mm^3, "
            f"faces {faces_before} -> {faces_after}"
        )
        log.require(
            volume_after < volume_before - 1.0,
            f"Cuts removed material (delta {volume_before - volume_after:.0f})",
        )
        log.require(
            faces_after >= faces_before + 8,
            f"Cuts added at least 8 new faces (door+window): "
            f"{faces_after - faces_before}",
        )

        # -----------------------------------------------------------------
        log.step(
            "step11",
            "Pitch the roof: move its top-left edge down for a sloped roof",
        )
        # Find a top edge of the roof block: along Y axis, on X=-90, Z=120.
        from OCP.TopAbs import TopAbs_EDGE
        from OCP.TopExp import TopExp
        from OCP.TopoDS import TopoDS
        from OCP.TopTools import TopTools_IndexedMapOfShape

        from cad_app.commands import supports_move_edge_controlled
        from cad_app.measurement import edge_measurement

        house_id = _body_item_ids(scene)[-1]
        roof_shape = scene.get(house_id).shape
        edge_map = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(roof_shape, TopAbs_EDGE, edge_map)
        roof_edge_index = None
        for idx in range(1, edge_map.Extent() + 1):
            try:
                edge = TopoDS.Edge_s(edge_map.FindKey(idx))
                m = edge_measurement(edge)
                if m.axis_name != "Y":
                    continue
                x_mid, _y_mid, z_mid = m.midpoint
                if abs(z_mid - 120.0) > 0.5 or abs(x_mid - (-90.0)) > 0.5:
                    continue
                if not supports_move_edge_controlled(roof_shape, idx):
                    continue
                roof_edge_index = idx
                break
            except Exception:  # noqa: BLE001
                continue
        if roof_edge_index is None:
            log.fail("Could not locate a movable top edge on the roof")
            return
        log.info(f"Roof top-left edge index: {roof_edge_index}")

        scene.set_selection(SelectionRef(house_id, SelectionKind.EDGE, roof_edge_index))
        widget._selection_kind = SelectionKind.EDGE
        widget._viewer.set_selection_kind(SelectionKind.EDGE)
        widget._set_active_category("select")
        _settle(app)
        log.require(
            main_window.actions["move"].isEnabled(),
            "Move action is enabled for the selected roof edge",
        )
        main_window.actions["move"].trigger()
        _settle(app)
        if widget._move_session is None:
            log.fail("Move did not start a session for the roof edge")
            return
        # Drag straight down 20 mm: axis Z, distance -20.
        widget._move_session.axis = (0.0, 0.0, 1.0)
        widget._move_session.axis_name = "Z"
        widget._move_session.distance = -20.0
        widget._move_session.vector = (0.0, 0.0, -20.0)
        widget._update_move_preview()
        widget._tool_done()
        _settle(app, ms=160)
        status_text = widget.get_ui_state().status_text
        house_id = _body_item_ids(scene)[-1]
        moved_shape = scene.get(house_id).shape
        validate_shape(moved_shape)
        bbox = _bounding_box(moved_shape)
        log.info(
            "After roof pitch bbox: "
            f"{bbox['width']:.1f} x {bbox['depth']:.1f} x {bbox['height']:.1f}"
        )
        if status_text == "Move failed":
            log.fail("Roof edge move failed instead of creating a slope")
        elif bbox["height"] > 124.0:
            log.fail(
                f"Roof height grew unexpectedly to {bbox['height']:.2f} mm "
                "after move_edge — possible move_edge precision bug"
            )
        else:
            from cad_app.command_topology import _shape_vertex_points

            vertices = _shape_vertex_points(moved_shape)
            left_roof_z = max(z for x, _y, z in vertices if abs(x - (-90.0)) < 0.5)
            right_roof_z = max(z for x, _y, z in vertices if abs(x - 90.0) < 0.5)
            log.require(
                left_roof_z < right_roof_z - 10.0,
                "Roof pitched: left top edge lower than right "
                f"({left_roof_z:.2f} < {right_roof_z:.2f})",
            )

        # -----------------------------------------------------------------
        log.step("step12", "Fillet a vertical wall edge")
        house_id = _body_item_ids(scene)[-1]
        widget._sketch_extrude_operation = "add"  # reset after cuts
        # Find a vertical edge to fillet: walk edges, pick one whose two
        # vertices have the same XY but different Z.
        from OCP.TopAbs import TopAbs_EDGE
        from OCP.TopExp import TopExp
        from OCP.TopTools import TopTools_IndexedMapOfShape

        edge_map = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(scene.get(house_id).shape, TopAbs_EDGE, edge_map)
        from OCP.TopoDS import TopoDS

        from cad_app.commands import edge_supports_direct_round
        from cad_app.measurement import edge_measurement

        fillet_edge_index = None
        for idx in range(1, edge_map.Extent() + 1):
            try:
                edge = TopoDS.Edge_s(edge_map.FindKey(idx))
                m = edge_measurement(edge)
                if m.axis_name == "Z" and edge_supports_direct_round(
                    scene.get(house_id).shape, idx
                ):
                    fillet_edge_index = idx
                    break
            except Exception:  # noqa: BLE001
                continue
        if fillet_edge_index is None:
            log.fail("No fillet-capable vertical edge found")
            return
        log.info(f"Filleting edge #{fillet_edge_index}")
        scene.set_selection(
            SelectionRef(house_id, SelectionKind.EDGE, fillet_edge_index)
        )
        widget._selection_kind = SelectionKind.EDGE
        widget._viewer.set_selection_kind(SelectionKind.EDGE)
        widget._set_active_category("select")
        _settle(app)
        log.require(
            main_window.actions["fillet_chamfer"].isEnabled(),
            "Fillet/Chamfer enabled for vertical edge",
        )
        main_window.actions["fillet_chamfer"].trigger()
        _settle(app)
        if widget._move_session is None:
            log.fail("Fillet did not start a move session")
            return
        widget._move_session.distance = 5.0  # positive → fillet (negative → chamfer)
        widget._update_move_preview()
        widget._tool_done()
        _settle(app, ms=160)
        log.passed("Fillet committed")
        validate_shape(scene.get(_body_item_ids(scene)[-1]).shape)

        # -----------------------------------------------------------------
        log.step("step13", "Plant a tree next to the house")
        scene.set_selection(None)
        widget._set_active_category("select")
        _settle(app)
        main_window.actions["category_sketch"].trigger()
        _settle(app, ms=150)
        log.require(
            widget._sketch_session is not None
            and widget._active_workplane_host is None,
            "Tree sketch starts independent on bottom plane",
        )
        trunk_profile = make_circle_profile_at(
            widget._active_workplane, (220.0, 0.0), 12.0
        )
        trunk_id = widget._add_sketch_profile(
            trunk_profile,
            widget._sketch_profile_meta(
                profile="circle",
                radius=12.0,
                center_u=220.0,
                center_v=0.0,
                workplane=widget._active_workplane_label,
            ),
        )
        _finish_sketch(app, widget)
        scene.set_selection(SelectionRef(trunk_id, SelectionKind.FACE, 1))
        widget._set_active_category("select")
        _settle(app)
        log.require(
            main_window.actions["sketch_new_body"].isEnabled(),
            "New Body action enabled for independent profile",
        )
        # Use New Body (not Extrude) so the trunk does not try to merge
        # with the house body.
        main_window.actions["sketch_new_body"].trigger()
        _settle(app)
        if widget._move_session is None:
            log.fail("sketch_new_body did not start a move session")
            return
        widget._move_session.distance = 70.0
        widget._update_move_preview()
        widget._tool_done()
        _settle(app, ms=160)
        body_ids = _body_item_ids(scene)
        log.info(f"Bodies after planting trunk: {len(body_ids)}")
        log.require(
            len(body_ids) >= 2, f"At least two bodies (house + tree): {len(body_ids)}"
        )

        # -----------------------------------------------------------------
        log.step("step8", "Export STEP + screenshot")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        # Export the largest body (most likely the merged house) or the
        # first body; for now write each into a compound.
        from OCP.BRep import BRep_Builder
        from OCP.TopoDS import TopoDS_Compound

        builder = BRep_Builder()
        compound = TopoDS_Compound()
        builder.MakeCompound(compound)
        for body_id in bodies:
            builder.Add(compound, scene.get(body_id).shape)
        export_step(compound, str(STEP_PATH))
        log.require(STEP_PATH.exists(), f"STEP exists: {STEP_PATH}")

        widget._fit_all()
        viewer.refresh_native_window()
        _settle(app, ms=250)
        _capture(window, widget, SCREENSHOT_PATH)
        log.require(SCREENSHOT_PATH.exists(), f"Screenshot: {SCREENSHOT_PATH}")
        log.require(
            widget.get_ui_state().status_text != "View: Top",
            "Camera is not stuck in Top view after the build",
        )
        # Second screenshot from the Front so the door / window cuts in the
        # front wall are actually visible to a reviewer.
        widget._navigation.view_axis("y", positive=False)
        widget._navigation.fit_all()
        viewer.refresh_native_window()
        _settle(app, ms=250)
        _capture(window, widget, SCREENSHOT_FRONT_PATH)
        log.require(
            SCREENSHOT_FRONT_PATH.exists(),
            f"Front screenshot: {SCREENSHOT_FRONT_PATH}",
        )
        # Third screenshot from the Right so the sloped roof and the gap
        # between house and tree are visible.
        widget._navigation.view_axis("x", positive=True)
        widget._navigation.fit_all()
        viewer.refresh_native_window()
        _settle(app, ms=250)
        _capture(window, widget, SCREENSHOT_RIGHT_PATH)
        log.require(
            SCREENSHOT_RIGHT_PATH.exists(),
            f"Right screenshot: {SCREENSHOT_RIGHT_PATH}",
        )
    finally:
        window.close()
        viewer.close()
        app.processEvents()


def main() -> int:
    log = _Log()
    sys.stdout.write("=== BUILD HOUSE WORKFLOW ===\n")
    try:
        _run(log)
    except Exception as exc:  # noqa: BLE001 - workflow must surface any blocker.
        log.fail(f"Unhandled exception: {exc}")
        import traceback

        traceback.print_exc()
    if log.failed:
        sys.stdout.write("\n=== RESULT: FAIL ===\n")
        return 1
    sys.stdout.write("\n=== RESULT: PASS ===\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
