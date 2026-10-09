"""Program generator and executor of the geometry fuzzer (geometry campaign, H10).

Not a test module. A **program** is plain JSON: a pool of subjects (kind,
base state, link configuration) and a list of operations. Every number is
in the program, so a seed replays to the same trace and a failure can be
written down and reduced.

Operations:

=====================  ======================================================
``["call", i, verb, args, kw]``  a pose verb on subject ``i`` with numbers
                       (``kw`` may hold ``time``: the call settles after);
                       verbs: move_by, move_to, rotate_by, rotate_to,
                       scale_by, scale_to, flip_x, flip_y, angle=
``["read", i, order]``  read every part of ``i`` (sorted / reversed): warmth
``["clone", i]``        a clone of ``i`` joins the pool (a fresh shadow)
``["unlink", i]``       ``unlink_all()`` on ``i`` (a link freezes its value)
``["batch", [ops]]``    the ops inside one frame batch (rewrites make these)
``["via_move_by", i, x, y]``  ``move_to`` spelled as ``move_by(p - center)``
``["via_rotate_by", i, t]``   ``rotate_to(t)`` spelled as ``rotate_by(t - angle)``
``["swap_clone", i]``   continue on a clone of ``i`` in its slot (a rewrite)
``["swap_copy", i, kind]``  continue on ``fresh << i`` of another model
=====================  ======================================================

``run(program)`` executes it and returns a ``Trace``: after every top-level
operation, each subject's observation (drawn set, point parts, heading modulo
360, scale, flip flags) or the refusal it raised. ``shadow=True`` checks every
call against the subject's affine shadow (H1); the sentinel (H2) is the
caller's ``geom_sentinel.active``.
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
import warnings
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
if TESTS not in sys.path:
    sys.path.insert(0, TESTS)

import geom_axes as A  # noqa: E402
import geom_shadow as S  # noqa: E402
import geometry_support as G  # noqa: E402
from scena.state import LinkedAttributeError  # noqa: E402

PIVOT = (50.0, -20.0)
# Bases the fuzzer draws: a mid-tween or parked subject changes what a timed
# verb means (H1 covers them); the fuzzer's rewrites trade timed for instant.
BASES = ("fresh", "flip_x", "flip_xy", "rotated", "scaled", "degenerate", "names_crossed",
         "copied", "cloned", "collidable", "drawn")
LINKS = ("none", "none", "none", "field", "part", "source", "whole")
VERBS = ("move_by", "move_to", "rotate_by", "rotate_to", "scale_by", "scale_to",
         "flip_x", "flip_y", "angle=")
KINDS = sorted(k for k in A.K if not k.startswith("Box"))


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def _num(rng, lo, hi, nd=2):
    return round(rng.uniform(lo, hi), nd)


def gen_call(rng, i) -> list:
    verb = rng.choice(VERBS)
    kw = {}
    if verb == "move_by":
        args = [_num(rng, -30, 30), _num(rng, -30, 30)]
    elif verb == "move_to":
        args = [_num(rng, -80, 80), _num(rng, -80, 80)]
    elif verb == "rotate_by":
        args = [_num(rng, -400, 400)]
        if rng.random() < 0.3:
            kw["about"] = list(PIVOT)
    elif verb in ("rotate_to", "angle="):
        args = [_num(rng, -500, 500)]
    elif verb == "scale_by":
        args = [rng.choice([0.5, 0.8, 1.25, 1.5, 2.0])]
        if rng.random() < 0.3:
            kw["about"] = list(PIVOT)
    elif verb == "scale_to":
        args = [rng.choice([0.5, 1.0, 1.5, 3.0])]
    else:
        args = []
    if verb in ("move_by", "rotate_by", "scale_by") and rng.random() < 0.2 and "about" not in kw:
        kw["time"] = 0.2
    return ["call", i, verb, args, kw]


def generate(seed: int, n_subjects: Optional[int] = None, n_ops: Optional[int] = None) -> dict:
    rng = random.Random(seed)
    n_subjects = n_subjects or rng.randint(1, 3)
    subjects = []
    for _ in range(n_subjects):
        subjects.append({"kind": rng.choice(KINDS), "base": rng.choice(BASES),
                         "link": rng.choice(LINKS)})
    ops = []
    for _ in range(n_ops or rng.randint(3, 12)):
        i = rng.randrange(len(subjects))
        r = rng.random()
        if r < 0.75:
            ops.append(gen_call(rng, i))
        elif r < 0.87:
            ops.append(["read", i, rng.choice(["sorted", "reversed"])])
        elif r < 0.94 and len(subjects) + sum(o[0] == "clone" for o in ops) < 5:
            ops.append(["clone", i])
        else:
            ops.append(["unlink", i])
    return {"seed": seed, "subjects": subjects, "ops": ops}


def mutate(program: dict, rng: random.Random) -> dict:
    """Corpus mutation: add, delete or duplicate an op, or perturb a number."""
    p = json.loads(json.dumps(program))
    ops = p["ops"]
    r = rng.random()
    n = len(p["subjects"])
    if r < 0.3 or not ops:
        ops.insert(rng.randint(0, len(ops)), gen_call(rng, rng.randrange(n)))
    elif r < 0.5:
        ops.pop(rng.randrange(len(ops)))
    elif r < 0.7:
        j = rng.randrange(len(ops))
        ops.insert(j, json.loads(json.dumps(ops[j])))
    else:
        calls = [o for o in ops if o[0] == "call" and o[3]]
        if calls:
            o = rng.choice(calls)
            k = rng.randrange(len(o[3]))
            o[3][k] = round(o[3][k] * rng.choice([-1, 0.5, 2, 1.01]) + rng.choice([0, 0.5]), 3)
    p["seed"] = rng.randrange(1 << 30)
    return p


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

@dataclass
class Subject:
    obj: object
    kind: str
    link: object
    shadow: Optional[S.Shadow]
    swapped: bool = False        # a copy / clone swap: compare drawn and pose only


@dataclass
class Trace:
    rows: List[list] = field(default_factory=list)      # per top-level op: [obs per subject]
    shadow_bad: List[str] = field(default_factory=list)
    refusals: List[Tuple[int, int, str]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)     # a non-author exception


def _fingerprint(obj):
    """Cold reads (``diff_support.fingerprint``): they keep the fast path."""
    from diff_support import fingerprint
    host = getattr(obj, "_alias_of", None)       # a reversed() view keeps no pose of its own
    try:
        fp = fingerprint(host if host is not None else obj)
    except Exception as exc:  # noqa: BLE001
        return ("raises", type(exc).__name__)
    out = {"center": tuple(round(v, 4) + 0.0 for v in fp.get("center", ())),
           "angle": round(fp["angle"] % 360.0, 4) % 360.0 if "angle" in fp else None,
           "prims": fp.get("prims")}
    return out


def _free(sub: Subject) -> bool:
    """No link into or out of the subject's own fields: the fast-path case."""
    return (sub.link is None or sub.link.name in ("none", "source")) and not G.is_relational(sub.obj)


def _observe(sub: Subject, cold: bool = False):
    obj = sub.obj
    # The cold fingerprint reads raw stores (engine readers): a linked subject
    # may hold a value its next pull refreshes, so only a free one is compared.
    fp = _fingerprint(obj) if _free(sub) else None
    if cold:
        return {"fp": fp}
    try:
        d = G.as_set(G.drawn(obj), 4)
    except Exception as exc:  # noqa: BLE001
        return ("raises", type(exc).__name__)
    parts = {}
    if not sub.swapped:
        for n, f in G.point_parts(obj).items():
            v = G.safe(f)
            parts[n] = v if isinstance(v, G.ReadError) else (round(v[0], 4) + 0.0, round(v[1], 4) + 0.0)
    a = G.safe(lambda: float(obj.angle))
    heading = None if isinstance(a, G.ReadError) else round(a % 360.0, 4) % 360.0
    sc = G.safe(lambda: float(obj.scale))
    scale = None if isinstance(sc, G.ReadError) else round(sc, 6)
    flags = (getattr(obj, "flip_x", None), getattr(obj, "flip_y", None))
    return {"fp": fp, "drawn": d, "parts": parts, "heading": heading, "scale": scale, "flags": flags}


def _call(obj, verb, args, kw):
    kw = dict(kw)
    if "about" in kw:
        kw["about"] = tuple(kw["about"])
    timed = "time" in kw
    if verb == "flip_x":
        obj.flip_x = not obj.flip_x
    elif verb == "flip_y":
        obj.flip_y = not obj.flip_y
    elif verb == "angle=":
        obj.angle = args[0]
    else:
        getattr(obj, verb)(*args, **kw)
    if timed:
        G.settle(1.0)


def _map(sub: Subject, verb, args, kw):
    """The call's affine map and pose update, from the shadow (H1)."""
    s = sub.shadow
    obj = sub.obj
    about = tuple(kw["about"]) if "about" in kw else None
    c = s.center()
    if verb == "move_by":
        return S.translate(args[0], args[1]), None
    if verb == "move_to":
        return S.translate(args[0] - c[0], args[1] - c[1]), None
    if verb == "rotate_by":
        return S.rotate_about(about or c, args[0]), ("turn", args[0])
    if verb == "rotate_to":
        return S.rotate_about(c, args[0] - s.heading), ("set", args[0])
    if verb == "angle=":
        name = S.placement_name(obj)
        if name == "lean":
            return None, None
        pivot = s.part(name) if name in s.parts0 else c
        return S.rotate_about(pivot, args[0] - s.heading), ("set", args[0])
    if verb == "scale_by":
        g = S.geom_factor(s, args[0])
        return S.scale_about(about or c, g), ("scale", args[0])
    if verb == "scale_to":
        k = args[0] / s.scale if s.scale else 1.0
        g = S.geom_factor(s, k)
        return S.scale_about(c, g), ("scale", k)
    if verb in ("flip_x", "flip_y"):
        return S.mirror_about(c, verb[-1]), ("flip", verb[-1])
    return None, None


def _applies(obj, verb) -> bool:
    if G.is_box(obj):
        return verb in ("rotate_by", "rotate_to")
    if verb in ("flip_x", "flip_y"):
        return G.can_flip(obj)
    if verb == "angle=":
        return S.placement_name(obj) != "lean"
    return True


def _shadow_ok(sub: Subject) -> bool:
    """Relational shapes keep their constraint cells; the fuzzer's shadow is
    rigid, so it follows only free subjects (H1 covers the constraint cells)."""
    return sub.shadow is not None and not G.is_relational(sub.obj)


def build_pool(w, program, cold: bool = False) -> List[Subject]:
    """The program's subjects. ``cold``: no shadow is built (a shadow reads
    every part, which would take a cold twin off the pose fast path)."""
    pool = []
    if cold:
        for spec in program["subjects"]:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                obj = w.track(A.build(spec["kind"]))
                if getattr(obj, "_ref", None) is not None:
                    w.track(obj._ref)
                try:
                    got = A.apply_base(spec["base"], obj, w)
                except Exception:  # noqa: BLE001
                    got = None
                if got is None:
                    obj = w.track(A.build(spec["kind"]))      # the base does not apply
                else:
                    obj = got
                lk = A.apply_link(spec["link"], obj, w) or A.LinkCtx("none")
            pool.append(Subject(obj, spec["kind"], lk, None))
        return pool
    for spec in program["subjects"]:
        # Keep whatever applies — the base, the link, or both — in the order the
        # cold pool uses, so both sides build the same subject.
        made = None
        for base, link in ((spec["base"], spec["link"]), (spec["base"], "none"),
                           ("fresh", spec["link"]), ("fresh", "none")):
            made = S.make_subject(w, spec["kind"], base, link)
            if made is not None and not isinstance(made, dict):
                break
        if made is None or isinstance(made, dict):
            obj = w.track(A.build(spec["kind"]))
            pool.append(Subject(obj, spec["kind"], A.LinkCtx("none"), S.Shadow(obj, spec["kind"])))
            continue
        obj, sh, lk = made
        pool.append(Subject(obj, spec["kind"], lk, sh))
    return pool


def _exec(op, pool, w, trace, x, shadow, depth=0):
    kind = op[0]
    if kind == "batch":
        from diff_support import in_batch
        in_batch(lambda: [_exec(o, pool, w, trace, x, shadow, depth + 1) for o in op[1]])
        return
    i = op[1] % len(pool)
    sub = pool[i]
    obj = sub.obj
    if kind == "read":
        names = sorted(G.point_parts(obj))
        if op[2] == "reversed":
            names = names[::-1]
        parts = G.point_parts(obj)
        for n in names:
            G.safe(parts[n])
        return
    if kind == "clone":
        if G.is_box(obj):
            return
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                c = w.track(obj.clone())
        except Exception as exc:  # noqa: BLE001
            trace.refusals.append((len(trace.rows), i, type(exc).__name__))
            return
        pool.append(Subject(c, sub.kind, A.LinkCtx("none"),
                            S.Shadow(c, sub.kind) if sub.shadow is not None else None, sub.swapped))
        return
    if kind == "unlink":
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                obj.unlink_all()
        except Exception as exc:  # noqa: BLE001
            trace.refusals.append((len(trace.rows), i, type(exc).__name__))
        sub.link = A.LinkCtx("none")
        if sub.shadow is not None:
            sub.shadow = S.Shadow(obj, sub.kind)      # a relational shape may turn free (Q3b)
        return
    if kind in ("swap_clone", "swap_copy"):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if kind == "swap_clone":
                new = w.track(obj.clone())
            else:
                new = w.track(A.build(op[2], dict(G.P0, x=-30.0, y=45.0)))
                new << obj
        # The copy continues where the source was: a new shadow from its state.
        pool[i] = Subject(new, sub.kind, A.LinkCtx("none"),
                          S.Shadow(new, sub.kind) if sub.shadow is not None else None,
                          swapped=sub.swapped or kind == "swap_copy")
        return
    if kind == "via_move_by":
        c = G.center_of(obj)
        op = ["call", op[1], "move_by", [op[2] - c[0], op[3] - c[1]], {}]
        kind = "call"
    elif kind == "via_rotate_by":
        op = ["call", op[1], "rotate_by", [op[2] - float(obj.angle)], {}]
        kind = "call"
    if kind != "call":
        return
    _, _, verb, args, kw = op
    if not _applies(obj, verb):
        return
    m = pose = None
    if shadow and _shadow_ok(sub):
        m, pose = _map(sub, verb, args, kw)
        if verb == "rotate_by" and "time" in kw:
            sub.shadow.pending_turn = 0.0
    before = S.snapshot(obj) if (shadow and sub.link is not None and sub.link.name not in ("none", "source")) else None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with A.execution(x, obj):
                _call(obj, verb, args, kw)
    except LinkedAttributeError:
        trace.refusals.append((len(trace.rows), i, "LinkedAttributeError"))
        if before is not None:
            diff = S.compare_snapshots(before, S.snapshot(obj))
            if diff:
                label = verb + (" timed" if "time" in kw else "")
                trace.shadow_bad.append(f"{sub.kind} | {label} | refusal changed {diff[0]}")
        return
    except (Exception, RecursionError) as exc:  # noqa: BLE001
        from hypothesis_support import leak_message
        if leak_message(exc) is not None:
            trace.errors.append(f"{sub.kind} | {verb} | {type(exc).__name__}: {str(exc)[:120]}")
        trace.refusals.append((len(trace.rows), i, type(exc).__name__))
        return
    if m is not None and shadow and _shadow_ok(sub):
        sub.shadow.push(m)
        S._update_pose(sub.shadow, pose)
        bad = S.check(sub.obj, sub.shadow, sorted(G.point_parts(obj)))
        if sub.link is not None and sub.link.sink is not None:
            pin = G.safe(lambda: G.xy(sub.link.sink))
            if isinstance(pin, G.ReadError) or not A.close_xy(pin, sub.shadow.center()):
                bad["link sink"] = ""
        for k in bad:
            trace.shadow_bad.append(f"{sub.kind} | {verb} | {k}")
        if bad:
            sub.shadow = S.Shadow(obj, sub.kind)       # report once, then follow from here


def run(w, program, *, x: str = "normal", shadow: bool = True, aligned: Optional[List[int]] = None) -> Trace:
    """Execute ``program`` in world ``w``. ``aligned``: indexes of ops after
    which to observe (default: every op). ``x="cold"``: observe through cold
    readers only, so free subjects stay on the pose fast path."""
    G.reset_clock()
    trace = Trace()
    cold = x == "cold"
    pool = build_pool(w, program, cold)
    run_x = "normal" if cold else x
    for k, op in enumerate(program["ops"]):
        if not (cold and op[0] == "read"):     # a read would warm a cold twin's subject
            _exec(op, pool, w, trace, run_x, shadow and not cold)
        if aligned is None or k in aligned:
            trace.rows.append([_observe(s, cold) for s in pool[:len(program["subjects"])]])
    return trace


def save(path, program) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(program, fh, indent=0)


def load(path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
