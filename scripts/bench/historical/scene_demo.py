"""FROZEN historical benchmark — do not add features.

app_scene_demo.py — realistic non-playable visual scene for Scena effects.

Gradient background, orbiting shapes, optional hero/orb GlowFilter, and a
canvas.effects stack (default: vignette+grain+bloom, no shape glow).
Toggled by number keys. Ctrl+Shift+3 cycles render quality profiles.

Usage
-----
    python scripts/app_scene_demo.py
    python scripts/app_scene_demo.py --mode full          # + GlowFilter
    python scripts/app_scene_demo.py --bench --duration 3
    python scripts/app_scene_demo.py --bench --mode baseline
    python scripts/app_scene_demo.py --bench --mode glow --profile --profile-seconds 3
    python scripts/app_scene_demo.py --bench --suite
"""
from __future__ import annotations

import argparse
import math
import os
import random
import subprocess
import sys
import time

_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_BENCH = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (_SCRIPTS, _BENCH):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from perf_profile import FrameProfiler, add_profile_args

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--bench", action="store_true")
parser.add_argument("--duration", type=float, default=3.0)
parser.add_argument("--warmup", type=float, default=0.5)
parser.add_argument("--n", type=int, default=180)
parser.add_argument(
    "--mode",
    choices=(
        "full",          # glow + post (default look)
        "baseline",      # solids only, no glow, no post
        "glow",          # shared GlowFilter, no post
        "glow_nobatch",  # unique GlowFilter per orb (no batching)
        "post",          # vignette+grain+bloom, no shape glow
        "geom",          # baseline + freeze motion (isolate draw)
        "circles",       # glow but all Circles (cheaper geom)
    ),
    default="post",
)
parser.add_argument(
    "--quality", default="high",
    choices=("low", "medium", "high", "max"),
)
parser.add_argument("--no-gradient-bg", action="store_true")
parser.add_argument(
    "--static", action="store_true",
    help="skip per-frame move/rotate (isolate draw cost)",
)
parser.add_argument(
    "--suite", action="store_true",
    help="with --bench: run isolation matrix in subprocesses",
)
add_profile_args(parser)
args, _ = parser.parse_known_args()

# ---------------------------------------------------------------------------
# Suite: spawn clean processes per config
# ---------------------------------------------------------------------------
if args.suite:
    script = os.path.abspath(__file__)
    configs = [
        ("baseline", "high", False),
        ("geom", "high", True),          # static solids
        ("glow", "high", False),
        ("glow", "high", True),          # static + glow
        ("glow_nobatch", "high", False),
        ("circles", "high", False),
        ("post", "high", False),
        ("full", "high", False),
        ("full", "low", False),
        ("full", "max", False),
        ("full", "high", False),         # no-gradient repeat below via flag
    ]
    rows = []
    print(f"=== app_scene_demo suite  n={args.n}  duration={args.duration}s ===")
    for i, (mode, quality, static) in enumerate(configs):
        no_grad = (i == len(configs) - 1)  # last full run without gradient bg
        cmd = [
            sys.executable, script,
            "--bench", "--mode", mode, "--quality", quality,
            "--n", str(args.n),
            "--duration", str(args.duration),
            "--warmup", str(args.warmup),
        ]
        if static:
            cmd.append("--static")
        if no_grad:
            cmd.append("--no-gradient-bg")
            mode_label = f"{mode}/no-grad"
        else:
            mode_label = f"{mode}{'/static' if static else ''}"
        print(f"\n>> mode={mode_label} Q={quality}")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        out = proc.stdout + proc.stderr
        print(out)
        fps = None
        for line in out.splitlines():
            if "Average FPS:" in line:
                try:
                    fps = float(line.split(":")[-1].strip())
                except ValueError:
                    pass
        rows.append((mode_label, quality, fps))
    print("\n=== suite summary ===")
    print(f"{'mode':<22} {'quality':<10} {'fps':>8}")
    print("-" * 42)
    for mode, quality, fps in rows:
        fps_s = f"{fps:.1f}" if fps is not None else "?"
        print(f"{mode:<22} {quality:<10} {fps_s:>8}")
    print("=" * 42)
    sys.exit(0)

# ---------------------------------------------------------------------------
# Single run
# ---------------------------------------------------------------------------
from scena import *  # noqa: E402
from scena.orchestration import ScenaFramework  # noqa: E402

W, H = 1200, 800
init(width=W, height=H, window_scale=0.7, title="Scena scene FX demo")
canvas.background = (0.02, 0.02, 0.05, 1)
canvas.batch_shared_filters = args.mode != "glow_nobatch"
canvas.fx_quality = args.quality

if not args.no_gradient_bg:
    bg = Rect(center=(W / 2, H / 2), width=W + 40, height=H + 40)
    bg.fill = Gradient("ocean", type=GradientType.RADIAL, size=max(W, H * 0.7))
    bg.line = None
    bg.move_to_back()

want_post = args.mode in ("full", "post")
want_glow = args.mode in ("full", "glow", "glow_nobatch", "circles")
force_circles = args.mode in ("circles", "geom")
static = args.static or args.mode == "geom"

_fx = {
    "vignette": None, "grain": None, "bloom": None, "grade": None,
    "chroma": None, "pixelate": None, "haze": None, "scanlines": None,
    "blur": None, "prism": None, "perspective": None, "lamp": None, "rays": None,
}
if want_post:
    _fx["vignette"] = canvas.effects.add(Vignette())
    _fx["grain"] = canvas.effects.add(Grain())
    _fx["bloom"] = canvas.effects.add(Bloom())

_GLOW_HERO = GlowFilter(radius=16, sigma=10, color=(1.0, 0.85, 0.4, 0.95))
_GLOW_ORB = GlowFilter(radius=8, sigma=5, color=(0.4, 0.9, 1.0, 0.85))

hero = RegularPolygon(n=6, center=(W / 2, H / 2), radius=70, angle=0).set_color("gold")
if want_glow:
    hero.fill_filter = _GLOW_HERO
hero.line = None

orbs = []
random.seed(11)
_n_glow = 0
for i in range(args.n):
    ang = i * (math.tau / args.n)
    r = 120 + (i % 7) * 35 + random.uniform(-10, 10)
    x = W / 2 + math.cos(ang) * r
    y = H / 2 + math.sin(ang) * r
    kind = 0 if force_circles else (i % 4)
    if kind == 0:
        shp = Circle(center=(x, y), radius=8 + (i % 4))
    elif kind == 1:
        shp = Square(center=(x, y), length=14 + (i % 3), angle=i * 7)
    elif kind == 2:
        shp = Triangle(center=(x, y), radius=10, angle=i * 5)
    else:
        shp = RegularPolygon(n=5, center=(x, y), radius=9, angle=i * 9)
    color = ("cyan", "magenta", "lime", "orange", "dodger blue", "orchid")[i % 6]
    shp.set_color(color); shp.line_width = 1
    if want_glow and i % 5 == 0:
        if args.mode == "glow_nobatch":
            # Unique batch_key per orb (param-based keys, not identity).
            shp.fill_filter = GlowFilter(
                radius=8,
                sigma=5.0 + i * 0.01,
                color=(0.4, 0.9, 1.0, 0.85),
            )
        else:
            shp.fill_filter = _GLOW_ORB
        _n_glow += 1
    orbs.append({
        "shape": shp, "r": r, "ang0": ang,
        "spin": 20 + (i % 9) * 8, "orbit": 0.15 + (i % 5) * 0.03,
    })

# Count unique batch keys
_keys = set()
for o in orbs:
    fx = o["shape"].fill_filter
    if fx is not None:
        _keys.add(getattr(fx, "_batch_key", id(fx)))
if want_glow and hero.fill_filter is not None:
    _keys.add(getattr(hero.fill_filter, "_batch_key", id(hero.fill_filter)))

print(
    f"[app_scene_demo] mode={args.mode} n={args.n} glow={_n_glow} "
    f"unique_batch_keys={len(_keys)} post={want_post} "
    f"batch={canvas.batch_shared_filters} quality={args.quality} "
    f"static={static} grad_bg={not args.no_gradient_bg} "
    f"shape_fx={canvas.shape_fx_scale} post_fx={canvas.post_fx_scale}"
)

hud = Label(
    text="1-9 FX · 0 clear · Ctrl+Shift+3 quality",
    x1=20, y1=H - 36, font_size=16,
)
fx_label = Label(text="", x1=20, y1=H - 64, font_size=14)


def _refresh():
    on = [k for k, e in _fx.items() if e is not None and getattr(e, "enabled", True)]
    q = canvas.fx_quality
    qname = q.value if q else "?"
    fx_label.text = (
        f"Q={qname} post={canvas.post_fx_scale:g} shape={canvas.shape_fx_scale:g}  "
        f"FX: {', '.join(on) or '(none)'}"
    )


def _toggle(name, factory):
    cur = _fx.get(name)
    if cur is not None:
        canvas.effects.remove(cur)
        _fx[name] = None
    else:
        _fx[name] = canvas.effects.add(factory())
    _refresh()


_t = 0.0
_bench_t0 = None
_frame_times = []
_prof = FrameProfiler.install() if args.profile else None
_prof_started = False


def _finish():
    from perf_common import print_report
    print_report(
        f"app_scene_demo [{args.mode}/{args.quality}]",
        _frame_times, args.n,
    )
    fw = ScenaFramework.get_instance()
    print(
        f"  FB={fw.fb_width}x{fw.fb_height}  design={W}x{H}  "
        f"batch={canvas.batch_shared_filters}  glow={_n_glow}  "
        f"batch_keys={len(_keys)}  effects={len(canvas.effects)}"
    )
    if _prof is not None:
        _prof.report(
            f"app_scene_demo — mode={args.mode} Q={args.quality}"
        )
        FrameProfiler.uninstall()
    import glfw
    glfw.set_window_should_close(fw._window, True)


def _update_body(dt):
    global _t, _bench_t0, _prof_started
    _t += dt

    if not args.bench:
        if keyp.once("0"):
            for k in list(_fx.keys()):
                if _fx[k] is not None:
                    canvas.effects.remove(_fx[k])
                    _fx[k] = None
            _refresh()
        if keyp.once("1"):
            _toggle("vignette", Vignette)
        if keyp.once("2"):
            _toggle("grain", Grain)
        if keyp.once("3"):
            _toggle("bloom", Bloom)
        if keyp.once("4"):
            _toggle("grade", lambda: Grade("cool"))
        if keyp.once("5"):
            _toggle("scanlines", Scanlines)
        if keyp.once("6"):
            _toggle("chroma", Chroma)
        if keyp.once("7"):
            _toggle("pixelate", Pixelate)
        if keyp.once("8"):
            _toggle("haze", Haze)
        if keyp.once("9"):
            _toggle("blur", ScreenBlur)
        if keyp.once("S"):
            _toggle("prism", Prism)
        if keyp.once("Y"):
            _toggle("perspective", Perspective)
        if keyp.once("L"):
            _toggle("lamp", Lamp)
        if keyp.once("U"):
            _toggle("rays", GodRays)
        if keyp.once("H"):
            canvas.ripple_at(mouse.x, mouse.y, amount=1.0)

    if not static:
        hero.rotate_by(25 * dt)
        for o in orbs:
            ang = o["ang0"] + _t * o["orbit"]
            o["shape"].move_to(
                W / 2 + math.cos(ang) * o["r"],
                H / 2 + math.sin(ang) * o["r"],
            )
            o["shape"].rotate_by(o["spin"] * dt)

    if args.bench or _prof is not None:
        now = time.perf_counter()
        if _bench_t0 is None:
            _bench_t0 = now
            return
        elapsed = now - _bench_t0
        if elapsed < args.warmup:
            return
        if _prof is not None and not _prof_started:
            _prof.start_recording()
            _prof_started = True
        if args.bench:
            if elapsed < args.warmup + args.duration:
                _frame_times.append(dt)
            else:
                _finish()
        elif _prof is not None and args.profile_seconds is not None:
            if elapsed >= args.warmup + args.profile_seconds:
                _finish()


update = _prof.wrap_update(_update_body) if _prof is not None else _update_body

_refresh()
set_framerate(FrameRateControl.NONE if (args.bench or args.profile) else FrameRateControl.VSYNC)
run()
