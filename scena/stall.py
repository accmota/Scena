"""Stall watch: name the author line when a frame (or the top level) never ends.

A ``while`` inside ``update`` (``while not keyp("SPACE"): pass``, a Scratch
"forever" written as Python) froze the window with no message: input and the
screen change only between frames, and the sync line watchdog is off by
default (``process.SYNC_WATCHDOG_ENABLED``: it costs 10–15 % of every frame).
Persona probes PP. This watch costs one clock read a frame: the frame body
stamps its start (``frame_begin``) and clears it (``frame_end``); a daemon
thread wakes every ``POLL_S`` and, when a frame has run past ``STALL_S`` (or
the top level past ``TOP_LEVEL_STALL_S`` without reaching ``run()``), prints
one SCENA ERROR to stderr naming the author line the main thread is on and
the fix. It never stops the game (Ctrl+C does); a frame under a debugger
(``f_trace`` set: pdb) is not a stall.

Armed by ``init()`` or ``run()`` called from the script itself (``__main__``;
a script with no ``init()`` gets the frame watch from ``run()``, RA B1), so a
test suite's ``init()`` starts nothing; ``arm()`` starts it by hand (tests).

Also here: a script run as ``python jogo.py`` that ends without ``run()``
(no window, no message: persona probes PP) is told so at exit
(``note_script_import``, from ``import scena``).
"""
from __future__ import annotations

import os
import sys
import threading
import time
from typing import List, Optional

STALL_S = 2.0               # a frame this long is stuck, not slow
TOP_LEVEL_STALL_S = 8.0     # loading art at the top level may take a while
POLL_S = 0.25

_ENGINE = os.path.dirname(os.path.abspath(__file__)) + os.sep
_STDLIB = os.path.dirname(os.__file__) + os.sep

# [phase, started_at, reported]: phase "top" (init → run), "frame", None.
_state: List = [None, 0.0, False]
_thread: Optional[threading.Thread] = None
# Engine work the main thread is inside (``busy``): [what, started_at, noted].
_busy: List[list] = []
_MAIN = threading.main_thread().ident


class busy:
    """``with stall.busy("baking a sound"):`` around engine work that may take
    seconds. A stall inside it is the engine's, not a loop of the author's:
    the watch prints a note naming the work and the author's call (once), and
    the time it took does not count toward the phase's stall. A cold
    top-level ``Sound.bake`` with Reverb on a slower machine got the loop
    error, "a game needs no loop of its own" (WP32)."""

    __slots__ = ("what",)

    def __init__(self, what: str):
        self.what = what

    def __enter__(self):
        if threading.get_ident() == _MAIN:
            _busy.append([self.what, time.perf_counter(), False])
        return self

    def __exit__(self, *exc):
        if threading.get_ident() == _MAIN and _busy:
            since = _busy.pop()[1]
            if not _busy and _state[0] is not None and _state[1] <= since:
                _state[1] += time.perf_counter() - since
        return False


def frame_begin() -> None:
    _state[0] = "frame"
    _state[1] = time.perf_counter()
    _state[2] = False


def frame_end() -> None:
    _state[0] = None


def top_level_begin() -> None:
    if _state[0] is None:
        _state[0] = "top"
        _state[1] = time.perf_counter()
        _state[2] = False


def top_level_end() -> None:
    if _state[0] == "top":
        _state[0] = None


def arm() -> None:
    """Start the watch thread (once per process)."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _thread = threading.Thread(target=_watch, name="scena-stall-watch", daemon=True)
    _thread.start()


def _author_frames(frame) -> List[tuple]:
    out = []
    while frame is not None:
        f = os.path.abspath(frame.f_code.co_filename)
        if not f.startswith(_ENGINE) and not f.startswith(_STDLIB) \
                and "site-packages" not in f and not frame.f_code.co_filename.startswith("<"):
            out.append((frame.f_code.co_filename, frame.f_lineno, frame.f_code.co_name))
        frame = frame.f_back
    return out


def _debugged(frame) -> bool:
    while frame is not None:
        if frame.f_trace is not None:
            return True
        frame = frame.f_back
    return False


def _where(frame) -> str:
    import linecache
    where = _author_frames(frame)
    if not where:
        return "engine code (no line of yours is running)"
    path, line, fn = where[0]
    code = linecache.getline(path, line).strip()
    return f"{os.path.basename(path)}:{line} in {fn}" + (f": {code}" if code else "")


def busy_message(phase: str, what: str, seconds: float, frame) -> Optional[str]:
    """The SCENA NOTE for engine work past the stall limit, or None (under a
    debugger)."""
    if _debugged(frame):
        return None
    waits = "the game starts" if phase == "top" else "the window moves again"
    return (
        f"SCENA NOTE: {what} has taken {seconds:.0f} s so far, for {_where(frame)}. "
        f"This is the engine's work, not a loop: {waits} when it is done."
    )


def stall_message(phase: str, seconds: float, frame) -> Optional[str]:
    """The SCENA ERROR for a stall, or None (under a debugger)."""
    if _debugged(frame):
        return None
    at = _where(frame)
    if phase == "top":
        return (
            f"SCENA ERROR: the script has run for {seconds:.0f} s without reaching run(), "
            f"stuck at {at}. A game needs no loop of its own: put the per-frame code in "
            f"def update(dt): and end the file with run(). Ctrl+C stops it."
        )
    return (
        f"SCENA ERROR: a frame has not finished for {seconds:.0f} s, so the window is "
        f"frozen; the game is stuck at {at}. A loop inside update (or on_update, a "
        f"handler) runs within one frame, and keys, the mouse and the screen change "
        f"only between frames: use if instead of while, @when(lambda: …), or a task "
        f"(async def + await wait(…), run_task). Ctrl+C stops the game."
    )


def _watch() -> None:
    main = threading.main_thread().ident
    while True:
        time.sleep(POLL_S)
        _poll(main)


def _poll(main: int) -> None:
    """One look at the main thread. Its own function, so the frame it reads
    dies when it returns: a local of the endless loop in ``_watch`` kept the
    main thread's stack, and every value its locals held, alive after the
    report (WP20)."""
    phase, since, reported = _state
    if phase is None or reported:
        return
    limit = TOP_LEVEL_STALL_S if phase == "top" else STALL_S
    work = _busy[0] if _busy else None
    if work is not None:
        # Engine work (``busy``): its time is not the phase's; a note, once.
        what, started, noted = work
        waited = time.perf_counter() - started
        if noted or waited < limit:
            return
        frame = sys._current_frames().get(main)
        if frame is None or not _busy or _busy[0] is not work:
            return
        msg = busy_message(phase, what, waited, frame)
        work[2] = True
    else:
        waited = time.perf_counter() - since
        if waited < limit:
            return
        frame = sys._current_frames().get(main)
        if frame is None or _state[0] != phase or _state[1] != since:
            return
        msg = stall_message(phase, waited, frame)
        _state[2] = True
    if msg is not None:
        try:
            sys.stderr.write(msg + "\n")
            sys.stderr.flush()
        except Exception:
            pass


# ``run()`` was entered (orchestration.run); read at exit. ``_made_from``:
# the registry key past which an object is the author's (``import scena`` and
# ``init()`` make the engine's own: the view's Rect and Point).
_run_called = [False]
_made_from = [None]


def _next_key() -> Optional[int]:
    try:
        from .canvas import ScenaCanvas
        return ScenaCanvas.get_current().registry._next_key
    except Exception:
        return None


def mark_engine_objects() -> None:
    """Everything made so far is the engine's (``init()`` of a script)."""
    if _made_from[0] is not None:
        _made_from[0] = _next_key()


def run_called() -> None:
    _run_called[0] = True


def note_script_import() -> None:
    """``import scena`` from the script ``python`` runs (its ``__main__`` file
    is ``sys.argv[0]``): at exit, a script that built objects and never
    reached ``run()`` says so. A test, a harness or a REPL is not that."""
    main = sys.modules.get("__main__")
    path = getattr(main, "__file__", None)
    if not path or not sys.argv or not sys.argv[0]:
        return
    # The import itself must come from the script's own code (``from scena
    # import *`` in jogo.py), not from a test module a runner imported.
    frame = sys._getframe(1)
    while frame is not None and (frame.f_code.co_filename.startswith("<")
                                 or os.path.abspath(frame.f_code.co_filename).startswith(_ENGINE)):
        frame = frame.f_back
    if frame is None or frame.f_globals is not getattr(main, "__dict__", None):
        return
    try:
        full = os.path.abspath(path)
        if full != os.path.abspath(sys.argv[0]):
            return
    except Exception:
        return
    if full.startswith(_STDLIB) or "site-packages" in full or full.startswith(_ENGINE):
        return          # python -m unittest / pytest: a runner, not a game
    import atexit
    _made_from[0] = _next_key()
    atexit.register(_ended_without_run)


def ended_without_run_message() -> Optional[str]:
    """The exit message, or None: ``run()`` ran, the script crashed (its own
    traceback says enough), a harness replaced ``run``, or nothing was made."""
    if _run_called[0]:
        return None
    if getattr(sys, "last_exc", None) is not None or getattr(sys, "last_value", None) is not None:
        return None
    try:
        import scena
        from . import orchestration
        if getattr(scena, "run", None) is not orchestration.run:
            return None
        from .canvas import ScenaCanvas
        start = _made_from[0] or 0
        if not any(k > start for k in list(ScenaCanvas.get_current().registry.live.keys())):
            return None
    except Exception:
        return None
    return ("SCENA: the script ended without run(), so no window opened. "
            "Add run() as the last line of the file.")


def _ended_without_run() -> None:
    msg = ended_without_run_message()
    if msg is not None:
        try:
            sys.stderr.write(msg + "\n")
            sys.stderr.flush()
        except Exception:
            pass
