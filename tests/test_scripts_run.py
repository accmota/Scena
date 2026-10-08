"""Every smoke and example script builds its scene and plays 30 frames headless.

Rule under test (Testing Design.md, Recurring bug classes: "A script is left
on a retired spelling"; catalogue SR1–SR3): a script under
``scripts/smoke/``, ``examples/``, ``tests/loads/`` (bench
loads) and the Galaga frame bench must
construct and run with today's API. Each script runs in its own process
(``tests/script_harness.py``): ``run()`` is replaced by the real frame body
(``update`` / processes / collision / flush), no window and no draw.

Bug class guarded: a script left on a retired spelling after an API change —
``Text(x1=)``, ``set_framerate(…)``, ``shape.group.add(…)``, punctuation key
names, ``hitbox=`` — found only when someone opens the window. The API
surface tests check the engine; this checks the scripts that teach it.

    python -m unittest tests.test_scripts_run -v
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
# calls ``run()`` and teaches nothing else can be listed here.
EXTRA = ("scripts/bench/historical/galaga.py",)


def scripts():
    found = iter_files(os.path.join(ROOT, "scripts", "smoke"), ".py")
    found += iter_files(os.path.join(ROOT, "examples"), ".py", recursive=True,
                        skip_dirs={"media"})
    found += iter_files(os.path.join(ROOT, "tests", "loads"), ".py")
    found = [f for f in found if not os.path.basename(f).startswith("_")]
    found += [os.path.join(ROOT, f) for f in EXTRA]
    return sorted(found)


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


class TestScriptsRun(unittest.TestCase):
    def test_every_script_runs_headless(self):
        paths = scripts()
        self.assertGreater(len(paths), 40, "script discovery found too few files")
        workers = max(2, min(8, (os.cpu_count() or 4) - 1))
        with ThreadPoolExecutor(workers) as pool:
            results = list(pool.map(run_one, paths))
        failed = [(os.path.relpath(p, ROOT), msg) for p, ok, msg in results if not ok]
        self.assertEqual(
            failed, [],
            "\n".join(f"{p}:\n    {msg}" for p, msg in failed),
        )


if __name__ == "__main__":
    unittest.main()
