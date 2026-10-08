"""
soak_leak.py — create/destroy + FX churn soak (leak / leftover detector).

Each cycle churns shapes/sprites/FX/timers then returns to a known idle scene,
recording RSS, idle frame time, and live inventory counts.

Deltas are **after_cycle 1 → last** (first-frame baseline excluded). Evolution
metrics are last idle ``work_ms``, last RSS, and Δ objects/handles.

Usage
-----
    python scripts/bench/soak_leak.py
    python scripts/bench/soak_leak.py --cycles 30 --json scripts/bench/results/soak.json
    python scripts/bench/soak_leak.py --cycles 20 --idle-frames 45 --warn-rss-mb 8
"""
from __future__ import annotations

import argparse
import gc
import os
import sys
import time
from typing import Any, Dict, List, Optional

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--cycles", type=int, default=0,
                    help="if >0, run N cycles then exit")
parser.add_argument("--idle-frames", type=int, default=40,
                    help="frames to sample idle cost after each cycle")
parser.add_argument("--churn-frames", type=int, default=10,
                    help="frames to keep churn objects alive before teardown")
parser.add_argument("--json", dest="json_path", default=None)
parser.add_argument("--warn-rss-mb", type=float, default=12.0)
parser.add_argument("--warn-work-ms", type=float, default=1.5)
parser.add_argument("--quality", default="high",
                    choices=("low", "medium", "high", "max"))
args, _ = parser.parse_known_args()

_BENCH = os.path.dirname(os.path.abspath(__file__))
if _BENCH not in sys.path:
    sys.path.insert(0, _BENCH)

from harness import write_json  # noqa: E402

from scena import *  # noqa: E402
from scena.orchestration import ScenaFramework, set_leak_detector  # noqa: E402
from scena.process import get_scheduler  # noqa: E402
from scena.collision import get_collision_system  # noqa: E402
from scena.state import get_scena_system  # noqa: E402

W, H = 1000, 700
init(width=W, height=H, window_scale=0.65, title="Bench — soak / leak")
set_fx_auto(False)
set_leak_detector(False)  # intentional create/destroy churn must not warn
canvas.fx_quality = args.quality
canvas.background = (0.06, 0.07, 0.09, 1)
canvas.batch_shared_filters = True

_idle_a = Circle(center=(200, 350), radius=20).set_color("cyan")
_idle_b = Circle(center=(800, 350), radius=20).set_color("gold")
(_t := (Line(p1=lambda: _idle_a.center, p2=lambda: _idle_b.center).set_color("white"))).line_width = 1

hud = Text(text="", top_left=(20, H - 10), font_size=15, color=Color(0.9, 0.92, 1.0, 1))
hint = Text(
    text="SPACE = one soak cycle  ·  --cycles N for headless",
    top_left=(20, H - 37), font_size=13, color=Color(0.55, 0.62, 0.75, 1),
)
status = Text(text="idle", top_left=(20, H - 59), font_size=14, color=Color(0.85, 0.8, 0.5, 1))

_samples: List[Dict[str, Any]] = []
_cycle = 0
_churn: List[Any] = []
_vel_holders: List[Any] = []  # plain Python holders for Vec2-reassign soak
_phase = "baseline" if args.cycles > 0 else "idle"
_frames_left = int(args.idle_frames) if args.cycles > 0 else 0
_idle_work: List[float] = []
_auto_left = int(args.cycles)
_done = False
_spin_handle = None


def _rss_mb() -> float:
    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            return float(rss) / (1024.0 * 1024.0)
        return float(rss) / 1024.0
    except Exception:
        return float("nan")


def _inventory() -> Dict[str, float]:
    fw = ScenaFramework.get_instance()
    n_obj = 0
    try:
        for layer in fw._scena_draw.registry.layers.iter_draw_order():
            n_obj += len(layer._objects)
    except Exception:
        n_obj = -1
    n_handles = -1
    try:
        n_handles = len(getattr(get_scheduler(), "_handles", []) or [])
    except Exception:
        pass
    n_coll = -1
    try:
        cs = get_collision_system()
        if cs is not None:
            n_coll = len(getattr(cs, "_colliders", []) or [])
    except Exception:
        pass
    n_post = -1
    try:
        n_post = len(canvas.effects)
    except Exception:
        pass
    n_bg = -1
    try:
        n_bg = len(canvas.background)
    except Exception:
        pass
    n_widgets = -1
    try:
        n_widgets = len(fw.widget_manager.widgets)
    except Exception:
        pass
    n_graph = -1
    try:
        ss = get_scena_system()
        if ss is not None:
            n_graph = len(ss.dependency_graph.nodes)
    except Exception:
        pass
    return {
        "objects": float(n_obj),
        "scheduler_handles": float(n_handles),
        "collision_enrolled": float(n_coll),
        "canvas_effects": float(n_post),
        "bg_extras": float(n_bg),
        "widgets": float(n_widgets),
        "graph_nodes": float(n_graph),
    }


def _cancel_spin() -> None:
    global _spin_handle
    if _spin_handle is not None:
        try:
            _spin_handle.cancel()
        except Exception:
            pass
        _spin_handle = None


def _destroy_churn() -> None:
    global _churn, _vel_holders
    _cancel_spin()
    for obj in list(_churn):
        try:
            if hasattr(obj, "destroy"):
                obj.destroy()
            elif hasattr(obj, "remove"):
                obj.remove()
        except Exception:
            pass
    _churn.clear()
    _vel_holders.clear()
    try:
        canvas.effects.clear()
    except Exception:
        pass
    try:
        canvas.background.clear()
    except Exception:
        pass
    canvas.background = (0.06, 0.07, 0.09, 1)


def _run_churn() -> None:
    global _churn, _spin_handle, _vel_holders
    _destroy_churn()

    for i in range(24):
        x = 80 + (i % 8) * 110
        y = 140 + (i // 8) * 100
        c = Circle(center=(x, y), radius=18 + (i % 5), group="soak").set_color(
            ("cyan", "magenta", "gold", "lime")[i % 4]
        )
        if i % 3 == 0:
            c.glow = Glow(radius=10, sigma=6)
        elif i % 3 == 1:
            c.visual = Neon(amount=0.9)
        else:
            try:
                c.fill_filter = GlowFilter(radius=8, sigma=5)
            except Exception:
                pass
        c.collidable = True
        _churn.append(c)

    for i in range(6):
        try:
            s = Sprite("examples/media/space/playerShip1_red.png", height=32, center=(150 + i * 120, 500), group="soak")
            if i % 2 == 0:
                s.visual = Halo(amount=0.7)
            s.flash(0.06)
            _churn.append(s)
        except Exception:
            pass

    try:
        _churn.append(Fire(center=(400, 220), radius=26))
        _churn.append(GlowSpot(center=(600, 220), radius=36, color="orange", amount=0.55))
    except Exception:
        pass

    try:
        canvas.effects.add(Vignette(amount=0.25))
        canvas.effects.add(Bloom(intensity=0.35))
        canvas.ripple_at(W * 0.5, H * 0.45, amount=0.6)
    except Exception:
        pass

    try:
        Stars(density=0.4, pan_response=0.0)
    except Exception:
        pass

    def _spin():
        for obj in list(group["soak"]):
            if hasattr(obj, "rotate_by"):
                try:
                    obj.rotate_by(10)
                except Exception:
                    pass

    try:
        _spin_handle = every(0.2, _spin, name="soak_spin")
    except Exception:
        _spin_handle = None

    try:
        a = Circle(center=(100, 80), radius=10, group="soak").set_color("white")
        b = Circle(center=(140, 80), radius=10, group="soak").set_color("orange")
        b.center["x"] @= lambda: float(a.center.x) + 40.0
        _churn.extend([a, b])
    except Exception:
        pass

    try:
        _idle_a.pulse_outline(0.15)
        _idle_b.pop(0.12)
    except Exception:
        pass

    # Regression: reassign bare Vec2 on plain Python holders (a GlowSpot arena game's pattern).
    # With lazy registration this must not grow graph_nodes across cycles.
    class _VelHolder:
        __slots__ = ("vel",)

    _vel_holders = []
    for i in range(16):
        h = _VelHolder()
        h.vel = Vec2(float(i), float(-i))
        _vel_holders.append(h)
    for h in _vel_holders:
        for j in range(8):
            h.vel = Vec2(float(j), float(j))


def _record_sample(label: str) -> Dict[str, Any]:
    inv = _inventory()
    work = sum(_idle_work) / len(_idle_work) if _idle_work else float("nan")
    sample = {
        "cycle": _cycle,
        "label": label,
        "rss_mb": _rss_mb(),
        "idle_work_ms": work,
        "fps_est": (1000.0 / work) if work and work > 0 else float("nan"),
        **inv,
        "t": time.time(),
    }
    _samples.append(sample)
    status.text = (
        f"cycle={_cycle}  rss={sample['rss_mb']:.1f}MiB  "
        f"work={work:.2f}ms  objs={int(inv['objects'])}  "
        f"handles={int(inv['scheduler_handles'])}  post={int(inv['canvas_effects'])}"
    )
    return sample


def _plateau_samples() -> List[Dict[str, Any]]:
    return [s for s in _samples if s.get("label") == "after_cycle"]


def _slope(key: str, samples: Optional[List[Dict[str, Any]]] = None) -> float:
    rows = _samples if samples is None else samples
    if len(rows) < 2:
        return 0.0
    return float(rows[-1].get(key, 0) or 0) - float(rows[0].get(key, 0) or 0)


def _finalize() -> None:
    global _done, _phase
    if _done:
        return
    _done = True
    _phase = "done"
    plateau = _plateau_samples()
    last = plateau[-1] if plateau else (_samples[-1] if _samples else {})
    first_plat = plateau[0] if plateau else {}
    payload = {
        "samples": _samples,
        "delta_rss_mb": _slope("rss_mb", plateau),
        "delta_work_ms": _slope("idle_work_ms", plateau),
        "delta_objects": _slope("objects", plateau),
        "delta_handles": _slope("scheduler_handles", plateau),
        "delta_graph_nodes": _slope("graph_nodes", plateau),
        "last_rss_mb": float(last.get("rss_mb", float("nan"))),
        "last_idle_work_ms": float(last.get("idle_work_ms", float("nan"))),
        "plateau_first_rss_mb": float(first_plat.get("rss_mb", float("nan"))),
        "plateau_first_idle_work_ms": float(first_plat.get("idle_work_ms", float("nan"))),
        "warn_rss_mb": args.warn_rss_mb,
        "warn_work_ms": args.warn_work_ms,
    }
    rss_d = payload["delta_rss_mb"]
    work_d = payload["delta_work_ms"]
    obj_d = payload["delta_objects"]
    graph_d = payload["delta_graph_nodes"]
    warns = []
    if rss_d == rss_d and rss_d > args.warn_rss_mb:
        warns.append(f"RSS rose {rss_d:.1f} MiB (warn>{args.warn_rss_mb})")
    if work_d == work_d and work_d > args.warn_work_ms:
        warns.append(f"idle work_ms rose {work_d:.2f} (warn>{args.warn_work_ms})")
    if obj_d == obj_d and obj_d > 5:
        warns.append(f"live objects rose by {obj_d:.0f}")
    if graph_d == graph_d and graph_d > 20:
        warns.append(f"graph nodes rose by {graph_d:.0f}")
    payload["warns"] = warns
    print("=" * 60)
    print("soak_leak summary")
    print("=" * 60)
    print(f"cycles:          {len(plateau)}")
    print(f"last rss_mb:     {payload['last_rss_mb']:.2f}")
    print(f"last idle_ms:    {payload['last_idle_work_ms']:.3f}")
    print(f"Δ rss_mb:        {rss_d:.2f}  (after_cycle 1→last; baseline excluded)")
    print(f"Δ idle_work_ms:  {work_d:.3f}")
    print(f"Δ objects:       {obj_d:.0f}")
    print(f"Δ handles:       {payload['delta_handles']:.0f}")
    print(f"Δ graph_nodes:   {graph_d:.0f}")
    if warns:
        print("WARN:", "; ".join(warns))
    else:
        print("OK: no warn thresholds crossed")
    print("=" * 60)
    print(
        f"RESULT_JSON: "
        f'{{"last_rss_mb": {payload["last_rss_mb"]:.4f}, '
        f'"last_idle_work_ms": {payload["last_idle_work_ms"]:.4f}, '
        f'"delta_rss_mb": {rss_d:.4f}, "delta_work_ms": {work_d:.4f}, '
        f'"delta_objects": {obj_d:.1f}, "delta_handles": {payload["delta_handles"]:.1f}, '
        f'"delta_graph_nodes": {graph_d:.1f}}}'
    )
    if args.json_path:
        write_json(args.json_path, payload)
        print("wrote", args.json_path)
    fw = ScenaFramework.get_instance()
    if fw is not None and getattr(fw, "_window", None) is not None:
        import glfw
        glfw.set_window_should_close(fw._window, True)


def _start_churn() -> None:
    global _phase, _frames_left, _cycle, _idle_work
    _cycle += 1
    status.text = f"churn #{_cycle}"
    _run_churn()
    _phase = "churn"
    _frames_left = int(args.churn_frames)
    _idle_work = []


def _start_settle() -> None:
    global _phase, _frames_left, _idle_work
    _destroy_churn()
    gc.collect()
    _idle_work = []
    _phase = "settle"
    _frames_left = int(args.idle_frames)
    status.text = f"settle #{_cycle}"


def update(dt):
    global _phase, _frames_left, _auto_left, _idle_work

    work_ms = (dt * 1000.0) if dt > 0 else 0.0

    if keyp.once("SPACE") and args.cycles <= 0 and _phase == "idle":
        _start_churn()

    if _phase == "baseline":
        _idle_work.append(work_ms)
        _frames_left -= 1
        if _frames_left <= 0:
            _record_sample("baseline")
            _idle_work = []
            if _auto_left > 0:
                _start_churn()
            else:
                _finalize()

    elif _phase == "churn":
        _frames_left -= 1
        if _frames_left <= 0:
            _start_settle()

    elif _phase == "settle":
        _idle_work.append(work_ms)
        _frames_left -= 1
        if _frames_left <= 0:
            _record_sample("after_cycle")
            if args.cycles > 0:
                _auto_left -= 1
                if _auto_left > 0:
                    _start_churn()
                else:
                    _finalize()
            else:
                _phase = "idle"
                status.text = "idle — SPACE for another cycle"

    inv = _inventory()
    hud.text = (
        f"soak  rss={_rss_mb():.1f}MiB  dt={work_ms:.2f}ms  "
        f"objs={int(inv['objects'])}  handles={int(inv['scheduler_handles'])}  "
        f"post={int(inv['canvas_effects'])}  phase={_phase}"
    )


canvas.framerate = "max"
# Same 1× window as mix benches — skips glfw.get_monitor_workarea (fragile on
# some macOS sessions after many GL contexts) and keeps design==window points.
_fw = ScenaFramework.get_instance()
if _fw is not None:
    _fw._compute_window_size = lambda dw, dh, wf: (int(dw), int(dh))
run()
