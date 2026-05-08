"""Primitive generation engine."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from OCP.TopoDS import TopoDS_Shape


def make_box(
    width: float = 100.0,
    depth: float = 80.0,
    height: float = 60.0,
) -> TopoDS_Shape:
    """Create a valid direct-modeling box shape."""
    if width <= 0 or depth <= 0 or height <= 0:
        raise ValueError("Box dimensions must be positive.")

    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    return BRepPrimAPI_MakeBox(
        gp_Pnt(-width / 2.0, -depth / 2.0, 0.0),
        gp_Pnt(width / 2.0, depth / 2.0, height),
    ).Shape()


def make_wedge(
    width: float = 100.0,
    depth: float = 80.0,
    height: float = 60.0,
    far_top_height: float | None = None,
) -> TopoDS_Shape:
    """Create a valid wedge with a controlled sloped top."""
    if width <= 0 or depth <= 0 or height <= 0:
        raise ValueError("Wedge dimensions must be positive.")

    resolved_far_top_height = (
        height * 0.35 if far_top_height is None else far_top_height
    )
    if not 0 <= resolved_far_top_height <= height:
        raise ValueError("Wedge far_top_height must be between 0 and height.")

    from build123d import Wedge

    half_width = width / 2.0
    half_height = height / 2.0
    zmax = -half_height + resolved_far_top_height
    shape = Wedge(
        width,
        depth,
        height,
        -half_width,
        -half_height,
        half_width,
        zmax,
    ).wrapped
    return shape
