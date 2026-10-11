"""perf_audio_levels.py -- cost of audio levels as formula sources (``@= lambda: mic.level``).

In-process interleaved A/B, headless (``tests/system_support.SystemWorld``),
simulate half of the frame plus a read of every linked field (the pull that
draw would do). Per-frame microseconds, median of the rounds.

1. frame path, no mic: the frame body with and without the audio sample step
   (the old body is rebuilt from the current source minus that step).
2. frame path, a mic with no formula: same A/B (nothing is linked, so the
   sample list stays empty).
3. a mic driving a bar, a light (two fields) and a ``@when``:
   copy  -- ``on_update`` writes ``st.voz = amp_db(mic.level)``; formulas read ``st.voz``
   direct -- each formula reads ``amp_db(mic.level)``
   cell  -- ``st["voz"] @= lambda: amp_db(mic.level)``; formulas read ``st.voz``
   One capture block is ingested per frame, outside the timed region.

    python scripts/bench/perf_audio_levels.py [--frames 1500] [--rounds 12] [--shapes 100]
"""
from __future__ import annotations

import argparse
import inspect
import statistics
import sys
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import miniaudio  # noqa: E402
import numpy as np  # noqa: E402

from scena import Circle, Microphone, Rect, amp_db, st, when  # noqa: E402
from scena import orchestration as orch  # noqa: E402
from system_support import system_world  # noqa: E402

BLOCK = (np.random.default_rng(1).standard_normal((800, 2)) * 0.1).astype(np.float32).tobytes()


def _old_simulate_frame():
    """The frame body as it was before the audio sample step."""
    src = textwrap.dedent(inspect.getsource(orch.ScenaFramework._simulate_frame))
    lines = src.splitlines()
    out, skip = [], 0
    for line in lines:
        if "Audio levels a formula reads" in line:
            skip = 5   # comment (3 lines) + if + call
        if skip:
            skip -= 1
            continue
        out.append(line)
    code = "\n".join(out)
    assert "sample_level_sources" not in code, "could not strip the step"
    ns = {}
    exec(compile(code, orch.__file__, "exec"), orch.__dict__, ns)
    return ns["_simulate_frame"]


def _scene(n):
    for i in range(n):
        Circle(center=(i * 7 % 400, i * 13 % 300), radius=5)


def _time_frames(w, frames, reads, mic=None):
    fw = w.fw
    total = 0.0
    for _ in range(frames):
        if mic is not None:
            mic._ingest(BLOCK)
        t0 = time.perf_counter()
        fw._simulate_frame(dt=1 / 60)
        for r in reads:
            r()
        total += time.perf_counter() - t0
    return total * 1e6 / frames


def bench_frame_path(args, with_mic):
    new = orch.ScenaFramework._simulate_frame
    old = _old_simulate_frame()
    res = {"old": [], "new": []}
    with system_world(draw=False) as w:
        _scene(args.shapes)
        mic = Microphone(backends=[miniaudio.Backend.NULL]) if with_mic else None
        _time_frames(w, 200, ())
        for r in range(args.rounds):
            order = ("old", "new") if r % 2 == 0 else ("new", "old")
            for k in order:
                orch.ScenaFramework._simulate_frame = old if k == "old" else new
                res[k].append(_time_frames(w, args.frames, (), mic))
        orch.ScenaFramework._simulate_frame = new
        if mic is not None:
            mic.close()
    return {k: statistics.median(v) for k, v in res.items()}


def _build(kind, mic):
    bar = Rect(top_left=(20, 20), width=0, height=10)
    light = Circle(center=(200, 150), radius=10)
    hits = [0]
    if kind == "copy":
        st.voz = 0
        bar["width"] @= lambda: 300 * st.voz
        light["radius"] @= lambda: 30 + 120 * st.voz
        bar["height"] @= lambda: 10 + 10 * st.voz

        class Copier(Circle):
            def on_update(self, dt):
                st.voz = amp_db(mic.level)
        Copier(radius=1)

        @when(lambda: st.voz > 0.75)
        def clap():
            hits[0] += 1
    elif kind == "direct":
        bar["width"] @= lambda: 300 * amp_db(mic.level)
        light["radius"] @= lambda: 30 + 120 * amp_db(mic.level)
        bar["height"] @= lambda: 10 + 10 * amp_db(mic.level)

        @when(lambda: amp_db(mic.level) > 0.75)
        def clap():
            hits[0] += 1
    else:  # cell
        st["voz"] @= lambda: amp_db(mic.level)
        bar["width"] @= lambda: 300 * st.voz
        light["radius"] @= lambda: 30 + 120 * st.voz
        bar["height"] @= lambda: 10 + 10 * st.voz

        @when(lambda: st.voz > 0.75)
        def clap():
            hits[0] += 1
    return (lambda: bar.width, lambda: light.radius, lambda: bar.height)


def bench_mic_formulas(args):
    kinds = ("copy", "direct", "cell")
    res = {k: [] for k in kinds}
    for r in range(args.rounds):
        order = kinds if r % 2 == 0 else kinds[::-1]
        for k in order:
            with system_world(draw=False) as w:
                _scene(args.shapes)
                mic = Microphone(backends=[miniaudio.Backend.NULL])
                reads = _build(k, mic)
                _time_frames(w, 100, reads, mic)
                res[k].append(_time_frames(w, args.frames, reads, mic))
                mic.close()
                if k == "cell":
                    st["voz"].unlink()
    return {k: statistics.median(v) for k, v in res.items()}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--frames", type=int, default=1500)
    p.add_argument("--rounds", type=int, default=12)
    p.add_argument("--shapes", type=int, default=100)
    args = p.parse_args()
    for label, with_mic in (("no mic", False), ("mic, no formula", True)):
        m = bench_frame_path(args, with_mic)
        d = m["new"] - m["old"]
        print(f"frame path, {label:16s} old {m['old']:7.2f} us   new {m['new']:7.2f} us   "
              f"diff {d:+.2f} us ({d / m['old'] * 100:+.1f}%)")
    m = bench_mic_formulas(args)
    for k, v in m.items():
        print(f"mic + 3 formulas + @when, {k:6s} {v:7.2f} us/frame")


if __name__ == "__main__":
    main()
