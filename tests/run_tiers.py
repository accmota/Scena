#!/usr/bin/env python
"""Tiered test runner: one process per test module (or shard), in parallel.

Run from the repo root::

    python tests/run_tiers.py focused test_shapes test_collision  # T0  < 30 s
    python tests/run_tiers.py quick                               # T1  ~ 1 min
    python tests/run_tiers.py gate                                # T2  ~ 5 min
    python tests/run_tiers.py deep                                # T3  2 h +

    python tests/run_tiers.py gate --plan      # print the jobs, run nothing
    python tests/run_tiers.py quick -j 4       # worker processes (default cpus - 2)

Why one process per module: Scena keeps ONE ScenaFramework per process, so a
single ``unittest discover`` grows the heap module after module, and every
``census()`` / ``full_collect()`` walks that heap. Measured: 5001 tests take
~24 min in one process and ~2 min as one process per module on 8 workers.
The deep tier still runs one serial pass (every module of every test root in
ONE process): it is the only run that sees state leaking from one module
into the next.

Tiers (strategy in design/Testing Design.md, "Test tiers"):

    focused  the named modules, dev profile, canaries off
    quick    every module but SLOW, dev profile, canaries off
    gate     every module, ci profile, canaries on, SPLIT modules sharded
    deep     every module, deep profile, canaries on, soak on,
             then one serial pass over every root (dev profile)

Each job is ``run_tiers.py --child <names>``: ``python -m unittest`` plus a
leftover check after each module (a module destroys what its tests made;
tests/leftovers.py).

Logs: ``.scena_test_runs/<tier>/<job>.log`` (a long label is shortened,
see ``log_name``); timings (used to start the
slowest jobs first): ``.scena_test_runs/timings.json``. Exit status 1 when a
job fails, errors, or times out.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
# Test roots: package -> folder. The level editor (companion app) keeps its
# tests next to it; module names stay unique across roots (test_editor_*).
TEST_ROOTS = (("tests", TESTS),
              ("scena_editor.tests", os.path.join(ROOT, "scena_editor", "tests")))
OUT = os.path.join(ROOT, ".scena_test_runs")
PYCACHE = os.path.join(OUT, "pycache")  # see child_env

# Modules too slow for the quick tier: past ~15 s of CPU at dev, alone (``focused``;
# a module that runs children in parallel counts their CPU). Testing Design, "Test tiers".
SLOW = frozenset({
    "test_hyp_surface",    # ~120 s dev, ~430 s ci: one generated test per export
    "test_sys_hyp_world",  # ~35 s dev: session state machine + reach guard + canaries
    "test_guia_thumbs_render",  # ~30 s: real renders, one child process each
    "test_program_coverage",    # ~55 s: every program spec scenario under a sys.monitoring hook
    "test_fuzz_corpus",         # the geometry fuzzer's corpus replay: gate only (Testing Design)
    # Exhaustive enumerations (measured alone 2026-10-10; under quick's 8 workers ~2.5x).
    "test_reactive_matrix_cells",  # ~22 s: every subject x field x path x order
                                   # (quick keeps test_reactive_matrix: guards + canary targets)
    "test_geometry_contract",   # ~18 s: the C1-C8 sweeps at fixed poses are 95 % of it
    "test_refusal_atomic",      # ~17 s: one test enumerates every kind x call x refusal source
    "test_smoke_scripts",       # ~22 s CPU in parallel children: scripts/smoke + benches
                                # (quick keeps test_scripts_run: the examples, ~11 s CPU)
    "test_tutorial_steps",      # ~300-500 s CPU: every tutorial step and box, 600 frames each
                                # (quick keeps test_tutorials and the endpoints in test_scripts_run)
    # Program model tests (gate / deep run them all; quick keeps the light ones).
    "test_prog_naves", "test_prog_cadeia_de_bolas", "test_prog_platformer",
    "test_prog_galaga_acts", "test_prog_runner_story",
    "test_prog_isolation",       # ~50 s dev, ~150 s ci: every program after a neighbour and
                                 # after dirty predecessors; ci runs every ordered pair
    "test_prog_invariance",      # ~35 s dev, ~195 s ci: camera, time-scale and layer-rename
                                 # oracles over every program; ci runs every scenario and camera
    # Game system tests (tests/games/): quick runs test_game_<name>; the long
    # runs, L3 oracles, random pilots and canaries are gate / deep.
    "test_game_armada_deep", "test_game_caverna_deep", "test_game_oficina_deep",
    "test_game_canteiro_deep",
    "test_game_coverage",        # every game under the coverage profile hook
    # Laws campaign (tests/laws/): quick runs test_laws_quick (the recorder, its
    # fixtures, the models on synthetic traces); the sweeps over the three
    # families are gate / deep.
    "test_laws_neutrality",      # ~110 s CPU dev: E0 over programs, games, examples
    "test_laws_families",        # the model over programs, games, examples (deep: tutorial steps)
    "test_laws_equations",       # E3 / E4 / E8: twins, every program, every example
})
# Modules sharded by TestCase class (big classes in chunks) in gate / deep.
SPLIT = frozenset({
    "test_hyp_surface",         # TestDeadEntityVerbs: one test per kind and verb kind
    "test_prog_invariance",     # one class per program
    "test_prog_isolation",      # one class per program read (B)
    "test_tutorial_steps",      # one class per tutorial page: one job per page
    "test_game_armada_deep", "test_game_caverna_deep", "test_game_oficina_deep",
    "test_game_canteiro_deep",
    "test_laws_neutrality",     # one class per family
    "test_laws_families",       # one class per family
    "test_laws_equations",      # one class per equation
})
CHUNK = 40  # max tests per shard of a SPLIT module


@dataclass(frozen=True)
class Tier:
    name: str
    profile: str
    canaries: bool
    timeout: float                      # seconds per job
    exclude: frozenset = frozenset()
    split: bool = False
    soak: bool = False
    serial_pass: bool = False           # finish with one single-process discover


TIERS: Dict[str, Tier] = {
    "focused": Tier("focused", "dev", canaries=False, timeout=900),
    "quick": Tier("quick", "dev", canaries=False, timeout=300, exclude=SLOW),
    "gate": Tier("gate", "ci", canaries=True, timeout=1800, split=True),
    "deep": Tier("deep", "deep", canaries=True, timeout=4 * 3600, split=True,
                 soak=True, serial_pass=True),
}


@dataclass
class Job:
    label: str
    names: List[str]                    # arguments to ``python -m unittest``
    env: Dict[str, str] = field(default_factory=dict)
    estimate: float = 0.0


@dataclass
class Result:
    job: Job
    seconds: float
    returncode: int
    ran: int = 0
    status: str = ""
    log: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


# --------------------------------------------------------------------------
# Planning (pure: unit-tested in tests/test_run_tiers.py)
# --------------------------------------------------------------------------

def discover_modules(tests_dir: Optional[str] = None) -> List[str]:
    """``test_*`` modules in ``tests_dir``, or in every test root."""
    dirs = [tests_dir] if tests_dir is not None else [d for _p, d in TEST_ROOTS]
    out = set()
    for d in dirs:
        if os.path.isdir(d):
            out.update(f[:-3] for f in os.listdir(d)
                       if f.startswith("test_") and f.endswith(".py"))
    return sorted(out)


def serial_names(roots=None) -> List[str]:
    """Every test module of every root as ``package.module``, root by root
    (``tests`` first), each root sorted — one ``python -m unittest`` process.
    ``unittest discover`` takes one start folder, so the names are listed."""
    out: List[str] = []
    for package, folder in (TEST_ROOTS if roots is None else roots):
        out += [f"{package}.{m}" for m in discover_modules(folder)]
    return out


def package_of(module: str) -> str:
    """The package that holds ``module`` (``tests`` unless another root has it)."""
    base = module.split(".", 1)[0]
    for package, folder in TEST_ROOTS:
        if os.path.isfile(os.path.join(folder, base + ".py")):
            return package
    return "tests"


SOURCE_DIRS = ("scena", "tests", "scripts", "examples", "design", "docs", "tools", "scena_editor")


def count_appledouble(root: str = ROOT, dirs: Sequence[str] = SOURCE_DIRS) -> int:
    """``._*`` files under ``root/<dirs>``: a tree copied from macOS to a volume
    without extended attributes. Tests skip them (tests/source_support.py);
    the count only feeds a warning, nothing is deleted."""
    n = 0
    for d in dirs:
        for _dirpath, _dirnames, filenames in os.walk(os.path.join(root, d)):
            n += sum(1 for f in filenames if f.startswith("._"))
    return n


def normalize(arg: str) -> str:
    """``tests/test_x.py`` / ``tests.test_x`` / ``test_x.Cls.meth`` -> dotted
    name under ``tests`` (``test_x`` or ``test_x.Cls.meth``)."""
    a = arg.strip()
    if not a or len(a.split()) > 1:
        raise ValueError(f"one test module or test id per name, got {arg!r}")
    if a.endswith(".py"):
        a = a[:-3]
    a = a.replace(os.sep, ".").replace("/", ".")
    for package, _folder in TEST_ROOTS:
        if a.startswith(package + "."):
            a = a[len(package) + 1:]
            break
    if not a.startswith("test_"):
        raise ValueError(f"not a test module or test id: {arg!r} (expected test_<area>…)")
    return a


def shard(ids: Sequence[str], chunk: int = CHUNK) -> List[List[str]]:
    """Group test ids by TestCase class; split classes larger than ``chunk``.
    Every id lands in exactly one shard, in the original order."""
    by_class: Dict[str, List[str]] = {}
    for tid in ids:
        by_class.setdefault(tid.rsplit(".", 1)[0], []).append(tid)
    out: List[List[str]] = []
    for members in by_class.values():
        for i in range(0, len(members), chunk):
            out.append(members[i:i + chunk])
    return out


def _shard_label(ids: List[str], index: int, count: int) -> str:
    cls = ids[0].rsplit(".", 1)[0]
    if cls.startswith("tests."):
        cls = cls[len("tests."):]
    return cls if count == 1 else f"{cls}[{index + 1}/{count}]"


def tier_modules(tier: Tier, modules: Iterable[str]) -> List[str]:
    """The discovered modules a tier runs (named modules bypass this)."""
    return [m for m in modules if m not in tier.exclude]


def child_env(base: Dict[str, str], extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """The environment of a job's process (and of the processes it starts).

    The child writes its log in its stdio encoding; it is pinned so the parent
    can read it back (Windows defaults to the locale, cp1252). A host that sets
    ``PYTHONDONTWRITEBYTECODE`` (Claude Code does) makes every child compile
    ``scena`` from source: ~0.7 s of CPU per process, every job and every
    script a job starts. The children cache their bytecode under ``OUT``
    instead, so the tree the host keeps clean gets no ``__pycache__``.
    Pose-revision verify mode is on by default (``SCENA_VERIFY_POSE_REV``).
    """
    env = {**base, "PYTHONIOENCODING": "utf-8", **(extra or {})}
    # Every proxy kept by its pose revision also builds the key and must agree
    # (collision._POSE_REV_VERIFY): a pose writer that forgets bump_pose_rev
    # fails whatever test moves that kind of body (Collision Design, "Pose
    # revision"). ``SCENA_VERIFY_POSE_REV=0`` measures the real skip.
    env.setdefault("SCENA_VERIFY_POSE_REV", "1")
    if env.pop("PYTHONDONTWRITEBYTECODE", None) is not None:
        env.setdefault("PYTHONPYCACHEPREFIX", PYCACHE)
    return env


def tier_env(tier: Tier, profile: Optional[str] = None) -> Dict[str, str]:
    env = {
        "SCENA_HYPOTHESIS_PROFILE": profile or tier.profile,
        "SCENA_CANARIES": "1" if tier.canaries else "0",
    }
    if tier.soak:
        env["SCENA_SOAK"] = "1"
    return env


def plan(tier: Tier, modules: Iterable[str], *,
         list_ids: Callable[[str], List[str]],
         timings: Optional[Dict[str, float]] = None,
         profile: Optional[str] = None) -> List[Job]:
    """Jobs for ``tier`` over ``modules`` (names from ``normalize``), slowest
    first. ``list_ids(module)`` returns the dotted test ids of a SPLIT module."""
    timings = timings or {}
    env = tier_env(tier, profile)
    key = env["SCENA_HYPOTHESIS_PROFILE"]
    jobs: List[Job] = []
    for mod in modules:
        base = mod.split(".", 1)[0]
        if tier.split and mod == base and base in SPLIT:
            groups = shard(list_ids(base))
            by_class: Dict[str, List[List[str]]] = {}
            for g in groups:
                by_class.setdefault(g[0].rsplit(".", 1)[0], []).append(g)
            for members in by_class.values():
                for i, g in enumerate(members):
                    label = _shard_label(g, i, len(members))
                    jobs.append(Job(label, g, dict(env)))
        else:
            jobs.append(Job(mod, [f"{package_of(base)}.{mod}"], dict(env)))
    for job in jobs:
        default = 60.0 if job.label.split(".", 1)[0] in SLOW else 1.0
        job.estimate = timings.get(f"{key}:{job.label}", default)
    jobs.sort(key=lambda j: -j.estimate)
    return jobs


_RAN = re.compile(r"^Ran (\d+) tests? in", re.M)
_STATUS = re.compile(r"^(?:OK|FAILED)\b.*$", re.M)


def parse_output(text: str) -> tuple:
    """(tests ran, final status line) from unittest's output."""
    ran = _RAN.findall(text)
    m = _STATUS.search(text[text.rfind("Ran "):] if ran else text)
    return (int(ran[-1]) if ran else 0, m.group(0).strip() if m else "")


# --------------------------------------------------------------------------
# The child: ``python -m unittest`` plus a leftover check after each module
# --------------------------------------------------------------------------

CHILD = "--child"


def with_leftover_checks(suites: Sequence[unittest.TestSuite], check) -> unittest.TestSuite:
    """``suites`` in order, ``check(module)`` after each run of one module.

    The check is a test of another module, so unittest runs the module's
    ``tearDownModule`` (its sweep) before it. Consecutive names of one module
    (a shard's test ids) share one check: no extra module setup between them.
    """
    out = unittest.TestSuite()
    prev = None
    for suite in suites:
        first = next(iter(_flat(suite)), None)
        module = type(first).__module__ if first is not None else prev
        if prev is not None and module != prev:
            out.addTest(check(prev))
        out.addTest(suite)
        prev = module
    if prev is not None:
        out.addTest(check(prev))
    return out


def _flat(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from _flat(t)
        else:
            yield t


def child_main(argv: Sequence[str]) -> None:
    """``python -m unittest <argv>`` with a ``LeftoverCheck`` after each module
    (tests/leftovers.py)."""
    sys.path[0] = ROOT                  # as ``python -m``: the cwd, not tests/
    from tests import leftovers

    class Loader(unittest.TestLoader):
        def loadTestsFromNames(self, names, module=None):
            suites = [self.loadTestsFromName(n, module) for n in names]
            state = {"at": leftovers.mark()}    # after imports: import-time actors are not counted
            return with_leftover_checks(
                suites, lambda mod: leftovers.LeftoverCheck(mod, state))

    unittest.main(module=None, argv=["python -m unittest", *argv], testLoader=Loader())


# --------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------

def list_ids_subprocess(module: str, env: Optional[Dict[str, str]] = None) -> List[str]:
    """Test ids of ``<package>.<module>`` (generated tests included), loaded in
    a child so this process never imports scena. ``env`` is the tier's
    (``tier_env``): a module may generate other tests at another profile
    (``test_prog_isolation``: every ordered pair at ci, a chain at dev), so the
    ids are listed where the jobs will run them (``ids_lister``)."""
    package = package_of(module)
    code = (
        "import sys, unittest\n"
        f"sys.path.insert(0, {ROOT!r})\n"
        "def walk(s):\n"
        "    for t in s:\n"
        "        yield from (walk(t) if isinstance(t, unittest.TestSuite) else [t])\n"
        f"for t in walk(unittest.defaultTestLoader.loadTestsFromName('{package}.{module}')):\n"
        "    print(t.id())\n"
    )
    p = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                       encoding="utf-8", errors="replace", timeout=600,
                       env=child_env(dict(os.environ), env))
    if p.returncode != 0:
        raise RuntimeError(f"cannot list tests of {module}:\n{p.stderr[-2000:]}")
    return [line for line in p.stdout.splitlines() if line.startswith(package + ".")]


def ids_lister(env: Dict[str, str]) -> Callable[[str], List[str]]:
    """``plan``'s ``list_ids`` for a run whose jobs get ``env``."""
    return lambda module: list_ids_subprocess(module, env)


def _safe(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.\-\[\]]", "_", label).replace("/", "of")


def open_fresh(path: str):
    """Open ``path`` for writing after deleting any old copy. Windows refuses
    ``open(path, "w")`` on an existing Hidden file (a tree copied from macOS
    hides them) and everywhere on a read-only one; deleting first avoids both."""
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except PermissionError:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        os.remove(path)
    return open(path, "w", encoding="utf-8")


LOG_NAME_MAX = 100  # bytes of a log basename; filesystems allow 255 (NAME_MAX)


def log_name(label: str) -> str:
    """``<label>.log`` made filesystem-safe. A label too long for that (many
    modules in one job, a long test id) becomes its first word, the count of
    the rest, and a hash of the whole label: ``test_a-plus27-1f2e3d4c5b.log``.
    Short labels keep their plain name."""
    safe = _safe(label)
    if len(safe) + len(".log") <= LOG_NAME_MAX:
        return safe + ".log"
    words = label.split()
    digest = hashlib.sha1(label.encode("utf-8")).hexdigest()[:10]
    head = _safe(words[0]) if words else safe
    if len(words) > 1:
        head += f"-plus{len(words) - 1}"
    head = head[:LOG_NAME_MAX - len(digest) - len("-.log")]
    return f"{head}-{digest}.log"


class Runner:
    def __init__(self, out_dir: str, timeout: float, workers: int,
                 stream=sys.stdout):
        self.out_dir = out_dir
        self.timeout = timeout
        self.workers = workers
        self.stream = stream
        self._procs: set = set()
        self._lock = threading.Lock()
        self._done = 0
        self._total = 0

    def _run(self, job: Job, extra_args: Sequence[str] = ()) -> Result:
        log = os.path.join(self.out_dir, log_name(job.label))
        env = child_env(dict(os.environ), job.env)
        start = time.time()
        with open_fresh(log) as fh:
            proc = subprocess.Popen([sys.executable, os.path.join(TESTS, "run_tiers.py"), CHILD,
                                     *extra_args, *job.names],
                                    cwd=ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT)
            with self._lock:
                self._procs.add(proc)
            try:
                rc = proc.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                rc = -9
            finally:
                with self._lock:
                    self._procs.discard(proc)
        seconds = time.time() - start
        with open(log, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        ran, status = parse_output(text)
        if rc == -9:
            status = f"TIMEOUT after {self.timeout:.0f} s"
        res = Result(job, seconds, rc, ran, status, log)
        with self._lock:
            self._done += 1
            mark = "ok  " if res.ok else "FAIL"
            print(f"[{self._done:>3}/{self._total}] {seconds:7.1f}s {mark} {job.label}"
                  f"  ({ran} tests{'; ' + status if not res.ok else ''})",
                  file=self.stream, flush=True)
        return res

    def run(self, jobs: List[Job]) -> List[Result]:
        os.makedirs(self.out_dir, exist_ok=True)
        self._total = len(jobs)
        try:
            with ThreadPoolExecutor(self.workers) as ex:
                return list(ex.map(self._run, jobs))
        except KeyboardInterrupt:
            with self._lock:
                for p in self._procs:
                    p.kill()
            raise

    def run_serial(self, env: Dict[str, str]) -> Result:
        self._total += 1
        job = Job("serial:all", serial_names(), env)
        return self._run(job)


def load_timings(path: str) -> Dict[str, float]:
    try:
        with open(path, encoding="utf-8") as fh:
            return {str(k): float(v) for k, v in json.load(fh).items()}
    except (OSError, ValueError):
        return {}


def save_timings(path: str, results: List[Result], profile: str) -> None:
    data = load_timings(path)
    for r in results:
        if r.returncode != -9:
            data[f"{profile}:{r.job.label}"] = round(r.seconds, 2)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open_fresh(path) as fh:
        json.dump(dict(sorted(data.items())), fh, indent=1)


def summarize(results: List[Result], wall: float, stream=sys.stdout) -> bool:
    failed = [r for r in results if not r.ok]
    tests = sum(r.ran for r in results)
    cpu = sum(r.seconds for r in results)
    print(f"\n{len(results)} jobs, {tests} tests, wall {wall:.1f} s "
          f"(sum of job times {cpu:.1f} s)", file=stream)
    slow = sorted(results, key=lambda r: -r.seconds)[:5]
    print("slowest: " + ", ".join(f"{r.job.label} {r.seconds:.0f}s" for r in slow), file=stream)
    for r in failed:
        print(f"\n===== FAILED {r.job.label}: {r.status or 'rc=%d' % r.returncode}"
              f"\n      log: {os.path.relpath(r.log, ROOT)}", file=stream)
        with open(r.log, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
        print("\n".join(lines[-40:]), file=stream)
    print("\nRESULT: " + ("OK" if not failed else f"FAILED ({len(failed)} jobs)"), file=stream)
    return not failed


def main(argv: Optional[Sequence[str]] = None, *, out_root: str = OUT,
         stream=sys.stdout) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tier", choices=sorted(TIERS))
    ap.add_argument("modules", nargs="*",
                    help="test modules or ids (focused: required; other tiers: restrict to these)")
    ap.add_argument("-j", "--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--profile", help="override the tier's Hypothesis profile (e.g. replay)")
    ap.add_argument("--timeout", type=float, help="seconds per job (default: per tier)")
    ap.add_argument("--plan", action="store_true", help="print the jobs and exit")
    ap.add_argument("--sentinel", nargs="?", const="log", choices=("log", "1"),
                    help="run every job under the geometry sentinel (tests/geom_sentinel.py): "
                         "log violations (default) or raise them (1)")
    args = ap.parse_args(argv)

    tier = TIERS[args.tier]
    if args.modules:
        # One argument may hold several names: zsh does not word-split an
        # unquoted $mods, so ``focused $mods`` arrives as "test_a test_b".
        modules = [normalize(m) for arg in args.modules for m in arg.split()]
    elif tier.name == "focused":
        ap.error("focused needs module names, e.g. focused test_shapes")
    else:
        modules = tier_modules(tier, discover_modules())

    out_dir = os.path.join(out_root, tier.name)
    timings_path = os.path.join(out_root, "timings.json")
    env = tier_env(tier, args.profile)
    jobs = plan(tier, modules, list_ids=ids_lister(env),
                timings=load_timings(timings_path), profile=args.profile)
    if args.sentinel:
        jobs = [j for j in jobs if j.label.split(".")[0].split("[")[0] not in SENTINEL_EXCLUDE]
        extra = sentinel_env(args.sentinel)
        env.update(extra)
        for j in jobs:
            j.env.update(extra)
        sys.path.insert(0, os.path.join(ROOT, "tests"))
        import geom_sentinel
        geom_sentinel.clear_logs()
    junk = count_appledouble()
    if junk:
        print(f"warning: {junk} AppleDouble '._*' files (tree copied from macOS); "
              "see tests/README.txt", file=stream, flush=True)
    print(f"tier {tier.name}: {len(jobs)} jobs, {args.jobs} workers, "
          + " ".join(f"{k}={v}" for k, v in env.items()), file=stream, flush=True)
    if args.plan:
        for j in jobs:
            print(f"  ~{j.estimate:6.1f}s  {j.label}", file=stream)
        if tier.serial_pass:
            print(f"  then  serial:all — {len(serial_names())} modules of "
                  f"{', '.join(p for p, _f in TEST_ROOTS)} in one process "
                  "(SCENA_HYPOTHESIS_PROFILE=dev)", file=stream)
        return 0

    runner = Runner(out_dir, args.timeout or tier.timeout, args.jobs, stream)
    start = time.time()
    results = runner.run(jobs)
    save_timings(timings_path, results, env["SCENA_HYPOTHESIS_PROFILE"])
    if tier.serial_pass and not args.modules:
        serial_env = dict(env, SCENA_HYPOTHESIS_PROFILE="dev", SCENA_SOAK="0")
        results.append(runner.run_serial(serial_env))
    ok = summarize(results, time.time() - start, stream)
    if args.sentinel:
        ok = sentinel_summary(stream) and ok
    return 0 if ok else 1


# Modules a sentinel run leaves out: they time engine calls against each other,
# and the sentinel's checks are not free (they recompute after every call).
SENTINEL_EXCLUDE = {
    "test_regular_polygon_perf": "rotate_by cost against n: the sentinel's I-clean recompute is O(n)",
    # They assert engine internals that any observer running engine code moves:
    # I-clean's recompute marks nodes dirty inside its batch and warms Derivates
    # (it restores values, not flags: restoring flags trips I-fast).
    "test_pose_fast_path": "counts mark_dirty calls during a motion",
    "test_pose_link_contract": "counts mark_dirty calls during a motion",
    "test_diff_pose": "asserts Derivates stay cold through engine reads",
}


def sentinel_env(mode: str) -> Dict[str, str]:
    """``SCENA_SENTINEL`` and ``tests/sentinel_site`` first on PYTHONPATH."""
    site = os.path.join(ROOT, "tests", "sentinel_site")
    path = os.pathsep.join(p for p in (site, ROOT, os.environ.get("PYTHONPATH", "")) if p)
    return {"SCENA_SENTINEL": mode, "PYTHONPATH": path}


def sentinel_summary(stream) -> bool:
    """Print the sentinel's distinct violations; False if any is not known."""
    import fnmatch
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    import geom_campaign_known
    import geom_sentinel
    agg = geom_sentinel.report()
    new = {k: a for k, a in agg.items()
           if not any(fnmatch.fnmatch(k, p) for p in geom_campaign_known.SENTINEL)}
    print(f"\nsentinel: {len(agg)} distinct violations, {len(new)} not known", file=stream)
    for k, a in sorted(new.items(), key=lambda kv: -kv[1]["count"]):
        print(f"  {a['count']:6d}  {k}\n          {a['detail'][:160]}\n          {', '.join(a['where'])}",
              file=stream)
    return not new


if __name__ == "__main__":
    if sys.argv[1:2] == [CHILD]:
        child_main(sys.argv[2:])        # exits
    # Failure logs can hold any character; a console redirected to a file on
    # Windows encodes with the locale and errors="strict".
    sys.stdout.reconfigure(errors="backslashreplace")
    sys.exit(main())
