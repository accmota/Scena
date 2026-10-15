"""The model over the three test families: programs, games, scripts.

Each function records one run and returns its model ``Report``. A finding
whose signature is in ``laws.known.KNOWN`` (with its verdict) is expected;
anything else is a candidate to investigate (Testing Design, "Laws and
equations", triage).
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict, List

from laws import model
from laws.attach import attach
from laws.neutrality import run_script


def program(program_name: str, spec_ns: Dict[str, Any], scenario: str) -> model.Report:
    import program_oracles as po
    box: Dict[str, Any] = {}

    def hook(run):
        attach(run)
        box["run"] = run

    po._run(program_name, spec_ns, scenario, before_start=hook)
    return model.check(box["run"].laws.events)


def game(game_name: str, scenario: str, **kw) -> model.Report:
    import game_harness as gh
    box: Dict[str, Any] = {}

    def hook(run):
        attach(run)
        box["run"] = run

    gh.run_game(game_name, scenario, before_start=hook, **kw)
    return model.check(box["run"].laws.events)


def _tuples(x):
    """JSON lists back to the trace's tuples, at every depth (a commit holds
    tuples of label pairs)."""
    return tuple(_tuples(v) for v in x) if isinstance(x, list) else x


def load_trace(path: str) -> List[tuple]:
    with open(path, encoding="utf-8") as fh:
        return [_tuples(json.loads(line)) for line in fh]


def script(path: str, frames: int) -> model.Report:
    with tempfile.TemporaryDirectory(prefix="laws_") as tmp:
        out = os.path.join(tmp, "trace.jsonl")
        run_script(path, frames, laws_out=out)
        events = load_trace(out)
    meta = events.pop() if events and events[-1][0] == "meta" else None
    rep = model.check(events)
    if meta is not None and meta[2]:
        rep.find("E0", 0, f"recorder errors {meta[2][:3]}", "recorder")
    return rep


def unexpected(rep: model.Report) -> List[str]:
    """Findings not in ``KNOWN``: one line per signature."""
    from laws.known import KNOWN
    out = []
    for sig, fs in sorted(rep.signatures().items()):
        if sig in KNOWN:
            continue
        out.append(f"{sig}: {len(fs)}x, first at frame {fs[0].frame}: {fs[0].msg}")
    return out
