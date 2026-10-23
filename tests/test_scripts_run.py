"""Every smoke and example script builds its scene and plays 30 frames headless.

Rule under test (Testing Design.md, Recurring bug classes: "A script is left
on a retired spelling"; catalogue SR1–SR3): a script under
``scripts/smoke/``, ``examples/``, ``tests/loads/`` (bench
loads), the Galaga frame bench and the scenes the bench pulses build
(``EXTRA``) must construct and run with today's API. Each script runs in its own process
(``tests/script_harness.py``): ``run()`` is replaced by the real frame body
(``update`` / processes / collision / flush), no window and no draw.

Bug class guarded: a script left on a retired spelling after an API change —
``Text(x1=)``, ``set_framerate(…)``, ``shape.group.add(…)``, punctuation key
names, ``hitbox=`` — found only when someone opens the window. The API
surface tests check the engine; this checks the scripts that teach it.

Two modules (Testing Design, "Test tiers": a module's children count by their
CPU). This one runs ``examples/`` (the tutorials' endpoints) and is in quick
(~11 s of CPU). ``test_smoke_scripts`` runs the rest (``scripts/smoke``, the
bench loads, ``EXTRA``; ~22 s of CPU) and is ``SLOW``. An API rename or removal
runs both.

    python tests/run_tiers.py focused test_scripts_run test_smoke_scripts
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor

from tests.source_support import iter_files

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARNESS = os.path.join(ROOT, "tests", "script_harness.py")
FRAMES = 30
# A hang detector, not a budget: ~8 s alone, but this module runs up to 8
# scripts at once on top of a tier's workers (WP15: 120 s ran out once in a
# loaded Windows gate). A looser value costs nothing on a green run.
TIMEOUT = 300.0

# Scripts that drive their own loop (not ``run()``) stay out; a bench that
# calls ``run()`` and teaches nothing else can be listed here. The pulse scenes
# (``scripts/bench/run_all.py``) are here because a refused spelling in one
# breaks the whole battery and nobody runs it daily (B1: ``gpu_mix`` kept
# ``Shield(style="bubble", color=...)`` after the KN refusal, 2026-10-12).
EXTRA = (
    "scripts/bench/historical/galaga.py",
    "scripts/bench/cpu_mix.py",
    "scripts/bench/gpu_mix.py",
    "scripts/bench/live_mix.py",
    "scripts/bench/perf_resolve_balls.py",
    "scripts/bench/perf_resolve_platformer.py",
    "scripts/bench/perf_text.py",
    "scripts/bench/perf_background.py",
    "scripts/bench/sched.py",
    "scripts/bench/games/horda.py",
    "scripts/bench/games/mundo.py",
    "scripts/bench/games/corrida.py",
    "scripts/bench/games/festa.py",
)


def scripts(smoke: bool = False):
    """The examples (an author's scripts), or with ``smoke`` the developer's:
    ``scripts/smoke``, the bench loads and ``EXTRA``."""
    if smoke:
        found = iter_files(os.path.join(ROOT, "scripts", "smoke"), ".py")
        found += iter_files(os.path.join(ROOT, "tests", "loads"), ".py")
    else:
        found = iter_files(os.path.join(ROOT, "examples"), ".py", recursive=True,
                           skip_dirs={"media"})
    found = [f for f in found if not os.path.basename(f).startswith("_")]
    if smoke:
        found += [os.path.normpath(os.path.join(ROOT, f)) for f in EXTRA]
    return sorted(found)


def translation_pairs():
    """``(Portuguese example, its English twin)`` for each pair of the
    tutorials' glossary (``tools/tutorial/names_en.json``) with both files in
    ``examples/``."""
    import json
    with open(os.path.join(ROOT, "tools", "tutorial", "names_en.json"), encoding="utf-8") as fh:
        names = json.load(fh).get("examples") or {}
    folder = os.path.join(ROOT, "examples")
    pairs = [(os.path.join(folder, pt), os.path.join(folder, en)) for pt, en in names.items()]
    return sorted((pt, en) for pt, en in pairs if os.path.isfile(pt) and os.path.isfile(en))


def law_scripts(profile: str):
    """The examples a laws check runs. Below ``deep``, an English twin is left
    out: it is its Portuguese example with every name renamed one to one
    (``test_example_translations``), so the same program, and each law ran it
    twice (WP33). ``deep`` runs both."""
    found = scripts()
    if profile == "deep":
        return found
    twins = {os.path.normpath(en) for _pt, en in translation_pairs()}
    return [p for p in found if os.path.normpath(p) not in twins]


def run_one(path):
    try:
        p = subprocess.run(
            [sys.executable, HARNESS, path, str(FRAMES)],
            capture_output=True, encoding="utf-8", errors="replace", timeout=TIMEOUT, cwd=ROOT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except subprocess.TimeoutExpired:
        return path, False, f"timed out after {TIMEOUT:.0f} s"
    ok = p.returncode == 0 and f"SCRIPT OK {FRAMES}" in p.stdout
    if ok:
        return path, True, ""
    lines = [ln for ln in (p.stderr or "").splitlines() if ln.strip() and "GLFW" not in ln]
    tail = "\n    ".join(lines[-6:]) or f"exit {p.returncode}, no SCRIPT OK line"
    return path, False, tail


def assert_all_run(tc, paths, least: int) -> None:
    tc.assertGreater(len(paths), least, "script discovery found too few files")
    workers = max(2, min(8, (os.cpu_count() or 4) - 1))
    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(run_one, paths))
    failed = [(os.path.relpath(p, ROOT), msg) for p, ok, msg in results if not ok]
    tc.assertEqual(
        failed, [],
        "\n".join(f"{p}:\n    {msg}" for p, msg in failed),
    )


class TestScriptsRun(unittest.TestCase):
    def test_every_example_runs_headless(self):
        assert_all_run(self, scripts(), 20)

    def test_the_two_halves_cover_every_script_once(self):
        examples, smoke = set(scripts()), set(scripts(smoke=True))
        self.assertEqual(examples & smoke, set())
        self.assertTrue(all(os.path.relpath(p, ROOT).startswith("examples" + os.sep)
                            for p in examples))
        self.assertLessEqual({os.path.normpath(os.path.join(ROOT, f)) for f in EXTRA}, smoke)
        for folder in ("scripts/smoke", "tests/loads"):
            found = {p for p in iter_files(os.path.normpath(os.path.join(ROOT, folder)), ".py")
                     if not os.path.basename(p).startswith("_")}
            self.assertLessEqual(found, smoke, folder)


if __name__ == "__main__":
    unittest.main()
