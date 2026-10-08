"""File patterns as frame sources: ``Sheet("ninja/Run__*.png")`` and
``sheet.strip("correndo", "ninja/Run__*.png", fps=12)``.

A filename with ``*`` is a list of files written short, legal exactly where a
list of files is (``Sheet`` source / extra files, ``strip`` source) and meaning
that list: natural order, ``*`` only, file name only, case-sensitive, first
image-search folder with a match, zero matches → one placeholder cell and one
warning. Layout keywords with a pattern are a ``TypeError`` decided from the
call, never from the disk. ``Sprite`` / ``SpriteButton`` (one file) refuse it.
Design: Sprite Design.md, "Author ladder (Sheet vs Sprite)".

    python -m unittest tests.test_sheet_patterns -v
"""
import os
import unittest
import warnings
from unittest.mock import patch

import skia

from scena import Sheet, Sprite, SpriteButton
from scena.sprite import (
    _expand_file_list, _natural_key, _pattern_matches, _pattern_regex,
)
from tests.media_support import MEDIA
from tests.test_sprite import SpriteTestCase, _frame, _write_rect_png


def _caught(fn):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = fn()
    return out, [str(w.message) for w in caught]


class PatternTestCase(SpriteTestCase):
    def setUp(self):
        super().setUp()
        self.root = self._tmp.name
        # The image search starts next to the running script: make it the tmp root.
        p = patch("scena.sprite._script_dir", return_value=self.root)
        p.start()
        self.addCleanup(p.stop)

    def png(self, rel, w=8, h=8):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _write_rect_png(path, w, h)
        return path

    def pack(self, folder="ninja", prefix="Run__", n=3, w=8, h=8):
        return [self.png(f"{folder}/{prefix}{i:03d}.png", w, h) for i in range(n)]


class TestMatching(PatternTestCase):
    def test_natural_order_padded_and_unpadded(self):
        for name in ("Run (10).png", "Run (2).png", "Run (1).png"):
            self.png(f"robot/{name}")
        for name in ("Fly_010.png", "Fly_2.png", "Fly_001.png"):
            self.png(f"bee/{name}")
        files, _ = _pattern_matches("robot/Run (*).png")
        self.assertEqual([os.path.basename(f) for f in files],
                         ["Run (1).png", "Run (2).png", "Run (10).png"])
        files, _ = _pattern_matches("bee/Fly_*.png")
        self.assertEqual([os.path.basename(f) for f in files],
                         ["Fly_001.png", "Fly_2.png", "Fly_010.png"])

    def test_natural_key_is_total(self):
        names = ["b2", "a10", "A2", "a2", "10", "2", "a", ""]
        self.assertEqual(sorted(names, key=_natural_key),
                         ["", "2", "10", "a", "A2", "a2", "a10", "b2"])

    def test_star_is_the_only_wildcard(self):
        rx = _pattern_regex("Run [*].png")
        self.assertIsNotNone(rx.fullmatch("Run [1].png"))
        self.assertIsNone(rx.fullmatch("Run 1.png"))
        self.assertIsNone(_pattern_regex("a?b_*.png").fullmatch("axb_1.png"))
        self.assertIsNotNone(_pattern_regex("a?b_*.png").fullmatch("a?b_1.png"))
        self.assertIsNone(_pattern_regex("Run_*.png").fullmatch("Run_1xpng"))
        self.assertIsNotNone(_pattern_regex("Run_*.png").fullmatch("Run_.png"))

    def test_literal_brackets_on_disk(self):
        self.png("pack/Run [1].png")
        self.png("pack/Run [2].png")
        self.png("pack/Run 3.png")
        files, _ = _pattern_matches("pack/Run [*].png")
        self.assertEqual([os.path.basename(f) for f in files],
                         ["Run [1].png", "Run [2].png"])

    def test_matching_is_case_sensitive(self):
        self.pack(prefix="Idle__")
        files, _ = _pattern_matches("ninja/idle__*.png")
        self.assertEqual(files, [])

    def test_dot_files_and_folders_never_join(self):
        self.pack(prefix="Run__", n=2)
        self.png("ninja/._Run__000.png")            # macOS AppleDouble copy
        os.makedirs(os.path.join(self.root, "ninja", "Run__999.png"))
        files, _ = _pattern_matches("ninja/*Run__*.png")
        self.assertEqual([os.path.basename(f) for f in files],
                         ["Run__000.png", "Run__001.png"])
        files, _ = _pattern_matches("ninja/.*.png")
        self.assertEqual([os.path.basename(f) for f in files], ["._Run__000.png"])

    def test_first_folder_with_a_match_wins_never_mixed(self):
        self.pack(folder="ninja", n=2)
        self.pack(folder="media/ninja", n=5)
        files, folders = _pattern_matches("ninja/Run__*.png")
        self.assertEqual(len(files), 2)
        self.assertTrue(all(os.path.dirname(f) == os.path.join(self.root, "ninja")
                            for f in files))
        self.assertEqual(folders, [os.path.join(self.root, "ninja")])

    def test_falls_through_to_media_then_cwd(self):
        self.pack(folder="media/ninja", n=4)
        files, folders = _pattern_matches("ninja/Run__*.png")
        self.assertEqual(len(files), 4)
        self.assertEqual(os.path.dirname(files[0]),
                         os.path.join(self.root, "media", "ninja"))
        self.assertEqual(folders[:2], [os.path.join(self.root, "ninja"),
                                       os.path.join(self.root, "media", "ninja")])

    def test_absolute_pattern_is_that_folder_only(self):
        paths = self.pack(folder="elsewhere", n=3)
        self.pack(folder="media/elsewhere", n=5)
        pattern = os.path.join(os.path.dirname(paths[0]), "Run__*.png")
        files, folders = _pattern_matches(pattern)
        self.assertEqual(files, paths)
        self.assertEqual(folders, [os.path.dirname(paths[0])])

    def test_plain_names_pass_through_expansion_in_place(self):
        self.pack(n=2)
        out = _expand_file_list(["a.png", "ninja/Run__*.png", "b.png"])
        self.assertEqual(out[0], "a.png")
        self.assertEqual(out[-1], "b.png")
        self.assertEqual([os.path.basename(p) for p in out[1:3]],
                         ["Run__000.png", "Run__001.png"])


class TestStripPattern(PatternTestCase):
    def test_one_clip_per_pattern(self):
        self.pack(prefix="Idle__", n=4)
        self.pack(prefix="Run__", n=3)
        sheet = Sheet()
        self.assertIs(sheet.strip("parado", "ninja/Idle__*.png", fps=8), sheet)
        sheet.strip("correndo", "ninja/Run__*.png", fps=12)
        self.assertEqual(sheet.nframes, 7)
        self.assertEqual(sheet._cycles["parado"], ([0, 1, 2, 3], 8.0, False))
        self.assertEqual(sheet._cycles["correndo"], ([4, 5, 6], 12.0, False))
        # Frames are named by file stem, as in a multi-file Sheet.
        self.assertEqual(sheet.names[4:], ("Run__000", "Run__001", "Run__002"))
        self.assertEqual(sheet.frame_index("Run__001"), 5)
        self.assertEqual(sheet.frame_index("ninja/Run__001.png"), 5)

    def test_pattern_clip_plays_and_switches(self):
        self.pack(prefix="Idle__", n=4)
        self.pack(prefix="Run__", n=3)
        sheet = Sheet()
        sheet.strip("parado", "ninja/Idle__*.png", fps=10)
        sheet.strip("correndo", "ninja/Run__*.png", fps=10)
        s = self.track(Sprite(sheet, height=20))
        self.assertEqual(s.frame, 0)            # two clips: still until play
        s.play("correndo")
        seen = set()
        for _ in range(6):
            seen.add(s.frame)
            _frame(0.1)
        self.assertEqual(seen, {4, 5, 6})
        s.play("parado")
        seen = set()
        for _ in range(8):
            seen.add(s.frame)
            _frame(0.1)
        self.assertEqual(seen, {0, 1, 2, 3})

    def test_different_sizes_keep_anchor_and_pixel_size(self):
        self.png("ninja/Idle__000.png", 20, 40)
        self.png("ninja/Idle__001.png", 20, 40)
        self.png("ninja/Dead__000.png", 40, 10)
        sheet = Sheet(anchor="bottom", pixel_size=0.5)
        sheet.strip("parado", "ninja/Idle__*.png", fps=8)
        sheet.strip("morto", "ninja/Dead__*.png", fps=8)
        for i in range(3):
            fr = sheet._frame_at(i)
            self.assertAlmostEqual(float(fr.pivot_x), 0.5)
            self.assertAlmostEqual(float(fr.pivot_y), 1.0)   # y-down: the feet
        s = self.track(Sprite(sheet, center=(0, 0)))
        self.assertAlmostEqual(float(s.height), 20.0)
        self.assertAlmostEqual(float(s.width), 10.0)
        s.play("morto")
        self.assertAlmostEqual(float(s.height), 5.0)
        self.assertAlmostEqual(float(s.width), 20.0)
        cx, cy, _w, h, _a = s._oriented_frame()
        self.assertAlmostEqual(cy - h / 2, 0.0)       # feet on the center

    def test_offset_on_a_pattern_strip(self):
        self.png("ninja/Dead__000.png", 20, 20)
        sheet = Sheet(pixel_size=1)
        sheet.strip("morto", "ninja/Dead__*.png", fps=8, offset=(0, -4))
        s = self.track(Sprite(sheet, center=(0, 0)))
        _cx, cy, _w, _h, _a = s._oriented_frame()
        self.assertAlmostEqual(cy, -4.0)

    def test_hitbox_source_sees_pattern_frames(self):
        self.pack(prefix="Idle__", n=2)
        self.pack(prefix="Run__", n=3)
        sheet = Sheet()
        sheet.strip("parado", "ninja/Idle__*.png", fps=8)
        sheet.strip("correndo", "ninja/Run__*.png", fps=8)
        s_all = self.track(Sprite(sheet, height=20, hitbox_source="all"))
        self.assertEqual(s_all._hitbox_from_indices(), (0, 1, 2, 3, 4))
        s_clip = self.track(Sprite(sheet, height=20, hitbox_source="clip"))
        s_clip.play("correndo")
        self.assertEqual(s_clip._hitbox_from_indices(), (2, 3, 4))
        s_named = self.track(Sprite(sheet, height=20, hitbox_source=("correndo",)))
        self.assertEqual(s_named._hitbox_from_indices(), (2, 3, 4))

    def test_list_source_is_one_file_per_frame(self):
        a, b = self.png("a.png", 8, 8), self.png("b.png", 12, 8)
        sheet = Sheet().strip("voo", [a, b], fps=6)
        self.assertEqual(sheet.names, ("a", "b"))
        self.assertEqual(sheet._cycles["voo"][0], [0, 1])
        self.assertEqual(int(sheet._frame_at(1).src_w), 12)

    def test_one_item_list_is_that_file(self):
        path = self.png("walk.png", 32, 8)
        sheet = Sheet().strip("walk", [path], cols=4, fps=6)
        self.assertEqual(sheet.nframes, 4)
        self.assertEqual(sheet.names[0], "walk:0")

    def test_bad_lists(self):
        sheet = Sheet()
        with self.assertRaises(ValueError):
            sheet.strip("x", [])
        with self.assertRaises(TypeError):
            sheet.strip("x", ["a.png", 3])
        with self.assertRaises(TypeError):
            sheet.strip("x", ["a.png", "sheet.xml"])
        with self.assertRaises(TypeError) as ctx:
            sheet.strip("x", 3)
        self.assertIn("pattern", str(ctx.exception))

    def test_single_image_strip_unchanged(self):
        grid = self.png("walk.png", 32, 8)
        one = self.png("jump.png", 8, 8)
        sheet = Sheet()
        sheet.strip("walk", grid, cols=4, fps=12)
        sheet.strip("jump", one, fps=6)
        self.assertEqual(sheet.nframes, 5)
        self.assertEqual(sheet.names, ("walk:0", "walk:1", "walk:2", "walk:3", "jump:0"))
        self.assertEqual(sheet._cycles["walk"], ([0, 1, 2, 3], 12.0, False))
        self.assertEqual(sheet._cycles["jump"], ([4], 6.0, False))
        self.assertEqual(len(sheet._images), 2)
        self.assertEqual(int(sheet._cell_w), 8)

    def test_strip_after_a_grid_sheet(self):
        grid = self.png("idle.png", 16, 8)
        self.pack(prefix="Run__", n=3)
        sheet = Sheet(grid, cols=2, fps=6, name="idle")
        sheet.strip("run", "ninja/Run__*.png", fps=12)
        self.assertEqual(sheet.nframes, 5)
        self.assertEqual(sheet._cycles["run"][0], [2, 3, 4])
        self.assertEqual(sheet._frame_image, (0, 0, 1, 1, 1))


class TestZeroMatches(PatternTestCase):
    def test_strip_placeholder_and_one_warning(self):
        sheet, msgs = _caught(
            lambda: Sheet().strip("parado", "ninja/Idle__*.png", fps=8))
        self.assertEqual(sheet.nframes, 1)
        self.assertTrue(sheet._placeholder)
        self.assertEqual(sheet._cycles["parado"][0], [0])
        self.assertEqual(len(msgs), 1, msgs)
        self.assertIn("'ninja/Idle__*.png'", msgs[0])
        self.assertIn(os.path.join(self.root, "ninja"), msgs[0])
        self.assertIn(os.path.join(self.root, "media", "ninja"), msgs[0])
        self.assertIn(os.path.join(os.getcwd(), "ninja"), msgs[0])
        # Warn once per pattern; the clip still plays.
        _again, msgs = _caught(
            lambda: Sheet().strip("parado", "ninja/Idle__*.png", fps=8))
        self.assertEqual(msgs, [])
        s = self.track(Sprite(sheet, height=20))
        s.play("parado")
        _frame(0.2)
        self.assertEqual(s.frame, 0)

    def test_sheet_placeholder_and_one_warning(self):
        sheet, msgs = _caught(lambda: Sheet("robot/Run (*).png", fps=12))
        self.assertEqual(sheet.nframes, 1)
        self.assertTrue(sheet._placeholder)
        self.assertIn("default", sheet._cycles)
        self.assertEqual(len(msgs), 1, msgs)
        self.assertIn("'robot/Run (*).png'", msgs[0])

    def test_case_near_miss_is_named(self):
        self.pack(prefix="Idle__", n=2)
        _sheet, msgs = _caught(lambda: Sheet().strip("p", "ninja/idle__*.png"))
        self.assertEqual(len(msgs), 1, msgs)
        self.assertIn("case", msgs[0])
        self.assertIn("Idle__000.png", msgs[0])

    def test_zero_matches_among_other_files(self):
        a = self.png("a.png")
        sheet, msgs = _caught(lambda: Sheet(a, "nothing/x_*.png"))
        self.assertEqual(sheet.nframes, 2)
        self.assertEqual(len(msgs), 1, msgs)


class TestRefusals(PatternTestCase):
    def test_layout_keywords_with_a_pattern(self):
        self.pack(n=1)                         # one match: still one file per frame
        for kw in ({"cols": 2}, {"cols": 2, "rows": 1}, {"cell": (8, 8)}):
            for pattern in ("ninja/Run__*.png", "nothing/x_*.png"):
                with self.subTest(kw=kw, pattern=pattern):
                    sheet = Sheet()
                    _out, msgs = _caught(lambda: self.assertRaises(
                        TypeError, sheet.strip, "run", pattern, **kw))
                    self.assertEqual(msgs, [])     # decided before the disk
                    with self.assertRaises(TypeError) as ctx:
                        sheet.strip("run", pattern, **kw)
                    text = str(ctx.exception)
                    self.assertIn(pattern, text)
                    self.assertIn('sheet.strip("walk", "walk.png", cols=8', text)
                    with self.assertRaises(TypeError) as ctx:
                        Sheet(pattern, **kw)
                    self.assertIn(pattern, str(ctx.exception))

    def test_layout_keywords_with_a_list_in_strip(self):
        a, b = self.png("a.png"), self.png("b.png")
        with self.assertRaises(TypeError) as ctx:
            Sheet().strip("x", [a, b], cols=2)
        self.assertIn('sheet.strip("walk", "walk.png", cols=8', str(ctx.exception))

    def test_star_in_a_folder(self):
        with self.assertRaises(ValueError) as ctx:
            Sheet().strip("run", "ninja*/Run__000.png")
        self.assertIn("file name only", str(ctx.exception))
        with self.assertRaises(ValueError):
            Sheet("*/Run__*.png")

    def test_pattern_of_atlas_files(self):
        with self.assertRaises(TypeError):
            Sheet("sheets/*.xml")
        with self.assertRaises(TypeError):
            Sheet().strip("x", "sheets/*.json")

    def test_pattern_with_atlas_keyword(self):
        with self.assertRaises(TypeError):
            Sheet("ninja/Run__*.png", atlas="sheet.xml")

    def test_sprite_source_refuses_a_pattern(self):
        self.pack(n=2)
        with self.assertRaises(TypeError) as ctx:
            Sprite("ninja/Run__*.png")
        self.assertIn('Sprite(Sheet(\'ninja/Run__*.png\'', str(ctx.exception))

        class Ninja(Sprite, source="ninja/Run__*.png"):
            pass
        with self.assertRaises(TypeError):
            Ninja()

    def test_sprite_button_art_refuses_a_pattern(self):
        self.pack(n=2)
        btn = self.png("button.png")
        with self.assertRaises(TypeError):
            SpriteButton("ninja/Run__*.png")
        with self.assertRaises(TypeError) as ctx:
            SpriteButton(btn, hover="ninja/Run__*.png")
        self.assertIn("one file per state", str(ctx.exception))
        with self.assertRaises(TypeError):
            SpriteButton("ninja/Run__*.png", hover=btn)

    def test_interned_still_refuses_strip(self):
        path = self.png("potion.png")
        s = self.track(Sprite(path, height=10))
        with self.assertRaises(TypeError):
            s.sheet.strip("x", "ninja/Run__*.png")


class TestEveryCatalogPath(PatternTestCase):
    """Every catalog-loading path that takes a file list takes a pattern, and
    the pattern means the list it matches."""

    def test_same_frames_from_every_path(self):
        files = self.pack(n=3)
        expected = ("Run__000", "Run__001", "Run__002")
        pat = "ninja/Run__*.png"
        builders = {
            "Sheet(pattern)": lambda: Sheet(pat),
            "Sheet(source=pattern)": lambda: Sheet(source=pat),
            "Sheet([pattern])": lambda: Sheet([pat]),
            "Sheet(pattern, fps=)": lambda: Sheet(pat, fps=8),
            "Sheet(list of files)": lambda: Sheet(files),
            "strip(pattern)": lambda: Sheet().strip("run", pat),
            "strip([pattern])": lambda: Sheet().strip("run", [pat]),
            "strip(list of files)": lambda: Sheet().strip("run", files),
        }
        for label, build in builders.items():
            with self.subTest(label):
                sheet, msgs = _caught(build)
                self.assertEqual(msgs, [])
                self.assertEqual(sheet.names, expected)
                self.assertFalse(sheet._placeholder)

    def test_pattern_expands_in_place_among_files(self):
        self.pack(n=2)
        a, b = self.png("a.png"), self.png("b.png")
        self.assertEqual(Sheet(a, "ninja/Run__*.png", b).names,
                         ("a", "Run__000", "Run__001", "b"))
        self.assertEqual(Sheet([a, "ninja/Run__*.png"]).names,
                         ("a", "Run__000", "Run__001"))

    def test_one_match_sheet_autoplays(self):
        self.pack(n=1)
        sheet = Sheet("ninja/Run__*.png", fps=8)
        self.assertEqual(sheet.nframes, 1)
        s = self.track(Sprite(sheet, height=10))
        self.assertEqual(s._play_name, "default")


class TestNinjaPack(SpriteTestCase):
    """The taught pack (``examples/media/ninja``): each prefix is one animation;
    ``Jump__*`` does not take ``Jump_Throw__*`` / ``Jump_Attack__*``."""

    def test_taught_patterns(self):
        folder = os.path.join(MEDIA, "ninja")
        expect = {"Idle__": 10, "Run__": 10, "Jump__": 10, "Jump_Throw__": 10,
                  "Dead__": 10, "Climb_": 10}
        for prefix, n in expect.items():
            with self.subTest(prefix):
                files, _ = _pattern_matches(os.path.join(folder, prefix + "*.png"))
                self.assertEqual(len(files), n)
                names = [os.path.basename(f) for f in files]
                self.assertEqual(names, [f"{prefix}{i:03d}.png" for i in range(n)])


if __name__ == "__main__":
    unittest.main()


class TestSheetFrames(PatternTestCase):
    """Graphics review (2026-10-08), Sheet frames: PA3, PA4, PA6, PA7, PA9, PA13."""

    def test_two_files_with_one_name_keep_their_paths(self):
        """PA3: ``idle/1.png`` and ``run/1.png`` are both "1": the last won,
        even for the exact path that loaded the first."""
        idle, run = self.png("idle/1.png", 8, 8), self.png("run/1.png", 16, 16)
        sheet = Sheet([idle, run])
        self.assertEqual(sheet.frame_index(idle), 0)
        self.assertEqual(sheet.frame_index(run), 1)
        self.assertEqual(sheet.frame_index("idle/1.png"), 0)
        with self.assertRaisesRegex(ValueError, "names 2 frames"):
            sheet.frame_index("1.png")
        with self.assertRaisesRegex(ValueError, "names 2 frames"):
            sheet.clip("one", ["1"], fps=4)

    def test_strip_per_folder_keeps_each_path(self):
        a = [self.png(f"idle/{i}.png") for i in (1, 2)]
        b = [self.png(f"run/{i}.png") for i in (1, 2)]
        sheet = Sheet()
        sheet.strip("idle", a, fps=4)
        sheet.strip("run", b, fps=4)
        self.assertEqual([sheet.frame_index(p) for p in a + b], [0, 1, 2, 3])
        with self.assertRaisesRegex(ValueError, "names 2 frames"):
            sheet.frame_index("2")

    def test_an_empty_sheet_names_no_cell(self):
        """PA4: an empty ``Sheet()`` took any index; the draw wrapped it."""
        with self.assertRaisesRegex(ValueError, "no cells yet"):
            Sheet().clip("a", [3], fps=4)

    def test_re_registering_a_clip_replaces_its_offset(self):
        """PA6: re-registering "a" clashed with its own old offset, or kept it
        after ``offset=`` was dropped."""
        sheet = Sheet(self.png("g.png", 64, 16), cell=(16, 16))
        sheet.clip("a", [0, 1], fps=4, offset=(3, 0))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")          # "clip replaced"
            sheet.clip("a", [0, 1], fps=4, offset=(5, 0))
            self.assertEqual(sheet._frame_offsets, {0: (5.0, 0.0), 1: (5.0, 0.0)})
            sheet.clip("a", [0, 1], fps=4)
        self.assertEqual(sheet._frame_offsets, {})
        sheet.clip("b", [1], fps=4, offset=(2, 0))
        with self.assertRaisesRegex(ValueError, "one offset"):
            sheet.clip("c", [1], fps=4, offset=(9, 0))

    def test_showing_refuses_a_bool_after_an_int(self):
        """PA7: ``True == 1`` shared the selector cache entry."""
        sheet = Sheet(self.png("g.png", 64, 16), cell=(16, 16))
        s = self.track(Sprite(sheet, center=(0, 0), height=16))
        s.showing(1)
        with self.assertRaises(TypeError):
            s.showing(True)
        with self.assertRaises(TypeError):
            s.showing((1, True))

    def test_a_path_that_only_matches_by_case_warns(self):
        """PA9: on a disk that ignores case, "G.PNG" opened g.png (missing on
        Linux) and got a second cache entry."""
        path = self.png("g.png", 16, 16)
        upper = os.path.join(os.path.dirname(path), "G.PNG")
        if not os.path.isfile(upper):
            self.skipTest("this disk tells letter case apart")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            Sheet(upper, cell=(16, 16))
        self.assertTrue(any("letter case" in str(w.message) for w in caught))
        from scena.sprite import _resolve_image_path
        self.assertEqual(_resolve_image_path(upper), path)

    def test_a_missing_file_with_cell_keeps_its_clips(self):
        """PA13: a missing file with ``cell=`` has one checker cell; "missing
        stays legal" broke at the first clip past cell 0."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sheet = Sheet(os.path.join(self.root, "nope.png"), cell=(16, 16))
        sheet.clip("walk", [0, 1, 2], fps=4)
        s = self.track(Sprite(sheet, center=(0, 0), height=16))
        s.play("walk")
