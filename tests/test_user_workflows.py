from importlib.util import find_spec

import pytest

from tests.cad_safety.contracts import CommandType, SelectionType
from tests.cad_safety.harness import SafetyHarness
from tests.cad_safety.invariants import (
    assert_model_unchanged,
    assert_scene_valid,
    assert_undo_redo_round_trip,
)
from tests.cad_safety.snapshots import capture_scene_snapshot
from tests.fixtures.model_factory import (
    box_with_cylinder_scene,
    box_with_top_level_scene,
    single_box_scene,
    sketch_profiles_scene,
)


def _skip_without_cad_dependencies() -> None:
    if find_spec("OCP") is None:
        pytest.skip("OCP is not installed in the active environment.")


def test_sketch_rectangle_extrude_face_undo_redo_step(tmp_path) -> None:
    _skip_without_cad_dependencies()

    from cad_app.io_step import export_step

    harness = SafetyHarness(sketch_profiles_scene())
    harness.select(SelectionType.SKETCH_PROFILE)
    profile_result = harness.execute(CommandType.EXTRUDE_PROFILE)
    assert profile_result.status == "success"

    harness.select(SelectionType.FACE)
    face_result = harness.execute(CommandType.EXTRUDE_FACE)
    assert face_result.status == "success"
    assert_scene_valid(face_result.after)

    assert_undo_redo_round_trip(harness.scene, face_result.after)

    active_item_id = harness.scene.active_item_id()
    assert active_item_id is not None
    step_path = tmp_path / "workflow.step"
    export_step(harness.scene.get(active_item_id).shape, step_path)
    assert step_path.exists()
    assert step_path.stat().st_size > 0


def test_box_with_top_level_face_operation_keeps_body_scope() -> None:
    _skip_without_cad_dependencies()

    harness = SafetyHarness(box_with_top_level_scene())
    before = capture_scene_snapshot(harness.scene)
    harness.select(SelectionType.FACE)

    result = harness.execute(CommandType.MOVE_FACE)

    assert result.status == "success"
    assert result.after.body_count == before.body_count
    assert_scene_valid(result.after)


def test_object_delete_and_face_delete_have_different_scope() -> None:
    _skip_without_cad_dependencies()

    harness = SafetyHarness(single_box_scene())
    harness.select(SelectionType.FACE)
    face_delete = harness.execute(CommandType.DELETE_OBJECT)

    assert face_delete.status == "blocked"
    assert face_delete.after.body_count == 1
    assert_model_unchanged(
        face_delete.before,
        face_delete.after,
        "Face selection must not delete the body.",
    )

    harness.select(SelectionType.OBJECT)
    object_delete = harness.execute(CommandType.DELETE_OBJECT)

    assert object_delete.status == "success"
    assert object_delete.after.body_count == 0
    assert harness.scene.undo() is not None
    assert capture_scene_snapshot(harness.scene).body_count == 1


def test_offset_face_is_failed_safe_until_implemented() -> None:
    _skip_without_cad_dependencies()

    harness = SafetyHarness(box_with_cylinder_scene())
    harness.select(SelectionType.FACE)

    result = harness.execute(CommandType.OFFSET_FACE)

    assert result.status == "failed_safe"
    assert_model_unchanged(
        result.before,
        result.after,
        "Unimplemented Offset Face must leave the model unchanged.",
    )
