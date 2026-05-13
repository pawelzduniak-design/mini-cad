from __future__ import annotations

import pytest

from tests.conftest import require_ocp
from tests.helpers.topology import bounding_box


def test_parametric_extrude_step_can_be_edited_and_rebuilt() -> None:
    require_ocp()

    from cad_app.commands import apply_extrude_face, top_planar_face_index
    from cad_app.engine import make_box
    from cad_app.feature_history import (
        feature_history_steps,
        update_scene_item_feature_step,
    )
    from cad_app.scene import Scene

    scene = Scene()
    item_id = scene.add_shape(make_box(20.0, 20.0, 20.0), meta={"kind": "body"})

    apply_extrude_face(
        scene,
        item_id,
        top_planar_face_index(scene.get(item_id).shape),
        10.0,
    )
    update_scene_item_feature_step(scene, item_id, 0, {"distance": 20.0})

    assert bounding_box(scene.get(item_id).shape)["height"] == pytest.approx(40.0)
    steps = feature_history_steps(scene.get(item_id).meta)
    assert len(steps) == 1
    assert steps[0]["kind"] == "extrude_face"
    assert steps[0]["params"]["distance"] == pytest.approx(20.0)


def test_parametric_rebuild_remaps_downstream_face_reference() -> None:
    require_ocp()

    from cad_app.commands import apply_extrude_face, top_planar_face_index
    from cad_app.engine import make_box
    from cad_app.feature_history import update_scene_item_feature_step
    from cad_app.scene import Scene

    scene = Scene()
    item_id = scene.add_shape(make_box(20.0, 20.0, 20.0), meta={"kind": "body"})
    apply_extrude_face(
        scene,
        item_id,
        top_planar_face_index(scene.get(item_id).shape),
        10.0,
    )
    apply_extrude_face(
        scene,
        item_id,
        top_planar_face_index(scene.get(item_id).shape),
        5.0,
    )

    update_scene_item_feature_step(scene, item_id, 0, {"distance": 20.0})

    assert bounding_box(scene.get(item_id).shape)["height"] == pytest.approx(45.0)


def test_parametric_rebuild_failure_does_not_mutate_body() -> None:
    require_ocp()

    from cad_app.commands import apply_extrude_face, top_planar_face_index
    from cad_app.engine import make_box
    from cad_app.feature_history import (
        FeatureRebuildError,
        feature_history,
        mark_scene_item_feature_history_failed,
        update_scene_item_feature_step,
    )
    from cad_app.scene import Scene

    scene = Scene()
    item_id = scene.add_shape(make_box(20.0, 20.0, 20.0), meta={"kind": "body"})
    apply_extrude_face(
        scene,
        item_id,
        top_planar_face_index(scene.get(item_id).shape),
        10.0,
    )
    before = bounding_box(scene.get(item_id).shape)

    with pytest.raises(FeatureRebuildError):
        update_scene_item_feature_step(scene, item_id, 0, {"distance": 0.0})

    assert bounding_box(scene.get(item_id).shape) == before
    mark_scene_item_feature_history_failed(scene, item_id, "distance is zero")
    history = feature_history(scene.get(item_id).meta)
    assert history is not None
    assert history["status"] == "failed"
    assert history["error"] == "distance is zero"


def test_parametric_history_can_roll_back_later_features() -> None:
    require_ocp()

    from cad_app.commands import apply_extrude_face, top_planar_face_index
    from cad_app.engine import make_box
    from cad_app.feature_history import (
        feature_history_steps,
        rollback_scene_item_feature_history,
    )
    from cad_app.scene import Scene

    scene = Scene()
    item_id = scene.add_shape(make_box(20.0, 20.0, 20.0), meta={"kind": "body"})
    apply_extrude_face(
        scene,
        item_id,
        top_planar_face_index(scene.get(item_id).shape),
        10.0,
    )
    apply_extrude_face(
        scene,
        item_id,
        top_planar_face_index(scene.get(item_id).shape),
        5.0,
    )

    rollback_scene_item_feature_history(scene, item_id, 1)

    assert bounding_box(scene.get(item_id).shape)["height"] == pytest.approx(30.0)
    assert len(feature_history_steps(scene.get(item_id).meta)) == 1


def test_thread_presets_expose_manufacturing_dimensions() -> None:
    require_ocp()

    from cad_app.thread_specs import (
        thread_parameters_from_preset,
        thread_preset_by_name,
    )

    preset = thread_preset_by_name("ISO M6x1.0")

    assert preset is not None
    params = thread_parameters_from_preset(preset)
    assert params["pitch"] == pytest.approx(1.0)
    assert params["major_diameter"] == pytest.approx(6.0)
    assert params["minor_diameter"] < params["major_diameter"]
    assert params["depth"] == pytest.approx(
        (params["major_diameter"] - params["minor_diameter"]) / 2.0
    )


def test_cosmetic_thread_keeps_geometry_and_records_feature_history() -> None:
    require_ocp()

    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder

    from cad_app.commands import CommandError, apply_thread_to_edge
    from cad_app.feature_history import feature_history_steps
    from cad_app.picker import Picker
    from cad_app.scene import Scene
    from cad_app.thread_specs import (
        thread_parameters_from_preset,
        thread_preset_by_name,
    )
    from cad_app.types import SelectionKind

    shape = BRepPrimAPI_MakeCylinder(3.0, 20.0).Shape()
    scene = Scene()
    item_id = scene.add_shape(shape, meta={"kind": "body", "source": "cylinder"})
    picker = Picker(scene)
    edge_index = None
    for index in range(1, picker.count_subshapes(item_id, SelectionKind.EDGE) + 1):
        try:
            from cad_app.commands import circular_edge_parameters

            circular_edge_parameters(shape, index)
        except (CommandError, IndexError, RuntimeError, ValueError):
            continue
        edge_index = index
        break
    assert edge_index is not None

    preset = thread_preset_by_name("ISO M6x1.0")
    assert preset is not None
    params = thread_parameters_from_preset(preset)
    before = bounding_box(scene.get(item_id).shape)

    apply_thread_to_edge(
        scene,
        item_id,
        edge_index,
        pitch=float(params["pitch"]),
        length=12.0,
        depth=float(params["depth"]),
        mode="cosmetic",
        thread_type="external",
        standard=str(params["standard"]),
        size=str(params["size"]),
        major_diameter=float(params["major_diameter"]),
        minor_diameter=float(params["minor_diameter"]),
    )

    assert bounding_box(scene.get(item_id).shape) == before
    steps = feature_history_steps(scene.get(item_id).meta)
    assert len(steps) == 1
    assert steps[0]["kind"] == "thread"
    assert steps[0]["params"]["mode"] == "cosmetic"
    assert steps[0]["params"]["standard"] == "ISO"
    assert steps[0]["params"]["size"] == "M6x1.0"


def test_thread_profile_validation_rejects_mismatched_preset_diameter() -> None:
    require_ocp()

    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder

    from cad_app.commands import CommandError, thread_edge
    from cad_app.picker import Picker
    from cad_app.scene import Scene
    from cad_app.thread_specs import (
        thread_parameters_from_preset,
        thread_preset_by_name,
    )
    from cad_app.types import SelectionKind

    shape = BRepPrimAPI_MakeCylinder(10.0, 20.0).Shape()
    scene = Scene()
    item_id = scene.add_shape(shape, meta={"kind": "body", "source": "cylinder"})
    picker = Picker(scene)
    edge_index = None
    for index in range(1, picker.count_subshapes(item_id, SelectionKind.EDGE) + 1):
        try:
            from cad_app.commands import circular_edge_parameters

            circular_edge_parameters(shape, index)
        except (CommandError, IndexError, RuntimeError, ValueError):
            continue
        edge_index = index
        break
    assert edge_index is not None

    preset = thread_preset_by_name("ISO M6x1.0")
    assert preset is not None
    params = thread_parameters_from_preset(preset)

    with pytest.raises(ValueError, match="does not match thread profile"):
        thread_edge(
            shape,
            edge_index,
            pitch=float(params["pitch"]),
            length=12.0,
            depth=float(params["depth"]),
            mode="cosmetic",
            thread_type="external",
            standard=str(params["standard"]),
            size=str(params["size"]),
            major_diameter=float(params["major_diameter"]),
            minor_diameter=float(params["minor_diameter"]),
        )
