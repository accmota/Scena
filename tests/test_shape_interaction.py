"""
Unit tests for Shape pointer interaction: hit-testing, click/drag/drop,
wheel_rotate, hover, decorators, z-order, and Anchor.

Complements the smoke script ``scripts/app_click_drag.py`` and the
draggable/link invariant tests in ``tests.test_shapes``.

Run headless:

    python -m unittest tests.test_shape_interaction -v
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.canvas import ScenaCanvas
from scena.collision import get_collision_system
from scena.geom import intersections
from scena.input import Mouse
from scena.interaction import click, drag_to, drag_over, drop_by
from scena.orchestration import ShapeInteractionManager
from scena.shapes import (
    HIT_PADDING,
    Anchor,
    Circle,
    Ellipse,
    EquilateralTriangle,
    Line,
    Point,
    Polygon,
    Rect,
    RegularPolygon,
    Square,
)


def _registry():
    return ScenaCanvas.get_current().registry


class InteractionTestCase(unittest.TestCase):
    """Each test owns shapes and destroys them so the shared canvas stays clean."""

    _origin = 0

    def setUp(self):
        self.sim = ShapeInteractionManager(_registry())
        self.btn = Mouse.BTN_LEFT
        self._owned = []
        # Unique patch per test so leftover shapes from a failed destroy cannot collide.
        InteractionTestCase._origin += 2000
        self.origin = InteractionTestCase._origin

    def tearDown(self):
        for s in self._owned:
            try:
                s.destroy()
            except Exception:
                pass
        self._owned.clear()

    def track(self, shape):
        self._owned.append(shape)
        return shape

    def at(self, x, y):
        return (self.origin + x, self.origin + y)

    def assertPointAlmost(self, point, x, y, places=5):
        self.assertAlmostEqual(point.x, x, places=places)
        self.assertAlmostEqual(point.y, y, places=places)


# ---------------------------------------------------------------------------
# Flags / registry / decorators
# ---------------------------------------------------------------------------
class TestFlagsAndDecorators(InteractionTestCase):
    def test_callback_setters_toggle_flags(self):
        c = self.track(Circle(center=self.at(0, 0), radius=10))
        self.assertFalse(c.clickable)
        self.assertFalse(c.draggable)
        self.assertFalse(c.droppable)

        c.on_click = lambda s: None
        self.assertTrue(c.clickable)
        c.on_click = None
        self.assertFalse(c.clickable)

        c.on_drag_to = lambda *a: None
        self.assertTrue(c.draggable)
        c.on_drag_to = None
        self.assertFalse(c.draggable)

        c.on_drag_over = lambda *a: None
        self.assertTrue(c.draggable)
        c.on_drag_over = None
        self.assertFalse(c.draggable)

        c.on_drop_by = lambda *a: None
        self.assertTrue(c.droppable)
        c.on_drop_by = None
        self.assertFalse(c.droppable)

    def test_no_interaction_helpers(self):
        c = self.track(Circle(center=self.at(0, 0), radius=10))
        layer = _registry().layers['default']

        c.on_click = lambda s: None
        c.on_drag_to = lambda *a: None
        c.on_drag_over = lambda *a: None
        c.on_drop_by = lambda *a: None
        c.wheel_rotate = True
        self.assertIn(c, layer._interactive)

        self.assertIs(c._no_click(), c)
        self.assertIsNone(c.on_click)
        self.assertFalse(c.clickable)

        self.assertIs(c.no_drag(), c)
        self.assertIsNone(c.on_drag_to)
        self.assertIsNone(c.on_drag_over)
        self.assertFalse(c.draggable)

        self.assertIs(c.no_drop(), c)
        self.assertIsNone(c.on_drop_by)
        self.assertFalse(c.droppable)
        self.assertIn(c, layer._interactive)        # wheel_rotate alone keeps it (SA9)

        self.assertIs(c.no_wheel_rotate(), c)
        self.assertFalse(c.wheel_rotate)
        self.assertNotIn(c, layer._interactive)

        # Flag-only opt-in (no callbacks) is also cleared.
        c.draggable = True
        c.clickable = True
        c.droppable = True
        c.no_drag()._no_click().no_drop()
        self.assertFalse(c.draggable)
        self.assertFalse(c.clickable)
        self.assertFalse(c.droppable)
        self.assertNotIn(c, layer._interactive)

    def test_interactive_registry_membership(self):
        c = self.track(Circle(center=self.at(0, 0), radius=10))
        layer = _registry().layers['default']
        self.assertNotIn(c, layer._interactive)

        c.clickable = True
        self.assertIn(c, layer._interactive)

        c.clickable = False
        self.assertNotIn(c, layer._interactive)

        c.draggable = True
        self.assertIn(c, layer._interactive)
        c.draggable = False
        c.droppable = True
        self.assertIn(c, layer._interactive)

    def test_click_decorator(self):
        ox, oy = self.at(50, 50)
        c = self.track(Circle(center=(ox, oy), radius=15))
        seen = []

        @click(c)
        def on_c(shape):
            seen.append(shape)

        self.assertTrue(c.clickable)
        self.assertTrue(self.sim.handle_mouse_down(ox, oy, self.btn))
        self.assertTrue(self.sim.handle_mouse_up(ox, oy, self.btn))
        self.assertEqual(seen, [c])

    def test_drag_drop_decorators(self):
        tx, ty = self.at(0, 0)
        zx, zy = self.at(100, 0)
        token = self.track(Circle(center=(tx, ty), radius=20))
        zone = self.track(Rect(center=(zx, zy), width=60, height=60))
        events = []

        @drag_to(token)
        def on_to(frm, to, pos):
            events.append(('to', to, pos))

        @drag_over(token)
        def on_over(frm, to, pos):
            events.append(('over', to))

        @drop_by(zone)
        def on_drop(frm, to, pos):
            events.append(('drop', frm, to))

        self.assertTrue(token.draggable)
        self.assertTrue(zone.droppable)

        self.sim.drag_threshold = 1.0
        self.assertTrue(self.sim.handle_mouse_down(tx, ty, self.btn))
        self.assertTrue(self.sim.handle_mouse_move(zx, zy))
        self.assertTrue(self.sim.handle_mouse_up(zx, zy, self.btn))

        kinds = [e[0] for e in events]
        self.assertIn('over', kinds)
        self.assertIn('to', kinds)
        self.assertIn('drop', kinds)
        self.assertIs(events[-1][1], token)
        self.assertIs(events[-1][2], zone)

    def test_no_drop_by_on_a_target_drag_to_destroyed(self):
        # review 2026-10-09 S1-2
        tx, ty = self.at(0, 0)
        zx, zy = self.at(100, 0)
        token = self.track(Circle(center=(tx, ty), radius=20))
        zone = self.track(Rect(center=(zx, zy), width=60, height=60))
        events = []

        @drag_to(token)
        def on_to(frm, to, pos):
            events.append("to")
            to.destroy()                     # the slot is consumed

        @drop_by(zone)
        def on_drop(frm, to, pos):
            events.append("drop")

        self.sim.drag_threshold = 1.0
        self.sim.handle_mouse_down(tx, ty, self.btn)
        self.sim.handle_mouse_move(zx, zy)
        self.sim.handle_mouse_up(zx, zy, self.btn)
        self.assertEqual(events, ["to"])

    def test_group_decorator_registers_members(self):
        from scena import group

        gid = f'ix_grp_{self.origin}'
        ax, ay = self.at(10, 10)
        bx, by = self.at(40, 10)
        a = self.track(Circle(center=(ax, ay), radius=8, group=gid))
        b = self.track(Circle(center=(bx, by), radius=8, group=gid))
        seen = []

        @click(group[gid])
        def on_g(shape):
            seen.append(shape)

        self.assertTrue(a.clickable)
        self.assertTrue(b.clickable)
        self.sim.handle_mouse_down(ax, ay, self.btn)
        self.sim.handle_mouse_up(ax, ay, self.btn)
        self.assertEqual(len(seen), 1)


# ---------------------------------------------------------------------------
# contains_point (design-space hit geometry)
# ---------------------------------------------------------------------------
class TestContainsPoint(InteractionTestCase):
    def test_circle(self):
        c = self.track(Circle(center=self.at(100, 100), radius=20))
        ox, oy = self.at(100, 100)
        self.assertTrue(c.contains_point(ox, oy))
        self.assertTrue(c.contains_point(ox + 20, oy))
        self.assertFalse(c.contains_point(ox + 21, oy))

    def test_rect_axis_aligned(self):
        ox, oy = self.at(100, 100)
        r = self.track(Rect(center=(ox, oy), width=40, height=20))
        self.assertTrue(r.contains_point(ox, oy))
        self.assertTrue(r.contains_point(ox + 19, oy + 9))
        self.assertFalse(r.contains_point(ox + 21, oy))

    def test_point_uses_guide_radius_when_not_handle(self):
        ox, oy = self.at(0, 0)
        p = self.track(Point(ox, oy, layer='default'))
        self.assertFalse(p.handle)
        r = Point.GUIDE_RADIUS
        self.assertTrue(p.contains_point(ox, oy))
        self.assertTrue(p.contains_point(ox + r, oy))
        self.assertFalse(p.contains_point(ox + r + 1, oy))

    def test_point_handle_uses_hover_radius(self):
        ox, oy = self.at(0, 0)
        p = self.track(Point(ox, oy))
        p.handle = True
        r = Point.HANDLE_HOVER_RADIUS
        self.assertTrue(p.contains_point(ox + r, oy))
        self.assertFalse(p.contains_point(ox + r + 1, oy))

    def test_line_segment_padding(self):
        x0, y0 = self.at(0, 0)
        line = self.track(Line(p1=(x0, y0), p2=(x0 + 100, y0)))
        line.line_width = 2
        self.assertTrue(line.contains_point(x0 + 50, y0))
        self.assertTrue(line.contains_point(x0 + 50, y0 + HIT_PADDING))
        self.assertFalse(line.contains_point(x0 + 50, y0 + HIT_PADDING + 2))

    def test_ellipse_polygon_square_regular(self):
        ox, oy = self.at(0, 0)
        e = self.track(Ellipse(center=(ox, oy), width=40, height=20))
        self.assertTrue(e.contains_point(ox, oy))
        self.assertFalse(e.contains_point(ox + 25, oy))

        poly = self.track(Polygon(points=[
            (ox, oy), (ox + 20, oy), (ox + 10, oy + 20),
        ]))
        self.assertTrue(poly.contains_point(ox + 10, oy + 5))
        self.assertFalse(poly.contains_point(ox + 50, oy + 50))

        sq = self.track(Square(center=(ox, oy), length=20))
        self.assertTrue(sq.contains_point(ox, oy))
        self.assertFalse(sq.contains_point(ox + 15, oy))

        reg = self.track(RegularPolygon(
            n=4, center=(ox, oy), radius=20, angle=45,
        ))
        self.assertTrue(reg.contains_point(ox, oy))

    def test_anchor_generous_hover_radius(self):
        ox, oy = self.at(0, 0)
        a = self.track(Anchor(ox, oy))
        self.assertTrue(a.contains_point(ox, oy))
        self.assertTrue(a.contains_point(ox + Anchor.HANDLE_HOVER_RADIUS, oy))
        self.assertFalse(a.contains_point(ox + Anchor.HANDLE_HOVER_RADIUS + 1, oy))
        self.assertGreater(Anchor.HANDLE_HOVER_RADIUS, Anchor.HANDLE_RADIUS)

    def test_accepts_point_likes(self):
        from scena.scenamath import Vec2
        c = self.track(Circle(center=self.at(100, 100), radius=20))
        ox, oy = self.at(100, 100)
        inside = Point(ox + 10, oy)
        outside = Point(ox + 50, oy)
        self.assertTrue(c.contains_point(inside))
        self.assertTrue(c.contains_point((ox + 10, oy)))
        self.assertTrue(c.contains_point(Vec2(ox + 10, oy)))
        mouseish = type("M", (), {"x": ox + 10, "y": oy})()
        self.assertTrue(c.contains_point(mouseish))
        other = self.track(Circle(center=(ox + 10, oy), radius=4))
        self.assertTrue(c.contains_point(other))
        self.assertFalse(c.contains_point(outside))
        self.assertFalse(c.contains_point((ox + 50, oy)))
        self.assertEqual(
            c.contains_point(ox + 10, oy),
            c.contains_point(inside),
        )
        with self.assertRaises(TypeError):
            c.contains_point("nope")

    def test_rounded_rect_pointer_cuts_the_corner(self):
        ox, oy = self.at(0, 0)
        r = self.track(Rect(
            center=(ox, oy), width=100, height=100, corner_radius=30,
        ))
        self.assertTrue(r.contains_point(ox, oy + 49))
        self.assertTrue(r.contains_point(ox + 34, oy + 34))
        self.assertFalse(r.contains_point(ox + 48, oy + 48))
        sharp = self.track(Rect(center=(ox, oy + 200), width=100, height=100))
        self.assertTrue(sharp.contains_point(ox + 48, oy + 248))

    def test_rounded_rect_pointer_follows_rotation(self):
        ox, oy = self.at(0, 0)
        r = self.track(Rect(
            center=(ox, oy), width=100, height=100,
            corner_radius=30, angle=45,
        ))
        rad = math.radians(45)
        lx, ly = 48.0, 48.0
        self.assertFalse(r.contains_point(
            ox + lx * math.cos(rad) - ly * math.sin(rad),
            oy + lx * math.sin(rad) + ly * math.cos(rad),
        ))
        self.assertTrue(r.contains_point(ox, oy))

    def test_square_inherits_rounded_pointer(self):
        ox, oy = self.at(0, 0)
        sq = self.track(Square(center=(ox, oy), length=100, corner_radius=30))
        self.assertFalse(sq.contains_point(ox + 48, oy + 48))
        self.assertTrue(sq.contains_point(ox, oy + 49))

    def test_rounded_collision_stays_the_box(self):
        ox, oy = self.at(0, 0)
        r = self.track(Rect(
            center=(ox, oy), width=100, height=100, corner_radius=30,
            group="roundbox",
        ))
        r.collidable = True
        self.assertFalse(r.contains_point(ox + 48, oy + 48))
        self.assertIn(r, get_collision_system().query_point(ox + 48, oy + 48))

    def test_circle_pie_pointer_matches_the_fill(self):
        ox, oy = self.at(0, 0)
        pie = self.track(Circle(
            center=(ox, oy), radius=40, angle=0, spread=90,
        ))
        pie.collidable = True
        self.assertTrue(pie.contains_point(ox + 20, oy))
        self.assertTrue(pie.contains_point(ox, oy))
        self.assertFalse(pie.contains_point(ox - 25, oy))
        self.assertFalse(pie.contains_point(ox, oy + 30))
        system = get_collision_system()
        self.assertIn(pie, system.query_point(ox + 20, oy))
        self.assertNotIn(pie, system.query_point(ox - 25, oy))

    def test_circle_chord_segment_pointer(self):
        ox, oy = self.at(0, 0)
        minor = self.track(Circle(
            center=(ox, oy), radius=40, angle=0, spread=90, use_center=False,
        ))
        self.assertFalse(minor.contains_point(ox, oy))
        self.assertTrue(minor.contains_point(ox + 36, oy))
        self.assertFalse(minor.contains_point(ox - 20, oy))
        wide = self.track(Circle(
            center=(ox, oy + 200), radius=40, angle=0, spread=270, use_center=False,
        ))
        self.assertTrue(wide.contains_point(ox, oy + 200))
        self.assertFalse(wide.contains_point(ox - 38, oy + 200))

    def test_circle_spread_zero_misses_and_full_turn_is_the_disk(self):
        ox, oy = self.at(0, 0)
        empty = self.track(Circle(center=(ox, oy), radius=40, spread=0))
        self.assertFalse(empty.contains_point(ox, oy))
        self.assertFalse(empty.contains_point(ox + 10, oy))
        full = self.track(Circle(center=(ox, oy + 100), radius=40, spread=360))
        self.assertTrue(full.contains_point(ox + 20, oy + 100))
        self.assertFalse(full.contains_point(ox + 41, oy + 100))

    def test_circle_outline_ignores_the_arc(self):
        ox, oy = self.at(0, 0)
        pie = self.track(Circle(center=(ox, oy), radius=10, angle=0, spread=90))
        line = self.track(Line(p1=(ox - 20, oy), p2=(ox + 20, oy)))
        xs = sorted(p[0] - ox for p in intersections(pie, line))
        self.assertEqual(len(xs), 2)
        self.assertAlmostEqual(xs[0], -10.0, places=3)
        self.assertAlmostEqual(xs[1], 10.0, places=3)


# ---------------------------------------------------------------------------
# Hit-test order, visibility, pressable vs droppable
# ---------------------------------------------------------------------------
class TestHitTest(InteractionTestCase):
    def test_skips_invisible(self):
        ox, oy = self.at(0, 0)
        c = self.track(Circle(center=(ox, oy), radius=30))
        c.clickable = True
        c.visible = False
        self.assertIsNone(self.sim.hit_test(ox, oy, pressable=True))

    def test_skips_non_interactive(self):
        ox, oy = self.at(0, 0)
        self.track(Circle(center=(ox, oy), radius=30))
        self.assertIsNone(self.sim.hit_test(ox, oy, pressable=True))

    def test_pressable_ignores_droppable_only(self):
        ox, oy = self.at(0, 0)
        zone = self.track(Rect(center=(ox, oy), width=40, height=40))
        zone.droppable = True
        self.assertIsNone(self.sim.hit_test(ox, oy, pressable=True))
        self.assertIs(self.sim.hit_test(ox, oy, droppable=True), zone)

    def test_top_layer_over_default(self):
        ox, oy = self.at(0, 0)
        under = self.track(Circle(center=(ox, oy), radius=40))
        over = self.track(Circle(
            center=(ox, oy), radius=40, layer='top',
        ))
        under.clickable = True
        over.clickable = True
        self.assertIs(self.sim.hit_test(ox, oy, pressable=True), over)

    def test_later_drawn_wins_within_layer(self):
        ox, oy = self.at(0, 0)
        a = self.track(Circle(center=(ox, oy), radius=40))
        b = self.track(Circle(center=(ox, oy), radius=40))
        a.clickable = True
        b.clickable = True
        self.assertIs(self.sim.hit_test(ox, oy, pressable=True), b)
        a.move_to_front()
        self.assertIs(self.sim.hit_test(ox, oy, pressable=True), a)

    def test_move_to_back(self):
        ox, oy = self.at(0, 0)
        a = self.track(Circle(center=(ox, oy), radius=40))
        b = self.track(Circle(center=(ox, oy), radius=40))
        a.clickable = True
        b.clickable = True
        b.move_to_back()
        self.assertIs(self.sim.hit_test(ox, oy, pressable=True), a)


# ---------------------------------------------------------------------------
# Click / drag / drop state machine
# ---------------------------------------------------------------------------
class TestClickDragDrop(InteractionTestCase):
    def test_click_requires_press_and_release_inside(self):
        ox, oy = self.at(100, 100)
        c = self.track(Circle(center=(ox, oy), radius=20))
        clicks = []
        c.on_click = lambda s: clicks.append(s)

        self.sim.handle_mouse_down(ox, oy, self.btn)
        self.sim.handle_mouse_up(ox, oy, self.btn)
        self.assertEqual(clicks, [c])

        clicks.clear()
        self.sim.handle_mouse_down(ox, oy, self.btn)
        self.sim.handle_mouse_up(ox + 100, oy + 100, self.btn)
        self.assertEqual(clicks, [])

    def test_draggable_only_release_without_drag_is_not_click(self):
        ox, oy = self.at(0, 0)
        c = self.track(Circle(center=(ox, oy), radius=20))
        clicks = []
        c.draggable = True
        # Attach handler without enabling clickable (setter would flip the flag).
        c._on_click = lambda s: clicks.append(s)
        self.assertFalse(c.clickable)

        self.sim.handle_mouse_down(ox, oy, self.btn)
        self.sim.handle_mouse_up(ox, oy, self.btn)
        self.assertEqual(clicks, [])

    def test_small_move_below_threshold_is_still_click(self):
        ox, oy = self.at(0, 0)
        c = self.track(Circle(center=(ox, oy), radius=30))
        clicks = []
        c.on_click = lambda s: clicks.append(1)
        self.sim.drag_threshold = 10.0

        self.sim.handle_mouse_down(ox, oy, self.btn)
        self.sim.handle_mouse_move(ox + 3, oy)
        self.sim.handle_mouse_up(ox + 3, oy, self.btn)
        self.assertEqual(clicks, [1])
        self.assertPointAlmost(c.center, ox, oy)

    def test_drag_moves_with_grab_offset(self):
        ox, oy = self.at(100, 100)
        c = self.track(Circle(center=(ox, oy), radius=20))
        c.draggable = True
        self.sim.drag_threshold = 5.0

        self.assertTrue(self.sim.handle_mouse_down(ox - 10, oy, self.btn))
        self.assertTrue(self.sim.handle_mouse_move(ox + 50, oy))
        self.assertPointAlmost(c.center, ox + 60, oy)

    def test_drag_vertex_side_triangle_follows_center(self):
        ox, oy = self.at(0, 0)
        tri = self.track(EquilateralTriangle(vertex=(ox, oy), side=60, angle=0))
        tri.draggable = True
        self.sim.drag_threshold = 1.0
        cx, cy = float(tri.center.x), float(tri.center.y)

        self.assertTrue(self.sim.handle_mouse_down(cx, cy, self.btn))
        self.assertTrue(self.sim.handle_mouse_move(cx + 10, cy + 4))
        self.assertPointAlmost(tri.center, cx + 10, cy + 4)
        # Pre-fix VERTEX_SIDE move_to teleported the vertex onto the old center.
        self.assertGreater(abs(tri.vertex.x - cx) + abs(tri.vertex.y - cy), 1.0)

    def test_drag_to_without_droppable(self):
        ox, oy = self.at(0, 0)
        c = self.track(Circle(center=(ox, oy), radius=20))
        got = []
        c.on_drag_to = lambda frm, to, pos: got.append((to, pos))
        self.sim.drag_threshold = 1.0

        self.sim.handle_mouse_down(ox, oy, self.btn)
        self.sim.handle_mouse_move(ox + 40, oy)
        self.sim.handle_mouse_up(ox + 40, oy, self.btn)
        self.assertEqual(len(got), 1)
        self.assertIsNone(got[0][0])
        self.assertEqual(got[0][1], (ox + 40, oy))

    def test_drop_on_zone(self):
        tx, ty = self.at(0, 0)
        zx, zy = self.at(80, 0)
        token = self.track(Circle(center=(tx, ty), radius=15))
        zone = self.track(Rect(center=(zx, zy), width=50, height=50))
        drops = []
        token.on_drag_to = lambda *a: None
        zone.on_drop_by = lambda frm, to, pos: drops.append((frm, to))

        self.sim.drag_threshold = 1.0
        self.sim.handle_mouse_down(tx, ty, self.btn)
        self.sim.handle_mouse_move(zx, zy)
        self.sim.handle_mouse_up(zx, zy, self.btn)
        self.assertEqual(drops, [(token, zone)])

    def test_drag_over_reports_current_droppable(self):
        tx, ty = self.at(0, 0)
        zx, zy = self.at(50, 0)
        token = self.track(Circle(center=(tx, ty), radius=10))
        zone = self.track(Rect(center=(zx, zy), width=40, height=40))
        overs = []
        token.on_drag_over = lambda frm, to, pos: overs.append(to)
        zone.droppable = True
        token.draggable = True

        self.sim.drag_threshold = 1.0
        self.sim.handle_mouse_down(tx, ty, self.btn)
        self.sim.handle_mouse_move(tx + 10, ty)
        self.sim.handle_mouse_move(zx, zy)
        self.assertIsNone(overs[0])
        self.assertIs(overs[-1], zone)

    def test_wheel_while_pressed_suppresses_click(self):
        ox, oy = self.at(0, 0)
        c = self.track(Circle(center=(ox, oy), radius=20))
        clicks = []
        c.on_click = lambda s: clicks.append(1)
        c.wheel_rotate = True

        self.sim.handle_mouse_down(ox, oy, self.btn)
        self.assertTrue(self.sim.handle_mouse_scroll(ox, oy, 0, 1.0))
        self.sim.handle_mouse_up(ox, oy, self.btn)
        self.assertEqual(clicks, [])

    def test_wheel_rotate_rotates_while_held(self):
        ox, oy = self.at(0, 0)
        r = self.track(Rect(center=(ox, oy), width=40, height=20, angle=0.0))
        r.draggable = True
        r.wheel_rotate = True
        before = r.angle

        self.sim.handle_mouse_down(ox, oy, self.btn)
        self.sim.handle_mouse_scroll(ox, oy, 0, 1.0)
        self.assertAlmostEqual(r.angle, before + math.degrees(0.04), places=5)

    def test_non_left_button_ignored(self):
        ox, oy = self.at(0, 0)
        c = self.track(Circle(center=(ox, oy), radius=20))
        c.clickable = True
        self.assertFalse(self.sim.handle_mouse_down(ox, oy, Mouse.BTN_RIGHT))
        self.assertFalse(self.sim.handle_mouse_up(ox, oy, Mouse.BTN_RIGHT))


# ---------------------------------------------------------------------------
# Hover
# ---------------------------------------------------------------------------
class TestHover(InteractionTestCase):
    def test_pointer_hover_tracks_topmost_pressable(self):
        ox, oy = self.at(0, 0)
        a = self.track(Circle(center=(ox, oy), radius=30))
        b = self.track(Circle(
            center=(ox, oy), radius=30, layer='top',
        ))
        a.clickable = True
        b.clickable = True

        self.sim.handle_mouse_move(ox, oy)
        self.sim.step_hover()
        self.assertTrue(b.pointer_hover)
        self.assertFalse(a.pointer_hover)

        self.sim.handle_mouse_move(ox + 200, oy + 200)
        self.sim.step_hover()
        self.assertFalse(b.pointer_hover)

    def test_anchor_hover_affordance_flag(self):
        ox, oy = self.at(0, 0)
        a = self.track(Anchor(ox, oy))
        self.assertFalse(a.pointer_hover)
        self.sim.handle_mouse_move(ox, oy)
        self.sim.step_hover()
        self.assertTrue(a.pointer_hover)
        self.sim.handle_mouse_move(ox + 100, oy + 100)
        self.sim.step_hover()
        self.assertFalse(a.pointer_hover)

    def test_colored_anchor_hover_affordance_flag(self):
        ox, oy = self.at(0, 0)
        a = self.track(Anchor(ox, oy, color="lime"))
        self.assertFalse(a.line)
        self.sim.handle_mouse_move(ox, oy)
        self.sim.step_hover()
        self.assertTrue(a.pointer_hover)


# ---------------------------------------------------------------------------
# pointer_pressed and the press lifecycle
# ---------------------------------------------------------------------------
class _Refuser(Circle):
    """A Graphic that swallows presses while ``refuse`` is set (a disabled button)."""

    refuse = True

    def _accepts_press(self):
        return not self.refuse


class TestPointerPressed(InteractionTestCase):
    """``pointer_pressed`` = held on this shape and the pointer over it.

    Bug class: a press that outlives what made it possible (destroyed,
    hidden, parked, no longer pressable) — the manager must drop it eagerly,
    not on the next pointer event.
    """

    def _clicky(self, x=0, y=0, cls=Circle):
        ox, oy = self.at(x, y)
        c = self.track(cls(center=(ox, oy), radius=20))
        clicks = []
        c.on_click = lambda s: clicks.append(s)
        return c, clicks, ox, oy

    def test_press_sets_and_release_clears(self):
        c, clicks, ox, oy = self._clicky()
        self.assertFalse(c.pointer_pressed)
        self.sim.handle_mouse_down(ox, oy, self.btn)
        self.assertTrue(c.pointer_pressed)
        self.sim.handle_mouse_up(ox, oy, self.btn)
        self.assertFalse(c.pointer_pressed)
        self.assertEqual(clicks, [c])

    def test_leaving_clears_and_coming_back_sets(self):
        c, clicks, ox, oy = self._clicky()
        self.sim.handle_mouse_down(ox, oy, self.btn)
        self.sim.handle_mouse_move(ox + 200, oy)
        self.assertFalse(c.pointer_pressed)
        self.sim.handle_mouse_move(ox + 1, oy)
        self.assertTrue(c.pointer_pressed)
        self.sim.handle_mouse_up(ox + 1, oy, self.btn)
        self.assertEqual(clicks, [c])

    def test_drag_keeps_it_pressed(self):
        ox, oy = self.at(0, 0)
        c = self.track(Circle(center=(ox, oy), radius=20))
        c.draggable = True
        self.sim.handle_mouse_down(ox, oy, self.btn)
        self.sim.handle_mouse_move(ox + 300, oy)
        self.assertTrue(c.pointer_pressed)
        self.sim.handle_mouse_up(ox + 300, oy, self.btn)
        self.assertFalse(c.pointer_pressed)

    def test_hover_handler_only_is_never_pressed(self):
        ox, oy = self.at(0, 0)
        c = self.track(Circle(center=(ox, oy), radius=20))
        c.on_hover = lambda s: None
        self.assertFalse(self.sim.handle_mouse_down(ox, oy, self.btn))
        self.assertFalse(c.pointer_pressed)

    def test_destroy_mid_press_drops_it_now(self):
        c, clicks, ox, oy = self._clicky()
        self.sim.handle_mouse_down(ox, oy, self.btn)
        c.destroy()
        self.assertIsNone(self.sim._pressed_shape)
        self.assertFalse(c.pointer_pressed)
        self.assertFalse(self.sim.handle_mouse_up(ox, oy, self.btn))
        self.assertEqual(clicks, [])

    def test_hide_mid_press_drops_it(self):
        c, clicks, ox, oy = self._clicky()
        self.sim.handle_mouse_down(ox, oy, self.btn)
        c.visible = False
        self.assertIsNone(self.sim._pressed_shape)
        self.assertFalse(c.pointer_pressed)
        self.sim.step_hover()
        self.assertFalse(c.pointer_hover)   # a hidden shape is not hovered
        c.visible = True
        self.sim.handle_mouse_up(ox, oy, self.btn)
        self.assertEqual(clicks, [])

    def test_park_mid_press_drops_it(self):
        c, clicks, ox, oy = self._clicky()
        self.sim.handle_mouse_down(ox, oy, self.btn)
        c.active = False
        self.assertIsNone(self.sim._pressed_shape)
        self.assertFalse(c.pointer_pressed)
        c.active = True
        self.sim.handle_mouse_up(ox, oy, self.btn)
        self.assertEqual(clicks, [])

    def test_unclickable_mid_press_drops_it(self):
        c, clicks, ox, oy = self._clicky()
        self.sim.handle_mouse_down(ox, oy, self.btn)
        c.clickable = False
        self.assertIsNone(self.sim._pressed_shape)
        self.assertFalse(c.pointer_pressed)

    def test_draggable_keeps_press_when_click_turns_off(self):
        ox, oy = self.at(0, 0)
        c = self.track(Circle(center=(ox, oy), radius=20))
        c.clickable = True
        c.draggable = True
        self.sim.handle_mouse_down(ox, oy, self.btn)
        c.clickable = False
        self.assertIs(self.sim._pressed_shape, c)

    def test_new_press_moves_the_bit(self):
        a, _, ax, ay = self._clicky(0, 0)
        b, _, bx, by = self._clicky(200, 0)
        self.sim.handle_mouse_down(ax, ay, self.btn)
        self.sim.handle_mouse_down(bx, by, self.btn)   # missed release
        self.assertFalse(a.pointer_pressed)
        self.assertTrue(b.pointer_pressed)

    def test_swallowed_press_no_click_no_bit_blocks_below(self):
        ox, oy = self.at(0, 0)
        below = self.track(Circle(center=(ox, oy), radius=30))
        below_clicks = []
        below.on_click = lambda s: below_clicks.append(s)
        top = self.track(_Refuser(center=(ox, oy), radius=20, layer="top"))
        top_clicks = []
        top.on_click = lambda s: top_clicks.append(s)
        self.assertTrue(self.sim.handle_mouse_down(ox, oy, self.btn))
        self.assertIs(self.sim._pressed_shape, top)
        self.assertFalse(top.pointer_pressed)
        self.assertTrue(self.sim.handle_mouse_up(ox, oy, self.btn))
        self.assertEqual(top_clicks, [])
        self.assertEqual(below_clicks, [])

    def test_swallowed_press_does_not_drag(self):
        ox, oy = self.at(0, 0)
        top = self.track(_Refuser(center=(ox, oy), radius=20))
        top.draggable = True
        self.sim.handle_mouse_down(ox, oy, self.btn)
        self.sim.handle_mouse_move(ox + 300, oy)
        self.assertAlmostEqual(top.center.x, ox)

    def test_refusing_between_press_and_release_cancels_click(self):
        ox, oy = self.at(0, 0)
        c = self.track(_Refuser(center=(ox, oy), radius=20))
        c.refuse = False
        clicks = []
        c.on_click = lambda s: clicks.append(s)
        self.sim.handle_mouse_down(ox, oy, self.btn)
        self.assertTrue(c.pointer_pressed)
        c.refuse = True
        self.sim.handle_mouse_up(ox, oy, self.btn)
        self.assertEqual(clicks, [])

    def test_on_pointer_pressed_changed_hook(self):
        seen = []

        class Watch(Circle):
            def _on_pointer_pressed_changed(self):
                seen.append(self.pointer_pressed)

        ox, oy = self.at(0, 0)
        c = self.track(Watch(center=(ox, oy), radius=20))
        c.clickable = True
        self.sim.handle_mouse_down(ox, oy, self.btn)
        self.sim.handle_mouse_up(ox, oy, self.btn)
        self.assertEqual(seen, [True, False])

    def test_widget_pointer_pressed_same_rule(self):
        from scena.uiwidget import Button
        from scena.orchestration import ScenaFramework

        ox, oy = self.at(0, 0)
        btn = Button(label="X", top_left=(ox - 40, oy + 12), width=100)
        try:
            wm = ScenaFramework.get_instance().widget_manager
            self.assertFalse(btn.pointer_pressed)
            wm.handle_mouse_down(ox, oy, self.btn)
            self.assertTrue(btn.pointer_pressed)
            wm.handle_mouse_move(ox + 500, oy)
            self.assertFalse(btn.pointer_pressed)
            wm.handle_mouse_move(ox, oy)
            self.assertTrue(btn.pointer_pressed)
            wm.handle_mouse_up(ox, oy, self.btn)
            self.assertFalse(btn.pointer_pressed)
            btn.enabled = False
            wm.handle_mouse_down(ox, oy, self.btn)
            self.assertFalse(btn.pointer_pressed)   # disabled swallows
            wm.handle_mouse_up(ox, oy, self.btn)
        finally:
            btn.destroy()

    def test_pointer_pressed_is_read_only(self):
        c, _, _, _ = self._clicky()
        with self.assertRaises(AttributeError):
            c.pointer_pressed = True


# ---------------------------------------------------------------------------
# Anchor
# ---------------------------------------------------------------------------
class TestAnchorInteraction(InteractionTestCase):
    def test_always_draggable_on_top(self):
        ox, oy = self.at(10, 20)
        a = self.track(Anchor(ox, oy, color="cyan"))
        self.assertTrue(a.handle)
        self.assertTrue(a.draggable)
        self.assertTrue(a.visible)
        self.assertEqual(a.layer, 'top')
        self.assertAlmostEqual(a.x, ox)
        self.assertAlmostEqual(a.y, oy)

        a.draggable = False
        self.assertTrue(a.draggable)
        self.assertTrue(a.handle)

        a.on_drag_to = None
        a.on_drag_over = None
        self.assertTrue(a.draggable)
        self.assertIn(a, _registry().layers['top']._interactive)

    def test_drag_moves_anchor_and_linked_line(self):
        ax, ay = self.at(0, 0)
        bx, by = self.at(100, 0)
        a = self.track(Anchor(ax, ay))
        b = self.track(Anchor(bx, by))
        line = self.track(Line(p1=lambda: a.center, p2=lambda: b.center))
        self.sim.drag_threshold = 1.0

        self.sim.handle_mouse_down(ax, ay, self.btn)
        self.sim.handle_mouse_move(ax + 30, ay + 10)
        self.assertPointAlmost(a.center, ax + 30, ay + 10)
        self.assertPointAlmost(line.p1, ax + 30, ay + 10)
        self.assertPointAlmost(line.p2, bx, by)


# ---------------------------------------------------------------------------
# UI vs shapes priority (decorative Text / widgets vs Graphics)
# ---------------------------------------------------------------------------
class TestPointerPriority(InteractionTestCase):
    def test_decorative_text_does_not_block_widgets_or_shapes(self):
        from scena import Text
        from scena.orchestration import ScenaFramework

        ox, oy = self.at(0, 0)
        lab = Text(text="XXXXXX", top_left=(ox - 20, oy + 10), font_size=30)  # covers (ox, oy)
        self.assertNotIn(lab, ScenaFramework.get_instance().widget_manager.widgets)
        a = self.track(Anchor(ox, oy))

        wm = ScenaFramework.get_instance().widget_manager
        self.assertIsNone(wm.get_widget_at(ox, oy))
        self.assertFalse(wm.handle_mouse_down(ox, oy, self.btn))
        self.assertTrue(self.sim.handle_mouse_down(ox, oy, self.btn))
        self.assertIs(self.sim._pressed_shape, a)

    def test_button_with_on_click_captures(self):
        from scena.uiwidget import Button
        from scena.orchestration import ScenaFramework

        ox, oy = self.at(0, 0)
        clicks = []
        btn = Button(
            label="XXXXXX", top_left=(ox - 40, oy + 12), width=100,  # covers (ox, oy)
            on_click=lambda: clicks.append(1),
        )
        self.track(Anchor(ox, oy))

        wm = ScenaFramework.get_instance().widget_manager
        self.assertIs(wm.get_widget_at(ox, oy), btn)
        self.assertTrue(wm.handle_mouse_down(ox, oy, self.btn))
        self.assertEqual(clicks, [])
        self.assertTrue(wm.handle_mouse_up(ox, oy, self.btn))
        self.assertEqual(clicks, [1])

    def test_top_layer_wins_over_default(self):
        ox, oy = self.at(0, 0)
        under = self.track(Circle(center=(ox, oy), radius=40))
        over = self.track(Anchor(ox, oy))  # layer top
        under.draggable = True
        self.assertEqual(over.layer, 'top')
        self.assertIs(self.sim.hit_test(ox, oy, pressable=True), over)


class TestContainsPointOnADeadActor(unittest.TestCase):
    """A destroyed actor contains nothing (review 2026-10-09 S6-8): the
    same answer as collision.query_point. A parked actor keeps its geometry."""

    def test_destroyed_kinds_contain_nothing(self):
        from scena import Circle, Rect, Polygon, Text
        for make in (lambda: Circle(center=(0, 0), radius=10),
                     lambda: Rect(center=(0, 0), width=20, height=20),
                     lambda: Polygon(points=[(-10, -10), (10, -10), (0, 10)]),
                     lambda: Text("abc", center=(0, 0))):
            s = make()
            self.assertTrue(s.contains_point(0, 0))
            center = s.center
            s.destroy()
            self.assertFalse(s.contains_point(0, 0), type(s).__name__)
            self.assertFalse(center.contains_point(0, 0), "a part of a dead actor")

    def test_parked_keeps_its_geometry(self):
        from scena import Circle
        c = Circle(center=(0, 0), radius=10)
        try:
            c.active = False
            self.assertTrue(c.contains_point(0, 0))
        finally:
            c.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
