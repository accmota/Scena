#!/usr/bin/env python
"""Reduce a fuzz failure to a minimal deterministic repro (geometry campaign, H10).

Not a test module. Delta debugging (ddmin) over the program's operations, then
its subjects, keeping the failure's signature; the rewrites are replayed from
the recorded seed, so a smaller program keeps the same rewrite choices only
when they still apply (the signature decides). Writes the reduced program to
``tests/fuzz/found/<id>.json`` and a ``unittest`` that replays it to
``tests/fuzz/found/test_<id>.py`` — move it into the owning
``tests/test_<area>.py`` during the fix wave.

    python tests/fuzz/reduce.py .scena_test_runs/fuzz/failures/<id>.json
    python tests/fuzz/reduce.py --all          # every recorded failure
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from typing import Callable, List

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (HERE, TESTS, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import geom_fuzz as F  # noqa: E402
import geom_gen as GEN  # noqa: E402

FOUND = os.path.join(HERE, "found")


def fails_with(program, rewrite_seed, signature) -> bool:
    try:
        fails, _used = F.check(program, rewrite_seed, sentinel=signature.startswith("sentinel"))
    except Exception:  # noqa: BLE001
        return False
    return any(s == signature for s, _d in fails)


def ddmin(items: List, test: Callable[[List], bool]) -> List:
    """Zeller's ddmin: a 1-minimal sublist on which ``test`` still holds."""
    n = 2
    while len(items) >= 2:
        chunk = max(1, len(items) // n)
        subsets = [items[i:i + chunk] for i in range(0, len(items), chunk)]
        reduced = False
        for k in range(len(subsets)):
            complement = [x for j, s in enumerate(subsets) if j != k for x in s]
            if complement and test(complement):
                items, n, reduced = complement, max(n - 1, 2), True
                break
        if not reduced:
            if n >= len(items):
                break
            n = min(len(items), n * 2)
    return items


def reduce(record) -> dict:
    sig, seed = record["signature"], record.get("rewrite_seed", 0)
    program = json.loads(json.dumps(record["program"]))
    if not fails_with(program, seed, sig):
        return {"signature": sig, "reproduced": False, "program": program}

    def with_ops(ops):
        p = dict(program)
        p["ops"] = ops
        return p
    ops = ddmin(program["ops"], lambda o: fails_with(with_ops(o), seed, sig))
    program = with_ops(ops)
    # Subjects no operation names can go (indexes are renumbered).
    used = sorted({op[1] for op in ops if len(op) > 1 and isinstance(op[1], int)})
    if len(used) < len(program["subjects"]):
        remap = {old: new for new, old in enumerate(used)}
        trial = {"seed": program["seed"], "subjects": [program["subjects"][i] for i in used],
                 "ops": [[op[0], remap[op[1]], *op[2:]] if len(op) > 1 and isinstance(op[1], int)
                         else op for op in ops]}
        if fails_with(trial, seed, sig):
            program = trial
    return {"signature": sig, "reproduced": True, "program": program, "rewrite_seed": seed}


TEMPLATE = '''"""Fuzz repro {ident}: {signature}

Reduced by tests/fuzz/reduce.py. Move the case into the owning
tests/test_<area>.py when its fix lands (Testing Design, bug loop step 3).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

import geom_fuzz as F  # noqa: E402

PROGRAM = {program}
REWRITE_SEED = {seed}
SIGNATURE = {signature!r}


class TestRepro(unittest.TestCase):
    def test_{ident}(self):
        fails, _used = F.check(PROGRAM, REWRITE_SEED, sentinel=SIGNATURE.startswith("sentinel"))
        self.assertNotIn(SIGNATURE, [s for s, _d in fails])


if __name__ == "__main__":
    unittest.main()
'''


def emit(result) -> str:
    os.makedirs(FOUND, exist_ok=True)
    ident = F.signature_id(result["signature"])
    with open(os.path.join(FOUND, f"{ident}.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1)
    with open(os.path.join(FOUND, f"test_{ident}.py"), "w", encoding="utf-8") as fh:
        fh.write(TEMPLATE.format(ident=ident, signature=result["signature"],
                                 program=json.dumps(result["program"]), seed=result["rewrite_seed"]))
    return ident


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args(argv)
    from hypothesis_support import boot
    boot()
    paths = list(args.paths)
    if args.all:
        from source_support import iter_files
        paths += iter_files(os.path.join(F.OUT, "failures"), ".json")
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            record = json.load(fh)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = reduce(record)
        if not result["reproduced"]:
            print(f"not reproduced: {record['signature']}")
            continue
        ident = emit(result)
        print(f"{ident}: {len(result['program']['ops'])} ops, "
              f"{len(result['program']['subjects'])} subjects — {result['signature']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
