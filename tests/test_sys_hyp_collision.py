"""Collision engine vs brute-force oracles over real frames (Hypothesis).

Random bodies on two tags (``ha`` × ``hb``, one ``@collide`` / ``@collide_exit``
pair) move by placement, get destroyed, or toggle ``collidable`` between real
frames. After every frame (Collision Design § Pipeline / Handlers):

* the open-contact set (built only from enter / exit handler calls) equals the
  oracle — exact circle geometry for circle-only worlds, and the engine's
  own one-shot ``test_collision`` over every pair for mixed shapes (that
  checks the broad phase, proxy AABBs and bookkeeping, not the narrow test);
* per pair, enter and exit alternate (never two enters, never an exit
  without an enter);
* a destroyed or non-collidable body has an exit for every open pair;
* creation order does not change the contact set;
* fast ``move_by`` circles match an exact swept oracle (a fast body's path
  counts, not only its end pose — Collision Design § Swept detection);
* shifting / moving every body by the same offset keeps the contact set, except
  for pairs within ``TANGENT_EPS`` of zero gap (Collision Design § Touching and
  tangency: at exact tangency either answer is allowed).

    python -m unittest tests.test_sys_hyp_collision -v
"""
from __future__ import annotations

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis import assume, example, given, note, strategies as hst  # noqa: E402

from system_support import quiet, system_world  # noqa: E402

from scena import Circle, Polygon, Rect, collide, collide_exit  # noqa: E402
# Aliased: a module-level ``test_*`` name would be collected by pytest.
from scena import test_collision as one_shot_overlap  # noqa: E402
from scena.collision import _gjk_distance, snapshot_shape  # noqa: E402

coord = hst.integers(-60, 60).map(float)
circle_spec = hst.tuples(hst.just("circle"), hst.sampled_from(["ha", "hb"]),
                         coord, coord, hst.integers(2, 25).map(float), hst.just(0.0))
any_spec = hst.tuples(
    hst.sampled_from(["circle", "rect", "polygon"]), hst.sampled_from(["ha", "hb"]),
    coord, coord, hst.integers(3, 25).map(float),
    hst.sampled_from([0.0, 15.0, 45.0, 90.0, 130.0]))


def op_strategy(n_max):
    i = hst.integers(0, n_max - 1)
    return hst.one_of(
        hst.tuples(hst.just("move"), i, coord, coord),
        hst.tuples(hst.just("destroy"), i, hst.none(), hst.none()),
        hst.tuples(hst.just("collidable"), i, hst.booleans(), hst.none()),
        hst.tuples(hst.just("step"), hst.none(), hst.none(), hst.none()),
    )


def _build(spec):
    kind, tag, x, y, size, rot = spec
    with quiet():
        if kind == "circle":
            return Circle(center=(x, y), radius=size, group=tag)
        if kind == "rect":
            return Rect(center=(x, y), width=size * 2, height=size, angle=rot, group=tag)
        # Dyadic fractions: vertices stay exact under a whole-number shift
        # (TestTranslation), so a far-away copy is the same polygon bit for bit.
        pts = [(x - size, y - size * 0.5), (x + size, y - size * 0.25), (x + size * 0.25, y + size)]
        return Polygon(points=pts, group=tag)


class ContactModel:
    """Open contacts as reported by the handlers, with alternation checks."""

    def __init__(self):
        self.open = set()
        self.errors = []

    def enter(self, a, b, info=None):
        k = (id(a), id(b))
        if k in self.open:
            self.errors.append(("double enter", k))
        self.open.add(k)

    def exit(self, a, b, info=None):
        k = (id(a), id(b))
        if k not in self.open:
            self.errors.append(("exit without enter", k))
        self.open.discard(k)


def _circle_overlap(a, b):
    d = math.hypot(a.center.x - b.center.x, a.center.y - b.center.y)
    return d < a.radius + b.radius


def _circle_near_boundary(bodies):
    for a in bodies:
        for b in bodies:
            if a is b:
                continue
            d = math.hypot(a.center.x - b.center.x, a.center.y - b.center.y)
            if abs(d - (a.radius + b.radius)) < 1e-6:
                return True
    return False


# Contract (Collision Design § Touching and tangency): touching counts, but at
# exactly zero gap either answer is allowed; float rounding decides, and a
# whole-number shift changes the rounding. A pair this close to zero gap is
# "either" in the translation properties (G2 in Testing Design).
TANGENT_EPS = 1e-6


def _clearance(a, b):
    """Signed separation: minus the depth when the engine reports a contact,
    else the true gap (GJK distance)."""
    info = one_shot_overlap(a, b)
    if info is not None:
        return -info.depth
    return _gjk_distance(snapshot_shape(a), snapshot_shape(b))[0]


class CollisionWorld:

    def __init__(self, testcase, w, specs):
        self.t = testcase
        self.w = w
        self.model = ContactModel()
        self.bodies = [w.track(_build(s)) for s in specs]

        @collide("ha", "hb")
        def _enter(a, b, info=None):
            self.model.enter(a, b)

        @collide_exit("ha", "hb")
        def _exit(a, b, info=None):
            self.model.exit(a, b)

    def live(self, tag):
        return [b for b in self.bodies
                if b.is_alive and tag in b.group and getattr(b, "collidable", True)]

    def expected(self, oracle):
        out = set()
        for a in self.live("ha"):
            for b in self.live("hb"):
                if a is not b and oracle(a, b):
                    out.add((id(a), id(b)))
        return out

    def borderline(self):
        """Pairs within ``TANGENT_EPS`` of zero gap, as body indexes."""
        idx = {id(b): j for j, b in enumerate(self.bodies)}
        return {(idx[id(a)], idx[id(b)])
                for a in self.live("ha") for b in self.live("hb")
                if a is not b and abs(_clearance(a, b)) < TANGENT_EPS}

    def open_indexes(self):
        idx = {id(b): j for j, b in enumerate(self.bodies)}
        return {(idx[a], idx[b]) for a, b in self.model.open}

    def _apply(self, op):
        kind, i, x, y = op
        if i is not None:
            i %= len(self.bodies)
            body = self.bodies[i]
            if not body.is_alive:
                return
        with quiet():
            if kind == "move":
                body.move_to(x, y)
            elif kind == "destroy":
                body.destroy()
            elif kind == "collidable":
                body.collidable = x
        if kind == "destroy" or (kind == "collidable" and not x):
            # Synchronous: the exits fire inside destroy() / the setter, not
            # at the next step (Collision Design § Handlers).
            left = [k for k in self.model.open if id(body) in k]
            self.t.assertEqual(left, [], f"{kind} left open contacts without an exit")
        if kind == "step":
            self.w.step(1)

    def check(self, oracle):
        self.w.step(1)
        self.t.assertEqual(self.model.errors, [], "enter / exit did not alternate")
        want = self.expected(oracle)
        got = {k for k in self.model.open
               if any(id(b) == k[0] and b.is_alive for b in self.bodies)
               and any(id(b) == k[1] and b.is_alive for b in self.bodies)}
        self.t.assertEqual(got, want, "open contacts differ from the oracle")
        dead_ids = {id(b) for b in self.bodies if not b.is_alive}
        stale = [k for k in self.model.open if k[0] in dead_ids or k[1] in dead_ids]
        self.t.assertEqual(stale, [], "a destroyed body kept an open contact (no exit)")


class TestCirclesAgainstGeometry(unittest.TestCase):

    @given(specs=hst.lists(circle_spec, min_size=2, max_size=10),
           ops=hst.lists(op_strategy(10), max_size=25))
    def test_contacts_match_exact_circle_overlap(self, specs, ops):
        with system_world(draw=False) as w:
            cw = CollisionWorld(self, w, specs)
            for op in [("step", None, None, None)] + ops:
                note(repr(op))
                cw._apply(op)
                live = [b for b in cw.bodies if b.is_alive]
                assume(not _circle_near_boundary(live))
                cw.check(_circle_overlap)


class TestMixedShapesAgainstPairwise(unittest.TestCase):

    @given(specs=hst.lists(any_spec, min_size=2, max_size=10),
           ops=hst.lists(op_strategy(10), max_size=20))
    def test_contacts_match_pairwise_exact_test(self, specs, ops):
        with system_world(draw=False) as w:
            cw = CollisionWorld(self, w, specs)
            oracle = lambda a, b: one_shot_overlap(a, b) is not None  # noqa: E731
            for op in [("step", None, None, None)] + ops:
                note(repr(op))
                cw._apply(op)
                cw.check(oracle)

    @given(specs=hst.lists(any_spec, min_size=2, max_size=8), seed=hst.randoms())
    def test_creation_order_does_not_change_contacts(self, specs, seed):
        def contacts(order):
            with system_world(draw=False) as w:
                cw = CollisionWorld(self, w, [specs[i] for i in order])
                w.step(1)
                inv = {id(b): order[j] for j, b in enumerate(cw.bodies)}
                return {(inv[a], inv[b]) for a, b in cw.model.open}

        order = list(range(len(specs)))
        shuffled = order[:]
        seed.shuffle(shuffled)
        self.assertEqual(contacts(order), contacts(shuffled))


# Whole-number shifts keep circle / axis-aligned geometry exact; the big ones
# land every body in far (and negative) broad-phase cells.
offset = hst.one_of(hst.integers(-100_000, 100_000),
                    hst.sampled_from([-65_536, -4096, -1, 1, 4096, 65_536])).map(float)


class TestTranslation(unittest.TestCase):
    """Moving every body by the same offset does not change who touches whom,
    except at exact tangency, where either answer is allowed.

    The other suites keep bodies within ±60 of the origin; this one checks the
    broad phase far away and the narrow phase's own consistency, with no oracle.
    A pair within ``TANGENT_EPS`` of zero gap in either world may differ: the
    engine does not promise translation-invariant rounding (G2).
    """

    def assertSameUpToTangency(self, base, moved):
        (got_a, near_a), (got_b, near_b) = base, moved
        differ = got_a ^ got_b
        self.assertLessEqual(
            differ, near_a | near_b,
            f"contacts differ on pairs that are not tangent: {sorted(differ - near_a - near_b)}")

    @given(specs=hst.lists(any_spec, min_size=2, max_size=8), dx=offset, dy=offset)
    def test_shifting_the_world_keeps_contacts(self, specs, dx, dy):
        def contacts(ox, oy):
            shifted = [(k, t, x + ox, y + oy, s, r) for k, t, x, y, s, r in specs]
            with system_world(draw=False) as w:
                cw = CollisionWorld(self, w, shifted)
                w.step(1)
                return cw.open_indexes(), cw.borderline()

        self.assertSameUpToTangency(contacts(0.0, 0.0), contacts(dx, dy))

    @given(specs=hst.lists(any_spec, min_size=2, max_size=8), dx=offset, dy=offset,
           steps=hst.sampled_from([1, 2, 4]))  # dyadic: dx / steps stays exact
    # G2: a Rect corner exactly on a Polygon edge. Built in place it is not a
    # contact; after move_by(0, 1) it is (1 ulp in the SAT projection).
    @example(specs=[("circle", "ha", 0.0, 0.0, 3.0, 0.0)] * 4
             + [("rect", "hb", 1.0, 2.0, 5.0, 0.0), ("polygon", "ha", 20.0, 3.0, 19.0, 0.0)],
             dx=0.0, dy=1.0, steps=1)
    def test_moving_the_world_keeps_contacts(self, specs, dx, dy, steps):
        """Same shift, applied with ``move_by`` over live frames (enrolled
        bodies re-bucket), must end where a world built there ends."""
        def contacts_after(move):
            with system_world(draw=False) as w:
                cw = CollisionWorld(self, w, specs)
                w.step(1)
                if move:
                    for _ in range(steps):
                        for b in cw.bodies:
                            b.move_by(dx / steps, dy / steps)
                        w.step(1)
                return cw.open_indexes(), cw.borderline()

        self.assertSameUpToTangency(contacts_after(False), contacts_after(True))


def _seg_min_dist(p0, p1):
    """Closest distance from the origin to the segment p0 -> p1, and its t."""
    ex, ey = p1[0] - p0[0], p1[1] - p0[1]
    ee = ex * ex + ey * ey
    t = 0.0 if ee == 0.0 else max(0.0, min(1.0, -(p0[0] * ex + p0[1] * ey) / ee))
    return math.hypot(p0[0] + t * ex, p0[1] + t * ey), t


fly = hst.tuples(hst.integers(0, 7), hst.integers(-150, 150).map(float),
                 hst.integers(-150, 150).map(float))


class TestFastMotionAgainstSweptOracle(unittest.TestCase):
    """Circles moved with ``move_by`` (motion, so swept when fast) against an
    exact oracle (Collision Design § Swept detection).

    A circle is fast when it travels more than its radius in a frame (half its
    thickness). After each frame, a pair is open when the circles overlap at
    the end pose, or when a side is fast and the relative path came within the
    radius sum — unless the pair was already open and overlapped at the start
    pose (that contact has ended). Enter / exit must alternate. Pairs within a
    small margin of tangency (start, end or closest approach) and circles
    within 1% of the fast threshold are skipped.
    """

    @given(specs=hst.lists(circle_spec, min_size=2, max_size=8),
           frames=hst.lists(hst.lists(fly, min_size=1, max_size=3), min_size=1, max_size=8))
    def test_contacts_match_swept_circle_oracle(self, specs, frames):
        margin = 1e-3
        with system_world(draw=False) as w:
            cw = CollisionWorld(self, w, specs)
            w.step(1)
            for moves in frames:
                note(repr(moves))
                start = {id(b): (b.center.x, b.center.y) for b in cw.bodies}
                delta = {}
                for i, dx, dy in moves:
                    b = cw.bodies[i % len(cw.bodies)]
                    ox, oy = delta.get(id(b), (0.0, 0.0))
                    delta[id(b)] = (ox + dx, oy + dy)
                for b in cw.bodies:
                    d = delta.get(id(b))
                    if d is not None:
                        assume(abs(math.hypot(*d) - b.radius) > 0.01 * b.radius)
                        b.move_by(*d)
                prev = set(cw.model.open)
                want = set()
                for a in cw.live("ha"):
                    for b in cw.live("hb"):
                        if a is b:
                            continue
                        r = a.radius + b.radius
                        a0, b0 = start[id(a)], start[id(b)]
                        p0 = (a0[0] - b0[0], a0[1] - b0[1])
                        p1 = (a.center.x - b.center.x, a.center.y - b.center.y)
                        d_end = math.hypot(*p1)
                        d_start = math.hypot(*p0)
                        d_min, _t = _seg_min_dist(p0, p1)
                        for dist in (d_end, d_start, d_min):
                            assume(abs(dist - r) > margin)
                        key = (id(a), id(b))
                        if d_end < r:
                            want.add(key)
                            continue
                        fast = any(math.hypot(*delta.get(id(c), (0.0, 0.0))) > c.radius
                                   for c in (a, b))
                        if fast and d_min < r and not (key in prev and d_start < r):
                            want.add(key)
                w.step(1)
                self.assertEqual(cw.model.errors, [], "enter / exit did not alternate")
                self.assertEqual(set(cw.model.open), want, "open contacts differ from the swept oracle")


class TestTangencyTolerance(unittest.TestCase):
    """The ``TANGENT_EPS`` escape hatch covers exact tangency and nothing else
    (so the translation properties cannot pass vacuously)."""

    def _clearance_of(self, spec_a, spec_b):
        with system_world(draw=False) as w:
            a, b = w.track(_build(spec_a)), w.track(_build(spec_b))
            return _clearance(a, b)

    def test_the_g2_corner_on_an_edge_is_tangent(self):
        rect = ("rect", "hb", 1.0, 2.0, 5.0, 0.0)
        poly = ("polygon", "ha", 20.0, 3.0, 19.0, 0.0)
        for dy in (0.0, 1.0, 4096.0):
            shifted = [(k, t, x, y + dy, s, r) for k, t, x, y, s, r in (rect, poly)]
            self.assertLess(abs(self._clearance_of(*shifted)), TANGENT_EPS, dy)

    def test_clear_and_overlapping_pairs_are_not_tangent(self):
        rect = ("rect", "hb", 0.0, 0.0, 5.0, 0.0)          # 10 x 5
        near = ("circle", "ha", 0.0, 2.5 + 3.0 + 1e-3, 3.0, 0.0)
        deep = ("circle", "ha", 0.0, 2.5 + 3.0 - 1e-3, 3.0, 0.0)
        self.assertAlmostEqual(self._clearance_of(rect, near), 1e-3, places=6)
        self.assertAlmostEqual(self._clearance_of(rect, deep), -1e-3, places=6)


if __name__ == "__main__":
    unittest.main()
