"""
The claims of ``examples/demo100.py``, played headless.

The example says: rings of triangles (8 + 8 * ring of them, five rings) dance
in three parts, then it loops (I Open: the rings open out of a point around a
beating heart, under the title; II Dance: they sway in slow waves; III Storm:
they spin faster and faster and burst); every triangle is placed by a formula
of the clock, nothing moves them by hand. User decisions guarded here: the
dance does not read the music (no audio source in any formula: the song only
plays), there is no Prism, and there are exactly three parts.

Bug class guarded: **an example that stops doing what its docstring says**
after an engine change (``@=`` formulas, group verbs, tweens of ``st``) while
it still builds and runs (``test_scripts_run`` only plays 30 frames); and
**a looping piece that grows each loop**: ``implode`` and ``dissolve_out``
only hide a shape, so each loop's 120 dancers and its title stayed alive,
hidden, their formulas still evaluated: the cost of a loop grew by its first
loop's cost every loop (measured 0.75 s, 1.15, 1.52 … 2.71 s of CPU per loop
headless; found 2026-10-23, the storyboard now destroys them).

Run:

    python tests/run_tiers.py focused test_example_demo100
"""
from __future__ import annotations

import ast
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
from hypothesis_support import registry  # noqa: E402
import scena.process  # noqa: E402
from scena import Text, Triangle, canvas, clock, group, vec_from_angle  # noqa: E402

PATH = "examples/demo100.py"
SECOND = 60
PLAY = 60           # seconds: the whole loop (~35.5 s) and most of the next
TITLE = "DEMO 100"
DANCERS = sum(8 + 8 * ring for ring in range(5))      # 120
SCENA_DIR = os.path.normcase(os.path.join(ROOT, "scena")) + os.sep
FIELDS = ("open", "sway", "spin")
# names that would make a formula read the sound (the audio object, its
# helpers, the microphone)
AUDIO = {"audio", "amp_db", "Microphone", "microphone", "mic", "spectrum", "level", "beat"}


def engine_warnings(caught) -> list:
    """The warnings the engine raised (a SCENA message, or raised from scena/)."""
    return [f"{w.category.__name__}: {w.message}" for w in caught
            if "SCENA" in str(w.message)
            or os.path.normcase(os.path.abspath(w.filename)).startswith(SCENA_DIR)]


def turned(a: float, b: float) -> float:
    """Gap between two angles in degrees, in 0 … 180."""
    return abs((a - b + 180) % 360 - 180)


def source() -> str:
    with open(os.path.normpath(os.path.join(ROOT, *PATH.split("/"))), encoding="utf-8") as fh:
        return fh.read()


def dance_mismatches(ns) -> list:
    """Every dancer (and the heart) that is not where its formula puts it now."""
    t = clock.time
    members = {id(o) for o in group["dancer"]}
    dancers = [o for o in registry().live_objects()      # in the order make_rings made them
               if isinstance(o, Triangle) and o.is_alive and id(o) in members]
    if len(dancers) != DANCERS:
        return [f"t={t:.2f}: {len(dancers)} dancers"]
    out = []
    n = 0
    for ring in range(5):
        for k in range(8 + 8 * ring):
            d = dancers[n]
            n += 1
            where = vec_from_angle(ns["turn"](ring, k), ns["reach"](ring))
            if math.dist((d.center.x, d.center.y), (where.x, where.y)) > 1e-6:
                out.append(f"t={t:.2f} ring {ring} dancer {k} at {d.center.x, d.center.y}")
            want = ns["turn"](ring, k) + 90 + 35 * math.sin(t * 2 - ring)
            if turned(d.angle, want) > 1e-6:
                out.append(f"t={t:.2f} ring {ring} dancer {k} angle {d.angle} != {want}")
    heart = ns["heart"]
    if abs(heart.radius - ns["st"].open * (35 + 5 * math.sin(t * 2))) > 1e-6:
        out.append(f"t={t:.2f} heart radius {heart.radius}")
    return out


class TestDemo100(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames = []         # one dict per frame
        cls.counts = []         # (t, live dancers, live titles, live roster), 4 a second
        cls.mismatches = []
        cls.checked = 0
        # The tier runs 8 workers next to peer sessions: building the 120
        # dancers (~0.1 s idle) can pass the 0.5 s watchdog budget there. The
        # budget is test_process's subject, not this piece's.
        with warnings.catch_warnings(record=True) as caught, \
                mock.patch.object(scena.process, "WATCHDOG_RESUME_S", 5.0):
            warnings.simplefilter("always")
            with ProgramRun(PATH, seed=1) as run:
                ns = run.ns
                st = ns["st"]
                for f in range(PLAY * SECOND):
                    run.step(1)
                    row = {name: float(getattr(st, name)) for name in FIELDS}
                    row["t"] = clock.time
                    row["effects"] = {type(e).__name__ for e in canvas.effects}
                    cls.frames.append(row)
                    if f % 15 == 0:
                        live = registry().live_objects()
                        cls.counts.append((
                            clock.time,
                            sum(1 for o in group["dancer"] if o.is_alive),
                            sum(1 for o in live if isinstance(o, Text) and o.is_alive and o.text == TITLE),
                            len(live)))
                    if f % 20 == 0 and st.open > 0:
                        row["reach"] = [ns["reach"](ring) for ring in range(5)]
                        cls.mismatches += dance_mismatches(ns)
                        cls.checked += 1
                cls.author_error = scena.process.last_author_error()
        cls.warned = engine_warnings(caught)

    def first(self, pred, after: float = 0.0) -> float:
        """Time of the first frame (at or after ``after``) where ``pred(row)``."""
        for row in self.frames:
            if row["t"] >= after and pred(row):
                return row["t"]
        self.fail(f"never reached (after t={after})")

    def loop_start(self) -> float:
        """When the second loop begins: the storyboard puts spin back to 1."""
        storm = self.first(lambda r: r["spin"] >= 5.999)
        return self.first(lambda r: r["spin"] == 1, after=storm)

    # -- the claims ---------------------------------------------------------
    def test_the_whole_loop_plays_without_a_warning(self):
        self.assertEqual(self.warned, [])
        self.assertIsNone(self.author_error)
        self.assertGreater(self.frames[-1]["t"], self.loop_start() + 15,
                           "vacuous: the run did not reach the second loop")

    def test_three_parts_in_order_then_it_loops(self):
        opened = self.first(lambda r: r["open"] == 1)
        dance = self.first(lambda r: r["sway"] > 0)
        self.assertLess(opened, dance, "the rings sway before they are open")
        swaying = self.first(lambda r: r["sway"] == 1, after=dance)
        storm = self.first(lambda r: r["spin"] > 1, after=swaying)
        self.assertGreater(storm - swaying, 10, "the Dance is too short")
        burst = self.first(lambda r: r["open"] == 0, after=storm)
        again = self.loop_start()
        self.assertLess(burst, again)
        self.first(lambda r: r["sway"] > 0, after=again)    # the second Dance
        # Three parts: the storyboard has three part headings, as the docstring
        parts = re.findall(r"^\s+# (I{1,3}|IV|V)\s+(\w+)", source(), re.M)
        self.assertEqual(parts, [("I", "Open"), ("II", "Dance"), ("III", "Storm")])

    def test_the_dance_does_not_read_the_music(self):
        tree = ast.parse(source())
        heard = sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id in AUDIO}
                       | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in AUDIO})
        self.assertEqual(heard, [], "a formula reads the sound")
        calls = {n.func.id for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("play_sound", calls, "vacuous: the song is gone")

    def test_there_is_no_prism(self):
        self.assertNotIn("Prism", source())
        self.assertEqual({e for r in self.frames for e in r["effects"]} & {"Prism", "Chroma"}, set())

    def test_the_rings_and_the_heart_are_their_formulas(self):
        self.assertGreater(self.checked, 100)
        self.assertEqual(self.mismatches[:5], [])

    def test_the_rings_open_wide_and_sway(self):
        """reach(): every ring sits further out than the one inside it, and in
        the Dance it moves in and out (the dancers follow reach(), above)."""
        swaying = [r["reach"] for r in self.frames if "reach" in r and r["sway"] == 1 and r["open"] == 1]
        self.assertGreater(len(swaying), 50)
        for ring in range(5):
            seen = [reach[ring] for reach in swaying]
            self.assertGreater(max(seen) - min(seen), 20, f"ring {ring} does not sway")
            if ring:
                self.assertTrue(all(reach[ring] > reach[ring - 1] for reach in swaying))

    def test_a_loop_leaves_nothing_behind(self):
        again = self.loop_start()
        for t, dancers, titles, live in self.counts:
            self.assertLessEqual(dancers, DANCERS, f"t={t:.2f}: dancers from an earlier loop")
            self.assertLessEqual(titles, 1, f"t={t:.2f}: a title from an earlier loop")
        self.assertEqual({d for t, d, _, _ in self.counts if 2 < t < 30}, {DANCERS})
        self.assertEqual({d for t, d, _, _ in self.counts if again + 1 < t}, {DANCERS})
        one = [n for t, _, _, n in self.counts if 1 <= t < 20]
        two = [n for t, _, _, n in self.counts if again + 0.5 <= t < again + 19.5]
        self.assertTrue(two, "vacuous: no second-loop samples")
        self.assertEqual(max(two), max(one), "the second loop has more live items than the first")


if __name__ == "__main__":
    unittest.main()
