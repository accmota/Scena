"""
Unit tests for the collision system.

Run headless:

    python -m unittest tests.test_collision -v
"""

import math
import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.collision import (
    ANYTHING,
    Collider,
    CollisionInfo,
    Contact,
    Prim,
    PrimKind,
    STATIC,
    collision,
    collide,
    collide_exit,
    collide_stay,
    collide_with,
    collide_with_exit,
    collide_with_stay,
    get_collision_system,
    narrow_phase,
    reset_collision_system,
    resolve,
    snapshot_shape,
    test_collision as query_collision,
    unresolve,
    _aabb_aabb,
    _aabb_overlaps_box,
    _circle_aabb,
    _circle_aabb_toi,
    _collision_pose_key,
    _ear_clip,
    _side_from_normal,
    _floor_snap_should_refuse,
    _is_convex,
    _points_or_witness,
    _proxy_aabb_for_shape,
    _proxy_aabb_overlap,
    _CONTACT_SKIN,
    _gjk_distance,
    _prim_gap,
    _RESOLVE_POSITION_ONLY,
    _RESOLVE_SLOP,
    _snapshot_shape_uncached,
)
from scena.shapes import (
    Circle, Ellipse, EquilateralTriangle, Line, Point, Polygon, Rect,
    RegularPolygon, Square,
)
from scena.track import Track
from scena.scenamath import Vec2
from scena.sprite import Sprite, Sheet


class CollisionTestCase(unittest.TestCase):
    _origin = 0

    def setUp(self):
        reset_collision_system()
        self._owned = []
        CollisionTestCase._origin += 5000
        self.origin = CollisionTestCase._origin

    def tearDown(self):
        for s in self._owned:
            try:
                s.destroy()
            except Exception:
                pass
        self._owned.clear()
        reset_collision_system()

    def track(self, shape):
        self._owned.append(shape)
        return shape

    def at(self, x, y):
        return (self.origin + x, self.origin + y)

    def step(self):
        get_collision_system().step()


class TestQueryInfoIsTheAuthorView(CollisionTestCase):
    """Bug PM11 (found writing the toybox program): ``test_collision(a, b)``
    returned the raw collider-level info: ``info.a`` / ``info.b`` were engine
    Collider objects, not the author's bodies, and the normal / side were
    reversed (Rect with a Circle to its right: normal (-1, 0), side "left").
    Guia CollisionInfo: a / b are the two bodies, the normal points from a to
    b, side is a's side. Now the same view a ``@collide`` handler gets."""

    def test_identities_and_orientation_both_ways(self):
        r = self.track(Rect(center=self.at(0, 0), width=20, height=20))
        c = self.track(Circle(center=self.at(8, 0), radius=6))
        info = query_collision(r, c)
        self.assertIs(info.a, r)
        self.assertIs(info.b, c)
        self.assertAlmostEqual(float(info.normal.x), 1.0)
        self.assertEqual(info.side, "right")
        back = query_collision(c, r)
        self.assertIs(back.a, c)
        self.assertIs(back.b, r)
        self.assertAlmostEqual(float(back.normal.x), -1.0)

    def test_same_as_the_handler_sees(self):
        r = self.track(Rect(center=self.at(0, 0), width=20, height=20, group="pm11_a"))
        c = self.track(Circle(center=self.at(3, 9), radius=6, group="pm11_b"))
        seen = []

        def hit(me, other, info):
            seen.append((info.a, info.b, round(float(info.normal.x), 9),
                         round(float(info.normal.y), 9), info.side))
        from scena import collide
        collide("pm11_a", "pm11_b")(hit)
        self.step()
        q = query_collision(r, c)
        self.assertTrue(seen)
        self.assertEqual(seen[0], (q.a, q.b, round(float(q.normal.x), 9),
                                   round(float(q.normal.y), 9), q.side))

    def test_a_piece_of_a_collider_answers_as_the_collider(self):
        post = self.track(Rect(center=self.at(0, 0), width=20, height=40))
        cap = self.track(Circle(center=self.at(0, 25), radius=12))
        bumper = Collider([post, cap])
        toy = self.track(Circle(center=self.at(8, 0), radius=6))
        info = query_collision(post, toy)
        # Not enrolled: the piece is probed on its own and answers as itself;
        # never an engine probe object.
        self.assertIn(info.a, (post, bumper))
        self.assertIs(info.b, toy)
        self.assertAlmostEqual(float(info.normal.x), 1.0)
        info = query_collision(bumper, toy)
        self.assertIs(info.a, bumper)
        self.assertIs(info.b, toy)


class TestFlagsAndOptIn(CollisionTestCase):
    def test_collidable_creates_implicit_collider(self):
        c = self.track(Circle(center=self.at(0, 0), radius=10))
        self.assertFalse(c.collidable)
        self.assertIsNone(c._collider)
        c.collidable = True
        self.assertTrue(c.collidable)
        self.assertIsNotNone(c._collider)
        self.assertIn(c._collider, get_collision_system()._colliders)
        self.assertEqual(c._collider._pair_targets, [])

    def test_callback_enables_collidable(self):
        c = self.track(Circle(center=self.at(0, 0), radius=10))
        c.on_collide = lambda *a: None
        self.assertTrue(c.collidable)
        self.assertIn(ANYTHING, c._collider._pair_targets)

    def test_collidable_only_does_not_pair(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20))
        b = self.track(Circle(center=self.at(5, 0), radius=20))
        a.collidable = True
        b.collidable = True
        self.step()
        stats = get_collision_system().last_stats
        self.assertEqual(stats["proxy_pairs"], 0)
        self.assertEqual(stats["narrow"], 0)

    def test_collidable_false_unregisters(self):
        c = self.track(Circle(center=self.at(0, 0), radius=10))
        c.collidable = True
        col = c._collider
        c.collidable = False
        self.assertNotIn(col, get_collision_system()._colliders)
        self.assertIsNone(c._collider)

    def test_unopted_shapes_not_tested(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20))
        b = self.track(Circle(center=self.at(5, 0), radius=20))
        a.collidable = True
        # b not collidable
        hits = []
        a.on_collide = lambda *args: hits.append(True)
        self.step()
        self.assertEqual(hits, [])


class TestAnythingInterestLifecycle(CollisionTestCase):
    def test_on_collide_clear_removes_anything(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20))
        b = self.track(Circle(center=self.at(5, 0), radius=20))
        b.collidable = True
        a.on_collide = lambda *args: None
        self.assertIn(ANYTHING, a._collider._pair_targets)
        a.on_collide = None
        self.assertNotIn(ANYTHING, a._collider._pair_targets)
        self.step()
        stats = get_collision_system().last_stats
        self.assertEqual(stats["proxy_pairs"], 0)

    def test_on_collide_clear_decorator_still_fires(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20))
        b = self.track(Circle(center=self.at(5, 0), radius=20))
        hits = []

        @collide(a, b)
        def on_hit(me, other, info):
            hits.append("dec")

        a.on_collide = lambda *args: hits.append("obj")
        self.step()
        self.assertEqual(hits, ["obj", "dec"])
        hits.clear()
        a.on_collide = None
        b.center = self.at(100, 0)
        self.step()
        hits.clear()
        b.center = self.at(5, 0)
        self.step()
        self.assertEqual(hits, ["dec"])

    def test_on_collide_stay_only_then_clear(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20))
        b = self.track(Circle(center=self.at(5, 0), radius=20))
        b.collidable = True
        a.on_collide_stay = lambda *args: None
        self.assertIn(ANYTHING, a._collider._pair_targets)
        a.on_collide_stay = None
        self.assertNotIn(ANYTHING, a._collider._pair_targets)

    def test_on_collide_clear_keeps_collide_with_anything(self):
        class Wasp(Circle):
            def on_collide(self, other, info):
                pass

            @collide_with(ANYTHING)
            def on_any(self, other, info):
                pass

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("ignore")
            wasp = self.track(Wasp(center=self.at(0, 0), radius=10))
        self.assertIn(ANYTHING, wasp._collider._pair_targets)
        wasp.on_collide = None
        self.assertIn(ANYTHING, wasp._collider._pair_targets)


    def test_unresolve_anything_removes_anything(self):
        # Review 2026-10-09 S8-4: the pair went, ANYTHING stayed, and the hero
        # kept a proxy pair with every body.
        a = self.track(Circle(center=self.at(0, 0), radius=200))
        for i in range(5):
            self.track(Circle(center=self.at(i * 10 - 20, 0), radius=4)).collidable = True
        resolve(a, ANYTHING)
        self.step()
        self.assertGreater(get_collision_system().last_stats["proxy_pairs"], 0)
        unresolve(a, ANYTHING)
        self.assertNotIn(ANYTHING, a._collider._pair_targets)
        self.step()
        self.assertEqual(get_collision_system().last_stats["proxy_pairs"], 0)

    def test_unresolve_anything_keeps_on_collide_interest(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20))
        a.on_collide = lambda *args: None
        resolve(a, ANYTHING)
        unresolve(a, ANYTHING)
        self.assertIn(ANYTHING, a._collider._pair_targets, "the callback still wants it")

    def test_a_tag_whose_last_rule_died_stops_enrolling(self):
        # Review 2026-10-09 S8-7, destroy door: with the boss gone, "un_bala"
        # kept enrolling every later bullet (a collider and a proxy each).
        boss = self.track(Circle(center=self.at(0, 0), radius=20))

        @collide(boss, "un_bala")
        def hit(b, bullet, info):
            pass

        first = self.track(Circle(center=self.at(50, 0), radius=3, group="un_bala"))
        self.assertIsNotNone(first._collider)
        boss.destroy()
        cs = get_collision_system()
        self.assertNotIn("un_bala", cs._pair_tags)
        self.assertIsNone(first._collider, "enrolled only by the dead rule")
        later = self.track(Circle(center=self.at(60, 0), radius=3, group="un_bala"))
        self.assertIsNone(later._collider)

    def test_unresolve_drops_the_other_side_from_the_targets(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20))
        self.track(Circle(center=self.at(100, 0), radius=20, group="un_wall"))
        resolve(a, "un_wall")
        self.assertIn("un_wall", a._collider._pair_targets)
        unresolve(a, "un_wall")
        self.assertNotIn("un_wall", a._collider._pair_targets)


class TestResolveAnythingIsSolid(CollisionTestCase):
    """resolve(x, ANYTHING) is kept on purpose and makes every enrolled body
    solid, a @collide-only collectable included (Collision Design, "Standing
    resolve"; the Guia warns at #res-basic). Decided 2026-10-13: not refused,
    unlike @leave_playfield(ANYTHING)."""

    def coin_pass(self, solid_side):
        hero = self.track(Rect(center=self.at(0, 0), width=20, height=20, group="ra_hero"))
        coin = self.track(Circle(center=self.at(12, 0), radius=10, group="ra_coin"))
        hits = []

        @collide(hero, "ra_coin")
        def pick(me, other, info):
            hits.append(other)

        resolve(hero, solid_side)
        self.step()
        return hero, coin, hits

    def test_anything_pushes_a_collide_only_coin_and_the_handler_still_fires(self):
        hero, coin, hits = self.coin_pass(ANYTHING)
        self.assertEqual(hits, [coin])
        self.assertLess(float(hero.center.x), self.origin - 1.0)
        self.assertGreater(float(coin.center.x), self.origin + 13.0)

    def test_named_solid_groups_leave_the_coin_alone(self):
        hero, coin, hits = self.coin_pass(["ra_wall", "ra_crate"])
        self.assertEqual(hits, [coin])
        self.assertEqual(float(hero.center.x), float(self.origin))
        self.assertEqual(float(coin.center.x), float(self.origin + 12))

    def test_anything_on_both_sides_is_accepted_and_separates(self):
        a = self.track(Rect(center=self.at(0, 0), width=20, height=20))
        b = self.track(Rect(center=self.at(10, 0), width=20, height=20))
        a.collidable = b.collidable = True
        resolve(ANYTHING, ANYTHING)
        self.step()
        self.assertGreaterEqual(float(b.center.x) - float(a.center.x), 19.5)


class TestDispatchHandlerIndex(CollisionTestCase):
    """Review 2026-10-09 perf: ``_dispatch`` walks this phase's handlers from a
    snapshot, skipping a tag handler whose tag holds neither collider. The
    skip is a necessary condition only: every handler that matched before
    still runs, in registration order."""

    def test_the_matching_handler_runs_among_unrelated_ones(self):
        log = []
        for k in range(20):
            @collide(f"dx_a{k}", f"dx_b{k}")
            def other(a, b, info):
                log.append("other")
        a = self.track(Circle(center=self.at(0, 0), radius=10, group="dx_x"))
        b = self.track(Circle(center=self.at(5, 0), radius=10, group="dx_y"))

        @collide("dx_x", "dx_y")
        def hit(me, other, info):
            log.append(("hit", me is a, other is b))
        self.step()
        self.assertEqual(log, [("hit", True, True)])

    def test_object_and_tag_sides_and_order(self):
        log = []
        a = self.track(Circle(center=self.at(0, 0), radius=10))
        b = self.track(Circle(center=self.at(5, 0), radius=10, group="dx_wall"))

        @collide(a, "dx_wall")
        def first(me, other, info):
            log.append("first")

        @collide(a, b)
        def second(me, other, info):
            log.append("second")

        @collide("dx_wall", a)
        def third(me, other, info):
            log.append("third")
        self.step()
        self.assertEqual(log, ["first", "second", "third"])

    def test_a_handler_added_and_dropped_between_steps(self):
        log = []
        a = self.track(Circle(center=self.at(0, 0), radius=10, group="dx_p"))
        b = self.track(Circle(center=self.at(5, 0), radius=10, group="dx_q"))

        @collide_stay("dx_p", "dx_q")
        def stay(me, other, info):
            log.append("stay")
        self.step()
        self.step()

        @collide_stay("dx_p", "dx_q")
        def later(me, other, info):
            log.append("later")
        self.step()
        self.assertEqual(log, ["stay", "stay", "later"])
        b.destroy()
        self._owned.remove(b)
        cs = get_collision_system()
        self.assertIsNone(cs._phase_cache, "the snapshot keeps no dropped side")


class TestLayer1FastPaths(CollisionTestCase):
    def test_circle_circle(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20))
        b = self.track(Circle(center=self.at(30, 0), radius=20))
        a.collidable = True
        b.collidable = True
        depths = []
        a.on_collide = lambda me, other, info: depths.append(info.depth)
        self.step()
        self.assertEqual(len(depths), 1)
        self.assertAlmostEqual(depths[0], 10.0, places=5)

    def test_circle_circle_separated(self):
        a = self.track(Circle(center=self.at(0, 0), radius=10))
        b = self.track(Circle(center=self.at(50, 0), radius=10))
        a.collidable = True
        b.collidable = True
        hits = []
        a.on_collide = lambda *a: hits.append(1)
        self.step()
        self.assertEqual(hits, [])

    def test_aabb_aabb(self):
        a = self.track(Rect(center=self.at(0, 0), width=40, height=40, angle=0))
        b = self.track(Rect(center=self.at(30, 0), width=40, height=40, angle=0))
        a.collidable = True
        b.collidable = True
        depths = []
        a.on_collide = lambda me, other, info: depths.append(info.depth)
        self.step()
        self.assertEqual(len(depths), 1)
        self.assertAlmostEqual(depths[0], 10.0, places=5)

    def test_circle_aabb(self):
        c = self.track(Circle(center=self.at(0, 0), radius=15))
        r = self.track(Rect(center=self.at(20, 0), width=20, height=20, angle=0))
        c.collidable = True
        r.collidable = True
        depths = []
        c.on_collide = lambda me, other, info: depths.append(info.depth)
        self.step()
        self.assertEqual(len(depths), 1)
        self.assertGreater(depths[0], 0.0)

    def test_point_as_degenerate_circle(self):
        p = self.track(Point(*self.at(0, 0)))
        c = self.track(Circle(center=self.at(0, 0), radius=10))
        p.collidable = True
        c.collidable = True
        hits = []
        c.on_collide = lambda *a: hits.append(1)
        self.step()
        self.assertEqual(hits, [1])


class TestCircleArcCollision(CollisionTestCase):
    """Partial circles collide as the filled pie or chord segment.

    A full turn stays one ``CIRCLE`` prim so circle–circle tests stay closed-form.
    """

    def _probe(self, x, y, radius=3.0):
        return self.track(Circle(center=self.at(x, y), radius=radius))

    def test_full_turn_stays_circle_prim(self):
        disk = self.track(Circle(center=self.at(0, 0), radius=10))
        spun = self.track(Circle(center=self.at(0, 0), radius=10, angle=40, spread=360))
        for shape in (disk, spun):
            prims = snapshot_shape(shape)
            self.assertEqual(len(prims), 1)
            self.assertEqual(prims[0].kind, PrimKind.CIRCLE)
            self.assertEqual(prims[0].params[2], 10.0)
        a = snapshot_shape(disk)[0]
        b = snapshot_shape(self.track(Circle(center=self.at(12, 0), radius=10, spread=360)))[0]
        contact = narrow_phase(a, b)
        self.assertIsNotNone(contact)
        self.assertAlmostEqual(contact.depth, 8.0, places=5)

    def test_formula_past_full_turn_stays_circle_prim(self):
        knob = self.track(Circle(center=self.at(0, 0), radius=400))
        arc = self.track(Circle(
            center=self.at(30, 0), radius=10, spread=lambda: knob.radius,
        ))
        prims = snapshot_shape(arc)
        self.assertEqual(len(prims), 1)
        self.assertEqual(prims[0].kind, PrimKind.CIRCLE)
        self.assertEqual(prims[0].params[2], 10.0)

    def test_spread_zero_emits_nothing(self):
        arc = self.track(Circle(center=self.at(0, 0), radius=40, spread=0))
        self.assertEqual(snapshot_shape(arc), [])
        self.assertIsNone(query_collision(arc, self._probe(0, 0)))

    def test_default_pie_covers_center_and_misses_the_gap(self):
        pie = self.track(Circle(center=self.at(0, 0), radius=40, angle=0, spread=90))
        self.assertTrue(pie._use_center)
        prims = snapshot_shape(pie)
        self.assertGreaterEqual(len(prims), 1)
        self.assertTrue(all(p.kind == PrimKind.POLY for p in prims))
        self.assertIsNotNone(query_collision(pie, self._probe(0, 0)))
        self.assertIsNotNone(query_collision(pie, self._probe(20, 0)))
        self.assertIsNone(query_collision(pie, self._probe(-25, 0)))
        # Pointer follows the same filled pie.
        self.assertFalse(pie.contains_point(*self.at(-25, 0)))
        self.assertTrue(pie.contains_point(*self.at(20, 0)))

    def test_heading_turns_the_pie(self):
        pie = self.track(Circle(center=self.at(0, 0), radius=40, angle=180, spread=90))
        self.assertIsNotNone(query_collision(pie, self._probe(-20, 0)))
        self.assertIsNone(query_collision(pie, self._probe(25, 0)))

    def test_segment_excludes_the_center(self):
        seg = self.track(Circle(
            center=self.at(0, 0), radius=40, angle=0, spread=90, use_center=False,
        ))
        prims = snapshot_shape(seg)
        self.assertEqual(len(prims), 1)
        self.assertEqual(prims[0].kind, PrimKind.POLY)
        self.assertIsNone(query_collision(seg, self._probe(0, 0)))
        self.assertIsNotNone(query_collision(seg, self._probe(36, 0, radius=2)))
        self.assertIsNone(query_collision(seg, self._probe(-20, 0)))

    def test_wide_segment_includes_the_center(self):
        seg = self.track(Circle(
            center=self.at(0, 0), radius=40, angle=0, spread=270, use_center=False,
        ))
        self.assertIsNotNone(query_collision(seg, self._probe(0, 0)))
        self.assertIsNone(query_collision(seg, self._probe(-38, 0, radius=1.5)))

    def test_spread_write_rebuilds_and_translation_keeps_extra(self):
        arc = self.track(Circle(center=self.at(0, 0), radius=30, spread=360))
        key = _collision_pose_key(arc)
        self.assertEqual(snapshot_shape(arc)[0].kind, PrimKind.CIRCLE)
        arc.spread = 80
        key2 = _collision_pose_key(arc)
        self.assertNotEqual(key2[3:], key[3:])
        self.assertTrue(all(p.kind == PrimKind.POLY for p in snapshot_shape(arc)))
        arc.move_by(12, -7)
        key3 = _collision_pose_key(arc)
        self.assertEqual(key3[3:], key2[3:])
        self.assertEqual((key3[1] - key2[1], key3[2] - key2[2]), (12.0, -7.0))

    def test_proxy_disk_contains_partial_arc(self):
        arc = self.track(Circle(center=self.at(0, 0), radius=30, angle=20, spread=70))
        proxy = _proxy_aabb_for_shape(arc)
        prims = snapshot_shape(arc)
        minx = min(p.aabb[0] for p in prims)
        miny = min(p.aabb[1] for p in prims)
        maxx = max(p.aabb[2] for p in prims)
        maxy = max(p.aabb[3] for p in prims)
        self.assertLessEqual(proxy[0], minx + 1e-6)
        self.assertLessEqual(proxy[1], miny + 1e-6)
        self.assertGreaterEqual(proxy[2], maxx - 1e-6)
        self.assertGreaterEqual(proxy[3], maxy - 1e-6)
        # The circumdisk reaches past the wedge (left edge of a +x pie).
        self.assertLess(proxy[0], minx - 1.0)

    def test_pie_step_misses_the_open_side(self):
        pie = self.track(Circle(center=self.at(0, 0), radius=40, angle=0, spread=90))
        gap = self._probe(-25, 0, radius=4)
        rim = self._probe(25, 0, radius=4)
        hits = []
        pie.on_collide = lambda me, other, info: hits.append(other)
        gap.collidable = True
        rim.collidable = True
        self.step()
        self.assertIn(rim, hits)
        self.assertNotIn(gap, hits)


class TestEnterStayExit(CollisionTestCase):
    def test_enter_stay_exit(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20))
        b = self.track(Circle(center=self.at(10, 0), radius=20))
        a.collidable = True
        b.collidable = True
        log = []
        a.on_collide = lambda *a: log.append("enter")
        a.on_collide_stay = lambda *a: log.append("stay")
        a.on_collide_exit = lambda *a: log.append("exit")
        self.step()
        self.assertEqual(log, ["enter"])
        self.step()
        self.assertEqual(log, ["enter", "stay"])
        b.move_to(*self.at(200, 0))
        self.step()
        self.assertEqual(log, ["enter", "stay", "exit"])


class TestSATAndShapes(CollisionTestCase):
    def test_rotated_rects(self):
        a = self.track(Rect(center=self.at(0, 0), width=40, height=20, angle=45))
        b = self.track(Rect(center=self.at(15, 0), width=40, height=20, angle=-45))
        a.collidable = True
        b.collidable = True
        depths = []
        a.on_collide = lambda me, other, info: depths.append(info.depth)
        self.step()
        self.assertEqual(len(depths), 1)
        self.assertGreater(depths[0], 0.0)

    def test_ellipse_circle(self):
        e = self.track(Ellipse(center=self.at(0, 0), width=40, height=20, angle=0))
        c = self.track(Circle(center=self.at(25, 0), radius=10))
        e.collidable = True
        c.collidable = True
        depths = []
        e.on_collide = lambda me, other, info: depths.append(info.depth)
        self.step()
        self.assertEqual(len(depths), 1)
        self.assertAlmostEqual(depths[0], 5.0, places=4)

    def test_polygon_overlap(self):
        p1 = self.track(Polygon(points=[
            self.at(0, 0), self.at(50, 0), self.at(25, 40),
        ]))
        p2 = self.track(Polygon(points=[
            self.at(20, 10), self.at(70, 10), self.at(45, 50),
        ]))
        p1.collidable = True
        p2.collidable = True
        hits = []
        p1.on_collide = lambda *a: hits.append(1)
        self.step()
        self.assertEqual(hits, [1])

    def test_square(self):
        a = self.track(Square(center=self.at(0, 0), length=20, angle=0))
        b = self.track(Square(center=self.at(15, 0), length=20, angle=0))
        a.collidable = True
        b.collidable = True
        hits = []
        a.on_collide = lambda *a: hits.append(1)
        self.step()
        self.assertEqual(hits, [1])

    def test_line_as_obb(self):
        line = self.track(Line(p1=self.at(0, 0), p2=self.at(100, 0)))
        c = self.track(Circle(center=self.at(50, 0), radius=5))
        line.collidable = True
        c.collidable = True
        hits = []
        c.on_collide = lambda *a: hits.append(1)
        self.step()
        self.assertEqual(hits, [1])


class TestTrackStrokeCollision(CollisionTestCase):
    """Track collides as a stroke tube (chain of thin OBBs), not a filled area."""

    def test_track_line_snapshot_one_obb(self):
        t = self.track(Track(points=[self.at(0, 0), self.at(100, 0)], smooth=0, line_width=8))
        prims = snapshot_shape(t)
        self.assertEqual(len(prims), 1)
        self.assertEqual(prims[0].kind, PrimKind.OBB)
        self.assertAlmostEqual(prims[0].params[3], 4.0, places=3)  # half width

    def test_track_arc_snapshot_many_obbs(self):
        ox, oy = self.at(0, 0)
        t = self.track(Track.arc(
            center=(ox, oy), radius=80, from_angle=0, to_angle=90, line_width=6,
        ))
        prims = snapshot_shape(t)
        self.assertGreater(len(prims), 4)
        for p in prims:
            self.assertIn(p.kind, (PrimKind.OBB, PrimKind.CIRCLE))
            self.assertNotEqual(p.kind, PrimKind.POLY)

    def test_ring_hole_misses_center_hits_rim(self):
        ox, oy = self.at(0, 0)
        ring = self.track(Track.circle(
            center=(ox, oy), radius=60, color="white", line_width=10,
        ))
        hole = self.track(Circle(center=(ox, oy), radius=8))
        rim = self.track(Circle(center=(ox + 60, oy), radius=6))
        ring.collidable = True
        hole.collidable = True
        rim.collidable = True
        hole_hits = []
        rim_hits = []
        hole.on_collide = lambda *a: hole_hits.append(1)
        rim.on_collide = lambda *a: rim_hits.append(1)
        self.step()
        self.assertEqual(hole_hits, [])
        self.assertEqual(rim_hits, [1])

    def test_quarter_arc_misses_missing_sector(self):
        ox, oy = self.at(0, 0)
        arc = self.track(Track.arc(
            center=(ox, oy), radius=70, from_angle=0, to_angle=90,
            color="gold", line_width=10,
        ))
        # On the stroke near +x (angle 0).
        on = self.track(Circle(center=(ox + 70, oy), radius=5))
        # On the circle at 180° — outside the quarter arc.
        off = self.track(Circle(center=(ox - 70, oy), radius=5))
        arc.collidable = True
        on.collidable = True
        off.collidable = True
        on_hits = []
        off_hits = []
        on.on_collide = lambda *a: on_hits.append(1)
        off.on_collide = lambda *a: off_hits.append(1)
        self.step()
        self.assertEqual(on_hits, [1])
        self.assertEqual(off_hits, [])

    def test_begin_end_trims_prims_and_misses_hidden_arc(self):
        ox, oy = self.at(0, 0)
        t = self.track(Track.circle(
            center=(ox, oy), radius=50, color="cyan", line_width=4,
        ))
        t.collidable = True
        owner = t._collider
        n0 = len(snapshot_shape(t, cache_owner=owner))
        t.begin = 0.0
        t.end = 0.25
        prims = snapshot_shape(t, cache_owner=owner)
        self.assertLess(len(prims), n0)
        self.assertGreater(len(prims), 0)
        # On the visible quarter near +x (u≈0).
        on = self.track(Circle(center=(ox + 50, oy), radius=5))
        # On the hidden arc near -x (u≈0.5).
        off = self.track(Circle(center=(ox - 50, oy), radius=5))
        on.collidable = True
        off.collidable = True
        on_hits = []
        off_hits = []
        on.on_collide = lambda *a: on_hits.append(1)
        off.on_collide = lambda *a: off_hits.append(1)
        self.step()
        self.assertEqual(on_hits, [1])
        self.assertEqual(off_hits, [])

    def test_closed_wrap_window_two_open_chains_no_gap_chord(self):
        ox, oy = self.at(0, 0)
        t = self.track(Track.circle(
            center=(ox, oy), radius=60, color="gold", line_width=6,
        ))
        t.begin = 0.8
        t.end = 0.15
        t.collidable = True
        prims = snapshot_shape(t)
        self.assertGreater(len(prims), 0)
        # Body in the invisible gap (u≈0.5, -x) must miss — no chord across.
        gap = self.track(Circle(center=(ox - 60, oy), radius=5))
        gap.collidable = True
        hits = []
        gap.on_collide = lambda *a: hits.append(1)
        self.step()
        self.assertEqual(hits, [])

    def test_open_empty_window_no_prims(self):
        t = self.track(Track(
            points=[self.at(0, 0), self.at(100, 0)], smooth=0, color="gold", line_width=4,
        ))
        t.begin = 0.8
        t.end = 0.2
        t.collidable = True
        self.assertEqual(snapshot_shape(t), [])

    def test_tween_end_rebuilds_tube_without_flatten(self):
        ox, oy = self.at(0, 0)
        t = self.track(Track.circle(
            center=(ox, oy), radius=40, color="cyan", line_width=4,
        ))
        t.collidable = True
        owner = t._collider
        t.end = 0.2
        t.at(0.0)
        n_rebuilds = t._rebuilds
        n0 = len(snapshot_shape(t, cache_owner=owner))
        t.end = 0.8
        prims = snapshot_shape(t, cache_owner=owner)
        self.assertEqual(t._rebuilds, n_rebuilds)
        self.assertGreater(len(prims), n0)

    def test_full_window_prim_count_unchanged_vs_defaults(self):
        ox, oy = self.at(0, 0)
        ring = self.track(Track.circle(
            center=(ox, oy), radius=50, color="white", line_width=4,
        ))
        line = self.track(Track(
            points=[self.at(0, 0), self.at(80, 0)], smooth=0, line_width=8,
        ))
        self.assertEqual(len(snapshot_shape(line)), 1)
        self.assertGreater(len(snapshot_shape(ring)), 4)
        # Explicit full window must match default.
        ring.begin = 0.0
        ring.end = 1.0
        n = len(snapshot_shape(ring))
        ring2 = self.track(Track.circle(
            center=(ox, oy), radius=50, color="white", line_width=4,
        ))
        self.assertEqual(len(snapshot_shape(ring2)), n)

    def test_line_width_rebuilds_cached_thickness(self):
        t = self.track(Track(
            points=[self.at(0, 0), self.at(80, 0)], smooth=0, line_width=4,
        ))
        t.collidable = True
        owner = t._collider
        p0 = snapshot_shape(t, cache_owner=owner)[0]
        self.assertAlmostEqual(p0.params[3], 2.0, places=3)
        t.line_width = 16
        p1 = snapshot_shape(t, cache_owner=owner)[0]
        self.assertAlmostEqual(p1.params[3], 8.0, places=3)

    def test_zigzag_rebuilds_not_stale_tube(self):
        t = self.track(Track(
            points=[self.at(0, 0), self.at(100, 0)], smooth=0, line_width=6,
        ))
        t.collidable = True
        owner = t._collider
        n0 = len(snapshot_shape(t, cache_owner=owner))
        self.assertEqual(n0, 1)
        t.zigzag(amount=20, waves=4)
        prims = snapshot_shape(t, cache_owner=owner)
        self.assertGreater(len(prims), 1)

    def test_query_point_stroke_vs_hole(self):
        ox, oy = self.at(0, 0)
        ring = self.track(Track.circle(
            center=(ox, oy), radius=50, color="white", line_width=8,
        ))
        ring.collidable = True
        self.step()
        self.assertEqual(collision.query_point(ox, oy), [])
        hits = collision.query_point(ox + 50, oy)
        self.assertIn(ring, hits)

    def test_resolve_stops_on_static_arc_not_disk(self):
        ox, oy = self.at(0, 0)
        # Quarter arc on the right (+x). Ball approaches from farther right.
        arc = self.track(Track.arc(
            center=(ox, oy), radius=60, from_angle=-20, to_angle=20,
            color="gold", line_width=10, group="wall",
        ))
        arc.mass = STATIC
        ball = self.track(Circle(
            center=(ox + 100, oy), radius=8, group="ball",
        ))
        ball.mass = 1.0
        ball.vel = Vec2(-180, 0)
        resolve("ball", "wall", bounce=0.0)
        for _ in range(40):
            ball.move_by(ball.vel.x * 0.016, ball.vel.y * 0.016)
            self.step()
        # Stopped near the arc rim (~ox+60), not at the disk center / past it.
        self.assertGreater(float(ball.center.x), ox + 40)
        self.assertLess(float(ball.center.x), ox + 85)
        # Interior of the circle (left of center) was never a wall.
        self.assertGreater(float(ball.center.x), ox)

    def test_proxy_aabb_covers_stroke(self):
        ox, oy = self.at(0, 0)
        t = self.track(Track.arc(
            center=(ox, oy), radius=40, from_angle=0, to_angle=90, line_width=8,
        ))
        aabb = _proxy_aabb_for_shape(t)
        self.assertIsNotNone(aabb)
        minx, miny, maxx, maxy = aabb
        # Includes the +x endpoint and pads by half-width.
        self.assertLessEqual(minx, ox + 40)
        self.assertGreaterEqual(maxx, ox + 40)
        self.assertGreaterEqual(maxy, oy + 40)


class TestConcaveDecomposition(CollisionTestCase):
    def test_convexity_helper(self):
        self.assertTrue(_is_convex([(0, 0), (1, 0), (1, 1), (0, 1)]))
        concave = [(0, 0), (3, 0), (3, 1), (1, 1), (1, 2), (3, 2), (3, 3), (0, 3)]
        self.assertFalse(_is_convex(concave))
        tris = _ear_clip(concave)
        self.assertGreaterEqual(len(tris), 6)
        for t in tris:
            self.assertEqual(len(t), 3)

    def test_concave_pocket_no_hit(self):
        ox, oy = self.at(0, 0)
        concave = self.track(Polygon(points=[
            (ox, oy), (ox + 60, oy), (ox + 60, oy + 20), (ox + 20, oy + 20),
            (ox + 20, oy + 40), (ox + 60, oy + 40), (ox + 60, oy + 60), (ox, oy + 60),
        ]))
        needle = self.track(Circle(center=(ox + 40, oy + 30), radius=5))
        concave.collidable = True
        needle.collidable = True
        hits = []
        concave.on_collide = lambda *a: hits.append(1)
        self.step()
        self.assertEqual(hits, [])

    def test_concave_solid_hit(self):
        ox, oy = self.at(0, 0)
        concave = self.track(Polygon(points=[
            (ox, oy), (ox + 60, oy), (ox + 60, oy + 20), (ox + 20, oy + 20),
            (ox + 20, oy + 40), (ox + 60, oy + 40), (ox + 60, oy + 60), (ox, oy + 60),
        ]))
        needle = self.track(Circle(center=(ox + 10, oy + 30), radius=5))
        concave.collidable = True
        needle.collidable = True
        hits = []
        concave.on_collide = lambda *a: hits.append(1)
        self.step()
        self.assertEqual(hits, [1])


class TestGroupsAndPairs(CollisionTestCase):
    def test_group_tag_filter_one_registration(self):
        """One @collide(tag, tag) opts both sides in — no mirror Collider()."""
        a = self.track(Circle(center=self.at(0, 0), radius=15, group="player"))
        b = self.track(Circle(center=self.at(5, 0), radius=15, group="enemy"))
        self.track(Circle(center=self.at(5, 0), radius=15, group="bullet"))
        hits = []

        @collide("player", "enemy")
        def on_hit(me, other, info):
            hits.append((me, other))

        self.step()
        self.assertEqual(len(hits), 1)
        self.assertIs(hits[0][0], a)
        self.assertIs(hits[0][1], b)
        self.assertIn("enemy", a._collider._pair_targets)
        self.assertIn("player", b._collider._pair_targets)

    def test_collide_decorator_shapes(self):
        player = self.track(Circle(center=self.at(0, 0), radius=15))
        enemy = self.track(Circle(center=self.at(10, 0), radius=15, group="enemies"))
        hits = []

        @collide(player, enemy)
        def on_hit(me, other, info):
            hits.append((me, other, info.depth))

        self.step()
        self.assertEqual(len(hits), 1)
        self.assertIs(hits[0][0], player)
        self.assertIs(hits[0][1], enemy)

    def test_collide_string_group_tag(self):
        player = self.track(Circle(center=self.at(0, 0), radius=15))
        e1 = self.track(Circle(center=self.at(10, 0), radius=15, group="en2"))
        hits = []

        @collide(player, "en2")
        def on_hit(me, other, info):
            hits.append(other)

        self.step()
        self.assertEqual(len(hits), 1)
        hits.clear()
        e2 = self.track(Circle(center=self.at(5, 0), radius=15, group="en2"))
        self.step()
        # enter for e2 + stay would be stay phase — @collide is enter only
        # e1 was already overlapping → stay (not enter); e2 is new enter
        self.assertEqual(len(hits), 1)
        self.assertIs(hits[0], e2)

    def test_collide_live_group_operator(self):
        from scena.registry import GroupOperator
        from scena.canvas import ScenaCanvas

        player = self.track(Circle(center=self.at(0, 0), radius=15))
        e1 = self.track(Circle(center=self.at(10, 0), radius=15, group="en3"))
        hits = []
        grp = GroupOperator(ScenaCanvas.get_current().registry, group_id="en3")

        @collide(player, grp)
        def on_hit(me, other, info):
            hits.append(other)

        self.step()
        self.assertEqual(len(hits), 1)

    def test_collide_exit_decorator(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20))
        b = self.track(Circle(center=self.at(10, 0), radius=20))
        log = []

        @collide(a, b)
        def on_enter(me, other, info):
            log.append("enter")

        @collide_exit(a, b)
        def on_exit(me, other, info):
            log.append("exit")

        self.step()
        self.assertEqual(log, ["enter"])
        b.move_to(*self.at(200, 0))
        self.step()
        self.assertEqual(log, ["enter", "exit"])

    def test_collide_stay_decorator(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20))
        b = self.track(Circle(center=self.at(10, 0), radius=20))
        log = []

        @collide_stay(a, b)
        def on_stay(me, other, info):
            log.append("stay")

        self.step()
        self.assertEqual(log, [])  # first frame is enter, not stay
        self.step()
        self.assertEqual(log, ["stay"])

    def test_collide_anything(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20))
        b = self.track(Circle(center=self.at(5, 0), radius=20))
        b.collidable = True
        hits = []

        @collide(a, ANYTHING)
        def on_hit(me, other, info):
            hits.append(other)

        self.step()
        self.assertEqual(len(hits), 1)
        self.assertIs(hits[0], b)
        self.assertIn(ANYTHING, a._collider._pair_targets)

    def test_cross_product_lists(self):
        a1 = self.track(Circle(center=self.at(0, 0), radius=15))
        a2 = self.track(Circle(center=self.at(100, 0), radius=15))
        b1 = self.track(Circle(center=self.at(5, 0), radius=15))
        b2 = self.track(Circle(center=self.at(105, 0), radius=15))
        hits = []

        @collide([a1, a2], [b1, b2])
        def on_hit(me, other, info):
            hits.append((me, other))

        self.step()
        self.assertEqual(len(hits), 2)
        pairs = {(id(m), id(o)) for m, o in hits}
        self.assertIn((id(a1), id(b1)), pairs)
        self.assertIn((id(a2), id(b2)), pairs)

    def test_cross_product_tuples(self):
        a1 = self.track(Circle(center=self.at(0, 0), radius=15))
        a2 = self.track(Circle(center=self.at(100, 0), radius=15))
        b1 = self.track(Circle(center=self.at(5, 0), radius=15))
        b2 = self.track(Circle(center=self.at(105, 0), radius=15))
        hits = []

        @collide((a1, a2), (b1, b2))
        def on_hit(me, other, info):
            hits.append((me, other))

        self.step()
        self.assertEqual(len(hits), 2)

    def test_right_side_list_of_tags(self):
        a = self.track(Circle(center=self.at(0, 0), radius=15, group="player"))
        b = self.track(Circle(center=self.at(5, 0), radius=15, group="enemy"))
        w = self.track(Circle(center=self.at(5, 0), radius=15, group="wall"))
        hits = []

        @collide("player", ["enemy", "wall"])
        def on_hit(me, other, info):
            hits.append(other)

        self.step()
        self.assertEqual(len(hits), 2)
        self.assertIn(b, hits)
        self.assertIn(w, hits)

    def test_three_args_rejected(self):
        a = self.track(Circle(center=self.at(0, 0), radius=10))
        b = self.track(Circle(center=self.at(0, 0), radius=10))
        c = self.track(Circle(center=self.at(0, 0), radius=10))
        with self.assertRaises(TypeError):
            @collide(a, b, c)
            def bad(me, other, info):
                pass

    def test_named_pair_does_not_fire_unrelated_third(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20))
        b = self.track(Circle(center=self.at(5, 0), radius=20))
        c = self.track(Circle(center=self.at(5, 0), radius=20))
        hits = []

        @collide(a, c)
        def on_ac(me, other, info):
            hits.append("ac")

        self.step()
        self.assertEqual(hits, ["ac"])

    def test_on_collide_hits_enrolled_partner(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20))
        b = self.track(Circle(center=self.at(5, 0), radius=20))
        b.collidable = True
        hits = []
        a.on_collide = lambda *args: hits.append("ab")
        self.step()
        self.assertEqual(hits, ["ab"])

    def test_spawn_after_decorate_same_step(self):
        """A member constructed after @collide still fires that same step()."""
        player = self.track(Circle(center=self.at(0, 0), radius=15, group="player"))
        hits = []

        @collide("sting", "player")
        def on_hit(me, other, info):
            hits.append(me)

        sting = self.track(Circle(center=self.at(5, 0), radius=15, group="sting"))
        self.step()
        self.assertEqual(len(hits), 1)
        self.assertIs(hits[0], sting)
        self.assertIn(sting._collider, get_collision_system()._tag_colliders["sting"])

    def test_untag_mid_run_drops_index(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20, group="player"))
        b = self.track(Circle(center=self.at(5, 0), radius=20, group="enemy"))
        hits = []

        @collide("player", "enemy")
        def on_hit(me, other, info):
            hits.append(True)

        self.step()
        self.assertEqual(len(hits), 1)
        hits.clear()
        b.remove_from_group("enemy")
        sys = get_collision_system()
        self.assertNotIn(b._collider, sys._tag_colliders.get("enemy", ()))
        self.step()
        self.step()
        self.assertEqual(hits, [])

    def test_two_handlers_sharing_a_tag(self):
        player = self.track(Circle(center=self.at(0, 0), radius=15, group="player"))
        enemy = self.track(Circle(center=self.at(5, 0), radius=15, group="enemy"))
        wall = self.track(Circle(center=self.at(5, 0), radius=15, group="wall"))
        hits = []

        @collide("player", "enemy")
        def on_enemy(me, other, info):
            hits.append("enemy")

        @collide("player", "wall")
        def on_wall(me, other, info):
            hits.append("wall")

        self.step()
        self.assertEqual(sorted(hits), ["enemy", "wall"])
        sys = get_collision_system()
        self.assertEqual(len(sys._tag_colliders["player"]), 1)
        self.assertIs(sys._tag_colliders["player"][0], player._collider)

    def test_enroll_count_is_membership_not_step(self):
        """ensure/bake enroll runs for new members, not live N each step."""
        self.track(Circle(center=self.at(0, 0), radius=15, group="player"))
        self.track(Circle(center=self.at(5, 0), radius=15, group="enemy"))
        sys = get_collision_system()

        @collide("player", "enemy")
        def on_hit(me, other, info):
            pass

        n0 = sys._debug_enroll_count
        self.step()
        self.step()
        self.step()
        self.assertEqual(sys._debug_enroll_count, n0)
        self.track(Circle(center=self.at(4, 0), radius=15, group="enemy"))
        self.assertEqual(sys._debug_enroll_count, n0 + 1)
        self.step()
        self.assertEqual(sys._debug_enroll_count, n0 + 1)


class TestCollisionInfoPoint(CollisionTestCase):
    def test_empty_is_none(self):
        info = CollisionInfo(a=None, b=None, normal=Vec2.temp(0, 0), depth=0.0, points=[])
        self.assertIsNone(info.point)

    def test_one_is_identity(self):
        pt = (12.5, -3.0)
        info = CollisionInfo(a=None, b=None, normal=Vec2.temp(1, 0), depth=1.0, points=[pt])
        self.assertIs(info.point, pt)
        self.assertEqual(info.point, (12.5, -3.0))

    def test_two_is_midpoint(self):
        info = CollisionInfo(
            a=None, b=None, normal=Vec2.temp(0, 1), depth=2.0,
            points=[(0.0, 0.0), (10.0, 4.0)],
        )
        self.assertEqual(info.point, (5.0, 2.0))

    def test_three_is_centroid(self):
        info = CollisionInfo(
            a=None, b=None, normal=Vec2.temp(1, 0), depth=1.0,
            points=[(0.0, 0.0), (6.0, 0.0), (0.0, 6.0)],
        )
        self.assertEqual(info.point, (2.0, 2.0))

    def test_live_circle_circle_surface(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20))
        b = self.track(Circle(center=self.at(30, 0), radius=20))
        a.collidable = True
        b.collidable = True
        seen = []

        def on_hit(me, other, info):
            seen.append(info.point)

        a.on_collide = on_hit
        self.step()
        self.assertEqual(len(seen), 1)
        pt = seen[0]
        self.assertIsNotNone(pt)
        self.assertEqual(len(pt), 2)
        ox, oy = self.at(0, 0)
        # Contact on A's +x surface: center + (r, 0) along a→b
        self.assertAlmostEqual(pt[0], ox + 20.0, places=4)
        self.assertAlmostEqual(pt[1], oy, places=4)

    def test_live_exit_has_no_point(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20))
        b = self.track(Circle(center=self.at(10, 0), radius=20))
        a.collidable = True
        b.collidable = True
        exit_payloads = []

        a.on_collide = lambda *args: None
        a.on_collide_exit = lambda me, other, info: exit_payloads.append(
            (info.point, list(info.points))
        )
        self.step()
        b.move_to(*self.at(200, 0))
        self.step()
        self.assertEqual(len(exit_payloads), 1)
        self.assertIsNone(exit_payloads[0][0])
        self.assertEqual(exit_payloads[0][1], [])

    def test_points_or_witness_keeps_clip(self):
        pa = Prim(PrimKind.AABB, (0, 0, 10, 10), (0, 0, 10, 10))
        pb = Prim(PrimKind.AABB, (8, 0, 18, 10), (8, 0, 18, 10))
        clip = [(10.0, 5.0)]
        self.assertEqual(
            _points_or_witness(clip, [pa], [pb], 1.0, 0.0),
            clip,
        )

    def test_points_or_witness_empty_uses_support(self):
        # Small box into a wide wall's left face (same layout as the manifold tests).
        pa = Prim(PrimKind.AABB, (-114, -15, -74, 15), (-114, -15, -74, 15))
        pb = Prim(PrimKind.AABB, (-80, -18, 80, 18), (-80, -18, 80, 18))
        pts = _points_or_witness([], [pa], [pb], 1.0, 0.0)
        self.assertEqual(len(pts), 1)
        px, py = pts[0]
        self.assertTrue(-80.5 <= px <= -73.5, f"witness x={px} not on the shared face")
        self.assertGreater(abs(px - (-47.0)), 15.0)
        self.assertLess(abs(py), 18.0)

    def test_points_or_witness_zero_normal_stays_empty(self):
        pa = Prim(PrimKind.AABB, (0, 0, 10, 10), (0, 0, 10, 10))
        pb = Prim(PrimKind.AABB, (8, 0, 18, 10), (8, 0, 18, 10))
        self.assertEqual(_points_or_witness([], [pa], [pb], 0.0, 0.0), [])

    def test_stay_has_point(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20))
        b = self.track(Circle(center=self.at(10, 0), radius=20))
        a.collidable = True
        b.collidable = True
        stay = []
        a.on_collide = lambda *args: None
        a.on_collide_stay = lambda me, other, info: stay.append(info.point)
        self.step()
        self.step()
        self.assertEqual(len(stay), 1)
        self.assertIsNotNone(stay[0])
        self.assertEqual(len(stay[0]), 2)

    def test_enter_empty_clip_gets_support_witness(self):
        import sys
        a = self.track(Circle(center=self.at(0, 0), radius=20))
        b = self.track(Circle(center=self.at(30, 0), radius=20))
        a.collidable = True
        b.collidable = True
        seen = []

        def on_hit(me, other, info):
            seen.append(info.point)

        a.on_collide = on_hit
        mod = sys.modules[CollisionInfo.__module__]
        real = mod.narrow_phase

        def stripped(pa, pb):
            c = real(pa, pb)
            if c is None:
                return None
            return Contact(c.normal, c.depth, [])

        mod.narrow_phase = stripped
        try:
            self.step()
        finally:
            mod.narrow_phase = real
        self.assertEqual(len(seen), 1)
        pt = seen[0]
        self.assertIsNotNone(pt)
        ox, oy = self.at(0, 0)
        # Support witness sits on the overlapping interval, not a body center.
        self.assertNotEqual(pt, (ox, oy))
        self.assertNotEqual(pt, (ox + 30.0, oy))
        self.assertAlmostEqual(pt[1], oy, places=4)
        self.assertGreater(pt[0], ox)
        self.assertLess(pt[0], ox + 30.0)


def _prim_boundary_dist(prim, pt):
    from scena.collision import _closest_point_on_poly, _prim_as_poly
    if prim.kind == PrimKind.CIRCLE:
        cx, cy, r = prim.params[0], prim.params[1], prim.params[2]
        return abs(math.hypot(pt[0] - cx, pt[1] - cy) - r)
    if prim.kind == PrimKind.ELLIPSE:
        # Approximate: OBB corners aren't the ellipse; use SAT contact tests instead.
        return None
    verts = _prim_as_poly(prim)
    qx, qy = _closest_point_on_poly(pt[0], pt[1], verts)
    return math.hypot(pt[0] - qx, pt[1] - qy)


class TestContactManifold(CollisionTestCase):
    """Contact points sit on the shared face, not the midpoint of body centers."""

    def _hit(self, a, b):
        a.collidable = True
        b.collidable = True
        seen = []

        def on_hit(me, other, info):
            seen.append(info)

        a.on_collide = on_hit
        self.step()
        return seen

    def test_aabb_side_on_face_not_centers(self):
        ox, oy = self.at(0, 0)
        wall = self.track(Rect(center=(ox, oy), width=160, height=36, angle=0))
        # 40×30 box overlapping the left face by 6 px.
        box = self.track(Rect(center=(ox - 94.0, oy), width=40, height=30, angle=0))
        seen = self._hit(box, wall)
        self.assertEqual(len(seen), 1)
        pt = seen[0].point
        self.assertIsNotNone(pt)
        left = ox - 80.0
        depth = seen[0].depth
        box_cx = ox - 94.0
        mid = (ox + box_cx) * 0.5
        # On either colliding face (wall left or box right), within the penetration.
        self.assertLess(min(abs(pt[0] - left), abs(pt[0] - (left + depth))), 1.5)
        self.assertGreater(abs(pt[0] - mid), 15.0)
        self.assertLess(abs(pt[1] - oy), 20.0)

    def test_aabb_top_on_face(self):
        ox, oy = self.at(0, 0)
        wall = self.track(Rect(center=(ox, oy), width=160, height=36, angle=0))
        box = self.track(Rect(center=(ox, oy + 28.0), width=40, height=30, angle=0))
        seen = self._hit(box, wall)
        self.assertEqual(len(seen), 1)
        pt = seen[0].point
        top = oy + 18.0
        depth = seen[0].depth
        self.assertLess(min(abs(pt[1] - top), abs(pt[1] - (top - depth))), 1.5)
        self.assertLess(abs(pt[0] - ox), 25.0)

    def test_obb_side_on_face_not_centers(self):
        ox, oy = self.at(0, 0)
        ang = 12.0
        wall = self.track(Rect(center=(ox, oy), width=160, height=36, angle=ang))
        rad = math.radians(ang)
        c, s = math.cos(rad), math.sin(rad)
        # Same local placement as the AABB case: local x = -94, y = 0.
        lx = -94.0
        box = self.track(Rect(
            center=(ox + lx * c, oy + lx * s), width=40, height=30, angle=ang,
        ))
        seen = self._hit(box, wall)
        self.assertEqual(len(seen), 1)
        pt = seen[0].point
        self.assertIsNotNone(pt)
        wprim = snapshot_shape(wall)[0]
        dist = _prim_boundary_dist(wprim, pt)
        self.assertIsNotNone(dist)
        self.assertLess(dist, seen[0].depth + 1.5)
        bcx, bcy = ox + lx * c, oy + lx * s
        mid = ((ox + bcx) * 0.5, (oy + bcy) * 0.5)
        self.assertGreater(math.hypot(pt[0] - mid[0], pt[1] - mid[1]), 15.0)

    def test_sat_poly_side_on_face_not_centers(self):
        ox, oy = self.at(0, 0)
        wall = self.track(Rect(center=(ox, oy), width=160, height=36, angle=12))
        hexagon = self.track(RegularPolygon(n=6, center=(ox - 100.0, oy), radius=28))
        seen = self._hit(hexagon, wall)
        self.assertEqual(len(seen), 1)
        pt = seen[0].point
        self.assertIsNotNone(pt)
        dist = _prim_boundary_dist(snapshot_shape(wall)[0], pt)
        self.assertLess(dist, seen[0].depth + 1.5)
        mid = ((ox + ox - 100.0) * 0.5, oy)
        self.assertGreater(abs(pt[0] - mid[0]), 15.0)

    def test_circle_aabb_side_on_wall(self):
        ox, oy = self.at(0, 0)
        wall = self.track(Rect(center=(ox, oy), width=160, height=36, angle=0))
        ball = self.track(Circle(center=(ox - 80.0 - 22.0, oy), radius=28))
        seen = self._hit(ball, wall)
        self.assertEqual(len(seen), 1)
        pt = seen[0].point
        self.assertAlmostEqual(pt[0], ox - 80.0, places=3)
        self.assertAlmostEqual(pt[1], oy, places=3)

    def test_circle_obb_side_on_wall(self):
        ox, oy = self.at(0, 0)
        ang = 12.0
        wall = self.track(Rect(center=(ox, oy), width=160, height=36, angle=ang))
        rad = math.radians(ang)
        c, s = math.cos(rad), math.sin(rad)
        # Circle center 22 px outside the local left face (r=28 → 6 px overlap).
        lx = -80.0 - 22.0
        ball = self.track(Circle(center=(ox + lx * c, oy + lx * s), radius=28))
        seen = self._hit(ball, wall)
        self.assertEqual(len(seen), 1)
        pt = seen[0].point
        dist = _prim_boundary_dist(snapshot_shape(wall)[0], pt)
        self.assertLess(dist, 1.5)

    def test_narrow_aabb_side_not_center_midpoint(self):
        pa = Prim(PrimKind.AABB, (-120, -20, -70, 20), (-120, -20, -70, 20))
        pb = Prim(PrimKind.AABB, (-80, -18, 80, 18), (-80, -18, 80, 18))
        contact = narrow_phase(pa, pb)
        self.assertIsNotNone(contact)
        xs = [p[0] for p in contact.points]
        self.assertTrue(xs)
        for x in xs:
            self.assertTrue(-80.5 <= x <= -69.5, f"side contact x={x} not on a face")
        cx = sum(xs) / len(xs)
        self.assertGreater(abs(cx - (-47.5)), 15.0)

    def test_face_hit_can_yield_two_clip_points(self):
        pa = Prim(PrimKind.AABB, (-120, -20, -70, 20), (-120, -20, -70, 20))
        pb = Prim(PrimKind.AABB, (-80, -18, 80, 18), (-80, -18, 80, 18))
        contact = narrow_phase(pa, pb)
        self.assertGreaterEqual(len(contact.points), 1)
        if len(contact.points) == 2:
            info = CollisionInfo(
                a=None, b=None,
                normal=Vec2.temp(contact.normal[0], contact.normal[1]),
                depth=contact.depth,
                points=list(contact.points),
            )
            mid = info.point
            self.assertAlmostEqual(
                mid[0], (contact.points[0][0] + contact.points[1][0]) * 0.5, places=6,
            )


class TestResolutionHelpers(CollisionTestCase):
    def test_mtv_split_static(self):
        info = CollisionInfo(a=None, b=None, normal=Vec2.temp(1, 0), depth=10)
        push_a, push_b = info.mtv_split(mass_a=1.0, mass_b=float("inf"))
        self.assertAlmostEqual(push_a[0], -10.0)
        self.assertAlmostEqual(push_a[1], 0.0)
        self.assertEqual(push_b, (0.0, 0.0))

    def test_mtv_split_equal_mass(self):
        info = CollisionInfo(a=None, b=None, normal=Vec2.temp(0, 1), depth=8)
        push_a, push_b = info.mtv_split(mass_a=1.0, mass_b=1.0)
        self.assertAlmostEqual(push_a[1], -4.0)
        self.assertAlmostEqual(push_b[1], 4.0)

    def test_reflect_velocity(self):
        info = CollisionInfo(a=None, b=None, normal=Vec2.temp(1, 0), depth=1)
        v = info.reflect_velocity((10, 5), restitution=1.0)
        self.assertAlmostEqual(float(v.x), -10.0)
        self.assertAlmostEqual(float(v.y), 5.0)


class TestQueries(CollisionTestCase):
    def test_query_point_and_circle(self):
        c = self.track(Circle(center=self.at(50, 50), radius=20))
        c.collidable = True
        self.step()
        ox, oy = self.at(50, 50)
        self.assertIn(c, collision.query_point(ox, oy))
        self.assertIn(c, collision.query_circle(ox, oy, 5))
        self.assertEqual(collision.query_point(ox + 100, oy), [])

    def test_raycast(self):
        c = self.track(Circle(center=self.at(50, 50), radius=20))
        c.collidable = True
        self.step()
        hit = collision.raycast(self.at(0, 50), p2=self.at(100, 50))
        self.assertIsNotNone(hit)
        ident, t, pt = hit
        self.assertIs(ident, c)
        self.assertGreaterEqual(t, 0.0)
        self.assertLessEqual(t, 1.0)

    def test_destroy_prunes_collider(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20))
        b = self.track(Circle(center=self.at(5, 0), radius=20))
        a.collidable = True
        b.collidable = True
        self.step()
        a.destroy()
        self._owned.remove(a)
        self.step()
        self.assertEqual(len([c for c in get_collision_system()._colliders if c.shapes]), 1)


class TestPieceThatIsAlsoABody(CollisionTestCase):
    """AC10 (decided 2026-10-10: two boundaries, made coherent). A shape inside
    ``Collider([torso, head])`` may also be a body of its own (``collidable``,
    or a rule that names its group): the weak-point pattern. The two bodies
    stay separate, but the boss never touches its own torso, and the queries
    answer the same whatever line ran first: the multi-piece body first."""

    def _boss(self, flag_first, ox=0):
        torso = self.track(Rect(center=self.at(ox, 0), width=60, height=40, group="ac10_fraco"))
        head = self.track(Circle(center=self.at(ox, 35), radius=12))
        if flag_first:
            torso.collidable = True
            boss = Collider([torso, head])
        else:
            boss = Collider([torso, head])
            torso.collidable = True
        return torso, head, boss

    def test_the_body_never_touches_its_own_piece(self):
        for flag_first in (True, False):
            with self.subTest(flag_first=flag_first):
                torso, _head, boss = self._boss(flag_first, ox=0 if flag_first else 600)
                others = []
                boss.on_collide = lambda me, o, info: others.append(o)
                torso.on_collide = lambda me, o, info: others.append(me if o is boss else None)
                self.step()
                self.step()
                self.assertNotIn(torso, others)
                self.assertNotIn(boss, others)

    def test_two_weak_points_of_one_body_never_touch(self):
        # Release audit 2026-10-11: AC10 kept a body off its own pieces, but two
        # pieces that are bodies of their own (two weak points) still collided
        # with each other every frame.
        torso = self.track(Rect(center=self.at(0, 0), width=60, height=40))
        head = self.track(Circle(center=self.at(0, 25), radius=12))
        torso.collidable = True
        head.collidable = True
        Collider([torso, head])
        touches = []
        torso.on_collide = lambda me, o, info: touches.append(o)
        head.on_collide = lambda me, o, info: touches.append(o)
        self.step()
        self.step()
        self.assertEqual(touches, [])
        # Two separate bodies that overlap still touch.
        other = self.track(Circle(center=self.at(0, 25), radius=12))
        other.collidable = True
        self.step()
        self.assertIn(other, touches)

    def test_weak_point_and_body_each_see_the_shot(self):
        torso, _head, boss = self._boss(True)
        seen = []

        @collide("ac10_tiro", "ac10_fraco")
        def fraco(t, o):
            seen.append(("fraco", o))

        boss.on_collide = lambda me, o, info: seen.append(("boss", me))
        self.track(Circle(center=self.at(0, 0), radius=4, group="ac10_tiro"))
        self.step()
        self.assertIn(("fraco", torso), seen)
        self.assertIn(("boss", boss), seen)
        self.assertEqual(len(seen), 2)

    def test_queries_name_the_body_first_in_either_order(self):
        for flag_first in (True, False):
            with self.subTest(flag_first=flag_first):
                torso, _head, boss = self._boss(flag_first)
                x, y = self.at(0, 0)
                hit = collision.raycast((x - 300, y), p2=(x + 300, y))
                self.assertIs(hit[0], boss)
                hit = collision.raycast((x - 300, y), p2=(x + 300, y), group="ac10_fraco")
                self.assertIs(hit[0], torso)
                at = collision.query_point(x, y)
                self.assertEqual(at[:2], [boss, torso])
                for spread in (40, 0):         # a wedge, and the segment case
                    cone = collision.query_sector((x - 100, y), angle=0, radius=200, spread=spread)
                    self.assertEqual(cone[:2], [boss, torso], f"spread={spread}")
                self.assertNotIn(boss, collision.query_shape(torso))
                for s in (torso, _head):
                    s.destroy()

    def test_a_resolve_on_the_piece_does_not_push_it_out_of_its_body(self):
        torso, _head, boss = self._boss(True)
        resolve(torso, ANYTHING)
        before = (float(torso.center.x), float(torso.center.y))
        for _ in range(5):
            self.step()
        self.assertEqual((float(torso.center.x), float(torso.center.y)), before)


class TestCompoundCollider(CollisionTestCase):
    def test_collider_comes_with_the_star_import(self):
        # The only author import is ``from scena import *``: a documented
        # class must be in ``scena.__all__`` (the Guia once taught
        # ``from scena.collision import Collider``).
        import inspect
        import scena
        self.assertIn("Collider", scena.__all__)
        ns = {}
        exec("from scena import *", ns)
        self.assertIs(ns["Collider"], Collider)
        # Author surface only: the shapes, and the three phase callbacks.
        self.assertEqual(list(inspect.signature(Collider).parameters), ["shapes"])
        torso = self.track(Rect(center=self.at(0, 0), width=20, height=40, angle=0))
        body = Collider([torso])
        public = sorted(n for n in dir(body) if not n.startswith("_"))
        self.assertEqual(public, ["on_collide", "on_collide_exit", "on_collide_stay", "shapes"])

    def test_compound_identity(self):
        torso = self.track(Rect(center=self.at(0, 0), width=20, height=40, angle=0))
        head = self.track(Circle(center=self.at(0, 30), radius=10))
        other = self.track(Circle(center=self.at(5, 30), radius=10))
        boss = Collider([torso, head])
        other.collidable = True
        hits = []
        boss.on_collide = lambda me, o, info: hits.append(me)
        self.step()
        self.assertEqual(len(hits), 1)
        self.assertIs(hits[0], boss)

    def test_non_shape_pieces_are_refused_before_registration(self):
        # Gate find (A33): Collider(shapes=<lambda>) was accepted and registered
        # a body with no geometry that nothing could unregister.
        sys_ = get_collision_system()
        torso = self.track(Rect(center=self.at(0, 0), width=20, height=40, angle=0))
        for junk in (lambda: 0, 3, "torso", (10, 20), [None], [torso, 7]):
            with self.subTest(pieces=junk):
                before = (len(sys_._colliders), len(sys_._collider_index))
                with self.assertRaisesRegex(TypeError, "Collider pieces must be shapes") as ctx:
                    Collider(junk)
                self.assertNotIn("<", str(ctx.exception))   # no object reprs
                self.assertEqual((len(sys_._colliders), len(sys_._collider_index)), before)
                self.assertIsNone(getattr(torso, "_collider", None))


class TestProxyBroadPhase(CollisionTestCase):
    """Collider proxy AABB → prim AABB → narrow (Option A)."""

    def test_stats_populated(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20))
        b = self.track(Circle(center=self.at(30, 0), radius=20))
        b.collidable = True
        a.on_collide = lambda *args: None
        self.step()
        stats = get_collision_system().last_stats
        self.assertEqual(stats["proxies"], 2)
        self.assertEqual(stats["prims"], 2)
        self.assertGreaterEqual(stats["proxy_pairs"], 1)
        self.assertGreaterEqual(stats["narrow"], 1)
        self.assertGreater(stats["ms_total"], 0.0)

    def test_separated_proxies_skip_narrow(self):
        a = self.track(Circle(center=self.at(0, 0), radius=10))
        b = self.track(Circle(center=self.at(200, 0), radius=10))
        a.collidable = True
        b.collidable = True
        self.step()
        stats = get_collision_system().last_stats
        self.assertEqual(stats["proxy_pairs"], 0)
        self.assertEqual(stats["narrow"], 0)

    def test_compound_proxy_unions_prims(self):
        # Two far-apart parts on one compound; probe overlaps only the head.
        torso = self.track(Rect(center=self.at(0, 0), width=20, height=20, angle=0))
        head = self.track(Circle(center=self.at(80, 0), radius=12))
        probe = self.track(Circle(center=self.at(80, 0), radius=8))
        boss = Collider([torso, head])
        probe.collidable = True
        hits = []
        boss.on_collide = lambda *a: hits.append(1)
        self.step()
        self.assertEqual(len(hits), 1)
        stats = get_collision_system().last_stats
        self.assertEqual(stats["proxies"], 2)
        self.assertEqual(stats["prims"], 3)  # torso + head + probe
        self.assertGreaterEqual(stats["proxy_pairs"], 1)

    def test_focused_interest_filters_before_narrow(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20, group="a"))
        b = self.track(Circle(center=self.at(10, 0), radius=20, group="b"))
        c = self.track(Circle(center=self.at(5, 0), radius=20, group="c"))
        hits = []

        @collide(a, b)
        def on_ab(me, other, info):
            hits.append("ab")

        # c is FOCUSED with no pair involving a/b interest toward c from OPEN…
        # a,b are FOCUSED via @collide; c not enrolled → only ab.
        self.step()
        self.assertEqual(hits, ["ab"])
        stats = get_collision_system().last_stats
        # Only two FOCUSED colliders enrolled (a,b); c never opted in.
        self.assertEqual(stats["proxies"], 2)

    def test_multi_prim_near_miss_no_false_hit(self):
        # Compound with two circles; probe sits in the gap between them.
        left = self.track(Circle(center=self.at(-30, 0), radius=12))
        right = self.track(Circle(center=self.at(30, 0), radius=12))
        probe = self.track(Circle(center=self.at(0, 0), radius=8))
        body = Collider([left, right])
        probe.collidable = True
        hits = []
        body.on_collide = lambda *a: hits.append(1)
        self.step()
        # Proxies may overlap (union AABB covers the gap) but prims should not.
        self.assertEqual(hits, [])
        stats = get_collision_system().last_stats
        self.assertGreaterEqual(stats["proxy_pairs"], 1)
        # Narrow may run after prim AABB overlap fails → narrow can be 0.
        self.assertEqual(stats["narrow"], 0)

    def test_cross_tag_vectorized_pairs_match_nested_and_dedupe(self):
        """8×8 A×B pools: numpy AABB hits match nested Python; @collide+resolve unique."""
        import numpy as np

        n = 10
        fleet = [
            self.track(Circle(center=self.at(i * 80, 0), radius=12, group="fleet"))
            for i in range(n)
        ]
        geom = [
            self.track(Circle(center=self.at(i * 80 + (4 if i < 4 else 2000), 0),
                              radius=12, group="geom"))
            for i in range(n)
        ]

        @collide("fleet", "geom")
        def on_hit(me, other, info):
            pass

        resolve("fleet", "geom")

        sys_ = get_collision_system()
        live = []
        for c in sys_._colliders:
            if sys_._update_proxy(c):
                live.append(c)
        proxy = np.zeros((len(live), 4), dtype=np.float64)
        for i, c in enumerate(live):
            p = c._proxy
            proxy[i, 0] = p[0]
            proxy[i, 1] = p[1]
            proxy[i, 2] = p[2]
            proxy[i, 3] = p[3]

        got = sys_._declared_broad_pairs(live, proxy)
        self.assertEqual(len(got), len(set(got)), "duplicate (lo, hi) from seen")

        idx = {id(c): i for i, c in enumerate(live)}
        left_ids = [idx[id(c._collider)] for c in fleet if id(c._collider) in idx]
        right_ids = [idx[id(c._collider)] for c in geom if id(c._collider) in idx]
        expected = set()
        for ia in left_ids:
            a = proxy[ia]
            for jb in right_ids:
                b = proxy[jb]
                if a[0] > b[2] or b[0] > a[2] or a[1] > b[3] or b[1] > a[3]:
                    continue
                lo, hi = (ia, jb) if ia < jb else (jb, ia)
                expected.add((lo, hi))
        self.assertEqual(set(got), expected)
        self.assertEqual(len(expected), 4)


class TestLazyHull(CollisionTestCase):
    def test_poly_still_contacts_when_overlapping(self):
        a = self.track(Polygon(points=[
            self.at(0, 0), self.at(20, 0), self.at(20, 20), self.at(0, 20),
        ]))
        b = self.track(Polygon(points=[
            self.at(10, 10), self.at(30, 10), self.at(30, 30), self.at(10, 30),
        ]))
        a.collidable = True
        b.collidable = True
        hits = []
        a.on_collide = lambda *args: hits.append(True)
        self.step()
        self.assertEqual(len(hits), 1)

    def test_translation_only_moving_overlap(self):
        a = self.track(Polygon(points=[
            self.at(0, 0), self.at(16, 0), self.at(16, 16), self.at(0, 16),
        ]))
        b = self.track(Polygon(points=[
            self.at(80, 0), self.at(96, 0), self.at(96, 16), self.at(80, 16),
        ]))
        a.collidable = True
        b.collidable = True
        hits = []
        a.on_collide = lambda *args: hits.append(True)
        self.step()
        self.assertEqual(hits, [])
        b.move_by(-70, 0)
        self.step()
        self.assertEqual(len(hits), 1)

    def test_no_overlap_mass_skips_hull_transform(self):
        bodies = [
            self.track(Circle(center=self.at(i * 80, 0), radius=10))
            for i in range(8)
        ]
        for s in bodies:
            s.collidable = True
        self.step()
        n = get_collision_system()._debug_hull_builds
        for s in bodies:
            s.move_by(0, 4)
        self.step()
        self.step()
        self.assertEqual(get_collision_system()._debug_hull_builds, n)
        stats = get_collision_system().last_stats
        self.assertEqual(stats["proxy_pairs"], 0)
        self.assertEqual(stats["narrow"], 0)

    def _spinner(self, x, y, group):
        spr = self.track(Sprite(center=self.at(x, y), size=24, hitbox_shape="rect", group=group))
        spr._hitbox_kind = "auto"
        spr._hitbox_boxes = ((0.0, 0.0, 1.0, 0.4),)
        spr._recompute_hitbox_local_radius()
        spr._auto_baked = True
        return spr

    def test_collide_only_spinners_build_no_hulls(self):
        """Rotation misses the translate path; without an overlap, still no hull.

        Resolved bounds are for ``resolve()`` recovery only. Building them for
        every collider rebuilt each spinner's hull every frame.
        """
        spinners = [self._spinner(i * 90, 0, "spin_a") for i in range(6)]
        others = [self._spinner(i * 90, 300, "spin_b") for i in range(4)]

        @collide("spin_a", "spin_b")
        def _hit(a, b):
            pass

        self.step()
        sys_ = get_collision_system()
        n = sys_._debug_hull_builds
        for k in range(3):
            for s in spinners + others:
                s.angle = 17.0 * (k + 1)
            self.step()
        self.assertEqual(sys_._debug_hull_builds, n)
        self.assertEqual(sys_.last_stats["proxy_pairs"], 0)
        self.assertIn("ms_bounds", sys_.last_stats)
        for s in spinners + others:
            self.assertIsNone(s._collider._resolved_aabb)

    def test_resolved_bounds_follow_resolve_membership(self):
        floor = self.track(Rect(center=self.at(0, -40), width=200, height=20, group="rb_floor"))
        floor.mass = STATIC
        body = self.track(Rect(center=self.at(0, 0), width=20, height=20, group="rb_body"))
        body.mass = 1.0
        body.vel = Vec2(0.0, 0.0)
        bystander = self.track(Circle(center=self.at(300, 0), radius=5, group="rb_other"))

        @collide("rb_other", "rb_body")
        def _hit(a, b):
            pass

        resolve("rb_body", "rb_floor", bounce=0.0)
        self.step()
        self.assertIsNotNone(body._collider._resolved_aabb)
        self.assertIsNotNone(floor._collider._resolved_aabb)
        self.assertIsNone(bystander._collider._resolved_aabb)

        unresolve("rb_body", "rb_floor")
        self.step()
        self.assertIsNone(body._collider._resolved_aabb)
        # The floor was enrolled only by the pair: it leaves collision with it
        # (review 2026-10-09 S8-7); the body stays for its @collide.
        self.assertIsNone(floor._collider)

    def test_narrow_loop_walks_pose_keys_once_per_collider(self):
        """A spinner in several proxy pairs walks its pose key once in narrow."""
        from unittest import mock
        col = sys.modules["scena.collision"]
        hub = self._spinner(0, 0, "hub")
        rim = [
            self.track(Circle(center=self.at(dx, dy), radius=6, group="rim"))
            for dx, dy in ((10, 0), (-10, 0), (0, 10))
        ]

        @collide("hub", "rim")
        def _hit(a, b):
            pass

        self.step()
        self.step()
        hub.angle = 30.0
        calls = []
        real = col._collision_pose_key

        def counting(shape):
            calls.append(shape)
            return real(shape)

        with mock.patch.object(col, "_collision_pose_key", counting):
            self.step()
        self.assertEqual(get_collision_system().last_stats["proxy_pairs"], 3)
        # One walk per collider in ``_update_proxy``, plus one hub rebuild.
        self.assertLessEqual(len(calls), len(rim) + 1 + 1)
        self.assertEqual(sum(1 for s in calls if s is hub), 2)


class TestSnapshot(CollisionTestCase):
    def test_snapshot_kinds(self):
        c = self.track(Circle(center=self.at(0, 0), radius=5))
        prims = snapshot_shape(c)
        self.assertEqual(prims[0].kind, PrimKind.CIRCLE)

        r = self.track(Rect(center=self.at(0, 0), width=10, height=10, angle=0))
        self.assertEqual(snapshot_shape(r)[0].kind, PrimKind.AABB)

        r2 = self.track(Rect(center=self.at(0, 0), width=10, height=10, angle=30))
        self.assertEqual(snapshot_shape(r2)[0].kind, PrimKind.OBB)

        rounded = self.track(
            Rect(center=self.at(0, 0), width=10, height=10, angle=0, corner_radius=3)
        )
        self.assertEqual(snapshot_shape(rounded)[0].kind, PrimKind.AABB)

    def test_rect_angle_assign_rebuilds_cached_obb(self):
        """``.angle =`` must not slide an unrotated hull (contact.py path)."""
        r = self.track(Rect(center=self.at(0, 0), width=80, height=20, angle=0))
        r.collidable = True
        owner = r._collider
        p0 = snapshot_shape(r, cache_owner=owner)[0]
        self.assertEqual(p0.kind, PrimKind.AABB)
        r.angle = 90.0
        p1 = snapshot_shape(r, cache_owner=owner)[0]
        self.assertEqual(p1.kind, PrimKind.OBB)
        minx, miny, maxx, maxy = p1.aabb
        self.assertAlmostEqual(maxx - minx, 20.0, places=2)
        self.assertAlmostEqual(maxy - miny, 80.0, places=2)

    def test_regular_polygon_angle_assign_rebuilds_cached_poly(self):
        hex_ = self.track(RegularPolygon(n=4, center=self.at(0, 0), radius=50, angle=0))
        hex_.collidable = True
        owner = hex_._collider
        p0 = snapshot_shape(hex_, cache_owner=owner)[0]
        v0 = [(round(x, 3), round(y, 3)) for x, y in (p0.verts or ())]
        hex_.angle = 45.0
        p1 = snapshot_shape(hex_, cache_owner=owner)[0]
        v1 = [(round(x, 3), round(y, 3)) for x, y in (p1.verts or ())]
        self.assertNotEqual(v0, v1)

    def test_regular_polygon_does_not_inherit_vertex_pose_extra(self):
        self.assertTrue(callable(Polygon._collision_pose_extra))
        self.assertIsNot(
            RegularPolygon._collision_pose_extra,
            Polygon._collision_pose_extra,
        )
        self.assertIsNot(
            EquilateralTriangle._collision_pose_extra,
            Polygon._collision_pose_extra,
        )
        self.assertTrue(callable(RegularPolygon._collision_pose_extra))
        self.assertTrue(callable(EquilateralTriangle._collision_pose_extra))

    def test_irregular_polygon_vertex_move_rebuilds_cached_poly(self):
        poly = self.track(Polygon(points=[
            self.at(0, 0), self.at(40, 0), self.at(20, 30),
        ]))
        poly.collidable = True
        owner = poly._collider
        p0 = snapshot_shape(poly, cache_owner=owner)[0]
        old = [(round(x, 3), round(y, 3)) for x, y in (p0.verts or ())]
        poly.points[0]._takein(self.at(200, 0))
        p1 = snapshot_shape(poly, cache_owner=owner)[0]
        got = list(p1.verts or ())
        expected = [(float(v.x), float(v.y)) for v in poly.points]
        self.assertEqual(len(got), len(expected))
        for (gx, gy), (ex, ey) in zip(got, expected):
            self.assertAlmostEqual(gx, ex, places=3)
            self.assertAlmostEqual(gy, ey, places=3)
        self.assertNotEqual(
            [(round(x, 3), round(y, 3)) for x, y in got],
            old,
        )

    def test_irregular_polygon_move_by_does_not_rebuild(self):
        sys = get_collision_system()
        poly = self.track(Polygon(points=[
            self.at(0, 0), self.at(40, 0), self.at(20, 30),
        ]))
        poly.collidable = True
        owner = poly._collider
        snapshot_shape(poly, cache_owner=owner)
        key0 = _collision_pose_key(poly)
        n0 = sys._debug_hull_builds
        poly.move_by(30, 5)
        p1 = snapshot_shape(poly, cache_owner=owner)[0]
        key1 = _collision_pose_key(poly)
        self.assertEqual(sys._debug_hull_builds, n0)
        self.assertEqual(key0[0], key1[0])
        self.assertEqual(key0[3:], key1[3:])
        self.assertNotEqual((key0[1], key0[2]), (key1[1], key1[2]))
        expected = [(float(v.x), float(v.y)) for v in poly.points]
        for (gx, gy), (ex, ey) in zip(p1.verts or (), expected):
            self.assertAlmostEqual(gx, ex, places=3)
            self.assertAlmostEqual(gy, ey, places=3)

    def test_ellipse_angle_assign_rebuilds_cached_ellipse(self):
        el = self.track(Ellipse(center=self.at(0, 0), width=80, height=20, angle=0))
        el.collidable = True
        owner = el._collider
        p0 = snapshot_shape(el, cache_owner=owner)[0]
        self.assertAlmostEqual(p0.params[4], 0.0, places=3)
        el.angle = 90.0
        p1 = snapshot_shape(el, cache_owner=owner)[0]
        self.assertAlmostEqual(p1.params[4], math.pi / 2, places=3)

    def test_ellipse_linked_rotation_rebuilds_cached_ellipse(self):
        """``ellipse["angle"] @=`` must rotate the hull without ``rotate_to``."""
        from scena.state import Attribute

        el = self.track(Ellipse(center=self.at(0, 0), width=80, height=20, angle=0))
        el.collidable = True
        owner = el._collider
        p0 = snapshot_shape(el, cache_owner=owner)[0]
        self.assertAlmostEqual(p0.params[4], 0.0, places=3)
        dial = Attribute(0.0)
        el["angle"] @= dial
        dial.value = 90.0
        p1 = snapshot_shape(el, cache_owner=owner)[0]
        self.assertAlmostEqual(p1.params[4], math.pi / 2, places=3)

    def test_regular_polygon_linked_rotation_rebuilds_cached_poly(self):
        from scena.state import Attribute

        hex_ = self.track(RegularPolygon(n=4, center=self.at(0, 0), radius=50, angle=0))
        hex_.collidable = True
        owner = hex_._collider
        p0 = snapshot_shape(hex_, cache_owner=owner)[0]
        v0 = [(round(x, 3), round(y, 3)) for x, y in (p0.verts or ())]
        dial = Attribute(0.0)
        hex_["angle"] @= dial
        dial.value = 45.0
        p1 = snapshot_shape(hex_, cache_owner=owner)[0]
        v1 = [(round(x, 3), round(y, 3)) for x, y in (p1.verts or ())]
        self.assertNotEqual(v0, v1)

    def test_equilateral_triangle_linked_rotation_rebuilds_cached_poly(self):
        from scena.state import Attribute

        tri = self.track(EquilateralTriangle(center=self.at(0, 0), radius=50, angle=0))
        tri.collidable = True
        owner = tri._collider
        p0 = snapshot_shape(tri, cache_owner=owner)[0]
        v0 = [(round(x, 3), round(y, 3)) for x, y in (p0.verts or ())]
        dial = Attribute(0.0)
        tri["angle"] @= dial
        dial.value = 30.0
        p1 = snapshot_shape(tri, cache_owner=owner)[0]
        v1 = [(round(x, 3), round(y, 3)) for x, y in (p1.verts or ())]
        self.assertNotEqual(v0, v1)

    def test_ellipse_scale_to_matches_width_height_not_squared(self):
        """``scale=`` grows geometry once. Draw used to CTM-scale on top of that."""
        el = self.track(Ellipse(center=self.at(0, 0), width=80, height=40, angle=0))
        el.collidable = True
        el.scale_to(2)
        self.assertAlmostEqual(float(el.width), 160.0, places=3)
        self.assertAlmostEqual(float(el.height), 80.0, places=3)
        prim = snapshot_shape(el)[0]
        self.assertAlmostEqual(prim.params[2], 80.0, places=3)
        self.assertAlmostEqual(prim.params[3], 40.0, places=3)
        minx, miny, maxx, maxy = prim.aabb
        self.assertAlmostEqual(maxx - minx, 160.0, places=3)
        self.assertAlmostEqual(maxy - miny, 80.0, places=3)

    def test_circle_radius_assign_rebuilds_cached_circle(self):
        c = self.track(Circle(center=self.at(0, 0), radius=10))
        c.collidable = True
        owner = c._collider
        p0 = snapshot_shape(c, cache_owner=owner)[0]
        self.assertAlmostEqual(p0.params[2], 10.0, places=3)
        c.radius = 40.0
        p1 = snapshot_shape(c, cache_owner=owner)[0]
        self.assertAlmostEqual(p1.params[2], 40.0, places=3)

    def test_rect_translation_does_not_rebuild_when_angle_fixed(self):
        sys = get_collision_system()
        r = self.track(Rect(center=self.at(0, 0), width=40, height=20, angle=12))
        r.collidable = True
        owner = r._collider
        snapshot_shape(r, cache_owner=owner)
        n0 = sys._debug_hull_builds
        r.center._takein(self.at(30, 5))
        snapshot_shape(r, cache_owner=owner)
        self.assertEqual(sys._debug_hull_builds, n0)

    def test_regular_polygon_move_by_does_not_rebuild(self):
        sys = get_collision_system()
        hex_ = self.track(RegularPolygon(n=6, center=self.at(0, 0), radius=30, angle=12))
        hex_.collidable = True
        owner = hex_._collider
        snapshot_shape(hex_, cache_owner=owner)
        n0 = sys._debug_hull_builds
        hex_.move_by(30, 5)
        snapshot_shape(hex_, cache_owner=owner)
        self.assertEqual(sys._debug_hull_builds, n0)


class TestSpatialFxCollision(CollisionTestCase):
    """SpatialFx domains publish tight collision_specs (not cull AABBs)."""

    def test_snapshot_point_domain_circle_main_paint(self):
        from scena.spatial_fx import Fire
        fire = self.track(Fire(center=self.at(10, 20), radius=15))
        prims = snapshot_shape(fire)
        self.assertEqual(len(prims), 1)
        self.assertEqual(prims[0].kind, PrimKind.CIRCLE)
        cx, cy, r = prims[0].params
        ox, oy = self.at(10, 20)
        self.assertAlmostEqual(cx, ox, places=3)
        self.assertAlmostEqual(cy, oy, places=3)
        self.assertAlmostEqual(r, 15.0, places=3)
        # Cull domain is larger (bloom) than collision disc.
        dminx, dminy, dmaxx, dmaxy = fire._domain_aabb()
        self.assertLess(dminx, cx - r)
        self.assertGreater(dmaxx, cx + r)

    def test_snapshot_plume_covers_emission(self):
        from scena.spatial_fx import Fire
        plume = self.track(Fire(style="plume", center=self.at(0, 0), width=26, length=60, angle=90))
        p = snapshot_shape(plume)[0]
        self.assertEqual(p.kind, PrimKind.ELLIPSE)
        minx, miny, maxx, maxy = p.aabb
        ox, oy = self.at(0, 0)
        self.assertLess(miny, oy + 10.0)   # includes base
        self.assertGreater(maxy, oy + 35.0)  # reaches upward along emission
        # Tighter than loose cull AABB (less empty headroom).
        dminx, dminy, dmaxx, dmaxy = plume._domain_aabb()
        self.assertLess(maxy - miny, dmaxy - dminy)

    def test_snapshot_pad_is_aabb(self):
        # Pads are axis-aligned (Rain has no angle): the hull is the pad box.
        from scena.spatial_fx import Rain
        ox, oy = self.at(0, 0)
        rain = self.track(Rain(center=(ox, oy), width=40, height=20))
        p = snapshot_shape(rain)[0]
        self.assertEqual(p.kind, PrimKind.AABB)
        self.assertEqual(tuple(p.aabb), (ox - 20, oy - 10, ox + 20, oy + 10))
        corners = self.track(Rain(p1=(ox, oy), p2=(ox + 40, oy + 20)))
        self.assertEqual(snapshot_shape(corners)[0].kind, PrimKind.AABB)

    def test_snapshot_beam_obb(self):
        from scena.spatial_fx import Jet
        ox, oy = self.at(0, 0)
        jet = self.track(Jet(p1=(ox, oy), p2=(ox + 100, oy), width=12))
        p = snapshot_shape(jet)[0]
        self.assertEqual(p.kind, PrimKind.OBB)
        self.assertAlmostEqual(p.params[2], 42.5)  # half of 85% length
        self.assertAlmostEqual(p.params[3], 6.0)   # half-width

    def test_origin_angle_jet_enrolled_in_anything_does_not_crash(self):
        """Jet has origin, not center — pose cache must not treat the emitter as a Point."""
        from scena.spatial_fx import Jet
        ball = self.track(Circle(center=self.at(0, 0), radius=10))
        jet = self.track(Jet(
            origin=self.at(200, 0), angle=45, length=80, width=12,
        ))
        jet.collidable = True
        @collide(ball, ANYTHING)
        def on_hit(me, other, info):
            pass

        self.step()  # used to TypeError: Cannot convert Jet to Point

    def test_circle_hits_origin_angle_jet(self):
        from scena.spatial_fx import Jet
        ox, oy = self.at(0, 0)
        jet = self.track(Jet(origin=(ox, oy), angle=0, length=100, width=20))
        ball = self.track(Circle(center=(ox + 50, oy), radius=5))
        hits = []

        @collide(ball, jet)
        def on_hit(me, other, info):
            hits.append((me, other))

        self.step()
        self.assertEqual(hits, [(ball, jet)])

    def test_jet_angle_change_rebuilds_cached_obb(self):
        from scena.spatial_fx import Jet
        ox, oy = self.at(0, 0)
        jet = self.track(Jet(origin=(ox, oy), angle=0, length=100, width=12))
        jet.collidable = True
        owner = jet._collider
        p0 = snapshot_shape(jet, cache_owner=owner)[0]
        self.assertAlmostEqual(p0.params[4], 0.0, places=3)
        jet.angle = 90.0
        p1 = snapshot_shape(jet, cache_owner=owner)[0]
        self.assertAlmostEqual(p1.params[4], math.pi / 2, places=3)

    def test_graphic_pose_key_translation_keeps_extra(self):
        from scena.spatial_fx import Fire
        c = self.track(Circle(center=self.at(10, 20), radius=5))
        key = _collision_pose_key(c)
        self.assertGreaterEqual(len(key), 3)
        extra = key[3:]
        c.center._takein(self.at(40, 25))
        key2 = _collision_pose_key(c)
        self.assertEqual(key2[0], key[0])
        self.assertEqual(key2[3:], extra)
        self.assertNotEqual((key2[1], key2[2]), (key[1], key[2]))
        fire = self.track(Fire(center=self.at(10, 20), radius=15))
        fkey = _collision_pose_key(fire)
        self.assertGreater(len(fkey), 3)  # includes radius via point_frame

    def test_camp_radius_change_rebuilds_cached_circle(self):
        from scena.spatial_fx import Fire
        fire = self.track(Fire(center=self.at(0, 0), radius=20))
        fire.collidable = True
        owner = fire._collider
        p0 = snapshot_shape(fire, cache_owner=owner)[0]
        self.assertAlmostEqual(p0.params[2], 20.0, places=3)
        fire.radius = 80.0
        p1 = snapshot_shape(fire, cache_owner=owner)[0]
        self.assertAlmostEqual(p1.params[2], 80.0, places=3)

    def test_plume_size_change_rebuilds_cached_obb(self):
        from scena.spatial_fx import Fire
        plume = self.track(Fire(
            style="plume", center=self.at(0, 0), width=26, length=60, angle=90,
        ))
        plume.collidable = True
        owner = plume._collider
        p0 = snapshot_shape(plume, cache_owner=owner)[0]
        self.assertAlmostEqual(p0.params[4], math.pi / 2, places=3)
        lat0 = p0.params[3]
        plume.angle = 0.0
        p1 = snapshot_shape(plume, cache_owner=owner)[0]
        self.assertAlmostEqual(p1.params[4], 0.0, places=3)
        plume.width = 50.0
        p2 = snapshot_shape(plume, cache_owner=owner)[0]
        self.assertGreater(p2.params[3], lat0)
        len2 = p2.params[2]
        plume.length = 140.0
        p3 = snapshot_shape(plume, cache_owner=owner)[0]
        self.assertGreater(p3.params[2], len2)

    def test_sparks_radius_resizes_hitbox(self):
        from scena.spatial_fx import Sparks
        s = self.track(Sparks(center=self.at(0, 0), radius=20))
        s.collidable = True
        owner = s._collider
        p0 = snapshot_shape(s, cache_owner=owner)[0]
        self.assertAlmostEqual(p0.params[2], 20.0, places=3)
        n = get_collision_system()._debug_hull_builds
        s.radius = 50.0
        p1 = snapshot_shape(s, cache_owner=owner)[0]
        self.assertAlmostEqual(p1.params[2], 50.0, places=3)
        self.assertGreater(get_collision_system()._debug_hull_builds, n)

    def test_rain_size_change_rebuilds_cached_pad(self):
        from scena.spatial_fx import Rain
        rain = self.track(Rain(center=self.at(0, 0), width=40, height=20))
        rain.collidable = True
        owner = rain._collider
        p0 = snapshot_shape(rain, cache_owner=owner)[0]
        self.assertEqual(p0.kind, PrimKind.AABB)
        span0 = p0.aabb[2] - p0.aabb[0]
        rain.width = 80.0
        p1 = snapshot_shape(rain, cache_owner=owner)[0]
        self.assertGreater(p1.aabb[2] - p1.aabb[0], span0)
        rain.height = 50.0
        p2 = snapshot_shape(rain, cache_owner=owner)[0]
        self.assertEqual(p2.kind, PrimKind.AABB)
        self.assertGreater(p2.aabb[3] - p2.aabb[1], p1.aabb[3] - p1.aabb[1])

    def test_camp_radius_grow_starts_hitting(self):
        from scena.spatial_fx import Fire
        fire = self.track(Fire(center=self.at(0, 0), radius=20))
        # collision r = 10; probe at x=40 r=5 → gap
        ball = self.track(Circle(center=self.at(40, 0), radius=5))
        hits = []

        @collide(ball, fire)
        def on_hit(me, other, info):
            hits.append(True)

        self.step()
        self.assertEqual(hits, [])
        fire.radius = 80.0  # collision r = 40; 40+5 >= 40
        self.step()
        self.assertTrue(hits)

    def test_camp_radius_shrink_stops_hitting(self):
        from scena.spatial_fx import Fire
        fire = self.track(Fire(center=self.at(0, 0), radius=80))
        ball = self.track(Circle(center=self.at(40, 0), radius=5))
        exits = []

        @collide(ball, fire)
        def on_hit(me, other, info):
            pass

        @collide_exit(ball, fire)
        def on_exit(me, other, info):
            exits.append(True)

        self.step()
        fire.radius = 20.0
        self.step()
        self.assertTrue(exits)

    def test_point_domain_look_params_do_not_rebuild_hull(self):
        from scena.spatial_fx import Fire
        fire = self.track(Fire(center=self.at(0, 0), radius=20))
        fire.collidable = True
        owner = fire._collider
        snapshot_shape(fire, cache_owner=owner)
        n = get_collision_system()._debug_hull_builds
        fire.amount = 2.0
        fire.speed = 3.0
        snapshot_shape(fire, cache_owner=owner)
        self.assertEqual(get_collision_system()._debug_hull_builds, n)

    def test_point_domain_translate_skips_hull_rebuild(self):
        from scena.spatial_fx import Fire
        fire = self.track(Fire(center=self.at(0, 0), radius=20))
        fire.collidable = True
        owner = fire._collider
        snapshot_shape(fire, cache_owner=owner)
        n = get_collision_system()._debug_hull_builds
        fire.center._takein(self.at(12, 4))
        p = snapshot_shape(fire, cache_owner=owner)[0]
        self.assertEqual(get_collision_system()._debug_hull_builds, n)
        ox, oy = self.at(12, 4)
        self.assertAlmostEqual(p.params[0], ox, places=3)
        self.assertAlmostEqual(p.params[1], oy, places=3)

    def test_circle_hits_campfire(self):
        from scena.spatial_fx import Fire
        ball = self.track(Circle(center=self.at(0, 0), radius=20))
        fire = self.track(Fire(center=self.at(10, 0), radius=20))
        hits = []

        @collide(ball, fire)
        def on_hit(me, other, info):
            hits.append((me, other))

        self.step()
        self.assertEqual(hits, [(ball, fire)])

    def test_sparks_snapshot_circle(self):
        from scena.spatial_fx import Sparks
        s = self.track(Sparks(center=self.at(5, 5), radius=12))
        p = snapshot_shape(s)[0]
        self.assertEqual(p.kind, PrimKind.CIRCLE)
        ox, oy = self.at(5, 5)
        self.assertAlmostEqual(p.params[0], ox, places=3)
        self.assertAlmostEqual(p.params[1], oy, places=3)
        self.assertAlmostEqual(p.params[2], 12.0, places=3)

    def test_glowspot_hitbox_is_90_percent_radius(self):
        from scena.spatial_fx import GlowSpot
        g = self.track(GlowSpot(center=self.at(0, 0), radius=50))
        p = snapshot_shape(g)[0]
        self.assertEqual(p.kind, PrimKind.CIRCLE)
        self.assertAlmostEqual(p.params[2], 45.0, places=3)

    def test_orb_hitbox_is_radius(self):
        from scena.spatial_fx import Orb
        g = self.track(Orb(center=self.at(0, 0), radius=50, glow=1.5))
        p = snapshot_shape(g)[0]
        self.assertEqual(p.kind, PrimKind.CIRCLE)
        self.assertAlmostEqual(p.params[2], 50.0, places=3)

    def test_plume_lat_wider_when_narrow_tighter_when_wide(self):
        from scena.spatial_fx import Fire
        narrow = self.track(Fire(
            style="plume", center=self.at(0, 0), width=10, length=60, angle=90,
        ))
        wide = self.track(Fire(
            style="plume", center=self.at(80, 0), width=70, length=60, angle=90,
        ))
        nlat = snapshot_shape(narrow)[0].params[3]
        wlat = snapshot_shape(wide)[0].params[3]
        self.assertAlmostEqual(nlat, 10.0 * 0.901 * 1.25, places=3)
        self.assertAlmostEqual(wlat, 70.0 * 0.901 * 0.85, places=3)
        # Wide: entire OBB lifted toward the tip (25% of box height at width 70).
        # Base is pinned using the length=200 lift so short plumes don't ride up.
        wide_p = snapshot_shape(wide)[0]
        oy = self.at(80, 0)[1]
        from scena.spatial_fx import _plume_along_lift, _PLUME_BASE_LENGTH
        lift = _plume_along_lift(70.0, _PLUME_BASE_LENGTH * 0.663, 70.0 * 0.28)
        sh = -70.0 * 0.14 + lift
        mid = 0.5 * ((-70.0 * 0.28 + sh) + (60.0 * 0.663 + sh))
        self.assertAlmostEqual(wide_p.params[1], oy + mid, places=2)

    def test_plume_min_hitbox_width(self):
        from scena.spatial_fx import Fire
        tiny = self.track(Fire(
            style="plume", center=self.at(0, 0), width=4, length=60, angle=90,
        ))
        self.assertGreaterEqual(snapshot_shape(tiny)[0].params[3], 10.0 - 1e-6)

    def test_plume_min_hitbox_height(self):
        from scena.spatial_fx import Fire
        short = self.track(Fire(
            style="plume", center=self.at(0, 0), width=26, length=20, angle=90,
        ))
        self.assertGreaterEqual(2.0 * snapshot_shape(short)[0].params[2], 20.0 - 1e-6)

    def test_plume_short_length_keeps_base(self):
        from scena.spatial_fx import Fire
        long = self.track(Fire(
            style="plume", center=self.at(0, 0), width=26, length=200, angle=90,
        ))
        short = self.track(Fire(
            style="plume", center=self.at(80, 0), width=26, length=20, angle=90,
        ))
        oy_long = self.at(0, 0)[1]
        oy_short = self.at(80, 0)[1]
        lp, sp = snapshot_shape(long)[0], snapshot_shape(short)[0]
        # Angle 90: base is center_y - half_len. Length must not lift the base.
        self.assertAlmostEqual(
            (sp.params[1] - oy_short) - sp.params[2],
            (lp.params[1] - oy_long) - lp.params[2],
            places=2,
        )
        self.assertGreater(lp.params[2], sp.params[2])

    def test_tongues_and_embers_narrow(self):
        from scena.spatial_fx import Fire
        tongues = self.track(Fire(style="tongues", center=self.at(0, 0), width=40, angle=90))
        tp = snapshot_shape(tongues)[0]
        self.assertEqual(tp.kind, PrimKind.ELLIPSE)
        self.assertAlmostEqual(tp.params[3], 40.0 * 0.363, places=3)
        embers = self.track(Fire(style="embers", center=self.at(80, 0), width=40, angle=90))
        ep = snapshot_shape(embers)[0]
        self.assertEqual(ep.kind, PrimKind.OBB)
        self.assertAlmostEqual(ep.params[3], 40.0 * 0.749, places=3)

    def test_tongues_square_when_length_le_width(self):
        from scena.spatial_fx import Fire
        short = self.track(Fire(
            style="tongues", center=self.at(0, 0), width=40, length=20, angle=90,
        ))
        eq = self.track(Fire(
            style="tongues", center=self.at(80, 0), width=40, length=40, angle=90,
        ))
        tall = self.track(Fire(
            style="tongues", center=self.at(160, 0), width=40, length=90, angle=90,
        ))
        ps, pe, pt = (snapshot_shape(x)[0] for x in (short, eq, tall))
        self.assertAlmostEqual(ps.params[2], ps.params[3], places=3)
        self.assertAlmostEqual(pe.params[2], pe.params[3], places=3)
        self.assertAlmostEqual(ps.params[2], pe.params[2], places=3)
        self.assertGreater(pt.params[2], pe.params[2])
        # Growing length pins the base and only extends the tip.
        oy_s, oy_e, oy_t = self.at(0, 0)[1], self.at(80, 0)[1], self.at(160, 0)[1]
        base_s = (ps.params[1] - oy_s) - ps.params[2]
        base_e = (pe.params[1] - oy_e) - pe.params[2]
        base_t = (pt.params[1] - oy_t) - pt.params[2]
        self.assertAlmostEqual(base_s, base_e, places=3)
        self.assertAlmostEqual(base_t, base_e, places=3)

    def test_plume_upward_hit(self):
        from scena.spatial_fx import Fire
        plume = self.track(Fire(style="plume", center=self.at(0, 0), width=20, length=50, angle=90))
        # Probe above base, inside the tight emission OBB (not above the tips).
        ball = self.track(Circle(center=self.at(0, 30), radius=5))
        hits = []

        @collide(ball, plume)
        def on_hit(me, other, info):
            hits.append(True)

        self.step()
        self.assertTrue(hits)


class TestDeadAndGroupResolve(CollisionTestCase):
    def test_object_collide_destroy_drops_handler(self):
        """Proposal B: object-literal ``@collide`` is swap-removed on destroy."""
        a = self.track(Circle(center=self.at(0, 0), radius=20, group="player"))
        b = self.track(Circle(center=self.at(5, 0), radius=20, group="star"))
        hits = []

        @collide(a, b)
        def on_hit(me, other, info):
            hits.append(True)

        self.step()
        self.assertEqual(len(hits), 1)
        hits.clear()

        sys = get_collision_system()
        self.assertEqual(len(sys._pair_handlers), 1)
        a.destroy()
        self._owned.remove(a)
        self.assertFalse(any(side is a for h in sys._pair_handlers for side in h[:2]))
        self.assertEqual(len(sys._pair_handlers), 0)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            self.step()
            self.step()
        dead_warns = [x for x in w if "destroyed" in str(x.message)]
        self.assertEqual(dead_warns, [])
        self.assertEqual(hits, [])

    def test_tag_handlers_untouched_by_member_destroy(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20, group="player"))
        b = self.track(Circle(center=self.at(5, 0), radius=20, group="star"))

        @collide("player", "star")
        def on_hit(me, other, info):
            pass

        self.assertEqual(len(get_collision_system()._pair_handlers), 1)
        a.destroy()
        self._owned.remove(a)
        handlers = get_collision_system()._pair_handlers
        self.assertEqual(len(handlers), 1)
        self.assertEqual(handlers[0][0], "player")
        self.assertEqual(handlers[0][1], "star")

    def test_spawn_destroy_cycles_do_not_grow_handlers(self):
        wall = self.track(Circle(center=self.at(0, 0), radius=20))
        n_handlers = []
        for i in range(20):
            shot = Circle(center=self.at(5, 0), radius=10)

            @collide(shot, wall)
            def on_hit(me, other, info):
                pass

            n_handlers.append(len(get_collision_system()._pair_handlers))
            shot.destroy()
        self.assertEqual(n_handlers[-1], 1)
        self.assertEqual(len(get_collision_system()._pair_handlers), 0)
        self.assertEqual(max(n_handlers), 1)

    def test_destroyed_side_leaves_no_pair_target_on_survivor(self):
        """S6 (system churn): dropping the handler is not enough — the other
        side's ``_pair_targets`` held every shot ever fired (leak + a broad
        phase that grows). Covers object literal, ``@collide_with`` and
        ``resolve`` pairs."""
        import gc
        import weakref
        from scena import collide_with, resolve

        wall = self.track(Circle(center=self.at(0, 0), radius=20, group="wall"))

        class Bolt(Circle):
            @collide_with("wall")
            def hit(self, other, info=None):
                pass

        for how in ("literal", "collide_with", "resolve"):
            with self.subTest(how=how):
                refs = []
                for _ in range(10):
                    if how == "collide_with":
                        shot = Bolt(center=self.at(5, 0), radius=4)
                    else:
                        shot = Circle(center=self.at(5, 0), radius=4)
                    if how == "literal":
                        @collide(shot, wall)
                        def on_hit(me, other, info):
                            pass
                    elif how == "resolve":
                        resolve(shot, wall)
                    self.step()
                    refs.append(weakref.ref(shot))
                    shot.destroy()
                    del shot
                targets = wall._collider._pair_targets if wall._collider else []
                self.assertFalse(
                    [t for t in targets if not isinstance(t, str) and t is not ANYTHING],
                    "survivor still targets destroyed shots")
                self.step()  # the last step's snapshot (_last_prims) is replaced
                gc.collect()
                self.assertEqual([r for r in refs if r() is not None], [])

    def test_group_collide_sees_recreated_member(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20, group="player"))
        b = self.track(Circle(center=self.at(5, 0), radius=20, group="star"))
        hits = []

        @collide("player", "star")
        def on_hit(me, other, info):
            hits.append(me)

        self.step()
        self.assertEqual(len(hits), 1)
        hits.clear()

        a.destroy()
        self.step()
        self.assertEqual(hits, [])

        a2 = self.track(Circle(center=self.at(0, 0), radius=20, group="player"))
        self.step()
        self.assertEqual(len(hits), 1)

    def test_group_collide_skips_inactive(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20, group="player"))
        b = self.track(Circle(center=self.at(5, 0), radius=20, group="star"))
        hits = []

        @collide("player", "star")
        def on_hit(me, other, info):
            hits.append(True)

        a.collidable = True
        self.step()
        self.assertEqual(len(hits), 1)
        hits.clear()

        a.active = False
        self.step()
        self.assertEqual(hits, [])
        a.active = True
        self.step()
        self.assertEqual(len(hits), 1)

    def test_group_collide_respects_collidable_false(self):
        """FOCUSED @collide must not re-enroll after collidable=False (death disarm)."""
        a = self.track(Circle(center=self.at(0, 0), radius=20, group="player"))
        b = self.track(Circle(center=self.at(5, 0), radius=20, group="star"))
        hits = []

        @collide("player", "star")
        def on_hit(me, other, info):
            hits.append(True)

        self.step()
        self.assertEqual(len(hits), 1)
        self.assertTrue(b.collidable)
        hits.clear()

        b.collidable = False
        self.assertFalse(b.collidable)
        self.assertIsNone(b._collider)
        self.step()
        self.step()
        self.assertEqual(hits, [])
        self.assertFalse(b.collidable)
        self.assertIsNone(b._collider)

        b.collidable = True
        self.step()
        self.assertEqual(len(hits), 1)


class TestOnCollideMethodArguments(CollisionTestCase):
    """AC6 (game system tests): ``on_collide*`` written as a class method got
    ``other = self`` and ``info = the other body``. The method was stored as
    the property callback ``fn(me, other, info)`` and called with its arity:
    a bound ``on_collide(self, other, info)`` takes two, so it received
    ``(me, other)``. Guia, "Detectar": "Como método da classe: fn(self, other)
    ou fn(self, other, info)". Every phase, both arities, every family that
    collides (Shape, Sprite, SpatialFx)."""

    def _families(self):
        from scena import Orb
        from scena.sprite import Sprite
        sheet = media_sheet()
        return (
            ("Circle", Circle, lambda K, c: K(center=c, radius=12)),
            ("Sprite", Sprite, lambda K, c: K(sheet, height=24, center=c, hitbox_shape="circle")),
            ("Orb", Orb, lambda K, c: K(center=c, radius=12)),
        )

    def test_method_gets_other_and_info(self):
        for i, (fam, base, make) in enumerate(self._families()):
            with self.subTest(family=fam):
                seen = []
                ox = i * 2000          # each family alone: earlier bodies stay alive

                class K(base):
                    def on_collide(self, other, info):
                        seen.append(("enter", self, other, info))

                    def on_collide_stay(self, other, info):
                        seen.append(("stay", self, other, info))

                    def on_collide_exit(self, other):
                        seen.append(("exit", self, other, None))

                k = self.track(make(K, self.at(ox, 0)))
                wall = self.track(Rect(center=self.at(ox + 8, 0), width=20, height=20))
                wall.collidable = True
                self.step()
                self.step()
                wall.center = self.at(ox + 500, 0)
                self.step()
                phases = [p for p, *_ in seen]
                self.assertEqual(phases, ["enter", "stay", "exit"], fam)
                for phase, me, other, info in seen:
                    self.assertIs(me, k, (fam, phase))
                    self.assertIs(other, wall, (fam, phase))
                    if info is not None:
                        self.assertIs(info.a, k, (fam, phase))
                        self.assertIs(info.b, wall, (fam, phase))

    def test_property_callback_unchanged(self):
        a = self.track(Circle(center=self.at(0, 0), radius=12))
        b = self.track(Circle(center=self.at(5, 0), radius=12))
        b.collidable = True
        got = []
        a.on_collide = lambda me, other, info: got.append((me, other, info.b))
        self.step()
        self.assertEqual(got, [(a, b, b)])


def media_sheet():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from media_support import media
    return Sheet(media("space", "star_gold.png"))


class TestCollideWith(CollisionTestCase):
    """Proposal C: ``@collide_with*`` on Entity methods."""

    def test_free_function_raises(self):
        with self.assertRaises(TypeError) as ctx:
            @collide_with("bolt")
            def hit(self, other, info):
                pass
        self.assertIn("class methods", str(ctx.exception))
        self.assertIn("@collide", str(ctx.exception))

    def test_construct_enrolls_focused_tag_pairs(self):
        hits = []

        class Wasp(Circle):
            @collide_with("bolt")
            def on_hit_bolt(self, bolt, info):
                hits.append((self, bolt))

        wasp = self.track(Wasp(center=self.at(0, 0), radius=20, group="wasp"))
        bolt = self.track(Circle(center=self.at(5, 0), radius=10, group="bolt"))
        other = self.track(Circle(center=self.at(5, 0), radius=10))
        other.collidable = True

        self.assertTrue(wasp._collider._pair_targets)
        self.step()
        self.assertEqual(hits, [(wasp, bolt)])
        # Unrelated enrolled shape is not a declared pair target for wasp.
        self.assertNotIn(other, [p[1] for p in hits])

    def test_multiple_methods_and_phases(self):
        log = []

        class Wasp(Circle):
            @collide_with("bolt")
            def on_hit(self, bolt, info):
                log.append("enter")

            @collide_with_stay("bolt")
            def on_stay(self, bolt, info):
                log.append("stay")

            @collide_with_exit("bolt")
            def on_exit(self, bolt, info):
                log.append("exit")

        wasp = self.track(Wasp(center=self.at(0, 0), radius=20))
        bolt = self.track(Circle(center=self.at(5, 0), radius=10, group="bolt"))
        self.step()
        self.assertEqual(log, ["enter"])
        log.clear()
        self.step()
        self.assertEqual(log, ["stay"])
        log.clear()
        bolt.center = self.at(400, 0)
        self.step()
        self.assertEqual(log, ["exit"])
        self.assertEqual(len(get_collision_system()._pair_handlers), 3)

    def test_destroy_removes_instance_handlers(self):
        class Wasp(Circle):
            @collide_with("bolt")
            def on_hit(self, bolt, info):
                pass

        a = self.track(Wasp(center=self.at(0, 0), radius=20))
        b = self.track(Wasp(center=self.at(80, 0), radius=20))
        self.assertEqual(len(get_collision_system()._pair_handlers), 2)
        a.destroy()
        self._owned.remove(a)
        handlers = get_collision_system()._pair_handlers
        self.assertEqual(len(handlers), 1)
        self.assertIs(handlers[0][0], b)

    def test_anything_plus_on_collide_warns_once(self):
        class Wasp(Circle):
            def on_collide(self, other, info):
                pass

            @collide_with(ANYTHING)
            def on_any(self, other, info):
                pass

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.track(Wasp(center=self.at(0, 0), radius=10))
            self.track(Wasp(center=self.at(40, 0), radius=10))
        msgs = [str(w.message) for w in caught if "ANYTHING" in str(w.message)]
        self.assertEqual(len(msgs), 1)
        self.assertIn("on_collide", msgs[0])
        self.assertIn("on_any", msgs[0])

    def test_classless_collide_unchanged(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20, group="player"))
        b = self.track(Circle(center=self.at(5, 0), radius=20, group="star"))
        hits = []

        @collide("player", "star")
        def on_hit(me, other, info):
            hits.append((me, other))

        self.step()
        self.assertEqual(hits, [(a, b)])

    def test_list_target_cross_product(self):
        hits = []

        class Wasp(Circle):
            @collide_with(["bolt", "sting"])
            def on_hit(self, other, info):
                hits.append(other)

        wasp = self.track(Wasp(center=self.at(0, 0), radius=20))
        bolt = self.track(Circle(center=self.at(5, 0), radius=10, group="bolt"))
        sting = self.track(Circle(center=self.at(5, 0), radius=10, group="sting"))
        self.step()
        self.assertEqual(set(hits), {bolt, sting})

    def test_stacked_collide_with_same_method(self):
        hits = []

        class Wasp(Circle):
            @collide_with("bolt")
            @collide_with("sting")
            def on_hit(self, other, info):
                hits.append(other)

        wasp = self.track(Wasp(center=self.at(0, 0), radius=20))
        bolt = self.track(Circle(center=self.at(5, 0), radius=10, group="bolt"))
        self.step()
        self.assertEqual(hits, [bolt])
        hits.clear()
        sting = self.track(Circle(center=self.at(5, 0), radius=10, group="sting"))
        bolt.center = self.at(400, 0)
        self.step()
        self.assertEqual(hits, [sting])

    def test_collide_on_method_raises(self):
        with self.assertRaises(TypeError) as ctx:
            class Wasp(Circle):
                @collide("bolt", "wasp")
                def on_hit(self, me, other, info):
                    pass
        self.assertIn("@collide_with", str(ctx.exception))


class TestProxyAabbConservative(CollisionTestCase):
    """Broad-phase ``_proxy_aabb_for_shape`` must never be tighter than exact."""

    @staticmethod
    def _union_aabb(prims):
        minx = miny = 1e300
        maxx = maxy = -1e300
        for p in prims:
            a = p.aabb
            if a[0] < minx:
                minx = a[0]
            if a[1] < miny:
                miny = a[1]
            if a[2] > maxx:
                maxx = a[2]
            if a[3] > maxy:
                maxy = a[3]
        return (minx, miny, maxx, maxy)

    def _assert_contains(self, proxy, exact, *, tol=1e-6):
        self.assertIsNotNone(proxy)
        self.assertLessEqual(proxy[0], exact[0] + tol)
        self.assertLessEqual(proxy[1], exact[1] + tol)
        self.assertGreaterEqual(proxy[2], exact[2] - tol)
        self.assertGreaterEqual(proxy[3], exact[3] - tol)

    def test_regular_polygon_proxy_contains_exact_across_angles(self):
        poly = self.track(
            RegularPolygon(n=5, center=self.at(0, 0), radius=20, angle=0)
        )
        for ang in (0, 15, 36, 72, 90, 137, 200):
            poly.angle = float(ang)
            proxy = _proxy_aabb_for_shape(poly)
            exact = self._union_aabb(_snapshot_shape_uncached(poly))
            self._assert_contains(proxy, exact)

    def test_multi_box_sprite_proxy_contains_exact_across_angles(self):
        spr = self.track(Sprite(center=self.at(0, 0), size=40, hitbox_shape="rect"))
        spr._hitbox_kind = "auto"
        spr._hitbox_boxes = (
            (0.0, 0.0, 0.9, 0.45),
            (0.15, 0.2, 0.35, 0.55),
            (-0.2, -0.15, 0.4, 0.3),
        )
        spr._recompute_hitbox_local_radius()
        spr._auto_baked = True
        self.assertGreater(spr._hitbox_local_radius, 0.0)
        for ang in (0, 20, 45, 90, 133, 270):
            spr.angle = float(ang)
            proxy = _proxy_aabb_for_shape(spr)
            exact = self._union_aabb(_snapshot_shape_uncached(spr))
            self._assert_contains(proxy, exact)

    def test_rect_proxy_matches_exact_when_axis_aligned(self):
        r = self.track(Rect(center=self.at(10, 5), width=40, height=20, angle=0))
        proxy = _proxy_aabb_for_shape(r)
        exact = self._union_aabb(_snapshot_shape_uncached(r))
        self._assert_contains(proxy, exact, tol=1e-9)
        # Axis-aligned OBB extents should match exactly.
        self.assertAlmostEqual(proxy[0], exact[0], places=6)
        self.assertAlmostEqual(proxy[1], exact[1], places=6)
        self.assertAlmostEqual(proxy[2], exact[2], places=6)
        self.assertAlmostEqual(proxy[3], exact[3], places=6)

    def test_line_proxy_matches_exact_across_models_and_angles(self):
        from scena.collision import _keys_uniform_translation
        ox, oy = self.at(0, 0)
        lines = (
            Line(p1=(ox, oy), p2=(ox + 40, oy + 10)),
            Line(p1=(ox, oy), angle=0.0, length=50.0),
            Line(center=(ox + 20, oy), length=40, angle=15.0),
            Line(p1=(ox, oy), dx=30, dy=10),
            Line(p1=(ox, oy), vec=Vec2(25, 5)),
        )
        for line in lines:
            self.track(line)
            for ang in (0, 20, 45, 90, 130):
                try:
                    line.angle = float(ang)
                except Exception:
                    line.rotate_to(float(ang))
                proxy = _proxy_aabb_for_shape(line)
                exact = self._union_aabb(_snapshot_shape_uncached(line))
                self._assert_contains(proxy, exact, tol=1e-6)
                self.assertAlmostEqual(proxy[0], exact[0], places=5)
                self.assertAlmostEqual(proxy[1], exact[1], places=5)
                self.assertAlmostEqual(proxy[2], exact[2], places=5)
                self.assertAlmostEqual(proxy[3], exact[3], places=5)

        # Angle-length: angle change must change non-translation extra;
        # rigid move_by must be a pure translation of the pose key.
        spin = self.track(Line(p1=(ox, oy), angle=0.0, length=40.0))
        k0 = _collision_pose_key(spin)
        spin.angle = 35.0
        k1 = _collision_pose_key(spin)
        self.assertIsNone(_keys_uniform_translation((k0,), (k1,)))
        spin.move_by(12, -7)
        k2 = _collision_pose_key(spin)
        delta = _keys_uniform_translation((k1,), (k2,))
        self.assertEqual(delta, (12.0, -7.0))
        # Still cold on Container Derivates after pose-key traffic.
        self.assertIsNone(spin.__dict__.get("center"))
        self.assertIsNone(spin.__dict__.get("vec"))

        # POINT_POINT: moving only p2 must rebuild (not translate).
        pp = self.track(Line(p1=(ox, oy), p2=(ox + 40, oy)))
        k_a = _collision_pose_key(pp)
        pp.p2._takein((ox + 40, oy + 25))
        k_b = _collision_pose_key(pp)
        self.assertIsNone(_keys_uniform_translation((k_a,), (k_b,)))

    def test_spatial_fx_proxy_contains_exact(self):
        from scena.spatial_fx import Fire, Jet, Rain
        ox, oy = self.at(0, 0)
        cases = (
            Fire(center=(ox, oy), radius=24),
            Fire(style="plume", center=(ox, oy), width=26, length=60, angle=90),
            Rain(center=(ox + 80, oy), width=40, height=20),
            Jet(origin=(ox, oy + 80), angle=30, length=80, width=12),
        )
        for fx in cases:
            self.track(fx)
            proxy = _proxy_aabb_for_shape(fx)
            exact = self._union_aabb(_snapshot_shape_uncached(fx))
            self._assert_contains(proxy, exact)

    def test_sprite_proxy_contains_exact_over_kind_anchor_scale(self):
        import tempfile
        import os
        import skia
        from tests.test_sprite import _write_disk_png, _write_l_png, _write_padded_png, _write_rect_png

        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        disk = os.path.join(td.name, "disk.png")
        el = os.path.join(td.name, "l.png")
        pad = os.path.join(td.name, "pad.png")
        wide = os.path.join(td.name, "wide.png")
        _write_disk_png(disk, side=64, radius=28)
        _write_l_png(el, 32)
        _write_padded_png(pad, canvas_w=64, canvas_h=64, blob=(16, 8, 32, 40))
        _write_rect_png(wide, 80, 32)
        specs = (
            (disk, "circle"),
            (el, "hull"),
            (pad, "rect"),
            (wide, "ellipse"),
            (pad, "auto"),
        )
        anchors = ("center", "bottom", "top", "left", "right")
        scales = (1.0, 0.5, (0.55, 1.0), (1.0, 0.7))
        for path, kind in specs:
            for anchor in anchors:
                for scale in scales:
                    spr = self.track(Sprite(
                        path, center=self.at(0, 0), height=48,
                        hitbox_shape=kind, hitbox_anchor=anchor, hitbox_scale=scale,
                    ))
                    spr.collidable = True
                    for ang in (0, 40, 90):
                        spr.angle = float(ang)
                        proxy = _proxy_aabb_for_shape(spr)
                        exact = self._union_aabb(_snapshot_shape_uncached(spr))
                        self._assert_contains(proxy, exact, tol=1e-4)

    def _wide_source_sprite(
        self, *, circles=(), ellipses=(), poly=(), boxes=(),
        src=(200, 100), draw=(100, 100),
    ):
        """A ``src`` image stretched into a ``draw`` box, with hand-set locals."""
        import tempfile
        from tests.test_sprite import _write_rect_png

        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = os.path.join(td.name, "src.png")
        _write_rect_png(path, int(src[0]), int(src[1]))
        spr = self.track(Sprite(
            path, center=self.at(0, 0), width=draw[0], height=draw[1],
            hitbox_shape="rect",
        ))
        spr._ensure_auto_baked()
        spr._hitbox_kind = "auto"
        spr._hitbox_ref_src_w = float(src[0])
        spr._hitbox_ref_src_h = float(src[1])
        spr._hitbox_circles = tuple(circles)
        spr._hitbox_circle = None
        spr._hitbox_ellipses = tuple(ellipses)
        spr._hitbox_ellipse = None
        spr._hitbox_poly = tuple(poly)
        spr._hitbox_boxes = tuple(boxes)
        spr._recompute_hitbox_local_radius()
        spr._auto_baked = True
        return spr

    def test_sprite_proxy_contains_mixed_bake_under_flip_offset_scale(self):
        """Turned extent box holds every family under any pose knob."""
        spr = self._wide_source_sprite(
            circles=((0.2, -0.1, 0.18),),
            ellipses=((-0.25, 0.15, 0.2, 0.08, 0.6),),
            poly=((0.1, 0.3), (0.4, 0.2), (0.3, 0.45)),
            boxes=((-0.1, -0.3, 0.3, 0.2),),
        )
        kinds = {spec[0] for spec in spr._collision_specs()}
        self.assertTrue({"ellipse", "poly"} <= kinds)
        for flip_x in (False, True):
            for flip_y in (False, True):
                for offset in ((0.0, 0.0), (7.0, -4.0)):
                    for scale in (1.0, 0.6):
                        spr.flip_x = flip_x
                        spr.flip_y = flip_y
                        spr.offset = offset
                        spr.scale = scale
                        for ang in (0, 17, 45, 90, 133, 200, 290):
                            spr.angle = float(ang)
                            proxy = _proxy_aabb_for_shape(spr)
                            exact = self._union_aabb(_snapshot_shape_uncached(spr))
                            self._assert_contains(proxy, exact, tol=1e-6)

    def test_wide_source_circle_proxy_holds_emitted_ry_at_every_angle(self):
        """M5: a 200×100 circle drawn at 100×100 is an ellipse with ry = 50."""
        spr = self._wide_source_sprite(circles=((0.0, 0.0, 0.25),))
        (spec,) = spr._collision_specs()
        self.assertEqual(spec[0], "ellipse")
        self.assertAlmostEqual(spec[3], 25.0, places=6)
        self.assertAlmostEqual(spec[4], 50.0, places=6)
        for ang in (0, 30, 90):
            spr.angle = float(ang)
            proxy = _proxy_aabb_for_shape(spr)
            exact = self._union_aabb(_snapshot_shape_uncached(spr))
            self._assert_contains(proxy, exact, tol=1e-6)
            cx, cy = self.at(0, 0)
            self.assertGreaterEqual(proxy[3] - cy, exact[3] - cy - 1e-6)

    def test_near_square_stretch_emits_mean_circle_inside_proxy(self):
        """``ellipse_as_circle`` emits the mean radius, wider than the short axis."""
        spr = self._wide_source_sprite(
            circles=((0.0, 0.0, 0.5),), src=(100, 100), draw=(100, 105),
        )
        (spec,) = spr._collision_specs()
        self.assertEqual(spec[0], "circle")
        self.assertGreater(spec[3], 50.0)
        for ang in (0, 30, 90):
            spr.angle = float(ang)
            proxy = _proxy_aabb_for_shape(spr)
            exact = self._union_aabb(_snapshot_shape_uncached(spr))
            self._assert_contains(proxy, exact, tol=1e-6)

    def test_sprite_proxy_extents_follow_pose_aspect_change(self):
        """A turned ellipse's bound depends on the pose aspect; a stretch rebuilds it."""
        spr = self._wide_source_sprite(
            ellipses=((0.1, 0.0, 0.3, 0.1, 0.7),), src=(100, 100), draw=(100, 100),
        )
        _proxy_aabb_for_shape(spr)
        spr.width = 40.0
        spr.height = 160.0
        for ang in (0, 30, 90):
            spr.angle = float(ang)
            proxy = _proxy_aabb_for_shape(spr)
            exact = self._union_aabb(_snapshot_shape_uncached(spr))
            self._assert_contains(proxy, exact, tol=1e-6)

    def test_sprite_proxy_is_tight_when_axis_aligned_and_disk_at_45(self):
        """Never wider than the old ``hypot(ex*w, ey*h)`` disk; equal at 45° square."""
        thin = self.track(Sprite(center=self.at(0, 0), width=10, height=100, hitbox_shape="rect"))
        thin._hitbox_kind = "auto"
        thin._hitbox_boxes = ((0.0, 0.0, 1.0, 1.0),)
        thin._recompute_hitbox_local_radius()
        thin._auto_baked = True
        w, h = thin._hitbox_pose_wh()
        disk = math.hypot(thin._hitbox_extent_x * w, thin._hitbox_extent_y * h)
        proxy = _proxy_aabb_for_shape(thin)
        area = (proxy[2] - proxy[0]) * (proxy[3] - proxy[1])
        self.assertLess(area, 0.25 * (2.0 * disk) ** 2)
        exact = self._union_aabb(_snapshot_shape_uncached(thin))
        for i in range(4):
            self.assertAlmostEqual(proxy[i], exact[i], places=6)

        sq = self.track(Sprite(center=self.at(200, 0), size=40, hitbox_shape="rect"))
        sq._hitbox_kind = "auto"
        sq._hitbox_boxes = ((0.0, 0.0, 1.0, 1.0),)
        sq._recompute_hitbox_local_radius()
        sq._auto_baked = True
        sq.angle = 45.0
        w, h = sq._hitbox_pose_wh()
        disk = math.hypot(sq._hitbox_extent_x * w, sq._hitbox_extent_y * h)
        proxy = _proxy_aabb_for_shape(sq)
        self.assertAlmostEqual(proxy[2] - proxy[0], 2.0 * disk, places=6)
        self.assertAlmostEqual(proxy[3] - proxy[1], 2.0 * disk, places=6)


class TestResolution(CollisionTestCase):
    def test_mass_validation(self):
        c = self.track(Circle(center=self.at(0, 0), radius=10))
        c.mass = 2.0
        self.assertEqual(c.mass, 2.0)
        c.mass = STATIC
        self.assertEqual(c.mass, STATIC)
        with self.assertRaises(ValueError):
            c.mass = 0
        with self.assertRaises(ValueError):
            c.mass = -1

    def test_resolve_blocks_linked_center_eagerly(self):
        from scena.state import LinkedAttributeError, Attribute
        from scena.shapes import Point
        a = self.track(Circle(center=self.at(0, 0), radius=20, group="a"))
        b = self.track(Circle(center=self.at(100, 0), radius=20, group="b"))
        src = Point(*self.at(1, 1))
        a.center @= src
        with self.assertRaises(LinkedAttributeError):
            resolve("a", "b")
        a.center.unlink()
        resolve("a", "b")
        self.assertTrue(a._resolve_enrolled)
        with self.assertRaises(LinkedAttributeError):
            a.center @= src
        # Non-overlapping field stays linkable.
        a["radius"] @= Attribute(22.0)
        self.assertAlmostEqual(float(a.radius), 22.0, places=5)
        unresolve("a", "b")
        self.assertFalse(a._resolve_enrolled)
        a.center @= src
        self.assertAlmostEqual(float(a.center.x), float(src.x), places=4)

    def test_mtv_split_rejects_nonpositive_mass(self):
        info = CollisionInfo(
            a=None, b=None,
            normal=Vec2.temp(1.0, 0.0),
            depth=10.0,
        )
        with self.assertRaises(ValueError):
            info.mtv_split(mass_a=0, mass_b=1)

    def test_resolve_separates_overlapping_circles(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20, group="a"))
        b = self.track(Circle(center=self.at(25, 0), radius=20, group="b"))
        resolve("a", "b")
        self.step()
        ax, ay = a.center.x, a.center.y
        bx, by = b.center.x, b.center.y
        dist = math.hypot(bx - ax, by - ay)
        self.assertGreaterEqual(dist, 39.0)

    def test_mutual_tag_pool_separates_cluster(self):
        """``resolve("ball", "ball")`` still pushes a pile of overlapping circles."""
        balls = []
        for i in range(6):
            ball = self.track(Circle(
                center=self.at(i * 8, 0), radius=12, group="ball",
            ))
            ball.mass = 1.0
            balls.append(ball)
        resolve("ball", "ball")
        for _ in range(8):
            self.step()
        for i, a in enumerate(balls):
            for b in balls[i + 1:]:
                dist = math.hypot(
                    float(b.center.x) - float(a.center.x),
                    float(b.center.y) - float(a.center.y),
                )
                self.assertGreaterEqual(dist, 20.0)

    def test_query_sees_pose_written_before_step(self):
        """``test_collision`` before the next ``step()`` must read live pose."""
        a = self.track(Circle(center=self.at(0, 0), radius=10, group="a"))
        b = self.track(Circle(center=self.at(100, 0), radius=10, group="b"))
        a.collidable = True
        b.collidable = True
        self.step()
        self.assertIsNone(query_collision(a, b))
        b.center = self.at(10, 0)
        info = query_collision(a, b)
        self.assertIsNotNone(info)

    def test_floor_snap_bottom_refcount_skips_when_grounded(self):
        """Sweep contact marks bottom; floor snap early-outs via refcount."""
        ox, oy = self.at(0, 0)
        h = 20.0
        floor = self.track(Rect(
            center=(ox, oy), width=200, height=h, group="floor",
        ))
        floor.mass = STATIC
        floor_top = oy + h * 0.5
        body_h = 60.0
        hero = self.track(Rect(
            center=(ox, floor_top + body_h * 0.5 - 4.0),
            width=30, height=body_h, group="hero",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(0.0, -120.0)
        resolve("hero", "floor", bounce=0.0)
        for _ in range(6):
            hero.vel.y = min(hero.vel.y, -40.0)
            hero.move_by(0.0, hero.vel.y / 60.0)
            self.step()
        self.assertIn("bottom", hero.touching_sides)
        sys_ = get_collision_system()
        self.assertGreater(sys_._solve_bottom_count.get(id(hero._collider), 0), 0)
        y0 = float(hero.center.y)
        hero.vel.y = -20.0
        hero.move_by(0.0, hero.vel.y / 60.0)
        self.step()
        self.assertIn("bottom", hero.touching_sides)
        self.assertLess(abs(float(hero.center.y) - y0), 2.0)

    def test_partner_identity_cache_reused_until_enroll_change(self):
        """Partner identities cache across steps; invalidate when a member joins."""
        floor = self.track(Rect(
            center=self.at(0, -40), width=400, height=20, group="wall",
        ))
        floor.mass = STATIC
        balls = []
        for i in range(3):
            b = self.track(Circle(
                center=self.at(i * 30, 0), radius=12, group="ball",
            ))
            b.mass = 1.0
            balls.append(b)
        resolve("ball", "ball")
        resolve("ball", "wall", bounce=0.0)
        self.step()
        sys_ = get_collision_system()
        ca = balls[0]._collider
        partners1 = sys_._resolve_partners(ca)
        self.assertIn(id(ca), sys_._partner_ident_cache)
        cached_before = sys_._partner_ident_cache[id(ca)]
        self.step()
        partners2 = sys_._resolve_partners(ca)
        self.assertIs(sys_._partner_ident_cache[id(ca)], cached_before)
        self.assertEqual(len(partners1), len(partners2))
        # New enroll must invalidate so the new ball appears as a partner.
        newbie = self.track(Circle(
            center=self.at(15, 0), radius=12, group="ball",
        ))
        newbie.mass = 1.0
        sys_._try_enroll_item(newbie, tag="ball")
        self.assertNotIn(id(ca), sys_._partner_ident_cache)
        partners3 = sys_._resolve_partners(ca)
        partner_ids = {id(c) for c, _tok, _dx, _dy in partners3}
        self.assertIn(id(newbie._collider), partner_ids)

    def test_resolve_body_list_ignores_detection_only_colliders(self):
        """Movable resolve bodies come from resolve sides, not all colliders."""
        sensor = self.track(Circle(
            center=self.at(500, 500), radius=10, group="sensor",
        ))
        sensor.collidable = True
        floor = self.track(Rect(
            center=self.at(0, 0), width=100, height=20, group="floor",
        ))
        floor.mass = STATIC
        hero = self.track(Rect(
            center=self.at(0, 40), width=20, height=40, group="hero",
        ))
        hero.mass = 1.0
        resolve("hero", "floor", bounce=0.0)
        self.step()
        sys_ = get_collision_system()
        self.assertFalse(sys_._collider_in_resolve(sensor._collider))
        self.assertTrue(sys_._collider_in_resolve(hero._collider))
        # Detection-only collider is enrolled but must not be on the resolve body list.
        self.assertGreater(len(sys_._colliders), 2)
        self.assertFalse(sensor._collider._in_resolve)
    def test_resolve_without_collidable_enrolls(self):
        """Standing resolve alone declares detection for the pair."""
        a = self.track(Circle(center=self.at(0, 0), radius=20, group="a"))
        b = self.track(Circle(center=self.at(25, 0), radius=20, group="b"))
        self.assertFalse(a.collidable)
        self.assertFalse(b.collidable)
        resolve("a", "b")
        self.assertTrue(a.collidable)
        self.assertTrue(b.collidable)
        self.step()
        dist = math.hypot(b.center.x - a.center.x, b.center.y - a.center.y)
        self.assertGreaterEqual(dist, 39.0)

    def test_resolve_list_side_is_or(self):
        """List/tuple sides are OR — same grammar as ``@collide``."""
        ball = self.track(Circle(center=self.at(0, 0), radius=20, group="ball"))
        wall = self.track(Rect(center=self.at(25, 0), width=20, height=80, group="wall"))
        floor = self.track(Rect(center=self.at(400, 0), width=40, height=20, group="floor"))
        wall.mass = STATIC
        floor.mass = STATIC
        resolve("ball", ["floor", "wall"])
        x_before = ball.center.x
        self.step()
        self.assertLess(ball.center.x, x_before)

    def test_unresolve_stops_separation(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20, group="a"))
        b = self.track(Circle(center=self.at(25, 0), radius=20, group="b"))
        a.collidable = True
        b.collidable = True
        resolve("a", "b")
        self.step()
        ax1, bx1 = a.center.x, b.center.x
        unresolve("a", "b")
        b.center = self.at(25, 0)
        self.step()
        ax2, bx2 = a.center.x, b.center.x
        self.assertAlmostEqual(ax1, ax2, places=1)
        self.assertLess(bx2, bx1)

    def test_bounce_wall_stops_ball(self):
        ball = self.track(Circle(center=self.at(35, 0), radius=15, group="ball"))
        wall = self.track(Rect(center=self.at(60, 0), width=20, height=80, group="wall"))
        ball.collidable = True
        wall.collidable = True
        wall.mass = STATIC
        ball.vel = Vec2(200, 0)
        resolve("ball", "wall", bounce=0.0)
        for _ in range(30):
            ball.move_by(ball.vel.x * 0.016, ball.vel.y * 0.016)
            self.step()
        self.assertLess(abs(ball.vel.x), 50.0)

    def test_bounce_missing_partner_vel_treated_as_rest(self):
        """Finite-mass floor with no .vel still damps the body that has .vel."""
        ball = self.track(Circle(center=self.at(0, 18), radius=10, group="ball"))
        floor = self.track(Rect(center=self.at(0, -6), width=80, height=12, group="floor"))
        ball.mass = 1.0
        floor.mass = 1000.0
        self.assertIsNone(floor.vel)
        ball.vel = Vec2(0, -200)
        resolve("ball", "floor", bounce=0.0)
        for _ in range(20):
            ball.move_by(0, ball.vel.y * 0.016)
            self.step()
        self.assertGreater(ball.vel.y, -40.0)
        self.assertGreater(ball.center.y, floor.center.y)

    def test_resolve_lifts_body_sunk_past_floor_midpoint(self):
        """Deep overlap past the floor center lifts a falling body, not pushes it through."""
        # Wide floor, squat body: vertical overlap is the MTV (not a side-exit).
        # Body center is slightly below the floor center, falling — geometric SAT
        # would push down through the bottom; resolve must lift instead.
        mob = self.track(Rect(center=self.at(0, -2), width=30, height=20, group="mob"))
        floor = self.track(Rect(center=self.at(0, 0), width=200, height=40, group="floor"))
        mob.mass = 1.0
        floor.mass = 1000.0
        mob.vel = Vec2(0, -180)
        y_before = float(mob.center.y)
        resolve("mob", "floor", bounce=0.2)
        self.step()
        self.assertGreater(float(mob.center.y), y_before)
        self.assertGreater(float(mob.vel.y), -50.0)

    def test_query_collision_returns_info(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20))
        b = self.track(Circle(center=self.at(10, 0), radius=20))
        a.collidable = True
        b.collidable = True
        info = query_collision(a, b)
        self.assertIsNotNone(info)
        self.assertGreater(info.depth, 0)

    def test_query_shape_finds_group(self):
        probe = self.track(Circle(center=self.at(0, 0), radius=50))
        target = self.track(Circle(center=self.at(10, 0), radius=15, group="enemy"))
        other = self.track(Circle(center=self.at(-10, 0), radius=15, group="friend"))
        probe.collidable = True
        target.collidable = True
        other.collidable = True
        resolve(probe, "enemy")
        self.step()
        hits = collision.query_shape(probe, group="enemy")
        self.assertEqual(len(hits), 1)
        self.assertIs(hits[0], target)

    def test_collides_with_sugar(self):
        probe = self.track(Circle(center=self.at(0, 0), radius=50))
        target = self.track(Circle(center=self.at(10, 0), radius=15, group="enemy"))
        probe.collidable = True
        target.collidable = True
        resolve(probe, "enemy")
        self.step()
        self.assertEqual(probe.collides_with(group="enemy"), [target])

    def test_touching_sides_after_resolve(self):
        ball = self.track(Circle(center=self.at(0, 0), radius=15, group="ball"))
        floor = self.track(Rect(center=self.at(0, -40), width=120, height=20, group="floor"))
        ball.collidable = True
        floor.collidable = True
        floor.mass = STATIC
        resolve("ball", "floor", bounce=0.0)
        ball.vel = Vec2(0, -120)
        for _ in range(8):
            ball.move_by(0, ball.vel.y * 0.016)
            self.step()
        self.assertIn("bottom", ball.touching_sides)
        unresolve("ball", "floor")
        self.step()
        self.assertNotIn("bottom", ball.touching_sides)

    def test_touching_contact_slide_along(self):
        ball = self.track(Circle(center=self.at(0, 0), radius=15, group="ball"))
        floor = self.track(Rect(center=self.at(0, -40), width=120, height=20, group="floor"))
        ball.collidable = True
        floor.collidable = True
        floor.mass = STATIC
        resolve("ball", "floor", bounce=0.0)
        ball.vel = Vec2(80, -120)
        for _ in range(8):
            ball.move_by(ball.vel.x * 0.016, ball.vel.y * 0.016)
            self.step()
        self.assertTrue(ball.touching_contacts)
        contact = ball.touching_contacts[0]
        slid = contact.slide_along(Vec2(80, -120))
        self.assertAlmostEqual(slid.y, 0.0, places=1)
        self.assertGreater(abs(slid.x), 50.0)

    def test_touching_excludes_sensor_only_overlap(self):
        hero = self.track(Circle(center=self.at(0, 0), radius=15, group="hero"))
        floor = self.track(Rect(center=self.at(0, -40), width=120, height=20, group="floor"))
        star = self.track(Circle(center=self.at(0, 0), radius=10, group="star"))
        hero.collidable = True
        floor.collidable = True
        star.collidable = True
        floor.mass = STATIC
        resolve("hero", "floor", bounce=0.0)
        hero.vel = Vec2(0, -120)
        for _ in range(8):
            hero.move_by(0, hero.vel.y * 0.016)
            self.step()
        star.center = hero.center
        self.step()
        self.assertIn("bottom", hero.touching_sides)
        others = {c.other for c in hero.touching_contacts}
        self.assertIn(floor, others)
        self.assertNotIn(star, others)

    def test_grounded_formula_tracks_touching_sides(self):
        hero = self.track(Circle(center=self.at(0, 0), radius=15, group="hero"))
        floor = self.track(Rect(center=self.at(0, -40), width=120, height=20, group="floor"))
        hero.collidable = True
        floor.collidable = True
        floor.mass = STATIC
        resolve("hero", "floor", bounce=0.0)
        hero.vel = Vec2(0, -120)
        hero["grounded"] @= lambda: "bottom" in hero.touching_sides
        for _ in range(8):
            hero.move_by(0, hero.vel.y * 0.016)
            self.step()
        self.assertTrue(hero.grounded)
        hero.vel = Vec2(0, 500)
        for _ in range(20):
            hero.move_by(0, hero.vel.y * 0.016)
            self.step()
        self.assertFalse(hero.grounded)

    def test_wide_floor_landing_is_not_a_side_shove(self):
        """A body off-center on a wide floor must depenetrate vertically.

        Center-to-center on a long slab is mostly horizontal; that must not
        steal the MTV from a shallow floor overlap.
        """
        floor = self.track(Rect(
            center=self.at(400, 0), width=1000, height=40, group="plataforma",
        ))
        floor.mass = STATIC
        hero = self.track(Ellipse(
            center=self.at(0, 40), width=50, height=70, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(0, -200)
        resolve("heroi", "plataforma", bounce=0.0)
        x_before = float(hero.center.x)
        self.step()
        self.assertIn("bottom", hero.touching_sides)
        self.assertNotIn("left", hero.touching_sides)
        self.assertNotIn("right", hero.touching_sides)
        self.assertLess(abs(float(hero.center.x) - x_before), 2.0)
        self.assertGreater(float(hero.vel.y), -40.0)

    def test_thin_ramp_side_hit_does_not_launch(self):
        """Side overlap with a thin rotated slab must exit the end, not the face.

        Sweep TOI takes the end-face normal at the moment of touching;
        bounce=0 then removes only that normal component.
        """
        ox, oy = self.at(0, 0)
        ang = 22.0
        rad = math.radians(ang)
        c, s = math.cos(rad), math.sin(rad)
        plat = self.track(Rect(
            center=(ox, oy), width=200, height=24, angle=ang, group="plataforma",
        ))
        plat.mass = STATIC
        # Beside the left end and slightly above the top face: min-overlap SAT
        # prefers the 24px thickness (upward pop), but the center sits in the
        # end Voronoi region so resolve must still use the short face.
        lx, ly = -100.0 - 12.0, 12.0 + 8.0
        hero = self.track(Ellipse(
            center=(ox + lx * c - ly * s, oy + lx * s + ly * c),
            width=40, height=70, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(250, -200)
        resolve("heroi", "plataforma", bounce=0.0)
        vy_before = float(hero.vel.y)
        self.step()
        sides = hero.touching_sides
        self.assertTrue(sides & {"left", "right"}, f"side hit classified as {sides}")
        self.assertNotIn("bottom", sides)
        self.assertLess(float(hero.vel.y), 20.0)
        self.assertLess(float(hero.vel.y) - vy_before, 80.0)

    def test_bounce_zero_slope_walk_tracks_surface_without_launch(self):
        """Holding run on a 22° floor must track the slope, not rocket above it.

        Walking uphill legitimately gains height (dy/dx == tan(22°)); the bug
        this guards is the body's height gaining *faster* than the slope
        itself, which is the signature of an MTV/velocity launch off the
        surface rather than tracking it.
        """
        ox, oy = self.at(0, 0)
        ang = 22.0
        rad = math.radians(ang)
        s = math.sin(rad)
        c = math.cos(rad)
        plat = self.track(Rect(
            center=(ox, oy), width=200, height=24, angle=ang, group="plataforma",
        ))
        plat.mass = STATIC
        ly = 12.0 + 30.0
        hero = self.track(Ellipse(
            center=(ox - ly * s, oy + ly * c), width=40, height=70, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(0, -80)
        resolve("heroi", "plataforma", bounce=0.0)
        for _ in range(4):
            hero.vel.y -= 900.0 * 0.016
            hero.move_by(0.0, hero.vel.y * 0.016)
            self.step()
        self.assertIn("bottom", hero.touching_sides)
        x0, y0 = float(hero.center.x), float(hero.center.y)
        for _ in range(12):
            hero.vel.x = 250.0
            hero.vel.y -= 900.0 * 0.016
            hero.move_by(hero.vel.x * 0.016, hero.vel.y * 0.016)
            self.step()
            self.assertIn("bottom", hero.touching_sides)
        dx = float(hero.center.x) - x0
        dy = float(hero.center.y) - y0
        self.assertGreater(dx, 10.0)
        self.assertLess(abs(dy - dx * math.tan(rad)), 4.0)

    def test_thin_ramp_top_landing_still_bottom(self):
        """Landing on the long face of a 22° slab still reads as ground."""
        ox, oy = self.at(0, 0)
        ang = 22.0
        rad = math.radians(ang)
        c, s = math.cos(rad), math.sin(rad)
        plat = self.track(Rect(
            center=(ox, oy), width=200, height=24, angle=ang, group="plataforma",
        ))
        plat.mass = STATIC
        # Above the slab center, along local +y.
        ly = 12.0 + 30.0
        hero = self.track(Ellipse(
            center=(ox - ly * s, oy + ly * c), width=40, height=70, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(0, -180)
        resolve("heroi", "plataforma", bounce=0.0)
        for _ in range(12):
            hero.vel.y -= 900.0 * 0.016
            hero.move_by(0, hero.vel.y * 0.016)
            self.step()
        self.assertIn("bottom", hero.touching_sides)

    def test_bounce_zero_slope_landing_does_not_launch(self):
        """bounce=0 on a 22° floor must stop the fall, not convert vx into +vy."""
        ox, oy = self.at(0, 0)
        ang = 22.0
        rad = math.radians(ang)
        s = math.sin(rad)
        c = math.cos(rad)
        plat = self.track(Rect(
            center=(ox, oy), width=200, height=24, angle=ang, group="plataforma",
        ))
        plat.mass = STATIC
        ly = 12.0 + 20.0
        hero = self.track(Ellipse(
            center=(ox - ly * s, oy + ly * c), width=40, height=70, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(250, -200)
        resolve("heroi", "plataforma", bounce=0.0)
        self.step()
        self.assertIn("bottom", hero.touching_sides)
        # Inelastic impulse at the surface normal keeps the tangent; running
        # uphill therefore leaves a modest +vy along the slope, not a launch.
        self.assertLess(float(hero.vel.y), 120.0)
        self.assertGreater(float(hero.vel.x), 100.0)

    def test_bounce_zero_slope_fall_does_not_kick_sideways(self):
        """A vertical fall onto a 22° floor must stop, not gain horizontal speed."""
        ox, oy = self.at(0, 0)
        ang = 22.0
        rad = math.radians(ang)
        s = math.sin(rad)
        c = math.cos(rad)
        plat = self.track(Rect(
            center=(ox, oy), width=200, height=24, angle=ang, group="plataforma",
        ))
        plat.mass = STATIC
        ly = 12.0 + 20.0
        hero = self.track(Ellipse(
            center=(ox - ly * s, oy + ly * c), width=40, height=70, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(0, -240)
        resolve("heroi", "plataforma", bounce=0.0)
        self.step()
        self.assertIn("bottom", hero.touching_sides)
        # Tangent leftover on a 22° face is real slide, not a sideways kick
        # from a wrong MTV axis. |vx| stays at the slope projection of the
        # incoming fall (~90 DU/s), and the body must not launch.
        self.assertLess(abs(float(hero.vel.x)), 120.0)
        self.assertLessEqual(float(hero.vel.y), 5.0)
        self.assertGreater(float(hero.vel.y), -40.0)

    def test_jump_into_descending_platform_underside_does_not_glue(self):
        """Head-bonk into a descending platform must not glue the jumper to it.

        Relative-frame leftover inheritance is a world-space conversion for
        every contact side. Gating it to ``side == "bottom"`` left a residual
        overlap on ceiling hits; the next frame's already-overlapping TOI then
        clamped the jumper's separating motion and the pair stayed stuck.
        """
        ox, oy = self.at(0, 0)
        plat = self.track(Rect(
            center=(ox, oy + 150.0), width=120.0, height=20.0, group="plataforma",
        ))
        plat.mass = STATIC
        plat.vel = Vec2(0.0, -80.0)
        hero = self.track(Rect(
            center=(ox, oy), width=38.0, height=70.0, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(0.0, 460.0)
        resolve("heroi", "plataforma", bounce=0.0)
        dt = 1.0 / 60.0
        hit_frame = None
        stuck_top = 0
        for frame in range(90):
            hero.vel.y -= 900.0 * dt
            hero.move_by(0.0, hero.vel.y * dt)
            plat.move_by(0.0, plat.vel.y * dt)
            self.step()
            if "top" in hero.touching_sides:
                if hit_frame is None:
                    hit_frame = frame
                else:
                    stuck_top += 1
        self.assertIsNotNone(hit_frame, "jump never reached the platform underside")
        self.assertEqual(
            stuck_top, 0,
            f"stayed glued to underside for {stuck_top} frames after first contact",
        )
        self.assertNotIn("top", hero.touching_sides)
        self.assertLess(float(hero.vel.y), float(plat.vel.y) - 50.0)

    def test_bounce_zero_moving_floor_carries_rider(self):
        """A STATIC floor with vel.y must still lift a resting rider (elevator)."""
        floor = self.track(Rect(
            center=self.at(0, 0), width=200, height=24, group="plataforma",
        ))
        floor.mass = STATIC
        floor.vel = Vec2(0, 80)
        hero = self.track(Ellipse(
            center=self.at(0, 40), width=40, height=70, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(0, 0)
        resolve("heroi", "plataforma", bounce=0.0)
        self.step()
        self.assertIn("bottom", hero.touching_sides)
        self.assertGreater(float(hero.vel.y), 40.0)

    def test_descending_elevator_with_side_contact_does_not_stall_horizontal_input(self):
        """Holding run on a descending elevator must not freeze x near side contact."""
        ox, oy = self.at(0, 0)
        elev = self.track(Rect(
            center=(ox + 230.0, oy + 120.0), width=120.0, height=20.0, group="plataforma",
        ))
        elev.mass = STATIC
        elev.vel = Vec2(0.0, -80.0)
        slab = self.track(Rect(
            center=(ox + 420.0, oy + 200.0), width=220.0, height=24.0, group="plataforma",
        ))
        slab.mass = STATIC
        hero = self.track(Rect(
            center=(ox + 230.0, oy + 167.08), width=38.0, height=70.0, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(0.0, -80.0)
        resolve("heroi", "plataforma", bounce=0.0)
        dt = 1.0 / 60.0
        self.step()
        x0 = float(hero.center.x)
        max_stall = 0
        stall = 0
        for _ in range(40):
            hero.vel.x = 250.0
            hero.vel.y -= 900.0 * dt
            x_prev = float(hero.center.x)
            hero.move_by(hero.vel.x * dt, hero.vel.y * dt)
            elev.move_by(0.0, elev.vel.y * dt)
            self.step()
            dx = float(hero.center.x) - x_prev
            if "left" in hero.touching_sides and abs(dx) < 0.05:
                stall += 1
            else:
                stall = 0
            max_stall = max(max_stall, stall)
        self.assertLessEqual(max_stall, 3, f"horizontal input stalled for {max_stall} frames")
        self.assertGreater(float(hero.center.x) - x0, 40.0)

    def test_corner_underside_and_elevator_side_contact_does_not_glue(self):
        """Simultaneous underside+side contact must not pin the jumper in place."""
        ox, oy = self.at(0, 0)
        elev = self.track(Rect(
            center=(ox + 230.0, oy + 120.0), width=120.0, height=20.0, group="plataforma",
        ))
        elev.mass = STATIC
        elev.vel = Vec2(0.0, -80.0)
        slab = self.track(Rect(
            center=(ox + 420.0, oy + 200.0), width=220.0, height=24.0, group="plataforma",
        ))
        slab.mass = STATIC
        hero = self.track(Rect(
            center=(ox + 300.0, oy + 100.0), width=38.0, height=70.0, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(0.0, 460.0)
        resolve("heroi", "plataforma", bounce=0.0)
        dt = 1.0 / 60.0
        stuck_top = 0
        hit_corner = False
        peak_y = float(hero.center.y)
        for _ in range(90):
            hero.vel.y -= 900.0 * dt
            hero.move_by(0.0, hero.vel.y * dt)
            elev.move_by(0.0, elev.vel.y * dt)
            self.step()
            peak_y = max(peak_y, float(hero.center.y))
            sides = hero.touching_sides
            if "top" in sides and "left" in sides:
                hit_corner = True
            if hit_corner and "top" in sides:
                stuck_top += 1
        self.assertTrue(hit_corner, "repro never touched underside+side corner")
        self.assertLessEqual(stuck_top, 3, f"stayed glued under corner for {stuck_top} frames")
        self.assertNotIn("top", hero.touching_sides)
        self.assertLess(float(hero.center.y), peak_y - 20.0)

    def test_flat_slab_corner_clip_while_jumping_is_not_a_floor_stop(self):
        """Jumping past the corner of a flat slab must not be read as landing on it."""
        ox, oy = self.at(0, 0)
        plat = self.track(Rect(
            center=(ox, oy), width=200, height=24, group="plataforma",
        ))
        plat.mass = STATIC
        hero = self.track(Ellipse(
            center=(ox - 100.0 - 12.0, oy + 39.0), width=40, height=70, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(250, 250)
        resolve("heroi", "plataforma", bounce=0.0)
        self.step()
        sides = hero.touching_sides
        self.assertNotIn("bottom", sides, f"corner clip classified as {sides}")
        # Honest impulse at a side/ceiling corner keeps the tangent, so a
        # jump is not arrested the way the old bounce=0 platformer-stop did.
        self.assertGreater(float(hero.vel.y), 50.0)


class TestSweepMassSplit(CollisionTestCase):
    """A sweep stop between two movable bodies splits by inverse mass (MS1).

    Bug class: the body swept first (lower ``_collider_index``) stopped at the
    contact and inherited the partner's leftover, whatever the masses. Every
    position outcome between two finite masses then depended on enrollment
    order: a crate was never pushed (player first) or pushed at full player
    speed even at mass 50 (crate first); a mass-1 floor held a rider or sank
    under it; a spring-held wall driven by ``move_by`` was carried by a ball's
    whole step and the box gained ~45 % energy in 10 s. Each test runs both
    orders and asserts they agree. Collision Design, "Relative-frame sweep".
    """

    DT = 1.0 / 60.0

    def fresh(self):
        """An empty world for the next run (the two orders must not meet)."""
        for s in self._owned:
            try:
                s.destroy()
            except Exception:
                pass
        self._owned.clear()
        reset_collision_system()

    def enroll(self, *bodies):
        """Enroll in this order (the sweep order)."""
        for b in bodies:
            b.collidable = True

    def spring_box(self, wall_first: bool, k: float = 6.0, wall_mass: float = 50.0):
        """Balls between STATIC walls and a spring-held wall moved by ``move_by``:
        the spring reads the pose. Returns the energy ratio after 10 s."""
        self.fresh()
        ox, oy = self.at(0, 0)
        home = ox + 300.0
        fixed = [
            self.track(Rect(center=(ox - 20, oy), width=20, height=400, group="fixo")),
            self.track(Rect(center=(ox + 140, oy + 210), width=340, height=20, group="fixo")),
            self.track(Rect(center=(ox + 140, oy - 210), width=340, height=20, group="fixo")),
        ]
        for f in fixed:
            f.mass = STATIC
        wall = self.track(Rect(center=(home, oy), width=20, height=400, group="mola"))
        wall.mass = wall_mass
        wall.vel = Vec2(0, 0)
        balls = []
        for i in range(6):
            b = self.track(Circle(center=(ox + 50 + 30 * i, oy - 150 + 60 * i), radius=7,
                                  group="bola"))
            b.vel = Vec2(400.0 * (1 if i % 2 else -1), 37.0 * (i - 2.5))
            balls.append(b)
        self.enroll(*fixed, *(([wall] + balls) if wall_first else (balls + [wall])))
        resolve("bola", ["mola", "fixo"], bounce=1)
        resolve("bola", "bola", bounce=1)

        def energy():
            e = sum(0.5 * b.mass * b.vel.length ** 2 for b in balls)
            x = float(wall.center.x) - home
            return e + 0.5 * wall_mass * (wall.vel.length ** 2 + k * x * x)

        e0 = energy()
        for _ in range(600):
            wall.vel = Vec2(wall.vel.x - (float(wall.center.x) - home) * k * self.DT, 0.0)
            wall.move_by(wall.vel.x * self.DT, 0)
            for b in balls:
                b.move_by(b.vel.x * self.DT, b.vel.y * self.DT)
            self.step()
        return energy() / e0

    def test_spring_held_body_keeps_its_energy_in_either_order(self):
        for wall_first in (True, False):
            with self.subTest(wall_first=wall_first):
                self.assertAlmostEqual(self.spring_box(wall_first), 1.0, delta=0.02)

    def test_mass_blind_sweep_gains_energy_canary(self):
        """The old rule fails the energy test above: the test catches the class."""
        from unittest import mock
        coll = sys.modules["scena.collision"]    # ``scena.collision`` is the facade
        with mock.patch.object(coll, "_SWEEP_MASS_SPLIT", False):
            self.assertGreater(self.spring_box(wall_first=True), 1.2)

    def push_crate(self, player_first: bool, crate_mass: float):
        self.fresh()
        ox, oy = self.at(0, 0)
        player = self.track(Rect(center=(ox, oy), width=20, height=20, group="jogador"))
        crate = self.track(Rect(center=(ox + 30.5, oy), width=20, height=20, group="caixa"))
        crate.mass = crate_mass
        self.enroll(*((player, crate) if player_first else (crate, player)))
        resolve("jogador", "caixa")
        for _ in range(30):
            player.move_by(300.0 * self.DT, 0)
            self.step()
        return float(player.center.x) - ox, float(crate.center.x) - ox - 30.5

    def test_push_splits_by_mass_in_either_order(self):
        for mass in (1.0, 50.0):
            a = self.push_crate(True, mass)
            b = self.push_crate(False, mass)
            with self.subTest(mass=mass):
                self.assertAlmostEqual(a[0], b[0], places=6)
                self.assertAlmostEqual(a[1], b[1], places=6)
                # 150 DU of intent, ~10.5 of them before the contact: the crate
                # takes 1 / (1 + mass) of the rest, the player keeps up with it.
                share = 1.0 / (1.0 + mass)
                self.assertAlmostEqual(b[1], 139.5 * share, delta=1.5)
                self.assertAlmostEqual(a[0] - a[1], 10.42, delta=0.05)

    def test_static_partner_takes_no_share(self):
        player, crate = self.push_crate(True, STATIC)
        self.assertEqual(crate, 0.0)
        self.assertAlmostEqual(player, 10.42, delta=0.01)

    def finite_floor(self, floor_first: bool):
        self.fresh()
        ox, oy = self.at(0, 0)
        floor = self.track(Rect(center=(ox, oy), width=200, height=20, group="chao"))
        hero = self.track(Rect(center=(ox, oy + 30.08), width=20, height=40, group="heroi"))
        self.enroll(*((floor, hero) if floor_first else (hero, floor)))
        floor.vel = Vec2(0, 0)
        hero.vel = Vec2(0, 0)
        resolve("heroi", "chao", bounce=0.0)
        for _ in range(60):
            hero.vel.y -= 900.0 * self.DT
            hero.move_by(0, hero.vel.y * self.DT)
            self.step()
        return float(floor.center.y) - oy, float(hero.center.y) - float(floor.center.y)

    def test_movable_floor_under_a_rider_is_order_free(self):
        """A floor left at mass 1 is a body: an equal mass falling on it pushes
        it (STATIC is the floor that does not give). Before, it held or sank
        depending on who enrolled first."""
        a = self.finite_floor(True)
        b = self.finite_floor(False)
        self.assertAlmostEqual(a[0], b[0], places=6)
        self.assertLess(a[0], -10.0)
        self.assertAlmostEqual(a[1], 30.08, delta=0.05)
        self.assertAlmostEqual(b[1], 30.08, delta=0.05)

    def test_push_into_a_thin_wall_stops_at_it(self):
        """The partner's share is swept against its STATIC partners: a light
        body shoved toward a 2 DU wall is not placed past it, and the pusher
        stops against it."""
        for speed in (600.0, 2400.0, 6000.0):
            with self.subTest(speed=speed):
                self.fresh()
                ox, oy = self.at(0, 0)
                wall = self.track(Rect(center=(ox + 100, oy), width=2, height=200, group="fixo"))
                wall.mass = STATIC
                face = ox + 99.0
                a = self.track(Circle(center=(ox, oy), radius=8, group="bola"))
                b = self.track(Circle(center=(face - 8 - 0.08, oy), radius=8, group="bola"))
                b.mass = 0.2
                self.enroll(wall, a, b)
                resolve("bola", ["bola", "fixo"])
                for _ in range(30):
                    a.move_by(speed * self.DT, 0)
                    self.step()
                    self.assertLessEqual(float(b.center.x) + 8, face + 1e-6)
                    self.assertLessEqual(float(a.center.x), float(b.center.x))


class TestSweepAndSlideGates(CollisionTestCase):
    """Phase 1 gates from the sweep-and-slide rework (Collision Resolution Redesign §4 / §10).

    These must fail on MTV depenetration (the documented reasons) and pass
    once sweep-and-slide is the resolve path.
    """

    def test_correction_does_not_leave_body_inside_thin_slab(self):
        """§4.1: a fall that spans a thin slab must rest on top, not teleport by thickness.

        A 70 DU body that this frame sweeps through a 24 DU slab has SAT depth
        equal to the slab thickness, so MTV leaves the body still inside.
        Wanted: residual overlap ≤ slop, correction bounded by this frame's motion.
        """
        from scena.collision import _RESOLVE_SLOP

        slab_h = 24.0
        body_h = 70.0
        ox, oy = self.at(0, 0)
        slab = self.track(Rect(
            center=(ox, oy), width=220.0, height=slab_h, group="plataforma",
        ))
        slab.mass = STATIC
        slab_top = oy + slab_h * 0.5
        gap = 2.0
        step_down = 40.0
        hero = self.track(Rect(
            center=(ox, slab_top + body_h * 0.5 + gap),
            width=38.0, height=body_h, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(0.0, -300.0)
        resolve("heroi", "plataforma", bounce=0.0)
        y_start = float(hero.center.y)
        hero.move_by(0.0, -step_down)
        y_sunk = float(hero.center.y)
        self.step()
        y_after = float(hero.center.y)
        bottom = y_after - body_h * 0.5
        self.assertGreaterEqual(
            bottom, slab_top - _RESOLVE_SLOP - 0.5,
            f"still inside slab: bottom={bottom:.2f} top={slab_top:.2f}",
        )
        self.assertLessEqual(y_after - y_sunk, step_down + _RESOLVE_SLOP + 0.5)
        self.assertLessEqual(y_start - y_after, step_down + 1.0)

    def test_two_overlapping_floors_apply_one_correction(self):
        """§4.2: N same-normal contacts must not stack N independent MTV pushes."""
        ox, oy = self.at(0, 0)
        h = 24.0
        floor_top = oy + h * 0.5
        for dx in (-60.0, 60.0):
            slab = self.track(Rect(
                center=(ox + dx, oy), width=200.0, height=h, group="plataforma",
            ))
            slab.mass = STATIC
        body_h = 70.0
        penetration = 6.0
        hero = self.track(Rect(
            center=(ox, floor_top + body_h * 0.5 - penetration),
            width=38.0, height=body_h, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(0.0, -120.0)
        resolve("heroi", "plataforma", bounce=0.0)
        y0 = float(hero.center.y)
        self.step()
        dy = float(hero.center.y) - y0
        self.assertGreater(dy, 1.0)
        self.assertLess(
            dy, penetration + 2.0,
            f"stacked correction dy={dy:.2f} (wanted ~{penetration})",
        )

    def test_side_impact_at_ledge_height_is_never_floor(self):
        """§4.3: running into a slab's end with feet 2 DU below the top is a wall."""
        ox, oy = self.at(500, 300)
        slab_w, slab_h = 220.0, 24.0
        hero_w, hero_h = 38.0, 70.0
        slab = self.track(Rect(
            center=(ox, oy), width=slab_w, height=slab_h, group="plataforma",
        ))
        slab.mass = STATIC
        slab_top = oy + slab_h * 0.5
        slab_left = ox - slab_w * 0.5
        feet_offset = 2.0
        hero = self.track(Rect(
            center=(slab_left - hero_w * 0.5 - 6.0, slab_top - feet_offset + hero_h * 0.5),
            width=hero_w, height=hero_h, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(250.0, 0.0)
        resolve("heroi", "plataforma", bounce=0.0)
        dt = 1.0 / 60.0
        y0 = float(hero.center.y)
        saw_bottom = False
        for _ in range(30):
            hero.vel.x = 250.0
            hero.vel.y -= 900.0 * dt
            hero.move_by(hero.vel.x * dt, hero.vel.y * dt)
            self.step()
            if "bottom" in hero.touching_sides:
                saw_bottom = True
                break
        self.assertFalse(saw_bottom, "ledge-height side hit classified as floor")
        self.assertLess(float(hero.center.y) - y0, 8.0)

    def test_jump_into_ramp_end_does_not_exceed_free_jump(self):
        """§4.4: jumping into a 22° ramp end face must not ratchet above a free jump."""
        dt = 1.0 / 60.0
        gravity = 900.0
        jump_vy = 460.0
        ox, oy = self.at(880, 260)
        ang = 22.0
        rad = math.radians(ang)
        w, h = 200.0, 24.0
        slab = self.track(Rect(
            center=(ox, oy), width=w, height=h, angle=ang, group="plataforma",
        ))
        slab.mass = STATIC
        low_x = ox - (w / 2) * math.cos(rad) + (h / 2) * math.sin(rad)
        low_y = oy - (w / 2) * math.sin(rad) - (h / 2) * math.cos(rad)
        hero = self.track(Rect(
            center=(low_x - 40.0, low_y - 60.0),
            width=38.0, height=70.0, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(250.0, jump_vy)
        resolve("heroi", "plataforma", bounce=0.0)
        y0 = float(hero.center.y)
        peak = y0
        for _ in range(80):
            hero.vel.x = 250.0
            hero.vel.y -= gravity * dt
            hero.move_by(hero.vel.x * dt, hero.vel.y * dt)
            self.step()
            peak = max(peak, float(hero.center.y))
        rise = peak - y0
        free = jump_vy * jump_vy / (2.0 * gravity)
        self.assertLess(
            rise, free + 20.0,
            f"ramp-end launch rise={rise:.1f} vs free jump {free:.1f}",
        )

    def test_small_body_does_not_tunnel_at_sixty_du_per_frame(self):
        """§4.5: a 2 DU body at 60 DU/frame must not pass through a 24 DU slab."""
        ox, oy = self.at(500, 300)
        slab_h = 24.0
        slab = self.track(Rect(
            center=(ox, oy), width=220.0, height=slab_h, group="plataforma",
        ))
        slab.mass = STATIC
        slab_bot = oy - slab_h * 0.5
        radius = 2.0
        speed = 3600.0
        dt = 1.0 / 60.0
        ball = self.track(Circle(
            center=(ox, oy + slab_h * 0.5 + radius + 8.0),
            radius=radius, group="bola",
        ))
        ball.mass = 1.0
        ball.vel = Vec2(0.0, -speed)
        resolve("bola", "plataforma", bounce=0.0)
        passed = False
        for _ in range(20):
            ball.vel.y -= 900.0 * dt
            ball.move_by(0.0, ball.vel.y * dt)
            self.step()
            if float(ball.center.y) + radius < slab_bot - 1.0:
                passed = True
                break
        self.assertFalse(passed, "2 DU body tunnelled through the slab at 60 DU/frame")

    def test_downhill_walk_stays_grounded(self):
        """Phase 4 / probe 7: walking down a 22° ramp must not ballistic-hop."""
        dt = 1.0 / 60.0
        ox, oy = self.at(880, 260)
        ang = 22.0
        rad = math.radians(ang)
        w, h = 200.0, 24.0
        slab = self.track(Rect(
            center=(ox, oy), width=w, height=h, angle=ang, group="plataforma",
        ))
        slab.mass = STATIC
        start_x = ox + 70.0
        nx, ny = -math.sin(rad), math.cos(rad)
        px, py = ox + nx * h * 0.5, oy + ny * h * 0.5
        surf = py + math.tan(rad) * (start_x - px)
        hero = self.track(Rect(
            center=(start_x, surf + 35.0 + 2.0), width=38.0, height=70.0, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(0.0, -80.0)
        resolve("heroi", "plataforma", bounce=0.0)
        for _ in range(12):
            hero.vel.y -= 900.0 * dt
            hero.move_by(0.0, hero.vel.y * dt)
            self.step()
        self.assertIn("bottom", hero.touching_sides)
        grounded = 0
        airborne = 0
        x_end = ox - 60.0
        for _ in range(40):
            hero.vel.x = -250.0
            hero.vel.y -= 900.0 * dt
            hero.move_by(hero.vel.x * dt, hero.vel.y * dt)
            self.step()
            if "bottom" in hero.touching_sides:
                grounded += 1
                airborne = 0
            else:
                airborne += 1
            self.assertLess(airborne, 4, "downhill hop lasted 4+ frames")
            if float(hero.center.x) <= x_end:
                break
        self.assertGreater(grounded, 15)

    def test_spawn_inside_wall_walks_out_monotonically(self):
        """Phase 5: a body spawned inside a wall recovers without overshoot."""
        ox, oy = self.at(0, 0)
        wall = self.track(Rect(
            center=(ox, oy), width=80.0, height=80.0, group="wall",
        ))
        wall.mass = STATIC
        body = self.track(Circle(center=(ox, oy), radius=12.0, group="mob"))
        body.mass = 1.0
        body.vel = Vec2(0.0, 0.0)
        resolve("mob", "wall")
        dist0 = 0.0
        prev = dist0
        overshoot = False
        for _ in range(20):
            self.step()
            dist = math.hypot(float(body.center.x) - ox, float(body.center.y) - oy)
            if dist + 0.05 < prev:
                overshoot = True
            prev = dist
        self.assertFalse(overshoot, "settle reversed direction")
        self.assertGreaterEqual(prev, 40.0 - 12.0 - 1.0)

    def _fresh_scene(self):
        for shape in self._owned:
            try:
                shape.destroy()
            except Exception:
                pass
        self._owned.clear()
        reset_collision_system()
        CollisionTestCase._origin += 5000
        self.origin = CollisionTestCase._origin

    def test_sweep_correction_does_not_invent_a_contact_the_prims_miss(self):
        """A sweep stop must not invent a contact from a fatter box.

        Stopping against one partner makes the solved pose differ from the
        motion channel, so unswept recovery runs against every other partner.
        Two boxes are fatter than the prims and used to count as a crossed
        face: the sprite circumradius, and the bounding box of a rotated
        body. ``bounce=0`` on that false contact cancels the free axis until
        the push into the real wall stops. The false face can be any side.
        """
        for source in ("proxy", "rotated"):
            for side in ("bottom", "top", "left", "right"):
                with self.subTest(source=source, side=side):
                    self._fresh_scene()
                    self._assert_no_phantom_from_fat_bounds(source, side)

    def _assert_no_phantom_from_fat_bounds(self, source, side):
        half = 20.0
        ox, oy = self.at(0, 0)
        along = {"bottom": (0.0, -1.0), "top": (0.0, 1.0),
                 "left": (-1.0, 0.0), "right": (1.0, 0.0)}[side]
        phantom_line = half + 12.0
        if source == "proxy":
            # A circle hitbox (radius 20) turned 45°: the broad-phase proxy is
            # its extent box turned by the heading, reaching about 28.3 on each
            # axis. The decoy's near face sits in the gap between the circle
            # (20) and that reach, so only the broad phase overlaps and a real
            # prim hit is still more than 8 DU of travel away.
            near = half + 8.1
            phantom_line = near
            decoy = self.track(Rect(
                center=(ox + along[0] * (near + 8.0), oy + along[1] * (near + 8.0)),
                width=16.0 if side in ("left", "right") else 400.0,
                height=400.0 if side in ("left", "right") else 16.0,
                group="plataforma",
            ))
            body = self.track(Sprite(
                center=(ox, oy), size=40, hitbox_shape="circle", group="heroi",
            ))
            body._hitbox_kind = "auto"
            body._hitbox_circles = ((0.0, 0.0, 0.5),)
            body._hitbox_circle = body._hitbox_circles[0]
            body._hitbox_boxes = ()
            body._recompute_hitbox_local_radius()
            body._auto_baked = True
            body.angle = 45.0
            proxy = _proxy_aabb_for_shape(body)
            reach = proxy[2] - ox if side in ("left", "right") else proxy[3] - oy
            self.assertGreater(reach, near)
        else:
            # The bar's bounding box crosses the body's path. The bar itself
            # stays past this run's travel, so a prim-AABB hit is empty space.
            wide = side in ("bottom", "top")
            dist = 200.0 if wide else 250.0
            decoy = self.track(Rect(
                center=(ox + along[0] * dist, oy + along[1] * dist),
                width=900.0 if wide else 520.0,
                height=16.0,
                angle=22.0,
                group="plataforma",
            ))
            body = self.track(Rect(
                center=(ox, oy), width=40.0, height=40.0, group="heroi",
            ))
        decoy.mass = STATIC
        if side in ("bottom", "top"):
            blocker = self.track(Rect(
                center=(ox + 48.0, oy), width=24.0, height=480.0, group="plataforma",
            ))
        else:
            blocker = self.track(Rect(
                center=(ox, oy + 48.0), width=480.0, height=24.0, group="plataforma",
            ))
        blocker.mass = STATIC
        body.mass = 1.0
        body.vel = Vec2(0.0, 0.0)
        resolve("heroi", "plataforma", bounce=0.0)
        self.step()
        cs = get_collision_system()
        free0 = float(body.center.y if side in ("bottom", "top") else body.center.x)
        phantom = 0
        bounds_overlapped = False
        proxies_overlapped = False
        hit_blocker = False
        dt = 1.0 / 60.0
        for _ in range(30):
            if side in ("bottom", "top"):
                body.vel.x = 250.0
                body.vel.y += (-900.0 if side == "bottom" else 900.0) * dt
            else:
                body.vel.y = 250.0
                body.vel.x += (-900.0 if side == "left" else 900.0) * dt
            body.move_by(body.vel.x * dt, body.vel.y * dt)
            self.step()
            ab = cs._exact_bounds_aabb(body._collider)
            bb = cs._exact_bounds_aabb(decoy._collider)
            if ab is not None and bb is not None and _aabb_overlaps_box(ab, bb):
                bounds_overlapped = True
            if _proxy_aabb_overlap(body._collider, decoy._collider):
                proxies_overlapped = True
            if any(c.other is blocker for c in body.touching_contacts):
                hit_blocker = True
            cx, cy = float(body.center.x), float(body.center.y)
            # Slop (~0.08) seats a real hit just clear of the face. A phantom
            # pin sits a proxy-radius away, so 2 DU still catches it.
            skin = 2.0
            if side == "bottom":
                clear = (cy - half) > (oy - phantom_line + skin)
            elif side == "top":
                clear = (cy + half) < (oy + phantom_line - skin)
            elif side == "left":
                clear = (cx - half) > (ox - phantom_line + skin)
            else:
                clear = (cx + half) < (ox + phantom_line - skin)
            if source == "rotated":
                clear = True
            if clear and any(c.other is decoy for c in body.touching_contacts):
                phantom += 1
        free1 = float(body.center.y if side in ("bottom", "top") else body.center.x)
        sign = -1.0 if side in ("bottom", "left") else 1.0
        self.assertTrue(hit_blocker)
        self.assertEqual(phantom, 0)
        self.assertGreater((free1 - free0) * sign, 8.0)
        if source == "rotated":
            self.assertTrue(
                bounds_overlapped,
                "rotated bounds never overlapped the body; the case is vacuous",
            )
        else:
            self.assertTrue(
                proxies_overlapped,
                "broad-phase proxies never overlapped the decoy; the case is vacuous",
            )

    def test_unswept_growth_into_ceiling_stays_on_entry_side(self):
        """A box that grows up into a thin slab while vy has turned down stays below.

        The growth is not motion-channel translation, so the sweep never sees it.
        Capped settle used to spend its budget out the far side. The entry face
        is the underside the bounds crossed.
        """
        ox, oy = self.at(0, 0)
        slab = self.track(Rect(
            center=(ox, oy + 200.0), width=220.0, height=24.0, group="plataforma",
        ))
        slab.mass = STATIC
        slab_bottom = oy + 200.0 - 12.0
        h0 = 50.0
        hero = self.track(Rect(
            center=(ox, oy + 159.0), width=36.0, height=h0, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(0.0, -30.0)
        resolve("heroi", "plataforma", bounce=0.0)
        self.step()
        self.assertLess(float(hero.center.y) + h0 * 0.5, slab_bottom)
        hero.move_by(0.0, float(hero.vel.y) / 60.0)
        h1 = 90.0
        hero.height = h1
        hero.center = (
            float(hero.center.x),
            float(hero.center.y) + (h1 - h0) * 0.5,
        )
        self.step()
        top = float(hero.center.y) + h1 * 0.5
        self.assertLess(top, slab_bottom + 0.02)
        self.assertGreater(top, slab_bottom - 2.0)
        self.assertIn("top", hero.touching_sides)
        self.assertLess(float(hero.vel.y), 0.0)
        hero.vel.y -= 900.0 / 60.0
        hero.move_by(0.0, float(hero.vel.y) / 60.0)
        self.step()
        top2 = float(hero.center.y) + float(hero.height) * 0.5
        self.assertLess(top2, slab_bottom + 0.02)

    def test_unswept_ellipse_shift_into_ceiling_stays_on_entry_side(self):
        """Same slab, ellipse shifted up by a center write (not ``move_by``)."""
        ox, oy = self.at(0, 0)
        slab = self.track(Rect(
            center=(ox, oy + 200.0), width=220.0, height=24.0, group="plataforma",
        ))
        slab.mass = STATIC
        slab_bottom = oy + 200.0 - 12.0
        h = 50.0
        hero = self.track(Ellipse(
            center=(ox, oy + 159.0), width=36.0, height=h, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(0.0, -30.0)
        resolve("heroi", "plataforma", bounce=0.0)
        self.step()
        self.assertLess(float(hero.center.y) + h * 0.5, slab_bottom)
        hero.move_by(0.0, float(hero.vel.y) / 60.0)
        hero.center = (float(hero.center.x), float(hero.center.y) + 28.0)
        self.step()
        top = float(hero.center.y) + h * 0.5
        self.assertLess(top, slab_bottom + 0.02)
        self.assertGreater(top, slab_bottom - 2.0)
        self.assertIn("top", hero.touching_sides)
        self.assertLess(float(hero.vel.y), 0.0)

    def test_moving_platform_pushes_resting_body_without_launch(self):
        """Phase 5: a platform driven into a sleeper lifts it, without a jump."""
        ox, oy = self.at(0, 0)
        floor = self.track(Rect(
            center=(ox, oy), width=200.0, height=24.0, group="plataforma",
        ))
        floor.mass = STATIC
        floor.vel = Vec2(0.0, 80.0)
        hero = self.track(Rect(
            center=(ox, oy + 12.0 + 35.0), width=38.0, height=70.0, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(0.0, 0.0)
        resolve("heroi", "plataforma", bounce=0.0)
        self.step()
        y0 = float(hero.center.y)
        for _ in range(10):
            floor.move_by(0.0, floor.vel.y * (1.0 / 60.0))
            self.step()
        self.assertGreater(float(hero.center.y), y0 + 5.0)
        self.assertLess(float(hero.vel.y), 200.0)
        self.assertIn("bottom", hero.touching_sides)

    def test_rising_platform_short_frames_keep_grounded(self):
        """Floor snap leave-gate must use contact-normal relative leave, not world-up.

        Resting contact leaves ``_RESOLVE_SLOP`` of separation. Closing it needs
        ``g·dt² ≥ slop``, so frames shorter than ~√(slop/g) ≈ 9.4 ms miss the
        primary sweep. An absolute ``vy > 8`` gate disabled snap for every
        rising ride; normal-projected leave (speed + displacement) restores
        the backstop without special-casing elevators.
        """
        ox, oy = self.at(0, 0)
        floor = self.track(Rect(
            center=(ox, oy), width=200.0, height=24.0, group="plataforma",
        ))
        floor.mass = STATIC
        floor.vel = Vec2(0.0, 80.0)
        hero = self.track(Rect(
            center=(ox, oy + 12.0 + 35.0), width=38.0, height=70.0, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(0.0, 0.0)
        resolve("heroi", "plataforma", bounce=0.0)
        self.step()
        self.assertIn("bottom", hero.touching_sides)
        # Alternating short/long frames — the short half is below the
        # g·dt² ≥ slop threshold that primary contact needs.
        pattern = (0.005, 0.028)
        misses = 0
        for i in range(60):
            dt = pattern[i % 2]
            hero.vel.y -= 900.0 * dt
            hero.move_by(0.0, hero.vel.y * dt)
            floor.move_by(0.0, floor.vel.y * dt)
            self.step()
            if "bottom" not in hero.touching_sides:
                misses += 1
        self.assertEqual(
            misses, 0,
            f"rising ride lost bottom on {misses}/60 short/long frames",
        )

    def test_jump_from_rising_platform_is_not_snapped(self):
        """Leave gate must still refuse to snap an active jump (speed + displacement)."""
        ox, oy = self.at(0, 0)
        floor = self.track(Rect(
            center=(ox, oy), width=200.0, height=24.0, group="plataforma",
        ))
        floor.mass = STATIC
        floor.vel = Vec2(0.0, 80.0)
        hero = self.track(Rect(
            center=(ox, oy + 12.0 + 35.0), width=38.0, height=70.0, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(0.0, 0.0)
        resolve("heroi", "plataforma", bounce=0.0)
        dt = 1.0 / 60.0
        for _ in range(8):
            hero.vel.y -= 900.0 * dt
            hero.move_by(0.0, hero.vel.y * dt)
            floor.move_by(0.0, floor.vel.y * dt)
            self.step()
        self.assertIn("bottom", hero.touching_sides)
        hero.vel.y += 460.0
        hero.vel.y -= 900.0 * dt
        hero.move_by(0.0, hero.vel.y * dt)
        floor.move_by(0.0, floor.vel.y * dt)
        self.step()
        self.assertNotIn("bottom", hero.touching_sides)
        self.assertGreater(float(hero.vel.y), float(floor.vel.y) + 50.0)

    def test_uphill_walk_short_frames_keep_grounded(self):
        """Climbing a ramp must not disable floor snap via tangential +vy.

        ``bounce=0`` keeps surface-tangent velocity, so uphill walk has large
        world ``+vy`` while resting. Leave is outward-normal speed *and*
        displacement — tangential climb must not look like a jump.
        """
        dt_pattern = (0.005, 0.028)
        ox, oy = self.at(880, 160)
        ang = 22.0
        rad = math.radians(ang)
        w, h = 200.0, 24.0
        slab = self.track(Rect(
            center=(ox, oy), width=w, height=h, angle=ang, group="plataforma",
        ))
        slab.mass = STATIC
        nx, ny = -math.sin(rad), math.cos(rad)
        px, py = ox + nx * h * 0.5, oy + ny * h * 0.5
        start_x = ox - 70.0
        surf = py + math.tan(rad) * (start_x - px)
        hero = self.track(Rect(
            center=(start_x, surf + 35.0 + 2.0), width=38.0, height=70.0, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(0.0, -80.0)
        resolve("heroi", "plataforma", bounce=0.0)
        # Warm onto the surface with stable frames first.
        for _ in range(8):
            dt = 1.0 / 60.0
            hero.vel.x = 250.0
            hero.vel.y -= 900.0 * dt
            hero.move_by(hero.vel.x * dt, hero.vel.y * dt)
            self.step()
        self.assertIn("bottom", hero.touching_sides)
        misses = 0
        x_end = ox + 60.0
        for i in range(40):
            dt = dt_pattern[i % 2]
            hero.vel.x = 250.0
            hero.vel.y -= 900.0 * dt
            hero.move_by(hero.vel.x * dt, hero.vel.y * dt)
            self.step()
            if "bottom" not in hero.touching_sides:
                misses += 1
            if float(hero.center.x) >= x_end:
                break
        self.assertEqual(
            misses, 0,
            f"uphill walk lost bottom on {misses} short/long frames",
        )
        self.assertGreater(float(hero.vel.y), 40.0)  # still climbing

    def test_jump_from_ramp_is_not_snapped(self):
        """Jumping off a slope must still clear the dual leave gate."""
        ox, oy = self.at(880, 160)
        ang = 22.0
        rad = math.radians(ang)
        w, h = 200.0, 24.0
        slab = self.track(Rect(
            center=(ox, oy), width=w, height=h, angle=ang, group="plataforma",
        ))
        slab.mass = STATIC
        nx, ny = -math.sin(rad), math.cos(rad)
        px, py = ox + nx * h * 0.5, oy + ny * h * 0.5
        start_x = ox - 40.0
        surf = py + math.tan(rad) * (start_x - px)
        hero = self.track(Rect(
            center=(start_x, surf + 35.0 + 2.0), width=38.0, height=70.0, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(0.0, -80.0)
        resolve("heroi", "plataforma", bounce=0.0)
        dt = 1.0 / 60.0
        for _ in range(10):
            hero.vel.x = 250.0
            hero.vel.y -= 900.0 * dt
            hero.move_by(hero.vel.x * dt, hero.vel.y * dt)
            self.step()
        self.assertIn("bottom", hero.touching_sides)
        hero.vel.y += 460.0
        hero.vel.y -= 900.0 * dt
        hero.move_by(hero.vel.x * dt, hero.vel.y * dt)
        self.step()
        self.assertNotIn("bottom", hero.touching_sides)
        self.assertGreater(float(hero.vel.y), 200.0)

    def test_floor_snap_leave_predicate_is_bounce_aware(self):
        """Walker needs displacement or leave_frac; elastic trusts leave_v."""
        # Resting: never refuse.
        self.assertFalse(_floor_snap_should_refuse(
            leave_v=0.0, leave_d=0.0, rel_motion_len=4.0, token=0.0,
        ))
        # Walker slope-walk miss: large leave_v, small leave_d, frac < 0.85.
        self.assertFalse(_floor_snap_should_refuse(
            leave_v=90.0, leave_d=1.5, rel_motion_len=4.2, token=0.0,
        ))
        self.assertFalse(_floor_snap_should_refuse(
            leave_v=90.0, leave_d=1.5, rel_motion_len=4.2, token=_RESOLVE_POSITION_ONLY,
        ))
        self.assertFalse(_floor_snap_should_refuse(
            leave_v=90.0, leave_d=1.5, rel_motion_len=4.2, token=0.2,
        ))
        # Walker 60 Hz jump: both speed and 2 DU.
        self.assertTrue(_floor_snap_should_refuse(
            leave_v=460.0, leave_d=7.7, rel_motion_len=7.7, token=0.0,
        ))
        # Walker high-FPS jump: leave_d under 2 DU, but motion is along n.
        self.assertTrue(_floor_snap_should_refuse(
            leave_v=460.0, leave_d=0.92, rel_motion_len=0.92, token=0.0,
        ))
        # 45° walk-miss frac ≈ 0.71 — still snap (below 0.85). High-FPS
        # numbers so leave_d stays under 2 DU.
        self.assertFalse(_floor_snap_should_refuse(
            leave_v=177.0, leave_d=0.355, rel_motion_len=0.5, token=0.0,
        ))
        # Elastic: leave_v is enough even when leave_d is tiny.
        self.assertTrue(_floor_snap_should_refuse(
            leave_v=200.0, leave_d=0.4, rel_motion_len=0.4, token=1.0,
        ))
        self.assertTrue(_floor_snap_should_refuse(
            leave_v=80.0, leave_d=0.16, rel_motion_len=0.4, token=0.7,
        ))
        # bounce=0.5 is still a walker (cut is > 0.5); same motion as a
        # slope-walk miss must snap. 0.51 is elastic and leaves on speed.
        self.assertFalse(_floor_snap_should_refuse(
            leave_v=200.0, leave_d=0.15, rel_motion_len=0.4, token=0.5,
        ))
        self.assertTrue(_floor_snap_should_refuse(
            leave_v=200.0, leave_d=0.15, rel_motion_len=0.4, token=0.51,
        ))
        # Elastic but not actually leaving.
        self.assertFalse(_floor_snap_should_refuse(
            leave_v=3.0, leave_d=0.01, rel_motion_len=0.01, token=1.0,
        ))

    def test_jump_from_floor_high_fps_is_not_snapped(self):
        """Walker leave_frac must refuse a real jump when leave_d is under 2 DU."""
        dt = 0.002
        ox, oy = self.at(0, 0)
        floor = self.track(Rect(
            center=(ox, oy), width=200.0, height=24.0, group="plataforma",
        ))
        floor.mass = STATIC
        hero = self.track(Rect(
            center=(ox, oy + 12.0 + 35.0), width=38.0, height=70.0, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(0.0, 0.0)
        resolve("heroi", "plataforma", bounce=0.0)
        settle_dt = 1.0 / 60.0
        for _ in range(8):
            hero.vel.y -= 900.0 * settle_dt
            hero.move_by(0.0, hero.vel.y * settle_dt)
            self.step()
        self.assertIn("bottom", hero.touching_sides)
        hero.vel.y = 460.0
        hero.move_by(0.0, hero.vel.y * dt)
        self.step()
        self.assertNotIn("bottom", hero.touching_sides)
        self.assertGreater(float(hero.vel.y), 400.0)

    def test_elastic_bounce_high_fps_does_not_stick_to_floor(self):
        """bounce=1 at 2 ms/frame must leave the floor; 2 DU leave_d would glue it."""
        dt = 0.002
        ox, oy = self.at(0, 0)
        floor_h = 24.0
        floor = self.track(Rect(
            center=(ox, oy), width=220.0, height=floor_h, group="floor",
        ))
        floor.mass = STATIC
        radius = 12.0
        floor_top = oy + floor_h * 0.5
        ball = self.track(Circle(
            center=(ox, floor_top + radius + 6.0),
            radius=radius, group="ball",
        ))
        ball.mass = 1.0
        ball.vel = Vec2(0.0, -200.0)
        resolve("ball", "floor", bounce=1.0)
        hit = False
        for _ in range(80):
            ball.move_by(0.0, ball.vel.y * dt)
            self.step()
            if "bottom" in ball.touching_sides and float(ball.vel.y) > 100.0:
                hit = True
                break
        self.assertTrue(hit, "never bounced off the floor")
        y_hit = float(ball.center.y)
        left = False
        for _ in range(20):
            ball.move_by(0.0, ball.vel.y * dt)
            self.step()
            if "bottom" not in ball.touching_sides:
                left = True
                break
        self.assertTrue(left, "elastic bounce snapped back onto the floor")
        self.assertGreater(float(ball.center.y), y_hit)
        self.assertGreater(float(ball.vel.y), 100.0)

    def test_glancing_elastic_bounce_does_not_stick_to_floor(self):
        """Glancing bounce=1 is a geometric alias of a 45° walk-miss; bounce wins."""
        dt = 0.002
        ox, oy = self.at(0, 0)
        floor_h = 24.0
        floor = self.track(Rect(
            center=(ox, oy), width=400.0, height=floor_h, group="floor",
        ))
        floor.mass = STATIC
        radius = 12.0
        floor_top = oy + floor_h * 0.5
        ball = self.track(Circle(
            center=(ox, floor_top + radius + 8.0),
            radius=radius, group="ball",
        ))
        ball.mass = 1.0
        ball.vel = Vec2(180.0, -80.0)
        resolve("ball", "floor", bounce=1.0)
        hit = False
        for _ in range(80):
            ball.move_by(ball.vel.x * dt, ball.vel.y * dt)
            self.step()
            if "bottom" in ball.touching_sides and float(ball.vel.y) > 20.0:
                hit = True
                break
        self.assertTrue(hit, "never bounced")
        left = False
        for _ in range(30):
            ball.move_by(ball.vel.x * dt, ball.vel.y * dt)
            self.step()
            if "bottom" not in ball.touching_sides:
                left = True
                break
        self.assertTrue(left, "glancing elastic bounce stuck on the floor")
        self.assertGreater(float(ball.vel.y), 20.0)

    def test_elastic_ball_does_not_snap_onto_other_ball(self):
        """Floor snap searches every resolve partner; bounce=1 must not glue stacks."""
        dt = 0.002
        ox, oy = self.at(0, 0)
        radius = 12.0
        lower = self.track(Circle(
            center=(ox, oy), radius=radius, group="ball",
        ))
        upper = self.track(Circle(
            center=(ox, oy + 2.0 * radius + 8.0), radius=radius, group="ball",
        ))
        lower.mass = 100.0
        upper.mass = 1.0
        lower.vel = Vec2(0.0, 0.0)
        upper.vel = Vec2(0.0, -200.0)
        resolve("ball", "ball", bounce=1.0)
        hit = False
        for _ in range(80):
            lower.move_by(lower.vel.x * dt, lower.vel.y * dt)
            upper.move_by(upper.vel.x * dt, upper.vel.y * dt)
            self.step()
            if "bottom" in upper.touching_sides and float(upper.vel.y) > 50.0:
                hit = True
                break
        self.assertTrue(hit, "upper ball never bounced off the lower")
        left = False
        for _ in range(30):
            lower.move_by(lower.vel.x * dt, lower.vel.y * dt)
            upper.move_by(upper.vel.x * dt, upper.vel.y * dt)
            self.step()
            if "bottom" not in upper.touching_sides:
                left = True
                break
        self.assertTrue(left, "upper ball snapped onto the lower after bounce")
        self.assertGreater(float(upper.vel.y), 50.0)

    def test_low_bounce_walker_short_frames_keep_grounded(self):
        """bounce=0.2 is still a walker; short frames must not drop bottom."""
        ox, oy = self.at(0, 0)
        floor = self.track(Rect(
            center=(ox, oy), width=400.0, height=24.0, group="plataforma",
        ))
        floor.mass = STATIC
        hero = self.track(Rect(
            center=(ox, oy + 12.0 + 35.0), width=38.0, height=70.0, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(0.0, 0.0)
        resolve("heroi", "plataforma", bounce=0.2)
        for _ in range(12):
            dt = 1.0 / 60.0
            hero.vel.y -= 900.0 * dt
            hero.move_by(hero.vel.x * dt, hero.vel.y * dt)
            self.step()
        self.assertIn("bottom", hero.touching_sides)
        pattern = (0.005, 0.028)
        misses = 0
        for i in range(40):
            dt = pattern[i % 2]
            hero.vel.x = 120.0
            hero.vel.y -= 900.0 * dt
            hero.move_by(hero.vel.x * dt, hero.vel.y * dt)
            self.step()
            if "bottom" not in hero.touching_sides:
                misses += 1
        self.assertEqual(
            misses, 0,
            f"bounce=0.2 walker lost bottom on {misses}/40 short/long frames",
        )

    def test_bounce_sweep_does_not_creep_through_walls(self):
        """Phase 7: bouncing against a STATIC wall stays in front at any restitution."""
        for i, bounce in enumerate((0.0, 0.5, 1.0, 1.2)):
            ox, oy = self.at(i * 400, 0)
            wall = self.track(Rect(
                center=(ox + 80, oy), width=20, height=120, group=f"wall{i}",
            ))
            wall.mass = STATIC
            ball = self.track(Circle(center=(ox, oy), radius=10, group=f"ball{i}"))
            ball.mass = 1.0
            ball.vel = Vec2(400.0, 0.0)
            resolve(f"ball{i}", f"wall{i}", bounce=bounce)
            wall_left = ox + 80 - 10
            for _ in range(40):
                ball.move_by(ball.vel.x * 0.016, ball.vel.y * 0.016)
                self.step()
            self.assertLess(
                float(ball.center.x) + 10.0, wall_left + 4.0,
                f"bounce={bounce} crept through the wall",
            )


class TestSpriteHitboxGrounding(CollisionTestCase):
    """Phase 4: frozen silhouette collider stays grounded; ``each`` still flickers."""

    def _walker(self, **kwargs):
        import tempfile
        from tests.test_sprite import _write_blob_strip

        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = os.path.join(td.name, "walk.png")
        _write_blob_strip(path, cell=32)
        kw = dict(
            center=self.at(0, 20), size=32,
            hitbox_shape="rect", group="hero",
        )
        kw.update(kwargs)
        return self.track(Sprite(Sheet(path, cols=4, fps=8), **kw))

    def _settle(self, hero):
        from scena import clock
        from scena.collision import _RESOLVE_SLOP, resolve

        clock.scale = 1.0
        clock.paused = False
        clock._dt = 0.0
        clock._time = 0.0
        clock._real_dt = 0.0
        clock._real_time = 0.0
        floor = self.track(Rect(
            center=self.at(0, -24), width=160, height=16, group="floor",
        ))
        floor.mass = STATIC
        hero.mass = 1.0
        hero.collidable = True
        floor.collidable = True
        resolve("hero", "floor", bounce=0.0)
        hero.vel = Vec2(0, -180)
        for _ in range(16):
            hero.move_by(0, hero.vel.y * 0.016)
            self.step()
        self.assertIn("bottom", hero.touching_sides)
        return clock, _RESOLVE_SLOP

    def test_frozen_recipe_stays_grounded_across_clip(self):
        hero = self._walker(
            hitbox_source="all", hitbox_anchor="bottom", hitbox_scale=(0.55, 1.0),
        )
        clock, slop = self._settle(hero)
        y0 = float(hero.center.y)
        for i in range(12):
            clock.advance(0.125)
            self.step()
            self.assertIn("bottom", hero.touching_sides, msg=f"tick {i} frame={hero.frame}")
        self.assertLess(abs(float(hero.center.y) - y0), slop)

    def test_each_center_still_flickers(self):
        hero = self._walker(hitbox_source="each", hitbox_anchor="center")
        clock, slop = self._settle(hero)
        y0 = float(hero.center.y)
        grounded = []
        ys = []
        for _ in range(12):
            clock.advance(0.125)
            self.step()
            grounded.append("bottom" in hero.touching_sides)
            ys.append(float(hero.center.y))
        lost_contact = not all(grounded)
        drifted = (max(ys) - min(ys)) >= slop
        self.assertTrue(
            lost_contact or drifted,
            f"each+center should flicker; grounded={grounded} ys={ys} slop={slop}",
        )

    def test_tilt_does_not_rotate_collider(self):
        """Visual tilt must not change the baked hitbox or grounding."""
        hero = self._walker(
            hitbox_source="all", hitbox_anchor="bottom", hitbox_scale=(0.55, 1.0),
        )
        self._settle(hero)
        y0 = float(hero.center.y)
        from scena.collision import _proxy_aabb_for_shape, _snapshot_shape_uncached
        proxy0 = _proxy_aabb_for_shape(hero)
        hero.tilt = 22.0
        self.assertAlmostEqual(hero.tilt, 22.0)
        self.step()
        self.assertIn("bottom", hero.touching_sides)
        self.assertLess(abs(float(hero.center.y) - y0), 1.0)
        proxy1 = _proxy_aabb_for_shape(hero)
        self.assertEqual(proxy0, proxy1)
        hero.reset_rotation()
        self.assertAlmostEqual(hero.tilt, 0.0)

    def test_touching_contact_exposes_point(self):
        floor = self.track(Rect(
            center=self.at(0, 0), width=200, height=20, group="plataforma",
        ))
        floor.mass = STATIC
        hero = self.track(Rect(
            center=self.at(0, 45), width=40, height=70, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(0, -80)
        resolve("heroi", "plataforma", bounce=0.0)
        for _ in range(6):
            hero.vel.y -= 900.0 * 0.016
            hero.move_by(0.0, hero.vel.y * 0.016)
            self.step()
        self.assertIn("bottom", hero.touching_sides)
        bottoms = [c for c in hero.touching_contacts if c.side == "bottom"]
        self.assertTrue(bottoms)
        pt = bottoms[0].point
        self.assertIsNotNone(pt)
        self.assertAlmostEqual(pt[0], float(hero.center.x), delta=25.0)
        self.assertAlmostEqual(pt[1], float(floor.center.y) + 10.0, delta=8.0)

    def test_ramp_contact_point_is_resting_corner(self):
        """Vertex-on-face synthesis must not average opposite ends of the ramp."""
        floor = self.track(Rect(
            center=self.at(0, -20), width=200, height=24, angle=22, group="plataforma",
        ))
        floor.mass = STATIC
        hero = self.track(Rect(
            center=self.at(0, 80), width=38, height=70, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(0, -300)
        resolve("heroi", "plataforma", bounce=0.0)
        for _ in range(40):
            hero.vel.y -= 900.0 * 0.016
            hero.move_by(0.0, hero.vel.y * 0.016)
            self.step()
        self.assertIn("bottom", hero.touching_sides)
        c = next(x for x in hero.touching_contacts if x.side == "bottom")
        self.assertIsNotNone(c.point)
        from scena.collision import snapshot_shape, _prims_support
        box = snapshot_shape(hero)[0].aabb
        support = _prims_support(snapshot_shape(hero), float(c.normal.x), float(c.normal.y))
        self.assertIsNotNone(support)
        # Must be near the resting corner — not averaged to the far end of the ramp
        # (~50–100 DU away). Settle manifolds can sit a couple DU off the vertex.
        self.assertAlmostEqual(c.point[0], support[0], delta=8.0)
        self.assertAlmostEqual(c.point[1], support[1], delta=8.0)
        mid_x = 0.5 * (box[0] + box[2])
        self.assertGreater(c.point[0], mid_x)


class TestMotionVsPlacement(CollisionTestCase):
    """Instant set is placement (no sweep); ``_by`` / ``time=`` is motion."""

    def test_center_assign_teleports_across_slab(self):
        """Reset via ``center =`` must land on the target, not stop mid-path."""
        ox, oy = self.at(0, 0)
        wall = self.track(Rect(
            center=(ox + 200, oy), width=40, height=240, group="walls",
        ))
        wall.mass = STATIC
        hero = self.track(Rect(
            center=(ox, oy), width=24, height=24, group="hero",
        ))
        hero.mass = 1.0
        resolve("hero", "walls")
        self.step()
        target = self.at(400, 0)
        hero.center = target
        self.step()
        self.assertAlmostEqual(float(hero.center.x), target[0], places=3)
        self.assertAlmostEqual(float(hero.center.y), target[1], places=3)

    def test_instant_move_to_teleports_across_slab(self):
        ox, oy = self.at(0, 0)
        wall = self.track(Rect(
            center=(ox + 200, oy), width=40, height=240, group="walls",
        ))
        wall.mass = STATIC
        hero = self.track(Rect(
            center=(ox, oy), width=24, height=24, group="hero",
        ))
        hero.mass = 1.0
        resolve("hero", "walls")
        self.step()
        tx, ty = self.at(400, 0)
        hero.move_to(tx, ty)
        self.step()
        self.assertAlmostEqual(float(hero.center.x), tx, places=3)
        self.assertAlmostEqual(float(hero.center.y), ty, places=3)

    def test_teleported_static_platform_does_not_drag_rider(self):
        """A ``center =`` elevator reports zero leftover; rider stays put."""
        ox, oy = self.at(0, 0)
        plat = self.track(Rect(
            center=(ox, oy), width=200, height=24, group="plataforma",
        ))
        plat.mass = STATIC
        hero = self.track(Rect(
            center=(ox, oy + 12.0 + 35.0), width=38, height=70, group="heroi",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(0.0, 0.0)
        plat.vel = Vec2(0.0, 0.0)
        resolve("heroi", "plataforma", bounce=0.0)
        self.step()
        self.assertIn("bottom", hero.touching_sides)
        hero_x = float(hero.center.x)
        hero_y = float(hero.center.y)
        plat.center = (ox + 400.0, oy)
        self.step()
        self.assertAlmostEqual(float(hero.center.x), hero_x, delta=2.0)
        self.assertAlmostEqual(float(hero.center.y), hero_y, delta=2.0)

    def test_move_by_still_sweeps_into_wall(self):
        ox, oy = self.at(0, 0)
        wall = self.track(Rect(
            center=(ox + 80, oy), width=20, height=80, group="walls",
        ))
        wall.mass = STATIC
        hero = self.track(Rect(
            center=(ox, oy), width=20, height=20, group="hero",
        ))
        hero.mass = 1.0
        resolve("hero", "walls")
        self.step()
        hero.move_by(200.0, 0.0)
        self.step()
        # Half-widths 10+10, slop ~0.08 — stop near the wall face, not past it.
        self.assertLess(float(hero.center.x), ox + 80.0)
        self.assertGreater(float(hero.center.x), ox + 40.0)

    def test_timed_move_to_stops_at_wall(self):
        from scena import clock
        from scena.process import reset_process_scheduler, tick_processes

        reset_process_scheduler()
        clock.scale = 1.0
        clock.paused = False
        clock._dt = 0.0
        clock._time = 0.0
        try:
            ox, oy = self.at(0, 0)
            wall = self.track(Rect(
                center=(ox + 200, oy), width=20, height=120, group="walls",
            ))
            wall.mass = STATIC
            hero = self.track(Rect(
                center=(ox, oy), width=20, height=20, group="hero",
            ))
            hero.mass = 1.0
            resolve("hero", "walls")
            self.step()
            hero.move_to(ox + 400.0, oy, time=1.0)
            dt = 1.0 / 60.0
            for _ in range(70):
                clock.advance(dt)
                tick_processes()
                self.step()
            self.assertLess(float(hero.center.x), ox + 200.0)
            self.assertGreater(float(hero.center.x), ox + 150.0)
        finally:
            reset_process_scheduler()

    def test_timed_move_to_arrives_in_clear_space(self):
        from scena import clock
        from scena.process import reset_process_scheduler, tick_processes

        reset_process_scheduler()
        clock.scale = 1.0
        clock.paused = False
        clock._dt = 0.0
        clock._time = 0.0
        try:
            ox, oy = self.at(0, 0)
            hero = self.track(Rect(
                center=(ox, oy), width=20, height=20, group="hero",
            ))
            hero.mass = 1.0
            dummy = self.track(Rect(
                center=(ox + 800, oy + 800), width=10, height=10, group="walls",
            ))
            dummy.mass = STATIC
            resolve("hero", "walls")
            tx, ty = ox + 120.0, oy + 40.0
            hero.move_to(tx, ty, time=0.25)
            dt = 1.0 / 60.0
            for _ in range(30):
                clock.advance(dt)
                tick_processes()
                self.step()
            self.assertAlmostEqual(float(hero.center.x), tx, places=2)
            self.assertAlmostEqual(float(hero.center.y), ty, places=2)
        finally:
            reset_process_scheduler()

    def test_instant_rotate_to_does_not_invent_translation(self):
        ox, oy = self.at(0, 0)
        wall = self.track(Rect(
            center=(ox + 400, oy), width=20, height=80, group="walls",
        ))
        wall.mass = STATIC
        hero = self.track(Rect(
            center=(ox, oy), width=40, height=20, group="hero",
        ))
        hero.mass = 1.0
        resolve("hero", "walls")
        self.step()
        hero.rotate_to(90)
        col = hero._collider
        get_collision_system()._update_proxy(col)
        self.assertEqual(col._motion_dx, 0.0)
        self.assertEqual(col._motion_dy, 0.0)
        self.assertAlmostEqual(float(hero.center.x), ox, places=3)
        self.assertAlmostEqual(float(hero.center.y), oy, places=3)

    def test_instant_scale_to_does_not_invent_translation(self):
        ox, oy = self.at(0, 0)
        wall = self.track(Rect(
            center=(ox + 400, oy), width=20, height=80, group="walls",
        ))
        wall.mass = STATIC
        hero = self.track(Rect(
            center=(ox, oy), width=40, height=20, group="hero",
        ))
        hero.mass = 1.0
        resolve("hero", "walls")
        self.step()
        hero.scale_to(2.0)
        col = hero._collider
        get_collision_system()._update_proxy(col)
        self.assertEqual(col._motion_dx, 0.0)
        self.assertEqual(col._motion_dy, 0.0)
        self.assertAlmostEqual(float(hero.center.x), ox, places=3)
        self.assertAlmostEqual(float(hero.center.y), oy, places=3)

    def test_move_by_marks_motion_delta(self):
        hero = self.track(Rect(
            center=self.at(0, 0), width=20, height=20, group="hero",
        ))
        wall = self.track(Rect(
            center=self.at(400, 0), width=20, height=20, group="walls",
        ))
        wall.mass = STATIC
        resolve("hero", "walls")
        self.step()
        hero.move_by(12.0, -5.0)
        col = hero._collider
        get_collision_system()._update_proxy(col)
        self.assertAlmostEqual(col._motion_dx, 12.0, places=5)
        self.assertAlmostEqual(col._motion_dy, -5.0, places=5)

    def test_tween_center_is_placement(self):
        from scena import clock, tween
        from scena.process import reset_process_scheduler, tick_processes

        reset_process_scheduler()
        clock.scale = 1.0
        clock.paused = False
        clock._dt = 0.0
        clock._time = 0.0
        try:
            ox, oy = self.at(0, 0)
            wall = self.track(Rect(
                center=(ox + 200, oy), width=40, height=240, group="walls",
            ))
            wall.mass = STATIC
            hero = self.track(Rect(
                center=(ox, oy), width=24, height=24, group="hero",
            ))
            hero.mass = 1.0
            resolve("hero", "walls")
            self.step()
            tween(hero.center, (ox + 400.0, oy), time=0.2)
            dt = 1.0 / 60.0
            for _ in range(20):
                clock.advance(dt)
                tick_processes()
                self.step()
            self.assertAlmostEqual(float(hero.center.x), ox + 400.0, places=2)
            self.assertAlmostEqual(float(hero.center.y), oy, places=2)
        finally:
            reset_process_scheduler()

    def test_tween_center_start_is_placement(self):
        """start= on a pose tween still writes via takein — no swept stop at the wall."""
        from scena import clock, tween
        from scena.process import reset_process_scheduler, tick_processes

        reset_process_scheduler()
        clock.scale = 1.0
        clock.paused = False
        clock._dt = 0.0
        clock._time = 0.0
        try:
            ox, oy = self.at(0, 0)
            wall = self.track(Rect(
                center=(ox + 200, oy), width=40, height=240, group="walls",
            ))
            wall.mass = STATIC
            hero = self.track(Rect(
                center=(ox, oy), width=24, height=24, group="hero",
            ))
            hero.mass = 1.0
            resolve("hero", "walls")
            self.step()
            # start= jumps the range across the wall; placement must still land past it.
            tween(
                hero.center,
                (ox + 400.0, oy),
                time=0.2,
                start=(ox - 50.0, oy),
            )
            dt = 1.0 / 60.0
            for _ in range(20):
                clock.advance(dt)
                tick_processes()
                self.step()
            self.assertAlmostEqual(float(hero.center.x), ox + 400.0, places=2)
            self.assertAlmostEqual(float(hero.center.y), oy, places=2)
        finally:
            reset_process_scheduler()

    def test_resolve_enabled_false_skips_push_keeps_detect(self):
        a = self.track(Circle(center=self.at(0, 0), radius=20, group="a"))
        b = self.track(Circle(center=self.at(25, 0), radius=20, group="b"))
        hits = []

        @collide("a", "b")
        def on_hit(me, other, info):
            hits.append((me, other))

        resolve("a", "b")
        ax, ay = float(a.center.x), float(a.center.y)
        bx, by = float(b.center.x), float(b.center.y)
        collision.resolve_enabled = False
        self.step()
        self.assertEqual(len(hits), 1)
        self.assertAlmostEqual(float(a.center.x), ax, places=5)
        self.assertAlmostEqual(float(a.center.y), ay, places=5)
        self.assertAlmostEqual(float(b.center.x), bx, places=5)
        self.assertAlmostEqual(float(b.center.y), by, places=5)
        self.assertEqual(a.touching_sides, frozenset())
        collision.resolve_enabled = True
        self.step()
        dist = math.hypot(float(b.center.x) - float(a.center.x),
                          float(b.center.y) - float(a.center.y))
        self.assertGreaterEqual(dist, 39.0)


class TestSilhouetteHurtbox(CollisionTestCase):
    def test_track_hurtbox_detects_while_walker_rect_resolves(self):
        import os
        import tempfile

        from tests.test_sprite import _write_rect_png

        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = os.path.join(td.name, "hero.png")
        _write_rect_png(path, 32, 48)
        hero = self.track(Sprite(
            path, center=self.at(0, 40), width=32, height=48,
            hitbox_shape="rect", hitbox_anchor="bottom", group="hero",
        ))
        hero.mass = 1.0
        hero.collidable = True
        floor = self.track(Rect(
            center=self.at(0, 0), width=220, height=16, group="floor",
        ))
        floor.mass = STATIC
        floor.collidable = True
        resolve("hero", "floor", bounce=0.0)
        hero.vel = Vec2(0, -240)
        for _ in range(24):
            hero.move_by(0, float(hero.vel.y) * 0.016)
            self.step()
        self.assertIn("bottom", hero.touching_sides)
        rect_fp = hero._collision_specs()

        hurt = self.track(Track(hero))
        self.assertFalse(hurt.collidable)
        hurt.collidable = True
        hurt.add_to_group("hurtbox")
        hits = []

        @collide("hurtbox", "sting")
        def _on_hit(a, b, info):
            hits.append(type(a).__name__)

        hurt._ensure_samples()
        px, py = hurt.at(0.0)
        sting = self.track(Circle(center=(px, py), radius=8, group="sting"))
        sting.collidable = True
        self.step()
        self.assertTrue(hits)
        self.assertIn("bottom", hero.touching_sides)
        self.assertEqual(hero._collision_specs(), rect_fp)


def _ellipse_prim(cx, cy, rx, ry, ang=0.0):
    return Prim(
        PrimKind.ELLIPSE,
        (cx - rx, cy - ry, cx + rx, cy + ry),
        (cx, cy, rx, ry, ang),
    )


def _circle_prim(cx, cy, r):
    return Prim(PrimKind.CIRCLE, (cx - r, cy - r, cx + r, cy + r), (cx, cy, r))


class TestReviewedCollisionFixes(CollisionTestCase):
    def test_queries_do_not_consume_the_sweep(self):
        """move_by then a query must still sweep on the next step."""
        wall = self.track(Rect(
            center=self.at(80, 0), width=4, height=120, group="wall",
        ))
        wall.mass = STATIC
        wall.collidable = True
        bullet = self.track(Circle(
            center=self.at(0, 0), radius=8, group="bullet",
        ))
        bullet.mass = 1.0
        bullet.vel = Vec2(400.0, 0.0)
        bullet.collidable = True
        resolve("bullet", "wall", bounce=0.0)
        bullet.move_by(200.0, 0.0)
        probe = self.track(Circle(center=self.at(0, 400), radius=6))
        collision.query_shape(probe)
        collision.query_point(*self.at(0, 0))
        collision.raycast(self.at(-20, 0), p2=self.at(20, 0))
        self.step()
        # Thin wall's left face is at origin+78; the bullet must stop, not tunnel.
        self.assertLess(float(bullet.center.x), self.origin + 78.0)

        floor = self.track(Rect(
            center=self.at(400, -40), width=200, height=20, group="floor",
        ))
        floor.mass = STATIC
        floor.vel = Vec2(0.0, 0.0)
        floor.collidable = True
        hero = self.track(Circle(
            center=self.at(400, 0), radius=15, group="hero",
        ))
        hero.mass = 1.0
        hero.collidable = True
        resolve("hero", "floor", bounce=0.0)
        hero.vel = Vec2(0.0, -200.0)
        for _ in range(8):
            hero.move_by(0.0, hero.vel.y / 60.0)
            self.step()
        self.assertIn("bottom", hero.touching_sides)
        y_ground = float(hero.center.y)
        hero.vel = Vec2(0.0, 360.0)
        hero.move_by(0.0, hero.vel.y / 60.0)
        collision.query_shape(probe)
        collision.query_point(*self.at(400, 0))
        collision.raycast(self.at(380, 40), p2=self.at(420, 40))
        self.step()
        self.assertGreater(float(hero.center.y), y_ground + 2.0)

    def test_walk_speed_holds_and_idle_slope_does_not_creep(self):
        dt = 1.0 / 60.0
        ox, oy = self.at(0, 0)
        ang = 22.0
        rad = math.radians(ang)
        slab = self.track(Rect(
            center=(ox, oy), width=400.0, height=24.0, angle=ang, group="floor",
        ))
        slab.mass = STATIC
        nx, ny = -math.sin(rad), math.cos(rad)
        px = ox + nx * 12.0
        py = oy + ny * 12.0
        start_x = ox
        surf = py + math.tan(rad) * (start_x - px)
        hero = self.track(Rect(
            center=(start_x, surf + 35.0 + 1.0), width=28.0, height=48.0, group="hero",
        ))
        hero.mass = 1.0
        hero.vel = Vec2(0.0, -80.0)
        resolve("hero", "floor", bounce=0.0)
        for _ in range(10):
            hero.vel.y -= 900.0 * dt
            hero.move_by(0.0, hero.vel.y * dt)
            self.step()
        self.assertIn("bottom", hero.touching_sides)
        x0 = float(hero.center.x)
        for _ in range(30):
            hero.vel.x = 80.0
            hero.vel.y -= 900.0 * dt
            hero.move_by(hero.vel.x * dt, hero.vel.y * dt)
            self.step()
        dx = float(hero.center.x) - x0
        self.assertGreater(dx, 25.0)
        self.assertLess(abs(dx - 80.0 * dt * 30.0), 15.0)
        self.assertGreater(abs(float(hero.vel.x)), 50.0)

        idle = self.track(Rect(
            center=(ox + 40.0, surf + math.tan(rad) * 40.0 + 36.0),
            width=28.0, height=48.0, group="idle",
        ))
        idle.mass = 1.0
        idle.vel = Vec2(0.0, -40.0)
        resolve("idle", "floor", bounce=0.0)
        for _ in range(12):
            idle.vel.y -= 900.0 * dt
            idle.move_by(0.0, idle.vel.y * dt)
            self.step()
        self.assertIn("bottom", idle.touching_sides)
        ix = float(idle.center.x)
        for _ in range(40):
            idle.vel.x = 0.0
            idle.vel.y -= 900.0 * dt
            idle.move_by(0.0, idle.vel.y * dt)
            self.step()
        self.assertLess(abs(float(idle.center.x) - ix), 3.0)
        self.assertLess(abs(float(idle.vel.x)), 40.0)

    def test_inside_aabb_normal_is_outward(self):
        # Centre just inside the left face: normal from circle toward the box is +x.
        contact = _circle_aabb((1.0, 5.0, 2.0), (0.0, 0.0, 10.0, 10.0))
        self.assertIsNotNone(contact)
        self.assertAlmostEqual(contact.normal[0], 1.0)
        self.assertAlmostEqual(contact.normal[1], 0.0)
        self.assertAlmostEqual(contact.depth, 3.0)
        toi = _circle_aabb_toi(1.0, 5.0, 2.0, (0.0, 0.0, 10.0, 10.0), 4.0, 0.0)
        self.assertIsNotNone(toi)
        self.assertAlmostEqual(toi[0], 0.0)
        self.assertAlmostEqual(toi[1], 1.0)
        self.assertAlmostEqual(toi[2], 0.0)

    def test_containment_depth_is_the_exit_not_the_width(self):
        # 2-wide box sunk 10 DU into a taller slab. Exit is vertical, depth 10.
        contact = _aabb_aabb((0.0, -10.0, 2.0, 10.0), (-20.0, 0.0, 20.0, 100.0))
        self.assertIsNotNone(contact)
        self.assertAlmostEqual(contact.normal[0], 0.0)
        self.assertAlmostEqual(abs(contact.normal[1]), 1.0)
        self.assertAlmostEqual(contact.depth, 10.0)

    def test_circle_aabb_corner_toi_is_round(self):
        box = (0.0, 0.0, 20.0, 20.0)
        # Closest approach is 12 DU from the corner; radius 10 must miss,
        # including a segment that clips the expanded corner square.
        self.assertIsNone(_circle_aabb_toi(-30.0, -12.0, 10.0, box, 60.0, 0.0))
        self.assertIsNone(_circle_aabb_toi(-20.0, -9.0, 10.0, box, 12.0, 0.0))
        graze = _circle_aabb_toi(-20.0, -6.0, 10.0, box, 40.0, 0.0)
        self.assertIsNotNone(graze)
        self.assertGreater(graze[0], 0.0)
        self.assertLess(graze[0], 1.0)

    def test_ellipse_gap_is_not_a_contact(self):
        gap = narrow_phase(
            _ellipse_prim(0.0, 0.0, 8.0, 5.0),
            _ellipse_prim(11.0, 10.0, 8.0, 5.0),
        )
        self.assertIsNone(gap)
        tip = narrow_phase(
            _ellipse_prim(0.0, 0.0, 20.0, 2.0),
            _circle_prim(20.5, 3.5, 2.0),
        )
        self.assertIsNone(tip)
        hit = narrow_phase(
            _ellipse_prim(0.0, 0.0, 4.0, 10.0),
            _ellipse_prim(6.0, 0.0, 4.0, 10.0),
        )
        self.assertIsNotNone(hit)
        self.assertGreater(hit.normal[0], 0.5)
        self.assertAlmostEqual(hit.depth, 2.0, delta=0.1)
        nx, ny = hit.normal
        shifted = narrow_phase(
            _ellipse_prim(-nx * (hit.depth + 0.05), -ny * (hit.depth + 0.05), 4.0, 10.0),
            _ellipse_prim(6.0, 0.0, 4.0, 10.0),
        )
        self.assertIsNone(shifted)

    def test_raycast_group_ignore_and_inside_start(self):
        wall = self.track(Rect(
            center=self.at(0, 0), width=6, height=80, angle=25, group="walls",
        ))
        wall.collidable = True
        caster = self.track(Circle(
            center=self.at(-320, 0), radius=8, group="caster",
        ))
        caster.collidable = True

        @collide("caster", "walls")
        def _watch(_a, _b, _info):
            pass

        p1 = self.at(-320, 0)
        p2 = self.at(320, 0)
        hit = collision.raycast(p1, p2=p2, group="walls", ignore=caster)
        self.assertIsNotNone(hit)
        self.assertIs(hit[0], wall)
        self.assertGreater(hit[1], 0.0)
        self.assertLess(hit[1], 1.0)
        # A positional end is a point-like, so it is not a direction or a group.
        with self.assertRaises(TypeError) as caught:
            collision.raycast(p1, p2, "walls")
        self.assertIn("p2=", str(caught.exception))

        inside = self.track(Circle(center=self.at(0, 200), radius=15))
        inside.collidable = True
        started = collision.raycast(self.at(0, 200), p2=self.at(40, 200))
        self.assertIsNotNone(started)
        self.assertIs(started[0], inside)
        self.assertEqual(started[1], 0.0)
        skipped = collision.raycast(
            self.at(0, 200), p2=self.at(40, 200), ignore=inside,
        )
        self.assertIsNone(skipped)

    def test_forty_five_degree_normal_is_a_floor(self):
        self.assertEqual(_side_from_normal(1.0, -1.0), "bottom")
        self.assertEqual(_side_from_normal(-1.0, 1.0), "top")
        self.assertEqual(_side_from_normal(1.0, 0.0), "right")

    def test_missing_vel_floor_is_immovable(self):
        floor = self.track(Rect(
            center=self.at(0, -20), width=120, height=20, group="floor",
        ))
        floor.mass = 1.0
        floor.collidable = True
        self.assertIsNone(floor._vel)
        ball = self.track(Circle(
            center=self.at(0, 0), radius=12, group="ball",
        ))
        ball.mass = 1.0
        ball.collidable = True
        ball.vel = Vec2(0.0, -100.0)
        resolve("ball", "floor", bounce=1.0)
        self.step()
        self.assertGreater(float(ball.vel.y), 70.0)
        self.assertIsNone(floor._vel)

    def test_destroy_in_enter_fires_exit_same_frame(self):
        hero = self.track(Circle(center=self.at(0, 0), radius=16, group="hero"))
        coin = self.track(Circle(center=self.at(8, 0), radius=8, group="coin"))
        log = []

        @collide(hero, coin)
        def _pick(_me, other, _info):
            log.append("enter")
            other.destroy()

        @collide_exit(hero, coin)
        def _gone(me, _other, _info):
            log.append(("exit", me))

        self.step()
        self.assertEqual(log[0], "enter")
        self.assertIn(("exit", hero), log)  # survivor told in the same frame
        n = len(log)
        self.step()
        self.assertEqual(len(log), n)  # no second enter / exit

    def test_raising_enter_commits_contacts(self):
        a = self.track(Circle(center=self.at(0, 0), radius=16, group="a"))
        b = self.track(Circle(center=self.at(8, 0), radius=16, group="b"))
        enters = []

        @collide(a, b)
        def _enter(_me, _other, _info):
            enters.append(1)
            if len(enters) == 1:
                raise RuntimeError("enter bug")

        with self.assertRaisesRegex(RuntimeError, "enter bug"):
            self.step()
        self.step()  # still touching: stay, not a second enter
        self.assertEqual(enters, [1])

    def test_collidable_false_fires_exit_and_drops_keys(self):
        a = self.track(Circle(center=self.at(0, 0), radius=16, group="a"))
        b = self.track(Circle(center=self.at(8, 0), radius=16, group="b"))
        exits = []

        @collide(a, b)
        def _enter(_me, _other, _info):
            pass

        @collide_exit(a, b)
        def _leave(me, _other, _info):
            exits.append(me)

        self.step()
        col_id = id(b._collider)
        b.collidable = False
        self.assertIn(a, exits)  # survivor told immediately
        cs = get_collision_system()
        self.assertFalse(any(col_id in key for key in cs._prev_contacts))
        n = len(exits)
        self.step()
        self.assertEqual(len(exits), n)

    def test_exit_handler_error_on_destroy_propagates_after_teardown(self):
        hero = self.track(Circle(center=self.at(0, 0), radius=16, group="hero"))
        foe = self.track(Circle(center=self.at(8, 0), radius=16, group="foe"))

        @collide(hero, foe)
        def _enter(_me, _other, _info):
            pass

        @collide_exit(hero, foe)
        def _leave(_me, _other, _info):
            raise RuntimeError("exit bug")

        self.step()
        with self.assertRaisesRegex(RuntimeError, "exit bug"):
            foe.destroy()
        self.assertFalse(foe.is_alive)
        self.assertIsNone(getattr(foe, "_collider", None))
        self.step()  # no stale collider / no second exit

    def test_bullet_destroy_skips_second_enemy_and_exit_reaches_survivor(self):
        hero = self.track(Circle(center=self.at(0, 0), radius=16, group="hero"))
        foe = self.track(Circle(center=self.at(8, 0), radius=16, group="foe"))
        exits = []

        @collide(hero, foe)
        def _enter(_me, _other, _info):
            pass

        @collide_exit(hero, foe)
        def _leave(me, _other, _info):
            exits.append(me)

        self.step()
        foe.destroy()
        self.assertIn(hero, exits)

        reset_collision_system()
        bullet = self.track(Circle(center=self.at(0, 300), radius=14, group="bullet"))
        e1 = self.track(Circle(center=self.at(6, 300), radius=14, group="enemy"))
        e2 = self.track(Circle(center=self.at(6, 308), radius=14, group="enemy"))
        damaged = []

        @collide("bullet", "enemy")
        def _hit(me, other, _info):
            if me is not bullet:
                return
            damaged.append(other)
            bullet.destroy()

        self.step()
        self.assertEqual(len(damaged), 1)

    def test_unresolve_order_and_bounce_validation(self):
        resolve("floor", "ball")
        unresolve("ball", "floor")
        with self.assertWarns(RuntimeWarning):
            unresolve("ball", "floor")
        built = "ene" + "my"
        resolve("hero", built)
        unresolve("hero", "enemy")
        with self.assertWarns(RuntimeWarning):
            unresolve("hero", "enemy")
        with self.assertRaises(ValueError):
            resolve("a", "b", bounce=-1)
        with self.assertRaises(ValueError):
            resolve("a", "b", bounce=float("nan"))

    def test_query_shape_does_not_enroll_a_probe(self):
        target = self.track(Circle(center=self.at(0, 0), radius=12, group="enemy"))
        target.collidable = True

        @collide("enemy", "marker")
        def _watch(_a, _b, _info):
            pass

        probe = self.track(Circle(center=self.at(2, 0), radius=12))
        self.assertFalse(probe.collidable)
        collision.query_shape(probe, group="enemy")
        system = get_collision_system()
        self.assertIsNone(getattr(probe, "_collider", None))
        self.assertFalse(any(probe in c.shapes for c in system._colliders))

    def test_idle_body_is_not_left_past_a_fast_floor(self):
        body = self.track(Circle(center=self.at(0, 0), radius=10, group="body"))
        body.mass = 1.0
        body.vel = Vec2(0.0, 0.0)
        body.collidable = True
        plat = self.track(Rect(
            center=self.at(0, -16), width=160, height=4, group="floor",
        ))
        plat.mass = STATIC
        plat.vel = Vec2(0.0, 400.0)
        plat.collidable = True
        resolve("body", "floor", bounce=0.0)
        plat.move_by(0.0, 40.0)
        self.step()
        self.assertGreater(float(body.center.y), float(plat.center.y))


class TestNamedGroupQueries(CollisionTestCase):
    """``group=`` tests the named members. It does not enroll them."""

    def _ids(self, hits):
        return {id(h) for h in hits}

    def _bundle(self, probe, group, x, y):
        ray = collision.raycast((x - 400, y), p2=(x + 400, y), group=group)
        return (
            self._ids(probe.collides_with(group=group)),
            self._ids(collision.query_shape(probe, group=group)),
            self._ids(collision.query_point(x, y, group=group)),
            self._ids(collision.query_circle(x, y, radius=8, group=group)),
            None if ray is None else id(ray[0]),
        )

    def test_undeclared_tag_is_visible_enrolled_or_not(self):
        probe = self.track(Circle(center=self.at(0, 0), radius=40))
        loose = self.track(Circle(center=self.at(10, 0), radius=12, group="enemy"))
        # Off the horizontal ray through ``loose``, still inside the probe.
        enrolled = self.track(Circle(center=self.at(-10, 30), radius=12, group="enemy"))
        enrolled.collidable = True
        far = self.track(Circle(center=self.at(0, 400), radius=12, group="enemy"))
        x, y = self.at(10, 0)
        hits = self._bundle(probe, "enemy", x, y)
        both = {id(loose), id(enrolled)}
        self.assertEqual(hits[0], both)
        self.assertEqual(hits[1], both)
        self.assertEqual(hits[2], {id(loose)})
        self.assertEqual(hits[3], {id(loose)})
        self.assertEqual(hits[4], id(loose))
        self.assertNotIn(id(far), hits[0])
        self.assertFalse(loose.collidable)

    def test_declaration_does_not_change_named_hits(self):
        probe = self.track(Circle(center=self.at(0, 0), radius=40))
        enemy = self.track(Circle(center=self.at(8, 0), radius=12, group="enemy"))
        x, y = self.at(8, 0)
        before = self._bundle(probe, "enemy", x, y)
        resolve(probe, "enemy")
        self.assertEqual(self._bundle(probe, "enemy", x, y), before)
        unresolve(probe, "enemy")

        @collide(probe, "enemy")
        def _hit(_me, _other, _info):
            pass

        self.assertEqual(self._bundle(probe, "enemy", x, y), before)
        self.assertIn(id(enemy), before[0])

    def test_list_tuple_set_and_frozenset_are_the_same_or(self):
        probe = self.track(Circle(center=self.at(0, 0), radius=80))
        foe = self.track(Circle(center=self.at(10, 0), radius=8, group="enemies"))
        boss = self.track(Circle(center=self.at(-10, 0), radius=8, group="bosses"))
        neutral = self.track(Circle(center=self.at(5, 0), radius=8, group="neutral"))
        want = {id(foe), id(boss)}
        for group in (
            ["enemies", "bosses"],
            ("enemies", "bosses"),
            {"enemies", "bosses"},
            frozenset({"enemies", "bosses"}),
        ):
            got = self._ids(collision.query_shape(probe, group=group))
            self.assertEqual(got, want, group)
            self.assertNotIn(id(neutral), got)

    def test_named_query_has_no_side_effects(self):
        probe = self.track(Circle(center=self.at(0, 0), radius=30))
        enemy = self.track(Circle(center=self.at(6, 0), radius=12, group="enemy"))
        fired = []
        watcher = self.track(Circle(center=self.at(6, 0), radius=12))
        watcher.on_collide = lambda *args: fired.append(args)
        system = get_collision_system()
        n_colliders = len(system._colliders)
        tags = set(system._pair_tags)
        x, y = self.at(6, 0)
        self._bundle(probe, "enemy", x, y)
        collision.query_circle(x, y, radius=20, group={"enemy"})
        self.assertEqual(len(system._colliders), n_colliders)
        self.assertEqual(system._pair_tags, tags)
        self.assertFalse(enemy.collidable)
        self.assertIsNone(enemy._collider)
        self.step()
        self.assertEqual(fired, [])

    def test_opt_outs_ui_and_bare_entity_are_skipped(self):
        from scena import Entity
        probe = self.track(Circle(center=self.at(0, 0), radius=40))
        live = self.track(Circle(center=self.at(4, 0), radius=10, group="enemy"))
        opted = self.track(Circle(center=self.at(4, 0), radius=10, group="enemy"))
        opted.collidable = True
        opted.collidable = False
        parked = self.track(Circle(center=self.at(4, 0), radius=10, group="enemy"))
        parked.active = False
        dead = self.track(Circle(center=self.at(4, 0), radius=10, group="enemy"))
        dead.destroy()
        hud = self.track(Circle(
            center=self.at(4, 0), radius=10, group="enemy", layer="ui",
        ))
        self.track(Entity(group="enemy"))
        hits = collision.query_shape(probe, group="enemy")
        self.assertEqual(hits, [live])
        self.assertNotIn(hud, hits)

    def test_hitbox_part_answers_for_its_tag(self):
        # Body is wide (scale 3). The hurt part is a thin rect. A point on the
        # wing hits the body tag and misses the part tag.
        ship = self.track(Sprite(
            center=self.at(0, 0), size=64, hitbox_shape="rect",
            hitbox_scale=(3.0, 1.0), group="ships",
        ))
        part = ship.add_hitbox(group="hurt", shape="rect", scale=(0.2, 1.0))
        wing = self.track(Circle(center=self.at(40, 0), radius=4))
        core = self.track(Circle(center=self.at(0, 0), radius=4))
        self.assertEqual(wing.collides_with(group="ships"), [ship])
        self.assertEqual(wing.collides_with(group="hurt"), [])
        self.assertEqual(core.collides_with(group="hurt"), [ship])
        self.assertEqual(ship.collides_with(group="hurt"), [])
        part.active = False
        self.assertEqual(core.collides_with(group="hurt"), [])
        self.assertFalse(ship.collidable)

    def test_formula_group_is_queried_by_name(self):
        from scena import group
        a = self.track(Circle(center=self.at(6, 0), radius=8, group="alpha"))
        b = self.track(Circle(center=self.at(-6, 0), radius=8, group="beta"))
        other = self.track(Circle(center=self.at(0, 0), radius=8, group="gamma"))
        probe = self.track(Circle(center=self.at(0, 0), radius=30))
        group["foes"] @= lambda: group["alpha"] | group["beta"]
        try:
            hits = self._ids(probe.collides_with(group="foes"))
            self.assertEqual(hits, {id(a), id(b)})
            self.assertNotIn(id(other), hits)
            self.assertFalse(a.collidable)
        finally:
            group["foes"].unlink()

    def test_unnamed_query_stays_the_enrolled_world(self):
        probe = self.track(Circle(center=self.at(0, 0), radius=20))
        probe.collidable = True
        loose = self.track(Circle(center=self.at(0, 0), radius=10, group="enemy"))
        enrolled = self.track(Circle(center=self.at(0, 0), radius=10))
        enrolled.collidable = True
        x, y = self.at(0, 0)
        world = self._ids(collision.query_point(x, y))
        self.assertEqual(world, {id(probe), id(enrolled)})
        self.assertNotIn(id(loose), world)
        self.assertEqual(self._ids(collision.query_point(x, y, group=ANYTHING)), world)
        self.assertEqual(
            self._ids(collision.query_circle(x, y, radius=5)),
            world,
        )
        self.assertIn(id(loose), self._ids(collision.query_point(x, y, group="enemy")))

    def test_group_grammar_errors_are_scena_messages(self):
        probe = self.track(Circle(center=self.at(0, 0), radius=8))
        x, y = self.at(0, 0)
        calls = (
            lambda g: collision.query_shape(probe, group=g),
            lambda g: probe.collides_with(group=g),
            lambda g: collision.query_point(x, y, group=g),
            lambda g: collision.query_circle(x, y, radius=4, group=g),
            lambda g: collision.raycast((x - 10, y), p2=(x + 10, y), group=g),
        )
        for call in calls:
            for bad in (3, {"a": 1}, True):
                with self.assertRaises(TypeError) as cm:
                    call(bad)
                self.assertIn("group=", str(cm.exception))
                self.assertNotIn("unhashable", str(cm.exception))
            with self.assertRaises(ValueError) as cm:
                call("")
            self.assertIn("group=", str(cm.exception))
            self.assertEqual(call([]), [] if call != calls[-1] else None)

    def test_named_query_does_not_consume_pending_motion(self):
        enemy = self.track(Circle(center=self.at(0, 0), radius=12, group="enemy"))
        enemy.collidable = True
        enemy.move_by(25, 0)
        pending = enemy._collider._pending_motion_dx
        self.assertGreater(pending, 0)
        probe = self.track(Circle(center=self.at(0, 0), radius=40))
        x, y = float(enemy.center.x), float(enemy.center.y)
        self._bundle(probe, "enemy", x, y)
        self.assertEqual(enemy._collider._pending_motion_dx, pending)
        loose = self.track(Circle(center=self.at(80, 0), radius=12, group="scout"))
        loose.move_by(10, 0)
        probe.collides_with(group="scout")
        loose.collidable = True
        loose.move_by(15, 0)
        pending_loose = loose._collider._pending_motion_dx
        self.assertGreater(pending_loose, 0)
        probe.collides_with(group="scout")
        collision.raycast(self.at(-100, 0), p2=self.at(200, 0), group="scout")
        self.assertEqual(loose._collider._pending_motion_dx, pending_loose)


class TestPolygonCacheAliasing(CollisionTestCase):
    """D2 (Testing Design): the translate fast path shifted polygon prims in
    place while ``_poly_cache`` still held the same objects under the old
    vertex key. A later uncached rebuild that landed back on those vertices
    returned prims displaced by the earlier move — the body collided where it
    had been, not where it was."""

    POINTS = [(0, 0), (40, 0), (40, 20), (0, 20)]
    CONCAVE = [(0, 0), (40, 0), (40, 40), (20, 10), (0, 40)]

    def _aabbs(self, prims):
        return sorted(tuple(round(c, 6) for c in p.aabb) for p in prims)

    def test_snapshot_cache_matches_uncached_after_move_and_back(self):
        from scena.collision import Collider, snapshot_shape, _snapshot_shape_uncached
        for pts in (self.POINTS, self.CONCAVE):
            with self.subTest(concave=pts is self.CONCAVE):
                poly = self.track(Polygon(points=[self.at(x, y) for x, y in pts]))
                owner = Collider([poly], _identity_shape=poly)
                snapshot_shape(poly, cache_owner=owner)
                poly.move_by(50, 0)
                snapshot_shape(poly, cache_owner=owner)      # translate path
                poly.move_by(-50, 0)
                poly.rotate_by(10)
                poly.rotate_by(-10)                          # forces a rebuild
                got = snapshot_shape(poly, cache_owner=owner)
                want = _snapshot_shape_uncached(poly, cache_owner=None)
                self.assertEqual(self._aabbs(got), self._aabbs(want))

    def test_engine_reports_the_polygon_where_it_is(self):
        poly = self.track(Polygon(points=[self.at(x, y) for x, y in self.POINTS], group="d2wall"))
        here = self.track(Circle(center=self.at(20, 10), radius=4))
        there = self.track(Circle(center=self.at(120, 10), radius=4))
        for c in (poly, here, there):
            c.collidable = True
        self.step()
        self.assertEqual(here.collides_with(group="d2wall"), [poly])
        poly.move_by(100, 0)                                  # overlaps `there`
        self.step()
        self.assertEqual(there.collides_with(group="d2wall"), [poly])
        poly.move_by(-100, 0)
        poly.rotate_by(10)
        poly.rotate_by(-10)
        self.step()
        self.assertEqual(here.collides_with(group="d2wall"), [poly])
        self.assertEqual(there.collides_with(group="d2wall"), [])

    def test_no_cache_hands_out_the_prims_it_keeps(self):
        # Bug-class guard: callers mutate returned prims in place
        # (_translate_prims), so a returned Prim must never be a cached one.
        from scena.collision import Collider, snapshot_shape, _snapshot_shape_uncached
        poly = self.track(Polygon(points=[self.at(x, y) for x, y in self.CONCAVE]))
        owner = Collider([poly], _identity_shape=poly)
        for _ in range(3):   # miss, then hits
            returned = _snapshot_shape_uncached(poly, cache_owner=owner)
            returned += snapshot_shape(poly, cache_owner=owner)
            kept = {id(p) for _k, prims in owner._poly_cache.values() for p in prims}
            self.assertFalse(kept & {id(p) for p in returned})
            owner._snap_cache.clear()


class TestArcSnapshotAfterFaceMove(CollisionTestCase):
    """D10 (Testing Design): ``test_diff_collision`` reported a Circle arc's
    cached prims diverging from uncached after ``move_by(face=True)`` then
    ``move_to``. The engine was right (translate drift of 1 ulp); the oracle
    sorted raw floats and paired the two wedges crosswise. This pins the
    engine side: the translate fast path serves the move and matches a
    rebuild as a multiset within 1e-6 — prim order is not part of the contract.
    """

    def _match(self, got, want):
        self.assertEqual(len(got), len(want))
        free = list(got)
        for w in want:
            def gap(g):
                if g.kind != w.kind or len(g.verts or ()) != len(w.verts or ()):
                    return math.inf
                nums = list(zip(g.aabb, w.aabb)) + [
                    (a, b) for gv, wv in zip(g.verts or (), w.verts or ()) for a, b in zip(gv, wv)]
                return max(abs(a - b) for a, b in nums)
            best = min(free, key=gap)
            self.assertLess(gap(best), 1e-6, f"no cached prim matches {w.aabb}")
            free.remove(best)

    def test_cached_arc_matches_uncached_after_face_move_then_move_to(self):
        from scena.collision import Collider, snapshot_shape, _snapshot_shape_uncached
        arc = self.track(Circle(center=(1, 2), radius=9, angle=110, spread=180))
        owner = Collider([arc], _identity_shape=arc)
        arc.move_by(-27.0, 3.0, face=True)            # turns the arc: rebuild
        self._match(snapshot_shape(arc, cache_owner=owner),
                    _snapshot_shape_uncached(arc, cache_owner=None))
        builds = get_collision_system()._debug_hull_builds
        arc.move_to(0.0, 0.0)                         # translation only
        got = snapshot_shape(arc, cache_owner=owner)
        self.assertEqual(get_collision_system()._debug_hull_builds, builds,
                         "move_to should be served by the translate fast path")
        self.assertEqual(len(got), 2)                 # two wedges of a 180° arc
        self._match(got, _snapshot_shape_uncached(arc, cache_owner=None))


class TestGjkDistanceIsAMinimum(unittest.TestCase):
    """D4 (Testing Design): ``_gjk_distance`` reused the intersection GJK, which
    stops as soon as it proves separation and reported the closest point of an
    unfinished simplex — an OVERestimate (3.07 for a true gap of 2.0).
    Conservative advancement trusts it as a lower bound, so the sweep stepped
    past the contact: a box sliding into an obstacle was detected 0.7 deep
    (t = 0.90 instead of 0.667)."""

    def _col(self):
        import scena  # noqa: F401
        return sys.modules["scena.collision"]

    def _box(self, x0, y0, w, h):
        col = self._col()
        b = (x0, y0, x0 + w, y0 + h)
        return col.Prim(col.PrimKind.AABB, b, b)

    def _obb(self, x, y, hw, hh, deg):
        col = self._col()
        a = math.radians(deg)
        return col.Prim(col.PrimKind.OBB, col._aabb_from_obb(x, y, hw, hh, a), (x, y, hw, hh, a))

    def test_distance_matches_the_true_gap(self):
        col = self._col()
        cases = [
            (self._box(3, 0, 1, 1), self._obb(0, 0, 1, 3, 0), 2.0, (-1.0, 0.0)),
            (self._box(0, 5, 2, 2), self._obb(0, 0, 3, 1, 0), 4.0, (0.0, -1.0)),
            (self._box(10, 10, 1, 1), self._obb(0, 0, 2, 2, 0), math.hypot(8, 8), None),
        ]
        for a, b, gap, normal in cases:
            with self.subTest(a=a.params, b=b.params):
                d, nx, ny = col._gjk_distance([a], [b])
                self.assertAlmostEqual(d, gap, places=6)
                if normal is not None:
                    self.assertAlmostEqual(nx, normal[0], places=6)
                    self.assertAlmostEqual(ny, normal[1], places=6)

    def test_advancement_stops_at_the_first_contact(self):
        col = self._col()
        a, b = self._box(3, 0, 1, 1), self._obb(0, 0, 1, 3, 0)
        hit = col._toi_prim_sets([a], [b], -3.0, 0.0)
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit[0], 2.0 / 3.0, delta=2e-3)


class TestSupportIsTheTrueArgmax(unittest.TestCase):
    """D5 (Testing Design): ``_prim_support_ex`` kept the FIRST vertex within an
    absolute ``tie_eps = 0.5`` of the running best (meant only for counting a
    face's ties), so OBB / POLY supports could be a vertex up to 0.5 worse than
    the furthest one. GJK, EPA, projections and TOI bisection all read it:
    a box sweeping into a circle was reported 0.07 deep; GJK distances
    overestimated."""

    def test_obb_and_poly_support_is_the_furthest_vertex(self):
        import scena  # noqa: F401
        col = sys.modules["scena.collision"]
        obb = col.Prim(col.PrimKind.OBB, (-1, -3, 1, -1), (0.0, -2.0, 1.0, 1.0, 0.0))
        verts = [(-1.0, -3.0), (1.0, -3.0), (1.0, -1.0), (-1.0, -1.0)]
        poly = col.Prim(col.PrimKind.POLY, (-1, -3, 1, -1), (), verts)
        for prim in (obb, poly):
            corners = col._prim_as_poly(prim)
            for k in range(72):
                a = math.radians(k * 5 + 0.3)
                dx, dy = math.cos(a), math.sin(a)
                with self.subTest(kind=prim.kind.name, deg=k * 5 + 0.3):
                    best = max(x * dx + y * dy for x, y in corners)
                    sx, sy = col._prim_support(prim, dx, dy)
                    self.assertAlmostEqual(sx * dx + sy * dy, best, places=9)

    def test_face_ties_are_still_counted(self):
        import scena  # noqa: F401
        col = sys.modules["scena.collision"]
        obb = col.Prim(col.PrimKind.OBB, (-1, -3, 1, -1), (0.0, -2.0, 1.0, 1.0, 0.0))
        _pt, ties = col._prim_support_ex(obb, 0.001, 1.0)   # near the top face normal
        self.assertGreaterEqual(ties, 2)

    def test_box_sweeping_into_a_circle_stops_at_contact(self):
        import scena  # noqa: F401
        col = sys.modules["scena.collision"]
        box = col.Prim(col.PrimKind.OBB, (-1, -3, 1, -1), (0.0, -2.0, 1.0, 1.0, 0.0))
        ball = col.Prim(col.PrimKind.CIRCLE, (-1, 0, 1, 2), (0.0, 1.0, 1.0))
        self.assertAlmostEqual(col._gjk_distance([box], [ball])[0], 1.0, places=6)
        hit = col._toi_prim_sets([box], [ball], 0.0, 2.0)
        self.assertAlmostEqual(hit[0], 0.5, delta=2e-3)


class TestUntagPrunesPairTargets(CollisionTestCase):
    """D6 (Testing Design): leaving a group dropped the collider from that tag's
    list but kept the pair targets the tag implied (S6's class, via untag
    instead of destroy). No wrong handler fired, but a body later tagged into
    the stale target's group paid narrow-phase work for pairs nobody declared."""

    def test_untag_keeps_only_implied_targets(self):
        collide("d6_a", "d6_b")(lambda a, b: None)
        collide("d6_c", "d6_d")(lambda a, b: None)
        body = self.track(Circle(center=self.at(0, 0), radius=5, group=["d6_a", "d6_c"]))
        self.assertEqual(sorted(body._collider._pair_targets), ["d6_b", "d6_d"])
        body.untag("d6_a")
        self.assertEqual(sorted(body._collider._pair_targets), ["d6_d"])
        body.untag("d6_c")
        self.assertEqual(body._collider._pair_targets, [])
        body.tag("d6_a")
        self.assertEqual(body._collider._pair_targets, ["d6_b"])


class TestRestingContactSkin(CollisionTestCase):
    """F1 (Testing Design): resolve() parks a body ``_RESOLVE_SLOP`` short of
    its partner, so ``@collide`` on a standing resolve pair counts a gap up to
    ``_CONTACT_SKIN`` as a contact. Sensors stay strict overlap.
    Frame-level guard: ``tests/test_sys_resting_contact.py``."""

    def _pair(self, gap, *, resolved=True, hero=None, floor=None):
        floor = self.track(floor or Rect(center=self.at(0, 0), width=40, height=10,
                                         group="f1_floor"))
        floor.mass = STATIC
        hero = self.track(hero or Rect(center=self.at(0, 5 + 10 + gap), width=12,
                                       height=20, group="f1_hero"))
        if resolved:
            resolve("f1_hero", "f1_floor", bounce=0.0)
        events = []
        collide("f1_hero", "f1_floor")(lambda a, b, info: events.append(("enter", info)))
        collide_exit("f1_hero", "f1_floor")(lambda a, b, info: events.append(("exit", info)))
        return hero, floor, events

    def test_the_skin_covers_the_resolve_slop(self):
        self.assertGreater(_CONTACT_SKIN, _RESOLVE_SLOP)

    def test_gap_within_the_skin_is_a_contact(self):
        hero, _floor, events = self._pair(_RESOLVE_SLOP)
        self.step()
        self.assertEqual([e for e, _ in events], ["enter"])
        info = events[0][1]
        self.assertEqual(info.depth, 0.0)
        self.assertAlmostEqual(info.normal.x, 0.0, places=6)
        self.assertAlmostEqual(info.normal.y, -1.0, places=6)   # hero -> floor
        self.assertIsNotNone(info.point)
        self.assertLessEqual(abs(info.point[1] - (self.origin + 5)), _CONTACT_SKIN)
        for _ in range(5):
            self.step()
        self.assertEqual([e for e, _ in events], ["enter"])

    def test_gap_beyond_the_skin_is_not(self):
        _hero, _floor, events = self._pair(_CONTACT_SKIN * 1.5)
        self.step()
        self.assertEqual(events, [])

    def test_leaving_past_the_skin_exits(self):
        hero, _floor, events = self._pair(_RESOLVE_SLOP)
        self.step()
        hero.move_to(self.at(0, 5 + 10 + 1.0))
        self.step()
        self.assertEqual([e for e, _ in events], ["enter", "exit"])

    def test_a_sensor_pair_stays_strict_overlap(self):
        _hero, _floor, events = self._pair(_RESOLVE_SLOP, resolved=False)
        self.step()
        self.assertEqual(events, [])

    def test_resolve_disabled_stays_strict_overlap(self):
        _hero, _floor, events = self._pair(_RESOLVE_SLOP)
        collision.resolve_enabled = False
        try:
            self.step()
        finally:
            collision.resolve_enabled = True
        self.assertEqual(events, [])

    def test_closed_form_gaps_match_gjk(self):
        """``_prim_gap`` fast paths (AABB / circle) against the GJK reference."""
        import random
        rng = random.Random(1)

        def box(x, y):
            w, h = rng.uniform(1, 20), rng.uniform(1, 20)
            p = (x - w, y - h, x + w, y + h)
            return Prim(PrimKind.AABB, p, p)

        def disk(x, y):
            r = rng.uniform(0.5, 10)
            return Prim(PrimKind.CIRCLE, (x - r, y - r, x + r, y + r), (x, y, r))

        checked = 0
        for _ in range(400):
            pa = rng.choice([box, disk])(rng.uniform(-50, 50), rng.uniform(-50, 50))
            pb = rng.choice([box, disk])(rng.uniform(-50, 50), rng.uniform(-50, 50))
            if narrow_phase(pa, pb) is not None:
                continue
            gap, nx, ny = _prim_gap(pa, pb)
            ref, rx, ry = _gjk_distance((pa,), (pb,))
            with self.subTest(a=pa, b=pb):
                # GJK stops within ~1e-9 relative on the gap; its normal on a
                # circle is only good to ~1e-5, so compare it at that accuracy.
                self.assertAlmostEqual(gap, ref, places=6)
                self.assertAlmostEqual(nx, rx, places=4)
                self.assertAlmostEqual(ny, ry, places=4)
            checked += 1
        self.assertGreater(checked, 100)

    def test_curved_and_rotated_prims_use_the_true_gap(self):
        """GJK distance, not the AABB: a circle near a 45° box corner's AABB
        but farther than the skin from the box is not a contact."""
        box = Rect(center=self.at(0, 0), width=20, height=20, angle=45,
                   group="f1_floor")
        top = self.origin + 10 * math.sqrt(2)
        near = Circle(center=(self.origin, top + 5 + _RESOLVE_SLOP), radius=5,
                      group="f1_hero")
        _hero, _floor, events = self._pair(0, hero=near, floor=box)
        self.step()
        self.assertEqual([e for e, _ in events], ["enter"])
        reset_collision_system()
        box = Rect(center=self.at(0, 0), width=20, height=20, angle=45,
                   group="f1_floor")
        # Inside the box's AABB, 3.1 DU from the slanted face x + y = top.
        far = Circle(center=self.at(8, 12), radius=1, group="f1_hero")
        self.assertGreater((8 + 12 - 10 * math.sqrt(2)) / math.sqrt(2) - 1, 3 * _CONTACT_SKIN)
        _hero, _floor, events = self._pair(0, hero=far, floor=box)
        self.step()
        self.assertEqual(events, [])


class TestPoseKeyCoversDefiningInputs(CollisionTestCase):
    """R7 (Testing Design): once D3 kept focal Ellipses / two-point Circles cold,
    their collision pose key stopped seeing some changes. The key's extra read
    Derivate slots from ``__dict__`` (stale while cold); it only ever worked
    because warm Derivates made ``_update_impl`` bump ``_collision_epoch``.
    A tilted focal ellipse flipped by ``flip_x`` kept colliding at 30 deg
    instead of 150 deg. Keys must be built from Defining inputs."""

    def _check(self, shape, change):
        import scena  # noqa: F401
        col = sys.modules["scena.collision"]
        owner = col.Collider([shape], _identity_shape=shape)
        col.snapshot_shape(shape, cache_owner=owner)
        change(shape)
        got = col.snapshot_shape(shape, cache_owner=owner)
        want = col._snapshot_shape_uncached(shape, cache_owner=None)
        key = lambda prims: [(p.kind.name, tuple(round(v, 6) for v in p.params)) for p in prims]
        self.assertEqual(key(got), key(want))

    def test_tilted_focal_ellipse_flip(self):
        a = math.radians(30)
        e = self.track(Ellipse(fp1=self.at(-3 * math.cos(a), -3 * math.sin(a)),
                               fp2=self.at(3 * math.cos(a), 3 * math.sin(a)), major_axis=10))
        self._check(e, lambda s: setattr(s, "flip_x", True))

    def test_focal_ellipse_major_axis_write(self):
        e = self.track(Ellipse(fp1=self.at(-3, 0), fp2=self.at(3, 0), major_axis=10))
        self._check(e, lambda s: setattr(s, "major_axis", 16))

    def test_two_point_circle_symmetric_resize(self):
        c = self.track(Circle(p1=self.at(-5, 0), p2=self.at(5, 0)))

        def grow(s):
            s.p1 = self.at(-9, 0)
            s.p2 = self.at(9, 0)      # same center, larger radius
        self._check(c, grow)

    def test_center_perimeter_circle_radius_change(self):
        c = self.track(Circle(center=self.at(0, 0), perimeter_point=self.at(5, 0)))
        self._check(c, lambda s: setattr(s, "perimeter_point", self.at(0, 9)))


class TestSweptDetection(CollisionTestCase):
    """A fast ``move_by`` body is detected along its path, not only at the end.

    Fast = this frame's motion exceeds half the body's thickness. A laser 28
    tall moving 83 per frame past a 40-tall enemy has no end-pose overlap, so
    plain detection tunnels; swept detection reports the crossing once.
    Collision Design.md — Swept detection (fast bodies).
    """

    STEP = 83.0

    def _laser(self, x=0.0, y=-40.0, group="shot"):
        return self.track(Rect(center=self.at(x, y), width=6, height=28, group=group))

    def _enemy(self, x=0.0, y=0.0, w=40.0, h=40.0, group="enemy"):
        return self.track(Rect(center=self.at(x, y), width=w, height=h, group=group))

    def _log_pair(self, a="shot", b="enemy"):
        log = []
        collide(a, b)(lambda me, other, info: log.append(("enter", other, info)))
        collide_stay(a, b)(lambda me, other, info: log.append(("stay", other, info)))
        collide_exit(a, b)(lambda me, other, info: log.append(("exit", other, info)))
        return log

    def test_fast_laser_through_enemy_enters_once_then_exits(self):
        shot = self._laser()
        enemy = self._enemy()
        log = self._log_pair()
        self.step()
        self.assertEqual(log, [])
        shot.move_by(0, self.STEP)            # -40 -> 43: no end-pose overlap
        self.step()
        self.assertEqual([(k, o) for k, o, _i in log], [("enter", enemy)])
        stats = get_collision_system().last_stats
        self.assertEqual(stats["fast"], 1)
        self.assertEqual(stats["swept_hits"], 1)
        shot.move_by(0, self.STEP)
        self.step()
        self.assertEqual([k for k, _o, _i in log], ["enter", "exit"])
        shot.move_by(0, self.STEP)
        self.step()
        self.assertEqual([k for k, _o, _i in log], ["enter", "exit"])

    def test_swept_payload_is_the_impact(self):
        shot = self._laser()
        self._enemy()
        log = self._log_pair()
        self.step()
        shot.move_by(0, self.STEP)
        self.step()
        (_k, _o, info), = log
        self.assertEqual(info.depth, 0.0)
        self.assertGreater(float(info.normal.y), 0.99)     # shot -> enemy: up
        px, py = info.point
        ox, oy = self.at(0, 0)
        self.assertAlmostEqual(py, oy - 20.0, delta=0.5)    # enemy's bottom face
        self.assertLess(abs(px - ox), 3.5)
        # The bodies stay where they ended: detection never moves them.
        self.assertAlmostEqual(float(shot.center.y), oy + 43.0, places=6)

    def test_threshold_is_half_the_thickness(self):
        # radius 10 -> thickness 20 -> fast above 10 per frame.
        for d, fast in ((9.9, 0), (10.1, 1)):
            reset_collision_system()
            a = self.track(Circle(center=self.at(0, 0), radius=10, group="shot"))
            self._enemy(x=500)
            self._log_pair()
            self.step()
            a.move_by(d, 0)
            self.step()
            self.assertEqual(get_collision_system().last_stats["fast"], fast, d)

    def test_nearest_enemy_first_when_shot_dies(self):
        shot = self._laser(y=-60)
        far = self._enemy(y=45)               # created first: index order picks it
        near = self._enemy(y=0)
        hit = []

        def boom(me, other, info):
            hit.append(other)
            me.destroy()
        collide("shot", "enemy")(boom)
        self.step()
        shot.move_by(0, 150)                  # crosses both, ends past both
        self.step()
        self.assertEqual(hit, [near])
        self.assertTrue(far.is_alive)

    def test_end_pose_contact_reached_first_still_goes_first(self):
        # The shot ends inside the long enemy B (entered at t~0.11) and passes
        # through the small A inside it (t~0.47): B is the nearer hit.
        small = self._enemy(y=60, w=10, h=10)
        big = self._enemy(y=100, w=40, h=200)
        shot = self._laser(y=-30)
        hit = []

        def boom(me, other, info):
            hit.append(other)
            me.destroy()
        collide("shot", "enemy")(boom)
        self.step()
        shot.move_by(0, 150)
        self.step()
        self.assertEqual(hit, [big])
        self.assertTrue(small.is_alive)

    def test_placement_is_not_swept(self):
        ox, oy = self.at(0, 0)
        for how in ("center", "move_to", "link"):
            reset_collision_system()
            ghost = self.track(Circle(center=(ox, oy - 40), radius=1))
            shot = self._laser()
            if how == "link":
                shot.center @= lambda: ghost.center
            self._enemy()
            log = self._log_pair()
            self.step()
            target = (ox, oy + 43)
            if how == "center":
                shot.center = target
            elif how == "move_to":
                shot.move_to(*target)
            else:
                ghost.center = target
            self.step()
            self.assertEqual(log, [], how)
            if how == "link":
                shot.center.unlink()

    def test_moving_together_is_not_swept(self):
        shot = self._laser()
        enemy = self._enemy(y=60)
        self._log_pair()
        self.step()
        shot.move_by(0, self.STEP)
        enemy.move_by(0, self.STEP)
        self.step()
        self.assertEqual(get_collision_system().last_stats["swept"], 0)

    def test_start_overlap_after_placement_enters(self):
        # Placed inside the enemy and moved out in the same frame: the start
        # pose overlaps, the pair was never reported, so it enters.
        shot = self._laser(y=-200)
        self._enemy()
        log = self._log_pair()
        self.step()
        shot.center = self.at(0, 0)
        shot.move_by(0, self.STEP)
        self.step()
        self.assertEqual([k for k, _o, _i in log], ["enter"])

    def test_on_collide_anything_sees_the_crossing(self):
        shot = self._laser(group=None)
        enemy = self._enemy(group=None)
        shot.collidable = True
        enemy.collidable = True
        log = []
        shot.on_collide = lambda me, other, info: log.append(other)
        self.step()
        shot.move_by(0, self.STEP)
        self.step()
        self.assertEqual(log, [enemy])

    def test_resolve_disabled_keeps_swept_detection(self):
        shot = self._laser()
        self._enemy()
        log = self._log_pair()
        get_collision_system().resolve_enabled = False
        try:
            self.step()
            shot.move_by(0, self.STEP)
            self.step()
        finally:
            get_collision_system().resolve_enabled = True
        self.assertEqual(len(log), 1)

    def test_fast_sprite_hitbox_part_is_swept(self):
        ship = self.track(Sprite(center=self.at(0, 0), size=64, hitbox_shape="rect"))
        ship.add_hitbox(group="hurt", shape="rect", scale=(0.2, 1.0))
        wall = self._enemy(x=50, w=10, h=200, group="wall")
        log = []
        collide("hurt", "wall")(lambda me, other, info: log.append(other))
        self.step()
        ship.move_by(100, 0)                  # part ~13 wide jumps the 10-wide wall
        self.step()
        self.assertEqual(log, [wall])

    def test_fast_body_pushed_into_resolved_wall_fires_collide(self):
        # resolve() stops the ball at the wall, but the pre-resolve end pose is
        # always past it: without swept detection @collide never fires.
        ball = self.track(Circle(center=self.at(0, 0), radius=5, group="ball"))
        ball.mass = 1.0
        wall = self._enemy(x=150, w=4, h=200, group="wall")
        wall.mass = STATIC
        resolve("ball", "wall")
        log = []
        collide("ball", "wall")(lambda me, other, info: log.append(other))
        self.step()
        for _ in range(3):
            ball.move_by(100, 0)
            self.step()
        self.assertEqual(log, [wall])
        ox, _oy = self.at(0, 0)
        self.assertLess(float(ball.center.x), ox + 148.0)  # resolve still stops it

    def test_slow_scene_pays_nothing(self):
        """Perf contract: a scene with no fast body never widens, sweeps or TOIs."""
        coll = sys.modules["scena.collision"]

        def scene():
            reset_collision_system()
            enemies = []
            for k in range(40):
                j, i = divmod(k, 8)
                enemies.append(self._enemy(x=i * 90, y=300 + j * 60, w=44, h=44))
            shots = [self.track(Circle(center=self.at(i * 30, i * 40), radius=7, group="shot"))
                     for i in range(10)]
            collide("shot", "enemy")(lambda *a: None)
            return shots, enemies

        def run():
            shots, enemies = scene()
            pairs = []
            for _f in range(60):
                for s in shots:
                    s.move_by(0, 2.0)
                for e in enemies:
                    e.move_by(0.5, 0)
                self.step()
                st = get_collision_system().last_stats
                self.assertEqual(st["fast"], 0)
                self.assertEqual(st["swept"], 0)
                pairs.append(st["proxy_pairs"])
            return pairs

        calls = []
        real = coll._toi_prim_sets

        def counting(*a, **k):
            calls.append(1)
            return real(*a, **k)
        coll._toi_prim_sets = counting
        try:
            with_sweep = run()
            saved = coll._FAST_MOTION_FRACTION
            coll._FAST_MOTION_FRACTION = math.inf
            try:
                without = run()
            finally:
                coll._FAST_MOTION_FRACTION = saved
        finally:
            coll._toi_prim_sets = real
        self.assertEqual(calls, [])
        self.assertEqual(with_sweep, without)

    def test_canary_old_rule_tunnels(self):
        """With the gate off the laser passes through: the tests above test the sweep."""
        coll = sys.modules["scena.collision"]
        saved = coll._FAST_MOTION_FRACTION
        coll._FAST_MOTION_FRACTION = math.inf
        try:
            shot = self._laser()
            self._enemy()
            log = self._log_pair()
            self.step()
            shot.move_by(0, self.STEP)
            self.step()
            self.assertEqual(log, [])
        finally:
            coll._FAST_MOTION_FRACTION = saved


class TestOrbitMotion(CollisionTestCase):
    """``rotate_by(..., about=)`` off the anchor carries it along a chord: motion.

    The chord is swept like a ``move_by`` (detection and resolve). Placement
    turns (instant ``rotate_to``, ``angle =``, face snaps) note nothing, and a
    turn about the anchor (spin) is still not swept.
    Collision Design.md — Motion vs placement / Swept detection.
    """

    R = 200.0
    STEP = 20.0                     # deg/frame: a 10-wide body moves ~69 DU

    def _pending(self, shape):
        c = shape._collider
        return (c._pending_motion_dx, c._pending_motion_dy)

    def _orbit_target(self, deg, r=None):
        r = self.R if r is None else r
        a = math.radians(deg)
        return self.track(Rect(
            center=self.at(r * math.cos(a), r * math.sin(a)),
            width=8, height=8, group="b",
        ))

    def test_fast_orbit_hits_a_target_between_poses(self):
        a = self.track(Rect(center=self.at(self.R, 0), width=10, height=10, group="a"))
        target = self._orbit_target(50.0)      # between the 40 and 60 poses
        log = []
        collide("a", "b")(lambda me, other, info: log.append(other))
        self.step()
        fast = 0
        for _ in range(6):
            a.rotate_by(self.STEP, about=self.at(0, 0))
            self.step()
            fast += get_collision_system().last_stats["fast"]
        self.assertEqual(log, [target])
        self.assertGreater(fast, 0)

    def test_orbit_notes_the_chord_once_for_every_kind(self):
        # An override that calls super().rotate_by must not note twice, and
        # every kind's pending motion is its anchor's displacement.
        from scena.collision import _collision_pose_xy
        kinds = [
            Rect(center=self.at(50, 0), width=10, height=6),
            Circle(center=self.at(50, 0), radius=5),
            Ellipse(center=self.at(50, 0), width=12, height=6),
            Polygon(points=[self.at(45, -5), self.at(55, -5), self.at(50, 6)]),
            RegularPolygon(center=self.at(50, 0), radius=6, n=5),
            Line(p1=self.at(45, 0), p2=self.at(55, 0), line_width=3),
            Track(points=[self.at(40, 0), self.at(60, 0)], smooth=0, line_width=4),
            Sprite(center=self.at(50, 0), size=16, hitbox_shape="rect"),
        ]
        for shape in kinds:
            with self.subTest(kind=type(shape).__name__):
                self.track(shape)
                shape.collidable = True
                self.step()
                x0, y0 = _collision_pose_xy(shape)
                shape.rotate_by(30, about=self.at(0, 0))
                x1, y1 = _collision_pose_xy(shape)
                self.assertGreater(math.hypot(x1 - x0, y1 - y0), 20.0)
                dx, dy = self._pending(shape)
                self.assertAlmostEqual(dx, x1 - x0, places=6)
                self.assertAlmostEqual(dy, y1 - y0, places=6)
                self.step()

    def test_placement_turns_and_spin_note_nothing(self):
        r = self.track(Rect(center=self.at(50, 0), width=10, height=6))
        s = self.track(Sprite(center=self.at(50, 0), size=16, hitbox_shape="rect"))
        for shape in (r, s):
            with self.subTest(kind=type(shape).__name__):
                shape.collidable = True
                self.step()
                cases = {
                    "rotate_to about": lambda: shape.rotate_to(
                        float(shape.angle) + 40, about=self.at(0, 0)),
                    "angle =": lambda: setattr(shape, "angle", float(shape.angle) + 40),
                    "spin": lambda: shape.rotate_by(40),
                    "move_to face about": lambda: shape.move_to(
                        self.at(0, 80), face=True, about=self.at(0, 0)),
                }
                for name, fn in cases.items():
                    fn()
                    self.assertEqual(self._pending(shape), (0.0, 0.0), name)
                    self.step()

    def test_unenrolled_orbit_does_not_enroll(self):
        r = self.track(Rect(center=self.at(50, 0), width=10, height=6))
        r.rotate_by(30, about=self.at(0, 0))
        self.assertIsNone(r._collider)

    def test_hitbox_parts_travel_with_an_orbiting_host(self):
        ship = self.track(Sprite(center=self.at(self.R, 0), size=16, hitbox_shape="rect"))
        part = ship.add_hitbox(group="hurt", shape="rect", scale=(0.5, 0.5))
        target = self._orbit_target(50.0)
        log = []
        collide("hurt", "b")(lambda me, other, info: log.append(other))
        self.step()
        for _ in range(6):
            ship.rotate_by(self.STEP, about=self.at(0, 0))
            self.step()
        self.assertEqual(log, [target])
        self.assertIsNotNone(part)

    def _ticking(self, body):
        from scena import clock
        from scena.process import reset_process_scheduler, tick_processes
        reset_process_scheduler()
        clock.scale = 1.0
        clock.paused = False
        clock._dt = 0.0
        clock._time = 0.0
        try:
            body(clock, tick_processes)
        finally:
            reset_process_scheduler()

    def test_timed_orbit_is_motion(self):
        for verb in ("rotate_by", "rotate_to"):
            with self.subTest(verb=verb):
                reset_collision_system()
                a = self.track(Rect(center=self.at(self.R, 0), width=10, height=10, group="a"))
                target = self._orbit_target(50.0)
                log = []
                collide("a", "b")(lambda me, other, info: log.append(other))

                def body(clock, tick):
                    self.step()
                    # 120 deg over 6 frames of 1/60 s: 20 deg per tick.
                    getattr(a, verb)(120, time=0.1, about=self.at(0, 0))
                    for _ in range(8):
                        clock.advance(1.0 / 60.0)
                        tick()
                        self.step()

                self._ticking(body)
                self.assertEqual(log, [target])

    def test_resolve_stops_an_orbit_at_a_thin_shelf(self):
        # Poses at 20 and 40 deg sit below and above the shelf: as placement the
        # body jumped it; as motion the sweep stops it underneath.
        ox, oy = self.at(0, 0)
        shelf = self.track(Rect(center=(ox + 175, oy + 100), width=110, height=4, group="wall"))
        shelf.mass = STATIC
        body = self.track(Rect(center=(ox + self.R, oy), width=10, height=10, group="hero"))
        body.mass = 1.0
        resolve("hero", "wall")
        self.step()
        body.rotate_by(self.STEP, about=(ox, oy))
        self.step()
        self.assertLess(float(body.center.y), oy + 98.0)
        body.rotate_by(self.STEP, about=(ox, oy))
        self.step()
        self.assertLess(float(body.center.y), oy + 98.0)

class TestDestroyedSidesLeaveEverySnapshotSide(CollisionTestCase):
    """HD1 (Testing Design, HD): a group-operator side (``group["a"] | group["b"]``)
    copies its members at the call; a destroyed member must leave that copy
    in every pair list (handlers and ``resolve``), or the dead body stays
    reachable from the collision system for good."""

    def _snapshot_sides(self):
        col = get_collision_system()
        sides = []
        for a, b, *_rest in list(col._pair_handlers) + list(col._resolve_pairs):
            for side in (a, b):
                snap = getattr(side, "_snapshot", None)
                if snap is not None:
                    sides.append(snap)
        return sides

    def test_destroyed_member_leaves_handler_and_resolve_snapshots(self):
        from scena import group
        a = self.track(Circle(center=self.at(0, 0), radius=5, group="hd_a"))
        b = self.track(Circle(center=self.at(50, 0), radius=5, group="hd_b"))
        rock = self.track(Circle(center=self.at(500, 0), radius=5, group="hd_rock"))
        rock.mass = STATIC

        @collide(group["hd_a"] | group["hd_b"], "hd_rock")
        def _hit(x, y, info=None):
            pass

        resolve(group["hd_a"] | group["hd_b"], rock)
        sides = self._snapshot_sides()
        self.assertTrue(sides, "no snapshot side was registered")
        self.assertTrue(all(any(m is a for m in snap) for snap in sides))
        a.destroy()
        for snap in self._snapshot_sides():
            self.assertFalse(any(m is a for m in snap), "a destroyed member stayed in a side")
            self.assertTrue(any(m is b for m in snap), "the live member was dropped too")


class TestDyingBodyExits(unittest.TestCase):
    """Destroy fires the dying body's own exit while it still exists, and the
    survivor's exit sees it out of its groups (review 2026-10-09 X-life-5,
    S9-2)."""

    def test_own_exit_may_write_to_the_dying_body(self):
        from scena import Circle
        from tests.system_support import system_world
        seen = []
        with system_world(draw=False) as w:
            ship = Circle(center=(0, 0), radius=10, group="dx_ship")
            lava = Circle(center=(5, 0), radius=10, group="dx_lava")

            def cool(me, other, info):
                me.color = "white"           # raised DestroyedError before
                seen.append(me.is_alive)
            ship.on_collide = lambda me, other, info: None
            ship.on_collide_exit = cool
            lava.collidable = True
            w.step(2, dt=1 / 60)
            ship.destroy()
            lava.destroy()
        self.assertEqual(seen, [True])

    def test_survivor_exit_sees_the_group_without_the_dying(self):
        from scena import Circle, collide, collide_exit, group
        from tests.system_support import system_world
        seen = []
        with system_world(draw=False) as w:
            hero = Circle(center=(0, 0), radius=10, group="dx_hero")
            foe = Circle(center=(5, 0), radius=10, group="dx_foe")

            @collide("dx_hero", "dx_foe")
            def touch(h, f, info):
                pass

            @collide_exit("dx_hero", "dx_foe")
            def gone(h, f, info):
                seen.append((group["dx_foe"].count, group["dx_foe"].empty))
                group["dx_foe"].move_by(1, 0)    # a broadcast skips the dying

            w.step(2, dt=1 / 60)
            foe.destroy()
            hero.destroy()
        self.assertEqual(seen, [(0, True)])


class TestExitAfterGroupChange(unittest.TestCase):
    """An exit matches the handlers its contact entered under: ``untag``
    mid-contact fires the exit of the tag it left (PB1), and a handler that
    destroys or untags a side does not hide the other exit handlers (PB3)."""

    def _run(self, act, *, part=False, cls=False):
        from scena import Rect, collide, collide_exit, collide_with, collide_with_exit
        from tests.system_support import system_world
        log = []
        with system_world(draw=False) as w:
            if cls:
                class Spike(Rect, width=40, height=40, group="xg_spike"):
                    @collide_with("xg_hero")
                    def hit(self, other):
                        log.append("enter")

                    @collide_with_exit("xg_hero")
                    def left(self, other):
                        log.append("exit")
                spike = Spike(center=(0, 0))
            else:
                spike = Rect(center=(0, 0), width=40, height=40, group="xg_spike")

                @collide("xg_spike", "xg_hero")
                def hit(s, h, info):
                    log.append("enter")

                @collide_exit("xg_spike", "xg_hero")
                def left(s, h, info):
                    log.append("exit")
            hero = Rect(center=(0, 0), width=20, height=20, group="xg_hero")
            w.begin_game()
            w.step(2)
            act(hero)
            w.step(2)
            hero.tag("xg_hero")
            w.step(2)
            seen = list(log)
            for o in (spike, hero):
                o.destroy()
        return seen

    def test_untag_mid_contact_fires_exit(self):
        self.assertEqual(self._run(lambda h: h.untag("xg_hero")), ["enter", "exit", "enter"])

    def test_untag_mid_contact_fires_class_exit(self):
        self.assertEqual(self._run(lambda h: h.untag("xg_hero"), cls=True),
                         ["enter", "exit", "enter"])

    def test_untag_and_retag_in_one_frame_is_no_change(self):
        def flick(h):
            h.untag("xg_hero")
            h.tag("xg_hero")
        log = self._run(flick)
        self.assertEqual(log, ["enter"])

    def test_untag_then_destroy_fires_one_exit(self):
        from scena import Rect, collide, collide_exit
        from tests.system_support import system_world
        log = []
        with system_world(draw=False) as w:
            spike = Rect(center=(0, 0), width=40, height=40, group="xg_spike")
            hero = Rect(center=(0, 0), width=20, height=20, group="xg_hero")

            @collide_exit("xg_spike", "xg_hero")
            def left(s, h, info):
                log.append("exit")
            w.step(2)
            hero.untag("xg_hero")
            hero.destroy()
            w.step(3)
            spike.destroy()
        self.assertEqual(log, ["exit"])

    def test_a_later_contact_does_not_match_the_left_tag(self):
        from scena import Rect, collide_exit
        from tests.system_support import system_world
        log = []
        with system_world(draw=False) as w:
            spike = Rect(center=(0, 0), width=40, height=40, group="xg_spike")
            other = Rect(center=(300, 0), width=40, height=40, group="xg_spike")
            hero = Rect(center=(0, 0), width=20, height=20, group="xg_hero")

            @collide_exit("xg_spike", "xg_hero")
            def left(s, h, info):
                log.append(s)
            w.step(2)
            hero.untag("xg_hero")
            w.step(1)
            hero.move_to(300, 0)          # touches ``other`` untagged: no pair
            w.step(3)
            hero.move_to(600, 0)
            w.step(3)
            for o in (spike, other, hero):
                o.destroy()
        self.assertEqual(log, [spike])

    def test_destroy_in_one_exit_handler_keeps_the_others(self):
        from scena import Circle, Rect, collide_exit
        from tests.system_support import system_world
        for victim in ("ball", "zone"):
            log = []
            with system_world(draw=False) as w:
                ball = Circle(center=(0, 0), radius=10, group="xg_ball")
                zone = Rect(center=(0, 0), width=50, height=50, group="xg_zone")

                @collide_exit("xg_ball", "xg_zone")
                def first(b, z, info):
                    log.append("first")
                    (b if victim == "ball" else z).destroy()

                @collide_exit("xg_ball", "xg_zone")
                def second(b, z, info):
                    log.append("second")
                w.begin_game()
                w.step(2)
                ball.move_by(300, 0)
                w.step(2)
                for o in (ball, zone):
                    if o.is_alive:
                        o.destroy()
            self.assertEqual(log, ["first", "second"], victim)


class TestDispatchSeesWhatHandlersDid(unittest.TestCase):
    """One dispatch, several handlers. Every enter / stay handler of a
    contact runs, also after one destroyed a side (PB5, 2026-10-14: S8-2
    stopped the rest, so who scored depended on spawn order); a body
    destroyed there enters no other pair, and an exit is delivered only for
    a pair whose enter ran (review 2026-10-09 S8-2, S8-3). An act change
    still stops the old act's handlers (test_act.TestChangeInsideADispatch)."""

    def test_later_pair_handlers_see_a_destroyed_side(self):
        from scena import Circle, collide
        from tests.system_support import system_world
        seen = []
        with system_world(draw=False) as w:
            hero = Circle(center=(0, 0), radius=5)
            enemy = Circle(center=(4, 0), radius=10)

            @collide(hero, enemy)
            def first(h, e, info):
                seen.append(("first", e.is_alive))

            @collide(hero, enemy)
            def kill(h, e, info):
                seen.append(("kill", e.is_alive))
                e.destroy()

            @collide(hero, enemy)
            def score(h, e, info):
                seen.append(("score", e.is_alive))

            w.step(2, dt=1 / 60)
            hero.destroy()
        # PB5: ``score`` runs too, with the dead-but-readable enemy.
        self.assertEqual(seen, [("first", True), ("kill", True), ("score", False)])

    def test_mutual_kill_kills_both(self):
        from scena import Circle
        from tests.system_support import system_world
        calls = []
        with system_world(draw=False) as w:
            a = Circle(center=(0, 0), radius=5)
            b = Circle(center=(4, 0), radius=10)
            a.on_collide = lambda me, other, info: (calls.append((me.is_alive, other.is_alive)), other.destroy())
            b.on_collide = lambda me, other, info: (calls.append((me.is_alive, other.is_alive)), other.destroy())
            w.step(2, dt=1 / 60)
            # PB5: both callbacks run (the second on a dead ``me``), so each
            # kills the other whichever was made first. Before, only one ran.
            self.assertEqual(calls, [(True, True), (False, True)])
            self.assertFalse(a.is_alive)
            self.assertFalse(b.is_alive)

    def test_no_exit_without_its_enter(self):
        from scena import Circle, collide, collide_exit
        from tests.system_support import system_world
        log = []
        with system_world(draw=False) as w:
            shot = Circle(center=(0, 0), radius=5, group="dl_shot")
            e1 = Circle(center=(-6, 0), radius=4, group="dl_foe")
            e2 = Circle(center=(6, 0), radius=4, group="dl_foe")

            @collide("dl_shot", "dl_foe")
            def hit(s, f, info):
                log.append(("enter", f))
                s.destroy()

            @collide_exit("dl_shot", "dl_foe")
            def left(s, f, info):
                log.append(("exit", f))

            w.step(2, dt=1 / 60)
            for o in (e1, e2):
                o.destroy()
        entered = [f for k, f in log if k == "enter"]
        exited = [f for k, f in log if k == "exit"]
        self.assertEqual(len(entered), 1)
        self.assertEqual(exited, entered)


class TestEveryEnterHandlerOfAContactRuns(unittest.TestCase):
    """PB5 (2026-10-14): the enter handlers of one contact all run, so the
    outcome does not depend on which body was spawned first or on whether
    a rule is a class method or a module ``@collide``."""

    def _shooter(self, shot_first):
        from scena import Circle, Rect, collide_with, st
        from tests.system_support import system_world
        with system_world(draw=False) as w:
            st.pb5_pontos = 0

            class Tiro(Circle, radius=5, group="pb5_tiros"):
                @collide_with("pb5_inimigos")
                def bateu(self, inimigo):
                    self.destroy()

            class Inimigo(Rect, width=40, height=40, group="pb5_inimigos"):
                @collide_with("pb5_tiros")
                def atingido(self, tiro):
                    self.destroy()
                    st.pb5_pontos += 1

            if shot_first:
                shots = [Tiro(center=(0, 0)), Tiro(center=(200, 0))]
                foes = [Inimigo(center=(0, 0)), Inimigo(center=(200, 0))]
            else:
                foes = [Inimigo(center=(0, 0)), Inimigo(center=(200, 0))]
                shots = [Tiro(center=(0, 0)), Tiro(center=(200, 0))]
            w.step(2, dt=1 / 60)
            alive = [o.is_alive for o in shots + foes]
            for o in shots + foes:
                if o.is_alive:
                    o.destroy()
            return st.pb5_pontos, alive

    def test_shooter_outcome_does_not_depend_on_spawn_order(self):
        for shot_first in (True, False):
            with self.subTest(shot_first=shot_first):
                pontos, alive = self._shooter(shot_first)
                self.assertEqual(pontos, 2)
                self.assertEqual(alive, [False] * 4)

    def test_module_rule_and_class_method_in_either_order(self):
        from scena import Circle, Rect, collide, collide_with, st
        from tests.system_support import system_world
        for rule_first in (True, False):
            with self.subTest(rule_first=rule_first), system_world(draw=False) as w:
                st.pb5_pts = 0

                class Inimigo(Rect, width=40, height=40, group="pb5m_inimigos"):
                    @collide_with("pb5m_tiros")
                    def atingido(self, tiro):
                        st.pb5_pts += 1

                def rule():
                    @collide("pb5m_tiros", "pb5m_inimigos")
                    def some(tiro, inimigo, info):
                        tiro.destroy()

                if rule_first:
                    rule()
                a = Inimigo(center=(0, 0))
                if not rule_first:
                    rule()
                b = Inimigo(center=(300, 0))
                s1 = Circle(center=(0, 0), radius=5, group="pb5m_tiros")
                s2 = Circle(center=(300, 0), radius=5, group="pb5m_tiros")
                w.step(2, dt=1 / 60)
                self.assertEqual(st.pb5_pts, 2)
                self.assertFalse(s1.is_alive)
                self.assertFalse(s2.is_alive)
                a.destroy()
                b.destroy()

    def test_two_methods_of_the_dying_body_both_run(self):
        from scena import Circle, Rect, collide_with
        from tests.system_support import system_world
        log = []
        with system_world(draw=False) as w:
            class Tiro(Circle, radius=5, group="pb5d_tiros"):
                @collide_with("pb5d_alvo")
                def a_some(self, alvo):
                    log.append("some")
                    self.destroy()

                @collide_with("pb5d_alvo")
                def b_faisca(self, alvo):
                    log.append(("faisca", self.is_alive))

            alvo = Rect(center=(0, 0), width=40, height=40, group="pb5d_alvo")
            Tiro(center=(0, 0))
            w.step(2, dt=1 / 60)
            alvo.destroy()
        self.assertEqual(log, ["some", ("faisca", False)])

    def test_one_shot_still_damages_one_enemy(self):
        """A shot destroyed in its first contact's handlers enters no other
        pair this step (S8-2's purpose, kept)."""
        from scena import Circle, collide, st
        from tests.system_support import system_world
        with system_world(draw=False) as w:
            st.pb5_dano = 0
            shot = Circle(center=(0, 0), radius=5, group="pb5o_shot")
            e1 = Circle(center=(-6, 0), radius=4, group="pb5o_foe")
            e2 = Circle(center=(6, 0), radius=4, group="pb5o_foe")

            @collide("pb5o_shot", "pb5o_foe")
            def hit(s, f, info):
                s.destroy()

            @collide("pb5o_foe", "pb5o_shot")
            def hurt(f, s, info):
                st.pb5_dano += 1

            w.step(2, dt=1 / 60)
            self.assertFalse(shot.is_alive)
            self.assertEqual(st.pb5_dano, 1)
            e1.destroy()
            e2.destroy()

    def test_stay_handlers_of_a_contact_all_run(self):
        from scena import Circle, collide_stay
        from tests.system_support import system_world
        log = []
        with system_world(draw=False) as w:
            hero = Circle(center=(0, 0), radius=5)
            lava = Circle(center=(4, 0), radius=10)

            @collide_stay(hero, lava)
            def burn(h, l, info):
                log.append("burn")
                if len(log) > 1:
                    h.destroy()

            @collide_stay(lava, hero)
            def hiss(l, h, info):
                log.append(("hiss", h.is_alive))

            w.step(4, dt=1 / 60)
            lava.destroy()
        self.assertEqual(log, ["burn", ("hiss", True), "burn", ("hiss", False)])


class TestAContactsExitComesAfterItsHandlers(unittest.TestCase):
    """PB5 follow-up (2026-10-14): a side destroyed (or parked) by one enter
    handler of a contact gets that contact's exit after the contact's other
    handlers, so an enter / exit counter reads +1 then -1 in either order.
    Before, the exit fired inside the destroy: -1, then the remaining enter
    handler's +1 (the counter went negative and the order read exit, enter)."""

    def _zone(self, kill_first, leave="destroy"):
        from scena import Circle, collide, collide_exit, st
        from tests.system_support import system_world
        log = []
        with system_world(draw=False) as w:
            st.pb5x_inside = 0
            ball = Circle(center=(0, 0), radius=5, group="pb5x_ball")
            zone = Circle(center=(4, 0), radius=20, group="pb5x_zone")

            def kill():
                @collide("pb5x_ball", "pb5x_zone")
                def burst(b, z, info):
                    log.append("burst")
                    if leave == "destroy":
                        b.destroy()
                    else:
                        b.active = False

            def count():
                @collide("pb5x_ball", "pb5x_zone")
                def enter(b, z, info):
                    st.pb5x_inside += 1
                    log.append(("in", st.pb5x_inside))

            @collide_exit("pb5x_ball", "pb5x_zone")
            def out(b, z, info):
                st.pb5x_inside -= 1
                log.append(("out", st.pb5x_inside))

            for f in ((kill, count) if kill_first else (count, kill)):
                f()
            w.step(3, dt=1 / 60)
            inside = st.pb5x_inside
            for o in (ball, zone):
                if o.is_alive:
                    o.destroy()
        return log, inside

    def test_counter_reads_enter_then_exit_in_either_order(self):
        for kill_first in (True, False):
            with self.subTest(kill_first=kill_first):
                log, inside = self._zone(kill_first)
                self.assertEqual(inside, 0)
                self.assertEqual([e for e in log if e != "burst"], [("in", 1), ("out", 0)])

    def test_park_defers_the_exit_too(self):
        log, inside = self._zone(True, leave="park")
        self.assertEqual([e for e in log if e != "burst"], [("in", 1), ("out", 0)])

    def test_class_methods_in_either_spawn_order(self):
        from scena import Circle, collide_with, collide_with_exit, st
        from tests.system_support import system_world
        for ball_first in (True, False):
            with self.subTest(ball_first=ball_first), system_world(draw=False) as w:
                st.pb5c_inside = 0
                log = []

                class Bola(Circle, radius=5, group="pb5c_ball"):
                    @collide_with("pb5c_zone")
                    def estoura(self, zona):
                        self.destroy()

                class Zona(Circle, radius=20, group="pb5c_zone"):
                    @collide_with("pb5c_ball")
                    def entrou(self, bola):
                        st.pb5c_inside += 1
                        log.append("in")

                    @collide_with_exit("pb5c_ball")
                    def saiu(self, bola):
                        st.pb5c_inside -= 1
                        log.append("out")

                if ball_first:
                    b = Bola(center=(0, 0))
                    z = Zona(center=(4, 0))
                else:
                    z = Zona(center=(4, 0))
                    b = Bola(center=(0, 0))
                w.step(3, dt=1 / 60)
                self.assertFalse(b.is_alive)
                self.assertEqual(log, ["in", "out"])
                self.assertEqual(st.pb5c_inside, 0)
                z.destroy()

    def test_other_pairs_of_the_dying_body_exit_at_the_destroy(self):
        """Only the running contact's exit waits: the dying body's other
        open contacts exit inside the destroy, as before."""
        from scena import Circle, collide, collide_exit
        from tests.system_support import system_world
        log = []
        with system_world(draw=False) as w:
            ball = Circle(center=(0, 0), radius=5, group="pb5o_ball")
            wall = Circle(center=(-6, 0), radius=4, group="pb5o_wall")
            w.step(1, dt=1 / 60)

            @collide_exit("pb5o_ball", "pb5o_wall")
            def off_wall(b, x, info):
                log.append("wall exit")

            @collide("pb5o_ball", "pb5o_wall")
            def on_wall(b, x, info):
                log.append("wall enter")

            w.step(1, dt=1 / 60)
            spike = Circle(center=(6, 0), radius=4, group="pb5o_spike")

            @collide("pb5o_ball", "pb5o_spike")
            def pop(b, s, info):
                log.append("pop")
                b.destroy()
                log.append("after destroy")

            @collide("pb5o_ball", "pb5o_spike")
            def later(b, s, info):
                log.append("later")

            @collide_exit("pb5o_ball", "pb5o_spike")
            def off_spike(b, s, info):
                log.append("spike exit")

            w.step(1, dt=1 / 60)
            for o in (wall, spike):
                o.destroy()
        self.assertEqual(log, ["wall enter", "pop", "wall exit", "after destroy",
                               "later", "spike exit"])


class TestBounceOffAPartnerAHandlerRemoved(unittest.TestCase):
    """PE5 (2026-10-14): handlers run before resolve, so a ``bounce=`` ball
    whose ``@collide`` destroyed the brick found no brick to bounce off and
    ploughed through the wall. A resolve partner a handler of this step
    removes still gives the survivor this contact's velocity response;
    it pushes nothing."""

    def _breakout(self, dt, speed, leave="destroy"):
        from scena import Circle, Rect, STATIC, Vec2, collide, resolve
        from tests.system_support import system_world
        with system_world(draw=False) as w:
            ball = Circle(center=(0, 0), radius=5, group="pe5_ball")
            ball.vel = Vec2(0, speed)
            bricks = []
            for i in range(4):
                b = Rect(center=(0, 60 + 16 * i), width=40, height=14, group="pe5_brick")
                b.mass = STATIC
                bricks.append(b)
            floor = Rect(center=(0, -60), width=400, height=20, group="pe5_wall")
            floor.mass = STATIC
            resolve(ball, ["pe5_brick", "pe5_wall"], bounce=1.0)
            hits = []

            @collide(ball, "pe5_brick")
            def hit(me, brick, info):
                hits.append(w.frames_run)
                if leave == "destroy":
                    brick.destroy()
                else:
                    brick.active = False

            w.on_update(lambda dt_: ball.move_by(ball.vel.x * dt_, ball.vel.y * dt_))
            flips = []                             # per step with a hit
            for _ in range(int(1200.0 / speed / dt)):
                vy = ball.vel.y
                n = len(hits)
                w.step(1, dt=dt)
                if len(hits) > n:
                    flips.append(ball.vel.y * vy < 0)
            self.assertEqual(len(hits), 4, "one hit per brick, from below")
            alive = sum(1 for b in bricks if b.is_alive and b.active)
            for b in bricks + [floor]:
                if b.is_alive:
                    b.destroy()
            ball.destroy()
            return flips, alive

    def test_every_broken_brick_reflects_the_ball(self):
        for hz in (30, 60, 144):
            for speed in (300.0, 900.0):
                with self.subTest(hz=hz, speed=speed):
                    flips, alive = self._breakout(1 / hz, speed)
                    self.assertTrue(flips and all(flips), flips)
                    self.assertEqual(alive, 0)

    def test_a_brick_parked_in_the_handler_reflects_too(self):
        flips, alive = self._breakout(1 / 60, 300.0, leave="park")
        self.assertTrue(flips and all(flips), flips)
        self.assertEqual(alive, 0)

    def test_no_push_from_the_dead_brick(self):
        from scena import Circle, Rect, STATIC, Vec2, collide, resolve
        from tests.system_support import system_world
        with system_world(draw=False) as w:
            ball = Circle(center=(0, 50), radius=5, group="pe5p_ball")
            ball.vel = Vec2(0, 600)
            brick = Rect(center=(0, 67), width=40, height=14, group="pe5p_brick")
            brick.mass = STATIC
            resolve(ball, "pe5p_brick", bounce=1.0)

            @collide(ball, "pe5p_brick")
            def hit(me, b, info):
                b.destroy()

            ball.move_by(0, 10)                    # reaches the brick this frame
            w.step(1, dt=1 / 60)
            self.assertFalse(brick.is_alive)
            self.assertAlmostEqual(ball.center.y, 60.0, places=6, msg="the dead brick pushed")
            self.assertAlmostEqual(ball.vel.y, -600.0, places=6)
            ball.destroy()

    def test_bounce_zero_floor_broken_on_landing_stops_the_fall_once(self):
        """A crumbling floor destroyed on landing answers that landing as a
        live one would (``bounce=0``: the fall stops this frame); the hero is
        not lifted, and falls from rest next frame."""
        from scena import Rect, STATIC, Vec2, collide, resolve
        from tests.system_support import system_world
        with system_world(draw=False) as w:
            hero = Rect(center=(0, 25), width=10, height=10, group="pe5c_hero")
            hero.vel = Vec2(0, -300)
            floor = Rect(center=(0, 0), width=100, height=20, group="pe5c_floor")
            floor.mass = STATIC
            resolve(hero, "pe5c_floor", bounce=0.0)

            @collide(hero, "pe5c_floor")
            def crumble(h, f, info):
                f.destroy()

            hero.move_by(0, -10)                   # 5 DU above, lands this frame
            w.step(1, dt=1 / 60)
            self.assertFalse(floor.is_alive)
            self.assertAlmostEqual(hero.vel.y, 0.0, places=6)
            self.assertAlmostEqual(hero.center.y, 15.0, places=6)
            hero.destroy()

    def test_skin_contact_answers_as_the_handler_saw_it(self):
        """A resting-skin contact is touching (F1): the handler saw it, so it
        answers too (a 144 Hz ball meets a brick at the skin first)."""
        from scena import Rect, STATIC, Vec2, collide_stay, resolve
        from tests.system_support import system_world
        with system_world(draw=False) as w:
            floor = Rect(center=(0, 0), width=100, height=20, group="pe5s_floor")
            floor.mass = STATIC
            hero = Rect(center=(0, 15.12), width=10, height=10, group="pe5s_hero")
            hero.vel = Vec2(0, -1.0)
            resolve(hero, "pe5s_floor", bounce=0.0)
            w.step(1, dt=1 / 60)                   # skin contact opens (gap 0.12)
            seen = []

            @collide_stay(hero, "pe5s_floor")
            def crumble(h, f, info):
                seen.append(info.depth)
                f.destroy()

            hero.move_by(0, -0.01)                 # still in the skin
            w.step(1, dt=1 / 60)
            self.assertEqual(seen, [0.0])
            self.assertAlmostEqual(hero.vel.y, 0.0, places=9)
            hero.destroy()

    def test_a_jump_along_a_removed_wall_keeps_its_speed(self):
        """Only the approaching component answers: a hero jumping up along
        a wall a handler removes is not stopped in mid-air."""
        from scena import Rect, STATIC, Vec2, collide_stay, resolve
        from tests.system_support import system_world
        with system_world(draw=False) as w:
            wall = Rect(center=(0, 0), width=20, height=200, group="pe5j_wall")
            wall.mass = STATIC
            hero = Rect(center=(15.1, 0), width=10, height=10, group="pe5j_hero")
            hero.vel = Vec2(-1.0, 0)
            resolve(hero, "pe5j_wall", bounce=0.0)
            for _ in range(3):
                hero.move_by(-0.5, 0)
                w.step(1, dt=1 / 60)               # pressed on the wall
            self.assertIn("left", hero.touching_sides)

            @collide_stay(hero, "pe5j_wall")
            def gone(h, wl, info):
                wl.destroy()

            hero.vel = Vec2(0, 300)
            hero.move_by(0, 5)
            w.step(1, dt=1 / 60)
            self.assertFalse(wall.is_alive)
            self.assertEqual((hero.vel.x, hero.vel.y), (0.0, 300.0))
            hero.destroy()

    def test_one_way_pass_keeps_its_speed(self):
        """A one-way platform (``only="bottom"``) a body jumps up through and
        a handler destroys gives no response: it would not have blocked."""
        from scena import Rect, STATIC, Vec2, collide, resolve
        from tests.system_support import system_world
        with system_world(draw=False) as w:
            plat = Rect(center=(0, 0), width=100, height=10, group="pe5o_plat")
            plat.mass = STATIC
            hero = Rect(center=(0, -12), width=10, height=10, group="pe5o_hero")
            hero.vel = Vec2(0, 300)
            resolve(hero, "pe5o_plat", only="bottom", bounce=0.0)

            @collide(hero, "pe5o_plat")
            def poof(h, p, info):
                p.destroy()

            hero.move_by(0, 5)
            w.step(1, dt=1 / 60)
            self.assertFalse(plat.is_alive)
            self.assertAlmostEqual(hero.vel.y, 300.0, places=6)
            hero.destroy()

    def test_finite_mass_partner_splits_as_if_alive(self):
        """Equal masses, ``bounce=1``: the mover hands its speed to the box
        whether or not a handler removes the box (written on the survivor)."""
        from scena import Circle, Rect, Vec2, collide, resolve
        from tests.system_support import system_world
        out = {}
        for kill in (False, True):
            with system_world(draw=False) as w:
                ball = Circle(center=(0, 0), radius=5, group="pe5m_ball")
                ball.vel = Vec2(300, 0)
                box = Rect(center=(20, 0), width=10, height=10, group="pe5m_box")
                box.vel = Vec2(0, 0)
                resolve(ball, "pe5m_box", bounce=1.0)
                if kill:
                    @collide(ball, "pe5m_box")
                    def hit(me, b, info):
                        b.destroy()
                ball.move_by(12, 0)                # reaches the box this frame
                w.step(1, dt=1 / 60)
                out[kill] = (ball.vel.x, ball.vel.y)
                ball.destroy()
                if box.is_alive:
                    box.destroy()
        self.assertAlmostEqual(out[True][0], out[False][0], places=6)
        self.assertAlmostEqual(out[True][0], 0.0, places=6)

    def test_position_only_pair_writes_no_velocity(self):
        from scena import Circle, Rect, STATIC, Vec2, collide, resolve
        from tests.system_support import system_world
        with system_world(draw=False) as w:
            ball = Circle(center=(0, 50), radius=5, group="pe5n_ball")
            ball.vel = Vec2(0, 600)
            brick = Rect(center=(0, 67), width=40, height=14, group="pe5n_brick")
            brick.mass = STATIC
            resolve(ball, "pe5n_brick")

            @collide(ball, "pe5n_brick")
            def hit(me, b, info):
                b.destroy()

            ball.move_by(0, 10)
            w.step(1, dt=1 / 60)
            self.assertEqual((ball.vel.x, ball.vel.y), (0.0, 600.0))
            ball.destroy()


class TestParkExitSeesAParkedActor(unittest.TestCase):
    """Park leaves collision after the actor reads parked: an exit handler
    sees ``active`` False and its flag writes go to the stash (review
    2026-10-09 X-life-1)."""

    def test_exit_handler_visible_write_waits_for_resume(self):
        from scena import Circle
        from tests.system_support import system_world
        seen = []
        with system_world(draw=False) as w:
            ship = Circle(center=(0, 0), radius=10)
            lava = Circle(center=(5, 0), radius=10)
            lava.collidable = True

            def leave(me, other, info):
                seen.append(me.active)
                me.visible = True            # the blink's "be visible again"
            ship.on_collide = lambda me, other, info: None
            ship.on_collide_exit = leave
            w.step(2, dt=1 / 60)
            ship.active = False
            self.assertEqual(seen, [False])
            self.assertFalse(ship.visible, "a parked actor was left drawn")
            ship.active = True
            self.assertTrue(ship.visible)
            ship.destroy()
            lava.destroy()


class TestLeavePathsForgetWhatTheyLeave(unittest.TestCase):
    """Each way out of collision clears what the step would have cleared
    (review 2026-10-09 S8-5, S8-6, S8-8, S8-9)."""

    def _rest_on_floor(self, w):
        from scena import Circle, Rect, resolve
        floor = Rect(center=(0, -40), width=400, height=20, group="lp_floor")
        hero = Circle(center=(0, -20), radius=10, group="lp_hero")
        resolve("lp_hero", "lp_floor")
        for _ in range(20):
            hero.move_by(0, -2)
            w.step(1, dt=1 / 60)
        self.assertIn("bottom", hero.touching_sides)
        return hero, floor

    def test_touching_clears_on_park_and_opt_out(self):
        from tests.system_support import system_world
        for leave in ("park", "opt_out"):
            with self.subTest(leave), system_world(draw=False) as w:
                hero, floor = self._rest_on_floor(w)
                if leave == "park":
                    hero.active = False
                else:
                    hero.collidable = False
                self.assertEqual(set(hero.touching_sides), set())
                hero.move_to(0, -10)              # 10 DU above the floor top
                if leave == "park":
                    hero.active = True
                else:
                    hero.collidable = True
                w.step(1, dt=1 / 60)
                self.assertAlmostEqual(hero.center.y, -10.0, places=6)   # no floor snap
                hero.destroy()
                floor.destroy()

    def test_contact_memory_goes_with_the_last_resolve_pair(self):
        from scena import unresolve
        from scena.collision import get_collision_system
        from tests.system_support import system_world
        with system_world(draw=False) as w:
            hero, floor = self._rest_on_floor(w)
            unresolve("lp_hero", "lp_floor")
            w.step(1, dt=1 / 60)
            self.assertEqual(get_collision_system()._contact_memory, {})
            hero.destroy()
            floor.destroy()

    def test_compound_collider_exits_when_its_pieces_die(self):
        from scena import Circle, Collider, Rect, collide, collide_exit
        from scena.collision import get_collision_system
        from tests.system_support import system_world
        with system_world(draw=False) as w:
            a = Circle(center=(0, 0), radius=5)
            b = Circle(center=(8, 0), radius=5)
            body = Collider([a, b])
            plate = Rect(center=(0, 0), width=30, height=30)
            log = []

            @collide(plate, body)
            def on(m, o, i):
                log.append("enter")

            @collide_exit(plate, body)
            def off(m, o, i):
                log.append("exit")

            w.step(2, dt=1 / 60)
            n = len(get_collision_system()._pair_handlers)
            a.destroy()
            b.destroy()
            w.step(3, dt=1 / 60)
            self.assertEqual(log, ["enter", "exit"])
            self.assertEqual(len(get_collision_system()._pair_handlers), n - 2)
            plate.destroy()

    def test_query_after_park_does_not_use_the_last_step(self):
        from scena import Circle, Rect, collide, collision
        from tests.system_support import system_world
        with system_world(draw=False) as w:
            hero = Circle(center=(0, 0), radius=10)
            wall = Rect(center=(100, 0), width=10, height=10)

            @collide(hero, wall)
            def hit(h, x, i):
                pass

            w.step(2, dt=1 / 60)
            hero.active = False
            self.assertEqual(collision.query_point((0, 0), group=hero), [])
            hero.destroy()
            wall.destroy()
