"""Central visual design tokens for the CAD UI."""

from __future__ import annotations

APP_BG_DARK = "#111820"
TOP_BAR_BG = "#171d24"
TOP_BAR_BG_2 = "#1c232b"
SIDEBAR_BG = "#151c24"
SIDEBAR_BG_HOVER = "#202a35"
SIDEBAR_BG_ACTIVE = "#147bd1"
VIEWPORT_BG = (0.018, 0.024, 0.030)
VIEWPORT_BG_CENTER = (0.045, 0.055, 0.068)
PANEL_BG = "#f6f8fb"
PANEL_BG_ALT = "#ffffff"
PANEL_BORDER = "#d6dce3"
TEXT_PRIMARY = "#edf3f8"
TEXT_DARK = "#1f2933"
TEXT_SECONDARY = "#9ca7b3"
TEXT_MUTED = "#6b7580"
DISABLED_TEXT = "#69737f"
ACCENT_BLUE = "#1f8fe5"
ACCENT_BLUE_HOVER = "#2d9df2"
ACCENT_BLUE_ACTIVE = "#0f73c9"
GRID_MINOR = (0.235, 0.265, 0.300)
GRID_MAJOR = (0.325, 0.360, 0.400)
AXIS_X = (0.92, 0.20, 0.18)
AXIS_Y = (0.24, 0.82, 0.30)
AXIS_Z = (0.28, 0.52, 1.0)
BODY_DEFAULT = (0.62, 0.64, 0.65)
BODY_EDGE = (0.15, 0.17, 0.19)
FACE_HOVER = (0.30, 0.68, 1.0)
FACE_SELECTED = (0.18, 0.58, 1.0)
PREVIEW_BLUE = (0.20, 0.60, 1.0)
DIMENSION_LABEL = (0.94, 0.96, 1.0)
SKETCH_PROFILE = (0.16, 0.70, 1.0)
SKETCH_UNDER_DEFINED = SKETCH_PROFILE
SKETCH_FULLY_DEFINED = (0.18, 0.78, 0.36)
SKETCH_ENTITY = (0.50, 0.82, 1.0)
TOOLTIP_BG = "#151b22"
SUCCESS_GREEN = "#35c46b"

SIDEBAR_WIDTH = 88
CONTEXT_PANEL_WIDTH = 224
RIGHT_PANEL_WIDTH = 320
STATUS_BAR_HEIGHT = 30
BORDER_RADIUS = 8
SIDEBAR_ICON_SIZE = 34
CONTEXT_ICON_SIZE = 22
TOP_ICON_SIZE = 20


def rgb_tuple(color: tuple[float, float, float]) -> str:
    return ", ".join(f"{component:.3f}" for component in color)


def sketch_profile_color(meta: dict[str, object] | None) -> tuple[float, float, float]:
    state = (meta or {}).get("definition_state")
    if state in {"fully_defined", "full"} or (meta or {}).get("fully_defined") is True:
        return SKETCH_FULLY_DEFINED
    return SKETCH_UNDER_DEFINED


def app_stylesheet() -> str:
    return f"""
    QMainWindow {{
        background: {APP_BG_DARK};
        color: {TEXT_PRIMARY};
    }}
    QMenuBar {{
        background: {TOP_BAR_BG};
        color: {TEXT_PRIMARY};
        padding: 5px 16px;
        spacing: 20px;
        border-bottom: 1px solid #27313b;
    }}
    QMenuBar::item {{
        background: transparent;
        padding: 7px 12px;
        border-radius: 6px;
    }}
    QMenuBar::item:selected {{
        background: #232d37;
    }}
    QMenu {{
        background: #f8fafc;
        color: {TEXT_DARK};
        border: 1px solid {PANEL_BORDER};
        padding: 6px;
    }}
    QMenu::item {{
        padding: 7px 24px;
        border-radius: 5px;
    }}
    QMenu::item:selected {{
        background: #e8f2fd;
        color: {ACCENT_BLUE_ACTIVE};
    }}
    QStatusBar {{
        background: {TOP_BAR_BG};
        color: {TEXT_SECONDARY};
        border-top: 1px solid #2b3540;
        min-height: {STATUS_BAR_HEIGHT}px;
        max-height: {STATUS_BAR_HEIGHT}px;
    }}
    QStatusBar QLabel {{
        color: {TEXT_SECONDARY};
        padding: 0 8px;
        border-left: 1px solid #2b3540;
    }}
    QLabel#ProjectLabel {{
        color: {TEXT_PRIMARY};
        font-weight: 700;
        font-size: 14px;
        padding-left: 8px;
    }}
    QDockWidget#BrowserDock {{
        background: {PANEL_BG};
        color: {TEXT_DARK};
        titlebar-close-icon: none;
        titlebar-normal-icon: none;
    }}
    QDockWidget#BrowserDock::title {{
        background: {PANEL_BG};
        color: {TEXT_DARK};
        padding: 7px 10px;
        border-left: 1px solid {PANEL_BORDER};
        border-bottom: 1px solid {PANEL_BORDER};
        font-weight: 600;
    }}
    QTabWidget#BrowserTabs::pane {{
        background: {PANEL_BG};
        border-left: 1px solid {PANEL_BORDER};
        border-top: 1px solid {PANEL_BORDER};
    }}
    QWidget#BrowserPanel {{
        background: {PANEL_BG};
    }}
    QTabBar::tab {{
        background: {PANEL_BG};
        color: #394553;
        padding: 10px 14px 9px 14px;
        border: none;
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:selected {{
        color: {ACCENT_BLUE_ACTIVE};
        border-bottom: 2px solid {ACCENT_BLUE};
        font-weight: 600;
    }}
    QListWidget {{
        background: {PANEL_BG};
        color: {TEXT_DARK};
        border: none;
        padding: 10px 12px;
        outline: 0;
        font-size: 13px;
    }}
    QListWidget::item {{
        padding: 7px 8px;
        border-radius: 6px;
    }}
    QListWidget::item:selected {{
        background: #dceeff;
        color: {ACCENT_BLUE_ACTIVE};
    }}
    """


def top_toolbar_stylesheet() -> str:
    return f"""
    QToolBar#TopToolbar {{
        background: {TOP_BAR_BG_2};
        border: none;
        border-bottom: 1px solid #2a3440;
        spacing: 8px;
        padding: 6px 16px;
    }}
    QToolBar#TopToolbar QToolButton {{
        color: {TEXT_PRIMARY};
        background: transparent;
        border: 1px solid transparent;
        border-radius: 7px;
        padding: 5px 10px;
        min-width: 76px;
        min-height: 34px;
    }}
    QToolBar#TopToolbar QToolButton:hover {{
        background: #26313c;
        border-color: #334150;
    }}
    QToolBar#TopToolbar QToolButton:pressed,
    QToolBar#TopToolbar QToolButton:checked {{
        background: #203850;
        border-color: {ACCENT_BLUE};
    }}
    QToolBar#TopToolbar QToolButton:disabled {{
        color: {DISABLED_TEXT};
    }}
    """


def sidebar_toolbar_stylesheet() -> str:
    return f"""
    QToolBar {{
        background: {SIDEBAR_BG};
        border: none;
        spacing: 8px;
        padding: 10px 8px;
    }}
    QToolBar QToolButton {{
        background: transparent;
        color: {TEXT_PRIMARY};
        border: 1px solid transparent;
        border-radius: {BORDER_RADIUS}px;
        padding: 7px 5px;
        min-width: 76px;
        max-width: 76px;
        min-height: 70px;
        max-height: 70px;
    }}
    QToolBar QToolButton:hover {{
        background: {SIDEBAR_BG_HOVER};
        border-color: #2e3b47;
    }}
    QToolBar QToolButton:checked {{
        background: {SIDEBAR_BG_ACTIVE};
        color: #ffffff;
        border-color: {ACCENT_BLUE_HOVER};
    }}
    QToolBar QToolButton:disabled {{
        color: {DISABLED_TEXT};
        background: transparent;
        border-color: transparent;
    }}
    """


def context_toolbar_stylesheet() -> str:
    return f"""
    QToolBar#CommandToolbar {{
        background: {TOP_BAR_BG_2};
        border: none;
        border-left: 1px solid #26303a;
        border-right: 1px solid #26303a;
        spacing: 6px;
        padding: 10px 10px;
    }}
    QToolBar#CommandToolbar QToolButton {{
        background: #202832;
        color: {TEXT_PRIMARY};
        border: 1px solid #364250;
        border-radius: 7px;
        padding: 7px 10px;
        min-width: {CONTEXT_PANEL_WIDTH - 34}px;
        max-width: {CONTEXT_PANEL_WIDTH - 34}px;
        min-height: 36px;
        max-height: 40px;
        text-align: left;
    }}
    QToolBar#CommandToolbar QToolButton:hover {{
        background: #26323f;
        border-color: {ACCENT_BLUE_HOVER};
    }}
    QToolBar#CommandToolbar QToolButton:pressed,
    QToolBar#CommandToolbar QToolButton:checked {{
        background: {ACCENT_BLUE_ACTIVE};
        border-color: {ACCENT_BLUE_HOVER};
        color: #ffffff;
    }}
    QToolBar#CommandToolbar QToolButton:disabled {{
        background: #1b222b;
        color: {DISABLED_TEXT};
        border-color: #29323c;
    }}
    """


def overlay_stylesheet() -> str:
    return f"""
    QLabel {{
        background: rgba(21, 27, 34, 218);
        color: {TEXT_PRIMARY};
        border: 1px solid rgba(74, 90, 108, 190);
        border-radius: 7px;
        padding: 6px 10px;
        font-weight: 600;
    }}
    """


def tool_popover_stylesheet() -> str:
    return f"""
    QFrame#tool_popover {{
        background: rgba(21, 27, 34, 230);
        color: {TEXT_PRIMARY};
        border: 1px solid rgba(52, 64, 78, 160);
        border-radius: 7px;
    }}
    QFrame#tool_popover QLabel {{
        background: transparent;
        border: none;
        color: {TEXT_PRIMARY};
        padding: 0;
    }}
    QFrame#tool_popover QDoubleSpinBox {{
        background: #111820;
        color: {TEXT_PRIMARY};
        border: 1px solid #34404e;
        border-radius: 5px;
        padding: 3px 6px;
    }}
    QFrame#tool_popover QPushButton {{
        background: #202a34;
        color: {TEXT_PRIMARY};
        border: 1px solid #34404e;
        border-radius: 5px;
        padding: 4px 8px;
    }}
    QFrame#tool_popover QPushButton:hover {{
        border-color: {ACCENT_BLUE_HOVER};
    }}
    """
