"""Run the tracked pulses back to back and refresh the dashboard.

Opens GLFW windows — not for CI. Close other GPU-heavy apps first.

    python scripts/bench/run_all.py
    python scripts/bench/run_all.py --skip fx          # skip the long matrix
    python scripts/bench/run_all.py --only balanced,sched
    python scripts/bench/run_all.py --long              # also the 5-min longrun pulse
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from typing import List

from fingerprint import BENCH_DIR, REPO_ROOT

STEPS = (
    ("balanced", [sys.executable, str(BENCH_DIR / "run_balanced.py"), "--comparable", "--notes", ""]),
    ("sched", [sys.executable, str(BENCH_DIR / "sched.py"), "--pulse"]),
    ("fx", [sys.executable, str(BENCH_DIR / "run_fx.py"), "--comparable"]),
    ("text", [sys.executable, str(BENCH_DIR / "perf_text.py"), "--pulse"]),
    ("graph", [sys.executable, str(BENCH_DIR / "run_graph.py")]),
    ("resolve", [sys.executable, str(BENCH_DIR / "run_resolve.py"), "--comparable", "--notes", ""]),
    ("background", [sys.executable, str(BENCH_DIR / "perf_background.py"), "--pulse"]),
    ("startup", [sys.executable, str(BENCH_DIR / "perf_startup.py"), "--pulse"]),
    ("assets", [sys.executable, str(BENCH_DIR / "perf_assets.py"), "--pulse"]),
    ("longrun", [sys.executable, str(BENCH_DIR / "longrun.py"), "--pulse"]),
)
# Minutes-long steps run only with --long or when named in --only.
LONG_STEPS = {"longrun"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only", default=None,
        help="comma-separated subset (" + ",".join(s[0] for s in STEPS) + ")",
    )
    parser.add_argument(
        "--long", action="store_true",
        help="include minutes-long steps (" + ",".join(sorted(LONG_STEPS)) + ")",
    )
    parser.add_argument(
        "--skip", default=None,
        help="comma-separated names to skip",
    )
    parser.add_argument(
        "--no-append", action="store_true",
        help="forward --no-append to runners (preview; do not write logs)",
    )
    args = parser.parse_args()
    names = [s[0] for s in STEPS]
    if args.only:
        want = {p.strip() for p in args.only.split(",") if p.strip()}
        unknown = want - set(names)
        if unknown:
            raise SystemExit(f"unknown --only: {sorted(unknown)}")
        names = [n for n in names if n in want]
    elif not args.long:
        names = [n for n in names if n not in LONG_STEPS]
    if args.skip:
        skip = {p.strip() for p in args.skip.split(",") if p.strip()}
        names = [n for n in names if n not in skip]

    t0 = time.perf_counter()
    failed: List[str] = []
    for key, argv in STEPS:
        if key not in names:
            continue
        cmd = list(argv)
        if args.no_append and "--no-append" not in cmd:
            cmd.append("--no-append")
        print("\n" + "#" * 60, flush=True)
        print(f"# {key}: {' '.join(cmd[1:])}", flush=True)
        print("#" * 60, flush=True)
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT))
        if proc.returncode != 0:
            failed.append(key)
            print(f"!! {key} exited {proc.returncode}", flush=True)
    # Always refresh the index from whatever logs exist.
    dash = subprocess.run(
        [sys.executable, str(BENCH_DIR / "dashboard.py")],
        cwd=str(REPO_ROOT),
    )
    elapsed = time.perf_counter() - t0
    print(f"\nrun_all elapsed={elapsed:.1f}s  steps={names}")
    if dash.returncode != 0:
        failed.append("dashboard")
    if failed:
        raise SystemExit(f"failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
