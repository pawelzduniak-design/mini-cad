"""Shared types and enums."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SelectionKind(str, Enum):
    """Selectable topological subshape kinds."""

    OBJECT = "object"
    FACE = "face"
    EDGE = "edge"
    VERTEX = "vertex"


class OperationState(str, Enum):
    """User-visible operation state for UI safety checks."""

    IDLE = "idle"
    SELECTING = "selecting"
    DRAWING_SKETCH = "drawing_sketch"
    PREVIEWING_EXTRUDE = "previewing_extrude"
    DRAGGING_TRANSFORM = "dragging_transform"
    COMMAND_PENDING = "command_pending"
    COMMAND_EXECUTING = "command_executing"


@dataclass(frozen=True)
class SceneObject:
    """Domain object stored by Scene."""

    item_id: str
    shape: Any
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SelectionRef:
    """Stable selection reference returned by Picker."""

    item_id: str
    kind: SelectionKind
    index: int


@dataclass(frozen=True)
class UIState:
    """Stable snapshot of UI state for non-visual contract tests."""

    work_mode: str
    selection_mode: str
    selection_type: str
    active_tool: str
    active_operation: OperationState
    context_actions: tuple[str, ...]
    status_text: str
    hint_text: str
    overlay_visible: bool
    overlay_text: str
    manipulator_visible: bool
    right_panel_context: str
