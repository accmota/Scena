"""A formula that reads through a holder follows what it holds now (2026-10-17).

``nave.alvo = a; r = Circle(radius=lambda: nave.alvo.radius * 2)``: sources
were learned once, at link. A new ``nave.alvo = b`` re-ran the formula (the ink
field is a source since ce8f12b), but ``b.radius = 7`` was not heard and
``a.radius`` still was. Through an st cell it was worse: ``st.alvo.radius``
stopped the chain at the cell, so the object was never followed at all.

Bug class guarded here: **a formula whose sources stay on the object a holder
held at link time**. Every holder (ink field, st cell) × every kind of read
through the held object × every write (a new object, its change, the old
object's change, the same object again, None and back).
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import Circle, State, Vec2, init  # noqa: E402

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()


# What the formula reads through the held object. ``make(k)`` builds an object
# that reads ``k``; ``change(o, k)`` makes it read ``k``.
def _make_radius(k):
    return Circle(radius=k)


def _make_hp(k):
    o = Circle(radius=1)
    o.hp = k
    return o


def _make_center(k):
    return Circle(center=(k, 0), radius=1)


def _make_list(k):
    return [Circle(radius=k)]


def _make_inner(k):
    o = Circle(radius=1)
    o.alvo = Circle(radius=k)
    return o


def _set_radius(o, k):
    o.radius = k


def _set_hp(o, k):
    o.hp = k


def _set_center(o, k):
    o.center = (k, 0)


def _set_list(o, k):
    o[0].radius = k


def _set_inner(o, k):
    o.alvo.radius = k


# One formula per holder × kind: the static reader needs the chain spelled out.
def _ink_radius(nave, st):
    return lambda: nave.alvo.radius


def _ink_hp(nave, st):
    return lambda: nave.alvo.hp


def _ink_center(nave, st):
    return lambda: nave.alvo.center.x


def _ink_list(nave, st):
    return lambda: nave.alvo[0].radius


def _ink_inner(nave, st):
    return lambda: nave.alvo.alvo.radius


def _st_radius(nave, st):
    return lambda: st.alvo.radius


def _st_hp(nave, st):
    return lambda: st.alvo.hp


def _st_center(nave, st):
    return lambda: st.alvo.center.x


def _st_list(nave, st):
    return lambda: st.alvo[0].radius


def _st_inner(nave, st):
    return lambda: st.alvo.alvo.radius


_KINDS = {
    "radius": (_make_radius, _set_radius, _ink_radius, _st_radius),
    "ink field": (_make_hp, _set_hp, _ink_hp, _st_hp),
    "center.x": (_make_center, _set_center, _ink_center, _st_center),
    "list[0].radius": (_make_list, _set_list, _ink_list, _st_list),
    "holder in holder": (_make_inner, _set_inner, _ink_inner, _st_inner),
}

_HOLDERS = ("ink", "st")


def _objects(o):
    """The Scena objects inside a made value (for teardown)."""
    if isinstance(o, list):
        return list(o)
    out = [o]
    inner = (getattr(o, "_ink", None) or {}).get("alvo")
    if inner is not None:
        out.append(inner)
    return out


class _Case(unittest.TestCase):
    def setUp(self):
        init(width=800, height=600)
        self._owned = []

    def tearDown(self):
        for obj in reversed(self._owned):
            try:
                obj.destroy()
            except Exception:
                pass
        self._owned.clear()

    def track(self, obj):
        for o in _objects(obj):
            self._owned.append(o)
        return obj

    def rig(self, holder, kind, first):
        """A holder holding ``first`` and a Circle whose radius reads through it."""
        make, change, ink_formula, st_formula = _KINDS[kind]
        nave = self.track(Circle(center=(0, 0), radius=5))
        st = State(name="hud")
        if holder == "ink":
            def put(v):
                nave.alvo = v
            formula = ink_formula(nave, st)
        else:
            def put(v):
                st.alvo = v
            formula = st_formula(nave, st)
        put(first)
        r = self.track(Circle(center=(0, 0), radius=formula))
        return r, put, change

    @staticmethod
    def anchor(r):
        return r._ensure_scalar_anchor("radius")


class TestHolderMatrix(_Case):
    """holder × kind × write."""

    def each(self):
        for holder in _HOLDERS:
            for kind, (make, change, _, _) in _KINDS.items():
                yield holder, kind, make, change

    def test_follows_the_object_held_at_link(self):
        for holder, kind, make, change in self.each():
            with self.subTest(holder=holder, kind=kind):
                a = self.track(make(2))
                r, put, change = self.rig(holder, kind, a)
                self.assertEqual(r.radius, 2)
                change(a, 3)
                self.assertEqual(r.radius, 3)

    def test_follows_a_new_object(self):
        for holder, kind, make, change in self.each():
            with self.subTest(holder=holder, kind=kind):
                a = self.track(make(2))
                b = self.track(make(4))
                r, put, change = self.rig(holder, kind, a)
                put(b)
                self.assertEqual(r.radius, 4)
                change(b, 7)
                self.assertEqual(r.radius, 7)
                change(b, 8)
                self.assertEqual(r.radius, 8)

    def test_the_old_object_is_no_longer_a_source(self):
        for holder, kind, make, change in self.each():
            with self.subTest(holder=holder, kind=kind):
                a = self.track(make(2))
                b = self.track(make(4))
                r, put, change = self.rig(holder, kind, a)
                put(b)
                self.assertEqual(r.radius, 4)       # the pull re-points
                change(a, 9)
                self.assertFalse(self.anchor(r)._dirty, "a still notifies the formula")
                self.assertEqual(r.radius, 4)
                if not isinstance(a, list):
                    self.assertNotIn("_link_source", vars(a))

    def test_back_to_the_first_object(self):
        for holder, kind, make, change in self.each():
            with self.subTest(holder=holder, kind=kind):
                a = self.track(make(2))
                b = self.track(make(4))
                r, put, change = self.rig(holder, kind, a)
                put(b)
                self.assertEqual(r.radius, 4)
                put(a)
                self.assertEqual(r.radius, 2)
                change(a, 6)
                self.assertEqual(r.radius, 6)
                change(b, 1)
                self.assertFalse(self.anchor(r)._dirty)

    def test_the_same_object_again(self):
        for holder, kind, make, change in self.each():
            with self.subTest(holder=holder, kind=kind):
                a = self.track(make(2))
                r, put, change = self.rig(holder, kind, a)
                link = self.anchor(r)._link
                before = set(map(id, link.sources))
                put(a)
                self.assertEqual(r.radius, 2)
                self.assertEqual(set(map(id, link.sources)), before)
                change(a, 5)
                self.assertEqual(r.radius, 5)

    def test_unlink_drops_the_new_sources(self):
        for holder, kind, make, change in self.each():
            with self.subTest(holder=holder, kind=kind):
                a = self.track(make(2))
                b = self.track(make(4))
                r, put, change = self.rig(holder, kind, a)
                put(b)
                self.assertEqual(r.radius, 4)
                r["radius"].unlink()
                change(b, 7)
                self.assertEqual(r.radius, 4)
                for o in _objects(b):
                    self.assertNotIn("_link_source", vars(o))


class TestNoneAndBack(_Case):
    """A guarded formula: the holder holds None for a while."""

    def test_ink(self):
        nave = self.track(Circle(center=(0, 0), radius=5))
        a = self.track(Circle(radius=2))
        b = self.track(Circle(radius=3))
        nave.alvo = a
        r = self.track(Circle(radius=lambda: nave.alvo.radius if nave.alvo else 1))
        nave.alvo = None
        self.assertEqual(r.radius, 1)
        a.radius = 8
        self.assertFalse(self.anchor_dirty(r))
        nave.alvo = b
        self.assertEqual(r.radius, 3)
        b.radius = 6
        self.assertEqual(r.radius, 6)

    def test_st_linked_while_none(self):
        # An st cell may hold None at link (the chain stops at the cell).
        st = State(name="hud")
        st.alvo = None
        b = self.track(Circle(radius=3))
        r = self.track(Circle(radius=lambda: st.alvo.radius if st.alvo else 1))
        self.assertEqual(r.radius, 1)
        st.alvo = b
        self.assertEqual(r.radius, 3)
        b.radius = 6
        self.assertEqual(r.radius, 6)
        st.alvo = None
        self.assertEqual(r.radius, 1)

    def test_ink_none_at_link_is_still_refused(self):
        # Link time keeps its message: the formula names what it reads.
        nave = self.track(Circle(center=(0, 0), radius=5))
        nave.alvo = None
        with self.assertRaises(AttributeError) as cm:
            Circle(radius=lambda: nave.alvo.radius if nave.alvo else 1)
        self.assertIn("nave.alvo is None when the formula is linked", str(cm.exception))

    def test_an_object_without_the_attribute(self):
        # The chain stops at the holder; the formula's own guard decides.
        nave = self.track(Circle(center=(0, 0), radius=5))
        a = self.track(Circle(radius=2))
        b = self.track(Circle(radius=3))
        nave.alvo = a
        r = self.track(Circle(
            radius=lambda: nave.alvo.radius if hasattr(nave.alvo, "radius") else 1))
        nave.alvo = Vec2(1, 1)
        self.assertEqual(r.radius, 1)
        nave.alvo = b
        self.assertEqual(r.radius, 3)
        b.radius = 4
        self.assertEqual(r.radius, 4)

    @staticmethod
    def anchor_dirty(r):
        return r._ensure_scalar_anchor("radius")._dirty


class TestCostAndEdges(_Case):
    def test_no_holder_no_hop(self):
        # A formula that reads no object through a holder pays nothing.
        nave = self.track(Circle(center=(0, 0), radius=5))
        nave.hp = 3
        nave.desvio = Vec2(1, 2)
        st = State(name="hud")
        st.score = 2
        for formula in (lambda: nave.hp, lambda: st.score, lambda: nave.radius,
                        lambda: nave.center.x + 1):
            with self.subTest(formula=formula):
                r = self.track(Circle(radius=formula))
                self.assertIsNone(r._ensure_scalar_anchor("radius")._link._hops)

    def test_a_new_value_does_not_relearn(self):
        # A Vec2 or a number in the holder is its value: a new one per frame
        # must not re-learn the sources.
        nave = self.track(Circle(center=(0, 0), radius=5))
        nave.desvio = Vec2(1, 2)
        nave.nome = "ab"
        st = State(name="hud")
        st.pos = Vec2(1, 2)
        cases = (
            (lambda: nave.desvio.x + 1, lambda k: setattr(nave, "desvio", Vec2(k, 0) * 1)),
            (lambda: st.pos.x + 1, lambda k: setattr(st, "pos", Vec2(k, 0) * 1)),
            (lambda: len(nave.nome.upper()), lambda k: setattr(nave, "nome", "x" * k)),
        )
        for formula, write in cases:
            with self.subTest(formula=formula):
                r = self.track(Circle(radius=formula))
                link = r._ensure_scalar_anchor("radius")._link
                self.assertIsNotNone(link._hops)
                with mock.patch.object(type(link), "_extract_sources",
                                       side_effect=AssertionError("re-learned")):
                    for k in (3, 4, 5):
                        write(k)
                        self.assertGreater(r.radius, 0)

    def test_a_cycle_through_the_new_object_is_not_followed(self):
        nave = self.track(Circle(center=(0, 0), radius=5))
        a = self.track(Circle(radius=2))
        b = self.track(Circle(radius=3))
        nave.alvo = a
        r = self.track(Circle(radius=lambda: nave.alvo.radius * 2))
        with mock.patch("scena.process.report_author_warning") as warn:
            nave.alvo = r
            r.radius                                # no CircularReferenceError
        self.assertTrue(warn.called)
        self.assertIn("cannot depend on the value it defines", warn.call_args[0][1])
        link = r._ensure_scalar_anchor("radius")._link
        self.assertNotIn(r, list(link.sources))
        nave.alvo = b
        self.assertEqual(r.radius, 6)
        b.radius = 5
        self.assertEqual(r.radius, 10)

    def test_a_destroyed_old_object(self):
        nave = self.track(Circle(center=(0, 0), radius=5))
        a = Circle(radius=2)
        b = self.track(Circle(radius=3))
        nave.alvo = a
        r = self.track(Circle(radius=lambda: nave.alvo.radius))
        nave.alvo = b
        a.destroy()
        self.assertEqual(r.radius, 3)
        b.radius = 4
        self.assertEqual(r.radius, 4)

    def test_holder_through_a_default_arg(self):
        nave = self.track(Circle(center=(0, 0), radius=5))
        a = self.track(Circle(radius=2))
        b = self.track(Circle(radius=3))
        nave.alvo = a
        r = self.track(Circle(radius=lambda n=nave: n.alvo.radius + 1))
        nave.alvo = b
        self.assertEqual(r.radius, 4)
        b.radius = 9
        self.assertEqual(r.radius, 10)


if __name__ == "__main__":
    unittest.main()
