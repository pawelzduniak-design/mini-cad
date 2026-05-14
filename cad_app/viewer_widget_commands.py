"""Modeling and file command handlers for ViewerWidget."""

from __future__ import annotations

import logging

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QFileDialog, QInputDialog

from cad_app.commands import (
    CommandError,
    apply_circle_feature,
    apply_extrude_face,
    apply_move_object,
    apply_remove_face,
    apply_thread_to_edge,
    circular_edge_parameters,
    thread_default_length,
    translated_shape,
)
from cad_app.engine import make_box
from cad_app.io_step import StepIOError, export_step, import_step
from cad_app.measurement import (
    EdgeMeasurement,
    axis_aligned_box_dimensions,
    edge_measurement,
)
from cad_app.sketch import is_sketch_object, is_sketch_profile
from cad_app.thread_specs import (
    THREAD_MODES,
    THREAD_TYPES,
    matching_thread_preset_for_edge_diameter,
    thread_parameters_from_preset,
    thread_preset_by_name,
    thread_preset_names,
)
from cad_app.types import SelectionKind, SelectionRef

LOGGER = logging.getLogger(__name__)

BOX_DIMENSION_SOURCES = {"primitive_box", "sketch_new_body", "sketch_extrude"}
BOX_DIMENSION_PROFILES = {None, "rectangle", "center_rectangle", "rectangle_corners"}


class ViewerWidgetCommandsMixin:
    def _extrude_active_top_face(self, distance: float) -> None:
        if self._block_modeling_command_during_sketch("Extrude"):
            return
        item_id, face_index = self._selected_face()
        if item_id is None or face_index is None:
            self._show_status("Select a face first")
            LOGGER.info("Extrude ignored because no face is selected")
            return
        try:
            apply_extrude_face(self._scene, item_id, face_index, distance)
        except (CommandError, IndexError, ValueError) as exc:
            LOGGER.warning(
                "Extrude failed item_id=%s face=%s distance=%.2f: %s",
                item_id,
                face_index,
                distance,
                exc,
                exc_info=True,
            )
            self._show_status("Extrude failed")
            return
        self._scene.set_selection(None)
        self._hover_selection = None
        if self._viewer.is_initialized:
            self._viewer.display_scene(self._scene, fit=False)
        self._show_status("Extrude applied")
        LOGGER.info(
            "Extrude applied item_id=%s face=%d distance=%.2f",
            item_id,
            face_index,
            distance,
        )

    def _import_step_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self.window(),
            "Import STEP",
            "",
            "STEP files (*.step *.stp);;All files (*.*)",
        )
        if not path:
            return
        try:
            shape = import_step(path)
        except StepIOError as exc:
            LOGGER.warning(
                "STEP import failed path=%s: %s",
                path,
                exc,
                exc_info=True,
            )
            self._show_status("STEP import failed")
            return
        item_id = self._scene.add_shape(shape, meta={"source": path})
        self._scene.set_active_item(item_id)
        self._scene.set_selection(None)
        self._hover_selection = None
        if self._viewer.is_initialized:
            self._viewer.display_scene(self._scene, fit=True)
            self._navigation.capture_home()
        self._show_status("STEP imported")
        LOGGER.info("STEP imported path=%s item_id=%s", path, item_id)

    def _export_step_dialog(self) -> None:
        item_id = self._selected_or_active_body_item_id()
        if item_id is None:
            self._show_status("No active object")
            return
        path, _ = QFileDialog.getSaveFileName(
            self.window(),
            "Export STEP",
            "",
            "STEP files (*.step *.stp);;All files (*.*)",
        )
        if not path:
            return
        try:
            export_step(self._scene.get(item_id).shape, path)
        except StepIOError as exc:
            LOGGER.warning(
                "STEP export failed path=%s: %s",
                path,
                exc,
                exc_info=True,
            )
            self._show_status("STEP export failed")
            return
        self._show_status("STEP exported")
        LOGGER.info("STEP exported path=%s item_id=%s", path, item_id)

    def _add_box_body(self) -> None:
        body_count = len(self._body_item_ids())
        try:
            shape = translated_shape(
                make_box(60.0, 50.0, 45.0),
                body_count * 35.0,
                0.0,
                0.0,
            )
        except ModuleNotFoundError:
            shape = f"box_body_{body_count + 1}"
        item_id = self._scene.add_shape(
            shape,
            meta={
                "kind": "body",
                "source": "primitive_box",
                "body_index": body_count + 1,
            },
        )
        self._scene.set_active_item(item_id)
        self._scene.set_selection(None)
        self._hover_selection = None
        if self._viewer.is_initialized:
            self._viewer.display_scene(self._scene, fit=True)
            self._navigation.capture_home()
        self._show_status("Box body added")
        LOGGER.info("Box body added item_id=%s index=%d", item_id, body_count + 1)

    def _selected_edge_measurement(self) -> EdgeMeasurement | None:
        selection = self._scene.selection()
        if selection is None or selection.kind != SelectionKind.EDGE:
            return None
        try:
            from OCP.TopoDS import TopoDS

            edge = TopoDS.Edge_s(
                self._picker.subshape(
                    selection.item_id,
                    SelectionKind.EDGE,
                    selection.index,
                )
            )
            return edge_measurement(edge)
        except (CommandError, IndexError, RuntimeError, ValueError) as exc:
            LOGGER.debug("Selected edge measurement failed: %s", exc, exc_info=True)
            return None

    def _selected_edge_is_circular(self) -> bool:
        selection = self._scene.selection()
        if selection is None or selection.kind != SelectionKind.EDGE:
            return False
        try:
            circular_edge_parameters(
                self._scene.get(selection.item_id).shape,
                selection.index,
            )
        except (CommandError, IndexError, RuntimeError, ValueError):
            return False
        return True

    def _thread_on_selected_edge_dialog(self) -> None:
        selection = self._scene.selection()
        if selection is None or selection.kind != SelectionKind.EDGE:
            self._show_status("Select a circular edge first")
            return
        try:
            _center, axis, radius = circular_edge_parameters(
                self._scene.get(selection.item_id).shape,
                selection.index,
            )
        except (CommandError, IndexError, RuntimeError, ValueError) as exc:
            LOGGER.warning("Thread start failed: %s", exc, exc_info=True)
            self._show_status("Thread requires a circular edge")
            return

        preset_names = thread_preset_names()
        matching_preset = matching_thread_preset_for_edge_diameter(radius * 2.0)
        default_preset = "Custom" if matching_preset is None else matching_preset.name
        preset_index = preset_names.index(default_preset)
        preset_name, ok = QInputDialog.getItem(
            self,
            "Thread",
            "Preset",
            preset_names,
            preset_index,
            False,
        )
        if not ok:
            return
        preset = thread_preset_by_name(preset_name)
        if preset is None:
            default_pitch = max(0.5, min(3.0, radius * 0.18))
            default_depth = max(0.15, default_pitch * 0.35)
            standard = "custom"
            size = "custom"
            major_diameter = None
            minor_diameter = None
        else:
            preset_params = thread_parameters_from_preset(preset)
            default_pitch = float(preset_params["pitch"])
            default_depth = float(preset_params["depth"])
            standard = str(preset_params["standard"])
            size = str(preset_params["size"])
            major_diameter = float(preset_params["major_diameter"])
            minor_diameter = float(preset_params["minor_diameter"])
        mode_label, ok = QInputDialog.getItem(
            self,
            "Thread",
            "Representation",
            ["Modeled", "Cosmetic"],
            0,
            False,
        )
        if not ok:
            return
        mode = mode_label.lower()
        if mode not in THREAD_MODES:
            self._show_status("Unsupported thread representation")
            return
        type_label, ok = QInputDialog.getItem(
            self,
            "Thread",
            "Thread Type",
            ["Auto", "External", "Internal"],
            0,
            False,
        )
        if not ok:
            return
        thread_type = type_label.lower()
        if thread_type not in THREAD_TYPES:
            self._show_status("Unsupported thread type")
            return
        default_length = thread_default_length(
            self._scene.get(selection.item_id).shape,
            axis,
        )
        pitch, ok = QInputDialog.getDouble(
            self,
            "Thread",
            "Pitch (mm)",
            default_pitch,
            0.001,
            1_000_000.0,
            2,
        )
        if not ok:
            return
        length, ok = QInputDialog.getDouble(
            self,
            "Thread",
            "Length (mm)",
            default_length,
            0.001,
            1_000_000.0,
            2,
        )
        if not ok:
            return
        depth, ok = QInputDialog.getDouble(
            self,
            "Thread",
            "Depth (mm)",
            default_depth,
            0.001,
            1_000_000.0,
            2,
        )
        if not ok:
            return
        try:
            apply_thread_to_edge(
                self._scene,
                selection.item_id,
                selection.index,
                pitch,
                length,
                depth,
                mode=mode,
                thread_type=thread_type,
                standard=standard,
                size=size,
                major_diameter=major_diameter,
                minor_diameter=minor_diameter,
            )
        except (CommandError, IndexError, RuntimeError, ValueError) as exc:
            LOGGER.warning("Thread failed: %s", exc, exc_info=True)
            self._show_status("Thread failed")
            return
        self._scene.set_selection(None)
        self._hover_selection = None
        if self._viewer.is_initialized:
            self._viewer.display_scene(self._scene, fit=False)
        self._show_status(
            f"Thread added: {standard} {size}, {mode}, "
            f"pitch {pitch:.2f} mm, length {length:.2f} mm"
        )
        self._set_context_hint("Thread feature applied")
        LOGGER.info(
            "Thread applied item_id=%s edge=%d standard=%s size=%s "
            "mode=%s type=%s pitch=%.2f length=%.2f depth=%.2f",
            selection.item_id,
            selection.index,
            standard,
            size,
            mode,
            thread_type,
            pitch,
            length,
            depth,
        )

    def _measure_selected_edge(self) -> None:
        selection = self._scene.selection()
        measurement = self._selected_edge_measurement()
        if selection is None or measurement is None:
            self._show_status("Select an edge first")
            return
        self._display_edge_measurement(measurement)
        axis_suffix = (
            f" ({measurement.axis_name})" if measurement.axis_name is not None else ""
        )
        self._set_context_hint("Edge measured - use Edit Length to resize a box edge")
        self._show_status(
            f"Edge {selection.index}: {measurement.length:.2f} mm{axis_suffix}"
        )
        self._refresh_hud()

    def _display_edge_measurement(self, measurement: EdgeMeasurement) -> None:
        if not self._viewer.is_initialized:
            return
        self._viewer.display_dimension_label(
            f"{measurement.length:.2f} mm",
            measurement.midpoint,
        )

    def _show_edge_dimension_editor(
        self,
        selection: SelectionRef,
        measurement: EdgeMeasurement,
    ) -> None:
        if not hasattr(self, "_inline_dimension_editors"):
            return
        if not self._viewer.is_initialized or not self._selected_edge_length_editable():
            self._hide_edge_dimension_editor()
            return
        self._edge_dimension_editor_selection = selection
        self._show_inline_dimension_editors(
            [
                {
                    "key": "edge",
                    "type": "edge",
                    "label": measurement.axis_name or "L",
                    "value": measurement.length,
                    "position": measurement.midpoint,
                    "selection": selection,
                    "offset": (28, 14),
                }
            ]
        )

    def _hide_edge_dimension_editor(self) -> None:
        self._hide_inline_dimension_editors()

    def _position_edge_dimension_editor(
        self,
        measurement: EdgeMeasurement | None = None,
    ) -> None:
        if not hasattr(self, "_inline_dimension_editors"):
            return
        if measurement is None:
            measurement = self._selected_edge_measurement()
        if measurement is not None and "edge" in self._inline_dimension_editor_specs:
            self._inline_dimension_editor_specs["edge"] = {
                **self._inline_dimension_editor_specs["edge"],
                "value": measurement.length,
                "position": measurement.midpoint,
            }
        self._position_inline_dimension_editors()

    def _show_inline_dimension_editors(self, specs: list[dict[str, object]]) -> None:
        if not hasattr(self, "_inline_dimension_editors"):
            return
        if not specs or not self._viewer.is_initialized:
            self._hide_inline_dimension_editors()
            return
        self._inline_dimension_editor_updating = True
        self._edge_dimension_editor_updating = True
        self._inline_dimension_editor_specs = {}
        visible_keys: set[str] = set()
        for spec in specs:
            key = str(spec.get("key", ""))
            editor = self._inline_dimension_editors.get(key)
            if editor is None:
                continue
            label = str(spec.get("label", ""))
            editor.setPrefix(f"{label} " if label else "")
            editor.setValue(float(spec.get("value", 0.0)))
            editor.setToolTip(str(spec.get("tooltip", "Edit dimension")))
            editor.show()
            editor.raise_()
            self._inline_dimension_editor_specs[key] = dict(spec)
            visible_keys.add(key)
        for key, editor in self._inline_dimension_editors.items():
            if key not in visible_keys:
                editor.hide()
        self._edge_dimension_editor_updating = False
        self._inline_dimension_editor_updating = False
        self._position_inline_dimension_editors()

    def _hide_inline_dimension_editors(self) -> None:
        if not hasattr(self, "_inline_dimension_editors"):
            return
        self._inline_dimension_editor_updating = True
        self._edge_dimension_editor_updating = True
        for editor in self._inline_dimension_editors.values():
            editor.hide()
        self._inline_dimension_editor_specs = {}
        self._edge_dimension_editor_selection = None
        self._edge_dimension_editor_updating = False
        self._inline_dimension_editor_updating = False

    def _position_inline_dimension_editors(self) -> None:
        if not hasattr(self, "_inline_dimension_editors"):
            return
        if not self._viewer.is_initialized:
            return
        for key in tuple(self._inline_dimension_editor_specs):
            self._position_inline_dimension_editor(key)

    def _position_inline_dimension_editor(self, key: str) -> None:
        editor = self._inline_dimension_editors.get(key)
        spec = self._inline_dimension_editor_specs.get(key)
        if editor is None or spec is None or editor.isHidden():
            return
        position = spec.get("position")
        if not isinstance(position, tuple) or len(position) != 3:
            return
        view_x, view_y = self._viewer.view.Convert(*position)
        scale = self.devicePixelRatioF() or 1.0
        offset = spec.get("offset", (14, 14))
        if not isinstance(offset, tuple) or len(offset) != 2:
            offset = (14, 14)
        x = int(round(view_x / scale)) + int(offset[0])
        y = int(round(view_y / scale)) + int(offset[1])
        max_x = max(0, self.width() - editor.width() - 8)
        max_y = max(0, self.height() - editor.height() - 8)
        x = min(max(8, x), max_x)
        y = min(max(8, y), max_y)
        editor.move(self.mapToGlobal(QPoint(x, y)))

    def _commit_inline_dimension_editor(self, key: str) -> None:
        if (
            not hasattr(self, "_inline_dimension_editors")
            or self._inline_dimension_editor_updating
        ):
            return
        spec = self._inline_dimension_editor_specs.get(key)
        if spec is None:
            return
        spec_type = spec.get("type")
        if spec_type == "edge":
            self._commit_edge_dimension_editor()
            return
        if spec_type == "box":
            self._commit_box_dimension_editors(spec)
            return
        if spec_type == "sketch":
            self._commit_sketch_dimension_editors(spec)

    def _commit_box_dimension_editors(self, spec: dict[str, object]) -> None:
        item_id = spec.get("item_id")
        if not isinstance(item_id, str) or not self._box_dimensions_editable(item_id):
            self._hide_inline_dimension_editors()
            return
        current_selection = self._scene.selection()
        if current_selection is not None and current_selection.item_id != item_id:
            self._hide_inline_dimension_editors()
            return
        old_width, old_depth, old_height, _anchor = axis_aligned_box_dimensions(
            self._scene.get(item_id).shape
        )
        width = (
            float(self._inline_dimension_editors["box_width"].value())
            if "box_width" in self._inline_dimension_editor_specs
            else old_width
        )
        depth = (
            float(self._inline_dimension_editors["box_depth"].value())
            if "box_depth" in self._inline_dimension_editor_specs
            else old_depth
        )
        height = (
            float(self._inline_dimension_editors["box_height"].value())
            if "box_height" in self._inline_dimension_editor_specs
            else old_height
        )
        try:
            self._resize_box_dimensions(
                item_id,
                width,
                depth,
                height,
                current_selection,
            )
        except (CommandError, IndexError, RuntimeError, ValueError) as exc:
            LOGGER.warning("Inline box dimension edit failed: %s", exc, exc_info=True)
            self._show_status("Edit Dimensions failed")
            return
        self._show_status(
            f"Box dimensions set to {width:.2f} x {depth:.2f} x {height:.2f} mm"
        )
        self._set_context_hint("Box dimensions updated")
        self._refresh_hud()

    def _commit_sketch_dimension_editors(self, spec: dict[str, object]) -> None:
        item_id = spec.get("item_id")
        selection = self._scene.selection()
        if (
            not isinstance(item_id, str)
            or selection is None
            or selection.item_id != item_id
            or not is_sketch_profile(self._scene.get(item_id).meta)
        ):
            self._hide_inline_dimension_editors()
            return
        meta = self._scene.get(item_id).meta
        width = (
            float(self._inline_dimension_editors["sketch_width"].value())
            if "sketch_width" in self._inline_dimension_editor_specs
            else self._sketch_meta_float(meta, "width")
        )
        height = (
            float(self._inline_dimension_editors["sketch_height"].value())
            if "sketch_height" in self._inline_dimension_editor_specs
            else self._sketch_meta_float(meta, "height")
        )
        radius = (
            float(self._inline_dimension_editors["sketch_radius"].value())
            if "sketch_radius" in self._inline_dimension_editor_specs
            else self._sketch_meta_float(meta, "radius")
        )
        inner_radius = (
            float(self._inline_dimension_editors["sketch_inner_radius"].value())
            if "sketch_inner_radius" in self._inline_dimension_editor_specs
            else self._sketch_meta_float(meta, "inner_circle_radius")
        )
        self._resize_selected_sketch_profile(
            width=width,
            height=height,
            radius=radius,
            inner_circle_radius=inner_radius,
        )

    def _show_selected_sketch_dimension_editors(
        self,
        meta: dict[str, object],
    ) -> None:
        if not hasattr(self, "_inline_dimension_editors"):
            return
        selection = self._scene.selection()
        if (
            selection is None
            or not self._viewer.is_initialized
            or not is_sketch_profile(self._scene.get(selection.item_id).meta)
        ):
            self._hide_inline_dimension_editors()
            return
        workplane = self._workplane_from_sketch_meta(meta)
        center_u = self._sketch_meta_float(meta, "center_u") or 0.0
        center_v = self._sketch_meta_float(meta, "center_v") or 0.0
        width = self._sketch_meta_float(meta, "width")
        height = self._sketch_meta_float(meta, "height")
        radius = self._sketch_meta_float(meta, "radius")
        inner_radius = self._sketch_meta_float(meta, "inner_circle_radius")
        specs: list[dict[str, object]] = []
        if width is not None and height is not None:
            specs.extend(
                [
                    {
                        "key": "sketch_width",
                        "type": "sketch",
                        "label": "W",
                        "value": width,
                        "position": self._offset_workplane_point(
                            workplane,
                            (center_u, center_v + height / 2.0 + 6.0),
                        ),
                        "item_id": selection.item_id,
                        "selection": selection,
                        "offset": (14, 14),
                        "tooltip": "Edit sketch width",
                    },
                    {
                        "key": "sketch_height",
                        "type": "sketch",
                        "label": "H",
                        "value": height,
                        "position": self._offset_workplane_point(
                            workplane,
                            (center_u + width / 2.0 + 6.0, center_v),
                        ),
                        "item_id": selection.item_id,
                        "selection": selection,
                        "offset": (14, 14),
                        "tooltip": "Edit sketch height",
                    },
                ]
            )
        if radius is not None:
            specs.append(
                {
                    "key": "sketch_radius",
                    "type": "sketch",
                    "label": "R",
                    "value": radius,
                    "position": self._offset_workplane_point(
                        workplane,
                        (center_u + radius + 6.0, center_v),
                    ),
                    "item_id": selection.item_id,
                    "selection": selection,
                    "offset": (14, 14),
                    "tooltip": "Edit sketch radius",
                }
            )
        if inner_radius is not None:
            circle_u = self._sketch_meta_float(meta, "inner_circle_center_u")
            circle_v = self._sketch_meta_float(meta, "inner_circle_center_v")
            specs.append(
                {
                    "key": "sketch_inner_radius",
                    "type": "sketch",
                    "label": "Inner R",
                    "value": inner_radius,
                    "position": self._offset_workplane_point(
                        workplane,
                        (
                            (circle_u if circle_u is not None else center_u)
                            + inner_radius
                            + 6.0,
                            circle_v if circle_v is not None else center_v,
                        ),
                    ),
                    "item_id": selection.item_id,
                    "selection": selection,
                    "offset": (14, 14),
                    "tooltip": "Edit inner radius",
                }
            )
        self._show_inline_dimension_editors(specs)

    def _commit_edge_dimension_editor(self) -> None:
        if (
            not hasattr(self, "_edge_dimension_editor")
            or self._edge_dimension_editor_updating
        ):
            return
        selection = self._edge_dimension_editor_selection
        current_selection = self._scene.selection()
        if selection is None or current_selection != selection:
            return
        measurement = self._selected_edge_measurement()
        if measurement is None:
            self._hide_edge_dimension_editor()
            return
        new_length = float(self._edge_dimension_editor.value())
        if abs(new_length - measurement.length) < 1e-6:
            self._position_edge_dimension_editor(measurement)
            return
        try:
            self._resize_box_along_selected_edge(selection, measurement, new_length)
        except (CommandError, IndexError, RuntimeError, ValueError) as exc:
            LOGGER.warning("Inline edge length edit failed: %s", exc, exc_info=True)
            self._show_status("Edit Length failed")
            self._show_edge_dimension_editor(selection, measurement)
            return
        updated = self._selected_edge_measurement()
        if updated is not None:
            self._show_edge_dimension_editor(selection, updated)
        self._show_status(f"Edge length set to {new_length:.2f} mm")
        self._set_context_hint("Box dimension updated")
        self._refresh_hud()

    def _selected_edge_length_editable(self) -> bool:
        selection = self._scene.selection()
        measurement = self._selected_edge_measurement()
        if selection is None or measurement is None:
            return False
        if measurement.axis_name is None:
            return False
        return self._box_dimensions_editable(selection.item_id)

    def _box_dimensions_editable(self, item_id: str | None = None) -> bool:
        if item_id is None:
            selection = self._scene.selection()
            if selection is None:
                item_id = self._scene.active_item_id()
            else:
                item_id = selection.item_id
        if item_id is None:
            return False
        item = self._scene.get(item_id)
        if item.meta.get("kind") != "body":
            return False
        if item.meta.get("source") not in BOX_DIMENSION_SOURCES:
            return False
        if item.meta.get("profile") not in BOX_DIMENSION_PROFILES:
            return False
        try:
            axis_aligned_box_dimensions(item.shape)
        except (RuntimeError, ValueError):
            return False
        return True

    def _show_selected_box_dimensions(self) -> None:
        selection = self._scene.selection()
        if selection is None or not self._viewer.is_initialized:
            self._hide_inline_dimension_editors()
            return
        if not self._box_dimensions_editable(selection.item_id):
            self._hide_inline_dimension_editors()
            return
        labels = self._box_dimension_labels(selection.item_id)
        if labels:
            self._viewer.display_dimension_labels(labels)
            self._show_inline_dimension_editors(
                [
                    {
                        **spec,
                        "type": "box",
                        "item_id": selection.item_id,
                        "selection": selection,
                    }
                    for spec in self._box_dimension_specs(selection.item_id)
                ]
            )

    def _box_dimension_labels(
        self,
        item_id: str,
    ) -> list[tuple[str, tuple[float, float, float]]]:
        return [
            (str(spec["text"]), spec["position"])
            for spec in self._box_dimension_specs(item_id)
        ]

    def _box_dimension_specs(
        self,
        item_id: str,
    ) -> list[dict[str, object]]:
        item = self._scene.get(item_id)
        width, depth, height, _anchor = axis_aligned_box_dimensions(item.shape)
        from OCP.Bnd import Bnd_Box
        from OCP.BRepBndLib import BRepBndLib

        bounds = Bnd_Box()
        BRepBndLib.Add_s(item.shape, bounds)
        x_min, y_min, z_min, x_max, y_max, z_max = bounds.Get()
        center_x = (x_min + x_max) * 0.5
        center_y = (y_min + y_max) * 0.5
        center_z = (z_min + z_max) * 0.5
        margin = max(width, depth, height) * 0.08 + 4.0
        return [
            {
                "key": "box_width",
                "label": "W",
                "value": width,
                "text": f"W {width:.2f} mm",
                "position": (center_x, y_min - margin, z_min),
                "offset": (14, 14),
                "tooltip": "Edit width",
            },
            {
                "key": "box_depth",
                "label": "D",
                "value": depth,
                "text": f"D {depth:.2f} mm",
                "position": (x_max + margin, center_y, z_min),
                "offset": (14, 14),
                "tooltip": "Edit depth",
            },
            {
                "key": "box_height",
                "label": "H",
                "value": height,
                "text": f"H {height:.2f} mm",
                "position": (x_max + margin, y_max, center_z),
                "offset": (14, 14),
                "tooltip": "Edit height",
            },
        ]

    def _edit_selected_edge_length(self) -> None:
        selection = self._scene.selection()
        measurement = self._selected_edge_measurement()
        if selection is None or measurement is None:
            self._show_status("Select an edge first")
            return
        if not self._selected_edge_length_editable():
            self._show_status("Edit Length supports straight box edges")
            return
        new_length, ok = QInputDialog.getDouble(
            self,
            "Edit Edge Length",
            f"{measurement.axis_name or 'Edge'} length (mm)",
            measurement.length,
            0.001,
            1_000_000.0,
            2,
        )
        if not ok:
            return
        try:
            self._resize_box_along_selected_edge(selection, measurement, new_length)
        except (CommandError, IndexError, RuntimeError, ValueError) as exc:
            LOGGER.warning("Edit edge length failed: %s", exc, exc_info=True)
            self._show_status("Edit Length failed")
            return
        self._show_status(f"Edge length set to {new_length:.2f} mm")
        self._set_context_hint("Box dimension updated")
        self._refresh_hud()

    def _edit_selected_box_dimensions(self) -> None:
        selection = self._scene.selection()
        item_id = (
            selection.item_id if selection is not None else self._scene.active_item_id()
        )
        if item_id is None:
            self._show_status("Select a box body, face, or edge first")
            return
        if not self._box_dimensions_editable(item_id):
            self._show_status("Edit Dimensions supports rectangular box bodies")
            return
        item = self._scene.get(item_id)
        width, depth, height, _anchor = axis_aligned_box_dimensions(item.shape)
        new_width, ok = QInputDialog.getDouble(
            self,
            "Edit Box Dimensions",
            "Width X (mm)",
            width,
            0.001,
            1_000_000.0,
            2,
        )
        if not ok:
            return
        new_depth, ok = QInputDialog.getDouble(
            self,
            "Edit Box Dimensions",
            "Depth Y (mm)",
            depth,
            0.001,
            1_000_000.0,
            2,
        )
        if not ok:
            return
        new_height, ok = QInputDialog.getDouble(
            self,
            "Edit Box Dimensions",
            "Height Z (mm)",
            height,
            0.001,
            1_000_000.0,
            2,
        )
        if not ok:
            return
        try:
            self._resize_box_dimensions(
                item_id,
                new_width,
                new_depth,
                new_height,
                selection,
            )
        except (CommandError, IndexError, RuntimeError, ValueError) as exc:
            LOGGER.warning("Edit box dimensions failed: %s", exc, exc_info=True)
            self._show_status("Edit Dimensions failed")
            return
        self._show_status(
            f"Box dimensions set to {new_width:.2f} x "
            f"{new_depth:.2f} x {new_height:.2f} mm"
        )
        self._set_context_hint("Box dimensions updated")
        self._refresh_hud()

    def _edit_selected_position(self) -> None:
        target = self._position_edit_target()
        if target is None:
            self._show_status("Select a body or sketch first")
            return
        item_id, target_label = target
        center = self._shape_center(self._scene.get(item_id).shape)
        if center is None:
            self._show_status("Position unavailable")
            return
        x, ok = QInputDialog.getDouble(
            self,
            f"Set {target_label} Position",
            "Center X (mm)",
            center[0],
            -1_000_000.0,
            1_000_000.0,
            2,
        )
        if not ok:
            return
        y, ok = QInputDialog.getDouble(
            self,
            f"Set {target_label} Position",
            "Center Y (mm)",
            center[1],
            -1_000_000.0,
            1_000_000.0,
            2,
        )
        if not ok:
            return
        z, ok = QInputDialog.getDouble(
            self,
            f"Set {target_label} Position",
            "Center Z (mm)",
            center[2],
            -1_000_000.0,
            1_000_000.0,
            2,
        )
        if not ok:
            return
        self._set_selected_position((x, y, z))

    def _set_selected_position(
        self,
        target_center: tuple[float, float, float],
    ) -> None:
        target = self._position_edit_target()
        if target is None:
            self._show_status("Select a body or sketch first")
            return
        item_id, target_label = target
        current_center = self._shape_center(self._scene.get(item_id).shape)
        if current_center is None:
            self._show_status("Position unavailable")
            return
        dx, dy, dz = (
            target_component - current_component
            for target_component, current_component in zip(
                target_center, current_center
            )
        )
        if abs(dx) < 1e-7 and abs(dy) < 1e-7 and abs(dz) < 1e-7:
            self._show_status("Position unchanged")
            return
        scene_object = self._scene.get(item_id)
        if is_sketch_object(scene_object.meta):
            self._apply_sketch_move((item_id,), (dx, dy, dz))
            selection = self._scene.selection()
            if selection is not None and selection.item_id == item_id:
                self._scene.set_selection(selection)
        else:
            apply_move_object(self._scene, item_id, dx, dy, dz)
        self._hover_selection = None
        if self._viewer.is_initialized:
            self._viewer.display_scene(self._scene, fit=False)
            selection = self._scene.selection()
            if selection is not None and selection.item_id == item_id:
                self._viewer.display_selection_marker(
                    self._picker.subshape(
                        selection.item_id,
                        selection.kind,
                        selection.index,
                    ),
                    self._scene.get(item_id).meta,
                )
        self._show_status(
            f"{target_label} position set to "
            f"X {target_center[0]:.2f}, Y {target_center[1]:.2f}, "
            f"Z {target_center[2]:.2f}"
        )
        self._set_context_hint("Absolute center position updated")
        self._refresh_hud()

    def _position_edit_target(self) -> tuple[str, str] | None:
        if len(self._scene.selection_refs()) > 1:
            return None
        selection = self._scene.selection()
        item_id = (
            selection.item_id if selection is not None else self._scene.active_item_id()
        )
        if item_id is None or item_id not in self._scene:
            return None
        meta = self._scene.get(item_id).meta
        if is_sketch_object(meta):
            return item_id, "Sketch"
        if selection is not None and selection.kind != SelectionKind.OBJECT:
            return None
        return item_id, "Body"

    def _resize_box_along_selected_edge(
        self,
        selection: SelectionRef,
        measurement: EdgeMeasurement,
        new_length: float,
    ) -> None:
        item = self._scene.get(selection.item_id)
        width, depth, height, anchor = axis_aligned_box_dimensions(item.shape)
        axis_name = measurement.axis_name
        if axis_name == "X":
            width = new_length
        elif axis_name == "Y":
            depth = new_length
        elif axis_name == "Z":
            height = new_length
        else:
            raise ValueError("Selected edge is not axis-aligned.")

        shape = translated_shape(make_box(width, depth, height), *anchor)
        next_meta = self._box_dimension_meta(item.meta, width, depth, height)
        self._scene.replace_shape(selection.item_id, shape, next_meta)
        self._scene.set_selection(selection)
        self._hover_selection = None
        if self._viewer.is_initialized:
            self._viewer.display_scene(self._scene, fit=False)
            self._viewer.display_selection_marker(
                self._picker.subshape(
                    selection.item_id,
                    SelectionKind.EDGE,
                    selection.index,
                ),
                next_meta,
            )
            updated = self._selected_edge_measurement()
            if updated is not None:
                self._display_edge_measurement(updated)
                self._show_edge_dimension_editor(selection, updated)

    def _resize_box_dimensions(
        self,
        item_id: str,
        width: float,
        depth: float,
        height: float,
        selection: SelectionRef | None,
    ) -> None:
        item = self._scene.get(item_id)
        _old_width, _old_depth, _old_height, anchor = axis_aligned_box_dimensions(
            item.shape
        )
        shape = translated_shape(make_box(width, depth, height), *anchor)
        next_meta = self._box_dimension_meta(item.meta, width, depth, height)
        self._scene.replace_shape(item_id, shape, next_meta)
        if selection is not None:
            self._scene.set_selection(selection)
        else:
            self._scene.set_active_item(item_id)
        self._hover_selection = None
        if self._viewer.is_initialized:
            self._viewer.display_scene(self._scene, fit=False)
            if selection is not None:
                self._viewer.display_selection_marker(
                    self._picker.subshape(
                        selection.item_id,
                        selection.kind,
                        selection.index,
                    ),
                    next_meta,
                )
            self._show_selected_box_dimensions()

    @staticmethod
    def _box_dimension_meta(
        meta: dict,
        width: float,
        depth: float,
        height: float,
    ) -> dict:
        return {
            **meta,
            "width": width,
            "depth": depth,
            "height": height,
        }

    def _circle_feature_on_selected_face(self, cut: bool) -> None:
        item_id, face_index = self._selected_face()
        if item_id is None or face_index is None:
            self._show_status("Select a face first")
            LOGGER.info("Circle feature ignored because no face is selected")
            return
        try:
            apply_circle_feature(
                self._scene,
                item_id,
                face_index,
                radius=8.0,
                depth=30.0,
                cut=cut,
            )
        except (CommandError, IndexError, ValueError) as exc:
            LOGGER.warning(
                "Circle feature failed item_id=%s face=%s cut=%s: %s",
                item_id,
                face_index,
                cut,
                exc,
                exc_info=True,
            )
            self._show_status("Circle feature failed")
            return
        self._scene.set_selection(None)
        self._hover_selection = None
        if self._viewer.is_initialized:
            self._viewer.display_scene(self._scene, fit=False)
        self._show_status("Circle cut applied" if cut else "Circle boss applied")
        LOGGER.info(
            "Circle feature applied item_id=%s face=%d cut=%s",
            item_id,
            face_index,
            cut,
        )

    def _remove_selected_face(self) -> None:
        item_id, face_index = self._selected_face()
        if item_id is None or face_index is None:
            self._show_status("Select a face first")
            LOGGER.info("Remove Face ignored because no face is selected")
            return
        try:
            apply_remove_face(self._scene, item_id, face_index)
        except (CommandError, IndexError, ValueError) as exc:
            LOGGER.warning(
                "Remove Face failed item_id=%s face=%s: %s",
                item_id,
                face_index,
                exc,
                exc_info=True,
            )
            self._show_status("Remove Face failed")
            return
        self._hover_selection = None
        if self._viewer.is_initialized:
            self._viewer.display_scene(self._scene, fit=False)
        self._show_status("Face removed")
        LOGGER.info("Face removed item_id=%s face=%d", item_id, face_index)
