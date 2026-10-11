"""Where things live in the repository, in one place.

A folder move edits this file, not every test that reads a doc, a page or a
tool. ``tests/test_repo_layout.py`` checks that each path exists.

    design/          design docs (Scena Design.md, Testing Design.md, …)
    docs/            the author site (GitHub Pages): docs/<lang>/guide/,
                     docs/<lang>/tutorial/, docs/assets/ (shared by languages)
    tools/guide/     the Guide's generators and checks (validate_guia.py, …)
    workbench/       private, git-ignored: archive/, proposals/, guides/
    drafts/          private, git-ignored: game examples in development
"""
from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DESIGN = os.path.join(ROOT, "design")
DOCS = os.path.join(ROOT, "docs")
LANGS = ("pt", "en")
# The Guide and tutorial the tools and tests read (Portuguese is written first;
# the English pages mirror it).
LANG = "pt"
GUIDE = os.path.join(DOCS, LANG, "guide")
GUIDE_HTML = os.path.join(GUIDE, "index.html")
GUIDE_CATALOGS = os.path.join(GUIDE, "guia-api-catalogs.js")
TUTORIAL = os.path.join(DOCS, LANG, "tutorial")
ASSETS = os.path.join(DOCS, "assets")
THUMBS = os.path.join(ASSETS, "thumbs")
GUIDE_TOOLS = os.path.join(ROOT, "tools", "guide")
EXAMPLES = os.path.join(ROOT, "examples")
# Game system tests: programs written to be tested (tests/games/README.txt).
GAMES = os.path.join(ROOT, "tests", "games")
WORKBENCH = os.path.join(ROOT, "workbench")
DRAFTS = os.path.join(ROOT, "drafts")
