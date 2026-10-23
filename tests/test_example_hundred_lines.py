"""
The claims of ``examples/hundred_lines.py``, played headless.

The example says: a whole intro in exactly 100 lines; four parts in order
(I Bloom: the hexagons open out of a point under the title; II Vortex: they
twist into a spiral and the petals spring out; III Mandala: a Kaleidoscope
folds the spiral while it winds the other way; IV Tunnel: the centres trail
round, it spins up, falls into a point and bursts), then it loops; everything
that moves is a formula of the clock and ``st``. User decisions guarded here:
the music drives the strokes only under the title (``st.beat`` goes to 0 when
the title leaves, and the stroke pulse then stays at 0 even on a loud kick),
and the Prism (split colours) covers only part of the piece.

Bug class guarded: **an example that stops doing what its docstring says**
after an engine change (``@=`` formulas, tweens of ``st`` cells, post effects)
while it still builds and runs (``test_scripts_run`` only plays 30 frames);
and **a looping piece that grows each loop**: ``dissolve_out`` only hides a
shape, so the title made in each loop stayed alive (one more Text a loop,
found 2026-10-23; the title now destroys itself when it has dissolved).

The music is replaced by a constant loud kick (a fake ``audio`` whose
spectrum is full): the pulse claim is then deterministic, and stricter than
with the real song.

Run:

    python tests/run_tiers.py focused test_example_hundred_lines
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
from hypothesis_support import registry  # noqa: E402
import scena.process  # noqa: E402
from scena import RegularPolygon, Text, Triangle, canvas, clock, vec_from_angle  # noqa: E402

PATH = "examples/hundred_lines.py"
SECOND = 60
PLAY = 80           # seconds: the whole loop (~57 s) and the first part of the next
TITLE = "100 LINES OF SCENA"
SCENA_DIR = os.path.normcase(os.path.join(ROOT, "scena")) + os.sep
FIELDS = ("open", "twist", "bend", "petals", "spin", "pulse", "beat")


class LoudKick:
    """Stands in for ``audio``: every band at full level, every frame."""

    def spectrum(self, bins: int = 8) -> list:
        return [1.0] * bins


def engine_warnings(caught) -> list:
    """The warnings the engine raised (a SCENA message, or raised from scena/)."""
    return [f"{w.category.__name__}: {w.message}" for w in caught
            if "SCENA" in str(w.message)
            or os.path.normcase(os.path.abspath(w.filename)).startswith(SCENA_DIR)]


def turned(a: float, b: float) -> float:
    """Gap between two angles in degrees, in 0 … 180."""
    return abs((a - b + 180) % 360 - 180)


def formula_mismatches(ns) -> list:
    """Every hexagon and petal where the drawing is not its formula now."""
    st = ns["st"]
    t = clock.time
    out = []
    shapes = registry().live_objects()
    hexagons = [o for o in shapes if type(o) is RegularPolygon]
    petals = [o for o in shapes if isinstance(o, Triangle)]
    if (len(hexagons), len(petals)) != (19, 24):
        return [f"{len(hexagons)} hexagons and {len(petals)} petals"]
    for i, h in enumerate(hexagons):
        where = vec_from_angle(t * 70 - i * 12, st.bend * (220 - 11 * i))
        checks = (
            ("radius", h.radius, st.open * (14 + 17 * i)),
            ("x", h.center.x, where.x),
            ("y", h.center.y, where.y),
            ("line_width", h.line_width, 3 + 4 * st.pulse),
        )
        for name, got, want in checks:
            if abs(got - want) > 1e-6:
                out.append(f"t={t:.2f} hexagon {i} {name} {got} != {want}")
        if turned(h.angle, t * 20 * st.spin + i * st.twist) > 1e-6:
            out.append(f"t={t:.2f} hexagon {i} angle {h.angle}")
        if len(h.points) != 6:
            out.append(f"t={t:.2f} hexagon {i} has {len(h.points)} corners")
    for k, p in enumerate(petals):
        turn = k * 15 + t * 15 * st.spin
        where = vec_from_angle(turn, st.petals * st.open * 340)
        if math.dist((p.center.x, p.center.y), (where.x, where.y)) > 1e-6:
            out.append(f"t={t:.2f} petal {k} at {p.center.x, p.center.y}, not {where.x, where.y}")
        if turned(p.angle, turn + 90) > 1e-6:
            out.append(f"t={t:.2f} petal {k} angle {p.angle}")
    return out


class TestHundredLines(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames = []         # one dict per frame
        cls.titles = []         # (t, live title Texts), four times a second
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
                ns["audio"] = LoudKick()
                st = ns["st"]
                for f in range(PLAY * SECOND):
                    run.step(1)
                    row = {name: float(getattr(st, name)) for name in FIELDS}
                    row["t"] = clock.time
                    row["effects"] = {type(e).__name__ for e in canvas.effects}
                    cls.frames.append(row)
                    if f % 15 == 0:
                        cls.titles.append((clock.time, sum(
                            1 for o in registry().live_objects()
                            if isinstance(o, Text) and o.is_alive and o.text == TITLE)))
                    if f % 30 == 0:
                        cls.roster.append((clock.time, len(registry().live_objects())))
                    if f % 20 == 0:
                        cls.mismatches += formula_mismatches(ns)
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

    def loop_start(self) -> float:
        """When the second loop begins: the storyboard puts bend back to 0."""
        t_bent = self.first(lambda r: r["bend"] >= 1)
        return self.first(lambda r: r["bend"] == 0, after=t_bent)

    # -- the claims ---------------------------------------------------------
    def test_the_file_is_exactly_100_lines(self):
        with open(os.path.normpath(os.path.join(ROOT, *PATH.split("/"))), encoding="utf-8") as fh:
            self.assertEqual(len(fh.read().splitlines()), 100)

    def test_the_whole_loop_plays_without_a_warning(self):
        self.assertEqual(self.warned, [])
        self.assertIsNone(self.author_error)
        self.assertGreater(self.frames[-1]["t"], self.loop_start() + 10,
                           "vacuous: the run did not reach the second loop")

    def test_the_four_parts_come_in_order_then_it_loops(self):
        bloom = self.first(lambda r: r["open"] == 1)     # the tween is over
        vortex = self.first(lambda r: r["twist"] >= 7.999, after=bloom)
        self.assertLess(self.first(lambda r: r["petals"] >= 0.999, after=bloom), vortex,
                        "the petals did not spring out in the Vortex")
        mandala = self.first(lambda r: "Kaleidoscope" in r["effects"], after=vortex)
        wound = self.first(lambda r: r["twist"] <= -7.999, after=mandala)
        tunnel = self.first(lambda r: r["bend"] >= 0.999, after=wound)
        spun = self.first(lambda r: r["spin"] >= 7.999, after=tunnel)
        shut = self.first(lambda r: r["open"] == 0, after=spun)
        again = self.loop_start()
        self.assertLess(shut, again)
        self.assertLess(again, 60, "the loop is far longer than the storyboard")
        self.first(lambda r: r["open"] >= 0.999, after=again)       # Bloom again
        # the mirror folds only the Mandala: off before the tunnel bends
        mirror = [r["t"] for r in self.frames if "Kaleidoscope" in r["effects"] and r["t"] < again]
        self.assertTrue(mirror)
        self.assertGreater(min(mirror), vortex)
        self.assertLess(max(mirror), self.first(lambda r: r["bend"] > 0))

    def test_the_title_stands_only_over_the_bloom_and_one_at_a_time(self):
        bloom = self.first(lambda r: r["open"] == 1)     # the tween is over
        vortex = self.first(lambda r: r["twist"] >= 7.999)
        self.assertTrue(any(n == 1 for t, n in self.titles if t < bloom))
        self.assertEqual([t for t, n in self.titles if n > 1], [], "a title from an earlier loop is alive")
        self.assertEqual([t for t, n in self.titles if bloom + 2 < t < vortex and n], [],
                         "the title is alive after it dissolved")

    def test_the_music_drives_the_strokes_only_under_the_title(self):
        quiet = self.first(lambda r: r["beat"] == 0)
        bloom = self.first(lambda r: r["open"] == 1)     # the tween is over
        self.assertLess(quiet, bloom + 2, "st.beat did not fall when the title left")
        under = [r["pulse"] for r in self.frames if r["t"] < bloom]
        self.assertGreater(max(under), 1, "vacuous: the kick never pulsed the strokes")
        again = self.loop_start()
        later = [r for r in self.frames if quiet + 0.6 <= r["t"] < again]
        self.assertTrue(later)
        self.assertEqual({r["pulse"] for r in later}, {0.0},
                         "the strokes still follow the music after the title left")
        self.assertEqual(self.frames[[r["t"] for r in self.frames].index(again)]["beat"], 1)

    def test_the_prism_covers_only_part_of_the_piece(self):
        again = self.loop_start()
        loop = [r for r in self.frames if r["t"] < again]
        prism = [r for r in loop if "Prism" in r["effects"]]
        self.assertTrue(prism, "vacuous: no Prism")
        self.assertLess(len(prism) / len(loop), 0.15, "the Prism is on for most of the piece")
        # it splits the colours while the tunnel bends, no longer
        for r in prism:
            self.assertLess(r["bend"], 1)
            self.assertEqual(r["spin"], 1)
            self.assertLessEqual(r["twist"], -7.999)

    def test_the_shapes_are_their_formulas(self):
        self.assertGreater(self.checked, 200)
        self.assertEqual(self.mismatches[:5], [])

    def test_a_loop_leaves_nothing_behind(self):
        again = self.loop_start()
        one = [n for t, n in self.roster if 1 <= t < 15]
        two = [n for t, n in self.roster if again + 0.5 <= t < again + 14.5]
        self.assertTrue(one and two, "vacuous: no second-loop samples")
        self.assertEqual(max(two), max(one), "the second loop has more live items than the first")

if __name__ == "__main__":
    unittest.main()
