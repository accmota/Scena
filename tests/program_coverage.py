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
from typing import Dict, Iterable, List, Set, Tuple

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


def collect(program_files: Iterable[str] = (), scenarios=None) -> Dict[str, Set[str]]:
    """``{export: {member qualnames}}`` reached by the programs' own code."""
    calls: Set[Tuple[str, str]] = set()           # (qualname, filename)
    classes: Set[str] = set()                     # exported classes an author call was about
    prog_files = set()

    def prof(frame, event, arg):
        if event != "call":
            return
        caller = frame.f_back
        if caller is None or caller.f_code.co_filename not in prog_files:
            return
        code = frame.f_code
        if code.co_filename.startswith(SCENA_DIR):
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

    for prog, letter in program_specs():
        ns = load_spec(prog, letter)
        from program_support import program_path
        prog_files.add(program_path(prog))
        for sc in ns["SCENARIOS"]:
            sys.setprofile(prof)
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    run_scenario(prog, ns, sc)
            except Exception as e:  # a crashing scenario is reported by its own test
                print(f"  ({prog}/{letter} {sc}: {type(e).__name__})", file=sys.stderr)
            finally:
                sys.setprofile(None)

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


# Read-only records the engine hands out: reached when a program reads the
# property that hands them out (an attribute read is not a call the hook sees).
RECORD_HINTS = {"TouchingContact": "touching_contacts", "CollisionInfo": "info."}


def source_reached() -> Set[str]:
    """Enums named in a program, and records whose property a program reads."""
    import enum
    import re
    from program_support import program_path
    srcs = []
    for prog, _l in program_specs():
        with open(program_path(prog), encoding="utf-8") as fh:
            srcs.append(fh.read())
    text = "\n".join(srcs)
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


def global_objects_touched() -> Set[str]:
    """Exported non-class / non-function objects (``st``, ``keyp``, ``canvas`` …)
    referenced by any program's source text (a read of a global object is not a
    Python call the profile hook sees)."""
    import re
    names = {n for n in scena.__all__
             if not inspect.isclass(getattr(scena, n, None))
             and not inspect.isfunction(getattr(scena, n, None))}
    from program_support import program_path
    seen = set()
    for prog, _l in program_specs():
        with open(program_path(prog), encoding="utf-8") as fh:
            src = fh.read()
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
