"""An axis-aligned Sprite hull is an AABB prim, and that changes no answer.

Rule under test (Collision Design.md, "Axis-aligned hulls"): a Sprite hull
whose four vertices are exactly the corners of its bounding box (an opaque
tile, unrotated; flips and scale keep it) becomes an ``AABB`` prim, as an
unrotated ``Rect`` is, so it takes the closed-form narrow phase and sweep.
Any real rotation keeps the ``POLY``. ``collision._HULL_AABB`` switches it off
(the oracle).

The same box as AABB and as POLY must give the same contact (normal, depth,
points) within 1e-4 against every prim kind, and the same sweep within the
GJK tolerance (the closed form is the exact one: ≤ 0.1 DU along the motion).
A walker on sprite tiles lands and walks the same way with the switch on or
off, and ``floor_below`` gives the same floors.

Bug class guarded: a prim conversion that silently changes contacts.
"""
import math
import os
import random
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scena.collision import STATIC, get_collision_system, reset_collision_system, resolve
from scena.sprite import Sprite
from scena.shapes import Rect
from scena.scenamath import Vec2
from tests.floor_support import with_floor  # noqa: E402

C = sys.modules["scena.collision"]   # the module (``scena.collision`` is the facade)
P, K = C.Prim, C.PrimKind
TILE = os.path.join(ROOT, "examples", "media", "tilesets", "Tiles", "2.png")


def rect_aabb(x0, y0, x1, y1):
    return P(K.AABB, (x0, y0, x1, y1), (x0, y0, x1, y1))


def rect_poly(x0, y0, x1, y1):
    return P(K.POLY, (x0, y0, x1, y1), (), [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def other_prim(r):
    kind = r.choice(("aabb", "circle", "obb", "poly", "polyrect"))
    cx, cy = r.uniform(-60, 60), r.uniform(-60, 60)
    if kind in ("aabb", "polyrect"):
        w, h = r.uniform(4, 50), r.uniform(4, 50)
        make = rect_aabb if kind == "aabb" else rect_poly
        return kind, make(cx - w, cy - h, cx + w, cy + h)
    if kind == "circle":
        rad = r.uniform(3, 40)
        return kind, P(K.CIRCLE, (cx - rad, cy - rad, cx + rad, cy + rad), (cx, cy, rad))
    if kind == "obb":
        hw, hh, a = r.uniform(4, 40), r.uniform(4, 40), r.uniform(0, math.pi)
        return kind, P(K.OBB, C._aabb_from_obb(cx, cy, hw, hh, a), (cx, cy, hw, hh, a))
    n = r.choice((3, 5, 6))
    rad, a0 = r.uniform(8, 40), r.uniform(0, 6.28)
    v = [(cx + rad * math.cos(a0 + 2 * math.pi * i / n), cy + rad * math.sin(a0 + 2 * math.pi * i / n))
         for i in range(n)]
    return kind, P(K.POLY, C._aabb_from_verts(v), (), v)


def same_contact(tc, a, b, ctx):
    tc.assertEqual(a is None, b is None, f"{ctx}: one hits, one misses")
    if a is None:
        return
    tc.assertLess(math.hypot(a.normal[0] - b.normal[0], a.normal[1] - b.normal[1]), 1e-4, ctx)
    tc.assertAlmostEqual(a.depth, b.depth, delta=1e-4, msg=ctx)
    pa = sorted((round(x, 3), round(y, 3)) for x, y in a.points)
    pb = sorted((round(x, 3), round(y, 3)) for x, y in b.points)
    tc.assertEqual(pa, pb, ctx)


class TestSameBoxSameAnswer(unittest.TestCase):
    """The prim kind is an implementation detail of one geometry."""

    def test_contacts_and_sweeps_agree(self):
        r = random.Random(1)
        hits = sweeps = 0
        for i in range(6000):
            w, h = r.uniform(5, 60), r.uniform(5, 60)
            x0, y0 = r.uniform(-40, 0), r.uniform(-40, 0)
            box_a = rect_aabb(x0, y0, x0 + 2 * w, y0 + 2 * h)
            box_p = rect_poly(x0, y0, x0 + 2 * w, y0 + 2 * h)
            kind, o = other_prim(r)
            ctx = f"case {i} vs {kind}"
            a, b = C.narrow_phase(o, box_a), C.narrow_phase(o, box_p)
            same_contact(self, a, b, ctx + " (o, box)")
            same_contact(self, C.narrow_phase(box_a, o), C.narrow_phase(box_p, o), ctx + " (box, o)")
            hits += a is not None
            dx, dy = r.uniform(-80, 80), r.uniform(-80, 80)
            ta = C._toi_prim_sets([o], [box_a], dx, dy)
            tp = C._toi_prim_sets([o], [box_p], dx, dy)
            self.assertEqual(ta is None, tp is None, ctx + " sweep hit")
            if ta is not None:
                sweeps += 1
                self.assertLessEqual(abs(ta[0] - tp[0]) * math.hypot(dx, dy), 0.1, ctx + " sweep t")
                self.assertLess(math.hypot(ta[1].normal[0] - tp[1].normal[0],
                                           ta[1].normal[1] - tp[1].normal[1]), 2e-3, ctx + " sweep n")
        self.assertGreater(hits, 1500)
        self.assertGreater(sweeps, 1500)


class SpriteCase(unittest.TestCase):
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

    def tile(self, x, y, size=64.0, group="chao", **kw):
        t = Sprite(TILE, size=size, center=(x, y), group=group, **kw)
        t.mass = STATIC
        self.owned.append(t)
        return t

    def kinds(self, shape):
        cs = get_collision_system()
        c = C.ensure_collider(shape)
        cs._update_proxy(c, commit_motion=False)
        return [p.kind for p in cs._world_prims(c)]


class TestSpriteHulls(SpriteCase):
    def test_opaque_tile_is_an_aabb(self):
        t = self.tile(1000.0, 1000.0)
        self.assertEqual(self.kinds(t), [K.AABB])

    def test_flip_and_scale_keep_it_an_aabb(self):
        t = self.tile(2000.0, 1000.0)
        t.flip_x = True
        t.scale = 1.7
        self.assertEqual(self.kinds(t), [K.AABB])
        box = get_collision_system()._world_prims(C.ensure_collider(t))[0].aabb
        self.assertAlmostEqual(box[2] - box[0], 64.0 * 1.7, delta=1e-6)

    def test_a_turn_keeps_the_polygon(self):
        t = self.tile(3000.0, 1000.0)
        for angle in (15.0, 0.001, 89.0):
            t.angle = angle
            self.assertEqual(self.kinds(t), [K.POLY], f"angle {angle}")
        t.angle = 90.0
        self.assertEqual(self.kinds(t), [K.AABB], "a quarter turn of a box is a box")

    def test_switch_off_keeps_the_polygon(self):
        t = self.tile(4000.0, 1000.0)
        with mock.patch.object(C, "_HULL_AABB", False):
            t.move_by(1.0, 0.0)
            self.assertEqual(self.kinds(t), [K.POLY])


@with_floor
class TestWalkersAgree(SpriteCase):
    """A walker on a row of tiles (gaps, steps) behaves the same either way."""

    def run_walk(self, seed, on):
        reset_collision_system()
        r = random.Random(seed)
        o = 10000.0 + seed * 3000.0
        x = 0.0
        top = 0.0
        tiles = []
        while x < 1400.0:
            if r.random() < 0.1:
                x += r.choice((40.0, 70.0))
                continue
            if r.random() < 0.2:
                top += r.choice((-20.0, 16.0))
            tiles.append(self.tile(o + x + 32.0, o + top - 32.0))
            x += 64.0
        hero = Rect(center=(o + 80.0, o + 120.0), width=24.0, height=40.0, group="heroi")
        hero.mass = 1.0
        hero.vel = Vec2(0.0, 0.0)
        self.owned.append(hero)
        resolve("heroi", "chao", bounce=0.0)
        trace = []
        with mock.patch.object(C, "_HULL_AABB", on):
            for f in range(240):
                grounded = "bottom" in hero.touching_sides
                if grounded and not hero.floor_below(dx=30.0):
                    hero.vel.y = 520.0
                hero.vel.x = 220.0
                hero.vel.y -= 1400.0 / 60.0
                hero.move_by(hero.vel.x / 60.0, hero.vel.y / 60.0)
                get_collision_system().step()
                if "bottom" in hero.touching_sides and hero.vel.y < 0:
                    hero.vel.y = 0.0
                trace.append((float(hero.center.x) - o, float(hero.center.y) - o,
                              tuple(sorted(hero.touching_sides))))
        for t in tiles + [hero]:
            t.destroy()
        self.owned.clear()
        return trace

    def test_same_walk(self):
        landed = 0
        for seed in range(6):
            a = self.run_walk(seed, False)
            b = self.run_walk(seed, True)
            for f, (pa, pb) in enumerate(zip(a, b)):
                self.assertLess(abs(pa[0] - pb[0]) + abs(pa[1] - pb[1]), 0.5,
                                f"seed {seed} frame {f}: {pa} vs {pb}")
                self.assertEqual(pa[2], pb[2], f"seed {seed} frame {f}: sides")
            landed += sum(1 for p in a if "bottom" in p[2])
        self.assertGreater(landed, 600, "fixture: the walker must spend time on the tiles")


class TestCanary(unittest.TestCase):
    def test_a_wrong_box_is_caught(self):
        def bad(verts, aabb):
            return True                                   # every quad becomes its box

        case = TestSameBoxSameAnswer("test_contacts_and_sweeps_agree")
        # A quad that is not a rectangle, converted anyway, must disagree.
        r = random.Random(3)
        disagreements = 0
        for _ in range(400):
            q = [(r.uniform(-30, -10), r.uniform(-30, -10)), (r.uniform(10, 30), r.uniform(-30, -10)),
                 (r.uniform(10, 30), r.uniform(10, 30)), (r.uniform(-30, -10), r.uniform(10, 30))]
            with mock.patch.object(C, "_is_axis_rect", bad):
                conv = C._prims_from_collision_specs([("poly", q)])[0]
            real = C._prims_from_collision_specs([("poly", q)])[0]
            o = P(K.CIRCLE, (-5, -5, 5, 5), (r.uniform(-40, 40), r.uniform(-40, 40), 8.0))
            a, b = C.narrow_phase(o, conv), C.narrow_phase(o, real)
            try:
                same_contact(case, a, b, "canary")
            except AssertionError:
                disagreements += 1
        self.assertGreater(disagreements, 20)


if __name__ == "__main__":
    unittest.main()
