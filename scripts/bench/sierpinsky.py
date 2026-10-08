"""Sierpinski reactive-graph stress (deep recursive ``@=`` midpoint links).

Interactive demo by default. Use ``--bench`` for phase-timed uncapped run.

Usage
-----
    python scripts/bench/sierpinsky.py
    python scripts/bench/sierpinsky.py --bench --depth 5 --duration 2 --warmup 0.4
"""
from __future__ import annotations

import argparse
import os
import sys

_parser = argparse.ArgumentParser(description=__doc__)
_parser.add_argument("--depth", type=int, default=5,
                     help="recursion depth (default 5; each level triples midpoints)")
_parser.add_argument("--bench", action="store_true",
                     help="uncapped FPS, phase-time, then exit")
_parser.add_argument("--duration", type=float, default=2.0)
_parser.add_argument("--warmup", type=float, default=0.4)
_parser.add_argument("--json", dest="json_path", default=None)
args, _ = _parser.parse_known_args()

from scena import *  # noqa: E402
from scena.orchestration import ScenaFramework  # noqa: E402
from scena.process import set_watchdog  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from perf_common import (  # noqa: E402
    average_phase_stats,
    empty_phase_stats,
    install_phase_run,
    print_phase_report,
    write_json,
)

set_watchdog(False)
set_fx_auto(False)


def sierpinsky(p1, p2, p3, depth=0):
    if depth == 0:
        Line(p1=lambda:p1, p2=lambda:p2).set_color("yellow")
        Line(p1=lambda:p2, p2=lambda:p3).set_color("yellow")
        Line(p1=lambda:p3, p2=lambda:p1).set_color("yellow")
        return

    m12 = Point()
    m23 = Point()
    m31 = Point()

    m12 @= lambda: middle_point(p1, p2)
    m23 @= lambda: middle_point(p2, p3)
    m31 @= lambda: middle_point(p3, p1)

    sierpinsky(p1, m12, m31, depth - 1)
    sierpinsky(m12, p2, m23, depth - 1)
    sierpinsky(m31, m23, p3, depth - 1)


side = canvas.height - 100 - 100
ref_min = (canvas.width / 2) - 400
ref_max = (canvas.width / 2) + 400
st.reference = canvas.width / 2
going_right = True

p1 = Point(x=float(st.reference), y=100)
p1["x"] @= st.reference
p2 = Point(x=canvas.width / 2 - (side / 2), y=canvas.height - 100)
p3 = Point(x=canvas.width / 2 + (side / 2), y=canvas.height - 100)

sierpinsky(p1, p2, p3, max(0, int(args.depth)))

if not args.bench:
    p1.show_handles()
    p2.show_handles()
    p3.show_handles()


def update(dt):
    global going_right
    step = 100 * dt
    if going_right:
        st.reference += step
        if st.reference >= ref_max:
            st.reference = ref_max
            going_right = False
    else:
        st.reference -= step
        if st.reference <= ref_min:
            st.reference = ref_min
            going_right = True



canvas.framerate = "max"

if args.bench:
    import json
    fw = ScenaFramework.get_instance()
    stats = empty_phase_stats()
    install_phase_run(
        fw,
        duration=args.duration,
        warmup=args.warmup,
        stats=stats,
    )
    run()
    print_phase_report(f"Sierpinski depth={args.depth} — phase timing", stats)
    avg = average_phase_stats(stats)
    payload = {
        "ok": True,
        "probe": "sierpinski",
        "depth": args.depth,
        "fps": avg["fps"],
        "work_ms": avg["work_ms"],
        "tick_ms": avg["tick_ms"],
        "flush_ms": avg["flush_ms"],
        "draw_ms": avg["draw_ms"],
        "frames": avg["frames"],
    }
    print("RESULT_JSON: " + json.dumps(payload))
    if args.json_path:
        payload["phases"] = avg
        write_json(args.json_path, payload)
else:
    run()
