"""One ``angle`` for a Gradient or a Texture wherever it is drawn (SK3, SK4 in Testing Design).

``Gradient("red", "blue", angle=90)`` runs from the bottom up: red at the
bottom, blue at the top, in Scena's y-up frame. A shape fill did; a Wallpaper
(and ``canvas.background = Gradient``) drew it top-down, because the wallpaper
fill is built in device pixels (y down) and skipped the flip a shape gets from
the canvas. Every surface that draws a Gradient is rendered here and read back.

``Texture(..., angle=90)`` turns the image a quarter counter-clockwise (y-up)
on a shape; a Wallpaper took the angle and drew the image unturned (SK4).

    python tests/run_tiers.py focused test_gradient_direction
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import skia  # noqa: E402

from scena import (  # noqa: E402
    Circle, Gradient, Menu, Rect, SkyGradient, Texture, Wallpaper, canvas,
)
from scena import background_kinds  # noqa: E402
from scena.style import GradientType  # noqa: E402
from tests.leftovers import module_sweep  # noqa: E402
from tests.system_support import system_world  # noqa: E402

setUpModule, tearDownModule = module_sweep()

FRAME = 1 / 60
RED, BLUE = np.array([255, 0, 0]), np.array([0, 0, 255])


def _frame(w) -> np.ndarray:
    w.step(1, dt=FRAME)
    img = w.surface.makeImageSnapshot()
    info = skia.ImageInfo.Make(
        img.width(), img.height(), skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType,
    )
    buf = bytearray(img.width() * img.height() * 4)
    assert img.readPixels(info, buf, img.width() * 4, 0, 0)
    return np.frombuffer(bytes(buf), np.uint8).reshape(img.height(), img.width(), 4)[:, :, :3]


def _redness(px) -> float:
    """1 for red, 0 for blue."""
    px = px.astype(float)
    return float(px[0] / max(px[0] + px[2], 1.0))


def _box(a, mask):
    ys, xs = np.where(mask)
    assert len(ys), "nothing drawn"
    return xs.min(), xs.max(), ys.min(), ys.max()


def _ramp(a, x0, x1, y0, y1) -> str:
    """'up' when red is at the bottom (device rows grow downward)."""
    cx = (x0 + x1) // 2
    inset = max(2, (y1 - y0) // 10)
    top, bottom = _redness(a[y0 + inset, cx]), _redness(a[y1 - inset, cx])
    assert abs(top - bottom) > 0.3, f"no vertical ramp: top {top:.2f} bottom {bottom:.2f}"
    return "up" if bottom > top else "down"


def _not_green(a):
    return a[:, :, 1] < 100


def _full(a):
    h, w = a.shape[:2]
    return 0, w - 1, 0, h - 1


class TestAngle90RunsBottomUpEverywhere(unittest.TestCase):

    def _shape(self, make):
        with system_world(draw=True) as w:
            Wallpaper("lime")
            make()
            a = _frame(w)
            return _ramp(a, *_box(a, _not_green(a)))

    def _wallpaper(self, make):
        with system_world(draw=True) as w:
            make()
            a = _frame(w)
            return _ramp(a, *_full(a))

    def test_every_surface(self):
        g = lambda **kw: Gradient("red", "blue", angle=90, **kw)  # noqa: E731

        def rect_fill(**kw):
            Rect(center=(200, 150), width=160, height=200).fill = g(**kw)

        def circle_fill():
            Circle(center=(200, 150), radius=100).fill = g()

        def bg_assign():
            canvas.background = g()

        def menu_panel():
            Menu(options=["Um", "Dois", "Três"], background=g(), modal=False)

        cases = {
            "shape fill": lambda: self._shape(rect_fill),
            "shape fill, size=": lambda: self._shape(lambda: rect_fill(size=100)),
            "circle fill": lambda: self._shape(circle_fill),
            "Menu panel": lambda: self._shape(menu_panel),
            "Wallpaper": lambda: self._wallpaper(lambda: Wallpaper(g())),
            "Wallpaper, size=": lambda: self._wallpaper(lambda: Wallpaper(g(size=100))),
            "canvas.background =": lambda: self._wallpaper(bg_assign),
        }
        for label, run in cases.items():
            with self.subTest(surface=label):
                self.assertEqual(run(), "up")

    def test_sweep_turns_the_same_way_on_a_shape_and_a_wallpaper(self):
        # y-up, counter-clockwise from +x: a quarter turn reaches the top.
        sweep = lambda: Gradient("red", "blue", type="sweep")  # noqa: E731

        def above_minus_below(a, x0, x1, y0, y1):
            cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
            d = (y1 - y0) // 4
            return _redness(a[cy - d, cx]) - _redness(a[cy + d, cx])

        with system_world(draw=True) as w:
            Wallpaper("lime")
            Rect(center=(200, 150), width=200, height=200).fill = sweep()
            a = _frame(w)
            shape = above_minus_below(a, *_box(a, _not_green(a)))
        with system_world(draw=True) as w:
            Wallpaper(sweep())
            a = _frame(w)
            wall = above_minus_below(a, *_full(a))
        self.assertGreater(shape, 0.2)
        self.assertGreater(wall, 0.2)

    def test_sky_gradient_keeps_its_zenith_on_top(self):
        for kw in ({"top": "red", "middle": "blue"}, {}):
            with self.subTest(kw=kw), system_world(draw=True) as w:
                SkyGradient(**kw) if kw else SkyGradient("day")
                a = _frame(w)
                h, wd = a.shape[:2]
                top, bottom = a[3, wd // 2].astype(int), a[h - 4, wd // 2].astype(int)
                if kw:
                    self.assertGreater(_redness(top), 0.8)
                    self.assertLess(_redness(bottom), 0.2)
                else:
                    # "day": deep blue zenith over a pale horizon.
                    self.assertLess(top.sum(), bottom.sum())


def _red_left_blue_right() -> skia.Image:
    """64 x 64: the image's +x half is blue. A quarter CCW turn puts blue on top."""
    surf = skia.Surface(64, 64)
    c = surf.getCanvas()
    c.drawRect(skia.Rect.MakeXYWH(0, 0, 32, 64), skia.Paint(Color=skia.ColorRED))
    c.drawRect(skia.Rect.MakeXYWH(32, 0, 32, 64), skia.Paint(Color=skia.ColorBLUE))
    return surf.makeImageSnapshot()


class TestTextureAngleTurnsTheSameWay(unittest.TestCase):
    """``angle=90`` puts the image's +x (blue) on top: red bottom, so ``"up"``."""

    @classmethod
    def setUpClass(cls):
        cls.img = _red_left_blue_right()

    def _tex(self, angle, **kw):
        return Texture(image=self.img, angle=angle, **kw)

    def _shape(self, angle, **kw):
        with system_world(draw=True) as w:
            Wallpaper("lime")
            Rect(center=(200, 150), width=160, height=160).fill = self._tex(angle, **kw)
            a = _frame(w)
            return _ramp(a, *_box(a, _not_green(a)))

    def _wallpaper(self, angle, **kw):
        with system_world(draw=True) as w:
            Wallpaper(self._tex(angle, **kw))
            a = _frame(w)
            return _ramp(a, *_full(a))

    # Every way a Wallpaper draws an image: the fitted DECAL image (drawImageRect),
    # a fitted image through the template shader (clamp), and tiles.
    FITS = {
        "cover": {"fit": "cover"},
        "contain": {"fit": "contain"},
        "stretch": {"fit": "stretch"},
        "cover, clamp": {"fit": "cover", "tile_mode": "clamp"},
        "stretch, mirror": {"fit": "stretch", "tile_mode": "mirror"},
    }

    def test_shape_and_wallpaper_agree_on_every_fit(self):
        for label, kw in self.FITS.items():
            for angle, want in ((90, "up"), (-90, "down")):
                with self.subTest(fit=label, angle=angle):
                    self.assertEqual(self._shape(angle, **kw), want)
                    self.assertEqual(self._wallpaper(angle, **kw), want)

    def test_tiles_turn_the_same_way(self):
        # One cell as tall as the design: a quarter turn about world (0, 0)
        # (the frame's bottom-left at rest) leaves red below the middle.
        with system_world():
            dh = float(canvas.height)
        for angle, want in ((90, "up"), (-90, "down")):
            with self.subTest(angle=angle):
                self.assertEqual(self._shape(angle, fit="tile", tile_size=160), want)
                self.assertEqual(self._wallpaper(angle, fit="tile", tile_size=dh), want)

    def test_unturned_texture_has_no_vertical_ramp(self):
        with system_world(draw=True) as w:
            Wallpaper(self._tex(0, fit="stretch"))
            a = _frame(w)
            with self.assertRaisesRegex(AssertionError, "no vertical ramp"):
                _ramp(a, *_full(a))

    def test_canary_wallpaper_ignores_the_angle(self):
        from tests.diff_support import assert_catches
        assert_catches(
            self, "test_gradient_direction.TestTextureAngleTurnsTheSameWay."
                  "test_shape_and_wallpaper_agree_on_every_fit",
            [("scena.style", "_texture_turn", lambda source: 0.0)],
            "a Wallpaper that draws a Texture unturned (SK4, 2026-10-13)")
        assert_catches(
            self, "test_gradient_direction.TestTextureAngleTurnsTheSameWay."
                  "test_tiles_turn_the_same_way",
            [("scena.style", "_texture_turn", lambda source: -source._angle)],
            "a Wallpaper tile turned clockwise")


class TestCanaries(unittest.TestCase):

    def test_the_reader_sees_a_top_down_ramp(self):
        with system_world(draw=True) as w:
            Wallpaper("lime")
            Rect(center=(200, 150), width=160, height=200).fill = Gradient(
                "blue", "red", angle=90)
            a = _frame(w)
            self.assertEqual(_ramp(a, *_box(a, _not_green(a))), "down")

    def test_a_sky_on_angle_90_would_be_upside_down(self):
        def old(self):
            args = [(p, background_kinds.Color(*c)) for p, c in self._ramp_stops()]
            return Gradient(*args, type=GradientType.LINEAR, angle=90.0)

        with mock.patch.object(SkyGradient, "_make_gradient", old), \
                system_world(draw=True) as w:
            SkyGradient(top="red", middle="blue")
            a = _frame(w)
            self.assertLess(_redness(a[3, a.shape[1] // 2]), 0.2)


if __name__ == "__main__":
    unittest.main()
