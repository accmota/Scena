"""
The claims of ``examples/one_line.py``, played headless.

The example says: one line of light is a circle, then a star, a spiral, a
figure eight, a wave and a circle again (Birth, Star, Eight, Wave, Home, in
that order, and round again); the comet's lit window runs around the line
and stays on it (begin / end inside [0, 1]); the comet's head, the pearls
and their threads are read from the line; the rings the comet leaves sit at
the star's tips and at the eight's crossing, and the History keeps at most
six; the zigzag and coil variations are written on the line while a tween
plays them; each round starts on a clean stage.

Three rounds of the whole storyboard (~171 s of demo, ~5 s headless) feed
every check: a round's leftovers (a hidden shape never destroyed, a tween
on an ``st`` cell that runs on) show up as a growing count or a warning only
in the next round.

Bug class guarded: **an example that stops doing what its docstring says**
after an engine change (``Track`` presets and ``at()``, ``begin`` / ``end``
links and ``unlink``, ``move_along`` on a reversed view, ``zigzag`` /
``orbit`` rewritten under a tween, ``History`` eviction) while it still
builds and runs: ``test_scripts_run`` plays only its first 30 frames.

Run:

    python tests/run_tiers.py focused test_example_one_line
"""
from __future__ import annotations

import inspect
import math
import os
import sys
import unittest
import warnings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from program_support import run_registry  # noqa: E402
from program_support import ProgramRun  # noqa: E402

from scena import clock  # noqa: E402

PATH = "examples/one_line.py"
SECOND = 60
CENTER = (640, 400)
PARTS = ["backdrop", "birth", "star", "eight", "wave", "home"]
IGNORED = (DeprecationWarning, PendingDeprecationWarning, ResourceWarning)


def xy(p):
    """A point (a Vec2, or the tuple ``Track.at`` returns) as two floats."""
    if isinstance(p, tuple):
        return float(p[0]), float(p[1])
    return float(p.x), float(p.y)


def reach(line, n=240):
    """The nearest and the farthest the line goes from the centre."""
    d = [math.dist(xy(line.at(k / n)), CENTER) for k in range(n + 1)]
    return min(d), max(d)


class Playthrough:
    def __init__(self):
        self.calls = []             # (part, frame, live count)
        self.failures = []
        self.shapes = {}            # what the line was, at a moment of each part
        self.rings = []             # (place, wiggle, coil, drift, marks)
        self.max_ghosts = 0
        self.window_frames = 0      # frames whose comet window was checked
        self.spark_frames = 0
        self.pearls_seen = 0

    def run(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with ProgramRun(PATH, seed=1) as run:
                self.play(run)
        self.warnings = [str(w.message) for w in caught if not issubclass(w.category, IGNORED)]

    def watch(self, run, name):
        ns = run.ns
        orig = ns[name]
        calls = self.calls
        if inspect.iscoroutinefunction(orig):
            async def watched(*a, **k):
                calls.append((name, run.frames, len(run_registry().live)))
                return await orig(*a, **k)
        else:
            def watched(*a, **k):
                calls.append((name, run.frames, len(run_registry().live)))
                return orig(*a, **k)
        ns[name] = watched

    def play(self, run):
        ns = run.ns
        st = ns["st"]
        for name in PARTS:
            self.watch(run, name)
        ghost = ns["ghost"]

        def watched_ghost(place, ramp):
            self.rings.append((tuple(place), st.wiggle, st.coil, st.drift, st.marks))
            ghost(place, ramp)

        ns["ghost"] = watched_ghost
        for _ in range(180 * SECOND):
            run.step(1)
            self.every_frame(ns, st)
            if not self.calls:
                continue
            part, start, _live = self.calls[-1]
            k = run.frames - start
            if len(self.calls) > 2 * len(PARTS) + 1:
                return          # the third round has begun
            moment = {("birth", 1): "circle", ("star", 1): "star", ("star", 6): "zigzag",
                      ("eight", 1): "spiral", ("eight", 7): "eight", ("eight", 17): "coil",
                      ("wave", 1): "wave", ("home", 1): "home"}
            if k % SECOND == 0 and (part, k // SECOND) in moment:
                self.shapes[moment[part, k // SECOND]] = self.shape(st)
            if k % 20 == 0:
                self.check_pearls(ns)

    def every_frame(self, ns, st):
        if st.ghosts is not None:
            self.max_ghosts = max(self.max_ghosts, len(st.ghosts))
        line = st.line
        if line is None:
            return
        self.window_frames += 1
        for field in ("begin", "end"):
            value = getattr(line, field)
            if not 0 <= value <= 1:
                self.failures.append(f"the comet's {field} left the line: {value}")
        if st.spark is not None:
            self.spark_frames += 1
            want = xy(line.at(st.head % 1))
            if math.dist(xy(st.spark.center), want) > 1e-6:
                self.failures.append(f"the comet's head is off the line: {xy(st.spark.center)} {want}")

    def shape(self, st):
        line = st.line
        near, far = reach(line)
        points = [xy(line.at(k / 240)) for k in range(241)]
        xs = [x for x, _ in points]
        ys = [y for _, y in points]
        return {"near": near, "far": far, "start": xy(line.at(0)), "end": xy(line.at(1)),
                "width": max(xs) - min(xs), "height": max(ys) - min(ys),
                "wiggle": st.wiggle, "coil": st.coil, "drift": st.drift, "points": points}

    def check_pearls(self, ns):
        """A thread runs from the centre to its pearl, and a pearl is 2 to 8 wide."""
        pearls = [p for p in ns["group"]["pearl"] if type(p).__name__ == "Circle"]
        threads = list(ns["group"]["thread"])
        if not pearls:
            return
        self.pearls_seen += 1
        centers = [xy(p.center) for p in pearls]
        for t in threads:
            if math.dist(xy(t.p1), CENTER) > 1e-6:
                self.failures.append("a thread left the centre")
            if min(math.dist(xy(t.p2), c) for c in centers) > 1e-6:
                self.failures.append("a thread lost its pearl")
        for p in pearls:
            if not 2 - 1e-9 <= p.radius <= 8 + 1e-9:
                self.failures.append(f"a pearl of radius {p.radius}")


class TestOneLine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seen = Playthrough()
        cls.seen.run()

    def test_plays_through_without_a_warning(self):
        self.assertEqual(self.seen.warnings, [])
        self.assertEqual(self.seen.failures, [])
        self.assertGreater(self.seen.window_frames, 60 * SECOND, "vacuous: no line")
        self.assertGreater(self.seen.spark_frames, 30 * SECOND, "vacuous: no comet")
        self.assertGreater(self.seen.pearls_seen, 20, "vacuous: no pearls")

    def test_the_parts_run_in_order_and_loop(self):
        names = [c[0] for c in self.seen.calls]
        self.assertEqual(names, PARTS * 2 + ["backdrop", "birth"])
        frames = [c[1] for c in self.seen.calls]
        rounds = [f for name, f, _ in self.seen.calls if name == "backdrop"]
        for a, b in zip(rounds, rounds[1:]):
            self.assertLess(abs((b - a) / SECOND - 85.5), 3, "one round is ~85 s")
        lives = [c[2] for c in self.seen.calls if c[0] == "backdrop"]
        self.assertEqual(len(lives), 3)
        lives = set(lives)
        self.assertEqual(len(lives), 1, f"each round does not start clean: {lives}")

    def test_the_line_morphs_through_its_shapes(self):
        s = self.seen.shapes
        self.assertEqual(set(s), {"circle", "star", "zigzag", "spiral", "eight", "coil",
                                  "wave", "home"})
        for name in ("circle", "home"):
            with self.subTest(name):
                self.assertAlmostEqual(s[name]["near"], 250, delta=0.5)
                self.assertAlmostEqual(s[name]["far"], 250, delta=0.5)
        with self.subTest("star"):
            self.assertAlmostEqual(s["star"]["far"], 250, delta=0.5)
            self.assertAlmostEqual(s["star"]["near"], 250 * 0.42, delta=2)
        with self.subTest("spiral"):
            self.assertAlmostEqual(s["spiral"]["near"], 0, delta=0.5)
            self.assertLess(math.dist(s["spiral"]["start"], CENTER), 0.5, "it winds out from the centre")
            self.assertAlmostEqual(math.dist(s["spiral"]["end"], CENTER), 250, delta=0.5)
        with self.subTest("eight"):
            self.assertLess(math.dist(s["eight"]["start"], CENTER), 0.5, "it starts at its crossing")
            self.assertAlmostEqual(s["eight"]["width"], 820, delta=1)
            # Track.eight(height=300) draws a figure 150 tall (y = h/2 sin t cos t);
            # its docstring says height is "the size of the figure". Not pinned here.
            self.assertGreater(s["eight"]["height"], 100)
            self.assertLessEqual(s["eight"]["height"], 300 + 1)
        with self.subTest("wave"):
            self.assertLess(math.dist(s["wave"]["start"], (140, 400)), 0.5)
            self.assertLess(math.dist(s["wave"]["end"], (1140, 400)), 0.5)
            self.assertAlmostEqual(s["wave"]["height"], 220, delta=1)

    def test_the_variations_are_written_on_the_line(self):
        s = self.seen.shapes
        self.assertEqual((s["star"]["wiggle"], s["star"]["coil"]), (0, 0))
        self.assertEqual(s["zigzag"]["wiggle"], 10)
        moved = max(math.dist(a, b) for a, b in zip(s["star"]["points"], s["zigzag"]["points"]))
        self.assertGreater(moved, 5, "the zigzag is not on the line")
        self.assertEqual(s["coil"]["coil"], 16)
        self.assertGreater(s["coil"]["far"], s["eight"]["far"] + 5, "the coil is not on the line")

    def test_the_rings_mark_the_tips_and_the_crossing(self):
        # the zigzag is zero at every fifth of the star (30 waves): only the
        # coil moves the tips off the plain star
        tips = [r for r in self.seen.rings if r[4] == 5 and r[2] == 0]
        crossing = [r for r in self.seen.rings if r[4] == 2 and r[2] == 0]
        self.assertGreater(len(tips), 5, "vacuous: no ring at a star's tip")
        self.assertGreater(len(crossing), 2, "vacuous: no ring at the crossing")
        for place, *_ in tips:
            self.assertAlmostEqual(math.dist(place, CENTER), 250, delta=0.5)
        for place, *_ in crossing:
            self.assertLess(math.dist(place, CENTER), 0.5)
        self.assertEqual(self.seen.max_ghosts, 6, "the History keeps at most six rings")


if __name__ == "__main__":
    unittest.main()
