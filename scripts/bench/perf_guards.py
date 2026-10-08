"""Cost of the author-boundary guards: a ScalarSlot write and a keyp() lookup.

Prints microseconds per call. Compare a future guard against this row;
do not add per-frame work that moves these numbers.

    python scripts/bench/perf_guards.py
"""
from __future__ import annotations

import time

from scena import Circle, init, keyp


def time_slot_write(n: int = 2000) -> float:
    c = Circle(center=(0, 0), radius=10)
    c.radius = 10
    t0 = time.perf_counter()
    for i in range(n):
        c.radius = 10 + (i & 1)
    return (time.perf_counter() - t0) * 1e6 / n


def time_keyp(n: int = 2000) -> float:
    t0 = time.perf_counter()
    for _ in range(n):
        keyp("SPACE")
    return (time.perf_counter() - t0) * 1e6 / n


def main() -> None:
    init(width=200, height=200)
    print(f"ScalarSlot write  {time_slot_write():.2f} us")
    print(f"keyp lookup       {time_keyp():.2f} us")


if __name__ == "__main__":
    main()
