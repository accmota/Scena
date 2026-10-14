"""
app_link_stress.py -- ~200 shapes, shallow reactive links, lots of motion.

Builds a diverse scene (rects, squares, circles, ellipses, polygons, triangles,
lines) and wires them with:
  - constructor Attribute links  (Line(p1=…, p2=…), Ellipse(from_rect=…), …)
  - DirectLink / FormulaLink via @=
Links are *shallow* (driver → dependent only; no A→B→C chains).

Many free "driver" shapes move / rotate / scale each frame; dependents track
them through the reactive graph.

Usage:
    python scripts/app_link_stress.py
    python scripts/app_link_stress.py --profile --profile-seconds 5
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from perf_profile import FrameProfiler, add_profile_args

_parser = argparse.ArgumentParser(description=__doc__)
add_profile_args(_parser)
_parser.add_argument("--seed", type=int, default=7)
_parser.add_argument("--bench", action="store_true",
                     help="uncapped FPS, phase-time, then exit")
_parser.add_argument("--duration", type=float, default=2.0)
_parser.add_argument("--warmup", type=float, default=0.5)
_parser.add_argument("--json", dest="json_path", default=None)
_args, _unknown = _parser.parse_known_args()

from scena import *  # noqa: E402
from scena.orchestration import ScenaFramework  # noqa: E402

WIDTH, HEIGHT = 1600, 1000
_init_kw = dict(width=WIDTH, height=HEIGHT, title="link stress (~200 shapes)")
if not _args.bench:
    _init_kw["window_scale"] = 0.7
init(**_init_kw)

canvas.background = (0.06, 0.07, 0.09, 1)
set_fx_auto(False)
set_defaults(line=None)

rng = random.Random(_args.seed)

# Global drivers for formula links (cheap to write once per frame).
st.create("t", initial=0.0)
st.create("pulse", initial=0.5)
st.create("spin", initial=0.0)

COLORS = [
    "crimson", "orange", "gold", "lime green", "turquoise", "cyan",
    "dodger blue", "orchid", "hot pink", "salmon", "khaki",
    "sea green", "sky blue", "violet", "tomato", "cornflower blue",
]


def _color(i: int):
    return COLORS[i % len(COLORS)]


def _jitter(scale: float = 18.0) -> float:
    return rng.uniform(-scale, scale)


# ---------------------------------------------------------------------------
# Layout: a grid of "cells". Each cell owns a free driver + several dependents.
# ~40 cells × ~5 shapes ≈ 200 drawable shapes (+ hub spokes).
# ---------------------------------------------------------------------------
# 6×4 cells ≈ 24 drivers × ~7 drawables + hub/polys/sibs → ~200 shapes
COLS, ROWS = 6, 4
CELL_W = WIDTH / (COLS + 0.5)
CELL_H = HEIGHT / (ROWS + 0.8)
MARGIN_X, MARGIN_Y = CELL_W * 0.55, CELL_H * 0.55

drivers = []          # free shapes we animate in update()
n_shapes = 0          # drawable count (approx)


def _count(shp):
    global n_shapes
    n_shapes += 1
    return shp


# ---- Hub (center) with spokes to every cell driver -------------------------
hub = Point(WIDTH * 0.5, HEIGHT * 0.5)
hub_marker = _count(Circle(center=lambda: hub, radius=8).set_color("white"))

cell_idx = 0
for row in range(ROWS):
    for col in range(COLS):
        cx = MARGIN_X + col * CELL_W + _jitter(10)
        cy = MARGIN_Y + row * CELL_H + _jitter(10)
        kind = cell_idx % 8
        cname = _color(cell_idx)

        # --- free driver (root of shallow links) ---
        if kind == 0:
            driver = _count(Rect(
                center=(cx, cy), width=42, height=28, angle=rng.uniform(0, 40),
            ).set_color(cname))
        elif kind == 1:
            driver = _count(Square(
                center=(cx, cy), length=36, angle=rng.uniform(0, 40),
            ).set_color(cname))
        elif kind == 2:
            driver = _count(Circle(
                center=(cx, cy), radius=22,
            ).set_color(cname))
        elif kind == 3:
            driver = _count(Ellipse(
                center=(cx, cy), width=50, height=28, angle=rng.uniform(0, 30),
            ).set_color(cname))
        elif kind == 4:
            driver = _count(RegularPolygon(
                n=5, center=(cx, cy), radius=24, angle=rng.uniform(0, 60),
            ).set_color(cname))
        elif kind == 5:
            driver = _count(RegularPolygon(
                n=6, center=(cx, cy), radius=22, angle=rng.uniform(0, 60),
            ).set_color(cname))
        elif kind == 6:
            driver = _count(Triangle(
                center=(cx, cy), side=40, angle=rng.uniform(0, 60),
            ).set_color(cname))
        else:
            driver = _count(Circle(
                center=(cx, cy), radius=18,
                angle=135.0, spread=270.0, use_center=True,
            ).set_color(cname))

        drivers.append({
            "shape": driver,
            "cx0": cx,
            "cy0": cy,
            "kind": kind,
            "orbit_r": rng.uniform(6, 18),
            "orbit_w": rng.uniform(0.4, 1.6) * rng.choice((-1, 1)),
            "spin_w": rng.uniform(20, 90) * rng.choice((-1, 1)),  # deg/s
            "scale_amp": rng.uniform(0.08, 0.22),
            "phase": rng.uniform(0, math.tau),
        })

        # Hub spoke — constructor link to driver's center (shallow).
        # Default-arg capture: `driver` is rebound every cell (loop late-bind).
        _ln = Line(p1=lambda: hub, p2=lambda d=driver: d.center)
        _ln.set_color("indigo")
        _ln.line_width = 1
        _ln.set_alpha(0.25)
        _count(_ln)

        # --- dependents (all depth-1 from this driver) --------------------
        # 1) Satellite circle whose center tracks a driver corner / vertex
        #    via constructor link, radius formula-linked to pulse.
        if hasattr(driver, "top_right"):
            sat_anchor = driver.top_right
        elif hasattr(driver, "points"):
            sat_anchor = driver.points[0]
        else:
            sat_anchor = driver.center

        sat = _count(Circle(
            center=lambda a=sat_anchor: a, radius=8,
        ).set_color("light " + cname))
        sat["radius"] @= (lambda base=10.0 + (cell_idx % 5), amp=4.0: base + amp * st.pulse)

        # 2) Connector line from driver center to satellite (constructor).
        _ln = Line(
            p1=lambda d=driver: d.center, p2=lambda s=sat: s.center,
        )
        _ln.set_color("gray")
        _ln.line_width = 1
        _ln.set_alpha(0.45)
        _count(_ln)

        # 3) Twin shape — pose linked shallowly via @= / constructor.
        ox, oy = cx + 55 + _jitter(8), cy + _jitter(12)
        if kind in (0, 1):
            twin = _count(Rect(
                center=(ox, oy), width=28, height=18,
            ).set_color("faded " + cname if " " not in cname else "gray"))
            # Angle DirectLink + size FormulaLink (depth 1).
            twin["angle"] @= (lambda d=driver: d.angle)
            twin["width"] @= (lambda d=driver, b=28: b + 6 * math.sin(float(st.t) + d.center.x * 0.01))
            # Ellipse that tracks the twin rect (constructor from_rect).
            _count(Ellipse(
                from_rect=twin, padding=4,
            ).set_color("sea green").set_alpha(0.35))
        elif kind in (2, 7):
            twin = _count(Circle(
                center=(ox, oy), radius=14,
            ).set_color("faded cyan"))
            twin["radius"] @= (lambda d=driver, b=14.0: b + 0.35 * d.radius)
            twin.center["x"] @= (lambda d=driver, o=ox - cx: d.center.x + o)
            twin.center["y"] @= (lambda d=driver, o=oy - cy: d.center.y + o)
            # Tangent line on the driver circle (constructor relational model).
            if kind == 2:
                tan = Line(
                    circle=driver, at_angle=0.0, length=50,
                ).set_color("magenta")
                tan.line_width = 1.5
                tan = _count(tan)
                tan["angle"] @= (lambda ph=drivers[-1]["phase"]: st.spin + math.degrees(ph))
        elif kind in (3,):
            twin = _count(Ellipse(
                center=(ox, oy), width=36, height=18,
            ).set_color("faded turquoise"))
            twin["angle"] @= (lambda d=driver: d.angle)
            twin["width"] @= (lambda d=driver: 30 + 0.4 * d.width)
            twin["height"] @= (lambda d=driver: 16 + 0.3 * d.height)
        else:
            # Regular poly / triangle: angle tracks driver; a parallel line.
            twin = _count(Square(
                center=(ox, oy), length=22,
            ).set_color("faded gold"))
            twin["angle"] @= (lambda d=driver: d.angle)
            twin["length"] @= (lambda: 18 + 8 * st.pulse)
            # Free reference edge on driver, then a parallel offset line.
            if hasattr(driver, "points") and len(driver.points) >= 2:
                edge = Line(
                    p1=lambda d=driver: d.points[0],
                    p2=lambda d=driver: d.points[1],
                )
                edge.set_color("white")
                edge.line_width = 1
                edge.set_alpha(0.5)
                _count(edge)
                par = Line(
                    dist=12, parallel_to=edge,
                ).set_color("gold")
                par.line_width = 1
                par.set_alpha(0.6)
                _count(par)

        # 4) Small marker at driver center (constructor center link).
        _count(Circle(
            center=driver.center, radius=3,
        ).set_color("white").set_alpha(0.8))

        cell_idx += 1

# Extra free-floating irregular polygons (~10) with one vertex @= a driver center.
for i in range(10):
    d = drivers[i * 3 % len(drivers)]["shape"]
    px = 80 + (i % 5) * 300 + _jitter(20)
    py = 80 + (i // 5) * 120 + _jitter(20)
    poly = _count(Polygon(
        points=[
            d.center,  # constructor link to driver center (shallow)
            (px + 40, py),
            (px + 55, py + 35),
            (px + 20, py + 50),
            (px - 10, py + 25),
        ],
    ).set_color(_color(i + 3)).set_alpha(0.55))

# A few cross-cell shallow links (still depth 1: shared driver → two dependents
# already exist; here we only add lines between sibling drivers' centers).
for i in range(0, len(drivers) - 1, 3):
    a = drivers[i]["shape"]
    b = drivers[i + 1]["shape"]
    _ln = Line(
        p1=lambda aa=a: aa.center, p2=lambda bb=b: bb.center,
    )
    _ln.set_color("steel blue")
    _ln.line_width = 1
    _ln.set_alpha(0.2)
    _count(_ln)

Text(
    text=f"link stress — ~{n_shapes} shapes, shallow @=/ctor links  |  ESC quit",
    top_left=(24, HEIGHT - 7), font_size=18, color=Color(0.85, 0.88, 0.92, 1),
)

print(f"[app_link_stress] drawable shapes ≈ {n_shapes}, drivers = {len(drivers)}")

# ---------------------------------------------------------------------------
# Animation + profiling
# ---------------------------------------------------------------------------
_prof = FrameProfiler.install() if _args.profile else None
_prof_t0 = None
_prof_started = False
_frame_times = []
_bench_start = None


def _finish_profile():
    if _prof is None:
        return
    n = max(len(_frame_times), 1)
    mean_dt = sum(_frame_times) / n
    fps = (1.0 / mean_dt) if mean_dt > 0 else 0.0
    print(f"\n[app_link_stress] mean FPS over {n} frames: {fps:.1f}  "
          f"(mean dt {mean_dt * 1000:.2f} ms)")
    _prof.report("app_link_stress — profile breakdown")
    FrameProfiler.uninstall()
    import glfw
    glfw.set_window_should_close(ScenaFramework.get_instance()._window, True)


def _update_body(dt):
    global _prof_t0, _prof_started, _bench_start

    if keyp.once("ESC"):
        import glfw
        glfw.set_window_should_close(ScenaFramework.get_instance()._window, True)
        return

    st.t = float(st.t) + dt
    st.pulse = 0.5 + 0.5 * math.sin(float(st.t) * 1.7)
    st.spin = (float(st.spin) + 55.0 * dt) % 360.0

    t = float(st.t)
    for d in drivers:
        shp = d["shape"]
        # Orbit the free center (move) — shallow root write.
        ox = d["cx0"] + d["orbit_r"] * math.cos(t * d["orbit_w"] + d["phase"])
        oy = d["cy0"] + d["orbit_r"] * math.sin(t * d["orbit_w"] + d["phase"])
        shp.move_to(ox, oy)

        # Rotate when the model has an angle Defining part.
        if d["kind"] not in (2, 7):
            shp.rotate_by(d["spin_w"] * dt)
        elif d["kind"] == 7:
            shp.angle = shp.angle + d["spin_w"] * dt

        # Scale pulse on size-like Defining parts (radius / length / width).
        amp = d["scale_amp"]
        factor = 1.0 + amp * math.sin(t * 2.1 + d["phase"])
        kind = d["kind"]
        if kind in (2, 4, 5, 7):  # circle / regular poly radius / arc
            base = d.get("_base_r")
            if base is None:
                d["_base_r"] = shp.radius
                base = d["_base_r"]
            shp.radius = base * factor
        elif kind == 1:  # square length
            base = d.get("_base_len")
            if base is None:
                d["_base_len"] = shp.length
                base = d["_base_len"]
            shp.length = base * factor
        elif kind in (0, 3):  # rect / ellipse wh
            bw = d.get("_base_w")
            if bw is None:
                d["_base_w"] = shp.width
                d["_base_h"] = shp.height
                bw = d["_base_w"]
            shp.width = bw * factor
            shp.height = d["_base_h"] * factor
        elif kind == 6:  # equilateral triangle side
            base = d.get("_base_side")
            if base is None:
                d["_base_side"] = shp.side
                base = d["_base_side"]
            shp.side = base * factor

    if _prof is not None:
        if not _prof_started:
            if _prof_t0 is None:
                _prof_t0 = time.perf_counter()
            elif time.perf_counter() - _prof_t0 >= 0.5:
                _prof.start_recording()
                _prof_started = True
                _bench_start = time.perf_counter()
                _prof_t0 = _bench_start
        else:
            _frame_times.append(dt)
            secs = _args.profile_seconds if _args.profile_seconds is not None else 5.0
            if time.perf_counter() - _bench_start >= secs:
                _finish_profile()


update = _prof.wrap_update(_update_body) if _prof is not None else _update_body

canvas.framerate = "max"

if _args.bench:
    from perf_common import (  # noqa: E402
        average_phase_stats,
        empty_phase_stats,
        install_phase_run,
        print_phase_report,
        write_json,
    )
    fw = ScenaFramework.get_instance()
    stats = empty_phase_stats()
    install_phase_run(
        fw,
        duration=_args.duration,
        warmup=_args.warmup,
        stats=stats,
    )
    run()
    print_phase_report("reactive_graph (shallow links) — phase timing", stats)
    avg = average_phase_stats(stats)
    payload = {
        "ok": True,
        "probe": "reactive_graph",
        "n_shapes": n_shapes,
        "fps": avg["fps"],
        "work_ms": avg["work_ms"],
        "tick_ms": avg["tick_ms"],
        "flush_ms": avg["flush_ms"],
        "draw_ms": avg["draw_ms"],
        "frames": avg["frames"],
    }
    print("RESULT_JSON: " + json.dumps(payload))
    if _args.json_path:
        payload["phases"] = avg
        write_json(_args.json_path, payload)
else:
    run()
