"""Which visuals take ``color=``, and what ``set_color`` does under each role.

Rule (Effect System Design, "Which visuals take color="): a visual takes
``color`` as its first parameter when it paints a color of its own (body,
rim, glow, trail) or redraws the host body (Beat, Liquify). Procedural
materials (Role D) and pixel operators do not. Under a Role D look
``set_color`` is kept but hidden: it warns once per look class, and
``.color`` reads the author's color, not a fallback.
"""

from __future__ import annotations

import inspect
import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import skia

import scena
from scena import Beat, Circle, Liquify, Neon, Sprite
from scena import recipes as _recipes
from scena import style as _style
from scena.visuals import Visual

# Visuals that take no ``color=`` on purpose. A new visual lands either here
# (with its reason) or with ``color`` as its first parameter.
_NO_COLOR = {
    # Procedural materials: the material is the color (Role D).
    "Flame": "material", "Swell": "material", "Water": "material",
    # Pixel operators: transform pixels that already exist.
    "Grayscale": "pixels", "HueShift": "pixels (to=)", "Recolor": "pixels (key=, to=)",
    "EmissiveBloom": "pixels",
    # Bases, not looks.
    "Visual": "base", "Recipe": "base",
}


def _public_visual_classes():
    out = []
    for name in scena.__all__:
        obj = getattr(scena, name, None)
        if inspect.isclass(obj) and issubclass(obj, Visual):
            out.append(obj)
    return out


def _rgb(shape):
    return tuple(round(float(v), 3) for v in tuple(shape.color.rgb)[:3])


def _draw(shape):
    surf = skia.Surface(128, 128)
    cnv = surf.getCanvas()
    cnv.clear(skia.ColorBLACK)
    shape.draw(cnv)
    return surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType).astype(int)


class TestWhoTakesColor(unittest.TestCase):
    def test_every_visual_takes_color_or_is_listed(self):
        """Bug class: a new look ships without color= by accident (Beat did)."""
        for cls in _public_visual_classes():
            name = cls.__name__
            with self.subTest(visual=name):
                params = [
                    p for p in inspect.signature(cls.__init__).parameters.values()
                    if p.name != "self"
                ]
                names = [p.name for p in params]
                if name in _NO_COLOR:
                    self.assertNotIn("color", names, f"{name} now takes color: drop it from _NO_COLOR")
                    continue
                self.assertIn("color", names, f"{name}: add color= or list it in _NO_COLOR with a reason")

    def test_listed_materials_are_role_d(self):
        for name, why in _NO_COLOR.items():
            if why != "material":
                continue
            with self.subTest(visual=name):
                self.assertEqual(getattr(scena, name)()._color_role, "D")


class TestBeatLiquifyColor(unittest.TestCase):
    LOOKS = (Beat, Liquify)

    def test_color_is_first_positional(self):
        for cls in self.LOOKS:
            with self.subTest(visual=cls.__name__):
                self.assertIs(cls("red"), cls(color="red"))
                self.assertIs(cls(), cls(None))
                self.assertIsNot(cls("red"), cls())

    def test_old_positional_amount_raises_with_fix(self):
        for cls in self.LOOKS:
            for bad in (0.1, 3):
                with self.subTest(visual=cls.__name__, arg=bad):
                    with self.assertRaises(TypeError) as cm:
                        cls(bad)
                    msg = str(cm.exception)
                    self.assertIn("first argument is color", msg)
                    self.assertIn(f"{cls.__name__}(amount={bad!r})", msg)
                self.assertEqual(cls(amount=0.1).amount, 0.1)

    def test_unseeded_keeps_host_color(self):
        for cls in self.LOOKS:
            with self.subTest(visual=cls.__name__):
                c = Circle(color="blue")
                c.visual = cls()
                self.assertEqual(_rgb(c), (0.0, 0.0, 1.0))
                self.assertEqual(cls()._color_role, "E")

    def test_seed_paints_body_like_neon(self):
        for cls in self.LOOKS + (Neon,):
            with self.subTest(visual=cls.__name__):
                c = Circle(color="blue")
                c.visual = cls("red")
                self.assertEqual(_rgb(c), (1.0, 0.0, 0.0))
                c.visual = None
                self.assertEqual(_rgb(c), (1.0, 0.0, 0.0), "visual=None keeps the seed")

    def test_set_color_after_seed_wins_and_unseeds(self):
        for cls in self.LOOKS:
            with self.subTest(visual=cls.__name__):
                c = Circle(color="blue")
                c.visual = cls("red", amount=0.2)
                c.set_color(0, 1, 0)
                self.assertEqual(_rgb(c), (0.0, 1.0, 0.0))
                self.assertIsNone(c.visual._seed_color)
                self.assertIs(c.visual, cls(amount=0.2))
                c.visual = None
                self.assertEqual(_rgb(c), (0.0, 1.0, 0.0))

    def test_seed_shows_in_pixels(self):
        _recipes_clock = _recipes._clock
        _recipes._clock = lambda: 0.37
        try:
            for cls in self.LOOKS:
                with self.subTest(visual=cls.__name__):
                    c = Circle(center=(64, 64), radius=40, color="blue")
                    c.visual = cls("red")
                    px = _draw(c)[64, 64]
                    self.assertGreater(px[0], 150, px)
                    self.assertLess(px[2], 80, px)
        finally:
            _recipes._clock = _recipes_clock

    def test_sprite_takes_beat_but_not_seeded_beat(self):
        s = Sprite()
        s.visual = Beat()
        with self.assertRaises(TypeError) as cm:
            s.visual = Beat("red")
        self.assertIn("HueShift(to=", str(cm.exception))
        self.assertIs(s.visual, Beat(), "rejected assignment keeps the previous visual")


class TestRecolorUnderOwnColors(unittest.TestCase):
    def setUp(self):
        _style._RECOLOR_HIDDEN_WARNED.clear()
        self._clock = _recipes._clock
        _recipes._clock = lambda: 0.37

    def tearDown(self):
        _recipes._clock = self._clock
        _style._RECOLOR_HIDDEN_WARNED.clear()

    def _assignable_role_de(self):
        """Every public visual whose zero-arg instance is Role D or E on a Circle."""
        out = []
        for cls in _public_visual_classes():
            if cls.__name__ in ("Visual", "Recipe"):
                continue
            try:
                look = cls()
                Circle().visual = look
            except TypeError:
                continue  # stamps (Tail) and Sprite-only looks
            if look._color_role in ("D", "E"):
                out.append(look)
        return out

    def test_role_matches_whether_set_color_shows(self):
        """Bug class: a look labelled D that draws the host (Liquify was), or the reverse.

        Role D means set_color is hidden; Role E means it shows.
        """
        looks = self._assignable_role_de()
        self.assertTrue(any(l._color_role == "D" for l in looks))
        self.assertTrue(any(l._color_role == "E" for l in looks))
        for look in looks:
            name = type(look).__name__
            with self.subTest(visual=name, role=look._color_role):
                c = Circle(center=(64, 64), radius=40, color="blue")
                c.visual = look
                before = _draw(c)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    c.set_color(0, 1, 0)
                changed = int((np.abs(before - _draw(c)).sum(axis=2) > 30).sum())
                if look._color_role == "D":
                    self.assertEqual(changed, 0, f"{name} is Role D but set_color showed")
                else:
                    self.assertGreater(changed, 500, f"{name} is Role E but set_color did not show")

    def test_role_d_set_color_warns_once_per_look(self):
        for cls in (scena.Flame, scena.Swell, scena.Water, scena.Shield):
            with self.subTest(visual=cls.__name__):
                c = Circle(color="blue")
                c.visual = cls()
                with warnings.catch_warnings(record=True) as got:
                    warnings.simplefilter("always")
                    c.set_color(0, 1, 0)
                    c.set_color("red")
                    Circle(color="blue", visual=None).set_color("red")
                    d = Circle(color="blue")
                    d.visual = cls()
                    d.set_color("green")
                hits = [w for w in got if cls.__name__ in str(w.message)]
                self.assertEqual(len(hits), 1, [str(w.message) for w in got])
                self.assertIs(hits[0].category, RuntimeWarning)
                self.assertIn("visual = None", str(hits[0].message))
                self.assertEqual(os.path.basename(hits[0].filename), os.path.basename(__file__))

    def test_no_warning_where_set_color_shows(self):
        for look in (Beat(), Liquify(), Neon(), scena.Halo(), None):
            with self.subTest(visual=type(look).__name__):
                c = Circle(color="blue")
                c.visual = look
                with warnings.catch_warnings(record=True) as got:
                    warnings.simplefilter("always")
                    c.set_color(0, 1, 0)
                self.assertEqual([str(w.message) for w in got], [])

    def test_color_reads_author_color_under_material(self):
        """``.color`` once read navy (0, 0, 0.5) under Flame / Swell."""
        for cls in (scena.Flame, scena.Swell, scena.Water, scena.Shield):
            with self.subTest(visual=cls.__name__):
                c = Circle(color="blue")
                c.visual = cls()
                self.assertEqual(_rgb(c), (0.0, 0.0, 1.0))
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    c.set_color(0, 1, 0)
                self.assertEqual(_rgb(c), (0.0, 1.0, 0.0))
                c.visual = None
                self.assertEqual(_rgb(c), (0.0, 1.0, 0.0))


if __name__ == "__main__":
    unittest.main()
