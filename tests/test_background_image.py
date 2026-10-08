"""Tiled image wallpaper: period in design units, independent of bitmap / FB pixels."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import skia

from scena.background_kinds import Wallpaper
from scena.style import (
    build_background_fill,
    _tile_matrix_components,
    _resolve_tile_size_du,
)


def _period(sx, iw):
    return sx * iw


class TestTileMatrix(unittest.TestCase):
    def _components(self, *, iw=64, ih=64, tile_size=200, scale=1.0,
                    fb_w=2000, fb_h=1600, dw=1000, dh=800, rest_x=None, rest_y=None):
        return _tile_matrix_components(
            image_width=iw, image_height=ih, tile_size=tile_size, scale=scale,
            fb_width=fb_w, fb_height=fb_h, design_width=dw, design_height=dh,
            rest_x=rest_x, rest_y=rest_y,
        )

    def test_same_tile_size_ignores_image_resolution(self):
        s64, _, _, _ = self._components(iw=64, ih=64)
        s256, _, _, _ = self._components(iw=256, ih=256)
        self.assertAlmostEqual(_period(s64, 64), _period(s256, 256))
        # 200 du × (2000 FB / 1000 du) = 400 FB px
        self.assertAlmostEqual(_period(s64, 64), 400.0)

    def test_retina_doubles_fb_period_keeps_design_period(self):
        s1, _, _, _ = self._components(fb_w=2000, fb_h=1600)
        s2, _, _, _ = self._components(fb_w=4000, fb_h=3200)
        p1 = _period(s1, 64)
        p2 = _period(s2, 64)
        self.assertAlmostEqual(p2, 2.0 * p1)
        fb_per_du_1 = 2000 / 1000
        fb_per_du_2 = 4000 / 1000
        self.assertAlmostEqual(p1 / fb_per_du_1, 200.0)
        self.assertAlmostEqual(p2 / fb_per_du_2, 200.0)

    def test_scale_doubles_period(self):
        s1, _, _, _ = self._components(scale=1.0)
        s2, _, _, _ = self._components(scale=2.0)
        self.assertAlmostEqual(_period(s2, 64), 2.0 * _period(s1, 64))

    def test_default_tile_size_is_quarter_short_side(self):
        dw, dh = 1000.0, 800.0
        expected = 0.25 * min(dw, dh)
        w_du, h_du = _resolve_tile_size_du(
            None, image_width=64, image_height=64,
            design_width=dw, design_height=dh,
        )
        self.assertAlmostEqual(w_du, expected)
        self.assertAlmostEqual(h_du, expected)  # square image
        s_default, _, _, _ = self._components(tile_size=None)
        s_explicit, _, _, _ = self._components(tile_size=expected)
        self.assertAlmostEqual(s_default, s_explicit)

    def test_rest_at_design_center_seam_at_fb_origin_x(self):
        sx, sy, tx, ty = self._components(rest_x=500.0, rest_y=400.0)
        self.assertAlmostEqual(tx, 0.0)
        # upright: cell bottom at FB y=h, top at h - tile_h_fb
        self.assertAlmostEqual(ty, 1600.0 - 400.0)

    def test_rest_at_origin_seam_at_fb_center(self):
        _, _, tx, ty = self._components(rest_x=0.0, rest_y=0.0)
        self.assertAlmostEqual(tx, 1000.0)  # w/2
        self.assertAlmostEqual(ty, 800.0 - 400.0)  # h/2 - tile_h_fb

    def test_explicit_wh_tile_size(self):
        sx, sy, _, _ = self._components(iw=64, ih=32, tile_size=(200, 50))
        self.assertAlmostEqual(_period(sx, 64), 400.0)
        self.assertAlmostEqual(sy * 32, 50.0 * (1600 / 800))

    def test_aspect_preserved_from_width(self):
        w_du, h_du = _resolve_tile_size_du(
            200, image_width=64, image_height=32,
            design_width=1000, design_height=800,
        )
        self.assertAlmostEqual(w_du, 200.0)
        self.assertAlmostEqual(h_du, 100.0)


class TestWallpaperImageTileSize(unittest.TestCase):
    def test_rejects_non_positive(self):
        with self.assertRaises(ValueError):
            Wallpaper.temp(fit="tile", tile_size=0)
        with self.assertRaises(ValueError):
            Wallpaper.temp(fit="tile", tile_size=-10)
        with self.assertRaises(ValueError):
            Wallpaper.temp(fit="tile", tile_size=(100, 0))
        with self.assertRaises(TypeError):
            Wallpaper.temp(fit="tile", tile_size="wide")
        with self.assertRaises(ValueError):
            Wallpaper.temp(scale=0)
        with self.assertRaises(ValueError):
            Wallpaper.temp(scale=-1)
        ok = Wallpaper.temp(scale=2.0)
        self.assertEqual(ok.source.scale, 2.0)

    def test_stores_scalar_and_pair(self):
        a = Wallpaper.temp(fit="tile", tile_size=200)
        self.assertEqual(a.source.tile_size, 200.0)
        b = Wallpaper.temp(fit="tile", tile_size=(120, 80))
        self.assertEqual(b.source.tile_size, (120.0, 80.0))
        c = Wallpaper.temp(fit="tile")
        self.assertIsNone(c.source.tile_size)

    def test_build_shader_tiles_without_error(self):
        info = skia.ImageInfo.Make(64, 64, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        surf.getCanvas().clear(skia.Color4f(1, 0, 0, 1))
        img = surf.makeImageSnapshot()
        w = Wallpaper.temp(image=img, fit="tile", tile_size=200)
        fill = build_background_fill(
            w.source, 2000, 1600, 1000.0, 800.0, rest_x=500.0, rest_y=400.0,
        )
        self.assertIsNotNone(fill.paint.getShader())
        self.assertIsNone(fill.underlay)
        self.assertAlmostEqual(fill.rect.width(), 2000.0)

    def test_filename_string_is_image_color_name_is_not(self):
        import warnings
        from scena.background import looks_like_image_path
        from scena.color import Color
        from scena.style import BackgroundImage
        self.assertFalse(looks_like_image_path("navy"))
        self.assertFalse(looks_like_image_path("sky blue"))
        self.assertTrue(looks_like_image_path("bg1.jpg"))
        self.assertTrue(looks_like_image_path("media/sky.png"))
        navy = Wallpaper.temp("navy")
        self.assertIsInstance(navy.source, Color)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            file_bg = Wallpaper.temp("bg1.jpg")
            slash_bg = Wallpaper.temp("media/sky.png")
        self.assertIsInstance(file_bg.source, BackgroundImage)
        self.assertIsInstance(slash_bg.source, BackgroundImage)

    def test_image_kwargs_rejected_on_color(self):
        with self.assertRaises(TypeError) as ctx:
            Wallpaper.temp("navy", fit="cover")
        self.assertIn("color name", str(ctx.exception))
        from scena.color import Color
        with self.assertRaises(TypeError):
            Wallpaper.temp(Color("navy"), fit="cover")
        from scena.style import Gradient
        with self.assertRaises(TypeError):
            Wallpaper.temp(Gradient("navy", "black"), fit="contain")

    def test_cover_plus_pan_on_one_constructor(self):
        info = skia.ImageInfo.Make(8, 8, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        img = surf.makeImageSnapshot()
        w = Wallpaper.temp(image=img, fit="cover", pan_response=0.15, zoom_response=0.3)
        self.assertEqual(w.source.fit, "cover")
        self.assertAlmostEqual(w.pan_response, 0.15)
        self.assertAlmostEqual(w.zoom_response, 0.3)


if __name__ == "__main__":
    unittest.main()


class TestWallpaperImageIdentity(unittest.TestCase):
    """Wallpaper images keep their decoded texture across rebuilds.

    skia-python's ``Paint.setShader`` deep-copies the shader into a new
    ``skia.Image`` (new uniqueID → GPU texture cache miss → the lazy PNG decodes
    again; a raster image is re-encoded to PNG, ~0.8 s at 2669x1782). So a
    fitted wallpaper must draw the *shared cached* image directly, and a tiled
    one must reuse a single template shader per image — never a fresh
    ``setShader`` per Wallpaper / window size / camera rest.
    """

    def setUp(self):
        import tempfile
        from scena import style
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "halves.png")
        surf = skia.Surface.MakeRaster(skia.ImageInfo.MakeN32Premul(40, 20))
        c = surf.getCanvas()
        c.clear(skia.Color4f(1, 0, 0, 1))
        c.drawRect(skia.Rect.MakeLTRB(20, 0, 40, 20), skia.Paint(Color=skia.ColorBLUE))
        with open(self.path, "wb") as f:
            f.write(bytes(surf.makeImageSnapshot().encodeToData()))
        self._style = style
        self._saved_cache = dict(style._IMAGE_CACHE)

    def tearDown(self):
        self._style._IMAGE_CACHE.clear()
        self._style._IMAGE_CACHE.update(self._saved_cache)
        self._tmp.cleanup()

    @staticmethod
    def _pixels(draw, w=100, h=60):
        surf = skia.Surface.MakeRaster(skia.ImageInfo.MakeN32Premul(w, h))
        c = surf.getCanvas()
        c.clear(skia.Color4f(0, 1, 0, 1))
        draw(c)
        return bytes(surf.makeImageSnapshot().tobytes())

    def test_fitted_wallpapers_draw_the_shared_lazy_image(self):
        a = Wallpaper.temp(self.path, fit="cover")
        b = Wallpaper.temp(self.path, fit="contain")
        fa = build_background_fill(a.source, 100, 60, 100.0, 60.0)
        fb = build_background_fill(b.source, 320, 200, 100.0, 60.0)
        cached = self._style._IMAGE_CACHE[os.path.abspath(self.path)]
        self.assertIs(fa._image, cached)
        self.assertIs(fb._image, cached)
        # Stays lazy (encoded bytes): an eager raster in the shared cache would
        # make every Texture / tile ``setShader`` re-encode it to PNG.
        self.assertTrue(cached.isLazyGenerated())
        self.assertIsNone(fa.paint.getShader())

    def test_fitted_fill_matches_decal_shader_placement(self):
        from scena.style import BackgroundImage
        for fit, (w, h) in (("cover", (100, 60)), ("contain", (100, 90)), ("stretch", (70, 60))):
            src = BackgroundImage(self.path, fit=fit)
            fill = build_background_fill(src, w, h, float(w), float(h))
            img = src.image
            d = fill._dst
            m = skia.Matrix()
            m.setScale(d.width() / img.width(), d.height() / img.height())
            m.postTranslate(d.left(), d.top())
            ref = skia.Paint()
            ref.setShader(img.makeShader(skia.TileMode.kDecal, skia.TileMode.kDecal,
                                         skia.SamplingOptions(), m))
            # Camera pan + zoom (rotation differs only on 1-2 non-AA edge pixels).
            cam = skia.Matrix()
            cam.setScale(1.25, 1.25, w * 0.5, h * 0.5)
            cam.postTranslate(3.0, -2.0)

            def new(c, fill=fill, w=w, h=h):
                c.concat(cam)
                c.clear(fill.underlay)
                fill.fill(c, skia.Rect.MakeLTRB(-50, -50, w + 50, h + 50))

            def old(c, ref=ref, fill=fill, w=w, h=h):
                c.concat(cam)
                c.clear(fill.underlay)
                c.drawRect(skia.Rect.MakeLTRB(-50, -50, w + 50, h + 50), ref)

            self.assertEqual(self._pixels(new, w, h), self._pixels(old, w, h), fit)

    def test_tile_template_shader_is_built_once_per_image(self):
        from scena.style import _IMAGE_PAINT_CACHE, _tile_local_matrix, _IMAGE_SAMPLING
        a = Wallpaper.temp(self.path, fit="tile", tile_size=30)
        b = Wallpaper.temp(self.path, fit="tile", tile_size=30)
        before = len(_IMAGE_PAINT_CACHE)
        fa = build_background_fill(a.source, 100, 60, 100.0, 60.0, rest_x=10.0, rest_y=5.0)
        build_background_fill(b.source, 200, 120, 100.0, 60.0, rest_x=40.0, rest_y=0.0)
        build_background_fill(a.source, 100, 60, 100.0, 60.0, rest_x=-3.0, rest_y=8.0)
        self.assertEqual(len(_IMAGE_PAINT_CACHE), before + 1)
        # Same tiling as a per-build local-matrix shader.
        img = a.source.image
        m = _tile_local_matrix(
            image_width=img.width(), image_height=img.height(), tile_size=30.0, scale=1.0,
            fb_width=100.0, fb_height=60.0, design_width=100.0, design_height=60.0,
            rest_x=10.0, rest_y=5.0,
        )
        ref = skia.Paint()
        ref.setBlendMode(skia.BlendMode.kSrc)
        ref.setShader(img.makeShader(skia.TileMode.kRepeat, skia.TileMode.kRepeat, _IMAGE_SAMPLING, m))
        cam = skia.Matrix()
        cam.setScale(1.3, 1.3, 50.0, 30.0)
        cam.postTranslate(-4.0, 6.0)
        big = skia.Rect.MakeLTRB(-80, -80, 180, 140)

        def new(c):
            c.concat(cam)
            fa.fill(c, big)

        def old(c):
            c.concat(cam)
            c.drawRect(big, ref)

        self.assertEqual(self._pixels(new), self._pixels(old))

    def test_prewarm_before_window_is_queued_for_run(self):
        from scena import style
        style._PENDING_PREWARM.clear()
        style.prewarm_background_image(style.BackgroundImage(self.path))
        style.prewarm_background_image(style.BackgroundImage(self.path, fit="tile"))
        self.assertEqual(len(style._PENDING_PREWARM), 2)
        self.assertIs(style._PENDING_PREWARM[0][0], style._IMAGE_CACHE[os.path.abspath(self.path)])
        style.prewarm_pending_images()  # still no context: keeps the queue
        self.assertEqual(len(style._PENDING_PREWARM), 2)
        style._PENDING_PREWARM.clear()
