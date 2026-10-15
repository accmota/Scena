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
"""
from __future__ import annotations

import ast
import re
from collections import Counter
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

LineMap = Dict[int, int]

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


def script_trace(path: str, frames: int, *, source: Optional[str] = None) -> List[tuple]:
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
            run_script(path, frames, laws_out=out)
        else:
            # The twin's folder mirrors the original's (a link per entry):
            # "next to the script" must find the same images, sounds and
            # level files, or the twin plays with placeholders (E3 first
            # blamed the engine for a twin that had lost its art).
            folder = os.path.join(tmp, "twin")
            os.mkdir(folder)
            from source_support import iter_entries
            here = os.path.dirname(path)
            for name in iter_entries(here):
                if name != os.path.basename(path):
                    os.symlink(os.path.join(here, name), os.path.join(folder, name))
            twin = os.path.join(folder, os.path.basename(path))
            with open(twin, "w", encoding="utf-8") as fh:
                fh.write(source)
            cwd = script_harness.harness_cwd(path, ROOT)
            run_script(twin, frames, laws_out=out, cwd=cwd)
        events = load_trace(out)
    meta = events.pop() if events and events[-1][0] == "meta" else None
    if meta is not None and meta[2]:
        raise AssertionError(f"recorder errors: {meta[2][:3]}")
    return events


def e3_script(path: str, frames: int, *, limit: Optional[int] = None) -> List[str]:
    """E3 on an example or a tutorial step."""
    import os
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    file = os.path.basename(path)
    cands = swap_candidates(source)[:limit]
    if not cands:
        return []
    base = project(script_trace(path, frames), file=file)
    out = []
    for i, _j in cands:
        twin_src, line_map = swap_statements(source, i)
        twin = project(script_trace(path, frames, source=twin_src), line_map=line_map, file=file)
        diff = compare(base, twin)
        if diff:
            line = ast.parse(source).body[i].lineno
            out.append(f"E3 {file} swap at line {line}: " + "; ".join(diff))
    return out


# ---------------------------------------------------------------------------
# Transforms
# ---------------------------------------------------------------------------

def _names_read(node) -> set:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def _names_written(node) -> set:
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
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
