"""Vectorized query candidates find what the Python walk finds.

Rule under test (Collision Design.md, "Moved set and vectorized candidates"):
between steps a query refreshes only the proxies of bodies that moved (their
revision cells, drained into ``_stale``), bodies whose pose can change with no
write (``_untrusted``: links, Polygons, Text...) and compound bodies; then it
masks the group's candidate rows (a numpy mirror of the proxies) against the
query box. ``collision._QUERY_VECTOR = False`` refreshes and tests every
candidate in Python (the oracle).

Random worlds of declared-tag ground are mutated between queries through the
write paths (moves, placement, resize, links, enroll and destroy, retag), and
``floor_below(group=)`` answers the same both ways, end pose included.

Bug class guarded: a candidate index that misses a body (a stale proxy, a row
out of date, a moved body never marked).
"""
import os
import random
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scena import st
from scena.collision import STATIC, collide, get_collision_system, reset_collision_system
from scena.shapes import Circle, Polygon, Rect
from scena.sprite import Sprite

C = sys.modules["scena.collision"]   # the module (``scena.collision`` is the facade)
TILE = os.path.join(ROOT, "examples", "media", "tilesets", "Tiles", "2.png")


def _probe_pose(captured):
    prims, found = captured
    return (round(min(p.aabb[0] for p in prims), 6), round(min(p.aabb[1] for p in prims), 6), found)


class VectorCase(unittest.TestCase):
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

    def ground(self, r, o):
        k = r.random()
        x = o + r.uniform(-300, 300)
        y = o + r.uniform(-60, 20)
        grp = r.choice(("chao", "plataforma"))
        if k < 0.35:
            g = Sprite(TILE, size=r.choice((32.0, 64.0)), center=(x, y), group=grp)
        elif k < 0.6:
            g = Rect(center=(x, y), width=r.uniform(20, 90), height=r.uniform(8, 30), group=grp)
        elif k < 0.75:
            g = Circle(center=(x, y), radius=r.uniform(8, 30), group=grp)
        else:
            w = r.uniform(20, 70)
            g = Polygon(points=[(x - w, y - 10), (x + w, y - 10), (x + w, y + 8), (x - w, y + 14)],
                        group=grp)
        g.mass = STATIC
        self.owned.append(g)
        return g

    def ask(self, h, vector, **kw):
        seen = []
        real = C.CollisionSystem._note_floor_probe

        def note(sys_, body, prims, found):
            seen.append((list(prims), found))
            return real(sys_, body, prims, found)

        with mock.patch.object(C, "_QUERY_VECTOR", vector), \
                mock.patch.object(C.CollisionSystem, "_note_floor_probe", note):
            got = h.floor_below(**kw)
        return got, (_probe_pose(seen[-1]) if seen and seen[-1][0] else None)

    def mutate(self, r, world, o):
        op = r.random()
        g = r.choice(world)
        if op < 0.25:
            g.move_by(r.uniform(-40, 40), r.uniform(-15, 15), force=True)
        elif op < 0.4:
            g.move_to(o + r.uniform(-300, 300), o + r.uniform(-60, 20), force=True)
        elif op < 0.5 and hasattr(g, "width") and not isinstance(g, Circle):
            g.width = r.uniform(10, 100)
        elif op < 0.6:
            st.lx = o + r.uniform(-300, 300)
            if isinstance(g, Rect):
                g.center["x"] @= lambda: st.lx       # linked: moves with no write
        elif op < 0.7:
            world.append(self.ground(r, o))
        elif op < 0.8 and len(world) > 4:
            world.remove(g)
            g.destroy()
        elif op < 0.9:
            if g.tagged("chao"):
                g.untag("chao")
                g.tag("plataforma")
            else:
                g.tag("chao")
        else:
            st.lx = o + r.uniform(-300, 300)          # moves every linked body


class TestSameAnswers(VectorCase):
    def test_random_worlds_and_mutations(self):
        compared = found = 0
        for seed in range(30):
            r = random.Random(seed)
            for s_ in self.owned:          # one world at a time, one system
                try:
                    s_.destroy()
                except Exception:
                    pass
            self.owned.clear()
            reset_collision_system()
            o = 3000.0 * (seed + 1)
            world = [self.ground(r, o) for _ in range(30)]

            @collide("chao", "plataforma")       # both tags are pair tags: indexed
            def _pair(a, b, info):
                pass

            hero = Rect(center=(o, o + 40), width=20, height=40, group="heroi")
            hero.mass = 1.0
            self.owned.append(hero)
            get_collision_system().step()
            for q in range(25):
                self.mutate(r, world, o)
                hero.center = (o + r.uniform(-250, 250), o + r.uniform(-20, 80))
                kw = {"dx": r.choice((0.0, 12.0, -30.0, 60.0)), "group": ["chao", "plataforma"]}
                # The index first: the walk refreshes every proxy it touches,
                # which would hide a body the moved set lost.
                vec = self.ask(hero, True, **kw)
                walk = self.ask(hero, False, **kw)
                self.assertIs(vec[0], walk[0], f"seed {seed} q {q}: floor differs")
                self.assertEqual(vec[1], walk[1], f"seed {seed} q {q}: end pose differs")
                compared += 1
                found += walk[0] is not None
                if q % 7 == 6:
                    get_collision_system().step()
        self.assertGreater(found, compared // 10, "the scenes must find floors")


class TestCanary(VectorCase):
    def test_a_moved_body_never_marked_is_caught(self):
        def lose(self_):
            C.DIRTY_POSE_CELLS.clear()           # drops the moves on the floor

        case = TestSameAnswers("test_random_worlds_and_mutations")
        case.setUp()
        try:
            with mock.patch.object(C.CollisionSystem, "_drain_pose_cells", lose), \
                    mock.patch.object(C, "_POSE_REV_VERIFY", False):
                with self.assertRaises(AssertionError):
                    case.test_random_worlds_and_mutations()
        finally:
            case.tearDown()


if __name__ == "__main__":
    unittest.main()
