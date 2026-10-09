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
        self.assertEqual(st.dst.value, 3.0)
        st.src = 8.0
        self.assertEqual(st.dst.value, 8.0)

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
        st.dst @= lambda: st.src.value * 10
        self.assertEqual(st.dst.value, 30)
        with self.assertRaises(LinkedAttributeError) as ctx:
            st.dst = 1
        self.assertIn("State.dst is linked", str(ctx.exception))
        self.assertIn("State['dst'].unlink()", str(ctx.exception))
        st.dst.unlink()
        st.dst = 1
        self.assertEqual(st.dst.value, 1)

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
        st["dst"] @= lambda: st.src.value * 10
        self.assertEqual(st.dst.value, 30)
        self.assertTrue(st["dst"].is_linked)
        st.src = 4
        self.assertEqual(st.dst.value, 40)

    def test_bracket_value_is_payload(self):
        st = State()
        st.create("score", initial=12.5)
        self.assertEqual(st["score"].value, 12.5)
        self.assertIsInstance(st.score, Attribute)

    def test_linked_dot_assign_raises_then_unlink(self):
        st = State()
        st.create("src", initial=3)
        st.create("dst", initial=0)
        st["dst"] @= lambda: st.src.value * 10
        with self.assertRaises(LinkedAttributeError) as ctx:
            st.dst = 1
        self.assertIn("State.dst", str(ctx.exception))
        self.assertIn("State['dst'].unlink()", str(ctx.exception))
        st["dst"].unlink()
        self.assertFalse(st["dst"].is_linked)
        st.dst = 1
        self.assertEqual(st.dst.value, 1)

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
        self.assertEqual(unlabeled.t.name, "State.t")
        ref = unlabeled["t"]
        self.assertIsInstance(ref, FieldRef)
        self.assertIs(ref.owner, unlabeled)

        st = State(name="st")
        self.assertEqual(st.name, "st")
        hud = State(name="hud")
        self.assertEqual(hud.name, "hud")
        hud.score = 0
        self.assertEqual(hud.score.name, "hud.score")
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
        self.assertAlmostEqual(st.t.value, 10.0, places=5)
        _frame(0.1)
        self.assertAlmostEqual(st.t.value, 20.0, places=5)

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
        for field in (
            "fill", "line", "visual", "line_width", "dash", "blend",
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

        c = Circle(center=(0, 0), radius=10)
        with self.assertRaises(AttributeError) as ctx:
            c.line_width = lambda: 5.0
        msg = str(ctx.exception)
        self.assertIn("cannot be linked with @=", msg)
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
            b["line_width"] @= lambda: a.radius * 2
        self.assertIsNone(getattr(b, "_ink", None))
        self.assertEqual(b.line_width, 1.5)


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
        self.assertIn("cannot be linked with @=", str(ctx.exception))
        self.assertIn("Graphics only", str(ctx.exception))
        e.angle = 12.0
        self.assertEqual(e.angle, 12.0)
        with self.assertRaises(AttributeError) as ctx:
            e["scale"]
        self.assertIn("cannot be linked with @=", str(ctx.exception))
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
                    with self.assertRaises((AttributeError, DerivedAttributeError)):
                        part @= (lambda p=part: p)   # what ``obj.prop @= f`` runs first
                    self.assertIsNone(part._link)
                    checked.add((kind_name, name))
        # Canary: the walk reached the parts this guard exists for.
        for kind_name in ("Circle", "Rect", "Sprite", "Text"):
            self.assertIn((kind_name, "vel"), checked)


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


if __name__ == "__main__":
    unittest.main()
