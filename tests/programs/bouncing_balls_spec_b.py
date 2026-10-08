"""Spec B for tests/programs/bouncing_balls.py, written from the docs alone.

Arena (from the program): W=1000, H=720; walls 32 DU thick, so the inner
faces are x=32, x=968, y=32, y=688. The spinning bar `roda` is a 100 x 20 Rect
at (500, 360), STATIC, turned by 50 deg/s in update(). Balls exist only after
the Start button runs start().
"""
from program_support import (Scenario, Expect, wait, wait_s, click_widget, click,
    key, key_down, key_up, move, scroll, set_cell, always, never, at, at_end,
    eventually, steady, all_of, custom, close)
import math

FILES_READ = [
    "tests/programs/bouncing_balls.py",
    "design/Scena Design.md#frame-order",
    "design/Scena Design.md#collision",
    "design/Collision Design.md#resolution",
    "design/Collision Design.md#movability-mass-and-static",
    "design/Collision Design.md#standing-resolve-resolve--unresolve",
    "design/Collision Design.md#motion-vs-placement",
    "design/Collision Design.md#velocity-bounce-none-or-restitution",
    "design/Collision Design.md#resting-contact-skin",
    "design/Collision Design.md#swept-detection-fast-bodies",
    "design/Collision Design.md#spin-not-swept",
    "docs/pt/guide/index.html#script-minimo",
    "docs/pt/guide/index.html#init",
    "docs/pt/guide/index.html#regras",
    "docs/pt/guide/index.html#unidades",
    "docs/pt/guide/index.html#globais",
    "docs/pt/guide/index.html#comecar-callbacks",
    "docs/pt/guide/index.html#mundo-camera",
    "docs/pt/guide/index.html#mundo-grupos",
    "docs/pt/guide/index.html#frame-clock",
    "docs/pt/guide/index.html#pose-move-by",
    "docs/pt/guide/index.html#pose-rotate-by",
    "docs/pt/guide/index.html#geo-vec2",
    "docs/pt/guide/index.html#ui-widgets",
    "docs/pt/guide/index.html#ui-stack",
    "docs/pt/guide/index.html#ui-button",
    "docs/pt/guide/index.html#ui-slider",
    "docs/pt/guide/index.html (Callbacks do script table, ~line 8630)",
]

W, H = 1000.0, 720.0
WALL = 32.0
DT = 1.0 / 60.0
RODA_C = (500.0, 360.0)
RODA_HALF = (50.0, 10.0)

# ---------------------------------------------------------------- probes


def _balls(p):
    out = []
    for b in p.group["ball"]:
        out.append((float(b.center.x), float(b.center.y),
                    float(b.vel.x), float(b.vel.y), float(b.radius)))
    return tuple(out)


PROBES = {
    "n_balls": lambda p: len(p.group["ball"]),
    "balls": _balls,
    "ball_mass": lambda p: tuple(float(b.mass) for b in p.group["ball"]),
    "n_walls": lambda p: len(p.group["wall"]),
    "walls": lambda p: tuple((float(w.center.x), float(w.center.y))
                             for w in p.group["wall"]),
    "wall_mass": lambda p: tuple(float(w.mass) for w in p.group["wall"]),
    "roda_center": lambda p: (float(p.roda.center.x), float(p.roda.center.y)),
    "roda_angle": lambda p: float(p.roda.angle),
    "roda_in_wall": lambda p: p.roda.tagged("wall"),
    "count": lambda p: p.st.count,
    "size": lambda p: p.st.size,
    "zoom": lambda p: float(p.canvas.zoom),
    "pan": lambda p: (float(p.canvas.pan_x), float(p.canvas.pan_y)),
    "clock_time": lambda p: float(p.clock.time),
}

# ---------------------------------------------------------------- scenarios

SCENARIOS = {
    # nothing pressed
    "idle": Scenario(params={}, seed=0, steps=[wait(300)]),
    # default 30 balls of radius 12
    "start": Scenario(params={}, seed=1, steps=[
        wait(10), click_widget("Start"), wait(400)]),
    # one ball: its speed is an exact invariant (only STATIC partners)
    "one_ball": Scenario(params={"count": 1}, seed=2, steps=[
        wait(5), click_widget("Start"), wait(500)]),
    # Start twice: old balls destroyed, not added to
    "restart": Scenario(params={}, seed=3, steps=[
        wait(5), click_widget("Start"), wait(60), click_widget("Start"), wait(60)]),
    # cells written between frames (what dragging the sliders does)
    "cells": Scenario(params={}, seed=4, steps=[
        set_cell("st.count", 5), set_cell("st.size", 20), wait(2),
        click_widget("Start"), wait(240)]),
    # PARAMS reach the program
    "params": Scenario(params={"count": 10, "size": 6}, seed=5, steps=[
        wait(3), click_widget("Start"), wait(240)]),
    # slider maximum
    "max_balls": Scenario(params={}, seed=6, steps=[
        set_cell("st.count", 80), wait(1), click_widget("Start"), wait(180)]),
    # mouse wheel over an empty part of the arena (no widget, no shape)
    "scroll": Scenario(params={}, seed=0, steps=[
        move(700, 150), wait(2), scroll(1), wait(3), scroll(-1), wait(3),
        scroll(-1), wait(3)]),
    # zoom first, then Start: widgets ignore the camera
    "zoomed_start": Scenario(params={}, seed=7, steps=[
        move(700, 150), wait(1), scroll(1), scroll(1), wait(2),
        click_widget("Start"), wait(60)]),
}

STARTED = ("start", "one_ball", "cells", "params", "max_balls", "zoomed_start")
ALL = ("*",)

# ---------------------------------------------------------------- helpers


def _first_frame_with_balls(t):
    for f, _tm, v in t.series("n_balls"):
        if v and v > 0:
            return f
    return None


def _check_inside(slop):
    def fn(t):
        for f, _tm, balls in t.series("balls"):
            for (x, y, _vx, _vy, r) in balls:
                if not (WALL + r - slop <= x <= W - WALL - r + slop and
                        WALL + r - slop <= y <= H - WALL - r + slop):
                    return "frame %d: ball (%.2f, %.2f) r=%.1f outside the walls" % (f, x, y, r)
        return True
    return fn


def _ke(balls):
    return sum(vx * vx + vy * vy for (_x, _y, vx, vy, _r) in balls)


def _check_ke_conserved(rel):
    def fn(t):
        f0 = _first_frame_with_balls(t)
        if f0 is None:
            return "no balls ever appeared"
        k0 = _ke(t.at_frame(f0, "balls"))
        for f, _tm, balls in t.series("balls"):
            if f < f0:
                continue
            k = _ke(balls)
            if abs(k - k0) > rel * k0:
                return "frame %d: sum |v|^2 = %.3f, was %.3f at frame %d" % (f, k, k0, f0)
        return True
    return fn


def _check_mean_speed_range(t):
    f0 = _first_frame_with_balls(t)
    if f0 is None:
        return "no balls ever appeared"
    balls = t.at_frame(f0, "balls")
    ms = _ke(balls) / len(balls)
    if not (180.0 ** 2 - 1e-6 <= ms <= 340.0 ** 2 + 1e-6):
        return "mean |v|^2 %.1f outside [180^2, 340^2]" % ms
    return True


def _check_no_ball_overlap(slop, settle_frames):
    def fn(t):
        f0 = _first_frame_with_balls(t)
        if f0 is None:
            return "no balls ever appeared"
        for f, _tm, balls in t.series("balls"):
            if f < f0 + settle_frames:
                continue
            n = len(balls)
            for i in range(n):
                xi, yi, _a, _b, ri = balls[i]
                for j in range(i + 1, n):
                    xj, yj, _c, _d, rj = balls[j]
                    d = math.hypot(xi - xj, yi - yj)
                    if d < ri + rj - slop:
                        return "frame %d: balls %d,%d overlap by %.2f DU" % (f, i, j, ri + rj - d)
        return True
    return fn


def _roda_signed_dist(x, y, angle_deg):
    a = math.radians(-angle_deg)
    dx, dy = x - RODA_C[0], y - RODA_C[1]
    lx = dx * math.cos(a) - dy * math.sin(a)
    ly = dx * math.sin(a) + dy * math.cos(a)
    ex, ey = abs(lx) - RODA_HALF[0], abs(ly) - RODA_HALF[1]
    if ex <= 0 and ey <= 0:
        return max(ex, ey)          # inside: negative
    return math.hypot(max(ex, 0.0), max(ey, 0.0))


def _check_no_roda_overlap(slop, settle_frames):
    def fn(t):
        f0 = _first_frame_with_balls(t)
        if f0 is None:
            return "no balls ever appeared"
        for f, _tm, balls in t.series("balls"):
            if f < f0 + settle_frames:
                continue
            ang = t.at_frame(f, "roda_angle")
            for (x, y, _vx, _vy, r) in balls:
                d = _roda_signed_dist(x, y, ang)
                if d < r - slop:
                    return "frame %d: ball (%.1f, %.1f) is %.2f DU into the bar" % (f, x, y, r - d)
        return True
    return fn


def _check_roda_angle(t):
    for f, _tm, ang in t.series("roda_angle"):
        want = (50.0 * f * DT) % 360.0
        diff = abs(((ang - want) + 180.0) % 360.0 - 180.0)
        if diff > 1e-6:
            return "frame %d: roda.angle %.6f, expected %.6f (mod 360)" % (f, ang, want)
    return True


def _check_clock(t):
    for s in t.samples:
        if abs(s.time - s.frame * DT) > 1e-6:
            return "frame %d: clock.time %.6f, expected %.6f" % (s.frame, s.time, s.frame * DT)
    return True


def _press_release(t):
    pf = t.input_frame("button", 0)
    if pf is None:
        return None, None
    rf = t.input_frame("button", 1)
    if rf is None:
        rf = pf + 1
    return pf, rf


def _check_balls_appear_on_click(n_expected):
    def fn(t):
        pf, rf = _press_release(t)
        if pf is None:
            return "no button input delivered"
        if pf > 1 and t.at_frame(pf - 1, "n_balls") != 0:
            return "balls existed before the Start press"
        if t.at_frame(rf, "n_balls") != n_expected:
            return "frame %d (release): %r balls, expected %d" % (rf, t.at_frame(rf, "n_balls"), n_expected)
        return True
    return fn


def _check_fires_on_release(t):
    pf, rf = _press_release(t)
    if pf is None:
        return "no button input delivered"
    if pf == rf:
        return True
    if t.at_frame(pf, "n_balls") != 0:
        return "balls appeared on the press frame %d, before release" % pf
    return True


def _check_spawn_box(slack):
    def fn(t):
        f0 = _first_frame_with_balls(t)
        if f0 is None:
            return "no balls ever appeared"
        for (x, y, _vx, _vy, _r) in t.at_frame(f0, "balls"):
            if not (80 - slack <= x <= W - 80 + slack and 200 - slack <= y <= H - 80 + slack):
                return "ball spawned at (%.1f, %.1f), outside the uniform box" % (x, y)
        return True
    return fn


def _check_one_ball_speed(t):
    f0 = _first_frame_with_balls(t)
    if f0 is None:
        return "no ball appeared"
    b0 = t.at_frame(f0, "balls")[0]
    s0 = math.hypot(b0[2], b0[3])
    if not (180.0 - 1e-6 <= s0 <= 340.0 + 1e-6):
        return "initial speed %.3f outside [180, 340]" % s0
    for f, _tm, balls in t.series("balls"):
        if f < f0:
            continue
        s = math.hypot(balls[0][2], balls[0][3])
        if abs(s - s0) > 1e-6 * s0:
            return "frame %d: speed %.6f, was %.6f" % (f, s, s0)
    return True


def _check_free_flight(t):
    """Between consecutive frames, a ball far from every partner moves by vel*dt."""
    ser = t.series("balls")
    for k in range(1, len(ser)):
        f, _tm, balls = ser[k]
        fp, _tp, prev = ser[k - 1]
        if len(balls) != 1 or len(prev) != 1 or f != fp + 1:
            continue
        x0, y0, vx0, vy0, r = prev[0]
        x1, y1, vx1, vy1, _ = balls[0]
        if (vx0, vy0) != (vx1, vy1):
            continue
        clear = 8.0
        far_walls = all(WALL + r + clear <= x <= W - WALL - r - clear and
                        WALL + r + clear <= y <= H - WALL - r - clear
                        for (x, y) in ((x0, y0), (x1, y1)))
        far_bar = all(math.hypot(x - RODA_C[0], y - RODA_C[1]) > 51.0 + r + clear
                      for (x, y) in ((x0, y0), (x1, y1)))
        if not (far_walls and far_bar):
            continue
        if abs((x1 - x0) - vx1 * DT) > 1e-6 or abs((y1 - y0) - vy1 * DT) > 1e-6:
            return "frame %d: moved (%.5f, %.5f), vel*dt = (%.5f, %.5f)" % (
                f, x1 - x0, y1 - y0, vx1 * DT, vy1 * DT)
    return True


def _check_count_constant_after_start(n_expected):
    def fn(t):
        f0 = _first_frame_with_balls(t)
        if f0 is None:
            return "no balls ever appeared"
        for f, _tm, n in t.series("n_balls"):
            if f >= f0 and n != n_expected:
                return "frame %d: %r balls, expected %d" % (f, n, n_expected)
        return True
    return fn


def _check_radius(r_expected):
    def fn(t):
        for f, _tm, balls in t.series("balls"):
            for b in balls:
                if abs(b[4] - r_expected) > 1e-9:
                    return "frame %d: radius %.3f, expected %.3f" % (f, b[4], r_expected)
        return True
    return fn


def _check_restart(t):
    pf0 = t.input_frame("button", 0)
    if pf0 is None:
        return "no button input"
    # the second click is the 3rd/4th button event (press, release, press, release)
    pf1 = t.input_frame("button", 2)
    if pf1 is None:
        return "second Start click not delivered"
    for f, _tm, n in t.series("n_balls"):
        if f >= pf1 - 1 and n not in (30,):
            return "frame %d: %r balls after a restart, expected 30" % (f, n)
    return True


def _check_scroll_zoom(t):
    want = [1.1, 1.0, 1.0 / 1.1]
    for i, z in enumerate(want):
        f = t.input_frame("scroll", i)
        if f is None:
            return "scroll %d not delivered" % i
        got = t.at_frame(f, "zoom")
        if abs(got - z) > 1e-9:
            return "after scroll %d (frame %d): zoom %.9f, expected %.9f" % (i, f, got, z)
    f0 = t.input_frame("scroll", 0)
    for f, _tm, z in t.series("zoom"):
        if f < f0 and abs(z - 1.0) > 1e-12:
            return "frame %d: zoom %.6f before any scroll" % (f, z)
    return True


def _check_pan_unchanged_by_zoom(t):
    vals = t.values("pan")
    if not vals:
        return "no samples"
    p0 = vals[0]
    for f, _tm, p in t.series("pan"):
        if abs(p[0] - p0[0]) > 1e-6 or abs(p[1] - p0[1]) > 1e-6:
            return "frame %d: pan moved to %r from %r" % (f, p, p0)
    return True


# ---------------------------------------------------------------- expectations

EXPECT = [
    # ---- startup / L0
    Expect(id="E1", level="L0", cite="docs/pt/guide/index.html#comecar-callbacks",
           text="start() is not a script callback (only setup/update/on_* are); "
                "with nothing pressed no ball ever exists.",
           check=always("n_balls", lambda n: n == 0), scenarios=("idle", "scroll")),
    Expect(id="E2", level="L0", cite="docs/pt/guide/index.html#mundo-grupos",
           text="group['wall'] holds the 4 walls plus roda (tagged group='wall'): 5 members, always.",
           check=always("n_walls", lambda n: n == 5), scenarios=ALL),
    Expect(id="E3", level="L0", cite="design/Collision Design.md#movability-mass-and-static",
           text="Every wall and roda has mass STATIC = inf (group write + roda.mass).",
           check=always("wall_mass", lambda ms: len(ms) == 5 and all(math.isinf(m) for m in ms)),
           scenarios=("idle", "start")),
    Expect(id="E4", level="L0", cite="docs/pt/guide/index.html#reativo-state",
           text="With no PARAMS st.count == 30 and st.size == 12 and Start does not change them.",
           check=all_of(always("count", lambda v: v == 30), always("size", lambda v: v == 12)),
           scenarios=("idle", "start", "restart", "scroll")),
    Expect(id="E5", level="L0", cite="tests/programs harness PARAMS + docs/pt/guide/index.html#reativo-state",
           text="PARAMS count=10, size=6 reach st.count / st.size from frame 1.",
           check=all_of(always("count", lambda v: v == 10), always("size", lambda v: v == 6)),
           scenarios=("params",)),
    Expect(id="E6", level="L0", cite="docs/pt/guide/index.html#mundo-grupos",
           text="roda carries the 'wall' tag.",
           check=always("roda_in_wall", lambda v: bool(v)), scenarios=("idle",)),

    # ---- Start button
    Expect(id="E7", level="L0", cite="docs/pt/guide/index.html#ui-button",
           text="Clicking Start creates exactly st.count (30) balls; none exist before the press.",
           check=custom(_check_balls_appear_on_click(30)), scenarios=("start",)),
    Expect(id="E8", level="L0", cite="docs/pt/guide/index.html#ui-button (SpriteButton: 'clica ao soltar'; Button is silent)",
           text="Assumed: Button.on_click fires on release, like SpriteButton and shape clicks; "
                "no balls on the press frame.",
           check=custom(_check_fires_on_release), scenarios=("start", "one_ball"), guess=True),
    Expect(id="E9", level="L0", cite="docs/pt/guide/index.html#mundo-grupos",
           text="After Start the ball count stays constant (collisions never destroy).",
           check=custom(_check_count_constant_after_start(30)), scenarios=("start",)),
    Expect(id="E10", level="L0", cite="docs/pt/guide/index.html#mundo-grupos (group.destroy)",
           text="A second Start destroys the old balls first: the group holds 30, never 60.",
           check=custom(_check_restart), scenarios=("restart",)),
    Expect(id="E11", level="L0", cite="docs/pt/guide/index.html#ui-widgets (cell two-way)",
           text="Writing st.count=5, st.size=20 (what the sliders write) then Start makes 5 balls of radius 20.",
           check=all_of(custom(_check_count_constant_after_start(5)), custom(_check_radius(20.0))),
           scenarios=("cells",)),
    Expect(id="E12", level="L0", cite="docs/pt/guide/index.html#ui-slider",
           text="PARAMS count=10, size=6: Start makes 10 balls of radius 6.",
           check=all_of(custom(_check_count_constant_after_start(10)), custom(_check_radius(6.0))),
           scenarios=("params",)),
    Expect(id="E13", level="L0", cite="docs/pt/guide/index.html#ui-slider",
           text="st.count at the slider maximum (80) gives 80 balls.",
           check=custom(_check_count_constant_after_start(80)), scenarios=("max_balls",)),
    Expect(id="E14", level="L0", cite="docs/pt/guide/index.html#regras (widgets ignore the camera)",
           text="After zooming, click_widget('Start') still hits the button: 30 balls.",
           check=custom(_check_count_constant_after_start(30)), scenarios=("zoomed_start",)),
    Expect(id="E15", level="L0", cite="docs/pt/guide/index.html#reativo-state",
           text="Default radius is st.size = 12 for every ball.",
           check=custom(_check_radius(12.0)), scenarios=("start", "restart", "zoomed_start")),
    Expect(id="E16", level="L0", cite="design/Collision Design.md#movability-mass-and-static",
           text="Every ball has mass 1.0 (finite; resolve may move it).",
           check=always("ball_mass", lambda ms: all(m == 1.0 for m in ms)), scenarios=("start",)),

    # ---- clock and roda / L1
    Expect(id="E17", level="L1", cite="docs/pt/guide/index.html#frame-clock",
           text="clock.time after frame n is n/60 (fixed dt, not paused), tol 1e-6.",
           check=custom(_check_clock), scenarios=ALL),
    Expect(id="E18", level="L1", cite="docs/pt/guide/index.html#pose-rotate-by",
           text="roda.angle after frame n is 50*n/60 deg (counter-clockwise), compared mod 360, tol 1e-6.",
           check=custom(_check_roda_angle), scenarios=("idle", "start")),
    Expect(id="E19", level="L1", cite="design/Collision Design.md#movability-mass-and-static",
           text="roda is STATIC and spins about its own centre: its centre stays (500, 360), tol 1e-9.",
           check=always("roda_center", lambda c: close(c, RODA_C, 1e-9)),
           scenarios=("idle", "start", "max_balls")),
    Expect(id="E20", level="L1", cite="design/Collision Design.md#movability-mass-and-static",
           text="No wall moves, even under 80 balls (STATIC = infinite mass).",
           check=steady("walls", tol=1e-9), scenarios=("start", "max_balls")),
    Expect(id="E21", level="L1", cite="docs/pt/guide/index.html#pose-move-by",
           text="A single ball away from every partner moves exactly vel*dt per frame (move_by in update).",
           check=custom(_check_free_flight), scenarios=("one_ball",)),

    # ---- camera / L1
    Expect(id="E22", level="L1", cite="docs/pt/guide/index.html#mundo-camera (zoom_by multiplies)",
           text="Wheel up multiplies canvas.zoom by 1.1 on the delivery frame, wheel down divides: 1.1, 1.0, 1/1.1; tol 1e-9.",
           check=custom(_check_scroll_zoom), scenarios=("scroll",)),
    Expect(id="E23", level="L0", cite="docs/pt/guide/index.html#mundo-camera",
           text="With no scroll the camera stays at zoom 1.",
           check=always("zoom", lambda z: abs(z - 1.0) < 1e-12), scenarios=("idle", "start")),
    Expect(id="E24", level="L1", cite="docs/pt/guide/index.html#mundo-camera ('Três movimentos': zoom uses pan only with about=)",
           text="zoom_by without about= is the zoom movement only: pan_x / pan_y never change.",
           check=custom(_check_pan_unchanged_by_zoom), scenarios=("scroll", "zoomed_start")),
    Expect(id="E25", level="L0", cite="docs/pt/guide/index.html#mundo-camera ('ela não move os objetos')",
           text="Zooming moves no object: walls and roda centre unchanged.",
           check=all_of(steady("walls", tol=1e-9), always("roda_center", lambda c: close(c, RODA_C, 1e-9))),
           scenarios=("scroll",)),

    # ---- physics / L2
    Expect(id="E26", level="L2", cite="design/Collision Design.md#standing-resolve-resolve--unresolve",
           text="Every ball centre stays inside the inner wall faces minus its radius; slop 2 DU "
                "(resolve skin 0.08 DU plus settle under crowding).",
           check=custom(_check_inside(2.0)),
           scenarios=("start", "one_ball", "restart", "cells", "params", "max_balls", "zoomed_start")),
    Expect(id="E27", level="L2", cite="design/Collision Design.md#velocity-bounce-none-or-restitution",
           text="One ball against STATIC partners with bounce=1: its speed never changes (rel 1e-6) and starts in [180, 340].",
           check=custom(_check_one_ball_speed), scenarios=("one_ball",)),
    Expect(id="E28", level="L2", cite="design/Collision Design.md#velocity-bounce-none-or-restitution",
           text="bounce=1 impulses are momentum-conserving with no energy loss and settle never writes .vel: "
                "sum of |v|^2 over the balls is constant after Start, rel tol 1e-4.",
           check=custom(_check_ke_conserved(1e-4)),
           scenarios=("start", "one_ball", "cells", "params", "max_balls")),
    Expect(id="E29", level="L2", cite="program uniform(180, 340) + design/Collision Design.md#velocity-bounce-none-or-restitution",
           text="Mean |v|^2 on the first ball frame lies in [180^2, 340^2] (each spawn speed is in [180, 340]).",
           check=custom(_check_mean_speed_range), scenarios=STARTED),
    Expect(id="E30", level="L2", cite="design/Collision Design.md#standing-resolve-resolve--unresolve (bounded settle)",
           text="Balls may spawn overlapping; from 30 frames after Start no two balls overlap by more than 3 DU "
                "(settle recovers spawn overlap at up to 8 DU per iteration; sweep stops new contacts).",
           check=custom(_check_no_ball_overlap(3.0, 30)), scenarios=("start", "cells", "params")),
    Expect(id="E31", level="L2", cite="design/Collision Design.md#spin-not-swept",
           text="From 30 frames after Start no ball sits more than 3 DU inside the spinning bar "
                "(spin is not swept, tip travel 0.7 DU/frame, settle separates the same frame).",
           check=custom(_check_no_roda_overlap(3.0, 30)), scenarios=("start", "one_ball", "max_balls")),
    Expect(id="E32", level="L2", cite="program uniform box + design/Collision Design.md#standing-resolve-resolve--unresolve",
           text="On the frame balls appear they are inside the spawn box x in [80, 920], y in [200, 640], "
                "widened by 16 DU (one frame of motion <= 5.7 DU plus one settle step <= 8 DU).",
           check=custom(_check_spawn_box(16.0)), scenarios=STARTED),
    Expect(id="E33", level="L2", cite="design/Collision Design.md#swept-detection-fast-bodies",
           text="No tunnelling: at 340 DU/s a ball travels 5.7 DU/frame < its 24 DU diameter, so the 80-ball "
                "pile stays inside the walls (slop 2 DU) for the whole run.",
           check=custom(_check_inside(2.0)), scenarios=("max_balls",)),
]
