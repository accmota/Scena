"""Where things live in the repository, in one place.

A folder move edits this file, not every test that reads a doc, a page or a
tool. ``tests/test_repo_layout.py`` checks that each path exists.

    design/          design docs (Scena Design.md, Testing Design.md, …)
    docs/            the author site (GitHub Pages): docs/<lang>/guide/,
                     docs/<lang>/tutorial/, docs/assets/ (shared by languages)
    tools/guide/     the Guide's generators and checks (validate_guia.py, …)
    tools/tutorial/  the English tutorials' checks (tutorial_parity.py, glossary)
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
# The tutorial index each language's checks read: the English pages list in a
# draft index (noindex) while the published ``index.html`` is a stub.
TUTORIAL_INDEX = {"pt": "index.html", "en": "draft.html"}
ASSETS = os.path.join(DOCS, "assets")
THUMBS = os.path.join(ASSETS, "thumbs")
GUIDE_TOOLS = os.path.join(ROOT, "tools", "guide")
TUTORIAL_TOOLS = os.path.join(ROOT, "tools", "tutorial")
EXAMPLES = os.path.join(ROOT, "examples")
# Game system tests: programs written to be tested (tests/games/README.txt).
GAMES = os.path.join(ROOT, "tests", "games")
WORKBENCH = os.path.join(ROOT, "workbench")
DRAFTS = os.path.join(ROOT, "drafts")


def tutorial_dir(lang: str) -> str:
    """``docs/<lang>/tutorial``."""
    return os.path.normpath(os.path.join(DOCS, lang, "tutorial"))
