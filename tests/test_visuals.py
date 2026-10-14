"""
tests/test_visuals.py — Shape visual / recipe unit tests (headless).

    python -m unittest tests.test_visuals -v
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import (
    init, canvas, clock, Circle, Ellipse, Line, Rect, RegularPolygon, Neon, MultiBorder, Extrude,
    DashRing, Halo, GearShell, ElectricField,
    OrganicOutline, Tracer, ElectricBolt,
    Shield,
    Swell, Water, Flame, Metal, Liquify, Bolt, Wave, Aurora,
    Laser, Ink, InkBleed, Sphere, Rim, Gel,
    Tail, Beat, InsetRim, HueShift, Recolor,
    WaterFill, SwellFill, WaveFill, AuroraFill, FlameFill, GlowFilter, HostGlow, DropShadow, set_extrude_focus,
    Paint, Fill, Stroke, Glow, Shadow, CheapGlow,
)
from scena.color import Color
from scena.style import BlendMode, Gradient, Texture
from scena.visuals import _paint_rgba
from scena.recipes import _channel_paint_rgba, _host_rgba
import skia


VISUAL_CLASSES = (
    Neon, MultiBorder, Extrude,
    OrganicOutline, Tracer, ElectricBolt,
    Swell, Water, Flame, Metal, Liquify, Bolt, Wave, Aurora,
    Laser, Ink, InkBleed, Sphere, Rim, Gel,
    DashRing, Halo, GearShell, ElectricField,
    Shield,
    Beat, InsetRim,
)

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


class TestVisuals(unittest.TestCase):
    def setUp(self):
        init(width=400, height=300)
        # Dashed / pulsing looks sample the global clock; freeze so a full
        # suite run cannot park Tracer's dash gap on the probe pixel.
        clock.scale = 1.0
        clock.paused = False
        clock._dt = 0.0
        clock._time = 0.0
        clock._real_dt = 0.0
        clock._real_time = 0.0
        clock._frame = 0

    def test_zero_arg_constructors(self):
        for cls in VISUAL_CLASSES:
            with self.subTest(cls=cls.__name__):
                visual = cls()
                self.assertIsNotNone(visual._batch_key)
                self.assertIsInstance(visual._batch_key, tuple)

    def test_interning(self):
        a = Neon(color="cyan")
        b = Neon(color="cyan")
        self.assertIs(a, b)
        c = Neon(color="magenta")
        self.assertIsNot(a, c)

    def test_look_alpha_and_width_clamp_intern(self):
        self.assertIs(Paint("tomato", alpha=1.5), Paint("tomato", alpha=1.0))
        self.assertIs(Paint("tomato", alpha=-1), Paint("tomato", alpha=0.0))
        self.assertIs(Fill("cyan", alpha=1.2), Fill("cyan", alpha=1.0))
        self.assertIs(Glow(alpha=1.5), Glow(alpha=1.0))
        with self.assertRaises(ValueError):
            Glow(sigma=-4)
        with self.assertRaises(ValueError):
            Stroke("black", width=-2)
        self.assertIs(Shadow(alpha=2.0), Shadow(alpha=1.0))
        self.assertAlmostEqual(Glow(alpha=1.5).alpha, 1.0)
        self.assertAlmostEqual(Fill("red", alpha=-0.5).alpha, 0.0)

    def test_paint_rgba_none_is_missing(self):
        """Color(none) is missing paint, not transparent black."""
        self.assertIsNone(_paint_rgba(Color(None)))
        self.assertIsNone(_channel_paint_rgba(Color(None)))
        solid = _paint_rgba(Color("cyan"))
        self.assertIsNotNone(solid)
        self.assertGreater(solid[1] + solid[2], 1.5)

    def test_texture_proxy_color_mean_and_override(self):
        """Texture.color is a proxy hue; omitted → opaque-pixel mean."""
        def _solid_image(r, g, b, a=255, size=8):
            info = skia.ImageInfo.Make(
                size, size, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType,
            )
            surf = skia.Surface.MakeRaster(info)
            surf.getCanvas().clear(skia.ColorSetARGB(a, r, g, b))
            return surf.makeImageSnapshot()

        red = Texture(image=_solid_image(255, 0, 0))
        self.assertAlmostEqual(red.color.rgb[0], 1.0, places=2)
        self.assertAlmostEqual(red.color.rgb[1], 0.0, places=2)
        self.assertAlmostEqual(red.color.rgb[2], 0.0, places=2)
        sampled = _paint_rgba(red)
        self.assertIsNotNone(sampled)
        self.assertAlmostEqual(sampled[0], 1.0, places=2)
        self.assertAlmostEqual(sampled[1], 0.0, places=2)

        gold = Texture(image=_solid_image(0, 0, 255), color="gold")
        override = _paint_rgba(gold)
        self.assertEqual(_channel_paint_rgba(gold), override)
        self.assertAlmostEqual(override[0], Color("gold").rgb[0], places=3)
        self.assertLess(override[2], 0.5)

        c = Circle(center=(50, 50), radius=10)
        c.fill = red
        host = _host_rgba(c)
        self.assertAlmostEqual(host[0], 1.0, places=2)
        self.assertAlmostEqual(host[1], 0.0, places=2)

        # Low-alpha pixels do not pull the mean toward the matte.
        info = skia.ImageInfo.Make(
            8, 8, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType,
        )
        surf = skia.Surface.MakeRaster(info)
        canvas = surf.getCanvas()
        canvas.clear(skia.ColorSetARGB(0, 0, 255, 0))
        canvas.drawRect(
            skia.Rect.MakeXYWH(0, 0, 8, 4),
            skia.Paint(Color=skia.ColorSetARGB(255, 255, 0, 0)),
        )
        mixed = Texture(image=surf.makeImageSnapshot())
        self.assertAlmostEqual(mixed.color.rgb[0], 1.0, places=1)
        self.assertLess(mixed.color.rgb[1], 0.15)

    def test_texture_shift_hueshift_and_recolor_pixels(self):
        """Texture(shift=) transforms bitmap pixels; proxy color unchanged."""
        def _solid_image(r, g, b, a=255, size=8):
            info = skia.ImageInfo.Make(
                size, size, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType,
            )
            surf = skia.Surface.MakeRaster(info)
            surf.getCanvas().clear(skia.ColorSetARGB(a, r, g, b))
            return surf.makeImageSnapshot()

        red_img = _solid_image(255, 0, 0)
        hs = HueShift(amount=0.33)
        tex_h = Texture(image=red_img, shift=hs)
        # Proxy stays mean of source (red), not the shifted green.
        self.assertAlmostEqual(tex_h.color.rgb[0], 1.0, places=2)
        self.assertAlmostEqual(tex_h.color.rgb[1], 0.0, places=2)
        self.assertIs(tex_h.shift, hs)
        self.assertIsNotNone(tex_h._shift_color_filter)

        c = Circle(center=(64, 64), radius=28)
        c.fill = tex_h
        surf = skia.Surface(128, 128)
        cnv = surf.getCanvas()
        cnv.clear(skia.ColorBLACK)
        c.draw(cnv)
        px = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
        r, g, b = int(px[64, 64, 0]), int(px[64, 64, 1]), int(px[64, 64, 2])
        self.assertGreater(g, r + 40, f"HueShift should move red toward green, got {r,g,b}")

        tex_r = Texture(
            image=red_img,
            shift=Recolor(key="red", to="blue", range=0.2),
        )
        self.assertAlmostEqual(tex_r.color.rgb[0], 1.0, places=2)
        c.fill = tex_r
        cnv.clear(skia.ColorBLACK)
        c.draw(cnv)
        px2 = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
        r2, g2, b2 = int(px2[64, 64, 0]), int(px2[64, 64, 1]), int(px2[64, 64, 2])
        self.assertGreater(b2, r2 + 80, f"Recolor red→blue expected blue center, got {r2,g2,b2}")

        # Cover and tile both install the ColorFilter (smoke draw).
        tile = Texture(
            image=red_img, fit="tile", tile_size=16,
            shift=HueShift(amount=0.5),
        )
        c.fill = tile
        cnv.clear(skia.ColorBLACK)
        c.draw(cnv)
        px3 = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
        self.assertGreater(int(px3[64, 64, 0]) + int(px3[64, 64, 1]) + int(px3[64, 64, 2]), 20)

    def test_texture_shift_composes_with_glow(self):
        """shift= is material; Glow stamp owns fill_filter pigment."""
        info = skia.ImageInfo.Make(
            8, 8, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType,
        )
        surf = skia.Surface.MakeRaster(info)
        surf.getCanvas().clear(skia.ColorSetARGB(255, 0, 0, 255))
        tex = Texture(image=surf.makeImageSnapshot(), shift=HueShift(amount=0.2))
        c = Circle(center=(50, 50), radius=20)
        c.fill = tex
        c.glow = Glow("cyan", radius=10, sigma=5)
        self.assertIsNotNone(c.fill_filter)
        self.assertIsInstance(c.glow, Glow)
        self.assertIsNone(c.visual)

    def test_filter_interning(self):
        a = GlowFilter()
        b = GlowFilter()
        self.assertIs(a, b)
        c = GlowFilter(radius=20, sigma=8)
        self.assertIsNot(a, c)

    def test_outer_glow_named_color_and_intern(self):
        from scena.color import Color
        a = GlowFilter(color="gold")
        b = GlowFilter(color="gold")
        self.assertIs(a, b)
        expected_rgb = tuple(round(float(c), 3) for c in Color("gold").rgb[:3])
        self.assertEqual(a._color[:3], expected_rgb)
        # Same resolved RGB as explicit tuple → same interned instance
        c = GlowFilter(color=Color("gold").rgb)
        self.assertIs(a, c)

    def test_set_clear_visual(self):
        c = Circle(center=(100, 100), radius=20)
        c.visual = Neon()
        self.assertIsNotNone(c.visual)
        c.visual = None
        self.assertIsNone(c.visual)
        c.visual = MultiBorder()
        self.assertIsInstance(c.visual, MultiBorder)

    def test_live_style_core(self):
        c = Circle(center=(50, 50), radius=15).set_color("red")
        c.line_width = 4
        c.visual = Neon()
        self.assertEqual(c.line_width, 4.0)

    def test_hit_test_ignores_visual(self):
        c = Circle(center=(100, 100), radius=20)
        self.assertTrue(c.contains_point(100, 100))
        c.visual = Neon(amount=2.0, width=20)
        self.assertTrue(c.contains_point(100, 100))
        self.assertFalse(c.contains_point(200, 200))

    def test_path_cache_regular_polygon(self):
        p = RegularPolygon(n=6, center=(100, 100), radius=30)
        surf = skia.Surface(200, 200)
        cnv = surf.getCanvas()
        p._geometry_draw(cnv)
        path1 = p._geom_path
        p._geometry_draw(cnv)
        self.assertIs(path1, p._geom_path)
        p.radius = 40
        p._geometry_draw(cnv)
        self.assertIsNot(path1, p._geom_path)

    def test_draw_smoke(self):
        surf = skia.Surface(256, 256)
        cnv = surf.getCanvas()
        shapes = [
            Circle(center=(80, 80), radius=25),
            Rect(center=(160, 120), width=40, height=30),
            RegularPolygon(n=5, center=(100, 180), radius=22),
        ]
        for shp in shapes:
            for cls in VISUAL_CLASSES:
                with self.subTest(shape=type(shp).__name__, visual=cls.__name__):
                    shp.visual = cls()
                    shp.draw(cnv)
            shp.visual = None
            with self.subTest(shape=type(shp).__name__, visual="Tail"):
                shp.tail = Tail()
                shp.draw(cnv)
                shp.tail = None

    def test_shared_visual_no_error(self):
        visual = Neon()
        shapes = [Circle(center=(30 + i * 40, 100), radius=12) for i in range(8)]
        for s in shapes:
            s.visual = visual
        canvas.batch_shared_filters = True
        surf = skia.Surface(400, 200)
        cnv = surf.getCanvas()
        for s in shapes:
            s.draw(cnv)

    def test_procedural_fill(self):
        c = Circle(center=(50, 50), radius=20)
        c.fill = WaterFill()
        paint = c._to_skia_fill_paint()
        self.assertIsNotNone(paint)
        self.assertIsNotNone(paint.getShader())
        c.fill = SwellFill()
        paint2 = c._to_skia_fill_paint()
        self.assertIsNotNone(paint2.getShader())

    def test_procedural_fill_amount_speed_live(self):
        fill = FlameFill(amount=1.0, speed=1.2)
        self.assertAlmostEqual(fill.amount, 1.0)
        self.assertAlmostEqual(fill.speed, 1.2)
        fill.amount = 1.6
        fill.speed = 0.5
        self.assertAlmostEqual(fill.amount, 1.6)
        self.assertAlmostEqual(fill._amount, 1.6)
        self.assertAlmostEqual(fill.speed, 0.5)
        self.assertAlmostEqual(fill._speed, 0.5)

    def test_colorable_fills(self):
        for factory, color in (
            (WaveFill, "cyan"),
            (AuroraFill, "lime"),
        ):
            with self.subTest(factory=factory.__name__):
                c = Circle(center=(50, 50), radius=18)
                c.fill = factory(color=color, amount=1.0)
                paint = c._to_skia_fill_paint()
                self.assertIsNotNone(paint)
                self.assertIsNotNone(paint.getShader())
                fill = c.fill
                self.assertIsNotNone(fill.color)
                surf = skia.Surface(128, 128)
                cnv = surf.getCanvas()
                cnv.clear(skia.ColorBLACK)
                c.draw(cnv)
                # Center pixel must be non-black (fill coverage regression guard)
                img = surf.makeImageSnapshot()
                px = img.toarray(colorType=skia.kRGBA_8888_ColorType)
                # BGRA or RGBA rows: mid pixel of shape center
                r = int(px[50, 50, 0]) if px.ndim == 3 else 0
                g = int(px[50, 50, 1]) if px.ndim == 3 else 0
                b = int(px[50, 50, 2]) if px.ndim == 3 else 0
                self.assertGreater(r + g + b, 30, f"{factory.__name__} center too dark {r,g,b}")

    def test_new_visuals_intern(self):
        self.assertIs(Laser("cyan"), Laser("cyan"))
        self.assertIs(Laser(), Laser(amount=1.0))
        self.assertIsNot(Laser(amount=1.0), Laser(amount=2.0))
        self.assertIs(Ink(), Ink())
        self.assertIs(Ink("navy"), Ink("navy"))
        self.assertIs(InkBleed(), InkBleed())
        self.assertIs(Gel(amount=1.0), Gel(amount=1.0))
        self.assertIsNot(Laser("red"), Laser("blue"))
        self.assertIsNot(Ink("red"), Ink("blue"))
        # Laser default (seed color for zero-arg) is red
        self.assertGreater(Laser().color[0], Laser().color[1])
        self.assertGreater(Laser().color[0], Laser().color[2])
        self.assertIs(Metal(), Metal())
        self.assertEqual(Metal()._fill._kind, "metal")
        # Shield orbs intern by flat style (style is keyword-only)
        self.assertIs(Shield(style="bubble"), Shield(style="bubble"))
        self.assertIs(GearShell(), GearShell())
        self.assertIsNot(Shield(style="nebula"), Shield(style="molten"))
        with self.assertRaises(ValueError):
            Shield(style="stars")
        with self.assertRaises(TypeError):
            Shield(style="nebula", palette="classic")
        self.assertIs(Shield(style="nebula"), Shield(style="nebula"))
        self.assertIsNot(Shield(style="nebula"), Shield(style="ember"))
        self.assertIs(Shield(style="cracks"), Shield(style="cracks"))
        self.assertIsNot(Shield(style="frost"), Shield(style="cracks"))
        # Tinted styles intern by color seed (host when color=None)
        self.assertIs(Shield(style="bands"), Shield(style="bands"))
        self.assertIs(Halo("magenta", style="line"), Halo("magenta", style="line"))
        self.assertIsNot(Halo("red", style="line"), Halo("blue", style="line"))
        self.assertIsNot(
            Shield(color="red", style="bands"), Shield(color="blue", style="bands")
        )
        # color is first positional; style must be keyword
        self.assertIs(Shield("magenta", style="bands"), Shield(color="magenta", style="bands"))
        with self.assertRaises(TypeError):
            Shield("bands", "magenta")  # style is keyword-only
        self.assertIs(Halo(style="fill"), Halo(style="fill"))
        self.assertIs(Halo(style="soft"), Halo(style="soft"))
        self.assertIsNot(Halo(style="fill"), Halo(style="soft"))
        self.assertIsNot(Halo(style="fill"), Halo())
        self.assertIs(Halo(style="line"), Halo(style="line"))
        self.assertIsInstance(Halo(style="fill"), Halo)
        self.assertIsInstance(Halo(style="line"), Halo)
        self.assertIs(Shield(style="plasma"), Shield(style="plasma"))
        self.assertIs(Halo(style="hollow"), Halo())
        self.assertIsNot(Halo(), Halo(style="fill"))
        with self.assertRaises(ValueError):
            Halo(style="glow")

    def test_shield_orb_styles_draw(self):
        """All shield SkSL styles compile and paint on Circle; Lines draw energy stroke."""
        surf = skia.Surface(256, 256)
        cnv = surf.getCanvas()
        c = Circle(center=(80, 80), radius=36)
        e = Ellipse(center=(180, 100), width=70, height=40)
        line = Line(p1=(10, 200), p2=(120, 220))
        line.line_width = 3
        for st in Shield._styles:
            with self.subTest(style=st):
                visual = Shield(style=st)
                c.visual = visual
                e.visual = visual
                line.visual = visual
                # Seed a solid so tinted styles sample a known hue
                try:
                    from scena.color import Color
                    c.fill = Color("lime")
                    e.fill = Color("lime")
                except Exception:
                    pass
                cnv.clear(skia.ColorBLACK)
                c.draw(cnv)
                e.draw(cnv)
                line.draw(cnv)  # skip body — no crash
                img = surf.makeImageSnapshot()
                px = img.toarray(colorType=skia.kRGBA_8888_ColorType)
                r = int(px[80, 80, 0]) if px.ndim == 3 else 0
                g = int(px[80, 80, 1]) if px.ndim == 3 else 0
                b = int(px[80, 80, 2]) if px.ndim == 3 else 0
                if st == "bubble":
                    r2 = int(px[80, 80 + 30, 0]) if px.ndim == 3 else 0
                    g2 = int(px[80, 80 + 30, 1]) if px.ndim == 3 else 0
                    b2 = int(px[80, 80 + 30, 2]) if px.ndim == 3 else 0
                    self.assertGreater(r2 + g2 + b2, 20, f"bubble rim too dark {r2,g2,b2}")
                else:
                    self.assertGreater(r + g + b, 15, f"{st} too dark {r,g,b}")
        # flat nebula / cracks family variants
        for st in ("nebula", "ember", "void", "cracks", "frost"):
            with self.subTest(style=st):
                c.visual = Shield(style=st)
                cnv.clear(skia.ColorBLACK)
                c.draw(cnv)
        c.visual = None
        e.visual = None
        line.visual = None

    def test_every_shield_style_has_its_own_body(self):
        """Two styles must not paint the same body.

        Regression 2026-10: ``frost`` shared the ``shield_cracks`` shader, whose
        rock / lava / spark colors were constants: only its rim was icy, so it
        rendered as magma ("cracks"). Each style's mean body color is compared
        with every other's.
        """
        import itertools
        import numpy as np
        from scena.recipes import SHIELD_STYLES

        canvas.fx_quality = "high"
        body = {}
        for st in SHIELD_STYLES:
            c = Circle(center=(80, 80), radius=30)
            c.visual = Shield(style=st)
            c.fill_filter = None
            surf = skia.Surface(160, 160)
            cnv = surf.getCanvas()
            cnv.clear(skia.ColorBLACK)
            c.draw(cnv)
            px = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
            body[st] = px[62:98, 62:98, :3].reshape(-1, 3).astype(float).mean(axis=0)
            c.visual = None
        for a, b in itertools.combinations(SHIELD_STYLES, 2):
            with self.subTest(pair=(a, b)):
                self.assertGreater(float(np.abs(body[a] - body[b]).max()), 12.0,
                                   f"{a} and {b} paint the same body: {body[a].round()}")
        # Frost is ice, not magma.
        r, g, bl = body["frost"]
        self.assertGreater(bl, r)

    def test_shield_shape_not_sprite_envelope(self):
        """Shape Shield must not take the Sprite costume-envelope UV path.

        Regression 2026-09: ``_uses_shield_envelope`` keyed only on ``.visual``,
        so Circle/Ellipse hit missing ``_shield_envelope_half``, and the bare
        ``except`` in ``to_skia_fill_paint`` fell back to fixed-res ``tick()`` —
        empty bubble / black nebula interiors at small radii.
        """
        from scena.sprite import _uses_shield_envelope
        from scena.recipes import _center_radius

        canvas.fx_quality = "high"
        for r in (12.0, 18.0, 28.0):
            with self.subTest(radius=r):
                c = Circle(center=(64, 64), radius=r)
                c.visual = Shield(style="bubble")
                self.assertFalse(_uses_shield_envelope(c))
                self.assertFalse(hasattr(c, "_shield_envelope_half"))
                _cx, _cy, half = _center_radius(c)
                self.assertAlmostEqual(half, float(r), places=3)

        # Small Circle: bubble rim and nebula body must paint (not empty disc).
        for st in ("bubble", "nebula", "ember", "void", "molten", "cracks"):
            with self.subTest(style=st, paint="small"):
                c = Circle(center=(80, 80), radius=16)
                c.visual = Shield(style=st)
                # Strip glow filter so the assertion is about the SkSL body.
                c.fill_filter = None
                surf = skia.Surface(160, 160)
                cnv = surf.getCanvas()
                cnv.clear(skia.ColorBLACK)
                c.draw(cnv)
                px = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
                if px.ndim != 3:
                    self.fail("expected RGBA image")
                # Sum RGB over the disc AABB — empty interior was ~0.
                y0, y1 = 80 - 16, 80 + 16
                x0, x1 = 80 - 16, 80 + 16
                region = px[y0:y1, x0:x1, :3].astype("int32")
                self.assertGreater(
                    int(region.sum()),
                    800,
                    f"{st} interior too empty at r=16 (sum={int(region.sum())})",
                )

        # Batched filter path (smoke fleet) must match solo for Shape Shield UV.
        look = Shield(style="nebula")
        circles = []
        for i in range(4):
            c = Circle(center=(40 + i * 70, 60), radius=18)
            c.visual = look
            circles.append(c)
        eng = canvas._engine
        surf = skia.Surface(320, 120)
        eng.skia_canvas = surf.getCanvas()
        eng.skia_canvas.clear(skia.Color4f(0, 0, 0, 1))
        eng.batch_shared_filters = True
        eng._draw_layer_batched(circles)
        batched = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
        surf2 = skia.Surface(320, 120)
        cnv2 = surf2.getCanvas()
        cnv2.clear(skia.Color4f(0, 0, 0, 1))
        for c in circles:
            c.draw(cnv2)
        solo = surf2.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
        self.assertGreater(int(batched[:, :, :3].astype("int32").sum()), 2000)
        # Soft glow can differ by a few LSBs under batching; interiors must agree.
        self.assertLess(
            abs(int(batched.sum()) - int(solo.sum())),
            max(5000, int(0.02 * solo.sum())),
        )

    def test_shield_tinted_live_host(self):
        """bands/vortex follow live host solid fill as primary tint."""
        from scena.color import Color
        for st in ("bands", "vortex"):
            with self.subTest(style=st):
                c = Circle(center=(64, 64), radius=28)
                c.fill = Color("red")
                c.visual = Shield(style=st)  # color=None → live fill
                self.assertIsNone(c.visual._seed_color)
                tint = c.visual._primary_tint(c)
                self.assertGreater(tint[0], 0.7, f"{st} should read red host")
                c.fill = Color("lime")
                tint2 = c.visual._primary_tint(c)
                self.assertGreater(tint2[1], 0.5, f"{st} should recolor with lime")
                # Explicit color= seeds magenta into procedural package
                c2 = Circle(center=(80, 80), radius=20)
                c2.fill = Color("white")
                c2.visual = Shield("magenta", style=st)
                fill = c2.fill
                from scena.style import ProceduralFill
                self.assertIsInstance(fill, ProceduralFill)
                pc = fill._color
                self.assertIsNotNone(pc)
                self.assertGreater(pc[0] + pc[2], pc[1] * 1.2)

    def test_primary_tint_live_from_host_fill(self):
        """color=None uses host solid fill; later fill changes recolor the visual."""
        from scena.color import Color
        c = Circle(center=(64, 64), radius=28)
        c.fill = Color("red")
        c.visual = Neon()  # no color= seed
        self.assertIsNone(getattr(c.visual, "_seed_color", "x"))
        tint = c.visual._primary_tint(c)
        self.assertGreater(tint[0], 0.7)
        self.assertLess(tint[1], 0.4)
        c.fill = Color("lime")
        tint2 = c.visual._primary_tint(c)
        self.assertLess(tint2[0], 0.5)
        self.assertGreater(tint2[1], 0.6)

    def test_neon_glow_uses_vibrant_host_tint(self):
        """Body and glow share one HSV-boosted tint; primary_tint stays raw host."""
        from scena.color import Color
        c = Circle(center=(64, 64), radius=28)
        muted = Color.from_hsv(0.55, 0.2, 0.65)
        c.fill = muted
        c.visual = Neon()
        tint = c.visual._primary_tint(c)
        neon = c.visual._neon_tint(c)
        self.assertAlmostEqual(tint[0], muted.rgb[0], places=4)
        self.assertGreater(Color(*neon).hsv[1], Color(*tint).hsv[1] + 0.25)
        self.assertEqual(neon, c.visual._glow_tint(c))

    def test_vivid_rgb_matches_color_vibrant_version(self):
        """§3.5: float vivid path equals Color.vibrant_version (pixel-identical tint)."""
        from scena.color import Color, _chroma_weight
        from scena.recipes import _vivid_rgb, _energy_rgb, _energy_spark_rgb
        samples = [
            (0.35, 0.9, 1.0),
            (0.8, 0.2, 0.15),
            Color.from_hsv(0.55, 0.2, 0.65).rgb[:3],
            (0.1, 0.1, 0.1),
            (1.0, 1.0, 1.0),
        ]
        for rgb in samples:
            got = _vivid_rgb(rgb, 0.55)
            ref = Color(float(rgb[0]), float(rgb[1]), float(rgb[2]), 1.0).vibrant_version(0.55).rgb
            for a, b in zip(got, ref[:3]):
                self.assertAlmostEqual(a, b, places=5, msg=f"vivid {rgb}")
            # Energy chroma boost (milder than vivid) stays bit-stable too.
            er = _energy_rgb((*rgb, 1.0))
            c = Color(float(rgb[0]), float(rgb[1]), float(rgb[2]), 1.0)
            h, s, v, _ = c.hsv
            s2 = min(1.0, s + _chroma_weight(s) * (1.0 - s) * 0.32)
            ref_e = Color.from_hsv(h, s2, v, 1.0).rgb
            for a, b in zip(er[:3], ref_e[:3]):
                self.assertAlmostEqual(a, b, places=5, msg=f"energy {rgb}")
            sp = _energy_spark_rgb(rgb, 0.15)
            h, s, v, _ = c.hsv
            v2 = min(1.0, v + (1.0 - v) * 0.15)
            ref_s = Color.from_hsv(h, min(1.0, s * 1.05), v2, 1.0).rgb
            for a, b in zip(sp, ref_s[:3]):
                self.assertAlmostEqual(a, b, places=5, msg=f"spark {rgb}")

    def test_neon_binds_fill_not_outline_on_closed(self):
        """Closed shapes sample fill for neon; host outline color is irrelevant."""
        from scena.color import Color
        c = Circle(center=(64, 64), radius=28)
        c.fill = Color("cyan")
        c.line = Color("red")
        c.line_width = 4
        c.visual = Neon()
        tint = c.visual._primary_tint(c)
        self.assertLess(tint[0], 0.4)
        self.assertGreater(tint[2], 0.5)

    def test_neon_glow_uses_gradient_fill_not_outline(self):
        """Gradient fills still drive neon glow; must not fall back to line color."""
        c = Circle(center=(64, 64), radius=28)
        c.fill = Gradient("cyan", "blue", type="radial", size=40)
        c.line = Color("red")
        c.line_width = 4
        c.visual = Neon()
        tint = c.visual._primary_tint(c)
        glow = c.visual._glow_tint(c)
        # Cyan-ish from gradient first stop, not red outline
        self.assertLess(tint[0], 0.45)
        self.assertGreater(tint[1] + tint[2], 1.2)
        self.assertLess(glow[0], 0.55)

    def test_neon_constructor_color_when_no_live_channel(self):
        c = Circle(center=(64, 64), radius=28)
        c.fill = None
        c.line = None
        c.visual = Neon("magenta")
        # Seed writes fill on apply; primary follows that fill
        tint = c.visual._primary_tint(c)
        self.assertGreater(tint[0] + tint[2], tint[1] * 1.5)

    def test_neon_binds_line_on_line_shape(self):
        from scena.color import Color
        ln = Line(p1=(10, 10), p2=(100, 20))
        ln.line = Color("magenta")
        ln.line_width = 3
        ln.visual = Neon()
        tint = ln.visual._primary_tint(ln)
        self.assertGreater(tint[0] + tint[2], tint[1] * 1.5)

    def test_color_arg_seeds_host_then_live(self):
        """Explicit color= writes into bound channel once; further edits still bind live."""
        from scena.color import Color
        c = Circle(center=(64, 64), radius=28)
        c.fill = Color("white")
        c.visual = Neon("magenta")
        # Seed should have written solid magenta-ish fill (high R and B, low G)
        fill = c.fill
        self.assertIsInstance(fill, Color)
        fr, fg, fb = fill.rgb[0], fill.rgb[1], fill.rgb[2]
        self.assertGreater(fr + fb, fg * 1.5)
        self.assertGreater(fr, 0.5)
        # Overwrite host after assignment — visual follows live
        c.fill = Color("cyan")
        tint = c.visual._primary_tint(c)
        self.assertLess(tint[0], 0.4)
        self.assertGreater(tint[2], 0.5)

    def test_laser_binds_line_channel(self):
        from scena.color import Color
        ln = Line(p1=(10, 10), p2=(100, 20))
        ln.line_width = 3
        ln.line = Color("blue")
        ln.visual = Laser()  # no seed → follows host line
        t = ln.visual._primary_tint(ln)
        self.assertGreater(t[2], t[0])  # blue-ish
        ln.visual = Laser("red")  # seeds line red
        self.assertIsInstance(ln.line, Color)
        lp = ln.line.rgb
        self.assertGreater(lp[0], lp[1])
        self.assertGreater(lp[0], lp[2])
        ln.line = Color("green")
        t2 = ln.visual._primary_tint(ln)
        self.assertGreater(t2[1], t2[0])

    def test_laser_line_keeps_absolute_width_ladder(self):
        """Line laser uses designed outline widths (same hierarchy as circle rims).

        Outline-mode host scaling used to collapse/invert layers on Line so the
        white core was thicker than the mid — lines must not use that path.
        """
        import skia
        from scena.fx_quality import activate_quality

        widths = []
        orig = Laser._stroke_paint

        def spy(self, *, color, width, blend=None, path_effect=None, alpha=None, mask=None, **kwargs):
            widths.append(float(width))
            return orig(
                self, color=color, width=width, blend=blend,
                path_effect=path_effect, alpha=alpha, mask=mask, **kwargs,
            )

        Laser._stroke_paint = spy
        try:
            info = skia.ImageInfo.Make(
                64, 64, skia.ColorType.kRGBA_8888_ColorType, skia.AlphaType.kPremul_AlphaType,
            )
            canvas = skia.Surface.MakeRaster(info).getCanvas()
            for quality, expect_min_layers in (("low", 2), ("medium", 3), ("high", 3)):
                activate_quality(quality)
                widths.clear()
                ln = Line(p1=(5, 10), p2=(55, 50))
                ln.line_width = 3.0
                ln.fill = None
                ln.set_color("cyan")
                ln.visual = Laser(amount=1.0)
                ln.draw(canvas)
                self.assertGreaterEqual(len(widths), expect_min_layers, quality)
                # Strict descending ladder on the energy beam
                for a, b in zip(widths, widths[1:]):
                    self.assertGreater(a, b, f"{quality}: {widths}")
                # Core must stay thin vs halo/body (not scaled up toward host)
                self.assertLess(widths[-1], 2.0, f"{quality}: fat core {widths}")
        finally:
            Laser._stroke_paint = orig
            activate_quality("high")

    def test_plasmashot_tesla_skips_bolts_on_line(self):
        """Tesla bolts are closed-shape only; Line matches core/filaments glow."""
        class _CountCanvas:
            def __init__(self, inner):
                self._inner = inner
                self.paths = 0

            def drawPath(self, path, paint):
                self.paths += 1
                return self._inner.drawPath(path, paint)

            def __getattr__(self, name):
                return getattr(self._inner, name)

        surf = skia.Surface(128, 128)
        inner = surf.getCanvas()
        inner.clear(skia.ColorBLACK)
        wrap = _CountCanvas(inner)
        look = Bolt(style="tesla", intensity=1.0)
        c = Circle(center=(64, 64), radius=28)
        c.visual = look
        c.draw(wrap)
        self.assertGreater(wrap.paths, 0, "closed tesla should draw bolts")
        wrap.paths = 0
        ln = Line(p1=(10, 20), p2=(110, 40))
        ln.line_width = 3.0
        ln.set_color("cyan")
        ln.visual = look
        ln.draw(wrap)
        self.assertEqual(wrap.paths, 0, "Line tesla must not draw bolts")

    def test_organic_outline_uses_line_variation(self):
        """Organic fringe follows line (not fill) and is lighter/softer than solid stroke."""
        from scena.color import Color
        c = Circle(center=(50, 50), radius=20)
        c.fill = Color("red")
        c.line = Color("navy")
        c.visual = OrganicOutline()
        self.assertEqual(c.visual._tint_channel, "line")
        base = c.visual._primary_tint(c)
        # Primary is navy-like (line), not red (fill)
        self.assertGreater(base[2], base[0])
        self.assertLess(base[0], 0.4)
        fringe = c.visual._organic_stroke_color(c)
        # Variation: higher luminance and/or lower alpha than full solid line
        base_lum = 0.2126 * base[0] + 0.7152 * base[1] + 0.0722 * base[2]
        fringe_lum = 0.2126 * fringe[0] + 0.7152 * fringe[1] + 0.0722 * fringe[2]
        self.assertGreater(fringe_lum, base_lum - 1e-6)
        self.assertLess(fringe[3], 1.0 + 1e-6)
        self.assertNotEqual(tuple(round(x, 3) for x in fringe[:3]),
                            tuple(round(x, 3) for x in base[:3]))

    def test_gel_live_recolor_smoke(self):
        """Draw Gel with live host recolor produces non-empty pixels (tint path works)."""
        from scena.color import Color
        c = Circle(center=(64, 64), radius=28)
        c.fill = Color(1.0, 0.2, 0.2, 1.0)
        c.visual = Gel()  # host-driven candy body
        surf = skia.Surface(128, 128)
        cnv = surf.getCanvas()
        cnv.clear(skia.ColorBLACK)
        c.draw(cnv)
        px = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
        r, g, b = int(px[64, 64, 0]), int(px[64, 64, 1]), int(px[64, 64, 2])
        self.assertGreater(r + g + b, 30, f"Gel host-tint center empty {r,g,b}")
        # switch host to cyan and redraw
        c.fill = Color(0.1, 0.85, 0.9, 1.0)
        cnv.clear(skia.ColorBLACK)
        c.draw(cnv)
        px2 = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
        r2, g2, b2 = int(px2[64, 64, 0]), int(px2[64, 64, 1]), int(px2[64, 64, 2])
        self.assertGreater(r2 + g2 + b2, 30)
        # After recolor, red channel should fall relative to first frame (red gel vs cyan gel)
        self.assertNotEqual((r, g, b), (r2, g2, b2))

    def test_ink_preserves_host_fill(self):
        """Ink looks draw host colors, not a navy wash."""
        c = Circle(center=(64, 64), radius=28).set_color("tomato")
        c.visual = Ink()
        surf = skia.Surface(128, 128)
        cnv = surf.getCanvas()
        cnv.clear(skia.ColorBLACK)
        c.draw(cnv)
        px = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
        r, g, b = int(px[64, 64, 0]), int(px[64, 64, 1]), int(px[64, 64, 2])
        # Tomato-ish host should be red-dominant at center
        self.assertGreater(r + g + b, 40)
        self.assertGreater(r, g)
        self.assertGreater(r, b)

    def test_non_tinted_recipe_ignores_color_channel_seed(self):
        """Water does not bind host color (tint_channel is None)."""
        from scena.color import Color
        c = Circle(center=(50, 50), radius=20)
        before = c.fill
        c.visual = Water()
        self.assertIsNone(c.visual._tint_channel)
        # Assignment with no seed must not rewrite fill
        self.assertIs(c.fill, before)
        c.fill = Color("red")
        c.visual = Water()  # still no write
        self.assertIsInstance(c.fill, Color)
        self.assertGreater(c.fill.rgb[0], 0.5)


    def test_plasma_shot_centered(self):
        for style in ("core", "filaments"):
            with self.subTest(style=style):
                c = Circle(center=(64, 64), radius=28)
                c.visual = Bolt(style=style, intensity=1.2)
                surf = skia.Surface(128, 128)
                cnv = surf.getCanvas()
                cnv.clear(skia.ColorBLACK)
                c.draw(cnv)
                px = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
                # Center bright; far corner dark
                cr = int(px[64, 64, 0]) + int(px[64, 64, 1]) + int(px[64, 64, 2])
                corner = int(px[8, 8, 0]) + int(px[8, 8, 1]) + int(px[8, 8, 2])
                self.assertGreater(cr, 60, f"plasma {style} center empty")
                self.assertGreater(cr, corner)

    def test_sphere_visual_has_fill(self):
        c = Circle(center=(64, 64), radius=28)
        c.visual = Sphere("steel blue")
        surf = skia.Surface(128, 128)
        cnv = surf.getCanvas()
        cnv.clear(skia.ColorBLACK)
        c.draw(cnv)
        img = surf.makeImageSnapshot()
        px = img.toarray(colorType=skia.kRGBA_8888_ColorType)
        r, g, b = int(px[64, 64, 0]), int(px[64, 64, 1]), int(px[64, 64, 2])
        self.assertGreater(r + g + b, 40, f"Sphere center empty {r,g,b}")

    def test_field_shells_on_compatible_shapes(self):
        visuals = (
            DashRing(),
            Halo(),
            Halo(style="fill"),
            Halo(style="soft"),
            GearShell(),
            ElectricField(),
        )
        _line = Line(p1=(40, 40), p2=(180, 90))
        _line.line_width = 3.0
        shapes = (
            Circle(center=(120, 120), radius=40),
            Ellipse(center=(200, 150), width=90, height=50, angle=25),
            _line,
            Rect(center=(80, 80), width=40, height=30),
            RegularPolygon(n=5, center=(160, 80), radius=28),
        )
        for visual in visuals:
            for shp in shapes:
                shp.visual = visual
                surf = skia.Surface(256, 256)
                shp.draw(surf.getCanvas())



    def test_paint_matches_set_color(self):
        from scena import Paint
        from scena.color import Color
        a = Circle(center=(10, 10), radius=5)
        a.set_color("tomato")
        b = Circle(center=(10, 10), radius=5, color="tomato")
        c = Circle(center=(10, 10), radius=5, visual=Paint("tomato"))
        d = Circle(center=(10, 10), radius=5, visual=Paint(color="tomato"))
        self.assertEqual(a.fill.rgb, b.fill.rgb)
        self.assertEqual(a.line.rgb, b.line.rgb)
        self.assertEqual(b.fill.rgb, c.fill.rgb)
        self.assertEqual(b.line.rgb, c.line.rgb)
        self.assertEqual(c.fill.rgb, d.fill.rgb)
        self.assertIs(Paint("tomato"), Paint(color="tomato"))
        self.assertIs(Paint("tomato"), Paint(material="tomato"))
        with self.assertRaises(TypeError):
            Paint("tomato", color="cyan")

    def test_set_color_area_fill_plus_contrast_stroke(self):
        from scena.color import Color
        c = Circle(center=(10, 10), radius=5).set_color("tomato")
        self.assertAlmostEqual(c.fill.rgb[0], Color("tomato").rgb[0], places=2)
        self.assertTrue(c.line)
        self.assertNotEqual(c.fill.rgb[:3], c.line.rgb[:3])

    def test_set_color_line_uses_stroke_channel(self):
        from scena.color import Color
        ln = Line(p1=(0, 0), p2=(10, 0)).set_color("cyan")
        self.assertFalse(ln.fill)
        self.assertAlmostEqual(ln.line.rgb[2], Color("cyan").rgb[2], places=2)

    def test_paint_line_matches_set_color(self):
        from scena import Paint
        a = Line(p1=(0, 0), p2=(10, 0)).set_color("magenta")
        b = Line(p1=(0, 0), p2=(10, 0), color="magenta")
        c = Line(p1=(0, 0), p2=(10, 0), visual=Paint("magenta"))
        self.assertFalse(a.fill)
        self.assertFalse(b.fill)
        self.assertFalse(c.fill)
        self.assertEqual(a.line.rgb, b.line.rgb)
        self.assertEqual(b.line.rgb, c.line.rgb)

    def test_set_color_and_paint_gradient_primary_channel(self):
        from scena import Paint, Gradient
        g = Gradient("navy", "cyan", type="linear", size=40)
        circle = Circle(center=(10, 10), radius=8).set_color(g)
        self.assertIs(circle.fill, g)
        self.assertTrue(bool(circle.line))
        expected = g.mean_color().darker(0.2)
        self.assertAlmostEqual(circle.line.rgb[0], expected.rgb[0], places=4)
        self.assertAlmostEqual(circle.line.rgb[1], expected.rgb[1], places=4)
        self.assertAlmostEqual(circle.line.rgb[2], expected.rgb[2], places=4)

        g2 = Gradient("magenta", "cyan", size=30)
        ln = Line(p1=(0, 0), p2=(20, 0)).set_color(g2)
        self.assertIs(ln.line, g2)
        self.assertFalse(ln.fill)

        g3 = Gradient("plasma")
        painted = Circle(center=(0, 0), radius=5, visual=Paint(g3))
        self.assertIs(painted.fill, g3)
        self.assertTrue(bool(painted.line))
        exp3 = g3.mean_color().darker(0.2)
        self.assertAlmostEqual(painted.line.rgb[0], exp3.rgb[0], places=4)

        g4 = Gradient("heat")
        painted_ln = Line(p1=(0, 0), p2=(5, 5), color=g4)
        self.assertIs(painted_ln.line, g4)
        self.assertFalse(painted_ln.fill)

    def test_color_and_visual_mutex(self):
        with self.assertRaises(ValueError):
            Circle(center=(0, 0), radius=5, color="red", visual=Paint("blue"))

    def test_aura_medium_filterless_add(self):
        """Halo / Halo(style='fill') medium: no ImageFilter, sharp ADD outline."""
        from scena.canvas import _must_solo_draw
        from scena.fx_quality import activate_quality
        canvas.fx_quality = "medium"
        look = Halo()
        a = Circle(center=(0, 0), radius=10).set_color("cyan")
        b = Circle(center=(0, 0), radius=10).set_color("tomato")
        a.visual = look
        b.visual = look
        self.assertTrue(look._MED_FILTERLESS)
        self.assertTrue(a.visual._is_multipass)
        self.assertTrue(_must_solo_draw(a))
        self.assertIs(a.visual, b.visual)
        self.assertIsNone(a.line_filter)
        self.assertIsNone(a.fill_filter)
        self.assertLess(a.fill.rgb[3], 0.25)
        surf = skia.Surface(64, 64)
        a.draw(surf.getCanvas())
        ln = Line(p1=(0, 0), p2=(40, 0)).set_color("tomato")
        ln.visual = Halo()
        self.assertIsNone(ln.line_filter)
        ln.draw(surf.getCanvas())
        f = Circle(center=(0, 0), radius=10).set_color("gold")
        f.visual = Halo(style="fill")
        self.assertTrue(f.visual._MED_FILTERLESS)
        self.assertIsNone(f.line_filter)
        self.assertGreater(f.fill.rgb[3], 0.9)
        f.draw(surf.getCanvas())
        activate_quality("high")
        a.visual._apply(a)
        self.assertIsNotNone(a.line_filter)
        self.assertFalse(a.visual._is_multipass)
        self.assertFalse(_must_solo_draw(a))
        activate_quality("medium")
        a.visual._apply(a)
        self.assertIsNone(a.line_filter)

    def test_phantom_high_uses_medium(self):
        """Halo(style='soft') uses batched HostGlow at medium and high, not fill's ADD outline."""
        from scena.canvas import _must_solo_draw
        from scena.fx_quality import activate_quality
        canvas.fx_quality = "medium"
        look = Halo(style="soft")
        a = Circle(center=(0, 0), radius=10).set_color("cyan")
        a.visual = look
        self.assertFalse(look._is_multipass)
        self.assertFalse(_must_solo_draw(a))
        self.assertIsInstance(a.line_filter, HostGlow)
        self.assertIs(a.line_filter, look._halo_med)
        self.assertAlmostEqual(float(a.line_width), 1.4, places=1)
        self.assertAlmostEqual(float(a.line_filter._spread), look._MED_SPREAD, places=2)
        self.assertGreater(a.fill.rgb[3], 0.9)
        med_spread = float(a.line_filter._spread)
        activate_quality("high")
        a.visual._apply(a)
        self.assertFalse(look._is_multipass)
        self.assertFalse(_must_solo_draw(a))
        self.assertIs(a.line_filter, look._halo_med)
        self.assertAlmostEqual(float(a.line_width), 1.4, places=1)
        self.assertAlmostEqual(float(a.line_filter._spread), med_spread, places=2)
        self.assertGreater(a.fill.rgb[3], 0.9)
        activate_quality("high")

    def test_phantom_high_skips_aura_rim(self):
        """Halo(style='soft') high must not draw Halo's ADD rim/spine on top of HostGlow."""
        hits = []
        soft_cls = type(Halo(style="soft"))
        orig = soft_cls._draw_extra_rim

        def wrapped(self, shape, skia_canvas):
            hits.append(1)
            return orig(self, shape, skia_canvas)

        soft_cls._draw_extra_rim = wrapped
        try:
            canvas.fx_quality = "high"
            look = Halo(style="soft")
            c = Circle(center=(0, 0), radius=10).set_color("cyan")
            c.visual = look
            self.assertIsInstance(c.line_filter, HostGlow)
            surf = skia.Surface(64, 64)
            c.draw(surf.getCanvas())
            ln = Line(p1=(0, 0), p2=(40, 0)).set_color("tomato")
            ln.visual = look
            ln.draw(surf.getCanvas())
            self.assertEqual(hits, [])
        finally:
            soft_cls._draw_extra_rim = orig
            canvas.fx_quality = "high"

    def test_aura_high_rim_pass(self):
        from scena import Blur
        from scena.canvas import _must_solo_draw
        canvas.fx_quality = "high"
        a = Circle(center=(0, 0), radius=10).set_color("cyan")
        a.visual = Halo()
        self.assertFalse(a.visual._is_multipass)
        self.assertFalse(_must_solo_draw(a))
        self.assertIsInstance(a.line_filter, Blur)
        self.assertAlmostEqual(float(a.line_width), 3.2, places=1)
        surf = skia.Surface(64, 64)
        a.draw(surf.getCanvas())
        ln = Line(p1=(0, 0), p2=(40, 0)).set_color("cyan")
        ln.visual = Halo()
        self.assertIsInstance(ln.line_filter, Blur)
        self.assertAlmostEqual(float(ln.line_width), 3.2, places=1)
        ln.draw(surf.getCanvas())
        self.assertGreater(float(Halo()._SPINE_WIDTH), 0.5)

    def test_glowrim_keepers_high_uses_blur(self):
        """Shipped glow/rim highs: GPU Blur on the stroke, not MaskFilter / GlowFilter."""
        from scena import Blur
        from scena.fx_quality import activate_quality
        from scena.style import BlendMode
        canvas.fx_quality = "high"
        looks = (ElectricField(), ElectricBolt(), Shield(style="plasma"))
        surf = skia.Surface(64, 64)
        for look in looks:
            with self.subTest(visual=type(look).__name__):
                self.assertIs(look, type(look)())
                c = Circle(center=(0, 0), radius=10).set_color("cyan")
                c.visual = look
                self.assertFalse(look._is_multipass)
                self.assertIsInstance(c.line_filter, Blur)
                self.assertIsNone(c.fill_filter)
                if type(look).__name__ == "ElectricField":
                    amt = float(look.amount)
                    wash = min(1.0, max(0.06, look._high._HIGH_WASH * max(0.35, amt)))
                    self.assertAlmostEqual(float(c.fill.rgb[3]), wash, places=2)
                    self.assertEqual(c.blend, "add")
                c.draw(surf.getCanvas())
                ln = Line(p1=(0, 0), p2=(40, 0)).set_color("tomato")
                ln.visual = look
                self.assertIsInstance(ln.line_filter, Blur)
                ln.draw(surf.getCanvas())
        activate_quality("medium")
        c = Circle(center=(0, 0), radius=10).set_color("cyan")
        c.visual = ElectricField()
        self.assertIsInstance(c.line_filter, Blur)
        self.assertFalse(c.visual._is_multipass)
        c.draw(surf.getCanvas())
        activate_quality("low")
        c.visual._apply(c)
        self.assertIsNone(c.line_filter)
        self.assertTrue(c.visual._is_multipass)
        c.draw(surf.getCanvas())
        activate_quality("high")

    def test_rim_high_glowrim(self):
        """Shape Rim uses GlowRim at every quality; Sprite has no ImageFilter."""
        from scena import Blur
        from scena.canvas import _has_any_batchable_filter, _must_solo_draw
        from scena.fx_quality import activate_quality
        from scena.style import BlendMode

        canvas.fx_quality = "high"
        look = Rim(darken=0)
        self.assertIs(look, Rim(darken=0))
        self.assertFalse(look._is_multipass)
        self.assertIsInstance(look._high._halo_high, Blur)
        self.assertFalse(hasattr(look, "_mask_soft"))
        surf = skia.Surface(64, 64)
        c = Circle(center=(0, 0), radius=10).set_color("tomato")
        host_fill = tuple(c.fill.rgb[:3])
        c.visual = look
        self.assertIsInstance(c.line_filter, Blur)
        self.assertIs(c.line_filter, look._high._halo_high)
        self.assertIsNone(c.fill_filter)
        self.assertEqual(c.blend, "normal")
        self.assertAlmostEqual(c.fill.rgb[0], host_fill[0], places=2)
        self.assertAlmostEqual(float(c.line_width), 8.0, places=1)
        self.assertFalse(_must_solo_draw(c))
        self.assertTrue(_has_any_batchable_filter(c))
        c.draw(surf.getCanvas())
        d = Circle(center=(40, 0), radius=10).set_color("cyan")
        d.visual = look
        self.assertIs(c.line_filter, d.line_filter)
        ln = Line(p1=(0, 0), p2=(40, 0)).set_color("cyan")
        ln.visual = Rim(darken=0)
        self.assertIsInstance(ln.line_filter, Blur)
        ln.draw(surf.getCanvas())

        baked = Circle(center=(0, 0), radius=10).set_color("tomato")
        before = tuple(baked.fill.rgb[:3])
        baked.visual = Rim()
        self.assertLess(baked.fill.rgb[0], before[0])

        for q in ("medium", "low"):
            activate_quality(q)
            c.visual._apply(c)
            self.assertIsInstance(c.line_filter, Blur)
            self.assertFalse(c.visual._is_multipass)
            self.assertFalse(_must_solo_draw(c))
            self.assertAlmostEqual(float(c.line_width), 8.0, places=1)
            c.draw(surf.getCanvas())
        activate_quality("high")
        c.visual._apply(c)
        self.assertIsInstance(c.line_filter, Blur)
        self.assertFalse(c.visual._is_multipass)

    def test_electricfield_pe_seed_uncapped_at_medium(self):
        """ElectricField flicker uses speed×14 at medium; lite pe_hz does not slow it."""
        import scena.recipes as recipes
        from scena.fx_quality import activate_quality

        orig = recipes._clock
        recipes._clock = lambda: 1.0
        try:
            activate_quality("medium")
            self.assertEqual(recipes._pe_seed(14.0), 8)
            self.assertEqual(recipes._pe_seed(14.0, cap=False), 14)
            activate_quality("high")
            self.assertEqual(recipes._pe_seed(14.0), 14)
            self.assertEqual(recipes._pe_seed(14.0, cap=False), 14)
        finally:
            recipes._clock = orig
            activate_quality("high")

    def test_aura_high_shares_blur_batch_key(self):
        """Halo high is not solo; mixed host tints share interned Blur batch_key."""
        from scena import Blur
        from scena.canvas import _has_any_batchable_filter, _must_solo_draw

        canvas.fx_quality = "high"
        look = Halo()
        a = Circle(center=(0, 0), radius=10).set_color("cyan")
        b = Circle(center=(40, 0), radius=10).set_color("tomato")
        a.visual = look
        b.visual = look
        self.assertFalse(a.visual._is_multipass)
        self.assertFalse(_must_solo_draw(a))
        self.assertFalse(_must_solo_draw(b))
        self.assertTrue(_has_any_batchable_filter(a))
        self.assertIsInstance(a.line_filter, Blur)
        self.assertIs(a.line_filter, b.line_filter)
        self.assertEqual(a.line_filter._batch_key, b.line_filter._batch_key)
        ef = ElectricField()
        c = Circle(center=(80, 0), radius=10).set_color("gold")
        d = Circle(center=(120, 0), radius=10).set_color("magenta")
        c.visual = ef
        d.visual = ef
        self.assertFalse(_must_solo_draw(c))
        self.assertTrue(_has_any_batchable_filter(c))
        self.assertIs(c.line_filter, d.line_filter)
        self.assertEqual(c.line_filter._batch_key, d.line_filter._batch_key)

    def test_aura_high_overlay_after_stroke_pass(self):
        """Deferred rims run after the batched stroke plate, not inside the Blur RT."""
        canvas.fx_quality = "high"
        look = Halo()
        a = Circle(center=(20, 20), radius=10).set_color("cyan")
        b = Circle(center=(60, 20), radius=10).set_color("tomato")
        a.visual = look
        b.visual = look
        eng = canvas._engine
        order = []
        orig_strokes = eng._draw_strokes_in_layer
        orig_ov = eng._draw_deferred_overlays

        def strokes(shapes):
            order.append("strokes")
            return orig_strokes(shapes)

        def ov(shapes):
            order.append("overlay")
            return orig_ov(shapes)

        eng._draw_strokes_in_layer = strokes
        eng._draw_deferred_overlays = ov
        surf = skia.Surface(128, 64)
        eng.skia_canvas = surf.getCanvas()
        try:
            eng._draw_filtered_segment([a, b])
        finally:
            eng._draw_strokes_in_layer = orig_strokes
            eng._draw_deferred_overlays = orig_ov
        self.assertEqual(order, ["strokes", "overlay"])

    def test_aura_high_transient_still_draws(self):
        """Active transient solos Halo high; overlay path must not crash."""
        from scena.canvas import _must_solo_draw
        from scena.transients import has_active_transient

        canvas.fx_quality = "high"
        a = Circle(center=(0, 0), radius=10).set_color("cyan")
        a.visual = Halo()
        self.assertFalse(_must_solo_draw(a))
        a.flash()
        self.assertTrue(_must_solo_draw(a))
        surf = skia.Surface(64, 64)
        a.draw(surf.getCanvas())
        a.clear_transients()
        self.assertFalse(has_active_transient(a))

    def test_neon_and_aura_medium_still_solo(self):
        from scena.canvas import _must_solo_draw
        from scena.fx_quality import activate_quality

        c = Circle(center=(0, 0), radius=10, visual=Neon())
        self.assertTrue(c.visual._is_multipass)
        self.assertTrue(_must_solo_draw(c))
        canvas.fx_quality = "medium"
        a = Circle(center=(0, 0), radius=10).set_color("cyan")
        a.visual = Halo()
        self.assertTrue(a.visual._is_multipass)
        self.assertTrue(_must_solo_draw(a))
        activate_quality("high")

    def test_plasmashot_high_uses_gpu_blur(self):
        """Bolt high halo is interned GPU Blur on line_filter, not CPU MaskFilter."""
        from scena import Blur
        from scena.canvas import _has_any_batchable_filter, _must_solo_draw
        from scena.fx_quality import activate_quality
        from scena.style import BlendMode, ProceduralFill

        canvas.fx_quality = "high"
        look = Bolt()
        self.assertFalse(look._is_multipass)
        self.assertIsInstance(look._high._halo_high, Blur)
        self.assertFalse(hasattr(look, "_mask"))
        surf = skia.Surface(64, 64)
        c = Circle(center=(0, 0), radius=10).set_color("cyan")
        c.visual = look
        self.assertIsInstance(c.line_filter, Blur)
        self.assertIs(c.line_filter, look._high._halo_high)
        self.assertIsInstance(c.fill, ProceduralFill)
        self.assertEqual(c.blend, "add")
        self.assertAlmostEqual(float(c.line_width), 4.5, places=1)
        self.assertFalse(_must_solo_draw(c))
        self.assertTrue(_has_any_batchable_filter(c))
        c.draw(surf.getCanvas())
        d = Circle(center=(40, 0), radius=10).set_color("tomato")
        d.visual = look
        self.assertIs(c.line_filter, d.line_filter)
        ln = Line(p1=(0, 0), p2=(40, 0)).set_color("tomato")
        ln.visual = Bolt()
        self.assertIsInstance(ln.line_filter, Blur)
        ln.draw(surf.getCanvas())
        activate_quality("medium")
        c.visual._apply(c)
        self.assertIsNone(c.line_filter)
        self.assertTrue(c.visual._is_multipass)
        self.assertEqual(c.blend, "normal")
        self.assertAlmostEqual(float(c.line_width), 1.5, places=1)
        c.draw(surf.getCanvas())
        activate_quality("high")

    def test_plasmashot_filaments_amount_vs_intensity(self):
        """Filaments: amount drives SkSL spokes; intensity drives halo, not body heat."""
        from scena.fx_quality import activate_quality
        from scena.style import ProceduralFill

        canvas.fx_quality = "high"
        look = Bolt(style="filaments")
        self.assertAlmostEqual(look.intensity, 0.6)
        c = Circle(center=(0, 0), radius=10).set_color("cyan")
        c.visual = look
        self.assertIsInstance(c.fill, ProceduralFill)
        self.assertAlmostEqual(c.fill._amount, 3.0)
        self.assertAlmostEqual(float(c.line_width), 4.5, places=1)

        hot = Bolt(style="filaments", intensity=1.8, amount=3.0)
        d = Circle(center=(20, 0), radius=10).set_color("cyan")
        d.visual = hot
        self.assertAlmostEqual(d.fill._amount, 3.0)
        self.assertGreater(float(d.line_width), float(c.line_width))
        self.assertGreater(hot._high._halo_high._sigma_x, look._high._halo_high._sigma_x)

        dense = Bolt(style="filaments", amount=8.0)
        e = Circle(center=(40, 0), radius=10).set_color("cyan")
        e.visual = dense
        self.assertAlmostEqual(e.fill._amount, 8.0)
        self.assertAlmostEqual(float(e.line_width), float(c.line_width), places=1)
        activate_quality("high")

    def test_metal_chrome_rim_all_qualities(self):
        """Metal uses the Line chrome outline at every quality; no sheen pass."""
        from scena.fx_quality import activate_quality
        from scena.recipes import _METAL_EDGE
        look = Metal()
        self.assertFalse(hasattr(look, "_highlight"))
        surf = skia.Surface(64, 64)
        for q in ("low", "medium", "high"):
            with self.subTest(quality=q):
                activate_quality(q)
                c = Circle(center=(0, 0), radius=10)
                c.visual = look
                self.assertAlmostEqual(float(c.line_width), 1.5, places=1)
                c.draw(surf.getCanvas())
                ln = Line(p1=(0, 0), p2=(40, 0))
                ln.visual = Metal()
                ln.draw(surf.getCanvas())
        self.assertEqual(_METAL_EDGE, (0.75, 0.78, 0.82, 0.95))
        activate_quality("high")

    def test_shield_tint_survives_quality_change(self):
        """bands/vortex keep host tint when fidelity re-applies."""
        from scena.color import Color
        from scena.fx_quality import activate_quality
        canvas.fx_quality = "high"
        for st in ("bands", "vortex"):
            with self.subTest(style=st):
                c = Circle(center=(64, 64), radius=28)
                c.fill = Color("lime")
                c.visual = Shield(style=st)
                rgb0 = tuple(c.fill.color)
                self.assertGreater(rgb0[1], 0.5, f"{st} should start lime-ish")
                activate_quality("medium")
                c.visual._apply(c)  # fidelity_sensitive refresh
                rgb1 = tuple(c.fill.color)
                self.assertGreater(rgb1[1], 0.5, f"{st} lost tint at medium {rgb1}")
                activate_quality("high")
                c.visual._apply(c)
                rgb2 = tuple(c.fill.color)
                self.assertGreater(rgb2[1], 0.5, f"{st} lost tint back at high {rgb2}")
                # Must not snap to vortex magenta default
                self.assertLess(rgb2[0], 0.55, f"{st} looks magenta-reset {rgb2}")
                activate_quality("high")

    def test_aura_tint_survives_quality_change(self):
        """Halo stash keeps host hue across fidelity re-apply (not wash/default)."""
        from scena.fx_quality import activate_quality
        canvas.fx_quality = "high"
        c = Circle(center=(0, 0), radius=12).set_color("lime")
        c.line = Color("lime")
        c.visual = Halo()
        t0 = c.visual._tint_rgba(c)
        self.assertGreater(t0[1], 0.7)
        self.assertLess(t0[0], 0.4)
        activate_quality("medium")
        c._reapply_visual()
        t1 = c.visual._tint_rgba(c)
        self.assertGreater(t1[1], 0.7)
        self.assertLess(t1[0], 0.4)
        activate_quality("high")
        c._reapply_visual()
        t2 = c.visual._tint_rgba(c)
        self.assertGreater(t2[1], 0.7)
        self.assertLess(t2[0], 0.4)
        self.assertTrue(hasattr(c, "_aura_host_tint"))

    def test_aura_fill_and_halo_tint_survives_quality_change(self):
        """Halo(style='fill') pack + Shield(style='plasma') GlowRim stash survive quality re-apply."""
        from scena.fx_quality import activate_quality
        canvas.fx_quality = "high"
        fill = Circle(center=(0, 0), radius=12).set_color("lime")
        fill.visual = Halo(style="fill")
        self.assertGreater(fill.visual._tint_rgba(fill)[1], 0.7)
        activate_quality("medium")
        fill.visual._apply(fill)
        self.assertGreater(fill.visual._tint_rgba(fill)[1], 0.7)
        activate_quality("high")
        fill.visual._apply(fill)
        t = fill.visual._tint_rgba(fill)
        self.assertGreater(t[1], 0.7)
        self.assertLess(t[0], 0.4)
        pack = getattr(fill, "_aura_fill_host", None)
        self.assertIsNotNone(pack)
        self.assertGreater(pack["tint"][1], 0.7)

        halo = Circle(center=(0, 0), radius=12).set_color("lime")
        halo.line = Color("lime")
        halo.visual = Shield(style="plasma")
        self.assertGreater(halo.visual._tint_rgba(halo)[1], 0.7)
        activate_quality("medium")
        halo.visual._apply(halo)
        self.assertGreater(halo.visual._tint_rgba(halo)[1], 0.7)
        activate_quality("high")
        halo.visual._apply(halo)
        ht = halo.visual._tint_rgba(halo)
        self.assertGreater(ht[1], 0.7)
        self.assertLess(ht[0], 0.55)

    def test_no_visual_clears_host_tint_stashes(self):
        from scena.visuals import _HOST_TINT_STASH_ATTRS
        c = Circle(center=(0, 0), radius=12).set_color("lime")
        c.visual = Halo()
        self.assertTrue(hasattr(c, "_aura_host_tint"))
        c.visual = None
        for name in _HOST_TINT_STASH_ATTRS:
            self.assertFalse(hasattr(c, name), name)
        c.visual = Halo(style="fill")
        self.assertTrue(hasattr(c, "_aura_fill_host"))
        c.visual = None
        self.assertFalse(hasattr(c, "_aura_fill_host"))
        self.assertFalse(hasattr(c, "_aura_host_tint"))
        c.visual = Shield(style="plasma")
        self.assertTrue(hasattr(c, "_glowrim_host_tint"))
        c.visual = None
        self.assertFalse(hasattr(c, "_glowrim_host_tint"))

    def test_shield_compiled_not_solo(self):
        from scena.canvas import _must_solo_draw
        canvas.fx_quality = "high"
        a = Circle(center=(0, 0), radius=10, visual=Shield(style="bubble"))
        self.assertFalse(_must_solo_draw(a))
        self.assertFalse(a.visual._is_multipass)
        self.assertIsInstance(a.fill_filter, GlowFilter)
        # Tinted styles: HostGlow at high (shared batch_key across hues).
        for st in ("bands", "vortex"):
            with self.subTest(style=st):
                c = Circle(center=(0, 0), radius=10, visual=Shield(style=st))
                self.assertIsInstance(c.fill_filter, HostGlow)
                d = Circle(center=(0, 0), radius=10).set_color("cyan")
                d.visual = Shield(style=st)
                e = Circle(center=(0, 0), radius=10).set_color("magenta")
                e.visual = Shield(style=st)
                self.assertIs(d.fill_filter, e.fill_filter)
        vortex = Circle(center=(0, 0), radius=10, visual=Shield(style="vortex"))
        bands = Circle(center=(0, 0), radius=10, visual=Shield(style="bands"))
        self.assertLess(float(vortex.fill_filter._sigma), float(bands.fill_filter._sigma))
        self.assertAlmostEqual(float(vortex.visual.speed), 1.0, places=2)
        canvas.fx_quality = "medium"
        # fidelity_sensitive re-apply drops GlowFilter at lite
        a.visual = Shield(style="bubble")
        self.assertIsNone(a.fill_filter)
        canvas.fx_quality = "high"

    def test_lineglow_outline_only(self):
        """Halo(style='line') drops fill; high uses shared HostGlow on the stroke."""
        from scena.canvas import _must_solo_draw
        canvas.fx_quality = "high"
        c = Circle(center=(64, 64), radius=28).set_color("cyan")
        c.visual = Halo(style="line")
        self.assertFalse(bool(c.fill))
        self.assertTrue(bool(c.line))
        self.assertIsInstance(c.line_filter, HostGlow)
        self.assertIsNone(c.fill_filter)
        self.assertFalse(_must_solo_draw(c))
        d = Circle(center=(80, 80), radius=20).set_color("magenta")
        d.visual = Halo(style="line")
        self.assertIs(c.line_filter, d.line_filter)
        surf = skia.Surface(128, 128)
        cnv = surf.getCanvas()
        cnv.clear(skia.ColorBLACK)
        c.draw(cnv)
        px = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
        rim = px[64, 64 + 27] if px.ndim == 3 else px[64][64 + 27]
        self.assertGreater(int(rim[0]) + int(rim[1]) + int(rim[2]), 20)
        canvas.fx_quality = "medium"
        c.visual._apply(c)
        self.assertIsNone(c.line_filter)
        self.assertFalse(bool(c.fill))
        canvas.fx_quality = "high"
        ln = Line(p1=(20, 64), p2=(108, 64)).set_color("lime")
        ln.visual = Halo(style="line")
        cnv.clear(skia.ColorBLACK)
        ln.draw(cnv)

    def test_glow_not_solo_shared_filter(self):
        from scena import Glow, canvas
        from scena.canvas import _must_solo_draw
        canvas.fx_quality = "high"
        a = Circle(center=(0, 0), radius=10)
        a.glow = Glow("cyan")
        b = Circle(center=(0, 0), radius=10)
        b.glow = Glow("cyan")
        self.assertFalse(_must_solo_draw(a))
        self.assertFalse(a.glow._is_multipass)
        self.assertIs(a.fill_filter, b.fill_filter)
        self.assertIs(a.glow, b.glow)

    def test_glow_keeps_host_paint(self):
        canvas.fx_quality = "high"
        a = Circle(center=(0, 0), radius=10).set_color("tomato")
        b = Circle(center=(0, 0), radius=10).set_color("cyan")
        g = Glow(radius=12, sigma=10)
        a.glow = g
        b.glow = g
        self.assertIs(a.glow, b.glow)
        self.assertIs(a.fill_filter, b.fill_filter)
        self.assertIsInstance(a.fill_filter, GlowFilter)
        self.assertAlmostEqual(a.fill.rgb[0], Color("tomato").rgb[0], places=2)
        self.assertAlmostEqual(b.fill.rgb[2], Color("cyan").rgb[2], places=2)
        # Explicit color tints the halo only — host fill stays tomato
        c = Circle(center=(0, 0), radius=10).set_color("tomato")
        c.glow = Glow("gold")
        self.assertIsInstance(c.fill_filter, GlowFilter)
        self.assertAlmostEqual(c.fill.rgb[0], Color("tomato").rgb[0], places=2)
        self.assertIs(Glow(), Glow())
        self.assertIsNot(Glow(), Glow("cyan"))
        # Host stroke width is kept; Lines get the halo on line_filter.
        d = Circle(center=(0, 0), radius=10).set_color("tomato")
        d.line_width = 4.5
        d.glow = Glow()
        self.assertAlmostEqual(float(d.line_width), 4.5, places=2)
        self.assertIsInstance(d.fill_filter, GlowFilter)
        ln = Line(p1=(0, 0), p2=(40, 0)).set_color("cyan")
        ln.line_width = 8.0
        ln.glow = Glow()
        self.assertAlmostEqual(float(ln.line_width), 8.0, places=2)
        self.assertIsNone(ln.fill_filter)
        self.assertIsInstance(ln.line_filter, GlowFilter)
        from scena.fx_quality import activate_quality
        activate_quality("low")
        a._after_stamp_change()
        # Glow keeps batched GlowFilter at low (same RT path as medium/high).
        self.assertFalse(a.glow._is_multipass)
        self.assertIsInstance(a.fill_filter, GlowFilter)
        self.assertAlmostEqual(a.fill.rgb[0], Color("tomato").rgb[0], places=2)
        activate_quality("high")
        a._after_stamp_change()
        self.assertFalse(a.glow._is_multipass)
        self.assertIsInstance(a.fill_filter, GlowFilter)

    def test_cheapglow_filterless_add(self):
        from scena.canvas import _must_solo_draw
        canvas.fx_quality = "high"
        a = Circle(center=(64, 64), radius=20).set_color("cyan")
        b = Circle(center=(64, 64), radius=20).set_color("tomato")
        look = CheapGlow()
        self.assertAlmostEqual(look.radius, 8.0)
        self.assertAlmostEqual(look.sigma, 0.0)
        self.assertAlmostEqual(look.amount, 1.0)
        a.glow = look
        b.glow = look
        self.assertIs(a.glow, b.glow)
        self.assertIsNone(a.fill_filter)
        self.assertIsNone(a.line_filter)
        self.assertFalse(a.glow._is_multipass)
        # Stamp CheapGlow needs full draw (dilated ADD overlay); filter batcher skips it.
        self.assertTrue(_must_solo_draw(a))
        self.assertAlmostEqual(a.fill.rgb[2], Color("cyan").rgb[2], places=2)
        surf = skia.Surface(128, 128)
        cnv = surf.getCanvas()
        cnv.clear(skia.Color4f(0, 0, 0, 1))
        a.draw(cnv)
        px = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
        r, g, bch = px[:, :, 0], px[:, :, 1], px[:, :, 2]
        cyan = (g > 150) & (bch > 150) & (r < 80)
        warm = (r > 25) & (g > 20) & (bch < r) & ~cyan
        self.assertGreater(int(cyan.sum()), 80)
        self.assertGreater(int(warm.sum()), 40)
        # Soft bloom, not a hard ring: tint must leak past the geometric edge.
        # Circle r=20 at (64,64); default pad ~5px, sample ~6px outside.
        yy, xx = 86, 64
        self.assertGreater(int(r[yy, xx]), 8)
        self.assertGreater(int(g[yy, xx]), 6)
        ln = Line(p1=(16, 64), p2=(112, 64)).set_color("lime")
        ln.glow = CheapGlow()
        self.assertIsNone(ln.fill_filter)
        self.assertIsNone(ln.line_filter)

    def test_shadow_keeps_host_paint(self):
        from scena.canvas import _must_solo_draw
        canvas.fx_quality = "high"
        a = Circle(center=(0, 0), radius=10).set_color("tomato")
        b = Circle(center=(0, 0), radius=10).set_color("cyan")
        sh = Shadow(offset=12, sigma=6)
        a.shadow = sh
        b.shadow = sh
        self.assertIs(a.shadow, b.shadow)
        self.assertIs(a.fill_filter, b.fill_filter)
        self.assertIsInstance(a.fill_filter, DropShadow)
        self.assertFalse(_must_solo_draw(a))
        self.assertFalse(a.shadow._is_multipass)
        self.assertAlmostEqual(a.fill.rgb[0], Color("tomato").rgb[0], places=2)
        self.assertAlmostEqual(b.fill.rgb[2], Color("cyan").rgb[2], places=2)
        # color= tints the shadow filter only
        c = Circle(center=(0, 0), radius=10).set_color("tomato")
        c.shadow = Shadow("gold", offset=4)
        self.assertIsInstance(c.fill_filter, DropShadow)
        self.assertAlmostEqual(c.fill.rgb[0], Color("tomato").rgb[0], places=2)
        g = Shadow(offset=12, sigma=6)
        self.assertIs(sh, g)
        self.assertIsNot(sh, Shadow(offset=20, sigma=6))
        from scena.fx_quality import activate_quality
        activate_quality("medium")
        a._after_stamp_change()
        self.assertIsInstance(a.fill_filter, DropShadow)
        activate_quality("low")
        a._after_stamp_change()
        self.assertIsNone(a.fill_filter)
        activate_quality("high")
        a._after_stamp_change()
        self.assertIsInstance(a.fill_filter, DropShadow)

    def test_dropshadow_offset_quality_invariant(self):
        """shape_fx_scale softens sigma, not pull cast closer to the body."""
        import numpy as np

        W, H = 200, 200
        cx, cy = 100, 100
        fx = DropShadow(offset=20, sigma=1.0, color=(0, 0, 0, 1.0))

        def peak_at(scale: float):
            canvas.fx_quality = "high"
            eng = canvas._engine
            eng.shape_fx_scale = float(scale)
            eng.batch_shared_filters = True
            c = Circle(center=(cx, cy), radius=20)
            c.set_color((0.5, 0.5, 0.5, 1)).line = None
            c.fill_filter = fx
            surf = skia.Surface(W, H)
            eng.skia_canvas = surf.getCanvas()
            eng.skia_canvas.clear(skia.Color4f(1, 1, 1, 1))
            eng._composite_filtered_group([c], fx, fills=True)
            img = surf.makeImageSnapshot()
            info = skia.ImageInfo.Make(
                W, H, skia.ColorType.kRGBA_8888_ColorType, skia.AlphaType.kUnpremul_AlphaType,
            )
            buf = bytearray(W * H * 4)
            img.readPixels(info, buf, W * 4, 0, 0)
            dark = 255 - np.frombuffer(buf, dtype=np.uint8).reshape(H, W, 4)[:, :, 0].astype(np.float32)
            yy, xx = np.ogrid[:H, :W]
            body = (xx - cx) ** 2 + (yy - cy) ** 2 <= 22 ** 2
            dm = dark.copy()
            dm[body] = 0
            iy, ix = np.unravel_index(int(dm.argmax()), dm.shape)
            return int(ix), int(iy)

        p_full = peak_at(1.0)
        p_half = peak_at(0.5)
        # Before fix, low RT scaled dx/dy and peak sat ~half the design offset.
        self.assertLessEqual(abs(p_full[0] - p_half[0]), 5)
        self.assertLessEqual(abs(p_full[1] - p_half[1]), 5)

    def test_neon_solo_multipass(self):
        from scena.canvas import _must_solo_draw
        c = Circle(center=(0, 0), radius=10, visual=Neon())
        self.assertTrue(c.visual._is_multipass)
        self.assertTrue(_must_solo_draw(c))

    def test_fire_compiled(self):
        c = Circle(center=(0, 0), radius=10, visual=Flame())
        self.assertFalse(c.visual._is_multipass)
        from scena.style import ProceduralFill
        self.assertIsInstance(c.fill, ProceduralFill)
        self.assertTrue(c.line)
        self.assertAlmostEqual(float(c.line.rgb[0]), 0.0, places=2)
        self.assertAlmostEqual(float(c.line.rgb[3]), 0.5, places=2)
        rim = Circle(center=(0, 0), radius=10, visual=Flame(border=True))
        self.assertTrue(rim.line)
        self.assertAlmostEqual(float(rim.line.rgb[3]), 0.95, places=2)
        ln = Line(p1=(0, 0), p2=(40, 0)).set_color("cyan")
        ln.visual = Flame(border=False)
        self.assertAlmostEqual(float(ln.line.rgb[0]), 1.0, places=2)
        self.assertAlmostEqual(float(ln.line.rgb[1]), 0.88, places=2)
        self.assertIsNot(Flame(border=False), Flame(border=True))

    def test_aura_fill_keeps_opaque_fill(self):
        from scena.style import BlendMode
        canvas.fx_quality = "high"
        c = Circle(center=(0, 0), radius=10).set_color("tomato")
        c.visual = Halo(style="fill")
        self.assertIsInstance(c.fill, Color)
        # Opaque body (not Halo wash ~0.12)
        self.assertGreater(c.fill.rgb[3], 0.9)
        # Light vibrant lift — still near host hue, not Neon-level
        self.assertGreater(c.fill.rgb[0], 0.5)
        self.assertEqual(c.blend, "normal")
        self.assertIsNotNone(c.line_filter)
        # Gradient fill left alone
        g = Gradient("magenta", "cyan", size=40)
        d = Circle(center=(0, 0), radius=10)
        d.fill = g
        d.visual = Halo(style="fill")
        self.assertIs(d.fill, g)
        # Medium: filterless ADD glow + sharp outline (no ImageFilter).
        canvas.fx_quality = "medium"
        e = Circle(center=(0, 0), radius=10).set_color("cyan")
        fill_look = Halo(style="fill")
        e.visual = fill_look
        self.assertTrue(fill_look._is_multipass)
        self.assertIsNone(e.line_filter)
        canvas.fx_quality = "high"

    def test_tail_insetrim_intern(self):
        a = Tail(angle=45, size=1.0)
        b = Tail(angle=45, size=1.0)
        self.assertIs(a, b)
        self.assertIsNot(Tail(angle=90, size=1.0), a)
        omitted = Tail(angle=45)
        self.assertAlmostEqual(omitted.size, 1.2, places=2)
        self.assertIsNot(omitted, a)
        r = InsetRim(fill_scale=0.9)
        self.assertIs(InsetRim(fill_scale=0.9), r)
        self.assertIsNot(InsetRim(fill_scale=0.8), r)
        d = InsetRim()
        self.assertAlmostEqual(d.fill_scale, 0.8, places=3)
        self.assertFalse(hasattr(d, "dual_border"))
        self.assertAlmostEqual(float(d.width), 6.0, places=1)
        self.assertAlmostEqual(d.amount, 0.3, places=2)

    def test_metal_speed_zero_freezes(self):
        """speed=0 stops procedural grain rotation."""
        frozen = Metal(speed=0)
        self.assertAlmostEqual(frozen.speed, 0.0)
        self.assertAlmostEqual(frozen._fill.speed, 0.0)
        self.assertIsNot(frozen, Metal(speed=1.0))

    def test_metal_color_tints_the_metal(self):
        """``Metal("crimson")`` draws red metal; ``Metal()`` stays chrome.

        Bug (2026-10-09, tutorial 28): the tint never reached the shader, so
        ``Metal("gold")`` drew silver though the Guia says ``color`` is the
        metal's color. ``Metal()`` stays chrome on any shape color (every
        published Metal is chrome).
        """
        def mean_rgb(visual, color=None):
            c = Circle(center=(64, 64), radius=40)
            if color is not None:
                c.color = color
            c.visual = visual
            surf = skia.Surface(128, 128)
            cnv = surf.getCanvas()
            cnv.clear(skia.ColorBLACK)
            c.draw(cnv)
            px = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
            c.destroy()
            core = px[44:84, 44:84, :3].reshape(-1, 3).mean(axis=0)
            return [float(v) for v in core]

        r, g, b = mean_rgb(Metal("crimson", speed=0))
        self.assertGreater(r, g + 40, (r, g, b))
        self.assertGreater(r, b + 30, (r, g, b))
        for chrome in (mean_rgb(Metal(speed=0)), mean_rgb(Metal(speed=0), color="crimson")):
            self.assertLess(max(chrome) - min(chrome), 25, chrome)    # gray, whatever the shape
        self.assertIsNot(Metal("gold"), Metal("crimson"))

    def test_metal_color_tints_the_rim(self):
        """``Metal("gold")`` has a gold rim; ``Metal()`` keeps the chrome one.

        Bug (2026-10-13): the tint reached the body but the rim stayed chrome,
        a silver outline around gold metal. On a Line the rim is the whole look.
        """
        from scena.recipes import _METAL_EDGE, _metal_edge

        def line_rgb(visual):
            ln = Line(p1=(10, 32), p2=(54, 32))
            ln.visual = visual
            surf = skia.Surface(64, 64)
            surf.getCanvas().clear(skia.ColorBLACK)
            ln.draw(surf.getCanvas())
            ln.destroy()
            px = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)[..., :3]
            lit = px.reshape(-1, 3)[px.reshape(-1, 3).sum(axis=1) > 60]
            return lit.mean(axis=0)

        r, g, b = line_rgb(Metal("gold"))
        self.assertGreater(r, b + 80, (r, g, b))
        chrome = line_rgb(Metal())
        self.assertLess(max(chrome) - min(chrome), 25, chrome)
        self.assertEqual(_metal_edge(None), _METAL_EDGE)
        # Same hue as the tint, lighter than the tinted body (0.95 x tint).
        import colorsys
        for tint in ((1.0, 0.84, 0.0), (0.86, 0.08, 0.24), (0.12, 0.56, 1.0)):
            edge = _metal_edge(tint)[:3]
            self.assertAlmostEqual(colorsys.rgb_to_hsv(*edge)[0], colorsys.rgb_to_hsv(*tint)[0], delta=0.02)
            self.assertGreater(sum(edge), 0.95 * sum(tint))

    def test_bubble_shield_color_rotates_its_palette(self):
        """``Shield(color, style="bubble")``: the film follows the tint's hue;
        no color is the lime palette, exactly (2026-10-13)."""
        import colorsys
        from scena import recipes
        from scena.recipes import _shift_palette

        pal = Shield._BUBBLE_PALETTE
        for name, rgb in _shift_palette(pal, "lime", pal["lime"]).items():
            for got, want in zip(rgb, pal[name]):
                self.assertAlmostEqual(got, want, places=9)
        c = Circle(center=(64, 64), radius=40)
        c.visual = Shield(style="bubble")
        self.assertEqual(c.fill._extra_rgb, pal)
        c.destroy()
        # A bare ProceduralFill(kind="shield_bubble") (no palette set) keeps
        # the lime film: the shader's colours are uniforms now, never zeros.
        from scena import ProceduralFill
        c = Circle(center=(64, 64), radius=40)
        c.fill = ProceduralFill(kind="shield_bubble")
        surf = skia.Surface(128, 128)
        surf.getCanvas().clear(skia.ColorBLACK)
        c.draw(surf.getCanvas())
        c.destroy()
        px = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)[..., :3]
        r, g, b = px.reshape(-1, 3).astype(float).sum(axis=0)
        self.assertGreater(g, 1.5 * max(r, b), (r, g, b))

        old_clock = recipes._clock
        recipes._clock = lambda: 0.37
        try:
            for tint in ("dodgerblue", "red", "magenta", "gold"):
                with self.subTest(tint=tint):
                    c = Circle(center=(64, 64), radius=40, color="gray")
                    c.visual = Shield(tint, style="bubble")
                    surf = skia.Surface(128, 128)
                    surf.getCanvas().clear(skia.ColorBLACK)
                    c.draw(surf.getCanvas())
                    c.destroy()
                    px = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
                    rgb = px[..., :3].reshape(-1, 3).astype(float)
                    rim = rgb[rgb.sum(axis=1) > 120].mean(axis=0) / 255.0
                    got = colorsys.rgb_to_hsv(*rim)[0]
                    want = colorsys.rgb_to_hsv(*Color(tint).rgb[:3])[0]
                    gap = min(abs(got - want), 1 - abs(got - want))
                    self.assertLess(gap, 0.08, (tint, rim))
        finally:
            recipes._clock = old_clock

    def test_tail_size_scales_span(self):
        """size drives ghost spacing (span = 22 × size)."""
        small = Tail(angle=45, size=0.5)
        large = Tail(angle=45, size=2.0)
        self.assertIsNot(small, large)
        self.assertAlmostEqual(small.size, 0.5)
        self.assertAlmostEqual(large.size, 2.0)
        self.assertIs(Tail(angle=45, size=1.0), Tail(angle=45, size=1.0))

    def test_electricfield_speed_one_intern(self):
        """speed=1.0 matches the old seed_rate=14 intern bucket."""
        self.assertIs(ElectricField(speed=1.0), ElectricField(speed=1.0))
        self.assertIsNot(ElectricField(speed=1.0), ElectricField(speed=2.0))

    def test_pulse_scale_does_not_mutate_geometry(self):
        c = Circle(center=(50, 50), radius=20)
        c.scale = 2.0
        c.set_color("tomato")
        c.line_width = 3.5
        g = Gradient("magenta", "cyan", size=30)
        c.line = g
        r0 = float(c.radius)
        s0 = float(getattr(c, "scale", c._scale))
        fill0 = tuple(c.fill.rgb)
        c.visual = Beat(amount=0.15, speed=2.0)
        surf = skia.Surface(128, 128)
        c.draw(surf.getCanvas())
        self.assertAlmostEqual(float(c.radius), r0, places=5)
        self.assertAlmostEqual(float(getattr(c, "scale", c._scale)), s0, places=5)
        self.assertEqual(tuple(c.fill.rgb), fill0)
        self.assertAlmostEqual(float(c.line_width), 3.5, places=2)
        self.assertIs(c.line, g)
        self.assertIsNone(c.visual._tint_channel)
        self.assertTrue(c.visual._is_multipass)

    def test_tail_keeps_host_style(self):
        c = Circle(center=(50, 50), radius=20).set_color("tomato")
        c.line_width = 4.0
        g = Gradient("gold", "orange", size=24)
        c.line = g
        fill0 = tuple(c.fill.rgb)
        c.tail = Tail(angle=180, size=1.0)
        surf = skia.Surface(128, 128)
        c.draw(surf.getCanvas())
        self.assertEqual(tuple(c.fill.rgb), fill0)
        self.assertAlmostEqual(float(c.line_width), 4.0, places=2)
        self.assertIs(c.line, g)
        self.assertIsNone(c.tail._tint_channel)
        ln = Line(p1=(10, 10), p2=(80, 10)).set_color("cyan")
        ln.line_width = 7.0
        lg = Gradient("magenta", "cyan", size=40)
        ln.set_color(lg)
        ln.tail = Tail(angle=90, size=1.2)
        ln.draw(surf.getCanvas())
        self.assertAlmostEqual(float(ln.line_width), 7.0, places=2)
        self.assertIs(ln.line, lg)

    def test_aura_uses_line_gradient(self):
        canvas.fx_quality = "high"
        g = Gradient("magenta", "cyan", size=40)
        ln = Line(p1=(0, 0), p2=(40, 0))
        ln.set_color(g)
        ln.line_width = 6.0
        ln.visual = Halo()
        tint = ln.visual._tint_rgba(ln)
        mag = Color("magenta").rgb
        self.assertAlmostEqual(tint[0], mag[0], places=2)
        self.assertAlmostEqual(tint[1], mag[1], places=2)
        self.assertIs(ln.line, g)
        c = Circle(center=(0, 0), radius=12).set_color("tomato")
        c.line = g
        c.visual = Halo()
        self.assertIs(c.line, g)

    def test_multiborder_keeps_host_when_color_none(self):
        c = Circle(center=(0, 0), radius=10).set_color("tomato")
        fill0 = tuple(c.fill.rgb)
        line0 = tuple(c.line.rgb)
        c.visual = MultiBorder(layers=2)
        self.assertEqual(tuple(c.fill.rgb), fill0)
        self.assertEqual(tuple(c.line.rgb), line0)

    def test_new_recipes_draw_smoke(self):
        shapes = (
            Circle(center=(64, 64), radius=28),
            Ellipse(center=(64, 64), width=50, height=30, angle=20),
        )
        looks = (
            Beat(amount=0.1),
            InsetRim(fill_scale=0.9),
        )
        for look in looks:
            for shp in shapes:
                shp.visual = look
                surf = skia.Surface(128, 128)
                shp.draw(surf.getCanvas())
        for shp in shapes:
            shp.visual = None
            shp.tail = Tail(angle=180, size=1.2)
            surf = skia.Surface(128, 128)
            shp.draw(surf.getCanvas())
            shp.tail = None

    def test_electric_bolt_quality_cycle_restores_host(self):
        """Medium/high share GlowRim; low ADD line restores host paint."""
        from scena import Blur
        from scena.fx_quality import activate_quality
        from scena.style import BlendMode

        canvas.fx_quality = "high"
        c = Circle(center=(0, 0), radius=12).set_color("tomato")
        c.line_width = 2.0
        host_line = c.line
        c.visual = ElectricBolt()
        self.assertIsInstance(c.line_filter, Blur)
        self.assertAlmostEqual(float(c.line_width), 3.6, places=1)
        self.assertEqual(c.blend, "add")

        activate_quality("medium")
        c._reapply_visual()
        self.assertIsInstance(c.line_filter, Blur)
        self.assertFalse(c.visual._is_multipass)
        self.assertTrue(c.visual._overlay_glow_batch)
        self.assertEqual(c.blend, "add")
        self.assertAlmostEqual(float(c.line_width), 3.6, places=1)
        surf = skia.Surface(64, 64)
        c.draw(surf.getCanvas())

        activate_quality("high")
        c._reapply_visual()
        self.assertIsInstance(c.line_filter, Blur)
        self.assertTrue(c.visual._overlay_glow_batch)
        self.assertEqual(c.blend, "add")
        activate_quality("low")
        c._reapply_visual()
        self.assertIsNone(c.line_filter)
        self.assertTrue(c.visual._is_multipass)
        self.assertFalse(c.visual._overlay_glow_batch)
        self.assertEqual(c.blend, "normal")
        self.assertAlmostEqual(float(c.line_width), 2.0, places=1)
        self.assertIs(c.line, host_line)

        ln = Line(p1=(0, 0), p2=(40, 0)).set_color("cyan")
        ln.line_width = 4.0
        host_ln = ln.line
        activate_quality("high")
        ln.visual = ElectricBolt()
        activate_quality("medium")
        ln._reapply_visual()
        self.assertIsInstance(ln.line_filter, Blur)
        self.assertEqual(ln.blend, "add")
        ln.draw(surf.getCanvas())
        activate_quality("low")
        ln._reapply_visual()
        self.assertIsNone(ln.line_filter)
        self.assertEqual(ln.blend, "normal")
        self.assertAlmostEqual(float(ln.line_width), 4.0, places=1)
        self.assertIs(ln.line, host_ln)
        ln.draw(surf.getCanvas())
        activate_quality("high")

    def test_fx_quality_reapply_keeps_host_tint(self):
        """canvas.fx_quality must re-apply from author identity, not the compiled core.

        ElectricBolt chroma-boosts near-white toward red. Restashing that
        rewritten stroke used to drift the host tint so high never returned
        and low then drew the drifted color too.
        """
        from scena import Blur

        prev = canvas.fx_quality
        surf = skia.Surface(64, 64)

        def _rgba(tint):
            return tuple(round(float(x), 3) for x in tint[:4])

        def _assert_near_white(tint, msg):
            r, g, b, a = _rgba(tint)
            self.assertGreater(r, 0.95, msg)
            self.assertGreater(g, 0.95, msg)
            self.assertGreater(b, 0.95, msg)
            self.assertGreater(a, 0.95, msg)

        try:
            canvas.fx_quality = "high"
            ln = Line(p1=(0, 0), p2=(40, 0)).set_color("white")
            ln.line_width = 2.0
            host = ln.line
            ln.visual = ElectricBolt()
            first_tint = _rgba(ln.visual._tint_rgba(ln))
            _assert_near_white(first_tint, "initial high host tint")
            self.assertIs(ln._look_identity["line"], host)

            for q in ("low", "medium", "high", "low", "medium", "high"):
                canvas.fx_quality = q
                ln.draw(surf.getCanvas())
                self.assertIs(ln._look_identity["line"], host)
                if q == "low":
                    self.assertIsNone(ln.line_filter)
                    self.assertEqual(ln.blend, "normal")
                    self.assertAlmostEqual(float(ln.line_width), 2.0, places=1)
                    self.assertIs(ln.line, host)
                    _assert_near_white(ln.visual._tint_rgba(ln), f"low tint after {q}")
                else:
                    self.assertIsInstance(ln.line_filter, Blur)
                    self.assertEqual(ln.blend, "add")
                    self.assertEqual(_rgba(ln.visual._tint_rgba(ln)), first_tint)
                    _assert_near_white(
                        ln.visual._outline_rgba(ln), f"{q} outline after cycle",
                    )

            # Recolor patches identity; a later quality cycle must track it.
            ln.set_color("cyan")
            cyan = _rgba(ln.visual._tint_rgba(ln))
            self.assertLess(cyan[0], 0.35)
            self.assertGreater(cyan[1], 0.7)
            self.assertGreater(cyan[2], 0.7)
            canvas.fx_quality = "low"
            canvas.fx_quality = "high"
            self.assertEqual(_rgba(ln.visual._tint_rgba(ln)), cyan)

            # Same contract for ElectricField (shared GlowRim rewrite + re-apply).
            canvas.fx_quality = "high"
            ef = Line(p1=(0, 0), p2=(20, 0)).set_color("white")
            ef.line_width = 2.0
            ef_host = ef.line
            ef.visual = ElectricField()
            ef_tint = _rgba(ef.visual._high._tint_rgba(ef))
            _assert_near_white(ef_tint, "field initial host tint")
            canvas.fx_quality = "low"
            canvas.fx_quality = "medium"
            canvas.fx_quality = "high"
            self.assertIs(ef._look_identity["line"], ef_host)
            self.assertEqual(_rgba(ef.visual._high._tint_rgba(ef)), ef_tint)
            self.assertIsInstance(ef.line_filter, Blur)
        finally:
            canvas.fx_quality = prev

    def test_electric_high_glowrim_look(self):
        """ElectricField high: ADD wash + interned Blur GlowRim."""
        from scena import Blur
        from scena.fx_quality import activate_quality
        from scena.style import BlendMode

        canvas.fx_quality = "high"
        shipped = Circle(center=(40, 0), radius=12).set_color("tomato")
        shipped.visual = ElectricBolt()
        self.assertEqual(shipped.blend, "add")

        ef = Circle(center=(80, 0), radius=12).set_color("cyan")
        ef.visual = ElectricField()
        self.assertFalse(ef.visual._is_multipass)
        self.assertIsInstance(ef.line_filter, Blur)
        self.assertEqual(ef.blend, "add")
        amt = float(ef.visual.amount)
        wash = min(1.0, max(0.06, ef.visual._high._HIGH_WASH * max(0.35, amt)))
        self.assertAlmostEqual(float(ef.fill.rgb[3]), wash, places=2)
        self.assertIs(ElectricField(), ElectricField())
        surf = skia.Surface(64, 64)
        shipped.draw(surf.getCanvas())
        ef.draw(surf.getCanvas())
        activate_quality("medium")
        ef.visual._apply(ef)
        self.assertIsInstance(ef.line_filter, Blur)
        activate_quality("low")
        ef.visual._apply(ef)
        self.assertTrue(ef.visual._is_multipass)
        activate_quality("high")

    def test_electric_medium_batched_glow(self):
        """ElectricField medium: tighter interned Blur (no extra overlay saveLayer)."""
        from scena import Blur
        from scena.fx_quality import activate_quality
        from scena.style import BlendMode

        canvas.fx_quality = "medium"
        f = Circle(center=(40, 0), radius=12).set_color("cyan")
        f.visual = ElectricField()
        self.assertFalse(f.visual._is_multipass)
        self.assertIsInstance(f.line_filter, Blur)
        self.assertEqual(f.blend, "add")
        self.assertAlmostEqual(float(ElectricField()._med._HIGH_SIGMA), 2.0, places=1)
        self.assertAlmostEqual(float(ElectricField()._med._HIGH_CORE_A), 0.8, places=2)
        self.assertAlmostEqual(float(f.line_filter._sigma_x), 2.0, places=1)
        amt = float(f.visual.amount)
        wash = min(1.0, max(0.06, f.visual._med._HIGH_WASH * max(0.35, amt)))
        self.assertAlmostEqual(float(f.fill.rgb[3]), wash, places=2)
        surf = skia.Surface(64, 64)
        f.draw(surf.getCanvas())
        activate_quality("high")

    def test_electric_shipped_quality_ladder(self):
        """Field: medium = tighter halo, high = overlay bloom. Bolt: med=high GlowRim."""
        from scena import Blur
        from scena.fx_quality import activate_quality
        from scena.style import BlendMode

        canvas.fx_quality = "high"
        f = Circle(center=(0, 0), radius=12).set_color("cyan")
        f.visual = ElectricField()
        self.assertIsInstance(f.line_filter, Blur)
        self.assertAlmostEqual(float(f.line_filter._sigma_x), float(ElectricField()._high._HIGH_SIGMA), places=1)
        amt = float(f.visual.amount)
        wash = min(1.0, max(0.06, ElectricField()._high._HIGH_WASH * max(0.35, amt)))
        self.assertAlmostEqual(float(f.fill.rgb[3]), wash, places=2)

        b = Circle(center=(40, 0), radius=12).set_color("tomato")
        b.visual = ElectricBolt()
        self.assertEqual(b.blend, "add")
        self.assertTrue(ElectricBolt()._OVERLAY_BLEND_ADD)
        self.assertAlmostEqual(float(ElectricBolt()._HIGH_SIGMA), 5.0, places=1)
        self.assertAlmostEqual(float(b.line_width), 3.6, places=1)

        activate_quality("medium")
        f.visual._apply(f)
        self.assertIsInstance(f.line_filter, Blur)
        self.assertAlmostEqual(float(f.line_filter._sigma_x), float(ElectricField()._med._HIGH_SIGMA), places=1)
        self.assertFalse(f.visual._is_multipass)
        b.visual._apply(b)
        self.assertIsInstance(b.line_filter, Blur)
        self.assertEqual(b.blend, "add")
        self.assertAlmostEqual(float(b.line_width), float(ElectricBolt()._HIGH_WIDTH), places=1)
        self.assertFalse(b.visual._is_multipass)
        self.assertTrue(b.visual._overlay_glow_batch)
        self.assertFalse(f.visual._overlay_glow_batch)

        activate_quality("low")
        f.visual._apply(f)
        self.assertIsNone(f.line_filter)
        self.assertTrue(f.visual._is_multipass)
        b.visual._apply(b)
        self.assertIsNone(b.line_filter)
        self.assertTrue(b.visual._is_multipass)
        self.assertFalse(b.visual._overlay_glow_batch)
        activate_quality("high")

    def test_electric_bolt_overlay_uses_outline_not_fill(self):
        """Bolt overlay mid follows host line (Gradient first stop), not fill."""
        canvas.fx_quality = "high"
        c = Circle(center=(0, 0), radius=12)
        c.fill = Color("cyan")
        c.line = Color("red")
        c.line_width = 3
        c.visual = ElectricBolt()
        mid = c.visual._outline_mid_rgb(c)
        self.assertGreater(mid[0], 0.7)
        self.assertGreater(mid[1], 0.3)

        g = Circle(center=(40, 0), radius=12)
        g.fill = Color("cyan")
        g.line = Gradient("magenta", "blue", type="linear")
        g.line_width = 3
        g.visual = ElectricBolt()
        gm = g.visual._outline_mid_rgb(g)
        self.assertGreater(gm[0] + gm[2], gm[1] * 1.5)
        self.assertLess(gm[1], 0.55)

    def test_costume_standard_outlines(self):
        """Listed costumes install their own outline width (not host)."""
        cases = (
            (DashRing(), 2.0),
            (GearShell(), 2.4),
            (Halo(style="line"), 1.5),
            (Shield(style="plasma"), 1.75),
            (Swell(), 1.5),
            (Flame(), 1.5),
            (Metal(), 1.5),
            (Bolt(), 4.5),  # high halo stroke; lite costume width is 1.5
            (Gel(), 2.0),
            (Wave(), 1.5),
            (Aurora(), 1.5),
            (InsetRim(), 1.8),  # width 6 × amount 0.3
        )
        for look, expected in cases:
            with self.subTest(visual=type(look).__name__):
                c = Circle(center=(0, 0), radius=12).set_color("tomato")
                c.line_width = 9.0
                c.visual = look
                self.assertAlmostEqual(float(c.line_width), expected, places=1)
                ln = Line(p1=(0, 0), p2=(40, 0)).set_color("cyan")
                ln.line_width = 10.0
                ln.visual = look
                self.assertAlmostEqual(float(ln.line_width), expected, places=1)

    def test_shield_draws_on_line(self):
        ln = Line(p1=(20, 64), p2=(108, 64))
        ln.line_width = 2.5
        ln.visual = Shield(style="bubble")
        surf = skia.Surface(128, 128)
        cnv = surf.getCanvas()
        cnv.clear(skia.ColorBLACK)
        ln.draw(cnv)
        px = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
        mid = px[64, 64] if px.ndim == 3 else px[64][64]
        self.assertGreater(int(mid[0]) + int(mid[1]) + int(mid[2]), 10)

    def test_line_fill_none_not_black_primary_tint(self):
        """Line Color(none) fill must not win over cyan stroke for AUTO looks."""
        ln = Line(p1=(0, 0), p2=(40, 0)).set_color("cyan")
        self.assertFalse(bool(ln.fill))
        for look in (Extrude(), Sphere(), Wave(), Aurora(), Bolt(), Gel()):
            with self.subTest(visual=type(look).__name__):
                tint = look._primary_tint(ln)
                self.assertGreater(tint[1] + tint[2], 1.5, tint)
                self.assertLess(tint[0], 0.2, tint)

    def test_tinted_visuals_circle_and_line_not_black(self):
        """Every tinted look draws visible pixels on cyan Circle and Line."""
        looks = []
        for cls in VISUAL_CLASSES:
            look = cls()
            if cls in (Beat, Tail):
                continue
            if getattr(look, "_tint_channel", "keep") is None:
                continue
            looks.append(look)
        looks.extend((
            Shield(style="bands"),
            Shield(style="vortex"),
        ))
        surf = skia.Surface(200, 128)
        cnv = surf.getCanvas()

        def _luma(px, y, x):
            p = px[y, x] if px.ndim == 3 else px[y][x]
            return int(p[0]) + int(p[1]) + int(p[2])

        for look in looks:
            name = type(look).__name__ + str(getattr(look, "style", "") or "")
            with self.subTest(visual=name, geom="line"):
                ln = Line(p1=(20, 64), p2=(180, 64)).set_color("cyan")
                ln.line_width = 4.0
                ln.visual = look
                cnv.clear(skia.ColorBLACK)
                ln.draw(cnv)
                px = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
                luma = _luma(px, 64, 100)
                self.assertGreater(luma, 20, f"line too dark luma={luma}")
            with self.subTest(visual=name, geom="circle"):
                c = Circle(center=(100, 64), radius=36).set_color("cyan")
                c.line_width = 4.0
                c.visual = look
                cnv.clear(skia.ColorBLACK)
                c.draw(cnv)
                px = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
                luma = max(_luma(px, 64, 100), _luma(px, 64, 128), _luma(px, 64, 134))
                self.assertGreater(luma, 20, f"circle too dark luma={luma}")


def _skia_paint_rgba(paint):
    c = paint.getColor4f()
    if hasattr(c, "fR"):
        return (float(c.fR), float(c.fG), float(c.fB), float(c.fA))
    return (float(c.r), float(c.g), float(c.b), float(c.a))


class TestColorReadsTheCurrentPaint(unittest.TestCase):
    """Guia .color (PM5): .color is the colour the shape paints now. A look that
    washes the body (Halo) reads as its wash, not the colour given; a look that
    paints its own material (Flame) has no single colour and reads the colour
    given; a look that paints the given colour (Gel) reads it."""

    def setUp(self):
        from scena import Circle
        self.made = []
        self.Circle = Circle

    def tearDown(self):
        for c in self.made:
            c.destroy()

    def circle(self, look):
        c = self.Circle(center=(0, 0), radius=10, color="tomato")
        self.made.append(c)
        c.visual = look
        return c

    def test_each_kind(self):
        from scena import Flame, Gel, Halo
        tomato = Color("tomato").hsl
        self.assertNotEqual(self.circle(Halo()).color.hsl, tomato)
        self.assertEqual(self.circle(Flame()).color.hsl, tomato)
        self.assertEqual(self.circle(Gel()).color.hsl, tomato)


class TestRecipeStrokePaintHotPath(unittest.TestCase):
    """§3.1: tuple strokes skip Color(); pixels match the old Color4f path."""

    def test_tuple_stroke_does_not_call_color_obj(self):
        look = Laser("tomato")
        calls = {"n": 0}
        import scena.recipes as rec

        orig = rec._color_obj

        def spy(color, default=(0.3, 0.85, 1.0, 1.0)):
            calls["n"] += 1
            return orig(color, default)

        rec._color_obj = spy
        try:
            look._stroke_paint(
                color=(0.95, 0.12, 0.10, 0.28), width=4.0, blend=BlendMode.ADD,
            )
            look._fill_paint_from((0.2, 0.4, 0.8, 0.5), alpha=0.7)
        finally:
            rec._color_obj = orig
        self.assertEqual(calls["n"], 0)

    def test_tuple_stroke_does_not_construct_color(self):
        look = Laser("tomato")
        n = {"n": 0}
        orig = Color.__init__

        def spy(self, *args, **kwargs):
            n["n"] += 1
            return orig(self, *args, **kwargs)

        Color.__init__ = spy
        try:
            look._stroke_paint(
                color=(0.95, 0.12, 0.10, 0.28), width=4.0, blend=BlendMode.ADD,
            )
        finally:
            Color.__init__ = orig
        self.assertEqual(n["n"], 0)

    def test_tuple_rgba_matches_color_object_rgb(self):
        look = Laser("tomato")
        from_tuple = look._stroke_paint(
            color=(0.2, 0.4, 0.8, 0.5), width=3.0, blend=BlendMode.ADD,
        )
        # Color alpha is ignored by resolve_rgba (default 1.0); pass alpha=.
        from_color = look._stroke_paint(
            color=Color(0.2, 0.4, 0.8, 1.0), width=3.0, blend=BlendMode.ADD,
            alpha=0.5,
        )
        tr, tg, tb, ta = _skia_paint_rgba(from_tuple)
        cr, cg, cb, ca = _skia_paint_rgba(from_color)
        self.assertAlmostEqual(tr, cr, places=5)
        self.assertAlmostEqual(tg, cg, places=5)
        self.assertAlmostEqual(tb, cb, places=5)
        self.assertAlmostEqual(ta, ca, places=5)
        self.assertAlmostEqual(ta, 0.5, places=5)

    def test_seed_pulse_uses_set_alpha(self):
        look = Laser("tomato")
        seed = look.color
        pulsed = look._stroke_paint(
            color=(*seed[:3], 0.28), width=4.0, blend=BlendMode.ADD,
        )
        r, g, b, a = _skia_paint_rgba(pulsed)
        self.assertAlmostEqual(r, float(seed[0]), places=5)
        self.assertAlmostEqual(g, float(seed[1]), places=5)
        self.assertAlmostEqual(b, float(seed[2]), places=5)
        self.assertAlmostEqual(a, 0.28, places=5)

    def test_white_core_alpha(self):
        look = Laser("tomato")
        core = look._stroke_paint(
            color=(1.0, 1.0, 1.0, 0.98), width=1.0, blend=BlendMode.ADD,
        )
        r, g, b, a = _skia_paint_rgba(core)
        self.assertAlmostEqual(r, 1.0, places=5)
        self.assertAlmostEqual(g, 1.0, places=5)
        self.assertAlmostEqual(b, 1.0, places=5)
        self.assertAlmostEqual(a, 0.98, places=5)

    def test_ink_neon_tuple_path(self):
        ink = Ink("navy")
        neon = Neon("cyan")
        import scena.recipes as rec

        orig = rec._color_obj

        def boom(color, default=(0.3, 0.85, 1.0, 1.0)):
            raise AssertionError("_color_obj on tuple paint path")

        rec._color_obj = boom
        try:
            ink._stroke_paint(color=ink.color, width=2.0)
            neon._stroke_paint(color=(1.0, 1.0, 1.0, 0.9), width=1.0, blend=BlendMode.ADD)
            neon._fill_paint_from(neon.color)
        finally:
            rec._color_obj = orig


class TestLookPassGrouping(unittest.TestCase):
    """§3.2: consecutive interned stroke Recipes emit pass-major; max escapes."""

    def setUp(self):
        init(width=400, height=300)
        canvas.fx_quality = "high"

    def _engine_surface(self):
        eng = canvas._engine
        surf = skia.Surface(200, 120)
        eng.skia_canvas = surf.getCanvas()
        eng.skia_canvas.clear(skia.Color4f(0, 0, 0, 1))
        return eng, surf

    def test_consecutive_lasers_emit_once(self):
        from scena.canvas import _look_pass_groupable, _must_solo_draw
        look = Laser("tomato")
        lines = []
        for i in range(4):
            ln = Line(p1=(10, 10 + i * 20), p2=(80, 18 + i * 20))
            ln.line_width = 2.5
            ln.visual = look
            lines.append(ln)
        self.assertTrue(look._look_pass_group)
        self.assertTrue(_must_solo_draw(lines[0]))
        self.assertTrue(_look_pass_groupable(lines[0]))
        calls = []
        orig = Laser._emit_look_passes

        def spy(self, shapes, skia_canvas):
            calls.append(len(shapes))
            return orig(self, shapes, skia_canvas)

        Laser._emit_look_passes = spy
        try:
            eng, _surf = self._engine_surface()
            eng.batch_shared_filters = True
            eng._draw_layer_batched(lines)
        finally:
            Laser._emit_look_passes = orig
        self.assertEqual(calls, [4])

    def test_max_quality_does_not_group(self):
        look = Laser("tomato")
        lines = []
        for i in range(3):
            ln = Line(p1=(10, 10 + i * 18), p2=(70, 16 + i * 18))
            ln.line_width = 2.5
            ln.visual = look
            lines.append(ln)
        renders = {"n": 0}
        orig = Laser._render

        def spy(self, shape, skia_canvas):
            renders["n"] += 1
            return orig(self, shape, skia_canvas)

        Laser._render = spy
        try:
            eng, _surf = self._engine_surface()
            eng.batch_shared_filters = False
            eng._draw_layer_batched(lines)
        finally:
            Laser._render = orig
        self.assertEqual(renders["n"], 3)

    def test_different_interns_stay_apart(self):
        a = Laser("red")
        b = Laser("blue")
        self.assertIsNot(a, b)
        calls = []
        orig = Laser._emit_look_passes

        def spy(self, shapes, skia_canvas):
            calls.append((id(self), len(shapes)))
            return orig(self, shapes, skia_canvas)

        Laser._emit_look_passes = spy
        try:
            ln1 = Line(p1=(0, 0), p2=(40, 0))
            ln1.visual = a
            ln2 = Line(p1=(0, 20), p2=(40, 20))
            ln2.visual = a
            ln3 = Line(p1=(0, 40), p2=(40, 40))
            ln3.visual = b
            ln4 = Line(p1=(0, 60), p2=(40, 60))
            ln4.visual = b
            eng, _surf = self._engine_surface()
            eng.batch_shared_filters = True
            eng._draw_layer_batched([ln1, ln2, ln3, ln4])
        finally:
            Laser._emit_look_passes = orig
        self.assertEqual([c[1] for c in calls], [2, 2])
        self.assertNotEqual(calls[0][0], calls[1][0])

    def test_laser_contrails_skip_line_endpoints(self):
        """Two Contrails sharing an interned Laser must not drawLine via p1."""
        import scena.recipes as rec
        from scena import Contrail

        look = Laser("cyan")
        a = Contrail(visual=look, max_points=4)
        b = Contrail(visual=look, max_points=4)
        a.snapshot((0, 0))
        a.snapshot((40, 10))
        b.snapshot((0, 40))
        b.snapshot((40, 50))
        self.assertIsNone(rec._world_stroke_kind(a._stroke))
        self.assertIsNone(rec._world_stroke_kind(b._stroke))
        eng, _surf = self._engine_surface()
        eng.batch_shared_filters = True
        eng._draw_layer_batched([a._stroke, b._stroke])

    def test_neon_ink_groupable(self):
        from scena.canvas import _look_pass_groupable
        c = Circle(center=(40, 40), radius=12, visual=Neon("magenta"))
        self.assertTrue(c.visual._look_pass_group)
        self.assertTrue(_look_pass_groupable(c))
        ink = Circle(center=(80, 40), radius=12)
        ink.set_color("white")
        ink.visual = Ink("black")
        self.assertTrue(ink.visual._look_pass_group)
        self.assertTrue(_look_pass_groupable(ink))

    def test_world_stroke_kind_keeps_circle_fast_path(self):
        """Same-tint Circle+Rect must not share a bucket (would demote drawCircle)."""
        import scena.recipes as rec

        look = Neon("cyan")
        circles = []
        rects = []
        for i in range(3):
            c = Circle(center=(30 + i * 40, 40), radius=12)
            c.line_width = 3.0
            c.visual = look
            circles.append(c)
            r = Rect(center=(30 + i * 40, 90), width=24, height=18)
            r.line_width = 3.0
            r.visual = look
            rects.append(r)
        calls = []
        orig = rec._stroke_group_world

        def spy(shapes, skia_canvas, paint, *, centers=None):
            kinds = {rec._world_stroke_kind(s) or "path" for s in shapes}
            calls.append((frozenset(kinds), len(shapes), centers is not None))
            return orig(shapes, skia_canvas, paint, centers=centers)

        rec._stroke_group_world = spy
        try:
            eng, _surf = self._engine_surface()
            eng.batch_shared_filters = True
            eng._draw_layer_batched(circles + rects)
        finally:
            rec._stroke_group_world = orig
        # Halo / body-or-fill / core — each pass must be kind-pure.
        for kinds, n, _has_centers in calls:
            self.assertEqual(len(kinds), 1, f"mixed kinds in one pass: {kinds}")
        circle_calls = [c for c in calls if "circle" in c[0]]
        path_calls = [c for c in calls if "path" in c[0]]
        self.assertTrue(circle_calls)
        self.assertTrue(path_calls)
        # Circles keep the hoisted-centers fast path on every stroke pass.
        self.assertTrue(all(c[2] for c in circle_calls))
        self.assertTrue(all(c[1] == 3 for c in circle_calls))

    def test_add_overlap_matches_solo(self):
        """Pass-major ADD on overlapping peers matches per-shape render."""
        import numpy as np
        import scena.recipes as rec

        look = Laser("tomato")
        a = Line(p1=(20, 40), p2=(120, 40))
        b = Line(p1=(70, 10), p2=(70, 90))
        a.line_width = b.line_width = 8.0
        a.visual = b.visual = look
        orig_clock = rec._clock
        rec._clock = lambda: 0.25
        try:
            def pixels(grouped: bool):
                eng, surf = self._engine_surface()
                eng.batch_shared_filters = grouped
                eng._draw_layer_batched([a, b])
                img = surf.makeImageSnapshot()
                return np.frombuffer(img.tobytes(), dtype=np.uint8).copy()

            grouped = pixels(True)
            solo = pixels(False)
        finally:
            rec._clock = orig_clock
        self.assertEqual(grouped.tobytes(), solo.tobytes())


class TestGraphicDrawCeremony(unittest.TestCase):
    """§3.3: skip stamp/transient probes when instance slots are unset."""

    def setUp(self):
        init(width=400, height=300)
        canvas.fx_quality = "high"

    def test_plain_draw_skips_stamp_body(self):
        import scena.shapes as sh

        n = {"n": 0}
        orig = sh.draw_body_with_stamps

        def spy(*a, **k):
            n["n"] += 1
            return orig(*a, **k)

        sh.draw_body_with_stamps = spy
        try:
            c = Circle(center=(40, 40), radius=12)
            c.fill = (0.8, 0.8, 0.9, 1.0)
            surf = skia.Surface(80, 80)
            c.draw(surf.getCanvas())
            self.assertEqual(n["n"], 0)
            c.glow = CheapGlow(color="tomato", radius=6)
            c.draw(surf.getCanvas())
            self.assertEqual(n["n"], 1)
        finally:
            sh.draw_body_with_stamps = orig

    def test_active_transient_still_envelopes(self):
        import scena.shapes as sh
        from scena import transients as tx

        c = Circle(center=(40, 40), radius=12)
        c.fill = (1, 1, 1, 1)
        c.flash(duration=1.0)
        self.assertTrue(tx.has_active_transient(c))
        n = {"n": 0}
        orig = sh.draw_with_transients

        def spy(*a, **k):
            n["n"] += 1
            return orig(*a, **k)

        sh.draw_with_transients = spy
        try:
            surf = skia.Surface(80, 80)
            c.draw(surf.getCanvas())
            self.assertEqual(n["n"], 1)
        finally:
            sh.draw_with_transients = orig


class TestOverlayGlowBatch(unittest.TestCase):
    """§3.4: Electric* high PE-glow shares one Plus plate; max escapes."""

    def setUp(self):
        init(width=400, height=300)
        canvas.fx_quality = "high"

    def _engine_surface(self):
        eng = canvas._engine
        surf = skia.Surface(220, 120)
        eng.skia_canvas = surf.getCanvas()
        eng.skia_canvas.clear(skia.Color4f(0, 0, 0, 1))
        return eng, surf

    def test_consecutive_ef_one_plate(self):
        import scena.recipes as rec
        from scena.canvas import ScenaCanvas, _overlay_glow_groupable

        look = ElectricField("yellow")
        circles = []
        for i in range(4):
            c = Circle(center=(40 + i * 48, 40), radius=12)
            c.visual = look
            circles.append(c)
        self.assertTrue(look._overlay_glow_batch)
        self.assertTrue(_overlay_glow_groupable(circles[0]))
        blurs = []
        orig_blur = rec._gpu_blur_stroke

        def blur_spy(*a, **k):
            blurs.append(1)
            return orig_blur(*a, **k)

        plates = []
        orig_plate = ScenaCanvas._draw_overlay_glow_plate

        def plate_spy(self, look_, shapes):
            plates.append(len(shapes))
            return orig_plate(self, look_, shapes)

        rec._gpu_blur_stroke = blur_spy
        ScenaCanvas._draw_overlay_glow_plate = plate_spy
        try:
            eng, _surf = self._engine_surface()
            eng.batch_shared_filters = True
            eng._draw_layer_batched(circles)
        finally:
            rec._gpu_blur_stroke = orig_blur
            ScenaCanvas._draw_overlay_glow_plate = orig_plate
        self.assertEqual(blurs, [])
        self.assertEqual(plates, [4])

    def test_max_quality_uses_per_shape_blur(self):
        import scena.recipes as rec
        from scena.canvas import ScenaCanvas

        look = ElectricField("yellow")
        circles = []
        for i in range(3):
            c = Circle(center=(40 + i * 48, 40), radius=12)
            c.visual = look
            circles.append(c)
        blurs = []
        orig_blur = rec._gpu_blur_stroke

        def blur_spy(*a, **k):
            blurs.append(1)
            return orig_blur(*a, **k)

        plates = []
        orig_plate = ScenaCanvas._draw_overlay_glow_plate

        def plate_spy(self, look_, shapes):
            plates.append(len(shapes))
            return orig_plate(self, look_, shapes)

        rec._gpu_blur_stroke = blur_spy
        ScenaCanvas._draw_overlay_glow_plate = plate_spy
        try:
            eng, _surf = self._engine_surface()
            eng.batch_shared_filters = False
            eng._draw_layer_batched(circles)
        finally:
            rec._gpu_blur_stroke = orig_blur
            ScenaCanvas._draw_overlay_glow_plate = orig_plate
        self.assertEqual(len(blurs), 3)
        self.assertEqual(plates, [])

    def test_medium_does_not_group_overlay_glow(self):
        from scena.fx_quality import activate_quality
        from scena.canvas import _overlay_glow_groupable

        activate_quality("medium")
        try:
            look = ElectricField("yellow")
            c = Circle(center=(40, 40), radius=12)
            c.visual = look
            self.assertFalse(look._overlay_glow_batch)
            self.assertFalse(_overlay_glow_groupable(c))
        finally:
            activate_quality("high")

    def test_electric_bolt_groups(self):
        import scena.recipes as rec
        from scena.canvas import ScenaCanvas
        from scena.fx_quality import activate_quality

        for quality in ("high", "medium"):
            activate_quality(quality)
            look = ElectricBolt()
            circles = []
            for i in range(3):
                c = Circle(center=(40 + i * 48, 40), radius=12).set_color("cyan")
                c.visual = look
                circles.append(c)
            self.assertTrue(look._overlay_glow_batch, quality)
            blurs = []
            orig_blur = rec._gpu_blur_stroke

            def blur_spy(*a, **k):
                blurs.append(1)
                return orig_blur(*a, **k)

            plates = []
            orig_plate = ScenaCanvas._draw_overlay_glow_plate

            def plate_spy(self, look_, shapes):
                plates.append(len(shapes))
                return orig_plate(self, look_, shapes)

            rec._gpu_blur_stroke = blur_spy
            ScenaCanvas._draw_overlay_glow_plate = plate_spy
            try:
                eng, _surf = self._engine_surface()
                eng.batch_shared_filters = True
                eng._draw_layer_batched(circles)
            finally:
                rec._gpu_blur_stroke = orig_blur
                ScenaCanvas._draw_overlay_glow_plate = orig_plate
            self.assertEqual(blurs, [], quality)
            self.assertEqual(plates, [3], quality)
        activate_quality("high")

    def test_separated_ef_matches_solo(self):
        """Shared plate vs per-shape saveLayer — bit-identical when RTs do not overlap."""
        import numpy as np
        import scena.recipes as rec

        look = ElectricField("cyan")
        a = Circle(center=(40, 50), radius=10)
        b = Circle(center=(160, 50), radius=10)
        a.visual = b.visual = look
        orig_clock = rec._clock
        rec._clock = lambda: 0.25
        try:
            def pixels(grouped: bool):
                eng, surf = self._engine_surface()
                eng.batch_shared_filters = grouped
                eng._draw_layer_batched([a, b])
                img = surf.makeImageSnapshot()
                return np.frombuffer(img.tobytes(), dtype=np.uint8).copy()

            grouped = pixels(True)
            solo = pixels(False)
        finally:
            rec._clock = orig_clock
        self.assertEqual(grouped.tobytes(), solo.tobytes())


class TestLookIdentity(unittest.TestCase):
    """no_visual() restores the author package; host-tint color= dyes it."""

    def setUp(self):
        init(width=400, height=300)
        canvas.fx_quality = "high"

    def _rgb(self, paint):
        c = paint if isinstance(paint, Color) else Color(paint)
        return tuple(round(float(x), 3) for x in c.rgb[:3])

    def test_paint_then_no_visual_keeps_package(self):
        c = Circle(center=(0, 0), radius=10, color="coral")
        coral = self._rgb("coral")
        self.assertEqual(self._rgb(c.fill), coral)
        c.visual = None
        self.assertIsNone(c.visual)
        self.assertEqual(self._rgb(c.fill), coral)

    def test_neon_plain_restores_host(self):
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        coral = self._rgb(c.fill)
        c.visual = Neon()
        c.visual = None
        self.assertEqual(self._rgb(c.fill), coral)
        self.assertIsNone(c.fill_filter)
        self.assertIsNone(c.line_filter)

    def test_neon_color_dyes_identity(self):
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        c.visual = Neon("cyan")
        self.assertEqual(self._rgb(c.fill), self._rgb("cyan"))
        c.visual = None
        self.assertEqual(self._rgb(c.fill), self._rgb("cyan"))
        self.assertNotEqual(self._rgb(c.fill), self._rgb("coral"))

    def test_glow_accent_does_not_dye(self):
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        coral = self._rgb(c.fill)
        c.glow = Glow("gold")
        self.assertEqual(self._rgb(c.fill), coral)
        self.assertIsInstance(c.fill_filter, GlowFilter)
        c.visual = None
        self.assertEqual(self._rgb(c.fill), coral)
        self.assertIsInstance(c.glow, Glow)
        self.assertIsInstance(c.fill_filter, GlowFilter)

    def test_shadow_accent_does_not_dye(self):
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        coral = self._rgb(c.fill)
        c.shadow = Shadow("navy")
        self.assertEqual(self._rgb(c.fill), coral)
        c.visual = None
        self.assertEqual(self._rgb(c.fill), coral)
        self.assertIsInstance(c.shadow, Shadow)
        self.assertIsInstance(c.fill_filter, DropShadow)

    def test_fire_restores_host_not_firefill(self):
        from scena.style import ProceduralFill
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        coral = self._rgb(c.fill)
        c.visual = Flame()
        self.assertIsInstance(c.fill, ProceduralFill)
        self.assertEqual(getattr(c.fill, "kind", None), "fire")
        c.visual = None
        self.assertEqual(self._rgb(c.fill), coral)
        self.assertNotIsInstance(c.fill, ProceduralFill)

    def test_aura_seed_not_wash(self):
        """The seed of an outline look dyes the outline only, never the wash
        (2026-10-13: before, it dyed the body too)."""
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        c.line_width = 2.0
        c.visual = Halo("cyan")
        self.assertLess(float(c.fill.rgb[3]), 0.35)
        c.visual = None
        self.assertEqual(self._rgb(c.fill), self._rgb("coral"))
        self.assertGreater(float(c.fill.rgb[3]), 0.9)
        self.assertEqual(self._rgb(c.line), self._rgb("cyan"))
        self.assertAlmostEqual(float(c.line_width), 2.0, places=2)

    def test_replace_costume_keeps_original_identity(self):
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        coral = self._rgb(c.fill)
        c.visual = Halo()
        c.visual = Flame()
        c.visual = None
        self.assertEqual(self._rgb(c.fill), coral)

    def test_author_fill_edit_before_costume_swap(self):
        """fill/line edits after color= must survive swapping to another visual."""
        from scena.style import Gradient

        c = Circle(center=(0, 0), radius=10, color="forest green")
        grad = Gradient("blue")
        c.fill = grad
        c.line = Color("red")
        c.visual = Halo(style="fill")
        self.assertIs(c.fill, grad)

    def test_replace_add_costume_does_not_poison_host_preserving(self):
        """Halo / Bolt leave ADD + wash; Tail / Beat must see host."""
        from scena.style import BlendMode

        coral = self._rgb("coral")
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        c.line_width = 2.0
        c.visual = Halo()
        self.assertEqual(c.blend, "add")
        self.assertLess(float(c.fill.rgb[3]), 0.35)
        c.visual = None
        c.tail = Tail()
        self.assertEqual(self._rgb(c.fill), coral)
        self.assertGreater(float(c.fill.rgb[3]), 0.9)
        self.assertEqual(c.blend, "normal")
        self.assertAlmostEqual(float(c.line_width), 2.0, places=2)

        d = Circle(center=(0, 0), radius=10).set_color("tomato")
        tomato = self._rgb(d.fill)
        d.visual = Bolt()
        d.visual = Beat()
        self.assertEqual(self._rgb(d.fill), tomato)
        self.assertEqual(d.blend, "normal")

    def test_look_like_copies_identity(self):
        a = Circle(center=(0, 0), radius=10).set_color("coral")
        coral = self._rgb(a.fill)
        a.visual = Neon()
        b = Circle(center=(20, 0), radius=10)
        b.look_like(a)
        self.assertIs(b.visual, a.visual)
        b.visual = None
        self.assertEqual(self._rgb(b.fill), coral)

    def test_laser_seeds_line(self):
        ln = Line(p1=(0, 0), p2=(40, 0)).set_color("coral")
        ln.visual = Laser("lime")
        self.assertEqual(self._rgb(ln.line), self._rgb("lime"))
        ln.visual = None
        self.assertEqual(self._rgb(ln.line), self._rgb("lime"))

    def test_no_visual_without_costume_is_noop(self):
        c = Circle(center=(0, 0), radius=10)
        c.set_color("coral")
        coral = self._rgb(c.fill)
        c.visual = None
        self.assertEqual(self._rgb(c.fill), coral)

    def test_halo_red_dyes_identity(self):
        """Halo("red") leaves what line = "red" then Halo() leaves: a red
        outline on the coral body (2026-10-13; before, a red body)."""
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        c.visual = Halo("red")
        c.visual = None
        self.assertEqual(self._rgb(c.line), self._rgb("red"))
        self.assertEqual(self._rgb(c.fill), self._rgb("coral"))

    def test_halo_plain_restores_host(self):
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        coral = self._rgb(c.fill)
        c.visual = Halo()
        c.visual = None
        self.assertEqual(self._rgb(c.fill), coral)

    def test_outline_only_halo_red_stays_ring(self):
        c = Circle(center=(0, 0), radius=10)
        c.fill = None
        c.line = Color("coral")
        c.visual = Halo("red")
        c.visual = None
        self.assertFalse(bool(c.fill))
        self.assertEqual(self._rgb(c.line), self._rgb("red"))

    def test_replace_a_then_b_keeps_unseeded_identity(self):
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        coral = self._rgb(c.fill)
        c.visual = Neon()
        c.visual = Halo()
        c.visual = None
        self.assertEqual(self._rgb(c.fill), coral)

    def test_gradient_visual_then_none_keeps_gradient_package(self):
        from scena.style import Gradient
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        grad = Gradient("red", "yellow")
        c.visual = grad
        self.assertIsInstance(c.visual, Paint)
        self.assertIs(c.fill, grad)
        self.assertTrue(bool(c.line))
        rim = grad.mean_color().darker(0.2)
        self.assertAlmostEqual(c.line.rgb[0], rim.rgb[0], places=4)
        c.visual = None
        self.assertIs(c.fill, grad)
        self.assertTrue(bool(c.line))
        self.assertAlmostEqual(c.line.rgb[0], rim.rgb[0], places=4)


class TestSeededVisualRecolorBaseline(unittest.TestCase):
    """Identity/tint rules for seeded looks, plus Phase 1 live recolor.

    Rules: Effect System Design §9, rule 18.
    """

    def setUp(self):
        init(width=400, height=300)
        canvas.fx_quality = "high"

    def _rgb(self, paint):
        c = paint if isinstance(paint, Color) else Color(paint)
        return tuple(round(float(x), 3) for x in c.rgb[:3])

    def _tint_rgb(self, tint):
        return tuple(round(float(x), 3) for x in tint[:3])

    def test_water_ignores_shape_color(self):
        """Rule 1: Water's tint_channel is None — shape.color must not leak in."""
        s = Circle(center=(64, 64), radius=28).set_color("cyan")
        s.visual = Water()
        self.assertIsNone(s.visual._tint_channel)
        water_fill = s.visual._fill
        s.color = "red"
        self.assertIs(s.visual._fill, water_fill)
        self.assertIs(s.visual, Water())
        surf = skia.Surface(128, 128)
        cnv = surf.getCanvas()
        cnv.clear(skia.ColorBLACK)
        s.draw(cnv)
        px = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
        r, g, b = int(px[64, 64, 0]), int(px[64, 64, 1]), int(px[64, 64, 2])
        self.assertGreater(r + g + b, 10)
        self.assertGreater(b, r)

    def test_seeded_neon_removed_without_recolor_keeps_seed(self):
        """Rule 2: Neon('cyan') dyes identity even with no intervening set_color."""
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        c.visual = Neon("cyan")
        self.assertEqual(self._rgb(c.fill), self._rgb("cyan"))
        c.visual = None
        self.assertEqual(self._rgb(c.fill), self._rgb("cyan"))
        self.assertNotEqual(self._rgb(c.fill), self._rgb("coral"))

    def test_set_color_retints_seeded_neon(self):
        c = Circle(center=(0, 0), radius=10)
        c.visual = Neon("red")
        c.color = "green"
        self.assertEqual(self._rgb(c.fill), self._rgb("green"))
        self.assertIsInstance(c.visual, Neon)
        self.assertIsNone(c.visual._seed_color)

    def test_set_color_retints_seeded_halo(self):
        c = Circle(center=(0, 0), radius=10)
        c.visual = Halo("blue")
        c.set_color("red")
        tint = c.visual._tint_rgba(c)
        self.assertEqual(self._tint_rgb(tint), self._rgb(Color("red").contrast_tone(intensity=0.2)))
        self.assertIsNone(c.visual._seed)
        c.visual = None
        self.assertEqual(self._rgb(c.fill), self._rgb("red"))

    def test_set_color_retints_seeded_halo_fill(self):
        c = Circle(center=(0, 0), radius=10)
        c.visual = Halo("blue", style="fill")
        c.color = "red"
        tint = c.visual._tint_rgba(c)
        self.assertEqual(self._tint_rgb(tint), self._rgb("red"))
        self.assertIsNone(c.visual._seed)

    def test_set_color_retints_seeded_halo_soft(self):
        c = Circle(center=(0, 0), radius=10)
        c.visual = Halo("blue", style="soft")
        c.color = "red"
        tint = c.visual._tint_rgba(c)
        # Outline look: follows the outline color="red" derives (2026-10-13).
        self.assertEqual(self._tint_rgb(tint), self._rgb(Color("red").contrast_tone(intensity=0.2)))
        self.assertIsNone(c.visual._seed)

    def test_visual_none_after_live_recolor_keeps_new_color(self):
        """Once de-seeded by an explicit recolor, removing the visual restores the
        NEW color (identity was patched at recolor time), not the original seed."""
        c = Circle(center=(0, 0), radius=10)
        c.visual = Neon("red")
        c.color = "green"
        c.visual = None
        self.assertEqual(self._rgb(c.fill), self._rgb("green"))

    def test_second_recolor_on_deseeded_visual_reuses_same_instance(self):
        c = Circle(center=(0, 0), radius=10)
        c.visual = Neon("red")
        c.color = "green"
        v1 = c.visual
        c.color = "yellow"
        self.assertIs(c.visual, v1)

    def test_recolor_batches_by_new_shared_color(self):
        """Two shapes recolored from different seeds to the SAME new color must
        end up sharing one interned look instance (Family B pass-major batching
        keys off `.visual is`)."""
        a = Circle(center=(0, 0), radius=10)
        a.visual = Neon("red")
        b = Circle(center=(20, 0), radius=10)
        b.visual = Neon("blue")
        a.color = "lime"
        b.color = "lime"
        self.assertIs(a.visual, b.visual)

    def test_halo_filter_object_stable_across_recolor(self):
        """Family A batches by filter batch_key (colorblind). Recolor must not change kind/params."""
        s = Circle(center=(0, 0), radius=10)
        s.visual = Halo("red")
        before = s.line_filter
        self.assertIsNotNone(before)
        before_key = before._batch_key
        before_cls = type(before)
        s.color = "green"
        after = s.line_filter
        self.assertIsNotNone(after)
        self.assertIs(type(after), before_cls)
        self.assertEqual(after._batch_key, before_key)
        self.assertIs(after, before)

    def test_continuous_recolor_does_not_grow_recipe_cache(self):
        from scena.recipes import _RECIPE_CACHE
        s = Circle(center=(0, 0), radius=10)
        s.visual = Neon("red")
        before = len(_RECIPE_CACHE)
        for i in range(500):
            s.color = (i / 500.0, 0.2, 0.8)
        after = len(_RECIPE_CACHE)
        self.assertLess(after - before, 5)

    def test_unseed_preserves_neon_amount_width(self):
        c = Circle(center=(0, 0), radius=10)
        c.visual = Neon("red", amount=2.0, width=20)
        c.color = "green"
        self.assertAlmostEqual(c.visual.amount, 2.0)
        self.assertAlmostEqual(c.visual.width, 20.0)
        self.assertIs(c.visual, Neon(None, 2.0, 20))

    def test_haloline_recolor_shows(self):
        """Phase 2 (2026-10-13): HaloLine stores ``_seed_color`` (not ``_seed``)
        and de-seeds like Halo; before, the blue seed won over set_color."""
        c = Circle(center=(0, 0), radius=10)
        c.visual = Halo("blue", style="line")
        c.color = "red"
        # color= "red" derives the outline; the outline look follows it.
        self.assertEqual(self._rgb(c.line), self._rgb(Color("red").contrast_tone(intensity=0.2)))
        self.assertIs(c.visual, Halo(style="line"))

    def test_phase2_recolor_shares_one_instance(self):
        """Every role-A/B look de-seeds to one interned sibling per knob set:
        shapes recolored from different seeds keep batching together
        (look-pass groups key ``.visual is``), and a recolor loop interns
        nothing new."""
        from scena import Laser, Rim
        from scena.recipes import _RECIPE_CACHE
        for make in (lambda c: Laser(c), lambda c: Rim(c, width=6.0)):
            a = Circle(center=(0, 0), radius=10)
            a.visual = make("red")
            b = Circle(center=(20, 0), radius=10)
            b.visual = make("blue")
            a.color = "lime"
            b.color = "lime"
            self.assertIs(a.visual, b.visual)
            self.assertIs(a.visual, make(None))
            before = len(_RECIPE_CACHE)
            for i in range(200):
                a.color = (i / 200.0, 0.2, 0.8)
            self.assertEqual(len(_RECIPE_CACHE), before)


class TestSaveVisual(unittest.TestCase):
    """save_visual / restore_visual one-slot appearance checkpoint."""

    def setUp(self):
        init(width=400, height=300)
        canvas.fx_quality = "high"

    def _rgb(self, paint):
        c = paint if isinstance(paint, Color) else Color(paint)
        return tuple(round(float(x), 3) for x in c.rgb[:3])

    def test_restore_neon_not_identity(self):
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        coral = self._rgb(c.fill)
        neon = Neon()
        c.visual = neon
        c.save_visual()
        c.glow = Glow("gold")
        c.restore_visual()
        self.assertIs(c.visual, neon)
        self.assertEqual(self._rgb(c.fill), coral)

    def test_visual_none_is_identity_not_save_restore(self):
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        coral = self._rgb(c.fill)
        neon = Neon()
        c.visual = neon
        c.save_visual()
        c.glow = Glow("gold")
        c.visual = None
        self.assertIsNone(c.visual)
        self.assertEqual(self._rgb(c.fill), coral)
        self.assertIsNot(c.visual, neon)

    def test_second_save_is_noop_two_star(self):
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        neon = Neon()
        c.visual = neon
        c.save_visual()
        c.glow = Glow("gold")
        c.save_visual()
        c.visual = Shield(style="bubble")
        c.restore_visual()
        self.assertIs(c.visual, neon)

    def test_empty_restore_is_noop(self):
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        c.glow = Glow()
        g = c.glow
        c.restore_visual()
        self.assertIs(c.glow, g)
        self.assertIsNone(c.visual)

    def test_save_after_restore(self):
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        c.save_visual()
        c.glow = Glow()
        c.restore_visual()
        c.save_visual()
        c.visual = Halo()
        c.restore_visual()
        self.assertIsNone(c.visual)
        self.assertEqual(self._rgb(c.fill), self._rgb("coral"))

    def test_no_costume_set_color_rewound(self):
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        coral = self._rgb(c.fill)
        c.save_visual()
        c.set_color("lime")
        c.restore_visual()
        self.assertEqual(self._rgb(c.fill), coral)
        self.assertIsNone(c.visual)

    def test_halo_live_package_survives_restore(self):
        from scena.style import BlendMode

        c = Circle(center=(0, 0), radius=10).set_color("coral")
        c.visual = Halo()
        self.assertEqual(c.blend, "add")
        wash_alpha = float(c.fill.rgb[3])
        c.save_visual()
        c.glow = Glow("gold")
        c.restore_visual()
        self.assertEqual(c.blend, "add")
        self.assertAlmostEqual(float(c.fill.rgb[3]), wash_alpha, places=3)

    def test_returns_self(self):
        c = Circle(center=(0, 0), radius=10)
        self.assertIs(c.save_visual(), c)
        self.assertIs(c.restore_visual(), c)

    def test_clone_does_not_copy_slot(self):
        a = Circle(center=(0, 0), radius=10).set_color("coral")
        neon = Neon()
        a.visual = neon
        a.save_visual()
        b = a.clone()
        self.addCleanup(b.destroy)
        self.assertIsNone(getattr(b, "_saved_visual", None))
        halo = Halo()
        a.visual = halo
        b.restore_visual()
        self.assertIs(a.visual, halo)
        a.restore_visual()
        self.assertIs(a.visual, neon)

    def test_look_like_does_not_copy_slot(self):
        a = Circle(center=(0, 0), radius=10).set_color("coral")
        a.visual = Neon()
        a.save_visual()
        b = Circle(center=(20, 0), radius=10)
        b.look_like(a)
        self.assertIsNone(getattr(b, "_saved_visual", None))


class TestVisualCoercion(unittest.TestCase):
    def setUp(self):
        init(width=400, height=300)

    def test_visual_gradient_coerces_to_paint(self):
        from scena.style import Gradient
        c = Circle(center=(0, 0), radius=10)
        g = Gradient("red", "yellow")
        c.visual = g
        self.assertIsInstance(c.visual, Paint)
        self.assertIs(c.fill, g)
        self.assertTrue(bool(c.line))
        rim = g.mean_color().darker(0.2)
        self.assertAlmostEqual(c.line.rgb[0], rim.rgb[0], places=4)
        self.assertAlmostEqual(float(c.line_width), 1.5, places=4)

    def test_visual_texture_coerces_to_paint(self):
        info = skia.ImageInfo.Make(8, 8, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        surf.getCanvas().clear(skia.ColorSetARGB(255, 255, 0, 0))
        tex = Texture(image=surf.makeImageSnapshot())
        c = Circle(center=(0, 0), radius=10)
        c.visual = tex
        self.assertIsInstance(c.visual, Paint)
        self.assertIs(c.fill, tex)
        self.assertFalse(bool(c.line))

    def test_visual_color_string_coerces_to_paint(self):
        c = Circle(center=(0, 0), radius=10)
        c.visual = "tomato"
        self.assertIsInstance(c.visual, Paint)
        self.assertAlmostEqual(c.fill.rgb[0], Color("tomato").rgb[0], places=2)

    def test_visual_wavefill_becomes_wave(self):
        c = Circle(center=(0, 0), radius=10)
        c.visual = WaveFill("magenta")
        self.assertIsInstance(c.visual, Wave)

    def test_visual_unknown_raises(self):
        c = Circle(center=(0, 0), radius=10)
        with self.assertRaises(TypeError):
            c.visual = 1


class TestSetColorLook(unittest.TestCase):
    def setUp(self):
        init(width=400, height=300)

    def _rgb(self, paint):
        c = paint if isinstance(paint, Color) else Color(paint)
        return tuple(round(float(x), 3) for x in c.rgb[:3])

    def test_solid_area_fill_plus_contrast(self):
        c = Circle(center=(0, 0), radius=10).set_color("tomato")
        self.assertEqual(self._rgb(c.fill), self._rgb("tomato"))
        self.assertTrue(bool(c.line))
        self.assertNotEqual(self._rgb(c.fill), self._rgb(c.line))

    def test_outline_only_recolors_line(self):
        c = Circle(center=(0, 0), radius=10)
        c.fill = None
        c.line = Color("coral")
        c.set_color("lime")
        self.assertFalse(bool(c.fill))
        self.assertEqual(self._rgb(c.line), self._rgb("lime"))

    def test_gradient_replaced_by_solid(self):
        from scena.style import Gradient
        c = Circle(center=(0, 0), radius=10)
        g = Gradient("red", "yellow")
        c.set_color(g)
        self.assertIsInstance(c.fill, Gradient)
        self.assertTrue(bool(c.line))
        rim = g.mean_color().darker(0.2)
        self.assertAlmostEqual(c.line.rgb[0], rim.rgb[0], places=4)
        c.set_color("lime")
        self.assertIsInstance(c.fill, Color)
        self.assertEqual(self._rgb(c.fill), self._rgb("lime"))
        self.assertTrue(bool(c.line))
        self.assertNotEqual(self._rgb(c.fill), self._rgb(c.line))

    def test_texture_replaced_by_solid(self):
        info = skia.ImageInfo.Make(8, 8, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        surf.getCanvas().clear(skia.ColorSetARGB(255, 0, 255, 0))
        tex = Texture(image=surf.makeImageSnapshot())
        c = Circle(center=(0, 0), radius=10)
        c.set_color(tex)
        self.assertIs(c.fill, tex)
        c.set_color("tomato")
        self.assertIsInstance(c.fill, Color)
        self.assertEqual(self._rgb(c.fill), self._rgb("tomato"))

    def test_stroke_type_line_only(self):
        ln = Line(p1=(0, 0), p2=(10, 0)).set_color("cyan")
        self.assertFalse(bool(ln.fill))
        self.assertEqual(self._rgb(ln.line), self._rgb("cyan"))

    def test_set_color_while_neon_active(self):
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        c.visual = Neon()
        c.set_color("lime")
        self.assertEqual(self._rgb(c.fill), self._rgb("lime"))
        c.visual = None
        self.assertEqual(self._rgb(c.fill), self._rgb("lime"))

    def test_set_color_while_halo_active(self):
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        c.line = Color("red")
        c.visual = Halo()
        c.set_color("lime")
        tint = c.visual._tint_rgba(c)
        want = Color("lime").contrast_tone(intensity=0.2).rgb
        self.assertEqual(tuple(round(v, 3) for v in tint[:3]), tuple(round(v, 3) for v in want[:3]))
        c.visual = None
        self.assertEqual(self._rgb(c.fill), self._rgb("lime"))

    def test_set_color_while_glow_does_not_change_pigment(self):
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        c.glow = Glow("gold")
        gold = tuple(round(float(x), 3) for x in c.fill_filter._color[:3])
        c.set_color("navy")
        self.assertEqual(self._rgb(c.fill), self._rgb("navy"))
        self.assertEqual(
            tuple(round(float(x), 3) for x in c.fill_filter._color[:3]),
            gold,
        )

    def test_set_color_while_flame_dyes_identity(self):
        from scena.style import ProceduralFill
        c = Circle(center=(0, 0), radius=10).set_color("coral")
        c.visual = Flame()
        self.assertIsInstance(c.fill, ProceduralFill)
        c.set_color("lime")
        self.assertIsInstance(c.fill, ProceduralFill)
        c.visual = None
        self.assertEqual(self._rgb(c.fill), self._rgb("lime"))

    def test_set_color_after_color_kwarg(self):
        """color= writes the package; set_color must not be rewound by Paint."""
        c = Circle(center=(0, 0), radius=10, color="coral")
        self.assertIsNone(c.visual)
        c.set_color("lime")
        self.assertEqual(self._rgb(c.fill), self._rgb("lime"))
        self.assertIsNone(c.visual)

    def test_color_property_recolors(self):
        c = Circle(center=(0, 0), radius=10, color="coral")
        c.color = "lime"
        self.assertEqual(self._rgb(c.fill), self._rgb("lime"))
        self.assertEqual(self._rgb(c.color), self._rgb("lime"))

    def test_set_color_after_visual_color_string(self):
        """visual='tomato' installs Paint; set_color must replace the installer."""
        c = Circle(center=(0, 0), radius=10)
        c.visual = "tomato"
        self.assertIsInstance(c.visual, Paint)
        c.set_color("lime")
        self.assertEqual(self._rgb(c.fill), self._rgb("lime"))
        self.assertIsInstance(c.visual, Paint)
        c.visual = None
        self.assertEqual(self._rgb(c.fill), self._rgb("lime"))


class TestHaloTintRoles(unittest.TestCase):
    def setUp(self):
        init(width=400, height=300)
        canvas.fx_quality = "high"

    def test_halo_pulse_knobs_raise_off_pulse(self):
        # KN3: line leaked Python's "HaloLine.__init__() got an unexpected
        # keyword argument 'rings'"; KN4: hollow / fill / soft took them and
        # drew nothing different. The defaults still pass.
        for style in ("hollow", "fill", "soft", "line"):
            for kw in ({"rings": 5}, {"speed": 2.0}):
                with self.subTest(style=style, **kw), self.assertRaises(TypeError) as cm:
                    Halo(style=style, **kw)
                self.assertNotIn("__init__()", str(cm.exception))
                self.assertIn('style="pulse"', str(cm.exception))
            self.assertIs(Halo(style=style, rings=3, speed=1.0), Halo(style=style))
        self.assertIsNotNone(Halo(style="pulse", rings=5, speed=2.0))

    def test_shield_color_raises_on_fixed_hue_styles(self):
        # KN4: a fixed-hue Shield took color= and drew its own palette.
        # bubble takes it since 2026-10-13 (palette look, like Metal).
        for style in ("nebula", "ember", "void", "molten", "cracks", "frost"):
            with self.subTest(style=style), self.assertRaises(TypeError) as cm:
                Shield("crimson", style=style)
            self.assertIn('style="bubble"', str(cm.exception))
            self.assertIsNotNone(Shield(style=style))
        for style in ("bubble", "bands", "vortex", "plasma"):
            self.assertIsNotNone(Shield("crimson", style=style))

    def test_bolt_amount_raises_on_core(self):
        # KN4: amount is filament density; core drew the same for any amount.
        with self.assertRaises(TypeError) as cm:
            Bolt(amount=6)
        self.assertIn('style="filaments"', str(cm.exception))
        self.assertIsNotNone(Bolt(amount=3.0))
        for style in ("filaments", "tesla"):
            self.assertIsNotNone(Bolt(style=style, amount=6))

    def test_halo_hollow_binds_outline(self):
        c = Circle(center=(0, 0), radius=12)
        c.fill = Color("blue")
        c.line = Color("red")
        c.visual = Halo()
        tint = c.visual._tint_rgba(c)
        self.assertGreater(tint[0], 0.7)
        self.assertLess(tint[2], 0.4)

    def test_halo_fill_binds_body(self):
        c = Circle(center=(0, 0), radius=12)
        c.fill = Color("blue")
        c.line = Color("red")
        c.visual = Halo(style="fill")
        tint = c.visual._tint_rgba(c)
        self.assertGreater(tint[2], 0.7)
        self.assertLess(tint[0], 0.4)


class TestVisualDrawCoverage(unittest.TestCase):
    def setUp(self):
        init(width=400, height=300)
        canvas.fx_quality = "high"

    def _center_rgb(self, shape, size=128):
        surf = skia.Surface(size, size)
        cnv = surf.getCanvas()
        cnv.clear(skia.ColorBLACK)
        shape.draw(cnv)
        px = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
        mid = size // 2
        p = px[mid, mid] if px.ndim == 3 else px[mid][mid]
        return int(p[0]), int(p[1]), int(p[2])

    def test_gradient_visual_covers_and_keeps_darker_outline(self):
        from scena.style import Gradient
        c = Circle(center=(64, 64), radius=40)
        g = Gradient("red", "yellow")
        c.visual = g
        self.assertTrue(bool(c.line))
        expected = g.mean_color().darker(0.2)
        self.assertAlmostEqual(float(c.line.rgb[0]), expected.rgb[0], places=4)
        self.assertAlmostEqual(float(c.line.rgb[1]), expected.rgb[1], places=4)
        self.assertAlmostEqual(float(c.line.rgb[2]), expected.rgb[2], places=4)
        self.assertAlmostEqual(float(c.line_width), 1.5, places=4)
        r, gch, b = self._center_rgb(c)
        self.assertGreater(r + gch + b, 30)

    def test_texture_visual_covers(self):
        info = skia.ImageInfo.Make(16, 16, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        surf.getCanvas().clear(skia.ColorSetARGB(255, 0, 200, 40))
        tex = Texture(image=surf.makeImageSnapshot())
        c = Circle(center=(64, 64), radius=40)
        c.visual = tex
        r, g, b = self._center_rgb(c)
        self.assertGreater(r + g + b, 30)

    def test_halo_fill_keeps_opaque_center(self):
        c = Circle(center=(64, 64), radius=40)
        c.fill = Color("blue")
        c.line = Color("red")
        c.visual = Halo(style="fill")
        r, g, b = self._center_rgb(c)
        self.assertGreater(r + g + b, 40)
        self.assertGreater(float(c.fill.rgb[3]), 0.9)

    def test_halo_hollow_center_not_opaque_fill(self):
        c = Circle(center=(64, 64), radius=40)
        c.fill = Color("blue")
        c.line = Color("red")
        c.visual = Halo()
        self.assertLess(float(c.fill.rgb[3]), 0.35)
        r, g, b = self._center_rgb(c)
        self.assertGreater(r + g + b, 10)

    def test_set_color_lime_on_halo_still_draws(self):
        """An outline look follows the outline set_color derives, as color=
        does (2026-10-13; before, set_color wrote the exact lime line)."""
        c = Circle(center=(64, 64), radius=40).set_color("coral")
        c.line = Color("red")
        c.visual = Halo()
        c.set_color("lime")
        tint = c.visual._tint_rgba(c)
        want = Color("lime").contrast_tone(intensity=0.2).rgb
        self.assertEqual(tuple(round(v, 3) for v in tint[:3]), tuple(round(v, 3) for v in want[:3]))
        r, g, b = self._center_rgb(c)
        self.assertGreater(r + g + b, 20)


class TestPlainBlit(unittest.TestCase):
    def setUp(self):
        init(width=400, height=300)

    def _sprite(self, **kwargs):
        import tempfile
        from scena.sprite import Sprite
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        info = skia.ImageInfo.Make(16, 16, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        surf.getCanvas().drawPaint(skia.Paint(Color=skia.ColorWHITE))
        surf.makeImageSnapshot().save(tmp.name, skia.kPNG)
        from scena.sprite import Sprite as Spr
        return Spr(tmp.name, height=16, center=(50, 50), **kwargs)

    def test_plain_sprite_skips_envelope(self):
        from scena.canvas import ScenaCanvas, _must_solo_draw
        s = self._sprite()
        self.assertTrue(s._plain_blit)
        self.assertFalse(_must_solo_draw(s))
        n0 = ScenaCanvas._plain_blit_draws
        eng = ScenaCanvas.get_current()
        eng._draw_layer_batched([s])
        self.assertGreater(ScenaCanvas._plain_blit_draws, n0)

    def test_visual_and_flash_leave_and_reenter(self):
        from scena import Glow
        s = self._sprite()
        self.assertTrue(s._plain_blit)
        s.glow = Glow(color="skyblue", radius=8, sigma=4)
        self.assertFalse(s._plain_blit)
        s.glow = None
        self.assertTrue(s._plain_blit)
        s.flash(0.1)
        self.assertFalse(s._plain_blit)
        s.clear_transients()
        from scena.transients import tick_all_transients
        tick_all_transients()
        self.assertTrue(s._plain_blit)

    def test_multipass_still_solos(self):
        from scena.canvas import _must_solo_draw
        c = Circle(center=(0, 0), radius=10, visual=Neon())
        self.assertTrue(_must_solo_draw(c))
        self.assertFalse(getattr(c, "_plain_blit", True))

    def test_plain_shape_uses_blit_fast_path(self):
        """Plain Circle/Line hit ``_blit_plain`` via the batched draw walk."""
        from scena.canvas import ScenaCanvas

        c = Circle(center=(50, 50), radius=10, color="tomato")
        self.assertTrue(c._plain_blit)
        self.assertTrue(callable(getattr(c, "_blit_plain", None)))

        n0 = ScenaCanvas._plain_blit_draws
        eng = ScenaCanvas.get_current()
        eng._draw_layer_batched([c])
        self.assertGreater(ScenaCanvas._plain_blit_draws, n0)

        ln = Line(p1=(0, 0), p2=(40, 0), color="white")
        self.assertTrue(ln._plain_blit)
        n1 = ScenaCanvas._plain_blit_draws
        eng._draw_layer_batched([ln])
        self.assertGreater(ScenaCanvas._plain_blit_draws, n1)

    def test_plain_shape_blit_pulls_linked_rotation(self):
        """Shape ``_blit_plain`` refreshes PropertyAnchors (same as Sprite).

        A free Polygon's heading is property-backed (a Circle's ``angle`` is a
        geometry slot: its link is a plain field link)."""
        from scena.state import Attribute
        from scena.canvas import ScenaCanvas
        from scena.shapes import Polygon

        c = Polygon(points=[(40, 40), (60, 40), (50, 60)], color="skyblue")
        self.assertTrue(c._plain_blit)
        heading = Attribute(15.0)
        c["angle"] @= heading
        self.assertAlmostEqual(c._rotation, 15.0)

        heading.value = 90.0
        self.assertAlmostEqual(c._rotation, 15.0)  # stale until blit

        ScenaCanvas.get_current()._draw_layer_batched([c])
        self.assertAlmostEqual(c._rotation, 90.0)

    def test_batched_plain_blit_pulls_linked_rotation(self):
        """Canvas plain-blit path must see live linked rotation (not stale raw)."""
        from scena.state import Attribute
        from scena.canvas import ScenaCanvas

        s = self._sprite()
        self.assertTrue(s._plain_blit)
        heading = Attribute(15.0)
        s["angle"] @= heading
        self.assertAlmostEqual(s._rotation, 15.0)

        heading.value = 90.0
        self.assertAlmostEqual(s._rotation, 15.0)  # still stale until draw

        eng = ScenaCanvas.get_current()
        eng._draw_layer_batched([s])
        self.assertAlmostEqual(s._rotation, 90.0)
        self.assertAlmostEqual(s._draw_angle(), 90.0)


class TestNeonFlicker(unittest.TestCase):
    def setUp(self):
        init(width=400, height=300)
        canvas.fx_quality = "high"

    def test_default_flicker_is_off_and_interns(self):
        a = Neon("cyan")
        b = Neon("cyan")
        self.assertAlmostEqual(a.flicker, 0.0)
        self.assertIs(a, b)
        self.assertIsNot(Neon("cyan", flicker=0.4), a)
        self.assertNotEqual(Neon("cyan", flicker=0.4)._batch_key, a._batch_key)

    def _halo_stroke(self, look, t):
        import scena.recipes as rec
        from scena.fx_quality import activate_quality

        activate_quality("high")
        orig = rec._clock
        rec._clock = lambda: t
        captured = []
        orig_stroke = Neon._stroke_paint

        def spy(self, *, color, width, blend=BlendMode.NORMAL, mask=None, **kw):
            paint = orig_stroke(
                self, color=color, width=width, blend=blend, mask=mask, **kw,
            )
            captured.append((blend, mask is not None, float(width), paint.getAlphaf()))
            return paint

        Neon._stroke_paint = spy
        try:
            c = Circle(center=(40, 40), radius=12, visual=look)
            c.line_width = 3.0
            surf = skia.Surface(80, 80)
            look._emit_look_passes([c], surf.getCanvas())
        finally:
            Neon._stroke_paint = orig_stroke
            rec._clock = orig
        halo = [row for row in captured if row[0] == BlendMode.ADD and row[1]]
        self.assertTrue(halo, captured)
        return halo[0][2], halo[0][3]

    def test_flicker_zero_matches_static_halo(self):
        w0, a0 = self._halo_stroke(Neon("cyan"), t=0.3)
        w1, a1 = self._halo_stroke(Neon("cyan", flicker=0.0), t=0.3)
        self.assertAlmostEqual(w0, w1)
        self.assertAlmostEqual(a0, a1)
        self.assertAlmostEqual(a0, 1.0)

    def test_flicker_modulates_halo_alpha_and_width(self):
        import math
        from scena.recipes import _NEON_FLICKER_HZ

        # Negative lobe: env < 1 so Skia alphaf is not clamped at 1.
        t = (1.5 * math.pi) / _NEON_FLICKER_HZ
        env = 1.0 + 0.5 * 0.15 * math.sin(t * _NEON_FLICKER_HZ)
        self.assertLess(env, 1.0)
        base_w, base_a = self._halo_stroke(Neon("cyan"), t=t)
        flick_w, flick_a = self._halo_stroke(Neon("cyan", flicker=0.5), t=t)
        self.assertAlmostEqual(flick_a, base_a * env, places=5)
        self.assertAlmostEqual(flick_w, base_w * env, places=5)
        self.assertNotAlmostEqual(flick_a, base_a)
        # Positive lobe: alpha may clamp at 1; width still follows env.
        t_hi = (0.5 * math.pi) / _NEON_FLICKER_HZ
        env_hi = 1.0 + 0.5 * 0.15 * math.sin(t_hi * _NEON_FLICKER_HZ)
        self.assertGreater(env_hi, 1.0)
        hi_w, _hi_a = self._halo_stroke(Neon("cyan", flicker=0.5), t=t_hi)
        self.assertAlmostEqual(hi_w, base_w * env_hi, places=5)


class TestHaloPulseStyle(unittest.TestCase):
    def setUp(self):
        init(width=400, height=300)
        canvas.fx_quality = "high"

    def test_dispatch_and_styles(self):
        from scena.visuals import HALO_STYLES, HaloPulse

        self.assertIn("pulse", HALO_STYLES)
        pulse = Halo(style="pulse")
        self.assertIsInstance(pulse, HaloPulse)
        self.assertIsInstance(pulse, Halo)
        self.assertIs(type(Halo()), Halo)
        self.assertIs(type(Halo(style="hollow")), Halo)
        self.assertIsNot(pulse, Halo())
        self.assertNotEqual(pulse._batch_key, Halo()._batch_key)
        self.assertIs(Halo(style="pulse", rings=3, speed=1.0), pulse)

    def test_apply_matches_hollow_package(self):
        hollow = Circle(center=(40, 40), radius=16)
        pulse = Circle(center=(40, 40), radius=16)
        hollow.fill = Color("cyan")
        pulse.fill = Color("cyan")
        hollow.visual = Halo(amount=1.2)
        pulse.visual = Halo(style="pulse", amount=1.2)
        self.assertEqual(tuple(hollow.fill.rgb), tuple(pulse.fill.rgb))
        self.assertAlmostEqual(float(hollow.line_width), float(pulse.line_width))
        self.assertEqual(type(hollow.line_filter), type(pulse.line_filter))
        self.assertEqual(
            getattr(hollow.line_filter, "_batch_key", None),
            getattr(pulse.line_filter, "_batch_key", None),
        )

    def test_filter_intern_isolated_by_variant(self):
        from scena.visuals import HaloPulse

        h = Halo("cyan", amount=1.0)
        p = Halo("cyan", amount=1.0, style="pulse")
        self.assertIsInstance(p, HaloPulse)
        self.assertIsNot(h, p)
        self.assertNotEqual(h._batch_key, p._batch_key)
        self.assertNotEqual(h._VARIANT, p._VARIANT)

    def test_ring_count_follows_tier(self):
        from scena.fx_quality import activate_quality
        from scena.visuals import HaloPulse

        look = Halo(style="pulse", rings=4, speed=1.0)
        self.assertIsInstance(look, HaloPulse)
        c = Circle(center=(40, 40), radius=16, visual=look)
        orig_clock = __import__("scena.visuals", fromlist=["_clock"])._clock
        import scena.visuals as vis

        vis._clock = lambda: 0.15
        orig = Halo._stroke_at_scale
        strokes = []

        def spy(self, shape, skia_canvas, paint, scale):
            strokes.append(float(scale))
            return orig(self, shape, skia_canvas, paint, scale)

        Halo._stroke_at_scale = spy
        try:
            surf = skia.Surface(80, 80)
            cnv = surf.getCanvas()
            activate_quality("low")
            strokes.clear()
            look._draw_pulse_rings(c, cnv)
            self.assertEqual(len(strokes), 1)
            activate_quality("medium")
            strokes.clear()
            look._draw_pulse_rings(c, cnv)
            self.assertEqual(len(strokes), 2)
            activate_quality("high")
            strokes.clear()
            look._draw_pulse_rings(c, cnv)
            self.assertEqual(len(strokes), 4)
        finally:
            Halo._stroke_at_scale = orig
            vis._clock = orig_clock
            activate_quality("high")


class TestHostStrokeCaps(unittest.TestCase):
    """Host-following recipes copy line_cap; costumes stay round."""

    def setUp(self):
        init(width=200, height=150)
        canvas.fx_quality = "high"

    def test_stroke_paint_cap_maps_and_resets_pool(self):
        look = Laser("red")
        p = look._stroke_paint(color=(1, 0, 0, 1), width=2.0, cap="project")
        self.assertEqual(p.getStrokeCap(), skia.Paint.Cap.kButt_Cap)
        p2 = look._stroke_paint(color=(1, 0, 0, 1), width=2.0, cap="square")
        self.assertEqual(p2.getStrokeCap(), skia.Paint.Cap.kSquare_Cap)
        p3 = look._stroke_paint(color=(1, 0, 0, 1), width=2.0, cap="round")
        self.assertEqual(p3.getStrokeCap(), skia.Paint.Cap.kRound_Cap)
        # Reused slot must not keep the previous caller's cap.
        look._stroke_paint(color=(1, 0, 0, 1), width=2.0, cap="project")
        p4 = look._stroke_paint(color=(1, 0, 0, 1), width=2.0)
        self.assertEqual(p4.getStrokeCap(), skia.Paint.Cap.kRound_Cap)

    def test_laser_and_neon_follow_host_cap(self):
        ln = Line(p1=(10, 10), p2=(80, 20))
        ln.line_cap = "project"
        laser = Laser("red")
        paints = []
        orig = Laser._stroke_paint

        def spy(self, **kw):
            paints.append(kw.get("cap", "round"))
            return orig(self, **kw)

        Laser._stroke_paint = spy
        try:
            surf = skia.Surface(100, 60)
            laser._render(ln, surf.getCanvas())
        finally:
            Laser._stroke_paint = orig
        self.assertTrue(paints)
        self.assertTrue(all(c == "project" for c in paints))

        neon = Neon()
        paints.clear()
        orig_n = Neon._stroke_paint

        def spy_n(self, **kw):
            paints.append(kw.get("cap", "round"))
            return orig_n(self, **kw)

        Neon._stroke_paint = spy_n
        try:
            neon._render(ln, skia.Surface(100, 60).getCanvas())
        finally:
            Neon._stroke_paint = orig_n
        self.assertTrue(paints)
        self.assertTrue(all(c == "project" for c in paints))

    def test_gearshell_and_electric_stay_round(self):
        from scena.fx_quality import activate_quality
        ln = Line(p1=(10, 10), p2=(80, 20))
        ln.line_cap = "project"
        # Survival path uses Recipe._stroke_paint (high ElectricField is GlowRim).
        activate_quality("low")
        try:
            for Cls in (GearShell, ElectricField):
                look = Cls()
                paints = []
                orig = Cls._stroke_paint

                def make_spy(orig_fn, sink):
                    def spy(self, **kw):
                        sink.append(kw.get("cap", "round"))
                        return orig_fn(self, **kw)
                    return spy

                Cls._stroke_paint = make_spy(orig, paints)
                try:
                    look._render(ln, skia.Surface(100, 60).getCanvas())
                finally:
                    Cls._stroke_paint = orig
                self.assertTrue(paints, f"{Cls.__name__} made no strokes")
                self.assertTrue(
                    all(c == "round" for c in paints),
                    f"{Cls.__name__} passed cap={paints}",
                )
        finally:
            activate_quality("high")

    def test_neon_rect_keeps_round_join(self):
        r = Rect(center=(40, 40), width=40, height=30)
        r.line_join = "miter"
        neon = Neon()
        joins = []
        orig = Neon._stroke_paint

        def spy(self, **kw):
            joins.append(kw.get("join", "round"))
            return orig(self, **kw)

        Neon._stroke_paint = spy
        try:
            neon._render(r, skia.Surface(100, 80).getCanvas())
        finally:
            Neon._stroke_paint = orig
        self.assertTrue(joins)
        self.assertTrue(all(j == "round" for j in joins))


class TestFilterBatchKeyIsInternKey(unittest.TestCase):
    def test_blur_input_and_tile_mode_split_batches(self):
        from scena.filters import Blur
        from scena.style import TileMode
        plain = Blur(4)
        chained = Blur(4, input=Blur(1))
        clamped = Blur(4, tile_mode=TileMode.CLAMP)
        self.assertNotEqual(plain._batch_key, chained._batch_key)
        self.assertNotEqual(plain._batch_key, clamped._batch_key)
        self.assertEqual(plain._batch_key, Blur(4)._batch_key)
        self.assertIs(plain, Blur(4))


if __name__ == "__main__":
    unittest.main()
