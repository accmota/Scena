"""
What the tutorial pages say, checked without running them: the extractor sees
every step and box, the last step of each tutorial is a file in
``examples/``, scripts are named parts, recaps and dive boxes link into the
Guia, focus anchors hit one line, quoted fields parse. The tutorial rules
these enforce: every step is a program (the runs are
``tests/test_tutorial_steps.py``); the last step's ``code`` is a file in
``examples/``.

This module is fast (no program runs) and stays in the quick tier. Running
every step and box is ~440 s of CPU: ``test_tutorial_steps`` is ``SLOW`` and
sharded by page in the gate (Testing Design, "Test tiers"). The quick tier
still runs each tutorial's last step, as its ``examples/`` file
(``test_scripts_run``, 30 frames), and this module ties the two.

Bug classes guarded:

* **The example drifts from the tutorial** (TU3): ``pegar_estrelas.py``,
  ``naves.py``, ``cadeia_de_bolas.py``, ``barras_girando.py`` had each
  grown past (or behind) the step that was meant to be them.
* **The extractor silently skips** a step or box (a regex change), so the
  runs in ``test_tutorial_steps`` would pass vacuously.
* **A page that does not parse is blank for the reader** (a quote inside a
  double-quoted field).
* **A ground lean about the waist** (TU7): ``tilt = "ground"`` on a sprite
  whose ``hitbox_anchor`` is not the bottom face turns the art about the
  collider's middle, so on a ramp the feet slide sideways and stay off the
  slope (the seat needs the bottom anchor). Every tutorial step and every
  ``examples/`` file that leans a sprite with ``"ground"`` names the anchor.
* **A one-shot clip that loops** (TU8): ``play("morto", loops=1)`` written
  every frame from a state that lasts (the dead ninja's ``on_update``)
  starts the clip over each time it ends, since only a clip still playing
  makes ``play`` a no-op. Such a call asks ``showing`` first.

How: each step's ``code:`` template literal is extracted from
``docs/pt/tutorial/NN-*.html`` (``extract_steps``). A ``try`` snippet is
appended to its step (``append_snippet``); a snippet that only makes sense
inside one of the step's functions (it names a local such as ``x`` /
``forma``, or it is a bare ``return``) is compiled inside a function instead
(``_check_fragment``), and every capitalised call in it must resolve.

A box that takes the place of lines ("no lugar de…") declares them:
``replaces: ['folha = Sheet(', 'folha.clip(']`` (each anchor starts exactly
one line of the step, as ``focus`` does). Such a box runs **in place**
(``in_place``): the first anchored line becomes the snippet (at its
indentation) and the other anchored lines go. Appended, it would pass even
when it breaks in place (tutorial 11, 2026-10-09: ``Sheet("plane/Fly*.png",
fps=12)`` named its clip ``"default"``, and the step's ``play("voando")``
raised; ``TU6``). A box in a method body with ``replaces:`` is run, not just
compiled.

A step may declare ``example: "app_x.py"``; the last step of every tutorial
must. That file, minus its module docstring, equals the step's code.

Run:

    python tests/run_tiers.py focused test_tutorials
    python tests/run_tiers.py focused test_tutorial_steps.TestSteps05   # run one page's steps
"""
from __future__ import annotations

import ast
import os
import re
import sys
import tempfile
import textwrap
import unittest
from typing import Dict, List, NamedTuple, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(ROOT, "examples")
MEDIA = os.path.join(EXAMPLES, "media")
sys.path.insert(0, ROOT)

from tests.source_support import iter_files  # noqa: E402
from tests import repo_layout as layout  # noqa: E402

TUTORIALS = layout.TUTORIAL

_PAGE = re.compile(r"\d\d-.*\.html")


class Step(NamedTuple):
    line: int
    code: str
    tries: List[Tuple[int, str]]
    example: Optional[str]
    places: Dict[int, List[str]]        # try line → the lines it replaces


def tutorial_pages() -> list:
    """``docs/pt/tutorial/NN-*.html``, sorted."""
    return [p for p in iter_files(TUTORIALS, ".html") if _PAGE.fullmatch(os.path.basename(p))]


_BLOCK = re.compile(r'\b(code|try|example|replaces):\s*(`((?:\\.|[^`\\])*)`|\[|"([^"]*)")', re.S)
_ANCHORS = re.compile(r'"([^"]*)"|\'([^\']*)\'')
# The rest of ``replaces: [`` up to its ``]``: quoted anchors only, so a ``]``
# inside an anchor (``'folha.clip("voando", [0, 1]'``) does not end the list.
_LIST_REST = re.compile(r'\s*((?:\'[^\']*\'|"[^"]*")(?:\s*,\s*(?:\'[^\']*\'|"[^"]*"))*)\s*\]')
_CODE = re.compile(r"\bcode:\s*`((?:\\.|[^`\\])*)`", re.S)
# A program's last line: ``run()``, or ``run(Fase)`` in a game made of acts
# (tutorial 20 on). A box never has one at column 0.
_RUN = re.compile(r"^run\(\w*\)[ \t]*$", re.M)


def is_program(src: str) -> bool:
    """``src`` ends a whole program (has a top-level ``run(…)`` line)."""
    return _RUN.search(src) is not None


def append_snippet(code: str, snippet: str) -> str:
    """The step with ``snippet`` added just before its ``run(…)`` line."""
    last = list(_RUN.finditer(code))[-1]
    return code[:last.start()] + "\n" + snippet + "\n" + code[last.start():]


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _unescape(src: str) -> str:
    return src.replace("\\`", "`").replace("\\$", "$").replace("\\\\", "\\")


def extract_steps(path: str) -> List[Step]:
    """The page's steps in order.

    A ``code:`` that follows a ``try: [`` before the next step's code belongs
    to that ``try`` box. ``example:`` belongs to the next step's code.
    """
    html = _read(path)
    steps: List[Step] = []
    in_try = False
    example = None
    replaces = None
    for m in _BLOCK.finditer(html):
        line = html.count("\n", 0, m.start()) + 1
        kind = m.group(1)
        if kind == "try":
            in_try = True
            continue
        if kind == "example":
            example, in_try = m.group(4), False
            continue
        if kind == "replaces":
            if m.group(4) is not None:
                replaces = [m.group(4)]
            else:
                rest = _LIST_REST.match(html, m.end())
                replaces = [a or b for a, b in _ANCHORS.findall(rest.group(1))] if rest else []
            continue
        src = _unescape(m.group(3))
        if in_try and steps and not is_program(src):
            steps[-1].tries.append((line, src))
            if replaces is not None:
                steps[-1].places[line] = replaces
            replaces = None
            continue
        in_try = False
        replaces = None
        steps.append(Step(line, src, [], example, {}))
        example = None
    return steps


def in_place(code: str, snippet: str, anchors: List[str]) -> Tuple[Optional[str], str]:
    """``(program, "")``: the step with ``snippet`` where the anchored lines were.

    Each anchor starts exactly one line (indentation ignored); the first one
    takes the snippet, re-indented to its own indentation, and the others are
    dropped. ``(None, why)`` when an anchor misses or is ambiguous.
    """
    lines = code.split("\n")
    at = []
    for anchor in anchors:
        hits = [i for i, ln in enumerate(lines) if ln.lstrip().startswith(anchor)]
        if len(hits) != 1:
            return None, f"replaces {anchor!r} starts {len(hits)} lines (needs exactly 1)"
        at.append(hits[0])
    first = at[0]
    indent = lines[first][:len(lines[first]) - len(lines[first].lstrip())]
    new = [indent + ln if ln.strip() else ln for ln in snippet.strip("\n").split("\n")]
    out = []
    for i, ln in enumerate(lines):
        if i == first:
            out.extend(new)
        elif i not in at:
            out.append(ln)
    return "\n".join(out), ""


def strip_docstring(src: str) -> str:
    """``src`` without its module docstring and the blank lines after it."""
    body = ast.parse(src).body
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
            and isinstance(body[0].value.value, str):
        src = "".join(src.splitlines(keepends=True)[body[0].end_lineno:])
    return src.lstrip("\n")


def _step_locals(program: str) -> set:
    """Names that only exist inside the step's functions (args, locals, loop vars)."""
    names = set()
    for node in ast.walk(ast.parse(program)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            for arg in node.args.args + node.args.kwonlyargs:
                names.add(arg.arg)
            if not isinstance(node, ast.Lambda):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                        names.add(sub.id)
    return names


def _module_names(program: str) -> set:
    """Names the step binds at the top level (outside its functions and classes)."""
    names = set()

    def visit(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(child.name)
                continue
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                names.add(child.id)
            visit(child)

    visit(ast.parse(program))
    return names


def _reads_a_local(snippet: str, program: str) -> bool:
    """The snippet names something that only exists inside one of the step's functions.

    ``self.propulsor = Jet(origin=lambda: self.center)`` belongs in a class
    method: run at the top level, ``self`` is missing, but the formula probe
    reports "no reactive sources" instead of a ``NameError``. Decided before
    the run, from the names, it does not depend on which error surfaces.
    """
    try:
        tree = ast.parse(snippet)
    except SyntaxError:
        return False        # a bare ``return``: the run reports "outside function"
    read = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    return bool(read & (_step_locals(program) - _module_names(program)))


def _check_fragment(snippet: str, program: str) -> Optional[str]:
    """Compile a function-body snippet; every capitalised call must resolve."""
    import scena
    body = textwrap.indent(snippet, "    ")
    try:
        tree = ast.parse(f"def _fragment():\n{body}\n")
    except SyntaxError as e:
        return f"SyntaxError: {e}"
    known = set(vars(scena)) | {n.id for n in ast.walk(ast.parse(program))
                                if isinstance(n, ast.Name)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if name[:1].isupper() and name not in known:
                return f"unknown call {name}()"
    return None


class TestTutorialExtraction(unittest.TestCase):
    """The extractor sees every step (a regex change must not silently skip)."""

    def test_every_tutorial_has_steps_that_are_programs(self):
        pages = tutorial_pages()
        self.assertGreaterEqual(len(pages), 5)
        for path in pages:
            with self.subTest(page=os.path.basename(path)):
                steps = extract_steps(path)
                html = _read(path)
                self.assertEqual(
                    sum(len(s.tries) for s in steps) + len(steps),
                    len(_CODE.findall(html)),
                )
                self.assertEqual(
                    sum(1 for s in steps if s.example), html.count("example:"),
                    "an example: field the extractor did not attach to a step")
                self.assertGreater(len(steps), 2)
                for step in steps:
                    self.assertTrue(is_program(step.code), f"{os.path.basename(path)}:{step.line}: no run(…) line")

    def test_fragment_check_catches_an_unknown_call(self):
        self.assertIsNone(_check_fragment("return Neon()", "def f():\n    pass\n"))
        self.assertIn("NoSuchLook", _check_fragment("return NoSuchLook()", ""))

    def test_a_snippet_for_a_method_is_a_fragment(self):
        # Tutorial 06: a "try" that swaps the hero's thruster is written for
        # ``setup``. At the top level its ``self`` is missing, and the formula
        # probe of ``origin=lambda: self.center`` hid the NameError.
        program = ("class Heroi(Sprite):\n    def setup(self):\n        self.glow = True\n\n"
                   "nave = Heroi()\nfor inimigo in range(3):\n    pass\n"
                   "def atira():\n    inimigo = 1\n")
        self.assertTrue(_reads_a_local("self.propulsor = Jet(origin=lambda: self.center)", program))
        self.assertFalse(_reads_a_local("nave.glow = False", program))
        self.assertFalse(_reads_a_local("inimigo = 2", program),
                         "a name the top level also binds runs as a program")
        self.assertFalse(_reads_a_local("return", program))

    def test_a_game_of_acts_ends_in_run_with_its_first_act(self):
        # Tutorial 20 (2026-10-09): ``run(Fase)`` / ``run(Titulo)``. The
        # extractor took a step without a bare ``run()`` for a box of the
        # step before, and an appended box went after ``run(Titulo)``.
        html = ("steps: [ { code: `from scena import *\nrun()\n`, try: [ { code: `x = 1` } ] },\n"
                "{ code: `from scena import *\nclass Fase(Act):\n    pass\n\nrun(Fase)\n` } ]")
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "99-x.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)
            steps = extract_steps(path)
        self.assertEqual(len(steps), 2)
        self.assertEqual([src for _line, src in steps[0].tries], ["x = 1"])
        self.assertTrue(is_program(steps[1].code))
        self.assertFalse(is_program("    run(Fase)\nfase.run()"))
        self.assertTrue(append_snippet(steps[1].code, "x = 1").endswith("\nx = 1\nrun(Fase)\n"))

    def test_strip_docstring(self):
        self.assertEqual(strip_docstring('"""Doc.\n\nMore.\n"""\n\nfrom scena import *\n'),
                         "from scena import *\n")
        self.assertEqual(strip_docstring("from scena import *\n"), "from scena import *\n")


class TestTutorialEndsInAnExample(unittest.TestCase):
    def test_last_step_is_an_example_file(self):
        for path in tutorial_pages():
            page = os.path.basename(path)
            steps = extract_steps(path)
            with self.subTest(page=page):
                self.assertIsNotNone(
                    steps[-1].example,
                    f"{page}: the last step has no example: \"app_….py\" (its code is a file in examples/)")
            for step in steps:
                if not step.example:
                    continue
                with self.subTest(page=page, example=step.example):
                    file = os.path.join(EXAMPLES, step.example)
                    self.assertTrue(os.path.isfile(file), f"{page}:{step.line}: no examples/{step.example}")
                    body = strip_docstring(_read(file))
                    self.assertEqual(
                        body.rstrip("\n"), step.code.rstrip("\n"),
                        f"examples/{step.example} differs from {page}:{step.line} "
                        "(the example is the tutorial's code plus a docstring)")


_STEP_OPEN = re.compile(r"^    \{$", re.M)


def step_heads(path: str) -> List[Tuple[bool, Optional[str]]]:
    """``(fresh, part)`` per step object (``    {`` at four spaces opens one)."""
    chunks = _STEP_OPEN.split(_read(path))[1:]
    heads = []
    for chunk in chunks:
        part = re.search(r'^      part:\s*"([^"]*)"', chunk, re.M)
        heads.append((bool(re.search(r"^      fresh:\s*true", chunk, re.M)),
                      part.group(1) if part else None))
    return heads


class TestTutorialParts(unittest.TestCase):
    """A tutorial with several scripts names each one in the sidebar (``part``)."""

    def test_every_script_is_a_named_part(self):
        for path in tutorial_pages():
            page = os.path.basename(path)
            heads = step_heads(path)
            with self.subTest(page=page):
                self.assertEqual(len(heads), len(extract_steps(path)),
                                 "a step object the head scan did not see")
                starts = {0} | {i for i, (fresh, _) in enumerate(heads) if fresh}
                named = {i for i, (_, part) in enumerate(heads) if part}
                if len(starts) == 1:
                    self.assertEqual(named, set(), f"{page}: part on a one-script tutorial")
                    continue
                self.assertEqual(
                    named, starts,
                    f"{page}: part goes on the first step and on every fresh step")


_RECAP = re.compile(r"^      recap:\s*`((?:\\.|[^`\\])*)`", re.M | re.S)
GUIDE_PT = os.path.join(ROOT, "docs", "pt", "guide", "index.html")


def step_recaps(path: str) -> List[Optional[str]]:
    """The ``recap`` HTML per step object (``None`` when the step has none)."""
    out = []
    for chunk in _STEP_OPEN.split(_read(path))[1:]:
        m = _RECAP.search(chunk)
        out.append(None if m is None else m.group(1))
    return out


def script_ends(path: str) -> List[int]:
    """Indexes of the last step of every script (before a ``fresh`` step, and the final one)."""
    heads = step_heads(path)
    return [i for i in range(len(heads)) if i == len(heads) - 1 or heads[i + 1][0]]


class TestTutorialRecap(unittest.TestCase):
    """"O que vimos": every script ends with a recap that points into the Guia.

    The recap looks back (tutorial-authoring.md, "O que vimos"): a list of the
    concepts, links to the Guia, and nothing the tutorial did not show.
    """

    def test_engine_draws_the_recap(self):
        js = _read(os.path.join(ROOT, "docs", "assets", "tutorial", "tutorial.js"))
        css = _read(os.path.join(ROOT, "docs", "assets", "tutorial", "tutorial.css"))
        self.assertIn("step.recap", js)
        self.assertIn('class="recap"', js)
        self.assertIn(".recap", css)

    def test_engine_draws_the_dive_boxes(self):
        js = _read(os.path.join(ROOT, "docs", "assets", "tutorial", "tutorial.js"))
        css = _read(os.path.join(ROOT, "docs", "assets", "tutorial", "tutorial.css"))
        self.assertIn("step.dive", js)
        self.assertIn('class="dive"', js)
        self.assertIn("Para entender melhor", js)
        self.assertIn(".dive", css)

    def test_every_script_ends_with_a_recap_and_only_there(self):
        for path in tutorial_pages():
            page = os.path.basename(path)
            recaps = step_recaps(path)
            self.assertEqual(len(recaps), len(extract_steps(path)),
                             "a step object the recap scan did not see")
            with self.subTest(page=page):
                have = [i for i, r in enumerate(recaps) if r is not None]
                self.assertEqual(
                    have, script_ends(path),
                    f"{page}: recap goes on the last step of every script (steps {script_ends(path)}), "
                    "and on no other")

    def test_recap_links_point_at_guia_anchors_that_exist(self):
        guide_ids = set(re.findall(r'\bid="([^"]+)"', _read(GUIDE_PT)))
        for path in tutorial_pages():
            page = os.path.basename(path)
            for i, recap in enumerate(step_recaps(path)):
                if recap is None:
                    continue
                with self.subTest(page=page, step=i + 1):
                    links = re.findall(r'href="([^"]*)"', recap)
                    self.assertTrue(links, f"{page} step {i + 1}: a recap needs a \"No Guia\" link")
                    for href in links:
                        self.assertTrue(href.startswith("../guide/index.html#"),
                                        f"{page}: {href} is not a link into the Guia")
                        self.assertIn(href.split("#", 1)[1], guide_ids,
                                      f"{page}: the Guia has no #{href.split('#', 1)[1]}")

    def test_recap_list_teaches_nothing_the_tutorial_did_not_show(self):
        for path in tutorial_pages():
            page = os.path.basename(path)
            html = _read(path)
            for i, recap in enumerate(step_recaps(path)):
                if recap is None:
                    continue
                shown = html.replace(recap, "")
                items = re.findall(r"<li>(.*?)</li>", recap, re.S)
                with self.subTest(page=page, step=i + 1):
                    self.assertTrue(items, f"{page} step {i + 1}: a recap lists the concepts as <li>")
                    for item in items:
                        for term in re.findall(r"<code>([^<]+)</code>", item):
                            word = re.split(r"[(\[ ]", term.lstrip("@."), 1)[0]
                            self.assertTrue(
                                word in shown,
                                f"{page} step {i + 1}: the recap names `{term}`, "
                                "which no step of the tutorial shows")


_FOCUS = re.compile(r"^      focus:\s*\[(.*)\],?$", re.M)


def step_focus(path: str) -> List[Optional[List[str]]]:
    """The ``focus`` anchors per step object (``None`` when the step has none)."""
    out = []
    for chunk in _STEP_OPEN.split(_read(path))[1:]:
        m = _FOCUS.search(chunk)
        out.append(None if m is None else
                   [a or b for a, b in re.findall(r'"([^"]*)"|\'([^\']*)\'', m.group(1))])
    return out


class TestTutorialFocus(unittest.TestCase):
    """A reading step (``focus``) lights paragraphs of the script the reader already has."""

    def test_focus_anchors_start_one_line_of_an_unchanged_script(self):
        seen = 0
        for path in tutorial_pages():
            page = os.path.basename(path)
            steps, focus = extract_steps(path), step_focus(path)
            self.assertEqual(len(steps), len(focus), f"{page}: a step object the focus scan did not see")
            for i, (step, anchors) in enumerate(zip(steps, focus)):
                if anchors is None:
                    continue
                seen += 1
                with self.subTest(page=page, line=step.line):
                    self.assertTrue(anchors, "an empty focus list")
                    self.assertGreater(i, 0, "the first step has no script to re-read")
                    self.assertEqual(step.code, steps[i - 1].code,
                                     "a focus step re-reads the previous script; new code needs a building step")
                    lines = [ln.lstrip() for ln in step.code.split("\n")]
                    for anchor in anchors:
                        hits = sum(1 for ln in lines if ln.startswith(anchor))
                        self.assertEqual(hits, 1, f"focus {anchor!r} starts {hits} lines (needs exactly 1)")
        self.assertGreater(seen, 0, "no focus step found: the scan regex no longer matches")


class TestTryInPlace(unittest.TestCase):
    """A box with ``replaces:`` runs where it goes, not after the program (TU6)."""

    STEP = ('from scena import *\n\n'
            'folha = Sheet("plane/Fly1.png", "plane/Fly2.png")\n'
            'folha.clip("voando", [0, 1], fps=12)\n\n'
            'class Aviao(Sprite, source=folha, height=40):\n'
            '    def setup(self):\n'
            '        self.play("voando")\n\n'
            'Aviao(center=(100, 100))\n\nrun()\n')

    def test_the_snippet_takes_the_place_of_the_anchored_lines(self):
        program, why = in_place(self.STEP, 'folha = Sheet("plane/Fly*.png", fps=12)',
                                ["folha = Sheet(", 'folha.clip("voando"'])
        self.assertEqual(why, "")
        self.assertIn('folha = Sheet("plane/Fly*.png", fps=12)\n\nclass Aviao', program)
        self.assertNotIn("folha.clip", program)
        program, _ = in_place(self.STEP, 'self.play("voando", loops=1)', ['self.play('])
        self.assertIn('    def setup(self):\n        self.play("voando", loops=1)\n', program)

    def test_a_missing_or_ambiguous_anchor_is_reported(self):
        self.assertIsNone(in_place(self.STEP, "x = 1", ["nada("])[0])
        self.assertIsNone(in_place(self.STEP, "x = 1", ["folha"])[0])     # starts two lines

    def test_the_pages_use_it(self):
        n = sum(len(step.places) for path in tutorial_pages() for step in extract_steps(path))
        self.assertGreater(n, 0, "no box declares replaces: (the scan no longer matches)")


class TestTutorialPageSyntax(unittest.TestCase):
    """A page whose script does not parse is blank for the reader (2026-10-09).

    An unescaped ``"`` inside a double-quoted ``note: "…"`` (a link written as
    ``<a href="…">`` in a try note) ended the string early and blanked the whole
    page; no test noticed, because the extractor only reads the ``code:`` blocks.
    No JavaScript engine here, so the quoted one-line fields are checked by shape.
    """

    _QUOTED = re.compile(r'^\s*(note|title|part|id|example|focus):\s*"')
    _WELL_FORMED = re.compile(r'^\s*(?:note|title|part|id|example):\s*"(?:[^"\\]|\\.)*",?\s*$')

    def test_quoted_fields_are_one_well_formed_string(self):
        for path in tutorial_pages():
            page = os.path.basename(path)
            for n, line in enumerate(_read(path).splitlines(), 1):
                if not re.match(r'^\s*(note|title|part|id|example):\s*"', line):
                    continue
                with self.subTest(page=page, line=n):
                    self.assertRegex(line, self._WELL_FORMED,
                                     f"{page}:{n}: a quote inside a double-quoted string "
                                     "(use single quotes in an href, or escape it)")

    def test_the_checker_catches_the_bug(self):
        bad = '          note: "Veja <a href="../guide/index.html#x">aqui</a>.",'
        good = "          note: \"Veja <a href='../guide/index.html#x'>aqui</a>.\","
        self.assertIsNone(self._WELL_FORMED.match(bad))
        self.assertIsNotNone(self._WELL_FORMED.match(good))


class TestTutorialDive(unittest.TestCase):
    """"Para entender melhor": a dive box has a title and a body, and its links resolve."""

    def test_dive_items_have_a_title_a_body_and_working_links(self):
        guide_ids = set(re.findall(r'\bid="([^"]+)"', _read(GUIDE_PT)))
        seen = 0
        for path in tutorial_pages():
            page = os.path.basename(path)
            html = _read(path)
            for chunk in _STEP_OPEN.split(html)[1:]:
                m = re.search(r"^      dive:\s*\[", chunk, re.M)
                if not m:
                    continue
                for item in re.split(r"^        \{$", chunk[m.end():], flags=re.M)[1:]:
                    seen += 1
                    with self.subTest(page=page):
                        self.assertRegex(item, r'^\s*title:\s*"[^"]+"', f"{page}: a dive item needs a title")
                        self.assertRegex(item, r"body:\s*`", f"{page}: a dive item needs a body")
                        for href in re.findall(r'href="([^"]*)"', item):
                            self.assertTrue(href.startswith("../guide/index.html#"), f"{page}: {href}")
                            self.assertIn(href.split("#", 1)[1], guide_ids,
                                          f"{page}: the Guia has no #{href.split('#', 1)[1]}")
        self.assertGreater(seen, 0, "no tutorial uses a dive box (05 'O céu' should)")


# ``tilt = "ground"`` seats the art on the ramp only when the pivot is the
# bottom face (Collision Design, "Ramps"); any other anchor leans it about
# the collider's middle and the feet float (TU7).
_GROUND = ("ground", "AUTO_GROUND")
_BOTTOM = ("bottom", (0, -1))


def _anchor_of(keywords) -> object:
    for kw in keywords:
        if kw.arg == "hitbox_anchor":
            try:
                return ast.literal_eval(kw.value)
            except ValueError:
                return "<expression>"
    return None


def _leans_on_ground(node) -> bool:
    value = node.value
    if isinstance(value, ast.Constant):
        return value.value == "ground"
    return isinstance(value, ast.Name) and value.id == "AUTO_GROUND"


def ground_leans_off_the_feet(src: str) -> List[str]:
    """Sprites in ``src`` that lean with ``tilt = "ground"`` about a non-bottom anchor.

    A class with ``self.tilt = "ground"`` in its body is checked by its own
    ``hitbox_anchor=``; ``name.tilt = "ground"`` by the call that made
    ``name`` (``Sprite(…, hitbox_anchor=…)`` or a class from this file).
    """
    tree = ast.parse(src)
    classes = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes[node.name] = _anchor_of(node.keywords)
    made = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            call = node.value
            anchor = _anchor_of(call.keywords)
            if anchor is None and isinstance(call.func, ast.Name):
                anchor = classes.get(call.func.id)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    made[target.id] = anchor
    bad = []
    for node in tree.body:
        scopes = [(node.name, classes[node.name], node)] if isinstance(node, ast.ClassDef) else [(None, None, node)]
        for cls, cls_anchor, scope in scopes:
            for sub in ast.walk(scope):
                if not (isinstance(sub, ast.Assign) and _leans_on_ground(sub)):
                    continue
                for target in sub.targets:
                    if not (isinstance(target, ast.Attribute) and target.attr == "tilt"
                            and isinstance(target.value, ast.Name)):
                        continue
                    who = target.value.id
                    if who == "self" and cls is not None:
                        anchor, name = cls_anchor, f"class {cls}"
                    else:
                        anchor, name = made.get(who), who
                    if anchor not in _BOTTOM:
                        bad.append(f"line {sub.lineno}: {name} leans with tilt = \"ground\" "
                                   f"but hitbox_anchor={anchor!r} (needs \"bottom\")")
    return bad


class TestGroundLeanHasBottomAnchor(unittest.TestCase):
    """``tilt = "ground"`` goes with ``hitbox_anchor="bottom"`` in what a reader copies."""

    def test_every_step_and_example_leans_about_the_feet(self):
        seen = 0
        for path in tutorial_pages():
            page = os.path.basename(path)
            for step in extract_steps(path):
                if "tilt" not in step.code:
                    continue
                seen += 1
                with self.subTest(page=page, line=step.line):
                    self.assertEqual(ground_leans_off_the_feet(step.code), [], f"{page}:{step.line}")
        for path in iter_files(EXAMPLES, ".py"):
            if os.sep + "media" + os.sep in path:
                continue
            src = _read(path)
            if "tilt" not in src:
                continue
            seen += 1
            with self.subTest(example=os.path.basename(path)):
                self.assertEqual(ground_leans_off_the_feet(src), [], path)
        self.assertGreater(seen, 0, "no step leans a sprite (22 'A tábua inclinada' should)")

    def test_the_check_catches_a_lean_about_the_waist(self):
        cls = ('class Heroi(Sprite, hitbox_shape="rect"):\n'
               '    def setup(self):\n'
               '        self.tilt = "ground"\n')
        self.assertEqual(len(ground_leans_off_the_feet(cls)), 1)
        self.assertEqual(ground_leans_off_the_feet(cls.replace('"rect"', '"rect", hitbox_anchor="bottom"')), [])
        top = 'heroi = Sprite(ninja, hitbox_anchor="center")\nheroi.tilt = AUTO_GROUND\n'
        self.assertEqual(len(ground_leans_off_the_feet(top)), 1)
        self.assertEqual(ground_leans_off_the_feet(top.replace('"center"', '(0, -1)')), [])
        made = 'class Robo(Sprite, hitbox_anchor="bottom"):\n    pass\nr = Robo()\nr.tilt = "ground"\n'
        self.assertEqual(ground_leans_off_the_feet(made), [])
        self.assertEqual(ground_leans_off_the_feet('heroi.tilt = 15\n'), [])


def _parents(tree) -> Dict[int, ast.AST]:
    up = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            up[id(child)] = node
    return up


def _asks_showing(test, clip) -> bool:
    for sub in ast.walk(test):
        if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "showing" and sub.args
                and isinstance(sub.args[0], ast.Constant) and sub.args[0].value == clip):
            return True
    return False


def replays_a_finished_clip(src: str) -> List[str]:
    """``play(clip, loops=1)`` with no ``next=``, every frame, without asking ``showing``.

    In ``update`` / ``on_update`` such a call runs again after the clip ends,
    and a finished ``loops=1`` clip starts over (only a clip that is still
    playing makes ``play`` a no-op): the dying ninja replayed its death every
    0.8 s. The call must sit under an ``if`` that asks ``showing(clip)``.
    """
    tree = ast.parse(src)
    up = _parents(tree)
    bad = []
    for fn in ast.walk(tree):
        if not (isinstance(fn, ast.FunctionDef) and fn.name in ("update", "on_update")):
            continue
        for call in ast.walk(fn):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "play" and call.args
                    and isinstance(call.args[0], ast.Constant)):
                continue
            kws = {kw.arg: kw.value for kw in call.keywords}
            loops = kws.get("loops")
            if not (isinstance(loops, ast.Constant) and loops.value == 1) or "next" in kws:
                continue
            clip, node, asked = call.args[0].value, call, False
            while node is not fn and not asked:
                node = up[id(node)]
                asked = isinstance(node, ast.If) and _asks_showing(node.test, clip)
            if not asked:
                bad.append(f"line {call.lineno}: play({clip!r}, loops=1) in {fn.name} "
                           f"replays once it ends (ask showing({clip!r}) first)")
    return bad


class TestOneShotClipPlaysOnce(unittest.TestCase):
    """A ``loops=1`` clip played from the frame loop is guarded by ``showing``."""

    def test_every_step_and_example_asks_before_replaying(self):
        seen = 0
        for path in tutorial_pages():
            page = os.path.basename(path)
            for step in extract_steps(path):
                if "loops=1" not in step.code:
                    continue
                seen += 1
                with self.subTest(page=page, line=step.line):
                    self.assertEqual(replays_a_finished_clip(step.code), [], f"{page}:{step.line}")
        for path in iter_files(EXAMPLES, ".py"):
            if os.sep + "media" + os.sep in path:
                continue
            src = _read(path)
            if "loops=1" not in src:
                continue
            seen += 1
            with self.subTest(example=os.path.basename(path)):
                self.assertEqual(replays_a_finished_clip(src), [], path)
        self.assertGreater(seen, 0, "no step plays a one-shot clip (15 'Três vidas' should)")

    def test_the_check_catches_the_death_that_loops(self):
        dying = ('class Heroi(Sprite):\n'
                 '    def on_update(self, dt):\n'
                 '        if st.vidas == 0:\n'
                 '            if "bottom" in self.touching_sides:\n'
                 '                self.play("morto", loops=1)\n'
                 '            return\n')
        self.assertEqual(len(replays_a_finished_clip(dying)), 1)
        fixed = dying.replace('self.touching_sides:', 'self.touching_sides and not self.showing("morto"):')
        self.assertEqual(replays_a_finished_clip(fixed), [])
        self.assertEqual(replays_a_finished_clip(dying.replace('loops=1)', 'loops=1, next="parado")')), [])
        other = fixed.replace('showing("morto")', 'showing("jogando")')
        self.assertEqual(len(replays_a_finished_clip(other)), 1)
        self.assertEqual(replays_a_finished_clip('def setup():\n    heroi.play("morto", loops=1)\n'), [])


if __name__ == "__main__":
    unittest.main()
