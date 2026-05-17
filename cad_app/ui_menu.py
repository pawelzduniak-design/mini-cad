"""Declarative menu and command surface model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MenuCategory:
    category_id: str
    action_name: str
    label: str
    status_tip: str
    context_hint: str


CATEGORY_DEFS: tuple[MenuCategory, ...] = (
    MenuCategory(
        "select",
        "category_select",
        "Select",
        "Choose what viewport clicks select.",
        "Choose Object, Face, Edge, or Vertex selection mode",
    ),
    MenuCategory(
        "create",
        "category_create",
        "Create",
        "Add or import geometry.",
        "Create: add a box body or import STEP geometry",
    ),
    MenuCategory(
        "modify",
        "category_modify",
        "Modify",
        "Use face, edge, vertex, and sketch profile modification tools.",
        "Select a face, edge, vertex, or sketch profile to modify",
    ),
    MenuCategory(
        "sketch",
        "category_sketch",
        "Sketch",
        "Start a new independent sketch on a face plane or XY plane.",
        "Sketch: create a new independent sketch",
    ),
    MenuCategory(
        "boolean",
        "category_boolean",
        "Boolean",
        "Combine or cut bodies.",
        "Choose target body, then select a tool body",
    ),
    MenuCategory(
        "transform",
        "category_transform",
        "Transform",
        "Transform the active body.",
        "Select a body, then choose Move",
    ),
    MenuCategory(
        "measure",
        "category_measure",
        "Measure",
        "Measure model geometry.",
        "Select an edge to measure distance",
    ),
    MenuCategory(
        "view",
        "category_view",
        "View",
        "Camera and display controls.",
        "View controls",
    ),
    MenuCategory(
        "file",
        "category_file",
        "File",
        "Project and STEP file actions.",
        "File actions",
    ),
)

CATEGORY_BY_ID = {category.category_id: category for category in CATEGORY_DEFS}
CATEGORY_IDS = tuple(category.category_id for category in CATEGORY_DEFS)
CATEGORY_RAIL_ACTIONS = ("category_select", "category_sketch")

TOP_TOOLBAR_ACTIONS = (
    "undo",
    "redo",
    "new_project",
    "export_step",
    "fit_all",
    "home",
    "display_shaded",
    "display_wireframe",
)

SELECT_ACTIONS = (
    "select_object",
    "select_face",
    "select_edge",
    "select_vertex",
    "select_through",
)

SKETCH_START_ACTIONS = ("start_sketch",)
SKETCH_DRAW_ACTIONS = (
    "sketch_line_tool",
    "sketch_arc_tool",
    "sketch_circle2_tool",
    "sketch_center_radius_tool",
    "sketch_rectangle3_tool",
    "sketch_center_rectangle_tool",
    "sketch_trim",
)
SKETCH_ACTIVE_ACTIONS = (*SKETCH_DRAW_ACTIONS, "finish_sketch")
PROFILE_ACTIONS = (
    "edit_sketch",
    "move",
    "extrude",
    "sketch_new_body",
    "sketch_revolve",
    "delete_sketch",
)
SKETCH_OBJECT_ACTIONS = (
    "edit_sketch",
    "move",
    "delete_sketch",
)
MULTI_PROFILE_ACTIONS = (
    "move",
    "extrude",
    "sketch_new_body",
    "delete_sketch",
)

CREATE_ACTIONS = ("add_box", "import_step")
BOOLEAN_ACTIONS = (
    "set_boolean_target",
    "boolean_union",
    "boolean_subtract",
    "boolean_intersect",
    "cancel_boolean",
)
MULTI_BODY_ACTIONS = ("move",)
BODY_ACTIONS = (
    "move",
    "rotate_body",
)
VIEW_ACTIONS = ("fit_all", "home", "display_shaded", "display_wireframe")
FILE_ACTIONS = ("new_project", "import_step", "export_step")
MEASURE_ACTIONS = (
    "measure_distance",
    "measure_angle",
    "measure_radius",
)

FACE_MODIFY_ACTIONS = (
    "extrude",
    "move",
    "remove_face",
)
EDGE_MODIFY_ACTIONS = (
    "move",
    "fillet_chamfer",
)
VERTEX_MODIFY_ACTIONS = ("move",)
EMPTY_MODIFY_SECTIONS = ()


def validate_category_id(category_id: str) -> MenuCategory:
    try:
        return CATEGORY_BY_ID[category_id]
    except KeyError as exc:
        raise ValueError(f"Unsupported tool category: {category_id}") from exc
