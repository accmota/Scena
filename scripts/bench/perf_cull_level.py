#!/usr/bin/env python3
"""perf_cull_level.py — ``canvas.cull_offscreen`` on a real game level, in-process A/B.

Runs an example unmodified (default: ``examples/ninja_nivel.py``, tutorial 21:
a 4000-wide level in a 1000-wide window) inside the phase-timed loop of
``harness.install_phase_run``, sweeps the camera across the level, and flips
``cull_offscreen`` every ``--block`` frames. Each OFF block replays the camera
positions of the ON block before it, so both sides see the same views.

The example's own camera follow is held off (``st.seguir`` stays False): the
sweep decides the view. Report: ms per frame for draw (recording the draw
calls), submit + present (GPU), and the whole frame (``work``), plus how many
objects the draw walk kept / skipped.

    python scripts/bench/perf_cull_level.py
    python scripts/bench/perf_cull_level.py --seconds 30 --block 60 --sweep 600
    python scripts/bench/perf_cull_level.py --script examples/ninja_perigos.py
"""
from __future__ import annotations

import argparse
import json
import math
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)

from harness import install_phase_run  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--script", default=os.path.join(REPO, "examples", "ninja_nivel.py"))
    p.add_argument("--seconds", type=float, default=20.0, help="recorded time")
    p.add_argument("--warmup", type=float, default=4.0,
                   help="unrecorded start (the example opens zoomed out on the whole level)")
    p.add_argument("--block", type=int, default=60, help="frames per ON / OFF block")
    p.add_argument("--only", choices=("on", "off"), default=None,
                   help="no A/B: keep one side the whole run (checks that flipping is not the cost)")
    p.add_argument("--sweep", type=int, default=480,
                   help="ON-frames for one camera pass left → right → left")
    p.add_argument("--x-min", type=float, default=500.0)
    p.add_argument("--x-max", type=float, default=3500.0)
    p.add_argument("--y", type=float, default=375.0)
    p.add_argument("--json", dest="json_path", default=None)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    script = os.path.abspath(args.script)

    import scena  # noqa: F401  (bootstraps the framework singleton)
    from scena import canvas, st
    from scena.orchestration import ScenaFramework

    fw = ScenaFramework.get_instance()
    draw = None                                  # the ScenaCanvas, once the window is open

    keys = ("draw_ms", "submit_ms", "present_ms", "work_ms")
    side = {on: {k: 0.0 for k in keys + ("frames", "kept", "skipped")} for on in (True, False)}
    state = {"rec_frame": 0, "last": {k: 0.0 for k in keys}}

    def camera_x(i: int) -> float:
        # Ping-pong across [x_min, x_max]; i counts ON-side frames.
        phase = (i % args.sweep) / args.sweep
        u = 0.5 - 0.5 * math.cos(2 * math.pi * phase)
        return args.x_min + (args.x_max - args.x_min) * u

    def on_frame(framework, recording):
        nonlocal draw
        if draw is None:
            draw = framework._scena_draw
        if hasattr(st, "seguir"):
            st.seguir = False                    # the sweep decides the view
        if not recording:
            canvas.cull_offscreen = args.only != "off"
            state["last"] = {k: stats[k] for k in keys}
            canvas.pan_to((camera_x(0), args.y))
            return
        on = bool(canvas.cull_offscreen)         # the side the frame just drawn ran on
        acc = side[on]
        for k in keys:
            acc[k] += stats[k] - state["last"][k]
            state["last"][k] = stats[k]
        acc["frames"] += 1
        acc["kept"] += draw._cull_kept
        acc["skipped"] += draw._cull_skipped

        n = state["rec_frame"]
        state["rec_frame"] = n + 1
        nb, npos = divmod(n + 1, args.block)
        next_on = nb % 2 == 0 if args.only is None else args.only == "on"
        canvas.cull_offscreen = next_on
        # ON block k and the OFF block after it visit the same positions.
        canvas.pan_to((camera_x((nb // 2) * args.block + npos), args.y))

    script_dir = os.path.dirname(script)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    stats = install_phase_run(fw, duration=args.seconds, warmup=args.warmup, on_frame=on_frame)

    old_argv = sys.argv
    sys.argv = [script]
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit:
        pass
    finally:
        sys.argv = old_argv

    rep = {"script": os.path.relpath(script, REPO), "block": args.block,
           "sweep": args.sweep, "seconds": args.seconds}
    print(f"\ncull_offscreen A/B — {rep['script']}  block={args.block} sweep={args.sweep}")
    print(f"{'':10}{'frames':>8}{'kept':>8}{'skipped':>9}{'draw':>9}{'sub+pres':>10}{'work':>9}  (ms/frame)")
    for on in (False, True):
        a = side[on]
        f = max(1.0, a["frames"])
        row = {
            "frames": int(a["frames"]),
            "kept": a["kept"] / f,
            "skipped": a["skipped"] / f,
            "draw_ms": a["draw_ms"] / f,
            "gpu_ms": (a["submit_ms"] + a["present_ms"]) / f,
            "work_ms": a["work_ms"] / f,
        }
        rep["on" if on else "off"] = row
        print(f"{'cull on' if on else 'cull off':10}{row['frames']:>8}{row['kept']:>8.1f}"
              f"{row['skipped']:>9.1f}{row['draw_ms']:>9.3f}{row['gpu_ms']:>10.3f}{row['work_ms']:>9.3f}")
    off, on_ = rep["off"], rep["on"]
    if off["work_ms"] > 0:
        print(f"work: {100.0 * (on_['work_ms'] - off['work_ms']) / off['work_ms']:+.1f} %   "
              f"draw: {100.0 * (on_['draw_ms'] - off['draw_ms']) / max(1e-9, off['draw_ms']):+.1f} %")
    print("RESULT_JSON: " + json.dumps(rep))
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, indent=1)
            fh.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
