"""Execution harness that applies CAD command contracts to real scene commands."""

from __future__ import annotations

from dataclasses import dataclass

from cad_app.commands import (
    CommandError,
    apply_boolean_bodies,
    apply_extrude_face,
    apply_move_edge_controlled,
    apply_move_face_normal,
    apply_move_object,
    top_planar_face_index,
)
from cad_app.engine import make_box
from cad_app.picker import Picker
from cad_app.scene import Scene
from cad_app.sketch import SKETCH_ENTITY_META_KIND, SKETCH_META_KIND, extrude_profile
from cad_app.types import SelectionKind, SelectionRef
from tests.cad_safety.contracts import (
    COMMAND_CONTRACTS,
    CommandContract,
    CommandType,
    SelectionType,
)
from tests.cad_safety.snapshots import ModelSnapshot, capture_scene_snapshot


@dataclass(frozen=True)
class CommandResult:
    """Result of a guarded command execution."""

    command: CommandType
    selection_type: SelectionType
    status: str
    before: ModelSnapshot
    after: ModelSnapshot
    message: str = ""


class SafetyHarness:
    """Run contract-guarded commands against a real Scene."""

    def __init__(self, scene: Scene) -> None:
        self.scene = scene

    def select(self, selection_type: SelectionType) -> None:
        if selection_type == SelectionType.NONE:
            self.scene.set_selection(None)
            return
        if selection_type == SelectionType.SKETCH_PROFILE:
            item_id = self._first_item_id_with_kind(SKETCH_META_KIND)
            self.scene.set_selection(
                SelectionRef(item_id=item_id, kind=SelectionKind.FACE, index=1)
            )
            return
        if selection_type == SelectionType.SKETCH_ENTITY:
            item_id = self._first_item_id_with_kind(SKETCH_ENTITY_META_KIND)
            self.scene.set_selection(
                SelectionRef(item_id=item_id, kind=SelectionKind.EDGE, index=1)
            )
            return

        item_id = self._first_body_item_id()
        if selection_type == SelectionType.OBJECT:
            self.scene.set_selection(
                SelectionRef(item_id=item_id, kind=SelectionKind.OBJECT, index=0)
            )
            return
        if selection_type == SelectionType.FACE:
            face_index = top_planar_face_index(self.scene.get(item_id).shape)
            self.scene.set_selection(
                SelectionRef(item_id=item_id, kind=SelectionKind.FACE, index=face_index)
            )
            return
        if selection_type == SelectionType.EDGE:
            self.scene.set_selection(
                SelectionRef(item_id=item_id, kind=SelectionKind.EDGE, index=1)
            )
            return
        if selection_type == SelectionType.VERTEX:
            self.scene.set_selection(
                SelectionRef(item_id=item_id, kind=SelectionKind.VERTEX, index=1)
            )
            return
        raise ValueError(f"Unsupported selection type: {selection_type}")

    def execute(self, command: CommandType) -> CommandResult:
        contract = COMMAND_CONTRACTS[command]
        before = capture_scene_snapshot(self.scene)
        selection_type = self.current_selection_type()
        if not contract.allows(selection_type):
            after = capture_scene_snapshot(self.scene)
            return CommandResult(
                command=command,
                selection_type=selection_type,
                status="blocked",
                before=before,
                after=after,
                message="Selection is forbidden by command contract.",
            )
        if not contract.implemented:
            after = capture_scene_snapshot(self.scene)
            return CommandResult(
                command=command,
                selection_type=selection_type,
                status="failed_safe",
                before=before,
                after=after,
                message="Command is not implemented yet.",
            )
        try:
            self._execute_allowed(command, contract)
        except (
            CommandError,
            IndexError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            after = capture_scene_snapshot(self.scene)
            return CommandResult(
                command=command,
                selection_type=selection_type,
                status="failed_safe",
                before=before,
                after=after,
                message=str(exc),
            )
        after = capture_scene_snapshot(self.scene)
        return CommandResult(
            command=command,
            selection_type=selection_type,
            status="success",
            before=before,
            after=after,
        )

    def current_selection_type(self) -> SelectionType:
        selection = self.scene.selection()
        if selection is None:
            return SelectionType.NONE
        meta = self.scene.get(selection.item_id).meta
        if meta.get("kind") == SKETCH_META_KIND:
            return SelectionType.SKETCH_PROFILE
        if meta.get("kind") == SKETCH_ENTITY_META_KIND:
            return SelectionType.SKETCH_ENTITY
        if selection.kind == SelectionKind.OBJECT:
            return SelectionType.OBJECT
        if selection.kind == SelectionKind.FACE:
            return SelectionType.FACE
        if selection.kind == SelectionKind.EDGE:
            return SelectionType.EDGE
        if selection.kind == SelectionKind.VERTEX:
            return SelectionType.VERTEX
        raise ValueError(f"Unsupported selection kind: {selection.kind}")

    def assert_global_invariants(self) -> None:
        from tests.cad_safety.invariants import assert_scene_valid

        assert_scene_valid(capture_scene_snapshot(self.scene))
        selection = self.scene.selection()
        if selection is not None:
            assert selection.item_id in self.scene
            if selection.kind != SelectionKind.OBJECT:
                count = Picker.indexed_map(
                    self.scene.get(selection.item_id).shape,
                    selection.kind,
                ).Extent()
                assert 1 <= selection.index <= count

    def _execute_allowed(
        self,
        command: CommandType,
        contract: CommandContract,
    ) -> None:
        if command == CommandType.CREATE_BODY:
            body_count = capture_scene_snapshot(self.scene).body_count
            self.scene.add_shape(
                make_box(60.0, 40.0, 20.0),
                meta={"kind": "body", "source": f"harness_box_{body_count + 1}"},
            )
            return

        selection = self.scene.selection()
        if selection is None:
            raise ValueError(f"{contract.command.value} requires a selection.")

        if command == CommandType.DELETE_OBJECT:
            if selection.kind != SelectionKind.OBJECT:
                raise ValueError("Delete object requires object selection.")
            self.scene.remove(selection.item_id)
            return
        if command == CommandType.MOVE_OBJECT:
            if selection.kind != SelectionKind.OBJECT:
                raise ValueError("Move object requires object selection.")
            apply_move_object(self.scene, selection.item_id, 8.0, 0.0, 0.0)
            return
        if command == CommandType.EXTRUDE_FACE:
            apply_extrude_face(self.scene, selection.item_id, selection.index, 8.0)
            return
        if command == CommandType.MOVE_FACE:
            apply_move_face_normal(self.scene, selection.item_id, selection.index, 6.0)
            return
        if command == CommandType.MOVE_EDGE:
            apply_move_edge_controlled(
                self.scene,
                selection.item_id,
                selection.index,
                0.0,
                0.0,
                4.0,
            )
            return
        if command == CommandType.EXTRUDE_PROFILE:
            scene_object = self.scene.get(selection.item_id)
            result = extrude_profile(scene_object.shape, 12.0)
            self.scene.replace_shape(
                selection.item_id,
                result,
                meta={"kind": "body", "source": "harness_profile_extrude"},
            )
            self.scene.set_selection(
                SelectionRef(
                    item_id=selection.item_id,
                    kind=SelectionKind.OBJECT,
                    index=0,
                )
            )
            return
        if command in {
            CommandType.BOOLEAN_UNION,
            CommandType.BOOLEAN_CUT,
            CommandType.BOOLEAN_INTERSECT,
        }:
            operation = {
                CommandType.BOOLEAN_UNION: "union",
                CommandType.BOOLEAN_CUT: "subtract",
                CommandType.BOOLEAN_INTERSECT: "intersect",
            }[command]
            target_item_id = self._first_other_body_item_id(selection.item_id)
            apply_boolean_bodies(
                self.scene,
                target_item_id,
                selection.item_id,
                operation,
            )
            return
        raise ValueError(f"Unsupported harness command: {command.value}")

    def _first_body_item_id(self) -> str:
        for item in self.scene:
            if item.meta.get("kind") not in {SKETCH_META_KIND, SKETCH_ENTITY_META_KIND}:
                return item.item_id
        raise ValueError("Scene contains no body item.")

    def _first_other_body_item_id(self, item_id: str) -> str:
        for item in self.scene:
            if item.item_id == item_id:
                continue
            if item.meta.get("kind") not in {SKETCH_META_KIND, SKETCH_ENTITY_META_KIND}:
                return item.item_id
        raise ValueError("Boolean operation requires a second body.")

    def _first_item_id_with_kind(self, kind: str) -> str:
        for item in self.scene:
            if item.meta.get("kind") == kind:
                return item.item_id
        raise ValueError(f"Scene contains no {kind} item.")
