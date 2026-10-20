"""Cost of a point-like read in ``nearest`` / ``distance`` / ``heading``.

Rows (microseconds per call): ``group[...].nearest`` over N Circles with a
``where=`` (the constelação pattern), ``nearest`` over lists of Circles,
Sprites, tuples, Points and Vec2s, ``distance`` / ``heading`` between two
Circles and with ``mouse``, ``_xy_of`` on a tuple, a Point, a Vec2, mouse and
a cold Line (each the other callers of ``_xy_of``), and a stepped frame of
``examples/constelacao.py`` when that file exists.

In-process interleaved A/B: ``--ab REV`` execs ``_xy_of`` and ``nearest`` as
they are at git revision REV into a copy of the ``shapes`` namespace and
swaps them in and out of ``shapes`` / ``registry`` between blocks, so both
sides share one world, one heap and the machine's load of the moment
(separate runs drift 3-5 %). Best block per side.

    python scripts/bench/perf_nearest.py [--n 55] [--rounds 7]
    python scripts/bench/perf_nearest.py --ab HEAD~1 [--pairs 9]
"""
from __future__ import annotations

import argparse
import ast
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

SWAPPED = ("_xy_of", "nearest")


def _old_functions(rev: str, shapes) -> dict:
    """``_xy_of`` and ``nearest`` from ``rev``, bound to a copy of shapes' globals."""
    src = subprocess.check_output(
        ["git", "show", f"{rev}:scena/shapes.py"], cwd=REPO, text=True)
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    ns = dict(shapes.__dict__)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in SWAPPED:
            start = node.lineno - 1 if not node.decorator_list else node.decorator_list[0].lineno - 1
            code = "".join(lines[start:node.end_lineno])
            exec(compile(code, f"<{rev}:{node.name}>", "exec"), ns)
    return {name: ns[name] for name in SWAPPED}


def _install(side: dict, shapes, registry) -> None:
    shapes._xy_of = side["_xy_of"]
    shapes.nearest = side["nearest"]
    registry._nearest_item = side["nearest"]


def _rows(n: int, run):
    from scena import Circle, Sprite, Line, Point, Vec2, group, mouse, distance, heading
    from scena import shapes
    from random import Random
    rng = Random(7)
    circles = [Circle(center=(rng.uniform(0, 800), rng.uniform(0, 600)), radius=4, group="nb")
               for _ in range(n)]
    try:
        sprites = [Sprite(center=(rng.uniform(0, 800), rng.uniform(0, 600)), width=8, height=8)
                   for _ in range(n)]
    except Exception:
        sprites = None
    tuples = [(rng.uniform(0, 800), rng.uniform(0, 600)) for _ in range(n)]
    points = [Point(rng.uniform(0, 800), rng.uniform(0, 600)) for _ in range(n)]
    vecs = [Vec2(rng.uniform(0, 800), rng.uniform(0, 600)) for _ in range(n)]
    cold = Line(p1=(0, 0), p2=(10, 10))
    a, b = circles[0], circles[1]
    fleet = group["nb"]

    def group_where():
        for c in circles:
            fleet.nearest(c, where=lambda o, c=c: o is not c)

    def lst(items):
        def body():
            near = shapes.nearest
            near(a, items)
        return body

    def xy(obj):
        def body():
            f = shapes._xy_of
            for _ in range(n):
                f(obj)
        return body

    rows = {
        "group.nearest(where=) x N": (group_where, n),
        "nearest(circles)": (lst(circles), 1),
        "nearest(tuples)": (lst(tuples), 1),
        "nearest(points)": (lst(points), 1),
        "nearest(vec2s)": (lst(vecs), 1),
        "distance(circle, circle)": (lambda: [distance(a, b) for _ in range(n)], n),
        "heading(circle, mouse)": (lambda: [heading(a, mouse) for _ in range(n)], n),
        "_xy_of(tuple)": (xy(tuples[0]), n),
        "_xy_of(Point)": (xy(points[0]), n),
        "_xy_of(Vec2)": (xy(vecs[0]), n),
        "_xy_of(mouse)": (xy(mouse), n),
        "_xy_of(cold Line)": (xy(cold), n),
    }
    if sprites:
        rows["nearest(sprites)"] = (lst(sprites), 1)
    if run is not None:
        rows["constelacao frame"] = (lambda: run.step(1), 1)
    return rows


def _time(body, per: int, reps: int) -> float:
    t = time.perf_counter()
    for _ in range(reps):
        body()
    return (time.perf_counter() - t) / (reps * per) * 1e6


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=55)
    ap.add_argument("--rounds", type=int, default=7)
    ap.add_argument("--pairs", type=int, default=9)
    ap.add_argument("--ab", default=None, help="git revision for the A side")
    ap.add_argument("--program", default=str(REPO / "examples" / "constelacao.py"))
    args = ap.parse_args()

    from program_support import ProgramRun
    from scena import shapes, registry

    program = args.program if os.path.exists(args.program) else None
    if program is None:
        from system_support import SystemWorld
        ctx = SystemWorld(draw=False, quarantine=False)
    else:
        ctx = ProgramRun(program)
    with ctx as run:
        if program is not None:
            run.step(30)
        else:
            run = None
        rows = _rows(args.n, run)
        new = {name: getattr(shapes, name) for name in SWAPPED}
        old = _old_functions(args.ab, shapes) if args.ab else None
        for label, (body, per) in rows.items():
            reps = 3 if label == "constelacao frame" else 200
            body()
            if old is None:
                best = min(_time(body, per, reps) for _ in range(args.rounds))
                print(f"{label:28} {best:9.3f} us")
                continue
            sides = {"A": [], "B": []}
            for i in range(args.pairs):
                order = ("A", "B") if i % 2 == 0 else ("B", "A")
                for side in order:
                    _install(old if side == "A" else new, shapes, registry)
                    sides[side].append(_time(body, per, reps))
            _install(new, shapes, registry)
            a, b = min(sides["A"]), min(sides["B"])
            print(f"{label:28} A {a:9.3f} us   B {b:9.3f} us   B/A {b / a:6.3f}")


if __name__ == "__main__":
    main()
