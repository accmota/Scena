"""
``Polygon.rotate_by`` writes its vertices in one inline pass and skips the
write gate for a vertex with nothing linked (showcase D2, 2026-10-23: a
linked angle turned a 12-point polygon through the per-vertex call layers,
~60 µs a frame). The pass must keep what the call layers did.

Guarded here: the turned positions are the rotation about the pivot; a
linked vertex still refuses before any vertex moves (SC4); a whole-object
link still refuses; a formula reading a vertex follows the turn; the gate
still runs (and records) under ``_GATE_RECORD``; a linked angle keeps
turning the polygon.

Run:

    python tests/run_tiers.py focused test_polygon_turn
"""
from __future__ import annotations

import math
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from program_support import FRAME  # noqa: E402
from system_support import boot, system_world  # noqa: E402

import scena.shapes as shapes_mod  # noqa: E402
from scena import Circle, Polygon, clock, st  # noqa: E402
from scena.state import LinkedAttributeError  # noqa: E402
from tests.leftovers import module_sweep  # noqa: E402

boot()
setUpModule, tearDownModule = module_sweep()

PTS = [(100, 100), (160, 110), (130, 130), (150, 170), (90, 150)]


def xy(p):
    return float(p.x), float(p.y)


def turned(points, pivot, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    px, py = pivot
    return [(px + (x - px) * c - (y - py) * s, py + (x - px) * s + (y - py) * c) for x, y in points]


class TestPolygonTurn(unittest.TestCase):
    def test_positions_are_the_rotation(self):
        for linked_elsewhere in (False, True):
            with self.subTest(linked_elsewhere=linked_elsewhere), system_world(draw=False):
                p = Polygon(points=PTS)
                if linked_elsewhere:
                    st.k = 1.0
                    p["k"] @= lambda: st.k      # the polygon now has an @=
                before = [xy(v) for v in p.points]
                p.rotate_by(37, about=(120, 140))
                want = turned(before, (120, 140), 37)
                for got, w in zip((xy(v) for v in p.points), want):
                    self.assertAlmostEqual(got[0], w[0], places=6)
                    self.assertAlmostEqual(got[1], w[1], places=6)
                self.assertAlmostEqual(float(p.angle), 37.0, places=6)

    def test_a_linked_vertex_refuses_before_any_moves(self):
        with system_world(draw=False):
            anchor = Circle(center=(160, 110), radius=2)
            p = Polygon(points=[PTS[0], lambda: anchor.center, *PTS[2:]])
            before = [xy(v) for v in p.points]
            with self.assertRaises(LinkedAttributeError):
                p.rotate_by(20)
            self.assertEqual([xy(v) for v in p.points], before)

    def test_a_whole_object_link_refuses(self):
        with system_world(draw=False):
            src = Polygon(points=PTS)
            p = Polygon(points=PTS)
            p @= src
            with self.assertRaises(LinkedAttributeError):
                p.rotate_by(20)

    def test_a_vertex_reader_follows(self):
        with system_world(draw=False) as w:
            p = Polygon(points=PTS)
            dot = Circle(center=lambda: p.points[1], radius=2)
            p.rotate_by(90, about=(100, 100))
            w.step(1, dt=FRAME)
            self.assertAlmostEqual(float(dot.center.x), 90.0, places=5)
            self.assertAlmostEqual(float(dot.center.y), 160.0, places=5)

    def test_the_gate_still_records(self):
        rec = []
        with system_world(draw=False), mock.patch.object(shapes_mod, "_GATE_RECORD", rec):
            p = Polygon(points=PTS)
            st.k = 1.0
            p["k"] @= lambda: st.k
            p.rotate_by(10)
        self.assertGreaterEqual(len(rec), len(PTS))

    def test_a_linked_angle_turns_it(self):
        with system_world(draw=True) as w:
            p = Polygon(points=PTS)
            p["angle"] @= lambda: clock.time * 90
            w.step(30, dt=FRAME)
            self.assertAlmostEqual(float(p.angle) % 360, (float(clock.time) * 90) % 360, places=3)


if __name__ == "__main__":
    unittest.main()
