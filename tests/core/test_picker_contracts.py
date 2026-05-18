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


class _AxoTopFaceRegressionView:
    """Orthographic axonometric view sampled from the real OCCT viewer.

    The click at screen (0, 0) is on an extruded circle's visible top
    face. Some 4 px halo rays also touch the far bottom cap, so this
    view guards the ranking between the real centre hit and halo hits.
    """

    def __init__(self) -> None:
        self._origin = (170.174319062, -162.124629621, 201.409654727)
        inv_sqrt_3 = 1.0 / math.sqrt(3.0)
        self._direction = (-inv_sqrt_3, inv_sqrt_3, -inv_sqrt_3)
        self._right_per_px = (0.447204969, 0.447204969, 0.0)
        self._down_per_px = (0.258193909, -0.258193909, -0.516387818)
        self._eye = (281.15, -281.15, 302.855)

    def ConvertWithProj(self, x: int, y: int):
        origin = tuple(
            self._origin[index]
            + self._right_per_px[index] * float(x)
            + self._down_per_px[index] * float(y)
            for index in range(3)
        )
        return (*origin, *self._direction)

    def Eye(self):
        return self._eye

    def Convert(self, world_x: float, world_y: float, world_z: float):
        return (0.0, 0.0)


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


def test_pick_face_planar_bonus_beats_curved_centre_hit(monkeypatch) -> None:
    """At an oblique camera angle a cylinder's top face appears as a
    thin ellipse; the user's click can land 1-3 px below the visible
    top boundary, where the centre ray hits the curved side face but
    a halo offset (e.g. 4 px up) reaches the planar top. The planar
    top must win - this matches user perception ('I clicked on the
    top') over strict geometric ray-cast ('centre hit the side')."""
    require_ocp()

    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder

    from cad_app.picker import FacePickResult, Picker
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef

    cylinder = BRepPrimAPI_MakeCylinder(10.0, 30.0).Shape()
    scene = Scene()
    item_id = scene.add_shape(cylinder, meta={"kind": "body", "source": "cyl"})
    picker = Picker(scene)

    top_index = _find_face_index_with_normal(picker, item_id, (0.0, 0.0, 1.0))
    side_index = None
    for idx in range(1, picker.count_subshapes(item_id, SelectionKind.FACE) + 1):
        face = picker.subshape(item_id, SelectionKind.FACE, idx)
        if not Picker._is_planar_face(face):
            side_index = idx
            break
    assert side_index is not None, "Cylinder must have a non-planar side face"

    side_ref = SelectionRef(item_id, SelectionKind.FACE, side_index)
    top_ref = SelectionRef(item_id, SelectionKind.FACE, top_index)

    def fake_ray_pick_faces(
        _item_id, _shape, _origin, _direction, _eye, distance_px=0.0
    ):
        # Centre ray (distance_px == 0) lands ONLY on the curved side -
        # the planar top is reached only by halo offsets within 4 px.
        # This is the boundary case: user clicked just below the
        # visible top edge.
        if distance_px <= 0.001:
            return [
                FacePickResult(
                    selection=side_ref,
                    depth=10.0,
                    distance_px=0.0,
                    is_planar=False,
                )
            ]
        if distance_px <= 4.0:
            return [
                FacePickResult(
                    selection=top_ref,
                    depth=5.0,
                    distance_px=distance_px,
                    is_planar=True,
                )
            ]
        return []

    monkeypatch.setattr(picker, "_ray_pick_faces", fake_ray_pick_faces)

    view = _OrthoView()
    result = picker.pick_face_result_at(view, 0, 0)
    assert result is not None
    assert result.selection.index == top_index, (
        "Planar top face hit by a 4-px-or-less offset must beat a "
        "centre hit on the curved side face."
    )


def test_pick_face_centre_hit_curved_keeps_winning_over_deep_planar(
    monkeypatch,
) -> None:
    """Click in the middle of a cylinder's side face: the centre ray
    enters through the side (close) and exits through the bottom
    planar face (far). Even though the bottom is planar and would
    have distance_px=0 from the centre, the SIDE must win because
    it's what the cursor is genuinely over. The planar bonus must
    NOT apply when the centre ray itself hit the planar face."""
    require_ocp()

    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder

    from cad_app.picker import FacePickResult, Picker
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef

    cylinder = BRepPrimAPI_MakeCylinder(10.0, 30.0).Shape()
    scene = Scene()
    item_id = scene.add_shape(cylinder, meta={"kind": "body", "source": "cyl"})
    picker = Picker(scene)

    bottom_index = _find_face_index_with_normal(picker, item_id, (0.0, 0.0, -1.0))
    side_index = None
    for idx in range(1, picker.count_subshapes(item_id, SelectionKind.FACE) + 1):
        face = picker.subshape(item_id, SelectionKind.FACE, idx)
        if not Picker._is_planar_face(face):
            side_index = idx
            break
    assert side_index is not None

    side_ref = SelectionRef(item_id, SelectionKind.FACE, side_index)
    bottom_ref = SelectionRef(item_id, SelectionKind.FACE, bottom_index)

    def fake_ray_pick_faces(
        _item_id, _shape, _origin, _direction, _eye, distance_px=0.0
    ):
        # Every ray (centre and halo) goes through the cylinder and
        # hits the side at near depth and the bottom at far depth.
        # Both faces are "centre-hit" when distance_px == 0.
        return [
            FacePickResult(
                selection=side_ref,
                depth=5.0,
                distance_px=distance_px,
                is_planar=False,
            ),
            FacePickResult(
                selection=bottom_ref,
                depth=40.0,
                distance_px=distance_px,
                is_planar=True,
            ),
        ]

    monkeypatch.setattr(picker, "_ray_pick_faces", fake_ray_pick_faces)

    view = _OrthoView()
    result = picker.pick_face_result_at(view, 0, 0)
    assert result is not None
    assert result.selection.index == side_index, (
        "Clicking the cylinder side must select the side, not the "
        "planar bottom the ray exits through."
    )


def test_pick_face_planar_bonus_does_not_apply_beyond_radius(monkeypatch) -> None:
    """If the planar face is only reached by FAR offsets (> 4 px), the
    centre hit on the curved face stays the winner. The bonus exists
    to bridge 1-3 px boundary misses, not to magnet onto distant
    planar geometry."""
    require_ocp()

    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder

    from cad_app.picker import FacePickResult, Picker
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef

    cylinder = BRepPrimAPI_MakeCylinder(10.0, 30.0).Shape()
    scene = Scene()
    item_id = scene.add_shape(cylinder, meta={"kind": "body", "source": "cyl"})
    picker = Picker(scene)

    top_index = _find_face_index_with_normal(picker, item_id, (0.0, 0.0, 1.0))
    side_index = None
    for idx in range(1, picker.count_subshapes(item_id, SelectionKind.FACE) + 1):
        face = picker.subshape(item_id, SelectionKind.FACE, idx)
        if not Picker._is_planar_face(face):
            side_index = idx
            break
    assert side_index is not None

    side_ref = SelectionRef(item_id, SelectionKind.FACE, side_index)
    top_ref = SelectionRef(item_id, SelectionKind.FACE, top_index)

    def fake_ray_pick_faces(
        _item_id, _shape, _origin, _direction, _eye, distance_px=0.0
    ):
        if distance_px <= 0.001:
            return [
                FacePickResult(
                    selection=side_ref,
                    depth=10.0,
                    distance_px=0.0,
                    is_planar=False,
                )
            ]
        # Only the FAR halo rays (8 px) reach the top face.
        if distance_px >= 7.9:
            return [
                FacePickResult(
                    selection=top_ref,
                    depth=5.0,
                    distance_px=distance_px,
                    is_planar=True,
                )
            ]
        return []

    monkeypatch.setattr(picker, "_ray_pick_faces", fake_ray_pick_faces)

    view = _OrthoView()
    result = picker.pick_face_result_at(view, 0, 0)
    assert result is not None
    assert result.selection.index == side_index, (
        "Centre hit on curved face must stay the winner when the only "
        "planar candidate is beyond the planar-preference radius."
    )


def test_pick_face_planar_halo_does_not_beat_closer_curved_halo(
    monkeypatch,
) -> None:
    """Near a cylinder rim, both the curved side and a planar cap can be
    reached only by halo rays. The cap must not win just because it is
    planar when the curved side is actually closer to the camera."""
    require_ocp()

    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder

    from cad_app.picker import FacePickResult, Picker
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef

    cylinder = BRepPrimAPI_MakeCylinder(10.0, 30.0).Shape()
    scene = Scene()
    item_id = scene.add_shape(cylinder, meta={"kind": "body", "source": "cyl"})
    picker = Picker(scene)

    bottom_index = _find_face_index_with_normal(picker, item_id, (0.0, 0.0, -1.0))
    side_index = None
    for idx in range(1, picker.count_subshapes(item_id, SelectionKind.FACE) + 1):
        face = picker.subshape(item_id, SelectionKind.FACE, idx)
        if not Picker._is_planar_face(face):
            side_index = idx
            break
    assert side_index is not None

    side_ref = SelectionRef(item_id, SelectionKind.FACE, side_index)
    bottom_ref = SelectionRef(item_id, SelectionKind.FACE, bottom_index)

    def fake_ray_pick_faces(
        _item_id, _shape, _origin, _direction, _eye, distance_px=0.0
    ):
        if distance_px <= 0.001:
            return []
        if distance_px <= 4.0:
            return [
                FacePickResult(
                    selection=side_ref,
                    depth=10.0,
                    distance_px=distance_px,
                    is_planar=False,
                ),
                FacePickResult(
                    selection=bottom_ref,
                    depth=15.0,
                    distance_px=distance_px,
                    is_planar=True,
                    is_front_facing=False,
                ),
            ]
        return []

    monkeypatch.setattr(picker, "_ray_pick_faces", fake_ray_pick_faces)

    view = _OrthoView()
    result = picker.pick_face_result_at(view, 0, 0)
    assert result is not None
    assert result.selection.index == side_index, (
        "A closer curved side halo hit must beat a farther planar cap "
        "halo hit so the cylinder side remains easy to select."
    )


def test_pick_face_top_center_beats_far_bottom_cap_halo_hit() -> None:
    """A centre hit on the visible top face must not lose to the far
    bottom cap just because a 4 px halo ray also intersects that planar
    face. This reproduces the extruded-circle cylinder selection bug."""
    require_ocp()

    from cad_app.picker import Picker
    from cad_app.scene import Scene
    from cad_app.sketch import extrude_profile, make_circle_profile_at
    from cad_app.types import SelectionKind
    from cad_app.workplane import Workplane

    profile = make_circle_profile_at(
        Workplane.world_xy(),
        (-7.322, 15.439),
        30.0,
    )
    shape = extrude_profile(profile, 43.43)
    scene = Scene()
    item_id = scene.add_shape(shape, meta={"kind": "body", "source": "sketch_extrude"})
    picker = Picker(scene)

    top_index = _find_face_index_with_normal(picker, item_id, (0.0, 0.0, 1.0))
    bottom_index = _find_face_index_with_normal(picker, item_id, (0.0, 0.0, -1.0))

    results = picker.pick_face_results_at(_AxoTopFaceRegressionView(), 0, 0)
    assert results, "Click on the visible top cap should return face candidates"
    assert results[0].selection.kind == SelectionKind.FACE
    assert results[0].selection.index == top_index, (
        "The visible top face hit by the centre ray must beat the far "
        f"bottom cap. Got index={results[0].selection.index}, "
        f"expected top={top_index}, bottom={bottom_index}."
    )
    assert any(result.selection.index == bottom_index for result in results), (
        "The bottom cap should still appear as an overlap candidate; it "
        "just must not outrank the visible top face."
    )


def test_pick_face_planar_bonus_does_not_steal_clicks_across_bodies(
    monkeypatch,
) -> None:
    """Two separate bodies: the centre ray hits body A's curved face,
    while a halo ray slips past it and reaches body B's planar face.
    The planar bonus must NOT promote body B's face - it is meant to
    resolve same-body face ambiguity (cylinder top vs side), not let
    a planar face on a different body behind the cursor steal the
    click."""
    require_ocp()

    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder

    from cad_app.picker import FacePickResult, Picker
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef

    body_a = BRepPrimAPI_MakeCylinder(10.0, 30.0).Shape()
    body_b = BRepPrimAPI_MakeCylinder(10.0, 30.0).Shape()
    scene = Scene()
    item_a = scene.add_shape(body_a, meta={"kind": "body", "source": "a"})
    item_b = scene.add_shape(body_b, meta={"kind": "body", "source": "b"})
    picker = Picker(scene)

    side_a_index = next(
        idx
        for idx in range(1, picker.count_subshapes(item_a, SelectionKind.FACE) + 1)
        if not Picker._is_planar_face(picker.subshape(item_a, SelectionKind.FACE, idx))
    )
    top_b_index = _find_face_index_with_normal(picker, item_b, (0.0, 0.0, 1.0))

    side_a_ref = SelectionRef(item_a, SelectionKind.FACE, side_a_index)
    top_b_ref = SelectionRef(item_b, SelectionKind.FACE, top_b_index)

    def fake_ray_pick_faces(
        item_id, _shape, _origin, _direction, _eye, distance_px=0.0
    ):
        if item_id == item_a:
            # Body A: curved side hit by centre + every halo (cursor is over it).
            return [
                FacePickResult(
                    selection=side_a_ref,
                    depth=20.0,
                    distance_px=distance_px,
                    is_planar=False,
                )
            ]
        if item_id == item_b and 0.001 < distance_px <= 4.0:
            # Body B: a halo ray slips off the side of A and reaches B's
            # planar top. The centre ray does NOT reach B.
            return [
                FacePickResult(
                    selection=top_b_ref,
                    depth=50.0,
                    distance_px=distance_px,
                    is_planar=True,
                    is_front_facing=True,
                )
            ]
        return []

    monkeypatch.setattr(picker, "_ray_pick_faces", fake_ray_pick_faces)

    view = _OrthoView()
    result = picker.pick_face_result_at(view, 0, 0)
    assert result is not None
    assert result.selection.item_id == item_a, (
        "Centre-hit body A must keep the click. A planar face on body B "
        "reached only by halo through a gap may not steal it."
    )


def test_pick_face_is_stable_pixel_by_pixel_across_top_silhouette() -> None:
    """Sweeping the cursor 1 px at a time across an extruded cylinder's
    top silhouette must produce a monotonic transition (TOP -> LAT) with
    no oscillation. Earlier versions flickered (TOP, LAT, TOP, LAT, ...)
    when the depth-gate criterion swung on the centre ray's hit depth."""
    require_ocp()

    from cad_app.picker import Picker
    from cad_app.scene import Scene
    from cad_app.sketch import extrude_profile, make_circle_profile_at
    from cad_app.types import SelectionKind
    from cad_app.workplane import Workplane

    profile = make_circle_profile_at(Workplane.world_xy(), (0.0, 0.0), 30.0)
    shape = extrude_profile(profile, 91.08)
    scene = Scene()
    item_id = scene.add_shape(shape, meta={"kind": "body", "source": "sketch_extrude"})
    picker = Picker(scene)

    top_index = _find_face_index_with_normal(picker, item_id, (0.0, 0.0, 1.0))
    lateral_index = next(
        idx
        for idx in range(1, picker.count_subshapes(item_id, SelectionKind.FACE) + 1)
        if not Picker._is_planar_face(picker.subshape(item_id, SelectionKind.FACE, idx))
    )

    class _AxoView:
        def __init__(self) -> None:
            distance = 500.0
            az = math.radians(45.0)
            el = math.radians(35.264)
            cx = math.cos(el) * math.cos(az)
            cy = math.cos(el) * math.sin(az)
            cz = math.sin(el)
            tx, ty, tz = 0.0, 0.0, 45.54
            self._eye = (
                tx + cx * distance,
                ty + cy * distance,
                tz + cz * distance,
            )
            self._dir = (-cx, -cy, -cz)
            # scale = 0.3 means cylinder is ~80px tall on screen so the
            # silhouette transition falls in a tight pixel band, which
            # is exactly where flicker showed up.
            scale = 0.3
            self._right = (
                -math.sin(az) / scale,
                math.cos(az) / scale,
                0.0,
            )
            self._down = (
                math.sin(el) * math.cos(az) / scale,
                math.sin(el) * math.sin(az) / scale,
                -math.cos(el) / scale,
            )

        def ConvertWithProj(self, x: int, y: int):
            origin = tuple(
                self._eye[i] + self._right[i] * float(x) + self._down[i] * float(y)
                for i in range(3)
            )
            return (*origin, *self._dir)

        def Eye(self):
            return self._eye

        def Convert(self, world_x: float, world_y: float, world_z: float):
            return (0.0, 0.0)

    view = _AxoView()
    indices = []
    for y in range(-15, 10):
        result = picker.pick_face_result_at(view, 0, y)
        if result is None:
            indices.append(None)
        else:
            indices.append(result.selection.index)

    transitions = sum(
        1
        for prev, curr in zip(indices, indices[1:])
        if prev is not None and curr is not None and prev != curr
    )
    assert transitions == 1, (
        "Cursor sweep across the top silhouette must produce exactly one "
        f"face transition (no flicker). Saw transitions={transitions}, "
        f"sequence={indices}."
    )

    top_runs = [i for i, idx in enumerate(indices) if idx == top_index]
    lat_runs = [i for i, idx in enumerate(indices) if idx == lateral_index]
    assert top_runs, "Sweep must include at least one TOP pick"
    assert lat_runs, "Sweep must include at least one LATERAL pick"
    assert max(top_runs) < min(lat_runs), (
        "TOP picks must come before LATERAL picks as the cursor moves "
        f"down past the silhouette. sequence={indices}."
    )
