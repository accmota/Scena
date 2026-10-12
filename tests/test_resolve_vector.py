"""Resolve passes over a large partner pool give the same frames either way.

Rule under test (Collision Design.md, "Moved set and vectorized candidates",
resolve pools): a body's resolve partners, when there are many, are a
``_PartnerPool`` of rows in the proxy mirror (proxy, motion, box over the
frame). Each partner scan (sweep casts, the unswept-bounds recovery, the
settle passes, ``floor_below()`` without ``group=``) keeps the rows that pass
its own test, in partner order, and still runs that test on them.
``collision._RESOLVE_VECTOR = False`` scans every partner in Python (the
oracle). The answers must be identical, bit for bit: same tests, same order.

Worlds: walkers on static tiles with one-way platforms and a moving lift; a
mutual crowd with walls; bodies spawned, destroyed and placed between
frames. ``_POOL_VECTOR_MIN`` is lowered so small worlds take the pool too.
``SCENA_VERIFY_POSE_REV=1`` (every tier) also checks each prefilter against
the Python test.

Bug class guarded: a mirror row out of date (a nudge or a motion that did not
mark it), a prefilter that drops a partner, a re-query that skips one.
"""
import os
import random
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scena.collision import STATIC, get_collision_system, reset_collision_system, resolve
from scena.scenamath import Vec2
from scena.shapes import Circle, Polygon, Rect

C = sys.modules["scena.collision"]   # the module (``scena.collision`` is the facade)
DT = 1.0 / 60.0


def pose(s):
    return (float(s.center.x), float(s.center.y), tuple(sorted(s.touching_sides)))


class World:
    """One seeded scene; ``run`` returns its trace."""

    def __init__(self, seed, origin):
        self.r = random.Random(seed)
        self.o = origin
        self.owned = []

    def keep(self, s):
        self.owned.append(s)
        return s

    def static(self, s):
        s.mass = STATIC
        return self.keep(s)

    def body(self, s):
        s.mass = 1.0
        s.vel = Vec2(0.0, 0.0)
        return self.keep(s)

    def destroy(self):
        for s in self.owned:
            try:
                s.destroy()
            except Exception:
                pass
        self.owned.clear()


class Platformer(World):
    def build(self):
        r, o = self.r, self.o
        x, top = 0.0, 0.0
        while x < 2400.0:
            if r.random() < 0.1:
                x += r.choice((40.0, 90.0))
                continue
            if r.random() < 0.2:
                top += r.choice((-24.0, 18.0))
            w = r.choice((32.0, 64.0))
            if r.random() < 0.15:
                g = Polygon(points=[(o + x, o + top), (o + x + w, o + top + 10.0),
                                    (o + x + w, o + top - 30.0), (o + x, o + top - 30.0)],
                            group="chao")
            else:
                g = Rect(center=(o + x + w / 2.0, o + top - 16.0), width=w, height=32.0,
                         group="chao")
            self.static(g)
            if r.random() < 0.2:
                self.static(Rect(center=(o + x + w / 2.0, o + top + 70.0), width=w,
                                 height=8.0, group="tabua"))
            x += w
        self.lift = self.static(Rect(center=(o + 600.0, o + 40.0), width=80.0, height=12.0,
                                     group="chao"))
        self.walkers = [self.body(Rect(center=(o + 80.0 + 140.0 * i, o + 160.0),
                                       width=r.uniform(14, 26), height=r.uniform(24, 44),
                                       group="robo"))
                        for i in range(12)]
        resolve("robo", "chao", bounce=0.0)
        resolve("robo", "tabua", bounce=0.0, only="bottom")

    def frame(self, f):
        r = self.r
        self.lift.move_by(0.0, 60.0 * DT * (1 if (f // 50) % 2 == 0 else -1))
        out = []
        for i, w in enumerate(self.walkers):
            ahead = w.floor_below(dx=24.0 if i % 2 == 0 else -24.0)
            if "bottom" in w.touching_sides and (ahead is None or r.random() < 0.02):
                w.vel.y = 420.0
            w.vel.x = 150.0 if i % 2 == 0 else -150.0
            w.vel.y -= 1300.0 * DT
            w.move_by(w.vel.x * DT, w.vel.y * DT)
            out.append(None if ahead is None else self.owned.index(ahead))
        if f % 40 == 39:
            w = r.choice(self.walkers)
            w.center = (self.o + r.uniform(0, 2300), self.o + 200.0)   # placement
            w.vel = Vec2(0.0, 0.0)
        get_collision_system().step()
        for w in self.walkers:
            if "bottom" in w.touching_sides and w.vel.y < 0.0:
                w.vel.y = 0.0
        return out + [pose(w) for w in self.walkers]


class Crowd(World):
    def build(self):
        r, o = self.r, self.o
        for k in range(10):
            self.static(Rect(center=(o + r.uniform(-400, 400), o + r.uniform(-300, 300)),
                             width=r.uniform(20, 80), height=r.uniform(20, 80), group="parede"))
        self.mob = []
        for _ in range(60):
            self.spawn()
        resolve("mob", "mob", bounce=0.0)
        resolve("mob", "parede", bounce=0.0)

    def spawn(self):
        r, o = self.r, self.o
        x, y = o + r.uniform(-450, 450), o + r.uniform(-350, 350)
        s = (Circle(center=(x, y), radius=r.uniform(6, 14), group="mob") if r.random() < 0.6
             else Rect(center=(x, y), width=r.uniform(10, 26), height=r.uniform(10, 26),
                       group="mob"))
        self.mob.append(self.body(s))

    def frame(self, f):
        r, o = self.r, self.o
        tx, ty = o + 200.0 * ((f // 60) % 2 * 2 - 1), o
        for s in self.mob:
            dx, dy = tx - float(s.center.x), ty - float(s.center.y)
            d = max(1.0, (dx * dx + dy * dy) ** 0.5)
            s.move_by(140.0 * DT * dx / d, 140.0 * DT * dy / d)
        if f % 10 == 9:
            gone = self.mob.pop(r.randrange(len(self.mob)))
            gone.destroy()
            self.spawn()
        get_collision_system().step()
        return [pose(s) for s in self.mob]


class SameFrames(unittest.TestCase):
    def run_world(self, cls, seed, on, frames):
        reset_collision_system()
        w = cls(seed, 50000.0 + 5000.0 * seed)
        trace = []
        try:
            with mock.patch.object(C, "_RESOLVE_VECTOR", on), \
                    mock.patch.object(C, "_POOL_VECTOR_MIN", 8):
                w.build()
                for f in range(frames):
                    trace.append(w.frame(f))
        finally:
            w.destroy()
            reset_collision_system()
        return trace

    def same(self, cls, seeds, frames):
        touching = 0
        for seed in seeds:
            a = self.run_world(cls, seed, False, frames)
            b = self.run_world(cls, seed, True, frames)
            for f, (fa, fb) in enumerate(zip(a, b)):
                self.assertEqual(fa, fb, f"{cls.__name__} seed {seed} frame {f}")
                touching += sum(1 for p in fa if isinstance(p, tuple) and p[2])
        return touching

    def test_platformer(self):
        touching = self.same(Platformer, range(2), 150)
        self.assertGreater(touching, 1500, "fixture: walkers must stand and bump")

    def test_crowd(self):
        touching = self.same(Crowd, range(2), 120)
        self.assertGreater(touching, 2000, "fixture: the crowd must press together")

    def test_the_pool_is_used(self):
        reset_collision_system()
        w = Platformer(9, 90000.0)
        calls = []
        real = C._PartnerPool.near_box
        try:
            with mock.patch.object(C, "_POOL_VECTOR_MIN", 8), \
                    mock.patch.object(C._PartnerPool, "near_box",
                                      lambda self, *a: calls.append(1) or real(self, *a)):
                w.build()
                for f in range(5):
                    w.frame(f)
        finally:
            w.destroy()
            reset_collision_system()
        self.assertTrue(calls, "fixture: the pools must take the vector path")


class SameFramesShared(SameFrames):
    """The shared partner lists against one list per body (``_SHARED_PARTNERS``)."""

    def run_world(self, cls, seed, on, frames):
        with mock.patch.object(C, "_SHARED_PARTNERS", on):
            return super().run_world(cls, seed, True, frames)

    def test_the_pool_is_used(self):
        pass


class SameFramesLocal(SameFrames):
    """One prefilter query per body's turn against one per pass (``_LOCAL_PREFILTER``)."""

    def run_world(self, cls, seed, on, frames):
        with mock.patch.object(C, "_LOCAL_PREFILTER", on):
            return super().run_world(cls, seed, True, frames)

    def test_the_pool_is_used(self):
        pass


class TestCanary(unittest.TestCase):
    def test_a_stale_mirror_is_caught(self):
        """The mirror never takes dirty rows: nudged bodies keep old boxes."""
        real = C.CollisionSystem._box_array

        def stale(self_):
            self_._row_dirty.clear()
            return real(self_)

        case = SameFrames("test_crowd")
        with mock.patch.object(C.CollisionSystem, "_box_array", stale), \
                mock.patch.object(C, "_POSE_REV_VERIFY", False):
            with self.assertRaises(AssertionError):
                case.test_crowd()


if __name__ == "__main__":
    unittest.main()
