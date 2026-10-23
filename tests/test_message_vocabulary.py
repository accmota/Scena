"""Engine messages and docs say "act" for the author concept; "scene" is the rendered frame.

History: the author concept was ``Scene`` (2026-09-28 .. 2026-10-06), then
``Act`` (the framework was renamed Stage → Scena, and ``scena.Scene`` says the
same word twice). See ``design/Act Design.md`` (Naming).

Bug class: a message or doc uses "scene" for the act ("scene change", "the
current scene"), for the top of the file, for the registry or for "not in the
world". With ``Act`` as the concept, "scene" in a message is either a leftover
of the old name or the old misuse, and reads as the wrong thing.

Walks ``scena/*.py`` with ``ast`` and collects string literals inside:

* ``raise`` statements;
* calls whose name contains ``warn`` / ``error`` / ``message``;
* ``return`` statements of functions whose name contains ``message``
  (``leak_detector.format_leak_message``, ``act._retired_scene_message``).

``ALLOWED`` holds the messages that may say "scene": the rendered frame (a
graphics term) and the retired-name errors (``Scene`` / ``change_scene``
raise with the new spelling). Shrink it; do not grow it without a reason in
the comment.

``TestDocsDoNotUseRetiredSceneTerms`` keeps the 2026-09-28 rename ("scene
citizen", "scene registry", "scene scope", "scene layer", … → "registry" /
"script scope" / "world layer"). ``TestDocsDoNotUseSceneForAct`` keeps the
2026-10-06 one (``Scene`` / ``change_scene`` / "scene change" → ``Act`` /
``change_act`` / "act change"). ``TestGuiaDoesNotSayCena`` keeps "cena" out
of the Guia ("ato" is the word). ``TestMessagesUseGuiaWords`` keeps "actor"
and "cell" (for a field) out of engine messages: the Guia says "object" and
"field".

    python -m unittest tests.test_message_vocabulary -v
"""
from __future__ import annotations

import ast
import functools
import json
import os
import re
import unittest

from tests.source_support import iter_files
from tests import repo_layout as layout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENA = os.path.join(ROOT, "scena")

_WORD = re.compile(r"\bscene", re.I)
_MSG_CALL = re.compile(r"warn|error|message", re.I)

ALLOWED = {
    # Rendered frame: developer-facing GPU failure (post_draw offscreen RT).
    ("orchestration.py", "Failed to create scene render target for post_draw"),
    # Retired name (0.6.0): the error names the old spelling and the fix
    # (``change_scene`` has no word boundary before "scene").
    ("act.py", "Scene was renamed to Act in 0.6.0. Write class"),
}


def _call_name(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return ""


def _strings(node):
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            yield sub


def _message_literals(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise):
            yield from _strings(node)
        elif isinstance(node, ast.Call) and _MSG_CALL.search(_call_name(node)):
            yield from _strings(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and "message" in node.name:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and sub.value is not None:
                    yield from _strings(sub.value)


def _scene_messages():
    hits = set()
    for path in iter_files(SCENA, ".py"):
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=name)
        for lit in _message_literals(tree):
            if _WORD.search(lit.value):
                hits.add((name, lit.lineno, lit.value.strip()))
    return hits


class TestMessagesDoNotSayScene(unittest.TestCase):
    def test_scan_sees_messages(self):
        # Guard the guard: the walk must reach real messages (this one is allowed).
        found = {(f, text) for f, _, text in _scene_messages()}
        self.assertTrue(ALLOWED <= found, f"ALLOWED entry no longer matches: {ALLOWED - found}")

    def test_no_scene_in_messages(self):
        bad = sorted(
            f"scena/{f}:{line}: {text!r}"
            for f, line, text in _scene_messages()
            if (f, text) not in ALLOWED
        )
        self.assertEqual(bad, [], "\n" + "\n".join(bad))


# Retired design-doc terms where "scene" meant the registry or script scope
# (the 2026-09-28 rename). "scene draw", "scene RT", "a taught scene" stay:
# those are the rendered frame or a game, not the registry.
_RETIRED_DOC_TERM = re.compile(
    r"\bscenes?[- ](citizens?|registry|scope|scoped|level|model|state machine"
    r"|membership|hooks?|map|layers?|identity|index)\b",
    re.I,
)
# The old author names (the 2026-10-06 rename): ``Scene`` / ``change_scene``
# in code spelling, links to the old doc, and the prose that went with them.
# A bare capitalised "Scene" is left alone: it starts sentences about the
# rendered frame ("Scene draw walks layers"). The archive record keeps its
# file name.
_SCENE_FOR_ACT = re.compile(
    r"change_scene|SceneUsageError|`Scene`|\(Scene\)|\bScene\(|\btest_scene\b"
    r"|\bScene Design\b(?! \(draft\))|Scene%20Design(?!%20%28draft)"
    r"|(?i:\bscene changes?\b|\bcurrent scene\b|\bper-scene\b|\bscene class)",
)
DOCS = layout.DESIGN
# The Guia is Portuguese (checked below by ``TestGuiaDoesNotSayCena``); the
# private workbench is not under design/.
_DOC_SKIP_DIRS = set()
# The Act subsystem doc tells the naming history (Room → Scene → Act).
_DOC_SKIP_FILES = {"Act Design.md"}


def _doc_hits(pattern):
    """``path:line: match`` for each hit in live docs; double-quoted text is
    exempt (a catalogue row quoting an old message)."""
    bad = []
    for path in iter_files(DOCS, ".md", recursive=True, skip_dirs=_DOC_SKIP_DIRS):
        if os.path.basename(path) in _DOC_SKIP_FILES:
            continue
        with open(path, encoding="utf-8") as fh:
            for no, line in enumerate(fh, 1):
                unquoted = re.sub(r'"[^"]*"', '""', line)
                for m in pattern.finditer(unquoted):
                    bad.append(f"{os.path.relpath(path, DOCS)}:{no}: {m.group(0)!r}")
    return bad


class TestDocsDoNotUseRetiredSceneTerms(unittest.TestCase):
    """Live design docs say "registry" / "script scope" / "world layer"."""

    def test_no_retired_terms(self):
        bad = _doc_hits(_RETIRED_DOC_TERM)
        self.assertEqual(bad, [], "\n" + "\n".join(bad))


class TestDocsDoNotUseSceneForAct(unittest.TestCase):
    """Live design docs say ``Act`` / ``change_act`` / "act change"; "scene"
    is left for the rendered frame (scene RT, ``scene_image``, scene draw)."""

    def test_no_scene_for_act(self):
        bad = _doc_hits(_SCENE_FOR_ACT)
        self.assertEqual(bad, [], "\n" + "\n".join(bad))

    def test_pattern_sees_the_old_names(self):
        # Guard the guard.
        for text in ("change_scene(Fase)", "class Fase(Scene)", "on a scene change",
                     "the current scene", "`Scene Design.md`", "`Scene` refuses",
                     "test_scene.TestStartAndChange"):
            self.assertTrue(_SCENE_FOR_ACT.search(text), text)
        for text in ("scene RT", "scene_image", "the scene draw", "Scene draw walks",
                     "untouched scenes change only for faded Contrails",
                     "archive/Scene Design (draft) 2026-09-28.md"):
            self.assertFalse(_SCENE_FOR_ACT.search(text), text)


# Hand-written sources plus the generated index (``validate_guia.py`` writes
# symbols.json / guia-api-symbols.js from the hand-written ones).
GUIA_FILES = {
    "index.html": layout.GUIDE_HTML,
    "guia-api-catalogs.js": layout.GUIDE_CATALOGS,
    "symbols.json": os.path.join(layout.GUIDE, "symbols.json"),
    "guia-api-symbols.js": os.path.join(layout.GUIDE, "guia-api-symbols.js"),
    "validate_guia.py": os.path.join(layout.GUIDE_TOOLS, "validate_guia.py"),
    "_transform_guia.py": os.path.join(layout.GUIDE_TOOLS, "_transform_guia.py"),
}
_CENA = re.compile(r"\bcenas?\b", re.I)
# The old English names may appear only in the line that says they were
# renamed (it names the version).
_OLD_NAMES = re.compile(r"change_scene|\bScene\b|SceneUsageError")
ACT_CHAPTER = "atos"


class TestGuiaDoesNotSayCena(unittest.TestCase):
    """"cena" is retired from the Guia: the concept is "ato" (``Act``), and the
    older misuse ("na cena" for "in the game") is "na tela" (visible), "no
    mundo" (world space vs HUD), "no jogo" (alive / registered), "script"
    (script scope) or "imagem" (the rendered frame, post FX). ``Scene`` /
    ``change_scene`` appear only in the 0.6.0 rename note."""

    def _read(self, name):
        with open(GUIA_FILES[name], encoding="utf-8") as fh:
            return fh.read()

    def test_no_cena(self):
        bad = []
        for name in GUIA_FILES:
            for i, line in enumerate(self._read(name).splitlines(), 1):
                if _CENA.search(line):
                    bad.append(f"{name}:{i}: {line.strip()[:100]}")
        self.assertEqual(bad, [], "\n" + "\n".join(bad))

    def test_old_names_only_in_the_rename_note(self):
        bad = []
        for name in GUIA_FILES:
            for i, line in enumerate(self._read(name).splitlines(), 1):
                if _OLD_NAMES.search(line) and "0.6.0" not in line:
                    bad.append(f"{name}:{i}: {line.strip()[:100]}")
        self.assertEqual(bad, [], "\n" + "\n".join(bad))

    def test_the_act_chapter_exists_and_says_ato(self):
        # Guard the guard: the concept still has its chapter and its word.
        html = self._read("index.html")
        a = html.index(f'<article class="chapter" id="{ACT_CHAPTER}"')
        self.assertTrue(re.search(r"\batos?\b", html[a:html.index("</article>", a)]))
        names = {r["name"] for r in json.loads(self._read("symbols.json"))["symbols"]}
        self.assertIn("Act", names)
        self.assertIn("change_act", names)


# ---------------------------------------------------------------------------
# The Guia's words: "object", never "actor"; "field", never "cell"
# ---------------------------------------------------------------------------
#
# Bug class: an engine message says "actor" for a game object or "cell" for a
# value Scena tracks (``st["hp"]``, an Attribute). The Guia's vocabulary
# (design/README.md, "Vocabulary") says *object* and *field*, and the Guia
# quotes engine messages exactly, so the old word leaks into both Guides
# (found 2026-10-22: "st has no cell 'nope'", "To show a st cell live",
# "The actor is still valid").
#
# "actor" has no other meaning, so every string literal under scena/ that is
# not a docstring is scanned (a message is often built in a variable or a
# module constant, out of reach of ``_message_literals``). "cell" is a real
# cell of a sprite sheet, a grid or an Endless tiling: ``_CELL_FILES`` are
# exempt, and ``{cell}`` placeholders, the widgets' ``cell`` parameter
# (``Slider(cell)``) and Sheet's ``cell=`` are spellings, not the word.

_ACTOR = re.compile(r"\bactors?\b", re.I)
_CELL = re.compile(r"\bcells?\b", re.I)
_CELL_SPELLING = re.compile(r"\{cell\}|\(cell\)|\bcell=")
_CELL_FILES = {
    "sprite.py",        # sheet cells (cols= / rows= / cell=)
    "atlas.py",         # sheet cells (the hitbox mask of one cell)
    "level_format.py",  # a sheet item's cell= / cols / rows
    "box.py",           # grid cells (grid.cell(col, row))
    "endless.py",       # axis='xy' tiles one image per cell
}


def _non_doc_literals(tree: ast.AST):
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docs.add(id(body[0].value))
    for sub in _strings(tree):
        if id(sub) not in docs:
            yield sub


@functools.lru_cache(maxsize=1)
def _parsed_sources():
    out = []
    for path in iter_files(SCENA, ".py", recursive=True):
        with open(path, encoding="utf-8") as fh:
            out.append((os.path.relpath(path, ROOT), ast.parse(fh.read(), filename=path)))
    return tuple(out)


def _actor_hits():
    return sorted(f"{rel}:{lit.lineno}: {lit.value.strip()[:100]!r}"
                  for rel, tree in _parsed_sources()
                  for lit in _non_doc_literals(tree) if _ACTOR.search(lit.value))


def _cell_hits():
    return sorted(f"{rel}:{lit.lineno}: {lit.value.strip()[:100]!r}"
                  for rel, tree in _parsed_sources()
                  if os.path.basename(rel) not in _CELL_FILES
                  for lit in _message_literals(tree)
                  if _CELL.search(_CELL_SPELLING.sub("", lit.value)))


class TestMessagesUseGuiaWords(unittest.TestCase):
    """Engine messages say "object" and "field", as the Guia does."""

    def test_no_actor(self):
        bad = _actor_hits()
        self.assertEqual(bad, [], "\n" + "\n".join(bad))

    def test_no_cell_for_a_field(self):
        bad = _cell_hits()
        self.assertEqual(bad, [], "\n" + "\n".join(bad))

    def test_the_scans_see_the_old_words(self):
        # Guard the guard: the 2026-10-22 messages, as they were, are caught.
        tree = ast.parse(
            "def f(key, source):\n"
            "    how = \"an actor's click hook is on_click(self)\"\n"
            "    raise KeyError(f\"st has no cell {key!r}\")\n"
            "    warn(f\"Sprite file not found: {source!r}. The actor is still valid.\")\n")
        self.assertEqual({s.lineno for s in _non_doc_literals(tree) if _ACTOR.search(s.value)},
                         {2, 4})
        self.assertEqual({s.lineno for s in _message_literals(tree) if _CELL.search(s.value)},
                         {3})
        for spelling in ("tween({cell}, …)", "Slider(cell) binds a field:",
                         "Sheet(cell=(16, 16))"):
            self.assertFalse(_CELL.search(_CELL_SPELLING.sub("", spelling)), spelling)
        self.assertTrue(all(os.path.exists(os.path.join(SCENA, f)) for f in _CELL_FILES))


# ---------------------------------------------------------------------------
# The old brand (Stage → Scena, 0.6.0)
# ---------------------------------------------------------------------------
#
# Bug class: a message, import, path or sentence still names Stage after the
# rename — an import that fails, a guard that scans a folder that no longer
# exists, or a sentence that names a framework the reader cannot install.
# Allowed: a line that states the rename (it names "0.6.0"), the legacy names
# the code keeps on purpose (the "stage-level" tag, the old "Stage Editor"
# launchers), double-quoted text in docs, "Stage 0–8" (proposal phases),
# ``PostEffectStage`` / "pipeline stage" (a step), and Act Design's Naming
# section (it tells the history). Released CHANGELOG sections and the bench
# result logs are records and are not scanned.

_BRAND = re.compile(
    r"\bStage\b(?! \d)|\bSTAGE\b|\b(?:from|import) stage\b|\bstage_editor\b"
    r"|\bstage-editor\b|(?<![\w./-])stage/|\bpip install stage\b"
)
_LEGACY_OK = re.compile(r"0\.6\.0|LEGACY|legacy|stage-level|Stage Editor|stage_editor\.ico")
_CODE_DIRS = ("scena", "scena_editor", "tests", "scripts", "examples", "tools")
_TEXT_DIRS = ("design", "docs", "examples")
_TEXT_ROOT_FILES = ("README.md", "CONTRIBUTING.md", "CLAUDE.md", "AGENTS.md")
_TEXT_SKIP_DIRS = {"archive", "notes", "proposals", "results"}


def _brand_line_ok(line):
    return bool(_LEGACY_OK.search(line))


def _section(text, heading):
    """(start, end) offsets of the ``## heading`` section, or None."""
    m = re.search(r"(?m)^## " + re.escape(heading) + r"\b.*$", text)
    if not m:
        return None
    n = re.search(r"(?m)^## ", text[m.end():])
    return m.start(), (m.end() + n.start()) if n else len(text)


def _brand_text_hits():
    paths = [os.path.join(ROOT, f) for f in _TEXT_ROOT_FILES]
    for d in _TEXT_DIRS:
        paths += iter_files(os.path.join(ROOT, d), ".md", ".html", ".js", ".txt",
                            recursive=True, skip_dirs=_TEXT_SKIP_DIRS)
    bad = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        history = _section(text, "Naming") if path.endswith("Act Design.md") else None
        offset = 0
        for no, line in enumerate(text.split("\n"), 1):
            start = offset
            offset += len(line) + 1
            if history and history[0] <= start < history[1]:
                continue
            unquoted = re.sub(r'"[^"]*"', '""', line)
            if _BRAND.search(unquoted) and not _brand_line_ok(line):
                bad.append(f"{os.path.relpath(path, ROOT)}:{no}: {line.strip()[:100]}")
    return bad


def _brand_code_hits():
    bad = []
    for d in _CODE_DIRS:
        for path in iter_files(os.path.join(ROOT, d), ".py", recursive=True,
                               skip_dirs={"archive", "historical"}):
            if os.path.abspath(path) == os.path.abspath(__file__):
                continue  # this guard spells the old names in its patterns
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
            rel = os.path.relpath(path, ROOT)
            tree = ast.parse(src, filename=rel)
            lines = src.split("\n")
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                    mods = [node.module]
                for mod in mods:
                    if mod.split(".")[0] in ("stage", "stage_editor"):
                        bad.append(f"{rel}:{node.lineno}: import {mod}")
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    v = node.value
                    if ((re.match(r"(?:stage|stage_editor)(?:\.|$)", v) or "-m stage" in v)
                            and not _brand_line_ok(lines[node.lineno - 1])):
                        bad.append(f"{rel}:{node.lineno}: {v[:60]!r}")
            for lit in _message_literals(tree):
                if re.search(r"\bStage\b|\bSTAGE\b", lit.value) and not _brand_line_ok(
                        lines[lit.lineno - 1]):
                    bad.append(f"{rel}:{lit.lineno}: message {lit.value.strip()[:60]!r}")
    return bad


class TestNoStageBrand(unittest.TestCase):
    """The framework is Scena since 0.6.0: no import, module string, message
    or published sentence names Stage, except the allowed history above."""

    def test_code_has_no_stage_imports_module_strings_or_messages(self):
        bad = _brand_code_hits()
        self.assertEqual(bad, [], "\n" + "\n".join(bad))

    def test_published_text_does_not_name_stage(self):
        bad = _brand_text_hits()
        self.assertEqual(bad, [], "\n" + "\n".join(bad))

    def test_the_patterns_see_the_old_brand(self):
        # Guard the guard.
        for text in ("from stage import *", "import stage", "python -m stage_editor",
                     "stage-editor --shortcut", "see stage/entity.py", "o Stage levanta",
                     "STAGE WARNING", "pip install stage"):
            self.assertTrue(_BRAND.search(text), text)
        for text in ("pipeline stages", "PostEffectStage", "Stage 3 — presets",
                     "the stage metaphor", "scena/entity.py", "from scena import *"):
            self.assertFalse(_BRAND.search(text), text)
        self.assertTrue(_brand_line_ok('LEGACY_FORMATS = ("stage-level",)'))
        self.assertTrue(_brand_line_ok("renamed Stage → Scena in 0.6.0"))
        self.assertFalse(_brand_line_ok("Stage draws every widget"))

    def test_the_scans_reach_real_files(self):
        # Guard the guard: the folders exist under their new names.
        for d in _CODE_DIRS + _TEXT_DIRS:
            self.assertTrue(os.path.isdir(os.path.join(ROOT, d)), d)
        self.assertTrue(os.path.exists(os.path.join(layout.DESIGN, "Scena Design.md")))


if __name__ == "__main__":
    unittest.main()
