"""
app_fx_auto_stress.py — stress + instrument the FX Auto quality ladder.

Loads N multipass / glow shapes. Motion is plain Python (no Attribute
formulas, no @= links) so the reactive graph is not the bottleneck.

Usage
-----
    python scripts/app_fx_auto_stress.py
    python scripts/app_fx_auto_stress.py --n 80 --auto
    python scripts/app_fx_auto_stress.py --scenario ramp_up --auto --log /tmp/auto.csv
    python scripts/app_fx_auto_stress.py --scenario low_probe --heavy --auto --n-max 600
    python scripts/app_fx_auto_stress.py --list-scenarios

Keys (interactive; ignored while a scenario drives N)
----
    [ / ] or - / =   change N (±step, clamped)
    A                 toggle FX Auto
    1 / 2 / 3         force quality low / medium / high (disables Auto)
    S                 toggle sparse SpatialFx campfires
    L                 write a log marker
    Ctrl+Shift+2/3/4  framework Auto / quality / framerate
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # repo root

from scena import (
    init,
    run,
    canvas,
    keyp,
    set_fx_auto,
    Circle,
    Line,
    Neon,
    Laser,
    ElectricField,
    Gel,
    Rim,
    Bolt,
    Glow,
    GlowFilter,
    Vignette,
    Grain,
    Bloom,
    Fire,
    Text,
    Color,
)
from scena.orchestration import ScenaFramework
from scena.fx_auto import AutoParams, budget_ms

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
_SCENARIO_HELP = """\
Scenarios (timeline of N / spatial / markers):
  ramp_up      start low → ramp to n-max → hold
  ramp_down    start n-max → ramp to low → hold
  stabilize    ramp up, then hold mid for long settle
  sawtooth     repeated up/down (oscillation bait)
  edge_hunt    binary-ish search for high↔medium border, then sit
  edge_jiggle  after border find, ±small N to provoke med↔high flips
  low_probe    aggressive load (high N + heavy + spatial) to reach low@30
               (survival rung; ladder holds low@60 first)
  fps_align    settle at several fixed N plateaus; check FPS vs target
  manual       interactive only (no auto timeline)
"""

parser = argparse.ArgumentParser(
    description=__doc__,
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog=_SCENARIO_HELP,
)
parser.add_argument("--n", type=int, default=40, help="starting shape count")
parser.add_argument(
    "--n-max", type=int, default=500,
    help="max shapes (default 500; raise to reach low on fast machines)",
)
parser.add_argument("--n-min", type=int, default=5)
parser.add_argument("--n-step", type=int, default=5, help="manual key step")
parser.add_argument(
    "--quality", default="high", choices=("low", "medium", "high", "max"),
)
parser.add_argument("--auto", action="store_true", help="enable Auto from start")
parser.add_argument("--spatial", action="store_true", help="start with campfires on")
parser.add_argument(
    "--heavy",
    action="store_true",
    help="unique multipass looks + more campfires (stress harder)",
)
parser.add_argument("--width", type=int, default=1200)
parser.add_argument("--height", type=int, default=800)
parser.add_argument(
    "--scenario", default="manual",
    help="load timeline (see --list-scenarios)",
)
parser.add_argument("--list-scenarios", action="store_true")
parser.add_argument(
    "--log", default="",
    help="CSV path for instrumentation (default: scripts/_fx_auto_stress.csv "
         "when --scenario != manual)",
)
parser.add_argument(
    "--log-hz", type=float, default=10.0,
    help="metric sample rate (Hz); 0 = every frame",
)
parser.add_argument(
    "--summary-json", default="",
    help="write end-of-run summary JSON (scenarios auto-exit)",
)
parser.add_argument(
    "--t-up", type=float, default=None,
    help="override AutoParams.t_up_s (harder up if larger)",
)
parser.add_argument(
    "--cooldown", type=float, default=None,
    help="override both cooldown_down_s and cooldown_up_s",
)
parser.add_argument(
    "--k-up", type=float, default=None,
    help="override AutoParams.k_up (harder up if smaller)",
)
args, _ = parser.parse_known_args()

_N_MIN = max(1, int(args.n_min))
_N_MAX = max(_N_MIN, int(args.n_max))
_N_STEP = max(1, int(args.n_step))

# ---------------------------------------------------------------------------
# Scenario timeline
# ---------------------------------------------------------------------------
@dataclass
class Step:
    """One timeline action. ``at`` is seconds since scenario start."""

    at: float
    op: str  # set_n | ramp_n | spatial | marker | hold_end | quit
    n: Optional[int] = None
    n_end: Optional[int] = None
    duration: float = 0.0
    on: Optional[bool] = None
    note: str = ""


@dataclass
class Scenario:
    name: str
    steps: List[Step]
    description: str = ""


def _sc_ramp_up(n0: int, n1: int) -> Scenario:
    return Scenario(
        "ramp_up",
        [
            Step(0.0, "set_n", n=n0, note="start"),
            Step(2.0, "ramp_n", n=n0, n_end=n1, duration=25.0, note="ramp"),
            Step(27.0, "hold_end", duration=20.0, note="hold peak"),
            Step(47.0, "quit", note="done"),
        ],
        "Ramp N up then hold at peak",
    )


def _sc_ramp_down(n0: int, n1: int) -> Scenario:
    return Scenario(
        "ramp_down",
        [
            Step(0.0, "set_n", n=n1, note="start peak"),
            Step(3.0, "ramp_n", n=n1, n_end=n0, duration=25.0, note="ramp down"),
            Step(28.0, "hold_end", duration=15.0, note="hold low"),
            Step(43.0, "quit", note="done"),
        ],
        "Start high N, ramp down, hold",
    )


def _sc_stabilize(n0: int, n_mid: int, n1: int) -> Scenario:
    return Scenario(
        "stabilize",
        [
            Step(0.0, "set_n", n=n0),
            Step(2.0, "ramp_n", n=n0, n_end=n1, duration=18.0, note="ramp"),
            Step(20.0, "set_n", n=n_mid, note="settle mid"),
            Step(20.0, "hold_end", duration=35.0, note="long settle"),
            Step(55.0, "quit"),
        ],
        "Ramp, then long hold at mid N",
    )


def _sc_sawtooth(n_lo: int, n_hi: int) -> Scenario:
    steps: List[Step] = [Step(0.0, "set_n", n=n_lo, note="saw start")]
    t = 2.0
    for i in range(4):
        steps.append(Step(t, "ramp_n", n=n_lo, n_end=n_hi, duration=8.0, note=f"up{i}"))
        t += 8.0
        steps.append(Step(t, "hold_end", duration=4.0, note=f"peak{i}"))
        t += 4.0
        steps.append(Step(t, "ramp_n", n=n_hi, n_end=n_lo, duration=8.0, note=f"dn{i}"))
        t += 8.0
        steps.append(Step(t, "hold_end", duration=4.0, note=f"valley{i}"))
        t += 4.0
    steps.append(Step(t, "quit"))
    return Scenario("sawtooth", steps, "Repeated up/down load cycles")


def _sc_edge_hunt(n0: int, n1: int) -> Scenario:
    """Coarse then fine N steps around the high↔medium decision region.

    Script does not know the border a priori; it walks N up until Auto has
    had time to react, then jiggles. Pair with --auto and inspect the log.
    """
    steps: List[Step] = [Step(0.0, "set_n", n=n0, note="edge start")]
    t = 3.0
    # Coarse climb
    n = n0
    while n < n1:
        n = min(n1, n + max(10, (n1 - n0) // 8))
        steps.append(Step(t, "set_n", n=n, note=f"coarse->{n}"))
        t += 8.0
    # Fine walk back down
    while n > n0:
        n = max(n0, n - max(5, _N_STEP))
        steps.append(Step(t, "set_n", n=n, note=f"fine->{n}"))
        t += 6.0
    steps.append(Step(t, "hold_end", duration=12.0, note="edge hold"))
    steps.append(Step(t + 12.0, "quit"))
    return Scenario("edge_hunt", steps, "Walk N to find high↔medium border")


def _sc_edge_jiggle(n_lo: int, n_hi: int) -> Scenario:
    mid = (n_lo + n_hi) // 2
    steps: List[Step] = [
        Step(0.0, "set_n", n=mid, note="jiggle mid"),
        Step(8.0, "hold_end", duration=5.0),
    ]
    t = 13.0
    amp = max(_N_STEP, (n_hi - n_lo) // 20)
    for i in range(10):
        steps.append(Step(t, "set_n", n=mid + amp, note=f"+amp {i}"))
        t += 5.0
        steps.append(Step(t, "set_n", n=mid - amp, note=f"-amp {i}"))
        t += 5.0
    steps.append(Step(t, "quit"))
    return Scenario(
        "edge_jiggle",
        steps,
        "Alternate N around a mid point to bait oscillation",
    )


def _sc_low_probe(n1: int) -> Scenario:
    return Scenario(
        "low_probe",
        [
            Step(0.0, "spatial", on=True, note="spatial on"),
            Step(0.0, "set_n", n=min(80, n1), note="warm"),
            Step(3.0, "ramp_n", n=min(80, n1), n_end=n1, duration=20.0),
            Step(23.0, "hold_end", duration=40.0, note="hold for low"),
            Step(63.0, "quit"),
        ],
        "Max load + spatial; try to reach low@30 (via low@60)",
    )


def _sc_fps_align(n_levels: Sequence[int]) -> Scenario:
    steps: List[Step] = []
    t = 0.0
    for n in n_levels:
        steps.append(Step(t, "set_n", n=int(n), note=f"plateau n={n}"))
        t += 2.0
        steps.append(Step(t, "hold_end", duration=14.0, note=f"measure n={n}"))
        t += 14.0
    steps.append(Step(t, "quit"))
    return Scenario(
        "fps_align",
        steps,
        "Plateaus at several N; compare measured FPS to Auto target",
    )


def build_scenarios() -> dict:
    n0 = max(_N_MIN, min(_N_MAX, 30))
    n1 = _N_MAX
    n_mid = max(n0, min(n1, (n0 + n1) // 2))
    levels = sorted({
        n0,
        max(n0, n_mid // 2),
        n_mid,
        min(n1, n_mid + (n1 - n_mid) // 2),
        n1,
    })
    return {
        "manual": Scenario("manual", [], "Interactive only"),
        "ramp_up": _sc_ramp_up(n0, n1),
        "ramp_down": _sc_ramp_down(n0, n1),
        "stabilize": _sc_stabilize(n0, n_mid, n1),
        "sawtooth": _sc_sawtooth(n0, min(n1, max(n0 + 40, n_mid))),
        "edge_hunt": _sc_edge_hunt(n0, n1),
        "edge_jiggle": _sc_edge_jiggle(n0, min(n1, n_mid + 80)),
        "low_probe": _sc_low_probe(n1),
        "fps_align": _sc_fps_align(levels),
    }


SCENARIOS = build_scenarios()

if args.list_scenarios:
    for name, sc in SCENARIOS.items():
        print(f"  {name:12s}  {sc.description}")
    sys.exit(0)

_scenario_name = args.scenario
if _scenario_name not in SCENARIOS:
    print(f"Unknown scenario {_scenario_name!r}. Use --list-scenarios.", file=sys.stderr)
    sys.exit(2)

_default_log = ""
if _scenario_name != "manual" and not args.log:
    _default_log = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        f"_fx_auto_{_scenario_name}.csv",
    )
_log_path = args.log or _default_log

# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------
init(
    width=args.width,
    height=args.height,
    window_scale=0.78,
    title=f"Scena — FX Auto stress [{_scenario_name}]",
)
canvas.background = (0.05, 0.06, 0.09, 1)
set_fx_auto(False)
canvas.fx_quality = args.quality
canvas.framerate = "vsync60"

canvas.effects.add(Vignette())
canvas.effects.add(Grain())
canvas.effects.add(Bloom(intensity=0.55))

LOOKS = (
    Neon("cyan"),
    Neon("magenta"),
    Laser("orange"),
    ElectricField("lime"),
    Gel("coral"),
    Rim("gold"),
    Bolt("violet"),
    Glow("cyan"),
)
SHARED_GLOW = GlowFilter()
FLEET_GLOW = Glow("deepskyblue")
_HEAVY_COLORS = (
    "cyan", "magenta", "orange", "lime", "coral", "gold", "violet",
    "deepskyblue", "tomato", "chocolate", "hotpink", "aqua",
)

_units: list = []
_spatial: list = []
_spatial_on = bool(args.spatial) or (_scenario_name == "low_probe")
_heavy = bool(args.heavy) or (_scenario_name == "low_probe")
_count = max(_N_MIN, min(_N_MAX, int(args.n)))
_t = 0.0
_scenario_t0: Optional[float] = None
_scenario_t = 0.0
_active_ramp: Optional[Tuple[float, float, int, int]] = None  # t0, dur, n0, n1
_next_step_i = 0
_pending_quit = False
_markers: List[str] = []
_last_log_t = 0.0
_samples: List[dict] = []
_rung_transitions: List[dict] = []
_last_rung_label: Optional[str] = None
_csv_file = None
_csv_writer = None

_CSV_FIELDS = [
    "t", "wall_t", "n", "fps", "inst_fps", "dt_ms",
    "quality", "auto", "rate",
    "rung", "rung_index", "present_hz", "fidelity",
    "ema_ms", "budget_ms", "down_line_ms", "up_line_ms",
    "bad_for_s", "good_for_s", "cooldown_left_s",
    "spatial", "heavy", "marker", "scenario",
]

hud = Text(
    text="",
    top_left=(14, args.height - 11),
    font_size=14,
    color=Color(0.9, 0.92, 0.95, 1),
)
tip = Text(
    text="[ ] N · A Auto · 1/2/3 quality · S spatial · L marker · Ctrl+Shift+2 Auto",
    top_left=(14, 62),
    font_size=12,
    color=Color(0.55, 0.6, 0.68, 1),
)
scenario_hud = Text(
    text="",
    top_left=(14, 86),
    font_size=12,
    color=Color(0.7, 0.75, 0.55, 1),
)


def _clear_units() -> None:
    for shape, *_rest in _units:
        try:
            shape.destroy()
        except Exception:
            try:
                shape.undraw()
            except Exception:
                pass
    _units.clear()


def _clear_spatial() -> None:
    for fx in _spatial:
        try:
            fx.destroy()
        except Exception:
            try:
                fx.undraw()
            except Exception:
                pass
    _spatial.clear()


def _make_look(i: int, kind: int):
    if not _heavy:
        return LOOKS[kind]
    color = _HEAVY_COLORS[i % len(_HEAVY_COLORS)]
    factories = (
        lambda: Neon(color),
        lambda: Neon(color),
        lambda: Laser(color),
        lambda: ElectricField(color),
        lambda: Gel(color),
        lambda: Rim(color),
        lambda: Bolt(color),
        lambda: Glow(color),
    )
    return factories[kind % len(factories)]()


def _rebuild(n: int) -> None:
    """Spawn n heavy shapes in a grid with shared (or unique) looks."""
    global _count
    _count = max(_N_MIN, min(_N_MAX, int(n)))
    _clear_units()

    cols = max(1, int(math.ceil(math.sqrt(_count * 1.4))))
    rows = max(1, int(math.ceil(_count / cols)))
    margin_x = 70.0
    margin_y = 70.0
    usable_w = max(1.0, float(args.width) - 2 * margin_x)
    usable_h = max(1.0, float(args.height) - 2 * margin_y)
    cell_w = usable_w / cols
    cell_h = usable_h / rows
    # Heavy: slightly larger radii → more fill-rate / multipass cost
    radius_scale = 0.34 if _heavy else 0.28
    radius = max(8.0, min(cell_w, cell_h) * radius_scale)

    for i in range(_count):
        r = i // cols
        c = i % cols
        bx = margin_x + (c + 0.5) * cell_w
        by = margin_y + (r + 0.5) * cell_h
        phase = i * 0.37
        kind = i % len(LOOKS)

        if kind in (2,):  # Laser — line host
            half = radius * 1.6
            shape = Line(
                p1=(bx - half, by),
                p2=(bx + half, by),
                line_width=max(2.0, radius * 0.18),
            )
        else:
            shape = Circle(center=(bx, by), radius=radius)

        if (not _heavy) and i % 5 == 4:
            shape.visual = FLEET_GLOW
            shape.fill_filter = SHARED_GLOW
        else:
            shape.visual = _make_look(i, kind)
            if _heavy and i % 3 == 0:
                # Unique GlowFilter breaks batching → much heavier.
                shape.fill_filter = GlowFilter(
                    radius=8 + (i % 5),
                    sigma=3 + (i % 3),
                )

        _units.append((shape, bx, by, phase, kind))


def _rebuild_spatial() -> None:
    _clear_spatial()
    if not _spatial_on:
        return
    if _heavy:
        spots = (
            (0.18, 0.28, 40),
            (0.50, 0.22, 36),
            (0.82, 0.30, 40),
            (0.30, 0.70, 32),
            (0.70, 0.72, 34),
        )
        for fx, fy, rad in spots:
            _spatial.append(Fire(center=(args.width * fx, args.height * fy), radius=rad))
    else:
        _spatial.append(Fire(center=(args.width * 0.22, args.height * 0.35), radius=36))
        if _count >= 40:
            _spatial.append(Fire(center=(args.width * 0.78, args.height * 0.55), radius=28))


def _open_log() -> None:
    global _csv_file, _csv_writer
    if not _log_path:
        return
    _csv_file = open(_log_path, "w", newline="", encoding="utf-8")
    _csv_writer = csv.DictWriter(_csv_file, fieldnames=_CSV_FIELDS, extrasaction="ignore")
    _csv_writer.writeheader()
    _csv_file.flush()
    print(f"[fx_auto_stress] logging → {_log_path}")


def _close_log() -> None:
    global _csv_file, _csv_writer
    if _csv_file is not None:
        _csv_file.flush()
        _csv_file.close()
        _csv_file = None
        _csv_writer = None


def _sample_metrics(dt: float, marker: str = "") -> dict:
    fw = ScenaFramework.get_instance()
    q = canvas.fx_quality
    qname = q.value if q is not None else "?"
    auto = bool(fw.fx_auto)
    rate = str(canvas.framerate)
    fps = float(fw.clock.fps)
    inst = (1.0 / dt) if dt > 1e-9 else 0.0
    row = {
        "t": round(_scenario_t if _scenario_t0 is not None else _t, 4),
        "wall_t": round(time.perf_counter(), 4),
        "n": _count,
        "fps": round(fps, 2),
        "inst_fps": round(inst, 2),
        "dt_ms": round(dt * 1000.0, 3),
        "quality": qname,
        "auto": int(auto),
        "rate": rate,
        "rung": "",
        "rung_index": -1,
        "present_hz": float(fw._pacer.diagnostics().get("present_hz") or 0),
        "fidelity": qname,
        "ema_ms": "",
        "budget_ms": "",
        "down_line_ms": "",
        "up_line_ms": "",
        "bad_for_s": "",
        "good_for_s": "",
        "cooldown_left_s": "",
        "spatial": int(_spatial_on),
        "heavy": int(_heavy),
        "marker": marker,
        "scenario": _scenario_name,
    }
    if auto and fw._fx_auto_ctrl is not None:
        d = fw._fx_auto_ctrl.diagnostics(now=time.perf_counter())
        row.update({
            "rung": d["rung_label"],
            "rung_index": d["rung_index"],
            "present_hz": d["present_hz"],
            "fidelity": d["fidelity"],
            "ema_ms": "" if d["ema_ms"] is None else round(d["ema_ms"], 3),
            "budget_ms": round(d["budget_ms"], 3),
            "down_line_ms": round(d["down_line_ms"], 3),
            "up_line_ms": round(d["up_line_ms"], 3),
            "bad_for_s": round(d["bad_for_s"], 3),
            "good_for_s": round(d["good_for_s"], 3),
            "cooldown_left_s": round(d["cooldown_left_s"], 3),
        })
    return row


def _record(dt: float, marker: str = "", force: bool = False) -> None:
    global _last_log_t, _last_rung_label
    now = _scenario_t if _scenario_t0 is not None else _t
    period = 0.0 if args.log_hz <= 0 else 1.0 / args.log_hz
    if not force and not marker and period > 0 and (now - _last_log_t) < period:
        return
    row = _sample_metrics(dt, marker=marker)
    _last_log_t = now
    _samples.append(row)
    if _csv_writer is not None:
        _csv_writer.writerow(row)
        if marker or len(_samples) % 20 == 0:
            _csv_file.flush()

    label = row.get("rung") or ""
    if label and label != _last_rung_label:
        if _last_rung_label is not None:
            _rung_transitions.append({
                "t": row["t"],
                "from": _last_rung_label,
                "to": label,
                "n": _count,
                "ema_ms": row.get("ema_ms"),
                "fps": row.get("fps"),
            })
            print(
                f"[fx_auto_stress] t={row['t']:.1f}s  "
                f"{_last_rung_label} → {label}  N={_count}  "
                f"ema={row.get('ema_ms')}ms  fps={row.get('fps')}"
            )
        _last_rung_label = label


def _hud_text() -> str:
    fw = ScenaFramework.get_instance()
    q = canvas.fx_quality
    qname = q.value if q is not None else "?"
    auto = "ON" if fw.fx_auto else "off"
    rate = str(canvas.framerate)
    fps = fw.clock.fps
    extra = ""
    if fw.fx_auto and fw._fx_auto_ctrl is not None:
        ctrl = fw._fx_auto_ctrl
        d = ctrl.diagnostics(now=time.perf_counter())
        work = f"{d['ema_ms']:.1f}ms" if d["ema_ms"] is not None else "—"
        extra = (
            f"  ladder:{d['rung_label']}  "
            f"fps:{fps:.0f}/{d['present_hz']:.0f}  "
            f"work:{work}/{d['budget_ms']:.1f}  "
            f"bad:{d['bad_for_s']:.1f} good:{d['good_for_s']:.1f}  "
            f"cd:{d['cooldown_left_s']:.1f}"
            f"{f'  uplk:{d['up_lock_left_s']:.0f}' if d.get('up_lock_left_s', 0) else ''}"
        )
    else:
        extra = f"  fps:{fps:.0f}"
    return (
        f"N={_count}/{_N_MAX}  q={qname}  auto={auto}  rate={rate}"
        f"{extra}  spat={'on' if _spatial_on else 'off'}"
        f"{'  HEAVY' if _heavy else ''}"
    )


def _auto_params() -> Optional[AutoParams]:
    if args.t_up is None and args.cooldown is None and args.k_up is None:
        return None
    base = AutoParams()
    cool = float(args.cooldown) if args.cooldown is not None else None
    return AutoParams(
        eval_period_s=base.eval_period_s,
        t_down_s=base.t_down_s,
        t_up_s=float(args.t_up) if args.t_up is not None else base.t_up_s,
        cooldown_down_s=cool if cool is not None else base.cooldown_down_s,
        cooldown_up_s=cool if cool is not None else base.cooldown_up_s,
        settle_evals=base.settle_evals,
        k_down=base.k_down,
        k_up=float(args.k_up) if args.k_up is not None else base.k_up,
        k_up_fidelity=(
            float(args.k_up) if args.k_up is not None else base.k_up_fidelity
        ),
        k_up_to_high=(
            float(args.k_up) if args.k_up is not None else base.k_up_to_high
        ),
        t_up_fidelity_scale=base.t_up_fidelity_scale,
        t_up_to_high_scale=base.t_up_to_high_scale,
        ema_alpha=base.ema_alpha,
        ema_reset_on_step=base.ema_reset_on_step,
        failed_climb_window_s=base.failed_climb_window_s,
        failed_climb_lock_s=base.failed_climb_lock_s,
        warmup_s=base.warmup_s,
    )


def _apply_step(step: Step) -> None:
    global _spatial_on, _active_ramp, _pending_quit
    if step.note:
        print(f"[fx_auto_stress] @{step.at:.1f}s  {step.op}  {step.note}")
    if step.op == "set_n" and step.n is not None:
        _rebuild(step.n)
        _rebuild_spatial()
        _active_ramp = None
    elif step.op == "ramp_n" and step.n is not None and step.n_end is not None:
        _rebuild(step.n)
        _rebuild_spatial()
        _active_ramp = (_scenario_t, max(0.01, step.duration), int(step.n), int(step.n_end))
    elif step.op == "spatial" and step.on is not None:
        _spatial_on = bool(step.on)
        _rebuild_spatial()
    elif step.op == "marker":
        _markers.append(step.note or "mark")
    elif step.op == "hold_end":
        _active_ramp = None
    elif step.op == "quit":
        _pending_quit = True


def _tick_scenario() -> None:
    global _next_step_i, _active_ramp
    sc = SCENARIOS[_scenario_name]
    if not sc.steps:
        return
    while _next_step_i < len(sc.steps) and sc.steps[_next_step_i].at <= _scenario_t + 1e-6:
        _apply_step(sc.steps[_next_step_i])
        _next_step_i += 1

    if _active_ramp is not None:
        t0, dur, n0, n1 = _active_ramp
        u = min(1.0, max(0.0, (_scenario_t - t0) / dur))
        # Discrete steps — avoid per-frame full scene rebuild thrash.
        step = max(1, _N_STEP)
        raw = n0 + (n1 - n0) * u
        if n1 >= n0:
            n = int(n0 + step * max(0, round((raw - n0) / step)))
            n = min(n1, max(n0, n))
        else:
            n = int(n0 - step * max(0, round((n0 - raw) / step)))
            n = max(n1, min(n0, n))
        if u >= 1.0:
            n = n1
            _active_ramp = None
        if n != _count:
            _rebuild(n)
            if not _heavy:
                _rebuild_spatial()


def _summarize() -> dict:
    rung_hist: dict = {}
    fps_by_rung: dict = {}
    for s in _samples:
        r = s.get("rung") or s.get("quality") or "?"
        rung_hist[r] = rung_hist.get(r, 0) + 1
        try:
            fps = float(s.get("fps") or 0)
        except (TypeError, ValueError):
            fps = 0.0
        if fps > 0:
            fps_by_rung.setdefault(r, []).append(fps)

    fps_align = {}
    for r, vals in fps_by_rung.items():
        if not vals:
            continue
        mean = sum(vals) / len(vals)
        # parse target from label like medium@60
        tgt = None
        if "@" in str(r):
            try:
                tgt = float(str(r).split("@", 1)[1])
            except ValueError:
                tgt = None
        fps_align[r] = {
            "mean_fps": round(mean, 2),
            "n_samples": len(vals),
            "target_hz": tgt,
            "abs_err": None if tgt is None else round(abs(mean - tgt), 2),
            "rel_err": None if tgt is None or tgt <= 0 else round(abs(mean - tgt) / tgt, 3),
            "ok_within_15pct": (
                None if tgt is None or tgt <= 0
                else abs(mean - tgt) / tgt <= 0.15
            ),
        }

    # Oscillation: count A→B→A patterns in transitions
    osc_pairs = 0
    for i in range(len(_rung_transitions) - 1):
        a = _rung_transitions[i]
        b = _rung_transitions[i + 1]
        if a["from"] == b["to"] and a["to"] == b["from"]:
            osc_pairs += 1

    reached_low = any(
        (s.get("fidelity") == "low") or str(s.get("rung", "")).startswith("low@")
        for s in _samples
    )
    reached_low60 = any(str(s.get("rung", "")) == "low@60" for s in _samples)

    return {
        "scenario": _scenario_name,
        "heavy": _heavy,
        "n_max": _N_MAX,
        "samples": len(_samples),
        "duration_s": _samples[-1]["t"] if _samples else 0.0,
        "log": _log_path,
        "rung_histogram": rung_hist,
        "transitions": _rung_transitions,
        "transition_count": len(_rung_transitions),
        "oscillation_pairs": osc_pairs,
        "fps_align": fps_align,
        "reached_low_60": reached_low60,
        "reached_low": reached_low,
        "markers": list(_markers),
        "auto_params": None if _auto_params() is None else _auto_params()._asdict(),
    }


def _finish(reason: str = "done") -> None:
    summary = _summarize()
    summary["exit_reason"] = reason
    print("\n=== FX Auto stress summary ===")
    print(json.dumps(summary, indent=2, default=str))
    out = args.summary_json
    if not out and _log_path:
        out = os.path.splitext(_log_path)[0] + "_summary.json"
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, default=str)
        print(f"[fx_auto_stress] summary → {out}")
    _close_log()
    import glfw
    fw = ScenaFramework.get_instance()
    if fw._window is not None:
        glfw.set_window_should_close(fw._window, True)


def setup(c):
    global _scenario_t0
    _rebuild(_count)
    _rebuild_spatial()
    _open_log()
    params = _auto_params()
    if args.auto or _scenario_name != "manual":
        set_fx_auto(True, params=params)
    hud.text = _hud_text()
    scenario_hud.text = f"scenario={_scenario_name}"
    _scenario_t0 = time.perf_counter()
    _record(1.0 / 60.0, marker="start", force=True)


def update(dt, c):
    global _t, _count, _spatial_on, _scenario_t, _pending_quit
    _t += dt
    if _scenario_t0 is not None:
        _scenario_t = time.perf_counter() - _scenario_t0

    fw = ScenaFramework.get_instance()

    # Scenario director
    if _scenario_name != "manual":
        _tick_scenario()

    # Manual load controls (always available; scenario may overwrite N)
    if keyp.once("LEFT") or keyp.once("-"):
        _rebuild(_count - _N_STEP)
        _rebuild_spatial()
    if keyp.once("RIGHT") or keyp.once("="):
        _rebuild(_count + _N_STEP)
        _rebuild_spatial()
    if keyp.once("A"):
        if fw.fx_auto:
            set_fx_auto(False)
        else:
            set_fx_auto(True, params=_auto_params())
    if keyp.once("1"):
        canvas.fx_quality = "low"
    if keyp.once("2"):
        canvas.fx_quality = "medium"
    if keyp.once("3"):
        canvas.fx_quality = "high"
    if keyp.once("S"):
        _spatial_on = not _spatial_on
        _rebuild_spatial()
    if keyp.once("L"):
        _markers.append(f"key@{_scenario_t:.1f}")
        _record(dt, marker="key_L", force=True)

    # Plain python motion
    for shape, bx, by, phase, kind in _units:
        ox = 14.0 * math.sin(_t * 1.3 + phase)
        oy = 11.0 * math.cos(_t * 1.1 + phase * 0.7)
        x = bx + ox
        y = by + oy
        if kind == 2:
            half = 28.0
            try:
                shape.p1.x = x - half
                shape.p1.y = y
                shape.p2.x = x + half
                shape.p2.y = y
            except Exception:
                pass
        else:
            try:
                shape.center.x = x
                shape.center.y = y
            except Exception:
                pass
            try:
                shape.rotate_to(math.degrees(math.sin(_t * 0.8 + phase) * 0.35))
            except Exception:
                pass

    _record(dt)
    hud.text = _hud_text()
    if _scenario_name != "manual":
        sc = SCENARIOS[_scenario_name]
        left = ""
        if _next_step_i < len(sc.steps):
            nxt = sc.steps[_next_step_i]
            left = f"  next:{nxt.op}@{nxt.at:.0f}s"
        scenario_hud.text = f"scenario={_scenario_name}  t={_scenario_t:.1f}s{left}"

    if _pending_quit:
        _record(dt, marker="quit", force=True)
        _finish("scenario_complete")


if __name__ == "__main__":
    run()
