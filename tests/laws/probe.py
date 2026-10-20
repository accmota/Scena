"""Probe runner: an author-shaped game, its stated expectations, and the laws.

``python tests/laws/probe.py <folder> [--out DIR] [-j N] [--only NAME]``

A probe is a pair written by someone playing an author (Testing Design,
"Persona probes"): ``<name>.py``, the game as that author would write it,
untouched, and ``<name>.expect.py``, written before the game ever ran:

* ``PLAY``: input steps, in game seconds (``wait``, ``key_down``, ``key_up``,
  ``tap``, ``hold``, ``key_repeat``, ``click``, ``press``, ``release``,
  ``move``, ``place``, ``drag``, ``scroll``, ``type``; see ``_STEPS``).
* ``CHECKS``: ``(label, seconds | "end", predicate)``; the predicate gets the
  program's namespace as attributes (``lambda g: g.score == 1``).
* optional ``SECONDS`` (game time to run; default: the end of ``PLAY`` plus
  half a second), ``PARAMS``, ``HZ`` (default 60, 30, 144; a run over
  ``LONG`` seconds defaults to 60 alone), ``TIMEOUT`` (wall seconds per run),
  ``LAWS`` (default on, off past ``LONG``), ``MOTION`` (record resolve poses),
  ``EXPECT_ERROR`` (``(type name, what the message should tell the author)``),
  ``MIRROR`` (``{"bodies": lambda g: [...], "keys": {...}}``, with a
  hand-mirrored ``<name>.mirror.py`` next to the probe: equation E11).

Each rate runs in its own process (crashes and hangs stay there) under OS-level
input (``game_harness.GameRun``, ``os_level``) with the laws recorder attached.
Per run: the exception (innermost author and engine frames), the warnings, the
checks, the laws findings not in ``known.KNOWN``, the timed edge events. Across
runs: a check that passes at one rate and fails at another, equation E1 (each
rate's edge events within a frame of the 60 Hz run's), and E11 (the mirrored
game's bodies mirror the game's). A run past its timeout is a HANG, with the
stack where it hung. A run past ``LONG`` seconds samples the live object count
and the wall time per game minute instead of recording laws (growth).

The output is flags, not verdicts: the triage reads each one to its mechanism.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import runpy
import subprocess
import sys
import tempfile
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Sequence

TESTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(TESTS)
ENGINE = os.path.join(ROOT, "scena") + os.sep

RATES = (60, 30, 144)
LONG = 300.0                 # game seconds; past this a run samples growth instead of laws
TAP = 0.1                    # seconds a tap holds its key
CLICK = 0.05                 # seconds a click holds its button
MIRROR_KEYS = {"LEFT": "RIGHT", "RIGHT": "LEFT", "A": "D", "D": "A"}
# A modifier as an author names it in keyp ("SHIFT") is a physical key here.
KEY_ALIASES = {"SHIFT": "LEFT_SHIFT", "CTRL": "LEFT_CTRL", "CONTROL": "LEFT_CTRL",
               "ALT": "LEFT_ALT", "CMD": "LEFT_CMD", "ESCAPE": "ESC", "RETURN": "ENTER"}
POS_BUDGET = 0.5             # DU (equations.POS_BUDGET)


# ---------------------------------------------------------------------------
# The expect file
# ---------------------------------------------------------------------------

def load_expect(path: Optional[str]) -> Dict[str, Any]:
    ns = runpy.run_path(path) if path else {}
    play = list(ns.get("PLAY", []))
    out = {
        "PLAY": play,
        "CHECKS": list(ns.get("CHECKS", [])),
        "PARAMS": dict(ns.get("PARAMS", {})),
        "EXPECT_ERROR": ns.get("EXPECT_ERROR"),
        "MIRROR": ns.get("MIRROR"),
        "MOTION": bool(ns.get("MOTION", False)),
    }
    secs = ns.get("SECONDS")
    out["SECONDS"] = float(secs) if secs is not None else play_length(play) + 0.5
    long = out["SECONDS"] > LONG
    out["HZ"] = tuple(ns.get("HZ", (60,) if long else RATES))
    out["LAWS"] = bool(ns.get("LAWS", not long))
    out["TIMEOUT"] = ns.get("TIMEOUT")
    return out


def play_length(play: Sequence[tuple]) -> float:
    return sum(_duration(st) for st in play)


def _duration(st: tuple) -> float:
    k = st[0]
    if k == "wait":
        return float(st[1])
    if k == "tap":
        return float(st[2]) if len(st) > 2 else TAP
    if k == "hold":
        return float(st[2])
    if k == "click":
        return CLICK
    if k == "drag":
        return float(st[5]) if len(st) > 5 else 0.3
    if k == "type":
        every = float(st[2]) if len(st) > 2 else 0.12
        return every * len(st[1])
    return 0.0


def default_timeout(seconds: float, hz: int, laws: bool) -> float:
    """Wall seconds a run may take: generous per frame (the recorder costs)."""
    return 60.0 + seconds * hz * (0.02 if laws else 0.006)


# ---------------------------------------------------------------------------
# One run (in the child process)
# ---------------------------------------------------------------------------

def _make_run(program: str, params: Dict, hz: int):
    from game_harness import GameRun

    class ProbeRun(GameRun):
        """``GameRun`` (OS level) plus typed characters that have no
        alphanumeric key (a space, punctuation): the char event an OS sends."""

        def type_char(self, ch: str) -> None:
            self._pending.append(("char", (ch,)))

        def _deliver(self, *a) -> None:
            pending, self._pending = self._pending, []
            fw = self.world.fw
            for item in pending:
                if item[0] == "char":
                    fw._handle_char(fw._window, ord(item[1][0]))
                else:
                    self._pending = [item]
                    super()._deliver(*a)
            self._pending = []

    run = ProbeRun(program, params, probes={}, dt=1.0 / hz)
    run.os_level = True
    return run


def _key_of(ch: str) -> Optional[str]:
    if ch == " ":
        return "SPACE"
    if ch.isascii() and ch.isalnum():
        return ch.upper()
    return None


class _Player:
    """Plays ``PLAY`` in game time at one rate, with the checks in between."""

    def __init__(self, run, hz: int, checks, mirror_keys=None):
        self.run, self.hz = run, hz
        self.t = 0.0
        self.frame = 0
        self.checks = sorted(((float(at) if at != "end" else math.inf, i, label, pred)
                              for i, (label, at, pred) in enumerate(checks)), key=lambda c: c[:2])
        self.results: List[Dict[str, Any]] = [None] * len(checks)  # type: ignore[list-item]
        self.mirror_keys = mirror_keys
        self.width = None
        self.on_frame = None

    def _x(self, x: float) -> float:
        if self.mirror_keys is None:
            return x
        if self.width is None:
            self.width = float(self.run.world.fw.design_width)
        return self.width - x

    def _k(self, k: str) -> str:
        k = KEY_ALIASES.get(k.upper(), k)
        if self.mirror_keys is None:
            return k
        return self.mirror_keys.get(k.upper(), k)

    def _check(self, i, label, at, pred):
        try:
            ok = bool(pred(self.run.view))
            self.results[i] = {"label": label, "at": at, "ok": ok, "t": round(self.t, 4)}
        except Exception as e:  # noqa: BLE001
            self.results[i] = {"label": label, "at": at, "ok": False, "t": round(self.t, 4),
                               "read_error": f"{type(e).__name__}: {e}"}

    def advance(self, seconds: float) -> None:
        """Run the frames up to ``t + seconds``, stopping for each check due."""
        end = self.t + seconds
        while self.checks and self.checks[0][0] <= end + 1e-9:
            at, i, label, pred = self.checks.pop(0)
            self._to(at)
            self._check(i, label, at, pred)
        self._to(end)

    def _to(self, t: float) -> None:
        target = int(round(t * self.hz))
        while self.frame < target:
            self.run.step(1)
            self.frame += 1
            if self.on_frame is not None:
                self.on_frame(self.frame / self.hz)
        self.t = max(self.t, t)

    def finish(self) -> None:
        for at, i, label, pred in self.checks:
            self._check(i, label, "end" if at == math.inf else at, pred)
        self.checks = []

    def play(self, steps: Sequence[tuple]) -> None:
        r = self.run
        for st in steps:
            k, args = st[0], st[1:]
            if k == "wait":
                self.advance(float(args[0]))
            elif k in ("key_down", "key_up", "key_repeat"):
                getattr(r, k)(self._k(args[0]))
            elif k == "tap":
                r.key_down(self._k(args[0]))
                self.advance(float(args[1]) if len(args) > 1 else TAP)
                r.key_up(self._k(args[0]))
            elif k == "hold":
                r.key_down(self._k(args[0]))
                self.advance(float(args[1]))
                r.key_up(self._k(args[0]))
            elif k == "click":
                r.press(self._x(args[0]), args[1], *args[2:])
                self.advance(CLICK)
                r.release(*args[2:])
            elif k == "press":
                r.press(self._x(args[0]), args[1], *args[2:])
            elif k == "release":
                r.release(*args)
            elif k in ("move", "place"):
                getattr(r, k)(self._x(args[0]), args[1])
            elif k == "drag":
                x0, y0, x1, y1 = (float(v) for v in args[:4])
                secs = float(args[4]) if len(args) > 4 else 0.3
                n = max(1, int(round(secs * self.hz)))
                r.press(self._x(x0), y0)
                for j in range(1, n + 1):
                    r.move(self._x(x0 + (x1 - x0) * j / n), y0 + (y1 - y0) * j / n)
                    self.advance(secs / n)
                r.release()
            elif k == "scroll":
                r.scroll(0.0, float(args[0]))
            elif k == "type":
                text = args[0]
                every = float(args[1]) if len(args) > 1 else 0.12
                for ch in text:
                    key = _key_of(ch)
                    if key is not None:
                        r.key_down(key)
                        if key == "SPACE":
                            r.type_char(" ")
                    else:
                        r.type_char(ch)
                    self.advance(every / 2)
                    if key is not None:
                        r.key_up(key)
                    self.advance(every / 2)
            else:
                raise ValueError(f"PLAY: unknown step {st!r} (steps: {', '.join(_STEPS)})")


_STEPS = ("wait", "key_down", "key_up", "key_repeat", "tap", "hold", "click", "press",
          "release", "move", "place", "drag", "scroll", "type")


def _where(e: BaseException, program: str) -> Dict[str, Any]:
    """The innermost author frame and the innermost engine frame of ``e``."""
    prog = os.path.normcase(os.path.abspath(program))
    author = engine = None
    innermost = None
    for fs in traceback.extract_tb(e.__traceback__):
        f = os.path.normcase(os.path.abspath(fs.filename))
        if f == prog:
            author = f"{os.path.basename(program)}:{fs.lineno}"
            innermost = "author"
        elif f.startswith(os.path.normcase(ENGINE)):
            engine = f"{os.path.relpath(fs.filename, ROOT)}:{fs.lineno} ({fs.name})"
            innermost = "engine"
    return {"type": type(e).__name__, "module": type(e).__module__,
            "message": str(e)[:2000], "author_line": author, "engine_line": engine,
            "innermost": innermost,
            "traceback": "".join(traceback.format_exception(type(e), e, e.__traceback__))[-4000:]}


def run_once(program: str, expect: Dict[str, Any], hz: int, *, mirror: bool = False,
             track: bool = False) -> Dict[str, Any]:
    """One run of ``program`` at ``hz``: the child process's whole job."""
    import warnings
    import gc
    from laws import model, families
    from laws.attach import attach
    from laws.equations import timed_edges
    from hypothesis_support import registry

    out: Dict[str, Any] = {"hz": hz, "error": None, "phase": None, "warnings": {},
                           "checks": [], "laws": [], "laws_errors": [], "edges": None,
                           "track": None, "growth": None}
    m = expect.get("MIRROR") or {}
    keys = dict(MIRROR_KEYS, **m.get("keys", {})) if mirror else None
    run = _make_run(program, expect["PARAMS"], hz)
    if expect["LAWS"]:
        attach(run, motion=expect["MOTION"])
    player = _Player(run, hz, expect["CHECKS"], keys)
    tracked: Dict[float, list] = {}
    growth: List[Dict[str, Any]] = []
    if track and m.get("bodies") is not None:
        def on_frame(t):
            pts = []
            for b in m["bodies"](run.view):
                c = getattr(b, "center", b)
                pts.append((float(c.x), float(c.y)))
            tracked[round(t, 6)] = pts
        player.on_frame = on_frame
    elif not expect["LAWS"]:
        import time
        t0 = [time.perf_counter(), 0.0]

        def on_frame(t):
            if t - t0[1] >= 60.0 - 1e-9:
                now = time.perf_counter()
                growth.append({"t": round(t, 1), "live": len(registry().live),
                               "gc": len(gc.get_objects()), "wall": round(now - t0[0], 3)})
                t0[0], t0[1] = now, t
        player.on_frame = on_frame
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            out["phase"] = "start"
            run.start()
            out["width"] = float(run.world.fw.design_width)
            out["phase"] = "play"
            player.play(expect["PLAY"])
            player.advance(max(0.0, expect["SECONDS"] - player.t))
            out["phase"] = "checks"
            player.finish()
            out["phase"] = "done"
        except Exception as e:  # noqa: BLE001
            out["error"] = _where(e, program)
            player.finish()
        finally:
            try:
                if run.world is not None:
                    run.close(strict=False)
            except Exception as e:  # noqa: BLE001
                out["close_error"] = f"{type(e).__name__}: {e}"
    for w in caught:
        msg = f"{w.category.__name__}: {w.message}"[:600]
        out["warnings"][msg] = out["warnings"].get(msg, 0) + 1
    out["checks"] = [c for c in player.results if c is not None]
    out["frames"] = player.frame
    if expect["LAWS"] and getattr(run, "laws", None) is not None:
        events = run.laws.events
        out["laws"] = families.unexpected(model.check(events))
        out["laws_errors"] = [str(x)[:300] for x in run.laws.errors[:5]]
        edges, end = timed_edges(events)
        out["edges"] = [[repr(k), v] for k, v in edges.items()]
        out["end"] = end
    if tracked:
        out["track"] = sorted(tracked.items())
    if growth:
        out["growth"] = growth
    return out


def _child(argv: Sequence[str]) -> int:
    program, expect_path, hz, out_path = argv[:4]
    flags = set(argv[4:])
    sys.path[:0] = [ROOT, TESTS]
    import faulthandler
    timeout = float(os.environ.get("SCENA_PROBE_TIMEOUT", "0"))
    if timeout > 3:
        faulthandler.dump_traceback_later(timeout - 2, exit=True)
    expect = load_expect(expect_path if expect_path != "-" else None)
    res = run_once(program, expect, int(hz), mirror="--mirror" in flags,
                   track="--track" in flags)
    import scena
    res["engine"] = os.path.dirname(scena.__file__)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(res, fh)
    return 0


# ---------------------------------------------------------------------------
# One probe (in the parent): rates, E1, E11, flags
# ---------------------------------------------------------------------------

def _stage(program: str, expect_path: Optional[str], tmp: str):
    """A fresh copy of the probe's folder (its files, a link to its
    ``media``) for one run: what a run writes next to the script (a save
    file) must not reach the next rate's run."""
    import shutil
    from source_support import iter_files
    folder = os.path.dirname(program)
    work = os.path.join(tmp, "probe")
    os.makedirs(work)
    for f in iter_files(folder):
        shutil.copy2(f, work)
    media = os.path.join(folder, "media")
    if os.path.isdir(media):
        os.symlink(os.path.realpath(media), os.path.join(work, "media"))
    moved = os.path.join(work, os.path.basename(program))
    exp = os.path.join(work, os.path.basename(expect_path)) if expect_path else None
    return moved, exp


def _spawn(program: str, expect_path: Optional[str], hz: int, timeout: float,
           flags: Sequence[str] = ()) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="probe_") as tmp:
        program, expect_path = _stage(program, expect_path, tmp)
        out = os.path.join(tmp, "out.json")
        env = dict(os.environ, SCENA_PROBE_TIMEOUT=str(timeout), PYTHONDONTWRITEBYTECODE="1",
                   PYTHONIOENCODING="utf-8")
        cmd = [sys.executable, os.path.abspath(__file__), "--child", program,
               expect_path or "-", str(hz), out, *flags]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=timeout + 5, cwd=ROOT, env=env)
            code, so, se = p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired as e:
            code = None
            so = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            se = e.stderr.decode("utf-8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
        if os.path.exists(out):
            with open(out, encoding="utf-8") as fh:
                res = json.load(fh)
        else:
            hang = code is None or "Timeout (" in se or "most recent call first" in se
            res = {"hz": hz, "hang": hang, "exit": code, "error": None}
        res["stdout_tail"] = so[-1500:]
        res["stderr_tail"] = se[-6000:]
        return res


def _hang_stack(stderr: str) -> str:
    """The head of faulthandler's dump: it prints the most recent call first,
    so the author's frame is at the top (a tail cut it off)."""
    i = stderr.rfind("most recent call first")
    return (stderr[i:] if i >= 0 else stderr)[:1500]


def _edges(res):
    if res.get("edges") is None:
        return None
    return {k: v for k, v in res["edges"]}, res.get("end", 0.0)


def run_probe(program: str, expect_path: Optional[str] = None) -> Dict[str, Any]:
    """Every rate of one probe, then the cross-run comparisons; ``flags`` is
    the list a triage reads."""
    from laws.equations import compare_paced
    program = os.path.abspath(program)
    expect = load_expect(expect_path)
    rates = list(expect["HZ"])
    mirror_file = program[:-3] + ".mirror.py"
    mirror = expect["MIRROR"] is not None and os.path.exists(mirror_file)
    runs: Dict[int, Dict[str, Any]] = {}
    for hz in rates:
        t = expect["TIMEOUT"] or default_timeout(expect["SECONDS"], hz, expect["LAWS"])
        flags = ["--track"] if (mirror and hz == 60) else []
        runs[hz] = _spawn(program, expect_path, hz, float(t), flags)
    flags: List[str] = []
    if expect_path is None:
        flags.append("NO-EXPECT: no .expect.py next to the probe")
    for hz, r in runs.items():
        if r.get("hang"):
            flags.append(f"HANG at {hz} Hz: no result in time; stack:\n{_hang_stack(r['stderr_tail'])}")
            continue
        if "frames" not in r and not r.get("hang"):
            flags.append(f"CRASH at {hz} Hz: the run process died (exit {r.get('exit')}):\n"
                         f"{r['stderr_tail'][-1500:]}")
            continue
        e = r.get("error")
        if e:
            flags.append(f"ERROR at {hz} Hz in {r['phase']}: {e['type']} ({e['module']}) "
                         f"innermost {e['innermost']}, author {e['author_line']}, "
                         f"engine {e['engine_line']}: {e['message'][:400]}")
        for c in r.get("checks", []):
            if not c["ok"]:
                why = f" (read error: {c['read_error']})" if "read_error" in c else ""
                flags.append(f"CHECK at {hz} Hz: {c['label']!r} false at t={c['t']}{why}")
        for line in r.get("laws", []):
            flags.append(f"LAWS at {hz} Hz: {line}")
        for line in r.get("laws_errors", []):
            flags.append(f"RECORDER at {hz} Hz: {line}")
        if r.get("close_error"):
            flags.append(f"CLOSE at {hz} Hz: {r['close_error']}")
        if r.get("growth"):
            g = r["growth"]
            if len(g) >= 3 and (g[-1]["live"] > 1.5 * max(1, g[1]["live"])
                                or g[-1]["wall"] > 2.0 * max(1e-3, g[1]["wall"])):
                flags.append(f"GROWTH at {hz} Hz: live objects or wall time per game minute "
                             f"grew: {g[1]} -> {g[-1]}")
    for msg, n in sorted(runs.get(60, next(iter(runs.values()))).get("warnings", {}).items()):
        flags.append(f"WARN ({n}x): {msg}")
    # The same checks at every rate.
    base = runs.get(60)
    if base is not None and "checks" in base:
        b = {c["label"]: c["ok"] for c in base["checks"]}
        for hz, r in runs.items():
            if hz == 60 or "checks" not in r:
                continue
            for c in r["checks"]:
                if c["label"] in b and c["ok"] != b[c["label"]]:
                    flags.append(f"PACE: {c['label']!r} is {b[c['label']]} at 60 Hz, "
                                 f"{c['ok']} at {hz} Hz")
            be, oe = (base.get("error") or {}).get("type"), (r.get("error") or {}).get("type")
            if be != oe:
                flags.append(f"PACE: error {be} at 60 Hz, {oe} at {hz} Hz")
    # E1: edge events within a frame of the 60 Hz run's.
    if base is not None and _edges(base) is not None and not base.get("error"):
        for hz, r in runs.items():
            if hz == 60 or _edges(r) is None or r.get("error"):
                continue
            tol = 1 / 60 + 1 / hz + 1e-6
            for line in compare_paced(_edges(base), _edges(r), tol):
                flags.append(f"E1 at {hz} Hz: {line}")
    # E11: the hand-mirrored game's bodies mirror the game's.
    if mirror and base is not None and base.get("track"):
        mt = float(expect["TIMEOUT"] or default_timeout(expect["SECONDS"], 60, expect["LAWS"]))
        mres = _spawn(mirror_file, expect_path, 60, mt, ["--mirror", "--track"])
        runs["mirror"] = mres
        if mres.get("error") or not mres.get("track"):
            flags.append(f"E11: the mirror run did not finish: {mres.get('error') or mres.get('stderr_tail', '')[-600:]}")
        else:
            width = (expect["MIRROR"] or {}).get("width") or base.get("width")
            flags.extend(_e11(base["track"], mres["track"], float(width)))
    elif expect["MIRROR"] is not None and not mirror:
        flags.append("E11: MIRROR is set but there is no .mirror.py")
    ee = expect["EXPECT_ERROR"]
    if ee:
        got = {(r.get("error") or {}).get("type") for r in runs.values() if isinstance(r, dict)}
        if ee[0] not in got:
            flags.append(f"EXPECT_ERROR: expected {ee[0]} ({ee[1]}), got {sorted(map(str, got))}")
    return {"probe": os.path.basename(program), "expect": expect_path is not None,
            "seconds": expect["SECONDS"], "rates": rates, "flags": flags,
            "runs": {str(k): _slim(v) for k, v in runs.items()}}


def _e11(a, b, width: float) -> List[str]:
    """Body positions of the game and of its mirror (x mapped back about the
    design width, as the runner mirrored the inputs), per frame."""
    ta, tb = dict((t, p) for t, p in a), dict((t, p) for t, p in b)
    worst, where = 0.0, ""
    for t in sorted(set(ta) & set(tb)):
        for i, (pa, pb) in enumerate(zip(ta[t], tb[t])):
            d = math.hypot(pa[0] - (width - pb[0]), pa[1] - pb[1])
            if d > worst:
                worst, where = d, f"body {i} at t={t:.3f}: {pa} vs mirrored {pb}"
    if worst > POS_BUDGET:
        return [f"E11: mirror {worst:.3f} DU apart ({where})"]
    return []


def _slim(r: Dict[str, Any]) -> Dict[str, Any]:
    """A run's record without the bulky edges and track."""
    return {k: v for k, v in r.items() if k not in ("edges", "track")}


# ---------------------------------------------------------------------------
# A folder
# ---------------------------------------------------------------------------

def probes_in(folder: str) -> List[str]:
    from source_support import iter_files
    out = []
    for path in sorted(iter_files(folder, ".py", recursive=False)):
        f = os.path.basename(path)
        if not f.endswith((".expect.py", ".mirror.py")) and not f.startswith(("_", ".")):
            out.append(path)
    return out


def run_folder(folder: str, out_dir: str, *, jobs: int = 4,
               only: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    probes = probes_in(folder)
    if only:
        probes = [p for p in probes if os.path.basename(p)[:-3] in only]

    def one(p):
        e = p[:-3] + ".expect.py"
        try:
            return run_probe(p, e if os.path.exists(e) else None)
        except Exception as ex:  # noqa: BLE001
            return {"probe": os.path.basename(p), "flags": [f"RUNNER: {type(ex).__name__}: {ex}"],
                    "runs": {}, "runner_traceback": traceback.format_exc()}

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        results = list(pool.map(one, probes))
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=1)
    with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8") as fh:
        fh.write(summary(results))
    return results


def summary(results: Sequence[Dict[str, Any]]) -> str:
    lines = ["| Probe | Flags | First flag |", "|---|---|---|"]
    for r in results:
        first = r["flags"][0].splitlines()[0][:160].replace("|", "\\|") if r["flags"] else ""
        lines.append(f"| {r['probe']} | {len(r['flags'])} | {first} |")
    lines.append("")
    for r in results:
        if not r["flags"]:
            continue
        lines.append(f"## {r['probe']}")
        lines.append("")
        for f in r["flags"]:
            lines.append("- " + f.replace("\n", "\n  "))
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--child":
        return _child(argv[1:])
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folder")
    ap.add_argument("--out", default=None, help="results folder (default: <folder>/_results)")
    ap.add_argument("-j", "--jobs", type=int, default=4)
    ap.add_argument("--only", nargs="*", help="probe names (no .py)")
    a = ap.parse_args(argv)
    sys.path[:0] = [ROOT, TESTS]
    out = a.out or os.path.join(a.folder, "_results")
    results = run_folder(a.folder, out, jobs=a.jobs, only=a.only)
    flagged = sum(1 for r in results if r["flags"])
    print(f"{len(results)} probes, {flagged} flagged; {os.path.join(out, 'summary.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
