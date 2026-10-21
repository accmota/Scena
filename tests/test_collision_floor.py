"""``collision.floor``: a world with a floor, or without one (the default).

The floor rules of ``resolve`` are the engine's half of a game with gravity
(the author writes the gravity): a body that touches something under it
stands on it. Floor snap keeps it there on ramps and short frames, a moving
STATIC partner carries it, it steps over small seams, it does not creep down
a ramp, and it does not bounce off the floor it started on. Seen from above
(a race, an RPG), in space or without gravity, those rules made the bottom
side special: a car glued to a wall under it, a barrier sliding under a car
carried it like a lift, a slanted wall slid a car less when it was under it
(Testing Design EX2, measured 2026-10-21). Since then a fresh world has no
floor (``collision.floor = False``) and a game with gravity writes
``collision.floor = True``.

Bug class guarded: **a rule of a world with gravity acting in a world
without one** (one side of a body treated as its feet). The class guard is
the law V10 (equation E16, ``test_laws_motion.TestTopDownHasNoDown``):
without a floor, turning the world turns every path. Here: the setting
itself, each rule on and off, and the hint for a game that asks a floor
question (``floor_below``, ``tilt = "ground"``) in a world without one.

    python tests/run_tiers.py focused test_collision_floor
"""
from __future__ import annotations

import importlib
import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system_support import system_world  # noqa: E402

from scena import STATIC, Circle, Rect, Sprite, Vec2, collision, resolve  # noqa: E402
from scena.collision import get_collision_system  # noqa: E402

_collision = importlib.import_module("scena.collision")


def leave_a_wall_under(floor, seconds=1.0):
    """A car slides along a wall under it, then drives off at a shallow angle."""
    with system_world() as w:
        collision.floor = floor
        parede = Rect(center=(400, 100), width=600, height=40, group="w")
        parede.mass = STATIC
        car = Rect(center=(200, 135), width=40, height=20, group="c")
        car.vel = Vec2(200, -60)
        resolve("c", "w")

        def upd(dt):
            if w.frames_run > 18:
                car.vel = Vec2(200, 40)
            car.move_by(car.vel * dt)
        w.on_update(upd)
        w.step(int(60 * seconds), draw=False)
        return car.center.y


def barrier_slides(floor, under):
    """How far a STATIC barrier sliding 120 in 1 s takes a body leaning on it,
    the barrier under the body (sliding right) or at its left (sliding down)."""
    with system_world() as w:
        collision.floor = floor
        if under:
            barreira = Rect(center=(400, 100), width=200, height=40, group="w")
            car = Rect(center=(400, 131), width=40, height=20, group="c")
            car.vel, passo = Vec2(0, -30), (120, 0)
        else:
            barreira = Rect(center=(100, 400), width=40, height=200, group="w")
            car = Rect(center=(131, 400), width=20, height=40, group="c")
            car.vel, passo = Vec2(-30, 0), (0, -120)
        barreira.mass = STATIC
        resolve("c", "w")
        x0, y0 = car.center.x, car.center.y

        def upd(dt):
            barreira.move_by(passo[0] * dt, passo[1] * dt)
            car.move_by(car.vel * dt)
        w.on_update(upd)
        w.step(60, draw=False)
        return (car.center.x - x0) if under else (y0 - car.center.y)


def push_into_slanted_wall(floor, under):
    """How far a ball pushing straight into a 30-degree wall slides in 0.5 s,
    the wall under it or (the same wall turned a quarter) at its side."""
    with system_world() as w:
        collision.floor = floor
        rampa = Rect(center=(400, 300), width=600, height=40, angle=30 if under else 120, group="w")
        rampa.mass = STATIC
        if under:
            ball = Circle(center=(400, 420), radius=12, group="c")
            v = (0, -150)
        else:
            ball = Circle(center=(520, 300), radius=12, group="c")
            v = (-150, 0)
        resolve("c", "w")
        w.on_update(lambda dt: ball.move_by(v[0] * dt, v[1] * dt))
        w.step(20, draw=False)
        x0, y0 = ball.center.x, ball.center.y
        w.step(30, draw=False)
        return ((ball.center.x - x0) ** 2 + (ball.center.y - y0) ** 2) ** 0.5


class TestTheSetting(unittest.TestCase):
    def test_a_fresh_world_has_no_floor(self):
        with system_world():
            self.assertFalse(collision.floor)
            self.assertFalse(get_collision_system().floor)
        self.assertFalse(_collision._FLOOR_DEFAULT)

    def test_a_flag_and_only_a_flag(self):
        with system_world():
            collision.floor = True
            self.assertTrue(get_collision_system().floor)
            collision.floor = False
            self.assertFalse(collision.floor)
            with self.assertRaises(TypeError):
                collision.floor = "yes"
            chao = Rect(center=(0, 0), width=10, height=10)
            with self.assertRaises(TypeError) as cm:
                collision.floor = chao
            self.assertIn("resolve(", str(cm.exception))
            self.assertFalse(collision.floor)


class TestTheFloorRules(unittest.TestCase):
    """Each rule, seen from above: off without a floor, as before with one."""

    def test_a_body_leaves_a_wall_under_it(self):
        self.assertGreater(leave_a_wall_under(False), 150, "glued to the wall under it")
        self.assertLess(leave_a_wall_under(True), 131, "with a floor, snap keeps a walker down")

    def test_a_barrier_under_a_body_takes_it_as_one_at_its_side(self):
        # A moving wall takes a body leaning on it some way, from any side
        # (the relative-frame sweep); only a floor's lift carries its rider
        # all the way, and only from under it.
        under, side = barrier_slides(False, True), barrier_slides(False, False)
        self.assertAlmostEqual(under, side, delta=1.0)
        self.assertGreater(barrier_slides(True, True), side + 10, "with a floor, a lift carries its rider")

    def test_a_slanted_wall_is_the_same_under_or_at_the_side(self):
        under, side = push_into_slanted_wall(False, True), push_into_slanted_wall(False, False)
        self.assertGreater(side, 20, "vacuous: the ball does not slide")
        self.assertAlmostEqual(under, side, delta=1.0)
        # With a floor, a stop with no sideways intent on a floor keeps (PE2).
        self.assertLess(push_into_slanted_wall(True, True), side - 5)


class TestNoFloorHint(unittest.TestCase):
    """Asking a floor question in a world without one says so, once."""

    def setUp(self):
        _collision._no_floor_hinted[0] = False

    def tearDown(self):
        _collision._no_floor_hinted[0] = False

    def _floor_below(self, floor):
        with system_world() as w:
            collision.floor = floor
            chao = Rect(center=(400, 100), width=600, height=40, group="chao")
            chao.mass = STATIC
            heroi = Rect(center=(400, 140), width=20, height=40, group="heroi")
            resolve("heroi", "chao")
            w.step(2, draw=False)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                heroi.floor_below(dx=10)
                heroi.floor_below(dx=20)
            return [str(c.message) for c in caught]

    def test_floor_below_without_a_floor_says_so_once(self):
        msgs = self._floor_below(False)
        self.assertEqual(len(msgs), 1, msgs)
        self.assertIn("collision.floor = True", msgs[0])

    def test_silent_with_a_floor(self):
        self.assertEqual(self._floor_below(True), [])

    def test_tilt_ground_without_a_floor_says_so(self):
        with system_world() as w:
            chao = Rect(center=(400, 100), width=600, height=40, group="chao")
            chao.mass = STATIC
            heroi = Sprite("space/playerShip1_red.png", center=(400, 160), height=40,
                           hitbox_anchor="bottom", group="heroi")
            heroi.vel = Vec2(0, -100)
            heroi.tilt = "ground"
            resolve("heroi", "chao")
            w.on_update(lambda dt: heroi.move_by(heroi.vel * dt))
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                w.step(30)
            msgs = [str(c.message) for c in caught if "collision.floor" in str(c.message)]
            self.assertEqual(len(msgs), 1, msgs)
            self.assertIn('tilt = "ground"', msgs[0])


if __name__ == "__main__":
    unittest.main()
