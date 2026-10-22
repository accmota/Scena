"""Doors on a value a holder keeps (RA2 follow-ups, after 0.9.0).

A cell or an Entity's own field holds a Vec2 (or a Point) by value, and the
value carries per-instance hooks that tell the holder about its changes. Three
leads from the 0.9.0 release audit, each a bug class:

* **A timed door accepted a target its first tick refused.** ``tween(st.v["x"],
  …)`` with ``st["v"] @= f`` started and then raised ``LinkedAttributeError``
  from the frame loop, far from the author's line. Every timed door × every
  linked holder: refused at the call, or unlinked under ``force=True``.
* **``copy.copy`` copied the hooks.** ``w = copy.copy(st.v); w.x = 5`` wrote
  ``st.v``; the copy of any Scena object shared the original's graph node. Every
  public Container class either copies its value or refuses with the spelling
  that makes a second one (a completeness check over ``scena.__all__``).
* **A message named the wrong subject.** ``st.pos += …`` with a Point in the
  cell talked of ``ship.center``; a linked Vec2 in a field said ``vec2``; ``v <<
  bala.vel`` after a destroy said ``Circle_vel``. Each message is checked for
  the subject the author wrote, and the fix it names is run.
"""
from __future__ import annotations

import copy
import inspect
import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scena  # noqa: E402
from scena import (  # noqa: E402
    Box, Circle, Entity, LinkedAttributeError, Point, State, Track, Vec2, clock, init, tween,
)
from scena.process import reset_process_scheduler, tick_processes  # noqa: E402
from scena.state import Attribute, Container  # noqa: E402

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()


class _Case(unittest.TestCase):
    def setUp(self):
        init(width=800, height=600)
        reset_process_scheduler()
        self._owned = []

    def tearDown(self):
        reset_process_scheduler()
        for obj in reversed(self._owned):
            try:
                obj.destroy()
            except Exception:
                pass
        self._owned.clear()

    def track(self, obj):
        self._owned.append(obj)
        return obj

    def frames(self, n=5, dt=0.1):
        for _ in range(n):
            clock.advance(dt)
            tick_processes()


# Linked holders: (name, build) → (holder label, the held value, unlink hint).
def _cell_vec(case):
    src = case.track(Circle(center=(10, 20), radius=5))
    st = State(name="st")
    st["v"] @= lambda: Vec2(src.center.x, 0)
    case.addCleanup(lambda: st["v"].is_linked and st["v"].unlink())
    return st, (lambda: st.v), "st['v'].unlink()", (lambda: st["v"].is_linked)


def _cell_point(case):
    src = case.track(Circle(center=(10, 20), radius=5))
    st = State(name="st")
    st["v"] @= lambda: src.center + (1, 1)
    case.addCleanup(lambda: st["v"].is_linked and st["v"].unlink())
    return st, (lambda: st.v), "st['v'].unlink()", (lambda: st["v"].is_linked)


def _ink_vec(case):
    src = case.track(Circle(center=(10, 20), radius=5))
    src.v = Vec2(0, 0)
    src.v @= lambda: Vec2(src.center.x, 0)
    case.addCleanup(lambda: src.v._link is not None and src.v.unlink())
    return src, (lambda: src.v), "circle.v.unlink()", (lambda: src.v._link is not None)


_HOLDERS = {"cell Vec2": _cell_vec, "cell Point": _cell_point, "ink Vec2": _ink_vec}

# Timed doors on the held value ``h``: (door, start, whether it takes Points only).
_TIMED_DOORS = {
    "tween(h['x'])": (lambda h, **kw: tween(h["x"], 100, time=0.3, **kw), False),
    "tween(h['y'])": (lambda h, **kw: tween(h["y"], 100, time=0.3, **kw), False),
    "tween(h)": (lambda h, **kw: tween(h, (50, 50), time=0.3, **kw), True),
    "h.move_to(time=)": (lambda h, **kw: h.move_to(50, 50, time=0.3, **kw), True),
    "h.move_by(time=)": (lambda h, **kw: h.move_by(5, 5, time=0.3, **kw), True),
    "h.move_along": (lambda h, **kw: h.move_along(
        Track.circle(center=(0, 0), radius=10), speed=50, **kw), True),
}


class TestTimedDoorsRefuseALinkedHolderAtTheCall(_Case):
    """``tween(st.v["x"], …)`` on a linked cell started and raised from the
    frame loop on its first tick (``tween(st.p, …)`` on a Point too). Every
    timed door × every linked holder refuses at the call and changes nothing;
    the ticks that follow raise nothing."""

    def test_every_timed_door_refuses_at_the_call(self):
        for holder, build in _HOLDERS.items():
            for door, (start, points_only) in _TIMED_DOORS.items():
                if points_only and holder != "cell Point":
                    continue
                with self.subTest(holder=holder, door=door):
                    reset_process_scheduler()
                    _bag, value, hint, _linked = build(self)
                    before = (value().x, value().y)
                    with self.assertRaises(LinkedAttributeError) as cm:
                        start(value())
                    self.assertIn(hint, str(cm.exception))
                    self.assertNotIn("vec2", str(cm.exception))
                    self.frames()           # nothing was started: no raise here
                    self.assertEqual((value().x, value().y), before)

    def test_force_unlinks_and_the_tween_reaches_its_end(self):
        for holder, build in _HOLDERS.items():
            with self.subTest(holder=holder):
                reset_process_scheduler()
                _bag, value, _hint, linked = build(self)
                with warnings.catch_warnings(record=True) as w:
                    warnings.simplefilter("always")
                    tween(value()["x"], 100, time=0.3, force=True)
                self.assertTrue(any("unlinked" in str(x.message) for x in w))
                self.assertFalse(linked())
                self.frames()
                self.assertAlmostEqual(value().x, 100.0)

    def test_an_unlinked_cell_still_tweens(self):
        """The pattern next to the refusal: no error, no warning."""
        st = State(name="st")
        st.v = Vec2(0, 0)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            tween(st.v["x"], 100, time=0.3)
            self.frames()
        self.assertEqual([str(x.message) for x in w], [])
        self.assertAlmostEqual(st.v.x, 100.0)


# Copies: every public Container class is a value kind or refuses.
_VALUE_KINDS = {"Vec2", "Point", "Box"}


def _public_containers():
    return sorted(n for n in scena.__all__
                  if inspect.isclass(getattr(scena, n, None))
                  and issubclass(getattr(scena, n), Container))


class TestCopyMakesAValueOrRefuses(_Case):
    """``copy.copy`` copied ``__dict__`` whole: a cell's vector kept the cell's
    write hook (``w.x = 5`` wrote ``st.v``) and every copy shared the original's
    graph node."""

    def _holders(self):
        """Ways a vector or point is held: (label, value, read back the holder)."""
        src = self.track(Circle(center=(10, 20), radius=5))
        st = State(name="st")
        st.v = Vec2(1, 2)
        src.aim = Vec2(1, 2)
        src.vel = (3, 4)
        st["L"] @= lambda: Vec2(src.center.x, 3)
        self.addCleanup(lambda: st["L"].unlink())
        st["P"] @= lambda: src.center + (1, 1)
        self.addCleanup(lambda: st["P"].unlink())
        st.p = Point(1, 2)
        self.track(st.p)
        return [
            ("st.v", lambda: st.v),
            ("ship.aim", lambda: src.aim),
            ("linked st.L", lambda: st.L),
            ("linked st.P", lambda: st.P),
            ("ship.center", lambda: src.center),
            ("ship.vel", lambda: src.vel),
            ("st.p (a Point actor)", lambda: st.p),
            ("free Vec2", lambda: Vec2(1, 2)),
        ]

    def test_a_copy_is_a_free_value_and_edits_reach_nothing(self):
        for label, read in self._holders():
            for how in (copy.copy, copy.deepcopy):
                with self.subTest(holder=label, how=how.__name__):
                    orig = read()
                    before = (orig.x, orig.y)
                    w = how(orig)
                    self.assertIsNot(w, orig)
                    self.assertIs(type(w), type(orig))
                    self.assertEqual((w.x, w.y), before)
                    d = w.__dict__
                    self.assertNotIn("_write_field", d)
                    self.assertNotIn("_held_payload", d)
                    self.assertIsNone(d.get("_owner"))
                    self.assertIsNone(d.get("_link"))
                    nid = orig.__dict__.get("_node_id")
                    if nid is not None:
                        self.assertNotEqual(d.get("_node_id"), nid)
                    w.x = 99                        # never refused, never shared
                    self.assertEqual((read().x, read().y), before)

    def test_a_copy_inside_a_container_is_a_value(self):
        st = State(name="st")
        st.v = Vec2(1, 2)
        items = copy.deepcopy([st.v, {"v": st.v}])
        items[0].x = 7
        items[1]["v"].y = 7
        self.assertEqual((st.v.x, st.v.y), (1.0, 2.0))

    def test_a_box_copies_its_region(self):
        b = Box(center=(10, 20), width=30, height=4, angle=15)
        for how in (copy.copy, copy.deepcopy):
            w = how(b)
            self.assertIsNot(w, b)
            self.assertEqual((w.width, w.height, w.angle), (b.width, b.height, b.angle))
            self.assertEqual((w.center.x, w.center.y), (b.center.x, b.center.y))

    def test_everything_else_refuses_with_the_spelling_that_makes_one(self):
        circle = self.track(Circle(center=(0, 0), radius=3))
        cases = [(circle, "shape.clone()"), (self.track(Entity()), "Entity(…)"),
                 (scena.mouse, "there is one Mouse"), (clock, "there is one Clock"),
                 (Attribute(3), "v = st.score")]
        for obj, fix in cases:
            for how in (copy.copy, copy.deepcopy):
                with self.subTest(kind=type(obj).__name__, how=how.__name__):
                    with self.assertRaises(TypeError) as cm:
                        how(obj)
                    self.assertIn(fix, str(cm.exception))
        twin = circle.clone()               # the fix works
        self.track(twin)
        self.assertIsNot(twin, circle)

    def test_every_public_container_class_is_decided(self):
        """A new public Container kind must be a value kind (its own
        ``__copy__``) or keep the refusal: never Python's ``__dict__`` copy."""
        for name in _public_containers():
            cls = getattr(scena, name)
            with self.subTest(kind=name):
                own = cls.__copy__ is not Container.__copy__
                self.assertEqual(own, name in _VALUE_KINDS or any(
                    issubclass(cls, getattr(scena, v)) for v in _VALUE_KINDS),
                    f"{name}: add it to _VALUE_KINDS with a __copy__, or let it refuse")
                self.assertIsNot(cls.__deepcopy__, object.__dict__.get("__deepcopy__"))


class TestMessagesNameTheAuthorsSubject(_Case):
    """The refusal names what the author wrote, and the fix it names works."""

    def test_point_iadd_in_a_cell_names_the_cell(self):
        st = State(name="st")
        st.pos = self.track(Point(1, 1))
        with self.assertRaises(TypeError) as cm:
            st.pos += (1, 1)
        msg = str(cm.exception)
        self.assertIn("`st.pos += …`", msg)
        self.assertNotIn("ship", msg)
        self.assertIn("st.pos.move_by(dx, dy)", msg)
        st.pos.move_by(1, 1)                # the fix works
        self.assertEqual((st.pos.x, st.pos.y), (2.0, 2.0))

    def test_point_isub_on_a_value_names_the_new_value(self):
        src = self.track(Circle(center=(0, 0), radius=3))
        q = src.center + (1, 1)              # point arithmetic: a value
        with self.assertRaises(TypeError) as cm:
            q -= (1, 1)
        self.assertIn("`q = q - (dx, dy)`", str(cm.exception))
        q = q - (1, 1)
        self.assertEqual((q.x, q.y), (0.0, 0.0))

    def test_point_iadd_on_a_part_still_names_its_actor(self):
        ship = self.track(Circle(center=(0, 0), radius=3))
        with self.assertRaises(TypeError) as cm:
            ship.center += (1, 1)
        self.assertIn("`ship.move_by(dx, dy)`", str(cm.exception))

    def test_point_iadd_on_a_linked_cell_says_it_is_linked(self):
        src = self.track(Circle(center=(0, 0), radius=3))
        st = State(name="st")
        st["L"] @= lambda: src.center + (1, 1)
        self.addCleanup(lambda: st["L"].unlink())
        with self.assertRaises(LinkedAttributeError) as cm:
            st.L += (1, 1)
        self.assertIn("st['L'].unlink()", str(cm.exception))

    def test_a_linked_field_vector_names_the_field_and_the_unlink_works(self):
        spellings = {
            ".x =": lambda v: setattr(v, "x", 5),
            "+=": lambda v: v.__iadd__((1, 1)),
            "<<": lambda v: v << (1, 1),
            "do_rotation": lambda v: v.do_rotation(10),
        }
        for spelling, write in spellings.items():
            with self.subTest(spelling=spelling):
                circle = self.track(Circle(center=(10, 20), radius=5))
                circle.mira = Vec2(0, 0)
                circle.mira @= lambda: Vec2(circle.center.x, 1)
                with self.assertRaises(LinkedAttributeError) as cm:
                    write(circle.mira)
                msg = str(cm.exception)
                self.assertEqual(msg, "circle.mira is linked — call circle.mira.unlink() first")
                circle.mira.unlink()        # the fix it names
                write(circle.mira)

    def test_a_linked_axis_of_a_field_vector_names_the_field(self):
        circle = self.track(Circle(center=(10, 20), radius=5))
        circle.b = Vec2(0, 0)
        circle.b["x"] @= lambda: circle.center.x
        with self.assertRaises(LinkedAttributeError) as cm:
            circle.b.x = 3
        self.assertIn("circle.b['x'].unlink()", str(cm.exception))
        circle.b["x"].unlink()
        circle.b.x = 3
        self.assertEqual(circle.b.x, 3)

    def test_takein_from_a_dead_part_names_the_owners_field(self):
        from scena.state import DestroyedError
        bala = Circle(center=(0, 0), radius=3)
        bala.vel = (1, 2)
        kept = bala.vel
        bala.destroy()
        ship = self.track(Circle(center=(5, 5), radius=3))
        ship.vel = (0, 0)
        for target, head in ((Vec2(0, 0), "v << Circle.vel"),
                             (ship.vel, "Circle.vel << Circle.vel"),
                             (ship.center, "Circle.center << Circle.vel")):
            with self.subTest(head=head):
                with self.assertRaises(DestroyedError) as cm:
                    target << kept
                msg = str(cm.exception)
                self.assertTrue(msg.startswith(head + ": the source was destroyed"), msg)
                self.assertNotIn("_vel", msg)
                self.assertNotIn("vec2", msg)


if __name__ == "__main__":
    unittest.main()
