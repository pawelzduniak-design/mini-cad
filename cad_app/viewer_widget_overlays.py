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
        self.setAttribute(Qt.WA_TranslucentBackground)
        # No axis is "active" until a Move or Rotate session sets one.
        # Defaulting to "X" used to light up the red X arrow permanently
        # so users thought they were perma-stuck on a Right-axis tool.
        self._axis_name: str | None = None
        self._press_parent_pos: tuple[int, int] | None = None
        self._dragging = False

    def set_axis_name(self, axis_name: str | None) -> None:
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

        cube_label_font = QFont(self.font())
        cube_label_font.setBold(True)
        cube_label_font.setPointSize(10)
        painter.setFont(cube_label_font)
        self._draw_labeled_text(painter, QRectF(64, 43, 42, 18), "Top")
        self._draw_labeled_text(painter, QRectF(48, 74, 34, 18), "Front")
        self._draw_labeled_text(painter, QRectF(86, 74, 40, 18), "Right")

        # Render the six standard-view shortcut buttons around the
        # cube. Without them the back / bottom / left views were
        # technically clickable but invisible, since the cube only
        # ever shows the Top/Front/Right faces of the +X+Y+Z corner.
        # Drawing the buttons gives the user a visible target for
        # every standard view.
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
        pen = QPen(color, 4.0 if self._axis_name == label else 3.0)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawLine(start, end)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(end, 5.5, 5.5)
        axis_font = QFont(painter.font())
        axis_font.setBold(True)
        axis_font.setPointSize(11)
        painter.setFont(axis_font)
        self._draw_labeled_text(
            painter,
            QRectF(end.x() - 13, end.y() - 25, 26, 22),
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
        font.setPointSize(9)
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

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        parent_pos = self._event_position_in_parent(event)
        self._press_parent_pos = (
            int(round(parent_pos.x())),
            int(round(parent_pos.y())),
        )
        self._dragging = False
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._press_parent_pos is None or not (event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return
        parent = self.parentWidget()
        parent_pos = self._event_position_in_parent(event)
        distance = math.hypot(
            parent_pos.x() - self._press_parent_pos[0],
            parent_pos.y() - self._press_parent_pos[1],
        )
        if not self._dragging:
            if distance < 4.0:
                event.accept()
                return
            self._dragging = True
            if parent is not None and hasattr(parent, "_navigation"):
                parent._navigation.begin_orbit(*self._press_parent_pos)
        if parent is not None and hasattr(parent, "_navigation"):
            parent._navigation.orbit_to(
                int(round(parent_pos.x())),
                int(round(parent_pos.y())),
            )
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton or self._press_parent_pos is None:
            super().mouseReleaseEvent(event)
            return
        parent = self.parentWidget()
        if self._dragging:
            if parent is not None and hasattr(parent, "_navigation"):
                parent._navigation.end_orbit()
            if parent is not None and hasattr(parent, "_show_status"):
                parent._show_status("Orbit view")
        else:
            target = self.view_at(
                int(round(event.position().x())),
                int(round(event.position().y())),
            )
            if target is not None and parent is not None:
                axis, positive, label = target
                if hasattr(parent, "_apply_orientation_gizmo_target"):
                    parent._apply_orientation_gizmo_target(axis, positive, label)
        self._press_parent_pos = None
        self._dragging = False
        event.accept()

    def _event_position_in_parent(self, event) -> QPointF:
        parent = self.parentWidget()
        local_pos = event.position().toPoint()
        if parent is None:
            return QPointF(float(local_pos.x()), float(local_pos.y()))
        return QPointF(parent.mapFromGlobal(self.mapToGlobal(local_pos)))

    @staticmethod
    def _view_button_rects() -> dict[str, QRectF]:
        # Only the three views the cube CAN'T show get explicit
        # buttons: Back, Left, Bottom. The three visible cube faces
        # (Top, Front, Right) are already clickable as cube polygons,
        # so labelling them again as separate buttons was creating
        # the "I click Top and Front lights up" confusion - two
        # different labels mapped to the same screen region.
        return {
            "Back": QRectF(60, 6, 36, 18),
            "Left": QRectF(6, 78, 32, 22),
            "Bottom": QRectF(60, 132, 36, 18),
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
        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus
        )
        self.setFixedSize(156, 156)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_AlwaysStackOnTop)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._active_axis: str | None = None
        self._press_parent_pos: tuple[int, int] | None = None
        self._dragging = False
        self._mode = "move"
        self._axis_directions: dict[str, QPointF] | None = None
        self.hide()

    def set_mode(self, mode: str) -> None:
        normalized = "rotate" if mode == "rotate" else "move"
        if normalized == self._mode:
            return
        self._mode = normalized
        self.update()

    def set_axis_directions(
        self,
        axis_directions: dict[str, tuple[float, float]] | None,
    ) -> None:
        if axis_directions is None:
            self._axis_directions = None
            self.update()
            return
        directions: dict[str, QPointF] = {}
        for axis, direction in axis_directions.items():
            length = math.hypot(direction[0], direction[1])
            if length <= 1e-7:
                continue
            directions[axis] = QPointF(direction[0] / length, direction[1] / length)
        self._axis_directions = directions or None
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(14, 20, 27, 110))
        painter.drawEllipse(QPointF(78, 78), 18, 18)
        if self._mode == "rotate":
            self._draw_rotate_rings(painter)
            return
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
        parent_pos = self._event_position_in_parent(event)
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
        parent_pos = self._event_position_in_parent(event)
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
        if self._mode == "rotate":
            return self._ring_axis_at(position)
        center = QPointF(78, 78)
        for axis, end, _color in self._axis_specs():
            if self._distance_to_segment(position, center, end) <= 12.0:
                return axis
            if math.hypot(position.x() - end.x(), position.y() - end.y()) <= 16.0:
                return axis
        return None

    def _event_position_in_parent(self, event) -> QPointF:
        parent = self.parentWidget()
        local_pos = event.position().toPoint()
        if parent is None:
            return QPointF(float(local_pos.x()), float(local_pos.y()))
        return QPointF(parent.mapFromGlobal(self.mapToGlobal(local_pos)))

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
        painter.setPen(QPen(QColor(0, 0, 0, 190), 7.0, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(center, end)
        painter.setPen(QPen(color, 4.2, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(center, end)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawPolygon([end, head_left, head_right])
        font = QFont(painter.font())
        font.setBold(True)
        font.setPointSize(11)
        painter.setFont(font)
        label_center = QPointF(end.x() + unit.x() * 12, end.y() + unit.y() * 12)
        label_center = QPointF(
            min(max(label_center.x(), 14.0), self.width() - 14.0),
            min(max(label_center.y(), 14.0), self.height() - 14.0),
        )
        label_rect = QRectF(label_center.x() - 14, label_center.y() - 11, 28, 22)
        shadow_rect = QRectF(label_rect)
        shadow_rect.translate(1.2, 1.2)
        painter.setPen(QColor(0, 0, 0, 230))
        painter.drawText(shadow_rect, Qt.AlignCenter, axis)
        painter.setPen(color)
        painter.drawText(label_rect, Qt.AlignCenter, axis)

    def _draw_rotate_rings(self, painter: QPainter) -> None:
        rings = (
            ("X", QRectF(25, 53, 106, 50), QColor(226, 74, 64)),
            ("Y", QRectF(47, 24, 62, 108), QColor(74, 196, 94)),
            ("Z", QRectF(26, 26, 104, 104), QColor(60, 145, 245)),
        )
        for axis, rect, color in rings:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(0, 0, 0, 190), 6.0))
            painter.drawEllipse(rect)
            painter.setPen(QPen(color, 3.2))
            painter.drawEllipse(rect)
            label_rect = self._ring_label_rect(axis)
            shadow_rect = QRectF(label_rect)
            shadow_rect.translate(1.2, 1.2)
            font = QFont(painter.font())
            font.setBold(True)
            font.setPointSize(11)
            painter.setFont(font)
            painter.setPen(QColor(0, 0, 0, 230))
            painter.drawText(shadow_rect, Qt.AlignCenter, axis)
            painter.setPen(color)
            painter.drawText(label_rect, Qt.AlignCenter, axis)

    @staticmethod
    def _ring_label_rect(axis: str) -> QRectF:
        if axis == "X":
            return QRectF(128, 62, 24, 22)
        if axis == "Y":
            return QRectF(36, 122, 24, 22)
        return QRectF(66, 4, 24, 22)

    def _ring_axis_at(self, position: QPointF) -> str | None:
        for axis, rect in (
            ("Z", QRectF(26, 26, 104, 104)),
            ("X", QRectF(25, 53, 106, 50)),
            ("Y", QRectF(47, 24, 62, 108)),
        ):
            if self._distance_to_ellipse(position, rect) <= 0.22:
                return axis
            if self._ring_label_rect(axis).contains(position):
                return axis
        return None

    def _axis_specs(self) -> tuple[tuple[str, QPointF, QColor], ...]:
        if self._axis_directions:
            center = QPointF(78, 78)
            length = 58.0
            colors = {
                "X": QColor(226, 74, 64),
                "Y": QColor(74, 196, 94),
                "Z": QColor(60, 145, 245),
            }
            specs = []
            for axis in ("X", "Y", "Z"):
                direction = self._axis_directions.get(axis)
                if direction is None:
                    continue
                specs.append(
                    (
                        axis,
                        QPointF(
                            center.x() + direction.x() * length,
                            center.y() + direction.y() * length,
                        ),
                        colors[axis],
                    )
                )
            if specs:
                return tuple(specs)
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

    @staticmethod
    def _distance_to_ellipse(point: QPointF, rect: QRectF) -> float:
        rx = rect.width() / 2.0
        ry = rect.height() / 2.0
        if rx <= 1e-7 or ry <= 1e-7:
            return 999.0
        cx = rect.center().x()
        cy = rect.center().y()
        value = math.sqrt(((point.x() - cx) / rx) ** 2 + ((point.y() - cy) / ry) ** 2)
        return abs(value - 1.0)


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
