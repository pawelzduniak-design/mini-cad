"""Parametric feature history for editable direct-modeling steps."""

from __future__ import annotations

import math
from typing import Any
from uuid import uuid4

from cad_app.command_common import CommandError, validate_shape
from cad_app.types import SelectionKind

FEATURE_HISTORY_KEY = "feature_history"


class FeatureRebuildError(CommandError):
    """Raised when a stored feature tree cannot rebuild."""


def feature_history(meta: dict[str, Any]) -> dict[str, Any] | None:
    history = meta.get(FEATURE_HISTORY_KEY)
    if isinstance(history, dict) and isinstance(history.get("steps"), list):
        return history
    return None


def feature_history_steps(meta: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    history = feature_history(meta)
    if history is None:
        return ()
    return tuple(history["steps"])


def capture_extrude_face_step(
    shape: Any,
    face_index: int,
    distance: float,
) -> dict[str, Any]:
    return _feature_step(
        "extrude_face",
        "Extrude Face",
        params={"distance": float(distance)},
        references={"face": _planar_face_reference(shape, face_index)},
    )


def capture_sketch_extrude_step(distance: float) -> dict[str, Any]:
    return _feature_step(
        "sketch_extrude",
        "Sketch Extrude",
        params={"distance": float(distance)},
    )


def capture_sketch_feature_step(profile_face: Any, distance: float) -> dict[str, Any]:
    return _feature_step(
        "sketch_profile_feature",
        "Sketch Feature",
        params={"distance": float(distance)},
        payload={"profile_face": profile_face},
    )


def capture_sketch_revolve_step(
    angle_degrees: float,
    elevation: float,
    axis_point: tuple[float, float, float],
    axis: tuple[float, float, float],
) -> dict[str, Any]:
    return _feature_step(
        "sketch_revolve",
        "Sketch Revolve",
        params={
            "angle_degrees": float(angle_degrees),
            "elevation": float(elevation),
            "axis_point": tuple(float(value) for value in axis_point),
            "axis": tuple(float(value) for value in axis),
        },
    )


def capture_thread_step(
    shape: Any,
    edge_index: int,
    params: dict[str, Any],
) -> dict[str, Any]:
    return _feature_step(
        "thread",
        "Thread",
        params=dict(params),
        references={"edge": _circular_edge_reference(shape, edge_index)},
    )


def create_feature_history(
    meta: dict[str, Any],
    base_shape: Any,
    first_step: dict[str, Any],
) -> dict[str, Any]:
    next_meta = dict(meta)
    next_meta[FEATURE_HISTORY_KEY] = {
        "base_shape": base_shape,
        "steps": [_copied_step(first_step)],
        "status": "ok",
        "error": None,
    }
    return next_meta


def append_feature_step(
    meta: dict[str, Any],
    base_shape: Any,
    step: dict[str, Any],
) -> dict[str, Any]:
    next_meta = dict(meta)
    history = _copied_history(feature_history(meta))
    if history is None:
        history = {
            "base_shape": base_shape,
            "steps": [],
            "status": "ok",
            "error": None,
        }
    history["steps"].append(_copied_step(step))
    history["status"] = "ok"
    history["error"] = None
    next_meta[FEATURE_HISTORY_KEY] = history
    return next_meta


def update_feature_step_parameters(
    meta: dict[str, Any],
    step_index: int,
    params: dict[str, Any],
) -> dict[str, Any]:
    history = _required_history(meta)
    steps = history["steps"]
    if step_index < 0 or step_index >= len(steps):
        raise IndexError(f"Feature step index out of range: {step_index}")
    next_meta = dict(meta)
    next_history = _copied_history(history)
    next_params = dict(next_history["steps"][step_index].get("params", {}))
    next_params.update(params)
    next_history["steps"][step_index]["params"] = next_params
    next_history["status"] = "pending"
    next_history["error"] = None
    next_meta[FEATURE_HISTORY_KEY] = next_history
    return next_meta


def truncate_feature_history(
    meta: dict[str, Any],
    step_count: int,
) -> dict[str, Any]:
    history = _required_history(meta)
    if step_count < 1 or step_count > len(history["steps"]):
        raise IndexError(f"Feature rollback step out of range: {step_count}")
    next_meta = dict(meta)
    next_history = _copied_history(history)
    next_history["steps"] = next_history["steps"][:step_count]
    next_history["status"] = "pending"
    next_history["error"] = None
    next_meta[FEATURE_HISTORY_KEY] = next_history
    return next_meta


def rebuild_shape_from_history(meta: dict[str, Any]) -> Any:
    history = _required_history(meta)
    index = -1
    try:
        shape = history["base_shape"]
        for index, step in enumerate(history["steps"]):
            shape = _apply_feature_step(shape, step)
            validate_shape(shape)
    except Exception as exc:
        raise FeatureRebuildError(
            f"Feature rebuild failed at step {index + 1}: {exc}"
        ) from exc
    return shape


def rebuild_scene_item_feature_history(scene, item_id: str) -> Any:
    scene_object = scene.get(item_id)
    next_shape = rebuild_shape_from_history(scene_object.meta)
    next_meta = dict(scene_object.meta)
    history = _copied_history(_required_history(scene_object.meta))
    history["status"] = "ok"
    history["error"] = None
    next_meta[FEATURE_HISTORY_KEY] = history
    scene.replace_shape(item_id, next_shape, meta=next_meta)
    return next_shape


def update_scene_item_feature_step(
    scene,
    item_id: str,
    step_index: int,
    params: dict[str, Any],
) -> Any:
    scene_object = scene.get(item_id)
    next_meta = update_feature_step_parameters(scene_object.meta, step_index, params)
    next_shape = rebuild_shape_from_history(next_meta)
    ok_meta = _mark_history_ok(next_meta)
    scene.replace_shape(item_id, next_shape, meta=ok_meta)
    return next_shape


def rollback_scene_item_feature_history(
    scene,
    item_id: str,
    step_count: int,
) -> Any:
    scene_object = scene.get(item_id)
    next_meta = truncate_feature_history(scene_object.meta, step_count)
    next_shape = rebuild_shape_from_history(next_meta)
    ok_meta = _mark_history_ok(next_meta)
    scene.replace_shape(item_id, next_shape, meta=ok_meta)
    return next_shape


def mark_scene_item_feature_history_failed(
    scene,
    item_id: str,
    error: str,
) -> None:
    scene_object = scene.get(item_id)
    next_meta = dict(scene_object.meta)
    history = _copied_history(_required_history(scene_object.meta))
    history["status"] = "failed"
    history["error"] = error
    next_meta[FEATURE_HISTORY_KEY] = history
    scene.replace_shape(item_id, scene_object.shape, meta=next_meta)


def feature_step_label(
    step: dict[str, Any],
    index: int,
    *,
    same_kind_index: int | None = None,
) -> str:
    """Build a browser label like ``"3. Sketch Cut 2: 8.00 mm"``.

    ``index`` is the global position in the history. ``same_kind_index``
    is the 1-based position within the same step *kind* (e.g. the
    second cut feature → 2). When provided, it's appended to the name
    so the browser shows ``Sketch Cut 1`` / ``Sketch Cut 2`` instead of
    a single repeated label for every cut.
    """
    name = str(step.get("name") or step.get("kind") or "Feature")
    if step.get("kind") == "sketch_profile_feature":
        # Distinguish add (boss) from subtract (cut/hole/pocket) by the
        # sign of the captured distance — same convention extrude_face
        # uses (positive = fuse outward, negative = cut into body).
        distance = float(step.get("params", {}).get("distance", 0.0))
        name = "Sketch Cut" if distance < 0 else "Sketch Boss"
    if same_kind_index is not None:
        name = f"{name} {same_kind_index}"
    return f"{index}. {name}: {_feature_step_summary(step)}"


def _feature_step(
    kind: str,
    name: str,
    *,
    params: dict[str, Any],
    references: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    step = {
        "id": str(uuid4()),
        "kind": kind,
        "name": name,
        "params": params,
    }
    if references:
        step["references"] = references
    if payload:
        step["payload"] = payload
    return step


def _apply_feature_step(shape: Any, step: dict[str, Any]) -> Any:
    kind = step.get("kind")
    params = dict(step.get("params", {}))
    if kind == "extrude_face":
        from cad_app.commands import extrude_face

        face_index = _resolve_planar_face_reference(
            shape,
            step.get("references", {}).get("face", {}),
        )
        return extrude_face(shape, face_index, float(params["distance"]))
    if kind == "sketch_extrude":
        from cad_app.sketch import extrude_profile

        return extrude_profile(shape, float(params["distance"]))
    if kind == "sketch_profile_feature":
        from cad_app.sketch import apply_profile_feature

        profile_face = step.get("payload", {}).get("profile_face")
        if profile_face is None:
            raise FeatureRebuildError("Sketch feature lost its source profile.")
        return apply_profile_feature(shape, profile_face, float(params["distance"]))
    if kind == "sketch_revolve":
        from cad_app.sketch_features import revolve_profile

        return revolve_profile(
            shape,
            tuple(params["axis_point"]),
            tuple(params["axis"]),
            float(params["angle_degrees"]),
            float(params.get("elevation", 0.0)),
        )
    if kind == "thread":
        from cad_app.commands import thread_edge
        from cad_app.thread_specs import (
            normalized_thread_parameters,
            validate_thread_edge_profile,
        )

        mode = str(params.get("mode", "modeled"))
        thread_params = normalized_thread_parameters(
            pitch=float(params["pitch"]),
            length=float(params["length"]),
            depth=float(params["depth"]),
            mode=mode,
            thread_type=str(params.get("thread_type", "auto")),
            standard=str(params.get("standard", "custom")),
            size=str(params.get("size", "custom")),
            major_diameter=_optional_float(params.get("major_diameter")),
            minor_diameter=_optional_float(params.get("minor_diameter")),
        )
        edge_reference = step.get("references", {}).get("edge", {})
        if (
            isinstance(edge_reference, dict)
            and edge_reference.get("radius") is not None
        ):
            validate_thread_edge_profile(
                thread_params,
                float(edge_reference["radius"]) * 2.0,
            )
        if mode == "cosmetic":
            return shape
        edge_index = _resolve_circular_edge_reference(
            shape,
            edge_reference,
        )
        return thread_edge(
            shape,
            edge_index,
            pitch=float(params["pitch"]),
            length=float(params["length"]),
            depth=float(params["depth"]),
            mode=mode,
            thread_type=str(params.get("thread_type", "auto")),
            standard=str(params.get("standard", "custom")),
            size=str(params.get("size", "custom")),
            major_diameter=_optional_float(params.get("major_diameter")),
            minor_diameter=_optional_float(params.get("minor_diameter")),
        )
    raise FeatureRebuildError(f"Unsupported feature step: {kind}")


def _feature_step_summary(step: dict[str, Any]) -> str:
    params = dict(step.get("params", {}))
    kind = step.get("kind")
    if kind in {"extrude_face", "sketch_extrude", "sketch_profile_feature"}:
        return f"{float(params.get('distance', 0.0)):.2f} mm"
    if kind == "sketch_revolve":
        angle = float(params.get("angle_degrees", 0.0))
        elevation = float(params.get("elevation", 0.0))
        return f"{angle:.2f} deg, elevation {elevation:.2f} mm"
    if kind == "thread":
        standard = params.get("standard", "custom")
        size = params.get("size", "custom")
        mode = params.get("mode", "modeled")
        pitch = float(params.get("pitch", 0.0))
        length = float(params.get("length", 0.0))
        return f"{standard} {size}, {mode}, P {pitch:.2f}, L {length:.2f}"
    return "parameters"


def _planar_face_reference(shape: Any, face_index: int) -> dict[str, Any]:
    from cad_app.command_topology import _face_by_index, _planar_face_normal

    face = _face_by_index(shape, face_index)
    center, area = _face_center_and_area(face)
    normal = _planar_face_normal(face)
    return {
        "kind": "planar_face",
        "index": int(face_index),
        "center": center,
        "normal": (normal.X(), normal.Y(), normal.Z()),
        "area": area,
    }


def _resolve_planar_face_reference(shape: Any, reference: dict[str, Any]) -> int:
    from OCP.TopoDS import TopoDS

    from cad_app.command_topology import _planar_face_normal
    from cad_app.picker import Picker

    face_map = Picker.indexed_map(shape, SelectionKind.FACE)
    if face_map.Extent() <= 0:
        raise FeatureRebuildError("No faces available for feature reference.")
    ref_center = tuple(reference.get("center", (0.0, 0.0, 0.0)))
    ref_normal = _normalize3(tuple(reference.get("normal", (0.0, 0.0, 1.0))))
    ref_area = float(reference.get("area", 0.0))

    best_index: int | None = None
    best_score: float | None = None
    for index in range(1, face_map.Extent() + 1):
        face = TopoDS.Face_s(face_map.FindKey(index))
        try:
            center, area = _face_center_and_area(face)
            normal = _planar_face_normal(face)
        except Exception:
            continue
        candidate_normal = (normal.X(), normal.Y(), normal.Z())
        score = _point_distance(ref_center, center)
        score += (1.0 - abs(_dot3(ref_normal, candidate_normal))) * 1000.0
        if ref_area > 1e-7:
            score += abs(area - ref_area) / ref_area
        if best_score is None or score < best_score:
            best_index = index
            best_score = score
    if best_index is None:
        raise FeatureRebuildError("Stored face reference could not be resolved.")
    return best_index


def _circular_edge_reference(shape: Any, edge_index: int) -> dict[str, Any]:
    from cad_app.commands import circular_edge_parameters

    center, axis, radius = circular_edge_parameters(shape, edge_index)
    return {
        "kind": "circular_edge",
        "index": int(edge_index),
        "center": center,
        "axis": axis,
        "radius": radius,
    }


def _resolve_circular_edge_reference(shape: Any, reference: dict[str, Any]) -> int:
    from cad_app.commands import CommandError, circular_edge_parameters
    from cad_app.picker import Picker

    edge_map = Picker.indexed_map(shape, SelectionKind.EDGE)
    ref_center = tuple(reference.get("center", (0.0, 0.0, 0.0)))
    ref_axis = _normalize3(tuple(reference.get("axis", (0.0, 0.0, 1.0))))
    ref_radius = float(reference.get("radius", 0.0))

    best_index: int | None = None
    best_score: float | None = None
    for index in range(1, edge_map.Extent() + 1):
        try:
            center, axis, radius = circular_edge_parameters(shape, index)
        except (CommandError, IndexError, RuntimeError, ValueError):
            continue
        score = _point_distance(ref_center, center)
        score += (1.0 - abs(_dot3(ref_axis, axis))) * 1000.0
        score += abs(radius - ref_radius) * 10.0
        if best_score is None or score < best_score:
            best_index = index
            best_score = score
    if best_index is None:
        raise FeatureRebuildError("Stored circular edge reference could not resolve.")
    return best_index


def _face_center_and_area(face: Any) -> tuple[tuple[float, float, float], float]:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    center = props.CentreOfMass()
    return (center.X(), center.Y(), center.Z()), float(props.Mass())


def _copied_history(history: dict[str, Any] | None) -> dict[str, Any] | None:
    if history is None:
        return None
    return {
        "base_shape": history.get("base_shape"),
        "steps": [_copied_step(step) for step in history.get("steps", [])],
        "status": history.get("status", "ok"),
        "error": history.get("error"),
    }


def _copied_step(step: dict[str, Any]) -> dict[str, Any]:
    copied = dict(step)
    copied["params"] = dict(step.get("params", {}))
    if "references" in step:
        copied["references"] = {
            key: dict(value) if isinstance(value, dict) else value
            for key, value in step["references"].items()
        }
    if "payload" in step:
        copied["payload"] = dict(step["payload"])
    return copied


def _required_history(meta: dict[str, Any]) -> dict[str, Any]:
    history = feature_history(meta)
    if history is None:
        raise FeatureRebuildError("Selected body has no parametric feature history.")
    return history


def _mark_history_ok(meta: dict[str, Any]) -> dict[str, Any]:
    next_meta = dict(meta)
    history = _copied_history(_required_history(meta))
    history["status"] = "ok"
    history["error"] = None
    next_meta[FEATURE_HISTORY_KEY] = history
    return next_meta


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _normalize3(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(sum(component * component for component in vector))
    if length <= 1e-7:
        raise FeatureRebuildError("Stored reference vector is zero.")
    return tuple(component / length for component in vector)


def _dot3(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> float:
    return sum(
        first_component * second_component
        for first_component, second_component in zip(first, second)
    )


def _point_distance(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> float:
    return math.sqrt(
        sum(
            (first_component - second_component) ** 2
            for first_component, second_component in zip(first, second)
        )
    )
