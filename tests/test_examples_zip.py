"""scena-examples.zip: every example finds its media inside the unzipped folder.

The README sends learners to ``scena-examples.zip`` (built on a release by
``tools/release/make_examples_zip.py`` from the committed list
``tools/release/examples_zip.txt``). Bug classes guarded:

* **The list goes stale.** An example or a tutorial step starts using an image
  the list does not name: the zip ships a game that shows a placeholder. The
  list must equal what the scanner finds now.
* **The zip holds a file without its license.** Every media folder a listed
  file sits in brings its license file, and ``CREDITS.md`` is in.
* **A path the scanner cannot see.** Level files name their images; a
  program can build a path at run time. Each example is read against the
  unzipped folder (its own ``media/``, the cwd there, not the repo), and the
  level-file examples are played from it: a missing image is a warning, and a
  warning fails.

    python -m unittest tests.test_examples_zip -v
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
import warnings
import zipfile
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "release"))

import make_examples_zip as mz  # noqa: E402
from tests.source_support import iter_files  # noqa: E402

# Played from the unzipped folder: their images come through a level file.
PLAYED = ("ninja_nivel.py", "ninja_perigos.py")


class TestExamplesZipList(unittest.TestCase):
    def test_the_list_is_current(self):
        files, missing = mz.collect()
        self.assertEqual(missing, [], "media paths with no file")
        self.assertEqual(mz.read_list(), files,
                         "tools/release/examples_zip.txt is stale: "
                         "python tools/release/make_examples_zip.py --update")

    def test_every_example_is_listed(self):
        listed = set(mz.read_list())
        for script in mz.example_scripts():
            self.assertIn(os.path.relpath(script, ROOT).replace(os.sep, "/"), listed)

    def test_every_listed_media_folder_brings_its_license(self):
        listed = set(mz.read_list())
        self.assertIn("examples/media/CREDITS.md", listed)
        for rel in listed:
            if not rel.startswith("examples/media/") or rel.endswith(".md"):
                continue
            folder = os.path.dirname(os.path.join(ROOT, *rel.split("/")))
            here = [p for p in iter_files(folder)
                    if os.path.basename(p).lower() in mz.LICENSE_NAMES]
            if here:
                with self.subTest(file=rel):
                    lic = os.path.relpath(here[0], ROOT).replace(os.sep, "/")
                    self.assertIn(lic, listed)

    def test_the_level_images_are_followed(self):
        listed = set(mz.read_list())
        level = os.path.join(mz.MEDIA, "levels", "ninja_perigos.json")
        images = mz._level_images(level)
        self.assertTrue(images, "the Ninja IV level places images")
        for p in images:
            self.assertIn(os.path.relpath(p, ROOT).replace(os.sep, "/"), listed)


class TestExamplesZipWiring(unittest.TestCase):
    """The README link, the release job and the zip agree on names."""

    def test_the_readme_links_the_latest_release_asset(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            readme = fh.read()
        self.assertIn("https://github.com/accmota/Scena/releases/latest/download/"
                      "scena-examples.zip", readme)
        self.assertIn(f"python {mz.TOP}/naves_escudo.py", readme)

    def test_the_release_job_builds_and_attaches_it_after_pypi(self):
        with open(os.path.join(ROOT, ".github", "workflows", "release.yml"),
                  encoding="utf-8") as fh:
            workflow = fh.read()
        self.assertIn("python tools/release/make_examples_zip.py", workflow)
        self.assertIn("dist/scena-examples.zip", workflow)
        self.assertIn("contents: write", workflow)
        self.assertLess(workflow.index("pypa/gh-action-pypi-publish"),
                        workflow.index("make_examples_zip.py"))


class TestExamplesZipContents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="scena_examples_zip_")
        cls.zip = os.path.join(cls.tmp, "scena-examples.zip")
        mz.build(cls.zip, mz.read_list())
        with zipfile.ZipFile(cls.zip) as z:
            cls.names = z.namelist()
            z.extractall(cls.tmp)
        cls.folder = os.path.join(cls.tmp, mz.TOP)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_layout(self):
        self.assertTrue(all(n.startswith(mz.TOP + "/") for n in self.names))
        self.assertIn(f"{mz.TOP}/README.txt", self.names)
        self.assertIn(f"{mz.TOP}/naves_escudo.py", self.names)
        self.assertIn(f"{mz.TOP}/media/CREDITS.md", self.names)

    def test_the_same_list_makes_the_same_zip(self):
        again = os.path.join(self.tmp, "again.zip")
        mz.build(again, mz.read_list())
        with open(self.zip, "rb") as a, open(again, "rb") as b:
            self.assertEqual(a.read(), b.read())

    def test_every_example_finds_its_media_in_the_folder(self):
        warnings.simplefilter("ignore")
        from tests import test_media_refs as refs
        cwd = os.getcwd()
        os.chdir(self.folder)              # the cwd fallback must not reach the repo
        try:
            for script in iter_files(self.folder, ".py"):
                name = os.path.basename(script)
                with open(script, encoding="utf-8") as fh:
                    src = fh.read()
                dead = []
                with patch("scena.sprite._script_dir", return_value=self.folder):
                    for line, kind, p in refs.literal_paths(src):
                        if refs.DELIBERATE.search(p):
                            continue
                        if kind == "media":
                            ok = os.path.isfile(os.path.join(self.folder, "media", p))
                        else:
                            ok = refs.path_exists(p)
                        if not ok:
                            dead.append(f"{line}: {p}")
                with self.subTest(example=name):
                    self.assertEqual(dead, [])
        finally:
            os.chdir(cwd)

    def test_level_examples_play_from_the_folder(self):
        from tests.program_support import ProgramRun
        for name in PLAYED:
            with self.subTest(example=name):
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    run = ProgramRun(os.path.join(self.folder, name), seed=0)
                    try:
                        run.start()
                        run.step(30)
                    finally:
                        run.close(strict=False)
                seen = [str(w.message) for w in caught if w.category.__name__ != "GLFWError"]
                self.assertEqual(seen, [], f"{name} warns when run from the zip")


if __name__ == "__main__":
    unittest.main()
