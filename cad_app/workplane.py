"""Local face workplanes for lightweight profile tools."""

from __future__ import annotations

from dataclasses import dataclass

from cad_app.commands import UnsupportedTopologyError


@dataclass(frozen=True)
class _FallbackPoint:
    x: float
    y: float
    z: float

    def X(self) -> float:
        return self.x

    def Y(self) -> float:
        return self.y

    def Z(self) -> float:
        return self.z


@dataclass(frozen=True)
class _FallbackDir(_FallbackPoint):
    def Crossed(self, other):
        return _FallbackDir(
            self.y * other.Z() - self.z * other.Y(),
            self.z * other.X() - self.x * other.Z(),
            self.x * other.Y() - self.y * other.X(),
        )


@dataclass(frozen=True)
class Workplane:
    origin: object
    normal: object
    x_direction: object
    y_direction: object

    @classmethod
    def world_xy(cls):
        try:
            from OCP.gp import gp_Dir, gp_Pnt
        except ModuleNotFoundError:
            return cls(
                origin=_FallbackPoint(0.0, 0.0, 0.0),
                normal=_FallbackDir(0.0, 0.0, 1.0),
                x_direction=_FallbackDir(1.0, 0.0, 0.0),
                y_direction=_FallbackDir(0.0, 1.0, 0.0),
            )

        return cls(
            origin=gp_Pnt(0.0, 0.0, 0.0),
            normal=gp_Dir(0.0, 0.0, 1.0),
            x_direction=gp_Dir(1.0, 0.0, 0.0),
            y_direction=gp_Dir(0.0, 1.0, 0.0),
        )

    @classmethod
    def world_yz(cls):
        try:
            from OCP.gp import gp_Dir, gp_Pnt
        except ModuleNotFoundError:
            return cls(
                origin=_FallbackPoint(0.0, 0.0, 0.0),
                normal=_FallbackDir(1.0, 0.0, 0.0),
                x_direction=_FallbackDir(0.0, 1.0, 0.0),
                y_direction=_FallbackDir(0.0, 0.0, 1.0),
            )

        return cls(
            origin=gp_Pnt(0.0, 0.0, 0.0),
            normal=gp_Dir(1.0, 0.0, 0.0),
            x_direction=gp_Dir(0.0, 1.0, 0.0),
            y_direction=gp_Dir(0.0, 0.0, 1.0),
        )

    @classmethod
    def world_xz(cls):
        try:
            from OCP.gp import gp_Dir, gp_Pnt
        except ModuleNotFoundError:
            return cls(
                origin=_FallbackPoint(0.0, 0.0, 0.0),
                normal=_FallbackDir(0.0, -1.0, 0.0),
                x_direction=_FallbackDir(1.0, 0.0, 0.0),
                y_direction=_FallbackDir(0.0, 0.0, 1.0),
            )

        return cls(
            origin=gp_Pnt(0.0, 0.0, 0.0),
            normal=gp_Dir(0.0, -1.0, 0.0),
            x_direction=gp_Dir(1.0, 0.0, 0.0),
            y_direction=gp_Dir(0.0, 0.0, 1.0),
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
