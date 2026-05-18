"""Contract tests for the face picker.

These guard the screen-pixel → world-ray → face-selection pipeline that
turns a viewport click into a SelectionRef. They use a tiny orthographic
view stub so they can run without a real OCP V3d_View (which would need a
Qt window). The stub matches the contract Picker depends on:
``ConvertWithProj(x, y)`` returns a world-space origin + direction, and
``Eye()`` returns the camera position used for depth ranking.
"""

from __future__ import annotations

import math

from tests.conftest import require_ocp


class _OrthoView:
    """Orthographic camera looking straight down -Z.

    Screen pixel (x, y) maps linearly to world (x, y, eye_z). Pixel
    sign matches OCP's `V3d_View.ConvertWithProj`, which returns world
    coordinates of the ray origin and the ray direction in 3D.
    """

    def __init__(
        self,
        eye: tuple[float, float, float] = (0.0, 0.0, 200.0),
        scale: float = 1.0,
    ) -> None:
        self._eye = eye
        self._scale = scale

    def ConvertWithProj(self, x: int, y: int):
        return (
            float(x) / self._scale,
            float(y) / self._scale,
            float(self._eye[2]),
            0.0,
            0.0,
            -1.0,
        )

    def Eye(self):
        return self._eye

    def Convert(self, world_x: float, world_y: float, world_z: float):
        return (world_x * self._scale, world_y * self._scale)


def _find_face_index_with_normal(
    picker, item_id: str, expected_normal: tuple[float, float, float]
) -> int:
    from cad_app.commands import face_normal_vector
    from cad_app.types import SelectionKind

    shape = picker._scene.get(item_id).shape
    for index in range(1, picker.count_subshapes(item_id, SelectionKind.FACE) + 1):
        try:
            normal = face_normal_vector(shape, index)
        except Exception:
            continue
        dot = sum(a * b for a, b in zip(normal, expected_normal))
        if dot > 0.99:
            return index
    raise AssertionError(
        f"No face with normal {expected_normal} found on item {item_id}"
    )


def test_pick_face_through_cylinder_returns_top_face_first() -> None:
    """Clicking on the top of an upright cylinder from above must return
    the top planar face, not the bottom planar face that's also along
    the same ray. The picker should also surface the bottom face as a
    secondary candidate (the ray genuinely intersects both)."""
    require_ocp()

    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder

    from cad_app.picker import Picker
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind

    cylinder = BRepPrimAPI_MakeCylinder(10.0, 30.0).Shape()
    scene = Scene()
    item_id = scene.add_shape(cylinder, meta={"kind": "body", "source": "cylinder"})
    picker = Picker(scene)
    view = _OrthoView()

    results = picker.pick_face_results_at(view, 0, 0)
    assert results, "Center click on cylinder should hit at least one face"

    top_index = _find_face_index_with_normal(picker, item_id, (0.0, 0.0, 1.0))
    bottom_index = _find_face_index_with_normal(picker, item_id, (0.0, 0.0, -1.0))

    assert results[0].selection.kind == SelectionKind.FACE
    assert results[0].selection.item_id == item_id
    assert results[0].selection.index == top_index, (
        "Top face must come first because it is closer to the camera. "
        f"Got index={results[0].selection.index}, "
        f"expected top={top_index}, bottom={bottom_index}."
    )

    picked_indices = {result.selection.index for result in results}
    assert bottom_index in picked_indices, (
        "The bottom face must also surface — the camera ray passes "
        "through the entire body."
    )
    assert results[0].depth < math.inf


def test_pick_face_returns_none_when_cursor_is_outside_silhouette() -> None:
    """A click far outside the body should return no results — the halo
    tolerance is small enough not to magnet onto distant geometry."""
    require_ocp()

    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder

    from cad_app.picker import Picker
    from cad_app.scene import Scene

    cylinder = BRepPrimAPI_MakeCylinder(10.0, 30.0).Shape()
    scene = Scene()
    scene.add_shape(cylinder, meta={"kind": "body", "source": "cylinder"})
    picker = Picker(scene)
    view = _OrthoView()

    # Cylinder has radius 10; clicking 50 units away is well outside the
    # 8 px halo tolerance.
    result = picker.pick_face_result_at(view, 50, 50)
    assert result is None


def test_pick_face_tolerates_click_just_outside_face_by_a_few_pixels() -> None:
    """A click 4 px outside a face boundary must still pick it via the
    halo offsets. This is the "click forgiveness" contract that lets
    users select features without pixel-perfect aim."""
    require_ocp()

    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder

    from cad_app.picker import Picker
    from cad_app.scene import Scene

    cylinder = BRepPrimAPI_MakeCylinder(10.0, 30.0).Shape()
    scene = Scene()
    item_id = scene.add_shape(cylinder, meta={"kind": "body", "source": "cylinder"})
    picker = Picker(scene)
    view = _OrthoView()

    # Cylinder radius = 10. Click at (12, 0) — 2 units past the rim,
    # well inside the 8 px halo. Top face should still be the first
    # candidate via the offset rays.
    result = picker.pick_face_result_at(view, 12, 0)
    assert result is not None, (
        "A click 2 px outside the rim must still hit the top face "
        "thanks to the halo offsets."
    )

    top_index = _find_face_index_with_normal(picker, item_id, (0.0, 0.0, 1.0))
    assert result.selection.index == top_index


def test_pick_face_is_stable_for_subpixel_jitter_near_boundary() -> None:
    """Successive clicks within a 1 px box near a face boundary must
    return the same face. This is the stability guarantee that prevents
    selection from flipping under mouse jitter."""
    require_ocp()

    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder

    from cad_app.picker import Picker
    from cad_app.scene import Scene

    cylinder = BRepPrimAPI_MakeCylinder(10.0, 30.0).Shape()
    scene = Scene()
    item_id = scene.add_shape(cylinder, meta={"kind": "body", "source": "cylinder"})
    picker = Picker(scene)
    view = _OrthoView()
    top_index = _find_face_index_with_normal(picker, item_id, (0.0, 0.0, 1.0))

    # Click at the centre and four 1-pixel-jittered neighbours. All five
    # land cleanly inside the top face (radius 10, well inside) and
    # must yield the same face.
    picks = [
        picker.pick_face_result_at(view, x, y)
        for x, y in [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)]
    ]
    assert all(pick is not None for pick in picks)
    assert all(pick.selection.index == top_index for pick in picks), (
        "Cursor jitter inside a single face must not flip the picker's "
        "choice between adjacent faces."
    )


def test_pick_face_prefers_front_body_when_two_bodies_overlap() -> None:
    """Two stacked bodies along the camera ray: the closer body's face
    must win, never the body behind it."""
    require_ocp()

    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder

    from cad_app.commands import translated_shape
    from cad_app.picker import Picker
    from cad_app.scene import Scene

    near_cylinder = BRepPrimAPI_MakeCylinder(10.0, 20.0).Shape()
    near_cylinder = translated_shape(near_cylinder, 0.0, 0.0, 30.0)
    far_cylinder = BRepPrimAPI_MakeCylinder(10.0, 20.0).Shape()

    scene = Scene()
    near_id = scene.add_shape(near_cylinder, meta={"kind": "body", "source": "near"})
    scene.add_shape(far_cylinder, meta={"kind": "body", "source": "far"})
    picker = Picker(scene)
    view = _OrthoView(eye=(0.0, 0.0, 200.0))

    result = picker.pick_face_result_at(view, 0, 0)
    assert result is not None
    assert (
        result.selection.item_id == near_id
    ), "Front cylinder must win over the cylinder directly behind it."
