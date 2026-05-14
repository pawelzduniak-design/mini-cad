from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cad_app.commands import (
    CommandError,
    supports_move_edge_controlled,
    supports_move_vertex_controlled,
    top_planar_face_index,
)
from cad_app.engine import make_box
from cad_app.main_window import create_main_window
from cad_app.measurement import edge_measurement
from cad_app.picker import Picker
from cad_app.scene import Scene
from cad_app.types import SelectionKind, SelectionRef
from cad_app.viewer import Viewer


@dataclass(frozen=True)
class GuiContractFixture:
    main_window: Any
    item_id: str
    face_index: int
    edge_index: int
    vertex_index: int


def create_box_contract_window() -> GuiContractFixture:
    scene = Scene()
    shape = make_box()
    item_id = scene.add_shape(
        shape,
        meta={"kind": "body", "source": "primitive_box"},
    )
    face_index = top_planar_face_index(shape)
    edge_index = _first_editable_edge_index(scene, item_id)
    vertex_index = _first_movable_vertex_index(scene, item_id)
    main_window = create_main_window(Viewer(), scene)
    return GuiContractFixture(
        main_window=main_window,
        item_id=item_id,
        face_index=face_index,
        edge_index=edge_index,
        vertex_index=vertex_index,
    )


def set_mode(main_window, category: str) -> dict:
    main_window.viewer_widget._set_active_category(category)
    return main_window.export_ui_state()


def clear_selection(main_window, category: str = "select") -> dict:
    main_window.scene.set_selection(None)
    main_window.viewer_widget._selection_kind = SelectionKind.OBJECT
    return set_mode(main_window, category)


def set_selection(
    main_window,
    item_id: str,
    kind: SelectionKind,
    index: int,
    category: str,
) -> dict:
    main_window.scene.set_selection(SelectionRef(item_id, kind, index))
    main_window.viewer_widget._selection_kind = kind
    return set_mode(main_window, category)


def apply_contract_context(fixture: GuiContractFixture, context_name: str) -> dict:
    if context_name == "no_selection":
        return clear_selection(fixture.main_window)
    if context_name == "body_selected":
        return set_selection(
            fixture.main_window,
            fixture.item_id,
            SelectionKind.OBJECT,
            0,
            "transform",
        )
    if context_name == "face_selected":
        return set_selection(
            fixture.main_window,
            fixture.item_id,
            SelectionKind.FACE,
            fixture.face_index,
            "modify",
        )
    if context_name == "edge_selected":
        return set_selection(
            fixture.main_window,
            fixture.item_id,
            SelectionKind.EDGE,
            fixture.edge_index,
            "modify",
        )
    if context_name == "vertex_selected":
        return set_selection(
            fixture.main_window,
            fixture.item_id,
            SelectionKind.VERTEX,
            fixture.vertex_index,
            "modify",
        )
    raise AssertionError(f"Unknown GUI contract context: {context_name}")


def _first_editable_edge_index(scene: Scene, item_id: str) -> int:
    picker = Picker(scene)
    shape = scene.get(item_id).shape
    for index in range(1, picker.count_subshapes(item_id, SelectionKind.EDGE) + 1):
        try:
            measurement = edge_measurement(
                picker.subshape(item_id, SelectionKind.EDGE, index)
            )
            if measurement.axis_name and supports_move_edge_controlled(shape, index):
                return index
        except (CommandError, IndexError, RuntimeError, ValueError):
            continue
    raise AssertionError("No editable box edge found for GUI contract tests.")


def _first_movable_vertex_index(scene: Scene, item_id: str) -> int:
    picker = Picker(scene)
    shape = scene.get(item_id).shape
    for index in range(1, picker.count_subshapes(item_id, SelectionKind.VERTEX) + 1):
        try:
            if supports_move_vertex_controlled(shape, index):
                return index
        except (CommandError, IndexError, RuntimeError, ValueError):
            continue
    raise AssertionError("No movable box vertex found for GUI contract tests.")
