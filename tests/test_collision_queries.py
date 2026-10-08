"""Sector query, caster rule, ignore= grammar, and raycast end forms."""
from __future__ import annotations

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hypothesis_support  # noqa: E402,F401  (loads the Hypothesis profile)
from hypothesis import given  # noqa: E402
from hypothesis import strategies as hst  # noqa: E402

from scena import ANYTHING, Sprite, group
from scena.collision import collision, reset_collision_system
from scena.input import Mouse
from scena.shapes import Circle, Ellipse, Point, Polygon, Rect
from scena.scenamath import Vec2


class TestCollisionQueries(unittest.TestCase):
    def setUp(self):
        reset_collision_system()
        self._owned = []

    def tearDown(self):
        for shape in self._owned:
            try:
                shape.destroy()
            except Exception:
                pass
        self._owned.clear()
        reset_collision_system()

    def track(self, shape):
        self._owned.append(shape)
        return shape

    def body(self, shape):
        shape.collidable = True
        return self.track(shape)

    def test_named_group_sees_a_collidable_only_body(self):
        lone = self.body(Circle(center=(0, 0), radius=10, group="lone_tag"))
        probe = self.track(Circle(center=(0, 0), radius=4, layer=None))
        self.assertEqual(collision.query_shape(probe, group="lone_tag"), [lone])
        self.assertEqual(collision.query_point((0, 0), group="lone_tag"), [lone])
        self.assertEqual(
            collision.query_circle((0, 0), radius=4, group="lone_tag"), [lone],
        )

    def test_sector_inside_outside_and_partial(self):
        inside = self.body(Circle(center=(40, 0), radius=6))
        wide = self.body(Circle(center=(50, 50), radius=4))
        far = self.body(Circle(center=(130, 0), radius=5))
        # Center sits on the arc; the body reaches well inside the chord error.
        partial = self.body(Circle(center=(100, 0), radius=12))
        hits = collision.query_sector((0, 0), angle=0, radius=100, spread=60)
        self.assertIn(inside, hits)
        self.assertIn(partial, hits)
        self.assertNotIn(wide, hits)
        self.assertNotIn(far, hits)

    def test_sector_shapes(self):
        box = self.body(Rect(
            center=(55, -8), width=20, height=8, angle=30,
        ))
        egg = self.body(Ellipse(center=(55, 10), width=16, height=8))
        ell = self.body(Polygon(points=[
            (48, -6), (78, -6), (78, 0), (56, 0), (56, 8), (48, 8),
        ]))
        hits = collision.query_sector((0, 0), angle=0, radius=120, spread=50)
        self.assertIn(box, hits)
        self.assertIn(egg, hits)
        self.assertIn(ell, hits)

    def test_sector_spread_edges(self):
        def at(deg, dist=40, radius=4):
            rad = math.radians(deg)
            return self.body(Circle(
                center=(dist * math.cos(rad), dist * math.sin(rad)),
                radius=radius,
            ))

        on_axis = at(0)
        off_axis = at(80)
        hits = collision.query_sector((0, 0), angle=0, radius=80, spread=0)
        self.assertIn(on_axis, hits)
        self.assertNotIn(off_axis, hits)

        near = at(20, dist=50)
        far_ang = at(80, dist=50)
        hits = collision.query_sector((0, 0), angle=0, radius=80, spread=90)
        self.assertIn(near, hits)
        self.assertNotIn(far_ang, hits)

        inside_half = at(80, dist=50)
        outside_half = at(170, dist=50)
        hits = collision.query_sector((0, 0), angle=0, radius=80, spread=180)
        self.assertIn(inside_half, hits)
        self.assertNotIn(outside_half, hits)

        inside_wide = at(120, dist=50)
        behind = at(180, dist=50)
        hits = collision.query_sector((0, 0), angle=0, radius=80, spread=270)
        self.assertIn(inside_wide, hits)
        self.assertNotIn(behind, hits)

        back = self.body(Circle(center=(-40, 0), radius=6))
        front = self.body(Circle(center=(40, 0), radius=6))
        full = collision.query_sector((0, 0), angle=0, radius=80, spread=360)
        circle = collision.query_circle((0, 0), radius=80)
        self.assertEqual(full, circle)
        self.assertIn(back, full)
        self.assertIn(front, full)

    def test_sector_hitbox_part_matches_query_shape(self):
        ship = self.track(Sprite(
            center=(40, 0), size=24, hitbox_shape="rect", hitbox_scale=(0.25, 1.0),
        ))
        ship.add_hitbox(group="hurt_sector", shape="rect", scale=(2.0, 1.0))
        probe = self.track(Circle(center=(40, 0), radius=8, layer=None))
        seen = collision.query_sector(
            (0, 0), angle=0, radius=80, spread=50, group="hurt_sector",
        )
        self.assertEqual(seen, collision.query_shape(probe, group="hurt_sector"))
        self.assertEqual(seen, [ship])
        self.assertEqual(
            collision.query_sector(
                (0, 0), angle=0, radius=80, spread=50,
                group="hurt_sector", ignore=ship,
            ),
            [],
        )

    def test_default_angle_is_rotation(self):
        guard = self.body(Circle(center=(0, 0), radius=4))
        guard.angle = 90
        above = self.body(Circle(center=(0, 40), radius=6))
        right = self.body(Circle(center=(40, 0), radius=6))
        seen = collision.query_sector(guard, radius=80, spread=40)
        self.assertIn(above, seen)
        self.assertNotIn(right, seen)
        self.assertNotIn(guard, seen)

        with self.assertRaises(TypeError) as caught:
            collision.query_sector((0, 0), radius=10, spread=20)
        self.assertIn("angle=", str(caught.exception))

    def test_sprite_heading_is_rotation_not_art_angle_again(self):
        ship = self.track(Sprite(
            center=(0, 0), size=16, art_angle=90, hitbox_shape="rect",
        ))
        self.assertAlmostEqual(ship.angle, 90.0)
        above = self.body(Circle(center=(0, 50), radius=6))
        right = self.body(Circle(center=(50, 0), radius=6))
        seen = collision.query_sector(ship, radius=80, spread=30)
        self.assertIn(above, seen)
        self.assertNotIn(right, seen)

        ninja = self.track(Sprite(
            center=(0, 0), size=16, art_angle=0, flip_x=True, hitbox_shape="rect",
        ))
        self.assertAlmostEqual(ninja.angle, 180.0)
        left = self.body(Circle(center=(-50, 0), radius=6))
        other = self.body(Circle(center=(50, 0), radius=6))
        seen = collision.query_sector(ninja, radius=80, spread=30)
        self.assertIn(left, seen)
        self.assertNotIn(other, seen)

    def test_caster_is_skipped_and_ignore_adds(self):
        guard = self.body(Circle(center=(0, 0), radius=10))
        other = self.body(Circle(center=(15, 0), radius=8))
        hits = collision.query_circle(guard, radius=40)
        self.assertNotIn(guard, hits)
        self.assertIn(other, hits)
        hits = collision.query_circle(guard, radius=40, ignore=other)
        self.assertNotIn(guard, hits)
        self.assertNotIn(other, hits)
        self.assertIn(guard, collision.query_circle(guard.center, radius=40))
        self.assertNotIn(guard, collision.query_point(guard))
        self.assertIn(guard, collision.query_point(guard.center))
        self.assertIn(guard, collision.query_point((0, 0)))

        dot = self.body(Point(0, 0, layer=None))
        self.assertIn(dot, collision.query_point(dot))

    def test_raycast_does_not_return_the_caster_at_zero(self):
        turret = self.body(Circle(center=(0, 0), radius=15))
        self.assertIsNone(collision.raycast(turret, p2=(80, 0)))
        wall = self.body(Rect(center=(60, 0), width=10, height=30))
        hit = collision.raycast(turret, p2=(100, 0))
        self.assertIs(hit[0], wall)
        self.assertGreater(hit[1], 0.0)

    def test_ignore_grammar(self):
        ally = self.body(Circle(center=(0, 0), radius=8, group="allies_q"))
        foe = self.body(Circle(center=(24, 0), radius=8, group="foes_q"))
        shield = self.body(Circle(center=(-24, 0), radius=8, group="foes_q"))
        hits = collision.query_circle((0, 0), radius=50, ignore="allies_q")
        self.assertNotIn(ally, hits)
        self.assertIn(foe, hits)
        self.assertIn(shield, hits)
        hits = collision.query_circle((0, 0), radius=50, ignore=["allies_q", foe])
        self.assertNotIn(ally, hits)
        self.assertNotIn(foe, hits)
        self.assertIn(shield, hits)
        hits = collision.query_circle((0, 0), radius=50, ignore=group["allies_q"])
        self.assertNotIn(ally, hits)
        self.assertIn(foe, hits)
        # A tag with no members matches nothing — it does not raise.
        hits = collision.query_circle((0, 0), radius=50, ignore="nobody_q")
        self.assertIn(ally, hits)
        self.assertIn(foe, hits)
        with self.assertRaises(ValueError):
            collision.query_circle((0, 0), radius=50, ignore=ANYTHING)
        with self.assertRaises(TypeError) as caught:
            collision.query_circle((0, 0), radius=50, ignore=3)
        self.assertIn("ignore=", str(caught.exception))

    def test_group_on_point_and_circle(self):
        a = self.body(Circle(center=(0, 0), radius=5, group="grp_a"))
        b = self.body(Circle(center=(0, 0), radius=5, group="grp_b"))
        self.assertEqual(collision.query_point((0, 0), group="grp_a"), [a])
        self.assertEqual(collision.query_circle((0, 0), radius=1, group="grp_b"), [b])
        self.assertNotIn(b, collision.query_point((0, 0), group="grp_a"))

    def test_raycast_end_forms_agree(self):
        wall = self.body(Circle(center=(100, 0), radius=10))
        start = (-20, 0)
        hit_p2 = collision.raycast(start, p2=(140, 0))
        hit_vec = collision.raycast(start, vec=(160, 0))
        hit_ang = collision.raycast(start, angle=0, length=160)
        turret = self.track(Circle(center=(-20, 0), radius=3))
        turret.angle = 0
        hit_len = collision.raycast(turret, length=160)
        for hit in (hit_p2, hit_vec, hit_ang, hit_len):
            self.assertIs(hit[0], wall)
        self.assertAlmostEqual(hit_p2[1], hit_vec[1])
        self.assertAlmostEqual(hit_p2[1], hit_ang[1])
        self.assertAlmostEqual(hit_p2[1], hit_len[1])
        hit_vec2 = collision.raycast(start, vec=Vec2(160, 0))
        self.assertAlmostEqual(hit_p2[1], hit_vec2[1])

    def test_raycast_end_form_errors(self):
        start = (0, 0)
        with self.assertRaises(TypeError) as caught:
            collision.raycast(start, (10, 0))
        message = str(caught.exception)
        self.assertIn("p2=", message)
        self.assertIn("vec=", message)
        self.assertIn("angle=", message)
        self.assertIn("length=", message)
        with self.assertRaises(TypeError):
            collision.raycast(start, p2=(10, 0), vec=(10, 0))
        with self.assertRaises(TypeError) as caught:
            collision.raycast(start, angle=10)
        self.assertIn("length=", str(caught.exception))
        with self.assertRaises(TypeError):
            collision.raycast(start, vec=Point(1, 0, layer=None))
        with self.assertRaises(TypeError):
            collision.raycast(start, vec=Circle(center=(1, 0), radius=1, layer=None))
        mouse = Mouse()
        mouse._x = 1
        mouse._y = 0
        with self.assertRaises(TypeError):
            collision.raycast(start, vec=mouse)

    def test_negative_sizes_raise_and_zero_is_legal(self):
        origin = (0, 0)
        calls = (
            lambda: collision.query_circle(origin, radius=-1),
            lambda: collision.query_circle(0, 0, -1),
            lambda: collision.query_sector(origin, angle=0, radius=-1, spread=10),
            lambda: collision.query_sector(origin, angle=0, radius=10, spread=-1),
            lambda: collision.query_sector(origin, angle=0, radius=10, spread=361),
            lambda: collision.raycast(origin, angle=0, length=-1),
        )
        for call in calls:
            with self.assertRaises(ValueError):
                call()
        collision.query_circle(origin, radius=0)
        collision.query_sector(origin, angle=0, radius=0, spread=0)
        collision.query_sector(origin, angle=0, radius=10, spread=0)
        collision.raycast(origin, angle=0, length=0)

    @given(
        angle=hst.floats(
            min_value=-720.0, max_value=720.0,
            allow_nan=False, allow_infinity=False,
        ),
        spread=hst.floats(
            min_value=30.0, max_value=330.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    def test_circle_wedge_matches_query_sector(self, angle, spread):
        """Dots just inside a Circle arc are sector hits; dots just outside are not."""
        from scena.track import shape_outline

        reach = 100.0
        wedge = self.track(Circle(
            center=(0, 0), radius=reach, angle=angle, spread=spread, use_center=True,
        ))
        verts, _closed = shape_outline(wedge, samples=24)
        start = math.degrees(math.atan2(verts[0][1], verts[0][0]))
        end = math.degrees(math.atan2(verts[-1][1], verts[-1][0]))
        mid = verts[len(verts) // 2]
        mid_deg = math.degrees(math.atan2(mid[1], mid[0]))

        def dot(deg, dist):
            rad = math.radians(deg)
            return self.body(Circle(
                center=(dist * math.cos(rad), dist * math.sin(rad)),
                radius=2,
            ))

        inside_arc = dot(mid_deg, reach - 12)
        outside_arc = dot(mid_deg, reach + 12)
        inside_start = dot(start + 8.0, reach * 0.45)
        outside_start = dot(start - 8.0, reach * 0.45)
        inside_end = dot(end - 8.0, reach * 0.45)
        outside_end = dot(end + 8.0, reach * 0.45)
        hits = collision.query_sector(
            (0, 0),
            angle=float(wedge.angle),
            radius=reach,
            spread=float(wedge.spread),
        )
        self.assertIn(inside_arc, hits)
        self.assertNotIn(outside_arc, hits)
        self.assertIn(inside_start, hits)
        self.assertNotIn(outside_start, hits)
        self.assertIn(inside_end, hits)
        self.assertNotIn(outside_end, hits)


if __name__ == "__main__":
    unittest.main()
