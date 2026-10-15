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
