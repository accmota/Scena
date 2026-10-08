"""Model-free (L3) oracles over whole programs: what must NOT change.

Not a test module. Each oracle runs a program scenario two ways and returns a
list of messages (empty = agree). Used by ``tests/test_prog_*.py``; strategy in
design/Testing Design.md, "Program model tests".

* ``replay``          — the same seed and input give the same trace, sample by sample.
* ``probe_neutral``   — reading the probes every frame does not change the world
                        (the world fingerprint at the end matches a run with no probes).
* ``dt_split``        — half the dt, twice the frames: named continuous probes agree
                        at the same times (within a tolerance).
* ``reactive_config`` — lazy registration + GC backstop (the fast configuration)
                        vs eager + strong references: same trace.
* ``cull_pixels``     — the final frame drawn with ``cull_offscreen`` on vs off is
                        pixel-identical (shared-filter batching off for both).
* ``teardown``        — after ``close()`` the census is back to baseline and no
                        registry references a dead object.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import skia

from program_support import (FRAME, ProgramRun, Scenario, Trace, _plain, close as approx,
                             registry)
from system_support import full_collect, zombies

from scena import canvas
from scena.entity import made_at


def world_fingerprint(run: ProgramRun) -> List[Tuple]:
    """Every live, unowned object the program registered: kind, origin, pose.

    Reads only public pose fields, the same reads in both runs it is compared
    across, so it cannot itself explain a difference.
    """
    # Collect first: an object waiting for GC is not part of the world, and
    # GC timing differs between the runs compared (PM7 hid behind it).
    full_collect()
    out = []
    for k, obj in list(registry().live.items()):
        if k in run._roster_before or getattr(obj, "_owner", None) is not None:
            continue
        row = [type(obj).__name__, made_at(obj) or "", bool(getattr(obj, "is_alive", True))]
        for attr in ("center", "angle", "width", "height", "radius"):
            try:
                row.append(_plain(getattr(obj, attr)))
            except Exception as e:     # a read that raises is part of the print
                row.append(f"<{type(e).__name__}>")
        out.append(tuple(row))
    return out


def _run(program: str, spec_ns: Dict[str, Any], scenario: str, *, probes=None,
         dt: Optional[float] = None, stretch: int = 1, draw: bool = False,
         before_start=None, at_end=None) -> Tuple[Trace, Any]:
    sc: Scenario = spec_ns["SCENARIOS"][scenario]
    run = ProgramRun(program, dict(sc.params),
                     probes=spec_ns["PROBES"] if probes is None else probes,
                     seed=sc.seed, dt=(sc.dt if dt is None else dt), draw=draw)
    if before_start is not None:
        before_start(run)
    run.start()
    ok = False
    try:
        run.stretch = stretch
        run.trace.scenario = scenario
        run.play(sc.steps)
        extra = at_end(run) if at_end is not None else None
        ok = True
    finally:
        run.close(strict=ok)
    run.trace.extra = extra
    run.trace.leftovers = run.leftovers()
    return run.trace, extra


def _diff_samples(a: Trace, b: Trace, tol: float = 0.0) -> List[str]:
    out = []
    if len(a.samples) != len(b.samples):
        out.append(f"sample count {len(a.samples)} vs {len(b.samples)}")
    for sa, sb in zip(a.samples, b.samples):
        for k in sa.values:
            va, vb = sa.values[k], sb.values.get(k)
            same = (va == vb) if tol == 0.0 else approx(va, vb, tol)
            if not same:
                out.append(f"frame {sa.frame} {k}: {va!r:.120} vs {vb!r:.120}")
                if len(out) > 5:
                    return out
    return out


def replay(program: str, spec_ns, scenario: str) -> List[str]:
    a, _ = _run(program, spec_ns, scenario)
    b, _ = _run(program, spec_ns, scenario)
    return [f"replay: {m}" for m in _diff_samples(a, b)]


def probe_neutral(program: str, spec_ns, scenario: str) -> List[str]:
    _a, fa = _run(program, spec_ns, scenario, at_end=world_fingerprint)
    _b, fb = _run(program, spec_ns, scenario, probes={}, at_end=world_fingerprint)
    if fa == fb:
        return []
    rows = [f"  probed {x}\n  bare   {y}" for x, y in zip(fa, fb) if x != y][:3]
    return [f"probe_neutral: reading the probes changed the world "
            f"({len(fa)} vs {len(fb)} objects)\n" + "\n".join(rows)]


def dt_split(program: str, spec_ns, scenario: str, tols: Dict[str, float]) -> List[str]:
    """``tols``: probe name -> absolute tolerance, for continuous probes only."""
    sc = spec_ns["SCENARIOS"][scenario]
    probes = {k: spec_ns["PROBES"][k] for k in tols}
    coarse, _ = _run(program, spec_ns, scenario, probes=probes)
    fine, _ = _run(program, spec_ns, scenario, probes=probes, dt=sc.dt / 2, stretch=2)
    by_time = {round(s.time, 9): s for s in fine.samples}
    out = []
    for s in coarse.samples:
        f = by_time.get(round(s.time, 9))
        if f is None:
            continue
        for k, tol in tols.items():
            if not approx(s.values[k], f.values[k], tol):
                out.append(f"dt_split: {k} at t={s.time:.4f}: dt {s.values[k]!r:.100} "
                           f"vs dt/2 {f.values[k]!r:.100} (tol {tol})")
                break
        if len(out) > 3:
            break
    return out


def reactive_config(program: str, spec_ns, scenario: str) -> List[str]:
    from scena.state import (init_scena_system, set_graph_gc_backstop,
                             set_lazy_container_registration)
    fast, _ = _run(program, spec_ns, scenario)
    set_lazy_container_registration(False)
    set_graph_gc_backstop(False)
    init_scena_system()
    try:
        slow, _ = _run(program, spec_ns, scenario)
    finally:
        set_lazy_container_registration(True)
        set_graph_gc_backstop(True)
        init_scena_system()
    return [f"reactive_config: {m}" for m in _diff_samples(fast, slow, tol=1e-9)]


def _screen(run: ProgramRun) -> np.ndarray:
    a = np.asarray(run.world.surface.makeImageSnapshot().toarray(
        colorType=skia.kRGBA_8888_ColorType))
    return a[: int(canvas.height), : int(canvas.width)].copy()


def cull_pixels(program: str, spec_ns, scenario: str) -> List[str]:
    def frames(run: ProgramRun):
        eng = run.world.fw._scena_draw
        saved = canvas.cull_offscreen, eng.batch_shared_filters
        eng.batch_shared_filters = False
        shots = []
        try:
            for cull in (False, True):
                canvas.cull_offscreen = cull
                run.world.step(1, dt=0.0)
                shots.append(_screen(run))
        finally:
            canvas.cull_offscreen, eng.batch_shared_filters = saved
        return shots
    _t, (off, on) = _run(program, spec_ns, scenario, probes={}, draw=True, at_end=frames)
    d = np.abs(off.astype(int) - on.astype(int)).max(axis=-1)
    if (d > 0).any():
        ys, xs = np.nonzero(d)
        return [f"cull_pixels: {int((d > 0).sum())} pixels differ (max {int(d.max())}), "
                f"bbox x {xs.min()}..{xs.max()} y {ys.min()}..{ys.max()}"]
    return []


def teardown(program: str, spec_ns, scenario: str) -> List[str]:
    t, _ = _run(program, spec_ns, scenario)
    out = []
    if t.leftovers:
        out.append(f"teardown: census moved {t.leftovers}")
    z = zombies()
    if z:
        out.append(f"teardown: zombies {[(h, type(o).__name__) for h, o in z[:5]]}")
    return out


# --------------------------------------------------------------------------
# Tier C: the program rewritten in ways that must not change what it does
# --------------------------------------------------------------------------

import ast  # noqa: E402

_GROUP_CALLS = {"collide", "collide_stay", "collide_exit", "resolve", "unresolve",
                "leave_playfield", "tag", "untag", "tagged", "collide_with",
                "collide_with_stay", "collide_with_exit", "until_empty",
                "drop_by", "test_collision"}


def _group_names(tree: ast.AST) -> set:
    """String literals the program uses as group names."""
    names = set()

    def take(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.add(node.value)
        elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            for e in node.elts:
                take(e)

    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "group":
            take(node.value)
        elif isinstance(node, ast.ClassDef):
            for kw in node.keywords:
                if kw.arg == "group":
                    take(kw.value)
        elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) \
                and node.value.id == "group":
            take(node.slice)
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if name in _GROUP_CALLS:
                for a in node.args:
                    take(a)
    return names


def rename_groups(source: str, suffix: str = "_r") -> str:
    """Every group name gets ``suffix`` everywhere it appears as a whole string."""
    tree = ast.parse(source)
    names = _group_names(tree)

    class R(ast.NodeTransformer):
        def visit_Constant(self, node):
            if isinstance(node.value, str) and node.value in names:
                return ast.copy_location(ast.Constant(node.value + suffix), node)
            return node
    return ast.unparse(R().visit(tree))


def reorder_defs(source: str) -> str:
    """Each run of consecutive undecorated top-level functions, reversed.

    Never moves a def across another statement: default values are evaluated
    at definition time, so crossing an assignment could change the program.
    """
    tree = ast.parse(source)
    out, run = [], []
    for node in tree.body + [None]:
        if isinstance(node, ast.FunctionDef) and not node.decorator_list:
            run.append(node)
            continue
        out.extend(reversed(run))
        run = []
        if node is not None:
            out.append(node)
    tree.body = out
    return ast.unparse(tree)


TIER_C = {"rename_groups": rename_groups, "reorder_defs": reorder_defs}


def tier_c(program: str, spec_ns, scenario: str, transform: str) -> List[str]:
    """The rewritten program leaves the same world (kind, alive, pose; not the
    line an object was made at, which a rewrite may move)."""
    from program_support import program_path
    with open(program_path(program), encoding="utf-8") as fh:
        src = fh.read()
    head = [ln for ln in src.splitlines()[:3] if ln.startswith("# harness:")]
    new_src = "\n".join(head) + "\n" + TIER_C[transform](src)

    def strip(fp):
        return [row[:1] + row[2:] for row in fp]

    _a, fa = _run(program, spec_ns, scenario, probes={}, at_end=world_fingerprint)
    _b, fb = _run(program, spec_ns, scenario, probes={}, at_end=world_fingerprint,
                  before_start=lambda run: setattr(run, "source", new_src))
    fa, fb = strip(fa), strip(fb)
    if fa == fb:
        return []
    rows = [f"  original  {x}\n  rewritten {y}" for x, y in zip(fa, fb) if x != y][:3]
    return [f"tier_c {transform}: the rewritten program left a different world "
            f"({len(fa)} vs {len(fb)} objects)\n" + "\n".join(rows)]
