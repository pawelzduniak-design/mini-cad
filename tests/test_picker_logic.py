from importlib.util import find_spec

import pytest


class FakeContext:
    def __init__(self, detected_shape=None) -> None:
        self.detected_shape = detected_shape
        self.move_to = None
        self.selected = False

    def MoveTo(self, x: int, y: int, view, redraw: bool) -> None:
        self.move_to = (x, y, view, redraw)

    def HasDetectedShape(self) -> bool:
        return self.detected_shape is not None

    def DetectedShape(self):
        return self.detected_shape

    def SelectDetected(self) -> None:
        self.selected = True


class FakeView:
    def __init__(self) -> None:
        self.redraw_calls = 0

    def Redraw(self) -> None:
        self.redraw_calls += 1

    def Convert(self, x: float, y: float, z: float) -> tuple[int, int]:
        return (round(x * 10 + 100), round(y * 10 + 100))

    def Eye(self) -> tuple[float, float, float]:
        return (0.0, 0.0, 100.0)

    def ConvertWithProj(self, x: int, y: int) -> tuple[float, ...]:
        return (0.0, 0.0, 100.0, 0.0, 0.0, -1.0)


def test_picker_preserves_passed_empty_scene() -> None:
    from cad_app.picker import Picker
    from cad_app.scene import Scene

    scene = Scene()
    picker = Picker(scene)

    assert picker._scene is scene


def test_picker_counts_box_topology_when_dependencies_exist() -> None:
    if find_spec("build123d") is None or find_spec("OCP") is None:
        pytest.skip("OCP/build123d are not installed in the active environment.")

    from cad_app.engine import make_box
    from cad_app.picker import Picker
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind

    scene = Scene()
    item_id = scene.add_shape(make_box(10, 20, 30))
    picker = Picker(scene)

    assert picker.count_subshapes(item_id, SelectionKind.OBJECT) == 1
    assert picker.count_subshapes(item_id, SelectionKind.FACE) == 6
    assert picker.count_subshapes(item_id, SelectionKind.EDGE) == 12
    assert picker.count_subshapes(item_id, SelectionKind.VERTEX) == 8


def test_picker_returns_stable_selection_ref_when_dependencies_exist() -> None:
    if find_spec("build123d") is None or find_spec("OCP") is None:
        pytest.skip("OCP/build123d are not installed in the active environment.")

    from cad_app.engine import make_box
    from cad_app.picker import Picker
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind

    scene = Scene()
    item_id = scene.add_shape(make_box(10, 20, 30))
    picker = Picker(scene)

    face = picker.subshape(item_id, SelectionKind.FACE, 1)
    selection = picker.selection_for_subshape(item_id, SelectionKind.FACE, face)

    assert selection is not None
    assert selection.item_id == item_id
    assert selection.kind == SelectionKind.FACE
    assert selection.index == 1

    object_selection = picker.selection_for_subshape(
        item_id,
        SelectionKind.OBJECT,
        scene.get(item_id).shape,
    )

    assert object_selection is not None
    assert object_selection.item_id == item_id
    assert object_selection.kind == SelectionKind.OBJECT
    assert object_selection.index == 0


def test_picker_rejects_out_of_range_subshape_index_when_dependencies_exist() -> None:
    if find_spec("build123d") is None or find_spec("OCP") is None:
        pytest.skip("OCP/build123d are not installed in the active environment.")

    from cad_app.engine import make_box
    from cad_app.picker import Picker
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind

    scene = Scene()
    item_id = scene.add_shape(make_box(10, 20, 30))
    picker = Picker(scene)

    with pytest.raises(IndexError, match="out of range"):
        picker.subshape(item_id, SelectionKind.FACE, 7)
    with pytest.raises(IndexError, match="out of range"):
        picker.subshape(item_id, SelectionKind.OBJECT, 1)


def test_picker_pick_face_at_returns_selection_ref_when_dependencies_exist() -> None:
    if find_spec("build123d") is None or find_spec("OCP") is None:
        pytest.skip("OCP/build123d are not installed in the active environment.")

    from cad_app.engine import make_box
    from cad_app.picker import Picker
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind

    scene = Scene()
    item_id = scene.add_shape(make_box(10, 20, 30))
    picker = Picker(scene)
    face = picker.subshape(item_id, SelectionKind.FACE, 1)
    context = FakeContext(face)
    view = FakeView()

    selection = picker.pick_face_at(context, view, 10, 20)

    assert selection is not None
    assert selection.item_id == item_id
    assert selection.kind == SelectionKind.FACE
    assert context.move_to is None
    assert context.selected is False


def test_picker_pick_face_result_uses_nearest_ray_hit_when_dependencies_exist() -> None:
    if find_spec("build123d") is None or find_spec("OCP") is None:
        pytest.skip("OCP/build123d are not installed in the active environment.")

    from cad_app.engine import make_box
    from cad_app.picker import Picker
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind

    scene = Scene()
    item_id = scene.add_shape(make_box(10, 20, 30))
    picker = Picker(scene)

    result = picker.pick_face_result_at(FakeView(), 10, 20)

    assert result is not None
    assert result.selection.item_id == item_id
    assert result.selection.kind == SelectionKind.FACE
    assert result.depth == pytest.approx(70.0)


def test_picker_prefers_sketch_profile_over_host_face_at_same_hit_metric() -> None:
    from cad_app.picker import Picker

    assert Picker._is_better_face_pick(
        distance=0.0,
        depth=100.0,
        priority=0,
        best_distance=0.0,
        best_depth=50.0,
        best_priority=1,
    )
    assert not Picker._is_better_face_pick(
        distance=0.0,
        depth=50.0,
        priority=1,
        best_distance=0.0,
        best_depth=100.0,
        best_priority=0,
    )


def test_picker_pick_at_uses_screen_space_edge_selection_when_available() -> None:
    if find_spec("build123d") is None or find_spec("OCP") is None:
        pytest.skip("OCP/build123d are not installed in the active environment.")

    from cad_app.engine import make_box
    from cad_app.picker import Picker
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind

    scene = Scene()
    item_id = scene.add_shape(make_box(10, 20, 30))
    picker = Picker(scene)
    context = FakeContext()
    view = FakeView()

    selection = picker.pick_at(context, view, 100, 3, SelectionKind.EDGE)

    assert selection is not None
    assert selection.item_id == item_id
    assert selection.kind == SelectionKind.EDGE
    assert context.move_to is None
    assert context.selected is False


def test_picker_screen_space_edge_selection_rejects_far_click() -> None:
    if find_spec("build123d") is None or find_spec("OCP") is None:
        pytest.skip("OCP/build123d are not installed in the active environment.")

    from cad_app.engine import make_box
    from cad_app.picker import Picker
    from cad_app.scene import Scene

    scene = Scene()
    scene.add_shape(make_box(10, 20, 30))
    picker = Picker(scene)

    selection = picker.pick_edge_at(FakeView(), 500, 500)

    assert selection is None


def test_picker_pick_at_uses_screen_space_vertex_selection_when_available() -> None:
    if find_spec("build123d") is None or find_spec("OCP") is None:
        pytest.skip("OCP/build123d are not installed in the active environment.")

    from OCP.BRep import BRep_Tool
    from OCP.TopoDS import TopoDS

    from cad_app.engine import make_box
    from cad_app.picker import Picker
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind

    scene = Scene()
    item_id = scene.add_shape(make_box(10, 20, 30))
    picker = Picker(scene)
    vertex = TopoDS.Vertex_s(picker.subshape(item_id, SelectionKind.VERTEX, 1))
    point = BRep_Tool.Pnt_s(vertex)
    view = FakeView()
    x, y = view.Convert(point.X(), point.Y(), point.Z())

    selection = picker.pick_at(FakeContext(), view, x, y, SelectionKind.VERTEX)

    assert selection is not None
    assert selection.item_id == item_id
    assert selection.kind == SelectionKind.VERTEX
    assert selection.index == 1


def test_picker_point_to_segment_distance_is_closest_on_segment() -> None:
    from cad_app.picker import Picker

    distance = Picker._point_to_segment_distance((5.0, 3.0), (0.0, 0.0), (10.0, 0.0))

    assert distance == 3.0


def test_picker_edge_pick_tie_break_prefers_closer_depth() -> None:
    from cad_app.picker import Picker

    assert Picker._is_better_edge_pick(
        distance=5.0,
        depth=10.0,
        best_distance=6.0,
        best_depth=100.0,
    )
    assert Picker._is_better_edge_pick(
        distance=5.5,
        depth=10.0,
        best_distance=5.0,
        best_depth=100.0,
    )
    assert not Picker._is_better_edge_pick(
        distance=5.5,
        depth=120.0,
        best_distance=5.0,
        best_depth=100.0,
    )
