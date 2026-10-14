"""A convex polygon swept against another takes the exact swept SAT.

Rule under test (Collision Design.md, "Polygon sweeps"): one convex polygon
prim (AABB, OBB, a convex POLY ring) moving against another is swept in
closed form (``_toi_sat``): a start overlap is the narrow contact; otherwise
the exact entry time and the normal of the face it enters through. Circles,
ellipses, capsules, rings that are not convex and multi-prim sets keep
conservative advancement (GJK). ``collision._SWEEP_SAT = False`` is the
oracle.

Advancement stops once the gap is under 1e-3, so the two differ only inside
that skin: SAT is never earlier, at most 1e-3 later along the normal, and
gives the same normal. A grazing pass inside the skin that never touches is
a hit for advancement and no hit for SAT; the tests prove SAT right there
(no overlap anywhere along the path).

Bug class guarded: a closed-form sweep that misses a face (a missing axis:
the body tunnels) or reads a corner graze as a wall.
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
from scena.scenamath import Vec2
from scena.shapes import Rect
from scena.sprite import Sprite

C = sys.modules["scena.collision"]   # the module (``scena.collision`` is the facade)
P, K = C.Prim, C.PrimKind
TILES = os.path.join(ROOT, "examples", "media", "tilesets", "Tiles")
ROUND = ("13.png", "15.png", "1.png", "3.png", "9.png")     # hulls that are not boxes
# Tutorial 27's platform end (tile 15 at 80 DU): the hull walkers probe.
END = [(760.0, 419.0625), (837.5, 419.0625), (840.0, 416.5353260869565),
       (840.0, 401.3722826086956), (837.5, 393.7907608695652),
       (830.0, 386.20923913043475), (780.0, 360.9375), (760.0, 360.9375)]


def hull(pts):
    pts = sorted(set(pts))

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]


def poly(v):
    return P(K.POLY, C._aabb_from_verts(v), (), list(v))


def box(x0, y0, x1, y1):
    return P(K.AABB, (x0, y0, x1, y1), (x0, y0, x1, y1))


def convex(r, cx, cy):
    k = r.random()
    if k < 0.3:
        w, h = r.uniform(2, 40), r.uniform(2, 40)
        return box(cx - w, cy - h, cx + w, cy + h)
    if k < 0.5:
        hw, hh, a = r.uniform(2, 30), r.uniform(2, 30), r.uniform(-3, 3)
        return P(K.OBB, C._aabb_from_obb(cx, cy, hw, hh, a), (cx, cy, hw, hh, a))
    v = hull([(cx + r.uniform(-30, 30), cy + r.uniform(-30, 30)) for _ in range(r.randint(3, 9))])
    if len(v) < 3:
        return convex(r, cx, cy)
    return poly(v if r.random() < 0.5 else v[::-1])


def advance(a, b, dx, dy):
    with mock.patch.object(C, "_SWEEP_SAT", False):
        return C._toi_prim_sets([a], [b], dx, dy)


def never_overlaps(a, b, dx, dy, samples=200):
    """No pose along the path overlaps by more than float noise."""
    for k in range(samples + 1):
        t = k / samples
        c = C._narrow_any(C._copy_translate([a], dx * t, dy * t), [b])
        if c is not None and c.depth > 1e-7:
            return False
    return True


class TestSameAsAdvancement(unittest.TestCase):
    def test_random_convex_pairs(self):
        r = random.Random(1)
        hits = starts = 0
        for i in range(5000):
            a = convex(r, 0.0, 0.0)
            b = convex(r, r.uniform(-80, 80), r.uniform(-80, 80))
            dx = 0.0 if r.random() < 0.2 else r.uniform(-150, 150)
            dy = 0.0 if r.random() < 0.2 else r.uniform(-150, 150)
            if not (dx or dy):
                continue
            ctx = f"case {i}: {a.kind.name} vs {b.kind.name} by ({dx:.3f}, {dy:.3f})"
            s = C._toi_sat(a, b, dx, dy)
            g = advance(a, b, dx, dy)
            self.assertEqual(s is None, g is None, ctx + ": one hits, one misses")
            if s is None:
                continue
            n = s[1].normal
            dn = g[1].normal
            if s[0] == 0.0 and g[0] == 0.0:
                starts += 1
                self.assertGreater(n[0] * dn[0] + n[1] * dn[1], 0.999, ctx + ": start normal")
                if s[1].points and g[1].points:          # both the narrow contact
                    self.assertEqual(s[1].depth, g[1].depth, ctx + ": start depth")
                continue
            hits += 1
            length = math.hypot(dx, dy)
            closing = (dx * n[0] + dy * n[1]) / length
            if s[0] > 0.0:
                self.assertGreater(closing, 0.0, ctx + ": the normal faces the motion")
            self.assertLessEqual(g[0], s[0] + 1e-9, ctx + ": advancement is never later")
            self.assertLessEqual((s[0] - g[0]) * length * closing, 1e-3 + 1e-9,
                                 ctx + ": within advancement's skin")
            self.assertGreater(n[0] * dn[0] + n[1] * dn[1], 0.999, ctx + ": same face")
        self.assertGreater(hits, 500)
        self.assertGreater(starts, 500)

    def test_entry_time_is_exact(self):
        """Touching at the SAT time; apart just before it."""
        r = random.Random(2)
        checked = 0
        for _ in range(3000):
            a = convex(r, 0.0, 0.0)
            b = convex(r, r.uniform(-80, 80), r.uniform(-80, 80))
            dx, dy = r.uniform(-150, 150), r.uniform(-150, 150)
            s = C._toi_sat(a, b, dx, dy)
            if s is None or s[0] == 0.0:
                continue
            length = math.hypot(dx, dy)
            n = s[1].normal
            if (dx * n[0] + dy * n[1]) / length < 0.1:
                continue                                 # grazing: no clean "just before"
            at = C._copy_translate([a], dx * s[0], dy * s[0])
            self.assertLess(C._gjk_distance(at, [b])[0], 1e-6, "touching at the entry time")
            back = s[0] - 1e-3 / length
            if back > 0.0:
                before = C._copy_translate([a], dx * back, dy * back)
                self.assertIsNone(C._narrow_any(before, [b]), "apart just before it")
            checked += 1
        self.assertGreater(checked, 500)


class TestGrazing(unittest.TestCase):
    """A box beside or on the platform end, inside and outside the skin."""

    def test_disagreements_are_skin_only(self):
        b = poly(END)
        r = random.Random(3)
        disagree = 0
        for i in range(6000):
            w, h = r.uniform(5, 20), r.uniform(5, 30)
            gap = r.choice((0.0, 1e-9, 1e-6, 1e-4, 1e-3, 2e-3, 0.08))
            if r.random() < 0.5:
                x, y = r.uniform(700, 900), 419.0625 + h + gap        # on the top face
            else:
                x, y = 840.0 + w + gap, r.uniform(380, 440)           # beside the right face
            a = box(x - w, y - h, x + w, y + h)
            dx, dy = r.choice(((r.uniform(-60, 60), 0.0), (r.uniform(-60, 60), r.uniform(-5, 0)),
                               (0.0, -r.uniform(0.1, 30)), (-r.uniform(0.1, 30), r.uniform(-3, 3))))
            if not (dx or dy):
                continue
            ctx = f"case {i}: gap {gap} by ({dx:.3f}, {dy:.3f})"
            s = C._toi_sat(a, b, dx, dy)
            g = advance(a, b, dx, dy)
            if s is None:
                self.assertTrue(never_overlaps(a, b, dx, dy), ctx + ": SAT missed an overlap")
                if g is not None:
                    disagree += 1
                continue
            length = math.hypot(dx, dy)
            n = s[1].normal
            at = C._copy_translate([a], dx * s[0], dy * s[0])
            self.assertLess(C._gjk_distance(at, [b])[0], 1e-6, ctx + ": SAT hit is a touch")
            if s[0] > 0.0:
                self.assertGreater(dx * n[0] + dy * n[1], 0.0, ctx + ": approaching face")
        self.assertGreater(disagree, 50, "fixture: the skin cases must occur")


class TestFallbacks(unittest.TestCase):
    def test_round_and_concave_prims_advance(self):
        a = box(-5, -5, 5, 5)
        circle = P(K.CIRCLE, (15, -5, 25, 5), (20.0, 0.0, 5.0))
        self.assertIs(C._toi_sat(a, circle, 30.0, 0.0), C._TOI_UNRESOLVED)
        self.assertIs(C._toi_sat(circle, a, -30.0, 0.0), C._TOI_UNRESOLVED)
        concave = poly([(10, -5), (30, -5), (20, 0), (30, 5), (10, 5)])
        self.assertIs(C._toi_sat(a, concave, 30.0, 0.0), C._TOI_UNRESOLVED)
        flat = poly([(10, 0), (20, 0), (30, 0)])
        self.assertIs(C._toi_sat(a, flat, 30.0, 0.0), C._TOI_UNRESOLVED)

    def test_convex_ring(self):
        sq = [(0, 0), (1, 0), (1, 1), (0, 1)]
        self.assertTrue(C._convex_ring(sq))
        self.assertTrue(C._convex_ring(sq[::-1]))
        self.assertTrue(C._convex_ring([(0, 0), (1, 0), (2, 0), (2, 1), (0, 1)]), "collinear run")
        self.assertTrue(C._convex_ring(END))
        star = [(math.cos(4 * math.pi * k / 5), math.sin(4 * math.pi * k / 5)) for k in range(5)]
        self.assertFalse(C._convex_ring(star), "a star turns one way and winds twice")
        self.assertFalse(C._convex_ring([(0, 0), (2, 0), (1, 0.5), (2, 2), (0, 2)]))
        self.assertFalse(C._convex_ring([(0, 0), (1, 0), (2, 0)]), "no area")

    def test_multi_prim_sets_advance(self):
        a = [box(-5, -5, 5, 5)]
        pair = [poly([(10, -5), (20, -5), (20, 5)]), poly([(10, -5), (20, 5), (10, 5)])]
        with mock.patch.object(C, "_toi_sat", side_effect=AssertionError("SAT on a set")):
            C._toi_prim_sets(a, pair, 30.0, 0.0)


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
        self.owned.clear()
        reset_collision_system()


class TestWalkersAgree(SpriteCase):
    """A walker over rounded tiles walks, lands and probes the same either way."""

    def run_walk(self, seed, on):
        reset_collision_system()
        r = random.Random(seed)
        o = 20000.0 + seed * 3000.0
        x = 0.0
        top = 0.0
        tiles = []
        while x < 1400.0:
            if r.random() < 0.1:
                x += r.choice((40.0, 70.0))
                continue
            if r.random() < 0.2:
                top += r.choice((-20.0, 16.0))
            t = Sprite(os.path.join(TILES, r.choice(ROUND + ("2.png",))), size=64.0,
                       center=(o + x + 32.0, o + top - 32.0), group="chao")
            t.mass = STATIC
            self.owned.append(t)
            tiles.append(t)
            x += 64.0
        hero = Rect(center=(o + 80.0, o + 120.0), width=24.0, height=40.0, group="heroi")
        hero.mass = 1.0
        hero.vel = Vec2(0.0, 0.0)
        self.owned.append(hero)
        resolve("heroi", "chao", bounce=0.0)
        trace = []
        cs = get_collision_system()
        tops = [max(p.aabb[3] for p in cs._world_prims(C.ensure_collider(t))) for t in tiles]
        with mock.patch.object(C, "_SWEEP_SAT", on):
            for f in range(240):
                grounded = "bottom" in hero.touching_sides
                ahead = hero.floor_below(dx=30.0)
                if grounded and not ahead:
                    hero.vel.y = 520.0
                hero.vel.x = 220.0
                hero.vel.y -= 1400.0 / 60.0
                hero.move_by(hero.vel.x / 60.0, hero.vel.y / 60.0)
                get_collision_system().step()
                if "bottom" in hero.touching_sides and hero.vel.y < 0:
                    hero.vel.y = 0.0
                trace.append((float(hero.center.x) - o, float(hero.center.y) - o,
                              tuple(sorted(hero.touching_sides)),
                              None if ahead is None else tiles.index(ahead), tops))
        for t in self.owned:
            t.destroy()
        self.owned.clear()
        return trace

    def test_same_walk(self):
        landed = 0
        for seed in range(6):
            a = self.run_walk(seed, False)
            b = self.run_walk(seed, True)
            for f, (pa, pb) in enumerate(zip(a, b)):
                self.assertLess(abs(pa[0] - pb[0]) + abs(pa[1] - pb[1]), 0.05,
                                f"seed {seed} frame {f}: {pa} vs {pb}")
                self.assertEqual(pa[2], pb[2], f"seed {seed} frame {f}: sides")
                self.assertEqual(pa[3] is None, pb[3] is None, f"seed {seed} frame {f}: floor ahead")
                if pa[3] != pb[3]:
                    # Two tiles level under the probe: either is the floor.
                    self.assertLess(abs(pa[4][pa[3]] - pb[4][pb[3]]), 1e-3,
                                    f"seed {seed} frame {f}: floors at different heights")
            landed += sum(1 for p in a if "bottom" in p[2])
        self.assertGreater(landed, 600, "fixture: the walker must spend time on the tiles")


class TestCanary(unittest.TestCase):
    def test_a_missing_axis_is_caught(self):
        """SAT on the moving polygon's faces only: some sweeps tunnel."""
        real = C._sat_ring

        def sat_a_axes(pa, pb, dx, dy):
            va, vb = real(pa), real(pb)
            if va is None or vb is None:
                return C._TOI_UNRESOLVED
            return _sweep_axes(va, vb, dx, dy, pa, pb)

        case = TestSameAsAdvancement("test_random_convex_pairs")
        with mock.patch.object(C, "_toi_sat", sat_a_axes):
            with self.assertRaises(AssertionError):
                case.test_random_convex_pairs()


def _sweep_axes(va, vb, dx, dy, pa, pb):
    """``_toi_sat`` with the axes of ``va`` only (the planted bug)."""
    t_enter, t_exit, best = -math.inf, math.inf, (0.0, 0.0)
    px, py = va[-1]
    for qx, qy in va:
        ex, ey = qx - px, qy - py
        px, py = qx, qy
        el = math.hypot(ex, ey)
        if el < 1e-12:
            continue
        nx, ny = ey / el, -ex / el
        pa_ = [x * nx + y * ny for x, y in va]
        pb_ = [x * nx + y * ny for x, y in vb]
        v = dx * nx + dy * ny
        if abs(v) < 1e-15:
            if max(pa_) < min(pb_) or min(pa_) > max(pb_):
                return None
            continue
        if v > 0:
            te, tx, s = (min(pb_) - max(pa_)) / v, (max(pb_) - min(pa_)) / v, (nx, ny)
        else:
            te, tx, s = (max(pb_) - min(pa_)) / v, (min(pb_) - max(pa_)) / v, (-nx, -ny)
        if te > t_enter:
            t_enter, best = te, s
        t_exit = min(t_exit, tx)
        if t_enter > t_exit or t_exit < 0.0 or t_enter > 1.0:
            return None
    if t_enter == -math.inf:
        return None
    if t_enter * math.hypot(dx, dy) <= 1e-6:
        c = C.narrow_phase(pa, pb) if C._aabb_overlap_tuple(pa.aabb, pb.aabb) else None
        if c is not None:
            return (0.0, c)
    return (max(0.0, t_enter), C.Contact(best, 0.0, []))


if __name__ == "__main__":
    unittest.main()
