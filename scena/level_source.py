"""Graph nodes for audio levels: ``@= lambda: mic.level`` / ``audio.level`` / ``h.level``.

A level is written by an audio thread (the capture callback, the mixer), which
must never touch the reactive graph. A ``LevelSource`` is the main-thread
stand-in: a formula that reads a microphone, the ``audio`` bus or a sound
``Handle`` depends on it (``state._extract_sources`` asks the object through
``_formula_source``), and the frame body's audio sample (``sample_level_sources``,
frame step 1, after the pointer sample) dirties it when the reader published
new data since the last frame. Nothing is created or sampled until a formula
links a level, so a game without one pays one empty-list check per frame.
Sound Design, "Analysis".
"""
from __future__ import annotations

import weakref

from .state import Container, get_scena_system

# Sources a formula has linked, sampled once per frame. Mutated in place, never
# rebound: the run loop holds this list by name.
LEVEL_SOURCES: list = []


class LevelSource(Container):
    """One reader's graph node. ``stamp`` is a cheap "did it publish?" token."""

    def __init__(self, owner_ref, stamp) -> None:
        super().__init__()
        self.__dict__["_reader"] = owner_ref      # weakref to the mic / bus
        self.__dict__["_stamp_fn"] = stamp        # reader -> hashable token
        self.__dict__["_stamp"] = None

    def _update_impl(self) -> None:
        pass

    def _takein_impl(self, new_value):
        raise TypeError("an audio level is read-only; read .level / .spectrum()")


def level_source_for(reader, stamp) -> LevelSource:
    """The reader's ``LevelSource`` on the current graph; register it for sampling.

    Kept on the reader (``_level_source``). A graph reset (``init_scena_system``)
    leaves the old node behind: a new one is made on the new graph.
    """
    ss = get_scena_system()
    src = reader.__dict__.get("_level_source")
    if src is not None and src._scena_system is ss:
        if not any(s is src for s in LEVEL_SOURCES):   # after reset_level_sources()
            LEVEL_SOURCES.append(src)
        return src
    if src is not None:
        LEVEL_SOURCES[:] = [s for s in LEVEL_SOURCES if s is not src]
    src = LevelSource(weakref.ref(reader), stamp)
    src.__dict__["_stamp"] = stamp(reader)
    reader.__dict__["_level_source"] = src
    LEVEL_SOURCES.append(src)
    return src


def sample_level_sources() -> None:
    """Dirty every linked level whose reader published since the last frame."""
    ss = get_scena_system()
    dead = None
    for src in LEVEL_SOURCES:
        d = src.__dict__
        reader = d["_reader"]()
        if reader is None or src._scena_system is not ss:
            dead = dead or []
            dead.append(src)
            continue
        stamp = d["_stamp_fn"](reader)
        if stamp != d["_stamp"]:
            d["_stamp"] = stamp
            src.update()
    if dead:
        LEVEL_SOURCES[:] = [s for s in LEVEL_SOURCES if not any(s is d for d in dead)]


def reset_level_sources() -> None:
    """Tests: forget every sampled source (a later link registers again)."""
    LEVEL_SOURCES.clear()
