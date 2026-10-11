"""Every media path written in an example, smoke, bench or tutorial resolves.

Bug class (Testing Design.md, "A media path is dead and nothing says so"): a
missing image or sound is a ``SCENA WARNING`` and a placeholder, never an
error. ``test_scripts_run`` builds the scene and passes, and a moved or
deleted file goes unnoticed until someone opens the window (the 2026-10
``scripts/examples`` → ``examples`` move left about 170 such paths).

Checked, in ``examples/**``, ``tests/loads/*.py``, ``tests/games/*.py``,
``scripts/smoke/*.py`` and ``scripts/bench/**``:

* a string constant with a media extension passed as the first argument of
  ``Sprite`` / ``Sheet`` / ``Texture`` / ``Wallpaper`` / ``Svg`` / ``Sound`` /
  ``play_sound`` / ``Level`` (or listed in a ``Sheet([...])``), the path of
  ``sheet.strip(name, path)``, and ``source=`` / ``atlas=`` / ``font=``
  keywords (class keywords too);
* any constant containing ``media/``;
* ``… / "examples" / "media" / …`` and ``os.path.join(…, "examples",
  "media", …)`` chains that end in a file name.

Each path resolves the way the engine does (``scena.sprite._resolve_image_path``):
absolute, next to the script, the script's ``media/``, then cwd (the repo root,
or the folder a ``# harness: cwd=<dir>`` header names).
A file pattern (``"ninja/Run__*.png"``, ``Sheet`` / ``strip``) must match at
least one file in the first folder that has a match
(``scena.sprite._pattern_matches``) — a pattern that matches nothing is a
placeholder clip, the same silent miss.
``frame=`` names, markup and f-strings are not paths. Deliberate misses
(``no_such_*``, ``missing_*``, …) are allowed.

The tutorial (``docs/pt/tutorial/*.html``) is checked too: its readers copy
``examples/media`` next to their script, so every media path in a step or a
``try`` box (read like a script: ``frame=`` names of a ``Sheet`` are not
paths) must exist under ``examples/media``.

    python -m unittest tests.test_media_refs -v
"""
from __future__ import annotations

import ast
import importlib.util
import os
import re
import unittest
from typing import Iterator, List, Optional, Tuple
from unittest.mock import patch

from scena.sprite import _pattern_matches, _resolve_image_path
from tests.media_support import MEDIA, ROOT
from tests.source_support import iter_files

MEDIA_EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".xml",
             ".json", ".wav", ".ogg", ".mp3", ".flac", ".ttf", ".otf")
LOADERS = frozenset({"Sprite", "Sheet", "Texture", "Wallpaper", "Svg", "Sound",
                     "play_sound", "Level"})
PATH_KEYWORDS = frozenset({"source", "atlas", "font"})
# Deliberately missing files (warning / placeholder demos and tests).
DELIBERATE = re.compile(r"(^|/)(no_such|missing|not_a_real|nope)[\w.-]*$|^x\.png$")


def _is_media(s: str) -> bool:
    """A single file path (not markup, not a sentence listing paths)."""
    return (s.lower().endswith(MEDIA_EXT) and "<" not in s and "\n" not in s
            and ", " not in s)


def _const(node) -> Optional[str]:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _name(func) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _chain_parts(node) -> Optional[List[Optional[str]]]:
    """``a / "b" / "c"`` → [None, "b", "c"]; ``os.path.join(x, "b")`` → [None, "b"]."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _chain_parts(node.left) or [None]
        return left + [_const(node.right)]
    if isinstance(node, ast.Call) and _name(node.func) == "join":
        return [_const(a) for a in node.args]
    return None


def _media_tail(parts: List[Optional[str]]) -> Optional[str]:
    """The ``examples/media``-relative file a path chain names, or None."""
    for i in range(len(parts) - 1):
        if parts[i] == "examples" and parts[i + 1] == "media":
            tail = parts[i + 2:]
            if tail and all(p is not None for p in tail) and _is_media(tail[-1]):
                return "/".join(tail)
    return None


def _file_items(nodes, name: str) -> List[ast.AST]:
    """The file nodes of a source argument: list / tuple items for ``Sheet``."""
    out: List[ast.AST] = []
    for node in nodes:
        if isinstance(node, (ast.List, ast.Tuple)) and name == "Sheet":
            out.extend(node.elts)
        else:
            out.append(node)
    return out


def path_exists(path: str) -> bool:
    """The engine finds it: one file, or a pattern with at least one match."""
    if "*" in path:
        return bool(_pattern_matches(path)[0])
    return _resolve_image_path(path) is not None


def literal_paths(src: str) -> Iterator[Tuple[int, str, str]]:
    """Yield ``(line, kind, path)``: kind ``"engine"`` (resolve like the
    engine) or ``"media"`` (``examples/media``-relative)."""
    tree = ast.parse(src)
    seen = set()

    def emit(node, kind, s):
        key = (node.lineno, s)
        if key not in seen:
            seen.add(key)
            yield node.lineno, kind, s

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _name(node.func)
            args = list(node.args)
            if name in LOADERS and args:
                # Sheet takes a list or extra positional files (patterns too).
                for item in _file_items(args if name == "Sheet" else args[:1], name):
                    s = _const(item)
                    if s is not None and _is_media(s):
                        yield from emit(item, "engine", s)
            if name == "strip" and len(args) >= 2:
                for item in _file_items(args[1:2], "Sheet"):
                    s = _const(item)
                    if s is not None and _is_media(s):
                        yield from emit(item, "engine", s)
            for kw in node.keywords:
                s = _const(kw.value)
                if kw.arg in PATH_KEYWORDS and s is not None and _is_media(s):
                    yield from emit(kw.value, "engine", s)
        if isinstance(node, ast.ClassDef):
            for kw in node.keywords:
                s = _const(kw.value)
                if kw.arg in PATH_KEYWORDS and s is not None and _is_media(s):
                    yield from emit(kw.value, "engine", s)
        s = _const(node)
        if s is not None and "media/" in s and _is_media(s):
            yield from emit(node, "engine", s)
        parts = _chain_parts(node)
        if parts:
            tail = _media_tail(parts)
            if tail:
                yield from emit(node, "media", tail)


def dead_paths(script: str, src: str) -> List[str]:
    """``"<line>: <path>"`` for each media path in ``src`` that does not resolve."""
    out = []
    with patch("scena.sprite._script_dir", return_value=os.path.dirname(script)):
        for line, kind, s in literal_paths(src):
            if DELIBERATE.search(s):
                continue
            if kind == "media":
                ok = os.path.isfile(os.path.join(MEDIA, s))
            else:
                ok = path_exists(s)
            if not ok:
                out.append(f"{line}: {s}")
    return out


def _scripts() -> List[str]:
    found = iter_files(os.path.join(ROOT, "examples"), ".py", recursive=True,
                       skip_dirs={"media"})
    found += iter_files(os.path.join(ROOT, "tests", "loads"), ".py")
    found += [p for p in iter_files(os.path.join(ROOT, "scripts", "smoke"), ".py")
              if not os.path.basename(p).startswith("_")]
    found += iter_files(os.path.join(ROOT, "scripts", "bench"), ".py",
                        recursive=True, skip_dirs={"results"})
    found += iter_files(os.path.join(ROOT, "tests", "games"), ".py")
    return found


def _harness_cwd(src: str) -> str:
    """The folder a script runs from: ``# harness: cwd=<dir>`` on its first
    lines (the game system tests run from ``examples/media``), else the root."""
    for line in src.splitlines()[:5]:
        if line.startswith("# harness: cwd="):
            return os.path.join(ROOT, line.split("=", 1)[1].strip())
    return ROOT


def tutorial_paths() -> Iterator[Tuple[str, str]]:
    """``("page:line", path)`` for each media path in a tutorial step or ``try``.

    The code is read like a script (``literal_paths``), so a ``Sheet`` frame
    name (``frame="…"``) is not a path. A ``try`` that is a function-body
    fragment is read inside a function.
    """
    from tests.test_tutorials import append_snippet, extract_steps, in_place, tutorial_pages
    for page in tutorial_pages():
        name = os.path.relpath(page, ROOT)
        for step in extract_steps(page):
            for line, code in [(step.line, step.code)] + step.tries:
                try:
                    found = list(literal_paths(code))
                except SyntaxError:
                    try:
                        found = list(literal_paths("def _f():\n" + "".join(
                            "    " + ln + "\n" for ln in code.splitlines())))
                    except SyntaxError:
                        # A box that only parses where it goes (a bare ``if``
                        # line in place of one, a decorator before a step's
                        # function): read it the way test_tutorials runs it.
                        if line in step.places:
                            program, _why = in_place(step.code, code, step.places[line])
                        else:
                            program = append_snippet(step.code, code)
                        found = list(literal_paths(program or code))
                for _no, _kind, path in found:
                    yield f"{name}:{line}", path


class TestMediaRefs(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        os.chdir(ROOT)   # cwd-relative bench paths resolve from the repo root

    def tearDown(self):
        os.chdir(self._cwd)

    def test_every_script_media_path_resolves(self):
        dead = []
        for path in _scripts():
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
            rel = os.path.relpath(path, ROOT)
            os.chdir(_harness_cwd(src))
            try:
                dead += [f"{rel}:{d}" for d in dead_paths(path, src)]
            finally:
                os.chdir(ROOT)
        self.assertEqual(dead, [], "media path does not resolve (moved or deleted file?)")

    def test_smoke_media_lists_exist(self):
        spec = importlib.util.spec_from_file_location(
            "_smoke_media", os.path.join(ROOT, "scripts", "smoke", "_media.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rels = list(mod.HITBOX_SINGLES) + list(mod.STRIPS)
        rels += [p for pair in mod.HITBOX_ATLASES for p in pair]
        missing = [r for r in rels if not os.path.isfile(os.path.join(MEDIA, r))]
        self.assertEqual(missing, [])

    def test_tutorial_media_names_exist_in_examples_media(self):
        # The reader copies examples/media next to the script: a path resolves
        # there (or next to the script, as "media/…"), never from this repo.
        dead = [f"{where}: {path}" for where, path in tutorial_paths()
                if not path_exists(os.path.join(MEDIA, path))
                and not path_exists(os.path.join(ROOT, "examples", path))]
        self.assertEqual(dead, [], "tutorial names a file its readers' media/ does not have")

    def test_tutorial_reader_sees_paths_not_frames(self):
        src = ('nave = Sprite("space/star_gold.png")\n'
               'space = Sheet("shooter/sheet.xml")\n'
               'n = Sprite(space, frame="playerShip1_blue.png")\n')
        self.assertEqual([p for _l, _k, p in literal_paths(src)],
                         ["space/star_gold.png", "shooter/sheet.xml"])
        self.assertGreater(len(list(tutorial_paths())), 20)

    def test_guard_fires_on_a_dead_path(self):
        script = os.path.join(ROOT, "examples", "probe.py")
        src = (
            'space = Sheet("shooter/sheet.xml")\n'
            'a = Sprite("space/star_gold.png")\n'
            'b = Sprite("space/gone.png")\n'
            'c = Sprite(space, frame="also_not_a_file.png")\n'
            'd = Sprite("no_such_file.png")\n'
            'e = Path(x) / "examples" / "media" / "space" / "vanished.png"\n'
            'play_sound("audio/Victory.mp3")\n'
        )
        self.assertEqual(dead_paths(script, src), ["3: space/gone.png", "6: space/vanished.png"])

    def test_a_box_is_read_where_it_runs(self):
        # 2026-10-09 (tutorials 14-20): a box that only parses in its place
        # (a bare ``if`` line with replaces:) raised SyntaxError here, so
        # authors bent boxes to please the scan. It is read the way
        # test_tutorials runs it.
        import tempfile
        page = ('steps: [ { code: `from scena import *\n\ndef f():\n    if x:\n'
                '        Sprite("space/star_gold.png")\n\nrun()\n`, try: [\n'
                "  { replaces: ['if x:'], code: `if keyp(\"A\"):` } ] } ]")
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "99-x.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(page)
            with patch("tests.test_tutorials.tutorial_pages", lambda: [path]):
                self.assertEqual([p for _at, p in tutorial_paths()], ["space/star_gold.png"] * 2)

    def test_guard_expands_patterns(self):
        # A pattern counts when it matches at least one file; one that matches
        # nothing (wrong prefix, wrong case, wrong folder) is dead.
        script = os.path.join(ROOT, "examples", "probe.py")
        src = (
            'n = Sheet(anchor="bottom")\n'
            'n.strip("parado", "ninja/Idle__*.png", fps=8)\n'
            'n.strip("x", "ninja/idle__*.png", fps=8)\n'
            'n.strip("y", ["ninja/Run__*.png", "ninja/Nope__*.png"])\n'
            'r = Sheet("robot/Run (*).png", fps=12)\n'
            'q = Sheet("robot/Walk (*).png", "ninja/Gone__*.png")\n'
        )
        self.assertEqual(dead_paths(script, src), [
            "3: ninja/idle__*.png", "4: ninja/Nope__*.png",
            "6: robot/Walk (*).png", "6: ninja/Gone__*.png",
        ])


if __name__ == "__main__":
    unittest.main()
