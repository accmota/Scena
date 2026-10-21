"""Process system: after / every / ready / tween / then= / async await / handles.

Cooperative scheduler driven by ``clock.dt``. Not ``asyncio``. Handles are
the only awaitables; ``wait`` / ``until`` / ``until_empty`` / ``parallel`` /
``race`` return the same ``Handle`` type as ``after``. They only run inside a
coroutine the engine is driving (an async mode, or a helper that mode
``await``s). Work started inside a mode body is mode-scoped (dies on leave);
``e.after`` / ``e.every`` / ``e.tween`` are entity-scoped. ``@on_mode`` tags a
mode body; ``@exit_mode`` registers optional non-Handle cleanup when that
mode is left.
"""

from __future__ import annotations

import functools
import types
import builtins
import inspect
import math
import os
import sys
import time
import traceback
import warnings
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Union
from weakref import WeakSet, ref

from .easing import Ease, TWEEN_EASES, resolve_ease
from types import CoroutineType as _CoroutineType

from .validate import (
    NO_FN, refuse_called_function,
    HINT_SCALE, clamp_magnitude, is_async_callable, magnitude, fixed_magnitude,
    payload_arity, refuse_async, refuse_coroutine_result, seconds,
)
from .closed import ClosedSurface

# Seconds in a mode with nothing pending before a frozen-mode warning.
FROZEN_MODE_S = 2.0
# Wall-clock budget for one async resume (``coro.send``) without an ``await``.
# Tuned for slow classroom Windows boxes: big Sprite waves must finish under this.
WATCHDOG_RESUME_S = 0.5
# Author LINE events between wall-clock checks (keeps the callback cheap).
WATCHDOG_CHECK_EVERY = 256
# Default on — beginners need the freeze guard. Prefer ``set_watchdog(False)``.
WATCHDOG_ENABLED = True
# Sync hooks (``update(dt)``, ``on_update`` fleet) skip LINE instrumentation by
# default — arming ``sys.monitoring`` every frame costs ~12–17%% on hot apps.
# Async mode resume stays guarded. Opt in with ``set_sync_watchdog(True)``.
SYNC_WATCHDOG_ENABLED = False
# ``every()`` creations from one owner + call site in one second before a flood warning.
# Named slots (``name=``) are not counted.
EVERY_FLOOD_PER_SEC = 40

# Package directory (…/<repo>/scena). Author scripts/tests live outside this tree.
_SCENA_PKG_ROOT = os.path.dirname(os.path.abspath(__file__))
_SCENA_FILE_CACHE: Dict[str, bool] = {}

# Last author notice for the on-canvas SCENA WARNING banner. Author errors
# are not recorded here: they propagate (raise-loud).
_AuthorError = Tuple[str, str, str, float, int, str]  # where, owner, message, time, count, severity
_last_author_error: Optional[_AuthorError] = None
_author_error_key: Optional[Tuple[str, int, type, str]] = None
_author_error_warned_at: float = 0.0


from .purity_check import _READING as _SOLVER_READING, refuse_if_solver_reading



# Time is summed frame by frame, so a deadline that is a whole number of
# frames lands a hair short (15 * (1/60) = 0.24999999999999997 < 0.25) or long
# (54 * (1/60) > 0.9) by rounding alone. Every "is it due" comparison on summed
# time goes through ``reached``: within 1e-9 (relative) counts as there. Far
# below any frame step, so it never merges two frames (bug PM8).
_DUE_EPS = 1e-9


def reached(elapsed: float, target: float) -> bool:
    """``elapsed >= target``, forgiving float rounding of a sum of frame steps."""
    return elapsed >= target - _DUE_EPS * (abs(target) if abs(target) > 1.0 else 1.0)


def _every_fire_budget(interval: float) -> int:
    """Most ``every`` fires one tick may make: what one capped world step owes."""
    from .input import MAX_FRAME_DT
    return max(1, int(math.ceil(MAX_FRAME_DT / interval - _DUE_EPS)))


def whole_steps(elapsed: float, rate: float) -> int:
    """Whole steps of ``1 / rate`` in summed ``elapsed`` — a clip's frame count.

    ``int(elapsed * rate)`` is one short on the frame a step is due (PM8; the
    clip playhead showed each frame one game frame late, graphics review PB3).
    The same tolerance as ``reached``."""
    x = elapsed * rate
    n = int(x)
    if x >= n + 1 - _DUE_EPS * (n + 1 if n + 1 > 1 else 1):
        n += 1
    return n

def last_author_error() -> Optional[Dict[str, Any]]:
    """Return the latest SCENA WARNING for the canvas banner, or ``None``."""
    hit = _last_author_error
    if hit is None:
        return None
    where, owner_s, msg, t, count, severity = hit
    return {
        "where": where,
        "owner": owner_s,
        "message": msg,
        "time": t,
        "count": count,
        "severity": severity,
    }


def report_author_warning(where: str, message: str, owner=None) -> None:
    """Non-fatal SCENA WARNING for the on-canvas banner (missing/corrupt sound).

    A missing file is not a crash: the game keeps running and the banner
    says what is missing. Dismiss with Ctrl+Shift+E.
    """
    global _last_author_error, _author_error_key, _author_error_warned_at
    owner_s = repr(owner) if owner is not None else f"<{ownerless_scope()}>"
    msg = str(message)
    now = time.perf_counter()
    key = (where, id(owner) if owner is not None else 0, Warning, msg)
    count = 1
    if (
        _last_author_error is not None
        and _author_error_key == key
    ):
        count = int(_last_author_error[4]) + 1
    _last_author_error = (where, owner_s, msg, now, count, "warning")
    _author_error_key = key
    _author_error_warned_at = now
    body = f"SCENA WARNING: {where}: {msg}"
    if count > 1:
        body = f"{body} (×{count})"
    warnings.warn(body, RuntimeWarning, stacklevel=3)


def clear_author_error() -> None:
    """Dismiss the SCENA WARNING banner (framework shortcut / tests)."""
    global _last_author_error, _author_error_key, _author_error_warned_at
    _last_author_error = None
    _author_error_key = None
    _author_error_warned_at = 0.0


def _reset_author_errors() -> None:
    clear_author_error()

# ``sys.monitoring`` tool id 3 is unassigned (0=debugger, 1=coverage, 2=profiler, 5=optimizer).
_WATCHDOG_TOOL_ID = 3
_WATCHDOG_TOOL_NAME = "scena.watchdog"
_watchdog_tool_ready = False
_watchdog_resume_depth = 0
_wd_deadline = 0.0
_wd_author_lines = 0
_wd_check_every = 256
# The task walk holds the LINE / JUMP events on for all its resumes (one
# ``set_events`` pair per tick, not per resume): each ``set_events`` re-instruments
# every function on the stack (the tick, the run loop), which cost ~25 µs per
# resume. Between resumes the deadline is infinite, so author code the walk
# runs outside a resume (a ``finally`` thrown by a cancel) never trips.
_wd_window_open = False
_wd_window_prev = 0

# Scope on a handle. Mode-scoped work is cancelled on ``e.mode = …``.
# Ownerless work (a bare ``after`` / ``play_sound`` / ``tween`` with no actor)
# is ``"game"`` when made before the top level ends and ``"act"`` after it
# (Act Design, Decision 11): an act change cancels the ``"act"`` ones.
SCOPE_GAME = "game"
SCOPE_ACT = "act"
SCOPE_ENTITY = "entity"
SCOPE_MODE = "mode"

# Why a handle was cancelled (``Handle._cancel_reason``): named in the warning
# a task or an async mode gets when what it awaits is cancelled under it.
_R_OWNER_GONE = "its owner was destroyed"
_R_DEAD_AT_START = "it was scheduled on an actor that was already destroyed"
_R_TARGET_GONE = "the actor it moves was destroyed"
_R_UNTIL_GONE = "the actor its condition reads was destroyed"
_R_UNTIL_RAISED = "its condition raised"
_R_PREEMPTED = "another move or tween took the same property"
_R_NAME = "a new job took its name="
_R_MODE_LEFT = "its mode was left"
_R_PROCESS = "cancel_process() was called on its owner"
_R_ACT = "the act ended"
_R_RACE = "race() picked another member"
_R_MEMBER = "one of its members was cancelled"
_R_TASK = "the task that started it was cancelled"

# Set by ``ActManager._seal`` when the top level ends (``run()`` startup).
_top_level_ended = False


def _set_top_level_ended(value: bool) -> None:
    global _top_level_ended
    _top_level_ended = bool(value)


def ownerless_scope() -> str:
    """``"game"`` before the top level ends, ``"act"`` after (ownerless work)."""
    return SCOPE_ACT if _top_level_ended else SCOPE_GAME

# Kinds that accept Handle.pause() / resume(). until / parallel / race raise.
_PAUSABLE_KINDS = frozenset({"every", "after", "wait", "tween", "sound"})

_CALL_FOR_KIND = {
    "task": "run_task", "after": "after", "every": "every",
    "tween": "tween", "sound": "play_sound",
}


def _game_task_clash_message(old: "Handle", name: str, kind: str) -> str:
    call = _CALL_FOR_KIND.get(kind, kind)
    fn = getattr(old._fn, "__name__", None)
    what = f"{fn}()" if fn and fn != "<lambda>" else "a task"
    return (
        f"{call}(..., name={name!r}) in an act: the game task named {name!r} "
        f"({what}) is still running. An act's "
        f"timer with a game timer's name pauses the game's one until the act "
        f"changes, but a task cannot pause, so this would end the game's task "
        f"for good. Use another name in the act, or end the game's task first "
        f"(keep its Handle and call cancel() on it)."
    )


_owner_ctx: ContextVar[Optional[object]] = ContextVar(
    "scena_process_owner", default=None
)
_scope_ctx: ContextVar[Optional[str]] = ContextVar(
    "scena_process_scope", default=None
)


class Cancelled(BaseException):
    """Raised into a waiting async script when its handle is cancelled.

    A ``BaseException`` so ``except Exception`` cannot swallow it; ``finally``
    still runs. Waiting on a destroyed actor ends the script silently.
    """


class _Watchdog(BaseException):
    """Internal: async mode ran too long without an ``await``."""


def _is_entity(obj) -> bool:
    return getattr(obj, "_scena_is_entity", False) is True


def _clock():
    return getattr(builtins, "clock", None)


def _argcount(callback) -> Optional[int]:
    """Payload slots on ``callback``: ``validate.payload_arity`` (parameters
    with no default, a bound method's ``self`` not counted; ``None`` for
    ``*args`` — it gets everything offered)."""
    return payload_arity(callback)


def _invoke(callback: Optional[Callable], owner=None) -> None:
    """Call ``callback``, arity-truncated; optionally pass ``owner`` as first arg."""
    if callback is None:
        return
    n = _argcount(callback)
    extra: list = []
    if owner is not None and not hasattr(callback, "__self__"):
        extra = [owner]
    result = callback(*extra[:n])
    if result is not None and type(result) is _CoroutineType:
        refuse_coroutine_result(result, callback)


def _no_update() -> None:
    """The frame snapshot's stand-in for an ``on_update`` cleared mid-frame."""


def _invoke_update(callback: Callable, owner, dt: float) -> None:
    """Call ``on_update``: method ``(self, dt)`` or function ``(e, dt)``; arity-truncated."""
    n = _argcount(callback)
    if n is not None and n <= 0:
        callback()
        return
    if hasattr(callback, "__self__"):
        callback(dt)
        return
    if n == 1:
        callback(owner)
    else:
        callback(owner, dt)


# ``on_update`` call forms, decided once per dense entry by the same rule as
# ``_invoke_update``: ``fn()``, ``fn(dt)`` (bound method), ``fn(owner)``,
# ``fn(owner, dt)``.
_CALL_NONE, _CALL_DT, _CALL_OWNER, _CALL_OWNER_DT = 0, 1, 2, 3


def _update_call_form(callback: Callable) -> int:
    """The payload ``_invoke_update`` would pass ``callback``, cached with
    the entry: a function's signature is taken as fixed once registered (a
    reassigned ``__code__`` / ``__defaults__``, or a slotted callable whose
    class ``__call__`` is swapped, keeps the old form; ``payload_arity``
    caches the same way)."""
    n = _argcount(callback)
    if n is not None and n <= 0:
        return _CALL_NONE
    if hasattr(callback, "__self__"):
        return _CALL_DT
    if n == 1:
        return _CALL_OWNER
    return _CALL_OWNER_DT


def _call_update(callback: Callable, form: int, owner, dt: float) -> None:
    if form == _CALL_DT:
        callback(dt)
    elif form == _CALL_OWNER_DT:
        callback(owner, dt)
    elif form == _CALL_NONE:
        callback()
    else:
        callback(owner)


def _spawn_coro(fn, owner):
    """Call an async callable the same way ``_invoke`` would; return the coroutine."""
    n = _argcount(fn)
    extra: list = []
    if owner is not None and not hasattr(fn, "__self__"):
        extra = [owner]
    result = fn(*extra[:n])
    if not inspect.iscoroutine(result):
        raise TypeError(
            f"async mode {getattr(fn, '__name__', fn)!r} did not return a coroutine"
        )
    return result


def _call_site(depth: int = 1) -> Tuple[str, int]:
    try:
        frame = sys._getframe(depth + 1)
        return frame.f_code.co_filename, int(frame.f_lineno)
    except (AttributeError, ValueError):
        return ("<unknown>", 0)


def _callable_or_none_error(value, what: str) -> None:
    if value is None:
        raise TypeError(
            f"{what} expected a function, got None. "
            f"If you wrote diving(), drop the ()."
        )
    if not callable(value):
        raise TypeError(
            f"{what} expected a function, got {type(value).__name__}."
        )


_is_async_callable = is_async_callable


def _in_executing_class_body(depth: int = 2) -> bool:
    """True when the frame at ``depth`` is a class body (PEP 3115 namespace).

    Default ``depth=2``: caller of our caller (decorator → class body).
    ``_claim_decorator_role`` uses ``depth=3`` (claim → decorator → class body).

    Conservative: ``False`` on any doubt so module-level ``@every`` / ``@when``
    still arm immediately. Class bodies have ``__module__`` and ``__qualname__``
    in ``f_locals``; modules and functions do not.
    """
    try:
        frame = sys._getframe(depth)
    except ValueError:
        return False
    if frame.f_code.co_flags & inspect.CO_OPTIMIZED:
        # A function frame is never a class body. Do not touch its f_locals:
        # on CPython <= 3.12 that caches a snapshot dict on the frame, which
        # pins every local (e.g. the last ``shot`` decorated with
        # ``@collide(shot, wall)`` in a long-lived async mode) after ``del``.
        return False
    locs = frame.f_locals
    return isinstance(locs, dict) and "__module__" in locs and "__qualname__" in locs


# Actor hook names (mirror shapes._ACTOR_HOOK_NAMES + setup) — duplicated to
# avoid a process ↔ shapes import cycle when claiming decorator roles.
_ACTOR_HOOK_METHOD_NAMES = frozenset({
    "on_update",
    "on_click",
    "on_hover",
    "on_hover_exit",
    "on_drag_to",
    "on_drag_over",
    "on_drop_by",
    "on_collide",
    "on_collide_stay",
    "on_collide_exit",
    "on_destroy",
    "setup",
})

_ROLE_EXCLUSIVE = frozenset({"timer", "mode", "exit", "leave_playfield"})
_ROLE_COMPATIBLE = frozenset({"when", "on_change", "collide", "pointer"})
_ROLE_LABELS = {
    "timer": "@every / @after",
    "when": "@when",
    "on_change": "@on_change",
    "collide": "@collide / @collide_with",
    "pointer": "@click / @drag_to / @drag_over / @drop_by",
    "mode": "@on_mode",
    "exit": "@exit_mode",
    "leave_playfield": "@leave_playfield",
}


def _claim_decorator_role(func: Callable, role: str) -> None:
    """Record ``role`` on ``func`` or raise ``TypeError`` on conflict.

    Compatible roles (``when``, ``on_change``, ``collide``, ``pointer``) may
    stack with themselves only. Exclusive roles (``timer``, ``mode``, ``exit``,
    ``leave_playfield``) may appear once and never with any other Scena
    decorator role.

    In a class body, decorating a discovered actor hook name (``on_update``,
    ``setup``, …) is also a ``TypeError``.
    """
    if role not in _ROLE_LABELS:
        raise ValueError(f"unknown decorator role: {role!r}")
    if role != "mode":
        # Only a mode is driven as a script; every other role is called.
        refuse_async(func, what=_ROLE_LABELS[role])

    if _in_executing_class_body(3):
        name = getattr(func, "__name__", None)
        if name in _ACTOR_HOOK_METHOD_NAMES:
            raise TypeError(
                f"{_ROLE_LABELS[role]} cannot decorate {name!r} — that name "
                f"is already a discovered actor hook. Use a second method or "
                f"a shared helper."
            )

    roles = getattr(func, "_scena_roles", None)
    if roles is None:
        roles = set()
        try:
            func._scena_roles = roles
        except (AttributeError, TypeError):
            # Builtin / slotted callables: skip tracking (cannot decorate those).
            return

    label = _ROLE_LABELS[role]
    fn_name = getattr(func, "__name__", repr(func))

    if role in _ROLE_EXCLUSIVE:
        if roles:
            other = next(iter(roles))
            other_label = _ROLE_LABELS.get(other, other)
            if other == role:
                raise TypeError(
                    f"{fn_name!r} already has {label} — one timer/mode/exit "
                    f"per function. Use a second method or a shared helper."
                )
            raise TypeError(
                f"{fn_name!r} already has {other_label}; cannot also use "
                f"{label}. Use a second method or a shared helper."
            )
        roles.add(role)
        return

    # Compatible role: stack with self only.
    for other in roles:
        if other == role:
            continue
        other_label = _ROLE_LABELS.get(other, other)
        raise TypeError(
            f"{fn_name!r} already has {other_label}; cannot also use "
            f"{label}. Use a second method or a shared helper."
        )
    roles.add(role)


# The mode body ``Entity._enter_mode`` is entering right now (its function):
# a sync ``@on_mode`` body runs only then (``on_mode``).
_ENTERING_MODE: List[Any] = [None]


def on_mode(fn):
    """Tag ``fn`` as a mode body. No effect on ``e.mode = fn`` / ``then=fn`` /
    comparison; enables a modes inventory (debug overlay, transition graph)
    built from tagged callables.

    A sync body is entered only by the engine: ``self.mode = self.phase2()``
    ran the body as a helper (its timers outlived the mode) and set the mode
    to ``None``, silently (persona probes round 2, R2-9). A direct call now
    raises naming ``self.mode = self.phase2``. An async body needs no guard:
    calling it only makes a coroutine, which the mode setter refuses.
    """
    if not callable(fn):
        raise TypeError(
            f"@on_mode decorates a function, got {type(fn).__name__} {fn!r}. "
            f"Write @on_mode above `def walking(self): …` (no parentheses)."
        )
    _claim_decorator_role(fn, "mode")
    fn._is_mode = True
    if _is_async_callable(fn) or not isinstance(fn, types.FunctionType):
        return fn
    n = _argcount(fn)
    name = fn.__name__

    @functools.wraps(fn)
    def mode_body(*args, **kwargs):
        if _ENTERING_MODE[0] is not mode_body:
            raise TypeError(
                f"{name}() is a mode (@on_mode): enter it with self.mode = "
                f"self.{name} (no parentheses). Called, it runs its body outside "
                f"the mode, and self.mode = None leaves the mode."
            )
        _ENTERING_MODE[0] = None
        return fn(*args[:n], **kwargs) if n is not None else fn(*args, **kwargs)

    mode_body._is_mode = True
    mode_body._scena_roles = getattr(fn, "_scena_roles", None)
    return mode_body


def exit_mode(enter_fn):
    """Register the decorated function to run when ``enter_fn``'s mode is
    left — cancellation still happens first; this runs right after, before
    the next mode's body. Attaches to ``enter_fn`` directly (no registry),
    the same way ``@every`` attaches its live handle as ``fn.handle``.

    Use for non-Handle cleanup (looks / ink). Mode-scoped timers and
    motion cancel automatically — no need to cancel them here.
    """
    if not callable(enter_fn):
        raise TypeError(
            f"@exit_mode(enter_fn) takes the mode function it cleans up after, got "
            f"{type(enter_fn).__name__} {enter_fn!r}. Write @exit_mode(walking) "
            f"above `def stop_walking(self): …`."
        )
    target = getattr(enter_fn, "__func__", enter_fn)

    def deco(exit_fn):
        if not callable(exit_fn):
            raise TypeError(
                f"@exit_mode(...) decorates a function, got {type(exit_fn).__name__}."
            )
        if _is_async_callable(exit_fn):
            raise TypeError(
                "exit_mode hooks must be a plain function, not async — "
                "use try/finally inside the async mode body for "
                "cancellation-time cleanup that must sit next to setup."
            )
        _claim_decorator_role(exit_fn, "exit")
        if getattr(target, "_exit_mode", None) is not None:
            warnings.warn(
                f"exit_mode(...) replaces an existing exit hook on "
                f"{target!r} — remove the duplicate @exit_mode if this "
                f"wasn't intentional.",
                stacklevel=2,
            )
        target._exit_mode = exit_fn
        return exit_fn

    return deco


def _fn_and_then(fn, then, *, call_name: str, on_done=None):
    """Validate completion channels. Returns ``(callback, then)``.

    ``fn`` and ``on_done=`` are the same call-channel (not both). Either call-channel
    xor ``then=`` (mode hop). Collapse: ``callback = fn if fn is not None else on_done``.
    """
    if fn is not None and on_done is not None:
        raise TypeError(
            f"Use fn or on_done= to call (same channel), not both. ({call_name})"
        )
    callback = fn if fn is not None else on_done
    if callback is not None and then is not None:
        raise TypeError(
            f"Use fn / on_done= to call, or then= to change mode, not both. ({call_name})"
        )
    if then is not None:
        _callable_or_none_error(then, "then=")
    if callback is not None:
        _callable_or_none_error(callback, "on_done=" if on_done is not None else f"{call_name}()")
        # No async check here (``after`` is a hot call): ``_invoke`` refuses
        # an async callback when it fires, at no cost to the sync path.
    return callback, then


# Default of the ``speed=`` argument below for the verbs that have no
# ``speed=`` (scale, zoom, ``tween``): their messages keep saying ``time=``.
_NO_SPEED = object()


def _timing_words(speed) -> str:
    """``time=`` or, on a verb that also takes ``speed=``, ``time= or speed=``."""
    return "time=" if speed is _NO_SPEED else "time= or speed="


def _require_timed_completion(*, time, then, on_done, call_name: str, ease="linear",
                              speed=_NO_SPEED) -> None:
    """``then=`` / ``on_done=`` / ``ease=`` only make sense with ``time=``
    (or ``speed=``, which becomes a ``time=``): an instant verb took ``ease=``
    and ignored it (graphics review E18)."""
    if time is not None or (speed is not None and speed is not _NO_SPEED):
        return
    words = _timing_words(speed)
    if then is not None or on_done is not None:
        raise TypeError(
            f"{call_name} then= / on_done= require {words}. "
            f"Omit them for an instant call, or pass {words} to tween."
        )
    if ease != "linear":
        raise TypeError(
            f"{call_name} ease= requires {words}: an instant call has no curve. "
            f"Omit ease=, or pass {words} to tween."
        )


def _require_loop_kwargs(*, loops, yoyo, time, call_name: str, speed=_NO_SPEED) -> int:
    """Validate ``loops=`` / ``yoyo=``; return the parsed loop count (``-1`` = forever).

    ``loops`` / ``yoyo`` require ``time=`` (or ``speed=``). ``yoyo=True`` needs
    ``loops`` > 1 (or ``\"forever\"``) — there is nothing to bounce against on
    a single lap.
    """
    from .track import _parse_loops

    from .validate import expect_bool
    yoyo = expect_bool(yoyo, f"{call_name} yoyo")      # "no" is truthy
    default_loops = loops is None or loops == 1
    if time is None and (speed is None or speed is _NO_SPEED):
        if not default_loops or yoyo:
            words = _timing_words(speed)
            raise TypeError(
                f"{call_name} loops= / yoyo= require {words}. "
                f"Omit them for an instant call, or pass {words} to tween."
            )
        return 1
    n_loops = _parse_loops(1 if loops is None else loops)
    if yoyo and n_loops == 1:
        raise ValueError(
            f"{call_name} yoyo=True needs loops > 1 (or loops=\"forever\"); "
            f"got loops=1 — nothing to bounce against."
        )
    return n_loops


def _check_speed(time, speed, call_name: str) -> Optional[float]:
    """The ``speed=`` of a timed verb, checked at the call: ``None`` when the
    author wrote ``time=``, else a positive finite number (units, or degrees
    on a turn, per second). ``time=`` and ``speed=`` together raise: they
    are two ways to say the same duration."""
    if speed is None:
        return None
    if time is not None:
        raise TypeError(
            f"{call_name} got both time= and speed=. Pass one: time= sets the "
            f"duration, speed= sets the rate and the duration follows from the distance."
        )
    from .validate import fixed_magnitude
    return float(fixed_magnitude(
        speed, f"{call_name} speed=", positive=True,
        hint="speed= is a rate per second (> 0); the target sets the direction",
    ))


def _speed_duration(speed: float, distance: float) -> float:
    """Seconds to cover ``distance`` at ``speed`` (a zero distance is 0 s)."""
    return abs(float(distance)) / speed


class Handle:
    """Running timed work. Safe to ignore, cancel twice, or hold after destroy.

    Awaitable: a finished handle completes immediately; a pending one yields
    until ``done``. Cancellation raises ``Cancelled`` into the waiting script.
    """

    __slots__ = (
        "kind", "_owner", "scope", "_name", "delay", "interval",
        "_fn", "_then", "_on_done", "_elapsed", "_done", "_cancelled", "_alive",
        "_paused", "_held",
        "_owner_ref", "_target_ref",
        "_tween_write", "_tween_keys",
        "_claimed_targets", "_claim_kind", "_claim_label", "_claim_writes",
        "_result", "_must_await", "_awaited", "_site", "_await_hint",
        "_children", "_pred",
        "_loops", "_lap", "_ride", "_yoyo",
        "_motion_readout", "_last_dx", "_last_dy", "_last_dt",
        "_last_heading", "_last_u",
        "_voice_id", "_sound_volume", "_sound_pan", "_sound_pitch",
        "_sound_loops", "_clip_duration", "_sound_effects", "_sound_fade_out",
        "_record", "_end_held",
        "_task", "_task_parent", "_cancel_reason",
    )

    def __init__(self, *_args, **_kwargs) -> None:
        # Any arguments: the author error, not Python's "__init__() got an
        # unexpected keyword argument" (tests/test_process.py TestHandleConstruction).
        raise TypeError(
            "Handle is not built by hand: after(), every(), tween(), wait(), "
            "move_to(..., time=) and play_sound() each return one. "
            "Write h = after(2.0, fn), then h.cancel()."
        )

    @classmethod
    def _make(cls, **kwargs) -> "Handle":
        """Engine constructor (``Handle()`` is refused for authors)."""
        handle = object.__new__(cls)
        handle._init(**kwargs)
        return handle

    def _init(
        self,
        *,
        kind: str,
        delay: float = 0.0,
        interval: float = 0.0,
        fn: Optional[Callable] = None,
        then: Optional[Callable] = None,
        on_done: Optional[Callable] = None,
        owner=None,
        scope: str = SCOPE_ACT,
        name: Optional[str] = None,
        tween_write: Optional[Callable] = None,
        tween_key=None,
        tween_keys=None,
        must_await: bool = False,
        await_hint: Optional[str] = None,
        site: Optional[Tuple[str, int]] = None,
        children: Optional[Tuple["Handle", ...]] = None,
        pred: Optional[Callable] = None,
        loops: int = 1,
        yoyo: bool = False,
        ride=None,
        motion_readout: bool = False,
        target=None,
    ):
        self.kind = kind
        self.delay = float(delay)
        self.interval = float(interval)
        self._fn = fn
        self._then = then
        self._on_done = on_done
        self._owner = owner
        if owner is None and scope == SCOPE_ACT and not _top_level_ended:
            # One place decides game vs act for every ownerless start site.
            # An explicit GAME stays GAME: work a game task starts after the
            # top level ended is still game work (Actors Design — Tasks).
            scope = SCOPE_GAME
        self.scope = scope
        self._name = name
        self._elapsed = 0.0
        self._done = False
        self._cancelled = False
        self._paused = False
        # Pointer-hold gate (Shapes Design — persistent drivers): a hold on
        # the parts this job writes freezes it without touching ``_paused``,
        # which stays the author's pause()/resume() switch.
        self._held = False
        # A sound whose voice ended while its owner was parked: ``on_done``
        # waits for the resume (park promises no owned callbacks).
        self._end_held = False
        self._alive = True
        self._owner_ref = ref(owner) if owner is not None else None
        self._target_ref = ref(target) if target is not None else None
        self._tween_write = tween_write
        if tween_keys is not None:
            self._tween_keys = tuple(tween_keys)
        elif tween_key is not None:
            self._tween_keys = (tween_key,)
        else:
            self._tween_keys = ()
        self._claimed_targets: Tuple = ()
        self._claim_kind: Optional[str] = None
        # The call as written (``move_by(time=2, loops="forever")``) and how it
        # writes (``"pushes"`` / ``"sets"``) — for driver-conflict messages.
        self._claim_label: Optional[str] = None
        self._claim_writes: Optional[str] = None
        self._result = None
        self._must_await = bool(must_await)
        self._awaited = False
        self._site = site
        self._await_hint = await_hint
        self._children = children
        self._pred = pred
        self._loops = int(loops) if loops is not None else 1
        self._lap = 0
        self._yoyo = bool(yoyo)
        self._ride = ride
        self._motion_readout = bool(motion_readout)
        self._last_dx = 0.0
        self._last_dy = 0.0
        self._last_dt = 0.0
        self._last_heading = 0.0
        self._last_u = 0.0
        self._voice_id = None
        self._sound_volume = 1.0
        self._sound_pan = 0.0
        self._sound_pitch = 1.0
        self._sound_loops = int(loops) if loops is not None else 1
        self._clip_duration = 0.0
        self._sound_effects = None
        # The ``fade_out`` tween, while it is the voice's live fade (it ends
        # the sound, so the sound rings out when its owner ends).
        self._sound_fade_out = None
        self._record = None
        # kind "task": the coroutine driver (a mode's async body, Actors
        # Design — Tasks). None for every other kind.
        self._task = None
        self._task_parent = None
        # ``_cancel_reason`` stays unset until a cancel names one (read it
        # with getattr): one store less on every handle.

    @property
    def effects(self):
        """Live audio effect stack of a ``play_sound`` handle.

        ``h.effects.add(Echo())``; ``fx.remove()`` takes one off. Sound handles only.
        """
        self._require_sound("effects")
        if self._sound_effects is None:
            from .audio_effects import AudioEffectStack
            self._sound_effects = AudioEffectStack(handle=self)
        return self._sound_effects

    @property
    def done(self) -> bool:
        """True once the job finished on its own (timer fired, tween arrived, sound ended)."""
        return self._done

    @property
    def cancelled(self) -> bool:
        """True once ``cancel()`` stopped the job (or its owner was destroyed) before it finished."""
        return self._cancelled

    # ``owner`` / ``name`` are the scheduler's slot key ``(id(owner), name)``
    # (``_named``, ``_by_owner``) and are recomputed on ``_forget``: a write
    # after scheduling orphans the slot (a cancelled handle stays parked in
    # ``_named``) or detaches the job from its owner's destroy. Read-only.
    @property
    def owner(self):
        """Entity (or ``None``) whose destroy / mode change cancels this job."""
        return self._owner

    @owner.setter
    def owner(self, value) -> None:
        raise TypeError(
            "Handle.owner is read-only (destroying the owner stops this job; "
            "a sound that ends by itself finishes). "
            "To run the job on another object, schedule it there: "
            "other.after(2.0, fn), and cancel() this one."
        )

    @property
    def name(self) -> Optional[str]:
        """The ``name=`` slot this job occupies (``None`` if unnamed)."""
        return self._name

    @name.setter
    def name(self, value) -> None:
        raise TypeError(
            "Handle.name is read-only (the name= slot this job was scheduled "
            f"into). Schedule again with the new slot: after(2.0, fn, name={value!r}), "
            "and cancel() this one."
        )

    @property
    def paused(self) -> bool:
        """True only while this job is alive and frozen via ``pause()``."""
        return self._paused and not self._done and not self._cancelled

    @paused.setter
    def paused(self, _value) -> None:
        raise TypeError(
            "Handle.paused is read-only. Use pause() / resume() to freeze "
            "or thaw this job."
        )

    @property
    def elapsed(self) -> float:
        """World seconds this job has run (paused time does not count).

        A finite ``loops=`` verb counts from its start, every lap included;
        ``loops="forever"`` reads the current lap."""
        if self.kind == "tween" and self._loops > 1:
            return self._lap * self.delay + self._elapsed
        return self._elapsed

    @property
    def remaining(self) -> float:
        """World seconds left until this job finishes, or until the next ``every`` fire.

        Dual of ``elapsed``. ``after`` / ``wait`` / ``tween`` count down ``delay``;
        ``every`` counts down ``interval`` (resets after each fire). ``until`` /
        ``parallel`` / ``race`` / a task have no clock duration → 0. Done or
        cancelled → 0.
        """
        if self._done or self._cancelled:
            return 0.0
        if self.kind == "sound":
            try:
                from .audio_mixer import get_mixer
                rem = get_mixer().snapshot().voice_remaining.get(self._voice_id)
            except Exception:
                rem = None
            if rem is not None and rem != float("inf"):
                return max(0.0, float(rem))
            dur = float(self._clip_duration or 0.0)
            pitch = float(self._sound_pitch or 1.0) or 1.0
            if dur <= 0.0:
                return 0.0
            lap = dur / pitch
            if self._sound_loops < 0:
                elapsed = self._elapsed % lap if lap > 0.0 else 0.0
                return max(0.0, lap - elapsed)
            return max(0.0, dur * max(self._sound_loops, 1) / pitch - self._elapsed)
        duration = self.interval if self.kind == "every" else self.delay
        if self.kind == "tween" and self._loops > 1:
            # Until the run ends, not the lap (review 2026-10-09 W-T4).
            left = self._loops * self.delay - (self._lap * self.delay + self._elapsed)
            return 0.0 if left <= 0.0 else left
        if self.kind == "tween" and self._loops < 0:
            duration = self.delay  # remaining in the current lap
        left = duration - self._elapsed
        return 0.0 if left <= 0.0 else left

    @remaining.setter
    def remaining(self, _value) -> None:
        raise TypeError(
            "Handle.remaining is read-only (seconds left on this job). "
            "To restart the countdown, schedule again with the same name=: "
            "after(2.0, fn, name='tail'). To stop it, call cancel()."
        )

    def _require_motion_readout(self, name: str) -> None:
        if self._motion_readout:
            return
        raise AttributeError(
            f"Handle.{name} is on move_along / timed move_to / move_by handles, "
            f"not on {self.kind!r}"
        )

    def _require_ride(self, name: str) -> None:
        if self._ride is not None:
            return
        raise AttributeError(
            f"Handle.{name} is on move_along handles, not on {self.kind!r}"
        )

    @property
    def velocity(self):
        """World DU/s applied by this motion tween this tick. Never writes Graphic.vel."""
        self._require_motion_readout("velocity")
        from .scenamath import Vec2
        dt = self._last_dt
        if dt <= 0.0:
            return Vec2.temp(0.0, 0.0)
        return Vec2.temp(self._last_dx / dt, self._last_dy / dt)

    @velocity.setter
    def velocity(self, _value) -> None:
        raise TypeError(
            "Handle.velocity is read-only (DU/s this tick). "
            "Copy it if you want physics, e.g. into a crate let go of the "
            "platform: caixa.vel = h.velocity (a body standing on it needs "
            "nothing: resolve() carries it). "
            "Motion tweens never write Graphic.vel."
        )

    @property
    def speed(self) -> float:
        """|velocity| in DU/s this tick."""
        self._require_motion_readout("speed")
        dt = self._last_dt
        if dt <= 0.0:
            return 0.0
        return math.hypot(self._last_dx, self._last_dy) / dt

    @speed.setter
    def speed(self, _value) -> None:
        raise TypeError(
            "Handle.speed is read-only. Copy into author state if you need a number to keep."
        )

    @property
    def heading(self) -> float:
        """Degrees, Scena CCW-from-+x (same convention as angle / face=)."""
        self._require_motion_readout("heading")
        ride = self._ride
        if ride is not None:
            if self._elapsed == 0.0 and not self._done and not self._cancelled:
                return 0.0
            ang = float(ride.world_angle(self._last_u))
            reverse = (ride.span1 - ride.span0) < 0.0
            if self._yoyo and (self._lap % 2) == 1:
                reverse = not reverse
            if reverse:
                ang = (ang + 180.0) % 360.0
            self._last_heading = ang
            return ang
        hypot = math.hypot(self._last_dx, self._last_dy)
        if hypot > 1e-9:
            self._last_heading = math.degrees(math.atan2(self._last_dy, self._last_dx))
        return self._last_heading

    @heading.setter
    def heading(self, _value) -> None:
        raise TypeError(
            "Handle.heading is read-only. Use face=True on move_along / "
            "move_to / move_by to write Graphic.angle."
        )

    @property
    def u(self) -> float:
        """Current track parameter after span/phase map (move_along only)."""
        self._require_ride("u")
        return self._last_u

    @u.setter
    def u(self, _value) -> None:
        raise TypeError(
            "Handle.u is read-only (track parameter after span/phase). "
            "Pass span= / phase= on move_along to choose the trip."
        )

    @property
    def lap(self) -> int:
        """0-based lap index (move_along only; forever loops keep counting)."""
        self._require_ride("lap")
        return self._lap

    @lap.setter
    def lap(self, _value) -> None:
        raise TypeError(
            "Handle.lap is read-only (0-based lap index). "
            "Pass loops= on move_along to choose how many laps to ride."
        )

    def _require_sound(self, name: str) -> None:
        if self.kind == "sound":
            return
        raise AttributeError(
            f"Handle.{name} is on play_sound handles, not on {self.kind!r}. "
            "Use play_sound(...) to get a sound handle."
        )

    def _linked_sound_fade(self):
        """In-flight ``fade_to`` / ``fade_out`` tween for this sound, if any."""
        if self.kind != "sound":
            return None
        fade = get_scheduler()._tweens.get(("sound-fade", id(self)))
        if fade is None or fade is self or fade._cancelled or fade._done:
            return None
        return fade

    @property
    def volume(self) -> float:
        """Sound volume (>= 0; 1 = as recorded). Writable while the sound plays."""
        self._require_sound("volume")
        return float(self._sound_volume)

    @volume.setter
    def volume(self, value) -> None:
        self._require_sound("volume")
        from .audio_mixer import get_mixer, require_finite
        self._sound_volume = require_finite("volume", value, non_negative=True)
        if self._voice_id is not None:
            get_mixer().set_volume(self._voice_id, self._sound_volume)

    @property
    def pan(self) -> float:
        """Stereo position, −1 (left) … 1 (right). Writable while the sound plays."""
        self._require_sound("pan")
        return float(self._sound_pan)

    @pan.setter
    def pan(self, value) -> None:
        self._require_sound("pan")
        from .audio_mixer import get_mixer, require_finite
        self._sound_pan = require_finite("pan", value)
        if self._voice_id is not None:
            get_mixer().set_pan(self._voice_id, self._sound_pan)

    @property
    def pitch(self) -> float:
        """Playback rate (1 = normal, 2 = an octave up and twice as fast). Writable."""
        self._require_sound("pitch")
        return float(self._sound_pitch)

    @pitch.setter
    def pitch(self, value) -> None:
        self._require_sound("pitch")
        from .audio_mixer import get_mixer, require_finite
        p = require_finite("pitch", value, positive=True)
        self._sound_pitch = p if p > 1e-12 else 1e-12
        if self._voice_id is not None:
            get_mixer().set_pitch(self._voice_id, self._sound_pitch)

    @property
    def level(self) -> float:
        """Current loudness of this voice, 0 … 1, smoothed over ``audio.level_tau`` seconds.

        Sound handles only. For a dB meter: ``amp_db(h.level)``. A formula
        that reads it (``@= lambda: h.level``) follows it, updated once per
        frame while anything plays.
        """
        self._require_sound("level")
        from .audio_mixer import get_mixer
        return float(get_mixer().snapshot().voice_levels.get(self._voice_id, 0.0))

    def _formula_source(self):
        """An ``@=`` reading a sound's ``level`` / ``spectrum`` depends on the mix.

        Every voice's analysis comes from the same mixer snapshot, so one graph
        node (the ``audio`` bus's) serves them all. Other handles have no level.
        """
        if self.kind != "sound":
            return None
        from .audio import audio
        return audio._formula_source()

    def spectrum(self, bins: int = 8) -> list:
        """Loudness per frequency band of this voice, low to high.

        Args:
            bins: how many bands (default 8).

        Returns:
            A list of ``bins`` numbers, 0 … 1.
        """
        self._require_sound("spectrum")
        from .audio import _resample_bins
        from .audio_mixer import get_mixer
        mixer = get_mixer()
        mixer.note_spectrum_interest()
        spec = mixer.snapshot().voice_spectra.get(self._voice_id)
        return _resample_bins(spec, bins)

    def fade_to(self, volume, time=0.3, ease="linear"):
        """Ramp this voice's volume over ``time`` seconds of world clock."""
        self._require_sound("fade_to")
        from .audio_mixer import require_finite
        start = float(self._sound_volume)
        end = require_finite("volume", volume, non_negative=True)
        duration = require_finite("time", time, non_negative=True)

        def write(u):
            self.volume = start + (end - start) * float(u)

        tw = _start_tween(
            duration=duration,
            ease=ease,
            write=write,
            tween_key=("sound-fade", id(self)),
            owner=self.owner,
            scope=self.scope,
        )
        if self._paused:
            tw.pause()
        return tw

    def fade_out(self, time=0.3, ease="linear"):
        """Ramp to silence and stop (natural end — ``on_done`` fires)."""
        self._require_sound("fade_out")
        from .audio_mixer import require_finite
        start = float(self._sound_volume)
        duration = require_finite("time", time, non_negative=True)

        def write(u):
            self.volume = start * (1.0 - float(u))

        def finish():
            if self._cancelled or self._done:
                return
            if self._voice_id is not None:
                from .audio_mixer import get_mixer
                get_mixer().finish_voice(self._voice_id)
            self._fire_once()

        tw = _start_tween(
            duration=duration,
            ease=ease,
            write=write,
            tween_key=("sound-fade", id(self)),
            on_done=finish,
            owner=self.owner,
            scope=self.scope,
        )
        self._sound_fade_out = tw
        if self._paused:
            tw.pause()
        return tw

    def _fading_out(self) -> bool:
        """True while this sound's live fade is a ``fade_out`` (it will end)."""
        fade = self._sound_fade_out
        return fade is not None and fade is self._linked_sound_fade()

    def pause(self) -> "Handle":
        """Freeze this job in place. Idempotent; returns ``self``.

        Clocked kinds only (``every`` / ``after`` / ``wait`` / ``tween`` /
        ``sound``). ``until`` / ``parallel`` / ``race`` raise ``TypeError``.
        No-op on a done or cancelled Handle.
        """
        if self.kind not in _PAUSABLE_KINDS:
            raise TypeError(
                f"Handle.pause() is for every / after / wait / tween / "
                f"play_sound, not on {self.kind!r}. Pause the member "
                f"Handles yourself for parallel / race."
            )
        if self._done or self._cancelled:
            return self
        if self._paused:
            return self
        self._paused = True
        if self._motion_readout:
            self._last_dt = 0.0
        if self.kind == "sound" and self._voice_id is not None:
            from .audio_mixer import get_mixer
            get_mixer().set_held(self._voice_id, True)
            fade = self._linked_sound_fade()
            if fade is not None:
                fade.pause()
        return self

    def resume(self) -> "Handle":
        """Thaw a paused job. Idempotent; returns ``self``.

        Does not revive a cancelled or finished Handle.
        """
        if self.kind not in _PAUSABLE_KINDS:
            raise TypeError(
                f"Handle.resume() is for every / after / wait / tween / "
                f"play_sound, not on {self.kind!r}."
            )
        if self._done or self._cancelled:
            return self
        if not self._paused:
            return self
        self._paused = False
        if self.kind == "sound" and self._voice_id is not None:
            from .audio_mixer import get_mixer
            get_mixer().set_held(self._voice_id, False)
            fade = self._linked_sound_fade()
            if fade is not None:
                fade.resume()
        return self

    def _cancel_for(self, reason: str) -> None:
        """:meth:`cancel`, recording why (the first reason wins)."""
        if getattr(self, "_cancel_reason", None) is None:
            self._cancel_reason = reason
        self.cancel()

    def cancel(self) -> None:
        """Stop the job now. ``then=`` / ``on_done=`` do not run.

        Safe to call twice, after the job finished, or after its owner was destroyed.
        A sound stops at once (an in-flight fade is dropped); a recording keeps
        the samples captured so far.
        """
        # A natural finish is not a cancel. Calling cancel() again is a no-op
        # and must not flip ``cancelled`` on a handle that already completed.
        if self._done or self._cancelled:
            return
        if self.kind == "sound":
            fade = self._linked_sound_fade()
            if fade is not None:
                fade.cancel()
            if self._voice_id is not None:
                from .audio_mixer import get_mixer
                get_mixer().cancel_voice(self._voice_id)
        elif self.kind == "record":
            # A cut keeps the samples captured so far and does not fire on_done.
            take = self._record
            if take is not None and not take.finalized:
                mic = take.mic
                if mic is not None:
                    mic._finish_take(take, natural=False)
        self._cancelled = True
        self._done = True
        self._paused = False
        self._held = False
        self._alive = False
        _release_process_driver(self)
        script = self._task
        kids = self._children
        if script is not None or type(kids) is dict:   # a task (its work, its body)
            if kids:
                # The work it started ends with it, before the body is thrown
                # (its ``finally`` sees that work gone, as on a mode's leave);
                # a sound that ends by itself rings out.
                self._children = None
                sched = get_scheduler()
                for child in tuple(kids):
                    child._task_parent = None
                    if not child._cancelled and not child._done:
                        if getattr(child, "_cancel_reason", None) is None:
                            child._cancel_reason = _R_TASK
                        sched._end_implicitly(child)
            if script is not None:
                # Throw Cancelled into the body (deferred while it is on the
                # stack, S2-11). Quiet when the owner is already dead.
                owner = self._owner
                script.cancel(silent=_is_entity(owner) and not getattr(owner, "is_alive", True))
                self._task = None      # no handle <-> script cycle left for the gc
                _clear_mode_task(owner, self)
        elif kids:
            for child in kids:
                if not child._cancelled:
                    child.cancel()
        get_scheduler()._forget(self)

    def _claimed_target_dead(self) -> bool:
        """True if the Entity this tween actually writes to was destroyed.

        Distinct from the *owner* check below: ``owner`` is who scheduled
        this work (a Director, the running mode's actor, or the act) —
        not necessarily who it writes to. A Director-owned
        ``wasp.move_to(..., time=...)`` kept ticking (and still fired
        ``on_done``) after ``wasp.destroy()``, because only the Director's
        liveness was checked, never the wasp's.

        Resolved from a weakref captured at tween-creation time
        (``_target_ref``), not by walking a claimed Container's ``_owner``
        at check time — ``destroy()`` clears that back-reference (to break
        the cycle for GC), so a walk done *after* destroy always comes up
        empty.
        """
        ref_fn = self._target_ref
        if ref_fn is None:
            return False
        target = ref_fn()
        return target is not None and _is_entity(target) and not target.is_alive

    def _live_owner(self):
        if self.owner is None:
            return None
        owner = self.owner
        if _is_entity(owner) and not owner.is_alive:
            return None
        return owner

    def _apply_then(self, owner) -> None:
        then = self._then
        if then is None or owner is None:
            return
        body = getattr(owner, "_mode_task", None)
        if body is not None and not body._done:
            warnings.warn(
                f"then= entered {getattr(then, '__name__', then)!r} and cancelled "
                f"a still-running async mode on {owner!r}. Inside async, use "
                f"await instead of then=.",
                stacklevel=2,
            )
        owner.mode = then

    def _mark_complete(self) -> None:
        self._done = True
        self._alive = False
        _release_process_driver(self)
        get_scheduler()._forget(self)

    def _fire_once(self) -> None:
        if self._done or self._cancelled:
            return
        owner = self._live_owner()
        if self.owner is not None and owner is None:
            self._cancel_for(_R_OWNER_GONE)
            return
        self._mark_complete()
        if self.kind == "wait":
            return
        if self._then is not None:
            self._apply_then(owner)
            return
        _invoke(self._fn, owner)

    def _poll_until(self) -> None:
        if self._done or self._cancelled:
            return
        pred = self._pred
        if pred is None:
            return
        from .state import DestroyedError

        try:
            hit = pred()
        except (DestroyedError, ReferenceError):
            # Same rule ``@when`` uses for its condition (events.py
            # ``_SOURCE_GONE``): the watched actor is gone, not an author
            # bug. ``until(lambda: boss.hp <= 0)`` used to raise
            # ``DestroyedError`` out of the process tick the frame after
            # ``boss.destroy()`` — contradicting "waiting on a dead entity
            # ends the script silently" for every other await path.
            self._cancel_for(_R_UNTIL_GONE)
            return
        except Exception:
            self._cancel_for(_R_UNTIL_RAISED)  # a broken predicate must not re-raise every frame
            raise
        if hit:
            self._mark_complete()

    def _poll_record(self) -> None:
        """Finish a microphone take on the process tick (natural end only)."""
        if self._done or self._cancelled:
            return
        take = self._record
        if take is None:
            return
        mic = take.mic
        if mic is not None:
            mic._service_record(take)
        if not take.finalized or not take.natural:
            return
        owner = self._live_owner()
        self._mark_complete()
        if self._then is not None:
            self._apply_then(owner)
            return
        if self._fn is not None:
            _invoke(self._fn, owner)

    def _poll_parallel(self) -> None:
        if self._done or self._cancelled:
            return
        kids = self._children or ()
        if not kids:
            self._mark_complete()
            return
        if not all(c._done for c in kids):
            return
        if any(c._cancelled for c in kids):
            self._cancel_for(_R_MEMBER)
            return
        self._mark_complete()

    def _poll_race(self) -> None:
        if self._done or self._cancelled:
            return
        kids = self._children or ()
        if not kids:
            self.cancel()
            return
        winner = None
        for i, child in enumerate(kids):
            if child._done and not child._cancelled:
                winner = i
                break
        if winner is None:
            if all(c._cancelled or c._done for c in kids):
                self._cancel_for(_R_MEMBER)
            return
        self._result = winner
        for i, child in enumerate(kids):
            if i != winner and not child._cancelled:
                child._cancel_for(_R_RACE)
        self._mark_complete()

    def _fire_every(self) -> None:
        if self._cancelled or self._done:
            return
        owner = self._live_owner()
        if self.owner is not None and owner is None:
            self._cancel_for(_R_OWNER_GONE)
            return
        _invoke(self._fn, owner)

    def _yoyo_u(self, u: float) -> float:
        """On odd laps with ``yoyo``, swap start/end by evaluating write at ``1 - u``."""
        if self._yoyo and (self._lap % 2) == 1:
            return 1.0 - float(u)
        return float(u)

    def _tick_tween(self) -> None:
        if self._cancelled or self._done:
            return
        if self._claimed_target_dead():
            self._cancel_for(_R_TARGET_GONE)
            return
        owner = self._live_owner()
        if self.owner is not None and owner is None:
            self._cancel_for(_R_OWNER_GONE)
            return
        duration = self.delay
        if duration <= 0.0:
            t = 1.0
        else:
            t = self._elapsed / duration
            if t > 1.0 or reached(self._elapsed, duration):
                t = 1.0
        u = 1.0 if t >= 1.0 else float(self._fn(t) if self._fn is not None else t)
        u = self._yoyo_u(u)
        write = self._tween_write
        if write is not None:
            try:
                write(u)
            except Exception:
                self.cancel()
                raise
        if t >= 1.0:
            loops = self._loops
            more = loops < 0 or (self._lap + 1) < loops
            if more and duration > 0.0:
                # Every whole lap this frame covered (PM8 tolerance): one frame
                # longer than a lap advanced one lap and dropped the rest, so a
                # finite run ended late and a yoyo lost its parity (review
                # 2026-10-09 W-T1).
                k = max(1, whole_steps(self._elapsed, 1.0 / duration))
                if loops >= 0 and self._lap + k >= loops:
                    # The run ends inside this frame: land on its last lap's end.
                    self._lap = loops - 1
                    self._elapsed = duration
                    if write is not None:
                        try:
                            write(self._yoyo_u(1.0))
                        except Exception:
                            self.cancel()
                            raise
                    self._mark_complete()
                    if self._then is not None:
                        self._apply_then(owner)
                    elif self._on_done is not None:
                        _invoke(self._on_done, owner)
                    return
                self._lap += k
                self._elapsed -= k * duration
                if self._elapsed < 0.0 or reached(self._elapsed, duration):
                    self._elapsed = 0.0     # a hair from a boundary: the boundary
                t2 = self._elapsed / duration if duration > 0.0 else 1.0
                if t2 > 1.0:
                    t2 = 1.0
                u2 = float(self._fn(t2) if self._fn is not None else t2)
                u2 = self._yoyo_u(u2)
                if write is not None:
                    try:
                        write(u2)
                    except Exception:
                        self.cancel()
                        raise
                return
            self._mark_complete()
            if self._then is not None:
                self._apply_then(owner)
            elif self._on_done is not None:
                _invoke(self._on_done, owner)

    def __await__(self):
        self._awaited = True
        if self.kind == "task" and not (self._done or self._cancelled):
            running = get_scheduler()._running
            if running is not None and running.handle is self:
                raise TypeError(
                    "a task cannot await itself (it would wait forever). "
                    "Await another task, or return a value and await the task "
                    "from the code that started it."
                )
        while not self._done and not self._cancelled:
            yield self
        if self._cancelled:
            raise Cancelled(self)      # the handle: its _cancel_reason names why
        return self._result

    def __del__(self) -> None:
        # getattr: a Handle whose _init raised has no slots filled.
        if not getattr(self, "_must_await", False) or getattr(self, "_awaited", False):
            return
        hint = self._await_hint or f"await {self.kind}(...)"
        where = ""
        if self._site:
            where = f" ({self._site[0]}, line {self._site[1]})"
        try:
            warnings.warn(
                f"{self.kind}() was not awaited{where}. Write {hint}.",
                stacklevel=1,
            )
        except Exception:
            pass

    def __repr__(self) -> str:
        bits = [self.kind]
        if self.name:
            bits.append(f"name={self.name!r}")
        bits.append(f"elapsed={self._elapsed:.3f}")
        if self._cancelled:
            bits.append("cancelled")
        elif self._done:
            bits.append("done")
        elif self._paused:
            bits.append("paused")
        elif self._held:
            bits.append("held")
        return f"<Handle {' '.join(bits)}>"


def _clear_mode_task(owner, handle) -> None:
    """Drop ``owner._mode_task`` if it still names ``handle`` (its body ended)."""
    if owner is not None and getattr(owner, "_mode_task", None) is handle:
        try:
            object.__setattr__(owner, "_mode_task", None)
        except Exception:
            pass


class Script:
    """The driver of one task: a coroutine the engine resumes (an async
    mode's body). Its ``handle`` is the ``Handle(kind="task")`` that owns it:
    the scheduler keeps the handle (owner, scope, cancel), the script keeps
    the coroutine and what it waits on (Actors Design — Tasks)."""

    __slots__ = (
        "coro", "owner", "kind", "done", "cancelled", "waiting_on", "silent",
        "_created_awaits", "handle", "waiting_since",
    )

    def __init__(self, coro, owner, *, kind: str = "mode", handle: Optional[Handle] = None):
        self.coro = coro
        self.owner = owner
        self.kind = kind
        self.done = False
        self.cancelled = False
        self.waiting_on: Optional[Handle] = None
        self.silent = False
        # The task's ``_elapsed`` when it reached its current await: how long
        # it has waited there (the process overlay; ``until`` has no clock).
        self.waiting_since = 0.0
        self._created_awaits: List[Handle] = []
        self.handle = handle

    def _end(self, *, cancelled: bool, result=None) -> None:
        """The body ended by itself (returned, raised, tripped the watchdog,
        or an awaited handle was cancelled under it): its task handle ends
        with it. A body that returned completes the handle (``await task``
        gets the value); the others leave it cancelled. Not a cancel of the
        task: nothing it started is cancelled here."""
        handle = self.handle
        if handle is None or handle._done or handle._cancelled:
            return
        handle._task = None            # no handle <-> script cycle left for the gc
        kids = handle._children
        if kids:
            # What it started goes on: the work of a nested task passes to the
            # task that started it (cancelling that one still ends it all).
            handle._children = None
            grand = handle._task_parent
            if grand is not None and (grand._done or grand._cancelled):
                grand = None
            for child in kids:
                child._task_parent = grand
                if grand is not None:
                    if grand._children is None:
                        grand._children = {}
                    grand._children[child] = None
        if cancelled:
            handle._cancelled = True
            handle._done = True
            handle._alive = False
            _release_process_driver(handle)
            get_scheduler()._forget(handle)
        else:
            handle._result = result
            handle._mark_complete()
        _clear_mode_task(handle._owner, handle)

    def start(self) -> None:
        self._advance()

    def cancel(self, *, silent: bool = False) -> None:
        if self.done:
            return
        self.silent = self.silent or silent
        # Any script on the stack, not only the innermost: cancelling an outer
        # running script threw into an executing coroutine (review 2026-10-09
        # S2-11). ``_advance`` closes it when its ``send`` returns.
        coro = self.coro
        running = (get_scheduler()._running is self
                   or getattr(coro, "cr_running", False)
                   or getattr(coro, "gi_running", False))
        self.cancelled = True
        self.done = True
        self.waiting_on = None
        if running:
            # The coroutine is on the stack (e.mode = … from inside the script).
            # Do not throw/close until send() returns.
            return
        try:
            self.coro.throw(Cancelled())
        except (Cancelled, StopIteration, _Watchdog):
            pass
        except Exception:
            if not self.silent:
                warnings.warn(
                    f"Exception in cancelled async {self.kind} on {self.owner!r}:\n"
                    f"{traceback.format_exc()}",
                    stacklevel=2,
                )
        try:
            self.coro.close()
        except Exception:
            pass

    def resume_if_ready(self) -> None:
        if self.done:
            return
        handle = self.waiting_on
        if handle is None:
            return
        if not handle._done and not handle._cancelled:
            return
        self._advance()

    def _advance(self, value=None) -> None:
        if self.done:
            return
        sched = get_scheduler()
        prev = sched._running
        sched._running = self
        self._created_awaits = []
        handle = self.handle
        own = (
            owning(handle._owner, scope=handle.scope)
            if handle is not None
            else nullcontext()
        )
        finished = False
        result = None
        try:
            try:
                with own:
                    yielded = _resume_with_watchdog(self.coro, value)
            except StopIteration as stop:
                self.done = True
                self.waiting_on = None
                finished = True
                result = stop.value
            except Cancelled as exc:
                self._cancelled_under_it(exc)
                return
            except _Watchdog:
                self._tripped_watchdog()
                return
            except Exception:
                self._abort()
                raise
        finally:
            sched._running = prev
        if finished:
            self._end(cancelled=False, result=result)
            self._raise_unused_awaits()
            return
        if self.cancelled:
            try:
                self.coro.close()
            except Exception:
                pass
            self.waiting_on = None
            return
        try:
            self._raise_unused_awaits()
            if not isinstance(yielded, Handle):
                # A bare yield (None: ``asyncio.sleep(0)``) included: the
                # tick resumes a task only when its Handle ends, so the
                # task would wait forever with no error.
                raise TypeError(self._not_a_handle_message(yielded))
        except TypeError:
            self._abort()
            raise
        self.waiting_on = yielded
        if handle is not None:
            self.waiting_since = handle._elapsed

    # The rare endings of ``_advance``, out of line: ``_advance`` is on the
    # stack whenever the watchdog turns its events on, and every function on
    # the stack is re-instrumented then (cost grows with its size).

    def _cancelled_under_it(self, exc: BaseException) -> None:
        """``Cancelled`` came out of the body. When the task itself was
        cancelled (its owner destroyed, its mode or act left, ``name=``
        replaced, ``cancel()``) that is the plan: quiet. Otherwise an awaited
        handle was cancelled *out from under* it (another tween claimed the
        same property, the awaited target was destroyed, an ``until()``
        subject was destroyed, ...) and the body did not catch ``Cancelled``
        around the ``await``: the task ends with a warning that names what it
        awaited, where, and why that ended. An async mode's ``e.mode`` still
        reads the old function; no further code in it will ever run."""
        handle = self.handle
        own = self.cancelled or (handle is not None and handle._cancelled)
        self.done = True
        self.cancelled = True
        self.waiting_on = None
        self._end(cancelled=True)
        if own or self.silent:
            return
        warnings.warn(self._under_it_message(exc), RuntimeWarning, stacklevel=4)

    def _under_it_message(self, exc: BaseException) -> str:
        src = exc.args[0] if exc.args and isinstance(exc.args[0], Handle) else None
        what = "handle"
        reason = "it was cancelled"
        if src is not None:
            what = src._claim_label or {"tween": "move or tween"}.get(src.kind, src.kind)
            reason = getattr(src, "_cancel_reason", None) or "cancel() was called on it"
        at = ""
        tb = exc.__traceback__
        while tb is not None:
            code = tb.tb_frame.f_code
            if not _is_ignored_filename(code.co_filename):
                at = f" at {os.path.basename(code.co_filename)}, line {tb.tb_lineno}"
            tb = tb.tb_next
        fix = ("If that is expected, wrap the `await` in `try: ... except Cancelled: ...`; "
               "to end the work together with an actor, start it on that actor "
               "(box.run_task(...)) or check `if box:` before using it.")
        if self.kind == "mode":
            mode = getattr(self.owner, "mode", None)
            mode_name = getattr(mode, "__name__", mode)
            return (
                f"async mode {mode_name!r} on {self.owner!r} was silently "
                f"cancelled: the {what} it was awaiting{at} was cancelled "
                f"({reason}). `.mode` still reports {mode_name!r}, but this mode "
                f"has stopped running. {fix}"
            )
        name = getattr(self.coro, "__name__", "task")
        return (
            f"task {name}() was silently cancelled: the {what} it was "
            f"awaiting{at} was cancelled ({reason}). {fix}"
        )

    def _who(self) -> str:
        """``async mode 'dive' on <Circle …>`` or ``task show()``: for messages."""
        if self.kind == "mode":
            mode = getattr(self.owner, "mode", None)
            mode_name = getattr(mode, "__name__", mode)
            return f"async mode {mode_name!r} on {self.owner!r}"
        return f"task {getattr(self.coro, '__name__', 'task')}()"

    def _not_a_handle_message(self, yielded) -> str:
        """The step yielded something the tick cannot wait on (not a Handle).

        Names what the body awaited and the author line, found down the
        suspended coroutine's ``cr_await`` chain: the deepest frame in author
        code is the ``await``, the next link is what it awaited
        (``asyncio.sleep(0)`` → ``sleep()``).
        """
        at = ""
        what = None
        try:
            link = self.coro
            while link is not None:
                frame = getattr(link, "cr_frame", None) or getattr(link, "gi_frame", None)
                nxt = getattr(link, "cr_await", None)
                if nxt is None:
                    nxt = getattr(link, "gi_yieldfrom", None)
                if (nxt is not None and frame is not None
                        and not _is_ignored_filename(frame.f_code.co_filename)):
                    at = (f" at {os.path.basename(frame.f_code.co_filename)}, "
                          f"line {frame.f_lineno}")
                    what = nxt
                link = nxt
        except Exception:
            pass
        qual = getattr(what, "__qualname__", None)
        if isinstance(qual, str):
            # ``Thing.__await__`` → ``Thing``: the author awaited the object.
            name = qual[:-len(".__await__")] if qual.endswith(".__await__") else f"{qual}()"
            module = getattr(getattr(what, "cr_code", None) or getattr(what, "gi_code", None),
                             "co_filename", "")
        else:
            obj = yielded if yielded is not None else what
            name = "None" if obj is None else type(obj).__name__
            module = getattr(type(obj), "__module__", "") or ""
        if "asyncio" in module or "asyncio" in (getattr(type(yielded), "__module__", "") or ""):
            name = f"asyncio.{name}"
        fix = ("await a Handle: wait(seconds) / until(...) / move_to(..., time=) / "
               "after(...); await wait(0) gives up the rest of the frame. A task runs "
               "on the game clock, not on an asyncio event loop.")
        if yielded is None:
            return (f"{self._who()} awaited {name}{at}, which yields nothing the "
                    f"engine can wait on (a bare yield): it would never resume; {fix}")
        return f"{self._who()} awaited {name}{at}, not a Scena Handle; {fix}"

    def _tripped_watchdog(self) -> None:
        self.done = True
        self.cancelled = True
        self.waiting_on = None
        self._end(cancelled=True)
        who = self._who()
        what = "mode" if self.kind == "mode" else "task"
        warnings.warn(
            f"SCENA ERROR: {who} "
            f"ran more than {WATCHDOG_RESUME_S:g}s without awaiting — "
            f"the {what} was CANCELLED and any in-progress work "
            f"(for example a partial spawn wave) may be incomplete. "
            f"This usually means `while True:` with no await. "
            f"Add `await wait(...)` / `await until(...)` / "
            f"`await move_to(..., time=)` inside the loop. "
            f"Constructing many Sprite(...) actors in one go is allowed.",
            RuntimeWarning,
            stacklevel=4,
        )
        try:
            self.coro.close()
        except Exception:
            pass

    def _abort(self) -> None:
        """An author error ended this script: done, coroutine closed, task ended."""
        self.done = True
        self.waiting_on = None
        try:
            self.coro.close()
        except Exception:
            pass  # never shadow the error that ended the script
        self._end(cancelled=True)

    def _raise_unused_awaits(self) -> None:
        """``wait`` / ``until`` / … created by this resume but never awaited → ``TypeError``.

        A handle already cancelled (``h.cancel()``, owner destroyed) is not a
        forgotten ``await``.
        """
        leftover = [
            h for h in self._created_awaits
            if h._must_await and not h._awaited and not h._cancelled
        ]
        self._created_awaits = []
        if not leftover:
            return
        for handle in leftover:
            handle._awaited = True
            if not handle._done and not handle._cancelled:
                handle.cancel()
        handle = leftover[0]
        hint = handle._await_hint or f"await {handle.kind}(...)"
        where = ""
        if handle._site:
            where = f" ({handle._site[0]}, line {handle._site[1]})"
        raise TypeError(f"{handle.kind}() was not awaited{where}. Write {hint}.")


def _is_scena_filename(filename: str) -> bool:
    """True when *filename* is under this package (``scena/…``)."""
    hit = _SCENA_FILE_CACHE.get(filename)
    if hit is not None:
        return hit
    try:
        abs_fn = os.path.abspath(filename)
    except Exception:
        abs_fn = filename
    root = _SCENA_PKG_ROOT
    # Exact package tree only — not repo ``scripts/`` or ``tests/``.
    result = abs_fn == root or abs_fn.startswith(root + os.sep)
    _SCENA_FILE_CACHE[filename] = result
    return result


# Interpreter lib trees (stdlib + site-packages). Cached per filename.
_IGNORE_FILE_CACHE: Dict[str, bool] = {}
_IGNORE_ROOTS: Optional[Tuple[str, ...]] = None


def _ignore_roots() -> Tuple[str, ...]:
    global _IGNORE_ROOTS
    if _IGNORE_ROOTS is not None:
        return _IGNORE_ROOTS
    roots: List[str] = []
    for prefix in (getattr(sys, "base_prefix", None), sys.prefix):
        if not prefix:
            continue
        try:
            base = os.path.abspath(prefix)
        except Exception:
            continue
        # POSIX uses ``lib/``; Windows CPython uses ``Lib/``.
        for name in ("lib", "Lib"):
            roots.append(os.path.join(base, name))
    _IGNORE_ROOTS = tuple(roots)
    return _IGNORE_ROOTS


def _is_ignored_filename(filename: str) -> bool:
    """True for engine, frozen importer, or interpreter lib (stdlib / site-packages).

    Used by the monitoring LINE callback: ignored code objects return
    ``sys.monitoring.DISABLE`` so Scena/stdlib stop paying instrumentation after
    first touch (bulk ``Sprite(...)`` waves stay lean).
    """
    if _is_scena_filename(filename):
        return True
    hit = _IGNORE_FILE_CACHE.get(filename)
    if hit is not None:
        return hit
    # Engine builds Color/state helpers via exec → ``<string>``. Frozen importer
    # modules are not author code. Keep ``<stdin>`` countable for REPLs/tests.
    if filename == "<string>" or filename.startswith("<frozen "):
        _IGNORE_FILE_CACHE[filename] = True
        return True
    try:
        abs_fn = os.path.abspath(filename)
    except Exception:
        _IGNORE_FILE_CACHE[filename] = False
        return False
    ignored = False
    for root in _ignore_roots():
        if abs_fn == root or abs_fn.startswith(root + os.sep):
            ignored = True
            break
    _IGNORE_FILE_CACHE[filename] = ignored
    return ignored


# --- An async function called without ``await`` ---------------------------
# ``show()`` with no ``await`` builds a coroutine and drops it: nothing in
# ``show()`` runs. CPython reports it through ``warnings._warn_unawaited_coroutine``
# (looked up on the module at each report, from the frame whose statement
# dropped the coroutine), with a message that does not say what to write.
# The hook says it as a SCENA WARNING (banner + console) for author code and
# hands everything else (stdlib, site-packages, the engine) to Python's own.

_UNAWAITED_ORIGINAL: Optional[Callable] = None
_UNAWAITED_HOOK_ACTIVE = False
_UNAWAITED_PROBE_SEEN = False
# Origin tracking depth before the hook turned it on: Python's own message
# lists where the coroutine was made only when the program asked for it.
_UNAWAITED_USER_DEPTH = 0


async def _unawaited_probe() -> None:
    """Dropped once at install: proves the interpreter calls the hook."""


def _unawaited_message(coro) -> str:
    code = coro.cr_code
    name = f"{code.co_name}()"
    where = ""
    origin = getattr(coro, "cr_origin", None)
    if origin:
        filename, lineno, _func = origin[0]   # the caller (most recent first)
        where = f" at {os.path.basename(filename)}, line {lineno}"
    return (
        f"{name} was called{where} but never awaited, so nothing in {name} ran. "
        f"Inside async code write await {name}; from a plain def start it as "
        f"a task (run_task({code.co_name})) or an async mode "
        f"(self.mode = self.{code.co_name})."
    )


def _python_unawaited(coro) -> None:
    """Python's own "never awaited" warning, as if the hook were not there.

    Same text as ``warnings._warn_unawaited_coroutine`` (the creation lines
    only when the program had turned origin tracking on itself) and the same
    location: ``stacklevel=3`` is the frame that dropped the coroutine
    (this function ← the hook ← that frame).
    """
    msg = f"coroutine '{coro.__qualname__}' was never awaited"
    origin = getattr(coro, "cr_origin", None)
    if origin and _UNAWAITED_USER_DEPTH > 0:
        import linecache
        lines = ["Coroutine created at (most recent call last)\n"]
        lines += traceback.format_list([
            (f, n, fn, linecache.getline(f, n)) for f, n, fn in reversed(origin)
        ])
        msg = (msg + "\n" + "".join(lines)).rstrip("\n")
    warnings.warn(msg, category=RuntimeWarning, stacklevel=3, source=coro)


def _warn_unawaited(coro) -> None:
    """``warnings._warn_unawaited_coroutine`` while Scena is imported.

    Runs while the coroutine is being freed: it never raises (any failure
    falls back to Python's own warning).
    """
    global _UNAWAITED_PROBE_SEEN
    original = _UNAWAITED_ORIGINAL
    try:
        code = coro.cr_code
        if code is _unawaited_probe.__code__:
            _UNAWAITED_PROBE_SEEN = True
            return
        if _is_ignored_filename(code.co_filename):
            _python_unawaited(coro)
            return
        report_author_warning("async call", _unawaited_message(coro))
    except BaseException:
        try:
            _python_unawaited(coro)
        except BaseException:
            if original is not None:
                try:
                    original(coro)
                except BaseException:
                    pass


def install_unawaited_hook() -> bool:
    """Route "coroutine … was never awaited" through :func:`_warn_unawaited`.

    Idempotent. Turns on coroutine origin tracking (depth ≥ 1) so the
    message names the line that called the function. Returns whether the
    interpreter calls the hook (a probe coroutine is dropped to find out);
    when it does not, Python's own warning stays.
    """
    global _UNAWAITED_ORIGINAL, _UNAWAITED_HOOK_ACTIVE, _UNAWAITED_PROBE_SEEN
    global _UNAWAITED_USER_DEPTH
    current = getattr(warnings, "_warn_unawaited_coroutine", None)
    if current is None:
        return False
    if current is not _warn_unawaited:
        _UNAWAITED_ORIGINAL = current
        warnings._warn_unawaited_coroutine = _warn_unawaited
        try:
            _UNAWAITED_USER_DEPTH = sys.get_coroutine_origin_tracking_depth()
            if _UNAWAITED_USER_DEPTH < 1:
                sys.set_coroutine_origin_tracking_depth(1)
        except Exception:
            pass
    if not _UNAWAITED_HOOK_ACTIVE:
        _UNAWAITED_PROBE_SEEN = False
        _unawaited_probe()  # dropped at once: the hook records it
        _UNAWAITED_HOOK_ACTIVE = _UNAWAITED_PROBE_SEEN
    return _UNAWAITED_HOOK_ACTIVE


def set_watchdog(enabled: bool = True) -> None:
    """Turn the author-code freeze watchdog on or off.

    Default is on for async mode resumes. Sync hooks (``on_update``, script
    ``update(dt)``) are guarded only when ``set_sync_watchdog(True)`` (off by
    default for frame cost). ``set_watchdog(False)`` skips all
    ``sys.monitoring`` (benchmarks / demos). Same as assigning
    ``WATCHDOG_ENABLED``.

    Args:
        enabled: ``True`` (default) stops an async mode stuck in a loop with an error;
            ``False`` turns every check off (benchmarks / demos).
    """
    global WATCHDOG_ENABLED
    from .validate import expect_bool
    WATCHDOG_ENABLED = expect_bool(enabled, "set_watchdog enabled")


def set_sync_watchdog(enabled: bool = True) -> None:
    """Turn LINE-event guarding on or off for sync hooks.

    ``update(dt)`` and the ``on_update`` fleet. Default off — enabling adds
    ~10–15%% overhead on scripts with heavy per-frame Python. Async mode
    resume is unaffected (always follows ``set_watchdog``). Same as assigning
    ``SYNC_WATCHDOG_ENABLED``.
    """
    global SYNC_WATCHDOG_ENABLED
    from .validate import expect_bool
    SYNC_WATCHDOG_ENABLED = expect_bool(enabled, "set_sync_watchdog enabled")


def _ensure_watchdog_tool() -> None:
    """Claim monitoring tool id once; register the LINE callback."""
    global _watchdog_tool_ready
    if _watchdog_tool_ready:
        return
    if not hasattr(sys, "monitoring"):
        raise RuntimeError(
            "Scena async watchdog requires Python 3.12+ (sys.monitoring)"
        )
    mon = sys.monitoring
    try:
        mon.use_tool_id(_WATCHDOG_TOOL_ID, _WATCHDOG_TOOL_NAME)
    except ValueError:
        try:
            mon.free_tool_id(_WATCHDOG_TOOL_ID)
        except ValueError:
            pass
        mon.use_tool_id(_WATCHDOG_TOOL_ID, _WATCHDOG_TOOL_NAME)
    mon.register_callback(_WATCHDOG_TOOL_ID, mon.events.LINE, _watchdog_on_line)
    mon.register_callback(_WATCHDOG_TOOL_ID, mon.events.JUMP, _watchdog_on_jump)
    _watchdog_tool_ready = True


def _watchdog_on_line(code, line_number):
    """LINE callback: DISABLE non-author code; sample wall-clock on author lines."""
    global _wd_author_lines
    if _is_ignored_filename(code.co_filename):
        return sys.monitoring.DISABLE
    _wd_author_lines += 1
    if _wd_author_lines % _wd_check_every == 0:
        if time.perf_counter() > _wd_deadline:
            raise _Watchdog()
    return None


# ``id(code)`` → (weak ref to the code, offsets of its one-line back jumps).
# Weak: an author's code (and with it the module) must not outlive the
# program (AC1).
_WD_ONE_LINE_JUMPS: Dict[int, Tuple[Any, set]] = {}


def _line_at(code, offset: int) -> Optional[int]:
    for start, end, line in code.co_lines():
        if start <= offset < end:
            return line
    return None


def _watchdog_on_jump(code, src, dest):
    """JUMP callback: a loop on one line (``while not st.pronto: pass``,
    ``while n < 10**9: n += 1``) emits no new LINE event, only its backward
    jump, and escaped the watchdog (review 2026-10-14 PA2).

    Only a backward jump that lands on its own line counts: a forward jump
    never loops, and a back jump to another line fires LINE on every
    iteration already. Those locations return ``DISABLE`` on first touch,
    so a multi-line loop pays the JUMP callback once, not per iteration."""
    global _wd_author_lines
    if dest >= src or _is_ignored_filename(code.co_filename):
        return sys.monitoring.DISABLE
    entry = _WD_ONE_LINE_JUMPS.get(id(code))
    if entry is None or entry[0]() is not code or src not in entry[1]:
        if _line_at(code, src) != _line_at(code, dest):
            return sys.monitoring.DISABLE
        if entry is None or entry[0]() is not code:
            entry = _WD_ONE_LINE_JUMPS[id(code)] = (ref(code), set())
        entry[1].add(src)
    _wd_author_lines += 1
    if _wd_author_lines % _wd_check_every == 0:
        if time.perf_counter() > _wd_deadline:
            raise _Watchdog()
    return None


# LINE | JUMP: every author line, and every jump (a one-line loop has only
# jumps). A/B switch for scripts/bench (``_WD_EVENTS = LINE`` is the old guard).
_WD_EVENTS = None


def _watchdog_events() -> int:
    ev = _WD_EVENTS
    if ev is None:
        mon = sys.monitoring
        ev = mon.events.LINE | mon.events.JUMP
    return ev


def _run_with_watchdog(
    fn, /, *args, budget: Optional[float] = None, sync: bool = False, **kwargs,
):
    """Run ``fn(*args, **kwargs)`` under the LINE-event wall-clock watchdog.

    Raises :class:`_Watchdog` if author code spins longer than ``budget``
    (default ``WATCHDOG_RESUME_S``) without returning. Nested calls reuse the
    outer instrumentation. ``set_watchdog(False)`` skips the guard. When
    ``sync=True``, also requires ``set_sync_watchdog(True)`` (off by default).
    """
    global _watchdog_resume_depth, _wd_deadline, _wd_author_lines, _wd_check_every

    if not WATCHDOG_ENABLED or _watchdog_resume_depth > 0:
        return fn(*args, **kwargs)
    if sync and not SYNC_WATCHDOG_ENABLED:
        return fn(*args, **kwargs)

    limit = float(WATCHDOG_RESUME_S if budget is None else budget)
    if _wd_window_open:
        return _run_in_watchdog_window(fn, args, kwargs, limit)

    _ensure_watchdog_tool()
    mon = sys.monitoring
    _wd_deadline = time.perf_counter() + limit
    _wd_author_lines = 0
    _wd_check_every = max(1, int(WATCHDOG_CHECK_EVERY))
    prev_events = mon.get_events(_WATCHDOG_TOOL_ID)
    _watchdog_resume_depth += 1
    mon.set_events(_WATCHDOG_TOOL_ID, _watchdog_events())
    try:
        return fn(*args, **kwargs)
    finally:
        mon.set_events(_WATCHDOG_TOOL_ID, prev_events)
        _watchdog_resume_depth -= 1


def _run_in_watchdog_window(fn, args, kwargs, limit: float):
    """A guarded call while the task walk holds the events on: only this
    resume's deadline (out of ``_run_with_watchdog``, which is on the stack
    when the events toggle and so is re-instrumented then)."""
    global _watchdog_resume_depth, _wd_deadline, _wd_author_lines, _wd_check_every
    _wd_deadline = time.perf_counter() + limit
    _wd_author_lines = 0
    _wd_check_every = max(1, int(WATCHDOG_CHECK_EVERY))
    _watchdog_resume_depth += 1
    try:
        return fn(*args, **kwargs)
    finally:
        _watchdog_resume_depth -= 1
        _wd_deadline = math.inf


def _watchdog_window_open() -> bool:
    """Turn the watchdog events on for a run of resumes (the task walk).

    Returns whether this call opened the window (close it with
    :func:`_watchdog_window_close`). No-op when the watchdog is off, a
    window is open, or a guarded call is already running.
    """
    global _wd_window_open, _wd_window_prev, _wd_deadline
    if not WATCHDOG_ENABLED or _wd_window_open or _watchdog_resume_depth > 0:
        return False
    _ensure_watchdog_tool()
    mon = sys.monitoring
    _wd_deadline = math.inf
    _wd_window_prev = mon.get_events(_WATCHDOG_TOOL_ID)
    mon.set_events(_WATCHDOG_TOOL_ID, _watchdog_events())
    _wd_window_open = True
    return True


def _watchdog_window_close() -> None:
    global _wd_window_open
    _wd_window_open = False
    sys.monitoring.set_events(_WATCHDOG_TOOL_ID, _wd_window_prev)


def _resume_with_watchdog(coro, value=None):
    """``coro.send`` with a wall-clock watchdog so ``while True`` cannot freeze ``run()``.

    Uses ``sys.monitoring`` LINE events (Python 3.12+). Non-author code objects
    return ``DISABLE`` after first touch so engine work (Sprite/atlas/looks) does
    not keep paying. Trips when one resume exceeds ``WATCHDOG_RESUME_S`` without
    an ``await``. ``set_watchdog(False)`` skips instrumentation entirely.
    """
    return _run_with_watchdog(coro.send, value)


# ``Scheduler._every_sites`` sweeps idle keys past this many (flood detector).
_EVERY_SITES_SWEEP_AT = 64


def _rings_out(handle: Handle) -> bool:
    """Does this sound finish when its owner ends? (Sound Design — When the owner ends)

    A sound that ends by itself rings out; one that would play forever is cut.
    Order matters: a paused voice never ends; a ``fade_out`` in flight ends
    even a named slot or a forever loop.
    """
    if handle.kind != "sound" or handle._done or handle._cancelled:
        return False
    if handle._paused:
        return False
    if handle._fading_out():
        return True
    if handle._name:
        return False  # a named slot is a channel (music, ambience)
    if handle._sound_loops < 0:
        return False  # loops="forever"
    # A live source (Microphone) has no clip duration: it never ends.
    return handle._clip_duration > 0.0


class _OrderedWeakSet:
    """A weak set that iterates in insertion order (``WeakSet`` iterates in
    hash order, which is the object's address: the ``on_update`` fleet ran in
    a different order on every run)."""

    __slots__ = ("_refs",)

    def __init__(self) -> None:
        self._refs: Dict[int, "weakref.ref"] = {}

    def add(self, item) -> None:
        key = id(item)
        if key in self._refs:
            return
        refs = self._refs

        def _gone(ref, key=key, refs=refs):
            if refs.get(key) is ref:
                del refs[key]

        refs[key] = ref(item, _gone)

    def discard(self, item) -> None:
        ref = self._refs.get(id(item))
        if ref is not None and ref() is item:
            del self._refs[id(item)]

    def __contains__(self, item) -> bool:
        ref = self._refs.get(id(item))
        return ref is not None and ref() is item

    def __iter__(self):
        for ref in list(self._refs.values()):
            obj = ref()
            if obj is not None:
                yield obj

    def __len__(self) -> int:
        return len(self._refs)

    def __bool__(self) -> bool:
        return bool(self._refs)


class Scheduler:
    """Cooperative timer list, driven by ``clock.dt`` (already scaled)."""

    def __init__(self) -> None:
        # Insertion-ordered dicts (value unused). Removal is O(1) anywhere,
        # creation order is kept, and a finished Handle drops immediately —
        # no tombstones, so a destroyed Entity can be collected right after
        # destroy() without waiting for the next tick.
        self._every: Dict[Handle, None] = {}
        self._once: Dict[Handle, None] = {}       # after / wait
        self._tween: Dict[Handle, None] = {}
        self._await_family: Dict[Handle, None] = {}  # until / parallel / race
        self._sound: Dict[Handle, None] = {}
        self._handles: Dict[Handle, None] = {}    # union view for tests / inventory
        # id(owner) → that owner's live handles. The Handle holds the owner
        # strongly, so the id cannot be reused while the key is present.
        self._by_owner: Dict[int, Dict[Handle, None]] = {}
        self._named: Dict[Tuple[Optional[int], str], Handle] = {}
        # Game-scope named handles an act's same-name ownerless handle took the
        # slot from: paused, not cancelled; the act change gives them back
        # (``resume_suspended_game_slots``). Key -> (handle, was it paused).
        self._suspended_game: Dict[Tuple[Any, str], Tuple[Handle, bool]] = {}
        self._tweens: Dict[object, Handle] = {}
        # Finished voice ids carried to the next tick after a raise (S2-13).
        self._sound_carry: set = set()
        # Insertion-ordered (creation order): a WeakSet walked in address
        # order, which changed from run to run (review 2026-10-09 S2-9).
        self._mode_owners = _OrderedWeakSet()
        self._update_owners = _OrderedWeakSet()
        self._update_running = False
        self._update_pos: Dict[int, int] = {}
        self._mode_dense: List[object] = []
        self._update_dense: List[object] = []
        self._mode_dirty = False
        self._update_dirty = False
        # Tasks (``Handle(kind="task")``: async mode bodies), creation order.
        # Walked after every other bucket, before ``on_update``.
        self._tasks: Dict[Handle, None] = {}
        # Set while the tick walks tasks: a task started during the walk is
        # also visited in it (the walk is not limited to its snapshot).
        self._task_walk_extras: Optional[List[Handle]] = None
        self._every_sites: Dict[Tuple[Optional[int], str, int], List[float]] = {}
        self._every_flood_warned: set = set()
        self._running: Optional[Script] = None
        # True while tick() runs (tests read it after a raise: the tick's
        # finally must reset it).
        self._iterating = False

    def _bucket_for(self, handle: Handle) -> Dict[Handle, None]:
        kind = handle.kind
        if kind == "every":
            return self._every
        if kind in ("after", "wait"):
            return self._once
        if kind == "tween":
            return self._tween
        if kind in ("until", "parallel", "race", "record"):
            return self._await_family
        if kind == "sound":
            return self._sound
        if kind == "task":
            return self._tasks
        return self._once

    def add(self, handle: Handle) -> Handle:
        owner = handle.owner
        replaced = None
        if owner is not None and _is_entity(owner) and not getattr(owner, "is_alive", True):
            # Work scheduled on a destroyed actor (e.g. ``e.after`` inside a
            # teardown callback) never runs: hand back a cancelled Handle and
            # keep it out of every bucket — registering it would hold the dead
            # owner until the next tick noticed.
            handle._cancel_for(_R_DEAD_AT_START)
            return handle
        if handle.name:
            key = (id(handle.owner) if handle.owner is not None else None, handle.name)
            self.refuse_game_task_clash(handle.owner, handle.scope, handle.name,
                                        handle.kind, new=handle)
            old = self._named.get(key)
            if (old is not None and old is not handle and key[0] is None
                    and old.scope == SCOPE_GAME and handle.scope == SCOPE_ACT
                    and old.kind in _PAUSABLE_KINDS
                    and not (old._done or old._cancelled)):
                # An act's timer takes a game timer's name: it replaces it for
                # the act only. The game's pauses and comes back at the act
                # change (review 2026-10-09 S2-6; Act Design).
                # setdefault: the act object may have set it aside already
                # (``_shadow_game_slot``); its "was paused" is the author's.
                self._suspended_game.setdefault(key, (old, old._paused))
                old.pause()
                old = None
            elif key[0] is not None and getattr(handle.owner, "_scena_is_act", False):
                self._shadow_game_slot(handle.name)
            if old is not None and old is not handle:
                old_fn = old._fn
                # Its parent first: the cancel unlinks it (a task restarting
                # itself takes its place under that parent, _link_to_task).
                replaced = (old, old._task_parent)
                old._cancel_for(_R_NAME)
                # Keep decorator ``fn.handle`` pointing at the live slot occupant.
                if (
                    old_fn is not None
                    and handle._fn is old_fn
                    and getattr(old_fn, "handle", None) is old
                ):
                    old_fn.handle = handle
            self._named[key] = handle
        for key in handle._tween_keys:
            old_tw = self._tweens.get(key)
            if old_tw is not None and old_tw is not handle:
                # Prefer _preempt_tween_keys (warns once at call site); cancel
                # here only if a handle slipped through without preempt.
                if _claim_active(old_tw):
                    warnings.warn(
                        f"tween/move_along on the same property replaces a previous "
                        f"in-flight {old_tw._claim_kind or old_tw.kind} handle",
                        RuntimeWarning,
                        stacklevel=3,
                    )
                    old_tw._cancel_for(_R_PREEMPTED)
            self._tweens[key] = handle
        self._bucket_for(handle)[handle] = None
        self._handles[handle] = None
        if handle.kind == "task":
            extras = self._task_walk_extras
            if extras is not None:
                extras.append(handle)
        owner = handle.owner
        if owner is not None:
            owned = self._by_owner.get(id(owner))
            if owned is None:
                owned = {}
                self._by_owner[id(owner)] = owned
            owned[handle] = None
        running = self._running
        if running is not None:
            if handle._must_await:
                running._created_awaits.append(handle)
            self._link_to_task(running, handle, replaced)
        return handle

    def _link_to_task(self, running: "Script", handle: Handle, replaced) -> None:
        """Work made during a task's step with the task's own owner and scope
        is the task's: it dies when the task is cancelled or replaced
        (``_children``), and is cancelled at once when the task already was
        (``self.mode = calm`` earlier in ``angry``'s step). A mode's body keeps
        no list: the mode's scope already ends its work on leave."""
        parent = running.handle
        if parent is None or parent is handle:
            return
        if replaced is not None and parent is replaced[0]:
            # ``run_task(loop, name="loop")`` inside ``loop``: the new run
            # takes the old run's place under its parent.
            parent = replaced[1]
            if parent is None:
                return
        if parent._owner is not handle._owner or parent.scope != handle.scope:
            return                     # another actor's work, or e.after from a mode
        if parent._cancelled:
            handle._cancel_for(_R_TASK)
            return
        if running.kind == "mode":
            return
        kids = parent._children
        if kids is None:
            kids = parent._children = {}
        kids[handle] = None
        handle._task_parent = parent

    def _forget(self, handle: Handle) -> None:
        parent = handle._task_parent
        if parent is not None:
            handle._task_parent = None
            kids = parent._children
            if kids is not None:
                kids.pop(handle, None)
        if handle.name:
            key = (id(handle.owner) if handle.owner is not None else None, handle.name)
            if self._named.get(key) is handle:
                del self._named[key]
        for key in handle._tween_keys:
            if self._tweens.get(key) is handle:
                del self._tweens[key]
        self._bucket_for(handle).pop(handle, None)
        self._handles.pop(handle, None)
        owner = handle.owner
        if owner is not None:
            owned = self._by_owner.get(id(owner))
            if owned is not None:
                owned.pop(handle, None)
                if not owned:
                    self._by_owner.pop(id(owner), None)
                    if getattr(owner, "_mode", None) is not None:
                        _note_idle_from(owner)

    def _reparent_to_game(self, handle: Handle) -> None:
        owner = handle._owner
        parent = handle._task_parent
        if parent is not None:         # a released sound is nobody's work now
            handle._task_parent = None
            if parent._children is not None:
                parent._children.pop(handle, None)
        if handle._name:
            # Unbind with the *old* key: once the owner is cleared, _forget
            # would look up (None, name) and leave a stale slot that a new
            # object reusing the dead owner's id could cut.
            key = (id(owner) if owner is not None else None, handle._name)
            if self._named.get(key) is handle:
                del self._named[key]
            handle._name = None
        if owner is not None:
            owned = self._by_owner.get(id(owner))
            if owned is not None:
                owned.pop(handle, None)
                if not owned:
                    self._by_owner.pop(id(owner), None)
        handle._owner = None
        handle._owner_ref = None
        handle.scope = SCOPE_GAME

    def _release_sound(self, handle: Handle) -> None:
        """The owner ended and this sound ends by itself: it finishes as game work.

        Callbacks never outlive the owner (``on_done`` / ``then=`` dropped).
        Its fade tween (``fade_out`` in flight) moves with it.
        """
        fade = handle._linked_sound_fade()
        self._reparent_to_game(handle)
        handle._fn = None
        handle._then = None
        handle._on_done = None
        if fade is not None:
            self._reparent_to_game(fade)

    def _end_implicitly(self, handle: Handle) -> None:
        """An owner ended without an explicit cancel: ring out or cut."""
        if _rings_out(handle):
            self._release_sound(handle)
        else:
            handle.cancel()

    def cancel_owner(
        self,
        owner,
        *,
        scopes: Optional[Tuple[str, ...]] = None,
        release: bool = False,
    ) -> None:
        """Cancel handles belonging to ``owner``. ``scopes`` defaults to all.

        Walks only that owner's handles (creation order), not every live job.
        ``release=True`` is an implicit ending (destroy, mode leave): a sound
        that ends by itself rings out instead (``_rings_out``). Sounds go
        first so a releasing sound takes its fade tween along before the
        cancel loop reaches it.
        """
        owned = self._by_owner.get(id(owner)) if owner is not None else None
        if not owned:
            pass
        elif _is_entity(owner) and not getattr(owner, "is_alive", True):
            reason = _R_OWNER_GONE
        elif scopes is not None and SCOPE_MODE in scopes:
            reason = _R_MODE_LEFT
        else:
            reason = _R_PROCESS
        if owned and release:
            for handle in list(owned):
                if handle.kind != "sound" or handle.owner is not owner:
                    continue
                if scopes is not None and handle.scope not in scopes:
                    continue
                if _rings_out(handle):
                    self._release_sound(handle)
            owned = self._by_owner.get(id(owner))
        if owned:
            # Tasks last: a mode's timers are gone before its body is thrown
            # (a ``finally`` in the body sees them cancelled, as it always did).
            tasks = None
            for handle in list(owned):
                if handle.owner is not owner:
                    continue
                if scopes is not None and handle.scope not in scopes:
                    continue
                if handle.kind == "task":
                    if tasks is None:
                        tasks = []
                    tasks.append(handle)
                    continue
                handle._cancel_for(reason)
            if tasks:
                for handle in tasks:
                    handle._cancel_for(reason)
        if scopes is None and _is_entity(owner) and not getattr(owner, "is_alive", True):
            # destroy(): forget the owner now, not at the next busy tick —
            # the dense snapshots hold it strongly.
            self._mode_owners.discard(owner)
            self._update_owners.discard(owner)
            self._mode_dirty = True
            self._update_dirty = True

    def refuse_game_task_clash(self, owner, scope: str, name: Optional[str],
                               kind: str, *, new: Optional[Handle] = None) -> None:
        """Ownerless act work named like a running game task raises.

        A task cannot pause, so it cannot step aside for the act the way a
        game timer does (``_suspended_game``): the restart would end the
        game's task for good, silently. ``add`` calls this before anything
        registers; ``play_sound`` and the tween verbs call it before they
        start a voice or claim a target.
        """
        if not name or owner is not None:
            return
        if scope == SCOPE_ACT and not _top_level_ended:
            scope = SCOPE_GAME          # as Handle._make decides
        if scope != SCOPE_ACT:
            return
        old = self._named.get((None, name))
        if (old is None or old is new or old.kind != "task"
                or old.scope != SCOPE_GAME or old._done or old._cancelled):
            return
        raise ValueError(_game_task_clash_message(old, name, kind))

    def _shadow_game_slot(self, name: str) -> None:
        """The act object's own named work (``self.every(…, name=)``, a loose
        ``every`` whose callback is an act method, ``self.play_sound(…,
        name=)``) takes a game handle's name: the game's steps aside for the
        act, as for the act's ownerless work above (R4-5: both ran, two
        tracks played). The act's handle keeps its own slot; the act change
        gives the game's back."""
        key = (None, name)
        if key in self._suspended_game:
            return
        game = self._named.get(key)
        if (game is not None and game.scope == SCOPE_GAME
                and game.kind in _PAUSABLE_KINDS
                and not (game._done or game._cancelled)):
            self._suspended_game[key] = (game, game._paused)
            game.pause()

    def resume_suspended_game_slots(self) -> None:
        """An act change: game named handles an act shadowed take their slot
        back and resume (unless the author paused or cancelled them)."""
        suspended, self._suspended_game = self._suspended_game, {}
        for key, (handle, was_paused) in suspended.items():
            if handle._done or handle._cancelled:
                continue
            current = self._named.get(key)
            if current is not None and current is not handle and not (
                    current._done or current._cancelled):
                continue
            self._named[key] = handle
            if not was_paused:
                handle.resume()

    def cancel_ownerless(self, scope: str = SCOPE_ACT, *, release: bool = False) -> int:
        """Cancel every ownerless handle of ``scope`` (an act change). Returns the count.

        ``release=True``: a sound that ends by itself rings out as game work
        instead (not counted). Sounds go first, so a released sound's fade
        tween leaves the act scope before the cancel pass.
        """
        if release:
            for handle in list(self._sound):
                if handle._owner is None and handle.scope == scope and _rings_out(handle):
                    self._release_sound(handle)
        n = 0
        tasks = []                      # tasks last, as in cancel_owner
        for handle in list(self._handles):
            if handle._owner is None and handle.scope == scope and not handle._cancelled:
                if handle.kind == "task":
                    tasks.append(handle)
                    continue
                handle._cancel_for(_R_ACT)
                n += 1
        for handle in tasks:
            if not handle._cancelled:
                handle._cancel_for(_R_ACT)
                n += 1
        return n

    def watch_mode(self, item, active: bool) -> None:
        if item is None:
            return
        if active and _is_entity(item) and not getattr(item, "is_alive", True):
            return  # a destroyed actor never ticks again (see ``add``)
        if active:
            self._mode_owners.add(item)
        else:
            self._mode_owners.discard(item)
        self._mode_dirty = True

    def watch_update(self, item, active: bool) -> None:
        if item is None:
            return
        if active and _is_entity(item) and not getattr(item, "is_alive", True):
            return  # a destroyed actor never ticks again (see ``add``)
        if active:
            self._update_owners.add(item)
        else:
            self._update_owners.discard(item)
        self._update_dirty = True
        if self._update_running:
            # Cleared or replaced by an earlier ``on_update`` this frame: the
            # old function does not run later in the frame (review 2026-10-09
            # S2-10). The frame's snapshot entry is swapped, so the fleet
            # loop pays nothing per actor.
            i = self._update_pos.get(id(item))
            dense = self._update_dense
            if i is not None and i < len(dense) and dense[i][0] is item:
                dense[i] = (item, _no_update, _CALL_NONE)

    def _refresh_mode_dense(self) -> None:
        if not self._mode_dirty:
            return
        self._mode_dense = [o for o in self._mode_owners]
        self._mode_dirty = False

    def _refresh_update_dense(self) -> None:
        if not self._update_dirty:
            return
        dense = []
        for o in self._update_owners:
            fn = getattr(o, "_on_update", None)
            if fn is None or not callable(fn):
                continue
            dense.append((o, fn, _update_call_form(fn)))
        self._update_dense = dense
        self._update_pos = {id(o): i for i, (o, _fn, _form) in enumerate(dense)}
        self._update_dirty = False

    def start_task(self, owner, coro, *, scope: str, mode: bool = False,
                   fn: Optional[Callable] = None, name: Optional[str] = None) -> Handle:
        """Register a task for ``coro`` and run its first step now.

        ``mode=True``: the body of ``owner``'s async mode (``owner._mode_task``;
        the mode's leave cancels it with the mode-scoped work). The first
        step runs here, in the caller's phase; its exceptions raise here.
        """
        if mode:
            old = getattr(owner, "_mode_task", None)
            if old is not None and not old._done:
                old.cancel()
        handle = Handle._make(kind="task", owner=owner, scope=scope, fn=fn, name=name)
        try:
            self.add(handle)
        except BaseException:
            coro.close()               # refused (a bad name=): no "never awaited" on top
            raise
        if handle._cancelled:          # owner already dead: the body never starts
            coro.close()
            return handle
        script = Script(coro, owner, kind="mode" if mode else "task", handle=handle)
        handle._task = script
        if mode:
            object.__setattr__(owner, "_mode_task", handle)
        script.start()
        return handle

    def note_every_site(
        self,
        site: Tuple[str, int],
        *,
        owner=None,
        name: Optional[str] = None,
    ) -> None:
        # Named per-entity slots replace themselves — a fleet of
        # ``every(..., name="fire")`` is not a flood.
        if name is not None:
            return
        now = time.monotonic()
        key = (id(owner) if owner is not None else None, site[0], site[1])
        bucket = self._every_sites.get(key)
        if bucket is None:
            bucket = []
            self._every_sites[key] = bucket
        bucket.append(now)
        cutoff = now - 1.0
        # In-place prune; sites are few.
        i = 0
        for t in bucket:
            if t >= cutoff:
                bucket[i] = t
                i += 1
        del bucket[i:]
        if len(self._every_sites) > _EVERY_SITES_SWEEP_AT:
            # Keys carry id(owner): a spawn / destroy churn leaves one per dead
            # actor. Drop sites idle for the whole window (bounded memory,
            # and a reused id() starts from an empty bucket).
            stale = [k for k, b in self._every_sites.items() if not b or b[-1] < cutoff]
            for k in stale:
                del self._every_sites[k]
                self._every_flood_warned.discard(k)
        if len(bucket) > EVERY_FLOOD_PER_SEC and key not in self._every_flood_warned:
            self._every_flood_warned.add(key)
            warnings.warn(
                f"every() created {len(bucket)} times in one second at "
                f"{site[0]}, line {site[1]}. Use name= so the timer replaces "
                f"itself, or schedule it from a mode body, not on_update.",
                stacklevel=3,
            )

    def _prepare_timed_handle(self, handle: Handle, world_dt: float) -> bool:
        """Shared prefix for every/after/wait/tween: live owner, parked, elapsed.

        Returns False when the handle should not fire this tick.
        """
        if handle._cancelled or handle._done:
            return False
        owner = handle._live_owner()
        if handle.owner is not None and owner is None:
            handle._cancel_for(_R_OWNER_GONE)
            return False
        if owner is not None and not getattr(owner, "active", True):
            return False
        if handle._paused or handle._held:
            return False
        scale = 1.0 if owner is None else getattr(owner, "_time_scale", 1.0)
        if scale != 1.0:
            if scale < 0.0:
                scale = 0.0
            dt_used = world_dt * scale
        else:
            dt_used = world_dt
        handle._elapsed += dt_used
        if handle._motion_readout:
            handle._last_dt = dt_used
            if dt_used > 0.0:
                handle._last_dx = 0.0
                handle._last_dy = 0.0
        return True

    def _tick_every(self, handle: Handle, world_dt: float) -> None:
        # every() stays live until cancelled — do not treat _done like once/tween.
        if handle._cancelled:
            return
        owner = handle._live_owner()
        if handle.owner is not None and owner is None:
            handle._cancel_for(_R_OWNER_GONE)
            return
        if owner is not None and not getattr(owner, "active", True):
            return
        if handle._paused:
            return
        scale = 1.0 if owner is None else getattr(owner, "_time_scale", 1.0)
        if scale != 1.0:
            if scale < 0.0:
                scale = 0.0
            handle._elapsed += world_dt * scale
        else:
            handle._elapsed += world_dt
        # ``every`` counts world seconds: a frame that covers several intervals
        # fires several times (30 FPS and 60 FPS give the same rate; a hitch
        # loses nothing). Bounded per tick by MAX_FRAME_DT / interval, the most
        # one capped world step can owe, so a stall cannot spiral; debt beyond
        # it (an uncapped ``clock.advance``, a time scale above 1) keeps only
        # its phase. Review 2026-10-09 S2-16.
        interval = handle.interval
        if not reached(handle._elapsed, interval):
            return
        fired = 0
        budget = 0                          # computed only when a frame owes more
        while True:
            handle._elapsed -= interval
            if handle._elapsed < 0.0:
                handle._elapsed = 0.0       # due by rounding only: no debt
            fired += 1
            if handle._elapsed >= interval:
                if not budget:
                    budget = _every_fire_budget(interval)
                if fired >= budget:
                    rem = handle._elapsed % interval
                    # A summed float leaves ``%`` a hair under ``interval``:
                    # that is the boundary, not one more fire past the
                    # budget (review 2026-10-09 W-T3, the PM8 class).
                    handle._elapsed = 0.0 if reached(rem, interval) else rem
            handle._fire_every()
            if not reached(handle._elapsed, interval):
                return
            # The callback may have cancelled, parked, paused or killed.
            if handle._cancelled or handle._paused:
                return
            owner = handle._live_owner()
            if handle.owner is not None and owner is None:
                return
            if owner is not None and not getattr(owner, "active", True):
                return

    def _tick_once(self, handle: Handle, world_dt: float) -> None:
        if not self._prepare_timed_handle(handle, world_dt):
            return
        if reached(handle._elapsed, handle.delay):
            handle._fire_once()

    def _tick_tween(self, handle: Handle, world_dt: float) -> None:
        if not self._prepare_timed_handle(handle, world_dt):
            return
        handle._tick_tween()

    def _tick_await(self, handle: Handle, world_dt: float) -> None:
        if handle._cancelled or handle._done:
            return
        owner = handle._live_owner()
        if handle.owner is not None and owner is None:
            handle._cancel_for(_R_OWNER_GONE)
            return
        if owner is not None and not getattr(owner, "active", True):
            return
        kind = handle.kind
        if kind == "until":
            handle._poll_until()
        elif kind == "parallel":
            handle._poll_parallel()
        elif kind == "record":
            handle._poll_record()
        else:
            handle._poll_race()

    def _tick_sound(self, handle: Handle, world_dt: float) -> None:
        if handle._cancelled or handle._done:
            return
        owner = handle._live_owner()
        if handle.owner is not None and owner is None:
            # Owner died without cancel_owner: same rule as destroy.
            self._end_implicitly(handle)
            if handle._cancelled:
                return
            owner = None
        # The voice keeps playing while its owner is parked (park does not
        # stop audio), so the Handle keeps reporting it; only an author
        # ``pause()`` (the mixer holds the voice) freezes it.
        parked = owner is not None and not getattr(owner, "active", True)
        if not handle._paused:
            scale = 1.0 if owner is None else getattr(owner, "_time_scale", 1.0)
            if scale < 0.0:
                scale = 0.0
            handle._elapsed += world_dt * scale
        pending = getattr(self, "_sound_finished_tick", None) or set()
        if handle._voice_id in pending:
            pending.discard(handle._voice_id)
            if parked:
                # Park promises no owned callbacks: hold ``on_done`` until the
                # owner resumes (review 2026-10-09 X-life-4).
                handle._end_held = True
                return
            handle._fire_once()
        elif handle._end_held and not parked:
            handle._end_held = False
            handle._fire_once()

    def _tick_idle(self) -> None:
        """The idle frame: no timers, scripts, modes or ``on_update``.

        Still (1) drops the dense owner snapshots — they hold owners strongly,
        so the last destroyed mode / ``on_update`` actor would otherwise stay
        in memory until some later process work — and (2) pumps an offline
        mixer that still has voices or queued commands, so a sound cancelled
        on the last busy tick (its owner destroyed) actually stops.
        """
        if self._mode_dense or self._update_dense:
            self._mode_dense = []
            self._update_dense = []
            self._mode_dirty = True
            self._update_dirty = True
        mixer = _offline_mixer_with_work()
        if mixer is not None:
            world_dt = float(getattr(_clock(), "dt", 0.0) or 0.0)
            if world_dt > 0.0:
                mixer.pump_dt(world_dt)
                mixer.take_finished()  # no sound handle is left to report to

    def tick(self) -> None:
        # Idle: no timers, scripts, modes, or on_update — skip clock/list work.
        if (
            not self._handles
            and not self._mode_owners
            and not self._update_owners
        ):
            self._tick_idle()
            return
        clock = _clock()
        world_dt = float(getattr(clock, "dt", 0.0) or 0.0)
        if world_dt < 0.0:
            world_dt = 0.0
        self._iterating = True
        try:
            if world_dt > 0.0:
                self._refresh_mode_dense()
                dead_modes = False
                for item in self._mode_dense:
                    if not getattr(item, "is_alive", True):
                        self._mode_owners.discard(item)
                        dead_modes = True
                        continue
                    if getattr(item, "_mode", None) is None:
                        continue
                    if not getattr(item, "active", True):
                        continue  # parked: mode_time freezes
                    scale = getattr(item, "_time_scale", 1.0)
                    if scale == 1.0:
                        item._mode_time = float(getattr(item, "_mode_time", 0.0)) + world_dt
                    else:
                        if scale < 0.0:
                            scale = 0.0
                        item._mode_time = float(getattr(item, "_mode_time", 0.0)) + world_dt * scale
                if dead_modes:
                    self._mode_dirty = True

            # Snapshot all four buckets up front. A handle created during this
            # tick's own fire callbacks (re-arm from `after`, `every`,
            # `tween(on_done=...)`, `then=`) must not become due until the
            # *next* tick — matching the "first tick next frame" rule already
            # true for collision/flush. Copying one bucket at a time would let
            # an after() created inside an every fire run in the same tick.
            every_s = list(self._every)
            once_s = list(self._once)
            tween_s = list(self._tween)
            await_s = list(self._await_family)

            # Tweens before timers (Laws T1): a timer as long as a tween made
            # with it sees the tween finished, its on_done run, and can start
            # the next one on the same field (R4-1: it read one step short,
            # and a re-tween dropped the first one's on_done).
            for handle in tween_s:
                self._tick_tween(handle, world_dt)
            for handle in every_s:
                self._tick_every(handle, world_dt)
            for handle in once_s:
                self._tick_once(handle, world_dt)
            for handle in await_s:
                self._tick_await(handle, world_dt)

            try:
                from .audio import tick_audio
                from .audio_mixer import get_mixer
                tick_audio(world_dt)
                self._sound_finished_tick = set(get_mixer().take_finished())
            except Exception:
                self._sound_finished_tick = set()
            carry = self._sound_carry
            if carry:
                # Voices a raising ``on_done`` left unprocessed last frame.
                self._sound_finished_tick |= carry
                self._sound_carry = set()
            # After tick_audio, so a sound handle created by that pump waits.
            sound_s = list(self._sound)
            try:
                for handle in sound_s:
                    self._tick_sound(handle, world_dt)
            except BaseException:
                # The finished voices not reached yet end next frame: one raising
                # ``on_done`` lost every other voice that ended this frame
                # (review 2026-10-09 S2-13).
                self._sound_carry = set(self._sound_finished_tick or ())
                raise
            finally:
                self._sound_finished_tick = None

            if self._tasks:
                # Snapshot, plus the tasks started during the walk (a mode
                # entered from another task's step is visited this tick too).
                batch = list(self._tasks)
                self._task_walk_extras = []
                # One watchdog window for the whole walk, opened at the first
                # task that is ready to resume (see _wd_window_open).
                window = False
                try:
                    while batch:
                        for handle in batch:
                            # Inlined _tick_task (one call per task per frame).
                            if handle._done:
                                continue
                            owner = handle._owner
                            if owner is not None and _is_entity(owner):
                                if not owner.is_alive:
                                    handle.cancel()        # quiet: the owner is dead
                                    continue
                                if not owner.active:
                                    continue               # parked: the body waits
                                scale = owner._time_scale
                                handle._elapsed += world_dt * scale if scale > 0.0 else 0.0
                            else:
                                handle._elapsed += world_dt
                            script = handle._task
                            awaited = script.waiting_on
                            if awaited is None or not (awaited._done or awaited._cancelled):
                                continue               # still waiting
                            if not window:
                                window = _watchdog_window_open()
                            script._advance()
                        batch = self._task_walk_extras
                        self._task_walk_extras = []
                finally:
                    if window:
                        _watchdog_window_close()
                self._task_walk_extras = None
            self._tick_on_update(world_dt)
            if world_dt > 0.0:
                self._warn_frozen_modes()
        finally:
            self._iterating = False
            self._task_walk_extras = None

    def _tick_on_update(self, world_dt: float) -> None:
        self._refresh_update_dense()
        dead = False
        current = [None]  # mutable cell for watchdog trip reporting

        def _run_all():
            nonlocal dead
            for item, fn, form in self._update_dense:
                current[0] = item
                if not getattr(item, "is_alive", True):
                    self._update_owners.discard(item)
                    dead = True
                    continue
                if not getattr(item, "active", True):
                    continue
                ts = getattr(item, "_time_scale", 1.0)
                if ts == 1.0:
                    dt = world_dt
                else:
                    if ts < 0.0:
                        ts = 0.0
                    dt = world_dt * ts
                _call_update(fn, form, item, dt)

        try:
            # One arm/disarm for the whole fleet — not per Entity (LINE tool cost).
            self._update_running = True
            try:
                _run_with_watchdog(_run_all, sync=True)
            finally:
                self._update_running = False
        except _Watchdog:
            item = current[0]
            warnings.warn(
                f"SCENA ERROR: on_update on {item!r} ran more than "
                f"{WATCHDOG_RESUME_S:g}s without returning — hook disabled "
                f"(likely a tight loop). Fix the spin or call "
                f"set_watchdog(False) for benchmarks.",
                stacklevel=2,
            )
            if item is not None:
                object.__setattr__(item, "_on_update", None)
                self._update_owners.discard(item)
                dead = True
        if dead:
            self._update_dirty = True

    def _owner_has_pending(self, item) -> bool:
        if getattr(item, "_on_update", None) is not None:
            return True
        body = getattr(item, "_mode_task", None)
        if body is not None and not body._done:
            return True                # the mode's body still runs (fast path)
        owned = self._by_owner.get(id(item))
        if not owned:
            return False
        for handle in owned:
            if handle.owner is item and not handle._cancelled and (
                handle.kind == "every" or not handle._done
            ):
                return True
        return False

    def _warn_frozen_modes(self) -> None:
        self._refresh_mode_dense()
        for item in self._mode_dense:
            if _is_entity(item) and not item.is_alive:
                continue
            if getattr(item, "_mode", None) is None:
                continue
            if getattr(item, "_frozen_warned", False):
                continue
            mode_time = float(getattr(item, "_mode_time", 0.0))
            if mode_time < FROZEN_MODE_S:
                continue        # too young to have been idle that long (the cheap exit)
            if self._owner_has_pending(item):
                continue
            # Idle since its last work ended in this mode, else since the
            # mode began.
            since = getattr(item, "_mode_idle_from", 0.0)
            if since > mode_time:
                since = 0.0
            if mode_time - since < FROZEN_MODE_S:
                continue
            object.__setattr__(item, "_frozen_warned", True)
            mode = item._mode
            warnings.warn(
                f"mode {getattr(mode, '__name__', mode)!r} on {item!r} has been "
                f"frozen for {FROZEN_MODE_S:.0f}s with nothing pending (no timer, "
                f"tween, async script, or on_update). Assign another mode or "
                f"start a timer / tween from the body.",
                stacklevel=2,
            )

    def reset(self) -> None:
        for handle in list(self._tasks):
            if handle._task is not None:
                handle._task.silent = True
        for handle in list(self._handles):
            handle.cancel()
        self._tasks.clear()
        self._task_walk_extras = None
        self._every.clear()
        self._once.clear()
        self._tween.clear()
        self._await_family.clear()
        self._sound.clear()
        self._handles.clear()
        self._by_owner.clear()
        self._named.clear()
        self._tweens.clear()
        self._sound_carry = set()
        self._mode_owners = _OrderedWeakSet()
        self._update_owners = _OrderedWeakSet()
        self._update_running = False
        self._update_pos: Dict[int, int] = {}
        self._mode_dense = []
        self._update_dense = []
        self._mode_dirty = False
        self._update_dirty = False
        self._every_sites.clear()
        self._every_flood_warned.clear()
        self._running = None
        self._iterating = False


def _offline_mixer_with_work():
    """The mixer if it is offline (no device) and has voices or commands."""
    from . import audio_mixer
    mixer = audio_mixer._mixer
    if mixer is None or not mixer.offline:
        return None
    if mixer.voices or mixer.queue._q:
        return mixer
    return None


_scheduler: Optional[Scheduler] = None


def get_scheduler() -> Scheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler()
    return _scheduler


def reset_process_scheduler() -> None:
    """Cancel every handle and async script. Tests call this in setUp; not an author API."""
    get_scheduler().reset()
    _reset_author_errors()
    try:
        from .audio import reset_audio
        reset_audio()
    except Exception:
        pass


def tick_processes() -> None:
    """Advance timers, tweens, async scripts, and ``on_update``. Tests call this after ``clock.advance``."""
    get_scheduler().tick()


@contextmanager
def owning(item, scope: str = SCOPE_ENTITY) -> Iterator[None]:
    """Bind bare ``after`` / ``every`` / ``tween`` / ``wait`` / … to ``item``."""
    t_owner = _owner_ctx.set(item)
    t_scope = _scope_ctx.set(scope)
    try:
        yield
    finally:
        _owner_ctx.reset(t_owner)
        _scope_ctx.reset(t_scope)


@contextmanager
def no_owner() -> Iterator[None]:
    """No ambient owner: for author hooks the engine calls synchronously
    (``setup()``, ``on_destroy``, ``@exit_mode``). Called from inside a mode
    body, they used to inherit that body's ``owning(actor, "mode")``, so a
    shot built in a wasp's mode had its own timers owned by the wasp's mode
    (review 2026-10-09 S2-1; Actors Design, Ownership)."""
    t_owner = _owner_ctx.set(None)
    t_scope = _scope_ctx.set(None)
    # Nor a running task: a hook called from a task's step is not the
    # task's work (its handles are not the task's children; wait() there
    # is refused like anywhere outside async code).
    sched = get_scheduler()
    running = sched._running
    sched._running = None
    try:
        yield
    finally:
        sched._running = running
        _owner_ctx.reset(t_owner)
        _scope_ctx.reset(t_scope)


def call_without_owner(fn: Callable, *args):
    """``fn(*args)`` under :func:`no_owner`, at no cost when no ambient owner
    is set (the common case: construction and destroy outside a mode body)."""
    if _owner_ctx.get() is None and _scope_ctx.get() is None:
        return fn(*args)
    with no_owner():
        return fn(*args)


# Actors whose ``on_destroy`` is running (innermost last). Work an
# ``on_destroy`` starts with a lambda over ``self`` is "after I am gone"
# work: it keeps the plain owner rule instead of dying with ``self`` (PA4).
_ON_DESTROY_RUNNING: List[object] = []


def run_on_destroy(hook: Callable, item) -> None:
    """Call an actor's ``on_destroy`` hook (no ambient owner; ``_fire_on_destroy``)."""
    _ON_DESTROY_RUNNING.append(item)
    try:
        call_without_owner(_invoke, hook, item)
    finally:
        _ON_DESTROY_RUNNING.pop()


def _closure_self(fn) -> Optional[object]:
    """The Entity a lambda / nested def closes over under the name ``self``
    (the method's own receiver), or None. A ``functools.partial`` is read
    through to its function. Only ``self``: a closure over another actor
    (``lambda: alvo.destroy()``) keeps its owner rule (PA4)."""
    func = getattr(fn, "func", None)
    if func is not None and getattr(fn, "args", None) is not None:
        own = getattr(func, "__self__", None)
        if _is_entity(own):
            return own
        fn = func
    code = getattr(fn, "__code__", None)
    if code is None:
        return None
    names = code.co_freevars
    if "self" not in names:
        return None
    try:
        value = fn.__closure__[names.index("self")].cell_contents
    except (AttributeError, IndexError, TypeError, ValueError):
        return None
    if not _is_entity(value):
        return None
    if _ON_DESTROY_RUNNING and any(x is value for x in _ON_DESTROY_RUNNING):
        return None
    return value


def _infer_owner(fn: Optional[Callable] = None) -> Tuple[object, str]:
    """Resolve owner/scope for bare ``after`` / ``every`` / ``wait`` / ``tween`` / …

    One rule: work started while a mode body is running is mode-scoped
    (dies on leave). Explicit ``e.after`` / ``e.every`` / ``e.tween`` bypass
    this via ``*_on`` (always entity). A bound method on a *different*
    Entity than the running mode stays entity-scoped on that other Entity
    (``after(0.4, bomb.destroy)`` from wasp's mode does not die with wasp).
    A closure over a method's ``self`` counts as that bound method
    (``_closure_self``, PA4).
    """
    ctx = _owner_ctx.get()
    self = None
    if fn is not None:
        self = getattr(fn, "__self__", None)
        if not _is_entity(self):
            # A lambda / nested def over a method's ``self`` is owned like
            # the bound method: ``after(0.1, lambda: self.set_color("red"))``
            # in ``on_update`` ends with the actor, as ``after(0.1,
            # self.piscar)`` does. As act work it outlived the actor and
            # reached it destroyed (review 2026-10-14 PA4).
            self = _closure_self(fn)
    # Bound method of another Entity → that Entity (entity-scoped).
    # Bound method of the *current* mode actor → still mode-scoped
    # (``after(0.4, self.shoot)`` inside formation dies when leaving).
    if _is_entity(self) and self is not ctx:
        return self, SCOPE_ENTITY
    if ctx is not None:
        return ctx, (_scope_ctx.get() or SCOPE_MODE)
    if _is_entity(self):
        return self, SCOPE_ENTITY
    # Inside an ownerless task's step: its scope (a game task's work stays
    # game work after the top level ended).
    scope = _scope_ctx.get()
    if scope == SCOPE_GAME:
        return None, SCOPE_GAME
    return None, SCOPE_ACT


def _require_then_owner(then, owner, *, call_name: str) -> None:
    if then is None:
        return
    if owner is None:
        raise TypeError(
            f"{call_name} then= needs an owner (call it on the actor, "
            f"or from a mode body). Script-level {call_name}(..., then=) is not allowed."
        )


def _start_after(
    delay: float,
    fn: Optional[Callable],
    *,
    then=None,
    on_done=None,
    name: Optional[str] = None,
    owner=None,
    scope: str = SCOPE_ACT,
) -> Handle:
    fn, then = _fn_and_then(fn, then, call_name="after", on_done=on_done)
    if then is None and fn is None:
        raise TypeError(
            "after() needs a function, on_done=, or then= (mode to enter when this finishes)."
        )
    _require_then_owner(then, owner, call_name="after")
    delay = seconds(delay, "after() delay")
    if delay < 0.0:
        raise ValueError("after() delay must be >= 0")
    handle = Handle._make(
        kind="after", delay=delay, fn=fn, then=then, owner=owner, scope=scope, name=name,
    )
    return get_scheduler().add(handle)


def _start_every(
    interval: float,
    fn: Callable,
    *,
    name: Optional[str] = None,
    owner=None,
    scope: str = SCOPE_ACT,
) -> Handle:
    _callable_or_none_error(fn, "every()")
    interval = seconds(interval, "every() interval")
    if interval <= 0.0:
        raise ValueError(
            "every() interval must be > 0 — for every frame, use "
            "on_update (Entity) or update(dt) (script)"
        )
    handle = Handle._make(
        kind="every", interval=interval, fn=fn, owner=owner, scope=scope, name=name,
    )
    return get_scheduler().add(handle)


def after(
    delay: float,
    fn: Optional[Callable] = NO_FN,
    *,
    then: Optional[Callable] = None,
    on_done: Optional[Callable] = None,
    name: Optional[str] = None,
) -> Union[Handle, Callable]:
    """Do ``fn`` / ``on_done=`` once after ``delay`` seconds, or enter ``then=``.

    ``fn`` and ``on_done=`` are the same call-channel (``after(d, boom)`` ≡
    ``after(d, on_done=boom)``). ``then=`` is the mode to enter when this finishes
    (needs an owner). Passing both a call-channel and ``then=`` is a ``TypeError``.

    Decorator form (``fn`` / ``on_done`` / ``then`` omitted) registers the decorated
    function and attaches the live handle as ``func.handle``::

        @after(2.0)
        def boom():
            ...
        # boom.handle.cancel()  # optional

    On an Entity-subclass method the decorator only tags; construct arms an
    entity-scoped timer via ``after_on``.

    Ownership (same rule as ``wait`` / ``tween`` / timed pose): called from
    inside a mode body → mode-scoped (dies on leave). ``e.after(...)`` →
    always entity-scoped (survives mode change; dies on ``destroy``). Bound
    method on another Entity → that Entity; a lambda / nested def over a
    method's ``self`` → that Entity, like the bound method. Else act.

    Args:
        delay: World seconds to wait (>= 0).
        fn: Function to call (same channel as ``on_done=``). Omit to use ``after`` as a
            decorator.
        then: Mode to enter when the timer fires (needs an owner).
        on_done: Function to call when the timer fires.
        name: Slot name: a new ``after`` with the same name (and owner) replaces the old
            one.
    """
    if _SOLVER_READING:
        refuse_if_solver_reading('after()')
    refuse_called_function("after", fn)
    if fn is NO_FN:
        fn = None
    if fn is None and then is None and on_done is None:
        def decorator(func: Callable) -> Callable:
            _claim_decorator_role(func, "timer")
            if _in_executing_class_body():
                # Tag only — Entity construct binds per instance.
                func._after_spec = (delay, name)
                return func
            owner, scope = _infer_owner(func)
            handle = _start_after(delay, func, name=name, owner=owner, scope=scope)
            func.handle = handle
            return func
        return decorator
    owner, scope = _infer_owner(
        fn if fn is not None else (on_done if on_done is not None else then)
    )
    return _start_after(
        delay, fn, then=then, on_done=on_done, name=name, owner=owner, scope=scope,
    )


def every(
    interval: float,
    fn: Optional[Callable] = NO_FN,
    *,
    name: Optional[str] = None,
) -> Union[Handle, Callable]:
    """Call ``fn`` every ``interval`` seconds of world time.

    Interval must be > 0. Per-frame work is ``on_update`` (Entity) or script
    ``update(dt)`` — both receive ``dt`` — not ``every(0, ...)``.

    Named timers replace themselves: ``every(0.8, drop, name="spawn")`` after
    ``@every(1.2, name="spawn")`` is one timer, not two.

    Decorator form attaches the live handle as ``func.handle`` (cancel via
    ``drop_star.handle.cancel()``). On an Entity-subclass method the decorator
    only tags; construct arms an entity-scoped timer via ``every_on``.

    Ownership: same ambient-mode rule as :func:`after`. Use ``e.every(...)``
    when the timer must survive a mode change.
    """
    if _SOLVER_READING:
        refuse_if_solver_reading('every()')
    refuse_called_function("every", fn)
    if fn is NO_FN:
        fn = None
    if fn is None:
        def decorator(func: Callable) -> Callable:
            _claim_decorator_role(func, "timer")
            if _in_executing_class_body():
                # Tag only — Entity construct binds per instance. Avoids a
                # act-scoped timer for the unbound function.
                func._every_spec = (interval, name)
                return func
            owner, scope = _infer_owner(func)
            handle = _start_every(interval, func, name=name, owner=owner, scope=scope)
            if name is None:
                try:
                    site = (func.__code__.co_filename, int(func.__code__.co_firstlineno))
                except (AttributeError, TypeError, ValueError):
                    site = _call_site(1)
                get_scheduler().note_every_site(site, owner=owner, name=name)
            func.handle = handle
            return func
        return decorator
    owner, scope = _infer_owner(fn)
    if name is None:
        get_scheduler().note_every_site(_call_site(1), owner=owner, name=name)
    return _start_every(interval, fn, name=name, owner=owner, scope=scope)


def after_on(
    item,
    delay: float,
    fn: Optional[Callable] = NO_FN,
    *,
    then: Optional[Callable] = None,
    on_done: Optional[Callable] = None,
    name: Optional[str] = None,
) -> Union[Handle, Callable]:
    """``Entity.after`` implementation (entity-scoped)."""
    if _SOLVER_READING:
        refuse_if_solver_reading('after()')
    refuse_called_function("after", fn)
    if fn is NO_FN:
        fn = None
    if fn is None and then is None and on_done is None:
        def decorator(func: Callable) -> Callable:
            handle = _start_after(
                delay, func, name=name, owner=item, scope=SCOPE_ENTITY,
            )
            func.handle = handle
            return func
        return decorator
    return _start_after(
        delay, fn, then=then, on_done=on_done, name=name, owner=item, scope=SCOPE_ENTITY,
    )


def every_on(
    item,
    interval: float,
    fn: Optional[Callable] = NO_FN,
    *,
    name: Optional[str] = None,
) -> Union[Handle, Callable]:
    """``Entity.every`` implementation (entity-scoped)."""
    if _SOLVER_READING:
        refuse_if_solver_reading('every()')
    refuse_called_function("every", fn)
    if fn is NO_FN:
        fn = None
    if fn is None:
        def decorator(func: Callable) -> Callable:
            handle = _start_every(
                interval, func, name=name, owner=item, scope=SCOPE_ENTITY,
            )
            func.handle = handle
            return func
        return decorator
    if name is None:
        get_scheduler().note_every_site(_call_site(2), owner=item, name=name)
    return _start_every(interval, fn, name=name, owner=item, scope=SCOPE_ENTITY)


def _check_task_fn(fn, what: str) -> str:
    """What ``run_task`` was given: ``"async"`` (an async def, bound method or
    partial) or ``"lambda"`` (its call must return a coroutine). Raises, with
    the fix, for anything else — before anything registers."""
    if inspect.iscoroutine(fn):
        name = getattr(fn, "__name__", "fn")
        fn.close()                     # no "never awaited" on top of this error
        raise TypeError(
            f"{what} takes the async function, not a call of it: write "
            f"run_task({name}), or run_task(lambda: {name}(...)) to pass "
            f"arguments. {name}() only made a coroutine, and nothing in it ran."
        )
    _callable_or_none_error(fn, what)
    name = getattr(fn, "__name__", None) or type(fn).__name__
    if getattr(getattr(fn, "__func__", fn), "_is_mode", False):
        raise TypeError(
            f"{name} is a mode (@on_mode): enter it with self.mode = self.{name}. "
            f"{what} runs a job alongside the modes, not a mode."
        )
    if is_async_callable(fn):
        return "async"
    if name == "<lambda>":
        return "lambda"
    raise TypeError(
        f"{what} needs an async def (a sequence that awaits), got {name}(), a "
        f"plain function. Call {name}() directly, or schedule it with after(...)."
    )


def _spawn_task_coro(fn, form: str, owner):
    """Call ``fn`` the way ``after`` calls a callback (the owner as the first
    argument when ``fn`` takes one and is not a bound method); return the
    coroutine."""
    n = _argcount(fn)
    extra: list = []
    if owner is not None and not hasattr(fn, "__self__"):
        extra = [owner]
    result = fn(*extra[:n])
    if inspect.iscoroutine(result):
        return result
    close = getattr(result, "aclose", None)
    if close is not None:              # an async generator (``yield``)
        raise TypeError(
            "run_task() needs an async def that awaits, not an async generator "
            "(a function with yield)."
        )
    if form == "lambda":
        raise TypeError(
            f"run_task(lambda: ...) must return a call of an async function, "
            f"like run_task(lambda: show(box)); the lambda returned "
            f"{type(result).__name__}."
        )
    raise TypeError(
        f"run_task() expected {getattr(fn, '__name__', fn)!r} to return a coroutine."
    )


def _start_run_task(fn, form: str, owner, scope: str, name: Optional[str]) -> Handle:
    sched = get_scheduler()
    if owner is not None and _is_entity(owner) and not getattr(owner, "is_alive", True):
        # Its body never starts; the handle comes back cancelled (T6).
        return sched.add(Handle._make(kind="task", owner=owner, scope=scope, fn=fn, name=name))
    coro = _spawn_task_coro(fn, form, owner)   # a refused lambda registers nothing
    return sched.start_task(owner, coro, scope=scope, fn=fn, name=name)


def run_task(fn, *, name: Optional[str] = None) -> Handle:
    """Run an ``async def`` alongside everything else: a task.

    ``run_task(show)`` runs ``show()`` up to its first ``await`` now, then
    continues it in later frames, like an async mode but without a mode:
    from a button's ``on_click``, a collision, the top of the file.
    ``run_task(lambda: show(box, 2))`` passes arguments. The owner is the
    one ``after`` would pick: a method of an actor (or a lambda over its
    ``self``) → that actor; inside a mode body → that mode (it ends with
    the mode); otherwise the act (the game, from the top of the file). Use
    ``e.run_task(fn)`` to make ``e`` the owner.

    Work the task starts (``after``, ``wait``, moves, sounds, other tasks)
    is the task's: cancelling the task ends it too. A task that finishes
    leaves that work running.

    Args:
        fn: an ``async def`` (or a lambda that calls one). A function marked
            ``@on_mode`` is refused: enter a mode with ``self.mode =``.
        name: a slot like ``after``'s: a new task with the same ``name``
            cancels the one running (and its work) — restart semantics.

    Returns:
        A ``Handle``: ``await`` it for the task's return value, ``cancel()``
        it, pass it to ``parallel`` / ``race``; ``.done`` / ``.elapsed``.
    """
    if _SOLVER_READING:
        refuse_if_solver_reading("run_task()")
    form = _check_task_fn(fn, "run_task()")
    owner, scope = _infer_owner(fn)
    return _start_run_task(fn, form, owner, scope, name)


def run_task_on(item, fn, *, name: Optional[str] = None) -> Handle:
    """``run_task`` owned by ``item`` (``item.run_task(fn)``): entity-scoped."""
    if _SOLVER_READING:
        refuse_if_solver_reading("run_task()")
    form = _check_task_fn(fn, "run_task()")
    return _start_run_task(fn, form, item, SCOPE_ENTITY, name)


def _require_number(value, *, what: str, minimum: Optional[float] = None) -> float:
    """Finite number. ``bool`` is not a number. ``minimum`` is a magnitude floor."""
    from .validate import number, fixed_magnitude
    if minimum == 0.0:
        return fixed_magnitude(value, what)
    out = number(value, what)
    if minimum is not None and out < minimum:
        raise ValueError(f"{what} must be >= {minimum}, got {out}")
    return out


def _require_handle(value, *, what: str, index: Optional[int] = None) -> Handle:
    if not isinstance(value, Handle):
        where = f" argument {index}" if index is not None else ""
        raise TypeError(
            f"{what}{where} expected a Handle (from after / wait / until / "
            f"move_to(time=) / tween), got {type(value).__name__}"
        )
    return value


def _require_running_script(what: str):
    """``wait`` / ``until`` / ``parallel`` / ``race`` need a driven async script."""
    script = get_scheduler()._running
    if script is None:
        raise TypeError(
            f"{what} only works inside an async mode or a task "
            f"(or a helper they await). In update / on_update / @collide / a "
            f"sync mode, start the waits as a task (run_task(fn)) or use "
            f"after(...)."
        )
    return script


def wait(delay: float) -> Handle:
    """Suspend an async script for ``delay`` seconds of world time.

    Must be awaited: ``await wait(0.4)``. Valid inside the async mode the
    engine is driving, or a helper that mode ``await``s. Calling with no
    running script is ``TypeError``. Ignoring the handle is an author error
    (unlike fire-and-forget ``after``).
    """
    delay = _require_number(delay, what="wait() delay", minimum=0.0)
    _require_running_script("wait()")
    owner, scope = _infer_owner()
    site = _call_site(1)
    handle = Handle._make(
        kind="wait",
        delay=delay,
        owner=owner,
        scope=scope,
        must_await=True,
        await_hint=f"await wait({delay})",
        site=site,
    )
    return get_scheduler().add(handle)


def _start_until(pred, *, await_hint: str, site, what: str = "until()") -> Handle:
    from .state import Container, FieldRef, as_payload, refuse_held_payload
    if callable(pred) and not isinstance(pred, Container):
        # An async predicate returns a (truthy) coroutine: the wait would end
        # on its first poll.
        refuse_async(pred, what=what)
        fn = pred
    elif isinstance(pred, Container):
        refuse_held_payload(pred, "until({cell})")
        cell = pred
        fn = lambda: bool(as_payload(cell))
    elif isinstance(pred, FieldRef):
        ref = pred                      # ``until(st["done"])``: re-read each frame
        ref.value                       # a missing cell raises here, not frames later
        fn = lambda: bool(ref.value)
    else:
        raise TypeError(
            f"until() expected a function or a reactive cell, got "
            f"{'None' if pred is None else type(pred).__name__}. "
            f"Wrap it: until(lambda: cond), or pass a st cell with brackets: "
            f"until(st[\"done\"]) (st.done reads the value since 0.8.0); "
            f"for group emptiness use until_empty(group) instead."
        )
    _require_running_script(what)
    owner, scope = _infer_owner()
    handle = Handle._make(
        kind="until",
        owner=owner,
        scope=scope,
        must_await=True,
        await_hint=await_hint,
        site=site,
        pred=fn,
    )
    get_scheduler().add(handle)
    handle._poll_until()
    return handle


def until(pred: Callable[[], bool]) -> Handle:
    """Suspend an async script until ``pred()`` is true. Must be awaited.

    Valid inside the async mode the engine is driving, or a helper that
    mode ``await``s: ``await until(lambda: ship.hp <= 0)``.
    """
    return _start_until(pred, await_hint="await until(...)", site=_call_site(1))


def until_empty(group_or_id) -> Handle:
    """Suspend an async script until a named group has no live members.

    ``await until_empty("wasp")`` or ``await until_empty(group["wasp"])``.
    The only async-wait spelling for emptiness — do not pass ``.empty`` to
    ``until()`` (that is already a bool, not a predicate). Same script rule
    as ``wait`` / ``until``.

    Args:
        group_or_id: A group tag (``"wasp"``) or ``group["wasp"]``.
    """
    if isinstance(group_or_id, str):
        gid = group_or_id
        g = getattr(builtins, "group", None)
        if g is not None:
            g[gid]  # a typo warns here, once, at the author's call
        pred = lambda: _live_group_empty(gid)
    elif getattr(group_or_id, "is_live", False):
        g = group_or_id
        pred = lambda: g.empty
    else:
        raise TypeError(
            "until_empty() expected a group id string or a live group[...], "
            f"got {type(group_or_id).__name__}."
        )
    return _start_until(
        pred,
        await_hint="await until_empty(...)",
        site=_call_site(1),
        what="until_empty()",
    )


def _live_group_empty(gid: str) -> bool:
    """Poll for ``until_empty("name")``. Reads the registry, not ``group[...]``.

    The author lookup ``group[name]`` warns on a near-miss name that is not in
    ``group_map`` — and the registry drops a group's bucket when its last
    member leaves. Polling through it warned "No group 'inimigo'. Did you mean
    'tiro_inimigo'?" at the exact moment the fleet was cleared.
    """
    g = getattr(builtins, "group", None)
    if g is None:
        return True
    registry = g._registry
    if registry.has_group_formula(gid):
        return bool(g[gid].empty)
    return registry.group_live_count(gid) == 0


def parallel(*handles: Handle) -> Handle:
    """Wait until every handle is done. Must be awaited. Cancelling cancels the rest.

    Same script rule as ``wait``: async mode or a helper that mode ``await``s.
    """
    if not handles:
        raise TypeError("parallel() needs at least one Handle")
    kids = tuple(_require_handle(h, what="parallel()", index=i) for i, h in enumerate(handles))
    _require_running_script("parallel()")
    for child in kids:
        child._awaited = True
    owner, scope = _infer_owner()
    site = _call_site(1)
    handle = Handle._make(
        kind="parallel",
        owner=owner,
        scope=scope,
        must_await=True,
        await_hint="await parallel(...)",
        site=site,
        children=kids,
    )
    get_scheduler().add(handle)
    handle._poll_parallel()
    return handle


def race(*handles: Handle) -> Handle:
    """Wait until the first handle completes; cancel the others. Must be awaited.

    The await result is the index of the winner (0-based). Same script
    rule as ``wait``.
    """
    if not handles:
        raise TypeError("race() needs at least one Handle")
    kids = tuple(_require_handle(h, what="race()", index=i) for i, h in enumerate(handles))
    _require_running_script("race()")
    for child in kids:
        child._awaited = True
    owner, scope = _infer_owner()
    site = _call_site(1)
    handle = Handle._make(
        kind="race",
        owner=owner,
        scope=scope,
        must_await=True,
        await_hint="await race(...)",
        site=site,
        children=kids,
    )
    get_scheduler().add(handle)
    handle._poll_race()
    return handle


def _claim_active(handle: Optional["Handle"]) -> bool:
    return handle is not None and not handle._done and not handle._cancelled


def _release_process_driver(handle: "Handle") -> None:
    """Drop duration-scoped claims when a tween/move_along finishes or cancels."""
    for entry in getattr(handle, "_claimed_targets", ()) or ():
        kind, obj, name = entry
        if kind == "field":
            claims = obj.__dict__.get("_process_field_claims")
            if claims is not None and claims.get(name) is handle:
                del claims[name]
                if not claims:
                    obj.__dict__.pop("_process_field_claims", None)
        elif kind == "node":
            if getattr(obj, "_active_process_claim", None) is handle:
                obj.__dict__["_active_process_claim"] = None
    handle._claimed_targets = ()
    handle._claim_kind = None
    handle._claim_label = None
    handle._claim_writes = None


def claim_process_driver(handle: "Handle", *targets, kind: str = "tween") -> None:
    """Mark pose/field targets as driven by ``handle`` until finish/cancel.

    ``targets`` may be Containers (Point / Attribute) or FieldRefs
    (``shape["radius"]``). Mid-flight ``@=`` on a claimed target raises
    immediately at the link site — see ``refuse_if_process_driven``.
    """
    from .state import Container, FieldRef

    claimed: List[Tuple[str, Any, Optional[str]]] = []
    for t in targets:
        if t is None:
            continue
        if isinstance(t, FieldRef):
            owner = t.owner
            name = t.name
            claims = owner.__dict__.setdefault("_process_field_claims", {})
            claims[name] = handle
            claimed.append(("field", owner, name))
        elif isinstance(t, Container):
            t.__dict__["_active_process_claim"] = handle
            claimed.append(("node", t, None))
    handle._claimed_targets = tuple(claimed)
    handle._claim_kind = kind
    _hold_if_on_held_part(handle, targets)


def refuse_if_process_driven(node) -> None:
    """Raise ``LinkedAttributeError`` if ``node`` (or an ancestor / field) has an active process claim."""
    from .state import LinkedAttributeError, ScalarAnchor, motion_conflict_message
    from .entity import entity_label, part_path

    # Field claim via ScalarAnchor parent map
    if isinstance(node, ScalarAnchor):
        parent = node._scalar_parent
        claims = getattr(parent, "_process_field_claims", None)
        if claims:
            h = claims.get(node._scalar_name)
            if _claim_active(h):
                raise LinkedAttributeError(
                    motion_conflict_message(
                        h, subject=entity_label(parent), part=str(node._scalar_name),
                    )
                )

    cur = node
    while cur is not None:
        h = getattr(cur, "_active_process_claim", None)
        if _claim_active(h):
            raise LinkedAttributeError(
                motion_conflict_message(
                    h, subject=entity_label(cur), part=part_path(cur),
                )
            )
        claims = getattr(cur, "_process_field_claims", None)
        if claims and getattr(node, "_attr_name", None) in claims:
            h = claims.get(node._attr_name)
            if _claim_active(h) and (node is cur or getattr(node, "_owner", None) is cur):
                raise LinkedAttributeError(
                    motion_conflict_message(
                        h, subject=entity_label(cur), part=str(node._attr_name),
                    )
                )
        cur = getattr(cur, "_owner", None)

    # A whole-object link drives every part under it: a claim on any of them
    # (a running turn claims the points it writes, and the heading field)
    # refuses it too (GX6 in Testing Design: the next tick raised).
    for sub in node._iter_subtree():
        if sub is node:
            claims = getattr(sub, "_process_field_claims", None)
            if claims:
                for name, h in claims.items():
                    if _claim_active(h):
                        raise LinkedAttributeError(
                            motion_conflict_message(h, subject=entity_label(sub), part=str(name)))
            continue
        h = getattr(sub, "_active_process_claim", None)
        if _claim_active(h):
            raise LinkedAttributeError(
                motion_conflict_message(h, subject=entity_label(node), part=part_path(sub)))
        claims = getattr(sub, "_process_field_claims", None)
        if claims:
            for name, h in claims.items():
                if _claim_active(h):
                    raise LinkedAttributeError(
                        motion_conflict_message(h, subject=entity_label(node), part=str(name)))


def process_claims_on(part) -> List["Handle"]:
    """Every distinct active process Handle claiming ``part`` (no first-match).

    ``part`` is a Container or FieldRef. A Container counts claims anywhere in
    its subtree **and** on its owner chain (a claim on an ancestor writes the
    part too). Used by the pointer hold, which must hold every writer — not
    only the first one ``active_process_claim_on`` finds.
    """
    from .state import FieldRef

    found: List["Handle"] = []
    seen = set()

    def add(h) -> None:
        if _claim_active(h) and id(h) not in seen:
            seen.add(id(h))
            found.append(h)

    if isinstance(part, FieldRef):
        claims = getattr(part.owner, "_process_field_claims", None)
        if claims:
            add(claims.get(part.name))
        return found
    for node in part._iter_subtree():
        add(getattr(node, "_active_process_claim", None))
        claims = getattr(node, "_process_field_claims", None)
        if claims:
            for h in claims.values():
                add(h)
    cur = getattr(part, "_owner", None)
    while cur is not None:
        d = getattr(cur, "__dict__", None)
        if d:
            add(d.get("_active_process_claim"))
        cur = getattr(cur, "_owner", None)
    return found


# -- Pointer hold ----------------------------------------------------------
#
# A pointer hold (drag past the threshold, or a wheel tick while pressed)
# *holds* every motion Handle that claims the parts the hold writes: the job
# does not advance (``Handle._held``) until the hold ends. ``_paused`` is not
# touched — it stays the author's ``pause()`` / ``resume()`` switch. State lives
# on the held shape (``_hold_parts`` / ``_hold_handles`` in its ``__dict__``) so
# ``draggable = False`` and ``destroy()`` can end the hold without the pointer
# manager. See Shapes Design — Persistent drivers vs linked pose.


def _hold_one(shape, handle: "Handle") -> None:
    if handle._held or not _claim_active(handle):
        return
    handle._held = True
    if handle._motion_readout:
        handle._last_dt = 0.0
    d = shape.__dict__
    held = d.get("_hold_handles")
    if held is None:
        held = d["_hold_handles"] = []
    held.append(handle)


def _hold_part_key(part):
    from .state import FieldRef
    if isinstance(part, FieldRef):
        return (id(part.owner), part.name)
    return id(part)


def hold_claims_on(shape, parts) -> None:
    """Start (or extend) ``shape``'s pointer hold over ``parts``.

    Holds every active claim on those parts now, and remembers the parts so a
    motion claimed on them later in the same hold is held at claim time.
    """
    parts = tuple(p for p in parts if p is not None)
    if not parts:
        return
    d = shape.__dict__
    known = d.get("_hold_parts") or ()
    keys = {_hold_part_key(k) for k in known}
    # ``shape["angle"]`` is a fresh FieldRef per call: dedupe by what it names.
    d["_hold_parts"] = known + tuple(p for p in parts if _hold_part_key(p) not in keys)
    for part in parts:
        for h in process_claims_on(part):
            _hold_one(shape, h)


def release_hold(shape) -> None:
    """End ``shape``'s pointer hold: every held Handle runs again. Idempotent."""
    d = getattr(shape, "__dict__", None)
    if not d:
        return
    held = d.pop("_hold_handles", None)
    d.pop("_hold_parts", None)
    for h in held or ():
        h._held = False


def _hold_if_on_held_part(handle: "Handle", targets) -> None:
    """A motion claimed on a part an active hold writes is held from birth."""
    from .state import FieldRef

    for t in targets:
        if t is None:
            continue
        cur = t.owner if isinstance(t, FieldRef) else t
        while cur is not None:
            d = getattr(cur, "__dict__", None)
            parts = d.get("_hold_parts") if d else None
            if parts:
                for part in parts:
                    if any(h is handle for h in process_claims_on(part)):
                        _hold_one(cur, handle)
                        return
            cur = getattr(cur, "_owner", None)


def active_process_claim_on(part) -> Optional["Handle"]:
    """Return an active process Handle claiming ``part`` (Container or FieldRef), if any."""
    from .state import FieldRef

    if isinstance(part, FieldRef):
        claims = getattr(part.owner, "_process_field_claims", None)
        if claims:
            h = claims.get(part.name)
            if _claim_active(h):
                return h
        return None
    # Whole-subtree: any claimed node under part
    for node in part._iter_subtree():
        h = getattr(node, "_active_process_claim", None)
        if _claim_active(h):
            return h
        claims = getattr(node, "_process_field_claims", None)
        if claims:
            for h in claims.values():
                if _claim_active(h):
                    return h
    return None


def _validate_timed(*, time, ease, then, on_done, owner=None,
                    what: str = "tween time=") -> tuple:
    """Every refusal ``_start_tween`` makes, run before a timed verb touches
    anything (the same-property replace, the ``face=`` snap): a rejected
    ``move_to(…, time=-1)`` cancelled the move already in flight (review
    2026-10-09 S2-5). Returns ``(on_done, then, duration, ease_fn)`` for
    ``_start_tween(checked=…)``, so nothing is checked twice."""
    on_done, then = _fn_and_then(None, then, call_name="tween", on_done=on_done)
    if then is not None:
        _require_then_owner(then, owner, call_name="tween")
    duration = seconds(time, what)
    if duration < 0.0:
        raise ValueError(f"{what} must be >= 0")
    return on_done, then, duration, resolve_ease(ease, what="ease")


def _empty_group_timed(kwargs: dict) -> Optional[Handle]:
    """A timed verb on an empty group (``group["tiros"].move_by(…, time=0.5)``
    with no shot alive): the verb's timing and ``on_done``, with nothing to
    move. A timer, not a tween on a stand-in actor (which built and
    registered a ``Blank`` per call, ~0.3 ms: review 2026-10-09 S9-8).
    Returns None for the rare forms the caller still routes through the
    stand-in (``then=`` / ``loops=`` / ``yoyo=``)."""
    if kwargs.get("then") is not None or kwargs.get("loops", 1) not in (1, None) \
            or kwargs.get("yoyo"):
        return None
    owner, scope = _infer_owner()
    time = kwargs.get("time")
    if _check_speed(time, kwargs.get("speed"), "tween") is not None:
        time = 0.0                          # nothing to move: no distance to cover
    checked = _validate_timed(
        time=time, ease=kwargs.get("ease", "linear"), then=None,
        on_done=kwargs.get("on_done"), owner=owner)
    on_done, _then, duration, _ease = checked
    handle = Handle._make(kind="after", delay=duration, fn=on_done, owner=owner, scope=scope)
    return get_scheduler().add(handle)


def _start_tween(
    *,
    duration: float,
    ease: Ease,
    write: Callable,
    tween_key=None,
    tween_keys=None,
    then=None,
    on_done=None,
    owner=None,
    scope: str = SCOPE_ACT,
    name: Optional[str] = None,
    loops: int = 1,
    yoyo: bool = False,
    ride=None,
    motion_readout: bool = False,
    claim_targets=(),
    claim_kind: str = "tween",
    claim_verb: Optional[str] = None,
    target=None,
    what: str = "tween time=",
    checked: Optional[tuple] = None,
    speed: Optional[float] = None,
) -> Handle:
    """``target=``, when given, is the Entity this tween actually writes to
    (e.g. the shape a ``move_to`` moves) — checked every tick independently
    of ``owner`` (who *scheduled* the tween, which may be a Director or the
    running mode's actor). Without it, a Director-owned tween on a
    destroyed target kept running (and still fired ``on_done``) because
    only the Director's liveness was ever checked.
    """
    if checked is not None:
        # The verb ran ``_validate_timed`` before touching anything.
        on_done, then, duration, ease_fn = checked
        if then is not None:
            _require_then_owner(then, owner, call_name="tween")
    else:
        on_done, then = _fn_and_then(None, then, call_name="tween", on_done=on_done)
        if then is not None:
            _require_then_owner(then, owner, call_name="tween")
        duration = seconds(duration, what)
        if duration < 0.0:
            raise ValueError(f"{what} must be >= 0")
        ease_fn = resolve_ease(ease, what="ease")
    handle = Handle._make(
        kind="tween",
        delay=duration,
        fn=ease_fn,
        then=then,
        on_done=on_done,
        owner=owner,
        scope=scope,
        name=name,
        tween_write=write,
        tween_key=tween_key,
        tween_keys=tween_keys,
        loops=loops,
        yoyo=yoyo,
        ride=ride,
        motion_readout=motion_readout,
        target=target if _is_entity(target) else None,
    )
    if claim_targets:
        verb = claim_verb or claim_kind
        handle._claim_label = _motion_label(verb, duration, loops, speed=speed)
        # ``tween(part, …)`` places every tick; the pose verbs push deltas.
        handle._claim_writes = "sets" if verb == "tween" else "pushes"
        claim_process_driver(handle, *claim_targets, kind=claim_kind)
    return get_scheduler().add(handle)


def _motion_label(verb: str, duration: float, loops: int,
                  speed: Optional[float] = None) -> str:
    """The motion call as the author wrote it: ``move_by(time=2, loops="forever")``
    (``speed=`` when the author gave the rate)."""
    if speed is not None:
        text = f"{verb}(speed={float(speed):g}"
    else:
        text = f"{verb}(time={float(duration):g}"
    if loops == -1:
        text += ', loops="forever"'
    elif loops != 1:
        text += f", loops={loops}"
    return text + ")"


def _as_xy(to) -> Tuple[float, float]:
    """Snapshot a tween location: numbers, or one point-like (Graphic, mouse)."""
    from .shapes import _xy_of
    try:
        return _xy_of(to, required=True)
    except TypeError:
        raise TypeError(
            "tween destination expected a point — (x, y), Point, Vec2, "
            f"or a Graphic — got {type(to).__name__}"
        ) from None


def _center_pose_key(shape) -> tuple:
    """The tween key of a shape's position, for every timed move and for
    ``tween(shape.center, …)`` (``_pose_target_key``): ``(id(shape),
    "center")``. It never reads ``center`` (a cold Derivate would wake: D3),
    and it does not depend on whether anything read it yet. The old key was
    ``id(shape)`` while the center was cold and ``id(center)`` after any
    read, so a read between two moves let both run at once (review
    2026-10-09 S2-7)."""
    return (id(shape), "center")


def _pose_target_key(target) -> object:
    """``tween(target, …)`` on a pose Container: a shape's ``center`` /
    ``centroid`` shares the timed moves' key; any other Container keys on
    itself."""
    d = target.__dict__
    owner = d.get("_owner")
    if owner is not None and d.get("_attr_name") in ("center", "centroid") \
            and _is_entity(owner):
        return _center_pose_key(owner)
    return id(target)


def _move_claim_targets(shape) -> tuple:
    """Defining position part(s) a timed move/move_along claim should protect.

    Reuses ``shape._parts_written_by_drag()`` — the same "what does
    ``_move_to`` / ``_move_by`` actually write" answer already used to guard
    ``draggable=True`` — instead of always claiming ``.center``. For a model
    whose position is Defining `p1`/`p2` (a ``Line`` built ``p1=``/``p2=``),
    ``center`` is a Derivate that the move does not write at all: claiming it
    both forces it live (see ``_center_pose_key``) and leaves the actually
    written parts (`p1`/`p2`) unprotected — a concurrent ``p1 @= ...`` during
    the tween would not raise, silently fighting the tween instead of the
    loud ``LinkedAttributeError`` every other persistent driver gets.
    Falls back to ``(getattr(shape, "center", shape),)`` for anything without
    a ``_parts_written_by_drag`` override (e.g. ``SpatialFx`` — not a
    ``Shape``) — same as previous behavior, not a regression there.
    """
    fn = getattr(shape, "_parts_written_by_drag", None)
    if callable(fn):
        parts = fn()
        if parts:
            return tuple(parts)
    return (getattr(shape, "center", shape),)


def _note_idle_from(owner) -> None:
    """``owner``'s async body or last owned handle just ended in its mode: its
    idle stretch may start now. The frozen-mode warning counts idle time from
    ``_mode_idle_from`` (AC7; Actors Design, "past FROZEN_MODE_S"); entering a
    mode resets it to 0 (``Entity._enter_mode``). Kept on the owner, like
    ``_frozen_warned``: nothing else holds it."""
    try:
        object.__setattr__(owner, "_mode_idle_from", owner._mode_time)
    except (AttributeError, TypeError):
        pass        # an owner with no slot for it: counted from the mode's start


def _preempt_tween_keys(*keys, slot=None, quiet: bool = False) -> None:
    """Same-kind replace: cancel in-flight handles on these tween keys (with warning).

    ``slot`` is the new call's ``(owner, name)``: an old handle in that same
    ``name=`` slot is the replacement the Guia promises ("substitui o
    anterior"), so it is cancelled without the warning. ``quiet``: the new
    call is a timed pose verb (``move_to`` / ``move_by`` / a turn / a scale),
    whose retarget is the documented last-wins (a puzzle tile, a hover lift:
    persona probes R3-3); no warning. The warning is located at the author's
    line (it pointed into ``shapes.py``) and names the ``name=`` way out.
    """
    if not keys:
        return
    sched = get_scheduler()
    named = None
    if slot is not None and slot[1] is not None:
        named = sched._named.get((id(slot[0]) if slot[0] is not None else None, slot[1]))
    seen = set()
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        old = sched._tweens.get(key)
        if old is not None and old is named and _claim_active(old):
            old._cancel_for(_R_NAME)        # the name= slot replaces it: no warning
            continue
        if old is not None and _claim_active(old):
            if not quiet:
                from .entity import _frame_outside_scena
                site = _frame_outside_scena()
                msg = (f"tween/move_along on the same property replaces a previous "
                       f"in-flight {old._claim_kind or old.kind} handle: the earlier one "
                       f"stops where it is. If that is meant, give both calls the same "
                       f"name= (tween(..., name=\"lift\")), and the new one replaces "
                       f"the old quietly.")
                if site is not None:
                    warnings.warn_explicit(msg, RuntimeWarning, site.filename, site.lineno)
                else:
                    warnings.warn(msg, RuntimeWarning, stacklevel=3)
            old._cancel_for(_R_PREEMPTED)


def _ensure_tween_writable(target, *, force: bool) -> None:
    from .shapes import _ensure_writable
    _ensure_writable(target, "tween", force=force)


def tween(
    target,
    to,
    *,
    time: float,
    ease: Ease = "linear",
    then: Optional[Callable] = None,
    on_done: Optional[Callable] = None,
    force: bool = False,
    name: Optional[str] = None,
    loops: object = 1,
    yoyo: bool = False,
    start=None,
) -> Handle:
    """Interpolate ``target`` (Attribute or pose Container) to ``to`` over ``time`` seconds.

    ``to`` must match the shape of the current value: number, flat tuple/list,
    ``Vec2``, ``Color``, or a pose destination ``(x, y)`` / Point / Vec2.
    Attribute / FieldRef paths interpolate via ``lerp`` (fails immediately on
    incompatible types). Pose Containers keep the allocation-free 2-float path.

    ``start=`` overrides the implicit current-value snapshot (same shape as
    ``to``). Omit to begin from the value at call time. Lap 1 only — later
    ``loops`` / ``yoyo`` legs keep today's start/end swap.

    ``ease`` is a name (``linear``, ``ease_in``, ``ease_out``, ``ease_in_out``,
    ``quad``, ``bounce``, ``elastic``, …) or a callable ``[0,1] → float``.
    ``then=`` is the mode to enter when this finishes; ``on_done=`` calls a function
    (same channel as ``fn`` on ``after`` — not both with ``then=``).
    ``loops=`` / ``yoyo=``: same vocabulary as ``move_along`` (``1``, ``N``,
    ``\"forever\"``; ``yoyo`` swaps start/end each odd lap).

    Two tweens on the same property: the later cancels the earlier.
    Linked targets refuse, or unlink with a warning when ``force=True``.
    """
    if _SOLVER_READING:
        refuse_if_solver_reading('tween()')
    owner, scope = _infer_owner()
    return _tween_target(
        target, to, time=time, ease=ease, then=then, on_done=on_done, force=force,
        owner=owner, scope=scope, name=name, loops=loops, yoyo=yoyo, start=start,
    )


def tween_on(
    item,
    target,
    to,
    *,
    time: float,
    ease: Ease = "linear",
    then: Optional[Callable] = None,
    on_done: Optional[Callable] = None,
    force: bool = False,
    name: Optional[str] = None,
    loops: object = 1,
    yoyo: bool = False,
    start=None,
) -> Handle:
    """``Entity.tween`` implementation (entity-scoped)."""
    if _SOLVER_READING:
        refuse_if_solver_reading('tween()')
    return _tween_target(
        target, to, time=time, ease=ease, then=then, on_done=on_done, force=force,
        owner=item, scope=SCOPE_ENTITY, name=name, loops=loops, yoyo=yoyo, start=start,
    )


def _entity_written_by(target):
    """The Entity a ``tween()`` target writes to (a FieldRef's owner, or the
    actor that owns an Attribute / pose node), or ``None`` (a ``st`` cell).
    It gets the dead-target rule the timed pose verbs have: destroyed →
    the tween cancels quietly, no write, no ``on_done`` (review S2-2)."""
    from .entity import Entity
    from .state import FieldRef
    node = target.owner if isinstance(target, FieldRef) else target
    seen = 0
    while node is not None and seen < 64:
        if isinstance(node, Entity):
            return node
        node = getattr(node, "_owner", None)
        seen += 1
    return None


# Appearance links a tween does not animate (``line_width`` / ``alpha`` do).
_FLAG_LINKS = frozenset({"visible", "flip_x", "flip_y"})
_UNTWEENED_LINKS = frozenset({"color", "fill", "line", "background"}) | _FLAG_LINKS


def _tween_target(
    target,
    to,
    *,
    time: float,
    ease: Ease,
    then,
    on_done,
    force: bool,
    owner,
    scope: str,
    name: Optional[str],
    loops: object = 1,
    yoyo: bool = False,
    start=None,
) -> Handle:
    from .state import Attribute, Container, FieldRef, refuse_held_payload
    from .shapes import Point
    from .easing import lerp

    if target is None:
        raise TypeError("tween() needs a target Attribute or pose Container")
    # Before the same-property preempt below cancels the target's tween.
    get_scheduler().refuse_game_task_clash(owner, scope, name, "tween")

    is_fieldref = isinstance(target, FieldRef)
    is_attribute = isinstance(target, Attribute)
    is_pose = isinstance(target, Point) or (
        isinstance(target, Container)
        and hasattr(target, "x")
        and hasattr(target, "y")
        and hasattr(target, "_takein")
    )
    if not (is_fieldref or is_attribute or is_pose):
        raise TypeError(
            'tween() needs a bracket handle (obj["field"], st["t"]) or a pose '
            f'Container, got a plain {type(target).__name__}. st.t reads the '
            'value (since 0.8.0); st["t"] is the cell.'
        )
    if is_pose:
        refuse_held_payload(target, "tween({cell}, …)")
    if is_fieldref and target.name in _UNTWEENED_LINKS and target.name in getattr(
            type(target.owner), "_scena_target_only", ()):
        # A paint or a flag links (``@=``) but does not tween: a color has no
        # interpolation space chosen here, a flag has no in-between.
        owner = getattr(target.owner, "name", "obj")
        hint = (f"tween a color cell and link to it: st.c = {owner}.{target.name}; "
                f"tween(st['c'], Color('blue'), time=…); {owner}['{target.name}'] @= "
                f"lambda: st.c" if target.name not in _FLAG_LINKS else
                f"set it with {owner}.{target.name} = …, or link it: "
                f"{owner}['{target.name}'] @= lambda: …")
        raise TypeError(f"tween() cannot animate {owner}['{target.name}']: {hint}.")

    n_loops = _require_loop_kwargs(
        loops=loops, yoyo=yoyo, time=time, call_name="tween",
    )
    checked = _validate_timed(time=time, ease=ease, then=then, on_done=on_done,
                              owner=owner)
    # Same-kind replace before writability — free the claim so probe succeeds.
    slot = (owner, name)
    if is_fieldref:
        _preempt_tween_keys((id(target.owner), target.name), slot=slot)
    elif is_attribute:
        _preempt_tween_keys(id(target), slot=slot)
    else:
        _preempt_tween_keys(_pose_target_key(target), slot=slot)
    _ensure_tween_writable(target, force=force)

    if is_fieldref:
        from_val = target.value if start is None else start
        # Fail fast on incompatible start/to (before the first tick).
        lerp(from_val, to, 0.0)

        def write(u, ref=target, s=from_val, e=to):
            value = lerp(s, e, u)
            slots = getattr(ref.owner, "_field_slots", None)
            if slots is not None:
                slot = slots().get(ref.name)
                if getattr(slot, "magnitude", False):
                    value = clamp_magnitude(value)
                hi = getattr(slot, "maximum", None)
                if (
                    hi is not None
                    and isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and value > hi
                ):
                    value = float(hi)
            ref.owner._write_field(ref.name, value)

        return _start_tween(checked=checked,
            duration=time, ease=ease, write=write, tween_key=(id(target.owner), target.name),
            then=then, on_done=on_done, owner=owner, scope=scope, name=name,
            loops=n_loops, yoyo=yoyo, claim_targets=(target,), claim_kind="tween",
            target=_entity_written_by(target),
        )

    if is_attribute:
        from_val = target.value if start is None else start
        lerp(from_val, to, 0.0)

        def write(u, attr=target, s=from_val, e=to):
            attr._takein(lerp(s, e, u))

        return _start_tween(checked=checked,
            duration=time, ease=ease, write=write, tween_key=id(target),
            then=then, on_done=on_done, owner=owner, scope=scope, name=name,
            loops=n_loops, yoyo=yoyo, claim_targets=(target,), claim_kind="tween",
            target=_entity_written_by(target),
        )

    if is_pose:
        if start is None:
            sx, sy = float(target.x), float(target.y)
        else:
            sx, sy = _as_xy(start)
        ex, ey = _as_xy(to)

        def write(u, node=target, x0=sx, y0=sy, x1=ex, y1=ey):
            node._takein((x0 + (x1 - x0) * u, y0 + (y1 - y0) * u))

        return _start_tween(checked=checked,
            duration=time, ease=ease, write=write, tween_key=_pose_target_key(target),
            then=then, on_done=on_done, owner=owner, scope=scope, name=name,
            loops=n_loops, yoyo=yoyo, claim_targets=(target,), claim_kind="tween",
            target=_entity_written_by(target),
        )

    raise TypeError(
        'tween() needs a bracket handle (obj["field"]) or a pose Container, '
        f'got a plain {type(target).__name__}'
    )


def shortest_delta_deg(start: float, end: float) -> float:
    """Signed shortest arc in degrees (CCW+). Exact 180° ties break CCW (+180)."""
    d = (float(end) - float(start)) % 360.0
    if d > 180.0:
        d -= 360.0
    return d


def _pose_owner_scope(item) -> Tuple[object, str]:
    owner, scope = _infer_owner()
    if owner is None:
        return item, SCOPE_ENTITY
    return owner, scope


def _heading_from_delta(dx: float, dy: float) -> Optional[float]:
    """Travel heading in degrees, or ``None`` when the delta is ~zero."""
    if math.hypot(float(dx), float(dy)) <= 1e-9:
        return None
    return math.degrees(math.atan2(float(dy), float(dx)))


def _face_to_heading(shape, heading: float, *, about=None, force: bool = False) -> None:
    """Snap ``shape.angle`` to ``heading`` via shortest arc (settle-only)."""
    cur = float(shape._rotation_value())   # Defining only (D3)
    step = shortest_delta_deg(cur, float(heading))
    if step != 0.0:
        if about is not None:
            # A snap is placement: the orbit about ``about`` is not motion.
            from .entity import _rotate_as_placement
            _rotate_as_placement(shape.rotate_by, step, about=about, force=force)
        else:
            shape.rotate_by(step, about=about, force=force)


def apply_face_delta(shape, dx: float, dy: float, *, about=None, force: bool = False) -> None:
    """Opt-in face for instant ``move_to`` / ``move_by``. Zero delta holds rotation.

    ``about=`` (default center) is the face-rotation pivot — same point
    ``move_to(..., about=)`` just placed on the target, so it stays put.
    """
    heading = _heading_from_delta(dx, dy)
    if heading is None:
        return
    _face_to_heading(shape, heading, about=about, force=force)


def timed_move_to(
    shape,
    to_x: Optional[float],
    to_y: Optional[float],
    *,
    about=None,
    time: Optional[float] = None,
    speed: Optional[float] = None,
    ease: Ease = "linear",
    then=None,
    on_done=None,
    force: bool = False,
    loops: object = 1,
    yoyo: bool = False,
    face: bool = False,
) -> Handle:
    from .collision import note_collider_motion

    speed = _check_speed(time, speed, "move_to")
    n_loops = _require_loop_kwargs(
        loops=loops, yoyo=yoyo, time=time, speed=speed, call_name="move_to",
    )
    if about is None:
        # The point the instant ``_move_to`` places: a sheet-anchored sprite's
        # ``center``, not its art frame (the old probe jumped it there first).
        origin = getattr(shape, "_move_to_xy", None)
        px, py = origin() if origin is not None else shape._pivot_xy(None)
    else:
        px, py = shape._pivot_xy(about)
    x1 = px if to_x is None else float(to_x)
    y1 = py if to_y is None else float(to_y)
    if speed is not None:
        # The distance is the frozen travel, read before anything moves.
        time = _speed_duration(speed, math.hypot(x1 - px, y1 - py))
    checked = _validate_timed(time=time, ease=ease, then=then, on_done=on_done,
                              owner=shape, what="move_to time=")
    key = _center_pose_key(shape)
    # Same-kind replace before writability probe.
    _preempt_tween_keys(key, quiet=True)
    # Probe writability at the call with the writer the ticks use (``_move_by``):
    # ``_move_to`` to the current place returned before its gate, so the
    # refusal came from a tick, after part of the move (GX4 in Testing Design).
    shape._move_by(0.0, 0.0, force=force)
    owner, scope = _pose_owner_scope(shape)
    dx = x1 - px
    dy = y1 - py
    applied = [0.0, 0.0]
    bound = [None]
    do_face = bool(face)
    heading0 = _heading_from_delta(dx, dy) if do_face else None
    if do_face and heading0 is not None:
        _preempt_tween_keys((id(shape), "angle"), quiet=True)
        _face_to_heading(shape, heading0, about=about, force=force)
    keys = (key, (id(shape), "angle")) if (do_face and heading0 is not None) else (key,)

    def write(
        u, s=shape, ddx=dx, ddy=dy, box=applied, f=force,
        note=note_collider_motion, hb=bound, base=heading0, facing=do_face,
        ab=about,
    ):
        tx, ty = ddx * u, ddy * u
        step_x, step_y = tx - box[0], ty - box[1]
        if step_x != 0.0 or step_y != 0.0:
            s._move_by(step_x, step_y, force=f)
            note(s, step_x, step_y)
            box[0], box[1] = tx, ty
        if facing and base is not None:
            heading = base
            h = hb[0]
            if h is not None and h._yoyo and (h._lap % 2) == 1:
                heading = (heading + 180.0) % 360.0
            _face_to_heading(s, heading, about=ab, force=f)
        h = hb[0]
        if h is not None:
            h._last_dx += step_x
            h._last_dy += step_y

    handle = _start_tween(checked=checked,
        duration=time, ease=ease, write=write, tween_keys=keys,
        then=then, on_done=on_done, owner=owner, scope=scope,
        loops=n_loops, yoyo=yoyo, motion_readout=True,
        claim_targets=(
            *_move_claim_targets(shape),
            *([shape["angle"]] if (do_face and heading0 is not None) else []),
        ),
        claim_kind="tween", claim_verb="move_to",
        target=shape,
        what="move_to time=",
        speed=speed,
    )
    bound[0] = handle
    return handle


def timed_move_by(
    shape,
    dx: float,
    dy: float,
    *,
    time: Optional[float] = None,
    speed: Optional[float] = None,
    ease: Ease = "linear",
    then=None,
    on_done=None,
    force: bool = False,
    loops: object = 1,
    yoyo: bool = False,
    face: bool = False,
) -> Handle:
    """Interpolate a frozen cartesian delta (same tween_key as ``timed_move_to``)."""
    from .collision import note_collider_motion

    speed = _check_speed(time, speed, "move_by")
    n_loops = _require_loop_kwargs(
        loops=loops, yoyo=yoyo, time=time, speed=speed, call_name="move_by",
    )
    dx = float(dx)
    dy = float(dy)
    if speed is not None:
        time = _speed_duration(speed, math.hypot(dx, dy))
    checked = _validate_timed(time=time, ease=ease, then=then, on_done=on_done,
                              owner=shape)
    key = _center_pose_key(shape)
    _preempt_tween_keys(key, quiet=True)
    # Probe writability on the instant path.
    shape._move_by(0.0, 0.0, force=force)
    applied = [0.0, 0.0]
    owner, scope = _pose_owner_scope(shape)
    bound = [None]
    do_face = bool(face)
    heading0 = _heading_from_delta(dx, dy) if do_face else None
    if do_face and heading0 is not None:
        _preempt_tween_keys((id(shape), "angle"), quiet=True)
        _face_to_heading(shape, heading0, force=force)
    keys = (key, (id(shape), "angle")) if (do_face and heading0 is not None) else (key,)

    def write(
        u, s=shape, ddx=dx, ddy=dy, box=applied, f=force,
        note=note_collider_motion, hb=bound, base=heading0, facing=do_face,
    ):
        tx, ty = ddx * u, ddy * u
        step_x, step_y = tx - box[0], ty - box[1]
        if step_x != 0.0 or step_y != 0.0:
            s._move_by(step_x, step_y, force=f)
            note(s, step_x, step_y)
            box[0], box[1] = tx, ty
        if facing and base is not None:
            heading = base
            h = hb[0]
            if h is not None and h._yoyo and (h._lap % 2) == 1:
                heading = (heading + 180.0) % 360.0
            _face_to_heading(s, heading, force=f)
        h = hb[0]
        if h is not None:
            h._last_dx += step_x
            h._last_dy += step_y

    handle = _start_tween(checked=checked,
        duration=time, ease=ease, write=write, tween_keys=keys,
        then=then, on_done=on_done, owner=owner, scope=scope,
        loops=n_loops, yoyo=yoyo, motion_readout=True,
        claim_targets=(
            *_move_claim_targets(shape),
            *([shape["angle"]] if (do_face and heading0 is not None) else []),
        ),
        claim_kind="tween", claim_verb="move_by",
        target=shape,
        speed=speed,
    )
    bound[0] = handle
    return handle


def _probe_rotate_writable(shape, *, about, force: bool, verb: str) -> None:
    """Formula check for a timed rotate, at the call (not on the first tick).

    Instant ``rotate_by(0)`` returns early, so it cannot serve as the probe.
    Same refuse / ``force=`` unlink as the instant verb: rotation, plus the
    pose parts when a pivot other than center moves them.
    """
    from .shapes import _ensure_writable
    parts_fn = getattr(shape, "_parts_written_by_wheel_rotate", None)
    parts = tuple(parts_fn()) if callable(parts_fn) else (shape["angle"],)
    if about is not None:
        parts += _move_claim_targets(shape)
    # The instant verb's pivot rule: a point on the pivot is not moved by a
    # turn, so it may stay linked (a Circle whose center follows something
    # turns about it; the timed turn refused it: GX17 in Testing Design).
    pivot = shape._pivot_xy(about)
    for part in parts:
        _ensure_writable(part, verb, force=force, pivot=pivot)


def _pose_claim_targets(shape, field: str, gate) -> tuple:
    """What a timed turn / scale claims: its pose field and every part its
    ticks write (the call's gate, recorded; points on the pivot excluded).
    It claimed only the field, so a link on a written point, or a whole
    ``@=``, was accepted mid-motion and the next tick raised (GX6)."""
    from .shapes import _gate_parts
    out = [shape[field]]
    for part in _gate_parts(gate):
        if not any(part is o for o in out):
            out.append(part)
    return tuple(out)


def timed_rotate_to(
    shape,
    value: float,
    *,
    time: Optional[float] = None,
    speed: Optional[float] = None,
    ease: Ease = "linear",
    then=None,
    on_done=None,
    about=None,
    force: bool = False,
    loops: object = 1,
    yoyo: bool = False,
) -> Handle:
    speed = _check_speed(time, speed, "rotate_to")
    n_loops = _require_loop_kwargs(
        loops=loops, yoyo=yoyo, time=time, speed=speed, call_name="rotate_to",
    )
    start = float(shape._rotation_value())
    end = float(value)
    delta = shortest_delta_deg(start, end)
    if speed is not None:
        time = _speed_duration(speed, delta)        # degrees per second
    checked = _validate_timed(time=time, ease=ease, then=then, on_done=on_done,
                              owner=shape)
    _preempt_tween_keys((id(shape), "angle"), quiet=True)
    _probe_rotate_writable(shape, about=about, force=force, verb="rotate_to")
    applied = [0.0]
    owner, scope = _pose_owner_scope(shape)

    def write(u, s=shape, d=delta, box=applied, ab=about, f=force, goal=end):
        if u == 1.0:
            # The end stores exactly the target, as the instant form does: the
            # shortest arc from 400 to 30 reached 390 (Q2 in Testing Design).
            # The rest of the arc plus the whole turns is one instant rotate_to.
            s.rotate_to(goal, about=ab, force=f)
            box[0] = d
            return
        target = d * u
        step = target - box[0]
        if step != 0.0:
            s.rotate_by(step, about=ab, force=f)
            box[0] = target

    return _start_tween(checked=checked,
        duration=time, ease=ease, write=write,
        tween_key=(id(shape), "angle"),
        then=then, on_done=on_done, owner=owner, scope=scope,
        loops=n_loops, yoyo=yoyo,
        claim_targets=_pose_claim_targets(shape, "angle", lambda: _probe_rotate_writable(
            shape, about=about, force=False, verb="rotate_to")),
        claim_kind="tween", claim_verb="rotate_to",
        target=shape,
        speed=speed,
    )


def timed_rotate_by(
    shape,
    angle: float,
    *,
    time: Optional[float] = None,
    speed: Optional[float] = None,
    ease: Ease = "linear",
    then=None,
    on_done=None,
    about=None,
    force: bool = False,
    loops: object = 1,
    yoyo: bool = False,
) -> Handle:
    speed = _check_speed(time, speed, "rotate_by")
    n_loops = _require_loop_kwargs(
        loops=loops, yoyo=yoyo, time=time, speed=speed, call_name="rotate_by",
    )
    delta = float(angle)
    if speed is not None:
        time = _speed_duration(speed, delta)        # degrees per second
    checked = _validate_timed(time=time, ease=ease, then=then, on_done=on_done,
                              owner=shape)
    _preempt_tween_keys((id(shape), "angle"), quiet=True)
    _probe_rotate_writable(shape, about=about, force=force, verb="rotate_by")
    applied = [0.0]
    owner, scope = _pose_owner_scope(shape)

    def write(u, s=shape, d=delta, box=applied, ab=about, f=force):
        target = d * u
        step = target - box[0]
        if step != 0.0:
            s.rotate_by(step, about=ab, force=f)
            box[0] = target

    return _start_tween(checked=checked,
        duration=time, ease=ease, write=write,
        tween_key=(id(shape), "angle"),
        then=then, on_done=on_done, owner=owner, scope=scope,
        loops=n_loops, yoyo=yoyo,
        claim_targets=_pose_claim_targets(shape, "angle", lambda: _probe_rotate_writable(
            shape, about=about, force=False, verb="rotate_by")),
        claim_kind="tween", claim_verb="rotate_by",
        target=shape,
        speed=speed,
    )


def _probe_scale_writable(shape, end: float, *, about, force: bool, verb: str) -> None:
    """The instant scale's checks at the call, toward the end value (the ticks
    write ``scale_to`` steps toward it): a refusal raised from a later tick,
    after part of the motion ran (GX4 in Testing Design)."""
    gate = getattr(shape, "_scale_gate", None)
    if gate is None:
        return                              # not a pose-scaled kind (an fx, a camera)
    from .shapes import _scale_gate_at_call
    _scale_gate_at_call(shape, value=end, about=about, force=force, verb=verb)


def _scale_claim_targets(shape, about) -> tuple:
    gate = getattr(shape, "_scale_gate", None)
    if gate is None:
        return (shape["scale"],)
    return _pose_claim_targets(shape, "scale", lambda: gate(about, False))


def timed_scale_to(
    shape,
    value: float,
    *,
    time: float,
    ease: Ease = "linear",
    then=None,
    on_done=None,
    about=None,
    force: bool = False,
    loops: object = 1,
    yoyo: bool = False,
) -> Handle:
    n_loops = _require_loop_kwargs(
        loops=loops, yoyo=yoyo, time=time, call_name="scale_to",
    )
    checked = _validate_timed(time=time, ease=ease, then=then, on_done=on_done,
                              owner=shape)
    _preempt_tween_keys((id(shape), "scale"), quiet=True)
    start = float(shape.scale)
    end = fixed_magnitude(value, "scale", hint=HINT_SCALE)
    _probe_scale_writable(shape, end, about=about, force=force, verb="scale_to")
    owner, scope = _pose_owner_scope(shape)

    def write(u, s=shape, a=start, b=end, ab=about, f=force):
        s.scale_to(clamp_magnitude(a + (b - a) * u), about=ab, force=f)

    return _start_tween(checked=checked,
        duration=time, ease=ease, write=write,
        tween_key=(id(shape), "scale"),
        then=then, on_done=on_done, owner=owner, scope=scope,
        loops=n_loops, yoyo=yoyo,
        claim_targets=_scale_claim_targets(shape, about),
        claim_kind="tween", claim_verb="scale_to",
        target=shape,
    )


def timed_scale_by(
    shape,
    factor: float,
    *,
    time: float,
    ease: Ease = "linear",
    then=None,
    on_done=None,
    about=None,
    force: bool = False,
    loops: object = 1,
    yoyo: bool = False,
) -> Handle:
    """Interpolate a frozen scale factor (same tween_key as ``timed_scale_to``)."""
    n_loops = _require_loop_kwargs(
        loops=loops, yoyo=yoyo, time=time, call_name="scale_by",
    )
    checked = _validate_timed(time=time, ease=ease, then=then, on_done=on_done,
                              owner=shape)
    _preempt_tween_keys((id(shape), "scale"), quiet=True)
    start = float(shape.scale)
    end = start * fixed_magnitude(factor, "scale", hint=HINT_SCALE)
    _probe_scale_writable(shape, end, about=about, force=force, verb="scale_by")
    owner, scope = _pose_owner_scope(shape)

    def write(u, s=shape, a=start, b=end, ab=about, f=force):
        s.scale_to(clamp_magnitude(a + (b - a) * u), about=ab, force=f)

    return _start_tween(checked=checked,
        duration=time, ease=ease, write=write,
        tween_key=(id(shape), "scale"),
        then=then, on_done=on_done, owner=owner, scope=scope,
        loops=n_loops, yoyo=yoyo,
        claim_targets=_scale_claim_targets(shape, about),
        claim_kind="tween", claim_verb="scale_by",
        target=shape,
    )


def timed_move_along(
    shape,
    target,
    *,
    time: Optional[float] = None,
    speed: Optional[float] = None,
    ease: Ease = "linear",
    span=(0.0, 1.0),
    phase: float = 0.0,
    loops: object = 1,
    yoyo: bool = False,
    face: bool = False,
    at=None,
    then=None,
    on_done=None,
    force: bool = False,
):
    """Travel along a Track / Shape outline via motion-channel deltas."""
    from .collision import note_collider_motion
    from .track import Track, RideState, _point_xy_static, _resolve_move_along_target
    from .shapes import Point as ShapePoint, Shape

    if time is None and speed is None:
        raise TypeError(
            "move_along needs time= (one lap, in seconds) or speed= (units per "
            "second along the track). Write move_along(track, time=2) or "
            "move_along(track, speed=120)."
        )
    speed = _check_speed(time, speed, "move_along")
    n_loops = _require_loop_kwargs(
        loops=loops, yoyo=yoyo, time=time, speed=speed, call_name="move_along",
    )
    span0, span1 = float(span[0]), float(span[1])
    phase = float(phase)
    if speed is None:
        time = seconds(time, "move_along time=")
        if time < 0.0:
            raise ValueError("move_along time= must be >= 0")

    key = _center_pose_key(shape)
    _preempt_tween_keys(key, *((id(shape), "angle"),) if face else ())
    # Probe writability (same refuse / unlink as move_to).
    shape._move_by(0.0, 0.0, force=force)

    target = _resolve_move_along_target(target)

    path = None
    floating = False
    wrap = False

    from .entity import scena_kind
    if isinstance(target, Track) or scena_kind(target) == "Track":  # reload-safe
        path = target
        path._ensure_samples()
        # A ``reversed()`` view's own copies of the host's fields go stale:
        # read the host (review 2026-10-09 S6-2).
        floating = bool(path._pose_host().is_floating)
        # Forever without yoyo sawtooths via wrap; yoyo reverses instead (open
        # paths must not wrap or u=1 becomes 0 and snaps away from the end).
        wrap = bool(path._table_host()._closed) or (n_loops < 0 and not yoyo)
    elif isinstance(target, ShapePoint) or (
        isinstance(target, (tuple, list)) and len(target) >= 2
        and not isinstance(target, Shape)
    ):
        raise TypeError(
            "move_along target expected Track, Shape, or preset string; "
            "slide to a point with move_to(..., time=). "
            f"got {type(target).__name__}"
        )
    elif isinstance(target, Shape):
        # Live outline: wrap as a live Track(shape). Off the draw list —
        # the source Shape is the author-visible object.
        path = Track(target, _register=False)
        path._visible = False
        path._ensure_samples()
        floating = False
        wrap = bool(path._closed) or (n_loops < 0 and not yoyo)
    else:
        raise TypeError(
            "move_along target expected Track, Shape, or preset string, "
            f"got {type(target).__name__}"
        )

    if speed is not None:
        # One lap covers the span window of the track as it is now (a track
        # that grows later keeps this duration, like move_to's frozen target).
        time = _speed_duration(speed, float(path.length) * abs(span1 - span0))

    u0 = span0 + phase
    if wrap:
        u0 = u0 % 1.0
        if u0 < 0.0:
            u0 += 1.0
    else:
        u0 = 0.0 if u0 < 0.0 else (1.0 if u0 > 1.0 else u0)

    if at is not None:
        if not floating:
            raise TypeError(
                "move_along(..., at=) is only for a floating track. "
                "Wrap as Track(source, floating=True)."
            )
        at_x, at_y = _point_xy_static(at)
        lx0, ly0 = path.local_at(u0)
        pose = path._pose_host()
        rot = float(pose._rotation)
        sc = float(pose._scale)
        from .curves import apply_pose
        posed_x, posed_y = apply_pose(
            lx0, ly0, cx=0.0, cy=0.0, rotation_deg=rot, scale=sc,
        )
        root_x, root_y = at_x - posed_x, at_y - posed_y
    elif floating:
        lx0, ly0 = path.local_at(u0)
        pose = path._pose_host()
        rot = float(pose._rotation)
        sc = float(pose._scale)
        from .curves import apply_pose
        tx, ty = apply_pose(lx0, ly0, cx=0.0, cy=0.0, rotation_deg=rot, scale=sc)
        cx, cy = shape._center_xy()
        root_x, root_y = cx - tx, cy - ty
    else:
        root_x, root_y = 0.0, 0.0

    ride = RideState(
        shape, path,
        floating=floating, root_x=root_x, root_y=root_y,
        span0=span0, span1=span1, phase=phase, face=bool(face), wrap=wrap,
    )
    if floating:
        # Anchoring the track later (a placement, ``is_floating = False``)
        # switches this ride to the track's place (KN9).
        path._pose_host()._list_floating_ride(ride)
    # Start on the track: first delta is from the rider's current pose to u0.
    cx0, cy0 = shape._center_xy()
    ride.prev_x, ride.prev_y = cx0, cy0
    wx, wy = ride.world_at(u0)
    dx0, dy0 = wx - cx0, wy - cy0
    if dx0 != 0.0 or dy0 != 0.0:
        shape._move_by(dx0, dy0, force=force)
        note_collider_motion(shape, dx0, dy0)
    ride.prev_x, ride.prev_y = wx, wy
    if face:
        heading = ride.world_angle(u0)
        cur = float(shape._rotation_value())
        step = shortest_delta_deg(cur, heading)
        if step != 0.0:
            shape.rotate_by(step, force=force)

    key = _center_pose_key(shape)
    keys = (key,)
    if face:
        keys = (key, (id(shape), "angle"))
    owner, scope = _pose_owner_scope(shape)
    bound = [None]

    def write(u, r=ride, s=shape, f=force, note=note_collider_motion, do_face=bool(face), hb=bound):
        # Source death: freeze last table, keep travelling; cancel only if never baked.
        if r.path is not None and not r._path_alive():
            if not r.freeze_last():
                raise RuntimeError("move_along: track destroyed before first sample")
        uu = r.map_u(u)
        try:
            x, y = r.world_at(uu)
        except RuntimeError:
            raise
        px, py = r.prev_x, r.prev_y
        dx, dy = x - px, y - py
        if dx != 0.0 or dy != 0.0:
            s._move_by(dx, dy, force=f)
            note(s, dx, dy)
        r.prev_x, r.prev_y = x, y
        if do_face:
            heading = r.world_angle(uu)
            # Path tangent points along increasing u; reverse travel (span back
            # or yoyo odd lap) faces the opposite way.
            reverse = (r.span1 - r.span0) < 0.0
            h = hb[0]
            if h is not None and h._yoyo and (h._lap % 2) == 1:
                reverse = not reverse
            if reverse:
                heading = (heading + 180.0) % 360.0
            cur = float(s._rotation_value())
            step = shortest_delta_deg(cur, heading)
            if step != 0.0:
                s.rotate_by(step, force=f)
        h = hb[0]
        if h is not None:
            h._last_dx += dx
            h._last_dy += dy
            h._last_u = uu

    handle = _start_tween(
        duration=time, ease=ease, write=write,
        tween_keys=keys,
        then=then, on_done=on_done, owner=owner, scope=scope,
        loops=n_loops, yoyo=yoyo, ride=ride, motion_readout=True,
        claim_targets=(
            *_move_claim_targets(shape),
            *([shape["angle"]] if face else []),
        ),
        claim_kind="move_along",
        target=shape,
        speed=speed,
    )
    bound[0] = handle
    handle._last_u = u0
    return handle


# Re-export ease names so error messages / tests can share the catalog.
EASE_NAMES = TWEEN_EASES


def _now() -> float:
    clock = _clock()
    return float(getattr(clock, "time", 0.0) or 0.0) if clock is not None else 0.0


def _frame_now() -> int:
    clock = _clock()
    return int(getattr(clock, "_frame", 0) or 0) if clock is not None else 0


def _require_poll_name(name, call: str) -> None:
    if not isinstance(name, str):
        raise TypeError(
            f"{call}() name expected a string, got {type(name).__name__} {name!r}. "
            f"Write {call}(\"shoot\", …)."
        )


def _validate_ready_interval(interval: float) -> float:
    from .validate import seconds
    v = seconds(interval, "ready() interval")
    if not math.isfinite(v):
        # NaN: `now - last >= nan` is always False -> never ready again.
        # inf: same, forever. Both silently "broke" the timer instead of
        # raising at the call that introduced the bad value.
        raise ValueError(f"ready() interval must be finite, got {v}")
    if v < 0.0:
        # Negative: `>=` a negative number is always True -> fires every
        # poll regardless of elapsed time, silently.
        raise ValueError(f"ready() interval must be >= 0, got {v}")
    return v


def _ready_poll(
    timers: Dict[str, dict],
    name: str,
    interval: Optional[float],
    now: float,
) -> bool:
    """Shared cooldown poll for global ``ready`` and ``e.ready``."""
    if _SOLVER_READING:
        refuse_if_solver_reading('ready()')
    if type(name) is not str:
        _require_poll_name(name, "ready")  # before the dict lookup (unhashable names)
    if name not in timers:
        _require_poll_name(name, "ready")
        if interval is None:
            # A missing argument (first use of this name) — TypeError, like any
            # missing argument; not KeyError (outside the author-error contract).
            raise TypeError(
                f"ready({name!r}) is new: give it an interval the first time, "
                f"e.g. ready({name!r}, 0.5)"
            )
        timers[name] = {
            "interval": _validate_ready_interval(interval),
            "last_called": now,
            "enabled": True,
            "polled": _frame_now(),
        }
        return True
    timer = timers[name]
    # A gap in polling (the button was let go for a frame or more): the
    # cadence restarts at the True that ends it, with no overshoot carried.
    frame = _frame_now()
    polled = timer.get("polled")
    timer["polled"] = frame
    gap = polled is not None and frame - polled > 1
    if timer["interval"] is None:
        # Disabled before its first poll (``ready.disable``): this call
        # supplies the interval; the timer starts when it is enabled.
        if interval is None:
            raise TypeError(
                f"ready({name!r}) is new: give it an interval the first time, "
                f"e.g. ready({name!r}, 0.5)"
            )
        timer["interval"] = _validate_ready_interval(interval)
        if not timer["enabled"]:
            # Ready on its first poll after ``enable``, like a new name.
            timer["last_called"] = now - timer["interval"]
            return False
        timer["last_called"] = now
        return True
    if not timer["enabled"]:
        return False
    if interval is not None:
        timer["interval"] = _validate_ready_interval(interval)
    interval = timer["interval"]
    if reached(now - timer["last_called"], interval):
        # A steady cadence: the next window opens one interval after this
        # one was due, not after the frame that noticed it (the overshoot was
        # dropped, so the rate depended on the frame rate: review 2026-10-09
        # W-T2). After a pause in polling (the button was not held) it opens
        # one interval from now: no burst of catch-up True.
        # A gap in polling, however short, restarts the cadence at this True
        # (a release and a press one frame late must not carry that frame
        # into the next shot: PG-RD1).
        nxt = timer["last_called"] + interval
        timer["last_called"] = nxt if (not gap and now - nxt < interval) else now
        return True
    return False


def _remembered_poll(
    slots: Dict[str, dict],
    name: str,
    value,
    hold: float,
    now: float,
) -> bool:
    """Shared decaying-truthy poll for global ``recently`` and ``e.recently``.

    True if ``value`` is truthy now, or was truthy within the last ``hold``
    seconds of world time. Passing ``hold`` again updates the stored window.
    """
    if _SOLVER_READING:
        refuse_if_solver_reading('recently()')
    if type(name) is not str:
        _require_poll_name(name, "recently")  # before the dict lookup (unhashable names)
    from .validate import seconds
    hold = seconds(hold, "recently() hold")
    if hold < 0.0:
        # A negative hold made `(now - last) <= hold` false even when
        # `value` is truthy on this exact call (now - last == 0), so a
        # currently-true value silently read as False.
        raise ValueError(f"recently() hold must be >= 0, got {hold}")
    slot = slots.get(name)
    if slot is None:
        _require_poll_name(name, "recently")
        slot = {"last_true": None, "hold": hold}
        slots[name] = slot
    else:
        slot["hold"] = hold
    if value:
        slot["last_true"] = now
    last = slot["last_true"]
    # (now - last) <= hold, forgiving rounding: hold "reaches" the gap.
    return last is not None and reached(slot["hold"], now - last)


def _entity_state_dict(item, attr: str) -> Dict[str, dict]:
    """Lazily attach a private poll-state dict on an Entity instance."""
    state = getattr(item, attr, None)
    if state is None:
        state = {}
        object.__setattr__(item, attr, state)
    return state


def ready_on(item, name: str, interval: Optional[float] = None) -> bool:
    """``ready`` scoped to ``item`` — independent slot per Entity instance."""
    return _ready_poll(_entity_state_dict(item, "_ready_state"), name, interval, _now())


def recently_on(item, name: str, value, hold: float = 0.1) -> bool:
    """``recently`` scoped to ``item`` — independent memory per Entity instance."""
    return _remembered_poll(
        _entity_state_dict(item, "_recently_state"), name, value, hold, _now(),
    )


class ReadyManager(ClosedSurface):
    """Poll API: ``ready('fire', 0.15)`` is True when the named interval elapses.

    Driven by ``clock.time`` (scaled world time), not wall ``perf_counter``.
    First call creates the timer and returns True (same as the old manager).
    """

    _closed_who = "ready"

    def __init__(self) -> None:
        self._timers: Dict[str, dict] = {}

    def __call__(self, name: str, interval: Optional[float] = None) -> bool:
        return _ready_poll(self._timers, name, interval, _now())

    def disable(self, name: str) -> "ReadyManager":
        """Pause the ``name`` timer: ``ready(name, …)`` is False until ``enable``.
        A name never polled yet is disabled too (its first ``ready`` call
        is False). Returns ``ready``."""
        _require_poll_name(name, "ready.disable")
        timer = self._timers.get(name)
        if timer is None:
            # Not a no-op: "no shooting until the intro ends" is written
            # before the first shot (review 2026-10-09 S2-15).
            self._timers[name] = {"interval": None, "last_called": None, "enabled": False}
        else:
            timer["enabled"] = False
        return self

    def enable(self, name: str) -> "ReadyManager":
        """Resume a disabled ``name`` timer. Returns ``ready``."""
        _require_poll_name(name, "ready.enable")
        if name in self._timers:
            self._timers[name]["enabled"] = True
        return self

    def reset(self, name: str) -> "ReadyManager":
        """Make ``ready(name, …)`` True again on its next call (restart the cooldown). Returns ``ready``."""
        _require_poll_name(name, "ready.reset")
        timer = self._timers.get(name)
        if timer is not None and timer["interval"] is not None:
            timer["last_called"] = _now() - timer["interval"]
        return self

    def remove(self, name: str) -> "ReadyManager":
        """Forget the ``name`` timer; its next call starts fresh (and is True). Returns ``ready``."""
        _require_poll_name(name, "ready.remove")
        self._timers.pop(name, None)
        return self


class RememberedManager(ClosedSurface):
    """Poll API: ``recently('no_chao', no_chao, hold=0.08)`` is True if
    ``value`` was truthy at any point in the last ``hold`` seconds.

    Driven by ``clock.time`` (scaled world time), like ``ready``.
    Level query — re-true every frame inside the window (not edge-consuming).
    """

    _closed_who = "recently"

    def __init__(self) -> None:
        self._slots: Dict[str, dict] = {}

    def __call__(self, name: str, value, hold: float = 0.1) -> bool:
        return _remembered_poll(self._slots, name, value, hold, _now())

    def reset(self, name: str) -> "RememberedManager":
        """Forget the slot: next read is False until ``value`` is truthy again."""
        _require_poll_name(name, "recently.reset")
        if name in self._slots:
            self._slots[name]["last_true"] = None
        return self

    def remove(self, name: str) -> "RememberedManager":
        """Forget the ``name`` slot entirely. Returns ``recently``."""
        _require_poll_name(name, "recently.remove")
        self._slots.pop(name, None)
        return self


# help(Handle) / inspect.signature: no public constructor (``Handle(...)``
# raises; the engine uses ``Handle._make``), so publish ``Handle()`` rather
# than the refusing ``__init__(*_args, **_kwargs)``.
Handle.__signature__ = inspect.Signature()
