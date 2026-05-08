"""Command contracts for CAD safety tests."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SelectionType(str, Enum):
    """Selection categories used by command contracts."""

    NONE = "none"
    OBJECT = "object"
    FACE = "face"
    EDGE = "edge"
    VERTEX = "vertex"
    SKETCH_PROFILE = "sketch_profile"
    SKETCH_ENTITY = "sketch_entity"


class CommandType(str, Enum):
    """CAD command categories covered by safety tests."""

    CREATE_BODY = "create_body"
    EXTRUDE_PROFILE = "extrude_profile"
    EXTRUDE_FACE = "extrude_face"
    MOVE_OBJECT = "move_object"
    MOVE_FACE = "move_face"
    MOVE_EDGE = "move_edge"
    OFFSET_FACE = "offset_face"
    DELETE_OBJECT = "delete_object"
    DELETE_FACE = "delete_face"
    REMOVE_FEATURE = "remove_feature"
    BOOLEAN_UNION = "boolean_union"
    BOOLEAN_CUT = "boolean_cut"
    BOOLEAN_INTERSECT = "boolean_intersect"


@dataclass(frozen=True)
class CommandContract:
    """Selection and mutation contract for one command."""

    command: CommandType
    allowed_selections: frozenset[SelectionType]
    modifies_model: bool
    destructive: bool
    requires_undo_snapshot: bool
    implemented: bool = True
    description: str = ""

    def allows(self, selection_type: SelectionType) -> bool:
        return selection_type in self.allowed_selections


COMMAND_CONTRACTS: dict[CommandType, CommandContract] = {
    CommandType.CREATE_BODY: CommandContract(
        command=CommandType.CREATE_BODY,
        allowed_selections=frozenset({SelectionType.NONE}),
        modifies_model=True,
        destructive=False,
        requires_undo_snapshot=True,
        description="Create a new independent body.",
    ),
    CommandType.EXTRUDE_PROFILE: CommandContract(
        command=CommandType.EXTRUDE_PROFILE,
        allowed_selections=frozenset({SelectionType.SKETCH_PROFILE}),
        modifies_model=True,
        destructive=False,
        requires_undo_snapshot=True,
        description="Turn a closed sketch profile into a body.",
    ),
    CommandType.EXTRUDE_FACE: CommandContract(
        command=CommandType.EXTRUDE_FACE,
        allowed_selections=frozenset({SelectionType.FACE}),
        modifies_model=True,
        destructive=False,
        requires_undo_snapshot=True,
        description="Push or pull a selected model face.",
    ),
    CommandType.MOVE_OBJECT: CommandContract(
        command=CommandType.MOVE_OBJECT,
        allowed_selections=frozenset({SelectionType.OBJECT}),
        modifies_model=True,
        destructive=False,
        requires_undo_snapshot=True,
        description="Translate the selected body as a whole.",
    ),
    CommandType.MOVE_FACE: CommandContract(
        command=CommandType.MOVE_FACE,
        allowed_selections=frozenset({SelectionType.FACE}),
        modifies_model=True,
        destructive=False,
        requires_undo_snapshot=True,
        description="Move the selected face without falling back to body move.",
    ),
    CommandType.MOVE_EDGE: CommandContract(
        command=CommandType.MOVE_EDGE,
        allowed_selections=frozenset({SelectionType.EDGE}),
        modifies_model=True,
        destructive=False,
        requires_undo_snapshot=True,
        description="Move the selected edge on supported planar solids.",
    ),
    CommandType.OFFSET_FACE: CommandContract(
        command=CommandType.OFFSET_FACE,
        allowed_selections=frozenset({SelectionType.FACE}),
        modifies_model=True,
        destructive=False,
        requires_undo_snapshot=True,
        implemented=False,
        description="Offset a selected face. Unimplemented commands must fail safe.",
    ),
    CommandType.DELETE_OBJECT: CommandContract(
        command=CommandType.DELETE_OBJECT,
        allowed_selections=frozenset({SelectionType.OBJECT}),
        modifies_model=True,
        destructive=True,
        requires_undo_snapshot=True,
        description="Delete only a selected whole body.",
    ),
    CommandType.DELETE_FACE: CommandContract(
        command=CommandType.DELETE_FACE,
        allowed_selections=frozenset({SelectionType.FACE}),
        modifies_model=True,
        destructive=True,
        requires_undo_snapshot=True,
        implemented=False,
        description="Delete only a selected face. Never delete the owner body.",
    ),
    CommandType.REMOVE_FEATURE: CommandContract(
        command=CommandType.REMOVE_FEATURE,
        allowed_selections=frozenset({SelectionType.OBJECT, SelectionType.FACE}),
        modifies_model=True,
        destructive=True,
        requires_undo_snapshot=True,
        implemented=False,
        description="Remove a feature when feature history exists.",
    ),
    CommandType.BOOLEAN_UNION: CommandContract(
        command=CommandType.BOOLEAN_UNION,
        allowed_selections=frozenset({SelectionType.OBJECT}),
        modifies_model=True,
        destructive=True,
        requires_undo_snapshot=True,
        description="Fuse two selected body objects.",
    ),
    CommandType.BOOLEAN_CUT: CommandContract(
        command=CommandType.BOOLEAN_CUT,
        allowed_selections=frozenset({SelectionType.OBJECT}),
        modifies_model=True,
        destructive=True,
        requires_undo_snapshot=True,
        description="Cut a tool body from a target body.",
    ),
    CommandType.BOOLEAN_INTERSECT: CommandContract(
        command=CommandType.BOOLEAN_INTERSECT,
        allowed_selections=frozenset({SelectionType.OBJECT}),
        modifies_model=True,
        destructive=True,
        requires_undo_snapshot=True,
        description="Keep only the overlap between two body objects.",
    ),
}

MATRIX_SELECTION_TYPES = tuple(SelectionType)
MATRIX_COMMANDS = tuple(CommandType)
