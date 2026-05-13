"""Geometry measurement helpers for selected model topology."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from OCP.TopoDS import TopoDS_Edge, TopoDS_Shape


@dataclass(frozen=True)
class EdgeMeasurement:
    length: float
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    midpoint: tuple[float, float, float]
    direction: tuple[float, float, float]
    axis_name: str | None


def edge_measurement(edge: TopoDS_Edge) -> EdgeMeasurement:
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopoDS import TopoDS

    edge = TopoDS.Edge_s(edge)
    curve = BRepAdaptor_Curve(edge)
    first = curve.FirstParameter()
    last = curve.LastParameter()
    start = _point_tuple(curve.Value(first))
    end = _point_tuple(curve.Value(last))
    midpoint = _point_tuple(curve.Value((first + last) * 0.5))

    props = GProp_GProps()
    BRepGProp.LinearProperties_s(edge, props)
    length = props.Mass()
    if length <= 1e-7:
        length = math.dist(start, end)

    direction = _direction(start, end)
    return EdgeMeasurement(
        length=length,
        start=start,
        end=end,
        midpoint=midpoint,
        direction=direction,
        axis_name=_dominant_axis(direction),
    )


def axis_aligned_box_dimensions(
    shape: TopoDS_Shape,
) -> tuple[float, float, float, tuple[float, float, float]]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    bounds = Bnd_Box()
    BRepBndLib.Add_s(shape, bounds)
    if bounds.IsVoid():
        raise ValueError("Shape bounds are empty.")
    x_min, y_min, z_min, x_max, y_max, z_max = bounds.Get()
    return (
        x_max - x_min,
        y_max - y_min,
        z_max - z_min,
        ((x_min + x_max) * 0.5, (y_min + y_max) * 0.5, z_min),
    )


def _point_tuple(point) -> tuple[float, float, float]:
    return point.X(), point.Y(), point.Z()


def _direction(
    start: tuple[float, float, float],
    end: tuple[float, float, float],
) -> tuple[float, float, float]:
    vector = tuple(
        end_component - start_component
        for start_component, end_component in zip(start, end)
    )
    length = math.sqrt(sum(component * component for component in vector))
    if length <= 1e-7:
        return 0.0, 0.0, 0.0
    return tuple(component / length for component in vector)


def _dominant_axis(
    direction: tuple[float, float, float],
    tolerance: float = 0.98,
) -> str | None:
    axes = ("X", "Y", "Z")
    components = [abs(component) for component in direction]
    dominant_index = max(range(3), key=components.__getitem__)
    if components[dominant_index] < tolerance:
        return None
    return axes[dominant_index]
