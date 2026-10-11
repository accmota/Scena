#!/usr/bin/env python
"""Which author names do the program model tests reach? (Phase 3 coverage pass)

Not a test module. Runs every scenario of every program spec with a profile
hook that records each call made **from a program's own code** into ``scena``
(constructors, functions, methods, property getters / setters), then maps the
calls onto ``scena.__all__``. An export counts as reached when the program
constructs it, calls it, or calls a member of it (``Circle.move_by`` reaches
``Circle``; a method inherited from ``Graphic`` reaches ``Graphic``).

    python tests/program_coverage.py            # summary + unreached exports
    python tests/program_coverage.py --json     # also .scena_test_runs/program_coverage.json

``test_program_coverage.py`` turns the report into a guard: every export is
reached or listed in ``PROGRAM_EXCLUDED`` with a reason.
"""
from __future__ import annotations

import inspect
import json
import os
import sys
import warnings
from typing import Callable, Dict, Iterable, List, Set, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import scena  # noqa: E402
from program_support import PROGRAMS, load_spec, run_scenario  # noqa: E402

SCENA_DIR = os.path.dirname(os.path.abspath(scena.__file__))
OUT = os.path.join(os.path.dirname(HERE), ".scena_test_runs", "program_coverage.json")

# The program behind each spec file (base name -> program argument).
def program_specs() -> List[Tuple[str, str]]:
    from source_support import iter_files
    out = []
    for path in iter_files(PROGRAMS, ".py", recursive=False):
        name = os.path.basename(path)
        if "_spec_" not in name:
            continue
        base, letter = name[:-3].split("_spec_")
        prog = base
        if not os.path.exists(os.path.join(PROGRAMS, base + ".py")):
            prog = f"examples/{base}.py"
        out.append((prog, letter))
    return out


def _export_owners() -> Dict[str, str]:
    """Qualified-name prefix -> export name, for every exported class and function."""
    owners = {}
    for name in scena.__all__:
        obj = getattr(scena, name, None)
        if inspect.isclass(obj) or inspect.isfunction(obj):
            owners[getattr(obj, "__qualname__", name)] = name
    return owners


def collect_runs(runs: Iterable[Tuple[str, Callable[[], object]]],
                 files: Iterable[str]) -> Dict[str, Set[str]]:
    """``{export: {member qualnames}}`` reached by calls made from ``files``.

    ``runs`` is ``(label, run)`` pairs; each ``run()`` executes under the
    monitoring hook. A run that raises is reported on stderr (its own test
    reports it properly) and the others go on. The game system tests
    (``test_game_coverage``) reuse this with their own runs.
    """
    calls: Set[Tuple[str, str]] = set()           # (qualname, filename)
    classes: Set[str] = set()                     # exported classes an author call was about
    prog_files = set(files)

    mon = sys.monitoring
    # Every Python frame that starts (or a generator resumes: what a profile
    # hook's "call" sees) in scena, called from a program's own code. A code
    # object outside scena is never recorded: DISABLE stops its events for
    # good, so only scena frames pay the callback (a sys.setprofile hook, on
    # every call, return and C call, took 101 s here against 55 s; the
    # scenarios alone take 32 s).
    events = mon.events.PY_START | mon.events.PY_RESUME

    def on_start(code, _offset):
        if not code.co_filename.startswith(SCENA_DIR):
            return mon.DISABLE
        frame = sys._getframe(1)                  # the frame that starts
        caller = frame.f_back
        if caller is None or caller.f_code.co_filename not in prog_files:
            return None
        calls.add((code.co_qualname, code.co_filename))
        # Exported constructors are wrapped (friendly-constructor shims),
        # and visuals are interned through __new__: name the class of the
        # object the call is about.
        loc = frame.f_locals
        for key in ("self", "cls"):
            obj = loc.get(key)
            if obj is None:
                continue
            cls = obj if inspect.isclass(obj) else type(obj)
            for c in cls.__mro__:
                if getattr(scena, c.__name__, None) is c:
                    classes.add(c.__name__)
        return None

    # The profiler slot, or a free one (cProfile and coverage.py take theirs).
    tool = next((t for t in (mon.PROFILER_ID, 3, 4) if mon.get_tool(t) is None), None)
    if tool is None:
        raise RuntimeError("no free sys.monitoring tool id for program coverage")
    mon.use_tool_id(tool, "scena program coverage")
    try:
        mon.register_callback(tool, mon.events.PY_START, on_start)
        mon.register_callback(tool, mon.events.PY_RESUME, on_start)
        for label, run in runs:
            mon.set_events(tool, events)
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    run()
            except Exception as e:  # a crashing scenario is reported by its own test
                print(f"  ({label}: {type(e).__name__})", file=sys.stderr)
            finally:
                mon.set_events(tool, 0)
    finally:
        mon.register_callback(tool, mon.events.PY_START, None)
        mon.register_callback(tool, mon.events.PY_RESUME, None)
        mon.free_tool_id(tool)
        mon.restart_events()                      # undo the DISABLEs

    owners = _export_owners()
    reached: Dict[str, Set[str]] = {}
    for qual, _fn in calls:
        head = qual.split(".")[0]
        if qual in owners:
            reached.setdefault(owners[qual], set()).add(qual)
        elif head in owners:
            reached.setdefault(owners[head], set()).add(qual)
    for name in classes:
        reached.setdefault(name, set()).add(name + " (instance)")
    return reached


def collect(program_files: Iterable[str] = (), scenarios=None) -> Dict[str, Set[str]]:
    """``{export: {member qualnames}}`` reached by the programs' own code."""
    from program_support import program_path
    runs, files = [], []
    for prog, letter in program_specs():
        ns = load_spec(prog, letter)
        files.append(program_path(prog))
        for sc in ns["SCENARIOS"]:
            runs.append((f"{prog}/{letter} {sc}",
                         lambda prog=prog, ns=ns, sc=sc: run_scenario(prog, ns, sc)))
    return collect_runs(runs, files)


# Read-only records the engine hands out: reached when a program reads the
# property that hands them out (an attribute read is not a call the hook sees).
RECORD_HINTS = {"TouchingContact": "touching_contacts", "CollisionInfo": "info."}


def _program_texts() -> List[str]:
    from program_support import program_path
    out = []
    for prog, _l in program_specs():
        with open(program_path(prog), encoding="utf-8") as fh:
            out.append(fh.read())
    return out


def source_reached(texts: Iterable[str] = None) -> Set[str]:
    """Enums named in a program, and records whose property a program reads."""
    import enum
    import re
    text = "\n".join(_program_texts() if texts is None else texts)
    out = set()
    for n in scena.__all__:
        obj = getattr(scena, n, None)
        if inspect.isclass(obj) and issubclass(obj, enum.Enum) \
                and re.search(rf"(?<![\w.]){n}\.", text):
            out.add(n)
    for n, hint in RECORD_HINTS.items():
        if hint in text:
            out.add(n)
    return out


def global_objects_touched(texts: Iterable[str] = None) -> Set[str]:
    """Exported non-class / non-function objects (``st``, ``keyp``, ``canvas`` …)
    referenced by any program's source text (a read of a global object is not a
    Python call the profile hook sees)."""
    import re
    names = {n for n in scena.__all__
             if not inspect.isclass(getattr(scena, n, None))
             and not inspect.isfunction(getattr(scena, n, None))}
    seen = set()
    for src in (_program_texts() if texts is None else texts):
        for n in names:
            if re.search(rf"(?<![\w.]){re.escape(n)}(?!\w)", src):
                seen.add(n)
    return seen


def report(write_json: bool = False) -> Dict[str, object]:
    reached = collect()
    globals_seen = global_objects_touched()
    all_names = set(scena.__all__)
    hit = set(reached) | globals_seen | source_reached()
    missing = sorted(all_names - hit)
    out = {"exports": len(all_names), "reached": len(hit), "missing": missing,
           "members": {k: sorted(v) for k, v in sorted(reached.items())}}
    if write_json:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1)
    return out


if __name__ == "__main__":
    r = report(write_json="--json" in sys.argv)
    print(f"{r['reached']} / {r['exports']} exports reached by the programs")
    print("unreached:", ", ".join(r["missing"]))
