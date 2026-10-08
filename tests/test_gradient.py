"""Gradient auto-fit size, absolute design units, and wallpaper frame fit."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import init, Circle, Rect, Line
from scena.color import Color
from scena.style import (
    Gradient,
    GradientType,
    _gradient_fit_scale,
    _local_half_extents,
    _quantize_extent,
    build_background_fill,
)
from scena.background_kinds import SkyGradient
from scena.place import unplaced_creation


class TestGradientFit(unittest.TestCase):
    def setUp(self):
        init(width=1000, height=800)

    def test_default_size_is_none_and_fits_host(self):
        g = Gradient("sunset")
        self.assertIsNone(g.size)
        self.assertTrue(g._needs_host_fit)
        self.assertIsNotNone(g._skia_shader)

    def test_removed_kwargs_rejected(self):
        with self.assertRaises(TypeError):
            Gradient("red", "blue", sway=True)
        with self.assertRaises(TypeError):
            Gradient("red", "blue", cycle=2)
        with self.assertRaises(TypeError):
            Gradient("red", "blue", interpolation_steps=8)
        with self.assertRaises(TypeError):
            Gradient("red", "blue", color_space="rgb")

    def test_size_must_be_positive(self):
        with self.assertRaises(ValueError):
            Gradient("red", "blue", size=0)
        with self.assertRaises(ValueError):
            Gradient("red", "blue", size=-10)

    def test_type_string_ok_junk_raises(self):
        self.assertEqual(Gradient("red", "blue").type, "linear")
        g = Gradient("red", "blue", type="radial")
        self.assertEqual(g.type, "radial")
        self.assertEqual(g._type, GradientType.RADIAL)
        with self.assertRaises(TypeError) as ctx:
            Gradient("red", "blue", type="spiral")
        self.assertIn("linear", str(ctx.exception))

    def test_auto_radial_on_circle_equals_radius(self):
        g = Gradient("cyan", "blue", type="radial")
        c = Circle(center=(10, 10), radius=32)
        hw, hh = _local_half_extents(c)
        self.assertAlmostEqual(_gradient_fit_scale(hw, hh, g), 32.0)
        c.fill = g
        c._to_skia_fill_paint()
        self.assertAlmostEqual(c._tex_fill_hw, _quantize_extent(32.0))
        self.assertAlmostEqual(c._tex_fill_hh, _quantize_extent(32.0))

    def test_auto_linear_on_line_equals_half_length(self):
        g = Gradient("magenta", "cyan")
        ln = Line(p1=(0, 0), p2=(80, 0))
        hw, hh = _local_half_extents(ln)
        self.assertAlmostEqual(_gradient_fit_scale(hw, hh, g), 40.0)
        ln.set_color(g)
        ln._to_skia_line_paint()
        self.assertAlmostEqual(ln._tex_line_hw, _quantize_extent(40.0))

    def test_auto_linear_angle_0_on_rect_equals_half_width(self):
        g = Gradient("navy", "cyan", angle=0)
        r = Rect(center=(0, 0), width=80, height=20)
        hw, hh = _local_half_extents(r)
        self.assertAlmostEqual(_gradient_fit_scale(hw, hh, g), 40.0)

    def test_auto_linear_angle_90_on_rect_equals_half_height(self):
        g = Gradient("navy", "cyan", angle=90)
        r = Rect(center=(0, 0), width=80, height=20)
        hw, hh = _local_half_extents(r)
        self.assertAlmostEqual(_gradient_fit_scale(hw, hh, g), 10.0)

    def test_auto_linear_on_text_uses_measured_box(self):
        from scena import Text
        g = Gradient("red", "cyan", angle=0)
        t = Text("FILL GRADIENT", top_left=(80, 450), font_size=28)
        t.fill = g
        hw, hh = _local_half_extents(t)
        self.assertGreater(hw, 24.0)
        self.assertGreater(hh, 5.0)
        self.assertAlmostEqual(_gradient_fit_scale(hw, hh, g), hw)
        t._to_skia_fill_paint()
        self.assertAlmostEqual(t._tex_fill_hw, _quantize_extent(hw))
        self.assertAlmostEqual(t._tex_fill_hh, _quantize_extent(hh))

    def test_auto_linear_angle_90_on_text_uses_half_height(self):
        from scena import Text
        g = Gradient("dark red", "white", angle=90)
        t = Text("FILL GRADIENT", top_left=(80, 450), font_size=28)
        hw, hh = _local_half_extents(t)
        self.assertGreater(hh, 5.0)
        self.assertAlmostEqual(_gradient_fit_scale(hw, hh, g), hh)

    def test_explicit_size_does_not_follow_radius(self):
        g = Gradient("navy", "cyan", type="radial", size=40)
        self.assertFalse(g._needs_host_fit)
        c = Circle(center=(0, 0), radius=10)
        c.fill = g
        p1 = c._to_skia_fill_paint()
        c.radius = 80
        p2 = c._to_skia_fill_paint()
        self.assertIs(p1, p2)

    def test_shared_auto_gradient_different_scales(self):
        g = Gradient("ocean", type="radial")
        a = Circle(center=(0, 0), radius=10)
        b = Circle(center=(50, 50), radius=40)
        a.fill = g
        b.fill = g
        a._to_skia_fill_paint()
        b._to_skia_fill_paint()
        self.assertAlmostEqual(a._tex_fill_hw, _quantize_extent(10.0))
        self.assertAlmostEqual(b._tex_fill_hw, _quantize_extent(40.0))
        self.assertIsNot(a._cached_fill_paint, b._cached_fill_paint)

    def test_quantized_cache_skips_sub_bucket_wobble(self):
        g = Gradient("ocean", type="radial")
        c = Circle(center=(0, 0), radius=40.0)
        c.fill = g
        p1 = c._to_skia_fill_paint()
        c.radius = 40.2
        p2 = c._to_skia_fill_paint()
        self.assertIs(p1, p2)
        c.radius = 40.4
        p3 = c._to_skia_fill_paint()
        self.assertIsNot(p1, p3)

    def test_sweep_ignores_size(self):
        g = Gradient("rainbow", type="sweep")
        self.assertIsNone(g.size)
        self.assertFalse(g._needs_host_fit)
        g2 = Gradient("rainbow", type="sweep", size=80)
        self.assertFalse(g2._needs_host_fit)

    def test_wallpaper_auto_linear_covers_frame(self):
        g = Gradient("sunset", angle=90)
        self.assertTrue(g._needs_host_fit)
        self.assertAlmostEqual(_gradient_fit_scale(500.0, 400.0, g), 400.0)
        fill = build_background_fill(g, 1000, 800, 1000.0, 800.0)
        self.assertIsNotNone(fill.paint.getShader())

    def test_wallpaper_auto_radial_uses_nearer_edge(self):
        g = Gradient("heat", type="radial")
        self.assertAlmostEqual(_gradient_fit_scale(500.0, 400.0, g), 400.0)

    def test_wallpaper_absolute_size_still_accepted(self):
        g = Gradient("heat", type="radial", size=700)
        self.assertFalse(g._needs_host_fit)
        fill = build_background_fill(g, 1000, 800, 1000.0, 800.0)
        self.assertIsNotNone(fill.paint.getShader())


class TestSkyGradientAutoFit(unittest.TestCase):
    def setUp(self):
        self._unplaced = unplaced_creation()
        self._unplaced.__enter__()

    def tearDown(self):
        self._unplaced.__exit__(None, None, None)

    def test_sky_gradient_size_is_auto(self):
        sky = SkyGradient("day", horizon=0.5)
        self.assertIsNone(sky._wallpaper.source.size)
        self.assertAlmostEqual(sky._wallpaper.source._angle, 90.0)
        src = sky._wallpaper.source
        sky._sync_gradient(900.0)
        self.assertIs(sky._wallpaper.source, src)
        sky._sync_gradient(100.0)
        self.assertIs(sky._wallpaper.source, src)

    def test_sky_gradient_rebuilds_when_horizon_changes(self):
        sky = SkyGradient("day")
        src = sky._wallpaper.source
        sky.horizon = 0.5
        sky._sync_gradient()
        self.assertIsNot(sky._wallpaper.source, src)
        self.assertIsNone(sky._wallpaper.source.size)

    def test_sky_gradient_rebuilds_when_fade_changes(self):
        sky = SkyGradient("day", horizon=0.5)
        src = sky._wallpaper.source
        sky.fade = 0.0
        sky._sync_gradient()
        self.assertIsNot(sky._wallpaper.source, src)

    def test_sky_gradient_horizon_zero_is_full_height_atmosphere(self):
        sky = SkyGradient("day")
        ramp = sky._ramp_stops()
        self.assertEqual(len(ramp), 2)
        self.assertEqual(ramp[-1][1], tuple(sky.middle))
        self.assertNotEqual(ramp[-1][1], tuple(sky.bottom))


class TestGradientToneHelpers(unittest.TestCase):
    def test_mean_color_two_equal_stops(self):
        g = Gradient("red", "blue")
        mean = g.mean_color()
        # Equal span 0→1: midpoint of endpoints
        self.assertAlmostEqual(mean.rgb[0], 0.5, places=4)
        self.assertAlmostEqual(mean.rgb[2], 0.5, places=4)

    def test_mean_color_weighted_by_span(self):
        g = Gradient((0.0, "black"), (0.25, "white"), (1.0, "white"))
        mean = g.mean_color()
        # Short dark segment, long white: mean should be bright
        self.assertGreater(mean.rgb[0], 0.7)

    def test_darker_lighter_map_stops_and_preserve_geometry(self):
        g = Gradient("navy", "cyan", type="radial", size=40, angle=30)
        dark = g.darker(0.2)
        light = g.lighter(0.15)
        self.assertIsNot(dark, g)
        self.assertEqual(dark.type, "radial")
        self.assertEqual(dark.size, 40)
        self.assertAlmostEqual(dark._angle, 30.0)
        self.assertEqual(len(dark._colors), len(g._colors))
        for a, b in zip(g._colors, dark._colors):
            self.assertLess(b.hsl[2], a.hsl[2])
        for a, b in zip(g._colors, light._colors):
            self.assertGreater(b.hsl[2], a.hsl[2])
        # Original unchanged
        self.assertAlmostEqual(g._colors[0].hsl[2], Color("navy").hsl[2], places=3)

    def test_darker_default_amount_matches_color(self):
        g = Gradient("coral", "gold")
        self.assertAlmostEqual(
            g.darker()._colors[0].hsl[2],
            g._colors[0].darker().hsl[2],
            places=4,
        )


class TestDefaultLineWidth(unittest.TestCase):
    def setUp(self):
        init(width=400, height=300)

    def test_new_shape_line_width_is_1_5(self):
        c = Circle(center=(0, 0), radius=10)
        self.assertAlmostEqual(float(c.line_width), 1.5, places=4)

    def test_gradient_visual_outline_keeps_line_width(self):
        c = Circle(center=(0, 0), radius=10)
        c.line_width = 3.0
        g = Gradient("ruby")
        c.visual = g
        self.assertAlmostEqual(float(c.line_width), 3.0, places=4)
        self.assertTrue(bool(c.line))
        rim = g.mean_color().darker(0.2)
        self.assertAlmostEqual(c.line.rgb[0], rim.rgb[0], places=4)

    def test_paint_line_false_skips_gradient_outline(self):
        from scena import Paint
        c = Circle(center=(0, 0), radius=10)
        g = Gradient("ocean")
        c.visual = Paint(g, line=False)
        self.assertIs(c.fill, g)
        self.assertFalse(bool(c.line))


if __name__ == "__main__":
    unittest.main()
