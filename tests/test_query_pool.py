"""Query pools answer exactly what the candidate walk answers.

Rule under test (Collision Design.md, "Query pools"): a query over a group
reads a cached candidate list (the walk's, in its order: a declared tag's
colliders, an undeclared tag's members through their answering collider, the
enrolled world), masks it against the query box on rows kept fresh by the
moved set, and runs the walk's per-member checks (in play, layer, a claiming
part) on the near ones only. ``collision._QUERY_POOL = False`` is the walk
(the oracle).

Random worlds of mixed kinds (Rect, Circle, Ellipse, Triangle,
RegularPolygon, Polygon, Sprite; enrolled or not; a compound body; a sprite
whose hitbox part claims the tag; a member on the ui layer) are mutated
between queries through the author's write paths (moves, turns, resizes,
links, active / collidable, retag, layer, spawn, destroy, a part switched
off), and every query (point, circle, sector, spread 0 and 360, shape,
raycast) over every group form answers the same both ways, in the same
order. The pool is asked first: the walk refreshes every proxy it touches,
which would hide a row the moved set lost.

Bug class guarded: a query index that misses a body or reports a stale one
(a moved body never marked, a member whose answer changed with no
membership change, a row out of date) — including a move during
``on_update`` seen by a later query of the same frame.
"""
import os
import random
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scena import ANYTHING, Collider, collision, st
from scena.collision import collide, get_collision_system, reset_collision_system
from scena.shapes import Circle, Ellipse, Polygon, Rect, RegularPolygon, Triangle
from scena.sprite import Sprite

C = sys.modules["scena.collision"]   # the module (``scena.collision`` is the facade)
TILE = os.path.join(ROOT, "examples", "media", "tilesets", "Tiles", "2.png")


def _ids(found):
    if found is None:
        return None
    if isinstance(found, tuple):
        if found[0] == "raised":
            return found
        return (id(found[0]), round(found[1], 9))    # raycast: (who, t, point)
    return [id(x) for x in found]


class PoolCase(unittest.TestCase):
    def setUp(self):
        reset_collision_system()
        self.owned = []
        self.enterContext(mock.patch.object(C, "_QUERY_POOL_MIN", 1))

    def tearDown(self):
        for s in self.owned:
            try:
                s.destroy()
            except Exception:
                pass
        self.owned.clear()
        reset_collision_system()

    def keep(self, s):
        self.owned.append(s)
        return s

    def both(self, ask):
        """``ask()`` with the pool, then with the walk (a refusal is an answer)."""
        out = []
        for on in (True, False):
            with mock.patch.object(C, "_QUERY_POOL", on):
                try:
                    out.append(ask())
                except Exception as exc:       # a ui caster: both must refuse
                    out.append(("raised", type(exc), str(exc)))
        return out[0], out[1]


class TestSameAnswers(PoolCase):
    KINDS = ("rect", "circle", "ellipse", "triangle", "regular", "polygon", "sprite")

    def member(self, r, o, tags=("bando",)):
        x, y = o + r.uniform(-250, 250), o + r.uniform(-250, 250)
        k = r.choice(self.KINDS)
        if k == "rect":
            s = Rect(center=(x, y), width=r.uniform(6, 40), height=r.uniform(6, 40))
        elif k == "circle":
            s = Circle(center=(x, y), radius=r.uniform(4, 20))
        elif k == "ellipse":
            s = Ellipse(center=(x, y), width=r.uniform(8, 40), height=r.uniform(6, 30))
        elif k == "triangle":
            s = Triangle(center=(x, y), radius=r.uniform(5, 20), base_ratio=r.uniform(0.4, 1.4))
        elif k == "regular":
            s = RegularPolygon(n=r.choice((3, 5, 6)), center=(x, y), radius=r.uniform(5, 20))
        elif k == "polygon":
            w = r.uniform(5, 25)
            s = Polygon(points=[(x - w, y - 8), (x + w, y - 6), (x, y + w)])
        else:
            s = Sprite(TILE, size=r.choice((16.0, 32.0)), center=(x, y))
        for t in tags:
            s.tag(t)
        if r.random() < 0.2:
            s.collidable = True                       # enrolled: answers with its own body
        if r.random() < 0.3:
            s.angle = r.uniform(-180, 180)
        return self.keep(s)

    def world(self, r, o):
        bando = [self.member(r, o) for _ in range(r.randint(12, 40))]
        ninho = [self.member(r, o, ("ninho",)) for _ in range(r.randint(4, 20))]

        @collide("ninho", "fera")                     # a declared pair tag: indexed colliders
        def _pair(a, b, info):
            pass

        a, b = bando[0], bando[1]
        if not a.collidable and not b.collidable:
            Collider([a, b])                          # two members, one compound body
        boss = self.keep(Sprite(TILE, size=48.0, center=(o, o)))
        part = boss.add_hitbox(group="bando", scale=0.5)
        hud = self.keep(Circle(center=(o + 10, o + 10), radius=12, group="bando", layer="ui"))
        st.lx = o
        linked = self.keep(Rect(center=(o, o), width=20, height=10, group="bando"))
        linked.center["x"] @= lambda: st.lx           # moves with no write
        bando += [boss, hud, linked]
        return bando, ninho, part

    def mutate(self, r, bando, ninho, part, o, calm=False):
        """One write. ``calm``: pose writes only (moves, turns, resizes, a
        link pulled), so the pools are reused and only their rows move."""
        pool = r.choice((bando, ninho))
        g = r.choice(pool)
        op = r.random()
        if calm:
            op = r.uniform(0.0, 0.52) if op < 0.9 else 0.9
        if not getattr(g, "is_alive", True):
            return "dead"
        try:
            if op < 0.25:
                g.move_by(r.uniform(-60, 60), r.uniform(-60, 60))
            elif op < 0.35:
                g.center = (o + r.uniform(-250, 250), o + r.uniform(-250, 250))
            elif op < 0.42:
                g.angle = r.uniform(-180, 180)
            elif op < 0.48:
                if isinstance(g, (Circle, Triangle, RegularPolygon)):
                    g.radius = r.uniform(3, 30)
                elif isinstance(g, (Rect, Ellipse)):
                    g.width = r.uniform(5, 60)
            elif op < 0.52 and isinstance(g, Triangle):
                g.base_ratio = r.uniform(0.3, 1.6)
            elif op < 0.58:
                g.active = not g.active
            elif op < 0.63:
                g.collidable = not g.collidable
            elif op < 0.68:
                if g.tagged("bando"):
                    g.untag("bando")
                else:
                    g.tag("bando")
            elif op < 0.72:
                g.layer = "ui" if g.layer != "ui" else "default"
            elif op < 0.78:
                pool.append(self.member(r, o, ("bando",) if pool is bando else ("ninho",)))
            elif op < 0.84 and len(pool) > 6:
                pool.remove(g)
                g.destroy()
            elif op < 0.88:
                part.active = not part.active
            elif op < 0.92:
                st.lx = o + r.uniform(-250, 250)
            elif op < 0.95:
                get_collision_system().step()
        except Exception:                             # a refused write (a computed
            return "refused"                          # center, a linked one): no change
        return "ok"

    def ask(self, r, o, bando):
        x, y = o + r.uniform(-260, 260), o + r.uniform(-260, 260)
        group = r.choice(("bando", "ninho", None, ANYTHING, ["bando", "ninho"],
                          ("ninho", "bando"), ["bando", ANYTHING]))
        live = [s for s in bando if getattr(s, "is_alive", True)]
        caster = r.choice(live) if live and r.random() < 0.4 else None
        origin = caster if caster is not None else (x, y)
        kind = r.choice(("point", "circle", "sector", "segment", "full", "shape", "ray"))
        rad = r.uniform(0, 120)
        if kind == "point":
            return kind, lambda: collision.query_point(origin, group=group)
        if kind == "circle":
            return kind, lambda: collision.query_circle(origin, radius=rad, group=group)
        if kind in ("sector", "segment", "full"):
            spread = {"sector": r.uniform(10, 200), "segment": 0, "full": 360}[kind]
            ang = r.uniform(-180, 180)
            return kind, lambda: collision.query_sector(origin, angle=ang, radius=rad,
                                                        spread=spread, group=group)
        if kind == "shape" and caster is not None:
            return kind, lambda: collision.query_shape(caster, group=group)
        ang = r.uniform(-180, 180)
        return "ray", lambda: collision.raycast(origin, angle=ang, length=rad * 2, group=group)

    def test_random_worlds_and_mutations(self):
        compared = hits = 0
        kinds = set()
        for seed in range(40):
            r = random.Random(seed)
            self.tearDown()
            reset_collision_system()
            o = 2000.0 * (seed + 1)
            bando, ninho, part = self.world(r, o)
            for q in range(60):
                calm = q % 30 >= 10                 # 10 churning queries, then 20 calm
                for _ in range(r.randint(0, 3)):
                    self.mutate(r, bando, ninho, part, o, calm)
                kind, ask = self.ask(r, o, bando)
                pooled, walked = self.both(ask)
                self.assertEqual(_ids(pooled), _ids(walked),
                                 f"seed {seed} q {q} {kind}: {pooled} != {walked}")
                compared += 1
                kinds.add(kind)
                hits += bool(walked)
        self.assertGreater(hits, compared // 4, "the scenes must find bodies")
        self.assertEqual(kinds, {"point", "circle", "sector", "segment", "full", "shape", "ray"})


class TestMidFrame(PoolCase):
    """A move between two queries of one frame is seen by the second."""

    def flock(self, cls=Triangle, n=30, **kw):
        """``n`` members of "bando" in a row, their pool built (the second
        query of a version builds it): the writes below meet existing rows."""
        birds = [self.keep(cls(center=(40.0 * i, 0.0), group="bando", **kw)) for i in range(n)]
        for _ in range(2):
            self.near(-9999, -9999)
        self.assertIn(("bando",), get_collision_system()._query_pools)
        return birds

    def near(self, x, y, r=10):
        return collision.query_circle((x, y), radius=r, group="bando")

    def test_every_write_kind_is_seen(self):
        writes = {
            "center": lambda b: setattr(b, "center", (5000.0, 5000.0)),
            "move_by": lambda b: b.move_by(5000.0 - b.center.x, 5000.0 - b.center.y),
            "move_to": lambda b: b.move_to(5000.0, 5000.0),
            "center.x": lambda b: (setattr(b.center, "x", 5000.0), setattr(b.center, "y", 5000.0)),
        }
        for name, write in writes.items():
            with self.subTest(write=name):
                self.tearDown()
                birds = self.flock(radius=9)
                self.assertEqual(self.near(5000, 5000), [], "the pool is built, nobody there")
                self.assertIn(birds[3], self.near(120, 0))
                write(birds[3])
                self.assertEqual(self.near(5000, 5000), [birds[3]], f"{name}: the new place")
                self.assertNotIn(birds[3], self.near(120, 0), f"{name}: not the old one")

    def test_shape_inputs_are_seen(self):
        birds = self.flock(radius=5)
        self.assertEqual(self.near(80, 15, 2), [])
        birds[2].radius = 40                          # now reaches (80, 15)
        self.assertIn(birds[2], self.near(80, 15, 2))
        birds[2].radius = 5
        birds[2].base_ratio = 1.5
        self.assertNotIn(birds[2], self.near(80, 15, 2))
        birds[2].angle = 90
        birds[2].radius = 35
        self.assertIn(birds[2], self.near(80, 15, 2), "turned and grown")

    def test_a_move_in_on_update_is_seen_by_a_later_query(self):
        """The flock pattern: each body moves, then asks; the pool answers
        what the walk answers, bird by bird, over two frames."""
        case = self
        answers = []

        class Passaro(Triangle, radius=9, group="bando"):
            def on_update(self, dt):
                self.move_by(30.0, 0.0)
                ask = lambda: collision.query_circle(self.center, radius=30, group="bando",
                                                     ignore=self)
                answers.append(case.both(ask))

        birds = [self.keep(Passaro(center=(25.0 * i, 0.0))) for i in range(20)]
        from scena.process import tick_processes
        tick_processes()
        tick_processes()
        self.assertEqual(len(answers), 40)
        for k, (pooled, walked) in enumerate(answers):
            self.assertEqual(pooled, walked, f"query {k}")
        self.assertTrue(sum(map(bool, (w for _p, w in answers))) > 10, "birds meet")
        self.assertIn(("bando",), get_collision_system()._query_pools)

    def test_a_part_claiming_the_tag_later_answers(self):
        """A claim changes who answers with no membership change."""
        tiles = [self.keep(Sprite(TILE, size=32.0, center=(100.0 * i, 0.0), group="bando"))
                 for i in range(20)]
        corner = (100.0 * 3 + 14, 14)                 # in the body, out of a small part
        for _ in range(2):                            # the second one builds the pool
            self.assertEqual(collision.query_point(corner, group="bando"), [tiles[3]])
        part = tiles[3].add_hitbox(group="bando", scale=0.3)
        pooled, walked = self.both(lambda: collision.query_point(corner, group="bando"))
        self.assertEqual(walked, [], "the part answers for the tag now")
        self.assertEqual(pooled, walked)
        tiles[3].remove_hitbox(part)
        pooled, walked = self.both(lambda: collision.query_point(corner, group="bando"))
        self.assertEqual(walked, [tiles[3]], "the body answers again")
        self.assertEqual(pooled, walked)

    def test_registered_rows_by_mirror_and_in_python(self):
        """Enrolled bodies: few moved -> the numpy mirror; most moved -> the
        proxies in Python. Both answer as the walk."""
        r = random.Random(4)
        bodies = [self.keep(Circle(center=(r.uniform(0, 800), r.uniform(0, 800)), radius=8))
                  for _ in range(60)]
        for b in bodies:
            b.collidable = True
        mirror = []
        real = C._rows_meeting
        with mock.patch.object(C, "_rows_meeting",
                               side_effect=lambda *a: mirror.append(1) or real(*a)):
            for q in range(80):
                movers = bodies[:2] if q % 2 else bodies           # few, then all
                for b in movers:
                    b.move_by(r.uniform(-30, 30), r.uniform(-30, 30))
                x, y, rad = r.uniform(0, 800), r.uniform(0, 800), r.uniform(10, 120)
                pooled, walked = self.both(lambda: collision.query_circle((x, y), radius=rad))
                self.assertEqual(_ids(pooled), _ids(walked), f"query {q}")
        self.assertTrue(mirror, "the mirror path ran")

    def test_an_untrusted_member_is_seen_too(self):
        birds = self.flock(cls=Circle, radius=6)
        st.px = 0.0
        birds[0].center["x"] @= lambda: st.px
        self.assertEqual(self.near(3000, 0), [])
        st.px = 3000.0                                 # moves with no write
        self.assertEqual(self.near(3000, 0), [birds[0]])

    def test_a_large_group_uses_the_pool(self):
        birds = self.flock(radius=9, n=40)
        with mock.patch.object(C, "_QUERY_POOL_MIN", 16):
            cs = get_collision_system()
            calls = []
            real = cs._query_collider
            with mock.patch.object(cs, "_query_collider",
                                   side_effect=lambda *a: calls.append(1) or real(*a)):
                self.near(0, 0)          # walks: every member
                self.near(0, 0)          # same version again: builds
                self.assertIn(("bando",), cs._query_pools)
                calls.clear()
                birds[0].move_by(1, 0)
                self.assertEqual(self.near(0, 0), [birds[0]])
            self.assertLessEqual(len(calls), 2, "a pooled query asks only its near members")


class TestCircleOverlaps(PoolCase):
    """``query_circle``'s yes/no is the narrow phase's, on every prim kind."""

    KINDS = TestSameAnswers.KINDS

    def test_same_decision_as_narrow_phase(self):
        r = random.Random(11)
        cs = get_collision_system()
        decided = {True: 0, False: 0}
        kinds = set()
        for k in range(400):
            s = TestSameAnswers.member(self, r, 0.0, tags=())
            if r.random() < 0.3 and hasattr(s, "rotation"):
                s.angle = r.uniform(-180, 180)
            col = C.Collider([s], _register=False, _bind=False)
            cs._update_proxy(col, commit_motion=False)
            for prim in cs._world_prims(col):
                kinds.add(prim.kind)
                px, py = prim.aabb[0], prim.aabb[1]
                for _ in range(6):
                    # Around the prim's box, and right at its corner (touching).
                    x = r.choice((px, px + r.uniform(-30, 30)))
                    y = r.choice((py, py + r.uniform(-30, 30)))
                    rad = r.choice((0.0, r.uniform(0, 25)))
                    probe = C.Prim(C.PrimKind.CIRCLE, C._aabb_from_circle(x, y, rad), (x, y, rad))
                    want = C.narrow_phase(probe, prim) is not None
                    self.assertEqual(C._circle_overlaps(probe, prim), want,
                                     f"{s!r} prim {prim.kind} circle ({x}, {y}, {rad})")
                    decided[want] += 1
            s.destroy()
        self.assertTrue(decided[True] > 100 and decided[False] > 100, decided)
        self.assertEqual(kinds, set(C.PrimKind), "every prim kind is met")


class TestCanary(PoolCase):
    def test_a_lost_move_is_caught(self):
        def lose(self_):
            real_reslot(self_)
            self_._q_by_root = {}                     # the moved set no longer reaches the rows

        real_reslot = C.CollisionSystem._reslot_query_pools
        case = TestSameAnswers("test_random_worlds_and_mutations")
        case.setUp()
        try:
            with mock.patch.object(C.CollisionSystem, "_reslot_query_pools", lose), \
                    mock.patch.object(C, "_POSE_REV_VERIFY", False):
                with self.assertRaises(AssertionError):
                    case.test_random_worlds_and_mutations()
        finally:
            case.tearDown()

    def test_verify_mode_names_a_stale_row(self):
        birds = [self.keep(Circle(center=(40.0 * i, 0.0), radius=6, group="bando"))
                 for i in range(20)]
        collision.query_point((0, 0), group="bando")
        collision.query_point((0, 0), group="bando")  # builds
        get_collision_system()._q_by_root.clear()
        birds[1].move_by(500, 0)
        with mock.patch.object(C, "_POSE_REV_VERIFY", True):
            with self.assertRaisesRegex(AssertionError, "did not mark it"):
                collision.query_point((0, 0), group="bando")


if __name__ == "__main__":
    unittest.main()
