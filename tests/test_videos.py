"""videos/: the scripts and texts are tracked; what they render is not.

The video scripts are run by hand (they render minutes of video), so these
checks hold what a render would find first: every script compiles, each
video folder reaches the examples' art through its ``media`` link, a cue
sheet written before videos/ still finds its takes, finish.py's levelling
decision, and the rendered folders stay out of git.

    python -m unittest tests.test_videos -v
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest

from tests import repo_layout as layout
from tests.source_support import iter_entries, iter_files

VIDEOS = os.path.join(layout.ROOT, "videos")
SCRIPTS = os.path.join(VIDEOS, "scripts")
KIT = os.path.join(SCRIPTS, "kit")
sys.path.insert(0, KIT)
import paths      # noqa: E402
import finish     # noqa: E402


class TestScripts(unittest.TestCase):

    def test_every_script_compiles(self):
        files = iter_files(SCRIPTS, ".py", recursive=True)
        self.assertGreater(len(files), 20)
        for path in files:
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
            with self.subTest(os.path.relpath(path, layout.ROOT)):
                compile(source, path, "exec")

    def test_each_video_folder_links_the_examples_media(self):
        want = os.path.realpath(os.path.join(layout.ROOT, "examples", "media"))
        folders = [n for n in iter_entries(SCRIPTS)
                   if n != "kit" and os.path.isdir(os.path.join(SCRIPTS, n))]
        self.assertIn("teaser3", folders)
        for name in folders:
            link = os.path.join(SCRIPTS, name, "media")
            with self.subTest(name):
                if os.path.isfile(link) and not os.path.islink(link):
                    self.skipTest("git checked the link out as a file (core.symlinks off)")
                self.assertTrue(os.path.islink(link), f"{name}/media is not a link")
                self.assertEqual(os.path.realpath(link), want)


class TestPaths(unittest.TestCase):

    def test_folders(self):
        self.assertEqual(paths.REPO, layout.ROOT)
        self.assertEqual(paths.RECORDINGS, os.path.join(VIDEOS, "recordings"))
        self.assertEqual(paths.FINALS, os.path.join(VIDEOS, "finals"))

    def test_cue_sheets_from_before_videos_still_resolve(self):
        def at(*parts):
            return os.path.normpath(os.path.join(paths.RECORDINGS, *parts))
        for cue, want in (("guardian/waves.mp4", at("guardian", "waves.mp4")),
                          ("recordings/guardian/waves.mp4", at("guardian", "waves.mp4")),
                          ("recordings/code_video/stars_1.mp4", at("code", "stars_1.mp4"))):
            self.assertEqual(os.path.normpath(paths.recording(cue)), want)

    def test_record_game_writes_into_videos_recordings(self):
        with open(os.path.join(layout.ROOT, "tools", "video", "record_game.py"),
                  encoding="utf-8") as fh:
            self.assertIn('RECORDINGS = REPO / "videos" / "recordings"', fh.read())


class TestFinishLevel(unittest.TestCase):
    """finish.gain_for: raise a quiet video, lower a loud one, move the rest."""

    def test_quiet_is_raised(self):
        self.assertAlmostEqual(finish.gain_for((-24.4, -3.0)), 10.4)

    def test_loud_is_lowered(self):
        self.assertAlmostEqual(finish.gain_for((-8.0, -0.5)), -6.0)

    def test_no_sound_silence_or_close_enough_is_moved(self):
        self.assertIsNone(finish.gain_for(None))
        self.assertIsNone(finish.gain_for((float("-inf"), float("-inf"))))
        self.assertIsNone(finish.gain_for((-70.0, -60.0)))
        self.assertIsNone(finish.gain_for((-14.09, -1.4)))


class TestRenderedOutputStaysOut(unittest.TestCase):

    RENDERED = ("videos/finals", "videos/recordings")

    def test_git_ignores_it(self):
        with open(os.path.join(layout.ROOT, ".gitignore"), encoding="utf-8") as fh:
            rules = fh.read().split()
        for name in self.RENDERED:
            self.assertIn(f"/{name}/", rules)

    def test_no_tracked_file_is_in_it(self):
        try:
            out = subprocess.run(["git", "ls-files", *self.RENDERED], cwd=layout.ROOT,
                                 capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=30)
        except (OSError, subprocess.SubprocessError):
            self.skipTest("git is not available")
        if out.returncode != 0:
            self.skipTest("not a git checkout")
        self.assertEqual(out.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
