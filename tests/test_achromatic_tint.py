"""A gray host gives a gray look: no invented hue.

Bug (2026-10-08): ``triangulo.visual = Neon(); triangulo.color = "white"``
drew a red tube. Neon's vivid tint lifts HSV saturation, and ``colorsys``
reports hue 0 (red) for every gray, so white, gray and black all became red.
The same lift sat in ``_energy_rgb`` (DashRing, GearShell, ElectricBolt) and
``Color.vibrant_version`` (Halo fill / soft). Fix: ``color._chroma_weight``
fades a saturation lift out below HSV saturation 0.1 (Effect System Design,
"A gray host gives a gray look").

The same lift sat in Color methods: ``saturate``, ``jitter``, ``accent_color``,
``monochromatic``, and ``interpolate`` in HSL / HSV, where a gray end's hue 0
sent white -> blue through magenta.

Bug class: any look or Color method that adds saturation to a gray (or reads
a gray's hue). The render tests walk every public look (shape visuals, Halo styles, stamps,
looks seeded with a gray on a Shape and a Sprite), so a new one is covered without a new test.
"""

from __future__ import annotations

import colorsys
import inspect
import os
import random
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
from scena.color import Color, ColorSpace, Colormap, _ACHROMATIC_S, _chroma_weight
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


def _is_gray(c: Color) -> bool:
    r, g, b = c.rgb[:3]
    return max(r, g, b) - min(r, g, b) < 1e-6


class TestColorMethodsKeepGraysGray(unittest.TestCase):
    def assertAllGray(self, out, msg):
        outs = out if isinstance(out, (list, tuple)) else [out]
        for c in outs:
            if isinstance(c, Color):
                self.assertTrue(_is_gray(c), f"{msg}: {tuple(round(x, 3) for x in c.rgb[:3])}")

    def test_every_zero_arg_method_on_every_gray(self):
        """Discovery: a new public Color method that invents a hue fails here."""
        called = []
        for name in dir(Color):
            if name.startswith("_") or isinstance(inspect.getattr_static(Color, name),
                                                  (classmethod, staticmethod, property)):
                continue
            for g in GRAYS:
                try:
                    out = getattr(Color(g, g, g), name)()
                except TypeError:
                    break  # needs arguments (lerp, with_alpha): covered below
                self.assertAllGray(out, f"Color({g}).{name}()")
            else:
                called.append(name)
        for name in ("saturate", "jitter", "accent_color", "monochromatic", "vibrant_version"):
            self.assertIn(name, called)

    def test_lifts_with_arguments(self):
        random.seed(7)
        for g in GRAYS:
            c = Color(g, g, g)
            for amt in (0.1, 0.5, 1.0):
                self.assertAllGray(c.saturate(amt), f"saturate({amt}) on {g}")
                self.assertAllGray(c.accent_color(amt), f"accent_color({amt}) on {g}")
            self.assertAllGray(c.monochromatic(9), f"monochromatic(9) on {g}")
            for _ in range(40):
                self.assertAllGray(c.jitter(hue=0.5, saturation=0.5, value=0.2), f"jitter on {g}")

    def test_lifts_unchanged_on_saturated_colors(self):
        c = Color(0.6, 0.4, 0.4)                    # HSV s = 0.33
        h, s, l, a = c.hsl
        self.assertEqual(c.saturate(0.2).rgb, Color.from_hsl(h, min(1.0, s + 0.2), l, a).rgb)
        golden = 0.618033988749895
        self.assertEqual(c.accent_color(0.3).rgb, Color.from_hsl(
            (h + golden) % 1.0, min(1.0, s + 0.3 * 0.2), max(0.2, min(0.8, l + (0.5 - l) * 0.3)), a).rgb)

    def _hues_along(self, a, b, space, n=9):
        return [Color.interpolate(a, b, i / (n - 1), space) for i in range(1, n - 1)]

    def test_interpolate_gray_end_takes_the_other_hue(self):
        """white -> blue in HSV/HSL stays blue; it used to sweep through magenta."""
        for space in (ColorSpace.HSV, ColorSpace.HSL):
            for g in GRAYS:
                for target in ("blue", "lime", "orange", "cyan"):
                    tc = Color(target)
                    for a, b in ((Color(g, g, g), tc), (tc, Color(g, g, g))):
                        for mid in self._hues_along(a, b, space):
                            if _is_gray(mid):
                                continue
                            d = abs(mid.hsv[0] - tc.hsv[0])
                            self.assertLess(min(d, 1 - d), 1e-3,
                                            f"{space.value} {g} <-> {target}: mid {mid.rgb[:3]}")
                # Colormap goes through interpolate.
                cmap = Colormap([(0.0, Color(g, g, g)), (1.0, tc)], space)
                mid = cmap.get_color(0.5)
                if not _is_gray(mid):
                    d = abs(mid.hsv[0] - tc.hsv[0])
                    self.assertLess(min(d, 1 - d), 1e-3, f"Colormap {space.value} {g} -> {target}")

    def test_interpolate_saturated_pairs_unchanged(self):
        """red -> blue still takes the shortest hue path (through magenta)."""
        for space in (ColorSpace.HSV, ColorSpace.HSL):
            mid = Color.interpolate(Color("red"), Color("blue"), 0.5, space)
            self.assertAlmostEqual(mid.hsv[0], 5 / 6, places=3)

    def test_interpolate_is_continuous_near_gray(self):
        """An end at s = 0.05 pulls halfway: between its own hue and the other's."""
        near = Color.from_hsv(0.0, 0.05, 1.0)       # faint pink
        mid = Color.interpolate(near, Color("blue"), 0.5, ColorSpace.HSV)
        self.assertTrue(2 / 3 < mid.hsv[0] < 1.0, mid.hsv)   # between blue and red, via magenta
        far = Color.interpolate(Color.from_hsv(0.0, 0.001, 1.0), Color("blue"), 0.5, ColorSpace.HSV)
        d = abs(far.hsv[0] - 2 / 3)
        self.assertLess(d, 0.01, far.hsv)


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
