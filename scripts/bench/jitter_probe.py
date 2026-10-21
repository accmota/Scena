"""Run any Scena script under the frame probe and report jitter / hitches / drift.

The script runs unmodified in the product loop (real pacing, present, GC).
Play it, watch it, or leave it alone; the window closes after ``--seconds``.

    python scripts/bench/jitter_probe.py examples/naves_1.py
    python scripts/bench/jitter_probe.py examples/barras_girando.py --seconds 120
    python scripts/bench/jitter_probe.py scripts/bench/live_mix.py --present fixed60 --seconds 300
    python scripts/bench/jitter_probe.py app.py --present vsync --json /tmp/j.json --trace /tmp/j.csv
    python scripts/bench/jitter_probe.py app.py --gc-freeze           # A/B: gc.freeze() after setup
    python scripts/bench/jitter_probe.py app.py -- --app-flag 1       # args after -- go to the app

``--present`` sets ``canvas.framerate`` at the first frame: ``keep`` (whatever
the script chose; default), ``auto`` (product default: FX Auto, display-locked
"vsync60" / "vsync30" rungs), ``vsync60`` / ``vsync30`` / ``vsync`` (locked:
nearest 60, nearest 30, every vblank), ``fixed60`` / ``fixed30`` (fixed-rate
timer), ``none`` (``"max"``, uncapped).

Run from the repo root (examples resolve ``media/`` paths from cwd).
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import runpy
import sys

_BENCH = os.path.dirname(os.path.abspath(__file__))
if _BENCH not in sys.path:
    sys.path.insert(0, _BENCH)

from frame_probe import FrameProbe, print_report  # noqa: E402

PRESENTS = ("keep", "auto", "fixed60", "fixed30", "vsync", "vsync60", "vsync30", "none")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("script", help="Scena script to run")
    p.add_argument("--seconds", type=float, default=60.0, help="close the window after this long (default 60)")
    p.add_argument("--present", choices=PRESENTS, default="keep")
    p.add_argument("--startup", type=float, default=10.0, help="seconds counted as the startup window (default 10)")
    p.add_argument("--objects-every", type=float, default=0.0,
                   help="count Python objects (gc.get_objects) every N s; 0 = off (costs a few ms each)")
    p.add_argument("--latch-ms", type=float, default=0.0, help="assumed compositor latch before vsync (default 0)")
    p.add_argument("--no-vsync-clock", action="store_true", help="skip the CoreVideo vsync timeline")
    p.add_argument("--gc-freeze", action="store_true",
                   help="A/B experiment: gc.collect(); gc.freeze() at the first frame")
    p.add_argument("--gc-threshold", type=str, default=None,
                   help="A/B experiment: gc.set_threshold(a[,b[,c]]) at the first frame")
    p.add_argument("--json", dest="json_path", default=None, help="write the full report as JSON")
    p.add_argument("--trace", default=None, help="write the per-frame trace as CSV")
    p.add_argument("--quiet", action="store_true", help="print only RESULT_JSON")
    return p


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    app_args = []
    if "--" in argv:
        k = argv.index("--")
        argv, app_args = argv[:k], argv[k + 1:]
    args = build_parser().parse_args(argv)
    script = os.path.abspath(args.script)
    if not os.path.isfile(script):
        raise SystemExit(f"no such script: {args.script}")

    def on_start(_fw):
        if args.gc_threshold:
            vals = [int(x) for x in args.gc_threshold.split(",") if x.strip()]
            gc.set_threshold(*vals)
        if args.gc_freeze:
            gc.collect()
            gc.freeze()

    import scena  # noqa: F401  (bootstraps the framework singleton)

    probe = FrameProbe(
        seconds=args.seconds,
        present=args.present,
        startup_s=args.startup,
        objects_every_s=args.objects_every,
        vsync=not args.no_vsync_clock,
        latch_ms=args.latch_ms,
        on_start=on_start if (args.gc_freeze or args.gc_threshold) else None,
    ).install()

    script_dir = os.path.dirname(script)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    old_argv = sys.argv
    sys.argv = [script] + app_args
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit:
        pass
    finally:
        sys.argv = old_argv
        probe.uninstall()

    rep = probe.analyze()
    rep["script"] = os.path.relpath(script)
    rep["experiments"] = {"gc_freeze": bool(args.gc_freeze), "gc_threshold": args.gc_threshold}
    if not args.quiet:
        print_report(rep, title=f"jitter probe — {rep['script']}  present={args.present}")
    if args.json_path:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_path)) or ".", exist_ok=True)
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=1, default=str)
            f.write("\n")
    if args.trace:
        probe.write_trace_csv(args.trace)
    summary = {
        "frames": rep.get("frames"),
        "fps": rep.get("fps"),
        "hitches_per_min": (rep.get("hitches") or {}).get("steady_per_min"),
        "held_per_min": (rep.get("present") or {}).get("held_per_min"),
        "episodes_per_min": (rep.get("present") or {}).get("episodes_per_min"),
    }
    print("RESULT_JSON: " + json.dumps(summary, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
