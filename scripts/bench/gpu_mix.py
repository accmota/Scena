"""
app_scene_realistic.py — game-like composite scene for Scena visual profiling.

Unlike effect-matrix protocols (full screen of one hero look), this scene models
a typical frame budget:

  ~150 drawable shapes
  ~130 cheap fleet (mostly solids / translucent / glow on a few highlight units)
  ~20 multipass heroes (Shield, ElectricField, Neon, Laser, … — mostly 1× each)
  ~20 Lines linking shape pairs via constructor links and @=
  light canvas post (vignette + grain + bloom)
  optional light SpatialFx décor (not counted as shapes)

Usage
-----
    python scripts/bench/gpu_mix.py
    python scripts/bench/gpu_mix.py --bench --duration 3
    python scripts/bench/gpu_mix.py --bench --profile --profile-seconds 3
    python scripts/bench/gpu_mix.py --mode fleet          # no multipass heroes
    python scripts/bench/gpu_mix.py --mode baseline       # solids only, no post
    python scripts/bench/gpu_mix.py --bench --mode heroes
    python scripts/bench/gpu_mix.py --bench --mode heroes_mass --n-heroes 48
    python scripts/bench/gpu_mix.py --bench --suite
"""
from __future__ import annotations

import argparse
import math
import os
import random
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from perf_profile import FrameProfiler, add_profile_args
from perf_common import (
    average_phase_stats,
    empty_phase_stats,
    install_phase_run,
    print_phase_report,
    print_report,
    write_json,
)

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--bench", action="store_true")
parser.add_argument("--duration", type=float, default=3.0)
parser.add_argument("--warmup", type=float, default=0.5)
parser.add_argument(
    "--mode",
    choices=(
        "realistic",  # full composite (default product-like path)
        "fleet",      # cheap shapes + links + post; no multipass heroes
        "heroes",     # only multipass heroes + bg + post (isolate elite cost)
        "heroes_mass",  # dense grid of multipass looks
        "nopost",     # realistic visuals, no canvas.effects
        "baseline",   # solids only, no filters/looks/post/spatial
        "geom",       # baseline + static (draw isolation)
    ),
    default="realistic",
)
parser.add_argument(
    "--quality", default="high",
    choices=("low", "medium", "high", "max"),
)
parser.add_argument("--seed", type=int, default=42)
parser.add_argument("--static", action="store_true", help="freeze motion")
parser.add_argument(
    "--no-spatial", action="store_true",
    help="skip light SpatialFx décor (plume + sparse embers)",
)
parser.add_argument(
    "--cull", action="store_true",
    help="enable canvas.cull_offscreen (large-world opt-in)",
)
parser.add_argument(
    "--n-heroes", type=int, default=48,
    help="with --mode heroes_mass: how many multipass shapes (default 48)",
)
parser.add_argument(
    "--post-only",
    choices=("none", "vignette", "grain", "bloom", "stack"),
    default=None,
    help="with fleet/baseline-like scenes: override post to one stage (vignette remeasure)",
)
parser.add_argument(
    "--suite", action="store_true",
    help="with --bench: isolation matrix in clean subprocesses",
)
parser.add_argument(
    "--json", dest="json_path", default=None,
    help="write phase-timing JSON (with --bench)",
)
add_profile_args(parser)
args, _ = parser.parse_known_args()

_STATIC = args.static or args.mode == "geom"

# ---------------------------------------------------------------------------
# Suite
# ---------------------------------------------------------------------------
if args.suite:
    script = os.path.abspath(__file__)
    configs = [
        ("baseline", "high"),
        ("geom", "high"),
        ("fleet", "high"),
        ("heroes", "high"),
        ("nopost", "high"),
        ("realistic", "low"),
        ("realistic", "high"),
        ("realistic", "max"),
        # post isolation (fleet geometry, no multipass heroes)
        ("fleet", "high", "vignette"),
        ("fleet", "high", "stack"),
    ]
    rows = []
    print(f"=== app_scene_realistic suite  duration={args.duration}s ===")
    for entry in configs:
        if len(entry) == 2:
            mode, quality = entry
            post_only = None
        else:
            mode, quality, post_only = entry
        cmd = [
            sys.executable, script,
            "--bench", "--mode", mode, "--quality", quality,
            "--duration", str(args.duration),
            "--warmup", str(args.warmup),
            "--seed", str(args.seed),
            "--no-spatial",
        ]
        if post_only:
            cmd.extend(["--post-only", post_only])
        if mode == "geom":
            cmd.append("--static")
        label = f"{mode}/{post_only}" if post_only else mode
        print(f"\n>> mode={label} Q={quality}")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        out = proc.stdout + proc.stderr
        print(out)
        fps = None
        ms = None
        for line in out.splitlines():
            if "Average FPS:" in line:
                try:
                    fps = float(line.split(":")[-1].strip())
                except ValueError:
                    pass
            # Prefer harness work_ms; fall back to wall-clock mean (pre-harness).
            stripped = line.strip()
            if stripped.startswith("work_ms:"):
                try:
                    ms = float(stripped.split(":")[-1].strip())
                except ValueError:
                    pass
            elif ms is None and "Mean frame time:" in line:
                try:
                    ms = float(line.split(":")[-1].strip().replace("ms", "").strip())
                except ValueError:
                    pass
        rows.append((label, quality, fps, ms))
    print("\n=== suite summary ===")
    print(f"{'mode':<18} {'quality':<10} {'fps':>8} {'ms':>8}")
    print("-" * 48)
    for mode, quality, fps, ms in rows:
        fps_s = f"{fps:.1f}" if fps is not None else "?"
        ms_s = f"{ms:.2f}" if ms is not None else "?"
        print(f"{mode:<18} {quality:<10} {fps_s:>8} {ms_s:>8}")
    print("=" * 48)
    sys.exit(0)

# ---------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------
from scena import *  # noqa: E402
from scena.orchestration import ScenaFramework  # noqa: E402
from scena.process import set_watchdog  # noqa: E402

if args.bench or args.profile:
    set_watchdog(False)

W, H = 1200, 800
init(
    width=W, height=H, window_scale=0.72,
    title=f"Scena realistic scene [{args.mode}/{args.quality}]",
)
canvas.background = (0.04, 0.045, 0.07, 1)
set_fx_auto(False)
canvas.fx_quality = args.quality
if args.cull:
    canvas.cull_offscreen = True
canvas.reset_shape_fx_surface_stats()

rng = random.Random(args.seed)

WANT_POST = args.mode in ("realistic", "fleet", "heroes", "heroes_mass")
WANT_HEROES = args.mode in ("realistic", "heroes", "nopost")
WANT_HEROES_MASS = args.mode == "heroes_mass"
WANT_FLEET = args.mode in ("realistic", "fleet", "nopost", "baseline", "geom")
WANT_FX = args.mode not in ("baseline", "geom")
WANT_SPATIAL = (
    WANT_FX
    and WANT_HEROES
    and args.mode not in ("fleet", "heroes_mass")
    and not args.no_spatial
)

if args.mode in ("baseline", "geom"):
    WANT_POST = False
    WANT_HEROES = False
    WANT_SPATIAL = False

if WANT_HEROES_MASS:
    WANT_FLEET = False
    WANT_HEROES = False  # mass grid installs its own multipass set
    WANT_SPATIAL = False
    if args.post_only is None:
        # Isolate paint cost unless user forces post
        WANT_POST = False
# Shared materials (batch-friendly filter keys)
_GLOW_FLEET = GlowFilter(radius=7, sigma=4.5, color=(0.45, 0.85, 1.0, 0.75))
_SHADOW_FLEET = DropShadow(dx=3, dy=-4, sigma=3.5, color=(0, 0, 0, 0.45))
_GLOW_LOOK = Glow(color="cyan", amount=0.85, radius=8, sigma=5)
_COLORS = (
    "crimson", "orange", "gold", "lime green", "turquoise", "cyan",
    "dodger blue", "orchid", "hot pink", "salmon", "sea green",
    "sky blue", "violet", "tomato", "cornflower blue", "khaki",
)

# Reactive scene clocks (drive FormulaLink / @=)
st.create("t", initial=0.0)
st.create("pulse", initial=0.5)
st.create("spin", initial=0.0)

# Inventory
_inv = {
    "cheap": 0,
    "hero": 0,
    "line": 0,
    "filter_glow": 0,
    "filter_shadow": 0,
    "visual_compiled": 0,
    "multipass_names": [],
    "spatial": [],
}
_movers = []       # free poses animated in update
_hero_movers = []
_n_shapes = 0
_links_formula = 0
_links_line = 0


def _color(i: int) -> str:
    return _COLORS[i % len(_COLORS)]


def _count(shp, *, tier: str = "cheap", note: str = ""):
    global _n_shapes
    _n_shapes += 1
    if tier == "line":
        _inv["line"] += 1
        _inv["cheap"] += 1
    elif tier == "hero":
        _inv["hero"] += 1
        if note:
            _inv["multipass_names"].append(note)
    else:
        _inv["cheap"] += 1
    return shp


def _apply_cheap(shp, style: str, i: int) -> None:
    """Non-multipass surface (solids on baseline).

    Fleet styling is intentionally mostly solids. Glow is selective:
    shared GlowFilter / Glow look only on sparse "highlight" units (~half-dozen
    orbiters), not the whole pack — matches real authoring and isolates
    filter-batch cost from the base fleet.
    """
    cname = _color(i)
    if not WANT_FX:
        shp.set_color(cname)
        shp.line_width = 1.0
        return
    if style == "paint":
        shp.visual = cname
        _inv["visual_compiled"] += 1
    elif style == "ghost":
        shp.set_color(cname)
        shp.set_alpha(0.42)
        _inv["visual_compiled"] += 1
    elif style == "glow_look":
        # Shared single cyan Glow stamp (one batch key) for highlights.
        shp.set_color(cname)
        shp.glow = _GLOW_LOOK
        _inv["visual_compiled"] += 1
        _inv["filter_glow"] += 1  # Glow stamp wraps GlowFilter
    elif style == "outer_glow":
        shp.set_color(cname)
        shp.line = None
        shp.fill_filter = _GLOW_FLEET
        _inv["filter_glow"] += 1
    elif style == "shadow":
        shp.set_color(cname)
        shp.fill_filter = _SHADOW_FLEET
        _inv["filter_shadow"] += 1
    else:
        shp.set_color(cname)
        shp.line_width = 1.0


def _orbiter_style(i: int) -> str:
    """Mostly paint/ghost; ~6/50 glow highlights; occasional shared shadow."""
    # Sparse elite glow: indices 0, 9, 18, 27, 36, 45 → 6 units
    if i % 9 == 0:
        return "outer_glow" if (i // 9) % 2 == 0 else "glow_look"
    # Soft ground contact on ~1/8 of the rest (not glow)
    if i % 8 == 3:
        return "shadow"
    # Fill: ~half paint, half ghost
    return "paint" if i % 2 == 0 else "ghost"


def _make_orbiter(i: int, *, cx: float, cy: float, r: float, ang0: float):
    x = cx + math.cos(ang0) * r
    y = cy + math.sin(ang0) * r
    kind = i % 5
    if kind == 0:
        shp = Circle(center=(x, y), radius=7 + (i % 4))
    elif kind == 1:
        shp = Square(center=(x, y), length=12 + (i % 4), angle=i * 11)
    elif kind == 2:
        shp = EquilateralTriangle(center=(x, y), radius=10, angle=i * 7)
    elif kind == 3:
        shp = RegularPolygon(n=5, center=(x, y), radius=9, angle=i * 9)
    else:
        shp = Ellipse(center=(x, y), width=16 + (i % 3), height=10, angle=i * 5)
    _apply_cheap(shp, _orbiter_style(i), i)
    _count(shp, tier="cheap")
    _movers.append({
        "shape": shp, "kind": "orb",
        "cx0": cx, "cy0": cy, "r": r, "ry": r,
        "ang0": ang0,
        "orbit": 0.22 + (i % 5) * 0.04,
        "spin": 18 + (i % 7) * 9,
    })
    return shp


# ---- soft background plate (not gameplay inventory) -----------------------
bg = Rect(center=(W / 2, H / 2), width=W + 60, height=H + 60)
bg.fill = Gradient("ocean", type="radial", size=max(W, H) * 0.55)
bg.line = None
bg.move_to_back()

# ===========================================================================
# FLEET — explicit counts totaling ~130 cheap + ~20 lines with heroes ≈ 150
#
#   50 orbiters
#   12 satellites (linked) + 12 connector lines
#    8 cross lines                          → 20 lines total
#   20 twins (@= angle / size / center)
#   28 debris / rim markers
#   20 multipass heroes (elsewhere)
#   ─────────────────
#  150 shapes
# ===========================================================================
orbiters = []
if WANT_FLEET:
    N_ORB = 50
    CX, CY = W * 0.40, H * 0.52
    for i in range(N_ORB):
        ang0 = i * (math.tau / N_ORB) + rng.uniform(-0.03, 0.03)
        ring = 0 if (i % 3) else 1
        r = (150 if ring == 0 else 265) + rng.uniform(-10, 10)
        orbiters.append(_make_orbiter(i, cx=CX, cy=CY, r=r, ang0=ang0))

    # --- satellites + connector lines (12) ---------------------------------
    for i, host in enumerate(orbiters[:12]):
        if hasattr(host, "top_right"):
            anchor = host.top_right
        elif hasattr(host, "points") and len(host.points) >= 1:
            anchor = host.points[0]
        else:
            anchor = host.center
        sat = Circle(center=lambda: anchor, radius=5.0)
        sat.set_color(_color(i + 4))
        sat.set_alpha(0.9)
        base = 4.5 + (i % 4)
        sat["radius"] @= (lambda b=base, a=2.0: b + a * st.pulse)
        _links_formula += 1
        if WANT_FX and i % 3 == 0:
            sat.set_color(_color(i + 4))
            sat.set_alpha(0.5)
        _count(sat, tier="cheap")

        ln = Line(p1=lambda: host.center, p2=lambda: sat.center)
        ln.set_color("gray")
        ln.line_width = 1.0
        ln.set_alpha(0.4)
        _count(ln, tier="line")
        _links_line += 1

    # --- cross-links between orbiters (8 more → 20 lines) ------------------
    for k in range(8):
        a = orbiters[k * 3 % len(orbiters)]
        b = orbiters[(k * 3 + 11) % len(orbiters)]
        ln = Line(p1=lambda: a.center, p2=lambda: b.center)
        ln.set_color("steel blue")
        ln.line_width = 1.0
        ln.set_alpha(0.22)
        _count(ln, tier="line")
        _links_line += 1

    # --- twin trackers with @= (20) ----------------------------------------
    for i, host in enumerate(orbiters[12:32]):
        hx = host.center.x
        hy = host.center.y
        ox = hx + 34 + rng.uniform(-3, 3)
        oy = hy + rng.uniform(-8, 8)
        cls = type(host)
        if getattr(getattr(cls, "angle", None), "_is_field_slot", False) or getattr(
            getattr(cls, "angle", None), "_is_field_slot", False
        ):
            twin = Square(center=(ox, oy), length=11, angle=0)
            twin["angle"] @= (lambda h=host: h.angle)
            twin["length"] @= (
                lambda h=host, b=11.0: b + 3.0 * st.pulse
                + 0.15 * getattr(h, "radius", getattr(h, "length", 10))
            )
            _links_formula += 2
        else:
            twin = Circle(center=(ox, oy), radius=7)
            twin.center["x"] @= (lambda h=host, d=34.0: h.center.x + d)
            twin.center["y"] @= (lambda h=host: h.center.y)
            twin["radius"] @= (lambda b=7.0: b + 2.5 * st.pulse)
            _links_formula += 3
        _apply_cheap(twin, "paint" if i % 2 == 0 else "ghost", i + 60)
        twin.set_alpha(0.72)
        _count(twin, tier="cheap")

    # --- rim / debris markers (28 → total ≈ 150 with heroes) ---------------
    for i in range(28):
        ang = i * (math.tau / 28) + 0.15
        rx, ry = 340, 235
        x = W * 0.5 + math.cos(ang) * rx
        y = H * 0.5 + math.sin(ang) * ry
        kind = i % 3
        if kind == 0:
            m = Circle(center=(x, y), radius=4 + (i % 3))
        elif kind == 1:
            m = Square(center=(x, y), length=8, angle=i * 15)
        else:
            m = RegularPolygon(n=3, center=(x, y), radius=7, angle=i * 10)
        # Debris never glows — solids / ghosts only (cheap filler density)
        _apply_cheap(m, "paint" if i % 2 == 0 else "ghost", i + 80)
        m.set_alpha(0.55)
        _count(m, tier="cheap")
        _movers.append({
            "shape": m, "kind": "rim",
            "cx0": W * 0.5, "cy0": H * 0.5,
            "r": rx, "ry": ry,
            "ang0": ang,
            "orbit": 0.07 * (1 if i % 2 == 0 else -1),
            "spin": 12.0 if kind else 0.0,
        })


# ===========================================================================
# HEROES — multipass looks, mostly 1× each (realistic elite budget ≈ 20)
# ===========================================================================
def _hero(shp, look, name: str, **move):
    """Install a multipass hero (enabled for heroes / realistic / heroes_mass)."""
    if not WANT_HEROES and not WANT_HEROES_MASS:
        return None
    if WANT_FX:
        shp.visual = look
    else:
        shp.set_color("gold")
    _count(shp, tier="hero", note=name)
    if move:
        _hero_movers.append({"shape": shp, **move})
    return shp


if WANT_HEROES:
    # 1 Shield for the whole scene
    _hero(
        Circle(center=(W * 0.72, H * 0.42), radius=42),
        Shield(style="bubble", color=(0.35, 0.75, 1.0)),
        "Shield",
        kind="spin", spin=18.0,
    )
    _hero(
        Circle(center=(W * 0.18, H * 0.68), radius=36),
        ElectricField(color=(0.55, 0.85, 1.0), amount=5.0),
        "ElectricField",
        kind="spin", spin=-22.0,
    )
    _hero(
        RegularPolygon(n=6, center=(W * 0.78, H * 0.72), radius=28, angle=0),
        Neon(color=(0.3, 0.95, 1.0), amount=1.1),
        "Neon",
        kind="spin", spin=30.0,
    )

    laser = Line(p1=Point(W * 0.08, H * 0.22), p2=Point(W * 0.38, H * 0.18))
    laser.line_width = 3.0
    _hero(laser, Laser(color=(1.0, 0.15, 0.12), amount=1.0), "Laser")

    lstack = Line(p1=Point(W * 0.62, H * 0.14), p2=Point(W * 0.92, H * 0.28))
    lstack.line_width = 2.5
    _hero(lstack, Laser(color=(0.2, 0.9, 1.0)), "Laser cyan")

    _hero(
        Circle(center=(W * 0.55, H * 0.22), radius=16),
        Bolt(color=(0.7, 0.4, 1.0), intensity=1.0),
        "Bolt",
        kind="bob", amp=10.0, base_y=H * 0.22, speed=2.4,
    )
    _hero(
        Ellipse(center=(W * 0.88, H * 0.55), width=48, height=34, angle=12),
        Gel(color=(0.2, 0.95, 0.55)),
        "Gel",
        kind="spin", spin=14.0,
    )

    ebolt = Line(p1=Point(W * 0.12, H * 0.88), p2=Point(W * 0.32, H * 0.78))
    ebolt.line_width = 2.5
    _hero(ebolt, ElectricBolt(color=(0.7, 0.9, 1.0)), "ElectricBolt")

    _hero(
        Rect(center=(W * 0.48, H * 0.78), width=54, height=28, angle=-8),
        Metal(color=(0.75, 0.78, 0.85)),
        "Metal",
        kind="spin", spin=10.0,
    )
    _hero(
        RegularPolygon(n=5, center=(W * 0.36, H * 0.28), radius=26, angle=0),
        Rim(color=(1.0, 0.55, 0.15)),
        "Rim",
        kind="spin", spin=-25.0,
    )
    _hero(
        Square(center=(W * 0.22, H * 0.38), length=32, angle=15),
        InkBleed(color=(0.15, 0.05, 0.25)),
        "InkBleed",
        kind="spin", spin=12.0,
    )
    _hero(
        Circle(center=(W * 0.65, H * 0.82), radius=30),
        Halo(color=(0.55, 0.35, 1.0), amount=1.0),
        "Halo",
        kind="spin", spin=20.0,
    )
    _hero(
        Circle(center=(W * 0.90, H * 0.32), radius=28),
        GearShell(color=(0.2, 0.85, 0.95)),
        "GearShell",
        kind="spin", spin=-16.0,
    )
    _hero(
        Rect(center=(W * 0.50, H * 0.62), width=70, height=36, angle=0),
        Water(),
        "Water",
        kind="bob", amp=6.0, base_y=H * 0.62, speed=1.3,
    )
    _hero(
        EquilateralTriangle(center=(W * 0.34, H * 0.88), radius=22, angle=0),
        Extrude(depth=18, layers=4),
        "Extrude",
        kind="spin", spin=28.0,
    )
    _hero(
        Circle(center=(W * 0.10, H * 0.50), radius=24),
        MultiBorder(layers=3, spread=0.14),
        "MultiBorder",
        kind="spin", spin=15.0,
    )
    _hero(
        Circle(center=(W * 0.82, H * 0.18), radius=22),
        Sphere(color=(0.5, 0.7, 1.0)),
        "Sphere",
        kind="bob", amp=8.0, base_y=H * 0.18, speed=1.8,
    )
    _hero(
        Circle(center=(W * 0.58, H * 0.48), radius=20),
        DashRing(color=(1.0, 0.8, 0.3)),
        "DashRing",
        kind="spin", spin=40.0,
    )
    tr = Line(p1=Point(W * 0.40, H * 0.10), p2=Point(W * 0.55, H * 0.10))
    tr.line_width = 2.0
    _hero(tr, Tracer(color=(1.0, 0.4, 0.7)), "Tracer")
    # 20th: organic outline on a free poly
    _hero(
        RegularPolygon(n=7, center=(W * 0.42, H * 0.90), radius=20, angle=0),
        OrganicOutline(amount=2.2, speed=1.0),
        "OrganicOutline",
        kind="spin", spin=22.0,
    )


# ===========================================================================
# HEROES MASS — dense multipass grid (DrawCache A/B)
# ===========================================================================
if WANT_HEROES_MASS:
    # Heavy + medium multipass looks cycling across a grid. Prefer shared
    # instances when params match so interning stays fair.
    _HEAVY = [
        ("Neon", lambda c: Neon(color=c, amount=1.05)),
        ("ElectricField", lambda c: ElectricField(color=c, amount=5.0)),
        ("Shield", lambda c: Shield(style="bubble")),
        ("Gel", lambda c: Gel(color=c)),
        ("GearShell", lambda c: GearShell(color=c)),
        ("Rim", lambda c: Rim(color=c)),
        ("Metal", lambda c: Metal(color=c)),
        ("Halo", lambda c: Halo(color=c, amount=1.0)),
        ("MultiBorder", lambda c: MultiBorder(layers=3, spread=0.14)),
        ("InkBleed", lambda c: InkBleed(color=c)),
        ("Extrude", lambda c: Extrude(depth=16, layers=4)),
        ("DashRing", lambda c: DashRing(color=c)),
    ]
    n = max(4, int(args.n_heroes))
    cols = max(1, int(math.ceil(math.sqrt(n * W / H))))
    rows = max(1, int(math.ceil(n / cols)))
    for i in range(n):
        c = i % cols
        r = i // cols
        x = 60 + c * ((W - 120) / max(cols - 1, 1))
        y = 60 + r * ((H - 120) / max(rows - 1, 1))
        name, factory = _HEAVY[i % len(_HEAVY)]
        cname = _color(i)
        kind = i % 4
        if kind == 0:
            shp = Circle(center=(x, y), radius=16 + (i % 5))
        elif kind == 1:
            shp = Square(center=(x, y), length=28 + (i % 4), angle=i * 9)
        elif kind == 2:
            shp = EquilateralTriangle(center=(x, y), radius=18, angle=i * 7)
        else:
            shp = RegularPolygon(n=5 + (i % 3), center=(x, y), radius=16, angle=i * 5)
        try:
            shp.set_color(cname)
        except Exception:
            pass
        _hero(
            shp,
            factory(cname),
            f"{name}#{i}",
            kind="spin", spin=12.0 + (i % 7) * 3.0,
        )


# ===========================================================================
# Spatial décor (optional — not shape-counted)
# ===========================================================================
if WANT_SPATIAL:
    Fire(style="plume", center=(W * 0.14, H * 0.16), width=22, amount=0.85, rate=50)
    Fire(style="embers", center=(W * 0.86, H * 0.88), width=20, amount=0.7, rate=28)
    _inv["spatial"] = ["Fire plume", "Fire embers"]


# ===========================================================================
# Canvas post
# ===========================================================================
_fx = {}
if args.post_only == "none":
    WANT_POST = False
if args.post_only in ("vignette", "grain", "bloom", "stack"):
    WANT_POST = True

if WANT_POST:
    if args.post_only == "vignette":
        _fx["vignette"] = canvas.effects.add(Vignette(amount=0.85))
    elif args.post_only == "grain":
        _fx["grain"] = canvas.effects.add(Grain())
    elif args.post_only == "bloom":
        _fx["bloom"] = canvas.effects.add(Bloom())
    else:
        # default stack or post_only == "stack"
        _fx["vignette"] = canvas.effects.add(Vignette(amount=0.85))
        _fx["grain"] = canvas.effects.add(Grain())
        _fx["bloom"] = canvas.effects.add(Bloom())


# ===========================================================================
# Inventory print
# ===========================================================================
_hn = _inv["multipass_names"]
_hn_show = ", ".join(_hn[:24]) + ("…" if len(_hn) > 24 else "") if _hn else "(none)"
print(
    f"[app_scene_realistic] mode={args.mode} Q={args.quality}\n"
    f"  shapes total={_n_shapes}  cheap={_inv['cheap']}  heroes={_inv['hero']}  "
    f"lines={_inv['line']}\n"
    f"  compiled visuals≈{_inv['visual_compiled']}  "
    f"glow_units={_inv['filter_glow']}  shadows={_inv['filter_shadow']}  "
    f"formula @≈{_links_formula}  line-ctor≈{_links_line}\n"
    f"  heroes: {_hn_show}\n"
    f"  spatial: {', '.join(_inv['spatial']) or '(none)'}  "
    f"post={list(_fx.keys()) or '(none)'}  "
    f"cull={canvas.cull_offscreen}  "
    f"batch={canvas.batch_shared_filters}  "
    f"shape_fx={canvas.shape_fx_scale} post_fx={canvas.post_fx_scale}"
)

Text(
    text=(
        f"realistic · {_n_shapes} shapes · {_inv['hero']} heroes · "
        f"{_inv['line']} lines · Q={args.quality}"
        f"{' · STATIC' if _STATIC else ''}"
    ),
    top_left=(16, H - 11), font_size=14,
    color=Color(0.82, 0.86, 0.92, 1),
)
Text(
    text="ESC quit · Ctrl+Shift+3 quality ·  --bench / --profile",
    top_left=(16, H - 36), font_size=12,
    color=Color(0.55, 0.6, 0.68, 1),
)


# ===========================================================================
# Bench / profile
# ===========================================================================
_prof = FrameProfiler.install() if args.profile else None
_t = 0.0
_bench_t0 = None
_frame_times = []
_prof_started = False


def _print_gpu_extras(fw) -> None:
    stats = canvas.shape_fx_surface_stats()
    print(
        f"  FB={fw.fb_width}x{fw.fb_height}  design={W}x{H}  "
        f"cheap={_inv['cheap']} heroes={_inv['hero']} lines={_inv['line']}  "
        f"batch={canvas.batch_shared_filters}  "
        f"effects={len(canvas.effects)}  "
        f"cull={canvas.cull_offscreen}"
    )
    print(
        f"  shape_fx_RT  allocs={stats['allocs']} reuses={stats['reuses']} "
        f"pool={stats['pool']}"
    )
    if _inv["multipass_names"]:
        shown = _inv["multipass_names"]
        if len(shown) > 24:
            shown = shown[:24] + [f"… +{len(_inv['multipass_names']) - 24}"]
        print(f"  multipass: {', '.join(shown)}")


def _finish():
    print_report(
        f"app_scene_realistic [{args.mode}/{args.quality}]",
        _frame_times,
        _n_shapes,
    )
    fw = ScenaFramework.get_instance()
    _print_gpu_extras(fw)
    if _prof is not None:
        _prof.report(
            f"app_scene_realistic — mode={args.mode} Q={args.quality}"
        )
        FrameProfiler.uninstall()
    import glfw
    glfw.set_window_should_close(fw._window, True)


def _update_body(dt):
    global _t, _bench_t0, _prof_started
    _t += dt

    if not args.bench and keyp.once("ESC"):
        import glfw
        glfw.set_window_should_close(ScenaFramework.get_instance()._window, True)
        return

    st.t = float(st.t) + dt
    st.pulse = 0.5 + 0.5 * math.sin(float(st.t) * 1.7)
    st.spin = (float(st.spin) + 55.0 * dt) % 360.0

    if not _STATIC:
        t = float(st.t)
        for m in _movers:
            shp = m["shape"]
            ang = m["ang0"] + t * m["orbit"]
            shp.move_to(
                m["cx0"] + math.cos(ang) * m["r"],
                m["cy0"] + math.sin(ang) * m["ry"],
            )
            if m.get("spin") and hasattr(shp, "rotate_by"):
                shp.rotate_by(m["spin"] * dt)
        for m in _hero_movers:
            shp = m["shape"]
            k = m["kind"]
            if k == "spin" and hasattr(shp, "rotate_by"):
                try:
                    shp.rotate_by(m["spin"] * dt)
                except Exception:
                    pass
            elif k == "bob":
                shp.move_to(shp.center.x, m["base_y"] + m["amp"] * math.sin(t * m["speed"]))

    # Profile-only (no --bench): wall-clock window, then exit.
    if args.bench:
        return
    if _prof is None:
        return
    now = time.perf_counter()
    if _bench_t0 is None:
        _bench_t0 = now
        return
    elapsed = now - _bench_t0
    if elapsed < args.warmup:
        return
    if not _prof_started:
        canvas.reset_shape_fx_surface_stats()
        _prof.start_recording()
        _prof_started = True
    if args.profile_seconds is not None and elapsed >= args.warmup + args.profile_seconds:
        _finish()


update = _prof.wrap_update(_update_body) if _prof is not None else _update_body

canvas.framerate = "max" if (args.bench or args.profile) else "vsync60"

if args.bench:
    fw = ScenaFramework.get_instance()
    stats = empty_phase_stats()
    _fx_reset = {"done": False}

    def on_frame(framework, recording):
        if recording and not _fx_reset["done"]:
            canvas.reset_shape_fx_surface_stats()
            if _prof is not None:
                _prof.start_recording()
            _fx_reset["done"] = True

    install_phase_run(
        fw,
        duration=args.duration,
        warmup=args.warmup,
        stats=stats,
        on_frame=on_frame,
    )
    run()
    print_phase_report(
        f"gpu_mix [{args.mode}/{args.quality}] n_shapes={_n_shapes}",
        stats,
    )
    fw = ScenaFramework.get_instance()
    _print_gpu_extras(fw)
    avg = average_phase_stats(stats)
    payload = {
        "mode": args.mode,
        "quality": args.quality,
        "n_shapes": _n_shapes,
        "n_cheap": _inv["cheap"],
        "n_heroes": _inv["hero"],
        "n_lines": _inv["line"],
        "fb_width": int(fw.fb_width) if fw is not None else 0,
        "fb_height": int(fw.fb_height) if fw is not None else 0,
        "design_w": W,
        "design_h": H,
        "fps": avg["fps"],
        "work_ms": avg["work_ms"],
        "tick_ms": avg["tick_ms"],
        "coll_ms": avg["coll_ms"],
        "flush_ms": avg["flush_ms"],
        "draw_ms": avg["draw_ms"],
        "post_ms": avg["post_ms"],
        "submit_ms": avg["submit_ms"],
        "present_ms": avg["present_ms"],
        "frames": avg["frames"],
    }
    print(
        f"RESULT_JSON: "
        f'{{"fps": {avg["fps"]:.2f}, "work_ms": {avg["work_ms"]:.4f}, '
        f'"draw_ms": {avg["draw_ms"]:.4f}, "post_ms": {avg["post_ms"]:.4f}, '
        f'"submit_ms": {avg["submit_ms"]:.4f}}}'
    )
    if args.json_path:
        write_json(args.json_path, payload)
    if _prof is not None:
        _prof.report(f"gpu_mix — mode={args.mode} Q={args.quality}")
        FrameProfiler.uninstall()
else:
    run()
