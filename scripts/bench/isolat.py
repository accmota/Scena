"""
app_scene_isolat.py — peel Scena overhead in 4 tiers (same scene / motion).

Scene: 200 rects (100 bounce+spin, 100 fixed). Motion has no cos/sin.

Tiers
-----
1. reactive  Scena ``Rect`` (Attribute / Derivate graph)
2. simple    ``SimpleRect`` floats on Scena canvas (no reactive graph)
3. sprite    ``SimpleRectSprite`` pre-raster blit on Scena canvas
4. raw       GLFW + Skia only (no Scena framework)

Usage
-----
    python scripts/bench/isolat.py --tier reactive
    python scripts/bench/isolat.py --bench --tier simple
    python scripts/bench/isolat.py --bench --suite
    python scripts/bench/isolat.py --bench --tier reactive --profile
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import skia

from scene_isolat_common import (
    WIDTH, HEIGHT,
    build_arg_parser, normalize_tier, generate_rects, step_mover,
    color_of, report,
)
from perf_profile import FrameProfiler

parser = build_arg_parser(__doc__)
args, _ = parser.parse_known_args()
tier = normalize_tier(args.tier)

# ---------------------------------------------------------------------------
# Suite
# ---------------------------------------------------------------------------
if args.suite:
    script = os.path.abspath(__file__)
    configs = [
        ("reactive", False),
        ("reactive", True),
        ("simple", False),
        ("simple", True),
        ("sprite", False),
        ("sprite", True),
        ("raw", False),
        ("raw", True),
    ]
    print(
        f"=== scene isolat suite  n={args.n} n_move={args.n_move} "
        f"duration={args.duration}s ==="
    )
    rows = []
    for t, static in configs:
        cmd = [
            sys.executable, script,
            "--bench", "--tier", t,
            "--n", str(args.n), "--n-move", str(args.n_move),
            "--duration", str(args.duration), "--warmup", str(args.warmup),
            "--seed", str(args.seed),
        ]
        if static:
            cmd.append("--static")
        label = f"{t}{'/static' if static else ''}"
        print(f"\n>> {label}")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        out = (proc.stdout or "") + (proc.stderr or "")
        print(out)
        fps = None
        for line in out.splitlines():
            if "Average FPS:" in line:
                try:
                    fps = float(line.split(":")[-1].strip())
                except ValueError:
                    pass
        rows.append((label, fps))
    print("\n=== suite summary ===")
    print(f"{'tier':<22} {'fps':>10}")
    print("-" * 34)
    for label, fps in rows:
        print(f"{label:<22} {fps:>10.1f}" if fps is not None else f"{label:<22} {'?':>10}")
    print("=" * 34)
    by = {k: v for k, v in rows}
    raw = by.get("raw")
    if raw:
        print("\nCost vs raw (moving):")
        for label in ("reactive", "simple", "sprite", "raw"):
            fps = by.get(label)
            if fps and fps > 0:
                print(f"  {label:<12}  {raw/fps:5.2f}× raw frame time  ({fps:.0f} fps)")
    sys.exit(0)


# ---------------------------------------------------------------------------
# Tier 4 — raw GLFW + Skia
# ---------------------------------------------------------------------------
def run_raw() -> None:
    import glfw
    from OpenGL import GL

    fixed, movers = generate_rects(args.n, args.n_move, WIDTH, HEIGHT, args.seed)
    all_poses = movers + fixed

    if not glfw.init():
        raise RuntimeError("glfw.init failed")
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 2)
    glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, True)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.STENCIL_BITS, 8)
    window = glfw.create_window(WIDTH, HEIGHT, f"isolat raw n={args.n}", None, None)
    if not window:
        glfw.terminate()
        raise RuntimeError("glfw window failed")
    glfw.make_context_current(window)
    glfw.swap_interval(0)

    win_w, win_h = glfw.get_window_size(window)
    fb_w, fb_h = glfw.get_framebuffer_size(window)
    pixel_ratio = (fb_w / win_w) if win_w else 1.0
    GL.glViewport(0, 0, fb_w, fb_h)

    context = skia.GrDirectContext.MakeGL()
    be = skia.GrBackendRenderTarget(
        fb_w, fb_h, 0, 0, skia.GrGLFramebufferInfo(0, GL.GL_RGBA8)
    )
    surface = skia.Surface.MakeFromBackendRenderTarget(
        context, be, skia.kBottomLeft_GrSurfaceOrigin,
        skia.kRGBA_8888_ColorType, skia.ColorSpace.MakeSRGB(),
    )
    if surface is None:
        raise RuntimeError("Skia surface failed")
    sk = surface.getCanvas()
    bg = skia.Color4f(0.02, 0.02, 0.05, 1.0)

    paints = []
    for p in all_poses:
        paint = skia.Paint(AntiAlias=True, Style=skia.Paint.kFill_Style)
        paint.setColor4f(skia.Color4f(*color_of(p)))
        paints.append(paint)

    print(
        f"[isolat] tier=raw n={args.n} movers={args.n_move} "
        f"static={args.static} FB={fb_w}x{fb_h}"
    )

    t0 = None
    frame_times = []
    last = time.perf_counter()

    while not glfw.window_should_close(window):
        now = time.perf_counter()
        dt = now - last
        last = now
        if t0 is None:
            t0 = now
        elapsed = now - t0

        glfw.poll_events()

        if not args.static:
            for m in movers:
                step_mover(m, dt, WIDTH, HEIGHT)

        sk.clear(bg)
        sk.resetMatrix()
        sk.scale(pixel_ratio, pixel_ratio)
        sk.translate(0, HEIGHT)
        sk.scale(1, -1)

        for pose, paint in zip(all_poses, paints):
            sk.save()
            sk.translate(pose["x"], pose["y"])
            if pose["angle"]:
                sk.rotate(pose["angle"])
            hw, hh = pose["width"] * 0.5, pose["length"] * 0.5
            sk.drawRect(skia.Rect.MakeLTRB(-hw, -hh, hw, hh), paint)
            sk.restore()

        surface.flushAndSubmit()
        glfw.swap_buffers(window)

        if elapsed < args.warmup:
            continue
        if args.bench:
            if elapsed < args.warmup + args.duration:
                frame_times.append(dt)
            else:
                break
        else:
            if glfw.get_key(window, glfw.KEY_ESCAPE) == glfw.PRESS:
                break

    context.abandonContext()
    glfw.terminate()
    if args.bench:
        report(
            "isolat [raw]", frame_times, args.n,
            extra=f"FB={fb_w}x{fb_h} movers={args.n_move} static={args.static}",
        )


if tier == "raw":
    run_raw()
    sys.exit(0)


# ---------------------------------------------------------------------------
# Tiers 1–3 — Scena framework
# ---------------------------------------------------------------------------
from scena import *  # noqa: E402, F403
from scena.orchestration import ScenaFramework  # noqa: E402
from simple_shapes import SimpleRect, SimpleRectSprite  # noqa: E402

init(width=WIDTH, height=HEIGHT, title=f"isolat {tier}")
fw = ScenaFramework.get_instance()
fw._compute_window_size = (
    lambda design_w, design_h, window_scale: (int(design_w), int(design_h))
)
canvas.background = (0.02, 0.02, 0.05, 1)
set_fx_auto(False)
set_defaults(line=None)
canvas.batch_shared_filters = False
fixed_poses, mover_poses = generate_rects(
    args.n, args.n_move, WIDTH, HEIGHT, args.seed,
)

movers = []  # (pose, drawable)

def _make(pose, i):
    color = color_of(pose)
    center = (pose["x"], pose["y"])
    if tier == "reactive":
        shp = Rect(
            center=center,
            width=pose["width"],
            height=pose["length"],
            angle=pose["angle"],
        )
        shp.fill = color
    elif tier == "simple":
        shp = SimpleRect(
            center, pose["width"], pose["length"],
            angle=pose["angle"], color=color,
        ).add_to_canvas(canvas)
    else:  # sprite
        # Bake at 2× for Retina so blit cost matches framebuffer density.
        shp = SimpleRectSprite(
            center, pose["width"], pose["length"],
            angle=pose["angle"], color=color,
            pixel_scale=2.0,
        ).add_to_canvas(canvas)
    return shp

for i, pose in enumerate(mover_poses):
    movers.append((pose, _make(pose, i)))
for j, pose in enumerate(fixed_poses):
    _make(pose, args.n_move + j)

print(
    f"[isolat] tier={tier} n={args.n} movers={args.n_move} "
    f"static={args.static} batch={canvas.batch_shared_filters}"
)

Text(
    text=f"isolat · {tier} · n={args.n} move={args.n_move}",
    top_left=(16, HEIGHT - 11), font_size=14,
)

_bench_t0 = None
_frame_times = []
_prof = FrameProfiler.install() if args.profile else None
_prof_started = False


def _finish():
    fb = f"FB={fw.fb_width}x{fw.fb_height}" if fw.fb_width else "FB=?"
    report(
        f"isolat [{tier}]", _frame_times, args.n,
        extra=f"{fb} movers={args.n_move} static={args.static}",
    )
    if _prof is not None:
        _prof.report(f"isolat — {tier}")
        FrameProfiler.uninstall()
    import glfw
    glfw.set_window_should_close(fw._window, True)


def _apply_pose(pose, shp):
    if tier == "reactive":
        shp.move_to(pose["x"], pose["y"])
        shp.angle = pose["angle"]
    else:
        shp.x = pose["x"]
        shp.y = pose["y"]
        shp.angle = pose["angle"]


def _update_body(dt):
    global _bench_t0, _prof_started
    if not args.static:
        for pose, shp in movers:
            step_mover(pose, dt, WIDTH, HEIGHT)
            _apply_pose(pose, shp)

    if not (args.bench or _prof is not None):
        return

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

canvas.framerate = "max" if (args.bench or args.profile) else "vsync60"

run()
