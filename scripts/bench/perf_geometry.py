"""Cost of the geometry hot paths the geometry campaign's fixes touch.

Rows: pose verbs on a free shape of each family (move, rotate, scale, flip),
`angle =` writes, a linked `angle` pull, a linked part pull, a heading read,
and a drawn frame of turning shapes. Prints microseconds per operation.

    python scripts/bench/perf_geometry.py [--n 3000] [--rounds 5] [--rows move,rotate]

A/B against a pristine copy of HEAD (alternating short runs, best block per
side; separate runs drift 3-5 % with the machine's load):

    git archive HEAD | tar -x -C /tmp/scena_head
    python scripts/bench/perf_geometry.py --ab /tmp/scena_head [--pairs 12]

``--tree DIR`` imports ``scena`` from DIR instead of this checkout (the A/B
driver uses it for the HEAD side).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _import_scena(tree: str | None):
    sys.path.insert(0, str(Path(tree).resolve() if tree else REPO))
    import scena  # noqa: F401
    return scena


def _rows(scena):
    from scena import (
        Circle, Ellipse, Line, Polygon, Rect, RegularPolygon, Sprite, State, Text, init,
    )
    init(width=200, height=200)

    def kinds():
        return {
            "Rect": lambda: Rect(center=(0, 0), width=10, height=5, angle=10),
            "Circle": lambda: Circle(center=(0, 0), radius=10),
            "Line": lambda: Line(p1=(0, 0), p2=(10, 3)),
            "Ellipse": lambda: Ellipse(center=(0, 0), width=10, height=4, angle=10),
            "RegularPolygon": lambda: RegularPolygon(center=(0, 0), radius=6, n=5, angle=10),
            "Polygon": lambda: Polygon(points=[(0, 0), (5, 0), (4, 4), (0, 3)]),
            "Spine": lambda: Rect(p1=(0, 0), p2=(20, 5), height=4, anchor="cap"),
            "Text": lambda: Text("hi", center=(0, 0)),
        }

    rows = {}

    def verb_row(name, make, step):
        def run(n):
            o = make()
            step(o, 0)
            t0 = time.perf_counter()
            for i in range(n):
                step(o, i)
            return (time.perf_counter() - t0) * 1e6 / n
        rows[name] = run

    for k, make in kinds().items():
        verb_row(f"move_by {k}", make, lambda o, i: o.move_by(0.1, -0.1))
        verb_row(f"rotate_by {k}", make, lambda o, i: o.rotate_by(1.0))
        if k != "Text":
            verb_row(f"scale_by {k}", make, lambda o, i: o.scale_by(1.0001 if i & 1 else 0.9999))
            verb_row(f"flip_x {k}", make, lambda o, i: setattr(o, "flip_x", bool(i & 1)))
        verb_row(f"angle = {k}", make, lambda o, i: setattr(o, "angle", 10.0 + (i & 7)))

    def linked_angle(n):
        st = State(name="pg_a")
        st.a = 0.0
        r = RegularPolygon(center=(0, 0), radius=6, n=5, angle=17)
        r["angle"] @= lambda: st.a
        r.angle
        t0 = time.perf_counter()
        for i in range(n):
            st.a = float(i & 63)
            r.angle
        return (time.perf_counter() - t0) * 1e6 / n
    rows["linked angle pull RegularPolygon"] = linked_angle

    def linked_part(n):
        st = State(name="pg_c")
        st.x = 0.0
        c = Circle(center=(0, 0), radius=5)
        c["center"] @= lambda: (st.x, 1.0)
        c.center.x
        t0 = time.perf_counter()
        for i in range(n):
            st.x = float(i & 63)
            c.center.x
        return (time.perf_counter() - t0) * 1e6 / n
    rows["linked center pull Circle"] = linked_part

    def heading_read(n):
        ln = Line(p1=(0, 0), p2=(10, 3))
        t0 = time.perf_counter()
        for i in range(n):
            ln.p2 = (10, 3 + (i & 1))
            ln.angle
        return (time.perf_counter() - t0) * 1e6 / n
    rows["Line write p2 + read angle"] = heading_read

    def frame(n):
        import skia
        objs = [Rect(center=(i * 3 % 200, i * 7 % 200), width=8, height=4) for i in range(80)]
        objs += [Circle(center=(i * 5 % 200, i * 11 % 200), radius=4) for i in range(80)]
        surf = skia.Surface(200, 200)
        cv = surf.getCanvas()
        reps = max(1, n // 100)
        t0 = time.perf_counter()
        for _ in range(reps):
            for o in objs:
                o.rotate_by(1.0)
                o.move_by(0.1, 0.0)
            for o in objs:
                o.draw(cv)
        dt = (time.perf_counter() - t0) * 1e6 / reps
        for o in objs:
            o.destroy()
        return dt
    rows["160 shapes turn + move + draw (per frame)"] = frame
    return rows


def run_rows(tree, n, rounds, only):
    scena = _import_scena(tree)
    rows = _rows(scena)
    out = {}
    for name, fn in rows.items():
        if only and not any(o in name for o in only):
            continue
        fn(max(50, n // 20))
        out[name] = min(fn(n) for _ in range(rounds))
    return out


def ab(head_tree, n, pairs, only):
    """Alternate HEAD / working-tree subprocesses; keep each side's best run."""
    best = {"head": {}, "work": {}}
    order = [("head", head_tree), ("work", None)]
    for k in range(pairs):
        for side, tree in (order if k % 2 == 0 else order[::-1]):
            cmd = [sys.executable, __file__, "--json", "--n", str(n), "--rounds", "1"]
            if tree:
                cmd += ["--tree", tree]
            if only:
                cmd += ["--rows", ",".join(only)]
            res = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"}, cwd=str(REPO),
            )
            if res.returncode:
                raise SystemExit(res.stderr)
            for name, v in json.loads(res.stdout.strip().splitlines()[-1]).items():
                best[side][name] = min(v, best[side].get(name, v))
    print(f"{'row':44s} {'HEAD':>9s} {'work':>9s} {'delta':>8s}")
    for name in best["head"]:
        h, w = best["head"][name], best["work"].get(name, float("nan"))
        print(f"{name:44s} {h:9.2f} {w:9.2f} {100 * (w - h) / h:+7.1f}%")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3000)
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--rows", default="")
    ap.add_argument("--tree", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--ab", default=None, metavar="HEAD_TREE")
    ap.add_argument("--pairs", type=int, default=12)
    args = ap.parse_args()
    only = [r for r in args.rows.split(",") if r]
    if args.ab:
        ab(args.ab, args.n, args.pairs, only)
        return
    out = run_rows(args.tree, args.n, args.rounds, only)
    if args.json:
        print(json.dumps(out))
        return
    for name, v in out.items():
        print(f"{name:44s} {v:8.2f} us")


if __name__ == "__main__":
    main()
