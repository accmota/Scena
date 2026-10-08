"""Scheduler isolate — move_along, tween, after/every, @when/@on_change, handles.

Peels the process + event cluster off cpu_mix (no collision, no sprites, no FX).
Each ``--mode`` stresses one axis; ``mix`` is the regular pulse.

Usage
-----
    python scripts/bench/sched.py
    python scripts/bench/sched.py --bench --mode mix
    python scripts/bench/sched.py --bench --mode ride --n 200 --face
    python scripts/bench/sched.py --bench --suite
    python scripts/bench/sched.py --bench --mode mix --repeats 3
    python scripts/bench/sched.py --bench --mode timers --ladder 50,200,400
    python scripts/bench/sched.py --bench --mode mix --profile --duration 2

See ``scripts/bench/sched.md``.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_MODES = ("ride", "tween", "timers", "when", "process", "mix")
_MODE_DEFAULT_N = {
    "ride": 200,
    "tween": 150,
    "timers": 200,
    "when": 200,
    "process": 80,
    "mix": 120,
}
# Frozen suite sizes (protocol sched-1). Independent of --n.
_SUITE = (
    ("ride", 200),
    ("tween", 150),
    ("timers", 200),
    ("when", 200),
    ("process", 80),
    ("mix", 120),
)
# mix proportions (sum 120 at the pulse N).
_MIX_WEIGHTS = ("ride", 36), ("tween", 28), ("timers", 24), ("when", 20), ("process", 12)

_parser = argparse.ArgumentParser(description=__doc__)
_parser.add_argument("--mode", choices=_MODES, default="mix",
                     help="isolate axis (default mix = regular pulse)")
_parser.add_argument("--n", type=int, default=None,
                     help="body count (default depends on --mode)")
_parser.add_argument("--bench", action="store_true",
                     help="uncapped FPS, phase-time, then exit")
_parser.add_argument("--duration", type=float, default=2.0,
                     help="measured seconds when --bench (default 2)")
_parser.add_argument("--warmup", type=float, default=0.5,
                     help="warmup seconds excluded from stats (default 0.5)")
_parser.add_argument("--ladder", type=str, default=None,
                     help="comma-separated N values; overrides --n")
_parser.add_argument("--suite", action="store_true",
                     help="run every isolate mode at frozen N, then mix")
_parser.add_argument("--repeats", type=int, default=1,
                     help="fresh processes; print median (default 1)")
_parser.add_argument("--seed", type=int, default=42)
_parser.add_argument("--face", action="store_true",
                     help="ride mode: face=True on every rider (mix: all rides, not 1/4)")
_parser.add_argument("--tracks", choices=("shared", "unique"), default="shared",
                     help="ride tracks: one path many riders, or a path per rider")
_parser.add_argument("--hide", action="store_true",
                     help="visible=False — peel draw_ms off work_ms")
_parser.add_argument("--no-readout", action="store_true",
                     help="skip per-frame Handle.elapsed/remaining walk")
_parser.add_argument("--tight", action="store_true",
                     help="shorter timer / when intervals (ceiling probe)")
_parser.add_argument("--profile", action="store_true",
                     help="with --bench, also print cProfile top functions")
_parser.add_argument("--json", dest="json_path", default=None)
_parser.add_argument(
    "--pulse", action="store_true",
    help="protocol snapshot: mix median of 3 + suite single-shot; append sched.md",
)
_parser.add_argument(
    "--no-append", action="store_true",
    help="with --pulse, print markdown only; do not write sched.md",
)
args, _ = _parser.parse_known_args()

if args.n is None:
    args.n = _MODE_DEFAULT_N[args.mode]
args.n = max(1, int(args.n))
args.repeats = max(1, int(args.repeats))

_BENCH = os.path.dirname(os.path.abspath(__file__))
_WORKER = os.environ.get("SCHED_WORKER")
if _BENCH not in sys.path:
    sys.path.insert(0, _BENCH)

from harness import (  # noqa: E402
    average_phase_stats,
    empty_phase_stats,
    install_phase_run,
    parse_ladder,
    print_phase_report,
    write_json,
)
from fingerprint import script_hashes  # noqa: E402
from pulse import (  # noqa: E402
    append_pulse,
    autodiff,
    latest_scena_fingerprint,
    now_meta,
    parse_leading_float,
    parse_summary_table,
    print_autodiff_banner,
)


def _worker_cmd(**overrides) -> List[str]:
    cmd = [
        sys.executable, os.path.abspath(__file__),
        "--bench",
        "--mode", str(overrides.get("mode", args.mode)),
        "--n", str(overrides.get("n", args.n)),
        "--duration", str(args.duration),
        "--warmup", str(args.warmup),
        "--seed", str(args.seed),
        "--tracks", args.tracks,
        "--repeats", "1",
    ]
    if args.face:
        cmd.append("--face")
    if args.hide:
        cmd.append("--hide")
    if args.no_readout:
        cmd.append("--no-readout")
    if args.tight:
        cmd.append("--tight")
    return cmd


def _parse_result_line(text: str) -> Optional[Dict[str, Any]]:
    for line in (text or "").splitlines():
        if line.startswith("RESULT_JSON:"):
            payload = line.split(":", 1)[1].strip()
            return json.loads(payload)
    return None


def _run_worker(**overrides) -> Dict[str, Any]:
    env = dict(os.environ)
    env["SCHED_WORKER"] = "1"
    cmd = _worker_cmd(**overrides)
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    print(out, end="" if out.endswith("\n") else "\n")
    row = _parse_result_line(out)
    if row is None:
        return {
            "mode": overrides.get("mode", args.mode),
            "n": overrides.get("n", args.n),
            "ok": False,
            "returncode": proc.returncode,
        }
    row["ok"] = proc.returncode == 0
    return row


def _median_bundle(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    ok = [r for r in rows if r.get("ok") and "work_ms" in r]
    if not ok:
        return {"ok": False, "repeats": len(rows)}
    keys = (
        "fps", "work_ms", "tick_ms", "coll_ms", "flush_ms", "draw_ms",
        "submit_ms", "present_ms", "handles", "events", "rides",
        "every_hz", "after_hz", "when_hz", "tween_hz", "exit_hz",
    )
    out = dict(ok[0])
    out["repeats"] = len(ok)
    for k in keys:
        vals = [float(r[k]) for r in ok if k in r and r[k] is not None]
        if not vals:
            continue
        out[k] = statistics.median(vals)
        out[f"{k}_min"] = min(vals)
        out[f"{k}_max"] = max(vals)
        med = out[k]
        out[f"{k}_spread_pct"] = (
            0.0 if med == 0 else 100.0 * (max(vals) - min(vals)) / abs(med)
        )
    return out


def _print_median(label: str, bundle: Dict[str, Any]) -> None:
    print("=" * 60)
    print(label)
    print("=" * 60)
    if not bundle.get("ok"):
        print("No successful repeats.")
        print("=" * 60)
        return
    work = bundle["work_ms"]
    spread = bundle.get("work_ms_spread_pct", 0.0)
    print(f"repeats:             {bundle.get('repeats', 1)} (median)")
    print(f"work_ms:             {work:.3f}  "
          f"({bundle.get('work_ms_min', work):.3f}–"
          f"{bundle.get('work_ms_max', work):.3f}, ±{spread:.0f}%)")
    print(f"Average FPS:         {bundle.get('fps', 0.0):.1f}")
    print(f"  tick_ms:           {bundle.get('tick_ms', 0.0):.3f}")
    print(f"  flush_ms:          {bundle.get('flush_ms', 0.0):.3f}")
    print(f"  draw_ms:           {bundle.get('draw_ms', 0.0):.3f}")
    print(f"  coll_ms:           {bundle.get('coll_ms', 0.0):.3f}")
    print(f"handles:             {bundle.get('handles', 0):.0f}")
    print(f"events:              {bundle.get('events', 0):.0f}")
    print("=" * 60)


def _print_suite_table(rows: Sequence[Dict[str, Any]]) -> None:
    print("\n=== sched suite summary ===")
    print(f"{'mode':<10} {'n':>5} {'work_ms':>8} {'tick':>8} {'flush':>8} "
          f"{'draw':>8} {'fps':>8} {'handles':>8} {'events':>7}")
    print("-" * 78)
    for r in rows:
        if not r.get("ok"):
            print(f"{str(r.get('mode', '?')):<10} {'FAIL':>5}")
            continue
        print(
            f"{r['mode']:<10} {int(r['n']):>5} {r['work_ms']:8.3f} "
            f"{r['tick_ms']:8.3f} {r['flush_ms']:8.3f} {r['draw_ms']:8.3f} "
            f"{r['fps']:8.1f} {r.get('handles', 0):8.0f} {r.get('events', 0):7.0f}"
        )
    print("=" * 78)


def _fmt_phase_sched(bundle: Dict[str, Any]) -> str:
    parts = []
    for key, short in (("tick_ms", "t"), ("flush_ms", "f"), ("draw_ms", "d")):
        v = bundle.get(key)
        if v is None:
            continue
        parts.append(f"{short}{v:.2f}")
    return " ".join(parts)


def _render_sched_pulse(
    *,
    mix: Dict[str, Any],
    suite: Sequence[Dict[str, Any]],
    meta: Dict[str, Any],
    script_fp: Dict[str, str],
) -> Tuple[str, str]:
    host_s = meta["host_s"]
    date = meta["date"]
    work = mix.get("work_ms", float("nan"))
    fps = mix.get("fps", float("nan"))
    spread = mix.get("work_ms_spread_pct", 0.0)
    ride = next((r for r in suite if r.get("mode") == "ride"), {})
    suite_note = ""
    if ride.get("ok") and "tick_ms" in ride:
        suite_note = f"ride tick **{ride['tick_ms']:.2f}** (n={int(ride.get('n', 0))}) is the heavy cell"
    row = (
        f"| {date} | `sched-1` | {host_s} | "
        f"{work:.3f} ({fps:.1f}) `{_fmt_phase_sched(mix)}` | "
        f"{suite_note} | |"
    )
    hash_s = " · ".join(f"`{k}` `{v}`" for k, v in script_fp.items())
    mix_spread = f" ±{spread:.0f}%" if spread >= 1.0 else ""
    suite_lines = [
        "| mode | n | work_ms | tick_ms | flush_ms | draw_ms | fps | handles | events |",
        "|------|--:|--------:|--------:|---------:|--------:|----:|--------:|-------:|",
    ]
    for r in suite:
        if not r.get("ok"):
            suite_lines.append(
                f"| {r.get('mode', '?')} | {r.get('n', '')} | FAIL | | | | | | |"
            )
            continue
        suite_lines.append(
            f"| {r['mode']} | {int(r['n'])} | {r['work_ms']:.3f} | "
            f"{r['tick_ms']:.3f} | {r['flush_ms']:.3f} | {r['draw_ms']:.3f} | "
            f"{r['fps']:.1f} | {r.get('handles', 0):.0f} | {r.get('events', 0):.0f} |"
        )
    wmin = mix.get("work_ms_min", work)
    wmax = mix.get("work_ms_max", work)
    section = "\n".join([
        f"### {date} — sched-1",
        "",
        "| | |",
        "|---|---|",
        f"| When | {meta['when']} |",
        f"| Protocol | `sched-1` |",
        f"| Host | {host_s} |",
        f"| Git | {meta['git']} |",
        f"| Scena | `{meta['scena_fingerprint']}` |",
        f"| Repeats | mix {mix.get('repeats', 3)} (median); suite single-shot |",
        f"| Scripts | {hash_s} |",
        "",
        "Frozen argv as in the protocol table. Window = design size via the phase harness; FB follows the display scale (2× on Retina) and is not recorded.",
        "",
        "#### mix (median of 3)",
        "",
        "| Metric | Median | min–max | spread |",
        "|--------|------:|--------:|-------:|",
        f"| work_ms | **{work:.3f}** | {wmin:.3f}–{wmax:.3f} | {mix_spread.strip() or '—'} |",
        f"| FPS | {fps:.1f} | | |",
        f"| tick_ms | {mix.get('tick_ms', float('nan')):.3f} | | |",
        f"| flush_ms | {mix.get('flush_ms', float('nan')):.3f} | | |",
        f"| draw_ms | {mix.get('draw_ms', float('nan')):.3f} | | |",
        f"| coll_ms | {mix.get('coll_ms', float('nan')):.3f} | | |",
        f"| handles | {mix.get('handles', float('nan')):.0f} | | |",
        f"| events | {mix.get('events', float('nan')):.0f} | | |",
        "",
        "#### suite (single-shot)",
        "",
        *suite_lines,
        "",
    ])
    return row, section


def _run_sched_pulse() -> None:
    log_path = Path(_BENCH) / "sched.md"
    meta = now_meta()
    hashes = script_hashes(("sched.py", "harness.py"), Path(_BENCH))
    print(
        f"=== sched pulse  mix repeats=3 + suite  "
        f"stage={meta['scena_fingerprint']} ===",
        flush=True,
    )
    print(f"\n>> mix n=120 repeats=3", flush=True)
    shots = [_run_worker(mode="mix", n=_MODE_DEFAULT_N["mix"]) for _ in range(3)]
    mix = _median_bundle(shots)
    mix["mode"] = "mix"
    mix["n"] = _MODE_DEFAULT_N["mix"]
    _print_median("sched mix n=120", mix)

    summary: List[Dict[str, Any]] = []
    for mode, n in _SUITE:
        print(f"\n>> mode={mode} n={n}", flush=True)
        row = _run_worker(mode=mode, n=n)
        row["mode"] = mode
        row["n"] = n
        summary.append(row)
    _print_suite_table(summary)

    md_row, section = _render_sched_pulse(
        mix=mix, suite=summary, meta=meta, script_fp=hashes,
    )
    prev_text = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
    prev_rows = parse_summary_table(prev_text)
    prev_metrics = None
    for cells in prev_rows:
        if len(cells) < 4:
            continue
        proto = cells[1].strip().strip("`")
        if proto != "sched-1":
            continue
        work = parse_leading_float(cells[3])
        if work is not None:
            prev_metrics = {"mix_work_ms": work}
            break
    prev_fp = latest_scena_fingerprint(prev_text) if prev_text else None
    same: Optional[bool]
    if prev_fp and meta["scena_fingerprint"]:
        same = prev_fp == meta["scena_fingerprint"]
    else:
        same = None
    warnings = autodiff(
        {"mix_work_ms": float(mix.get("work_ms", float("nan")))},
        prev_metrics,
        same_scena=same,
        prev_label="last sched-1 row",
    )
    print_autodiff_banner(warnings, same_scena=same)
    print("\n" + "=" * 60)
    print("sched pulse")
    print("=" * 60)
    print(section)
    if not args.no_append:
        append_pulse(log_path, md_row, section)
        print(f"appended {log_path}")
        try:
            from dashboard import refresh as refresh_dashboard
            refresh_dashboard()
        except Exception as exc:
            print(f"(dashboard refresh skipped: {exc})")


# -- parent: suite / ladder / repeats (no Scena window) ----------------------
if not _WORKER and args.pulse:
    args.bench = True
    _run_sched_pulse()
    sys.exit(0)

if not _WORKER and (args.suite or args.ladder or args.repeats > 1):
    args.bench = True
    if args.suite:
        print(
            f"=== sched suite  duration={args.duration}s  warmup={args.warmup}s  "
            f"repeats={args.repeats}  tracks={args.tracks} ===",
            flush=True,
        )
        summary: List[Dict[str, Any]] = []
        for mode, n in _SUITE:
            print(f"\n>> mode={mode} n={n}", flush=True)
            shots = [_run_worker(mode=mode, n=n) for _ in range(args.repeats)]
            bundle = _median_bundle(shots) if args.repeats > 1 else shots[0]
            if args.repeats > 1:
                _print_median(f"sched {mode} n={n}", bundle)
            bundle["mode"] = mode
            bundle["n"] = n
            summary.append(bundle)
        _print_suite_table(summary)
        sys.exit(0)

    if args.ladder:
        ns = parse_ladder(args.ladder)
        print(
            f"=== sched ladder  mode={args.mode} n={ns}  "
            f"duration={args.duration}s ===",
            flush=True,
        )
        summary = []
        for n in ns:
            print(f"\n>> n={n}", flush=True)
            shots = [_run_worker(n=n) for _ in range(args.repeats)]
            bundle = _median_bundle(shots) if args.repeats > 1 else shots[0]
            if args.repeats > 1:
                _print_median(f"sched {args.mode} n={n}", bundle)
            bundle["mode"] = args.mode
            bundle["n"] = n
            summary.append(bundle)
        _print_suite_table(summary)
        sys.exit(0)

    # repeats > 1, single mode
    print(
        f"=== sched repeats={args.repeats}  mode={args.mode} n={args.n} ===",
        flush=True,
    )
    shots = [_run_worker() for _ in range(args.repeats)]
    bundle = _median_bundle(shots)
    _print_median(f"sched {args.mode} n={args.n}", bundle)
    print(
        f"RESULT_JSON: {json.dumps({k: bundle.get(k) for k in ('mode', 'n', 'fps', 'work_ms', 'tick_ms', 'flush_ms', 'draw_ms', 'coll_ms', 'handles', 'events', 'ok')})}"
    )
    sys.exit(0)


# -- worker / interactive: build the scene -----------------------------------
from scena import *  # noqa: E402
from scena.events import get_global_event_system  # noqa: E402
from scena.orchestration import ScenaFramework  # noqa: E402
from scena.process import get_scheduler, set_watchdog  # noqa: E402

W, H = 1000, 700
init(width=W, height=H, title=f"Bench — sched {args.mode} n={args.n}")
canvas.background = (0.05, 0.06, 0.09)
set_fx_auto(False)
canvas.fx_quality = "medium"
set_watchdog(False)
canvas.framerate = "max"

EVERY_IVL = 0.03 if args.tight else 0.05
AFTER_IVL = 0.06 if args.tight else 0.12
WHEN_RATE = 420.0 if args.tight else 280.0  # heat/s; threshold 70

COUNTERS = {
    "every": 0,
    "after": 0,
    "when": 0,
    "tween": 0,
    "exit": 0,
    "update": 0,
}


def _mix_counts(n: int) -> Dict[str, int]:
    weights = [w for _, w in _MIX_WEIGHTS]
    names = [k for k, _ in _MIX_WEIGHTS]
    total = sum(weights)
    parts = [int(n * w / total) for w in weights]
    parts[-1] += n - sum(parts)
    i = len(parts) - 1
    while parts[-1] < 0 and i > 0:
        steal = min(parts[i - 1], -parts[-1])
        parts[i - 1] -= steal
        parts[-1] += steal
        i -= 1
    return {name: max(0, p) for name, p in zip(names, parts)}


def _slots(n: int, x0: float, x1: float, y0: float, y1: float) -> List[Tuple[float, float]]:
    if n <= 0:
        return []
    span_x = max(1.0, x1 - x0)
    span_y = max(1.0, y1 - y0)
    cols = max(1, int(math.ceil(math.sqrt(n * span_x / span_y))))
    rows = max(1, (n + cols - 1) // cols)
    out: List[Tuple[float, float]] = []
    i = 0
    for r in range(rows):
        for c in range(cols):
            if i >= n:
                return out
            x = x0 + span_x * (c + 0.5) / cols
            y = y0 + span_y * (r + 0.5) / rows
            out.append((x, y))
            i += 1
    return out


def _maybe_hide(body) -> None:
    if args.hide:
        body.visible = False


def _inventory() -> Dict[str, float]:
    sched = get_scheduler()
    events = get_global_event_system()
    tweens = list(getattr(sched, "_tween", []) or [])
    rides = sum(1 for h in tweens if getattr(h, "_ride", None) is not None)
    return {
        "handles": float(len(getattr(sched, "_handles", []) or [])),
        "every": float(len(getattr(sched, "_every", []) or [])),
        "once": float(len(getattr(sched, "_once", []) or [])),
        "tween": float(len(tweens)),
        "rides": float(rides),
        "await": float(len(getattr(sched, "_await_family", []) or [])),
        "scripts": float(len(getattr(sched, "_scripts", []) or [])),
        "events": float(len(getattr(events, "_events", []) or [])),
        "updates": float(len(getattr(sched, "_update_dense", []) or [])),
        "modes": float(len(getattr(sched, "_mode_dense", []) or [])),
    }


# -- roles -------------------------------------------------------------------

class Rider(Circle):
    """Forever move_along. Shared or unique Track; optional face=."""

    def setup(self):
        self.collidable = False


class Tweener(Circle):
    """Ping-pong pose tweens (center + rotation + radius). Handle churn via on_done."""

    def setup(self):
        self.collidable = False
        self.home = (float(self.center.x), float(self.center.y))
        self.r0 = float(self.radius)
        self._arm_move()
        self._arm_spin()
        self._arm_pulse()

    def _arm_move(self):
        x0, y0 = self.home
        dx, dy = 36.0, 22.0
        ease = ("linear", "ease_in_out", "ease_out", "quad")[int(x0) % 4]

        def there():
            COUNTERS["tween"] += 1
            self.move_to(x0 + dx, y0 + dy, time=0.45, ease=ease, on_done=back)

        def back():
            COUNTERS["tween"] += 1
            self.move_to(x0, y0, time=0.45, ease=ease, on_done=there)

        there()

    def _arm_spin(self):
        def spin():
            COUNTERS["tween"] += 1
            self.rotate_by(150, time=0.55, ease="linear", on_done=spin)

        spin()

    def _arm_pulse(self):
        lo, hi = max(4.0, self.r0 * 0.7), self.r0 * 1.45

        def up():
            COUNTERS["tween"] += 1
            self.tween(self["radius"], hi, time=0.4, ease="ease_in_out", on_done=down)

        def down():
            COUNTERS["tween"] += 1
            self.tween(self["radius"], lo, time=0.4, ease="ease_in_out", on_done=up)

        up()


class Timer(Circle):
    """Named every + named after re-arm (replace slot).

    Re-arm ``after`` from ``on_update``, not from the fire callback. ``_once``
    is a live list: appending during ``_tick_once`` with ``dt >= delay``
    (first-frame stall) would spin forever in one tick.
    """

    def setup(self):
        self.collidable = False
        self.n = 0
        self._hop = None
        self.every(EVERY_IVL, self.pulse, name="pulse")

    def pulse(self):
        COUNTERS["every"] += 1
        self.n += 1
        self.radius = 6.0 + (self.n % 2) * 3.0

    def _hop_fire(self):
        COUNTERS["after"] += 1

    def on_update(self, dt):
        h = self._hop
        if h is not None:
            _ = h.remaining
            _ = h.elapsed
        if h is None or h.done or h.cancelled:
            self._hop = self.after(AFTER_IVL, self._hop_fire, name="hop")


class Watcher(Circle):
    """on_update ramps ink; @when / @on_change poll on flush."""

    def setup(self):
        self.collidable = False
        self.heat = 0.0
        self.hits = 0

    def on_update(self, dt):
        COUNTERS["update"] += 1
        self.heat = float(self.heat) + dt * WHEN_RATE
        if float(self.heat) > 140.0:
            self.heat = 0.0

    @when(lambda self: float(self.heat) >= 70.0)
    def on_hot(self):
        COUNTERS["when"] += 1
        self.hits += 1
        self.heat = 0.0
        self.set_color("white")
        self.after(0.05, self._restore, name="restore")

    def _restore(self):
        self.set_color("tomato")

    @on_change(lambda self: int(float(self.heat)) // 20)
    def on_band(self, value):
        pass


class Actor(Circle):
    """Modes + async wait/until/parallel/race + mode-scoped every."""

    def setup(self):
        self.collidable = False
        self.home = (float(self.center.x), float(self.center.y))
        self._gate = True
        self.mode = self.patrol

    def on_update(self, dt):
        COUNTERS["update"] += 1

    def _open(self):
        self._gate = True

    @on_mode
    def patrol(self):
        self.every(0.18, lambda: self.rotate_by(18), name="spin")
        self.after(0.55, then=self.dash)

    @exit_mode(patrol)
    def leave_patrol(self):
        COUNTERS["exit"] += 1

    @on_mode
    async def dash(self):
        x0, y0 = self.home
        await parallel(
            self.move_to(x0 + 26, y0 + 16, time=0.2, ease="ease_out"),
            self.rotate_by(110, time=0.2),
        )
        self._gate = False
        self.after(0.06, self._open)
        await until(lambda: self._gate)
        await race(wait(0.08), wait(0.28))
        await self.move_to(x0, y0, time=0.2, ease="ease_in")
        self.mode = self.patrol


COLORS = {
    "ride": "cyan",
    "tween": "orchid",
    "timers": "gold",
    "when": "tomato",
    "process": "sea green",
}


def _make_shared_tracks() -> List[Track]:
    c1 = Track.circle(center=(220, 480), radius=95)
    eight = Track.eight(width=150, height=64)
    rail = Track(points=[(620, 220), (920, 520)], smooth=0)
    rail.zigzag(amount=18, waves=5)
    star = Track.star(points=5, radius=70, center=(780, 480))
    return [c1, eight, rail, star]


def _spawn_riders(n: int, slots: Sequence[Tuple[float, float]]) -> None:
    if n <= 0:
        return
    face_all = bool(args.face)
    if args.tracks == "unique":
        for i, (x, y) in enumerate(slots[:n]):
            r = Rider(center=(x, y), radius=7, color=COLORS["ride"])
            _maybe_hide(r)
            path = Track.circle(center=(x, y), radius=22 + (i % 5) * 3)
            r.move_along(
                path, time=1.6 + (i % 5) * 0.15, loops="forever",
                face=face_all or (i % 4 == 0),
            )
        return
    tracks = _make_shared_tracks()
    for i, (x, y) in enumerate(slots[:n]):
        r = Rider(center=(x, y), radius=7, color=COLORS["ride"])
        _maybe_hide(r)
        path = tracks[i % len(tracks)]
        r.move_along(
            path,
            time=2.0 + (i % 7) * 0.12,
            loops="forever",
            phase=(i / max(1, n)),
            face=face_all or (i % 4 == 0),
        )


def _spawn_role(kind: str, n: int, slots: Sequence[Tuple[float, float]]) -> None:
    if n <= 0:
        return
    if kind == "ride":
        _spawn_riders(n, slots)
        return
    cls = {"tween": Tweener, "timers": Timer, "when": Watcher, "process": Actor}[kind]
    color = COLORS[kind]
    for x, y in slots[:n]:
        body = cls(center=(x, y), radius=8, color=color)
        _maybe_hide(body)


def _bands_for(kinds: Sequence[str]) -> List[Tuple[str, float, float]]:
    """Vertical bands, top → bottom, one per populated role."""
    k = len(kinds)
    top, bot = 80.0, 40.0
    usable = H - top - bot
    out = []
    for i, kind in enumerate(kinds):
        y1 = H - top - usable * i / k
        y0 = H - top - usable * (i + 1) / k
        out.append((kind, y0, y1))
    return out


counts = _mix_counts(args.n) if args.mode == "mix" else {args.mode: args.n}
populated = [k for k, c in counts.items() if c > 0]
margin_x = 50.0
for kind, y0, y1 in _bands_for(populated):
    _spawn_role(kind, counts[kind], _slots(counts[kind], margin_x, W - margin_x, y0, y1))


director = Entity()
if not args.no_readout:
    def _handle_readout(e, dt):
        sched = get_scheduler()
        acc = 0.0
        for h in sched._handles:
            acc += h.remaining
            acc += h.elapsed
        e._readout_sink = acc

    director.on_update = _handle_readout


hud = None
if not args.bench and not args.hide:
    hud = Text(
        text="",
        top_left=(16, H - 9), font_size=16,
        color=Color(0.75, 0.8, 0.88, 1),
    )


def update(dt):
    if hud is None:
        return
    inv = _inventory()
    hud.text = (
        f"{args.mode} n={args.n}  handles={inv['handles']:.0f}  "
        f"rides={inv['rides']:.0f}  every={inv['every']:.0f}  "
        f"tween={inv['tween']:.0f}  events={inv['events']:.0f}  "
        f"when={COUNTERS['when']}"
    )


# -- bench loop --------------------------------------------------------------
if args.bench:
    import cProfile
    from io import StringIO
    import pstats

    fw = ScenaFramework.get_instance()
    stats = empty_phase_stats()
    extra = {
        "handles": 0.0, "rides": 0.0, "events": 0.0, "every": 0.0,
        "tween": 0.0, "once": 0.0, "await": 0.0, "scripts": 0.0,
        "n_frames": 0.0,
    }
    _recording_started = {"done": False}

    def on_frame(framework, recording):
        if not recording:
            return
        if not _recording_started["done"]:
            for k in COUNTERS:
                COUNTERS[k] = 0
            _recording_started["done"] = True
        inv = _inventory()
        extra["handles"] += inv["handles"]
        extra["rides"] += inv["rides"]
        extra["events"] += inv["events"]
        extra["every"] += inv["every"]
        extra["tween"] += inv["tween"]
        extra["once"] += inv["once"]
        extra["await"] += inv["await"]
        extra["scripts"] += inv["scripts"]
        extra["n_frames"] += 1.0

    install_phase_run(
        fw,
        duration=args.duration,
        warmup=args.warmup,
        stats=stats,
        on_frame=on_frame,
    )

    def _report():
        print_phase_report(f"sched {args.mode} n={args.n} — phase timing", stats)
        avg = average_phase_stats(stats)
        nf = max(1.0, extra["n_frames"])
        handles = extra["handles"] / nf
        rides = extra["rides"] / nf
        events = extra["events"] / nf
        dur = max(1e-6, args.duration)
        every_hz = COUNTERS["every"] / dur
        after_hz = COUNTERS["after"] / dur
        when_hz = COUNTERS["when"] / dur
        tween_hz = COUNTERS["tween"] / dur
        exit_hz = COUNTERS["exit"] / dur
        print(f"mode:                {args.mode}")
        print(f"n:                   {args.n}  tracks={args.tracks}  "
              f"face={bool(args.face)}  hide={bool(args.hide)}")
        print(f"avg handles:         {handles:.1f}  "
              f"(every {extra['every'] / nf:.1f}  tween {extra['tween'] / nf:.1f}  "
              f"rides {rides:.1f}  once {extra['once'] / nf:.1f}  "
              f"await {extra['await'] / nf:.1f})")
        print(f"avg events:          {events:.1f}")
        print(f"avg scripts:         {extra['scripts'] / nf:.2f}")
        print(f"fires / s:           every {every_hz:.0f}  after {after_hz:.0f}  "
              f"when {when_hz:.0f}  tween-done {tween_hz:.0f}  exit {exit_hz:.0f}")
        print(f"avg work_ms:         {avg['work_ms']:.3f}")
        payload = {
            "ok": True,
            "mode": args.mode,
            "n": args.n,
            "seed": args.seed,
            "tracks": args.tracks,
            "face": bool(args.face),
            "hide": bool(args.hide),
            "tight": bool(args.tight),
            "fps": avg["fps"],
            "work_ms": avg["work_ms"],
            "tick_ms": avg["tick_ms"],
            "coll_ms": avg["coll_ms"],
            "flush_ms": avg["flush_ms"],
            "draw_ms": avg["draw_ms"],
            "submit_ms": avg["submit_ms"],
            "present_ms": avg["present_ms"],
            "frames": avg["frames"],
            "handles": handles,
            "rides": rides,
            "events": events,
            "every_hz": every_hz,
            "after_hz": after_hz,
            "when_hz": when_hz,
            "tween_hz": tween_hz,
            "exit_hz": exit_hz,
        }
        print(
            "RESULT_JSON: "
            + json.dumps(
                {k: payload[k] for k in (
                    "ok", "mode", "n", "fps", "work_ms", "tick_ms", "flush_ms",
                    "draw_ms", "coll_ms", "handles", "events", "rides",
                    "every_hz", "after_hz", "when_hz", "tween_hz",
                )}
            )
        )
        if args.json_path:
            payload["phases"] = avg
            payload["counts"] = counts
            write_json(args.json_path, payload)
        return avg

    if args.profile:
        pr = cProfile.Profile()
        pr.enable()
        run()
        pr.disable()
        _report()
        buf = StringIO()
        pstats.Stats(pr, stream=buf).sort_stats("cumulative").print_stats(40)
        print(buf.getvalue())
        buf2 = StringIO()
        pstats.Stats(pr, stream=buf2).sort_stats("tottime").print_stats(25)
        print("--- tottime ---")
        print(buf2.getvalue())
    else:
        run()
        _report()
else:
    run()
