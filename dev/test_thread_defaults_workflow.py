"""Probe thread defaults on a small circular hole in a box.

A beginner workflow: small box → drill a circular hole → add a thread to
the edge of that hole. The current defaults are 'całą głębokość bryły',
which on a 20 mm tall box drilled 10 mm deep produces a thread that runs
past the actual hole and looks wrong.

This script prints what defaults the dialog would currently propose so a
regression in `thread_default_length` or the preset auto-pick is easy to
spot. It does not run the dialog — it queries the same helpers directly.
"""

from __future__ import annotations

import sys
from typing import Any

from cad_app.commands import (
    circular_edge_parameters,
    thread_default_length,
)
from cad_app.engine import make_box
from cad_app.sketch import apply_profile_feature, make_circle_profile_at
from cad_app.thread_specs import (
    matching_thread_preset_for_edge_diameter,
    thread_parameters_from_preset,
)
from cad_app.workplane import Workplane


def _circular_edges_with_radius(shape: Any, *, target_radius: float, tol: float):
    """Return (edge_index, radius, axis) for every circular edge whose
    radius is within `tol` of `target_radius`."""
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    edge_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_EDGE, edge_map)
    out = []
    for idx in range(1, edge_map.Extent() + 1):
        try:
            _center, axis, radius = circular_edge_parameters(shape, idx)
        except Exception:  # noqa: BLE001
            continue
        if abs(radius - target_radius) <= tol:
            out.append((idx, radius, axis))
    return out


def _report_thread_defaults(label: str, shape: Any, edge_idx: int) -> None:
    _center, axis, radius = circular_edge_parameters(shape, edge_idx)
    diameter = radius * 2.0
    legacy_length = thread_default_length(shape, axis)
    aware_length = thread_default_length(shape, axis, edge_radius=radius)
    matching = matching_thread_preset_for_edge_diameter(diameter)
    print(f"\n[{label}] edge_idx={edge_idx}")
    print(f"  radius={radius:.3f} mm, diameter={diameter:.3f} mm")
    print(f"  default_length (no edge_radius) = {legacy_length:.2f} mm")
    print(
        f"  default_length (radius-aware)   = {aware_length:.2f} mm "
        "  <-- new UI default"
    )
    if matching is None:
        print("  matching preset = None (would default to Custom)")
        default_pitch = max(0.5, min(3.0, radius * 0.18))
        default_depth = max(0.15, default_pitch * 0.35)
        print(
            f"  Custom defaults: pitch={default_pitch:.2f}, "
            f"depth={default_depth:.2f}"
        )
    else:
        params = thread_parameters_from_preset(matching)
        print(
            f"  matching preset = {matching.name} (pitch={params['pitch']:.2f}, "
            f"depth={params['depth']:.2f}, "
            f"major D={params['major_diameter']:.2f}, "
            f"minor D={params['minor_diameter']:.2f})"
        )

    # The cardinal sanity checks for a beginner:
    # - thread length should not exceed the actual through-feature depth
    # - pitch / depth should be reasonable for the diameter (rule of thumb:
    #   pitch around 10–20% of major D, depth ~50% of pitch).
    assumed_hole_depth = 10.0
    # The radius-aware default should fit a sensible 5x radius rule of
    # thumb. For M6 (radius 3) that's 15 mm; for the dialog's 10 mm hole
    # it is still slightly long but no longer absurd.
    expected_max = max(2.0, radius * 5.0)
    if aware_length > expected_max + 0.1:
        print(
            f"  FAIL: radius-aware length {aware_length:.1f} > 5x radius "
            f"({expected_max:.1f}) -- defaults still too long"
        )
    elif legacy_length > assumed_hole_depth + 1.0:
        print(
            f"  INFO: legacy length {legacy_length:.1f} mm exceeds hole "
            f"depth {assumed_hole_depth:.1f}; radius-aware default fixes it "
            f"({aware_length:.1f} mm)"
        )
    else:
        print(
            f"  OK: legacy and aware defaults both reasonable "
            f"({legacy_length:.1f} / {aware_length:.1f})"
        )


def _rotate_pivot_probe() -> None:
    """Quick check: rotate around a body vertex vs the body centroid."""
    from PySide6.QtWidgets import QApplication

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    app = QApplication.instance() or QApplication([])
    _ = app
    scene = Scene()
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget

    body = make_box(40.0, 30.0, 20.0)
    item_id = scene.add_shape(body, meta={"kind": "body", "source": "rotate_probe"})

    # Pick a corner vertex of the box. Vertex 1 is by convention the
    # (-20, -15, 0) corner because make_box centres on XY.
    vertex_ref = SelectionRef(item_id, SelectionKind.VERTEX, 1)
    body_ref = SelectionRef(item_id, SelectionKind.OBJECT, 0)
    scene.set_selections((body_ref, vertex_ref))

    widget._set_active_category("select")
    rotate_enabled = main_window.actions["rotate_body"].isEnabled()
    print(f"\n[rotate_pivot] rotate_body enabled with body+vertex = {rotate_enabled}")

    pivot = widget._rotate_pivot_from_selection()
    print(f"  pivot from selection (vertex 1): {pivot}")
    # Expected: corner near (-20, -15, 0)
    if pivot is not None and pivot[0] < -10.0 and pivot[1] < -10.0:
        print("  OK: custom pivot resolves to the picked vertex")
    else:
        print(f"  FAIL: pivot did not snap to the vertex corner ({pivot})")
    main_window.window.close()


def main() -> int:
    sys.stdout.write("=== THREAD DEFAULTS PROBE ===\n")

    # Build a small box 60×40×20, drill a 6 mm diameter, 10 mm deep hole
    # from the top face. Then look at the circular edges on the hole.
    body = make_box(60.0, 40.0, 20.0)
    # The box is centered on XY, top face at Z=20. The hole workplane
    # is on that top face (normal +Z); cut downward (negative distance).
    # However, the simplest way: build the hole profile in world XY and
    # apply_profile_feature with distance -10 going downward into a body
    # whose top face is at +Z.

    # We need the top face workplane. Construct from face.
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape

    from cad_app.commands import _planar_face_normal

    face_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(body, TopAbs_FACE, face_map)
    top_face = None
    for i in range(1, face_map.Extent() + 1):
        f = TopoDS.Face_s(face_map.FindKey(i))
        n = _planar_face_normal(f)
        if abs(n.Z() - 1.0) < 0.05:
            top_face = f
            break
    assert top_face is not None, "Top face not found"
    workplane = Workplane.from_face(top_face)

    hole_profile = make_circle_profile_at(workplane, (0.0, 0.0), 3.0)
    body_with_hole = apply_profile_feature(body, hole_profile, -10.0)
    print("Built box 60x40x20 with a 6 mm hole, 10 mm deep")

    # Find circular edges of radius 3 mm
    edges = _circular_edges_with_radius(body_with_hole, target_radius=3.0, tol=0.05)
    if not edges:
        print("[FAIL] No circular edges of radius 3 mm found in the cut body")
        return 1

    print(f"Found {len(edges)} circular edge(s) with radius ~3 mm")
    for idx, _radius, _axis in edges:
        _report_thread_defaults("hole edge", body_with_hole, idx)

    # For comparison, do the same on a HUGE box — to see that the
    # default length is just the body span and has no relation to a
    # thread that makes sense.
    big = make_box(500.0, 400.0, 300.0)
    print("\n--- Same hole geometry on a 500x400x300 mm body ---")
    big_with_hole = apply_profile_feature(
        big,
        make_circle_profile_at(Workplane.from_face(top_face), (0.0, 0.0), 3.0),
        -10.0,
    )
    edges_big = _circular_edges_with_radius(big_with_hole, target_radius=3.0, tol=0.05)
    if edges_big:
        _report_thread_defaults("big body", big_with_hole, edges_big[0][0])

    _rotate_pivot_probe()
    _revolve_custom_axis_probe()
    return 0


def _revolve_custom_axis_probe() -> None:
    """Quick check: revolve a profile around a construction line."""
    from PySide6.QtWidgets import QApplication

    from cad_app.main_window import create_main_window
    from cad_app.scene import Scene
    from cad_app.sketch import (
        SKETCH_ENTITY_META_KIND,
        SKETCH_META_KIND,
        make_circle_profile_at,
        make_polyline_preview,
    )
    from cad_app.types import SelectionKind, SelectionRef
    from cad_app.viewer import Viewer

    app = QApplication.instance() or QApplication([])
    _ = app
    scene = Scene()
    main_window = create_main_window(Viewer(), scene)
    widget = main_window.viewer_widget
    workplane = Workplane.world_xy()

    # Profile: a small circle off to the side; will be revolved around
    # the construction line below.
    profile = make_circle_profile_at(workplane, (30.0, 0.0), 5.0)
    profile_id = scene.add_shape(
        profile,
        meta={
            "kind": SKETCH_META_KIND,
            "profile": "circle",
            "workplane": "XY",
            "workplane_origin": (0.0, 0.0, 0.0),
            "workplane_x_direction": (1.0, 0.0, 0.0),
            "workplane_y_direction": (0.0, 1.0, 0.0),
            "display_normal": (0.0, 0.0, 1.0),
            "radius": 5.0,
            "center_u": 30.0,
            "center_v": 0.0,
        },
    )
    # Construction line along the Y axis (from (0,-20) to (0,20)) — the
    # circle should be revolved around this line to produce a torus.
    line_points = [(0.0, -20.0), (0.0, 20.0)]
    line_shape = make_polyline_preview(workplane, line_points)
    line_id = scene.add_shape(
        line_shape,
        meta={
            "kind": SKETCH_ENTITY_META_KIND,
            "profile": "line_segments",
            "workplane": "XY",
            "workplane_origin": (0.0, 0.0, 0.0),
            "workplane_x_direction": (1.0, 0.0, 0.0),
            "workplane_y_direction": (0.0, 1.0, 0.0),
            "display_normal": (0.0, 0.0, 1.0),
            "points_uv": line_points,
        },
    )

    scene.set_selections(
        (
            SelectionRef(profile_id, SelectionKind.FACE, 1),
            SelectionRef(line_id, SelectionKind.OBJECT, 0),
        )
    )
    widget._set_active_category("select")
    enabled = main_window.actions["sketch_revolve"].isEnabled()
    print(f"\n[revolve_axis] sketch_revolve enabled with profile+line = {enabled}")
    axis_data = widget._custom_revolve_axis_from_selection(scene.selection_refs())
    print(f"  custom axis: {axis_data}")
    if axis_data is not None:
        start, axis = axis_data
        # Expected axis ~= (0, 1, 0) since line is from -Y to +Y at X=0.
        if abs(axis[0]) < 1e-3 and axis[1] > 0.99 and abs(axis[2]) < 1e-3:
            print("  OK: axis vector matches the Y direction of the line")
        else:
            print(f"  FAIL: axis vector {axis} != (0, 1, 0)")
    main_window.window.close()


if __name__ == "__main__":
    raise SystemExit(main())
