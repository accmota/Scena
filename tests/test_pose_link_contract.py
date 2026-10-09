"""
Pose / reactive-link contract (A4).

Catches the class of bug where bare-float pose writes (``_takein_xy_float``)
skip ``mark_dirty`` while an outbound ``@=`` already set
``_needs_pull_invalidate`` — sinks go silently stale. That was the Sprite
pre-A4 failure mode; these tests pin the same contract across Shape models
(canonical + non-canonical), Sprite, Point, and State.

Also locks: inbound links still block ``move_*`` without ``force=True``;
unlinked motion still skips ``mark_dirty`` (A2).

Run::

    python -m pytest tests/test_pose_link_contract.py tests/test_pose_fast_path.py -q
"""

from __future__ import annotations

import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.shapes import (
    Point, Line, Rect, Square, Circle, Ellipse, Polygon, RegularPolygon,
    EquilateralTriangle, get_xy,
)
from scena.sprite import Sprite
from scena.state import (
    LinkedAttributeError, Attribute, State, get_scena_system,
)
from scena.scenamath import Vec2

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def _mark_dirty_count(fn) -> int:
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


def _sprite(**kwargs) -> Sprite:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return Sprite("nope_missing.png", **kwargs)


class PoseLinkCase(unittest.TestCase):
    def assertPointAlmost(self, point, x, y, places=5):
        self.assertAlmostEqual(float(point.x), x, places=places)
        self.assertAlmostEqual(float(point.y), y, places=places)

    def assertNumAlmost(self, attr, value, places=5):
        got = attr.value if hasattr(attr, "value") else attr
        self.assertAlmostEqual(float(got), value, places=places)

    def assertSinkTracksPoint(self, sink: Point, src_point, *, places=5):
        self.assertPointAlmost(sink, float(src_point.x), float(src_point.y), places=places)

    def assertOutboundCenterTracks(self, shape, *, place=(50.0, 60.0), delta=(3.0, -2.0)):
        """``sink @= shape.center`` must track ``move_to`` and ``move_by``."""
        sink = Point(0, 0)
        sink @= shape.center
        self.assertTrue(shape._needs_pull_invalidate)
        shape.move_to(*place)
        self.assertSinkTracksPoint(sink, shape.center)
        shape.move_by(*delta)
        self.assertSinkTracksPoint(sink, shape.center)
        # Partial axis
        shape.move_to(x=place[0] + 100, y=None)
        self.assertSinkTracksPoint(sink, shape.center)
        shape.move_to(x=None, y=place[1] + 100)
        self.assertSinkTracksPoint(sink, shape.center)

    def assertOutboundLeafTracks(self, shape, part_name: str = "center"):
        """Formula leaf: ``attr @= lambda: shape.<part>.x`` tracks motion."""
        part = getattr(shape, part_name)
        sink = Attribute(0.0)
        sink @= (lambda: part.x)
        self.assertTrue(shape._needs_pull_invalidate)
        before = float(part.x)
        shape.move_by(7, 0)
        self.assertNumAlmost(sink, before + 7)
        shape.move_to(float(getattr(shape, part_name).x) + 1, None)
        self.assertNumAlmost(sink, float(getattr(shape, part_name).x))

    def assertInboundBlocks(self, shape, part_name: str = "center"):
        src = Point(100, 200)
        part = getattr(shape, part_name)
        part @= src
        with self.assertRaises(LinkedAttributeError):
            shape.move_to(1, 1)
        with self.assertRaises(LinkedAttributeError):
            shape.move_by(1, 0)
        with self.assertWarns(RuntimeWarning):
            shape.move_to(1, 1, force=True)
        self.assertPointAlmost(part, 1, 1)


# ---------------------------------------------------------------------------
# Canonical center models + Sprite
# ---------------------------------------------------------------------------
class TestOutboundCenterCanonical(PoseLinkCase):
    def test_rect_center_wh(self):
        self.assertOutboundCenterTracks(Rect(center=(0, 0), width=10, height=8))

    def test_square(self):
        self.assertOutboundCenterTracks(Square(center=(0, 0), length=10))

    def test_circle_center_radius(self):
        self.assertOutboundCenterTracks(Circle(center=(0, 0), radius=5))

    def test_ellipse_center_wh(self):
        self.assertOutboundCenterTracks(Ellipse(center=(0, 0), width=12, height=6))

    def test_regular_polygon_center(self):
        self.assertOutboundCenterTracks(
            RegularPolygon(n=5, center=(0, 0), radius=10, angle=0)
        )

    def test_equilateral(self):
        self.assertOutboundCenterTracks(
            EquilateralTriangle(center=(0, 0), radius=8, angle=0)
        )

    def test_sprite_center(self):
        """Regression: Sprite once always bare-floated and left sinks stale."""
        self.assertOutboundCenterTracks(_sprite(center=(0, 0), width=40, height=20))

    def test_line_center_length_angle(self):
        self.assertOutboundCenterTracks(
            Line(center=(0, 0), length=20, angle=0)
        )


# ---------------------------------------------------------------------------
# Non-canonical / multi-point models — link Defining parts
# ---------------------------------------------------------------------------
class TestOutboundNonCanonical(PoseLinkCase):
    def test_line_point_point_p1(self):
        ln = Line(p1=(0, 0), p2=(10, 0))
        sink = Point(0, 0)
        sink @= ln.p1
        ln.move_to(20, 30)
        self.assertSinkTracksPoint(sink, ln.p1)
        # Center moved; endpoints translated together
        self.assertAlmostEqual(float(ln.center.x), 20, places=5)
        self.assertAlmostEqual(float(ln.center.y), 30, places=5)
        self.assertAlmostEqual(float(ln.p2.x) - float(ln.p1.x), 10, places=5)

    def test_line_point_point_p2(self):
        ln = Line(p1=(0, 0), p2=(10, 0))
        sink = Point(0, 0)
        sink @= ln.p2
        ln.move_by(5, 7)
        self.assertSinkTracksPoint(sink, ln.p2)

    def test_line_point_point_both_endpoints(self):
        ln = Line(p1=(0, 0), p2=(4, 0))
        a, b = Point(0, 0), Point(0, 0)
        a @= ln.p1
        b @= ln.p2
        ln.move_to(10, 10)
        self.assertSinkTracksPoint(a, ln.p1)
        self.assertSinkTracksPoint(b, ln.p2)

    def test_line_point_angle_length_p1(self):
        ln = Line(p1=(0, 0), angle=0.0, length=10.0)
        sink = Point(0, 0)
        sink @= ln.p1
        ln.move_to(8, 9)
        self.assertSinkTracksPoint(sink, ln.p1)

    def test_line_point_vec_p1(self):
        ln = Line(p1=(1, 2), vec=Vec2(10, 0))
        sink = Point(0, 0)
        sink @= ln.p1
        ln.move_by(4, -1)
        self.assertSinkTracksPoint(sink, ln.p1)

    def test_line_point_dx_dy_p1(self):
        ln = Line(p1=(0, 0), dx=10, dy=0)
        sink = Point(0, 0)
        sink @= ln.p1
        ln.move_to(3, 4)
        self.assertSinkTracksPoint(sink, ln.p1)

    def test_circle_two_points_p1(self):
        c = Circle(p1=(0, 0), p2=(10, 0))
        sink = Point(0, 0)
        sink @= c.p1
        c.move_to(5, 5)
        self.assertSinkTracksPoint(sink, c.p1)
        self.assertAlmostEqual(float(c.center.x), 5, places=4)
        self.assertAlmostEqual(float(c.center.y), 5, places=4)

    def test_circle_center_perimeter(self):
        c = Circle.from_points(center=(0, 0), perimeter=(5, 0))
        sink = Point(0, 0)
        sink @= c.center
        c.move_by(2, 3)
        self.assertSinkTracksPoint(sink, c.center)
        sink2 = Point(0, 0)
        sink2 @= c.perimeter_point
        c.move_to(10, 10)
        self.assertSinkTracksPoint(sink2, c.perimeter_point)

    def test_ellipse_focal_points(self):
        e = Ellipse(fp1=(0, 0), fp2=(10, 0), major_axis=20)
        sink = Point(0, 0)
        sink @= e.fp1
        e.move_to(5, 5)
        self.assertSinkTracksPoint(sink, e.fp1)
        self.assertAlmostEqual(float(e.center.x), 5, places=4)
        self.assertAlmostEqual(float(e.center.y), 5, places=4)

    def test_rect_corner_corner(self):
        r = Rect(p1=(0, 0), p2=(10, 8))
        sink = Point(0, 0)
        sink @= r.p1
        r.move_to(100, 100)
        self.assertSinkTracksPoint(sink, r.p1)
        self.assertAlmostEqual(float(r.center.x), 100, places=4)
        self.assertAlmostEqual(float(r.center.y), 100, places=4)

    def test_rect_top_left_wh(self):
        r = Rect(top_left=(0, 10), width=10, height=8)
        sink = Point(0, 0)
        sink @= r.top_left
        r.move_by(5, -5)
        self.assertSinkTracksPoint(sink, r.top_left)

    def test_rect_point_vec(self):
        r = Rect(p1=(0, 0), vec=Vec2(10, 5))
        sink = Point(0, 0)
        sink @= r.p1
        r.move_to(20, 30)
        self.assertSinkTracksPoint(sink, r.p1)

    def test_rect_spine(self):
        r = Rect(p1=(0, 0), p2=(10, 0), height=5, anchor="cap")
        sink = Point(0, 0)
        sink @= r.p1
        r.move_by(1, 2)
        self.assertSinkTracksPoint(sink, r.p1)

    def test_regular_polygon_vertex_side(self):
        poly = RegularPolygon(n=5, vertex=(0, 10), side=8, angle=90)
        sink = Point(0, 0)
        sink @= poly.vertex
        poly.move_to(7, 8)
        self.assertSinkTracksPoint(sink, poly.vertex)

    def test_irregular_polygon_vertex(self):
        poly = Polygon(points=[(0, 0), (4, 0), (0, 3)])
        sink = Point(0, 0)
        sink @= poly._vertices[0]
        poly.move_to(10, 10)
        self.assertSinkTracksPoint(sink, poly._vertices[0])


# ---------------------------------------------------------------------------
# Leaf / formula / State consumers
# ---------------------------------------------------------------------------
class TestOutboundLeafAndState(PoseLinkCase):
    def test_formula_on_rect_center_x(self):
        self.assertOutboundLeafTracks(Rect(center=(0, 0), width=8, height=8))

    def test_formula_on_sprite_center_x(self):
        self.assertOutboundLeafTracks(_sprite(center=(0, 0), width=20, height=10))

    def test_formula_on_line_p1_x(self):
        ln = Line(p1=(0, 0), p2=(10, 0))
        sink = Attribute(0.0)
        sink @= (lambda: ln.p1.x)
        ln.move_by(5, 0)
        self.assertNumAlmost(sink, 5)
        ln.move_to(20, 0)
        # POINT_POINT center at midpoint; p1.x = center.x - half length
        self.assertNumAlmost(sink, float(ln.p1.x))

    def test_point_sink_bracket_xy(self):
        r = Rect(center=(1, 2), width=4, height=4)
        sink = Point(0, 0)
        sink["x"] @= (lambda: r.center.x)
        sink["y"] @= (lambda: r.center.y)
        r.move_to(9, 8)
        self.assertPointAlmost(sink, 9, 8)

    def test_state_cell_tracks_circle(self):
        c = Circle(center=(0, 0), radius=3)
        st = State(name="hud")
        st.x = 0.0
        st["x"] @= (lambda: c.center.x)
        c.move_to(12, 0)
        self.assertNumAlmost(st.x, 12)
        c.move_by(-2, 0)
        self.assertNumAlmost(st.x, 10)

    def test_state_to_shape_inbound_blocks(self):
        st = State(name="pose")
        st.cx = 50.0
        st.cy = 60.0
        c = Circle(center=(0, 0), radius=2)
        c.center["x"] @= (lambda: st.cx)
        c.center["y"] @= (lambda: st.cy)
        self.assertPointAlmost(c.center, 50, 60)
        with self.assertRaises(LinkedAttributeError):
            c.move_to(0, 0)
        st.cx = 1.0
        st.cy = 2.0
        self.assertPointAlmost(c.center, 1, 2)

    def test_chained_shapes(self):
        """A moves → B (linked to A.center) → C (linked to B.center)."""
        a = Circle(center=(0, 0), radius=2)
        b = Circle(center=(0, 0), radius=2)
        c = Circle(center=(0, 0), radius=2)
        b.center @= a.center
        c.center @= b.center
        a.move_to(15, 25)
        self.assertPointAlmost(b.center, 15, 25)
        self.assertPointAlmost(c.center, 15, 25)
        a.move_by(1, 1)
        self.assertPointAlmost(c.center, 16, 26)

    def test_line_endpoint_to_sprite_center(self):
        spr = _sprite(center=(0, 0), width=16, height=16)
        ln = Line(p1=(0, 0), p2=(10, 0))
        ln.p1 @= spr.center
        spr.move_to(40, 50)
        self.assertPointAlmost(ln.p1, 40, 50)
        spr.move_by(-5, 5)
        self.assertPointAlmost(ln.p1, 35, 55)

    def test_multiple_consumers_one_sprite(self):
        spr = _sprite(center=(0, 0), width=10, height=10)
        sinks = [Point(0, 0) for _ in range(5)]
        for s in sinks:
            s @= spr.center
        spr.move_to(7, 8)
        for s in sinks:
            self.assertPointAlmost(s, 7, 8)


# ---------------------------------------------------------------------------
# Inbound guards
# ---------------------------------------------------------------------------
class TestInboundBlocksMove(PoseLinkCase):
    def test_rect(self):
        self.assertInboundBlocks(Rect(center=(0, 0), width=4, height=4))

    def test_circle(self):
        self.assertInboundBlocks(Circle(center=(0, 0), radius=3))

    def test_sprite(self):
        self.assertInboundBlocks(_sprite(center=(0, 0), width=10, height=10))

    def test_line_p1_inbound(self):
        ln = Line(p1=(0, 0), p2=(10, 0))
        src = Point(100, 200)
        ln.p1 @= src
        with self.assertRaises(LinkedAttributeError):
            ln.move_to(1, 1)
        with self.assertRaises(LinkedAttributeError):
            ln.move_by(1, 0)
        with self.assertWarns(RuntimeWarning):
            ln.move_by(1, 0, force=True)
        # force unlinked p1 then translated; center model still applies for move_to
        self.assertAlmostEqual(float(ln.p1.x), 101.0, places=5)
        self.assertAlmostEqual(float(ln.p1.y), 200.0, places=5)

    def test_ellipse_fp1_inbound(self):
        e = Ellipse(fp1=(0, 0), fp2=(10, 0), major_axis=20)
        src = Point(0, 0)
        e.fp1 @= src
        with self.assertRaises(LinkedAttributeError):
            e.move_by(1, 0)


# ---------------------------------------------------------------------------
# Unlinked still cheap (A2) after A4 coverage
# ---------------------------------------------------------------------------
class TestUnlinkedStillSkipsMarkDirty(PoseLinkCase):
    def test_line_point_point(self):
        ln = Line(p1=(0, 0), p2=(10, 0))
        self.assertFalse(ln._needs_pull_invalidate)

        def motion():
            for i in range(20):
                ln.move_to(i, i + 1)
                ln.move_by(0.1, 0.1)

        self.assertEqual(_mark_dirty_count(motion), 0)
        self.assertFalse(ln._needs_pull_invalidate)

    def test_sprite(self):
        spr = _sprite(center=(0, 0), width=20, height=10)
        self.assertFalse(spr._needs_pull_invalidate)

        def motion():
            for i in range(20):
                spr.move_to(i, i)

        self.assertEqual(_mark_dirty_count(motion), 0)

    def test_ellipse_focal(self):
        e = Ellipse(fp1=(0, 0), fp2=(10, 0), major_axis=20)

        def motion():
            e.move_to(3, 4)
            e.move_by(1, 1)

        self.assertEqual(_mark_dirty_count(motion), 0)

    def test_circle_two_points(self):
        c = Circle(p1=(0, 0), p2=(10, 0))

        def motion():
            c.move_to(5, 5)
            c.move_by(1, 0)

        self.assertEqual(_mark_dirty_count(motion), 0)

    def test_rect_corner_and_spine(self):
        shapes = [
            Rect(p1=(0, 0), p2=(10, 8)),
            Rect(p1=(0, 0), p2=(10, 0), height=4, anchor="cap"),
            Rect(top_left=(0, 10), width=8, height=6),
            Rect(p1=(0, 0), vec=Vec2(8, 4)),
        ]

        def motion():
            for s in shapes:
                s.move_to(2, 3)
                s.move_by(1, 1)

        self.assertEqual(_mark_dirty_count(motion), 0)

    def test_regular_polygon_vertex_side(self):
        poly = RegularPolygon(n=6, vertex=(0, 10), side=5, angle=0)

        def motion():
            poly.move_to(1, 2)
            poly.move_by(0.5, 0.5)

        self.assertEqual(_mark_dirty_count(motion), 0)


# ---------------------------------------------------------------------------
# Geometry coherence after linked motion
# ---------------------------------------------------------------------------
class TestGeometryCoherenceAfterLinkedMove(PoseLinkCase):
    def test_line_length_preserved_after_outbound(self):
        ln = Line(p1=(0, 0), p2=(10, 0))
        sink = Point(0, 0)
        sink @= ln.p1
        length0 = float(ln.length)
        ln.move_to(100, 200)
        self.assertAlmostEqual(float(ln.length), length0, places=5)
        self.assertSinkTracksPoint(sink, ln.p1)

    def test_circle_radius_preserved_two_points(self):
        c = Circle(p1=(0, 0), p2=(10, 0))
        r0 = float(c.radius)
        sink = Point(0, 0)
        sink @= c.p1
        c.move_to(0, 50)
        self.assertAlmostEqual(float(c.radius), r0, places=5)
        self.assertSinkTracksPoint(sink, c.p1)

    def test_sprite_size_unchanged(self):
        spr = _sprite(center=(0, 0), width=40, height=20)
        sink = Point(0, 0)
        sink @= spr.center
        spr.move_to(9, 4)
        self.assertAlmostEqual(float(spr.width), 40)
        self.assertAlmostEqual(float(spr.height), 20)
        self.assertPointAlmost(sink, 9, 4)

    def test_derivate_center_after_line_move_with_outbound(self):
        ln = Line(p1=(0, 0), p2=(10, 0))
        sink = Attribute(0.0)
        sink @= (lambda: ln.center.x)
        ln.move_to(30, 40)
        self.assertNumAlmost(sink, 30)
        self.assertAlmostEqual(float(ln.center.y), 40, places=5)


# ---------------------------------------------------------------------------
# Point as shape
# ---------------------------------------------------------------------------
class TestPointPoseLinks(PoseLinkCase):
    def test_point_outbound(self):
        p = Point(0, 0)
        sink = Point(0, 0)
        sink @= p
        p.move_to(5, 6)
        self.assertPointAlmost(sink, 5, 6)
        p.move_by(1, 1)
        self.assertPointAlmost(sink, 6, 7)

    def test_point_leaf_outbound(self):
        p = Point(1, 2)
        sink = Attribute(0.0)
        sink @= (lambda: p.x)
        p.move_to(9, 4)
        self.assertNumAlmost(sink, 9)


# ---------------------------------------------------------------------------
# Tier 1 leaf / batch / clean-read contracts (T1.4–T1.6)
# ---------------------------------------------------------------------------
class TestTier1LeafResolveAndTakein(PoseLinkCase):
    """Leaf sinks (Point / Attribute / ScalarAnchor) under batch must stay fresh.

    Guards the Sprite-pre-A4 class of bug if T1.4/T1.5 skip mark_dirty wrongly.
    """

    def test_attribute_leaf_tracks_batched_center_takein(self):
        host = Rect(center=(0, 0), width=20, height=10)
        leaf = Attribute(0.0)
        leaf @= (lambda h=host: h.center.x)
        with host._batch_update():
            host.center._takein((42.0, 7.0))
        self.assertNumAlmost(leaf, 42.0)
        with host._batch_update():
            host.move_to(100.0, 7.0)
        self.assertNumAlmost(leaf, 100.0)

    def test_point_direct_link_tracks_batched_move(self):
        host = Rect(center=(1, 2), width=10, height=8)
        sink = Point(0, 0)
        sink @= host.center
        with host._batch_update():
            host.move_by(5, 6)
        self.assertPointAlmost(sink, 6, 8)

    def test_scalar_anchor_rotation_tracks_after_clean_read(self):
        """T1.6: clean linked ScalarSlot reads must still refresh when dirtied."""
        r = Rect(center=(0, 0), width=30, height=12, angle=0.0)
        sink = Attribute(0.0)
        sink @= (lambda r=r: r.angle)
        self.assertNumAlmost(sink, 0.0)  # clean read
        r.rotate_to(15.0)
        self.assertNumAlmost(sink, 15.0)
        _ = float(r.angle)  # clean again
        r.rotate_to(75.0)
        self.assertNumAlmost(sink, 75.0)

    def test_unlinked_still_zero_mark_dirty_after_tier1(self):
        """A2 control — Tier 1 must not start marking unlinked pose writes."""
        shapes = [
            Rect(center=(0, 0), width=10, height=8),
            Circle(center=(0, 0), radius=5),
            Line(p1=(0, 0), p2=(10, 0)),
        ]

        def motion():
            for s in shapes:
                s.move_to(2, 3)
                s.move_by(0.5, 0.5)

        self.assertEqual(_mark_dirty_count(motion), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
