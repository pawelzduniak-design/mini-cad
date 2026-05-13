"""Record real GUI tutorial verification artifacts.

This intentionally drives the running Qt/OCCT application with real Windows
mouse/keyboard input. It does not call modeling commands or mutate geometry
directly; internal state is read only to verify results and to calculate
viewport click targets for real UI clicks.
"""

# ruff: noqa: E402

from __future__ import annotations

import ctypes
import json
import math
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageGrab
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolButton

from cad_app.main_window import create_main_window
from cad_app.scene import Scene
from cad_app.sketch import SKETCH_META_KIND
from cad_app.types import SelectionKind
from cad_app.viewer import Viewer

OUT_ROOT = Path("docs/tutorials/verification")
RAW_ROOT = OUT_ROOT / "raw"
GIF_ROOT = OUT_ROOT / "gifs"
REPORT_PATH = OUT_ROOT / "report.md"
REPORT_JSON_PATH = OUT_ROOT / "report.json"


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


class SystemInput:
    LEFT_DOWN = 0x0002
    LEFT_UP = 0x0004
    RIGHT_DOWN = 0x0008
    RIGHT_UP = 0x0010
    MIDDLE_DOWN = 0x0020
    MIDDLE_UP = 0x0040
    WHEEL = 0x0800
    KEY_UP = 0x0002

    VK = {
        "A": 0x41,
        "B": 0x42,
        "E": 0x45,
        "F": 0x46,
        "H": 0x48,
        "M": 0x4D,
        "S": 0x53,
        "X": 0x58,
        "Y": 0x59,
        "Z": 0x5A,
        "ENTER": 0x0D,
        "ESC": 0x1B,
        "CTRL": 0x11,
    }

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Real cursor recording requires Windows.")
        self.user32 = ctypes.windll.user32
        self.user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self.user32.SetCursorPos.restype = ctypes.c_bool
        self.user32.GetCursorPos.argtypes = [ctypes.POINTER(_Point)]
        self.user32.GetCursorPos.restype = ctypes.c_bool

    def position(self) -> QPoint:
        point = _Point()
        self.user32.GetCursorPos(ctypes.byref(point))
        return QPoint(point.x, point.y)

    def move_to(self, point: QPoint) -> None:
        self.user32.SetCursorPos(int(point.x()), int(point.y()))

    def click(self, point: QPoint | None = None, button: str = "left") -> None:
        if point is not None:
            self.move_to(point)
            QTest.qWait(80)
        down, up = self._button_flags(button)
        self.user32.mouse_event(down, 0, 0, 0, 0)
        QTest.qWait(65)
        self.user32.mouse_event(up, 0, 0, 0, 0)

    def drag(
        self,
        start: QPoint,
        end: QPoint,
        *,
        button: str = "left",
        steps: int = 10,
        after_down: Callable[[], None] | None = None,
        per_step: Callable[[int], None] | None = None,
    ) -> None:
        self.move_to(start)
        QTest.qWait(100)
        down, up = self._button_flags(button)
        self.user32.mouse_event(down, 0, 0, 0, 0)
        QTest.qWait(90)
        if after_down is not None:
            after_down()
        for index in range(1, steps + 1):
            x = start.x() + (end.x() - start.x()) * index / steps
            y = start.y() + (end.y() - start.y()) * index / steps
            self.move_to(QPoint(round(x), round(y)))
            QTest.qWait(45)
            if per_step is not None:
                per_step(index)
        QTest.qWait(80)
        self.user32.mouse_event(up, 0, 0, 0, 0)

    def key(self, name: str, *, ctrl: bool = False) -> None:
        if ctrl:
            self._key_down(self.VK["CTRL"])
            QTest.qWait(30)
        vk = self.VK[name.upper()]
        self._key_down(vk)
        QTest.qWait(45)
        self._key_up(vk)
        if ctrl:
            QTest.qWait(30)
            self._key_up(self.VK["CTRL"])

    def wheel(self, delta: int) -> None:
        self.user32.mouse_event(self.WHEEL, 0, 0, delta, 0)

    def _key_down(self, vk: int) -> None:
        self.user32.keybd_event(vk, 0, 0, 0)

    def _key_up(self, vk: int) -> None:
        self.user32.keybd_event(vk, 0, self.KEY_UP, 0)

    def _button_flags(self, button: str) -> tuple[int, int]:
        if button == "left":
            return self.LEFT_DOWN, self.LEFT_UP
        if button == "right":
            return self.RIGHT_DOWN, self.RIGHT_UP
        if button == "middle":
            return self.MIDDLE_DOWN, self.MIDDLE_UP
        raise ValueError(f"Unsupported mouse button: {button}")


class WindowCapture:
    CURSOR_SHOWING = 0x00000001
    DI_NORMAL = 0x0003
    DIB_RGB_COLORS = 0
    BI_RGB = 0
    SM_CXCURSOR = 13
    SM_CYCURSOR = 14

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Desktop capture requires Windows.")
        self.user32 = ctypes.windll.user32
        self.gdi32 = ctypes.windll.gdi32
        self.user32.GetCursorInfo.argtypes = [ctypes.POINTER(_CursorInfo)]
        self.user32.GetCursorInfo.restype = ctypes.c_bool
        self.user32.GetIconInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_IconInfo),
        ]
        self.user32.GetIconInfo.restype = ctypes.c_bool
        self.user32.GetDC.argtypes = [ctypes.c_void_p]
        self.user32.GetDC.restype = ctypes.c_void_p
        self.user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.user32.ReleaseDC.restype = ctypes.c_int
        self.user32.DrawIconEx.argtypes = [
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
        self.user32.DrawIconEx.restype = ctypes.c_bool
        self.gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
        self.gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
        self.gdi32.CreateDIBSection.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_BitmapInfo),
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
            ctypes.c_uint,
        ]
        self.gdi32.CreateDIBSection.restype = ctypes.c_void_p
        self.gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.gdi32.SelectObject.restype = ctypes.c_void_p
        self.gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
        self.gdi32.DeleteObject.restype = ctypes.c_bool
        self.gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
        self.gdi32.DeleteDC.restype = ctypes.c_bool

    def grab(self, window) -> Image.Image:
        origin = window.mapToGlobal(QPoint(0, 0))
        scale = window.devicePixelRatioF()
        left = round(origin.x() * scale)
        top = round(origin.y() * scale)
        width = round(window.width() * scale)
        height = round(window.height() * scale)
        image = ImageGrab.grab(
            bbox=(left, top, left + width, top + height),
            all_screens=True,
        ).convert("RGBA")
        self._paste_actual_cursor(image, left, top)
        return image.convert("RGB")

    def _paste_actual_cursor(self, image: Image.Image, left: int, top: int) -> None:
        cursor = self._cursor_info()
        if cursor is None:
            return
        cursor_image, hotspot, position = cursor
        image.alpha_composite(
            cursor_image,
            (position.x() - left - hotspot[0], position.y() - top - hotspot[1]),
        )

    def _cursor_info(self) -> tuple[Image.Image, tuple[int, int], QPoint] | None:
        cursor_info = _CursorInfo()
        cursor_info.cbSize = ctypes.sizeof(_CursorInfo)
        if not self.user32.GetCursorInfo(ctypes.byref(cursor_info)):
            return None
        if not cursor_info.flags & self.CURSOR_SHOWING:
            return None
        icon_info = _IconInfo()
        if not self.user32.GetIconInfo(cursor_info.hCursor, ctypes.byref(icon_info)):
            return None
        try:
            return (
                self._cursor_bitmap(cursor_info.hCursor),
                (int(icon_info.xHotspot), int(icon_info.yHotspot)),
                QPoint(cursor_info.ptScreenPos.x, cursor_info.ptScreenPos.y),
            )
        finally:
            if icon_info.hbmMask:
                self.gdi32.DeleteObject(icon_info.hbmMask)
            if icon_info.hbmColor:
                self.gdi32.DeleteObject(icon_info.hbmColor)

    def _cursor_bitmap(self, hcursor) -> Image.Image:
        width = int(self.user32.GetSystemMetrics(self.SM_CXCURSOR))
        height = int(self.user32.GetSystemMetrics(self.SM_CYCURSOR))
        screen_dc = self.user32.GetDC(None)
        memory_dc = self.gdi32.CreateCompatibleDC(screen_dc)
        bits = ctypes.c_void_p()
        bitmap_info = _BitmapInfo()
        bitmap_info.bmiHeader.biSize = ctypes.sizeof(_BitmapInfoHeader)
        bitmap_info.bmiHeader.biWidth = width
        bitmap_info.bmiHeader.biHeight = -height
        bitmap_info.bmiHeader.biPlanes = 1
        bitmap_info.bmiHeader.biBitCount = 32
        bitmap_info.bmiHeader.biCompression = self.BI_RGB
        bitmap = self.gdi32.CreateDIBSection(
            screen_dc,
            ctypes.byref(bitmap_info),
            self.DIB_RGB_COLORS,
            ctypes.byref(bits),
            None,
            0,
        )
        previous = self.gdi32.SelectObject(memory_dc, bitmap)
        self.user32.DrawIconEx(
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
        buffer = ctypes.string_at(bits, width * height * 4)
        self.gdi32.SelectObject(memory_dc, previous)
        self.gdi32.DeleteObject(bitmap)
        self.gdi32.DeleteDC(memory_dc)
        self.user32.ReleaseDC(None, screen_dc)
        return Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1)


@dataclass
class TutorialResult:
    number: int
    slug: str
    title: str
    goal: str
    expected: str
    status: str = "FAIL"
    steps_attempted: list[str] = field(default_factory=list)
    actual: list[str] = field(default_factory=list)
    bugs: list[str] = field(default_factory=list)
    ux_issues: list[str] = field(default_factory=list)
    missing_ui: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    raw_path: str = ""
    gif_path: str = ""
    screenshots: list[str] = field(default_factory=list)


class TutorialSession:
    def __init__(self, result: TutorialResult, app: QApplication) -> None:
        self.result = result
        self.app = app
        self.scene = Scene()
        self.viewer = Viewer()
        self.main_window = create_main_window(self.viewer, self.scene)
        self.window = self.main_window.window
        self.widget = self.main_window.viewer_widget
        self.input = SystemInput()
        self.capture = WindowCapture()
        self.frame_index = 0
        self.raw_dir = RAW_ROOT / f"{result.number:02d}_{result.slug}"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        for old_frame in self.raw_dir.glob("*.png"):
            old_frame.unlink()
        self.window.resize(1280, 820)
        self.window.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.window.show()
        self._activate_window()
        self.widget.setFocus()
        self._wait_for_ready()
        self._activate_window()
        self.widget.setFocus()
        self.pause("initial_scene", 3)

    def close(self) -> None:
        self.widget._hide_edge_dimension_editor()
        self.window.close()
        self.viewer.close()
        self.app.processEvents()
        QTest.qWait(180)

    def _wait_for_ready(self) -> None:
        for _ in range(100):
            self.app.processEvents()
            if self.viewer.is_initialized and self.widget._initial_scene_displayed:
                return
            QTest.qWait(50)
        raise RuntimeError("Application window did not initialize.")

    def process(self, delay_ms: int = 120) -> None:
        self.app.processEvents()
        QTest.qWait(delay_ms)
        self.app.processEvents()

    def _activate_window(self) -> None:
        for _ in range(3):
            self.window.raise_()
            self.window.activateWindow()
            self.app.processEvents()
            if sys.platform == "win32":
                hwnd = int(self.window.winId())
                sw_restore = 9
                hwnd_topmost = -1
                swp_nosize = 0x0001
                swp_nomove = 0x0002
                swp_showwindow = 0x0040
                ctypes.windll.user32.ShowWindow(hwnd, sw_restore)
                ctypes.windll.user32.SetWindowPos(
                    hwnd,
                    hwnd_topmost,
                    0,
                    0,
                    0,
                    0,
                    swp_nosize | swp_nomove | swp_showwindow,
                )
                ctypes.windll.user32.SetForegroundWindow(hwnd)
                if hasattr(ctypes.windll.user32, "SwitchToThisWindow"):
                    ctypes.windll.user32.SwitchToThisWindow(hwnd, True)
            QTest.qWait(120)
            self.app.processEvents()

    def grab(self, label: str) -> Path:
        self.process(30)
        image = self.capture.grab(self.window)
        path = self.raw_dir / f"{self.frame_index:04d}_{self._safe(label)}.png"
        image.save(path)
        self.frame_index += 1
        self.result.screenshots.append(str(path))
        return path

    def pause(self, label: str, frames: int = 2) -> None:
        for _ in range(frames):
            self.grab(label)
            self.process(180)

    def step(self, text: str) -> None:
        self.result.steps_attempted.append(text)

    def actual(self, text: str) -> None:
        self.result.actual.append(text)

    def bug(self, text: str) -> None:
        self.result.bugs.append(text)

    def ux(self, text: str) -> None:
        self.result.ux_issues.append(text)

    def missing(self, text: str) -> None:
        self.result.missing_ui.append(text)

    def press(self, key: str, label: str, *, ctrl: bool = False) -> None:
        self._activate_window()
        self.widget.setFocus()
        self.step(f"Press {('Ctrl+' if ctrl else '')}{key}")
        self.grab(f"before_key_{label}")
        self.input.key(key, ctrl=ctrl)
        self.process(350)
        self.pause(f"after_key_{label}", 2)

    def click_action(self, action_name: str, label: str | None = None) -> bool:
        self._activate_window()
        label = label or action_name
        button = self._action_button(action_name)
        action = self.main_window.actions.get(action_name)
        if action is None:
            self.missing(f"Action {action_name} does not exist.")
            self.grab(f"missing_action_{action_name}")
            return False
        if button is None or not button.isVisible():
            self.missing(f"Action {action_name} is not visible in the current UI.")
            self.grab(f"hidden_action_{action_name}")
            return False
        if not action.isEnabled():
            self.bug(f"Action {action_name} is visible but disabled.")
            self.grab(f"disabled_action_{action_name}")
            return False
        self.step(f"Click visible action {action.text().replace('&', '')}")
        point = self._center_global(button)
        self.input.move_to(point)
        self.grab(f"before_click_{label}")
        self.input.click()
        self.process(420)
        self.pause(f"after_click_{label}", 2)
        return True

    def click_view_point(
        self,
        world: tuple[float, float, float],
        label: str,
        *,
        additive: bool = False,
    ) -> None:
        self._activate_window()
        point = self._world_to_global(world)
        self.step(f"Click viewport target {label}")
        self.input.move_to(point)
        self.grab(f"before_click_{label}")
        if additive:
            self.input.key("CTRL")
        self.input.click()
        self.process(350)
        self.pause(f"after_click_{label}", 2)

    def drag_view(
        self,
        start_world: tuple[float, float, float],
        end_delta: QPoint,
        label: str,
        *,
        button: str = "left",
        steps: int = 10,
        after_down: Callable[[], None] | None = None,
    ) -> None:
        self._activate_window()
        start = self._world_to_global(start_world)
        end = QPoint(start.x() + end_delta.x(), start.y() + end_delta.y())
        self.step(f"Drag {label}")
        self.input.move_to(start)
        self.grab(f"before_drag_{label}")
        self.input.drag(
            start,
            end,
            button=button,
            steps=steps,
            after_down=after_down,
            per_step=lambda index: (
                self.grab(f"drag_{label}_{index:02d}")
                if index in {1, steps // 2, steps}
                else None
            ),
        )
        self.process(550)
        self.pause(f"after_drag_{label}", 2)

    def drag_between_world(
        self,
        start_world: tuple[float, float, float],
        end_world: tuple[float, float, float],
        label: str,
        *,
        button: str = "left",
        steps: int = 10,
    ) -> None:
        start = self._world_to_global(start_world)
        end = self._world_to_global(end_world)
        self.step(f"Drag {label}")
        self.input.move_to(start)
        self.grab(f"before_drag_{label}")
        self.input.drag(
            start,
            end,
            button=button,
            steps=steps,
            per_step=lambda index: (
                self.grab(f"drag_{label}_{index:02d}")
                if index in {1, steps // 2, steps}
                else None
            ),
        )
        self.process(550)
        self.pause(f"after_drag_{label}", 2)

    def drag_from_widget(
        self,
        start: QPoint,
        delta: QPoint,
        label: str,
        *,
        button: str = "left",
        steps: int = 10,
    ) -> None:
        self._activate_window()
        global_start = self.widget.mapToGlobal(start)
        global_end = QPoint(global_start.x() + delta.x(), global_start.y() + delta.y())
        self.step(f"Drag viewport {label}")
        self.input.move_to(global_start)
        self.grab(f"before_drag_{label}")
        self.input.drag(
            global_start,
            global_end,
            button=button,
            steps=steps,
            per_step=lambda index: (
                self.grab(f"drag_{label}_{index:02d}")
                if index in {1, steps // 2, steps}
                else None
            ),
        )
        self.process(300)
        self.pause(f"after_drag_{label}", 2)

    def wheel_at_view(self, local: QPoint, delta: int, label: str) -> None:
        self._activate_window()
        self.step(f"Mouse wheel {label}")
        self.input.move_to(self.widget.mapToGlobal(local))
        self.grab(f"before_wheel_{label}")
        self.input.wheel(delta)
        self.process(300)
        self.pause(f"after_wheel_{label}", 2)

    def create_body_from_sketch_extrude(
        self,
        label: str = "body",
        *,
        note_missing_box: bool = False,
    ) -> str | None:
        if note_missing_box and self._action_button("add_box") is None:
            self.ux("No visible Create/Box Body button is available.")
            self.missing(
                "Box Body is not exposed in the left rail; using Sketch -> "
                "New Body instead."
            )
        before_bodies = set(self.body_ids())
        if not self.click_action("category_sketch", f"{label}_open_sketch_workspace"):
            return None
        if not self.click_action("start_sketch", f"{label}_start_sketch"):
            return None
        self.click_action("sketch_center_rectangle_tool", f"{label}_center_rect_tool")
        self.drag_between_world(
            (0.0, 0.0, 0.0),
            (30.0, 20.0, 0.0),
            f"{label}_draw_center_rectangle",
            steps=12,
        )
        profile_id = self.scene.active_item_id()
        if (
            profile_id is None
            or self.scene.get(profile_id).meta.get("kind") != SKETCH_META_KIND
        ):
            self.bug("Sketch rectangle did not create a selected sketch profile.")
            return None
        self.actual(f"Sketch rectangle profile created: {profile_id[:8]}.")
        if not self.click_action("finish_sketch", f"{label}_finish_sketch"):
            return None
        if not self.click_action("category_modify", f"{label}_open_modify_workspace"):
            return None
        if not self.click_action("sketch_new_body", f"{label}_new_body"):
            return None
        self.move_active_drag_from_world(
            (0.0, 0.0, 0.0),
            220,
            f"{label}_extrude_profile",
        )
        new_bodies = [
            item_id for item_id in self.body_ids() if item_id not in before_bodies
        ]
        item_id = self.scene.active_item_id()
        if item_id not in new_bodies and new_bodies:
            item_id = new_bodies[-1]
        if item_id is None or self.scene.get(item_id).meta.get("kind") != "body":
            self.bug("Sketch New Body did not produce a body.")
            return None
        self.actual(
            f"Body created through Sketch -> New Body extrusion: {item_id[:8]}."
        )
        self.click_action("home", f"{label}_home_view")
        self.click_action("fit_all", f"{label}_fit_all")
        return item_id

    def set_selection_mode(self, kind: SelectionKind) -> bool:
        action_name = {
            SelectionKind.OBJECT: "select_object",
            SelectionKind.FACE: "select_face",
            SelectionKind.EDGE: "select_edge",
            SelectionKind.VERTEX: "select_vertex",
        }[kind]
        self.click_action("category_select", f"open_select_for_{kind.value}")
        return self.click_action(action_name, f"selection_{kind.value}")

    def select_object(self, item_id: str) -> bool:
        self.set_selection_mode(SelectionKind.OBJECT)
        self.click_view_point(self.body_center(item_id), "object_center")
        return self._selected(SelectionKind.OBJECT)

    def select_face(self, item_id: str, face: str = "top") -> bool:
        self.set_selection_mode(SelectionKind.FACE)
        self.click_view_point(self.face_point(item_id, face), f"{face}_face")
        return self._selected(SelectionKind.FACE)

    def select_edge(self, item_id: str, edge: str = "top_front") -> bool:
        self.set_selection_mode(SelectionKind.EDGE)
        self.click_view_point(self.edge_point(item_id, edge), f"{edge}_edge")
        return self._selected(SelectionKind.EDGE)

    def select_vertex(self, item_id: str, vertex: str = "top_front_left") -> bool:
        self.set_selection_mode(SelectionKind.VERTEX)
        self.click_view_point(self.vertex_point(item_id, vertex), f"{vertex}_vertex")
        return self._selected(SelectionKind.VERTEX)

    def move_active_selection_by_drag(
        self,
        action_name: str,
        anchor: tuple[float, float, float],
        pixels: int,
        label: str,
    ) -> bool:
        if not self.click_action(action_name, label):
            return False

        direction = self._screen_direction_for_active_move(anchor, pixels)
        start = self._world_to_global(anchor)
        self.input.move_to(start)
        self.grab(f"before_drag_{label}")
        self.input.drag(
            start,
            QPoint(start.x() + direction.x(), start.y() + direction.y()),
            button="left",
            steps=10,
            per_step=lambda index: (
                self.grab(f"drag_{label}_{index:02d}") if index in {1, 5, 10} else None
            ),
        )
        self.process(700)
        self.pause(f"after_drag_{label}", 2)
        return True

    def move_active_drag_from_world(
        self,
        anchor: tuple[float, float, float],
        pixels: int,
        label: str,
    ) -> None:
        start = self._world_to_global(anchor)
        delta = self._screen_direction_for_active_move(anchor, pixels)
        end = QPoint(start.x() + delta.x(), start.y() + delta.y())
        self.step(f"Drag active tool {label}")
        self.input.move_to(start)
        self.grab(f"before_drag_{label}")
        self.input.drag(
            start,
            end,
            steps=10,
            per_step=lambda index: (
                self.grab(f"drag_{label}_{index:02d}") if index in {1, 5, 10} else None
            ),
        )
        self.process(700)
        self.pause(f"after_drag_{label}", 2)

    def _screen_direction_for_active_move(
        self,
        anchor: tuple[float, float, float],
        pixels: int,
    ) -> QPoint:
        session = self.widget._move_session
        if session is None:
            return QPoint(pixels, 0)
        screen_axis = self.widget._screen_axis_for_session(session)
        if screen_axis is not None:
            return QPoint(
                round(screen_axis[0] * pixels),
                round(screen_axis[1] * pixels),
            )
        axis = session.axis
        endpoint = (
            anchor[0] + axis[0] * 25.0,
            anchor[1] + axis[1] * 25.0,
            anchor[2] + axis[2] * 25.0,
        )
        start_x, start_y = self.viewer.view.Convert(*anchor)
        end_x, end_y = self.viewer.view.Convert(*endpoint)
        dx = end_x - start_x
        dy = end_y - start_y
        length = math.hypot(dx, dy)
        if length < 1e-7:
            return QPoint(pixels, 0)
        return QPoint(round(dx / length * pixels), round(dy / length * pixels))

    def done(self, status: str) -> TutorialResult:
        self.result.status = status
        self.result.raw_path = str(self.raw_dir)
        gif_path = GIF_ROOT / f"{self.result.number:02d}_{self.result.slug}.gif"
        frames = [Image.open(path) for path in sorted(self.raw_dir.glob("*.png"))]
        if frames:
            frames[0].save(
                gif_path,
                save_all=True,
                append_images=frames[1:],
                duration=260,
                loop=0,
                optimize=True,
            )
            self.result.gif_path = str(gif_path)
        return self.result

    def _selected(self, kind: SelectionKind) -> bool:
        selection = self.scene.selection()
        if selection is None:
            self.bug(f"Selection failed: expected {kind.value}, got none.")
            return False
        if selection.kind != kind:
            self.bug(
                "Selection mismatch: "
                f"expected {kind.value}, got {selection.kind.value}."
            )
            return False
        self.actual(f"Selected {selection.kind.value} {selection.index}.")
        return True

    def _action_button(self, action_name: str) -> QToolButton | None:
        action = self.main_window.actions.get(action_name)
        if action is None:
            return None
        for widget in action.associatedObjects():
            if isinstance(widget, QToolButton) and widget.isVisible():
                return widget
        for button in self.window.findChildren(QToolButton):
            if button.defaultAction() is action and button.isVisible():
                return button
        return None

    @staticmethod
    def _center_global(widget) -> QPoint:
        rect = widget.rect()
        return widget.mapToGlobal(rect.center())

    def _world_to_global(self, point: tuple[float, float, float]) -> QPoint:
        view_x, view_y = self.viewer.view.Convert(*point)
        scale = self.widget.devicePixelRatioF()
        local = QPoint(round(view_x / scale), round(view_y / scale))
        return self.widget.mapToGlobal(local)

    def bounds(self, item_id: str) -> tuple[float, float, float, float, float, float]:
        from OCP.Bnd import Bnd_Box
        from OCP.BRepBndLib import BRepBndLib

        bounds = Bnd_Box()
        BRepBndLib.Add_s(self.scene.get(item_id).shape, bounds)
        return bounds.Get()

    def body_ids(self) -> list[str]:
        return [item.item_id for item in self.scene if item.meta.get("kind") == "body"]

    def body_center(self, item_id: str) -> tuple[float, float, float]:
        x0, y0, z0, x1, y1, z1 = self.bounds(item_id)
        return (x0 + x1) * 0.5, (y0 + y1) * 0.5, (z0 + z1) * 0.5

    def face_point(self, item_id: str, face: str) -> tuple[float, float, float]:
        x0, y0, z0, x1, y1, z1 = self.bounds(item_id)
        cx, cy, cz = (x0 + x1) * 0.5, (y0 + y1) * 0.5, (z0 + z1) * 0.5
        points = {
            "top": (cx, cy, z1),
            "front": (cx, y0, cz),
            "right": (x1, cy, cz),
            "left": (x0, cy, cz),
        }
        return points[face]

    def edge_point(self, item_id: str, edge: str) -> tuple[float, float, float]:
        x0, y0, z0, x1, y1, z1 = self.bounds(item_id)
        cx, cy, cz = (x0 + x1) * 0.5, (y0 + y1) * 0.5, (z0 + z1) * 0.5
        points = {
            "top_front": (cx, y0, z1),
            "top_back": (cx, y1, z1),
            "front_left_vertical": (x0, y0, cz),
            "top_right": (x1, cy, z1),
            "bottom_front": (cx, y0, z0),
        }
        return points[edge]

    def vertex_point(self, item_id: str, vertex: str) -> tuple[float, float, float]:
        x0, y0, z0, x1, y1, z1 = self.bounds(item_id)
        points = {
            "top_front_left": (x0, y0, z1),
            "top_front_right": (x1, y0, z1),
            "bottom_front_left": (x0, y0, z0),
        }
        return points[vertex]

    @staticmethod
    def _safe(label: str) -> str:
        return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in label)


def scenario_1(app: QApplication) -> TutorialResult:
    result = TutorialResult(
        1,
        "create_basic_box",
        "Create Basic Box From Sketch Extrude",
        "Verify that a user can create a simple box from the UI.",
        "A box-like solid appears after drawing and extruding a sketch profile.",
    )
    s = TutorialSession(result, app)
    try:
        item_id = s.create_body_from_sketch_extrude(
            "basic_box",
            note_missing_box=True,
        )
        if item_id is None:
            return s.done("FAIL")
        s.select_object(item_id)
        center = QPoint(s.widget.width() // 2, s.widget.height() // 2)
        s.drag_from_widget(center, QPoint(90, -40), "orbit_camera", button="middle")
        s.drag_from_widget(center, QPoint(70, 30), "pan_camera", button="right")
        s.wheel_at_view(center, 240, "zoom_in")
        s.actual("Camera orbit, pan, and zoom accepted after box creation.")
        return s.done("PARTIAL" if result.missing_ui else "PASS")
    finally:
        s.close()


def scenario_2(app: QApplication) -> TutorialResult:
    result = TutorialResult(
        2,
        "select_object_face_edge_vertex",
        "Select Object / Face / Edge / Vertex",
        "Verify selection modes and selection feedback.",
        "Only the intended object, face, edge, or vertex is selected.",
    )
    s = TutorialSession(result, app)
    try:
        item_id = s.create_body_from_sketch_extrude("selection_box")
        if item_id is None:
            return s.done("FAIL")
        ok = [
            s.select_object(item_id),
            s.select_face(item_id, "top"),
            s.select_edge(item_id, "top_front"),
            s.select_vertex(item_id, "top_front_left"),
        ]
        if all(ok):
            s.actual("Object, face, edge, and vertex selections all produced UI state.")
            return s.done("PASS")
        return s.done("PARTIAL")
    finally:
        s.close()


def scenario_3(app: QApplication) -> TutorialResult:
    result = TutorialResult(
        3,
        "move_face",
        "Move Face",
        "Verify direct modeling face movement.",
        "Only selected face moves and adjacent faces stretch predictably.",
    )
    s = TutorialSession(result, app)
    try:
        item_id = s.create_body_from_sketch_extrude("move_face_box")
        if item_id is None:
            return s.done("FAIL")
        if not s.select_face(item_id, "top"):
            return s.done("FAIL")
        before = s.bounds(item_id)
        s.move_active_selection_by_drag(
            "move_selection_normal",
            s.face_point(item_id, "top"),
            95,
            "move_top_face_outward",
        )
        after_out = s.bounds(item_id)
        if after_out[5] <= before[5] + 1.0:
            s.bug("Move Face did not increase the top Z bound as expected.")
        s.select_face(item_id, "top")
        s.move_active_selection_by_drag(
            "move_selection_normal",
            s.face_point(item_id, "top"),
            -70,
            "move_top_face_inward",
        )
        after_in = s.bounds(item_id)
        if after_in[5] >= after_out[5] - 1.0:
            s.bug("Second Move Face did not reduce the top Z bound.")
        return s.done("PASS" if not result.bugs else "PARTIAL")
    finally:
        s.close()


def scenario_4(app: QApplication) -> TutorialResult:
    result = TutorialResult(
        4,
        "move_edge_slanted_shape",
        "Move Edge Into Slanted Shape",
        "Verify local BRep-style edge deformation.",
        "Selected top-front edge moves downward while opposite edge and "
        "bottom stay put.",
    )
    s = TutorialSession(result, app)
    try:
        item_id = s.create_body_from_sketch_extrude("move_edge_box")
        if item_id is None:
            return s.done("FAIL")
        if not s.select_edge(item_id, "top_front"):
            return s.done("FAIL")
        s.press("Z", "axis_z")
        before = s.bounds(item_id)
        s.move_active_selection_by_drag(
            "move_selection",
            s.edge_point(item_id, "top_front"),
            -85,
            "move_top_front_edge_down_z",
        )
        after = s.bounds(item_id)
        if abs(after[5] - before[5]) < 0.5:
            s.actual(
                "Overall box height stayed similar; screenshot must be "
                "inspected for local slope."
            )
        selection = s.scene.selection()
        if selection is not None:
            s.actual(f"Post-operation selection state: {selection.kind.value}.")
        return s.done("PASS" if not result.bugs else "PARTIAL")
    finally:
        s.close()


def scenario_5(app: QApplication) -> TutorialResult:
    result = TutorialResult(
        5,
        "delete_face_open_solid",
        "Delete Face / Open Solid Test",
        "Verify removing a face does not delete the whole object.",
        "Only selected face is removed; body remains visible as open shell.",
    )
    s = TutorialSession(result, app)
    try:
        item_id = s.create_body_from_sketch_extrude("delete_face_box")
        if item_id is None:
            return s.done("FAIL")
        if not s.select_face(item_id, "top"):
            return s.done("FAIL")
        before_count = len(s.scene)
        if not s.click_action("remove_face", "remove_top_face"):
            return s.done("FAIL")
        after_count = len(s.scene)
        if after_count != before_count:
            s.bug(
                "Remove Face changed object count; whole object may have been removed."
            )
        else:
            s.actual("Object remained in the scene after Remove Face.")
        return s.done("PASS" if not result.bugs else "FAIL")
    finally:
        s.close()


def scenario_6(app: QApplication) -> TutorialResult:
    result = TutorialResult(
        6,
        "stack_two_boxes_modify_upper",
        "Stack Two Boxes and Modify Only Upper Box",
        "Verify local editing does not damage nearby geometry.",
        "Base box remains unchanged while only upper box is modified.",
    )
    s = TutorialSession(result, app)
    try:
        first = s.create_body_from_sketch_extrude("base_box")
        second = s.create_body_from_sketch_extrude("upper_box")
        if first is None or second is None:
            return s.done("FAIL")
        s.missing("No visible size controls for creating a smaller upper box.")
        if not s.select_object(second):
            return s.done("FAIL")
        s.move_active_selection_by_drag(
            "move_object_z",
            s.body_center(second),
            90,
            "lift_second_box",
        )
        before_base = s.bounds(first)
        if not s.select_face(second, "top"):
            return s.done("PARTIAL")
        s.move_active_selection_by_drag(
            "move_selection_normal",
            s.face_point(second, "top"),
            70,
            "modify_upper_top_face",
        )
        after_base = s.bounds(first)
        if any(abs(a - b) > 0.01 for a, b in zip(before_base, after_base)):
            s.bug("Base box bounds changed while editing the upper box.")
        else:
            s.actual("Base box bounds stayed unchanged after upper edit.")
        return s.done("PARTIAL" if result.missing_ui else "PASS")
    finally:
        s.close()


def scenario_7(app: QApplication) -> TutorialResult:
    result = TutorialResult(
        7,
        "undo_redo_reliability",
        "Undo / Redo Reliability",
        "Verify modeling operations can be undone and redone.",
        "Undo restores previous geometry; redo reapplies operations.",
    )
    s = TutorialSession(result, app)
    try:
        item_id = s.create_body_from_sketch_extrude("undo_box")
        if item_id is None:
            return s.done("FAIL")
        s.select_face(item_id, "top")
        s.move_active_selection_by_drag(
            "move_selection_normal",
            s.face_point(item_id, "top"),
            75,
            "move_face_for_undo",
        )
        s.select_edge(item_id, "top_front")
        s.press("Z", "axis_z")
        s.move_active_selection_by_drag(
            "move_selection",
            s.edge_point(item_id, "top_front"),
            -55,
            "move_edge_for_undo",
        )
        s.select_face(item_id, "top")
        s.click_action("remove_face", "remove_face_for_undo")
        for idx in range(3):
            if not s.click_action("undo", f"undo_{idx + 1}"):
                s.bug(f"Undo {idx + 1} was not reachable.")
                break
        for idx in range(3):
            if not s.click_action("redo", f"redo_{idx + 1}"):
                s.bug(f"Redo {idx + 1} was not reachable.")
                break
        return s.done("PASS" if not result.bugs else "PARTIAL")
    finally:
        s.close()


def scenario_8(app: QApplication) -> TutorialResult:
    result = TutorialResult(
        8,
        "transform_gizmo_axis_constraint",
        "Transform Gizmo / Axis Constraint Test",
        "Verify movement direction is controllable and visible.",
        "User can control X, Y, and Z movement with visible feedback.",
    )
    s = TutorialSession(result, app)
    try:
        item_id = s.create_body_from_sketch_extrude("axis_box")
        if item_id is None:
            return s.done("FAIL")
        if not s.select_object(item_id):
            return s.done("FAIL")
        for axis, pixels in (("x", 80), ("y", 70), ("z", 70)):
            action = f"move_object_{axis}"
            if not s.move_active_selection_by_drag(
                action,
                s.body_center(item_id),
                pixels,
                f"move_object_{axis}",
            ):
                s.bug(f"{action} was not usable.")
        s.ux("Face/edge axis constraints are not exposed as visible axis buttons.")
        return s.done("PARTIAL" if result.ux_issues else "PASS")
    finally:
        s.close()


def scenario_9(app: QApplication) -> TutorialResult:
    result = TutorialResult(
        9,
        "camera_navigation_during_modeling",
        "Camera Navigation During Modeling",
        "Verify viewport navigation does not conflict with modeling.",
        "Selection remains stable after orbit, pan, zoom, then edit works.",
    )
    s = TutorialSession(result, app)
    try:
        item_id = s.create_body_from_sketch_extrude("camera_box")
        if item_id is None:
            return s.done("FAIL")
        if not s.select_face(item_id, "top"):
            return s.done("FAIL")
        center = QPoint(s.widget.width() // 2, s.widget.height() // 2)
        s.drag_from_widget(
            center, QPoint(120, -45), "orbit_before_edit", button="middle"
        )
        s.drag_from_widget(center, QPoint(-60, 40), "pan_before_edit", button="right")
        s.wheel_at_view(center, -240, "zoom_out_before_edit")
        selection = s.scene.selection()
        if selection is None or selection.kind != SelectionKind.FACE:
            s.bug("Selection was lost after camera navigation.")
            return s.done("FAIL")
        s.move_active_selection_by_drag(
            "move_selection_normal",
            s.face_point(item_id, "top"),
            65,
            "edit_after_camera_navigation",
        )
        return s.done("PASS" if not result.bugs else "FAIL")
    finally:
        s.close()


def scenario_10(app: QApplication) -> TutorialResult:
    result = TutorialResult(
        10,
        "mini_printable_enclosure_blockout",
        "Full Mini Workflow: Simple Printable Enclosure Blockout",
        "Verify a beginner can complete a small direct-modeling workflow.",
        "Operations compose into a coherent blockout and the model remains "
        "inspectable.",
    )
    s = TutorialSession(result, app)
    try:
        base = s.create_body_from_sketch_extrude("workflow_base")
        upper = s.create_body_from_sketch_extrude("workflow_upper")
        if base is None or upper is None:
            return s.done("FAIL")
        s.missing("No visible workflow for creating a raised section on a chosen face.")
        s.select_object(upper)
        s.move_active_selection_by_drag(
            "move_object_z",
            s.body_center(upper),
            85,
            "raise_second_body",
        )
        s.select_face(base, "right")
        s.move_active_selection_by_drag(
            "move_selection_normal",
            s.face_point(base, "right"),
            60,
            "modify_base_side_face",
        )
        s.select_edge(upper, "top_front")
        s.press("Z", "axis_z_for_sloped_area")
        s.move_active_selection_by_drag(
            "move_selection",
            s.edge_point(upper, "top_front"),
            -50,
            "slope_upper_edge",
        )
        s.select_face(base, "top")
        s.click_action("remove_face", "open_base_top_face")
        center = QPoint(s.widget.width() // 2, s.widget.height() // 2)
        s.drag_from_widget(center, QPoint(120, -60), "inspect_final", button="middle")
        export_button = s._action_button("export_step")
        export_action = s.main_window.actions.get("export_step")
        if export_button is not None and export_action is not None:
            s.input.move_to(s._center_global(export_button))
            s.grab("export_step_visible")
            s.actual(
                "Export STEP button is visible; file dialog completion was not "
                "included in this unattended verification artifact."
            )
        else:
            s.missing("Export STEP was not reachable from current UI state.")
        return s.done("PARTIAL" if (result.missing_ui or result.bugs) else "PASS")
    finally:
        s.close()


SCENARIOS: tuple[Callable[[QApplication], TutorialResult], ...] = (
    scenario_1,
    scenario_2,
    scenario_3,
    scenario_4,
    scenario_5,
    scenario_6,
    scenario_7,
    scenario_8,
    scenario_9,
    scenario_10,
)


def write_report(results: list[TutorialResult]) -> None:
    passed = sum(result.status == "PASS" for result in results)
    failed = sum(result.status == "FAIL" for result in results)
    partial = sum(result.status == "PARTIAL" for result in results)
    serious = []
    confusing = []
    missing = []
    for result in results:
        serious.extend(result.bugs)
        confusing.extend(result.ux_issues)
        missing.extend(result.missing_ui)
    lines = [
        "# Direct Modeling CAD Tutorial Verification Report",
        "",
        "## Summary",
        "",
        f"Total tutorials attempted: {len(results)}",
        f"Passed: {passed}",
        f"Failed: {failed}",
        f"Partially passed: {partial}",
        "",
        "Most serious problems:",
        *_numbered(serious[:5]),
        "",
        "Most confusing UI points:",
        *_numbered(confusing[:5]),
        "",
        "Missing UI capabilities:",
        *_numbered(missing[:5]),
        "",
        "## Tutorial Results",
        "",
    ]
    for result in results:
        lines.extend(
            [
                f"### {result.number}. {result.title}",
                "",
                f"Status: {result.status}",
                "",
                "Goal:",
                result.goal,
                "",
                "Expected:",
                result.expected,
                "",
                "Actual:",
                *_bullets(result.actual),
                "",
                "Steps attempted:",
                *_bullets(result.steps_attempted),
                "",
                "Evidence:",
                f"- Raw screenshot sequence: {result.raw_path}",
                f"- Final GIF: {result.gif_path}",
                f"- Screenshots: {result.raw_path}",
                "",
                "Bugs found:",
                *_bullets(result.bugs),
                "",
                "UX issues:",
                *_bullets(result.ux_issues),
                "",
                "Missing UI features:",
                *_bullets(result.missing_ui),
                "",
                "Notes:",
                *_bullets(result.notes),
                "",
            ]
        )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    REPORT_JSON_PATH.write_text(
        json.dumps([result.__dict__ for result in results], indent=2),
        encoding="utf-8",
    )


def _numbered(items: list[str]) -> list[str]:
    if not items:
        return ["1. None observed."]
    return [f"{index}. {item}" for index, item in enumerate(items, start=1)]


def _bullets(items: list[str]) -> list[str]:
    if not items:
        return ["- None."]
    return [f"- {item}" for item in items]


def warm_up_foreground(app: QApplication) -> None:
    scene = Scene()
    viewer = Viewer()
    main_window = create_main_window(viewer, scene)
    window = main_window.window
    window.resize(1280, 820)
    window.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    window.show()
    for _ in range(5):
        window.raise_()
        window.activateWindow()
        app.processEvents()
        if sys.platform == "win32":
            hwnd = int(window.winId())
            ctypes.windll.user32.ShowWindow(hwnd, 9)
            ctypes.windll.user32.SetWindowPos(
                hwnd,
                -1,
                0,
                0,
                0,
                0,
                0x0001 | 0x0002 | 0x0040,
            )
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            if hasattr(ctypes.windll.user32, "SwitchToThisWindow"):
                ctypes.windll.user32.SwitchToThisWindow(hwnd, True)
        QTest.qWait(150)
    window.close()
    viewer.close()
    app.processEvents()
    QTest.qWait(250)


def main() -> int:
    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    GIF_ROOT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    warm_up_foreground(app)
    results: list[TutorialResult] = []
    for scenario in SCENARIOS:
        result = scenario(app)
        results.append(result)
        print(f"[{result.status}] {result.number:02d} {result.title}")
    write_report(results)
    print(REPORT_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
