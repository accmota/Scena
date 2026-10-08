"""
perf_reactive_transform.py -- headless micro-benchmark for move/rotate cost.

Measures the reactive-system cost of transform-only workloads (no vertex /
Derivate reads) across shape kinds and RegularPolygon vertex counts.
Useful for quantifying O(n) bookkeeping regressions and verifying that
rotate/move stay flat in n after the deferred-wiring / batch-attrs fixes.

Usage:
    python scripts/perf_reactive_transform.py
    python scripts/perf_reactive_transform.py --n 100 --iters 200
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Allow `python scripts/perf_reactive_transform.py` from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scena import (  # noqa: E402
    Circle, EquilateralTriangle, Rect, RegularPolygon, Square, init,
)


def _bench(label: str, make_shape, n_shapes: int, iters: int, op) -> float:
    shapes = [make_shape(i) for i in range(n_shapes)]
    # Warmup
    for s in shapes:
        op(s)
    t0 = time.perf_counter()
    for _ in range(iters):
        for s in shapes:
            op(s)
    elapsed = time.perf_counter() - t0
    calls = iters * n_shapes
    per_us = (elapsed / calls) * 1e6 if calls else 0.0
    print(f"{label:42s}  total={elapsed:7.4f}s  per-call={per_us:8.2f} us  "
          f"({n_shapes} shapes x {iters} iters)")
    return per_us


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=200,
                        help="shapes per kind (default 200)")
    parser.add_argument("--iters", type=int, default=200,
                        help="transform iterations (default 200)")
    args = parser.parse_args()

    init(width=800, height=600, title="reactive transform perf")

    n, iters = args.n, args.iters
    print("=" * 72)
    print("Reactive transform micro-benchmark (no Derivate reads)")
    print("=" * 72)

    print("\n--- rotate_by(1.0) ---")
    results_rot = {}
    for vn in (6, 20, 60, 200):
        results_rot[f"RegularPolygon n={vn}"] = _bench(
            f"RegularPolygon n={vn}",
            lambda i, vn=vn: RegularPolygon(n=vn, center=(i % 50, i // 50), radius=10),
            n, iters, lambda s: s.rotate_by(1.0),
        )
    results_rot["EquilateralTriangle"] = _bench(
        "EquilateralTriangle",
        lambda i: EquilateralTriangle(center=(i % 50, i // 50), radius=10),
        n, iters, lambda s: s.rotate_by(1.0),
    )
    results_rot["Circle"] = _bench(
        "Circle",
        lambda i: Circle(center=(i % 50, i // 50), radius=10),
        n, iters, lambda s: s.rotate_by(1.0),
    )
    results_rot["Rect"] = _bench(
        "Rect",
        lambda i: Rect(center=(i % 50, i // 50), width=20, height=12),
        n, iters, lambda s: s.rotate_by(1.0),
    )
    results_rot["Square"] = _bench(
        "Square",
        lambda i: Square(center=(i % 50, i // 50), length=16),
        n, iters, lambda s: s.rotate_by(1.0),
    )

    print("\n--- move_by(0.1, 0.1) ---")
    for vn in (6, 20, 60, 200):
        _bench(
            f"RegularPolygon n={vn}",
            lambda i, vn=vn: RegularPolygon(n=vn, center=(i % 50, i // 50), radius=10),
            n, iters, lambda s: s.move_by(0.1, 0.1),
        )
    _bench(
        "EquilateralTriangle",
        lambda i: EquilateralTriangle(center=(i % 50, i // 50), radius=10),
        n, iters, lambda s: s.move_by(0.1, 0.1),
    )
    _bench(
        "Circle",
        lambda i: Circle(center=(i % 50, i // 50), radius=10),
        n, iters, lambda s: s.move_by(0.1, 0.1),
    )
    _bench(
        "Rect",
        lambda i: Rect(center=(i % 50, i // 50), width=20, height=12),
        n, iters, lambda s: s.move_by(0.1, 0.1),
    )

    # Scaling check: n=200 should not be much worse than n=6 after the fix.
    r6 = results_rot.get("RegularPolygon n=6", 0.0)
    r200 = results_rot.get("RegularPolygon n=200", 0.0)
    ratio = (r200 / r6) if r6 > 0 else float("inf")
    print("\n" + "=" * 72)
    print(f"rotate_by scaling: n=200 / n=6 = {ratio:.2f}x  "
          f"(target ~1x after fix; was ~10x+ before)")
    print("=" * 72)


if __name__ == "__main__":
    main()
