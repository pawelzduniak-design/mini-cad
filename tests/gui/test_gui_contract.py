from __future__ import annotations

import json

import pytest

from cad_app.gui_contract import GUI_CONTRACT
from tests.conftest import require_gui_enabled, require_ocp
from tests.gui.helpers import apply_contract_context, create_box_contract_window


def _context_panel_actions(exported: dict) -> list[str]:
    return exported["context_tool_panel"]["actions"]


def _assert_expected_context(exported: dict, expected: dict) -> None:
    state = exported["state"]
    assert state["work_mode"] == expected["work_mode"]
    assert state["selection_mode"] == expected["selection_mode"]
    assert state["selection_type"] == expected["selection_type"]
    assert state["active_tool"] == expected["active_tool"]
    assert state["context_actions"] == list(expected["context_actions"])
    assert _context_panel_actions(exported) == list(expected["context_actions"])

    for action_name in expected["enabled_actions"]:
        action = exported["actions"][action_name]
        assert action["enabled"], action_name
        assert action["in_context_tool_panel"], action_name
        assert action["button_object_name"], action_name

    for action_name in expected["disabled_actions"]:
        assert not exported["actions"][action_name]["enabled"], action_name

    for action_name in expected["checked_actions"]:
        assert exported["actions"][action_name]["checked"], action_name

    for action_name, text in expected["action_text"].items():
        assert exported["actions"][action_name]["text"] == text

    panel_actions = set(_context_panel_actions(exported))
    for action_name in expected["forbidden_context_actions"]:
        assert action_name not in panel_actions, action_name


def test_export_ui_state_is_json_serializable_and_names_layout_regions(qapp) -> None:
    require_ocp()

    fixture = create_box_contract_window()
    exported = fixture.main_window.export_ui_state()

    json.dumps(exported, sort_keys=True)

    assert exported["schema"] == "cad_gui_state.v1"
    assert set(exported) == {
        "schema",
        "state",
        "regions",
        "actions",
        "context_tool_panel",
        "hud",
    }
    for region_name in GUI_CONTRACT["layout_regions"]:
        region = exported["regions"][region_name]
        assert region["present"], region_name
        assert region["object_name"] == region_name
        assert region["visible"], region_name
        assert region["enabled"], region_name

    for region_name in ("top_bar", "left_menu", "context_tool_panel"):
        for action in exported["regions"][region_name]["actions"]:
            assert action["button_object_name"], action


@pytest.mark.parametrize("context_name", GUI_CONTRACT["contexts"])
def test_exported_ui_state_matches_gui_contract(context_name: str, qapp) -> None:
    require_ocp()

    fixture = create_box_contract_window()
    exported = apply_contract_context(fixture, context_name)

    _assert_expected_context(exported, GUI_CONTRACT["contexts"][context_name])


def test_edge_move_tool_exports_useful_active_status_and_hint(qapp) -> None:
    require_ocp()

    fixture = create_box_contract_window()
    exported = apply_contract_context(fixture, "edge_selected")
    assert exported["actions"]["move_selection"]["enabled"]
    assert exported["actions"]["move_selection"]["text"] == "Move Edge"

    fixture.main_window.actions["move_selection"].trigger()
    exported = fixture.main_window.export_ui_state()

    assert exported["state"]["active_tool"] == "move"
    assert exported["state"]["active_operation"] == "command_pending"
    assert exported["context_tool_panel"]["actions"] == [
        "move_selection",
        "cancel_tool",
    ]
    assert exported["actions"]["cancel_tool"]["enabled"]
    assert "move edge" in exported["state"]["status_text"].lower()
    assert "drag" in exported["state"]["hint_text"].lower()
    assert exported["hud"]["hint"]["text"] == exported["state"]["hint_text"]


@pytest.mark.gui
def test_main_layout_visual_snapshot_smoke(qapp, tmp_path) -> None:
    require_gui_enabled()

    from PySide6.QtTest import QTest

    fixture = create_box_contract_window()
    main_window = fixture.main_window
    window = main_window.window
    widget = main_window.viewer_widget
    viewer = main_window.viewer
    window.resize(960, 640)
    window.show()
    widget.setFocus()

    try:
        for _ in range(80):
            qapp.processEvents()
            if viewer.is_initialized and widget._initial_scene_displayed:
                break
            QTest.qWait(50)

        snapshot = window.grab()
        snapshot_path = tmp_path / "main_layout_snapshot.png"
        assert snapshot.save(str(snapshot_path))
        assert snapshot_path.exists()
        assert snapshot.width() >= 900
        assert snapshot.height() >= 600

        exported = main_window.export_ui_state()
        for region_name in GUI_CONTRACT["layout_regions"]:
            assert exported["regions"][region_name]["present"], region_name
    finally:
        window.close()
        viewer.close()
        qapp.processEvents()
