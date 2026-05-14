"""Generate short animated GIF tutorials from real CAD UI interactions."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import ctypes
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageGrab
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QApplication, QToolBar, QWidget

from cad_app.commands import translated_shape
from cad_app.engine import make_box
from cad_app.main_window import create_main_window
from cad_app.scene import Scene
from cad_app.sketch import is_sketch_profile
from cad_app.types import SelectionKind
from cad_app.viewer import Viewer
from cad_app.workplane import Workplane

DEFAULT_OUT_DIR = Path("docs/tutorials/gifs")


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _CursorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("hCursor", ctypes.c_void_p),
        ("ptScreenPos", _Point),
    ]


class _IconInfo(ctypes.Structure):
    _fields_ = [
        ("fIcon", ctypes.c_bool),
        ("xHotspot", ctypes.c_ulong),
        ("yHotspot", ctypes.c_ulong),
        ("hbmMask", ctypes.c_void_p),
        ("hbmColor", ctypes.c_void_p),
    ]


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_ulong),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", ctypes.c_ushort),
        ("biBitCount", ctypes.c_ushort),
        ("biCompression", ctypes.c_ulong),
        ("biSizeImage", ctypes.c_ulong),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", ctypes.c_ulong),
        ("biClrImportant", ctypes.c_ulong),
    ]


class _BitmapInfo(ctypes.Structure):
    _fields_ = [("bmiHeader", _BitmapInfoHeader), ("bmiColors", ctypes.c_ulong * 3)]


class SystemMouse:
    LEFT_DOWN = 0x0002
    LEFT_UP = 0x0004
    KEY_UP = 0x0002
    VK_CONTROL = 0x11

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("System mouse recording currently requires Windows.")
        self._user32 = ctypes.windll.user32
        self._user32.GetCursorPos.argtypes = [ctypes.POINTER(_Point)]
        self._user32.GetCursorPos.restype = ctypes.c_bool
        self._user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self._user32.SetCursorPos.restype = ctypes.c_bool

    def position(self) -> QPoint:
        point = _Point()
        self._user32.GetCursorPos(ctypes.byref(point))
        return QPoint(point.x, point.y)

    def move_to(self, point: QPoint) -> None:
        self._user32.SetCursorPos(int(point.x()), int(point.y()))

    def left_down(self, modifiers: Qt.KeyboardModifier = Qt.NoModifier) -> None:
        self._press_modifiers(modifiers)
        self._user32.mouse_event(self.LEFT_DOWN, 0, 0, 0, 0)

    def left_up(self, modifiers: Qt.KeyboardModifier = Qt.NoModifier) -> None:
        self._user32.mouse_event(self.LEFT_UP, 0, 0, 0, 0)
        self._release_modifiers(modifiers)

    def click(self, modifiers: Qt.KeyboardModifier = Qt.NoModifier) -> None:
        self.left_down(modifiers)
        QTest.qWait(45)
        self.left_up(modifiers)

    def _press_modifiers(self, modifiers: Qt.KeyboardModifier) -> None:
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            self._user32.keybd_event(self.VK_CONTROL, 0, 0, 0)

    def _release_modifiers(self, modifiers: Qt.KeyboardModifier) -> None:
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            self._user32.keybd_event(self.VK_CONTROL, 0, self.KEY_UP, 0)


class DesktopCapture:
    CURSOR_SHOWING = 0x00000001
    DI_NORMAL = 0x0003
    DIB_RGB_COLORS = 0
    BI_RGB = 0
    SM_CXCURSOR = 13
    SM_CYCURSOR = 14

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Desktop cursor capture currently requires Windows.")
        self._user32 = ctypes.windll.user32
        self._gdi32 = ctypes.windll.gdi32
        self._user32.GetCursorInfo.argtypes = [ctypes.POINTER(_CursorInfo)]
        self._user32.GetCursorInfo.restype = ctypes.c_bool
        self._user32.GetIconInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_IconInfo),
        ]
        self._user32.GetIconInfo.restype = ctypes.c_bool
        self._user32.GetDC.argtypes = [ctypes.c_void_p]
        self._user32.GetDC.restype = ctypes.c_void_p
        self._user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self._user32.ReleaseDC.restype = ctypes.c_int
        self._user32.DrawIconEx.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_uint,
        ]
        self._user32.DrawIconEx.restype = ctypes.c_bool
        self._gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
        self._gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
        self._gdi32.CreateDIBSection.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_BitmapInfo),
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
            ctypes.c_uint,
        ]
        self._gdi32.CreateDIBSection.restype = ctypes.c_void_p
        self._gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self._gdi32.SelectObject.restype = ctypes.c_void_p
        self._gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
        self._gdi32.DeleteObject.restype = ctypes.c_bool
        self._gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
        self._gdi32.DeleteDC.restype = ctypes.c_bool

    def grab_window(self, window, caption: str) -> Image.Image:
        left_top = window.mapToGlobal(QPoint(0, 0))
        scale = window.devicePixelRatioF()
        left = round(left_top.x() * scale)
        top = round(left_top.y() * scale)
        width = round(window.width() * scale)
        height = round(window.height() * scale)
        image = ImageGrab.grab(
            bbox=(left, top, left + width, top + height),
            all_screens=True,
        ).convert("RGBA")
        self._paste_system_cursor(image, left, top)
        self._draw_caption(image, caption)
        return image.convert("RGB")

    def _paste_system_cursor(self, image: Image.Image, left: int, top: int) -> None:
        cursor = self._cursor_info()
        if cursor is None:
            return
        cursor_image, hotspot = cursor
        position = self._cursor_position()
        paste_at = (
            position.x() - left - hotspot[0],
            position.y() - top - hotspot[1],
        )
        image.alpha_composite(cursor_image, paste_at)

    def _cursor_info(self) -> tuple[Image.Image, tuple[int, int]] | None:
        cursor_info = _CursorInfo()
        cursor_info.cbSize = ctypes.sizeof(_CursorInfo)
        if not self._user32.GetCursorInfo(ctypes.byref(cursor_info)):
            return None
        if not cursor_info.flags & self.CURSOR_SHOWING:
            return None
        icon_info = _IconInfo()
        if not self._user32.GetIconInfo(cursor_info.hCursor, ctypes.byref(icon_info)):
            return None
        try:
            hotspot = (int(icon_info.xHotspot), int(icon_info.yHotspot))
            return self._cursor_bitmap(cursor_info.hCursor), hotspot
        finally:
            if icon_info.hbmMask:
                self._gdi32.DeleteObject(icon_info.hbmMask)
            if icon_info.hbmColor:
                self._gdi32.DeleteObject(icon_info.hbmColor)

    def _cursor_bitmap(self, hcursor) -> Image.Image:
        width = int(self._user32.GetSystemMetrics(self.SM_CXCURSOR))
        height = int(self._user32.GetSystemMetrics(self.SM_CYCURSOR))
        screen_dc = self._user32.GetDC(None)
        memory_dc = self._gdi32.CreateCompatibleDC(screen_dc)
        bits = ctypes.c_void_p()
        bitmap_info = _BitmapInfo()
        bitmap_info.bmiHeader.biSize = ctypes.sizeof(_BitmapInfoHeader)
        bitmap_info.bmiHeader.biWidth = width
        bitmap_info.bmiHeader.biHeight = -height
        bitmap_info.bmiHeader.biPlanes = 1
        bitmap_info.bmiHeader.biBitCount = 32
        bitmap_info.bmiHeader.biCompression = self.BI_RGB
        bitmap = self._gdi32.CreateDIBSection(
            screen_dc,
            ctypes.byref(bitmap_info),
            self.DIB_RGB_COLORS,
            ctypes.byref(bits),
            None,
            0,
        )
        previous = self._gdi32.SelectObject(memory_dc, bitmap)
        try:
            ctypes.memset(bits, 0, width * height * 4)
            self._user32.DrawIconEx(
                memory_dc,
                0,
                0,
                hcursor,
                width,
                height,
                0,
                None,
                self.DI_NORMAL,
            )
            raw = ctypes.string_at(bits, width * height * 4)
            image = Image.frombuffer(
                "RGBA", (width, height), raw, "raw", "BGRA", 0, 1
            ).copy()
        finally:
            self._gdi32.SelectObject(memory_dc, previous)
            self._gdi32.DeleteObject(bitmap)
            self._gdi32.DeleteDC(memory_dc)
            self._user32.ReleaseDC(None, screen_dc)
        return self._ensure_cursor_alpha(image)

    @staticmethod
    def _ensure_cursor_alpha(image: Image.Image) -> Image.Image:
        alpha = image.getchannel("A")
        if alpha.getextrema() != (0, 0):
            return image
        mask = Image.new("L", image.size, 0)
        pixels = image.convert("RGB").load()
        mask_pixels = mask.load()
        for y in range(image.height):
            for x in range(image.width):
                if pixels[x, y] != (0, 0, 0):
                    mask_pixels[x, y] = 255
        image.putalpha(mask)
        return image

    def _cursor_position(self) -> QPoint:
        point = _Point()
        self._user32.GetCursorPos(ctypes.byref(point))
        return QPoint(point.x, point.y)

    @staticmethod
    def _draw_caption(image: Image.Image, caption: str) -> None:
        draw = ImageDraw.Draw(image, "RGBA")
        margin = 22
        height = 54
        width = min(620, image.width - margin * 2)
        top = image.height - height - margin
        draw.rounded_rectangle(
            (margin, top, margin + width, top + height),
            radius=8,
            fill=(13, 18, 26, 220),
        )
        draw.text(
            (margin + 18, top + 16),
            caption,
            fill=(245, 248, 252, 255),
        )


class TutorialRecorder:
    def __init__(
        self,
        name: str,
        out_dir: Path,
        *,
        width: int = 1120,
        height: int = 760,
        gif_width: int = 760,
        duration_ms: int = 70,
    ) -> None:
        self.name = name
        self.out_dir = out_dir
        self.gif_width = gif_width
        self.duration_ms = duration_ms
        self.frames: list[Image.Image] = []
        self.app = QApplication.instance() or QApplication([])
        self.scene = Scene()
        self.viewer = Viewer()
        self.main_window = create_main_window(self.viewer, self.scene)
        self.window = self.main_window.window
        self.widget = self.main_window.viewer_widget
        self.mouse = SystemMouse()
        self.capture_source = DesktopCapture()
        self.window.resize(width, height)
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        self.widget.setFocus()
        self._wait_for_initial_display()
        self.mouse.move_to(self.window.mapToGlobal(QPoint(120, 130)))

    def close(self) -> None:
        self.window.close()
        self.viewer.close()
        self.app.processEvents()

    def save(self) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.out_dir / f"{self.name}.gif"
        if not self.frames:
            raise RuntimeError("No tutorial frames were captured.")
        self.frames[0].save(
            output_path,
            save_all=True,
            append_images=self.frames[1:],
            duration=self.duration_ms,
            loop=0,
            optimize=True,
        )
        return output_path

    def hold(self, caption: str, frames: int = 10) -> None:
        self.capture(caption, frames=frames)

    def move_to(self, point: QPoint, caption: str, *, steps: int = 8) -> None:
        start = self.mouse.position()
        for index in range(1, steps + 1):
            t = index / steps
            next_point = QPoint(
                round(start.x() + (point.x() - start.x()) * t),
                round(start.y() + (point.y() - start.y()) * t),
            )
            self.mouse.move_to(next_point)
            self.wait(18)
            self.capture(caption)

    def click_action(self, action_name: str, caption: str) -> None:
        action = self.main_window.actions[action_name]
        if not action.isEnabled():
            raise RuntimeError(f"Tutorial action is disabled: {action_name}")
        _target, _local_point, screen_point = self._action_target(action_name)
        self.move_to(screen_point, caption)
        self.capture(caption, frames=3)
        self.mouse.click()
        self.wait(220)
        self.capture(caption, frames=5)

    def click_action_until(
        self,
        action_name: str,
        caption: str,
        predicate: Callable[[], bool],
        *,
        attempts: int = 2,
    ) -> None:
        for attempt in range(attempts):
            retry_caption = caption if attempt == 0 else f"{caption} again"
            self.click_action(action_name, retry_caption)
            if predicate():
                return
        raise RuntimeError(
            f"Tutorial action did not reach expected state: {action_name}"
        )

    def click_tool_done(self, caption: str) -> None:
        button = getattr(self.widget, "_tool_done_button", None)
        if not isinstance(button, QAbstractButton) or button.isHidden():
            raise RuntimeError("Tutorial Done button is not visible.")
        local_point = button.rect().center()
        screen_point = button.mapToGlobal(local_point)
        self.move_to(screen_point, caption)
        self.capture(caption, frames=3)
        self.mouse.click()
        self.wait(260)
        self.capture(caption, frames=8)

    def click_viewport(
        self,
        point: QPoint,
        caption: str,
        *,
        modifiers: Qt.KeyboardModifier = Qt.NoModifier,
    ) -> None:
        self.move_to(self.widget.mapToGlobal(point), caption)
        self.capture(caption, frames=3)
        self.mouse.click(modifiers)
        self.wait(180)
        self.capture(caption, frames=5)

    def drag_viewport(
        self,
        start: QPoint,
        end: QPoint,
        caption: str,
        *,
        steps: int = 10,
        modifiers: Qt.KeyboardModifier = Qt.NoModifier,
    ) -> None:
        self.move_to(self.widget.mapToGlobal(start), caption)
        self.mouse.left_down(modifiers)
        self.capture(caption, frames=2)
        for point in self._interpolated_points(start, end, steps):
            self.mouse.move_to(self.widget.mapToGlobal(point))
            self.wait(22)
            self.capture(caption)
        self.mouse.move_to(self.widget.mapToGlobal(end))
        self.mouse.left_up(modifiers)
        self.wait(220)
        self.capture(caption, frames=7)

    def draw_circle(
        self,
        center_uv: tuple[float, float],
        radius: float,
        caption: str,
    ) -> None:
        session = self.widget._sketch_session
        if session is None:
            raise RuntimeError("Circle draw requested without an active sketch.")
        before = self._sketch_profile_count()
        start = self.sketch_uv_to_widget_point(center_uv)
        end = self.sketch_uv_to_widget_point((center_uv[0] + radius, center_uv[1]))
        self.drag_viewport(start, end, caption, steps=12)
        if self._sketch_profile_count() <= before:
            raise RuntimeError(f"Circle was not created by viewport drag: {caption}")

    def click_sketch_points(
        self,
        points_uv: tuple[tuple[float, float], ...],
        caption: str,
        *,
        expect_new_profile: bool = False,
    ) -> None:
        before = self._sketch_profile_count()
        for uv in points_uv:
            self.click_viewport(self.sketch_uv_to_widget_point(uv), caption)
        if expect_new_profile and self._sketch_profile_count() <= before:
            raise RuntimeError(f"Sketch profile was not created by clicks: {caption}")

    def drag_active_tool_distance(self, value: float, caption: str) -> None:
        session = self.widget._move_session
        if session is None:
            raise RuntimeError(f"{caption}: no active move session.")
        start, end = self._drag_points_for_session_distance(session, value)
        self.drag_viewport(start, end, caption, steps=12)
        if self.widget._move_session is not None:
            raise RuntimeError(f"{caption}: drag did not commit the active tool.")

    def preload_body(self, shape, meta: dict[str, object], *, fit: bool = True) -> str:
        item_id = self.scene.add_shape(shape, meta=meta)
        self.scene.set_active_item(item_id)
        self.scene.set_selection(None)
        self.viewer.display_scene(self.scene, fit=fit)
        self.main_window.navigation.capture_home()
        self.widget._refresh_browser()
        self.widget._refresh_hud()
        self.widget._refresh_action_state()
        self.wait(220)
        return item_id

    def select_body_by_viewport_click(
        self,
        item_id: str,
        caption: str,
        *,
        modifiers: Qt.KeyboardModifier = Qt.NoModifier,
    ) -> None:
        self.widget._set_selection_kind(SelectionKind.OBJECT)
        point = self._body_pick_point(item_id)
        self.click_viewport(point, caption, modifiers=modifiers)
        selections = self.scene.selection_refs()
        if not any(selection.item_id == item_id for selection in selections):
            raise RuntimeError(f"Viewport click did not select body {item_id}.")

    def inspect_isometric(self, caption: str) -> None:
        self.move_to(self.viewport_window_point(0.78, 0.35), caption, steps=6)
        if self.viewer.view is not None and hasattr(self.viewer.view, "SetProj"):
            self.viewer.view.SetProj(1.0, -1.0, 0.75)
            if hasattr(self.viewer.view, "ZFitAll"):
                self.viewer.view.ZFitAll()
            if hasattr(self.viewer.view, "Redraw"):
                self.viewer.view.Redraw()
        self.wait(220)
        self.capture(caption, frames=10)

    def viewport_local_point(self, rel_x: float, rel_y: float) -> QPoint:
        return QPoint(
            round(self.widget.width() * rel_x),
            round(self.widget.height() * rel_y),
        )

    def viewport_window_point(self, rel_x: float, rel_y: float) -> QPoint:
        return self.widget.mapToGlobal(self.viewport_local_point(rel_x, rel_y))

    def sketch_uv_to_widget_point(self, uv: tuple[float, float]) -> QPoint:
        session = self.widget._sketch_session
        if session is None:
            raise RuntimeError("No active sketch session.")
        return self.workplane_uv_to_widget_point(session.workplane, uv)

    def workplane_uv_to_widget_point(
        self,
        workplane: Workplane,
        uv: tuple[float, float],
    ) -> QPoint:
        world = self.widget._workplane_point(workplane, uv)
        return self.world_to_widget_point(world)

    def world_to_widget_point(self, world: tuple[float, float, float]) -> QPoint:
        if not self.viewer.is_initialized:
            raise RuntimeError("Viewer is not initialized.")
        view_x, view_y = self.viewer.view.Convert(*world)
        scale = self.widget.devicePixelRatioF()
        return QPoint(round(float(view_x) / scale), round(float(view_y) / scale))

    def capture(self, caption: str, *, frames: int = 1) -> None:
        self.app.processEvents()
        source = self.capture_source.grab_window(self.window, caption)
        frame = self._qimage_to_pil(source)
        for _ in range(frames):
            self.frames.append(frame.copy())

    def wait(self, ms: int) -> None:
        self.app.processEvents()
        QTest.qWait(ms)
        self.app.processEvents()

    def _wait_for_initial_display(self) -> None:
        for _ in range(80):
            self.app.processEvents()
            if self.viewer.is_initialized and self.widget._initial_scene_displayed:
                return
            QTest.qWait(50)
        raise RuntimeError("Viewer did not initialize.")

    def _action_target(self, action_name: str) -> tuple[QWidget, QPoint, QPoint]:
        action = self.main_window.actions[action_name]
        for toolbar in self.window.findChildren(QToolBar):
            if action not in toolbar.actions():
                continue
            button = toolbar.widgetForAction(action)
            if button is not None and button.isVisible() and button.isEnabled():
                local_point = button.rect().center()
                return button, local_point, button.mapToGlobal(local_point)
            rect = toolbar.actionGeometry(action)
            if not rect.isValid() or rect.width() <= 1 or rect.height() <= 1:
                continue
            local_point = rect.center()
            return toolbar, local_point, toolbar.mapToGlobal(local_point)
        raise RuntimeError(
            f"Tutorial action is not visible in a toolbar: {action_name}"
        )

    @staticmethod
    def _interpolated_points(
        start: QPoint, end: QPoint, steps: int
    ) -> tuple[QPoint, ...]:
        points = []
        for index in range(1, steps + 1):
            t = index / steps
            points.append(
                QPoint(
                    round(start.x() + (end.x() - start.x()) * t),
                    round(start.y() + (end.y() - start.y()) * t),
                )
            )
        return tuple(points)

    def _drag_points_for_session_distance(
        self, session, value: float
    ) -> tuple[QPoint, QPoint]:
        scale = self.widget._move_pixels_to_units
        screen_axis = self.widget._screen_axis_for_session(session)
        pixels = value / scale
        if screen_axis is None:
            delta_x = pixels
            delta_y = 0.0
        else:
            delta_x = pixels * screen_axis[0]
            delta_y = pixels * screen_axis[1]
        return self._bounded_drag_points(delta_x, delta_y)

    def _bounded_drag_points(
        self, delta_x: float, delta_y: float
    ) -> tuple[QPoint, QPoint]:
        margin = 44

        def start_coord(limit: int, delta: float) -> int:
            if delta > 0:
                return round(max(margin, min(limit - margin, limit - margin - delta)))
            if delta < 0:
                return round(max(margin, min(limit - margin, margin - delta)))
            return limit // 2

        start = QPoint(
            start_coord(self.widget.width(), delta_x),
            start_coord(self.widget.height(), delta_y),
        )
        end = QPoint(round(start.x() + delta_x), round(start.y() + delta_y))
        if not self.widget.rect().contains(end):
            raise RuntimeError(f"Drag target is outside viewport: {start} -> {end}")
        return start, end

    def _body_pick_point(self, item_id: str) -> QPoint:
        scene_object = self.scene.get(item_id)
        center = self.widget._shape_center(scene_object.shape)
        candidates: list[QPoint] = []
        if center is not None:
            candidates.append(self.world_to_widget_point(center))
        candidates.extend(self._shape_bbox_widget_points(scene_object.shape))
        scale = self.widget.devicePixelRatioF()
        for point in candidates:
            for dx, dy in (
                (0, 0),
                (-8, 0),
                (8, 0),
                (0, -8),
                (0, 8),
                (-16, -16),
                (16, -16),
                (-16, 16),
                (16, 16),
            ):
                candidate = QPoint(point.x() + dx, point.y() + dy)
                if not self.widget.rect().contains(candidate):
                    continue
                result = self.main_window.picker.pick_object_result_at(
                    self.viewer.view,
                    round(candidate.x() * scale),
                    round(candidate.y() * scale),
                )
                if result is not None and result.selection.item_id == item_id:
                    return candidate
        raise RuntimeError(f"Could not find a viewport pick point for body {item_id}.")

    def _shape_bbox_widget_points(self, shape) -> list[QPoint]:
        points = self.main_window.picker._shape_screen_points(self.viewer.view, shape)
        if not points:
            return []
        scale = self.widget.devicePixelRatioF()
        xs = [point[0] / scale for point in points]
        ys = [point[1] / scale for point in points]
        left, right = min(xs), max(xs)
        top, bottom = min(ys), max(ys)
        center_x = (left + right) * 0.5
        center_y = (top + bottom) * 0.5
        return [
            QPoint(round(center_x), round(center_y)),
            QPoint(round(center_x), round(top + (bottom - top) * 0.33)),
            QPoint(round(center_x), round(top + (bottom - top) * 0.67)),
            QPoint(round(left + (right - left) * 0.33), round(center_y)),
            QPoint(round(left + (right - left) * 0.67), round(center_y)),
        ]

    def _sketch_profile_count(self) -> int:
        return sum(1 for item in self.scene if is_sketch_profile(item.meta))

    def _qimage_to_pil(self, image: Image.Image) -> Image.Image:
        pil_image = image.convert("RGB")
        if self.gif_width and pil_image.width > self.gif_width:
            target_height = round(pil_image.height * (self.gif_width / pil_image.width))
            pil_image = pil_image.resize(
                (self.gif_width, target_height),
                Image.Resampling.LANCZOS,
            )
        return pil_image.convert(
            "P",
            palette=Image.Palette.ADAPTIVE,
            colors=96,
        )


def generate_hat(out_dir: Path) -> Path:
    recorder = TutorialRecorder("01_hat_from_sketch_extrude", out_dir)
    try:
        recorder.hold("Start in a clean CAD workspace", frames=12)
        recorder.click_action_until(
            "category_sketch",
            "Open Sketch tools",
            lambda: recorder.widget._active_category == "sketch",
        )
        recorder.click_action_until(
            "start_sketch",
            "Start a sketch on the bottom plane",
            lambda: recorder.widget._sketch_session is not None,
        )
        recorder.click_action_until(
            "sketch_circle_tool",
            "Choose Circle",
            lambda: recorder.widget._sketch_session is not None
            and recorder.widget._sketch_session.tool == "circle",
        )
        recorder.draw_circle((0.0, 0.0), 58.0, "Drag on the workspace to draw the brim")
        recorder.click_action_until(
            "finish_sketch",
            "Finish the sketch",
            lambda: recorder.widget._sketch_session is None,
        )
        recorder.click_action_until(
            "category_modify",
            "Open profile tools",
            lambda: recorder.widget._active_category == "modify",
        )
        recorder.click_action_until(
            "push_pull",
            "Choose Push/Pull",
            lambda: recorder.widget._move_session is not None,
        )
        recorder.drag_active_tool_distance(6.0, "Drag in the viewport to pull the brim")

        recorder.click_action_until(
            "category_sketch",
            "Start the crown sketch",
            lambda: recorder.widget._active_category == "sketch",
        )
        recorder.click_action_until(
            "start_sketch",
            "Use the bottom plane again",
            lambda: recorder.widget._sketch_session is not None,
        )
        recorder.click_action_until(
            "sketch_circle_tool",
            "Choose Circle",
            lambda: recorder.widget._sketch_session is not None
            and recorder.widget._sketch_session.tool == "circle",
        )
        recorder.draw_circle(
            (0.0, 0.0), 29.0, "Drag on the workspace to draw the crown"
        )
        recorder.click_action_until(
            "finish_sketch",
            "Finish the sketch",
            lambda: recorder.widget._sketch_session is None,
        )
        recorder.click_action_until(
            "category_modify",
            "Open profile tools",
            lambda: recorder.widget._active_category == "modify",
        )
        recorder.click_action_until(
            "sketch_new_body",
            "Create a new body from the crown",
            lambda: recorder.widget._move_session is not None,
        )
        recorder.drag_active_tool_distance(58.0, "Drag upward to pull the crown")
        recorder.click_action("fit_all", "Fit the finished hat")
        recorder.inspect_isometric("Orbit to inspect the hat in 3D")
        recorder.hold("Result: a top hat from two real sketch drags", frames=18)
        return recorder.save()
    finally:
        recorder.close()


def generate_revolve(out_dir: Path) -> Path:
    recorder = TutorialRecorder("02_revolve_lid_from_side_profile", out_dir)
    try:
        recorder.hold("Revolve starts from a sketched profile", frames=12)
        recorder.click_action_until(
            "category_sketch",
            "Open Sketch tools",
            lambda: recorder.widget._active_category == "sketch",
        )
        recorder.click_action_until(
            "start_sketch",
            "Start a sketch on the bottom plane",
            lambda: recorder.widget._sketch_session is not None,
        )
        recorder.click_action_until(
            "sketch_arc_tool",
            "Choose Arc",
            lambda: recorder.widget._sketch_session is not None
            and recorder.widget._sketch_session.tool == "arc",
        )
        recorder.click_sketch_points(
            ((0.0, 35.0), (48.0, 10.0), (25.0, 39.0)),
            "Click three workspace points for the lid arc",
        )
        recorder.click_action_until(
            "sketch_line_tool",
            "Choose Line",
            lambda: recorder.widget._sketch_session is not None
            and recorder.widget._sketch_session.tool == "line",
        )
        recorder.click_sketch_points(
            ((0.0, 35.0), (0.0, 10.0), (48.0, 10.0)),
            "Click lines back to the arc endpoint",
            expect_new_profile=True,
        )
        recorder.click_action_until(
            "finish_sketch",
            "Finish the sketch",
            lambda: recorder.widget._sketch_session is None,
        )
        recorder.click_action_until(
            "category_modify",
            "Open profile tools",
            lambda: recorder.widget._active_category == "modify",
        )
        recorder.click_action_until(
            "sketch_revolve_y",
            "Choose Revolve around the profile axis",
            lambda: recorder.widget._move_session is not None
            and recorder.widget._move_session.tool == "sketch_revolve",
        )
        recorder.click_tool_done("Confirm the 360 degree revolve")
        recorder.click_action("fit_all", "Fit the revolved lid")
        recorder.inspect_isometric("Inspect the revolved body in 3D")
        recorder.hold("Result: a revolved CAD body", frames=18)
        return recorder.save()
    finally:
        recorder.close()


def generate_move_rotate(out_dir: Path) -> Path:
    recorder = TutorialRecorder("03_move_and_rotate_body", out_dir)
    try:
        body_id = recorder.preload_body(
            make_box(72.0, 54.0, 42.0),
            {"kind": "body", "source": "tutorial_box"},
        )
        recorder.hold("Start from a simple solid body", frames=8)
        recorder.select_body_by_viewport_click(
            body_id, "Click the body in the viewport"
        )
        recorder.click_action_until(
            "move_object",
            "Move the body",
            lambda: recorder.widget._move_session is not None,
        )
        recorder.widget._set_move_axis_from_manipulator("X")
        recorder.drag_active_tool_distance(34.0, "Drag to preview and commit the move")
        recorder.click_action_until(
            "rotate_body_z",
            "Rotate the body around Z",
            lambda: recorder.widget._move_session is not None
            and recorder.widget._move_session.tool == "rotate",
        )
        recorder.drag_active_tool_distance(32.0, "Drag to preview and commit rotation")
        recorder.click_action("display_wireframe", "Switch to wireframe for inspection")
        recorder.hold("Result: move and rotate are normal body operations", frames=18)
        return recorder.save()
    finally:
        recorder.close()


def generate_multi_body_move(out_dir: Path) -> Path:
    recorder = TutorialRecorder("04_multi_body_move", out_dir)
    try:
        first_id = recorder.preload_body(
            translated_shape(make_box(44.0, 44.0, 36.0), -48.0, 0.0, 0.0),
            {"kind": "body", "source": "tutorial_left_box"},
            fit=False,
        )
        second_id = recorder.preload_body(
            translated_shape(make_box(44.0, 44.0, 36.0), 48.0, 0.0, 0.0),
            {"kind": "body", "source": "tutorial_right_box"},
            fit=True,
        )
        recorder.hold("Multi-select starts from bodies already in the scene", frames=8)
        recorder.select_body_by_viewport_click(first_id, "Click the first body")
        recorder.select_body_by_viewport_click(
            second_id,
            "Ctrl-click the second body",
            modifiers=Qt.KeyboardModifier.ControlModifier,
        )
        recorder.click_action_until(
            "move_object",
            "Move both selected bodies",
            lambda: recorder.widget._move_session is not None,
        )
        recorder.widget._set_move_axis_from_manipulator("X")
        recorder.drag_active_tool_distance(
            32.0, "One viewport drag translates both bodies"
        )
        recorder.hold("Result: both bodies moved together", frames=18)
        return recorder.save()
    finally:
        recorder.close()


GENERATORS: dict[str, Callable[[Path], Path]] = {
    "hat": generate_hat,
    "revolve": generate_revolve,
    "move_rotate": generate_move_rotate,
    "multi_body": generate_multi_body_move,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=("all", *GENERATORS.keys()),
        default="all",
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir)
    selected = (
        GENERATORS.items()
        if args.scenario == "all"
        else ((args.scenario, GENERATORS[args.scenario]),)
    )
    outputs = []
    for name, generator in selected:
        print(f"[INFO] Generating {name}")
        output_path = generator(out_dir)
        outputs.append(output_path)
        print(f"[PASS] {output_path}")
    print("=== TUTORIAL GIFS ===")
    for output_path in outputs:
        print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
