"""Laws campaign, stage S6: motion under ``resolve`` (P laws, E10–E14).

The continuous layer is checked by bounds and symmetries, never by an exact
prediction (an exact physics model would re-implement the solver and share
its bugs). On the motion twin (``tests/laws/twins/motion_world.py``: an idle
body on a ramp, a stack, a head-on hit, a rider on a lift, a ball in a box):

* the motion model (``tests/laws/model/motion.py``): P1 overlap ≤ slop, P2
  no energy gained, P3 momentum kept, P4 STATIC unmoved, P5 no sideways creep
  of an idle body; P6 (a rider moves with its lift) on the lift scene;
* E10 translation, E11 mirror, E12 mass scale, E14 world scale within the
  position budget; E13 pacing within one frame of travel;
* canaries (gate) through the engine's own switches (``_SKIN_ALONG_MOTION``,
  ``_SETTLE_STATIC_CLAMP``, ``_SWEEP_MASS_SPLIT``, ``_RIDER_CARRY``) and a
  left / right asymmetric bounce for E11.

    python -m unittest tests.test_laws_motion -v
"""
from __future__ import annotations

import os
import sys
import unittest
from collections import Counter
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import require_canaries  # noqa: E402
from laws import equations as eq, model  # noqa: E402
from laws.harness import record  # noqa: E402
from laws.model import motion  # noqa: E402
from laws.plants import col  # noqa: E402

FRAMES = 240


def _scene(scene, patches=()):
    return record(eq.MOTION, FRAMES, params={"scene": scene}, patches=patches,
                  motion=True, keep_going=bool(patches))


class TestScenes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reports = {s: _scene(s)[2] for s in eq.MOTION_SCENES}

    def test_no_finding(self):
        out = [f"{s}: {r.summary(3)}" for s, r in self.reports.items() if r.findings]
        self.assertEqual(out, [])

    def test_every_motion_law_is_witnessed(self):
        seen = Counter()
        for r in self.reports.values():
            seen.update(r.witnesses)
        self.assertEqual([law for law in motion.LAWS if not seen[law]], [], dict(seen))

    def test_the_slop_is_the_engines(self):
        self.assertEqual(motion.SLOP, col._RESOLVE_SLOP)


class TestRiderMovesWithItsLift(unittest.TestCase):
    """P6: a rider standing on a sideways lift moves with it (PB2, full carry)."""

    def test_rider_keeps_its_place_on_the_lift(self):
        traj = eq.motion_trajectory("lift")
        t0, t1 = 1.0, 4.0
        x0, x1 = traj[round(t0, 6)][0][0], traj[round(t1, 6)][0][0]
        self.assertAlmostEqual(x1 - x0, 60 * (t1 - t0), delta=eq.POS_BUDGET)


class TestInvariances(unittest.TestCase):
    def test_e10_translation(self):
        for s in eq.MOTION_SCENES:
            with self.subTest(scene=s):
                self.assertEqual(eq.motion_equation(s, {"ox": 65536.0, "oy": 4096.0}), [])

    def test_e11_mirror(self):
        for s in eq.MOTION_SCENES:
            with self.subTest(scene=s):
                self.assertEqual(eq.motion_equation(s, {"mirror": True}), [])

    def test_e12_mass_scale(self):
        for s in eq.MOTION_SCENES:
            with self.subTest(scene=s):
                self.assertEqual(eq.motion_equation(s, {"k": 10.0}), [])

    def test_e14_world_scale(self):
        for s in eq.MOTION_SCENES:
            with self.subTest(scene=s):
                self.assertEqual(eq.motion_equation(s, {"s": 2.0}), [])

    def test_e13_pacing(self):
        for s in eq.MOTION_SCENES:
            for dt in (1 / 30, 1 / 144):
                with self.subTest(scene=s, dt=dt):
                    self.assertEqual(eq.e13_pacing(s, dt), [])


# -- synthetic traces ---------------------------------------------------------

def body(label, x, y, vx=0.0, vy=0.0, mass=1.0, kind="circle", a=10.0, b=0.0, ang=0.0):
    return (label, kind, x, y, vx, vy, mass, a, b, ang)


INF = float("inf")


def frame_pair(pre, post, pairs):
    return [("M", "pre", tuple(pre)), ("M", "post", tuple(post), tuple(pairs))]


def found(ev, law):
    return [f for f in model.check(ev).findings if f.law == law]


class TestMotionRules(unittest.TestCase):
    W = body("W#0", 0, 0, mass=INF, kind="rect", a=100, b=20)

    def test_p4_a_static_body_moved_by_resolve_is_found(self):
        moved = body("W#0", 0, -0.5, mass=INF, kind="rect", a=100, b=20)
        ev = frame_pair([self.W], [moved], [])
        self.assertTrue(found(ev, "P4"))

    def test_p1_a_deep_overlap_is_found(self):
        ev = frame_pair([self.W, body("B#0", 0, 20)], [self.W, body("B#0", 0, 15)],
                        [("B#0", "W#0")])
        self.assertTrue(found(ev, "P1"))

    def test_p2_a_faster_bounce_is_found(self):
        still = frame_pair([self.W], [self.W], [])
        ev = still + frame_pair([self.W, body("B#0", 0, 20.1, vy=-100)],
                                [self.W, body("B#0", 0, 20.1, vy=150)], [("B#0", "W#0")])
        self.assertTrue(found(ev, "P2"))

    def test_p3_lost_momentum_is_found(self):
        a0, b0 = body("A#0", 0, 0, vx=10, mass=1), body("B#0", 19.9, 0, vx=-10, mass=3)
        a1, b1 = body("A#0", 0, 0, vx=-10, mass=1), body("B#0", 19.9, 0, vx=10, mass=3)
        self.assertTrue(found(frame_pair([a0, b0], [a1, b1], [("A#0", "B#0")]), "P3"))

    def test_p5_a_sideways_nudge_of_an_idle_body_is_found(self):
        rest = frame_pair([self.W, body("B#0", 0, 20.0, vy=-15)],
                          [self.W, body("B#0", 0, 20.0, vx=4.0, vy=0.0)], [("B#0", "W#0")])
        ev = rest + frame_pair([self.W, body("B#0", 0, 20.0, vx=0.0, vy=-15)],
                               [self.W, body("B#0", 0.04, 20.08, vx=0.0, vy=0.0)],
                               [("B#0", "W#0")])
        self.assertTrue(found(ev, "P5"))

    def test_p5_a_body_falling_onto_a_slope_may_slide(self):
        fall = frame_pair([self.W, body("B#0", 0, 30.0, vy=-200)],
                          [self.W, body("B#0", 0, 30.0, vy=-200)], [])
        ev = fall + frame_pair([self.W, body("B#0", 0, 20.0, vx=0.0, vy=-220)],
                               [self.W, body("B#0", 0.9, 20.4, vx=84, vy=-180)],
                               [("B#0", "W#0")])
        self.assertEqual(found(ev, "P5"), [])


# -- canaries -----------------------------------------------------------------

class TestCanaries(unittest.TestCase):
    def setUp(self):
        require_canaries(self)

    def test_p5_catches_the_skin_backed_off_along_the_normal(self):
        _r, _s, rep = _scene("ramp", [(col, "_SKIN_ALONG_MOTION", False)])
        self.assertIn("P5", {f.law for f in rep.findings}, rep.summary())

    def test_p3_catches_a_bounce_that_ignores_mass(self):
        real = col.CollisionInfo.velocity_split

        def split(self, *, mass_a, mass_b, **k):
            m = 1.0 if (mass_a != float("inf") and mass_b != float("inf")) else None
            return real(self, mass_a=m or mass_a, mass_b=m or mass_b, **k)  # the plant
        _r, _s, rep = _scene("headon", [(col.CollisionInfo, "velocity_split", split)])
        self.assertIn("P3", {f.law for f in rep.findings}, rep.summary())

    def test_p6_catches_a_rider_not_carried(self):
        with mock.patch.object(col, "_RIDER_CARRY", False):
            traj = eq.motion_trajectory("lift")
        x0, x1 = traj[round(1.0, 6)][0][0], traj[round(4.0, 6)][0][0]
        self.assertGreater(abs((x1 - x0) - 60 * 3.0), eq.POS_BUDGET)

    def test_e11_catches_a_left_right_asymmetric_bounce(self):
        real = col.CollisionInfo.velocity_split

        def split(self, *a, **k):
            va, vb = real(self, *a, **k)
            # The plant: a bounce off a wall on one side (its normal along
            # +x) loses 2 % of the speed across it — a sign error's shape.
            if float(self.normal.x) > 0.5:
                lose = (lambda v: col.Vec2.temp(v.x * 0.98, v.y))
                return lose(va), lose(vb)
            return va, vb
        with mock.patch.object(col.CollisionInfo, "velocity_split", split):
            out = eq.motion_equation("box", {"mirror": True})
        self.assertTrue(out)


if __name__ == "__main__":
    unittest.main()
