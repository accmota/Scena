"""
The claims of ``examples/xyz.py``, played headless.

The example says: everything that moves is a formula of a few numbers in
``st`` (``@=``) and the storyboard only changes those numbers; four parts in
order (I Ring: the big circle draws itself, then two lights run round it
together, against each other, then out of step; II Rosette: the glass opens,
``st.bloom``, and twists; III Turtles: six turtle walks draw themselves one
after another, ``end`` to 1, then retract, ``begin`` to 1; IV Rings: the
rings inside the ring light up, ``ring_arc``, then fall out of phase,
``phase``, turn at different speeds, ``spread``, and take colour, ``tint``),
then it loops. Each light's ``begin`` / ``end`` is its formula of
``st.lap1`` / ``st.lap2`` / ``st.arc``; each inner ring's of ``st.lap``,
``st.phase``, ``st.spread``, ``st.ring_arc`` and ``st.tint``.

Bug class guarded: **an example that stops doing what its docstring says**
after an engine change (``@=`` formulas on ``begin`` / ``end`` / ``color``,
tweens of ``st`` cells and of a Track's ``begin`` / ``end``) while it still
builds and runs (``test_scripts_run`` only plays 30 frames); and **a looping
piece that grows each loop** (one more live item, tween or task a loop).

Run:

    python tests/run_tiers.py focused test_example_xyz
"""
from __future__ import annotations

import math
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
from scena import Color, RegularPolygon, Square, Track, Triangle, clock, lerp  # noqa: E402

PATH = "examples/xyz.py"
SECOND = 60
PLAY = 100          # seconds: the whole loop (~92.4 s) and the next ring drawn
SCENA_DIR = os.path.normcase(os.path.join(ROOT, "scena")) + os.sep
FIELDS = ("lap1", "lap2", "speed1", "speed2", "arc", "bloom", "twist",
          "lap", "phase", "spread", "ring_arc", "tint")
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


def formula_mismatches(ns, inner_rings, glass) -> list:
    """Every light, inner ring and piece of glass that is not its formula now."""
    st = ns["st"]
    t = clock.time
    out = []
    for name, lap in (("inner", st.lap1), ("outer", st.lap2)):
        light = ns[name]
        for end, want in (("begin", lap % 1), ("end", (lap + st.arc) % 1)):
            if lap_gap(getattr(light, end), want) > 1e-9:
                out.append(f"t={t:.2f} {name}.{end} {getattr(light, end)} != {want}")
    rings = ns["RINGS"]
    if len(inner_rings) != rings:
        return out + [f"{len(inner_rings)} inner rings"]
    for k, circle in enumerate(inner_rings):
        head = st.lap * (1 + st.spread * k) - st.phase * k
        for end, want in (("begin", head % 1), ("end", (head + st.ring_arc) % 1)):
            if lap_gap(getattr(circle, end), want) > 1e-9:
                out.append(f"t={t:.2f} ring {k}.{end} {getattr(circle, end)} != {want}")
        want = lerp(Color("white"), ns["WHEEL"].get_color(k / rings), st.tint)
        if color_gap(circle.color, want) > 1e-6:
            out.append(f"t={t:.2f} ring {k} color {circle.color} != {want}")
    for piece, reach in glass:
        if abs(piece.scale - st.bloom) > 1e-9:
            out.append(f"t={t:.2f} glass scale {piece.scale} != bloom {st.bloom}")
        far = math.hypot(piece.center.x, piece.center.y)
        if abs(far - abs(st.bloom) * reach) > 1e-6:
            out.append(f"t={t:.2f} glass at {far}, not {st.bloom} * {reach}")
    return out


class TestXyz(unittest.TestCase):
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
                walks = ns["walks"]
                named = {id(ns[n]) for n in ("ring", "inner", "outer")} | {id(w) for w in walks}
                live = run_registry().live_objects()      # in the order the file made them
                inner_rings = [o for o in live if type(o) is Track and id(o) not in named]
                reach = {Square: 95, Triangle: 55, RegularPolygon: 28}
                glass = [(o, reach[type(o)]) for o in live if type(o) in reach]
                cls.glass = len(glass)
                cls.inner_rings = len(inner_rings)
                for f in range(PLAY * SECOND):
                    run.step(1)
                    row = {name: float(getattr(st, name)) for name in FIELDS}
                    row["t"] = clock.time
                    row["ring"] = ns["ring"].end
                    row["walk_end"] = [w.end for w in walks]
                    row["walk_begin"] = [w.begin for w in walks]
                    cls.frames.append(row)
                    if f % 30 == 0:
                        cls.roster.append((clock.time, len(run_registry().live_objects())))
                    if f % 10 == 0:
                        cls.mismatches += formula_mismatches(ns, inner_rings, glass)
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

    def test_part_one_the_ring_draws_then_the_lights_run(self):
        drawn = self.first(lambda r: r["ring"] >= 1 - EPS)
        before = self.during(0, drawn)
        self.assertTrue(before)
        self.assertEqual({(r["speed1"], r["speed2"]) for r in before}, {(0.0, 0.0)},
                         "a light runs before the ring is drawn")
        ends = [r["ring"] for r in before]
        self.assertEqual(ends, sorted(ends), "the ring does not draw itself forward")
        self.assertGreater(drawn, 2, "the ring is drawn at once")
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

    def test_four_parts_in_order_then_it_loops(self):
        step = self.first(lambda r: r["speed2"] >= 0.3 - EPS)
        # II Rosette: shut until the lights ran out of step, then it opens and twists
        opens = self.first(lambda r: r["bloom"] > 0)
        self.assertGreater(opens, step)
        self.first(lambda r: r["bloom"] >= 0.999, after=opens)
        twisted = self.first(lambda r: r["twist"] >= 90 - EPS, after=opens)
        # III Turtles: six walks draw themselves, one after another, then retract
        drawn = []
        for i in range(6):
            start = self.first(lambda r: r["walk_end"][i] > 0)
            self.assertGreaterEqual(start, twisted, f"walk {i} draws before the rosette twisted")
            drawn.append(self.first(lambda r: r["walk_end"][i] >= 1 - EPS, after=start))
        self.assertEqual(drawn, sorted(drawn))
        self.assertEqual(len(set(drawn)), 6, "two walks draw at once")
        gone = []
        for i in range(6):
            start = self.first(lambda r: r["walk_begin"][i] > 0)
            self.assertGreater(start, max(drawn), f"walk {i} retracts before every walk is drawn")
            gone.append(self.first(lambda r: r["walk_begin"][i] >= 1 - EPS, after=start))
        self.assertEqual(gone, sorted(gone))
        # IV Rings: lit, out of phase, different speeds and colours, in that order
        lit = self.first(lambda r: r["ring_arc"] > 0)
        self.assertGreaterEqual(lit, max(gone) - 3.1)       # with the rosette closing
        self.assertEqual([r for r in self.during(0, lit) if r["phase"] or r["spread"] or r["tint"]], [])
        lit_full = self.first(lambda r: r["ring_arc"] >= 0.15 - EPS, after=lit)
        phased = self.first(lambda r: r["phase"] > 0, after=lit_full)
        phase_full = self.first(lambda r: r["phase"] >= 0.02 - EPS, after=phased)
        spread = self.first(lambda r: r["spread"] > 0, after=phase_full)
        self.assertGreaterEqual(self.first(lambda r: r["tint"] > 0), spread)
        self.first(lambda r: r["spread"] >= 0.08 - EPS, after=spread)
        tinted = self.first(lambda r: r["tint"] >= 1 - EPS, after=spread)
        # then it loops: every number back to its start, and the ring draws again
        again = self.loop_start()
        self.assertGreater(again, tinted)
        row = next(r for r in self.frames if r["t"] == again)
        self.assertEqual({row[n] for n in FIELDS if n not in ("arc", "lap")}, {0.0})
        self.assertEqual(row["arc"], 0.1)
        self.assertLess(row["ring"], 0.01)
        self.assertEqual(set(row["walk_end"]) | set(row["walk_begin"]), {0.0})
        self.first(lambda r: r["ring"] >= 1 - EPS, after=again)
        self.first(lambda r: r["speed1"] == r["speed2"] == 0.15, after=again)

    def test_the_lights_the_rings_and_the_glass_are_their_formulas(self):
        self.assertEqual((self.inner_rings, self.glass), (22, 36))
        self.assertGreater(self.checked, 500)
        self.assertEqual(self.mismatches[:5], [])

    def test_a_loop_leaves_nothing_behind(self):
        again = self.loop_start()
        one = [n for t, n in self.roster if 1 <= t < 7]
        two = [n for t, n in self.roster if again + 1 <= t < again + 7]
        self.assertTrue(one and two, "vacuous: no second-loop samples")
        self.assertEqual(max(two), max(one), "the second loop has more live items than the first")
        self.assertEqual(max(n for t, n in self.roster), max(one), "the piece grows inside a loop")


if __name__ == "__main__":
    unittest.main()
