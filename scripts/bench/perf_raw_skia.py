"""
perf_raw_skia.py -- baseline performance benchmark using GLFW + Skia directly,
with no Scena framework involved.

Draws the identical deterministic scene as perf_scena.py (same shapes,
positions, colors, and rotation, via perf_common.generate_shapes) straight
onto a GL-backed Skia surface, using the same GLFW/OpenGL/Skia setup Scena
itself uses under the hood (see scena/orchestration.py: _create_glfw_window,
_init_skia, _create_drawing_surface). Comparing its FPS against
perf_scena.py's estimates the overhead of Scena's reactive scene graph.

Usage:
    python scripts/perf_raw_skia.py [--n 300] [--duration 10] [--warmup 1] [--seed 42]
"""
import math
import time

import glfw
import skia
from OpenGL import GL

from perf_common import build_arg_parser, generate_shapes, print_report, WIDTH, HEIGHT


def create_window():
    if not glfw.init():
        raise RuntimeError("Failed to initialize GLFW")

    # Same context hints as ScenaFramework._create_glfw_window: macOS defaults
    # to a legacy 2.1 context without these, which Skia's shaders need.
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 2)
    glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, True)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.STENCIL_BITS, 8)

    window = glfw.create_window(WIDTH, HEIGHT, "Raw GLFW+Skia perf benchmark", None, None)
    if not window:
        glfw.terminate()
        raise RuntimeError("Failed to create GLFW window")

    glfw.make_context_current(window)
    glfw.swap_interval(0)  # no VSync -- run flat out, like Scena's canvas.framerate = "max"
    return window


def create_skia_surface(fb_width, fb_height):
    context = skia.GrDirectContext.MakeGL()
    backend_render_target = skia.GrBackendRenderTarget(
        fb_width, fb_height, 0, 0, skia.GrGLFramebufferInfo(0, GL.GL_RGBA8)
    )
    surface = skia.Surface.MakeFromBackendRenderTarget(
        context,
        backend_render_target,
        skia.kBottomLeft_GrSurfaceOrigin,
        skia.kRGBA_8888_ColorType,
        skia.ColorSpace.MakeSRGB(),
    )
    if not surface:
        raise RuntimeError("Failed to create Skia surface")
    return context, surface


def build_paints(specs):
    """One solid-fill, anti-aliased Skia Paint per shape, built once up front."""
    paints = []
    for spec in specs:
        r, g, b, a = spec["color"]
        paint = skia.Paint(AntiAlias=True, Style=skia.Paint.kFill_Style)
        paint.setColor4f(skia.Color4f(r, g, b, a))
        paints.append(paint)
    return paints


def draw_shape(sk_canvas, spec, paint, angle):
    kind = spec["kind"]
    x, y = spec["x"], spec["y"]

    if kind == "circle":
        sk_canvas.drawCircle(x, y, spec["size"], paint)

    elif kind == "rect":
        w, h = spec["size"]
        hw, hh = w / 2.0, h / 2.0
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        corners = ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))
        pts = [(x + cx * cos_a - cy * sin_a, y + cx * sin_a + cy * cos_a) for cx, cy in corners]
        path = skia.Path()
        path.moveTo(*pts[0])
        for p in pts[1:]:
            path.lineTo(*p)
        path.close()
        sk_canvas.drawPath(path, paint)

    else:  # triangle (equilateral, circumradius = spec["size"])
        r = spec["size"]
        path = skia.Path()
        for i in range(3):
            a = angle + i * (2.0 * math.pi / 3.0)
            px, py = x + r * math.cos(a), y + r * math.sin(a)
            if i == 0:
                path.moveTo(px, py)
            else:
                path.lineTo(px, py)
        path.close()
        sk_canvas.drawPath(path, paint)


def main():
    args = build_arg_parser(__doc__).parse_args()
    specs = generate_shapes(args.n, WIDTH, HEIGHT, args.seed)
    paints = build_paints(specs)

    window = create_window()

    win_width, win_height = glfw.get_window_size(window)
    fb_width, fb_height = glfw.get_framebuffer_size(window)
    pixel_ratio = (fb_width / win_width) if win_width else 1.0
    GL.glViewport(0, 0, fb_width, fb_height)

    context, surface = create_skia_surface(fb_width, fb_height)
    sk_canvas = surface.getCanvas()

    background = skia.Color4f(0.1, 0.1, 0.12, 1.0)

    start_time = time.perf_counter()
    last_time = start_time
    warmup_done = False
    bench_start = None
    frame_times = []

    while not glfw.window_should_close(window):
        now = time.perf_counter()
        dt = now - last_time
        last_time = now
        elapsed = now - start_time

        glfw.poll_events()

        sk_canvas.clear(background)
        sk_canvas.resetMatrix()
        sk_canvas.scale(pixel_ratio, pixel_ratio)

        for spec, paint in zip(specs, paints):
            if spec["kind"] == "circle":
                angle = 0.0  # circles are visually rotation-invariant; skip the math
            else:
                angle = (spec["angle0"] + spec["speed"] * elapsed) % math.tau
            draw_shape(sk_canvas, spec, paint, angle)

        surface.flushAndSubmit()
        glfw.swap_buffers(window)

        if not warmup_done:
            if elapsed >= args.warmup:
                warmup_done = True
                bench_start = now
        else:
            frame_times.append(dt)
            if now - bench_start >= args.duration:
                break

    context.abandonContext()
    glfw.terminate()

    print_report("Raw GLFW + Skia (no Scena)", frame_times, args.n)


if __name__ == "__main__":
    main()
