"""Spec A for tests/programs/platformer.py, written from the docs only.

Geometry used below (from the program + docs):
  ground "plataforma" Rect center (550, 40) h 40      -> top y = 60
  walls: inner faces at x = 42 (left) and x = 1058 (right)
  elevator: iniciar_posicoes() (run at load) puts it at (230, 290), vel.y = -80;
            update moves it by vel.y*dt and flips below y 90 / above y 700.
  roda: STATIC Rect at (600, 400), rotate_by(150*dt) each frame (angle accumulates).
  .vel is plain data: nothing integrates it except the script's move_by
  (Guia #colisao-resolve: ".vel e None ate atribuir; o script move com move_by").
"""
from program_support import (Scenario, Expect, wait, wait_s, click_widget, click,
    key, key_down, key_up, move, scroll, set_cell, always, never, at, at_end,
    eventually, steady, all_of, custom, close)
import math

FILES_READ = [
    "tests/programs/platformer.py",
    "tests/programs/spec_agent_prompt.txt",
    "design/Scena Design.md#frame-order",
    "design/Scena Design.md#scheduler",
    "design/Scena Design.md#collision",
    "design/Scena Design.md#numbers-and-signs",
    "design/Actors Design.md (@collide arity / transient on_done / group-scoped every rows)",
    "docs/pt/guide/index.html#colisao (collide, info, resolve, touching, floor)",
    "docs/pt/guide/index.html#sprite-animar",
    "docs/pt/guide/index.html#sprite-orientar",
    "docs/pt/guide/index.html#spr-hit-corpo",
    "docs/pt/guide/index.html#mundo-grupos",
    "docs/pt/guide/index.html#frame-teclado",
    "docs/pt/guide/index.html#agendar (after/every, ready, recently, Ao terminar)",
    "docs/pt/guide/index.html#reagir-when",
    "docs/pt/guide/index.html#desenhar-entity (active, destroy)",
    "docs/pt/guide/index.html#aparencia-transientes",
    "docs/pt/guide/index.html#aparencia-selos (.tail)",
    "docs/pt/guide/index.html#pose-rotate-by",
    "docs/pt/guide/index.html#geo-vec2 (vec_from_angle)",
    "examples/media (file names only)",
]

DT = 1.0 / 60.0
GROUND_TOP = 60.0
WALL_L, WALL_R = 42.0, 1058.0

# --------------------------------------------------------------------------- probes
PROBES = {
    "time": lambda p: p.clock.time,
    "hero_x": lambda p: p.heroi.center.x,
    "hero_y": lambda p: p.heroi.center.y,
    "hero_center": lambda p: (p.heroi.center.x, p.heroi.center.y),
    "hero_bottom": lambda p: p.heroi.hitbox.box.bottom,
    "hero_left": lambda p: p.heroi.hitbox.box.left,
    "hero_right": lambda p: p.heroi.hitbox.box.right,
    "hero_flip": lambda p: bool(p.heroi.flip_x),
    "hero_active": lambda p: bool(p.heroi.active),
    "hero_ferido": lambda p: bool(p.heroi.tagged("ferido")),
    "hero_tail": lambda p: p.heroi.tail not in (None, False),
    "show_parado": lambda p: bool(p.heroi.showing("parado")),
    "show_correndo": lambda p: bool(p.heroi.showing("correndo")),
    "show_pulando": lambda p: bool(p.heroi.showing("pulando")),
    "estrelas": lambda p: p.st.estrelas,
    "vidas": lambda p: p.st.vidas,
    "text": lambda p: p.placar.text,
    "n_estrela": lambda p: len(p.group["estrela"]),
    "n_inimigo": lambda p: len(p.group["inimigo"]),
    "n_tchau": lambda p: len(p.group["tchau"]),
    "n_bola": lambda p: len(p.group["bola"]),
    "balls": lambda p: tuple((b.center.x, b.center.y) for b in p.group["bola"]),
    "ball_vel": lambda p: tuple((b.vel.x, b.vel.y) for b in p.group["bola"]),
    "elev_center": lambda p: (p.elevador.center.x, p.elevador.center.y),
    "elev_y": lambda p: p.elevador.center.y,
    "roda_angle": lambda p: p.roda.angle,
    "roda_center": lambda p: (p.roda.center.x, p.roda.center.y),
    "robot_flip": lambda p: tuple(bool(r.flip_x) for r in p.group["inimigo"]),
    "robot_x": lambda p: tuple(r.center.x for r in p.group["inimigo"]),
    "star_centers": lambda p: tuple((s.center.x, s.center.y) for s in p.group["estrela"]),
}

# --------------------------------------------------------------------------- scenarios
SCENARIOS = {
    "idle": Scenario(params={}, seed=0, steps=[wait(300)]),
    "walk_right": Scenario(params={}, seed=0, steps=[
        wait(30), key("RIGHT", frames=60), wait(60)]),
    "walk_left_wall": Scenario(params={}, seed=0, steps=[
        wait(30), key("LEFT", frames=90), wait(30)]),
    "jump": Scenario(params={}, seed=0, steps=[
        wait(60), key("UP", frames=1), wait(120)]),
    "jump_hold": Scenario(params={}, seed=0, steps=[
        wait(60), key("UP", frames=150), wait(30)]),
    "up_while_falling": Scenario(params={}, seed=0, steps=[
        key("UP", frames=1), wait(60)]),
    "letter_keys": Scenario(params={}, seed=0, steps=[
        wait(30), key("A", frames=30), key("D", frames=30), key("W", frames=1),
        key("Z", frames=1), wait(30)]),
    "shoot_right": Scenario(params={}, seed=0, steps=[
        wait(30), key("SPACE", frames=1), wait(170)]),
    "shoot_hold": Scenario(params={}, seed=0, steps=[
        wait(30), key("SPACE", frames=60), wait(10)]),
    "shoot_double_tap": Scenario(params={}, seed=0, steps=[
        wait(30), key("SPACE", frames=1), wait(3), key("SPACE", frames=1), wait(20)]),
    "shoot_left_lifetime": Scenario(params={}, seed=0, steps=[
        wait(20), key("LEFT", frames=10), wait(5), key("SPACE", frames=1), wait(290)]),
    "star_pick": Scenario(params={}, seed=0, steps=[
        wait(90), set_cell("heroi.center", (770, 340)), wait(150)]),
    "hurt": Scenario(params={}, seed=0, steps=[
        wait(30), set_cell("heroi.center", (548, 100)), wait(150)]),
    "game_over_restart": Scenario(params={}, seed=0, steps=[
        wait(20), set_cell("st.vidas", 1), set_cell("heroi.center", (540, 100)),
        wait(60), key("R", frames=1), wait(30)]),
    "score_cell": Scenario(params={}, seed=0, steps=[
        wait(5), set_cell("st.estrelas", 5), wait(5)]),
    "reset_hold": Scenario(params={}, seed=0, steps=[
        wait(30), key("SPACE", frames=1), wait(30), key("R", frames=30), wait(30)]),
}

NO_R = ("idle", "walk_right", "walk_left_wall", "jump", "jump_hold", "up_while_falling",
        "letter_keys", "shoot_right", "shoot_hold", "shoot_double_tap",
        "shoot_left_lifetime", "star_pick", "hurt")


# --------------------------------------------------------------------------- helpers
def _near(a, b, tol):
    """Own approximate compare (bool) for numbers / nested tuples."""
    if isinstance(a, (tuple, list)) or isinstance(b, (tuple, list)):
        return (isinstance(a, (tuple, list)) and isinstance(b, (tuple, list))
                and len(a) == len(b) and all(_near(x, y, tol) for x, y in zip(a, b)))
    return abs(float(a) - float(b)) <= tol


def _first_frame(t, probe, pred, after=0):
    for fr, _tm, v in t.series(probe):
        if fr > after and pred(v):
            return fr
    return None


def _expected_text(e, v):
    e, v = int(e), int(v)
    if v > 0:
        return f"Estrelas {e}   Vidas {v}"
    return f"Fim de jogo — estrelas {e}  (R para recomeçar)"


def _text_consistent(t):
    for (fr, _tm, txt), (_f2, _t2, e), (_f3, _t3, v) in zip(
            t.series("text"), t.series("estrelas"), t.series("vidas")):
        want = _expected_text(e, v)
        if txt != want:
            return f"frame {fr}: text {txt!r} != {want!r}"
    return True


def _rise(lo, hi):
    def f(t):
        j = t.input_frame("key")
        base = t.at_frame(j - 1, "hero_bottom")
        peak = max(v for fr, _tm, v in t.series("hero_bottom") if fr >= j)
        r = peak - base
        return True if lo <= r <= hi else f"jump rise {r:.2f} not in [{lo}, {hi}]"
    return f


def _vidas_spacing(t):
    prev = None
    last_drop = None
    for fr, _tm, v in t.series("vidas"):
        if prev is not None and v > prev:
            return f"frame {fr}: vidas rose {prev} -> {v} without R"
        if prev is not None and v < prev:
            if v != prev - 1:
                return f"frame {fr}: vidas dropped by more than 1 ({prev} -> {v})"
            if last_drop is not None and fr - last_drop < 59:
                return f"frame {fr}: two life losses {fr - last_drop} frames apart (< 1 s)"
            last_drop = fr
        prev = v
    return True


def _foes_monotone(t):
    prev = None
    for (fr, _tm, a), (_f, _t, b) in zip(t.series("n_inimigo"), t.series("n_tchau")):
        tot = a + b
        if prev is not None and tot > prev:
            return f"frame {fr}: robots (inimigo + tchau) grew {prev} -> {tot} without R"
        prev = tot
    return True


def _tchau_short_lived(t):
    # each robot tagged "tchau" burns out in 0.5 s, then on_done destroys it.
    s = t.series("n_tchau")
    run_start, rises, prev = None, 0, 0
    for fr, _tm, v in s:
        if v > prev:
            rises += 1
            if run_start is None:
                run_start = fr
        if v == 0:
            run_start, rises = None, 0
        elif run_start is not None and fr - run_start > 32 * rises:
            return f"frame {fr}: a 'tchau' robot lived more than 0.5 s + 2 frames"
        prev = v
    return True


def _balls_inside_walls(t):
    for fr, _tm, balls in t.series("balls"):
        for (x, y) in balls:
            if not (WALL_L - 2.0 <= x <= WALL_R + 2.0) or y < GROUND_TOP - 2.0:
                return f"frame {fr}: ball at ({x:.1f}, {y:.1f}) is inside a wall/ground"
    return True


def _elev_descends(t):
    for fr, tm, y in t.series("elev_y"):
        if tm <= 2.4 and abs(y - (290.0 - 80.0 * tm)) > 0.3:
            return f"frame {fr}: elevator y {y:.3f} != 290 - 80 t = {290 - 80 * tm:.3f}"
    return True


def _roda(t):
    # Revised (MISREAD): update() returns early while the hero is inactive (game
    # over), so the wheel turns 150*dt only on frames that start with the hero
    # active. Integrate those frames instead of assuming 150 * time.
    angle, prev_t, active = 0.0, 0.0, True
    for s in t.samples:
        if active:
            angle += 150.0 * (s.time - prev_t)
        prev_t, active = s.time, s.values["hero_active"]
        a = s.values["roda_angle"]
        if abs(a - angle) > 0.05:
            return f"frame {s.frame}: roda angle {a:.3f} != {angle:.3f}"
    return True


def _ball_count_increments(t):
    frames = []
    prev = 0
    for fr, _tm, n in t.series("n_bola"):
        if n > prev:
            frames.extend([fr] * int(n - prev))
        prev = n
    if len(frames) != 4:
        return f"{len(frames)} balls created while SPACE held 60 frames (want 4)"
    gaps = [b - a for a, b in zip(frames, frames[1:])]
    if any(g < 14 or g > 16 for g in gaps):
        return f"shot gaps {gaps} frames (want ~15 = 0.25 s)"
    return True


def _first_ball_kinematics(t):
    j = _first_frame(t, "n_bola", lambda n: n >= 1)
    if j is None:
        return "no ball was created"
    hx, hy = t.at_frame(j - 1, "hero_center")
    (bx, by), = t.at_frame(j, "balls")
    (vx, vy), = t.at_frame(j, "ball_vel")
    ex_vx, ex_vy = 420 * math.cos(math.radians(30)), 420 * math.sin(math.radians(30)) - 900 * DT
    dx, dy = bx - hx, by - hy
    if abs(dx - (28 + ex_vx * DT)) > 0.6 or abs(dy - (10 + ex_vy * DT)) > 0.6:
        return f"ball offset from hero ({dx:.2f}, {dy:.2f}), want ({28 + ex_vx * DT:.2f}, {10 + ex_vy * DT:.2f})"
    if abs(vx - ex_vx) > 0.05 or abs(vy - ex_vy) > 0.05:
        return f"ball vel ({vx:.2f}, {vy:.2f}), want ({ex_vx:.2f}, {ex_vy:.2f})"
    return True


def _ball_lifetime(lo_s, hi_s):
    def f(t):
        j = _first_frame(t, "n_bola", lambda n: n >= 1)
        if j is None:
            return "no ball was created"
        k = _first_frame(t, "n_bola", lambda n: n == 0, after=j)
        if k is None:
            return "ball never removed"
        life = (k - j) * DT
        return True if lo_s <= life <= hi_s else f"ball lived {life:.3f} s, want [{lo_s}, {hi_s}]"
    return f


def _hurt(t):
    h = _first_frame(t, "vidas", lambda v: v == 2)
    if h is None:
        return "hero was never hurt"
    if not t.at_frame(h, "hero_ferido"):
        return f"frame {h}: not tagged ferido on the hit frame"
    if not t.at_frame(h + 58, "hero_ferido"):
        return "ferido cleared before 1.0 s"
    if t.at_frame(h + 62, "hero_ferido"):
        return "ferido still set after 1.0 s + 2 frames"
    if t.end("vidas") != 2:
        return f"vidas at end {t.end('vidas')} (want 2: the robot overlap is one enter)"
    if not t.end("hero_active"):
        return "hero parked with lives left"
    return True


def _game_over(t):
    h = _first_frame(t, "vidas", lambda v: v == 0)
    if h is None:
        return "no game over"
    if t.at_frame(h, "hero_active"):
        return f"frame {h}: hero still active at 0 lives"
    r = t.input_frame("key")
    c0 = t.at_frame(h + 1, "hero_center")
    for fr in range(h + 1, r):
        c = t.at_frame(fr, "hero_center")
        if abs(c[0] - c0[0]) > 1e-6 or abs(c[1] - c0[1]) > 1e-6:
            return f"frame {fr}: parked hero moved {c0} -> {c}"
    return True


def _restart_frame(t):
    r = t.input_frame("key")
    checks = [
        ("hero_center", lambda v: _near(v, (120.0, 120.0), 0.01)),
        ("vidas", lambda v: v == 3),
        ("estrelas", lambda v: v == 0),
        ("hero_active", lambda v: v is True),
        ("hero_ferido", lambda v: v is False),
        ("n_estrela", lambda v: v == 4),
        ("n_inimigo", lambda v: v == 3),
        ("n_bola", lambda v: v == 0),
        ("n_tchau", lambda v: v == 0),
        ("elev_center", lambda v: _near(v, (230.0, 290.0), 0.01)),
        ("robot_x", lambda v: _near(v, (520.0, 420.0, 780.0), 0.01)),
        ("star_centers", lambda v: _near(v, ((300.0, 250.0), (520.0, 250.0),
                                             (780.0, 370.0), (920.0, 240.0)), 0.01)),
        ("text", lambda v: v == "Estrelas 0   Vidas 3"),
    ]
    for name, pred in checks:
        v = t.at_frame(r, name)
        if not pred(v):
            return f"R frame {r}: {name} = {v!r}"
    return True


def _reset_once(t):
    r = t.press_frame("R")  # revised (HARNESS): input_frame("key", 1) was the SPACE release
    y = t.at_frame(r + 20, "elev_y")
    want = 290.0 - 80.0 * 20 * DT
    return True if abs(y - want) < 0.3 else f"elevator y {y:.2f} at R+20, want {want:.2f} (R held must fire once)"


def _star_pick(t):
    c = _first_frame(t, "estrelas", lambda v: v == 1)
    w = t.input_frame("cell")
    if c is None:
        return "star never collected"
    if c - w > 2:
        return f"collected {c - w} frames after placing the hero on the star"
    if t.at_frame(c, "n_estrela") != 3:
        return "star not destroyed on collection"
    if not t.at_frame(c, "hero_tail"):
        return "tail not on after collection"
    if not t.at_frame(c + 118, "hero_tail"):
        return "tail off before 2 s"
    if t.at_frame(c + 122, "hero_tail"):
        return "tail still on 2 s + 2 frames after collection"
    return True


def _walk_right(t):
    j = t.input_frame("key")
    x0 = t.at_frame(j - 1, "hero_x")
    x1 = t.end("hero_x")
    d = x1 - x0
    return True if abs(d - 250.0) <= 5.0 else f"walked {d:.2f}, want 250 (60 frames x 250/s)"


def _running_clip(t):
    j = t.input_frame("key")
    return True if t.at_frame(j + 30, "show_correndo") else "not showing 'correndo' while walking on ground"


def _air_clip(t):
    j = t.input_frame("key")
    return True if t.at_frame(j + 20, "show_pulando") else "not showing 'pulando' mid-jump"


def _held_up_one_jump(t):
    j = t.input_frame("key")
    base = t.at_frame(j - 1, "hero_bottom")
    for fr, _tm, b in t.series("hero_bottom"):
        if j + 90 <= fr <= j + 148 and abs(b - base) > 1.0:
            return f"frame {fr}: bottom {b:.2f} off ground {base:.2f} while UP still held (re-jump?)"
    return True


def _no_jump_when_falling(t):
    b1 = t.at_frame(1, "hero_bottom")
    for fr, _tm, b in t.series("hero_bottom"):
        if b > b1 + 1.0:
            return f"frame {fr}: hero rose to {b:.2f} (UP pressed mid-air must not jump)"
    return True


def _letters_ignored(t):
    x0 = t.at_frame(30, "hero_x")
    for fr, _tm, x in t.series("hero_x"):
        if fr >= 30 and abs(x - x0) > 0.01:
            return f"frame {fr}: hero moved on A/D"
    if any(n > 0 for n in t.values("n_bola")):
        return "Z fired a ball"
    for fr, _tm, b in t.series("hero_bottom"):
        if fr >= 30 and b > GROUND_TOP + 1.5:
            return f"frame {fr}: W made the hero leave the ground"
    return True


# --------------------------------------------------------------------------- expectations
G_RESOLVE = "docs/pt/guide/index.html#colisao-resolve"
G_TOUCH = "docs/pt/guide/index.html#colisao-touching"
G_AGENDAR = "docs/pt/guide/index.html#agendar-ready / #agendar-recently"

EXPECT = [
    # ---------------- startup (L0)
    Expect(id="E1", level="L0", cite="docs/pt/guide/index.html#reativo (@= link); program placar",
           text="Startup: the score text reads 'Estrelas 0   Vidas 3'.",
           check=at(1, "text", lambda v: v == "Estrelas 0   Vidas 3"),
           scenarios=("idle",)),
    Expect(id="E2", level="L0", cite="docs/pt/guide/index.html#mundo-grupos (grp-ler: count, order of entry)",
           text="Startup: 4 stars at their spawn centers (in creation order), 3 robots, 0 balls, 0 'tchau'.",
           check=all_of(
               at(1, "n_estrela", lambda v: v == 4),
               at(1, "n_inimigo", lambda v: v == 3),
               at(1, "n_bola", lambda v: v == 0),
               at(1, "n_tchau", lambda v: v == 0),
               at(1, "star_centers", lambda v: _near(v, ((300.0, 250.0), (520.0, 250.0),
                                                         (780.0, 370.0), (920.0, 240.0)), 0.01))),
           scenarios=("idle",)),
    Expect(id="E3", level="L0", cite="docs/pt/guide/index.html#spr-flip; program update robot loop",
           text="Robots face their walking direction: flip_x is (False, True, False) after frame 1.",
           check=at(1, "robot_flip", lambda v: v == (False, True, False)),
           scenarios=("idle",)),
    Expect(id="E4", level="L0", cite="docs/pt/guide/index.html#spr-clip / #spr-plat; #colisao-touching",
           text="Frame 1: touching_sides reflects the previous (non-existent) check, so the hero is not grounded and plays 'pulando'.",
           check=at(1, "show_pulando", lambda v: v is True),
           scenarios=("idle",)),
    Expect(id="E5", level="L1", cite="docs/pt/guide/index.html#colisao-resolve (.vel only moves via move_by); program update",
           text="Frame 1: the hero falls one step: center.y = 120 - 900*dt*dt = 119.75 and x stays 120.",
           check=at(1, "hero_center", lambda v: _near(v, (120.0, 119.75), 0.05)),
           scenarios=("idle",), guess=True),
    # ---------------- idle physics
    Expect(id="E6", level="L2", cite=G_RESOLVE + " (bounce=0.0, grudar no chao)",
           text="Idle: the hero lands on the ground; hitbox bottom sits at y=60 (slop 1.5 for resolve skin) from frame 40 on.",
           check=always("hero_bottom", lambda b: abs(b - GROUND_TOP) <= 1.5, after=40),
           scenarios=("idle", "shoot_hold", "shoot_double_tap", "score_cell")),
    Expect(id="E7", level="L0", cite="program update (vel.x = 0 without LEFT/RIGHT); " + G_RESOLVE,
           text="Idle: hero x never changes (no horizontal input, no lateral push) and is steady after landing.",
           check=all_of(always("hero_x", lambda x: abs(x - 120.0) < 0.01),
                        steady("hero_center", after=40, tol=0.3)),
           scenarios=("idle",)),
    Expect(id="E8", level="L0", cite="docs/pt/guide/index.html#spr-plat",
           text="Idle on the ground the hero ends showing the 'parado' clip (unless game over parks it).",
           check=custom(lambda t: True if (t.end("show_parado") or t.end("vidas") <= 0)
                        else "not showing 'parado' at end of idle"),
           scenarios=("idle",)),
    Expect(id="E9", level="L0", cite="program (no shooting input)",
           text="Without SPACE no ball ever exists and no star is collected while idle.",
           check=all_of(always("n_bola", lambda n: n == 0), always("estrelas", lambda e: e == 0)),
           scenarios=("idle", "walk_right", "jump", "up_while_falling")),
    # ---------------- elevator / roda (L1)
    Expect(id="E10", level="L1", cite="program iniciar_posicoes + update; docs/pt/guide/index.html#pose-move-by",
           text="Elevator starts at (230, 290) moving down 80/s: y = 290 - 80 t (tol 0.3) for t <= 2.4 s; x stays 230.",
           check=all_of(custom(_elev_descends),
                        always("elev_center", lambda c: abs(c[0] - 230.0) < 1e-6)),
           scenarios=("idle",)),
    Expect(id="E11", level="L1", cite="program update (reverse below 90)",
           text="Elevator reverses near y=90 at t~2.5 s and climbs back to y~290 at t=5 s (tol 3.5 for the reversal frame).",
           check=at_end("elev_y", lambda y: abs(y - 290.0) <= 3.5),
           scenarios=("idle",)),
    Expect(id="E12", level="L2", cite="program update (bounds 90..700, step 80/60)",
           text="Elevator y always stays within [90 - 80/60, 700 + 80/60] (one step of overshoot).",
           check=always("elev_y", lambda y: 88.6 <= y <= 701.4),
           scenarios=("*",)),
    Expect(id="E13", revised="MISREAD: the program freezes update() at game over; integrate only active frames", level="L1", cite="docs/pt/guide/index.html#pose-rotate-by (angle accumulates)",
           text="roda.angle = 150 * time (tol 0.05), never wrapped, and its center stays (600, 400).",
           check=all_of(custom(_roda),
                        always("roda_center", lambda c: _near(c, (600.0, 400.0), 1e-6))),
           scenarios=("*",)),
    # ---------------- walking
    Expect(id="E14", level="L1", cite="docs/pt/guide/index.html#frame-teclado; program VELOCIDADE_HEROI",
           text="Holding RIGHT 60 frames on open ground moves the hero +250 (250/s, tol 5 = one frame).",
           check=custom(_walk_right),
           scenarios=("walk_right",)),
    Expect(id="E15", level="L0", cite="docs/pt/guide/index.html#spr-plat",
           text="While walking on the ground the hero shows the 'correndo' clip.",
           check=custom(_running_clip),
           scenarios=("walk_right",)),
    Expect(id="E16", level="L0", cite="docs/pt/guide/index.html#spr-flip; program update",
           text="RIGHT keeps flip_x False; after LEFT the hero keeps facing left (flip_x True) once released.",
           check=custom(lambda t: True if (not any(t.values("hero_flip")) if t.end("hero_x") > 200
                                          else t.end("hero_flip")) else "wrong facing"),
           scenarios=("walk_right", "walk_left_wall")),
    Expect(id="E17", level="L2", cite=G_RESOLVE + " (parede STATIC; bounce=0)",
           text="Walking into the left wall: hitbox left never passes x=42 (slop 1) and the hero is steady at the end.",
           check=all_of(always("hero_left", lambda x: x >= WALL_L - 1.0),
                        steady("hero_x", after=110, tol=0.01)),
           scenarios=("walk_left_wall",)),
    Expect(id="E18", level="L2", cite=G_RESOLVE,
           text="In every scenario the hero's hitbox stays between the walls (slop 1).",
           check=all_of(always("hero_left", lambda x: x >= WALL_L - 1.0),
                        always("hero_right", lambda x: x <= WALL_R + 1.0)),
           scenarios=("*",)),
    Expect(id="E19", level="L0", cite="docs/pt/guide/index.html#frame-teclado (keyp('LEFT') names one key)",
           text="A / D / W / Z do nothing: the code reads only LEFT, RIGHT, UP, SPACE, R (the docstring's A/D/W/Z claim is not implemented).",
           check=custom(_letters_ignored),
           scenarios=("letter_keys",)),
    # ---------------- jumping
    Expect(id="E20", level="L2", cite="program PULO/GRAVIDADE; " + G_AGENDAR,
           text="A jump from the ground rises at least PULO^2/(2g) ~ 117.6 minus slop and at most ~165 (coyote re-sets of vel.y can add a few frames at 460).",
           check=custom(_rise(110.0, 165.0)),
           scenarios=("jump", "jump_hold")),
    Expect(id="E21", level="L1", cite=G_AGENDAR + " (recently is True every frame of the window)",
           text="Exact rise: recently('no_chao', hold=0.08) stays True 4 frames after takeoff while recently('pulo') holds, so vel.y is reset to 460 for 5 frames: rise ~152 (accept 140..158).",
           check=custom(_rise(140.0, 158.0)),
           scenarios=("jump",), guess=True),
    Expect(id="E22", level="L0", cite="docs/pt/guide/index.html#spr-plat",
           text="Mid-jump (20 frames after UP) the hero shows the 'pulando' clip.",
           check=custom(_air_clip),
           scenarios=("jump",)),
    Expect(id="E23", level="L0", cite="docs/pt/guide/index.html#frame-teclado (keyp.once: one press = one True)",
           text="Holding UP does not re-jump: after landing the hero stays on the ground while UP is still held.",
           check=custom(_held_up_one_jump),
           scenarios=("jump_hold",)),
    Expect(id="E24", level="L0", cite=G_AGENDAR + "; " + G_TOUCH,
           text="UP pressed on frame 1 while falling from spawn does not jump (the 0.12 s buffer expires before landing at ~0.24 s).",
           check=custom(_no_jump_when_falling),
           scenarios=("up_while_falling",), guess=True),
    # ---------------- shooting
    Expect(id="E25", level="L1", cite="program atirar; docs/pt/guide/index.html#geo-vec2 (vec_from_angle)",
           text="A right-facing shot spawns at hero.center + (28, 10), gets vel = 420 at 30 deg, and is moved once in the same update: offset (34.06, 13.25), vel (363.73, 195.0).",
           check=custom(_first_ball_kinematics),
           scenarios=("shoot_right", "shoot_hold", "shoot_double_tap")),
    Expect(id="E26", level="L0", cite="docs/pt/guide/index.html#agendar-ready",
           text="SPACE held 60 frames fires exactly 4 balls, ~15 frames (0.25 s) apart; ready() is True on its first call.",
           check=custom(_ball_count_increments),
           scenarios=("shoot_hold",)),
    Expect(id="E27", level="L0", cite="docs/pt/guide/index.html#agendar-ready",
           text="Two SPACE taps 4 frames apart fire only one ball (cooldown 0.25 s).",
           check=always("n_bola", lambda n: n <= 1),
           scenarios=("shoot_double_tap",)),
    Expect(id="E28", level="L2", cite="docs/pt/guide/index.html#agendar (e.after) + #aparencia-transientes (dissolve_out on_done)",
           text="A ball is gone at most 4.0 + 0.4 s (+3 frames) after it is fired, whatever it hits.",
           check=custom(_ball_lifetime(0.0, 4.45)),
           scenarios=("shoot_left_lifetime",)),
    Expect(id="E29", revised="INTUITION: the ball bounced back off the wall into robot 1 (gone at 2.93 s); keep the upper bound only", level="L1", cite="docs/pt/guide/index.html#agendar (e.after passes the entity, per Actors Design arity row) + transient channel",
           text="A ball shot into the empty left corner lives 4.0 s then dissolves 0.4 s: removed 4.4 s after firing (tol -0.05/+0.07); assumes no robot reaches it.",
           check=custom(_ball_lifetime(0.0, 4.47)),
           scenarios=("shoot_left_lifetime",), guess=True),
    Expect(id="E30", level="L2", cite=G_RESOLVE + " (bola vs plataforma/parede bounce=0.7)",
           text="Balls never end a frame inside a wall or below the ground top (slop 2).",
           check=custom(_balls_inside_walls),
           scenarios=("shoot_right", "shoot_hold", "shoot_left_lifetime")),
    Expect(id="E31", level="L0", cite="docs/pt/guide/index.html#colisao-collide (enter) + #mundo-grupos (tag/untag)",
           text="A right shot from the spawn rolls into robot 1: it leaves 'inimigo' (count 2) within 3 s of the shot.",
           check=eventually("n_inimigo", lambda n: n == 2),
           scenarios=("shoot_right",), guess=True),
    Expect(id="E32", level="L0", cite="docs/pt/guide/index.html#aparencia-transientes (burn_out 0.5 + on_done destroy)",
           text="A robot retagged 'tchau' is destroyed within 0.5 s + 2 frames; robot totals never grow without R.",
           check=all_of(custom(_tchau_short_lived), custom(_foes_monotone)),
           scenarios=NO_R),
    # ---------------- stars / score
    Expect(id="E33", level="L0", cite="docs/pt/guide/index.html#colisao-collide; program coletou",
           text="Collected stars + remaining stars always equal 4 (destroy leaves the group at once, same handler adds 1).",
           check=custom(lambda t: next((f"frame {fr}: {int(e)} + {int(n)} != 4"
                                        for (fr, _a, e), (_f, _b, n) in zip(t.series("estrelas"), t.series("n_estrela"))
                                        if e + n != 4), True)),
           scenarios=tuple(s for s in SCENARIOS if s != "score_cell")),
    Expect(id="E34", level="L0", cite="docs/pt/guide/index.html#colisao-collide + #agendar (after name=) + #aparencia-selos (.tail)",
           text="Placing the hero on the star at (780, 370) collects it within 2 frames; tail turns on then off 2.0 s later.",
           check=custom(_star_pick),
           scenarios=("star_pick",)),
    Expect(id="E35", level="L2", cite=G_RESOLVE,
           text="After the pick the hero stands on the platform (780, 280): hitbox bottom ~292 (slop 1.5).",
           check=at_end("hero_bottom", lambda b: abs(b - 292.0) <= 1.5),
           scenarios=("star_pick",)),
    Expect(id="E36", level="L0", cite="docs/pt/guide/index.html#reativo-state (st cell + @= link)",
           text="The score text always matches st: 'Estrelas e   Vidas v', or the game-over line when vidas <= 0.",
           check=custom(_text_consistent),
           scenarios=("*",)),
    Expect(id="E37", level="L0", cite="docs/pt/guide/index.html#reativo-state",
           text="Writing st.estrelas = 5 updates the text to 'Estrelas 5   Vidas 3'.",
           check=at_end("text", lambda v: v == "Estrelas 5   Vidas 3"),
           scenarios=("score_cell",)),
    # ---------------- damage / game over / restart
    Expect(id="E38", level="L0", cite="docs/pt/guide/index.html#colisao-collide (enter once) + #agendar (after 1.0)",
           text="Touching a robot costs exactly one life, tags 'ferido' for 1.0 s (+-2 frames), and the hero stays active.",
           check=custom(_hurt),
           scenarios=("hurt",)),
    Expect(id="E39", level="L0", cite="docs/pt/guide/index.html#colisao-collide; program machucou/ferido",
           text="Lives never rise without R, drop by one at a time, and two losses are at least 1 s apart.",
           check=custom(_vidas_spacing),
           scenarios=NO_R),
    Expect(id="E40", level="L0", cite="docs/pt/guide/index.html#desenhar-entity (active parks: no update effect, no collision)",
           text="Hero is active exactly when vidas > 0.",
           check=custom(lambda t: next((f"frame {fr}: active={a} vidas={int(v)}"
                                        for (fr, _x, a), (_f, _y, v) in zip(t.series("hero_active"), t.series("vidas"))
                                        if a != (v > 0)), True)),
           scenarios=("*",)),
    Expect(id="E41", level="L0", cite="docs/pt/guide/index.html#desenhar-entity (active=False); program perder_vida",
           text="Last life lost: hero parked (active False) and frozen in place until R.",
           check=custom(_game_over),
           scenarios=("game_over_restart",)),
    Expect(id="E42", level="L0", cite="docs/pt/guide/index.html#reagir-when (edge) + design/Scena Design.md#frame-order (flush after update)",
           text="On the R frame iniciar_posicoes runs after update: hero at exactly (120, 120), 3 lives, 0 stars, active, 4 stars, 3 robots at spawn, 0 balls, elevator (230, 290), normal text.",
           check=custom(_restart_frame),
           scenarios=("game_over_restart",)),
    Expect(id="E43", revised="HARNESS: input_frame(\"key\", 1) counted the SPACE release; anchored on press_frame(\"R\")", level="L0", cite="docs/pt/guide/index.html#reagir-when (fires once on False->True)",
           text="Holding R 30 frames resets once: 20 frames after R the elevator is at 290 - 80*20/60, and the earlier ball is gone at R.",
           check=all_of(custom(_reset_once),
                        custom(lambda t: True if t.at_frame(t.press_frame("R"), "n_bola") == 0
                               else "ball survived R")),
           scenarios=("reset_hold",)),
    Expect(id="E44", level="L1", cite="program criar_robo; " + G_RESOLVE + " (tangent kept)",
           text="Robot 1 walks right on the ground at 55/s: x = 520 + 55 t (tol 2) for t <= 3 s.",
           check=custom(lambda t: next((f"frame {fr}: robot1 x {xs[0]:.2f} != {520 + 55 * tm:.2f}"
                                        for fr, tm, xs in t.series("robot_x")
                                        if tm <= 3.0 and abs(xs[0] - (520 + 55 * tm)) > 2.0), True)),
           scenarios=("idle",)),
]
