"""
The claims of ``examples/polygon_ballet.py``, played headless.

The example says: 28 regular polygons dance three movements, looping (about
60 s): I Polygons (domino waves change their sides and looks: big polygons
gain a side, small ones lose one, so the total stays the same), II Rosettes
(pieces orbit four rosettes, the polygons gather round them), III Lines (the
big heptagons come apart into their 98 edges, string art that locks on a
circle, closes into a ring, falls into the centre and bursts); a wave is
``domino()``: one action on every polygon, later the farther it is from
where the wave starts. User decisions guarded here: a polygon always has 3 to
7 sides; the file stays within 200 lines; each movement colours the screen
its own way, and the Prism splits the colours only briefly.

Bug class guarded: **an example that stops doing what its docstring says**
after an engine change (linked ``center=lambda``, ``after()`` timers, group
destroy, ``points`` of a RegularPolygon) while it still builds and runs
(``test_scripts_run`` only plays 30 frames).

Run:

    python tests/run_tiers.py focused test_example_polygon_ballet
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
from scena import Line, canvas, clock, group  # noqa: E402

PATH = "examples/polygon_ballet.py"
SECOND = 60
PLAY = 72           # seconds: the whole loop (~63 s) and the first waves of the next
SCENA_DIR = os.path.normcase(os.path.join(ROOT, "scena")) + os.sep
POSTS = {"ColorSweep": "I", "ColorWash": "II", "Vignette": "III"}


def engine_warnings(caught) -> list:
    """The warnings the engine raised (a SCENA message, or raised from scena/)."""
    return [f"{w.category.__name__}: {w.message}" for w in caught
            if "SCENA" in str(w.message)
            or os.path.normcase(os.path.abspath(w.filename)).startswith(SCENA_DIR)]


def part(caption: str) -> str:
    return caption.split()[0] if caption else ""


def sides(ns) -> dict:
    """Sides of every live polygon, by spot."""
    return {i: len(p.points) for i, p in ns["dancers"].items() if p.is_alive}


def strand_mismatches(ns) -> list:
    """With the lines locked on the circle, line j joins slot j to slot j·mult + skip."""
    st = ns["st"]
    strands = [o for o in registry().live_objects()      # in the order they were made
               if isinstance(o, Line) and o.is_alive and "strand" in o.group]
    n = ns["STRANDS"]
    if len(strands) != n:
        return [f"{len(strands)} strands"]
    out = []
    for j, line in enumerate(strands):
        for end, slot in ((line.p1, j), (line.p2, j * st.mult + st.skip)):
            want = ns["around"](640, 400, 360 * st.ring, slot * 360 / n + st.turn)
            if math.dist((end.x, end.y), want) > 1e-6:
                out.append(f"t={clock.time:.2f} strand {j} end at {end.x, end.y}, not {want}")
    return out


class TestPolygonBallet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames = []         # one dict per frame
        cls.made = []           # (t, spot, sides) for every polygon dance() makes
        cls.at_part = {}        # caption -> (sides by spot, big flags) when it first shows
        cls.follow = []         # mismatches: a polygon off its spot, a piece off its orbit
        cls.strands = []        # mismatches of the locked string art
        cls.strand_checks = 0
        cls.follow_checks = cls.pieces_seen = 0
        cls.fired = {}          # domino probe: (start, spot) -> time it fired
        cls.probe_t = None
        cls.strand_count = None
        cls.alive_in_lines = None
        # The tier runs 8 workers next to peer sessions: a resume that takes
        # ~0.1 s idle can pass the 0.5 s watchdog budget there. The budget is
        # test_process's subject, not this piece's.
        with warnings.catch_warnings(record=True) as caught, \
                mock.patch.object(scena.process, "WATCHDOG_RESUME_S", 5.0):
            warnings.simplefilter("always")
            with ProgramRun(PATH, seed=1) as run:
                ns = run.ns
                st = ns["st"]
                dance = ns["dance"]

                def recorded(i, n):
                    cls.made.append((clock.time, i, n))
                    dance(i, n)
                ns["dance"] = recorded      # step() and the first wave look it up here
                caption = ns["caption"]
                last = None
                for f in range(PLAY * SECOND):
                    run.step(1)
                    t = clock.time
                    row = {"t": t, "caption": caption.text, "lock": float(st.lock),
                           "effects": [type(e).__name__ for e in canvas.effects]}
                    cls.frames.append(row)
                    if caption.text != last:
                        last = caption.text
                        cls.at_part.setdefault(last, (sides(ns), list(ns["big"])))
                    if part(caption.text) == "II" and f % 5 == 0:
                        for i, p in ns["dancers"].items():
                            s = ns["spots"][i]
                            if p.is_alive and math.dist((p.center.x, p.center.y), (s.x, s.y)) > 1e-6:
                                cls.follow.append(f"t={t:.2f} polygon {i} is off its spot")
                        cls.follow += cls.piece_mismatches(ns)
                        cls.pieces_seen = max(cls.pieces_seen, len(group["piece"]))
                        cls.follow_checks += 1
                    if st.lock == 1 and f % 10 == 0:
                        cls.strands += strand_mismatches(ns)
                        cls.strand_checks += 1
                        if cls.strand_count is None:
                            cls.strand_count = len(group["strand"])
                            cls.alive_in_lines = sides(ns)
                    if cls.probe_t is None and part(caption.text) == "I" and t > 3:
                        cls.probe_t = t
                        cls.lights = [(fx.center.x, fx.center.y) for fx in group["light"]]
                        for start in ("lights", "diagonal"):
                            ns["domino"](start, lambda i, start=start: cls.fired.setdefault(
                                (start, i), clock.time))
                cls.author_error = scena.process.last_author_error()
                cls.ns_spots = [(s.x, s.y) for s in ns["spots"]]
                cls.pace = ns["PACE"]
        cls.warned = engine_warnings(caught)

    @staticmethod
    def piece_mismatches(ns) -> list:
        """Each rosette piece circles its rosette, as far out as the rosette is open."""
        pieces = [o for o in registry().live_objects()
                  if o.is_alive and "piece" in getattr(o, "group", ())]
        if not pieces:
            return []
        out = []
        n = 0
        for cx, cy in ns["ROSETTES"]:
            for kind, count, dist, *_ in ns["PIECES"]:
                for _ in range(count):
                    p = pieces[n]
                    n += 1
                    got = math.dist((p.center.x, p.center.y), (cx, cy))
                    if abs(got - abs(dist * ns["st"].bloom)) > 1e-6:
                        out.append(f"t={clock.time:.2f} a {kind.__name__} is {got} from its rosette")
        return out

    # -- helpers ------------------------------------------------------------
    def first(self, pred, after: float = 0.0) -> float:
        for row in self.frames:
            if row["t"] >= after and pred(row):
                return row["t"]
        self.fail(f"never reached (after t={after})")

    # -- the claims ---------------------------------------------------------
    def test_the_file_is_at_most_200_lines(self):
        with open(os.path.normpath(os.path.join(ROOT, *PATH.split("/"))), encoding="utf-8") as fh:
            self.assertLessEqual(len(fh.read().splitlines()), 200)

    def test_the_whole_loop_plays_without_a_warning(self):
        self.assertEqual(self.warned, [])
        self.assertIsNone(self.author_error)

    def test_three_movements_in_order_then_it_loops(self):
        order = []
        for row in self.frames:
            if not order or order[-1] != part(row["caption"]):
                order.append(part(row["caption"]))
        self.assertEqual(order, ["I", "II", "III", "I"])
        again = self.first(lambda r: part(r["caption"]) == "I", after=self.first(
            lambda r: part(r["caption"]) == "III"))
        self.assertTrue(55 < again < 70, f"a loop lasts {again:.1f} s, not about 60")

    def test_each_movement_colours_the_screen_its_own_way(self):
        for row in self.frames[1:]:
            posts = [e for e in row["effects"] if e in POSTS]
            self.assertEqual(len(posts), 1, f"t={row['t']:.2f}: {posts}")
            self.assertEqual(POSTS[posts[0]], part(row["caption"]), f"t={row['t']:.2f}")

    def test_the_prism_is_brief(self):
        again = self.first(lambda r: part(r["caption"]) == "I", after=self.first(
            lambda r: part(r["caption"]) == "III"))
        prism = [r for r in self.frames if "Prism" in r["effects"] and r["t"] < again]
        self.assertTrue(prism, "vacuous: no Prism")
        self.assertLessEqual(len(prism), 5 * SECOND + 2, "the Prism is on longer than its five seconds")
        self.assertEqual({part(r["caption"]) for r in prism}, {"III"})

    def test_a_polygon_always_has_3_to_7_sides(self):
        self.assertGreater(len(self.made), 28 * 6, "vacuous: few polygons made")
        self.assertEqual([m for m in self.made if not 3 <= m[2] <= 7], [])
        for caption, (by_spot, big) in self.at_part.items():
            for i, n in by_spot.items():
                self.assertTrue(3 <= n <= 7, f"{caption}: polygon {i} has {n} sides")

    def test_the_waves_keep_the_total_of_sides(self):
        """Big ones gain what small ones lose: after the four waves of I, every
        big polygon is a heptagon and every small one a triangle."""
        start = self.at_part["II   ROSETTES"]
        by_spot, big = start
        self.assertEqual(len(by_spot), 28)
        self.assertEqual(sum(by_spot.values()), 14 * 3 + 14 * 7)
        for i, n in by_spot.items():
            self.assertEqual(n, 7 if big[i] else 3, f"polygon {i}")
        # the next loop starts over: big triangles, small heptagons
        again = self.first(lambda r: part(r["caption"]) == "I", after=self.first(
            lambda r: part(r["caption"]) == "III"))
        reborn = {i: n for t, i, n in self.made if again <= t < again + 2.5}
        self.assertEqual(len(reborn), 28)
        self.assertEqual(reborn, {i: 3 if big[i] else 7 for i in range(28)})

    def test_polygons_ride_their_spots_and_pieces_orbit_their_rosettes(self):
        self.assertGreater(self.follow_checks, 100)
        self.assertEqual(self.pieces_seen, 4 * (4 + 7 + 7))
        self.assertEqual(self.follow[:5], [])

    def test_the_big_heptagons_come_apart_into_98_lines(self):
        self.assertEqual(self.strand_count, 98)
        self.assertEqual(self.alive_in_lines, {}, "a polygon outlived its coming apart")

    def test_the_string_art_follows_its_rule(self):
        self.assertGreater(self.strand_checks, 100)
        self.assertEqual(self.strands[:5], [])

    def test_a_wave_reaches_far_spots_later(self):
        """domino(): each spot acts PACE seconds per unit of distance after the
        wave starts (from the nearest light, or from a diagonal line)."""
        self.assertIsNotNone(self.probe_t, "vacuous: the domino probe never ran")
        self.assertEqual(len(self.lights), 4)
        frame = 1 / SECOND
        far = {
            "lights": [min(math.dist(s, fx) for fx in self.lights) for s in self.ns_spots],
            "diagonal": [max(0.0, (x + y - 300) * 0.5) for x, y in self.ns_spots],
        }
        for start, d in far.items():
            fired = [self.fired.get((start, i)) for i in range(28)]
            self.assertNotIn(None, fired, f"{start}: the wave missed a spot")
            delays = [f - self.probe_t for f in fired]
            for i in range(28):
                self.assertAlmostEqual(delays[i], d[i] * self.pace, delta=2 * frame,
                                       msg=f"{start}: spot {i}")
            by_distance = [delays[i] for i in sorted(range(28), key=lambda i: d[i])]
            self.assertEqual(by_distance, sorted(by_distance), f"{start}: a nearer spot acted later")
            self.assertGreater(max(delays) - min(delays), 0.5, f"{start}: the wave is not a wave")

if __name__ == "__main__":
    unittest.main()
