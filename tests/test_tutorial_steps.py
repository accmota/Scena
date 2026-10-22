"""
Every tutorial step and ``try`` box runs: headless, strict, 600 frames. The
page checks that need no run (extraction, endpoints, recaps, focus, syntax)
are ``tests/test_tutorials.py``; this module runs what they extract.

Bug classes guarded (catalogue: Testing Design, TU and T4):

* **API drift** (T4): a step calls API that has moved on.
* **A step breaks only after time passes** (TU1): ``FRAMES`` frames of the
  real frame body (``update`` / processes / collision), so shots land and
  timers fire; ``random`` is seeded, so a crash reproduces.
* **The reader sees a warning** (TU2): ``script_harness.py --strict``; the
  program runs from a temporary folder with ``media/`` → ``examples/media``.
* **A box passes appended and breaks in place** (TU6): a box with
  ``replaces:`` runs where it goes.
* **A bounce only works at a fixed frame time** (TU5): ``TestFleetBounce``.

One TestCase class per tutorial page (``TestSteps05`` runs
``05-naves.html``, ``TestStepsEn05`` its English twin), generated from the pages, so a new tutorial is covered
without an edit here. Each class runs its page's programs in parallel child
processes. The whole module is ~440 s of CPU: it is ``SLOW`` (not in the quick
tier) and ``SPLIT`` (the gate and deep tiers run one job per class). Why:
Testing Design, "Test tiers".

Run:

    python tests/run_tiers.py focused test_tutorial_steps.TestSteps05   # one page
    python tests/run_tiers.py focused test_tutorial_steps               # every page
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Sequence, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.source_support import iter_files  # noqa: E402
from tests import test_tutorials as pages  # noqa: E402
from tests.test_tutorials import (  # noqa: E402
    EXAMPLES, MEDIA, TUTORIALS, _check_fragment, _read, _reads_a_local, _step_locals,
    append_snippet, extract_steps, in_place, tutorial_pages,
)

HARNESS = os.path.join(ROOT, "tests", "script_harness.py")
FRAMES = 600          # 10 s of game time: shots land, fleets turn, timers fire
TIMEOUT = 120.0


def _link_media(folder: str) -> None:
    """``folder/media`` → ``examples/media`` (a copy where links are not allowed)."""
    target = os.path.join(folder, "media")
    try:
        os.symlink(MEDIA, target, target_is_directory=True)
    except (OSError, NotImplementedError):
        shutil.copytree(MEDIA, target)


def run_program(folder: str, name: str, program: str) -> Tuple[bool, str]:
    """Run one program headless and strict. ``(ok, stderr tail)``."""
    path = os.path.normpath(os.path.join(folder, name))
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


def run_all(paths: Optional[Sequence[str]] = None) -> List[str]:
    """``["page:line: error", …]`` for every step and ``try`` snippet of
    ``paths`` (default: every tutorial page)."""
    jobs = []      # (label, program, snippet or None, step code)
    fragment_failures = []
    for path in (tutorial_pages() if paths is None else paths):
        page = os.path.basename(path)
        for step in extract_steps(path):
            jobs.append((f"{page}:{step.line}", step.code, None, step.code))
            for tline, snippet in step.tries:
                if tline in step.places:
                    program, why = in_place(step.code, snippet, step.places[tline])
                    if program is None:
                        fragment_failures.append(f"{page}:{tline}: try: {why}")
                    else:
                        jobs.append((f"{page}:{tline}: try (in place)", program, None, step.code))
                    continue
                if _reads_a_local(snippet, step.code):
                    frag = _check_fragment(snippet, step.code)
                    if frag:
                        fragment_failures.append(f"{page}:{tline}: try: {frag}")
                    continue
                program = append_snippet(step.code, snippet)
                jobs.append((f"{page}:{tline}: try", program, snippet, step.code))

    failures = fragment_failures
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


def page_case_name(path: str) -> str:
    """``.../05-naves.html`` → ``TestSteps05`` (the number names the page);
    an appendix ``.../A-depuracao.html`` → ``TestStepsA``; an English page
    ``docs/en/tutorial/05-ships.html`` → ``TestStepsEn05``."""
    lang = "" if pages.page_lang(path) == "pt" else pages.page_lang(path).capitalize()
    return "TestSteps" + lang + pages.page_key(path)


def _page_case(path: str) -> type:
    page = os.path.basename(path)

    def test_every_step_and_try_runs(self):
        failures = run_all([path])
        self.assertEqual(failures, [], "\n" + "\n".join(failures))

    return type(page_case_name(path), (unittest.TestCase,), {
        "__doc__": f"Every step and ``try`` box of ``{page}`` runs.",
        "__module__": __name__,
        "PAGE": path,
        "test_every_step_and_try_runs": test_every_step_and_try_runs,
    })


PAGE_CASES = [_page_case(p) for p in tutorial_pages()]
globals().update({case.__name__: case for case in PAGE_CASES})


class TestPageCases(unittest.TestCase):
    """One class per page, every page once: the gate's shards cover every step."""

    def test_every_page_has_its_own_class(self):
        self.assertEqual([case.PAGE for case in PAGE_CASES], tutorial_pages())
        names = [case.__name__ for case in PAGE_CASES]
        self.assertEqual(len(set(names)), len(names), "two pages share a number")
        for case in PAGE_CASES:
            self.assertIs(globals()[case.__name__], case)


class TestRunCatches(unittest.TestCase):
    """The run fails where a reader would see a failure (TU1, TU2, TU6)."""

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

    def test_in_place_catches_the_box_that_only_passes_appended(self):
        step = pages.TestTryInPlace.STEP
        bad = 'folha = Sheet("plane/Fly*.png", fps=12)'          # its one clip is "default"
        good = 'folha = Sheet("plane/Fly*.png", fps=12, name="voando")'
        anchors = ["folha = Sheet(", 'folha.clip("voando"']
        with tempfile.TemporaryDirectory() as folder:
            _link_media(folder)
            appended = step.replace("run()", "") + "\n" + bad + "\nrun()\n"
            self.assertTrue(run_program(folder, "appended.py", appended)[0])
            self.assertFalse(run_program(folder, "bad.py", in_place(step, bad, anchors)[0])[0])
            self.assertEqual(run_program(folder, "good.py", in_place(step, good, anchors)[0]),
                             (True, ""))


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
    names = inspect.currentframe().f_back.f_globals
    fw.set_auto_callbacks(names)
    # A game of acts (tutorial 25) opens on its title: start at the act whose
    # code moves the fleet, as a player who pressed "Jogar" would.
    for value in list(names.values()):
        if (isinstance(value, type) and issubclass(value, scena.Act) and value is not scena.Act
                and MARKER in inspect.getsource(value)):
            first_act = value
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

    MARKER = 'group["inimigos"].move_by(st.velocidade'

    def _flips(self, driver: str, script: str) -> Tuple[Optional[int], str]:
        """``(turns, "")``, or ``(None, stderr tail)`` when the driver printed none."""
        p = subprocess.run([sys.executable, driver, script], capture_output=True,
                           encoding="utf-8", errors="replace", timeout=TIMEOUT,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        m = re.search(r"FLIPS (\d+)", p.stdout)
        return (int(m.group(1)), "") if m else (None, p.stderr[-800:])

    def test_fleet_does_not_stick_at_the_edge(self):
        # 20 s at 80 u/s over a 290-unit lane: about 6 turns. A stuck fleet turns every frame.
        marker = self.MARKER
        # game_*.py are learners' games (no ``if nave:``: the update stops once the ship dies).
        # Labels in "/" form on every OS (os.path.relpath gives "\\" on Windows).
        programs = [(os.path.relpath(p, ROOT).replace(os.sep, "/"), p) for p in iter_files(EXAMPLES, ".py", recursive=True)
                    if marker in _read(p) and not os.path.basename(p).startswith("game_")]
        self.assertIn("examples/naves_1.py", [label for label, _ in programs])
        steps = [s for s in extract_steps(os.path.join(TUTORIALS, "05-naves.html"))
                 if marker in s.code]
        self.assertGreater(len(steps), 0, "no fleet-bounce step found in tutorial 05")
        with tempfile.TemporaryDirectory() as folder:
            _link_media(folder)
            driver = os.path.join(folder, "bounce_driver.py")
            with open(driver, "w", encoding="utf-8") as f:
                f.write(f"ROOT = {ROOT!r}\nMARKER = {self.MARKER!r}\n" + _BOUNCE_DRIVER)
            for step in steps:
                path = os.path.join(folder, f"step_{step.line}.py")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(step.code)
                programs.append((f"05-naves.html:{step.line}", path))
            # 20 s of game time each: in parallel, as run_all does.
            workers = max(2, min(8, (os.cpu_count() or 4) - 1))
            with ThreadPoolExecutor(workers) as pool:
                results = list(pool.map(lambda lp: self._flips(driver, lp[1]), programs))
            for (label, _path), (flips, err) in zip(programs, results):
                with self.subTest(program=label):
                    self.assertIsNotNone(flips, err)
                    self.assertGreater(flips, 2, "the fleet never turned: the driver saw no bounce")
                    self.assertLess(flips, 12, f"{flips} turns in 20 s: the fleet sticks at the edge")


if __name__ == "__main__":
    unittest.main()
