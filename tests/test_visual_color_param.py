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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def _public_visual_classes():
    out = []
    for name in scena.__all__:
        obj = getattr(scena, name, None)
        if inspect.isclass(obj) and issubclass(obj, Visual):
            out.append(obj)
    return out


def _rgb(shape):
    return tuple(round(float(v), 3) for v in tuple(shape.color.rgb)[:3])


def _nebula_shield():
    """A Shield style that paints its own palette and takes no color (Role D)."""
    return scena.Shield(style="nebula")


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
        for cls in (scena.Flame, scena.Swell, scena.Water, _nebula_shield):
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
                hits = [w for w in got if type(d.visual).__name__ in str(w.message)]
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
        for cls in (scena.Flame, scena.Swell, scena.Water, _nebula_shield, scena.Shield, scena.Metal):
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


# Seeded looks where ``set_color`` still loses to the seed: the colour is
# written to the shape and shows after ``visual = None``, but the look keeps
# drawing the seed (no ``_unseed`` yet: "Phase 2", Effect System Design §9).
# Outline looks (Rim, Ink, …) repaint the body and keep the seeded outline,
# which a changed-pixel count mistakes for "shows": compare with the look
# worn on the new colour instead.
# Shrink-only: a look that starts to show set_color must leave the list.
SEED_WINS = {
    ("Aurora", None), ("Bolt", "core"), ("Bolt", "filaments"), ("Bolt", "tesla"),
    ("DashRing", None), ("ElectricBolt", None), ("ElectricField", None),
    ("Extrude", None), ("GearShell", None), ("Gel", None), ("Halo", "line"),
    ("Ink", None), ("InkBleed", None), ("InsetRim", None), ("Laser", None),
    ("MultiBorder", None), ("OrganicOutline", None), ("Rim", None),
    ("Shield", "bands"), ("Shield", "vortex"), ("Shield", "plasma"),
    ("Sphere", None), ("Tracer", None), ("Wave", None),
}


def _wearable_cells():
    """(class, style) for every public look a Circle can wear, every style."""
    from tests.test_knobs_take_effect import shape_visuals, _styles
    for name in shape_visuals():
        cls = getattr(scena, name)
        for style in _styles(cls):
            yield cls, style


def _takes_color(cls, style) -> bool:
    if "color" not in inspect.signature(cls.__init__).parameters:
        return False
    try:
        cls("deepskyblue", **({} if style is None else {"style": style}))
    except TypeError:
        return False            # refused on this style (KN4)
    return True


def _recolor_shows(look) -> tuple:
    """(pixels changed by set_color, warnings) for a blue Circle wearing ``look``."""
    c = Circle(center=(64, 64), radius=40, color="blue")
    try:
        c.visual = look
        before = _draw(c)
        with warnings.catch_warnings(record=True) as got:
            warnings.simplefilter("always")
            c.set_color(0, 1, 0)
        changed = int((np.abs(before - _draw(c)).sum(axis=2) > 30).sum())
        return changed, [str(w.message) for w in got]
    finally:
        c.destroy()


def _worn(look, color):
    c = Circle(center=(64, 64), radius=40, color=color)
    try:
        c.visual = look
        return _draw(c)
    finally:
        c.destroy()


def _recolored(look, color):
    c = Circle(center=(64, 64), radius=40, color="blue")
    try:
        c.visual = look
        c.set_color(color)
        return _draw(c)
    finally:
        c.destroy()


class TestSetColorShowsWhereColorIsTaken(unittest.TestCase):
    """Rule (2026-10-13): a look that takes ``color=`` shows ``set_color``; a
    look that takes none paints its own colors and warns.

    Bug class: ``Metal()`` / ``Metal("gold")`` + ``set_color`` changed nothing
    and said nothing (labelled Role A); the role test above only looked at
    zero-arg Role D / E looks, on the default style.
    """

    def setUp(self):
        _style._RECOLOR_HIDDEN_WARNED.clear()
        self._clock = _recipes._clock
        _recipes._clock = lambda: 0.37

    def tearDown(self):
        _recipes._clock = self._clock
        _style._RECOLOR_HIDDEN_WARNED.clear()

    def test_unseeded_every_look_and_style(self):
        cells = list(_wearable_cells())
        self.assertGreater(len(cells), 30, "the sweep stopped reaching the surface")
        for cls, style in cells:
            base = {} if style is None else {"style": style}
            with self.subTest(visual=cls.__name__, style=style), warnings.catch_warnings():
                warnings.simplefilter("ignore")
                look = cls(**base)
            _style._RECOLOR_HIDDEN_WARNED.clear()
            changed, warned = _recolor_shows(look)
            with self.subTest(visual=cls.__name__, style=style):
                if _takes_color(cls, style):
                    self.assertGreater(changed, 500, "takes color= but set_color did not show")
                    self.assertEqual(warned, [])
                    self.assertNotEqual(look._color_role, "D")
                else:
                    self.assertEqual(changed, 0, "takes no color but set_color showed")
                    self.assertEqual(look._color_role, "D")
                    self.assertTrue(any("paints its own colors" in w for w in warned), warned)

    def test_seeded_every_look_and_style(self):
        shows, hidden = set(), set()
        for cls, style in _wearable_cells():
            if not _takes_color(cls, style):
                continue
            base = {} if style is None else {"style": style}
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                got = _recolored(cls("deepskyblue", **base), "lime")
                # Shown = what the look draws on a lime shape: the unseeded
                # look (tint looks) or the look given lime (palette / paint).
                want = (_worn(cls(**base), "lime"), _worn(cls("lime", **base), "blue"))
            ok = any(np.abs(got - w).max() <= 2 for w in want)
            (shows if ok else hidden).add((cls.__name__, style))
        self.assertIn(("Neon", None), shows)
        unlisted = sorted(hidden - SEED_WINS, key=str)
        self.assertFalse(unlisted, f"seeded looks where set_color does not show: {unlisted}")
        stale = sorted(SEED_WINS & shows, key=str)
        self.assertFalse(stale, f"SEED_WINS looks that now show set_color: remove them: {stale}")

    def test_canary_metal_recolor_silent_again(self):
        import diff_support
        from scena.recipes import Metal
        diff_support.assert_catches(
            self, "test_visual_color_param.TestSetColorShowsWhereColorIsTaken.test_unseeded_every_look_and_style",
            [(Metal, "_unseed", lambda self: None)],
            "Metal() + set_color that changes nothing (before 2026-10-13)")


class TestPaletteLooks(unittest.TestCase):
    """Metal and Shield(style="bubble"): own palette without color=, tinted with it.

    ``set_color`` swaps either one for its shape-following sibling: one
    interned instance for every colour, never back to the palette.
    """

    LOOKS = (
        ("Metal", lambda c=None: scena.Metal(c, speed=0)),
        ("bubble", lambda c=None: scena.Shield(c, style="bubble")),
    )

    def setUp(self):
        self._clock = _recipes._clock
        _recipes._clock = lambda: 0.37

    def tearDown(self):
        _recipes._clock = self._clock

    def test_no_color_keeps_the_shape_color(self):
        for name, make in self.LOOKS:
            with self.subTest(visual=name):
                c = Circle(color="blue")
                c.visual = make()
                self.assertEqual(_rgb(c), (0.0, 0.0, 1.0), "the default must not overwrite the shape")
                c.visual = None
                self.assertEqual(_rgb(c), (0.0, 0.0, 1.0))
                c.destroy()

    def test_color_becomes_the_shape_color(self):
        for name, make in self.LOOKS:
            with self.subTest(visual=name):
                c = Circle(color="blue")
                c.visual = make("red")
                self.assertEqual(_rgb(c), (1.0, 0.0, 0.0))
                c.visual = None
                self.assertEqual(_rgb(c), (1.0, 0.0, 0.0), "visual=None keeps the given color")
                c.destroy()

    def test_set_color_retints_through_one_shared_sibling(self):
        for name, make in self.LOOKS:
            for seed in (None, "red"):
                with self.subTest(visual=name, seed=seed):
                    c = Circle(center=(64, 64), radius=40, color="blue")
                    c.visual = make(seed)
                    c.set_color(0, 1, 0)
                    sibling = c.visual
                    self.assertTrue(sibling._follows_shape)
                    self.assertIsNot(sibling, make(seed))
                    green = _draw(c)[40:88, 40:88, :3].reshape(-1, 3).sum(axis=0)
                    self.assertGreater(green[1], 1.5 * max(green[0], green[2]), green)
                    for i in range(40):
                        c.set_color(i / 40, 0.2, 0.6)
                    self.assertIs(c.visual, sibling, "a recolor interned a new look")
                    c.set_color("red")
                    c.visual = None
                    self.assertEqual(_rgb(c), (1.0, 0.0, 0.0))
                    c.destroy()

    def test_sibling_draws_like_the_seeded_look(self):
        """Recoloring to X draws what ``look(X)`` draws."""
        for name, make in self.LOOKS:
            with self.subTest(visual=name):
                a = Circle(center=(64, 64), radius=40, color="blue")
                a.visual = make("dodgerblue")
                b = Circle(center=(64, 64), radius=40, color="blue")
                b.visual = make()
                b.set_color("dodgerblue")
                np.testing.assert_array_equal(_draw(a), _draw(b))
                a.destroy()
                b.destroy()


if __name__ == "__main__":
    unittest.main()
