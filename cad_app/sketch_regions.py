"""Boolean region helpers for planar sketch profiles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cad_app.commands import UnsupportedTopologyError, validate_shape

if TYPE_CHECKING:
    from OCP.TopoDS import TopoDS_Face


@dataclass(frozen=True)
class ProfileRegionSplit:
    """Non-overlapping planar regions produced by two sketch profiles."""

    base_regions: tuple["TopoDS_Face", ...]
    common_regions: tuple["TopoDS_Face", ...]
    tool_regions: tuple["TopoDS_Face", ...]

    @property
    def has_intersection(self) -> bool:
        return bool(self.common_regions)


def split_profile_regions(
    base_profile: TopoDS_Face,
    tool_profile: TopoDS_Face,
    *,
    area_tolerance: float = 1e-6,
) -> ProfileRegionSplit:
    """Split two coplanar sketch profiles into selectable planar regions."""
    validate_shape(base_profile)
    validate_shape(tool_profile)

    common_regions = _boolean_profile_faces(
        "common",
        base_profile,
        tool_profile,
        area_tolerance=area_tolerance,
    )
    if not common_regions:
        return ProfileRegionSplit(
            base_regions=(base_profile,),
            common_regions=(),
            tool_regions=(tool_profile,),
        )

    return ProfileRegionSplit(
        base_regions=tuple(
            _boolean_profile_faces(
                "cut",
                base_profile,
                tool_profile,
                area_tolerance=area_tolerance,
            )
        ),
        common_regions=tuple(common_regions),
        tool_regions=tuple(
            _boolean_profile_faces(
                "cut",
                tool_profile,
                base_profile,
                area_tolerance=area_tolerance,
            )
        ),
    )


def subtract_profile_regions(
    profile: TopoDS_Face,
    cutters: tuple["TopoDS_Face", ...],
    *,
    area_tolerance: float = 1e-6,
) -> tuple["TopoDS_Face", ...]:
    """Subtract multiple coplanar profiles and return remaining face regions."""
    validate_shape(profile)
    remaining = (profile,)
    for cutter in cutters:
        validate_shape(cutter)
        next_remaining: list[TopoDS_Face] = []
        for face in remaining:
            next_remaining.extend(
                _boolean_profile_faces(
                    "cut",
                    face,
                    cutter,
                    area_tolerance=area_tolerance,
                )
            )
        remaining = tuple(next_remaining)
        if not remaining:
            break
    return remaining


def _boolean_profile_faces(
    operation: str,
    first,
    second,
    *,
    area_tolerance: float,
) -> list["TopoDS_Face"]:
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    if operation == "cut":
        builder = BRepAlgoAPI_Cut(first, second)
    elif operation == "common":
        builder = BRepAlgoAPI_Common(first, second)
    else:
        raise ValueError(f"Unsupported profile boolean operation: {operation}")
    builder.Build()
    if not builder.IsDone():
        raise UnsupportedTopologyError(f"Sketch profile {operation} failed.")

    faces = []
    explorer = TopExp_Explorer(builder.Shape(), TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        if _profile_area(face) > area_tolerance:
            validate_shape(face)
            faces.append(face)
        explorer.Next()
    return faces


def _profile_area(profile) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(profile, props)
    return abs(float(props.Mass()))
