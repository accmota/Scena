"""Laws: two programs that must end in the same shape (geometry campaign, H3).

Not a test module. Each law has two programs run on two identical subjects
(same kind, same base state); afterwards both must read alike. What a law
compares follows Q6 (Testing Design — Geometry campaign): drawn geometry and
every point part exactly (relative tolerance); ``angle`` modulo 360 unless the
law is about the turn count (``turns=True``); flip flags only in laws about
them (``flags=True``). A flip does not commute with a running rotation (Q4),
so no law reorders the two.

A program may also refuse: when **both** programs raise the same exception
type the law holds (the same door is closed both ways); when one raises and
the other does not, the law fails — unless the raise is a documented closed
door (``CLOSED``: a Derivate ``center`` refuses ``center =``).

``LAWS`` is the table; ``REWRITES`` (in ``tests/fuzz/geom_rewrite.py``) reuses
it as semantics-preserving program rewrites.
"""
from __future__ import annotations

import math
import os
import sys
import warnings
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import geometry_support as G  # noqa: E402
import geom_axes as A  # noqa: E402
from scena.state import DerivedAttributeError, LinkedAttributeError  # noqa: E402

PIVOT = (50.0, -20.0)

# A refusal that is a documented closed door, not a broken law: a Derivate
# ``center`` refuses a write (Shapes Design — Defining vs Derivate); a name a
# kind does not have refuses (route table).
CLOSED = (DerivedAttributeError, AttributeError)


@dataclass
class Law:
    name: str
    a: Callable            # program A: a(obj, ctx) -> None
    b: Callable            # program B
    applies: Callable = lambda obj: True
    turns: bool = False    # compare angle exactly (the law is about turn counts)
    flags: bool = False    # compare flip flags
    pose: bool = True      # compare angle / scale at all
    note: str = ""
    family: str = "algebra"


def _graphic(o):
    return not G.is_box(o)


def _settle():
    G.settle(1.0)


def _c(o):
    return G.center_of(o)


def _heading(o):
    return float(o.angle)


def _not_lean(o):
    from geom_shadow import placement_name
    return _graphic(o) and placement_name(o) != "lean"


def _center_places(o):
    """``center =`` is a move only where the center is the one point input
    (a field write keeps the model's other inputs: a rim-placed Circle keeps
    its ``perimeter_point`` and changes its radius — Shapes Design, Setting
    ``angle``, the same rule for ``center``)."""
    from scena.state import ContainerSlot
    if not _graphic(o):
        return False
    slots = o._field_slots() if hasattr(o, "_field_slots") else {}
    defining = A._defining(o)
    points = {n for n in defining if isinstance(slots.get(n), ContainerSlot)
              and slots[n].container_class.__name__ == "Point"}
    return points == {"center"} or not defining


def _centered_angle(o):
    """``angle =`` is ``rotate_to`` where nothing else places the shape."""
    from geom_shadow import placement_name
    return _graphic(o) and placement_name(o) in (None, "center")


LAWS: List[Law] = [
    # --- algebra -----------------------------------------------------------
    Law("move_by a then b = move_by a+b",
        lambda o, c: (o.move_by(7, -3), o.move_by(-2, 11)),
        lambda o, c: o.move_by(5, 8), _graphic, turns=True, flags=True),
    Law("move_by v then -v = id",
        lambda o, c: (o.move_by(7, -3), o.move_by(-7, 3)),
        lambda o, c: None, _graphic, turns=True, flags=True),
    Law("rotate_by a then b = rotate_by a+b",
        lambda o, c: (o.rotate_by(33), o.rotate_by(-71)),
        lambda o, c: o.rotate_by(-38), turns=True, flags=True),
    Law("rotate_by about P a then b = a+b",
        lambda o, c: (o.rotate_by(33, about=PIVOT), o.rotate_by(48, about=PIVOT)),
        lambda o, c: o.rotate_by(81, about=PIVOT), turns=True, flags=True),
    Law("rotate_by a then -a = id",
        lambda o, c: (o.rotate_by(400), o.rotate_by(-400)),
        lambda o, c: None, turns=True, flags=True),
    Law("flip_x twice = id",
        lambda o, c: (setattr(o, "flip_x", not o.flip_x), setattr(o, "flip_x", not o.flip_x)),
        lambda o, c: None, G.can_flip, turns=True, flags=True),
    Law("flip_y twice = id",
        lambda o, c: (setattr(o, "flip_y", not o.flip_y), setattr(o, "flip_y", not o.flip_y)),
        lambda o, c: None, G.can_flip, turns=True, flags=True),
    Law("flip_x then flip_y = rotate_by 180 (geometry)",
        lambda o, c: (setattr(o, "flip_x", not o.flip_x), setattr(o, "flip_y", not o.flip_y)),
        lambda o, c: o.rotate_by(180), G.can_flip, pose=False,
        note="Q6: flags differ, the heading may differ by 360"),
    Law("scale_by k then 1/k = id",
        lambda o, c: (o.scale_by(1.5), o.scale_by(1 / 1.5)),
        lambda o, c: None, _graphic, flags=True),
    Law("scale_by a then b = scale_by a*b",
        lambda o, c: (o.scale_by(1.5), o.scale_by(0.4)),
        lambda o, c: o.scale_by(0.6), _graphic, flags=True),
    Law("scale_to twice = scale_to once",
        lambda o, c: (o.scale_to(2.0), o.scale_to(2.0)),
        lambda o, c: o.scale_to(2.0), _graphic, flags=True),
    Law("rotate_to t = rotate_by(t - angle)",
        lambda o, c: o.rotate_to(c["h"] + 77),
        lambda o, c: o.rotate_by(77), turns=True, flags=True),
    Law("rotate_to t (a turn away) = rotate_by(t - angle)",
        lambda o, c: o.rotate_to(c["h"] - 283),
        lambda o, c: o.rotate_by(-283), turns=True, flags=True),
    # --- timed (settled) = instant -----------------------------------------
    Law("rotate_by timed = instant",
        lambda o, c: (o.rotate_by(33, time=0.2), _settle()),
        lambda o, c: o.rotate_by(33), _graphic, turns=True, flags=True, family="timed"),
    Law("rotate_to timed = instant (Q2)",
        lambda o, c: (o.rotate_to(c["h"] - 310, time=0.2), _settle()),
        lambda o, c: o.rotate_to(c["h"] - 310), _graphic, turns=True, flags=True, family="timed"),
    Law("scale_by timed = instant",
        lambda o, c: (o.scale_by(1.5, time=0.2), _settle()),
        lambda o, c: o.scale_by(1.5), _graphic, flags=True, family="timed"),
    Law("move_by timed = instant",
        lambda o, c: (o.move_by(7, -3, time=0.2), _settle()),
        lambda o, c: o.move_by(7, -3), _graphic, turns=True, flags=True, family="timed"),
    Law("move_to timed = instant",
        lambda o, c: (o.move_to(60, 40, time=0.2), _settle()),
        lambda o, c: o.move_to(60, 40), _graphic, turns=True, flags=True, family="timed"),
    # --- spelling ----------------------------------------------------------
    Law("move_to p = center = p",
        lambda o, c: o.move_to(60, 40),
        lambda o, c: setattr(o, "center", (60, 40)), _center_places, turns=True, flags=True, family="spelling"),
    Law("move_to p = center << p",
        lambda o, c: o.move_to(60, 40),
        lambda o, c: o.center << (60, 40), _center_places, turns=True, flags=True, family="spelling"),
    Law("move_to p = center.x, center.y",
        lambda o, c: o.move_to(60, 40),
        lambda o, c: (setattr(o.center, "x", 60), setattr(o.center, "y", 40)), _center_places,
        turns=True, flags=True, family="spelling"),
    Law("move_to p = move_by(p - center)",
        lambda o, c: o.move_to(60, 40),
        lambda o, c: o.move_by(60 - c["c"][0], 40 - c["c"][1]), _graphic,
        turns=True, flags=True, family="spelling"),
    Law("angle = a is rotate_to(a) where the center places it",
        lambda o, c: setattr(o, "angle", c["h"] + 64),
        lambda o, c: o.rotate_to(c["h"] + 64), _centered_angle, turns=True, flags=True, family="spelling"),
    Law("scale = k is scale_to(k)",
        lambda o, c: setattr(o, "scale", 1.75),
        lambda o, c: o.scale_to(1.75), _center_places, turns=True, flags=True, family="spelling"),
    Law("a verb in a batch = the verb",
        lambda o, c: _in_batch(lambda: (o.rotate_by(21), o.move_by(3, 4))),
        lambda o, c: (o.rotate_by(21), o.move_by(3, 4)), _graphic, turns=True, flags=True,
        family="spelling"),
]


def _in_batch(fn):
    from scena.state import get_scena_system
    ss = get_scena_system()
    ss.begin_frame_batch()
    try:
        fn()
    finally:
        ss.end_frame_batch()


# ---------------------------------------------------------------------------
# Observables and comparison
# ---------------------------------------------------------------------------

def observe(obj) -> dict:
    out = {"parts": {n: G.safe(f) for n, f in G.point_parts(obj).items()},
           "drawn": G.safe(lambda: G.drawn(obj)),
           "angle": G.safe(lambda: float(obj.angle))}
    if _graphic(obj):
        out["scale"] = G.safe(lambda: float(obj.scale))
        out["flags"] = (getattr(obj, "flip_x", None), getattr(obj, "flip_y", None))
    return out


def differ(a: dict, b: dict, law: Optional[Law] = None) -> Optional[str]:
    """The first observable where two subjects differ (None: alike)."""
    turns = law.turns if law else True
    flags = law.flags if law else True
    pose = law.pose if law else True
    for n, pa in a["parts"].items():
        pb = b["parts"].get(n)
        if isinstance(pa, G.ReadError) or isinstance(pb, G.ReadError):
            if type(pa) is not type(pb):
                return f"part {G.part_group(n)}"
            continue
        if pb is None or not A.close_xy(pa, pb, 1e-6):
            return f"part {G.part_group(n)}"
    da, db = a["drawn"], b["drawn"]
    if isinstance(da, G.ReadError) != isinstance(db, G.ReadError):
        return "drawn"
    if not isinstance(da, G.ReadError):
        span = max([1.0] + [abs(v) for q in da for v in q])
        if not G.same_set(da, db, 1e-6 * span):
            return "drawn"
    if pose:
        x, y = a["angle"], b["angle"]
        if not (isinstance(x, G.ReadError) or isinstance(y, G.ReadError)):
            gap = abs(x - y) if turns else abs((x - y + 180.0) % 360.0 - 180.0)
            if gap > 1e-6 * max(1.0, abs(x)):
                return "angle (turns)" if turns and abs((x - y + 180) % 360 - 180) < 1e-6 else "angle"
        if "scale" in a and not (isinstance(a["scale"], G.ReadError) or isinstance(b["scale"], G.ReadError)):
            if not A.close_num(a["scale"], b["scale"], 1e-7):
                return "scale"
    if flags and a.get("flags") != b.get("flags"):
        return "flip flags"
    return None


def _ctx(obj) -> dict:
    return {"c": G.safe(lambda: _c(obj)), "h": G.safe(lambda: _heading(obj))}


def run_law(w, law: Law, kind: str, base: str = "fresh", warm: str = "cold",
            x: str = "normal") -> Optional[str]:
    """Run ``law`` on two twins of ``kind`` in base state ``base``.

    Returns None (holds or N/A) or a violation detail."""
    G.reset_clock()
    if base == "parked" and law.family == "timed":
        return None                 # a parked actor's own timed verbs wait (Actors Design, park)
    twins = []
    for _ in range(2):
        obj = w.track(A.build(kind))
        if getattr(obj, "_ref", None) is not None:
            w.track(obj._ref)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                obj = A.apply_base(base, obj, w)
        except Exception:  # noqa: BLE001  (base findings are H1's)
            return None
        if obj is None or not law.applies(obj):
            return None
        A.prepare_twin(obj, x)
        twins.append(obj)
    if base == "mid_tween":
        G.settle(1.0)               # Q4: no law runs over a running turn
    outcomes = []
    for obj, prog in zip(twins, (law.a, law.b)):
        A.W[warm](obj)
        ctx = _ctx(obj)
        if isinstance(ctx["c"], G.ReadError) or isinstance(ctx["h"], G.ReadError):
            return None
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                with A.execution(x, obj):
                    prog(obj, ctx)
            outcomes.append(None)
        except (Exception, RecursionError) as exc:  # noqa: BLE001
            outcomes.append(exc)
    ea, eb = outcomes
    if ea is not None or eb is not None:
        if ea is not None and eb is not None and type(ea) is type(eb):
            return None
        closed = [e for e in (ea, eb) if e is not None]
        if all(isinstance(e, CLOSED) for e in closed) and law.family == "spelling":
            return None             # a documented closed door on one spelling
        if any(isinstance(e, LinkedAttributeError) for e in closed) and G.is_relational(twins[0]):
            return None             # a relational shape refuses some verbs: the table, not a law (H8)
        return f"raises {type(ea or eb).__name__} one way only"
    return differ(observe(twins[0]), observe(twins[1]), law)
