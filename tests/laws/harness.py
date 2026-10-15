"""Record a program (a laws fixture, a test program) and check it.

``record(program, frames, patches=...)`` runs the program in a
``ProgramRun`` with the recorder attached, optionally under engine plants
(``mock.patch.object`` triples, applied before the recorder installs, so a
planted function is the one hooked), and returns ``(run, events, report)``.
"""
from __future__ import annotations

from contextlib import ExitStack
from typing import Any, Dict, Optional, Sequence, Tuple
from unittest import mock

from laws import model
from laws.attach import attach
from program_support import ProgramRun


def drive(program: str, steps, *, params: Optional[Dict[str, Any]] = None,
          patches: Sequence[Tuple[Any, str, Any]] = (), areas=model.AREAS,
          keep_going: bool = False):
    """Record ``program`` under OS-level input (``game_harness.GameRun``:
    held keys, key repeats, a cursor placed with no motion). ``steps``: a
    list of ``(method, *args)`` on the run (``key_down``, ``key_up``,
    ``key_repeat``, ``press``, ``release``, ``move``) and ``("step", n)``.
    Returns ``(run, state, report)`` like ``record``."""
    from game_harness import GameRun
    state: Dict[str, Any] = {}
    with ExitStack() as stack:
        for target, attr, new in patches:
            stack.enter_context(mock.patch.object(target, attr, new))
        run = GameRun(program, params or {}, probes={})
        run.os_level = True
        run.error = None
        attach(run)
        run.start()
        try:
            try:
                for st in steps:
                    if st[0] == "step":
                        run.step(st[1])
                    else:
                        getattr(run, st[0])(*st[1:])
            except Exception as e:  # noqa: BLE001
                if not keep_going:
                    raise
                run.error = e
            st_cell = run.ns.get("st")
            state = {k: getattr(st_cell, k) for k in st_cell.keys()} if st_cell is not None else {}
        finally:
            run.close(strict=not patches)
    return run, state, model.check(run.laws.events, areas)


def record(program: str, frames: int, *, params: Optional[Dict[str, Any]] = None,
           patches: Sequence[Tuple[Any, str, Any]] = (), probes=None,
           areas=model.AREAS, keep_going: bool = False):
    """``keep_going``: an author error ends the run, the trace so far is kept
    (a canary's plant can trip the engine's own guards; ``run.error``)."""
    state: Dict[str, Any] = {}
    with ExitStack() as stack:
        for target, attr, new in patches:
            stack.enter_context(mock.patch.object(target, attr, new))
        run = ProgramRun(program, params or {}, probes=probes or {})
        run.error = None
        attach(run)
        run.start()
        try:
            try:
                run.step(frames)
            except Exception as e:  # noqa: BLE001
                if not keep_going:
                    raise
                run.error = e
            st = run.ns.get("st")
            state = {k: getattr(st, k) for k in st.keys()} if st is not None else {}
        finally:
            run.close(strict=not patches)
    events = run.laws.events
    return run, state, model.check(events, areas)
