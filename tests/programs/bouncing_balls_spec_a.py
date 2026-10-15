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
    # program change: Concave corners
    "docs/pt/guide/index.html#shape-concave",
    "docs/pt/guide/index.html#colisao-resolve (STATIC; spawn overlaps separate)",
    "docs/pt/guide/index.html#colocar-box (contains_point)",
    "design/Shapes Design.md#concave",
    "design/Collision Design.md#polygon-sweeps (sets swept pair by pair, CV1)",
    "design/Collision Design.md#specs-by-body-kind (Concave)",
    "design/Collision Design.md#resting-contact-skin",
]

W, H = 1000.0, 720.0
WALL = 32.0          # wall thickness: inner faces at 32 and W-32 / H-32
DT = 1.0 / 60.0
INF = float("inf")

# program change: Concave corners. Four quarter-pipes, C = 120, rim 0 (default).
# Model from the docs (Guia #shape-concave: "scoop" is the named point where the
# curve's centre sits, a corner takes a quarter out, the curve reaches the far
# sides; radius = box reach - rim): the solid of a piece is its box minus the
# disk of radius R_C around the scoop point S. F is the opposite named point,
# the arena's inner corner. Keyed by the scoop name the program passes.
R_C = 120.0
CORNERS = {
    #  scoop:          (centre,        S (curve centre), F (opposite point))
    "top_right":    ((92.0, 92.0),   (152.0, 152.0),   (32.0, 32.0)),
    "top_left":     ((908.0, 92.0),  (848.0, 152.0),   (968.0, 32.0)),
    "bottom_right": ((92.0, 628.0),  (152.0, 568.0),   (32.0, 688.0)),
    "bottom_left":  ((908.0, 628.0), (848.0, 568.0),   (968.0, 688.0)),
}
OPPOSITE = {"top_right": "bottom_left", "bottom_left": "top_right",
            "top_left": "bottom_right", "bottom_right": "top_left"}


# ---------------------------------------------------------------- probes

def _centers(p):
    return tuple((float(b.center.x), float(b.center.y)) for b in p.group["ball"])


def _vels(p):
    return tuple((float(b.vel.x), float(b.vel.y)) for b in p.group["ball"])


def _model_for(c):
    """The CORNERS entry whose centre is nearest this piece's centre."""
    x, y = float(c.center.x), float(c.center.y)
    return min(CORNERS.items(),
               key=lambda kv: math.hypot(kv[1][0][0] - x, kv[1][0][1] - y))


def _diag_point(S, F, dist):
    """The point at distance `dist` from S toward F along the diagonal."""
    dx, dy = F[0] - S[0], F[1] - S[1]
    n = math.hypot(dx, dy)
    return (S[0] + dx / n * dist, S[1] + dy / n * dist)


def _corner_contains(p):
    out = []
    for c in p.group["corner"]:
        name, (_ctr, S, F) = _model_for(c)
        sx = 1.0 if F[0] > S[0] else -1.0
        sy = 1.0 if F[1] > S[1] else -1.0
        pts = (S,                                   # the scoop point: curve centre
               _diag_point(S, F, 0.4 * math.hypot(F[0] - S[0], F[1] - S[1])),
               _diag_point(S, F, R_C - 2.0),        # just inside the curve (free)
               _diag_point(S, F, R_C + 2.0),        # just past the curve (solid)
               (F[0] - 6.0 * sx, F[1] - 6.0 * sy))  # near the arena corner (solid)
        out.append((name,) + tuple(bool(c.contains_point(x, y)) for x, y in pts))
    return tuple(out)


def _corner_points(p):
    out = []
    for c in p.group["corner"]:
        sc = str(c.scoop)
        a = getattr(c, sc)
        b = getattr(c, OPPOSITE[sc])
        out.append((sc, (float(a.x), float(a.y)), (float(b.x), float(b.y))))
    return tuple(out)


PROBES = {
    # program change: Concave corners (the corner probes)
    "n_corners": lambda p: len(p.group["corner"]),
    "corner_kinds": lambda p: tuple((bool(isinstance(c, p.Concave)), bool(isinstance(c, p.Rect)))
                                    for c in p.group["corner"]),
    "corner_masses": lambda p: tuple(float(c.mass) for c in p.group["corner"]),
    "corner_reads": lambda p: tuple(
        (str(c.scoop), float(c.center.x), float(c.center.y), float(c.width),
         float(c.height), float(c.angle), float(c.rim.x), float(c.rim.y))
        for c in p.group["corner"]),
    "corner_points": _corner_points,
    "corner_contains": _corner_contains,
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
    # program change: Concave corners. One ball, long enough to cross the arena
    # several times (560 frames at >= 180 DU/s is >= 1680 DU).
    "lone": Scenario(params={"count": 1}, seed=21, steps=[
        wait(2), click_widget("Start"), wait(560)]),
    # a few big balls for 560 frames: corner contacts away from walls and others
    "corners": Scenario(params={"count": 12, "size": 24}, seed=22, steps=[
        wait(2), click_widget("Start"), wait(560)]),
}

SPAWN_SCENARIOS = ("start", "restart", "cells", "params", "crowd", "slider")
CORNER_SCENARIOS = SPAWN_SCENARIOS + ("lone", "corners")


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
        # program change: Concave corners. A ball of r >= 20 can spawn
        # overlapping a top corner piece (spawn box reaches 101.8 DU from its
        # curve centre, R = 120): that ball is in a contact too. Margin: one
        # ball's frame travel (340/60 = 5.67) plus the skin, rounded to 6.
        touching = touching or _max_corner_pen((x, y), r) > -6.0
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


# ---- corner pieces (program change: Concave corners)

def _corner_pen(c, r, S, F):
    """How deep a ball (centre c, radius r) reaches into one piece's solid.

    Solid = box minus disk(S, R_C). For a centre in S's quadrant toward F the
    nearest solid point is on the arc along the ray from S: depth
    |c - S| + r - R_C (positive also when the centre is in the solid). Outside
    that quadrant the nearest solid points are the two knife tips (rim 0),
    which sit on the wall faces. Negative = gap.
    """
    sx = 1.0 if F[0] > S[0] else -1.0
    sy = 1.0 if F[1] > S[1] else -1.0
    dx, dy = c[0] - S[0], c[1] - S[1]
    if dx * sx >= 0.0 and dy * sy >= 0.0:
        return math.hypot(dx, dy) + r - R_C
    t1 = (S[0] + sx * R_C, S[1])
    t2 = (S[0], S[1] + sy * R_C)
    return r - min(math.hypot(c[0] - t1[0], c[1] - t1[1]),
                   math.hypot(c[0] - t2[0], c[1] - t2[1]))


def _nearest_corner(c, r):
    """(depth, name) of the piece the ball reaches deepest into."""
    return max((_corner_pen(c, r, S, F), name) for name, (_ctr, S, F) in CORNERS.items())


def _max_corner_pen(c, r):
    return _nearest_corner(c, r)[0]


def _centre_in_corner_solid(c):
    for name, (_ctr, S, F) in CORNERS.items():
        lo_x, hi_x = min(S[0], F[0]), max(S[0], F[0])
        lo_y, hi_y = min(S[1], F[1]), max(S[1], F[1])
        if lo_x <= c[0] <= hi_x and lo_y <= c[1] <= hi_y and \
                math.hypot(c[0] - S[0], c[1] - S[1]) >= R_C:
            return name
    return None


def _check_corner_centres(t):
    for f, cs in _frames_from(t, "centers", 0):
        for x, y in cs:
            name = _centre_in_corner_solid((x, y))
            if name:
                return "frame %d: ball centre (%.2f, %.2f) inside the %s corner's solid" % (
                    f, x, y, name)
    return True


def _check_corner_overlap(slop_frac, settle=3):
    def fn(t):
        start = last_release(t) + settle
        for (f, cs), (_f2, rs) in zip(_frames_from(t, "centers", start),
                                     _frames_from(t, "radii", start)):
            for (x, y), r in zip(cs, rs):
                pen, name = _nearest_corner((x, y), r)
                if pen > slop_frac * r:
                    return "frame %d: ball (%.2f, %.2f) r=%.1f is %.2f inside the %s corner" % (
                        f, x, y, r, pen, name)
        return True
    return fn


def _corner_events(t, settle=3):
    """Ball-frames whose .vel changed while the ball was clear of every other
    partner: walls, other balls and the bar, at both ends of the frame, with a
    margin of the frame's travel + 1 DU. The only resolve partner left is a
    corner piece. Yields (frame, ball, c0, c1, v0, v1, r)."""
    start = last_release(t) + settle - 1
    cs = _frames_from(t, "centers", start)
    vs = _frames_from(t, "vels", start)
    rs = _frames_from(t, "radii", start)
    an = _frames_from(t, "roda_angle", start)
    rc = _frames_from(t, "roda_center", start)
    out = []
    for k in range(1, min(len(cs), len(vs), len(rs), len(an), len(rc))):
        f, c1 = cs[k]
        _f0, c0 = cs[k - 1]
        v0, v1 = vs[k - 1][1], vs[k][1]
        rr = rs[k][1]
        if not (len(c0) == len(c1) == len(v0) == len(v1) == len(rr)):
            continue
        reach = [max(math.hypot(*v0[j]), math.hypot(*v1[j])) * DT + 1.0 for j in range(len(c1))]
        for i in range(len(c1)):
            if math.hypot(v1[i][0] - v0[i][0], v1[i][1] - v0[i][1]) <= 1e-6:
                continue
            r = rr[i]
            clear = True
            for cc, ang, rcen in ((c0, an[k - 1][1], rc[k - 1][1]), (c1, an[k][1], rc[k][1])):
                x, y = cc[i]
                m = r + reach[i]
                if x - m < WALL or x + m > W - WALL or y - m < WALL or y + m > H - WALL:
                    clear = False
                elif _roda_penetration((x, y), r, rcen, ang) > -reach[i]:
                    clear = False
                else:
                    for j in range(len(cc)):
                        if j != i and math.hypot(x - cc[j][0], y - cc[j][1]) <= \
                                r + rr[j] + reach[i] + reach[j]:
                            clear = False
                            break
                if not clear:
                    break
            if clear:
                out.append((f, i, c0[i], c1[i], v0[i], v1[i], r))
    return out


def _check_corner_speed(tol):
    def fn(t):
        for f, i, _c0, _c1, v0, v1, _r in _corner_events(t):
            s0, s1 = math.hypot(*v0), math.hypot(*v1)
            if abs(s1 - s0) > tol * s0:
                return "frame %d ball %d: speed %.2f -> %.2f at a corner bounce" % (f, i, s0, s1)
        return True
    return fn


def _check_corner_contact_at_curve(t):
    for f, i, c0, c1, v0, v1, r in _corner_events(t):
        pen0, name = _nearest_corner(c0, r)
        pen = max(pen0, _max_corner_pen(c1, r))
        need = -(0.5 + max(math.hypot(*v0), math.hypot(*v1)) * DT)
        if pen < need:
            return ("frame %d ball %d: velocity changed %.2f DU short of the drawn %s curve "
                    "(allowed %.2f)" % (f, i, -pen, name, -need))
    return True


def _check_corner_leaves(t):
    for f, i, c0, _c1, _v0, v1, r in _corner_events(t):
        _pen, name = _nearest_corner(c0, r)
        S = CORNERS[name][1]
        ux, uy = S[0] - c0[0], S[1] - c0[1]
        n = math.hypot(ux, uy)
        if n == 0.0:
            continue
        s1 = math.hypot(*v1)
        along = (v1[0] * ux + v1[1] * uy) / n
        if along < -0.15 * s1:
            return "frame %d ball %d: after the %s bounce v.u = %.2f (|v| %.2f), into the solid" % (
                f, i, name, along, s1)
    return True


def _check_some_corner_bounce(t):
    ev = _corner_events(t)
    return True if ev else "no corner-only velocity change happened (scenario assumption)"


def _check_lone_speed(tol):
    def fn(t):
        start = last_release(t)
        cs = _frames_from(t, "centers", start)
        vs = _frames_from(t, "vels", start)
        rs = _frames_from(t, "radii", start)
        an = _frames_from(t, "roda_angle", start)
        rc = _frames_from(t, "roda_center", start)
        if not vs or len(vs[0][1]) != 1:
            return "assumption: exactly one ball after Start"
        for k in range(1, min(len(cs), len(vs), len(rs), len(an), len(rc))):
            f = vs[k][0]
            v0, v1 = vs[k - 1][1][0], vs[k][1][0]
            r = rs[k][1][0]
            s0, s1 = math.hypot(*v0), math.hypot(*v1)
            reach = max(s0, s1) * DT + 1.0
            near_bar = any(_roda_penetration(cs[q][1][0], r, rc[q][1], an[q][1]) > -reach
                           for q in (k - 1, k))
            if near_bar:
                continue
            if abs(s1 - s0) > tol * s0:
                return "frame %d: lone ball speed %.3f -> %.3f away from the bar" % (f, s0, s1)
        return True
    return fn


def _check_corner_reads(t):
    for f, _tm, reads in t.series("corner_reads"):
        got = {}
        for sc, cx, cy, w, h, ang, rx, ry in reads:
            got[sc] = (cx, cy, w, h, ang, rx, ry)
        if set(got) != set(CORNERS):
            return "frame %d: scoops %s, want %s" % (f, sorted(got), sorted(CORNERS))
        for sc, (ctr, _S, _F) in CORNERS.items():
            want = (ctr[0], ctr[1], 120.0, 120.0, 0.0, 0.0, 0.0)
            if not all(abs(a - b) <= 1e-9 for a, b in zip(got[sc], want)):
                return "frame %d: %s piece reads %s, want %s" % (f, sc, got[sc], want)
    return True


def _check_corner_points(t):
    pts = t.end("corner_points")
    if len(pts) != 4:
        return "%d pieces" % len(pts)
    for sc, a, b in pts:
        if sc not in CORNERS:
            return "unknown scoop %r" % (sc,)
        _ctr, S, F = CORNERS[sc]
        if not (close(a, S, 1e-9) and close(b, F, 1e-9)):
            return "%s piece: .%s = %s (want %s), .%s = %s (want %s)" % (
                sc, sc, a, S, OPPOSITE[sc], b, F)
    return True


def _check_corner_contains(t):
    rows = t.end("corner_contains")
    want = (False, False, False, True, True)
    if len(rows) != 4:
        return "%d pieces" % len(rows)
    for row in rows:
        if tuple(row[1:]) != want:
            return "%s piece: contains_point(S, mid-free, R-2, R+2, near F) = %s, want %s" % (
                row[0], tuple(row[1:]), want)
    return True


def _check_corner_still(t):
    series = t.series("corner_reads")
    if not series:
        return "no samples"
    first = {row[0]: row[1:] for row in series[0][2]}
    for f, _tm, reads in series:
        for row in reads:
            ref = first.get(row[0])
            if ref is None or not all(abs(a - b) <= 1e-9 for a, b in zip(row[1:], ref)):
                return "frame %d: %s piece reads %s, was %s" % (f, row[0], row[1:], ref)
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
           # program change: Concave corners
           text="vec_from_angle(a, length=L) with L in [180, 340]: at the Start release frame every ball not yet in a contact (with another ball, or now with a corner piece it spawned against) has |vel| in [180, 340].",
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
           # program change: Concave corners
           text="bounce=1.0 is an elastic, momentum-conserving impulse; the STATIC walls, the bar and the corner pieces (no .vel) act as rest, infinite mass: total sum |v|^2 stays within 2% of its value at Start.",
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

    # ---- the Concave corners (program change: Concave corners)
    Expect(id="E35", level="L0", cite="docs/pt/guide/index.html#shape-concave (Nao confundir: isinstance(c, Rect) is False); #mundo-grupos",
           text="group['corner'] holds the four Concave pieces on every frame (balls never join it); each is a Concave and none is a Rect.",
           check=all_of(always("n_corners", lambda n: n == 4),
                        always("corner_kinds", lambda ks: len(ks) == 4 and all(k == (True, False) for k in ks))),
           scenarios=("*",)),
    Expect(id="E36", level="L0", cite="docs/pt/guide/index.html#colisao-resolve (STATIC = float('inf')); #mundo-grupos",
           text="group['corner'].mass = STATIC writes every member: each corner piece's mass reads inf.",
           check=always("corner_masses", lambda ms: len(ms) == 4 and all(m == INF for m in ms)),
           scenarios=("idle", "start", "corners")),
    Expect(id="E37", level="L1", cite="docs/pt/guide/index.html#shape-concave (Neste Concave: .center .width .height .angle as Rect; .scoop read; .rim Vec2, default 0)",
           text="Each piece reads back its constructor: scoops {top_right, top_left, bottom_right, bottom_left} at centres (92,92), (908,92), (92,628), (908,628), width = height = 120, angle 0, rim (0, 0); tol 1e-9.",
           check=custom(_check_corner_reads), scenarios=("idle",)),
    Expect(id="E38", level="L1", cite="docs/pt/guide/index.html#shape-concave (named points are the box's; the scoop's point is the curve centre, outside the solid)",
           text="Each piece's .<scoop> named point is the curve centre at the arena-side box corner (152,152), (848,152), (152,568), (848,568), and its opposite named point is the arena's inner corner (32,32), (968,32), (32,688), (968,688): the curve faces the arena; tol 1e-9.",
           check=custom(_check_corner_points), scenarios=("idle",)),
    Expect(id="E39", level="L0", cite="docs/pt/guide/index.html#shape-concave (Nao confundir: contains_point follows the exact curve); design/Shapes Design.md#concave (Pointer: inside the box and not strictly inside the ellipse)",
           text="contains_point follows the exact quarter circle of radius 120 around the scoop point: False at the scoop point, at 0.4 of the way to the far corner and at R-2 along the diagonal; True at R+2 and 6 DU in from the far corner.",
           check=custom(_check_corner_contains), scenarios=("idle",)),
    Expect(id="E40", level="L1", cite="docs/pt/guide/index.html#colisao-resolve (STATIC never yields)",
           text="The corner pieces never move: centre, width, height, angle, rim and scoop read the same on every frame as on frame 1, balls hitting them or not, zoom or not; tol 1e-9.",
           check=custom(_check_corner_still), scenarios=("*",)),
    Expect(id="E41", level="L2", cite="docs/pt/guide/index.html#colisao-resolve; docs/pt/guide/index.html#shape-concave (the curve is solid up to it)",
           text="No ball centre is ever inside a corner piece's solid (its box minus the disk of radius 120 around the scoop point): hard bound, no slop (a centre there means a penetration of at least r; spawn centres are at most 101.8 DU from a top piece's curve centre).",
           check=custom(_check_corner_centres), scenarios=CORNER_SCENARIOS),
    Expect(id="E42", level="L2", cite="docs/pt/guide/index.html#shape-concave (collides as chords at most 0.25 DU from the drawn curve); docs/pt/guide/index.html#colisao-resolve (spawn overlaps separate); design/Collision Design.md#resting-contact-skin",
           text="From 3 frames after Start no ball reaches more than 0.25*r into a corner piece's drawn solid. Slop: the chords sit within 0.25 DU of the arc and the sweep stops 0.08 DU short (both under 3 DU = 0.25*12); the rest covers ball-ball pushes within a frame, as E25; a spawn overlap with a top piece (up to 11.8 DU at r=30) is undone within the 3 frames.",
           check=custom(_check_corner_overlap(0.25)), scenarios=CORNER_SCENARIOS),
    Expect(id="E43", level="L2", cite="design/Collision Design.md#velocity-bounce-none-or-restitution (bounce=1 elastic along the normal); docs/pt/guide/index.html#colisao-resolve",
           text="A lone ball's speed is kept within 1% across every frame it spends away from the bar (frame travel + 1 DU): the walls and the corner pieces are STATIC and bounce=1 reflects the normal component without loss.",
           check=custom(_check_lone_speed(0.01)), scenarios=("lone",)),
    Expect(id="E44", level="L2", cite="design/Collision Design.md#velocity-bounce-none-or-restitution; docs/pt/guide/index.html#shape-concave",
           text="Every velocity change of a ball clear of the walls, the bar and every other ball (by the frame's travel + 1 DU, at both ends of the frame, from 3 frames after Start) is a corner bounce and keeps |v| within 1% (elastic against STATIC).",
           check=custom(_check_corner_speed(0.01)), scenarios=("corners", "lone", "crowd")),
    Expect(id="E45", level="L2", cite="docs/pt/guide/index.html#shape-concave (chords within 0.25 DU of the arc); design/Collision Design.md#velocity-bounce-none-or-restitution",
           text="After such a corner bounce the velocity points out of the solid: v . u >= -0.15*|v|, u the unit vector from the ball (before the frame) to the curve centre. Slack: a 0.25 DU sagitta on R=120 tilts a chord normal by at most 3.7 deg (sin 0.065), plus up to ~3 deg because u is taken one frame of travel (<= 5.7 DU at 108 DU from S) from the contact.",
           check=custom(_check_corner_leaves), scenarios=("corners", "lone", "crowd")),
    Expect(id="E46", level="L2", cite="design/Collision Design.md#polygon-sweeps (sets swept pair by pair, CV1); docs/pt/guide/index.html#shape-concave (not a box; collision follows the drawn curve)",
           text="A corner bounce happens at the drawn curve, not at the box or the hull chord from tip to tip (85 DU from the curve centre vs 120): at the frame before or after the change the ball reaches within 0.5 DU + one frame of travel of the arc (0.25 chord + 0.08 sweep slop + 0.16 skin < 0.5).",
           check=custom(_check_corner_contact_at_curve), scenarios=("corners", "lone", "crowd")),
    Expect(id="E47", level="L2", cite="docs/pt/guide/index.html#colisao-resolve (resolve with bounce= writes .vel on contact)",
           text="GUESS: with 12 balls of r=24 for 560 frames (each travels >= 1680 DU) at least one corner bounce happens clear of the walls, the bar and the other balls (assumes the seeded spawn sends some ball into a curve's middle; the check says so if not).",
           check=custom(_check_some_corner_bounce), scenarios=("corners",), guess=True),
]
