#!/usr/bin/env python
"""Branch-coverage ledger for the geometry campaign (H9).

Not a test module. Runs a list of test modules under ``coverage.py`` with
``branch=True``, one process per module, measuring the geometry engine
modules only; writes the reached arcs per module to a ledger in
``.scena_test_runs/coverage/`` and compares it with the previous ledger of the
same name. The reached set only grows: an arc reached before and not now is
printed as LOST (a suite stopped reaching it, or the code moved).

    python tests/geom_coverage.py                       # baseline suites
    python tests/geom_coverage.py --suites test_geom_laws test_shapes --tag after
    python tests/geom_coverage.py --report              # unreached branches per function

Needs ``coverage`` (the ``test`` extra). Never runs in a tier: measuring is
slow (several minutes), and a tier answers "does it pass", not "what is
reached" (Testing Design — Geometry campaign).
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Set, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, ".scena_test_runs", "coverage")

ENGINE = ["shapes", "entity", "state", "box", "sprite", "text", "track", "hitbox",
          "geom", "scenamath"]

# The geometry and reactive suites that existed before the campaign (baseline),
# plus the campaign's own modules once they exist (``--suites`` adds more).
BASELINE_SUITES = [
    "test_geometry_contract", "test_reactive_matrix", "test_hyp_reactive_matrix",
    "test_diff_pose", "test_diff_link_write", "test_ctor_links", "test_heading_link",
    "test_write_path_guards", "test_rect_frame", "test_rect_names", "test_flip_mirror",
    "test_angle_field", "test_shapes", "test_box", "test_track", "test_text",
    "test_sprite", "test_hitbox_parts", "test_refusal_atomic", "test_value_validation",
    "test_cache_keys", "test_hot_paths", "test_pose_fast_path", "test_pose_link_contract",
    "test_hyp_api",
]
CAMPAIGN_SUITES = [
    "test_geom_structure", "test_geom_sequences", "test_geom_laws", "test_geom_influence",
    "test_geom_values", "test_geom_sentinel", "test_fuzz_corpus",
]


def _run_one(module: str, data_dir: str) -> Tuple[str, int]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "SCENA_CANARIES": "0",
           "SCENA_HYPOTHESIS_PROFILE": "dev", "SCENA_HYPOTHESIS_DB": "0",
           "COVERAGE_FILE": os.path.join(data_dir, f".coverage.{module}")}
    include = ",".join(os.path.join(ROOT, "scena", m + ".py") for m in ENGINE)
    cmd = [sys.executable, "-m", "coverage", "run", "--branch", f"--include={include}",
           "-m", "unittest", "-q", f"tests.{module}"]
    r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return module, r.returncode


def measure(suites: List[str], jobs: int) -> Dict[str, Set[Tuple[int, int]]]:
    import coverage
    data_dir = tempfile.mkdtemp(prefix="geom_cov_")
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        for module, rc in ex.map(lambda m: _run_one(m, data_dir), suites):
            print(f"  {module:34s} {'ok' if rc == 0 else f'exit {rc}'}", flush=True)
    cov = coverage.Coverage(data_file=os.path.join(data_dir, ".coverage"))
    cov.combine([data_dir], keep=False)
    data = cov.get_data()
    out = {}
    for f in data.measured_files():
        name = os.path.splitext(os.path.basename(f))[0]
        out[name] = set(map(tuple, data.arcs(f) or ()))
    return out


def _functions(path: str) -> List[Tuple[str, int, int]]:
    tree = ast.parse(open(path, encoding="utf-8").read())
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for f in node.body:
                if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append((f"{node.name}.{f.name}", f.lineno, f.end_lineno or f.lineno))
    return out


def report(ledger: Dict[str, Set[Tuple[int, int]]]) -> None:
    """Unreached branch arcs, grouped by function (new cells or dead code)."""
    from coverage.parser import PythonParser
    for name in ENGINE:
        path = os.path.join(ROOT, "scena", name + ".py")
        parser = PythonParser(filename=path)
        parser.parse_source()
        branch_lines = {ln for ln, n in parser.exit_counts().items() if n > 1}
        branch_arcs = {a for a in parser.arcs() if a[0] in branch_lines}
        missed = branch_arcs - ledger.get(name, set())
        by_fn: Dict[str, int] = {}
        for fn, lo, hi in _functions(path):
            n = sum(1 for a in missed if lo <= a[0] <= hi)
            if n:
                by_fn[fn] = n
        print(f"{name}: {len(branch_arcs) - len(missed)}/{len(branch_arcs)} branch arcs reached")
        for fn, n in sorted(by_fn.items(), key=lambda kv: -kv[1])[:25]:
            print(f"    {n:4d}  {fn}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--suites", nargs="*", default=None)
    ap.add_argument("--campaign", action="store_true",
                    help="baseline suites plus the campaign's modules")
    ap.add_argument("--tag", default="baseline")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("-j", "--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    args = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{args.tag}.json")
    previous = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            previous = {k: set(map(tuple, v)) for k, v in json.load(fh)["arcs"].items()}
    if args.report and previous and args.suites is None:
        report(previous)
        return 0
    suites = list(args.suites) if args.suites is not None else list(BASELINE_SUITES)
    if args.campaign:
        suites += [m for m in CAMPAIGN_SUITES
                   if os.path.exists(os.path.join(HERE, m + ".py")) and m not in suites]
    t0 = time.time()
    ledger = measure(suites, args.jobs)
    lost = {k: sorted(previous[k] - ledger.get(k, set())) for k in previous}
    lost = {k: v for k, v in lost.items() if v}
    total = sum(len(v) for v in ledger.values())
    print(f"{total} arcs reached in {time.time() - t0:.0f} s")
    for k in sorted(ledger):
        gained = len(ledger[k] - previous.get(k, set()))
        print(f"  {k:10s} {len(ledger[k]):6d} arcs  (+{gained})")
    for k, v in lost.items():
        print(f"  LOST {k}: {len(v)} arcs, e.g. {v[:5]}")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(dict(suites=suites, stamp=time.strftime("%Y-%m-%d %H:%M"),
                       arcs={k: sorted(v) for k, v in ledger.items()}), fh)
    if args.report:
        report(ledger)
    return 1 if lost else 0


if __name__ == "__main__":
    sys.exit(main())
