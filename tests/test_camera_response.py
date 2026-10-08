"""
Unit tests for camera_response (partial camera matrix + ScrollState).

Mirrors tests/test_background.py's TestParallaxTransform structure: neutral
response must equal ScenaCanvas._sync_camera; edge knobs stay finite.
"""
import dataclasses
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import skia

from scena.camera_response import (
    CameraResponse,
    ScrollState,
    partial_camera_matrix,
)
from scena.canvas import ScenaCanvas


def _matrix_maps(m: skia.Matrix, points):
    return [m.mapXY(float(x), float(y)) for x, y in points]


def _assert_matrices_equal(test, a: skia.Matrix, b: skia.Matrix, places=6):
    probes = [
        (0.0, 0.0),
        (100.0, 50.0),
        (-80.0, 120.0),
        (400.0, 300.0),
        (999.0, -40.0),
    ]
    for (x, y), pa, pb in zip(probes, _matrix_maps(a, probes), _matrix_maps(b, probes)):
        test.assertAlmostEqual(pa.x(), pb.x(), places=places, msg=f"x@{x},{y}")
        test.assertAlmostEqual(pa.y(), pb.y(), places=places, msg=f"y@{x},{y}")


class TestCameraResponseFrozen(unittest.TestCase):
    def test_defaults_neutral(self):
        r = CameraResponse()
        self.assertTrue(r.is_neutral)
        self.assertEqual(r.pan_response, 1.0)
        self.assertEqual(r.scroll, (0.0, 0.0))

    def test_non_neutral_pan_response(self):
        self.assertFalse(CameraResponse(pan_response=0.3).is_neutral)
        self.assertFalse(CameraResponse(zoom_response=0.5).is_neutral)
        self.assertFalse(CameraResponse(rotation_response=0.0).is_neutral)
        self.assertFalse(CameraResponse(scroll=(1.0, 0.0)).is_neutral)

    def test_epsilon_neutrality(self):
        self.assertTrue(CameraResponse(pan_response=1.0 + 1e-12).is_neutral)
        self.assertFalse(CameraResponse(pan_response=1.0 + 1e-3).is_neutral)

    def test_frozen(self):
        r = CameraResponse(pan_response=0.5)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.pan_response = 1.0  # type: ignore[misc]


class TestPartialCameraMatrixNeutralEqualsSync(unittest.TestCase):
    """Load-bearing: neutral response must match ScenaCanvas._sync_camera."""

    def setUp(self):
        self._prev = ScenaCanvas.get_current()

    def tearDown(self):
        if self._prev is not None:
            ScenaCanvas.set_current(self._prev)

    def _build_both(self, *, w, h, look_x, look_y, zoom, rotation, rest_x=None, rest_y=None):
        eng = ScenaCanvas(None, width=w, height=h)
        eng._look_x = float(look_x)
        eng._look_y = float(look_y)
        eng._zoom = float(zoom)
        eng._rotation = float(rotation)
        if rest_x is not None:
            eng._look_rest_x = float(rest_x)
        if rest_y is not None:
            eng._look_rest_y = float(rest_y)
        eng._sync_camera()
        full = eng.camera_matrix()
        rx = eng._look_rest_x
        ry = eng._look_rest_y
        neutral = partial_camera_matrix(
            cx=w * 0.5,
            cy=h * 0.5,
            look_x=look_x,
            look_y=look_y,
            zoom=zoom,
            rotation_deg=rotation,
            rest_x=rx,
            rest_y=ry,
            pan_response=1.0,
            zoom_response=1.0,
            rotation_response=1.0,
        )
        return full, neutral

    def test_identity_camera(self):
        full, neut = self._build_both(
            w=1000, h=800, look_x=500, look_y=400, zoom=1.0, rotation=0.0
        )
        _assert_matrices_equal(self, full, neut)
        # Design center maps to itself under identity look.
        p = neut.mapXY(500, 400)
        self.assertAlmostEqual(p.x(), 500.0, places=5)
        self.assertAlmostEqual(p.y(), 400.0, places=5)

    def test_pan_only(self):
        full, neut = self._build_both(
            w=1000, h=800, look_x=600, look_y=450, zoom=1.0, rotation=0.0
        )
        _assert_matrices_equal(self, full, neut)

    def test_zoom_only(self):
        full, neut = self._build_both(
            w=1000, h=800, look_x=500, look_y=400, zoom=2.5, rotation=0.0
        )
        _assert_matrices_equal(self, full, neut)

    def test_rotation_only(self):
        full, neut = self._build_both(
            w=1000, h=800, look_x=500, look_y=400, zoom=1.0, rotation=35.0
        )
        _assert_matrices_equal(self, full, neut)

    def test_combo_and_center_origin_rest(self):
        full, neut = self._build_both(
            w=1400,
            h=900,
            look_x=100,
            look_y=-50,
            zoom=1.8,
            rotation=-22.0,
            rest_x=0.0,
            rest_y=0.0,
        )
        _assert_matrices_equal(self, full, neut)


class TestPartialCameraMatrixResponse(unittest.TestCase):
    def test_pan_response_zero_screen_locked_for_pan(self):
        # rest = center; pan changes should not move content at pan_resp=0.
        cx, cy = 500.0, 400.0
        rest_id = partial_camera_matrix(
            cx=cx, cy=cy, look_x=cx, look_y=cy, zoom=1.0, rotation_deg=0.0,
            rest_x=cx, rest_y=cy, pan_response=0.0, zoom_response=0.0, rotation_response=0.0,
        )
        panned = partial_camera_matrix(
            cx=cx, cy=cy, look_x=cx + 200, look_y=cy + 100, zoom=1.0, rotation_deg=0.0,
            rest_x=cx, rest_y=cy, pan_response=0.0, zoom_response=0.0, rotation_response=0.0,
        )
        _assert_matrices_equal(self, rest_id, panned)

    def test_half_pan_response_and_zoom_lerp(self):
        cx, cy = 500.0, 400.0
        # Partial look halfway between rest and full look.
        half = partial_camera_matrix(
            cx=cx, cy=cy, look_x=700, look_y=500, zoom=2.0, rotation_deg=0.0,
            rest_x=cx, rest_y=cy, pan_response=0.5, zoom_response=0.5, rotation_response=0.0,
        )
        mid_look = partial_camera_matrix(
            cx=cx, cy=cy, look_x=600, look_y=450, zoom=1.5, rotation_deg=0.0,
            rest_x=cx, rest_y=cy, pan_response=1.0, zoom_response=1.0, rotation_response=0.0,
        )
        _assert_matrices_equal(self, half, mid_look)

    def test_rotation_response_halves_angle(self):
        cx, cy = 500.0, 400.0
        half = partial_camera_matrix(
            cx=cx, cy=cy, look_x=cx, look_y=cy, zoom=1.0, rotation_deg=90.0,
            rest_x=cx, rest_y=cy, pan_response=1.0, zoom_response=1.0, rotation_response=0.5,
        )
        full45 = partial_camera_matrix(
            cx=cx, cy=cy, look_x=cx, look_y=cy, zoom=1.0, rotation_deg=45.0,
            rest_x=cx, rest_y=cy, pan_response=1.0, zoom_response=1.0, rotation_response=1.0,
        )
        _assert_matrices_equal(self, half, full45)

    def test_rest_anchoring_no_rebake_at_rest(self):
        # At look == rest, every pan_response value must give the same matrix.
        refs = []
        for p in (0.0, 0.3, 1.0, 1.5, -0.5):
            m = partial_camera_matrix(
                cx=700, cy=450, look_x=0.0, look_y=0.0, zoom=1.0, rotation_deg=0.0,
                rest_x=0.0, rest_y=0.0, pan_response=p, zoom_response=0.0,
            )
            refs.append(m)
        for m in refs[1:]:
            _assert_matrices_equal(self, refs[0], m)

    def test_pan_response_gt_1_exaggerates(self):
        cx, cy = 500.0, 400.0
        # Compare mapping of a marker: exaggerated pan response > full.
        full = partial_camera_matrix(
            cx=cx, cy=cy, look_x=cx + 100, look_y=cy, zoom=1.0, rotation_deg=0.0,
            rest_x=cx, rest_y=cy, pan_response=1.0, zoom_response=1.0,
        )
        overt = partial_camera_matrix(
            cx=cx, cy=cy, look_x=cx + 100, look_y=cy, zoom=1.0, rotation_deg=0.0,
            rest_x=cx, rest_y=cy, pan_response=2.0, zoom_response=1.0,
        )
        # Marker at rest center: under pan right, content on screen moves left.
        pf = full.mapXY(cx, cy)
        po = overt.mapXY(cx, cy)
        # Both should place cx left of design center more as look moves right.
        self.assertLess(pf.x(), cx)
        self.assertLess(po.x(), pf.x())  # pan_response > 1 moves further

    def test_negative_pan_response_invertible(self):
        m = partial_camera_matrix(
            cx=500, cy=400, look_x=600, look_y=450, zoom=1.5, rotation_deg=10.0,
            rest_x=500, rest_y=400, pan_response=-0.5, zoom_response=0.5,
        )
        inv = skia.Matrix()
        self.assertTrue(m.invert(inv))
        p = m.mapXY(10, 20)
        back = inv.mapXY(p.x(), p.y())
        self.assertAlmostEqual(back.x(), 10.0, places=4)
        self.assertAlmostEqual(back.y(), 20.0, places=4)


class TestScrollState(unittest.TestCase):
    def test_accumulates_rate(self):
        s = ScrollState((10.0, -20.0))
        s.advance(0.0)
        s.advance(0.5)
        ax, ay = s.accum
        self.assertAlmostEqual(ax, 5.0, places=5)
        self.assertAlmostEqual(ay, -10.0, places=5)

    def test_reset_clears_offset_keeps_rate(self):
        s = ScrollState((10.0, 0.0))
        s.advance(0.0)
        s.advance(1.0)
        s.reset()
        self.assertEqual(s.accum, (0.0, 0.0))
        self.assertEqual(s.rate, (10.0, 0.0))

    def test_skips_huge_dt(self):
        s = ScrollState((100.0, 0.0))
        s.advance(0.0)
        s.advance(10.0)  # > 1.5s gap
        self.assertEqual(s.accum, (0.0, 0.0))

    def test_first_advance_seeds_only(self):
        s = ScrollState((100.0, 0.0))
        s.advance(1.0)
        self.assertEqual(s.accum, (0.0, 0.0))

    def test_nonfinite_rate_raises_and_time_is_skipped(self):
        with self.assertRaises(ValueError):
            ScrollState((float("nan"), 0.0))
        s = ScrollState((10.0, 0.0))
        with self.assertRaises(ValueError):
            s.rate = (float("inf"), 0.0)
        self.assertEqual(s.rate, (10.0, 0.0))
        s.advance(0.0)
        s.advance(float("nan"))
        self.assertEqual(s.accum, (0.0, 0.0))
        s.advance(0.5)
        self.assertAlmostEqual(s.accum[0], 5.0, places=5)


if __name__ == "__main__":
    unittest.main()
