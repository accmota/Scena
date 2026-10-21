"""Standing resolve solver promises (review 2026-10-14: PB2, PE1-PE4).

Each class pins one documented promise of ``resolve()`` and the bug class
behind it, at several frame rates where frame time was the variable:

* PB2 ``TestRiderCarry`` -- a body standing on a moving partner moves with it,
  at every fps (it was 97 % at 30 fps and 1 % at 240 for a sideways lift);
* PE2 ``TestIdleSlope`` -- an idle body on a slope does not creep (it slid
  ``_RESOLVE_SLOP * sin(slope)`` downhill every frame);
* PE1 ``TestSettleIgnoresVelocity`` -- an overlap is separated along the
  overlap, never along a guess from ``.vel`` (two balls moving apart were
  pushed through each other; a ball spawned in a wall escaped outside);
* PE3 / PE4 ``TestStaticHolds`` -- nothing a movable body does pushes another
  movable body into or through a ``STATIC`` one (a light crate under a heavy
  one sank into the floor; a light ball hit by a heavy one went through it).

Collision Design: "Riders", "Resolution" (steps 3 and 4), "Mass split between
two movable bodies". Each class has a canary that turns its fix off
(``_RIDER_CARRY``, ``_SKIN_ALONG_MOTION``, ``_SETTLE_MIN_OVERLAP``,
``_SETTLE_STATIC_CLAMP``, ``_SWEEP_INHERIT_CLAMP``) and sees the bug.

    python tests/run_tiers.py focused test_resolve_solver
"""
from __future__ import annotations

import math
import os
import random
import sys
import unittest
import warnings
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system_support import system_world  # noqa: E402

from scena import STATIC, Circle, Rect, Track, resolve  # noqa: E402
from scena.collision import get_collision_system, reset_collision_system  # noqa: E402
from scena.scenamath import Vec2  # noqa: E402
from tests.floor_support import floor_module  # noqa: E402

# Walkers, ramps, lifts and resting piles: a world with gravity (collision.floor).
setUpModule, tearDownModule = floor_module()

C = sys.modules["scena.collision"]   # the module (``scena.collision`` is the facade)
FPS = (30, 60, 144, 240)


class _Plain(unittest.TestCase):
    """Bodies driven by ``move_by`` and a bare collision ``step()``."""

    _origin = 0

    def setUp(self):
        reset_collision_system()
        self._owned = []
        _Plain._origin += 4000
        self.o = float(_Plain._origin)

    def tearDown(self):
        self.clear()
        reset_collision_system()

    def clear(self):
        for s in self._owned:
            try:
                s.destroy()
            except Exception:
                pass
        self._owned.clear()
        reset_collision_system()

    def keep(self, s, mass=1.0, vel=True):
        s.mass = mass
        if vel:
            s.vel = Vec2(0.0, 0.0)
        self._owned.append(s)
        return s

    @staticmethod
    def step():
        get_collision_system().step()


# --------------------------------------------------------------------------
# PB2 -- riders
# --------------------------------------------------------------------------


class TestRiderCarry(_Plain):
    """A body resting on a moving partner moves with the partner's displacement
    this frame, at every fps; its own motion adds. Bug PB2: the only carry was
    the relative sweep's leftover ``d_other * (1 - t)``, with ``t`` the share of
    the gravity step spent closing the skin, so the carry fell with frame time
    (97 % at 30 fps, 87 % at 60, 1 % at 240)."""

    G = 2200.0

    def lift_ride(self, fps, *, lift_mass=STATIC, lift_vel=False, walk=0.0,
                  frames_s=0.6, lift_speed=200.0, strict=True, only=None):
        """Hero on a lift moved sideways by ``move_by``; returns (hero dx, lift dx)."""
        self.clear()
        dt = 1.0 / fps
        o = self.o
        lift = self.keep(Rect(center=(o, o), width=160, height=20, group="lift"),
                         mass=lift_mass, vel=lift_vel)
        hero = self.keep(Rect(center=(o, o + 30.5), width=30, height=40, group="hero"))
        if only is None:
            resolve("hero", "lift", bounce=0.0)
        else:
            resolve("hero", "lift", bounce=0.0, only=only)

        def frame(move):
            hero.vel.x = walk
            hero.vel.y -= self.G * dt
            hero.move_by(hero.vel.x * dt, hero.vel.y * dt)
            if move:
                lift.move_by(lift_speed * dt, 0.0)
            self.step()

        for _ in range(int(0.2 * fps)):          # land and rest
            frame(False)
        self.assertIn("bottom", hero.touching_sides)
        h0, l0 = float(hero.center.x), float(lift.center.x)
        for _ in range(int(frames_s * fps)):
            frame(True)
            if strict:
                self.assertIn("bottom", hero.touching_sides)
        return float(hero.center.x) - h0, float(lift.center.x) - l0

    def test_static_lift_carries_its_rider_at_every_fps(self):
        for fps in FPS:
            with self.subTest(fps=fps):
                hdx, ldx = self.lift_ride(fps)
                self.assertGreater(ldx, 100.0)
                self.assertAlmostEqual(hdx, ldx, delta=1e-6)

    def test_one_way_lift_carries_its_rider(self):
        """Tutorial 27's elevator is a one-way platform (``only="bottom"``)."""
        for fps in FPS:
            with self.subTest(fps=fps):
                hdx, ldx = self.lift_ride(fps, only="bottom")
                self.assertAlmostEqual(hdx, ldx, delta=1e-6)

    def test_finite_mass_lift_carries_its_rider(self):
        for fps in FPS:
            with self.subTest(fps=fps):
                hdx, ldx = self.lift_ride(fps, lift_mass=50.0)
                self.assertAlmostEqual(hdx, ldx, delta=1e-6)

    def test_walking_on_the_lift_adds_to_the_carry(self):
        for fps in FPS:
            for walk in (-90.0, 90.0):
                with self.subTest(fps=fps, walk=walk):
                    hdx, ldx = self.lift_ride(fps, walk=walk, frames_s=0.5)
                    own = walk * int(0.5 * fps) / fps
                    self.assertAlmostEqual(hdx, ldx + own, delta=1e-6)

    def test_jumping_off_ends_the_carry(self):
        """The carry is for a body standing on the lift: from the jump on, the
        hero moves only by its own motion (``vel.x`` is 0 here)."""
        for fps in FPS:
            with self.subTest(fps=fps):
                self.clear()
                dt = 1.0 / fps
                o = self.o
                lift = self.keep(Rect(center=(o, o), width=400, height=20, group="lift"),
                                 mass=STATIC, vel=False)
                hero = self.keep(Rect(center=(o, o + 30.5), width=30, height=40))
                resolve(hero, "lift", bounce=0.0)
                airborne_x = None
                for f in range(int(0.8 * fps)):
                    if f == int(0.3 * fps):
                        hero.vel.y = 600.0          # jump
                    hero.vel.y -= self.G * dt
                    hero.move_by(0.0, hero.vel.y * dt)
                    lift.move_by(200.0 * dt, 0.0)
                    self.step()
                    if f >= int(0.3 * fps):
                        if airborne_x is None:
                            airborne_x = float(hero.center.x)
                        if "bottom" not in hero.touching_sides:
                            self.assertAlmostEqual(float(hero.center.x), airborne_x, delta=1e-9)
                self.assertIsNotNone(airborne_x)

    def test_a_wall_on_the_lift_path_stops_the_rider(self):
        for fps in FPS:
            with self.subTest(fps=fps):
                self.clear()
                dt = 1.0 / fps
                o = self.o
                lift = self.keep(Rect(center=(o, o), width=300, height=20, group="solid"),
                                 mass=STATIC, vel=False)
                # A still wall above the lift's top, in the rider's way.
                wall = self.keep(Rect(center=(o + 60, o + 60), width=10, height=60,
                                      group="solid"), mass=STATIC, vel=False)
                hero = self.keep(Rect(center=(o, o + 30.5), width=30, height=40))
                resolve(hero, "solid", bounce=0.0)
                face = float(wall.center.x) - 5.0
                for _ in range(int(0.6 * fps)):
                    hero.vel.y -= self.G * dt
                    hero.move_by(0.0, hero.vel.y * dt)
                    lift.move_by(200.0 * dt, 0.0)
                    self.step()
                    self.assertLessEqual(float(hero.center.x) + 15.0, face + 1e-6)
                self.assertIn("right", hero.touching_sides)
                self.assertGreater(float(hero.center.x) + 15.0, face - 0.5)

    def test_two_stacked_riders_ride_in_either_order(self):
        """A crate on a hero on a lift: both ride; who was made first does not
        matter."""
        for fps in (60, 240):
            for crate_first in (False, True):
                with self.subTest(fps=fps, crate_first=crate_first):
                    self.clear()
                    dt = 1.0 / fps
                    o = self.o
                    lift = self.keep(Rect(center=(o, o), width=200, height=20, group="lift"),
                                     mass=STATIC, vel=False)
                    made = []
                    for k in (("crate", "hero") if crate_first else ("hero", "crate")):
                        if k == "hero":
                            made.append(self.keep(Rect(center=(o, o + 30.5), width=30,
                                                       height=40, group="body")))
                        else:
                            made.append(self.keep(Rect(center=(o, o + 61.0), width=20,
                                                       height=20, group="body")))
                    hero, crate = (made[1], made[0]) if crate_first else (made[0], made[1])
                    resolve("body", ["lift", "body"], bounce=0.0)

                    def frame(move):
                        for b in (hero, crate):
                            b.vel.y -= self.G * dt
                            b.move_by(0.0, b.vel.y * dt)
                        if move:
                            lift.move_by(150.0 * dt, 0.0)
                        self.step()

                    for _ in range(int(0.3 * fps)):
                        frame(False)
                    self.assertIn("bottom", crate.touching_sides)
                    h0, c0, l0 = (float(hero.center.x), float(crate.center.x),
                                  float(lift.center.x))
                    for _ in range(int(0.5 * fps)):
                        frame(True)
                    ldx = float(lift.center.x) - l0
                    self.assertAlmostEqual(float(hero.center.x) - h0, ldx, delta=1e-6)
                    self.assertAlmostEqual(float(crate.center.x) - c0, ldx, delta=1e-6)

    def test_a_crate_on_a_pushed_crate_is_not_dragged(self):
        """A physics body (with ``.vel``) is no platform: its own motion carries
        nothing (frictionless contact), only a carry it rides on itself."""
        dt = 1.0 / 60.0
        o = self.o
        self.keep(Rect(center=(o, o - 20), width=800, height=40, group="floor"),
                  mass=STATIC, vel=False)
        low = self.keep(Rect(center=(o, o + 20.08), width=40, height=40, group="crate"))
        top = self.keep(Rect(center=(o, o + 60.16), width=20, height=40, group="crate"))
        resolve("crate", ["floor", "crate"], bounce=0.0)
        for _ in range(30):
            for b in (low, top):
                b.vel.y -= 900.0 * dt
                b.move_by(0.0, b.vel.y * dt)
            self.step()
        x0 = float(top.center.x)
        for _ in range(20):
            for b in (low, top):
                b.vel.y -= 900.0 * dt
            low.move_by(1.0, low.vel.y * dt)
            top.move_by(0.0, top.vel.y * dt)
            self.step()
        self.assertGreater(float(low.center.x) - o, 15.0)
        self.assertAlmostEqual(float(top.center.x), x0, delta=1e-6)

    def test_a_ball_bouncing_off_a_moving_paddle_is_not_dragged(self):
        """The leave gate: an elastic body leaving the paddle is not carried on
        the frame after its bounce."""
        dt = 1.0 / 60.0
        o = self.o
        paddle = self.keep(Rect(center=(o, o), width=200, height=10, group="paddle"),
                           mass=STATIC, vel=False)
        ball = self.keep(Circle(center=(o, o + 30), radius=5, group="ball"))
        ball.vel = Vec2(0.0, -300.0)
        resolve("ball", "paddle", bounce=1.0)
        x_after = None
        for _ in range(30):
            ball.move_by(ball.vel.x * dt, ball.vel.y * dt)
            paddle.move_by(400.0 * dt, 0.0)
            self.step()
            if float(ball.vel.y) > 0.0:
                if x_after is None:
                    x_after = float(ball.center.x)     # the bounce frame
                self.assertAlmostEqual(float(ball.center.x), x_after, delta=1e-9)
        self.assertIsNotNone(x_after)

    def test_rider_carry_off_is_the_frame_rate_bug_canary(self):
        with mock.patch.object(C, "_RIDER_CARRY", False):
            hdx, ldx = self.lift_ride(240, strict=False)
        self.assertLess(hdx, 0.5 * ldx)


class TestRiderCarryTimedMovers(unittest.TestCase):
    """The carry reads the motion channel, so every pose mover that travels
    carries: timed ``move_by`` (eased, yoyo) and ``move_along``."""

    def ride(self, mover, fps):
        dt = 1.0 / fps
        with system_world(draw=False) as w:
            lift = Rect(center=(0, 200), width=160, height=20, group="lift")
            lift.mass = STATIC
            hero = Rect(center=(0, 230.5), width=30, height=40)
            hero.vel = Vec2(0, 0)
            resolve(hero, "lift", bounce=0.0)

            def update(_dt):
                hero.vel.y -= 2200.0 * dt
                hero.move_by(0.0, hero.vel.y * dt)

            w.on_update(update)
            w.begin_game()
            w.step(int(0.2 * fps), dt=dt)
            self.assertIn("bottom", hero.touching_sides)
            if mover == "timed":
                lift.move_by(300, 0, time=1.0, loops="forever", yoyo=True, ease="ease_in_out")
            else:
                lift.move_along(Track(points=[(0, 200), (300, 200)]), time=1.0,
                                loops="forever", yoyo=True)
            offs = []
            for _ in range(int(2.5 * fps)):
                w.step(1, dt=dt)
                offs.append(float(hero.center.x) - float(lift.center.x))
                self.assertIn("bottom", hero.touching_sides)
            travelled = float(lift.center.x)
        return offs, travelled

    def test_eased_yoyo_and_track_movers_carry(self):
        for mover in ("timed", "track"):
            for fps in (60, 240):
                with self.subTest(mover=mover, fps=fps):
                    offs, _ = self.ride(mover, fps)
                    self.assertLess(max(offs) - min(offs), 1e-6)


# --------------------------------------------------------------------------
# PE2 -- an idle body on a slope does not creep
# --------------------------------------------------------------------------


class TestBounceLeavesAtEveryRate(_Plain):
    """Persona probes round 2 (R2-1): a ball with ``bounce=0.5`` and sideways
    speed was glued to the floor at 144 Hz after its first bounce. The walker
    leave gate needed 2 DU of separation in one frame (``vy · dt``: a 150 DU/s
    rebound moves 1 DU at 144 Hz) or a step at least 0.85 straight off the
    floor (sideways speed lowers it). A body a real bounce impulse just sent
    off the floor is leaving, at every rate; a resting or walking body (tiny
    impulses from ``g · dt``) keeps the walker gate."""

    def second_hop(self, fps, bounce, vx=300.0):
        self.clear()
        dt = 1.0 / fps
        o = self.o
        self.keep(Rect(center=(o + 500, o + 50), width=4000, height=100, group="chao"),
                  mass=STATIC, vel=False)
        ball = self.keep(Circle(center=(o + 100, o + 300), radius=20, group="bola"))
        ball.vel = Vec2(vx, 0.0)
        resolve("bola", "chao", bounce=bounce)
        peak, t = 0.0, 0.0
        while t < 1.5:
            ball.vel.y -= 600.0 * dt
            ball.move_by(ball.vel.x * dt, ball.vel.y * dt)
            self.step()
            t += dt
            if t > 0.75:
                peak = max(peak, float(ball.center.y) - o)
        return peak

    def test_a_soft_bounce_with_sideways_speed_rises_at_every_rate(self):
        ref = {b: self.second_hop(60, b) for b in (0.3, 0.5)}
        for b in (0.3, 0.5):
            self.assertGreater(ref[b], 125.0, b)       # the 60 Hz hop clears the floor
            for fps in (30, 144, 240):
                with self.subTest(bounce=b, fps=fps):
                    self.assertGreater(self.second_hop(fps, b), ref[b] - 8.0)

    def test_a_soft_walker_on_a_slope_stays_grounded(self):
        for fps in (60, 144, 240):
            with self.subTest(fps=fps):
                self.clear()
                dt = 1.0 / fps
                o = self.o
                ramp = self.keep(Rect(center=(o, o), width=800, height=20, group="chao"),
                                 mass=STATIC, vel=False)
                ramp.rotate_by(-20.0)
                snail = self.keep(Rect(center=(o - 200, o + 120), width=20, height=20,
                                       group="lesma"))
                resolve("lesma", "chao", bounce=0.2)
                lost = 0
                for i in range(int(2.0 * fps)):
                    snail.vel.x = 120.0
                    snail.vel.y -= 2200.0 * dt
                    snail.move_by(snail.vel.x * dt, snail.vel.y * dt)
                    self.step()
                    if i > fps // 2 and "bottom" not in snail.touching_sides:
                        lost += 1
                self.assertEqual(lost, 0)


class TestARestingMovablePartnerIsNotAWall(_Plain):
    """Persona probes round 3 (R3-2): a mover that ended a frame inside the
    resting skin of a resting *movable* partner (``.vel`` = 0) bounced off it
    as off a wall at 60 Hz (the unreached-contact answer, LW8): B never moved,
    masses ignored. At 30 and 144 Hz the textbook split held. The answer is
    the sweep's, with the masses, at every rate; a partner with no ``.vel``
    (a Breakout brick) is still answered there."""

    def collide(self, fps, ma, mb, bounce, x0=100.0):
        self.clear()
        dt = 1.0 / fps
        o = self.o
        a = self.keep(Rect(center=(o + x0, o), width=60, height=60, group="pa"), mass=ma)
        b = self.keep(Rect(center=(o + 500, o), width=60, height=60, group="pb"), mass=mb)
        a.vel = Vec2(200.0, 0.0)
        resolve("pa", "pb", bounce=bounce)
        for _ in range(int(2.5 * fps)):
            a.move_by(a.vel.x * dt, a.vel.y * dt)
            b.move_by(b.vel.x * dt, b.vel.y * dt)
            self.step()
        return float(a.vel.x), float(b.vel.x)

    def test_the_split_holds_at_every_rate_and_start(self):
        cases = ((10.0, 1.0, 0.5, (172.7, 272.7)), (1.0, 10.0, 1.0, (-163.6, 36.4)),
                 (1.0, 1.0, 1.0, (0.0, 200.0)))
        for ma, mb, e, (wa, wb) in cases:
            for fps in (30, 60, 144):
                for x0 in (100.0, 103.2, 100.2):
                    with self.subTest(ma=ma, mb=mb, fps=fps, x0=x0):
                        va, vb = self.collide(fps, ma, mb, e, x0)
                        self.assertAlmostEqual(va, wa, delta=1.0)
                        self.assertAlmostEqual(vb, wb, delta=1.0)


class TestIdleSlope(_Plain):
    """Bug PE2: after a vertical stop on a slope the sweep backed off the skin
    along the slope normal, and floor snap did the same, so an idle hero slid
    ``_RESOLVE_SLOP * sin(slope)`` downhill every frame (30 deg: 24 DU in 10 s at
    60 Hz, 57.6 at 144 Hz). The ninja_mundo idiom: ``vel.x = 0`` when no key."""

    def idle(self, angle, fps, bounce, seconds=2.0):
        self.clear()
        dt = 1.0 / fps
        o = self.o
        ramp = self.keep(Rect(center=(o, o), width=600, height=20, group="chao"),
                         mass=STATIC, vel=False)
        ramp.rotate_by(angle)
        hero = self.keep(Rect(center=(o, o + 60), width=20, height=40, group="heroi"))
        if bounce is None:
            resolve("heroi", "chao")
        else:
            resolve("heroi", "chao", bounce=bounce)

        def frame():
            hero.vel.x = 0.0
            if bounce is None and "bottom" in hero.touching_sides and hero.vel.y < 0:
                hero.vel.y = 0.0
            hero.vel.y -= 2200.0 * dt
            hero.move_by(hero.vel.x * dt, hero.vel.y * dt)
            self.step()

        for _ in range(int(0.5 * fps)):
            frame()
        self.assertIn("bottom", hero.touching_sides)
        x0, y0 = float(hero.center.x), float(hero.center.y)
        for _ in range(int(seconds * fps)):
            frame()
            self.assertIn("bottom", hero.touching_sides)
        return float(hero.center.x) - x0, float(hero.center.y) - y0

    def test_idle_body_stays_put_on_walkable_slopes(self):
        for angle in (10.0, -22.0, 30.0, 40.0):
            for fps in (60, 144, 240):
                for bounce in (0.0, None):
                    with self.subTest(angle=angle, fps=fps, bounce=bounce):
                        dx, dy = self.idle(angle, fps, bounce)
                        self.assertLess(abs(dx), 1e-6)
                        self.assertLess(abs(dy), 1e-6)

    def test_skin_along_normal_is_the_creep_canary(self):
        with mock.patch.object(C, "_SKIN_ALONG_MOTION", False):
            dx, _dy = self.idle(30.0, 60, 0.0, seconds=2.0)
        self.assertLess(dx, -3.0)


# --------------------------------------------------------------------------
# PE1 -- settle separates along the overlap, never along .vel
# --------------------------------------------------------------------------


class TestSettleIgnoresVelocity(_Plain):
    """Bug PE1: settle with no remembered contact normal flipped the overlap
    axis when the pair's velocities separated along it, so each correction
    deepened the overlap: two overlapping balls moving apart swapped sides, a
    ball spawned in a wall moving into the room escaped outside, a STATIC
    paddle placed onto a ball lost it below. Class guard: where settle puts an
    overlapping pair does not depend on the bodies' velocities."""

    def test_overlapping_pair_moving_apart_keeps_its_sides(self):
        dt = 1.0 / 60.0
        for bounce in (None, 0.0, 1.0):
            with self.subTest(bounce=bounce):
                self.clear()
                o = self.o
                a = self.keep(Circle(center=(o, o), radius=10, group="ball"))
                b = self.keep(Circle(center=(o + 15, o), radius=10, group="ball"))
                a.vel = Vec2(-60.0, 0.0)
                b.vel = Vec2(60.0, 0.0)
                if bounce is None:
                    resolve("ball", "ball")
                else:
                    resolve("ball", "ball", bounce=bounce)
                for _ in range(8):
                    for c in (a, b):
                        c.move_by(c.vel.x * dt, c.vel.y * dt)
                    self.step()
                    self.assertLess(float(a.center.x), float(b.center.x))
                gap = float(b.center.x) - float(a.center.x) - 20.0
                self.assertGreater(gap, -0.2)

    def test_ball_spawned_in_a_wall_leaves_into_the_room(self):
        dt = 1.0 / 60.0
        for thick in (4.0, 20.0):
            with self.subTest(thick=thick):
                self.clear()
                o = self.o
                self.keep(Rect(center=(o - thick / 2, o), width=thick, height=400,
                               group="wall"), mass=STATIC, vel=False)
                ball = self.keep(Circle(center=(o + 5, o), radius=10, group="ball"))
                ball.vel = Vec2(100.0, 0.0)
                resolve("ball", "wall", bounce=1.0)
                for _ in range(8):
                    ball.move_by(ball.vel.x * dt, ball.vel.y * dt)
                    self.step()
                self.assertGreater(float(ball.center.x), o + 10.0)
                self.assertGreater(float(ball.vel.x), 0.0)

    def test_paddle_placed_onto_a_ball_keeps_it_on_its_side(self):
        dt = 1.0 / 60.0
        o = self.o
        paddle = self.keep(Rect(center=(o + 100, o + 20), width=60, height=10, group="pad"),
                           mass=STATIC, vel=False)
        ball = self.keep(Circle(center=(o + 138, o + 18), radius=5, group="ball"))
        ball.vel = Vec2(150.0, 260.0)
        resolve(ball, "pad", bounce=1.0)
        ball.move_by(ball.vel.x * dt, ball.vel.y * dt)
        self.step()
        paddle.center = (o + 130, o + 20)           # placement onto the ball
        for _ in range(10):
            ball.move_by(ball.vel.x * dt, ball.vel.y * dt)
            self.step()
        self.assertGreater(float(ball.center.y), o + 20)

    def test_settle_position_does_not_depend_on_velocity(self):
        """Random overlapping pairs (circles and boxes, free and against a
        STATIC body), placed and never moved: one step with random velocities
        puts every body where the same step with no velocity does."""
        rng = random.Random(1014)

        def run(seed, with_vel):
            self.clear()
            r = random.Random(seed)
            o = self.o
            bodies = []
            for i in range(6):
                cx, cy = o + 120.0 * i, o
                kind = r.choice(("circle", "rect"))
                a = (Circle(center=(cx, cy), radius=r.uniform(6, 14), group="p")
                     if kind == "circle" else
                     Rect(center=(cx, cy), width=r.uniform(10, 30), height=r.uniform(10, 30),
                          group="p"))
                ang = r.uniform(0, 2 * math.pi)
                d = r.uniform(2, 10)
                if r.random() < 0.5:
                    b = Rect(center=(cx + d * math.cos(ang), cy + d * math.sin(ang)),
                             width=r.uniform(10, 40), height=r.uniform(10, 40), group="w")
                    self.keep(b, mass=STATIC, vel=False)
                else:
                    b = Circle(center=(cx + d * math.cos(ang), cy + d * math.sin(ang)),
                               radius=r.uniform(6, 14), group="p")
                    self.keep(b, mass=r.uniform(0.5, 3))
                self.keep(a, mass=r.uniform(0.5, 3))
                bodies += [a, b]
            for s in bodies:
                if s.vel is not None:
                    s.vel = (Vec2(r.uniform(-300, 300), r.uniform(-300, 300)) if with_vel
                             else Vec2(0.0, 0.0))
            resolve("p", ["p", "w"])
            self.step()
            return [(round(float(s.center.x) - o, 9), round(float(s.center.y) - o, 9))
                    for s in bodies]

        for _ in range(12):
            seed = rng.randrange(1 << 30)
            with self.subTest(seed=seed):
                self.assertEqual(run(seed, True), run(seed, False))

    def test_velocity_flip_is_the_push_through_canary(self):
        """The old flip pushes a ball spawned in a thin wall, moving into the
        room, out through the far face."""
        with mock.patch.object(C, "_SETTLE_MIN_OVERLAP", False):
            dt = 1.0 / 60.0
            o = self.o
            self.keep(Rect(center=(o - 2, o), width=4, height=400, group="wall"),
                      mass=STATIC, vel=False)
            ball = self.keep(Circle(center=(o + 5, o), radius=10, group="ball"))
            ball.vel = Vec2(100.0, 0.0)
            resolve("ball", "wall", bounce=1.0)
            for _ in range(8):
                ball.move_by(ball.vel.x * dt, ball.vel.y * dt)
                self.step()
            self.assertLess(float(ball.center.x), o - 4.0)


# --------------------------------------------------------------------------
# PE3 / PE4 -- STATIC never gives way
# --------------------------------------------------------------------------


class TestStaticHolds(_Plain):
    """Bug PE3: settle split a correction between two movable bodies by mass
    without looking at the lower body's STATIC contacts, so a light crate under
    a heavy one was pressed into the floor (mass 5: 8 DU in; mass 20: almost
    fully in; a 2 DU floor: through it). Bug PE4: a sweep stop between two
    movable bodies placed the body's inherited leftover unswept, so a light
    ball hit by a fast heavy one could be put past a thin wall behind it (116
    DU at 6000 DU/s). Stacks may still overlap a little between crates (no
    stacking guarantee); nothing ends inside or past a STATIC body."""

    def crate_stack(self, top_mass, floor_h, low_first=True, frames=240):
        """Light crate on a STATIC floor, a heavy one dropped on it. Returns the
        light crate's lowest bottom relative to the floor's top."""
        self.clear()
        dt = 1.0 / 60.0
        o = self.o
        self.keep(Rect(center=(o, o - floor_h / 2), width=400, height=floor_h,
                       group="floor"), mass=STATIC, vel=False)
        made = []
        for k in ("low", "top") if low_first else ("top", "low"):
            if k == "low":
                made.append(self.keep(Rect(center=(o, o + 20.08), width=40, height=40,
                                           group="crate")))
            else:
                made.append(self.keep(Rect(center=(o, o + 100.0), width=40, height=40,
                                           group="crate"), mass=top_mass))
        low = made[0] if low_first else made[1]
        resolve("crate", "floor", bounce=0.0)
        resolve("crate", "crate", bounce=0.0)
        lowest = math.inf
        for _ in range(frames):
            for c in made:
                c.vel.y -= 900.0 * dt
                c.move_by(0.0, c.vel.y * dt)
            self.step()
            lowest = min(lowest, float(low.center.y) - 20.0 - o)
        return lowest

    def test_heavy_crate_does_not_press_a_light_one_into_the_floor(self):
        for top_mass in (1.0, 5.0, 20.0, 100.0):
            for floor_h in (2.0, 16.0, 40.0):
                for low_first in (True, False):
                    with self.subTest(top=top_mass, floor=floor_h, low_first=low_first):
                        self.assertGreater(self.crate_stack(top_mass, floor_h, low_first),
                                           -0.05)

    def test_ball_bin_keeps_every_ball_above_a_thin_floor(self):
        dt = 1.0 / 60.0
        o = self.o
        rng = random.Random(7)
        self.keep(Rect(center=(o + 150, o - 5), width=400, height=10, group="solid"),
                  mass=STATIC, vel=False)
        for x in (o - 20, o + 320):
            self.keep(Rect(center=(x, o + 300), width=40, height=600, group="solid"),
                      mass=STATIC, vel=False)
        balls = []
        for i in range(40):
            r = rng.uniform(6, 12)
            b = self.keep(Circle(center=(o + rng.uniform(20, 280), o + 40 + 9 * i), radius=r,
                                 group="ball"), mass=(r / 10.0) ** 2)
            balls.append(b)
        resolve("ball", ["solid", "ball"], bounce=0.2)
        for _ in range(150):
            for b in balls:
                b.vel.y -= 900.0 * dt
                b.move_by(b.vel.x * dt, b.vel.y * dt)
            self.step()
        lowest = min(float(b.center.y) - float(b.radius) - o for b in balls)
        self.assertGreater(lowest, -0.05)

    def test_light_ball_under_a_falling_heavy_one_stays_on_the_floor(self):
        """PE4 as the Mass split doc stated it: the light body swept first."""
        for fps, floor_h, drop in ((60, 10.0, 110.0), (60, 2.0, 110.0), (30, 10.0, 300.0),
                                   (144, 4.0, 300.0)):
            for light_first in (True, False):
                with self.subTest(fps=fps, floor=floor_h, drop=drop, light_first=light_first):
                    self.clear()
                    dt = 1.0 / fps
                    o = self.o
                    self.keep(Rect(center=(o, o - floor_h / 2), width=400, height=floor_h,
                                   group="floor"), mass=STATIC, vel=False)
                    made = {}
                    for k in ("l", "h") if light_first else ("h", "l"):
                        if k == "l":
                            made[k] = self.keep(Circle(center=(o, o + 10.08), radius=10,
                                                       group="ball"))
                        else:
                            made[k] = self.keep(Circle(center=(o, o + 30 + drop), radius=10,
                                                       group="ball"), mass=30.0)
                    resolve("ball", "floor", bounce=0.0)
                    resolve("ball", "ball", bounce=0.0)
                    light = made["l"]
                    for _ in range(int(2 * fps)):
                        for c in made.values():
                            c.vel.y -= 900.0 * dt
                            c.move_by(0.0, c.vel.y * dt)
                        self.step()
                        self.assertGreater(float(light.center.y) - 10.0 - o, -0.05)

    def test_fast_push_into_a_thin_wall_with_the_light_body_first(self):
        """The Open case of "Mass split": the light body enrolled (swept) before
        its fast pusher inherited the pusher's leftover unswept."""
        dt = 1.0 / 60.0
        for speed in (600.0, 2400.0, 6000.0):
            with self.subTest(speed=speed):
                self.clear()
                o = self.o
                self.keep(Rect(center=(o + 100, o), width=2, height=200, group="fixo"),
                          mass=STATIC, vel=False)
                face = o + 99.0
                b = self.keep(Circle(center=(face - 8 - 0.08, o), radius=8, group="bola"),
                              mass=0.2, vel=False)
                a = self.keep(Circle(center=(o, o), radius=8, group="bola"), vel=False)
                resolve("bola", ["bola", "fixo"])
                for _ in range(30):
                    a.move_by(speed * dt, 0)
                    self.step()
                    self.assertLessEqual(float(b.center.x) + 8, face + 1e-6)
                    self.assertLessEqual(float(a.center.x), float(b.center.x))

    def test_static_clamps_off_are_the_sink_canaries(self):
        with mock.patch.object(C, "_SETTLE_STATIC_CLAMP", False):
            self.assertLess(self.crate_stack(5.0, 40.0), -3.0)
        with mock.patch.object(C, "_SWEEP_INHERIT_CLAMP", False):
            dt = 1.0 / 60.0
            self.clear()
            o = self.o
            self.keep(Rect(center=(o + 100, o), width=2, height=200, group="fixo"),
                      mass=STATIC, vel=False)
            b = self.keep(Circle(center=(o + 99 - 8.08, o), radius=8, group="bola"),
                          mass=0.2, vel=False)
            a = self.keep(Circle(center=(o, o), radius=8, group="bola"), vel=False)
            resolve("bola", ["bola", "fixo"])
            worst = -math.inf
            for _ in range(30):
                a.move_by(6000.0 * dt, 0)
                self.step()
                worst = max(worst, float(b.center.x) + 8 - (o + 99))
            self.assertGreater(worst, 10.0)


if __name__ == "__main__":
    with warnings.catch_warnings():
        unittest.main()
