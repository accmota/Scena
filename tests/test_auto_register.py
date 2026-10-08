"""Construct-to-place: post effects and background fields attach by family."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import (
    canvas, init,
    Vignette, Bloom,
    Stars, Clouds, SkyGradient, Tunnel,
    Gradient, Color,
)
from scena.background_kinds import Wallpaper as WallpaperCls
from scena.style import Gradient as GradientCls


class TestAutoRegister(unittest.TestCase):
    def setUp(self):
        init(width=800, height=600)
        canvas.background.clear()
        canvas.background.reset_base()
        canvas.effects.clear()

    def test_extras_follow_construction_order(self):
        a = Stars()
        b = Clouds()
        extras = list(canvas.background)
        self.assertEqual(extras, [a, b])

    def test_wallpaper_last_wins_base(self):
        first = SkyGradient("day")
        second = SkyGradient("night")
        self.assertIs(canvas.background.base, second)
        self.assertIsNot(canvas.background.base, first)
        self.assertEqual(len(canvas.background), 0)

    def test_stars_then_sky_keeps_stars(self):
        stars = Stars()
        sky = SkyGradient("night")
        self.assertIs(canvas.background.base, sky)
        self.assertEqual(list(canvas.background), [stars])

    def test_gradient_does_not_attach(self):
        Gradient("navy", "black")
        Color("cyan")
        self.assertEqual(len(canvas.background), 0)
        self.assertIsInstance(canvas.background.base, WallpaperCls)
        self.assertNotIsInstance(canvas.background.base.source, GradientCls)

    def test_vignette_attaches(self):
        v = Vignette()
        self.assertIn(v, list(canvas.effects))
        self.assertEqual(len(canvas.effects), 1)

    def test_temp_does_not_attach(self):
        Vignette.temp()
        Stars.temp()
        SkyGradient.temp("sunset")
        Bloom.temp()
        self.assertEqual(len(canvas.effects), 0)
        self.assertEqual(len(canvas.background), 0)
        self.assertIsInstance(canvas.background.base, WallpaperCls)
        self.assertIsInstance(canvas.background.base.source, Color)

    def test_add_idempotent(self):
        v = Vignette()
        canvas.effects.add(v)
        self.assertEqual(len(canvas.effects), 1)
        stars = Stars()
        canvas.background.add(stars)
        self.assertEqual(len(canvas.background), 1)

    def test_set_fly_single_extra(self):
        Stars()
        canvas.set_fly(Tunnel())
        extras = list(canvas.background)
        self.assertEqual(len(extras), 1)
        self.assertIsInstance(extras[0], Tunnel)

    def test_background_assign_solid(self):
        canvas.background = "navy"
        self.assertIsInstance(canvas.background.base, WallpaperCls)
        self.assertIsInstance(canvas.background.base.source, Color)

    def test_move_extra_to_base(self):
        field = Stars()
        self.assertIn(field, list(canvas.background))
        canvas.background.base = field
        self.assertIs(canvas.background.base, field)
        self.assertNotIn(field, list(canvas.background))

    def test_instance_remove_extra(self):
        stars = Stars()
        moon = Clouds()
        stars.remove()
        self.assertEqual(list(canvas.background), [moon])
        stars.remove()  # idempotent
        self.assertEqual(list(canvas.background), [moon])
        canvas.background.add(stars)
        self.assertEqual(list(canvas.background), [moon, stars])

    def test_instance_remove_orphaned_wallpaper_is_noop(self):
        first = SkyGradient("day")
        SkyGradient("night")
        first.remove()
        self.assertIsNot(canvas.background.base, first)

    def test_instance_remove_base_raises(self):
        sky = SkyGradient("night")
        with self.assertRaises(TypeError):
            sky.remove()
        self.assertIs(canvas.background.base, sky)

    def test_instance_remove_moved_extra_as_base_raises(self):
        stars = Stars()
        canvas.background.base = stars
        with self.assertRaises(TypeError):
            stars.remove()
        self.assertIs(canvas.background.base, stars)

    def test_instance_remove_extra_wallpaper_wash(self):
        wash = SkyGradient.temp("sunset")
        canvas.background.add(wash)
        self.assertIn(wash, list(canvas.background))
        wash.remove()
        self.assertNotIn(wash, list(canvas.background))

    def test_instance_remove_post(self):
        bloom = Bloom()
        vignette = Vignette()
        bloom.remove()
        self.assertEqual(list(canvas.effects), [vignette])
        bloom.remove()  # idempotent
        self.assertEqual(list(canvas.effects), [vignette])
        canvas.effects.add(bloom)
        self.assertIn(bloom, list(canvas.effects))


if __name__ == "__main__":
    unittest.main()
