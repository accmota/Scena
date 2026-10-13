"""History + Contrail unit tests.

Run::

    python -m unittest tests.test_history -v
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import (
    Circle, Color, Contrail, History, Laser, Point, Track, clock, every,
)
from scena.history import (
    _Stroke,
    registered_history_count,
    tick_all_histories,
)
from scena.process import reset_process_scheduler, tick_processes
from scena.state import DestroyedError
from tests.graph_support import full_collect, gc_paused  # noqa: E402


class HistoryTestCase(unittest.TestCase):
    def setUp(self):
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
                if hasattr(obj, "destroy"):
                    obj.destroy()
                elif getattr(obj, "is_alive", False):
                    obj.destroy()
            except Exception:
                pass
        self._owned.clear()

    def own(self, obj):
        self._owned.append(obj)
        return obj


class TestHistoryCore(HistoryTestCase):
    def test_add_order_and_indexing(self):
        h = History()
        h.add("a")
        h.add("b")
        h.add("c")
        self.assertEqual(list(h), ["a", "b", "c"])
        self.assertEqual(h[0], "a")
        self.assertEqual(h[-1], "c")
        self.assertEqual(h.first, "a")
        self.assertEqual(h.last, "c")
        self.assertEqual(h[1:3], ["b", "c"])
        self.assertEqual(len(h), 3)
        self.assertTrue(h)
        self.assertIs(h.add("d"), "d")

    def test_slice_is_list_copy(self):
        h = History()
        h.add(1)
        h.add(2)
        snap = h[:]
        h.add(3)
        self.assertEqual(snap, [1, 2])

    def test_max_points_evicts_oldest(self):
        left = []
        h = History(max_points=2, on_leave=lambda v: left.append(v))
        h.add(1)
        h.add(2)
        h.add(3)
        self.assertEqual(list(h), [2, 3])
        self.assertEqual(left, [1])

    def test_duration_evicts_on_tick(self):
        left = []
        h = History(duration=0.5, on_leave=lambda v: left.append(v))
        h.add("a")
        h.add("b")
        self.assertGreaterEqual(registered_history_count(), 1)
        clock.advance(0.6)
        tick_all_histories()
        self.assertEqual(list(h), [])
        self.assertEqual(left, ["a", "b"])

    def test_both_bounds(self):
        h = History(max_points=10, duration=1.0)
        for i in range(5):
            h.add(i)
        clock.advance(1.5)
        tick_all_histories()
        self.assertEqual(len(h), 0)

    def test_lowering_max_points_evicts_immediately(self):
        left = []
        h = History(max_points=5, on_leave=lambda v: left.append(v))
        for i in range(5):
            h.add(i)
        h.max_points = 2
        self.assertEqual(list(h), [3, 4])
        self.assertEqual(left, [0, 1, 2])

    def test_raising_max_points_does_not_evict(self):
        h = History(max_points=2)
        h.add(1)
        h.add(2)
        h.max_points = 10
        self.assertEqual(list(h), [1, 2])

    def test_lowering_duration_evicts_immediately(self):
        left = []
        h = History(duration=10.0, on_leave=lambda v: left.append(v))
        h.add("old")
        clock.advance(2.0)
        h.add("new")
        h.duration = 1.0  # old is age 2 > 1
        self.assertEqual(list(h), ["new"])
        self.assertEqual(left, ["old"])

    def test_grow_max_points_for_snake(self):
        h = History(max_points=3)
        for i in range(3):
            h.add(i)
        h.max_points += 1
        h.add(3)
        self.assertEqual(list(h), [0, 1, 2, 3])

    def test_pop_hands_back_alive_without_leave(self):
        left = []
        h = History(on_leave=lambda v: left.append(v))
        dot = self.own(Circle(center=(1, 2), radius=3))
        h.add(dot)
        got = h.pop()
        self.assertIs(got, dot)
        self.assertTrue(dot.is_alive)
        self.assertEqual(left, [])

    def test_discard_and_clear_full_leave(self):
        left = []
        h = History(on_leave=lambda v: left.append(v), destroy_on_leave=False)
        a = self.own(Circle(center=(1, 2), radius=3))
        b = self.own(Circle(center=(4, 5), radius=3))
        h.add(a)
        h.add(b)
        self.assertTrue(h.discard(a))
        self.assertFalse(h.discard(a))
        self.assertEqual(list(h), [b])
        h.clear()
        self.assertEqual(left, [a, b])
        self.assertTrue(a.is_alive)
        self.assertTrue(b.is_alive)

    def test_on_leave_one_argument(self):
        got = []
        h = History(on_leave=lambda v: got.append(v))
        h.add(9)
        h.clear()
        self.assertEqual(got, [9])
        h.on_leave = lambda v: got.append(("later", v))
        h.add(8)
        h.clear()
        self.assertEqual(got[1], ("later", 8))

    def test_subclass_on_leave(self):
        log = []

        class Footprints(History):
            def on_leave(self, value):
                log.append(value)

        f = Footprints(max_points=1)
        f.add("a")
        f.add("b")
        self.assertEqual(log, ["a"])
        self.assertEqual(list(f), ["b"])

    def test_subclass_rejects_constructor_callback(self):
        class Footprints(History):
            def on_leave(self, value):
                pass

        with self.assertRaises(TypeError):
            Footprints(on_leave=lambda v: None)

    def test_unbounded_not_registered(self):
        before = registered_history_count()
        h = History(max_points=3)
        h.add(1)
        self.assertEqual(registered_history_count(), before)

    def test_age_eviction_raises(self):
        h = History(duration=0.2, on_leave=lambda v: (_ for _ in ()).throw(RuntimeError("loud")))
        h.add(1)
        clock.advance(0.5)
        with self.assertRaises(RuntimeError):
            tick_all_histories()


class TestHistoryOwnership(HistoryTestCase):
    def _dot(self, x=0):
        return self.own(Circle(center=(x, 0), radius=4))

    def test_add_returns_and_destroys_on_each_leave_path(self):
        # cap
        cap = History(max_points=1)
        a = cap.add(self._dot(1))
        self.assertIs(a, cap.last)
        b = cap.add(self._dot(2))
        self.assertFalse(a.is_alive)
        self.assertTrue(b.is_alive)

        # discard / clear / lowered bound
        h = History()
        c = h.add(self._dot(3))
        d = h.add(self._dot(4))
        h.discard(c)
        self.assertFalse(c.is_alive)
        h.max_points = 0
        self.assertFalse(d.is_alive)

        aged = History(duration=0.3)
        e = aged.add(self._dot(5))
        clock.advance(0.5)
        tick_all_histories()
        self.assertFalse(e.is_alive)

    def test_on_leave_sees_alive_then_destroy(self):
        seen = []

        def leave(dot):
            seen.append(dot.is_alive)

        h = History(max_points=1, on_leave=leave)
        dot = h.add(self._dot())
        h.add(self._dot(8))
        self.assertEqual(seen, [True])
        self.assertFalse(dot.is_alive)

    def test_on_leave_raise_still_destroys(self):
        def boom(_dot):
            raise RuntimeError("author")

        h = History(max_points=1, on_leave=boom)
        dot = h.add(self._dot())
        with self.assertRaises(RuntimeError):
            h.add(self._dot(2))
        self.assertFalse(dot.is_alive)

    def test_destroy_on_leave_false_keeps_alive_and_allows_duplicate(self):
        h = History(max_points=1, destroy_on_leave=False)
        dot = h.add(self._dot())
        h.add(dot)
        self.assertTrue(dot.is_alive)
        self.assertIs(h.last, dot)
        with self.assertRaises(AttributeError):
            h.destroy_on_leave = True

    def test_plain_and_ephemeral_not_destroyed(self):
        left = []
        h = History(max_points=1, on_leave=lambda v: left.append(v))
        h.add(7)
        h.add((1, 2))
        self.assertEqual(left, [7])
        pt = Point.temp(3, 4)
        h.add(pt)
        h.add("next")
        self.assertTrue(any(v is pt for v in left))   # identity: left also holds (1, 2)
        self.assertTrue(pt.is_alive)

    def test_snapshot_copies_off_graph(self):
        from scena.canvas import ScenaCanvas
        from scena.state import get_scena_system

        h = History()
        tip = self._dot(5)
        self.enterContext(gc_paused())
        full_collect()      # the count includes garbage; a collection mid-test would move it
        before = len(get_scena_system().dependency_graph.nodes)
        p = h.snapshot(10, 20)
        q = h.snapshot((30, 40))
        r = h.snapshot(tip)
        after = len(get_scena_system().dependency_graph.nodes)
        self.assertEqual(after, before)
        self.assertTrue(p._ephemeral and q._ephemeral and r._ephemeral)
        self.assertIsNone(p._node_id)
        self.assertAlmostEqual(float(p.x), 10)
        self.assertAlmostEqual(float(q.y), 40)
        self.assertAlmostEqual(float(r.x), 5)
        self.assertFalse(ScenaCanvas.get_current().registry.is_live(p))
        with self.assertRaises(TypeError):
            h.snapshot(1, 2, 3)

    def test_guards(self):
        from scena.input import Mouse
        from scena.scenamath import Vec2

        tip = self._dot()
        h = History()
        with self.assertRaises(TypeError) as part:
            h.add(tip.center)
        self.assertIn("snapshot(", str(part.exception))
        with self.assertRaises(TypeError) as live:
            h.add(Vec2(1, 2))
        self.assertIn("snapshot", str(live.exception))
        with self.assertRaises(TypeError):
            h.add(Mouse())
        owned = h.add(self._dot(9))
        with self.assertRaises(ValueError):
            h.add(owned)

    def test_death_verb_defers_spawn_does_not(self):
        from scena import transients as tx

        tx.set_now_fn(lambda: clock.time)
        try:
            dying = self._dot(1)
            h = History(max_points=1, on_leave=lambda d: d.dissolve_out(0.4))
            h.add(dying)
            h.add(self._dot(2))
            self.assertTrue(dying.is_alive)
            clock.advance(0.5)
            tx.tick_all_transients()
            self.assertFalse(dying.is_alive)

            spawning = self._dot(3)
            spawning.fade_in(0.4)
            g = History(max_points=1)
            g.add(spawning)
            g.add(self._dot(4))
            self.assertFalse(spawning.is_alive)
        finally:
            tx.set_now_fn(None)

    def test_second_death_verb_waits_spawn_replacement_destroys(self):
        from scena import transients as tx

        tx.set_now_fn(lambda: clock.time)
        try:
            dot = self._dot()
            h = History(max_points=1, on_leave=lambda d: d.dissolve_out(1.0))
            h.add(dot)
            h.add(self._dot(2))
            dot.burn_out(1.0)
            self.assertTrue(dot.is_alive)
            dot.fade_in(0.2)
            self.assertFalse(dot.is_alive)

            other = self._dot(5)
            other.dissolve_out(1.0)
            k = History(max_points=1)
            k.add(other)
            k.clear()
            self.assertTrue(other.is_alive)
            other.clear_transients()
            self.assertFalse(other.is_alive)
        finally:
            tx.set_now_fn(None)

    def test_already_destroyed_skipped(self):
        h = History(max_points=1)
        dot = h.add(self._dot())
        dot.destroy()
        h.add(self._dot(2))  # leave of an already-dead dot must not raise

    def test_destroyed_by_breadcrumb(self):
        h = History(max_points=1)
        dot = h.add(self._dot())
        h.clear()
        with self.assertRaises(AttributeError) as ctx:
            _ = dot.hp
        self.assertIn("destroyed by History when it left", str(ctx.exception))
        self.assertIn("added at t=", str(ctx.exception))

    def test_on_destroy_chains_extra(self):
        from scena import Line

        h = History(max_points=1)
        older = h.add(self._dot(0))
        newer = self._dot(10)
        line = self.own(Line(p1=older.center, p2=newer.center))
        older.on_destroy = line.destroy
        h.add(newer)
        self.assertFalse(older.is_alive)
        self.assertFalse(line.is_alive)

    def test_contrail_add_raises_and_xy_snapshot(self):
        c = self.own(Contrail(color="red"))
        with self.assertRaises(TypeError) as ctx:
            c.add(self._dot())
        self.assertIn("snapshot", str(ctx.exception))
        c.snapshot(3, 4)
        self.assertAlmostEqual(float(c.last.x), 3)
        self.assertAlmostEqual(float(c.last.y), 4)


class TestContrail(HistoryTestCase):
    def test_stamp_point_stays_off_graph(self):
        from scena.state import get_scena_system

        c = self.own(Contrail(max_points=2, color="red"))
        self.enterContext(gc_paused())
        full_collect()
        before = len(get_scena_system().dependency_graph.nodes)
        for i in range(8):
            c.snapshot((float(i), float(i)))
        after = len(get_scena_system().dependency_graph.nodes)
        # Evicted temps must not enter the graph.
        self.assertEqual(after, before)
        self.assertEqual(len(c), 2)
        self.assertTrue(all(p._ephemeral and p._node_id is None for p in c))

    def test_stamp_snapshots_mouse(self):
        from scena.input import Mouse
        c = self.own(Contrail(max_points=4, color="red"))
        mouse = Mouse()
        mouse._update_position(15, 25)
        c.snapshot(mouse)
        mouse._update_position(1, 1)
        self.assertAlmostEqual(float(c.last.x), 15)
        self.assertAlmostEqual(float(c.last.y), 25)

    def test_stamp_snapshots_graphic(self):
        c = self.own(Contrail(max_points=10, color="red"))
        ball = Circle(center=(50, 60), radius=8)
        c.snapshot(ball)
        c.snapshot(ball.center)
        c.snapshot((70, 80))
        ball.center.x = 999
        ball.center.y = 999
        self.assertEqual(len(c), 3)
        self.assertAlmostEqual(float(c[0].x), 50)
        self.assertAlmostEqual(float(c[1].x), 50)
        self.assertAlmostEqual(float(c[2].x), 70)
        self.assertIsInstance(c.last, Point)

    def test_stroke_rebuilds(self):
        c = self.own(Contrail(max_points=4, color="cyan", line_width=3))
        c.snapshot((0, 0))
        c.snapshot((10, 0))
        self.assertEqual(c._stroke._xs, [0.0, 10.0])
        c.snapshot((20, 5))
        self.assertEqual(len(c._stroke._xs), 3)
        c.pop(0)
        self.assertEqual(c._stroke._xs, [10.0, 20.0])

    def test_fade_and_ease(self):
        c = self.own(Contrail(fade=True, ease="ease_out", color="red"))
        self.assertTrue(c.fade)
        self.assertTrue(callable(c.ease))
        c.snapshot((0, 0))
        c.snapshot((1, 1))
        self.assertTrue(c._stroke._fade)

    def test_ease_requires_fade(self):
        with self.assertRaises(TypeError):
            Contrail(ease="linear")

    def test_line_join_default_round(self):
        c = self.own(Contrail(color="red"))
        self.assertEqual(c.line_join, "round")
        c.line_join = "miter"
        self.assertEqual(c.line_join, "miter")

    def test_smooth_default_is_one(self):
        c = self.own(Contrail(color="red"))
        self.assertEqual(c.smooth, 1.0)

    def _path_verbs(self, path):
        import skia
        verbs = []
        it = skia.Path.Iter(path, False)
        while True:
            verb, _pts = it.next()
            if verb == skia.Path.Verb.kDone_Verb:
                break
            verbs.append(verb)
        return verbs

    def test_smooth_zero_is_polyline(self):
        import skia
        for smooth in (0, False):
            c = self.own(Contrail(smooth=smooth, color="red"))
            c.snapshot((0, 0))
            c.snapshot((10, 0))
            c.snapshot((10, 10))
            verbs = self._path_verbs(c._stroke._path)
            self.assertIn(skia.Path.Verb.kLine_Verb, verbs)
            self.assertNotIn(skia.Path.Verb.kCubic_Verb, verbs)

    def test_smooth_one_is_cubic_not_chord(self):
        import skia
        from scena.curves import catmull_rom_to_bezier, eval_cubic, _phantom_open

        c = self.own(Contrail(smooth=1, color="red"))
        c.snapshot((0, 0))
        c.snapshot((10, 0))
        c.snapshot((10, 10))
        verbs = self._path_verbs(c._stroke._path)
        self.assertIn(skia.Path.Verb.kCubic_Verb, verbs)
        self.assertNotIn(skia.Path.Verb.kLine_Verb, verbs)
        # Corner span midpoint is off the chord (Catmull-Rom bulge).
        pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
        _before, after = _phantom_open(pts)
        b = catmull_rom_to_bezier(pts[0], pts[1], pts[2], after, smooth=1.0)
        mid = eval_cubic(*b, 0.5)
        self.assertNotAlmostEqual(mid[0], 10.0, places=3)
        self.assertNotAlmostEqual(mid[1], 5.0, places=3)

    def test_smooth_path_endpoints_are_stamps(self):
        import skia
        c = self.own(Contrail(smooth=1, color="red"))
        c.snapshot((1, 2))
        c.snapshot((10, 0))
        c.snapshot((20, 15))
        it = skia.Path.Iter(c._stroke._path, False)
        first = None
        last = None
        while True:
            verb, pts = it.next()
            if verb == skia.Path.Verb.kDone_Verb:
                break
            if verb == skia.Path.Verb.kMove_Verb:
                first = (pts[0].x(), pts[0].y())
            if verb == skia.Path.Verb.kCubic_Verb:
                last = (pts[3].x(), pts[3].y())
        self.assertEqual(first, (1.0, 2.0))
        self.assertEqual(last, (20.0, 15.0))

    def test_smooth_live_switches_verbs(self):
        import skia
        c = self.own(Contrail(smooth=1, color="red"))
        c.snapshot((0, 0))
        c.snapshot((10, 0))
        c.snapshot((10, 10))
        self.assertIn(skia.Path.Verb.kCubic_Verb, self._path_verbs(c._stroke._path))
        c.smooth = 0
        verbs = self._path_verbs(c._stroke._path)
        self.assertIn(skia.Path.Verb.kLine_Verb, verbs)
        self.assertNotIn(skia.Path.Verb.kCubic_Verb, verbs)

    def test_fade_bands_cap_and_alphas(self):
        c = self.own(Contrail(fade=True, ease="linear", color=Color("red").with_alpha(0.8)))
        for i in range(40):
            c.snapshot((float(i), 0.0))
        bands = c._stroke._band_paths
        alphas = c._stroke._band_alphas
        self.assertLessEqual(len(bands), 16)
        self.assertEqual(len(bands), len(alphas))
        self.assertGreaterEqual(len(bands), 2)
        self.assertEqual(alphas, sorted(alphas))
        self.assertAlmostEqual(alphas[-1], 1.0, places=5)

    def test_fade_two_points_one_band(self):
        c = self.own(Contrail(fade=True, color="red"))
        c.snapshot((0, 0))
        c.snapshot((10, 0))
        self.assertEqual(len(c._stroke._band_paths), 1)
        self.assertAlmostEqual(c._stroke._band_alphas[0], 1.0, places=5)

    def test_fade_draws_band_paths_not_lines(self):
        import skia
        c = self.own(Contrail(fade=True, color="red", line_width=4, smooth=0))
        for i in range(20):
            c.snapshot((float(i), 0.0))
        paths = []
        caps = []
        lines = []

        class SpyCanvas:
            def drawLine(self, *a, **k):
                lines.append(1)

            def drawPath(self, path, paint):
                paths.append(path)
                caps.append(paint.getStrokeCap())

        c._stroke._geometry_draw(SpyCanvas())
        self.assertEqual(lines, [])
        self.assertEqual(len(paths), len(c._stroke._band_paths))
        self.assertLessEqual(len(paths), 16)
        # Tail and head keep host cap (round); interior bands are butt.
        self.assertEqual(caps[0], skia.Paint.Cap.kRound_Cap)
        self.assertEqual(caps[-1], skia.Paint.Cap.kRound_Cap)
        if len(caps) > 2:
            self.assertTrue(all(cap == skia.Paint.Cap.kButt_Cap for cap in caps[1:-1]))

    def test_no_fade_draw_path(self):
        c = self.own(Contrail(fade=False, color="red"))
        c.snapshot((0, 0))
        c.snapshot((10, 0))
        paths = []
        lines = []

        class SpyCanvas:
            def drawLine(self, *a, **k):
                lines.append(1)

            def drawPath(self, path, paint):
                paths.append(1)

        c._stroke._geometry_draw(SpyCanvas())
        self.assertEqual(paths, [1])
        self.assertEqual(lines, [])

    def test_stamp_rebuilds_once(self):
        c = self.own(Contrail(max_points=3, color="red"))
        c.snapshot((0, 0))
        c.snapshot((1, 0))
        c.snapshot((2, 0))
        before = c._rebuild_count
        c.snapshot((3, 0))  # append + one eviction
        self.assertEqual(c._rebuild_count, before + 1)
        self.assertEqual(len(c), 3)

    def test_duration_tick_rebuilds_once(self):
        c = self.own(Contrail(duration=0.5, color="gold"))
        for i in range(5):
            c.snapshot((float(i), 0.0))
        before = c._rebuild_count
        clock.advance(0.6)
        tick_all_histories()
        self.assertEqual(len(c), 0)
        self.assertEqual(c._rebuild_count, before + 1)

    def test_visual_laser(self):
        c = self.own(Contrail(visual=Laser("red"), max_points=5))
        c.snapshot((0, 0))
        c.snapshot((5, 5))
        self.assertIsNotNone(c.visual)

    def test_color_with_alpha(self):
        c = self.own(Contrail(color=Color("cyan").with_alpha(0.5)))
        self.assertAlmostEqual(float(c.color.alpha), 0.5, places=4)

    def test_author_on_leave(self):
        left = []
        c = self.own(Contrail(max_points=1, on_leave=lambda v: left.append(v), color="red"))
        c.snapshot((0, 0))
        c.snapshot((1, 1))
        self.assertEqual(len(left), 1)
        self.assertIsInstance(left[0], Point)

    def test_duration_clears_stroke(self):
        c = self.own(Contrail(duration=0.4, color="gold"))
        c.snapshot((0, 0))
        c.snapshot((10, 10))
        clock.advance(0.5)
        tick_all_histories()
        self.assertEqual(len(c), 0)
        self.assertEqual(c._stroke._xs, [])

    def test_grow_trail(self):
        c = self.own(Contrail(max_points=2, color="lime"))
        c.snapshot((0, 0))
        c.snapshot((1, 0))
        c.max_points += 1
        c.snapshot((2, 0))
        self.assertEqual(len(c), 3)

    def test_track_from_contrail_points(self):
        c = self.own(Contrail(color="red"))
        c.snapshot((0, 0))
        c.snapshot((40, 0))
        c.snapshot((40, 40))
        track = self.own(Track(points=list(c), smooth=0, color="yellow"))
        track._ensure_samples()
        self.assertGreater(float(track.length), 0.0)

    def test_non_pointlike_raises(self):
        c = self.own(Contrail(color="red"))
        with self.assertRaises(TypeError):
            c.snapshot(Color("red"))

    def test_destroy(self):
        c = Contrail(color="red", duration=2.0)
        c.snapshot((0, 0))
        stroke = c._stroke
        c.destroy()
        self.assertEqual(len(c), 0)
        self.assertFalse(stroke.is_alive)

    def test_stroke_is_private_shape(self):
        c = self.own(Contrail(color="red"))
        self.assertIsInstance(c._stroke, _Stroke)
        self.assertTrue(c._stroke._primary_is_stroke())


# Public Contrail names that write. A new public name fails
# test_public_names_are_classified until it is listed here or in _READ_ONLY.
_CONTRAIL_MUTATORS = {
    "snapshot": lambda c: c.snapshot((1, 1)),
    "add": lambda c: c.add(None),
    "pop": lambda c: c.pop(),
    "discard": lambda c: c.discard(None),
    "clear": lambda c: c.clear(),
    "max_points": lambda c: setattr(c, "max_points", 4),
    "duration": lambda c: setattr(c, "duration", 1.0),
    "on_leave": lambda c: setattr(c, "on_leave", lambda _v: None),
    "fade": lambda c: setattr(c, "fade", False),
    "ease": lambda c: setattr(c, "ease", "ease_out"),
    "smooth": lambda c: setattr(c, "smooth", 0),
    "color": lambda c: setattr(c, "color", "blue"),
    "visual": lambda c: setattr(c, "visual", Laser("gold")),
    "line_width": lambda c: setattr(c, "line_width", 4),
    "line_join": lambda c: setattr(c, "line_join", "miter"),
    "line_cap": lambda c: setattr(c, "line_cap", "butt"),
}

_CONTRAIL_READ_ONLY = frozenset({
    "first", "last", "destroy", "destroy_on_leave",
})


def _frame(real_dt=0.1):
    clock.advance(real_dt)
    tick_processes()


class TestContrailUseAfterDestroy(HistoryTestCase):
    """Use after Contrail.destroy() raises — the whole mutator surface, not one method."""

    def _dead(self):
        c = Contrail(fade=True, ease="linear", color="red", duration=1.0)
        c.snapshot((0, 0))
        c.destroy()
        return c

    def test_public_names_are_classified(self):
        public = {n for n in dir(Contrail) if not n.startswith("_")}
        unknown = public - _CONTRAIL_READ_ONLY - set(_CONTRAIL_MUTATORS)
        self.assertEqual(
            unknown, set(),
            "new Contrail surface must be a mutator (raises after destroy) or read-only",
        )

    def test_each_mutator_raises(self):
        for name, call in _CONTRAIL_MUTATORS.items():
            c = self._dead()
            with self.assertRaises(DestroyedError, msg=name) as ctx:
                call(c)
            self.assertIn("cannot " + name, str(ctx.exception), name)
            self.assertIn("cancel its handle", str(ctx.exception), name)

    def test_reads_stay_legal(self):
        c = self._dead()
        self.assertEqual(len(c), 0)
        self.assertEqual(list(c), [])
        self.assertIn("Contrail", repr(c))
        self.assertTrue(c.fade)
        self.assertTrue(c.destroy_on_leave)
        self.assertEqual(c.duration, 1.0)
        self.assertIsNone(c.on_leave)
        with self.assertRaises(IndexError):
            _ = c.first
        with self.assertRaises(IndexError):
            _ = c.last

    def test_destroy_is_idempotent(self):
        c = self._dead()
        c.destroy()
        self.assertEqual(len(c), 0)


class TestSnapshotDestroyedSource(HistoryTestCase):
    def _stores(self):
        return [History(), self.own(Contrail(color="red"))]

    def test_dead_entity_and_parts(self):
        from scena import Line

        for store in self._stores():
            dot = self.own(Circle(center=(3, 4), radius=2))
            dot.destroy()
            with self.assertRaises(DestroyedError) as ctx:
                store.snapshot(dot)
            self.assertIn(".every(", str(ctx.exception))

            dot = self.own(Circle(center=(3, 4), radius=2))
            center = dot.center
            dot.destroy()
            with self.assertRaises(DestroyedError) as ctx:
                store.snapshot(center)
            self.assertIn(".every(", str(ctx.exception))

            line = self.own(Line(p1=(0, 0), p2=(5, 5)))
            p1 = line.p1
            line.destroy()
            with self.assertRaises(DestroyedError) as ctx:
                store.snapshot(p1)
            self.assertIn(".every(", str(ctx.exception))

    def test_add_dead_entity(self):
        for store in self._stores():
            dot = self.own(Circle(center=(0, 0), radius=1))
            dot.destroy()
            with self.assertRaises(DestroyedError):
                store.add(dot)

    def test_mouse_and_tuples_still_snapshot(self):
        from scena.input import Mouse

        for store in self._stores():
            store.snapshot(Mouse())
            store.snapshot((8, 9))
            store.snapshot(1, 2)
            self.assertGreaterEqual(len(store), 3)


class TestSamplingTimerLifetime(HistoryTestCase):
    def setUp(self):
        super().setUp()
        reset_process_scheduler()

    def tearDown(self):
        reset_process_scheduler()
        super().tearDown()

    def test_entity_every_stops_when_source_is_destroyed(self):
        e = self.own(Circle(center=(1, 2), radius=3))
        c = self.own(Contrail(color="red"))
        seen = []
        e.every(0.01, lambda: seen.append(c.snapshot(e)))
        e.destroy()
        _frame(0.02)
        self.assertEqual(seen, [])

    def test_module_every_raises_after_source_is_destroyed(self):
        e = self.own(Circle(center=(1, 2), radius=3))
        c = self.own(Contrail(color="red"))
        every(0.01, lambda: c.snapshot(e))
        e.destroy()
        with self.assertRaises(DestroyedError) as ctx:
            _frame(0.02)
        self.assertIn(".every(", str(ctx.exception))

    def test_module_every_raises_after_contrail_is_destroyed(self):
        c = self.own(Contrail(duration=1.0, color="red"))
        every(0.01, lambda: c.snapshot((1, 1)))
        c.destroy()
        with self.assertRaises(DestroyedError) as ctx:
            _frame(0.02)
        self.assertIn("cannot snapshot", str(ctx.exception))
        self.assertIn("cancel its handle", str(ctx.exception))


class TestSegmentsRecipe(HistoryTestCase):
    """Per-segment lines: the line dies with its older endpoint."""

    def test_segment_destroyed_with_older_endpoint(self):
        from scena import Line

        segments = History(max_points=3)
        tip = self.own(Circle(center=(0, 0), radius=2))
        for x in (0, 10, 20, 30):
            tip.center.x = x
            start = segments.last.p2 if segments else tip.center
            segment = segments.add(Line(p1=start, p2=tip.center))
            segment.visual = Laser("red")
            self.own(segment)
        self.assertEqual(len(segments), 3)
        self.assertTrue(all(seg.is_alive for seg in segments))


if __name__ == "__main__":
    unittest.main()
