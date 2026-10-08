"""Guard: every door that hands an author a CollisionInfo hands the same view.

Class guard for PM11 (``test_collision`` returned engine colliders and, for
half the pairs, the other body's normal). For one overlapping pair, the
``@collide`` pair handler, the entity's ``on_collide`` hook, ``@collide_stay``
on the next frame and ``test_collision(a, b)`` must agree: ``info.a`` is ``a``,
``info.b`` is ``b``, the same normal (from a to b), side, depth and point.
Random shapes, sizes and offsets, both argument orders.

    python -m unittest tests.test_collision_doors -v
"""
from __future__ import annotations

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import boot  # noqa: E402,F401  (profiles)
from hypothesis import assume, given, note, strategies as hst  # noqa: E402
from system_support import system_world  # noqa: E402

from scena import Circle, Polygon, Rect, collide, collide_stay  # noqa: E402
from scena import test_collision as query_collision  # noqa: E402  (not a test)

TOL = 1e-6


def _make(kind, center, size, group):
    x, y = center
    if kind == "circle":
        return Circle(center=center, radius=size, group=group)
    if kind == "rect":
        return Rect(center=center, width=2 * size, height=1.3 * size, group=group)
    s = size
    return Polygon(points=[(x - s, y - s), (x + s, y - 0.6 * s), (x + 0.2 * s, y + s)], group=group)


def _view(info):
    pt = info.point
    return (info.a, info.b, round(float(info.normal.x), 6), round(float(info.normal.y), 6),
            info.side, round(float(info.depth), 6),
            None if pt is None else (round(float(pt[0]), 6), round(float(pt[1]), 6)))


def _same(tc, got, want, door):
    a1, b1, *rest1 = got
    a2, b2, *rest2 = want
    tc.assertIs(a1, a2, f"{door}: info.a")
    tc.assertIs(b1, b2, f"{door}: info.b")
    for x, y, what in zip(rest1, rest2, ("normal.x", "normal.y", "side", "depth", "point")):
        if isinstance(x, float) and isinstance(y, float):
            tc.assertTrue(math.isclose(x, y, abs_tol=1e-5), f"{door}: {what} {x} vs {y}")
        elif isinstance(x, tuple) and isinstance(y, tuple):
            tc.assertTrue(all(math.isclose(p, q, abs_tol=1e-5) for p, q in zip(x, y)),
                          f"{door}: {what} {x} vs {y}")
        else:
            tc.assertEqual(x, y, f"{door}: {what}")


KINDS = hst.sampled_from(["circle", "rect", "polygon"])


class TestEveryDoorGivesTheSameView(unittest.TestCase):

    @given(ka=KINDS, kb=KINDS, sa=hst.integers(6, 30), sb=hst.integers(6, 30),
           dx=hst.integers(-12, 12), dy=hst.integers(-12, 12), swap=hst.booleans())
    def test_doors_agree(self, ka, kb, sa, sb, dx, dy, swap):
        with system_world(draw=False) as w:
            a = w.track(_make(ka, (300.0, 200.0), sa, "door_a"))
            b = w.track(_make(kb, (300.0 + dx, 200.0 + dy), sb, "door_b"))
            seen = {}

            def pair(me, other, info):
                seen.setdefault("collide", _view(info))

            def hook(me, other, info):
                seen.setdefault("on_collide", _view(info))

            def stay(me, other, info):
                seen.setdefault("stay", _view(info))
            collide("door_a", "door_b")(pair)
            collide_stay("door_a", "door_b")(stay)
            a.on_collide = hook
            w.step(1)
            # Not touching proves nothing; Hypothesis fails a health check if
            # too many draws are rejected (vacuity guard).
            assume("collide" in seen)
            w.step(1)
            q = query_collision(a, b)
            self.assertIsNotNone(q, "the handler saw a contact the query did not")
            want = _view(q)
            note(f"query view {want}")
            for door in ("collide", "on_collide", "stay"):
                if door in seen:
                    _same(self, seen[door], want, door)
            # Reversed arguments reverse the normal when the centres differ along
            # it. Level centres (concentric circles, equal rects side by side
            # pushed apart vertically) have no direction: the narrow phase takes
            # a fallback in argument order, the same for a handler declared
            # (a, b) and a query (a, b) — compared above — but not antisymmetric.
            ca, cb = a.center, b.center
            along = (float(cb.x) - float(ca.x)) * want[2] + (float(cb.y) - float(ca.y)) * want[3]
            if swap and abs(along) > 1e-9:
                back = _view(query_collision(b, a))
                self.assertIs(back[0], b)
                self.assertIs(back[1], a)
                self.assertTrue(math.isclose(back[2], -want[2], abs_tol=1e-5)
                                and math.isclose(back[3], -want[3], abs_tol=1e-5),
                                f"reversed query normal {back[2:4]} vs {want[2:4]}")


class TestDoorsCanary(unittest.TestCase):
    def test_a_raw_query_is_caught(self):
        from diff_support import assert_catches
        import scena.collision  # noqa: F401
        CS = type(sys.modules["scena.collision"].get_collision_system())
        real = CS.test_collision

        def raw(self, a, b):        # PM11: the raw canonical payload
            lefts = self._colliders_for_query(a)
            rights = self._colliders_for_query(b)
            for ca in lefts:
                for cb in rights:
                    info = self._collision_info_for_colliders(ca, cb)
                    if info is not None:
                        return info
            return None
        assert_catches(self, "test_collision_doors.TestEveryDoorGivesTheSameView.test_doors_agree",
                       [(CS, "test_collision", raw)], "a query that skips the author view")
        self.assertIsNotNone(real)


if __name__ == "__main__":
    unittest.main()
