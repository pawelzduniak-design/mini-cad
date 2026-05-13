from __future__ import annotations

from typing import Any


def count_subshapes(shape: Any, topology: str) -> int:
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID, TopAbs_VERTEX
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    topologies = {
        "edge": TopAbs_EDGE,
        "face": TopAbs_FACE,
        "solid": TopAbs_SOLID,
        "vertex": TopAbs_VERTEX,
    }
    shape_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, topologies[topology], shape_map)
    return shape_map.Extent()


def bounding_box(shape: Any) -> dict[str, float]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return {
        "xmin": xmin,
        "ymin": ymin,
        "zmin": zmin,
        "xmax": xmax,
        "ymax": ymax,
        "zmax": zmax,
        "width": xmax - xmin,
        "depth": ymax - ymin,
        "height": zmax - zmin,
    }


def assert_valid_shape(shape: Any) -> None:
    from OCP.BRepCheck import BRepCheck_Analyzer

    assert not shape.IsNull()
    assert BRepCheck_Analyzer(shape).IsValid()


def scene_fingerprint(scene: Any) -> tuple[tuple[str, str, tuple[float, ...]], ...]:
    return tuple(
        sorted(
            (
                item.item_id,
                str(item.meta.get("kind", "")),
                _rounded_box(item.shape),
            )
            for item in scene
        )
    )


def _rounded_box(shape: Any) -> tuple[float, ...]:
    box = bounding_box(shape)
    return tuple(
        round(box[key], 4) for key in ("xmin", "ymin", "zmin", "xmax", "ymax", "zmax")
    )
