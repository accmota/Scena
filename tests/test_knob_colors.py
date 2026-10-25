"""A colour knob written after construction takes any colour form (KC1).

Background fields and screen effects resolve ``color=`` once, in the
constructor, into the float triple their shader reads. ``plasma.color =
SKY.get_color(t)`` (a ``Color``, written each frame from ``update``) stored
the raw value, and the next draw raised ``'Color' object is not iterable``;
a colour name was worse: the shader read the letters of the string.

Bug class guarded: every public ``BackgroundField`` and ``PostEffect`` kind,
every public knob that holds an RGB(A) float tuple after construction, takes
a name, a ``Color`` and a ``Colormap`` colour (``color_knob_setattr``).

Run:

    python tests/run_tiers.py focused test_knob_colors
"""
import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import skia

import scena
from scena import Color, Colormap, Plasma, init
from scena.background import BackgroundField, CameraSample
from scena.postfx import PostEffect
from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()


def public_kinds(base):
    kinds = []
    for name in scena.__all__:
        obj = getattr(scena, name)
        if inspect.isclass(obj) and issubclass(obj, base) and obj is not base:
            kinds.append(obj)
    return kinds


def colour_knobs(obj):
    """Public knobs holding an RGB(A) float tuple: what a shader reads as a colour."""
    return {k: v for k, v in vars(obj).items()
            if not k.startswith("_") and type(v) is tuple and len(v) in (3, 4)
            and all(isinstance(x, float) for x in v)}


def build(kind):
    """A zero-arg instance that is not left on the canvas."""
    if issubclass(kind, BackgroundField):
        return kind.temp(), None
    fx = kind()
    return fx, fx.remove


class TestColourKnobsTakeAnyColour(unittest.TestCase):
    def setUp(self):
        init(width=320, height=200)

    def test_every_colour_knob_takes_a_name_a_color_and_a_colormap_colour(self):
        ramp = Colormap.from_colors("navy", "gold")
        seen = 0
        for kind in public_kinds(BackgroundField) + public_kinds(PostEffect):
            try:
                obj, undo = build(kind)
            except TypeError:
                continue        # a kind that needs arguments (Wallpaper(image))
            try:
                for name, old in colour_knobs(obj).items():
                    seen += 1
                    with self.subTest(kind=kind.__name__, knob=name):
                        setattr(obj, name, "red")
                        self.assertEqual(getattr(obj, name)[:3], (1.0, 0.0, 0.0))
                        setattr(obj, name, Color("blue"))
                        self.assertEqual(getattr(obj, name)[:3], (0.0, 0.0, 1.0))
                        mid = ramp.get_color(0.5)
                        setattr(obj, name, mid)
                        got = getattr(obj, name)
                        self.assertEqual(len(got), len(old))
                        for a, b in zip(got[:3], mid.rgb):
                            self.assertAlmostEqual(a, b)
                        if len(old) == 4:
                            self.assertEqual(got[3], old[3])     # a name keeps the knob's alpha
            finally:
                if undo is not None:
                    undo()
        # the walk must reach the kinds this was found on (and many more)
        self.assertGreater(seen, 25)

    def test_written_colour_draws(self):
        sky = Plasma.temp(color="navy", speed=0, alpha=1.0)
        sky.color = Colormap.from_colors("navy", "gold").get_color(1.0)
        surf = skia.Surface(64, 64)
        cam = CameraSample(0.0, 0.0, 1.0, 0.0, rest_x=0.0, rest_y=0.0)
        sky.draw(surf.getCanvas(), 64, 64, 0.0, cam, design_width=64, design_height=64)
        px = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
        r, g, b = (int(v) for v in px[32, 32][:3])
        self.assertGreater(r + g, 2 * b)        # gold, not navy

    def test_other_writes_are_unchanged(self):
        sky = Plasma.temp(color="navy")
        sky.color = (0.25, 0.5, 0.75)           # a tuple passes as before
        self.assertEqual(sky.color, (0.25, 0.5, 0.75))
        sky.amount = 0.3
        self.assertEqual(sky.amount, 0.3)
        with self.assertRaises(AttributeError):  # still a closed surface
            sky.colour = "red"


if __name__ == "__main__":
    unittest.main()
