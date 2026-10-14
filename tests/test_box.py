"""Box, Grid, box= fit contract, graphic.box, canvas parents.

Run headless:

    python -m unittest tests.test_box -v
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hypothesis_support  # noqa: E402,F401  (loads the Hypothesis profile)
from hypothesis import assume, given, strategies as hst  # noqa: E402

from scena import (
    Box, Grid, Circle, Rect, Square, Ellipse, RegularPolygon, Triangle,
    Line, Polygon, Sprite, Text, canvas, init, Entity,
)
from scena.entity import Graphic
from scena.geom import intersections, closest_point


class BoxTestCase(unittest.TestCase):
    def setUp(self):
        init(width=1000, height=800)
        canvas.reset_view()
        self._owned = []

    def tearDown(self):
        for s in list(self._owned):
            try:
                s.destroy()
            except Exception:
                pass
        self._owned.clear()

    def track(self, obj):
        self._owned.append(obj)
        return obj


class TestBoxConstructors(BoxTestCase):
    def test_center_wh(self):
        b = Box(center=(400, 300), width=200, height=100)
        self.assertAlmostEqual(float(b.center.x), 400.0)
        self.assertAlmostEqual(float(b.center.y), 300.0)
        self.assertAlmostEqual(float(b.width), 200.0)
        self.assertAlmostEqual(float(b.height), 100.0)
        self.assertAlmostEqual(b.left, 300.0)
        self.assertAlmostEqual(b.right, 500.0)
        self.assertAlmostEqual(b.bottom, 250.0)
        self.assertAlmostEqual(b.top, 350.0)
        self.assertIsNone(b.col_index)
        self.assertIsNone(b.row_index)

    def test_top_left_wh(self):
        b = Box(top_left=(100, 300), width=400, height=200)
        self.assertAlmostEqual(float(b.center.x), 300.0)
        self.assertAlmostEqual(float(b.center.y), 200.0)

    def test_corner_corner(self):
        b = Box(p1=(100, 100), p2=(500, 300))
        self.assertAlmostEqual(float(b.width), 400.0)
        self.assertAlmostEqual(float(b.height), 200.0)
        self.assertAlmostEqual(float(b.center.x), 300.0)

    def test_spine(self):
        b = Box(p1=(100, 300), p2=(500, 300), height=40, anchor="square")
        self.assertGreater(float(b.width), 400.0)
        self.assertAlmostEqual(float(b.height), 40.0)

    def test_empty_raises(self):
        with self.assertRaises(ValueError) as ctx:
            Box()
        self.assertIn("needs a region", str(ctx.exception))

    def test_no_color_or_layer(self):
        with self.assertRaises(TypeError):
            Box(center=(0, 0), width=10, height=10, color="red")
        with self.assertRaises(TypeError):
            Box(center=(0, 0), width=10, height=10, layer="ui")

    def test_no_four_positionals(self):
        with self.assertRaises(TypeError):
            Box(100, 100, 500, 300)

    def test_not_an_entity(self):
        b = Box(center=(400, 300), width=80, height=40)
        self.assertNotIsInstance(b, Entity)
        self.assertNotIsInstance(b, Graphic)
        self.assertNotIsInstance(b, Rect)

    def test_from_graphic_alias(self):
        panel = self.track(Rect(center=(400, 300), width=120, height=80, angle=15))
        a = Box.from_graphic(panel)
        c = Box(panel)
        self.assertAlmostEqual(float(a.width), 120.0)
        self.assertAlmostEqual(float(c.height), 80.0)
        self.assertAlmostEqual(float(a.angle), 15.0)


class TestBoxLayout(BoxTestCase):
    def test_inset(self):
        b = Box(center=(400, 300), width=200, height=100)
        inner = b.inset(10)
        self.assertAlmostEqual(float(inner.width), 180.0)
        self.assertAlmostEqual(float(inner.height), 80.0)
        self.assertAlmostEqual(float(b.width), 200.0)
        self.assertAlmostEqual(float(inner.center.x), 400.0)

    def test_inset_clamps_to_line(self):
        # Smoke stamp path: cell_pad=4 on a 59.2×3.84 cell.
        b = Box(center=(400, 300), width=59.2, height=3.84)
        inner = b.inset(4)
        self.assertAlmostEqual(float(inner.width), 51.2, places=5)
        self.assertAlmostEqual(float(inner.height), 0.0)
        self.assertAlmostEqual(float(inner.center.x), 400.0)
        self.assertAlmostEqual(float(inner.center.y), 300.0)

    def test_inset_clamps_to_point(self):
        b = Box(center=(400, 300), width=20, height=20)
        inner = b.inset(12)
        self.assertAlmostEqual(float(inner.width), 0.0)
        self.assertAlmostEqual(float(inner.height), 0.0)
        self.assertAlmostEqual(float(inner.center.x), 400.0)
        self.assertAlmostEqual(float(inner.center.y), 300.0)

    def test_inset_exact_fit_is_point(self):
        b = Box(center=(400, 300), width=20, height=20)
        inner = b.inset(10)
        self.assertAlmostEqual(float(inner.width), 0.0)
        self.assertAlmostEqual(float(inner.height), 0.0)

    def test_inset_negative_still_raises(self):
        b = Box(center=(400, 300), width=20, height=20)
        with self.assertRaises(ValueError):
            b.inset(-1)

    def test_outset(self):
        b = Box(center=(400, 300), width=200, height=100)
        outer = b.outset(10)
        self.assertAlmostEqual(float(outer.width), 220.0)
        self.assertAlmostEqual(float(outer.height), 120.0)
        self.assertAlmostEqual(float(b.width), 200.0)
        self.assertAlmostEqual(float(outer.center.x), 400.0)
        self.assertAlmostEqual(float(outer.center.y), 300.0)

    def test_outset_zero_is_same_size_new_object(self):
        b = Box(center=(400, 300), width=200, height=100)
        copy = b.outset(0)
        self.assertIsNot(copy, b)
        self.assertAlmostEqual(float(copy.width), 200.0)
        self.assertAlmostEqual(float(copy.height), 100.0)

    def test_outset_negative_raises(self):
        b = Box(center=(400, 300), width=20, height=20)
        with self.assertRaises(ValueError) as ctx:
            b.outset(-1)
        self.assertIn("outset", str(ctx.exception))

    def test_outset_from_line(self):
        line = Box(center=(400, 300), width=50, height=0)
        outer = line.outset(10)
        self.assertAlmostEqual(float(outer.width), 70.0)
        self.assertAlmostEqual(float(outer.height), 20.0)

    def test_outset_from_point(self):
        point = Box(center=(400, 300), width=0, height=0)
        outer = point.outset(10)
        self.assertAlmostEqual(float(outer.width), 20.0)
        self.assertAlmostEqual(float(outer.height), 20.0)

    def test_outset_then_inset_roundtrip(self):
        for src in (
            Box(center=(400, 300), width=200, height=100),
            Box(center=(400, 300), width=50, height=0),
            Box(center=(400, 300), width=0, height=0),
        ):
            m = 10.0
            back = src.outset(m).inset(m)
            self.assertAlmostEqual(float(back.width), float(src.width))
            self.assertAlmostEqual(float(back.height), float(src.height))
            self.assertAlmostEqual(float(back.center.x), float(src.center.x))
            self.assertAlmostEqual(float(back.center.y), float(src.center.y))

    def test_inset_then_outset_roundtrip(self):
        b = Box(center=(400, 300), width=200, height=100)
        back = b.inset(10).outset(10)
        self.assertAlmostEqual(float(back.width), 200.0)
        self.assertAlmostEqual(float(back.height), 100.0)
        # Clamped inset does not recover the original.
        clamped = Box(center=(400, 300), width=20, height=20).inset(12).outset(12)
        self.assertAlmostEqual(float(clamped.width), 24.0)
        self.assertAlmostEqual(float(clamped.height), 24.0)

    def test_outset_keeps_angle(self):
        b = Box(center=(400, 300), width=200, height=100, angle=25)
        outer = b.outset(8)
        self.assertAlmostEqual(float(outer.angle), 25.0)

    def test_contains_point_zero_area_is_false(self):
        line = Box(center=(400, 300), width=50, height=0)
        point = Box(center=(400, 300), width=0, height=0)
        self.assertFalse(line.contains_point(400, 300))
        self.assertFalse(point.contains_point(400, 300))

    def test_is_collapsed_normal_false(self):
        b = Box(center=(400, 300), width=100, height=50)
        self.assertFalse(b.is_collapsed)

    def test_is_collapsed_line_and_point(self):
        line = Box(center=(400, 300), width=50, height=0)
        point = Box(center=(400, 300), width=0, height=0)
        self.assertTrue(line.is_collapsed)
        self.assertTrue(point.is_collapsed)

    def test_is_collapsed_after_inset_remainder(self):
        line = Box(center=(400, 300), width=59.2, height=3.84).inset(4)
        point = Box(center=(400, 300), width=20, height=20).inset(12)
        self.assertTrue(line.is_collapsed)
        self.assertTrue(point.is_collapsed)
        normal = Box(center=(400, 300), width=200, height=100).inset(10)
        self.assertFalse(normal.is_collapsed)

    def test_contains_point(self):
        b = Box(center=(400, 300), width=100, height=50)
        self.assertTrue(b.contains_point(400, 300))
        self.assertTrue(b.contains_point((400, 300)))
        self.assertFalse(b.contains_point(0, 0))

    def test_oriented_contains_point(self):
        b = Box(center=(400, 300), width=200, height=20, angle=45)
        self.assertTrue(b.contains_point(400, 300))
        # A point on the local +x axis, far in AABB-x but inside the thin rotated bar.
        import math
        rad = math.radians(45)
        px = 400 + 80 * math.cos(rad)
        py = 300 + 80 * math.sin(rad)
        self.assertTrue(b.contains_point(px, py))
        self.assertFalse(b.contains_point(400 + 80, 300))

    def test_beside_same_size_flush_aabb(self):
        b = Box(center=(400, 300), width=200, height=100)
        right = b.beside("right")
        left = b.beside("left")
        top = b.beside("top")
        bottom = b.beside("bottom")
        for n in (right, left, top, bottom):
            self.assertAlmostEqual(float(n.width), 200.0)
            self.assertAlmostEqual(float(n.height), 100.0)
            self.assertAlmostEqual(float(n.angle), 0.0)
        self.assertAlmostEqual(float(right.center.x), 600.0)
        self.assertAlmostEqual(float(right.center.y), 300.0)
        self.assertAlmostEqual(float(left.center.x), 200.0)
        self.assertAlmostEqual(float(left.center.y), 300.0)
        self.assertAlmostEqual(float(top.center.x), 400.0)
        self.assertAlmostEqual(float(top.center.y), 400.0)
        self.assertAlmostEqual(float(bottom.center.x), 400.0)
        self.assertAlmostEqual(float(bottom.center.y), 200.0)
        self.assertAlmostEqual(float(b.center.x), 400.0)

    def test_beside_size_inheritance(self):
        b = Box(center=(400, 300), width=200, height=100)
        sidebar = b.beside("right", width=120)
        self.assertAlmostEqual(float(sidebar.width), 120.0)
        self.assertAlmostEqual(float(sidebar.height), 100.0)
        self.assertAlmostEqual(float(sidebar.center.x), 560.0)
        caption = b.beside("bottom", height=40)
        self.assertAlmostEqual(float(caption.width), 200.0)
        self.assertAlmostEqual(float(caption.height), 40.0)
        self.assertAlmostEqual(float(caption.center.y), 230.0)
        tile = b.beside("left", width=80, height=60)
        self.assertAlmostEqual(float(tile.width), 80.0)
        self.assertAlmostEqual(float(tile.height), 60.0)
        self.assertAlmostEqual(float(tile.center.x), 260.0)
        self.assertAlmostEqual(float(tile.center.y), 300.0)

    def test_beside_gap(self):
        b = Box(center=(400, 300), width=200, height=100)
        rail = b.beside("left", width=64, gap=8)
        self.assertAlmostEqual(float(rail.width), 64.0)
        self.assertAlmostEqual(float(rail.center.x), 260.0)  # 400 - (200+64)/2 - 8
        self.assertAlmostEqual(float(rail.center.y), 300.0)

    def test_beside_rotated(self):
        import math
        from scena.box import oriented_xy

        b = Box(center=(400, 300), width=200, height=100, angle=35)
        n = b.beside("right", width=80)
        self.assertAlmostEqual(float(n.angle), 35.0)
        self.assertAlmostEqual(float(n.width), 80.0)
        self.assertAlmostEqual(float(n.height), 100.0)
        wx, wy = oriented_xy(400.0, 300.0, (200 + 80) / 2.0, 0.0, 35.0)
        self.assertAlmostEqual(float(n.center.x), wx, places=5)
        self.assertAlmostEqual(float(n.center.y), wy, places=5)
        # AABB corner math would be wrong once rotated.
        self.assertFalse(math.isclose(float(n.center.x), 540.0, abs_tol=1e-6))

    def test_beside_errors(self):
        b = Box(center=(400, 300), width=200, height=100)
        with self.assertRaises(ValueError) as ctx:
            b.beside("diagonal")
        self.assertIn("side", str(ctx.exception))
        with self.assertRaises(ValueError):
            b.beside("right", width=-1)
        with self.assertRaises(ValueError):
            b.beside("right", height=-1)
        with self.assertRaises(ValueError) as gctx:
            b.beside("right", gap=-2)
        self.assertIn("gap", str(gctx.exception))

    def test_beside_collapsed_source(self):
        line = Box(center=(400, 300), width=50, height=0)
        n = line.beside("top")
        self.assertAlmostEqual(float(n.width), 50.0)
        self.assertAlmostEqual(float(n.height), 0.0)
        self.assertAlmostEqual(float(n.center.x), 400.0)
        self.assertAlmostEqual(float(n.center.y), 300.0)
        self.assertTrue(n.is_collapsed)

    def test_beside_chaining(self):
        b = Box(center=(400, 300), width=100, height=80)
        far = b.beside("right").beside("right", width=40)
        self.assertAlmostEqual(float(far.width), 40.0)
        self.assertAlmostEqual(float(far.height), 80.0)
        # First same-size beside centers at 500; then width=40 beside → 570.
        self.assertAlmostEqual(float(far.center.x), 570.0)
        self.assertAlmostEqual(float(far.center.y), 300.0)

    def test_strip_four_sides_aabb(self):
        b = Box(center=(400, 300), width=200, height=100)
        top = b.strip("top", 20)
        bottom = b.strip("bottom", 20)
        left = b.strip("left", 30)
        right = b.strip("right", 30)
        self.assertAlmostEqual(float(top.width), 200.0)
        self.assertAlmostEqual(float(top.height), 20.0)
        self.assertAlmostEqual(float(top.center.x), 400.0)
        self.assertAlmostEqual(float(top.center.y), 340.0)  # 300 + (100-20)/2
        self.assertAlmostEqual(float(bottom.center.y), 260.0)
        self.assertAlmostEqual(float(left.width), 30.0)
        self.assertAlmostEqual(float(left.height), 100.0)
        self.assertAlmostEqual(float(left.center.x), 315.0)  # 400 - (200-30)/2
        self.assertAlmostEqual(float(right.center.x), 485.0)
        self.assertAlmostEqual(float(b.width), 200.0)

    def test_strip_rotated(self):
        from scena.box import oriented_xy

        b = Box(center=(400, 300), width=200, height=100, angle=35)
        band = b.strip("top", 20)
        self.assertAlmostEqual(float(band.angle), 35.0)
        self.assertAlmostEqual(float(band.width), 200.0)
        self.assertAlmostEqual(float(band.height), 20.0)
        wx, wy = oriented_xy(400.0, 300.0, 0.0, (100 - 20) / 2.0, 35.0)
        self.assertAlmostEqual(float(band.center.x), wx, places=5)
        self.assertAlmostEqual(float(band.center.y), wy, places=5)

    def test_strip_full_extent_is_same_frame(self):
        b = Box(center=(400, 300), width=200, height=100, angle=12)
        full = b.strip("top", 100)
        self.assertAlmostEqual(float(full.width), 200.0)
        self.assertAlmostEqual(float(full.height), 100.0)
        self.assertAlmostEqual(float(full.center.x), 400.0)
        self.assertAlmostEqual(float(full.center.y), 300.0)
        self.assertAlmostEqual(float(full.angle), 12.0)

    def test_strip_overshoot_clamps(self):
        b = Box(center=(400, 300), width=200, height=100)
        full = b.strip("top", 1e9)
        self.assertAlmostEqual(float(full.width), 200.0)
        self.assertAlmostEqual(float(full.height), 100.0)
        self.assertAlmostEqual(float(full.center.x), 400.0)
        self.assertAlmostEqual(float(full.center.y), 300.0)
        flat = Box(center=(400, 300), width=200, height=0).strip("top", 80)
        self.assertAlmostEqual(float(flat.height), 0.0)
        self.assertTrue(flat.is_collapsed)

    def test_strip_errors(self):
        b = Box(center=(400, 300), width=200, height=100)
        with self.assertRaises(ValueError) as ctx:
            b.strip("middle", 10)
        self.assertIn("side", str(ctx.exception))
        with self.assertRaises(ValueError) as tctx:
            b.strip("top", -1)
        self.assertIn("thickness", str(tctx.exception))


class TestGrid(BoxTestCase):
    def test_counts_and_iteration(self):
        zone = Box(center=(400, 300), width=400, height=200)
        g = zone.grid(8, 4, gap=16)
        self.assertEqual(g.col_count, 8)
        self.assertEqual(g.row_count, 4)
        self.assertEqual(len(g), 32)
        cells = list(g)
        self.assertEqual(len(cells), 32)
        # row 0 first, left→right
        self.assertEqual(cells[0].col_index, 0)
        self.assertEqual(cells[0].row_index, 0)
        self.assertEqual(cells[7].col_index, 7)
        self.assertEqual(cells[8].row_index, 1)

    def test_cell_col_row_and_flat(self):
        g = Box(center=(400, 300), width=400, height=200).grid(4, 3)
        a = g.cell(2, 1)
        b = g.cell(1 * 4 + 2)  # row-major flat: col = n % cols, row = n // cols
        self.assertIs(a, g.cell(2, 1))
        self.assertEqual(b.col_index, 2)
        self.assertEqual(b.row_index, 1)
        self.assertAlmostEqual(float(a.center.x), float(b.center.x))
        self.assertAlmostEqual(float(a.center.y), float(b.center.y))

    def test_rows_cols_lists(self):
        g = Box(center=(400, 300), width=400, height=200).grid(3, 2)
        self.assertEqual(len(g.rows), 2)
        self.assertEqual(len(g.rows[0]), 3)
        self.assertEqual(len(g.cols), 3)
        self.assertEqual(len(g.cols[0]), 2)
        self.assertIs(g.rows[1][2], g.cols[2][1])

    def test_row_zero_is_visual_top(self):
        g = Box(center=(400, 300), width=200, height=100).grid(2, 2, gap=0)
        top = g.cell(0, 0)
        bottom = g.cell(0, 1)
        self.assertGreater(float(top.center.y), float(bottom.center.y))

    def test_gap_tuple(self):
        g = Box(center=(400, 300), width=800, height=200).grid(4, 2, gap=(20, 10))
        c0 = g.cell(0, 0)
        c1 = g.cell(1, 0)
        dx = float(c1.center.x) - float(c0.center.x)
        self.assertAlmostEqual(dx, float(c0.width) + 20.0, places=5)

    def test_getitem_reserved(self):
        g = Box(center=(400, 300), width=100, height=100).grid(2, 2)
        with self.assertRaises(TypeError) as ctx:
            g[0, 1]
        self.assertIn("g.cell(col, row)", str(ctx.exception))

    def test_cell_at_axis_aligned(self):
        g = Box(center=(400, 300), width=400, height=200).grid(4, 2, gap=0)
        cell = g.cell(1, 0)
        hit = g.cell_at(cell.center.x, cell.center.y)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.col_index, 1)
        self.assertEqual(hit.row_index, 0)
        self.assertIsNone(g.cell_at(0, 0))
        self.assertIsNone(g.cell_at(cell.center.x + 10000, cell.center.y))

    def test_cell_at_oriented(self):
        zone = Box(center=(400, 300), width=200, height=100, angle=35)
        g = zone.grid(4, 2, gap=0)
        cell = g.cell(3, 1)
        hit = g.cell_at(cell.center)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.col_index, 3)
        self.assertEqual(hit.row_index, 1)
        self.assertAlmostEqual(float(cell.angle), 35.0)

    def test_cell_at_gap_is_none(self):
        g = Box(center=(400, 300), width=200, height=80).grid(2, 1, gap=40)
        left = g.cell(0, 0)
        right = g.cell(1, 0)
        mid_x = (float(left.right) + float(right.left)) / 2.0
        self.assertIsNone(g.cell_at(mid_x, 300))

    def test_no_parent_backref(self):
        g = Box(center=(400, 300), width=100, height=100).grid(2, 2)
        cell = g.cell(0, 0)
        self.assertFalse(hasattr(cell, "grid") and cell.grid is g)

    def test_gap_too_large_zero_size_cells(self):
        g = Box(center=(400, 300), width=100, height=50).grid(8, 3, gap=50)
        self.assertEqual(len(g), 24)
        for cell in g:
            self.assertAlmostEqual(float(cell.width), 0.0)
            self.assertAlmostEqual(float(cell.height), 0.0)
            self.assertTrue(cell.is_collapsed)
        # Placement math kept: first cell at local left, spaced by gap.
        self.assertAlmostEqual(float(g.cell(0, 0).center.x), 350.0)
        self.assertAlmostEqual(float(g.cell(1, 0).center.x), 400.0)

    def test_grid_of_point_box(self):
        g = Box(center=(400, 300), width=0, height=0).grid(2, 2, gap=0)
        self.assertEqual(len(g), 4)
        for cell in g:
            self.assertAlmostEqual(float(cell.width), 0.0)
            self.assertAlmostEqual(float(cell.height), 0.0)
            self.assertAlmostEqual(float(cell.center.x), 400.0)
            self.assertAlmostEqual(float(cell.center.y), 300.0)
        self.assertEqual(g.cell(1, 1).col_index, 1)
        self.assertEqual(g.cell(1, 1).row_index, 1)

    def test_nested_inset_after_grid(self):
        zone = Box(center=(400, 300), width=80, height=20)
        g = zone.inset(4).grid(6, 3, gap=10)
        for cell in g:
            inner = cell.inset(4)
            self.assertGreaterEqual(float(inner.width), 0.0)
            self.assertGreaterEqual(float(inner.height), 0.0)


# Grid geometry the properties below sample. Sizes stay above 1 unit so a cell
# is a region, not the Remainder line / point (covered by the examples above).
_extent = hst.floats(1.0, 500.0, allow_nan=False, allow_infinity=False)
_gap = hst.one_of(hst.just(0.0), hst.floats(0.0, 20.0, allow_nan=False))
_grid_angle = hst.one_of(hst.just(0.0), hst.floats(-180.0, 180.0, allow_nan=False))
_grid_center = hst.tuples(hst.floats(-300.0, 300.0), hst.floats(-300.0, 300.0))
_unit = hst.floats(0.0, 1.0, allow_nan=False)
# Keep sample points this far from any cell edge: exactly on an edge, the
# cell's own frame and the grid's frame round differently and may disagree
# by one ulp (both include the edge). Testing Design § Harness pitfalls.
_EDGE = 1e-6


def _local_to_world(box_center, ang, lx, ly):
    a = math.radians(ang)
    cx, cy = box_center
    return (cx + lx * math.cos(a) - ly * math.sin(a),
            cy + lx * math.sin(a) + ly * math.cos(a))


class TestGridCoversBoxProperty(BoxTestCase):
    """Cell placement (``_make_cell``) and ``cell_at`` (``_index_along``) are
    separate code. Both must describe one tiling of the Box: cells in order,
    gaps between them, nothing outside, nothing overlapping."""

    @given(w=_extent, h=_extent, ang=_grid_angle, center=_grid_center,
           cols=hst.integers(1, 9), rows=hst.integers(1, 9), gx=_gap, gy=_gap,
           samples=hst.lists(hst.tuples(_unit, _unit), min_size=1, max_size=20))
    def test_cell_at_matches_closed_form(self, w, h, ang, center, cols, rows,
                                         gx, gy, samples):
        cw = (w - gx * (cols - 1)) / cols
        ch = (h - gy * (rows - 1)) / rows
        assume(cw > 1e-3 and ch > 1e-3)
        g = Box(center=center, width=w, height=h, angle=ang).grid(cols, rows, gap=(gx, gy))
        for u, v in samples:
            # Measured from the local top-left: row 0 is the visual top.
            fx, fy = u * w, v * h
            col, ux = divmod(fx, cw + gx)
            row, uy = divmod(fy, ch + gy)
            if min(ux, abs(ux - cw), uy, abs(uy - ch)) < _EDGE:
                continue
            col, row = min(int(col), cols - 1), min(int(row), rows - 1)
            want = (col, row) if ux < cw and uy < ch else None
            px, py = _local_to_world(center, ang, fx - w / 2.0, h / 2.0 - fy)
            hit = g.cell_at(px, py)
            got = None if hit is None else (hit.col_index, hit.row_index)
            self.assertEqual(got, want, f"cell_at at local ({fx}, {fy})")
            if hit is not None:
                self.assertTrue(hit.contains_point((px, py)),
                                "cell_at returned a cell that does not contain the point")

    @given(w=_extent, h=_extent, ang=_grid_angle, center=_grid_center,
           cols=hst.integers(1, 9), rows=hst.integers(1, 9), gx=_gap, gy=_gap)
    def test_cells_tile_the_box(self, w, h, ang, center, cols, rows, gx, gy):
        usable_w = w - gx * (cols - 1)
        usable_h = h - gy * (rows - 1)
        assume(usable_w > 1e-3 and usable_h > 1e-3)
        box = Box(center=center, width=w, height=h, angle=ang)
        g = box.grid(cols, rows, gap=(gx, gy))
        tol = 1e-9 * max(w, h, 1.0)
        # Area: cells fill exactly what the gaps leave (w * h when gap=0).
        area = sum(float(c.width) * float(c.height) for c in g)
        self.assertTrue(math.isclose(area, usable_w * usable_h, rel_tol=1e-9),
                        f"cells cover {area}, expected {usable_w * usable_h}")
        # Inside: every cell corner lies in the Box (edge included, ulp slack).
        slack = box.outset(tol)
        for c in g:
            self.assertAlmostEqual(float(c.angle), float(box.angle))
            for p in (c.top_left, c.top_right, c.bottom_left, c.bottom_right):
                self.assertTrue(slack.contains_point(p),
                                f"cell ({c.col_index}, {c.row_index}) corner outside its Box")
        # No overlap, no hole: neighbours sit exactly one cell + gap apart
        # along the Box's own axes (with containment and counts, a tiling).
        a = math.radians(float(box.angle))
        ux, uy = (math.cos(a), math.sin(a)), (-math.sin(a), math.cos(a))

        def along(p, q, axis):
            return (float(q.x) - float(p.x)) * axis[0] + (float(q.y) - float(p.y)) * axis[1]

        for row in g.rows:
            for left, right in zip(row, row[1:]):
                self.assertAlmostEqual(along(left.center, right.center, ux),
                                       float(left.width) + gx, delta=tol * 10)
                self.assertAlmostEqual(along(left.center, right.center, uy), 0.0,
                                       delta=tol * 10)
        for col in g.cols:
            for top, below in zip(col, col[1:]):
                self.assertAlmostEqual(along(below.center, top.center, uy),
                                       float(top.height) + gy, delta=tol * 10)
                self.assertAlmostEqual(along(below.center, top.center, ux), 0.0,
                                       delta=tol * 10)


class TestGridPropertyCanaries(BoxTestCase):
    """The Grid properties catch a placement / lookup drift (SCENA_CANARIES)."""

    def test_lookup_that_ignores_gaps_is_caught(self):
        from diff_support import assert_catches

        def no_gap_index(pos, count, cell, gap):
            return min(int(pos // cell), count - 1) if cell > 0 else None

        assert_catches(self, "test_box.TestGridCoversBoxProperty.test_cell_at_matches_closed_form",
                       [(Grid, "_index_along", staticmethod(no_gap_index))],
                       "cell_at that ignores gaps")

    def test_placement_that_ignores_gaps_is_caught(self):
        from diff_support import assert_catches
        original = Grid._local_cell

        def packed(self, col, row):
            gx, gy = self._gap_x, self._gap_y
            self._gap_x = self._gap_y = 0.0
            try:
                return original(self, col, row)
            finally:
                self._gap_x, self._gap_y = gx, gy

        assert_catches(self, "test_box.TestGridCoversBoxProperty.test_cells_tile_the_box",
                       [(Grid, "_local_cell", packed)], "cells packed without gaps")


class TestParents(BoxTestCase):
    def test_game_view_identity(self):
        v = canvas.game_view
        self.assertIsInstance(v, Box)
        self.assertAlmostEqual(v.left, 0.0)
        self.assertAlmostEqual(v.bottom, 0.0)
        self.assertAlmostEqual(v.width, 1000.0)
        self.assertAlmostEqual(v.height, 800.0)
        v2 = canvas.game_view
        self.assertIsNot(v, v2)

    def test_ui_view_stable_after_pan(self):
        ui0 = canvas.ui_view
        canvas.pan_to(200, 150).zoom_to(2.0)
        ui1 = canvas.ui_view
        self.assertAlmostEqual(ui1.left, ui0.left)
        self.assertAlmostEqual(ui1.width, 1000.0)
        self.assertAlmostEqual(float(canvas.game_view.center.x), 200.0, places=4)

    def test_playfield_is_not_box(self):
        pf = canvas.playfield
        self.assertNotIsInstance(pf, Box)
        inner = pf.inset(10)
        self.assertIsInstance(inner, Box)
        self.assertEqual(pf.pad, 0.25)
        g = pf.grid(2, 2)
        self.assertIsInstance(g, Grid)
        self.assertEqual(pf.pad, 0.25)

    def test_playfield_inset_clamps(self):
        pf = canvas.playfield
        huge = pf.inset(1e9)
        self.assertIsInstance(huge, Box)
        self.assertAlmostEqual(float(huge.width), 0.0)
        self.assertAlmostEqual(float(huge.height), 0.0)
        self.assertEqual(pf.pad, 0.25)

    def test_playfield_outset_does_not_write_pad(self):
        pf = canvas.playfield
        snap = pf._as_box()
        outer = pf.outset(40)
        self.assertIsInstance(outer, Box)
        self.assertEqual(pf.pad, 0.25)
        self.assertAlmostEqual(float(outer.width), float(snap.width) + 80.0)
        self.assertAlmostEqual(float(outer.height), float(snap.height) + 80.0)

    def test_playfield_beside_does_not_write_pad(self):
        pf = canvas.playfield
        snap = pf._as_box()
        side = pf.beside("right", width=120)
        self.assertIsInstance(side, Box)
        self.assertEqual(pf.pad, 0.25)
        self.assertAlmostEqual(float(side.width), 120.0)
        self.assertAlmostEqual(float(side.height), float(snap.height))

    def test_playfield_strip_does_not_write_pad(self):
        pf = canvas.playfield
        snap = pf._as_box()
        band = pf.strip("top", 80)
        self.assertIsInstance(band, Box)
        self.assertEqual(pf.pad, 0.25)
        self.assertAlmostEqual(float(band.width), float(snap.width))
        self.assertAlmostEqual(float(band.height), 80.0)

    def test_playfield_alias(self):
        self.assertIs(canvas.bounds, canvas.playfield)


class TestBoxFitContract(BoxTestCase):
    def test_rect_fills(self):
        cell = Box(center=(200, 150), width=80, height=40, angle=12)
        r = self.track(Rect(box=cell, color="sienna"))
        self.assertAlmostEqual(float(r.width), 80.0)
        self.assertAlmostEqual(float(r.height), 40.0)
        self.assertAlmostEqual(float(r.angle), 12.0)
        self.assertAlmostEqual(float(r.center.x), 200.0)

    def test_ellipse_fills(self):
        cell = Box(center=(200, 150), width=80, height=40)
        e = self.track(Ellipse(box=cell))
        self.assertAlmostEqual(float(e.width), 80.0)
        self.assertAlmostEqual(float(e.height), 40.0)

    def test_circle_inscribes(self):
        cell = Box(center=(200, 150), width=80, height=40)
        c = self.track(Circle(box=cell))
        self.assertAlmostEqual(float(c.radius), 20.0)
        self.assertAlmostEqual(float(c.center.x), 200.0)

    def test_circle_radius_override_centers_only(self):
        cell = Box(center=(200, 150), width=80, height=40)
        c = self.track(Circle(box=cell, radius=7))
        self.assertAlmostEqual(float(c.radius), 7.0)
        self.assertAlmostEqual(float(c.center.x), 200.0)

    def test_square_inscribes(self):
        cell = Box(center=(200, 150), width=80, height=40)
        s = self.track(Square(box=cell))
        self.assertAlmostEqual(float(s.length), 40.0)

    def test_regular_polygon_inscribes(self):
        cell = Box(center=(200, 150), width=80, height=40)
        p = self.track(RegularPolygon(box=cell, n=6))
        self.assertAlmostEqual(float(p.radius), 20.0)

    def test_equilateral_triangle_inscribes(self):
        cell = Box(center=(200, 150), width=80, height=40)
        t = self.track(Triangle(box=cell))
        self.assertAlmostEqual(float(t.radius), 20.0)

    def test_sprite_height_override(self):
        cell = Box(center=(200, 150), width=80, height=40)
        sp = self.track(Sprite(box=cell, height=18))
        self.assertAlmostEqual(float(sp.height), 18.0)
        self.assertAlmostEqual(float(sp.center.x), 200.0)
        self.assertAlmostEqual(float(sp.center.y), 150.0)

    def test_sprite_uniform_fit_inherits_angle(self):
        cell = Box(center=(200, 150), width=80, height=40, angle=18)
        sp = self.track(Sprite(box=cell))
        self.assertAlmostEqual(float(sp.angle), 18.0, places=4)

    def test_mix_raises(self):
        cell = Box(center=(200, 150), width=80, height=40)
        with self.assertRaises(TypeError):
            Rect(box=cell, width=10)
        with self.assertRaises(TypeError):
            Circle(box=cell, center=(0, 0))

    def test_line_rejects_box(self):
        cell = Box(center=(200, 150), width=80, height=40)
        with self.assertRaises(TypeError):
            Line(box=cell)

    def test_text_box_view_pin(self):
        ui = canvas.ui_view.inset(24)
        t = self.track(Text("Score", box=ui.grid(1, 8).cell(0, 0), font_size=20))
        self.assertEqual(t.layer, "ui")

    def test_text_box_is_centred_in_the_region(self):
        """Bugs A/B: box= fed the region centre to the bottom-left edge (the
        caption sat half its height high) and to the align edge (left/right
        shifted the region-wide box by half a width)."""
        cell = Box(center=(200, 150), width=160, height=60)
        for align in ("left", "center", "right"):
            for text in ("Score", "Score\nLevel 2\nx"):
                with self.subTest(align=align, text=text):
                    t = self.track(Text(text, box=cell, font_size=20, align=align))
                    t._refresh_layout()
                    self.assertAlmostEqual(float(t.center.x), 200.0)
                    self.assertAlmostEqual(float(t.center.y), 150.0)
                    self.assertAlmostEqual(0.5 * (t._x1 + t._x2), 200.0)
                    self.assertAlmostEqual(0.5 * (t._y1 + t._y2), 150.0)
                    self.assertAlmostEqual(t._x2 - t._x1, 160.0)
                    self.assertEqual(t.align, align)

    def test_text_box_stays_centred_as_the_string_changes(self):
        cell = Box(center=(300, 200), width=200, height=80)
        t = self.track(Text("1", box=cell, font_size=20))
        t.text = "1\n2\n3"
        t._refresh_layout()
        self.assertAlmostEqual(0.5 * (t._y1 + t._y2), 200.0)

    def test_text_box_does_not_join_the_hud_column(self):
        from scena.orchestration import ScenaFramework
        wm = ScenaFramework.get_instance().widget_manager
        before = (wm._stack_x, wm._stack_bottom, wm._column_top)
        self.track(Text("Score", box=Box(center=(300, 300), width=100, height=40)))
        self.assertEqual((wm._stack_x, wm._stack_bottom, wm._column_top), before)

    def test_text_box_with_world_layer(self):
        cell = Box(center=(10, 20), width=100, height=40)
        t = self.track(Text("W", box=cell, layer="default"))
        self.assertEqual(t.layer, "default")
        self.assertAlmostEqual(float(t.center.x), 10.0)

    def test_text_mix_with_center_raises(self):
        cell = Box(center=(200, 150), width=80, height=40)
        with self.assertRaises(TypeError):
            Text("nope", box=cell, center=(0, 0))

    def test_rect_fills_zero_size(self):
        cell = Box(center=(200, 150), width=0, height=0)
        r = self.track(Rect(box=cell, color="sienna"))
        self.assertAlmostEqual(float(r.width), 0.0)
        self.assertAlmostEqual(float(r.height), 0.0)
        self.assertAlmostEqual(float(r.center.x), 200.0)

    def test_circle_inscribes_zero_size(self):
        cell = Box(center=(200, 150), width=51.2, height=0)
        c = self.track(Circle(box=cell, color="gold"))
        self.assertAlmostEqual(float(c.radius), 0.0)
        self.assertAlmostEqual(float(c.center.x), 200.0)

    def test_sprite_contain_zero_size(self):
        cell = Box(center=(200, 150), width=0, height=0)
        sp = self.track(Sprite(box=cell))
        self.assertAlmostEqual(float(sp.width), 0.0)
        self.assertAlmostEqual(float(sp.height), 0.0)
        self.assertAlmostEqual(float(sp.center.x), 200.0)
        self.assertAlmostEqual(float(sp.center.y), 150.0)

    def test_sprite_height_override_on_point_box(self):
        cell = Box(center=(200, 150), width=0, height=0)
        sp = self.track(Sprite(box=cell, height=36))
        self.assertAlmostEqual(float(sp.height), 36.0)
        self.assertAlmostEqual(float(sp.center.x), 200.0)
        self.assertAlmostEqual(float(sp.center.y), 150.0)

    def test_text_zero_width_is_content_pin(self):
        cell = Box(center=(200, 150), width=0, height=0)
        t = self.track(Text("Score", box=cell, layer="ui", font_size=20))
        self.assertEqual(t.layer, "ui")
        self.assertIsNone(t.width)   # zero-width region: the box follows the string
        self.assertAlmostEqual(float(t.center.x), 200.0)
        self.assertAlmostEqual(float(t.center.y), 150.0)

    def test_text_graphic_box(self):
        t = self.track(Text("Score", top_left=(20, 300), font_size=20))
        b = t.box
        self.assertAlmostEqual(float(b.top_left.x), 20.0)
        self.assertAlmostEqual(float(b.top_left.y), 300.0)


class TestGraphicBoxBridge(BoxTestCase):
    def test_rect_box_snapshot(self):
        panel = self.track(Rect(center=(400, 300), width=480, height=480, color="sienna"))
        b1 = panel.box
        self.assertIsInstance(b1, Box)
        self.assertAlmostEqual(float(b1.width), 480.0)
        panel.move_by(50, 0)
        b2 = panel.box
        self.assertIsNot(b1, b2)
        self.assertAlmostEqual(float(b1.center.x), 400.0)
        self.assertAlmostEqual(float(b2.center.x), 450.0)

    def test_circle_box_is_diameter_square(self):
        c = self.track(Circle(center=(100, 80), radius=25))
        b = c.box
        self.assertAlmostEqual(float(b.width), 50.0)
        self.assertAlmostEqual(float(b.height), 50.0)

    def test_line_has_no_box(self):
        ln = self.track(Line(p1=(0, 0), p2=(10, 10)))
        with self.assertRaises(TypeError) as ctx:
            _ = ln.box
        self.assertIn("unsupported", str(ctx.exception))

    def test_polygon_has_no_box(self):
        poly = self.track(Polygon(points=[(0, 0), (10, 0), (5, 8)]))
        with self.assertRaises(TypeError):
            _ = poly.box

    def test_grid_over_panel(self):
        panel = self.track(Rect(center=(400, 300), width=480, height=480))
        squares = panel.box.inset(8).grid(8, 8)
        self.assertEqual(squares.col_count, 8)
        self.assertEqual(len(list(squares)), 64)


class TestBoxGeometryHelpers(BoxTestCase):
    def test_intersections_with_line(self):
        b = Box(center=(400, 300), width=100, height=100)
        ln = self.track(Line(p1=(300, 300), p2=(500, 300)))
        hits = intersections(ln, b)
        self.assertGreaterEqual(len(hits), 1)

    def test_closest_point(self):
        b = Box(center=(400, 300), width=100, height=50)
        p = closest_point(b, (400, 300))
        self.assertAlmostEqual(p[0], 400.0, places=4)
        self.assertAlmostEqual(p[1], 300.0, places=4)


class TestBoxVerbsGateTheirParts(unittest.TestCase):
    """Phase-8 mutation survivor (geometry campaign): deleting Box.rotate_by's
    gate on ``p1`` passed every suite. A linked corner refuses the turn, and
    the refusal changes nothing."""

    def test_a_linked_corner_refuses_a_turn(self):
        from scena import Box, State
        from scena.state import LinkedAttributeError
        st = State(name="boxgate")
        st.x = 0.0
        b = Box(p1=(0, 0), p2=(10, 4))
        b["p1"] @= lambda: (st.x, 0.0)
        before = (float(b.p2.x), float(b.p2.y))
        with self.assertRaises(LinkedAttributeError):
            b.rotate_by(10)
        self.assertEqual((float(b.p2.x), float(b.p2.y)), before)


if __name__ == "__main__":
    unittest.main()
