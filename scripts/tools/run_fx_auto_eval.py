"""
run_fx_auto_eval.py — run a battery of Auto stress scenarios then evaluate.

Each scenario is a subprocess (clean GLFW / Auto state). Requires a display.

Usage
-----
    python scripts/run_fx_auto_eval.py
    python scripts/run_fx_auto_eval.py --quick
    python scripts/run_fx_auto_eval.py --scenarios ramp_up,edge_jiggle,low_probe --n-max 400
    python scripts/run_fx_auto_eval.py --harder-up   # t_up=10 cooldown=2.5 k_up=0.45
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRESS = os.path.join(ROOT, "scripts", "app_fx_auto_stress.py")
EVAL = os.path.join(ROOT, "scripts", "eval_fx_auto.py")
OUT_DIR = os.path.join(ROOT, "scripts", "_fx_auto_runs")

DEFAULT_SCENARIOS = (
    "ramp_up",
    "stabilize",
    "sawtooth",
    "edge_jiggle",
    "fps_align",
    "low_probe",
)
QUICK_SCENARIOS = ("ramp_up", "edge_jiggle", "low_probe")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scenarios", default="", help="comma list (default battery)")
    p.add_argument("--quick", action="store_true", help="shorter battery")
    p.add_argument("--n-max", type=int, default=500)
    p.add_argument("--n", type=int, default=40)
    p.add_argument("--heavy", action="store_true", help="force --heavy on all")
    p.add_argument("--harder-up", action="store_true",
                   help="pass t_up=10, cooldown=2.5, k_up=0.45")
    p.add_argument("--t-up", type=float, default=None)
    p.add_argument("--cooldown", type=float, default=None)
    p.add_argument("--k-up", type=float, default=None)
    p.add_argument("--width", type=int, default=1200)
    p.add_argument("--height", type=int, default=800)
    p.add_argument("--out-dir", default=OUT_DIR)
    ns = p.parse_args()

    if ns.scenarios:
        scenarios = [s.strip() for s in ns.scenarios.split(",") if s.strip()]
    elif ns.quick:
        scenarios = list(QUICK_SCENARIOS)
    else:
        scenarios = list(DEFAULT_SCENARIOS)

    os.makedirs(ns.out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(ns.out_dir, stamp)
    os.makedirs(run_dir, exist_ok=True)

    t_up = ns.t_up
    cooldown = ns.cooldown
    k_up = ns.k_up
    if ns.harder_up:
        t_up = 10.0 if t_up is None else t_up
        cooldown = 2.5 if cooldown is None else cooldown
        k_up = 0.45 if k_up is None else k_up

    csv_paths = []
    results = []
    for name in scenarios:
        log = os.path.join(run_dir, f"{name}.csv")
        summary = os.path.join(run_dir, f"{name}_summary.json")
        cmd = [
            sys.executable, STRESS,
            "--scenario", name,
            "--auto",
            "--n", str(ns.n),
            "--n-max", str(ns.n_max),
            "--width", str(ns.width),
            "--height", str(ns.height),
            "--log", log,
            "--summary-json", summary,
        ]
        if ns.heavy or name == "low_probe":
            cmd.append("--heavy")
        if t_up is not None:
            cmd.extend(["--t-up", str(t_up)])
        if cooldown is not None:
            cmd.extend(["--cooldown", str(cooldown)])
        if k_up is not None:
            cmd.extend(["--k-up", str(k_up)])

        print(f"\n>>> Running {name}")
        print(" ", " ".join(cmd))
        # Scenarios self-quit; give generous wall timeout.
        timeout = 180 if name != "sawtooth" else 300
        try:
            proc = subprocess.run(cmd, cwd=ROOT, timeout=timeout)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            print(f"!!! timeout after {timeout}s: {name}")
            rc = 124
        csv_paths.append(log)
        results.append({"scenario": name, "rc": rc, "log": log, "summary": summary})

    report_json = os.path.join(run_dir, "eval_report.json")
    existing = [p for p in csv_paths if os.path.isfile(p) and os.path.getsize(p) > 32]
    if existing:
        print("\n>>> Evaluating logs")
        subprocess.run(
            [sys.executable, EVAL, *existing, "--json", report_json],
            cwd=ROOT,
        )
    else:
        print("No CSV logs produced.", file=sys.stderr)

    manifest = {
        "run_dir": run_dir,
        "scenarios": results,
        "n_max": ns.n_max,
        "harder_up": ns.harder_up,
        "t_up": t_up,
        "cooldown": cooldown,
        "k_up": k_up,
        "eval_report": report_json if existing else None,
    }
    man_path = os.path.join(run_dir, "manifest.json")
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nRun directory: {run_dir}")
    print(f"Manifest: {man_path}")
    return 0 if all(r["rc"] == 0 for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
