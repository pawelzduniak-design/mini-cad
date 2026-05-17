"""Main window Qt layout assembly."""

from __future__ import annotations

from cad_app import theme
from cad_app.ui_chrome import (
    assign_toolbar_button_object_names,
    configure_toolbar,
    make_sidebar_section_label,
)
from cad_app.ui_menu import CATEGORY_RAIL_ACTIONS, TOP_TOOLBAR_ACTIONS


def build_main_window_layout(
    window,
    viewer_widget,
    actions: dict,
    commands_menu,
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QDockWidget,
        QLabel,
        QListWidget,
        QTabWidget,
        QToolBar,
        QVBoxLayout,
        QWidget,
    )

    top_toolbar = QToolBar("Project", window)
    top_toolbar.setObjectName("top_bar")
    top_toolbar.setProperty("perception_object_name", "top_bar")
    configure_toolbar(top_toolbar, role="top")
    project_label = QLabel("Direct Modeling CAD", window)
    project_label.setObjectName("ProjectLabel")
    project_label.setMinimumWidth(160)
    top_toolbar.addWidget(project_label)
    top_toolbar.addSeparator()
    top_toolbar.addActions(
        [actions[action_name] for action_name in TOP_TOOLBAR_ACTIONS[:4]]
    )
    top_toolbar.addSeparator()
    top_toolbar.addActions(
        [actions[action_name] for action_name in TOP_TOOLBAR_ACTIONS[4:]]
    )
    assign_toolbar_button_object_names(top_toolbar)
    window.addToolBar(Qt.TopToolBarArea, top_toolbar)

    category_toolbar = QToolBar("Main Menu", window)
    category_toolbar.setObjectName("left_menu")
    category_toolbar.setProperty("perception_object_name", "left_menu")
    configure_toolbar(category_toolbar)
    category_toolbar.addWidget(make_sidebar_section_label("WORKSPACE"))
    category_toolbar.addActions(
        [actions[action_name] for action_name in CATEGORY_RAIL_ACTIONS]
    )
    assign_toolbar_button_object_names(category_toolbar)
    window.addToolBar(Qt.LeftToolBarArea, category_toolbar)

    command_toolbar = QToolBar("Context Tools", window)
    command_toolbar.setObjectName("context_tool_panel")
    command_toolbar.setProperty("perception_object_name", "context_tool_panel")
    configure_toolbar(command_toolbar, role="context")
    window.addToolBarBreak(Qt.LeftToolBarArea)
    window.addToolBar(Qt.LeftToolBarArea, command_toolbar)
    viewer_widget._sketch_toolbar = None

    browser_dock = QDockWidget("Model", window)
    browser_dock.setObjectName("BrowserDock")
    browser_dock.setProperty("perception_object_name", "project_sidebar")
    browser_dock.setMinimumWidth(theme.RIGHT_PANEL_WIDTH)
    browser_tabs = QTabWidget(browser_dock)
    browser_tabs.setObjectName("BrowserTabs")
    model_list = QListWidget(browser_tabs)
    model_list.setObjectName("ModelList")
    bodies_list = QListWidget(browser_tabs)
    bodies_list.setObjectName("BodiesList")
    sketches_list = QListWidget(browser_tabs)
    sketches_list.setObjectName("SketchesList")
    history_list = QListWidget(browser_tabs)
    history_list.setObjectName("HistoryList")
    browser_panel = QWidget(browser_dock)
    browser_panel.setObjectName("BrowserPanel")
    browser_layout = QVBoxLayout(browser_panel)
    browser_layout.setContentsMargins(0, 0, 0, 0)
    browser_layout.setSpacing(0)
    properties_header = QLabel("Properties", browser_panel)
    properties_header.setObjectName("PropertiesHeader")
    properties_header.setStyleSheet(f"""
        QLabel#PropertiesHeader {{
            background: {theme.PANEL_BG};
            color: {theme.TEXT_DARK};
            border-top: 1px solid {theme.PANEL_BORDER};
            padding: 12px 14px 6px 14px;
            font-weight: 700;
        }}
        """)
    properties_list = QListWidget(browser_panel)
    properties_list.setObjectName("PropertiesList")
    browser_tabs.addTab(model_list, "Model")
    browser_tabs.addTab(bodies_list, "Bodies")
    browser_tabs.addTab(sketches_list, "Sketches")
    browser_tabs.addTab(history_list, "History")
    browser_layout.addWidget(browser_tabs, 3)
    browser_layout.addWidget(properties_header)
    browser_layout.addWidget(properties_list, 2)
    browser_dock.setWidget(browser_panel)
    window.addDockWidget(Qt.RightDockWidgetArea, browser_dock)
    browser_dock.hide()

    status_bar = window.statusBar()
    status_bar.setObjectName("bottom_status_bar")
    hud_labels = {
        "mode": QLabel(),
        "selection": QLabel(),
        "axis": QLabel(),
        "tool": QLabel(),
        "sketch": QLabel(),
        "hint": QLabel(),
    }
    for name, label in hud_labels.items():
        label.setObjectName(
            "selection_label" if name == "selection" else f"Status{name.title()}"
        )
        if name == "hint":
            label.setObjectName("bottom_hint_bar")
            label.setMinimumWidth(260)
        else:
            label.setMinimumWidth(132 if name != "sketch" else 180)
        status_bar.addPermanentWidget(label)
    viewer_widget.attach_hud(hud_labels)
    viewer_widget.attach_actions(actions)
    viewer_widget.attach_command_surface(commands_menu, command_toolbar)
    viewer_widget.attach_browser(
        {
            "model": model_list,
            "bodies": bodies_list,
            "sketches": sketches_list,
            "history": history_list,
            "properties": properties_list,
        }
    )
    status_bar.showMessage("Ready")
    window.resize(1200, 800)
