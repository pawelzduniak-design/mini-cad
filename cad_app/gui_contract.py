"""Machine-checkable GUI contract for core CAD contexts."""

from __future__ import annotations

from cad_app.ui_menu import (
    BODY_ACTIONS,
    BOOLEAN_ACTIONS,
    EDGE_MODIFY_ACTIONS,
    FACE_MODIFY_ACTIONS,
    SELECT_ACTIONS,
    VERTEX_MODIFY_ACTIONS,
)

LAYOUT_REGIONS = (
    "top_bar",
    "left_menu",
    "context_tool_panel",
    "viewport",
    "bottom_status_bar",
)

AVAILABLE_FACE_ACTIONS = FACE_MODIFY_ACTIONS
SELECT_VERTEX_ACTIONS = (*SELECT_ACTIONS, *VERTEX_MODIFY_ACTIONS)
SELECT_EDGE_ACTIONS = (*SELECT_ACTIONS, *EDGE_MODIFY_ACTIONS)
SELECT_FACE_ACTIONS = (*SELECT_ACTIONS, *AVAILABLE_FACE_ACTIONS)
SELECT_BODY_ACTIONS = (*SELECT_ACTIONS, *BODY_ACTIONS, "set_boolean_target")

_CONTEXT_TOOL_ACTIONS = tuple(
    dict.fromkeys(
        (
            *SELECT_ACTIONS,
            *BODY_ACTIONS,
            *BOOLEAN_ACTIONS,
            *AVAILABLE_FACE_ACTIONS,
            *EDGE_MODIFY_ACTIONS,
            *VERTEX_MODIFY_ACTIONS,
        )
    )
)


def _forbidden_context_actions(*allowed: str) -> tuple[str, ...]:
    allowed_set = set(allowed)
    return tuple(
        action_name
        for action_name in _CONTEXT_TOOL_ACTIONS
        if action_name not in allowed_set
    )


GUI_CONTRACT = {
    "schema": "cad_gui_contract.v1",
    "layout_regions": LAYOUT_REGIONS,
    "contexts": {
        "no_selection": {
            "work_mode": "select",
            "selection_mode": "object",
            "selection_type": "none",
            "active_tool": "idle",
            "context_actions": SELECT_ACTIONS,
            "checked_actions": ("category_select", "select_object", "axis_x"),
            "enabled_actions": SELECT_ACTIONS,
            "disabled_actions": (
                "move",
                "extrude",
                "fillet",
                "chamfer",
                "fillet_chamfer",
                "measure_distance",
            ),
            "action_text": {"move": "Move"},
            "forbidden_context_actions": _forbidden_context_actions(*SELECT_ACTIONS),
        },
        "vertex_selected": {
            "work_mode": "select",
            "selection_mode": "vertex",
            "selection_type": "vertex",
            "active_tool": "idle",
            "context_actions": SELECT_VERTEX_ACTIONS,
            "checked_actions": ("category_select", "select_vertex", "axis_x"),
            "enabled_actions": SELECT_VERTEX_ACTIONS,
            "disabled_actions": (
                "extrude",
                "fillet",
                "chamfer",
                "fillet_chamfer",
                "measure_distance",
            ),
            "action_text": {"move": "Move"},
            "forbidden_context_actions": _forbidden_context_actions(
                *SELECT_VERTEX_ACTIONS
            ),
        },
        "edge_selected": {
            "work_mode": "select",
            "selection_mode": "edge",
            "selection_type": "edge",
            "active_tool": "idle",
            "context_actions": SELECT_EDGE_ACTIONS,
            "checked_actions": ("category_select", "select_edge", "axis_x"),
            "enabled_actions": SELECT_EDGE_ACTIONS,
            "disabled_actions": (
                "extrude",
                "remove_face",
                "circle_boss",
                "circle_cut",
                "fillet",
                "chamfer",
            ),
            "action_text": {"move": "Move", "fillet_chamfer": "Fillet/Chamfer"},
            "forbidden_context_actions": _forbidden_context_actions(
                *SELECT_EDGE_ACTIONS
            ),
        },
        "face_selected": {
            "work_mode": "select",
            "selection_mode": "face",
            "selection_type": "face",
            "active_tool": "idle",
            "context_actions": SELECT_FACE_ACTIONS,
            "checked_actions": ("category_select", "select_face", "axis_x"),
            "enabled_actions": SELECT_FACE_ACTIONS,
            "disabled_actions": (
                "fillet",
                "chamfer",
                "fillet_chamfer",
                "measure_distance",
            ),
            "action_text": {
                "move": "Move",
                "extrude": "Extrude",
            },
            "forbidden_context_actions": _forbidden_context_actions(
                *SELECT_FACE_ACTIONS
            ),
        },
        "body_selected": {
            "work_mode": "select",
            "selection_mode": "object",
            "selection_type": "object",
            "active_tool": "idle",
            "context_actions": SELECT_BODY_ACTIONS,
            "checked_actions": ("category_select", "select_object", "axis_x"),
            "enabled_actions": SELECT_BODY_ACTIONS,
            "disabled_actions": (
                "move_selection",
                "move_selection_normal",
                "extrude",
                "fillet",
                "chamfer",
                "fillet_chamfer",
                "measure_distance",
            ),
            "action_text": {"move": "Move"},
            "forbidden_context_actions": _forbidden_context_actions(
                *SELECT_BODY_ACTIONS,
            ),
        },
    },
}
