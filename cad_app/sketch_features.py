"""Solid features generated from sketch profiles."""

from __future__ import annotations

import math

from cad_app.command_common import CommandError, cleanup_shape, validate_shape


def revolve_profile(
    profile_face,
    axis_point: tuple[float, float, float],
    axis_direction: tuple[float, float, float],
    angle_degrees: float = 360.0,
    elevation: float = 0.0,
):
    """Revolve a sketch face around an axis into a solid or helical solid."""
    if abs(angle_degrees) < 1e-7:
        raise ValueError("Revolve angle must be non-zero.")
    length = math.sqrt(sum(component * component for component in axis_direction))
    if length < 1e-7:
        raise ValueError("Revolve axis must be non-zero.")

    if abs(elevation) > 1e-7:
        return _helical_revolve_profile(
            profile_face,
            axis_point,
            tuple(component / length for component in axis_direction),
            angle_degrees,
            elevation,
        )

    from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt

    axis = gp_Ax1(
        gp_Pnt(*axis_point),
        gp_Dir(*(component / length for component in axis_direction)),
    )
    builder = BRepPrimAPI_MakeRevol(profile_face, axis, math.radians(angle_degrees))
    if not builder.IsDone():
        raise CommandError("Revolve operation failed.")
    result = builder.Shape()
    validate_shape(result)
    return cleanup_shape(result)


def _helical_revolve_profile(
    profile_face,
    axis_point: tuple[float, float, float],
    unit_axis: tuple[float, float, float],
    angle_degrees: float,
    elevation: float,
):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    from OCP.BRepTools import BRepTools
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
    from OCP.TopAbs import TopAbs_WIRE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    validate_shape(profile_face)
    face = TopoDS.Face_s(profile_face)
    wires = []
    wire_explorer = TopExp_Explorer(face, TopAbs_WIRE)
    while wire_explorer.More():
        wires.append(TopoDS.Wire_s(wire_explorer.Current()))
        wire_explorer.Next()
    if len(wires) != 1:
        raise CommandError(
            "Helical revolve supports profiles without inner loops only."
        )
    base_wire = BRepTools.OuterWire_s(face)
    if base_wire.IsNull():
        raise CommandError("Revolve profile outer wire unavailable.")

    axis_direction = gp_Dir(*unit_axis)
    axis = gp_Ax1(gp_Pnt(*axis_point), axis_direction)
    steps = _helical_revolve_section_count(angle_degrees)
    loft = BRepOffsetAPI_ThruSections(True, False, 1e-6)
    for index in range(steps + 1):
        fraction = index / steps
        rotation = gp_Trsf()
        rotation.SetRotation(axis, math.radians(angle_degrees * fraction))
        translation = gp_Trsf()
        translation.SetTranslation(
            gp_Vec(axis_direction).Multiplied(elevation * fraction)
        )
        transform = translation.Multiplied(rotation)
        wire = TopoDS.Wire_s(
            BRepBuilderAPI_Transform(base_wire, transform, True).Shape()
        )
        loft.AddWire(wire)

    loft.CheckCompatibility(False)
    loft.Build()
    if not loft.IsDone():
        raise CommandError("Helical revolve operation failed.")
    result = loft.Shape()
    validate_shape(result)
    return cleanup_shape(result)


def _helical_revolve_section_count(angle_degrees: float) -> int:
    revolutions = max(abs(angle_degrees) / 360.0, 0.25)
    return max(8, min(240, int(math.ceil(revolutions * 24.0))))
