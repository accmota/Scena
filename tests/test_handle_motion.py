"""Handle motion readout: .velocity / .speed / .heading / ride .u / .lap.

Run headless:

    python -m unittest tests.test_handle_motion -v
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import (
    Circle, Track, after, every, tween, clock, Handle,
)
from scena.process import (
    reset_process_scheduler,
    tick_processes,
    shortest_delta_deg,
)
from scena.scenamath import Vec2


def _frame(real_dt=0.1):
    clock.advance(real_dt)
    tick_processes()


def _ang_close(got, expect, tol=3.0):
    d = abs((float(got) - float(expect) + 180.0) % 360.0 - 180.0)
    return d <= tol


class HandleMotionTestCase(unittest.TestCase):
    def setUp(self):
        reset_process_scheduler()
        clock.scale = 1.0
        clock.paused = False
        clock._dt = 0.0
        clock._time = 0.0
        clock._real_dt = 0.0
        clock._real_time = 0.0
        clock._frame = 0
        self._owned = []

    def tearDown(self):
        for obj in self._owned:
            try:
                if getattr(obj, "is_alive", False):
                    obj.destroy()
            except Exception:
                pass
        self._owned.clear()
        reset_process_scheduler()

    def track(self, obj):
        self._owned.append(obj)
        return obj


class TestStraightMotionReadout(HandleMotionTestCase):
    def test_before_first_tick_is_zero(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        h = c.move_by(100, 0, time=1.0)
        self.assertAlmostEqual(h.velocity.x, 0.0, places=6)
        self.assertAlmostEqual(h.velocity.y, 0.0, places=6)
        self.assertAlmostEqual(h.speed, 0.0, places=6)
        self.assertAlmostEqual(h.heading, 0.0, places=6)

    def test_linear_move_by_mid_tick(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        h = c.move_by(100, 0, time=1.0)
        _frame(0.1)
        self.assertAlmostEqual(float(h.velocity.x), 100.0, places=4)
        self.assertAlmostEqual(float(h.velocity.y), 0.0, places=4)
        self.assertAlmostEqual(h.speed, 100.0, places=4)
        self.assertAlmostEqual(h.heading, 0.0, places=4)
        _frame(0.4)
        self.assertAlmostEqual(float(h.velocity.x), 100.0, places=4)
        self.assertAlmostEqual(h.speed, 100.0, places=4)

    def test_linear_move_to_matches_move_by(self):
        a = self.track(Circle(center=(10, 20), radius=8))
        b = self.track(Circle(center=(10, 20), radius=8))
        ha = a.move_to(110, 20, time=1.0)
        hb = b.move_by(100, 0, time=1.0)
        _frame(0.25)
        self.assertAlmostEqual(float(ha.velocity.x), float(hb.velocity.x), places=4)
        self.assertAlmostEqual(ha.speed, hb.speed, places=4)
        self.assertAlmostEqual(ha.heading, hb.heading, places=4)

    def test_heading_from_displacement(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        h = c.move_by(30, 30, time=0.5)
        _frame(0.1)
        self.assertTrue(_ang_close(h.heading, 45.0, tol=0.5))

    def test_paused_time_scale_zeros_velocity_holds_heading(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        h = c.move_by(80, 80, time=1.0)
        _frame(0.2)
        self.assertGreater(h.speed, 0.0)
        self.assertTrue(_ang_close(h.heading, 45.0, tol=0.5))
        held = h.heading
        c.time_scale = 0.0
        _frame(0.2)
        self.assertAlmostEqual(h.speed, 0.0, places=6)
        self.assertAlmostEqual(float(h.velocity.x), 0.0, places=6)
        self.assertAlmostEqual(h.heading, held, places=4)
        self.assertFalse(h.done)

    def test_on_done_can_read_last_speed(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        seen = []

        def done():
            seen.append((h.speed, float(h.velocity.x), h.heading))

        h = c.move_by(80, 0, time=0.2, on_done=done)
        _frame(0.2)
        self.assertTrue(h.done)
        self.assertEqual(len(seen), 1)
        self.assertGreater(seen[0][0], 0.0)
        self.assertGreater(seen[0][1], 0.0)
        self.assertAlmostEqual(seen[0][2], 0.0, places=4)
        # Frozen after complete — same last-tick values.
        self.assertAlmostEqual(h.speed, seen[0][0], places=6)

    def test_copy_into_graphic_vel(self):
        platform = self.track(Circle(center=(0, 0), radius=8))
        rider = self.track(Circle(center=(0, 20), radius=8))
        h = platform.move_by(80, 0, time=1.0)
        _frame(0.1)
        rider.vel = h.velocity
        self.assertIsInstance(rider.vel, Vec2)
        self.assertAlmostEqual(float(rider.vel.x), 80.0, places=4)
        self.assertAlmostEqual(float(rider.vel.y), 0.0, places=4)

    def test_does_not_write_graphic_vel(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        self.assertIsNone(c.vel)
        h = c.move_by(40, 0, time=0.4)
        _frame(0.2)
        self.assertGreater(h.speed, 0.0)
        self.assertIsNone(c.vel)

    def test_u_and_lap_are_ride_only(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        h = c.move_to(40, 0, time=0.4)
        with self.assertRaises(AttributeError) as ctx:
            _ = h.u
        self.assertIn("move_along", str(ctx.exception))
        with self.assertRaises(AttributeError) as ctx:
            _ = h.lap
        self.assertIn("move_along", str(ctx.exception))

    def test_readout_is_readonly(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        h = c.move_by(10, 0, time=0.4)
        with self.assertRaises(TypeError):
            h.velocity = (0, 0)
        with self.assertRaises(TypeError):
            h.speed = 0
        with self.assertRaises(TypeError):
            h.heading = 90


class TestStraightFace(HandleMotionTestCase):
    def test_instant_move_by_faces_delta(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        c.rotate_to(0)
        c.move_by(30, 30, face=True)
        self.assertTrue(_ang_close(c.angle, 45.0, tol=0.5))

    def test_instant_move_to_faces_destination(self):
        c = self.track(Circle(center=(10, 10), radius=8))
        c.rotate_to(0)
        c.move_to(10, 110, face=True)
        self.assertTrue(_ang_close(c.angle, 90.0, tol=0.5))
        self.assertAlmostEqual(float(c.center.x), 10.0, places=4)
        self.assertAlmostEqual(float(c.center.y), 110.0, places=4)

    def test_instant_polar_move_by_faces_angle(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        c.rotate_to(0)
        c.move_by(angle=120, distance=40, face=True)
        self.assertTrue(_ang_close(c.angle, 120.0, tol=0.5))

    def test_zero_delta_holds_rotation(self):
        c = self.track(Circle(center=(50, 50), radius=8))
        c.rotate_to(33)
        c.move_by(0, 0, face=True)
        self.assertTrue(_ang_close(c.angle, 33.0, tol=0.5))
        c.move_to(50, 50, face=True)
        self.assertTrue(_ang_close(c.angle, 33.0, tol=0.5))

    def test_timed_move_by_faces_and_matches_heading(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        c.rotate_to(0)
        h = c.move_by(100, 0, time=1.0, face=True)
        self.assertTrue(_ang_close(c.angle, 0.0, tol=0.5))
        _frame(0.25)
        self.assertTrue(_ang_close(c.angle, 0.0, tol=0.5))
        self.assertTrue(_ang_close(h.heading, float(c.angle), tol=1.0))

    def test_timed_move_to_diagonal(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        c.rotate_to(0)
        h = c.move_to(80, 80, time=1.0, face=True)
        _frame(0.1)
        self.assertTrue(_ang_close(c.angle, 45.0, tol=1.0))
        self.assertTrue(_ang_close(h.heading, 45.0, tol=1.0))

    def test_timed_move_to_about_face_keeps_anchor_on_target(self):
        from scena import Rect
        r = self.track(Rect(center=(0, 0), width=20, height=10))
        r.rotate_to(0)
        tlx, tly = float(r.top_left.x), float(r.top_left.y)
        tx, ty = 80.0, 40.0
        r.move_to(tx, ty, time=0.2, about=r.top_left, face=True)
        _frame(0.25)
        self.assertAlmostEqual(float(r.top_left.x), tx, places=5)
        self.assertAlmostEqual(float(r.top_left.y), ty, places=5)
        expect = math.degrees(math.atan2(ty - tly, tx - tlx))
        self.assertTrue(_ang_close(r.angle, expect, tol=0.5))

    def test_face_does_not_fight_rotate_by(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        h = c.move_by(200, 0, time=2.0, face=True)
        _frame(0.05)
        c.rotate_by(30, time=0.4)
        self.assertTrue(h.cancelled)

    def test_yoyo_face_reverses_heading(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        h = c.move_by(100, 0, time=0.2, loops="forever", yoyo=True, face=True)
        _frame(0.1)
        self.assertTrue(_ang_close(c.angle, 0.0, tol=5.0))
        _frame(0.1)  # finish forward lap
        self.assertEqual(h._lap, 1)
        _frame(0.05)  # into reverse lap
        self.assertTrue(_ang_close(c.angle, 180.0, tol=5.0))
        h.cancel()

    def test_sprite_art_angle_world_heading(self):
        from scena import Sprite
        s = self.track(Sprite(center=(0, 0), size=24, art_angle=90))
        s.move_by(50, 0, face=True)
        # World heading = travel direction (0°), not travel − art_angle.
        self.assertTrue(_ang_close(s.angle, 0.0, tol=0.5))


class TestRideMotionReadout(HandleMotionTestCase):
    def test_circle_speed_matches_arc_length(self):
        path = self.track(Track.circle(center=(0, 0), radius=50))
        path._ensure_samples()
        expected = float(path.length) / 2.0
        rider = self.track(Circle(center=(50, 0), radius=4))
        h = rider.move_along(path, time=2.0, ease="linear")
        _frame(0.1)
        self.assertAlmostEqual(h.speed, expected, delta=expected * 0.08)

    def test_face_matches_heading(self):
        c = self.track(Circle(center=(50, 0), radius=6))
        h = c.move_along(Track.circle(center=(0, 0), radius=50), time=1.0, face=True)
        _frame(0.25)
        self.assertTrue(_ang_close(h.heading, float(c.angle), tol=1.0))
        self.assertTrue(_ang_close(h.heading, 180.0, tol=3.0))

    def test_heading_is_tangent_without_face(self):
        a = self.track(Circle(center=(50, 0), radius=6))
        b = self.track(Circle(center=(50, 0), radius=6))
        ha = a.move_along(Track.circle(center=(0, 0), radius=50), time=1.0, face=True)
        hb = b.move_along(Track.circle(center=(0, 0), radius=50), time=1.0, face=False)
        _frame(0.25)
        self.assertAlmostEqual(
            shortest_delta_deg(ha.heading, hb.heading), 0.0, places=2,
        )
        self.assertFalse(_ang_close(b.angle, hb.heading, tol=5.0))

    def test_u_and_lap_on_forever_ride(self):
        rider = self.track(Circle(center=(50, 0), radius=4))
        h = rider.move_along(
            Track.circle(center=(0, 0), radius=50),
            time=1.0, loops="forever", phase=0.25,
        )
        self.assertAlmostEqual(h.u, 0.25, places=4)
        self.assertEqual(h.lap, 0)
        _frame(0.25)
        self.assertAlmostEqual(h.u, 0.5, places=2)
        self.assertEqual(h.lap, 0)
        _frame(1.0)
        self.assertEqual(h.lap, 1)
        self.assertGreaterEqual(h.u, 0.0)
        self.assertLess(h.u, 1.0)
        self.assertFalse(h.done)

    def test_cancel_freezes_readout(self):
        rider = self.track(Circle(center=(50, 0), radius=4))
        h = rider.move_along(
            Track.circle(center=(0, 0), radius=50),
            time=2.0, loops="forever",
        )
        _frame(0.2)
        speed = h.speed
        heading = h.heading
        u = h.u
        lap = h.lap
        self.assertGreater(speed, 0.0)
        h.cancel()
        self.assertTrue(h.cancelled)
        self.assertTrue(h.done)
        self.assertAlmostEqual(h.speed, speed, places=6)
        self.assertAlmostEqual(h.heading, heading, places=4)
        self.assertAlmostEqual(h.u, u, places=6)
        self.assertEqual(h.lap, lap)

    def test_unread_forever_ride_still_moves(self):
        rider = self.track(Circle(center=(50, 0), radius=4))
        h = rider.move_along(
            Track.circle(center=(0, 0), radius=50),
            time=1.0, loops="forever",
        )
        x0, y0 = float(rider.center.x), float(rider.center.y)
        for _ in range(5):
            _frame(0.1)
        self.assertFalse(h.done)
        self.assertFalse(
            math.isclose(float(rider.center.x), x0)
            and math.isclose(float(rider.center.y), y0)
        )

    def test_ride_u_lap_readonly(self):
        rider = self.track(Circle(center=(50, 0), radius=4))
        h = rider.move_along(Track.circle(center=(0, 0), radius=50), time=1.0)
        with self.assertRaises(TypeError):
            h.u = 0.5
        with self.assertRaises(TypeError):
            h.lap = 2


class TestNonMotionHandles(HandleMotionTestCase):
    def test_after_raises(self):
        h = after(1.0, lambda: None)
        self.assertIsInstance(h, Handle)
        with self.assertRaises(AttributeError) as ctx:
            _ = h.velocity
        msg = str(ctx.exception)
        self.assertIn("velocity", msg)
        self.assertIn("move_along", msg)
        with self.assertRaises(AttributeError):
            _ = h.speed
        with self.assertRaises(AttributeError):
            _ = h.heading

    def test_every_wait_rotate_scale_tween_raise(self):
        c = self.track(Circle(center=(0, 0), radius=8))
        handles = [
            every(0.5, lambda: None),
            c.rotate_by(90, time=0.3),
            c.scale_to(2, time=0.3),
            tween(c["radius"], 20, time=0.3),
        ]
        for h in handles:
            with self.subTest(kind=h.kind):
                with self.assertRaises(AttributeError):
                    _ = h.velocity


if __name__ == "__main__":
    unittest.main()
