"""GC policy for the run loop: freeze the built world so play has no long GC pauses.

A full cyclic-GC pass walks every tracked object. Right after ``setup()`` (or a
scene build) that is the whole world: 8–10 ms on the dev Mac, 37–54 ms on a
Windows office laptop, on CPython 3.12 and 3.14.5+ alike (3.14.5 rolled the
incremental GC back). ``gc.freeze()`` moves everything alive into the
permanent generation, so later passes walk only what play created (~1 ms).

Freeze points (Scena Design, "Frame pacing and GC"):

* ``freeze_world()`` — end of ``_begin_game`` (setup + HUD + first scene).
* ``request_freeze()`` — an act change; ``run_pending_freeze()`` runs it at
  the end of ``_simulate_frame``, when no handler stack holds the old act.
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
# An act change asked for a collect + freeze; the frame boundary runs it.
_pending = False


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
    global _frozen, _pending
    _pending = False
    if not _enabled:
        return False
    gc.collect()
    gc.freeze()
    _frozen = True
    return True


def request_freeze() -> None:
    """Freeze at the next frame boundary (``run_pending_freeze``).

    An act change can run inside a handler (a collision step, a timer, a
    cover ``on_done``) whose stack still holds the old act's objects: a
    collect there would freeze them until the next change (review 2026-10-09
    S4-7). The end of the frame holds nothing of the old act.
    """
    global _pending
    if _enabled:
        _pending = True


def freeze_pending() -> bool:
    return _pending


def run_pending_freeze() -> bool:
    """The frame boundary: run a requested collect + freeze. True if it froze."""
    if not _pending:
        return False
    return freeze_world()


def thaw_world() -> bool:
    """Undo ``freeze_world`` (no collect). Returns True if the heap was frozen,
    or a freeze was pending (two changes in one frame refreeze once).

    The caller decides when to collect: a scene change collects once, after
    the new scene is built (``request_freeze``), so the old scene's garbage and
    the build garbage go in one pass.
    """
    global _frozen, _pending
    was = _frozen or _pending
    _pending = False
    if _frozen:
        gc.unfreeze()
        _frozen = False
    return was
