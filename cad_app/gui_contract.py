"""Machine-checkable GUI contract for core CAD contexts."""

from __future__ import annotations

from cad_app.ui_menu import (
    BODY_ACTIONS,
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

AVAILABLE_FACE_ACTIONS = tuple(
    action_name for action_name in FACE_MODIFY_ACTIONS if action_name != "offset_face"
)

_CONTEXT_TOOL_ACTIONS = tuple(
    dict.fromkeys(
        (
            *SELECT_ACTIONS,
            *BODY_ACTIONS,
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
                "move_selection",
                "move_selection_normal",
                "extrude",
                "fillet",
                "chamfer",
                "measure_distance",
            ),
            "action_text": {"move_selection": "Move Selection"},
            "forbidden_context_actions": _forbidden_context_actions(*SELECT_ACTIONS),
        },
        "vertex_selected": {
            "work_mode": "modify",
            "selection_mode": "vertex",
            "selection_type": "vertex",
            "active_tool": "idle",
            "context_actions": VERTEX_MODIFY_ACTIONS,
            "checked_actions": ("category_modify", "select_vertex", "axis_x"),
            "enabled_actions": VERTEX_MODIFY_ACTIONS,
            "disabled_actions": (
                "extrude",
                "move_selection_normal",
                "fillet",
                "chamfer",
                "measure_distance",
            ),
            "action_text": {"move_selection": "Move Vertex"},
            "forbidden_context_actions": _forbidden_context_actions(
                *VERTEX_MODIFY_ACTIONS
            ),
        },
        "edge_selected": {
            "work_mode": "modify",
            "selection_mode": "edge",
            "selection_type": "edge",
            "active_tool": "idle",
            "context_actions": EDGE_MODIFY_ACTIONS,
            "checked_actions": ("category_modify", "select_edge", "axis_x"),
            "enabled_actions": EDGE_MODIFY_ACTIONS,
            "disabled_actions": (
                "extrude",
                "move_selection_normal",
                "remove_face",
                "circle_boss",
                "circle_cut",
            ),
            "action_text": {"move_selection": "Move Edge"},
            "forbidden_context_actions": _forbidden_context_actions(
                *EDGE_MODIFY_ACTIONS
            ),
        },
        "face_selected": {
            "work_mode": "modify",
            "selection_mode": "face",
            "selection_type": "face",
            "active_tool": "idle",
            "context_actions": AVAILABLE_FACE_ACTIONS,
            "checked_actions": ("category_modify", "select_face", "axis_x"),
            "enabled_actions": AVAILABLE_FACE_ACTIONS,
            "disabled_actions": ("fillet", "chamfer", "measure_distance"),
            "action_text": {
                "move_selection": "Move Face",
                "start_sketch": "New Sketch (Face Plane)",
            },
            "forbidden_context_actions": _forbidden_context_actions(
                *AVAILABLE_FACE_ACTIONS
            ),
        },
        "body_selected": {
            "work_mode": "transform",
            "selection_mode": "object",
            "selection_type": "object",
            "active_tool": "idle",
            "context_actions": BODY_ACTIONS,
            "checked_actions": ("category_transform", "select_object", "axis_x"),
            "enabled_actions": BODY_ACTIONS,
            "disabled_actions": (
                "move_selection",
                "move_selection_normal",
                "extrude",
                "fillet",
                "chamfer",
                "measure_distance",
            ),
            "action_text": {"move_selection": "Move Selection"},
            "forbidden_context_actions": _forbidden_context_actions(*BODY_ACTIONS),
        },
    },
}
