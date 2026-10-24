"""
The claims of ``examples/string_theory.py``, played headless.

The example says: four parts in order, then it loops (~85 s): I Times table
(point i joins point k·i on a circle, k climbs 2 → 99), II Fans (two fans of
lines cross), III Lissajous (strings whose two ends ride sines with drifting
ratios), IV Curves; each part starts in a clean act. User decisions guarded
here: a card warns about flashing lights first and SPACE skips it; the Prism
and the Chroma (split colours) are on only for a few seconds each, not the
whole piece; the file stays within 200 lines.

Bug class guarded: **an example that stops doing what its docstring says**
after an engine change (``Line`` ends as formulas, ``change_act`` clearing
the last part, ``after()`` timers that remove an effect, ``race`` / ``until``
with ``keyp.once``) while it still builds and runs (``test_scripts_run`` only
plays 30 frames).

Run:

    python tests/run_tiers.py focused test_example_string_theory
"""
from __future__ import annotations

import math
import os
import re
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
from scena import Line, Text, canvas, clock  # noqa: E402

PATH = "examples/string_theory.py"
SECOND = 60
PLAY = 100          # seconds: the card, the whole loop (~84 s) and part I of the next
SCENA_DIR = os.path.normcase(os.path.join(ROOT, "scena")) + os.sep
CAPTION = re.compile(r"^(I|II|III|IV)  ")
CARD = "flashing lights"


def engine_warnings(caught) -> list:
    """The warnings the engine raised (a SCENA message, or raised from scena/)."""
    return [f"{w.category.__name__}: {w.message}" for w in caught
            if "SCENA" in str(w.message)
            or os.path.normcase(os.path.abspath(w.filename)).startswith(SCENA_DIR)]


def texts() -> list:
    return [o.text for o in run_registry().live_objects() if isinstance(o, Text) and o.is_alive]


def caption() -> str:
    """The part now on screen: "I" … "IV", "card" or ""."""
    found = texts()
    for s in found:
        m = CAPTION.match(s)
        if m:
            return m.group(1)
    return "card" if any(CARD in s for s in found) else ""


def lines() -> list:
    """The live lines, in the order they were made."""
    return [o for o in run_registry().live_objects() if isinstance(o, Line) and o.is_alive]


def tap(run, key):
    run.key_down(key)
    run.step(1)
    run.key_up(key)
    run.step(1)


class TestStringTheory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames = []         # one dict per frame (the part: every 5 frames)
        cls.table = []          # mismatches of the times table
        cls.stops = set()       # whole k at which the table was checked
        cls.strings = []        # mismatches of the Lissajous strings
        cls.string_checks = 0
        cls.counts = {}         # part -> line counts seen
        # The tier runs 8 workers next to peer sessions: building a part (~0.1 s
        # idle) can pass the 0.5 s watchdog budget there. The budget is
        # test_process's subject, not this piece's.
        with warnings.catch_warnings(record=True) as caught, \
                mock.patch.object(scena.process, "WATCHDOG_RESUME_S", 5.0):
            warnings.simplefilter("always")
            with ProgramRun(PATH, seed=1) as run:
                ns = run.ns
                st = ns["st"]
                now = ""
                for f in range(PLAY * SECOND):
                    run.step(1)
                    if f % 5 == 0:
                        now = caption()
                    row = {"t": clock.time, "part": now,
                           "effects": {type(e).__name__ for e in canvas.effects}}
                    if f % 30 == 0:
                        row["live"] = len(run_registry().live_objects())
                    cls.frames.append(row)
                    if f % 30 == 0 and now in ("I", "II", "III", "IV"):
                        cls.counts.setdefault(now, set()).add(len(lines()))
                    if now == "I" and hasattr(st, "k") and st.k == round(st.k) and st.k not in cls.stops:
                        cls.stops.add(st.k)
                        cls.table += cls.table_mismatches(ns)
                    if now == "III" and f % 10 == 0:
                        cls.strings += cls.string_mismatches(ns)
                        cls.string_checks += 1
                cls.author_error = scena.process.last_author_error()
        cls.warned = engine_warnings(caught)

    @staticmethod
    def table_mismatches(ns) -> list:
        """Chord i joins point i to point k·i mod N (k whole, at a stop)."""
        n, cx, cy, r = ns["N"], ns["CX"], ns["CY"], ns["R"]
        k = int(ns["st"].k)

        def point(m):
            return (cx + r * math.cos(2 * math.pi * m / n), cy + r * math.sin(2 * math.pi * m / n))
        chords = lines()
        if len(chords) != n:
            return [f"k={k}: {len(chords)} chords"]
        out = []
        for i, chord in enumerate(chords):
            for end, m in ((chord.p1, i), (chord.p2, k * i % n)):
                if math.dist((end.x, end.y), point(m)) > 1e-6:
                    out.append(f"k={k} chord {i}: an end at {end.x, end.y}, not point {m}")
        return out

    @staticmethod
    def string_mismatches(ns) -> list:
        """String j joins the curve at u = j·π/48 to the curve 0.8 further on."""
        strings = lines()
        if len(strings) != 96:
            return [f"t={clock.time:.2f}: {len(strings)} strings"]
        out = []
        for j, s in enumerate(strings):
            u = j * math.pi / 48
            for end, want in ((s.p1, ns["lissajous"](u)), (s.p2, ns["lissajous"](u + 0.8))):
                if math.dist((end.x, end.y), want) > 1e-6:
                    out.append(f"t={clock.time:.2f} string {j}: an end at {end.x, end.y}, not {want}")
        return out

    # -- helpers ------------------------------------------------------------
    def first(self, pred, after: float = 0.0) -> float:
        for row in self.frames:
            if row["t"] >= after and pred(row):
                return row["t"]
        self.fail(f"never reached (after t={after})")

    def loop_start(self) -> float:
        """When part I comes back after part IV."""
        return self.first(lambda r: r["part"] == "I", after=self.first(lambda r: r["part"] == "IV"))

    # -- the claims ---------------------------------------------------------
    def test_the_file_is_at_most_200_lines(self):
        with open(os.path.normpath(os.path.join(ROOT, *PATH.split("/"))), encoding="utf-8") as fh:
            self.assertLessEqual(len(fh.read().splitlines()), 200)

    def test_the_whole_loop_plays_without_a_warning(self):
        self.assertEqual(self.warned, [])
        self.assertIsNone(self.author_error)

    def test_four_parts_in_order_then_it_loops(self):
        order = []
        for row in self.frames:
            if row["part"] and (not order or order[-1] != row["part"]):
                order.append(row["part"])
        self.assertEqual(order, ["card", "I", "II", "III", "IV", "I"])
        again = self.loop_start()
        start = self.first(lambda r: r["part"] == "I")
        self.assertTrue(75 < again - start < 95, f"a loop lasts {again - start:.1f} s, not ~85")
        # each part starts in a clean act: only its own lines
        self.assertEqual(self.counts["I"], {160})
        self.assertEqual(self.counts["II"], {144})
        self.assertEqual(self.counts["III"], {96})
        self.assertEqual(self.counts["IV"], {0})

    def test_the_card_comes_first_and_waits_its_time(self):
        card = [r["t"] for r in self.frames if r["part"] == "card"]
        self.assertTrue(card)
        self.assertLess(min(card), 0.2)
        self.assertTrue(3.3 < max(card) < 3.7, f"the card left at {max(card):.2f} s")

    def test_space_skips_the_card(self):
        with mock.patch.object(scena.process, "WATCHDOG_RESUME_S", 5.0), \
                ProgramRun(PATH, seed=1) as run:
            run.step(SECOND)
            self.assertEqual(caption(), "card")
            tap(run, "SPACE")
            run.step(2)
            self.assertEqual(caption(), "I", "SPACE did not skip the card")
            self.assertLess(clock.time, 1.2)
            self.assertTrue(hasattr(run.ns["st"], "k"), "part I did not start")

    def test_the_split_colours_come_only_for_a_few_seconds(self):
        start = self.first(lambda r: r["part"] == "I")
        loop = [r for r in self.frames if start <= r["t"] < self.loop_start()]
        for effect, seconds, where in (("Prism", 5, "I"), ("Chroma", 3, "II")):
            on = [r for r in loop if effect in r["effects"]]
            self.assertTrue(on, f"vacuous: no {effect}")
            self.assertLessEqual(len(on), seconds * SECOND + 2, f"the {effect} stays on too long")
            self.assertLess(len(on) / len(loop), 0.1)
            self.assertEqual({r["part"] for r in on}, {where}, effect)
            # one stretch, not a flicker
            ts = [r["t"] for r in on]
            self.assertAlmostEqual(ts[-1] - ts[0], (len(on) - 1) / SECOND, delta=1e-6)

    def test_chord_i_joins_point_i_to_point_k_times_i(self):
        self.assertTrue(set(map(int, self.stops)) >= {3, 4, 5, 7, 10, 21, 34, 51, 99},
                        sorted(self.stops))
        self.assertEqual(self.table[:5], [])

    def test_the_lissajous_strings_ride_the_curve(self):
        self.assertGreater(self.string_checks, 50)
        self.assertEqual(self.strings[:5], [])

    def test_a_loop_leaves_nothing_behind(self):
        start = self.first(lambda r: r["part"] == "I")
        again = self.loop_start()
        one = [r["live"] for r in self.frames if "live" in r and start + 1 <= r["t"] < start + 10]
        two = [r["live"] for r in self.frames if "live" in r and again + 1 <= r["t"] < again + 10]
        self.assertTrue(one and two, "vacuous: no second-loop samples")
        self.assertEqual(max(two), max(one), "the second loop has more live items than the first")


if __name__ == "__main__":
    unittest.main()
