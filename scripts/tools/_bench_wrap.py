"""Phase-timing bench wrapper for Scena apps without built-in --bench.

Usage:
    python scripts/tools/_bench_wrap.py examples/naves_1.py
    python scripts/tools/_bench_wrap.py scripts/smoke/spatial.py --duration 3 --warmup 0.5
"""
from __future__ import annotations

import argparse
import os
import runpy
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bench"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from harness import empty_phase_stats, install_phase_run, print_phase_report  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("script", help="path to Scena app script")
parser.add_argument("--duration", type=float, default=3.0)
parser.add_argument("--warmup", type=float, default=0.5)
args, script_args = parser.parse_known_args()

_stats = empty_phase_stats()
_patched = False


def _bench_run():
    global _patched
    import scena.orchestration as orch

    fw = orch.ScenaFramework.get_instance()
    if fw is not None and not _patched:
        install_phase_run(
            fw,
            duration=args.duration,
            warmup=args.warmup,
            stats=_stats,
        )
        _patched = True
    return _orig_run()


import scena.orchestration as _orch  # noqa: E402

_orig_run = _orch.run
_orch.run = _bench_run

import scena as _stage  # noqa: E402

_stage.run = _bench_run

script_path = os.path.abspath(args.script)
if not os.path.isfile(script_path):
    print(f"Script not found: {script_path}", file=sys.stderr)
    sys.exit(1)

sys.argv = [script_path] + script_args
runpy.run_path(script_path, run_name="__main__")

if _patched:
    label = os.path.basename(script_path).replace(".py", "")
    print_phase_report(f"{label} — phase timing", _stats)
else:
    print("Warning: bench wrapper did not install (run() never called?)", file=sys.stderr)
    sys.exit(1)
