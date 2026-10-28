"""Leak-detector heuristic: registry objects + reactive-graph growth.

Run headless:

    python -m unittest tests.test_leak_detector -v
"""

import gc
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.leak_detector import (
    CLIMB_TAIL,
    HISTORY_LEN,
    LeakSampler,
    MIN_OBJECT_STEP,
    MIN_OBJECTS_TO_WARN,
    SAMPLE_EVERY_FRAMES,
    SAMPLE_EVERY_SECONDS,
    format_leak_message,
    leak_signal,
)
from scena.process import clear_author_error, last_author_error, report_author_warning


def _fill(history, n=HISTORY_LEN):
    """Pad / trim to exactly HISTORY_LEN samples."""
    if len(history) >= n:
        return list(history[-n:])
    if not history:
        return [(0, 0)] * n
    out = list(history)
    while len(out) < n:
        out.insert(0, out[0])
    return out


class TestLeakSignal(unittest.TestCase):
    def test_flat_flat_is_none(self):
        h = [(10, 100)] * HISTORY_LEN
        self.assertIsNone(leak_signal(h))

    def test_too_short_is_none(self):
        self.assertIsNone(leak_signal([(1, 1)] * (HISTORY_LEN - 1)))

    def test_graph_climbing_objects_flat(self):
        # Signature of the Vec2-reassignment leak: every sample still up.
        h = [(5, 50 + i * 20) for i in range(HISTORY_LEN)]
        self.assertEqual(leak_signal(h), "graph")

    def test_objects_climbing_at_leak_rate(self):
        # Per-frame construct without destroy: leak-sized step every sample.
        # Graph grows too (Entities register) — that must not look like spawn.
        step = MIN_OBJECT_STEP
        h = [(5 + i * step, 80 + i * step) for i in range(HISTORY_LEN)]
        self.assertEqual(leak_signal(h), "objects")

    def test_proportional_spawner_is_none(self):
        # Both climb together at a spawn-sized rate (1 object / sample).
        h = [(10 + i, 100 + i * 8) for i in range(HISTORY_LEN)]
        self.assertIsNone(leak_signal(h))

    def test_soak_churn_create_destroy_replay_is_none(self):
        # Mimic soak_leak: spike up then back to idle each cycle.
        # Across a window that spans full cycles, net delta is ~0.
        idle_e, idle_g = 4, 120
        samples = []
        for _ in range(3):
            samples.append((idle_e, idle_g))
            samples.append((idle_e + 30, idle_g + 80))
            samples.append((idle_e + 30, idle_g + 80))
            samples.append((idle_e, idle_g))
        h = _fill(samples)
        # First and last both idle → no net growth.
        self.assertIsNone(leak_signal(h))

    def test_graph_noise_below_threshold_is_none(self):
        h = [(5, 100 + i) for i in range(HISTORY_LEN)]  # +9 total < MIN_GRAPH_DELTA
        self.assertIsNone(leak_signal(h))

    def test_rgb_arena_criar_burst_then_plateau_is_none(self):
        # Terminal replay: 14→22 over a handful of clicks, then idle.
        # Old heuristic fired "objects" because graph stayed within slack.
        h = [
            (14, 80),
            (14, 82),
            (16, 84),
            (18, 86),
            (20, 88),
            (22, 90),
            (22, 90),
            (22, 91),
            (24, 92),
            (24, 92),
        ]
        self.assertEqual(len(h), HISTORY_LEN)
        self.assertIsNone(leak_signal(h))

    def test_rgb_arena_sliding_window_from_terminal_is_none(self):
        # Later windows from the same session still have net +8..+14 with
        # a plateau tail — must stay quiet.
        h = [
            (16, 90),
            (16, 90),
            (18, 92),
            (20, 94),
            (22, 96),
            (24, 98),
            (26, 100),
            (28, 102),
            (28, 102),
            (28, 102),
        ]
        self.assertIsNone(leak_signal(h))

    def test_graph_warmup_then_plateau_is_none(self):
        # First-touch ContainerSlot materialization: +40 then flat.
        h = [(10, 36), (10, 48), (10, 60), (10, 76)] + [(10, 76)] * (HISTORY_LEN - 4)
        self.assertEqual(len(h), HISTORY_LEN)
        self.assertIsNone(leak_signal(h))

    def test_casual_clicks_across_window_is_none(self):
        # One particle (+2 objects, +2 graph) every other sample — sandbox play.
        ents = [14]
        graphs = [80]
        for i in range(1, HISTORY_LEN):
            if i % 2 == 0:
                ents.append(ents[-1] + 2)
                graphs.append(graphs[-1] + 2)
            else:
                ents.append(ents[-1])
                graphs.append(graphs[-1])
        h = list(zip(ents, graphs))
        self.assertIsNone(leak_signal(h))


class TestLeakSampler(unittest.TestCase):
    def test_advance_only_samples_every_k_frames(self):
        s = LeakSampler()
        hits = 0
        for _ in range(SAMPLE_EVERY_FRAMES * 2):
            if s.advance():
                hits += 1
        self.assertEqual(hits, 2)

    def test_advance_uses_wall_clock_not_frame_count(self):
        s = LeakSampler()
        now = 0.0
        hits = 0
        # Uncapped FPS: 180 frames in 0.18s must not fill a ~15s window.
        for _ in range(SAMPLE_EVERY_FRAMES * 2):
            now += 0.001
            if s.advance(now):
                hits += 1
        self.assertEqual(hits, 0)
        now += SAMPLE_EVERY_SECONDS
        self.assertTrue(s.advance(now))

    def test_disabled_never_advances_sample(self):
        s = LeakSampler()
        s.enabled = False
        for _ in range(SAMPLE_EVERY_FRAMES * 3):
            self.assertFalse(s.advance())

    def test_sample_emits_graph_hit_after_window(self):
        s = LeakSampler()
        hit = None
        for i in range(HISTORY_LEN):
            hit = s.sample(5, 50 + i * 30)
        self.assertIsNotNone(hit)
        kind, msg = hit
        self.assertEqual(kind, "graph")
        self.assertIn("graph", msg.lower())

    def test_sample_does_not_repeat_same_trend(self):
        s = LeakSampler()
        hits = []
        for i in range(HISTORY_LEN + 3):
            hit = s.sample(5, 50 + i * 30)
            if hit is not None:
                hits.append(hit[0])
        self.assertEqual(hits, ["graph"])

    def test_recount_that_drops_the_climb_is_no_hit(self):
        """D11: a climb one ``gc.collect()`` gives back is churn, not a leak."""
        s = LeakSampler()
        calls = []

        def recount():
            calls.append(1)
            return 5, 50

        hits = [s.sample(5, 50 + i * 30, recount=recount) for i in range(HISTORY_LEN)]
        self.assertEqual(hits, [None] * HISTORY_LEN)
        self.assertEqual(len(calls), 1, "recount runs only when a hit is about to fire")

    def test_recount_that_keeps_the_climb_still_warns(self):
        s = LeakSampler()
        hit = None
        for i in range(HISTORY_LEN):
            g = 50 + i * 30
            hit = s.sample(5, g, recount=lambda g=g: (5, g))
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "graph")

    def test_no_recount_while_the_same_trend_is_active(self):
        s = LeakSampler()
        calls = []

        def recount():
            calls.append(1)
            return s._history[-1]

        for i in range(HISTORY_LEN + 4):
            s.sample(5, 50 + i * 30, recount=recount)
        self.assertEqual(len(calls), 1)


class TestGcChurnIsNotALeak(unittest.TestCase):
    """D11 (Testing Design), the class: graph nodes that only the cyclic GC
    frees. A Container tree is a reference cycle (owner <-> parts), so a
    discarded one leaves the WeakValueDictionary graph at a full collection
    only. Built every frame (an author ``Box(center=...)``, a ``Point``),
    those nodes climb between collections — and the frozen heap after setup
    makes full collections rare. The detector must recount after one
    ``gc.collect()`` before it warns; a held reference must still warn."""

    def setUp(self):
        from scena import init
        from scena.orchestration import ScenaFramework
        init(width=400, height=300)
        self.fw = ScenaFramework.get_instance()
        self.fw._leak_sampler.reset()
        self.fw._leak_sampler.advance = lambda now=None: True
        clear_author_error()
        self._gc_was = gc.isenabled()
        gc.collect()
        gc.disable()

    def tearDown(self):
        if self._gc_was:
            gc.enable()
        del self.fw._leak_sampler.advance
        self.fw._leak_sampler.reset()
        clear_author_error()

    def run_window(self, keep):
        from scena import Box
        for _ in range(HISTORY_LEN + 2):
            for _ in range(40):
                b = Box(center=(1, 2), width=3, height=4)  # eager: registers
                b.top_left
                if keep is not None:
                    keep.append(b)
            self.fw._tick_leak_detector()

    def test_cyclic_churn_does_not_warn(self):
        self.run_window(keep=None)
        self.assertIsNone(last_author_error())

    def test_held_containers_still_warn(self):
        kept = []
        self.run_window(keep=kept)
        err = last_author_error()
        self.assertIsNotNone(err)
        self.assertEqual(err["where"], "leak-detector")


class TestPartsOfDrawnObjectsAreNotOrphans(unittest.TestCase):
    """Showcase A7 (2026-10-23): the graph registers parts (a polygon's
    vertices, a History's points), the drawn-object count does not, so a
    polygon given one more side each wave, or a History filling slowly, read
    as "reactive graph rising while objects stay ~9". The graph signals
    compare the graph with the live roster (parts included); a roster that
    jumps while nothing more is drawn warns only when the growth sits off
    screen (held Boxes), not in drawn parts."""

    def window(self, drawn, graph, live):
        return [(drawn(i), graph(i), live(i)) for i in range(HISTORY_LEN)]

    def test_graph_and_roster_growing_together_is_not_orphans(self):
        # Not "graph"; the roster's own climb is judged by where it sits
        # (test_roster_hit_needs_growth_off_screen).
        h = self.window(lambda i: 28, lambda i: 300 + 30 * i, lambda i: 200 + 28 * i)
        self.assertNotEqual(leak_signal(h), "graph")
        s = LeakSampler()
        hits = [s.sample(*row[:2], live=row[2], off_screen=lambda: 0) for row in h]
        self.assertEqual([x for x in hits if x is not None], [])

    def test_graph_with_a_flat_roster_is_still_orphans(self):
        h = self.window(lambda i: 28, lambda i: 300 + 30 * i, lambda i: 200)
        self.assertEqual(leak_signal(h), "graph")

    def test_a_jumping_roster_with_nothing_more_drawn_is_flagged(self):
        h = self.window(lambda i: 9, lambda i: 100 + 80 * i, lambda i: 100 + 80 * i)
        self.assertEqual(leak_signal(h), "roster")

    def test_roster_hit_needs_growth_off_screen(self):
        h = self.window(lambda i: 9, lambda i: 100 + 80 * i, lambda i: 100 + 80 * i)
        for off, fires in ((10, False), (500, True)):
            with self.subTest(off_screen=off):
                s = LeakSampler()
                hit = None
                for row in h:
                    hit = s.sample(*row[:2], live=row[2], off_screen=lambda o=off: o) or hit
                self.assertEqual(hit is not None, fires)
                if fires:
                    self.assertEqual(hit[0], "roster")
                    self.assertIn("off screen", hit[1])


class TestDrawnPartsGrowInAGame(unittest.TestCase):
    """The framework's own sampler on the two showcase scenes."""

    def setUp(self):
        from scena import init
        from scena.orchestration import ScenaFramework
        init(width=400, height=300)
        self.fw = ScenaFramework.get_instance()
        self.fw._leak_sampler.reset()
        self.fw._leak_sampler.advance = lambda now=None: True
        clear_author_error()

    def tearDown(self):
        del self.fw._leak_sampler.advance
        self.fw._leak_sampler.reset()
        clear_author_error()

    def test_polygons_given_one_more_side_each_wave(self):
        from scena import RegularPolygon
        polys = []
        try:
            for wave in range(HISTORY_LEN + 3):
                for p in polys:
                    p.destroy()
                polys = [RegularPolygon(n=3 + wave, center=(20 + 12 * i, 150), radius=5)
                         for i in range(28)]
                for p in polys:
                    p.points
                gc.collect()
                self.fw._tick_leak_detector()
            self.assertIsNone(last_author_error())
        finally:
            for p in polys:
                p.destroy()

    def test_a_history_filling_slowly(self):
        from scena import Circle, History
        trail = History(max_points=16, on_leave=lambda dot: dot.destroy())
        made = []
        try:
            for beat in range(HISTORY_LEN + 3):
                dot = Circle(center=(10 + beat * 5, 100), radius=2)
                made.append(dot)
                trail.add(dot)
                self.fw._tick_leak_detector()
            self.assertIsNone(last_author_error())
        finally:
            for d in made:
                if not d._destroyed:
                    d.destroy()


class TestObjectsWarnOnlyWhenItMatters(unittest.TestCase):
    """"objects rising" fired on games: a spawner of ~6/s whose objects live
    ~20 s climbs like a leak for 13 s and warned at ~100 objects (2026-10-27).
    A new "objects" hit now needs MIN_OBJECTS_TO_WARN drawn objects and half
    the growth off view (the shot that left the screen, never destroyed).
    The growth off view is counted from the climb's first walk: a world
    bigger than the screen keeps hundreds off view while a spawner climbs on
    screen, and the off-view total warned there (RA4)."""

    STEP = 3 * MIN_OBJECT_STEP

    def _climb(self, s, base, steps=HISTORY_LEN + 2, **kw):
        hit = None
        for i in range(steps):
            e = base + i * self.STEP
            hit = s.sample(e, 80 + e, **kw) or hit
        return hit

    def test_spawner_of_six_a_second_is_quiet(self):
        s = LeakSampler()
        hits = []
        for i in range(30):                       # 45 s at 1.5 s a sample
            t = i * 1.5
            n = 20 + int(6 * min(t, 20.0))
            hits.append(s.sample(n, n * 5, live=n))
        self.assertEqual([h for h in hits if h], [])

    def test_below_the_floor_never_collects(self):
        s = LeakSampler()
        calls = []

        def recount():
            calls.append(1)
            return s._history[-1]
        self.assertIsNone(self._climb(s, 10, recount=recount))
        self.assertLess(10 + (HISTORY_LEN + 1) * self.STEP, MIN_OBJECTS_TO_WARN)
        self.assertEqual(calls, [])

    def test_growth_on_screen_is_quiet(self):
        s = LeakSampler()
        self.assertIsNone(self._climb(s, MIN_OBJECTS_TO_WARN, off_view=lambda: 0))

    def test_a_world_kept_off_view_is_not_growth(self):
        # 10 000 static objects off view, the climb on screen (RA4).
        s = LeakSampler()
        self.assertIsNone(self._climb(s, MIN_OBJECTS_TO_WARN, steps=40,
                                      off_view=lambda: 10_000))

    def test_growth_off_view_warns_and_says_so(self):
        # A world off view, and every new object leaves the screen too.
        s = LeakSampler()
        hit = self._climb(s, MIN_OBJECTS_TO_WARN,
                          off_view=lambda: 10_000 + s._history[-1][0])
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "objects")
        self.assertIn(f"{2 * self.STEP} more off view", hit[1])
        self.assertIn("possible missing destroy()", hit[1])

    def test_half_the_growth_off_view_is_enough(self):
        s = LeakSampler()
        hit = self._climb(s, MIN_OBJECTS_TO_WARN,
                          off_view=lambda: 500 + s._history[-1][0] // 2)
        self.assertEqual(hit and hit[0], "objects")

    def test_a_new_climb_takes_a_new_baseline(self):
        s = LeakSampler()
        self._climb(s, MIN_OBJECTS_TO_WARN, off_view=lambda: 0)
        self.assertIsNotNone(s._off_base)
        for _ in range(HISTORY_LEN):
            s.sample(2000, 2080, off_view=lambda: 0)
        self.assertIsNone(s._off_base)

    def test_without_a_view_walk_the_floor_still_applies(self):
        s = LeakSampler()
        self.assertIsNone(self._climb(s, 10))
        s = LeakSampler()
        hit = self._climb(s, MIN_OBJECTS_TO_WARN)
        self.assertEqual(hit[0], "objects")

    def test_an_on_screen_climb_is_walked_every_few_samples(self):
        s = LeakSampler()
        walks = []

        def off_view():
            walks.append(len(s._history))
            return 0
        for i in range(HISTORY_LEN + 3 * (CLIMB_TAIL + 1)):
            e = MIN_OBJECTS_TO_WARN + i * self.STEP
            s.sample(e, 80 + e, off_view=off_view)
        self.assertEqual(len(walks), 4)


class TestObjectsOffViewInAGame(unittest.TestCase):
    """The framework's sampler, drawn objects on and off the view."""

    def setUp(self):
        from scena import init
        from scena.orchestration import ScenaFramework
        init(width=400, height=300)
        self.fw = ScenaFramework.get_instance()
        self.fw._leak_sampler.reset()
        self.fw._leak_sampler.advance = lambda now=None: True
        clear_author_error()
        self.made = []

    def tearDown(self):
        del self.fw._leak_sampler.advance
        self.fw._leak_sampler.reset()
        clear_author_error()
        for d in self.made:
            if not d._destroyed:
                d.destroy()

    def _waves(self, where, waves=HISTORY_LEN + 3):
        from scena import Circle
        per = MIN_OBJECTS_TO_WARN // (HISTORY_LEN - 2)
        for wave in range(waves):
            for i in range(per):
                self.made.append(Circle(center=where(wave, i), radius=2))
            self.fw._tick_leak_detector()

    def test_a_pile_on_screen_is_quiet(self):
        self._waves(lambda w, i: (20 + (i * 7) % 360, 20 + (w * 13 + i) % 260))
        self.assertIsNone(last_author_error())

    def test_a_spawner_on_screen_in_a_big_world_is_quiet(self):
        # RA4: 400 objects of the level far off view, the climb on screen.
        from scena import Rect
        for i in range(400):
            self.made.append(Rect(center=(3000 + 30 * i, 150), width=20, height=20))
        self._waves(lambda w, i: (20 + (i * 7) % 360, 20 + (w * 13 + i) % 260),
                    waves=HISTORY_LEN + 12)
        self.assertIsNone(last_author_error())

    def test_shots_that_left_the_screen_warn(self):
        self._waves(lambda w, i: (5000 + w * 40 + i, 150))
        err = last_author_error()
        self.assertIsNotNone(err)
        self.assertIn("objects rising", err["message"])
        self.assertIn("off view", err["message"])


class TestWarningChannel(unittest.TestCase):
    def setUp(self):
        clear_author_error()

    def tearDown(self):
        clear_author_error()

    def test_report_author_warning_dedups(self):
        report_author_warning("leak-detector", "reactive graph rising (10→50)")
        report_author_warning("leak-detector", "reactive graph rising (10→50)")
        err = last_author_error()
        self.assertIsNotNone(err)
        self.assertEqual(err["severity"], "warning")
        self.assertEqual(err["where"], "leak-detector")
        self.assertEqual(err["count"], 2)


class TestLeakMessageWording(unittest.TestCase):
    """The SCENA WARNING text authors read: plain "objects", never "scene"
    (the word was reserved for the author concept, now Act; it means only the rendered frame)."""

    def test_objects_message(self):
        msg = format_leak_message("objects", 40, 900, 10, 300)
        self.assertTrue(msg.startswith("objects rising (10→40)"), msg)
        self.assertIn("possible missing destroy()", msg)
        self.assertNotIn("scene", msg.lower())

    def test_graph_message(self):
        msg = format_leak_message("graph", 12, 900, 12, 300)
        self.assertTrue(msg.startswith("reactive graph rising (300→900)"), msg)
        self.assertNotIn("scene", msg.lower())


class TestRegistryObjectCount(unittest.TestCase):
    """D1 (Testing Design): the leak detector's entity count included the
    tombstones destroyed objects leave in a draw list until ``compact()``."""

    def test_count_ignores_tombstones(self):
        from scena import Circle, init
        from scena.orchestration import ScenaFramework
        init(width=400, height=300)
        fw = ScenaFramework.get_instance()
        before = fw._count_registry_objects()
        shapes = [Circle() for _ in range(4)]
        self.assertEqual(fw._count_registry_objects(), before + 4)
        for s in shapes[:3]:
            s.destroy()
        self.assertEqual(fw._count_registry_objects(), before + 1)
        shapes[3].destroy()
        self.assertEqual(fw._count_registry_objects(), before)


if __name__ == "__main__":
    unittest.main()
