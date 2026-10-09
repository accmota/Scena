"""
Frame-batch / pull-based reactivity semantics.

Outside run(), and inside begin_frame_batch()…flush():
  - pure derived data (Derivate parts, @= targets) is fresh on read (pull)
  - effects (@when / @on_change) wait for flush() while deferring
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.shapes import Rect, Line, Point
from scena.state import get_scena_system, flush
from scena.events import when, unregister_event, cleanup_global_event_system

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


class TestPullOutsideFrameBatch(unittest.TestCase):
    def test_construction_pulls_on_read(self):
        rect = Rect(center=(50, 50), width=100, height=40, angle=0.0)
        self.assertAlmostEqual(rect.top_left.x, 0.0, places=5)
        rect.angle = 90
        # Pull: derivate corners refresh on read
        self.assertNotAlmostEqual(rect.top_left.x, 0.0, places=5)


class TestPullFrameBatch(unittest.TestCase):
    def tearDown(self):
        ss = get_scena_system()
        ss.end_frame_batch()
        ss.flush()
        cleanup_global_event_system()

    def test_own_derivate_fresh_on_read_mid_batch(self):
        rect = Rect(center=(100, 100), width=80, height=40, angle=0.0)
        old_tl_x = rect.top_left.x

        ss = get_scena_system()
        ss.begin_frame_batch()
        rect.angle = 90
        self.assertAlmostEqual(rect.angle, 90, places=5)
        # Own corner fresh on read — no flush required
        self.assertNotAlmostEqual(rect.top_left.x, old_tl_x, places=5)
        ss.end_frame_batch()

    def test_linked_dependent_fresh_on_read_without_flush(self):
        rect = Rect(top_left=(0, 0), width=100, height=50)
        line = Line(p1=lambda: rect.right_center, p2=(200, 25))
        self.assertAlmostEqual(line.p1.x, 100.0, places=5)

        ss = get_scena_system()
        ss.begin_frame_batch()
        rect.move_by(10, 0)
        # Own right_center fresh…
        self.assertAlmostEqual(rect.right_center.x, 110.0, places=5)
        # …and linked p1 also fresh on read (pull) — flush not required for data
        self.assertAlmostEqual(line.p1.x, 110.0, places=5)
        ss.end_frame_batch()

    def test_move_then_rotate_order_independent_mid_batch(self):
        """Chained transforms on one shape must not depend on call order."""
        target_x = 400.0

        ss = get_scena_system()

        a = Rect(top_left=(100, 200), width=60, height=40, angle=0.0)
        _ = a.center
        ss.begin_frame_batch()
        a.move_to(x=target_x)
        a.rotate_by(45)
        cx_a, cy_a = a.center.x, a.center.y
        ang_a = a.angle
        ss.end_frame_batch()
        ss.flush()

        b = Rect(top_left=(100, 200), width=60, height=40, angle=0.0)
        _ = b.center
        ss.begin_frame_batch()
        b.rotate_by(45)
        b.move_to(x=target_x)
        cx_b, cy_b = b.center.x, b.center.y
        ang_b = b.angle
        ss.end_frame_batch()
        ss.flush()

        self.assertAlmostEqual(cx_a, target_x, places=5)
        self.assertAlmostEqual(cx_b, target_x, places=5)
        self.assertAlmostEqual(cx_a, cx_b, places=5)
        self.assertAlmostEqual(cy_a, cy_b, places=5)
        self.assertAlmostEqual(ang_a, ang_b, places=5)

    def test_writes_do_not_flush_effects_while_deferring(self):
        rect = Rect(center=(50, 50), width=40, height=20, angle=0.0)
        fired = {'n': 0}

        @when(lambda: rect.angle > 10)
        def on_angle():
            fired['n'] += 1

        ss = get_scena_system()
        ss.begin_frame_batch()
        rect.angle = 30
        self.assertEqual(fired['n'], 0)
        flush()
        self.assertEqual(fired['n'], 1)
        flush()
        self.assertEqual(fired['n'], 1)  # exactly once — no double fire
        ss.end_frame_batch()
        unregister_event(on_angle)

    def test_flush_is_idempotent_when_clean(self):
        Point(1, 2)
        ss = get_scena_system()
        ss.begin_frame_batch()
        flush()
        flush()
        ss.end_frame_batch()

    def test_structural_resolve_once_per_dirty_read(self):
        rect = Rect(center=(50, 50), width=40, height=20, angle=0.0)
        _ = rect.top_left
        line = Line(p1=lambda: rect.right_center, p2=(200, 50))

        calls = []
        orig = rect._update_impl

        def counting():
            calls.append(1)
            return orig()

        ss = get_scena_system()
        ss.begin_frame_batch()
        rect._update_impl = counting
        try:
            rect.angle = 30
            self.assertEqual(len(calls), 0)  # write does not recompute
            _ = rect.top_left.x
            self.assertEqual(len(calls), 1)  # first read pulls once
            _ = rect.right_center.x
            self.assertEqual(len(calls), 1)  # memoized until next dirty
            self.assertAlmostEqual(line.p1.x, rect.right_center.x, places=5)
        finally:
            rect._update_impl = orig
            ss.end_frame_batch()


class TestSkipColdDerivates(unittest.TestCase):
    """Cold Derivate slots stay unregistered; links and access materialize them."""

    def test_rect_corners_not_registered_until_accessed(self):
        rect = Rect(center=(50, 50), width=100, height=40, angle=0.0)
        self.assertNotIn('top_left', rect.__dict__)
        self.assertNotIn('right_center', rect.__dict__)
        self.assertIn('center', rect.__dict__)
        self.assertIn('width', rect.__dict__)

    def test_access_materializes_fresh_corner(self):
        rect = Rect(center=(50, 50), width=100, height=40, angle=0.0)
        rect.angle = 90
        self.assertAlmostEqual(rect.top_left.x, 30.0, places=5)

    def test_linked_midpoint_stays_live(self):
        rect = Rect(center=(0, 0), width=100, height=50, angle=0.0)
        line = Line(p1=lambda: rect.right_center, p2=(200, 0))
        self.assertAlmostEqual(line.p1.x, 50.0, places=5)
        rect.center = (10, 0)
        self.assertAlmostEqual(line.p1.x, 60.0, places=5)
        self.assertTrue(rect.right_center._derivate_live)


if __name__ == '__main__':
    unittest.main(verbosity=2)
