"""
The claims of ``examples/canopy.py``, played headless.

The example says: every branch is a Line that starts where its parent ends,
turns a little from its parent's direction and is a little shorter; one
recursive function, ``grow()``, lays all ``2 ** (DEPTH + 1) - 1`` branches
every frame, and a few numbers in ``st`` change it. The storyboard: the tree
grows a level at a time (I Seed), sways (II Wind), opens to a circuit
(``st.spread`` 90) and a coral that spins (``st.turn`` moving) (III Shapes),
curls into a fern (``st.lean`` 25) (IV Spiral), shrinks back into its seed,
then loops. The sky is a background, which does not link: its colours are
written each frame from ``SKY`` at ``st.dusk``.

Bug class guarded: **an example that stops doing what its docstring says**
after an engine change (Line endpoints written every frame, tweens of ``st``,
a background's colours written each frame) while it still builds and runs
(``test_scripts_run`` only plays 30 frames); a docstring whose numbers drift
from the code (it said 1023 branches for DEPTH 8, which lays 511); and **a
looping piece that grows each loop**.

``grow()`` is wrapped to note the numbers the frame's ``update`` laid the
tree with (a tween of ``st`` may move them later in the same frame). Laying
511 Lines is most of a frame's cost, and grow() lays the whole tree from
``st`` and the clock alone, so the run steps at 30 Hz and the real grow()
lays it one frame in three (every checked frame among them); the wrapper
still counts update's call on every frame.

Run:

    python tests/run_tiers.py focused test_example_canopy
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
from scena import Line, clock  # noqa: E402

PATH = "examples/canopy.py"
HZ = 30
PLAY = 84           # seconds: the whole loop (~80.5 s) and the next seed
LAY = 3             # the real grow() lays the tree one frame in LAY (and on every checked frame)
SCENA_DIR = os.path.normcase(os.path.join(ROOT, "scena")) + os.sep
FIELDS = ("grow", "spread", "lean", "ratio", "sway", "turn", "dusk", "root")
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


def parents(branches) -> list:
    """The parent index of each branch (None for the trunk), from grow()'s order."""
    out, stack = [], []
    for i, (_line, depth) in enumerate(branches):
        del stack[depth:]
        out.append(stack[-1] if stack else None)
        stack.append(i)
    return out


def tree_mismatches(ns, laid) -> list:
    """Every branch that is not where the one rule puts it, with the numbers
    the frame's update laid the tree with."""
    t = clock.time
    branches = ns["branches"]
    depth_max, trunk = ns["DEPTH"], ns["TRUNK"]
    out = []
    ends = [((ln.p1.x, ln.p1.y), (ln.p2.x, ln.p2.y)) for ln, _ in branches]
    up = parents(branches)
    children = {}
    for i, p in enumerate(up):
        children.setdefault(p, []).append(i)
    (x, y), _ = ends[0]
    if math.dist((x, y), (0, laid["root"])) > EPS:
        out.append(f"t={t:.2f} the trunk starts at {(x, y)}, not (0, {laid['root']})")
    for i, (line, depth) in enumerate(branches):
        p1, p2 = ends[i]
        length = math.dist(p1, p2)
        want = trunk * laid["ratio"] ** depth * min(1, max(0, laid["grow"] - depth))
        if abs(length - want) > 1e-6:
            out.append(f"t={t:.2f} branch {i} (depth {depth}) is {length} long, not {want}")
        if up[i] is not None and math.dist(p1, ends[up[i]][1]) > EPS:
            out.append(f"t={t:.2f} branch {i} starts at {p1}, its parent ends at {ends[up[i]][1]}")
        kids = children.get(i, [])
        if depth < depth_max and len(kids) != 2:
            out.append(f"branch {i} has {len(kids)} children")
        if len(kids) == 2 and all(math.dist(*ends[k]) > 1e-3 for k in kids):
            a, b = (math.degrees(math.atan2(ends[k][1][1] - ends[k][0][1], ends[k][1][0] - ends[k][0][0]))
                    for k in kids)
            if turned(b - a, 2 * laid["spread"]) > 1e-6:
                out.append(f"t={t:.2f} branch {i}'s children are {b - a} apart, not 2 * {laid['spread']}")
    return out


class TestCanopy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames = []         # one dict per frame
        cls.roster = []         # (t, live roster items), twice a second
        cls.mismatches = []
        cls.checked = 0
        with warnings.catch_warnings(record=True) as caught, \
                mock.patch.object(scena.process, "WATCHDOG_RESUME_S", 5.0):
            warnings.simplefilter("always")
            with ProgramRun(PATH, seed=1, dt=1 / HZ) as run:
                ns = run.ns
                st = ns["st"]
                cls.lines = sum(1 for o in run_registry().live_objects() if type(o) is Line)
                cls.count = len(ns["branches"])
                cls.depth = ns["DEPTH"]
                laid = {}
                lay = ns["grow"]

                def grow(x, y, angle, depth, i):
                    if depth == 0:
                        laid.update({name: float(getattr(st, name)) for name in FIELDS})
                        laid["calls"] = laid.get("calls", 0) + 1
                        if not laid["now"]:
                            return i        # noted, not laid (update ignores the return)
                    return lay(x, y, angle, depth, i)

                ns["grow"] = grow            # update and the recursion find it by name
                sky, SKY = ns["sky"], ns["SKY"]
                for f in range(PLAY * HZ):
                    calls = laid.get("calls", 0)
                    laid["now"] = f % LAY == 0
                    run.step(1)
                    row = {name: float(getattr(st, name)) for name in FIELDS}
                    row["t"] = clock.time
                    row["laid"] = laid.get("calls", 0) - calls
                    d = laid["dusk"]
                    row["sky"] = (tuple(sky.color), tuple(sky.color2), tuple(sky.color3))
                    row["sky_want"] = (SKY.get_color(d).rgb, SKY.get_color((d + 0.33) % 1).rgb,
                                       SKY.get_color((d + 0.66) % 1).rgb)
                    cls.frames.append(row)
                    if f % (5 * LAY) == 0:
                        cls.roster.append((clock.time, len(run_registry().live_objects())))
                        cls.mismatches += tree_mismatches(ns, laid)
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
        """When the second loop begins: the tree grows again after it shrank."""
        grown = self.first(lambda r: r["grow"] >= self.depth + 1 - EPS)
        shrunk = self.first(lambda r: r["grow"] == 0, after=grown)
        return self.first(lambda r: r["grow"] > 0, after=shrunk)

    # -- the claims ---------------------------------------------------------
    def test_the_whole_loop_plays_without_a_warning(self):
        self.assertEqual(self.warned, [])
        self.assertIsNone(self.author_error)
        self.assertGreater(self.frames[-1]["t"], self.loop_start() + 2,
                           "vacuous: the run did not reach the second loop")

    def test_one_branch_per_node_of_a_full_binary_tree(self):
        self.assertEqual(self.count, 2 ** (self.depth + 1) - 1)
        self.assertEqual(self.lines, self.count, "a Line that is not a branch, or a branch that is not a Line")
        said = re.search(r"lays all (\d+) branches", source())
        self.assertIsNotNone(said, "the docstring no longer counts the branches")
        self.assertEqual(int(said.group(1)), self.count, "the docstring's branch count is not the tree's")

    def test_the_tree_is_laid_every_frame(self):
        self.assertEqual({r["laid"] for r in self.frames}, {1})

    def test_each_branch_starts_where_its_parent_ends(self):
        self.assertGreater(self.checked, 150)
        self.assertEqual(self.mismatches[:5], [])

    def test_it_grows_a_level_at_a_time(self):
        grow = [r["grow"] for r in self.frames if r["t"] < self.first(lambda r: r["grow"] >= self.depth + 1 - EPS)]
        self.assertEqual(grow, sorted(grow))
        # each level gets time of its own (the lengths follow growth(): checked above)
        for level in range(self.depth + 1):
            span = [r["t"] for r in self.frames if level < r["grow"] < level + 1 and r["t"] < 15]
            self.assertGreater(len(span), 5, f"level {level} grows at once")

    def test_the_storyboard_reaches_each_shape_then_loops(self):
        grown = self.first(lambda r: r["grow"] >= self.depth + 1 - EPS)
        swaying = self.first(lambda r: r["sway"] >= 1.2 - EPS, after=grown)
        circuit = self.first(lambda r: r["spread"] >= 90 - EPS, after=swaying)
        coral = self.first(lambda r: r["turn"] > 90, after=circuit)
        turns = [r["turn"] for r in self.frames if coral <= r["t"] <= coral + 10]
        self.assertGreater(turns[-1] - turns[0], 60, "the coral does not spin")
        self.first(lambda r: r["spread"] <= 60 + EPS, after=coral)
        fern = self.first(lambda r: r["lean"] >= 25 - EPS, after=coral)
        self.assertEqual([r["t"] for r in self.frames if r["lean"] and r["t"] < coral], [],
                         "the tree curls before the coral")
        straight = self.first(lambda r: r["lean"] == 0, after=fern)
        shrunk = self.first(lambda r: r["grow"] == 0, after=straight)
        again = self.loop_start()
        self.assertGreater(again, shrunk)
        row = next(r for r in self.frames if r["t"] == again)
        self.assertEqual((row["spread"], row["lean"], row["sway"], row["turn"], row["root"]),
                         (24, 0, 0, 90, -380))

    def test_the_sky_follows_dusk_every_frame(self):
        for r in self.frames:
            for got, want in zip(r["sky"], r["sky_want"]):
                self.assertLess(max(abs(a - b) for a, b in zip(got, want)), 1e-9,
                                f"t={r['t']:.2f}: the sky is {got}, not {want}")
        loop = [r for r in self.frames if r["t"] < self.loop_start()]
        self.assertGreater(len({r["sky"][0] for r in loop}), len(loop) // 2, "vacuous: the sky does not change")
        dusk = [r["dusk"] for r in loop]
        self.assertGreater(max(dusk), 0.9)

    def test_a_loop_leaves_nothing_behind(self):
        again = self.loop_start()
        one = [n for t, n in self.roster if 0.5 <= t < 3.5]
        two = [n for t, n in self.roster if again + 0.5 <= t < again + 3.5]
        self.assertTrue(one and two, "vacuous: no second-loop samples")
        self.assertEqual(max(two), max(one), "the second loop has more live items than the first")
        self.assertEqual(max(n for t, n in self.roster), max(one), "the piece grows inside a loop")


if __name__ == "__main__":
    unittest.main()
