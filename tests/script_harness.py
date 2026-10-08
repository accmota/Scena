"""Run one Scena script headless: ``python tests/script_harness.py <script> [frames] [--strict]``.

Not a test module (no ``test_`` prefix). ``tests/test_scripts_run.py`` starts
one process per script with this file. ``scena.run`` is replaced by a loop of
the real frame body (``ScenaFramework._simulate_frame``) — the same order a
windowed run uses: ``update`` / processes / collision / flush — without a
window or a draw. The global ``random`` is seeded (0), so a run that fails
fails again. The script's own directory is the working directory (its
media paths are relative to it) and ``sys.argv`` is just the script, so a
bench with argparse takes its defaults.

Prints ``SCRIPT OK <frames>`` on success. Any author error propagates with its
traceback and a non-zero exit.

``--strict`` (``tests/test_tutorials.py``): a warning is a failure. Each one is
printed as ``SCRIPT WARNING <category>: <message>`` on stderr and the exit is 3.
A tutorial reader sees every warning in the console (a missing media file, a
near-miss group name), so a tutorial step must run without any.
"""
from __future__ import annotations

import inspect
import os
import runpy
import sys
import warnings


def main(argv) -> None:
    strict = "--strict" in argv
    argv = [a for a in argv if a != "--strict"]
    script = os.path.abspath(argv[1])
    frames = int(argv[2]) if len(argv) > 2 else 30
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, root)
    seen = []
    if strict:
        warnings.simplefilter("always")
        def collect(message, category, *_a, **_k):
            if category.__name__ != "GLFWError":    # no window here: a harness artifact
                seen.append(f"{category.__name__}: {message}")
        warnings.showwarning = collect
    else:
        warnings.simplefilter("ignore")  # missing art / placeholders are legal

    import random
    random.seed(0)                       # same draws every run: a failure reproduces

    import scena
    from scena.orchestration import ScenaFramework

    def headless_run(first_act=None):
        fw = ScenaFramework.get_instance()
        caller = inspect.currentframe().f_back.f_globals
        fw.set_auto_callbacks(caller)
        fw._begin_game(first_act)
        for _ in range(frames):
            fw._simulate_frame(dt=1.0 / 60.0)
        print(f"SCRIPT OK {frames}", flush=True)

    scena.run = headless_run
    here = os.path.dirname(script)
    os.chdir(here)
    sys.path.insert(0, here)
    sys.argv = [script]
    runpy.run_path(script, run_name="__main__")
    if seen:
        for line in dict.fromkeys(seen):
            print(f"SCRIPT WARNING {line}", file=sys.stderr, flush=True)
        sys.exit(3)


if __name__ == "__main__":
    main(sys.argv)
