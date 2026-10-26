"""
The claims of ``examples/xyz2.py``, played headless.

The example says: everything that moves is a formula of a few numbers in
``st`` (``@=``) and the storyboard only changes those numbers; two effects in
order (Ring: the big circle draws itself, then two lights run round it
together, against each other, then out of step; Vortex: squares of glass,
each ``STEP`` smaller than the one before, open, ``st.open``, twist,
``st.twist``, further into a star, then each takes its own colour from the
``WHEEL``, ``st.tint``, and the colours slide, ``st.slide``), then it closes
and loops. Each light's ``begin`` / ``end`` is its formula of ``st.lap1`` /
``st.lap2`` / ``st.arc``; each square's ``angle``, ``scale`` and ``fill`` its
formula of ``st.spin``, ``st.twist``, ``st.open``, ``st.tint`` and
``st.slide``, always see-through.

Bug class guarded: **an example that stops doing what its docstring says**
after an engine change (``@=`` formulas on ``begin`` / ``end`` / ``angle`` /
``scale`` / ``fill``, tweens of ``st`` cells and of a Track's ``end``) while
it still builds and runs (``test_scripts_run`` only plays 30 frames); and
**a looping piece that grows each loop** (one more live item, tween or task a
loop).

Run:

    python tests/run_tiers.py focused test_example_xyz2
"""
from __future__ import annotations

import os
import sys
import unittest
import warnings
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from program_support import ProgramRun  # noqa: E402
from program_support import run_registry  # noqa: E402
import scena.process  # noqa: E402
from scena import Color, Square, clock, lerp  # noqa: E402

PATH = "examples/xyz2.py"
SECOND = 60
PLAY = 72           # seconds: the whole loop (~65.5 s) and the next ring drawn
SCENA_DIR = os.path.normcase(os.path.join(ROOT, "scena")) + os.sep
FIELDS = ("lap1", "lap2", "speed1", "speed2", "arc", "open", "twist",
          "spin", "tint", "slide")
EPS = 1e-9


def engine_warnings(caught) -> list:
    """The warnings the engine raised (a SCENA message, or raised from scena/)."""
    return [f"{w.category.__name__}: {w.message}" for w in caught
            if "SCENA" in str(w.message)
            or os.path.normcase(os.path.abspath(w.filename)).startswith(SCENA_DIR)]


def lap_gap(a: float, b: float) -> float:
    """Gap between two positions on a circle, in laps (0 … 0.5)."""
    d = (a - b) % 1
    return min(d, 1 - d)


def color_gap(a, b) -> float:
    return max(abs(x - y) for x, y in zip(a.rgb, b.rgb))


def formula_mismatches(ns, glass) -> list:
    """Every light and square of glass that is not its formula now."""
    st = ns["st"]
    t = clock.time
    out = []
    for name, lap in (("inner", st.lap1), ("outer", st.lap2)):
        light = ns[name]
        for end, want in (("begin", lap % 1), ("end", (lap + st.arc) % 1)):
            if lap_gap(getattr(light, end), want) > 1e-9:
                out.append(f"t={t:.2f} {name}.{end} {getattr(light, end)} != {want}")
    squares = ns["SQUARES"]
    for k, piece in enumerate(glass):
        angle = st.spin + k * st.twist
        if lap_gap(piece.angle / 360, angle / 360) > 1e-9:
            out.append(f"t={t:.2f} square {k} angle {piece.angle} != {angle}")
        if abs(piece.scale - st.open) > 1e-9:
            out.append(f"t={t:.2f} square {k} scale {piece.scale} != open {st.open}")
        tone = ns["WHEEL"].get_color((k / squares + st.slide) % 1)
        want = lerp(ns["BLUE"], tone, st.tint).with_alpha(0.08)
        if color_gap(piece.fill, want) > 1e-6:
            out.append(f"t={t:.2f} square {k} fill {piece.fill} != {want}")
    return out


class TestXyz2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames = []         # one dict per frame
        cls.roster = []         # (t, live roster items), twice a second
        cls.mismatches = []
        cls.checked = 0
        # The tier runs 8 workers next to peer sessions: a resume that takes
        # ~0.1 s idle can pass the 0.5 s watchdog budget there. The budget is
        # test_process's subject, not this piece's.
        with warnings.catch_warnings(record=True) as caught, \
                mock.patch.object(scena.process, "WATCHDOG_RESUME_S", 5.0):
            warnings.simplefilter("always")
            with ProgramRun(PATH, seed=1) as run:
                ns = run.ns
                st = ns["st"]
                glass = [o for o in run_registry().live_objects() if type(o) is Square]
                cls.lengths = None    # read open and steady: a shut square's length is scaled down to a point
                cls.step = ns["STEP"]
                cls.squares = ns["SQUARES"]
                for f in range(PLAY * SECOND):
                    run.step(1)
                    row = {name: float(getattr(st, name)) for name in FIELDS}
                    row["t"] = clock.time
                    row["ring"] = ns["ring"].end
                    cls.frames.append(row)
                    if cls.lengths is None and st.twist > 0:
                        cls.lengths = [g.length for g in glass]
                    if f % 30 == 0:
                        cls.roster.append((clock.time, len(run_registry().live_objects())))
                    if f % 10 == 0:
                        cls.mismatches += formula_mismatches(ns, glass)
                        cls.checked += 1
                cls.author_error = scena.process.last_author_error()
        cls.warned = engine_warnings(caught)

    # -- helpers ------------------------------------------------------------
    def first(self, pred, after: float = 0.0) -> float:
        """Time of the first frame (at or after ``after``) where ``pred(row)``."""
        for row in self.frames:
            if row["t"] >= after and pred(row):
                return row["t"]
        self.fail(f"never reached (after t={after})")

    def during(self, a: float, b: float) -> list:
        return [r for r in self.frames if a <= r["t"] < b]

    def loop_start(self) -> float:
        """When the second loop begins: the storyboard puts tint back to 0."""
        tinted = self.first(lambda r: r["tint"] >= 1 - EPS)
        return self.first(lambda r: r["tint"] == 0, after=tinted)

    # -- the claims ---------------------------------------------------------
    def test_the_whole_loop_plays_without_a_warning(self):
        self.assertEqual(self.warned, [])
        self.assertIsNone(self.author_error)
        self.assertGreater(self.frames[-1]["t"], self.loop_start() + 5,
                           "vacuous: the run did not reach the second loop")

    def test_the_ring_draws_then_the_lights_run(self):
        drawn = self.first(lambda r: r["ring"] >= 1 - EPS)
        before = self.during(0, drawn)
        self.assertTrue(before)
        self.assertEqual({(r["speed1"], r["speed2"]) for r in before}, {(0.0, 0.0)},
                         "a light runs before the ring is drawn")
        ends = [r["ring"] for r in before]
        self.assertEqual(ends, sorted(ends), "the ring does not draw itself forward")
        # together: the same speed, the same way
        together = self.first(lambda r: r["speed1"] == r["speed2"] == 0.15)
        against = self.first(lambda r: r["speed2"] <= -0.15 + EPS, after=together)
        self.assertGreater(against - together, 5)
        for r in self.during(together, together + 5):
            self.assertEqual((r["speed1"], r["speed2"]), (0.15, 0.15))
        # against: the outer light runs backwards while the inner one keeps on
        span = self.during(against, against + 5)
        self.assertEqual({r["speed1"] for r in span}, {0.15})
        self.assertLess(span[-1]["lap2"], span[0]["lap2"], "the outer light does not run back")
        self.assertGreater(span[-1]["lap1"], span[0]["lap1"])
        # out of step: the outer one twice as fast, the lights longer
        step = self.first(lambda r: r["speed2"] >= 0.3 - EPS, after=against)
        self.first(lambda r: r["arc"] >= 0.25 - EPS, after=step)
        self.assertEqual(self.frames[0]["arc"], 0.1)
        # lap1 is the sum of speed1 * dt (the storyboard writes a speed after update: it counts from the next frame)
        for a, b in zip(self.frames, self.frames[1:]):
            if b["t"] > step + 5:
                break
            self.assertAlmostEqual(b["lap1"] - a["lap1"], a["speed1"] * (b["t"] - a["t"]), places=9)

    def test_the_vortex_opens_twists_into_a_star_takes_colour_then_closes(self):
        step = self.first(lambda r: r["speed2"] >= 0.3 - EPS)
        opens = self.first(lambda r: r["open"] > 0)
        self.assertGreater(opens, step, "the vortex opens before the lights ran out of step")
        self.assertEqual({r["open"] for r in self.during(0, opens)}, {0.0})
        opened = self.first(lambda r: r["open"] >= 1 - EPS, after=opens)
        twists = self.first(lambda r: r["twist"] > 0)
        self.assertGreaterEqual(twists, opened, "the squares twist before the vortex is open")
        spiral = self.first(lambda r: r["twist"] >= 7.5 - EPS, after=twists)
        star = self.first(lambda r: r["twist"] > 7.5 + EPS, after=spiral)
        self.assertGreater(star - spiral, 2, "no pause on the spiral")
        starred = self.first(lambda r: r["twist"] >= 30 - EPS, after=star)
        tints = self.first(lambda r: r["tint"] > 0)
        self.assertGreater(tints, starred, "colour before the star")
        self.assertEqual({r["tint"] for r in self.during(0, tints)}, {0.0})
        tinted = self.first(lambda r: r["tint"] >= 1 - EPS, after=tints)
        untwists = self.first(lambda r: r["twist"] < 30 - EPS, after=tinted)
        self.assertGreater(untwists - tinted, 5, "the colours do not get time to slide")
        closes = self.first(lambda r: r["open"] < 1 - EPS, after=untwists)
        self.assertLessEqual(self.first(lambda r: r["twist"] == 0, after=untwists), closes,
                             "the vortex closes before it untwisted")
        self.first(lambda r: r["open"] == 0, after=closes)
        # the whole vortex turns and the colours slide all the time
        for a, b in zip(self.frames, self.frames[1:]):
            self.assertGreater(b["spin"], a["spin"])
            self.assertGreater(b["slide"], a["slide"])

    def test_each_square_smaller_than_the_one_before(self):
        self.assertIsNotNone(self.lengths, "vacuous: the vortex never opened")
        self.assertEqual(len(self.lengths), self.squares)
        for k, length in enumerate(self.lengths):
            self.assertAlmostEqual(length, 300 - self.step * k, places=6)

    def test_the_lights_and_the_glass_are_their_formulas(self):
        self.assertGreater(self.checked, 400)
        self.assertEqual(self.mismatches[:5], [])

    def test_then_it_loops_and_a_loop_leaves_nothing_behind(self):
        again = self.loop_start()
        row = next(r for r in self.frames if r["t"] == again)
        self.assertEqual({row[n] for n in ("lap1", "lap2", "speed1", "speed2", "open", "twist", "tint")}, {0.0})
        self.assertEqual(row["arc"], 0.1)
        self.assertLess(row["ring"], 0.01)
        self.first(lambda r: r["ring"] >= 1 - EPS, after=again)
        self.first(lambda r: r["speed1"] == r["speed2"] == 0.15, after=again)
        one = [n for t, n in self.roster if 1 <= t < 6]
        two = [n for t, n in self.roster if again + 1 <= t < again + 6]
        self.assertTrue(one and two, "vacuous: no second-loop samples")
        self.assertEqual(max(two), max(one), "the second loop has more live items than the first")
        self.assertEqual(max(n for t, n in self.roster), max(one), "the piece grows inside a loop")


if __name__ == "__main__":
    unittest.main()
