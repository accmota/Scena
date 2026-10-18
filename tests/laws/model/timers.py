"""T laws: timers (design/Laws.md, "Timers").

Input: each timed handle's ``add`` (kind, delay / interval, owner, the phase
it was made in), its ``tick`` records (world dt, the owner's time scale,
parked, dead, paused) and its fires. Time is exact here: every number is
taken at its rational intent (``Fraction(x).limit_denominator(10**6)``:
1/60 for a 60 Hz dt, 1/2 for 0.5 s), never through the engine's
``reached`` tolerance — an independent oracle for the PM8 class (a timer a
frame late or early by float rounding). ``once`` (``after``) and ``every``
are modelled; other kinds (tweens, waits) abstain.

T1  A timer fires on the first tick where its owner's world time since its
    start reaches its delay: a whole number of frames lands on that frame.
T2  A timer's time starts at the first process tick that begins after it is
    made: one made before the tick (in update, an input hook) counts that
    frame; one made in the tick or later counts from the next. A task's
    later steps run in the tick (its first runs where it is started).
T3  A parked owner's timers neither fire nor gain time; a dead owner's never
    fire. A parked or dead owner's task takes no step.
T5  Work a task starts (its owner and scope) ends with it: nothing it
    started fires after a live cancel of the task (its replacement by
    ``name=``, its owner's destroy). The closure-over-``self`` half of T5
    is equation E6.
T4  ``every`` fires once per interval of world time, at most
    ``ceil(MAX_FRAME_DT / interval)`` times in one tick (debt beyond that
    keeps only its phase).
T6  Work scheduled on a destroyed actor registers nothing: it never ticks,
    never runs (a task's body never takes a step).
"""
from __future__ import annotations

import math
from fractions import Fraction
from typing import Dict

from laws.model.base import Report, Trace

LAWS = ("T1", "T2", "T3", "T4", "T5", "T6")

MAX_FRAME_DT = Fraction(1, 4)       # scena.input.MAX_FRAME_DT, a declared parameter
MODELLED = ("after", "every")
BEFORE_TICK = (None, "poll", "update")


def R(x) -> Fraction:
    return Fraction(x).limit_denominator(10 ** 6)


class _H:
    __slots__ = ("kind", "delay", "interval", "elapsed", "made_frame", "made_phase",
                 "refused", "over", "fired", "want", "ticks", "abstain", "parked")

    def __init__(self, kind, delay, interval, frame, phase, refused):
        self.kind = kind
        self.delay = R(delay)
        self.interval = R(interval)
        self.elapsed = Fraction(0)
        self.made_frame = frame
        self.made_phase = phase
        self.refused = refused
        self.over = refused
        self.fired = 0          # fires since the last tick
        self.want = 0           # fires the last tick owes
        self.ticks = 0
        self.abstain = False
        self.parked = False     # the last tick found the owner parked


def _budget(interval: Fraction) -> int:
    return max(1, math.ceil(MAX_FRAME_DT / interval)) if interval > 0 else 1


def check(tr: Trace, rep: Report) -> None:
    hs: Dict[str, _H] = {}
    frames = tr.frames
    dead = set()                      # labels whose destroy returned (dead)
    tasks: Dict[str, list] = {}       # task label -> [steps taken, refused]
    parent_of: Dict[str, str] = {}    # handle label -> the task it is work of
    killed = set()                    # tasks a live cancel ended

    def settle(label, h, f):
        """The tick that ended owed ``h.want`` fires; ``h.fired`` happened."""
        if h.abstain or h.ticks == 0:
            return
        if h.fired != h.want:
            law = "T3" if (h.parked and h.fired) else ("T4" if h.kind == "every" else "T1")
            rep.find(law, f, f"{label}: {h.fired} fire(s) where {h.want} were due "
                     f"(elapsed {float(h.elapsed):.6f})", f"{h.kind}|{label.rsplit('#', 1)[0]}")

    for i, e in enumerate(tr.events):
        if e[0] == "d" and e[2]:
            dead.add(e[1])
        elif e[0] == "N":
            dead.discard(e[1])
        if e[0] != "H":
            if e[0] == "f":
                for label, h in hs.items():
                    if h.want or h.fired:
                        settle(label, h, e[1])
                    h.want = h.fired = 0
            continue
        what, label = e[1], e[2]
        f = frames[i]
        if what == "add":
            kind, delay, interval, _owner, _scope, refused, phase = e[3], e[4], e[5], e[6], e[7], e[8], e[9]
            parent = e[10] if len(e) > 10 else None
            if parent is not None:
                parent_of[label] = parent
            if kind == "task":
                tasks[label] = [0, refused or (_owner is not None and _owner in dead)]
                continue
            if kind not in MODELLED:
                continue
            on_dead = _owner is not None and _owner in dead
            hs[label] = _H(kind, delay, interval, f, phase, refused or on_dead)
            if on_dead:
                rep.witness("T6")
            continue
        if what == "step":
            t = tasks.get(label)
            if t is None:
                continue
            active, alive, phase = e[3], e[4], e[5]
            if t[1]:
                rep.find("T6", f, f"{label} was started on a destroyed actor and took a step",
                         "task|registered")
            if t[0]:
                rep.witness("T2")
                if phase is not None and phase != "tick":
                    rep.find("T2", f, f"{label} took a later step in {phase}", f"task|{phase}")
                rep.witness("T3")
                if not active or not alive:
                    rep.find("T3", f, f"{label} took a step while its owner was "
                             f"{'parked' if alive else 'destroyed'}", "task|owner")
            t[0] += 1
            if parent_of.get(label) in killed:
                rep.find("T5", f, f"{label} took a step after its task was cancelled",
                         "task|step")
            continue
        if what == "cancel" and len(e) > 3 and e[3] and label in tasks:
            killed.add(label)
            if label in parent_of.values():
                rep.witness("T5")
        elif what == "fire" and parent_of.get(label) in killed:
            rep.find("T5", f, f"{label} fired after its task was cancelled",
                     f"{label.rsplit('#', 1)[0]}|fire")
        h = hs.get(label)
        if h is None:
            continue
        if what == "tick":
            world_dt, scale, active, alive, paused, held, over = e[3:10]
            if h.refused:
                rep.find("T6", f, f"{label} was made on a destroyed actor and registered",
                         f"{h.kind}|registered")
                h.refused = False             # once per handle
            if h.ticks == 0:
                rep.witness("T2")
                if h.made_frame == f and h.made_phase not in BEFORE_TICK:
                    rep.find("T2", f, f"{label} made in {h.made_phase} ticked in the same frame",
                             f"{h.kind}|{h.made_phase}")
            h.ticks += 1
            h.parked = False
            if over or h.over:
                h.want = 0
                continue
            if not alive:
                h.want = 0
                h.over = True
                continue
            if not active or paused or held:
                rep.witness("T3")
                h.want = 0
                h.parked = not active
                continue
            if scale < 0:
                scale = 0.0
            h.elapsed += R(world_dt) * R(scale)
            if h.kind == "after":
                rep.witness("T1")
                h.want = 1 if h.elapsed >= h.delay else 0
                if h.want:
                    h.over = True
            else:
                rep.witness("T4")
                if h.interval <= 0:
                    h.abstain = True
                    continue
                owed = int(h.elapsed // h.interval)
                cap = _budget(h.interval)
                k = min(owed, cap)
                h.elapsed -= k * h.interval
                if k == cap and h.elapsed >= h.interval:
                    h.elapsed = h.elapsed % h.interval     # debt beyond the cap: phase only
                h.want = k
        elif what == "fire":
            h.fired += 1
            if h.refused:
                rep.find("T6", f, f"{label} was made on a destroyed actor and ran", h.kind)
        elif what == "cancel":
            if h.fired < h.want:
                h.abstain = True          # cancelled from its own callback, mid-loop
            h.over = True
        elif what in ("pause", "resume"):
            pass
