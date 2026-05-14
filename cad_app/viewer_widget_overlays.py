"""Small Qt overlays drawn above the native CAD viewport."""

from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget


class OrientationGizmoOverlay(QWidget):
    """Shaded cube-style orientation indicator."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("OrientationGizmoOverlay")
        self.setFixedSize(156, 156)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._axis_name = "X"

    def set_axis_name(self, axis_name: str) -> None:
        self._axis_name = axis_name
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(44, 54, 64, 185))
        painter.drawRoundedRect(QRectF(4, 4, 148, 148), 10, 10)

        center = QPointF(78, 84)
        top = [
            QPointF(46, 52),
            QPointF(84, 34),
            QPointF(122, 53),
            QPointF(82, 74),
        ]
        left = [
            QPointF(46, 52),
            QPointF(82, 74),
            QPointF(82, 118),
            QPointF(46, 96),
        ]
        right = [
            QPointF(82, 74),
            QPointF(122, 53),
            QPointF(122, 98),
            QPointF(82, 118),
        ]
        painter.setPen(QPen(QColor(88, 98, 111), 1.2))
        painter.setBrush(QColor(72, 78, 86))
        painter.drawPolygon(top)
        painter.setBrush(QColor(54, 60, 68))
        painter.drawPolygon(left)
        painter.setBrush(QColor(63, 69, 78))
        painter.drawPolygon(right)

        label_font = QFont(self.font())
        label_font.setBold(True)
        label_font.setPointSize(8)
        painter.setFont(label_font)
        self._draw_labeled_text(painter, QRectF(64, 43, 42, 18), "Top")
        self._draw_labeled_text(painter, QRectF(48, 74, 34, 18), "Front")
        self._draw_labeled_text(painter, QRectF(86, 74, 40, 18), "Right")
        self._draw_view_buttons(painter)

        self._draw_axis(
            painter,
            center,
            QPointF(31, 111),
            QColor(226, 74, 64),
            "X",
        )
        self._draw_axis(
            painter,
            center,
            QPointF(35, 31),
            QColor(60, 145, 245),
            "Z",
        )
        self._draw_axis(
            painter,
            center,
            QPointF(131, 103),
            QColor(74, 196, 94),
            "Y",
        )

    def _draw_axis(
        self,
        painter: QPainter,
        start: QPointF,
        end: QPointF,
        color: QColor,
        label: str,
    ) -> None:
        pen = QPen(color, 3.0 if self._axis_name == label else 2.2)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawLine(start, end)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(end, 4.0, 4.0)
        painter.setPen(color)
        painter.drawText(
            QRectF(end.x() - 10, end.y() - 20, 20, 18),
            Qt.AlignCenter,
            label,
        )

    @staticmethod
    def _draw_labeled_text(painter: QPainter, rect: QRectF, label: str) -> None:
        shadow_rect = QRectF(rect)
        shadow_rect.translate(1.0, 1.0)
        painter.setPen(QColor(0, 0, 0, 230))
        painter.drawText(shadow_rect, Qt.AlignCenter, label)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(rect, Qt.AlignCenter, label)

    def _draw_view_buttons(self, painter: QPainter) -> None:
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSize(7)
        painter.setFont(font)
        for label, rect in self._view_button_rects().items():
            painter.setPen(QPen(QColor(92, 111, 128), 1.1))
            painter.setBrush(QColor(18, 26, 34, 226))
            painter.drawRoundedRect(rect, 4, 4)
            self._draw_labeled_text(painter, rect, label)

    def view_at(self, x: int, y: int) -> tuple[str, bool, str] | None:
        point = QPointF(float(x), float(y))
        for label, rect in self._view_button_rects().items():
            if rect.contains(point):
                return self._view_target(label)
        return self._cube_view_at(point)

    @staticmethod
    def _view_button_rects() -> dict[str, QRectF]:
        return {
            "Top": QRectF(58, 8, 40, 20),
            "Back": QRectF(58, 30, 40, 20),
            "Left": QRectF(8, 68, 40, 22),
            "Right": QRectF(108, 68, 40, 22),
            "Front": QRectF(54, 96, 48, 22),
            "Bottom": QRectF(47, 126, 62, 22),
        }

    @staticmethod
    def _view_target(label: str) -> tuple[str, bool, str]:
        targets = {
            "Top": ("z", True, "Top"),
            "Bottom": ("z", False, "Bottom"),
            "Left": ("x", False, "Left"),
            "Right": ("x", True, "Right"),
            "Front": ("y", False, "Front"),
            "Back": ("y", True, "Back"),
        }
        return targets[label]

    def _cube_view_at(self, point: QPointF) -> tuple[str, bool, str] | None:
        zones = {
            "Top": [
                QPointF(46, 52),
                QPointF(84, 34),
                QPointF(122, 53),
                QPointF(82, 74),
            ],
            "Front": [
                QPointF(46, 52),
                QPointF(82, 74),
                QPointF(82, 118),
                QPointF(46, 96),
            ],
            "Right": [
                QPointF(82, 74),
                QPointF(122, 53),
                QPointF(122, 98),
                QPointF(82, 118),
            ],
        }
        for label, polygon in zones.items():
            if self._point_in_polygon(point, polygon):
                return self._view_target(label)
        return None

    @staticmethod
    def _point_in_polygon(point: QPointF, polygon: list[QPointF]) -> bool:
        inside = False
        previous = polygon[-1]
        for current in polygon:
            intersects = (current.y() > point.y()) != (previous.y() > point.y())
            if intersects:
                slope_x = (previous.x() - current.x()) * (point.y() - current.y()) / (
                    previous.y() - current.y()
                ) + current.x()
                if point.x() < slope_x:
                    inside = not inside
            previous = current
        return inside


class MoveManipulatorOverlay(QWidget):
    """Clickable X/Y/Z transform arrows for active move sessions."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MoveManipulatorOverlay")
        self.setFixedSize(156, 156)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._active_axis: str | None = None
        self._press_parent_pos: tuple[int, int] | None = None
        self._dragging = False
        self.hide()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(14, 20, 27, 110))
        painter.drawEllipse(QPointF(78, 78), 18, 18)
        for axis, end, color in self._axis_specs():
            self._draw_axis(painter, axis, end, color)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        axis = self.axis_at(event.position())
        if axis is None:
            super().mousePressEvent(event)
            return
        parent = self.parentWidget()
        if parent is not None and hasattr(parent, "_set_move_axis_from_manipulator"):
            parent._set_move_axis_from_manipulator(axis)
        parent_pos = self.mapToParent(event.position().toPoint())
        self._active_axis = axis
        self._press_parent_pos = (parent_pos.x(), parent_pos.y())
        self._dragging = False
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._active_axis is None or self._press_parent_pos is None:
            super().mouseMoveEvent(event)
            return
        if not (event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return
        parent = self.parentWidget()
        if parent is None:
            return
        parent_pos = self.mapToParent(event.position().toPoint())
        distance = math.hypot(
            parent_pos.x() - self._press_parent_pos[0],
            parent_pos.y() - self._press_parent_pos[1],
        )
        if not self._dragging:
            if distance < 3.0:
                event.accept()
                return
            if hasattr(parent, "_begin_move_drag"):
                parent._begin_move_drag(*self._press_parent_pos)
            self._dragging = True
        if hasattr(parent, "_drag_move_to"):
            parent._drag_move_to(parent_pos.x(), parent_pos.y())
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._active_axis is not None:
            parent = self.parentWidget()
            if (
                self._dragging
                and parent is not None
                and hasattr(
                    parent,
                    "_commit_move_session",
                )
            ):
                parent._commit_move_session()
            self._active_axis = None
            self._press_parent_pos = None
            self._dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def axis_at(self, position: QPointF) -> str | None:
        center = QPointF(78, 78)
        for axis, end, _color in self._axis_specs():
            if self._distance_to_segment(position, center, end) <= 9.0:
                return axis
            if math.hypot(position.x() - end.x(), position.y() - end.y()) <= 12.0:
                return axis
        return None

    def _draw_axis(
        self,
        painter: QPainter,
        axis: str,
        end: QPointF,
        color: QColor,
    ) -> None:
        center = QPointF(78, 78)
        vector = QPointF(end.x() - center.x(), end.y() - center.y())
        length = math.hypot(vector.x(), vector.y()) or 1.0
        unit = QPointF(vector.x() / length, vector.y() / length)
        normal = QPointF(-unit.y(), unit.x())
        head_base = QPointF(end.x() - unit.x() * 14, end.y() - unit.y() * 14)
        head_left = QPointF(
            head_base.x() + normal.x() * 6,
            head_base.y() + normal.y() * 6,
        )
        head_right = QPointF(
            head_base.x() - normal.x() * 6,
            head_base.y() - normal.y() * 6,
        )
        painter.setPen(QPen(QColor(0, 0, 0, 170), 6.0, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(center, end)
        painter.setPen(QPen(color, 3.4, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(center, end)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawPolygon([end, head_left, head_right])
        painter.setPen(color)
        painter.drawText(
            QRectF(end.x() - 10, end.y() - 24, 20, 18),
            Qt.AlignCenter,
            axis,
        )

    @staticmethod
    def _axis_specs() -> tuple[tuple[str, QPointF, QColor], ...]:
        return (
            ("X", QPointF(136, 78), QColor(226, 74, 64)),
            ("Y", QPointF(41, 123), QColor(74, 196, 94)),
            ("Z", QPointF(78, 20), QColor(60, 145, 245)),
        )

    @staticmethod
    def _distance_to_segment(point: QPointF, start: QPointF, end: QPointF) -> float:
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        length_sq = dx * dx + dy * dy
        if length_sq <= 1e-7:
            return math.hypot(point.x() - start.x(), point.y() - start.y())
        t = ((point.x() - start.x()) * dx + (point.y() - start.y()) * dy) / length_sq
        t = max(0.0, min(1.0, t))
        closest = QPointF(start.x() + t * dx, start.y() + t * dy)
        return math.hypot(point.x() - closest.x(), point.y() - closest.y())


class SelectionBoxOverlay(QWidget):
    """Viewport overlay for left/right direction area selection."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SelectionBoxOverlay")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._start: tuple[int, int] | None = None
        self._current: tuple[int, int] | None = None
        self._filter_label = "All Items"
        self.hide()

    def update_box(
        self,
        start: tuple[int, int],
        current: tuple[int, int],
        filter_label: str,
    ) -> None:
        self._start = start
        self._current = current
        self._filter_label = filter_label
        if self.parentWidget() is not None:
            self.setGeometry(self.parentWidget().rect())
        self.update()

    def clear(self) -> None:
        self._start = None
        self._current = None
        self.hide()
        self.update()

    def paintEvent(self, event) -> None:
        del event
        if self._start is None or self._current is None:
            return

        start_x, start_y = self._start
        current_x, current_y = self._current
        left = min(start_x, current_x)
        top = min(start_y, current_y)
        width = abs(current_x - start_x)
        height = abs(current_y - start_y)
        if width < 1 or height < 1:
            return

        contains_only = current_x >= start_x
        fill = QColor(80, 160, 245, 42) if contains_only else QColor(78, 204, 128, 42)
        outline = (
            QColor(80, 160, 245, 220) if contains_only else QColor(78, 204, 128, 220)
        )

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setPen(
            QPen(outline, 1.3, Qt.SolidLine if contains_only else Qt.DashLine)
        )
        painter.setBrush(fill)
        painter.drawRect(QRectF(left, top, width, height))


class SketchPlaneChooserOverlay(QWidget):
    """Three clickable construction-plane tiles used before starting a sketch."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        hover_callback: Callable[[str | None], None],
        activate_callback: Callable[[str], None],
    ) -> None:
        super().__init__(parent)
        self.setObjectName("SketchPlaneChooserOverlay")
        self.setFixedSize(172, 76)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._hover_plane: str | None = None
        self._hover_callback = hover_callback
        self._activate_callback = activate_callback

    @property
    def hover_plane(self) -> str | None:
        return self._hover_plane

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(15, 22, 29, 218))
        painter.drawRoundedRect(QRectF(0, 0, 172, 76), 8, 8)

        title_font = QFont(self.font())
        title_font.setPointSize(8)
        painter.setFont(title_font)
        painter.setPen(QColor(188, 198, 208))
        painter.drawText(QRectF(10, 5, 152, 16), Qt.AlignCenter, "Choose sketch plane")

        label_font = QFont(self.font())
        label_font.setBold(True)
        label_font.setPointSize(9)
        painter.setFont(label_font)
        for plane, rect in self._plane_rects().items():
            active = plane == self._hover_plane
            painter.setPen(
                QPen(
                    QColor(79, 169, 245) if active else QColor(76, 88, 101),
                    1.4,
                )
            )
            painter.setBrush(
                QColor(25, 104, 166, 226) if active else QColor(48, 58, 69, 226)
            )
            painter.drawRoundedRect(rect, 4, 4)
            painter.setPen(QColor(246, 250, 255))
            painter.drawText(rect, Qt.AlignCenter, plane)

    def mouseMoveEvent(self, event) -> None:
        plane = self._plane_at(event.position())
        if plane != self._hover_plane:
            self._hover_plane = plane
            self._hover_callback(plane)
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_plane = None
        self._hover_callback(None)
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            plane = self._plane_at(event.position())
            if plane is not None:
                self._activate_callback(plane)
                event.accept()
                return
        super().mousePressEvent(event)

    @staticmethod
    def _plane_rects() -> dict[str, QRectF]:
        return {
            "XY": QRectF(12, 26, 44, 36),
            "YZ": QRectF(64, 26, 44, 36),
            "XZ": QRectF(116, 26, 44, 36),
        }

    def _plane_at(self, position: QPointF) -> str | None:
        for plane, rect in self._plane_rects().items():
            if rect.contains(position):
                return plane
        return None
