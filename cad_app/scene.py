"""Scene model and shape storage."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from cad_app.types import SceneObject, SelectionRef


@dataclass
class SceneSnapshot:
    items: dict[str, SceneObject]
    active_item_id: str | None
    selection: SelectionRef | None
    selections: tuple[SelectionRef, ...]


class Scene:
    """Pure domain scene storing UUID-addressed TopoDS shapes."""

    def __init__(self) -> None:
        self._items: dict[str, SceneObject] = {}
        self._active_item_id: str | None = None
        self._selection: SelectionRef | None = None
        self._selections: tuple[SelectionRef, ...] = ()
        self._undo_stack: list[SceneSnapshot] = []
        self._redo_stack: list[SceneSnapshot] = []
        self._transaction_depth = 0
        self._transaction_snapshot: SceneSnapshot | None = None
        self._transaction_changed = False

    def __contains__(self, item_id: str) -> bool:
        return item_id in self._items

    def __iter__(self) -> Iterator[SceneObject]:
        return iter(self._items.values())

    def __len__(self) -> int:
        return len(self._items)

    def add_shape(self, shape: Any, meta: dict[str, Any] | None = None) -> str:
        self._record_undo()
        item_id = str(uuid4())
        self._items[item_id] = SceneObject(
            item_id=item_id,
            shape=shape,
            meta=dict(meta or {}),
        )
        if self._active_item_id is None:
            self._active_item_id = item_id
        return item_id

    def get(self, item_id: str) -> SceneObject:
        try:
            return self._items[item_id]
        except KeyError as exc:
            raise KeyError(f"Unknown scene object: {item_id}") from exc

    def replace_shape(
        self,
        item_id: str,
        shape: Any,
        meta: dict[str, Any] | None = None,
    ) -> None:
        current = self.get(item_id)
        self._record_undo()
        self._items[item_id] = SceneObject(
            item_id=item_id,
            shape=shape,
            meta=dict(current.meta if meta is None else meta),
        )

    def remove(self, item_id: str) -> SceneObject:
        self._record_undo()
        try:
            removed = self._items.pop(item_id)
        except KeyError as exc:
            raise KeyError(f"Unknown scene object: {item_id}") from exc
        active_removed = self._active_item_id == item_id
        selection_removed = (
            self._selection is not None and self._selection.item_id == item_id
        )
        self._selections = tuple(
            selection for selection in self._selections if selection.item_id != item_id
        )
        if selection_removed:
            self._selection = self._selections[0] if self._selections else None
        if active_removed:
            self._active_item_id = (
                self._selection.item_id
                if self._selection is not None
                else next(iter(self._items), None)
            )
        return removed

    def clear(self) -> None:
        self._items.clear()
        self._active_item_id = None
        self._selection = None
        self._selections = ()
        self._undo_stack.clear()
        self._redo_stack.clear()

    def active_item_id(self) -> str | None:
        return self._active_item_id

    def set_active_item(self, item_id: str) -> None:
        self.get(item_id)
        self._active_item_id = item_id

    def selection(self) -> SelectionRef | None:
        return self._selection

    def selection_refs(self) -> tuple[SelectionRef, ...]:
        return self._selections

    def set_selection(self, selection: SelectionRef | None) -> None:
        if selection is not None:
            self.get(selection.item_id)
            self._active_item_id = selection.item_id
        self._selection = selection
        self._selections = () if selection is None else (selection,)

    def set_selections(self, selections: tuple[SelectionRef, ...]) -> None:
        normalized: list[SelectionRef] = []
        seen: set[SelectionRef] = set()
        for selection in selections:
            self.get(selection.item_id)
            if selection in seen:
                continue
            seen.add(selection)
            normalized.append(selection)
        self._selections = tuple(normalized)
        self._selection = self._selections[0] if self._selections else None
        if self._selection is not None:
            self._active_item_id = self._selection.item_id

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def undo_depth(self) -> int:
        return len(self._undo_stack)

    def redo_depth(self) -> int:
        return len(self._redo_stack)

    def undo(self) -> SceneSnapshot | None:
        if not self._undo_stack:
            return None
        current = self._snapshot()
        previous = self._undo_stack.pop()
        self._redo_stack.append(current)
        self._restore_snapshot(previous)
        return previous

    def redo(self) -> SceneSnapshot | None:
        if not self._redo_stack:
            return None
        current = self._snapshot()
        next_snapshot = self._redo_stack.pop()
        self._undo_stack.append(current)
        self._restore_snapshot(next_snapshot)
        return next_snapshot

    @contextmanager
    def transaction(self) -> Iterator[None]:
        snapshot = self._snapshot()
        self._transaction_depth += 1
        if self._transaction_depth == 1:
            self._transaction_snapshot = snapshot
            self._transaction_changed = False
        failed = False
        try:
            yield
        except Exception:
            failed = True
            if self._transaction_depth == 1:
                self._restore_snapshot(snapshot)
            raise
        finally:
            self._transaction_depth -= 1
            if self._transaction_depth == 0:
                if (
                    not failed
                    and self._transaction_changed
                    and self._transaction_snapshot is not None
                ):
                    self._undo_stack.append(self._transaction_snapshot)
                    self._redo_stack.clear()
                self._transaction_snapshot = None
                self._transaction_changed = False

    def _record_undo(self) -> None:
        if self._transaction_depth > 0:
            self._transaction_changed = True
            return
        self._undo_stack.append(self._snapshot())
        self._redo_stack.clear()

    def _snapshot(self) -> SceneSnapshot:
        return SceneSnapshot(
            items={
                item_id: SceneObject(
                    item_id=item.item_id,
                    shape=item.shape,
                    meta=dict(item.meta),
                )
                for item_id, item in self._items.items()
            },
            active_item_id=self._active_item_id,
            selection=self._selection,
            selections=self._selections,
        )

    def _restore_snapshot(self, snapshot: SceneSnapshot) -> None:
        self._items = {
            item_id: SceneObject(
                item_id=item.item_id,
                shape=item.shape,
                meta=dict(item.meta),
            )
            for item_id, item in snapshot.items.items()
        }
        self._active_item_id = snapshot.active_item_id
        self._selection = snapshot.selection
        self._selections = snapshot.selections
