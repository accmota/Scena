"""README.md: its code runs, its names exist, its links and clips resolve.

README.md is the page GitHub shows and the page PyPI shows (``readme`` in
``pyproject.toml``), so every link and image in it is an absolute
``github.com/accmota/Scena`` URL (images through ``/raw/main/``: the
``raw.githubusercontent.com`` host 404s while the repository is private). A
relative one breaks on PyPI.

Bug classes guarded:

* **The landing page shows code that no longer runs.** A complete program in
  the README (a block with ``from scena import *`` and ``run()``) is played
  headless for 2 s, like ``tests/test_scripts_run.py`` plays the examples; a
  warning (a missing image, a near-miss name) is a failure, as in the tutorials.
* **A fragment is left on a retired spelling.** A short block (not a whole
  program) cannot run alone, but every scena name it uses must still be
  exported, every keyword it passes to a scena callable must be accepted, and
  every attribute it reads on a scena global (``canvas.burst_at``) must exist.
* **A link or picture points at a file that moved.** Every absolute URL into
  this repository maps to a file in the checkout.
* **A clip and its code drift apart.** ``tools/readme/make_readme_media.py``
  renders the README's own block for ``<!-- clip: id -->``; each clip the README
  shows is one the tool makes, and each README clip has its marker. Staleness
  is by input hash (``status``): an edited block is stale, never silently kept.
* **A Gallery line count goes stale.** Each Gallery cell says how many lines of
  Python its program is (code only, the way ``cloc`` counts: no blank lines, no
  comments, no docstrings); a montage gives the range of its takes. The count
  is recomputed from the example and must match.

    python -m unittest tests.test_readme -v
"""
from __future__ import annotations

import ast
import builtins
import inspect
import os
import re
import sys
import textwrap
import tokenize
import unittest
import warnings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README = os.path.join(ROOT, "README.md")
sys.path.insert(0, os.path.join(ROOT, "tools", "readme"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import make_readme_media as mm  # noqa: E402

_REPO_URL = re.compile(
    r"https://(?:github\.com/accmota/Scena/(?:blob|tree|raw)/main|"
    r"raw\.githubusercontent\.com/accmota/Scena/main)/([^\s\"')#?]+)")
# An image goes through github.com/.../raw/main/ (a redirect GitHub signs for a
# logged-in viewer): raw.githubusercontent.com answers 404 while the repo is private.
_IMG_SRC = re.compile(r"""<img\s[^>]*src=["']([^"']+)["']""")
# A block may sit inside a list item (indented fences); its code is dedented.
_BLOCK = re.compile(r"^([ \t]*)```python\n(.*?)\n\1```", re.S | re.M)
# Globals whose attributes are the author's own (``st.score``): any name is legal.
_OPEN = frozenset({"st"})
_ATTR = re.compile(r"""(?:src|href)=["']([^"']+)["']|\]\(([^)\s]+)\)""")


def _readme() -> str:
    with open(README, encoding="utf-8") as fh:
        return fh.read()


def _blocks(text: str | None = None) -> list[str]:
    return [textwrap.dedent(m.group(2)) + "\n" for m in _BLOCK.finditer(
        _readme() if text is None else text)]


def _is_program(code: str) -> bool:
    return "from scena import *" in code and re.search(r"(?m)^run\(\)", code) is not None


def _scena():
    warnings.simplefilter("ignore")
    import scena
    return scena


def fragment_problems(code: str, scena) -> list[str]:
    """Names, keywords and global attributes in ``code`` that scena does not have."""
    tree = ast.parse(code)
    exported = set(scena.__all__)
    bound = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            bound |= {(a.asname or a.name).split(".")[0] for a in node.names}
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            n = node.id
            if n in bound or n in exported or hasattr(builtins, n):
                continue
            # A free lower-case name stands for the reader's own object
            # (``ship``, ``enemy``); a capitalised or decorator name is API.
            if n[:1].isupper():
                bad.append(f"line {node.lineno}: {n} is not a scena export")
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            owner = node.value.id
            if owner in exported and owner not in bound and owner not in _OPEN:
                obj = getattr(scena, owner)
                if not inspect.isclass(obj) and not hasattr(obj, node.attr):
                    bad.append(f"line {node.lineno}: {owner}.{node.attr} does not exist")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in exported and node.func.id not in bound:
            fn = getattr(scena, node.func.id)
            try:
                sig = inspect.signature(fn)
            except (TypeError, ValueError):
                continue
            if any(p.kind is p.VAR_KEYWORD for p in sig.parameters.values()):
                continue
            for kw in node.keywords:
                if kw.arg is not None and kw.arg not in sig.parameters:
                    bad.append(f"line {node.lineno}: {node.func.id}() has no keyword {kw.arg}=")
    for node in ast.walk(tree):
        decos = getattr(node, "decorator_list", [])
        for d in decos:
            f = d.func if isinstance(d, ast.Call) else d
            if isinstance(f, ast.Name) and f.id not in exported and f.id not in bound:
                bad.append(f"line {d.lineno}: @{f.id} is not a scena export")
    return bad


class TestReadmeCode(unittest.TestCase):
    def test_has_a_complete_program(self):
        self.assertTrue(any(_is_program(b) for b in _blocks()),
                        "README.md shows no complete program")

    def test_every_complete_program_plays_without_warnings(self):
        from program_support import ProgramRun  # type: ignore
        for i, code in enumerate(_blocks()):
            if not _is_program(code):
                continue
            with self.subTest(block=i):
                seen = []
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    run = ProgramRun(f"examples/readme_block_{i}.py", source=code, seed=0)
                    try:
                        run.start()
                        run.step(120)
                    finally:
                        run.close(strict=False)
                seen = [f"{w.category.__name__}: {w.message}" for w in caught
                        if w.category.__name__ != "GLFWError"]
                self.assertEqual(seen, [], f"README block {i} warns")

    def test_an_indented_block_is_read_whole(self):
        """A block in a list item: its own closing fence ends it, never a later one."""
        text = "- item\n\n  ```python\n  a = 1\n  b = 2\n  ```\n\n```python\nc = 3\n```\n"
        self.assertEqual(_blocks(text), ["a = 1\nb = 2\n", "c = 3\n"])

    def test_every_fragment_uses_current_names(self):
        scena = _scena()
        problems = []
        for i, code in enumerate(_blocks()):
            ast.parse(code)                      # a block that does not parse fails here
            problems += [f"block {i}, {p}" for p in fragment_problems(code, scena)]
        self.assertEqual(problems, [], "\n".join(problems))

    def test_the_fragment_check_catches_drift(self):
        scena = _scena()
        bad = "ship = Sprite('a.png', hieght=4)\nship.visual = Neonn()\ncanvas.burst_att(ship)\n" \
              "@colide('a', 'b')\ndef f(a, b):\n    pass\n"
        found = "\n".join(fragment_problems(bad, scena))
        for word in ("hieght", "Neonn", "burst_att", "@colide"):
            self.assertIn(word, found)
        self.assertEqual(fragment_problems("ship = Sprite('a.png', height=4)\nship.glow = True\n"
                                           "st.anything = 1\n", scena), [])


class TestReadmeLinks(unittest.TestCase):
    def test_repo_urls_point_at_files_in_the_checkout(self):
        missing = []
        for m in _REPO_URL.finditer(_readme()):
            rel = m.group(1).rstrip("/.")
            if not os.path.exists(os.path.join(ROOT, *rel.split("/"))):
                missing.append(rel)
        self.assertEqual(missing, [])

    def test_images_use_the_github_raw_redirect(self):
        bad = [u for u in _IMG_SRC.findall(_readme())
               if not u.startswith("https://github.com/accmota/Scena/raw/main/")]
        self.assertEqual(bad, [], "README images must use github.com/accmota/Scena/raw/main/ "
                                  "(raw.githubusercontent.com is dead while the repo is private)")

    def test_no_relative_links(self):
        """PyPI renders the same file: a relative link or image is dead there."""
        rel = []
        for m in _ATTR.finditer(_readme()):
            target = m.group(1) or m.group(2)
            if not re.match(r"^(?:https?:|mailto:|#)", target):
                rel.append(target)
        self.assertEqual(rel, [])

    def test_pyproject_ships_this_readme_as_markdown(self):
        with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertRegex(text, r'readme\s*=\s*\{\s*file\s*=\s*"README\.md",\s*'
                               r'content-type\s*=\s*"text/markdown"\s*\}')


class TestReadmeClips(unittest.TestCase):
    def test_every_shown_clip_is_made_by_the_tool(self):
        shown = set(re.findall(r"docs/assets/readme/([\w-]+)\.webp", _readme()))
        self.assertEqual(shown - set(mm.CLIPS), set())
        self.assertEqual(set(mm.CLIPS) - shown, set(), "a clip the README does not show")

    def test_readme_clips_have_their_block(self):
        blocks = mm.readme_blocks(_readme())
        for cid, clip in mm.CLIPS.items():
            for take in mm.takes(clip):
                if take["program"].startswith("README.md#"):
                    self.assertIn(take["program"].split("#", 1)[1], blocks)
        for cid in blocks:
            self.assertIn(cid, mm.CLIPS, f"<!-- clip: {cid} --> has no CLIPS entry")

    def test_marker_takes_the_block_right_after_it(self):
        text = "x\n<!-- clip: a-b -->\n```python\nprint(1)\n```\n```python\nprint(2)\n```\n"
        self.assertEqual(mm.readme_blocks(text), {"a-b": "print(1)\n"})

    def test_example_clips_keep_the_design_aspect(self):
        """A montage letterboxes its takes (``fit``); a single clip must not."""
        for cid, clip in mm.CLIPS.items():
            if "segments" in clip:
                continue
            path, source = mm.program_of(clip)
            tree = ast.parse(source if source is not None else
                             open(os.path.join(ROOT, path), encoding="utf-8").read())
            consts = {t.id: v.value for n in tree.body if isinstance(n, ast.Assign)
                      for t, v in zip(getattr(n.targets[0], "elts", n.targets),
                                      getattr(n.value, "elts", [n.value]))
                      if isinstance(t, ast.Name) and isinstance(v, ast.Constant)}
            init = next(n for n in ast.walk(tree) if isinstance(n, ast.Call)
                        and getattr(n.func, "id", None) == "init")
            kw = {k.arg: k.value for k in init.keywords}
            w, h = (consts[v.id] if isinstance(v, ast.Name) else v.value
                    for v in (kw["width"], kw["height"]))
            cw, ch = clip["size"]
            with self.subTest(clip=cid):
                self.assertAlmostEqual(cw / ch, w / h, places=6)

    def test_every_pilot_exists(self):
        for cid, clip in mm.CLIPS.items():
            for take in mm.takes(clip):
                self.assertIn(take["pilot"], mm.PILOTS, cid)

    def test_every_take_is_an_example(self):
        for cid, clip in mm.CLIPS.items():
            for take in mm.takes(clip):
                path, source = mm.program_of(take)
                if source is None:
                    self.assertTrue(os.path.isfile(os.path.join(ROOT, path)), f"{cid}: {path}")

    def test_montage_hash_follows_each_take(self):
        cid = next(c for c, clip in mm.CLIPS.items() if "segments" in clip)
        clip = mm.CLIPS[cid]
        base = mm.entry_hash(cid)
        segs = [dict(s) for s in clip["segments"]]
        segs[-1]["pilot"] = "watch"
        self.assertNotEqual(base, mm.entry_hash(cid, {**clip, "segments": segs}))
        segs = [dict(s) for s in clip["segments"]]
        segs[0]["seconds"] += 1
        self.assertNotEqual(base, mm.entry_hash(cid, {**clip, "segments": segs}))

    def test_montage_letterboxes_each_take_with_its_caption(self):
        import numpy as np
        tall = np.full((2, 40, 20, 3), 200, np.uint8)     # narrower than the box
        wide = np.full((1, 30, 60, 3), 90, np.uint8)      # the box's own aspect
        images = mm.compose([(tall, "a.py"), (wide, "b.py")], (60, 40))
        self.assertEqual(len(images), 3)
        self.assertEqual({im.size for im in images}, {(60, 40)})
        first = np.asarray(images[0])
        self.assertEqual(tuple(first[2, 2]), mm.LETTERBOX)  # the bar beside the take
        self.assertEqual(tuple(first[2, 30]), (200, 200, 200))

    def test_hash_follows_each_input(self):
        cid = "catch-the-stars"
        base = mm.entry_hash(cid, text="a")
        self.assertEqual(base, mm.entry_hash(cid, text="a"))
        self.assertNotEqual(base, mm.entry_hash(cid, text="b"))
        moved = {**mm.CLIPS[cid], "seconds": mm.CLIPS[cid]["seconds"] + 1}
        self.assertNotEqual(base, mm.entry_hash(cid, moved, text="a"))
        other_pilot = {**mm.CLIPS[cid], "pilot": "watch"}
        self.assertNotEqual(base, mm.entry_hash(cid, other_pilot, text="a"))

    def test_status_sees_stale_and_missing(self):
        cid = next(iter(mm.CLIPS))
        good = {cid: {"hash": mm.entry_hash(cid)}}
        if os.path.isfile(os.path.join(mm.OUT_DIR, f"{cid}.webp")):
            self.assertEqual(mm.status([cid], good)[cid], "ok")
        self.assertEqual(mm.status([cid], {cid: {"hash": "0"}})[cid],
                         "stale" if os.path.isfile(os.path.join(mm.OUT_DIR, f"{cid}.webp"))
                         else "missing")
        self.assertEqual(mm.status([cid], {})[cid], "missing")



# Tokens that are not code; a triple-quoted string is a docstring or text block,
# which cloc counts as a comment.
_NOT_CODE = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
             tokenize.DEDENT, tokenize.ENCODING, tokenize.ENDMARKER}
_TRIPLE = re.compile(r"(?i)[rbuf]*('''|\"\"\")")
_COUNT = re.compile(r"<sub>(\d+)(?: to (\d+))? lines of Python(?: each)?</sub>")


def code_lines(path: str) -> int:
    """Lines of code in a Python file, as ``cloc`` counts them."""
    with open(path, "rb") as fh:
        tokens = list(tokenize.tokenize(fh.readline))
    lines = set()
    for t in tokens:
        if t.type in _NOT_CODE:
            continue
        if t.type in (tokenize.STRING, getattr(tokenize, "FSTRING_START", -1)) \
                and _TRIPLE.match(t.string):
            continue
        lines.update(range(t.start[0], t.end[0] + 1))
    return len(lines)


def _gallery_cells() -> list[str]:
    text = _readme()
    gallery = text[text.index("## Gallery"):text.index("\n## ", text.index("## Gallery") + 1)]
    return re.findall(r"<td\b.*?</td>", gallery, re.S)


class TestReadmeLineCounts(unittest.TestCase):
    def test_every_gallery_cell_has_a_count(self):
        cells = _gallery_cells()
        self.assertGreater(len(cells), 0)
        for cell in cells:
            self.assertRegex(cell, _COUNT, "a Gallery cell without its line count")

    def test_counts_match_the_programs(self):
        for cell in _gallery_cells():
            cid = re.search(r"docs/assets/readme/([\w-]+)\.webp", cell).group(1)
            m = _COUNT.search(cell)
            counts = [code_lines(os.path.join(ROOT, take["program"]))
                      for take in mm.takes(mm.CLIPS[cid])]
            if m.group(2) is None:
                self.assertEqual(counts, [int(m.group(1))], cid)
            else:
                self.assertEqual((min(counts), max(counts)),
                                 (int(m.group(1)), int(m.group(2))), cid)

    def test_counter_skips_blanks_comments_and_docstrings(self):
        import tempfile
        src = '"""A docstring\non two lines."""\n\n# a comment\nx = 1  # code\n' \
              'def f():\n    """Doc."""\n    return (1,\n            2)\n'
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
            fh.write(src)
        try:
            self.assertEqual(code_lines(fh.name), 4)
        finally:
            os.unlink(fh.name)


if __name__ == "__main__":
    unittest.main()
