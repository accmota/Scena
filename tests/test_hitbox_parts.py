"""Hitbox parts: ``sprite.add_hitbox(...)`` detection-only colliders.

Run headless:

    python -m unittest tests.test_hitbox_parts -v
"""

import json
import math
import unittest

from scena import (
    ANYTHING, Circle, Hitbox, Rect, Sheet, Sprite, Svg, collide,
    collide_exit, group, resolve,
)
from scena.collision import (
    STATIC, TouchingContact, get_collision_system, collision,
)
from scena.shapes import get_xy
from scena.scenamath import Vec2
from scena.state import DestroyedError

from tests.test_sprite import (
    SpriteTestCase,
    _frame,
    _write_blob_strip,
    _write_padded_png,
    _write_rect_png,
)


# 64×64 canvas, 16×48 opaque bar in the middle: the silhouette is x∈[-8, 8],
# y∈[-24, 24] about the centre at 1 px = 1 design unit.
_BAR = (24, 8, 16, 48)


class PartTestCase(SpriteTestCase):
    _origin = 0

    def setUp(self):
        super().setUp()
        PartTestCase._origin += 5000
        self.origin = PartTestCase._origin

    def at(self, x, y):
        return (self.origin + x, self.origin + y)

    def step(self):
        get_collision_system().step()

    def bar_png(self, name="bar.png", blob=_BAR):
        path = self.tmp(name)
        _write_padded_png(path, canvas_w=64, canvas_h=64, blob=blob)
        return path

    def hero(self, *, group="hero", body_scale=(3.0, 1.0), **kw):
        """Wide body rect (x∈[-24, 24]) around the thin bar silhouette."""
        return self.track(Sprite(
            self.bar_png(), center=self.at(0, 0), width=64, height=64,
            group=group, hitbox_shape="rect", hitbox_scale=body_scale, **kw,
        ))

    def dot(self, x, y, *, group="bullet", r=2.0):
        return self.track(Circle(center=self.at(x, y), radius=r, group=group))


def _spec_bounds(specs):
    xs, ys = [], []
    for spec in specs:
        kind = spec[0]
        if kind == "aabb":
            xs += [spec[1], spec[3]]
            ys += [spec[2], spec[4]]
        elif kind == "poly":
            xs += [p[0] for p in spec[1]]
            ys += [p[1] for p in spec[1]]
        elif kind == "obb":
            _k, cx, cy, hw, hh, ang = spec
            c, s = math.cos(ang), math.sin(ang)
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                xs.append(cx + sx * hw * c - sy * hh * s)
                ys.append(cy + sx * hw * s + sy * hh * c)
        elif kind == "circle":
            xs += [spec[1] - spec[3], spec[1] + spec[3]]
            ys += [spec[2] - spec[3], spec[2] + spec[3]]
        elif kind == "ellipse":
            r = max(spec[3], spec[4])
            xs += [spec[1] - r, spec[1] + r]
            ys += [spec[2] - r, spec[2] + r]
    return min(xs), min(ys), max(xs), max(ys)


class TestAddHitboxApi(PartTestCase):
    def test_defaults_and_listing(self):
        s = self.hero()
        hb = s.add_hitbox()
        self.assertIsInstance(hb, Hitbox)
        self.assertEqual(hb.shape, "auto")
        self.assertEqual(hb.source, "each")
        self.assertEqual(hb.anchor, "center")
        self.assertEqual(hb.scale, (1.0, 1.0))
        self.assertTrue(hb.active)
        self.assertIs(hb.host, s)
        self.assertTrue(hb.is_alive)
        self.assertEqual(hb.group, frozenset())
        self.assertEqual(s.hitboxes, (s.hitbox, hb))   # main first, then parts

    def test_unknown_kwarg_raises(self):
        s = self.hero()
        with self.assertRaises(TypeError):
            s.add_hitbox(frames=(1, 2))
        with self.assertRaises(TypeError):
            s.add_hitbox("hurt")  # keyword-only

    def test_direct_construct_raises(self):
        with self.assertRaises(TypeError) as cm:
            Hitbox()
        self.assertIn("add_hitbox", str(cm.exception))

    def test_knobs_reuse_sprite_validation(self):
        s = self.hero()
        with self.assertRaises(ValueError):
            s.add_hitbox(shape="square")
        with self.assertRaises(TypeError):
            s.add_hitbox(shape=0.9)
        with self.assertRaises(ValueError):
            s.add_hitbox(source="nope")
        with self.assertRaises(ValueError):
            s.add_hitbox(scale=-1)
        with self.assertRaises((TypeError, ValueError)):
            s.add_hitbox(anchor="middle")
        with self.assertRaises(TypeError):
            s.add_hitbox(group=3)
        self.assertEqual(s.hitboxes, (s.hitbox,))

    def test_live_knobs(self):
        s = self.hero()
        hb = s.add_hitbox(shape="rect")
        hb.shape = "hull"
        self.assertEqual(hb.shape, "hull")
        hb.source = "all"
        self.assertEqual(hb.source, "all")
        hb.scale = 0.5
        self.assertEqual(hb.scale, (0.5, 0.5))
        hb.anchor = "bottom"
        self.assertEqual(hb.anchor, "bottom")

    def test_remove_hitbox(self):
        s = self.hero()
        hb = s.add_hitbox(group="hurt")
        self.assertTrue(s.tagged("hurt"))
        s.remove_hitbox(hb)
        self.assertEqual(s.hitboxes, (s.hitbox,))
        self.assertFalse(hb.is_alive)
        self.assertIsNone(hb.host)
        self.assertFalse(s.tagged("hurt"))
        with self.assertRaises(ValueError):
            s.remove_hitbox(hb)

    def test_remove_hitbox_keeps_the_hosts_own_groups(self):
        """HP13 (decision 5): the host leaves only the groups the part's claim
        added. Removing a weak spot took the boss out of "enemy"."""
        boss = self.hero(group="enemy")
        spot = boss.add_hitbox(group=["enemy", "weak"])
        self.assertEqual(set(boss.group), {"enemy", "weak"})
        boss.remove_hitbox(spot)
        self.assertEqual(set(boss.group), {"enemy"})
        # The same rule on the part's own verb.
        spot = boss.add_hitbox(group=["enemy", "weak"])
        spot.remove_from_group("enemy")
        spot.remove_from_group("weak")
        self.assertEqual(set(boss.group), {"enemy"})

    def test_remove_hitbox_on_a_destroyed_sprite_raises(self):
        """HP12: it returned silently."""
        s = self.hero()
        hb = s.add_hitbox(group="hurt")
        s.destroy()
        with self.assertRaises(DestroyedError):
            s.remove_hitbox(hb)

    def test_hitboxes_is_read_only(self):
        s = self.hero()
        with self.assertRaises(AttributeError):
            s.hitboxes = ()

    def test_svg_host(self):
        svg = self.track(Svg(
            '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32">'
            '<rect x="8" y="8" width="16" height="16" fill="red"/></svg>',
            center=self.at(0, 0), size=32,
        ))
        hb = svg.add_hitbox(group="hurt")
        self.assertTrue(hb._collision_specs())
        svg.svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32">'
            '<rect x="0" y="0" width="32" height="32" fill="red"/></svg>'
        )
        self.assertFalse(hb._auto_baked)


class TestHitboxGroups(PartTestCase):
    def test_host_joins_claimed_group(self):
        s = self.hero()
        hb = s.add_hitbox(group="hurt")
        self.assertTrue(s.tagged("hurt"))
        self.assertIn(s, group["hurt"])
        self.assertEqual(len(group["hurt"]), 1)
        self.assertEqual(hb.group, frozenset({"hurt"}))
        self.assertTrue(hb.tagged("hurt"))

    def test_claim_routes_tag_to_part_and_body_keeps_its_groups(self):
        s = self.hero()
        s.add_hitbox(group="hurt")
        log = []

        @collide("bullet", "hurt")
        def _hurt(b, target, info):
            log.append("hurt")

        @collide("bullet", "hero")
        def _body(b, target, info):
            log.append("body")

        # Inside the wide body rect, outside the thin silhouette.
        b = self.dot(16, 0)
        self.step()
        self.assertEqual(log, ["body"])
        log.clear()
        b.center = self.at(0, 0)  # still on the body (stay); now on the part
        self.step()
        self.assertEqual(log, ["hurt"])

    def test_body_colliders_skip_claimed_tags(self):
        s = self.hero()
        s.add_hitbox(group="hurt")

        @collide("bullet", "hurt")
        def _hurt(b, target, info):
            pass

        sys = get_collision_system()
        members = sys._tag_colliders.get("hurt") or ()
        self.assertEqual(len(members), 1)
        self.assertIsNotNone(members[0]._part)
        self.assertNotIn("hurt", s._collider._group_tags())

    def test_two_parts_same_group_raise(self):
        s = self.hero()
        s.add_hitbox(group="hurt")
        with self.assertRaises(TypeError):
            s.add_hitbox(group="hurt")
        other = s.add_hitbox(group="weak")
        with self.assertRaises(TypeError):
            other.add_to_group("hurt")

    def test_untag_host_toggles_part_and_keeps_claim(self):
        s = self.hero()
        hb = s.add_hitbox(group="hurt")
        hits = []

        @collide("bullet", "hurt")
        def _hurt(b, target, info):
            hits.append(target)

        b = self.dot(0, 0)
        self.step()
        self.assertEqual(hits, [s])
        hits.clear()
        s.untag("hurt")  # invulnerability window
        b.center = self.at(200, 0)
        self.step()
        b.center = self.at(0, 0)
        self.step()
        self.assertEqual(hits, [])
        self.assertTrue(hb.tagged("hurt"))
        s.tag("hurt")
        b.center = self.at(200, 0)
        self.step()
        b.center = self.at(0, 0)
        self.step()
        self.assertEqual(hits, [s])

    def test_hitbox_group_verbs(self):
        s = self.hero()
        hb = s.add_hitbox()
        hb.add_to_group("weak")
        self.assertTrue(s.tagged("weak"))
        self.assertEqual(hb.group, frozenset({"weak"}))
        hb.tag("hurt", "soft")
        self.assertTrue(s.tagged("soft"))
        hb.untag("soft")
        self.assertFalse(s.tagged("soft"))
        hb.remove_from_group("weak")
        self.assertFalse(s.tagged("weak"))
        self.assertEqual(hb.group, frozenset({"hurt"}))
        with self.assertRaises(TypeError):
            hb.add_to_group("")

    def test_claiming_a_group_the_body_answered_moves_it(self):
        s = self.hero(group=("hero", "hurt"))
        hits = []

        @collide("bullet", "hurt")
        def _hurt(b, target, info):
            hits.append(info.b_hitbox)

        b = self.dot(16, 0)  # body only
        self.step()
        self.assertEqual(hits, [None])
        hits.clear()
        hb = s.add_hitbox(group="hurt")
        b.center = self.at(200, 0)
        self.step()
        b.center = self.at(16, 0)
        self.step()
        self.assertEqual(hits, [])
        b.center = self.at(0, 0)
        self.step()
        self.assertEqual(hits, [hb])


class TestHitboxDispatch(PartTestCase):
    def test_handler_gets_host_and_part_in_info(self):
        s = self.hero()
        hb = s.add_hitbox(group="hurt")
        got = []

        @collide("bullet", "hurt")
        def _hurt(b, target, info):
            got.append((target, info.a_hitbox, info.b_hitbox))

        @collide("hurt", "bullet")
        def _hurt_left(me, b, info):
            got.append((me, info.a_hitbox, info.b_hitbox))

        self.dot(0, 0)
        self.step()
        self.assertIn((s, None, hb), got)
        self.assertIn((s, hb, None), got)

    def test_part_vs_part_across_hosts_and_same_host_skipped(self):
        a = self.hero(group="fighter_a")
        b = self.track(Sprite(
            self.bar_png("b.png"), center=self.at(4, 0), width=64, height=64,
            group="fighter_b", hitbox_shape="rect",
        ))
        a_fist = a.add_hitbox(group="attack", shape="rect")
        a.add_hitbox(group="hurt")
        b.add_hitbox(group="hurt")
        hits = []

        @collide("attack", "hurt")
        def _hit(attacker, victim, info):
            hits.append((attacker, victim, info.a_hitbox))

        self.step()
        self.assertEqual(hits, [(a, b, a_fist)])

    def test_naming_the_sprite_means_the_body(self):
        s = self.hero()
        s.add_hitbox(group="hurt")
        seen = []
        bullet = self.dot(0, 0)

        @collide(bullet, s)
        def _obj(b, target, info):
            seen.append(("obj", info.b_hitbox))

        @collide("bullet", "hurt")
        def _hurt(b, target, info):
            seen.append(("hurt", info.b_hitbox is not None))

        bullet.on_collide = lambda me, other, info: seen.append(("cb", info.b_hitbox))
        self.step()
        self.assertEqual(seen.count(("obj", None)), 1)
        self.assertEqual(seen.count(("cb", None)), 1)
        self.assertEqual(seen.count(("hurt", True)), 1)
        self.assertEqual(len(seen), 3)

    def test_anything_side_means_bodies(self):
        s = self.hero()
        s.add_hitbox(group="hurt")
        seen = []

        @collide("bullet", ANYTHING)
        def _any(b, other, info):
            seen.append(info.b_hitbox)

        @collide("bullet", "hurt")
        def _hurt(b, target, info):
            pass

        self.dot(0, 0)
        self.step()
        self.assertEqual(seen, [None])

    def test_hitbox_object_as_side(self):
        s = self.hero()
        hb = s.add_hitbox()
        seen = []

        @collide("bullet", hb)
        def _hit(b, target, info):
            seen.append((target, info.b_hitbox))

        self.dot(0, 0)
        self.step()
        self.assertEqual(seen, [(s, hb)])

    def test_part_is_a_filled_region(self):
        # Track(sprite) collided as a ring: a blast covering the hero missed.
        s = self.hero()
        s.add_hitbox(group="hurt")
        hits = []

        @collide("blast", "hurt")
        def _hit(blast, target, info):
            hits.append(target)

        self.track(Circle(center=self.at(0, 0), radius=200, group="blast"))
        self.step()
        self.assertEqual(hits, [s])


class TestHitboxDetectsOnly(PartTestCase):
    def test_resolve_refuses_a_hitbox_side(self):
        s = self.hero()
        hb = s.add_hitbox(group="hurt")
        with self.assertRaises(TypeError):
            resolve(hb, "floor")
        with self.assertRaises(TypeError):
            resolve("floor", hb)
        with self.assertRaises(TypeError):
            resolve(["bullet"], ["floor", hb])  # all-or-nothing
        self.assertEqual(get_collision_system()._resolve_pairs, [])
        # A group a part claims is a legal side: resolve moves the bodies.
        resolve("bullet", "hurt")
        self.assertEqual(len(get_collision_system()._resolve_pairs), 1)

    def test_claiming_a_resolve_side_is_allowed(self):
        s = self.hero()
        resolve("crate", "floor")
        hb = s.add_hitbox(group="floor")
        hb.add_to_group("crate")
        self.assertEqual(hb.group, frozenset({"floor", "crate"}))
        sys = get_collision_system()
        self.assertTrue(sys._collider_in_resolve(s._collider))
        self.assertFalse(sys._collider_in_resolve(hb._collider))

    def test_manual_resolution_on_a_part_contact_raises(self):
        s = self.hero()
        s.add_hitbox(group="hurt")
        infos = []

        @collide("bullet", "hurt")
        def _hurt(b, target, info):
            infos.append(info)

        self.dot(0, 0)
        self.step()
        self.assertEqual(len(infos), 1)
        info = infos[0]
        self.assertIsNotNone(info.point)
        for call in (info.push_apart, info.bounce_apart, info.resolve):
            with self.assertRaises(TypeError):
                call()

    def test_resolve_now_skips_own_parts_and_resolves_claimed_bodies(self):
        s = self.hero()
        s.add_hitbox(group="hurt")
        before = get_xy(s.center, bare=True)
        self.assertEqual(s.resolve_now(ANYTHING), [])
        self.assertEqual(get_xy(s.center, bare=True), before)
        other = self.hero(group="villain")
        other.add_hitbox(group="enemy_hurt")

        @collide("bullet", "enemy_hurt")
        def _hit(b, target, info):
            pass

        # A claimed group resolves against the members' bodies, not the part.
        hits = s.resolve_now("enemy_hurt")
        self.assertEqual(len(hits), 1)
        self.assertIs(hits[0].b, other)
        self.assertIsNone(hits[0].b_hitbox)
        self.assertNotEqual(get_xy(s.center, bare=True), before)
        with self.assertRaises(TypeError):
            s.resolve_now(other.hitboxes[1])

    def test_walker_rect_resolves_while_part_detects(self):
        path = self.tmp("hero.png")
        _write_rect_png(path, 32, 48)
        hero = self.track(Sprite(
            path, center=self.at(0, 40), width=32, height=48,
            hitbox_shape="rect", hitbox_anchor="bottom", group="hero",
        ))
        hero.mass = 1.0
        hurt = hero.add_hitbox(group="hurt")
        floor = self.track(Rect(center=self.at(0, 0), width=220, height=16, group="floor"))
        floor.mass = STATIC
        floor.collidable = True
        resolve("hero", "floor", bounce=0.0)
        hits = []

        @collide("sting", "hurt")
        def _hit(sting, target, info):
            hits.append(info.b_hitbox)

        hero.vel = Vec2(0, -240)
        for _ in range(24):
            hero.move_by(0, float(hero.vel.y) * 0.016)
            self.step()
        # The part's collider shares the host identity: it must not wipe
        # the body's touching_* (regression guard).
        self.assertIn("bottom", hero.touching_sides)
        rect_fp = hero._collision_specs()
        self.track(Circle(center=get_xy(hero.center, bare=True), radius=4, group="sting"))
        self.step()
        self.assertEqual(hits, [hurt])
        self.assertIn("bottom", hero.touching_sides)
        self.assertEqual(hero._collision_specs(), rect_fp)
        sys = get_collision_system()
        self.assertTrue(sys._collider_in_resolve(hero._collider))
        self.assertFalse(sys._collider_in_resolve(hurt._collider))


class TestResolveUsesBodies(PartTestCase):
    """``resolve()`` on a group moves its members' bodies, even when a
    hitbox part answers that group for ``@collide`` (boss weak spot)."""

    def _scene(self, *, resolve_first=False, claim_late=False):
        floor = self.track(Rect(center=self.at(0, 0), width=600, height=16, group="floor"))
        floor.mass = STATIC
        floor.collidable = True
        if resolve_first:
            resolve("enemy", "floor", bounce=0.0)
        boss = self.track(Sprite(
            self.bar_png("boss.png"), center=self.at(0, 60), width=64, height=64,
            group="boss", hitbox_shape="rect", hitbox_scale=(3.0, 1.0), hitbox_anchor="bottom",
        ))
        boss.mass = 1.0
        weak = boss.add_hitbox() if claim_late else boss.add_hitbox(group="enemy")
        wasp = self.track(Sprite(
            self.bar_png("wasp.png"), center=self.at(200, 60), width=64, height=64,
            group="enemy", hitbox_shape="rect",
        ))
        wasp.mass = 1.0
        if not resolve_first:
            resolve("enemy", "floor", bounce=0.0)
        if claim_late:
            weak.add_to_group("enemy")
        return floor, boss, weak, wasp

    def _fall(self, *bodies, frames=30):
        for b in bodies:
            b.vel = Vec2(0, -240)
        for _ in range(frames):
            for b in bodies:
                b.move_by(0, float(b.vel.y) * 0.016)
            self.step()

    def test_weak_spot_boss_and_wasp_stand_and_detect(self):
        floor, boss, weak, wasp = self._scene()
        hits = []

        @collide("bullet", "enemy")
        def _hit(b, target, info):
            hits.append((target, info.b_hitbox))

        self._fall(boss, wasp)
        self.assertIn("bottom", boss.touching_sides)
        self.assertIn("bottom", wasp.touching_sides)
        by = get_xy(boss.center, bare=True)[1]
        self.dot(16, by - self.origin)  # boss body only: not the weak spot
        self.step()
        self.assertEqual(hits, [])
        self.dot(0, by - self.origin)   # the weak spot
        wy = get_xy(wasp.center, bare=True)[1]
        self.dot(200, wy - self.origin)  # a wasp body
        self.step()
        self.assertIn((boss, weak), hits)
        self.assertIn((wasp, None), hits)
        sys = get_collision_system()
        self.assertEqual(sys._resolve_bounce_for(boss._collider, floor._collider), 0.0)

    def test_order_independent(self):
        for kw in ({"resolve_first": True}, {"claim_late": True}):
            reset = get_collision_system()
            floor, boss, weak, wasp = self._scene(**kw)
            self._fall(boss, wasp)
            self.assertIn("bottom", boss.touching_sides, kw)
            self.assertIn(boss._collider, reset._resolve_side_colliders("enemy"))
            self.assertNotIn(weak._collider, reset._resolve_side_colliders("enemy"))
            for obj in (floor, boss, wasp):
                obj.destroy()
            from scena.collision import reset_collision_system
            reset_collision_system()

    def test_inactive_part_keeps_the_body_standing(self):
        _floor, boss, weak, wasp = self._scene()
        weak.active = False
        self._fall(boss, wasp)
        self.assertIn("bottom", boss.touching_sides)

    def test_untag_leaves_detection_and_resolution(self):
        _floor, boss, _weak, _wasp = self._scene()
        boss.untag("enemy")
        sys = get_collision_system()
        self.assertNotIn(boss._collider, sys._resolve_side_colliders("enemy"))
        self.assertFalse(sys._collider_in_resolve(boss._collider))
        boss.tag("enemy")
        self.assertIn(boss._collider, sys._resolve_side_colliders("enemy"))

    def test_unresolve_and_remove_hitbox_clean_up(self):
        from scena import unresolve
        _floor, boss, weak, _wasp = self._scene()
        sys = get_collision_system()
        self.assertIn("enemy", sys._claimed_bodies)
        unresolve("enemy", "floor")
        self.assertNotIn("enemy", sys._claimed_bodies)
        self.assertFalse(sys._collider_in_resolve(boss._collider))
        resolve("enemy", "floor")
        self.assertIn("enemy", sys._claimed_bodies)
        boss.remove_hitbox(weak)
        self.assertNotIn(boss._collider, sys._claimed_bodies.get("enemy", ()))

    def test_body_is_gold_part_never(self):
        _floor, boss, weak, _wasp = self._scene()
        sys = get_collision_system()
        self.assertTrue(sys._collider_in_resolve(boss._collider))
        self.assertFalse(sys._collider_in_resolve(weak._collider))


class TestHitboxFollowsPaint(PartTestCase):
    def _rect_part(self, **kw):
        path = self.tmp("r.png")
        _write_rect_png(path, 32, 16)
        s = self.track(Sprite(
            path, center=self.at(0, 0), width=64, height=32, hitbox_shape="rect", **kw,
        ))
        return s, s.add_hitbox(shape="rect")

    def _assert_matches_paint(self, s, hb):
        """Part corners are the painted design-box corners (opaque cell)."""
        want = sorted((round(x, 4), round(y, 4)) for x, y in s._design_box_world_verts())
        got = sorted((round(x, 4), round(y, 4)) for x, y in _corner_points(hb._collision_specs()))
        self.assertEqual(got, want)

    def test_flip_rotation_scale_offset_tilt_follow_the_paint(self):
        cases = (
            {},
            {"flip_x": True},
            {"flip_y": True},
            {"offset": (6, 3)},
            {"offset": (6, 3), "flip_x": True},
        )
        for kw in cases:
            s, hb = self._rect_part(hitbox_anchor=(0.5, -1.0), **kw)
            self._assert_matches_paint(s, hb)
            s.angle = 30
            self._assert_matches_paint(s, hb)
            s.scale = 1.5
            self._assert_matches_paint(s, hb)
            s.tilt = 25
            self._assert_matches_paint(s, hb)
            s.destroy()

    def test_tilt_moves_the_part_not_the_body(self):
        s, hb = self._rect_part(hitbox_anchor="bottom")
        body0 = s._collision_specs()
        part0 = hb._collision_specs()
        s.tilt = 30
        self.assertEqual(s._collision_specs(), body0)
        self.assertNotEqual(hb._collision_specs(), part0)
        self._assert_matches_paint(s, hb)

    def test_contact_tilt_seat_moves_the_part(self):
        s, hb = self._rect_part(hitbox_anchor="bottom")
        n = Vec2(-math.sin(math.radians(20)), math.cos(math.radians(20)))
        cx, cy = get_xy(s.center, bare=True)
        contact = TouchingContact(
            other=None, side="bottom", slope_angle=20.0,
            normal=n, tangent=Vec2(n.y, -n.x), point=(cx + 10, cy - 24),
        )
        s.tilt = contact
        seat = s._tilt_seat_local(cx, cy)
        self.assertGreater(math.hypot(*seat), 1e-3)
        self._assert_matches_paint(s, hb)

    def test_each_follows_the_current_cell(self):
        path = self.tmp("strip.png")
        _write_blob_strip(path, cell=32)
        sheet = Sheet(path, cols=4, fps=8)
        s = self.track(Sprite(
            sheet, center=self.at(0, 0), size=32, hitbox_shape="rect", hitbox_source="all",
        ))
        hb = s.add_hitbox(shape="rect")
        body = s._collision_specs()
        seen = set()
        for _ in range(4):
            seen.add(tuple(round(v, 3) for v in _spec_bounds(hb._collision_specs())))
            self.assertEqual(s._collision_specs(), body)
            _frame(0.125)
            self.step()
        self.assertGreaterEqual(len(seen), 3)

    def test_still_frame_write_rebakes_each(self):
        path = self.tmp("strip.png")
        _write_blob_strip(path, cell=32)
        sheet = Sheet(path, cols=4)
        s = self.track(Sprite(sheet, center=self.at(0, 0), size=32, frame=0))
        hb = s.add_hitbox(shape="rect")
        b0 = _spec_bounds(hb._collision_specs())
        s.frame = 1
        b1 = _spec_bounds(hb._collision_specs())
        self.assertNotEqual(b0, b1)


def _corner_points(specs):
    pts = []
    for spec in specs:
        kind = spec[0]
        if kind == "aabb":
            _k, x0, y0, x1, y1 = spec
            pts += [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        elif kind == "poly":
            pts += list(spec[1])
        elif kind == "obb":
            _k, cx, cy, hw, hh, ang = spec
            c, s = math.cos(ang), math.sin(ang)
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                pts.append((cx + sx * hw * c - sy * hh * s, cy + sx * hw * s + sy * hh * c))
    return pts


class TestPartProxyConservative(PartTestCase):
    """The cheap part proxy (body extents placed by paint) never under-covers."""

    def test_proxy_contains_every_prim(self):
        from scena.collision import _prims_from_collision_specs, _proxy_aabb_for_shape

        path = self.tmp("strip.png")
        _write_blob_strip(path, cell=32)
        sheet = Sheet(path, cols=4)
        eps = 1e-6
        checked = 0
        for kind in ("auto", "rect", "circle", "ellipse", "hull"):
            for flips in ((False, False), (True, False), (False, True), (True, True)):
                s = self.track(Sprite(
                    sheet, center=self.at(0, 0), width=40, height=56, frame=0,
                    flip_x=flips[0], flip_y=flips[1], offset=(5, -3),
                    hitbox_shape="rect", hitbox_anchor="bottom",
                ))
                hb = s.add_hitbox(shape=kind, scale=(1.3, 0.8),
                                  anchor=(0.4, -0.6))
                for frame in range(4):
                    s.frame = frame
                    for rot in (0, 33, 90, 147):
                        s.angle = rot
                        for tilt in (0, 17, -40):
                            s.tilt = tilt
                            proxy = _proxy_aabb_for_shape(hb)
                            prims = _prims_from_collision_specs(hb._collision_specs())
                            self.assertIsNotNone(proxy)
                            for prim in prims:
                                a = prim.aabb
                                msg = (kind, flips, frame, rot, tilt, a, proxy)
                                self.assertLessEqual(proxy[0], a[0] + eps, msg)
                                self.assertLessEqual(proxy[1], a[1] + eps, msg)
                                self.assertGreaterEqual(proxy[2], a[2] - eps, msg)
                                self.assertGreaterEqual(proxy[3], a[3] - eps, msg)
                                checked += 1
                # Contact seat moves the paint too.
                n = Vec2(-math.sin(math.radians(20)), math.cos(math.radians(20)))
                cx, cy = get_xy(s.center, bare=True)
                s.tilt = TouchingContact(other=None, side="bottom", slope_angle=20.0,
                                         normal=n, tangent=Vec2(n.y, -n.x),
                                         point=(cx + 7, cy - 40))
                proxy = _proxy_aabb_for_shape(hb)
                for prim in _prims_from_collision_specs(hb._collision_specs()):
                    a = prim.aabb
                    self.assertLessEqual(proxy[0], a[0] + eps)
                    self.assertGreaterEqual(proxy[2], a[2] - eps)
                    self.assertLessEqual(proxy[1], a[1] + eps)
                    self.assertGreaterEqual(proxy[3], a[3] - eps)
                s.destroy()
        self.assertGreater(checked, 500)

    def test_empty_bake_has_no_proxy(self):
        from scena.collision import _proxy_aabb_for_shape

        path = self.tmp("clear.png")
        _write_padded_png(path, canvas_w=32, canvas_h=32, blob=(0, 0, 0, 0))
        s = self.track(Sprite(path, center=self.at(0, 0), size=32))
        hb = s.add_hitbox()
        self.assertIsNone(_proxy_aabb_for_shape(hb))


class TestHitboxDebugColors(PartTestCase):
    def test_show_colliders_legend(self):
        from scena.collision import (
            _DEBUG_DETECT_RGBA, _DEBUG_PART_RGBA, _DEBUG_RESOLVE_RGBA,
        )
        s = self.hero()
        hurt = s.add_hitbox(group="hurt")
        floor = self.track(Rect(center=self.at(0, -60), width=200, height=10, group="floor"))

        @collide("bullet", "hurt")
        def _hurt(b, target, info):
            pass

        sys = get_collision_system()
        self.assertEqual(sys._debug_color_for(s._collider), _DEBUG_DETECT_RGBA)
        resolve("hero", "floor")
        self.assertEqual(sys._debug_color_for(s._collider), _DEBUG_RESOLVE_RGBA)
        self.assertEqual(sys._debug_color_for(hurt._collider), _DEBUG_PART_RGBA)
        self.assertEqual(len({_DEBUG_DETECT_RGBA, _DEBUG_PART_RGBA, _DEBUG_RESOLVE_RGBA}), 3)
        self.assertIsNotNone(floor._collider)


class TestHitboxAtlasBoxes(PartTestCase):
    def _sheet(self):
        png = self.tmp("fighter.png")
        _write_rect_png(png, 64, 16)
        atlas = self.tmp("fighter.json")
        with open(atlas, "w", encoding="utf-8") as f:
            json.dump({"frames": [
                {"filename": "idle", "frame": {"x": 0, "y": 0, "w": 32, "h": 16}},
                {"filename": "punch", "frame": {"x": 32, "y": 0, "w": 32, "h": 16},
                 "hitboxes": [{"x": 20, "y": 2, "w": 12, "h": 12}]},
            ]}, f)
        return Sheet(png, atlas=atlas)

    def test_atlas_boxes_feed_auto_bakes_only(self):
        # Authored boxes are per sprite, not per part: every "auto" bake uses
        # them; an explicit kind ignores them (docs: Sprite Design, Hitbox parts).
        sheet = self._sheet()
        body_rect = self.track(Sprite(sheet, frame="punch", center=self.at(0, 0),
                                      width=32, height=16, hitbox_shape="rect"))
        fist = body_rect.add_hitbox(group="attack")
        bx0, by0, bx1, by1 = _spec_bounds(body_rect._collision_specs())
        self.assertAlmostEqual(bx1 - bx0, 32.0, places=3)  # whole cell
        fx0, fy0, fx1, fy1 = _spec_bounds(fist._collision_specs())
        self.assertAlmostEqual(fx1 - fx0, 12.0, places=3)  # the authored box
        self.assertAlmostEqual(fy1 - fy0, 12.0, places=3)
        body_auto = self.track(Sprite(sheet, frame="punch", center=self.at(100, 0),
                                      width=32, height=16))
        ax0, _ay0, ax1, _ay1 = _spec_bounds(body_auto._collision_specs())
        self.assertAlmostEqual(ax1 - ax0, 12.0, places=3)  # the body takes it too


class TestHitboxEmptyBake(PartTestCase):
    def test_transparent_art_means_no_part(self):
        path = self.tmp("clear.png")
        _write_padded_png(path, canvas_w=32, canvas_h=32, blob=(0, 0, 0, 0))
        s = self.track(Sprite(path, center=self.at(0, 0), size=32, group="hero"))
        s.add_hitbox(group="hurt")
        hits = []

        @collide("bullet", "hurt")
        def _hurt(b, target, info):
            hits.append("hurt")

        @collide("bullet", "hero")
        def _body(b, target, info):
            hits.append("body")

        self.assertEqual(s.hitboxes[1]._collision_specs(), [])
        self.dot(0, 0)
        self.step()
        # The body keeps its design-box fallback; the part has nothing.
        self.assertEqual(hits, ["body"])

    def test_part_appears_and_disappears_with_the_cell(self):
        path = self.tmp("blink.png")
        _write_blob_strip(path, cell=32, blobs=((4, 4, 24, 24), (0, 0, 0, 0)))
        sheet = Sheet(path, cols=2)
        s = self.track(Sprite(sheet, center=self.at(0, 0), size=32, frame=0))
        s.add_hitbox(group="hurt")
        log = []

        @collide("bullet", "hurt")
        def _enter(b, target, info):
            log.append("enter")

        @collide_exit("bullet", "hurt")
        def _exit(b, target, info):
            log.append("exit")

        self.dot(0, 0)
        self.step()
        self.assertEqual(log, ["enter"])
        s.frame = 1
        self.step()
        self.assertEqual(log, ["enter", "exit"])
        s.frame = 0
        self.step()
        self.assertEqual(log, ["enter", "exit", "enter"])


class TestHitboxLifetime(PartTestCase):
    def test_destroy_fires_exit_and_kills_parts(self):
        s = self.hero()
        hb = s.add_hitbox(group="hurt")
        log = []

        @collide("bullet", "hurt")
        def _enter(b, target, info):
            log.append("enter")

        @collide_exit("bullet", "hurt")
        def _exit(b, target, info):
            log.append(("exit", target is s))

        @collide("bullet", hb)
        def _obj(b, target, info):
            pass

        self.dot(0, 0)
        self.step()
        n_handlers = len(get_collision_system()._pair_handlers)
        s.destroy()
        self.assertIn(("exit", True), log)
        self.assertFalse(hb.is_alive)
        self.assertIsNone(hb.host)
        self.assertIsNone(hb._collider)
        # Handlers naming the dead part go with its host.
        self.assertEqual(len(get_collision_system()._pair_handlers), n_handlers - 1)
        self.step()
        from scena.state import DestroyedError
        with self.assertRaises(DestroyedError):     # every write on a dead hitbox
            hb.source = "all"

    def test_park_and_resume(self):
        s = self.hero()
        s.add_hitbox(group="hurt")
        log = []

        @collide("bullet", "hurt")
        def _enter(b, target, info):
            log.append("enter")

        @collide_exit("bullet", "hurt")
        def _exit(b, target, info):
            log.append("exit")

        self.dot(0, 0)
        self.step()
        s.active = False
        self.step()
        self.assertEqual(log, ["enter", "exit"])
        s.active = True
        self.step()
        self.assertEqual(log, ["enter", "exit", "enter"])

    def test_host_collidable_false_switches_off_everything(self):
        s = self.hero()
        s.add_hitbox(group="hurt")
        log = []

        @collide("bullet", ["hurt", "hero"])
        def _hit(b, target, info):
            log.append(info.b_hitbox is None)

        self.dot(0, 0)
        s.collidable = False
        self.step()
        self.assertEqual(log, [])
        s.collidable = True
        self.step()
        self.assertCountEqual(log, [True, False])

    def test_hitbox_active_switch(self):
        s = self.hero()
        hb = s.add_hitbox(group="hurt")
        log = []

        @collide("bullet", "hurt")
        def _enter(b, target, info):
            log.append("enter")

        @collide_exit("bullet", "hurt")
        def _exit(b, target, info):
            log.append("exit")

        self.dot(0, 0)
        self.step()
        hb.active = False
        self.assertEqual(log, ["enter", "exit"])
        self.step()
        self.assertEqual(log, ["enter", "exit"])
        hb.active = True
        self.step()
        self.assertEqual(log, ["enter", "exit", "enter"])

    def test_inactive_part_does_not_hand_its_group_to_the_body(self):
        s = self.hero()
        s.add_hitbox(group="hurt", active=False)
        log = []

        @collide("bullet", "hurt")
        def _hurt(b, target, info):
            log.append(info.b_hitbox)

        self.dot(16, 0)
        self.step()
        self.dot(0, 0)
        self.step()
        self.assertEqual(log, [])


class TestHitboxClone(PartTestCase):
    def test_parts_from_setup_are_recreated_once(self):
        png = self.bar_png()

        class Ninja(Sprite):
            def setup(self):
                self.hurt = self.add_hitbox(group="hurt")

        a = self.track(Ninja(png, center=self.at(0, 0), size=64, group="ninja"))
        b = self.track(a.clone(center=self.at(100, 0)))
        self.assertEqual(len(b.hitboxes), 2)          # main + the one part
        self.assertIs(b.hurt, b.hitboxes[1])
        self.assertEqual(b.hitboxes[1].group, frozenset({"hurt"}))
        self.assertTrue(b.tagged("hurt"))
        self.assertTrue(b.tagged("ninja"))

    def test_setup_parts_enroll_with_handlers_declared_first(self):
        # Module-top @collide, then spawn: setup() adds the part mid-construct.
        hits = []

        @collide("bullet", "hurt")
        def _hurt(b, target, info):
            hits.append((target, info.b_hitbox))

        png = self.bar_png()

        class Ninja(Sprite):
            def setup(self):
                self.hurt = self.add_hitbox(group="hurt")

        a = self.track(Ninja(png, center=self.at(0, 0), width=64, height=64,
                             hitbox_shape="rect", hitbox_scale=(3, 1)))
        self.dot(16, 0)  # body only
        self.step()
        self.assertEqual(hits, [])
        self.dot(0, 0)
        self.step()
        self.assertEqual(hits, [(a, a.hurt)])
        b = self.track(a.clone(center=self.at(300, 0)))
        self.dot(300, 0)
        self.step()
        self.assertEqual(hits[-1], (b, b.hurt))

    def test_ad_hoc_parts_and_their_groups_are_not_copied(self):
        s = self.hero()
        s.add_hitbox(group="hurt")
        c = self.track(s.clone(center=self.at(100, 0)))
        self.assertEqual(c.hitboxes, (c.hitbox,))
        self.assertEqual(c.group, {"hero"})


class TestHitboxQueries(PartTestCase):
    def test_query_point_returns_the_host_once(self):
        s = self.hero()
        s.add_hitbox(group="hurt")
        s.collidable = True

        @collide("bullet", "hurt")
        def _hurt(b, target, info):
            pass

        self.step()
        x, y = self.at(0, 0)
        self.assertEqual(collision.query_point(x, y), [s])

    def test_raycast_group_hits_the_part_and_ignore_skips_it(self):
        s = self.hero()
        s.add_hitbox(group="hurt")

        @collide("bullet", "hurt")
        def _hurt(b, target, info):
            pass

        self.step()
        p1, p2 = self.at(-100, 0), self.at(100, 0)
        hit = collision.raycast(p1, p2=p2, group="hurt")
        self.assertIsNotNone(hit)
        ident, _t, (hx, _hy) = hit
        self.assertIs(ident, s)
        # The part edge is x = -8, not the wide body edge at x = -24.
        self.assertAlmostEqual(hx - self.origin, -8.0, places=3)
        self.assertIsNone(collision.raycast(p1, p2=p2, group="hurt", ignore=s))

    def test_queries_without_a_group_see_bodies_only(self):
        # Narrow body (x∈[-2, 2]) inside the wider silhouette part (x∈[-8, 8]).
        s = self.hero(body_scale=(0.25, 1.0))
        s.add_hitbox(group="hurt")

        @collide("bullet", "hurt")
        def _hurt(b, target, info):
            pass

        self.step()
        hit = collision.raycast(self.at(-100, 0), p2=self.at(100, 0))
        self.assertIsNotNone(hit)
        ident, _t, (hx, _hy) = hit
        self.assertIs(ident, s)
        self.assertAlmostEqual(hx - self.origin, -2.0, places=3)
        probe = self.dot(6, 0, group="probe")
        probe.collidable = True
        self.assertEqual(probe.collides_with(), [])
        self.assertEqual(probe.collides_with("hurt"), [s])
        x, y = self.at(6, 0)
        self.assertEqual(collision.query_point(x, y), [probe])

    def test_collides_with_skips_own_parts(self):
        s = self.hero()
        s.add_hitbox(group="hurt")
        s.collidable = True

        @collide("bullet", "hurt")
        def _hurt(b, target, info):
            pass

        self.step()
        self.assertEqual(s.collides_with("hurt"), [])
        other = self.hero(group="villain")
        other.collidable = True
        self.assertEqual(s.collides_with("hurt"), [])
        other.add_hitbox(group="hurt")
        self.step()
        self.assertEqual(s.collides_with("hurt"), [other])



class TestDestroyExitsEveryPart(PartTestCase):
    """Review 2026-10-09 S8-10: a raising body exit skipped the part exits and
    left the part's contact keys behind (an ``id()`` a new collider could
    reuse before the next step)."""

    def test_a_raising_body_exit_still_ends_the_parts(self):
        s = self.hero()
        s.add_hitbox(group="hurt")
        log = []

        @collide_exit("bullet", "hero")
        def body_exit(b, target, info):
            log.append("body")
            raise RuntimeError("author bug in a body exit")

        @collide_exit("bullet", "hurt")
        def part_exit(b, target, info):
            log.append("part")

        @collide("bullet", "hurt")
        def part_enter(b, target, info):
            pass

        @collide("bullet", "hero")
        def body_enter(b, target, info):
            pass

        self.dot(0, 0)
        self.step()
        parts = [p._collider for p in s._hitbox_parts if p._collider is not None]
        self.assertTrue(parts, "not vacuous: the part is enrolled")
        part_ids = {id(c) for c in parts}
        with self.assertRaises(RuntimeError):
            s.destroy()
        self.assertEqual(sorted(log), ["body", "part"])
        cs = get_collision_system()
        self.assertFalse([k for k in cs._prev_contacts if part_ids & set(k)],
                         "a part key outlived its collider")


if __name__ == "__main__":
    unittest.main()
