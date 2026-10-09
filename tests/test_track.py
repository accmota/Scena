"""Track + move_along gates (proposal stages 1–8).

Run headless:

    python -m unittest tests.test_track tests.test_curves -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import (
    Circle, Ellipse, Point, Track, Rect, Square, RegularPolygon, Sprite, Vec2, clock,
    flush, group, resolve, show_tracks, STATIC, tween,
)
from scena.collision import get_collision_system, reset_collision_system
from scena.geom import _oriented_box_verts
from scena.track import shape_outline, tracks_overlay_wanted
from scena.process import reset_process_scheduler, tick_processes
from scena.state import FieldType, DerivedAttributeError, LinkedAttributeError


def _frame(dt=0.1):
    clock.advance(dt)
    tick_processes()


def _xy_close(got, expect, places=1):
    return (
        round(float(got[0]), places) == round(float(expect[0]), places)
        and round(float(got[1]), places) == round(float(expect[1]), places)
    )


def _ang_close(got, expect, tol=3.0):
    d = abs((float(got) - float(expect) + 180.0) % 360.0 - 180.0)
    return d <= tol


class TrackTestCase(unittest.TestCase):
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
        show_tracks(False)

    def tearDown(self):
        for obj in self._owned:
            try:
                if getattr(obj, "is_alive", False):
                    obj.destroy()
            except Exception:
                pass
        self._owned.clear()
        reset_process_scheduler()
        show_tracks(False)

    def track(self, obj):
        self._owned.append(obj)
        return obj


# ---------------------------------------------------------------------------
# Stage 1 — Track core
# ---------------------------------------------------------------------------

class TestTrackCore(TrackTestCase):
    def test_empty_path_is_closed_floating_eight(self):
        p = self.track(Track())
        e = self.track(Track.eight())
        self.assertTrue(p.closed)
        self.assertTrue(p.is_floating)
        self.assertFalse(p.visible)
        p._ensure_samples()
        e._ensure_samples()
        self.assertGreater(float(p.length), 0.0)
        self.assertTrue(_xy_close(p.local_at(0.0), (0.0, 0.0), places=4))
        self.assertTrue(_xy_close(p.local_at(0.2), e.local_at(0.2), places=4))
        a = p.at(0.0)
        b = p.at(1.0)
        self.assertAlmostEqual(a[0], b[0], places=4)
        self.assertAlmostEqual(a[1], b[1], places=4)

    def test_empty_path_is_eight(self):
        z = self.track(Track())
        e = self.track(Track.eight(width=90, height=40))
        z._ensure_samples()
        e._ensure_samples()
        self.assertTrue(_xy_close(z.local_at(0.2), e.local_at(0.2), places=4))
        self.assertTrue(_xy_close(z.at(0.0), e.at(0.0), places=4))

    def test_move_along_empty_path_returns_to_start(self):
        bug = self.track(Circle(center=(200, 300), radius=5))
        x0, y0 = float(bug.center.x), float(bug.center.y)
        h = bug.move_along(Track(), time=0.4)
        _frame(0.4)
        self.assertTrue(h.done)
        self.assertAlmostEqual(float(bug.center.x), x0, places=1)
        self.assertAlmostEqual(float(bug.center.y), y0, places=1)

    def test_reversed_shares_tables_and_is_involution(self):
        p = self.track(Track.circle(center=(0, 0), radius=20))
        p._ensure_samples()
        rev = p.reversed()
        self.assertIs(rev._alias_of, p)
        self.assertIs(rev.reversed(), p)
        self.assertTrue(rev._read_reversed)
        # Same geometry object (host tables), opposite direction.
        self.assertAlmostEqual(p.at(0.0)[0], rev.at(0.0)[0], places=1)
        self.assertAlmostEqual(p.at(0.25)[1], -rev.at(0.25)[1], places=1)

    def test_styled_draws_unstyled_stays_invisible(self):
        raw = self.track(Track())
        ink = self.track(Track(points=[(0, 0), (40, 10), (80, 0)], color="tomato"))
        self.assertFalse(raw.visible)
        self.assertTrue(ink.visible)
        self.assertIsNone(raw.layer)
        self.assertIsNotNone(ink.layer)

    def test_width_is_not_stroke_alias(self):
        with self.assertRaises(TypeError) as cm:
            Track(points=[(0, 0), (40, 0)], width=4)
        msg = str(cm.exception)
        self.assertIn("line_width", msg)
        self.assertIn("eight", msg)
        self.assertIn("unexpected keyword", msg)
        self.assertIn("Valid:", msg)
        eight = self.track(Track.eight(width=90, height=40, color="gold", line_width=2))
        self.assertAlmostEqual(float(eight.line_width), 2.0, places=4)

    def test_visible_true_promotes_unstyled_onto_layer(self):
        p = self.track(Track())
        self.assertIsNone(p.layer)
        p.visible = True
        self.assertTrue(p.visible)
        self.assertIsNotNone(p.layer)
        p.visible = False
        self.assertFalse(p.visible)
        self.assertIsNone(p.layer)

    def test_moving_linked_center_does_not_rebuild(self):
        earth = self.track(Circle(center=(0, 0), radius=8))
        track = self.track(Track.circle(center=(0, 0), radius=40))
        track.center @= earth.center
        track.at(0.0)
        n = track._rebuilds
        earth.move_to(80, 10)
        self.assertEqual(track._rebuilds, n)
        x, y = track.at(0.0)
        self.assertAlmostEqual(x, 120.0, places=1)
        self.assertAlmostEqual(y, 10.0, places=1)

    def test_linked_control_points_rebuild_once_per_dirty_read(self):
        a = self.track(Circle(center=(0, 0), radius=4))
        p = self.track(Track(
            points=[
                lambda: (a.center.x, a.center.y),
                (50, 0),
                (100, 0),
            ],
            smooth=0,
        ))
        self.assertTrue(_xy_close(p.at(0.0), (0.0, 0.0), places=0))
        n = p._rebuilds
        a.move_to(10, 10)
        # Cold pull: unread → no rebuild yet; first sample sees new verts.
        self.assertEqual(p._rebuilds, n)
        self.assertTrue(_xy_close(p.at(0.0), (10.0, 10.0), places=0))
        self.assertEqual(p._rebuilds, n + 1)
        p.at(0.5)
        self.assertEqual(p._rebuilds, n + 1)

    def test_quality_low_has_fewer_samples(self):
        pts = [(0, 0), (40, 25), (80, 0), (120, 30), (160, 0)]
        hi = self.track(Track(points=pts, smooth=1, quality="high"))
        lo = self.track(Track(points=pts, smooth=1, quality="low"))
        hi.at(0.0)
        lo.at(0.0)
        self.assertLess(len(lo._xs), len(hi._xs))

    def test_spaced_points_closed_no_duplicate_wrap(self):
        p = self.track(Track.circle(center=(10, 20), radius=50))
        pts = p.spaced_points(8)
        self.assertEqual(len(pts), 8)
        self.assertIsInstance(pts[0], tuple)
        self.assertEqual(len(pts[0]), 2)
        # Closed: first sample is at u=0; no second copy of the wrap point.
        self.assertTrue(_xy_close(pts[0], p.at(0.0), places=4))
        for i, (x, y) in enumerate(pts):
            self.assertTrue(_xy_close((x, y), p.at(i / 8.0), places=4))
            d = ((x - 10.0) ** 2 + (y - 20.0) ** 2) ** 0.5
            self.assertAlmostEqual(d, 50.0, places=0)
        # Neighbors are distinct (not a collapsed sample).
        self.assertFalse(_xy_close(pts[0], pts[1], places=1))
        self.assertFalse(_xy_close(pts[0], pts[-1], places=1))

    def test_spaced_points_open_includes_endpoints(self):
        p = self.track(Track(points=[(0, 0), (100, 0)], smooth=0))
        pts = p.spaced_points(5)
        self.assertEqual(len(pts), 5)
        self.assertTrue(_xy_close(pts[0], (0.0, 0.0), places=4))
        self.assertTrue(_xy_close(pts[-1], (100.0, 0.0), places=4))
        self.assertTrue(_xy_close(pts[2], (50.0, 0.0), places=4))
        for i, (x, y) in enumerate(pts):
            self.assertTrue(_xy_close((x, y), p.at(i / 4.0), places=4))

    def test_spaced_points_n_one_and_shape_outline(self):
        p = self.track(Track.circle(center=(0, 0), radius=30))
        one = p.spaced_points(1)
        self.assertEqual(len(one), 1)
        self.assertTrue(_xy_close(one[0], p.at(0.0), places=4))

        src = self.track(Rect(center=(50, 50), width=40, height=20))
        outline = self.track(Track(src))
        pts = outline.spaced_points(4)
        self.assertEqual(len(pts), 4)
        self.assertTrue(outline.closed)
        self.assertIsInstance(pts[0], tuple)


# ---------------------------------------------------------------------------
# Rounded Rect / Square outline (Track / move_along silhouette)
# ---------------------------------------------------------------------------

class TestRoundedRectOutline(TrackTestCase):
    def test_sharp_rect_matches_oriented_box_verts(self):
        r = self.track(Rect(center=(10, 20), width=40, height=20, angle=15))
        outline, closed = shape_outline(r)
        sharp = _oriented_box_verts(r)
        self.assertTrue(closed)
        self.assertEqual(len(outline), 4)
        for got, expect in zip(outline, sharp):
            self.assertTrue(_xy_close(got, expect, places=6))

    def test_rounded_avoids_sharp_corner(self):
        # Local BR sharp corner of a 40×20 rect at origin is (20, -10).
        r = self.track(Rect(center=(0, 0), width=40, height=20, corner_radius=8))
        outline, closed = shape_outline(r)
        self.assertTrue(closed)
        self.assertGreater(len(outline), 4)
        sharp_br = (20.0, -10.0)
        for x, y in outline:
            self.assertFalse(
                _xy_close((x, y), sharp_br, places=1),
                f"outline still visits sharp corner {sharp_br}: {(x, y)}",
            )
        # A point on the BR fillet (mid-angle ≈ -45°) must be near the polyline.
        mid = (20.0 - 8.0 + 8.0 * 0.7071, -10.0 + 8.0 - 8.0 * 0.7071)
        dmin = min((x - mid[0]) ** 2 + (y - mid[1]) ** 2 for x, y in outline)
        self.assertLess(dmin, 1.0)

    def test_r_to_zero_u0_approaches_bl(self):
        sharp = self.track(Rect(center=(0, 0), width=40, height=20))
        rounded = self.track(
            Rect(center=(0, 0), width=40, height=20, corner_radius=0.25)
        )
        # Any positive radius, including below half a pixel, follows the fillet.
        o0, _ = shape_outline(sharp)
        o1, _ = shape_outline(rounded)
        self.assertGreater(len(o1), 4)
        self.assertTrue(_xy_close(o1[0], (-20.0 + 0.25, -10.0), places=4))
        self.assertTrue(_xy_close(o0[0], (-20.0, -10.0), places=4))
        # Small but visible r: u=0 is bottom-edge start after BL fillet.
        soft = self.track(Rect(center=(0, 0), width=40, height=20, corner_radius=4))
        o2, _ = shape_outline(soft)
        self.assertTrue(_xy_close(o2[0], (-20.0 + 4.0, -10.0), places=4))
        self.assertTrue(_xy_close(o0[0], (-20.0, -10.0), places=4))

    def test_square_inherits_rounding(self):
        sq = self.track(Square(center=(0, 0), length=30, corner_radius=6))
        outline, closed = shape_outline(sq)
        self.assertTrue(closed)
        self.assertGreater(len(outline), 4)
        # Sharp TL/TR/BL/BR of a 30×30 square: (±15, ±15).
        for corner in ((15.0, 15.0), (15.0, -15.0), (-15.0, 15.0), (-15.0, -15.0)):
            for x, y in outline:
                self.assertFalse(_xy_close((x, y), corner, places=1))

    def test_live_track_rebuilds_when_corner_radius_changes(self):
        r = self.track(Rect(center=(0, 0), width=40, height=20, corner_radius=0))
        t = self.track(Track(r))
        t.at(0.0)
        n = t._rebuilds
        n_verts = len(shape_outline(r)[0])
        self.assertEqual(n_verts, 4)
        r.corner_radius = 10
        t.at(0.0)
        self.assertEqual(t._rebuilds, n + 1)
        self.assertGreater(len(shape_outline(r)[0]), 4)
        # Travel sample sits on the silhouette, not the sharp corner.
        pt = t.at(0.0)
        self.assertTrue(_xy_close(pt, (-20.0 + 10.0, -10.0), places=2))

    def test_move_along_rounded_rect_stays_on_fillet(self):
        box = self.track(
            Rect(center=(0, 0), width=40, height=20, corner_radius=8, color="cyan")
        )
        bug = self.track(Circle(center=(0, 0), radius=3))
        # u≈0 starts on bottom edge after BL; a short trip stays near the bottom.
        h = bug.move_along(box, time=0.1, span=(0.0, 0.05))
        _frame(0.1)
        self.assertTrue(h.done)
        # Must not sit at the sharp BL (-20, -10).
        self.assertFalse(_xy_close(
            (float(bug.center.x), float(bug.center.y)), (-20.0, -10.0), places=1,
        ))
        self.assertAlmostEqual(float(bug.center.y), -10.0, places=0)


# ---------------------------------------------------------------------------
# Stage 2 — move_along
# ---------------------------------------------------------------------------

class TestMoveAlong(TrackTestCase):
    def test_interrupt_move_to(self):
        c = self.track(Circle(center=(0, 0), radius=6))
        h1 = c.move_to(100, 0, time=1.0)
        _frame(0.2)
        h2 = c.move_along(
            Track(points=[(float(c.center.x), float(c.center.y)), (float(c.center.x), 80)], smooth=0),
            time=0.4,
        )
        self.assertTrue(h1.cancelled)
        self.assertFalse(h2.cancelled)
        _frame(0.4)
        self.assertTrue(h2.done)
        self.assertAlmostEqual(float(c.center.y), 80.0, places=1)

    def test_interrupt_move_along_with_move_to(self):
        c = self.track(Circle(center=(50, 0), radius=6))
        h1 = c.move_along(Track.circle(center=(0, 0), radius=50), time=2.0)
        _frame(0.1)
        h2 = c.move_to(10, 10, time=0.2)
        self.assertTrue(h1.cancelled)
        _frame(0.2)
        self.assertTrue(h2.done)
        self.assertAlmostEqual(float(c.center.x), 10.0, places=1)

    def test_span_reverses(self):
        c = self.track(Circle(center=(50, 0), radius=4))
        c.move_along(Track.circle(center=(0, 0), radius=50), time=1.0, span=(1, 0))
        _frame(0.25)
        self.assertAlmostEqual(float(c.center.x), 0.0, places=0)
        self.assertAlmostEqual(float(c.center.y), -50.0, places=0)

    def test_phase_starts_at_offset(self):
        c = self.track(Circle(center=(0, 0), radius=4))
        track = self.track(Track.circle(center=(0, 0), radius=50))
        c.move_along(track, time=1.0, phase=0.25)
        self.assertAlmostEqual(float(c.center.x), 0.0, places=0)
        self.assertAlmostEqual(float(c.center.y), 50.0, places=0)

    def test_live_hexagon_and_destroy_freeze(self):
        hexagon = self.track(RegularPolygon(n=6, center=(0, 0), radius=40))
        rider = self.track(Circle(center=(40, 0), radius=4))
        h = rider.move_along(hexagon, time=2.0)
        _frame(0.2)
        self.assertFalse(h.done)
        x1, y1 = float(rider.center.x), float(rider.center.y)
        hexagon.destroy()
        _frame(0.3)
        self.assertFalse(h.cancelled)
        self.assertFalse(h.done)
        # Still travelling on the frozen outline.
        self.assertFalse(_xy_close((x1, y1), (rider.center.x, rider.center.y), places=1))

    def test_group_broadcast_returns_handles(self):
        # Unique group id: "fleet" is reused across the suite and is not wiped.
        a = self.track(Circle(center=(10, 10), radius=4, group="move_along_riders"))
        b = self.track(Circle(center=(40, 10), radius=4, group="move_along_riders"))
        handles = group["move_along_riders"].move_along(
            Track.eight(width=30, height=12), time=0.3,
        )
        self.assertEqual(len(handles), 2)
        _frame(0.3)
        self.assertTrue(all(h.done for h in handles))


class TestMoveAlongPresetStrings(TrackTestCase):
    """String targets are 1:1 aliases for zero-arg Track presets; loops=1 default."""

    _PRESETS = ("circle", "eight", "star", "wave", "spiral", "arc", "line", "shuttle")

    def test_each_preset_one_lap(self):
        for name in self._PRESETS:
            with self.subTest(name=name):
                reset_process_scheduler()
                rider = self.track(Circle(center=(200, 300), radius=4))
                h = rider.move_along(name, time=0.2)
                self.assertEqual(h.kind, "tween")
                _frame(0.25)
                self.assertTrue(h.done, f"{name!r} should finish one lap")

    def test_eight_string_matches_Track_eight(self):
        a = self.track(Circle(center=(100, 100), radius=4))
        b = self.track(Circle(center=(100, 100), radius=4))
        ha = a.move_along("eight", time=0.3)
        hb = b.move_along(Track.eight(), time=0.3)
        _frame(0.15)
        self.assertTrue(_xy_close(
            (a.center.x, a.center.y), (b.center.x, b.center.y), places=1,
        ))
        _frame(0.2)
        self.assertTrue(ha.done and hb.done)
        self.assertTrue(_xy_close(
            (a.center.x, a.center.y), (b.center.x, b.center.y), places=1,
        ))

    def test_unknown_preset_raises(self):
        rider = self.track(Circle(center=(0, 0), radius=4))
        with self.assertRaises(TypeError) as cm:
            rider.move_along("orbit", time=0.2)
        msg = str(cm.exception)
        self.assertIn("eight", msg)
        self.assertIn("orbit", msg)
        self.assertIn("line", msg)
        self.assertIn("shuttle", msg)

    def test_zigzag_string_raises(self):
        rider = self.track(Circle(center=(0, 0), radius=4))
        with self.assertRaises(TypeError) as cm:
            rider.move_along("zigzag", time=0.2)
        msg = str(cm.exception)
        self.assertIn("eight", msg)
        self.assertIn("zigzag", msg)

    def test_shuttle_string_matches_Track_shuttle(self):
        a = self.track(Circle(center=(100, 100), radius=4))
        b = self.track(Circle(center=(100, 100), radius=4))
        ha = a.move_along("shuttle", time=0.3)
        hb = b.move_along(Track.shuttle(), time=0.3)
        _frame(0.15)
        self.assertTrue(_xy_close(
            (a.center.x, a.center.y), (b.center.x, b.center.y), places=1,
        ))
        _frame(0.2)
        self.assertTrue(ha.done and hb.done)
        self.assertTrue(_xy_close(
            (a.center.x, a.center.y), (b.center.x, b.center.y), places=1,
        ))

    def test_line_string_matches_Track_line(self):
        a = self.track(Circle(center=(100, 100), radius=4))
        b = self.track(Circle(center=(100, 100), radius=4))
        ha = a.move_along("line", time=0.3)
        hb = b.move_along(Track.line(), time=0.3)
        _frame(0.15)
        self.assertTrue(_xy_close(
            (a.center.x, a.center.y), (b.center.x, b.center.y), places=1,
        ))
        _frame(0.2)
        self.assertTrue(ha.done and hb.done)
        self.assertTrue(_xy_close(
            (a.center.x, a.center.y), (b.center.x, b.center.y), places=1,
        ))

    def test_explicit_forever_keeps_running(self):
        rider = self.track(Circle(center=(50, 50), radius=4))
        h = rider.move_along("eight", time=0.2, loops="forever")
        _frame(0.25)
        self.assertFalse(h.done)
        self.assertFalse(h.cancelled)
        self.assertGreaterEqual(int(h.lap), 1)
        h.cancel()

    def test_wave_one_lap_no_snap(self):
        # Open preset + loops=1: one pass, lands at the wave end (not start).
        rider = self.track(Circle(center=(400, 300), radius=4))
        x0, y0 = float(rider.center.x), float(rider.center.y)
        h = rider.move_along("wave", time=0.2)
        _frame(0.25)
        self.assertTrue(h.done)
        # Floating wave is centered on the rider at u0; end is displaced in x.
        self.assertNotAlmostEqual(float(rider.center.x), x0, places=0)
        # Should not have snapped back to the start of the open path.
        self.assertFalse(_xy_close((rider.center.x, rider.center.y), (x0, y0), places=0))

    def test_link_mid_move_along_raises_immediately(self):
        from scena.state import LinkedAttributeError, Attribute
        from scena.shapes import Point
        rider = self.track(Circle(center=(50, 50), radius=4))
        h = rider.move_along("eight", time=2.0)
        src = Point(1, 2)
        with self.assertRaises(LinkedAttributeError) as ctx:
            rider.center @= src
        self.assertIn("move_along", str(ctx.exception))
        h.cancel()
        rider.center @= src
        self.assertAlmostEqual(float(rider.center.x), 1.0, places=4)


class TestMoveAlongCollision(unittest.TestCase):
    _origin = 0

    def setUp(self):
        reset_collision_system()
        reset_process_scheduler()
        clock.scale = 1.0
        clock.paused = False
        clock._dt = 0.0
        clock._time = 0.0
        self._owned = []
        TestMoveAlongCollision._origin += 5000
        self.origin = TestMoveAlongCollision._origin

    def tearDown(self):
        for s in self._owned:
            try:
                s.destroy()
            except Exception:
                pass
        self._owned.clear()
        reset_collision_system()
        reset_process_scheduler()

    def track(self, shape):
        self._owned.append(shape)
        return shape

    def at(self, x, y):
        return (self.origin + x, self.origin + y)

    def step(self):
        get_collision_system().step()

    def test_move_along_stops_at_wall(self):
        ox, oy = self.at(0, 0)
        wall = self.track(Rect(
            center=(ox + 200, oy), width=20, height=120, group="walls",
        ))
        wall.mass = STATIC
        hero = self.track(Rect(
            center=(ox, oy), width=20, height=20, group="hero",
        ))
        hero.mass = 1.0
        resolve("hero", "walls")
        self.step()
        hero.move_along(Track(points=[(ox, oy), (ox + 400, oy)], smooth=0), time=1.0)
        dt = 1.0 / 60.0
        for _ in range(70):
            clock.advance(dt)
            tick_processes()
            self.step()
        self.assertLess(float(hero.center.x), ox + 200.0)
        self.assertGreater(float(hero.center.x), ox + 150.0)

    def test_cursor_at_is_placement_not_swept(self):
        ox, oy = self.at(0, 0)
        wall = self.track(Rect(
            center=(ox + 80, oy), width=20, height=80, group="walls",
        ))
        wall.mass = STATIC
        hero = self.track(Rect(
            center=(ox, oy), width=16, height=16, group="hero",
        ))
        hero.mass = 1.0
        resolve("hero", "walls")
        self.step()
        track = self.track(Track(points=[(ox, oy), (ox + 200, oy)], smooth=0))
        with self.assertRaises(LinkedAttributeError):
            hero.center @= track.cursor
        # Instant placement (not a formula driver) still jumps past the wall.
        cx, cy = track.at(1.0)
        hero.center = (cx, cy)
        self.step()
        self.assertGreater(float(hero.center.x), ox + 150.0)


# ---------------------------------------------------------------------------
# Stage 3 — presets, Track(shape), clone
# ---------------------------------------------------------------------------

class TestPresetsAndClone(TrackTestCase):
    def test_circle_u0_ccw(self):
        p = self.track(Track.circle(center=(0, 0), radius=50))
        self.assertTrue(_xy_close(p.at(0.0), (50, 0), places=0))
        self.assertTrue(_xy_close(p.at(0.25), (0, 50), places=0))

    def test_line_u0(self):
        p = self.track(Track(points=[(10, 20), (110, 20)], smooth=0))
        self.assertTrue(_xy_close(p.at(0.0), (10, 20), places=1))
        self.assertTrue(_xy_close(p.at(1.0), (110, 20), places=1))

    def test_arc_u0(self):
        p = self.track(Track.arc(center=(0, 0), radius=40, from_angle=0, to_angle=90))
        self.assertTrue(_xy_close(p.at(0.0), (40, 0), places=0))
        self.assertTrue(_xy_close(p.at(1.0), (0, 40), places=0))

    def test_star_u0_on_plus_x(self):
        p = self.track(Track.star(points=5, radius=40, center=(0, 0)))
        x, y = p.at(0.0)
        self.assertGreater(x, 20)
        self.assertAlmostEqual(y, 0.0, places=0)

    def test_clone_unlinks_live_shape(self):
        hexagon = self.track(RegularPolygon(n=6, center=(10, 20), radius=30))
        live = self.track(Track(hexagon))
        frozen = live.clone()
        self.track(frozen)
        self.assertTrue(_xy_close(live.at(0), frozen.at(0), places=1))
        hexagon.move_to(100, 100)
        self.assertTrue(_xy_close(live.at(0), (130, 100), places=0))
        self.assertTrue(_xy_close(frozen.at(0), (40, 20), places=0))

    def test_clone_of_reversed_is_frozen_reversed(self):
        p = self.track(Track.circle(center=(0, 0), radius=20))
        rev = p.reversed()
        frozen = rev.clone()
        self.track(frozen)
        self.assertTrue(_xy_close(frozen.at(0.0), rev.at(0.0), places=1))
        self.assertTrue(_xy_close(frozen.at(0.25), rev.at(0.25), places=1))
        self.assertIsNone(frozen._alias_of)


# ---------------------------------------------------------------------------
# Track.line — floating segment (length=, angle=, optional center=)
# ---------------------------------------------------------------------------

class TestTrackLinePreset(TrackTestCase):
    def test_default_is_floating_open_smooth0(self):
        p = self.track(Track.line())
        self.assertTrue(p.is_floating)
        self.assertFalse(p.closed)
        self.assertEqual(float(p.smooth), 0.0)
        p._ensure_samples()
        self.assertGreater(float(p.length), 0.0)

    def test_length_equals_chord(self):
        p = self.track(Track.line(length=200))
        p._ensure_samples()
        self.assertAlmostEqual(float(p.length), 200.0, places=4)

    def test_move_along_plus_x(self):
        bug = self.track(Circle(center=(100, 200), radius=4))
        h = bug.move_along(Track.line(length=180), time=0.4)
        _frame(0.4)
        self.assertTrue(h.done)
        self.assertAlmostEqual(float(bug.center.x), 280.0, places=1)
        self.assertAlmostEqual(float(bug.center.y), 200.0, places=1)

    def test_move_along_angle_90_plus_y(self):
        bug = self.track(Circle(center=(50, 50), radius=4))
        h = bug.move_along(Track.line(length=120, angle=90), time=0.3)
        _frame(0.3)
        self.assertTrue(h.done)
        self.assertAlmostEqual(float(bug.center.x), 50.0, places=1)
        self.assertAlmostEqual(float(bug.center.y), 170.0, places=1)

    def test_reversed_goes_other_way(self):
        bug = self.track(Circle(center=(200, 100), radius=4))
        h = bug.move_along(Track.line(length=150).reversed(), time=0.3)
        _frame(0.3)
        self.assertTrue(h.done)
        self.assertAlmostEqual(float(bug.center.x), 50.0, places=1)
        self.assertAlmostEqual(float(bug.center.y), 100.0, places=1)

    def test_p1_plants_and_anchors(self):
        p = self.track(Track.line(length=100, angle=0, p1=(400, 300)))
        self.assertFalse(p.is_floating)
        self.assertTrue(_xy_close(p.at(0.0), (400, 300), places=1))
        self.assertTrue(_xy_close(p.at(1.0), (500, 300), places=1))

    def test_p1_p2_is_anchored_segment(self):
        p = self.track(Track.line(p1=(0, 0), p2=(100, 0)))
        self.assertFalse(p.is_floating)
        self.assertTrue(_xy_close(p.at(0.0), (0.0, 0.0), places=4))
        self.assertTrue(_xy_close(p.at(1.0), (100.0, 0.0), places=4))
        self.assertTrue(_xy_close(
            (float(p.center.x), float(p.center.y)), (50.0, 0.0), places=4,
        ))
        with self.assertRaises(DerivedAttributeError):
            p.center = (10, 20)

    def test_p1_p2_floating_override_roots_at_rider(self):
        p = self.track(Track.line(p1=(0, 0), p2=(200, 0), floating=True))
        self.assertTrue(p.is_floating)
        bug = self.track(Circle(center=(10, 20), radius=4))
        h = bug.move_along(p, time=0.4)
        _frame(0.4)
        self.assertTrue(h.done)
        self.assertAlmostEqual(float(bug.center.x), 210.0, places=1)
        self.assertAlmostEqual(float(bug.center.y), 20.0, places=1)

    def test_positional_points_raise(self):
        with self.assertRaises(TypeError) as cm:
            Track.line((0, 0), (100, 0))
        self.assertIn("p1=", str(cm.exception))

    def test_negative_length_raises(self):
        with self.assertRaises(ValueError):
            Track.line(length=-10)

    def test_vec_matches_length_angle(self):
        by_vec = self.track(Track.line(vec=Vec2(200, 0)))
        by_len = self.track(Track.line(length=200, angle=0))
        self.assertTrue(by_vec.is_floating)
        self.assertFalse(by_vec.closed)
        self.assertAlmostEqual(float(by_vec.length), 200.0, places=4)
        self.assertTrue(_xy_close(by_vec.local_at(0.0), by_len.local_at(0.0), places=4))
        self.assertTrue(_xy_close(by_vec.local_at(1.0), by_len.local_at(1.0), places=4))

    def test_vec_tuple_and_negative_y(self):
        p = self.track(Track.line(vec=(120, -40), p1=(400, 300)))
        self.assertFalse(p.is_floating)
        length = (120.0 ** 2 + 40.0 ** 2) ** 0.5
        self.assertAlmostEqual(float(p.length), length, places=4)
        self.assertTrue(_xy_close(p.at(0.0), (400.0, 300.0), places=1))
        self.assertTrue(_xy_close(p.at(1.0), (520.0, 260.0), places=1))

    def test_vec_and_length_raise(self):
        with self.assertRaises(TypeError) as cm:
            Track.line(vec=Vec2(100, 0), length=100)
        self.assertIn("vec=", str(cm.exception))
        self.assertIn("length=", str(cm.exception))

    def test_vec_and_angle_raise(self):
        with self.assertRaises(TypeError) as cm:
            Track.line(vec=Vec2(100, 0), angle=90)
        self.assertIn("vec=", str(cm.exception))


# ---------------------------------------------------------------------------
# Track(vectors=) — turtle deltas, sibling of points=
# ---------------------------------------------------------------------------

class TestTrackVectors(TrackTestCase):
    def test_floating_open_polyline(self):
        p = self.track(Track(
            vectors=[Vec2(50, 0), (0, 80), (-40, 20)],
            smooth=0,
        ))
        self.assertTrue(p.is_floating)
        self.assertFalse(p.closed)
        p._ensure_samples()
        x0, y0 = p.at(0.0)
        x1, y1 = p.at(1.0)
        self.assertAlmostEqual(x1 - x0, 10.0, places=4)
        self.assertAlmostEqual(y1 - y0, 100.0, places=4)

    def test_matches_points_local_geometry(self):
        vecs = [Vec2(50, 0), (0, 80), (-40, 20)]
        abs_pts = [(0.0, 0.0), (50.0, 0.0), (50.0, 80.0), (10.0, 100.0)]
        from_vec = self.track(Track(vectors=vecs, smooth=0, start=(0, 0)))
        from_pts = self.track(Track(points=abs_pts, smooth=0))
        self.assertEqual(from_vec._ctrl_local, from_pts._ctrl_local)
        self.assertFalse(from_vec.is_floating)
        self.assertFalse(from_pts.is_floating)
        self.assertTrue(_xy_close(from_vec.at(0.0), from_pts.at(0.0), places=4))
        self.assertTrue(_xy_close(from_vec.at(1.0), from_pts.at(1.0), places=4))

    def test_start_plants_and_anchors(self):
        p = self.track(Track(
            vectors=[(100, 0)],
            smooth=0,
            start=(400, 300),
        ))
        self.assertFalse(p.is_floating)
        self.assertTrue(_xy_close(p.at(0.0), (400, 300), places=1))
        self.assertTrue(_xy_close(p.at(1.0), (500, 300), places=1))

    def test_move_along_floating_walks_from_rider(self):
        bug = self.track(Circle(center=(100, 200), radius=4))
        h = bug.move_along(
            Track(vectors=[(80, 0), (0, 40)], smooth=0),
            time=0.4,
        )
        _frame(0.4)
        self.assertTrue(h.done)
        self.assertAlmostEqual(float(bug.center.x), 180.0, places=1)
        self.assertAlmostEqual(float(bug.center.y), 240.0, places=1)

    def test_vec2_in_points_is_absolute(self):
        p = self.track(Track(points=[Vec2(10, 20), Vec2(110, 20)], smooth=0))
        self.assertFalse(p.is_floating)
        self.assertTrue(_xy_close(p.at(0.0), (10.0, 20.0), places=4))
        self.assertTrue(_xy_close(p.at(1.0), (110.0, 20.0), places=4))

    def test_points_and_vectors_raise(self):
        with self.assertRaises(TypeError) as cm:
            Track(points=[(0, 0), (10, 0)], vectors=[(10, 0)])
        self.assertIn("points=", str(cm.exception))
        self.assertIn("vectors=", str(cm.exception))

    def test_points_and_radius_raise(self):
        with self.assertRaises(TypeError) as cm:
            Track(points=[(0, 0), (10, 0)], radius=50)
        self.assertIn("points=", str(cm.exception))
        self.assertIn("radius=", str(cm.exception))

    def test_vectors_and_radius_raise(self):
        with self.assertRaises(TypeError) as cm:
            Track(vectors=[(10, 0)], radius=50)
        self.assertIn("vectors=", str(cm.exception))
        self.assertIn("radius=", str(cm.exception))

    def test_empty_vectors_raise(self):
        with self.assertRaises(ValueError):
            Track(vectors=[])

    def test_move_along_tuple_raises(self):
        rider = self.track(Circle(center=(0, 0), radius=4))
        with self.assertRaises(TypeError) as cm:
            rider.move_along((80, 40), time=0.1)
        self.assertIn("move_to", str(cm.exception))

    def test_move_along_point_raises(self):
        rider = self.track(Circle(center=(0, 0), radius=4))
        dest = self.track(Point(80, 40))
        with self.assertRaises(TypeError) as cm:
            rider.move_along(dest, time=0.1)
        self.assertIn("move_to", str(cm.exception))


# ---------------------------------------------------------------------------
# Stage 4 — face=
# ---------------------------------------------------------------------------

class TestFace(TrackTestCase):
    def test_face_follows_tangent(self):
        c = self.track(Circle(center=(50, 0), radius=6))
        c.move_along(Track.circle(center=(0, 0), radius=50), time=1.0, face=True)
        self.assertTrue(_ang_close(c.angle, 90.0))
        _frame(0.25)
        self.assertTrue(_ang_close(c.angle, 180.0))

    def test_face_does_not_fight_rotate_by(self):
        c = self.track(Circle(center=(50, 0), radius=6))
        h = c.move_along(Track.circle(center=(0, 0), radius=50), time=2.0, face=True)
        _frame(0.05)
        c.rotate_by(30, time=0.4)
        self.assertTrue(h.cancelled)

    def test_face_uses_world_heading(self):
        s = self.track(Sprite(center=(50, 0), size=24, art_angle=90))
        s.move_along(Track.circle(center=(0, 0), radius=50), time=1.0, face=True)
        # World heading = tangent (90° at u=0), not tangent − art_angle.
        self.assertTrue(_ang_close(s.angle, 90.0))

    def test_face_on_reversed_uses_host_rotation(self):
        """A reversed() view has no pose of its own: ``view.angle`` is the host's
        (its own ``_rotation`` slot stays at identity). face= must use the host."""
        plain = self.track(Track.circle(center=(0, 0), radius=50))
        spun = self.track(Track.circle(center=(0, 0), radius=50))
        spun.angle = 90
        view = spun.reversed()
        self.assertEqual(float(view._rotation), 0.0)
        self.assertEqual(float(view.angle), 90.0)
        a = self.track(Circle(center=(50, 0), radius=4))
        b = self.track(Circle(center=(0, 50), radius=4))
        a.move_along(plain.reversed(), time=1.0, face=True)
        b.move_along(view, time=1.0, face=True)
        self.assertTrue(_ang_close(float(b.angle), (float(a.angle) + 90.0) % 360.0, tol=5))

    def test_reversed_rotated_freeze_does_not_jump(self):
        path = self.track(Track.circle(center=(0, 0), radius=50))
        path.angle = 90
        rider = self.track(Circle(radius=4))
        rider.collidable = False
        rider.move_along(path.reversed(), time=1.0)
        _frame(0.2)
        x, y = float(rider.center.x), float(rider.center.y)
        path.destroy()
        _frame(0.05)
        dx = float(rider.center.x) - x
        dy = float(rider.center.y) - y
        self.assertLess((dx * dx + dy * dy) ** 0.5, 25.0)

    def test_ride_pulls_pose_once_per_rider(self):
        path = self.track(Track.circle(center=(0, 0), radius=40))
        riders = []
        for i in range(4):
            rider = self.track(Circle(radius=3))
            rider.collidable = False
            rider.move_along(path, time=2.0, phase=i / 4.0)
            riders.append(rider)
        calls = {"n": 0}
        orig = path._pose_xy

        def _counted():
            calls["n"] += 1
            return orig()

        path._pose_xy = _counted
        _frame(0.05)
        self.assertEqual(calls["n"], len(riders))


# ---------------------------------------------------------------------------
# Stage 5 — modifiers
# ---------------------------------------------------------------------------

class TestModifiers(TrackTestCase):
    def test_zigzag_in_place_and_lengthens(self):
        base = self.track(Track(points=[(0, 0), (100, 0)], smooth=0))
        base._ensure_samples()
        before = float(base.length)
        self.assertIs(base.zigzag(amount=20, waves=6), base)
        after = float(base.length)
        self.assertGreater(after, before)

    def test_orbit_keeps_linked_center(self):
        earth = self.track(Circle(center=(0, 0), radius=8))
        track = self.track(Track.circle(center=(0, 0), radius=40))
        track.center @= earth.center
        self.assertIs(track.orbit(radius=8, laps=4), track)
        track.at(0.0)
        n = track._rebuilds
        earth.move_to(50, 0)
        self.assertEqual(track._rebuilds, n)
        x, _ = track.at(0.0)
        self.assertGreater(x, 70.0)

    def test_wander_in_place_and_lengthens(self):
        base = self.track(Track(points=[(0, 0), (100, 0)], smooth=0))
        before = float(base.length)
        self.assertIs(base.wander(amount=12, seed=7), base)
        self.assertGreater(float(base.length), before)

    def test_constant_speed_after_zigzag(self):
        p = self.track(Track(points=[(0, 0), (200, 0)], smooth=0).zigzag(amount=15, waves=4))
        rider = self.track(Circle(center=(0, 0), radius=3))
        rider.move_along(p, time=1.0)
        _frame(0.5)
        mid = p.at(0.5)
        self.assertAlmostEqual(float(rider.center.x), mid[0], places=0)
        self.assertAlmostEqual(float(rider.center.y), mid[1], places=0)


# ---------------------------------------------------------------------------
# Stage 6 — loops forever
# ---------------------------------------------------------------------------

class TestLoops(TrackTestCase):
    def test_forever_survives_laps_and_cancels(self):
        c = self.track(Circle(center=(50, 0), radius=4))
        h = c.move_along(
            Track.circle(center=(0, 0), radius=50), time=0.2, loops="forever",
        )
        for _ in range(8):
            _frame(0.2)
            self.assertTrue(_xy_close(
                (c.center.x, c.center.y), (50.0, 0.0), places=0,
            ))
        self.assertFalse(h.done)
        self.assertGreaterEqual(h._lap, 7)
        h.cancel()
        self.assertTrue(h.cancelled)
        self.assertTrue(h.done)

    def test_destroy_tears_down_forever(self):
        c = self.track(Circle(center=(50, 0), radius=4))
        h = c.move_along(
            Track.circle(center=(0, 0), radius=50), time=0.5, loops="forever",
        )
        c.destroy()
        _frame(0.05)
        self.assertTrue(h.cancelled)

    def test_yoyo_retraces_open_path(self):
        c = self.track(Circle(center=(0, 0), radius=4))
        rail = Track(points=[(0, 0), (100, 0)], smooth=0, closed=False)
        h = c.move_along(rail, time=0.2, loops=2, yoyo=True)
        _frame(0.2)
        self.assertTrue(_xy_close((c.center.x, c.center.y), (100.0, 0.0), places=0))
        self.assertEqual(h._lap, 1)
        _frame(0.2)
        self.assertTrue(h.done)
        self.assertTrue(_xy_close((c.center.x, c.center.y), (0.0, 0.0), places=0))

    def test_yoyo_face_reverses_heading(self):
        c = self.track(Circle(center=(0, 0), radius=4))
        rail = Track(points=[(0, 0), (100, 0)], smooth=0, closed=False)
        h = c.move_along(rail, time=0.2, loops="forever", yoyo=True, face=True)
        _frame(0.1)
        self.assertTrue(_ang_close(c.angle, 0.0, tol=5.0))
        _frame(0.1)  # finish forward lap
        self.assertEqual(h._lap, 1)
        _frame(0.05)  # into reverse lap
        self.assertTrue(_ang_close(c.angle, 180.0, tol=5.0))
        h.cancel()

    def test_yoyo_requires_loops_gt_one(self):
        c = self.track(Circle(center=(0, 0), radius=4))
        with self.assertRaises(ValueError):
            c.move_along(
                Track(points=[(0, 0), (40, 0)], smooth=0, closed=False),
                time=0.2, yoyo=True,
            )


# ---------------------------------------------------------------------------
# Stage 7 — overlay
# ---------------------------------------------------------------------------

class TestOverlay(TrackTestCase):
    def test_overlay_off_by_default(self):
        self.assertFalse(tracks_overlay_wanted())

    def test_show_tracks_does_not_flip_visible(self):
        p = self.track(Track())
        self.assertFalse(p.visible)
        show_tracks(True)
        self.assertTrue(tracks_overlay_wanted())
        self.assertFalse(p.visible)
        show_tracks(False)
        self.assertFalse(tracks_overlay_wanted())


# ---------------------------------------------------------------------------
# Reclaim — movement Tracks stay off the draw list
# ---------------------------------------------------------------------------

def _count_layer_paths():
    from scena.canvas import ScenaCanvas
    registry = ScenaCanvas.get_current().registry
    n = 0
    for layer in registry.layers.values():
        for obj in list(getattr(layer, "_objects", ())):
            if isinstance(obj, Track):
                n += 1
    return n


class TestTrackReclaim(TrackTestCase):
    def test_oneshot_move_along_paths_do_not_accumulate(self):
        before = _count_layer_paths()
        rider = self.track(Circle(center=(0, 0), radius=4))
        for i in range(20):
            h = rider.move_along(
                Track(points=[(0, 0), (10 + i, 20), (40, 0)]),
                time=0.05,
            )
            _frame(0.06)
            self.assertTrue(h.done)
        self.assertEqual(_count_layer_paths(), before)

    def test_floating_eight_hover_not_on_layer(self):
        before = _count_layer_paths()
        wasp = self.track(Circle(center=(100, 200), radius=5))
        h = wasp.move_along(Track.eight(width=40, height=12), time=0.5, loops="forever")
        self.assertEqual(_count_layer_paths(), before)
        h.cancel()
        self.assertEqual(_count_layer_paths(), before)

    def test_live_outline_wrapper_not_on_layer(self):
        before = _count_layer_paths()
        hexagon = self.track(RegularPolygon(n=6, center=(0, 0), radius=40))
        rider = self.track(Circle(center=(40, 0), radius=4))
        h = rider.move_along(hexagon, time=0.2)
        mid = _count_layer_paths()
        self.assertEqual(mid, before)  # wrapper Track never registered
        _frame(0.25)
        self.assertTrue(h.done)
        self.assertEqual(_count_layer_paths(), before)

    def test_styled_path_stays_on_layer_after_ride(self):
        before = _count_layer_paths()
        rail = self.track(Track(points=[(0, 0), (100, 0)], smooth=0, color="gold"))
        self.assertEqual(_count_layer_paths(), before + 1)
        rider = self.track(Circle(center=(0, 0), radius=3))
        h = rider.move_along(rail, time=0.1)
        _frame(0.15)
        self.assertTrue(h.done)
        self.assertEqual(_count_layer_paths(), before + 1)
        self.assertIsNotNone(rail.layer)


# ---------------------------------------------------------------------------
# Stage 8 — cursor / u
# ---------------------------------------------------------------------------

class TestCursor(TrackTestCase):
    def test_cursor_stays_cold_until_read(self):
        p = self.track(Track.circle(center=(0, 0), radius=40))
        p.at(0.0)
        self.assertNotIn("cursor", p.__dict__)
        cur = p.cursor
        self.assertIn("cursor", p.__dict__)
        self.assertEqual(cur.field_type, FieldType.Derivate)
        self.assertAlmostEqual(float(cur.x), 40.0, places=1)

    def test_u_write_moves_cursor_and_linked_center(self):
        track = self.track(Track.circle(center=(0, 0), radius=40))
        ship = self.track(Circle(center=(0, 0), radius=4))
        ship.center @= track.cursor
        track.u = 0.25
        flush()
        self.assertAlmostEqual(float(track.cursor.x), 0.0, places=0)
        self.assertAlmostEqual(float(track.cursor.y), 40.0, places=0)
        self.assertAlmostEqual(float(ship.center.x), 0.0, places=0)
        self.assertAlmostEqual(float(ship.center.y), 40.0, places=0)


# ---------------------------------------------------------------------------
# Draw window (begin / end) — presentation only
# ---------------------------------------------------------------------------

class _RecCanvas:
    def __init__(self):
        self.n_fill = 0
        self.n_stroke = 0
        self.n_path = 0

    def save(self):
        return None

    def restore(self):
        return None

    def translate(self, *args):
        return None

    def rotate(self, *args):
        return None

    def scale(self, *args):
        return None

    def drawPath(self, path, paint):
        self.n_path += 1
        style = paint.getStyle()
        import skia
        if style == skia.Paint.kFill_Style:
            self.n_fill += 1
        else:
            self.n_stroke += 1


class TestDrawWindow(TrackTestCase):
    def test_defaults_full(self):
        p = self.track(Track.circle(center=(0, 0), radius=20, color="white"))
        self.assertAlmostEqual(float(p.begin), 0.0)
        self.assertAlmostEqual(float(p.end), 1.0)

    def test_ctor_and_clamp(self):
        p = self.track(Track(points=[(0, 0), (100, 0)], smooth=0, color="gold", begin=-0.5, end=2.0))
        self.assertAlmostEqual(float(p.begin), 0.0)
        self.assertAlmostEqual(float(p.end), 1.0)
        p.begin = -3
        p.end = 4
        self.assertAlmostEqual(float(p.begin), 0.0)
        self.assertAlmostEqual(float(p.end), 1.0)

    def test_does_not_rebuild_or_change_length_at_move_along(self):
        p = self.track(Track.circle(center=(0, 0), radius=40, color="white"))
        p.at(0.0)
        n = p._rebuilds
        length = float(p.length)
        at_mid = p.at(0.5)
        p.begin = 0.2
        p.end = 0.4
        self.assertEqual(p._rebuilds, n)
        self.assertAlmostEqual(float(p.length), length, places=6)
        self.assertTrue(_xy_close(p.at(0.5), at_mid, places=4))
        p.at(0.9)
        self.assertEqual(p._rebuilds, n)

        bug = self.track(Circle(center=(40, 0), radius=4))
        h = bug.move_along(p, time=0.4)
        _frame(0.4)
        self.assertTrue(h.done)
        self.assertAlmostEqual(float(bug.center.x), 40.0, places=0)
        self.assertAlmostEqual(float(bug.center.y), 0.0, places=0)

    def test_open_empty_when_begin_past_end(self):
        p = self.track(Track(points=[(0, 0), (80, 0)], smooth=0, color="gold"))
        p.begin = 0.8
        p.end = 0.2
        self.assertEqual(p._window_contours(), [])

    def test_closed_wraps_when_begin_past_end(self):
        p = self.track(Track.circle(center=(0, 0), radius=40, color="gold"))
        p.begin = 0.8
        p.end = 0.15
        contours = p._window_contours()
        self.assertEqual(len(contours), 2)
        self.assertTrue(_xy_close(contours[0][0], p.local_at(0.8), places=3))
        self.assertTrue(_xy_close(contours[1][-1], p.local_at(0.15), places=3))

    def test_half_window_starts_at_begin(self):
        p = self.track(Track(points=[(0, 0), (100, 0)], smooth=0, color="gold"))
        p.end = 0.4
        contours = p._window_contours()
        self.assertEqual(len(contours), 1)
        self.assertTrue(_xy_close(contours[0][0], p.local_at(0.0), places=4))
        self.assertTrue(_xy_close(contours[0][-1], p.local_at(0.4), places=4))

    def test_trimmed_skips_fill_keeps_stroke(self):
        p = self.track(Track.circle(center=(0, 0), radius=30, color="gold"))
        p.fill = "navy"
        rec = _RecCanvas()
        p._geometry_draw(rec)
        self.assertGreaterEqual(rec.n_fill, 1)
        self.assertGreaterEqual(rec.n_stroke, 1)
        p.end = 0.4
        rec2 = _RecCanvas()
        p._geometry_draw(rec2)
        self.assertEqual(rec2.n_fill, 0)
        self.assertGreaterEqual(rec2.n_stroke, 1)

    def test_full_window_uses_cached_path(self):
        p = self.track(Track.circle(center=(0, 0), radius=20, color="white"))
        rec = _RecCanvas()
        p._geometry_draw(rec)
        cached = p._geom_path
        rec2 = _RecCanvas()
        p._geometry_draw(rec2)
        self.assertIs(p._geom_path, cached)

    def test_hit_test_follows_window(self):
        p = self.track(Track.circle(center=(0, 0), radius=40, color="white", line_width=6))
        far = p.at(0.9)
        near = p.at(0.05)
        self.assertTrue(p._hit_test_xy(far[0], far[1]))
        self.assertTrue(p._hit_test_xy(near[0], near[1]))
        p.end = 0.1
        self.assertFalse(p._hit_test_xy(far[0], far[1]))
        self.assertTrue(p._hit_test_xy(near[0], near[1]))

    def test_tween_end(self):
        p = self.track(Track.circle(center=(0, 0), radius=20, color="gold"))
        p.end = 0.0
        tween(p["end"], 1.0, time=0.4)
        _frame(0.4)
        self.assertAlmostEqual(float(p.end), 1.0, places=3)

    def test_clone_copies_window(self):
        p = self.track(Track.circle(center=(0, 0), radius=20, color="gold"))
        p.begin = 0.2
        p.end = 0.6
        c = self.track(p.clone())
        self.assertAlmostEqual(float(c.begin), 0.2, places=4)
        self.assertAlmostEqual(float(c.end), 0.6, places=4)
        self.assertAlmostEqual(float(c.length), float(p.length), places=2)


# ---------------------------------------------------------------------------
# Floating vs anchored redesign
# ---------------------------------------------------------------------------

class TestFloatingInference(TrackTestCase):
    def test_sizes_only_floating(self):
        for p in (
            Track.eight(),
            Track.circle(radius=40),
            Track.star(radius=20),
            Track.spiral(radius=30),
            Track.shuttle(length=80),
            Track.line(length=100),
            Track.wave(),
            Track(),
        ):
            self.track(p)
            self.assertTrue(p.is_floating, getattr(p, "_spec", None) or type(p).__name__)

    def test_center_anchors_centered_presets(self):
        for p in (
            Track.eight(width=80, height=30, center=(400, 300)),
            Track.circle(radius=40, center=(10, 20)),
            Track.star(radius=20, center=(5, 5)),
            Track.spiral(radius=30, center=(0, 0)),
            Track.shuttle(length=80, center=(100, 100)),
            Track.arc(radius=20, center=(0, 0)),
        ):
            self.track(p)
            self.assertFalse(p.is_floating)

    def test_floating_true_with_center_stays_floating(self):
        p = self.track(Track.eight(width=80, height=30, center=(400, 300), floating=True))
        self.assertTrue(p.is_floating)
        self.assertTrue(_xy_close(
            (float(p.center.x), float(p.center.y)), (400, 300), places=4,
        ))

    def test_floating_false_without_center_is_anchored(self):
        p = self.track(Track.eight(width=80, height=30, floating=False))
        self.assertFalse(p.is_floating)

    def test_setter_flips_both_ways_move_to_does_not(self):
        p = self.track(Track.eight())
        self.assertTrue(p.is_floating)
        p.is_floating = False
        self.assertFalse(p.is_floating)
        p.is_floating = True
        self.assertTrue(p.is_floating)
        p.move_to(200, 100)
        self.assertTrue(p.is_floating)
        p.center = (10, 20)
        self.assertTrue(p.is_floating)

    def test_points_floating_true_detaches_pose(self):
        p = self.track(Track(
            points=[(0, 0), (100, 0)], smooth=0, floating=True,
        ))
        self.assertTrue(p.is_floating)
        bug = self.track(Circle(center=(50, 50), radius=3))
        h = bug.move_along(p, time=0.2)
        _frame(0.2)
        self.assertTrue(h.done)
        self.assertAlmostEqual(float(bug.center.x), 150.0, places=1)
        self.assertAlmostEqual(float(bug.center.y), 50.0, places=1)


class TestFloatingShapeWrap(TrackTestCase):
    def test_source_move_does_not_drag_template(self):
        hexagon = self.track(RegularPolygon(n=6, center=(10, 20), radius=30))
        template = self.track(Track(hexagon, floating=True))
        self.assertTrue(template.is_floating)
        x0, y0 = template.at(0.0)
        hexagon.move_to(100, 100)
        x1, y1 = template.at(0.0)
        self.assertAlmostEqual(x0, x1, places=1)
        self.assertAlmostEqual(y0, y1, places=1)

    def test_source_rotation_still_affects_ride(self):
        box = self.track(Rect(center=(0, 0), width=40, height=20))
        template = self.track(Track(box, floating=True))
        pt0 = template.at(0.0)
        box.angle = 90
        pt1 = template.at(0.0)
        self.assertFalse(_xy_close(pt0, pt1, places=1))

    def test_visible_and_move_to_work(self):
        src = self.track(Circle(center=(40, 50), radius=10))
        template = self.track(Track(src, floating=True, visible=True))
        self.assertTrue(template.visible)
        template.move_to(200, 100)
        self.assertTrue(_xy_close(
            (float(template.center.x), float(template.center.y)), (200, 100), places=1,
        ))


class TestLinkedPointsCenterDerivate(TrackTestCase):
    def test_center_write_raises(self):
        a = self.track(Circle(center=(0, 0), radius=4))
        p = self.track(Track(
            points=[
                lambda: (a.center.x, a.center.y),
                (50, 0),
                (100, 0),
            ],
            smooth=0,
        ))
        p.at(0.0)
        with self.assertRaises(DerivedAttributeError):
            p.center = (10, 20)


class TestWaveStart(TrackTestCase):
    def test_start_omitted_floating(self):
        p = self.track(Track.wave(length=200, amplitude=0, waves=1))
        self.assertTrue(p.is_floating)

    def test_start_plants_u0(self):
        p = self.track(Track.wave(length=200, amplitude=0, waves=1, start=(400, 300)))
        self.assertFalse(p.is_floating)
        self.assertTrue(_xy_close(p.at(0.0), (400, 300), places=1))
        self.assertTrue(_xy_close(p.at(1.0), (600, 300), places=1))

    def test_center_kwarg_raises(self):
        with self.assertRaises(TypeError) as cm:
            Track.wave(length=100, center=(0, 0))
        self.assertIn("start=", str(cm.exception))


class TestShuttle(TrackTestCase):
    def test_closed_u0_at_center_then_right_left(self):
        p = self.track(Track.shuttle(length=100, angle=0, center=(0, 0)))
        self.assertFalse(p.is_floating)
        self.assertTrue(p.closed)
        self.assertTrue(_xy_close(p.at(0.0), (0.0, 0.0), places=4))
        self.assertAlmostEqual(float(p.length), 200.0, places=4)
        # First quarter of arc length is the outbound +x half (50 units of 200).
        self.assertTrue(_xy_close(p.at(0.25), (50.0, 0.0), places=1))
        self.assertTrue(_xy_close(p.at(0.75), (-50.0, 0.0), places=1))

    def test_floating_ride_starts_on_rider_and_returns(self):
        bug = self.track(Circle(center=(200, 300), radius=4))
        x0, y0 = float(bug.center.x), float(bug.center.y)
        h = bug.move_along(Track.shuttle(length=80), time=0.4)
        _frame(0.4)
        self.assertTrue(h.done)
        self.assertAlmostEqual(float(bug.center.x), x0, places=1)
        self.assertAlmostEqual(float(bug.center.y), y0, places=1)

    def test_vec_and_length_raise(self):
        with self.assertRaises(TypeError) as cm:
            Track.shuttle(vec=Vec2(100, 0), length=100)
        self.assertIn("vec=", str(cm.exception))
        self.assertIn("length=", str(cm.exception))

    def test_vec_matches_length_angle(self):
        by_vec = self.track(Track.shuttle(vec=Vec2(80, 0), center=(0, 0)))
        by_len = self.track(Track.shuttle(length=80, angle=0, center=(0, 0)))
        self.assertAlmostEqual(float(by_vec.length), float(by_len.length), places=4)
        self.assertTrue(_xy_close(by_vec.at(0.25), by_len.at(0.25), places=4))


class TestRotationCtor(TrackTestCase):
    def test_wave_rotation_spins_world_not_local(self):
        raw = self.track(Track.wave(length=200, amplitude=0, waves=1, start=(0, 0)))
        spun = self.track(Track.wave(
            length=200, amplitude=0, waves=1, start=(0, 0), angle=90,
        ))
        self.assertTrue(_xy_close(raw.local_at(0.0), spun.local_at(0.0), places=4))
        self.assertTrue(_xy_close(raw.at(0.0), (0.0, 0.0), places=1))
        # Local (-100, 0) about center (100, 0), 90° CCW → (100, -100).
        self.assertTrue(_xy_close(spun.at(0.0), (100.0, -100.0), places=1))

    def test_eight_rotation_about_center(self):
        raw = self.track(Track.eight(width=80, height=40, center=(0, 0)))
        spun = self.track(Track.eight(width=80, height=40, center=(0, 0), angle=90))
        self.assertTrue(_xy_close(raw.local_at(0.25), spun.local_at(0.25), places=4))
        lx, ly = raw.local_at(0.25)
        self.assertTrue(_xy_close(spun.at(0.25), (-ly, lx), places=1))


class TestSpiralOrigin(TrackTestCase):
    def test_innermost_at_local_origin(self):
        p = self.track(Track.spiral(turns=2, radius=40, center=(10, 20)))
        self.assertTrue(_xy_close(p.local_at(0.0), (0.0, 0.0), places=4))
        self.assertTrue(_xy_close(p.at(0.0), (10.0, 20.0), places=4))


class TestMoveAlongAt(TrackTestCase):
    def test_floating_at_plants_u0_eight(self):
        mark = (300.0, 400.0)
        bug = self.track(Circle(center=(0, 0), radius=4))
        h = bug.move_along(
            Track.eight(width=80, height=40), time=0.4, at=mark,
        )
        self.assertTrue(_xy_close(
            (float(bug.center.x), float(bug.center.y)), mark, places=1,
        ))
        _frame(0.4)
        self.assertTrue(h.done)
        self.assertTrue(_xy_close(
            (float(bug.center.x), float(bug.center.y)), mark, places=1,
        ))

    def test_floating_at_plants_u0_circle(self):
        mark = (50.0, 60.0)
        bug = self.track(Circle(center=(0, 0), radius=4))
        bug.move_along(Track.circle(radius=30), time=0.2, at=mark)
        self.assertTrue(_xy_close(
            (float(bug.center.x), float(bug.center.y)), mark, places=1,
        ))

    def test_at_on_anchored_raises(self):
        bug = self.track(Circle(center=(0, 0), radius=4))
        with self.assertRaises(TypeError) as cm:
            bug.move_along(
                Track.circle(center=(0, 0), radius=40),
                time=0.2, at=(10, 10),
            )
        self.assertIn("floating", str(cm.exception))

    def test_at_on_raw_shape_raises(self):
        box = self.track(Rect(center=(0, 0), width=40, height=20))
        bug = self.track(Circle(center=(0, 0), radius=4))
        with self.assertRaises(TypeError) as cm:
            bug.move_along(box, time=0.2, at=(10, 10))
        self.assertIn("floating", str(cm.exception))


class TestLineCenterKwarg(TrackTestCase):
    def test_center_on_line_raises(self):
        with self.assertRaises(TypeError) as cm:
            Track.line(length=100, center=(0, 0))
        msg = str(cm.exception)
        self.assertIn("p1=", msg)
        self.assertIn("u=0", msg)
        self.assertIn("middle", msg)

    def test_vectors_center_raises(self):
        with self.assertRaises(TypeError) as cm:
            Track(vectors=[(10, 0)], center=(0, 0))
        self.assertIn("start=", str(cm.exception))


class TestConstructorStyle(TrackTestCase):
    def test_stroke_kwarg_names_color(self):
        with self.assertRaises(TypeError) as cm:
            Track(points=[(0, 0), (10, 0)], stroke="gold")
        self.assertIn("color=", str(cm.exception))

    def test_fill_kwarg_names_property(self):
        with self.assertRaises(TypeError) as cm:
            Track.circle(radius=20, fill="navy")
        self.assertIn(".fill", str(cm.exception))

    def test_line_width_shows_track_and_clears_fill(self):
        t = self.track(Track(points=[(0, 0), (10, 0)], line_width=4))
        self.assertTrue(t.visible)
        self.assertIsNotNone(t.layer)
        self.assertAlmostEqual(float(t.line_width), 4.0, places=4)
        self.assertIsNone(t.fill)

    def test_paint_setters_do_not_show_an_unstyled_track(self):
        filled = self.track(Track())
        filled.fill = "navy"
        self.assertIsNone(filled.layer)
        stroked = self.track(Track())
        stroked.line = "gold"
        self.assertIsNone(stroked.layer)
        thick = self.track(Track())
        thick.line_width = 5
        self.assertIsNone(thick.layer)

    def test_color_then_fill_is_the_two_channel_spelling(self):
        from scena.color import Color
        t = self.track(Track(points=[(0, 0), (10, 0)], color="gold"))
        t.fill = "navy"
        self.assertTrue(t.visible)
        # Track.line is the preset; the stroke channel is the paint property.
        self.assertEqual(Color(t._line).rgb[:3], Color("gold").rgb[:3])
        self.assertEqual(Color(t.fill).rgb[:3], Color("navy").rgb[:3])


class TestGeometryEdgeCases(TrackTestCase):
    def test_track_radius_assignment_rebakes(self):
        track = self.track(Track.circle(radius=50, center=(0, 0)))
        track.at(0)
        track.radius = 100
        self.assertAlmostEqual(track.at(0)[0], 100.0, places=3)

    def test_track_ellipse_outline(self):
        ell = self.track(Ellipse(center=(0, 0), width=80, height=40))
        track = self.track(Track(ell))
        p = track.at(0)
        self.assertAlmostEqual(p[0], 40.0, places=1)
        self.assertAlmostEqual(p[1], 0.0, places=1)

    def test_reversed_view_hits_after_rebake(self):
        track = self.track(Track.circle(radius=40, center=(5, 5)))
        rev = track.reversed()
        self.assertTrue(rev.contains_point(45, 5))
        self.assertTrue(track.contains_point(45, 5))

        poly = self.track(Track(points=[(0, 0), (100, 0), (100, 100)], smooth=0))
        poly.at(0)
        view = poly.reversed()
        self.assertTrue(view.contains_point(50, 0))
        poly.smooth = 1
        self.assertEqual(poly.contains_point(50, 0), view.contains_point(50, 0))

    def test_arc_radius_assignment_rebakes(self):
        arc = self.track(Track.arc(radius=40, from_angle=0, to_angle=90, center=(0, 0)))
        arc.at(0)
        arc.radius = 80
        self.assertAlmostEqual(arc.at(0)[0], 80.0, places=3)
        self.assertAlmostEqual(arc.at(0)[1], 0.0, places=3)

    def test_arc_sweep_is_signed(self):
        # 350° → 10° is a −340° sweep (midpoint on −x), not a +20° arc across 0.
        arc = self.track(Track.arc(radius=40, from_angle=350, to_angle=10, center=(0, 0)))
        mid = arc.at(0.5)
        self.assertAlmostEqual(mid[0], -40.0, places=3)
        self.assertAlmostEqual(mid[1], 0.0, places=3)

    def test_reversed_follows_host_window(self):
        host = self.track(Track(
            points=[(0, 0), (100, 0)], smooth=0, color="white", begin=0.2, end=0.6,
        ))
        rev = host.reversed()
        self.assertFalse(host.contains_point(90, 0))
        self.assertFalse(rev.contains_point(90, 0))
        self.assertTrue(host.contains_point(40, 0))
        self.assertTrue(rev.contains_point(40, 0))
        # The view does not own a second window.
        rev.begin = 0.0
        rev.end = 1.0
        self.assertFalse(rev.contains_point(90, 0))
        cloned = self.track(rev.clone())
        self.assertAlmostEqual(float(cloned.begin), 0.2, places=5)
        self.assertAlmostEqual(float(cloned.end), 0.6, places=5)
        self.assertFalse(cloned.contains_point(90, 0))

    def test_begin_end_non_finite_rejected(self):
        with self.assertRaises(ValueError):
            Track(points=[(0, 0), (10, 0)], smooth=0, begin=float("nan"))
        track = self.track(Track.line(length=10))
        with self.assertRaises(ValueError):
            track.begin = float("nan")
        with self.assertRaises(ValueError):
            track.end = float("inf")

    def test_non_finite_points_and_radius_rejected(self):
        with self.assertRaises(ValueError):
            Track(points=[(0, 0), (float("inf"), 0)], smooth=0)
        with self.assertRaises(ValueError):
            Track(points=[(0, 0), (float("nan"), 0)], smooth=0)
        with self.assertRaises(ValueError):
            Track.circle(radius=float("inf"), center=(0, 0))
        track = self.track(Track.circle(radius=10, center=(0, 0)))
        with self.assertRaises(ValueError):
            track.radius = float("nan")

    def test_reversed_stroke_uses_host_tables(self):
        from scena.collision import _track_stroke_contours
        track = self.track(Track.circle(radius=40, center=(5, 5)))
        rev = track.reversed()
        contours, closed, _half = _track_stroke_contours(rev)
        self.assertTrue(closed)
        self.assertGreaterEqual(len(contours), 1)
        self.assertGreaterEqual(len(contours[0]), 2)

    def test_small_corner_radius_is_in_the_outline(self):
        sharp = self.track(Rect(center=(0, 0), width=100, height=40, corner_radius=0))
        soft = self.track(Rect(center=(0, 0), width=100, height=40, corner_radius=0.49))
        self.assertEqual(len(shape_outline(sharp)[0]), 4)
        self.assertGreater(len(shape_outline(soft)[0]), 4)


class TestTrackPathCache(unittest.TestCase):
    def test_spin_does_not_rebuild_and_window_skips_full_path(self):
        import skia
        tr = Track(points=[(0, 0), (80, 10), (40, 40)], smooth=0)
        surf = skia.Surface(120, 120)
        tr._geometry_draw(surf.getCanvas())
        key = tr._geom_path_key
        path = tr._geom_path
        tr.rotate_by(20)
        tr.scale_by(1.2)
        tr._geometry_draw(surf.getCanvas())
        self.assertEqual(tr._geom_path_key, key)
        self.assertIs(tr._geom_path, path)
        tr.begin = 0.25
        tr.end = 0.75
        tr._geometry_draw(surf.getCanvas())
        self.assertNotEqual(tr._geom_path_key, key)
        self.assertNotIn(id(tr._pose_host()._xs), tr._geom_path_key)


class TestReversedViewTimedVerbs(unittest.TestCase):
    """A timed turn or scale on a reversed() view is the host's own timed
    verb: one tween key (a new turn replaces the old), owned by the host,
    gone with it (review 2026-10-09 S6-3)."""

    def test_view_turn_replaces_the_host_turn(self):
        from scena import Track
        from tests.system_support import system_world
        with system_world(draw=False) as w:
            t = Track.line(length=200)
            try:
                t.rotate_by(90, time=1)
                w.step(1, dt=1 / 60)
                t.reversed().rotate_by(-90, time=1)
                w.step(80, dt=1 / 60)
                h = Track.line(length=200)
                h.rotate_by(90, time=1)
                w.step(1, dt=1 / 60)
                h.rotate_by(-90, time=1)
                w.step(80, dt=1 / 60)
                self.assertAlmostEqual(t.angle, h.angle, places=6)
                h.destroy()
            finally:
                t.destroy()

    def test_view_tween_dies_with_the_host(self):
        from scena import Track
        from tests.system_support import system_world
        with system_world(draw=False) as w:
            t = Track.line(length=200)
            handle = t.reversed().scale_by(2, time=1)
            w.step(5, dt=1 / 60)
            t.destroy()
            w.step(5, dt=1 / 60)                 # raised DestroyedError before
            self.assertTrue(handle.cancelled or handle.done)


if __name__ == "__main__":
    unittest.main()


class TestTrackGeometryContract(TrackTestCase):
    """Track fixes found by the geometry contract sweep (Testing Design G11, G12)."""

    def test_clone_keeps_the_pose_and_draws_the_same_path(self):
        # The pose used to be baked into the copy's points (rotation 0, scale 1).
        import math
        makers = (lambda: Track.eight(width=60, height=30, center=(3, 4)),
                  lambda: Track.circle(radius=12, center=(1, 1)),
                  lambda: Track(points=[(0, 0), (40, 10), (20, 50)]),
                  lambda: Track.line(p1=(0, 0), p2=(30, 5)))
        for k, make in enumerate(makers):
            for reverse in (False, True):
                with self.subTest(track=k, reversed=reverse):
                    src = self.track(make())
                    src.flip_x = True
                    src.rotate_by(20)
                    src.scale_by(1.25)
                    view = src.reversed() if reverse else src
                    copy = self.track(view.clone())
                    for attr in ("angle", "scale", "flip_x", "flip_y"):
                        self.assertEqual(getattr(copy, attr), getattr(src, attr), attr)
                    self.assertTrue(_xy_close((copy.center.x, copy.center.y), (src.center.x, src.center.y), places=6))
                    gap = max(math.dist(view.at(u / 97), copy.at(u / 97)) for u in range(98))
                    self.assertLess(gap, 1e-9)
                    # Later verbs act on the copy as on the source (a view shares its host's pose).
                    for t in (src, copy):
                        t.rotate_by(-20)
                    gap = max(math.dist(view.at(u / 97), copy.at(u / 97)) for u in range(98))
                    self.assertLess(gap, 1e-9)

    def test_a_reversed_view_shares_the_host_pose(self):
        # G16: rotate_by / scale_by wrote view slots nothing drew; move_by moved
        # the host but view.center read the old spot; radius read 0; the outline
        # of a view was empty; the view's cursor raised, then went stale.
        import math
        host = self.track(Track.circle(radius=10, center=(3, 4)))
        view = host.reversed()
        self.assertIs(view.center, host.center)
        self.assertEqual(float(view.radius), 10.0)
        view.rotate_by(30)
        view.scale_by(2)
        view.move_by(5, -1)
        view.flip_y = True
        for attr in ("angle", "scale", "flip_x", "flip_y", "length", "radius"):
            self.assertEqual(getattr(view, attr), getattr(host, attr), attr)
        self.assertTrue(_xy_close((view.center.x, view.center.y), (8.0, 3.0), places=9))
        for k in range(11):
            u = k / 10
            self.assertLess(math.dist(view.at(u), host.at(1.0 - u if u else 0.0)), 1e-9)
        from scena.track import shape_outline
        pts, closed = shape_outline(view)
        self.assertTrue(pts and closed)

    def test_a_link_on_a_view_writes_the_host(self):
        from scena import State
        st = State()
        st.a = 40.0
        host = self.track(Track.eight(width=60, height=30, center=(0, 0)))
        view = host.reversed()
        view["angle"] @= lambda: st.a
        self.assertEqual(float(host.angle), 40.0)
        st.a = 70.0
        self.assertEqual(float(view.angle), 70.0)
        self.assertTrue(host["angle"].is_linked)

    def test_a_view_cursor_follows_the_host_pose(self):
        import math
        host = self.track(Track.circle(radius=10, center=(0, 0)))
        view = host.reversed()
        ship = self.track(Circle(center=(0, 0), radius=1))
        ship.center @= view.cursor
        view.u = 0.25
        host.move_by(7, 0)
        host.rotate_by(40)
        self.assertLess(math.dist((ship.center.x, ship.center.y), view.at(0.25)), 1e-9)

    def test_a_destroyed_view_is_not_handed_out_again(self):
        host = self.track(Track.circle(radius=10, center=(0, 0)))
        view = host.reversed()
        view.destroy()
        self.assertTrue(host.is_alive)
        again = host.reversed()
        self.assertIsNot(again, view)
        self.assertTrue(again.is_alive)
        self.assertIs(again.center, host.center)

    def test_line_cursor_link_and_center(self):
        # G11: reading cursor on Track.line(p1=, p2=) recursed forever; center read (0, 0).
        t = self.track(Track.line(p1=(0, 0), p2=(40, 10)))
        ship = self.track(Circle(center=(0, 0), radius=2))
        ship.center @= t.cursor
        t.u = 0.5
        self.assertTrue(_xy_close((ship.center.x, ship.center.y), (20.0, 5.0), places=6))
        self.assertTrue(_xy_close((t.center.x, t.center.y), (20.0, 5.0), places=6))
        t.move_by(7, -3)
        self.assertTrue(_xy_close((t.center.x, t.center.y), (27.0, 2.0), places=6))

    def test_line_turns_and_scales_about_a_pivot(self):
        t = self.track(Track.line(p1=(3, -2), p2=(40, 10)))
        a0, b0 = t.at(0.0), t.at(1.0)
        t.rotate_by(37, about=(50, -20))
        t.rotate_by(-37, about=(50, -20))
        self.assertTrue(_xy_close(t.at(0.0), a0, places=6) and _xy_close(t.at(1.0), b0, places=6))
        t.scale_by(2, about=(50, -20))
        self.assertTrue(_xy_close(t.at(0.0), (50 + 2 * (3 - 50), -20 + 2 * (-2 + 20)), places=6))

    def test_cursor_follows_rotate_and_scale(self):
        t = self.track(Track.circle(radius=10, center=(0, 0)))
        t.u = 0.0
        x0, y0 = float(t.cursor.x), float(t.cursor.y)
        t.rotate_by(90)
        self.assertTrue(_xy_close((t.cursor.x, t.cursor.y), (-y0, x0), places=6))
        t.scale_by(2)
        self.assertTrue(_xy_close((t.cursor.x, t.cursor.y), (-2 * y0, 2 * x0), places=6))

    def test_flip_mirrors_the_path_in_place(self):
        # G12: flips only toggled the flag.
        for axis in ("x", "y"):
            with self.subTest(axis=axis):
                t = self.track(Track.eight(center=(3, 4)))
                p = t.at(0.1)
                setattr(t, "flip_" + axis, True)
                want = (6 - p[0], p[1]) if axis == "x" else (p[0], 8 - p[1])
                self.assertTrue(_xy_close(t.at(0.1), want, places=6))
                setattr(t, "flip_" + axis, False)
                self.assertTrue(_xy_close(t.at(0.1), p, places=6))

    def test_cull_box_contains_a_turned_track_and_text(self):
        from scena import Text
        from scena.canvas import _approx_draw_aabb
        t = self.track(Track.eight(width=60, height=20, center=(0, 0)))
        t.rotate_by(70)
        x1, y1, x2, y2 = _approx_draw_aabb(t)
        for u in (i / 32 for i in range(32)):
            x, y = t.at(u)
            self.assertTrue(x1 <= x <= x2 and y1 <= y <= y2)
        label = self.track(Text("a long caption", center=(0, 0)))
        label.rotate_by(90)
        bx1, by1, bx2, by2 = _approx_draw_aabb(label)
        self.assertGreater(by2 - by1, bx2 - bx1)      # tall once turned


class TestCopyOfAFlippedTrack(unittest.TestCase):
    """GX10: ``track << flipped`` drew the unflipped points. The drawn table
    has the mirror baked in and the copy takes the flags too, so the takein
    must un-mirror first, as ``clone()`` does."""

    def test_the_copy_draws_what_the_source_draws(self):
        from scena import Track
        for flips in (("x",), ("y",), ("x", "y")):
            src = Track(points=[(0, 0), (30, 5), (12, 22), (-4, 9)])
            for axis in flips:
                setattr(src, f"flip_{axis}", True)
            dst = Track(points=[(1, 1), (2, 2)])
            dst << src
            for u in (0.0, 0.3, 0.7):
                a, b = src.at(u), dst.at(u)
                self.assertAlmostEqual(a[0], b[0], places=6, msg=f"{flips} {u}")
                self.assertAlmostEqual(a[1], b[1], places=6, msg=f"{flips} {u}")
            for t in (src, dst):
                t.destroy()
