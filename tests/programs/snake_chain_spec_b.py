"""Spec B for tests/programs/snake_chain.py, written from the docs alone.

The program: 8 balls in group "bolas" start at the game-view centre; the first
one (the head) is steered by LEFT/RIGHT through a lagged wheel (st.giro chases
+-220 deg/s at rate 5), accelerated by UP/DOWN (80..380 u/s), moved polar along
st.angulo and clamped inside canvas.game_view; every other ball chases the one
in front at rate 8. @every(1) appends a ball at the tail, each one 0.02 darker.
"""
from program_support import (Scenario, Expect, wait, wait_s, click_widget, click,
    key, key_down, key_up, move, scroll, set_cell, always, never, at, at_end,
    eventually, steady, all_of, custom, close)
import math

FILES_READ = [
    "tests/programs/snake_chain.py",
    "tests/programs/spec_agent_prompt.txt",
    "design/Scena Design.md#frame-order",
    "design/Actors Design.md#every-is-seconds-not-frames",
    "docs/pt/guide/index.html#util-chase",
    "docs/pt/guide/index.html#mover-confine",
    "docs/pt/guide/index.html#mundo-grupos",
    "docs/pt/guide/index.html#aparencia-cor (mat-color: lighter/darker; Gradient.darker row)",
    "docs/pt/guide/index.html#circle",
    "docs/pt/guide/index.html#colocar-pais (game_view)",
    "docs/pt/guide/index.html#unidades",
    "docs/pt/guide/index.html (move_by polar angle=/distance= signature)",
    "docs/pt/guide/index.html (keyp table, after/every table)",
    "docs/pt/guide/guia-api-catalogs.js#visual-sphere",
]

# ---- program constants (copied from the program; the program is the spec input)
VMIN, VMAX, ACC, GMAX, RESP, FOLLOW = 80.0, 380.0, 260.0, 220.0, 5.0, 8.0
W, H = 1000.0, 700.0
CX, CY = 500.0, 350.0
DT = 1.0 / 60.0
R_WHEEL = math.exp(-RESP * DT)     # chase keeps this fraction of the gap per frame
R_FOLLOW = math.exp(-FOLLOW * DT)
# tomato = (255, 99, 71): HSL lightness = (max + min) / 2
L_TOMATO = (1.0 + 71.0 / 255.0) / 2.0


def _bolas(p):
    return p.group["bolas"]


PROBES = {
    "count": lambda p: _bolas(p).count,
    "centers": lambda p: tuple((float(b.center.x), float(b.center.y)) for b in _bolas(p)),
    "radii": lambda p: tuple(float(b.radius) for b in _bolas(p)),
    "light": lambda p: tuple(float(b.color.hsl[2]) for b in _bolas(p)),
    "spheres": lambda p: all(isinstance(b.visual, p.Sphere) for b in _bolas(p)),
    "angulo": lambda p: p.st.angulo,
    "giro": lambda p: p.st.giro,
    "vel": lambda p: p.st.velocidade,
    "head_angle": lambda p: float(_bolas(p)[0].angle),
}

SCENARIOS = {
    # nothing pressed: head goes straight up at 80 u/s, hits the top at ~frame 263
    "idle": Scenario(seed=0, steps=[wait(480)]),
    # UP held 90 frames: speed reaches the 380 cap and stays there
    "accel": Scenario(seed=0, steps=[wait(10), key("UP", frames=90), wait(60)]),
    # DOWN at min speed does nothing; then UP 30 frames, DOWN 15 frames
    "brake": Scenario(seed=0, steps=[key("DOWN", frames=60), wait(5),
                                     key("UP", frames=30), wait(5),
                                     key("DOWN", frames=15), wait(20)]),
    # LEFT held 60 frames, then released: wheel lags in and out
    "left": Scenario(seed=0, steps=[wait(5), key("LEFT", frames=60), wait(150)]),
    # RIGHT held 45 frames
    "right": Scenario(seed=0, steps=[key("RIGHT", frames=45), wait(150)]),
    # LEFT and RIGHT together cancel
    "both": Scenario(seed=0, steps=[key_down("LEFT"), key_down("RIGHT"), wait(90),
                                    key_up("LEFT"), key_up("RIGHT"), wait(30)]),
    # long left turn while accelerating: a spiral that may reach the walls
    "spiral": Scenario(seed=0, steps=[key_down("UP"), key_down("LEFT"), wait(240),
                                      key_up("LEFT"), wait(200), key_up("UP"), wait(30)]),
}


# ---------------------------------------------------------------- helpers
def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _series(t, probe):
    return [(f, tm, v) for (f, tm, v) in t.series(probe)]


def _wheel_targets(t):
    """Per frame, the target st.giro chased: must be one of -220, 0, +220."""
    out = []
    prev = 0.0
    for f, _tm, g in _series(t, "giro"):
        if not _num(g):
            return None, "giro probe failed at frame %s: %r" % (f, g)
        tgt = (g - prev * R_WHEEL) / (1.0 - R_WHEEL)
        best = min((-GMAX, 0.0, GMAX), key=lambda c: abs(c - tgt))
        if abs(best - tgt) > 0.5:
            return None, "frame %d: giro %.4f from %.4f is not a rate-5 chase toward -220/0/220 (target %.3f)" % (f, g, prev, tgt)
        out.append((f, best))
        prev = g
    return out, None


def _check_wheel_model(t):
    tg, err = _wheel_targets(t)
    if err:
        return err
    return True


def _check_angle_integrates(t):
    prev = 90.0
    giro = dict((f, g) for f, _tm, g in _series(t, "giro"))
    for f, _tm, a in _series(t, "angulo"):
        g = giro.get(f)
        if not (_num(a) and _num(g)):
            return "probe failed at frame %d" % f
        if abs(a - (prev + g * DT)) > 1e-6 * max(1.0, abs(a)):
            return "frame %d: angulo %.6f != prev %.6f + giro %.6f * dt" % (f, a, prev, g)
        prev = a
    return True


def _check_speed_model(t):
    prev = VMIN
    for f, _tm, v in _series(t, "vel"):
        if not _num(v):
            return "vel probe failed at frame %d" % f
        cands = [min(VMAX, max(VMIN, prev + s * ACC * DT)) for s in (-1, 0, 1)]
        if min(abs(v - c) for c in cands) > 1e-6:
            return "frame %d: velocidade %.6f is not prev %.6f +-260*dt clamped to [80,380]" % (f, v, prev)
        prev = v
    return True


def _clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def _check_head_motion(t):
    """Head: moved v*dt along angulo (this frame's values), then clamped by centre."""
    prev = (CX, CY)
    ang = dict((f, a) for f, _tm, a in _series(t, "angulo"))
    vel = dict((f, v) for f, _tm, v in _series(t, "vel"))
    for f, _tm, cs in _series(t, "centers"):
        if not isinstance(cs, tuple) or not cs:
            return "centers probe failed at frame %d: %r" % (f, cs)
        a, v = ang.get(f), vel.get(f)
        if not (_num(a) and _num(v)):
            return "probe failed at frame %d" % f
        ex = _clamp(prev[0] + v * DT * math.cos(math.radians(a)), 0.0, W)
        ey = _clamp(prev[1] + v * DT * math.sin(math.radians(a)), 0.0, H)
        hx, hy = cs[0]
        if abs(hx - ex) > 1e-3 or abs(hy - ey) > 1e-3:
            return "frame %d: head at (%.4f, %.4f), expected (%.4f, %.4f)" % (f, hx, hy, ex, ey)
        prev = (hx, hy)
    return True


def _check_followers(t):
    """Ball i (i >= 1, present last frame) = lead_new + (own_old - lead_new) * e^(-8 dt)."""
    prev = tuple([(CX, CY)] * 8)
    for f, _tm, cs in _series(t, "centers"):
        if not isinstance(cs, tuple):
            return "centers probe failed at frame %d" % f
        for i in range(1, min(len(prev), len(cs))):
            lx, ly = cs[i - 1]
            ox, oy = prev[i]
            ex = lx + (ox - lx) * R_FOLLOW
            ey = ly + (oy - ly) * R_FOLLOW
            if abs(cs[i][0] - ex) > 1e-3 or abs(cs[i][1] - ey) > 1e-3:
                return "frame %d ball %d at %r, expected (%.4f, %.4f)" % (f, i, cs[i], ex, ey)
        prev = cs
    return True


def _check_spawn_at_tail(t):
    prev_n = 8
    for f, _tm, cs in _series(t, "centers"):
        if not isinstance(cs, tuple):
            return "centers probe failed at frame %d" % f
        n = len(cs)
        if n == prev_n + 1:
            a, b = cs[-1], cs[-2]
            if abs(a[0] - b[0]) > 1e-6 or abs(a[1] - b[1]) > 1e-6:
                return "frame %d: new ball at %r, previous tail at %r" % (f, a, b)
        elif n != prev_n:
            return "frame %d: count jumped from %d to %d" % (f, prev_n, n)
        prev_n = n
    return True


def _check_count_vs_time(t):
    for f, tm, n in _series(t, "count"):
        lo = 8 + int(math.floor(tm - 0.03))
        hi = 8 + int(math.floor(tm + 0.03))
        if not (_num(n) and lo <= n <= hi):
            return "frame %d (t=%.4f): count %r, expected 8 + floor(t) (%d..%d)" % (f, tm, n, lo, hi)
    return True


def _check_lightness(t):
    for f, _tm, ls in _series(t, "light"):
        if not isinstance(ls, tuple):
            return "light probe failed at frame %d" % f
        for i, l in enumerate(ls):
            ex = max(0.0, L_TOMATO - 0.02 * i)
            if abs(l - ex) > 0.01:
                return "frame %d ball %d lightness %.4f, expected %.4f" % (f, i, l, ex)
    return True


def _check_head_angle(t):
    ang = dict((f, a) for f, _tm, a in _series(t, "angulo"))
    for f, _tm, h in _series(t, "head_angle"):
        a = ang.get(f)
        if not (_num(h) and _num(a)):
            return "probe failed at frame %d" % f
        d = (h - a) % 360.0
        if min(d, 360.0 - d) > 1e-4:
            return "frame %d: head .angle %.5f vs st.angulo %.5f (mod 360)" % (f, h, a)
    return True


def _held_count(t, target):
    tg, err = _wheel_targets(t)
    if err:
        return None, err
    frames = [f for f, x in tg if x == target]
    return frames, None


def _check_left_held_60(t):
    frames, err = _held_count(t, GMAX)
    if err:
        return err
    if len(frames) != 60:
        return "LEFT target seen on %d frames, expected 60" % len(frames)
    if frames != list(range(frames[0], frames[0] + 60)):
        return "LEFT frames not contiguous: %r" % frames
    return True


def _check_right_held_45(t):
    frames, err = _held_count(t, -GMAX)
    if err:
        return err
    if len(frames) != 45:
        return "RIGHT target seen on %d frames, expected 45" % len(frames)
    if frames != list(range(frames[0], frames[0] + 45)):
        return "RIGHT frames not contiguous"
    return True


def _check_peak_giro(n, sign):
    def fn(t):
        vals = [g for _f, _tm, g in _series(t, "giro") if _num(g)]
        peak = max(vals) if sign > 0 else -min(vals)
        ex = GMAX * (1.0 - R_WHEEL ** n)
        return True if abs(peak - ex) < 0.05 else "peak |giro| %.4f, expected %.4f" % (peak, ex)
    return fn


def _check_spawn_first(t):
    s = dict((f, n) for f, _tm, n in _series(t, "count"))
    if s.get(58) != 8:
        return "count at frame 58 is %r, expected 8" % s.get(58)
    if s.get(62) != 9:
        return "count at frame 62 is %r, expected 9" % s.get(62)
    return True


def _inside_all(cs):
    return isinstance(cs, tuple) and all(
        -1e-6 <= x <= W + 1e-6 and -1e-6 <= y <= H + 1e-6 for x, y in cs)


def _head_inside(cs):
    return _inside_all(cs[:1])


EXPECT = [
    # ---------------- startup
    Expect(id="E1", level="L0", cite="docs/pt/guide/index.html#after-every (@every: 'No módulo: o timer começa já')",
           text="At frame 1 the group holds exactly the 8 balls made at load; the 1 s timer has not fired yet.",
           check=at(1, "count", lambda n: n == 8), scenarios=("*",)),
    Expect(id="E2", level="L0", cite="docs/pt/guide/index.html#mundo-grupos (group[...] is a live tag view)",
           text="Every ball made with group='bolas' is in group['bolas'] and all have radius 16.",
           check=always("radii", lambda rs: len(rs) >= 8 and all(abs(r - 16.0) < 1e-9 for r in rs)),
           scenarios=("*",)),
    Expect(id="E3", level="L0", cite="docs/pt/guide/guia-api-catalogs.js#visual-sphere",
           text="Every ball keeps its Sphere visual, including balls added by the timer.",
           check=always("spheres", lambda v: v is True), scenarios=("idle", "spiral")),
    Expect(id="E4", level="L1", cite="docs/pt/guide/index.html#colocar-pais; design/Scena Design.md#frame-order",
           text="Before any input the 8 balls start at the game-view centre (500,350); after frame 1 the head is at (500, 350+80/60).",
           check=at(1, "centers", lambda cs: close(cs[0], (CX, CY + VMIN * DT), 1e-4)),
           scenarios=("idle", "accel", "left")),
    Expect(id="E5", level="L0", cite="program body (st cells set before run)",
           text="With nothing pressed the cells stay at their start values: velocidade 80, giro 0, angulo 90.",
           check=all_of(always("vel", lambda v: v == VMIN), always("giro", lambda g: g == 0),
                        always("angulo", lambda a: a == 90)),
           scenarios=("idle",)),
    # ---------------- timer / growth
    Expect(id="E6", level="L0", cite="design/Actors Design.md#every-is-seconds-not-frames",
           text="@every(1) counts world seconds: the 9th ball appears around t=1 s (count 8 at frame 58, 9 at frame 62).",
           check=custom(_check_spawn_first), scenarios=("idle", "left")),
    Expect(id="E7", level="L0", cite="design/Actors Design.md#every-is-seconds-not-frames",
           text="Count is always 8 + floor(clock.time) (+-0.03 s slack around each whole second).",
           check=custom(_check_count_vs_time), scenarios=("*",)),
    Expect(id="E8", level="L0", cite="docs/pt/guide/index.html#mundo-grupos (no destroy; join order)",
           text="Count never decreases and grows by at most one per frame (nothing is destroyed).",
           check=custom(lambda t: (lambda ns: True if all(0 <= b - a <= 1 for a, b in zip([8] + ns, ns))
                                   else "count decreased or jumped")(t.values("count"))),
           scenarios=("*",)),
    Expect(id="E9", level="L1", cite="design/Scena Design.md#frame-order (update before process tick); program acrescentar()",
           text="A timer-added ball appears exactly at the tail ball's centre of that frame (timers run after update, so nobody moved it yet).",
           check=custom(_check_spawn_at_tail), scenarios=("idle", "spiral", "left")),
    Expect(id="E10", level="L0", cite="docs/pt/guide/index.html#mundo-grupos ('A ordem é a de entrada no grupo')",
           text="At the end of 480 idle frames (t=8 s) there are 15 or 16 balls, and at frame 470 exactly 15.",
           check=all_of(at_end("count", lambda n: n in (15, 16)), at(470, "count", lambda n: n == 15)),
           scenarios=("idle",)),
    Expect(id="E11", level="L1", cite="docs/pt/guide/index.html#aparencia-cor (darker: copy; Gradient.darker: amount is the HSL lightness step)",
           text="Ball i (join order) has HSL lightness L(tomato) - 0.02*i (tol 0.01).",
           check=custom(_check_lightness), scenarios=("idle",), guess=True),
    # ---------------- speed
    Expect(id="E12", level="L1", cite="program update; docs keyp table ('True enquanto A está segurada')",
           text="Each frame velocidade is the previous value +-260*dt or unchanged, clamped to [80, 380].",
           check=custom(_check_speed_model), scenarios=("*",)),
    Expect(id="E13", level="L0", cite="program update (clamp max 380)",
           text="Holding UP for 90 frames drives velocidade to the 380 cap, and it stays at 380 after release.",
           check=all_of(at_end("vel", lambda v: abs(v - VMAX) < 1e-9),
                        always("vel", lambda v: VMIN <= v <= VMAX)),
           scenarios=("accel",)),
    Expect(id="E14", level="L1", cite="docs keyp table; harness key(name, frames=n)",
           text="UP is seen on exactly 90 update frames, so velocidade rises on 70 frames (69 full steps + the clamp step).",
           check=custom(lambda t: (lambda inc: True if inc == 70 else "speed rose on %d frames, expected 70" % inc)(
               sum(1 for a, b in zip([VMIN] + t.values("vel"), t.values("vel")) if b > a + 1e-12))),
           scenarios=("accel",)),
    Expect(id="E15", level="L0", cite="program update (clamp min 80)",
           text="DOWN at minimum speed leaves velocidade at 80 (never below).",
           check=all_of(at(60, "vel", lambda v: v == VMIN), always("vel", lambda v: v >= VMIN)),
           scenarios=("brake",)),
    Expect(id="E16", level="L1", cite="program update; harness key frames",
           text="After DOWN 60, UP 30, DOWN 15, velocidade ends at 80 + 30*260/60 - 15*260/60 = 145.",
           check=at_end("vel", lambda v: abs(v - (VMIN + 15 * ACC * DT)) < 1e-6),
           scenarios=("brake",)),
    # ---------------- wheel / heading
    Expect(id="E17", level="L1", cite="docs/pt/guide/index.html#util-chase (lerp(current, target, 1-exp(-rate*dt)))",
           text="Each frame st.giro = chase(previous, target, rate=5) with target -220, 0 or +220.",
           check=custom(_check_wheel_model), scenarios=("*",)),
    Expect(id="E18", level="L1", cite="program update",
           text="Each frame st.angulo = previous + st.giro(this frame) * dt, from 90.",
           check=custom(_check_angle_integrates), scenarios=("*",)),
    Expect(id="E19", level="L0", cite="docs keyp table; harness key(name, frames=n)",
           text="LEFT held 60 frames is seen as target +220 on exactly 60 contiguous frames, never -220.",
           check=all_of(custom(_check_left_held_60), always("giro", lambda g: g >= 0)),
           scenarios=("left",)),
    Expect(id="E20", level="L1", cite="docs/pt/guide/index.html#util-chase",
           text="Peak giro after holding LEFT 60 frames is 220*(1-exp(-5)) ~ 218.52 (tol 0.05).",
           check=custom(_check_peak_giro(60, 1)), scenarios=("left",)),
    Expect(id="E21", level="L1", cite="docs/pt/guide/index.html#util-chase (geometric lag cancels in the sum)",
           text="After LEFT 60 frames and a long release, angulo settles at 90 + 220*60/60 = 310 (tol 0.05); giro back near 0.",
           check=all_of(at_end("angulo", lambda a: abs(a - 310.0) < 0.05),
                        at_end("giro", lambda g: abs(g) < 0.05)),
           scenarios=("left",)),
    Expect(id="E22", level="L0", cite="docs keyp table; harness key(name, frames=n)",
           text="RIGHT held 45 frames is target -220 on exactly 45 contiguous frames; giro never positive.",
           check=all_of(custom(_check_right_held_45), always("giro", lambda g: g <= 0)),
           scenarios=("right",)),
    Expect(id="E23", level="L1", cite="docs/pt/guide/index.html#util-chase",
           text="After RIGHT 45 frames and release, angulo settles at 90 - 220*45/60 = -75 (tol 0.05).",
           check=all_of(custom(_check_peak_giro(45, -1)), at_end("angulo", lambda a: abs(a + 75.0) < 0.05)),
           scenarios=("right",)),
    Expect(id="E24", level="L2", cite="program update (alvo = +220 - 220)",
           text="LEFT and RIGHT held together cancel: |giro| never exceeds what 2 frames of a lone key give (key_down steps may split by a frame).",
           check=all_of(always("giro", lambda g: abs(g) <= GMAX * (1 - R_WHEEL ** 2) + 1e-9),
                        at_end("giro", lambda g: abs(g) < 2.0)),
           scenarios=("both",), guess=True),
    Expect(id="E25", level="L1", cite="docs/pt/guide/index.html#circle (.angle read/write); program ponta.angle = st.angulo",
           text="The head's .angle equals st.angulo every frame (mod 360, in case the engine normalises).",
           check=custom(_check_head_angle), scenarios=("left", "right", "spiral")),
    # ---------------- motion / confine
    Expect(id="E26", level="L1", cite="docs move_by polar ('Graus, 0 = +x'); docs/pt/guide/index.html#mover-confine (by='center', action='clamp')",
           text="Head moves v*dt along angulo each frame, then its centre is clamped into the 1000x700 game view.",
           check=custom(_check_head_motion), scenarios=("*",)),
    Expect(id="E27", level="L1", cite="docs move_by polar; docs/pt/guide/index.html#unidades (y up, 90 = up)",
           text="Idle: head goes straight up at 80 u/s: at frame 120 it is at (500, 510).",
           check=at(120, "centers", lambda cs: close(cs[0], (500.0, 510.0), 1e-4)),
           scenarios=("idle",)),
    Expect(id="E28", level="L1", cite="docs/pt/guide/index.html#mover-confine (clamp holds the centre on the edge)",
           text="Idle: the head reaches the top by frame 263 and is held at (500, 700) from then on.",
           check=all_of(at(262, "centers", lambda cs: cs[0][1] < H),
                        always("centers", lambda cs: close(cs[0], (500.0, 700.0), 1e-6), after=263)),
           scenarios=("idle",)),
    Expect(id="E29", level="L2", cite="docs/pt/guide/index.html#mover-confine",
           text="The head's centre never leaves [0,1000]x[0,700] (slop 1e-6: clamp is exact).",
           check=always("centers", _head_inside), scenarios=("*",)),
    Expect(id="E30", level="L2", cite="docs/pt/guide/index.html#util-chase ('sem passar do alvo')",
           text="Followers chase points inside the box and never overshoot, so every ball stays inside the game view too.",
           check=always("centers", _inside_all), scenarios=("*",)),
    Expect(id="E31", level="L1", cite="docs/pt/guide/index.html#util-chase; docs/pt/guide/index.html#mundo-grupos (order = join order)",
           text="Each follower i moves to lead_new + (own_old - lead_new)*exp(-8/60), where lead_new is ball i-1 already moved this frame.",
           check=custom(_check_followers), scenarios=("*",)),
    Expect(id="E32", level="L1", cite="docs/pt/guide/index.html#util-chase",
           text="Idle: after 480 frames the chain has converged near the head at (500,700): ball 1 within 2 units of it.",
           check=at_end("centers", lambda cs: math.hypot(cs[1][0] - cs[0][0], cs[1][1] - cs[0][1]) < 2.0),
           scenarios=("idle",)),
    Expect(id="E33", level="L2", cite="program; docs/pt/guide/index.html#util-chase",
           text="Spiral (UP+LEFT): the head turns left continuously while held, so angulo is non-decreasing over the whole run.",
           check=custom(lambda t: (lambda vs: True if all(b >= a - 1e-9 for a, b in zip([90.0] + vs, vs))
                                   else "angulo decreased")(t.values("angulo"))),
           scenarios=("spiral", "left")),
]
