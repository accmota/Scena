"""
Aura and EmissiveBloom on every Shape kind.

Both were Sprite-only until 2026-10-27, with no reason of principle: an Aura
is a band along the outline and a bloom lights what is bright, and a Shape has
both an outline and a body. On a Shape the Aura band is the outline stroked
and blurred to the Sprite shader's Gaussian (``visuals._draw_shape_aura``), and
the bloom filter goes on the fill and on the outline (a Line is all outline).
The looks that stay Sprite-only change the image's pixels (HueShift,
Grayscale, Recolor).

Bug class guarded: a look that draws through ``_geometry_draw`` with its own
paint and a kind that ignores the paint (or has no outline), leaving the look
invisible on that kind.

Run:

    python tests/run_tiers.py focused test_shape_pixel_looks
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import numpy as np  # noqa: E402

from system_support import boot, system_world  # noqa: E402
from test_look_group_body import pixels  # noqa: E402

from scena import (  # noqa: E402
    Aura, Circle, Concave, EmissiveBloom, Ellipse, Grayscale, HueShift, Line,
    Polygon, Rect, Recolor, RegularPolygon, Square, Track, Triangle,
)
from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()

boot()

# Every exported Shape kind that draws (Point and Anchor are markers), each
# about 70 units across, centred on (x, y).
KINDS = {
    "Line": lambda x, y, **k: Line(p1=(x - 35, y - 10), p2=(x + 35, y + 10), line_width=4, **k),
    "Rect": lambda x, y, **k: Rect(center=(x, y), width=70, height=40, angle=15, **k),
    "Square": lambda x, y, **k: Square(center=(x, y), length=50, **k),
    "Concave": lambda x, y, **k: Concave(center=(x, y), width=70, height=50, **k),
    "Circle": lambda x, y, **k: Circle(center=(x, y), radius=32, **k),
    "Circle arc": lambda x, y, **k: Circle(center=(x, y), radius=32, spread=200, **k),
    "Ellipse": lambda x, y, **k: Ellipse(center=(x, y), width=70, height=36, **k),
    "Polygon": lambda x, y, **k: Polygon(
        points=[(x - 35, y - 25), (x + 30, y - 30), (x + 10, y), (x + 35, y + 30), (x - 30, y + 20)], **k),
    "RegularPolygon": lambda x, y, **k: RegularPolygon(center=(x, y), radius=34, n=6, **k),
    "Triangle": lambda x, y, **k: Triangle(center=(x, y), radius=36, **k),
    "Track closed": lambda x, y, **k: Track.star(center=(x, y), radius=36, line_width=3, **k),
    "Track open": lambda x, y, **k: Track.line(p1=(x - 35, y - 20), p2=(x + 35, y + 20), line_width=3, **k),
}

PLAIN_X, LOOK_X, Y = 100, 300, 150
HALF = 90       # the crop around each centre


def _crops(px):
    import scena
    row = int(scena.canvas.height) - Y     # y-up design units, 1:1 from the top-left
    def crop(x):
        return px[row - HALF:row + HALF, x - HALF:x + HALF].astype(int)
    return crop(PLAIN_X), crop(LOOK_X)


def _render_pair(make, look, color):
    """The same kind drawn plain (left) and with ``look`` (right)."""
    with system_world(draw=True) as w:
        make(PLAIN_X, Y, color=color)
        shape = make(LOOK_X, Y, color=color)
        shape.visual = look
        return _crops(pixels(w))


class TestAuraOnEveryShapeKind(unittest.TestCase):
    def test_band_shows_around_the_body(self):
        for name, make in KINDS.items():
            with self.subTest(kind=name):
                plain, aura = _render_pair(make, Aura("cyan"), "#2040c0")
                added = np.clip(aura - plain, 0, 255)
                lit = (added[:, :, 1] > 40) & (added[:, :, 2] > 40)
                self.assertGreater(int(lit.sum()), 400, f"{name}: no Aura band")
                # Cyan, not the body's blue: green rises with blue.
                self.assertGreater(int(added[:, :, 1].sum()), int(added[:, :, 0].sum()) * 2)

    def test_body_is_drawn_over_the_band(self):
        plain, aura = _render_pair(KINDS["Circle"], Aura("cyan"), "#2040c0")
        self.assertTrue(np.array_equal(plain[HALF, HALF], aura[HALF, HALF]))

    def test_amount_and_width_take_effect(self):
        _p, base = _render_pair(KINDS["Rect"], Aura("cyan"), "#2040c0")
        _p, strong = _render_pair(KINDS["Rect"], Aura("cyan", amount=2.0), "#2040c0")
        _p, wide = _render_pair(KINDS["Rect"], Aura("cyan", width=0.7), "#2040c0")
        self.assertGreater(int(strong.sum()), int(base.sum()))
        self.assertGreater(int((wide.sum(axis=2) > 60).sum()), int((base.sum(axis=2) > 60).sum()))


    def test_band_turns_and_resizes_with_the_shape(self):
        # Written after the look: the band is the one a shape built so draws.
        def one(build):
            with system_world(draw=True) as w:
                build()
                return _crops(pixels(w))[1]
        cases = {
            "angle": (lambda: setattr(_aura(Rect(center=(LOOK_X, Y), width=70, height=30)), "angle", 40),
                      lambda: _aura(Rect(center=(LOOK_X, Y), width=70, height=30, angle=40))),
            "width": (lambda: setattr(_aura(Rect(center=(LOOK_X, Y), width=70, height=30)), "width", 120),
                      lambda: _aura(Rect(center=(LOOK_X, Y), width=120, height=30))),
            "scale": (lambda: setattr(_aura(Circle(center=(LOOK_X, Y), radius=30)), "scale", 2),
                      lambda: _aura(Circle(center=(LOOK_X, Y), radius=60))),
        }
        for name, (after, fresh) in cases.items():
            with self.subTest(change=name):
                a, b = one(after), one(fresh)
                self.assertGreater(int((np.abs(b - one(lambda: None)).sum(axis=2) > 40).sum()), 400)
                self.assertEqual(int(np.abs(a - b).max()), 0)


def _aura(shape):
    shape.color = "#2040c0"
    shape.visual = Aura("cyan")
    return shape


class TestEmissiveBloomOnEveryShapeKind(unittest.TestCase):
    def test_bright_body_blooms(self):
        for name, make in KINDS.items():
            with self.subTest(kind=name):
                plain, bloom = _render_pair(make, EmissiveBloom(), "#ffd040")
                added = np.clip(bloom - plain, 0, 255).sum(axis=2)
                self.assertGreater(int((added > 20).sum()), 300, f"{name}: no bloom")

    def test_line_filter_follows_the_body(self):
        with system_world(draw=True):
            line = Line(p1=(0, 0), p2=(50, 0))
            ring = Circle(center=(0, 0), radius=10)
            for s in (line, ring):
                s.visual = EmissiveBloom()
                self.assertIsNotNone(s.fill_filter)
                self.assertIs(s.line_filter, s.fill_filter)
                s.visual = None
                self.assertIsNone(s.fill_filter)
                self.assertIsNone(s.line_filter)


class TestPixelLooksStaySpriteOnly(unittest.TestCase):
    """The looks that change an image's pixels still refuse a Shape: a Shape's
    color is chosen, not recolored."""

    def test_refused(self):
        c = Circle(center=(0, 0), radius=10)
        self.addCleanup(c.destroy)
        with self.assertRaises(TypeError):
            c.visual = Recolor()
        for stamp in (HueShift(0.3), Grayscale()):
            with self.assertRaises(TypeError):
                c.visual = stamp


# The looks a Sprite refuses (on an image they would hide it) and the one a
# Shape refuses (it changes an image's pixels); every other `.visual` look of
# scena.__all__ wears both. Stamps (Glow, Shadow, HueShift, …) go on their own
# fields. The CHANGELOG (0.11.0) and Effect System Design name these lists.
SHAPE_ONLY = {"Paint", "Fill", "Stroke", "Neon", "Gel", "Sphere", "Water",
              "Liquify", "InsetRim", "Bolt"}
SPRITE_ONLY = {"Recolor"}
STAMPS = {"Glow", "CheapGlow", "Shadow", "HueShift", "Grayscale", "Tail"}


class TestWhichHostWearsWhichLook(unittest.TestCase):
    """RA4: the 0.11.0 CHANGELOG first said "looks that paint the body are
    for Shapes", but Metal, Aurora, Wave and Extrude paint a body and wear a
    Sprite. Bug class: a rule stated for a family of looks that no test
    enumerates. Every public look is tried on both hosts."""

    def test_every_public_look_on_both_hosts(self):
        import scena
        from scena import Sprite
        from scena.visuals import Visual
        looks = {n for n in scena.__all__
                 if isinstance(getattr(scena, n), type)
                 and issubclass(getattr(scena, n), Visual)
                 and n not in ("Visual", "Recipe") and n not in STAMPS}
        self.assertTrue(SHAPE_ONLY | SPRITE_ONLY <= looks)
        for name in sorted(looks):
            cls = getattr(scena, name)
            with self.subTest(look=name):
                wears = {}
                for host, make in (("shape", lambda: Circle(center=(0, 0), radius=10)),
                                   ("sprite", lambda: Sprite(center=(0, 0), size=20))):
                    obj = make()
                    self.addCleanup(obj.destroy)
                    try:
                        obj.visual = cls()
                        wears[host] = True
                    except TypeError as e:
                        wears[host] = False
                        other = "shape" if host == "sprite" else "sprite"
                        self.assertIn(other, str(e).lower(), "the refusal names the other host")
                self.assertEqual(wears["shape"], name not in SPRITE_ONLY)
                self.assertEqual(wears["sprite"], name not in SHAPE_ONLY)


if __name__ == "__main__":
    unittest.main()
