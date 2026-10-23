"""
The claims of ``examples/rose_window.py``, played headless.

The example says: an endless dive into a rose window whose rings each grow
by the golden ratio over the one inside it; the rings live in a ``History``
of four (a new ring is born in the heart, the oldest leaves in a vortex and
its glass goes with it); every ring turns, neighbours against each other; a
bell rings every 8 seconds and the third bell closes the movement; four
movements of about 24 s (Glass, Mirror, Dawn, Eclipse), each with its own
lens, Dawn with a sun and Eclipse with a moon that crosses the window; keys
1-4 jump to a movement; SPACE holds the dive (the fall stops, the window
keeps turning); a click strikes the nearest piece of glass; the mouse is a
lamp.

Bug class guarded: **an example that stops doing what its docstring says**
after an engine change (``History(max_points=, on_leave=)`` with death verbs,
shapes built from lambdas, ``group.nearest``, links on ``Track`` ``scale`` /
``begin`` / ``end``, ``canvas.covered``) while it still builds and runs,
**a dive that leaks** (a ring that leaves must take its pieces: the live
glass stays bounded however long the dive runs), and **a movement that
warns**: the whole cycle is played and must not raise a single Scena warning,
and **a cycle that leaks**: a death verb (``dissolve_out``) only hides a
shape, so the live objects are counted at the same point of two cycles.

Not covered: drawing (a CPU raster frame costs seconds headless).

Run:

    python tests/run_tiers.py focused test_example_rose_window
"""
from __future__ import annotations

import contextlib
import math
import os
import sys
import unittest
import warnings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from program_support import ProgramRun  # noqa: E402
from hypothesis_support import registry  # noqa: E402

PATH = "examples/rose_window.py"
SECOND = 60

# Engine finding (2026-10-23, reported, not fixed here): a timed camera verb
# that retargets one still in flight (a movement key pressed within 4 s of
# the last movement's zoom_to(time=4)) cancels it, as Canvas Design says, but
# warns through the scheduler's fallback ("replaces a previous in-flight
# tween handle", located in scena/canvas.py, with no fix: camera verbs take
# no name=). Only quick key presses reach it; the cycle on its own does not.
CAMERA_RETARGET = "tween/move_along on the same property replaces a previous in-flight tween handle"


@contextlib.contextmanager
def known_warnings_only(test):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        yield
    other = [str(w.message) for w in caught if str(w.message) != CAMERA_RETARGET]
    test.assertEqual(other, [], "a Scena warning")


def tap(run, key):
    run.key_down(key)
    run.step(1)
    run.key_up(key)
    run.step(1)


def norm(p) -> float:
    x, y = p
    return math.hypot(float(x), float(y))


def lenses(ns):
    return tuple(ns[name].enabled for name in ("mirror", "dawn", "chroma"))


def passing(ns):
    return [t for t in ns["group"]["passing"]]


class TestRoseWindowCycle(unittest.TestCase):
    def test_four_movements_loop_without_a_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with ProgramRun(PATH, seed=1) as run:
                ns = run.ns
                st = ns["st"]
                seen = [(0, 0)]
                bells = 0
                live = []           # 2 s into the first movement, of each loop
                for _ in range(105 * SECOND):
                    if run.frames == seen[-1][1] + 2 * SECOND and st.movement == 0:
                        live.append(len(registry().live))
                        if len(live) == 2:
                            break
                    before = st.bells
                    run.step(1)
                    if st.bells == before + 1:
                        bells += 1
                    if st.movement != seen[-1][0]:
                        seen.append((st.movement, run.frames))
                        m = st.movement
                        # the lens of the movement, and only it
                        self.assertEqual(lenses(ns), (m == 1, m == 2, m == 3))
                        self.assertEqual(st.bells, 0)
                        names = sorted(type(t).__name__ for t in passing(ns))
                        self.assertEqual(names, {0: [], 1: [], 2: ["Sunburst"],
                                                 3: ["Circle", "Circle"]}[m], m)
                        self.assertIn(ns["MOVEMENTS"][m], ns["hud"].text)
        self.assertEqual([str(w.message) for w in caught], [], "a movement raised a Scena warning")
        self.assertEqual(len(live), 2)
        self.assertLessEqual(live[1], live[0], "live objects grew over one cycle")
        self.assertEqual([m for m, _ in seen], [0, 1, 2, 3, 0])
        # about 24 s each: three bells of 8 s, then the iris
        for (_, a), (_, b) in zip(seen[1:], seen[2:]):
            self.assertAlmostEqual((b - a) / SECOND, 24, delta=0.5)
        self.assertGreaterEqual(bells, 12)

    def test_keys_jump_to_a_movement(self):
        with known_warnings_only(self), ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            st = ns["st"]
            for key in ("3", "4", "2", "1"):
                tap(run, key)
                run.step(5 * SECOND)
                m = int(key) - 1
                self.assertEqual(st.movement, m, key)
                self.assertEqual(lenses(ns), (m == 1, m == 2, m == 3), key)
                self.assertIn(f"{key}  {ns['MOVEMENTS'][m]}", ns["hud"].text)

    def test_the_eclipse_moon_crosses_the_window(self):
        with known_warnings_only(self), ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            tap(run, "4")
            run.step(SECOND)
            moon = next(t for t in passing(ns) if t.blend == "difference")
            shadow = next(t for t in passing(ns) if t.blend == "multiply")
            xs = []
            for _ in range(4):
                xs.append(float(moon.center.x))
                self.assertAlmostEqual(float(shadow.center.x), xs[-1], delta=1e-6,
                                       msg="the shadow does not travel with the moon")
                run.step(5 * SECOND)
            self.assertEqual(xs, sorted(xs))
            self.assertLess(xs[0], -600)
            self.assertGreater(xs[-1], 0)
            # the next movement takes the moon away
            tap(run, "1")
            run.step(2 * SECOND)
            self.assertFalse(moon.is_alive)
            self.assertFalse(shadow.is_alive)
            self.assertEqual(passing(ns), [])


class TestRoseWindowDive(unittest.TestCase):
    def test_rings_grow_by_phi_and_the_history_stays_bounded(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            st, dive, phi = ns["st"], ns["dive"], ns["PHI"]
            rings_seen = set()
            glass_most = 0
            for _ in range(40):
                run.step(SECOND // 2)
                rings = list(dive)
                rings_seen.update(rings)
                self.assertEqual(len(rings), ns["RINGS"])
                # the oldest is the biggest; each ring is phi times the next one in
                for outer, inner in zip(rings, rings[1:]):
                    self.assertAlmostEqual(outer.radius / inner.radius, phi, delta=1e-9)
                # the newest is never smaller than the heart it is born in
                self.assertGreaterEqual(rings[-1].radius, ns["HEART"] - 1e-6)
                self.assertLess(rings[-1].radius, ns["HEART"] * phi + 1e-6)
                for ring in rings:
                    self.assertAlmostEqual(ring.radius,
                                           ns["HEART"] * phi ** (st.depth - rings_born(ns, ring)),
                                           delta=1e-6)
                glass_most = max(glass_most, len(list(ns["group"]["glass"])))
            self.assertGreater(st.depth, 3, "the dive did not go on")
            self.assertGreater(len(rings_seen), ns["RINGS"] + 2, "no ring was born")
            # a ring that left is gone, with all of its pieces
            run.step(2 * SECOND)
            for ring in rings_seen - set(dive):
                self.assertFalse(ring.is_alive, "a ring that left the dive stays")
                self.assertTrue(all(not p.is_alive for p in ring.pieces), "a ring left its glass behind")
            self.assertLessEqual(glass_most, ns["RINGS"] * ns["PANES"])

    def test_glass_rides_its_ring(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            run.step(7 * SECOND)
            checked = 0
            glass = set(ns["group"]["glass"])
            for ring in ns["dive"]:
                for piece in ring.pieces:
                    if piece not in glass:
                        continue
                    # every piece sits on its ring's circle (f = 1)
                    self.assertAlmostEqual(norm(piece.center), ring.radius, delta=1e-6)
                    checked += 1
            self.assertGreaterEqual(checked, 2 * ns["PANES"], "vacuous: no glass")
            # neighbours turn against each other
            rings = list(ns["dive"])
            for a, b in zip(rings, rings[1:]):
                self.assertLess(a.spin * b.spin, 0)

    def test_space_holds_the_dive_and_the_window_keeps_turning(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            st, canvas = ns["st"], ns["canvas"]
            run.step(SECOND)
            tap(run, "SPACE")
            self.assertFalse(st.diving)
            self.assertIn("(held)", ns["hud"].text)
            depth = st.depth
            ring = ns["dive"].last
            angle, view = ring.angle, canvas.rotation
            born = st.born
            run.step(10 * SECOND)
            self.assertEqual(st.depth, depth, "the fall did not stop")
            self.assertEqual(st.born, born, "a ring was born while held")
            self.assertNotAlmostEqual(ring.angle, angle, delta=1, msg="the rings stopped turning")
            self.assertNotAlmostEqual(canvas.rotation, view, delta=1, msg="the window stopped turning")
            tap(run, "SPACE")
            self.assertTrue(st.diving)
            self.assertNotIn("(held)", ns["hud"].text)
            run.step(SECOND)
            self.assertAlmostEqual(st.depth - depth, (SECOND + 2) / SECOND / ns["RING_TIME"], delta=0.02)


def rings_born(ns, ring) -> int:
    """The birth number n of a ring: its radius is HEART * PHI ** (depth - n)."""
    return round(ns["st"].depth - math.log(ring.radius / ns["HEART"], ns["PHI"]))


class TestRoseWindowPointer(unittest.TestCase):
    def test_a_click_strikes_the_nearest_piece(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            real = ns["group"]
            asked = []

            class Glass:
                """``group["glass"]`` as on_mouse_click sees it: records each nearest()."""

                def __init__(self, g):
                    self.g = g

                def nearest(self, xy):
                    piece = self.g.nearest(xy)
                    asked.append((tuple(map(float, xy)), piece))
                    return piece

                def __iter__(self):
                    return iter(self.g)

            class Groups:
                def __getitem__(self, name):
                    g = real[name]
                    return Glass(g) if name == "glass" else g

            ns["group"] = Groups()
            run.step(3 * SECOND)        # between two bells (they pop every piece)
            for vx, vy in ((640, 400), (900, 500), (300, 250)):
                asked.clear()
                run.press(vx, vy)
                run.step(1)
                run.release()
                run.step(1)
                self.assertEqual(len(asked), 1, (vx, vy))
                xy, piece = asked[0]
                pieces = [p for p in real["glass"] if p.is_alive]
                best = min(pieces, key=lambda p: math.dist(xy, (float(p.center.x), float(p.center.y))))
                self.assertIs(piece, best, "the click did not strike the nearest piece")
                self.assertEqual(piece._tx_state.pop.peak, 1.5, "the struck piece did not pop")

    def test_the_lamp_follows_the_mouse(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            lamp, mouse = ns["lamp"], ns["mouse"]
            for vx, vy in ((100, 100), (1000, 700)):
                run.move(vx, vy)
                run.step(2)
                self.assertAlmostEqual(float(lamp.center.x), float(mouse.x), delta=1e-6)
                self.assertAlmostEqual(float(lamp.center.y), float(mouse.y), delta=1e-6)


if __name__ == "__main__":
    unittest.main()
