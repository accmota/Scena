"""Texture materials on shapes keep drawing the shared image (no per-paint copy)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import skia

from scena import init, Line, Rect
from scena.style import Texture


class TestTextureImageIdentity(unittest.TestCase):
    """Shape paints of a Texture sample the Texture's own ``skia.Image``.

    skia-python's ``Paint.setShader`` deep-copies the shader into a new
    ``skia.Image`` (new uniqueID → GPU texture cache miss → the file decodes
    again for every shape paint; a raster image is re-encoded to PNG). Shape
    paints must share it instead (``skia.Paint(Shader=...)``). A raster image
    over a mutable numpy buffer tells the two apart: a copy keeps the old
    pixels, the shared image shows the edit.
    """

    def setUp(self):
        init(width=400, height=300)
        self.pixels = np.zeros((16, 16, 4), dtype=np.uint8)
        self.pixels[...] = (255, 0, 0, 255)
        self.image = skia.Image.fromarray(
            self.pixels, colorType=skia.kRGBA_8888_ColorType,
            alphaType=skia.kPremul_AlphaType, copy=False,
        )

    def _center_rgba(self, paint, stroke=False):
        surf = skia.Surface.MakeRaster(skia.ImageInfo.MakeN32Premul(60, 60))
        c = surf.getCanvas()
        c.clear(skia.ColorWHITE)
        c.translate(30, 30)
        if stroke:
            c.drawLine(-25, 0, 25, 0, paint)
        else:
            c.drawRect(skia.Rect.MakeLTRB(-20, -10, 20, 10), paint)
        r, g, b, a = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)[30, 30]
        return int(r), int(g), int(b), int(a)

    def _paints(self):
        cover = Texture(image=self.image)
        tile = Texture(image=self.image, fit="tile", tile_size=8)
        small = Rect(center=(100, 100), width=40, height=20)
        big = Rect(center=(200, 100), width=90, height=50)
        tiled = Rect(center=(100, 200), width=40, height=20)
        line = Line(p1=(10, 250), p2=(120, 250))
        small.fill = cover
        big.fill = cover
        tiled.fill = tile
        line.line = cover
        line.line_width = 12
        return [
            (small._to_skia_fill_paint(), False),
            (big._to_skia_fill_paint(), False),
            (tiled._to_skia_fill_paint(), False),
            (line._to_skia_line_paint(), True),
        ]

    def test_shape_paints_sample_the_texture_image(self):
        paints = self._paints()
        for paint, stroke in paints:
            self.assertEqual(self._center_rgba(paint, stroke), (255, 0, 0, 255))
        self.pixels[...] = (0, 0, 255, 255)
        for i, (paint, stroke) in enumerate(paints):
            with self.subTest(paint=i):
                self.assertEqual(self._center_rgba(paint, stroke), (0, 0, 255, 255))


if __name__ == "__main__":
    unittest.main()
