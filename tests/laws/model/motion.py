"""P laws: motion under ``resolve`` (design/Laws.md, "Motion").

Input: ``M`` events — every resolve body's raw pose, velocity and mass just
before and just after each resolve (``Recorder.motion``), and the pairs the
solver answered. Bounds, not predictions: an exact physics model would
re-implement the solver and share its bugs. Shapes: circles and Rects
(axis-aligned for the overlap bound); other kinds abstain.

P1  After resolve, a resolved pair overlaps by at most the slop (stacks are
    a documented non-goal: a pair whose body touches two resolved partners
    abstains).
P2  Resolve adds no energy: a body answered only by still STATIC partners
    leaves no faster than it came (bounce ≤ 1).
P3  Between two movable bodies answered only by each other, momentum is
    kept. A body with no ``.vel`` is infinite mass in the impulse, like
    STATIC (Collision Design, Resolution step 3): such a pair abstains (the
    11th body field; S7 found the model counting a velocity-less brick).
P4  A STATIC body never moves under resolve.
P5  A body with no sideways velocity, answered only by still STATIC
    partners (and not riding a partner that moved), is not moved sideways
    by resolve (an idle body on a ramp does not creep, PE2). Only in a
    world with a floor (``collision.floor``, recorded per resolve step):
    seen from above, nothing rests on anything (V10).
"""
from __future__ import annotations

import math
from typing import Dict, List, Tuple

from laws.model.base import Report, Trace

LAWS = ("P1", "P2", "P3", "P4", "P5")


def _has_vel(body) -> bool:
    """The body's ``.vel`` is set (recorded since S7; older traces: assume so)."""
    return body[10] if len(body) > 10 else True

SLOP = 0.08            # scena.collision._RESOLVE_SLOP, a declared parameter (pinned by a test)
POS_BUDGET = 0.5       # DU (design/Laws.md, budgets)
SPEED_BUDGET = 0.02
EPS = 1e-6
# P5's "resting": slower than this after the last resolve, against the same
# surface. One frame of gravity on a slope leaves a few DU/s along it (an idle
# platformer hero: ~6 DU/s on 25°); a body falling onto a corner leaves
# hundreds (it slides there, PE6).
REST_SPEED = 50.0


def _overlap(a, b):
    """Penetration depth of two bodies (circle / axis-aligned rect), or None."""
    ka, kb = a[1], b[1]
    if "other" in (ka, kb):
        return None                    # a Sprite collides as its hitbox: no outline here
    if ka == "circle" and kb == "circle":
        d = math.hypot(a[2] - b[2], a[3] - b[3])
        return (a[7] + b[7]) - d
    if ka == "rect" and kb == "rect":
        if a[9] % 90 or b[9] % 90:
            return None
        ox = (a[7] + b[7]) / 2 - abs(a[2] - b[2])
        oy = (a[8] + b[8]) / 2 - abs(a[3] - b[3])
        return min(ox, oy)
    c, r = (a, b) if ka == "circle" else (b, a)
    if r[9] % 90:
        return None
    hw, hh = r[7] / 2, r[8] / 2
    dx, dy = c[2] - r[2], c[3] - r[3]
    if abs(dx) <= hw and abs(dy) <= hh:            # center inside the rect
        return c[7] + min(hw - abs(dx), hh - abs(dy))
    qx = max(-hw, min(hw, dx))
    qy = max(-hh, min(hh, dy))
    return c[7] - math.hypot(dx - qx, dy - qy)


def check(tr: Trace, rep: Report) -> None:
    prev_post: Dict[str, tuple] = {}
    prev_partners: Dict[str, List[str]] = {}
    pre: Dict[str, tuple] = {}
    floor = True
    for i, e in enumerate(tr.events):
        if e[0] != "M":
            continue
        f = tr.frames[i]
        if e[1] == "pre":
            pre = {b[0]: b for b in e[2] if b[0]}
            floor = e[3] if len(e) > 3 else True
            continue
        post = {b[0]: b for b in e[2] if b[0]}
        # A partner the recorder cannot name still counts as a partner: its
        # pair is not checked, but the bodies it touched are not "answered
        # only by each other" (a body made during the step once read ``?``
        # and a three-body solve was checked as a pair: P3, tutorial 32).
        pairs = [p for p in e[3] if "?" not in p]
        partners: Dict[str, List[str]] = {}
        for a, b in e[3]:
            partners.setdefault(a, []).append(b)
            partners.setdefault(b, []).append(a)

        def still_static(label):
            b0, b1 = pre.get(label), prev_post.get(label)
            return (b0 is not None and math.isinf(b0[6]) and b1 is not None
                    and abs(b0[2] - b1[2]) <= EPS and abs(b0[3] - b1[3]) <= EPS)

        for label, b1 in post.items():
            b0 = pre.get(label)
            if b0 is None:
                continue
            static = math.isinf(b0[6])
            if static:
                rep.witness("P4")
                if abs(b1[2] - b0[2]) > EPS or abs(b1[3] - b0[3]) > EPS:
                    rep.find("P4", f, f"STATIC {label} moved by resolve "
                             f"({b1[2] - b0[2]:+.4f}, {b1[3] - b0[3]:+.4f})", label.rsplit("#", 1)[0])
                continue
            ps = partners.get(label, [])
            if ps and all(still_static(p) for p in ps):
                v0 = math.hypot(b0[4], b0[5])
                v1 = math.hypot(b1[4], b1[5])
                rep.witness("P2")
                if v1 > v0 * (1 + SPEED_BUDGET) + EPS:
                    rep.find("P2", f, f"{label} left faster ({v1:.3f}) than it came ({v0:.3f})",
                             label.rsplit("#", 1)[0])
                # A rider is carried with its partner's displacement inside
                # resolve (PB2, full carry): a partner of the last step that
                # moved since makes the sideways move the carry's.
                riding = any(not still_static(p) for p in prev_partners.get(label, ()))
                # Idle: it ended the last resolve at rest on the same surface
                # (a body still falling onto a slope or a corner slides there:
                # no friction, PE6).
                last = prev_post.get(label)
                resting = (last is not None and math.hypot(last[4], last[5]) <= REST_SPEED
                           and set(prev_partners.get(label, ())) & set(ps))
                # No sideways motion of its own this frame: neither velocity
                # nor a direct ``move_by`` (a walker moving by ``move_by``
                # keeps ``vel.x`` at 0; caverna's robot).
                walked = last is not None and abs(b0[2] - last[2]) > EPS
                # P5 is a law of a world with a floor: seen from above an idle
                # body against a slanted wall may slide (V10, no down).
                if floor and abs(b0[4]) <= EPS and not riding and resting and not walked:
                    rep.witness("P5")
                    if abs(b1[2] - b0[2]) > EPS:
                        rep.find("P5", f, f"{label} with no sideways velocity moved "
                                 f"{b1[2] - b0[2]:+.6f} sideways", label.rsplit("#", 1)[0])
        for a, b in pairs:
            ba, bb = post.get(a), post.get(b)
            if ba is None or bb is None:
                continue
            if len(partners.get(a, ())) == 1 and len(partners.get(b, ())) == 1:
                d = _overlap(ba, bb)
                if d is not None:
                    rep.witness("P1")
                    if d > SLOP + POS_BUDGET:
                        rep.find("P1", f, f"{a} and {b} overlap {d:.3f} after resolve",
                                 f"{a.rsplit('#', 1)[0]}|{b.rsplit('#', 1)[0]}")
                if not math.isinf(ba[6]) and not math.isinf(bb[6]) \
                        and _has_vel(ba) and _has_vel(bb):
                    a0, b0 = pre.get(a), pre.get(b)
                    if a0 is None or b0 is None:
                        continue
                    rep.witness("P3")
                    px0 = a0[6] * a0[4] + b0[6] * b0[4]
                    py0 = a0[6] * a0[5] + b0[6] * b0[5]
                    px1 = ba[6] * ba[4] + bb[6] * bb[4]
                    py1 = ba[6] * ba[5] + bb[6] * bb[5]
                    scale = max(1.0, math.hypot(px0, py0))
                    if math.hypot(px1 - px0, py1 - py0) > SPEED_BUDGET * scale:
                        rep.find("P3", f, f"momentum of {a} + {b} changed "
                                 f"({px0:.2f}, {py0:.2f}) -> ({px1:.2f}, {py1:.2f})",
                                 f"{a.rsplit('#', 1)[0]}|{b.rsplit('#', 1)[0]}")
        prev_post = post
        prev_partners = partners
