"""Reusable model factories for CAD safety tests."""

from __future__ import annotations

from cad_app.commands import (
    add_circle_feature,
    boolean_bodies,
    top_planar_face_index,
    translated_shape,
)
from cad_app.engine import make_box
from cad_app.scene import Scene
from cad_app.sketch import (
    SKETCH_ENTITY_META_KIND,
    SKETCH_META_KIND,
    make_arc_chord_profile,
    make_circle_profile_at,
    make_polyline_preview,
    make_polyline_profile,
    make_rectangle_profile,
)
from cad_app.workplane import Workplane


def single_box_scene() -> Scene:
    scene = Scene()
    scene.add_shape(
        make_box(60.0, 40.0, 20.0),
        meta={"kind": "body", "source": "SingleBox"},
    )
    return scene


def two_box_scene() -> Scene:
    scene = single_box_scene()
    scene.add_shape(
        translated_shape(make_box(45.0, 35.0, 20.0), 25.0, 0.0, 0.0),
        meta={"kind": "body", "source": "BooleanToolBox"},
    )
    return scene


def box_with_top_level_scene() -> Scene:
    base = make_box(80.0, 50.0, 15.0)
    tower = translated_shape(make_box(40.0, 30.0, 20.0), 0.0, 0.0, 15.0)
    scene = Scene()
    scene.add_shape(
        boolean_bodies(base, tower, "union"),
        meta={"kind": "body", "source": "BoxWithTopLevel"},
    )
    return scene


def box_with_cylinder_scene() -> Scene:
    body = make_box(80.0, 50.0, 15.0)
    result = add_circle_feature(
        body,
        face_index=top_planar_face_index(body),
        radius=9.0,
        depth=20.0,
        cut=False,
    )
    scene = Scene()
    scene.add_shape(
        result,
        meta={"kind": "body", "source": "BoxWithCylinder"},
    )
    return scene


def box_with_cutout_scene() -> Scene:
    body = make_box(80.0, 50.0, 25.0)
    result = add_circle_feature(
        body,
        face_index=top_planar_face_index(body),
        radius=9.0,
        depth=18.0,
        cut=True,
    )
    scene = Scene()
    scene.add_shape(
        result,
        meta={"kind": "body", "source": "BoxWithCutout"},
    )
    return scene


def sketch_profiles_scene() -> Scene:
    scene = Scene()
    workplane = Workplane.world_xy()
    scene.add_shape(
        make_rectangle_profile(workplane, width=32.0, height=20.0),
        meta={"kind": SKETCH_META_KIND, "profile": "rectangle"},
    )
    scene.add_shape(
        make_circle_profile_at(workplane, (55.0, 0.0), radius=10.0),
        meta={"kind": SKETCH_META_KIND, "profile": "circle"},
    )
    scene.add_shape(
        make_polyline_profile(
            workplane,
            [
                (-20.0, 35.0),
                (15.0, 35.0),
                (10.0, 55.0),
                (-20.0, 55.0),
                (-20.0, 35.0),
            ],
        ),
        meta={"kind": SKETCH_META_KIND, "profile": "polyline"},
    )
    scene.add_shape(
        make_arc_chord_profile(workplane, (-15.0, -35.0), (15.0, -35.0), (0.0, -20.0)),
        meta={"kind": SKETCH_META_KIND, "profile": "arc"},
    )
    scene.add_shape(
        make_polyline_preview(workplane, [(70.0, 25.0), (90.0, 25.0)]),
        meta={"kind": SKETCH_ENTITY_META_KIND, "profile": "line"},
    )
    return scene


def cad_safety_scene() -> Scene:
    scene = two_box_scene()
    sketches = sketch_profiles_scene()
    for item in sketches:
        scene.add_shape(item.shape, meta=item.meta)
    return scene
