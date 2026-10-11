"""
clock / keyp / mouse as @= formula sources (Container graph bridge).

Level sample (window-open / per-frame world mouse) vs motion/press edges:
``Mouse._sync_position``, ``Clock._mark_play_start``, ``KeyPressed._seed_held``.
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.orchestration import ScenaFramework
from scena.shapes import Circle
from scena.state import State, get_scena_system
from scena.input import MAX_FRAME_DT, Clock, KeyPressed, Mouse

from tests.leftovers import module_sweep  # noqa: E402
from tests.graph_support import gc_paused, settled_graph_size  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


class TestMouseAsPoint(unittest.TestCase):
    """Plain ``mouse`` is a point wherever a Point / ``(x, y)`` is accepted."""

    def test_plain_mouse_where_a_point_is_expected(self):
        from scena.history import Contrail
        from scena.shapes import Point

        mouse = Mouse()
        mouse._update_position(30, 40)

        marker = Circle(center=(0, 0), radius=4)
        marker.move_to(mouse)
        self.assertEqual(marker.center.x, 30)
        self.assertEqual(marker.center.y, 40)

        live = Circle(center=lambda: mouse, radius=2)
        mouse._update_position(7, 8)
        self.assertEqual(live.center.x, 7)
        self.assertEqual(live.center.y, 8)

        pinned = Circle(center=mouse, radius=2)
        mouse._update_position(1, 2)
        self.assertEqual(pinned.center.x, 7)
        self.assertEqual(pinned.center.y, 8)
        self.assertEqual(live.center.x, 1)
        self.assertEqual(live.center.y, 2)

        trail = Contrail(max_points=4, color="red")
        try:
            mouse._update_position(15, 25)
            trail.snapshot(mouse)
            mouse._update_position(0, 0)
            self.assertAlmostEqual(float(trail.last.x), 15)
            self.assertAlmostEqual(float(trail.last.y), 25)
            self.assertEqual(live.center.x, 0)
            self.assertEqual(live.center.y, 0)
        finally:
            trail.destroy()

        with self.assertRaises(TypeError):
            marker.move_by(mouse)

        p = Point(1, 0)
        origin = Mouse()
        origin._update_position(0, 0)
        p.rotate_by(90, about=origin)
        self.assertAlmostEqual(p.x, 0.0, places=5)
        self.assertAlmostEqual(p.y, 1.0, places=5)


class TestMouseFormulaSource(unittest.TestCase):
    def test_whole_mouse_drives_center(self):
        mouse = Mouse()
        c = Circle(center=(0, 0), radius=5)
        c.center @= mouse
        self.assertEqual(c.center.x, 0)
        self.assertEqual(c.center.y, 0)
        mouse._update_position(12, 34)
        self.assertEqual(c.center.x, 12)
        self.assertEqual(c.center.y, 34)

    def test_position_drives_linked_center(self):
        mouse = Mouse()
        c = Circle(center=(0, 0), radius=5)
        c.center["x"] @= (lambda: mouse.x)
        c.center["y"] @= (lambda: mouse.y)

        self.assertEqual(c.center.x, 0)
        self.assertEqual(c.center.y, 0)

        mouse._update_position(120, 340)
        self.assertEqual(c.center.x, 120)
        self.assertEqual(c.center.y, 340)

        mouse._update_position(-10, 50)
        self.assertEqual(c.center.x, -10)
        self.assertEqual(c.center.y, 50)

    def test_press_drives_linked_scalar(self):
        mouse = Mouse()
        st = State()
        st.create("held", initial=0.0)
        st["held"] @= (lambda: 1.0 if mouse.press(Mouse.BTN_LEFT) else 0.0)

        self.assertEqual(st.held, 0.0)
        mouse._button_down(Mouse.BTN_LEFT, 10, 20)
        self.assertEqual(st.held, 1.0)
        mouse._button_up(Mouse.BTN_LEFT)
        self.assertEqual(st.held, 0.0)

    def test_unused_mouse_skips_mark_dirty(self):
        """A2: no pull consumers → update() early-out; graph size stable."""
        mouse = Mouse()
        ss = get_scena_system()
        self.enterContext(gc_paused())
        n0 = settled_graph_size(ss)
        self.assertFalse(mouse._requires_pull_invalidate())

        for i in range(30):
            mouse._update_position(i, i * 2)
            mouse._button_down(Mouse.BTN_LEFT, i, i)
            mouse._button_up(Mouse.BTN_LEFT)

        self.assertEqual(len(ss.dependency_graph.nodes), n0)
        self.assertFalse(mouse._requires_pull_invalidate())

    def test_mouse_xy_are_not_attributes(self):
        mouse = Mouse()
        with self.assertRaises(TypeError):
            # Raw number RHS — same rule as clock.time / keyp results.
            Circle(center=(0, 0), radius=5).center["x"] @= mouse.x

    def test_sync_position_pulls_without_dx(self):
        """Window-open sample: level write, not a motion from the fake (0, 0)."""
        mouse = Mouse()
        c = Circle(center=(40, 40), radius=5)
        c.center["x"] @= (lambda: mouse.x)
        c.center["y"] @= (lambda: mouse.y)
        self.assertEqual(c.center.x, 0)
        self.assertEqual(c.center.y, 0)

        changed = mouse._sync_position(120, 340)
        self.assertTrue(changed)
        self.assertEqual(c.center.x, 120)
        self.assertEqual(c.center.y, 340)
        self.assertEqual(mouse.dx, 0)
        self.assertEqual(mouse.dy, 0)

        self.assertFalse(mouse._sync_position(120, 340))
        self.assertEqual(mouse.dx, 0)
        self.assertEqual(mouse.dy, 0)

    def test_sync_then_move_dx_from_synced_point(self):
        mouse = Mouse()
        mouse._sync_position(100, 200)
        self.assertEqual(mouse.dx, 0)
        mouse._update_position(110, 205)
        self.assertEqual(mouse.dx, 10)
        self.assertEqual(mouse.dy, 5)

    def test_unused_mouse_sync_skips_mark_dirty(self):
        mouse = Mouse()
        self.assertFalse(mouse._requires_pull_invalidate())
        mouse._sync_position(10, 20)
        mouse._sync_position(10, 20)
        mouse._sync_position(30, 40)
        self.assertFalse(mouse._requires_pull_invalidate())


class TestClockFormulaSource(unittest.TestCase):
    def test_time_drives_linked_scalar(self):
        clock = Clock()
        st = State()
        st.create("t", initial=-1.0)
        st["t"] @= (lambda: clock.time)

        self.assertEqual(st.t, 0.0)
        clock.advance(0.25)
        self.assertAlmostEqual(st.t, 0.25, places=5)
        clock.advance(0.1)
        self.assertAlmostEqual(st.t, 0.35, places=5)

    def test_unused_clock_skips_mark_dirty(self):
        clock = Clock()
        self.assertFalse(clock._requires_pull_invalidate())
        clock.advance(0.016)
        clock.advance(0.016)
        self.assertFalse(clock._requires_pull_invalidate())

    def test_mark_play_start_drops_construct_backlog(self):
        clock = Clock()
        clock._last_time = time.perf_counter() - 2.0
        clock._start_time = clock._last_time
        clock._mark_play_start()
        self.assertEqual(clock.time, 0.0)
        self.assertEqual(clock.frame, 0)

        clock._tick(time.perf_counter())
        self.assertLess(clock.dt, 0.5)
        self.assertLess(clock.real_time, 0.5)
        self.assertEqual(clock.frame, 1)

    def test_mark_play_start_does_not_advance_linked_time(self):
        clock = Clock()
        st = State()
        st.create("t", initial=-1.0)
        st["t"] @= (lambda: clock.time)
        self.assertEqual(st.t, 0.0)
        clock._mark_play_start()
        self.assertEqual(st.t, 0.0)
        clock.advance(0.1)
        self.assertAlmostEqual(st.t, 0.1, places=5)


class TestClockTickClamp(unittest.TestCase):
    """Wall-clock ``tick`` is environment input: clamp, don't crash."""

    def _started(self):
        clock = Clock()
        clock._mark_play_start()
        return clock, clock._last_time

    def test_backward_step_is_zero(self):
        clock, t0 = self._started()
        clock._tick(t0 - 5.0)
        self.assertEqual(clock.dt, 0.0)
        self.assertEqual(clock.real_dt, 0.0)
        self.assertEqual(clock.time, 0.0)

    def test_hitch_is_capped_for_the_world_only(self):
        clock, t0 = self._started()
        clock._tick(t0 + 10.0)
        self.assertAlmostEqual(clock.dt, MAX_FRAME_DT)
        self.assertAlmostEqual(clock.time, MAX_FRAME_DT)
        self.assertAlmostEqual(clock.real_dt, 10.0, places=6)
        self.assertAlmostEqual(clock.real_time, 10.0, places=6)

    def test_cap_applies_before_scale(self):
        clock, t0 = self._started()
        clock.scale = 0.5
        clock._tick(t0 + 10.0)
        self.assertAlmostEqual(clock.dt, MAX_FRAME_DT * 0.5)

    def test_normal_frame_unchanged(self):
        clock, t0 = self._started()
        clock._tick(t0 + 1 / 60)
        self.assertAlmostEqual(clock.dt, 1 / 60, places=9)

    def test_explicit_advance_is_not_capped(self):
        clock = Clock()
        clock.advance(2.0)
        self.assertAlmostEqual(clock.dt, 2.0)

    def test_scale_rejects_negative_nan_inf(self):
        # Regression: `max(0.0, float(value))` silently turned a negative
        # or NaN scale into 0 (misleadingly reading as "paused"), and
        # silently accepted inf (world time then advances by an unbounded
        # amount every frame).
        clock, _t0 = self._started()
        for bad in (-1.0, float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError):
                clock.scale = bad
        self.assertEqual(clock.scale, 1.0)
        clock.scale = 0.0  # still the documented "pause" value
        self.assertEqual(clock.scale, 0.0)
        self.assertTrue(clock.paused)


class TestKeypFormulaSource(unittest.TestCase):
    def test_held_key_drives_linked_center_x(self):
        keyp = KeyPressed()
        c = Circle(center=(800, 700), radius=10)
        c.center["x"] @= (lambda: 1200 if keyp("D") else 800)

        self.assertEqual(c.center.x, 800)
        keyp._press("D")
        self.assertEqual(c.center.x, 1200)
        keyp._release("D")
        self.assertEqual(c.center.x, 800)

    def test_seed_held_is_level_not_once_edge(self):
        keyp = KeyPressed()
        c = Circle(center=(800, 700), radius=10)
        c.center["x"] @= (lambda: 1200 if keyp("D") else 800)
        self.assertEqual(c.center.x, 800)

        keyp._seed_held(["D"])
        self.assertTrue(keyp("D"))
        self.assertFalse(keyp.once("D"))
        self.assertEqual(c.center.x, 1200)

        keyp._seed_held(["D"])
        self.assertEqual(c.center.x, 1200)
        self.assertFalse(keyp.once("D"))

        keyp._release("D")
        self.assertEqual(c.center.x, 800)

    def test_seed_held_shift_does_not_fire_once(self):
        keyp = KeyPressed()
        keyp._seed_held(["LEFT_SHIFT"])
        self.assertTrue(keyp("SHIFT"))
        self.assertFalse(keyp.once("SHIFT"))
        self.assertFalse(keyp.once("LEFT_SHIFT"))

    def test_unused_keyp_seed_skips_mark_dirty(self):
        keyp = KeyPressed()
        self.assertFalse(keyp._requires_pull_invalidate())
        keyp._seed_held(["D", "A"])
        keyp._seed_held(["D", "A"])
        keyp._seed_held([])
        self.assertFalse(keyp._requires_pull_invalidate())


class TestInputSampleGuards(unittest.TestCase):
    def test_sync_and_seed_noop_without_window(self):
        fw = ScenaFramework.get_instance()
        self.assertIsNone(fw._window)
        fw._sync_pointer_level(hover=True)
        fw._seed_held_keys_from_os()


if __name__ == "__main__":
    unittest.main()
