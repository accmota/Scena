"""
perf_scena.py -- Scena-framework performance benchmark.

Creates N random, deterministic, solid shapes (rectangles, circles,
equilateral triangles -- see perf_common.generate_shapes) that spin in place,
and reports the maximum frame rate Scena can sustain (VSync disabled, no
per-frame sleep) after a short warmup. Compare against perf_raw_skia.py,
which draws the identical scene with plain GLFW + Skia calls and no Scena
machinery, to estimate the framework's overhead.

Usage:
    python scripts/perf_scena.py [--n 300] [--duration 10] [--warmup 1] [--seed 42]
    python scripts/perf_scena.py --profile --duration 3 --warmup 0.5
"""
import math
import time

from perf_common import (
    build_arg_parser, generate_shapes, print_report, WIDTH, HEIGHT,
)
from perf_profile import FrameProfiler, add_profile_args

parser = build_arg_parser(__doc__)
add_profile_args(parser)
args = parser.parse_args()

from scena import *  # noqa: E402  (must come after arg parsing, before any shape/canvas use)
from scena.orchestration import ScenaFramework  # noqa: E402

init(width=WIDTH, height=HEIGHT, title="Scena perf benchmark")

# Force the OS window to exactly WIDTH x HEIGHT points (design == window, no
# monitor-fraction scaling), so both benchmark scripts rasterize the same
# physical pixel count -- otherwise FPS would not be comparable.
_fw = ScenaFramework.get_instance()
_fw._compute_window_size = lambda design_w, design_h, window_scale: (int(design_w), int(design_h))

canvas.background = (0.1, 0.1, 0.12, 1)
set_defaults(line=None)  # solid shapes only, no strokes

specs = generate_shapes(args.n, WIDTH, HEIGHT, args.seed)

rotating = []  # (shape, spec) pairs for shapes whose angle we animate each frame
for i, spec in enumerate(specs):
    kind = spec["kind"]
    x, y = spec["x"], spec["y"]

    if kind == "rect":
        w, h = spec["size"]
        shp = Rect(center=(x, y), width=w, height=h, angle=spec["angle0"])
        rotating.append((shp, spec))
    elif kind == "circle":
        shp = Circle(center=(x, y), radius=spec["size"])
    else:  # triangle
        shp = EquilateralTriangle(center=(x, y), radius=spec["size"], angle=spec["angle0"])
        rotating.append((shp, spec))

    shp.fill = spec["color"]

# --- Benchmark / profile state ---------------------------------------------
_start_time = None
_warmup_done = False
_bench_start = None
_frame_times = []
_prof = FrameProfiler.install() if args.profile else None


def _finish():
    print_report("Scena framework", _frame_times, args.n)
    if _prof is not None:
        _prof.report("Scena framework — profile breakdown")
        FrameProfiler.uninstall()
    import glfw
    glfw.set_window_should_close(_fw._window, True)


def _update_body(dt):
    global _start_time, _warmup_done, _bench_start

    now = time.perf_counter()
    if _start_time is None:
        _start_time = now
    elapsed = now - _start_time

    # Reactive write: this is exactly the cost we're measuring -- one
    # Attribute assignment (-> mark_dirty under frame batch) per rotating
    # shape, every frame; flush() before draw resolves the cone once.
    for shp, spec in rotating:
        shp.angle = (spec["angle0"] + spec["speed"] * elapsed) % 360.0

    if not _warmup_done:
        if elapsed >= args.warmup:
            _warmup_done = True
            _bench_start = now
            if _prof is not None:
                _prof.start_recording()
        return

    _frame_times.append(dt)
    if now - _bench_start >= args.duration:
        _finish()


update = _prof.wrap_update(_update_body) if _prof is not None else _update_body

set_fx_auto(False)
canvas.framerate = "max"  # disable VSync/sleep -- run flat out
run()
