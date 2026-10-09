"""
Extensive shape tests: multi-model construction, derived attributes, and
transforms (move/rotate/scale) for every shape in shapes.py.

Covers common cases, boundary/degenerate cases, and the Defining/Derivate
guards (LinkedAttributeError / DerivedAttributeError) documented in
`Shapes Design.md`.

Run headless (no window) with either:

    python -m unittest tests.test_shapes -v
    python tests/test_shapes.py
"""

import os

import math
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hypothesis_support  # noqa: E402,F401  (loads the Hypothesis profile)
from hypothesis import given  # noqa: E402
from hypothesis import strategies as hst  # noqa: E402

from scena.shapes import (
    Point, Anchor, Line, LineModel, Rect, RectModel, Square, Circle, CircleModel,
    Ellipse, EllipseModel, Polygon, RegularPolygon, RegularPolygonModel,
    EquilateralTriangle, get_xy, distance, heading, middle_point, nearest,
)
from scena.state import LinkedAttributeError, DerivedAttributeError, Attribute
from scena.scenamath import Vec2
from scena.box import Box


class ShapeTestCase(unittest.TestCase):
    """Common numeric-comparison helpers for shape tests."""

    def assertPointAlmost(self, point, x, y, places=6, msg=None):
        self.assertAlmostEqual(point.x, x, places=places, msg=msg or f"x: {point.x} != {x}")
        self.assertAlmostEqual(point.y, y, places=places, msg=msg or f"y: {point.y} != {y}")

    def assertNumAlmost(self, attr, value, places=6, msg=None):
        got = attr.value if hasattr(attr, 'value') else attr
        self.assertAlmostEqual(got, value, places=places, msg=msg)


# ---------------------------------------------------------------------------
# Point
# ---------------------------------------------------------------------------
class TestPoint(ShapeTestCase):
    def test_basic_construction(self):
        p = Point(3, 4)
        self.assertEqual(p.x, 3)
        self.assertEqual(p.y, 4)
        self.assertIs(p.center, p)

    def test_default_construction(self):
        p = Point()
        self.assertEqual(p.x, 0.0)
        self.assertEqual(p.y, 0.0)

    def test_temp_never_links(self):
        src = Point(1, 2)
        t = Point.temp(src.x, src.y)
        self.assertEqual(t.x, 1)
        self.assertEqual(t.y, 2)
        src.x = 99
        # temp must NOT track src -- it copies bare values only.
        self.assertEqual(t.x, 1)

    def test_move_by_and_to(self):
        p = Point(1, 1)
        p.move_by(2, 3)
        self.assertPointAlmost(p, 3, 4)
        p.move_to(10, 20)
        self.assertPointAlmost(p, 10, 20)
        p.move_to(x=None, y=5)  # partial move_to leaves x untouched
        self.assertPointAlmost(p, 10, 5)

    def test_rotate_by_about_pivot(self):
        p = Point(1, 0)
        p.rotate_by(90, about=(0, 0))
        self.assertPointAlmost(p, 0, 1)

    def test_rotate_by_about_self_is_noop(self):
        p = Point(5, 5)
        p.rotate_by(60)  # default pivot is self -> distance 0 -> no-op for position
        self.assertPointAlmost(p, 5, 5)

    def test_rotate_by_about_self_still_turns_the_heading(self):
        # Regression: rotate_by returned before adding the angle when the
        # pivot was the point itself, while rotate_to set it (and every other
        # kind adds it). raycast(p, length=) reads this heading.
        p = Point(5, 5)
        p.rotate_by(60)
        self.assertAlmostEqual(float(p.angle), 60.0)
        p.rotate_by(30, about=(5, 5))
        self.assertAlmostEqual(float(p.angle), 90.0)
        p.rotate_to(10)
        self.assertAlmostEqual(float(p.angle), 10.0)
        self.assertPointAlmost(p, 5, 5)

    def test_rotate_by_about_self_on_a_linked_point(self):
        # Position does not move, so a linked point turns without force=
        # (same as rotate_to at distance 0) and stays linked.
        src = Point(1, 1)
        dst = Point(0, 0)
        dst @= src
        dst.rotate_by(45)
        self.assertAlmostEqual(float(dst.angle), 45.0)
        src.move_by(2, 0)
        self.assertPointAlmost(dst, 3, 1)

    def test_scale_by_about_pivot(self):
        p = Point(2, 0)
        p.scale_by(3, about=(0, 0))
        self.assertPointAlmost(p, 6, 0)

    def test_takein_from_tuple_and_point(self):
        p = Point(0, 0)
        p._takein((5, 6))
        self.assertPointAlmost(p, 5, 6)
        other = Point(7, 8)
        p._takein(other)
        self.assertPointAlmost(p, 7, 8)

    def test_takein_from_mouse_like_and_graphic(self):
        p = Point(0, 0)
        mouseish = type("M", (), {"x": 11.0, "y": 22.0})()
        p._takein(mouseish)
        self.assertPointAlmost(p, 11, 22)
        ball = Circle(center=(3, 4), radius=1)
        p._takein(ball)
        self.assertPointAlmost(p, 3, 4)
        ball.move_to(9, 8)
        self.assertPointAlmost(p, 3, 4)

    def test_linking_via_imatmul(self):
        src = Point(1, 1)
        dst = Point(0, 0)
        dst @= src
        self.assertPointAlmost(dst, 1, 1)
        src.move_by(5, 5)
        self.assertPointAlmost(dst, 6, 6)

    def test_rotate_by_respects_ensure_writable(self):
        src = Point(1, 1)
        dst = Point(0, 0)
        dst @= src
        with self.assertRaises(LinkedAttributeError):
            dst.rotate_by(math.degrees(0.1), about=(0, 0))
        # force=True unlinks and proceeds
        dst.rotate_by(math.degrees(0.1), about=(0, 0), force=True)

    def test_move_by_respects_ensure_writable(self):
        src = Point(1, 1)
        dst = Point(0, 0)
        dst @= src
        with self.assertRaises(LinkedAttributeError):
            dst.move_by(1, 0)
        dst.move_by(1, 0, force=True)
        self.assertPointAlmost(dst, 2, 1)

    def test_construct_from_tuple(self):
        p = Point((5, 6))
        self.assertPointAlmost(p, 5, 6)

    def test_construct_from_point_copies(self):
        src = Point(7, 8)
        p = Point(src)
        self.assertPointAlmost(p, 7, 8)
        src.move_to(99, 100)
        self.assertPointAlmost(p, 7, 8)  # snapshot, not a link

    def test_construct_from_vec2(self):
        p = Point(Vec2(3, 4))
        self.assertPointAlmost(p, 3, 4)

    def test_construct_from_graphic_center(self):
        c = Circle(center=(10, 20), radius=5)
        p = Point(c)
        self.assertPointAlmost(p, 10, 20)
        c.move_to(50, 60)
        self.assertPointAlmost(p, 10, 20)

    def test_construct_from_box_center(self):
        box = Box(center=(100, 200), width=40, height=20)
        p = Point(box.center)
        self.assertPointAlmost(p, 100, 200)

    def test_construct_from_mouse_like(self):
        mouseish = type("M", (), {"x": 11.0, "y": 22.0})()
        p = Point(mouseish)
        self.assertPointAlmost(p, 11, 22)

    def test_center_formula_follows_mouse_like_container(self):
        from scena.input import Mouse
        mouse = Mouse()
        mouse._update_position(4, 5)
        live = Circle(center=lambda: mouse, radius=3)
        self.assertPointAlmost(live.center, 4, 5)
        mouse._update_position(12, 9)
        self.assertPointAlmost(live.center, 12, 9)
        pinned = Circle(center=mouse, radius=3)
        mouse._update_position(1, 1)
        self.assertPointAlmost(pinned.center, 12, 9)

    def test_center_formula_follows_graphic(self):
        player = Circle(center=(1, 2), radius=4)
        follower = Circle(center=lambda: player, radius=2)
        self.assertPointAlmost(follower.center, 1, 2)
        player.move_to(9, 8)
        self.assertPointAlmost(follower.center, 9, 8)

    def test_construct_whole_point_formula(self):
        src = Point(1, 2)
        p = Point(lambda: src)
        self.assertPointAlmost(p, 1, 2)
        src.move_to(9, 8)
        self.assertPointAlmost(p, 9, 8)

    def test_construct_tuple_links_one_axis(self):
        src = Point(5, 0)
        p = Point((lambda: src.x, 10))
        self.assertPointAlmost(p, 5, 10)
        src.x = 42
        self.assertPointAlmost(p, 42, 10)

    def test_construct_one_scalar_and_keywords(self):
        p = Point(3)
        self.assertPointAlmost(p, 3, 0)
        p2 = Point(x=3, y=4)
        self.assertPointAlmost(p2, 3, 4)
        p3 = Point(None, 5)
        self.assertPointAlmost(p3, 0, 5)

    def test_construct_point_like_with_layer(self):
        src = Point(1, 2)
        p = Point(src, layer="top")
        self.assertPointAlmost(p, 1, 2)
        self.assertEqual(p.layer, "top")
        self.assertTrue(p.visible)

    def test_construct_invalid_raises(self):
        with self.assertRaises(TypeError):
            Point("nope")
        with self.assertRaises(TypeError):
            Point((1, 2, 3))
        with self.assertRaises(TypeError):
            Point(Point(1, 2), 5)  # two-arg stays scalars only

    def test_anchor_from_point_like_copies(self):
        box = Box(center=(40, 50), width=10, height=10)
        a = Anchor(box.center)
        self.assertPointAlmost(a, 40, 50)
        self.assertTrue(a.handle)

    def test_anchor_rejects_formula(self):
        src = Point(1, 2)
        with self.assertRaises(LinkedAttributeError):
            Anchor(lambda: src)


# ---------------------------------------------------------------------------
# distance (standalone + Point.distance)
# ---------------------------------------------------------------------------
class TestDistance(ShapeTestCase):
    def test_point_point_345(self):
        a = Point(0, 0)
        b = Point(3, 4)
        self.assertNumAlmost(distance(a, b), 5.0)

    def test_tuple_tuple(self):
        self.assertNumAlmost(distance((0, 0), (3, 4)), 5.0)

    def test_mixed_general_point(self):
        p = Point(1, 1)
        v = Vec2(4, 5)
        self.assertNumAlmost(distance(p, v), 5.0)
        self.assertNumAlmost(distance(p, (4, 5)), 5.0)
        self.assertNumAlmost(distance((0, 0), v), math.hypot(4, 5))

    def test_symmetric_and_zero(self):
        a = Point(2, -3)
        b = Point(8, 5)
        self.assertNumAlmost(distance(a, b), distance(b, a))
        self.assertNumAlmost(distance(a, a), 0.0)
        self.assertNumAlmost(distance((7, 7), (7, 7)), 0.0)

    def test_method_matches_standalone(self):
        a = Point(10, 20)
        b = Point(13, 24)
        self.assertNumAlmost(a.distance(b), distance(a, b))
        self.assertNumAlmost(a.distance((13, 24)), 5.0)
        self.assertNumAlmost(a.distance(Vec2(13, 24)), 5.0)

    def test_graphic_and_xy_object(self):
        a = Circle(center=(0, 0), radius=1)
        b = Circle(center=(3, 4), radius=1)
        self.assertNumAlmost(distance(a, b), 5.0)
        mouseish = type("M", (), {"x": 3.0, "y": 4.0})()
        self.assertNumAlmost(distance(a, mouseish), 5.0)

    def test_vec2_delegates_to_free_function(self):
        v = Vec2(0, 0)
        p = Point(3, 4)
        self.assertNumAlmost(v.distance(p), 5.0)
        self.assertNumAlmost(v.distance((3, 4)), 5.0)
        circ = Circle(center=(3, 4), radius=1)
        self.assertNumAlmost(v.distance(circ), 5.0)

    def test_invalid_raises(self):
        with self.assertRaises(TypeError):
            distance(Point(0, 0), "nope")
        with self.assertRaises(TypeError):
            distance((0, 0, 0), (1, 1))

    def test_live_formula(self):
        a = Point(0, 0)
        b = Point(3, 4)
        c = Circle(center=(0, 0), radius=1)
        c["radius"] @= lambda: distance(a, b)
        self.assertNumAlmost(c.radius, 5.0)
        b.move_to(6, 8)
        self.assertNumAlmost(c.radius, 10.0)


# ---------------------------------------------------------------------------
# middle_point
# ---------------------------------------------------------------------------
class TestMiddlePoint(ShapeTestCase):
    def test_midpoint_and_weight(self):
        self.assertEqual(middle_point((0, 0), (10, 4)), (5.0, 2.0))
        self.assertEqual(middle_point((0, 0), (10, 0), weight=0.0), (0.0, 0.0))
        self.assertEqual(middle_point((0, 0), (10, 0), weight=1.0), (10.0, 0.0))

    def test_graphic_without_center_attr_access(self):
        a = Circle(center=(0, 0), radius=1)
        b = Circle(center=(10, 4), radius=1)
        self.assertEqual(middle_point(a, b), (5.0, 2.0))

    def test_invalid_weight(self):
        with self.assertRaises(ValueError):
            middle_point((0, 0), (1, 1), weight=1.5)


# ---------------------------------------------------------------------------
# heading (standalone + Point.heading)
# ---------------------------------------------------------------------------
class TestHeading(ShapeTestCase):
    def test_axis_bearings(self):
        o = Point(0, 0)
        self.assertNumAlmost(heading(o, Point(1, 0)), 0.0)
        self.assertNumAlmost(heading(o, Point(0, 1)), 90.0)
        self.assertNumAlmost(heading(o, Point(-1, 0)), 180.0)
        self.assertNumAlmost(heading(o, Point(0, -1)), -90.0)

    def test_tuple_and_vec2(self):
        self.assertNumAlmost(heading((0, 0), (0, 1)), 90.0)
        self.assertNumAlmost(heading(Vec2(0, 0), Vec2(1, 0)), 0.0)

    def test_graphic_without_center(self):
        hero = Circle(center=(10, 10), radius=4)
        foe = Circle(center=(20, 10), radius=4)
        self.assertNumAlmost(heading(hero, foe), 0.0)
        self.assertNumAlmost(heading(hero, Circle(center=(10, 20), radius=1)), 90.0)

    def test_mouse_like(self):
        hero = Circle(center=(0, 0), radius=1)
        mouseish = type("M", (), {"x": 0.0, "y": 5.0})()
        self.assertNumAlmost(heading(hero, mouseish), 90.0)

    def test_method_matches_standalone(self):
        a = Point(0, 0)
        b = Point(0, 4)
        self.assertNumAlmost(a.heading(b), heading(a, b))
        self.assertNumAlmost(a.heading((0, 4)), 90.0)
        circ = Circle(center=(4, 0), radius=1)
        self.assertNumAlmost(a.heading(circ), 0.0)

    def test_coincident_is_zero(self):
        p = Point(3, 7)
        self.assertNumAlmost(heading(p, p), 0.0)
        self.assertNumAlmost(heading((1, 1), (1, 1)), 0.0)
        c = Circle(center=(2, 2), radius=1)
        self.assertNumAlmost(heading(c, c), 0.0)

    def test_swapped_args_flip_by_180(self):
        self.assertNumAlmost(heading((0, 0), (1, 0)), 0.0)
        self.assertNumAlmost(heading((1, 0), (0, 0)), 180.0)
        self.assertNumAlmost(heading((0, 0), (0, 1)), 90.0)
        self.assertNumAlmost(heading((0, 1), (0, 0)), -90.0)

    def test_matches_displacement_angle(self):
        a = Point(2, 3)
        b = Point(5, 7)
        self.assertNumAlmost(heading(a, b), (b - a).angle)

    def test_invalid_raises(self):
        with self.assertRaises(TypeError):
            heading(Point(0, 0), "nope")
        with self.assertRaises(TypeError):
            heading("nope", (0, 0))


# ---------------------------------------------------------------------------
# nearest (standalone)
# ---------------------------------------------------------------------------
class TestNearest(ShapeTestCase):
    def test_mixed_origin_and_items(self):
        a = Point(0, 0)
        b = Point(10, 0)
        c = Point(3, 0)
        self.assertIs(nearest(a, [b, c]), c)
        self.assertIs(nearest((0, 0), [b, c]), c)
        self.assertIs(nearest(Vec2(0, 0), [(10, 0), (3, 0)]), (3, 0))
        circ = Circle(center=(1, 0), radius=2)
        self.assertIs(nearest(Point(0, 0), [b, circ]), circ)

    def test_returns_original_identity(self):
        a = (10, 0)
        b = (3, 0)
        items = [a, b]
        self.assertIs(nearest((0, 0), items), b)

    def test_empty_and_unpositioned(self):
        self.assertIsNone(nearest((0, 0), []))
        self.assertIsNone(nearest((0, 0), ["nope", object()]))

    def test_tie_first_wins(self):
        a = Point(5, 0)
        b = Point(5, 0)
        self.assertIs(nearest((0, 0), [a, b]), a)

    def test_within(self):
        near = Point(3, 0)
        far = Point(10, 0)
        self.assertIs(nearest((0, 0), [near, far], within=5), near)
        self.assertIsNone(nearest((0, 0), [near, far], within=2))
        self.assertIs(nearest((0, 0), [near], within=3), near)
        origin_self = Point(0, 0)
        self.assertIs(nearest((0, 0), [origin_self], within=0), origin_self)
        with self.assertRaises(ValueError):
            nearest((0, 0), [near], within=-1)

    def test_where(self):
        a = Point(1, 0)
        b = Point(10, 0)
        self.assertIs(nearest((0, 0), [a, b], where=lambda p: p is b), b)
        with self.assertRaises(TypeError):
            nearest((0, 0), [a], where="nope")

    def test_invalid_origin_and_items(self):
        with self.assertRaises(TypeError):
            nearest("nope", [(0, 0)])
        with self.assertRaises(TypeError):
            nearest((0, 0), 42)

    def test_polygon_vertices(self):
        poly = Polygon(points=[(0, 0), (100, 0), (50, 80)])
        hit = nearest((90, 5), poly.points)
        self.assertIs(hit, poly.points[1])

    def test_matches_group_nearest(self):
        from scena import group, init
        init(width=200, height=200)
        gid = "nearest_match"
        a = Circle(center=(0, 0), radius=1, group=gid)
        b = Circle(center=(10, 0), radius=1, group=gid)
        g = group[gid]
        origin = (1, 0)
        self.assertIs(nearest(origin, g), g.nearest(origin))
        self.assertIs(nearest(origin, g), a)
        self.assertIs(g.nearest(origin, within=2), a)
        self.assertIsNone(g.nearest(origin, within=0.5))
        a.destroy()
        b.destroy()


# ---------------------------------------------------------------------------
# move_by families (cartesian / Vec2 / polar)
# ---------------------------------------------------------------------------
class TestMoveByFamilies(ShapeTestCase):
    def test_polar_90_is_plus_y(self):
        p = Point(0, 0)
        p.move_by(angle=90, distance=40)
        self.assertPointAlmost(p, 0, 40)

    def test_polar_0_is_plus_x(self):
        p = Point(1, 1)
        p.move_by(angle=0, distance=10)
        self.assertPointAlmost(p, 11, 1)

    def test_vec2_still_works(self):
        p = Point(0, 0)
        p.move_by(Vec2(3, 4))
        self.assertPointAlmost(p, 3, 4)

    def test_point_raises(self):
        p = Point(0, 0)
        other = Point(5, 5)
        with self.assertRaises(TypeError) as ctx:
            p.move_by(other)
        msg = str(ctx.exception)
        self.assertIn("Point", msg)
        self.assertIn("move_to", msg)
        p.move_to(other)
        self.assertPointAlmost(p, 5, 5)

    def test_mix_cartesian_and_polar_raises(self):
        p = Point(0, 0)
        with self.assertRaises(TypeError) as ctx:
            p.move_by(10, 0, angle=90, distance=40)
        self.assertIn("family", str(ctx.exception).lower())
        with self.assertRaises(TypeError):
            p.move_by(Vec2(1, 0), angle=90, distance=10)

    def test_half_polar_raises(self):
        p = Point(0, 0)
        with self.assertRaises(TypeError) as ctx:
            p.move_by(angle=90)
        self.assertIn("angle=", str(ctx.exception))
        self.assertIn("distance=", str(ctx.exception))
        with self.assertRaises(TypeError):
            p.move_by(distance=40)

    def test_polar_on_circle(self):
        c = Circle(center=(0, 0), radius=8)
        c.move_by(angle=180, distance=20)
        self.assertPointAlmost(c.center, -20, 0)

    def test_polar_force_unlinks(self):
        src = Point(1, 1)
        dst = Point(0, 0)
        dst @= src
        with self.assertRaises(LinkedAttributeError):
            dst.move_by(angle=0, distance=1)
        dst.move_by(angle=0, distance=1, force=True)
        self.assertPointAlmost(dst, 2, 1)


# ---------------------------------------------------------------------------
# Point visible / handle + handles / show_points
# ---------------------------------------------------------------------------
class TestPointVisibleHandle(ShapeTestCase):
    def test_default_undrawn_and_not_visible(self):
        p = Point(3, 4)
        self.assertIsNone(p.layer)
        self.assertFalse(p.visible)
        self.assertFalse(p.handle)
        self.assertFalse(p.draggable)

    def test_visible_promotes_none_to_top_and_restores(self):
        p = Point(1, 2)
        self.assertIsNone(p.layer)
        p.visible = True
        self.assertTrue(p.visible)
        self.assertEqual(p.layer, 'top')
        p.visible = False
        self.assertFalse(p.visible)
        self.assertIsNone(p.layer)

    def test_visible_restores_non_none_original_layer(self):
        p = Point(0, 0)
        p.layer = 'default'  # still invisible; on draw list but skipped
        self.assertFalse(p.visible)
        self.assertEqual(p.layer, 'default')
        p.visible = True
        self.assertEqual(p.layer, 'default')  # already had a layer — no promote
        p.visible = False
        self.assertEqual(p.layer, 'default')  # restored saved layer

    def test_visible_restore_after_promote_ignores_manual_layer_change(self):
        # Saved layer is the one before first show (None), not mid-show edits.
        p = Point(0, 0)
        p.visible = True
        self.assertEqual(p.layer, 'top')
        p.layer = 'default'
        p.visible = False
        self.assertIsNone(p.layer)

    def test_handle_implies_visible_and_draggable(self):
        p = Point(0, 0)
        p.handle = True
        self.assertTrue(p.handle)
        self.assertTrue(p.visible)
        self.assertTrue(p.draggable)
        self.assertEqual(p.layer, 'top')
        p.handle = False
        self.assertFalse(p.handle)
        self.assertFalse(p.draggable)
        self.assertTrue(p.visible)  # marker can remain

    def test_inbound_link_on_handle_point_raises(self):
        """Defined behavior: inbound link on a handle Point → LinkedAttributeError.
        Outbound links *to* the handle remain fine (tested via Anchor / Line).
        """
        p = Point(0, 0)
        p.handle = True
        src = Point(5, 5)
        with self.assertRaises(LinkedAttributeError):
            p @= src
        with self.assertRaises(LinkedAttributeError):
            p["x"] @= lambda: src.x

    def test_outbound_link_to_handle_point_ok(self):
        h = Point(10, 20)
        h.handle = True
        line = Line(p1=lambda: h, p2=(30, 40))
        self.assertIsNotNone(line.p1._link)
        h.move_by(1, 0)
        self.assertPointAlmost(line.p1, 11, 20)

    def test_handle_true_on_linked_point_raises(self):
        src = Point(1, 1)
        p = Point(0, 0)
        p @= src
        with self.assertRaises(LinkedAttributeError):
            p.handle = True

    def test_explicit_layer_construction_is_visible(self):
        p = Point(1, 1, layer='default')
        self.assertTrue(p.visible)
        self.assertEqual(p.layer, 'default')

    def test_guide_vs_handle_auto_colors(self):
        from scena.color import Color
        p = Point(0, 0)
        p.visible = True
        self.assertTrue(p._marker_style_auto)
        self.assertEqual(Color(p.fill).rgb[:3], Color(Point.GUIDE_COLOR).rgb[:3])
        p.handle = True
        self.assertEqual(Color(p.fill).rgb[:3], Color(Point.HANDLE_COLOR).rgb[:3])
        p.handle = False
        self.assertTrue(p.visible)
        self.assertEqual(Color(p.fill).rgb[:3], Color(Point.GUIDE_COLOR).rgb[:3])

    def test_set_color_opts_out_of_auto_marker_style(self):
        from scena.color import Color
        p = Point(0, 0)
        p.handle = True
        p.set_color("lime")
        self.assertFalse(p._marker_style_auto)
        self.assertEqual(Color(p.fill).rgb[:3], Color("lime").rgb[:3])
        p.handle = False
        p.visible = True
        # Still lime — role change must not stomp author color.
        self.assertEqual(Color(p.fill).rgb[:3], Color("lime").rgb[:3])

    def test_set_color_keeps_marker_fill_only(self):
        """Area set_color would add a contrast stroke; markers must stay fill-only."""
        p = Point(0, 0)
        p.handle = True
        p.set_color("cyan")
        self.assertFalse(p._marker_style_auto)
        self.assertFalse(p.line)
        self.assertIsNone(p._to_skia_line_paint())

    def test_color_kwarg_shows_guide_not_handle(self):
        from scena.color import Color
        p = Point(3, 4, color="cyan")
        self.assertTrue(p.visible)
        self.assertEqual(p.layer, "top")
        self.assertFalse(p.handle)
        self.assertFalse(p.draggable)
        self.assertFalse(p._marker_style_auto)
        self.assertEqual(Color(p.fill).rgb[:3], Color("cyan").rgb[:3])
        self.assertFalse(p.line)

    def test_color_kwarg_respects_visible_false(self):
        from scena.color import Color
        p = Point(1, 2, color="lime", visible=False)
        self.assertFalse(p.visible)
        self.assertIsNone(p.layer)
        self.assertFalse(p._marker_style_auto)
        self.assertEqual(Color(p.fill).rgb[:3], Color("lime").rgb[:3])

    def test_anchor_color_forwards_and_stays_handle(self):
        from scena.color import Color
        a = Anchor(10, 20, color="cyan")
        self.assertTrue(a.handle)
        self.assertTrue(a.visible)
        self.assertFalse(a._marker_style_auto)
        self.assertEqual(Color(a.fill).rgb[:3], Color("cyan").rgb[:3])
        # Default Anchor keeps role auto (red handle).
        red = Anchor(0, 0)
        self.assertTrue(red._marker_style_auto)
        self.assertEqual(Color(red.fill).rgb[:3], Color(Point.HANDLE_COLOR).rgb[:3])

    def test_handles_and_points_use_role_colors(self):
        from scena.color import Color
        line = Line(p1=(0, 0), p2=(10, 0))
        line.show_handles()
        self.assertEqual(Color(line.p1.fill).rgb[:3], Color(Point.HANDLE_COLOR).rgb[:3])
        r = Rect(center=(0, 0), width=20, height=10)
        r.show_points()
        self.assertEqual(Color(r.top_left.fill).rgb[:3], Color(Point.GUIDE_COLOR).rgb[:3])
        self.assertFalse(r.top_left.handle)

    def test_marker_radius_guide_vs_handle(self):
        p = Point(0, 0)
        p.visible = True
        self.assertEqual(p._marker_radius(), Point.GUIDE_RADIUS)
        p.handle = True
        self.assertEqual(p._marker_radius(), Point.HANDLE_RADIUS)

    def _draw_circle_radii(self, point):
        from unittest.mock import Mock
        canvas = Mock()
        point._geometry_draw(canvas)
        return [call.args[2] for call in canvas.drawCircle.call_args_list]

    def test_hover_ring_draws_for_colored_anchor(self):
        from scena.shapes import Anchor
        a = Anchor(5, 6, color="lime")
        self.assertFalse(a.line)
        self.assertIsNone(a._to_skia_line_paint())
        a._pointer_hover = True
        self.assertIn(Anchor.HANDLE_RADIUS + 2.5, self._draw_circle_radii(a))

        red = Anchor(0, 0)
        self.assertFalse(red.line)
        red._pointer_hover = True
        self.assertIn(Anchor.HANDLE_RADIUS + 2.5, self._draw_circle_radii(red))

    def test_hover_ring_independent_of_stroke(self):
        """Author/contrast stroke at r must not suppress the outer hover ring."""
        p = Point(10, 20)
        p.handle = True
        p.line = "white"
        p._pointer_hover = True
        radii = self._draw_circle_radii(p)
        self.assertIn(Point.HANDLE_RADIUS, radii)
        self.assertIn(Point.HANDLE_RADIUS + 2.5, radii)


class TestHandles(ShapeTestCase):
    def test_line_handles(self):
        line = Line(p1=(0, 0), p2=(10, 0))
        line.show_handles()
        self.assertTrue(line.p1.handle)
        self.assertTrue(line.p2.handle)
        self.assertTrue(line.p1.draggable)
        self.assertEqual(line.p1.layer, 'top')
        self.assertFalse(line.draggable)  # whole-shape drag unchanged

    def test_handles_skips_linked_defining_points_no_raise(self):
        """Bulk handles() skips linked Points (does not raise)."""
        src = Point(5, 5)
        line = Line(p1=lambda: src, p2=(10, 0))
        line.show_handles()  # must not raise
        self.assertFalse(line.p1.visible)  # linked — skipped
        self.assertFalse(line.p1.handle)
        self.assertTrue(line.p2.handle)

    def test_handles_ignores_derivate_points(self):
        r = Rect(center=(0, 0), width=20, height=10)
        # Force materialize a Derivate corner without handles() including it.
        _ = r.top_left
        r.show_handles()
        self.assertTrue(r.center.handle)
        self.assertFalse(r.top_left.visible)
        self.assertFalse(r.top_left.handle)

    def test_no_handles(self):
        line = Line(p1=(0, 0), p2=(10, 0))
        line.show_handles()
        line.no_handles()
        self.assertFalse(line.p1.visible)
        self.assertFalse(line.p1.handle)
        self.assertIsNone(line.p1.layer)

    def test_circle_handles_center(self):
        c = Circle(center=(1, 2), radius=5)
        c.show_handles()
        self.assertTrue(c.center.handle)
        self.assertFalse(c.draggable)  # whole-shape drag unchanged

    def test_polygon_handles_vertices(self):
        poly = Polygon(points=[(0, 0), (10, 0), (5, 8)])
        poly.show_handles()
        for v in poly.points:
            self.assertTrue(v.handle)


class TestShowPoints(ShapeTestCase):
    def test_show_points_includes_derivate_corners(self):
        r = Rect(center=(0, 0), width=40, height=20)
        self.assertIsNone(r.__dict__.get('top_left'))  # cold
        r.show_points()
        self.assertTrue(r.center.visible)
        self.assertTrue(r.top_left.visible)
        self.assertFalse(r.top_left.handle)
        self.assertTrue(r.top_left._is_derivate_live())

    def test_cold_derivates_stay_cold_until_show_points(self):
        r = Rect(center=(0, 0), width=40, height=20)
        self.assertIsNone(r.__dict__.get('top_right'))
        r.show_handles()  # Defining only
        self.assertIsNone(r.__dict__.get('top_right'))
        self.assertTrue(r.center.handle)

    def test_no_points_releases_debug_derivate_liveness(self):
        r = Rect(center=(0, 0), width=40, height=20)
        r.show_points()
        self.assertTrue(r.top_left._is_derivate_live())
        r.no_points()
        self.assertFalse(r.top_left.visible)
        self.assertFalse(r.top_left._derivate_live)

    def test_reshow_points_keeps_derivates_tracking_handles(self):
        """no_points then show_points must revive named Derivate markers.

        Without re-setting ``_derivate_live``, Rect/Square corners and
        VERTEX_SIDE centers stay visible but freeze when a handle moves.
        """
        from scena.shapes import get_xy

        r = Rect(center=(0, 0), width=40, height=20)
        r.show_handles()
        r.show_points()
        r.no_points()
        r.show_points()
        self.assertTrue(r.top_left.visible)
        self.assertTrue(r.top_left._is_derivate_live())
        r.center.move_to(100, 50)
        self.assertPointAlmost(r.top_left, 80, 60)

        sq = Square(center=(0, 0), length=30)
        sq.show_handles()
        sq.show_points()
        sq.no_points()
        sq.show_points()
        self.assertTrue(sq.top_left._is_derivate_live())
        sq.center.move_to(40, 40)
        self.assertPointAlmost(sq.top_left, 25, 55)

        tri = EquilateralTriangle(vertex=(0, 0), side=60, angle=0)
        tri.show_handles()
        tri.show_points()
        tri.no_points()
        tri.show_points()
        self.assertTrue(tri.center.visible)
        self.assertTrue(tri.center._is_derivate_live())
        cx0, cy0 = get_xy(tri.center, bare=True)
        tri.vertex.move_to(30, 20)
        cx1, cy1 = get_xy(tri.center, bare=True)
        self.assertAlmostEqual(cx1 - cx0, 30, places=5)
        self.assertAlmostEqual(cy1 - cy0, 20, places=5)

    def test_no_points_keeps_liveness_if_externally_linked(self):
        r = Rect(center=(0, 0), width=40, height=20)
        sink = Point(0, 0)
        sink @= r.top_left  # materializes + external dependent
        r.show_points()
        r.no_points()
        self.assertTrue(r.top_left._is_derivate_live())

    def test_no_points_preserves_handles(self):
        line = Line(p1=(0, 0), p2=(10, 0))
        line.show_handles()
        line.show_points()
        line.no_points()
        self.assertTrue(line.p1.handle)
        self.assertTrue(line.p1.visible)

    def test_regular_polygon_show_points_materializes_vertices(self):
        reg = RegularPolygon(n=4, center=(0, 0), radius=10, angle=0)
        self.assertFalse(reg._vertices[0]._is_derivate_live())
        reg.show_points()
        self.assertTrue(reg._vertices[0]._is_derivate_live())
        self.assertTrue(reg._vertices[0].visible)
        reg.no_points()
        self.assertFalse(reg._vertices[0]._derivate_live)

    def test_equilateral_center_not_duplicated_with_centroid(self):
        """center (handle) and centroid must not both paint at the same locus."""
        from scena.canvas import ScenaCanvas
        from scena.shapes import get_xy
        tri = EquilateralTriangle(center=(50, 60), radius=20)
        tri.show_handles()
        tri.show_points()
        top = ScenaCanvas.get_current().registry.layers['top']._objects
        at_center = [
            o for o in top
            if isinstance(o, Point) and o.visible
            and abs(get_xy(o, bare=True)[0] - 50) < 1e-6
            and abs(get_xy(o, bare=True)[1] - 60) < 1e-6
        ]
        self.assertEqual(len(at_center), 1)
        self.assertTrue(at_center[0].handle)
        self.assertIs(at_center[0], tri.center)
        # Inactive alternate-model slot must not appear at the origin.
        self.assertFalse(tri.__dict__.get('vertex') and tri.vertex.visible)

    def test_show_points_skips_coincident_guides(self):
        from scena.shapes import get_xy
        r = Rect(center=(300, 400), width=40, height=20)
        r.show_points()
        keys = set()
        for p in r._iter_debug_points(materialize=False):
            if not p.visible:
                continue
            x, y = get_xy(p, bare=True)
            key = (round(x, 4), round(y, 4))
            self.assertNotIn(key, keys)
            keys.add(key)
        self.assertGreaterEqual(len(keys), 5)


# ---------------------------------------------------------------------------
# Line
# ---------------------------------------------------------------------------
class TestLinePointPoint(ShapeTestCase):
    def test_derived_attributes(self):
        line = Line(p1=(0, 0), p2=(3, 4))
        self.assertEqual(line.model, LineModel.POINT_POINT)
        self.assertNumAlmost(line.length, 5.0)
        self.assertAlmostEqual(_norm_angle(line.angle), _norm_angle(math.degrees(math.atan2(4, 3))))
        self.assertPointAlmost(line.center, 1.5, 2.0)
        self.assertNumAlmost(line.dx, 3.0)
        self.assertNumAlmost(line.dy, 4.0)

    def test_scalar_endpoints_are_not_a_line_spelling(self):
        """Line takes points; x1=/y1=/x2=/y2= orient toward p1= / p2=."""
        with self.assertRaises(TypeError) as ctx:
            Line(x1=0, y1=0, x2=10, y2=0)
        self.assertIn("p1=(x1, y1), p2=(x2, y2)", str(ctx.exception))
        self.assertEqual(str(ctx.exception).count("Line takes points"), 1)
        line = Line(p1=(0, 0), p2=(10, 0))
        self.assertEqual(line.model, LineModel.POINT_POINT)
        self.assertNumAlmost(line.length, 10.0)
        self.assertNumAlmost(line.angle, 0.0)

    def test_default_constructor_is_visible_centered(self):
        from scena.shapes import _default_pose
        (cx, cy), unit = _default_pose()
        line = Line()
        self.assertEqual(line.model, LineModel.CENTER_LENGTH_ANGLE)
        self.assertNumAlmost(line.length, 2.0 * unit)
        self.assertNumAlmost(line.angle, 0.0)
        self.assertPointAlmost(line.center, cx, cy)
        self.assertPointAlmost(line.p1, cx - unit, cy)
        self.assertPointAlmost(line.p2, cx + unit, cy)

    def test_move_by_translates_both_endpoints(self):
        line = Line(p1=(0, 0), p2=(3, 4))
        line.move_by(10, -10)
        self.assertPointAlmost(line.p1, 10, -10)
        self.assertPointAlmost(line.p2, 13, -6)
        self.assertNumAlmost(line.length, 5.0)

    def test_move_to_moves_center(self):
        line = Line(p1=(0, 0), p2=(10, 0))
        line.move_to(100, 100)
        self.assertPointAlmost(line.center, 100, 100)
        self.assertPointAlmost(line.p1, 95, 100)
        self.assertPointAlmost(line.p2, 105, 100)

    def test_move_to_point_like_and_move_by_rejects_location(self):
        line = Line(p1=(0, 0), p2=(10, 0))
        mouseish = type("M", (), {"x": 100.0, "y": 40.0})()
        line.move_to(mouseish)
        self.assertPointAlmost(line.center, 100, 40)
        ball = Circle(center=(0, 0), radius=2)
        ball.move_to((30, 10))
        self.assertPointAlmost(ball.center, 30, 10)
        ball.move_to(50)  # number: x only
        self.assertPointAlmost(ball.center, 50, 10)
        with self.assertRaises(TypeError):
            ball.move_by(mouseish)
        with self.assertRaises(TypeError):
            ball.move_by(Point(1, 1))

    def test_rotate_by_about_mouse_like(self):
        p = Point(1, 0)
        mouseish = type("M", (), {"x": 0.0, "y": 0.0})()
        p.rotate_by(90, about=mouseish)
        self.assertPointAlmost(p, 0, 1)

    def test_rotate_by_about_center(self):
        line = Line(p1=(0, 0), p2=(10, 0))
        line.rotate_by(90)  # default pivot: center = (5, 0)
        self.assertPointAlmost(line.p1, 5, -5)
        self.assertPointAlmost(line.p2, 5, 5)
        self.assertNumAlmost(line.length, 10.0)

    def test_rotate_to_sets_absolute_angle(self):
        line = Line(p1=(0, 0), p2=(10, 0))
        line.rotate_to(90)
        self.assertAlmostEqual(_norm_angle(line.angle), _norm_angle(90))

    def test_reset_rotation_returns_to_rest_heading(self):
        circle = Circle(center=(0, 0), radius=10)
        rect = Rect(center=(0, 0), width=20, height=10)
        self.assertAlmostEqual(circle.rest_heading, 0.0)
        self.assertAlmostEqual(rect.rest_heading, 0.0)
        circle.rotate_by(40.0)
        rect.rotate_by(40.0)
        circle.reset_rotation()
        rect.reset_rotation()
        self.assertAlmostEqual(circle.angle, 0.0)
        self.assertAlmostEqual(rect.angle, 0.0)

    def test_scale_by_about_p1(self):
        line = Line(p1=(0, 0), p2=(10, 0))
        line.scale_by(2, about=line.p1)
        self.assertPointAlmost(line.p1, 0, 0)
        self.assertPointAlmost(line.p2, 20, 0)
        self.assertNumAlmost(line.length, 20.0)

    def test_scale_by_negative_factor_raises(self):
        line = Line(p1=(0, 0), p2=(10, 0))
        with self.assertRaises(ValueError):
            line.scale_by(-1, about=(0, 0))

    def test_zero_length_line_angle_is_zero(self):
        line = Line(p1=(5, 5), p2=(5, 5))
        self.assertNumAlmost(line.length, 0.0)
        self.assertNumAlmost(line.angle, 0.0)
        self.assertTrue(line.is_collapsed)

    def test_positive_line_is_not_collapsed(self):
        line = Line(p1=(0, 0), p2=(10, 0))
        self.assertFalse(line.is_collapsed)

    def test_linked_endpoint_tracks_source(self):
        anchor = Point(0, 0)
        line = Line(p1=lambda: anchor, p2=(10, 0))
        anchor.move_by(5, 5)
        self.assertPointAlmost(line.p1, 5, 5)
        self.assertPointAlmost(line.p2, 10, 0)
        self.assertNumAlmost(line.length, math.hypot(5, -5))

    def test_bare_endpoint_copies_does_not_track(self):
        anchor = Point(0, 0)
        line = Line(p1=anchor, p2=(10, 0))
        self.assertIsNone(line.p1._link)
        anchor.move_by(5, 5)
        self.assertPointAlmost(line.p1, 0, 0)

    def test_takein_copies_values_not_links(self):
        a = Line(p1=(0, 0), p2=(1, 1))
        b = Line(p1=(10, 10), p2=(20, 20))
        a._takein(b)
        self.assertPointAlmost(a.p1, 10, 10)
        self.assertPointAlmost(a.p2, 20, 20)


class TestLinePointVec(ShapeTestCase):
    def test_derived_attributes(self):
        line = Line(p1=(1, 1), vec=Vec2(4, 3))
        self.assertEqual(line.model, LineModel.POINT_VEC)
        self.assertPointAlmost(line.p2, 5, 4)
        self.assertNumAlmost(line.length, 5.0)
        self.assertPointAlmost(line.center, 3, 2.5)

    def test_live_vec_link_propagates(self):
        v = Vec2(10, 0)
        line = Line(p1=(0, 0), vec=lambda: v)
        self.assertPointAlmost(line.p2, 10, 0)
        v.x = 20
        self.assertPointAlmost(line.p2, 20, 0)
        self.assertNumAlmost(line.length, 20.0)

    def test_scale_by_requires_force_when_vec_is_linked(self):
        v = Vec2(10, 0)
        line = Line(p1=(0, 0), vec=lambda: v)
        with self.assertRaises(LinkedAttributeError):
            line.scale_by(2)
        line.scale_by(2, force=True)
        self.assertNumAlmost(line.length, 20.0)

    def test_rotate_by_rotates_vec(self):
        # Bare Vec2 / tuple both copy — no force needed.
        line = Line(p1=(0, 0), vec=Vec2(10, 0))
        line.rotate_by(90, about=line.p1)
        self.assertPointAlmost(line.p2, 0, 10, places=5)

    def test_rotate_by_rotates_linked_vec_needs_force(self):
        v = Vec2(10, 0)
        line = Line(p1=(0, 0), vec=lambda: v)
        with self.assertRaises(LinkedAttributeError):
            line.rotate_by(90, about=line.p1)
        line.rotate_by(90, about=line.p1, force=True)
        self.assertPointAlmost(line.p2, 0, 10, places=5)

    def test_rotate_by_rotates_vec_when_unlinked(self):
        # A plain tuple never links -- no force needed.
        line = Line(p1=(0, 0), vec=(10, 0))
        line.rotate_by(90, about=line.p1)
        self.assertPointAlmost(line.p2, 0, 10, places=5)


class TestLinePointDxDy(ShapeTestCase):
    def test_derived_attributes(self):
        line = Line(p1=(0, 0), dx=3, dy=4)
        self.assertEqual(line.model, LineModel.POINT_DX_DY)
        self.assertPointAlmost(line.p2, 3, 4)
        self.assertNumAlmost(line.length, 5.0)

    def test_move_by_translates_p1_only(self):
        line = Line(p1=(0, 0), dx=3, dy=4)
        line.move_by(1, 1)
        self.assertPointAlmost(line.p1, 1, 1)
        self.assertPointAlmost(line.p2, 4, 5)

    def test_rotate_by_rotates_dx_dy(self):
        line = Line(p1=(0, 0), dx=10, dy=0)
        line.rotate_by(90, about=line.p1)
        self.assertNumAlmost(line.dx, 0.0, places=5)
        self.assertNumAlmost(line.dy, 10.0, places=5)


class TestLinePointAngleLength(ShapeTestCase):
    def test_derived_attributes(self):
        line = Line(p1=(0, 0), angle=0.0, length=10.0)
        self.assertEqual(line.model, LineModel.POINT_ANGLE_LENGTH)
        self.assertPointAlmost(line.p2, 10, 0)

    def test_angle_pi_over_2(self):
        line = Line(p1=(0, 0), angle=90, length=4.0)
        self.assertPointAlmost(line.p2, 0, 4, places=5)

    def test_move_by_keeps_angle_length(self):
        line = Line(p1=(0, 0), angle=math.degrees(0.3), length=7.0)
        line.move_by(5, -5)
        self.assertNumAlmost(line.angle, math.degrees(0.3))
        self.assertNumAlmost(line.length, 7.0)

    def test_scale_by_scales_length_only(self):
        line = Line(p1=(0, 0), angle=0.0, length=10.0)
        line.scale_by(0.5, about=line.p1)
        self.assertNumAlmost(line.length, 5.0)
        self.assertPointAlmost(line.p1, 0, 0)

    def test_home_fill_center_only(self):
        from scena.shapes import _default_pose
        (_, _), unit = _default_pose()
        line = Line(center=(10, 20))
        self.assertEqual(line.model, LineModel.CENTER_LENGTH_ANGLE)
        self.assertPointAlmost(line.center, 10, 20)
        self.assertNumAlmost(line.angle, 0.0)
        self.assertNumAlmost(line.length, 2.0 * unit)
        self.assertPointAlmost(line.p1, 10 - unit, 20)
        self.assertPointAlmost(line.p2, 10 + unit, 20)

    def test_home_fill_length_angle(self):
        from scena.shapes import _default_pose
        (cx, cy), _ = _default_pose()
        line = Line(length=40, angle=90)
        self.assertEqual(line.model, LineModel.CENTER_LENGTH_ANGLE)
        self.assertPointAlmost(line.center, cx, cy)
        self.assertNumAlmost(line.length, 40.0)
        self.assertNumAlmost(line.angle, 90.0)
        self.assertPointAlmost(line.p1, cx, cy - 20)
        self.assertPointAlmost(line.p2, cx, cy + 20)

    def test_p1_only_is_incomplete(self):
        with self.assertRaises(ValueError) as ctx:
            Line(p1=(0, 0))
        self.assertIn("p1", str(ctx.exception))

    def test_incomplete_home_pair_raises(self):
        with self.assertRaises(ValueError):
            Line(center=(0, 0), length=10)
        with self.assertRaises(ValueError):
            Line(center=(0, 0), angle=45)
        with self.assertRaises(ValueError):
            Line(length=10)
        with self.assertRaises(ValueError):
            Line(angle=45)

    def test_p1_is_derivate_on_home_model(self):
        from scena.state import DerivedAttributeError
        line = Line(center=(0, 0), length=10, angle=0)
        with self.assertRaises(DerivedAttributeError):
            line.p1 = (1, 1)

    def test_center_link_tracks(self):
        r = Rect(center=(5, 5), width=10, height=10)
        line = Line(center=lambda: r.center, length=20, angle=0)
        self.assertPointAlmost(line.center, 5, 5)
        r.move_by(10, 0)
        self.assertPointAlmost(line.center, 15, 5)

    def test_width_kwarg_is_not_length(self):
        with self.assertRaises(TypeError) as ctx:
            Line(center=(0, 0), width=10, angle=0)
        msg = str(ctx.exception)
        self.assertIn("width", msg)
        self.assertIn("length", msg)

    def test_incomplete_expert_path_raises(self):
        with self.assertRaises(ValueError) as ctx:
            Line(p2=(10, 0))
        self.assertIn("p2", str(ctx.exception))
        with self.assertRaises(ValueError):
            Line(p1=(0, 0), dx=10)


class TestLineParallelPoint(ShapeTestCase):
    def test_tracks_reference_angle(self):
        ref = Line(p1=(0, 0), p2=(10, 0))
        line = Line(p1=(0, 5), parallel_to=ref, length=10)
        self.assertEqual(line.model, LineModel.PARALLEL_POINT)
        self.assertNumAlmost(line.angle, 0.0)
        self.assertPointAlmost(line.p2, 10, 5, places=5)

    def test_reactive_when_reference_rotates(self):
        ref = Line(p1=(0, 0), p2=(10, 0))
        line = Line(p1=(0, 5), parallel_to=ref, length=10)
        ref.rotate_by(90)
        self.assertAlmostEqual(_norm_angle(line.angle), _norm_angle(ref.angle), places=5)

    def test_move_by_moves_p1_freely(self):
        ref = Line(p1=(0, 0), p2=(10, 0))
        line = Line(p1=(0, 5), parallel_to=ref, length=10)
        line.move_by(1, 1)
        self.assertPointAlmost(line.p1, 1, 6)


class TestLinePerpendicularPoint(ShapeTestCase):
    def test_angle_is_perpendicular(self):
        ref = Line(p1=(0, 0), p2=(10, 0))
        line = Line(p1=(0, 0), perpendicular_to=ref, length=5)
        self.assertEqual(line.model, LineModel.PERPENDICULAR_POINT)
        self.assertAlmostEqual(_norm_angle(line.angle), _norm_angle(90), places=5)
        self.assertPointAlmost(line.p2, 0, 5, places=5)


class TestLineParallelDist(ShapeTestCase):
    def test_offset_point_and_length_track_reference(self):
        ref = Line(p1=(0, 0), p2=(10, 0))
        line = Line(dist=5, parallel_to=ref)
        self.assertEqual(line.model, LineModel.PARALLEL_DIST)
        self.assertNumAlmost(line.length, 10.0)
        self.assertPointAlmost(line.p1, 0, 5, places=5)
        self.assertPointAlmost(line.p2, 10, 5, places=5)

    def test_negative_dist_flips_side(self):
        ref = Line(p1=(0, 0), p2=(10, 0))
        line = Line(dist=-5, parallel_to=ref)
        self.assertPointAlmost(line.p1, 0, -5, places=5)

    def test_reactive_when_reference_moves(self):
        ref = Line(p1=(0, 0), p2=(10, 0))
        line = Line(dist=5, parallel_to=ref)
        ref.move_by(100, 0)
        self.assertPointAlmost(line.p1, 100, 5, places=5)

    def test_move_by_adjusts_dist(self):
        ref = Line(p1=(0, 0), p2=(10, 0))
        line = Line(dist=5, parallel_to=ref)
        line.move_by(0, 5)
        self.assertNumAlmost(line.dist, 10.0)
        self.assertPointAlmost(line.p1, 0, 10, places=5)
        # Along the reference: left-normal is (0, 1), so dx adds nothing.
        line.move_by(10, 0)
        self.assertNumAlmost(line.dist, 10.0)
        self.assertPointAlmost(line.p1, 0, 10, places=5)
        # p1 stays linked to the reference.
        ref.move_by(0, 1)
        self.assertPointAlmost(line.p1, 0, 11, places=5)

    def test_move_by_zero_length_reference_is_noop(self):
        ref = Line(p1=(0, 0), p2=(0, 0))
        line = Line(dist=5, parallel_to=ref)
        line.move_by(0, 5)
        self.assertNumAlmost(line.dist, 5.0)

    def test_scale_by_scales_dist_and_length(self):
        ref = Line(p1=(0, 0), p2=(10, 0))
        line = Line(dist=5, parallel_to=ref)
        line.scale_by(2, about=(0, 0), force=True)
        self.assertNumAlmost(line.dist, 10.0)
        self.assertNumAlmost(line.length, 20.0)


class TestLineTangentAngle(ShapeTestCase):
    def test_p1_on_circle_and_tangent_direction(self):
        circle = Circle(center=(0, 0), radius=10)
        line = Line(circle=circle, at_angle=0.0, length=5)
        self.assertEqual(line.model, LineModel.TANGENT_ANGLE)
        self.assertPointAlmost(line.p1, 10, 0, places=5)
        self.assertPointAlmost(line.p2, 10, 5, places=5)  # tangent dir = angle + pi/2

    def test_reactive_when_circle_moves(self):
        circle = Circle(center=(0, 0), radius=10)
        line = Line(circle=circle, at_angle=0.0, length=5)
        circle.move_by(100, 0)
        self.assertPointAlmost(line.p1, 110, 0, places=5)

    def test_rotate_by_moves_around_circle(self):
        circle = Circle(center=(0, 0), radius=10)
        line = Line(circle=circle, at_angle=0.0, length=5)
        line.rotate_by(90)
        self.assertPointAlmost(line.p1, 0, 10, places=5)

    def test_scale_by_only_scales_length(self):
        circle = Circle(center=(0, 0), radius=10)
        line = Line(circle=circle, at_angle=0.0, length=5)
        line.scale_by(2)
        self.assertNumAlmost(line.length, 10.0)
        self.assertPointAlmost(line.p1, 10, 0, places=5)  # p1 pinned to circle

    def test_move_by_requires_force(self):
        circle = Circle(center=(0, 0), radius=10)
        line = Line(circle=circle, at_angle=0.0, length=5)
        with self.assertRaises(LinkedAttributeError):
            line.move_by(1, 1)
        line.move_by(1, 1, force=True)


class TestLineTangentPoint(ShapeTestCase):
    def test_touch_point_left_and_right(self):
        circle = Circle(center=(0, 0), radius=5)
        left = Line(circle=circle, from_point=(10, 0), side='left')
        right = Line(circle=circle, from_point=(10, 0), side='right')
        self.assertEqual(left.model, LineModel.TANGENT_POINT)

        offset = math.acos(5 / 10)
        ex = 5 * math.cos(offset)
        ey_left = 5 * math.sin(offset)
        self.assertPointAlmost(left.p2, ex, ey_left, places=5)
        self.assertPointAlmost(right.p2, ex, -ey_left, places=5)

    def test_degenerates_when_point_inside_circle(self):
        circle = Circle(center=(0, 0), radius=10)
        line = Line(circle=circle, from_point=(3, 0), side='left')
        self.assertPointAlmost(line.p2, 3, 0, places=5)

    def test_invalid_side_raises(self):
        circle = Circle(center=(0, 0), radius=5)
        with self.assertRaises(ValueError):
            Line(circle=circle, from_point=(10, 0), side='up')

    def test_reactive_when_from_point_moves(self):
        circle = Circle(center=(0, 0), radius=5)
        anchor = Point(10, 0)
        line = Line(circle=circle, from_point=lambda: anchor, side='left')
        anchor.move_to(20, 0)
        offset = math.acos(5 / 20)
        expected_x = 5 * math.cos(offset)
        expected_y = 5 * math.sin(offset)
        self.assertPointAlmost(line.p2, expected_x, expected_y, places=5)

    def test_negative_radius_raises(self):
        with self.assertRaises(ValueError):
            Circle(center=(0, 0), radius=-5)


def _norm_angle(a):
    """Normalize an angle to [0, 360) for wrap-safe comparisons."""
    return a % 360


# ---------------------------------------------------------------------------
# Circle
# ---------------------------------------------------------------------------
class TestCircleCenterRadius(ShapeTestCase):
    def test_basic_construction(self):
        c = Circle(center=(0, 0), radius=10)
        self.assertEqual(c.model, CircleModel.CENTER_RADIUS)
        self.assertPointAlmost(c.p1, 10, 0)
        self.assertPointAlmost(c.p2, -10, 0)
        self.assertPointAlmost(c.perimeter_point, 10, 0)

    def test_negative_radius_still_hits(self):
        c = Circle(center=(0, 0), radius=10)
        with self.assertRaises(ValueError):
            c.radius = -10
        self.assertTrue(c.contains_point(0, 0))

    def test_default_construction(self):
        from scena.shapes import _default_pose
        (cx, cy), unit = _default_pose()
        c = Circle()
        self.assertEqual(c.model, CircleModel.CENTER_RADIUS)
        self.assertPointAlmost(c.center, cx, cy)
        self.assertNumAlmost(c.radius, unit)

    def test_unknown_kwargs_raise(self):
        with self.assertRaises(TypeError) as ctx:
            Circle(aaa=1)
        self.assertIn("aaa", str(ctx.exception))
        with self.assertRaises(TypeError) as ctx:
            Circle(frame="x.png")
        self.assertIn("frame", str(ctx.exception))
        self.assertIn("Sprite", str(ctx.exception))
        # Gradual: radius alone still places.
        c = Circle(radius=50)
        self.assertNumAlmost(c.radius, 50)
        c.destroy()
        # Mix of known placement + unknown still TypeError.
        with self.assertRaises(TypeError) as ctx:
            Circle(center=(0, 0), aaa=1)
        self.assertIn("aaa", str(ctx.exception))

    def test_home_fill_center_only(self):
        from scena.shapes import _default_pose
        (_, _), unit = _default_pose()
        c = Circle(center=(10, 20))
        self.assertEqual(c.model, CircleModel.CENTER_RADIUS)
        self.assertPointAlmost(c.center, 10, 20)
        self.assertNumAlmost(c.radius, unit)

    def test_incomplete_expert_path_raises(self):
        with self.assertRaises(ValueError) as ctx:
            Circle(p1=(0, 0))
        msg = str(ctx.exception)
        self.assertIn("p1", msg)
        self.assertIn("complete", msg.lower())
        # Must not invent a home-default body.
        with self.assertRaises(ValueError):
            Circle(p1=(0, 0), angle=0)

    def test_move_by(self):
        c = Circle(center=(0, 0), radius=5)
        c.move_by(10, -10)
        self.assertPointAlmost(c.center, 10, -10)
        self.assertPointAlmost(c.p1, 15, -10)

    def test_rotate_by_about_pivot_orbits_center(self):
        c = Circle(center=(10, 0), radius=5)
        c.rotate_by(90, about=(0, 0))
        self.assertPointAlmost(c.center, 0, 10, places=5)
        self.assertNumAlmost(c.radius, 5.0)

    def test_scale_by(self):
        c = Circle(center=(0, 0), radius=5)
        c.scale_by(3)
        self.assertNumAlmost(c.radius, 15.0)

    def test_negative_radius_construction_raises(self):
        with self.assertRaises(ValueError):
            Circle(center=(0, 0), radius=-5)


class TestCircleRimPoints(ShapeTestCase):
    """p1 ≡ perimeter_point, p2 opposite, in the circle's frame (Named points)."""

    def _models(self):
        return (Circle(center=(1, 2), radius=9, angle=30),
                Circle(center=(1, 2), perimeter_point=(8, 5)),
                Circle(p1=(0, 0), p2=(10, 4)))

    def test_rim_points_turn_and_mirror_with_the_circle(self):
        for c in self._models():
            with self.subTest(model=c.model):
                cx, cy = c._center_xy()
                p1 = (float(c.p1.x), float(c.p1.y))
                self.assertPointAlmost(c.perimeter_point, *p1)
                self.assertPointAlmost(c.p2, 2 * cx - p1[0], 2 * cy - p1[1])
                c.rotate_by(90)
                self.assertPointAlmost(c.p1, cx - (p1[1] - cy), cy + (p1[0] - cx))
                c.rotate_by(-90)
                c.flip_x = True
                self.assertPointAlmost(c.p1, 2 * cx - p1[0], p1[1])

    def test_center_radius_rim_sits_on_the_heading(self):
        c = Circle(center=(0, 0), radius=10, angle=90)
        self.assertPointAlmost(c.p1, 0, 10)          # was (10, 0) whatever the heading

    def test_box_is_turned_to_the_rim_point_and_clone_keeps_it(self):
        for c in self._models():
            with self.subTest(model=c.model):
                self.assertPointAlmost(c.box.right_center, c.p1.x, c.p1.y)
                copy = c.clone()
                self.assertEqual(copy.model, c.model)
                self.assertPointAlmost(copy.p1, c.p1.x, c.p1.y)


    # G17: placed by its rim, a circle's rotation read the arc angle (0 by
    # default) while its frame (p1, .box) pointed elsewhere.

    def _heading(self, c):
        cx, cy = c._center_xy()
        return math.degrees(math.atan2(float(c.p1.y) - cy, float(c.p1.x) - cx))

    def _same_angle(self, a, b):
        d = (float(a) - float(b)) % 360.0
        self.assertLess(min(d, 360.0 - d), 1e-6, f"{a} vs {b}")

    def test_rim_placed_rotation_is_the_direction_to_p1(self):
        for c in self._models():
            with self.subTest(model=c.model):
                for step in (lambda: None, lambda: c.rotate_by(35), lambda: setattr(c, "flip_x", True),
                             lambda: setattr(c, "flip_y", True), lambda: c.scale_by(1.5)):
                    step()
                    self._same_angle(c.angle, self._heading(c))
                    self._same_angle(c.angle, c.angle)
                    self._same_angle(c.box.angle, c.angle)

    def test_moving_the_rim_point_turns_the_heading(self):
        two = Circle(p1=(0, 0), p2=(10, 0))
        self._same_angle(two.angle, 180.0)
        two.p1 = (5, -5)
        two.p2 = (5, 5)
        self._same_angle(two.angle, -90.0)
        peri = Circle(center=(0, 0), perimeter_point=(3, 3))
        self._same_angle(peri.angle, 45.0)
        peri.perimeter_point = (0, -4)
        self._same_angle(peri.angle, -90.0)

    def test_angle_at_construction_turns_the_rim_and_keeps_the_arc(self):
        # The arc opens where angle= always put it; the rim point moves onto it.
        peri = Circle(center=(0, 0), perimeter_point=(10, 0), angle=45, spread=90)
        self.assertNumAlmost(peri.angle, 45.0)
        self.assertNumAlmost(peri.radius, 10.0)
        self.assertPointAlmost(peri.perimeter_point, 10 * math.cos(math.radians(45)), 10 * math.sin(math.radians(45)))
        two = Circle(p1=(0, 0), p2=(10, 0), angle=20)
        self.assertPointAlmost(two.center, 5, 0)
        self.assertNumAlmost(two.radius, 5.0)
        self.assertPointAlmost(two.p1, 5 + 5 * math.cos(math.radians(20)), 5 * math.sin(math.radians(20)))

    def test_writing_the_heading_turns_the_rim_about_the_center(self):
        from scena import State
        for spelling in ("angle", "angle"):
            with self.subTest(spelling=spelling):
                c = Circle(p1=(0, 0), p2=(10, 0))
                setattr(c, spelling, 90)
                self.assertPointAlmost(c.center, 5, 0)
                self.assertPointAlmost(c.p1, 5, 5)
        st = State()
        st.a = 10.0
        c = Circle(center=(0, 0), perimeter_point=(5, 0))
        c["angle"] @= lambda: st.a
        self.assertNumAlmost(c.angle, 10.0)
        st.a = 90.0
        self.assertNumAlmost(c.angle, 90.0)
        self.assertPointAlmost(c.perimeter_point, 0, 5)
        self.assertPointAlmost(c.center, 0, 0)

    def test_full_turns_accumulate(self):
        c = Circle(p1=(0, 0), p2=(10, 0), angle=20)
        c.rotate_by(400)
        self.assertNumAlmost(c.angle, 420.0)
        self.assertNumAlmost(c.clone().angle, 420.0)

    def test_angle_with_a_linked_rim_point_is_refused(self):
        from scena import State
        st = State()
        st.x = 5.0
        with self.assertRaises(TypeError):
            Circle(center=(0, 0), perimeter_point=lambda: (st.x, 0), angle=30)
        c = Circle(center=(0, 0), perimeter_point=lambda: (st.x, 0))   # no angle=: fine
        self._same_angle(c.angle, 0.0)


class TestCircleCenterPerimeter(ShapeTestCase):
    def test_radius_is_distance(self):
        c = Circle(center=(0, 0), perimeter_point=(3, 4))
        self.assertEqual(c.model, CircleModel.CENTER_PERIMETER)
        self.assertNumAlmost(c.radius, 5.0)

    def test_reactive_when_perimeter_point_moves(self):
        pp = Point(10, 0)
        c = Circle(center=(0, 0), perimeter_point=lambda: pp)
        pp.move_to(0, 20)
        self.assertNumAlmost(c.radius, 20.0)

    def test_scale_by_scales_perimeter_point_distance(self):
        c = Circle(center=(0, 0), perimeter_point=(10, 0))
        c.scale_by(2)
        self.assertNumAlmost(c.radius, 20.0)
        self.assertPointAlmost(c.perimeter_point, 20, 0, places=5)


class TestCircleTwoPoints(ShapeTestCase):
    def test_center_and_radius_derived(self):
        c = Circle(p1=(0, 0), p2=(10, 0))
        self.assertEqual(c.model, CircleModel.TWO_POINTS)
        self.assertPointAlmost(c.center, 5, 0)
        self.assertNumAlmost(c.radius, 5.0)

    def test_move_by_translates_both_points(self):
        c = Circle(p1=(0, 0), p2=(10, 0))
        c.move_by(1, 1)
        self.assertPointAlmost(c.p1, 1, 1)
        self.assertPointAlmost(c.p2, 11, 1)


def _dir_deg(pt, origin=(0.0, 0.0)) -> float:
    return math.degrees(math.atan2(pt[1] - origin[1], pt[0] - origin[0]))


def _ang_dist(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


class TestCircleArc(ShapeTestCase):
    def test_default_arc_is_full_circle(self):
        c = Circle(center=(0, 0), radius=5)
        self.assertNumAlmost(c.angle, 0.0)
        self.assertNumAlmost(c.spread, 360.0)
        self.assertNumAlmost(c.angle, 0.0)
        self.assertTrue(c._use_center)
        opened = Circle(center=(0, 0), radius=5, spread=90, use_center=False)
        self.assertFalse(opened._use_center)

    def test_angle_or_spread_alone_on_every_model(self):
        headed = Circle(angle=90)
        self.assertNumAlmost(headed.angle, 90.0)
        self.assertNumAlmost(headed.spread, 360.0)
        opened = Circle(spread=90)
        self.assertNumAlmost(opened.angle, 0.0)
        self.assertNumAlmost(opened.spread, 90.0)
        placed = Circle(center=(3, 4), angle=15)
        self.assertPointAlmost(placed.center, 3, 4)
        self.assertNumAlmost(placed.angle, 15.0)
        self.assertGreater(float(placed.radius), 0.0)
        sized = Circle(radius=10, spread=40)
        self.assertNumAlmost(sized.radius, 10.0)
        self.assertNumAlmost(sized.spread, 40.0)

        peri_h = Circle(center=(0, 0), perimeter_point=(10, 0), angle=45)
        peri_s = Circle(center=(0, 0), perimeter_point=(10, 0), spread=90)
        self.assertEqual(peri_h.model, CircleModel.CENTER_PERIMETER)
        self.assertNumAlmost(peri_h.angle, 45.0)
        self.assertNumAlmost(peri_s.spread, 90.0)

        ends_h = Circle(p1=(0, 0), p2=(10, 0), angle=20)
        ends_s = Circle(p1=(0, 0), p2=(10, 0), spread=40)
        self.assertEqual(ends_h.model, CircleModel.TWO_POINTS)
        self.assertNumAlmost(ends_h.angle, 20.0)
        self.assertNumAlmost(ends_s.spread, 40.0)

    def test_spread_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            Circle(center=(0, 0), radius=5, spread=-1)
        with self.assertRaises(ValueError):
            Circle(center=(0, 0), radius=5, spread=361)
        c = Circle(center=(0, 0), radius=5, spread=90)
        with self.assertRaises(ValueError):
            c.spread = -0.1
        with self.assertRaises(ValueError):
            c.spread = 360.1
        self.assertNumAlmost(c.spread, 90.0)

    def test_formula_over_full_turn_draws_a_full_circle(self):
        from scena.track import shape_outline
        knob = Circle(center=(0, 0), radius=400)
        c = Circle(center=(0, 0), radius=10, spread=lambda: knob.radius)
        _verts, closed = shape_outline(c, samples=12)
        self.assertTrue(closed)
        self.assertNumAlmost(c.spread, 360.0)

    def test_theta_window_raises_migration_error(self):
        with self.assertRaises(TypeError) as ctx:
            Circle(center=(0, 0), radius=5, theta1=0, theta2=90)
        msg = str(ctx.exception)
        self.assertIn("angle", msg)
        self.assertIn("spread", msg)

    def test_rotate_turns_angle_not_spread(self):
        c = Circle(center=(0, 0), radius=5, angle=10, spread=80)
        c.rotate_by(90)
        self.assertNumAlmost(c.angle, 100.0)
        self.assertNumAlmost(c.spread, 80.0)
        self.assertNumAlmost(c.angle, 100.0)
        c.rotate_to(15)
        self.assertNumAlmost(c.angle, 15.0)
        self.assertNumAlmost(c.angle, 15.0)
        self.assertNumAlmost(c.spread, 80.0)

    def test_rotation_link_writes_angle(self):
        c = Circle(center=(0, 0), radius=5, angle=0, spread=60)
        c["angle"] @= Attribute(40.0)
        self.assertNumAlmost(c.angle, 40.0)
        self.assertNumAlmost(c.angle, 40.0)
        self.assertNumAlmost(c.spread, 60.0)

    def test_scale_by_does_not_affect_arc(self):
        c = Circle(center=(0, 0), radius=5, angle=20, spread=80)
        c.scale_by(2)
        self.assertNumAlmost(c.angle, 20.0)
        self.assertNumAlmost(c.spread, 80.0)
        self.assertNumAlmost(c.radius, 10.0)

    def test_flip_reflects_heading_and_keeps_spread(self):
        c = Circle(center=(0, 0), radius=5, angle=30, spread=90)
        c.flip_x = True
        self.assertNumAlmost(c.angle, 150.0)
        self.assertNumAlmost(c.spread, 90.0)
        c.flip_x = False
        self.assertNumAlmost(c.angle, 30.0)
        self.assertNumAlmost(c.spread, 90.0)

        c.flip_y = True
        self.assertNumAlmost(c.angle, -30.0)
        self.assertNumAlmost(c.spread, 90.0)
        c.flip_y = False
        self.assertNumAlmost(c.angle, 30.0)

    def test_outline_seam(self):
        from scena.track import shape_outline
        full = Circle(center=(0, 0), radius=10, angle=30)
        verts, closed = shape_outline(full, samples=16)
        self.assertTrue(closed)
        self.assertLess(_ang_dist(_dir_deg(verts[0]), 30.0), 0.05)

        arc = Circle(center=(0, 0), radius=10, angle=40, spread=80)
        verts, closed = shape_outline(arc, samples=16)
        self.assertFalse(closed)
        self.assertLess(_ang_dist(_dir_deg(verts[0]), 0.0), 0.05)
        self.assertLess(_ang_dist(_dir_deg(verts[-1]), 80.0), 0.05)

    def test_heading_wrap_does_not_flip_opening(self):
        """The old theta1/theta2 spin did ``% 360`` on both ends and flipped the arc."""
        from scena.track import shape_outline
        c = Circle(center=(0, 0), radius=10, angle=0, spread=270)
        c.angle = (float(c.angle) + 100.0) % 360.0
        verts, closed = shape_outline(c, samples=24)
        self.assertFalse(closed)
        self.assertNumAlmost(c.spread, 270.0)
        span = (_dir_deg(verts[-1]) - _dir_deg(verts[0])) % 360.0
        self.assertAlmostEqual(span, 270.0, places=2)


class TestCircleTangentMethods(ShapeTestCase):
    def test_tangent_line_from_angle_delegates_to_tangent_angle_model(self):
        c = Circle(center=(0, 0), radius=10)
        line = c.tangent_line_from_angle(at_angle=0.0, size=5)
        self.assertEqual(line.model, LineModel.TANGENT_ANGLE)
        self.assertPointAlmost(line.p1, 10, 0, places=5)

    def test_tangent_lines_from_returns_left_and_right(self):
        c = Circle(center=(0, 0), radius=5)
        left, right = c.tangent_lines_from((10, 0))
        self.assertEqual(left.model, LineModel.TANGENT_POINT)
        self.assertEqual(right.model, LineModel.TANGENT_POINT)
        self.assertNotAlmostEqual(left.p2.y, right.p2.y)

    def test_point_at_angle(self):
        c = Circle(center=(0, 0), radius=10)
        p = c.point_at_angle(0.0)
        self.assertPointAlmost(p, 10, 0, places=5)


# ---------------------------------------------------------------------------
# Rect
# ---------------------------------------------------------------------------
class TestRectCornerCorner(ShapeTestCase):
    def test_derived_geometry(self):
        r = Rect(p1=(0, 0), p2=(10, 20))
        self.assertEqual(r.model, RectModel.CORNER_CORNER)
        self.assertNumAlmost(r.width, 10.0)
        self.assertNumAlmost(r.height, 20.0)
        self.assertPointAlmost(r.center, 5, 10)
        # Y-up: top has larger y
        self.assertPointAlmost(r.top_left, 0, 20)
        self.assertPointAlmost(r.top_right, 10, 20)
        self.assertPointAlmost(r.bottom_left, 0, 0)
        self.assertPointAlmost(r.bottom_right, 10, 0)

    def test_default_construction(self):
        from scena.shapes import _default_pose
        (cx, cy), unit = _default_pose()
        r = Rect()
        self.assertEqual(r.model, RectModel.CENTER_WH)
        self.assertPointAlmost(r.center, cx, cy)
        self.assertNumAlmost(r.width, 2.0 * unit)
        self.assertNumAlmost(r.height, 1.25 * unit)
        self.assertNumAlmost(r.angle, 0.0)

    def test_wrong_family_kwargs_raise(self):
        with self.assertRaises(TypeError) as ctx:
            Rect(radius=5)
        self.assertIn("radius", str(ctx.exception))
        self.assertIn("Circle", str(ctx.exception))

    def test_home_fill_center_only(self):
        from scena.shapes import _default_pose
        (cx, cy), unit = _default_pose()
        r = Rect(center=(1, 2))
        self.assertEqual(r.model, RectModel.CENTER_WH)
        self.assertPointAlmost(r.center, 1, 2)
        self.assertNumAlmost(r.width, 2.0 * unit)
        self.assertNumAlmost(r.height, 1.25 * unit)

    def test_home_fill_width_height(self):
        from scena.shapes import _default_pose
        (cx, cy), _ = _default_pose()
        r = Rect(width=40, height=30)
        self.assertEqual(r.model, RectModel.CENTER_WH)
        self.assertPointAlmost(r.center, cx, cy)
        self.assertNumAlmost(r.width, 40)
        self.assertNumAlmost(r.height, 30)

    def test_partial_home_size_raises(self):
        with self.assertRaises(ValueError):
            Rect(width=40)
        with self.assertRaises(ValueError):
            Rect(center=(0, 0), width=40)
        with self.assertRaises(ValueError):
            Rect(height=30)

    def test_incomplete_expert_path_raises(self):
        with self.assertRaises(ValueError) as ctx:
            Rect(p1=(0, 0))
        self.assertIn("p1", str(ctx.exception))
        with self.assertRaises(ValueError):
            Rect(p1=(0, 0), width=12)
        with self.assertRaises(ValueError):
            Rect(top_left=(0, 0))

    def test_reversed_corners_normalize(self):
        # p1 bottom-right of p2 -- width/height must still be positive.
        r = Rect(p1=(10, 20), p2=(0, 0))
        self.assertNumAlmost(r.width, 10.0)
        self.assertNumAlmost(r.height, 20.0)
        self.assertPointAlmost(r.top_left, 0, 20)

    def test_move_by(self):
        r = Rect(p1=(0, 0), p2=(10, 20))
        r.move_by(5, 5)
        self.assertPointAlmost(r.p1, 5, 5)
        self.assertPointAlmost(r.p2, 15, 25)
        self.assertPointAlmost(r.center, 10, 15)

    def test_rotate_by_about_center_moves_defining_corners(self):
        r = Rect(p1=(0, 0), p2=(10, 20))
        r.show_points()
        r.rotate_by(90)
        self.assertNumAlmost(r.angle, 90)
        # Defining p1/p2 orbit with the oriented rect (local BL / TR).
        self.assertPointAlmost(r.p1, 15, 5, places=5)       # was (0,0) about center (5,10)
        self.assertPointAlmost(r.p2, -5, 15, places=5)      # was (10,20)
        self.assertPointAlmost(r.bottom_left, 15, 5, places=5)
        self.assertPointAlmost(r.top_right, -5, 15, places=5)

    def test_construct_with_angle_pins_corners(self):
        r = Rect(p1=(0, 0), p2=(100, 50), angle=90)
        r.show_points()
        # p1/p2 stay where they were put. angle=90 swaps the sides:
        # the diagonal is vertical in the local frame, so width/height swap.
        self.assertPointAlmost(r.p1, 0, 0)
        self.assertPointAlmost(r.p2, 100, 50)
        self.assertPointAlmost(r.center, 50, 25)
        self.assertNumAlmost(r.width, 50)
        self.assertNumAlmost(r.height, 100)
        self.assertPointAlmost(r.bottom_left, 100, 0, places=5)
        self.assertPointAlmost(r.top_right, 0, 50, places=5)

    def test_rotate_by_about_other_pivot_moves_center(self):
        r = Rect(p1=(0, 0), p2=(10, 10))  # center (5,5)
        r.rotate_by(90, about=(0, 0))
        # (5,5) rotated 90deg CCW about the origin -> (-5, 5)
        self.assertPointAlmost(r.center, -5, 5, places=5)

    def test_scale_by_about_center(self):
        r = Rect(p1=(0, 0), p2=(10, 20))
        r.scale_by(2)
        self.assertNumAlmost(r.width, 20.0)
        self.assertNumAlmost(r.height, 40.0)
        self.assertPointAlmost(r.center, 5, 10)

    def test_zero_size_rect_is_valid(self):
        r = Rect(p1=(5, 5), p2=(5, 5))
        self.assertNumAlmost(r.width, 0.0)
        self.assertNumAlmost(r.height, 0.0)
        self.assertTrue(r.is_collapsed)

    def test_positive_rect_is_not_collapsed(self):
        r = Rect(center=(0, 0), width=40, height=20)
        self.assertFalse(r.is_collapsed)


class TestRectTopLeftWH(ShapeTestCase):
    def test_derived_geometry(self):
        # Y-up: top_left at y=20, height 20 → center at y=10, bottom at y=0
        r = Rect(top_left=(0, 20), width=10, height=20)
        self.assertEqual(r.model, RectModel.TOP_LEFT_WH)
        self.assertPointAlmost(r.center, 5, 10)
        self.assertPointAlmost(r.p1, 0, 0)
        self.assertPointAlmost(r.p2, 10, 20)

    def test_rotate_by_about_center_keeps_center_fixed(self):
        r = Rect(top_left=(0, 20), width=10, height=20)
        center_before = (r.center.x, r.center.y)
        r.rotate_by(90)
        self.assertPointAlmost(r.center, *center_before, places=5)
        self.assertNumAlmost(r.angle, 90)

    def test_scale_by_scales_width_height(self):
        r = Rect(top_left=(0, 20), width=10, height=20)
        r.scale_by(1.5)
        self.assertNumAlmost(r.width, 15.0)
        self.assertNumAlmost(r.height, 30.0)

    def test_negative_width_raises(self):
        with self.assertRaises(ValueError):
            Rect(top_left=(0, 20), width=-10, height=20)


class TestRectCenterWH(ShapeTestCase):
    def test_derived_geometry_matches_top_left_wh(self):
        a = Rect(top_left=(0, 20), width=10, height=20)
        b = Rect(center=(5, 10), width=10, height=20)
        self.assertPointAlmost(b.top_left, a.top_left.x, a.top_left.y)
        self.assertPointAlmost(b.p1, 0, 0)
        self.assertPointAlmost(b.p2, 10, 20)

    def test_move_by(self):
        r = Rect(center=(0, 0), width=10, height=10)
        r.move_by(3, 4)
        self.assertPointAlmost(r.center, 3, 4)

    def test_rotate_by_updates_oriented_p1_p2(self):
        r = Rect(center=(0, 0), width=20, height=10, angle=0)
        r.show_points()
        r.rotate_by(90)
        self.assertPointAlmost(r.p1, 5, -10, places=5)
        self.assertPointAlmost(r.p2, -5, 10, places=5)
        self.assertPointAlmost(r.bottom_left, 5, -10, places=5)
        self.assertPointAlmost(r.top_right, -5, 10, places=5)

    def test_negative_size_raises(self):
        with self.assertRaises(ValueError):
            Rect(center=(0, 0), width=-50, height=40)
        r2 = Rect(center=(0, 0), width=50, height=40)
        with self.assertRaises(ValueError):
            r2.scale_by(-1)


class TestRectPointVec(ShapeTestCase):
    def test_derived_geometry(self):
        r = Rect(p1=(0, 0), vec=Vec2(10, 20))
        self.assertEqual(r.model, RectModel.POINT_VEC)
        self.assertPointAlmost(r.p2, 10, 20)
        self.assertNumAlmost(r.width, 10.0)
        self.assertNumAlmost(r.height, 20.0)

    def test_scale_by_requires_force_when_vec_linked(self):
        v = Vec2(10, 20)
        r = Rect(p1=(0, 0), vec=lambda: v)
        with self.assertRaises(LinkedAttributeError):
            r.scale_by(2)
        r.scale_by(2, force=True)
        self.assertNumAlmost(r.width, 20.0)
        self.assertNumAlmost(r.height, 40.0)

    def test_negative_vec_components(self):
        # vec is a signed local extent. p1 stays; named corners come from the box.
        r = Rect(p1=(10, 10), vec=Vec2(-10, -10))
        self.assertPointAlmost(r.p1, 10, 10)
        self.assertPointAlmost(r.p2, 0, 0)
        self.assertPointAlmost(r.bottom_left, 0, 0)
        self.assertPointAlmost(r.top_right, 10, 10)
        self.assertNumAlmost(r.width, 10.0)
        self.assertNumAlmost(r.height, 10.0)

    def test_negative_vec_does_not_resort_p1(self):
        r = Rect(p1=(0, 0), vec=(-10, 20), angle=0)
        self.assertPointAlmost(r.p1, 0, 0)
        self.assertPointAlmost(r.p2, -10, 20)
        self.assertPointAlmost(r.bottom_left, -10, 0)
        self.assertPointAlmost(r.top_right, 0, 20)
        positive = Rect(p1=(0, 0), vec=(10, 20), angle=0)
        self.assertPointAlmost(positive.p1, 0, 0)
        self.assertPointAlmost(positive.bottom_left, 0, 0)
        self.assertPointAlmost(positive.p2, 10, 20)

    def test_rotated_corner_is_inside(self):
        r = Rect(center=(0, 0), width=10, height=20, angle=30)
        self.assertTrue(r.contains_point(r.bottom_left))
        self.assertTrue(r.contains_point(r.top_right))


class TestRectSpine(ShapeTestCase):
    def test_side_left_matches_manual_formula(self):
        p1, p2, height = (0, 0), (10, 0), 5
        r = Rect(p1=p1, p2=p2, height=height, anchor="side_left")
        self.assertEqual(r.model, RectModel.SPINE)
        self.assertEqual(r._anchor, "side_left")

        vx, vy = p2[0] - p1[0], p2[1] - p1[1]
        d = math.hypot(vx, vy)
        nx, ny = -vy / d, vx / d
        expected_cx = (p1[0] + p2[0]) / 2.0 + nx * height / 2.0
        expected_cy = (p1[1] + p2[1]) / 2.0 + ny * height / 2.0

        self.assertPointAlmost(r.center, expected_cx, expected_cy, places=5)
        self.assertNumAlmost(r.height, height)  # Defining cross-axis
        self.assertNumAlmost(r.width, d)  # Derivate along-axis
        tlx, tly = r.top_left.x, r.top_left.y
        trx, try_ = r.top_right.x, r.top_right.y
        self.assertAlmostEqual(math.hypot(trx - tlx, try_ - tly), d, places=5)

    def test_cap_uses_midpoint_as_center(self):
        r = Rect(p1=(0, -5), p2=(0, 5), height=10, anchor="cap")
        self.assertPointAlmost(r.center, 0, 0, places=5)
        self.assertNumAlmost(r.height, 10.0)
        self.assertNumAlmost(r.width, 10.0)  # |p2-p1| = 10
        # Cap length (vertical) shows up as along-axis local width after rotation.
        tlx, tly = r.top_left.x, r.top_left.y
        blx, bly = r.bottom_left.x, r.bottom_left.y
        self.assertAlmostEqual(math.hypot(blx - tlx, bly - tly), 10.0, places=5)

    def test_square_extends_axis_by_height(self):
        r = Rect(p1=(0, 0), p2=(10, 0), height=4, anchor="square")
        self.assertPointAlmost(r.center, 5, 0, places=5)
        self.assertNumAlmost(r.height, 4.0)
        self.assertNumAlmost(r.width, 14.0)  # d + height
        # Short-wall midpoints (outer caps).
        self.assertPointAlmost(r.left_center, -2, 0, places=5)
        self.assertPointAlmost(r.right_center, 12, 0, places=5)
        # End-square centers match Defining p1/p2 for anchor="square".
        self.assertPointAlmost(r.left_square_center, 0, 0, places=5)
        self.assertPointAlmost(r.right_square_center, 10, 0, places=5)
        self.assertPointAlmost(r.left_square_center, r.p1.x, r.p1.y, places=5)
        self.assertPointAlmost(r.right_square_center, r.p2.x, r.p2.y, places=5)

    def test_side_right_mirrors_side_left(self):
        left = Rect(p1=(0, 0), p2=(10, 0), height=5, anchor="side_left")
        right = Rect(p1=(0, 0), p2=(10, 0), height=5, anchor="side_right")
        self.assertNumAlmost(left.height, 5.0)
        self.assertNumAlmost(right.height, 5.0)
        self.assertNumAlmost(left.width, right.width)
        self.assertNotAlmostEqual(left.center.y, right.center.y)
        self.assertAlmostEqual(left.center.y, -right.center.y, places=5)

    def test_width_differs_from_height(self):
        # Regression: old EDGE_WIDTH mirrored thickness into both .width and .height.
        r = Rect(p1=(0, 0), p2=(10, 0), height=4, anchor="cap")
        self.assertNumAlmost(r.width, 10.0)
        self.assertNumAlmost(r.height, 4.0)
        self.assertNotAlmostEqual(r.width, r.height)

    def test_negative_height_raises(self):
        with self.assertRaises(ValueError):
            Rect(p1=(0, 0), p2=(10, 0), height=-5, anchor="side_left")

    def test_invalid_anchor_raises(self):
        with self.assertRaises(ValueError) as ctx:
            Rect(p1=(0, 0), p2=(10, 0), height=5, anchor="middle")
        self.assertIn("anchor", str(ctx.exception))

    def test_missing_anchor_raises(self):
        with self.assertRaises(ValueError):
            Rect(p1=(0, 0), p2=(10, 0), height=5)

    def test_setting_rotation_turns_about_the_center(self):
        # The heading is derived from p1 -> p2: setting it is rotate_to (it used to raise).
        r = Rect(p1=(0, 0), p2=(10, 0), height=5, anchor="side_left")
        ref = Rect(p1=(0, 0), p2=(10, 0), height=5, anchor="side_left")
        r.angle = 30.0
        ref.rotate_to(30.0)
        self.assertNumAlmost(r.angle, 30.0, places=6)
        self.assertPointAlmost(r.p1, ref.p1.x, ref.p1.y, places=6)
        self.assertPointAlmost(r.p2, ref.p2.x, ref.p2.y, places=6)

    def test_rotate_by_recomputes_from_p1_p2(self):
        r = Rect(p1=(0, 0), p2=(10, 0), height=5, anchor="side_left")
        r.rotate_by(90, about=(0, 0))
        self.assertPointAlmost(r.p1, 0, 0, places=5)
        self.assertPointAlmost(r.p2, 0, 10, places=5)
        self.assertNumAlmost(r.angle, 90, places=5)

    def test_scale_by_keeps_height_non_negative(self):
        r = Rect(p1=(0, 0), p2=(10, 0), height=4, anchor="cap")
        with self.assertRaises(ValueError):
            r.scale_by(-2)
        self.assertNumAlmost(r.width, 10.0)

    def test_clone_preserves_spine(self):
        r = Rect(p1=(0, 0), p2=(10, 0), height=4, anchor="square")
        c = r.clone()
        self.assertEqual(c.model, RectModel.SPINE)
        self.assertEqual(c._anchor, "square")
        self.assertNumAlmost(c.height, 4.0)
        self.assertNumAlmost(c.width, 14.0)


class TestRectSquareCenters(ShapeTestCase):
    """Derivate left_square_center / right_square_center (end-square loci)."""

    def test_center_wh_axis_aligned(self):
        r = Rect(center=(100, 200), width=20, height=8)
        # Inset by h/2 from short walls: (±(w-h)/2, 0) about center.
        self.assertPointAlmost(r.left_square_center, 94, 200, places=5)
        self.assertPointAlmost(r.right_square_center, 106, 200, places=5)
        self.assertPointAlmost(r.left_center, 90, 200, places=5)
        self.assertPointAlmost(r.right_center, 110, 200, places=5)

    def test_inset_from_edge_mids_by_half_height(self):
        r = Rect(center=(0, 0), width=30, height=10)
        self.assertAlmostEqual(
            float(r.left_square_center.x) - float(r.left_center.x), 5.0, places=5
        )
        self.assertAlmostEqual(
            float(r.right_center.x) - float(r.right_square_center.x), 5.0, places=5
        )

    def test_rotated_matches_oriented_local(self):
        r = Rect(center=(0, 0), width=20, height=8, angle=90)
        # Local left_square=(-6, 0) → world (0, -6) after +90°.
        self.assertPointAlmost(r.left_square_center, 0, -6, places=5)
        self.assertPointAlmost(r.right_square_center, 0, 6, places=5)

    def test_spine_square_matches_defining_p1_p2(self):
        r = Rect(p1=(0, 0), p2=(10, 0), height=4, anchor="square")
        self.assertPointAlmost(r.left_square_center, 0, 0, places=5)
        self.assertPointAlmost(r.right_square_center, 10, 0, places=5)

    def test_spine_cap_differs_from_square_centers(self):
        r = Rect(p1=(0, 0), p2=(10, 0), height=4, anchor="cap")
        self.assertPointAlmost(r.left_center, 0, 0, places=5)
        self.assertPointAlmost(r.right_center, 10, 0, places=5)
        self.assertPointAlmost(r.left_square_center, 2, 0, places=5)
        self.assertPointAlmost(r.right_square_center, 8, 0, places=5)

    def test_updates_when_size_changes(self):
        r = Rect(center=(0, 0), width=20, height=8)
        _ = r.left_square_center  # live
        _ = r.right_square_center
        r.width = 40
        self.assertPointAlmost(r.left_square_center, -16, 0, places=5)
        self.assertPointAlmost(r.right_square_center, 16, 0, places=5)

    def test_square_when_width_equals_height_collapses_to_center(self):
        r = Rect(center=(50, 50), width=10, height=10)
        self.assertPointAlmost(r.left_square_center, 50, 50, places=5)
        self.assertPointAlmost(r.right_square_center, 50, 50, places=5)


class _DrawSpy:
    """Minimal canvas: count drawRect vs drawRRect (unused-path contract)."""

    def __init__(self):
        self.n_rect = 0
        self.n_rrect = 0

    def save(self):
        pass

    def restore(self):
        pass

    def translate(self, *args):
        pass

    def rotate(self, *args):
        pass

    def drawRect(self, *args):
        self.n_rect += 1

    def drawRRect(self, *args):
        self.n_rrect += 1


class TestRectCornerRadius(ShapeTestCase):
    def test_default_is_zero(self):
        self.assertEqual(Rect(center=(0, 0), width=40, height=20).corner_radius, 0.0)
        self.assertEqual(Square(center=(0, 0), length=20).corner_radius, 0.0)
        self.assertEqual(Rect().corner_radius, 0.0)
        self.assertEqual(Square().corner_radius, 0.0)

    def test_constructor_extra_does_not_break_dispatch(self):
        r = Rect(center=(1, 2), width=40, height=20, corner_radius=8)
        self.assertEqual(r.model, RectModel.CENTER_WH)
        self.assertPointAlmost(r.center, 1, 2)
        self.assertNumAlmost(r.width, 40)
        self.assertNumAlmost(r.height, 20)
        self.assertEqual(r.corner_radius, 8.0)

        from scena.shapes import _default_pose
        (cx, cy), unit = _default_pose()
        r2 = Rect(center=(3, 4), corner_radius=5)
        self.assertEqual(r2.model, RectModel.CENTER_WH)
        self.assertPointAlmost(r2.center, 3, 4)
        self.assertNumAlmost(r2.width, 2.0 * unit)
        self.assertEqual(r2.corner_radius, 5.0)

        sq = Square(center=(0, 0), length=30, corner_radius=6)
        self.assertEqual(sq.corner_radius, 6.0)
        self.assertNumAlmost(sq.length, 30)

    def test_live_setter_clamps_negative(self):
        r = Rect(center=(0, 0), width=40, height=20)
        r.corner_radius = 12
        self.assertEqual(r.corner_radius, 12.0)
        with self.assertRaises(ValueError):
            r.corner_radius = -4

    def test_clone_and_takein_copy_radius(self):
        r = Rect(center=(5, 5), width=40, height=20, corner_radius=9)
        copy = r.clone()
        self.assertEqual(copy.corner_radius, 9.0)
        other = Rect(center=(0, 0), width=10, height=10)
        other._takein(r)
        self.assertEqual(other.corner_radius, 9.0)

        sq = Square(center=(1, 1), length=16, corner_radius=3)
        sq2 = sq.clone()
        self.assertEqual(sq2.corner_radius, 3.0)

    def test_hit_test_follows_rounded_fill(self):
        r = Rect(center=(0, 0), width=40, height=20, corner_radius=8)
        # Inside the AABB, outside the fillet (local corner (20, 10), r=8).
        self.assertFalse(r.contains_point(19.0, 9.0))
        self.assertTrue(r.contains_point(0, 0))
        self.assertTrue(r.contains_point(0, 9.0))
        self.assertFalse(r.contains_point(21.0, 0))

        sq = Square(center=(0, 0), length=20, corner_radius=6)
        self.assertFalse(sq.contains_point(9.0, 9.0))
        self.assertFalse(sq.contains_point(11.0, 0))

    def test_draw_rect_when_zero_rrect_when_positive(self):
        r = Rect(center=(0, 0), width=40, height=20)
        spy = _DrawSpy()
        r._geometry_draw(spy)
        self.assertGreater(spy.n_rect, 0)
        self.assertEqual(spy.n_rrect, 0)

        r.corner_radius = 8
        spy2 = _DrawSpy()
        r._geometry_draw(spy2)
        self.assertEqual(spy2.n_rect, 0)
        self.assertGreater(spy2.n_rrect, 0)

        sq = Square(center=(0, 0), length=20, corner_radius=4)
        spy3 = _DrawSpy()
        sq._geometry_draw(spy3)
        self.assertEqual(spy3.n_rect, 0)
        self.assertGreater(spy3.n_rrect, 0)


# ---------------------------------------------------------------------------
# Square
# ---------------------------------------------------------------------------
class TestSquare(ShapeTestCase):
    def test_init_sets_what_rect_init_sets(self):
        # Square.__init__ skips Rect.__init__ (its own signatures), so state a
        # future Rect.__init__ adds would be silently missing on every Square.
        # Built the same way, both must carry the same instance attributes;
        # only the size parts differ (width/height vs length). Rect sets
        # _anchor; Square once did not (harmless only while SPINE-gated).
        size_rect, size_square = {"width", "height"}, {"length"}
        cases = [
            (dict(center=(0, 0), width=4, height=4), dict(center=(0, 0), length=4)),
            (dict(top_left=(1, 2), width=4, height=4, angle=10, corner_radius=1),
             dict(top_left=(1, 2), length=4, angle=10, corner_radius=1)),
            (dict(box=Box(center=(0, 0), width=4, height=4)),
             dict(box=Box(center=(0, 0), width=4, height=4))),
            ({}, {}),
        ]
        for kw_rect, kw_square in cases:
            with self.subTest(square=kw_square):
                rect_keys = set(vars(Rect(**kw_rect))) - size_rect
                square_keys = set(vars(Square(**kw_square))) - size_square
                self.assertEqual(rect_keys - square_keys, set(),
                                 "set by Rect.__init__, missing on Square")
                self.assertEqual(square_keys - rect_keys, set(),
                                 "set by Square.__init__ only")

    def test_top_left_scale_keeps_the_pivot(self):
        # Rect.scale_by (TOP_LEFT_WH) re-read the old length: the square drifted.
        for about in (None, (50.0, -20.0)):
            with self.subTest(about=about):
                sq = Square(top_left=(3, -2), length=20, angle=15)
                cx, cy = sq._center_xy()
                sq.scale_by(1.5, about=about)
                px, py = (cx, cy) if about is None else about
                self.assertPointAlmost(sq.center, px + 1.5 * (cx - px), py + 1.5 * (cy - py))
                self.assertNumAlmost(sq.length, 30.0)

    def test_default_construction(self):
        from scena.shapes import _default_pose
        (cx, cy), unit = _default_pose()
        sq = Square()
        self.assertEqual(sq.model, RectModel.CENTER_WH)
        self.assertPointAlmost(sq.center, cx, cy)
        self.assertNumAlmost(sq.length, 1.5 * unit)
        self.assertNumAlmost(sq.width, 1.5 * unit)
        self.assertNumAlmost(sq.height, 1.5 * unit)

    def test_home_fill_center_only(self):
        from scena.shapes import _default_pose
        (_, _), unit = _default_pose()
        sq = Square(center=(5, 5))
        self.assertPointAlmost(sq.center, 5, 5)
        self.assertNumAlmost(sq.length, 1.5 * unit)

    def test_center_length_model(self):
        sq = Square(center=(0, 0), length=10)
        self.assertNumAlmost(sq.width, 10.0)
        self.assertNumAlmost(sq.height, 10.0)
        self.assertPointAlmost(sq.top_left, -5, 5)

    def test_top_left_length_model(self):
        sq = Square(top_left=(0, 10), length=10)
        self.assertPointAlmost(sq.center, 5, 5)
        self.assertNumAlmost(sq.width, 10.0)

    def test_width_height_are_derivate(self):
        sq = Square(center=(0, 0), length=10)
        with self.assertRaises(DerivedAttributeError):
            sq.width = 50
        with self.assertRaises(DerivedAttributeError):
            sq.height = 50

    def test_setting_length_updates_width_height(self):
        sq = Square(center=(0, 0), length=10)
        sq.length = 20
        self.assertNumAlmost(sq.width, 20.0)
        self.assertNumAlmost(sq.height, 20.0)

    def test_scale_by_keeps_length_in_sync(self):
        sq = Square(center=(0, 0), length=10)
        sq.scale_by(2)
        self.assertNumAlmost(sq.length, 20.0)
        self.assertNumAlmost(sq.width, 20.0)
        self.assertNumAlmost(sq.height, 20.0)

    def test_move_by_and_rotate_by_inherited_from_rect(self):
        sq = Square(center=(0, 0), length=10)
        sq.move_by(5, 5)
        self.assertPointAlmost(sq.center, 5, 5)
        sq.show_points()
        sq.rotate_by(90)
        self.assertNumAlmost(sq.angle, 90)
        # Oriented Derivate corners (and p1/p2) follow the rotation.
        self.assertPointAlmost(sq.bottom_left, 10, 0, places=5)
        self.assertPointAlmost(sq.p1, 10, 0, places=5)
        self.assertNumAlmost(sq.length, 10.0)

    def test_conflicting_wh_signature_raises(self):
        # width/height are not Square constructor keys (use length=).
        with self.assertRaises(TypeError) as ctx:
            Square(center=(0, 0), width=10, height=10)
        self.assertIn("width", str(ctx.exception))


# ---------------------------------------------------------------------------
# Ellipse
# ---------------------------------------------------------------------------
class TestEllipseCenterWH(ShapeTestCase):
    def test_default_construction(self):
        from scena.shapes import _default_pose
        (cx, cy), unit = _default_pose()
        e = Ellipse()
        self.assertEqual(e.model, EllipseModel.CENTER_WH)
        self.assertPointAlmost(e.center, cx, cy)
        self.assertNumAlmost(e.width, 2.0 * unit)
        self.assertNumAlmost(e.height, 1.25 * unit)
        self.assertNumAlmost(e.angle, 0.0)

    def test_scale_by_negative_raises(self):
        e = Ellipse(center=(0, 0), width=200, height=100)
        with self.assertRaises(ValueError):
            e.scale_by(-1)

    def test_foci_along_major_axis(self):
        e = Ellipse(center=(0, 0), width=10, height=6)
        self.assertEqual(e.model, EllipseModel.CENTER_WH)
        a, b = 5.0, 3.0
        c = math.sqrt(a * a - b * b)
        self.assertPointAlmost(e.fp1, -c, 0, places=5)
        self.assertPointAlmost(e.fp2, c, 0, places=5)
        self.assertNumAlmost(e.major_axis, 10.0)

    def test_foci_along_height_when_taller(self):
        e = Ellipse(center=(0, 0), width=6, height=10)
        a, b = 5.0, 3.0
        c = math.sqrt(a * a - b * b)
        self.assertPointAlmost(e.fp1, 0, -c, places=5)
        self.assertPointAlmost(e.fp2, 0, c, places=5)

    def test_circle_case_zero_focal_distance(self):
        e = Ellipse(center=(0, 0), width=10, height=10)
        self.assertNumAlmost(e.c, 0.0, places=5)

    def test_move_by(self):
        e = Ellipse(center=(0, 0), width=10, height=6)
        e.move_by(5, 5)
        self.assertPointAlmost(e.center, 5, 5)

    def test_rotate_by_about_center(self):
        e = Ellipse(center=(0, 0), width=10, height=6, angle=0.0)
        e.rotate_by(90)
        self.assertNumAlmost(e.angle, 90)

    def test_scale_by(self):
        e = Ellipse(center=(0, 0), width=10, height=6)
        e.scale_by(2)
        self.assertNumAlmost(e.width, 20.0)
        self.assertNumAlmost(e.height, 12.0)

    def test_scale_by_draw_uses_geometry_not_ctm_scale(self):
        """Hitbox follows width/height; draw must not also multiply ``_scale``."""
        e = Ellipse(center=(0, 0), width=10, height=6)
        e.scale_by(2)
        self.assertNumAlmost(e.scale, 2.0)

        class _OvalSpy:
            def __init__(self):
                self.scales = []
                self.ovals = []

            def save(self):
                pass

            def restore(self):
                pass

            def translate(self, *args):
                pass

            def rotate(self, *args):
                pass

            def scale(self, x, y):
                self.scales.append((x, y))

            def drawOval(self, rect, paint):
                self.ovals.append((rect.width(), rect.height()))

        spy = _OvalSpy()
        e._geometry_draw(spy)
        self.assertEqual(spy.scales, [])
        self.assertGreater(len(spy.ovals), 0)
        for w, h in spy.ovals:
            self.assertAlmostEqual(w, 20.0, places=5)
            self.assertAlmostEqual(h, 12.0, places=5)

    def test_partial_home_size_raises(self):
        with self.assertRaises(ValueError):
            Ellipse(center=(0, 0), width=10)
        with self.assertRaises(ValueError):
            Ellipse(width=10)


class TestEllipseFocalPoints(ShapeTestCase):
    def test_derived_geometry(self):
        e = Ellipse(fp1=(-3, 0), fp2=(3, 0), major_axis=10)
        self.assertEqual(e.model, EllipseModel.FOCAL_POINTS)
        self.assertPointAlmost(e.center, 0, 0, places=5)
        self.assertNumAlmost(e.width, 10.0)
        self.assertNumAlmost(e.height, 8.0, places=5)  # b = sqrt(5^2-3^2)=4 -> height=8

    def test_major_axis_equal_to_the_focal_distance_is_a_collapsed_ellipse(self):
        seg = Ellipse(fp1=(-5, 0), fp2=(5, 0), major_axis=10)
        self.assertTrue(seg.is_collapsed)
        self.assertNumAlmost(seg.width, 10.0)
        self.assertNumAlmost(seg.height, 0.0)
        dot = Ellipse(fp1=(3, 4), fp2=(3, 4), major_axis=0)     # zero size builds (C8)
        self.assertTrue(dot.is_collapsed)

    def test_invalid_major_axis_raises(self):
        with self.assertRaises(ValueError):
            Ellipse(fp1=(-5, 0), fp2=(5, 0), major_axis=5)  # major_axis <= distance

    def test_focal_axis_cannot_shrink_past_the_foci(self):
        e = Ellipse(fp1=(-30, 0), fp2=(30, 0), major_axis=100)
        e.major_axis = 10
        # Degenerate segment between the foci: width == distance, height == 0.
        self.assertGreaterEqual(float(e.width) + 1e-6, 60.0)
        self.assertNumAlmost(e.width, 60.0)
        self.assertNumAlmost(e.height, 0.0)
        self.assertTrue(e.is_collapsed)

    def test_equal_focal_points_edge_case(self):
        # Degenerates toward a circle (distance 0); still must not raise.
        e = Ellipse(fp1=(0, 0), fp2=(0, 0), major_axis=10)
        self.assertNumAlmost(e.width, 10.0)
        self.assertNumAlmost(e.height, 10.0, places=5)

    def test_rotate_by_recomputes_angle(self):
        e = Ellipse(fp1=(-3, 0), fp2=(3, 0), major_axis=10)
        e.rotate_by(90, about=(0, 0))
        self.assertPointAlmost(e.fp1, 0, -3, places=5)
        self.assertPointAlmost(e.fp2, 0, 3, places=5)
        self.assertAlmostEqual(_norm_angle(e.angle), _norm_angle(90), places=5)

    def test_move_by_moves_both_foci(self):
        e = Ellipse(fp1=(-3, 0), fp2=(3, 0), major_axis=10)
        e.move_by(10, 10)
        self.assertPointAlmost(e.fp1, 7, 10, places=5)
        self.assertPointAlmost(e.fp2, 13, 10, places=5)


class TestEllipseFromRect(ShapeTestCase):
    def test_tracks_rect_geometry(self):
        r = Rect(center=(0, 0), width=20, height=10)
        e = Ellipse(from_rect=r)
        self.assertEqual(e.model, EllipseModel.FROM_RECT)
        self.assertPointAlmost(e.center, 0, 0)
        self.assertNumAlmost(e.width, 20.0)
        self.assertNumAlmost(e.height, 10.0)

    def test_padding_shrinks_dimensions(self):
        r = Rect(center=(0, 0), width=20, height=10)
        e = Ellipse(from_rect=r, padding=2)
        self.assertNumAlmost(e.width, 16.0)
        self.assertNumAlmost(e.height, 6.0)

    def test_padding_overflow_collapses(self):
        r = Rect(center=(0, 0), width=10, height=10)
        e = Ellipse(from_rect=r, padding=8)
        self.assertNumAlmost(e.width, 0.0)
        self.assertNumAlmost(e.height, 0.0)
        self.assertTrue(e.is_collapsed)
        self.assertFalse(e.contains_point(0, 0))

    def test_reactive_when_rect_resizes(self):
        r = Rect(center=(0, 0), width=20, height=10)
        e = Ellipse(from_rect=r)
        r.width = 40
        self.assertNumAlmost(e.width, 40.0)

    def test_move_by_raises_and_can_be_forced(self):
        r = Rect(center=(0, 0), width=20, height=10)
        e = Ellipse(from_rect=r)
        with self.assertRaises(LinkedAttributeError):
            e.move_by(1, 1)
        e.move_by(1, 1, force=True)


# ---------------------------------------------------------------------------
# Polygon
# ---------------------------------------------------------------------------
class TestPolygon(ShapeTestCase):
    def test_requires_at_least_three_points(self):
        with self.assertRaises(ValueError):
            Polygon(points=[(0, 0), (1, 1)])

    def test_default_construction_is_irregular_quad_at_center(self):
        from scena.shapes import _default_pose
        (cx, cy), unit = _default_pose()
        poly = Polygon()
        self.assertEqual(len(poly.points), 4)
        self.assertPointAlmost(poly.centroid, cx, cy, places=5)
        # Unequal distances from center → not regular.
        radii = [math.hypot(v.x - cx, v.y - cy) for v in poly.points]
        self.assertGreater(max(radii) - min(radii), 0.1 * unit)
        self.assertGreater(poly.signed_area, 0.0)  # CCW

    def test_triangle_centroid_and_area(self):
        poly = Polygon(points=[(0, 0), (4, 0), (0, 4)])
        self.assertPointAlmost(poly.centroid, 4 / 3, 4 / 3, places=5)
        self.assertPointAlmost(poly.center, 4 / 3, 4 / 3, places=5)  # alias
        self.assertNumAlmost(poly.signed_area, 8.0, places=5)  # 0.5*4*4 = 8, CCW positive
        expected_perimeter = 4 + 4 + math.hypot(4, 4)
        self.assertNumAlmost(poly.perimeter_length, expected_perimeter, places=5)

    def test_clockwise_winding_gives_negative_area(self):
        poly = Polygon(points=[(0, 0), (0, 4), (4, 0)])
        self.assertLess(poly.signed_area, 0)

    def test_vertex_can_be_linked(self):
        anchor = Point(100, 100)
        poly = Polygon(points=[lambda: anchor, (0, 0), (10, 0), (10, 10)])
        anchor.move_to(50, 50)
        self.assertPointAlmost(poly.points[0], 50, 50)

    def test_move_by_translates_every_vertex(self):
        poly = Polygon(points=[(0, 0), (4, 0), (0, 4)])
        poly.move_by(10, 10)
        self.assertPointAlmost(poly.points[0], 10, 10)
        self.assertPointAlmost(poly.points[1], 14, 10)
        self.assertPointAlmost(poly.points[2], 10, 14)

    def test_rotate_by_about_centroid(self):
        poly = Polygon(points=[(-1, 0), (1, 0), (0, 2)])
        cx, cy = poly.centroid.x, poly.centroid.y
        poly.rotate_by(180)
        self.assertAlmostEqual(poly.centroid.x, cx, places=5)
        self.assertAlmostEqual(poly.centroid.y, cy, places=5)

    def test_rotate_by_raises_on_linked_vertex(self):
        shared = Point(0, 0)
        poly = Polygon(points=[lambda: shared, (10, 0), (10, 10), (0, 10)])
        with self.assertRaises(LinkedAttributeError):
            poly.rotate_by(math.degrees(0.1))
        poly.rotate_by(math.degrees(0.1), force=True)

    def test_scale_by_about_pivot(self):
        poly = Polygon(points=[(0, 0), (2, 0), (2, 2), (0, 2)])
        poly.scale_by(2, about=(0, 0))
        self.assertPointAlmost(poly.points[2], 4, 4)

    def test_takein_requires_matching_vertex_count(self):
        a = Polygon(points=[(0, 0), (1, 0), (1, 1)])
        b = Polygon(points=[(0, 0), (1, 0), (1, 1), (0, 1)])
        with self.assertRaises(ValueError):
            a._takein(b)

    def test_centroid_is_readonly(self):
        poly = Polygon(points=[(0, 0), (4, 0), (0, 4)])
        with self.assertRaises(DerivedAttributeError):
            poly.centroid = (1, 1)

    def test_color_and_visual_kwargs(self):
        from scena.color import Color
        from scena.style import Gradient
        poly = Polygon(points=[(0, 0), (10, 0), (5, 8)], color="tomato")
        self.assertEqual(Color(poly.fill).rgb[:3], Color("tomato").rgb[:3])
        styled = Polygon(
            points=[(0, 0), (10, 0), (5, 8)],
            visual=Gradient("red", "blue"),
        )
        self.assertIsNotNone(styled.visual)
        with self.assertRaises(ValueError):
            Polygon(
                points=[(0, 0), (10, 0), (5, 8)],
                color="red",
                visual=Gradient("red", "blue"),
            )

    def test_class_color_visual_group_defaults(self):
        from scena.color import Color
        from scena.recipes import Neon

        class Tri(Polygon, color="gold", group="tri"):
            pass

        t = Tri(points=[(0, 0), (10, 0), (5, 8)])
        self.assertEqual(Color(t.fill).rgb[:3], Color("gold").rgb[:3])
        self.assertIn("tri", t.group)

        class Fancy(Polygon, visual=Neon(), group="fx"):
            pass

        f = Fancy(points=[(0, 0), (4, 0), (0, 4)])
        self.assertIsNotNone(f.visual)
        self.assertIn("fx", f.group)


# ---------------------------------------------------------------------------
# RegularPolygon
# ---------------------------------------------------------------------------
class TestRegularPolygon(ShapeTestCase):
    def test_default_n_when_geom_given(self):
        hexagon = RegularPolygon(center=(0, 0), radius=5)
        self.assertEqual(hexagon._n, 6)
        self.assertEqual(hexagon.model, RegularPolygonModel.CENTER_RADIUS)
        self.assertPointAlmost(hexagon.center, 0, 0)
        self.assertNumAlmost(hexagon.radius, 5.0)

    def test_center_only_defaults_n(self):
        from scena.shapes import _default_pose
        (_, _), unit = _default_pose()
        poly = RegularPolygon(center=(3, 4))
        self.assertEqual(poly._n, 6)
        self.assertPointAlmost(poly.center, 3, 4)
        self.assertNumAlmost(poly.radius, unit)

    def test_default_construction_is_hexagon(self):
        from scena.shapes import _default_pose
        (cx, cy), unit = _default_pose()
        hexagon = RegularPolygon()
        self.assertEqual(hexagon._n, 6)
        self.assertEqual(hexagon.model, RegularPolygonModel.CENTER_RADIUS)
        self.assertPointAlmost(hexagon.center, cx, cy)
        self.assertNumAlmost(hexagon.radius, unit)

    def test_default_with_n_only(self):
        from scena.shapes import _default_pose
        (cx, cy), unit = _default_pose()
        pent = RegularPolygon(n=5)
        self.assertEqual(pent._n, 5)
        self.assertPointAlmost(pent.center, cx, cy)
        self.assertNumAlmost(pent.radius, unit)

    def test_requires_n_at_least_three(self):
        with self.assertRaises(ValueError):
            RegularPolygon(n=2, center=(0, 0), radius=5)

    def test_center_radius_vertex_positions(self):
        hexagon = RegularPolygon(n=6, center=(0, 0), radius=10, angle=0.0)
        self.assertEqual(hexagon.model, RegularPolygonModel.CENTER_RADIUS)
        self.assertEqual(len(hexagon.points), 6)
        self.assertPointAlmost(hexagon.points[0], 10, 0, places=5)
        expected_side = 2 * 10 * math.sin(math.pi / 6)
        self.assertNumAlmost(hexagon.side, expected_side, places=5)

    def test_center_side_derives_radius(self):
        square_ish = RegularPolygon(n=4, center=(0, 0), side=10, angle=0.0)
        self.assertEqual(square_ish.model, RegularPolygonModel.CENTER_SIDE)
        expected_radius = 10 / (2 * math.sin(math.pi / 4))
        self.assertNumAlmost(square_ish.radius, expected_radius, places=5)

    def test_vertex_side_derives_center(self):
        tri = RegularPolygon(n=3, vertex=(10, 0), side=10, angle=0.0)
        self.assertEqual(tri.model, RegularPolygonModel.VERTEX_SIDE)
        self.assertPointAlmost(tri.points[0], 10, 0, places=5)

    def test_vertices_are_equidistant_from_center(self):
        pent = RegularPolygon(n=5, center=(1, 1), radius=7)
        for v in pent.points:
            d = math.hypot(v.x - 1, v.y - 1)
            self.assertAlmostEqual(d, 7.0, places=5)

    def test_centroid_matches_center_by_symmetry(self):
        pent = RegularPolygon(n=5, center=(3, -2), radius=7)
        self.assertAlmostEqual(pent.centroid.x, 3.0, places=4)
        self.assertAlmostEqual(pent.centroid.y, -2.0, places=4)

    def test_vertices_are_readonly(self):
        hexagon = RegularPolygon(n=6, center=(0, 0), radius=10)
        with self.assertRaises(DerivedAttributeError):
            hexagon.points[0].x = 999

    def test_move_by_translates_center(self):
        hexagon = RegularPolygon(n=6, center=(0, 0), radius=10)
        hexagon.move_by(5, 5)
        self.assertPointAlmost(hexagon.center, 5, 5)
        self.assertPointAlmost(hexagon.points[0], 15, 5, places=5)

    def test_rotate_by_updates_angle_and_vertices(self):
        hexagon = RegularPolygon(n=6, center=(0, 0), radius=10, angle=0.0)
        hexagon.rotate_by(30)
        self.assertNumAlmost(hexagon.angle, 30)
        self.assertPointAlmost(
            hexagon.points[0], 10 * math.cos(math.pi / 6), 10 * math.sin(math.pi / 6), places=5
        )

    def test_scale_by_scales_radius(self):
        hexagon = RegularPolygon(n=6, center=(0, 0), radius=10)
        hexagon.scale_by(2)
        self.assertNumAlmost(hexagon.radius, 20.0)

    def test_takein_requires_matching_n(self):
        a = RegularPolygon(n=5, center=(0, 0), radius=5)
        b = RegularPolygon(n=6, center=(0, 0), radius=5)
        with self.assertRaises(ValueError):
            a._takein(b)


# ---------------------------------------------------------------------------
# EquilateralTriangle
# ---------------------------------------------------------------------------
class TestEquilateralTriangle(ShapeTestCase):
    def test_always_three_vertices(self):
        tri = EquilateralTriangle(center=(0, 0), side=10)
        self.assertEqual(len(tri.points), 3)

    def test_default_construction(self):
        from scena.shapes import _default_pose
        (cx, cy), unit = _default_pose()
        tri = EquilateralTriangle()
        self.assertEqual(len(tri.points), 3)
        self.assertEqual(tri.model, RegularPolygonModel.CENTER_RADIUS)
        self.assertPointAlmost(tri.center, cx, cy)
        self.assertNumAlmost(tri.radius, unit)

    def test_conflicting_n_raises(self):
        with self.assertRaises(ValueError):
            EquilateralTriangle(n=4, center=(0, 0), side=10)

    def test_side_length_between_vertices(self):
        tri = EquilateralTriangle(center=(0, 0), side=10, angle=0.0)
        p0, p1 = tri.points[0], tri.points[1]
        d = math.hypot(p1.x - p0.x, p1.y - p0.y)
        self.assertAlmostEqual(d, 10.0, places=5)

    def test_rotation_zero_points_right(self):
        """rotation is where the apex points, like every heading: 0 → +x."""
        tri = EquilateralTriangle(center=(0, 0), radius=10, angle=0.0)
        self.assertPointAlmost(tri.points[0], 10, 0, places=5)
        same = RegularPolygon(center=(0, 0), radius=10, n=3, angle=0.0)
        for a, b in zip(tri.points, same.points):
            self.assertPointAlmost(a, b.x, b.y, places=9)

    def test_rotation_ninety_has_flat_base(self):
        """angle=90 → the upright pose: apex on +y, base parallel to the x-axis."""
        tri = EquilateralTriangle(center=(0, 0), radius=10, angle=90.0)
        ys = sorted(v.y for v in tri.points)
        self.assertAlmostEqual(ys[0], ys[1], places=5)  # two base verts share y
        self.assertGreater(ys[2], ys[0])  # apex above base
        base = [v for v in tri.points if abs(v.y - ys[0]) < 1e-5]
        self.assertEqual(len(base), 2)
        self.assertAlmostEqual(base[0].x + base[1].x, 0.0, places=5)
        self.assertPointAlmost(tri.points[0], 0, 10, places=5)

    def test_face_motion_flies_apex_first(self):
        tri = EquilateralTriangle(center=(0, 0), radius=10)
        tri.move_by(30, 30, face=True)
        cx, cy = tri._center_xy()
        apex = tri.points[0]
        self.assertAlmostEqual(math.degrees(math.atan2(apex.y - cy, apex.x - cx)), 45.0, places=5)

    def test_vertex_side_model(self):
        tri = EquilateralTriangle(vertex=(0, 0), side=10, angle=0.0)
        self.assertPointAlmost(tri.points[0], 0, 0, places=5)
        # Apex at vertex, pointing right; the center sits behind it.
        self.assertPointAlmost(tri.center, -tri.radius, 0, places=5)

    def test_inherits_regular_polygon_transforms(self):
        tri = EquilateralTriangle(center=(0, 0), side=10)
        tri.move_by(5, 5)
        self.assertPointAlmost(tri.center, 5, 5)
        tri.scale_by(2)
        self.assertNumAlmost(tri.side, 20.0, places=4)


# ---------------------------------------------------------------------------
# move_to default center + about= (Unify move_to on center)
# ---------------------------------------------------------------------------
def _heading_deg(dx, dy):
    return math.degrees(math.atan2(float(dy), float(dx)))


def _ang_close(got, expect, tol=0.5):
    d = abs((float(got) - float(expect) + 180.0) % 360.0 - 180.0)
    return d <= tol


class TestMoveToAnchor(ShapeTestCase):
    def test_vertex_side_move_to_places_center(self):
        poly = RegularPolygon(n=5, vertex=(10, 0), side=20, angle=0.0)
        cx0, cy0 = poly._center_xy()
        self.assertGreater(math.hypot(cx0 - 10.0, cy0 - 0.0), 1.0)
        poly.move_to(100, 80)
        cx, cy = poly._center_xy()
        self.assertAlmostEqual(cx, 100.0, places=5)
        self.assertAlmostEqual(cy, 80.0, places=5)
        self.assertGreater(math.hypot(poly.vertex.x - 100.0, poly.vertex.y - 80.0), 1.0)

    def test_equilateral_vertex_side_move_to_places_center(self):
        tri = EquilateralTriangle(vertex=(0, 0), side=60, angle=0.0)
        self.assertGreater(abs(tri._center_xy()[0]), 1.0)
        tri.move_to(100, 100)
        cx, cy = tri._center_xy()
        self.assertAlmostEqual(cx, 100.0, places=5)
        self.assertAlmostEqual(cy, 100.0, places=5)
        self.assertGreater(math.hypot(tri.vertex.x - 100.0, tri.vertex.y - 100.0), 1.0)

    def test_vertex_side_about_vertex_reproduces_old_default(self):
        poly = RegularPolygon(n=5, vertex=(10, 0), side=20, angle=0.0)
        poly.move_to(100, 80, about=poly.vertex)
        self.assertPointAlmost(poly.vertex, 100, 80, places=5)

    def test_circle_about_center_matches_default(self):
        a = Circle(center=(10, 20), radius=5)
        b = Circle(center=(10, 20), radius=5)
        a.move_to(40, 50)
        b.move_to(40, 50, about=b.center)
        self.assertPointAlmost(a.center, 40, 50)
        self.assertPointAlmost(b.center, 40, 50)

    def test_rect_about_top_left_lands_on_target(self):
        r = Rect(center=(0, 0), width=20, height=10)
        tlx, tly = float(r.top_left.x), float(r.top_left.y)
        r.move_to(100, 50, about=r.top_left)
        self.assertPointAlmost(r.top_left, 100, 50, places=5)
        self.assertPointAlmost(r.center, 100 - tlx, 50 - tly, places=5)

    def test_partial_move_to_about_preserves_other_axis(self):
        r = Rect(center=(0, 0), width=20, height=10)
        tly = float(r.top_left.y)
        r.move_to(x=40, y=None, about=r.top_left)
        self.assertAlmostEqual(float(r.top_left.x), 40.0, places=5)
        self.assertAlmostEqual(float(r.top_left.y), tly, places=5)
        r.move_to(x=None, y=25, about=r.top_left)
        self.assertAlmostEqual(float(r.top_left.x), 40.0, places=5)
        self.assertAlmostEqual(float(r.top_left.y), 25.0, places=5)

    def test_about_does_not_bypass_linked_defining_parts(self):
        src = Point(10, 10)
        r = Rect(center=(10, 10), width=20, height=10)
        r.center @= src
        with self.assertRaises(LinkedAttributeError):
            r.move_to(50, 50, about=r.top_left)
        r.move_to(50, 50, about=r.top_left, force=True)
        self.assertPointAlmost(r.top_left, 50, 50, places=5)

    def test_linked_about_point_is_only_read(self):
        src = Attribute(5.0)
        pivot = Point(5, 5)
        pivot["x"] @= src
        r = Rect(center=(0, 0), width=20, height=10)
        r.move_to(50, 40, about=pivot)
        self.assertPointAlmost(r.center, 45, 35, places=5)
        self.assertPointAlmost(pivot, 5, 5)
        self.assertTrue(pivot["x"].is_linked)

    def test_about_face_keeps_anchor_on_target(self):
        r = Rect(center=(0, 0), width=20, height=10)
        r.rotate_to(0)
        tlx, tly = float(r.top_left.x), float(r.top_left.y)
        tx, ty = 80.0, 40.0
        r.move_to(tx, ty, about=r.top_left, face=True)
        self.assertPointAlmost(r.top_left, tx, ty, places=5)
        self.assertTrue(_ang_close(r.angle, _heading_deg(tx - tlx, ty - tly), tol=0.5))

    def test_blank_about_is_a_noop(self):
        from scena.shapes import Blank
        b = Blank()
        self.assertIs(b.move_to(10, 20, about=(0, 0)), b)


# ---------------------------------------------------------------------------
# Draggable / wheel_rotate vs linked pose
# ---------------------------------------------------------------------------
class TestInteractiveLinkInvariant(ShapeTestCase):
    def test_linked_center_blocks_draggable(self):
        src = Point(10, 20)
        c = Circle(center=(0, 0), radius=5)
        c.center @= src
        with self.assertRaises(LinkedAttributeError):
            c.draggable = True

    def test_draggable_blocks_linking_center(self):
        src = Point(10, 20)
        c = Circle(center=(0, 0), radius=5)
        c.draggable = True
        with self.assertRaises(LinkedAttributeError):
            c.center @= src

    def test_linked_radius_allows_draggable(self):
        r = Attribute(5.0)
        c = Circle(center=(0, 0), radius=5)
        c["radius"] @= r
        c.draggable = True
        self.assertTrue(c.draggable)

    def test_linked_angle_blocks_wheel_rotate(self):
        ang = Attribute(0.0)
        rect = Rect(center=(0, 0), width=10, height=8)
        rect["angle"] @= ang
        with self.assertRaises(LinkedAttributeError):
            rect.wheel_rotate = True

    def test_wheel_rotate_blocks_linking_angle(self):
        ang = Attribute(0.0)
        rect = Rect(center=(0, 0), width=10, height=8)
        rect.wheel_rotate = True
        with self.assertRaises(LinkedAttributeError):
            rect["angle"] @= ang

    def test_linked_center_allows_wheel_rotate_on_rect(self):
        # CENTER_WH wheel_rotate about center only writes angle.
        src = Point(1, 2)
        rect = Rect(center=(0, 0), width=10, height=8)
        rect.center @= src
        rect.wheel_rotate = True
        self.assertTrue(rect.wheel_rotate)

    def test_on_drag_to_runs_draggable_check(self):
        src = Point(10, 20)
        c = Circle(center=(0, 0), radius=5)
        c.center @= src
        with self.assertRaises(LinkedAttributeError):
            c.on_drag_to = lambda *a: None

    def test_anchor_rejects_inbound_link(self):
        from scena.shapes import Anchor
        a = Anchor(0, 0)
        src = Point(5, 5)
        with self.assertRaises(LinkedAttributeError):
            a.center @= src
        with self.assertRaises(LinkedAttributeError):
            a["x"] @= Attribute(3.0)

    def test_anchor_outbound_link_ok(self):
        from scena.shapes import Anchor
        a = Anchor(10, 20)
        b = Anchor(30, 40)
        line = Line(p1=lambda: a.center, p2=lambda: b.center)
        self.assertIsNotNone(line.p1._link)
        self.assertIsNotNone(line.p2._link)
        a.move_to(15, 25)
        self.assertPointAlmost(line.p1, 15, 25)

    def test_anchor_bare_center_is_a_snapshot(self):
        """Construction copies a bare ``a.center`` (or ``a``): the line stays put.

        The Anchor docstring once showed ``Line(p1=a.center, …)`` as a link.
        """
        a = Anchor(100, 100)
        by_part = Line(p1=a.center, p2=(300, 100))
        by_anchor = Line(p1=a, p2=(300, 100))
        a.move_to(150, 120)
        self.assertPointAlmost(by_part.p1, 100, 100)
        self.assertPointAlmost(by_anchor.p1, 100, 100)
        self.assertIsNone(by_part.p1._link)

    def test_anchor_docstring_example_follows_the_drag(self):
        """The ``Example:`` in ``Anchor.__doc__`` runs and its Line tracks ``a``."""
        import inspect
        import textwrap
        doc = inspect.getdoc(Anchor)
        body = doc.split("Example:", 1)[1].split("\n\n", 1)[0]
        scope = {"Anchor": Anchor, "Line": Line}
        exec(textwrap.dedent(body).replace("Line(", "line = Line(", 1), scope)
        scope["a"].move_to(10, 20)
        self.assertPointAlmost(scope["line"].p1, 10, 20)

    def test_anchor_construction_copies_attribute_value(self):
        from scena.shapes import Anchor
        src = Point(1, 2)
        a = Anchor(src.x, 0)
        self.assertEqual(a.x, 1.0)
        self.assertFalse(a["x"].is_linked)
        src.x = 99
        self.assertEqual(a.x, 1.0)

    def test_circle_property_anchor_rotation_blocks_wheel_rotate(self):
        """PropertyAnchor-backed rotation uses the same parts list as ScalarSlot."""
        ang = Attribute(0.0)
        c = Circle(center=(0, 0), radius=5)
        c["angle"] @= ang
        with self.assertRaises(LinkedAttributeError):
            c.wheel_rotate = True

    def test_wheel_rotate_blocks_circle_property_anchor_rotation(self):
        ang = Attribute(0.0)
        c = Circle(center=(0, 0), radius=5)
        c.wheel_rotate = True
        with self.assertRaises(LinkedAttributeError):
            c["angle"] @= ang

    def test_polygon_property_anchor_rotation_vs_wheel_rotate(self):
        from scena.shapes import Polygon
        ang = Attribute(0.0)
        poly = Polygon(points=[(0, 0), (10, 0), (5, 8)])
        poly.wheel_rotate = True
        with self.assertRaises(LinkedAttributeError):
            poly["angle"] @= ang
        poly.wheel_rotate = False
        poly["angle"] @= ang
        with self.assertRaises(LinkedAttributeError):
            poly.wheel_rotate = True

    def test_sprite_property_anchor_rotation_vs_wheel_rotate(self):
        import warnings
        from scena.sprite import Sprite
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            s = Sprite("missing_for_test.png", center=(0, 0))
        s.wheel_rotate = True
        with self.assertRaises(LinkedAttributeError):
            s["angle"] @= Attribute(0.0)

    def test_linked_scale_allows_wheel_rotate_today(self):
        """scale is PropertyAnchor-backed but no gesture writes it yet."""
        c = Circle(center=(0, 0), radius=5)
        c["scale"] @= Attribute(1.0)
        c.wheel_rotate = True
        self.assertTrue(c.wheel_rotate)


# ---------------------------------------------------------------------------
# Constructor line_width
# ---------------------------------------------------------------------------
class TestConstructorLineWidth(ShapeTestCase):
    def test_line_stores_line_width_and_omission_keeps_prototype(self):
        thick = Line(p1=(0, 0), p2=(10, 0), line_width=5)
        plain = Line(p1=(0, 0), p2=(10, 0))
        self.assertAlmostEqual(float(thick.line_width), 5.0, places=4)
        self.assertAlmostEqual(float(plain.line_width), 1.5, places=4)

    def test_circle_stores_line_width(self):
        c = Circle(center=(0, 0), radius=10, line_width=4)
        self.assertAlmostEqual(float(c.line_width), 4.0, places=4)

    def test_polygon_stores_line_width(self):
        poly = Polygon(
            points=[(0, 0), (10, 0), (0, 10)],
            line_width=3,
        )
        self.assertAlmostEqual(float(poly.line_width), 3.0, places=4)

    def test_point_and_anchor_reject_line_width(self):
        with self.assertRaises(TypeError):
            Point(0, 0, line_width=3)
        with self.assertRaises(TypeError):
            Anchor(0, 0, line_width=3)

    def test_line_clone_keeps_line_width(self):
        copy = Line(p1=(0, 0), p2=(10, 0), line_width=5).clone()
        self.assertAlmostEqual(float(copy.line_width), 5.0, places=4)

    def test_stroke_and_fill_kwargs_still_rejected(self):
        with self.assertRaises(TypeError):
            Line(p1=(0, 0), p2=(10, 0), stroke="cyan")
        with self.assertRaises(TypeError):
            Circle(center=(0, 0), radius=10, fill="navy")


# ---------------------------------------------------------------------------
# clone()
# ---------------------------------------------------------------------------
class TestShapeClone(ShapeTestCase):
    def test_circle_clone_copies_geometry_and_style_without_links(self):
        src = Point(10, 20)
        c = Circle(center=(0, 0), radius=15)
        c.set_color("red")
        c.center @= src
        copy = c.clone(scale=2.0)
        self.assertIsNot(copy, c)
        self.assertIsNone(copy.center._link)
        self.assertPointAlmost(copy.center, 10, 20)
        self.assertNumAlmost(copy.radius, 30)
        self.assertEqual(str(copy.fill), str(c.fill))

    def test_rect_clone_preserves_angle_in_degrees(self):
        r = Rect(center=(5, 5), width=40, height=20, angle=45)
        copy = r.clone()
        self.assertNumAlmost(copy.angle, 45)
        self.assertPointAlmost(copy.center, 5, 5)

    def test_point_clone_is_on_canvas_not_ephemeral(self):
        p = Point(3, 4)
        copy = p.clone()
        self.assertFalse(getattr(copy, '_ephemeral', False))
        self.assertPointAlmost(copy, 3, 4)

    def test_anchor_clone_stays_anchor(self):
        from scena.shapes import Anchor
        a = Anchor(1, 2, color="cyan")
        copy = a.clone()
        self.assertIsInstance(copy, Anchor)
        self.assertTrue(copy.handle)
        self.assertTrue(copy.draggable)
        self.assertEqual(copy.layer, 'top')
        self.assertTrue(copy.visible)

    def test_clone_copies_groups_unless_overridden(self):
        c = Circle(center=(0, 0), radius=10, group="fleet")
        c.tag("shielded")
        copy = c.clone()
        self.assertIn("fleet", copy.group)
        self.assertIn("shielded", copy.group)
        other = c.clone(group="other")
        self.assertEqual(other.group, {"other"})
        self.assertNotIn("fleet", other.group)

    def test_clone_layer_none_is_undrawn(self):
        from scena import canvas
        c = Circle(center=(0, 0), radius=10, group="fleet", layer=None)
        on_default = c.clone()
        self.assertEqual(on_default.layer, canvas.layers.default)
        self.assertIn("fleet", on_default.group)
        undrawn = c.clone(layer=None)
        self.assertIsNone(undrawn.layer)
        on_top = c.clone(layer="top")
        self.assertEqual(on_top.layer, "top")

    def test_subclass_clone_keeps_type_and_setup(self):
        setups = []

        class Bolt(Circle):
            def setup(self):
                setups.append(self)
                self.hp = 3

            def on_update(self, dt):
                self.move_by(0, dt)

        src = Bolt(center=(0, 0), radius=8, group="bolt")
        self.assertEqual(len(setups), 1)
        copy = src.clone()
        self.assertIsInstance(copy, Bolt)
        self.assertIsNot(copy, src)
        self.assertEqual(len(setups), 2)
        self.assertEqual(float(copy.hp), 3)
        self.assertIn("bolt", copy.group)
        self.assertIsNotNone(copy.on_update)


# ---------------------------------------------------------------------------
# Shape class defaults
# ---------------------------------------------------------------------------
class TestShapeClassDefaults(ShapeTestCase):
    def test_class_radius_color_group_on_home_spawn(self):
        class Bolt(Circle, radius=8, color="gold", group="bolt"):
            pass

        b = Bolt(center=(100, 200))
        self.assertPointAlmost(b.center, 100, 200)
        self.assertNumAlmost(b.radius, 8)
        self.assertIn("bolt", b.group)
        from scena.color import Color
        self.assertIsInstance(b.fill, Color)
        r, g, _b, _a = b.fill.rgb
        self.assertAlmostEqual(r, 1.0, places=2)
        self.assertAlmostEqual(g, 0.843, places=2)
        # Empty construct uses class radius at canvas center.
        from scena.shapes import _default_pose
        (cx, cy), _ = _default_pose()
        b2 = Bolt()
        self.assertNumAlmost(b2.radius, 8)
        self.assertPointAlmost(b2.center, cx, cy)

    def test_expert_path_ignores_class_size_keeps_style(self):
        class Shot(Circle, radius=8, color="gold"):
            pass

        d = Shot(p1=(0, 0), p2=(10, 0))
        self.assertEqual(d.model, CircleModel.TWO_POINTS)
        self.assertNumAlmost(d.radius, 5.0)  # diameter, not class 8
        # color= still applied on expert path
        self.assertIsNotNone(d.fill)

    def test_placement_and_wrong_family_class_kwargs_raise(self):
        with self.assertRaises(TypeError) as ctx:
            class Bad(Circle, center=(0, 0)):  # noqa: F841
                pass
        self.assertIn("placement", str(ctx.exception).lower())
        with self.assertRaises(TypeError) as ctx:
            class BadRect(Rect, radius=8):  # noqa: F841
                pass
        self.assertIn("radius", str(ctx.exception))
        self.assertIn("Circle", str(ctx.exception))

    def test_instance_kwargs_win_over_class(self):
        class Bolt(Circle, radius=8, color="gold"):
            pass

        b = Bolt(center=(0, 0), radius=12, color="tomato")
        self.assertNumAlmost(b.radius, 12)

    def test_regular_polygon_class_n(self):
        class Hex(RegularPolygon, n=6, radius=20):
            pass

        h = Hex(center=(0, 0))
        self.assertEqual(h._n, 6)
        self.assertNumAlmost(h.radius, 20)

    def test_brick_class_size_completes_partial_instance(self):
        class Brick(Rect, width=90, height=36, color="sienna"):
            pass

        # Class height supplies the missing half of the size pair.
        b = Brick(width=180)
        self.assertNumAlmost(b.width, 180)
        self.assertNumAlmost(b.height, 36)
        b2 = Brick(center=(10, 20))
        self.assertPointAlmost(b2.center, 10, 20)
        self.assertNumAlmost(b2.width, 90)
        self.assertNumAlmost(b2.height, 36)

    def test_class_default_rotation(self):
        class Brick(Rect, width=90, height=36, angle=15):
            pass

        b = Brick()
        self.assertNumAlmost(b.width, 90)
        self.assertNumAlmost(b.height, 36)
        self.assertNumAlmost(b.angle, 15)

    def test_rotation_kwarg_is_retired(self):
        # The heading is angle= on every Graphic; rotation= names the fix.
        for build in (
            lambda: Rect(center=(0, 0), width=10, height=10, rotation=30),
            lambda: Square(center=(0, 0), length=10, rotation=15),
            lambda: EquilateralTriangle(center=(0, 0), radius=10, rotation=0),
            lambda: Ellipse(center=(0, 0), width=10, height=4, rotation=5),
            lambda: Line(center=(0, 0), length=10, rotation=5),
            lambda: Circle(center=(0, 0), radius=4, rotation=5),
        ):
            with self.assertRaises(TypeError) as ctx:
                build()
            self.assertIn("angle=", str(ctx.exception))
        with self.assertRaises(TypeError) as ctx:
            class Slant(Rect, width=10, height=8, rotation=20):  # noqa: F841
                pass
        self.assertIn("angle=", str(ctx.exception))
        for cls in (Rect, Ellipse, RegularPolygon, Line, Circle):
            self.assertFalse(hasattr(cls, "rotation"), cls.__name__)

    def test_line_class_length(self):
        class Beam(Line, length=80, angle=0, color="cyan"):
            pass

        beam = Beam(center=(50, 60))
        self.assertEqual(beam.model, LineModel.CENTER_LENGTH_ANGLE)
        self.assertPointAlmost(beam.center, 50, 60)
        self.assertNumAlmost(beam.length, 80)


class TestTakeinAndAbsorb(ShapeTestCase):
    def test_lshift_is_takein_only(self):
        a = Circle(center=(10, 10), radius=5)
        b = Circle(center=(40, 50), radius=12)
        a << b
        self.assertPointAlmost(a.center, 40, 50)
        self.assertAlmostEqual(a.radius, 12)
        self.assertTrue(b.is_alive)
        self.assertPointAlmost(b.center, 40, 50)

    def test_absorb_takein_and_destroys(self):
        a = Circle(center=(10, 10), radius=5)
        b = Circle(center=(40, 50), radius=12)
        a.absorb(b)
        self.assertPointAlmost(a.center, 40, 50)
        self.assertAlmostEqual(a.radius, 12)
        self.assertFalse(b.is_alive)

    def test_lshift_raises_when_leaf_linked(self):
        src = Circle(center=(0, 0), radius=4)
        a = Circle(center=(10, 10), radius=5)
        b = Circle(center=(40, 50), radius=12)
        a.center["x"] @= lambda: src.center.x
        with self.assertRaises(LinkedAttributeError):
            a << b
        self.assertPointAlmost(a.center, 0, 10)
        a.unlink_all()
        a << b
        self.assertPointAlmost(a.center, 40, 50)

    def test_absorb_raises_when_child_linked(self):
        src = Circle(center=(0, 0), radius=4)
        a = Circle(center=(10, 10), radius=5)
        b = Circle(center=(40, 50), radius=12)
        a["radius"] @= lambda: src.radius
        with self.assertRaises(LinkedAttributeError):
            a.absorb(b)
        self.assertTrue(b.is_alive)
        a["radius"].unlink()
        a.absorb(b)
        self.assertAlmostEqual(a.radius, 12)
        self.assertFalse(b.is_alive)

    def test_center_assign_raises_when_leaf_linked(self):
        src = Point(1, 0)
        c = Circle(center=(10, 10), radius=5)
        c.center["x"] @= lambda: src.x
        with self.assertRaises(LinkedAttributeError):
            c.center = (0, 0)
        self.assertAlmostEqual(c.center.x, 1.0)
        c.center["x"].unlink()
        c.center = (0, 0)
        self.assertPointAlmost(c.center, 0, 0)

    def test_leaf_assign_raises_when_center_linked(self):
        src = Point(8, 9)
        c = Circle(center=(10, 10), radius=5)
        c["center"] @= src
        with self.assertRaises(LinkedAttributeError):
            c.center.x = 0
        self.assertAlmostEqual(c.center.x, 8.0)


class TestConstructorCallableLink(ShapeTestCase):
    """Bare args copy; callables install a live link (scalar and composite)."""

    def test_bare_container_copies_does_not_track(self):
        player = Circle(center=(400, 300), radius=20)
        c = Circle(center=player.center, radius=12)
        self.assertIsNone(c.center._link)
        player.center._takein((0, 0))
        self.assertPointAlmost(c.center, 400, 300)

    def test_callable_composite_and_scalar_link(self):
        player = Circle(center=(400, 300), radius=20)
        player.hp = 5
        c = Circle(center=lambda: player.center, radius=lambda: player.hp * 10)
        self.assertIsNotNone(c.center._link)
        self.assertTrue(c["radius"].is_linked)
        self.assertAlmostEqual(c.radius, 50.0)
        player.center._takein((10, 20))
        player.hp = 7
        self.assertPointAlmost(c.center, 10, 20)
        self.assertAlmostEqual(c.radius, 70.0)

    def test_plain_assign_on_linked_composite_raises(self):
        player = Circle(center=(400, 300), radius=20)
        c = Circle(center=lambda: player.center, radius=12)
        with self.assertRaises(LinkedAttributeError):
            c.center = (0, 0)
        self.assertPointAlmost(c.center, 400, 300)
        c["center"].unlink()
        c.center = (0, 0)
        self.assertPointAlmost(c.center, 0, 0)

    def test_plain_assign_on_linked_scalar_raises(self):
        player = Circle(center=(0, 0), radius=20)
        c = Circle(center=(0, 0), radius=lambda: player.radius)
        with self.assertRaises(LinkedAttributeError):
            c.radius = 1
        self.assertAlmostEqual(c.radius, 20.0)
        c["radius"].unlink()
        c.radius = 1
        self.assertAlmostEqual(c.radius, 1.0)

    def test_multi_kwarg_lambdas_isolate_sources(self):
        """Two lambdas on one constructor line must not merge FormulaLink sources."""
        a = Circle(center=(10, 0), radius=5)
        b = Circle(center=(0, 20), radius=7)
        c = Circle(center=lambda: a.center, radius=lambda: b.radius)
        center_sources = set(c.center._link.sources)
        radius_anchor = c._ensure_scalar_anchor('radius')
        radius_sources = set(radius_anchor._link.sources)
        self.assertIn(a.center, center_sources)
        self.assertNotIn(b, center_sources)
        self.assertNotIn(b.center, center_sources)
        # radius formula depends on b (outermost) — not on a
        self.assertTrue(any(s is b or getattr(s, '_owner', None) is b for s in radius_sources) or b in radius_sources)
        self.assertNotIn(a, radius_sources)
        self.assertNotIn(a.center, radius_sources)

    def test_polygon_mixed_callable_and_bare(self):
        anchor = Point(100, 100)
        poly = Polygon(points=[lambda: anchor, (0, 0), (5, 0)])
        self.assertIsNotNone(poly.points[0]._link)
        self.assertIsNone(poly.points[1]._link)
        anchor.move_to(50, 50)
        self.assertPointAlmost(poly.points[0], 50, 50)
        self.assertPointAlmost(poly.points[1], 0, 0)


class TestIsCollapsed(ShapeTestCase):
    def test_circle_radius_zero(self):
        self.assertTrue(Circle(center=(0, 0), radius=0).is_collapsed)
        self.assertFalse(Circle(center=(0, 0), radius=10).is_collapsed)

    def test_ellipse_one_axis_zero(self):
        self.assertTrue(Ellipse(center=(0, 0), width=40, height=0).is_collapsed)
        self.assertTrue(Ellipse(center=(0, 0), width=0, height=20).is_collapsed)
        self.assertFalse(Ellipse(center=(0, 0), width=40, height=20).is_collapsed)

    def test_square_and_regular_polygon_zero(self):
        self.assertTrue(Square(center=(0, 0), length=0).is_collapsed)
        self.assertFalse(Square(center=(0, 0), length=20).is_collapsed)
        self.assertTrue(RegularPolygon(n=6, center=(0, 0), radius=0).is_collapsed)
        self.assertFalse(RegularPolygon(n=6, center=(0, 0), radius=10).is_collapsed)

    def test_point_is_not_collapsed(self):
        self.assertFalse(Point(3, 4).is_collapsed)
        self.assertFalse(Point().is_collapsed)


# ---------------------------------------------------------------------------
# Reactive rotation / scale — per-model equivalence with rotate_to / scale_to
# ---------------------------------------------------------------------------
def _pose_snapshot(shape):
    from scena.collision import _collision_pose_key

    snap = {
        "angle": float(shape.angle),
        "scale": float(shape.scale),
        "pose_key": _collision_pose_key(shape),
    }
    center = getattr(shape, "center", None)
    if center is shape:
        snap["xy"] = (float(shape.x), float(shape.y))
    elif center is not None:
        snap["xy"] = (float(center.x), float(center.y))
    for name in ("angle",):
        if hasattr(type(shape), name):
            try:
                snap[name] = float(getattr(shape, name))
            except Exception:
                pass
    verts = getattr(shape, "_vertices", None)
    if verts:
        snap["verts"] = [get_xy(v, bare=True) for v in verts]
    return snap


class TestReactiveRotationScaleEquivalence(ShapeTestCase):
    """Linking rotation/scale to a constant matches calling rotate_to/scale_to."""

    def _assert_snap_equal(self, a, b, places=5, *, skip_private_rotation=False):
        self.assertAlmostEqual(a["angle"], b["angle"], places=places)
        self.assertAlmostEqual(a["scale"], b["scale"], places=places)
        self.assertEqual(len(a["pose_key"]), len(b["pose_key"]))
        # Skip collision epoch (index 0): link install vs scale_to can bump it
        # a different number of times when Derivate angle/width stay cold (A4).
        # Skip private `_rotation` (index 3) on merged classes: a ScalarSlot
        # write does not go through rotate_to, so the hand-maintained mirror
        # may lag; live extras after it (slot / _oriented_frame) must match.
        skip = {0}
        if skip_private_rotation:
            skip.add(3)
        for i, (x, y) in enumerate(zip(a["pose_key"], b["pose_key"])):
            if i in skip:
                continue
            self.assertAlmostEqual(float(x), float(y), places=places)
        if "xy" in a:
            self.assertAlmostEqual(a["xy"][0], b["xy"][0], places=places)
            self.assertAlmostEqual(a["xy"][1], b["xy"][1], places=places)
        for name in ("angle",):
            if name in a and name in b:
                self.assertAlmostEqual(a[name], b[name], places=places)
        if "verts" in a:
            self.assertEqual(len(a["verts"]), len(b["verts"]))
            for (x0, y0), (x1, y1) in zip(a["verts"], b["verts"]):
                self.assertAlmostEqual(x0, x1, places=places)
                self.assertAlmostEqual(y0, y1, places=places)

    def _check_rotation(self, linked, direct, value):
        linked["angle"] @= Attribute(value)
        direct.rotate_to(value)
        self._assert_snap_equal(
            _pose_snapshot(linked),
            _pose_snapshot(direct),
            skip_private_rotation=("angle" in linked._field_slots()),
        )
        self.assertAlmostEqual(linked.angle, value, places=5)

    def _check_scale(self, linked, direct, value):
        linked["scale"] @= Attribute(value)
        direct.scale_to(value)
        self._assert_snap_equal(_pose_snapshot(linked), _pose_snapshot(direct))
        self.assertAlmostEqual(linked.scale, value, places=5)

    def test_rect_center_wh(self):
        self._check_rotation(
            Rect(center=(10, 20), width=40, height=20, angle=0),
            Rect(center=(10, 20), width=40, height=20, angle=0),
            35.0,
        )
        self._check_scale(
            Rect(center=(10, 20), width=40, height=20, angle=15),
            Rect(center=(10, 20), width=40, height=20, angle=15),
            1.5,
        )

    def test_rect_spine_derivate_angle(self):
        kw = dict(p1=(0, 0), p2=(10, 0), height=4, anchor="cap")
        # Derived heading: a link drives rotate_to (it used to raise), like Line.
        self._check_rotation(Rect(**kw), Rect(**kw), 25.0)
        self.assertFalse(hasattr(Rect(**kw), "rotation"))
        self._check_scale(
            Rect(**kw),
            Rect(**kw),
            2.0,
        )

    def test_line_point_point_derivate_angle(self):
        self._check_rotation(
            Line(p1=(0, 0), p2=(10, 0)),
            Line(p1=(0, 0), p2=(10, 0)),
            90.0,
        )

    def test_line_point_vec_derivate_angle(self):
        self._check_rotation(
            Line(p1=(0, 0), vec=Vec2(10, 0)),
            Line(p1=(0, 0), vec=Vec2(10, 0)),
            45.0,
        )

    def test_line_point_dx_dy_derivate_angle(self):
        self._check_rotation(
            Line(p1=(0, 0), dx=10, dy=0),
            Line(p1=(0, 0), dx=10, dy=0),
            30.0,
        )

    def test_ellipse_focal_points_derivate_angle(self):
        kw = dict(fp1=(-3, 0), fp2=(3, 0), major_axis=10)
        # Derived heading: a link drives rotate_to (it used to raise), like Line.
        self._check_rotation(Ellipse(**kw), Ellipse(**kw), 20.0)
        self.assertFalse(hasattr(Ellipse(**kw), "rotation"))
        self._check_scale(Ellipse(**kw), Ellipse(**kw), 1.25)

    def test_circle_polygon_regular_point_blank(self):
        self._check_rotation(
            Circle(center=(0, 0), radius=8),
            Circle(center=(0, 0), radius=8),
            50.0,
        )
        self._check_scale(
            Circle(center=(0, 0), radius=8),
            Circle(center=(0, 0), radius=8),
            2.0,
        )
        pts = [(0, 0), (10, 0), (6, 8)]
        self._check_rotation(Polygon(points=pts), Polygon(points=pts), 15.0)
        self._check_scale(Polygon(points=pts), Polygon(points=pts), 1.5)
        self._check_rotation(
            RegularPolygon(n=5, center=(0, 0), radius=10, angle=0),
            RegularPolygon(n=5, center=(0, 0), radius=10, angle=0),
            18.0,
        )
        p = Point(3, 4)
        p["angle"] @= Attribute(70.0)
        self.assertAlmostEqual(p.angle, 70.0)
        self.assertPointAlmost(p, 3, 4)
        from scena.shapes import Blank
        b = Blank()
        b["angle"] @= Attribute(12.0)
        b["scale"] @= Attribute(2.0)
        # Blank rotate_to / scale_to are no-ops; linking is still legal.
        self.assertTrue(b["angle"].is_linked)
        self.assertTrue(b["scale"].is_linked)


class TestGeometryEdgeFixes(ShapeTestCase):
    """Contracts from the shapes/tracks edge review. Happy-path geometry stays."""

    def test_line_negative_length_rejected(self):
        with self.assertRaises(ValueError):
            Line(center=(0, 0), length=-10, angle=0)
        with self.assertRaises(ValueError):
            Line(center=(0, 0), length=float("nan"), angle=0)
        with self.assertRaises(ValueError):
            Line(p1=(0, 0), angle=0, length=-1)
        line = Line(center=(0, 0), length=20, angle=0)
        with self.assertRaises(ValueError):
            line.length = -1
        with self.assertRaises(ValueError):
            line.length = float("inf")

    def test_line_scale_negative_raises(self):
        line = Line(center=(10, 0), length=20, angle=0)
        with self.assertRaises(ValueError):
            line.scale_by(-1)
        ray = Line(p1=(0, 0), angle=0, length=10)
        with self.assertRaises(ValueError):
            ray.scale_by(-1, about=ray.p1)

    def test_regpoly_negative_radius_raises(self):
        with self.assertRaises(ValueError):
            RegularPolygon(n=3, center=(0, 0), radius=-10)
        with self.assertRaises(ValueError):
            RegularPolygon(n=4, center=(0, 0), side=-10)

    def test_n_must_be_int(self):
        with self.assertRaises(TypeError):
            RegularPolygon(n=5.9, center=(0, 0), radius=10)
        with self.assertRaises(ValueError):
            RegularPolygon(n=2, center=(0, 0), radius=10)
        with self.assertRaises(ValueError):
            EquilateralTriangle(n=3.9, center=(0, 0), side=10)
        with self.assertRaises(ValueError):
            EquilateralTriangle(n=4, center=(0, 0), side=10)
        tri = EquilateralTriangle(center=(0, 0), side=10)
        self.assertEqual(tri._n, 3)

    def test_regpoly_non_finite_radius_rejected(self):
        with self.assertRaises(ValueError):
            RegularPolygon(n=4, center=(0, 0), radius=float("nan"))
        poly = RegularPolygon(n=4, center=(0, 0), radius=10)
        with self.assertRaises(ValueError):
            poly.radius = float("inf")

    def test_ellipse_major_axis_must_be_finite(self):
        with self.assertRaises(ValueError):
            Ellipse(fp1=(0, 0), fp2=(10, 0), major_axis=float("nan"))
        with self.assertRaises(ValueError):
            Ellipse(fp1=(0, 0), fp2=(10, 0), major_axis=float("inf"))

    def test_spine_zero_length_anchor(self):
        cap = Rect(p1=(5, 5), p2=(5, 5), height=10, anchor="cap")
        square = Rect(p1=(5, 5), p2=(5, 5), height=10, anchor="square")
        side = Rect(p1=(5, 5), p2=(5, 5), height=10, anchor="side_left")
        self.assertTrue(cap.is_collapsed)
        self.assertTrue(side.is_collapsed)
        self.assertFalse(square.is_collapsed)
        _cx, _cy, w, h, _ang = square._oriented_frame()
        self.assertAlmostEqual(w, 10.0)
        self.assertAlmostEqual(h, 10.0)

    def test_tangent_angle_move_by_raises(self):
        circle = Circle(center=(0, 0), radius=10)
        line = Line(circle=circle, at_angle=0.0, length=5)
        with self.assertRaises(LinkedAttributeError):
            line.move_by(1, 1)


class TestPolygonPathCache(unittest.TestCase):
    def test_translate_and_rotate_do_not_rebuild(self):
        import skia
        poly = Polygon(points=[(0, 0), (40, 0), (10, 30)])
        surf = skia.Surface(80, 80)
        poly._geometry_draw(surf.getCanvas())
        key = poly._geom_path_key
        path = poly._geom_path
        poly.move_by(12, -4)
        poly._geometry_draw(surf.getCanvas())
        self.assertEqual(poly._geom_path_key, key)
        self.assertIs(poly._geom_path, path)
        poly.rotate_by(25)
        poly._geometry_draw(surf.getCanvas())
        self.assertEqual(poly._geom_path_key, key)
        self.assertIs(poly._geom_path, path)


class TestCircleArcSpan(ShapeTestCase):
    """Opening stays ``spread`` for any heading, including values reduced mod 360.

    Spinning the old ``theta1``/``theta2`` window with ``% 360`` on both ends
    flipped a long arc into its complement.
    """

    @given(
        angle=hst.floats(
            min_value=-1.0e5, max_value=1.0e5,
            allow_nan=False, allow_infinity=False,
        ),
        spread=hst.floats(
            min_value=0.0, max_value=359.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    def test_outline_span_equals_spread(self, angle, spread):
        from scena.track import shape_outline
        arc = Circle(center=(0, 0), radius=10, angle=angle, spread=spread)
        verts, closed = shape_outline(arc, samples=32)
        self.assertFalse(closed)
        self.assertLess(_ang_dist(_dir_deg(verts[0]), angle - spread / 2.0), 0.05)
        self.assertLess(_ang_dist(_dir_deg(verts[-1]), angle + spread / 2.0), 0.05)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestCopyContract(unittest.TestCase):
    """C7 (graphics review batch 7): a copy carries geometry and pose, keeps a
    free model, and turns a relational model into its free twin."""

    def test_lshift_carries_the_pose(self):
        # SC7 / SB7: << copied geometry, not flips / turns / scale.
        src = Rect(center=(0, 0), width=4, height=2)
        src.rotate_by(400)
        src.flip_x = True
        dst = Rect(center=(9, 9), width=1, height=1)
        dst << src
        self.assertEqual((float(dst.angle), dst.flip_x), (float(src.angle), True))
        src.rotate_to(30)
        dst.rotate_to(30)
        self.assertAlmostEqual(float(dst.p1.x), float(src.p1.x))

    def test_clone_keeps_a_free_model(self):
        # SB6: every Line clone was POINT_POINT, so clone().length = 20 raised.
        from scena import Ellipse
        from scena.shapes import LineModel
        for line in (Line(center=(0, 0), length=40, angle=30), Line(p1=(0, 0), angle=10, length=5)):
            copy = line.clone()
            self.assertIs(copy.model, line.model)
            copy.length = 20
            self.assertAlmostEqual(float(copy.length), 20.0)
        e = Ellipse(fp1=(-3, 0), fp2=(3, 0), major_axis=10)
        self.assertIs(e.clone().model, e.model)

    def test_a_relational_copy_is_free(self):
        # SB5: << / clone / force=True kept a relational model without links.
        from scena.shapes import LineModel
        c = Circle(center=(0, 0), radius=10)
        tangent = Line(circle=c, at_angle=0, length=20)
        for copy in (tangent.clone(), Line(p1=(0, 0), p2=(1, 1))):
            if copy.model is LineModel.POINT_POINT:
                copy << tangent
            self.assertIs(copy.model, LineModel.POINT_ANGLE_LENGTH)
            self.assertIsNone(copy._ref)
            x0 = float(copy.p1.x)
            copy.move_by(5, 0)
            self.assertAlmostEqual(float(copy.p1.x), x0 + 5)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tangent.move_by(5, 0, force=True)
        self.assertIs(tangent.model, LineModel.POINT_ANGLE_LENGTH)
        self.assertAlmostEqual(float(tangent.p1.x), 15.0)

    def test_polygon_takes_a_regular_polygons_vertices(self):
        # SC2: the source's cold vertices read (0, 0).
        rp = RegularPolygon(center=(10, 10), radius=5, n=6)
        poly = Polygon(points=[(0, 0)] * 6)
        poly << rp
        self.assertAlmostEqual(float(poly.points[0].x), 15.0)

    def test_from_points_copies_like_the_constructor(self):
        # SB9: from_points linked a plain point (the constructor copies).
        a, b = Point(0, 0), Point(5, 0)
        copied = Circle.from_points(a, b)
        linked = Circle.from_points(lambda: a, lambda: b)
        a.move_by(10, 0)
        self.assertAlmostEqual(float(copied.center.x), 0.0)
        self.assertAlmostEqual(float(linked.center.x), 10.0)

    def test_clone_of_a_parked_actor_is_visible(self):
        # E9: the clone took the parked (hidden) visible.
        c = Circle(center=(0, 0), radius=3)
        c.active = False
        self.assertTrue(c.clone().visible)


class TestRelationalVerbs(unittest.TestCase):
    """Graphics review batch 8: a relational line's pose verbs keep the relation
    or refuse; none ignores an argument (SB1, SB4)."""

    def setUp(self):
        self.circle = Circle(center=(0, 0), radius=10)

    def test_a_tangent_from_a_point_orbits_its_circle(self):
        # SB1: the turn pivoted on the from-point; rotate_by(30) turned it 14.6°.
        line = Line(circle=self.circle, from_point=(30, 0), side="left")
        a0 = float(line.angle)
        line.rotate_by(30)
        self.assertAlmostEqual(float(line.angle), a0 + 30, places=6)
        self.assertAlmostEqual(math.hypot(line.p1.x, line.p1.y), 30.0, places=6)
        with self.assertRaises(LinkedAttributeError):
            line.scale_by(2)                      # it shrank the length 49.8 → 8
        with self.assertRaises(LinkedAttributeError):
            line.rotate_by(10, about=(50, 50))

    def test_a_tangent_at_an_angle_reads_one_heading_and_honours_about(self):
        # SB4: angle 290 vs pose -70 (rotate_to(l.angle) added a turn); about= ignored.
        line = Line(circle=self.circle, at_angle=200, length=20)
        self.assertAlmostEqual(float(line.angle), line._rotation_value())
        p1 = (float(line.p1.x), float(line.p1.y))
        line.rotate_to(float(line.angle))
        self.assertAlmostEqual(float(line.p1.x), p1[0], places=6)
        line.rotate_by(30, about=(0, 0))          # the circle's center: an orbit
        with self.assertRaises(LinkedAttributeError):
            line.rotate_by(30, about=(50, 50))
        with self.assertRaises(LinkedAttributeError):
            line.scale_by(2, about=(50, 50))

    def test_point_rotate_to_about_a_pivot_turns_by_the_difference(self):
        # SA4: rotate_to(θ, about=p) put the point at polar angle θ about p.
        p = Point(10, 0)
        p.rotate_by(30)                           # heading 30, still at (10, 0)
        p.rotate_to(90, about=(0, 0))             # turn by 60 about the origin
        self.assertAlmostEqual(float(p.angle), 90.0)
        self.assertAlmostEqual(float(p.x), 10 * math.cos(math.radians(60)), places=6)

    def test_a_second_argument_is_not_dropped(self):
        # SA16: move_to(Point, 50) / move_by(Vec2, 5) ignored the second argument.
        c = Circle(center=(0, 0), radius=3)
        with self.assertRaises(TypeError):
            c.move_by(Vec2(1, 1), 5)
        with self.assertRaises(TypeError):
            c.move_to(Point(1, 1), 50)


class TestPointKeepsItsLayer(unittest.TestCase):
    def test_hide_and_show_keep_the_layer(self):
        # SA13: a Point built on a layer came back on 'top' after hide / show.
        p = Point(1, 1, layer="default")
        p.visible = False
        p.visible = True
        self.assertEqual(p.layer, "default")


class TestCopyDoorsRefuseWhatClonesRefuse(unittest.TestCase):
    """Geometry campaign, wave 1: ``<<`` refuses what ``clone()`` refuses."""

    def test_a_destroyed_source_refuses_every_kind(self):
        # GX12: ``dst << dead`` copied the destroyed shape; ``dead.clone()`` refused.
        import warnings
        import geom_axes as A
        from scena.state import DestroyedError
        wrong = []
        for kind in sorted(A.K):
            if kind.startswith("Box") or kind.endswith("reversed") or A.family(kind) in ("Sprite", "Svg", "Text"):
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                src, dst = A.build(kind), A.build(kind)
                if __import__("geometry_support").is_relational(dst):
                    A._destroy(dst)
                    continue            # a relational shape refuses every copy (linked)
                src.destroy()
                before = {n: f() for n, f in __import__("geometry_support").point_parts(dst).items()
                          if not n.startswith("box.")}
                try:
                    dst << src
                    wrong.append(f"{kind}: accepted")
                except DestroyedError:
                    pass
                after = {n: f() for n, f in __import__("geometry_support").point_parts(dst).items()
                         if not n.startswith("box.")}
                if after != before:
                    wrong.append(f"{kind}: the refusal changed the copy")
                A._destroy(dst)
        self.assertEqual(wrong, [])

    def test_a_kind_without_a_copy_refuses_with_the_fix(self):
        # GX9: Sprite / Svg / Text << other leaked NotImplementedError("Subclasses must implement takein").
        import geom_axes as A
        for kind in ("Sprite", "Svg", "Text center", "Text top_left"):
            a, b = A.build(kind), A.build(kind)
            with self.assertRaises(TypeError) as ctx:
                a << b
            self.assertIn("clone()", str(ctx.exception))
            for o in (a, b):
                o.destroy()

    def test_a_link_refused_for_wheel_rotate_installs_nothing(self):
        # GX11: the property-anchor path made the angle anchor (and its graph
        # node) before the wheel_rotate conflict refused the link.
        import warnings
        from scena import Polygon, Sprite
        from scena.state import Attribute, LinkedAttributeError, get_scena_system
        g = get_scena_system().dependency_graph
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            subjects = [Polygon(points=[(0, 0), (10, 0), (5, 8)]), Sprite("missing_gx11.png", center=(0, 0))]
        for obj in subjects:
            obj.wheel_rotate = True
            nodes0 = len(list(g.nodes))
            anchors0 = dict(obj.__dict__.get("_field_anchors") or {})
            with self.assertRaises(LinkedAttributeError):
                obj["angle"] @= Attribute(0.0)
            self.assertEqual(dict(obj.__dict__.get("_field_anchors") or {}), anchors0)
            self.assertEqual(len(list(g.nodes)), nodes0)
            obj.destroy()
