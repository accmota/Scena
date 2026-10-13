"""Guard: a knob the author passes changes what is drawn, or is listed with a reason.

Bug class (Testing Design, "A knob is accepted and changes nothing"):
``Metal("gold")`` drew chrome (the tint never reached the shader, 2026-10-09)
and ``Wallpaper("BG.png", tile_mode="mirror")`` ignored ``tile_mode`` on every
fit but ``"tile"`` (2026-10-10). Both were accepted, both changed nothing, and
each unit test had checked the knob on the one path where it worked.

Enumerated from the surface, not a hand list:

* every exported ``Visual`` a shape can wear × every ``style`` (read from the
  ``style`` annotation) × every constructor knob: the default and another
  value draw different pixels at the same clock time;
* every ``Wallpaper`` image ``fit`` × every image knob: some camera (rest, a
  far pan, a zoom-out, a rotation) shows the difference;
* every ``Wallpaper(Texture(...))`` ``fit`` × every ``Texture`` knob (and
  ``set_alpha``): the same, so a Texture keeps on a Wallpaper what it does on a
  shape (``angle``, ``shift`` and alpha were taken and dropped: SK4).

A cell with no effect is in ``KNOWN_NO_EFFECT`` (a decision pending, or a
documented "only on style X"), ``SAME_VALUE`` (the alternative *is* the
default on that path) or ``REFUSED_ON_STYLE`` / ``REFUSED_ON_FIT`` (the knob
raises, naming the style or fit that reads it: KN3, KN4); a listed no-effect
cell that starts to draw differently fails, so the lists only shrink.

    python tests/run_tiers.py focused test_knobs_take_effect
"""
from __future__ import annotations

import inspect
import os
import sys
import typing
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import skia  # noqa: E402

import scena  # noqa: E402
from scena import Circle, Wallpaper  # noqa: E402
from scena.visuals import Visual  # noqa: E402
from leftovers import module_sweep  # noqa: E402
from system_support import SystemTestCase  # noqa: E402

setUpModule, tearDownModule = module_sweep()


# ---------------------------------------------------------------------------
# Visuals
# ---------------------------------------------------------------------------

# Exported Visual classes a shape cannot wear (``shape.visual = X()`` raises
# with the right door): checked on their own doors elsewhere.
NOT_ON_A_SHAPE = {
    "Visual": "the base class",
    "Recipe": "the base class",
    **{n: "a stamp (shape.glow / .shadow / .tail / sprite.gray / .hue): test_stamps"
       for n in ("Glow", "CheapGlow", "Shadow", "Tail", "Grayscale", "HueShift")},
    **{n: "sprite-only (needs a bitmap body): test_visuals"
       for n in ("Aura", "EmissiveBloom", "Recolor")},
}

# Knobs whose default is None / unset: the value to try instead.
ALTERNATIVES = {
    "intensity": 2.0, "focus": (0.0, 0.0), "angle": 45.0, "alpha": 0.3,
    "width": 6.0, "material": "crimson",
}

# bubble left this list on 2026-10-13: it takes color= (palette look, like Metal).
_SHIELD_FIXED_HUE = ("nebula", "ember", "void", "molten", "cracks", "frost")

# (class, style, knob) -> why it draws nothing different. Shrink-only.
KNOWN_NO_EFFECT: dict = {}

# (class, style, knob) -> the constructor refuses the knob on that style, and
# the message names the style that reads it. Python's own "__init__() got an
# unexpected keyword" is not an author message (KN3). Decided 2026-10-12: a
# knob that one style reads raises on the others (KN4).
REFUSED_ON_STYLE = {
    **{("Shield", s, "color"): 'style="bubble"' for s in _SHIELD_FIXED_HUE},
    **{("Halo", s, k): "pulse"
       for s in ("hollow", "fill", "soft", "line") for k in ("rings", "speed")},
    ("Bolt", "core", "amount"): "filaments",
}


def _alternative(param):
    if param.name == "color":
        return "deepskyblue"
    d = param.default
    if d is None or d is param.empty or type(d).__name__ == "Unset":
        return ALTERNATIVES.get(param.name)
    if isinstance(d, bool):
        return not d
    if isinstance(d, int) and d:
        return d * 2
    if isinstance(d, (int, float)):
        return d * 0.5 if d else 0.5
    return None


def _styles(cls) -> list:
    p = inspect.signature(cls.__init__).parameters.get("style")
    if p is None:
        return [None]
    ann = p.annotation
    if isinstance(ann, str):
        ann = getattr(sys.modules[cls.__module__], ann, None) or getattr(scena, ann, None)
    return list(typing.get_args(ann)) or [p.default]


def _knobs(cls):
    for p in inspect.signature(cls.__init__).parameters.values():
        if p.name in ("self", "style") or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        yield p


def shape_visuals() -> list:
    return sorted(n for n in scena.__all__
                  if inspect.isclass(getattr(scena, n))
                  and issubclass(getattr(scena, n), Visual) and n not in NOT_ON_A_SHAPE)


def _render(visual) -> np.ndarray:
    """One Circle wearing ``visual``, drawn at the current clock time (no frame runs)."""
    c = Circle(center=(64, 64), radius=36, color="orange")
    try:
        c.visual = visual
        surf = skia.Surface(128, 128)
        cnv = surf.getCanvas()
        cnv.clear(skia.Color4f(0.2, 0.3, 0.4, 1.0))   # not black: Stroke() is black
        c.draw(cnv)
        return np.asarray(surf.makeImageSnapshot().toarray(
            colorType=skia.kRGBA_8888_ColorType)).astype(np.int32)
    finally:
        c.destroy()


def visual_cells():
    """(class name, style, knob, alternative) for every cell of the sweep."""
    for name in shape_visuals():
        cls = getattr(scena, name)
        for style in _styles(cls):
            for p in _knobs(cls):
                alt = _alternative(p)
                if alt is not None:
                    yield name, style, p.name, alt


class TestVisualKnobsReachThePixels(SystemTestCase, unittest.TestCase):
    world_draw = False

    def setUp(self):
        super().setUp()
        # Animated looks: a clock past zero, so speed / flicker show; no frame
        # runs between the two draws of a cell.
        self.w.seconds(0.7)

    def test_every_exported_visual_is_swept_or_listed(self):
        exported = {n for n in scena.__all__
                    if inspect.isclass(getattr(scena, n)) and issubclass(getattr(scena, n), Visual)}
        self.assertFalse(set(NOT_ON_A_SHAPE) - exported, "NOT_ON_A_SHAPE names a class no longer exported")
        for name in sorted(set(NOT_ON_A_SHAPE) - {"Visual", "Recipe"}):
            with self.subTest(visual=name), warnings.catch_warnings():
                warnings.simplefilter("ignore")
                with self.assertRaises(TypeError, msg=f"{name} is now wearable: sweep it"):
                    _render(getattr(scena, name)())
        self.assertGreater(len(list(visual_cells())), 100, "the sweep stopped reaching the surface")

    def test_every_knob_changes_the_pixels(self):
        no_effect = set()
        for name, style, knob, alt in visual_cells():
            cls = getattr(scena, name)
            base = {} if style is None else {"style": style}
            with self.subTest(visual=name, style=style, knob=knob), warnings.catch_warnings():
                warnings.simplefilter("ignore")
                if (name, style, knob) in REFUSED_ON_STYLE:
                    with self.assertRaises(TypeError) as cm:
                        cls(**base, **{knob: alt})
                    msg = str(cm.exception)
                    self.assertNotIn("__init__()", msg, "Python's own error reached the author")
                    self.assertIn(REFUSED_ON_STYLE[name, style, knob], msg)
                    continue
                a = _render(cls(**base))
                b = _render(cls(**base, **{knob: alt}))
                self.assertTrue(np.array_equal(a, _render(cls(**base))),
                                "two draws at one clock time differ: the cell cannot judge")
                if np.array_equal(a, b):
                    no_effect.add((name, style, knob))
        unexplained = sorted(no_effect - set(KNOWN_NO_EFFECT), key=str)
        self.assertFalse(unexplained, f"knobs accepted that change nothing: {unexplained}")
        stale = sorted(set(KNOWN_NO_EFFECT) - no_effect, key=str)
        self.assertFalse(stale, f"KNOWN_NO_EFFECT cells that now draw: remove them: {stale}")

    def test_canary_metal_without_its_tint(self):
        from diff_support import assert_catches
        # The sweep's seeded Metal, interned before the plant as another
        # module would (test_visual_color_param): it baked its rim from the
        # real _metal_edge, and the plant must still reach the sweep.
        seeded = scena.Metal("deepskyblue")
        edge = seeded._edge
        assert_catches(
            self, "test_knobs_take_effect.TestVisualKnobsReachThePixels.test_every_knob_changes_the_pixels",
            # Body and rim: since the rim takes the tint (2026-10-13) a body
            # without it still changes the pixels here; test_visuals'
            # test_metal_color_tints_the_metal reads the body on its own.
            [("scena.recipes", "_metal_tint", lambda fill: [0.0, 0.0, 0.0, 0.0]),
             ("scena.recipes", "_metal_edge", lambda tint: (0.75, 0.78, 0.82, 0.95))],
            "Metal(color) that never reaches the shader (2026-10-09)")
        # ... and the Metal built under the plant (chrome rim) did not stay
        # interned for later tests.
        self.assertIs(scena.Metal("deepskyblue"), seeded)
        self.assertEqual(seeded._edge, edge)


class TestCanaryPlantsReachInternedLooks(unittest.TestCase):
    """A canary plant runs on empty look intern caches and leaves them as it
    found them (``hypothesis_support.fresh_interns``; the Metal rim canary
    failed after test_visual_color_param, and its plant leaked a chrome-rimmed
    ``Metal("deepskyblue")`` into later tests, 2026-10-13)."""

    def test_a_look_built_before_the_plant_does_not_hide_it(self):
        from unittest import mock
        from hypothesis_support import fresh_interns
        import scena.recipes as R
        before = scena.Metal("deepskyblue")
        planted = (0.75, 0.78, 0.82, 0.95)
        with fresh_interns(), mock.patch.object(R, "_metal_edge", lambda tint: planted):
            under = scena.Metal("deepskyblue")
            self.assertIsNot(under, before)
            self.assertEqual(under._edge, planted)
        self.assertIs(scena.Metal("deepskyblue"), before)
        self.assertNotEqual(before._edge, planted)

    def test_every_intern_cache_is_emptied_and_given_back(self):
        import importlib
        from hypothesis_support import _INTERN_CACHES, fresh_interns
        scena.Metal("gold"), scena.Halo(), scena.Grayscale(0.5)   # one per cache
        caches = [getattr(importlib.import_module(m), a) for m, a in _INTERN_CACHES]
        saved = [dict(c) for c in caches]
        self.assertTrue(all(saved), "a cache the sweep names was never filled")
        with fresh_interns():
            self.assertEqual([len(c) for c in caches], [0] * len(caches))
            scena.Metal("gold"), scena.Halo(), scena.Grayscale(0.5)
        for c, old in zip(caches, saved):
            self.assertEqual(c, old)
            self.assertTrue(all(c[k] is old[k] for k in old))

    def test_the_cache_list_holds_every_interned_look(self):
        # A look interned in a cache fresh_interns does not clear would
        # bring the bug class back: every exported look and filter built
        # with its defaults sits in one of _INTERN_CACHES when it is interned.
        import importlib
        from scena.filters import FilterEffect
        from hypothesis_support import _INTERN_CACHES
        held = {id(v) for m, a in _INTERN_CACHES
                for v in getattr(importlib.import_module(m), a).values()}
        checked = 0
        for name in scena.__all__:
            cls = getattr(scena, name)
            if not (inspect.isclass(cls) and issubclass(cls, (Visual, FilterEffect))):
                continue
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    obj = cls()
            except Exception:
                continue
            if obj.__dict__.get("_interned"):
                checked += 1
                held |= {id(v) for m, a in _INTERN_CACHES
                         for v in getattr(importlib.import_module(m), a).values()}
                self.assertIn(id(obj), held, f"{name}() is interned outside _INTERN_CACHES")
        self.assertGreater(checked, 20, "the sweep stopped reaching interned looks")


# ---------------------------------------------------------------------------
# Wallpaper images
# ---------------------------------------------------------------------------

FITS = ("cover", "contain", "stretch", "tile")
WALLPAPER_KNOBS = {
    "tile_mode": ("mirror", "repeat", "clamp", "decal"),
    "scale": (2.0, 0.5),
    "tile_size": (100.0,),
    "underlay": ("red",),
}

# (fit, knob, value) -> why the same pixels are right: the value is what that
# fit already draws.
SAME_VALUE = {
    **{(f, "tile_mode", "decal"): "decal is the omitted default on a fitted image"
       for f in ("cover", "contain", "stretch")},
    ("tile", "tile_mode", "repeat"): "repeat is the omitted default on fit=\"tile\"",
    ("tile", "tile_mode", "clamp"): "clamp on fit=\"tile\" becomes repeat (Canvas Design)",
    ("tile", "underlay", "red"): "a repeating tile leaves no pixel for the underlay",
}

# (fit, knob, value) -> no effect, decision pending. Shrink-only.
KNOWN_WALLPAPER: dict = {}

# (fit, knob, value) -> refused, and the message names the fit that reads it
# (KN4, decided 2026-10-12).
REFUSED_ON_FIT = {(f, "tile_size", 100.0): 'fit="tile"' for f in ("cover", "contain", "stretch")}

# Texture knobs on a Wallpaper: the constructor's, read from its signature, plus
# ``set_alpha`` (a method on the same object). Values are built per cell.
TEXTURE_KNOBS = {
    "tile_mode": ("mirror", "repeat", "clamp", "decal"),
    "scale": (2.0, 0.5),
    "tile_size": (100.0,),
    "angle": (30.0, -90.0),
    "shift": ("hue", "recolor"),
    "color": ("red",),
    "set_alpha": (0.3,),
}
TEXTURE_SOURCE_ARGS = {"source", "filename", "image", "fit"}

# (fit, knob, value) -> why no pixel changes is right.
TEXTURE_NO_PIXELS = {
    **{(f, "color", "red"): "a proxy hue for looks that sample the host; a "
                            "Wallpaper wears no look (Texture docstring)"
       for f in FITS},
}


def _texture_value(knob, v):
    if knob == "shift":
        from scena import HueShift, Recolor
        return HueShift(0.33) if v == "hue" else Recolor("cyan", "gold")  # BG.png is mostly green-cyan
    return v


class TestWallpaperKnobsReachThePixels(unittest.TestCase):
    W, H = 200, 150
    DW, DH = 1000.0, 750.0       # design; BG.png is 1000 x 750
    REST = (500.0, 375.0)

    @classmethod
    def setUpClass(cls):
        from media_support import media
        cls.path = media("tilesets", "BG", "BG.png")

    def _cams(self):
        from scena.background import CameraSample
        rx, ry = self.REST
        return (
            CameraSample(rx, ry, 1.0, 0.0, rest_x=rx, rest_y=ry),
            CameraSample(rx + 4000.0, ry, 1.0, 0.0, rest_x=rx, rest_y=ry),
            CameraSample(rx, ry, 0.2, 0.0, rest_x=rx, rest_y=ry),
            CameraSample(rx + 900.0, ry, 1.0, 33.0, rest_x=rx, rest_y=ry),
        )

    def _shot(self, wp, cam):
        surf = skia.Surface(self.W, self.H)
        c = surf.getCanvas()
        c.clear(skia.Color4f(0, 1, 0, 1))
        wp.draw(c, self.W, self.H, 0.0, cam, design_width=self.DW, design_height=self.DH)
        return np.asarray(surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType))

    def _wallpaper(self, **kw):
        return Wallpaper.temp(self.path, pan_response=0.1, zoom_response=1.0,
                              rotation_response=1.0, **kw)

    def test_the_knob_list_is_the_signature(self):
        params = set(inspect.signature(Wallpaper.__init__).parameters)
        image_only = {"fit", "tile_mode", "scale", "tile_size", "underlay"}
        self.assertLessEqual(image_only, params)
        self.assertEqual(set(WALLPAPER_KNOBS), image_only - {"fit"})

    def test_every_knob_changes_some_camera_on_every_fit(self):
        no_effect = set()
        cams = self._cams()
        for fit in FITS:
            base = self._wallpaper(fit=fit)
            shots = [self._shot(base, c) for c in cams]
            for knob, values in WALLPAPER_KNOBS.items():
                for v in values:
                    with self.subTest(fit=fit, knob=knob, value=v):
                        if (fit, knob, v) in REFUSED_ON_FIT:
                            with self.assertRaises(TypeError) as cm:
                                self._wallpaper(fit=fit, **{knob: v})
                            self.assertIn(REFUSED_ON_FIT[fit, knob, v], str(cm.exception))
                            continue
                        wp = self._wallpaper(fit=fit, **{knob: v})
                        if all(np.array_equal(s, self._shot(wp, c)) for s, c in zip(shots, cams)):
                            no_effect.add((fit, knob, v))
        unexplained = sorted(no_effect - set(SAME_VALUE) - set(KNOWN_WALLPAPER), key=str)
        self.assertFalse(unexplained, f"Wallpaper knobs accepted that change nothing: {unexplained}")
        stale = sorted((set(SAME_VALUE) | set(KNOWN_WALLPAPER)) - no_effect, key=str)
        self.assertFalse(stale, f"listed cells that now draw: remove them: {stale}")

    def _texture_wallpaper(self, fit, knob=None, v=None):
        from scena import Texture
        kw = {} if knob in (None, "set_alpha") else {knob: _texture_value(knob, v)}
        tex = Texture(self.path, fit=fit, **kw)
        if knob == "set_alpha":
            tex.set_alpha(v)
        return Wallpaper.temp(tex, pan_response=0.1, zoom_response=1.0,
                              rotation_response=1.0)

    def test_the_texture_knob_list_is_the_signature(self):
        from scena import Texture
        params = set(inspect.signature(Texture.__init__).parameters) - {"self"}
        self.assertEqual(set(TEXTURE_KNOBS) - {"set_alpha"}, params - TEXTURE_SOURCE_ARGS)

    def test_every_texture_knob_changes_some_camera_on_every_fit(self):
        no_effect = set()
        cams = self._cams()
        for fit in FITS:
            base = self._texture_wallpaper(fit)
            shots = [self._shot(base, c) for c in cams]
            for knob, values in TEXTURE_KNOBS.items():
                for v in values:
                    with self.subTest(fit=fit, knob=knob, value=v):
                        if (fit, knob, v) in REFUSED_ON_FIT:
                            with self.assertRaises(TypeError) as cm:
                                self._texture_wallpaper(fit, knob, v)
                            self.assertIn(REFUSED_ON_FIT[fit, knob, v], str(cm.exception))
                            continue
                        wp = self._texture_wallpaper(fit, knob, v)
                        if all(np.array_equal(s, self._shot(wp, c)) for s, c in zip(shots, cams)):
                            no_effect.add((fit, knob, v))
        explained = {c for c in SAME_VALUE if c[1] in TEXTURE_KNOBS} | set(TEXTURE_NO_PIXELS)
        unexplained = sorted(no_effect - explained, key=str)
        self.assertFalse(unexplained, f"Texture knobs a Wallpaper takes and drops: {unexplained}")
        stale = sorted(explained - no_effect, key=str)
        self.assertFalse(stale, f"listed cells that now draw: remove them: {stale}")

    def test_set_alpha_after_the_wallpaper_drew(self):
        # The built fill is cached per Wallpaper; a later set_alpha on the same
        # Texture must rebuild it, as a shape repaints.
        from scena import Texture
        cam = self._cams()[0]
        for fit in FITS:
            with self.subTest(fit=fit):
                tex = Texture(self.path, fit=fit)
                wp = Wallpaper.temp(tex)
                before = self._shot(wp, cam)
                tex.set_alpha(0.3)
                self.assertFalse(np.array_equal(before, self._shot(wp, cam)))

    def test_canary_wallpaper_drops_texture_knobs(self):
        from diff_support import assert_catches
        assert_catches(
            self, "test_knobs_take_effect.TestWallpaperKnobsReachThePixels."
                  "test_every_texture_knob_changes_some_camera_on_every_fit",
            [("scena.style", "_texture_turn", lambda source: 0.0),
             ("scena.style", "_texture_knobs_paint", lambda paint, source: paint)],
            "a Wallpaper that drops a Texture's angle, shift and alpha (SK4, 2026-10-13)")

    def test_canary_fitted_image_ignores_tile_mode(self):
        from diff_support import assert_catches
        from scena.style import BackgroundFit
        assert_catches(
            self, "test_knobs_take_effect.TestWallpaperKnobsReachThePixels."
                  "test_every_knob_changes_some_camera_on_every_fit",
            [("scena.style", "_uses_template", lambda s: s._fit == BackgroundFit.TILE)],
            "a fitted Wallpaper that draws once whatever tile_mode says (2026-10-10)")


if __name__ == "__main__":
    unittest.main()
