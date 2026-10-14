"""Semantics-preserving rewrites of a fuzz program (geometry campaign, H10).

Not a test module. Each rewrite is one law of ``geom_laws`` turned into a
program transformation: P and P′ must end every original operation in the
same observable state (drawn set, parts, heading modulo 360, scale, flags) and
refuse the same calls with the same exception type. The program is kept as
**groups** — one group per original operation — so an expansion stays aligned
with the operation it replaces.

========================  ===================================================
split_rotate              ``rotate_by(a)`` → ``rotate_by(b); rotate_by(a - b)``
split_move                ``move_by(v)`` → two moves that add up to ``v``
split_scale               ``scale_by(k)`` → ``scale_by(k1); scale_by(k / k1)``
identity_flip             append ``flip_x`` twice after an op
identity_move             append ``move_by(v); move_by(-v)``
identity_scale            append ``scale_by(k); scale_by(1 / k)`` (``k > 1`` first:
                          the ``MIN_SCALE`` clamp keeps that an identity)
timed_to_instant          ``rotate_by(a, time=)`` (settled) ↔ the instant form
move_to_as_move_by        ``move_to(p)`` → ``move_by(p - center)`` (read at run time)
rotate_to_as_rotate_by    ``rotate_to(t)`` → ``rotate_by(t - angle)`` (run time)
wrap_batch                a run of calls inside one frame batch
extra_reads               insert reads (warmth, read order)
swap_clone                continue on a clone (no links, nothing reads it)
swap_copy                 continue on ``fresh << s`` of another model
reorder                   swap two calls on unrelated free subjects
x_twin                    run P′ forced slow, with caches dropped, or cold (observed
                          through cold readers only: the pose fast path stays on)
========================  ===================================================
"""
from __future__ import annotations

import json
import random
from typing import Callable, Dict, List, Optional, Tuple

COPY_TWINS = {
    "Line": "Line center_length", "Circle": "Circle two_points", "Ellipse": "Ellipse focal_points",
    "Rect": "Rect corner_corner", "Square": "Square top_left_length",
    "Triangle": "Triangle vertex_side",
}


def to_groups(program) -> List[List[list]]:
    return [[json.loads(json.dumps(op))] for op in program["ops"]]


def from_groups(program, groups) -> Tuple[dict, List[int]]:
    ops, aligned, k = [], [], -1
    for g in groups:
        ops.extend(g)
        k += len(g)
        aligned.append(k)
    p = dict(program)
    p["ops"] = ops
    return p, aligned


def _calls(groups, verb=None):
    out = []
    for gi, g in enumerate(groups):
        for oi, op in enumerate(g):
            if op[0] == "call" and (verb is None or op[2] == verb):
                out.append((gi, oi, op))
    return out


def _free(program, i) -> bool:
    if i >= len(program["subjects"]):
        return False
    spec = program["subjects"][i]
    return spec["link"] == "none"


def _not_read_by_others(program, i) -> bool:
    return all(s["link"] not in ("source", "chain", "whole") for s in program["subjects"])


def split_rotate(program, groups, rng):
    cands = [c for c in _calls(groups, "rotate_by") if "time" not in c[2][4]]
    if not cands:
        return None
    gi, oi, op = rng.choice(cands)
    a = op[3][0]
    b = round(rng.uniform(-200, 200), 2)
    first = ["call", op[1], "rotate_by", [b], dict(op[4])]
    second = ["call", op[1], "rotate_by", [round(a - b, 6)], dict(op[4])]
    groups[gi][oi:oi + 1] = [first, second]
    return groups


def split_move(program, groups, rng):
    cands = [c for c in _calls(groups, "move_by") if "time" not in c[2][4]]
    if not cands:
        return None
    gi, oi, op = rng.choice(cands)
    dx, dy = op[3]
    ax, ay = round(rng.uniform(-20, 20), 2), round(rng.uniform(-20, 20), 2)
    groups[gi][oi:oi + 1] = [["call", op[1], "move_by", [ax, ay], {}],
                             ["call", op[1], "move_by", [round(dx - ax, 6), round(dy - ay, 6)], {}]]
    return groups


def split_scale(program, groups, rng):
    cands = [c for c in _calls(groups, "scale_by") if "time" not in c[2][4]]
    if not cands:
        return None
    gi, oi, op = rng.choice(cands)
    k = op[3][0]
    if not isinstance(k, (int, float)) or k <= 0:
        return None                        # a refused factor cannot be split into one that runs
    k1 = rng.choice([1.25, 2.0])               # up first: the MIN_SCALE clamp stays an identity
    groups[gi][oi:oi + 1] = [["call", op[1], "scale_by", [k1], dict(op[4])],
                             ["call", op[1], "scale_by", [k / k1], dict(op[4])]]
    return groups


def _append(groups, rng, ops):
    gi = rng.randrange(len(groups))
    groups[gi].extend(ops)
    return groups


def identity_flip(program, groups, rng):
    i = rng.randrange(len(program["subjects"]))
    axis = rng.choice(["flip_x", "flip_y"])
    return _append(groups, rng, [["call", i, axis, [], {}], ["call", i, axis, [], {}]])


def identity_move(program, groups, rng):
    i = rng.randrange(len(program["subjects"]))
    dx, dy = round(rng.uniform(-30, 30), 2), round(rng.uniform(-30, 30), 2)
    return _append(groups, rng, [["call", i, "move_by", [dx, dy], {}],
                                 ["call", i, "move_by", [-dx, -dy], {}]])


def identity_scale(program, groups, rng):
    i = rng.randrange(len(program["subjects"]))
    k = rng.choice([1.25, 2.0])
    return _append(groups, rng, [["call", i, "scale_by", [k], {}],
                                 ["call", i, "scale_by", [1.0 / k], {}]])


def timed_to_instant(program, groups, rng):
    cands = [c for c in _calls(groups) if c[2][2] in ("rotate_by", "move_by", "scale_by")]
    if not cands:
        return None
    gi, oi, op = rng.choice(cands)
    kw = dict(op[4])
    if "time" in kw:
        kw.pop("time")
    elif "about" not in kw:
        kw["time"] = 0.2
    else:
        return None
    groups[gi][oi] = ["call", op[1], op[2], list(op[3]), kw]
    return groups


def move_to_as_move_by(program, groups, rng):
    cands = _calls(groups, "move_to")
    if not cands:
        return None
    gi, oi, op = rng.choice(cands)
    groups[gi][oi] = ["via_move_by", op[1], op[3][0], op[3][1]]
    return groups


def rotate_to_as_rotate_by(program, groups, rng):
    cands = _calls(groups, "rotate_to")
    if not cands:
        return None
    gi, oi, op = rng.choice(cands)
    groups[gi][oi] = ["via_rotate_by", op[1], op[3][0]]
    return groups


def wrap_batch(program, groups, rng):
    gi = rng.randrange(len(groups))
    calls = [op for op in groups[gi] if op[0] == "call" and "time" not in op[4]]
    if not calls or len(calls) != len(groups[gi]):
        return None
    groups[gi] = [["batch", groups[gi]]]
    return groups


def extra_reads(program, groups, rng):
    i = rng.randrange(len(program["subjects"]))
    gi = rng.randrange(len(groups))
    groups[gi].insert(rng.randint(0, len(groups[gi])), ["read", i, rng.choice(["sorted", "reversed"])])
    return groups


def swap_clone(program, groups, rng):
    i = rng.randrange(len(program["subjects"]))
    if not _free(program, i) or not _not_read_by_others(program, i):
        return None
    if program["subjects"][i]["kind"].endswith("reversed"):
        return None                        # a view's clone is a free points track (another object)
    if program["subjects"][i]["kind"].startswith(("Line parallel", "Line perpendicular", "Line tangent",
                                                    "Ellipse from_rect")):
        return None                        # a relational source's clone is its free twin
    gi = rng.randrange(len(groups))
    groups[gi].append(["swap_clone", i])
    return groups


def swap_copy(program, groups, rng):
    i = rng.randrange(len(program["subjects"]))
    spec = program["subjects"][i]
    fam = spec["kind"].split()[0]
    if fam not in COPY_TWINS or not _free(program, i) or not _not_read_by_others(program, i):
        return None
    if any(w in spec["kind"] for w in ("parallel", "perpendicular", "tangent", "from_rect")):
        return None
    gi = rng.randrange(len(groups))
    groups[gi].append(["swap_copy", i, COPY_TWINS[fam]])
    return groups


def reorder(program, groups, rng):
    for _ in range(4):
        gi = rng.randrange(max(1, len(groups) - 1))
        if gi + 1 >= len(groups):
            return None
        a, b = groups[gi], groups[gi + 1]
        if len(a) == 1 and len(b) == 1 and a[0][0] == "call" and b[0][0] == "call" \
                and a[0][1] != b[0][1] and _free(program, a[0][1]) and _free(program, b[0][1]) \
                and _not_read_by_others(program, a[0][1]):
            # Observation is per group: swap the ops, keep the group order.
            groups[gi], groups[gi + 1] = [b[0]], [a[0]]
            return ("reordered", gi, groups)
    return None


REWRITES: Dict[str, Callable] = {
    "split_rotate": split_rotate, "split_move": split_move, "split_scale": split_scale,
    "identity_flip": identity_flip, "identity_move": identity_move,
    "identity_scale": identity_scale, "timed_to_instant": timed_to_instant,
    "move_to_as_move_by": move_to_as_move_by, "rotate_to_as_rotate_by": rotate_to_as_rotate_by,
    "wrap_batch": wrap_batch, "extra_reads": extra_reads, "swap_clone": swap_clone,
    "swap_copy": swap_copy, "reorder": reorder,
}
X_TWINS = ("normal", "forced_slow", "caches_dropped", "cold")


def rewrite(program, rng, n: int = 3) -> Tuple[dict, List[int], List[str], str, Optional[int]]:
    """Stack up to ``n`` rewrites. Returns (P′, aligned, names, x twin, reordered
    group or None: the two swapped groups are compared only after both ran)."""
    groups = to_groups(program)
    used, swapped_at = [], None
    if not groups or not program["subjects"]:
        return dict(program), list(range(len(groups))), [], "normal", None
    names = list(REWRITES)
    for _ in range(n):
        name = rng.choice(names)
        if name == "reorder" and swapped_at is not None:
            continue                       # one swap per program: only its row is excused
        out = REWRITES[name](program, groups, rng)
        if out is None:
            continue
        if isinstance(out, tuple) and out[0] == "reordered":
            swapped_at = out[1]
            groups = out[2]
        else:
            groups = out
        used.append(name)
    x = rng.choice(X_TWINS)
    if x != "normal":
        used.append(f"x_twin:{x}")
    p2, aligned = from_groups(program, groups)
    return p2, aligned, used, x, swapped_at
