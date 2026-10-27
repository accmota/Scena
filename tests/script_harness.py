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

``--pace HZ`` / ``--pace uneven``: the game time of ``frames`` at 60 Hz, in
frames of 1/HZ, or in alternating 5 ms / 28 ms frames (equation E1).

``--fingerprint``: after the frames, print ``SCRIPT FINGERPRINT <crc>`` — the
kind, origin and pose of every live, unowned object (the E0 neutrality
equation compares it with and without the recorder).

``--live-audio`` (``tests/test_audio_exit.py``): the mixer plays on a real
device thread (miniaudio's NULL backend, no speakers) instead of offline, and
the process ends without ``run()``'s cleanup: the exit path ``atexit`` owns.
"""
from __future__ import annotations

import inspect
import os
import runpy
import sys
import warnings

# The freeze budget a headless run uses (``main``; ProgramRun's PROGRAM_WATCHDOG_S).
HARNESS_WATCHDOG_S = 5.0


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


def pace_schedule(frames: int, pace=None):
    """The frame times: ``frames`` of 1/60 s, or the same game time at another
    pace (``"30"``, ``"144"``: 1/HZ each; ``"uneven"``: 5 ms and 28 ms in turn)."""
    total = frames / 60.0
    if pace is None or pace == "60":
        return [1.0 / 60.0] * frames
    if pace == "uneven":
        out, t, k = [], 0.0, 0
        while t < total - 1e-9:
            dt = min(0.005 if k % 2 == 0 else 0.028, total - t)
            out.append(dt)
            t += dt
            k += 1
        return out
    hz = float(pace)
    return [1.0 / hz] * int(round(total * hz))


def _flag_value(argv, name):
    """``name value`` out of ``argv``: (value or None, the rest)."""
    if name not in argv:
        return None, argv
    i = argv.index(name)
    return argv[i + 1], argv[:i] + argv[i + 2:]


def main(argv) -> None:
    strict = "--strict" in argv
    fingerprint = "--fingerprint" in argv
    live_audio = "--live-audio" in argv
    argv = [a for a in argv if a not in ("--strict", "--fingerprint", "--live-audio")]
    laws_out, argv = _flag_value(argv, "--laws")
    if laws_out is not None:
        laws_out = os.path.abspath(laws_out)     # the script runs from its own cwd
    # ``--cwd DIR``: run from DIR (a rewritten twin of an example, saved under
    # the example's own name elsewhere, still finds the example's media).
    cwd_override, argv = _flag_value(argv, "--cwd")
    # ``--pace HZ`` / ``--pace uneven``: the same game time as ``frames`` at
    # 60 Hz, in frames of 1/HZ, or alternating 5 ms / 28 ms (equation E1).
    pace, argv = _flag_value(argv, "--pace")
    # ``--chaos plan.json``: the chaos doors (tests/laws/chaos.py): the script
    # runs rewritten (every author return through ``__chaos__``) and the plan's
    # commands fire at their doors; the log goes where the plan says.
    chaos_spec, argv = _flag_value(argv, "--chaos")
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
    # A headless run counts frames, never wall time: the freeze watchdog's
    # 0.5 s budget for one async step cut string_theory's 160-line build under
    # the gate's load, and law E1 saw one pacing twin make fewer Lines (0.10.0
    # gate). Same rule as ProgramRun; a step that never yields still trips.
    import scena.process as _proc
    _proc.WATCHDOG_RESUME_S = max(_proc.WATCHDOG_RESUME_S, HARNESS_WATCHDOG_S)

    def headless_run(first_act=None):
        fw = ScenaFramework.get_instance()
        caller = inspect.currentframe().f_back.f_globals
        fw.set_auto_callbacks(caller)
        fw._begin_game(first_act)
        for dt in pace_schedule(frames, pace):
            fw._simulate_frame(dt=dt)
        print(f"SCRIPT OK {frames}", flush=True)
        if fingerprint:
            print(f"SCRIPT FINGERPRINT {world_fingerprint()}", flush=True)

    scena.run = headless_run
    if live_audio:
        import miniaudio
        from scena.audio_mixer import get_mixer
        get_mixer().start_device(backends=[miniaudio.Backend.NULL])
    here = os.path.dirname(script)
    os.chdir(cwd_override or harness_cwd(script, root) or here)
    sys.path.insert(0, here)
    sys.argv = [script]
    rec = None
    if laws_out is not None:
        from laws import trace
        rec = trace.Recorder()
        rec.motion = True                 # the motion laws read every resolve body's pose
        trace.install(rec)
    try:
        if chaos_spec is not None:
            from laws import chaos
            chaos.script_main(script, os.path.abspath(chaos_spec) if not os.path.isabs(chaos_spec)
                              else chaos_spec, lambda go: go())
        else:
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
