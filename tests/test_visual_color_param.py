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
from scena import Beat, Circle, Color, Liquify, Neon, Sprite
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
# drawing the seed. Empty since 2026-10-13: every look that takes ``color=``
# has an ``_unseed`` (Effect System Design §9 rule 18). Shrink-only: a new
# look that takes ``color=`` and keeps its seed on set_color fails the sweep.
SEED_WINS: set = set()

# Paint / Fill / Stroke are installers, not looks with a seed: set_color
# replaces them with the installer built on the new material.
from scena.visuals import Fill as _Fill, Paint as _Paint, Stroke as _Stroke  # noqa: E402
_INSTALLERS = (_Paint, _Fill, _Stroke)


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


def _knobs_of(look) -> dict:
    """A look's public non-colour knobs, as stored."""
    return {k: v for k, v in vars(look).items() if not k.startswith("_") and k != "color"}


def _follower(cls, base):
    """The look a recolor ends on: the unseeded look, or a palette look's
    shape-following sibling."""
    plain = cls(**base)
    return plain._unseed() or plain


def _state(shape) -> tuple:
    """(fill, line) as rounded RGBA (None for no paint)."""
    def one(p):
        if p is None:
            return None
        return tuple(round(float(v), 3) for v in p.rgb) if isinstance(p, Color) else type(p).__name__
    return one(shape.fill), one(shape.line)


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
            if not _takes_color(cls, style) or issubclass(cls, _INSTALLERS):
                continue            # installers: set_color rebuilds them (style.py)
            base = {} if style is None else {"style": style}
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                got = _recolored(cls("deepskyblue", **base), "lime")
                # Shown = what the shape-following look draws on a shape made
                # with color="lime" (set_color is color=, 2026-10-13).
                want = _worn(_follower(cls, base), "lime")
            ok = np.abs(got - want).max() <= 2
            (shows if ok else hidden).add((cls.__name__, style))
        self.assertIn(("Neon", None), shows)
        unlisted = sorted(hidden - SEED_WINS, key=str)
        self.assertFalse(unlisted, f"seeded looks where set_color does not show: {unlisted}")
        stale = sorted(SEED_WINS & shows, key=str)
        self.assertFalse(stale, f"SEED_WINS looks that now show set_color: remove them: {stale}")

    def test_deseed_keeps_every_knob(self):
        """``_unseed`` returns the sibling built from the same non-colour knobs:
        ``Rim("red", width=8)`` + ``set_color`` is ``Rim(width=8)``, not
        ``Rim()``. Bug class: a sibling that drops a knob (it would still
        pass the default-knob sweep above)."""
        from tests.test_knobs_take_effect import visual_cells
        n = 0
        for name, style, knob, alt in visual_cells():
            if knob == "color":
                continue
            cls = getattr(scena, name)
            kw = {knob: alt, **({} if style is None else {"style": style})}
            with self.subTest(visual=name, style=style, knob=knob), warnings.catch_warnings():
                warnings.simplefilter("ignore")
                if not _takes_color(cls, style) or issubclass(cls, _INSTALLERS):
                    continue            # installers: set_color rebuilds them (style.py)
                try:
                    seeded, plain = cls("deepskyblue", **kw), cls(**kw)
                except TypeError:
                    continue            # knob refused on this style (KN4)
                want = plain._unseed() or plain     # palette looks: shape-following
                got = seeded._unseed()
                self.assertIs(type(got), type(want))
                # Knobs as stored (clamped: Extrude(layers=10) keeps 7 and
                # interns apart from layers=7; one key clamp cost ~0.3 µs per
                # construction, 2026-10-13, so the twin interns stay).
                self.assertEqual(_knobs_of(got), _knobs_of(want))
                if _knobs_of(plain).get(knob, alt) == alt:     # not clamped
                    self.assertIs(got, want)
                self.assertIsNone(want._unseed(), "already unseeded: no new intern")
                n += 1
        self.assertGreater(n, 40, "the knob sweep stopped reaching the surface")

    def test_canary_seed_wins_again(self):
        import diff_support
        diff_support.assert_catches(
            self, "test_visual_color_param.TestSetColorShowsWhereColorIsTaken.test_seeded_every_look_and_style",
            [(_recipes.Rim, "_unseed", lambda self: None), (_recipes.Laser, "_unseed", lambda self: None)],
            "Rim / Laser seeds that win over set_color (before 2026-10-13)")

    def test_canary_deseed_drops_a_knob(self):
        import diff_support
        diff_support.assert_catches(
            self, "test_visual_color_param.TestSetColorShowsWhereColorIsTaken.test_deseed_keeps_every_knob",
            [(_recipes.Rim, "_unseed",
              lambda self: None if self._seed_color is None else _recipes.Rim(None, self.amount))],
            "Rim._unseed that forgets width= / darken=")

    def test_canary_metal_recolor_silent_again(self):
        import diff_support
        from scena.recipes import Metal
        diff_support.assert_catches(
            self, "test_visual_color_param.TestSetColorShowsWhereColorIsTaken.test_unseeded_every_look_and_style",
            [(Metal, "_unseed", lambda self: None)],
            "Metal() + set_color that changes nothing (before 2026-10-13)")


class TestSetColorIsColorParam(unittest.TestCase):
    """Decided 2026-10-13: ``set_color(X)`` gives what ``color=X`` gives, under
    any look; an outline look (Role B) follows the outline, which ``color=``
    derives; ``.fill`` / ``.line`` written before or after ``visual =`` draw
    the same; an outline look's seed dyes the outline only.

    Bug class: the shape's paint depending on the order of author writes.
    Before, set_color under an outline look wrote the exact line (a shape no
    ``color=`` gives, kept after ``visual = None``), a ``.line`` write under
    a look skipped the look's package (Rim lost its alpha, Halo kept its old
    wash), and ``Rim("red")`` left a red *body* once removed.
    """

    def setUp(self):
        _style._RECOLOR_HIDDEN_WARNED.clear()
        self._clock = _recipes._clock
        _recipes._clock = lambda: 0.37
        warnings.simplefilter("ignore")

    def tearDown(self):
        _recipes._clock = self._clock
        _style._RECOLOR_HIDDEN_WARNED.clear()
        warnings.resetwarnings()

    @staticmethod
    def _cells(seeded=None):
        """(cls, base, look) for every wearable look and style, installers out
        (set_color rebuilds them; a later write to them stands)."""
        for cls, style in _wearable_cells():
            if issubclass(cls, _INSTALLERS):
                continue
            base = {} if style is None else {"style": style}
            try:
                plain = cls(**base)
            except TypeError:
                continue
            if seeded is not True:
                yield cls, base, plain
            if seeded is not False and _takes_color(cls, style):
                yield cls, base, cls("deepskyblue", **base)

    def test_set_color_gives_what_color_param_gives(self):
        n = 0
        for cls, base, look in self._cells():
            with self.subTest(visual=cls.__name__, **base, seeded=look._seeded()):
                ref = Circle(center=(64, 64), radius=40, color="lime")
                ref.visual = _follower(cls, base)
                got = Circle(center=(64, 64), radius=40, color="blue")
                got.visual = look
                got.set_color("lime")
                self.assertLessEqual(int(np.abs(_draw(got) - _draw(ref)).max()), 2)
                got.visual = None
                self.assertEqual(_state(got), _state(Circle(radius=40, color="lime")))
                n += 1
                got.destroy()
                ref.destroy()
        self.assertGreater(n, 60, "the sweep stopped reaching the surface")

    def test_channel_write_order_does_not_matter(self):
        for cls, base, look in self._cells(seeded=False):
            for channel in ("fill", "line"):
                with self.subTest(visual=cls.__name__, **base, channel=channel):
                    before = Circle(center=(64, 64), radius=40, color="blue")
                    setattr(before, channel, "red")
                    before.visual = look
                    after = Circle(center=(64, 64), radius=40, color="blue")
                    after.visual = look
                    setattr(after, channel, "red")
                    self.assertLessEqual(int(np.abs(_draw(after) - _draw(before)).max()), 2)
                    before.visual = after.visual = None
                    self.assertEqual(_state(after), _state(before))
                    before.destroy()
                    after.destroy()

    # Stroke and blend knobs: a look sets some in its package (Rim's width,
    # Halo's ADD, Shield's dash) and reads others (Neon's width).
    _KNOBS = (("line_width", 6.0), ("blend", "screen"), ("dash", "dash"),
              ("line_cap", "square"), ("line_join", "bevel"))

    def test_knob_write_order_does_not_matter(self):
        """Decided 2026-10-13 (user): a knob written under a look re-applies
        it, as ``.fill`` / ``.line``. Where the look sets the knob itself it
        wins (``Rim(width=)`` is how to change it); the author's value shows
        where the look reads it, and after ``visual = None``. Before, a write
        after ``visual =`` overrode the package (23 / 18 / 11 of 42 cells for
        line_width / blend / dash) and ``visual = None`` dropped it (every
        cell, every knob)."""
        forced = 0
        for cls, base, look in self._cells(seeded=False):
            plain = Circle(center=(64, 64), radius=40, color="blue")
            plain.visual = look
            worn = _draw(plain)
            plain.destroy()
            for knob, value in self._KNOBS:
                with self.subTest(visual=cls.__name__, **base, knob=knob):
                    before = Circle(center=(64, 64), radius=40, color="blue")
                    setattr(before, knob, value)
                    before.visual = look
                    after = Circle(center=(64, 64), radius=40, color="blue")
                    after.visual = look
                    setattr(after, knob, value)
                    got = _draw(after)
                    self.assertLessEqual(int(np.abs(got - _draw(before)).max()), 2)
                    forced += int(np.abs(got - worn).max()) <= 2
                    before.visual = after.visual = None
                    self.assertEqual(getattr(after, knob), value, "visual = None dropped the write")
                    self.assertEqual(getattr(before, knob), value)
                    before.destroy()
                    after.destroy()
        self.assertGreater(forced, 60, "the sweep stopped reaching looks that set the knob")

    def test_knob_in_the_constructor_is_written_before_the_look(self):
        """``Circle(visual=Rim(), line_width=6)`` is ``line_width = 6`` then
        ``visual = Rim()``: the width is the shape's, the look keeps its own."""
        for look in (scena.Rim(), scena.Halo(), scena.Neon()):
            with self.subTest(visual=type(look).__name__):
                made = Circle(center=(64, 64), radius=40, visual=look, line_width=6)
                ref = Circle(center=(64, 64), radius=40)
                ref.line_width = 6
                ref.visual = look
                self.assertLessEqual(int(np.abs(_draw(made) - _draw(ref)).max()), 2)
                made.visual = None
                self.assertEqual(made.line_width, 6.0)
                made.destroy()
                ref.destroy()

    def test_sprite_knob_write_survives_the_look(self):
        """On a Sprite a write under a look is kept by ``visual = None``, and
        the body blit takes the author's blend in either order."""
        n = 0
        for cls, base, look in self._cells(seeded=False):
            probe = Sprite()
            try:
                probe.visual = look
            except TypeError:
                continue                    # shape-only look
            finally:
                probe.destroy()
            for knob, value in self._KNOBS:
                with self.subTest(visual=cls.__name__, **base, knob=knob):
                    before = Sprite()
                    setattr(before, knob, value)
                    before.visual = look
                    after = Sprite()
                    after.visual = look
                    setattr(after, knob, value)
                    self.assertEqual(after._blit_paint.getBlendMode(), before._blit_paint.getBlendMode())
                    after.visual = None
                    self.assertEqual(getattr(after, knob), value)
                    n += 1
                    before.destroy()
                    after.destroy()
        self.assertGreater(n, 20, "the sprite sweep stopped reaching the looks")

    def test_write_on_its_channel_beats_the_seed(self):
        """``Rim("red")`` then ``.line = "lime"`` is ``.line = "lime"`` then
        ``Rim()``; ``Neon("red")`` then ``.fill = "lime"`` likewise."""
        for cls, base, look in self._cells(seeded=True):
            if look._color_role not in ("A", "B"):
                continue
            channel = "line" if look._color_role == "B" else "fill"
            with self.subTest(visual=cls.__name__, **base, channel=channel):
                got = Circle(center=(64, 64), radius=40, color="blue")
                got.visual = look
                setattr(got, channel, "lime")
                # A body look's seed is the shape color (outline derived from
                # it, as color=); an outline look's seed is the outline only.
                ref = Circle(center=(64, 64), radius=40,
                             color="deepskyblue" if channel == "fill" else "blue")
                setattr(ref, channel, "lime")
                ref.visual = _follower(cls, base)
                self.assertLessEqual(int(np.abs(_draw(got) - _draw(ref)).max()), 2)
                got.destroy()
                ref.destroy()

    def test_outline_seed_dyes_the_outline_only(self):
        """``look("red")`` is ``line = "red"`` then ``look()`` for an outline
        look, on screen and once removed; a body look's seed stays the shape
        color, as ``color="red"``."""
        n = 0
        for cls, base, look in self._cells(seeded=True):
            with self.subTest(visual=cls.__name__, **base, role=look._color_role):
                got = Circle(center=(64, 64), radius=40, color="blue")
                got.visual = cls("red", **base)
                if look._color_role == "B":
                    ref = Circle(center=(64, 64), radius=40, color="blue")
                    ref.line = "red"
                    ref.visual = _follower(cls, base)
                    self.assertLessEqual(int(np.abs(_draw(got) - _draw(ref)).max()), 2)
                    ref.visual = None
                    n += 1
                else:
                    ref = Circle(center=(64, 64), radius=40, color="red")
                got.visual = None
                self.assertEqual(_state(got), _state(ref))
                got.destroy()
                ref.destroy()
        self.assertGreater(n, 10, "the outline looks left the sweep")

    def test_drawing_never_reapplies(self):
        """Looks rewrite their package at draw time (``_apply_at_draw``) under
        the apply guard: no draw, at any quality, runs a re-apply."""
        from scena.fx_quality import activate_quality
        calls = []
        orig = _style.PaintState._reapply_visual
        _style.PaintState._reapply_visual = lambda s: (calls.append(type(s._visual).__name__), orig(s))[1]
        try:
            for q in ("low", "medium", "high", "max"):
                activate_quality(q)
                for cls, base, look in self._cells():
                    c = Circle(center=(64, 64), radius=40, color="blue")
                    c.visual = look
                    _draw(c)
                    _draw(c)
                    c.destroy()
                self.assertEqual(calls, [], q)
        finally:
            _style.PaintState._reapply_visual = orig
            activate_quality("high")

    def test_canary_exact_line_again(self):
        import diff_support

        orig = _style.PaintState._apply_primary_paint

        def exact(self, material, **kw):
            if getattr(self, "_visual", None) is None:
                return orig(self, material, **kw)
            c = Color(material)
            self.fill = c
            self.line = c
            return self
        diff_support.assert_catches(
            self, "test_visual_color_param.TestSetColorIsColorParam.test_set_color_gives_what_color_param_gives",
            [(_style.PaintState, "_apply_primary_paint", exact)],
            "set_color writing the exact line (before 2026-10-13)")

    def test_canary_raw_channel_write_again(self):
        import diff_support
        diff_support.assert_catches(
            self, "test_visual_color_param.TestSetColorIsColorParam.test_channel_write_order_does_not_matter",
            [(_style.PaintState, "_look_channel_written", lambda self, channel: None)],
            ".line / .fill under a look skipping the look (before 2026-10-13)")

    def test_canary_raw_knob_write_again(self):
        import diff_support
        orig = _style.PaintState._patch_look_identity
        diff_support.assert_catches(
            self, "test_visual_color_param.TestSetColorIsColorParam.test_knob_write_order_does_not_matter",
            [(_style.PaintState, "_patch_look_identity",
              lambda self, **ch: False if not ch.keys() & {"fill", "line"}
              else orig(self, **ch))],
            "line_width / blend / dash under a look skipping it (before 2026-10-13)")

    def test_canary_outline_seed_dyes_the_body_again(self):
        import diff_support
        orig = _style.PaintState._identity_patch_seed
        diff_support.assert_catches(
            self, "test_visual_color_param.TestSetColorIsColorParam.test_outline_seed_dyes_the_outline_only",
            [(_style.PaintState, "_identity_patch_seed",
              lambda self, rgba, channel="auto": orig(self, rgba, channel="fill"))],
            "Rim(\"red\") leaving a red body (before 2026-10-13)")


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
