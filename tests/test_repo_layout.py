"""The repository layout that ``tests/repo_layout.py`` describes is real.

Bug class: a folder moves (``documentation/`` → ``design/``, the Guia →
``docs/pt/guide/``) and a test, a tool or a page keeps the old path. Tests read
paths from ``repo_layout``; this module checks those paths exist and that the
author site (``docs/``, GitHub Pages) has the same shape in every language.
See ``design/README.md`` — "Repository layout".

    python -m unittest tests.test_repo_layout -v
"""
from __future__ import annotations

import os
import re
import subprocess
import unittest

from tests import repo_layout as layout
from tests.source_support import iter_files

_HREF = re.compile(r"""(?:href|src)=["']([^"'#?]+)""")


class TestLayoutPaths(unittest.TestCase):
    def test_every_published_path_exists(self):
        for name in ("DESIGN", "DOCS", "GUIDE", "GUIDE_HTML", "GUIDE_CATALOGS", "TUTORIAL",
                     "ASSETS", "THUMBS", "GUIDE_TOOLS", "EXAMPLES"):
            path = getattr(layout, name)
            self.assertTrue(os.path.exists(path), f"repo_layout.{name}: {path} does not exist")

    def test_the_old_folders_are_gone(self):
        for old in ("documentation", "tutorial"):
            self.assertFalse(os.path.exists(os.path.join(layout.ROOT, old)),
                             f"{old}/ came back: the layout is design/ + docs/")


class TestAuthorSite(unittest.TestCase):
    """``docs/`` is served as is by GitHub Pages (main branch, /docs)."""

    def test_each_language_has_a_guide_and_a_tutorial_page(self):
        for lang in layout.LANGS:
            for part in ("guide", "tutorial"):
                page = os.path.join(layout.DOCS, lang, part, "index.html")
                self.assertTrue(os.path.isfile(page), page)

    def test_the_landing_page_links_every_language(self):
        with open(os.path.join(layout.DOCS, "index.html"), encoding="utf-8") as fh:
            links = set(_HREF.findall(fh.read()))
        for lang in layout.LANGS:
            for part in ("guide", "tutorial"):
                self.assertIn(f"{lang}/{part}/index.html", links)

    def test_pages_are_served_without_jekyll(self):
        # Jekyll would drop files whose names start with "_" and rewrite others.
        self.assertTrue(os.path.isfile(os.path.join(layout.DOCS, ".nojekyll")))

    def test_the_site_holds_pages_not_tools(self):
        tools = [os.path.relpath(p, layout.ROOT)
                 for p in iter_files(layout.DOCS, ".py", recursive=True)]
        self.assertEqual(tools, [], "the Guia's tools live in tools/guide/")

    def test_shared_assets_resolve_from_each_page(self):
        # Every local href / src in the site points at a file that exists.
        bad = []
        for page in iter_files(layout.DOCS, ".html", recursive=True):
            d = os.path.dirname(page)
            with open(page, encoding="utf-8") as fh:
                for target in _HREF.findall(fh.read()):
                    if re.match(r"^(?:[a-z]+:|//)", target) or "${" in target:
                        continue
                    if not os.path.exists(os.path.normpath(os.path.join(d, target))):
                        bad.append(f"{os.path.relpath(page, layout.ROOT)}: {target}")
        self.assertEqual(bad, [], "\n" + "\n".join(bad))


class TestPrivateFoldersStayPrivate(unittest.TestCase):
    """``workbench/`` and ``drafts/`` are the maintainer's: never published."""

    PRIVATE = ("workbench", "drafts")

    def test_git_ignores_them(self):
        with open(os.path.join(layout.ROOT, ".gitignore"), encoding="utf-8") as fh:
            rules = fh.read().split()
        for name in self.PRIVATE:
            self.assertIn(f"/{name}/", rules)

    def test_no_tracked_file_is_in_them(self):
        try:
            out = subprocess.run(["git", "ls-files", *self.PRIVATE], cwd=layout.ROOT,
                                 capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=30)
        except (OSError, subprocess.SubprocessError):
            self.skipTest("git is not available")
        if out.returncode != 0:
            self.skipTest("not a git checkout")
        self.assertEqual(out.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
