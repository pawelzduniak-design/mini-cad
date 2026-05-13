"""Capture the CAD window into screenshots plus machine-readable visual metrics."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QToolBar, QWidget

from cad_app.main_window import create_main_window
from cad_app.scene import Scene
from cad_app.viewer import Viewer


@dataclass(frozen=True)
class CaptureSpec:
    name: str
    actions: tuple[str, ...]
    flow_actions: tuple[str, ...] = ()
    expect_status: str | None = None
    expect_grid: bool = True
    expect_gizmo: bool = True


SCENARIOS: tuple[CaptureSpec, ...] = (
    CaptureSpec("startup", ()),
    CaptureSpec(
        "reactivated_viewport",
        ("reactivate_window",),
        flow_actions=("reactivate_window",),
    ),
    CaptureSpec(
        "sketch_mode",
        ("category_sketch",),
        flow_actions=("category_sketch",),
    ),
    CaptureSpec(
        "sketch_line",
        ("category_sketch", "start_sketch", "sketch_line_tool"),
        flow_actions=("start_sketch", "sketch_line_tool"),
    ),
    CaptureSpec(
        "gizmo_click_z",
        ("click_gizmo_z",),
        flow_actions=("click_gizmo_z",),
        expect_status="View: Top",
    ),
)


def _wait_for_initial_display(app, viewer, widget) -> None:
    for _ in range(80):
        app.processEvents()
        if viewer.is_initialized and widget._initial_scene_displayed:
            return
        QTest.qWait(50)
    raise RuntimeError("Viewer did not initialize and display the initial scene.")


def _widget_rect_in_window(window: QWidget, widget: QWidget) -> QRect:
    top_left = window.mapFromGlobal(widget.mapToGlobal(QPoint(0, 0)))
    return QRect(top_left, widget.size())


def _clipped_rect(image: QImage, rect: QRect) -> QRect:
    image_rect = QRect(0, 0, image.width(), image.height())
    return rect.intersected(image_rect)


def _region_metrics(
    image: QImage,
    rect: QRect,
    *,
    sample_step: int = 4,
) -> dict[str, Any]:
    rect = _clipped_rect(image, rect)
    if rect.isEmpty():
        return {
            "rect": _rect_dict(rect),
            "samples": 0,
            "black_ratio": 0.0,
            "very_dark_ratio": 0.0,
            "light_line_ratio": 0.0,
            "unique_colors": 0,
            "avg_rgb": [0, 0, 0],
            "dominant_axis_pixels": 0,
        }

    total = 0
    black = 0
    very_dark = 0
    light_line = 0
    red_axis = 0
    green_axis = 0
    blue_axis = 0
    colors: set[tuple[int, int, int]] = set()
    rgb_sum = [0, 0, 0]
    for y in range(rect.top(), rect.bottom() + 1, sample_step):
        for x in range(rect.left(), rect.right() + 1, sample_step):
            color = image.pixelColor(x, y)
            red = color.red()
            green = color.green()
            blue = color.blue()
            total += 1
            rgb_sum[0] += red
            rgb_sum[1] += green
            rgb_sum[2] += blue
            colors.add((red // 8 * 8, green // 8 * 8, blue // 8 * 8))
            if red < 8 and green < 8 and blue < 8:
                black += 1
            if red < 24 and green < 24 and blue < 24:
                very_dark += 1
            if (
                max(red, green, blue) >= 85
                and max(red, green, blue)
                - min(
                    red,
                    green,
                    blue,
                )
                <= 34
            ):
                light_line += 1
            if red > 125 and red > green * 1.45 and red > blue * 1.45:
                red_axis += 1
            if green > 125 and green > red * 1.35 and green > blue * 1.35:
                green_axis += 1
            if blue > 125 and blue > red * 1.35 and blue > green * 1.35:
                blue_axis += 1

    avg = [round(value / total, 2) for value in rgb_sum] if total else [0, 0, 0]
    return {
        "rect": _rect_dict(rect),
        "samples": total,
        "black_ratio": round(black / total, 4) if total else 0.0,
        "very_dark_ratio": round(very_dark / total, 4) if total else 0.0,
        "light_line_ratio": round(light_line / total, 4) if total else 0.0,
        "unique_colors": len(colors),
        "avg_rgb": avg,
        "dominant_axis_pixels": red_axis + green_axis + blue_axis,
        "axis_pixels": {
            "red": red_axis,
            "green": green_axis,
            "blue": blue_axis,
        },
    }


def _black_components(
    image: QImage,
    rect: QRect,
    *,
    sample_step: int = 6,
    min_samples: int = 80,
) -> list[dict[str, Any]]:
    rect = _clipped_rect(image, rect)
    black_points: set[tuple[int, int]] = set()
    for grid_y, y in enumerate(range(rect.top(), rect.bottom() + 1, sample_step)):
        for grid_x, x in enumerate(range(rect.left(), rect.right() + 1, sample_step)):
            color = image.pixelColor(x, y)
            if color.red() < 8 and color.green() < 8 and color.blue() < 8:
                black_points.add((grid_x, grid_y))

    components: list[dict[str, Any]] = []
    while black_points:
        start = black_points.pop()
        queue: deque[tuple[int, int]] = deque([start])
        points = [start]
        while queue:
            x, y = queue.popleft()
            for neighbor in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if neighbor not in black_points:
                    continue
                black_points.remove(neighbor)
                queue.append(neighbor)
                points.append(neighbor)
        if len(points) < min_samples:
            continue
        min_x = min(point[0] for point in points)
        min_y = min(point[1] for point in points)
        max_x = max(point[0] for point in points)
        max_y = max(point[1] for point in points)
        components.append(
            {
                "samples": len(points),
                "rect": {
                    "x": rect.left() + min_x * sample_step,
                    "y": rect.top() + min_y * sample_step,
                    "width": (max_x - min_x + 1) * sample_step,
                    "height": (max_y - min_y + 1) * sample_step,
                },
            }
        )
    return sorted(components, key=lambda item: item["samples"], reverse=True)


def _rect_dict(rect: QRect) -> dict[str, int]:
    return {
        "x": rect.x(),
        "y": rect.y(),
        "width": rect.width(),
        "height": rect.height(),
    }


def _toolbar_actions(window, toolbar_name: str) -> list[dict[str, Any]]:
    toolbar = window.findChild(QToolBar, toolbar_name)
    if toolbar is None:
        return []
    return [
        {
            "name": action.objectName(),
            "text": action.text(),
            "enabled": action.isEnabled(),
            "checked": action.isChecked(),
            "visible": action.isVisible(),
        }
        for action in toolbar.actions()
        if action.objectName()
    ]


def _overlay_state(widget) -> dict[str, Any]:
    overlays = {}
    for attr in (
        "_context_hint_overlay",
        "_sketch_plane_chooser",
        "_orientation_gizmo_overlay",
        "_selection_box_overlay",
        "_dimension_overlay",
    ):
        overlay = getattr(widget, attr, None)
        if overlay is None:
            continue
        overlays[attr.removeprefix("_")] = {
            "hidden": overlay.isHidden(),
            "visible": overlay.isVisible(),
            "geometry": _rect_dict(overlay.geometry()),
            "text": overlay.text() if isinstance(overlay, QLabel) else "",
        }
    return overlays


def _perform_capture_action(app, main_window, action_name: str) -> None:
    widget = main_window.viewer_widget
    if action_name == "reactivate_window":
        other_window = QWidget()
        other_window.setWindowTitle("CAD activation probe")
        other_window.resize(260, 120)
        other_window.show()
        other_window.raise_()
        other_window.activateWindow()
        app.processEvents()
        QTest.qWait(160)
        main_window.window.raise_()
        main_window.window.activateWindow()
        widget.setFocus()
        app.processEvents()
        QTest.qWait(260)
        other_window.close()
        app.processEvents()
        QTest.qWait(120)
        return
    if action_name == "click_gizmo_z":
        left, top, size = widget._orientation_gizmo_rect()
        point = QPoint(left + size // 2, top + 5)
        QTest.mousePress(
            widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point
        )
        QTest.mouseRelease(
            widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point
        )
        app.processEvents()
        QTest.qWait(120)
        return
    if action_name == "drag_gizmo":
        left, top, size = widget._orientation_gizmo_rect()
        start = QPoint(left + size // 2, top + size // 2)
        end = QPoint(start.x() + 28, start.y() - 16)
        QTest.mousePress(
            widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start
        )
        QTest.mouseMove(widget, end)
        QTest.mouseRelease(
            widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end
        )
        app.processEvents()
        QTest.qWait(120)
        return
    main_window.actions[action_name].trigger()
    app.processEvents()
    QTest.qWait(120)


def _capture_window(
    app,
    main_window,
    spec: CaptureSpec,
    out_dir: Path,
    *,
    run_actions: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    window = main_window.window
    widget = main_window.viewer_widget
    actions = spec.actions if run_actions is None else run_actions
    for action_name in actions:
        _perform_capture_action(app, main_window, action_name)
    app.processEvents()
    QTest.qWait(160)

    image = (
        widget.screen()
        .grabWindow(int(window.winId()))
        .toImage()
        .convertToFormat(QImage.Format.Format_RGB32)
    )
    screenshot = out_dir / f"{spec.name}.png"
    image.save(str(screenshot))

    viewport_rect = _widget_rect_in_window(window, widget)
    central_viewport = QRect(
        viewport_rect.left() + viewport_rect.width() // 8,
        viewport_rect.top() + viewport_rect.height() // 8,
        viewport_rect.width() * 3 // 4,
        viewport_rect.height() * 3 // 4,
    )
    gizmo_rect = QRect(
        viewport_rect.right() - 180,
        viewport_rect.bottom() - 180,
        170,
        170,
    )
    viewport_metrics = _region_metrics(image, viewport_rect)
    central_metrics = _region_metrics(image, central_viewport)
    gizmo_metrics = _region_metrics(image, gizmo_rect, sample_step=2)
    black_boxes = _black_components(image, viewport_rect)

    native_cube_present = (
        gizmo_metrics["light_line_ratio"] >= 0.04
        and gizmo_metrics["unique_colors"] >= 18
    )
    gizmo_present = (
        gizmo_metrics["dominant_axis_pixels"] >= 12
        or native_cube_present
        or not widget._orientation_gizmo_overlay.isHidden()
    )
    grid_present = central_metrics["light_line_ratio"] >= 0.006
    problems = []
    if viewport_metrics["black_ratio"] > 0.05:
        problems.append("viewport_black_ratio_high")
    if black_boxes:
        problems.append("large_black_components")
    if spec.expect_grid and not grid_present:
        problems.append("grid_not_detected")
    if spec.expect_gizmo and not gizmo_present:
        problems.append("gizmo_not_detected")

    ui_state = widget.get_ui_state()
    if spec.expect_status is not None and ui_state.status_text != spec.expect_status:
        problems.append("expected_status_not_seen")
    return {
        "name": spec.name,
        "actions": list(spec.actions),
        "screenshot": str(screenshot),
        "window_size": [image.width(), image.height()],
        "ui_state": {
            "work_mode": ui_state.work_mode,
            "selection_mode": ui_state.selection_mode,
            "selection_type": ui_state.selection_type,
            "active_tool": ui_state.active_tool,
            "status_text": ui_state.status_text,
            "hint_text": ui_state.hint_text,
            "context_actions": list(ui_state.context_actions),
        },
        "toolbars": {
            "command": _toolbar_actions(window, "CommandToolbar"),
            "category": _toolbar_actions(window, "CategoryToolbar"),
        },
        "overlays": _overlay_state(widget),
        "regions": {
            "viewport": viewport_metrics,
            "central_viewport": central_metrics,
            "gizmo": gizmo_metrics,
        },
        "detected": {
            "grid_present": grid_present,
            "gizmo_present": gizmo_present,
            "black_components": black_boxes,
        },
        "problems": problems,
    }


def _capture_spec(
    app: QApplication,
    spec: CaptureSpec,
    out_dir: Path,
    *,
    width: int,
    height: int,
) -> dict[str, Any]:
    viewer = Viewer()
    main_window = create_main_window(viewer, Scene())
    window = main_window.window
    widget = main_window.viewer_widget
    window.resize(width, height)
    window.show()
    widget.setFocus()
    try:
        _wait_for_initial_display(app, viewer, widget)
        return _capture_window(app, main_window, spec, out_dir)
    finally:
        viewer.close()
        window.close()
        app.processEvents()


def _capture_flow(
    app: QApplication,
    specs: tuple[CaptureSpec, ...],
    out_dir: Path,
    *,
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    viewer = Viewer()
    main_window = create_main_window(viewer, Scene())
    window = main_window.window
    widget = main_window.viewer_widget
    window.resize(width, height)
    window.show()
    widget.setFocus()
    try:
        _wait_for_initial_display(app, viewer, widget)
        return [
            _capture_window(
                app,
                main_window,
                spec,
                out_dir,
                run_actions=spec.flow_actions,
            )
            for spec in specs
        ]
    finally:
        window.close()
        viewer.close()
        app.processEvents()


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    app = QApplication.instance() or QApplication([])
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.scenario == "all":
        captures = _capture_flow(
            app,
            SCENARIOS,
            out_dir,
            width=args.width,
            height=args.height,
        )
    else:
        selected = next(spec for spec in SCENARIOS if spec.name == args.scenario)
        captures = [
            _capture_spec(
                app,
                selected,
                out_dir,
                width=args.width,
                height=args.height,
            )
        ]
    return {
        "width": args.width,
        "height": args.height,
        "captures": captures,
        "problems": [
            {"capture": capture["name"], "problem": problem}
            for capture in captures
            for problem in capture["problems"]
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=("all", *(spec.name for spec in SCENARIOS)),
        default="all",
    )
    parser.add_argument("--out-dir", default="out/visual_probe")
    parser.add_argument("--report", default="out/visual_probe/report.json")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=820)
    parser.add_argument("--fail-on-problems", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_probe(args)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.fail_on_problems and report["problems"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
