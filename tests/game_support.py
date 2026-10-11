"""In-game instrumentation for the game system tests (``tests/games/``).

Not a test module. The games import it (``from game_support import ...``:
``program_support`` puts ``tests/`` on ``sys.path``); the drivers read what it
recorded through ``G.report()``. Strategy: design/Testing Design.md,
"Game system tests".

Rules every model here follows:

* **An independent source.** A model never calls the engine function it
  checks. Its truth is a Guia sentence (cited in its docstring), closed-form
  math (``geom``), or the game's own bookkeeping (what it spawned, scored,
  destroyed).
* **Record, never raise.** A check that fails inside an engine callback must
  not end the run (an author error leaves the frame): ``check`` records the
  failure with the frame, the time and the scope, and the driver fails the
  test with the list. ``SCENA_GAME_CHECKS=raise`` raises at the site instead,
  for a debugger.
* **Plain data out.** ``report()`` holds no engine object, so reading it after
  ``close()`` keeps nothing alive. Objects are known by a serial the ledger
  gives (never ``id()``: ids are reused after a free).
* **Frame clock.** A game calls ``G.frame()`` as the first line of its module
  ``update(dt)``. That is step 2 of the frame (Scena Design, "Frame order"):
  what the models read there is the state the previous frame left after its
  collision step, flush and pre-draw ticks.
"""
from __future__ import annotations

import math
import os
import weakref
import zlib
from collections import deque
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

__all__ = [
    "Ledger", "TimerModel", "TweenModel", "EdgeModel", "ChangeModel",
    "CoverModel", "SoundModel", "reached", "geom",
]


# ---------------------------------------------------------------------------
# The due rule, written from the Guia ("Agendar": a timer fires on the first
# frame where the time has passed; Scena Design, "Clocks": deadlines on summed
# time compare with a 1e-9 relative tolerance). Written here, not imported, so
# a change to the engine's rule shows up as a divergence.
# ---------------------------------------------------------------------------

def reached(elapsed: float, target: float) -> bool:
    tol = 1e-9 * (abs(target) if abs(target) > 1.0 else 1.0)
    return elapsed >= target - tol


def _close(a: Any, b: Any, tol: float) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if math.isnan(a) or math.isnan(b):
            return False
        return abs(float(a) - float(b)) <= tol
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    return a == b


def _xy(p: Any) -> Tuple[float, float]:
    """A point-like as a float pair (tuple, Vec2, Point, Graphic's center)."""
    if isinstance(p, (tuple, list)):
        return float(p[0]), float(p[1])
    c = getattr(p, "center", None)
    if c is not None and not isinstance(p, (tuple, list)) and c is not p:
        p = c
    return float(p.x), float(p.y)


class Ledger:
    """The game's notebook: reach counters, checks, failures, lifetimes, models."""

    MAX_FAILURES = 200

    def __init__(self, game: str, mark: Optional[Callable] = None) -> None:
        from scena import clock
        self._clock = clock
        self.game = game
        self._mark = mark if callable(mark) else None
        self.raise_mode = os.environ.get("SCENA_GAME_CHECKS", "") == "raise"
        self.frame_no = 0          # G.frame() calls (1 = the first update)
        self.t = 0.0               # clock.time at the last G.frame()
        self.dt = 0.0
        self.scope_label = "top"
        self.reach: Dict[str, int] = {}
        self.evals: Dict[str, int] = {}
        self.fails: Dict[str, int] = {}
        self.failures: List[Dict[str, Any]] = []
        self.events: deque = deque(maxlen=200)
        self._invariants: List[Tuple[str, Callable, int, int]] = []
        self._models: List[Any] = []
        self._serial = weakref.WeakKeyDictionary()
        self._next_serial = 0
        self._alive: Dict[str, set] = {}
        self._kind_of: Dict[int, str] = {}
        self._dead: Dict[int, str] = {}
        self._deaths: Dict[str, int] = {}
        self._finished = False

    # -- frame clock ---------------------------------------------------------
    def frame(self) -> None:
        clk = self._clock
        t, dt = float(clk.time), float(clk.dt)
        if self.frame_no:
            self.check(t >= self.t, "clock.monotone", f"time went back {self.t} -> {t}")
            self.check(_close(t - self.t, dt, 1e-9), "clock.dt_is_step",
                       f"time moved {t - self.t!r} but dt is {dt!r}")
        self.frame_no += 1
        self.t, self.dt = t, dt
        for m in self._models:
            try:
                m.on_frame(self)
            except Exception as e:      # a model bug is a failure, not a crash
                self.fail(f"model.{type(m).__name__}", f"raised {type(e).__name__}: {e}")
        for name, fn, every, after in self._invariants:
            if self.frame_no < after or (self.frame_no - after) % every:
                continue
            try:
                r = fn()
            except Exception as e:
                r = f"raised {type(e).__name__}: {e}"
            self.check(r is None or r is True, name, r if isinstance(r, str) else "")

    # -- reach and events ---------------------------------------------------
    def hit(self, name: str, n: int = 1) -> None:
        self.reach[name] = self.reach.get(name, 0) + n

    def event(self, name: str, **data: Any) -> None:
        self.hit(name)
        self.events.append((self.frame_no, round(self.t, 6), name, _plainish(data)))
        if self._mark is not None:
            self._mark(name, **_plainish(data))

    # -- checks ---------------------------------------------------------------
    def check(self, ok: Any, name: str, msg: str = "", **ctx: Any) -> bool:
        self.evals[name] = self.evals.get(name, 0) + 1
        if ok:
            return True
        self.fail(name, msg, **ctx)
        return False

    def equal(self, got: Any, want: Any, name: str, tol: float = 0.0, **ctx: Any) -> bool:
        ok = _close(got, want, tol)
        return self.check(ok, name, "" if ok else f"got {got!r:.160} want {want!r:.160} (tol {tol})", **ctx)

    def within(self, v: Any, lo: float, hi: float, name: str, **ctx: Any) -> bool:
        ok = lo <= v <= hi
        return self.check(ok, name, "" if ok else f"{v!r} not in [{lo}, {hi}]", **ctx)

    def fail(self, name: str, msg: str = "", **ctx: Any) -> None:
        self.fails[name] = self.fails.get(name, 0) + 1
        if len(self.failures) < self.MAX_FAILURES:
            self.failures.append({
                "name": name, "msg": str(msg)[:300], "frame": self.frame_no,
                "t": round(self.t, 6), "scope": self.scope_label, "ctx": _plainish(ctx),
            })
        if self.raise_mode:
            raise AssertionError(f"[{self.game}] {name} @frame {self.frame_no}: {msg} {ctx}")

    def invariant(self, name: str, fn: Callable[[], Any], *, every: int = 1, after: int = 0) -> None:
        """``fn()`` runs at every ``G.frame()``: None / True pass, a str or False fail."""
        self._invariants.append((name, fn, max(1, int(every)), int(after)))

    def scope(self, label: str) -> None:
        """Label failures with where the game is (an act, a mode)."""
        self.scope_label = label

    def model(self, m: Any) -> Any:
        self._models.append(m)
        return m

    # -- lifetimes ------------------------------------------------------------
    def serial(self, obj: Any) -> int:
        s = self._serial.get(obj)
        if s is None:
            s = self._next_serial
            self._next_serial += 1
            self._serial[obj] = s
        return s

    def born(self, obj: Any, kind: str) -> int:
        s = self.serial(obj)
        self.check(s not in self._kind_of, "life.born_once", f"{kind} #{s} born twice")
        self._kind_of[s] = kind
        self._alive.setdefault(kind, set()).add(s)
        self.hit(f"born.{kind}")
        return s

    def died(self, obj: Any, how: str = "") -> None:
        """Once per object, from its ``on_destroy`` (the engine's own door)."""
        s = self.serial(obj)
        kind = self._kind_of.get(s)
        if not self.check(kind is not None, "life.died_known", f"#{s} died unborn ({how})"):
            return
        if not self.check(s not in self._dead, "life.died_once",
                          f"{kind} #{s} died twice ({self._dead.get(s)} then {how})"):
            return
        self._dead[s] = how
        self._alive[kind].discard(s)
        self._deaths[f"{kind}.{how}"] = self._deaths.get(f"{kind}.{how}", 0) + 1
        self.hit(f"died.{kind}")

    def alive(self, kind: str) -> int:
        return len(self._alive.get(kind, ()))

    def alive_serials(self, kind: str) -> set:
        return set(self._alive.get(kind, ()))

    def deaths(self, kind: str, how: Optional[str] = None) -> int:
        if how is not None:
            return self._deaths.get(f"{kind}.{how}", 0)
        return sum(v for k, v in self._deaths.items() if k.startswith(kind + "."))

    def is_dead(self, obj: Any) -> bool:
        return self.serial(obj) in self._dead

    # -- end ------------------------------------------------------------------
    def finish(self) -> None:
        """End-of-run checks, then drop every engine reference the models hold
        (handles, readers): the program's teardown census must not see them."""
        if self._finished:
            return
        self._finished = True
        for m in self._models:
            fin = getattr(m, "on_finish", None)
            if fin is not None:
                try:
                    fin(self)
                except Exception as e:
                    self.fail(f"model.{type(m).__name__}", f"finish raised {type(e).__name__}: {e}")
        for m in self._models:
            rel = getattr(m, "release", None)
            if rel is not None:
                rel()
        self._invariants.clear()

    def report(self) -> Dict[str, Any]:
        return {
            "game": self.game,
            "frames": self.frame_no,
            "time": round(self.t, 6),
            "n_failures": sum(self.fails.values()),
            "fails": dict(self.fails),
            "failures": list(self.failures),
            "evals": dict(self.evals),
            "reach": dict(self.reach),
            "deaths": dict(self._deaths),
            "events": list(self.events)[-40:],
        }

    def digest(self) -> str:
        """The per-frame probe value: counters and failures, stable across runs."""
        body = repr((sorted(self.reach.items()), sorted(self.fails.items())))
        return f"{self.frame_no}|{sum(self.fails.values())}|{zlib.crc32(body.encode('utf-8')):08x}"


def _plainish(d: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k, v in d.items():
        if isinstance(v, (bool, int, float, str, type(None))):
            out[k] = v
        elif isinstance(v, (tuple, list)):
            out[k] = tuple(x if isinstance(x, (bool, int, float, str, type(None))) else repr(x)[:60]
                           for x in v)
        else:
            out[k] = repr(v)[:80]
    return out


# ---------------------------------------------------------------------------
# Timers
# ---------------------------------------------------------------------------

class TimerModel:
    """``after`` / ``every`` fire frames from the due rule alone.

    Guia, "after / every": a timer fires on the first frame where its time has
    passed; ``every`` fires at each multiple of the interval (debt kept, so a
    long frame fires every time it owes). Frame order (Scena Design): a timer
    created in ``update`` (before the process tick) counts that frame's ``dt``;
    one created later in the frame (a collision handler, a timer callback, an
    act's ``setup`` run from either) counts from the next frame. The game says
    which with ``early=``. ``clock.dt`` is the step (world time: pause and
    ``clock.scale`` included); ``scale=`` is the owner's ``time_scale``.

    The game calls ``expect_*`` when it schedules, ``fired`` from the callback,
    and ``cancelled`` when it cancels on purpose. An act change retires a scope
    (``retire``): its handles must read ``.cancelled`` from then on.
    """

    def __init__(self) -> None:
        self._t: Dict[str, Dict[str, Any]] = {}

    def expect_after(self, G: Ledger, label: str, handle: Any, delay: float, *,
                     early: bool, scale: float = 1.0, scope: str = "") -> None:
        self._add(G, label, handle, float(delay), every=False, early=early, scale=scale, scope=scope)

    def expect_every(self, G: Ledger, label: str, handle: Any, interval: float, *,
                     early: bool, scale: float = 1.0, scope: str = "") -> None:
        self._add(G, label, handle, float(interval), every=True, early=early, scale=scale, scope=scope)

    def _add(self, G, label, handle, period, *, every, early, scale, scope) -> None:
        old = self._t.get(label)
        if old is not None and not old["closed"]:
            # A name= slot replaced it: the old one must never fire again.
            old["closed"] = "replaced"
        G.check(G.dt >= 0.0, "timer.dt")
        G.equal(getattr(handle, "remaining", period), period, "timer.remaining_at_start",
                tol=1e-9, label=label)
        self._t[label] = {
            "h": (lambda h=handle: h),        # Handle has no weakref slot; the run owns the model
            "period": period, "every": every, "scale": float(scale), "scope": scope,
            # elapsed of this frame's process tick: early counts this frame's dt
            "acc": G.dt * scale if early else 0.0, "fires": 0, "closed": "",
            "born": G.frame_no, "label": label,
        }
        G.hit("timer.scheduled")

    def fired(self, G: Ledger, label: str) -> None:
        rec = self._t.get(label)
        if not G.check(rec is not None, "timer.fired_known", f"unknown timer {label!r}"):
            return
        if not G.check(not rec["closed"], "timer.fired_after_close",
                       f"{label!r} fired after it was {rec['closed']}"):
            return
        k = rec["fires"] + 1
        due = rec["period"] * k
        acc = rec["acc"]
        step = G.dt * rec["scale"]
        ok = reached(acc, due) and not reached(acc - step, due)
        G.check(ok, "timer.fire_frame",
                f"{label!r} fire #{k}: elapsed {acc!r} for due {due!r} (step {step!r})",
                label=label, born=rec["born"])
        rec["fires"] = k
        if not rec["every"]:
            rec["closed"] = "done"
        G.hit("timer.fired")

    def cancelled(self, label: str) -> None:
        rec = self._t.get(label)
        if rec is not None and not rec["closed"]:
            rec["closed"] = "cancelled"

    def release(self) -> None:
        for rec in self._t.values():
            rec["h"] = lambda: None

    def retire(self, G: Ledger, scope: str) -> None:
        """An act change ended ``scope``: every handle in it is cancelled."""
        for rec in self._t.values():
            if rec["scope"] == scope and not rec["closed"]:
                h = rec["h"]()
                if h is not None:
                    G.check(h.cancelled or h.done, "act.timers_cancelled",
                            f"{rec['label']!r} still pending after its act ended")
                rec["closed"] = "retired"
                G.hit("timer.retired")

    def on_frame(self, G: Ledger) -> None:
        # Start of frame M's update: acc is what the handle had after frame
        # M-1's tick. A deadline already reached with no fire is a miss.
        for rec in self._t.values():
            if rec["closed"]:
                continue
            due = rec["period"] * (rec["fires"] + 1)
            if reached(rec["acc"], due) and rec["born"] < G.frame_no:
                h = rec["h"]()
                alive = h is not None and not getattr(h, "cancelled", False)
                if alive:
                    G.fail("timer.missed", f"{rec['label']!r} due {due!r} at elapsed "
                           f"{rec['acc']!r}: no fire", label=rec["label"])
                rec["closed"] = "missed" if alive else "cancelled"
                continue
            rec["acc"] += G.dt * rec["scale"]


# ---------------------------------------------------------------------------
# Tweens
# ---------------------------------------------------------------------------

class TweenModel:
    """A tween's value from its ease, read at frame start.

    Guia, "tween": the value goes from the start to the target "em linha
    reta, como lerp", through ``ease``, over ``time`` seconds of the owner's
    time; ``on_done`` runs once at the end, with the field on the target. A
    game-written ease (a plain function) gives an exact value every frame;
    a named ease is checked by its endpoints and monotone shape only (its
    formula is the engine's, not the Guia's).
    """

    def __init__(self) -> None:
        self._w: Dict[str, Dict[str, Any]] = {}

    def expect(self, G: Ledger, label: str, read: Callable[[], float], start: float, end: float,
               time: float, *, ease: Optional[Callable[[float], float]] = None,
               early: bool, monotone: bool = True) -> None:
        self._w[label] = {
            "read": read, "a": float(start), "b": float(end), "time": float(time),
            "ease": ease, "acc": G.dt if early else 0.0, "done": 0, "last": float(start),
            "monotone": monotone, "label": label, "closed": False,
        }
        G.hit("tween.started")

    def done(self, G: Ledger, label: str) -> None:
        w = self._w.get(label)
        if not G.check(w is not None, "tween.done_known", label):
            return
        w["done"] += 1
        G.check(w["done"] == 1, "tween.done_once", f"{label!r} on_done #{w['done']}")
        G.check(reached(w["acc"], w["time"]) and not reached(w["acc"] - G.dt, w["time"]),
                "tween.done_frame", f"{label!r} done at elapsed {w['acc']!r} of {w['time']!r}")
        G.equal(w["read"](), w["b"], "tween.done_value", tol=1e-9, label=label)
        w["closed"] = True
        G.hit("tween.done")

    def cancel(self, label: str) -> None:
        w = self._w.get(label)
        if w is not None:
            w["closed"] = True

    def release(self) -> None:
        for w in self._w.values():
            w["closed"] = True
            w["read"] = lambda: 0.0

    def on_frame(self, G: Ledger) -> None:
        for w in self._w.values():
            if w["closed"]:
                continue
            v = float(w["read"]())
            u = min(1.0, w["acc"] / w["time"]) if w["time"] > 0 else 1.0
            span = w["b"] - w["a"]
            if w["ease"] is not None:
                G.equal(v, w["a"] + span * w["ease"](u), "tween.value", tol=1e-6,
                        label=w["label"], u=round(u, 6))
            else:
                lo, hi = min(w["a"], w["b"]), max(w["a"], w["b"])
                G.within(v, lo - 1e-9, hi + 1e-9, "tween.bounds", label=w["label"])
                if w["monotone"]:
                    moved = (v - w["last"]) * (1 if span >= 0 else -1)
                    G.check(moved >= -1e-9, "tween.monotone",
                            f"{w['label']!r} went back {w['last']!r} -> {v!r}")
            w["last"] = v
            w["acc"] += G.dt


# ---------------------------------------------------------------------------
# @when / @on_change
# ---------------------------------------------------------------------------

class EdgeModel:
    """``@when`` fires once per rising edge of its condition.

    Guia, "@when": "roda a função uma vez quando a condição passa de False
    para True"; it is checked at ``flush`` (frame step 6). The model samples
    the condition at ``G.frame()`` (step 2). A rising edge first seen at frame
    N's sample was written in frame N-1 (steps 2–6: fired in N-1's flush) or
    in frame N's input poll (a widget: fired in N's flush, after the sample).
    So each edge is checked one frame later: exactly one fire in frame N-1 or
    N. A fire with no edge in its window is spurious. The game changes the
    condition's sources at most once per frame for this to hold.
    """

    def __init__(self, name: str, cond: Callable[[], bool]) -> None:
        self.name, self.cond = name, cond
        self.prev: Optional[bool] = None
        self.fired_frames: List[int] = []
        self.edges: List[int] = []          # frames whose sample first saw an edge
        self.matched: set = set()

    def fired(self, G: Ledger) -> None:
        self.fired_frames.append(G.frame_no)
        G.hit(f"when.{self.name}")

    def on_frame(self, G: Ledger) -> None:
        n = G.frame_no
        now = bool(self.cond())
        # settle the edges seen last frame: a fire in N-1 or N
        keep = []
        for seen in self.edges:
            if seen < n:
                fires = [f for f in self.fired_frames if seen - 1 <= f <= seen and f not in self.matched]
                G.check(len(fires) >= 1, f"when.{self.name}.edges",
                        f"edge seen at frame {seen}: no fire in frames {seen - 1}..{seen}")
                if fires:
                    self.matched.add(fires[0])
            else:
                keep.append(seen)
        self.edges = keep
        # a fire that no edge explains (two frames back: its window has closed)
        for f in self.fired_frames:
            if f <= n - 2 and f not in self.matched:
                G.fail(f"when.{self.name}.spurious", f"fire at frame {f} with no rising edge")
                self.matched.add(f)
        if self.prev is not None and not self.prev and now:
            self.edges.append(n)
        self.fired_frames = [f for f in self.fired_frames if f > n - 3]
        self.matched = {f for f in self.matched if f > n - 3}
        self.prev = now


class ChangeModel:
    """``@on_change`` fires when the value changes, with the new value.

    Guia, "@on_change": "Dispara quando o valor novo é != do anterior";
    callback with the new value; it runs at ``flush`` (frame step 6).

    A change seen at ``G.frame()`` of frame N was written either in frame N-1
    (steps 2–6: its call was in N-1's flush) or in frame N's input poll (a
    widget or a click callback: its call comes in N's flush, after this
    sample). So the model checks one frame later: some call in frame N-1 or N
    carried the new value. Calls never repeat the value before them, and a
    call's value is the value the source had right after that flush.
    """

    def __init__(self, name: str, read: Callable[[], Any]) -> None:
        self.name, self.read = name, read
        self.prev: Any = None
        self.started = False
        self.calls: List[Tuple[int, Any]] = []
        self.pending: List[Tuple[int, Any, Any]] = []   # (frame seen, old, new)
        self.last_call: Any = _NOTHING

    def fired(self, G: Ledger, value: Any) -> None:
        if self.last_call is not _NOTHING:
            G.check(value != self.last_call, f"change.{self.name}.repeat",
                    f"call repeated {value!r}")
        self.last_call = value
        self.calls.append((G.frame_no, value))
        G.hit(f"change.{self.name}")

    def on_frame(self, G: Ledger) -> None:
        now = self.read()
        n = G.frame_no
        keep = []
        for seen, old, new in self.pending:
            if seen < n:
                vals = [v for f, v in self.calls if seen - 1 <= f <= seen]
                G.check(new in vals, f"change.{self.name}.fires",
                        f"{old!r} -> {new!r} seen at frame {seen}: calls {vals!r}")
            else:
                keep.append((seen, old, new))
        self.pending = keep
        if self.started and now != self.prev:
            self.pending.append((n, self.prev, now))
        self.calls = [(f, v) for f, v in self.calls if f >= n - 2]
        self.prev, self.started = now, True


_NOTHING = object()


# ---------------------------------------------------------------------------
# Canvas cover
# ---------------------------------------------------------------------------

class CoverModel:
    """``canvas.fade_out`` / ``fade_in`` from the Guia's "Impactos — Capa".

    The cover only rises during a fade_out and only falls during a fade_in;
    on the fade_out's ``on_done`` it is 1 and stays 1 until a fade_in; each
    ``on_done`` runs once; it moves while ``clock.paused`` (presentation time).
    A fade started while another runs replaces it, and the old one's
    ``on_done`` runs at once ("um efeito novo ... chama o on_done do velho na
    hora", Guia, "Transientes"; the cover follows it): that call is not held
    to the end value.
    """

    def __init__(self, read: Callable[[], float]) -> None:
        self.read = read
        self.dir = 0           # +1 fading out, -1 fading in, 0 still
        self.current = None    # label of the fade that runs
        self.last = None
        self.dones: Dict[str, int] = {}
        self.cut: set = set()
        self.held = False      # fully covered after a fade_out finished

    def start(self, G: Ledger, label: str, out: bool) -> None:
        if self.current is not None and self.dir != 0:
            self.cut.add(self.current)
            G.hit("cover.cut")
        self.current = label
        self.dir = 1 if out else -1
        self.held = False
        self.last = None       # a new phase: no comparison across it
        self.dones[label] = 0
        G.hit("cover.fade_out" if out else "cover.fade_in")

    def done(self, G: Ledger, label: str, out: bool) -> None:
        self.dones[label] = self.dones.get(label, 0) + 1
        G.check(self.dones[label] == 1, "cover.done_once", f"{label!r} #{self.dones[label]}")
        if label in self.cut:
            G.hit("cover.cut_done")
            return
        G.equal(self.read(), 1.0 if out else 0.0, "cover.done_value", tol=1e-9, label=label)
        if label == self.current:
            self.held = out
            self.dir = 0
            self.last = None
        G.hit("cover.done")

    def on_frame(self, G: Ledger) -> None:
        v = float(self.read())
        G.within(v, 0.0, 1.0, "cover.range")
        if self.last is not None:
            if self.dir > 0:
                G.check(v >= self.last - 1e-9, "cover.out_rises", f"{self.last} -> {v}")
            elif self.dir < 0:
                G.check(v <= self.last + 1e-9, "cover.in_falls", f"{self.last} -> {v}")
            elif self.held:
                G.equal(v, 1.0, "cover.holds", tol=1e-9)
        self.last = v


# ---------------------------------------------------------------------------
# Sounds
# ---------------------------------------------------------------------------

class SoundModel:
    """Sound handles against the Guia's "Som" sentences.

    * a finite sound's ``on_done`` runs once, at its natural end: not before
      ``duration / pitch * loops`` of world time has passed since it started
      (with a frame's slack for the pump); the mixer pumps world ``dt``;
    * ``.cancel()`` / a name= replacement never run ``on_done``;
    * at most one live voice per ``name=`` slot;
    * ``h.effects`` is a stack: ``add`` / ``remove`` / ``clear`` like a list,
      a second ``remove`` does nothing.
    """

    def __init__(self) -> None:
        self._s: Dict[str, Dict[str, Any]] = {}
        self._slots: Dict[str, str] = {}

    def started(self, G: Ledger, label: str, handle: Any, length: Optional[float], *,
                slot: Optional[str] = None) -> None:
        if slot is not None:
            old = self._slots.get(slot)
            if old is not None and old in self._s:
                self._s[old]["closed"] = "replaced"
            self._slots[slot] = label
        self._s[label] = {"h": (lambda h=handle: h), "len": length, "t0": G.t, "acc": 0.0,
                          "dones": 0, "closed": "", "fx": [], "label": label}
        G.hit("sound.started")

    def done(self, G: Ledger, label: str) -> None:
        s = self._s.get(label)
        if not G.check(s is not None, "sound.done_known", label):
            return
        s["dones"] += 1
        G.check(s["dones"] == 1, "sound.done_once", f"{label!r} #{s['dones']}")
        G.check(not s["closed"], "sound.done_after_close", f"{label!r} was {s['closed']}")
        if s["len"] is not None:
            G.check(s["acc"] + G.dt >= s["len"] - 1e-6, "sound.done_not_early",
                    f"{label!r} done after {s['acc'] + G.dt:.4f}s of {s['len']:.4f}s")
            G.check(s["acc"] <= s["len"] + 0.1, "sound.done_not_late",
                    f"{label!r} done after {s['acc'] + G.dt:.4f}s of {s['len']:.4f}s")
        s["closed"] = "done"
        G.hit("sound.done")

    def cancelled(self, label: str) -> None:
        s = self._s.get(label)
        if s is not None and not s["closed"]:
            s["closed"] = "cancelled"

    def release(self) -> None:
        for s in self._s.values():
            s["h"] = lambda: None
            s["fx"] = []

    def fx_add(self, G: Ledger, label: str, fx: Any) -> None:
        s = self._s[label]
        s["fx"].append(fx)
        self._fx_check(G, s)

    def fx_remove(self, G: Ledger, label: str, fx: Any) -> None:
        s = self._s[label]
        if any(f is fx for f in s["fx"]):
            s["fx"] = [f for f in s["fx"] if f is not fx]
        self._fx_check(G, s)

    def fx_clear(self, G: Ledger, label: str) -> None:
        s = self._s[label]
        s["fx"] = []
        self._fx_check(G, s)

    def _fx_check(self, G: Ledger, s: Dict[str, Any]) -> None:
        h = s["h"]()
        if h is None:
            return
        got = list(h.effects)
        G.check(len(got) == len(s["fx"]) and all(a is b for a, b in zip(got, s["fx"])),
                "sound.effects_stack", f"{s['label']!r}: {len(got)} effects vs model {len(s['fx'])}")
        G.hit("sound.fx_op")

    def on_frame(self, G: Ledger) -> None:
        for s in self._s.values():
            if not s["closed"]:
                s["acc"] += G.dt

    def on_finish(self, G: Ledger) -> None:
        live = {}
        for slot, label in self._slots.items():
            s = self._s.get(label)
            h = s["h"]() if s else None
            if h is not None and not h.done:
                live[slot] = live.get(slot, 0) + 1
        G.check(all(n <= 1 for n in live.values()), "sound.one_voice_per_slot", repr(live))


# ---------------------------------------------------------------------------
# Independent geometry (closed forms; never scena.geom)
# ---------------------------------------------------------------------------

class geom:
    """Closed-form plane geometry the games check the engine against."""

    @staticmethod
    def dist(a, b) -> float:
        (ax, ay), (bx, by) = _xy(a), _xy(b)
        return math.hypot(bx - ax, by - ay)

    @staticmethod
    def rot(px, py, deg, cx=0.0, cy=0.0) -> Tuple[float, float]:
        r = math.radians(deg)
        c, s = math.cos(r), math.sin(r)
        dx, dy = px - cx, py - cy
        return cx + dx * c - dy * s, cy + dx * s + dy * c

    @staticmethod
    def rect_corners(cx, cy, w, h, angle=0.0) -> List[Tuple[float, float]]:
        hw, hh = w / 2.0, h / 2.0
        return [geom.rot(cx + dx, cy + dy, angle, cx, cy)
                for dx, dy in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))]

    @staticmethod
    def aabb(points: Sequence[Tuple[float, float]]) -> Tuple[float, float, float, float]:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return min(xs), min(ys), max(xs), max(ys)

    @staticmethod
    def point_in_rect(p, cx, cy, w, h, angle=0.0) -> bool:
        x, y = geom.rot(*_xy(p), -angle, cx, cy)
        return abs(x - cx) <= w / 2.0 + 1e-9 and abs(y - cy) <= h / 2.0 + 1e-9

    @staticmethod
    def point_in_poly(p, pts) -> bool:
        x, y = _xy(p)
        inside = False
        n = len(pts)
        for i in range(n):
            (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % n]
            if (y1 > y) != (y2 > y):
                xc = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
                if x < xc:
                    inside = not inside
        return inside

    @staticmethod
    def seg_circle(p1, p2, c, r) -> List[Tuple[float, float]]:
        (x1, y1), (x2, y2), (cx, cy) = _xy(p1), _xy(p2), _xy(c)
        dx, dy = x2 - x1, y2 - y1
        fx, fy = x1 - cx, y1 - cy
        a = dx * dx + dy * dy
        if a == 0:
            return []
        b = 2 * (fx * dx + fy * dy)
        k = fx * fx + fy * fy - r * r
        disc = b * b - 4 * a * k
        if disc < 0:
            return []
        sq = math.sqrt(disc)
        out = []
        for t in sorted({(-b - sq) / (2 * a), (-b + sq) / (2 * a)}):
            if -1e-9 <= t <= 1 + 1e-9:
                out.append((x1 + t * dx, y1 + t * dy))
        return out

    @staticmethod
    def seg_seg(p1, p2, q1, q2) -> Optional[Tuple[float, float]]:
        (x1, y1), (x2, y2), (x3, y3), (x4, y4) = _xy(p1), _xy(p2), _xy(q1), _xy(q2)
        den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(den) < 1e-12:
            return None
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
        u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / den
        if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
            return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
        return None

    @staticmethod
    def seg_poly(p1, p2, pts) -> List[Tuple[float, float]]:
        out = []
        n = len(pts)
        for i in range(n):
            h = geom.seg_seg(p1, p2, pts[i], pts[(i + 1) % n])
            if h is not None and not any(abs(h[0] - o[0]) < 1e-7 and abs(h[1] - o[1]) < 1e-7
                                         for o in out):
                out.append(h)
        return out

    @staticmethod
    def closest_on_seg(p, a, b) -> Tuple[float, float]:
        (px, py), (ax, ay), (bx, by) = _xy(p), _xy(a), _xy(b)
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
        return ax + t * dx, ay + t * dy

    @staticmethod
    def closest_on_circle_disk(p, c, r) -> Tuple[float, float]:
        (px, py), (cx, cy) = _xy(p), _xy(c)
        d = math.hypot(px - cx, py - cy)
        if d <= r:
            return (px, py)
        return cx + (px - cx) * r / d, cy + (py - cy) * r / d

    @staticmethod
    def swept_circle_hits(a0, a1, ra, b, rb) -> bool:
        """A circle moving a0 -> a1 (radius ra) touches a still circle b (rb)."""
        p = geom.closest_on_seg(b, a0, a1)
        return geom.dist(p, b) <= ra + rb

    @staticmethod
    def grid_cell(left, top, w, h, cols, rows, gap, col, row) -> Tuple[float, float, float, float]:
        """Guia "Grid": row 0 at the top; cells of equal size with ``gap`` between.
        Returns (center x, center y, cell width, cell height)."""
        gx, gy = (gap, gap) if isinstance(gap, (int, float)) else gap
        cw = (w - gx * (cols - 1)) / cols
        ch = (h - gy * (rows - 1)) / rows
        return (left + col * (cw + gx) + cw / 2.0, top - row * (ch + gy) - ch / 2.0, cw, ch)

    @staticmethod
    def amp_db(x: float, floor: float = -60.0) -> float:
        """Guia, "audio": 1 stays 1; ``floor`` dB below or less is 0; <= 0 is 0."""
        if x <= 0:
            return 0.0
        v = 1.0 + 20.0 * math.log10(x) / (-floor)
        return max(0.0, min(1.0, v))
