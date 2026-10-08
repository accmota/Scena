"""The document being edited: level size + items, file I/O. No Graphics.

Items are the normalized dicts of ``scena.level_format`` plus a transient
``"id"`` (an int, never saved) that the view, the selection and undo use.
``version`` grows on every change so the view knows when to sync.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from typing import Any, Dict, Iterable, List, Optional, Tuple

from scena.level_format import KINDS, dumps, parse, parse_item, serialize

DEFAULT_SIZE = (1280.0, 800.0)


DECIMALS = 2        # the editor stores 0.01 design units; float noise never reaches a file


def tidy(value: Any) -> Any:
    """Numbers to ``DECIMALS`` places (``-0.0`` → ``0.0``), recursively."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return round(value, DECIMALS) + 0.0
    if isinstance(value, int):
        return value
    if isinstance(value, tuple):
        return tuple(tidy(v) for v in value)
    if isinstance(value, list):
        return [tidy(v) for v in value]
    return value


class NameTaken(ValueError):
    """Another item already has that name (names are unique in a level)."""


class LevelDoc:
    def __init__(self, size: Tuple[float, float] = DEFAULT_SIZE,
                 items: Iterable[Dict[str, Any]] = (), path: Optional[str] = None):
        self.size = (float(size[0]), float(size[1]))
        self.items: List[Dict[str, Any]] = []
        self.path = path
        self.version = 0
        self._next_id = 1
        for item in items:
            self._append(dict(item))
        self._saved = self.snapshot()
        self._dirty_cache = (self.version, False)

    # -- identity -----------------------------------------------------------
    def _append(self, item: Dict[str, Any], index: Optional[int] = None) -> int:
        item["id"] = self._next_id
        self._next_id += 1
        if index is None:
            self.items.append(item)
        else:
            self.items.insert(index, item)
        return item["id"]

    def _changed(self) -> None:
        self.version += 1

    @property
    def dirty(self) -> bool:
        """True when the content differs from the last save or load (undoing
        back to the saved state is clean again)."""
        version, dirty = self._dirty_cache
        if version != self.version:
            dirty = self.snapshot() != self._saved
            self._dirty_cache = (self.version, dirty)
        return dirty

    def get(self, item_id: int) -> Dict[str, Any]:
        for item in self.items:
            if item["id"] == item_id:
                return item
        raise KeyError(item_id)

    def has(self, item_id: int) -> bool:
        return any(item["id"] == item_id for item in self.items)

    def index_of(self, item_id: int) -> int:
        for i, item in enumerate(self.items):
            if item["id"] == item_id:
                return i
        raise KeyError(item_id)

    def names(self) -> Dict[str, int]:
        return {item["name"]: item["id"] for item in self.items if item.get("name")}

    def groups(self) -> List[str]:
        seen: Dict[str, None] = {}
        for item in self.items:
            for g in item["groups"]:
                seen.setdefault(g, None)
        return list(seen)

    # -- edits ----------------------------------------------------------------
    def add(self, raw: Dict[str, Any]) -> int:
        """Add an item (raw level-file fields, checked by ``parse_item``)."""
        item = parse_item({k: tidy(v) for k, v in raw.items() if k != "id"}, where="new item")
        if item["name"] is not None and item["name"] in self.names():
            raise NameTaken(item["name"])
        new_id = self._append(item)
        self._changed()
        return new_id

    def update(self, item_id: int, **fields) -> None:
        """Change fields of one item. Geometry is checked by ``parse_item``."""
        item = self.get(item_id)
        if "name" in fields:
            name = fields["name"]
            name = name.strip() if isinstance(name, str) else name
            fields["name"] = name or None
            if fields["name"] is not None:
                owner = self.names().get(fields["name"])
                if owner is not None and owner != item_id:
                    raise NameTaken(fields["name"])
        merged = {k: v for k, v in item.items() if k != "id"}
        merged.update({k: tidy(v) for k, v in fields.items()})
        checked = parse_item(_raw(merged), where=f"item {item_id}")
        if all(item.get(k) == v for k, v in checked.items()):
            return
        checked["id"] = item_id
        self.items[self.index_of(item_id)] = checked
        self._changed()

    def remove(self, ids: Iterable[int]) -> None:
        ids = set(ids)
        before = len(self.items)
        self.items = [item for item in self.items if item["id"] not in ids]
        if len(self.items) != before:
            self._changed()

    def duplicate(self, ids: Iterable[int], offset: Tuple[float, float]) -> List[int]:
        """Copies placed ``offset`` away, on top; a copied name gets ``_2``, ``_3`` …"""
        from .geometry import translate
        new_ids = []
        for item_id in [i for i in (it["id"] for it in self.items) if i in set(ids)]:
            src = self.get(item_id)
            copy = {k: v for k, v in src.items() if k != "id"}
            copy.update(translate(copy, *offset))
            if copy.get("name"):
                copy["name"] = self.free_name(copy["name"])
            new_ids.append(self._append(copy))
        if new_ids:
            self._changed()
        return new_ids

    def free_name(self, name: str) -> str:
        taken = self.names()
        base = name
        n = 2
        if "_" in name and name.rsplit("_", 1)[1].isdigit():
            base, tail = name.rsplit("_", 1)
            n = int(tail) + 1
        while f"{base}_{n}" in taken:
            n += 1
        return f"{base}_{n}"

    def restack(self, ids: Iterable[int], *, front: bool) -> None:
        """Move items to the top (``front``) or the bottom of the draw order."""
        ids = set(ids)
        moved = [item for item in self.items if item["id"] in ids]
        rest = [item for item in self.items if item["id"] not in ids]
        new = rest + moved if front else moved + rest
        if [i["id"] for i in new] != [i["id"] for i in self.items]:
            self.items = new
            self._changed()

    def set_size(self, width: float, height: float) -> None:
        size = (float(width), float(height))
        if size[0] < 0 or size[1] < 0:
            raise ValueError("level size must be >= 0")
        if size != self.size:
            self.size = size
            self._changed()

    # -- undo snapshots -----------------------------------------------------------
    def snapshot(self) -> tuple:
        """An immutable copy of the content (items keep their ids)."""
        return (self.size, tuple(tuple(sorted(item.items())) for item in self.items))

    def restore(self, snap: tuple) -> None:
        size, items = snap
        self.size = size
        self.items = [dict(pairs) for pairs in items]
        self._next_id = max([self._next_id] + [i["id"] + 1 for i in self.items])
        self._changed()

    # -- files -------------------------------------------------------------------
    def base_dir(self) -> str:
        return os.path.dirname(os.path.abspath(self.path)) if self.path else os.getcwd()

    def image_path(self, item: Dict[str, Any]) -> str:
        """Absolute path of an image item's file."""
        file = item["file"]
        if os.path.isabs(file):
            return os.path.normpath(file)
        return os.path.normpath(os.path.join(self.base_dir(), *file.split("/")))

    def relative_file(self, absolute: str, folder: Optional[str] = None) -> str:
        """``absolute`` relative to ``folder`` (default: the level's), POSIX.
        Absolute when no relative path exists (another drive on Windows)."""
        folder = folder or self.base_dir()
        try:
            rel = os.path.relpath(absolute, folder)
        except ValueError:
            return absolute
        return rel.replace(os.sep, "/")

    def to_file_dict(self, folder: Optional[str] = None) -> Dict[str, Any]:
        """The level file content; image paths rebased onto ``folder``."""
        items = []
        for item in self.items:
            item = {k: v for k, v in item.items() if k != "id"}
            if item["kind"] == "image" and folder is not None:
                item["file"] = self.relative_file(self.image_path(item), folder)
            items.append(item)
        return serialize({"size": self.size, "items": items})

    def save(self, path: Optional[str] = None) -> str:
        """Write the level (atomically; the previous file is kept as ``.bak``)."""
        path = os.path.abspath(path or self.path)
        folder = os.path.dirname(path)
        data = self.to_file_dict(folder)
        text = dumps(data)
        fd, tmp = tempfile.mkstemp(prefix=".level_", suffix=".json", dir=folder)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            if os.path.exists(path):
                shutil.copy2(path, path + ".bak")
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
        # Image paths now live relative to the new folder.
        for item, written in zip(self.items, data["items"]):
            if item["kind"] == "image":
                item["file"] = written["file"]
        self.path = path
        self._saved = self.snapshot()
        self._dirty_cache = (self.version, False)
        return path

    @classmethod
    def load(cls, path: str) -> "LevelDoc":
        path = os.path.abspath(path)
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
        doc_data = parse(data, source=os.path.basename(path))
        return cls(doc_data["size"], doc_data["items"], path=path)


def _raw(item: Dict[str, Any]) -> Dict[str, Any]:
    """A normalized item back to raw fields (for re-checking after an edit)."""
    out = {}
    for key, value in item.items():
        if key == "groups":
            out[key] = list(value)
        elif isinstance(value, tuple):
            out[key] = [list(v) if isinstance(v, tuple) else v for v in value]
        else:
            out[key] = value
    if out.get("name") is None:
        out.pop("name", None)
    return out


__all__ = ["LevelDoc", "NameTaken", "DEFAULT_SIZE", "KINDS"]
