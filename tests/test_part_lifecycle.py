"""
A part is geometry of its owner, not an actor.

A part leaves with its owner (P1), has no tags of its own, is not a collision
body, and cannot be destroyed or parked on its own (Actors Design — "A part is
not an actor").

Bug class (Testing Design, P1): Entity parts (a Circle's ``center``, a Line's
``p1`` / ``p2``, Polygon vertices) register like actors, but ``destroy()`` and
the failed-constructor rollback only took the owner out. A part stayed alive,
ownerless, in the roster, and — when shown — drawn and draggable on ``top``
forever (the draw list held it). Every registry membership is checked here for
every shape family and every way a part gets one (hidden, handles, visible).

Run headless:

    python -m unittest tests.test_part_lifecycle -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import (  # noqa: E402
    Circle, Ellipse, Triangle, Line, Point, Polygon, Rect, RegularPolygon,
    Square, Text, Track, canvas, collide, collide_exit, collide_stay, group, init,
    resolve, test_collision, unresolve,
)
from scena.collision import Collider, get_collision_system  # noqa: E402
from scena.canvas import ScenaCanvas  # noqa: E402
from scena.entity import DestroyedError  # noqa: E402
from scena.registry import entity_parts  # noqa: E402


FAMILIES = {
    "Circle": lambda: Circle(center=(40, 40), radius=10),
    "Rect": lambda: Rect(center=(40, 40), width=20, height=10),
    "Square": lambda: Square(center=(40, 40), length=12),
    "Ellipse": lambda: Ellipse(center=(40, 40), width=20, height=10),
    "Line": lambda: Line(p1=(10, 10), p2=(60, 30)),
    "Polygon": lambda: Polygon(points=[(0, 0), (30, 0), (15, 20)]),
    "RegularPolygon": lambda: RegularPolygon(n=5, center=(40, 40), radius=12),
    "Triangle": lambda: Triangle(center=(40, 40), radius=12),
    "Text": lambda: Text("hi", center=(40, 40)),
    "Track": lambda: Track.circle(center=(40, 40), radius=12),
}


def _registry():
    return ScenaCanvas.get_current().registry


def _memberships(reg, part):
    """Every registry list that holds ``part`` (empty when it is nowhere)."""
    where = []
    if reg.is_live(part):
        where.append("roster")
    for name in list(reg.layers):
        layer = reg.layers.get(name)
        layer._compact()
        if part in layer._objects:
            where.append(f"layer {name!r}")
        if part in layer._interactive:
            where.append(f"pointer list {name!r}")
    for gid, members in reg.group_map.items():
        if part in list(members):
            where.append(f"group {gid!r}")
    return where


class TestPartLeavesWithOwner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def _check_destroy(self, make, show):
        reg = _registry()
        actor = make()
        parts = entity_parts(actor)
        self.assertTrue(parts, "every family owns at least one Point part")
        if show == "handles" and hasattr(actor, "show_handles"):
            actor.show_handles()
        elif show == "visible":
            parts[0].visible = True
        before = {id(p): (float(p.x), float(p.y)) for p in parts}
        actor.destroy()
        for p in parts:
            self.assertEqual(_memberships(reg, p), [], f"{p!r} left behind")
            self.assertFalse(p.is_alive)
            self.assertFalse(p)
            self.assertEqual((float(p.x), float(p.y)), before[id(p)], "reads stay")
            with self.assertRaises(DestroyedError) as ctx:
                p.move_by(1, 0)
            self.assertIn(f"a part of the {type(actor).__name__} made at", str(ctx.exception))

    def test_every_family_every_way_shown(self):
        for name, make in FAMILIES.items():
            for show in ("hidden", "handles", "visible"):
                with self.subTest(family=name, show=show):
                    self._check_destroy(make, show)

    def test_dead_part_cannot_be_shown_again(self):
        # Used to put an ownerless handle back on ``top`` after the owner died.
        c = Circle(center=(10, 10), radius=5)
        cen = c.center
        c.destroy()
        with self.assertRaises(DestroyedError):
            cen.visible = True
        self.assertEqual(_memberships(_registry(), cen), [])

    def test_dead_part_still_copies_as_a_value(self):
        # Same as any destroyed actor: pose reads stay, so a value copy works.
        c = Circle(center=(12, 34), radius=5)
        cen = c.center
        c.destroy()
        p = Point(cen)
        self.assertEqual((float(p.x), float(p.y)), (12.0, 34.0))
        p.destroy()

    def test_failed_constructor_retires_its_parts(self):
        reg = _registry()
        mark = reg._next_key
        with self.assertRaises(TypeError):
            Circle(center="")
        self.assertEqual([o for k, o in reg.live.items() if k > mark], [])

    def test_subclass_init_error_after_parts_retires_them(self):
        seen = []

        class Fussy(Line):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.show_handles()  # parts now drawn and draggable on top
                seen.extend(entity_parts(self))
                raise RuntimeError("author bug in __init__")

        reg = _registry()
        mark = reg._next_key
        with self.assertRaises(RuntimeError):
            Fussy(p1=(0, 0), p2=(20, 20))
        self.assertEqual([o for k, o in reg.live.items() if k > mark], [])
        self.assertTrue(seen)
        for p in seen:
            self.assertEqual(_memberships(reg, p), [], f"{p!r} left behind")
            self.assertFalse(p.is_alive)


class TestPartsHaveNoTags(unittest.TestCase):
    """Groups are actor-level: a tagged ``center`` would collide as a Point
    (``@collide`` auto-enrolls group members) or reshape its owner (bulk verbs)."""

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def test_every_tag_spelling_refuses_and_names_the_owner(self):
        ln = Line(p1=(0, 0), p2=(10, 10))
        try:
            p1 = ln.p1
            for label, call in (
                ("tag", lambda: p1.tag("h")),
                ("untag", lambda: p1.untag("h")),
                ("add_to_group", lambda: p1.add_to_group("h")),
                ("remove_from_group", lambda: p1.remove_from_group("h")),
                ("group =", lambda: setattr(p1, "group", "h")),
            ):
                with self.subTest(verb=label):
                    with self.assertRaises(TypeError) as ctx:
                        call()
                    msg = str(ctx.exception)
                    self.assertIn("p1 is a part of the Line made at", msg)
                    self.assertIn("line.tag('h')", msg)
            self.assertEqual(len(group["h"]), 0)
            self.assertFalse(p1.tagged("h"))
            p1.group = ()  # empty set: nothing to refuse
        finally:
            ln.destroy()

    def test_every_family_refuses(self):
        for name, make in FAMILIES.items():
            with self.subTest(family=name):
                actor = make()
                try:
                    for part in entity_parts(actor):
                        with self.assertRaises(TypeError):
                            part.tag("x")
                finally:
                    actor.destroy()

    def test_free_point_still_tags(self):
        p = Point(1, 2)
        try:
            p.tag("free")
            self.assertIn(p, group["free"])
        finally:
            p.destroy()


class TestPartIsNotABody(unittest.TestCase):
    """A collidable part was a Point body: handlers got a Point instead of the
    actor, ``resolve`` pushed one point (the disc overlapped the wall, a Line
    stretched), owner and part fired twice, and a parked owner's part kept
    colliding. Detection on a part is a future hitbox-style design, not this."""

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def setUp(self):
        self.wall = Rect(center=(200, 200), width=10, height=10)

    def tearDown(self):
        self.wall.destroy()

    def _verbs(self, part):
        wall = self.wall
        return (
            ("collidable = True", lambda: setattr(part, "collidable", True)),
            ("on_collide =", lambda: setattr(part, "on_collide", lambda *a: None)),
            ("on_collide_stay =", lambda: setattr(part, "on_collide_stay", lambda *a: None)),
            ("on_collide_exit =", lambda: setattr(part, "on_collide_exit", lambda *a: None)),
            ("@collide left", lambda: collide(part, wall)),
            ("@collide right", lambda: collide(wall, part)),
            ("@collide in a list", lambda: collide(wall, [part])),
            ("@collide_stay", lambda: collide_stay(part, wall)),
            ("@collide_exit", lambda: collide_exit(wall, part)),
            ("resolve left", lambda: resolve(part, wall)),
            ("resolve right", lambda: resolve(wall, part)),
            ("unresolve", lambda: unresolve(part, wall)),
            ("Collider([...])", lambda: Collider([part])),
        )

    def test_every_body_verb_refuses_on_every_family(self):
        sys_ = get_collision_system()
        for name, make in FAMILIES.items():
            actor = make()
            try:
                for part in entity_parts(actor):
                    for verb, call in self._verbs(part):
                        with self.subTest(family=name, verb=verb):
                            pairs = list(sys_._pair_handlers)
                            with self.assertRaises(TypeError) as ctx:
                                call()
                            msg = str(ctx.exception)
                            self.assertIn("is not a collision body", msg)
                            self.assertIn(f"a part of the {type(actor).__name__} made at", msg)
                            self.assertIn("contains_point", msg)
                            self.assertIsNone(part._collider)
                            self.assertFalse(part.collidable)
                            self.assertEqual(list(sys_._pair_handlers), pairs)
            finally:
                actor.destroy()

    def test_queries_and_clears_stay_allowed(self):
        ln = Line(p1=(0, 0), p2=(200, 200))
        try:
            ln.p2.collidable = False       # the state it is already in
            ln.p2.on_collide = None
            self.assertIsNotNone(test_collision(ln.p2, self.wall))
            self.assertEqual(ln.p2.collides_with(), [])
            self.assertTrue(self.wall.contains_point(ln.p2))
            self.assertIsNone(ln.p2._collider)  # queries did not enroll it
        finally:
            ln.destroy()

    def test_follower_point_is_the_body_spelling(self):
        ln = Line(p1=(0, 0), p2=(200, 200))
        tip = Point(lambda: ln.p2)
        try:
            tip.collidable = True
            hits = []
            collide(tip, self.wall)(lambda me, other, info: hits.append((me, other)))
            get_collision_system().step()
            self.assertEqual(hits, [(tip, self.wall)])
        finally:
            tip.destroy()
            ln.destroy()


class TestPartLivesWithItsOwner(unittest.TestCase):
    """``c.center.destroy()`` used to leave a live Circle drawing and moving on a
    dead centre; ``part.active`` parked a point of a live shape."""

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def test_destroy_and_active_refuse_on_every_family(self):
        for name, make in FAMILIES.items():
            actor = make()
            try:
                for part in entity_parts(actor):
                    for verb, call in (
                        ("destroy()", part.destroy),
                        ("active = False", lambda: setattr(part, "active", False)),
                        ("active = True", lambda: setattr(part, "active", True)),
                    ):
                        with self.subTest(family=name, verb=verb):
                            with self.assertRaises(TypeError) as ctx:
                                call()
                            self.assertIn("a part lives, parks and dies with its owner",
                                          str(ctx.exception))
                            self.assertTrue(part.is_alive)
                            self.assertTrue(part.active)
                            self.assertTrue(_registry().is_live(part))
            finally:
                actor.destroy()

    def test_hard_layer_clear_undraws_handles_of_an_owner_elsewhere(self):
        # ``top.clear(hard=True)`` destroys actors on ``top``; a handle there is
        # a view of a point whose owner lives on ``default``.
        reg = _registry()
        ln = Line(p1=(0, 0), p2=(50, 50))
        try:
            ln.show_handles()
            parts = entity_parts(ln)
            canvas.layers["top"].clear(hard=True)
            self.assertTrue(ln.is_alive)
            for p in parts:
                self.assertTrue(p.is_alive)
                self.assertTrue(reg.is_live(p))
                self.assertNotIn(p, reg.layers["top"]._objects)
            ln.move_by(1, 0)  # the owner still works on its live points
        finally:
            ln.destroy()

    def test_hard_layer_clear_with_the_owner_on_it_retires_parts(self):
        reg = _registry()
        ln = Line(p1=(0, 0), p2=(50, 50), layer="top")
        ln.show_handles()
        parts = entity_parts(ln)
        canvas.layers["top"].clear(hard=True)
        self.assertFalse(ln.is_alive)
        for p in parts:
            self.assertFalse(p.is_alive)
            self.assertEqual(_memberships(reg, p), [])


class TestPartParksWithOwner(unittest.TestCase):
    """``line.active = False`` hid the Line but its shown handles kept drawing
    and stayed draggable — dragging one moved a parked shape."""

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    @staticmethod
    def _on_screen(part):
        reg = _registry()
        out = []
        for name in list(reg.layers):
            layer = reg.layers.get(name)
            layer._compact()
            if part in layer._objects:
                out.append("drawn")
            if part in layer._interactive:
                out.append("pointer")
        return out

    def test_park_hides_and_resume_restores_every_family(self):
        for name, make in FAMILIES.items():
            for show in ("handles", "visible"):
                with self.subTest(family=name, show=show):
                    actor = make()
                    try:
                        parts = entity_parts(actor)
                        if show == "handles" and hasattr(actor, "show_handles"):
                            actor.show_handles()
                        else:
                            parts[0].visible = True
                        before = {id(p): self._on_screen(p) for p in parts}
                        actor.active = False
                        for p in parts:
                            self.assertEqual(self._on_screen(p), [], f"{p!r} still on screen")
                            self.assertFalse(p.active)
                            self.assertTrue(p.is_alive)
                        actor.active = True
                        for p in parts:
                            self.assertEqual(self._on_screen(p), before[id(p)])
                            self.assertTrue(p.active)
                    finally:
                        actor.destroy()

    def test_handle_changes_while_parked_apply_on_resume(self):
        ln = Line(p1=(0, 0), p2=(50, 50))
        try:
            ln.active = False
            ln.show_handles()
            self.assertEqual(self._on_screen(ln.p1), [])
            ln.active = True
            self.assertEqual(self._on_screen(ln.p1), ["drawn", "pointer"])
            ln.active = False
            ln.no_handles()
            ln.active = True
            self.assertEqual(self._on_screen(ln.p1), [])
        finally:
            ln.destroy()

    def test_part_timers_pause_with_the_owner(self):
        from scena import clock
        from scena.process import tick_processes
        ln = Line(p1=(0, 0), p2=(50, 50))
        try:
            ticks = []
            ln.p1.every(0.1, lambda: ticks.append(1))
            ln.active = False
            for _ in range(5):
                clock.advance(0.1)
                tick_processes()
            self.assertEqual(ticks, [])
            ln.active = True
            for _ in range(3):
                clock.advance(0.1)
                tick_processes()
            self.assertTrue(ticks)
        finally:
            ln.destroy()

    def test_destroy_while_parked_retires_parts(self):
        ln = Line(p1=(0, 0), p2=(50, 50))
        ln.show_handles()
        ln.active = False
        parts = entity_parts(ln)
        ln.destroy()
        for p in parts:
            self.assertFalse(p.is_alive)
            self.assertEqual(_memberships(_registry(), p), [])


if __name__ == "__main__":
    unittest.main()
