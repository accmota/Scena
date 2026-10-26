"""Equations: pairs of programs an author believes equivalent.

An equation runs a program and a transformed twin and compares their traces
through a projection: per frame, a multiset of normalized events (the order
inside a phase is never compared — loop order is the engine's business, not
a law's). No expected value is needed, only agreement: the answer to the
oracle problem (Testing Design, "Laws and equations").

Transforms rewrite the program text and return a line map (new line → old
line) so the twin's labels and function ids name the original lines.

* ``spawn_swaps`` (E3): two adjacent top-level statements that make objects
  and do not read each other swap places. Statements that draw random
  numbers are left alone: their order changes the draws, not the engine.
* ``add_neutral_rule`` (E15): a no-op ``@collide_stay(a, b)`` between two
  tags the program's top-level rules already name (so enrollment, queries
  and ``collidable`` do not change). Every other rule's calls must agree: a
  rule's enters, stays and exits do not depend on another rule pairing the
  same bodies (V15; CD3).
"""
from __future__ import annotations

import ast
import functools
import math
import re
from collections import Counter
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

LineMap = Dict[int, int]

import os as _os  # noqa: E402
ROOT_TESTS = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))

# Pulls whose count depends on who read what when (caches, probes): not a law.
UNCOMPARED_DOORS = frozenset({"formula", "condition"})

# Calls that draw from the author's global ``random`` stream: two of them
# swapped trade their numbers (the program is no less random, nor less
# reproducible). ``Endless`` without ``seed=`` draws its seed at construction
# (endless.py ``_check_seed``; E3 found it, ACADEMIC).
_RANDOM_NAMES = frozenset({"random", "uniform", "randint", "randrange", "choice", "choices",
                           "shuffle", "sample", "gauss", "chance", "random_point",
                           "random_color", "vec_random", "jitter", "Endless"})
_LABEL = re.compile(r"^(?P<kind>[^@]+)@(?P<file>[^:]+):(?P<line>\d+)(?P<rest>.*)$")
_FN = re.compile(r"^(?P<file>[^:]+):(?P<line>\d+):(?P<qual>.*)$")


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

def _map_label(label, line_map: Optional[LineMap], file: Optional[str]):
    if not isinstance(label, str) or not line_map:
        return label
    m = _LABEL.match(label)
    if not m or (file and m.group("file") != file):
        return label
    line = line_map.get(int(m.group("line")), int(m.group("line")))
    return f"{m.group('kind')}@{m.group('file')}:{line}{m.group('rest')}"


def _map_fn(fn, line_map: Optional[LineMap], file: Optional[str], lines: bool):
    m = _FN.match(fn) if isinstance(fn, str) else None
    if not m:
        return fn
    if not lines:
        return f"{m.group('file')}:{m.group('qual')}"
    line = int(m.group("line"))
    if line_map and (not file or m.group("file") == file):
        line = line_map.get(line, line)
    return f"{m.group('file')}:{line}:{m.group('qual')}"


def project(events: Sequence[tuple], *, line_map: Optional[LineMap] = None,
            file: Optional[str] = None, fn_lines: bool = True,
            doors: Optional[Callable[[str], bool]] = None) -> Dict[int, Counter]:
    """frame -> Counter of normalized discrete events."""
    lab = lambda x: _map_label(x, line_map, file)      # noqa: E731
    out: Dict[int, Counter] = {}
    frame = 0
    cur = out.setdefault(0, Counter())
    for e in events:
        k = e[0]
        if k == "F":
            frame = e[1]
            cur = out.setdefault(frame, Counter())
        elif k == "X":
            door = e[1].split(">", 1)[0]
            if door in UNCOMPARED_DOORS or (doors is not None and not doors(door)):
                continue
            cur[("X", e[1], e[2], _map_fn(e[3], line_map, file, fn_lines),
                 tuple(lab(a) for a in e[4]))] += 1
        elif k == "N":
            cur[("N", e[2], lab(e[1]).rsplit("#", 1)[0] if isinstance(e[1], str) else e[1])] += 1
        elif k in ("Q", "K", "R"):
            cur[(k, lab(e[1]))] += 1
        elif k == "C":
            for name, pairs in zip(("enter", "stay", "exit"), e[1:4]):
                for p in pairs:
                    cur[("C", name, tuple(sorted(lab(x) for x in p)))] += 1
        elif k in ("A", "B"):
            cur[(k, e[1])] += 1
    return out


def compare(a: Dict[int, Counter], b: Dict[int, Counter], *, limit: int = 4,
            frames: Optional[Iterable[int]] = None) -> List[str]:
    """Frames whose multisets differ, first ``limit`` of them, with the diff."""
    out = []
    keys = sorted(set(a) | set(b)) if frames is None else sorted(frames)
    for f in keys:
        ca, cb = a.get(f, Counter()), b.get(f, Counter())
        if ca == cb:
            continue
        only_a = list((ca - cb).elements())[:3]
        only_b = list((cb - ca).elements())[:3]
        out.append(f"frame {f}: only in the program {only_a}; only in the twin {only_b}")
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# E1, pacing: edge events in game time
# ---------------------------------------------------------------------------

# Doors that fire once per event (an enter, a timer, a destroy), not once per
# frame: those can be matched across frame rates. Per-frame doors (update,
# on_update, stay, pulls, pre-draw ticks) run as often as there are frames.
EDGE_DOORS = frozenset({"enter", "exit", "after", "every", "on_destroy", "setup", "hover",
                        "hover_exit", "leave", "act-build", "act-teardown", "history"})


def _strip(label):
    """``Kind@file:line#n`` -> ``Kind@file:line`` (ordinals can differ by pacing)."""
    return label.rsplit("#", 1)[0] if isinstance(label, str) else label


def timed_edges(events: Sequence[tuple]) -> Tuple[Dict[tuple, List[float]], float]:
    """key -> sorted game times of its edge events; and the run's end time."""
    out: Dict[tuple, List[float]] = {}
    t = 0.0
    for e in events:
        k = e[0]
        if k == "F":
            t += float(e[2] or 0.0)
            continue
        key = None
        if k == "X":
            door = e[1].split(">", 1)[0]
            if door in EDGE_DOORS:
                key = ("X", e[1], e[3], tuple(_strip(a) for a in e[4]))
        elif k == "N":
            key = ("N", e[2], _strip(e[1]))
        elif k == "Q":
            key = ("Q", _strip(e[1]))
        elif k in ("A", "B"):
            key = (k, e[1])
        if key is not None:
            out.setdefault(key, []).append(t)
    return out, t


def compare_paced(a, b, tol: float, *, limit: int = 6) -> List[str]:
    """Edge events of two pacings agree: the same events, each within ``tol``
    seconds. Events within ``tol`` of the end of either run are not compared
    (one pacing may stop a frame before the other's)."""
    (ea, ta), (eb, tb) = a, b
    edge = min(ta, tb) - 2 * tol          # an event past here may fall on either side
    out = []
    for key in sorted(set(ea) | set(eb), key=repr):
        xa, xb = ea.get(key, []), eb.get(key, [])
        i = j = 0
        lost_a, lost_b = [], []
        while i < len(xa) and j < len(xb):      # two sorted lists, paired within tol
            if abs(xa[i] - xb[j]) <= tol:
                i += 1
                j += 1
            elif xa[i] < xb[j]:
                lost_a.append(xa[i])
                i += 1
            else:
                lost_b.append(xb[j])
                j += 1
        lost_a += xa[i:]
        lost_b += xb[j:]
        lost_a = [x for x in lost_a if x <= edge]
        lost_b = [x for x in lost_b if x <= edge]
        if lost_a or lost_b:
            out.append(f"{key!r:.140}: unpaired within {tol:.4f} s — only in the first "
                       f"{[round(x, 4) for x in lost_a[:3]]}, only in the second "
                       f"{[round(x, 4) for x in lost_b[:3]]}")
        if len(out) >= limit:
            break
    return out


PACES = {"30": 1 / 30, "144": 1 / 144, "uneven": 0.028}


def e1_script(path: str, frames: int, paces: Sequence[str] = ("30", "144", "uneven")
              ) -> List[str]:
    """E1 on a script: each pace's edge events match the 60 Hz run's."""
    runs, judge = e1_script_runs(path, frames, paces=paces)
    return judge([run() for run in runs])


def e1_script_runs(path: str, frames: int, *, limit: Optional[int] = None,
                   paces: Sequence[str] = ("30", "144", "uneven")):
    """``e1_script`` as independent runs: ``(runs, judge)``, the 60 Hz run
    then one per pace (``limit`` is unused: every pace, as ``e3_script_runs``'s
    signature)."""
    import os

    def base():
        return timed_edges(script_trace(path, frames))

    def paced(pace):
        return timed_edges(script_trace(path, frames, pace=pace))

    def judge(results):
        out = []
        for pace, twin in zip(paces, results[1:]):
            diff = compare_paced(results[0], twin, 1 / 60 + PACES[pace] + 1e-6)
            if diff:
                out.append(f"E1 {os.path.basename(path)} at {pace}: " + "; ".join(diff))
        return out

    return [base] + [functools.partial(paced, pace) for pace in paces], judge


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

def program_trace(program: str, spec_ns: Dict, scenario: str, *, source: Optional[str] = None,
                  params: Optional[Dict] = None, prelude=None, dt: Optional[float] = None,
                  stretch: int = 1) -> List[tuple]:
    """The laws trace of one program scenario (``source``: a rewritten twin,
    run from a file with the program's own name, Tier C)."""
    from laws.attach import attach
    from program_support import ProgramRun
    sc = spec_ns["SCENARIOS"][scenario]
    p = dict(sc.params)
    if params:
        p.update(params)
    run = ProgramRun(program, p, probes={}, seed=sc.seed, dt=sc.dt if dt is None else dt,
                     source=source)
    run.prelude = prelude
    attach(run)
    run.start()
    ok = False
    try:
        run.stretch = stretch
        run.play(sc.steps)
        ok = True
    finally:
        run.close(strict=ok)
    if run.laws.errors:
        raise AssertionError(f"recorder errors: {run.laws.errors[:3]}")
    return run.laws.events


def e3_program(program: str, spec_ns: Dict, scenario: str, *, limit: Optional[int] = None
               ) -> List[str]:
    """E3, spawn order: each swap candidate's twin traces like the program."""
    import os
    from program_support import program_path
    path = program_path(program)
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    file = os.path.basename(path)
    base = project(program_trace(program, spec_ns, scenario), file=file)
    out = []
    for i, _j in swap_candidates(source)[:limit]:
        twin_src, line_map = swap_statements(source, i)
        twin = project(program_trace(program, spec_ns, scenario, source=twin_src),
                       line_map=line_map, file=file)
        diff = compare(base, twin)
        if diff:
            line = ast.parse(source).body[i].lineno
            out.append(f"E3 {program}/{scenario} swap at line {line}: " + "; ".join(diff))
    return out


def script_trace(path: str, frames: int, *, source: Optional[str] = None,
                 pace: Optional[str] = None) -> List[tuple]:
    """The laws trace of a headless script run; ``source``: a twin, saved under
    the script's own name in a temporary folder and run from the script's
    folder (its media, its harness cwd)."""
    import os
    import tempfile
    from laws.families import load_trace
    from laws.neutrality import ROOT, run_script
    import script_harness
    with tempfile.TemporaryDirectory(prefix="laws_eq_") as tmp:
        out = os.path.join(tmp, "trace.jsonl")
        if source is None:
            run_script(path, frames, laws_out=out, pace=pace)
        else:
            # The twin's folder mirrors the original's (a link per entry):
            # "next to the script" must find the same images, sounds and
            # level files, or the twin plays with placeholders (E3 first
            # blamed the engine for a twin that had lost its art).
            folder = os.path.join(tmp, "twin")
            os.mkdir(folder)
            from source_support import iter_entries, link_entry
            here = os.path.dirname(path)
            for name in iter_entries(here):
                if name != os.path.basename(path):
                    link_entry(os.path.join(here, name), os.path.join(folder, name))
            twin = os.path.join(folder, os.path.basename(path))
            with open(twin, "w", encoding="utf-8") as fh:
                fh.write(source)
            cwd = script_harness.harness_cwd(path, ROOT)
            run_script(twin, frames, laws_out=out, cwd=cwd, pace=pace)
        events = load_trace(out)
    meta = events.pop() if events and events[-1][0] == "meta" else None
    if meta is not None and meta[2]:
        raise AssertionError(f"recorder errors: {meta[2][:3]}")
    return events


def e3_script(path: str, frames: int, *, limit: Optional[int] = None) -> List[str]:
    """E3 on an example or a tutorial step."""
    runs, judge = e3_script_runs(path, frames, limit=limit)
    return judge([run() for run in runs])


def e3_script_runs(path: str, frames: int, *, limit: Optional[int] = None):
    """``e3_script`` as independent runs a pool can spread: ``(runs, judge)``,
    the base run then one per swap; ``judge(results)`` gives the messages.
    Run one after another, an example with many candidates (ninja_5_espada:
    36 E15 twins) held one pool slot past a gate job's 30 min (WP31)."""
    import os
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    file = os.path.basename(path)
    cands = swap_candidates(source)[:limit]
    if not cands:
        return [], lambda results: []

    def base():
        return project(script_trace(path, frames), file=file)

    def twin(i):
        twin_src, line_map = swap_statements(source, i)
        return project(script_trace(path, frames, source=twin_src), line_map=line_map, file=file)

    def judge(results):
        out = []
        for (i, _j), got in zip(cands, results[1:]):
            diff = compare(results[0], got)
            if diff:
                line = ast.parse(source).body[i].lineno
                out.append(f"E3 {file} swap at line {line}: " + "; ".join(diff))
        return out

    return [base] + [functools.partial(twin, i) for i, _j in cands], judge


# ---------------------------------------------------------------------------
# Transforms
# ---------------------------------------------------------------------------

def _names_read(node) -> set:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


# A call of one of these on a name fills or empties the container it names
# (``bobs.append(bob)``): the name is written (LW12).
_MUTATORS = frozenset({"append", "extend", "insert", "add", "update", "setdefault",
                       "remove", "discard", "clear"})


def _names_written(node) -> set:
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif (isinstance(n, ast.Subscript) and isinstance(n.ctx, (ast.Store, ast.Del))
              and isinstance(n.value, ast.Name)):
            out.add(n.value.id)
        elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr in _MUTATORS and isinstance(n.func.value, ast.Name)):
            out.add(n.func.value.id)
    return out


def _calls(node) -> set:
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            out.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", ""))
    return out


def _makes_objects(stmt) -> bool:
    """A top-level statement that constructs something (a call whose name is
    capitalized: ``Circle(...)``, ``ship = Ship(...)``, a loop of them)."""
    if not isinstance(stmt, (ast.Expr, ast.Assign, ast.AnnAssign, ast.For)):
        return False
    return any(name[:1].isupper() for name in _calls(stmt))


def bound_to_closure(source: str) -> Tuple[str, int]:
    """E6: every ``after`` / ``every`` whose callback is a bound method of
    ``self`` (``after(0.9, self.atirar)``) gets a closure over ``self`` instead
    (``lambda: self.atirar()``), in place (lines unchanged). Returns the new
    source and how many calls changed."""
    tree = ast.parse(source)
    spots = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        if name not in ("after", "every"):
            continue
        cb = node.args[-1]
        if (isinstance(cb, ast.Attribute) and isinstance(cb.value, ast.Name)
                and cb.value.id == "self" and cb.lineno == cb.end_lineno):
            spots.append(cb)
    lines = source.splitlines(keepends=True)
    for cb in sorted(spots, key=lambda n: (n.lineno, n.col_offset), reverse=True):
        line = lines[cb.lineno - 1]
        lines[cb.lineno - 1] = (line[:cb.col_offset] + f"lambda: self.{cb.attr}()"
                                + line[cb.end_col_offset:])
    return "".join(lines), len(spots)


def e6_projection(events) -> Dict[int, Counter]:
    """Timer fires and cancels per handle, plus every door except the timer
    callbacks themselves (a bound method vs a lambda: other functions)."""
    out = project(events, doors=lambda d: d not in ("after", "every"))
    frame = 0
    for e in events:
        if e[0] == "F":
            frame = e[1]
        elif e[0] == "H" and e[1] in ("fire", "cancel"):
            out.setdefault(frame, Counter())[("H", e[1], e[2])] += 1
    return out


def e6_script(path: str, frames: int) -> List[str]:
    runs, judge = e6_script_runs(path, frames)
    return judge([run() for run in runs])


def e6_script_runs(path: str, frames: int, *, limit: Optional[int] = None):
    """``e6_script`` as independent runs: ``(runs, judge)``, the script then
    its closure twin; none when no callback is a bound method."""
    import os
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    twin_src, n = bound_to_closure(source)
    if not n:
        return [], lambda results: []

    def judge(results):
        diff = compare(results[0], results[1])
        return [f"E6 {os.path.basename(path)} ({n} callbacks): " + "; ".join(diff)] if diff else []

    return [lambda: e6_projection(script_trace(path, frames)),
            lambda: e6_projection(script_trace(path, frames, source=twin_src))], judge


def e6_program(program: str, spec_ns: Dict, scenario: str) -> List[str]:
    from program_support import program_path
    with open(program_path(program), encoding="utf-8") as fh:
        source = fh.read()
    twin_src, n = bound_to_closure(source)
    if not n:
        return []
    base = e6_projection(program_trace(program, spec_ns, scenario))
    twin = e6_projection(program_trace(program, spec_ns, scenario, source=twin_src))
    diff = compare(base, twin)
    return [f"E6 {program}/{scenario} ({n} callbacks): " + "; ".join(diff)] if diff else []


# ---------------------------------------------------------------------------
# E10–E14: motion invariances (S6), on tests/laws/twins/motion_world.py
# ---------------------------------------------------------------------------

MOTION = "tests/laws/twins/motion_world"
MOTION_SCENES = ("ramp", "stack", "headon", "lift", "box")
POS_BUDGET = 0.5          # DU per sample (design/Laws.md, budgets)


def motion_trajectory(scene: str, params: Optional[Dict] = None, *, dt: float = 1 / 60,
                      seconds: float = 4.0) -> Dict[float, List[Tuple[float, float]]]:
    """game time -> the moving bodies' centers, mapped back to the
    untransformed world (``home``)."""
    from program_support import ProgramRun
    p = dict(params or {}, scene=scene)
    probes = {"pos": lambda v: [tuple(v.home(b.center.x, b.center.y)) for b in v.BODIES]}
    run = ProgramRun(MOTION, p, probes=probes, dt=dt)
    run.start()
    try:
        run.step(int(round(seconds / dt)))
    finally:
        run.close()
    return {round(s.time, 6): s.values["pos"] for s in run.trace.samples}


def compare_trajectories(a, b, budget: float) -> Tuple[float, str]:
    """Largest distance between the two runs at the times both sampled."""
    worst, where = 0.0, ""
    for t in sorted(set(a) & set(b)):
        for i, (pa, pb) in enumerate(zip(a[t], b[t])):
            d = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
            if d > worst:
                worst, where = d, f"body {i} at t={t:.3f}: {pa} vs {pb}"
    return worst, where


def motion_equation(scene: str, twin_params: Dict, *, budget: float = POS_BUDGET,
                    dt: float = 1 / 60, base_dt: float = 1 / 60) -> List[str]:
    """E10–E12, E14: the twin's trajectory within ``budget`` of the base."""
    base = motion_trajectory(scene, dt=base_dt)
    twin = motion_trajectory(scene, twin_params, dt=dt)
    worst, where = compare_trajectories(base, twin, budget)
    if worst > budget:
        return [f"{scene} {twin_params or ''} dt={dt:.4f}: {worst:.3f} DU apart ({where})"]
    return []


def e13_pacing(scene: str, dt: float, *, c: float = 1.0, base_dt: float = 1 / 60) -> List[str]:
    """E13: at another frame time the bodies stay within ``c`` frames of
    travel of the 60 Hz run (the coarser frame, at the body's speed there),
    plus the position budget. The bound is the claim: an author's Euler step
    and a bounce's dropped leftover (LW7) both stay inside one frame of
    travel over a few seconds; a body that drifts further is a finding."""
    base = motion_trajectory(scene, dt=base_dt)
    twin = motion_trajectory(scene, dt=dt)
    coarse = max(dt, base_dt)
    times = sorted(base)
    out = []
    for prev, t in zip(times, times[1:]):
        if t not in twin:
            continue
        for i, (pa, pb) in enumerate(zip(base[t], twin[t])):
            q = base[prev][i]
            speed = math.hypot(pa[0] - q[0], pa[1] - q[1]) / (t - prev)
            bound = c * speed * coarse + POS_BUDGET
            d = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
            if d > bound:
                out.append(f"{scene} dt={dt:.4f}: body {i} at t={t:.3f} {d:.3f} DU apart "
                           f"(bound {bound:.3f})")
                return out
    return out


# ---------------------------------------------------------------------------
# E16: a world without a floor has no down (V10), on tests/laws/twins/topdown_world.py
# ---------------------------------------------------------------------------

TOPDOWN = "tests/laws/twins/topdown_world"
TOPDOWN_SCENES = ("leave", "lift", "slope", "seam", "bounce")


def topdown_trajectory(scene: str, rot: float, *, floor: bool = False,
                       seconds: float = 1.5) -> Dict[float, List[Tuple[float, float]]]:
    """game time -> the moving bodies' centers, turned back by ``rot``."""
    from program_support import ProgramRun
    probes = {"pos": lambda v: [tuple(v.home(b.center.x, b.center.y)) for b in v.BODIES]}
    run = ProgramRun(TOPDOWN, {"scene": scene, "rot": rot, "floor": floor}, probes=probes)
    run.start()
    try:
        run.step(int(round(seconds * 60)))
    finally:
        run.close()
    return {round(s.time, 6): s.values["pos"] for s in run.trace.samples}


def e16_rotation(scene: str, rot: float, *, floor: bool = False,
                 budget: float = POS_BUDGET) -> List[str]:
    """E16: the world turned by ``rot`` moves as the turn of the world."""
    base = topdown_trajectory(scene, 0.0, floor=floor)
    twin = topdown_trajectory(scene, rot, floor=floor)
    worst, where = compare_trajectories(base, twin, budget)
    if worst > budget:
        return [f"{scene} rot={rot:g} floor={floor}: {worst:.3f} DU apart ({where})"]
    return []


def e5_projection(events) -> Dict[int, Counter]:
    """E5: everything but the act's own machinery (its build, its setup)."""
    out = project(events, doors=lambda d: d not in ("act-build", "setup"))
    for c in out.values():
        for k in [k for k in c if k[0] in ("A", "B") or (k[0] == "N" and k[1] in ("Fase",))]:
            del c[k]
    return out


def swap_candidates(source: str) -> List[Tuple[int, int]]:
    """Indices (i, i + 1) of adjacent top-level statements that can swap."""
    tree = ast.parse(source)
    body = tree.body
    out = []
    for i in range(len(body) - 1):
        s1, s2 = body[i], body[i + 1]
        if not (_makes_objects(s1) and _makes_objects(s2)):
            continue
        calls = _calls(s1) | _calls(s2)
        if calls & _RANDOM_NAMES or {"run", "init"} & calls:
            continue
        w1, w2 = _names_written(s1), _names_written(s2)
        if w1 & _names_read(s2) or w2 & _names_read(s1) or w1 & w2:
            continue
        out.append((i, i + 1))
    return out


def swap_statements(source: str, i: int) -> Tuple[str, LineMap]:
    """Swap top-level statements ``i`` and ``i + 1`` as text (comments and the
    lines between them stay put). Returns the source and new line → old line."""
    tree = ast.parse(source)
    s1, s2 = tree.body[i], tree.body[i + 1]
    lines = source.splitlines(keepends=True)
    a0, a1 = s1.lineno, s1.end_lineno          # 1-based, inclusive
    b0, b1 = s2.lineno, s2.end_lineno
    block1 = lines[a0 - 1:a1]
    middle = lines[a1:b0 - 1]
    block2 = lines[b0 - 1:b1]
    new = lines[:a0 - 1] + block2 + middle + block1 + lines[b1:]
    line_map: LineMap = {}
    n = a0
    for old in list(range(b0, b1 + 1)) + list(range(a1 + 1, b0)) + list(range(a0, a1 + 1)):
        line_map[n] = old
        n += 1
    return "".join(new), line_map


# ---------------------------------------------------------------------------
# E15: a rule's calls do not depend on other rules (V15, CD3)
# ---------------------------------------------------------------------------

NEUTRAL = "_e15_neutral"
_RULE_DECORATORS = frozenset({"collide", "collide_stay", "collide_exit"})


def _top_level_rules(source: str):
    """String tags named by the top-level rules (``@collide*`` decorators,
    ``resolve(...)`` statements) in order, and the tag pairs they declare."""
    tree = ast.parse(source)
    tags: List[str] = []
    pairs = set()
    for node in tree.body:
        calls = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            calls = [d for d in node.decorator_list
                     if isinstance(d, ast.Call) and isinstance(d.func, ast.Name)
                     and d.func.id in _RULE_DECORATORS]
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) \
                and isinstance(node.value.func, ast.Name) and node.value.func.id == "resolve":
            calls = [node.value]
        for c in calls:
            strs = [a.value for a in c.args[:2]
                    if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            for t in strs:
                if t not in tags:
                    tags.append(t)
            if len(strs) == 2:
                pairs.add(frozenset(strs))
    return tags, pairs


def neutral_candidates(source: str) -> List[Tuple[str, str]]:
    """Tag pairs for a neutral rule: two tags the top-level rules name, a
    pair no rule declares first (it adds contacts: the CD3 shape), then the
    declared pairs. Empty when the program does not ``from scena import *``."""
    if "from scena import *" not in source:
        return []
    tags, pairs = _top_level_rules(source)
    fresh = [(a, b) for i, a in enumerate(tags) for b in tags[i + 1:]
             if frozenset((a, b)) not in pairs]
    known = sorted(tuple(sorted(p)) for p in pairs if len(p) == 2)
    return fresh + [p for p in known if p not in fresh]


def add_neutral_rule(source: str, a: str, b: str) -> Tuple[str, LineMap]:
    """The program with ``@collide_stay(a, b)`` doing nothing, as a game rule
    before its top-level ``run()`` (else at the end). Returns the source and
    new line → old line."""
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    at = len(lines)
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) \
                and isinstance(node.value.func, ast.Name) and node.value.func.id == "run":
            at = node.lineno - 1
            break
    block = [f"@collide_stay({a!r}, {b!r})\n", f"def {NEUTRAL}(a, b, info):\n",
             "    pass\n", "\n"]
    new = lines[:at] + block + lines[at:]
    line_map: LineMap = {}
    for old in range(at + 1, len(lines) + 1):
        line_map[old + len(block)] = old
    return "".join(new), line_map


def e15_projection(events, *, line_map: Optional[LineMap] = None,
                   file: Optional[str] = None) -> Dict[int, Counter]:
    """Every author call and lifetime event but the neutral rule's own calls;
    no contact commits (a rule that pairs new bodies adds contacts: per pair,
    not per rule)."""
    out = project(events, line_map=line_map, file=file)
    for c in out.values():
        for k in [k for k in c if k[0] == "C" or (k[0] == "X" and NEUTRAL in str(k[3]))]:
            del c[k]
    return out


def program_path_of(program: str) -> str:
    from program_support import program_path
    return program_path(program)


def e15_program(program: str, spec_ns: Dict, scenario: str, *, limit: Optional[int] = None
                ) -> List[str]:
    """E15 on a program: each neutral rule's twin calls every other rule alike."""
    import os
    from program_support import program_path
    path = program_path(program)
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    cands = neutral_candidates(source)[:limit]
    if not cands:
        return []
    file = os.path.basename(path)
    base = e15_projection(program_trace(program, spec_ns, scenario), file=file)
    out = []
    for a, b in cands:
        twin_src, line_map = add_neutral_rule(source, a, b)
        twin = e15_projection(program_trace(program, spec_ns, scenario, source=twin_src),
                              line_map=line_map, file=file)
        diff = compare(base, twin)
        if diff:
            out.append(f"E15 {program}/{scenario} neutral {a!r} x {b!r}: " + "; ".join(diff))
    return out


def e15_script(path: str, frames: int, *, limit: Optional[int] = None) -> List[str]:
    """E15 on an example or a tutorial step."""
    runs, judge = e15_script_runs(path, frames, limit=limit)
    return judge([run() for run in runs])


def e15_script_runs(path: str, frames: int, *, limit: Optional[int] = None):
    """``e15_script`` as independent runs: ``(runs, judge)``, as
    ``e3_script_runs`` (WP31)."""
    import os
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    cands = neutral_candidates(source)[:limit]
    if not cands:
        return [], lambda results: []
    file = os.path.basename(path)

    def base():
        return e15_projection(script_trace(path, frames), file=file)

    def twin(a, b):
        twin_src, line_map = add_neutral_rule(source, a, b)
        return e15_projection(script_trace(path, frames, source=twin_src),
                              line_map=line_map, file=file)

    def judge(results):
        out = []
        for (a, b), got in zip(cands, results[1:]):
            diff = compare(results[0], got)
            if diff:
                out.append(f"E15 {file} neutral {a!r} x {b!r}: " + "; ".join(diff))
        return out

    return [base] + [functools.partial(twin, a, b) for a, b in cands], judge
