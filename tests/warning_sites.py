#!/usr/bin/env python
"""Which tests fire each engine warning? (measures ``test_warning_contracts.CONTRACTS``)

Not a test module. Runs a tier with ``tests/warnsite_site`` on PYTHONPATH (a
``sitecustomize`` that records every warning site that fires, by module and
function, with the test module that ran) and prints, for each site, the
modules that fired it, then the rows of ``CONTRACTS`` that disagree: a
``fires=`` module that did not fire it, an ``untested=`` row that something
fired. The hook adds a stack frame, so the stacklevel tests fail during the
measurement; that is expected.

    python tests/warning_sites.py              # quick tier
    python tests/warning_sites.py gate
"""
from __future__ import annotations

import collections
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from source_support import iter_files  # noqa: E402


def measure(tier: str = "quick"):
    fired = collections.defaultdict(set)
    with tempfile.TemporaryDirectory(prefix="scena_warnsites_") as log:
        env = {**os.environ, "SCENA_WARNSITE_LOG": log,
               "PYTHONPATH": os.pathsep.join(filter(None, [os.path.join(HERE, "warnsite_site"),
                                                           os.environ.get("PYTHONPATH", "")]))}
        subprocess.run([sys.executable, os.path.join(HERE, "run_tiers.py"), tier], cwd=ROOT, env=env)
        for path in iter_files(log, ".txt"):
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    site, _, mod = line.rstrip("\n").partition("\t")
                    name = mod.split()[0].split(".")[1] if mod.startswith("tests.") else (mod or "?")
                    fired[site].add(name)
    return fired


def main() -> None:
    from test_warning_contracts import CONTRACTS
    fired = measure(sys.argv[1] if len(sys.argv) > 1 else "quick")
    for site in sorted(CONTRACTS):
        print(f"{site:55s} {', '.join(sorted(fired.get(site, ()))) or '-'}")
    print("\nrows that disagree with the measurement:")
    for site, w in sorted(CONTRACTS.items()):
        got = fired.get(site, set())
        if w.fires and w.fires not in got:
            print(f"  {site}: fires={w.fires} did not fire it (fired by: {sorted(got) or 'nothing'})")
        if w.untested and got:
            print(f"  {site}: listed untested, fired by {sorted(got)}")


if __name__ == "__main__":
    main()
