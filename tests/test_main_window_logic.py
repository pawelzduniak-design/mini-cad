import pytest

from cad_app.main_window import (
    EXTRUDE_DRAG_FALLBACK_AXIS,
    MoveSession,
    _drag_distance_delta,
    _normalize_screen_axis,
    _sketch_dimension_label,
)


def _volume(shape) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def _count_faces_of_type(shape, surface_type) -> int:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.TopoDS import TopoDS

    from cad_app.picker import Picker
    from cad_app.types import SelectionKind

    face_map = Picker.indexed_map(shape, SelectionKind.FACE)
    return sum(
        1
        for index in range(1, face_map.Extent() + 1)
        if BRepAdaptor_Surface(TopoDS.Face_s(face_map.FindKey(index))).GetType()
        == surface_type
    )


def test_extrude_drag_uses_screen_axis_instead_of_horizontal_delta() -> None:
    scale = 0.2

    assert _drag_distance_delta(50, 0, scale, EXTRUDE_DRAG_FALLBACK_AXIS) == 0
    assert _drag_distance_delta(0, -50, scale, EXTRUDE_DRAG_FALLBACK_AXIS) == 10


def test_plain_move_drag_keeps_horizontal_delta() -> None:
    assert _drag_distance_delta(50, -50, 0.2) == 10


def test_screen_axis_normalization_rejects_tiny_projection() -> None:
    assert _normalize_screen_axis(0.5, 0.5) is None
    assert _normalize_screen_axis(3, 4) == pytest.approx((0.6, 0.8))


def test_sketch_dimension_label_reports_rectangle_size() -> None:
    assert _sketch_dimension_label("rectangle", (10.0, -5.0), (-20.0, 15.0)) == (
        "30.0 x 20.0"
    )


def test_sketch_dimension_label_reports_circle_radius() -> None:
    assert _sketch_dimension_label("circle", (1.0, 2.0), (4.0, 6.0)) == "R 5.0"


def test_line_first_click_leaves_visible_start_marker() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape
    from PySide6.QtWidgets import QApplication

    from cad_app.main_window import SketchSession, create_main_window
    from cad_app.scene import Scene
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    QApplication.instance() or QApplication([])
    main_window = create_main_window(Viewer(), Scene())
    captured = []
    main_window.viewer_widget._viewer.display_sketch_preview_marker = (
        lambda shape, normal: captured.append(shape)
    )
    session = SketchSession(Workplane.world_xy(), "XY", None, tool="line")

    main_window.viewer_widget._handle_line_click(session, (0.0, 0.0), 20, 20)

    edge_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(captured[-1], TopAbs_EDGE, edge_map)
    assert edge_map.Extent() == 2


def test_arc_second_click_keeps_base_line_visible() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape
    from PySide6.QtWidgets import QApplication

    from cad_app.main_window import SketchSession, create_main_window
    from cad_app.scene import Scene
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    QApplication.instance() or QApplication([])
    main_window = create_main_window(Viewer(), Scene())
    captured = []
    main_window.viewer_widget._viewer.display_sketch_preview_marker = (
        lambda shape, normal: captured.append(shape)
    )
    session = SketchSession(Workplane.world_xy(), "XY", None, tool="arc")

    main_window.viewer_widget._handle_arc_click(session, (0.0, 0.0), 20, 20)
    main_window.viewer_widget._handle_arc_click(session, (10.0, 0.0), 30, 20)

    edge_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(captured[-1], TopAbs_EDGE, edge_map)
    assert edge_map.Extent() == 1


def test_right_mouse_button_starts_pan_without_middle_button() -> None:
    pytest.importorskip("PySide6")

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from cad_app.main_window import create_main_window
    from cad_app.viewer import Viewer

    app = QApplication.instance() or QApplication([])
    main_window = create_main_window(Viewer())
    widget = main_window.viewer_widget

    QTest.mousePress(widget, Qt.RightButton, Qt.NoModifier, QPoint(20, 20))
    assert app is not None
    assert main_window.navigation._is_panning is True

    QTest.mouseRelease(widget, Qt.RightButton, Qt.NoModifier, QPoint(25, 25))
    assert main_window.navigation._is_panning is False

    QTest.mousePress(widget, Qt.MiddleButton, Qt.ShiftModifier, QPoint(20, 20))
    assert main_window.navigation._is_panning is False
    QTest.mouseRelease(widget, Qt.MiddleButton, Qt.ShiftModifier, QPoint(20, 20))


def test_extrude_preview_uses_boolean_result_for_inward_push() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication

    from cad_app.commands import top_planar_face_index
    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind
    from cad_app.viewer import Viewer

    scene = Scene()
    shape = make_box(40, 40, 40)
    item_id = scene.add_shape(shape)
    QApplication.instance() or QApplication([])
    main_window = create_main_window(Viewer(), scene)
    face_index = top_planar_face_index(shape)
    main_window.viewer_widget._move_session = MoveSession(
        tool="extrude",
        target_kind=SelectionKind.FACE,
        item_id=item_id,
        index=face_index,
        axis_name="Normal",
        axis=(0.0, 0.0, 1.0),
        distance=-8.0,
    )

    preview = main_window.viewer_widget._move_preview_shape(
        main_window.viewer_widget._move_session
    )

    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    solid_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(preview, TopAbs_SOLID, solid_map)

    assert preview is not None
    assert solid_map.Extent() == 1


def test_context_move_uses_selected_edge_instead_of_active_object() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    scene = Scene()
    item_id = scene.add_shape(make_box())
    QApplication.instance() or QApplication([])
    main_window = create_main_window(Viewer(), scene)
    scene.set_selection(SelectionRef(item_id=item_id, kind=SelectionKind.EDGE, index=2))

    main_window.viewer_widget._begin_context_move_tool()

    session = main_window.viewer_widget._move_session
    assert session is not None
    assert session.target_kind == SelectionKind.EDGE
    assert session.item_id == item_id
    assert session.index == 2


def test_sketch_new_body_keeps_host_and_sets_boolean_target() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from OCP.gp import gp_Dir, gp_Pnt
    from PySide6.QtWidgets import QApplication

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.sketch import SKETCH_META_KIND, make_circle_profile_at
    from cad_app.viewer import Viewer
    from cad_app.workplane import Workplane

    scene = Scene()
    host_id = scene.add_shape(make_box(60, 60, 20), meta={"kind": "body"})
    workplane = Workplane(
        origin=gp_Pnt(0.0, 0.0, 20.0),
        normal=gp_Dir(0.0, 0.0, 1.0),
        x_direction=gp_Dir(1.0, 0.0, 0.0),
        y_direction=gp_Dir(0.0, 1.0, 0.0),
    )
    profile_id = scene.add_shape(
        make_circle_profile_at(workplane, (0.0, 0.0), 8.0),
        meta={
            "kind": SKETCH_META_KIND,
            "host_item_id": host_id,
            "profile": "circle",
        },
    )
    QApplication.instance() or QApplication([])
    main_window = create_main_window(Viewer(), scene)

    main_window.viewer_widget._apply_sketch_extrude(
        profile_id,
        12.0,
        new_body=True,
    )

    assert len(scene) == 2
    assert scene.get(host_id).meta["kind"] == "body"
    assert scene.get(profile_id).meta["source"] == "sketch_new_body"
    assert scene.active_item_id() == profile_id
    assert main_window.viewer_widget._boolean_target_item_id == host_id
    assert main_window.viewer_widget._active_category == "transform"


def test_context_move_uses_view_drag_for_selected_face() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    scene = Scene()
    item_id = scene.add_shape(make_box())
    QApplication.instance() or QApplication([])
    main_window = create_main_window(Viewer(), scene)
    scene.set_selection(SelectionRef(item_id=item_id, kind=SelectionKind.FACE, index=2))

    main_window.viewer_widget._begin_context_move_tool()

    session = main_window.viewer_widget._move_session
    assert session is not None
    assert session.target_kind == SelectionKind.FACE
    assert session.item_id == item_id
    assert session.index == 2
    assert session.axis_name == "View"


def test_edge_fillet_tool_uses_draggable_parameter_preview() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from OCP.GeomAbs import GeomAbs_Cylinder
    from PySide6.QtWidgets import QApplication

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    scene = Scene()
    item_id = scene.add_shape(make_box(40, 40, 40))
    QApplication.instance() or QApplication([])
    main_window = create_main_window(Viewer(), scene)
    scene.set_selection(SelectionRef(item_id=item_id, kind=SelectionKind.EDGE, index=1))

    main_window.viewer_widget._begin_fillet_tool()
    session = main_window.viewer_widget._move_session
    preview = main_window.viewer_widget._move_preview_shape(session)

    assert session is not None
    assert session.tool == "fillet"
    assert session.distance == pytest.approx(4.0)
    assert _count_faces_of_type(preview, GeomAbs_Cylinder) == 1


def test_chamfer_tool_commits_parameter_session() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    scene = Scene()
    item_id = scene.add_shape(make_box(40, 40, 40))
    before = _volume(scene.get(item_id).shape)
    QApplication.instance() or QApplication([])
    main_window = create_main_window(Viewer(), scene)
    scene.set_selection(SelectionRef(item_id=item_id, kind=SelectionKind.EDGE, index=1))

    main_window.viewer_widget._begin_chamfer_tool()
    main_window.viewer_widget._move_session.distance = 3.0
    main_window.viewer_widget._commit_move_session()

    assert main_window.viewer_widget._move_session is None
    assert _volume(scene.get(item_id).shape) < before


def test_rotate_body_tool_commits_angle_session() -> None:
    pytest.importorskip("OCP")
    pytest.importorskip("PySide6")

    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from PySide6.QtWidgets import QApplication

    from cad_app.engine import make_box
    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    scene = Scene()
    item_id = scene.add_shape(make_box(20, 40, 10), meta={"kind": "body"})
    scene.set_selection(
        SelectionRef(item_id=item_id, kind=SelectionKind.OBJECT, index=0)
    )
    QApplication.instance() or QApplication([])
    main_window = create_main_window(Viewer(), scene)
    main_window.viewer_widget._set_move_axis("Z", (0.0, 0.0, 1.0))

    main_window.viewer_widget._begin_object_rotate_tool()
    main_window.viewer_widget._move_session.distance = 90.0
    main_window.viewer_widget._commit_move_session()

    bounds = Bnd_Box()
    BRepBndLib.Add_s(scene.get(item_id).shape, bounds)
    x_min, y_min, *_rest, x_max, y_max, _z_max = bounds.Get()

    assert main_window.viewer_widget._move_session is None
    assert x_max - x_min == pytest.approx(40.0, abs=1e-6)
    assert y_max - y_min == pytest.approx(20.0, abs=1e-6)


def test_object_move_refuses_to_start_when_edge_is_selected() -> None:
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    scene = Scene()
    item_id = scene.add_shape("body")
    QApplication.instance() or QApplication([])
    main_window = create_main_window(Viewer(), scene)
    scene.set_selection(SelectionRef(item_id=item_id, kind=SelectionKind.EDGE, index=2))

    main_window.viewer_widget._begin_object_move_tool_on_axis(
        "X",
        (1.0, 0.0, 0.0),
    )

    assert main_window.viewer_widget._move_session is None


def test_orientation_gizmo_hit_region_is_bottom_right() -> None:
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.viewer import Viewer

    QApplication.instance() or QApplication([])
    main_window = create_main_window(Viewer(), Scene())
    widget = main_window.viewer_widget
    widget.resize(800, 600)
    left, top, size = widget._orientation_gizmo_rect()

    assert left > widget.width() - size - 30
    assert top > widget.height() - size - 30
    assert widget._is_in_orientation_gizmo(left + size // 2, top + size // 2)
    assert not widget._is_in_orientation_gizmo(20, 20)
    assert widget._orientation_gizmo_axis_at(left + size // 2, top + 5) == "z"
