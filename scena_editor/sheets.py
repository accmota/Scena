"""The level's sheets as Scena ``Sheet`` catalogs: one per file and cut.

Built through ``Sheet`` itself, so the editor cuts, names and sizes frames as
the game will (a layout ``Sheet`` refuses is refused here with its message).
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from scena import Sheet
from scena.level_format import sheet_call

from . import _engine
from .doc import sheet_layout

_CACHE: Dict[tuple, Sheet] = {}
_FRAMES: Dict[tuple, list] = {}


def sheet_for(entry: Dict[str, Any]) -> Sheet:
    """The ``Sheet`` for a sheet entry (absolute paths). Raises ``Sheet``'s
    ``ValueError`` / ``TypeError`` for a cut it refuses."""
    key = sheet_layout(entry)
    sheet = _CACHE.get(key)
    if sheet is None:
        args, kwargs = sheet_call(entry)
        sheet = _CACHE[key] = Sheet(*args, **kwargs)
    return sheet


def frames(entry: Dict[str, Any]) -> List[Tuple[tuple, tuple, str]]:
    """``((x, y, w, h), (src_w, src_h), name)`` per frame (see ``_engine.sheet_frames``)."""
    key = sheet_layout(entry)
    out = _FRAMES.get(key)
    if out is None:
        out = _FRAMES[key] = _engine.sheet_frames(sheet_for(entry))
    return out


def frame_key(entry: Dict[str, Any], index: int) -> Any:
    """What the file writes for frame ``index``: the name on an atlas (stable
    when the atlas is repacked), the index on a grid."""
    return frames(entry)[index][2] if entry.get("atlas") else index


def frame_size(entry: Dict[str, Any], frame: Any) -> Tuple[float, float]:
    """The untrimmed pixel size of ``frame`` (an index or a name)."""
    index = sheet_for(entry).frame_index(frame)
    return tuple(float(v) for v in frames(entry)[index][1])


def forget() -> None:
    """Drop the cached catalogs (the art may have changed on disk)."""
    _CACHE.clear()
    _FRAMES.clear()
