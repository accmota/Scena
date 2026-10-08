"""Tests for the shared gradient preset table."""
import unittest

from tests.source_support import iter_files

from scena.gradient_presets import (
    GRADIENT_PRESETS,
    SCENIC_PRESET_NAMES,
    get_preset,
    normalize_preset_name,
    preset_names,
    sample_stops_rgb,
)
from scena.style import Gradient


class TestGradientPresets(unittest.TestCase):
    def test_scientific_and_scenic_present(self):
        for name in (
            "plasma", "inferno", "vrds", "coolwarm", "cool",
            "purple", "magenta", "sunset",
        ):
            self.assertIn(name, GRADIENT_PRESETS)
        for name in (
            "day", "dawn", "sunset", "dusk", "night", "space",
            "overcast", "desert", "forest", "toxic", "ember", "ice", "underwater",
        ):
            self.assertIn(name, GRADIENT_PRESETS)
            self.assertIn(name, SCENIC_PRESET_NAMES)

    def test_every_scenic_name_has_a_ramp(self):
        # The name set and the ramp table once drifted apart: SkyGradient("space")
        # raised an error whose own preset list named "space". No exemptions.
        for name in sorted(SCENIC_PRESET_NAMES):
            with self.subTest(name=name):
                self.assertIsNotNone(get_preset(name))

    def test_scenic_ramps_are_well_formed(self):
        for name in sorted(SCENIC_PRESET_NAMES):
            with self.subTest(name=name):
                stops = get_preset(name)
                self.assertGreaterEqual(len(stops), 2)
                self.assertEqual(stops[0][0], 0.0)
                self.assertEqual(stops[-1][0], 1.0)
                for pos, rgb in stops:
                    self.assertTrue(0.0 <= pos <= 1.0)
                    self.assertEqual(len(rgb), 3)
                    for c in rgb:
                        self.assertTrue(0.0 <= c <= 1.0)

    def test_creative_game_presets_present(self):
        for name in (
            "neon", "beam", "flare", "chrome",
            "synthwave", "aurora", "candy", "gold",
            "lava", "acid", "mana", "health",
        ):
            self.assertIn(name, GRADIENT_PRESETS)
            self.assertNotIn(name, SCENIC_PRESET_NAMES)
            stops = get_preset(name)
            self.assertGreaterEqual(len(stops), 3)
            self.assertEqual(stops[0][0], 0.0)
            self.assertEqual(stops[-1][0], 1.0)

    def test_get_preset_normalize(self):
        self.assertIsNotNone(get_preset("Sunset"))
        self.assertIsNotNone(get_preset("RdYl"))
        self.assertEqual(normalize_preset_name("Blue Sky"), "blue_sky")
        self.assertIsNone(get_preset("not-a-real-preset"))

    def test_preset_names_sorted(self):
        names = preset_names()
        self.assertEqual(names, tuple(sorted(names)))

    def test_sample_stops_rgb_scenic(self):
        stops = get_preset("sunset")
        self.assertEqual(len(stops), 4)
        z, h, g = sample_stops_rgb(stops)
        self.assertEqual(z, (0.12, 0.05, 0.2))
        # Middle of a 4-stop ramp is index len//2 → stop at 0.6
        self.assertEqual(h, (1, 0.78, 0.28))
        self.assertEqual(g, (0.35, 0.15, 0.18))

    def test_gradient_string_ctor_scenic(self):
        g = Gradient("sunset", angle=90)
        self.assertAlmostEqual(g._angle, 90.0)
        self.assertEqual(len(g._colors), 4)


class TestSkyPresetNamesResolve(unittest.TestCase):
    """Every sky name the API advertises, aliases, or suggests must build a sky."""

    def setUp(self):
        from scena.place import unplaced_creation

        self._unplaced = unplaced_creation()
        self._unplaced.__enter__()

    def tearDown(self):
        self._unplaced.__exit__(None, None, None)

    def test_every_sky_alias_has_a_ramp(self):
        from scena.background_kinds import _SKY_ALIASES

        for alias, target in sorted(_SKY_ALIASES.items()):
            with self.subTest(alias=alias):
                self.assertIsNotNone(get_preset(target), f"{alias} -> {target}")

    def test_every_scenic_name_and_alias_builds_a_sky(self):
        from scena.background_kinds import _SKY_ALIASES, SkyGradient, sky_palette

        for name in sorted(SCENIC_PRESET_NAMES | set(_SKY_ALIASES)):
            with self.subTest(name=name):
                sky = SkyGradient(name)
                self.assertIsNotNone(sky_palette(name))
                self.assertEqual((sky.top, sky.middle, sky.bottom), sky_palette(name))

    def test_advertised_palettes_resolve(self):
        from scena.background_kinds import SkyGradient

        for name in SkyGradient._PALETTES:
            with self.subTest(name=name):
                self.assertIsNotNone(get_preset(name))

    def test_error_message_only_offers_real_presets(self):
        import re

        from scena.background_kinds import _SKY_ALIASES, SkyGradient

        def resolves(name):
            return get_preset(_SKY_ALIASES.get(name, name)) is not None

        for typo in ("spcae", "toxc", "forrest", "sunsett", "nope"):
            with self.subTest(typo=typo):
                with self.assertRaises(ValueError) as ctx:
                    SkyGradient(typo)
                msg = str(ctx.exception)
                listed = re.search(r"Sky presets: ([^.]*)\.", msg).group(1)
                for name in listed.split(", "):
                    self.assertTrue(resolves(name), f"listed {name!r} does not resolve")
                suggested = re.search(r"Did you mean (.*)\?", msg)
                if suggested:
                    for name in re.findall(r"'([^']+)'", suggested.group(1)):
                        self.assertTrue(resolves(name), f"suggested {name!r} does not resolve")
        with self.assertRaises(ValueError) as ctx:
            SkyGradient("spcae")
        self.assertIn("'space'", str(ctx.exception))

    def test_smoke_script_sky_and_preset_strings_resolve(self):
        # Smoke scripts are not imported by the unit tests, so a stale preset
        # string there only surfaces at runtime. Scan the literals instead.
        import pathlib
        import re

        from scena.background_kinds import _SKY_ALIASES
        from scena.color import ColorNames

        smoke = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "smoke"
        sky_call = re.compile(r"SkyGradient\(\s*[\"']([^\"']+)[\"']")
        # One-name gradient recipes, e.g. (("toxic",), "linear", 55.0).
        one_preset = re.compile(r"\(\(\s*[\"']([^\"']+)[\"']\s*,\s*\)")
        for path in map(pathlib.Path, iter_files(smoke, ".py")):
            text = path.read_text(encoding="utf-8")
            for name in sky_call.findall(text):
                with self.subTest(file=path.name, sky=name):
                    key = normalize_preset_name(name)
                    ok = (
                        get_preset(_SKY_ALIASES.get(key, key)) is not None
                        or name.startswith("#")
                        or ColorNames.is_known(name)
                    )
                    self.assertTrue(ok, f"SkyGradient({name!r}) in {path.name}")
            for name in one_preset.findall(text):
                with self.subTest(file=path.name, preset=name):
                    self.assertIsNotNone(get_preset(name), f"{name!r} in {path.name}")


if __name__ == "__main__":
    unittest.main()
