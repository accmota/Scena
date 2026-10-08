"""Cost of the field read/write/link paths that reactive fixes touch.

Prints microseconds per operation. Run on a clean tree and again after a
change (interleave old/new runs); a reactive fix must stay within the noise
floor of every row.

    python scripts/bench/perf_fields.py [--n 5000] [--rounds 5]
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scena import Circle, Line, Point, Rect, State, Vec2, init  # noqa: E402


def _per_call(fn, n: int) -> float:
    t0 = time.perf_counter()
    fn(n)
    return (time.perf_counter() - t0) * 1e6 / n


def case_scalar_write(n):
    c = Circle(center=(0, 0), radius=10)
    for i in range(n):
        c.radius = 10 + (i & 1)


def case_scalar_read(n):
    c = Circle(center=(0, 0), radius=10)
    for _ in range(n):
        c.radius


def case_vec2_arith(n):
    a, b = Vec2(3, 4), Vec2(1, 2)
    for _ in range(n):
        a + b


def case_vec2_length_read(n):
    v = Vec2(3, 4)
    for i in range(n):
        v.x = 3 + (i & 1)
        v.length


def case_linked_read_warm(n):
    st = State(name="pf")
    st.a = 1.0
    c = Circle(center=(0, 0), radius=10)
    c["radius"] @= lambda: st.a + 1
    c.radius
    for _ in range(n):
        c.radius


def case_linked_read_cold(n):
    st = State(name="pf2")
    st.a = 1.0
    c = Circle(center=(0, 0), radius=10)
    c["radius"] @= lambda: st.a + 1
    for i in range(n):
        st.a = float(i)
        c.radius


def case_rect_corner_read(n):
    r = Rect(p1=(0, 0), p2=(4, 3))
    for i in range(n):
        r.p2 = (4 + (i & 1), 3)
        r.top_left


def case_rect_linked_corner(n):
    st = State(name="pf3")
    st.a = 4.0
    r = Rect(p1=(0, 0), p2=(4, 3))
    r["p2"] @= lambda: (st.a, 3)
    for i in range(n):
        st.a = float(i)
        r.top_left


def case_pair_link_pull(n):
    st = State(name="pf4")
    st.a = 1.0
    p = Point(0, 0)
    p @= lambda: (st.a, 2)
    for i in range(n):
        st.a = float(i)
        p.x


def case_line_length(n):
    ln = Line(p1=(0, 0), p2=(3, 4))
    for i in range(n):
        ln.p2 = (3 + (i & 1), 4)
        ln.length


def case_move_by(n):
    r = Rect(center=(0, 0), width=10, height=5)
    for _ in range(n):
        r.move_by(0.1, 0.1)


CASES = [
    ("ScalarSlot write", case_scalar_write),
    ("ScalarSlot read", case_scalar_read),
    ("Vec2 a + b", case_vec2_arith),
    ("Vec2 write x + read length", case_vec2_length_read),
    ("linked scalar read (warm)", case_linked_read_warm),
    ("linked scalar write src + read", case_linked_read_cold),
    ("Rect write p2 + read corner", case_rect_corner_read),
    ("Rect linked p2 + read corner", case_rect_linked_corner),
    ("Point pair link + read", case_pair_link_pull),
    ("Line write p2 + read length", case_line_length),
    ("Rect move_by", case_move_by),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5000)
    ap.add_argument("--rounds", type=int, default=5)
    args = ap.parse_args()
    init(width=200, height=200)
    for label, fn in CASES:
        _per_call(fn, 200)  # warm up
        runs = [_per_call(fn, args.n) for _ in range(args.rounds)]
        print(f"{label:34s} median {statistics.median(runs):7.2f} us"
              f"   min {min(runs):7.2f}   max {max(runs):7.2f}")


if __name__ == "__main__":
    main()
