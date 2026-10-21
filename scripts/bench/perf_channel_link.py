"""Cost of pulling an appearance link (``shape["color"] @= lambda: …``).

Rows (microseconds per step): a Circle with ``CheapGlow`` moved one pixel and
read (``.fill``) with its colour linked to a ``Colormap`` of its x (the
constelação pattern); the same recolour written by hand on a Circle whose
center also feeds a formula (so both move on the same path); the hand
recolour on a plain Circle; the move alone; a linked ``visible`` flipping
every step; and a fleet of 55 such linked circles (the constelação pattern
before its example moved to ``every(0.25, …)``) each moved, then the
draw-head refresh that pulls them all (``refresh_linked_channels``).

Each block runs with the garbage collector off (collected before): a
collection landing in one side's block reads as a 10-20 % swing. Blocks are timed in process CPU time, not wall
time: with peer test runs loading the machine (load 20-60), wall-clock rows
that run no changed code swung ±13 %. CPU time is steadier but not immune:
read a row against the control rows (hand, move alone) of the same run.

In-process interleaved A/B: ``--ab REV`` execs the link write path as it is
at git revision REV (``_ChannelAnchor._takein_impl``,
``_PaintChannelAnchor._same``, ``entity._refuse_linked_channel``,
``style._refuse_linked_paint``) and swaps it in and out between blocks, so
both sides share one world, one heap and the machine's load of the moment.
Best block per side.

    python scripts/bench/perf_channel_link.py [--rounds 7]
    python scripts/bench/perf_channel_link.py --ab HEAD~1 [--pairs 9]
"""
from __future__ import annotations

import argparse
import ast
import gc
import subprocess
import sys
import textwrap
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

# (module, class or None, function)
SWAPPED = (
    ("state", "_ChannelAnchor", "_takein_impl"),
    ("state", "_PaintChannelAnchor", "_same"),
    ("entity", None, "_refuse_linked_channel"),
    ("style", None, "_refuse_linked_paint"),
)


def _old_side(rev: str) -> dict:
    """The swapped functions from ``rev``, each bound to a copy of its module's globals."""
    import importlib
    side = {}
    for mod_name, cls, fn in SWAPPED:
        mod = importlib.import_module(f"scena.{mod_name}")
        src = subprocess.check_output(
            ["git", "show", f"{rev}:scena/{mod_name}.py"], cwd=REPO, text=True)
        lines = src.splitlines(keepends=True)
        body = ast.parse(src).body
        if cls is not None:
            body = next(n for n in body if isinstance(n, ast.ClassDef) and n.name == cls).body
        node = next(n for n in body if isinstance(n, ast.FunctionDef) and n.name == fn)
        start = (node.decorator_list[0] if node.decorator_list else node).lineno - 1
        code = textwrap.dedent("".join(lines[start:node.end_lineno]))
        ns = dict(mod.__dict__)
        exec(compile(code, f"<{rev}:{mod_name}.{fn}>", "exec"), ns)
        side[(mod_name, cls, fn)] = ns[fn]
    return side


def _new_side() -> dict:
    import importlib
    side = {}
    for mod_name, cls, fn in SWAPPED:
        mod = importlib.import_module(f"scena.{mod_name}")
        owner = getattr(mod, cls) if cls else mod
        side[(mod_name, cls, fn)] = owner.__dict__[fn] if cls else getattr(mod, fn)
    return side


def _install(side: dict) -> None:
    import importlib
    for (mod_name, cls, fn), f in side.items():
        mod = importlib.import_module(f"scena.{mod_name}")
        if cls:
            setattr(getattr(mod, cls), fn, f)
        else:
            setattr(mod, fn, f)
            if fn == "_refuse_linked_channel":
                importlib.import_module("scena.shapes")._refuse_linked_channel = f


def _rows():
    from scena import Circle, CheapGlow, Colormap, Point, Rect, st
    cores = Colormap.from_colors("cyan", "medium purple", "hot pink", "orange")

    def made():
        c = Circle(center=(100, 100), radius=4)
        c.glow = CheapGlow(radius=6)
        return c

    linked = made()
    linked["color"] @= lambda: cores.get_color(linked.center.x / 800)
    live = made()
    feed = Point(0, 0)
    feed["x"] @= lambda: live.center.x       # the center feeds a formula: same move path
    plain = made()
    still = made()
    st.flag_n = 0
    flag = Rect()
    flag["visible"] @= lambda: st.flag_n % 2 == 0

    def step(s):
        s.move_by(1, 0)
        if s.center.x > 700:
            s.move_by(-600, 0)

    def link_row():
        step(linked)
        linked.fill

    def hand_live():
        step(live)
        live.color = cores.get_color(live.center.x / 800)
        live.fill

    def hand_plain():
        step(plain)
        plain.color = cores.get_color(plain.center.x / 800)
        plain.fill

    def move_only():
        step(still)
        still.fill

    def visible_row():
        st.flag_n += 1
        flag.visible

    from scena.entity import refresh_linked_channels
    fleet = []
    for i in range(55):
        c = made()
        c.move_by(i * 11, 0)
        c["color"] @= (lambda c=c: cores.get_color(c.center.x / 800))
        fleet.append(c)
    refresh_linked_channels()

    def fleet_row():
        for c in fleet:
            step(c)
        refresh_linked_channels()

    return {
        "linked colour (move + pull)": link_row,
        "hand, center feeds a formula": hand_live,
        "hand, plain circle": hand_plain,
        "move alone": move_only,
        "linked visible flip": visible_row,
        "55 linked circles + refresh": fleet_row,
    }


def _time(body, reps: int) -> float:
    gc.collect()
    gc.disable()
    try:
        t = time.process_time()
        for _ in range(reps):
            body()
        return (time.process_time() - t) / reps * 1e6
    finally:
        gc.enable()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rounds", type=int, default=7)
    ap.add_argument("--pairs", type=int, default=9)
    ap.add_argument("--reps", type=int, default=5000)
    ap.add_argument("--ab", default=None, help="git revision for the A side")
    args = ap.parse_args()

    from system_support import system_world
    with system_world(draw=False, quarantine=False):
        rows = {label: (body, args.reps // 50 if label.startswith("55") else args.reps)
                for label, body in _rows().items()}
        new = _new_side()
        old = _old_side(args.ab) if args.ab else None
        for label, (body, reps) in rows.items():
            for _ in range(min(200, reps)):
                body()
            if old is None:
                best = min(_time(body, reps) for _ in range(args.rounds))
                print(f"{label:30} {best:8.2f} us")
                continue
            sides = {"A": [], "B": []}
            for i in range(args.pairs):
                for side in (("A", "B") if i % 2 == 0 else ("B", "A")):
                    _install(old if side == "A" else new)
                    sides[side].append(_time(body, reps))
            _install(new)
            a, b = min(sides["A"]), min(sides["B"])
            print(f"{label:30} A {a:8.2f} us   B {b:8.2f} us   B/A {b / a:6.3f}")


if __name__ == "__main__":
    main()
