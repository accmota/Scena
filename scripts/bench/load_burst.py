"""CPU load burst for FX Auto stability checks.

After ``--delay`` seconds, keep ``--workers`` processes busy for ``--seconds``,
then exit. Start it in the background right before a probe run, so the burst
lands inside the run:

    python scripts/bench/load_burst.py --delay 30 --seconds 30 --workers 2
    # PowerShell (background):
    Start-Process -NoNewWindow python -ArgumentList "scripts/bench/load_burst.py --delay 30 --seconds 30 --workers 2"

``--workers all`` = one per CPU (heavy). Prints the wall-clock start and end
of the burst. Stdlib only; any OS.
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import sys
import time


def _burn(until: float) -> None:
    x = 0
    while time.time() < until:
        x += 1


def worker_count(value: str) -> int:
    if value == "all":
        return max(1, os.cpu_count() or 1)
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("--workers must be >= 1 or 'all'")
    return n


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--delay", type=float, default=30.0, help="seconds before the burst")
    p.add_argument("--seconds", type=float, default=30.0, help="burst length")
    p.add_argument("--workers", type=worker_count, default=2, help="busy processes, or 'all'")
    return p.parse_args(argv)


def run(delay: float, seconds: float, workers: int) -> None:
    time.sleep(max(0.0, delay))
    t0 = time.time()
    until = t0 + max(0.0, seconds)
    print(f"load_burst: {workers} busy worker(s) from {time.strftime('%H:%M:%S')}"
          f" for {seconds:g} s", flush=True)
    procs = [mp.Process(target=_burn, args=(until,), daemon=True) for _ in range(workers)]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join()
    print(f"load_burst: done at {time.strftime('%H:%M:%S')}", flush=True)


def main(argv=None) -> int:
    args = parse_args(argv)
    run(args.delay, args.seconds, args.workers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
