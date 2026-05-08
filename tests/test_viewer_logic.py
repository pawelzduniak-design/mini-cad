import pytest

from cad_app.types import SelectionKind
from cad_app.viewer import Viewer


class FakeSelectionContext:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.displayed: list[object] = []
        self.removed: list[object] = []
        self.erased: list[object] = []

    def Display(self, ais: object, update: bool) -> None:
        self.calls.append(("display", ais, update, None))
        self.displayed.append(ais)

    def Remove(self, ais: object, update: bool) -> None:
        self.calls.append(("remove", ais, update, None))
        self.removed.append(ais)

    def Erase(self, ais: object, update: bool) -> None:
        self.calls.append(("erase", ais, update, None))
        self.erased.append(ais)

    def Deactivate(self, ais: object) -> None:
        self.calls.append(("deactivate", ais, None, None))

    def Activate(self, ais: object, mode: int, force: bool) -> None:
        self.calls.append(("activate", ais, mode, force))

    def SetSelectionSensitivity(self, ais: object, mode: int, sensitivity: int) -> None:
        self.calls.append(("sensitivity", ais, mode, sensitivity))

    def Redisplay(self, ais: object, update: bool) -> None:
        self.calls.append(("redisplay", ais, update, None))

    def RemoveAll(self, update: bool) -> None:
        self.calls.append(("remove_all", update, None, None))


class FakeView:
    def __init__(self) -> None:
        self.redraw_count = 0
        self.triedron_display_calls = []
        self.triedron_setup_calls = []

    def Redraw(self) -> None:
        self.redraw_count += 1

    def ZBufferTriedronSetup(self, *args) -> None:
        self.triedron_setup_calls.append(args)

    def TriedronDisplay(self, *args) -> None:
        self.triedron_display_calls.append(args)

    def MustBeResized(self) -> None:
        pass

    def FitAll(self, margin: float, update: bool) -> None:
        pass

    def ZFitAll(self) -> None:
        pass

    def SetAutoZFitMode(self, on: bool) -> None:
        pass


def test_viewer_edge_selection_resets_previous_ais_modes() -> None:
    pytest.importorskip("OCP")

    viewer = Viewer()
    fake_context = FakeSelectionContext()
    viewer._context = fake_context
    ais = object()

    viewer._activate_selection_kind(ais, SelectionKind.EDGE)

    assert fake_context.calls == [
        ("deactivate", ais, None, None),
        ("activate", ais, 2, True),
        ("sensitivity", ais, 2, 12),
    ]


def test_viewer_selection_mode_values_match_occt_topology() -> None:
    pytest.importorskip("OCP")

    assert Viewer._selection_mode(SelectionKind.OBJECT) == 0
    assert Viewer._selection_mode(SelectionKind.FACE) == 4
    assert Viewer._selection_mode(SelectionKind.EDGE) == 2
    assert Viewer._selection_mode(SelectionKind.VERTEX) == 1


def test_display_shape_uses_shaded_mode_by_default() -> None:
    pytest.importorskip("OCP")

    from OCP.AIS import AIS_DisplayMode

    from cad_app.engine import make_box

    viewer = Viewer()
    viewer._context = FakeSelectionContext()
    viewer._view = FakeView()
    viewer.is_initialized = True

    viewer.display_shape("box", make_box())

    assert viewer._ais_map["box"].DisplayMode() == AIS_DisplayMode.AIS_Shaded
    assert "box" in viewer._edge_map
    assert viewer._edge_map["box"] in viewer._context.displayed
    assert ("deactivate", viewer._edge_map["box"], None, None) in viewer._context.calls


def test_sketch_profile_display_shape_is_offset_from_workplane() -> None:
    pytest.importorskip("OCP")

    from cad_app.sketch import make_circle_profile_at
    from cad_app.workplane import Workplane

    profile = make_circle_profile_at(Workplane.world_xy(), (0.0, 0.0), 10.0)
    display_shape = Viewer()._display_shape_for_meta(
        profile,
        {"kind": "sketch_profile", "display_normal": (0.0, 0.0, 1.0)},
    )

    assert _shape_bounds(display_shape)[2] > _shape_bounds(profile)[2] + 0.25


def test_sketch_profile_displays_as_wireframe_instead_of_filled_sheet() -> None:
    pytest.importorskip("OCP")

    from OCP.AIS import AIS_DisplayMode

    from cad_app.sketch import make_circle_profile_at
    from cad_app.workplane import Workplane

    viewer = Viewer()
    viewer._context = FakeSelectionContext()
    viewer._view = FakeView()
    viewer.is_initialized = True
    profile = make_circle_profile_at(Workplane.world_xy(), (0.0, 0.0), 10.0)

    viewer.display_shape(
        "profile",
        profile,
        {"kind": "sketch_profile", "display_normal": (0.0, 0.0, 1.0)},
    )

    assert viewer._ais_map["profile"].DisplayMode() == AIS_DisplayMode.AIS_WireFrame


def test_sketch_profile_does_not_get_duplicate_edge_overlay() -> None:
    pytest.importorskip("OCP")

    from cad_app.sketch import make_circle_profile_at
    from cad_app.workplane import Workplane

    viewer = Viewer()
    viewer._context = FakeSelectionContext()
    viewer._view = FakeView()
    viewer.is_initialized = True
    profile = make_circle_profile_at(Workplane.world_xy(), (0.0, 0.0), 10.0)

    viewer.display_shape(
        "profile",
        profile,
        {"kind": "sketch_profile", "display_normal": (0.0, 0.0, 1.0)},
    )

    assert "profile" not in viewer._edge_map


def test_sketch_entity_does_not_get_duplicate_edge_overlay() -> None:
    pytest.importorskip("OCP")

    from cad_app.sketch import make_polyline_preview
    from cad_app.workplane import Workplane

    viewer = Viewer()
    viewer._context = FakeSelectionContext()
    viewer._view = FakeView()
    viewer.is_initialized = True

    viewer.display_shape(
        "line",
        make_polyline_preview(Workplane.world_xy(), [(0.0, 0.0), (10.0, 0.0)]),
        {"kind": "sketch_entity", "display_normal": (0.0, 0.0, 1.0)},
    )

    assert "line" not in viewer._edge_map


def test_sketch_entity_display_shape_uses_larger_offset_than_profile() -> None:
    pytest.importorskip("OCP")

    from cad_app.sketch import make_polyline_preview
    from cad_app.workplane import Workplane

    entity = make_polyline_preview(Workplane.world_xy(), [(0.0, 0.0), (10.0, 0.0)])
    display_shape = Viewer()._display_shape_for_meta(
        entity,
        {"kind": "sketch_entity", "display_normal": (0.0, 0.0, 1.0)},
    )

    assert _shape_bounds(display_shape)[2] > _shape_bounds(entity)[2] + 0.75


def test_display_mode_can_switch_existing_shapes_to_wireframe() -> None:
    pytest.importorskip("OCP")

    from OCP.AIS import AIS_DisplayMode

    from cad_app.engine import make_box

    viewer = Viewer()
    fake_context = FakeSelectionContext()
    viewer._context = fake_context
    viewer._view = FakeView()
    viewer.is_initialized = True
    viewer.display_shape("box", make_box())

    viewer.set_display_mode("wireframe")

    assert viewer.display_mode == "wireframe"
    assert viewer._ais_map["box"].DisplayMode() == AIS_DisplayMode.AIS_WireFrame
    assert ("redisplay", viewer._ais_map["box"], False, None) in fake_context.calls


def test_display_grid_redraws_after_passive_objects_are_added() -> None:
    pytest.importorskip("OCP")

    viewer = Viewer()
    viewer._context = FakeSelectionContext()
    fake_view = FakeView()
    viewer._view = fake_view
    viewer.is_initialized = True

    viewer.display_grid(size=20.0, step=10.0)

    assert len(viewer._grid_objects) > 0
    assert fake_view.redraw_count == 1


def test_display_orientation_gizmo_uses_ocp_triedron() -> None:
    pytest.importorskip("OCP")

    viewer = Viewer()
    viewer._context = FakeSelectionContext()
    fake_view = FakeView()
    viewer._view = fake_view
    viewer.is_initialized = True

    viewer.display_orientation_gizmo()

    assert len(fake_view.triedron_setup_calls) == 1
    assert len(fake_view.triedron_display_calls) == 1


def test_preview_marker_is_passive_and_replaceable() -> None:
    pytest.importorskip("OCP")

    from cad_app.engine import make_box

    viewer = Viewer()
    fake_context = FakeSelectionContext()
    viewer._context = fake_context
    viewer._view = FakeView()
    viewer.is_initialized = True

    viewer.display_preview_marker(make_box())
    first_marker = viewer._preview_marker
    viewer.display_preview_marker(make_box())

    assert first_marker in fake_context.removed
    assert viewer._preview_marker is not None
    assert ("deactivate", viewer._preview_marker, None, None) in fake_context.calls


def test_preview_marker_uses_polygon_offset_to_avoid_z_fighting() -> None:
    pytest.importorskip("OCP")

    from OCP.Aspect import Aspect_POM_Fill

    from cad_app.engine import make_box

    viewer = Viewer()
    viewer._context = FakeSelectionContext()
    viewer._view = FakeView()
    viewer.is_initialized = True

    viewer.display_preview_marker(make_box())

    assert viewer._preview_marker is not None
    shading_aspect = viewer._preview_marker.Attributes().ShadingAspect()
    assert shading_aspect is not None
    assert shading_aspect.Aspect().PolygonOffsets(0.0, 0.0) == (int(Aspect_POM_Fill),)


def test_sketch_preview_marker_is_wireframe_and_offset_above_workplane() -> None:
    pytest.importorskip("OCP")

    from OCP.AIS import AIS_DisplayMode

    from cad_app.sketch import make_rectangle_profile
    from cad_app.workplane import Workplane

    profile = make_rectangle_profile(Workplane.world_xy(), width=40.0, height=20.0)
    viewer = Viewer()
    fake_context = FakeSelectionContext()
    viewer._context = fake_context
    viewer._view = FakeView()
    viewer.is_initialized = True

    viewer.display_sketch_preview_marker(profile, (0.0, 0.0, 1.0))

    assert viewer._preview_marker is not None
    assert viewer._preview_marker.DisplayMode() == AIS_DisplayMode.AIS_WireFrame
    assert _shape_bounds(viewer._preview_marker.Shape())[2] > (
        _shape_bounds(profile)[2] + 0.75
    )
    assert ("deactivate", viewer._preview_marker, None, None) in fake_context.calls


def test_sketch_plane_marker_is_passive_and_replaceable() -> None:
    pytest.importorskip("OCP")

    from cad_app.workplane import Workplane

    viewer = Viewer()
    fake_context = FakeSelectionContext()
    viewer._context = fake_context
    viewer._view = FakeView()
    viewer.is_initialized = True

    viewer.display_sketch_plane_marker(Workplane.world_xy(), size=20.0)
    first_marker = viewer._sketch_plane_marker
    viewer.display_sketch_plane_marker(Workplane.world_xy(), size=20.0)

    assert first_marker in fake_context.removed
    assert viewer._sketch_plane_marker is not None
    assert ("deactivate", viewer._sketch_plane_marker, None, None) in fake_context.calls


def test_sketch_plane_marker_is_offset_above_workplane() -> None:
    pytest.importorskip("OCP")

    from cad_app.workplane import Workplane

    overlay = Viewer._build_workplane_overlay_shape(Workplane.world_xy(), size=20.0)

    assert _shape_bounds(overlay)[2] > 0.35


def test_viewer_grid_shape_contains_expected_line_edges() -> None:
    pytest.importorskip("OCP")

    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    grid = Viewer._build_grid_shape(size=20.0, step=10.0)
    edge_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(grid, TopAbs_EDGE, edge_map)

    assert edge_map.Extent() == 8


def test_viewer_workplane_overlay_shape_avoids_closed_profile_frame() -> None:
    pytest.importorskip("OCP")

    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    from cad_app.workplane import Workplane

    overlay = Viewer._build_workplane_overlay_shape(
        Workplane.world_xy(),
        size=20.0,
    )
    edge_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(overlay, TopAbs_EDGE, edge_map)

    assert edge_map.Extent() == 10


def _shape_bounds(shape) -> tuple[float, float, float, float, float, float]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    bounds = Bnd_Box()
    BRepBndLib.Add_s(shape, bounds)
    return bounds.Get()


def test_sketch_display_offsets_meet_minimum_thresholds() -> None:
    from cad_app.viewer import (
        SKETCH_DISPLAY_OFFSET,
        SKETCH_ENTITY_DISPLAY_OFFSET,
        SKETCH_MARKER_OFFSET,
        SKETCH_PLANE_OFFSET,
        SKETCH_PREVIEW_OFFSET,
    )

    assert (
        SKETCH_DISPLAY_OFFSET >= 1.0
    ), "Sketch display offset too small - z-fighting risk"
    assert SKETCH_ENTITY_DISPLAY_OFFSET >= 1.5, "Sketch entity display offset too small"
    assert SKETCH_PLANE_OFFSET >= 1.0, "Sketch plane offset too small"
    assert SKETCH_MARKER_OFFSET >= 1.5, "Sketch marker offset too small"
    assert SKETCH_PREVIEW_OFFSET >= 1.5, "Sketch preview offset too small"


def test_preview_polygon_offset_meets_minimum_thresholds() -> None:
    from cad_app.viewer import (
        PREVIEW_POLYGON_OFFSET_FACTOR,
        PREVIEW_POLYGON_OFFSET_UNITS,
    )

    assert (
        PREVIEW_POLYGON_OFFSET_FACTOR <= -4.0
    ), "Polygon offset factor too weak - z-fighting risk"
    assert PREVIEW_POLYGON_OFFSET_UNITS <= -4.0, "Polygon offset units too weak"


def test_sketch_selection_marker_uses_topmost_z_layer() -> None:
    pytest.importorskip("OCP")

    from cad_app.sketch import make_circle_profile_at
    from cad_app.workplane import Workplane

    viewer = Viewer()
    viewer._context = FakeSelectionContext()
    viewer._view = FakeView()
    viewer.is_initialized = True
    profile = make_circle_profile_at(Workplane.world_xy(), (0.0, 0.0), 10.0)

    viewer.display_selection_marker(
        profile,
        {"kind": "sketch_profile", "display_normal": (0.0, 0.0, 1.0)},
    )

    assert viewer._selection_marker is not None
    assert hasattr(viewer._selection_marker, "ZLayer")
    from OCP.Graphic3d import Graphic3d_ZLayerId_Topmost

    assert viewer._selection_marker.ZLayer() == Graphic3d_ZLayerId_Topmost


def test_sketch_hover_marker_uses_topmost_z_layer() -> None:
    pytest.importorskip("OCP")

    from cad_app.sketch import make_circle_profile_at
    from cad_app.workplane import Workplane

    viewer = Viewer()
    viewer._context = FakeSelectionContext()
    viewer._view = FakeView()
    viewer.is_initialized = True
    profile = make_circle_profile_at(Workplane.world_xy(), (0.0, 0.0), 10.0)

    viewer.display_hover_marker(
        profile,
        {"kind": "sketch_profile", "display_normal": (0.0, 0.0, 1.0)},
    )

    assert viewer._hover_marker is not None
    assert hasattr(viewer._hover_marker, "ZLayer")
    from OCP.Graphic3d import Graphic3d_ZLayerId_Topmost

    assert viewer._hover_marker.ZLayer() == Graphic3d_ZLayerId_Topmost


def test_sketch_plane_marker_uses_topmost_z_layer() -> None:
    pytest.importorskip("OCP")

    from cad_app.workplane import Workplane

    viewer = Viewer()
    viewer._context = FakeSelectionContext()
    viewer._view = FakeView()
    viewer.is_initialized = True

    viewer.display_sketch_plane_marker(Workplane.world_xy(), size=20.0)

    assert viewer._sketch_plane_marker is not None
    assert hasattr(viewer._sketch_plane_marker, "ZLayer")
    from OCP.Graphic3d import Graphic3d_ZLayerId_Topmost

    assert viewer._sketch_plane_marker.ZLayer() == Graphic3d_ZLayerId_Topmost


def test_body_markers_do_not_use_topmost_z_layer() -> None:
    pytest.importorskip("OCP")

    from cad_app.engine import make_box

    viewer = Viewer()
    viewer._context = FakeSelectionContext()
    viewer._view = FakeView()
    viewer.is_initialized = True
    shape = make_box(20.0, 20.0, 20.0)

    viewer.display_selection_marker(shape)
    assert viewer._selection_marker is not None
    assert hasattr(viewer._selection_marker, "ZLayer")
    from OCP.Graphic3d import Graphic3d_ZLayerId_Topmost

    assert viewer._selection_marker.ZLayer() != Graphic3d_ZLayerId_Topmost

    viewer.display_hover_marker(shape)
    assert viewer._hover_marker is not None
    assert viewer._hover_marker.ZLayer() != Graphic3d_ZLayerId_Topmost


def test_preview_marker_hides_original_item_during_preview() -> None:
    pytest.importorskip("OCP")

    from cad_app.engine import make_box

    viewer = Viewer()
    fake_context = FakeSelectionContext()
    viewer._context = fake_context
    viewer._view = FakeView()
    viewer.is_initialized = True

    box = make_box(40.0, 40.0, 40.0)
    viewer.display_shape("box", box)

    viewer.display_preview_marker(make_box(30.0, 30.0, 30.0), hide_item_id="box")

    assert viewer._ais_map["box"] in fake_context.erased
    assert "box" in viewer._preview_hidden_items


def test_preview_marker_restores_hidden_item_on_clear() -> None:
    pytest.importorskip("OCP")

    from cad_app.engine import make_box

    viewer = Viewer()
    fake_context = FakeSelectionContext()
    viewer._context = fake_context
    viewer._view = FakeView()
    viewer.is_initialized = True

    box = make_box(40.0, 40.0, 40.0)
    viewer.display_shape("box", box)

    viewer.display_preview_marker(make_box(30.0, 30.0, 30.0), hide_item_id="box")
    viewer.clear_preview_marker()

    assert "box" not in viewer._preview_hidden_items
    assert viewer._preview_marker is None
    assert viewer._ais_map["box"] in fake_context.displayed


def test_preview_marker_replace_restores_previous_hidden_then_hides_new() -> None:
    pytest.importorskip("OCP")

    from cad_app.engine import make_box

    viewer = Viewer()
    fake_context = FakeSelectionContext()
    viewer._context = fake_context
    viewer._view = FakeView()
    viewer.is_initialized = True

    box_a = make_box(40.0, 40.0, 40.0)
    viewer.display_shape("box_a", box_a)

    viewer.display_preview_marker(make_box(30.0, 30.0, 30.0), hide_item_id="box_a")

    assert "box_a" in viewer._preview_hidden_items
    assert viewer._ais_map["box_a"] in fake_context.erased

    viewer.display_preview_marker(make_box(35.0, 35.0, 35.0), hide_item_id="box_a")

    assert viewer._ais_map["box_a"] in fake_context.erased
    assert "box_a" in viewer._preview_hidden_items


def test_sketch_on_face_display_avoids_surface_competition() -> None:
    pytest.importorskip("OCP")

    from cad_app.engine import make_box
    from cad_app.scene import Scene
    from cad_app.sketch import SKETCH_META_KIND, make_circle_profile_at
    from cad_app.workplane import Workplane

    scene = Scene()
    box = make_box(80.0, 80.0, 40.0)
    host_id = scene.add_shape(box, meta={"kind": "body"})

    workplane = Workplane.world_xy()

    profile = make_circle_profile_at(workplane, (0.0, 0.0), 15.0)
    profile_id = scene.add_shape(
        profile,
        meta={
            "kind": SKETCH_META_KIND,
            "display_normal": (0.0, 0.0, 1.0),
            "host_item_id": host_id,
        },
    )

    viewer = Viewer()
    viewer._context = FakeSelectionContext()
    viewer._view = FakeView()
    viewer.is_initialized = True

    viewer.display_scene(scene)

    assert profile_id in viewer._ais_map
    from OCP.AIS import AIS_DisplayMode

    assert viewer._ais_map[profile_id].DisplayMode() == AIS_DisplayMode.AIS_WireFrame
    assert profile_id not in viewer._edge_map

    display_shape = viewer._ais_map[profile_id].Shape()
    assert _shape_bounds(display_shape)[2] > _shape_bounds(profile)[2] + 1.0


def test_selection_marker_for_body_face_uses_polygon_offset() -> None:
    pytest.importorskip("OCP")

    from OCP.Aspect import Aspect_POM_Fill

    from cad_app.engine import make_box

    viewer = Viewer()
    viewer._context = FakeSelectionContext()
    viewer._view = FakeView()
    viewer.is_initialized = True

    viewer.display_selection_marker(make_box(20.0, 20.0, 20.0))

    assert viewer._selection_marker is not None
    shading_aspect = viewer._selection_marker.Attributes().ShadingAspect()
    assert shading_aspect is not None
    assert shading_aspect.Aspect().PolygonOffsets(0.0, 0.0) == (int(Aspect_POM_Fill),)


def test_hover_marker_for_body_face_uses_polygon_offset() -> None:
    pytest.importorskip("OCP")

    from OCP.Aspect import Aspect_POM_Fill

    from cad_app.engine import make_box

    viewer = Viewer()
    viewer._context = FakeSelectionContext()
    viewer._view = FakeView()
    viewer.is_initialized = True

    viewer.display_hover_marker(make_box(20.0, 20.0, 20.0))

    assert viewer._hover_marker is not None
    shading_aspect = viewer._hover_marker.Attributes().ShadingAspect()
    assert shading_aspect is not None
    assert shading_aspect.Aspect().PolygonOffsets(0.0, 0.0) == (int(Aspect_POM_Fill),)
