"""One ``angle`` for a Gradient wherever it is drawn (SK3 in Testing Design).

``Gradient("red", "blue", angle=90)`` runs from the bottom up: red at the
bottom, blue at the top, in Scena's y-up frame. A shape fill did; a Wallpaper
(and ``canvas.background = Gradient``) drew it top-down, because the wallpaper
fill is built in device pixels (y down) and skipped the flip a shape gets from
the canvas. Every surface that draws a Gradient is rendered here and read back.

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
    Circle, Gradient, Menu, Rect, SkyGradient, Wallpaper, canvas,
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
