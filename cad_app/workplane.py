"""Local face workplanes for lightweight profile tools."""

from __future__ import annotations

from dataclasses import dataclass

from cad_app.commands import UnsupportedTopologyError


@dataclass(frozen=True)
class Workplane:
    origin: object
    normal: object
    x_direction: object
    y_direction: object

    @classmethod
    def world_xy(cls):
        from OCP.gp import gp_Dir, gp_Pnt

        return cls(
            origin=gp_Pnt(0.0, 0.0, 0.0),
            normal=gp_Dir(0.0, 0.0, 1.0),
            x_direction=gp_Dir(1.0, 0.0, 0.0),
            y_direction=gp_Dir(0.0, 1.0, 0.0),
        )

    @classmethod
    def from_face(cls, face):
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.BRepGProp import BRepGProp
        from OCP.GeomAbs import GeomAbs_Plane
        from OCP.gp import gp_Dir
        from OCP.GProp import GProp_GProps
        from OCP.TopAbs import TopAbs_REVERSED

        surface = BRepAdaptor_Surface(face)
        if surface.GetType() != GeomAbs_Plane:
            raise UnsupportedTopologyError("Only planar faces define workplanes.")

        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        origin = props.CentreOfMass()

        plane = surface.Plane()
        normal = plane.Axis().Direction()
        if face.Orientation() == TopAbs_REVERSED:
            normal = gp_Dir(-normal.X(), -normal.Y(), -normal.Z())

        x_direction = plane.XAxis().Direction()
        y_direction = normal.Crossed(x_direction)
        return cls(
            origin=origin,
            normal=normal,
            x_direction=x_direction,
            y_direction=y_direction,
        )
