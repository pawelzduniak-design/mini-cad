from __future__ import annotations

from cad_app.scene import Scene
from cad_app.types import SelectionKind, SelectionRef


def test_scene_tracks_active_selection_and_undo_redo() -> None:
    scene = Scene()
    first_id = scene.add_shape("first", meta={"kind": "body"})
    second_id = scene.add_shape("second", meta={"kind": "body"})

    scene.set_selection(SelectionRef(second_id, SelectionKind.OBJECT, 0))

    assert len(scene) == 2
    assert scene.active_item_id() == second_id
    assert scene.selection() == SelectionRef(second_id, SelectionKind.OBJECT, 0)

    removed = scene.remove(second_id)
    assert removed.item_id == second_id
    assert second_id not in scene
    assert scene.selection() is None

    scene.undo()
    assert second_id in scene
    assert scene.active_item_id() == second_id

    scene.redo()
    assert second_id not in scene
    assert first_id in scene


def test_scene_tracks_multi_selection_refs() -> None:
    scene = Scene()
    first_id = scene.add_shape("first", meta={"kind": "body"})
    second_id = scene.add_shape("second", meta={"kind": "body"})
    selections = (
        SelectionRef(first_id, SelectionKind.OBJECT, 0),
        SelectionRef(second_id, SelectionKind.OBJECT, 0),
        SelectionRef(first_id, SelectionKind.OBJECT, 0),
    )

    scene.set_selections(selections)

    assert scene.selection_refs() == selections[:2]
    assert scene.selection() == selections[0]
    assert scene.active_item_id() == first_id

    scene.remove(first_id)

    assert scene.selection_refs() == (selections[1],)
    assert scene.selection() == selections[1]
    assert scene.active_item_id() == second_id


def test_scene_transaction_rolls_back_on_failure() -> None:
    scene = Scene()
    item_id = scene.add_shape("shape", meta={"kind": "body"})

    try:
        with scene.transaction():
            scene.replace_shape(item_id, "changed")
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert scene.get(item_id).shape == "shape"
