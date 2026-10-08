"""Undo / redo over whole-document snapshots.

One step per finished gesture: the editor calls :meth:`History.commit` when a
drag, resize, turn, creation or committed field edit ends. ``commit`` with
nothing changed records nothing, so pan and selection never become steps.
At hundreds of items a snapshot is cheap and always correct.
"""
from __future__ import annotations

from typing import List

from .doc import LevelDoc

LIMIT = 200


class History:
    def __init__(self, doc: LevelDoc, limit: int = LIMIT):
        self.doc = doc
        self.limit = limit
        self._past: List[tuple] = []
        self._future: List[tuple] = []
        self._current = doc.snapshot()

    def reset(self, doc: LevelDoc) -> None:
        """Forget every step (a new or opened document)."""
        self.doc = doc
        self._past.clear()
        self._future.clear()
        self._current = doc.snapshot()

    def commit(self) -> bool:
        """Record the document as one step if it changed. True when recorded."""
        snap = self.doc.snapshot()
        if snap == self._current:
            return False
        self._past.append(self._current)
        del self._past[:-self.limit]
        self._current = snap
        self._future.clear()
        return True

    def discard(self) -> None:
        """Throw away uncommitted changes (a cancelled gesture)."""
        if self.doc.snapshot() != self._current:
            self.doc.restore(self._current)

    @property
    def can_undo(self) -> bool:
        return bool(self._past)

    @property
    def can_redo(self) -> bool:
        return bool(self._future)

    def undo(self) -> bool:
        self.commit()          # an unfinished edit becomes its own step first
        if not self._past:
            return False
        self._future.append(self._current)
        self._current = self._past.pop()
        self.doc.restore(self._current)
        return True

    def redo(self) -> bool:
        if self.doc.snapshot() != self._current:
            return False       # edited since the undo: redo was cleared by that edit
        if not self._future:
            return False
        self._past.append(self._current)
        self._current = self._future.pop()
        self.doc.restore(self._current)
        return True
