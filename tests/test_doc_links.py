"""Published files never point into the private workbench; doc links resolve.

Bug class: a live design doc, a page, a code comment or a test docstring cites
a file under ``workbench/`` (``archive/``, ``proposals/``, ``guides/``) or
``drafts/`` (game examples in development), or the
old private paths ``documentation/archive|notes|proposals/…``. The workbench
(plans, deliberation, dated bench logs, the authoring guides) is git-ignored
and not published: in the released tree every such citation is a dead link, and the
reason it pointed at (why a fence exists, the number behind a decision) is
gone with it. The same scan catches the older rot: a link whose target moved
(``proposals/X.md`` after X went to ``archive/``) or never existed.

Rule: a living doc carries the conclusion **and** the reason itself — a fence
row with its why, the one number a decision rests on — never a link out of the
published set. See ``design/README.md`` — "Private folders".

Checked, over the published tree (``design/``, ``docs/``, ``tools/``,
``scena/``, ``scena_editor/``, ``tests/``, ``scripts/``, ``examples/`` and the
root files):

* **private path** — a file under one of the private folders is named, as a
  link target or as text (``workbench/archive/X.md`` in a comment,
  ``proposals/x.py`` in backticks in a design doc), or a path to one is joined
  in code. Naming a folder alone (``workbench/``, ``archive/``) is allowed:
  protocol text may say the folders exist and are private.
* **broken link** — a relative Markdown ``[..](target)`` or HTML
  ``href="target"`` in a ``.md`` / ``.html`` file whose file does not exist.
  Anchors (``#…``) are not checked here.

    python -m unittest tests.test_doc_links -v
"""
from __future__ import annotations

import os
import re
import unittest
from urllib.parse import unquote

from tests import repo_layout as layout
from tests.source_support import iter_files, path_key

ROOT = layout.ROOT

#: Private folders (repo-relative, ``/`` form). Not published. The old
#: ``documentation/…`` ones stay listed: a citation of them is just as dead.
PRIVATE = ("workbench", "drafts", "documentation/archive", "documentation/notes",
           "documentation/proposals")

SCAN_DIRS = ("design", "docs", "tools", "scena", "scena_editor", "tests", "scripts", "examples")
ROOT_FILES = ("AGENTS.md", "CHANGELOG.md", "CLAUDE.md", "CONTRIBUTING.md", "README.md",
              "pyproject.toml")
SUFFIXES = (".md", ".py", ".txt", ".html", ".js", ".toml")
SKIP_SUBTREES = ("scripts/bench/results",)  # gitignored bench output

_PRIVATE_NAMES = "archive|notes|proposals|guides"
# ``workbench/<something>`` (or the old ``documentation/archive/<something>``)
# anywhere: code comments, docstrings, scripts, pages.
_ABS_TEXT = re.compile(
    rf"(?<![\w.-])(?:workbench|drafts|documentation/(?:{_PRIVATE_NAMES}))/(?=[^\s`'\")\]>])")
# ``os.path.join(ROOT, "workbench", "proposals", …)`` — a test reading a private file.
_JOIN_TEXT = re.compile(
    rf"""["'](?:workbench|documentation)["']\s*,\s*["'](?:{_PRIVATE_NAMES})["']""")
# ``archive/<something>`` written as if next to the design docs (files directly in design/).
_REL_TEXT = re.compile(rf"(?<![\w/.-])(?:{_PRIVATE_NAMES})/(?=[^\s`'\")\]>#])")
# ``[text](target)``; one level of parentheses inside the target.
_MD_LINK = re.compile(r"\]\(((?:[^()\s]|\([^()\s]*\))+)\)")
_HREF = re.compile(r"""href=["']([^"']+)["']""")
_EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//)", re.I)


def _rel(path: str) -> str:
    return path_key(os.path.relpath(path, ROOT))


def _is_private(rel: str) -> bool:
    return any(rel == p or rel.startswith(p + "/") for p in PRIVATE)


def _published_files():
    me = os.path.abspath(__file__)
    for name in ROOT_FILES:
        path = os.path.join(ROOT, name)
        if os.path.isfile(path):
            yield path
    for top in SCAN_DIRS:
        for path in iter_files(os.path.join(ROOT, top), *SUFFIXES, recursive=True):
            rel = _rel(path)
            if _is_private(rel) or any(rel.startswith(s + "/") for s in SKIP_SUBTREES):
                continue
            if os.path.abspath(path) == me:
                continue  # this docstring describes the paths it forbids
            yield path


def _link_targets(text: str):
    """Yield ``(line_no, raw_target)`` for Markdown links and ``href=``."""
    for no, line in enumerate(text.splitlines(), 1):
        for rx in (_MD_LINK, _HREF):
            for m in rx.finditer(line):
                yield no, m.group(1)


def _resolve(doc: str, target: str):
    """Repo-relative ``/`` path a relative link points at, or None if not a file link."""
    target = target.strip().strip("<>")
    if not target or target.startswith("#") or _EXTERNAL.match(target):
        return None
    if any(c in target for c in "{}$+'\"") or target.startswith("data:"):
        return None  # built by page script, not a literal path
    target = unquote(target.split("#", 1)[0].split("?", 1)[0])
    if not target:
        return None
    full = os.path.normpath(os.path.join(os.path.dirname(doc), target))
    return _rel(full)


_TEXT_END = re.compile(r"\]\(|[`'\"<>]|\.(?:\s|$)|$")


def _cited_text(line: str, start: int) -> str:
    """The cited path from ``start``: up to a backtick, quote, ``](`` or
    sentence end (file names hold spaces, so a space does not end it)."""
    rest = line[start:]
    return rest[:_TEXT_END.search(rest).start()].rstrip(" .,;:)")


def _offenders():
    """Yield ``(kind, rel_file, line_no, detail)``; ``detail`` is the cited path."""
    doc_dir = layout.DESIGN
    for path in _published_files():
        rel = _rel(path)
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        is_page = path.endswith((".md", ".html"))
        directly_in_docs = os.path.dirname(path) == doc_dir
        for no, line in enumerate(text.splitlines(), 1):
            if is_page:  # link targets are checked below, once, resolved
                line = _MD_LINK.sub("]()", _HREF.sub('href=""', line))
            for m in _JOIN_TEXT.finditer(line):
                yield "private path", rel, no, m.group(0)
            hits = list(_ABS_TEXT.finditer(line))
            if directly_in_docs:
                hits += list(_REL_TEXT.finditer(line))
            for m in hits:
                cited = _cited_text(line, m.start())
                if not cited.endswith("/"):  # a folder named alone is allowed
                    yield "private path", rel, no, cited
        if not is_page:
            continue
        for no, target in _link_targets(text):
            dest = _resolve(path, target)
            if dest is None:
                continue
            if _is_private(dest):
                yield "private path", rel, no, dest
            elif not os.path.exists(os.path.join(ROOT, dest)):
                yield "broken link", rel, no, dest




class TestScanner(unittest.TestCase):
    """The patterns themselves: a pattern that misses would pass vacuously."""

    def test_text_patterns(self):
        self.assertTrue(_ABS_TEXT.search("# (workbench/archive/Heading is angle.md)"))
        self.assertTrue(_ABS_TEXT.search("see workbench/guides/tutorial-authoring.md"))
        self.assertTrue(_ABS_TEXT.search("run drafts/app_platformer.py"))
        self.assertTrue(_ABS_TEXT.search("# (documentation/archive/Heading is angle.md)"))
        self.assertTrue(_REL_TEXT.search("the sketch `proposals/scene_sketch.py`"))
        # A folder named alone is protocol text, not a citation.
        for line in ("`workbench/archive/` (history)", "`workbench/` is private"):
            m = _ABS_TEXT.search(line)
            self.assertTrue(m is None or _cited_text(line, m.start()).endswith("/"), line)
        self.assertIsNone(_REL_TEXT.search("Do not ingest `archive/`, `notes/`"))
        line = "`archive/notes/` holds the logs"
        self.assertEqual(_cited_text(line, _REL_TEXT.search(line).start()), "archive/notes/")
        # Another tree's archive folder is not ours.
        self.assertIsNone(_REL_TEXT.search("`scripts/archive/x.py` (frozen)"))

    def test_join_form(self):
        # A test that builds the path piece by piece reads a file the published
        # tree does not have (it used to skipTest forever: test_win_bench).
        self.assertTrue(_JOIN_TEXT.search('os.path.join(ROOT, "workbench", "proposals", "X.md")'))
        self.assertTrue(_JOIN_TEXT.search('os.path.join(ROOT, "documentation", "proposals", "X.md")'))
        self.assertIsNone(_JOIN_TEXT.search('os.path.join(ROOT, "workbench")'))
        self.assertIsNone(_JOIN_TEXT.search('os.path.join(ROOT, "docs", "pt")'))

    def test_cited_text_keeps_spaces(self):
        line = "See workbench/archive/Heading is angle.md. Then more."
        m = _ABS_TEXT.search(line)
        self.assertEqual(_cited_text(line, m.start()), "workbench/archive/Heading is angle.md")

    def test_links_resolve_into_private(self):
        doc = os.path.join(layout.DESIGN, "X Design.md")
        line = ("Why: [rejects](../workbench/archive/Mass%20sprite%20rejects.md#decisions) "
                "and [b](Box%20Design.md)")
        targets = [t for _no, t in _link_targets(line)]
        self.assertEqual(
            [_resolve(doc, t) for t in targets],
            ["workbench/archive/Mass sprite rejects.md", "design/Box Design.md"],
        )
        self.assertTrue(_is_private(_resolve(doc, targets[0])))
        self.assertIsNone(_resolve(doc, "https://example.com/archive/x.md"))
        self.assertIsNone(_resolve(doc, "#resolution"))
        # Parentheses inside a target (one level) stay part of it.
        line = "[s](proposals/Group%20sway_x%20(parking%20lot).md)"
        self.assertEqual([t for _no, t in _link_targets(line)],
                         ["proposals/Group%20sway_x%20(parking%20lot).md"])


class TestDocLinks(unittest.TestCase):
    def test_scan_sees_links(self):
        # Guard the guard: a link regex that matches nothing would pass vacuously.
        n = 0
        for path in _published_files():
            if path.endswith(".md"):
                with open(path, encoding="utf-8", errors="replace") as fh:
                    n += sum(1 for _ in _link_targets(fh.read()))
        self.assertGreater(n, 500)

    def test_no_private_paths_or_broken_links(self):
        found = sorted(f"{rel}:{no}: {kind}: {detail}" for kind, rel, no, detail in _offenders())
        self.assertEqual(
            found, [],
            "\nPublished files must not cite the private folders, and links must resolve.\n"
            "Carry the conclusion and its reason in the living doc instead of a link "
            "(design/README.md — 'Private folders').\n" + "\n".join(found),
        )


if __name__ == "__main__":
    unittest.main()
