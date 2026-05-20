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
        return cls._from_face(face, anchor="centroid")

    @classmethod
    def from_face_corner(cls, face):
        """Like :meth:`from_face` but anchors the origin at the
        bottom-left corner of the face's bounding box in UV space.

        Reason: with centroid-anchored workplanes a sketch dimension
        like "X=20 mm" maps to a UV offset measured from the face
        centre, which moves whenever the face is re-trimmed by an
        adjacent feature (e.g. after a boolean union splits the top
        face into an L-shape). Corner-anchored workplanes give users
        a stable origin they can measure from in absolute mm.
        """
        return cls._from_face(face, anchor="corner")

    @classmethod
    def _from_face(cls, face, *, anchor: str):
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.BRepGProp import BRepGProp
        from OCP.GeomAbs import GeomAbs_Plane
        from OCP.gp import gp_Dir, gp_Pnt
        from OCP.GProp import GProp_GProps
        from OCP.TopAbs import TopAbs_REVERSED

        surface = BRepAdaptor_Surface(face)
        if surface.GetType() != GeomAbs_Plane:
            raise UnsupportedTopologyError("Only planar faces define workplanes.")

        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        centroid = props.CentreOfMass()

        plane = surface.Plane()
        normal = plane.Axis().Direction()
        if face.Orientation() == TopAbs_REVERSED:
            normal = gp_Dir(-normal.X(), -normal.Y(), -normal.Z())

        x_direction = plane.XAxis().Direction()
        y_direction = normal.Crossed(x_direction)

        if anchor == "centroid":
            origin = centroid
        elif anchor == "corner":
            origin = _face_uv_corner(face, plane, x_direction, y_direction)
        else:
            raise ValueError(f"Unsupported workplane anchor: {anchor!r}")

        # Sanity: make sure we return a real gp_Pnt, not a typed-alias.
        if not isinstance(origin, gp_Pnt):
            origin = gp_Pnt(origin.X(), origin.Y(), origin.Z())

        return cls(
            origin=origin,
            normal=normal,
            x_direction=x_direction,
            y_direction=y_direction,
        )


def _face_uv_corner(face, plane, x_direction, y_direction):
    """Find the face vertex with the smallest U,V coords on the plane
    and return its world-space gp_Pnt. The plane origin is implicit in
    the X/Y axes; we measure each vertex's distance along x_direction
    and y_direction from the plane's location and pick the one with
    the smallest (u, v)."""
    from OCP.BRep import BRep_Tool
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_VERTEX
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape

    plane_location = plane.Location()
    px, py, pz = plane_location.X(), plane_location.Y(), plane_location.Z()
    ux, uy, uz = x_direction.X(), x_direction.Y(), x_direction.Z()
    vx, vy, vz = y_direction.X(), y_direction.Y(), y_direction.Z()

    vmap = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(face, TopAbs_VERTEX, vmap)
    best = None
    for index in range(1, vmap.Extent() + 1):
        vertex = TopoDS.Vertex_s(vmap.FindKey(index))
        point = BRep_Tool.Pnt_s(vertex)
        dx, dy, dz = point.X() - px, point.Y() - py, point.Z() - pz
        u = dx * ux + dy * uy + dz * uz
        v = dx * vx + dy * vy + dz * vz
        if best is None or (u + v) < (best[0] + best[1]):
            best = (u, v, point.X(), point.Y(), point.Z())
    if best is None:
        # Empty face: fall back to plane origin.
        return gp_Pnt(px, py, pz)
    return gp_Pnt(best[2], best[3], best[4])
