"""Reusable safety invariants for CAD tests."""

from __future__ import annotations

from cad_app.scene import Scene
from tests.cad_safety.snapshots import ModelSnapshot, capture_scene_snapshot


def assert_scene_valid(snapshot: ModelSnapshot) -> None:
    """Every stored shape must pass BRepCheck."""
    invalid = [shape.item_id for shape in snapshot.shapes if not shape.valid]
    assert not invalid, f"Invalid shapes in scene: {invalid}"


def assert_model_unchanged(
    before: ModelSnapshot,
    after: ModelSnapshot,
    reason: str,
) -> None:
    assert after.fingerprint == before.fingerprint, reason


def assert_model_changed(
    before: ModelSnapshot,
    after: ModelSnapshot,
    reason: str,
) -> None:
    assert after.fingerprint != before.fingerprint, reason


def assert_modification_has_undo(
    before: ModelSnapshot,
    after: ModelSnapshot,
) -> None:
    assert after.undo_depth > before.undo_depth


def assert_undo_redo_round_trip(scene: Scene, expected_after: ModelSnapshot) -> None:
    """Undo must change the model and redo must restore the exact result."""
    undo_result = scene.undo()
    assert undo_result is not None
    after_undo = capture_scene_snapshot(scene)
    assert after_undo.fingerprint != expected_after.fingerprint
    redo_result = scene.redo()
    assert redo_result is not None
    after_redo = capture_scene_snapshot(scene)
    assert after_redo.fingerprint == expected_after.fingerprint
    assert_scene_valid(after_redo)
