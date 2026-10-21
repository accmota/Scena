#!/usr/bin/env python3
"""game_bench.py — time a whole game in the **real** run loop.

Runs any game script unmodified (an example, a ``scripts/bench/games/`` game)
and times the product frame: ``ScenaFramework._simulate_frame`` /
``_draw_frame`` and the subsystems they call are wrapped in place, never
re-implemented (``harness.install_phase_run`` is a replica loop that drifted
from the product frame: no clip settle, Endless refill, bounds, hover or
pointer resync). Pacing is uncapped (``canvas.framerate = "max"``), FX Auto
off; everything else is the game's own.

    python scripts/bench/game_bench.py examples/ninja_4_perigos.py
    python scripts/bench/game_bench.py scripts/bench/games/horda.py --params n=400
    python scripts/bench/game_bench.py scripts/bench/games/horda.py --ladder n=50,150,400,1000
    python scripts/bench/game_bench.py examples/ninja_3_nivel.py --cull ab
    python scripts/bench/game_bench.py scripts/bench/games/mundo.py --profile 40

Report (ms per recorded frame): ``work`` (simulate + draw + submit: the CPU
frame, before the present wait), its p50 / p95 / p99 / max, the phases, the
collision step's own sub-phases (``CollisionSystem.last_stats``), query calls
and their time, objects drawn / culled, the framebuffer scale, RSS and the
load average (peers load this machine: compare runs at a similar load).
``x4`` is the work time on a machine four times slower (the target).

``--params k=v,k=v`` reaches the game as ``PARAMS`` (like ``tests/games``).
``--ladder k=v1,v2`` runs one fresh process per value. ``--cull ab`` flips
``canvas.cull_offscreen`` every ``--block`` frames and reports both sides.
``--set module:NAME=value`` sets a switch before the game is built (a
process-level A/B, for switches whose effect is cached). ``--ab module:FLAG`` flips a private bool switch the same way (an in-process
A/B of one optimization: ``ab_on`` / ``ab_off``). ``--profile N`` adds cProfile (top N by own time, then own time per file).
``--json`` writes the result; the last stdout line is ``RESULT_JSON: {...}``.
"""
from __future__ import annotations

import argparse
import cProfile
import json
import os
import pstats
import runpy
import subprocess
import sys
import time
from array import array
from typing import Any, Callable, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

pc = time.perf_counter

# Collision query entry points (CollisionSystem methods); nested calls are
# counted once, at the outermost one.
QUERY_METHODS = ("floor_below", "query_shape", "query_point", "query_circle",
                 "query_sector", "raycast", "test_collision")
# Module functions the frame body calls by global name (scena/orchestration.py).
ORCH_FUNCS = {
    "tick_processes": "processes",
    "settle_clip_ends": "clip_ends",
    "refill_after_tick": "endless",
    "sample_level_sources": "audio_levels",
    "tick_all_transients": "transients",
    "tick_all_histories": "histories",
    "tick_cover": "cover",
    "tick_all_spatial_fx": "spatial_fx",
}
COLL_KEYS = ("ms_snapshot", "ms_broad", "ms_narrow", "ms_resolve", "ms_bounds",
             "proxy_pairs", "narrow", "fast", "swept")


def parse_params(text: Optional[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not text:
        return out
    for part in text.split(","):
        if not part.strip():
            continue
        k, _, v = part.partition("=")
        v = v.strip()
        for conv in (int, float):
            try:
                out[k.strip()] = conv(v)
                break
            except ValueError:
                continue
        else:
            out[k.strip()] = {"true": True, "false": False}.get(v.lower(), v)
    return out


def pct(values: array, q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


class Side:
    """Accumulators for one side of the run (all frames, or cull on / off)."""

    def __init__(self) -> None:
        self.frames = 0
        self.work = array("d")
        self.frame = array("d")
        self.ph: Dict[str, float] = {}
        self.coll: Dict[str, float] = {}
        self.q_n: Dict[str, int] = {}
        self.q_ms: Dict[str, float] = {}
        self.kept = 0
        self.skipped = 0

    def summary(self) -> Dict[str, Any]:
        n = max(1, self.frames)
        work_mean = sum(self.work) / n if self.work else 0.0
        frame_mean = sum(self.frame) / max(1, len(self.frame)) if self.frame else 0.0
        out: Dict[str, Any] = {
            "frames": self.frames,
            "fps": 1000.0 / frame_mean if frame_mean > 0 else 0.0,
            "frame_ms": frame_mean,
            "work_ms": work_mean,
            "work_p50": pct(self.work, 0.50),
            "work_p95": pct(self.work, 0.95),
            "work_p99": pct(self.work, 0.99),
            "work_max": max(self.work) if self.work else 0.0,
            "x4_ms": 4.0 * work_mean,
            "phases": {k: v / n for k, v in sorted(self.ph.items(), key=lambda kv: -kv[1])},
            "collision": {k: v / n for k, v in self.coll.items()},
            "queries": {k: {"per_frame": self.q_n[k] / n, "ms": self.q_ms.get(k, 0.0) / n}
                        for k in sorted(self.q_n, key=lambda k: -self.q_ms.get(k, 0.0))},
            "drawn": self.kept / n,
            "culled": self.skipped / n,
        }
        return out


class Recorder:
    def __init__(self, args) -> None:
        self.args = args
        self.t_first: Optional[float] = None
        self.recording = False
        self.done = False
        self.sides: Dict[str, Side] = {}
        self.cur: Dict[str, float] = {}
        self.q_cur_n: Dict[str, int] = {}
        self.q_cur_ms: Dict[str, float] = {}
        self.q_depth = 0
        self.sim_start = 0.0
        self.wait_start: Optional[float] = None
        self.draw_end = 0.0
        self.last_side: Optional[str] = None
        self.rec_frame = 0
        self.prof: Optional[cProfile.Profile] = cProfile.Profile() if args.profile else None
        self.rss0 = self.rss1 = float("nan")
        self.fw = None
        self.fb = None
        self.t_rec0 = self.t_rec1 = 0.0
        self.ab_target = None
        self.ab_default = None
        if args.ab:
            import importlib
            modname, _, attr = args.ab.partition(":")
            mod = importlib.import_module(modname)
            if not hasattr(mod, attr):
                raise SystemExit(f"--ab: {modname} has no {attr}")
            self.ab_target = (mod, attr)
            self.ab_default = getattr(mod, attr)

    # -- wrappers ------------------------------------------------------------

    def timed(self, name: str, fn: Callable) -> Callable:
        cur = self.cur

        def wrapper(*a, **kw):
            t = pc()
            try:
                return fn(*a, **kw)
            finally:
                cur[name] = cur.get(name, 0.0) + (pc() - t)
        wrapper.__wrapped__ = fn
        return wrapper

    def query_wrapper(self, name: str, fn: Callable) -> Callable:
        rec = self

        def wrapper(*a, **kw):
            if rec.q_depth:
                return fn(*a, **kw)
            rec.q_depth = 1
            t = pc()
            try:
                return fn(*a, **kw)
            finally:
                rec.q_depth = 0
                rec.q_cur_n[name] = rec.q_cur_n.get(name, 0) + 1
                rec.q_cur_ms[name] = rec.q_cur_ms.get(name, 0.0) + (pc() - t)
        wrapper.__wrapped__ = fn
        return wrapper

    # -- install -------------------------------------------------------------

    def install(self) -> None:
        import scena.orchestration as orch
        from scena.collision import CollisionSystem
        from scena.orchestration import ScenaFramework

        rec = self
        for fname, label in ORCH_FUNCS.items():
            fn = getattr(orch, fname, None)
            if fn is not None:
                setattr(orch, fname, self.timed(label, fn))
        orig_cb = orch.callback_if_exists

        def callback_if_exists(obj, name, *a, **kw):
            if name != "update":
                return orig_cb(obj, name, *a, **kw)
            t = pc()
            try:
                return orig_cb(obj, name, *a, **kw)
            finally:
                rec.cur["update"] = rec.cur.get("update", 0.0) + (pc() - t)
        orch.callback_if_exists = callback_if_exists
        for m in QUERY_METHODS:
            fn = getattr(CollisionSystem, m, None)
            if fn is not None:
                setattr(CollisionSystem, m, self.query_wrapper(m, fn))
        C = ScenaFramework
        C._step_hover = self.timed("hover", C._step_hover)
        C._draw_background = self.timed("background", C._draw_background)
        orig_sim, orig_draw = C._simulate_frame, C._draw_frame

        def _simulate_frame(fw, *a, **kw):
            rec.frame_start(fw)
            if rec.done:
                return None
            t = pc()
            orig_sim(fw, *a, **kw)
            rec.cur["simulate"] = pc() - t
            cs = fw.collision_system
            st = getattr(cs, "last_stats", None) if cs is not None else None
            rec.coll_now = dict(st) if st else None
            return None

        def _draw_frame(fw, *a, **kw):
            t = pc()
            r = orig_draw(fw, *a, **kw)
            rec.draw_end = pc()
            rec.cur["draw_frame"] = rec.draw_end - t
            return r
        C._simulate_frame = _simulate_frame
        C._draw_frame = _draw_frame
        self.coll_now = None

    def first_frame(self, fw) -> None:
        """Late patches: objects that exist only once the window is open."""
        from scena import canvas, set_fx_auto
        from scena.orchestration import get_bounds_system, get_scena_system

        self.fw = fw
        set_fx_auto(False)
        canvas.framerate = "max"
        if self.args.cull in ("on", "off"):
            canvas.cull_offscreen = self.args.cull == "on"
        cs = fw.collision_system
        if cs is not None:
            cs.step = self.timed("collision", cs.step)
        bs = get_bounds_system()
        bs.step = self.timed("bounds", bs.step)
        ss = get_scena_system()
        if ss is not None:
            ss.flush = self.timed("flush", ss.flush)
        sd = fw._scena_draw
        sd.draw = self.timed("scene_draw", sd.draw)
        wm = getattr(fw, "widget_manager", None)
        if wm is not None:
            wm.draw = self.timed("widgets", wm.draw)
        pacer = fw._pacer
        orig_wait = pacer.wait_for_present
        rec = self

        def wait_for_present(*a, **kw):
            rec.wait_start = pc()
            return orig_wait(*a, **kw)
        pacer.wait_for_present = wait_for_present
        try:
            self.fb = (int(fw.fb_width), int(fw.fb_height), int(fw.width), int(fw.height))
        except Exception:
            self.fb = None

    # -- per frame -----------------------------------------------------------

    def frame_start(self, fw) -> None:
        now = pc()
        if self.t_first is None:
            self.t_first = now
            self.first_frame(fw)
        else:
            self.close_frame(now)
        if self.done:
            return
        el = now - self.t_first
        a = self.args
        if not self.recording and el >= a.warmup:
            self.recording = True
            self.t_rec0 = now
            from frame_probe import current_rss_mb
            self.rss0 = current_rss_mb()
            if self.prof is not None:
                self.prof.enable()
        if self.recording and el >= a.warmup + a.seconds:
            if self.prof is not None:
                self.prof.disable()
            from frame_probe import current_rss_mb
            self.rss1 = current_rss_mb()
            self.t_rec1 = now
            self.recording = False
            self.done = True
            fw._running = False
            return
        if self.recording and a.cull == "ab":
            from scena import canvas
            on = (self.rec_frame // a.block) % 2 == 0
            canvas.cull_offscreen = on
        if a.ab:
            mod, attr = self.ab_target
            on = self.recording and (self.rec_frame // a.block) % 2 == 0
            setattr(mod, attr, on if self.recording else self.ab_default)
        self.sim_start = now
        self.wait_start = None
        self.cur.clear()
        self.q_cur_n.clear()
        self.q_cur_ms.clear()
        self.last_side = self.side_name() if self.recording else None
        if self.recording:
            self.rec_frame += 1

    def side_name(self) -> str:
        if self.args.ab:
            mod, attr = self.ab_target
            return "ab_on" if getattr(mod, attr) else "ab_off"
        if self.args.cull == "ab":
            from scena import canvas
            return "cull_on" if canvas.cull_offscreen else "cull_off"
        return "all"

    def close_frame(self, now: float) -> None:
        name = self.last_side
        if name is None:
            return
        side = self.sides.setdefault(name, Side())
        work_end = self.wait_start if self.wait_start is not None else self.draw_end
        side.frames += 1
        side.work.append(1000.0 * (work_end - self.sim_start))
        side.frame.append(1000.0 * (now - self.sim_start))
        for k, v in self.cur.items():
            side.ph[k] = side.ph.get(k, 0.0) + 1000.0 * v
        if self.wait_start is not None:
            side.ph["submit"] = side.ph.get("submit", 0.0) + 1000.0 * (self.wait_start - self.draw_end)
            side.ph["present"] = side.ph.get("present", 0.0) + 1000.0 * (now - self.wait_start)
        st = self.coll_now
        if st:
            for k in COLL_KEYS:
                if k in st:
                    side.coll[k] = side.coll.get(k, 0.0) + float(st[k])
        for k, v in self.q_cur_n.items():
            side.q_n[k] = side.q_n.get(k, 0) + v
            side.q_ms[k] = side.q_ms.get(k, 0.0) + 1000.0 * self.q_cur_ms.get(k, 0.0)
        sd = self.fw._scena_draw if self.fw is not None else None
        if sd is not None:
            side.kept += int(getattr(sd, "_cull_kept", 0) or 0)
            side.skipped += int(getattr(sd, "_cull_skipped", 0) or 0)

    # -- report --------------------------------------------------------------

    def report(self, script: str, params: Dict[str, Any]) -> Dict[str, Any]:
        from fingerprint import scena_fingerprint
        out: Dict[str, Any] = {
            "script": os.path.relpath(script, REPO),
            "params": params,
            "seconds": self.args.seconds,
            "cull": self.args.cull,
            "ab": self.args.ab,
            "fb": self.fb,
            "rss_mb": [round(self.rss0, 1), round(self.rss1, 1)],
            "load": [round(x, 2) for x in os.getloadavg()],
            "scena_fingerprint": scena_fingerprint(),
            "sides": {k: v.summary() for k, v in self.sides.items()},
        }
        if self.prof is not None:
            out["profile_by_file"] = profile_by_file(self.prof, max(1, sum(
                s.frames for s in self.sides.values())))
        return out


def profile_by_file(prof: cProfile.Profile, frames: int) -> Dict[str, float]:
    st = pstats.Stats(prof)
    by: Dict[str, float] = {}
    for (fname, _line, _fn), (_cc, _nc, tt, _ct, _callers) in st.stats.items():
        if "/scena/scena/" in fname:
            key = "scena/" + fname.split("/scena/scena/", 1)[1]
        elif fname.startswith("~") or fname.startswith("<"):
            key = "builtins/C"
        elif "site-packages" in fname:
            key = "lib/" + fname.split("site-packages/", 1)[1].split("/", 1)[0]
        elif "/scena/" in fname:
            key = os.path.relpath(fname, REPO)
        else:
            key = "python/" + os.path.basename(fname)
        by[key] = by.get(key, 0.0) + tt
    return {k: 1000.0 * v / frames for k, v in sorted(by.items(), key=lambda kv: -kv[1])}


def print_report(rep: Dict[str, Any]) -> None:
    fb = rep.get("fb")
    fbs = f"fb {fb[0]}x{fb[1]} ({fb[0] / max(1, fb[2]):.0f}x)" if fb else "fb ?"
    print(f"\n=== {rep['script']}  params={rep['params']}  {fbs}  load {rep['load']}"
          f"  rss {rep['rss_mb'][0]}→{rep['rss_mb'][1]} MiB")
    for name, s in rep["sides"].items():
        print(f"--- {name}: {s['frames']} frames  {s['fps']:.0f} fps  frame {s['frame_ms']:.3f} ms")
        print(f"    work {s['work_ms']:.3f} ms  (p50 {s['work_p50']:.3f}  p95 {s['work_p95']:.3f}"
              f"  p99 {s['work_p99']:.3f}  max {s['work_max']:.2f})  x4 ≈ {s['x4_ms']:.1f} ms")
        print(f"    drawn {s['drawn']:.0f}  culled {s['culled']:.0f}")
        print("    phases (ms/frame): " + "  ".join(
            f"{k} {v:.3f}" for k, v in s["phases"].items() if v >= 0.0005))
        if s["collision"]:
            print("    collision.step: " + "  ".join(
                (f"{k[3:]} {v:.3f}" if k.startswith("ms_") else f"#{k} {v:.1f}")
                for k, v in s["collision"].items()))
        if s["queries"]:
            print("    queries: " + "  ".join(
                f"{k} {q['per_frame']:.1f}/f {q['ms']:.3f} ms" for k, q in s["queries"].items()))
    prof = rep.get("profile_by_file")
    if prof:
        print("--- own time by file (ms/frame, under cProfile):")
        for k, v in list(prof.items())[:18]:
            print(f"    {v:7.3f}  {k}")


def harness_cwd(script: str) -> Optional[str]:
    """``# harness: cwd=<dir>`` on the first lines (the bench games keep their
    art in ``examples/media``, like ``tests/games``), or None."""
    with open(script, encoding="utf-8") as fh:
        for _ in range(5):
            line = fh.readline()
            if line.startswith("# harness: cwd="):
                return os.path.join(REPO, line.split("=", 1)[1].strip())
    return None


def apply_sets(sets) -> Dict[str, Any]:
    """``--set module:NAME=value`` before the game is built (process-level A/B)."""
    import importlib
    done: Dict[str, Any] = {}
    for item in sets or ():
        target, _, raw = item.partition("=")
        modname, _, attr = target.partition(":")
        mod = importlib.import_module(modname)
        if not hasattr(mod, attr):
            raise SystemExit(f"--set: {modname} has no {attr}")
        value = parse_params(f"v={raw}")["v"]
        setattr(mod, attr, value)
        done[target] = value
    return done


def run_one(args, params: Dict[str, Any]) -> Dict[str, Any]:
    script = os.path.abspath(args.script)
    import scena  # noqa: F401
    sets = apply_sets(args.set)
    rec = Recorder(args)
    import scena  # noqa: F401  (bootstraps the framework singleton)
    rec.install()
    os.chdir(harness_cwd(script) or os.path.dirname(script))
    sys.path.insert(0, os.path.dirname(script))
    old_argv = sys.argv
    sys.argv = [script]
    try:
        runpy.run_path(script, init_globals={"PARAMS": dict(params)}, run_name="__main__")
    except SystemExit:
        pass
    finally:
        sys.argv = old_argv
        os.chdir(REPO)
    if not rec.done:
        print("game_bench: the game ended before the recorded window was over", file=sys.stderr)
    rep = rec.report(script, params)
    rep["set"] = sets
    if rec.prof is not None and args.profile:
        st = pstats.Stats(rec.prof)
        st.sort_stats("tottime").print_stats(args.profile)
    return rep


def run_ladder(args) -> int:
    key, _, values = args.ladder.partition("=")
    base = parse_params(args.params)
    rows = []
    for v in [x for x in values.split(",") if x.strip()]:
        params = dict(base)
        params.update(parse_params(f"{key}={v}"))
        cmd = [sys.executable, os.path.abspath(__file__), args.script,
               "--params", ",".join(f"{k}={val}" for k, val in params.items()),
               "--seconds", str(args.seconds), "--warmup", str(args.warmup),
               "--cull", args.cull, "--block", str(args.block)]
        p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
        line = next((ln for ln in reversed(p.stdout.splitlines())
                     if ln.startswith("RESULT_JSON: ")), None)
        if line is None:
            print(f"{key}={v}: failed\n{p.stderr[-2000:]}", file=sys.stderr)
            continue
        rep = json.loads(line[len("RESULT_JSON: "):])
        print_report(rep)
        rows.append((v, rep))
    print(f"\nladder {key}: {args.script}")
    print(f"{key:>8} {'work':>8} {'p95':>8} {'x4':>7} {'fps':>7}  top phases")
    for v, rep in rows:
        for name, s in rep["sides"].items():
            top = "  ".join(f"{k} {x:.2f}" for k, x in list(s["phases"].items())[:4])
            tag = "" if name == "all" else f" [{name}]"
            print(f"{v:>8} {s['work_ms']:>8.3f} {s['work_p95']:>8.3f} {s['x4_ms']:>7.1f}"
                  f" {s['fps']:>7.0f}  {top}{tag}")
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as fh:
            json.dump([{"value": v, "report": r} for v, r in rows], fh, indent=1)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("script")
    p.add_argument("--params", default="")
    p.add_argument("--seconds", type=float, default=10.0)
    p.add_argument("--warmup", type=float, default=3.0)
    p.add_argument("--ladder", default=None, help="key=v1,v2,... (one process per value)")
    p.add_argument("--cull", choices=("game", "on", "off", "ab"), default="game",
                   help="game: leave the game's own setting")
    p.add_argument("--block", type=int, default=60, help="frames per side with --cull ab")
    p.add_argument("--ab", default=None, metavar="MODULE:FLAG",
                   help="flip a private bool switch every --block frames (in-process A/B), "
                        "e.g. scena.collision:_FLOOR_PROBE_FAST")
    p.add_argument("--set", action="append", default=[], metavar="MODULE:NAME=VALUE",
                   help="set a private switch before the game is built (repeatable)")
    p.add_argument("--profile", type=int, default=0, metavar="N")
    p.add_argument("--json", dest="json_path", default=None)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.ladder:
        return run_ladder(args)
    params = parse_params(args.params)
    rep = run_one(args, params)
    print_report(rep)
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, indent=1)
            fh.write("\n")
    print("RESULT_JSON: " + json.dumps(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
