"""Headless tests for windowed fit, letterbox pads, and canvas.display.

    python -m unittest tests.test_window_geom -v
"""
from __future__ import annotations

import ctypes
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import canvas, init
from scena.orchestration import (
    DISPLAY_FULLSCREEN,
    DISPLAY_MAXIMIZED,
    DISPLAY_WINDOWED,
    ScenaFramework,
    coerce_display_mode,
    fit_windowed_geom,
    letterbox_view,
)


class TestFitWindowedGeom(unittest.TestCase):
    def test_scale_one_is_max_work_area_fit(self):
        # 1600×900 work area, no chrome, 16:9 design → fills the work area.
        cw, ch, x, y = fit_windowed_geom(
            1600, 900, 1.0,
            work_x=0, work_y=0, work_w=1600, work_h=900,
        )
        self.assertEqual((cw, ch), (1600, 900))
        self.assertEqual((x, y), (0, 0))

    def test_scale_is_fraction_of_max_client(self):
        cw1, ch1, _, _ = fit_windowed_geom(
            1000, 700, 1.0,
            work_x=0, work_y=0, work_w=1920, work_h=1080,
        )
        cw8, ch8, _, _ = fit_windowed_geom(
            1000, 700, 0.8,
            work_x=0, work_y=0, work_w=1920, work_h=1080,
        )
        self.assertAlmostEqual(cw8 / cw1, 0.8, places=2)
        self.assertAlmostEqual(ch8 / ch1, 0.8, places=2)
        self.assertAlmostEqual(cw8 / ch8, 1000 / 700, places=3)

    def test_tall_design_fits_height_not_width_fraction(self):
        # Old window_frac took 0.8 of work width, then shrank. New scale is
        # 0.8 of the *max fit* — for a tall design that max is height-bound.
        cw, ch, x, y = fit_windowed_geom(
            400, 1200, 1.0,
            work_x=10, work_y=20, work_w=1920, work_h=1080,
        )
        self.assertEqual(ch, 1080)
        self.assertEqual(cw, 360)  # 1080 * (400/1200)
        # Centered in the leftover horizontal strip.
        self.assertEqual(x, 10 + (1920 - 360) // 2)
        self.assertEqual(y, 20)

    def test_insets_shrink_usable_client_and_center_outer_frame(self):
        # Work 1000×800, chrome 8/40/8/8 → usable 984×752.
        # Square design, scale 1 → client 752×752; outer 768×800.
        cw, ch, x, y = fit_windowed_geom(
            100, 100, 1.0,
            work_x=100, work_y=50, work_w=1000, work_h=800,
            left=8, top=40, right=8, bottom=8,
        )
        self.assertEqual((cw, ch), (752, 752))
        outer_w = cw + 8 + 8
        outer_h = ch + 40 + 8
        self.assertEqual(outer_w, 768)
        self.assertEqual(outer_h, 800)
        self.assertEqual(x, 100 + (1000 - 768) // 2)
        self.assertEqual(y, 50 + (800 - 800) // 2)

    def test_scale_clamps_above_one(self):
        a = fit_windowed_geom(800, 600, 1.0, 0, 0, 1280, 800)
        b = fit_windowed_geom(800, 600, 2.0, 0, 0, 1280, 800)
        self.assertEqual(a[:2], b[:2])

    def test_rejects_non_positive_scale(self):
        with self.assertRaises(ValueError):
            fit_windowed_geom(800, 600, 0.0, 0, 0, 1280, 800)
        with self.assertRaises(ValueError):
            fit_windowed_geom(800, 600, -0.5, 0, 0, 1280, 800)


class TestLetterboxView(unittest.TestCase):
    def test_matching_aspect_has_no_pads(self):
        vs, pad_x, pad_y = letterbox_view(1600, 900, 1600, 900)
        self.assertAlmostEqual(vs, 1.0)
        self.assertAlmostEqual(pad_x, 0.0)
        self.assertAlmostEqual(pad_y, 0.0)

    def test_uniform_downscale_matching_aspect(self):
        vs, pad_x, pad_y = letterbox_view(800, 450, 1600, 900)
        self.assertAlmostEqual(vs, 0.5)
        self.assertAlmostEqual(pad_x, 0.0)
        self.assertAlmostEqual(pad_y, 0.0)

    def test_widescreen_window_letterboxes_x(self):
        # Design 1000×1000 in a 2000×1000 window → scale 1, 500px side pads.
        vs, pad_x, pad_y = letterbox_view(2000, 1000, 1000, 1000)
        self.assertAlmostEqual(vs, 1.0)
        self.assertAlmostEqual(pad_x, 500.0)
        self.assertAlmostEqual(pad_y, 0.0)

    def test_tall_window_letterboxes_y(self):
        vs, pad_x, pad_y = letterbox_view(1000, 2000, 1000, 1000)
        self.assertAlmostEqual(vs, 1.0)
        self.assertAlmostEqual(pad_x, 0.0)
        self.assertAlmostEqual(pad_y, 500.0)


class TestDisplayModeApi(unittest.TestCase):
    def setUp(self):
        init(width=1000, height=800)
        canvas.display = "windowed"

    def test_default_is_windowed(self):
        self.assertEqual(canvas.display, DISPLAY_WINDOWED)

    def test_assignment_is_absolute(self):
        canvas.display = "maximized"
        self.assertEqual(canvas.display, DISPLAY_MAXIMIZED)
        canvas.display = "fullscreen"
        self.assertEqual(canvas.display, DISPLAY_FULLSCREEN)
        canvas.display = "windowed"
        self.assertEqual(canvas.display, DISPLAY_WINDOWED)

    def test_init_display_is_the_same_writer(self):
        init(width=1000, height=800, display="fullscreen")
        self.assertEqual(canvas.display, DISPLAY_FULLSCREEN)
        init(display="maximized")
        self.assertEqual(canvas.display, DISPLAY_MAXIMIZED)

    def test_rejects_aliases_and_non_strings(self):
        with self.assertRaises(ValueError):
            canvas.display = "full"
        with self.assertRaises(ValueError):
            canvas.display = "max"
        with self.assertRaises(ValueError):
            canvas.display = True  # type: ignore[misc]
        self.assertEqual(coerce_display_mode("FULLSCREEN"), DISPLAY_FULLSCREEN)
        self.assertEqual(coerce_display_mode(" Maximized"), DISPLAY_MAXIMIZED)

    def test_window_scale_via_init(self):
        fw = ScenaFramework.get_instance()
        init(width=1000, height=800, window_scale=0.5)
        self.assertAlmostEqual(fw.window_scale, 0.5)
        init(window_scale=0.9)
        self.assertAlmostEqual(fw.window_scale, 0.9)

    def test_window_frac_second_spelling_is_gone(self):
        # Pre-publication: one spelling (window_scale), no deprecated alias.
        with self.assertRaises(TypeError):
            init(window_frac=0.7)
        self.assertFalse(hasattr(ScenaFramework.get_instance(), "window_frac"))

    def test_init_display_rejects_bad_token(self):
        with self.assertRaises(ValueError):
            init(display="full")
        with self.assertRaises(ValueError):
            init(window_scale=0)

    def test_no_live_window_scale_on_canvas(self):
        self.assertFalse(hasattr(canvas, "window_scale"))


class TestGlfwMonitorGuard(unittest.TestCase):
    """pyGLFW wraps C NULL as a ctypes object; that must not be treated as live."""

    def test_valid_glfw_monitor_rejects_null_handles(self):
        fw = ScenaFramework.__new__(ScenaFramework)
        self.assertIsNone(fw._valid_glfw_monitor(None))

        class _NullAddr:
            value = 0

        self.assertIsNone(fw._valid_glfw_monitor(_NullAddr()))

        class _GLFWmonitor(ctypes.Structure):
            _fields_ = []

        null_ptr = ctypes.POINTER(_GLFWmonitor)()
        self.assertIsNone(fw._valid_glfw_monitor(null_ptr))


class TestLetterboxCoords(unittest.TestCase):
    def setUp(self):
        init(width=1000, height=800)
        canvas.reset_view()
        self.fw = ScenaFramework.get_instance()

    def tearDown(self):
        self.fw.view_scale = 1.0
        self.fw._letterbox_pad_x = 0.0
        self.fw._letterbox_pad_y = 0.0

    def test_screen_to_view_subtracts_pads(self):
        fw = self.fw
        fw.view_scale = 1.0
        fw._letterbox_pad_x = 100.0
        fw._letterbox_pad_y = 40.0
        # Window point on the design origin (bottom-left of content).
        # Content origin in window space: (pad_x, pad_y + design_h * vs)
        vx, vy = fw.screen_to_view_coords(100.0, 40.0 + 800.0)
        self.assertAlmostEqual(vx, 0.0, places=5)
        self.assertAlmostEqual(vy, 0.0, places=5)
        vx, vy = fw.screen_to_view_coords(100.0 + 500.0, 40.0)
        self.assertAlmostEqual(vx, 500.0, places=5)
        self.assertAlmostEqual(vy, 800.0, places=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
