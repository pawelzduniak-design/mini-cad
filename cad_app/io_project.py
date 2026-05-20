"""Native project save / load.

Stores the scene as a JSON file with each shape serialised to a base64
BREP string (`BRepTools.Write` round-trips solids, shells, compounds,
sketches, edges, etc. with exact B-rep fidelity, unlike STEP which
discards meta and feature history). Meta dictionaries are kept verbatim
when they are JSON-serialisable; non-serialisable values are dropped
with a note so reloading never silently fabricates data.

File format (versioned):

    {
        "format": "cad_app.project",
        "version": 1,
        "active_item_id": "uuid-or-null",
        "items": [
            {"item_id": "uuid", "meta": {...}, "brep_b64": "..."}
        ]
    }
"""

from __future__ import annotations

import base64
import json
import logging
from io import BytesIO
from os import PathLike
from typing import Any

from cad_app.scene import Scene

LOGGER = logging.getLogger(__name__)

PROJECT_FORMAT = "cad_app.project"
PROJECT_VERSION = 1


class ProjectIOError(RuntimeError):
    """Raised when project save or load fails."""


def save_project(scene: Scene, path: str | PathLike[str]) -> None:
    """Write ``scene`` to ``path`` as a native project JSON file."""
    payload = {
        "format": PROJECT_FORMAT,
        "version": PROJECT_VERSION,
        "active_item_id": scene.active_item_id(),
        "items": [
            {
                "item_id": item.item_id,
                "meta": _json_safe_meta(item.meta),
                "brep_b64": _shape_to_brep_b64(item.shape),
            }
            for item in scene
        ],
    }
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False, sort_keys=False)
    except OSError as exc:
        raise ProjectIOError(f"Failed to write project file: {exc}") from exc


def load_project(path: str | PathLike[str]) -> Scene:
    """Read a native project JSON file and return a fresh ``Scene``."""
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectIOError(f"Failed to read project file: {exc}") from exc

    if not isinstance(payload, dict):
        raise ProjectIOError("Project file must contain a JSON object at root.")
    fmt = payload.get("format")
    version = payload.get("version")
    if fmt != PROJECT_FORMAT:
        raise ProjectIOError(
            f"Unknown project format: {fmt!r} (expected {PROJECT_FORMAT!r})."
        )
    if version != PROJECT_VERSION:
        raise ProjectIOError(
            f"Unsupported project version: {version!r} "
            f"(this build expects {PROJECT_VERSION})."
        )

    items_payload = payload.get("items", [])
    if not isinstance(items_payload, list):
        raise ProjectIOError("Project 'items' must be a list.")

    scene = Scene()
    # We cannot use scene.add_shape because it generates new UUIDs;
    # we want to preserve the saved item_ids so feature history and
    # selection state remain meaningful across save/load.
    requested_active = payload.get("active_item_id")
    for entry in items_payload:
        if not isinstance(entry, dict):
            raise ProjectIOError("Project item must be a JSON object.")
        item_id = entry.get("item_id")
        if not isinstance(item_id, str) or not item_id:
            raise ProjectIOError("Project item is missing a string 'item_id'.")
        brep_b64 = entry.get("brep_b64")
        if not isinstance(brep_b64, str):
            raise ProjectIOError(
                f"Project item {item_id!r} is missing 'brep_b64' payload."
            )
        meta = entry.get("meta", {}) or {}
        if not isinstance(meta, dict):
            raise ProjectIOError(f"Project item {item_id!r} has non-object meta.")
        try:
            shape = _brep_b64_to_shape(brep_b64)
        except Exception as exc:  # noqa: BLE001 - any BREP parse error
            raise ProjectIOError(
                f"BREP payload of item {item_id!r} failed to load: {exc}"
            ) from exc
        _scene_add_with_id(scene, item_id, shape, meta)
    if isinstance(requested_active, str) and requested_active in scene:
        scene.set_active_item(requested_active)
    return scene


def _scene_add_with_id(scene: Scene, item_id: str, shape: Any, meta: dict) -> None:
    """Insert into ``scene`` preserving the saved item_id.

    Scene.add_shape mints a fresh UUID, but for round-tripping we want
    the same identifiers that were saved. We poke into the internal
    dict directly because Scene has no public re-key API; if Scene
    grows one in the future this should switch to that.
    """
    from cad_app.types import SceneObject

    # Bypass undo recording during load (loading is not an undoable
    # action). Touching _record_undo etc. would push redundant
    # snapshots onto the stack.
    scene._items[item_id] = SceneObject(  # noqa: SLF001
        item_id=item_id,
        shape=shape,
        meta=dict(meta),
    )
    if scene.active_item_id() is None:
        scene._active_item_id = item_id  # noqa: SLF001


def _shape_to_brep_b64(shape: Any) -> str:
    from OCP.BRepTools import BRepTools

    buffer = BytesIO()
    try:
        # Some OCP builds expose Write_s taking a file path; we use the
        # ostream overload available everywhere we ship.
        BRepTools.Write_s(shape, buffer)
    except TypeError:
        # Fallback: write to a tmp file then read back. Slower but
        # works on builds without a stream overload.
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".brep", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            BRepTools.Write_s(shape, tmp_path)
            with open(tmp_path, "rb") as fh:
                buffer.write(fh.read())
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _brep_b64_to_shape(payload: str) -> Any:
    from OCP.BRep import BRep_Builder
    from OCP.BRepTools import BRepTools
    from OCP.TopoDS import TopoDS_Shape

    raw = base64.b64decode(payload.encode("ascii"))
    builder = BRep_Builder()
    shape = TopoDS_Shape()
    buffer = BytesIO(raw)
    try:
        BRepTools.Read_s(shape, buffer, builder)
    except TypeError:
        # Same tmp-file fallback as the writer.
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".brep", delete=False) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name
        try:
            BRepTools.Read_s(shape, tmp_path, builder)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    if shape.IsNull():
        raise ProjectIOError("BREP payload produced a null shape.")
    return shape


def _json_safe_meta(meta: dict) -> dict:
    """Filter ``meta`` so json.dumps will not raise.

    Most meta entries are primitives (numbers, strings, dicts of
    those). The feature_history sub-dict embeds profile references
    that are dicts of primitives too. We pass-through any value that
    survives a json.dumps round-trip and drop anything else with a
    debug log so loading is reproducible.
    """
    safe: dict = {}
    for key, value in meta.items():
        if not isinstance(key, str):
            LOGGER.debug("project save: dropping non-string meta key %r", key)
            continue
        try:
            json.dumps(value)
        except TypeError:
            LOGGER.debug(
                "project save: meta key %s holds non-JSON value (type %s) - dropping",
                key,
                type(value).__name__,
            )
            continue
        safe[key] = value
    return safe
