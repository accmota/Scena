"""Attach the laws recorder to a ``ProgramRun`` (games and programs).

``before_start=attach`` (``game_harness.run_game``, ``program_oracles._run``)
or ``attach(run)`` before ``run.start()``. The recorder starts in the run's
prelude (after the world reset, right before the program's first line, so
the harness's own setup is not part of the trace) and stops when the run
closes; the recording is ``run.laws``.
"""
from __future__ import annotations

from typing import Any, Optional

from laws import trace


def attach(run: Any, recorder: Optional[trace.Recorder] = None, *, motion: bool = False) -> None:
    """``motion``: also record every resolve body's pose around each resolve
    (the motion laws, S6)."""
    rec = recorder if recorder is not None else trace.Recorder()
    rec.motion = motion or rec.motion
    run.laws = rec
    before = run.prelude

    def prelude(r):
        if before is not None:
            before(r)
        trace.install(rec)

    run.prelude = prelude
    close = run.close

    def closing(strict: bool = True) -> None:
        if trace.installed():
            trace.uninstall()
        close(strict=strict)

    run.close = closing
