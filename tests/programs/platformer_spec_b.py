"""Spec B for tests/programs/platformer.py, written from the docs only.

Geometry notes used below (all derived from the program's constants):
- ground: Rect center (550, 40), height 40 -> top at y = 60.
- walls: inner faces at x = 42 (left) and x = 1058 (right).
- elevator: x = 230, width 120 (x 170..290), height 20; startup calls
  iniciar_posicoes(), which puts it at y = 290 moving down at 80/s;
  update() reverses it below y = 90 and above y = 700.
- ramp (880, 160) 200x24 at 22 deg floats above the ground: its lowest
  corner is near (791.8, 111.4), so a ~70-tall hero walking on the ground
  cannot pass under it.
- dt = 1/60: hero speed 250 -> 4.1667 per frame; gravity 900 -> 15/frame.
"""
from program_support import (Scenario, Expect, wait, wait_s, click_widget, click,
    key, key_down, key_up, move, scroll, set_cell, always, never, at, at_end,
    eventually, steady, all_of, custom, close)
import math

FILES_READ = [
    "tests/programs/platformer.py",
    "tests/programs/spec_agent_prompt.txt",
    "design/Scena Design.md#frame-order",
    "docs/pt/guide/index.html#init",
    "docs/pt/guide/index.html#globais",
    "docs/pt/guide/index.html#reativo",
    "docs/pt/guide/index.html#frame-clock",
    "docs/pt/guide/index.html#frame-teclado",
    "docs/pt/guide/index.html#pose-move-by",
    "docs/pt/guide/index.html#pose-rotate-by",
    "docs/pt/guide/index.html#agendar-timers",
    "docs/pt/guide/index.html#agendar-ready",
    "docs/pt/guide/index.html#agendar-recently",
    "docs/pt/guide/index.html#agendar-fim",
    "docs/pt/guide/index.html#reagir-when",
    "docs/pt/guide/index.html#colisao-collide",
    "docs/pt/guide/index.html#colisao-info",
    "docs/pt/guide/index.html#colisao-resolve",
    "docs/pt/guide/index.html#colisao-touching",
    "docs/pt/guide/index.html#spr-clip",
    "docs/pt/guide/index.html#spr-plat",
    "docs/pt/guide/index.html#spr-flip",
    "docs/pt/guide/index.html#spr-tilt",
    "docs/pt/guide/index.html#spr-hit",
    "docs/pt/guide/index.html#mundo-grupos",
    "docs/pt/guide/index.html (Todo objeto na tela: active / destroy)",
    "docs/pt/guide/index.html#geo-vec2 (vec_from_angle)",
    "examples/media (file names only)",
]

DT = 1.0 / 60.0
HERO_STEP = 250.0 * DT
SHOT_VX = 420.0 * math.cos(math.radians(30))   # 363.7307
SHOT_VY_AFTER_FRAME = 420.0 * math.sin(math.radians(30)) - 900.0 * DT  # 195
SHOT_DX = 28 + SHOT_VX * DT    # 34.062
SHOT_DY = 10 + SHOT_VY_AFTER_FRAME * DT   # 13.25
GROUND_TOP = 60.0
FIM = "Fim de jogo — estrelas {}  (R para recomeçar)"
NORMAL = "Estrelas {}   Vidas {}"


# --- probes ------------------------------------------------------------------
def _count(p, name):
    return sum(1 for _ in p.group[name])


def _clip(p):
    for c in ("parado", "correndo", "pulando"):
        if p.heroi.showing(c):
            return c
    return None


PROBES = {
    "hero_c": lambda p: (p.heroi.center.x, p.heroi.center.y),
    "hero_x": lambda p: p.heroi.center.x,
    "hero_bottom": lambda p: p.heroi.hitbox.box.bottom,
    "hero_ground": lambda p: "bottom" in p.heroi.touching_sides,
    "hero_flip": lambda p: p.heroi.flip_x,
    "hero_angle": lambda p: p.heroi.angle,
    "hero_active": lambda p: p.heroi.active,
    "hero_ferido": lambda p: p.heroi.tagged("ferido"),
    "hero_clip": _clip,
    "estrelas": lambda p: p.st.estrelas,
    "vidas": lambda p: p.st.vidas,
    "placar": lambda p: p.placar.text,
    "n_estrela": lambda p: _count(p, "estrela"),
    "n_inimigo": lambda p: _count(p, "inimigo"),
    "n_tchau": lambda p: _count(p, "tchau"),
    "n_bola": lambda p: _count(p, "bola"),
    "stars": lambda p: tuple(sorted((s.center.x, s.center.y)
                                    for s in p.group["estrela"])),
    "robots": lambda p: tuple(sorted((r.center.x, r.center.y)
                                     for r in p.group["inimigo"])),
    "robot_flips_by_y": lambda p: tuple(
        r.flip_x for r in sorted(p.group["inimigo"], key=lambda r: r.center.y)),
    "robot_low_x": lambda p: min(p.group["inimigo"],
                                 key=lambda r: r.center.y).center.x,
    "balls": lambda p: tuple((b.center.x, b.center.y, b.vel.x, b.vel.y)
                             for b in p.group["bola"]),
    "elev_x": lambda p: p.elevador.center.x,
    "elev_y": lambda p: p.elevador.center.y,
    "elev_vy": lambda p: p.elevador.vel.y,
    "roda_angle": lambda p: p.roda.angle,
}


# --- scenarios ---------------------------------------------------------------
SCENARIOS = {
    # nothing pressed
    "idle": Scenario(params={}, seed=0, steps=[wait(240)]),
    # RIGHT for 52 frames: hero ends near x = 336, clear of the elevator column
    "walk_right": Scenario(params={}, seed=0, steps=[
        wait(30), key("RIGHT", frames=52), wait(40)]),
    "walk_left": Scenario(params={}, seed=0, steps=[
        wait(60), key("LEFT", frames=8), wait(30)]),
    "jump": Scenario(params={}, seed=0, steps=[
        wait(60), key("UP", frames=1), wait(120)]),
    "hold_up": Scenario(params={}, seed=0, steps=[
        wait(60), key("UP", frames=120), wait(30)]),
    "shoot": Scenario(params={}, seed=0, steps=[
        wait(60), key("SPACE", frames=60), wait(330)]),
    "shoot_left": Scenario(params={}, seed=0, steps=[
        wait(60), key("LEFT", frames=2), wait(5), key("SPACE", frames=1), wait(20)]),
    # long run right: overtakes robot 1 on the ground, stops at the ramp
    "run_right_long": Scenario(params={}, seed=0, steps=[
        wait(30), key("RIGHT", frames=360), wait(30)]),
    "gameover": Scenario(params={}, seed=0, steps=[
        set_cell("st.vidas", 1), wait(30), key("RIGHT", frames=200), wait(60),
        key("R", frames=1), wait(60)]),
    "restart_hold": Scenario(params={}, seed=0, steps=[
        wait(200), key("LEFT", frames=4), wait(36), key("R", frames=30), wait(30)]),
    "letter_A": Scenario(params={}, seed=0, steps=[
        wait(60), key("A", frames=30), wait(10)]),
    "score_cell": Scenario(params={}, seed=0, steps=[
        wait(10), set_cell("st.estrelas", 7), wait(10)]),
}

NO_R = ("idle", "walk_right", "walk_left", "jump", "hold_up", "shoot",
        "shoot_left", "run_right_long", "letter_A")


# --- custom check helpers ----------------------------------------------------
def _key_frame(t, nth=0):
    return t.input_frame("key", nth)


def _walk_dx(expected, tol):
    def fn(t):
        f = _key_frame(t)
        x0 = t.at_frame(f - 1, "hero_x")
        x1 = t.end("hero_x")
        if abs((x1 - x0) - expected) <= tol:
            return True
        return f"hero moved {x1 - x0:.3f}, expected {expected:.3f} +- {tol}"
    return fn


def _placar_matches(t):
    for s in t.samples:
        v, e, txt = s.values["vidas"], s.values["estrelas"], s.values["placar"]
        if v <= 0:
            want = FIM.format(int(e))
        else:
            want = NORMAL.format(int(e), int(v))
        if txt != want:
            return f"frame {s.frame}: placar {txt!r}, expected {want!r}"
    return True


def _stars_conserved(t):
    for s in t.samples:
        if s.values["estrelas"] + s.values["n_estrela"] != 4:
            return (f"frame {s.frame}: estrelas {s.values['estrelas']} + "
                    f"stars left {s.values['n_estrela']} != 4")
    return True


def _non_increasing(probe):
    def fn(t):
        vals = t.series(probe)
        for (f0, _, a), (f1, _, b) in zip(vals, vals[1:]):
            if b > a:
                return f"{probe} rose from {a} to {b} at frame {f1}"
        return True
    return fn


def _decrements(t):
    vals = t.series("vidas")
    return [f1 for (f0, _, a), (f1, _, b) in zip(vals, vals[1:]) if b < a]


def _life_spacing(t):
    d = _decrements(t)
    for a, b in zip(d, d[1:]):
        if b - a < 58:
            return f"lives lost at frames {a} and {b}, less than 1 s apart"
    return True


def _ferido_window(t):
    d = _decrements(t)
    if not d:
        return "no life was lost"
    first = d[0]
    if not t.at_frame(first, "hero_ferido"):
        return f"hero not tagged 'ferido' at the hit frame {first}"
    later = [x for x in d if first < x <= first + 64]
    if not later:
        last = t.samples[-1].frame
        if first + 64 <= last and t.at_frame(first + 64, "hero_ferido"):
            return "hero still tagged 'ferido' 64 frames after the hit"
    return True


def _peak_rise(lo, hi):
    def fn(t):
        f = _key_frame(t)
        base = t.at_frame(f - 1, "hero_bottom")
        peak = max(v for (fr, _, v) in t.series("hero_bottom") if fr >= f)
        rise = peak - base
        if lo <= rise <= hi:
            return True
        return f"jump rise {rise:.2f} outside [{lo}, {hi}]"
    return fn


def _takeoffs(expected):
    def fn(t):
        vals = [(fr, v) for (fr, _, v) in t.series("hero_ground") if fr >= 50]
        n = sum(1 for (_, a), (_, b) in zip(vals, vals[1:]) if a and not b)
        return True if n == expected else f"{n} take-offs, expected {expected}"
    return fn


def _first_ball_frame(t):
    for s in t.samples:
        if s.values["n_bola"] >= 1:
            return s.frame
    return None


def _first_ball(sign):
    def fn(t):
        f = _first_ball_frame(t)
        if f is None:
            return "no ball was fired"
        balls = t.at_frame(f, "balls")
        if len(balls) != 1:
            return f"{len(balls)} balls on the shot frame"
        bx, by, vx, vy = balls[0]
        hx, hy = t.at_frame(f, "hero_c")
        if not close((bx - hx, by - hy), (sign * SHOT_DX, SHOT_DY), 0.6):
            return f"ball offset {(bx - hx, by - hy)} from hero"
        if not close((vx, vy), (sign * SHOT_VX, SHOT_VY_AFTER_FRAME), 0.02):
            return f"ball velocity {(vx, vy)}"
        return True
    return fn


def _shot_count(t):
    f = _key_frame(t)
    if _first_ball_frame(t) != f:
        return f"first ball at {_first_ball_frame(t)}, SPACE delivered at {f}"
    window = [v for (fr, _, v) in t.series("n_bola") if f <= fr <= f + 59]
    if max(window) != 4:
        return f"max balls during the 60 held frames = {max(window)}, expected 4"
    if t.at_frame(f + 59, "n_bola") != 4:
        return f"{t.at_frame(f + 59, 'n_bola')} balls at the last held frame"
    return True


def _ball_bounds(t):
    for s in t.samples:
        for (x, y, _, _) in s.values["balls"]:
            if not (46 <= x <= 1054) or y < 64:
                return f"frame {s.frame}: ball at {(x, y)} outside the walls/ground"
    return True


def _robot_bounds(t):
    for s in t.samples:
        for (x, y) in s.values["robots"]:
            if not (42 <= x <= 1058) or y < GROUND_TOP:
                return f"frame {s.frame}: robot at {(x, y)} outside"
    return True


def _hero_bounds(t):
    for s in t.samples:
        x = s.values["hero_x"]
        b = s.values["hero_bottom"]
        if not (42 <= x <= 1058):
            return f"frame {s.frame}: hero x {x} outside the walls"
        if b < GROUND_TOP - 1.0:
            return f"frame {s.frame}: hero hitbox bottom {b} below the ground"
    return True


def _elevator_first_leg(t):
    for (fr, _, y) in t.series("elev_y"):
        if fr > 148:
            break
        want = 290.0 - 80.0 * DT * fr
        if abs(y - want) > 0.05:
            return f"frame {fr}: elevator y {y}, expected {want:.3f}"
    return True


def _roda(t):
    for (fr, _, a) in t.series("roda_angle"):
        if abs(a - 2.5 * fr) > 1e-6 * fr + 1e-6:
            return f"frame {fr}: roda angle {a}, expected {2.5 * fr}"
    return True


def _gameover_frames(t):
    over = None
    for s in t.samples:
        if over is None and s.values["vidas"] <= 0:
            over = s.frame
        elif over is not None and s.values["vidas"] == 3:
            return over, s.frame
    return over, None


def _gameover_state(t):
    over, reset = _gameover_frames(t)
    if over is None:
        return "lives never reached 0"
    if t.at_frame(over, "hero_active"):
        return "hero still active on the game-over frame"
    if t.at_frame(over, "placar") != FIM.format(0):
        return f"placar {t.at_frame(over, 'placar')!r} on game over"
    end = reset if reset is not None else t.samples[-1].frame + 1
    for fr in range(over, end):
        if t.at_frame(fr, "hero_active"):
            return f"hero active again at frame {fr} before R"
    return True


def _gameover_frozen(t):
    over, reset = _gameover_frames(t)
    if over is None or reset is None:
        return "no game over / reset pair"
    y0 = t.at_frame(over + 1, "elev_y")
    r0 = t.at_frame(over + 1, "robots")
    for fr in range(over + 1, reset):
        if abs(t.at_frame(fr, "elev_y") - y0) > 1e-9:
            return f"elevator moved at frame {fr} while the game was over"
        r = t.at_frame(fr, "robots")
        if len(r) != len(r0) or not all(close(a, b, 0.5) for a, b in zip(r, r0)):
            return f"robots moved at frame {fr} while the game was over"
    return True


def _reset_state(r, flip_before=None):
    def fn(t):
        fr = r(t)
        if fr is None:
            return "reset frame not found"
        v = lambda name: t.at_frame(fr, name)
        checks = [
            ("vidas", v("vidas") == 3),
            ("estrelas", v("estrelas") == 0),
            ("hero_active", bool(v("hero_active"))),
            ("hero_c", close(v("hero_c"), (120.0, 120.0), 1e-6)),
            ("hero_flip", not v("hero_flip")),
            ("n_inimigo", v("n_inimigo") == 3),
            ("n_estrela", v("n_estrela") == 4),
            ("n_bola", v("n_bola") == 0),
            ("n_tchau", v("n_tchau") == 0),
            ("elev_y", close(v("elev_y"), 290.0, 1e-6)),
            ("elev_vy", close(v("elev_vy"), -80.0, 1e-9)),
            ("placar", v("placar") == NORMAL.format(0, 3)),
        ]
        bad = [n for n, ok in checks if not ok]
        if flip_before is not None and t.at_frame(fr - 1, "hero_flip") != flip_before:
            bad.append("hero_flip before reset")
        return True if not bad else f"frame {fr}: wrong after R: {bad}"
    return fn


def _gameover_reset_frame(t):
    return _gameover_frames(t)[1]


def _restart_frame(t):
    for (fr, _, y) in t.series("elev_y"):
        if fr > 200 and abs(y - 290.0) < 1e-6:
            return fr
    return None


def _restart_once(t):
    fr = _restart_frame(t)
    if fr is None:
        return "elevator never reset to y = 290"
    want = 290.0 - 80.0 * DT * 29
    y = t.at_frame(fr + 29, "elev_y")
    if abs(y - want) > 0.1:
        return f"elevator y {y} 29 frames after R (held), expected {want:.2f}: R re-fired?"
    return True


def _running_clip(t):
    f = _key_frame(t)
    for fr in range(f + 2, f + 49):
        c = t.at_frame(fr, "hero_clip")
        if c != "correndo":
            return f"frame {fr}: clip {c!r} while running right"
    return True


# --- expectations ------------------------------------------------------------
G = "docs/pt/guide/index.html"
EXPECT = [
    # startup
    Expect(id="E1", level="L0", cite=G + "#mundo-grupos (group[...] count)",
           text="After startup there are 4 stars, 3 robots, no balls and no 'tchau' bodies.",
           check=all_of(at(1, "n_estrela", lambda v: v == 4),
                        at(1, "n_inimigo", lambda v: v == 3),
                        at(1, "n_bola", lambda v: v == 0),
                        at(1, "n_tchau", lambda v: v == 0)),
           scenarios=("idle",)),
    Expect(id="E2", level="L0", cite=G + "#desenhar-sprite (construct-to-place center=)",
           text="Stars sit at (300,250), (520,250), (780,370), (920,240) and do not move.",
           check=always("stars", lambda v: close(
               v, ((300.0, 250.0), (520.0, 250.0), (780.0, 370.0), (920.0, 240.0)), 1e-6)),
           scenarios=("idle",)),
    Expect(id="E3", level="L0", cite=G + "#reativo-state (st)",
           text="st.estrelas starts at 0 and st.vidas at 3.",
           check=all_of(at(1, "estrelas", lambda v: v == 0), at(1, "vidas", lambda v: v == 3)),
           scenarios=("idle",)),
    Expect(id="E4", level="L0", cite=G + "#reativo-liga (@= follows its sources)",
           text="placar.text always equals the linked f-string of st (normal while vidas > 0, game-over text once vidas <= 0).",
           check=custom(_placar_matches), scenarios=("*",)),
    Expect(id="E5", level="L0", cite=G + "#colisao-collide (enter fires once; destroy)",
           text="Each collected star is destroyed and counted once: estrelas + stars left == 4 at every frame.",
           check=custom(_stars_conserved),
           scenarios=tuple(s for s in SCENARIOS if s != "score_cell")),
    Expect(id="E6", level="L0", cite=G + "#reagir-when (R handler is the only refill)",
           text="Without R, st.vidas never increases.",
           check=custom(_non_increasing("vidas")), scenarios=NO_R),
    Expect(id="E7", level="L0", cite=G + "#agendar-timers (e.after(1.0) clears 'ferido')",
           text="Two life losses are never less than 1 s apart (the 'ferido' tag guards for 1 s).",
           check=custom(_life_spacing), scenarios=("run_right_long", "gameover")),
    Expect(id="E8", level="L0", cite=G + "#colisao-collide (hero x robot overlap, no resolve between them)",
           text="Running right on the ground overtakes robot 1 (same lane, no resolve pair) so a life is lost within 300 frames.",
           check=eventually("vidas", lambda v: v <= 2, within=300),
           scenarios=("run_right_long",)),
    Expect(id="E9", level="L0", cite=G + "#colisao-collide + #mundo-grupos (tag/tagged)",
           text="On a hit the hero is tagged 'ferido' and the tag is gone ~1 s later (after(1.0, untag)).",
           check=custom(_ferido_window), scenarios=("run_right_long",)),
    # elevator
    Expect(id="E10", level="L1", cite=G + "#pose-move-by",
           text="The elevator never moves horizontally: x stays 230.",
           check=always("elev_x", lambda v: close(v, 230.0, 1e-6)), scenarios=("*",)),
    Expect(id="E11", level="L1", cite=G + "#pose-move-by + #frame-clock (dt)",
           text="From the startup reset (y=290, vel -80) the elevator descends 80/60 per frame: y(n) = 290 - 4n/3 for n <= 148.",
           check=custom(_elevator_first_leg), scenarios=("idle",)),
    Expect(id="E12", level="L2", cite="program update() bounds; " + G + "#pose-move-by",
           text="The elevator stays within one frame step of its limits [90, 700] (slop 80/60).",
           check=always("elev_y", lambda v: 90 - 80 * DT - 0.01 <= v <= 700 + 80 * DT + 0.01),
           scenarios=("*",)),
    Expect(id="E13", level="L2", cite="program update(); " + G + "#pose-move-by",
           text="The elevator turns around at the bottom (~frame 150): vel -80 at frame 100, +80 at frame 200, y in [153.5, 157.2] at frame 200 (float edge at exactly 90).",
           check=all_of(at(100, "elev_vy", lambda v: v == -80),
                        at(200, "elev_vy", lambda v: v == 80),
                        at(200, "elev_y", lambda v: 153.5 <= v <= 157.2)),
           scenarios=("idle",)),
    # wheel
    Expect(id="E14", level="L1", cite=G + "#pose-rotate-by (angle accumulates, no wrap)",
           text="roda.rotate_by(150*dt) every frame: roda.angle == 2.5 * frame (accumulating past 360).",
           check=custom(_roda), scenarios=("idle",)),
    # hero at rest
    Expect(id="E15", level="L2", cite=G + "#colisao-resolve (bounce=0 floor, stick) + #colisao-touching",
           text="Idle hero lands and stays grounded: from frame 60 'bottom' in touching_sides and hitbox bottom within 0.5 of y=60.",
           check=all_of(always("hero_ground", lambda v: bool(v), after=60),
                        always("hero_bottom", lambda v: abs(v - GROUND_TOP) <= 0.5, after=60)),
           scenarios=("idle",)),
    Expect(id="E16", level="L1", cite=G + "#pose-move-by (vel.x = 0 when no key)",
           text="With no input the hero never moves horizontally (x stays 120).",
           check=always("hero_x", lambda v: close(v, 120.0, 0.01)), scenarios=("idle",)),
    Expect(id="E17", level="L0", cite=G + "#spr-plat (play same clip = no-op)",
           text="A grounded, still hero shows the 'parado' clip, faces right and is active.",
           check=all_of(always("hero_clip", lambda v: v == "parado", after=60),
                        always("hero_flip", lambda v: not v),
                        always("hero_active", lambda v: bool(v))),
           scenarios=("idle",)),
    # walking
    Expect(id="E18", level="L1", cite=G + "#frame-teclado (keyp held) + #pose-move-by",
           text="RIGHT held 52 frames moves the hero 52*250/60 = 216.67 to the right (tol 1).",
           check=custom(_walk_dx(52 * HERO_STEP, 1.0)), scenarios=("walk_right",)),
    Expect(id="E19", level="L0", cite=G + "#spr-plat + #spr-flip",
           text="While running right the hero shows 'correndo' and faces right; 10+ frames after release it shows 'parado'.",
           check=all_of(
               custom(_running_clip),
               always("hero_flip", lambda v: not v),
               at_end("hero_clip", lambda v: v == "parado")),
           scenarios=("walk_right",)),
    Expect(id="E20", level="L1", cite=G + "#frame-teclado + #pose-move-by",
           text="LEFT held 8 frames moves the hero 8*250/60 = 33.33 to the left (tol 1).",
           check=custom(_walk_dx(-8 * HERO_STEP, 1.0)), scenarios=("walk_left",)),
    Expect(id="E21", level="L1", cite=G + "#spr-flip (flip_x rewrites angle to 180 - theta)",
           text="After walking left the hero keeps facing left (flip_x True) and its angle reads 180.",
           check=all_of(at_end("hero_flip", lambda v: bool(v)),
                        at_end("hero_angle", lambda v: close(v % 360, 180.0, 1e-6))),
           scenarios=("walk_left",)),
    Expect(id="E22", level="L0", cite="design/Scena Design.md#frame-order (one name per key, no aliases)",
           text="Holding 'A' does not move the hero: keyp('LEFT') has no 'A' alias (the program docstring's A/D/W/Z do nothing).",
           check=always("hero_x", lambda v: close(v, 120.0, 0.01)), scenarios=("letter_A",)),
    # jumping
    Expect(id="E23", level="L2", cite=G + "#agendar-recently (coyote + buffer re-apply vel.y=PULO)",
           text="A jump raises the hitbox bottom by 110..165: one 460 impulse gives ~121.4, and the coyote/buffer windows may re-apply PULO for up to ~5 frames (~152).",
           check=custom(_peak_rise(110.0, 165.0)), scenarios=("jump", "hold_up")),
    Expect(id="E24", level="L0", cite=G + "#spr-plat + #colisao-touching",
           text="15 frames after UP the hero is airborne and shows 'pulando'; by the end it is grounded again at y=60.",
           check=all_of(at(lambda t: _key_frame(t) + 15, "hero_ground", lambda v: not v),
                        at(lambda t: _key_frame(t) + 15, "hero_clip", lambda v: v == "pulando"),
                        at_end("hero_ground", lambda v: bool(v)),
                        at_end("hero_bottom", lambda v: abs(v - GROUND_TOP) <= 0.5)),
           scenarios=("jump",)),
    Expect(id="E25", level="L0", cite=G + "#frame-teclado (keyp.once only on the press frame)",
           text="Holding UP for 2 s gives exactly one take-off (keyp.once fires once per press).",
           check=custom(_takeoffs(1)), scenarios=("jump", "hold_up")),
    Expect(id="E26", level="L1", cite=G + "#pose-move-by",
           text="Jumping straight up does not change the hero's x.",
           check=always("hero_x", lambda v: close(v, 120.0, 0.01)), scenarios=("jump", "hold_up")),
    # shooting
    Expect(id="E27", level="L0", cite=G + "#agendar-ready (first call True, at most once per interval)",
           text="Holding SPACE 60 frames fires on the press frame and every 0.25 s: exactly 4 balls exist at the last held frame, never more.",
           check=custom(_shot_count), scenarios=("shoot",)),
    Expect(id="E28", level="L1", cite=G + "#geo-vec2 (vec_from_angle) + #pose-move-by",
           text="The first ball spawns at hero.center + (28, 10) with vel 420 at 30 deg, then moves one frame: offset ~(34.06, 13.25), vel ~(363.73, 195).",
           check=custom(_first_ball(1)), scenarios=("shoot",)),
    Expect(id="E29", level="L1", cite=G + "#spr-flip + #geo-vec2",
           text="Facing left, the shot goes at 150 deg from hero.center + (-28, 10): offset ~(-34.06, 13.25), vel ~(-363.73, 195).",
           check=custom(_first_ball(-1)), scenarios=("shoot_left",)),
    Expect(id="E30", level="L2", cite=G + "#colisao-resolve (bounce=0.7 vs plataforma/parede)",
           text="Balls stay inside the walls and above the ground (radius 8, slop 4 for one-frame contact).",
           check=custom(_ball_bounds), scenarios=("shoot", "shoot_left")),
    Expect(id="E31", level="L0", cite=G + "#agendar-timers (e.after) + #agendar-fim (dissolve_out on_done)",
           text="Every ball is gone ~4.4 s after its shot, and burned robots are destroyed: no balls and no 'tchau' at the end. Assumes e.after passes the entity to the 1-arg sumir(bola).",
           check=all_of(at_end("n_bola", lambda v: v == 0), at_end("n_tchau", lambda v: v == 0)),
           scenarios=("shoot",), guess=True),
    Expect(id="E32", level="L2", cite=G + "#colisao-collide (bola x inimigo)",
           text="Some ball of the 4-shot volley eventually hits a robot (estimated from the bounce trajectory), so fewer than 3 robots remain.",
           check=eventually("n_inimigo", lambda v: v < 3),
           scenarios=("shoot",), guess=True),
    # robots
    Expect(id="E33", level="L0", cite=G + "#spr-flip",
           text="At start robots face their walking direction: by height, (520,90) right, (420,230) left, (780,350) right.",
           check=at(1, "robot_flips_by_y", lambda v: tuple(bool(x) for x in v) == (False, True, False)),
           scenarios=("idle",)),
    Expect(id="E34", level="L1", cite=G + "#pose-move-by + #colisao-resolve (tangent kept on flat floor)",
           text="Robot 1 walks right at 55/s on the ground: x at frame 30 ~= 520 + 27.5 (tol 1).",
           check=at(30, "robot_low_x", lambda v: close(v, 547.5, 1.0)), scenarios=("idle",)),
    Expect(id="E35", level="L2", cite=G + "#colisao-resolve (STATIC walls/floor)",
           text="Robots stay between the walls and above the ground top.",
           check=custom(_robot_bounds), scenarios=("*",)),
    Expect(id="E36", level="L0", cite=G + "#mundo-grupos (untag/tag)",
           text="A robot is only ever moved from 'inimigo' to 'tchau': inimigo + tchau <= 3 always, and without R the robot count never rises.",
           check=all_of(custom(lambda t: all(s.values["n_inimigo"] + s.values["n_tchau"] <= 3
                                             for s in t.samples) or "more than 3 robots"),
                        custom(_non_increasing("n_inimigo"))),
           scenarios=NO_R),
    # hero bounds
    Expect(id="E37", level="L2", cite=G + "#colisao-resolve (resolve stops a traveller at STATIC walls)",
           text="The hero stays between the walls and never sinks more than 1 unit into the ground.",
           check=custom(_hero_bounds), scenarios=("*",)),
    Expect(id="E38", level="L2", cite=G + "#colisao-resolve (Colocar x viajar)",
           text="Running right on the ground the hero is stopped by the floating ramp's low corner (y~111) and never passes x=800. Assumes the hero hitbox is ~70 tall (program comment).",
           check=always("hero_x", lambda v: v <= 800), scenarios=("run_right_long",), guess=True),
    # game over and restart
    Expect(id="E39", level="L0", cite=G + "#reagir-when + Todo objeto na tela (active=False)",
           text="With 1 life, the robot hit ends the game: vidas 0, hero inactive until R, placar shows the game-over text with 0 stars.",
           check=custom(_gameover_state), scenarios=("gameover",)),
    Expect(id="E40", level="L2", cite="program update() returns early; " + G + "#colisao-resolve",
           text="While the game is over update() returns early: the elevator and robots stand still (robots tol 0.5).",
           check=custom(_gameover_frozen), scenarios=("gameover",)),
    Expect(id="E41", level="L0", cite="design/Scena Design.md#frame-order (@when flush after collision) + " + G + "#reagir-when",
           text="R after game over resets in the same frame: 3 lives, 0 stars, hero active at (120,120), 3 robots, 4 stars, no balls, elevator at y=290 moving down, normal placar.",
           check=custom(_reset_state(_gameover_reset_frame)), scenarios=("gameover",)),
    Expect(id="E42", level="L0", cite=G + "#reagir-when + #spr-flip",
           text="R in play resets the same way, and un-flips a hero that was facing left.",
           check=custom(_reset_state(_restart_frame, flip_before=True)),
           scenarios=("restart_hold",)),
    Expect(id="E43", level="L1", cite=G + "#reagir-when (fires on the False->True edge only)",
           text="Holding R for 30 frames resets once: 29 frames later the elevator has descended to 290 - 29*4/3 = 251.33.",
           check=custom(_restart_once), scenarios=("restart_hold",)),
    Expect(id="E44", level="L0", cite=G + "#reativo-liga (@= reads st)",
           text="Writing st.estrelas = 7 updates the linked placar to 'Estrelas 7   Vidas 3'.",
           check=at_end("placar", lambda v: v == NORMAL.format(7, 3)), scenarios=("score_cell",)),
    Expect(id="E45", level="L0", cite=G + "#spr-flip (flip persists when still)",
           text="After a 2-frame LEFT tap and release the hero keeps facing left (vel.x 0 keeps the last side), so the shot follows the look.",
           check=at_end("hero_flip", lambda v: bool(v)), scenarios=("shoot_left",)),
]
