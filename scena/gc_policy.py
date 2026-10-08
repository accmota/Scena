"""GC policy for the run loop: freeze the built world so play has no long GC pauses.

A full cyclic-GC pass walks every tracked object. Right after ``setup()`` (or a
scene build) that is the whole world: 8–10 ms on the dev Mac, 37–54 ms on a
Windows office laptop, on CPython 3.12 and 3.14.5+ alike (3.14.5 rolled the
incremental GC back). ``gc.freeze()`` moves everything alive into the
permanent generation, so later passes walk only what play created (~1 ms).

Freeze points (Scena Design, "Frame pacing and GC"):

* ``freeze_world()`` — end of ``_begin_game`` (setup + HUD + first scene), and
  after every scene build.
* ``thaw_world()`` — start of a scene change and ``run()`` cleanup.

Cost: Scena objects sit in reference cycles, so a frozen object that is
destroyed during play is only reclaimed at the next thaw (scene change or
exit). That memory was already in use at the freeze, so it is bounded by the
built world; it never grows. The collect happens at a scene change, where a
pause is not seen as jitter.

``set_gc_freeze(False)`` turns the policy off (headless tests do: a frozen
heap would hide a real leak from the census). Same style as
``state.set_graph_gc_backstop``.
"""
from __future__ import annotations

import gc

_enabled = True
# True while the heap holds objects this module froze (and has not thawed).
_frozen = False


def set_gc_freeze(enabled: bool) -> None:
    """Debug / test escape hatch: turn the freeze-after-build policy on or off.

    Turning it off does not thaw a heap that is already frozen; the next
    ``thaw_world`` still does.
    """
    global _enabled
    _enabled = bool(enabled)


def gc_freeze_enabled() -> bool:
    return _enabled


def world_frozen() -> bool:
    """True while objects frozen by ``freeze_world`` are still frozen."""
    return _frozen


def freeze_world() -> bool:
    """Collect, then freeze everything alive. Returns True if it froze."""
    global _frozen
    if not _enabled:
        return False
    gc.collect()
    gc.freeze()
    _frozen = True
    return True


def thaw_world() -> bool:
    """Undo ``freeze_world`` (no collect). Returns True if the heap was frozen.

    The caller decides when to collect: a scene change collects once, after
    the new scene is built (``freeze_world``), so the old scene's garbage and
    the build garbage go in one pass.
    """
    global _frozen
    if not _frozen:
        return False
    gc.unfreeze()
    _frozen = False
    return True
