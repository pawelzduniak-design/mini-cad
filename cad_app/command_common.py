"""Shared command errors and shape validation helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from OCP.TopoDS import TopoDS_Shape


class CommandError(RuntimeError):
    """Base error for direct modeling command failures."""


class InvalidShapeError(CommandError):
    """Raised when input or result shape is topologically invalid."""


class UnsupportedTopologyError(CommandError):
    """Raised when a command receives unsupported topology."""


class OperationFailedError(CommandError):
    """Raised when OCCT refuses to build the requested operation."""


def validate_shape(shape: TopoDS_Shape) -> None:
    """Validate a TopoDS shape using OCCT's BRepCheck analyzer."""
    from OCP.BRepCheck import BRepCheck_Analyzer

    if shape.IsNull():
        raise InvalidShapeError("Shape is null.")
    if not BRepCheck_Analyzer(shape).IsValid():
        raise InvalidShapeError("Shape is not topologically valid.")


def cleanup_shape(shape: TopoDS_Shape) -> TopoDS_Shape:
    """Merge same-domain faces/edges when OCCT can do it safely."""
    validate_shape(shape)

    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain

    unifier = ShapeUpgrade_UnifySameDomain(shape, True, True, False)
    unifier.SetSafeInputMode(True)
    unifier.Build()
    cleaned = unifier.Shape()
    try:
        validate_shape(cleaned)
    except InvalidShapeError:
        return shape
    return cleaned
