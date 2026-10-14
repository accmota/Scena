#!/usr/bin/env python
"""Metamorphic fuzzer for the geometry engine (geometry campaign, H10).

Not a test module. Each program P (``geom_gen``) runs against a rewritten P′
(``geom_rewrite``: stacked laws), under a triple oracle:

1. **P vs P′** — after every original operation, every subject reads alike
   (drawn set, parts, heading modulo 360, scale, flags);
2. **shadow** (H1) — every call on P matches its subject's composed affine map;
3. **sentinel** (H2) — the runtime invariants hold through P and P′.

A non-author exception anywhere is a failure too. Failures are deduplicated
by signature (oracle × kind × first divergent observable × rewrites) and
written to ``.scena_test_runs/fuzz/failures/``; ``reduce.py`` shrinks one to a
deterministic ``unittest`` repro in ``tests/fuzz/found/``.

Coverage guidance: ``sys.monitoring`` BRANCH events over the geometry engine
modules record (branch, kind) pairs; a program reaching a new pair joins
``.scena_test_runs/fuzz/corpus/`` and is mutated further.

    python tests/fuzz/geom_fuzz.py --minutes 30 --workers 8 --seed 1
    python tests/fuzz/geom_fuzz.py --programs 400 --canary flip      # programs to detection
    python tests/fuzz/geom_fuzz.py --build-corpus 3000 --corpus-size 80   # regression corpus
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import math
import multiprocessing as mp
import os
import random
import sys
import time
import warnings
from typing import Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (HERE, TESTS, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import geom_gen as GEN  # noqa: E402
import geom_rewrite as RW  # noqa: E402

OUT = os.path.join(ROOT, ".scena_test_runs", "fuzz")
ENGINE = ("shapes", "entity", "state", "box", "sprite", "text", "track", "hitbox", "geom", "collision")


# ---------------------------------------------------------------------------
# Oracle
# ---------------------------------------------------------------------------

def _close(a, b, tol=1e-5) -> bool:
    if a is None or b is None:
        return a is b
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def _heading_close(a, b) -> bool:
    if a is None or b is None:
        return a is b
    d = abs((a - b + 180.0) % 360.0 - 180.0)
    return d <= 1e-4


def _diff_fp(a, b) -> Optional[str]:
    if a is None or b is None:
        return None                     # a linked subject: no cold comparison
    if isinstance(a, tuple) or isinstance(b, tuple):
        return None if a == b else f"fingerprint raises {a} vs {b}"
    if a["center"] and b["center"]:
        span = max(1.0, *(abs(v) for v in a["center"]))
        if any(abs(x - y) > 1e-4 * span for x, y in zip(a["center"], b["center"])):
            return "center (cold)"
    if not _heading_close(a["angle"], b["angle"]):
        return "pose store angle (cold)"
    pa, pb = a.get("prims"), b.get("prims")
    if pa is not None and pb is not None:
        from diff_support import diff_values, pair_prims
        try:
            g, w = pair_prims(_rehydrate(pa), _rehydrate(pb))
        except Exception:  # noqa: BLE001
            g, w = pa, pb
        if diff_values(g, w, "", 1e-6, 1e-4):
            return "collision prims (cold)"
    return None


def _rehydrate(rows):
    """``fingerprint`` prims are tuples; pair_prims wants objects with fields."""
    class _P:
        pass
    out = []
    for kind, aabb, params, verts in rows:
        p = _P()
        p.kind = type("K", (), {"name": kind})()
        if kind == "OBB" and len(params) >= 5:
            # A box is the same box turned by a half turn: compare the angle mod pi.
            params = tuple(params[:4]) + (params[4] % math.pi,) + tuple(params[5:])
        p.aabb, p.params, p.verts = aabb, params, verts
        out.append(p)
    return out


def diff_obs(a, b) -> Optional[str]:
    if isinstance(a, tuple) or isinstance(b, tuple):
        return None if a == b else f"raises {a} vs {b}"
    d = _diff_fp(a["fp"], b["fp"])
    if d or "drawn" not in a or "drawn" not in b:
        return d
    import geometry_support as G
    span = max([1.0] + [abs(c) for q in a["drawn"] for c in q])
    if not G.same_set(a["drawn"], b["drawn"], 1e-4 * span):
        return "drawn"
    for n in sorted(set(a["parts"]) & set(b["parts"])):
        pa, pb = a["parts"][n], b["parts"][n]
        if isinstance(pa, G.ReadError) or isinstance(pb, G.ReadError):
            if type(pa) is not type(pb):
                return f"part {G.part_group(n)}"
            continue
        if not (abs(pa[0] - pb[0]) <= 1e-4 * span and abs(pa[1] - pb[1]) <= 1e-4 * span):
            return f"part {G.part_group(n)}"
    if not _heading_close(a["heading"], b["heading"]):
        return "heading"
    if not _close(a["scale"], b["scale"]):
        return "scale"
    if a["flags"] != b["flags"]:
        return "flags"
    return None


def _sentinel_new(found) -> List[str]:
    import geom_campaign_known as K
    return sorted({v["key"] for v in found
                   if not any(fnmatch.fnmatch(v["key"], p) for p in K.SENTINEL)})


def _known_shadow(key) -> bool:
    import geom_campaign_known as K
    return any(fnmatch.fnmatch(key, p) for p in K.SHADOW)


RELATIONAL = ("parallel", "perpendicular", "tangent", "from_rect")


def tags(program, j) -> str:
    """Facts about subject ``j`` that map a divergence to a known finding."""
    spec = program["subjects"][j] if j < len(program["subjects"]) else {"kind": "", "base": ""}
    out = []
    if spec["kind"].startswith(("Line", "Track line")) and spec.get("base") == "degenerate":
        out.append("zero-length line")
    if any(w in spec["kind"] for w in RELATIONAL) and any(
            op[0] == "unlink" and op[1] == j for op in program["ops"]):
        out.append("relational unlinked")
    if spec.get("link") == "part":
        out.append("part link")
    if any(op[0] == "call" and op[1] == j and op[2] in ("scale_by", "scale_to") and op[3]
           and op[3][0] == 0 for op in program["ops"]):
        out.append("zero scale")
    return ",".join(out)


def _known_fuzz(sig) -> bool:
    import geom_campaign_known as K
    return any(fnmatch.fnmatch(sig, p) for p in getattr(K, "FUZZ", {}))


def check(program, rewrite_seed: int, n_rewrites: int = 3, *, sentinel: bool = True):
    """Run P and a rewritten P′. Returns (failures [(signature, detail)], rewrites used)."""
    import geom_sentinel as GS
    from hypothesis_support import fresh_world
    rng = random.Random(rewrite_seed)
    p2, aligned, used, x, swapped_at = RW.rewrite(program, rng, n_rewrites)
    failures = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ctx = GS.active(raise_=False) if sentinel else _Null()
        with ctx as found:
            with fresh_world() as w:
                t1 = GEN.run(w, program, shadow=True)
            with fresh_world() as w:
                t2 = GEN.run(w, p2, x=x, shadow=False, aligned=set(aligned))
            sent = _sentinel_new(found) if sentinel else []
    kinds = [s["kind"] for s in program["subjects"]]
    for e in t1.errors + t2.errors:
        failures.append((f"error | {e.split(':')[0]}", e))
    for k in t1.shadow_bad:
        j = next((i for i, sp in enumerate(program["subjects"]) if k.startswith(sp["kind"] + " |")), 0)
        sig = f"shadow | {k} | tags: {tags(program, j)}"
        if not _known_shadow(k) and not _known_fuzz(sig):
            failures.append((sig, ""))
    for k in sent:
        failures.append((f"sentinel | {k}", ""))
    rows = min(len(t1.rows), len(t2.rows))
    if len(t1.rows) != len(t2.rows):
        failures.append(("P vs P' | rows", f"{len(t1.rows)} vs {len(t2.rows)}"))
    for r in range(rows):
        if swapped_at is not None and r == swapped_at:
            continue
        for j, (a, b) in enumerate(zip(t1.rows[r], t2.rows[r])):
            d = diff_obs(a, b)
            if d:
                sig = (f"P vs P' | {kinds[j]} | {d} | {'+'.join(sorted(set(u for u in used)))}"
                       f" | tags: {tags(program, j)}")
                if not _known_fuzz(sig):
                    failures.append((sig, f"op {r}: {program['ops'][r] if r < len(program['ops']) else ''}"))
                break
        else:
            continue
        break
    # Refusals are not compared one by one: a rewrite that inserts calls on a
    # linked subject adds refusals of its own. A call refused one way and run
    # the other shows in the state rows; a refusal that changed something
    # shows in the sentinel (I-atomic) and the shadow.
    return failures, used


def replay(program, rewrite_seed, n_rewrites=3):
    """P, P′ and their traces, for triage (no sentinel)."""
    from hypothesis_support import fresh_world
    rng = random.Random(rewrite_seed)
    p2, aligned, used, x, swapped_at = RW.rewrite(program, rng, n_rewrites)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with fresh_world() as w:
            t1 = GEN.run(w, program, shadow=True)
        with fresh_world() as w:
            t2 = GEN.run(w, p2, x=x, shadow=False, aligned=set(aligned))
    return p2, used, x, t1, t2


class _Null:
    def __enter__(self):
        return []

    def __exit__(self, *exc):
        return False


# ---------------------------------------------------------------------------
# Coverage guidance (sys.monitoring BRANCH over the engine modules)
# ---------------------------------------------------------------------------

class Coverage:
    TOOL = 3

    def __init__(self):
        self.seen = set()
        self.box = [set()]          # the callback adds here; take() swaps in a new set
        import scena
        base = os.path.dirname(scena.__file__)
        self.files = {os.path.join(base, m + ".py") for m in ENGINE}

    def start(self):
        mon = sys.monitoring
        if mon.get_tool(self.TOOL) is None:
            mon.use_tool_id(self.TOOL, "scena-fuzz-coverage")
        E = mon.events
        files = self.files
        box = self.box

        def on_branch(code, src, dst):
            if code.co_filename not in files:
                return mon.DISABLE
            box[0].add((code.co_filename, src, dst))
            return mon.DISABLE
        mon.register_callback(self.TOOL, E.BRANCH, on_branch)
        mon.set_events(self.TOOL, E.BRANCH)

    def take(self, kinds) -> int:
        """New (branch, kind) pairs since the last call."""
        hits, self.box[0] = self.box[0], set()     # engine finalizers may still add
        sys.monitoring.restart_events()
        fam = tuple(sorted({k.split()[0] for k in kinds}))
        new = {(b, fam) for b in hits} - self.seen
        self.seen |= new
        return len(new)


# ---------------------------------------------------------------------------
# Canaries: planted bugs and the programs it takes to find each
# ---------------------------------------------------------------------------

def plant(name):
    """Patch a known bug back in; returns an undo function."""
    from unittest import mock
    import scena.shapes as SH
    from scena.shapes import Shape, _RadialPolygon
    if name == "flip":
        # The shared base: RegularPolygon and Triangle (not a RegularPolygon) both flip here.
        p = mock.patch.object(_RadialPolygon, "_mirror_geometry", Shape._mirror_geometry)
    elif name == "pivot":
        p = mock.patch.object(SH, "_scale_xy", lambda x, y, cx, cy, f: (x * f, y * f))
    elif name == "fast":
        orig = SH._translate_point_float
        p = mock.patch.object(SH, "_translate_point_float",
                              lambda pt, dx=None, dy=None: orig(pt, None if dx is None else dx * 1.001, dy))
    elif name == "turns":
        p = mock.patch.object(SH, "_unwrap_deg", lambda raw, acc: (raw + 180.0) % 360.0 - 180.0)
    else:
        raise SystemExit(f"unknown canary {name}")
    p.start()
    return p.stop


CANARIES = ("flip", "pivot", "fast", "turns")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def signature_id(sig: str) -> str:
    return hashlib.sha1(sig.encode("utf-8")).hexdigest()[:12]


def _worker(args):
    wid, seed, deadline, n_programs, canary, corpus_dir, out_dir = args
    from hypothesis_support import boot
    boot()
    rng = random.Random(seed * 7919 + wid)
    cov = Coverage()
    cov.start()
    corpus = []
    found, usage, ran = {}, {}, 0
    undo = plant(canary) if canary else None
    first_hit = None
    try:
        while (deadline is None or time.time() < deadline) and (n_programs is None or ran < n_programs):
            if corpus and rng.random() < 0.4:
                program = GEN.mutate(rng.choice(corpus), rng)
            else:
                program = GEN.generate(rng.randrange(1 << 30))
            rw_seed = rng.randrange(1 << 30)
            try:
                fails, used = check(program, rw_seed)
            except Exception as exc:  # noqa: BLE001  (a harness crash is a finding too)
                fails, used = [(f"harness | {type(exc).__name__}", str(exc)[:200])], []
            ran += 1
            for u in used:
                usage[u.split(":")[0]] = usage.get(u.split(":")[0], 0) + 1
            if cov.take([s["kind"] for s in program["subjects"]]):
                corpus.append(program)
                if corpus_dir:
                    GEN.save(os.path.join(corpus_dir, f"w{wid}_{len(corpus):05d}.json"), program)
            for sig, detail in fails:
                if sig not in found:
                    found[sig] = {"program": program, "detail": detail, "count": 0}
                    if out_dir:
                        GEN.save(os.path.join(out_dir, f"{signature_id(sig)}.json"),
                                 {"signature": sig, "detail": detail, "program": program,
                                  "rewrite_seed": rw_seed})
                found[sig]["count"] += 1
                if first_hit is None:
                    first_hit = ran
    finally:
        if undo:
            undo()
    return {"ran": ran, "found": {k: {"count": v["count"], "detail": v["detail"]} for k, v in found.items()},
            "usage": usage, "first_hit": first_hit, "corpus": len(corpus)}


CORPUS = os.path.join(HERE, "corpus")


def build_corpus(n_candidates: int, limit: int, seed: int = 0) -> int:
    """Greedy set cover: run ``n_candidates`` generated programs, record the
    (branch, family) pairs each reaches, then keep up to ``limit`` programs,
    each time the one adding the most pairs not yet covered. Clean programs
    only, each with its rewrite seed. Writes ``tests/fuzz/corpus/``."""
    from hypothesis_support import boot
    from source_support import iter_files
    boot()
    cov = Coverage()
    cov.start()
    rng = random.Random(seed)
    cands = []
    for _k in range(n_candidates):
        program = GEN.generate(rng.randrange(1 << 30))
        rw = rng.randrange(1 << 30)
        cov.box[0] = set()
        fails, used = check(program, rw, sentinel=False)
        hits, cov.box[0] = cov.box[0], set()
        if fails:
            continue
        fam = tuple(sorted({s["kind"].split()[0] for s in program["subjects"]}))
        cands.append(({(b, f) for b in hits for f in fam}, program, rw, used))
    covered, chosen = set(), []
    while cands and len(chosen) < limit:
        best = max(range(len(cands)), key=lambda i: len(cands[i][0] - covered))
        gain = cands[best][0] - covered
        if not gain:
            break
        covered |= gain
        chosen.append(cands.pop(best))
    os.makedirs(CORPUS, exist_ok=True)
    for old in iter_files(CORPUS, ".json"):
        os.remove(old)
    for k, (_pairs, program, rw, used) in enumerate(chosen, 1):
        GEN.save(os.path.join(CORPUS, f"{k:03d}.json"),
                 {"program": program, "rewrite_seed": rw, "rewrites": used})
    print(f"covered {len(covered)} (branch, family) pairs with {len(chosen)} of {len(cands) + len(chosen)} programs")
    return len(chosen)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--minutes", type=float, default=None)
    ap.add_argument("--programs", type=int, default=None, help="per worker")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--canary", choices=CANARIES, default=None)
    ap.add_argument("--build-corpus", type=int, metavar="N", default=None,
                    help="rebuild tests/fuzz/corpus/ from N candidates (greedy coverage)")
    ap.add_argument("--corpus-size", type=int, default=80)
    args = ap.parse_args(argv)
    if args.build_corpus:
        kept = build_corpus(args.build_corpus, args.corpus_size, args.seed)
        print(f"corpus: {kept} programs in {CORPUS}")
        return 0
    if args.minutes is None and args.programs is None:
        args.programs = 50
    deadline = time.time() + 60 * args.minutes if args.minutes else None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    corpus_dir = os.path.join(OUT, "corpus")
    out_dir = os.path.join(OUT, "failures" if not args.canary else f"canary-{args.canary}")
    os.makedirs(corpus_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    jobs = [(w, args.seed, deadline, args.programs, args.canary, corpus_dir, out_dir)
            for w in range(args.workers)]
    t0 = time.time()
    ctx = mp.get_context("spawn")
    with ctx.Pool(args.workers) as pool:
        results = pool.map(_worker, jobs)
    ran = sum(r["ran"] for r in results)
    found: Dict[str, dict] = {}
    usage: Dict[str, int] = {}
    for r in results:
        for k, v in r["found"].items():
            found.setdefault(k, {"count": 0, "detail": v["detail"]})["count"] += v["count"]
        for k, v in r["usage"].items():
            usage[k] = usage.get(k, 0) + v
    hits = [r["first_hit"] for r in results if r["first_hit"] is not None]
    report = {"programs": ran, "seconds": round(time.time() - t0, 1), "signatures": found,
              "rewrite_usage": usage, "canary": args.canary,
              "programs_to_detection": min(hits) if hits else None,
              "corpus": sum(r["corpus"] for r in results)}
    with open(os.path.join(OUT, f"report-{stamp}.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    print(f"{ran} programs in {report['seconds']} s; {len(found)} signatures; corpus +{report['corpus']}")
    for k, v in sorted(found.items(), key=lambda kv: -kv[1]["count"]):
        print(f"  {v['count']:5d}  {k}\n         {v['detail'][:150]}")
    unused = sorted(set(RW.REWRITES) - set(usage))
    print("rewrites used:", dict(sorted(usage.items())), "unused:", unused)
    if args.canary:
        print(f"canary {args.canary}: programs to detection = {report['programs_to_detection']}")
        return 0 if report["programs_to_detection"] else 1
    return 1 if found or unused else 0


if __name__ == "__main__":
    sys.exit(main())
