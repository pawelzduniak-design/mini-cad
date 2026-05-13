"""Sketch profile regionization behavior for ViewerWidget."""

from __future__ import annotations

import logging

from cad_app.commands import CommandError
from cad_app.sketch import (
    SKETCH_META_KIND,
    is_sketch_profile,
    split_profile_regions,
    subtract_profile_regions,
)
from cad_app.sketch_graph import shape_graph_meta
from cad_app.types import SelectionKind, SelectionRef
from cad_app.ui_sessions import SketchSession

LOGGER = logging.getLogger(__name__)


class ViewerWidgetSketchRegionMixin:
    def _try_regionize_profile_with_existing(
        self,
        session: SketchSession,
        profile,
        profile_meta: dict[str, object],
    ) -> bool:
        splits = self._profile_region_splits(session, profile)
        if not splits:
            return False

        host_shapes = tuple(
            host_shape for _item_id, _split, _meta, host_shape in splits
        )
        try:
            tool_regions = subtract_profile_regions(profile, host_shapes)
        except (CommandError, ValueError):
            return False

        new_region_ids: list[str] = []
        selected_region_id: str | None = None
        with self._scene.transaction():
            for host_item_id, split, host_meta, _host_shape in splits:
                if host_item_id in session.profile_ids:
                    session.profile_ids.remove(host_item_id)
                self._scene.remove(host_item_id)
                for role, faces, source_meta in (
                    ("base", split.base_regions, host_meta),
                    (
                        "intersection",
                        split.common_regions,
                        {**host_meta, **profile_meta},
                    ),
                ):
                    for face in faces:
                        item_id = self._add_region_profile_item(
                            session,
                            face,
                            self._sketch_region_meta(
                                source_meta=source_meta,
                                role=role,
                            ),
                        )
                        new_region_ids.append(item_id)
                        if selected_region_id is None and role == "base":
                            selected_region_id = item_id

            for face in tool_regions:
                item_id = self._add_region_profile_item(
                    session,
                    face,
                    self._sketch_region_meta(
                        source_meta=profile_meta,
                        role="tool",
                    ),
                )
                new_region_ids.append(item_id)
            if selected_region_id is None and new_region_ids:
                selected_region_id = new_region_ids[0]
            if selected_region_id is not None:
                self._scene.set_active_item(selected_region_id)
                self._scene.set_selection(
                    SelectionRef(
                        item_id=selected_region_id,
                        kind=SelectionKind.FACE,
                        index=1,
                    )
                )
        if selected_region_id is None:
            return False
        if self._viewer.is_initialized:
            self._viewer.display_scene(self._scene, fit=False)
            selected = self._scene.get(selected_region_id)
            self._viewer.display_selection_marker(selected.shape, selected.meta)
        self._continue_sketch_after_profile(
            session,
            "Sketch regions updated",
        )
        LOGGER.info(
            "Sketch regions updated hosts=%d tool_profile=%s regions=%d",
            len(splits),
            profile_meta.get("profile"),
            len(new_region_ids),
        )
        return True

    def _profile_region_splits(
        self,
        session: SketchSession,
        profile,
    ) -> list[tuple[str, object, dict[str, object], object]]:
        def _split_for(item_id: str):
            if item_id not in self._scene:
                return None
            item = self._scene.get(item_id)
            if not is_sketch_profile(item.meta):
                return None
            try:
                return split_profile_regions(item.shape, profile)
            except (CommandError, ValueError):
                return None

        candidates: list[tuple[str, object, dict[str, object], object]] = []
        for item_id in self._profile_region_candidate_ids(session):
            split = _split_for(item_id)
            if split is None or not split.has_intersection:
                continue
            item = self._scene.get(item_id)
            candidates.append((item_id, split, dict(item.meta), item.shape))
        return candidates

    def _profile_region_candidate_ids(self, session: SketchSession) -> list[str]:
        candidate_ids: list[str] = []

        def add_candidate(item_id: str | None) -> None:
            if (
                item_id is None
                or item_id in candidate_ids
                or item_id not in self._scene
            ):
                return
            item = self._scene.get(item_id)
            if is_sketch_profile(item.meta) and self._sketch_item_matches_session(
                item.item_id,
                item.meta,
                session,
            ):
                candidate_ids.append(item_id)

        if session.host is not None:
            add_candidate(session.host[0])

        selection = self._scene.selection()
        if selection is not None and selection.item_id in self._scene:
            selected_item = self._scene.get(selection.item_id)
            selected_in_active_sketch = selection.item_id in session.profile_ids
            selected_from_browser = self._selection_source == "browser"
            if is_sketch_profile(selected_item.meta) and (
                selected_in_active_sketch or selected_from_browser
            ):
                add_candidate(selection.item_id)

        for item_id in session.profile_ids:
            add_candidate(item_id)
        return candidate_ids

    def _add_region_profile_item(
        self,
        session: SketchSession,
        profile,
        meta: dict[str, object],
    ) -> str:
        workplane = self._workplane_from_sketch_meta(meta)
        graph_meta = shape_graph_meta(profile, workplane)
        item_id = self._scene.add_shape(
            profile,
            meta={"kind": SKETCH_META_KIND, **meta, **graph_meta},
        )
        session.profile_ids.append(item_id)
        return item_id

    @staticmethod
    def _profile_area(profile) -> float:
        from OCP.BRepGProp import BRepGProp
        from OCP.GProp import GProp_GProps

        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(profile, props)
        return abs(float(props.Mass()))

    @staticmethod
    def _sketch_region_meta(
        source_meta: dict[str, object],
        role: str,
    ) -> dict[str, object]:
        source_profile = source_meta.get(
            "region_source_profile",
            source_meta.get("profile", "profile"),
        )
        return {
            **source_meta,
            "profile": "sketch_region",
            "region_role": role,
            "region_source_profile": source_profile,
            "dimensions_editable": False,
        }
