"""The reference model: pure functions over a laws trace.

``check(events)`` runs every area's rules and returns a ``Report``:
findings (law, frame, message, signature), witnesses (how often each law's
precondition held) and abstentions (where the model does not judge).

A model never imports the engine function it checks: its truth is the law's
sentence in design/Laws.md. Areas: ``frame`` (F laws), ``lifetime`` (L laws).
"""
from __future__ import annotations

from laws.model.base import Report, Trace  # noqa: F401
from laws.model import collision, frame, input as input_, lifetime, timers

AREAS = (frame, lifetime, collision, input_, timers)


def check(events, areas=AREAS) -> Report:
    tr = Trace(events)
    rep = Report()
    for area in areas:
        area.check(tr, rep)
    return rep


def laws_checked(areas=AREAS):
    """Every law id some area checks (the constitution guard reads it)."""
    out = set()
    for area in areas:
        out.update(area.LAWS)
    return out
