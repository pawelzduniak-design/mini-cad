from importlib.util import find_spec

import pytest

from tests.cad_safety.contracts import (
    COMMAND_CONTRACTS,
    MATRIX_COMMANDS,
    MATRIX_SELECTION_TYPES,
)
from tests.cad_safety.harness import SafetyHarness
from tests.cad_safety.invariants import (
    assert_model_changed,
    assert_model_unchanged,
    assert_modification_has_undo,
    assert_scene_valid,
)
from tests.fixtures.model_factory import cad_safety_scene


def _skip_without_cad_dependencies() -> None:
    if find_spec("OCP") is None:
        pytest.skip("OCP is not installed in the active environment.")


@pytest.mark.parametrize("command", MATRIX_COMMANDS)
@pytest.mark.parametrize("selection_type", MATRIX_SELECTION_TYPES)
def test_command_contract_matrix(command, selection_type) -> None:
    _skip_without_cad_dependencies()

    contract = COMMAND_CONTRACTS[command]
    harness = SafetyHarness(cad_safety_scene())
    harness.select(selection_type)

    result = harness.execute(command)

    assert_scene_valid(result.after)
    if not contract.allows(selection_type):
        assert result.status == "blocked"
        assert_model_unchanged(
            result.before,
            result.after,
            f"{command.value} mutated model for forbidden {selection_type.value}",
        )
        return

    assert result.status in {"success", "failed_safe"}
    if result.status == "failed_safe":
        assert_model_unchanged(
            result.before,
            result.after,
            f"{command.value} failed unsafely for {selection_type.value}",
        )
        return

    if contract.modifies_model:
        assert_model_changed(
            result.before,
            result.after,
            f"{command.value} did not modify model for allowed selection",
        )
    if contract.requires_undo_snapshot:
        assert_modification_has_undo(result.before, result.after)


def test_delete_object_contract_blocks_face_selection() -> None:
    _skip_without_cad_dependencies()

    from tests.cad_safety.contracts import CommandType, SelectionType

    harness = SafetyHarness(cad_safety_scene())
    harness.select(SelectionType.FACE)

    result = harness.execute(CommandType.DELETE_OBJECT)

    assert result.status == "blocked"
    assert result.after.body_count == result.before.body_count
    assert_model_unchanged(
        result.before,
        result.after,
        "Delete Object must not delete the owner body for face selection.",
    )
