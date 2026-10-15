"""Joint response and bounce sub-step (2026-10-15: LW2, LW7, LW8; PE5 → G2).

Each class pins one rule of ``resolve(..., bounce=)`` and the bug class behind
it, at the frame rates where frame time was the variable:

* ``TestJointAlgebra`` -- ``_cone_response``: one contact is ``velocity_split``;
  any set of contacts is answered together, order-free, adding no energy and
  leaving no contact approached;
* ``TestSeams`` (LW2) -- a ball into the seam of two bricks leaves straight
  back, whatever the creation order, the frame rate or how the bricks break
  (it left 7-60 degrees off by creation order);
* ``TestInternalEdges`` -- a walker crossing flat tile seams is not stopped by
  the next tile's side face (the joint stop must not take it in);
* ``TestBounceSubstep`` (LW7) -- a bounce keeps the rest of its frame's travel
  (a ball in a box ran 3-6 % slow at low frame rates; a ``bounce=1`` ball lost
  height by frame rate), and a bouncy ball still comes to rest;
* ``TestGhostWalls`` (PE5, G2) -- a partner a handler removes is a still wall
  for the survivor's sweep that step: breaking in the handler, a frame later or
  never gives the same path;
* ``TestSkinAnswer`` (LW8) -- a skin contact the handlers saw is answered that
  step, so a brick broken a frame later still bounces the ball.

Collision Design: "Joint stop", "Resolution" (step 3), "Partner removed by a
handler", "Resting contact (skin)". Canaries: ``_JOINT_RESPONSE``,
``_BOUNCE_SUBSTEP``, ``_GHOST_WALLS``, ``_SKIN_ANSWER``.

    python tests/run_tiers.py focused test_joint_response
"""
from __future__ import annotations

import math
import os
import random
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scena import STATIC, Circle, Rect, collide, resolve  # noqa: E402
from scena.collision import get_collision_system, reset_collision_system  # noqa: E402
from scena.scenamath import Vec2  # noqa: E402

C = sys.modules["scena.collision"]   # the module (``scena.collision`` is the facade)
FPS = (30, 60, 144)
SLOP = C._RESOLVE_SLOP


class _World(unittest.TestCase):
    """Bodies driven by ``move_by`` and a bare collision ``step()``."""

    def setUp(self):
        reset_collision_system()
        self._owned = []

    def tearDown(self):
        self.clear()

    def clear(self):
        for s in self._owned:
            try:
                if s.is_alive:
                    s.destroy()
            except Exception:
                pass
        self._owned.clear()
        reset_collision_system()

    def keep(self, s, mass=1.0, vel=None):
        s.mass = mass
        if vel is not None:
            s.vel = Vec2(*vel)
        self._owned.append(s)
        return s

    @staticmethod
    def step():
        get_collision_system().step()


def _deg_from_down(v):
    return math.degrees(math.atan2(v[0], -v[1]))


# --------------------------------------------------------------------------
# The algebra
# --------------------------------------------------------------------------


def _unit(a):
    return (math.cos(a), math.sin(a))


class TestJointAlgebra(unittest.TestCase):
    """``_cone_response``: the inelastic projection onto the contacts' cone,
    each impulse times ``1 + e``."""

    def test_one_contact_is_velocity_split(self):
        rng = random.Random(1)
        for _ in range(300):
            v = (rng.uniform(-400, 400), rng.uniform(-400, 400))
            n = _unit(rng.uniform(0, 2 * math.pi))
            e = rng.choice((0.0, 0.3, 1.0))
            got = C._cone_response(v[0], v[1], [n], [e])
            info = C.CollisionInfo(a=None, b=None, normal=Vec2(*n), depth=0.0)
            want, _ = info.velocity_split(mass_a=1.0, mass_b=STATIC, bounce=e,
                                          vel_a=v, vel_b=(0.0, 0.0))
            self.assertAlmostEqual(got[0], float(want.x), places=9)
            self.assertAlmostEqual(got[1], float(want.y), places=9)

    def test_random_sets_add_no_energy_ignore_order_and_leave_no_approach(self):
        rng = random.Random(2)
        n_sets = 0
        while n_sets < 3000:
            ns = [_unit(rng.uniform(0, 2 * math.pi)) for _ in range(rng.choice((2, 2, 3)))]
            v = _unit(rng.uniform(0, 2 * math.pi))
            if not all(v[0] * n[0] + v[1] * n[1] > 1e-3 for n in ns):
                continue                         # a joint set: every contact approached
            n_sets += 1
            e = rng.choice((0.0, 0.5, 1.0))
            w = C._cone_response(v[0], v[1], ns, [e] * len(ns))
            w2 = C._cone_response(v[0], v[1], ns[::-1], [e] * len(ns))
            self.assertLessEqual(math.hypot(*w), 1.0 + 1e-9, (v, ns, e))       # P2
            self.assertAlmostEqual(w[0], w2[0], places=9)
            self.assertAlmostEqual(w[1], w2[1], places=9)
            for n in ns:
                self.assertLessEqual(w[0] * n[0] + w[1] * n[1], 1e-9, (v, ns, e, w))
        # Mixed restitutions never add energy either (the smallest is taken).
        for _ in range(500):
            ns = [_unit(rng.uniform(0, 2 * math.pi)) for _ in range(2)]
            v = _unit(rng.uniform(0, 2 * math.pi))
            w = C._cone_response(v[0], v[1], ns, [rng.random(), rng.random()])
            self.assertLessEqual(math.hypot(*w), 1.0 + 1e-9)

    def test_the_cases_one_at_a_time_got_wrong(self):
        s, c = math.sin(math.radians(14.5)), math.cos(math.radians(14.5))
        seam = C._cone_response(0.0, 1.0, [(-s, c), (s, c)], [1.0, 1.0])
        self.assertAlmostEqual(seam[0], 0.0, places=9)
        self.assertAlmostEqual(seam[1], -1.0, places=9)
        # A room corner: each wall reflects its own component.
        corner = C._cone_response(1.0, -0.5, [(1.0, 0.0), (0.0, -1.0)], [1.0, 1.0])
        self.assertAlmostEqual(corner[0], -1.0, places=9)
        self.assertAlmostEqual(corner[1], 0.5, places=9)
        # A fall onto the joint of a floor and a 30 degree slope stops (bounce=0).
        sl = (-0.5, -math.sqrt(3) / 2)
        v = C._cone_response(0.0, -1.0, [(0.0, -1.0), sl], [0.0, 0.0])
        self.assertAlmostEqual(v[0], 0.0, places=9)
        self.assertAlmostEqual(v[1], 0.0, places=9)


# --------------------------------------------------------------------------
# LW2 -- seams
# --------------------------------------------------------------------------


class TestSeams(_World):
    """A ball on the seam of two bricks: one stop, both bricks answered."""

    def seam(self, gap, mode="plain", fps=60, order="lr", x0=0.0, y0=60.0):
        """A row of two 60 x 24 STATIC bricks, a gap between; a ball r = 8
        going straight up at 360 DU/s. ``mode``: plain resolve, break in
        ``@collide`` (``handler``) or a frame later (``later``). Returns the
        ball's velocity after the hit."""
        self.clear()
        dt = 1.0 / fps
        xs = [-(30 + gap / 2), 30 + gap / 2]
        if order == "rl":
            xs.reverse()
        for x in xs:
            self.keep(Rect(center=(x, 100), width=60, height=24, group="jr_brick"), STATIC)
        ball = self.keep(Circle(center=(x0, y0), radius=8, group="jr_ball"), 1.0, (0.0, 360.0))
        resolve("jr_ball", "jr_brick", bounce=1.0)
        doomed = []
        if mode != "plain":
            @collide("jr_ball", "jr_brick")
            def broke(b, brick, info):
                if mode == "handler":
                    brick.destroy()
                else:
                    doomed.append(brick)
        for _ in range(int(0.5 * fps)):
            while doomed:
                doomed.pop().destroy()
            ball.move_by(ball.vel.x * dt, ball.vel.y * dt)
            self.step()
        return (float(ball.vel.x), float(ball.vel.y))

    def test_a_seam_bounces_straight_back(self):
        for gap in (0.0, 1.0, 2.0, 4.0, 8.0, 12.0):
            for fps in FPS:
                for mode in ("plain", "handler", "later"):
                    for order in ("lr", "rl"):
                        with self.subTest(gap=gap, fps=fps, mode=mode, order=order):
                            v = self.seam(gap, mode, fps, order)
                            self.assertLess(abs(_deg_from_down(v)), 0.01, v)
                            self.assertAlmostEqual(math.hypot(*v), 360.0, places=6)

    def test_at_every_phase(self):
        for gap in (2.0, 4.0):
            for fps in FPS:
                for k in range(8):
                    with self.subTest(gap=gap, fps=fps, k=k):
                        y0 = 60.0 + 0.77 * k
                        out = {m: self.seam(gap, m, fps, y0=y0) for m in ("plain", "handler", "later")}
                        for m, v in out.items():
                            self.assertLess(abs(_deg_from_down(v)), 0.01, (m, v))

    def test_near_the_centre_the_three_breaks_agree(self):
        """Off centre the answer is the geometry's (not straight back); how
        the brick breaks does not change it."""
        for fps in FPS:
            for x0 in (-0.3, 0.1, 0.3):
                with self.subTest(fps=fps, x0=x0):
                    out = [self.seam(2.0, m, fps, x0=x0) for m in ("plain", "handler", "later")]
                    for v in out[1:]:
                        self.assertAlmostEqual(v[0], out[0][0], places=6)
                        self.assertAlmostEqual(v[1], out[0][1], places=6)

    def column_seam(self, mode, fps, order):
        """The E8 twin's geometry (``tests/laws/twins/breakout.py``, ``vy=0``),
        STATIC bricks: a ball moving right into the seam of a column."""
        self.clear()
        dt = 1.0 / fps
        bricks = {}
        for i in order:
            bricks[i] = self.keep(Rect(center=(330, 90 + 60 * i), width=16, height=50,
                                       group="jr_col"), STATIC)
        ball = self.keep(Circle(center=(120, 120), radius=6, group="jr_cball"), 1.0, (300.0, 0.0))
        resolve("jr_cball", "jr_col", bounce=1.0)
        doomed = []
        if mode != "plain":
            @collide("jr_cball", "jr_col")
            def broke(b, brick, info):
                if mode == "handler":
                    brick.destroy()
                else:
                    doomed.append(brick)
        for _ in range(int(2.5 * fps)):
            while doomed:
                doomed.pop().destroy()
            ball.move_by(ball.vel.x * dt, ball.vel.y * dt)
            self.step()
        return (float(ball.vel.x), float(ball.vel.y))

    def test_the_e8_twin_seam(self):
        for fps in FPS:
            for mode in ("plain", "handler", "later"):
                for order in ((0, 1, 2), (2, 1, 0)):
                    with self.subTest(fps=fps, mode=mode, order=order):
                        vx, vy = self.column_seam(mode, fps, order)
                        self.assertAlmostEqual(vx, -300.0, places=6)
                        self.assertAlmostEqual(vy, 0.0, places=6)

    def test_canary_one_at_a_time_depends_on_creation_order(self):
        with mock.patch.object(C, "_JOINT_RESPONSE", False):
            a = _deg_from_down(self.seam(4.0, "plain", 60, "lr"))
            b = _deg_from_down(self.seam(4.0, "plain", 60, "rl"))
        self.assertGreater(abs(a - b), 10.0, (a, b))


# --------------------------------------------------------------------------
# Internal edges
# --------------------------------------------------------------------------


class TestInternalEdges(_World):
    """A tile seam's side face within the skin of a walker's floor hit is an
    AABB corner artefact: the floor's slide passes above it, so the joint
    stop leaves it out (mutual blocking). It stopped the walker dead."""

    def walk(self, pacing, frames=150):
        self.clear()
        for i in range(12):
            self.keep(Rect(center=(16.0 * i, 0), width=16, height=16, group="jr_tile"), STATIC)
        hero = self.keep(Rect(center=(0, 8 + 10 + 1), width=12, height=20, group="jr_hero"),
                         1.0, (0.0, 0.0))
        resolve("jr_hero", "jr_tile", bounce=0.0)
        x0 = float(hero.center.x)
        t = 0.0
        for k in range(frames):
            dt = pacing[k % len(pacing)]
            hero.vel.x = 60.0
            hero.vel.y -= 900.0 * dt
            hero.move_by(hero.vel.x * dt, hero.vel.y * dt)
            self.step()
            t += dt
            self.assertNotIn("right", hero.touching_sides, f"snag at frame {k}")
        return float(hero.center.x) - x0, 60.0 * t

    def test_a_walker_crosses_seams_at_full_speed(self):
        for pacing in ([0.005, 0.028], [1 / 30], [1 / 144]):
            with self.subTest(pacing=pacing):
                travel, want = self.walk(pacing)
                self.assertAlmostEqual(travel, want, delta=1e-6)


# --------------------------------------------------------------------------
# LW7 -- the bounce sub-step
# --------------------------------------------------------------------------


class TestBounceSubstep(_World):
    """After a stop, the closing part of the leftover gets the restitution
    the velocity got. It was dropped at every bounce."""

    def two_walls(self, pacing, seconds=5.0, speed=700.0):
        """Phase lag (DU) of a ball r = 8 between two STATIC walls, per bounce."""
        self.clear()
        self.keep(Rect(center=(-5, 0), width=10, height=2000, group="jr_wall"), STATIC)
        self.keep(Rect(center=(389, 0), width=10, height=2000, group="jr_wall"), STATIC)
        ball = self.keep(Circle(center=(100, 0), radius=8, group="jr_wb"), 1.0, (speed, 0.0))
        resolve("jr_wb", "jr_wall", bounce=1.0)
        t, k, bounces, sign = 0.0, 0, 0, 1
        while t < seconds - 1e-9:
            dt = pacing[k % len(pacing)]
            k += 1
            ball.move_by(ball.vel.x * dt, 0.0)
            self.step()
            t += dt
            s = 1 if ball.vel.x > 0 else -1
            bounces += s != sign
            sign = s
        span = 368.0
        u_ideal = (100 - 8 + speed * t) % (2 * span)
        x = float(ball.center.x)
        u = (x - 8) if ball.vel.x > 0 else (2 * span - (x - 8))
        lag = (u_ideal - u + span) % (2 * span) - span
        self.assertGreater(bounces, 4)
        return lag / bounces

    def test_a_ball_between_two_walls_keeps_its_pace(self):
        for pacing in ([1 / 30], [1 / 60], [1 / 144], [1 / 240], [0.005, 0.028]):
            with self.subTest(pacing=pacing):
                per = self.two_walls(pacing)
                self.assertLessEqual(abs(per), 1.5 * SLOP, per)    # the skin, at every rate

    def drop(self, fps, bounce, seconds=6.0):
        self.clear()
        dt = 1.0 / fps
        self.keep(Rect(center=(0, -10), width=400, height=20, group="jr_floor"), STATIC)
        ball = self.keep(Circle(center=(0, 210), radius=10, group="jr_drop"), 1.0, (0.0, 0.0))
        resolve("jr_drop", "jr_floor", bounce=bounce)
        peaks, up, top, last = [], False, 0.0, []
        n = round(seconds * fps)
        for k in range(n):
            ball.vel.y -= 900.0 * dt
            ball.move_by(0.0, ball.vel.y * dt)
            self.step()
            y = float(ball.center.y) - 10.0
            if ball.vel.y > 0:
                up, top = True, max(top, y)
            elif up:
                peaks.append(top)
                up, top = False, 0.0
            if k >= n - round(0.5 * fps):
                last.append(y)
        return peaks, last

    def test_an_elastic_ball_keeps_its_height(self):
        for fps in FPS:
            with self.subTest(fps=fps):
                peaks, _last = self.drop(fps, 1.0, seconds=3.0)
                self.assertTrue(peaks)
                for p in peaks:
                    self.assertGreater(p, 199.8, peaks)
                    self.assertLess(p, 200.0 + 2 * SLOP, peaks)       # P2

    def test_a_bouncy_ball_comes_to_rest(self):
        """A body grounded at the start of the frame does not bounce its
        leftover off that floor: one frame's gravity kick is not a bounce."""
        for fps in FPS:
            for bounce in (0.2, 0.5):
                with self.subTest(fps=fps, bounce=bounce):
                    _peaks, last = self.drop(fps, bounce)
                    self.assertLess(max(last) - min(last), 1e-6, (min(last), max(last)))
                    self.assertAlmostEqual(min(last), SLOP, places=6)

    def head_on(self, fps, ma, mb, seconds=0.6):
        self.clear()
        dt = 1.0 / fps
        a = self.keep(Circle(center=(0, 0), radius=8, group="jr_hb"), ma, (300.0, 0.0))
        b = self.keep(Circle(center=(100, 0), radius=8, group="jr_hb"), mb, (0.0, 0.0))
        resolve("jr_hb", "jr_hb", bounce=1.0)
        n = round(seconds * fps)
        for _ in range(n):
            for c in (a, b):
                c.move_by(c.vel.x * dt, c.vel.y * dt)
            self.step()
        t, tc = n * dt, 84.0 / 300.0
        va = (ma - mb) / (ma + mb) * 300.0
        vb = 2 * ma / (ma + mb) * 300.0
        return (float(a.center.x) - (84 + va * (t - tc)), float(b.center.x) - (100 + vb * (t - tc)))

    def test_two_balls_follow_the_ideal_paths(self):
        for fps in FPS:
            for ma, mb in ((1.0, 1.0), (1.0, 3.0), (3.0, 1.0)):
                with self.subTest(fps=fps, masses=(ma, mb)):
                    ea, eb = self.head_on(fps, ma, mb)
                    self.assertLess(abs(ea), 0.1)
                    self.assertLess(abs(eb), 0.1)

    def slide(self):
        self.clear()
        self.keep(Rect(center=(100, 0), width=10, height=400, group="jr_sw"), STATIC)
        ball = self.keep(Circle(center=(0, 0), radius=8, group="jr_sb"), 1.0, (400.0, 150.0))
        resolve("jr_sb", "jr_sw", bounce=0.0)
        path = []
        for _ in range(40):
            ball.move_by(ball.vel.x / 60, ball.vel.y / 60)
            self.step()
            path.append((float(ball.center.x), float(ball.center.y)))
        return path

    def test_bounce_zero_slides_as_before(self):
        on = self.slide()
        with mock.patch.object(C, "_BOUNCE_SUBSTEP", False):
            off = self.slide()
        self.assertEqual(on, off)

    def test_canary_the_dropped_leftover(self):
        with mock.patch.object(C, "_BOUNCE_SUBSTEP", False):
            per = self.two_walls([1 / 60])
        self.assertGreater(per, 1.0)


# --------------------------------------------------------------------------
# PE5 -> G2 -- a removed partner is a wall for one sweep
# --------------------------------------------------------------------------


class TestGhostWalls(_World):
    """Breaking a resolve partner in ``@collide``, the frame after, or not at
    all: the survivor's path is the same."""

    def shot(self, mode, fps, y0, vx, speed=300.0, seconds=0.5):
        self.clear()
        dt = 1.0 / fps
        self.keep(Rect(center=(0, 100), width=60, height=24, group="jr_gb"), STATIC)
        ball = self.keep(Circle(center=(0, y0), radius=8, group="jr_gball"), 1.0, (vx, speed))
        resolve("jr_gball", "jr_gb", bounce=1.0)
        doomed = []
        if mode != "plain":
            @collide("jr_gball", "jr_gb")
            def hit(me, b, info):
                if mode == "handler":
                    b.destroy()
                else:
                    doomed.append(b)
        for _ in range(int(seconds * fps)):
            while doomed:
                doomed.pop().destroy()
            ball.move_by(ball.vel.x * dt, ball.vel.y * dt)
            self.step()
        return (float(ball.center.x), float(ball.center.y)), (float(ball.vel.x), float(ball.vel.y))

    def test_handler_later_and_never_take_one_path(self):
        rng = random.Random(3)
        for fps in FPS:
            for _ in range(12):
                y0, vx = rng.uniform(40, 60), rng.uniform(-60, 60)
                with self.subTest(fps=fps, y0=y0, vx=vx):
                    p, vp = self.shot("plain", fps, y0, vx)
                    for mode in ("handler", "later"):
                        q, vq = self.shot(mode, fps, y0, vx)
                        self.assertLess(math.dist(p, q), 1e-6, (mode, p, q))
                        self.assertLess(math.dist(vp, vq), 1e-6, (mode, vp, vq))

    def movable(self, destroy):
        self.clear()
        a = self.keep(Circle(center=(0, 0), radius=8, group="jr_mb"), 1.0, (300.0, 0.0))
        b = self.keep(Circle(center=(20, 0), radius=8, group="jr_mb"), 1.0, (0.0, 0.0))
        resolve("jr_mb", "jr_mb", bounce=1.0)
        if destroy:
            @collide(a, b)
            def gone(me, other, info):
                other.destroy()
        a.move_by(5.0, 0.0)
        self.step()
        return float(a.center.x), float(a.vel.x)

    def test_a_removed_movable_body_leaves_the_mover_where_the_split_would(self):
        """Equal masses, ``bounce=1``: the mover stops where it touched,
        whether the struck body lives or a handler removes it."""
        live_x, live_v = self.movable(False)
        dead_x, dead_v = self.movable(True)
        self.assertAlmostEqual(dead_v, 0.0, places=9)
        self.assertAlmostEqual(live_v, 0.0, places=9)
        self.assertAlmostEqual(dead_x, live_x, delta=SLOP)

    def test_canary_the_ghost_passes_through(self):
        with mock.patch.object(C, "_GHOST_WALLS", False):
            p, _ = self.shot("plain", 30, 45.0, 0.0)
            q, _ = self.shot("handler", 30, 45.0, 0.0)
        self.assertGreater(math.dist(p, q), 1.0)


# --------------------------------------------------------------------------
# LW8 -- a skin contact the sweep never reached
# --------------------------------------------------------------------------


class TestSkinAnswer(_World):
    """A ball that ends a frame within the skin of a brick gets ``@collide``
    that frame, and its bounce that frame: a brick broken the frame after
    let it through."""

    def near_brick(self, gap, bounce=1.0, later=True):
        """A ball r = 8 whose first frame ends ``gap`` below a STATIC brick,
        going up at 360 DU/s (60 Hz). ``later``: the handler marks the brick,
        the next frame destroys it before the ball moves."""
        self.clear()
        brick = self.keep(Rect(center=(0, 100), width=60, height=24, group="jr_sk"), STATIC)
        top = 100 - 12 - gap - 8                   # the ball's centre at the frame's end
        ball = self.keep(Circle(center=(0, top - 6.0), radius=8, group="jr_skb"), 1.0, (0.0, 360.0))
        resolve("jr_skb", "jr_sk", bounce=bounce)
        seen, doomed = [], []

        @collide("jr_skb", "jr_sk")
        def hit(me, b, info):
            seen.append(info.depth)
            if later:
                doomed.append(b)

        ball.move_by(0.0, 6.0)
        self.step()
        first = (float(ball.vel.y), set(ball.touching_sides), list(seen))
        for _ in range(10):
            while doomed:
                doomed.pop().destroy()
            ball.move_by(ball.vel.x / 60, ball.vel.y / 60)
            self.step()
        return first, float(ball.vel.y), brick.is_alive

    def test_a_brick_broken_a_frame_later_still_bounces_the_ball(self):
        for gap in (0.02, 0.1, 0.15):
            with self.subTest(gap=gap):
                (vy1, sides, seen), vy, alive = self.near_brick(gap)
                self.assertEqual(seen, [0.0])               # the handler saw the skin
                self.assertAlmostEqual(vy1, -360.0, places=6)
                self.assertIn("top", sides)                 # and so does touching_*
                self.assertFalse(alive)
                self.assertAlmostEqual(vy, -360.0, places=6)

    def test_bounce_zero_is_left_to_the_next_sweep(self):
        """A ``bounce=0`` skin contact is not answered early: the next sweep
        answers it (and early answers on a ramp made an idle body slide)."""
        (vy1, _sides, _seen), _vy, _alive = self.near_brick(0.1, bounce=0.0, later=False)
        self.assertAlmostEqual(vy1, 360.0, places=6)

    def test_canary_the_ball_goes_through(self):
        with mock.patch.object(C, "_SKIN_ANSWER", False):
            (vy1, _sides, _seen), vy, _alive = self.near_brick(0.1)
        self.assertAlmostEqual(vy1, 360.0, places=6)
        self.assertAlmostEqual(vy, 360.0, places=6)


if __name__ == "__main__":
    unittest.main()
