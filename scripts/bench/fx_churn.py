"""
fx_churn.py — cycle canvas posts / shape looks / spawn, then return to none.

Diagnoses the shape_fx "back to none and FPS dipped" leak: leftover inventory
plus idle work_ms after each family, including the direct window-FB idle
cost after leaving post.

Usage
-----
    python scripts/bench/fx_churn.py
    python scripts/bench/fx_churn.py --quick --repeats 4
    python scripts/bench/fx_churn.py --isolate canvas --json /tmp/fx_churn.json
    python scripts/bench/fx_churn.py --lab          # shape_fx window_scale / size
"""
from __future__ import annotations

import argparse
import gc
import math
import os
import random
import sys
import time
from typing import Any, Callable, Dict, List, Sequence, Tuple

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--isolate",
    default="all",
    choices=("all", "canvas", "visual", "sksl", "trails", "hit", "spawn", "path"),
    help="run only this family (default all)",
)
parser.add_argument("--dwell", type=int, default=6, help="frames to hold each effect")
parser.add_argument("--idle-frames", type=int, default=45, help="idle sample frames after none")
parser.add_argument("--warmup-frames", type=int, default=50, help="discarded frames before baseline")
parser.add_argument("--n", type=int, default=48, help="persistent mover count")
parser.add_argument("--quality", default="high", choices=("low", "medium", "high", "max"))
parser.add_argument("--quick", action="store_true", help="fewer effects / shorter idle")
parser.add_argument(
    "--lab", action="store_true",
    help="match shape_fx window (1200×800, window_scale=0.75). Default is design==window.",
)
parser.add_argument("--no-bg", action="store_true", help="solid bg instead of image wallpaper")
parser.add_argument("--repeats", type=int, default=1, help="repeat canvas+visual cycles (slope)")
parser.add_argument("--json", dest="json_path", default=None)
parser.add_argument("--warn-work-ms", type=float, default=0.20,
                    help="idle tail_ms rise vs warm baseline that warns")
args, _ = parser.parse_known_args()

if args.quick:
    args.dwell = max(2, min(args.dwell, 3))
    args.idle_frames = max(16, min(args.idle_frames, 24))
    args.warmup_frames = max(20, min(args.warmup_frames, 24))

_BENCH = os.path.dirname(os.path.abspath(__file__))
if _BENCH not in sys.path:
    sys.path.insert(0, _BENCH)
from harness import write_json  # noqa: E402

from scena import *  # noqa: E402
from scena.orchestration import ScenaFramework  # noqa: E402
from scena.process import get_scheduler  # noqa: E402
from scena.collision import get_collision_system  # noqa: E402
from scena.state import get_scena_system  # noqa: E402
from scena.stamps import is_stamp_visual  # noqa: E402
from scena.style import ProceduralFill  # noqa: E402
from scena.visuals import Visual  # noqa: E402
from scena.cover import reset_cover, is_cover_active  # noqa: E402
from scena import transients as _transients  # noqa: E402
from scena import spatial_fx as _spatial  # noqa: E402
from scena.recipes import _RECIPE_CACHE  # noqa: E402
from scena.canvas import ScenaCanvas  # noqa: E402

if args.lab:
    W, H = 1200, 800
    init(width=W, height=H, window_scale=0.75, title="Bench — FX churn / leak")
else:
    W, H = 1000, 700
    init(width=W, height=H, window_scale=0.65, title="Bench — FX churn / leak")
canvas.fx_quality = args.quality
set_fx_auto(False)
canvas.batch_shared_filters = True
if args.no_bg:
    canvas.background = (0.07, 0.08, 0.10, 1)
else:
    try:
        Wallpaper("examples/media/images/bg3.jpg", fit="cover")
    except Exception:
        canvas.background = (0.07, 0.08, 0.10, 1)

# ---------------------------------------------------------------------------
# Persistent movers (shape_fx-like mix, no HUD sliders)
# ---------------------------------------------------------------------------
COLORS = (
    "cyan", "magenta", "gold", "lime", "orange",
    "dodger blue", "orchid", "white", "tomato", "green",
)
movers: List[Dict[str, Any]] = []
random.seed(42)
_line_count = max(4, args.n // 4)
_filled_count = max(0, args.n - _line_count)
_n_grad_fills = min(20, _filled_count)
_n_tex_sprite = min(4, _filled_count)
_n_tex_tile = min(4, max(0, _filled_count - _n_tex_sprite))
try:
    _tex_sprite = Texture("examples/media/k-textures/floor_wood_planks.png", fit="cover")
    _tex_tile = Texture("examples/media/k-textures/floor_wood_planks.png", fit="tile", tile_size=40)
except Exception:
    _tex_sprite = _tex_tile = None

for i in range(_filled_count):
    kind = i % 6
    x = random.uniform(80, W - 80)
    y = random.uniform(80, H - 80)
    size = random.uniform(12, 55)
    ang = random.uniform(0, 360)
    if kind == 0:
        shp = Circle(center=(x, y), radius=size * 0.5)
    elif kind == 1:
        shp = Square(center=(x, y), length=size, angle=ang)
    elif kind == 2:
        shp = Rect(center=(x, y), width=size * 1.4, height=size * 0.7, angle=ang)
    elif kind == 3:
        shp = EquilateralTriangle(center=(x, y), radius=size * 0.55, angle=ang)
    elif kind == 4:
        shp = RegularPolygon(n=5 + (i % 3), center=(x, y), radius=size * 0.5, angle=ang)
    else:
        shp = Ellipse(center=(x, y), width=size * 1.2, height=size * 0.55, angle=ang)
    color = COLORS[i % len(COLORS)]
    shp.set_color(color)
    shp.line_width = 2.0
    if i < _n_tex_sprite and _tex_sprite is not None:
        shp.fill = _tex_sprite
    elif i < _n_tex_sprite + _n_tex_tile and _tex_tile is not None:
        shp.fill = _tex_tile
    elif i < _n_grad_fills:
        shp.fill = Gradient("plasma", type="radial", size=max(18.0, size * 0.85))
    movers.append({
        "shape": shp, "ox": x, "oy": y, "base_color": color,
        "base_fill": shp.fill, "base_line": shp.line,
        "amp": 16 + (i % 5) * 8, "freq": 0.4 + (i % 7) * 0.1,
        "phase": i * 0.37, "spin": (i % 9 - 4) * 20.0,
    })

for i in range(_line_count):
    cx = random.uniform(100, W - 100)
    cy = random.uniform(100, H - 100)
    length = random.uniform(40, 120)
    ang = random.uniform(0, 360)
    rad = math.radians(ang)
    hx, hy = math.cos(rad) * length * 0.5, math.sin(rad) * length * 0.5
    color = COLORS[(i + 3) % len(COLORS)]
    shp = Line(p1=(cx - hx, cy - hy), p2=(cx + hx, cy + hy))
    shp.set_color(color)
    shp.line_width = 2.0
    movers.append({
        "shape": shp, "ox": cx, "oy": cy, "base_color": color,
        "base_fill": None, "base_line": shp.line,
        "amp": 12 + (i % 4) * 6, "freq": 0.35 + (i % 5) * 0.1,
        "phase": i * 0.51, "spin": 0.0,
    })

hud = Text(text="", top_left=(20, H - 10), font_size=15, color=Color(0.9, 0.92, 1.0, 1))
status = Text(text="starting", top_left=(20, H - 35), font_size=14, color=Color(0.85, 0.8, 0.5, 1))
# Same slider pool cost as shape_fx (rebound, never spawned per mode).
for i in range(6):
    s = Slider(label="—", top_left=(16, H - 130 - i * 28 + 28), min_value=0, max_value=100, initial=50, show_value=True)
    s.enabled = False

# ---------------------------------------------------------------------------
# Catalogs — representative of shape_fx A/S and Q/W
# ---------------------------------------------------------------------------
def _canvas_posts() -> List[Tuple[str, Callable]]:
    rows = [
        ("vignette", Vignette),
        ("grain", Grain),
        ("bloom", Bloom),
        ("grade", Grade),
        ("chroma", Chroma),
        ("pixelate", Pixelate),
        ("haze", Haze),
        ("crt", Crt),
        ("fog", Fog),
        ("scanlines", Scanlines),
        ("screenblur", ScreenBlur),
        ("lamp", Lamp),
        ("distant", DistantLight),
        ("spotlight", Spotlight),
        ("rays", GodRays),
        ("prism", Prism),
        ("kaleido", Kaleidoscope),
        ("wash", Wash),
        ("colorsweep", ColorSweep),
        ("plasmawash", ColorWash),
        ("nebulabloom", CosmicBloom),
        ("vortex", Vortex),
        ("zoomblur", ZoomBlur),
    ]
    if args.quick:
        return [r for r in rows if r[0] in (
            "vignette", "bloom", "grade", "chroma", "prism",
            "plasmawash", "nebulabloom", "kaleido",
        )]
    return rows


def _sksl_posts() -> List[Tuple[str, Callable]]:
    return [
        ("prism", Prism),
        ("kaleido", Kaleidoscope),
        ("plasmawash", ColorWash),
        ("nebulabloom", CosmicBloom),
        ("vortex", Vortex),
        ("zoomblur", ZoomBlur),
        ("colorsweep", ColorSweep),
        ("crt", Crt),
    ]


def _visuals() -> List[Tuple[str, Callable]]:
    rows = [
        ("glow", lambda: Glow(radius=12, sigma=10)),
        ("cheapglow", lambda: CheapGlow()),
        ("shadow", lambda: Shadow()),
        ("tail", lambda: Tail()),
        ("blur", lambda: Blur(sigma=4)),
        ("glowfilter", lambda: GlowFilter(radius=10, sigma=8)),
        ("dilate", lambda: Dilate(radius=4)),
        ("neon", lambda: Neon()),
        ("halo", lambda: Halo()),
        ("rim", lambda: Rim()),
        ("laser", lambda: Laser()),
        ("gearshell", lambda: GearShell()),
        ("electricfield", lambda: ElectricField()),
        ("electricbolt", lambda: ElectricBolt()),
        ("shield", lambda: Shield()),
        ("extrude", lambda: Extrude()),
        ("swell", lambda: Swell()),
        ("flame", lambda: Flame()),
        ("metal", lambda: Metal()),
        ("gel", lambda: Gel()),
        ("wave", lambda: Wave()),
        ("aurora", lambda: Aurora()),
        ("bolt", lambda: Bolt()),
        ("ink", lambda: Ink()),
        ("ink_bleed", lambda: InkBleed()),
        ("sphere", lambda: Sphere()),
        ("liquify", lambda: Liquify()),
        ("beat", lambda: Beat()),
        ("insetrim", lambda: InsetRim()),
        ("organic", lambda: OrganicOutline()),
        ("tracer", lambda: Tracer()),
        ("multiborder", lambda: MultiBorder()),
        ("wavefill", lambda: WaveFill(color="cyan")),
    ]
    if args.quick:
        keep = {
            "glow", "cheapglow", "blur", "neon", "halo", "laser",
            "gearshell", "electricfield", "shield", "extrude", "bolt",
        }
        return [r for r in rows if r[0] in keep]
    return rows


# ---------------------------------------------------------------------------
# Apply / clear (mirrors shape_fx SPACE / A/S / Q/W teardown)
# ---------------------------------------------------------------------------
def _restore_base(m: Dict[str, Any]) -> None:
    shp = m["shape"]
    try:
        fill, line = m.get("base_fill"), m.get("base_line")
        shp.fill = fill
        shp.line = line
    except Exception:
        bc = m.get("base_color")
        if bc is not None:
            try:
                shp.set_color(bc)
            except Exception:
                pass


def _clear_stamps(shp) -> None:
    shp.glow = None
    shp.shadow = None
    shp.tail = None
    try:
        shp.hue = None
    except Exception:
        pass


def _clear_shape_fx() -> None:
    for m in movers:
        shp = m["shape"]
        shp.visual = None
        shp.fill_filter = None
        shp.line_filter = None
        _clear_stamps(shp)
        try:
            shp.clear_transients()
        except Exception:
            pass
        _restore_base(m)


def _clear_canvas() -> None:
    canvas.effects.clear()
    try:
        reset_cover()
    except Exception:
        pass


def _clear_all() -> None:
    _clear_canvas()
    _clear_shape_fx()


def _apply_canvas(factory: Callable) -> None:
    _clear_canvas()
    canvas.effects.add(factory())


def _apply_look(factory: Callable) -> None:
    fx = factory()
    stamp = is_stamp_visual(fx)
    procedural = isinstance(fx, ProceduralFill)
    visual = isinstance(fx, Visual)
    for m in movers:
        shp = m["shape"]
        shp.fill_filter = None
        shp.line_filter = None
        _clear_stamps(shp)
        _restore_base(m)
        if stamp:
            shp.visual = None
            name = type(fx).__name__
            if name in ("Glow", "CheapGlow"):
                shp.glow = fx
            elif name == "Shadow":
                shp.shadow = fx
            elif name == "Tail":
                shp.tail = fx
            elif name == "HueShift":
                try:
                    shp.hue = fx
                except Exception:
                    pass
        elif procedural:
            shp.visual = None
            if type(shp).__name__ == "Line":
                continue
            try:
                shp.fill = fx
            except Exception:
                pass
        elif visual:
            try:
                shp.visual = fx
            except Exception:
                pass
        else:
            shp.visual = None
            try:
                shp.fill_filter = fx
            except Exception:
                pass


def _fire_hit() -> None:
    _clear_canvas()
    canvas.effects._hit_feedback()
    canvas.ripple_at(W * 0.5, H * 0.5, amount=1.0, shock=True, flash=False, shake=False)
    canvas.explosion_at(W * 0.35, H * 0.45, amount=1.0, shock=False, flash=False, shake=False)
    canvas.burst_at(W * 0.65, H * 0.45, radius=42.0, amount=1.0)


_churn: List[Any] = []


def _destroy_churn() -> None:
    for obj in list(_churn):
        try:
            obj.destroy()
        except Exception:
            pass
    _churn.clear()


def _run_churn() -> None:
    _destroy_churn()
    n = 8 if args.quick else 24
    for i in range(n):
        x = 80 + (i % 8) * 110
        y = 140 + (i // 8) * 90
        c = Circle(center=(x, y), radius=16 + (i % 5), group="churn").set_color(
            ("cyan", "magenta", "gold", "lime")[i % 4]
        )
        if i % 3 == 0:
            c.glow = Glow(radius=10, sigma=6)
        elif i % 3 == 1:
            c.visual = Neon()
        else:
            c.fill_filter = GlowFilter(radius=8, sigma=5)
        try:
            c.flash(0.08)
        except Exception:
            pass
        _churn.append(c)
    try:
        canvas.effects.add(Vignette(amount=0.25))
        canvas.effects.add(Bloom(intensity=0.3))
        canvas.ripple_at(W * 0.5, H * 0.4, amount=0.7)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------
def _rss_mb() -> float:
    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            return float(rss) / (1024.0 * 1024.0)
        return float(rss) / 1024.0
    except Exception:
        return float("nan")


def _len_weak(s) -> int:
    try:
        return len(s)
    except Exception:
        return -1


def _inventory() -> Dict[str, Any]:
    fw = ScenaFramework.get_instance()
    n_obj = 0
    n_visual = n_ff = n_lf = n_glow = n_shadow = n_tail = n_not_plain = 0
    leftover: List[str] = []
    try:
        for layer in fw._scena_draw.registry.layers.iter_draw_order():
            n_obj += len(layer._objects)
            for obj in layer._objects:
                if getattr(obj, "_visual", None) is not None:
                    n_visual += 1
                    leftover.append(f"visual:{type(obj._visual).__name__}")
                if getattr(obj, "_fill_filter", None) is not None:
                    n_ff += 1
                    leftover.append(f"fill_filter:{type(obj._fill_filter).__name__}")
                if getattr(obj, "_line_filter", None) is not None:
                    n_lf += 1
                    leftover.append(f"line_filter:{type(obj._line_filter).__name__}")
                if getattr(obj, "_glow", None) is not None:
                    n_glow += 1
                    leftover.append("glow")
                if getattr(obj, "_shadow", None) is not None:
                    n_shadow += 1
                    leftover.append("shadow")
                if getattr(obj, "_tail", None) is not None:
                    n_tail += 1
                    leftover.append("tail")
                if not getattr(obj, "_plain_blit", True):
                    n_not_plain += 1
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
    n_widgets = -1
    try:
        n_widgets = len(fw.widget_manager.widgets)
    except Exception:
        pass
    n_nodes = -1
    try:
        n_nodes = len(get_scena_system().dependency_graph.nodes)
    except Exception:
        pass
    stack = getattr(fw, "_post_fx_stack", None)
    fx_names = []
    n_post = 0
    hit_held = 0
    compose = 0
    mid = 0
    if stack is not None:
        n_post = len(stack)
        fx_names = [type(e).__name__ for e in stack]
        hit_held = 1 if getattr(stack, "_hit", None) is not None else 0
        compose = 1 if getattr(stack, "_compose_surface", None) is not None else 0
        mid = 1 if getattr(stack, "_mid_surface", None) is not None else 0
    pool = getattr(fw._scena_draw, "_shape_fx_pool", None) if fw._scena_draw else None
    pool_n = len(pool) if isinstance(pool, list) else 0
    cover = 0
    try:
        cover = 1 if is_cover_active() else 0
    except Exception:
        pass
    leftover_n = n_visual + n_ff + n_lf + n_glow + n_shadow + n_tail
    # Persistent movers should have no costume after none. Widgets/HUD Text
    # are expected. Count only leftover FX attachments.
    return {
        "objects": float(n_obj),
        "scheduler_handles": float(n_handles),
        "collision_enrolled": float(n_coll),
        "widgets": float(n_widgets),
        "graph_nodes": float(n_nodes),
        "canvas_effects": float(n_post),
        "canvas_effect_names": ",".join(fx_names),
        "hit_held": float(hit_held),
        "compose_rt": float(compose),
        "mid_rt": float(mid),
        "leftover_fx": float(leftover_n),
        "n_visual": float(n_visual),
        "n_fill_filter": float(n_ff),
        "n_line_filter": float(n_lf),
        "n_glow": float(n_glow),
        "n_shadow": float(n_shadow),
        "n_tail": float(n_tail),
        "n_not_plain": float(n_not_plain),
        "transients": float(_len_weak(getattr(_transients, "_active_shapes", None))),
        "spatial_fx": float(_len_weak(getattr(_spatial, "_active_fx", None))),
        "recipe_cache": float(len(_RECIPE_CACHE)),
        "cover": float(cover),
        "needs_scene_rt": float(1 if fw._needs_scene_rt() else 0),
        "post_draw_live": float(1 if fw._post_draw_live() else 0),
        "builtin_post": float(1 if fw._builtin_post_active() else 0),
        "was_using_post": float(1 if fw._was_using_post else 0),
        # Engine no longer has a scene-RT identity-blit path (dead since the
        # post→none recovery purge); column kept for JSON compatibility.
        "prefer_scene_blit": float(1 if getattr(fw, "_prefer_scene_blit", False) else 0),
        "has_scene_surf": float(1 if fw._scene_surface is not None else 0),
        "shape_fx_pool": float(pool_n),
        "leftover_kinds": ",".join(sorted(set(leftover))[:12]),
        "rss_mb": _rss_mb(),
        "fb_w": float(getattr(fw, "fb_width", 0) or 0),
        "fb_h": float(getattr(fw, "fb_height", 0) or 0),
        "pixel_ratio": float(getattr(fw, "pixel_ratio", 1.0) or 1.0),
    }


def _work_stats(samples: Sequence[float]) -> Dict[str, float]:
    if not samples:
        return {
            "idle_work_ms": float("nan"),
            "idle_p50_ms": float("nan"),
            "idle_p90_ms": float("nan"),
            "idle_head_ms": float("nan"),
            "idle_tail_ms": float("nan"),
            "fps_est": float("nan"),
        }
    xs = list(samples)
    xs_sorted = sorted(xs)
    p50 = xs_sorted[len(xs_sorted) // 2]
    p90 = xs_sorted[int(len(xs_sorted) * 0.9)]
    n_head = min(5, len(xs))
    n_tail = min(20, len(xs))
    mean = sum(xs) / len(xs)
    tail = sum(xs[-n_tail:]) / n_tail
    return {
        "idle_work_ms": mean,
        "idle_p50_ms": float(p50),
        "idle_p90_ms": float(p90),
        "idle_head_ms": sum(xs[:n_head]) / n_head,
        "idle_tail_ms": tail,
        "fps_est": (1000.0 / tail) if tail > 0 else float("nan"),
    }


# ---------------------------------------------------------------------------
# Step machine
# ---------------------------------------------------------------------------
# each step: (label, kind, payload)
# kind: idle | cycle_canvas | cycle_visual | hit | churn | path_direct | done
_steps: List[Tuple[str, str, Any]] = []
_iso = args.isolate

_steps.append(("warmup", "warmup", None))
_steps.append(("warm_baseline", "idle", None))
_nrep = max(1, int(args.repeats))
for _rep in range(_nrep):
    tag = "" if _nrep == 1 else f"_r{_rep + 1}"
    if _iso in ("all", "canvas"):
        _steps.append((f"cycle_canvas{tag}", "cycle_canvas", _canvas_posts()))
        _steps.append((f"idle_after_canvas{tag}", "idle", None))
    if _iso == "path" and _rep == 0:
        _steps.append(("cycle_sksl", "cycle_canvas", _sksl_posts()))
        _steps.append(("idle_after_sksl", "idle", None))
    if _iso in ("all", "path", "canvas") and _rep == 0:
        _steps.append(("idle_direct_fb", "path_direct", None))
    if _iso in ("all", "sksl") and _rep == 0:
        _steps.append(("cycle_sksl", "cycle_canvas", _sksl_posts()))
        _steps.append(("idle_after_sksl", "idle", None))
    if _iso in ("all", "trails") and _rep == 0:
        _steps.append(("cycle_trails", "cycle_canvas", [("trails", MotionTrail)]))
        _steps.append(("idle_after_trails", "idle", None))
    if _iso in ("all", "hit") and _rep == 0:
        _steps.append(("cycle_hit", "hit", None))
        _steps.append(("idle_after_hit", "idle", None))
        _steps.append(("idle_hit_held", "hit_held", None))
    if _iso in ("all", "visual"):
        _steps.append((f"cycle_visuals{tag}", "cycle_visual", _visuals()))
        _steps.append((f"idle_after_visuals{tag}", "idle", None))
    if _iso in ("all", "spawn") and _rep == 0:
        _steps.append(("cycle_spawn", "churn", None))
        _steps.append(("idle_after_spawn", "idle", None))
_steps.append(("final_none", "idle", None))
_steps.append(("done", "done", None))

_step_i = 0
_frames_left = 0
_cat_i = 0
_idle_work: List[float] = []
_plain0 = 0
_samples: List[Dict[str, Any]] = []
_done = False


def _begin_step() -> None:
    global _frames_left, _cat_i, _idle_work, _plain0
    if _step_i >= len(_steps):
        return
    label, kind, payload = _steps[_step_i]
    status.text = f"{label}  ({kind})"
    _idle_work = []
    _plain0 = int(getattr(ScenaCanvas, "_plain_blit_draws", 0) or 0)
    _cat_i = 0
    fw = ScenaFramework.get_instance()
    if kind == "idle":
        _clear_all()
        _frames_left = int(args.idle_frames)
    elif kind == "warmup":
        _clear_all()
        _frames_left = int(args.warmup_frames)
    elif kind == "cycle_canvas":
        _clear_all()
        _frames_left = int(args.dwell)
        if payload:
            _apply_canvas(payload[0][1])
    elif kind == "cycle_visual":
        _clear_all()
        _frames_left = int(args.dwell)
        if payload:
            _apply_look(payload[0][1])
    elif kind == "hit":
        _clear_all()
        _fire_hit()
        _frames_left = int(args.dwell) * (2 if args.quick else 4)
    elif kind == "hit_held":
        _clear_shape_fx()
        canvas.effects.clear()
        canvas.effects._hit_feedback()  # idle singleton left on the stack
        gc.collect()
        _frames_left = int(args.idle_frames)
    elif kind == "churn":
        _clear_all()
        _run_churn()
        _frames_left = int(args.dwell) * (2 if args.quick else 3)
    elif kind == "path_direct":
        _clear_all()
        gc.collect()
        fw._was_using_post = False
        _frames_left = int(args.idle_frames)
    elif kind == "done":
        _frames_left = 1


def _record(label: str) -> Dict[str, Any]:
    inv = _inventory()
    stats = _work_stats(_idle_work)
    plain1 = int(getattr(ScenaCanvas, "_plain_blit_draws", 0) or 0)
    nfr = max(1, len(_idle_work))
    sample = {
        "label": label,
        "plain_blit_per_frame": (plain1 - _plain0) / nfr,
        **stats,
        **inv,
        "t": time.time(),
    }
    _samples.append(sample)
    status.text = (
        f"{label}  work={stats['idle_work_ms']:.2f}ms  "
        f"leftover={int(inv['leftover_fx'])}  rt={int(inv['needs_scene_rt'])}  "
        f"blit={int(inv['prefer_scene_blit'])}"
    )
    return sample


def _advance() -> None:
    global _step_i, _frames_left, _cat_i, _done
    if _step_i >= len(_steps):
        _finalize()
        return
    label, kind, payload = _steps[_step_i]
    if kind in ("idle", "hit_held", "path_direct"):
        _record(label)
    elif kind in ("churn", "warmup"):
        if kind == "churn":
            _destroy_churn()
            _clear_all()
    elif kind in ("cycle_canvas", "cycle_visual", "hit"):
        pass
    _step_i += 1
    if _step_i >= len(_steps) or _steps[_step_i][1] == "done":
        _finalize()
        return
    _begin_step()


def _tick_cycle(kind: str, payload) -> bool:
    """Hold current catalog item; True when the whole catalog is done."""
    global _frames_left, _cat_i
    _frames_left -= 1
    if _frames_left > 0:
        return False
    _cat_i += 1
    if payload is None or _cat_i >= len(payload):
        _clear_all()
        return True
    name, factory = payload[_cat_i]
    status.text = f"{_steps[_step_i][0]}  {name}  ({_cat_i + 1}/{len(payload)})"
    if kind == "cycle_canvas":
        _apply_canvas(factory)
    else:
        _apply_look(factory)
    _frames_left = int(args.dwell)
    return False


def _finalize() -> None:
    global _done
    if _done:
        return
    _done = True
    by = {s["label"]: s for s in _samples}
    base = by.get("warm_baseline", {})
    base_ms = float(base.get("idle_tail_ms", base.get("idle_work_ms", float("nan"))))
    skip_work_warn = {"warm_baseline", "idle_scene_blit", "idle_direct_fb"}
    warns: List[str] = []
    rows = []
    for s in _samples:
        tail = float(s.get("idle_tail_ms", s.get("idle_work_ms", float("nan"))))
        dlt = tail - base_ms
        s["delta_work_ms"] = dlt
        rows.append(s)
        leftover = float(s.get("leftover_fx", 0) or 0)
        lab = str(s["label"])
        if leftover > 0 and lab.startswith(("idle", "final", "warm")):
            kinds = s.get("leftover_kinds") or "?"
            warns.append(f"{lab}: leftover FX attachments ({leftover:.0f}) [{kinds}]")
        if (
            dlt == dlt
            and dlt > args.warn_work_ms
            and lab not in skip_work_warn
        ):
            warns.append(
                f"{lab}: idle tail_ms +{dlt:.3f} vs warm baseline "
                f"(warn>{args.warn_work_ms})"
            )
        if float(s.get("needs_scene_rt", 0) or 0) and lab.startswith(
            ("idle_after", "final", "warm", "idle_direct", "idle_hit")
        ):
            names = s.get("canvas_effect_names") or ""
            warns.append(
                f"{lab}: needs_scene_rt still set "
                f"(post_draw_live={int(s.get('post_draw_live', 0))} "
                f"builtin={int(s.get('builtin_post', 0))} fx=[{names}])"
            )
    fw = ScenaFramework.get_instance()
    payload = {
        "samples": rows,
        "baseline_work_ms": base_ms,
        "warns": warns,
        "isolate": args.isolate,
        "dwell": args.dwell,
        "idle_frames": args.idle_frames,
        "n": args.n,
        "quality": args.quality,
        "flat": not bool(args.lab),
        "fb_w": int(getattr(fw, "fb_width", 0) or 0),
        "fb_h": int(getattr(fw, "fb_height", 0) or 0),
        "pixel_ratio": float(getattr(fw, "pixel_ratio", 1.0) or 1.0),
    }
    print("=" * 86)
    print("fx_churn diagnostics")
    print("=" * 86)
    print(
        f"FB {payload['fb_w']}×{payload['fb_h']}  "
        f"pixel_ratio={payload['pixel_ratio']:.2f}  "
        f"design={W}×{H}  lab={args.lab}  n={args.n}  Q={args.quality}"
    )
    hdr = (
        f"{'label':22} {'tail':>7} {'Δms':>7} {'head':>7} {'fps':>7}  "
        f"{'obj':>4} {'fx':>3} {'left':>4} {'nplain':>6} "
        f"{'rt':>2} {'blit':>4} {'scene':>5} {'pool':>4}  notes"
    )
    print(hdr)
    print("-" * 86)
    for s in rows:
        notes = []
        if s.get("canvas_effect_names"):
            notes.append(s["canvas_effect_names"])
        if s.get("leftover_kinds"):
            notes.append(s["leftover_kinds"])
        if int(s.get("hit_held", 0) or 0):
            notes.append("hit_held")
        print(
            f"{s['label']:22} {s.get('idle_tail_ms', float('nan')):7.3f} "
            f"{s.get('delta_work_ms', float('nan')):7.3f} "
            f"{s.get('idle_head_ms', float('nan')):7.3f} "
            f"{s.get('fps_est', float('nan')):7.0f}  "
            f"{int(s.get('objects', 0)):4d} {int(s.get('canvas_effects', 0)):3d} "
            f"{int(s.get('leftover_fx', 0)):4d} {int(s.get('n_not_plain', 0)):6d} "
            f"{int(s.get('needs_scene_rt', 0)):2d} {int(s.get('prefer_scene_blit', 0)):4d} "
            f"{int(s.get('has_scene_surf', 0)):5d} {int(s.get('shape_fx_pool', 0)):4d}  "
            f"{'; '.join(notes)}"
        )
    print("-" * 86)
    print(
        "tail=last-20-frame mean (settled).  rt=needs_scene_rt  "
        "blit=prefer_scene_blit  left=costume leftovers"
    )
    print(
        f"warm baseline {base_ms:.3f} ms   graph_nodes={int(base.get('graph_nodes', 0))}  "
        f"post_draw_live={int(base.get('post_draw_live', 0))}  "
        f"recipe_cache last={int(rows[-1].get('recipe_cache', 0) if rows else 0)}"
    )
    direct = by.get("idle_direct_fb")
    if direct:
        dms = float(direct.get("idle_tail_ms", float("nan")))
        print(f"GPU path after canvas: direct-FB idle {dms:.3f} ms")
    vis_plateau = [s for s in rows if str(s["label"]).startswith("idle_after_visuals")]
    canv_plateau = [s for s in rows if str(s["label"]).startswith("idle_after_canvas")]
    if len(vis_plateau) >= 2:
        slope = float(vis_plateau[-1]["idle_tail_ms"]) - float(vis_plateau[0]["idle_tail_ms"])
        print(f"visual-cycle slope (first→last idle): {slope:+.3f} ms")
        if slope > args.warn_work_ms:
            warns.append(f"idle_after_visuals slope {slope:+.3f} ms over {len(vis_plateau)} repeats")
            payload["warns"] = warns
    if len(canv_plateau) >= 2:
        slope = float(canv_plateau[-1]["idle_tail_ms"]) - float(canv_plateau[0]["idle_tail_ms"])
        print(f"canvas-cycle slope (first→last idle): {slope:+.3f} ms")
        if slope > args.warn_work_ms:
            warns.append(f"idle_after_canvas slope {slope:+.3f} ms over {len(canv_plateau)} repeats")
            payload["warns"] = warns
    if warns:
        print("WARN:")
        for w in warns:
            print("  -", w)
    else:
        print("OK: no warn thresholds crossed")
    print("=" * 86)
    print(
        "RESULT_JSON: "
        + str({
            "baseline_work_ms": round(base_ms, 4) if base_ms == base_ms else None,
            "fb": [payload["fb_w"], payload["fb_h"], payload["pixel_ratio"]],
            "samples": [
                {
                    "label": s["label"],
                    "idle_tail_ms": round(float(s.get("idle_tail_ms", 0) or 0), 4),
                    "delta_work_ms": round(float(s.get("delta_work_ms", 0) or 0), 4),
                    "leftover_fx": int(s.get("leftover_fx", 0) or 0),
                    "needs_scene_rt": int(s.get("needs_scene_rt", 0) or 0),
                    "prefer_scene_blit": int(s.get("prefer_scene_blit", 0) or 0),
                    "objects": int(s.get("objects", 0) or 0),
                    "n_not_plain": int(s.get("n_not_plain", 0) or 0),
                    "graph_nodes": int(s.get("graph_nodes", 0) or 0),
                }
                for s in rows
            ],
            "warns": warns,
        })
    )
    if args.json_path:
        write_json(args.json_path, payload)
        print("wrote", args.json_path)
    if fw is not None and getattr(fw, "_window", None) is not None:
        import glfw
        glfw.set_window_should_close(fw._window, True)


def update(dt):
    global _frames_left
    t = clock.time
    work_ms = (dt * 1000.0) if dt > 0 else 0.0
    for m in movers:
        shp = m["shape"]
        nx = m["ox"] + math.sin(t * m["freq"] + m["phase"]) * m["amp"]
        ny = m["oy"] + math.cos(t * m["freq"] * 0.85 + m["phase"]) * m["amp"] * 0.7
        shp.move_to(nx, ny)
        if m["spin"]:
            shp.rotate_by(m["spin"] * dt)

    if _done or _step_i >= len(_steps):
        return
    label, kind, payload = _steps[_step_i]
    if kind in ("idle", "hit_held", "path_direct", "warmup"):
        _idle_work.append(work_ms)
        _frames_left -= 1
        if _frames_left <= 0:
            _advance()
    elif kind in ("cycle_canvas", "cycle_visual"):
        if _tick_cycle(kind, payload):
            _advance()
    elif kind == "hit":
        _frames_left -= 1
        if _frames_left <= 0:
            _clear_all()
            _advance()
    elif kind == "churn":
        _frames_left -= 1
        if _frames_left <= 0:
            _advance()
    elif kind == "done":
        _finalize()

    inv = _inventory()
    hud.text = (
        f"churn  {label}  dt={work_ms:.2f}ms  leftover={int(inv['leftover_fx'])}  "
        f"rt={int(inv['needs_scene_rt'])} blit={int(inv['prefer_scene_blit'])}  "
        f"fx={int(inv['canvas_effects'])}"
    )


canvas.framerate = "max"
_fw = ScenaFramework.get_instance()
if (not args.lab) and _fw is not None:
    _fw._compute_window_size = lambda dw, dh, wf: (int(dw), int(dh))
_begin_step()
run()
