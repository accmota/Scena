"""Glow fleet layout bench — clustered vs sparse same-Glow draw/submit.

Measures the union-AABB cliff documented in Scena Design.md §5: identical
shared ``Glow`` / ``CheapGlow`` / count, only spatial layout changes.

Reports avg ``draw_ms`` / ``submit_ms`` / ``present_ms`` / ``work_ms`` / FPS
under ``canvas.framerate = "max"`` (subprocess per cell).

Usage:
  python scripts/perf_glow_fleet.py
  python scripts/perf_glow_fleet.py --n 48 --duration 1.2
  python scripts/perf_glow_fleet.py --layout sparse --visual glow
  python scripts/perf_glow_fleet.py --fb native --json /tmp/glow_fleet.json
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import subprocess
import sys
import time
import types

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--duration", type=float, default=1.2)
parser.add_argument("--warmup", type=float, default=0.45)
parser.add_argument("--n", type=int, default=48)
parser.add_argument("--width", type=int, default=1000)
parser.add_argument("--height", type=int, default=700)
parser.add_argument(
    "--quality",
    default="high",
    help="fx_quality (default high — shipping target)",
)
parser.add_argument(
    "--layout",
    choices=("clustered", "sparse"),
    default=None,
    help="single layout; omit with --suite for both",
)
parser.add_argument(
    "--visual",
    choices=("none", "glow", "cheapglow"),
    default=None,
    help="none / glow / cheapglow (shared GlowFilter fleet look)",
)
parser.add_argument(
    "--kind",
    choices=("shape", "sprite"),
    default="sprite",
    help="geometry: procedural shapes, or sheet sprites (Galaga-like)",
)
parser.add_argument(
    "--fb",
    choices=("design", "native"),
    default="native",
    help="design=force window==design (1× FB); native=OS window / Retina FB",
)
parser.add_argument(
    "--glow-radius",
    type=float,
    default=8.0,
    help="Glow radius (Galaga sting default 8)",
)
parser.add_argument(
    "--glow-sigma",
    type=float,
    default=4.0,
    help="Glow sigma (Galaga sting default 4)",
)
parser.add_argument(
    "--suite",
    action="store_true",
    default=None,
    help="run full matrix (default when layout/visual omitted)",
)
parser.add_argument(
    "--json",
    dest="json_path",
    default=None,
    help="write suite results JSON",
)
parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
parser.add_argument("--layout-key", default="clustered", help=argparse.SUPPRESS)
parser.add_argument("--visual-key", default="glow", help=argparse.SUPPRESS)
args = parser.parse_args()

if args.suite is None:
    args.suite = args.layout is None and args.visual is None and not args.worker
if args.layout is None:
    args.layout = "clustered"
if args.visual is None:
    args.visual = "glow"

CELLS = (
    ("clustered", "none"),
    ("clustered", "glow"),
    ("clustered", "cheapglow"),
    ("sparse", "none"),
    ("sparse", "glow"),
    ("sparse", "cheapglow"),
)


def _positions(layout: str, n: int, w: int, h: int) -> list[tuple[float, float]]:
    """Return n centers. Clustered = tight blob; sparse = full viewport grid."""
    if n <= 0:
        return []
    if layout == "clustered":
        cols = max(1, int(math.ceil(math.sqrt(n))))
        rows = max(1, int(math.ceil(n / cols)))
        gap = 28.0
        ox = w * 0.5 - (cols - 1) * gap * 0.5
        oy = h * 0.5 - (rows - 1) * gap * 0.5
        out = []
        for i in range(n):
            c = i % cols
            r = i // cols
            out.append((ox + c * gap, oy + r * gap))
        return out

    cols = max(1, int(math.ceil(math.sqrt(n * w / max(h, 1)))))
    rows = max(1, int(math.ceil(n / cols)))
    margin = 50.0
    out = []
    for i in range(n):
        c = i % cols
        r = i // cols
        x = margin + c * ((w - 2 * margin) / max(cols - 1, 1))
        y = margin + r * ((h - 2 * margin) / max(rows - 1, 1))
        out.append((x, y))
    return out


def _estimate_metrics(
    positions: list[tuple[float, float]],
    half_extent: float,
    outset: float,
    viewport_w: float,
    viewport_h: float,
) -> dict:
    """O(n) union / fill_ratio / union_frac from AABB centers (bench metadata)."""
    if not positions:
        return {
            "sum_area": 0.0,
            "union_area": 0.0,
            "fill_ratio": 0.0,
            "union_frac": 0.0,
        }
    half = half_extent + outset
    min_x = min(x for x, _ in positions) - half
    max_x = max(x for x, _ in positions) + half
    min_y = min(y for _, y in positions) - half
    max_y = max(y for _, y in positions) + half
    side = 2.0 * half
    cell = max(side * side, 1e-6)
    sum_area = len(positions) * cell
    union_area = max((max_x - min_x) * (max_y - min_y), 1e-6)
    viewport_area = max(viewport_w * viewport_h, 1e-6)
    return {
        "sum_area": sum_area,
        "union_area": union_area,
        "fill_ratio": min(1.0, sum_area / union_area),
        "union_frac": union_area / viewport_area,
        "union_w": max_x - min_x,
        "union_h": max_y - min_y,
    }


def _run_worker(layout: str, visual: str) -> dict:
    cmd = [
        sys.executable,
        __file__,
        "--worker",
        "--layout-key",
        layout,
        "--visual-key",
        visual,
        "--n",
        str(args.n),
        "--duration",
        str(args.duration),
        "--warmup",
        str(args.warmup),
        "--width",
        str(args.width),
        "--height",
        str(args.height),
        "--quality",
        str(args.quality),
        "--kind",
        str(args.kind),
        "--fb",
        str(args.fb),
        "--glow-radius",
        str(args.glow_radius),
        "--glow-sigma",
        str(args.glow_sigma),
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=max(60.0, args.duration + args.warmup + 30.0),
    )
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{") and '"layout"' in line:
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {
        "layout": layout,
        "visual": visual,
        "error": f"worker failed rc={proc.returncode}",
        "tail": out[-1500:],
    }


def _suite() -> None:
    rows = []
    for layout, visual in CELLS:
        print(f"… {layout}/{visual}", flush=True)
        rows.append(_run_worker(layout, visual))

    print()
    print(
        f"=== glow fleet bench  n={args.n}  {args.width}x{args.height}  "
        f"q={args.quality}  kind={args.kind}  fb={args.fb}  "
        f"glow=r{args.glow_radius}/s{args.glow_sigma}  "
        f"warm={args.warmup}s  dur={args.duration}s ==="
    )
    print(
        f"{'layout':<10} {'visual':<10} {'fps':>7} {'work':>7} {'draw':>7} "
        f"{'sub':>6} {'pres':>6} {'fill':>6} {'ufrac':>6} {'fb':>11}"
    )
    for r in rows:
        if r.get("error"):
            print(f"{r.get('layout', '?'):<10} {r.get('visual', '?'):<10} ERROR")
            print(r.get("tail", "")[-400:])
            continue
        fb = f"{r.get('fb_width', '?')}x{r.get('fb_height', '?')}"
        print(
            f"{r['layout']:<10} {r['visual']:<10} {r['fps']:7.1f} "
            f"{r['work_ms']:7.2f} {r['draw_ms']:7.2f} {r['submit_ms']:6.2f} "
            f"{r['present_ms']:6.2f} {r['fill_ratio']:6.2f} {r['union_frac']:6.2f} "
            f"{fb:>11}"
        )

    by = {(r["layout"], r["visual"]): r for r in rows if not r.get("error")}
    gc = by.get(("clustered", "glow"))
    gs = by.get(("sparse", "glow"))
    ns = by.get(("sparse", "none"))
    if gc and gs and ns:
        print()
        print("Cliff (same shared Glow, layout only):")
        print(
            f"  clustered glow  work={gc['work_ms']:.2f} draw={gc['draw_ms']:.2f} "
            f"sub={gc['submit_ms']:.2f} pres={gc['present_ms']:.2f}  fps={gc['fps']:.0f}"
        )
        print(
            f"  sparse glow     work={gs['work_ms']:.2f} draw={gs['draw_ms']:.2f} "
            f"sub={gs['submit_ms']:.2f} pres={gs['present_ms']:.2f}  fps={gs['fps']:.0f}"
        )
        print(
            f"  sparse none     work={ns['work_ms']:.2f} draw={ns['draw_ms']:.2f} "
            f"sub={ns['submit_ms']:.2f} present={ns['present_ms']:.2f}  fps={ns['fps']:.0f}"
        )
        print(
            f"  sparse−clustered (glow): Δwork={gs['work_ms'] - gc['work_ms']:+.2f} "
            f"Δdraw={gs['draw_ms'] - gc['draw_ms']:+.2f} "
            f"Δsubmit={gs['submit_ms'] - gc['submit_ms']:+.2f} "
            f"Δpresent={gs['present_ms'] - gc['present_ms']:+.2f} "
            f"fps×={gc['fps'] / max(gs['fps'], 1e-6):.2f}"
        )
        print(
            f"  glow−none (sparse):      "
            f"Δwork={gs['work_ms'] - ns['work_ms']:+.2f} "
            f"Δdraw={gs['draw_ms'] - ns['draw_ms']:+.2f} "
            f"Δsubmit={gs['submit_ms'] - ns['submit_ms']:+.2f} "
            f"Δpresent={gs['present_ms'] - ns['present_ms']:+.2f}"
        )
    cs = by.get(("sparse", "cheapglow"))
    if cs and ns:
        print()
        print("CheapGlow (sparse) vs none:")
        print(
            f"  sparse cheapglow work={cs['work_ms']:.2f} draw={cs['draw_ms']:.2f} "
            f"sub={cs['submit_ms']:.2f} present={cs['present_ms']:.2f}  fps={cs['fps']:.0f}"
        )
        print(
            f"  Δ vs none: work={cs['work_ms'] - ns['work_ms']:+.2f} "
            f"draw={cs['draw_ms'] - ns['draw_ms']:+.2f} "
            f"present={cs['present_ms'] - ns['present_ms']:+.2f}"
        )

    payload = {
        "machine": platform.platform(),
        "n": args.n,
        "width": args.width,
        "height": args.height,
        "quality": args.quality,
        "kind": args.kind,
        "fb_mode": args.fb,
        "glow_radius": args.glow_radius,
        "glow_sigma": args.glow_sigma,
        "warmup": args.warmup,
        "duration": args.duration,
        "rows": rows,
    }
    print()
    print(json.dumps(payload, indent=2))
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        print(f"Wrote {args.json_path}", flush=True)


if __name__ == "__main__" and args.suite and not args.worker:
    _suite()
    sys.exit(0)

if __name__ != "__main__" and not args.worker:
    # Allow importing helpers without opening a window / running a worker.
    raise SystemExit(0)

# --- worker -----------------------------------------------------------------
from scena import *  # noqa: E402
from scena.orchestration import ScenaFramework, callback_if_exists  # noqa: E402
from scena.process import tick_processes  # noqa: E402
from scena.state import get_scena_system  # noqa: E402
from scena.transients import tick_all_transients  # noqa: E402
from scena.spatial_fx import tick_all_spatial_fx  # noqa: E402
from OpenGL import GL as _GL  # noqa: E402
import glfw  # noqa: E402

W, H = args.width, args.height
layout = args.layout_key if args.worker else args.layout
visual = args.visual_key if args.worker else args.visual
half_extent = 14.0 if args.kind == "sprite" else 12.0
blur = max(args.glow_sigma + args.glow_radius * 0.65, 4.0)
glow_outset = 3.0 * blur

init(width=W, height=H, title=f"glow fleet {layout}/{visual}")
fw = ScenaFramework.get_instance()
if args.fb == "design":
    fw._compute_window_size = (
        lambda design_w, design_h, window_scale: (int(design_w), int(design_h))
    )
canvas.background = (0.04, 0.05, 0.08, 1)
set_fx_auto(False)
canvas.fx_quality = args.quality

centers = _positions(layout, args.n, W, H)
metrics = _estimate_metrics(centers, half_extent, glow_outset, float(W), float(H))
movers = []
shared_glow = None
if visual == "glow":
    shared_glow = Glow(
        color="tomato", radius=args.glow_radius, sigma=args.glow_sigma
    )
elif visual == "cheapglow":
    shared_glow = CheapGlow(
        color="tomato", radius=args.glow_radius, sigma=args.glow_sigma
    )

sheet = Sheet("examples/media/shooter/sheet.xml") if args.kind == "sprite" else None

for i, (x, y) in enumerate(centers):
    if args.kind == "sprite":
        frame = ("fire06.png", "laserBlue02.png", "laserRed01.png")[i % 3]
        shp = Sprite(sheet, frame=frame, height=18, center=(x, y))
    else:
        kind = i % 3
        if kind == 0:
            shp = Circle(center=(x, y), radius=half_extent)
        elif kind == 1:
            shp = Square(center=(x, y), length=half_extent * 1.6, angle=i * 7)
        else:
            shp = EquilateralTriangle(
                center=(x, y), radius=half_extent, angle=i * 5
            )
        shp.set_color(("tomato", "deepskyblue", "gold", "lime")[i % 4])
    if shared_glow is not None:
        shp.visual = shared_glow
    movers.append({"shape": shp, "hx": x, "hy": y, "a": i * 0.17})

canvas.framerate = "max"
if not fw._windowed:
    fw.open_window()
canvas.framerate = "max"

stats = {
    "draw_ms": 0.0,
    "submit_ms": 0.0,
    "present_ms": 0.0,
    "work_ms": 0.0,
    "frames": 0,
}


def instrumented_run(self):
    self._running = True
    callback_if_exists(self, "setup", self._canvas)
    self.frame_count = 0
    canvas.framerate = "max"
    t_start = time.perf_counter()
    recording = False

    while self._running and not glfw.window_should_close(self._window):
        ss = get_scena_system()
        if ss is not None:
            ss.begin_frame_batch()
        try:
            current_time = time.perf_counter()
            elapsed = current_time - t_start
            if elapsed >= args.warmup:
                recording = True
            if elapsed >= args.warmup + args.duration:
                self._running = False
                break

            self.clock._tick(current_time)
            t = self.clock.time
            self._scena_draw.advance_layer_scroll(t)

            for m in movers:
                m["shape"].move_to(
                    m["hx"] + math.sin(t * 1.5 + m["a"]) * 6,
                    m["hy"] + math.cos(t * 1.2 + m["a"]) * 5,
                )

            if not self._needs_scene_rt():
                self._draw_background(self._drawing_canvas)
                self._apply_view_transform()

            glfw.poll_events()
            callback_if_exists(self, "update", clock.dt, self._canvas)

            tick_processes()
            if self.collision_system is not None:
                self.collision_system.step()
            if ss is not None:
                ss.flush()
        finally:
            if ss is not None:
                ss.end_frame_batch()

        tick_all_transients()
        tick_all_spatial_fx()

        draw_dt = 0.0
        if self._needs_scene_rt():
            _GL.glViewport(0, 0, self.fb_width, self.fb_height)
            self._was_using_post = True
            self._prefer_scene_blit = True
            scene_surf = self._ensure_scene_surface()
            scene_canvas = scene_surf.getCanvas()
            self._draw_background(scene_canvas)
            self._apply_view_transform(scene_canvas)
            top_exempt = self._top_exempt_from_post()
            t0 = time.perf_counter()
            self._draw_scene_to(scene_canvas, exclude_top=top_exempt)
            draw_dt = (time.perf_counter() - t0) * 1000.0
            scene_image = scene_surf.makeImageSnapshot()
            self._clear_background_fast(self._drawing_canvas)
            if self._post_draw_live():
                callback_if_exists(self, "post_draw", self._drawing_canvas, scene_image)
            else:
                self.post_fx_stack._render(
                    self._drawing_canvas, scene_image, fw=self, t=self.clock.time
                )
            self._apply_view_transform()
            if top_exempt:
                self._draw_top_layer(self._drawing_canvas)
        else:
            _GL.glViewport(0, 0, self.fb_width, self.fb_height)
            t0 = time.perf_counter()
            self._scena_draw.draw(t=self.clock.time if self.clock is not None else None)
            draw_dt = (time.perf_counter() - t0) * 1000.0

        self._apply_view_transform(camera=False)
        self.widget_manager.draw(self._drawing_canvas)

        t0 = time.perf_counter()
        self._drawing_surface.flushAndSubmit()
        sub_dt = (time.perf_counter() - t0) * 1000.0
        # Large filter saveLayers often finish on present, not flushAndSubmit.
        t0 = time.perf_counter()
        glfw.swap_buffers(self._window)
        present_dt = (time.perf_counter() - t0) * 1000.0
        work = (time.perf_counter() - current_time) * 1000.0
        self.frame_count += 1

        if recording:
            stats["draw_ms"] += draw_dt
            stats["submit_ms"] += sub_dt
            stats["present_ms"] += present_dt
            stats["work_ms"] += work
            stats["frames"] += 1


fw.run = types.MethodType(instrumented_run, fw)
run()

n = max(1, stats["frames"])
out = {
    "layout": layout,
    "visual": visual,
    "n": args.n,
    "quality": args.quality,
    "kind": args.kind,
    "fb_mode": args.fb,
    "width": W,
    "height": H,
    "fb_width": int(getattr(fw, "fb_width", 0) or 0),
    "fb_height": int(getattr(fw, "fb_height", 0) or 0),
    "pixel_ratio": float(getattr(fw, "pixel_ratio", 1.0) or 1.0),
    "frames": n,
    "fps": n / args.duration,
    "work_ms": stats["work_ms"] / n,
    "draw_ms": stats["draw_ms"] / n,
    "submit_ms": stats["submit_ms"] / n,
    "present_ms": stats["present_ms"] / n,
    "fill_ratio": metrics["fill_ratio"],
    "union_frac": metrics["union_frac"],
    "union_area": metrics["union_area"],
    "sum_area": metrics["sum_area"],
    "glow_radius": args.glow_radius,
    "glow_sigma": args.glow_sigma,
    "batch_shared_filters": bool(getattr(canvas, "batch_shared_filters", True)),
}
print(json.dumps(out), flush=True)
