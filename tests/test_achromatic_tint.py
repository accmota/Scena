"""A gray host gives a gray look: no invented hue.

Bug (2026-10-08): ``triangulo.visual = Neon(); triangulo.color = "white"``
drew a red tube. Neon's vivid tint lifts HSV saturation, and ``colorsys``
reports hue 0 (red) for every gray, so white, gray and black all became red.
The same lift sat in ``_energy_rgb`` (DashRing, GearShell, ElectricBolt) and
``Color.vibrant_version`` (Halo fill / soft). Fix: ``color._chroma_weight``
fades a saturation lift out below HSV saturation 0.1 (Effect System Design,
"A gray host gives a gray look").

Bug class: any look that follows the host color and lifts saturation. The
render tests walk every public look (shape visuals, Halo styles, stamps,
looks seeded with a gray on a Shape and a Sprite), so a new one is covered without a new test.
"""

from __future__ import annotations

import colorsys
import inspect
import os
import shutil
import sys
import tempfile
import unittest
import warnings

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import skia

import scena
from scena import EquilateralTriangle, Halo, Sprite
from scena import recipes as _recipes
from scena.color import Color, _ACHROMATIC_S, _chroma_weight
from scena.recipes import _energy_rgb, _energy_spark_rgb, _vivid_rgb
from scena.visuals import Visual

GRAYS = (0.0, 0.1, 0.25, 0.5, 0.75, 1.0)
HOSTS = ("white", "gray", "black")

# Looks that take no host color (the material is the color) or are bases:
# they cannot invent a hue from the host. Same list and reasons as
# test_visual_color_param._NO_COLOR.
_NO_HOST_COLOR = {"Flame", "Swell", "Water", "Grayscale", "HueShift", "Recolor",
                  "EmissiveBloom", "Visual", "Recipe"}

# Mean (R - max(G, B)) over lit pixels. Hue 0 invented from a gray gives 11
# (ElectricBolt) to 175 (Neon); warm-white looks (Glow) stay under 3.
RED_CAST_TOL = 6.0


def _red_cast(px: np.ndarray):
    rgb = px[..., :3].astype(int)
    lit = rgb.max(-1) > 40
    if not lit.any():
        return None
    return float((rgb[lit][:, 0] - rgb[lit][:, 1:].max(-1)).mean())


def _draw(obj) -> np.ndarray:
    surf = skia.Surface(128, 128)
    cnv = surf.getCanvas()
    cnv.clear(skia.ColorBLACK)
    obj.draw(cnv)
    return surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)


def _public_looks():
    out = []
    for name in scena.__all__:
        obj = getattr(scena, name, None)
        if inspect.isclass(obj) and issubclass(obj, Visual) and name not in _NO_HOST_COLOR:
            out.append(obj)
    return out


def _vivid_unramped(rgb, amt):
    """The pre-fix lift: what any color at s >= _ACHROMATIC_S must still get."""
    h, s, v = colorsys.rgb_to_hsv(*rgb)
    return colorsys.hsv_to_rgb(h, min(1.0, s + amt + (1.0 - s) * amt * 0.65),
                               min(1.0, max(v, 0.72) + amt * 0.28))


class TestHelpersKeepGraysGray(unittest.TestCase):
    def assertGray(self, rgb, msg):
        self.assertAlmostEqual(max(rgb[:3]) - min(rgb[:3]), 0.0, places=6, msg=msg)

    def test_every_gray_level_every_helper(self):
        for g in GRAYS:
            rgb = (g, g, g)
            for amt in (0.22, 0.5, 0.55, 1.0):
                self.assertGray(_vivid_rgb(rgb, amt), f"_vivid_rgb{rgb} amt={amt}")
                self.assertGray(Color(*rgb).vibrant_version(amt).rgb,
                                f"vibrant_version{rgb} amt={amt}")
            self.assertGray(_energy_rgb((g, g, g, 1.0)), f"_energy_rgb{rgb}")
            self.assertGray(_energy_spark_rgb(rgb, 0.18), f"_energy_spark_rgb{rgb}")

    def test_vibrant_still_lifts_value_of_a_gray(self):
        """Neon still brightens a dark host; it just keeps it neutral."""
        out = Color(0.1, 0.1, 0.1).vibrant_version(0.55)
        self.assertGreater(out.rgb[0], 0.8)

    def test_ramp_is_continuous_and_monotone_near_gray(self):
        prev = -1.0
        for i in range(0, 21):
            s = 0.15 * i / 20
            rgb = colorsys.hsv_to_rgb(0.6, s, 0.8)
            s2 = colorsys.rgb_to_hsv(*_vivid_rgb(rgb, 0.55))[1]
            self.assertGreaterEqual(s2, prev - 1e-9, f"s={s:.3f}")
            prev = s2
        near = colorsys.hsv_to_rgb(0.0, 0.01, 1.0)        # "snow"-like
        self.assertLess(colorsys.rgb_to_hsv(*_vivid_rgb(near, 0.55))[1], 0.15)

    def test_saturated_colors_unchanged(self):
        """The ramp only touches s < _ACHROMATIC_S: gold, slate, cyan keep their tint."""
        self.assertEqual(_chroma_weight(_ACHROMATIC_S), 1.0)
        for rgb in [(1.0, 0.84, 0.0), (0.44, 0.5, 0.56), (0.35, 0.9, 1.0),
                    colorsys.hsv_to_rgb(0.3, _ACHROMATIC_S, 0.6)]:
            for got in (_vivid_rgb(rgb, 0.55), Color(*rgb).vibrant_version(0.55).rgb[:3]):
                for a, b in zip(got, _vivid_unramped(rgb, 0.55)):
                    self.assertAlmostEqual(a, b, places=6, msg=str(rgb))


class TestLooksKeepGraysGray(unittest.TestCase):
    """Every host-following look on a white / gray / black host: no red cast."""

    def setUp(self):
        self._clock = _recipes._clock
        _recipes._clock = lambda: 0.37
        warnings.simplefilter("ignore")

    def tearDown(self):
        _recipes._clock = self._clock
        warnings.resetwarnings()

    def _check(self, label, make):
        for host in HOSTS:
            with self.subTest(look=label, host=host):
                cast = _red_cast(_draw(make(host)))
                if cast is not None:
                    self.assertLessEqual(cast, RED_CAST_TOL, f"{label} on {host}: red cast {cast:.1f}")

    def test_shape_visuals(self):
        checked = []
        for cls in _public_looks():
            try:
                EquilateralTriangle().visual = cls()
            except TypeError:
                continue  # stamps and sprite-only looks: covered below
            checked.append(cls.__name__)

            def make(host, cls=cls):
                t = EquilateralTriangle(center=(64, 64), radius=36, angle=90)
                t.color = "gold"
                t.visual = cls()
                t.color = host          # recolor after the look (tutorial 01)
                return t
            self._check(cls.__name__, make)
        self.assertIn("Neon", checked)
        self.assertGreater(len(checked), 20, "discovery found too few looks")

    def test_halo_styles(self):
        for style in ("hollow", "fill", "soft", "line", "pulse"):
            def make(host, style=style):
                t = EquilateralTriangle(center=(64, 64), radius=36, angle=90)
                t.color = host
                t.visual = Halo(style=style)
                return t
            self._check(f"Halo({style})", make)

    def test_stamps(self):
        for slot, cls in (("glow", scena.Glow), ("glow", scena.CheapGlow),
                          ("shadow", scena.Shadow), ("tail", scena.Tail)):
            def make(host, slot=slot, cls=cls):
                t = EquilateralTriangle(center=(64, 64), radius=30, angle=90)
                t.color = host
                setattr(t, slot, cls())
                return t
            self._check(cls.__name__, make)

    def test_seeded_with_a_gray(self):
        """``Neon("white")``: the seed goes through the same lift as a host color.

        Unseeded looks on a Sprite use their own default tint (Laser red, Halo
        cyan), not the sprite's pixels, so a seeded look is the Sprite path
        into this bug; it is covered on both hosts.
        """
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        info = skia.ImageInfo.Make(32, 32, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        surf.getCanvas().drawCircle(16, 16, 14, skia.Paint(Color=skia.Color(128, 128, 128), AntiAlias=True))
        sprite_png = os.path.join(tmp, "gray.png")
        surf.makeImageSnapshot().save(sprite_png, skia.kPNG)
        checked = []
        for cls in _public_looks():
            if "color" not in inspect.signature(cls.__init__).parameters:
                continue
            for host_kind in ("shape", "sprite"):
                def make(gray, cls=cls, host_kind=host_kind):
                    if host_kind == "shape":
                        o = EquilateralTriangle(center=(64, 64), radius=36, angle=90)
                        o.color = gray
                    else:
                        o = Sprite(sprite_png, size=48, center=(64, 64))
                    o.visual = cls(gray)
                    return o
                try:
                    make("white")
                except TypeError:
                    continue  # stamps; sprite-only / shape-only looks
                checked.append(f"{host_kind} {cls.__name__}")
                self._check(f"{host_kind} {cls.__name__}(seeded)", make)
        self.assertIn("shape Neon", checked)
        self.assertIn("shape Halo", checked)

if __name__ == "__main__":
    unittest.main()
