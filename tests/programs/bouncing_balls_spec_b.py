"""Spec B for tests/programs/bouncing_balls.py, written from the docs alone.

Arena (from the program): W=1000, H=720; walls 32 DU thick, so the inner
faces are x=32, x=968, y=32, y=688. The spinning bar `roda` is a 100 x 20 Rect
at (500, 360), STATIC, turned by 50 deg/s in update(). Balls exist only after
the Start button runs start().

Corners (program change: Concave corners): four 120 x 120 Concave boxes, group
"corner", STATIC, each sitting in an inner corner of the arena (boxes
[32, 152] x [32, 152] and its mirrors). Each scoop is the box corner that faces
the arena, so by the docs (a corner scoop is centred on that named point, radii
(w - rim.x, h - rim.y) = (120, 120), rim 0) the solid of the bottom-left piece
is the box minus the disc of radius 120 about (152, 152): the region between
the arena corner (32, 32) and the quarter circle through the knife tips
(32, 152) and (152, 32). The other three are its mirrors in x = W/2, y = H/2.
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
    # program change: Concave corners
    "docs/pt/guide/index.html#shape-concave",
    "docs/pt/guide/index.html#colisao-resolve ('Não há atrito'; bounce=1.0 elástico; "
    "'nascem um dentro do outro se separam')",
    "docs/pt/guide/index.html#reagir-pointer (contains_point = geometria de desenho)",
    "docs/pt/guide/index.html#mundo-grupos (order = entry order; group write 'escreve em todos')",
    "docs/pt/guide/index.html (Parâmetros de STATIC table, ~line 9530)",
    "design/Shapes Design.md#concave",
    "design/Collision Design.md#polygon-sweeps (sets swept pair by pair, CV1)",
    "design/Collision Design.md#specs-by-body-kind (Concave)",
]

W, H = 1000.0, 720.0
WALL = 32.0
DT = 1.0 / 60.0
RODA_C = (500.0, 360.0)
RODA_HALF = (50.0, 10.0)
# corner pieces (program change: Concave corners)
C = 120.0
CC = WALL + C                   # 152: the folded curve centre is (CC, CC)
CORNER_R = C                    # rim 0: radius = w - rim.x = h - rim.y = 120
CORNERS = (                     # entry order (group order = entry order)
    ((WALL + C / 2, WALL + C / 2), "top_right"),
    ((W - WALL - C / 2, WALL + C / 2), "top_left"),
    ((WALL + C / 2, H - WALL - C / 2), "bottom_right"),
    ((W - WALL - C / 2, H - WALL - C / 2), "bottom_left"),
)

# ---------------------------------------------------------------- probes


def _balls(p):
    out = []
    for b in p.group["ball"]:
        out.append((float(b.center.x), float(b.center.y),
                    float(b.vel.x), float(b.vel.y), float(b.radius)))
    return tuple(out)


def _pt(v):
    if hasattr(v, "x"):
        return (float(v.x), float(v.y))
    return (float(v[0]), float(v[1]))


def _unfold(fx, fy, cx, cy):
    """A point given in the bottom-left piece's frame, mirrored to the piece at (cx, cy)."""
    return (fx if cx < W / 2 else W - fx, fy if cy < H / 2 else H - fy)


# Folded test points for contains_point, with the answer the exact curve gives
# (solid = inside the box [32, 152]^2 and not strictly inside the disc r=120
# about (152, 152)):
_DIAG = 1.0 / math.sqrt(2.0)
CONTAINS_PROBES = (
    (40.0, 40.0),                       # deep in the solid, by the arena corner
    (140.0, 140.0),                     # in the scoop
    (CC - 121.0 * _DIAG, CC - 121.0 * _DIAG),   # 1 DU past the arc, on the diagonal: solid
    (CC - 119.0 * _DIAG, CC - 119.0 * _DIAG),   # 1 DU short of the arc: scoop
    (34.0, 140.0),                      # in the box, 1.4 DU inside the disc near a knife tip
    (160.0, 40.0),                      # outside the box
    (CC, CC),                           # the scoop's named point: the curve centre
)
CONTAINS_WANT = (True, False, True, False, False, False, False)


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
    # program change: Concave corners
    "n_corners": lambda p: len(p.group["corner"]),
    "corner_kinds": lambda p: tuple(
        (isinstance(c, p.Concave), isinstance(c, p.Rect), bool(c.tagged("corner")),
         bool(c.tagged("wall")), isinstance(c.visual, p.Metal))
        for c in p.group["corner"]),
    "corner_mass": lambda p: tuple(float(c.mass) for c in p.group["corner"]),
    "corners": lambda p: tuple(
        (float(c.center.x), float(c.center.y), float(c.width), float(c.height),
         str(c.scoop), float(c.rim.x), float(c.rim.y), float(c.angle))
        for c in p.group["corner"]),
    "corner_points": lambda p: tuple(
        (_pt(c.bottom_left), _pt(c.bottom_right), _pt(c.top_left), _pt(c.top_right),
         _pt(getattr(c, str(c.scoop))))
        for c in p.group["corner"]),
    "corner_contains": lambda p: tuple(
        tuple(bool(c.contains_point(*_unfold(fx, fy, float(c.center.x), float(c.center.y))))
              for (fx, fy) in CONTAINS_PROBES)
        for c in p.group["corner"]),
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
    # program change: Concave corners. Long runs so balls reach the corners.
    # Seeds picked by a plain-Python flight model of start() (walls + arcs, no
    # bar, no ball-ball); the checks that need a corner contact verify it.
    "corner_one": Scenario(params={"count": 1}, seed=24, steps=[
        wait(2), click_widget("Start"), wait(570)]),
    "corner_six": Scenario(params={"count": 6}, seed=5, steps=[
        wait(2), click_widget("Start"), wait(570)]),
}

STARTED = ("start", "one_ball", "cells", "params", "max_balls", "zoomed_start")
CORNER_RUNS = ("corner_one", "corner_six")
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


def _seg_dist(px, py, ax, ay, bx, by):
    ux, uy = bx - ax, by - ay
    L2 = ux * ux + uy * uy
    k = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * ux + (py - ay) * uy) / L2))
    return math.hypot(px - (ax + k * ux), py - (ay + k * uy))


def _fold(x, y):
    return (x if x < W / 2 else W - x, y if y < H / 2 else H - y)


def _corner_centre(x, y):
    """World curve centre of the corner piece in the quadrant of (x, y)."""
    return (CC if x < W / 2 else W - CC, CC if y < H / 2 else H - CC)


def _corner_signed_dist(x, y):
    """Signed distance from (x, y) to the solid of the nearest corner piece
    (negative inside). Folded solid S = box [32, 152]^2 minus the open disc
    r=120 about (152, 152); its boundary is the arc plus the two outer edges
    (rim 0: the arc's ends are knife tips on those edges)."""
    fx, fy = _fold(x, y)
    dx, dy = fx - CC, fy - CC
    rho = math.hypot(dx, dy)
    if WALL <= fx <= CC and WALL <= fy <= CC and rho >= CORNER_R:
        return -min(rho - CORNER_R, fx - WALL, fy - WALL, CC - fx, CC - fy)
    best = float("inf")
    if dx <= 0 and dy <= 0:                       # radial foot lands on the arc
        best = abs(rho - CORNER_R)
    best = min(best, _seg_dist(fx, fy, WALL, WALL, CC, WALL),
               _seg_dist(fx, fy, WALL, WALL, WALL, CC))
    return best


def _check_out_of_corners(slop):
    def fn(t):
        f0 = _first_frame_with_balls(t)
        if f0 is None:
            return "no balls ever appeared"
        for f, _tm, balls in t.series("balls"):
            if f < f0:
                continue
            for (x, y, _vx, _vy, r) in balls:
                d = _corner_signed_dist(x, y)
                if d < r - slop:
                    return "frame %d: ball (%.2f, %.2f) r=%.1f is %.2f DU into a corner piece" % (
                        f, x, y, r, r - d)
        return True
    return fn


def _corner_bounces(t, need_wall_clear):
    """(frame, ball index, before, after, mid) for each frame a ball's velocity
    changed while its path midpoint was within r + 6 DU of a corner arc, in the
    arc's angular range, with no other ball within ri + rj + 8 and the bar
    > 51 + r + 8 away at both frames. r + 6: contact is at r (+0.25 chords, +
    skin); the midpoint of the frame's path is within half a frame of travel
    (<= 2.84 DU at 340 DU/s) of the contact point."""
    out = []
    ser = t.series("balls")
    for k in range(1, len(ser)):
        f, _tm, cur = ser[k]
        fp, _tp, prev = ser[k - 1]
        if f != fp + 1 or len(cur) != len(prev) or not cur:
            continue
        for i in range(len(cur)):
            x0, y0, vx0, vy0, r = prev[i]
            x1, y1, vx1, vy1, _ = cur[i]
            if abs(vx1 - vx0) < 1e-9 and abs(vy1 - vy0) < 1e-9:
                continue
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            fx, fy = _fold(mx, my)
            if not (fx < CC and fy < CC):
                continue
            if _corner_signed_dist(mx, my) > r + 6.0:
                continue
            ok = True
            for (x, y) in ((x0, y0), (x1, y1)):
                if math.hypot(x - RODA_C[0], y - RODA_C[1]) <= 51.0 + r + 8.0:
                    ok = False
                if need_wall_clear:
                    gx, gy = _fold(x, y)
                    if gx < WALL + r + 8.0 or gy < WALL + r + 8.0:
                        ok = False
            for j in range(len(cur)):
                if j == i:
                    continue
                for (bs, a) in ((prev, (x0, y0)), (cur, (x1, y1))):
                    xj, yj, _a, _b, rj = bs[j]
                    if math.hypot(a[0] - xj, a[1] - yj) <= r + rj + 8.0:
                        ok = False
            if ok:
                out.append((f, i, (vx0, vy0), (vx1, vy1), (mx, my)))
    return out


def _check_corner_speed(t):
    hits = _corner_bounces(t, need_wall_clear=False)
    if not hits:
        return ("scenario premise failed: no isolated corner bounce happened "
                "(seed-dependent; not an engine fact)")
    for (f, i, v0, v1, _m) in hits:
        s0, s1 = math.hypot(*v0), math.hypot(*v1)
        if abs(s1 - s0) > 1e-6 * s0:
            return "frame %d ball %d: corner bounce changed speed %.6f -> %.6f" % (f, i, s0, s1)
    return True


def _check_corner_normal(max_deg):
    def fn(t):
        hits = _corner_bounces(t, need_wall_clear=True)
        if not hits:
            return ("scenario premise failed: no corner bounce on the middle of an arc "
                    "(seed-dependent; not an engine fact)")
        for (f, i, v0, v1, (mx, my)) in hits:
            dvx, dvy = v1[0] - v0[0], v1[1] - v0[1]
            cx, cy = _corner_centre(mx, my)
            nx, ny = cx - mx, cy - my
            dl, nl = math.hypot(dvx, dvy), math.hypot(nx, ny)
            cosang = (dvx * nx + dvy * ny) / (dl * nl)
            ang = math.degrees(math.acos(max(-1.0, min(1.0, cosang))))
            if ang > max_deg:
                return ("frame %d ball %d: velocity change (%.2f, %.2f) is %.2f deg off the "
                        "direction to the curve centre (%.0f, %.0f)" % (f, i, dvx, dvy, ang, cx, cy))
        return True
    return fn


def _check_corner_reads(t):
    for f, _tm, cs in t.series("corners"):
        if len(cs) != 4:
            return "frame %d: %d corner pieces" % (f, len(cs))
        for k, (got, ((cx, cy), scoop)) in enumerate(zip(cs, CORNERS)):
            want = (cx, cy, C, C, scoop, 0.0, 0.0, 0.0)
            if got[4] != scoop:
                return "frame %d piece %d: scoop %r, expected %r" % (f, k, got[4], scoop)
            for a, b in zip(got[:4] + got[5:], want[:4] + want[5:]):
                if abs(a - b) > 1e-9:
                    return "frame %d piece %d: %r, expected %r" % (f, k, got, want)
    return True


def _check_corner_points(t):
    for f, _tm, pts in t.series("corner_points"):
        if len(pts) != 4:
            return "frame %d: %d corner pieces" % (f, len(pts))
        for k, (got, ((cx, cy), scoop)) in enumerate(zip(pts, CORNERS)):
            h = C / 2
            box = {"bottom_left": (cx - h, cy - h), "bottom_right": (cx + h, cy - h),
                   "top_left": (cx - h, cy + h), "top_right": (cx + h, cy + h)}
            want = (box["bottom_left"], box["bottom_right"], box["top_left"],
                    box["top_right"], _corner_centre(cx, cy))
            if box[scoop] != _corner_centre(cx, cy):
                return "spec arithmetic: piece %d scoop point is not the curve centre" % k
            for a, b in zip(got, want):
                if not close(a, b, 1e-9):
                    return "frame %d piece %d: named points %r, expected %r" % (f, k, got, want)
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
        # program change: Concave corners -- the corner pieces are partners too
        far_corners = all(_corner_signed_dist(x, y) > r + clear
                          for (x, y) in ((x0, y0), (x1, y1)))
        if not (far_walls and far_bar and far_corners):
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
    # program change: Concave corners
    Expect(id="E21", level="L1", cite="docs/pt/guide/index.html#pose-move-by",
           text="A single ball away from every partner (wall faces, the bar, and now the corner "
                "pieces' solid: > r + 8 DU at both frames) moves exactly vel*dt per frame (move_by in update).",
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
    # program change: Concave corners
    Expect(id="E25", level="L0", cite="docs/pt/guide/index.html#mundo-camera ('ela não move os objetos')",
           text="Zooming moves no object: walls, roda centre and the four corner pieces unchanged.",
           check=all_of(steady("walls", tol=1e-9), always("roda_center", lambda c: close(c, RODA_C, 1e-9)),
                        steady("corners", tol=1e-9)),
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

    # ---- corner pieces (program change: Concave corners)
    Expect(id="E34", level="L0", cite="docs/pt/guide/index.html#mundo-grupos + #shape-concave ('Não confundir')",
           text="group['corner'] holds exactly the 4 Concave pieces, always (before and after Start); "
                "each is a Concave, is not a Rect (isinstance(c, Rect) is False), carries 'corner' and not 'wall'.",
           check=all_of(always("n_corners", lambda n: n == 4),
                        always("corner_kinds", lambda ks: len(ks) == 4 and
                               all(k[0] and not k[1] and k[2] and not k[3] for k in ks)),
                        always("n_walls", lambda n: n == 5)),
           scenarios=ALL),
    Expect(id="E35", level="L0", cite="docs/pt/guide/index.html#colisao-resolve (STATIC = float('inf')) + #mundo-grupos (group write)",
           text="group['corner'].mass = STATIC writes every piece: all 4 masses are inf.",
           check=always("corner_mass", lambda ms: len(ms) == 4 and all(math.isinf(m) and m > 0 for m in ms)),
           scenarios=("idle", "start")),
    Expect(id="E36", level="L1", cite="docs/pt/guide/index.html#shape-concave ('Neste Concave': .center .width .height .angle .scoop .rim)",
           text="In entry order the pieces read centre (92,92), (908,92), (92,628), (908,628); width = height = 120; "
                "scoop 'top_right', 'top_left', 'bottom_right', 'bottom_left'; rim Vec2(0, 0) (default 0); angle 0. Tol 1e-9.",
           check=custom(_check_corner_reads), scenarios=("idle", "start")),
    Expect(id="E37", level="L1", cite="docs/pt/guide/index.html#shape-concave ('Os cantos e meios de aresta são os da caixa — o do scoop é o centro da curva')",
           text="Each piece's named corners are its box's corners (centre +- 60), and the point named by its scoop "
                "is the curve centre: (152,152), (848,152), (152,568), (848,568). Tol 1e-9.",
           check=custom(_check_corner_points), scenarios=("idle",)),
    Expect(id="E38", level="L0", cite="docs/pt/guide/index.html#shape-concave ('O clique (contains_point) segue a curva exata'; 'fora do sólido') + #reagir-pointer",
           text="contains_point follows the exact quarter circle r=120 about the scoop point: true deep by the arena "
                "corner and 1 DU past the arc; false in the scoop, 1 DU short of the arc, 1.4 DU inside the disc next "
                "to a knife tip, outside the box, and at the scoop point itself.",
           check=always("corner_contains", lambda cs: len(cs) == 4 and all(c == CONTAINS_WANT for c in cs)),
           scenarios=("idle",)),
    Expect(id="E39", level="L1", cite="design/Collision Design.md#movability-mass-and-static + docs/pt/guide/index.html#colisao-resolve ('Um STATIC nunca cede')",
           text="No corner piece moves, turns or resizes, even under 80 balls (STATIC; update() never touches them): "
                "the read tuple is constant, tol 1e-9.",
           check=steady("corners", tol=1e-9), scenarios=("start", "max_balls") + CORNER_RUNS),
    Expect(id="E40", level="L2", cite="docs/pt/guide/index.html#shape-concave ('a curva é sólida até ela'; chords within 0.25) + design/Shapes Design.md#concave",
           text="From the frame balls appear, no ball centre is closer than r - 2 DU to a corner piece's solid "
                "(box minus the disc r=120 about the scoop point). Slop 2 DU, as for the walls: resting skin "
                "0.08 DU plus settle under crowding; a size-20 ball can spawn up to 1.8 DU into an upper piece "
                "(spawn corner (80, 640) is 101.8 from (152, 568)) and is separated by resolve; chords with "
                "their ends on the arc lie on the scoop side, so they only keep balls further out.",
           check=custom(_check_out_of_corners(2.0)),
           scenarios=("start", "one_ball", "restart", "cells", "params", "max_balls", "zoomed_start") + CORNER_RUNS),
    Expect(id="E41", level="L2", cite="docs/pt/guide/index.html#colisao-resolve (bounce=1.0 elástico) + design/Collision Design.md#velocity-bounce-none-or-restitution",
           text="resolve('ball', 'corner', bounce=1.0) against a STATIC piece is elastic: at every frame a ball "
                "bounces off a corner arc with no other ball or the bar near, its speed is unchanged (rel 1e-6). "
                "Scenario premise (checked): at least one such bounce happens.",
           check=custom(_check_corner_speed), scenarios=CORNER_RUNS),
    Expect(id="E42", level="L1", cite="docs/pt/guide/index.html#shape-concave ('colide como cordas a no máximo 0,25'; 'Uma caixa' is what it is not) + #colisao-resolve ('Não há atrito') + design/Collision Design.md#polygon-sweeps (CV1)",
           text="A corner bounce reflects about the curve's normal, not a box face or the hull chord: with no "
                "friction the velocity change of a ball hitting the middle of an arc (> r + 8 DU from the wall "
                "faces) points at the curve centre within 8 deg (chord normal <= 3.7 deg off radial for a "
                "0.25 DU sagitta at r=120; path midpoint <= 2.84 DU from the contact at radius ~108: 1.5 deg). "
                "Scenario premise (checked): at least one such bounce happens.",
           check=custom(_check_corner_normal(8.0)), scenarios=CORNER_RUNS),
    Expect(id="E43", level="L2", cite="design/Collision Design.md#velocity-bounce-none-or-restitution",
           text="With six balls bouncing off walls, corners and each other (all bounce=1, corners STATIC), "
                "sum of |v|^2 is constant after Start, rel tol 1e-4.",
           check=custom(_check_ke_conserved(1e-4)), scenarios=CORNER_RUNS),
    Expect(id="E44", level="L0", cite="docs/pt/guide/index.html#mundo-grupos ('escreve em todos') + #shape-concave (.visual on a Shape)",
           text="group['corner'].visual = Metal() gives every piece a Metal look (isinstance, not class name).",
           check=always("corner_kinds", lambda ks: len(ks) == 4 and all(k[4] for k in ks)),
           scenarios=("idle",)),
]
