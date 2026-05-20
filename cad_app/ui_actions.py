"""Menu and action assembly for the main CAD window."""

from __future__ import annotations

from PySide6.QtGui import QAction, QActionGroup, QKeySequence

from cad_app.types import SelectionKind
from cad_app.ui_chrome import make_icon
from cad_app.ui_menu import CATEGORY_DEFS


def build_main_window_actions(
    window, viewer_widget
) -> tuple[dict[str, QAction], object]:
    actions: dict[str, QAction] = {}

    def make_action(
        name: str,
        text: str,
        slot,
        shortcut: str | None = None,
        status_tip: str = "",
        checkable: bool = False,
    ) -> QAction:
        action = QAction(make_icon(name), text, window)
        action.setObjectName(name)
        action.setCheckable(checkable)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        if status_tip:
            action.setStatusTip(status_tip)
        action.triggered.connect(lambda _checked=False, callback=slot: callback())
        actions[name] = action
        return action

    file_menu = window.menuBar().addMenu("&File")
    new_project_action = make_action(
        "new_project",
        "New Project",
        viewer_widget._new_project,
        "Ctrl+N",
        "Discard the current model and start a new project.",
    )
    new_project_action.setIconText("New")
    file_menu.addAction(new_project_action)
    file_menu.addAction(
        make_action(
            "open_project",
            "Open Project...",
            viewer_widget._open_project_dialog,
            "Ctrl+O",
            "Open a native .cadproj project file.",
        )
    )
    file_menu.addAction(
        make_action(
            "save_project",
            "Save Project...",
            viewer_widget._save_project_dialog,
            "Ctrl+S",
            "Save the current scene to a native .cadproj project file.",
        )
    )
    file_menu.addSeparator()
    file_menu.addAction(
        make_action(
            "import_step",
            "Import STEP...",
            viewer_widget._import_step_dialog,
            "Ctrl+Shift+O",
            "Import a STEP body into the scene.",
        )
    )
    file_menu.addAction(
        make_action(
            "export_step",
            "Export STEP...",
            viewer_widget._export_step_dialog,
            "Ctrl+Shift+S",
            "Export the active body as STEP.",
        )
    )
    file_menu.addSeparator()
    file_menu.addAction(
        make_action("exit", "Exit", window.close, "Ctrl+Q", "Close the application.")
    )

    add_menu = window.menuBar().addMenu("&Add")
    add_menu.addAction(
        make_action(
            "add_box",
            "Box Body",
            viewer_widget._add_box_body,
            "B",
            "Add a separate box body.",
        )
    )

    edit_menu = window.menuBar().addMenu("&Edit")
    edit_menu.addAction(
        make_action(
            "undo",
            "Undo",
            viewer_widget._undo,
            "Ctrl+Z",
            "Restore the previous body state.",
        )
    )
    edit_menu.addAction(
        make_action(
            "redo",
            "Redo",
            viewer_widget._redo,
            "Ctrl+Y",
            "Redo the last undone action.",
        )
    )
    edit_menu.addAction(
        make_action(
            "cancel_tool",
            "Cancel Tool",
            viewer_widget._cancel_active_tool,
            "Esc",
            "Cancel the active tool.",
        )
    )
    edit_menu.addAction(
        make_action(
            "delete_object",
            "Delete Object",
            viewer_widget._delete_active_object,
            "Del",
            "Delete the selected or active object.",
        )
    )

    commands_menu = window.menuBar().addMenu("&Commands")
    commands_menu.setObjectName("CommandsMenu")

    boolean_menu = window.menuBar().addMenu("&Boolean")
    for action in (
        make_action(
            "set_boolean_target",
            "Boolean",
            viewer_widget._set_boolean_target_from_context,
            None,
            "Use the current body as the boolean target.",
        ),
        make_action(
            "clear_boolean_target",
            "Clear Boolean Target",
            viewer_widget._clear_boolean_target,
            None,
            "Clear the pending boolean target.",
        ),
        make_action(
            "cancel_boolean",
            "Cancel Boolean",
            viewer_widget._clear_boolean_target,
            None,
            "Cancel the pending boolean operation.",
        ),
        make_action(
            "boolean_union",
            "Union Bodies",
            lambda: viewer_widget._apply_boolean_tool("union"),
            None,
            "Fuse the selected body into the boolean target.",
        ),
        make_action(
            "boolean_subtract",
            "Subtract Body",
            lambda: viewer_widget._apply_boolean_tool("subtract"),
            None,
            "Cut the selected body from the boolean target.",
        ),
        make_action(
            "boolean_intersect",
            "Intersect Bodies",
            lambda: viewer_widget._apply_boolean_tool("intersect"),
            None,
            "Keep only the target/tool overlap.",
        ),
    ):
        boolean_menu.addAction(action)

    selection_group = QActionGroup(window)
    selection_group.setExclusive(True)
    selection_menu = window.menuBar().addMenu("&Selection")
    for action in (
        make_action(
            "select_object",
            "Object",
            lambda: viewer_widget._set_selection_kind(SelectionKind.OBJECT),
            "1",
            "Select whole bodies.",
            checkable=True,
        ),
        make_action(
            "select_face",
            "Face",
            lambda: viewer_widget._set_selection_kind(SelectionKind.FACE),
            "2",
            "Select faces.",
            checkable=True,
        ),
        make_action(
            "select_edge",
            "Edge",
            lambda: viewer_widget._set_selection_kind(SelectionKind.EDGE),
            "3",
            "Select edges.",
            checkable=True,
        ),
        make_action(
            "select_vertex",
            "Vertex",
            lambda: viewer_widget._set_selection_kind(SelectionKind.VERTEX),
            "4",
            "Select vertices.",
            checkable=True,
        ),
    ):
        selection_group.addAction(action)
        selection_menu.addAction(action)
    selection_menu.addSeparator()
    selection_menu.addAction(
        make_action(
            "select_through",
            "Select Through",
            viewer_widget._toggle_select_through,
            "T",
            "Select through visible geometry and choose from overlapping hits.",
            checkable=True,
        )
    )

    axis_group = QActionGroup(window)
    axis_group.setExclusive(True)
    axis_menu = window.menuBar().addMenu("&Axis")
    for action in (
        make_action(
            "axis_x",
            "X Axis",
            lambda: viewer_widget._set_move_axis("X", (1.0, 0.0, 0.0)),
            "X",
            "Use world X for object, edge, and vertex moves.",
            checkable=True,
        ),
        make_action(
            "axis_y",
            "Y Axis",
            lambda: viewer_widget._set_move_axis("Y", (0.0, 1.0, 0.0)),
            "Y",
            "Use world Y for object, edge, and vertex moves.",
            checkable=True,
        ),
        make_action(
            "axis_z",
            "Z Axis",
            lambda: viewer_widget._set_move_axis("Z", (0.0, 0.0, 1.0)),
            "Z",
            "Use world Z for object, edge, and vertex moves.",
            checkable=True,
        ),
    ):
        axis_group.addAction(action)
        axis_menu.addAction(action)

    sketch_menu = window.menuBar().addMenu("&Sketch")
    sketch_menu.addAction(
        make_action(
            "toggle_workplane_corner_anchor",
            "Anchor Workplane at Face Corner",
            viewer_widget._toggle_workplane_anchor,
            None,
            "Anchor face-based sketches at the face's bottom-left "
            "corner instead of its centroid, so sketch dimensions are "
            "absolute mm from the corner.",
            checkable=True,
        )
    )
    sketch_menu.addSeparator()
    for action in (
        make_action(
            "start_sketch",
            "New Sketch (Bottom)",
            viewer_widget._start_sketch_on_selection,
            "S",
            "Start an independent sketch on the bottom plane or selected face plane.",
        ),
        make_action(
            "new_sketch",
            "New Sketch (Bottom)",
            viewer_widget._start_new_sketch_on_selection,
            None,
            "Compatibility alias for starting an independent sketch.",
        ),
        make_action(
            "sketch_rectangle_tool",
            "Center Rect",
            lambda: viewer_widget._set_sketch_tool("center_rectangle"),
            None,
            "Draw center rectangles in the active sketch.",
            checkable=True,
        ),
        make_action(
            "sketch_line_tool",
            "Line",
            lambda: viewer_widget._set_sketch_tool("line"),
            None,
            "Draw connected sketch lines.",
            checkable=True,
        ),
        make_action(
            "sketch_arc_tool",
            "Arc",
            lambda: viewer_widget._set_sketch_tool("arc"),
            None,
            "Draw 3-point arcs in the active sketch.",
            checkable=True,
        ),
        make_action(
            "sketch_rectangle3_tool",
            "3-Point Rect",
            lambda: viewer_widget._set_sketch_tool("rectangle_3_point"),
            None,
            "Draw rotated 3-point rectangles.",
            checkable=True,
        ),
        make_action(
            "sketch_center_rectangle_tool",
            "Center Rect",
            lambda: viewer_widget._set_sketch_tool("center_rectangle"),
            None,
            "Draw center rectangles in the active sketch.",
            checkable=True,
        ),
        make_action(
            "sketch_circle2_tool",
            "Circle 2-Point",
            lambda: viewer_widget._set_sketch_tool("circle_diameter"),
            None,
            "Draw a circle from two diameter points.",
            checkable=True,
        ),
        make_action(
            "sketch_center_radius_tool",
            "Center Radius",
            lambda: viewer_widget._set_sketch_tool("circle"),
            None,
            "Draw a circle from center and radius.",
            checkable=True,
        ),
        make_action(
            "sketch_circle_tool",
            "Circle",
            lambda: viewer_widget._set_sketch_tool("circle"),
            None,
            "Compatibility alias for center-radius circles.",
            checkable=True,
        ),
        make_action(
            "sketch_trim",
            "Trim",
            viewer_widget._begin_sketch_trim_tool,
            None,
            "Remove a clicked sketch segment.",
            checkable=True,
        ),
        make_action(
            "edit_sketch",
            "Edit Sketch",
            viewer_widget._edit_selected_sketch,
            None,
            "Open the selected sketch profile for drawing, trimming, or edits.",
        ),
        make_action(
            "edit_sketch_dimensions",
            "Edit Dimensions",
            viewer_widget._edit_selected_sketch_dimensions,
            None,
            "Edit width, height, or radius of the selected sketch profile.",
        ),
        make_action(
            "edit_position",
            "Set Position",
            viewer_widget._edit_selected_position,
            None,
            "Set absolute XYZ center position for the selected body or sketch.",
        ),
        make_action(
            "move_sketch",
            "Move Sketch",
            viewer_widget._begin_sketch_move_tool,
            None,
            "Drag selected sketch geometry with the viewport move manipulator.",
        ),
        make_action(
            "move_sketch_x",
            "Move Sketch X",
            lambda: viewer_widget._begin_sketch_move_tool_on_axis(
                "X",
                (1.0, 0.0, 0.0),
            ),
            None,
            "Drag selected sketch geometry along X.",
        ),
        make_action(
            "move_sketch_y",
            "Move Sketch Y",
            lambda: viewer_widget._begin_sketch_move_tool_on_axis(
                "Y",
                (0.0, 1.0, 0.0),
            ),
            None,
            "Drag selected sketch geometry along Y.",
        ),
        make_action(
            "move_sketch_z",
            "Move Sketch Z",
            lambda: viewer_widget._begin_sketch_move_tool_on_axis(
                "Z",
                (0.0, 0.0, 1.0),
            ),
            None,
            "Drag selected sketch geometry along Z.",
        ),
        make_action(
            "delete_sketch",
            "Delete Sketch",
            viewer_widget._delete_selected_sketch,
            "Del",
            "Delete the selected sketch geometry.",
        ),
        make_action(
            "finish_sketch",
            "Finish Sketch",
            viewer_widget._finish_active_sketch,
            None,
            "Finish the active sketch and return to selection.",
        ),
        make_action(
            "sketch_extrude",
            "Extrude Sketch",
            viewer_widget._begin_sketch_extrude_tool,
            None,
            "Drag the selected sketch profile into a solid.",
        ),
        make_action(
            "sketch_cut_mode",
            "Cut Mode",
            viewer_widget._toggle_sketch_cut_mode,
            None,
            "Toggle sketch extrusion between adding material and cutting material.",
            checkable=True,
        ),
        make_action(
            "sketch_new_body",
            "New Body",
            viewer_widget._begin_sketch_new_body_tool,
            None,
            "Extrude the selected sketch profile as a separate body.",
        ),
        make_action(
            "sketch_revolve",
            "Revolve",
            viewer_widget._begin_sketch_revolve_tool,
            None,
            "Revolve the selected sketch profile around the current sketch axis.",
        ),
        make_action(
            "sketch_revolve_x",
            "Revolve X",
            lambda: viewer_widget._begin_sketch_revolve_tool_on_axis("X"),
            None,
            "Revolve the selected sketch profile around its sketch X axis.",
        ),
        make_action(
            "sketch_revolve_y",
            "Revolve Y",
            lambda: viewer_widget._begin_sketch_revolve_tool_on_axis("Y"),
            None,
            "Revolve the selected sketch profile around its sketch Y axis.",
        ),
        make_action(
            "sketch_revolve_z",
            "Revolve Z",
            lambda: viewer_widget._begin_sketch_revolve_tool_on_axis("Z"),
            None,
            "Revolve the selected sketch profile around its sketch normal.",
        ),
    ):
        sketch_menu.addAction(action)

    tools_menu = window.menuBar().addMenu("&Tools")
    for action in (
        make_action(
            "move",
            "Move",
            viewer_widget._begin_unified_move_tool,
            "G",
            "Move the selected body, topology, or sketch geometry.",
        ),
        make_action(
            "move_object",
            "Move",
            viewer_widget._begin_object_move_tool,
            None,
            "Drag the active object with the viewport move manipulator.",
        ),
        make_action(
            "move_object_x",
            "Move X",
            lambda: viewer_widget._begin_object_move_tool_on_axis(
                "X",
                (1.0, 0.0, 0.0),
            ),
            None,
            "Drag the active object along X.",
        ),
        make_action(
            "move_object_y",
            "Move Y",
            lambda: viewer_widget._begin_object_move_tool_on_axis(
                "Y",
                (0.0, 1.0, 0.0),
            ),
            None,
            "Drag the active object along Y.",
        ),
        make_action(
            "move_object_z",
            "Move Z",
            lambda: viewer_widget._begin_object_move_tool_on_axis(
                "Z",
                (0.0, 0.0, 1.0),
            ),
            None,
            "Drag the active object along Z.",
        ),
        make_action(
            "rotate_body",
            "Rotate",
            viewer_widget._begin_object_rotate_tool,
            None,
            "Drag to rotate the active body around the current axis.",
        ),
        make_action(
            "rotate_body_x",
            "Rotate X",
            lambda: viewer_widget._begin_object_rotate_tool_on_axis(
                "X",
                (1.0, 0.0, 0.0),
            ),
            None,
            "Rotate the active body around X.",
        ),
        make_action(
            "rotate_body_y",
            "Rotate Y",
            lambda: viewer_widget._begin_object_rotate_tool_on_axis(
                "Y",
                (0.0, 1.0, 0.0),
            ),
            None,
            "Rotate the active body around Y.",
        ),
        make_action(
            "rotate_body_z",
            "Rotate Z",
            lambda: viewer_widget._begin_object_rotate_tool_on_axis(
                "Z",
                (0.0, 0.0, 1.0),
            ),
            None,
            "Rotate the active body around Z.",
        ),
        make_action(
            "mirror_body",
            "Mirror",
            viewer_widget._mirror_active_body_dialog,
            None,
            "Mirror the active body across an XY / YZ / XZ plane.",
        ),
        make_action(
            "rib_feature",
            "Rib",
            viewer_widget._rib_between_selected_faces_dialog,
            None,
            "Add a triangular rib between two perpendicular planar faces.",
        ),
        make_action(
            "move_selection",
            "Move Selection",
            viewer_widget._begin_selected_move_tool,
            "M",
            (
                "Drag the selected face, edge, or vertex with the viewport "
                "move manipulator."
            ),
        ),
        make_action(
            "move_selection_normal",
            "Move Normal",
            viewer_widget._begin_selected_move_normal_tool,
            None,
            "Drag the selected face along its normal.",
        ),
        make_action(
            "move_selection_x",
            "Move X",
            lambda: viewer_widget._begin_selected_move_tool_on_axis(
                "X",
                (1.0, 0.0, 0.0),
            ),
            None,
            "Drag selected topology along X.",
        ),
        make_action(
            "move_selection_y",
            "Move Y",
            lambda: viewer_widget._begin_selected_move_tool_on_axis(
                "Y",
                (0.0, 1.0, 0.0),
            ),
            None,
            "Drag selected topology along Y.",
        ),
        make_action(
            "move_selection_z",
            "Move Z",
            lambda: viewer_widget._begin_selected_move_tool_on_axis(
                "Z",
                (0.0, 0.0, 1.0),
            ),
            None,
            "Drag selected topology along Z.",
        ),
        make_action(
            "push_pull",
            "Extrude",
            viewer_widget._begin_push_pull_tool,
            None,
            "Compatibility alias for Extrude.",
        ),
        make_action(
            "extrude",
            "Extrude",
            viewer_widget._begin_push_pull_tool,
            "E",
            "Extrude the selected face or sketch profile.",
        ),
        make_action(
            "edit_box_dimensions",
            "Edit Dimensions",
            viewer_widget._edit_selected_box_dimensions,
            None,
            "Edit width, depth, and height of a rectangular box body.",
        ),
        make_action(
            "extrude_reverse",
            "Extrude Reverse",
            lambda: viewer_widget._extrude_active_top_face(-10.0),
            "Shift+E",
            "Push/pull the selected face inward.",
        ),
        make_action(
            "circle_boss",
            "Circle Boss",
            lambda: viewer_widget._circle_feature_on_selected_face(cut=False),
            "O",
            "Add a centered cylindrical boss on the selected face.",
        ),
        make_action(
            "circle_cut",
            "Circle Cut",
            lambda: viewer_widget._circle_feature_on_selected_face(cut=True),
            "Shift+O",
            "Cut a centered cylindrical hole from the selected face.",
        ),
        make_action(
            "offset_face",
            "Offset Face",
            lambda: viewer_widget._show_pending_command("Offset Face"),
            None,
            "Offset the selected face.",
        ),
        make_action(
            "remove_face",
            "Remove Face",
            viewer_widget._remove_selected_face,
            None,
            "Remove only the selected face and leave an open shell.",
        ),
        make_action(
            "fillet_chamfer",
            "Fillet/Chamfer",
            viewer_widget._begin_fillet_chamfer_tool,
            "R",
            "Drag positive for fillet or negative for chamfer.",
        ),
        make_action(
            "fillet",
            "Fillet Edge",
            viewer_widget._begin_fillet_tool,
            None,
            "Drag to set the selected edge fillet radius.",
        ),
        make_action(
            "chamfer",
            "Chamfer Edge",
            viewer_widget._begin_chamfer_tool,
            None,
            "Drag to set the selected edge chamfer distance.",
        ),
        make_action(
            "thread",
            "Thread",
            viewer_widget._thread_on_selected_edge_dialog,
            None,
            "Add a thread to a cylindrical face or circular edge.",
        ),
        make_action(
            "edit_edge_length",
            "Edit Length",
            viewer_widget._edit_selected_edge_length,
            None,
            "Edit the length of a selected straight box edge.",
        ),
    ):
        tools_menu.addAction(action)

    view_menu = window.menuBar().addMenu("&View")
    view_menu.addAction(
        make_action("fit_all", "Fit All", viewer_widget._fit_all, "F", "Fit scene.")
    )
    view_menu.addAction(
        make_action("home", "Home View", viewer_widget._home_view, "H", "Home view.")
    )
    display_group = QActionGroup(window)
    display_group.setExclusive(True)
    for action in (
        make_action(
            "display_shaded",
            "Shaded",
            lambda: viewer_widget._set_display_mode("shaded"),
            None,
            "Show filled faces.",
            checkable=True,
        ),
        make_action(
            "display_wireframe",
            "Wireframe",
            lambda: viewer_widget._set_display_mode("wireframe"),
            "W",
            "Show wireframe edges only.",
            checkable=True,
        ),
    ):
        display_group.addAction(action)
        view_menu.addAction(action)

    measure_menu = window.menuBar().addMenu("&Measure")
    for action in (
        make_action(
            "measure_distance",
            "Measure",
            viewer_widget._measure_selected_edge,
            None,
            "Measure the selected edge length.",
        ),
        make_action(
            "measure_axis_distance",
            "Axis Distance",
            viewer_widget._measure_axis_distance,
            None,
            "Distance between the axes of two cylindrical features "
            "(e.g. hole centres).",
        ),
        make_action(
            "measure_angle",
            "Angle",
            lambda: viewer_widget._show_pending_command("Measure Angle"),
            None,
            "Measure angle between selected geometry.",
        ),
        make_action(
            "measure_radius",
            "Radius",
            lambda: viewer_widget._show_pending_command("Measure Radius"),
            None,
            "Measure radius or diameter of selected circular geometry.",
        ),
    ):
        measure_menu.addAction(action)

    category_group = QActionGroup(window)
    category_group.setExclusive(True)
    for category in CATEGORY_DEFS:
        action = make_action(
            category.action_name,
            category.label,
            lambda category_id=category.category_id: viewer_widget._set_active_category(
                category_id
            ),
            None,
            category.status_tip,
            checkable=True,
        )
        category_group.addAction(action)
        window.addAction(action)

    for local_tool_menu in (
        add_menu,
        commands_menu,
        boolean_menu,
        selection_menu,
        axis_menu,
        sketch_menu,
        tools_menu,
        measure_menu,
    ):
        local_tool_menu.menuAction().setVisible(False)

    return actions, commands_menu
