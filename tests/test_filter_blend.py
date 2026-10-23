"""
A shape with a fill or line filter keeps its ``.blend``.

A filtered shape draws in its filter's layer (full-res ``saveLayer`` or the
reduced ``shape_fx_scale`` render target), where it paints over transparent;
the layer landed on the picture with srcOver, so ``blend = "multiply"`` under
``fill_filter = Blur(2)`` painted as normal (showcase A6, 2026-10-23). The
layer now lands with the group's blend, and shapes of two blends never share
a layer (``canvas._filter_group_key``).

Guarded in pixels: each blend × each fx scale × fill / line filter matches
the same shape without its filter at the middle of the shape; two shapes
sharing one filter but not one blend each keep theirs.

Run:

    python tests/run_tiers.py focused test_filter_blend
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import numpy as np  # noqa: E402
import skia  # noqa: E402

from program_support import FRAME  # noqa: E402
from system_support import boot, system_world  # noqa: E402

from scena import Blur, Ellipse, Line, Rect, canvas  # noqa: E402
from tests.leftovers import module_sweep  # noqa: E402

boot()
setUpModule, tearDownModule = module_sweep()

BLENDS = ("multiply", "add", "screen", "normal")


def frame(w):
    w.step(2, dt=FRAME)
    img = w.surface.makeImageSnapshot()
    info = skia.ImageInfo.Make(img.width(), img.height(),
                               skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
    buf = bytearray(img.width() * img.height() * 4)
    assert img.readPixels(info, buf, img.width() * 4, 0, 0)
    return np.frombuffer(bytes(buf), np.uint8).reshape(img.height(), img.width(), 4)[:, :, :3].astype(int)


def scene(blend, filtered, scale, line=False):
    with system_world(draw=True) as w:
        saved = canvas.shape_fx_scale
        try:
            canvas.shape_fx_scale = scale
            Rect(center=(200, 150), width=400, height=300, color="#4080c0")
            if line:
                s = Line(p1=(120, 150), p2=(280, 150), line_width=30, color="#d04020")
            else:
                s = Ellipse(center=(200, 150), width=160, height=100, color="#d04020")
            s.blend = blend
            if filtered:
                if line:
                    s.line_filter = Blur(1)
                else:
                    s.fill_filter = Blur(1)
            return frame(w)[150, 200]
        finally:
            canvas.shape_fx_scale = saved


class TestFilteredShapesKeepTheirBlend(unittest.TestCase):
    def test_each_blend_scale_and_channel(self):
        for blend in BLENDS:
            for scale in (1.0, 0.5):
                for line in (False, True):
                    with self.subTest(blend=blend, scale=scale, line=line):
                        plain = scene(blend, False, scale, line)
                        blurred = scene(blend, True, scale, line)
                        self.assertLess(int(np.abs(plain - blurred).max()), 24,
                                        f"{blend}: {plain} without the filter, {blurred} with it")

    def test_two_blends_sharing_a_filter_keep_their_own(self):
        with system_world(draw=True) as w:
            Rect(center=(200, 150), width=400, height=300, color="#4080c0")
            a = Ellipse(center=(130, 150), width=90, height=90, color="#d04020")
            b = Ellipse(center=(270, 150), width=90, height=90, color="#d04020")
            a.blend, b.blend = "multiply", "screen"
            blur = Blur(1)
            a.fill_filter = blur
            b.fill_filter = blur
            px = frame(w)
        multiply = np.array([0x40 * 0xd0 // 255, 0x80 * 0x40 // 255, 0xc0 * 0x20 // 255])
        screen = 255 - (255 - np.array([0x40, 0x80, 0xc0])) * (255 - np.array([0xd0, 0x40, 0x20])) // 255
        self.assertLess(int(np.abs(px[150, 130] - multiply).max()), 24, px[150, 130])
        self.assertLess(int(np.abs(px[150, 270] - screen).max()), 24, px[150, 270])


if __name__ == "__main__":
    unittest.main()
