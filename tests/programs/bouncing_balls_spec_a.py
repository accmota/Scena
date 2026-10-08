"""Spec A for tests/programs/bouncing_balls.py, written from the docs only.

Frozen before the engine ran. Each Expect cites the passage it rests on;
guess=True marks a claim the docs do not settle.
"""
from program_support import (Scenario, Expect, wait, wait_s, click_widget, click,
    key, key_down, key_up, move, scroll, set_cell, always, never, at, at_end,
    eventually, steady, all_of, custom, close)
import math

FILES_READ = [
    "tests/programs/bouncing_balls.py",
    "design/Scena Design.md#frame-order",
    "design/Scena Design.md#collision",
    "design/Collision Design.md#velocity-bounce-none-or-restitution",
    "docs/pt/guide/index.html#globais",
    "docs/pt/guide/index.html#reagir-callbacks",
    "docs/pt/guide/index.html#colisao-resolve",
    "docs/pt/guide/index.html#ui-widgets",
    "docs/pt/guide/index.html#ui-button",
    "docs/pt/guide/index.html#ui-slider",
    "docs/pt/guide/index.html#mundo-grupos",
    "docs/pt/guide/index.html#mundo-camera",
    "docs/pt/guide/index.html#mover-pose",
    "docs/pt/guide/index.html#suite-about",
    "docs/pt/guide/index.html#desenhar-drawable",
    "docs/pt/guide/index.html#desenhar-shapes",
    "docs/pt/guide/index.html#geo-vec2",
    "examples/cadeia_de_bolas.py",
]

W, H = 1000.0, 720.0
WALL = 32.0          # wall thickness: inner faces at 32 and W-32 / H-32
DT = 1.0 / 60.0
INF = float("inf")


# ---------------------------------------------------------------- probes

def _centers(p):
    return tuple((float(b.center.x), float(b.center.y)) for b in p.group["ball"])


def _vels(p):
    return tuple((float(b.vel.x), float(b.vel.y)) for b in p.group["ball"])


PROBES = {
    "n_balls": lambda p: len(p.group["ball"]),
    "n_walls": lambda p: len(p.group["wall"]),
    "roda_is_wall": lambda p: bool(p.roda.tagged("wall")),
    "centers": _centers,
    "vels": _vels,
    "radii": lambda p: tuple(float(b.radius) for b in p.group["ball"]),
    "ball_masses": lambda p: tuple(float(b.mass) for b in p.group["ball"]),
    "balls_alive": lambda p: all(b.is_alive for b in p.group["ball"]),
    "wall_masses": lambda p: tuple(float(w.mass) for w in p.group["wall"]),
    "roda_angle": lambda p: float(p.roda.angle),
    "roda_center": lambda p: (float(p.roda.center.x), float(p.roda.center.y)),
    "st_count": lambda p: p.st.count,
    "st_size": lambda p: p.st.size,
    "zoom": lambda p: float(p.canvas.zoom),
    "pan": lambda p: (float(p.canvas.pan_x), float(p.canvas.pan_y)),
    "time": lambda p: float(p.clock.time),
}


# ---------------------------------------------------------------- scenarios

SCENARIOS = {
    # nothing pressed
    "idle": Scenario(params={}, seed=0, steps=[wait(120)]),
    # one Start with defaults (30 balls, r=12)
    "start": Scenario(params={}, seed=1, steps=[wait(5), click_widget("Start"), wait(300)]),
    # Start twice: the second replaces the first set
    "restart": Scenario(params={}, seed=2, steps=[
        wait(5), click_widget("Start"), wait(60), click_widget("Start"), wait(60)]),
    # cells written between frames, then Start
    "cells": Scenario(params={}, seed=3, steps=[
        set_cell("st.count", 5), set_cell("st.size", 20), wait(10),
        click_widget("Start"), wait(120)]),
    # PARAMS reach the program
    "params": Scenario(params={"count": 8, "size": 30}, seed=4, steps=[
        wait(2), click_widget("Start"), wait(240)]),
    # denser arena
    "crowd": Scenario(params={"count": 60, "size": 20}, seed=5, steps=[
        wait(2), click_widget("Start"), wait(240)]),
    # mouse wheel zoom (pointer away from widgets, balls and the bar)
    "zoom": Scenario(params={}, seed=6, steps=[
        move(700, 150), wait(2), scroll(1), wait(5), scroll(1), wait(5),
        scroll(-1), wait(5)]),
    # a click on the "Balls" slider, then Start
    "slider": Scenario(params={}, seed=7, steps=[
        wait(2), click_widget("Balls"), wait(3), click_widget("Start"), wait(30)]),
}

SPAWN_SCENARIOS = ("start", "restart", "cells", "params", "crowd", "slider")


# ---------------------------------------------------------------- helpers

def _button_frames(t):
    """Frames of every 'button' input, in order."""
    out = []
    for n in range(32):
        try:
            f = t.input_frame("button", nth=n)
        except Exception:
            break
        if f is None:
            break
        out.append(f)
    return out


def last_release(t):
    """Frame of the last button input (the release of the last click_widget)."""
    fr = _button_frames(t)
    return fr[-1] if fr else 10 ** 9


def first_press(t):
    fr = _button_frames(t)
    return fr[0] if fr else 10 ** 9


def _frames_from(t, probe, start):
    return [(f, v) for (f, _tm, v) in t.series(probe) if f >= start]


def _ang_diff(a, b):
    d = (a - b) % 360.0
    return min(d, 360.0 - d)


def _check_walls(slop_frac):
    def fn(t):
        start = last_release(t) + 1
        for (f, cs), (_f2, rs) in zip(_frames_from(t, "centers", start),
                                     _frames_from(t, "radii", start)):
            for (x, y), r in zip(cs, rs):
                s = slop_frac * r
                if x - r < WALL - s or x + r > W - WALL + s or y - r < WALL - s or y + r > H - WALL + s:
                    return "frame %d: ball (%.2f, %.2f) r=%.1f pokes into a wall" % (f, x, y, r)
        return True
    return fn


def _check_inside_arena(t):
    for f, cs in _frames_from(t, "centers", 0):
        for x, y in cs:
            if not (WALL < x < W - WALL and WALL < y < H - WALL):
                return "frame %d: ball centre (%.2f, %.2f) left the arena" % (f, x, y)
    return True


def _check_ball_overlap(slop_frac, settle=3):
    def fn(t):
        start = last_release(t) + settle
        for (f, cs), (_f2, rs) in zip(_frames_from(t, "centers", start),
                                     _frames_from(t, "radii", start)):
            n = len(cs)
            for i in range(n):
                xi, yi = cs[i]
                for j in range(i + 1, n):
                    xj, yj = cs[j]
                    need = rs[i] + rs[j]
                    d = math.hypot(xi - xj, yi - yj)
                    if d < need - slop_frac * min(rs[i], rs[j]):
                        return "frame %d: balls %d,%d overlap by %.2f" % (f, i, j, need - d)
        return True
    return fn


def _roda_penetration(c, r, rc, ang_deg):
    a = math.radians(-ang_deg)
    dx, dy = c[0] - rc[0], c[1] - rc[1]
    lx = dx * math.cos(a) - dy * math.sin(a)
    ly = dx * math.sin(a) + dy * math.cos(a)
    hx, hy = 50.0, 10.0
    ox, oy = abs(lx) - hx, abs(ly) - hy
    if ox <= 0 and oy <= 0:            # centre inside the bar
        return r + min(-ox, -oy)
    dist = math.hypot(max(ox, 0.0), max(oy, 0.0))
    return r - dist


def _check_roda_overlap(slop_frac, settle=3):
    def fn(t):
        start = last_release(t) + settle
        cs_s = _frames_from(t, "centers", start)
        rs_s = _frames_from(t, "radii", start)
        an_s = _frames_from(t, "roda_angle", start)
        rc_s = _frames_from(t, "roda_center", start)
        for (f, cs), (_a, rs), (_b, ang), (_c, rc) in zip(cs_s, rs_s, an_s, rc_s):
            for (x, y), r in zip(cs, rs):
                pen = _roda_penetration((x, y), r, rc, ang)
                if pen > slop_frac * r:
                    return "frame %d: ball (%.1f, %.1f) is %.2f inside the bar" % (f, x, y, pen)
        return True
    return fn


def _ke(vs):
    return sum(vx * vx + vy * vy for vx, vy in vs)


def _check_energy(tol):
    def fn(t):
        start = last_release(t)
        series = _frames_from(t, "vels", start)
        if not series:
            return "no samples after Start"
        e0 = _ke(series[0][1])
        if e0 <= 0:
            return "no kinetic energy at Start"
        for f, vs in series:
            e = _ke(vs)
            if abs(e - e0) > tol * e0:
                return "frame %d: sum |v|^2 = %.1f vs %.1f at Start (%.1f%%)" % (
                    f, e, e0, 100.0 * (e - e0) / e0)
        return True
    return fn


def _check_speed_cap(t):
    start = last_release(t)
    series = _frames_from(t, "vels", start)
    if not series:
        return "no samples after Start"
    cap = math.sqrt(_ke(series[0][1])) * 1.02
    for f, vs in series:
        for vx, vy in vs:
            if math.hypot(vx, vy) > cap:
                return "frame %d: speed %.1f above cap %.1f" % (f, math.hypot(vx, vy), cap)
    return True


def _check_initial_speeds(t):
    # Revised (SPEC-LOGIC): the claim excludes balls already in a contact; the
    # first version approximated that with "80% of balls", which one touching
    # pair breaks at count=8. Now: a ball clear of every other ball and of the
    # walls at the release frame still has its drawn speed. "Clear" allows for
    # the frame's own travel: a pair that touched during the spawn frame is
    # already separated when the sample is read (2 * 340 DU/s * dt < 12).
    f = last_release(t)
    vs = t.at_frame(f, "vels")
    cs = t.at_frame(f, "centers")
    rs = t.at_frame(f, "radii")
    if not vs:
        return "no balls at the release frame"
    bad = []
    for i, ((vx, vy), (x, y), r) in enumerate(zip(vs, cs, rs)):
        touching = any(math.hypot(x - x2, y - y2) <= r + r2 + 12.0
                       for j, ((x2, y2), r2) in enumerate(zip(cs, rs)) if j != i)
        if touching:
            continue
        sp = math.hypot(vx, vy)
        if not (180.0 - 1e-6 <= sp <= 340.0 + 1e-6):
            bad.append((i, round(sp, 3)))
    return "free balls with speed outside [180, 340]: %s" % bad if bad else True


def _check_spawn_box(t):
    f = last_release(t)
    cs = t.at_frame(f, "centers")
    rs = t.at_frame(f, "radii")
    for (x, y), r in zip(cs, rs):
        m = 12.0 + r
        if not (80 - m <= x <= W - 80 + m and 200 - m <= y <= H - 80 + m):
            return "ball at (%.1f, %.1f) outside the spawn box" % (x, y)
    return True


def _check_free_flight(t):
    start = last_release(t) + 1
    cs = _frames_from(t, "centers", start - 1)
    vs = _frames_from(t, "vels", start - 1)
    total = match = 0
    for k in range(1, len(cs)):
        f0, c0 = cs[k - 1]
        f1, c1 = cs[k]
        v0 = vs[k - 1][1]
        if len(c0) != len(c1) or len(v0) != len(c0):
            continue
        for (x0, y0), (x1, y1), (vx, vy) in zip(c0, c1, v0):
            total += 1
            if abs(x1 - (x0 + vx * DT)) < 1e-4 and abs(y1 - (y0 + vy * DT)) < 1e-4:
                match += 1
    if total == 0:
        return "no ball-frames to compare"
    if match < 0.8 * total:
        return "only %d/%d ball-frames moved by vel*dt" % (match, total)
    return True


def _check_some_bounce(t):
    start = last_release(t)
    series = _frames_from(t, "vels", start)
    v0 = series[0][1]
    for f, vs in series[1:]:
        if len(vs) == len(v0):
            for a, b in zip(v0, vs):
                if abs(a[0] - b[0]) > 1e-6 or abs(a[1] - b[1]) > 1e-6:
                    return True
    return "no ball ever changed .vel"


def _count_before_press(t):
    fp = first_press(t)
    for f, _tm, n in t.series("n_balls"):
        if f < fp and n != 0:
            return "frame %d: %s balls before any click" % (f, n)
    return True


def _count_matches_cell(t):
    f = last_release(t)
    for fr, _tm, n in t.series("n_balls"):
        if fr >= f:
            want = int(t.at_frame(fr, "st_count"))
            if int(n) != want:
                return "frame %d: %s balls, st.count=%s" % (fr, n, want)
    return True


def _radii_match_cell(t):
    f = last_release(t)
    for fr, _tm, rs in t.series("radii"):
        if fr >= f:
            want = float(t.at_frame(fr, "st_size"))
            if any(abs(r - want) > 1e-9 for r in rs):
                return "frame %d: radii %s, st.size=%s" % (fr, rs[:3], want)
    return True


def _roda_angle_formula(t):
    for f, _tm, a in t.series("roda_angle"):
        want = 50.0 * f / 60.0
        if _ang_diff(a, want) > 1e-6:
            return "frame %d: angle %.6f, want %.6f (mod 360)" % (f, a, want)
    return True


def _clock_formula(t):
    for f, tm, _v in t.series("time"):
        if abs(tm - f / 60.0) > 1e-9:
            return "frame %d: clock.time %.9f, want %.9f" % (f, tm, f / 60.0)
    return True


def _zoom_after(nth, want):
    def fn(t):
        f = t.input_frame("scroll", nth=nth)
        z = t.at_frame(f, "zoom")
        if abs(z - want) > 1e-9:
            return "after scroll #%d: zoom %.9f, want %.9f" % (nth, z, want)
        return True
    return fn


def _zoom_before_scroll(t):
    f0 = t.input_frame("scroll", nth=0)
    for f, _tm, z in t.series("zoom"):
        if f < f0 and abs(z - 1.0) > 1e-12:
            return "frame %d: zoom %.6f before any scroll" % (f, z)
    return True


def _is_int_in_range(v, lo, hi):
    return float(v) == int(float(v)) and lo <= float(v) <= hi


# ---------------------------------------------------------------- expectations

EXPECT = [
    # ---- startup / script callbacks
    Expect(id="E1", level="L0", cite="docs/pt/guide/index.html#reagir-callbacks",
           text="start() is not a script callback: no ball exists until the Start button is clicked.",
           check=always("n_balls", lambda n: n == 0), scenarios=("idle", "zoom")),
    Expect(id="E2", level="L0", cite="docs/pt/guide/index.html#reagir-callbacks",
           text="In every scenario the ball count is 0 on every frame before the first button press.",
           check=custom(_count_before_press), scenarios=SPAWN_SCENARIOS),
    Expect(id="E3", level="L0", cite="docs/pt/guide/index.html#mundo-grupos",
           text="The wall group holds the four border Rects plus the bar: 5 members, always; balls never join it.",
           check=always("n_walls", lambda n: n == 5), scenarios=("*",)),
    Expect(id="E4", level="L0", cite="docs/pt/guide/index.html#mundo-grupos",
           text="roda is tagged 'wall' (group= in its constructor).",
           check=always("roda_is_wall", lambda v: bool(v)), scenarios=("idle",)),
    Expect(id="E5", level="L0", cite="docs/pt/guide/index.html#colisao-resolve",
           text="group['wall'].mass = STATIC writes to all members and roda.mass = STATIC: every wall mass is inf.",
           check=always("wall_masses", lambda ms: len(ms) == 5 and all(m == INF for m in ms)),
           scenarios=("idle", "start")),

    # ---- cells and widgets
    Expect(id="E6", level="L0", cite="docs/pt/guide/index.html#ui-slider",
           text="A Slider bound to an Attribute without initial= keeps the cell value: st.count stays 30 and st.size 12 with no input.",
           check=all_of(always("st_count", lambda v: float(v) == 30.0),
                        always("st_size", lambda v: float(v) == 12.0)),
           scenarios=("idle", "zoom")),
    Expect(id="E7", level="L0", cite="docs/pt/guide/index.html#ui-slider",
           text="PARAMS count=8, size=30 reach st (inside the slider ranges, only_int value already int): st.count==8, st.size==30.",
           check=all_of(always("st_count", lambda v: float(v) == 8.0),
                        always("st_size", lambda v: float(v) == 30.0)),
           scenarios=("params",)),
    Expect(id="E8", level="L0", cite="docs/pt/guide/index.html#ui-button",
           text="One Start click creates exactly st.count balls (30 by default).",
           check=at(last_release, "n_balls", lambda n: n == 30), scenarios=("start",)),
    Expect(id="E9", level="L0", cite="docs/pt/guide/index.html#ui-button",
           text="After Start the ball count stays equal to int(st.count) on every later frame (nothing else creates or destroys balls).",
           check=custom(_count_matches_cell), scenarios=SPAWN_SCENARIOS),
    Expect(id="E10", level="L0", cite="docs/pt/guide/index.html#mundo-grupos",
           text="A second Start destroys the old set first (group.destroy) then makes a new one: count never exceeds 30 and ends at 30.",
           check=all_of(always("n_balls", lambda n: n <= 30), at_end("n_balls", lambda n: n == 30)),
           scenarios=("restart",)),
    Expect(id="E11", level="L0", cite="docs/pt/guide/index.html#desenhar-drawable",
           text="Every member read from group['ball'] is alive: destroyed balls leave the group.",
           check=always("balls_alive", lambda v: bool(v)), scenarios=("restart", "start")),
    Expect(id="E12", level="L0", cite="docs/pt/guide/index.html#ui-widgets",
           text="Writing st.count=5 and st.size=20 between frames creates no balls by itself (start() only runs on click).",
           check=custom(_count_before_press), scenarios=("cells",)),
    Expect(id="E13", level="L0", cite="docs/pt/guide/index.html#ui-widgets",
           text="After st.count=5, st.size=20 and a Start click there are 5 balls of radius 20.",
           check=all_of(at_end("n_balls", lambda n: n == 5),
                        at_end("radii", lambda rs: len(rs) == 5 and all(r == 20.0 for r in rs))),
           scenarios=("cells",)),
    Expect(id="E14", level="L0", cite="docs/pt/guide/index.html#desenhar-shapes",
           text="Every ball's radius equals float(st.size) (Circle radius= reads back as .radius).",
           check=custom(_radii_match_cell), scenarios=SPAWN_SCENARIOS),
    Expect(id="E15", level="L0", cite="docs/pt/guide/index.html#colisao-resolve",
           text="Each ball's mass reads back 1.0.",
           check=at_end("ball_masses", lambda ms: len(ms) > 0 and all(m == 1.0 for m in ms)),
           scenarios=("start", "params")),
    Expect(id="E16", level="L0", cite="docs/pt/guide/index.html#ui-slider",
           text="After a click on the 'Balls' slider st.count is an integer in [1, 80] (only_int=True, range 1..80).",
           check=at_end("st_count", lambda v: _is_int_in_range(v, 1, 80)), scenarios=("slider",)),
    Expect(id="E17", level="L0", cite="docs/pt/guide/index.html#ui-slider",
           text="GUESS: a press+release on the slider moves the knob to the pointer, so st.count is no longer 30 (assumes click_widget hits the bar, not the label, and the hit is not at the 30 mark).",
           check=at(lambda t: _button_frames(t)[1] if len(_button_frames(t)) > 1 else 10 ** 9,
                    "st_count", lambda v: float(v) != 30.0),
           scenarios=("slider",), guess=True),

    # ---- motion, clock and the spinning bar
    Expect(id="E18", level="L1", cite="design/Scena Design.md#frame-order",
           text="clock.time after frame n is n/60 s (fixed dt, frame-1 dt is a real step); tol 1e-9.",
           check=custom(_clock_formula), scenarios=("idle", "start")),
    Expect(id="E19", level="L1", cite="docs/pt/guide/index.html#mover-pose",
           text="roda.rotate_by(50*dt) each frame: roda.angle after frame n is 50*n/60 degrees (mod 360, counterclockwise positive); tol 1e-6.",
           check=custom(_roda_angle_formula), scenarios=("idle", "start", "zoom")),
    Expect(id="E20", level="L1", cite="docs/pt/guide/index.html#mover-pose",
           text="roda spins about its centre and is STATIC, so its centre stays (500, 360) even with balls hitting it; tol 1e-9.",
           check=always("roda_center", lambda c: close(c, (500.0, 360.0), 1e-9)),
           scenarios=("idle", "start", "crowd", "zoom")),
    Expect(id="E21", level="L1", cite="docs/pt/guide/index.html#geo-vec2",
           text="vec_from_angle(a, length=L) with L in [180, 340]: at the Start release frame at least 80% of balls (those not yet in a contact) have |vel| in [180, 340].",
           check=custom(_check_initial_speeds), scenarios=("start", "crowd", "params"),
           revised="SPEC-LOGIC: the check approximated its own claim (80% threshold); now skips balls in contact"),
    Expect(id="E22", level="L1", cite="design/Scena Design.md#frame-order",
           text="Balls spawn in x in [80, 920], y in [200, 640]; at the release frame each centre is within that box widened by 12 (up to two frames of motion) plus r (overlap separation).",
           check=custom(_check_spawn_box), scenarios=("start", "params", "cells")),
    Expect(id="E23", level="L1", cite="docs/pt/guide/index.html#colisao-resolve",
           text="Free flight: in at least 80% of ball-frames after Start, centre(n) = centre(n-1) + vel(n-1)*dt (update's move_by; contact frames excepted); tol 1e-4.",
           check=custom(_check_free_flight), scenarios=("start", "params")),

    # ---- physics bounds
    Expect(id="E24", level="L2", cite="docs/pt/guide/index.html#colisao-resolve",
           text="resolve(ball, wall) stops travel at the wall: no ball centre ever crosses a wall's inner face (hard bound, no slop: crossing means a penetration of at least r).",
           check=custom(_check_inside_arena), scenarios=SPAWN_SCENARIOS),
    Expect(id="E25", level="L2", cite="docs/pt/guide/index.html#colisao-resolve",
           text="After Start no ball pokes into a border wall by more than 0.25*r (sweep stop + ~0.08 DU skin; slop covers ball-ball pushes within one frame).",
           check=custom(_check_walls(0.25)), scenarios=SPAWN_SCENARIOS),
    Expect(id="E26", level="L2", cite="docs/pt/guide/index.html#colisao-resolve",
           text="resolve('ball','ball') leaves no deep overlap: from 3 frames after Start, centre distance >= r_i + r_j - 0.25*r (spawn overlaps are undone within those frames).",
           check=custom(_check_ball_overlap(0.25)), scenarios=("start", "params", "crowd", "cells")),
    Expect(id="E27", level="L2", cite="design/Scena Design.md#collision",
           text="The spinning bar is a spin (not swept) but resolve undoes leftover overlap: from 3 frames after Start no ball sits more than 0.25*r inside the bar (tip speed ~0.73 DU/frame).",
           check=custom(_check_roda_overlap(0.25)), scenarios=("start", "crowd", "params")),
    Expect(id="E28", level="L2", cite="design/Collision Design.md#velocity-bounce-none-or-restitution",
           text="bounce=1.0 is an elastic, momentum-conserving impulse; STATIC walls and the bar (no .vel) act as rest, infinite mass: total sum |v|^2 stays within 2% of its value at Start.",
           check=custom(_check_energy(0.02)), scenarios=("start", "params", "crowd")),
    Expect(id="E29", level="L2", cite="design/Collision Design.md#velocity-bounce-none-or-restitution",
           text="Consequence of energy conservation: no single ball ever exceeds sqrt(sum |v|^2 at Start) * 1.02.",
           check=custom(_check_speed_cap), scenarios=("start", "crowd")),
    Expect(id="E30", level="L2", cite="docs/pt/guide/index.html#colisao-resolve",
           text="resolve(..., bounce=1.0) writes .vel on contact: within 300 frames at 180-340 DU/s some ball's velocity changes.",
           check=custom(_check_some_bounce), scenarios=("start",)),

    # ---- camera / scroll input
    Expect(id="E31", level="L0", cite="docs/pt/guide/index.html#mundo-camera",
           text="With no scroll the camera keeps zoom 1 and pan (500, 360) (initial view: origin at the corner, so the window centre shows world (W/2, H/2)).",
           check=all_of(always("zoom", lambda z: z == 1.0),
                        always("pan", lambda c: close(c, (500.0, 360.0), 1e-9))),
           scenarios=("idle", "start")),
    Expect(id="E32", level="L1", cite="docs/pt/guide/index.html#reagir-callbacks",
           text="on_mouse_scroll(yoffset>0) calls canvas.zoom_by(1.1): zoom is 1 before the first scroll, 1.1 after it, 1.21 after the second; tol 1e-9.",
           check=all_of(custom(_zoom_before_scroll), custom(_zoom_after(0, 1.1)),
                        custom(_zoom_after(1, 1.21))),
           scenarios=("zoom",)),
    Expect(id="E33", level="L1", cite="docs/pt/guide/index.html#mundo-camera",
           text="A scroll down (yoffset<0) multiplies by 1/1.1: after up, up, down the zoom is back to 1.1 and stays there; tol 1e-9.",
           check=all_of(custom(_zoom_after(2, 1.1)), at_end("zoom", lambda z: abs(z - 1.1) < 1e-9)),
           scenarios=("zoom",)),
    Expect(id="E34", level="L1", cite="docs/pt/guide/index.html#suite-about",
           text="zoom_by without about= anchors at the view centre, so pan_x/pan_y stay (500, 360) through the zooms; tol 1e-6.",
           check=always("pan", lambda c: close(c, (500.0, 360.0), 1e-6)), scenarios=("zoom",)),
]
