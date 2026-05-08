"""STEP import/export helpers."""

from __future__ import annotations

from os import PathLike
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from OCP.TopoDS import TopoDS_Shape


class StepIOError(RuntimeError):
    """Raised when STEP import/export fails."""


def export_step(shape: TopoDS_Shape, path: str | PathLike[str]) -> None:
    """Export a TopoDS shape as STEP."""
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    writer = STEPControl_Writer()
    transfer_status = writer.Transfer(shape, STEPControl_AsIs)
    if transfer_status != IFSelect_RetDone:
        raise StepIOError(f"STEP transfer failed: {transfer_status}")

    write_status = writer.Write(str(path))
    if write_status != IFSelect_RetDone:
        raise StepIOError(f"STEP write failed: {write_status}")


def import_step(path: str | PathLike[str]) -> TopoDS_Shape:
    """Import a STEP file as one compound TopoDS shape."""
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_Reader

    reader = STEPControl_Reader()
    read_status = reader.ReadFile(str(path))
    if read_status != IFSelect_RetDone:
        raise StepIOError(f"STEP read failed: {read_status}")

    roots = reader.TransferRoots()
    if roots <= 0:
        raise StepIOError("STEP file contains no transferable roots.")

    shape = reader.OneShape()
    if shape.IsNull():
        raise StepIOError("STEP import produced a null shape.")
    return shape
