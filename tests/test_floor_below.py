"""``Graphic.floor_below(dx=, depth=, group=)``: the floor after a step.

Rule under test (Collision Design.md, "Floor ahead: floor_below"): the answer
uses the body's collision prims, the solver's floor rule (a ``"bottom"``
contact, ±45°), and the floor-snap reach as the default ``depth`` — so "no
floor" means the resolver would let the body fall. Ground is the body's
``resolve()`` partners unless ``group=`` names it. The call is a read.

Bug class guarded: a ledge helper that disagrees with the physics — a drawn
box instead of the hitbox, a false edge at a tile join, a slope read as a
ledge, a sensor that counts coins as floor, or a query that moves the body.
"""
import math
import os
import sys
import unittest

import skia

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.collision import (
    STATIC,
    _FLOOR_SNAP_MIN,
    _RESOLVE_SLOP,
    collide,
    get_collision_system,
    reset_collision_system,
    resolve,
)
from scena.shapes import Circle, Polygon, Rect
from scena.scenamath import Vec2

GRAVITY = 900.0
DT = 1.0 / 60.0
HERO_W = 20.0
HERO_H = 40.0


class FloorBelowCase(unittest.TestCase):
    _origin = 0

    def setUp(self):
        reset_collision_system()
        self._owned = []
        FloorBelowCase._origin += 5000
        self.o = float(FloorBelowCase._origin)

    def tearDown(self):
        for s in self._owned:
            try:
                s.destroy()
            except Exception:
                pass
        self._owned.clear()
        reset_collision_system()

    # --- world (floor tops at y = self.o unless given) ---------------------
    def track(self, shape):
        self._owned.append(shape)
        return shape

    def slab(self, left, right, top=0.0, group="chao", height=20.0):
        s = self.track(Rect(
            center=(self.o + (left + right) / 2.0, self.o + top - height / 2.0),
            width=right - left, height=height, group=group,
        ))
        s.mass = STATIC
        return s

    def poly(self, pts, group="chao"):
        p = self.track(Polygon(
            points=[(self.o + x, self.o + y) for x, y in pts], group=group,
        ))
        p.mass = STATIC
        return p

    def hero(self, x, bottom=0.0, group="heroi", shape="rect", radius=12.0):
        if shape == "circle":
            h = Circle(center=(self.o + x, self.o + bottom + radius + 0.5),
                       radius=radius, group=group)
        else:
            h = Rect(center=(self.o + x, self.o + bottom + HERO_H / 2.0 + 0.5),
                     width=HERO_W, height=HERO_H, group=group)
        h = self.track(h)
        h.mass = 1.0
        h.vel = Vec2(0.0, 0.0)
        return h

    def step(self):
        get_collision_system().step()

    def fall(self, h, vx=0.0):
        h.vel.x = vx
        h.vel.y -= GRAVITY * DT
        h.move_by(h.vel.x * DT, h.vel.y * DT)
        self.step()

    def settle(self, h, frames=10):
        for _ in range(frames):
            self.fall(h)
        self.assertIn("bottom", h.touching_sides, "fixture: hero did not land")

    def x(self, h):
        return float(h.center.x) - self.o


class TestFlatSlab(FloorBelowCase):
    """The whole hitbox decides, as the solver does: a corner still stands."""

    def setUp(self):
        super().setUp()
        self.s = self.slab(-100.0, 100.0)
        self.h = self.hero(0.0)
        resolve("heroi", "chao", bounce=0.0)
        self.settle(self.h)

    def test_current_floor(self):
        self.assertIs(self.h.floor_below(), self.s)

    def test_supported_until_the_back_edge_leaves(self):
        # Edge at x = 100, hero half width 10: supported while center < 110.
        edge = 100.0 + HERO_W / 2.0 - self.x(self.h)
        self.assertIs(self.h.floor_below(dx=edge - 1.0), self.s)
        self.assertIsNone(self.h.floor_below(dx=edge + 1.0))
        self.assertIs(self.h.floor_below(dx=-(edge - 1.0)), self.s)
        self.assertIsNone(self.h.floor_below(dx=-(edge + 1.0)))

    def test_dx_width_is_front_edge_at_the_ledge(self):
        h = self.h
        h.center = (self.o + 100.0 - HERO_W / 2.0 - 1.0, float(h.center.y))
        self.assertIs(h.floor_below(dx=HERO_W), self.s, "front edge 1 DU before the ledge")
        h.center = (self.o + 100.0 - HERO_W / 2.0 + 1.0, float(h.center.y))
        self.assertIsNone(h.floor_below(dx=HERO_W), "front edge 1 DU past the ledge")

    def test_answer_matches_walking_off(self):
        """floor_below's edge is where the resolver really drops the body."""
        h = self.h
        h.center = (self.o + 100.0, float(h.center.y))
        self.settle(h, 3)
        predicted = h.floor_below(dx=15.0)
        for _ in range(4):  # walk 15 DU right in small frames
            self.fall(h, vx=15.0 / (4 * DT))
        for _ in range(3):
            self.fall(h)
        self.assertIsNone(predicted)
        self.assertNotIn("bottom", h.touching_sides)

    def test_is_a_read(self):
        """No motion consumed, no one-way pass started, no enroll, no step change."""
        h = self.h
        twin = self.hero(-60.0, group="twin")
        resolve("twin", "chao", bounce=0.0)
        self.settle(twin)
        h.move_by(5.0, 0.0)
        twin.move_by(5.0, 0.0)
        before = self.x(h)
        h.floor_below(dx=40.0)
        h.floor_below(dx=-400.0)
        self.assertEqual(self.x(h), before)
        self.step()
        self.assertAlmostEqual(self.x(h) - before, self.x(twin) - (before - 60.0), places=6)
        self.assertEqual(h.touching_sides, twin.touching_sides)


class TestTilesAndSlopes(FloorBelowCase):
    def test_no_false_edge_at_a_tile_join(self):
        tiles = [self.slab(-100.0 + 40.0 * i, -60.0 + 40.0 * i) for i in range(5)]
        h = self.hero(-80.0)
        resolve("heroi", "chao", bounce=0.0)
        self.settle(h)
        for dx in range(0, 170, 5):
            self.assertIsNotNone(h.floor_below(dx=float(dx)), f"false edge at dx={dx}")
        self.assertIn(h.floor_below(dx=160.0), tiles)
        self.assertIsNone(h.floor_below(dx=200.0))

    def _plateau_then(self, angle, up, m=1.0):
        """Plateau, then a ramp starting at x = 0; ``m = -1`` mirrors it left."""
        if m > 0:
            self.plat = self.slab(-100.0, 0.0)
        else:
            self.plat = self.slab(0.0, 100.0)
        run = 120.0
        rise = run * math.tan(math.radians(angle))
        y = rise if up else -rise
        pts = [(0.0, 0.0), (m * run, y), (m * run, min(0.0, y) - 40.0), (0.0, min(0.0, y) - 40.0)]
        self.ramp = self.poly(pts)
        h = self.hero(-30.0 * m)
        resolve("heroi", "chao", bounce=0.0)
        self.settle(h)
        return h

    def _clear(self, h):
        for s in (h, self.plat, self.ramp):
            s.destroy()

    def test_walkable_slopes_are_floor(self):
        for m in (1.0, -1.0):
            for up in (True, False):
                with self.subTest(up=up, mirrored=m < 0):
                    h = self._plateau_then(30.0, up, m)
                    for dx in (20.0, 40.0, 60.0, 90.0):
                        self.assertIs(h.floor_below(dx=m * dx), self.ramp, f"dx={m * dx}")
                    self._clear(h)

    def test_depth_never_turns_a_walkable_slope_into_a_ledge(self):
        """depth= is for sheer drops; sub-steps shrink with it, so ≤45° stays floor."""
        for depth in (1.0, 4.0, _FLOOR_SNAP_MIN):
            with self.subTest(depth=depth):
                h = self._plateau_then(40.0, False)
                self.assertIs(h.floor_below(dx=60.0, depth=depth), self.ramp)
                self._clear(h)

    def test_steep_drop_is_not_floor(self):
        for m in (1.0, -1.0):
            with self.subTest(mirrored=m < 0):
                h = self._plateau_then(60.0, False, m)
                self.assertIsNone(h.floor_below(dx=m * 50.0))
                self._clear(h)

    def test_steep_rise_is_a_wall_not_a_ledge(self):
        """Blocked: the floor where the march stopped, never None."""
        for m in (1.0, -1.0):
            with self.subTest(mirrored=m < 0):
                h = self._plateau_then(60.0, True, m)
                self.assertIs(h.floor_below(dx=m * 60.0), self.plat)
                self._clear(h)


class TestDepthAndDrops(FloorBelowCase):
    def _step_down(self, drop):
        self.slab(-100.0, 0.0)
        low = self.slab(0.0, 200.0, top=-drop)
        h = self.hero(-15.0)
        resolve("heroi", "chao", bounce=0.0)
        self.settle(h)
        return h, low

    def _walk_keeps_ground(self, h, frames=30, vx=120.0):
        grounded = True
        for _ in range(frames):
            self.fall(h, vx=vx)
            if "bottom" not in h.touching_sides:
                grounded = False
        return grounded

    def test_small_step_down_is_floor_and_the_solver_agrees(self):
        h, low = self._step_down(8.0)
        self.assertIs(h.floor_below(dx=40.0), low)
        self.assertTrue(self._walk_keeps_ground(h), "solver let an 8 DU step drop the body")

    def test_big_drop_is_a_fall_and_the_solver_agrees(self):
        h, _low = self._step_down(_FLOOR_SNAP_MIN * 2)
        self.assertIsNone(h.floor_below(dx=40.0))
        self.assertFalse(self._walk_keeps_ground(h), "solver kept a 32 DU drop grounded")

    def test_depth_is_the_sheer_drop_threshold(self):
        h, low = self._step_down(10.0)
        self.assertIsNone(h.floor_below(dx=40.0, depth=9.0))
        self.assertIs(h.floor_below(dx=40.0, depth=11.0), low)

    def test_depth_widens_the_drop(self):
        h, low = self._step_down(30.0)
        self.assertIsNone(h.floor_below(dx=40.0))
        self.assertIs(h.floor_below(dx=40.0, depth=40.0), low)

    def test_low_ceiling_does_not_break_flat_ground(self):
        s = self.slab(-100.0, 100.0)
        h = self.hero(0.0)
        self.slab(-100.0, 100.0, top=HERO_H + 3.0 + 20.0, height=20.0)
        resolve("heroi", "chao", bounce=0.0)
        self.settle(h)
        self.assertIs(h.floor_below(dx=60.0), s)

    def test_wall_ahead_answers_the_floor_there(self):
        s = self.slab(-100.0, 100.0)
        self.slab(30.0, 50.0, top=80.0, height=80.0, group="muro")
        h = self.hero(0.0)
        resolve("heroi", ["chao", "muro"], bounce=0.0)
        self.settle(h)
        self.assertIs(h.floor_below(dx=200.0), s)


class TestShapes(FloorBelowCase):
    def test_circle_rolls_off_past_45_degrees(self):
        r = 12.0
        s = self.slab(-100.0, 100.0)
        h = self.hero(0.0, shape="circle", radius=r)
        resolve("heroi", "chao", bounce=0.0)
        self.settle(h)
        # Contact normal leaves the ±45° floor cone at r·sin 45° past the edge.
        cut = 100.0 + r * math.sin(math.radians(45.0)) - self.x(h)
        self.assertIs(h.floor_below(dx=cut - 2.0), s)
        self.assertIsNone(h.floor_below(dx=cut + 2.0))


class TestSpriteHitbox(FloorBelowCase):
    def test_uses_the_hitbox_not_the_drawn_box(self):
        """Padded art: 64 px drawn, a 16 px bar hitbox. The bar decides."""
        import tempfile
        from scena.sprite import Sprite
        from tests.test_sprite import _write_padded_png

        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = os.path.join(td.name, "bar.png")
        _write_padded_png(path, canvas_w=64, canvas_h=64, blob=(24, 8, 16, 48))
        s = self.slab(-100.0, 100.0)
        h = self.track(Sprite(path, center=(self.o, self.o + 30.0), width=64, height=64,
                              group="heroi", hitbox_shape="rect"))
        h.mass = 1.0
        h.vel = Vec2(0.0, 0.0)
        resolve("heroi", "chao", bounce=0.0)
        self.settle(h, 20)
        self.assertGreater(h.box.width, 60.0, "fixture: drawn box should be the padded cell")
        edge = 100.0 + 8.0 - self.x(h)  # bar half width 8, not the drawn 32
        self.assertIs(h.floor_below(dx=edge - 2.0), s)
        self.assertIsNone(h.floor_below(dx=edge + 2.0))
        # The taught front-edge idiom measures the hitbox, not the drawing.
        self.assertAlmostEqual(h.hitbox.box.width, 16.0)
        # Front edge of the hitbox 1 DU before the ledge (slab edge at o + 100).
        gap = self.o + 100.0 - h.hitbox.box.right
        h.center = (float(h.center.x) + gap - 1.0, float(h.center.y))
        self.assertIs(h.floor_below(dx=h.hitbox.box.width), s)
        h.center = (float(h.center.x) + 2.0, float(h.center.y))
        self.assertIsNone(h.floor_below(dx=h.hitbox.box.width))


class TestGround(FloorBelowCase):
    def test_detection_only_bodies_are_not_floor(self):
        self.slab(-100.0, 100.0)
        # Under the whole step, flush with the slab top: only group= decides.
        coin = self.track(Rect(center=(self.o + 140.0, self.o - 5.0),
                               width=120.0, height=10.0, group="moeda"))
        h = self.hero(95.0)
        resolve("heroi", "chao", bounce=0.0)

        @collide("heroi", "moeda")
        def _grab(info):
            pass

        self.settle(h)
        self.assertIsNone(h.floor_below(dx=30.0), "a coin counted as ground")
        self.assertIs(h.floor_below(dx=30.0, group="moeda"), coin)

    def test_group_names_ground_for_a_walker_without_resolve(self):
        s = self.slab(-100.0, 100.0, group="chao")
        walker = self.track(Rect(center=(self.o, self.o + HERO_H / 2.0 + 0.1),
                                 width=HERO_W, height=HERO_H, group="bicho"))
        sys_ = get_collision_system()
        before = len(sys_._colliders)
        self.assertIs(walker.floor_below(dx=50.0, group="chao"), s)
        self.assertIsNone(walker.floor_below(dx=150.0, group="chao"))
        self.assertIsNone(getattr(walker, "_collider", None), "floor_below enrolled the walker")
        self.assertEqual(len(sys_._colliders), before)

    def test_no_resolve_and_no_group_raises_with_both_fixes(self):
        self.slab(-100.0, 100.0)
        walker = self.track(Rect(center=(self.o, self.o + 25.0), width=20.0, height=40.0))
        with self.assertRaises(ValueError) as cm:
            walker.floor_below()
        msg = str(cm.exception)
        self.assertIn("resolve(", msg)
        self.assertIn("group=", msg)

    def test_one_way_platform_is_floor_from_above_and_query_starts_no_pass(self):
        self.slab(-200.0, 200.0)
        plat = self.slab(-50.0, 50.0, top=60.0, height=8.0, group="fina")
        h = self.hero(0.0)
        resolve("heroi", "chao", bounce=0.0)
        resolve("heroi", "fina", bounce=0.0, only="bottom")
        self.settle(h)
        sys_ = get_collision_system()
        # Below the platform: the lift reaches its underside; the gate rejects
        # it and the query must not start a pass through it.
        h.floor_below(dx=30.0)
        self.assertFalse(sys_._passing.get(id(h._collider)), "a query started a one-way pass")
        h.center = (self.o, self.o + 60.0 + HERO_H / 2.0 + 0.5)
        self.settle(h, 5)
        self.assertIs(h.floor_below(), plat)

    def test_dead_or_inactive_body_answers_none(self):
        self.slab(-100.0, 100.0)
        h = self.hero(0.0)
        resolve("heroi", "chao", bounce=0.0)
        self.settle(h)
        h.active = False
        self.assertIsNone(h.floor_below())
        h.active = True
        h.destroy()
        self.assertIsNone(h.floor_below())


class TestValidation(FloorBelowCase):
    def setUp(self):
        super().setUp()
        self.slab(-100.0, 100.0)
        self.h = self.hero(0.0)
        resolve("heroi", "chao", bounce=0.0)

    def test_bad_numbers(self):
        for kwargs, exc in (
            ({"dx": "a"}, TypeError),
            ({"dx": float("nan")}, ValueError),
            ({"dx": lambda: 3.0}, TypeError),
            ({"depth": -1.0}, ValueError),
            ({"depth": float("inf")}, ValueError),
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(exc):
                self.h.floor_below(**kwargs)

    def test_keyword_only(self):
        with self.assertRaises(TypeError):
            self.h.floor_below(10.0)


class TestShowColliders(FloorBelowCase):
    def test_probe_is_drawn_once_in_its_colour(self):
        self.slab(-100.0, 100.0)
        h = self.hero(0.0)
        resolve("heroi", "chao", bounce=0.0)
        self.settle(h)
        sys_ = get_collision_system()
        h.floor_below(dx=10.0)
        self.assertEqual(sys_._debug_probes, {}, "probe kept while show_colliders is off")
        sys_.show_colliders(True)
        try:
            h.floor_below(dx=10.0)
            h.floor_below(dx=500.0)  # same body: the last probe wins
            (_prims, found), = sys_._debug_probes.values()
            self.assertFalse(found)
            surface = skia.Surface(32, 32)
            sys_.debug_draw(surface.getCanvas())
            self.assertEqual(sys_._debug_probes, {}, "probe not cleared by the draw")
        finally:
            sys_.show_colliders(False)


if __name__ == "__main__":
    unittest.main()
