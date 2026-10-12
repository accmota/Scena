"""``query_shape`` rejects on proxy boxes first, and answers the same.

Rule under test (Collision Design.md, "Queries (on-demand)"): every query
rejects a candidate whose proxy box misses the probe's before it builds
world prims; proxies contain their prims (``TestProxyAabbConservative``) and
the reject is inclusive, so a touching pair still reaches the narrow phase.
``query_shape`` built prims for every candidate (games.md B3).
``collision._QUERY_SHAPE_REJECT = False`` is the old walk (the oracle).

Bug class guarded: a reject that is not conservative (a rotated or sprite
hull poking out of its proxy, tangent contacts).
"""
import math
import os
import random
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scena.collision import get_collision_system, reset_collision_system
from scena.shapes import Circle, Line, Polygon, Rect
from scena.sprite import Sprite

C = sys.modules["scena.collision"]   # the module (``scena.collision`` is the facade)
TILE = os.path.join(ROOT, "examples", "media", "tilesets", "Tiles", "2.png")
STAR = os.path.join(ROOT, "examples", "media", "k-rolling-ball", "star.png")


def make(r, x, y):
    k = r.choice(("rect", "circle", "poly", "line", "tile", "star"))
    if k == "rect":
        s = Rect(center=(x, y), width=r.uniform(4, 60), height=r.uniform(4, 60), group="mundo")
        s.angle = r.choice((0.0, 0.0, 30.0, 45.0, 72.5))
    elif k == "circle":
        s = Circle(center=(x, y), radius=r.uniform(3, 30), group="mundo")
    elif k == "poly":
        n = r.choice((3, 5, 6))
        rad = r.uniform(8, 35)
        a0 = r.uniform(0, 6.28)
        s = Polygon(points=[(x + rad * math.cos(a0 + 2 * math.pi * i / n),
                             y + rad * math.sin(a0 + 2 * math.pi * i / n)) for i in range(n)],
                    group="mundo")
    elif k == "line":
        a = r.uniform(0, 6.28)
        L = r.uniform(10, 70)
        s = Line(p1=(x, y), p2=(x + L * math.cos(a), y + L * math.sin(a)), group="mundo")
        s.line_width = r.choice((1.0, 4.0))
    else:
        s = Sprite(TILE if k == "tile" else STAR, size=r.uniform(16, 70), center=(x, y), group="mundo")
        s.angle = r.choice((0.0, 0.0, 20.0, 90.0))
        s.flip_x = r.random() < 0.3
    return s


class TestSameHits(unittest.TestCase):
    def setUp(self):
        reset_collision_system()
        self.owned = []

    def tearDown(self):
        for s in self.owned:
            try:
                s.destroy()
            except Exception:
                pass
        reset_collision_system()

    def test_random_worlds(self):
        hits = 0
        for seed in range(25):
            r = random.Random(seed)
            reset_collision_system()
            world = [make(r, r.uniform(0, 400), r.uniform(0, 400)) for _ in range(40)]
            for s in world:
                s.collidable = True
            self.owned += world
            get_collision_system().step()
            for q in range(12):
                probe = make(r, r.uniform(0, 400), r.uniform(0, 400))
                probe.group = ["sonda"]
                self.owned.append(probe)
                with mock.patch.object(C, "_QUERY_SHAPE_REJECT", False, create=True):
                    slow = [id(h) for h in get_collision_system().query_shape(probe, group="mundo")]
                fast = [id(h) for h in get_collision_system().query_shape(probe, group="mundo")]
                self.assertEqual(fast, slow, f"seed {seed} probe {q}")
                hits += len(slow)
        self.assertGreater(hits, 100)

    def test_touching_boxes_still_hit(self):
        a = Rect(center=(0, 0), width=20, height=20, group="mundo")
        a.collidable = True
        b = Rect(center=(20, 0), width=20, height=20, group="sonda")
        self.owned += [a, b]
        with mock.patch.object(C, "_QUERY_SHAPE_REJECT", False, create=True):
            slow = get_collision_system().query_shape(b, group="mundo")
        self.assertEqual(get_collision_system().query_shape(b, group="mundo"), slow)


if __name__ == "__main__":
    unittest.main()
