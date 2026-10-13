"""Overlap-aware batching: a run reaches past draws it does not overlap.

Rule under test (Effect System Design.md §5.5, "Overlap-aware batching"): with
``batch_shared_filters`` on, a look run (one interned stroke Recipe) or a
one-key filter segment takes later runs of the same look or key, past the
runs between, when none of the moved draw boxes (the cull box: every pixel the
draw can paint) meets a box it passes. Disjoint draws commute, so z between
different looks is kept; only peers of one look or key relax, as they already
do inside a run. ``canvas._BATCH_REACH = False`` is consecutive runs only.

Planner property: over random unit sequences, every pair whose order changes
is one signature or box-disjoint. Pixels: random interleaved scenes (Neon in
two colors, glow in two colors, plain and shadowed shapes, an ADD blend)
where peers of one look stay apart but other looks overlap them render the
same with the reach on and off.

Bug class guarded: a batch that pulls a draw over one it overlaps (z flips
between two looks).
"""
import os
import random
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import numpy as np  # noqa: E402
import skia  # noqa: E402

from test_diff_draw import _engine, assert_pixels_equal, build  # noqa: E402

from scena import Neon  # noqa: E402

CV = sys.modules["scena.canvas"]


class _Look:
    _look_pass_group = True


class _Key:
    def __init__(self, k):
        self._batch_key = k
        self._skia_filter = object()


class _Obj:
    def __init__(self, name, box, visual=None, fill=None):
        self.name = name
        self.box = box
        self.visual = visual
        self.fill_filter = fill
        self.line_filter = None


class TestPlannerProperty(unittest.TestCase):
    def random_units(self, r):
        looks = [_Look(), _Look()]
        keys = [_Key(("blur", 1)), _Key(("glow", 2))]
        units = []
        for k in range(r.randint(3, 40)):
            x, y = r.uniform(0, 400), r.uniform(0, 300)
            w, h = r.uniform(5, 60), r.uniform(5, 60)
            box = (x, y, x + w, y + h) if r.random() > 0.03 else None
            kind = r.choice(("look", "seg", "seg2", "solo", "plain"))
            if kind == "look":
                look = r.choice(looks)
                run = [_Obj(f"L{k}.{m}", box if m == 0 else (x + 70 * m, y, x + 70 * m + w, y + h),
                            visual=look) for m in range(r.choice((1, 1, 2)))]
                units.append(("look", run))
            elif kind in ("seg", "seg2"):
                key = r.choice(keys)
                run = [_Obj(f"S{k}", box, fill=key)]
                if kind == "seg2":            # a mixed segment: never merges
                    run.append(_Obj(f"S{k}b", box, fill=keys[0] if key is keys[1] else keys[1]))
                units.append(("seg", run))
            else:
                units.append((kind, [_Obj(f"{kind[0].upper()}{k}", box)]))
        return units

    def test_moved_pairs_are_peers_or_apart(self):
        r = random.Random(11)
        moved_total = 0
        for case in range(400):
            units = self.random_units(r)
            boxes = {o.name: o.box for _k, run in units for o in run}
            sig = {}
            for kind, run in units:
                s = CV._unit_sig(kind, run)
                for o in run:
                    sig[o.name] = s
            before = [o.name for _k, run in units for o in run]
            with mock.patch.object(CV, "_cull_box", lambda o: o.box):
                merged = CV._merge_reach(units)
            after = [o.name for _k, run in merged for o in run]
            self.assertEqual(sorted(after), sorted(before), f"case {case}: draws lost or doubled")
            pos = {n: i for i, n in enumerate(after)}
            for a in range(len(before)):
                for b in range(a + 1, len(before)):
                    na, nb = before[a], before[b]
                    if pos[na] < pos[nb]:
                        continue
                    moved_total += 1
                    if sig[na] is not None and sig[na] == sig[nb]:
                        continue
                    ba, bb = boxes[na], boxes[nb]
                    self.assertTrue(ba is not None and bb is not None and not CV._boxes_meet(ba, bb),
                                    f"case {case}: {nb} moved over {na}, which it overlaps")
            for kind, run in merged:              # a merged run is one signature
                if len(run) > 1 and kind == "look":
                    self.assertEqual(len({id(o.visual) for o in run}), 1, f"case {case}")
        self.assertGreater(moved_total, 200, "fixture: runs must reach")


BW, BH = 640, 420


def render(objs) -> np.ndarray:
    """``objs`` as one batched layer on a fresh CPU surface; RGBA array."""
    eng = _engine()
    surf = skia.Surface(BW, BH)
    saved = eng.skia_canvas, eng.batch_shared_filters
    try:
        eng.skia_canvas = surf.getCanvas()
        eng.skia_canvas.clear(skia.Color4f(0, 0, 0, 1))
        eng.batch_shared_filters = True
        eng._draw_layer_batched(list(objs))
    finally:
        eng.skia_canvas, eng.batch_shared_filters = saved
    return np.asarray(surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)).copy()


def scene(r):
    """Peers of each look on their own grid cells (apart); other looks anywhere."""
    neon = [Neon("cyan"), Neon("magenta")]
    glows = ["gold", "lime"]
    cells = [(cx, cy) for cx in range(4) for cy in range(3)]
    r.shuffle(cells)
    objs = []
    for k in range(r.randint(10, 18)):
        what = r.choice(("neon0", "neon1", "glow0", "glow1", "neon0", "glow0", "plain",
                         "shadow", "add"))
        if what.startswith(("neon", "glow")) and not cells:
            what = "plain"                    # peers stay on their own cells
        if what.startswith(("neon", "glow")):
            cx, cy = cells.pop()
            x, y = 80.0 + cx * 180.0, 70.0 + cy * 140.0
        elif r.random() < 0.5:                # on top of a cell: real overlaps
            cx, cy = r.randrange(4), r.randrange(3)
            x, y = 80.0 + cx * 180.0 + r.uniform(-4, 4), 70.0 + cy * 140.0 + r.uniform(-4, 4)
        else:
            x, y = r.uniform(20, BW - 20), r.uniform(20, BH - 20)
        small = what.startswith(("neon", "glow"))
        # Neon on rects and polygons only: a look run draws a circle's core with
        # drawCircle and a solo render with a path, whose AA edges differ (LP1 in
        # scripts/bench/games.md), which is not what this test is about.
        kinds = ("rect", "poly") if what.startswith("neon") else ("circle", "rect", "poly")
        o = build((r.choice(kinds), x, y,
                   r.uniform(3, 5) if small else r.uniform(5, 9), "white", 2.0))
        if what.startswith("neon"):
            o.visual = neon[int(what[-1])]
        elif what.startswith("glow"):
            o.glow = glows[int(what[-1])]
        elif what == "shadow":
            o.shadow = True
            o.color = r.choice(("red", "blue"))
        elif what == "add":
            o.color = "orange"
            o.blend = "add"
        else:
            o.color = r.choice(("red", "blue", "green"))
        objs.append(o)
    return objs


class TestSamePixels(unittest.TestCase):
    def setUp(self):
        import scena.recipes as rec           # Neon flickers with the clock: pin it
        self._rec, self._clock = rec, rec._clock
        rec._clock = lambda: 0.25

    def tearDown(self):
        self._rec._clock = self._clock

    def test_reach_on_equals_off(self):
        r = random.Random(4)
        reached = 0
        for case in range(40):
            objs = scene(r)
            try:
                units, _rep = CV.ScenaCanvas._batch_units(_FakeEng(), objs)
                reached += len(CV._merge_reach(units)) < len(units)
                with mock.patch.object(CV, "_BATCH_REACH", True):
                    on = render(objs)
                with mock.patch.object(CV, "_BATCH_REACH", False):
                    off = render(objs)
                # tol=1: a merged plate composites with a batched layer's rounding,
                # as in test_diff_draw's batch_shared_filters on / off differential.
                assert_pixels_equal(self, on, off, f"case {case}: reach on vs off", tol=1)
            finally:
                for o in objs:
                    o.destroy()
        self.assertGreater(reached, 10, "fixture: scenes must merge runs")


class _FakeEng:
    batch_shared_filters = True
    _iter_units = CV.ScenaCanvas._iter_units
    _plan_units = CV.ScenaCanvas._plan_units


class TestCanary(unittest.TestCase):
    def test_a_reach_over_an_overlap_is_caught(self):
        case = TestSamePixels("test_reach_on_equals_off")
        case.setUp()
        try:
            with mock.patch.object(CV, "_boxes_meet", lambda a, b: False):
                with self.assertRaises(AssertionError):
                    case.test_reach_on_equals_off()
        finally:
            case.tearDown()


if __name__ == "__main__":
    unittest.main()
