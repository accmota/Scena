"""FieldRef, ScalarSlot, bracket linking, and raise-on-linked-assign.

Phase 1 core tests (promoted from the Phase 0 Point spike).

Run::

    python -m pytest tests/test_fieldref.py -q
"""
from __future__ import annotations

import os
import sys
import math
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.process import reset_process_scheduler, tick_processes
from scena.shapes import Line, Point
from scena.scenamath import Vec2
from scena.state import (
    Attribute,
    DerivedAttributeError,
    FieldRef,
    LinkedAttributeError,
    ScalarSlot,
    State,
)
from scena import clock, tween

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def _frame(real_dt=0.1):
    clock.advance(real_dt)
    tick_processes()


class TestBarePointReadWrite(unittest.TestCase):
    def test_dot_returns_plain_float(self):
        p = Point(3.5, 4.5)
        self.assertIsInstance(p.x, float)
        self.assertIsInstance(p.y, float)
        self.assertEqual(p.x, 3.5)
        self.assertEqual(p.y, 4.5)
        self.assertNotIsInstance(p.x, Attribute)

    def test_dot_write(self):
        p = Point(0, 0)
        p.x = 12.0
        p.y = 13.0
        self.assertEqual(p.x, 12.0)
        self.assertEqual(p.y, 13.0)

    def test_format_spec_works(self):
        p = Point(1.23456, 0)
        self.assertEqual(f"{p.x:.2f}", "1.23")

    def test_hashable_as_float(self):
        p = Point(1, 2)
        self.assertEqual(hash(p.x), hash(1.0))
        self.assertIn(p.x, {1.0, 2.0})

    def test_construction_does_not_link_attribute(self):
        src = Attribute(42.0)
        p = Point(src, 0)
        self.assertEqual(p.x, 42.0)
        self.assertFalse(p["x"].is_linked)
        src.value = 99.0
        self.assertEqual(p.x, 42.0)

    def test_a3_bare_ok_cached_on_owner(self):
        p = Point(1, 2)
        _ = p.x
        cache = p.__dict__.get("_scalar_bare_ok")
        self.assertIsNotNone(cache)
        self.assertIs(cache.get("x"), True)
        for _ in range(200):
            v = p.x
        self.assertEqual(v, 1.0)

    def test_a3_write_fast_path_seeds_and_invalidates_on_link(self):
        """Write-side A3 cache: seeds on first write; link clears it; raises after."""
        p = Point(1, 2)
        # Write before any read — seeds _scalar_bare_ok via the full guard path.
        p.x = 3.0
        cache = p.__dict__.get("_scalar_bare_ok")
        self.assertIsNotNone(cache)
        self.assertIs(cache.get("x"), True)
        # Fast path hits for subsequent writes.
        p.x = 4.0
        self.assertEqual(p.x, 4.0)
        src = Point(10, 0)
        p["x"] @= lambda: src.x
        # Anchor present → write must not take the bare fast path.
        with self.assertRaises(LinkedAttributeError):
            p.x = 99.0
        p["x"].unlink()
        p.x = 5.0
        self.assertEqual(p.x, 5.0)
        self.assertIs(p.__dict__["_scalar_bare_ok"].get("x"), True)

    def test_ownership_root_cache_follows_owner(self):
        p = Point(1, 2)
        self.assertIs(p._ownership_root(), p)
        self.assertIs(p.__dict__.get("_ownership_root_cache"), p)
        line = Line(p1=(0, 0), p2=(1, 0))
        # Fresh part under a shape caches the shape as root.
        root = line.p1._ownership_root()
        self.assertIs(root, line)
        self.assertIs(line.p1.__dict__.get("_ownership_root_cache"), line)

    def test_typo_raises(self):
        p = Point(1, 2)
        with self.assertRaises(AttributeError):
            p["raduis"]

    def test_formula_link_and_unlink(self):
        src = Point(10, 0)
        dst = Point(0, 0)
        dst["x"] @= lambda: src.x * 2
        self.assertTrue(dst["x"].is_linked)
        self.assertEqual(dst.x, 20.0)
        src.x = 15
        self.assertEqual(dst.x, 30.0)
        dst["x"].unlink()
        self.assertFalse(dst["x"].is_linked)
        src.x = 100
        self.assertEqual(dst.x, 30.0)

    def test_direct_link_to_attribute_cell(self):
        cell = Attribute(7.0)
        p = Point(0, 0)
        p["x"] @= cell
        self.assertEqual(p.x, 7.0)
        cell.value = 11.0
        self.assertEqual(p.x, 11.0)

    def test_direct_link_to_fieldref(self):
        """``dst["x"] @= src["x"]`` — bracket FieldRef as DirectLink RHS."""
        src = Point(10, 0)
        dst = Point(0, 0)
        dst["x"] @= src["x"]
        self.assertTrue(dst["x"].is_linked)
        self.assertEqual(dst.x, 10.0)
        src.x = 42.0
        self.assertEqual(dst.x, 42.0)
        dst["x"].unlink()
        src.x = 99.0
        self.assertEqual(dst.x, 42.0)

    def test_direct_link_fieldref_shape_scalar(self):
        from scena.shapes import Circle

        host = Circle(center=(0, 0), radius=12)
        twin = Circle(center=(40, 0), radius=1)
        twin["radius"] @= host["radius"]
        self.assertAlmostEqual(twin.radius, 12.0)
        host.radius = 20.0
        self.assertAlmostEqual(twin.radius, 20.0)

    def test_formula_default_arg_shape_capture(self):
        """Bench / loop idiom: ``lambda h=host: h.angle`` must install live."""
        from scena.shapes import Square

        hosts = [
            Square(center=(0, 0), length=10, angle=10),
            Square(center=(20, 0), length=10, angle=30),
        ]
        twins = []
        for host in hosts:
            twin = Square(center=(0, 40), length=8, angle=0)
            twin["angle"] @= (lambda h=host: h.angle)
            twins.append(twin)
        self.assertAlmostEqual(twins[0].angle, 10.0)
        self.assertAlmostEqual(twins[1].angle, 30.0)
        hosts[0].angle = 55.0
        self.assertAlmostEqual(twins[0].angle, 55.0)
        self.assertAlmostEqual(twins[1].angle, 30.0)

    def test_formula_subscript_shape_source(self):
        from scena.shapes import Circle

        orbiters = [
            Circle(center=(0, 0), radius=5),
            Circle(center=(10, 0), radius=8),
        ]
        sat = Circle(center=(0, 20), radius=1)
        sat["radius"] @= (lambda: orbiters[1].radius + 1)
        self.assertAlmostEqual(sat.radius, 9.0)
        orbiters[1].radius = 12.0
        self.assertAlmostEqual(sat.radius, 13.0)

    def test_direct_link_fieldref_state_cell(self):
        st = State(name="bag")
        st.src = 3.0
        st.dst = 0.0
        st["dst"] @= st["src"]
        self.assertEqual(st.dst, 3.0)
        st.src = 8.0
        self.assertEqual(st.dst, 8.0)

    def test_non_linkable_rhs_raises(self):
        p = Point(0, 0)
        with self.assertRaises(TypeError) as ctx:
            p["x"] @= 5
        self.assertIn("linkable", str(ctx.exception).lower())

    def test_dot_form_matmul_raises(self):
        p = Point(0, 0)
        with self.assertRaises(TypeError):
            p.x @= lambda: 1

    def test_linked_write_raises(self):
        src = Point(10, 0)
        dst = Point(0, 0)
        dst["x"] @= lambda: src.x
        with self.assertRaises(LinkedAttributeError) as ctx:
            dst.x = 5
        self.assertIn("unlink", str(ctx.exception))
        dst["x"].unlink()
        dst.x = 5
        self.assertEqual(dst.x, 5.0)

    def test_parent_write_raises_when_leaf_linked(self):
        src = Point(10, 0)
        dst = Point(0, 0)
        dst["x"] @= lambda: src.x
        with self.assertRaises(LinkedAttributeError):
            dst << Point(7, 8)
        with self.assertRaises(LinkedAttributeError):
            dst._assign_value((7, 8))
        dst._takein((3, 4))  # engine copy is ungated
        dst["x"].unlink()
        dst << Point(1, 2)
        self.assertEqual(dst.x, 1.0)
        self.assertEqual(dst.y, 2.0)

    def test_leaf_write_raises_when_parent_linked(self):
        src = Point(10, 20)
        dst = Point(0, 0)
        dst @= src
        with self.assertRaises(LinkedAttributeError):
            dst.x = 5
        self.assertEqual(dst.x, 10.0)
        dst.unlink()
        dst.x = 5
        self.assertEqual(dst.x, 5.0)

    def test_setitem_plain_assignment_raises(self):
        p = Point(0, 0)
        with self.assertRaises(TypeError):
            p["x"] = 5

    def test_nested_access_via_composite(self):
        line = Line(p1=(0, 0), p2=(10, 0))
        self.assertIsInstance(line.p1.x, float)
        src = Point(3, 4)
        line.p1["x"] @= lambda: src.x
        self.assertEqual(line.p1.x, 3.0)
        src.x = 8
        self.assertEqual(line.p1.x, 8.0)


class TestBoxedCellAssignValueRaises(unittest.TestCase):
    """Decision 4 applies immediately to Attribute-backed cells (Phase 1)."""

    def test_linked_attribute_plain_assign_raises(self):
        src = Attribute(10)
        dst = Attribute(0)
        dst @= lambda: src.value * 2
        self.assertEqual(dst.value, 20)
        with self.assertRaises(LinkedAttributeError) as ctx:
            dst.value = 5
        self.assertIn("unlink", str(ctx.exception))
        dst.unlink()
        dst.value = 5
        self.assertEqual(dst.value, 5)

    def test_state_cell_linked_assign_raises(self):
        st = State()
        st.create("src", initial=3)
        st.create("dst", initial=0)
        st["dst"] @= lambda: st.src * 10
        self.assertEqual(st.dst, 30)
        with self.assertRaises(LinkedAttributeError) as ctx:
            st.dst = 1
        self.assertIn("State.dst is linked", str(ctx.exception))
        self.assertIn("State['dst'].unlink()", str(ctx.exception))
        st["dst"].unlink()
        st.dst = 1
        self.assertEqual(st.dst, 1)

    def test_root_container_at_equals_still_links(self):
        """Root objects have no owner field — ``obj @=`` remains the link verb."""
        a = Point(1, 2)
        b = Point(0, 0)
        b @= a
        self.assertTrue(b._link is not None)
        self.assertEqual(b.x, 1.0)
        a.x = 9
        self.assertEqual(b.x, 9.0)


class TestStateBrackets(unittest.TestCase):
    """st[\"key\"] FieldRef — preferred link spelling; dot still returns Attribute."""

    def test_bracket_link_propagates(self):
        st = State()
        st.create("src", initial=3)
        st.create("dst", initial=0)
        st["dst"] @= lambda: st.src * 10
        self.assertEqual(st.dst, 30)
        self.assertTrue(st["dst"].is_linked)
        st.src = 4
        self.assertEqual(st.dst, 40)

    def test_bracket_value_is_payload(self):
        st = State()
        st.create("score", initial=12.5)
        self.assertEqual(st["score"].value, 12.5)
        # The dot read is the value too (0.8.0); the bracket is the handle.
        self.assertIs(type(st.score), float)
        self.assertIsInstance(st._resolve_cell("score"), Attribute)

    def test_linked_dot_assign_raises_then_unlink(self):
        st = State()
        st.create("src", initial=3)
        st.create("dst", initial=0)
        st["dst"] @= lambda: st.src * 10
        with self.assertRaises(LinkedAttributeError) as ctx:
            st.dst = 1
        self.assertIn("State.dst", str(ctx.exception))
        self.assertIn("State['dst'].unlink()", str(ctx.exception))
        st["dst"].unlink()
        self.assertFalse(st["dst"].is_linked)
        st.dst = 1
        self.assertEqual(st.dst, 1)

    def test_unknown_key_raises(self):
        st = State()
        with self.assertRaises(AttributeError) as ctx:
            _ = st["missing"].value
        self.assertIn("missing", str(ctx.exception))
        self.assertIn("State", str(ctx.exception))

    def test_plain_setitem_raises(self):
        st = State()
        st.create("dst", initial=0)
        with self.assertRaises(TypeError) as ctx:
            st["dst"] = 1
        self.assertIn("plain assignment", str(ctx.exception).lower())

    def test_bracket_rejects_bare_number_rhs(self):
        st = State()
        st.create("dst", initial=0)
        with self.assertRaises(TypeError):
            st["dst"] @= 5

    def test_name_for_diagnostics(self):
        unlabeled = State()
        self.assertEqual(unlabeled.name, "State")
        unlabeled.create("t", initial=0)
        self.assertEqual(unlabeled._resolve_cell("t").name, "State.t")
        ref = unlabeled["t"]
        self.assertIsInstance(ref, FieldRef)
        self.assertIs(ref.owner, unlabeled)

        st = State(name="st")
        self.assertEqual(st.name, "st")
        hud = State(name="hud")
        self.assertEqual(hud.name, "hud")
        hud.score = 0
        self.assertEqual(hud._resolve_cell("score").name, "hud.score")
        self.assertIn("'hud'", str(hud))
        self.assertIn("name='hud'", repr(hud))

    def test_name_is_reserved(self):
        st = State()
        with self.assertRaises(AttributeError):
            st.name = "hud"
        with self.assertRaises(AttributeError):
            st.create("name", initial=0)
        with self.assertRaises(TypeError):
            State(name=1)
        with self.assertRaises(ValueError):
            State(name="")

    def test_named_bags_distinct_in_linked_errors(self):
        hud = State(name="hud")
        waves = State(name="waves")
        hud.create("count", initial=0)
        waves.create("count", initial=0)
        src_h = Attribute(1)
        src_w = Attribute(2)
        hud["count"] @= src_h
        waves["count"] @= src_w
        with self.assertRaises(LinkedAttributeError) as hud_ctx:
            hud.count = 9
        with self.assertRaises(LinkedAttributeError) as waves_ctx:
            waves.count = 9
        self.assertIn("hud.count", str(hud_ctx.exception))
        self.assertIn("hud['count'].unlink()", str(hud_ctx.exception))
        self.assertNotIn("waves", str(hud_ctx.exception))
        self.assertIn("waves.count", str(waves_ctx.exception))
        self.assertIn("waves['count'].unlink()", str(waves_ctx.exception))
        self.assertNotIn("hud", str(waves_ctx.exception))


class TestTweenFieldRef(unittest.TestCase):
    def setUp(self):
        reset_process_scheduler()
        clock.scale = 1.0
        clock.paused = False
        clock._dt = 0.0
        clock._time = 0.0
        clock._real_dt = 0.0
        clock._real_time = 0.0
        clock._frame = 0

    def tearDown(self):
        reset_process_scheduler()

    def test_tween_bracket_handle(self):
        p = Point(0, 0)
        tween(p["x"], to=20, time=0.2)
        _frame(0.1)
        self.assertAlmostEqual(p.x, 10.0, places=5)
        _frame(0.1)
        self.assertAlmostEqual(p.x, 20.0, places=5)

    def test_tween_bracket_handle_start(self):
        p = Point(0, 0)
        tween(p["x"], to=20, start=5, time=0.2)
        _frame(0.1)
        self.assertAlmostEqual(p.x, 12.5, places=5)
        _frame(0.1)
        self.assertAlmostEqual(p.x, 20.0, places=5)

    def test_tween_state_bracket_handle(self):
        st = State()
        st.create("t", initial=0.0)
        tween(st["t"], to=20, time=0.2)
        _frame(0.1)
        self.assertAlmostEqual(st.t, 10.0, places=5)
        _frame(0.1)
        self.assertAlmostEqual(st.t, 20.0, places=5)

    def test_tween_linked_state_field_names_the_bag(self):
        hud = State(name="hud")
        hud.create("count", initial=0)
        hud["count"] @= Attribute(1)
        with self.assertRaises(LinkedAttributeError) as ctx:
            tween(hud["count"], to=20, time=0.2)
        msg = str(ctx.exception)
        self.assertIn("Cannot tween hud", msg)
        self.assertIn("its count has an @= formula", msg)
        self.assertIn("hud['count'].unlink()", msg)

    def test_tween_plain_float_raises(self):
        p = Point(0, 0)
        with self.assertRaises(TypeError) as ctx:
            tween(p.x, to=20, time=0.2)
        self.assertIn("bracket", str(ctx.exception).lower())


class TestDerivateAdjacentHotLoop(unittest.TestCase):
    def test_line_endpoint_reads_point_x(self):
        line = Line(p1=(1.5, 2.5), p2=(10, 0))
        self.assertIsInstance(line.p1.x, float)
        self.assertIsInstance(type(line.p1).__dict__["x"], ScalarSlot)
        total = 0.0
        for _ in range(500):
            total += line.p1.x
        self.assertEqual(total, 1.5 * 500)
        cache = line.p1.__dict__.get("_scalar_bare_ok")
        self.assertIsNotNone(cache)
        self.assertIs(cache.get("x"), True)


class TestBareVec2(unittest.TestCase):
    def test_dot_returns_plain_float(self):
        v = Vec2(3.0, 4.0)
        self.assertIsInstance(v.x, float)
        self.assertIsInstance(v.y, float)
        self.assertEqual(v.x, 3.0)
        self.assertEqual(v.y, 4.0)
        self.assertNotIsInstance(v.x, Attribute)
        self.assertIsInstance(v.length, float)
        self.assertIsInstance(v.angle, float)
        self.assertNotIsInstance(v.length, Attribute)
        self.assertAlmostEqual(v.length, 5.0)
        self.assertAlmostEqual(v.angle, math.degrees(math.atan2(4.0, 3.0)))

    def test_length_angle_are_derivate_readonly(self):
        v = Vec2(3.0, 4.0)
        with self.assertRaises(DerivedAttributeError):
            v.length = 1.0
        with self.assertRaises(DerivedAttributeError):
            v["length"] @= lambda: 1.0
        with self.assertRaises(DerivedAttributeError):
            v.angle = 0.0
        with self.assertRaises(DerivedAttributeError):
            v["angle"] @= lambda: 0.0
        # x/y writes still refresh length/angle
        v.x = 0.0
        v.y = 5.0
        self.assertAlmostEqual(v.length, 5.0)
        self.assertAlmostEqual(v.angle, 90.0)

    def test_construction_does_not_link(self):
        src = Attribute(42.0)
        v = Vec2(src, 1)
        self.assertEqual(v.x, 42.0)
        self.assertFalse(v["x"].is_linked)
        src.value = 99.0
        self.assertEqual(v.x, 42.0)

    def test_bracket_link_and_unlink(self):
        src = Vec2(10, 0)
        dst = Vec2(0, 0)
        dst["x"] @= lambda: src.x * 2
        self.assertTrue(dst["x"].is_linked)
        self.assertEqual(dst.x, 20.0)
        src.x = 7
        self.assertEqual(dst.x, 14.0)
        dst["x"].unlink()
        src.x = 100
        self.assertEqual(dst.x, 14.0)

    def test_linked_write_raises(self):
        src = Vec2(1, 0)
        dst = Vec2(0, 0)
        dst["x"] @= lambda: src.x
        with self.assertRaises(LinkedAttributeError):
            dst.x = 5
        dst["x"].unlink()
        dst.x = 5
        self.assertEqual(dst.x, 5.0)

    def test_parent_write_raises_when_leaf_linked(self):
        src = Vec2(1, 0)
        dst = Vec2(0, 0)
        dst["x"] @= lambda: src.x
        with self.assertRaises(LinkedAttributeError):
            dst << Vec2(7, 8)
        with self.assertRaises(LinkedAttributeError):
            dst += (1, 0)
        dst._takein((3, 4))
        dst["x"].unlink()
        dst << Vec2(1, 2)
        self.assertEqual(dst.x, 1.0)
        self.assertEqual(dst.y, 2.0)

    def test_leaf_write_raises_when_parent_linked(self):
        src = Vec2(10, 20)
        dst = Vec2(0, 0)
        dst @= src
        with self.assertRaises(LinkedAttributeError):
            dst.x = 5
        with self.assertRaises(LinkedAttributeError):
            dst += (1, 0)
        self.assertEqual(dst.x, 10.0)
        dst.unlink()
        dst.x = 5
        self.assertEqual(dst.x, 5.0)

    def test_dot_form_matmul_raises(self):
        v = Vec2(0, 0)
        with self.assertRaises(TypeError):
            v.x @= lambda: 1

    def test_tween_bracket_handle(self):
        reset_process_scheduler()
        clock.scale = 1.0
        clock.paused = False
        clock._dt = 0.0
        clock._time = 0.0
        clock._real_dt = 0.0
        clock._real_time = 0.0
        clock._frame = 0
        try:
            v = Vec2(0, 0)
            tween(v["x"], to=20, time=0.2)
            _frame(0.1)
            self.assertAlmostEqual(v.x, 10.0, places=5)
            _frame(0.1)
            self.assertAlmostEqual(v.x, 20.0, places=5)
        finally:
            reset_process_scheduler()


class TestBareLine(unittest.TestCase):
    def test_point_point_derived_scalars_are_bare(self):
        line = Line(p1=(0, 0), p2=(10, 0))
        self.assertIsInstance(line.length, float)
        self.assertIsInstance(line.angle, float)
        self.assertNotIsInstance(line.length, Attribute)
        self.assertAlmostEqual(line.length, 10.0)
        self.assertAlmostEqual(line.angle, 0.0)
        self.assertAlmostEqual(line.dx, 10.0)
        self.assertAlmostEqual(line.dy, 0.0)

    def test_derived_length_tracks_endpoints(self):
        line = Line(p1=(0, 0), p2=(10, 0))
        line.p2.x = 20
        self.assertAlmostEqual(line.length, 20.0)

    def test_rotate_to_refreshes_derived_angle(self):
        line = Line(p1=(0, 0), p2=(10, 0))
        line.rotate_to(90)
        self.assertAlmostEqual(line.angle, 90.0, places=5)

    def test_defining_angle_bracket_link(self):
        src = Line(p1=(0, 0), angle=45, length=10)
        dst = Line(p1=(0, 0), angle=0, length=10)
        dst["angle"] @= lambda: src.angle
        self.assertTrue(dst["angle"].is_linked)
        self.assertAlmostEqual(dst.angle, 45.0)
        with self.assertRaises(LinkedAttributeError):
            dst.angle = 10
        dst["angle"].unlink()
        dst.angle = 10
        self.assertAlmostEqual(dst.angle, 10.0)

    def test_parallel_dist_does_not_cycle(self):
        ref = Line(p1=(0, 0), p2=(10, 0))
        line = Line(dist=5, parallel_to=ref)
        self.assertAlmostEqual(line.length, 10.0)
        self.assertAlmostEqual(line.p1.x, 0.0)
        self.assertAlmostEqual(line.p1.y, 5.0)
        ref.move_by(100, 0)
        self.assertAlmostEqual(line.p1.x, 100.0)
        self.assertAlmostEqual(line.p1.y, 5.0)


class TestEntityInkFieldRef(unittest.TestCase):
    def test_entity_bracket_link_materializes_ink(self):
        from scena.shapes import Circle

        c = Circle(center=(0, 0), radius=10)
        c["hp"] @= Attribute(1)
        self.assertTrue(c["hp"].is_linked)
        self.assertEqual(c.hp, 1)

    def test_ink_dot_assign_callable_raises(self):
        from scena.shapes import Circle

        host = Circle(center=(0, 0), radius=5)
        ship = Circle(center=(10, 0), radius=3)
        with self.assertRaises(AttributeError) as ctx:
            ship.hp = lambda: host.radius * 2
        msg = str(ctx.exception)
        self.assertIn("@=", msg)
        self.assertIn("hp", msg)
        with self.assertRaises(AttributeError):
            _ = ship.hp

    def test_existing_ink_dot_assign_callable_raises(self):
        from scena.shapes import Circle

        host = Circle(center=(0, 0), radius=5)
        ship = Circle(center=(10, 0), radius=3)
        ship.hp = 3
        with self.assertRaises(AttributeError) as ctx:
            ship.hp = lambda: host.radius * 2
        self.assertIn("@=", str(ctx.exception))
        self.assertEqual(ship.hp, 3)
        self.assertFalse(ship["hp"].is_linked)

    def test_ink_bracket_at_equals_still_links(self):
        from scena.shapes import Circle

        host = Circle(center=(0, 0), radius=5)
        ship = Circle(center=(10, 0), radius=3)
        ship["hp"] @= lambda: host.radius * 2
        self.assertTrue(ship["hp"].is_linked)
        self.assertEqual(ship.hp, 10.0)
        host.radius = 9
        self.assertEqual(ship.hp, 18.0)

    def test_point_typo_still_raises(self):
        p = Point(1, 2)
        with self.assertRaises(AttributeError):
            p["raduis"]

    def test_paint_field_bracket_link_raises(self):
        from scena.shapes import Circle

        c = Circle(center=(0, 0), radius=10)
        # fill / line / line_width / color link since the appearance links
        # (tests/test_paint_flag_links.py); looks and stroke knobs still refuse.
        for field in (
            "visual", "dash", "blend",
            "line_filter", "fill_filter", "glow", "shadow", "tail",
        ):
            with self.subTest(field=field):
                with self.assertRaises(AttributeError) as ctx:
                    c[field]
                msg = str(ctx.exception)
                self.assertIn("cannot be linked with @=", msg)
                self.assertIn(field, msg)

    def test_paint_field_callable_assign_raises(self):
        from scena.shapes import Circle
        from scena.state import CallableAssignError

        c = Circle(center=(0, 0), radius=10)
        with self.assertRaises(AttributeError) as ctx:
            c.dash = lambda: "dash"
        self.assertIn("cannot be linked with @=", str(ctx.exception))
        # A linkable appearance field points at ``@=`` instead (``=`` copies).
        with self.assertRaises(CallableAssignError) as ctx:
            c.line_width = lambda: 5.0
        self.assertIn("Circle['line_width'] @= lambda", str(ctx.exception))
        self.assertEqual(c.line_width, 1.5)

    def test_handler_callable_assign_is_not_an_ink_link(self):
        from scena.shapes import Circle

        c = Circle(center=(0, 0), radius=10)
        c.on_click = lambda s: None
        self.assertIsNotNone(c.on_click)
        self.assertTrue(c.clickable)
        c.on_update = lambda e, dt: None
        self.assertIsNotNone(c.on_update)
        c.on_destroy = lambda e: None
        self.assertIsNotNone(c.on_destroy)

        def idle(e):
            pass

        c.mode = idle
        self.assertIs(c.mode, idle)
        with self.assertRaises(AttributeError) as ctx:
            c["on_click"]
        self.assertIn("cannot be linked with @=", str(ctx.exception))
        with self.assertRaises(AttributeError) as ctx:
            c["mode"]
        self.assertIn("cannot be linked with @=", str(ctx.exception))

    def test_sprite_hue_bracket_link_raises(self):
        from scena import Sprite

        s = Sprite("media/hero.png", center=(0, 0))
        with self.assertRaises(AttributeError) as ctx:
            s["hue"]
        self.assertIn("cannot be linked with @=", str(ctx.exception))

    def test_geometry_slot_still_linkable_after_paint_guard(self):
        from scena.shapes import Rect

        r = Rect(center=(0, 0), width=40, height=20)
        r["width"] @= Attribute(80)
        self.assertEqual(r.width, 80)

    def test_bracket_link_does_not_create_phantom_ink(self):
        from scena.shapes import Circle

        a = Circle(center=(0, 0), radius=10)
        b = Circle(center=(100, 0), radius=1)
        with self.assertRaises(AttributeError):
            b["dash"] @= lambda: "dash" if a.radius > 5 else "solid"
        self.assertIsNone(getattr(b, "_ink", None))
        self.assertEqual(b.dash, "solid")
        # A linked appearance field writes through its setter, never into ink.
        b["line_width"] @= lambda: a.radius * 2
        self.assertIsNone(getattr(b, "_ink", None))
        self.assertEqual(b.line_width, 20.0)


class TestReactiveRotationScale(unittest.TestCase):
    """Graphic.angle / Graphic.scale are @=-linkable (slot or _PropertyAnchor)."""

    def test_rotation_link_installs_and_tracks(self):
        from scena.shapes import Rect

        dial = Attribute(15.0)
        rect = Rect(center=(0, 0), width=40, height=20)
        rect["angle"] @= dial
        self.assertTrue(rect["angle"].is_linked)
        self.assertAlmostEqual(rect.angle, 15.0)
        dial.value = 40.0
        self.assertAlmostEqual(rect.angle, 40.0)

    def test_scale_link_installs_and_tracks(self):
        from scena.shapes import Rect

        dial = Attribute(1.0)
        rect = Rect(center=(0, 0), width=40, height=20)
        rect["scale"] @= dial
        self.assertTrue(rect["scale"].is_linked)
        self.assertAlmostEqual(rect.scale, 1.0)
        dial.value = 2.0
        self.assertAlmostEqual(rect.scale, 2.0)
        self.assertAlmostEqual(rect.width, 80.0)
        self.assertAlmostEqual(rect.height, 40.0)

    def test_fieldref_surface_parity_with_angle(self):
        from scena.shapes import Rect

        src = Attribute(30.0)
        rect = Rect(center=(0, 0), width=40, height=20)
        ref = rect["angle"]
        self.assertFalse(ref.is_linked)
        self.assertAlmostEqual(ref.value, 0.0)
        ref @= src
        self.assertTrue(rect["angle"].is_linked)
        self.assertAlmostEqual(rect["angle"].value, 30.0)
        rect["angle"].unlink()
        self.assertFalse(rect["angle"].is_linked)
        rect.angle = 5.0
        self.assertAlmostEqual(rect.angle, 5.0)

    def test_direct_link_fieldref_rotation(self):
        from scena.shapes import Rect

        a = Rect(center=(0, 0), width=40, height=20)
        b = Rect(center=(80, 0), width=40, height=20)
        a.angle = 25.0
        b["angle"] @= a["angle"]
        self.assertAlmostEqual(b.angle, 25.0)
        a.angle = 70.0
        self.assertAlmostEqual(b.angle, 70.0)

    def test_dot_callable_assign_still_raises(self):
        from scena.shapes import Circle

        c = Circle(center=(0, 0), radius=10)
        with self.assertRaises(AttributeError) as ctx:
            c.angle = lambda: 1
        self.assertIn("cannot be linked by assigning a callable", str(ctx.exception))
        self.assertIn("['angle'] @=", str(ctx.exception))
        self.assertAlmostEqual(c.angle, 0.0)
        with self.assertRaises(AttributeError) as ctx:
            c.scale = lambda: 2
        self.assertIn("cannot be linked by assigning a callable", str(ctx.exception))
        self.assertIn("['scale'] @=", str(ctx.exception))

    def test_rect_rotation_link_is_plain_scalar_anchor(self):
        from scena.shapes import Rect
        from scena.state import ScalarAnchor, _PropertyAnchor

        dial = Attribute(15.0)
        rect = Rect(center=(0, 0), width=40, height=20)
        rect["angle"] @= dial
        anchors = rect.__dict__.get("_field_anchors") or {}
        self.assertIsInstance(anchors.get("angle"), ScalarAnchor)
        self.assertNotIsInstance(anchors.get("angle"), _PropertyAnchor)
        width_src = Attribute(40.0)
        rect["width"] @= width_src
        self.assertIs(type(anchors.get("angle")), type(anchors.get("width")))
        rect["angle"].unlink()
        self.assertFalse(rect["angle"].is_linked)
        rect["angle"] @= Attribute(70.0)
        self.assertAlmostEqual(rect.angle, 70.0)

    def test_rect_rotation_link_holds_top_left_fixed(self):
        """Direct ``["angle"] @=`` is a geometry-field write, not center-pivot rotate_to."""
        from scena.shapes import Rect, get_xy

        rect = Rect(top_left=(10, 50), width=40, height=20, angle=0)
        tl0 = get_xy(rect.top_left, bare=True)
        c0 = get_xy(rect.center, bare=True)
        rect["angle"] @= Attribute(90.0)
        self.assertAlmostEqual(rect.angle, 90.0)
        self.assertAlmostEqual(get_xy(rect.top_left, bare=True)[0], tl0[0], places=5)
        self.assertAlmostEqual(get_xy(rect.top_left, bare=True)[1], tl0[1], places=5)
        self.assertNotAlmostEqual(get_xy(rect.center, bare=True)[0], c0[0], places=5)

    def test_unmerged_rotation_still_uses_property_anchor(self):
        from scena.shapes import Circle, Point, Polygon
        from scena.sprite import Sprite
        from scena.state import _PropertyAnchor
        from scena.text import Text

        for shape in (
            Point(3, 4),
            Polygon(points=[(0, 0), (10, 0), (6, 8)]),
            Sprite("media/hero.png", center=(0, 0), size=20),
            Text("Hi", top_left=(0, 0), font_size=12),
        ):
            self.assertNotIn("angle", shape._field_slots())
            shape["angle"] @= Attribute(12.0)
            anchors = shape.__dict__.get("_field_anchors") or {}
            self.assertIsInstance(anchors.get("angle"), _PropertyAnchor)
            with self.assertRaises(AttributeError) as ctx:
                shape.angle = lambda: 1
            self.assertIn("cannot be linked by assigning a callable", str(ctx.exception))

    def test_wheel_rotate_blocks_linking_rotation(self):
        from scena.shapes import Rect

        dial = Attribute(10.0)
        rect = Rect(center=(0, 0), width=10, height=8)
        rect.wheel_rotate = True
        with self.assertRaises(LinkedAttributeError) as ctx:
            rect["angle"] @= dial
        self.assertIn("wheel_rotate", str(ctx.exception))

    def test_unchanged_value_does_not_bump_collision_epoch(self):
        from scena.shapes import Rect

        rect = Rect(center=(0, 0), width=10, height=8, angle=0)
        epoch = rect._collision_epoch
        rect["angle"] @= Attribute(0.0)
        self.assertEqual(rect._collision_epoch, epoch)
        _ = rect.angle
        self.assertEqual(rect._collision_epoch, epoch)

    def test_clone_drops_rotation_link_and_freezes_value(self):
        from scena.shapes import Rect

        dial = Attribute(40.0)
        rect = Rect(center=(0, 0), width=10, height=8)
        rect["angle"] @= dial
        copy = rect.clone()
        self.assertFalse(copy["angle"].is_linked)
        self.assertAlmostEqual(copy.angle, 40.0)
        dial.value = 90.0
        self.assertAlmostEqual(rect.angle, 90.0)
        self.assertAlmostEqual(copy.angle, 40.0)

    def test_formula_reading_rotation_tracks_imperative_writes(self):
        from scena.shapes import Polygon, Rect
        from scena.state import _PropertyAnchor

        src = Polygon(points=[(0, 0), (10, 0), (5, 8)])
        dst = Rect(center=(50, 0), width=10, height=8)
        dst["width"] @= lambda: src.angle + 40
        self.assertAlmostEqual(dst.width, 40.0)
        src.angle = 25.0
        self.assertAlmostEqual(dst.width, 65.0)
        src.rotate_by(5.0)
        self.assertAlmostEqual(dst.width, 70.0)
        anchors = src.__dict__.get("_field_anchors") or {}
        self.assertIsInstance(anchors.get("angle"), _PropertyAnchor)

    def test_formula_reading_scale_tracks_imperative_writes(self):
        from scena.shapes import Circle, Rect
        from scena.state import _PropertyAnchor

        src = Circle(center=(0, 0), radius=10)
        dst = Rect(center=(50, 0), width=10, height=8)
        dst["width"] @= lambda: src.scale * 10
        self.assertAlmostEqual(dst.width, 10.0)
        src.scale = 2.0
        self.assertAlmostEqual(dst.width, 20.0)
        anchors = src.__dict__.get("_field_anchors") or {}
        self.assertIsInstance(anchors.get("scale"), _PropertyAnchor)

    def test_formula_chain_from_derivate_angle(self):
        from scena.shapes import Rect

        spine = Rect(p1=(0, 0), p2=(10, 0), height=4, anchor="cap")
        other = Rect(center=(50, 0), width=10, height=8)
        other["angle"] @= lambda: spine.angle
        self.assertAlmostEqual(other.angle, spine.angle)
        spine.rotate_by(20)
        self.assertAlmostEqual(other.angle, spine.angle, places=5)
        spine.rotate_by(-7)
        self.assertAlmostEqual(other.angle, spine.angle, places=5)
        self.assertFalse(other._in_batch_update)
        self.assertFalse(spine._in_batch_update)

    def test_bare_entity_rotation_is_still_forbidden(self):
        from scena.entity import Entity

        e = Entity()
        with self.assertRaises(AttributeError) as ctx:
            e["angle"]
        self.assertIn("has no field 'angle'", str(ctx.exception))
        self.assertIn("Graphics only", str(ctx.exception))
        e.angle = 12.0
        self.assertEqual(e.angle, 12.0)
        with self.assertRaises(AttributeError) as ctx:
            e["scale"]
        self.assertIn("has no field 'scale'", str(ctx.exception))
        e.scale = 2.0
        self.assertEqual(e.scale, 2.0)


class TestTupleAtEquals(unittest.TestCase):
    def test_point_plain_tuple_raises(self):
        q = Point(0, 0)
        with self.assertRaises(TypeError) as ctx:
            q @= (5, 10)
        msg = str(ctx.exception)
        self.assertIn("tuple form", msg)
        self.assertIn("@=", msg)
        self.assertEqual(q.x, 0)
        self.assertEqual(q.y, 0)
        self.assertIsNone(q._link)

    def test_point_mixed_tuple_raises(self):
        src = Point(3, 4)
        q = Point(0, 0)
        with self.assertRaises(TypeError) as ctx:
            q @= (5, lambda: src.y)
        self.assertIn("tuple form", str(ctx.exception))
        self.assertEqual(q.x, 0)
        self.assertEqual(q.y, 0)
        self.assertFalse(q["x"].is_linked)
        self.assertFalse(q["y"].is_linked)

    def test_point_both_callables_still_link(self):
        a = Point(3, 0)
        b = Point(0, 4)
        q = Point(0, 0)
        q @= (lambda: a.x, lambda: b.y)
        self.assertTrue(q["x"].is_linked)
        self.assertTrue(q["y"].is_linked)
        self.assertEqual(q.x, 3)
        self.assertEqual(q.y, 4)
        a.x = 9
        b.y = 8
        self.assertEqual(q.x, 9)
        self.assertEqual(q.y, 8)

    def test_vec2_plain_tuple_raises(self):
        v = Vec2(0, 0)
        with self.assertRaises(TypeError) as ctx:
            v @= (5, 10)
        self.assertIn("tuple form", str(ctx.exception))
        self.assertEqual(v.x, 0)
        self.assertEqual(v.y, 0)
        self.assertIsNone(v._link)

    def test_vec2_mixed_tuple_raises(self):
        src = Vec2(3, 4)
        v = Vec2(0, 0)
        with self.assertRaises(TypeError) as ctx:
            v @= (5, lambda: src.y)
        self.assertIn("tuple form", str(ctx.exception))
        self.assertEqual(v.x, 0)
        self.assertEqual(v.y, 0)
        self.assertFalse(v["x"].is_linked)
        self.assertFalse(v["y"].is_linked)

    def test_vec2_both_callables_still_link(self):
        a = Vec2(3, 0)
        b = Vec2(0, 4)
        v = Vec2(0, 0)
        v @= (lambda: a.x, lambda: b.y)
        self.assertTrue(v["x"].is_linked)
        self.assertTrue(v["y"].is_linked)
        self.assertEqual(v.x, 3)
        self.assertEqual(v.y, 4)
        a.x = 9
        b.y = 8
        self.assertEqual(v.x, 9)
        self.assertEqual(v.y, 8)


class TestVelIsNotLinkable(unittest.TestCase):
    """``ship.vel @= f`` runs ``ship.vel = ship.vel.__imatmul__(f)``: the link
    landed on the owned Vec2, then the setter wrote into it and raised
    ``LinkedAttributeError`` — and a link that stuck would make
    ``resolve(bounce=)`` / ``vel.y -= g * dt`` raise later. Every spelling
    refuses at the ``@=`` line with the bracket message (Testing Design A35)."""

    def setUp(self):
        from scena.shapes import Circle

        self.st = State("vel_link")
        self.st.a = 1
        self.ship = Circle(center=(0, 0), radius=5)
        self.ship.vel = (1, 0)

    def _assert_untouched(self):
        v = self.ship.vel
        self.assertEqual((v.x, v.y), (1, 0))
        self.assertIsNone(v._link)
        self.assertFalse(v["x"].is_linked)
        self.assertFalse(v["y"].is_linked)
        # The engine's writes and the taught idiom still work.
        v.y -= 2
        self.ship.vel = (3, 4)
        self.assertEqual((v.x, v.y), (3, 4))

    def test_attribute_link_refuses_with_the_bracket_message(self):
        from scena import vec_from_angle

        st = self.st
        with self.assertRaises(AttributeError) as attr:
            self.ship.vel @= lambda: vec_from_angle(st.a * 30, 10)
        with self.assertRaises(AttributeError) as bracket:
            self.ship["vel"] @= lambda: vec_from_angle(st.a * 30, 10)
        self.assertNotIsInstance(attr.exception, LinkedAttributeError)
        self.assertEqual(str(attr.exception), str(bracket.exception))
        msg = str(attr.exception)
        self.assertIn("vel cannot be linked with @=", msg)
        self.assertIn("ship.vel = vec_from_angle(", msg)
        self.assertIn("on_update", msg)
        self._assert_untouched()

    def test_direct_link_from_another_vec_refuses(self):
        from scena.shapes import Circle

        other = Circle(center=(0, 0), radius=5)
        other.vel = (7, 7)
        with self.assertRaises(AttributeError):
            self.ship.vel @= other.vel
        self._assert_untouched()

    def test_axis_link_refuses(self):
        st = self.st
        for axis in ("x", "y"):
            with self.subTest(axis=axis):
                with self.assertRaises(AttributeError) as ctx:
                    self.ship.vel[axis] @= lambda: st.a * 3
                self.assertIn("vel cannot be linked with @=", str(ctx.exception))
                self._assert_untouched()
                self.ship.vel = (1, 0)

    def test_vel_still_reads_as_a_link_source(self):
        p = Point(0, 0)
        p["x"] @= lambda: self.ship.vel.x * 10
        self.assertEqual(p.x, 10)
        self.ship.vel.x = 2
        self.assertEqual(p.x, 20)

    def test_attribute_and_bracket_link_agree_on_every_actor_part(self):
        """Bug class: a property that hands out an owned Container is reachable
        by ``obj.prop @= …`` (Python's in-place protocol) even when
        ``obj["prop"] @= …`` refuses. Walk every exported actor kind: where the
        bracket refuses, the attribute spelling refuses and links nothing
        (Polygon's derived ``center`` refuses as a Derivate)."""
        import scena
        from scena.entity import Entity
        from scena.state import Container

        checked = set()
        for kind_name in scena.__all__:
            kind = getattr(scena, kind_name)
            if not (isinstance(kind, type) and issubclass(kind, Entity)):
                continue
            try:
                obj = kind()
            except Exception:
                continue   # needs arguments; the shapes that matter build bare
            try:
                obj.vel = (1, 0)
            except Exception:
                pass
            for name in dir(type(obj)):
                if name.startswith("_") or not isinstance(getattr(type(obj), name, None), property):
                    continue
                try:
                    part = getattr(obj, name)
                except Exception:
                    continue
                if not isinstance(part, Container) or part is obj:
                    continue
                try:
                    obj[name]
                    continue   # linkable by bracket: the attribute spelling may link too
                except AttributeError:
                    pass
                with self.subTest(kind=kind_name, prop=name):
                    try:
                        fresh = getattr(obj, name) is not part
                    except Exception:
                        fresh = False
                    if fresh:
                        # A measurement handed out fresh on every read
                        # (``rect.box``): ``rect.box @= f`` links a throwaway
                        # copy (a measured Box is linkable as a value), then
                        # Python's store-back refuses (read-only). PC2 made
                        # the bracket refuse these names too (it made dead ink).
                        with self.assertRaises(AttributeError):
                            setattr(obj, name, part)
                        checked.add((kind_name, name))
                        continue
                    with self.assertRaises((AttributeError, DerivedAttributeError)):
                        part @= (lambda p=part: p)   # what ``obj.prop @= f`` runs first
                    self.assertIsNone(part._link)
                    checked.add((kind_name, name))
        # Canary: the walk reached the parts this guard exists for.
        for kind_name in ("Circle", "Rect", "Sprite", "Text"):
            self.assertIn((kind_name, "vel"), checked)


class TestReservedLinkRefusalPerKind(unittest.TestCase):
    """A reserved name refuses ``@=`` with the same kind of answer on every
    Graphic kind (2026-10-15). Only Line / Point (``_ink_strict``) read the
    route table; Rect, Circle, Sprite, Text said "appearance and built-in
    properties" even for a field they lack (``rect["text"]``,
    ``circle["width"]``, ``sprite["corner_radius"]``)."""

    def _graphic_kinds(self):
        import scena
        from scena.entity import Graphic
        for kind_name in scena.__all__:
            kind = getattr(scena, kind_name)
            if (isinstance(kind, type) and issubclass(kind, Graphic)
                    and not getattr(kind, "__abstractmethods__", None)):
                yield kind_name, kind()

    @staticmethod
    def _expected(obj, name):
        """``absent`` / ``property`` / ``read_only``, read from the class the
        way the route table reads it (first setter in the MRO wins)."""
        for base in type(obj).__mro__:
            desc = base.__dict__.get(name)
            if desc is not None and hasattr(desc, "__set__"):
                if isinstance(desc, property) and desc.fset is None:
                    return "read_only"
                return "property"
        try:
            object.__getattribute__(obj, name)   # a plain field or class default
        except AttributeError:
            return "absent"
        return "property"

    def test_every_kind_and_reserved_name(self):
        from scena.entity import _INK_RESERVED, _RESERVED_FAMILY
        words = {"absent": "has no field {name!r}", "property": "is a property",
                 "read_only": "is read-only"}
        checked = {}
        for kind_name, obj in self._graphic_kinds():
            self.addCleanup(obj.destroy)
            for name in sorted(_INK_RESERVED):
                try:
                    obj._resolve_field(name)
                    if name != "touching_sides":    # a formula source, never a target
                        continue    # linkable by design (angle, center, width …)
                except AttributeError:
                    pass
                expected = self._expected(obj, name)
                with self.subTest(kind=kind_name, name=name, expected=expected):
                    with self.assertRaises(AttributeError) as cm:
                        obj[name] @= (lambda: 1.0)
                    msg = str(cm.exception)
                    self.assertIn(words[expected].format(name=name), msg)
                    self.assertNotIn("appearance and built-in", msg)
                    if expected == "absent" and name in _RESERVED_FAMILY:
                        self.assertIn(f"a {_RESERVED_FAMILY[name]} field", msg)
                    else:
                        self.assertIn(f"{kind_name}.{name}" if expected != "absent"
                                      else kind_name, msg)
                    ink = getattr(obj, "_ink", None) or {}
                    self.assertNotIn(name, ink)
                checked[(kind_name, name)] = expected
        # Canary: the rows of the report, and one of each answer.
        for row, expected in ((("Rect", "text"), "absent"), (("Rect", "font_size"), "absent"),
                              (("Rect", "frame"), "absent"), (("Circle", "width"), "absent"),
                              (("Circle", "corner_radius"), "absent"),
                              (("Sprite", "corner_radius"), "absent"),
                              (("Line", "blend"), "property"), (("Rect", "glow"), "property"),
                              (("Text", "group"), "property"), (("Sprite", "gray"), "property"),
                              # Appearance links a kind excludes still refuse.
                              (("Point", "color"), "property"), (("Point", "visible"), "property"),
                              (("Track", "visible"), "property"), (("Text", "flip_x"), "property"),
                              (("Sprite", "color"), "property"),
                              (("Rect", "name"), "read_only"),
                              (("Circle", "touching_sides"), "read_only")):
            self.assertEqual(checked.get(row), expected, row)

    def test_hints_survive(self):
        from scena import Circle, Rect, Sprite
        c = Circle(center=(0, 0), radius=5)
        self.addCleanup(c.destroy)
        with self.assertRaises(AttributeError) as cm:
            c["glow"] @= lambda: 1.0
        self.assertIn(".glow = True", str(cm.exception))
        with self.assertRaisesRegex(AttributeError, "Size it with radius"):
            c["height"] @= lambda: 1.0
        r = Rect(center=(0, 0), width=10, height=10)
        self.addCleanup(r.destroy)
        with self.assertRaisesRegex(AttributeError, "Paint only"):
            r["corner_radius"] @= lambda: 1.0
        s = Sprite()
        self.addCleanup(s.destroy)
        with self.assertRaisesRegex(AttributeError, "Sprite-only"):
            s["gray"] @= lambda: 1.0

    def test_callable_write_gives_the_same_answer(self):
        """``rect.text = lambda: …`` refuses as ``rect["text"] @=`` does."""
        from scena import Rect
        from scena.state import CallableAssignError
        r = Rect(center=(0, 0), width=10, height=10)
        self.addCleanup(r.destroy)
        for name in ("text", "dash", "frame"):
            with self.subTest(name=name):
                with self.assertRaises(AttributeError) as bracket:
                    r[name] @= lambda: 1.0
                with self.assertRaises(CallableAssignError) as write:
                    setattr(r, name, lambda: 1.0)
                self.assertEqual(str(write.exception), str(bracket.exception))


class TestReservedWriteRefusalPerKind(unittest.TestCase):
    """RN1 (2026-10-15): ``=`` on a reserved name the kind does not have stored
    a plain attribute nothing reads (``rect.text = "hi"``, ``rect.frame = 3``,
    ``circle.collider = 1``), while ``rect["text"] @=`` said "Rect has no field
    'text' (a Text field)". Every exported Graphic kind × every reserved name:
    where the kind lacks the name, ``=`` raises with the words ``@=`` answers
    with, and nothing is stored."""

    _graphic_kinds = TestReservedLinkRefusalPerKind._graphic_kinds
    _expected = staticmethod(TestReservedLinkRefusalPerKind._expected)

    def test_every_kind_and_reserved_name(self):
        from scena.entity import _INK_RESERVED, _RESERVED_FAMILY
        absent = set()
        for kind_name, obj in self._graphic_kinds():
            self.addCleanup(obj.destroy)
            for name in sorted(_INK_RESERVED - {"group"}):
                if self._expected(obj, name) != "absent":
                    continue
                with self.subTest(kind=kind_name, name=name):
                    with self.assertRaises(AttributeError) as write:
                        setattr(obj, name, 1)
                    with self.assertRaises(AttributeError) as link:
                        obj[name] @= (lambda: 1.0)
                    msg = str(write.exception)
                    self.assertEqual(
                        msg, str(link.exception).replace(", so @= has nothing to link", ""))
                    self.assertIn(f"{kind_name} has no field {name!r}", msg)
                    if name in _RESERVED_FAMILY:
                        self.assertIn(f"(a {_RESERVED_FAMILY[name]} field)", msg)
                    self.assertNotIn(name, obj.__dict__)
                    self.assertNotIn(name, getattr(obj, "_ink", None) or {})
                absent.add((kind_name, name))
        # Canary: the rows of the report, a size word (E13) and a look name.
        for row in (("Rect", "text"), ("Rect", "frame"), ("Circle", "collider"),
                    ("Rect", "background"), ("Rect", "align"), ("Rect", "hitboxes"),
                    ("Rect", "offset"), ("Rect", "tilt"), ("Rect", "art_angle"),
                    ("Rect", "soft_edge"), ("Text", "model"), ("Text", "frame"),
                    ("Sprite", "text"), ("Circle", "width"), ("Rect", "font_size")):
            self.assertIn(row, absent)

    def test_fields_the_kind_has_still_write(self):
        """Plain fields set in ``__init__`` (``Text.group``) and descriptors
        (``Sprite.frame``, ``Text.text``) keep working."""
        from scena import Rect, Sprite, Text
        t = Text(text="a")
        self.addCleanup(t.destroy)
        t.text = "b"
        t.group = "hud"
        self.assertTrue(t.text == "b")
        self.assertEqual(t.group, frozenset({"hud"}))
        s = Sprite()
        self.addCleanup(s.destroy)
        s.tilt = 10
        s.offset = (1, 2)
        r = Rect(center=(0, 0), width=10, height=10)
        self.addCleanup(r.destroy)
        r.model = r.model       # every Shape has its geometry discriminant

    def test_author_subclass(self):
        """A field of the author's own under a reserved name refuses with the
        fix; a property of the author's own under it is theirs."""
        from scena import Rect

        class Placa(Rect):
            def setup(self):
                self.text = "Saída"

        with self.assertRaisesRegex(AttributeError, "Placa has no field 'text' "
                                    r"\(a Text field\)\. A field of your own"):
            Placa(center=(0, 0), width=10, height=10)

        class Carta(Rect):
            @property
            def text(self):
                return self.__dict__.get("_texto", "")

            @text.setter
            def text(self, v):
                self._texto = v

        c = Carta(center=(0, 0), width=10, height=10)
        self.addCleanup(c.destroy)
        c.text = "Ás"
        self.assertEqual(c.text, "Ás")

    def test_bare_entity_keeps_its_own_fields(self):
        """Not a Graphic: an Entity is the author's data holder (``e.angle``)."""
        from scena import Entity
        e = Entity()
        self.addCleanup(e.destroy)
        e.frame = 3
        e.text = "x"
        self.assertEqual((e.frame, e.text), (3, "x"))


class TestReservedWriteRefusalClosedKinds(unittest.TestCase):
    """RN2 (2026-10-15): RN1 on the closed non-Graphic kinds. ``button.text =
    "Play"``, ``slider.color = …``, ``fire.color = …``, ``jet.center = …``
    stored a plain attribute nothing drew. Every exported UI widget and
    SpatialFx kind (each Fire style too) × every reserved name: where the kind
    lacks the name, ``=`` raises with the words ``@=`` answers, and nothing is
    stored; the plain fields it keeps (``_reserved_fields``) still write."""

    _closed = ("Button", "TextInput", "DropDown", "Slider", "CheckBox", "Menu",
               "Fire", "Sunburst", "Starburst", "Rain", "Jet", "Sparks",
               "GlowSpot", "Orb", "Warp", "Portal")

    def _make(self, kind_name):
        import scena
        kind = getattr(scena, kind_name)
        if kind_name in ("DropDown", "Menu"):
            return [kind(options=["a", "b"])]
        if kind_name in ("Rain", "Jet"):
            return [kind(p1=(0, 0), p2=(100, 0 if kind_name == "Jet" else 80))]
        if kind_name == "Fire":
            from scena.spatial_fx_effects import FIRE_STYLES
            return [kind(center=(50, 50), style=s) for s in FIRE_STYLES]
        if issubclass(kind, scena.SpatialFx):
            return [kind(center=(50, 50))]
        return [kind()]

    def _kinds(self):
        for kind_name in self._closed:
            for obj in self._make(kind_name):
                self.addCleanup(obj.destroy)
                yield kind_name, obj

    def test_the_closed_kinds_are_every_exported_non_graphic_kind(self):
        """A new widget or effect joins the list (and the rule) on purpose;
        Entity, Act and Endless are the author's own and keep storing."""
        import scena
        from scena.entity import Entity, Graphic
        strict, open_ = set(), set()
        for kind_name in scena.__all__:
            kind = getattr(scena, kind_name)
            if (isinstance(kind, type) and issubclass(kind, Entity)
                    and not issubclass(kind, Graphic)):
                (strict if getattr(kind, "_scena_reserved_strict", False)
                 else open_).add(kind_name)
        self.assertEqual(strict - {"SpatialFx"}, set(self._closed))
        self.assertEqual(open_, {"Entity", "Act", "Endless"})

    def test_every_kind_and_reserved_name(self):
        from scena.entity import _INK_RESERVED, _RESERVED_FAMILY
        expected_of = TestReservedLinkRefusalPerKind._expected
        absent, kept = set(), set()
        for kind_name, obj in self._kinds():
            for name in sorted(_INK_RESERVED - {"group"}):
                if expected_of(obj, name) != "absent":
                    if name in vars(obj):       # a plain field of __init__
                        with self.subTest(kind=type(obj).__name__, name=name, held=True):
                            setattr(obj, name, getattr(obj, name))
                        kept.add((type(obj).__name__, name))
                    continue
                with self.subTest(kind=type(obj).__name__, name=name):
                    with self.assertRaises(AttributeError) as write:
                        setattr(obj, name, 1)
                    with self.assertRaises(AttributeError) as link:
                        obj[name] @= (lambda: 1.0)
                    msg = str(write.exception)
                    self.assertEqual(
                        msg, str(link.exception).replace(", so @= has nothing to link", ""))
                    self.assertIn(f"{type(obj).__name__} has no field {name!r}", msg)
                    if name in _RESERVED_FAMILY:
                        self.assertIn(f"(a {_RESERVED_FAMILY[name]} field)", msg)
                    self.assertNotIn("Graphics only", msg)
                    self.assertNotIn(name, obj.__dict__)
                    self.assertNotIn(name, getattr(obj, "_ink", None) or {})
                absent.add((type(obj).__name__, name))
        # Canary: the rows of the report, and the fields each kind keeps.
        for row in (("Button", "text"), ("Slider", "color"), ("CheckBox", "frame"),
                    ("Button", "center"), ("CheckBox", "height"), ("Fire", "color"),
                    ("Fire", "width"), ("Fire", "angle"), ("Jet", "center"),
                    ("Orb", "scale"), ("Menu", "color"), ("Rain", "size")):
            self.assertIn(row, absent)
        for row in (("Button", "width"), ("Button", "height"), ("CheckBox", "size"),
                    ("Fire", "soft_edge"), ("Rain", "model"), ("Jet", "model"),
                    ("Orb", "glow"), ("Portal", "angle"), ("Portal", "tilt")):
            self.assertIn(row, kept)

    def test_hints_name_the_kinds_own_field(self):
        import scena
        cases = (
            (scena.Button(label="Jogar"), "text", "Its caption is `.label`."),
            (scena.Slider(), "center", "placed by `top_left=(x, y)`"),
            (scena.CheckBox(), "height", "Size it with size."),
            (scena.Menu(options=["a"]), "color", "Menu(..., color=…)"),
            (scena.Fire(center=(0, 0)), "width", "Size it with radius."),
            (scena.Fire(center=(0, 0), style="plume"), "height",
             "Size it with width / length."),
            (scena.Jet(p1=(0, 0), p2=(10, 0)), "center", "p1= / p2="),
            (scena.Rain(p1=(0, 0), p2=(10, 10)), "size", "Size it with width / height."),
        )
        for obj, name, words in cases:
            self.addCleanup(obj.destroy)
            with self.subTest(kind=type(obj).__name__, name=name):
                with self.assertRaises(AttributeError) as cm:
                    setattr(obj, name, 1)
                self.assertIn(words, str(cm.exception))

    def test_menu_center_still_moves_it(self):
        """``Menu.center`` is attached after the class is made; its route was
        built before (bug class below)."""
        import scena
        m = scena.Menu(options=["a"])
        self.addCleanup(m.destroy)
        m.center = (30, 40)
        self.assertEqual((m.center.x, m.center.y), (30, 40))

    def test_route_built_at_class_creation_matches_a_fresh_one(self):
        """Bug class: a descriptor attached to a class after it was made
        (``Menu.center = ContainerSlot(Point)``) is missing from the route
        table built at creation, which then refuses (or stores) the name
        instead of reaching the descriptor. Every exported Entity kind."""
        import scena
        from scena.entity import Entity, _install_setattr_route

        def shape(route):
            return {k: (type(v).__name__, getattr(v, "message", None))
                    for k, v in route.items()}

        for kind_name in scena.__all__:
            kind = getattr(scena, kind_name)
            if not (isinstance(kind, type) and issubclass(kind, Entity)):
                continue
            if "_setattr_route" not in kind.__dict__:
                continue        # built on first write, from the finished class
            built = kind._setattr_route
            with self.subTest(kind=kind_name):
                try:
                    _install_setattr_route(kind)
                    self.assertEqual(shape(built), shape(kind._setattr_route))
                finally:
                    kind._setattr_route = built

    def test_author_subclass(self):
        """A field of the author's own under a reserved name refuses with the
        fix; a property of the author's own under it is theirs."""
        from scena import Fire, Button

        class Tocha(Fire):
            def setup(self):
                self.color = "orange"

        with self.assertRaisesRegex(AttributeError, "Tocha has no field 'color'. "
                                    "A field of your own"):
            Tocha(center=(0, 0))

        class Botao(Button):
            @property
            def text(self):
                return self.label

            @text.setter
            def text(self, v):
                self.label = v

        b = Botao()
        self.addCleanup(b.destroy)
        b.text = "Sair"
        self.assertEqual(b.label, "Sair")


class TestBracketRefusesWhatAssignRefuses(unittest.TestCase):
    """PC2 (2026-10-14): ``obj["name"] @= f`` made a new ink field — a link
    nothing reads — when ``name`` is a method (``c["move_to"]``), a read-only
    property (``tri["points"]``, ``poly["pointer_hover"]``) or a Polygon
    vertex name (``tri["v1"]``), while ``obj.name = …`` refuses. The route
    guard (R8) covered ``=`` only."""

    def _kinds(self):
        import scena
        from scena.entity import Entity
        for kind_name in scena.__all__:
            kind = getattr(scena, kind_name)
            if not (isinstance(kind, type) and issubclass(kind, Entity)):
                continue
            try:
                yield kind_name, kind()
            except Exception:
                continue   # needs arguments; the shapes that matter build bare

    def test_every_refused_route_name_refuses_the_bracket(self):
        """Bug class: every name ``=`` refuses through the route table (a
        method, a read-only property, a size / point word the kind lacks)
        refuses ``obj[name] @=`` with the same message, and makes no ink."""
        from scena.entity import _INK_RESERVED, _RouteRefusal, _install_setattr_route
        checked = set()
        for kind_name, obj in self._kinds():
            cls = type(obj)
            if "_setattr_route" not in cls.__dict__:
                _install_setattr_route(cls)
            for name, route in cls._setattr_route.items():
                if not isinstance(route, _RouteRefusal):
                    continue
                try:
                    obj._resolve_field(name)
                    continue        # a field by design (a widget's ``value``)
                except AttributeError:
                    pass
                with self.subTest(kind=kind_name, name=name):
                    with self.assertRaises(AttributeError) as cm:
                        obj[name] @= (lambda: 1.0)
                    own = getattr(cls, "_ink_name_refusal", None)
                    if name not in _INK_RESERVED and (own is None or own(name) is None):
                        # Reserved names keep their own @= message.
                        self.assertEqual(str(cm.exception),
                                         route.message.format(cls=cls.__name__))
                    ink = getattr(obj, "_ink", None) or {}
                    self.assertNotIn(name, ink)
                    checked.add((kind_name, name))
        for row in (("Circle", "move_to"), ("Polygon", "pointer_hover"),
                    ("Polygon", "contains_point"), ("Circle", "top_left")):
            self.assertIn(row, checked)

    def test_examples_from_the_report(self):
        from scena import Anchor, Circle, Polygon
        b = Anchor(100, 0)
        c = Circle(center=(0, 0), radius=5)
        with self.assertRaisesRegex(AttributeError, "is a method"):
            c["move_to"] @= lambda: b.center.x
        tri = Polygon(points=[(0, 0), (10, 0), (0, 10)])
        for name, words in (("points", "points[i] @="), ("v1", "points[1] @="),
                            ("pointer_hover", "read-only")):
            with self.subTest(name=name):
                with self.assertRaises(AttributeError) as cm:
                    tri[name] @= lambda: (b.center.x, b.center.y)
                self.assertIn(words, str(cm.exception))
        # The plain write of a vertex name refuses too (it was ink).
        with self.assertRaisesRegex(AttributeError, r"points\[1\]"):
            tri.v1 = (1, 1)
        self.assertFalse(getattr(tri, "_ink", None))

    def test_settable_property_is_not_ink(self):
        from scena import Track
        tr = Track(points=[(0, 0), (10, 0)])
        with self.assertRaisesRegex(AttributeError, "is a property"):
            tr["is_floating"] @= lambda: True

    def test_ink_still_links(self):
        from scena import Anchor, Circle
        b = Anchor(3, 0)
        c = Circle(center=(0, 0), radius=5)
        c["hp"] @= lambda: b.center.x * 2
        self.assertEqual(c.hp, 6.0)


class TestPolygonVertexLink(unittest.TestCase):
    """PC3 (2026-10-14): ``tri.points[1] @= f`` raised "'tuple' object does
    not support item assignment" although the link was installed (Python runs
    ``@=`` on the vertex, then stores it back into ``points``). The view takes
    its own vertex back, so the statement links cleanly, like ``line.p1 @= f``."""

    def test_vertex_link_through_points(self):
        from scena import Anchor, Polygon
        b = Anchor(100, 0)
        tri = Polygon(points=[(0, 0), (10, 0), (0, 10)])
        tri.points[1] @= lambda: b.center
        b.move_to(200, 50)
        self.assertEqual((tri.points[1].x, tri.points[1].y), (200.0, 50.0))
        self.assertIsInstance(tri.points, tuple)
        self.assertEqual(len(tri.points), 3)

    def test_plain_store_refuses_and_changes_nothing(self):
        from scena import Polygon, RegularPolygon
        tri = Polygon(points=[(0, 0), (10, 0), (0, 10)])
        with self.assertRaises(TypeError) as cm:
            tri.points[1] = (5, 5)
        self.assertIn("points[1].move_to", str(cm.exception))
        self.assertEqual((tri.points[1].x, tri.points[1].y), (10.0, 0.0))
        hexa = RegularPolygon(center=(0, 0), radius=5, n=6)
        with self.assertRaisesRegex(TypeError, "computed from its center"):
            hexa.points[0] = (1, 1)

    def test_derived_vertex_link_refuses_and_installs_nothing(self):
        from scena import Anchor, RegularPolygon
        b = Anchor(1, 1)
        hexa = RegularPolygon(center=(0, 0), radius=5, n=6)
        with self.assertRaises(DerivedAttributeError):
            hexa.points[1] @= lambda: b.center
        self.assertIsNone(hexa.points[1]._link)

    def test_every_computed_vertex_kind_says_computed(self):
        """Bug class (0.9.0 merge): Triangle left ``RegularPolygon`` for the
        shared ``_RadialPolygon``, and refusals keyed on ``RegularPolygon``
        gave it the free-vertex advice ("link one vertex: points[i] @=") or
        named the wrong kind. Every computed-vertex kind, author subclasses
        included, refuses a vertex write as computed, under its own name."""
        from scena import Anchor, RegularPolygon, Triangle

        class Hex(RegularPolygon):
            pass

        class Nave(Triangle, base_ratio=0.6):
            pass

        b = Anchor(1, 1)
        for make, label, inputs in (
                (lambda: RegularPolygon(center=(0, 0), radius=5, n=6),
                 "RegularPolygon", "center, radius and angle"),
                (lambda: Hex(center=(0, 0), radius=5, n=6),
                 "Hex", "center, radius and angle"),
                (lambda: Triangle(center=(0, 0), radius=5),
                 "Triangle", "center, radius, angle and base_ratio"),
                (lambda: Nave(center=(0, 0), radius=5),
                 "Nave", "center, radius, angle and base_ratio")):
            poly = make()
            for name in ("points", "v1"):
                with self.subTest(kind=label, name=name):
                    with self.assertRaises(AttributeError) as cm:
                        poly[name] @= lambda: (b.center.x, b.center.y)
                    msg = str(cm.exception)
                    self.assertIn(f"computed from its {inputs}", msg)
                    self.assertIn(f"{label}.{name}", msg)
                    self.assertNotIn("points[1] @=", msg)
                    self.assertFalse(getattr(poly, "_ink", None))
            with self.subTest(kind=label, store="points[0] ="):
                with self.assertRaises(TypeError) as cm:
                    poly.points[0] = (1, 1)
                self.assertIn(f"computed from its {inputs}", str(cm.exception))
            kind = poly._KIND_LABEL
            with self.subTest(kind=label, index="'a'"):
                with self.assertRaisesRegex(TypeError, rf"^{kind}\.points takes"):
                    poly.points["a"]


class TestFormulaLinkNamedFunction(unittest.TestCase):
    def test_named_function_links_like_a_lambda(self):
        """A ``def`` is read the same way as a lambda (tests/test_formula_functions.py)."""
        src = Attribute(3.0)
        sink = Attribute(0.0)

        def doubled():
            return src.value * 2

        sink @= doubled
        self.assertEqual(sink.value, 6.0)
        src.value = 4.0
        self.assertEqual(sink.value, 8.0)



class TestUnlinkKeepsReaders(unittest.TestCase):
    """AC12 (found by test_hyp_api.ReactiveLinksMachine, 2026-10-10): unlinking
    a scalar or ink field that another formula reads dropped the field's graph
    anchor, which is also the node the reader depends on: the reader was
    unlinked ("a formula source was removed") and froze at a stale value. The
    Guia: ``unlink`` freezes the field at its current value; readers keep
    reading it."""

    def _quiet(self, fn):
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            fn()
        return [str(x.message) for x in w if "was unlinked" in str(x.message)]

    def _check(self, owner, field, src, read):
        owner[field] @= lambda: src.value + 1
        reader = Attribute(0.0)
        reader @= lambda: read() * 10
        self.assertEqual(reader.value, 30.0)
        self.assertEqual(self._quiet(owner[field].unlink), [])
        self.assertIsNotNone(reader._link, "the reader was unlinked")
        self.assertFalse(owner[field].is_linked)
        src.value = 7                       # the field is frozen now
        self.assertEqual(read(), 3.0)
        setattr(owner, field, 5.0)          # a write reaches the reader
        self.assertEqual(reader.value, 50.0)
        with self.assertRaises(LinkedAttributeError):
            reader.value = 1

    def test_ink_field(self):
        from scena.shapes import Circle
        c = Circle(center=(0, 0), radius=10)
        c.hp = 0.0
        self._check(c, "hp", Attribute(2.0), lambda: c.hp)

    def test_scalar_slot_field(self):
        from scena.shapes import Circle
        c = Circle(center=(0, 0), radius=10)
        self._check(c, "radius", Attribute(2.0), lambda: c.radius)

    def test_an_unread_field_drops_its_anchor(self):
        from scena.shapes import Circle
        c = Circle(center=(0, 0), radius=10)
        src = Attribute(2.0)
        c["radius"] @= lambda: src.value + 1
        c["radius"].unlink()
        self.assertNotIn("radius", c.__dict__.get("_field_anchors") or {})
        self.assertEqual(c.radius, 3.0)



class TestOwnSizeReadIsAKnownLimit(unittest.TestCase):
    """AC14 (decided 2026-10-10: a known limitation, documented). A custom field
    of an object cannot read the object's own size fields or computed points:
    they are worked out from the whole object, the new field included. The
    refusal says so and names the idiom (a class property, or update(dt)),
    installs nothing, and a real cycle keeps the generic message."""

    def _refused(self, owner, name, fn):
        from scena.state import CircularReferenceError
        with self.assertRaises(CircularReferenceError) as ctx:
            owner[name] @= fn
        anchors = owner.__dict__.get("_field_anchors") or {}
        self.assertTrue(name not in anchors or anchors[name]._link is None, "the refusal installed a link")
        return str(ctx.exception)

    def test_the_message_names_the_limit_and_the_idiom(self):
        from scena.shapes import Circle, Polygon, Rect
        r = Rect(center=(0, 0), width=4, height=4)
        c = Circle(center=(0, 0), radius=3)
        p = Polygon(points=[(0, 0), (40, 0), (20, 30)])
        try:
            for owner, fn in ((r, lambda: r.width * 2), (r, lambda: r.top_left.x),
                              (c, lambda: c.radius + 1), (p, lambda: p.center.x)):
                with self.subTest(kind=type(owner).__name__):
                    msg = self._refused(owner, "dano", fn)
                    self.assertIn("known limit", msg)
                    self.assertIn("@property def dano(self)", msg)
        finally:
            for s in (r, c, p):
                s.destroy()

    def test_what_still_reads_fine(self):
        from scena.shapes import Rect
        other = Rect(center=(0, 0), width=6, height=4)
        r = Rect(center=(1, 2), width=4, height=4)
        try:
            r.carga = 2.0
            r["a"] @= lambda: r.carga * 2           # its own custom field
            r["b"] @= lambda: r.center.x + 1        # its center (a placement point)
            r["c"] @= lambda: other.width * 2       # another object's size
            self.assertEqual((r.a, r.b, r.c), (4.0, 2.0, 12.0))
        finally:
            r.destroy()
            other.destroy()

    def test_a_real_cycle_keeps_the_generic_message(self):
        from scena.shapes import Rect
        from scena.state import CircularReferenceError
        r = Rect(center=(0, 0), width=4, height=4)
        try:
            r.a = 1.0
            r["b"] @= lambda: r.a + 1
            with self.assertRaises(CircularReferenceError) as ctx:
                r["a"] @= lambda: r.b + 1
            self.assertIn("Link one direction only", str(ctx.exception))
            self.assertNotIn("known limit", str(ctx.exception))
        finally:
            r.destroy()


if __name__ == "__main__":
    unittest.main()
