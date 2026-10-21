"""
Colors the engine builds from channels it already holds skip the author-input
parser, and come out exactly as the parser would have made them.

Found profiling ``examples/constelacao.py`` (2026-10-21): every point repaints
its thread every frame with ``CORES.get_color(x).with_alpha(near)``. Three
engine paths built a Color through ``Color(r, g, b, a)`` (``as_payload_all``
three times, ``_parse_color_args``, ``_validate_color_components``) from values
that were already valid floats in [0, 1]:

* ``Color.with_alpha`` (its own channels; the alpha is clamped first),
* ``Color.interpolate`` in RGB and OKLAB (both clamp), so ``Colormap.get_color``,
* ``style._coerce_channel_paint``, the copy a ``fill`` / ``line`` write keeps.

They now go through ``Color._unit`` (the derived-outline constructor since
2026-10-13). Measured: ``with_alpha`` 3.3 → 0.6 µs, ``get_color`` 6.1 → 3.3 µs,
the Constelação frame ~0.8 ms less (Effect System Design, "Engine-made
colours skip the parser").

Bug class guarded: **an engine-internal value rebuilt through the author-input
path** — correct, but paid per object per frame. Pinned two ways: the parser
is not called on these paths (a spy), and each result has exactly the
channels, ``_is_none`` and immutability the parser's result has.

Run:

    python tests/run_tiers.py focused test_color_fast_paths
"""
from __future__ import annotations

import os
import random
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scena.style as style_mod  # noqa: E402
from scena import Color, Colormap, ColorSpace, Line, Circle, canvas, init  # noqa: E402
from scena.color import _clamp01  # noqa: E402


def channels(c):
    return (c._r, c._g, c._b, c._a, c._is_none)


def slow_with_alpha(c, alpha):
    """What with_alpha returned before: the parser over its own channels."""
    return Color(c._r, c._g, c._b, _clamp01(float(alpha)))


def slow_interpolate(c1, c2, t, space):
    """What interpolate returned before, built by the parser."""
    if space == ColorSpace.RGB:
        return Color(*(_clamp01(x + (y - x) * t) for x, y in
                       zip(channels(c1)[:4], channels(c2)[:4])))
    l1, a1, b1 = Color._rgb_to_oklab(c1._r, c1._g, c1._b)
    l2, a2, b2 = Color._rgb_to_oklab(c2._r, c2._g, c2._b)
    r, g, b = Color._oklab_to_rgb(l1 + (l2 - l1) * t, a1 + (a2 - a1) * t, b1 + (b2 - b1) * t)
    return Color(r, g, b, _clamp01(c1._a + (c2._a - c1._a) * t))


def colours(rng, n):
    """Corners of the cube, names, and random channels (alpha too)."""
    out = [Color(r, g, b, a) for r in (0, 1) for g in (0, 1) for b in (0, 1) for a in (0, 1)]
    out += [Color(name) for name in ("cyan", "medium purple", "hot pink", "orange", "navy")]
    out += [Color(rng.random(), rng.random(), rng.random(), rng.random()) for _ in range(n)]
    return out


class TestSameColorAsTheParser(unittest.TestCase):
    def test_with_alpha(self):
        rng = random.Random(1)
        for c in colours(rng, 60) + [Color(None)]:
            for alpha in (0, 1, 0.5, -0.3, 1.7, rng.random(), 1e-9):
                with self.subTest(c=c, alpha=alpha):
                    self.assertEqual(channels(c.with_alpha(alpha)), channels(slow_with_alpha(c, alpha)))

    def test_interpolate_rgb_and_oklab(self):
        rng = random.Random(2)
        cs = colours(rng, 30)
        ts = (0.0, 1.0, 0.5, -0.4, 1.6, 1e-12) + tuple(rng.random() for _ in range(6))
        for space in (ColorSpace.RGB, ColorSpace.OKLAB):
            for _ in range(200):
                c1, c2 = rng.choice(cs), rng.choice(cs)
                for t in ts:
                    fast = Color.interpolate(c1, c2, t, space)
                    self.assertEqual(channels(fast), channels(slow_interpolate(c1, c2, t, space)),
                                     (space, c1, c2, t))

    def test_colormap_get_color(self):
        ramp = Colormap.from_colors("cyan", "medium purple", "hot pink", "orange")
        stops = [c for _p, c in ramp._colors]
        for i in range(301):
            t = i / 300
            k = min(int(t * 3), 2)
            u = t * 3 - k
            want = slow_interpolate(stops[k], stops[k + 1], u, ColorSpace.OKLAB)
            got = ramp.get_color(t)
            # the ramp's own segment arithmetic may differ in the last bit of u
            for a, b in zip(channels(got)[:4], channels(want)[:4]):
                self.assertAlmostEqual(a, b, places=12)

    def test_results_are_sealed_colors(self):
        c = Color("tomato")
        for made in (c.with_alpha(0.5), Color.interpolate(c, Color("navy"), 0.3),
                     style_mod._coerce_channel_paint(c)):
            self.assertIs(type(made), Color)
            with self.assertRaises(AttributeError):
                made.alpha = 0.2
            with self.assertRaises(AttributeError):     # sealed like a parsed Color
                made.tint = 0.1

    def test_a_subclass_still_gets_its_own_class(self):
        class Tinta(Color):
            pass
        made = Tinta.interpolate(Tinta("red"), Tinta("blue"), 0.5)
        self.assertIs(type(made), Tinta)


class TestPaintCoercionCopies(unittest.TestCase):
    def test_copy_equals_the_parser_copy(self):
        rng = random.Random(3)
        for c in colours(rng, 40) + [Color(None)]:
            got = style_mod._coerce_channel_paint(c)
            self.assertEqual(channels(got), channels(Color(c)))
            self.assertIsNot(got, c)

    def test_other_materials_unchanged(self):
        self.assertIsNone(style_mod._coerce_channel_paint(None))
        self.assertEqual(channels(style_mod._coerce_channel_paint("red")), channels(Color("red")))
        self.assertEqual(channels(style_mod._coerce_channel_paint((0.2, 0.4, 0.6))),
                         channels(Color(0.2, 0.4, 0.6)))


class TestTheParserIsNotCalled(unittest.TestCase):
    """The spy: these paths must not reach the author-input parser."""

    def setUp(self):
        init(width=800, height=600)
        canvas.reset_view()
        self.ramp = Colormap.from_colors("cyan", "orange")
        self.line = Line(p1=(10, 10), p2=(200, 120), color="white")
        self.ball = Circle(center=(300, 300), radius=10)

    def tearDown(self):
        self.line.destroy()
        self.ball.destroy()

    def test_per_frame_repaint(self):
        cores = [self.ramp.get_color(i / 9) for i in range(10)]
        with mock.patch.object(Color, "_parse_color_args",
                               side_effect=AssertionError("parsed")) as spy:
            for i in range(10):
                c = self.ramp.get_color(i / 9).with_alpha(0.1 * i)
                self.line.color = c
                self.ball.fill = cores[i]
            self.assertEqual(spy.call_count, 0)
        self.assertEqual(channels(self.line.line)[:4], channels(c)[:4])
        self.assertIsNot(self.line.line, c)
        self.assertEqual(channels(self.ball.fill), channels(cores[-1]))

    def test_author_input_is_still_parsed(self):
        with mock.patch.object(Color, "_parse_color_args", wraps=Color._parse_color_args) as spy:
            self.line.color = "red"
            Color(0.1, 0.2, 0.3)
        self.assertGreaterEqual(spy.call_count, 2)
        with self.assertRaises(ValueError):
            self.line.color = (2, 0, 0)


if __name__ == "__main__":
    unittest.main()
