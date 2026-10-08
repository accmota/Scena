"""
perf_profile.py -- lightweight frame / reactivity profiler for Scena scripts.

Installs monkeypatches on UpdateManager, Container._recalculate_formula, and
ScenaCanvas.draw so scripts can attribute wall time to:

  user_update | flush (reactive) | scene_draw | other (swap / clear / widgets)

and count reactive work: cycles, cone size, recalcs vs written-skips vs cold-skips,
recalcs by node class, takeins during recalc.

Usage (from a script after `from scena import *`):

    from perf_profile import FrameProfiler
    prof = FrameProfiler.install()
    ...
    # in update(), after warmup:
    prof.end_frame()
    # on finish:
    prof.report()
    FrameProfiler.uninstall()

CLI helpers: add_profile_args(parser) → --profile / --profile-frames
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional


class FrameProfiler:
    """Accumulate per-frame phase times and reactive counters."""

    _instance: Optional["FrameProfiler"] = None
    _orig: Dict[str, Any] = {}

    def __init__(self):
        self.enabled = True
        self.recording = False  # set True after warmup
        self.frames = 0

        # Phase times (seconds), summed over recorded frames
        self.t_user_update = 0.0
        self.t_flush = 0.0
        self.t_draw = 0.0
        self.t_frame = 0.0  # wall time between end_frame calls

        # Reactive counters (summed)
        self.n_cycles = 0
        self.n_cone = 0
        self.n_process = 0
        self.n_recalc = 0
        self.n_written_skip = 0
        self.n_cold_skip = 0
        self.n_takein = 0
        self.recalc_by_class: Dict[str, int] = defaultdict(int)
        self.recalc_defining = 0
        self.recalc_derivate = 0
        self.recalc_linked = 0
        self.graph_nodes_last = 0
        self.dirty_seeds_last = 0

        # Per-frame scratch (reset at begin_frame / first hook of frame)
        self._frame_t0 = None
        self._user_t0 = None
        self._in_user_update = False

    # ------------------------------------------------------------------ install
    @classmethod
    def install(cls) -> "FrameProfiler":
        if cls._instance is not None:
            return cls._instance
        prof = cls()
        cls._instance = prof
        prof._patch()
        return prof

    @classmethod
    def uninstall(cls) -> None:
        if cls._instance is None:
            return
        cls._instance._unpatch()
        cls._instance = None

    @classmethod
    def get(cls) -> Optional["FrameProfiler"]:
        return cls._instance

    def _patch(self) -> None:
        from scena.state import UpdateManager, Container, get_scena_system, FieldType
        from scena.canvas import ScenaCanvas

        self._FieldType = FieldType
        um = UpdateManager

        # --- flush ---
        orig_flush = um.flush
        self._orig["flush"] = orig_flush

        def flush(self_um):
            if not self.enabled:
                return orig_flush(self_um)
            t0 = time.perf_counter()
            orig_flush(self_um)
            dt = time.perf_counter() - t0
            if self.recording:
                self.t_flush += dt
                self.n_cycles += 1  # effect-flush rounds (proxy for old cycles)

        um.flush = flush

        # --- mark_dirty: count invalidate cone size ---
        orig_mark = um.mark_dirty
        self._orig["mark_dirty"] = orig_mark

        def mark_dirty(self_um, node):
            if self.enabled and self.recording:
                self.n_process += 1
            return orig_mark(self_um, node)

        um.mark_dirty = mark_dirty

        # --- pull resolves ---
        orig_rl = Container._resolve_link
        self._orig["_resolve_link"] = orig_rl

        def _resolve_link(self_c):
            if not self.enabled or not self.recording or not self_c._dirty:
                return orig_rl(self_c)
            self.n_recalc += 1
            self.recalc_linked += 1
            self.recalc_by_class[type(self_c).__name__] += 1
            return orig_rl(self_c)

        Container._resolve_link = _resolve_link

        orig_rs = Container._resolve_structural
        self._orig["_resolve_structural"] = orig_rs

        def _resolve_structural(self_c):
            if not self.enabled or not self.recording or not self_c._dirty:
                return orig_rs(self_c)
            self.n_recalc += 1
            self.recalc_derivate += 1
            self.recalc_by_class[type(self_c).__name__] += 1
            return orig_rs(self_c)

        Container._resolve_structural = _resolve_structural

        # --- ScenaCanvas.draw ---
        orig_draw = ScenaCanvas.draw
        self._orig["ScenaCanvas.draw"] = orig_draw

        def canvas_draw(self_canvas):
            if not self.enabled:
                return orig_draw(self_canvas)
            t0 = time.perf_counter()
            orig_draw(self_canvas)
            dt = time.perf_counter() - t0
            if self.recording:
                self.t_draw += dt

        ScenaCanvas.draw = canvas_draw

        # --- PaintState paint cache + ImageFilter draw counting ---
        from scena.style import PaintState
        self.n_paint_rebuild = 0
        self.n_paint_cache_hit = 0
        self.n_filtered_draw = 0
        self.n_plain_draw = 0

        orig_line = PaintState._to_skia_line_paint
        orig_fill = PaintState._to_skia_fill_paint
        self._orig["to_skia_line_paint"] = orig_line
        self._orig["to_skia_fill_paint"] = orig_fill

        def _to_skia_line_paint(self_style):
            if not self.enabled or not self.recording:
                return orig_line(self_style)
            was_dirty = self_style._is_line_paint_dirty or self_style._cached_line_paint is None
            paint = orig_line(self_style)
            if paint is None:
                return None
            if was_dirty and self_style._line:
                self.n_paint_rebuild += 1
            else:
                self.n_paint_cache_hit += 1
            if self_style._line_filter:
                self.n_filtered_draw += 1
            else:
                self.n_plain_draw += 1
            return paint

        def _to_skia_fill_paint(self_style):
            if not self.enabled or not self.recording:
                return orig_fill(self_style)
            was_dirty = self_style._is_fill_paint_dirty or self_style._cached_fill_paint is None
            paint = orig_fill(self_style)
            if paint is None:
                return None
            if was_dirty and self_style._fill:
                self.n_paint_rebuild += 1
            else:
                self.n_paint_cache_hit += 1
            if self_style._fill_filter:
                self.n_filtered_draw += 1
            else:
                self.n_plain_draw += 1
            return paint

        PaintState._to_skia_line_paint = to_skia_line_paint
        PaintState._to_skia_fill_paint = to_skia_fill_paint

        # GPU submit hooks need the Skia surface (created in open_window / run).
        self.t_submit = 0.0
        self.t_swap = 0.0
        self._gpu_hooks_ready = False

        ss = get_scena_system()
        if ss is not None:
            self.graph_nodes_last = len(ss.dependency_graph.nodes)

    def _ensure_gpu_hooks(self) -> None:
        """Time GPU submit / buffer swap once the GL surface exists.

        ``skia.Surface.flushAndSubmit`` is a read-only binding, so we wrap the
        surface object itself rather than assigning the method.
        """
        if self._gpu_hooks_ready:
            return
        try:
            from scena.orchestration import ScenaFramework
            import glfw as _glfw

            fw = ScenaFramework.get_instance()
            if fw is None or getattr(fw, "_drawing_surface", None) is None:
                return

            if "drawing_surface" not in self._orig:
                real_surf = fw._drawing_surface
                self._orig["drawing_surface"] = (fw, real_surf)
                prof = self

                class _SurfaceSubmitTimer:
                    __slots__ = ("_surf",)

                    def __init__(self, surf):
                        self._surf = surf

                    def flushAndSubmit(self, *a, **kw):
                        if not prof.enabled or not prof.recording:
                            return self._surf.flushAndSubmit(*a, **kw)
                        t0 = time.perf_counter()
                        out = self._surf.flushAndSubmit(*a, **kw)
                        prof.t_submit += time.perf_counter() - t0
                        return out

                    def __getattr__(self, name):
                        return getattr(self._surf, name)

                fw._drawing_surface = _SurfaceSubmitTimer(real_surf)

            if "swap_buffers" not in self._orig:
                orig_swap = _glfw.swap_buffers
                self._orig["swap_buffers"] = orig_swap

                def swap_buffers(window):
                    if not self.enabled or not self.recording:
                        return orig_swap(window)
                    t0 = time.perf_counter()
                    out = orig_swap(window)
                    self.t_swap += time.perf_counter() - t0
                    return out

                _glfw.swap_buffers = swap_buffers

            self._gpu_hooks_ready = True
        except Exception:
            pass

    def _unpatch(self) -> None:
        from scena.state import UpdateManager, Container
        from scena.canvas import ScenaCanvas
        from scena.style import PaintState

        if "flush" in self._orig:
            UpdateManager.flush = self._orig["flush"]
        if "mark_dirty" in self._orig:
            UpdateManager.mark_dirty = self._orig["mark_dirty"]
        if "_resolve_link" in self._orig:
            Container._resolve_link = self._orig["_resolve_link"]
        if "_resolve_structural" in self._orig:
            Container._resolve_structural = self._orig["_resolve_structural"]
        if "ScenaCanvas.draw" in self._orig:
            ScenaCanvas.draw = self._orig["ScenaCanvas.draw"]
        if "to_skia_line_paint" in self._orig:
            PaintState._to_skia_line_paint = self._orig["to_skia_line_paint"]
        if "to_skia_fill_paint" in self._orig:
            PaintState._to_skia_fill_paint = self._orig["to_skia_fill_paint"]
        if "drawing_surface" in self._orig:
            fw, real_surf = self._orig["drawing_surface"]
            fw._drawing_surface = real_surf
        if "swap_buffers" in self._orig:
            import glfw as _glfw
            _glfw.swap_buffers = self._orig["swap_buffers"]
        self._orig.clear()

    # ------------------------------------------------------------------ frame API
    def begin_user_update(self) -> None:
        """Call at the start of the user update(dt) body."""
        self._user_t0 = time.perf_counter()
        self._in_user_update = True
        if self._frame_t0 is None:
            self._frame_t0 = self._user_t0

    def end_user_update(self) -> None:
        if self._user_t0 is not None and self.recording:
            self.t_user_update += time.perf_counter() - self._user_t0
        self._user_t0 = None
        self._in_user_update = False

    def end_frame(self) -> None:
        """Call once per frame after work (e.g. end of update, or timed separately).

        Note: flush/draw happen *after* user update in the run loop, so end_frame
        from inside update() only closes the previous frame's wall clock. Prefer
        calling start_recording() then letting hooks accumulate; call end_frame()
        at the start of update to book the prior frame's wall time.
        """
        now = time.perf_counter()
        if self._frame_t0 is not None and self.recording:
            self.t_frame += now - self._frame_t0
            self.frames += 1
        self._frame_t0 = now
        from scena.state import get_scena_system
        ss = get_scena_system()
        if ss is not None:
            self.graph_nodes_last = len(ss.dependency_graph.nodes)

    def start_recording(self) -> None:
        self._ensure_gpu_hooks()
        self.recording = True
        self._frame_t0 = time.perf_counter()

    def wrap_update(self, user_update: Callable) -> Callable:
        """Return an update(dt) wrapper that times the user body and books frames."""

        def wrapped(dt, *args, **kwargs):
            # Book previous frame wall time (includes prior flush+draw+swap)
            if self.recording and self._frame_t0 is not None:
                now = time.perf_counter()
                self.t_frame += now - self._frame_t0
                self.frames += 1
                self._frame_t0 = now
            elif self.recording:
                self._frame_t0 = time.perf_counter()

            self.begin_user_update()
            try:
                return user_update(dt, *args, **kwargs)
            finally:
                self.end_user_update()

        return wrapped

    # ------------------------------------------------------------------ report
    def report(self, label: str = "Scena profile") -> None:
        from scena.state import get_scena_system

        ss = get_scena_system()
        n = max(self.frames, 1)
        print("=" * 60)
        print(label)
        print("=" * 60)
        print(f"Recorded frames:      {self.frames}")
        if ss is not None:
            print(f"Graph nodes (now):    {len(ss.dependency_graph.nodes)}")
        print()
        print("Per-frame means (ms)")
        print("-" * 60)
        def row(name, total_s):
            print(f"  {name:<22} {total_s / n * 1000:8.3f}")

        row("user update(dt)", self.t_user_update)
        row("flush (reactive)", self.t_flush)
        row("scene draw (CPU)", self.t_draw)
        if getattr(self, "t_submit", 0.0) or getattr(self, "t_swap", 0.0):
            row("GPU flushAndSubmit", self.t_submit)
            row("glfw.swap_buffers", self.t_swap)
        accounted = (
            self.t_user_update + self.t_flush + self.t_draw
            + getattr(self, "t_submit", 0.0) + getattr(self, "t_swap", 0.0)
        )
        row("accounted sum", accounted)
        row("frame wall (approx)", self.t_frame)
        other = max(0.0, self.t_frame - accounted)
        row("other (clear/UI/…)", other)
        print()
        print("Reactive work (totals / per-frame)")
        print("-" * 60)
        print(f"  effect flush calls:   {self.n_cycles}  ({self.n_cycles / n:.2f}/frame)")
        print(f"  mark_dirty calls:     {self.n_process}  ({self.n_process / n:.1f}/frame)")
        print(f"  pull resolves:        {self.n_recalc}  ({self.n_recalc / n:.1f}/frame)")
        print(f"  resolve linked:       {self.recalc_linked}  ({self.recalc_linked / n:.1f}/frame)")
        print(f"  resolve structural:   {self.recalc_derivate}  ({self.recalc_derivate / n:.1f}/frame)")
        print()
        if getattr(self, "n_paint_cache_hit", 0) or getattr(self, "n_paint_rebuild", 0):
            print("Paint / ImageFilter draws (totals / per-frame)")
            print("-" * 60)
            print(f"  paint cache hits:     {self.n_paint_cache_hit}  ({self.n_paint_cache_hit / n:.1f}/frame)")
            print(f"  paint rebuilds:       {self.n_paint_rebuild}  ({self.n_paint_rebuild / n:.1f}/frame)")
            print(f"  draws w/ ImageFilter: {self.n_filtered_draw}  ({self.n_filtered_draw / n:.1f}/frame)")
            print(f"  draws plain paint:    {self.n_plain_draw}  ({self.n_plain_draw / n:.1f}/frame)")
            print()
        if self.recalc_by_class:
            print("Resolves by class (top 12)")
            print("-" * 60)
            items = sorted(self.recalc_by_class.items(), key=lambda kv: -kv[1])[:12]
            for name, count in items:
                print(f"  {name:<22} {count:8d}  ({count / n:.1f}/frame)")
        print("=" * 60)


def add_profile_args(parser) -> None:
    parser.add_argument(
        "--profile", action="store_true",
        help="install FrameProfiler and print a breakdown at the end",
    )
    parser.add_argument(
        "--profile-seconds", type=float, default=None,
        help="with --profile on interactive apps: auto-quit after N seconds of recording",
    )
