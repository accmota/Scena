"""
A colour that changes every frame recolours the built paints in place and
still paints the colour it names.

A colour formula rebuilt both Skia paints every frame (and re-derived the
outline tone): ~22 µs an object, 126 triangles at 63 fps against 180 still
(showcase D4, 2026-10-23). A plain colour replacing a plain colour now sets
the colour on the paints already built (``PaintState._recolor_cached_paints``).

Guarded here, in pixels: a linked colour, a ``=`` each frame, a shape with a
fill filter (its filtered paint is the one drawn), a line-type shape, and a
switch from a colour to a Gradient and back all draw the current colour.

Bug class guarded: a paint cache kept across a write that changed more than
the colour (a shader, a filter), or a colour write that left a stale paint.

Run:

    python tests/run_tiers.py focused test_color_link_paint
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

from scena import Blur, Color, Gradient, Line, Rect, st  # noqa: E402
from tests.leftovers import module_sweep  # noqa: E402

boot()
setUpModule, tearDownModule = module_sweep()

SEQ = ["red", "lime", "blue", "yellow"]


def pixel(w, x, y):
    w.step(1, dt=FRAME)
    img = w.surface.makeImageSnapshot()
    info = skia.ImageInfo.Make(img.width(), img.height(),
                               skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
    buf = bytearray(img.width() * img.height() * 4)
    assert img.readPixels(info, buf, img.width() * 4, 0, 0)
    a = np.frombuffer(bytes(buf), np.uint8).reshape(img.height(), img.width(), 4)
    return tuple(int(v) for v in a[y, x, :3])


def want(name):
    c = Color(name)
    return tuple(int(round(v * 255)) for v in c.rgb[:3])


class TestColourChangesDraw(unittest.TestCase):
    def assertNear(self, got, expected, tol=40):
        self.assertTrue(all(abs(g - e) <= tol for g, e in zip(got, expected)),
                        f"{got} != {expected}")

    def test_linked_colour_each_frame(self):
        with system_world(draw=True) as w:
            st.i = 0
            r = Rect(center=(200, 150), width=80, height=80)
            r["color"] @= lambda: SEQ[st.i % len(SEQ)]
            for i in range(8):
                st.i = i
                self.assertNear(pixel(w, 200, 150), want(SEQ[i % len(SEQ)]))

    def test_assigned_colour_each_frame_with_a_fill_filter(self):
        with system_world(draw=True) as w:
            r = Rect(center=(200, 150), width=120, height=120)
            r.fill_filter = Blur(1)
            for i in range(8):
                r.color = SEQ[i % len(SEQ)]
                self.assertNear(pixel(w, 200, 150), want(SEQ[i % len(SEQ)]))

    def test_line_type_shape(self):
        with system_world(draw=True) as w:
            ln = Line(p1=(140, 150), p2=(260, 150), line_width=10)
            for i in range(6):
                ln.color = SEQ[i % len(SEQ)]
                self.assertNear(pixel(w, 200, 150), want(SEQ[i % len(SEQ)]))

    def test_colour_gradient_colour(self):
        with system_world(draw=True) as w:
            r = Rect(center=(200, 150), width=120, height=40)
            r.color = "red"
            self.assertNear(pixel(w, 200, 150), want("red"))
            r.color = Gradient("blue", "blue")
            self.assertNear(pixel(w, 200, 150), want("blue"))
            r.color = "lime"
            self.assertNear(pixel(w, 200, 150), want("lime"))
            r.color = "red"
            self.assertNear(pixel(w, 200, 150), want("red"))


def frame_pixels(w):
    w.step(1, dt=FRAME)
    img = w.surface.makeImageSnapshot()
    info = skia.ImageInfo.Make(img.width(), img.height(),
                               skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
    buf = bytearray(img.width() * img.height() * 4)
    assert img.readPixels(info, buf, img.width() * 4, 0, 0)
    return np.frombuffer(bytes(buf), np.uint8).reshape(img.height(), img.width(), 4)[:, :, :3].astype(int)


class TestGradientResize(unittest.TestCase):
    def test_a_growing_gradient_draws_as_one_built_at_that_size(self):
        # Showcase D5: a size change swaps the re-fitted shader on the cached
        # paint. The picture must be the one a fresh paint gives.
        from scena import Circle
        with system_world(draw=True) as w:
            c = Circle(center=(200, 150), radius=20, visual=Gradient("red", "blue", type="radial"))
            for r in (24, 31, 37.5, 52, 60):
                c.radius = r
                frame_pixels(w)
            grown = frame_pixels(w)
            c.destroy()
            fresh = Circle(center=(200, 150), radius=60, visual=Gradient("red", "blue", type="radial"))
            built = frame_pixels(w)
            fresh.destroy()
        off = (np.abs(grown - built).max(axis=2) > 8).sum()
        self.assertLess(off, 5, f"{off} pixels differ")


if __name__ == "__main__":
    unittest.main()
