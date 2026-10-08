"""Image path resolve: absolute, script dir, script/media/, cwd. No recurse."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from scena.sprite import _resolve_image_path


def _touch(path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"x")
    return path


class TestResolveImagePath(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = self._tmp.name
        self.script = os.path.join(root, "game")
        self.media = os.path.join(self.script, "media")
        self.cwd = os.path.join(root, "launch")
        os.makedirs(self.media)
        os.makedirs(self.cwd)
        self._old_cwd = os.getcwd()
        os.chdir(self.cwd)

    def tearDown(self):
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def test_absolute_existing_wins_over_script_and_cwd(self):
        elsewhere = _touch(os.path.join(self._tmp.name, "other", "hero.png"))
        _touch(os.path.join(self.script, "hero.png"))
        _touch(os.path.join(self.cwd, "hero.png"))
        with patch("scena.sprite._script_dir", return_value=self.script):
            hit = _resolve_image_path(elsewhere)
        self.assertEqual(os.path.realpath(hit), os.path.realpath(elsewhere))

    def test_absolute_missing_does_not_search(self):
        _touch(os.path.join(self.script, "hero.png"))
        _touch(os.path.join(self.cwd, "hero.png"))
        missing = os.path.join(self._tmp.name, "nope", "hero.png")
        with patch("scena.sprite._script_dir", return_value=self.script):
            self.assertIsNone(_resolve_image_path(missing))

    def test_script_folder_before_cwd(self):
        script_hit = _touch(os.path.join(self.script, "hero.png"))
        _touch(os.path.join(self.cwd, "hero.png"))
        with patch("scena.sprite._script_dir", return_value=self.script):
            hit = _resolve_image_path("hero.png")
        self.assertEqual(os.path.realpath(hit), os.path.realpath(script_hit))

    def test_script_media_when_not_beside_script(self):
        media_hit = _touch(os.path.join(self.media, "hero.png"))
        _touch(os.path.join(self.cwd, "hero.png"))
        with patch("scena.sprite._script_dir", return_value=self.script):
            hit = _resolve_image_path("hero.png")
        self.assertEqual(os.path.realpath(hit), os.path.realpath(media_hit))

    def test_as_written_under_script_media(self):
        nested = _touch(os.path.join(self.media, "sprites", "space", "ship.png"))
        with patch("scena.sprite._script_dir", return_value=self.script):
            hit = _resolve_image_path("sprites/space/ship.png")
        self.assertEqual(os.path.realpath(hit), os.path.realpath(nested))

    def test_cwd_last(self):
        cwd_hit = _touch(os.path.join(self.cwd, "hero.png"))
        with patch("scena.sprite._script_dir", return_value=self.script):
            hit = _resolve_image_path("hero.png")
        self.assertEqual(os.path.realpath(hit), os.path.realpath(cwd_hit))

    def test_cwd_when_no_script(self):
        cwd_hit = _touch(os.path.join(self.cwd, "hero.png"))
        with patch("scena.sprite._script_dir", return_value=None):
            hit = _resolve_image_path("hero.png")
        self.assertEqual(os.path.realpath(hit), os.path.realpath(cwd_hit))

    def test_does_not_recurse_into_media(self):
        _touch(os.path.join(self.media, "sprites", "space", "hero.png"))
        with patch("scena.sprite._script_dir", return_value=self.script):
            self.assertIsNone(_resolve_image_path("hero.png"))

    def test_empty_and_non_str(self):
        self.assertIsNone(_resolve_image_path(""))
        self.assertIsNone(_resolve_image_path(None))  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
