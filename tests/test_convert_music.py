"""tools/media/convert_music.py: plain names, a sample-exact encode, the
license file follows the rename.

Bug classes guarded:

* **A name the license test cannot read.** ``tests/test_media_licenses``
  reads file names without spaces or parentheses; a track keeps its download
  name ("ArcLight (192 Kbps).mp3") and its credit is never checked.
* **A gap where a track loops.** The encoded track must decode to exactly as
  many frames as its source.
* **A crash on a long track.** libsndfile 1.2 segfaults on one Vorbis write
  of a few minutes of audio; the encoder writes in blocks (a long input here).
* **A rename that cuts a longer name.** Old names inside the license file are
  replaced longest first.

    python -m unittest tests.test_convert_music -v
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "media"))

import convert_music as cm  # noqa: E402
from tests.source_support import iter_files  # noqa: E402

try:
    import soundfile  # noqa: F401
except ImportError:
    soundfile = None


class TestPlainName(unittest.TestCase):

    def test_download_names(self):
        for given, want in (
                ("ArcLight (192 Kbps).mp3", "arc_light.ogg"),
                ("Juhani Junkala - Epic Boss Battle [Seamlessly Looping].wav",
                 "juhani_junkala_epic_boss_battle.ogg"),
                ("Heroic Demise (New).mp3", "heroic_demise.ogg"),
                ("little town - orchestral.ogg", "little_town_orchestral.ogg"),
                ("battleThemeA.mp3", "battle_theme_a.ogg"),
                ("TylerSong3_Normal.wav", "tyler_song3_normal.ogg"),
                ("SuperHero_original_no_Intro.ogg", "super_hero_original_no_intro.ogg"),
                ("MP3Theme.flac", "mp3_theme.ogg"),
                ("Canção à noite.wav", "cancao_a_noite.ogg"),
                ("space.flac", "space.ogg")):
            with self.subTest(given):
                self.assertEqual(cm.plain_name(given), want)

    def test_names_the_license_test_reads(self):
        from tests.test_media_licenses import _MEDIA_NAME
        name = cm.plain_name("Battle in the winter (Final) [loop].mp3")
        self.assertEqual(_MEDIA_NAME.findall(f"x {name} y"), [name])

    def test_nothing_left_refuses(self):
        with self.assertRaises(ValueError):
            cm.plain_name("(192 Kbps).mp3")


@unittest.skipUnless(soundfile, "soundfile not installed (pip install soundfile)")
class TestConvert(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def _wav(self, name, seconds, rate=44100, channels=2):
        import numpy as np
        n = int(seconds * rate) + 123           # not a whole block
        t = np.arange(n) / rate
        x = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        path = os.path.normpath(os.path.join(self.dir.name, name))
        soundfile.write(path, np.tile(x[:, None], (1, channels)), rate, subtype="PCM_16")
        return path, n

    def test_long_track_keeps_every_frame(self):
        src, n = self._wav("Long Track (WAV).wav", 200)
        dst = os.path.join(self.dir.name, "long_track.ogg")
        cm.convert(src, dst, 2.0)
        back, rate = cm._decode(dst)
        self.assertEqual((back.shape, rate), ((n, 2), 44100))
        self.assertLess(cm.kbps(dst, n, rate), 128)

    def test_apply_renames_moves_originals_and_rewrites_license(self):
        folder = os.path.join(self.dir.name, "music")
        os.makedirs(folder)
        self._wav(os.path.join("music", "Theme.wav"), 1, channels=1)
        self._wav(os.path.join("music", "Theme Song.wav"), 1)
        with open(os.path.join(folder, "License.txt"), "w", encoding="utf-8") as fh:
            fh.write("Theme Song.wav\nCC0\n---\nTheme.wav\nCC0\n")
        originals = os.path.join(self.dir.name, "kept")
        with contextlib.redirect_stdout(io.StringIO()):
            cm.main([folder, "--apply", "--originals", originals])
        self.assertEqual(_names(folder), ["License.txt", "theme.ogg", "theme_song.ogg"])
        self.assertEqual(_names(originals), ["Theme Song.wav", "Theme.wav"])
        with open(os.path.join(folder, "License.txt"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "theme_song.ogg\nCC0\n---\ntheme.ogg\nCC0\n")
        with contextlib.redirect_stdout(io.StringIO()):
            cm.main([folder, "--apply", "--originals", originals])   # small Vorbis: kept
        self.assertEqual(_names(originals), ["Theme Song.wav", "Theme.wav"])

    def test_two_names_that_collide_refuse(self):
        folder = os.path.join(self.dir.name, "music")
        os.makedirs(folder)
        self._wav(os.path.join("music", "Boss.wav"), 0.1)
        self._wav(os.path.join("music", "Boss (loop).wav"), 0.1)
        with self.assertRaises(SystemExit):
            cm.plan(folder, 128)


def _names(folder):
    return sorted(os.path.basename(p) for p in iter_files(folder))


if __name__ == "__main__":
    unittest.main()
