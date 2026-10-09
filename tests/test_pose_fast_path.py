"""
Pose fast-path (A1–A3) regressions + B1 promotion contract.

Catches the bugs that blocked A2 on Circle / RegularPolygon, locks the
author-visible semantics of unlinked motion + ``@=`` / handles / ctor capture,
and documents the B1 float-pose+promotion contract so those cases stay green
after the representation change.

Run::

    python -m pytest tests/test_pose_fast_path.py -q
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.shapes import (
    Point, Line, Rect, Square, Circle, Ellipse, Polygon, RegularPolygon,
    EquilateralTriangle, get_xy,
)
from scena.state import (
    LinkedAttributeError, DerivedAttributeError, Attribute, get_scena_system,
)

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def _mark_dirty_count(fn) -> int:
    """How many times ``UpdateManager.mark_dirty`` runs during ``fn``."""
    um = get_scena_system().update_manager
    orig = um.mark_dirty
    n = 0

    def wrapped(node):
        nonlocal n
        n += 1
        return orig(node)

    um.mark_dirty = wrapped  # type: ignore[method-assign]
    try:
        fn()
    finally:
        um.mark_dirty = orig  # type: ignore[method-assign]
    return n


class PoseTestCase(unittest.TestCase):
    def assertPointAlmost(self, point, x, y, places=6):
        self.assertAlmostEqual(point.x, x, places=places)
        self.assertAlmostEqual(point.y, y, places=places)

    def assertNumAlmost(self, attr, value, places=6):
        got = attr.value if hasattr(attr, "value") else attr
        self.assertAlmostEqual(got, value, places=places)


# ---------------------------------------------------------------------------
# Bug regressions (would have failed before the cold-Derivate / move_to fixes)
# ---------------------------------------------------------------------------
class TestColdDerivateConstructionBugs(PoseTestCase):
    """Bugs: eager getattr in _set_defining_parts; RegularPolygon.move_to → centroid."""

    def test_circle_ctor_does_not_enable_pull_invalidate(self):
        c = Circle(center=(10, 20), radius=5)
        self.assertFalse(
            c._needs_pull_invalidate,
            "Circle ctor must not materialize Derivate slots (p1/p2/perimeter)",
        )
        self.assertIsNone(c.__dict__.get("p1"))
        self.assertIsNone(c.__dict__.get("p2"))
        self.assertIsNone(c.__dict__.get("perimeter_point"))

    def test_circle_move_rotate_keeps_pull_flag_clear(self):
        c = Circle(center=(0, 0), radius=8)
        c.move_to(50, 60)
        c.rotate_by(15)
        self.assertFalse(c._needs_pull_invalidate)
        self.assertPointAlmost(c.center, 50, 60)

    def test_regular_polygon_move_to_does_not_materialize_centroid(self):
        poly = RegularPolygon(n=5, center=(0, 0), radius=10, angle=0)
        self.assertFalse(poly._needs_pull_invalidate)
        self.assertIsNone(poly.__dict__.get("centroid"))
        poly.move_to(40, 50)
        self.assertFalse(
            poly._needs_pull_invalidate,
            "move_to must use Defining center, not Derivate centroid",
        )
        self.assertIsNone(poly.__dict__.get("centroid"))
        self.assertPointAlmost(poly.center, 40, 50)

    def test_equilateral_move_to_does_not_enable_pull(self):
        tri = EquilateralTriangle(center=(1, 2), radius=10, angle=0)
        tri.move_to(7, 8)
        tri.rotate_by(10)
        self.assertFalse(tri._needs_pull_invalidate)
        self.assertPointAlmost(tri.center, 7, 8)

    def test_vertex_side_move_to_does_not_materialize_centroid(self):
        poly = RegularPolygon(n=5, vertex=(0, 10), side=8, angle=0)
        self.assertFalse(poly._needs_pull_invalidate)
        self.assertIsNone(poly.__dict__.get("centroid"))
        self.assertIsNone(poly.__dict__.get("center"))
        poly.move_to(40, 50)
        self.assertFalse(
            poly._needs_pull_invalidate,
            "VERTEX_SIDE move_to must not wake Derivate centroid/center",
        )
        self.assertIsNone(poly.__dict__.get("centroid"))
        self.assertIsNone(poly.__dict__.get("center"))
        cx, cy = poly._center_xy()
        self.assertAlmostEqual(cx, 40.0, places=5)
        self.assertAlmostEqual(cy, 50.0, places=5)

    def test_line_ctor_does_not_materialize_unused_derivates(self):
        line = Line(p1=(0, 0), p2=(3, 4))
        self.assertFalse(line._needs_pull_invalidate)
        # POINT_POINT: vec/length/angle are Derivate — must stay cold
        self.assertIsNone(line.__dict__.get("vec"))
        self.assertIsNone(line.__dict__.get("length"))

    def test_line_angle_length_ctor_keeps_container_derivates_cold(self):
        line = Line(p1=(0, 0), angle=0.0, length=10.0)
        self.assertFalse(line._needs_pull_invalidate)
        self.assertIsNone(line.__dict__.get("vec"))
        self.assertIsNone(line.__dict__.get("center"))
        self.assertIsNone(line.__dict__.get("p2"))
        # Collision pose / proxy must not wake those slots either.
        from scena.collision import _collision_pose_key, _proxy_aabb_for_shape
        _ = _collision_pose_key(line)
        _ = _proxy_aabb_for_shape(line)
        self.assertIsNone(line.__dict__.get("vec"))
        self.assertIsNone(line.__dict__.get("center"))
        self.assertIsNone(line.__dict__.get("p2"))
        self.assertFalse(line._needs_pull_invalidate)

    def test_line_parallel_dist_does_not_wake_ref_vec(self):
        ref = Line(p1=(0, 0), angle=0.0, length=100.0)
        par = Line(dist=10.0, parallel_to=ref)
        self.assertIsNone(ref.__dict__.get("vec"))
        self.assertIsNone(ref.__dict__.get("center"))
        # Force the offset formula to evaluate (p1 is Defining + linked).
        _ = get_xy(par.p1, bare=True)
        self.assertIsNone(ref.__dict__.get("vec"))
        self.assertIsNone(ref.__dict__.get("center"))

    def test_ellipse_ctor_does_not_materialize_foci(self):
        e = Ellipse(center=(0, 0), width=10, height=6)
        self.assertFalse(e._needs_pull_invalidate)
        self.assertIsNone(e.__dict__.get("fp1"))
        self.assertIsNone(e.__dict__.get("fp2"))


# ---------------------------------------------------------------------------
# A1 / A2 / A3 behavior
# ---------------------------------------------------------------------------
class TestPoseFastPathA(PoseTestCase):
    """Absolute pose writes, skip mark_dirty when unlinked, bare Defining reads."""

    def test_unlinked_motion_skips_mark_dirty_rect(self):
        r = Rect(center=(0, 0), width=10, height=8, angle=0)

        def motion():
            for i in range(20):
                r.move_to(i, i + 1)
                r.rotate_by(3)

        self.assertEqual(_mark_dirty_count(motion), 0)
        self.assertFalse(r._needs_pull_invalidate)
        self.assertPointAlmost(r.center, 19, 20)

    def test_unlinked_motion_skips_mark_dirty_circle_square_poly(self):
        shapes = [
            Circle(center=(0, 0), radius=5),
            Square(center=(0, 0), length=10, angle=0),
            RegularPolygon(n=6, center=(0, 0), radius=9, angle=0),
            EquilateralTriangle(center=(0, 0), radius=8, angle=0),
            Ellipse(center=(0, 0), width=12, height=8, angle=0),
            Line(p1=(0, 0), p2=(10, 0)),
            Line(center=(0, 0), length=20, angle=0),
        ]

        def motion():
            for s in shapes:
                s.move_to(3, 4)
                s.rotate_by(5)

        self.assertEqual(_mark_dirty_count(motion), 0)
        for s in shapes:
            self.assertFalse(s._needs_pull_invalidate)
            self.assertPointAlmost(s.center, 3, 4)

    def test_accessing_derivate_enables_pull_invalidate(self):
        r = Rect(center=(0, 0), width=20, height=10, angle=0)
        self.assertFalse(r._needs_pull_invalidate)
        _ = r.top_left  # materialize Derivate
        self.assertTrue(r._needs_pull_invalidate)
        r.move_to(5, 5)
        # Live Derivate must stay coherent after motion
        self.assertPointAlmost(r.top_left, -5, 10)

    def test_regular_polygon_centroid_access_enables_pull(self):
        poly = RegularPolygon(n=5, center=(2, 3), radius=10, angle=0)
        poly.move_to(10, 10)
        self.assertFalse(poly._needs_pull_invalidate)
        cx, cy = get_xy(poly.centroid, bare=True)
        self.assertTrue(poly._needs_pull_invalidate)
        self.assertAlmostEqual(cx, 10, places=4)
        self.assertAlmostEqual(cy, 10, places=4)

    def test_inbound_link_enables_pull_and_blocks_move(self):
        src = Point(100, 200)
        r = Rect(center=(0, 0), width=10, height=10)
        self.assertFalse(r._needs_pull_invalidate)
        r.center @= src
        self.assertTrue(r._needs_pull_invalidate)
        with self.assertRaises(LinkedAttributeError):
            r.move_to(1, 1)
        # force escapes (and warns that the inbound link was dropped)
        with self.assertWarns(RuntimeWarning):
            r.move_to(1, 1, force=True)
        self.assertPointAlmost(r.center, 1, 1)

    def test_outbound_link_from_defining_enables_pull(self):
        r = Rect(center=(5, 6), width=10, height=10)
        sink = Attribute(0.0)
        sink @= lambda: r.center.x
        self.assertTrue(r._needs_pull_invalidate)
        self.assertNumAlmost(sink, 5)
        r.move_to(8, 9)
        self.assertNumAlmost(sink, 8)

    def test_point_move_to_updates_outbound_attribute_link(self):
        """Regression: batched Point._takein must mark_dirty leaf consumers."""
        p = Point(1, 2)
        sink = Attribute(0.0)
        sink @= lambda: p.x
        p.move_to(9, 4)
        self.assertNumAlmost(sink, 9)
        self.assertNumAlmost(p.y, 4)

    def test_move_by_absolute_equivalence(self):
        a = Circle(center=(10, 10), radius=3)
        b = Circle(center=(10, 10), radius=3)
        a.move_to(25, 30)
        b.move_by(15, 20)
        self.assertPointAlmost(a.center, 25, 30)
        self.assertPointAlmost(b.center, 25, 30)

    def test_partial_move_to_preserves_other_axis(self):
        r = Rect(center=(1, 2), width=4, height=4)
        r.move_to(x=9, y=None)
        self.assertPointAlmost(r.center, 9, 2)
        r.move_to(x=None, y=7)
        self.assertPointAlmost(r.center, 9, 7)

    def test_square_length_mirrors_after_fast_motion(self):
        sq = Square(center=(0, 0), length=10, angle=0)
        sq.move_to(3, 4)
        sq.rotate_by(45)
        self.assertFalse(sq._needs_pull_invalidate)
        self.assertNumAlmost(sq.length, 10)
        self.assertNumAlmost(sq.width, 10)
        self.assertNumAlmost(sq.height, 10)

    def test_irregular_polygon_move_to_still_uses_centroid(self):
        """Freeform Polygon correctly moves by centroid (not a RegularPolygon bug)."""
        poly = Polygon(points=[(0, 0), (4, 0), (0, 3)])
        # Accessing centroid is expected here — Defining vertices model.
        poly.move_to(10, 10)
        self.assertPointAlmost(poly.centroid, 10, 10)


# ---------------------------------------------------------------------------
# B1 contract — must stay green after float-pose + Attribute promotion
# ---------------------------------------------------------------------------
class TestB1PromotionContract(PoseTestCase):
    """Author-visible semantics B1 must preserve (and today's Attribute model already does).

    After B1, unlinked shapes may store bare floats until a promotion trigger.
    These tests are the oracle: same assertions, no reliance on private float
    storage — only public API and graph behavior.
    """

    # --- unlinked animation (must stay cheap; semantics identical) ----------

    def test_b1_unlinked_move_rotate_api(self):
        shapes = [
            Rect(center=(0, 0), width=10, height=8, angle=0),
            Circle(center=(0, 0), radius=5),
            Square(center=(0, 0), length=12, angle=0),
            RegularPolygon(n=5, center=(0, 0), radius=9, angle=15),
            EquilateralTriangle(center=(0, 0), radius=7, angle=0),
            Ellipse(center=(0, 0), width=14, height=6, angle=0),
        ]
        for s in shapes:
            s.move_to(20, 30)
            s.move_by(1, -1)
            s.rotate_by(10)
            self.assertPointAlmost(s.center, 21, 29)
            # Angle / rotation cache coherent enough to keep spinning
            s.rotate_by(-10)

    def test_b1_leaf_assignment_on_defining_center(self):
        r = Rect(center=(0, 0), width=10, height=10)
        r.center.x = 4
        r.center.y = 5
        self.assertPointAlmost(r.center, 4, 5)
        r.angle = 30
        self.assertNumAlmost(r.angle, 30)

    # --- promotion trigger: @= either direction -----------------------------

    def test_b1_promote_via_inbound_direct_link(self):
        src = Point(50, 60)
        r = Rect(center=(0, 0), width=10, height=10)
        r.center @= src
        self.assertPointAlmost(r.center, 50, 60)
        src.move_to(1, 2)
        self.assertPointAlmost(r.center, 1, 2)

    def test_b1_promote_via_outbound_link_from_part(self):
        r = Rect(center=(3, 4), width=10, height=10)
        sink = Point(0, 0)
        sink["x"] @= lambda: r.center.x
        sink["y"] @= lambda: r.center.y
        self.assertPointAlmost(sink, 3, 4)
        r.move_to(8, 9)
        self.assertPointAlmost(sink, 8, 9)

    def test_b1_promote_via_formula_link(self):
        r = Rect(center=(10, 0), width=10, height=10)
        sink = Attribute(0.0)
        # FormulaLink requires a lambda (inspect.getsource); keep it in this file.
        sink @= (lambda: r.center.x * 2)
        self.assertNumAlmost(sink, 20)
        r.move_to(15, 0)
        self.assertNumAlmost(sink, 30)

    # --- promotion trigger: ctor capture of a part identity ----------------

    def test_b1_promote_via_line_ctor_capturing_center(self):
        r = Rect(center=(5, 5), width=10, height=10)
        # Capturing rect.center as Line.p1 DirectLinks p1 → center (B1: promote
        # then link). Endpoint must track subsequent move_to.
        line = Line(p1=lambda: r.center, p2=(20, 5))
        self.assertIsNotNone(line.p1._link)
        r.move_to(0, 0)
        self.assertPointAlmost(line.p1, 0, 0)

    def test_b1_promote_via_line_ctor_capturing_derivate_corner(self):
        r = Rect(center=(0, 0), width=20, height=10, angle=0)
        line = Line(p1=lambda: r.top_left, p2=(0, 0))
        # top_left is Derivate; capture materializes + links (or B1 promotes).
        self.assertPointAlmost(line.p1, -10, 5)
        r.move_to(10, 10)
        self.assertPointAlmost(line.p1, 0, 15)

    # --- promotion trigger: handles() --------------------------------------

    def test_b1_handles_exposes_defining_points(self):
        r = Rect(center=(0, 0), width=10, height=10)
        r.show_handles()
        # Defining center becomes an interactive handle Point (promotes under B1).
        self.assertTrue(getattr(r.center, "handle", False) or r.center.visible)
        r.center.move_to(7, 8)
        self.assertPointAlmost(r.center, 7, 8)

    def test_b1_regular_polygon_handles_center(self):
        poly = RegularPolygon(n=5, center=(1, 1), radius=5, angle=0)
        poly.show_handles()
        poly.center.move_to(9, 9)
        self.assertPointAlmost(poly.center, 9, 9)

    # --- after promotion, full Attribute semantics --------------------------

    def test_b1_linked_move_raises_without_force(self):
        src = Point(0, 0)
        c = Circle(center=(1, 1), radius=3)
        c.center @= src
        with self.assertRaises(LinkedAttributeError):
            c.move_by(1, 0)
        with self.assertWarns(RuntimeWarning):
            c.move_by(1, 0, force=True)
        self.assertPointAlmost(c.center, 1, 0)

    def test_b1_derivate_still_readonly_after_motion(self):
        r = Rect(top_left=(0, 10), width=10, height=10)
        r.move_to(5, 5)
        with self.assertRaises(DerivedAttributeError):
            r.center = Point(0, 0)
        with self.assertRaises(DerivedAttributeError):
            r.top_right @= Point(1, 1)

    def test_b1_mixed_unlinked_and_linked_scene(self):
        """Many free movers + one constraint — B1 must not break either path."""
        free = [
            Circle(center=(i, i), radius=2) for i in range(10)
        ]
        pinned = Rect(center=(0, 0), width=6, height=6)
        anchor = Point(100, 100)
        pinned.center @= anchor
        for i, c in enumerate(free):
            c.move_to(i * 3, i * 2)
            c.rotate_by(i)
            self.assertFalse(c._needs_pull_invalidate)
        self.assertPointAlmost(pinned.center, 100, 100)
        anchor.move_to(50, 50)
        self.assertPointAlmost(pinned.center, 50, 50)

    def test_b1_clone_is_unlinked_copy(self):
        r = Rect(center=(2, 3), width=8, height=8, angle=15)
        src = Point(0, 0)
        r.center @= src
        copy = r.clone()
        # Clone drops formula links (existing Scena contract).
        copy.move_to(9, 9)
        self.assertPointAlmost(copy.center, 9, 9)
        self.assertPointAlmost(r.center, 0, 0)  # still pinned to src

    def test_b1_part_identity_stable_across_reads(self):
        """Repeated ``shape.center`` is the same object (today); B1 proxies must match."""
        r = Rect(center=(1, 1), width=4, height=4)
        a = r.center
        b = r.center
        self.assertIs(a, b)
        a.move_to(2, 3)
        self.assertPointAlmost(r.center, 2, 3)

    def test_b1_angle_property_and_rotate_by_agree(self):
        r = Rect(center=(0, 0), width=10, height=10, angle=0)
        r.rotate_by(40)
        self.assertNumAlmost(r.angle, 40)
        r.angle = 10
        self.assertNumAlmost(r.angle, 10)


class TestUnlinkedPoseNeverPaysPropertyAnchor(PoseTestCase):
    """Unlinked rotate_by / scale_by stay on the A1–A3 fast path (§6.1)."""

    def test_never_linked_rotation_scale_skips_mark_dirty(self):
        r = Rect(center=(0, 0), width=10, height=8, angle=0)
        self.assertIsNone(r.__dict__.get("_field_anchors"))

        def motion():
            for i in range(20):
                r.rotate_by(3)
                r.scale_by(1.0)

        self.assertEqual(_mark_dirty_count(motion), 0)
        self.assertFalse(r._needs_pull_invalidate)
        self.assertIsNone(r.__dict__.get("_field_anchors"))
        self.assertFalse(r["angle"].is_linked)
        self.assertFalse(r["scale"].is_linked)


class TestTier1UnlinkedStillA2(PoseTestCase):
    """Tier 1 must not regress A2 on shapes never used as link sources."""

    def test_center_wh_move_rotate_scale_zero_mark_dirty(self):
        r = Rect(center=(0, 0), width=12, height=6, angle=0)

        def motion():
            r.move_to(1, 2)
            r.move_by(0.5, 0.5)
            r.rotate_to(10)
            r.rotate_to(10)  # same value again
            r.scale_to(1.2)

        self.assertEqual(_mark_dirty_count(motion), 0)
        self.assertFalse(r._needs_pull_invalidate)


class TestDrawHelpersKeepDerivatesCold(PoseTestCase):
    """Draw / FX geometry helpers must not wake cold Derivates (A2).

    One wake is permanent: the host pays the batched move path every frame
    after (shape_fx smoke: ~15% idle FPS lost after cycling shape visuals).
    """

    def _assert_line_cold(self, line):
        self.assertFalse(line._needs_pull_invalidate)
        for name in ("center", "vec", "length"):
            self.assertIsNone(line.__dict__.get(name), name)

    def test_line_helpers(self):
        from scena.canvas import _approx_draw_aabb
        from scena.visuals import _aura_anchor
        from scena.transients import shape_pivot
        from scena.style import _local_half_extents

        line = Line(p1=(0, 0), p2=(30, 40))
        self.assertEqual(_approx_draw_aabb(line), (0.0, 0.0, 30.0, 40.0))
        self._assert_line_cold(line)
        self.assertEqual(_aura_anchor(line), (15.0, 20.0))
        self._assert_line_cold(line)
        cx, cy, r = shape_pivot(line)
        self.assertEqual((cx, cy), (15.0, 20.0))
        self.assertAlmostEqual(r, 25.0)
        self._assert_line_cold(line)
        hw, _hh = _local_half_extents(line)
        self.assertAlmostEqual(hw, 25.0)
        self._assert_line_cold(line)

        def motion():
            line.move_to(5, 5)
            line.rotate_by(10)

        self.assertEqual(_mark_dirty_count(motion), 0)

    def test_square_helpers(self):
        from scena.visuals import CheapGlow
        from scena.style import _local_half_extents

        sq = Square(center=(0, 0), length=20, angle=30)
        self.assertEqual(CheapGlow()._host_radius(sq), 10.0)
        self.assertEqual(_local_half_extents(sq), (10.0, 10.0))
        self.assertFalse(sq._needs_pull_invalidate)
        self.assertIsNone(sq.__dict__.get("width"))
        self.assertIsNone(sq.__dict__.get("height"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
