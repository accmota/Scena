"""
Color name resolution: exact, normalize, modifiers, suffix, fuzzy, fallback.

Run:

    python -m unittest tests.test_color -v
"""

import os
import sys
import random
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.color import (
    Color,
    ColorNames,
    ColorResolveKind,
    ColorSpace,
    Colormap,
    Palette,
    resolve_rgb,
    resolve_rgba,
)


class TestColorExact(unittest.TestCase):
    def test_basic_names(self):
        self.assertEqual(ColorNames.get('red'), (1, 0, 0))
        self.assertEqual(ColorNames.get('blue'), (0, 0, 1))
        self.assertEqual(ColorNames.get('white'), (1, 1, 1))

    def test_case_insensitive_no_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            rgb = ColorNames.get('Red')
            self.assertEqual(rgb, (1, 0, 0))
            self.assertEqual(len(w), 0)

    def test_multiword_exact(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            rgb = ColorNames.get('sky blue')
            self.assertEqual(rgb, ColorNames._COLORS['sky blue'])
            self.assertEqual(len(w), 0)

    def test_grey_alias(self):
        self.assertEqual(ColorNames.get('grey'), ColorNames.get('gray'))


class TestLighterDarkerAreHslLightness(unittest.TestCase):
    """Guia Color table (PM10): darker / lighter move HSL lightness by amount;
    hue and saturation stay."""

    def test_step(self):
        from scena.color import Color
        c = Color("tomato")
        h, s_, l, a = c.hsl
        for amount in (0.02, 0.1, 0.25):
            d, li = c.darker(amount).hsl, c.lighter(amount).hsl
            self.assertAlmostEqual(d[2], l - amount, places=6)
            self.assertAlmostEqual(li[2], l + amount, places=6)
            self.assertAlmostEqual(d[0], h, places=6)
            self.assertAlmostEqual(d[1], s_, places=6)


class TestColorNormalize(unittest.TestCase):
    def test_hyphen(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            self.assertEqual(ColorNames.get('sky-blue'), ColorNames._COLORS['sky blue'])
            self.assertEqual(len(w), 0)

    def test_underscore(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            self.assertEqual(ColorNames.get('hot_pink'), ColorNames._COLORS['hot pink'])
            self.assertEqual(len(w), 0)

    def test_camel_case(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            self.assertEqual(ColorNames.get('SkyBlue'), ColorNames._COLORS['sky blue'])
            self.assertEqual(ColorNames.get('DeepSkyBlue'), ColorNames._COLORS['deep sky blue'])
            self.assertEqual(len(w), 0)

    def test_compact_no_spaces(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            self.assertEqual(ColorNames.get('deepskyblue'), ColorNames._COLORS['deep sky blue'])
            self.assertEqual(len(w), 0)

    def test_extra_spaces_and_punctuation(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            self.assertEqual(ColorNames.get('  sky   blue! '), ColorNames._COLORS['sky blue'])
            self.assertEqual(len(w), 0)


class TestColorModifiers(unittest.TestCase):
    def test_dark_light_faded(self):
        base = Color('blue')
        dark = Color('dark blue')
        light = Color('light blue')
        faded = Color('faded blue')

        self.assertLess(dark.hsl[2], base.hsl[2])
        self.assertGreater(light.hsl[2], base.hsl[2])
        self.assertLess(faded.hsl[1], base.hsl[1])

    def test_dark_with_hyphen_normalize(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            a = ColorNames.get('dark-blue')
            b = ColorNames.get('dark blue')
            self.assertEqual(a, b)
            self.assertEqual(len(w), 0)

    def test_modifier_on_multiword(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            rgb = ColorNames.get('dark sky blue')
            expected = Color(ColorNames._COLORS['sky blue']).darker(0.2).rgb[:3]
            self.assertEqual(rgb, expected)
            self.assertEqual(len(w), 0)

    def test_stacked_modifiers(self):
        # Peel order: dark then light; apply in the same order.
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            rgb = ColorNames.get('dark light blue')
            expected = Color(ColorNames._COLORS['blue']).darker(0.2).lighter(0.2).rgb[:3]
            self.assertEqual(rgb, expected)
            self.assertEqual(len(w), 0)


class TestGluedModifiers(unittest.TestCase):
    """``"lightcyan"`` is ``"light cyan"``, as ``"deepskyblue"`` is ``"deep sky blue"``.

    Bug (2026-10-09, tutorial 08): ``Color("lightcyan")`` painted magenta with a
    warning suggesting ``cyan, tan`` — the compact spelling of a base name was
    already the same name, but a modifier glued to its base was not peeled.
    """

    def assertSilent(self, name, spaced):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            self.assertEqual(ColorNames.get(name), ColorNames.get(spaced), name)
            self.assertEqual(len(w), 0, f"{name!r} warned: {[str(x.message) for x in w]}")

    def test_every_modifier_glued_to_every_name_is_that_name(self):
        for mod in ColorNames._MODIFIERS:
            for base in ColorNames._COLORS:
                with self.subTest(mod=mod, base=base):
                    self.assertSilent(mod + base.replace(' ', ''), f"{mod} {base}")

    def test_case_stacking_and_mixing(self):
        self.assertSilent('LightCyan', 'light cyan')
        self.assertSilent('DARKBLUE', 'dark blue')
        self.assertSilent('darkdarkblue', 'dark dark blue')
        self.assertSilent('dark lightblue', 'dark light blue')
        self.assertSilent('darkskyblue', 'dark sky blue')

    def test_a_typo_suggests_the_name_with_its_modifier(self):
        result = ColorNames.resolve('lightcyna')
        self.assertEqual(result.kind, ColorResolveKind.FUZZY)
        self.assertEqual(result.resolved_name, 'light cyan')
        self.assertIn('light cyan', result.suggestions)
        with self.assertWarns(RuntimeWarning) as cm:
            ColorNames.get('lightcyna')
        self.assertIn("'light cyan'", str(cm.warning))
        self.assertEqual(ColorNames.resolve('faded blu').suggestions, ('faded blue',))

    def test_a_word_that_only_starts_like_a_modifier_is_not_peeled(self):
        for name in ('lightning', 'darkxyz', 'light', 'dark'):
            with self.subTest(name=name):
                self.assertEqual(ColorNames.resolve(name).kind, ColorResolveKind.FALLBACK)

    def test_a_table_name_that_starts_with_a_modifier_wins(self):
        ColorNames._COLORS['darkorange'] = (1.0, 0.55, 0.0)
        ColorNames._compact_to_name = ColorNames._names_by_length = None
        try:
            result = ColorNames.resolve('darkorange')
            self.assertEqual(result.kind, ColorResolveKind.EXACT)
            self.assertEqual(result.rgb, (1.0, 0.55, 0.0))
        finally:
            del ColorNames._COLORS['darkorange']
            ColorNames._compact_to_name = ColorNames._names_by_length = None


class TestColorSuffix(unittest.TestCase):
    def test_super_blue_uses_blue_not_sky(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            result = ColorNames.resolve('super blue')
            self.assertEqual(result.kind, ColorResolveKind.SUFFIX)
            self.assertEqual(result.resolved_name, 'blue')
            self.assertEqual(result.rgb, (0, 0, 1))
            ColorNames.get('super blue')
            self.assertTrue(any('super blue' in str(x.message) for x in w))

    def test_longest_suffix_wins(self):
        # Prefer "deep sky blue" over shorter "sky blue" / "blue"
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            result = ColorNames.resolve('very deep sky blue')
            self.assertEqual(result.kind, ColorResolveKind.SUFFIX)
            self.assertEqual(result.resolved_name, 'deep sky blue')
            self.assertEqual(result.rgb, ColorNames._COLORS['deep sky blue'])
            ColorNames.get('very deep sky blue')
            self.assertTrue(any(issubclass(x.category, Warning) for x in w))
            self.assertTrue(any('very deep sky blue' in str(x.message) for x in w))

    def test_suffix_with_modifier(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            result = ColorNames.resolve('dark super blue')
            self.assertEqual(result.kind, ColorResolveKind.SUFFIX)
            self.assertEqual(result.resolved_name, 'dark blue')
            expected = Color((0, 0, 1)).darker(0.2).rgb[:3]
            self.assertEqual(result.rgb, expected)
            ColorNames.get('dark super blue')
            self.assertTrue(len(w) >= 1)


class TestColorFuzzy(unittest.TestCase):
    def test_typo_blu(self):
        with self.assertWarns(RuntimeWarning):
            rgb = ColorNames.get('blu')
        self.assertEqual(rgb, (0, 0, 1))

    def test_typo_purpel(self):
        result = ColorNames.resolve('purpel')
        self.assertEqual(result.kind, ColorResolveKind.FUZZY)
        self.assertEqual(result.resolved_name, 'purple')
        self.assertEqual(result.rgb, ColorNames._COLORS['purple'])
        with self.assertWarns(RuntimeWarning):
            self.assertEqual(ColorNames.get('purpel'), ColorNames._COLORS['purple'])

    def test_typo_oragne(self):
        with self.assertWarns(RuntimeWarning):
            rgb = ColorNames.get('oragne')
        self.assertEqual(rgb, ColorNames._COLORS['orange'])

    def test_fuzzy_does_not_pick_wrong_multiword_for_super_blue(self):
        # Regression: low-cutoff fuzzy would prefer steel/sky blue over blue
        result = ColorNames.resolve('super blue')
        self.assertNotIn(result.resolved_name, ('sky blue', 'steel blue', 'royal blue'))
        self.assertEqual(result.resolved_name, 'blue')


class TestColorFallback(unittest.TestCase):
    def test_unknown_uses_magenta_and_warns(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            rgb = ColorNames.get('plutonium')
            self.assertEqual(rgb, ColorNames._FALLBACK_RGB)
            self.assertEqual(rgb, (1.0, 0.0, 1.0))
            self.assertTrue(any('fallback' in str(x.message).lower() for x in w))

    def test_resolve_fallback_kind(self):
        result = ColorNames.resolve('xyzzy-not-a-color')
        self.assertEqual(result.kind, ColorResolveKind.FALLBACK)
        self.assertEqual(result.resolved_name, ColorNames._FALLBACK_NAME)
        self.assertFalse(ColorNames.is_known('xyzzy-not-a-color'))

    def test_empty_string_fallback(self):
        result = ColorNames.resolve('   ')
        self.assertEqual(result.kind, ColorResolveKind.FALLBACK)

    def test_color_constructor_does_not_raise_on_unknown(self):
        with self.assertWarns(RuntimeWarning):
            c = Color('not-a-real-color-name')
        self.assertEqual(c.rgb[:3], ColorNames._FALLBACK_RGB)


class TestColorStillStrict(unittest.TestCase):
    def test_invalid_hex_warns_and_falls_back_to_magenta(self):
        # One unknown-colour rule everywhere (Scena Design — Numbers and signs):
        # a malformed hex is an unknown spelling — warn + magenta, never raise.
        for bad in ('#ff', '#gg0000', '#', '#000:00'):
            with self.subTest(bad=bad):
                with self.assertWarns(RuntimeWarning):
                    c = Color(bad)
                self.assertEqual(tuple(c.rgb)[:3], tuple(Color('magenta').rgb)[:3])

    def test_invalid_type_still_raises(self):
        # A wrong type is a TypeError, and the message lists the forms.
        with self.assertRaises(TypeError) as ctx:
            Color({'r': 1})
        self.assertIn('"#FF8800"', str(ctx.exception))

    def test_out_of_range_components_still_raise(self):
        with self.assertRaises(ValueError) as ctx:
            Color(1.5, 0, 0)
        self.assertIn("[0, 1]", str(ctx.exception))
        self.assertIn("1.5", str(ctx.exception))

    def test_byte_scale_message_hints_divide_by_255(self):
        with self.assertRaises(ValueError) as ctx:
            Color(255, 0, 0)
        msg = str(ctx.exception)
        self.assertIn("255", msg)
        self.assertIn("0–1", msg)
        self.assertIn("divide by 255", msg)

    def test_bool_components_raise_type_error(self):
        with self.assertRaises(TypeError):
            Color(True, 0, 0)
        with self.assertRaises(TypeError):
            Color(1, False, 0)

    def test_constructor_alpha_clamps(self):
        c = Color(1, 0, 0, 1.5)
        self.assertAlmostEqual(c.rgb[3], 1.0)
        c2 = Color(0, 1, 0, -0.2)
        self.assertAlmostEqual(c2.rgb[3], 0.0)
        c3 = Color((0, 0, 1, 2.0))
        self.assertAlmostEqual(c3.rgb[3], 1.0)
        with self.assertRaises(ValueError):
            Color(1.5, 0, 0, 1.5)


class TestColorIsKnownAndColormap(unittest.TestCase):
    def test_is_known(self):
        self.assertTrue(ColorNames.is_known('red'))
        self.assertTrue(ColorNames.is_known('blu'))  # fuzzy still "known"
        self.assertTrue(ColorNames.is_known('super blue'))  # suffix
        self.assertFalse(ColorNames.is_known('totally-made-up-zzzz'))

    def test_colormap_from_preset_color_name(self):
        cm = Colormap.from_preset('coral')
        self.assertIsInstance(cm, Colormap)

    def test_colormap_from_preset_unknown_raises(self):
        with self.assertRaises(ValueError):
            Colormap.from_preset('totally-made-up-zzzz')

    def test_colormap_from_preset_case_insensitive(self):
        cm = Colormap.from_preset('RdYl')
        self.assertIsInstance(cm, Colormap)
        cm2 = Colormap.from_preset('rdyl')
        self.assertEqual(len(cm.colors), len(cm2.colors))

    def test_colormap_and_gradient_share_plasma_stops(self):
        from scena.gradient_presets import get_preset
        from scena.style import Gradient
        stops = get_preset('plasma')
        cm = Colormap.from_preset('plasma')
        g = Gradient('plasma')
        self.assertEqual([c.rgb[:3] for _, c in cm.colors], [t[1] for t in stops])
        self.assertEqual(len(g._colors), len(stops))

    def test_colormap_default_color_space_is_oklab(self):
        self.assertEqual(
            Colormap.from_colors('red', 'blue').color_space,
            ColorSpace.OKLAB,
        )
        self.assertEqual(
            Colormap.from_preset('plasma').color_space,
            ColorSpace.OKLAB,
        )
        self.assertEqual(
            Colormap([(0.0, 'red'), (1.0, 'blue')]).color_space,
            ColorSpace.OKLAB,
        )


class TestColorRandomJitter(unittest.TestCase):
    def test_random_default_is_vivid(self):
        samples = [Color.random() for _ in range(40)]
        sats = [c.hsv[1] for c in samples]
        vals = [c.hsv[2] for c in samples]
        self.assertTrue(all(abs(s - 0.65) < 1e-9 for s in sats))
        self.assertTrue(all(abs(v - 0.85) < 1e-9 for v in vals))
        hues = {round(c.hsv[0], 5) for c in samples}
        self.assertGreater(len(hues), 10)

    def test_random_range_saturation_value(self):
        random.seed(7)
        samples = [
            Color.random(saturation=(0.2, 0.4), value=(0.5, 0.6))
            for _ in range(30)
        ]
        for c in samples:
            s, v = c.hsv[1], c.hsv[2]
            self.assertGreaterEqual(s, 0.2 - 1e-9)
            self.assertLessEqual(s, 0.4 + 1e-9)
            self.assertGreaterEqual(v, 0.5 - 1e-9)
            self.assertLessEqual(v, 0.6 + 1e-9)

    def test_random_rejects_bad_spec(self):
        with self.assertRaises(TypeError):
            Color.random(saturation=(0.1, 0.2, 0.3))
        with self.assertRaises(TypeError):
            Color.random(value='high')

    def test_jitter_stays_near_base_hue(self):
        random.seed(3)
        base = Color('red')
        bh = base.hsv[0]
        for _ in range(40):
            j = base.jitter()
            dh = abs(j.hsv[0] - bh)
            dh = min(dh, 1.0 - dh)
            self.assertLessEqual(dh, 0.04 + 1e-9)

    def test_jitter_wider_hue(self):
        random.seed(11)
        base = Color('red')
        far = [base.jitter(hue=0.2) for _ in range(80)]
        deltas = []
        bh = base.hsv[0]
        for c in far:
            dh = abs(c.hsv[0] - bh)
            deltas.append(min(dh, 1.0 - dh))
        self.assertGreater(max(deltas), 0.05)

    def test_jitter_none_stays_none(self):
        self.assertTrue(Color(None).jitter().is_none())

    def test_colormap_random_on_ramp(self):
        random.seed(42)
        ramp = Colormap.from_colors('red', 'blue')
        ends = {ramp.get_color(0.0).rgb[:3], ramp.get_color(1.0).rgb[:3]}
        picks = [ramp.random().rgb[:3] for _ in range(20)]
        self.assertTrue(all(isinstance(Color(p), Color) for p in picks))
        # Not every pick is an endpoint (very unlikely with seed + 20 samples)
        self.assertTrue(any(p not in ends for p in picks))


class TestColorVibrant(unittest.TestCase):
    def test_vibrant_version_uses_hsv_saturation(self):
        muted = Color.from_hsv(0.55, 0.25, 0.7, 1.0)
        vivid = muted.vibrant_version(0.5)
        mh, ms, mv, ma = muted.hsv
        vh, vs, vv, va = vivid.hsv
        self.assertAlmostEqual(vh, mh, places=5)
        self.assertGreater(vs, ms + 0.35)
        self.assertGreaterEqual(vv, max(mv, 0.72))
        self.assertAlmostEqual(va, ma, places=5)

    def test_vibrant_version_clamps_saturation(self):
        already = Color.from_hsv(0.1, 0.95, 0.8)
        vivid = already.vibrant_version(0.5)
        self.assertAlmostEqual(vivid.hsv[1], 1.0, places=5)

    def test_vibrant_version_default_amount(self):
        muted = Color.from_hsv(0.1, 0.2, 0.5)
        vivid = muted.vibrant_version()
        self.assertGreater(vivid.hsv[1], 0.7)

    def test_whiter_version_mixes_toward_white(self):
        c = Color(0.2, 0.4, 0.8, 0.9)
        w = c.whiter_version(0.5)
        self.assertGreater(w.rgb[0], c.rgb[0])
        self.assertGreater(w.rgb[1], c.rgb[1])
        self.assertGreater(w.rgb[2], c.rgb[2])
        self.assertLess(w.rgb[2], 1.0)
        self.assertAlmostEqual(w.rgb[3], 0.9, places=5)
        full = c.whiter_version(1.0)
        self.assertAlmostEqual(full.rgb[0], 1.0, places=5)
        self.assertAlmostEqual(full.rgb[1], 1.0, places=5)
        self.assertAlmostEqual(full.rgb[2], 1.0, places=5)


class TestColorFactoriesAndRamps(unittest.TestCase):
    def test_from_hsl_wraps_hue_and_clamps(self):
        a = Color.from_hsl(0.25, 1.0, 0.5)
        b = Color.from_hsl(1.25, 1.0, 0.5)
        self.assertAlmostEqual(a.rgb[0], b.rgb[0], places=5)
        self.assertAlmostEqual(a.rgb[1], b.rgb[1], places=5)
        self.assertAlmostEqual(a.rgb[2], b.rgb[2], places=5)
        over = Color.from_hsl(0.0, 2.0, 1.5)
        self.assertTrue(all(0.0 <= c <= 1.0 for c in over.rgb))

    def test_from_hsv_wraps_hue_and_clamps(self):
        a = Color.from_hsv(0.1, 1.0, 1.0)
        b = Color.from_hsv(-0.9, 1.0, 1.0)
        self.assertAlmostEqual(a.rgb[0], b.rgb[0], places=5)
        self.assertAlmostEqual(a.rgb[1], b.rgb[1], places=5)
        self.assertAlmostEqual(a.rgb[2], b.rgb[2], places=5)
        Color.from_hsv(0.0, -1.0, 2.0)

    def test_shades_and_tints_require_two_steps(self):
        c = Color(1.0, 0.0, 0.0)
        with self.assertRaises(ValueError):
            c.shades(1)
        with self.assertRaises(ValueError):
            c.tints(0)
        self.assertEqual(len(c.shades(2)), 2)
        self.assertEqual(len(c.tints(3)), 3)


class TestColorResolveApi(unittest.TestCase):
    def test_names_lists_known(self):
        names = ColorNames.names()
        self.assertIn('red', names)
        self.assertIn('deep sky blue', names)
        self.assertEqual(names, sorted(names))

    def test_from_name(self):
        c = Color.from_name('cyan')
        self.assertEqual(c.rgb[:3], (0, 1, 1))


class TestResolveRgbRgba(unittest.TestCase):
    def test_resolve_rgb_none_default(self):
        self.assertEqual(resolve_rgb(None), (1.0, 1.0, 1.0))
        self.assertEqual(resolve_rgb(None, default=(0.2, 0.3, 0.4)), (0.2, 0.3, 0.4))

    def test_resolve_rgb_name_str(self):
        self.assertEqual(resolve_rgb("cyan"), (0.0, 1.0, 1.0))

    def test_resolve_rgb_color_discards_alpha(self):
        c = Color(1.0, 0.0, 0.0, 0.25)
        self.assertEqual(resolve_rgb(c), (1.0, 0.0, 0.0))

    def test_resolve_rgb_3_and_4_tuple(self):
        self.assertEqual(resolve_rgb((0.1, 0.2, 0.3)), (0.1, 0.2, 0.3))
        self.assertEqual(resolve_rgb((0.1, 0.2, 0.3, 0.5)), (0.1, 0.2, 0.3))

    def test_resolve_rgb_invalid_raises(self):
        with self.assertRaises(TypeError):
            resolve_rgb(object(), default=(0.5, 0.5, 0.5))
        with self.assertRaises(TypeError):
            resolve_rgb((), default=(0.5, 0.5, 0.5))
        with self.assertRaises(TypeError):
            resolve_rgb((0.1, 0.2))

    def test_resolve_rgb_clamps_author_tuple(self):
        self.assertEqual(resolve_rgb((1.5, -0.2, 0.3)), (1.0, 0.0, 0.3))

    def test_resolve_rgb_none_keeps_hdr_default(self):
        self.assertEqual(
            resolve_rgb(None, default=(1.15, 1.05, 0.85)),
            (1.15, 1.05, 0.85),
        )

    def test_resolve_rgba_invalid_raises(self):
        with self.assertRaises(TypeError):
            resolve_rgba(object())
        with self.assertRaises(TypeError):
            resolve_rgba((1.0, 0.0))

    def test_resolve_rgba_clamps_author_tuple(self):
        self.assertEqual(
            resolve_rgba((1.2, 0.0, 0.0, 1.5)),
            (1.0, 0.0, 0.0, 1.0),
        )

    def test_resolve_rgba_none_default(self):
        self.assertEqual(resolve_rgba(None), (1.0, 1.0, 1.0, 1.0))
        self.assertEqual(
            resolve_rgba(None, default=(0.1, 0.2, 0.3, 0.4)),
            (0.1, 0.2, 0.3, 0.4),
        )

    def test_resolve_rgba_str_uses_default_alpha(self):
        self.assertEqual(
            resolve_rgba("white", default=(0, 0, 0, 0.5)),
            (1.0, 1.0, 1.0, 0.5),
        )

    def test_resolve_rgba_color_discards_alpha(self):
        c = Color(0.0, 1.0, 0.0, 0.2)
        self.assertEqual(
            resolve_rgba(c, default=(0, 0, 0, 0.8)),
            (0.0, 1.0, 0.0, 0.8),
        )

    def test_resolve_rgba_3_tuple_default_alpha(self):
        self.assertEqual(
            resolve_rgba((0.2, 0.4, 0.6), default=(0, 0, 0, 0.3)),
            (0.2, 0.4, 0.6, 0.3),
        )

    def test_resolve_rgba_4_tuple_keeps_alpha(self):
        self.assertEqual(
            resolve_rgba((0.2, 0.4, 0.6, 0.25)),
            (0.2, 0.4, 0.6, 0.25),
        )


class TestPalette(unittest.TestCase):
    def assertRgbAlmostEqual(self, a, b, places=5):
        for x, y in zip(a[:3], b[:3]):
            self.assertAlmostEqual(x, y, places=places)

    def test_default_steps_and_empty_uses_plasma(self):
        from scena.gradient_presets import get_preset

        p = Palette()
        self.assertEqual(len(p), 6)
        self.assertEqual(repr(p), 'Palette(6 swatches)')
        stops = get_preset('plasma')
        named = Palette('plasma')
        self.assertRgbAlmostEqual(p[0].rgb, named[0].rgb)
        self.assertRgbAlmostEqual(p[-1].rgb, named[-1].rgb)
        self.assertRgbAlmostEqual(p[0].rgb, stops[0][1])
        self.assertRgbAlmostEqual(p[5].rgb, stops[-1][1])

    def test_preset_case_insensitive_and_steps(self):
        a = Palette('Plasma', steps=4)
        b = Palette('plasma', steps=4)
        self.assertEqual(len(a), 4)
        self.assertEqual([c.rgb for c in a], [c.rgb for c in b])

    def test_list_and_varargs_colors_match(self):
        listed = Palette(['red', 'yellow', 'blue'], steps=3)
        varargs = Palette('red', 'yellow', 'blue', steps=3)
        self.assertEqual(len(listed), len(varargs))
        for a, b in zip(listed, varargs):
            self.assertRgbAlmostEqual(a.rgb, b.rgb)
        self.assertRgbAlmostEqual(listed[0].rgb, Color('red').rgb)
        self.assertRgbAlmostEqual(listed[2].rgb, Color('blue').rgb)

    def test_explicit_stops(self):
        p = Palette([(0.0, 'navy'), (1.0, 'white')], steps=2)
        self.assertRgbAlmostEqual(p[0].rgb, Color('navy').rgb)
        self.assertRgbAlmostEqual(p[1].rgb, Color('white').rgb)

    def test_from_colormap_and_gradient(self):
        from scena.style import Gradient

        ramp = Colormap.from_colors('red', 'blue')
        from_cm = Palette(ramp, steps=3)
        from_g = Palette(Gradient('sunset'), steps=3)
        self.assertEqual(len(from_cm), 3)
        self.assertEqual(len(from_g), 3)
        self.assertRgbAlmostEqual(from_cm[0].rgb, Color('red').rgb)
        self.assertRgbAlmostEqual(from_g[0].rgb, Color(0.12, 0.05, 0.2).rgb)

    def test_single_color_builds_dark_to_light(self):
        p = Palette(Color('coral'), steps=2)
        self.assertRgbAlmostEqual(p[0].rgb, Color('coral').darker(0.3).rgb)
        self.assertRgbAlmostEqual(p[1].rgb, Color('coral').lighter(0.2).rgb)

    def test_index_wraps_and_slice_does_not(self):
        p = Palette('red', 'blue', steps=4)
        self.assertEqual(p[0].rgb, p[4].rgb)
        self.assertEqual(p[1].rgb, p[5].rgb)
        self.assertEqual(p[-1].rgb, p[3].rgb)
        sliced = p[:2]
        self.assertEqual(len(sliced), 2)
        self.assertEqual(sliced[0].rgb, p[0].rgb)

    def test_get_next_cycles_and_reset(self):
        p = Palette('red', 'blue', steps=3)
        first = [p.get_next() for _ in range(3)]
        second = [p.get_next() for _ in range(3)]
        self.assertEqual([c.rgb for c in first], [c.rgb for c in second])
        self.assertEqual(first[0].rgb, p[0].rgb)
        p.reset(1)
        self.assertEqual(p.get_next().rgb, p[1].rgb)
        p.reset(100)
        self.assertEqual(p.get_next().rgb, p[100 % 3].rgb)

    def test_iter_is_finite_and_does_not_advance_cursor(self):
        p = Palette('plasma', steps=4)
        walked = list(p)
        self.assertEqual(len(walked), 4)
        self.assertEqual(p.get_next().rgb, p[0].rgb)

    def test_colors_is_a_copy(self):
        p = Palette('plasma', steps=3)
        copy = p.colors
        copy.clear()
        self.assertEqual(len(p), 3)
        self.assertEqual(len(p.colors), 3)

    def test_random_picks_a_swatch(self):
        random.seed(21)
        p = Palette('red', 'blue', steps=3)
        allowed = {c.rgb[:3] for c in p}
        picks = {p.random().rgb[:3] for _ in range(20)}
        self.assertTrue(picks.issubset(allowed))
        self.assertGreater(len(picks), 1)

    def test_oklab_default_differs_from_rgb_midpoint(self):
        red, blue = Color('red'), Color('blue')
        p_ok = Palette('red', 'blue', steps=3)
        p_rgb = Palette('red', 'blue', steps=3, color_space=ColorSpace.RGB)
        expected_ok = Color.interpolate(red, blue, 0.5, ColorSpace.OKLAB)
        expected_rgb = Color.interpolate(red, blue, 0.5, ColorSpace.RGB)
        self.assertEqual(p_ok[1].rgb[:3], expected_ok.rgb[:3])
        self.assertEqual(p_rgb[1].rgb[:3], expected_rgb.rgb[:3])
        self.assertNotEqual(p_ok[1].rgb[:3], p_rgb[1].rgb[:3])

    def test_steps_one_samples_midpoint(self):
        p = Palette('red', 'blue', steps=1)
        mid = Color.interpolate(Color('red'), Color('blue'), 0.5)
        self.assertEqual(len(p), 1)
        self.assertEqual(p[0].rgb[:3], mid.rgb[:3])

    def test_errors(self):
        with self.assertRaises(ValueError):
            Palette('plasma', steps=0)
        with self.assertRaises(ValueError):
            Palette('totally-made-up-zzzz')
        with self.assertRaises(TypeError):
            Palette(42)
        with self.assertRaises(ValueError):
            Palette(['red'])

    def test_exported(self):
        import scena
        self.assertIn('Palette', scena.__all__)
        self.assertTrue(hasattr(scena, 'Palette'))



class TestColorEquality(unittest.TestCase):
    """A Color is a value: two equal colors compare equal however they were
    spelled (persona probes PP: a memory game compared card colors with
    ``==`` and never matched, ``Color("red") == Color("red")`` was False)."""

    def test_equal_colors_compare_equal_and_hash_alike(self):
        a, b = Color("red"), Color("#ff0000")
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b, Color(1, 0, 0), Color((1, 0, 0, 1))}), 1)
        self.assertEqual({a: "x"}[Color("red")], "x")
        self.assertNotEqual(Color("red"), Color("blue"))
        self.assertNotEqual(Color("red"), Color("red").with_alpha(0.5))

    def test_any_color_spelling_compares(self):
        c = Color("red")
        for same in ("red", "Red", "#ff0000", "#FF0000FF", (1, 0, 0), (1, 0, 0, 1), [1, 0, 0]):
            self.assertTrue(c == same, same)
            self.assertFalse(c != same, same)
        self.assertTrue(Color("dark red") == "dark red")
        self.assertFalse(c == "blue")
        self.assertTrue("red" == c)            # reflected

    def test_no_color(self):
        self.assertEqual(Color(None), Color(None))
        self.assertNotEqual(Color(None), Color("black"))
        self.assertNotEqual(Color(0, 0, 0, 0), Color(None))

    def test_not_a_color_is_unequal_and_silent(self):
        c = Color("red")
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            for other in ("auto", "none", "", (255, 0, 0), (1, 0), 5, None, object(), "#zz0000"):
                self.assertFalse(c == other, other)
                self.assertTrue(c != other, other)

    def test_a_near_typo_warns_once_and_is_unequal(self):
        c = Color("yellow")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            self.assertFalse(c == "yelow")
            self.assertFalse(c == "yelow")
        msgs = [str(x.message) for x in w]
        self.assertEqual(len(msgs), 1, msgs)
        self.assertIn("yellow", msgs[0])

    def test_repr_shows_the_channels(self):
        self.assertEqual(repr(Color("red")), str(Color("red")))
        self.assertIn("r=1.000", repr(Color("red")))
        self.assertEqual(repr(Color(None)), "Color(none)")


class TestCssNames(unittest.TestCase):
    """The CSS / X11 base names learners guess resolve exactly (persona
    probes PP: beige went magenta, midnight blue went blue); a dark / light
    prefix stays Scena's modifier."""

    CSS_BASES = ("alice blue", "antique white", "aquamarine", "azure", "beige", "bisque",
                 "blanched almond", "burlywood", "chartreuse", "cornsilk", "floral white",
                 "fuchsia", "gainsboro", "ghost white", "honeydew", "ivory", "lavender blush",
                 "linen", "medium aquamarine", "medium blue", "medium purple",
                 "medium sea green", "medium slate blue", "medium spring green",
                 "medium turquoise", "medium violet red", "midnight blue", "mint cream",
                 "misty rose", "moccasin", "navajo white", "old lace", "olive drab",
                 "orange red", "pale goldenrod", "pale green", "pale turquoise",
                 "pale violet red", "papaya whip", "peach puff", "powder blue",
                 "rebecca purple", "rosy brown", "saddle brown", "seashell", "slate blue",
                 "slate gray", "slate grey", "snow", "spring green", "thistle", "wheat",
                 "white smoke")

    def test_css_bases_resolve_exactly_in_every_spelling(self):
        for name in self.CSS_BASES:
            for spelling in (name, name.replace(" ", ""), name.title().replace(" ", "")):
                self.assertEqual(ColorNames.resolve(spelling).kind, ColorResolveKind.EXACT, spelling)
        self.assertEqual(Color("saddlebrown"), "#8b4513")
        self.assertEqual(Color("midnight blue"), "#191970")

    def test_css_dark_light_compounds_are_modifiers_without_a_warning(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            for name in ("darkslategray", "dark slate blue", "dark olive green",
                         "lightslategray", "light steel blue", "dark orange"):
                self.assertEqual(ColorNames.resolve(name).kind, ColorResolveKind.MODIFIER, name)
                Color(name)

    def test_the_guia_shows_every_name(self):
        import re
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "docs", "pt", "guide", "index.html"), encoding="utf-8") as fh:
            html = fh.read()
        sec = html[html.index("<summary>Nomes de cor</summary>"):
                   html.index("<summary>Presets de Gradient</summary>")]
        shown = set(re.findall(r'<div class="color-label">([^<]+)</div>', sec))
        self.assertEqual(set(ColorNames._COLORS) - shown, set())
        self.assertEqual(shown - set(ColorNames._COLORS), set())

if __name__ == '__main__':
    unittest.main()
