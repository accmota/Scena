"""E0, neutrality: a run with the laws recorder is the run without it.

Every other law and equation trusts the trace, so the observer must not
change what it observes: same probe samples frame by frame, same world at
the end (kind, origin, pose of every object), same game ledger, same script
fingerprint. Also checked: the recorder saw every frame (a DISABLEd hook
would lose them) and raised nothing of its own.

Each function returns a list of messages (empty = neutral).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from typing import Any, Dict, List

from laws import trace
from laws.attach import attach

TESTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(TESTS)
HARNESS = os.path.join(TESTS, "script_harness.py")


def survivors() -> int:
    """Engine objects still alive as Python objects after a full collection.

    The registries forget a destroyed actor even while something holds it,
    so the census cannot see a recorder that keeps references; this count
    can (the same program leaves the same survivors with and without it)."""
    import gc
    gc.collect()
    n = 0
    for o in gc.get_objects():
        if getattr(type(o), "_scena_is_entity", False):
            n += 1
    return n


def _self_check(rec: trace.Recorder, frames: int, where: str) -> List[str]:
    out = []
    if rec.errors:
        out.append(f"{where}: recorder errors {rec.errors[:3]}")
    if rec.counts["frames"] != frames:
        out.append(f"{where}: recorder saw {rec.counts['frames']} frames of {frames}")
    left = trace.assert_clean()
    if left:
        out.append(f"{where}: recorder left {left}")
    return out


def program(program_name: str, spec_ns: Dict[str, Any], scenario: str) -> List[str]:
    """A program scenario with and without the recorder."""
    import program_oracles as po
    box: Dict[str, Any] = {}

    def hook(run):
        attach(run)
        box["run"] = run

    bare, fb = po._run(program_name, spec_ns, scenario, at_end=po.world_fingerprint)
    sb = survivors()
    traced, ft = po._run(program_name, spec_ns, scenario, before_start=hook,
                         at_end=po.world_fingerprint)
    st = survivors()
    where = f"{program_name}/{scenario}"
    out = [f"{where}: {m}" for m in po._diff_samples(bare, traced)]
    if st != sb:
        out.append(f"{where}: survivors {sb} vs {st} (the recorder keeps objects alive)")
    if fb != ft:
        rows = [f"  bare   {x}\n  traced {y}" for x, y in zip(fb, ft) if x != y][:3]
        out.append(f"{where}: world differs ({len(fb)} vs {len(ft)} objects)\n" + "\n".join(rows))
    if bare.leftovers != traced.leftovers:
        out.append(f"{where}: leftovers {bare.leftovers} vs {traced.leftovers}")
    run = box["run"]
    out += _self_check(run.laws, run.frames, where)
    return out


_REPORT_KEYS = ("frames", "time", "fails", "failures", "evals", "reach", "deaths")


def game(game_name: str, scenario: str, **kw) -> List[str]:
    """A game scenario with and without the recorder: ledger, probes, leftovers."""
    import game_harness as gh
    box: Dict[str, Any] = {}

    def hook(run):
        attach(run)
        box["run"] = run

    bare = gh.run_game(game_name, scenario, **kw)
    sb = survivors()
    traced = gh.run_game(game_name, scenario, before_start=hook, **kw)
    st = survivors()
    where = f"{game_name}/{scenario}"
    out = []
    if st != sb:
        out.append(f"{where}: survivors {sb} vs {st} (the recorder keeps objects alive)")
    for k in _REPORT_KEYS:
        if bare.report.get(k) != traced.report.get(k):
            out.append(f"{where}: report[{k!r}] {bare.report.get(k)!r:.160} "
                       f"vs {traced.report.get(k)!r:.160}")
    import program_oracles as po
    out += [f"{where}: {m}" for m in po._diff_samples(bare.trace, traced.trace)]
    if bare.leftovers != traced.leftovers:
        out.append(f"{where}: leftovers {bare.leftovers} vs {traced.leftovers}")
    if bare.warnings != traced.warnings:
        out.append(f"{where}: warnings {bare.warnings[:2]} vs {traced.warnings[:2]}")
    run = box["run"]
    out += _self_check(run.laws, run.frames, where)
    return out


def run_script(path: str, frames: int, *, laws_out: str = None, timeout: float = 240,
               cwd: str = None) -> str:
    """stdout of one headless run of ``path`` (``--fingerprint``); ``cwd``: the
    folder it runs from (a twin saved elsewhere under the example's name)."""
    cmd = [sys.executable, HARNESS, path, str(frames), "--fingerprint"]
    if laws_out is not None:
        cmd += ["--laws", laws_out]
    if cwd is not None:
        cmd += ["--cwd", cwd]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    p = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace",
                       timeout=timeout, env=env, cwd=ROOT)
    if p.returncode != 0:
        raise AssertionError(f"{os.path.relpath(path, ROOT)} exit {p.returncode}\n{p.stderr[-1500:]}")
    return p.stdout


def script(path: str, frames: int = 30) -> List[str]:
    """An example or tutorial step with and without the recorder."""
    import json
    where = os.path.relpath(path, ROOT)
    bare = run_script(path, frames)
    with tempfile.TemporaryDirectory(prefix="laws_") as tmp:
        out_path = os.path.join(tmp, "trace.jsonl")
        traced = run_script(path, frames, laws_out=out_path)
        with open(out_path, encoding="utf-8") as fh:
            last = fh.read().splitlines()[-1]
    meta = json.loads(last)
    out = []
    if bare != traced:
        out.append(f"{where}: stdout {bare.strip()!r} vs {traced.strip()!r}")
    counts, errors = meta[1], meta[2]
    if errors:
        out.append(f"{where}: recorder errors {errors[:3]}")
    if counts.get("frames") != frames:
        out.append(f"{where}: recorder saw {counts.get('frames')} frames of {frames}")
    return out
