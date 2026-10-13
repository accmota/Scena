"""Spec A for tests/programs/snake_chain.py, written from the docs alone."""
from program_support import (Scenario, Expect, wait, wait_s, click_widget, click,
    key, key_down, key_up, move, scroll, set_cell, always, never, at, at_end,
    eventually, steady, all_of, custom, close)
import math

FILES_READ = [
    "tests/programs/spec_agent_prompt.txt",
    "tests/programs/snake_chain.py",
    "design/Scena Design.md#frame-order",
    "docs/pt/guide/index.html#init",
    "docs/pt/guide/index.html#util-chase",
    "docs/pt/guide/index.html#frame (clock)",
    "docs/pt/guide/index.html#frame-teclado",
    "docs/pt/guide/index.html#agendar-timers",
    "docs/pt/guide/index.html#mundo-grupos",
    "docs/pt/guide/index.html#pose-move-by",
    "docs/pt/guide/index.html#mover-confine",
    "docs/pt/guide/index.html (Point section: center= copies a point once)",
    "docs/pt/guide/index.html (Regioes da tela: canvas.game_view)",
    "docs/pt/guide/index.html#mat-color (darker)",
    "docs/pt/guide/index.html#util-approach (one-liner, signature, table, gotcha, confuse table)",
    "docs/pt/guide/index.html#pose-move-to (move_to(ponto): tuple / Point, centre lands on it)",
    "docs/pt/guide/index.html line ~10667 (chase vs approach confuse row)",
]

DT = 1.0 / 60.0
W, H = 1000.0, 700.0
START = (500.0, 350.0)          # canvas.game_view.center for init(1000, 700)
K_GIRO = 1.0 - math.exp(-5 * DT)     # chase(..., rate=5)
K_FOLLOW = 1.0 - math.exp(-8 * DT)   # chase(..., rate=8)
TOL = 1e-6


def _bolas(p):
    return p.group["bolas"]


PROBES = {
    "count": lambda p: _bolas(p).count,
    "centers": lambda p: tuple((float(b.center.x), float(b.center.y)) for b in _bolas(p)),
    "head": lambda p: (float(_bolas(p)[0].center.x), float(_bolas(p)[0].center.y)),
    "head_angle": lambda p: float(_bolas(p)[0].angle),
    "radii": lambda p: tuple(float(b.radius) for b in _bolas(p)),
    "angulo": lambda p: float(p.st.angulo),
    "giro": lambda p: float(p.st.giro),
    "vel": lambda p: float(p.st.velocidade),
    "time": lambda p: float(p.clock.time),
    "view_center": lambda p: (float(p.canvas.game_view.center.x),
                              float(p.canvas.game_view.center.y)),
    "spheres": lambda p: all(isinstance(b.visual, p.Sphere) for b in _bolas(p)),
    # farejador (sniffer): a plain Circle outside group "bolas"
    "far": lambda p: (float(p.farejador.center.x), float(p.farejador.center.y)),
    "far_r": lambda p: float(p.farejador.radius),
    "far_in_bolas": lambda p: any(b is p.farejador for b in _bolas(p)),
}

# Key events per scenario, in delivery order; each maps onto t.input_frame("key", n).
KEY_EVENTS = {
    "idle": [],
    "up": [("UP", True), ("UP", False)],
    "up_max": [("UP", True), ("UP", False)],
    "down_min": [("DOWN", True), ("DOWN", False)],
    "up_down": [("UP", True), ("UP", False), ("DOWN", True), ("DOWN", False)],
    "left": [("LEFT", True), ("LEFT", False)],
    "right": [("RIGHT", True), ("RIGHT", False)],
    "left_right": [("LEFT", True), ("RIGHT", True), ("LEFT", False), ("RIGHT", False)],
}

SCENARIOS = {
    "idle": Scenario(params={}, seed=0, steps=[wait(300)]),
    "up": Scenario(params={}, seed=0, steps=[wait(10), key("UP", frames=30), wait(60)]),
    "up_max": Scenario(params={}, seed=0, steps=[key("UP", frames=120), wait(20)]),
    "down_min": Scenario(params={}, seed=0, steps=[wait(5), key("DOWN", frames=30), wait(10)]),
    "up_down": Scenario(params={}, seed=0, steps=[key("UP", frames=60), wait(5),
                                                  key("DOWN", frames=30), wait(10)]),
    "left": Scenario(params={}, seed=0, steps=[wait(5), key("LEFT", frames=60), wait(120)]),
    "right": Scenario(params={}, seed=0, steps=[wait(5), key("RIGHT", frames=60), wait(60)]),
    "left_right": Scenario(params={}, seed=0, steps=[wait(5), key_down("LEFT"), wait(10),
                                                     key_down("RIGHT"), wait(30),
                                                     key_up("LEFT"), wait(10),
                                                     key_up("RIGHT"), wait(30)]),
    # farejador: long idle run so it catches the head (pinned at (500, 700)) around frame 309
    "catch": Scenario(params={}, seed=0, steps=[wait(400)]),
    # farejador caught at ~309; then LEFT turns the head off the top wall and UP pushes it to
    # 380 u/s (> 150), so the head runs away; after UP/LEFT release it creeps along the top
    # wall at ~44 u/s and is caught again (model: ~frame 481, max gap ~127)
    "escape": Scenario(params={}, seed=0, steps=[wait(320), key_down("LEFT"), wait(20),
                                                 key_down("UP"), wait(80), key_up("LEFT"),
                                                 wait(40), key_up("UP"), wait(100)]),
}


def _near(a, b, tol=TOL):
    return abs(a - b) <= tol


def _pt_near(a, b, tol=TOL):
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def _clampv(v, lo, hi):
    return max(lo, min(hi, v))


def _model(events):
    """Replay keyp state from the delivered key frames and integrate giro/angulo/velocidade."""
    def check(t):
        evs = sorted((t.input_frame("key", i), ev) for i, ev in enumerate(events))
        held = set()
        giro, ang, vel = 0.0, 90.0, 80.0
        j = 0
        for s in t.samples:
            while j < len(evs) and evs[j][0] <= s.frame:
                name, down = evs[j][1]
                if down:
                    held.add(name)
                else:
                    held.discard(name)
                j += 1
            alvo = (220.0 if "LEFT" in held else 0.0) - (220.0 if "RIGHT" in held else 0.0)
            giro += (alvo - giro) * K_GIRO
            ang += giro * DT
            if "UP" in held:
                vel += 260.0 * DT
            if "DOWN" in held:
                vel -= 260.0 * DT
            vel = _clampv(vel, 80.0, 380.0)
            v = s.values
            if not _near(v["giro"], giro, 1e-5):
                return f"frame {s.frame}: giro {v['giro']} != model {giro}"
            if not _near(v["angulo"], ang, 1e-5):
                return f"frame {s.frame}: angulo {v['angulo']} != model {ang}"
            if not _near(v["vel"], vel, 1e-5):
                return f"frame {s.frame}: velocidade {v['vel']} != model {vel}"
        return True
    return custom(check)


def _count_vs_time(t):
    for s in t.samples:
        tm = s.values["time"]
        if abs(tm - round(tm)) <= 1.5 * DT:
            continue  # the firing frame itself may land on either side of the boundary
        want = 8 + int(math.floor(tm))
        if s.values["count"] != want:
            return f"frame {s.frame} (t={tm:.4f}): count {s.values['count']} != {want}"
    return True


def _count_steps(t):
    prev = 8
    for s in t.samples:
        n = s.values["count"]
        if n - prev not in (0, 1):
            return f"frame {s.frame}: count went {prev} -> {n}"
        prev = n
    return True


def _head_step(t):
    prev = START
    for s in t.samples:
        v, a = s.values["vel"], math.radians(s.values["angulo"])
        ex = (prev[0] + v * DT * math.cos(a), prev[1] + v * DT * math.sin(a))
        ex = (_clampv(ex[0], 0.0, W), _clampv(ex[1], 0.0, H))
        if not _pt_near(s.values["head"], ex, 1e-5):
            return f"frame {s.frame}: head {s.values['head']} != expected {ex}"
        prev = s.values["head"]
    return True


def _followers(t):
    prev = (START,) * 8
    for s in t.samples:
        c = s.values["centers"]
        for i in range(1, len(prev)):
            ex = (prev[i][0] + (c[i - 1][0] - prev[i][0]) * K_FOLLOW,
                  prev[i][1] + (c[i - 1][1] - prev[i][1]) * K_FOLLOW)
            if not _pt_near(c[i], ex, 1e-5):
                return f"frame {s.frame}: ball {i} at {c[i]} != chase {ex}"
        prev = c
    return True


def _frame1_cascade(t):
    c = t.at_frame(1, "centers")
    head = (START[0], START[1] + 80.0 * DT)
    if not _pt_near(c[0], head):
        return f"head at frame 1 {c[0]} != {head}"
    lead = head
    for i in range(1, 8):
        ex = (START[0] + (lead[0] - START[0]) * K_FOLLOW,
              START[1] + (lead[1] - START[1]) * K_FOLLOW)
        if not _pt_near(c[i], ex):
            return f"ball {i} at frame 1 {c[i]} != {ex}"
        lead = ex
    return True


def _spawn_at_last(t):
    prev_n = 8
    for s in t.samples:
        c = s.values["centers"]
        if len(c) == prev_n + 1 and not _pt_near(c[-1], c[-2], 1e-9):
            return f"frame {s.frame}: new ball at {c[-1]}, last was at {c[-2]}"
        prev_n = len(c)
    return True


def _inside(t):
    for s in t.samples:
        for (x, y) in s.values["centers"]:
            if not (-TOL <= x <= W + TOL and -TOL <= y <= H + TOL):
                return f"frame {s.frame}: center ({x}, {y}) outside game_view"
    return True


def _angle_matches(t):
    for s in t.samples:
        d = (s.values["head_angle"] - s.values["angulo"]) % 360.0
        if min(d, 360.0 - d) > 1e-5:
            return f"frame {s.frame}: head.angle {s.values['head_angle']} vs st.angulo {s.values['angulo']}"
    return True


def _angulo_integrates(t):
    prev = 90.0
    for s in t.samples:
        if not _near(s.values["angulo"] - prev, s.values["giro"] * DT, 1e-6):
            return f"frame {s.frame}: d(angulo) {s.values['angulo'] - prev} != giro*dt"
        prev = s.values["angulo"]
    return True


def _giro_step(t):
    prev = 0.0
    for s in t.samples:
        g = s.values["giro"]
        options = [prev + (alvo - prev) * K_GIRO for alvo in (220.0, 0.0, -220.0)]
        if not any(_near(g, o, 1e-6) for o in options):
            return f"frame {s.frame}: giro {g} is no chase step from {prev}"
        prev = g
    return True


def _vel_step(t):
    prev = 80.0
    for s in t.samples:
        v = s.values["vel"]
        options = [_clampv(prev + k * 260.0 * DT, 80.0, 380.0) for k in (-1, 0, 1)]
        if not any(_near(v, o, 1e-6) for o in options):
            return f"frame {s.frame}: velocidade {v} is no step from {prev}"
        prev = v
    return True


def _idle_line(t):
    for s in t.samples:
        x, y = s.values["head"]
        want = min(H, START[1] + 80.0 * s.frame * DT)
        if not (_near(x, 500.0, 1e-6) and _near(y, want, 1e-5)):
            return f"frame {s.frame}: head ({x}, {y}) != (500, {want})"
    return True


def _idle_ordered(t):
    for s in t.samples:
        c = s.values["centers"]
        for i in range(1, len(c)):
            if not _near(c[i][0], 500.0, 1e-6):
                return f"frame {s.frame}: ball {i} left x=500 ({c[i][0]})"
            if c[i][1] > c[i - 1][1] + 1e-9:
                return f"frame {s.frame}: ball {i} above the one in front"
    return True


def _turn_sign(sign):
    def check(t):
        prev = 90.0
        for s in t.samples:
            g, a = s.values["giro"], s.values["angulo"]
            if sign * g < -1e-9:
                return f"frame {s.frame}: giro {g} has the wrong sign"
            if sign * (a - prev) < -1e-9:
                return f"frame {s.frame}: angulo moved backwards"
            prev = a
        if sign * (t.end("angulo") - 90.0) <= 1.0:
            return f"angulo ended at {t.end('angulo')}, expected a clear turn"
        return True
    return custom(check)


def _giro_decays_after_release(t):
    rel = t.input_frame("key", 1)
    prev = None
    for f, _tm, g in t.series("giro"):
        if f < rel:
            continue
        if prev is not None and abs(g) > abs(prev) + 1e-9:
            return f"frame {f}: |giro| grew after release"
        prev = g
    if abs(prev) >= 1.0:
        return f"giro still {prev} two seconds after release"
    return True


# --- farejador helpers ------------------------------------------------------------------
FAR_START = (80.0, 80.0)
FAR_SPEED = 150.0
FAR_STEP = FAR_SPEED * DT          # 2.5 units per frame


def _dist(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _approach_pt(c, tgt):
    """approach(c, tgt, 150) with dt = 1/60: straight line, 2.5 per frame, exact landing."""
    d = _dist(c, tgt)
    if d <= FAR_STEP:
        return tgt
    return (c[0] + (tgt[0] - c[0]) / d * FAR_STEP, c[1] + (tgt[1] - c[1]) / d * FAR_STEP)


def _far_frame1(t):
    h = t.at_frame(1, "head")
    ex = _approach_pt(FAR_START, h)
    got = t.at_frame(1, "far")
    if not _pt_near(got, ex, 1e-6):
        return f"farejador at frame 1 {got} != one step from (80, 80) towards head {h}: {ex}"
    return True


def _far_law(t):
    prev = FAR_START
    for s in t.samples:
        h, f = s.values["head"], s.values["far"]
        ex = _approach_pt(prev, h)
        # at a distance of exactly one step both readings of "menos que um passo" give the target
        if not _pt_near(f, ex, 1e-6):
            return f"frame {s.frame}: farejador {f} != approach({prev}, head {h}, 150) = {ex}"
        prev = f
    return True


def _far_step_bound(t):
    prev = FAR_START
    for s in t.samples:
        f = s.values["far"]
        if _dist(prev, f) > FAR_STEP + 1e-9:
            return f"frame {s.frame}: farejador stepped {_dist(prev, f)} > 2.5"
        prev = f
    return True


def _far_no_overshoot(t):
    prev = FAR_START
    for s in t.samples:
        h, f = s.values["head"], s.values["far"]
        to_h = (h[0] - prev[0], h[1] - prev[1])
        step = (f[0] - prev[0], f[1] - prev[1])
        cross = to_h[0] * step[1] - to_h[1] * step[0]
        if abs(cross) > 1e-6 * max(1.0, math.hypot(*to_h)):
            return f"frame {s.frame}: step {step} is not along the line to the head {to_h}"
        if step[0] * (h[0] - f[0]) + step[1] * (h[1] - f[1]) < -1e-9:
            return f"frame {s.frame}: farejador {f} passed the head {h}"
        if _dist(f, h) > _dist(prev, h) + 1e-9:
            return f"frame {s.frame}: farejador got farther from this frame's head"
        prev = f
    return True


def _far_gap_growth(t):
    prev_f, prev_h = FAR_START, START
    for s in t.samples:
        h, f = s.values["head"], s.values["far"]
        gap, prev_gap = _dist(f, h), _dist(prev_f, prev_h)
        if gap > 0.0 and gap > prev_gap + _dist(prev_h, h) - FAR_STEP + 1e-6:
            return (f"frame {s.frame}: gap {gap} grew more than head step {_dist(prev_h, h)} - 2.5 "
                    f"from {prev_gap}")
        prev_f, prev_h = f, h
    return True


def _far_catch(t):
    first = next((s for s in t.samples if s.values["far"] == s.values["head"]), None)
    if first is None:
        return "farejador never landed exactly (==) on the head"
    if not 308 <= first.frame <= 310:
        return f"first exact landing at frame {first.frame}, model says 309"
    if first.values["far"] != (500.0, 700.0):
        return f"landed at {first.values['far']}, expected the pinned head (500, 700)"
    return True


def _far_stays_on(t):
    on = False
    for s in t.samples:
        if s.values["far"] == s.values["head"]:
            on = True
        elif on:
            return f"frame {s.frame}: farejador left the head ({s.values['far']} vs {s.values['head']})"
    return True if on else "farejador never caught the head"


def _far_escape(t):
    press = t.input_frame("key", 0)
    before = t.at_frame(press - 1, "far"), t.at_frame(press - 1, "head")
    if before[0] != before[1]:
        return f"frame {press - 1}: farejador {before[0]} not on the head {before[1]} before the keys"
    sep = next((s for s in t.samples if s.frame >= press and s.values["far"] != s.values["head"]), None)
    if sep is None:
        return "the head never got away from the farejador"
    if sep.values["vel"] <= FAR_SPEED:
        return f"frame {sep.frame}: separated while velocidade {sep.values['vel']} <= 150"
    gaps = [_dist(s.values["far"], s.values["head"]) for s in t.samples if s.frame >= sep.frame]
    if max(gaps) < 50.0:
        return f"max gap {max(gaps)} < 50 (model ~127)"
    if t.end("far") != t.end("head"):
        return f"farejador {t.end('far')} did not re-land on the head {t.end('head')} by the end"
    return True


def _far_inside(t):
    for s in t.samples:
        x, y = s.values["far"]
        if not (-TOL <= x <= W + TOL and -TOL <= y <= H + TOL):
            return f"frame {s.frame}: farejador ({x}, {y}) outside game_view"
    return True


EXPECT = [
    # --- startup -----------------------------------------------------------
    Expect(id="E1", level="L0", cite="docs/pt/guide/index.html#mundo-grupos; snake_chain.py loop",
           text="Eight balls exist on frame 1: the script body adds 8 before the game starts.",
           check=at(1, "count", lambda n: n == 8), scenarios=("*",)),
    Expect(id="E2", level="L0", cite="docs/pt/guide/index.html#init (unidades); Regioes da tela",
           text="init(1000, 700) gives a game_view centred at (500, 350); the camera never moves.",
           check=always("view_center", lambda c: close(c, (500.0, 350.0), 1e-9)), scenarios=("*",)),
    Expect(id="E3", level="L1", cite="design/Scena Design.md#frame-order; #util-chase; #pose-move-by",
           text="Frame 1: the head moved 80*dt up from (500,350) and each follower chased its "
                "(already moved) leader once from (500,350) with rate 8.",
           check=custom(_frame1_cascade), scenarios=("idle", "up", "left", "right", "down_min")),
    Expect(id="E4", level="L0", cite="docs/pt/guide/index.html (Circle radius=)",
           text="Every ball keeps radius 16.",
           check=always("radii", lambda rs: all(r == 16.0 for r in rs)), scenarios=("*",)),
    Expect(id="E5", level="L0", cite="docs/pt/guide/index.html (.visual = material)",
           text="Every ball's .visual reads back as a Sphere (assumed: .visual returns the assigned material).",
           check=always("spheres", lambda b: b is True), scenarios=("idle",), guess=True),
    # --- timer growth ------------------------------------------------------
    Expect(id="E6", level="L0", cite="docs/pt/guide/index.html#agendar-timers (@every no modulo: comeca ja)",
           text="@every(1) adds one ball per game second: count == 8 + floor(clock.time) away from "
                "the boundary frames (timer starts at script time 0).",
           check=custom(_count_vs_time), scenarios=("*",)),
    Expect(id="E7", level="L0", cite="docs/pt/guide/index.html#agendar-timers",
           text="The count never drops and grows by at most one per frame.",
           check=custom(_count_steps), scenarios=("*",)),
    Expect(id="E8", level="L0", cite="docs/pt/guide/index.html#agendar-timers",
           text="Idle run of 300 frames (5 s) ends with 12 or 13 balls (8 + 4 or 5 firings).",
           check=at_end("count", lambda n: n in (12, 13)), scenarios=("idle",)),
    Expect(id="E9", level="L0", cite="docs/pt/guide/index.html#agendar-timers",
           text="At frame 30 (0.5 s) no timer has fired yet: 8 balls; at frame 90 (1.5 s): 9.",
           check=all_of(at(30, "count", lambda n: n == 8), at(90, "count", lambda n: n == 9)),
           scenarios=("idle",)),
    Expect(id="E10", level="L1", cite="docs/pt/guide/index.html (Point: center=<point> copia uma vez); "
                                      "design/Scena Design.md#frame-order (timers after update)",
           text="A new ball is born exactly at the current last ball's centre (copied, after this frame's update).",
           check=custom(_spawn_at_last), scenarios=("*",)),
    Expect(id="E11", level="L0", cite="docs/pt/guide/index.html#mundo-grupos (ordem de entrada)",
           text="group['bolas'][0] stays the first ball: the head is centers[0] (order = entry order).",
           check=custom(lambda t: all(s.values["head"] == s.values["centers"][0] for s in t.samples)
                        or "head probe differs from centers[0]"), scenarios=("*",)),
    # --- head motion ---------------------------------------------------------
    Expect(id="E12", level="L1", cite="docs/pt/guide/index.html#pose-move-by; #mover-confine",
           text="Each frame the head moves velocidade*dt along st.angulo (0 deg = +x, ccw), then its "
                "centre is clamped into game_view [0,1000]x[0,700].",
           check=custom(_head_step), scenarios=("*",)),
    Expect(id="E13", level="L1", cite="docs/pt/guide/index.html#pose-move-by",
           text="Idle: the head goes straight up at 80 u/s: x == 500, y == min(700, 350 + 80 t).",
           check=custom(_idle_line), scenarios=("idle",)),
    Expect(id="E14", level="L1", cite="docs/pt/guide/index.html#mover-confine (clamp by center)",
           text="Idle: after 300 frames the head rests clamped at (500, 700).",
           check=at_end("head", lambda h: close(h, (500.0, 700.0), 1e-6)), scenarios=("idle",)),
    Expect(id="E15", level="L2", cite="docs/pt/guide/index.html#mover-confine; #util-chase (sem passar do alvo)",
           text="Every ball centre stays inside game_view (head clamped; followers are convex mixes). Slop 1e-6.",
           check=custom(_inside), scenarios=("*",)),
    Expect(id="E16", level="L1", cite="Pose .angle (le / escreve)",
           text="The head's .angle equals st.angulo modulo 360 every frame (assumed .angle may normalise).",
           check=custom(_angle_matches), scenarios=("*",)),
    # --- followers ------------------------------------------------------------
    Expect(id="E17", level="L1", cite="docs/pt/guide/index.html#util-chase (lerp(c, t, 1-exp(-rate*dt)))",
           text="Each follower i moves to prev_i + (leader_now - prev_i)*(1-exp(-8 dt)), leader already "
                "moved this frame.",
           check=custom(_followers), scenarios=("*",)),
    Expect(id="E18", level="L2", cite="docs/pt/guide/index.html#util-chase",
           text="Idle: followers stay on x=500 and each is never above the ball in front.",
           check=custom(_idle_ordered), scenarios=("idle",)),
    Expect(id="E19", level="L1", cite="docs/pt/guide/index.html#util-chase (a cada 1/rate s cai ~1/3)",
           text="Idle: ~37 frames after the head stops at y=700, follower 1 is within 1 unit of it.",
           check=at_end("centers", lambda c: c[1][1] > 699.0), scenarios=("idle",)),
    # --- steering and speed ----------------------------------------------------
    Expect(id="E20", level="L0", cite="docs/pt/guide/index.html#util-chase (rate e alvo iguais: nao muda)",
           text="With no key pressed giro stays 0, angulo 90 and velocidade 80.",
           check=all_of(always("giro", lambda g: g == 0.0), always("angulo", lambda a: a == 90.0),
                        always("vel", lambda v: v == 80.0)), scenarios=("idle",)),
    Expect(id="E21", level="L1", cite="docs/pt/guide/index.html#util-chase",
           text="Each frame giro is one chase step (rate 5) towards one of 220, 0 or -220.",
           check=custom(_giro_step), scenarios=("*",)),
    Expect(id="E22", level="L1", cite="docs/pt/guide/index.html#frame (clock.dt)",
           text="angulo grows by exactly giro*dt each frame.",
           check=custom(_angulo_integrates), scenarios=("*",)),
    Expect(id="E23", level="L1", cite="docs/pt/guide/index.html#frame-teclado",
           text="Each frame velocidade changes by -260dt, 0 or +260dt, clamped to [80, 380].",
           check=all_of(custom(_vel_step), always("vel", lambda v: 80.0 <= v <= 380.0)),
           scenarios=("*",)),
] + [
    Expect(id=f"E24{name}", level="L1",
           cite="docs/pt/guide/index.html#frame-teclado (keyp True enquanto segurada); "
                "design/Scena Design.md#frame-order (input before update)",
           text=f"{name}: replaying keyp from the delivered key frames (held from press frame up to, not "
                "including, the release frame) reproduces giro, angulo and velocidade exactly.",
           check=_model(evs), scenarios=(name,))
    for name, evs in KEY_EVENTS.items()
] + [
    Expect(id="E25", level="L0", cite="docs/pt/guide/index.html#frame-teclado",
           text="Holding UP for 120 frames saturates velocidade at 380.",
           check=at_end("vel", lambda v: v == 380.0), scenarios=("up_max",)),
    Expect(id="E26", level="L0", cite="docs/pt/guide/index.html#frame-teclado",
           text="Holding DOWN at minimum speed keeps velocidade at 80.",
           check=always("vel", lambda v: v == 80.0), scenarios=("down_min",)),
    Expect(id="E27", level="L1", cite="docs/pt/guide/index.html#frame-teclado",
           text="Holding UP 30 frames leaves velocidade at 80 + 30*260/60 = 210 (or one frame more, 214.33), "
                "and it stays there.",
           check=all_of(at_end("vel", lambda v: _near(v, 210.0, 1e-6) or _near(v, 80 + 31 * 260 / 60, 1e-6)),
                        custom(lambda t: all(v == t.end("vel") for f, _tm, v in t.series("vel")
                                             if f >= t.input_frame("key", 1)) or "vel moved after release")),
           scenarios=("up",)),
    Expect(id="E28", level="L1", cite="docs/pt/guide/index.html#frame-teclado; #util-chase",
           text="LEFT turns counter-clockwise: giro >= 0, angulo never decreases and ends clearly above 90.",
           check=_turn_sign(+1), scenarios=("left",)),
    Expect(id="E29", level="L1", cite="docs/pt/guide/index.html#frame-teclado; #util-chase",
           text="RIGHT turns clockwise: giro <= 0, angulo never increases and ends clearly below 90.",
           check=_turn_sign(-1), scenarios=("right",)),
    Expect(id="E30", level="L1", cite="docs/pt/guide/index.html#util-chase",
           text="After LEFT is released giro decays monotonically and is below 1 deg/s two seconds later "
                "(220*exp(-10) ~ 0.01).",
           check=custom(_giro_decays_after_release), scenarios=("left",)),
    Expect(id="E31", level="L1", cite="docs/pt/guide/index.html#frame-teclado (keyp('A') ignora outra tecla comum)",
           text="While LEFT and RIGHT are both held the target is 0, so |giro| never grows in that window.",
           check=custom(lambda t: (lambda a, b: all(
               abs(t.at_frame(f, "giro")) <= abs(t.at_frame(f - 1, "giro")) + 1e-9
               for f in range(max(a, 2), b)) or "giro grew while both keys were held")(
                   t.input_frame("key", 1), t.input_frame("key", 2))),
           scenarios=("left_right",)),
    Expect(id="E32", level="L1", cite="harness: fixed dt = 1/60",
           text="clock.time after frame n is n/60.",
           check=custom(lambda t: all(_near(s.values["time"], s.frame * DT, 1e-6) for s in t.samples)
                        or "clock.time drifted from frame/60"), scenarios=("*",)),
    # --- farejador (approach at 150 u/s towards the head) ---------------------------------
    Expect(id="E33", level="L1", cite="docs/pt/guide/index.html#util-approach; #pose-move-to; "
                                      "snake_chain.py (Circle center=(80, 80); approach after the chain moved)",
           text="The farejador starts at (80, 80): on frame 1 it is exactly one 2.5-unit step (150*dt) from "
                "(80, 80) along the line to the head's frame-1 position.",
           check=custom(_far_frame1), scenarios=("*",)),
    Expect(id="E34", level="L1", cite="docs/pt/guide/index.html#util-approach (anda speed*dt em linha reta; "
                                      "quando falta menos que um passo, devolve o proprio alvo)",
           text="Every frame farejador_n == approach(farejador_{n-1}, head_n, 150) with dt=1/60, head_n being the "
                "head after this frame's move and confine (the call comes after the chain moved).",
           check=custom(_far_law), scenarios=("*",)),
    Expect(id="E35", level="L2", cite="docs/pt/guide/index.html#util-approach (sempre na mesma velocidade)",
           text="The farejador never moves more than 150*dt = 2.5 units in one frame (slop 1e-9).",
           check=custom(_far_step_bound), scenarios=("*",)),
    Expect(id="E36", level="L2", cite="docs/pt/guide/index.html#util-approach (linha reta; nunca passa do alvo)",
           text="Each farejador step lies on the segment towards this frame's head: collinear (slop 1e-6 "
                "relative), never past the head, never farther from it than before the step.",
           check=custom(_far_no_overshoot), scenarios=("*",)),
    Expect(id="E37", level="L1", cite="docs/pt/guide/index.html#util-approach; #pose-move-by; #mover-confine",
           text="Idle: 300 frames are not enough to catch the head (it closes at 150 against a head going "
                "up at 80, then pinned at (500, 700)): it walks exactly 2.5 every frame and ends ~20.79 short.",
           check=all_of(custom(lambda t: (lambda d: abs(d - 20.7902) <= 0.01 or f"end gap {d} != ~20.79")(
                            _dist(t.end("far"), t.end("head")))),
                        custom(lambda t: all(abs(_dist(a.values["far"], b.values["far"]) - FAR_STEP) <= 1e-6
                                             for a, b in zip(t.samples, t.samples[1:]))
                               or "a farejador step in idle was not 2.5")),
           scenarios=("idle",)),
    Expect(id="E38", level="L0", cite="docs/pt/guide/index.html#util-approach (a chegada e exata, da para testar com ==)",
           text="The farejador first lands on the head with == at frame 309 (308-310 allowed) at the pinned "
                "head (500, 700).",
           check=custom(_far_catch), scenarios=("catch",)),
    Expect(id="E39", level="L0", cite="docs/pt/guide/index.html#util-approach (nunca passa do alvo nem treme em volta)",
           text="Once on the head, the farejador stays exactly (==) on it while the head moves under 2.5 per "
                "frame (idle head pinned; no jitter around the target).",
           check=custom(_far_stays_on), scenarios=("catch",)),
    Expect(id="E40", level="L1", cite="docs/pt/guide/index.html#util-approach; #frame-teclado",
           text="Escape: the farejador is on the head before the keys; the head gets away only once velocidade "
                "exceeds 150, the gap opens past 50 (model ~127), and after the head slows along the top wall "
                "the farejador lands on it again (== at the end).",
           check=custom(_far_escape), scenarios=("escape",)),
    Expect(id="E41", level="L2", cite="docs/pt/guide/index.html#util-approach (cada chamada anda speed*dt)",
           text="On a frame where the farejador is not on the head, the gap grows by at most the head's step "
                "minus 2.5 (triangle inequality on one approach step), so it can grow only while the head "
                "moves faster than 150 u/s. Slop 1e-6.",
           check=custom(_far_gap_growth), scenarios=("*",)),
    Expect(id="E42", level="L0", cite="docs/pt/guide/index.html#mundo-grupos; snake_chain.py (no group= for farejador)",
           text="The farejador is not a member of group['bolas'] and keeps radius 10.",
           check=all_of(always("far_in_bolas", lambda b: not b), always("far_r", lambda r: r == 10.0)),
           scenarios=("*",)),
    Expect(id="E43", level="L2", cite="docs/pt/guide/index.html#util-approach (linha reta); #mover-confine",
           text="The farejador centre stays inside game_view: it starts inside and each step is a convex move "
                "towards a confined head. Slop 1e-6.",
           check=custom(_far_inside), scenarios=("*",)),
]
