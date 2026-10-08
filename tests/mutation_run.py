#!/usr/bin/env python
"""Sampled mutation run: which mutants does a suite kill that the others miss?

Not a test module. The program model tests' value metric (design/Testing
Design.md, "Program model tests"): mutate engine lines the program suite
executes, then run (A) the program suite and (B) the quick tier without the
program modules. "Killed by A only" is what the program tests add.

    python tests/mutation_run.py --modules scena.collision scena.shapes \
        --programs test_prog_bouncing_balls --n 30
    python tests/mutation_run.py ... --no-baseline     # A only (fast)
    python tests/mutation_run.py ... --ops call        # only deleted calls

``--ops`` keeps the sites of the named operators (``mutation_ops``: cmp, binop,
bool, not, if, const, return, call). ``call`` deletes one expression-statement
call (``self.update()``, ``_invalidate_bare_reads()``): a missing call was the
root cause of most reactive and geometry bugs (D12-D26, G5, G8, R7), so the
geometry campaign measures it on its own.

Each mutant runs in fresh processes with ``SCENA_MUTANT=<module>:<site>``
(``tests/mutant_site/sitecustomize.py`` applies it at import) and
``SCENA_HYPOTHESIS_DB=0`` (a mutant's failures must not enter the example
database). A mutant that cannot even ``import scena`` is "stillborn" and left
out of the counts. Report: ``.scena_test_runs/mutation/<stamp>.json``.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Sequence

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import mutation_ops  # noqa: E402

OUT = os.path.join(ROOT, ".scena_test_runs", "mutation")


def module_path(module: str) -> str:
    return os.path.join(ROOT, *module.split(".")) + ".py"


def _env(mutant: str = "") -> Dict[str, str]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "SCENA_HYPOTHESIS_DB": "0",
           "SCENA_CANARIES": "0",
           "PYTHONPATH": os.pathsep.join(
               [os.path.join(HERE, "mutant_site"), ROOT, os.environ.get("PYTHONPATH", "")])}
    if mutant:
        env["SCENA_MUTANT"] = mutant
    else:
        env.pop("SCENA_MUTANT", None)
    return env


def collect_lines(modules: Sequence[str], programs: Sequence[str]) -> Dict[str, List[int]]:
    """Lines of ``modules`` the program suite executes (one traced child process)."""
    code = f"""
import sys, json, unittest
sys.path.insert(0, {HERE!r}); sys.path.insert(0, {ROOT!r})
files = {{}}
import os
for m in {list(modules)!r}:
    files[os.path.realpath(os.path.join({ROOT!r}, *m.split('.')) + '.py')] = m
hit = {{m: set() for m in files.values()}}
mon = sys.monitoring
TOOL = mon.COVERAGE_ID
mon.use_tool_id(TOOL, "mutation_run")
def on_line(code, line):
    m = files.get(code.co_filename)
    if m is None:
        return mon.DISABLE
    hit[m].add(line)
    return mon.DISABLE
mon.register_callback(TOOL, mon.events.LINE, on_line)
mon.set_events(TOOL, mon.events.LINE)
suite = unittest.defaultTestLoader.loadTestsFromNames({["tests." + p for p in programs]!r})
res = unittest.TextTestRunner(stream=open(os.devnull, "w")).run(suite)
mon.set_events(TOOL, 0)
json.dump({{m: sorted(v) for m, v in hit.items()}}, sys.stdout)
"""
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=_env(),
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    if out.returncode != 0:
        raise SystemExit(f"line collection failed:\n{out.stderr[-3000:]}")
    return json.loads(out.stdout.strip().splitlines()[-1])


def _run(cmd: List[str], mutant: str, timeout: float) -> str:
    try:
        r = subprocess.run(cmd, cwd=ROOT, env=_env(mutant), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return "timeout"
    return "survived" if r.returncode == 0 else "killed"


def stillborn(mutant: str) -> bool:
    return _run([sys.executable, "-c", "import scena"], mutant, 60) != "survived"


def program_cmd(programs: Sequence[str]) -> List[str]:
    return [sys.executable, "-m", "unittest", "-q"] + ["tests." + p for p in programs]


def baseline_cmd(exclude: Sequence[str], jobs: int, out_root: str) -> List[str]:
    code = (
        "import sys; sys.path.insert(0, 'tests'); import run_tiers as rt; "
        "mods = [m for m in rt.tier_modules(rt.TIERS['quick'], rt.discover_modules()) "
        f"if not m.startswith('test_prog_') and m not in {list(exclude)!r}]; "
        f"sys.exit(rt.main(['quick', *mods, '-j', '{jobs}'], out_root={out_root!r}, "
        "stream=open(__import__('os').devnull, 'w')))")
    return [sys.executable, "-c", code]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--modules", nargs="+", required=True)
    ap.add_argument("--programs", nargs="+", required=True)
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("-j", "--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--no-baseline", action="store_true")
    ap.add_argument("--ops", nargs="*", default=[],
                    help="only these operators (default: all)")
    ap.add_argument("--exclude-baseline", nargs="*", default=[],
                    help="quick-tier modules to leave out of B")
    args = ap.parse_args(argv)

    t0 = time.time()
    lines = collect_lines(args.modules, args.programs)
    pool = []
    for m in args.modules:
        with open(module_path(m), encoding="utf-8") as fh:
            src = fh.read()
        hit = set(lines.get(m, ()))
        pool += [(m, s) for s in mutation_ops.sites(src)
                 if s.line in hit and (not args.ops or s.op in args.ops)]
    rng = random.Random(args.seed)
    sample = rng.sample(pool, min(args.n, len(pool)))
    print(f"{len(pool)} sites on executed lines; sampling {len(sample)}", flush=True)

    os.makedirs(OUT, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="mutation_tiers_")
    pcmd = program_cmd(args.programs)

    # Control: both suites must pass with no mutant, or every "kill" is noise
    # (a spec failing on its own while the run is going counts as a kill).
    if _run(pcmd, "", 900) != "survived":
        raise SystemExit("control: the program suite fails without a mutant; fix it first")
    if not args.no_baseline and _run(baseline_cmd(args.exclude_baseline, args.jobs, tmp), "", 1800) != "survived":
        raise SystemExit("control: the baseline fails without a mutant; fix it first")
    print("control: both suites pass unmutated", flush=True)

    def run_a(item):
        m, s = item
        spec = f"{m}:{s.index}"
        if stillborn(spec):
            return spec, "stillborn"
        return spec, _run(pcmd, spec, 300)

    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        a_res = dict(ex.map(run_a, sample))
    rows = []
    for m, s in sample:
        spec = f"{m}:{s.index}"
        a = a_res[spec]
        b = "-"
        if a != "stillborn" and not args.no_baseline:
            b = _run(baseline_cmd(args.exclude_baseline, args.jobs, tmp), spec, 900)
        rows.append(dict(mutant=spec, line=s.line, op=s.op, detail=s.detail,
                         programs=a, baseline=b))
        print(f"{spec:32} L{s.line:<5} {s.op:6} {s.detail:24} A={a:9} B={b}", flush=True)

    live = [r for r in rows if r["programs"] != "stillborn"]
    dead = lambda v: v in ("killed", "timeout")  # noqa: E731
    summary = dict(
        mutants=len(live),
        killed_programs=sum(dead(r["programs"]) for r in live),
        killed_baseline=sum(dead(r["baseline"]) for r in live),
        only_programs=[r["mutant"] for r in live if dead(r["programs"]) and r["baseline"] == "survived"],
        only_baseline=[r["mutant"] for r in live if dead(r["baseline"]) and r["programs"] == "survived"],
        neither=[r["mutant"] for r in live if not dead(r["programs"]) and r["baseline"] == "survived"],
        seconds=round(time.time() - t0, 1),
    )
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(OUT, f"{stamp}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(dict(args=vars(args), rows=rows, summary=summary), fh, indent=1)
    print(json.dumps(summary, indent=1))
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
