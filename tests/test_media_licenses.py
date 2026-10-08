"""Bundled media must say where it came from and how it may be used.

Bug class: a folder of images or sounds is copied into ``examples/media/``
without its license notice (``backgrounds/`` once had none), or a file that
needs attribution (CC-BY, CC-BY-SA) is added without a ready-to-copy credit
in ``examples/media/CREDITS.md``. Then a Scena author ships a game with the
file and cannot know they owe a credit. Nothing else turns red.

Checked:

* every folder under ``examples/media/`` that holds media has a license file
  (``license.txt`` / ``License.txt`` / ``licence.txt``);
* every top-level media folder is named in ``CREDITS.md``;
* every file that a license notice puts under an attribution license (a block
  linking ``licenses/by/`` or ``licenses/by-sa/``) is named in the
  "Attribution required" section of ``CREDITS.md``, and every file named there
  exists;
* the code license: ``LICENSE`` is MIT and ``pyproject.toml`` declares it.

    python -m unittest tests.test_media_licenses -v
"""
from __future__ import annotations

import os
import re
import unittest

from tests.source_support import iter_files

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEDIA = os.path.join(ROOT, "examples", "media")
CREDITS = os.path.join(MEDIA, "CREDITS.md")

MEDIA_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ttf", ".otf",
             ".wav", ".ogg", ".mp3", ".flac")
LICENSE_NAMES = {"license.txt", "licence.txt"}
# File names in a license notice. No spaces or parentheses: they would swallow
# "(laser4.wav" from "CC-BY 3.0 (laser4.wav, ...)"; name attribution files
# without them.
_MEDIA_NAME = re.compile(r"(?<![\w\-+@./])[\w\-+@]+\.(?:%s)\b"
                         % "|".join(e[1:] for e in MEDIA_EXT), re.IGNORECASE)
_ATTRIBUTION_LINK = re.compile(r"creativecommons\.org/licenses/by(?:-sa)?/")


def _media_dirs():
    """(directory, file names) for each directory under MEDIA (MEDIA itself
    excluded) that holds media files."""
    by_dir = {}
    for path in iter_files(MEDIA, recursive=True):
        by_dir.setdefault(os.path.dirname(path), []).append(os.path.basename(path))
    for dirpath, filenames in sorted(by_dir.items()):
        if dirpath != MEDIA and any(f.lower().endswith(MEDIA_EXT) for f in filenames):
            yield dirpath, filenames


def _license_files():
    for dirpath, filenames in _media_dirs():
        for f in filenames:
            if f.lower() in LICENSE_NAMES:
                yield os.path.join(dirpath, f)


def _attribution_section(text: str) -> str:
    start = text.index("## Attribution required")
    end = text.find("\n## ", start + 1)
    return text[start:] if end < 0 else text[start:end]


@unittest.skipUnless(os.path.isdir(MEDIA), "examples/media not present")
class TestMediaLicenses(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(CREDITS, encoding="utf-8") as fh:
            cls.credits = fh.read()
        cls.attribution = _attribution_section(cls.credits)

    def test_every_media_folder_has_a_license_file(self):
        missing = [os.path.relpath(d, MEDIA) for d, files in _media_dirs()
                   # A sub-folder of a pack may rely on its parent's notice.
                   if not any(f.lower() in LICENSE_NAMES for f in files)
                   and not any(os.path.basename(p).lower() in LICENSE_NAMES
                               for p in iter_files(os.path.dirname(d)))]
        self.assertEqual(missing, [], "media folders without license.txt")

    def test_every_top_level_folder_is_in_credits(self):
        tops = sorted({os.path.relpath(d, MEDIA).split(os.sep)[0] for d, _ in _media_dirs()})
        self.assertTrue(tops, "vacuous: no media folders found")
        missing = [d for d in tops if f"`{d}/" not in self.credits]
        self.assertEqual(missing, [], "folders not listed in CREDITS.md")

    def test_attribution_files_have_a_credit_block(self):
        needs_credit = set()
        for path in _license_files():
            folder = os.path.relpath(os.path.dirname(path), MEDIA).replace(os.sep, "/")
            with open(path, encoding="utf-8", errors="replace") as fh:
                blocks = re.split(r"\n-{3,}\n", fh.read())
            for block in blocks:
                if _ATTRIBUTION_LINK.search(block):
                    for name in _MEDIA_NAME.findall(block):
                        needs_credit.add(f"{folder}/{name.strip()}")
        self.assertTrue(needs_credit, "vacuous: no attribution-licensed file found")
        missing = sorted(n for n in needs_credit if f"`{n}`" not in self.attribution)
        self.assertEqual(missing, [],
                         "CC-BY / CC-BY-SA files without a credit block in "
                         "CREDITS.md, section 'Attribution required'")

    def test_credited_files_exist(self):
        named = re.findall(r"`([\w\-]+/[^`]+?\.\w+)`", self.attribution)
        self.assertTrue(named, "vacuous: Attribution required names no file")
        missing = [n for n in named if not os.path.isfile(os.path.join(MEDIA, n))]
        self.assertEqual(missing, [], "CREDITS.md credits files that do not exist")


class TestCodeLicense(unittest.TestCase):

    def test_license_is_mit_and_pyproject_declares_it(self):
        with open(os.path.join(ROOT, "LICENSE"), encoding="utf-8") as fh:
            self.assertTrue(fh.read().startswith("MIT License"))
        with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertRegex(text, r'(?m)^license = "MIT"$')
        self.assertRegex(text, r'(?m)^license-files = \["LICENSE"\]$')


if __name__ == "__main__":
    unittest.main()
