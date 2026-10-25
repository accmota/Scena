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

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


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
        fit = (c._tex_fill_hw, c._tex_fill_hh)
        c.radius = 40.2
        p2 = c._to_skia_fill_paint()
        self.assertIs(p1, p2)
        self.assertEqual((c._tex_fill_hw, c._tex_fill_hh), fit)
        c.radius = 40.4
        p3 = c._to_skia_fill_paint()
        # Re-fitted: a new bucket swaps the scaled shader on the kept paint
        # (it rebuilt the paint until showcase D5).
        self.assertNotEqual((c._tex_fill_hw, c._tex_fill_hh), fit)
        self.assertIsNotNone(p3.getShader())
        self.assertIs(p3, p1, "a re-fit swaps the shader on the kept paint")

    def test_a_growing_shape_keeps_one_paint(self):
        # The 0.10.0 CHANGELOG ("no longer rebuilds its paint each frame"):
        # 30 frames of growth gave 30 paints at v0.9.1 (release audit).
        c = Circle(center=(0, 0), radius=40.0)
        c.fill = Gradient("ocean", type="radial")
        paints = []                    # held: a freed paint's id is reused
        for i in range(30):
            c.radius = 40.0 + 0.5 * i
            paints.append(c._to_skia_fill_paint())
        self.assertEqual(len({id(paint) for paint in paints}), 1)

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


class TestTrackGradientFit(unittest.TestCase):
    """A gradient on a Track fits the drawn outline, never its arc length.

    A turtle star (Track(vectors=…)) has no radius, so the fit fell through
    to ``length``: 36 steps of 220 units spread the ramp over ~8000 units
    and the star showed one flat middle colour. Every Track form is checked:
    the half-size equals the outline's own reach in the track's frame."""

    def setUp(self):
        init(width=1000, height=800)

    def tracks(self):
        from scena import Track, vec_from_angle
        star_walk = [vec_from_angle(k * 170, 220) for k in range(36)]
        return {
            "vectors": Track(vectors=star_walk, start=(0, 0), smooth=0),
            "points": Track(points=[(0, 0), (300, 40), (120, 260)], closed=True),
            "circle": Track.circle(center=(0, 0), radius=90),
            "eight": Track.eight(width=300, height=120, center=(0, 0)),
            "star": Track.star(points=5, radius=110, center=(0, 0)),
            "spiral": Track.spiral(turns=3, radius=150, center=(0, 0)),
            "wave": Track.wave(length=400, amplitude=50, start=(0, 0)),
            "arc": Track.arc(radius=200, from_angle=225, to_angle=315, center=(0, 0)),
            "zigzag": Track.circle(center=(0, 0), radius=100).zigzag(amount=20, waves=12),
            "shape": Track(Rect(center=(0, 0), width=240, height=60)),
        }

    def test_every_track_form_fits_its_outline(self):
        for name, t in self.tracks().items():
            with self.subTest(track=name):
                pts = [t.local_at(i / 720) for i in range(721)]
                reach_x = max(abs(p[0]) for p in pts)
                reach_y = max(abs(p[1]) for p in pts)
                hw, hh = _local_half_extents(t)
                self.assertAlmostEqual(hw, reach_x, delta=0.03 * reach_x + 1)
                self.assertAlmostEqual(hh, max(reach_y, 1e-3), delta=0.03 * reach_y + 1)

    def test_turtle_star_ramp_spans_the_star(self):
        t = self.tracks()["vectors"]
        g = Gradient("red", "blue", angle=90)
        t.color = g
        t.visible = True
        t.at(0.5)
        hw, hh = _local_half_extents(t)
        self.assertLess(_gradient_fit_scale(hw, hh, g), 300)

    def test_ramp_reaches_both_ends_on_screen(self):
        # Pixels, not sizes (A29 lesson): a closed box walk 600 wide is
        # 1400 long; fitted on the length its sides were 30 % / 70 % mixes.
        import skia
        from scena import Track
        t = Track(points=[(100, 250), (700, 250), (700, 350), (100, 350)],
                  closed=True, smooth=0, line_width=16)
        t.color = Gradient("red", "blue")
        t.visible = True
        info = skia.ImageInfo.Make(800, 600, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
        surface = skia.Surface.MakeRaster(info)
        surface.getCanvas().clear(skia.ColorBLACK)
        t.draw(surface.getCanvas())
        img = surface.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
        left = [int(v) for v in img[300, 101][:3]]
        right = [int(v) for v in img[300, 699][:3]]
        self.assertGreater(left[0], 220, left)
        self.assertLess(left[2], 40, left)
        self.assertGreater(right[2], 220, right)
        self.assertLess(right[0], 40, right)

    def test_reshaped_track_refits(self):
        from scena import Track
        t = Track(points=[(0, 0), (100, 0), (100, 100)], closed=True)
        t.at(0.5)
        before = _local_half_extents(t)
        t.scale = 1     # pose only: the outline (and the cache) stays
        self.assertEqual(_local_half_extents(t), before)
        t.zigzag(amount=40, waves=6)
        t.at(0.5)
        after = _local_half_extents(t)
        self.assertGreater(after[0], before[0] + 10)


class TestSkyGradientAutoFit(unittest.TestCase):
    def setUp(self):
        self._unplaced = unplaced_creation()
        self._unplaced.__enter__()

    def tearDown(self):
        self._unplaced.__exit__(None, None, None)

    def test_sky_gradient_size_is_auto(self):
        sky = SkyGradient("day", horizon=0.5)
        self.assertIsNone(sky._wallpaper.source.size)
        self.assertAlmostEqual(sky._wallpaper.source._angle, -90.0)  # top → bottom, y-up
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
