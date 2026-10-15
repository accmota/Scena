"""Run one Scena script headless: ``python tests/script_harness.py <script> [frames] [--strict]``.

Not a test module (no ``test_`` prefix). ``tests/test_scripts_run.py`` starts
one process per script with this file. ``scena.run`` is replaced by a loop of
the real frame body (``ScenaFramework._simulate_frame``) — the same order a
windowed run uses: ``update`` / processes / collision / flush — without a
window or a draw. The global ``random`` is seeded (0), so a run that fails
fails again. The script's own directory is the working directory (its
media paths are relative to it), or the folder its ``# harness: cwd=<dir>``
header names and ``sys.argv`` is just the script, so a
bench with argparse takes its defaults.

Prints ``SCRIPT OK <frames>`` on success. Any author error propagates with its
traceback and a non-zero exit.

``--strict`` (``tests/test_tutorial_steps.py``): a warning is a failure. Each one is
printed as ``SCRIPT WARNING <category>: <message>`` on stderr and the exit is 3.
A tutorial reader sees every warning in the console (a missing media file, a
near-miss group name), so a tutorial step must run without any.

``--laws <out.jsonl>`` (``tests/test_laws_*.py``): the laws recorder
(``tests/laws/trace.py``) runs from the script's first line and its trace is
written to ``out.jsonl`` (one event per line; a last ``["meta", ...]`` line
holds the counts and the recorder's own errors).

``--cwd DIR``: run from DIR instead of the script's folder (an equation's
rewritten twin of an example, saved under the same name in a temporary
folder, finds the example's media).

``--fingerprint``: after the frames, print ``SCRIPT FINGERPRINT <crc>`` — the
kind, origin and pose of every live, unowned object (the E0 neutrality
equation compares it with and without the recorder).
"""
from __future__ import annotations

import inspect
import os
import runpy
import sys
import warnings


def harness_cwd(script: str, root: str):
    """``# harness: cwd=<dir>`` on a script's first lines (repo-relative), or
    None. The game system tests and the bench games keep their art in
    ``examples/media`` and run from there (``tests/test_media_refs`` reads the
    same header)."""
    with open(script, encoding="utf-8") as fh:
        for _ in range(5):
            line = fh.readline()
            if line.startswith("# harness: cwd="):
                return os.path.join(root, line.split("=", 1)[1].strip())
    return None


def world_fingerprint() -> str:
    """CRC of (kind, origin, alive, rounded pose) of every live, unowned object."""
    import zlib
    from scena.entity import made_at
    from scena.canvas import ScenaCanvas
    rows = []
    for obj in list(ScenaCanvas.get_current().registry.live.values()):
        if getattr(obj, "_owner", None) is not None:
            continue
        row = [type(obj).__name__, made_at(obj) or "", bool(getattr(obj, "is_alive", True))]
        for attr in ("center", "angle"):
            try:
                v = getattr(obj, attr)
                v = (round(v.x, 6), round(v.y, 6)) if hasattr(v, "x") else round(float(v), 6)
            except Exception as e:     # a read that raises is part of the print
                v = f"<{type(e).__name__}>"
            row.append(v)
        rows.append(repr(row))
    rows.sort()
    return f"{len(rows)}:{zlib.crc32(chr(10).join(rows).encode('utf-8')):08x}"


def _flag_value(argv, name):
    """``name value`` out of ``argv``: (value or None, the rest)."""
    if name not in argv:
        return None, argv
    i = argv.index(name)
    return argv[i + 1], argv[:i] + argv[i + 2:]


def main(argv) -> None:
    strict = "--strict" in argv
    fingerprint = "--fingerprint" in argv
    argv = [a for a in argv if a not in ("--strict", "--fingerprint")]
    laws_out, argv = _flag_value(argv, "--laws")
    if laws_out is not None:
        laws_out = os.path.abspath(laws_out)     # the script runs from its own cwd
    # ``--cwd DIR``: run from DIR (a rewritten twin of an example, saved under
    # the example's own name elsewhere, still finds the example's media).
    cwd_override, argv = _flag_value(argv, "--cwd")
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
        if fingerprint:
            print(f"SCRIPT FINGERPRINT {world_fingerprint()}", flush=True)

    scena.run = headless_run
    here = os.path.dirname(script)
    os.chdir(cwd_override or harness_cwd(script, root) or here)
    sys.path.insert(0, here)
    sys.argv = [script]
    rec = None
    if laws_out is not None:
        from laws import trace
        rec = trace.install()
    try:
        runpy.run_path(script, run_name="__main__")
    finally:
        if rec is not None:
            trace.uninstall()
            rec.events.append(("meta", rec.counts, rec.errors))
            rec.dump(laws_out)
    if seen:
        for line in dict.fromkeys(seen):
            print(f"SCRIPT WARNING {line}", file=sys.stderr, flush=True)
        sys.exit(3)


if __name__ == "__main__":
    main(sys.argv)
