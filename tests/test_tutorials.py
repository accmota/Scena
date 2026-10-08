"""
Every tutorial step runs against the real API and the reader's media, and the
last step of each tutorial is a file in ``examples/``. The tutorial rules
these enforce: every step is a program that runs; no invented API; the last
step's ``code`` is a file in ``examples/``.

Bug classes guarded:

* **API drift** (2026-09-28, Testing Design T4): steps kept calling API that
  had moved on (``Aura`` on a shape, ``keyp.once("escape")``, a
  self-referencing rotation formula, a missing ``SkyGradient`` preset).
* **A step breaks only after time passes** (2026-10-02, TU1): the last step of
  tutorial 05 destroyed the ship in ``@collide`` and ``update`` kept calling
  ``nave.confine`` (``DestroyedError``). Three ``update(dt)`` calls never let a
  shot land; the real frame loop does.
* **The reader sees a warning** (TU2): a missing media file is a placeholder
  and a ``RuntimeWarning``, never an error; so is a near-miss group name.
* **The example drifts from the tutorial** (TU3): ``pegar_estrelas.py``,
  ``naves.py``, ``cadeia_de_bolas.py``, ``barras_girando.py`` had each
  grown past (or behind) the step that was meant to be them.

How: each step's ``code:`` template literal is extracted from
``docs/pt/tutorial/0*.html`` and written to a temporary folder next to ``media/``
(a link to ``examples/media``, as the reader copies it). It runs in its own
process through ``tests/script_harness.py --strict``: the real frame body
(``update`` / processes / collision) for ``FRAMES`` frames, no window, and any
warning fails. A ``try`` snippet is appended to its step and run the same way;
a snippet that only makes sense inside one of the step's functions (it names a
local such as ``x`` / ``forma``, or it is a bare ``return``) is compiled inside
a function instead, and every capitalised call in it must resolve.

A step may declare ``example: "app_x.py"``; the last step of every tutorial
must. That file, minus its module docstring, equals the step's code.

Run:

    python tests/run_tiers.py focused test_tutorials
"""
from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from concurrent.futures import ThreadPoolExecutor
from typing import List, NamedTuple, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(ROOT, "examples")
MEDIA = os.path.join(EXAMPLES, "media")
HARNESS = os.path.join(ROOT, "tests", "script_harness.py")
FRAMES = 600          # 10 s of game time: shots land, fleets turn, timers fire
TIMEOUT = 120.0
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


def tutorial_pages() -> list:
    """``docs/pt/tutorial/NN-*.html``, sorted."""
    return [p for p in iter_files(TUTORIALS, ".html") if _PAGE.fullmatch(os.path.basename(p))]


_BLOCK = re.compile(r'\b(code|try|example):\s*(`((?:\\.|[^`\\])*)`|\[|"([^"]*)")', re.S)
_CODE = re.compile(r"\bcode:\s*`((?:\\.|[^`\\])*)`", re.S)


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
    for m in _BLOCK.finditer(html):
        line = html.count("\n", 0, m.start()) + 1
        kind = m.group(1)
        if kind == "try":
            in_try = True
            continue
        if kind == "example":
            example, in_try = m.group(4), False
            continue
        src = _unescape(m.group(3))
        if in_try and steps and "run()" not in src:
            steps[-1].tries.append((line, src))
            continue
        in_try = False
        steps.append(Step(line, src, [], example))
        example = None
    return steps


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


def _link_media(folder: str) -> None:
    """``folder/media`` → ``examples/media`` (a copy where links are not allowed)."""
    target = os.path.join(folder, "media")
    try:
        os.symlink(MEDIA, target, target_is_directory=True)
    except (OSError, NotImplementedError):
        shutil.copytree(MEDIA, target)


def run_program(folder: str, name: str, program: str) -> Tuple[bool, str]:
    """Run one program headless and strict. ``(ok, stderr tail)``."""
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(program)
    try:
        p = subprocess.run(
            [sys.executable, HARNESS, path, str(FRAMES), "--strict"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=TIMEOUT, cwd=ROOT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except subprocess.TimeoutExpired:
        return False, f"timed out after {TIMEOUT:.0f} s"
    if p.returncode == 0 and f"SCRIPT OK {FRAMES}" in p.stdout:
        return True, ""
    lines = [ln for ln in (p.stderr or "").splitlines() if ln.strip() and "GLFW" not in ln]
    return False, "\n".join(lines[-6:]) or f"exit {p.returncode}, no SCRIPT OK line"


_NAME_ERROR = re.compile(r"NameError: name '(\w+)' is not defined")


def run_all() -> List[str]:
    """``["page:line: error", …]`` for every step and ``try`` snippet."""
    jobs = []      # (label, program, snippet or None, step code)
    for path in tutorial_pages():
        page = os.path.basename(path)
        for step in extract_steps(path):
            jobs.append((f"{page}:{step.line}", step.code, None, step.code))
            for tline, snippet in step.tries:
                program = step.code.replace("run()", "") + "\n" + snippet + "\nrun()\n"
                jobs.append((f"{page}:{tline}: try", program, snippet, step.code))

    failures = []
    with tempfile.TemporaryDirectory() as folder:
        _link_media(folder)
        workers = max(2, min(8, (os.cpu_count() or 4) - 1))
        with ThreadPoolExecutor(workers) as pool:
            results = list(pool.map(
                lambda ij: run_program(folder, f"step_{ij[0]:03d}.py", ij[1][1]),
                enumerate(jobs)))
    for (label, _program, snippet, code), (ok, err) in zip(jobs, results):
        if ok:
            continue
        if snippet is not None:
            # A function-body fragment: compile it inside a function instead.
            missing = _NAME_ERROR.search(err)
            local = missing is not None and missing.group(1) in _step_locals(code)
            if local or "outside function" in err:
                frag = _check_fragment(snippet, code)
                if frag:
                    failures.append(f"{label}: {frag}")
                continue
        failures.append(f"{label}:\n    " + err.replace("\n", "\n    "))
    return failures


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
                    self.assertIn("run()", step.code)

    def test_fragment_check_catches_an_unknown_call(self):
        self.assertIsNone(_check_fragment("return Neon()", "def f():\n    pass\n"))
        self.assertIn("NoSuchLook", _check_fragment("return NoSuchLook()", ""))

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


# A bounce written as ``if past_edge: v = -v`` sticks at the edge when one frame is
# shorter than the overshoot: the shape is still past the edge, flips back, and
# oscillates there for good. The harness runs a fixed 1/60 dt, so it never sees it.
# This driver gives the frame right after the first flip a 1 ms dt (a real hitch),
# then 1/60 again, and counts direction changes of ``st.velocidade``.
_BOUNCE_DRIVER = r'''
import inspect, os, random, runpy, sys
random.seed(0)
sys.path.insert(0, ROOT)
import scena
from scena.orchestration import ScenaFramework

def headless_run(first_act=None):
    fw = ScenaFramework.get_instance()
    fw.set_auto_callbacks(inspect.currentframe().f_back.f_globals)
    fw._begin_game(first_act)
    last, flips, hitch = float(scena.st.velocidade), 0, True
    for _ in range(60 * 20):
        dt = 1.0 / 60.0
        if float(scena.st.velocidade) != last:
            flips += 1
            last = float(scena.st.velocidade)
            if hitch:
                dt, hitch = 0.001, False
        fw._simulate_frame(dt=dt)
    print(f"FLIPS {flips}", flush=True)

scena.run = headless_run
os.chdir(os.path.dirname(os.path.abspath(sys.argv[1])))
runpy.run_path(sys.argv[1], run_name="__main__")
'''


class TestFleetBounce(unittest.TestCase):
    """Tutorial 05's fleet turns at the edges once per crossing, even after a short frame."""

    def _flips(self, script: str) -> int:
        with tempfile.TemporaryDirectory() as folder:
            driver = os.path.join(folder, "bounce_driver.py")
            with open(driver, "w", encoding="utf-8") as f:
                f.write(f"ROOT = {ROOT!r}\n" + _BOUNCE_DRIVER)
            p = subprocess.run([sys.executable, driver, script], capture_output=True,
                               encoding="utf-8", errors="replace", timeout=TIMEOUT,
                               env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        m = re.search(r"FLIPS (\d+)", p.stdout)
        self.assertIsNotNone(m, p.stderr[-800:])
        return int(m.group(1))

    def test_fleet_does_not_stick_at_the_edge(self):
        # 20 s at 80 u/s over a 290-unit lane: about 6 turns. A stuck fleet turns every frame.
        marker = 'group["inimigos"].move_by(st.velocidade'
        # game_*.py are learners' games (no ``if nave:``: the update stops once the ship dies).
        # Labels in "/" form on every OS (os.path.relpath gives "\\" on Windows).
        programs = [(os.path.relpath(p, ROOT).replace(os.sep, "/"), p) for p in iter_files(EXAMPLES, ".py", recursive=True)
                    if marker in _read(p) and not os.path.basename(p).startswith("game_")]
        self.assertIn("examples/naves.py", [label for label, _ in programs])
        steps = [s for s in extract_steps(os.path.join(TUTORIALS, "05-naves.html"))
                 if marker in s.code]
        self.assertGreater(len(steps), 0, "no fleet-bounce step found in tutorial 05")
        with tempfile.TemporaryDirectory() as folder:
            _link_media(folder)
            for step in steps:
                path = os.path.join(folder, f"step_{step.line}.py")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(step.code)
                programs.append((f"05-naves.html:{step.line}", path))
            for label, path in programs:
                with self.subTest(program=label):
                    flips = self._flips(path)
                    self.assertGreater(flips, 2, "the fleet never turned: the driver saw no bounce")
                    self.assertLess(flips, 12, f"{flips} turns in 20 s: the fleet sticks at the edge")


class TestTutorialsRun(unittest.TestCase):
    def test_every_step_and_try_runs(self):
        failures = run_all()
        self.assertEqual(failures, [], "\n" + "\n".join(failures))

    def test_the_run_catches_a_late_crash_and_a_warning(self):
        late = ("from scena import *\nnave = Rect(center=(500, 100))\nst.t = 0\n"
                "def update(dt):\n    st.t += dt\n    if st.t > 1 and nave:\n"
                "        nave.destroy()\n    nave.move_by(1, 0)\nrun()\n")
        warn = 'from scena import *\nSprite("space/no_longer_here.png")\nrun()\n'
        ok = 'from scena import *\nSprite("space/star_gold.png")\nrun()\n'
        with tempfile.TemporaryDirectory() as folder:
            _link_media(folder)
            self.assertFalse(run_program(folder, "late.py", late)[0])
            ok_warn, err = run_program(folder, "warn.py", warn)
            self.assertFalse(ok_warn)
            self.assertIn("SCRIPT WARNING", err)
            self.assertEqual(run_program(folder, "ok.py", ok), (True, ""))


if __name__ == "__main__":
    unittest.main()
