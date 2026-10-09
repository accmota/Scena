"""The geometry fuzzer's regression corpus and its self-checks (geometry campaign, H10).

* ``TestCorpusReplays`` — every program of ``tests/fuzz/corpus/`` (a greedy
  coverage set built by ``geom_fuzz.py --build-corpus``) and every reduced
  repro in ``tests/fuzz/found/`` replays under the triple oracle (P vs P′,
  shadow, sentinel) with no failure outside ``geom_campaign_known``.
* ``TestFuzzerChecksItself`` — a seed replays to the same trace twice; every
  rewrite is applied somewhere in the corpus (no vacuous law); each planted
  canary is found within a fixed program budget (SCENA_CANARIES).

The volume runs (``python tests/fuzz/geom_fuzz.py --minutes 30``) are not a
tier: they run in campaign blocks and nightly (Testing Design — Geometry
campaign).

    python tests/run_tiers.py focused test_fuzz_corpus
"""
from __future__ import annotations

import json
import os
import random
import sys
import unittest
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "fuzz"))

from hypothesis_support import fresh_world, require_canaries  # noqa: E402
from source_support import iter_files  # noqa: E402

import geom_fuzz as F  # noqa: E402
import geom_gen as GEN  # noqa: E402
import geom_rewrite as RW  # noqa: E402

CORPUS = os.path.join(HERE, "fuzz", "corpus")
FOUND = os.path.join(HERE, "fuzz", "found")


def _records(folder):
    out = []
    for path in iter_files(folder, ".json"):
        with open(path, encoding="utf-8") as fh:
            out.append((os.path.basename(path), json.load(fh)))
    return out


class TestCorpusReplays(unittest.TestCase):
    def test_corpus_is_clean(self):
        records = _records(CORPUS)
        self.assertGreaterEqual(len(records), 40, "rebuild: geom_fuzz.py --build-corpus 2500")
        bad = []
        for name, rec in records:
            fails, _used = F.check(rec["program"], rec["rewrite_seed"])
            bad += [f"{name}: {sig}" for sig, _d in fails]
        self.assertEqual(bad, [])

    def test_found_repros_stay_fixed(self):
        bad = []
        for name, rec in _records(FOUND):
            fails, _used = F.check(rec["program"], rec["rewrite_seed"],
                                   sentinel=rec["signature"].startswith("sentinel"))
            if rec["signature"] in [s for s, _d in fails]:
                bad.append(f"{name}: {rec['signature']}")
        self.assertEqual(bad, [])


class TestFuzzerChecksItself(unittest.TestCase):
    def test_a_seed_replays_to_the_same_trace(self):
        for seed in (3, 17, 101):
            program = GEN.generate(seed)
            traces = []
            for _ in range(2):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    with fresh_world() as w:
                        t = GEN.run(w, program, shadow=True)
                traces.append(json.dumps([t.rows, t.refusals, t.shadow_bad], default=str, sort_keys=True))
            self.assertEqual(traces[0], traces[1], f"seed {seed} is not deterministic")
            self.assertEqual(GEN.generate(seed), program)

    def test_every_rewrite_is_applied_in_the_corpus(self):
        used = set()
        for _name, rec in _records(CORPUS):
            used |= {u.split(":")[0] for u in rec.get("rewrites", ())}
        missing = sorted(set(RW.REWRITES) - used)
        self.assertEqual(missing, [], "a law the corpus never applies (vacuous)")

    def test_canaries_are_found_within_budget(self):
        require_canaries(self)
        budget = {"flip": 20, "pivot": 20, "fast": 20, "turns": 40}
        missed = []
        for name, limit in budget.items():
            undo = F.plant(name)
            try:
                rng = random.Random(11)
                hit = None
                for k in range(limit):
                    program = GEN.generate(rng.randrange(1 << 30))
                    fails, _used = F.check(program, rng.randrange(1 << 30), sentinel=False)
                    if fails:
                        hit = k + 1
                        break
            finally:
                undo()
            if hit is None:
                missed.append(name)
        self.assertEqual(missed, [], "a planted bug the fuzzer does not find within its budget")


if __name__ == "__main__":
    unittest.main()
