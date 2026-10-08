"""Stage 0 gates: flatten, arc-length, sample, smooth=0, closed wrap, reversal."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.curves import (
    SAMPLES_HIGH,
    SAMPLES_LOW,
    arc_length_table,
    build_table,
    flatten_controls,
    sample,
    sample_span,
    sample_tangent,
    samples_per_segment_for,
    subpolyline,
)


def _integrate_polyline(xs, ys, closed=False) -> float:
    n = len(xs)
    total = 0.0
    last = n if not closed else n
    for i in range(1, n):
        total += math.hypot(xs[i] - xs[i - 1], ys[i] - ys[i - 1])
    if closed and n >= 2:
        total += math.hypot(xs[0] - xs[-1], ys[0] - ys[-1])
    return total


class TestSmoothZero(unittest.TestCase):
    def test_smooth_zero_is_polyline(self):
        pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
        xs, ys = flatten_controls(pts, closed=False, smooth=0.0, samples_per_segment=16)
        self.assertEqual(len(xs), 3)
        self.assertEqual(xs, [0.0, 10.0, 10.0])
        self.assertEqual(ys, [0.0, 0.0, 10.0])

    def test_smooth_false_same_as_zero(self):
        pts = [(0.0, 0.0), (4.0, 0.0), (4.0, 3.0)]
        a = flatten_controls(pts, closed=False, smooth=0.0, samples_per_segment=8)
        b = flatten_controls(pts, closed=False, smooth=False, samples_per_segment=8)
        self.assertEqual(a, b)

    def test_polyline_sample_constant_speed(self):
        pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
        xs, ys, s = build_table(pts, closed=False, smooth=0.0, samples_per_segment=4)
        self.assertAlmostEqual(s[-1], 20.0, places=9)
        x, y = sample(xs, ys, s, 0.0, closed=False)
        self.assertAlmostEqual(x, 0.0)
        self.assertAlmostEqual(y, 0.0)
        x, y = sample(xs, ys, s, 0.5, closed=False)
        self.assertAlmostEqual(x, 10.0)
        self.assertAlmostEqual(y, 0.0)
        x, y = sample(xs, ys, s, 0.75, closed=False)
        self.assertAlmostEqual(x, 10.0)
        self.assertAlmostEqual(y, 5.0)
        x, y = sample(xs, ys, s, 1.0, closed=False)
        self.assertAlmostEqual(x, 10.0)
        self.assertAlmostEqual(y, 10.0)


class TestArcLength(unittest.TestCase):
    def test_matches_numeric_polyline_sum(self):
        pts = [(0.0, 0.0), (3.0, 0.0), (3.0, 4.0)]
        xs, ys, s = build_table(pts, closed=False, smooth=0.0, samples_per_segment=4)
        self.assertAlmostEqual(s[-1], 7.0, places=9)
        self.assertEqual(s[0], 0.0)
        for i in range(1, len(s)):
            self.assertGreaterEqual(s[i], s[i - 1] - 1e-12)

    def test_cubic_vs_dense_integration(self):
        pts = [(0.0, 0.0), (20.0, 40.0), (80.0, 10.0), (120.0, 50.0)]
        xs, ys, s = build_table(pts, closed=False, smooth=1.0, samples_per_segment=32)
        # Independent numeric integration along the same flattened polyline.
        numeric = _integrate_polyline(xs, ys, closed=False)
        self.assertAlmostEqual(s[-1], numeric, places=9)
        # Table is monotonic.
        for i in range(1, len(s)):
            self.assertGreaterEqual(s[i] + 1e-12, s[i - 1])

    def test_equal_u_covers_equal_distance(self):
        pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        xs, ys, s = build_table(pts, closed=False, smooth=0.0, samples_per_segment=4)
        self.assertAlmostEqual(s[-1], 30.0, places=9)
        # Three equal-length sides: u = 0, 1/3, 2/3, 1 land on the vertices.
        self.assertEqual(sample(xs, ys, s, 0.0, closed=False), (0.0, 0.0))
        x, y = sample(xs, ys, s, 1.0 / 3.0, closed=False)
        self.assertAlmostEqual(x, 10.0)
        self.assertAlmostEqual(y, 0.0)
        x, y = sample(xs, ys, s, 2.0 / 3.0, closed=False)
        self.assertAlmostEqual(x, 10.0)
        self.assertAlmostEqual(y, 10.0)
        x, y = sample(xs, ys, s, 1.0, closed=False)
        self.assertAlmostEqual(x, 0.0)
        self.assertAlmostEqual(y, 10.0)


class TestClosedWrap(unittest.TestCase):
    def test_u0_equals_u1(self):
        pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        xs, ys, s = build_table(pts, closed=True, smooth=0.0, samples_per_segment=4)
        a = sample(xs, ys, s, 0.0, closed=True)
        b = sample(xs, ys, s, 1.0, closed=True)
        self.assertAlmostEqual(a[0], b[0], places=9)
        self.assertAlmostEqual(a[1], b[1], places=9)

    def test_wrap_continuity(self):
        pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        xs, ys, s = build_table(pts, closed=True, smooth=0.0, samples_per_segment=4)
        p_lo = sample(xs, ys, s, 0.02, closed=True)
        p_hi = sample(xs, ys, s, 0.98, closed=True)
        # Both near the start vertex along the closing edge / first edge.
        # Distance between them should be a small fraction of the perimeter.
        d = math.hypot(p_lo[0] - p_hi[0], p_lo[1] - p_hi[1])
        self.assertLess(d, 0.25 * s[-1])

    def test_closed_length_includes_wrap(self):
        pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        xs, ys, s = build_table(pts, closed=True, smooth=0.0, samples_per_segment=4)
        self.assertAlmostEqual(s[-1], 40.0, places=9)
        self.assertEqual(len(s), len(xs) + 1)


class TestReversal(unittest.TestCase):
    def test_sample_one_minus_u(self):
        pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 6.0)]
        xs, ys, s = build_table(pts, closed=False, smooth=0.0, samples_per_segment=4)
        for u in (0.0, 0.25, 0.5, 0.8, 1.0):
            fwd = sample(xs, ys, s, u, closed=False, reversed=False)
            rev = sample(xs, ys, s, u, closed=False, reversed=True)
            back = sample(xs, ys, s, 1.0 - u, closed=False, reversed=False)
            self.assertAlmostEqual(rev[0], back[0], places=9)
            self.assertAlmostEqual(rev[1], back[1], places=9)
            # And the reversed sample at 0 is the original end.
        self.assertAlmostEqual(
            sample(xs, ys, s, 0.0, closed=False, reversed=True)[1], 6.0,
        )

    def test_tangent_flips(self):
        pts = [(0.0, 0.0), (10.0, 0.0)]
        xs, ys, s = build_table(pts, closed=False, smooth=0.0, samples_per_segment=2)
        tx, ty = sample_tangent(xs, ys, s, 0.5, closed=False, reversed=False)
        rx, ry = sample_tangent(xs, ys, s, 0.5, closed=False, reversed=True)
        self.assertAlmostEqual(tx, -rx, places=6)
        self.assertAlmostEqual(ty, -ry, places=6)


class TestSampleDensity(unittest.TestCase):
    def test_quality_values(self):
        self.assertEqual(samples_per_segment_for("high"), SAMPLES_HIGH)
        self.assertEqual(samples_per_segment_for("low"), SAMPLES_LOW)
        self.assertLess(SAMPLES_LOW, SAMPLES_HIGH)

    def test_low_samples_still_monotonic(self):
        pts = [(0.0, 0.0), (5.0, 8.0), (16.0, 3.0), (22.0, 12.0)]
        xs, ys, s = build_table(
            pts, closed=False, smooth=1.0, samples_per_segment=SAMPLES_LOW,
        )
        self.assertGreaterEqual(len(xs), 2)
        for i in range(1, len(s)):
            self.assertGreaterEqual(s[i] + 1e-12, s[i - 1])
        # Continuous: adjacent samples are close relative to total length.
        span = sample_span(xs, ys, s, 0.0, 1.0, closed=False, n=20)
        total = s[-1]
        for i in range(1, len(span)):
            d = math.hypot(span[i][0] - span[i - 1][0], span[i][1] - span[i - 1][1])
            self.assertLess(d, 0.2 * total + 1e-9)

    def test_low_fewer_vertices_than_high(self):
        pts = [(0.0, 0.0), (10.0, 5.0), (20.0, 0.0), (30.0, 8.0)]
        lo = flatten_controls(
            pts, closed=False, smooth=1.0, samples_per_segment=SAMPLES_LOW,
        )
        hi = flatten_controls(
            pts, closed=False, smooth=1.0, samples_per_segment=SAMPLES_HIGH,
        )
        self.assertLess(len(lo[0]), len(hi[0]))


class TestSampleSpan(unittest.TestCase):
    def test_endpoints(self):
        pts = [(0.0, 0.0), (8.0, 0.0)]
        xs, ys, s = build_table(pts, closed=False, smooth=0.0, samples_per_segment=2)
        span = sample_span(xs, ys, s, 0.0, 1.0, closed=False, n=5)
        self.assertAlmostEqual(span[0][0], 0.0)
        self.assertAlmostEqual(span[-1][0], 8.0)


class TestSubpolyline(unittest.TestCase):
    def test_open_half(self):
        xs, ys, s = build_table([(0.0, 0.0), (10.0, 0.0)], closed=False, smooth=0.0, samples_per_segment=2)
        contours = subpolyline(xs, ys, s, 0.0, 0.5, closed=False)
        self.assertEqual(len(contours), 1)
        self.assertAlmostEqual(contours[0][0][0], 0.0)
        self.assertAlmostEqual(contours[0][-1][0], 5.0)

    def test_open_begin_after_end_is_empty(self):
        xs, ys, s = build_table([(0.0, 0.0), (10.0, 0.0)], closed=False, smooth=0.0, samples_per_segment=2)
        self.assertEqual(subpolyline(xs, ys, s, 0.8, 0.2, closed=False), [])
        self.assertEqual(subpolyline(xs, ys, s, 0.5, 0.5, closed=False), [])

    def test_clamps_outside_unit(self):
        xs, ys, s = build_table([(0.0, 0.0), (10.0, 0.0)], closed=False, smooth=0.0, samples_per_segment=2)
        lo = subpolyline(xs, ys, s, -2.0, 0.5, closed=False)
        hi = subpolyline(xs, ys, s, 0.0, 4.0, closed=False)
        self.assertAlmostEqual(lo[0][0][0], 0.0)
        self.assertAlmostEqual(lo[0][-1][0], 5.0)
        self.assertAlmostEqual(hi[0][-1][0], 10.0)

    def test_closed_wrap_two_contours(self):
        pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        xs, ys, s = build_table(pts, closed=True, smooth=0.0, samples_per_segment=2)
        contours = subpolyline(xs, ys, s, 0.75, 0.25, closed=True)
        self.assertEqual(len(contours), 2)
        # 0.75 → (0, 10); 1.0 / 0.0 → (0, 0); 0.25 → (10, 0)
        self.assertAlmostEqual(contours[0][0][1], 10.0)
        self.assertAlmostEqual(contours[0][-1][0], 0.0)
        self.assertAlmostEqual(contours[0][-1][1], 0.0)
        self.assertAlmostEqual(contours[1][0][0], 0.0)
        self.assertAlmostEqual(contours[1][-1][0], 10.0)

    def test_reversed_matches_sample(self):
        xs, ys, s = build_table([(0.0, 0.0), (10.0, 0.0), (10.0, 6.0)], closed=False, smooth=0.0, samples_per_segment=2)
        contours = subpolyline(xs, ys, s, 0.0, 0.5, closed=False, reversed=True)
        start = sample(xs, ys, s, 0.0, closed=False, reversed=True)
        end = sample(xs, ys, s, 0.5, closed=False, reversed=True)
        self.assertAlmostEqual(contours[0][0][0], start[0])
        self.assertAlmostEqual(contours[0][0][1], start[1])
        self.assertAlmostEqual(contours[0][-1][0], end[0])
        self.assertAlmostEqual(contours[0][-1][1], end[1])


if __name__ == "__main__":
    unittest.main()
