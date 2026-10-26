"""
The claims of ``examples/pendulums.py``, played headless.

The example says: ``COUNT`` pendulums hang in a row; in one cycle
(``CYCLE`` seconds) pendulum k swings ``FIRST + k`` times, so let go
together they drift apart and all meet again after ``CYCLE`` seconds;
nothing steers them, each keeps its own beat. Each bob plays a note of the
pentatonic ``SCALE`` as it crosses the middle going out, and only once they
are let go (``st.notes``). After the first cycle the row curls into a ring
(``st.bend`` 1: every bob on radius 270, swinging in and out) for a second
cycle, then it uncurls, the bobs go and the piece loops.

Bug class guarded: **an example that stops doing what its docstring says**
after an engine change (formula arguments ``p1=lambda``, a Track through
moving points, tweens of ``st``, group verbs) while it still builds and runs
(``test_scripts_run`` only plays 30 frames); a docstring whose numbers drift
from the code (it said the first swings 40 times and the last 63, with
FIRST = 5); **a loop that is not the same piece again** (the stems were
hidden for the ring and never shown again: from the second loop on the bobs
swung without them); and **a looping piece that grows each loop**.

``play_sound`` is replaced in the program's namespace by a recorder (update
finds it by name), so the notes are counted, with their pitch, and no sound
is loaded.

Run:

    python tests/run_tiers.py focused test_example_pendulums
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
from scena import clock, group  # noqa: E402

PATH = "examples/pendulums.py"
SECOND = 60
PLAY = 186          # seconds: the whole loop (~176 s) and the next let-go
SCENA_DIR = os.path.normcase(os.path.join(ROOT, "scena")) + os.sep
EPS = 1e-9


def engine_warnings(caught) -> list:
    """The warnings the engine raised (a SCENA message, or raised from scena/)."""
    return [f"{w.category.__name__}: {w.message}" for w in caught
            if "SCENA" in str(w.message)
            or os.path.normcase(os.path.abspath(w.filename)).startswith(SCENA_DIR)]


def source() -> str:
    with open(os.path.normpath(os.path.join(ROOT, *PATH.split("/"))), encoding="utf-8") as fh:
        return fh.read()


def turned(a: float, b: float) -> float:
    """Gap between two angles in degrees, in 0 … 180."""
    return abs((a - b + 180) % 360 - 180)


class TestPendulums(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames = []         # one dict per frame
        cls.notes = []          # (t, st.time, st.notes, pitch), one per play_sound
        cls.roster = []         # (t, live roster items), twice a second
        cls.near = []           # (st.time, swing, [bob offset from rest]) close to a meeting
        cls.ring = []           # (st.swing, [(|centre|, angle, swing(k))]) on the ring
        with warnings.catch_warnings(record=True) as caught, \
                mock.patch.object(scena.process, "WATCHDOG_RESUME_S", 5.0):
            warnings.simplefilter("always")
            with ProgramRun(PATH, seed=1) as run:
                ns = run.ns
                st = ns["st"]
                cls.count, cls.first_swings, cls.cycle = ns["COUNT"], ns["FIRST"], ns["CYCLE"]
                cls.scale = list(ns["SCALE"])

                def play_sound(path, pitch=1.0, volume=1.0, pan=0.0):
                    cls.notes.append((clock.time, float(st.time), bool(st.notes), pitch))

                ns["play_sound"] = play_sound
                bobs, rest, swing = ns["bobs"], ns["rest"], ns["swing"]
                stems = list(group["line_bars"])
                cls.stems = len(stems)
                count = cls.count
                for f in range(PLAY * SECOND):
                    run.step(1)
                    row = {"t": clock.time, "time": float(st.time), "swing": float(st.swing),
                           "bend": float(st.bend), "notes": bool(st.notes),
                           "signs": [swing(k) > 0 for k in range(count)]}
                    if f % 30 == 0:
                        row["stems"] = sum(1 for s in stems if s.visible)
                        row["bobs"] = sum(1 for b in bobs if b.visible)
                        cls.roster.append((clock.time, len(run_registry().live_objects())))
                    cls.frames.append(row)
                    near = min(abs(st.time - m * cls.cycle) for m in (1, 2))
                    if st.swing > 100 and (near < 0.05 or abs(st.time % cls.cycle - 0.37 * cls.cycle) < 0.02):
                        cls.near.append((float(st.time), float(st.swing),
                                         [math.dist((bobs[k].center.x, bobs[k].center.y), (rest(k).x, rest(k).y))
                                          for k in range(count)]))
                    if st.bend == 1 and f % 30 == 0:
                        cls.ring.append((float(st.swing), [
                            (math.hypot(bobs[k].center.x, bobs[k].center.y),
                             math.degrees(math.atan2(bobs[k].center.y, bobs[k].center.x)),
                             swing(k)) for k in range(count)]))
                cls.author_error = scena.process.last_author_error()
        cls.warned = engine_warnings(caught)

    # -- helpers ------------------------------------------------------------
    def first(self, pred, after: float = 0.0) -> float:
        """Time of the first frame (at or after ``after``) where ``pred(row)``."""
        for row in self.frames:
            if row["t"] >= after and pred(row):
                return row["t"]
        self.fail(f"never reached (after t={after})")

    def let_go(self, after: float = 0.0) -> float:
        """When the pendulums are let go (st.notes turns on)."""
        return self.first(lambda r: r["notes"], after=after)

    def loop_start(self) -> float:
        """When the second loop lets the pendulums go."""
        quiet = self.first(lambda r: not r["notes"], after=self.let_go())
        return self.let_go(after=quiet)

    def pitch(self, k: int) -> float:
        return 2 ** ((self.scale[k % 5] + 12 * (k // 5) - 12) / 12)

    # -- the claims ---------------------------------------------------------
    def test_the_whole_loop_plays_without_a_warning(self):
        self.assertEqual(self.warned, [])
        self.assertIsNone(self.author_error)
        self.assertGreater(self.frames[-1]["t"], self.loop_start() + 5,
                           "vacuous: the run did not reach the second loop")

    def test_the_docstring_counts_the_swings_of_the_code(self):
        said = re.search(r"the first swings (\d+)\s+times, the next (\d+), the next (\d+) … the last (\d+)",
                         source())
        self.assertIsNotNone(said, "the docstring no longer counts the swings")
        last = self.first_swings + self.count - 1
        self.assertEqual(tuple(int(n) for n in said.groups()),
                         (self.first_swings, self.first_swings + 1, self.first_swings + 2, last))

    def test_pendulum_k_swings_first_plus_k_times_a_cycle(self):
        """Upward zero crossings of swing(k) over the first cycle after the let-go."""
        dt = 1 / SECOND
        again = self.loop_start()
        cycle = [r for r in self.frames
                 if r["t"] < again and r["notes"] and 1.5 * dt < r["time"] <= self.cycle + 0.5]
        self.assertGreater(cycle[-1]["time"], self.cycle, "vacuous: the cycle did not end")
        for k in range(self.count):
            ups = sum(1 for a, b in zip(cycle, cycle[1:]) if b["signs"][k] and not a["signs"][k])
            self.assertEqual(ups, self.first_swings + k, f"pendulum {k}")

    def test_each_crossing_plays_its_note(self):
        """The same count as notes, each pendulum at its pitch of SCALE."""
        dt = 1 / SECOND
        pitches = [self.pitch(k) for k in range(self.count)]
        self.assertEqual(len(set(pitches)), self.count)
        for which in (1, 2):
            a, b = (which - 1) * self.cycle, which * self.cycle
            heard = [p for t, time, on, p in self.notes
                     if t < self.loop_start() and a + 1.5 * dt < time <= b + 0.5]
            for k in range(self.count):
                got = sum(1 for p in heard if abs(p - pitches[k]) < 1e-12)
                self.assertEqual(got, self.first_swings + k, f"cycle {which}: pendulum {k}'s notes")
            self.assertEqual(len(heard), sum(self.first_swings + k for k in range(self.count)),
                             "a note at a pitch no pendulum has")

    def test_notes_play_only_while_st_notes(self):
        self.assertTrue(self.notes, "vacuous: no note played")
        self.assertEqual([n for n in self.notes if not n[2]], [])
        # off before the let-go and after the bobs stopped, though they cross the middle
        silent = [r for r in self.frames if not r["notes"]]
        crossings = sum(1 for a, b in zip(silent, silent[1:]) for k in range(self.count)
                        if b["signs"][k] and not a["signs"][k] and b["t"] - a["t"] < 0.02)
        self.assertGreater(crossings, 0, "vacuous: no pendulum crossed the middle while silent")
        for start, end in self.silences():
            self.assertEqual([t for t, *_ in self.notes if start < t < end], [],
                             f"a note between {start:.2f} and {end:.2f}")

    def silences(self) -> list:
        out, start = [], 0.0
        prev = None
        for r in self.frames:
            if prev is not None and prev["notes"] != r["notes"]:
                if r["notes"]:
                    out.append((start, r["t"] - 1 / SECOND))
                else:
                    start = r["t"]
            prev = r
        return out

    def test_they_all_meet_again_after_each_cycle(self):
        for m in (1, 2):
            at = [n for n in self.near if abs(n[0] - m * self.cycle) < 0.05]
            self.assertTrue(at, f"vacuous: no frame near st.time = {m} * CYCLE")
            time, swing, offsets = min(at, key=lambda n: abs(n[0] - m * self.cycle))
            fastest = 2 * math.pi * (self.first_swings + self.count - 1) / self.cycle
            bound = swing * fastest * abs(time - m * self.cycle) + 1e-6
            self.assertLessEqual(max(offsets), bound, f"cycle {m}: a bob is away from rest")
        apart = [max(n[2]) for n in self.near if abs(n[0] % self.cycle - 0.37 * self.cycle) < 0.02]
        self.assertTrue(apart)
        self.assertGreater(min(apart), 50, "vacuous: the bobs are at rest mid-cycle too")
        # the row curls into the ring when they meet, and uncurls when they meet again
        go = self.let_go()
        curl = self.first(lambda r: r["bend"] > 0, after=go)
        row = next(r for r in self.frames if r["t"] == curl)
        self.assertLess(abs(row["time"] - self.cycle), 0.1)
        ringed = self.first(lambda r: r["bend"] == 1, after=curl)
        back = self.first(lambda r: r["bend"] < 1, after=ringed)
        row = next(r for r in self.frames if r["t"] == back)
        self.assertLess(abs(row["time"] - 2 * self.cycle), 0.1)

    def test_the_ring_puts_the_bobs_on_radius_270(self):
        self.assertGreater(len(self.ring), 50, "vacuous: the ring hardly lasted")
        for swing, bobs in self.ring:
            for k, (far, angle, out) in enumerate(bobs):
                self.assertAlmostEqual(far, 270 + swing * 0.55 * out, places=6)
                if far > 1:
                    self.assertLess(turned(angle, 90 - k * 360 / self.count), 1e-6)
        self.assertGreater(max(sw for sw, _ in self.ring), 100, "vacuous: the bobs did not swing on the ring")

    def test_every_loop_shows_the_stems_while_the_row_swings(self):
        self.assertEqual(self.stems, self.count)
        for go in (self.let_go(), self.loop_start()):
            rows = [r for r in self.frames if go + 4 <= r["t"] < go + 10 and "stems" in r]
            self.assertTrue(rows, f"vacuous: no samples after the let-go at {go:.2f}")
            for r in rows:
                self.assertEqual((r["bend"], r["bobs"]), (0, self.count))
                self.assertEqual(r["stems"], self.count, f"t={r['t']:.2f}: stems hidden while the row swings")

    def test_a_loop_leaves_nothing_behind(self):
        again = self.loop_start()
        go = self.let_go()
        one = [n for t, n in self.roster if go + 0.5 <= t < go + 6.5]
        two = [n for t, n in self.roster if again + 0.5 <= t < again + 6.5]
        self.assertTrue(one and two, "vacuous: no second-loop samples")
        self.assertEqual(max(two), max(one), "the second loop has more live items than the first")
        self.assertEqual(max(n for t, n in self.roster), max(one), "the piece grows inside a loop")


if __name__ == "__main__":
    unittest.main()
