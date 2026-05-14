"""Qt chrome helpers for the CAD shell."""

from __future__ import annotations

from pathlib import Path

from cad_app import theme

ICON_ASSET_DIR = Path(__file__).resolve().parent / "assets" / "icons"

ICON_GLYPHS = {
    "add_box": "+",
    "axis_x": "X",
    "axis_y": "Y",
    "axis_z": "Z",
    "boolean_intersect": "I",
    "boolean_subtract": "-",
    "boolean_union": "U",
    "cancel_tool": "Esc",
    "category_create": "+",
    "category_boolean": "B",
    "category_file": "Fi",
    "category_measure": "R",
    "category_modify": "M",
    "category_select": "S",
    "category_sketch": "K",
    "category_transform": "T",
    "category_view": "V",
    "chamfer": "C",
    "circle_boss": "O",
    "circle_cut": "O-",
    "clear_boolean_target": "B-",
    "delete_object": "X",
    "display_shaded": "F",
    "display_wireframe": "W",
    "delete_sketch": "X",
    "edit_sketch": "Ed",
    "edit_sketch_dimensions": "D",
    "edit_box_dimensions": "D",
    "edit_position": "XYZ",
    "exit": "Q",
    "export_step": "Ex",
    "extrude": "E",
    "extrude_reverse": "E-",
    "fillet": "F",
    "finish_sketch": "Done",
    "fit_all": "Fit",
    "home": "H",
    "import_step": "Im",
    "mirror_body": "Mi",
    "new_sketch": "NS",
    "move_object": "M",
    "move_object_x": "MX",
    "move_object_y": "MY",
    "move_object_z": "MZ",
    "move_sketch": "M",
    "move_sketch_x": "MX",
    "move_sketch_y": "MY",
    "move_sketch_z": "MZ",
    "move_selection": "M",
    "move_selection_normal": "MN",
    "move_selection_x": "MX",
    "move_selection_y": "MY",
    "move_selection_z": "MZ",
    "offset_face": "Of",
    "push_pull": "P",
    "remove_face": "Rf",
    "redo": "Re",
    "rotate_body": "Ro",
    "rotate_body_x": "RX",
    "rotate_body_y": "RY",
    "rotate_body_z": "RZ",
    "save_project": "Sv",
    "select_object": "O",
    "select_edge": "E",
    "select_face": "F",
    "select_through": "ST",
    "select_vertex": "V",
    "set_boolean_target": "B",
    "sketch_arc_tool": "A",
    "sketch_circle_tool": "C",
    "sketch_cut_mode": "Cut",
    "sketch_center_rectangle_tool": "CR",
    "sketch_extrude": "E",
    "sketch_line_tool": "L",
    "sketch_new_body": "NB",
    "sketch_revolve": "Rv",
    "sketch_revolve_x": "RX",
    "sketch_revolve_y": "RY",
    "sketch_revolve_z": "RZ",
    "sketch_rectangle3_tool": "3R",
    "sketch_rectangle_tool": "R",
    "sketch_trim": "Tr",
    "start_sketch": "S",
    "thread": "Th",
    "undo": "Un",
}

ICON_ASSET_FILES = {
    "boolean_intersect": "17_boolean_intersect.png",
    "boolean_subtract": "16_boolean_subtract.png",
    "boolean_union": "15_boolean_union.png",
    "add_box": "15_boolean_union.png",
    "category_create": "15_boolean_union.png",
    "category_boolean": "15_boolean_union.png",
    "category_file": "01_select.png",
    "category_modify": "08_push_pull.png",
    "category_transform": "09_move.png",
    "category_select": "01_select.png",
    "category_sketch": "02_sketch.png",
    "category_view": "20_face_mode.png",
    "chamfer": "14_chamfer.png",
    "circle_boss": "05_circle.png",
    "circle_cut": "16_boolean_subtract.png",
    "clear_boolean_target": "16_boolean_subtract.png",
    "delete_object": "16_boolean_subtract.png",
    "display_shaded": "20_face_mode.png",
    "display_wireframe": "19_edge_mode.png",
    "delete_sketch": "16_boolean_subtract.png",
    "edit_sketch": "02_sketch.png",
    "edit_sketch_dimensions": "02_sketch.png",
    "edit_box_dimensions": "02_sketch.png",
    "edit_position": "09_move.png",
    "extrude": "08_push_pull.png",
    "extrude_reverse": "08_push_pull.png",
    "fillet": "13_fillet.png",
    "finish_sketch": "02_sketch.png",
    "mirror_body": "09_move.png",
    "new_sketch": "02_sketch.png",
    "move_object": "09_move.png",
    "move_object_x": "09_move.png",
    "move_object_y": "09_move.png",
    "move_object_z": "09_move.png",
    "move_sketch": "09_move.png",
    "move_sketch_x": "09_move.png",
    "move_sketch_y": "09_move.png",
    "move_sketch_z": "09_move.png",
    "move_selection": "09_move.png",
    "move_selection_normal": "09_move.png",
    "move_selection_x": "09_move.png",
    "move_selection_y": "09_move.png",
    "move_selection_z": "09_move.png",
    "offset_face": "12_offset.png",
    "push_pull": "08_push_pull.png",
    "remove_face": "16_boolean_subtract.png",
    "rotate_body": "10_rotate.png",
    "rotate_body_x": "10_rotate.png",
    "rotate_body_y": "10_rotate.png",
    "rotate_body_z": "10_rotate.png",
    "select_edge": "19_edge_mode.png",
    "select_face": "20_face_mode.png",
    "select_object": "01_select.png",
    "select_through": "01_select.png",
    "select_vertex": "18_vertex_mode.png",
    "set_boolean_target": "15_boolean_union.png",
    "sketch_arc_tool": "06_arc.png",
    "sketch_circle_tool": "05_circle.png",
    "sketch_cut_mode": "16_boolean_subtract.png",
    "sketch_center_rectangle_tool": "04_rectangle.png",
    "sketch_extrude": "07_extrude.png",
    "sketch_line_tool": "03_line.png",
    "sketch_new_body": "07_extrude.png",
    "sketch_revolve": "10_rotate.png",
    "sketch_revolve_x": "10_rotate.png",
    "sketch_revolve_y": "10_rotate.png",
    "sketch_revolve_z": "10_rotate.png",
    "sketch_rectangle3_tool": "04_rectangle.png",
    "sketch_rectangle_tool": "04_rectangle.png",
    "sketch_trim": "16_boolean_subtract.png",
    "start_sketch": "02_sketch.png",
    "thread": "10_rotate.png",
}


def icon_group(name: str) -> str:
    if name.startswith("select_") or name == "category_select":
        return "select"
    if "sketch" in name or name in {"start_sketch", "category_sketch"}:
        return "sketch"
    if name in {"add_box", "import_step", "category_create"}:
        return "create"
    if name in {
        "extrude",
        "extrude_reverse",
        "push_pull",
        "fillet",
        "chamfer",
        "circle_boss",
        "circle_cut",
        "thread",
        "offset_face",
        "remove_face",
        "edit_box_dimensions",
        "edit_position",
        "category_modify",
    }:
        return "modify"
    if (
        name.startswith("axis_")
        or name.startswith("boolean_")
        or name
        in {
            "move_object",
            "move_object_x",
            "move_object_y",
            "move_object_z",
            "move_selection",
            "move_selection_normal",
            "move_selection_x",
            "move_selection_y",
            "move_selection_z",
            "rotate_body",
            "rotate_body_x",
            "rotate_body_y",
            "rotate_body_z",
            "mirror_body",
            "set_boolean_target",
            "clear_boolean_target",
            "category_transform",
            "category_boolean",
        }
    ):
        return "transform"
    if name in {
        "category_view",
        "display_shaded",
        "display_wireframe",
        "fit_all",
        "home",
    }:
        return "view"
    if name in {
        "category_file",
        "save_project",
        "import_step",
        "export_step",
        "exit",
    }:
        return "file"
    return "default"


def make_icon(name: str):
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

    toolbar_icon_size = QSize(theme.SIDEBAR_ICON_SIZE, theme.SIDEBAR_ICON_SIZE)
    asset_file = ICON_ASSET_FILES.get(name)
    if asset_file is not None:
        asset_path = ICON_ASSET_DIR / asset_file
        if asset_path.exists():
            source = QPixmap(str(asset_path))
            if not source.isNull():
                side = min(source.width(), source.height())
                icon_source = source.copy(0, 0, side, side)
                scaled = icon_source.scaled(
                    toolbar_icon_size,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                pixmap = QPixmap(toolbar_icon_size)
                pixmap.fill(Qt.transparent)
                painter = QPainter(pixmap)
                painter.drawPixmap(
                    (toolbar_icon_size.width() - scaled.width()) // 2,
                    (toolbar_icon_size.height() - scaled.height()) // 2,
                    scaled,
                )
                painter.end()
                return QIcon(pixmap)

    icon_colors = {
        "select": QColor(62, 94, 140),
        "sketch": QColor(54, 125, 100),
        "create": QColor(142, 98, 45),
        "modify": QColor(135, 74, 88),
        "transform": QColor(87, 91, 120),
        "view": QColor(82, 96, 102),
        "file": QColor(78, 105, 83),
        "default": QColor(88, 88, 88),
    }
    pixmap = QPixmap(toolbar_icon_size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    color = icon_colors[icon_group(name)]
    painter.setBrush(color)
    painter.setPen(QPen(color.darker(135), 1))
    painter.drawRoundedRect(2, 2, 20, 20, 4, 4)
    painter.setPen(QPen(QColor(255, 255, 255), 1))
    painter.drawText(pixmap.rect(), Qt.AlignCenter, ICON_GLYPHS.get(name, "?"))
    painter.end()
    return QIcon(pixmap)


def configure_toolbar(toolbar, *, role: str = "sidebar") -> None:
    from PySide6.QtCore import QSize, Qt

    toolbar.setMovable(False)
    if role == "top":
        toolbar.setIconSize(QSize(theme.TOP_ICON_SIZE, theme.TOP_ICON_SIZE))
        toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toolbar.setStyleSheet(theme.top_toolbar_stylesheet())
        return
    if role == "context":
        toolbar.setIconSize(QSize(theme.CONTEXT_ICON_SIZE, theme.CONTEXT_ICON_SIZE))
        toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toolbar.setMinimumWidth(theme.CONTEXT_PANEL_WIDTH)
        toolbar.setMaximumWidth(theme.CONTEXT_PANEL_WIDTH)
        toolbar.setStyleSheet(theme.context_toolbar_stylesheet())
        return
    toolbar.setIconSize(QSize(theme.SIDEBAR_ICON_SIZE, theme.SIDEBAR_ICON_SIZE))
    toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
    toolbar.setMinimumWidth(theme.SIDEBAR_WIDTH)
    toolbar.setStyleSheet(theme.sidebar_toolbar_stylesheet())


def assign_toolbar_button_object_names(toolbar) -> None:
    """Give QToolButton widgets stable names derived from their QAction."""
    toolbar_name = toolbar.objectName()
    if not toolbar_name:
        return
    for action in toolbar.actions():
        action_name = action.objectName()
        if not action_name:
            continue
        button = toolbar.widgetForAction(action)
        if button is None:
            continue
        button.setObjectName(f"{toolbar_name}__{action_name}")


def make_sidebar_section_label(text: str, parent=None):
    from PySide6.QtWidgets import QLabel

    label = QLabel(text, parent)
    label.setStyleSheet(f"""
        QLabel {{
            color: {theme.TEXT_SECONDARY};
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0px;
            padding: 8px 4px 2px 4px;
        }}
        """)
    label.setMinimumWidth(theme.SIDEBAR_WIDTH - 18)
    return label
