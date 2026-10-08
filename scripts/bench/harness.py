"""
bench/harness.py — shared helpers for Scena performance benchmarks.

CLI: --n --ladder --duration --warmup --seed --quality --json --profile (via add_*)

Phase harness mirrors instrumented fw.run loops so every CPU stress script
reports the same breakdown (tick / collision / flush / draw / submit / work ms).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import time
import types
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

WIDTH = 1000
HEIGHT = 700
DEFAULT_N_SHAPES = 300
DEFAULT_SEED = 42
DEFAULT_DURATION = 10.0
DEFAULT_WARMUP = 1.0

SHAPE_KINDS = ("rect", "circle", "triangle")

MARGIN = 60
RECT_SIZE_RANGE = (18, 46)
RADIUS_RANGE = (12, 28)
SPEED_RANGE = (math.degrees(0.3), math.degrees(2.2))

PHASE_KEYS = (
    "tick_ms",
    "coll_ms",
    "flush_ms",
    "transient_ms",
    "spatial_ms",
    "bg_ms",
    "draw_ms",
    "post_ms",
    "submit_ms",
    "present_ms",
    "work_ms",
    "frames",
)


def generate_shapes(n=DEFAULT_N_SHAPES, width=WIDTH, height=HEIGHT, seed=DEFAULT_SEED):
    """Return a list of `n` plain-dict shape specs, deterministic for a given seed."""
    rng = random.Random(seed)
    shapes = []
    for _ in range(n):
        kind = rng.choice(SHAPE_KINDS)
        x = rng.uniform(MARGIN, width - MARGIN)
        y = rng.uniform(MARGIN, height - MARGIN)

        if kind == "rect":
            size = (rng.uniform(*RECT_SIZE_RANGE), rng.uniform(*RECT_SIZE_RANGE))
        else:
            size = rng.uniform(*RADIUS_RANGE)

        color = (
            rng.uniform(0.15, 0.95),
            rng.uniform(0.15, 0.95),
            rng.uniform(0.15, 0.95),
            1.0,
        )
        angle0 = rng.uniform(0.0, 360.0)
        speed = rng.uniform(*SPEED_RANGE) * rng.choice((-1.0, 1.0))

        shapes.append({
            "kind": kind,
            "x": x,
            "y": y,
            "size": size,
            "color": color,
            "angle0": angle0,
            "speed": speed,
        })
    return shapes


def parse_ladder(text: Optional[str]) -> List[int]:
    """Parse ``--ladder 50,200,800`` into a list of ints. Empty → []."""
    if not text:
        return []
    out: List[int] = []
    for part in str(text).split(","):
        part = part.strip()
        if not part:
            continue
        out.append(int(part))
    return out


def build_arg_parser(description):
    """Common CLI surface shared by solid-shape benchmark scripts."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--n", type=int, default=DEFAULT_N_SHAPES,
                        help=f"number of shapes (default {DEFAULT_N_SHAPES})")
    parser.add_argument("--ladder", type=str, default=None,
                        help="comma-separated N values (e.g. 50,200,800); overrides --n")
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION,
                        help=f"measured benchmark duration in seconds (default {DEFAULT_DURATION})")
    parser.add_argument("--warmup", type=float, default=DEFAULT_WARMUP,
                        help=f"warmup duration in seconds, excluded from stats (default {DEFAULT_WARMUP})")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED,
                        help=f"RNG seed for deterministic scene layout (default {DEFAULT_SEED})")
    parser.add_argument(
        "--quality", default=None,
        choices=("low", "medium", "high", "max"),
        help="canvas.fx_quality (omit = leave default)",
    )
    parser.add_argument(
        "--json", dest="json_path", default=None,
        help="write results JSON to this path",
    )
    return parser


def add_bench_args(parser: argparse.ArgumentParser, *, duration=2.0, warmup=0.5) -> argparse.ArgumentParser:
    """Add ``--bench`` / ``--duration`` / ``--warmup`` / ladder / json flags."""
    parser.add_argument("--bench", action="store_true",
                        help="uncapped FPS, phase-time, then exit")
    parser.add_argument("--duration", type=float, default=duration,
                        help=f"measured seconds when --bench (default {duration})")
    parser.add_argument("--warmup", type=float, default=warmup,
                        help=f"warmup seconds excluded from stats (default {warmup})")
    parser.add_argument("--ladder", type=str, default=None,
                        help="comma-separated N values (e.g. 50,200,800)")
    parser.add_argument(
        "--json", dest="json_path", default=None,
        help="write results JSON to this path",
    )
    return parser


def add_quality_arg(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument(
        "--quality", default="high",
        choices=("low", "medium", "high", "max"),
        help="canvas.fx_quality (default high)",
    )
    return parser


def configure_bench(*, quality=None, uncapped: bool = True) -> None:
    """Lock presentation so FX Auto cannot move quality/rate mid-measure.

    Product Auto is on by default (high@60). Benches must opt out.
    """
    from scena import canvas, set_fx_auto

    set_fx_auto(False)
    if quality is not None:
        canvas.fx_quality = quality
    if uncapped:
        canvas.framerate = "max"


def write_json(path: str, payload: Any) -> None:
    """Write ``payload`` as JSON, creating parent dirs if needed."""
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def summarize(frame_times):
    """Compute FPS / frame-time statistics from a list of per-frame durations (seconds)."""
    n = len(frame_times)
    if n == 0:
        return {"frames": 0}

    total = sum(frame_times)
    sorted_times = sorted(frame_times)
    p95_index = min(n - 1, int(0.95 * (n - 1)))

    return {
        "frames": n,
        "duration_s": total,
        "avg_fps": n / total if total > 0 else 0.0,
        "mean_frame_ms": (total / n) * 1000.0,
        "best_frame_ms": sorted_times[0] * 1000.0,
        "p95_frame_ms": sorted_times[p95_index] * 1000.0,
        "worst_frame_ms": sorted_times[-1] * 1000.0,
    }


def print_report(label, frame_times, n_shapes):
    """Print a human-readable performance report to stdout."""
    stats = summarize(frame_times)
    print("=" * 60)
    print(label)
    print("=" * 60)
    if stats["frames"] == 0:
        print("No frames captured -- benchmark duration too short?")
        print("=" * 60)
        return
    print(f"Shapes:               {n_shapes}")
    print(f"Frames captured:      {stats['frames']}")
    print(f"Measured duration:    {stats['duration_s']:.2f} s")
    print(f"Average FPS:          {stats['avg_fps']:.1f}")
    print(f"Mean frame time:      {stats['mean_frame_ms']:.3f} ms")
    print(f"Best frame time:      {stats['best_frame_ms']:.3f} ms")
    print(f"P95 frame time:       {stats['p95_frame_ms']:.3f} ms")
    print(f"Worst frame time:     {stats['worst_frame_ms']:.3f} ms")
    print(f"Shape-draws / sec:    {stats['avg_fps'] * n_shapes:,.0f}")
    print("=" * 60)


def empty_phase_stats() -> Dict[str, float]:
    """Zeroed accumulator dict for ``install_phase_run``."""
    return {k: 0.0 for k in PHASE_KEYS}


def average_phase_stats(stats: Dict[str, float]) -> Dict[str, float]:
    """Convert cumulative phase ms into per-frame averages (+ fps)."""
    n = max(1, int(stats.get("frames", 0) or 0))
    out = {k: float(stats.get(k, 0.0) or 0.0) / n for k in PHASE_KEYS if k != "frames"}
    out["frames"] = float(stats.get("frames", 0) or 0)
    work = float(stats.get("work_ms", 0.0) or 0.0)
    out["fps"] = (n / (work / 1000.0)) if work > 0 else 0.0
    return out


def print_phase_report(label: str, stats: Dict[str, float]) -> None:
    """Print mean phase times from a cumulative ``install_phase_run`` accumulator."""
    avg = average_phase_stats(stats)
    print("=" * 60)
    print(label)
    print("=" * 60)
    if avg["frames"] <= 0:
        print("No frames captured -- benchmark duration too short?")
        print("=" * 60)
        return
    print(f"Frames:               {int(avg['frames'])}")
    print(f"Average FPS:          {avg['fps']:.1f}")
    print(f"work_ms:              {avg['work_ms']:.3f}")
    print(f"  tick_ms:            {avg['tick_ms']:.3f}")
    print(f"  coll_ms:            {avg['coll_ms']:.3f}")
    print(f"  flush_ms:           {avg['flush_ms']:.3f}")
    print(f"  transient_ms:       {avg['transient_ms']:.3f}")
    print(f"  spatial_ms:         {avg['spatial_ms']:.3f}")
    print(f"  bg_ms:              {avg['bg_ms']:.3f}")
    print(f"  draw_ms:            {avg['draw_ms']:.3f}")
    print(f"  post_ms:            {avg['post_ms']:.3f}")
    print(f"  submit_ms:          {avg['submit_ms']:.3f}")
    print(f"  present_ms:         {avg['present_ms']:.3f}")
    print("=" * 60)


def install_phase_run(
    fw,
    *,
    duration: float,
    warmup: float,
    stats: Optional[Dict[str, float]] = None,
    on_frame: Optional[Callable[[Any, bool], None]] = None,
    force_1x_pixels: bool = True,
    burst_window: Optional[Tuple[float, float]] = None,
    burst_stats: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """Replace ``fw.run`` with a phase-timed loop; return the stats accumulator."""
    import glfw
    from OpenGL import GL as _GL

    from scena import canvas, clock, set_fx_auto
    from scena.orchestration import callback_if_exists
    from scena.process import tick_processes
    from scena.spatial_fx import tick_all_spatial_fx
    from scena.state import get_scena_system
    from scena.transients import tick_all_transients

    if stats is None:
        stats = empty_phase_stats()
    else:
        for k in PHASE_KEYS:
            stats.setdefault(k, 0.0)

    if burst_window is not None:
        if burst_stats is None:
            burst_stats = empty_phase_stats()
        else:
            for k in PHASE_KEYS:
                burst_stats.setdefault(k, 0.0)
        burst_lo, burst_hi = float(burst_window[0]), float(burst_window[1])
    else:
        burst_lo = burst_hi = -1.0

    if force_1x_pixels:
        fw._compute_window_size = lambda dw, dh, wf: (int(dw), int(dh))

    def instrumented_run(self):
        self._running = True
        callback_if_exists(self, "setup", self._canvas)
        self.frame_count = 0
        set_fx_auto(False)
        canvas.framerate = "max"
        t_start = time.perf_counter()
        recording = False
        record_t0 = 0.0

        while self._running and not glfw.window_should_close(self._window):
            ss = get_scena_system()
            if ss is not None:
                ss.begin_frame_batch()
            try:
                current_time = time.perf_counter()
                elapsed = current_time - t_start
                if elapsed >= warmup:
                    if not recording:
                        record_t0 = current_time
                    recording = True
                if elapsed >= warmup + duration:
                    self._running = False
                    break

                self.clock._tick(current_time)
                # Layer scroll is world state (frame tick, not draw).
                self._scena_draw.advance_layer_scroll(self.clock.time)

                bg_dt = 0.0
                if not self._needs_scene_rt():
                    t_bg0 = time.perf_counter()
                    self._draw_background(self._drawing_canvas)
                    self._apply_view_transform()
                    bg_dt = (time.perf_counter() - t_bg0) * 1000.0

                glfw.poll_events()
                callback_if_exists(self, "update", clock.dt, self._canvas)

                t0 = time.perf_counter()
                tick_processes()
                tick_dt = (time.perf_counter() - t0) * 1000.0

                t0 = time.perf_counter()
                if self.collision_system is not None:
                    self.collision_system.step()
                coll_dt = (time.perf_counter() - t0) * 1000.0

                t0 = time.perf_counter()
                if ss is not None:
                    ss.flush()
                flush_dt = (time.perf_counter() - t0) * 1000.0
            finally:
                if ss is not None:
                    ss.end_frame_batch()

            t0 = time.perf_counter()
            tick_all_transients()
            tr_dt = (time.perf_counter() - t0) * 1000.0

            t0 = time.perf_counter()
            tick_all_spatial_fx()
            sx_dt = (time.perf_counter() - t0) * 1000.0

            post_dt = 0.0
            draw_dt = 0.0
            if self._needs_scene_rt():
                _GL.glViewport(0, 0, self.fb_width, self.fb_height)
                self._was_using_post = True
                self._prefer_scene_blit = True
                scene_surf = self._ensure_scene_surface()
                scene_canvas = scene_surf.getCanvas()
                t_bg0 = time.perf_counter()
                self._draw_background(scene_canvas)
                self._apply_view_transform(scene_canvas)
                bg_dt += (time.perf_counter() - t_bg0) * 1000.0
                top_exempt = self._top_exempt_from_post()
                t0 = time.perf_counter()
                self._draw_scene_to(scene_canvas, exclude_top=top_exempt)
                draw_dt = (time.perf_counter() - t0) * 1000.0
                scene_image = scene_surf.makeImageSnapshot()
                self._clear_background_fast(self._drawing_canvas)
                t0 = time.perf_counter()
                if self._post_draw_live():
                    callback_if_exists(self, "post_draw", self._drawing_canvas, scene_image)
                else:
                    self.post_fx_stack._render(
                        self._drawing_canvas, scene_image, fw=self, t=self.clock.time
                    )
                post_dt = (time.perf_counter() - t0) * 1000.0
                self._apply_view_transform()
                if top_exempt:
                    self._draw_top_layer(self._drawing_canvas)
            else:
                _GL.glViewport(0, 0, self.fb_width, self.fb_height)
                t = self.clock.time if self.clock is not None else None
                t0 = time.perf_counter()
                self._scena_draw.draw(t=t)
                draw_dt = (time.perf_counter() - t0) * 1000.0

            self._apply_view_transform(camera=False)
            self.widget_manager.draw(self._drawing_canvas)

            t0 = time.perf_counter()
            self._drawing_surface.flushAndSubmit()
            sub_dt = (time.perf_counter() - t0) * 1000.0
            t0 = time.perf_counter()
            glfw.swap_buffers(self._window)
            present_dt = (time.perf_counter() - t0) * 1000.0
            work = (time.perf_counter() - current_time) * 1000.0
            self.frame_count += 1

            if recording:
                stats["tick_ms"] += tick_dt
                stats["coll_ms"] += coll_dt
                stats["flush_ms"] += flush_dt
                stats["transient_ms"] += tr_dt
                stats["spatial_ms"] += sx_dt
                stats["bg_ms"] += bg_dt
                stats["draw_ms"] += draw_dt
                stats["post_ms"] += post_dt
                stats["submit_ms"] += sub_dt
                stats["present_ms"] += present_dt
                stats["work_ms"] += work
                stats["frames"] += 1
                if burst_stats is not None and burst_lo >= 0.0:
                    rec_elapsed = current_time - record_t0
                    in_burst = burst_lo <= rec_elapsed < burst_hi
                    if in_burst:
                        burst_stats["tick_ms"] += tick_dt
                        burst_stats["coll_ms"] += coll_dt
                        burst_stats["flush_ms"] += flush_dt
                        burst_stats["transient_ms"] += tr_dt
                        burst_stats["spatial_ms"] += sx_dt
                        burst_stats["bg_ms"] += bg_dt
                        burst_stats["draw_ms"] += draw_dt
                        burst_stats["post_ms"] += post_dt
                        burst_stats["submit_ms"] += sub_dt
                        burst_stats["present_ms"] += present_dt
                        burst_stats["work_ms"] += work
                        burst_stats["frames"] += 1
                    self._bench_in_burst = in_burst
                else:
                    self._bench_in_burst = False
            else:
                self._bench_in_burst = False

            if on_frame is not None:
                on_frame(self, recording)

    fw.run = types.MethodType(instrumented_run, fw)
    return stats
