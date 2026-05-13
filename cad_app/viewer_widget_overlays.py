"""Small Qt overlays drawn above the native CAD viewport."""

from __future__ import annotations

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
        painter.setPen(QColor(235, 240, 245))
        painter.drawText(QRectF(64, 43, 42, 18), Qt.AlignCenter, "Top")
        painter.drawText(QRectF(48, 74, 34, 18), Qt.AlignCenter, "Front")
        painter.drawText(QRectF(86, 74, 40, 18), Qt.AlignCenter, "Right")
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

    def _draw_view_buttons(self, painter: QPainter) -> None:
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSize(7)
        painter.setFont(font)
        for label, rect in self._view_button_rects().items():
            painter.setPen(QPen(QColor(92, 111, 128), 1.1))
            painter.setBrush(QColor(18, 26, 34, 226))
            painter.drawRoundedRect(rect, 4, 4)
            painter.setPen(QColor(238, 244, 250))
            painter.drawText(rect, Qt.AlignCenter, label)

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
