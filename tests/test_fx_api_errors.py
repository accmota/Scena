"""Fail-fast FX API: wrong family, unknown names, apply must not swallow.

    python -m unittest tests.test_fx_api_errors -v
"""
from __future__ import annotations

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import (
    init, canvas, Circle, Neon, Fill, Stroke, Halo, Shield, Bolt,
    Blur, set_defaults, Grade, Haze, Fire, Sparks, Rain, Warp, Vignette,
    HueShift, Recolor, Glow, Aura,
)
from scena.style import Gradient, Texture, WaterFill, ProceduralFill
from scena.visuals import Visual
from scena.background_kinds import Lattice, Wallpaper
from scena.color import Color
from scena.place import unplaced_creation
from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()


class TestFxApiErrors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def test_fill_filter_rejects_look_and_string(self):
        c = Circle(center=(0, 0), radius=10)
        with self.assertRaises(TypeError) as ctx:
            c.fill_filter = Neon()
        self.assertIn("look", str(ctx.exception).lower())
        with self.assertRaises(TypeError) as ctx:
            c.fill_filter = "bad"
        self.assertIn("filter", str(ctx.exception).lower())
        c.fill_filter = Blur()
        c.fill_filter = None
        self.assertIsNone(c.fill_filter)

    def test_fill_stroke_solids_only(self):
        with self.assertRaises(TypeError) as ctx:
            Fill(Gradient("blue"))
        msg = str(ctx.exception)
        self.assertIn("solid", msg.lower())
        self.assertIn("Paint", msg)

    def test_set_defaults_rejects_wrong_family(self):
        with self.assertRaises(TypeError) as ctx:
            set_defaults(Blur())
        self.assertIn("filter", str(ctx.exception).lower())
        with self.assertRaises(TypeError):
            set_defaults(fill_filter=Neon())

    def test_visual_rejects_non_looks_without_apply(self):
        c = Circle(center=(0, 0), radius=10)
        with self.assertRaises(TypeError):
            c.visual = 1
        with self.assertRaises(TypeError) as ctx:
            c.visual = random.Random()
        self.assertIn("look", str(ctx.exception).lower())

    def test_unknown_discrete_names_raise(self):
        with self.assertRaises(ValueError) as ctx:
            Shield(style="nimbus")
        self.assertIn("bubble", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            Halo(style="glow")
        self.assertIn("hollow", str(ctx.exception))
        with self.assertRaises(TypeError):
            Aura(style="edge")
        with self.assertRaises(TypeError):
            Aura(style="glow")
        with self.assertRaises(ValueError):
            Bolt(style="new")
        with self.assertRaises(ValueError):
            Fire(style="huge")
        with self.assertRaises(TypeError):
            Sparks(style="chunky")
        with self.assertRaises(ValueError):
            Grade("neon")
        with self.assertRaises(ValueError):
            Haze(kind="fog")
        c = Circle(center=(0, 0), radius=10)
        with self.assertRaises(ValueError):
            c.dissolve_out(0.2, style="melt")
        with unplaced_creation():
            with self.assertRaises(ValueError):
                Lattice(fold="grid")

    def test_dash_enum_string_ok_junk_raises(self):
        c = Circle(center=(0, 0), radius=10)
        c.dash = "dash"
        self.assertEqual(c.dash, "dash")
        other = Circle(center=(0, 0), radius=10)
        other.dash = c.dash
        self.assertEqual(other.dash, "dash")
        with self.assertRaises(TypeError):
            c.dash = "zigzag"

    def test_line_width_and_filter_sigma_clamp_nonneg(self):
        c = Circle(center=(0, 0), radius=10)
        with self.assertRaises(ValueError):
            c.line_width = -2
        with self.assertRaises(ValueError):
            Blur(sigma=-4)
        from scena.filters import DropShadow, Dilate
        with self.assertRaises(ValueError):
            DropShadow(sigma=-1)
        with self.assertRaises(ValueError):
            Dilate(radius=-3)

    def test_gradient_type_and_texture_fit_raise(self):
        g = Gradient("navy", "cyan", type="linear")
        self.assertEqual(g.type, "linear")
        with self.assertRaises(TypeError) as ctx:
            Gradient("navy", "cyan", type="cone")
        self.assertIn("radial", str(ctx.exception))
        tex = Texture(fit="tile")
        self.assertEqual(tex.fit, "tile")
        with self.assertRaises(TypeError) as ctx:
            Texture(fit="fit")
        self.assertIn("cover", str(ctx.exception))
        with self.assertRaises(TypeError) as ctx:
            Texture(fit="tile", tile_mode="zigzag")
        self.assertIn("tile_mode", str(ctx.exception))
        with unplaced_creation():
            with self.assertRaises(TypeError):
                Wallpaper(fit="zoom")
        with self.assertRaises(ValueError):
            Texture(scale=0)
        with self.assertRaises(ValueError):
            Texture(scale=-0.5)
        self.assertEqual(Texture(scale=2).scale, 2.0)

    def test_texture_shift_accepts_hueshift_recolor_only(self):
        hs = HueShift(amount=0.33)
        rc = Recolor(key="lime", to="tomato")
        self.assertIs(Texture(shift=hs).shift, hs)
        self.assertIs(Texture(shift=rc).shift, rc)
        self.assertIsNone(Texture().shift)
        with self.assertRaises(TypeError) as ctx:
            Texture(shift=Glow())
        self.assertIn("HueShift", str(ctx.exception))
        self.assertIn("Recolor", str(ctx.exception))
        with self.assertRaises(TypeError) as ctx:
            Texture(shift=1)
        self.assertIn("HueShift", str(ctx.exception))
        with self.assertRaises(TypeError) as ctx:
            Texture(shift=HueShift(live=True))
        self.assertIn("live", str(ctx.exception).lower())

    def test_waterfill_and_procedural_kind_raise(self):
        WaterFill(kind="top")
        with self.assertRaises(ValueError) as ctx:
            WaterFill(kind="ocean")
        self.assertIn("side", str(ctx.exception))
        with self.assertRaises(ValueError):
            WaterFill(kind="above")
        with self.assertRaises(ValueError) as ctx:
            ProceduralFill(kind="foo")
        self.assertIn("swell", str(ctx.exception))

    def test_fidelity_reapply_propagates(self):
        class Boom(Visual):
            _fidelity_sensitive = True

            def _apply(self, shape):
                if getattr(self, "_boom", False):
                    raise RuntimeError("apply boom")

        c = Circle(center=(0, 0), radius=10)
        boom = Boom()
        c.visual = boom
        boom._boom = True
        prev = canvas.fx_quality
        try:
            with self.assertRaises(RuntimeError) as ctx:
                canvas.fx_quality = "medium"
            self.assertIn("apply boom", str(ctx.exception))
        finally:
            boom._boom = False
            canvas.fx_quality = prev

    def test_effects_add_rejects_wrong_family(self):
        with self.assertRaises(TypeError) as ctx:
            canvas.effects.add(Neon())
        self.assertIn("look", str(ctx.exception).lower())
        fx = Fire(center=(0, 0))
        try:
            with self.assertRaises(TypeError) as ctx:
                canvas.effects.add(fx)
            self.assertIn("SpatialFx", str(ctx.exception))
        finally:
            fx.destroy()
        with self.assertRaises(TypeError):
            canvas.effects.add(Blur())
        v = Vignette()
        self.assertIs(canvas.effects.add(v), v)
        canvas.effects.remove(v)

    def test_wallpaper_rejects_wrong_family(self):
        with self.assertRaises(TypeError) as ctx:
            canvas.background = Neon()
        self.assertIn("look", str(ctx.exception).lower())
        fx = Fire(center=(0, 0))
        try:
            with self.assertRaises(TypeError) as ctx:
                canvas.background = fx
            self.assertIn("SpatialFx", str(ctx.exception))
        finally:
            fx.destroy()
        with unplaced_creation():
            with self.assertRaises(TypeError):
                Wallpaper(source=Blur())
            w = Wallpaper("navy")
            self.assertEqual(
                tuple(round(float(c), 3) for c in w.source.rgb[:3]),
                tuple(round(float(c), 3) for c in Color("navy").rgb[:3]),
            )
        canvas.background = "navy"

    def test_spatial_positionals_raise(self):
        # Keyword-only like Shape; the class-wide walk is in test_spatial_fx.
        for call in (lambda: Fire(1, 2), lambda: Rain(1, 2, 3, 4),
                     lambda: Fire(0, 0, center=(10, 10)), lambda: Warp(1, 2, 3)):
            with self.assertRaises(TypeError):
                call()

    def test_spatial_unknown_kwargs_raise(self):
        with self.assertRaises(TypeError) as ctx:
            Fire(aaa=1)
        self.assertIn("aaa", str(ctx.exception))
        with self.assertRaises(TypeError) as ctx:
            Rain(center=(0, 0), width=10, height=10, aaa=1)
        self.assertIn("aaa", str(ctx.exception))
