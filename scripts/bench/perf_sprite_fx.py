"""Benchmark cost of each Sprite look / filter used in ``sprite_fx`` smoke.

Spawns ``--n`` sprites with one effect at a time, measures phase-timed
``draw_ms`` / ``work_ms`` at ``canvas.fx_quality=high``.

    python scripts/bench/perf_sprite_fx.py
    python scripts/bench/perf_sprite_fx.py --n 48 --duration 1.0 --warmup 0.35
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.bench.harness import (  # noqa: E402
    average_phase_stats,
    empty_phase_stats,
    install_phase_run,
)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--n", type=int, default=48)
parser.add_argument("--duration", type=float, default=1.0)
parser.add_argument("--warmup", type=float, default=0.35)
parser.add_argument("--width", type=int, default=1000)
parser.add_argument("--height", type=int, default=700)
parser.add_argument("--quality", default="high")
parser.add_argument("--json", dest="json_path", default=None)
args = parser.parse_args()

from scena import *  # noqa: E402
from scena.orchestration import ScenaFramework  # noqa: E402

W, H = args.width, args.height
init(width=W, height=H, window_scale=0.55, title="bench — sprite FX")
set_fx_auto(False)
canvas.fx_quality = args.quality
canvas.batch_shared_filters = True
# Isolate sprite looks: no wallpaper / post stack.
canvas.background = (0.06, 0.07, 0.09)
canvas.effects.clear()

_ART = os.path.join(_ROOT, "examples", "media", "space", "enemyBlue2.png")

TINT = "cyan"
sprites: list = []


def _clear() -> None:
    for s in list(sprites):
        if s.is_alive:
            s.destroy()
    sprites.clear()


def _spawn(apply) -> None:
    _clear()
    cols = max(1, int(math.ceil(math.sqrt(args.n))))
    gap = min(W, H) / (cols + 1)
    for i in range(args.n):
        row, col = divmod(i, cols)
        x = gap * (col + 1)
        y = gap * (row + 1)
        spr = Sprite(_ART, height=48, center=(x, y), group="bench")
        apply(spr)
        sprites.append(spr)


# (label, apply) — mirrors smoke gallery looks.
EFFECTS: list[tuple[str, object]] = [
    ("none", lambda s: None),
    ("Glow", lambda s: setattr(s, "glow", Glow(TINT, radius=16, sigma=8, amount=1.2))),
    ("Shadow", lambda s: setattr(s, "shadow", Shadow(offset=10, sigma=6))),
    ("Halo", lambda s: setattr(s, "visual", Halo(TINT, amount=1.15))),
    ("Halo fill", lambda s: setattr(s, "visual", Halo(TINT, style="fill", amount=1.1))),
    ("Halo soft", lambda s: setattr(s, "visual", Halo(TINT, style="soft", amount=1.2))),
    ("Halo line", lambda s: setattr(s, "visual", Halo(TINT, style="line", amount=1.25))),
    ("Tail", lambda s: setattr(s, "tail", Tail(TINT, angle=0, size=1.5, amount=1.15))),
    ("Beat", lambda s: setattr(s, "visual", Beat(amount=0.14, speed=1.4))),
    (
        "Tail + GlowFilter",
        lambda s: (
            setattr(s, "tail", Tail("orange", angle=90, size=1.6, amount=1.2)),
            setattr(
                s,
                "fill_filter",
                GlowFilter(radius=10, sigma=5, intensity=1.1, color=(1.0, 0.55, 0.15, 1.0)),
            ),
            None,
        )[-1],
    ),
    ("HueShift", lambda s: setattr(s, "hue", HueShift(amount=0.33))),
    ("Recolor", lambda s: setattr(s, "visual", Recolor(key="lime", to="tomato", range=0.14))),
    ("Aura", lambda s: setattr(s, "visual", Aura(TINT, amount=1.1))),
    ("EmissiveBloom", lambda s: setattr(s, "visual", EmissiveBloom(intensity=1.5, sigma=11))),
    ("Rim", lambda s: setattr(s, "visual", Rim("white", amount=1.1, width=3.5))),
    (
        "ElectricField",
        lambda s: setattr(s, "visual", ElectricField(amount=6, speed=16 / 14.0)),
    ),
    ("ElectricBolt", lambda s: setattr(s, "visual", ElectricBolt("gold", amount=6, speed=1.0))),
    ("Shield bubble", lambda s: setattr(s, "visual", Shield(style="bubble", amount=1.05))),
    ("Shield nebula", lambda s: setattr(s, "visual", Shield(style="nebula", amount=1.05))),
    ("Shield ember", lambda s: setattr(s, "visual", Shield(style="ember", amount=1.05))),
    ("Shield void", lambda s: setattr(s, "visual", Shield(style="void", amount=1.05))),
    ("Shield molten", lambda s: setattr(s, "visual", Shield(style="molten", amount=1.1, speed=1.15))),
    ("Shield bands", lambda s: setattr(s, "visual", Shield("teal", style="bands", amount=1.05, speed=0.4))),
    ("Shield vortex", lambda s: setattr(s, "visual", Shield("orchid", style="vortex", amount=1.1))),
    ("Shield plasma", lambda s: setattr(s, "visual", Shield(style="plasma", amount=1.1))),
    ("Shield cracks", lambda s: setattr(s, "visual", Shield(style="cracks", amount=1.1))),
    ("Shield frost", lambda s: setattr(s, "visual", Shield(style="frost", amount=1.1))),
    (
        "GlowFilter",
        lambda s: setattr(
            s, "fill_filter",
            GlowFilter(radius=16, sigma=9, intensity=1.35, color=(0.35, 0.8, 1.0, 1.0)),
        ),
    ),
    ("Blur", lambda s: setattr(s, "fill_filter", Blur(sigma=2.8))),
    (
        "DropShadow",
        lambda s: setattr(
            s, "fill_filter",
            DropShadow(offset=12, sigma=6, color=(0.0, 0.0, 0.0, 0.7)),
        ),
    ),
]


fw = ScenaFramework.get_instance()
# Same as live_mix / cpu_mix / perf_fx_matrix: pin OS window to design size,
# then install_phase_run + module-level run() (opens GLFW via open_window).
fw._compute_window_size = lambda dw, dh, wf: (int(dw), int(dh))

print(
    f"=== sprite FX bench  n={args.n}  Q={args.quality}  "
    f"dur={args.duration}s  art={os.path.basename(_ART)} ===",
    flush=True,
)

rows = []
for label, apply in EFFECTS:
    _spawn(apply)
    stats = empty_phase_stats()
    install_phase_run(
        fw,
        duration=args.duration,
        warmup=args.warmup,
        stats=stats,
        force_1x_pixels=True,
    )
    # Module-level run() → open_window() once, then instrumented fw.run.
    # Do not call fw.run() directly (skips GLFW / Skia surface setup).
    run()
    avg = average_phase_stats(stats)
    row = {
        "effect": label,
        "draw_ms": round(avg["draw_ms"], 3),
        "work_ms": round(avg["work_ms"], 3),
        "fps": round(avg["fps"], 1),
        "frames": int(avg["frames"]),
    }
    rows.append(row)
    print(
        f"{label:<18} draw={row['draw_ms']:7.3f} ms  "
        f"work={row['work_ms']:7.3f} ms  fps={row['fps']:6.1f}",
        flush=True,
    )
    time.sleep(0.05)

_clear()
rows.sort(key=lambda r: r["draw_ms"], reverse=True)
base = next((r for r in rows if r["effect"] == "none"), None)
base_draw = float(base["draw_ms"]) if base else 0.0
for r in rows:
    r["delta_ms"] = round(r["draw_ms"] - base_draw, 3) if base else None
    r["vs_none"] = (
        round(r["draw_ms"] / base_draw, 2) if base and base_draw > 1e-6 else None
    )

print("\n=== ranked by draw_ms (most expensive first) ===", flush=True)
print(f"{'effect':<18} {'draw_ms':>8} {'Δms':>8} {'×none':>7} {'work_ms':>8}", flush=True)
for r in rows:
    dlt = f"{r['delta_ms']:+.3f}" if r["delta_ms"] is not None else "—"
    vs = f"{r['vs_none']:.2f}" if r["vs_none"] is not None else "—"
    print(
        f"{r['effect']:<18} {r['draw_ms']:8.3f} {dlt:>8} {vs:>7} {r['work_ms']:8.3f}",
        flush=True,
    )

out = {
    "n": args.n,
    "quality": args.quality,
    "duration": args.duration,
    "warmup": args.warmup,
    "art": os.path.basename(_ART),
    "ranked": rows,
}
if args.json_path:
    os.makedirs(os.path.dirname(os.path.abspath(args.json_path)) or ".", exist_ok=True)
    with open(args.json_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"\nwrote {args.json_path}", flush=True)

# Always write a session copy for the canvas
_default_json = os.path.join(_HERE, "results", "sprite_fx_latest.json")
os.makedirs(os.path.dirname(_default_json), exist_ok=True)
with open(_default_json, "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2)
print(f"wrote {_default_json}", flush=True)
