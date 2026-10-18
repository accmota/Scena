"""A formula that reads an Entity ink field follows the field (2026-10-16).

``mira = Circle(center=lambda: nave.center + nave.desvio)`` with ``nave.desvio``
a Vec2: the formula's source was the vector the field held at link time, not
the field. A vector from arithmetic (``Vec2.temp``, ``vec_from_angle``) is never
on the graph, so nothing it did reached the formula; a vector from ``Vec2(…)``
was followed in place but a new value (``nave.desvio = …``, ``*=``) was not.
And a list or dict in a field missed ``+=`` / ``|=``: the same object comes back.

Bug class guarded here: **a change to what a holder (ink field or st cell)
holds that the formulas reading the holder do not hear**. Every payload kind
times every in-place spelling times every holder; a completeness check fails
when Vec2 grows a method or operator that changes it in place and the matrix
does not cover it.
"""
from __future__ import annotations

import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import Circle, State, Vec2, init, on_change, vec_from_angle  # noqa: E402
from scena.state import get_scena_system  # noqa: E402

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()


# How a Vec2 payload is made: each lands on a different construction path.
_VEC_MAKERS = {
    "Vec2()": lambda: Vec2(50, 0),
    "v + w": lambda: Vec2(25, 0) + Vec2(25, 0),
    "v * k": lambda: Vec2(25, 0) * 2,
    "vec_from_angle": lambda: vec_from_angle(0, 50),
    "Vec2.temp": lambda: Vec2.temp(50, 0),
}


def _ink_write(attr):
    """In-place spellings through a holder ``h`` with field ``attr``."""
    def iadd(h):
        v = getattr(h, attr)
        v += (10, 5)
        setattr(h, attr, v)

    def isub(h):
        v = getattr(h, attr)
        v -= (10, 5)
        setattr(h, attr, v)

    def imul(h):
        v = getattr(h, attr)
        v *= 2                      # in place (VB9), assigned back
        setattr(h, attr, v)

    def itruediv(h):
        v = getattr(h, attr)
        v /= 2
        setattr(h, attr, v)

    def alias_iadd(h):
        v = getattr(h, attr)        # another name for the held vector
        v += (3, 4)                 # changes it, and nothing is assigned back

    def x_aug(h):
        getattr(h, attr).x += 7

    return {
        "<<": lambda h: getattr(h, attr) << (80, 30),
        "+=": iadd,
        "-=": isub,
        "*=": imul,
        "/=": itruediv,
        ".x =": lambda h: setattr(getattr(h, attr), "x", 70),
        ".y =": lambda h: setattr(getattr(h, attr), "y", -20),
        ".x +=": x_aug,
        "do_rotation": lambda h: getattr(h, attr).do_rotation(90),
        "alias +=": alias_iadd,
        "= new": lambda h: setattr(h, attr, vec_from_angle(0, 20)),
    }


# Spellings that change a Vec2 in place, by the name the completeness check
# finds them under (a public method, or an in-place operator).
_IN_PLACE_COVERED = {"__iadd__": "+=", "__isub__": "-=", "__lshift__": "<<",
                     "do_rotation": "do_rotation", "__imul__": "*=",
                     "__itruediv__": "/="}
# In-place operators that are not value writes: ``@=`` links (its own rules:
# Reactive Design, "What may be linked").
_IN_PLACE_NOT_WRITES = {"__imatmul__"}


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
        self._owned.append(obj)
        return obj

    def assertFollows(self, circle, want):
        got = (circle.center.x, circle.center.y)
        self.assertAlmostEqual(got[0], want[0], places=6, msg=f"got {got}, want {want}")
        self.assertAlmostEqual(got[1], want[1], places=6, msg=f"got {got}, want {want}")


class TestInkVec2Matrix(_Case):
    """Every Vec2 payload × every spelling, read by a formula and a DirectLink."""

    def test_formula_reading_the_field(self):
        for maker_name, make in _VEC_MAKERS.items():
            for spelling, write in _ink_write("desvio").items():
                with self.subTest(payload=maker_name, spelling=spelling):
                    nave = self.track(Circle(center=(100, 100), radius=5))
                    nave.desvio = make()
                    mira = self.track(Circle(center=lambda: nave.center + nave.desvio,
                                             radius=3))
                    self.assertFollows(mira, (150, 100))
                    write(nave)
                    d = nave.desvio
                    self.assertFollows(mira, (100 + d.x, 100 + d.y))

    def test_formula_reading_one_axis(self):
        # ``nave.desvio.x``: the chain stops at the field, as ``st.pos.x`` does.
        for spelling, write in _ink_write("desvio").items():
            with self.subTest(spelling=spelling):
                nave = self.track(Circle(center=(100, 100), radius=5))
                nave.desvio = Vec2.temp(50, 0)
                mira = self.track(Circle(center=lambda: (nave.desvio.x, 0), radius=3))
                write(nave)
                self.assertFollows(mira, (nave.desvio.x, 0))

    def test_direct_link_from_the_field(self):
        for spelling, write in _ink_write("desvio").items():
            with self.subTest(spelling=spelling):
                nave = self.track(Circle(center=(100, 100), radius=5))
                nave.desvio = Vec2(50, 0) + Vec2(0, 0)
                mira = self.track(Circle(radius=3))
                mira["center"] @= nave["desvio"]
                write(nave)
                d = nave.desvio
                self.assertFollows(mira, (d.x, d.y))

    def test_field_read_by_a_formula_made_before_the_value(self):
        # The anchor exists first; each later value gets the hook.
        nave = self.track(Circle(center=(0, 0), radius=5))
        nave.desvio = Vec2(1, 1)
        mira = self.track(Circle(center=lambda: nave.desvio, radius=3))
        for _ in range(3):
            nave.desvio = Vec2(2, 2) * 1      # a temp each time
            nave.desvio << (5, 6)
            self.assertFollows(mira, (5, 6))
            nave.desvio.do_rotation(90)
            self.assertFollows(mira, (-6, 5))

    def test_a_replaced_vector_no_longer_notifies(self):
        nave = self.track(Circle(center=(0, 0), radius=5))
        old = Vec2(1, 2)
        nave.desvio = old
        mira = self.track(Circle(center=lambda: nave.desvio, radius=3))
        nave.desvio = Vec2(3, 4)
        old << (9, 9)                          # a free vector again
        self.assertFollows(mira, (3, 4))
        self.assertNotIn("update", vars(old))
        self.assertNotIn("_held_payload", vars(old))
        self.assertFalse(old._needs_pull_invalidate)

    def test_an_aliased_owned_vector_is_followed(self):
        # ``nave.v0 = ball.vel`` keeps the object (ink stores by reference).
        ball = self.track(Circle(center=(0, 0), radius=5))
        ball.vel = (3, 4)
        nave = self.track(Circle(center=(0, 0), radius=5))
        nave.v0 = ball.vel
        mira = self.track(Circle(center=lambda: nave.v0, radius=3))
        ball.vel = (7, 8)
        self.assertFollows(mira, (7, 8))
        ball.vel.x = 1
        self.assertFollows(mira, (1, 8))

    def test_in_a_flush_callback(self):
        # A flush runs with the update manager busy: the batch skips update().
        st = State(name="hud")
        st.go = 0
        nave = self.track(Circle(center=(0, 0), radius=5))
        nave.desvio = Vec2(10, 0) + Vec2(0, 0)
        mira = self.track(Circle(center=lambda: nave.desvio, radius=3))

        def bump(value):
            alias = nave.desvio
            alias += (1, 0)
            nave.desvio.do_rotation(90)

        on_change(st["go"])(bump)
        st.go = 1
        get_scena_system().flush()
        self.assertFollows(mira, (0, 11))

    def test_length_and_angle_follow_every_spelling(self):
        # An off-graph held vector syncs only the computed fields it has
        # (``_HeldPayloadUpdate``): read before and after, never stale.
        import math
        for holder in ("ink", "cell"):
            writes = _ink_write("v")
            if holder == "cell":
                writes = {k: w for k, w in writes.items()
                          if k not in (".x =", ".y =", ".x +=")}
            for spelling, write in writes.items():
                for read_first in (False, True):
                    with self.subTest(holder=holder, spelling=spelling, read_first=read_first):
                        if holder == "ink":
                            h = self.track(Circle(center=(0, 0), radius=5))
                        else:
                            h = State(name="st")
                        h.v = Vec2(3, 4) + Vec2(0, 0)
                        self.track(Circle(center=lambda: h.v, radius=3))
                        if read_first:
                            self.assertEqual(h.v.length, 5)
                        write(h)
                        v = h.v
                        self.assertAlmostEqual(v.length, math.hypot(v.x, v.y))
                        self.assertAlmostEqual(v.angle, math.degrees(math.atan2(v.y, v.x)))

    def test_other_vec2s_are_untouched(self):
        free = Vec2(1, 2) + Vec2(0, 0)
        free.x = 5
        free << (3, 3)
        self.assertNotIn("update", vars(free))
        self.assertNotIn("_held_payload", vars(free))
        ball = self.track(Circle(center=(0, 0), radius=5))
        ball.vel = (1, 1)
        self.assertNotIn("update", vars(ball.vel))
        nave = self.track(Circle(center=(0, 0), radius=5))
        nave.v = Vec2(1, 1)                 # held, but no formula reads it
        self.assertNotIn("update", vars(nave.v))


class TestInkOtherPayloads(_Case):
    """Lists, dicts and objects in an ink field."""

    def test_list_and_dict_augmented_writes(self):
        nave = self.track(Circle(center=(0, 0), radius=5))
        nave.itens = [1]
        nave.d = {"a": 1}
        r = self.track(Circle(center=(0, 0), radius=lambda: 10 * len(nave.itens)))
        s = self.track(Circle(center=(0, 0), radius=lambda: 10 * len(nave.d)))
        nave.itens += [2]
        nave.d |= {"b": 2}
        self.assertEqual((r.radius, s.radius), (20, 20))
        nave.itens = nave.itens + [3]
        self.assertEqual(r.radius, 30)

    def test_append_is_silent_as_in_a_cell(self):
        # The documented rule for st too: write ``+= [x]`` (Reactive Design).
        nave = self.track(Circle(center=(0, 0), radius=5))
        nave.itens = [1]
        r = self.track(Circle(center=(0, 0), radius=lambda: 10 * len(nave.itens)))
        nave.itens.append(2)
        self.assertEqual(r.radius, 10)

    def test_an_object_in_the_field_is_followed_and_replaced(self):
        a = self.track(Circle(center=(0, 0), radius=4))
        b = self.track(Circle(center=(0, 0), radius=9))
        nave = self.track(Circle(center=(0, 0), radius=5))
        nave.alvo = a
        r = self.track(Circle(center=(0, 0), radius=lambda: nave.alvo.radius * 2))
        a.radius = 5
        self.assertEqual(r.radius, 10)          # the held object, as before
        nave.alvo = b
        self.assertEqual(r.radius, 18)          # a new value re-runs the formula


class TestCellVec2InPlace(_Case):
    """An st cell's Vec2: the spellings the cell accepts reach its formulas."""

    def test_every_accepted_spelling(self):
        writes = {k: v for k, v in _ink_write("pos").items()
                  if k not in (".x =", ".y =", ".x +=")}       # these raise (CS4)
        for spelling, write in writes.items():
            with self.subTest(spelling=spelling):
                st = State(name="st")
                st.pos = Vec2(50, 0)
                c = self.track(Circle(center=lambda: st.pos, radius=3))
                write(st)
                self.assertFollows(c, (st.pos.x, st.pos.y))

    def test_axis_write_still_raises(self):
        st = State(name="st")
        st.pos = Vec2(1, 2)
        with self.assertRaises(AttributeError):
            st.pos.x = 5


class TestInPlaceSpellingsComplete(unittest.TestCase):
    """A new way to change a Vec2 in place must join the matrix above."""

    _ARGS = {"other": Vec2(1, 1), "normal": Vec2(0, 1), "onto": Vec2(1, 0),
             "from_vec": Vec2(1, 0), "angle": 30, "t": 0.5,
             "min_length": 1, "max_length": 2, "x": 1, "y": 2}
    _SKIP = {"temp", "update", "unlink", "unlink_all"}   # a constructor; graph verbs

    def test_every_mutating_method_is_covered(self):
        init(width=800, height=600)
        found = set()
        for name, fn in inspect.getmembers(Vec2, callable):
            if name.startswith("_") or name in self._SKIP:
                continue
            params = list(inspect.signature(fn).parameters)[1:]
            missing = [p for p in params if p not in self._ARGS]
            self.assertFalse(missing, f"Vec2.{name}: add an argument for {missing} to _ARGS")
            v = Vec2(3, 4)
            fn(v, *[self._ARGS[p] for p in params])
            if (v.x, v.y) != (3, 4):
                found.add(name)
        found |= {n for n in vars(Vec2) if n.startswith("__i") and n != "__init__"
                  and n != "__init_subclass__" and n != "__iter__"}
        found.add("__lshift__")
        uncovered = found - set(_IN_PLACE_COVERED) - _IN_PLACE_NOT_WRITES
        self.assertFalse(uncovered, f"in-place Vec2 spellings with no matrix row: {uncovered}")
        for spelling in _IN_PLACE_COVERED.values():
            self.assertIn(spelling, _ink_write("f"))


if __name__ == "__main__":
    unittest.main()
