from cad_app.scene import Scene
from cad_app.types import SelectionKind, SelectionRef


def test_scene_add_get_replace_remove() -> None:
    scene = Scene()
    item_id = scene.add_shape("shape-a", meta={"kind": "box"})

    assert len(scene) == 1
    assert item_id in scene
    assert scene.get(item_id).shape == "shape-a"
    assert scene.get(item_id).meta == {"kind": "box"}

    scene.replace_shape(item_id, "shape-b")
    assert scene.get(item_id).shape == "shape-b"
    assert scene.get(item_id).meta == {"kind": "box"}

    removed = scene.remove(item_id)
    assert removed.shape == "shape-b"
    assert len(scene) == 0


def test_scene_iteration_returns_objects() -> None:
    scene = Scene()
    item_id = scene.add_shape("shape")
    assert [item.item_id for item in scene] == [item_id]


def test_scene_tracks_active_item() -> None:
    scene = Scene()
    first_id = scene.add_shape("first")
    second_id = scene.add_shape("second")

    assert scene.active_item_id() == first_id

    scene.set_active_item(second_id)
    assert scene.active_item_id() == second_id

    scene.remove(second_id)
    assert scene.active_item_id() == first_id

    scene.clear()
    assert scene.active_item_id() is None


def test_scene_tracks_selection_and_active_item() -> None:
    scene = Scene()
    item_id = scene.add_shape("shape")
    selection = SelectionRef(item_id=item_id, kind=SelectionKind.FACE, index=1)

    scene.set_selection(selection)

    assert scene.selection() == selection
    assert scene.active_item_id() == item_id

    scene.set_selection(None)
    assert scene.selection() is None


def test_scene_undo_restores_previous_shape() -> None:
    scene = Scene()
    item_id = scene.add_shape("shape-a")
    scene.undo()
    item_id = scene.add_shape("shape-a")
    scene.replace_shape(item_id, "shape-b")

    assert scene.can_undo() is True
    restored = scene.undo()

    assert restored is not None
    assert scene.get(item_id).shape == "shape-a"


def test_scene_undo_can_remove_added_shape() -> None:
    scene = Scene()
    item_id = scene.add_shape("shape")

    assert item_id in scene
    assert scene.undo() is not None

    assert len(scene) == 0
    assert scene.active_item_id() is None


def test_scene_undo_restores_removed_shape_and_selection() -> None:
    scene = Scene()
    item_id = scene.add_shape("shape")
    selection = SelectionRef(item_id=item_id, kind=SelectionKind.FACE, index=1)
    scene.set_selection(selection)
    scene.undo()
    item_id = scene.add_shape("shape")
    selection = SelectionRef(item_id=item_id, kind=SelectionKind.FACE, index=1)
    scene.set_selection(selection)

    scene.remove(item_id)
    assert len(scene) == 0
    assert scene.selection() is None

    assert scene.undo() is not None
    assert scene.get(item_id).shape == "shape"
    assert scene.selection() == selection


def test_scene_transaction_undo_restores_multi_step_change() -> None:
    scene = Scene()
    host_id = scene.add_shape("host-a")
    profile_id = scene.add_shape("profile")
    scene.undo()
    scene.undo()
    host_id = scene.add_shape("host-a")
    profile_id = scene.add_shape("profile")

    with scene.transaction():
        scene.replace_shape(host_id, "host-b")
        scene.remove(profile_id)
        scene.set_active_item(host_id)

    assert scene.get(host_id).shape == "host-b"
    assert profile_id not in scene

    assert scene.undo() is not None
    assert scene.get(host_id).shape == "host-a"
    assert scene.get(profile_id).shape == "profile"
