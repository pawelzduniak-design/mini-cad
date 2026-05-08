from importlib.util import find_spec
from random import Random

import pytest

from tests.cad_safety.contracts import CommandType, SelectionType
from tests.cad_safety.harness import SafetyHarness
from tests.cad_safety.invariants import assert_model_unchanged
from tests.fixtures.model_factory import cad_safety_scene


def _skip_without_cad_dependencies() -> None:
    if find_spec("OCP") is None:
        pytest.skip("OCP is not installed in the active environment.")


def test_random_command_sequences_keep_scene_valid() -> None:
    _skip_without_cad_dependencies()

    rng = Random(20260507)
    harness = SafetyHarness(cad_safety_scene())
    commands = [
        CommandType.CREATE_BODY,
        CommandType.EXTRUDE_FACE,
        CommandType.MOVE_FACE,
        CommandType.MOVE_EDGE,
        CommandType.MOVE_OBJECT,
        CommandType.DELETE_OBJECT,
        CommandType.BOOLEAN_UNION,
        CommandType.BOOLEAN_CUT,
        CommandType.OFFSET_FACE,
    ]
    selections = [
        SelectionType.NONE,
        SelectionType.OBJECT,
        SelectionType.FACE,
        SelectionType.EDGE,
        SelectionType.VERTEX,
        SelectionType.SKETCH_PROFILE,
        SelectionType.SKETCH_ENTITY,
    ]

    for _step in range(50):
        action = rng.choice(["select", "command", "undo", "redo", "clear_selection"])
        if action == "select":
            _safe_select(harness, rng.choice(selections))
        elif action == "command":
            result = harness.execute(rng.choice(commands))
            if result.status in {"blocked", "failed_safe"}:
                assert_model_unchanged(
                    result.before,
                    result.after,
                    "Blocked or failed-safe command mutated the model.",
                )
        elif action == "undo":
            harness.scene.undo()
        elif action == "redo":
            harness.scene.redo()
        else:
            harness.scene.set_selection(None)
        harness.assert_global_invariants()


def _safe_select(harness: SafetyHarness, selection_type: SelectionType) -> None:
    try:
        harness.select(selection_type)
    except ValueError:
        harness.scene.set_selection(None)
