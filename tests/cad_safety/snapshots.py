"""Scene snapshots and model fingerprints for CAD safety tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from cad_app.picker import Picker
from cad_app.scene import Scene
from cad_app.sketch import is_sketch_object
from cad_app.types import SelectionKind


@dataclass(frozen=True)
class ShapeSnapshot:
    """Stable geometric facts for one scene item."""

    item_id: str
    kind: str
    face_count: int
    edge_count: int
    vertex_count: int
    solid_count: int
    bbox: tuple[float, float, float, float, float, float] | None
    volume: float
    center_of_mass: tuple[float, float, float] | None
    valid: bool


@dataclass(frozen=True)
class ModelSnapshot:
    """Stable scene fingerprint used by safety assertions."""

    body_count: int
    sketch_count: int
    selection: tuple[str, str, int] | None
    active_item_id: str | None
    undo_depth: int
    redo_depth: int
    shapes: tuple[ShapeSnapshot, ...]
    fingerprint: str


def capture_scene_snapshot(scene: Scene) -> ModelSnapshot:
    """Capture topological and undo/redo state for a scene."""
    shapes = tuple(_shape_snapshot(item) for item in scene)
    selection = scene.selection()
    selection_value = (
        None
        if selection is None
        else (selection.item_id, selection.kind.value, selection.index)
    )
    body_count = sum(1 for item in scene if not is_sketch_object(item.meta))
    sketch_count = sum(1 for item in scene if is_sketch_object(item.meta))
    raw = {
        "active_item_id": scene.active_item_id(),
        "body_count": body_count,
        "redo_depth": scene.redo_depth(),
        "selection": selection_value,
        "shapes": [asdict(shape) for shape in shapes],
        "sketch_count": sketch_count,
        "undo_depth": scene.undo_depth(),
    }
    fingerprint = hashlib.sha256(
        json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ModelSnapshot(
        body_count=body_count,
        sketch_count=sketch_count,
        selection=selection_value,
        active_item_id=scene.active_item_id(),
        undo_depth=scene.undo_depth(),
        redo_depth=scene.redo_depth(),
        shapes=shapes,
        fingerprint=fingerprint,
    )


def _shape_snapshot(item: Any) -> ShapeSnapshot:
    shape = item.shape
    return ShapeSnapshot(
        item_id=item.item_id,
        kind=str(item.meta.get("kind", "body")),
        face_count=_count_subshapes(shape, SelectionKind.FACE),
        edge_count=_count_subshapes(shape, SelectionKind.EDGE),
        vertex_count=_count_subshapes(shape, SelectionKind.VERTEX),
        solid_count=_solid_count(shape),
        bbox=_bbox(shape),
        volume=_volume(shape),
        center_of_mass=_center_of_mass(shape),
        valid=_is_valid(shape),
    )


def _count_subshapes(shape: Any, kind: SelectionKind) -> int:
    return Picker.indexed_map(shape, kind).Extent()


def _solid_count(shape: Any) -> int:
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    solid_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_SOLID, solid_map)
    return solid_map.Extent()


def _bbox(shape: Any) -> tuple[float, float, float, float, float, float] | None:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    bounds = Bnd_Box()
    BRepBndLib.Add_s(shape, bounds)
    if bounds.IsVoid():
        return None
    return _rounded_tuple(bounds.Get())


def _volume(shape: Any) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return round(float(props.Mass()), 6)


def _center_of_mass(shape: Any) -> tuple[float, float, float] | None:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    if abs(float(props.Mass())) <= 1e-9:
        BRepGProp.SurfaceProperties_s(shape, props)
    if abs(float(props.Mass())) <= 1e-9:
        return None
    center = props.CentreOfMass()
    return _rounded_tuple((center.X(), center.Y(), center.Z()))


def _is_valid(shape: Any) -> bool:
    from OCP.BRepCheck import BRepCheck_Analyzer

    return bool(not shape.IsNull() and BRepCheck_Analyzer(shape).IsValid())


def _rounded_tuple(values: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(round(float(value), 6) for value in values)
