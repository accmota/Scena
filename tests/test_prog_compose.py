"""Program model, Tier B: random compositions of small behaviours (non-interference).

Each behaviour is a code template plus the expectations it guarantees **alone**
(written from the Guia; design/Testing Design.md, "Program model tests"). The
composer draws 2-6 behaviours, renders one author program (``from scena
import *``, one ``update(dt)``, ``run()``), runs it through the program harness
with a drawn dt, and checks every behaviour's expectations. Behaviours share
nothing unless a coupling says so, so a divergence means one feature disturbed
another (or the expectation was wrong: triage per tests/program_ledger.py).

    python -m unittest tests.test_prog_compose -v
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
import unittest
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import boot  # noqa: E402,F401  (profiles)
from hypothesis import given, note, settings, strategies as hst  # noqa: E402

from program_support import ProgramRun, Trace, close  # noqa: E402

Check = Callable[[Trace], Optional[str]]


@dataclass
class Behaviour:
    name: str
    setup: str                         # module-level code
    update: str = ""                   # lines inside update(dt)
    probes: Dict[str, Callable] = field(default_factory=dict)
    checks: List[Tuple[str, Check]] = field(default_factory=list)
    steps: List[Tuple] = field(default_factory=list)   # input steps (run first)
    fired: Optional[Check] = None      # vacuity: None when the behaviour did act
    camera: bool = False               # at most one camera behaviour per program


def _first_fail(t: Trace, probe: str, want: Callable[[float, int], object], tol: float,
                after_frame: int = 0) -> Optional[str]:
    for s in t.samples:
        if s.frame <= after_frame:
            continue
        got, exp = s.values.get(probe), want(s.time, s.frame)
        if not close(got, exp, tol):
            return f"{probe} at frame {s.frame} (t={s.time:.4f}): {got!r} != {exp!r}"
    return None


# --------------------------------------------------------------------------
# Behaviours (Guia citations in each docstring line)
# --------------------------------------------------------------------------

def mover(p, x0, y0, vx, vy):
    """move_by(dx, dy) in update(dt) moves by exactly that (Guia #pose-move-by)."""
    return Behaviour(
        "mover", f"{p} = Circle(center=({x0}, {y0}), radius=6)\n",
        f"    {p}.move_by({vx} * dt, {vy} * dt)\n",
        {f"{p}_c": lambda v: getattr(v, p).center},
        [("moves by v*t", lambda t: _first_fail(
            t, f"{p}_c", lambda tm, _f: (x0 + vx * tm, y0 + vy * tm), 1e-6))],
        fired=lambda t: None if (vx or vy) else "still")


def spinner(p, w):
    """rotate_by(dθ) accumulates; .angle is not wrapped (Guia #pose-rotate-by, PM1)."""
    return Behaviour(
        "spinner", f"{p} = Rect(center=(100, 100), width=30, height=10)\n",
        f"    {p}.rotate_by({w} * dt)\n",
        {f"{p}_a": lambda v: getattr(v, p).angle},
        [("angle = w*t", lambda t: _first_fail(t, f"{p}_a", lambda tm, _f: w * tm, 1e-6))])


def ticker(p, interval):
    """every(T, fn) calls fn again each interval, in game time (Guia #tempo)."""
    return Behaviour(
        "ticker",
        f"st.{p} = 0\n"
        f"def {p}_tick():\n    st.{p} += 1\n"
        f"every({interval}, {p}_tick)\n",
        "",
        {f"{p}_n": lambda v: getattr(v.st, p)},
        [("count = floor(t/T) within one tick", lambda t: next(
            (f"{p}_n at t={s.time:.4f}: {s.values[f'{p}_n']} vs {math.floor(s.time / interval + 1e-9)}"
             for s in t.samples
             if abs(s.values[f"{p}_n"] - math.floor(s.time / interval + 1e-9)) > 1), None))],
        fired=lambda t: None if t.end(f"{p}_n") else "never ticked")


def delayed_destroy(p, delay):
    """obj.after(T, obj.destroy): alive until T, gone after (Guia #tempo)."""
    def chk(t):
        for s in t.samples:
            alive = s.values[f"{p}_alive"]
            if s.time < delay - 1.5 / 60 and not alive:
                return f"destroyed early at t={s.time:.4f}"
            if s.time > delay + 1.5 / 60 and alive:
                return f"still alive at t={s.time:.4f}"
        return None
    return Behaviour(
        "delayed_destroy",
        f"{p} = Circle(center=(300, 300), radius=4, group='{p}_g')\n"
        f"{p}.after({delay}, {p}.destroy)\n",
        "",
        {f"{p}_alive": lambda v: bool(getattr(v, p).is_alive),
         f"{p}_n": lambda v: len(v.group[f"{p}_g"])},
        [("dies at T", chk),
         ("leaves its group with it", lambda t: next(
             (f"group count {s.values[f'{p}_n']} vs alive {s.values[f'{p}_alive']} at frame {s.frame}"
              for s in t.samples if s.values[f"{p}_n"] != int(s.values[f"{p}_alive"])), None))],
        fired=lambda t: None if not t.end(f"{p}_alive") else "never died")


def tween(p, x0, x1, dur):
    """move_to(x, y, time=T) arrives at T and stays (Guia #pose-move-to)."""
    def chk(t):
        for s in t.samples:
            c = s.values[f"{p}_c"]
            lo, hi = min(x0, x1) - 1e-6, max(x0, x1) + 1e-6
            if not (lo <= c[0] <= hi) or abs(c[1] - 200.0) > 1e-6:
                return f"left the segment at frame {s.frame}: {c}"
            if s.time >= dur + 1e-9 and abs(c[0] - x1) > 1e-6:
                return f"not at the target after T: frame {s.frame} x={c[0]}"
        return None
    return Behaviour(
        "tween",
        f"{p} = Circle(center=({x0}, 200), radius=4)\n"
        f"{p}.move_to({x1}, 200, time={dur})\n",
        "",
        {f"{p}_c": lambda v: getattr(v, p).center},
        [("arrives and stays on the segment", chk)])


def follower(p, k):
    """b["center"] @= lambda: a.center + (k, 0): fresh every frame (Guia #reativo)."""
    return Behaviour(
        "follower",
        f"{p}a = Circle(center=(50, 400), radius=4)\n"
        f"{p}b = Circle(center=(0, 0), radius=4)\n"
        f"{p}b['center'] @= lambda: {p}a.center + ({k}, 0)\n",
        f"    {p}a.move_by(30 * dt, 10 * dt)\n",
        {f"{p}_a": lambda v: getattr(v, p + "a").center,
         f"{p}_b": lambda v: getattr(v, p + "b").center},
        [("b = a + (k, 0) every frame", lambda t: next(
            (f"frame {s.frame}: b {s.values[f'{p}_b']} vs a {s.values[f'{p}_a']}"
             for s in t.samples
             if not close(s.values[f"{p}_b"], (s.values[f"{p}_a"][0] + k, s.values[f"{p}_a"][1]), 1e-9)),
            None))])


def when_once(p, n):
    """@when fires on the False -> True passage, not while it stays True (Guia #reagir-when)."""
    def chk(t):
        for s in t.samples:
            c, fired = s.values[f"{p}_c"], s.values[f"{p}_f"]
            if c < n and fired:
                return f"fired before the counter reached {n} (frame {s.frame})"
            if c >= n + 2 and fired != 1:
                return f"fired {fired} times by frame {s.frame} (counter {c})"
        return None
    return Behaviour(
        "when_once",
        f"st.{p}_c = 0\nst.{p}_f = 0\n"
        f"@when(lambda: st.{p}_c >= {n})\n"
        f"def {p}_hit():\n    st.{p}_f += 1\n",
        f"    st.{p}_c += 1\n",
        {f"{p}_c": lambda v: getattr(v.st, f"{p}_c"), f"{p}_f": lambda v: getattr(v.st, f"{p}_f")},
        [("fires once", chk)],
        fired=lambda t: None if t.end(f"{p}_f") else "never fired")


def collide_pair(p, gap, speed):
    """@collide(a, b) runs once when they touch; destroying one in it ends contact (Guia #colisao)."""
    def chk(t):
        # Contact once the left circle has travelled the gap. Within one frame
        # of travel of that moment either count is allowed.
        n = t.end(f"{p}_hits")
        travel = speed * t.samples[-1].time
        step = speed * (t.samples[0].time / t.samples[0].frame)
        if travel >= gap + 2 * step and n != 1:
            return f"{n} hits after travelling {travel:.2f} >= gap {gap} (want exactly 1)"
        if travel < gap - 2 * step and n != 0:
            return f"{n} hits after travelling only {travel:.2f} < gap {gap}"
        return None if n in (0, 1) else f"{n} hits"
    return Behaviour(
        "collide_pair",
        f"st.{p}_hits = 0\n"
        f"{p}l = Circle(center=(400 - {gap} / 2 - 8, 500), radius=8, group='{p}_l')\n"
        f"{p}r = Circle(center=(400 + {gap} / 2 + 8, 500), radius=8, group='{p}_r')\n"
        f"@collide('{p}_l', '{p}_r')\n"
        f"def {p}_hit(a, b):\n    st.{p}_hits += 1\n    b.destroy()\n",
        f"    if {p}l.is_alive:\n        {p}l.move_by({speed} * dt, 0)\n",
        {f"{p}_hits": lambda v: getattr(v.st, f"{p}_hits")},
        [("exactly one hit", chk)],
        fired=lambda t: None if t.end(f"{p}_hits") else "never hit")


def text_formula(p):
    """t["text"] @= lambda: f"...{st.x}": the text follows the cell (Guia #reativo)."""
    return Behaviour(
        "text_formula",
        f"st.{p} = 0\n"
        f"{p} = Text('', top_left=(10, 580), font_size=12)\n"
        f"{p}['text'] @= lambda: f'n={{st.{p}}}'\n",
        f"    st.{p} += 1\n",
        {f"{p}_t": lambda v: getattr(v, p).text, f"{p}_n": lambda v: getattr(v.st, p)},
        [("text = n=<cell>", lambda t: next(
            (f"frame {s.frame}: {s.values[f'{p}_t']!r} vs n={s.values[f'{p}_n']}"
             for s in t.samples if s.values[f"{p}_t"] != f"n={int(s.values[f'{p}_n'])}"), None))])


def group_mover(p, k, v):
    """group[g].move_by moves every member (Guia #mundo-grupos)."""
    xs = [500 + 20 * i for i in range(k)]
    return Behaviour(
        "group_mover",
        "".join(f"Circle(center=({x}, 50), radius=3, group='{p}_g')\n" for x in xs),
        f"    group['{p}_g'].move_by({v} * dt, 0)\n",
        {f"{p}_xs": lambda vw: tuple(sorted(c.center.x for c in vw.group[f"{p}_g"]))},
        [("every member moved by v*t", lambda t: _first_fail(
            t, f"{p}_xs", lambda tm, _f: tuple(x + v * tm for x in xs), 1e-6))])


def camera_pan(p, vx):
    """canvas.pan_by moves the view, never the world (Guia #mundo-camera)."""
    return Behaviour(
        "camera_pan", "", f"    canvas.pan_by({vx} * dt, 0)\n",
        {f"{p}_pan": lambda v: v.canvas.pan_x},
        [], camera=True)


def key_mover(p, key, frames, speed):
    """keyp(K) is True while K is held: move_by while held (Guia #entrada-teclado)."""
    def chk(t):
        held = sum(1 for f, d in t.inputs if d.startswith("key") and f"'{key}'" in d)
        if held != 2:
            return f"inputs for {key}: {t.inputs}"
        x = t.end(f"{p}_x")
        want = 600 + speed * frames * (t.samples[0].time / t.samples[0].frame)
        return None if abs(x - want) < 1e-6 else f"x {x} vs {want} (held {frames} frames)"
    return Behaviour(
        "key_mover",
        f"{p} = Circle(center=(600, 300), radius=5)\n",
        f"    if keyp('{key}'):\n        {p}.move_by({speed} * dt, 0)\n",
        {f"{p}_x": lambda v: getattr(v, p).center.x},
        [("moved while held", chk)],
        steps=[("key", key, frames)])


KEYS = ("A", "S", "D", "F", "J", "K")
num = lambda lo, hi: hst.integers(lo, hi).map(float)  # noqa: E731


@hst.composite
def behaviour(draw, i: int, used_keys: set):
    p = f"b{i}"
    kind = draw(hst.sampled_from(sorted(_BUILDERS)))
    if kind == "key_mover":
        free = [k for k in KEYS if k not in used_keys]
        if not free:
            kind = "mover"
        else:
            k = draw(hst.sampled_from(free))
            used_keys.add(k)
            return key_mover(p, k, draw(hst.integers(1, 20)), draw(num(-200, 200)))
    return _BUILDERS[kind](draw, p)


_BUILDERS = {
    "mover": lambda d, p: mover(p, d(num(100, 700)), d(num(100, 500)), d(num(-120, 120)), d(num(-120, 120))),
    "spinner": lambda d, p: spinner(p, d(num(-400, 400))),
    "ticker": lambda d, p: ticker(p, d(hst.sampled_from([0.1, 0.25, 0.5, 0.3]))),
    "delayed_destroy": lambda d, p: delayed_destroy(p, d(hst.sampled_from([0.2, 0.5, 1.0]))),
    "tween": lambda d, p: tween(p, d(num(100, 300)), d(num(400, 700)), d(hst.sampled_from([0.3, 0.75, 1.5]))),
    "follower": lambda d, p: follower(p, d(num(-50, 50))),
    "when_once": lambda d, p: when_once(p, d(hst.integers(1, 40))),
    "collide_pair": lambda d, p: collide_pair(p, d(num(10, 120)), d(num(60, 400))),
    "text_formula": lambda d, p: text_formula(p),
    "group_mover": lambda d, p: group_mover(p, d(hst.integers(1, 5)), d(num(-80, 80))),
    "camera_pan": lambda d, p: camera_pan(p, d(num(-100, 100))),
    "key_mover": None,      # drawn with a free key in behaviour()
}


@hst.composite
def program(draw):
    n = draw(hst.integers(2, 6))
    used: set = set()
    out, camera = [], False
    for i in range(n):
        b = draw(behaviour(i, used))
        if b.camera and camera:
            continue
        camera |= b.camera
        out.append(b)
    dt = draw(hst.sampled_from([1 / 60, 1 / 30, 1 / 144]))
    frames = draw(hst.integers(30, 150))
    return out, dt, frames


def render(behaviours: Sequence[Behaviour]) -> str:
    body = "".join(b.update for b in behaviours) or "    pass\n"
    return ("from scena import *\n"
            "init(width=800, height=600)\n"
            + "".join(b.setup for b in behaviours)
            + "def update(dt):\n" + body
            + "run()\n")


def run_composed(behaviours: Sequence[Behaviour], dt: float, frames: int):
    src = render(behaviours)
    probes = {}
    for b in behaviours:
        probes.update(b.probes)
    steps = [s for b in behaviours for s in b.steps]
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "composed.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(src)
        with ProgramRun(path, probes=probes, dt=dt) as run:
            run.play(steps + [("wait", frames)])
            trace = run.trace
        leftovers = run.leftovers()
    failures = []
    for b in behaviours:
        for label, check in b.checks:
            msg = check(trace)
            if msg:
                failures.append(f"{b.name}: {label}: {msg}")
    errs = trace.errors()
    if errs:
        failures.append(f"probe errors: {errs[:3]}")
    if leftovers:
        failures.append(f"teardown leftovers: {leftovers}")
    return src, trace, failures


class TestComposedPrograms(unittest.TestCase):
    """Behaviours keep their guarantees when composed (any 2-6, any dt)."""

    @settings(max_examples=max(10, settings().max_examples // 2))
    @given(prog=program())
    def test_behaviours_do_not_interfere(self, prog):
        behaviours, dt, frames = prog
        src, _trace, failures = run_composed(behaviours, dt, frames)
        note(src)
        self.assertFalse(failures, f"dt={dt} frames={frames}\n{src}\n" + "\n".join(failures))


class TestBehavioursAlone(unittest.TestCase):
    """Vacuity: each behaviour, alone, acts (moves, ticks, fires) and passes."""

    CASES = [
        mover("b0", 200.0, 200.0, 50.0, -20.0), spinner("b0", 90.0), ticker("b0", 0.25),
        delayed_destroy("b0", 0.5), tween("b0", 100.0, 500.0, 0.75), follower("b0", 12.0),
        when_once("b0", 10), collide_pair("b0", 40.0, 200.0), text_formula("b0"),
        group_mover("b0", 3, 40.0), camera_pan("b0", 30.0), key_mover("b0", "A", 10, 120.0),
    ]

    def test_every_builder_has_a_case(self):
        self.assertEqual(sorted({b.name for b in self.CASES}), sorted(_BUILDERS))

    def test_each_alone(self):
        for b in self.CASES:
            with self.subTest(b.name):
                _src, trace, failures = run_composed([b], 1 / 60, 90)
                self.assertFalse(failures, "\n".join(failures))
                if b.fired is not None:
                    self.assertIsNone(b.fired(trace), f"{b.name} did nothing (vacuous)")


if __name__ == "__main__":
    unittest.main()
