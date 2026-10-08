"""Spec B for examples/naves.py (tutorial 05), written from the docs only.

Frame model used (design/Scena Design.md "Frame order"): input -> update(dt)
-> process tick (tweens, due timers) -> collision -> leave_playfield -> flush.
So: a player shot is created in update and moved by the group line in the same
update (spawn y = 70 + 28 + 640/60); an enemy shot is created by the @every
timer after update (spawn y = enemy y - 20, not moved yet); hits and playfield
exits are already applied when the probes read.
"""

from program_support import (Scenario, Expect, wait, wait_s, click_widget, click,
    key, key_down, key_up, move, scroll, set_cell, always, never, at, at_end,
    eventually, steady, all_of, custom, close)
import math

FILES_READ = [
    "examples/naves.py",
    "docs/pt/tutorial/05-naves.html",
    "design/Scena Design.md#frame-order",
    "design/Collision Design.md#frame-order",
    "docs/pt/guide/index.html#frame-clock",
    "docs/pt/guide/index.html#frame-teclado",
    "docs/pt/guide/index.html#mover-confine",
    "docs/pt/guide/index.html#mover-pose",
    "docs/pt/guide/index.html#agendar-timers",
    "docs/pt/guide/index.html#agendar-ready",
    "docs/pt/guide/index.html#reagir-bounds",
    "docs/pt/guide/index.html#colocar-pais",
    "docs/pt/guide/index.html#colisao-collide",
    "docs/pt/guide/index.html#desenhar-text",
    "docs/pt/guide/index.html#mundo-grupos",
    "docs/pt/guide/index.html#spr-hit-medir",
    "docs/pt/guide/index.html (DestroyedError row, is_alive row)",
]

DT = 1.0 / 60.0
SHIP_V = 340.0 * DT
SHOT_V = 640.0 * DT
ESHOT_V = 400.0 * DT
FLEET_V = 80.0 * DT
SHOT_SPAWN_Y = 70.0 + 28.0 + SHOT_V
ROWS_Y = (580.0, 650.0, 720.0)
ESHOT_SPAWN_Y = tuple(y - 20.0 for y in ROWS_Y)
PF_TOP = 1000.0      # playfield: 800 * 1.5 centred -> y in [-200, 1000]
PF_BOTTOM = -200.0
EPS = 1e-6


def _pts(group):
    return tuple(sorted((float(s.center.x), float(s.center.y)) for s in group))


PROBES = {
    "time": lambda p: p.clock.time,
    "ship": lambda p: (p.nave.center.x, p.nave.center.y),
    "alive": lambda p: bool(p.nave.is_alive),
    "ship_height": lambda p: p.nave.height,
    "glow": lambda p: bool(p.nave.glow),
    "pontos": lambda p: p.st.pontos,
    "vel": lambda p: p.st.velocidade,
    "placar": lambda p: p.placar.text,
    "placar_tl": lambda p: (p.placar.top_left.x, p.placar.top_left.y),
    "n_enemies": lambda p: p.group["inimigos"].count,
    "enemies": lambda p: _pts(p.group["inimigos"]),
    "scales": lambda p: tuple(float(e.scale) for e in p.group["inimigos"]),
    "shots": lambda p: _pts(p.group["tiros"]),
    "eshots": lambda p: _pts(p.group["tiros_inimigos"]),
    "eshot_angles": lambda p: tuple(float(s.angle) for s in p.group["tiros_inimigos"]),
}

SCENARIOS = {
    # nothing pressed
    "idle": Scenario(params={}, seed=0, steps=[wait(400)]),
    # short move right
    "move_short": Scenario(params={}, seed=0, steps=[key("RIGHT", frames=30), wait(20)]),
    # hold right into the fence
    "right_wall": Scenario(params={}, seed=0, steps=[key("RIGHT", frames=120), wait(10)]),
    # hold left into the fence
    "left_wall": Scenario(params={}, seed=1, steps=[key("LEFT", frames=100), wait(5)]),
    # fleet frozen; ship at x=500 sits between columns 455 and 545; hold SPACE ~1 s
    "shoot_gap": Scenario(params={}, seed=0, steps=[
        set_cell("st.velocidade", 0), wait(5), key("SPACE", frames=61), wait(100)]),
    # fleet frozen; ship moved under column x=545, fire ~4 shots
    "hit_column": Scenario(params={}, seed=0, steps=[
        set_cell("st.velocidade", 0), wait(2), key("RIGHT", frames=8), wait(2),
        key("SPACE", frames=40), wait(150)]),
    # fleet frozen; ship parked under column 545 until a red laser falls on it;
    # then try to move and shoot (must do nothing if it is gone)
    "death": Scenario(params={}, seed=3, steps=[
        set_cell("st.velocidade", 0), key("RIGHT", frames=8), wait(520),
        key("LEFT", frames=20), key("SPACE", frames=20), wait(10)]),
}

FROZEN = ("shoot_gap", "hit_column", "death")


# ---------------------------------------------------------------- helpers

def _series(t, name):
    return [(f, v) for (f, _tm, v) in t.series(name)]


def _diff(prev, cur, dy, tol=0.05):
    """Match prev shots moved by dy against cur. Returns (removed, new)."""
    left = list(cur)
    removed = []
    for (x, y) in prev:
        sx, sy = x, y + dy
        hit = None
        for i, (cx, cy) in enumerate(left):
            if abs(cx - sx) < tol and abs(cy - sy) < tol:
                hit = i
                break
        if hit is None:
            removed.append((sx, sy))
        else:
            left.pop(hit)
    return removed, left


def _death_frame(t):
    for (f, a) in _series(t, "alive"):
        if not a:
            return f
    return None


def _xs(enemies):
    return [x for (x, _y) in enemies]


def _tri_scale(time):
    u = (time / 0.45) % 2.0
    frac = u if u <= 1.0 else 2.0 - u
    return 1.0 + 0.08 * frac


# ---------------------------------------------------------------- customs

def _check_fleet_step(t):
    en = _series(t, "enemies")
    vel = dict(_series(t, "vel"))
    prev_min, prev_vel = 185.0, 80.0
    for (f, e) in en:
        m = min(_xs(e))
        if abs((m - prev_min) - prev_vel * DT) > 1e-6:
            return "frame %d: fleet min x moved %.6f, expected %.6f" % (
                f, m - prev_min, prev_vel * DT)
        prev_min, prev_vel = m, vel[f]
    return True


def _check_bounce_rule(t):
    en = dict(_series(t, "enemies"))
    prev_vel = 80.0
    for (f, v) in _series(t, "vel"):
        xs = _xs(en[f])
        if max(xs) > 960:
            want = -80.0
        elif min(xs) < 40:
            want = 80.0
        else:
            want = prev_vel
        if v != want:
            return "frame %d: velocidade %r, expected %r (x range %.3f..%.3f)" % (
                f, v, want, min(xs), max(xs))
        prev_vel = v
    return True


def _check_reversal_frames(t):
    vs = _series(t, "vel")
    flips = [f for (i, (f, v)) in enumerate(vs) if i > 0 and v != vs[i - 1][1]]
    if vs and vs[0][1] != 80.0:
        return "velocidade at frame 1 is %r, expected 80" % vs[0][1]
    if len(flips) < 2:
        return "expected 2 reversals in 400 frames, got %r" % flips
    if abs(flips[0] - 109) > 1 or abs(flips[1] - 327) > 1:
        return "reversals at %r, expected ~109 and ~327" % flips[:2]
    return True


def _check_scale_phase(t):
    sc = dict(_series(t, "scales"))
    for (f, tm, _v) in t.series("time"):
        want = _tri_scale(tm)
        for s in sc[f]:
            if abs(s - want) > 0.006:
                return "frame %d t=%.4f: scale %.5f, expected %.5f" % (f, tm, s, want)
    return True


def _eshot_spawn_frames(t):
    frames = []
    es = _series(t, "eshots")
    prev = ()
    for (f, cur) in es:
        _rem, new = _diff(prev, cur, -ESHOT_V)
        if new:
            frames.append((f, new))
        prev = cur
    return frames


def _check_first_eshot(t):
    sp = _eshot_spawn_frames(t)
    if not sp:
        return "no enemy shot spawned"
    f = sp[0][0]
    if abs(f - 24) > 1:
        return "first enemy shot at frame %d, expected 24 +-1" % f
    return True


def _check_eshot_cadence(t):
    sp = _eshot_spawn_frames(t)
    for (f, new) in sp:
        if len(new) != 1:
            return "frame %d: %d enemy shots spawned at once" % (f, len(new))
    fr = [f for (f, _n) in sp]
    for a, b in zip(fr, fr[1:]):
        if abs((b - a) - 24) > 1:
            return "enemy shot spacing %d frames (%d->%d), expected 24 +-1" % (b - a, a, b)
    if len(fr) < 10:
        return "only %d enemy shots in the run" % len(fr)
    return True


def _check_eshot_spawn_pos(t):
    en = dict(_series(t, "enemies"))
    ne = dict(_series(t, "n_enemies"))
    prev_n = 24.0
    for (f, new) in _eshot_spawn_frames(t):
        for (x, y) in new:
            if not any(abs(y - sy) < 0.01 for sy in ESHOT_SPAWN_Y):
                return "frame %d: enemy shot spawned at y=%.4f" % (f, y)
            matched = any(abs(x - ex) < 0.01 and abs(y - (ey - 20)) < 0.01
                          for (ex, ey) in en[f])
            if not matched and ne[f] >= prev_n:
                return "frame %d: enemy shot at (%.3f, %.3f) under no enemy" % (f, x, y)
        prev_n = ne[f]
    return True


def _check_eshot_motion(t):
    es = _series(t, "eshots")
    alive = dict(_series(t, "alive"))
    prev, prev_alive = (), True
    for (f, cur) in es:
        removed, _new = _diff(prev, cur, -ESHOT_V)
        died = prev_alive and not alive[f]
        hits = [s for s in removed if s[1] >= PF_BOTTOM]
        if hits and not died:
            return "frame %d: enemy shot(s) %r vanished inside the playfield, ship not hit" % (f, hits)
        if died and not hits:
            return "frame %d: ship destroyed without an enemy shot being consumed" % f
        prev, prev_alive = cur, alive[f]
    return True


def _check_shots(t):
    """Player shots: spawn at (ship x, SHOT_SPAWN_Y); move +640/s; vanish only by
    leaving the playfield (y > 1000) or by a hit, and hits == pontos."""
    ships = dict(_series(t, "ship"))
    pts = dict(_series(t, "pontos"))
    prev, hits = (), 0
    for (f, cur) in _series(t, "shots"):
        removed, new = _diff(prev, cur, SHOT_V)
        for (x, y) in new:
            if abs(y - SHOT_SPAWN_Y) > 0.01 or abs(x - ships[f][0]) > 0.01:
                return "frame %d: new shot at (%.3f, %.3f), ship at %r" % (f, x, y, ships[f])
        hits += sum(1 for (_x, y) in removed if y <= PF_TOP)
        if hits != pts[f]:
            return "frame %d: %d shots consumed by hits but pontos=%r" % (f, hits, pts[f])
        prev = cur
    return True


def _shot_spawn_frames(t):
    out = []
    for (f, cur) in _series(t, "shots"):
        if any(abs(y - SHOT_SPAWN_Y) < 0.01 for (_x, y) in cur):
            out.append(f)
    return out


def _check_cadence(t):
    fr = _shot_spawn_frames(t)
    if not fr:
        return "no shot fired"
    press = t.input_frame("key", 0)
    if fr[0] != press:
        return "first shot at frame %r, SPACE delivered at %r" % (fr[0], press)
    for a, b in zip(fr, fr[1:]):
        if b - a < 12 or b - a > 13:
            return "shot spacing %d frames (%d->%d), expected 12 or 13" % (b - a, a, b)
    return True


def _check_shot_count(t):
    n = len(_shot_spawn_frames(t))
    return True if n in (5, 6) else "%d shots in 61 held frames, expected 5 or 6" % n


def _check_ship_steps(t):
    prev = None
    for (f, s) in _series(t, "ship"):
        if prev is not None:
            dx = s[0] - prev[0]
            ok = (abs(dx) < EPS or abs(abs(dx) - SHIP_V) < 1e-6
                  or abs(s[0] - 40.0) < EPS or abs(s[0] - 960.0) < EPS)
            if not ok:
                return "frame %d: ship x step %.6f" % (f, dx)
        prev = s
    return True


def _check_move_short(t):
    x, y = t.end("ship")
    for n in (30, 31):
        if abs(x - (500.0 + n * SHIP_V)) < 1e-6 and abs(y - 70.0) < EPS:
            return True
    return "ship ended at (%.4f, %.4f), expected x=670 (30 frames) or 675.67 (31)" % (x, y)


def _check_column_cleared(t):
    en = t.end("enemies")
    xs = sorted(set(round(x, 3) for x in _xs(en)))
    if len(en) != 21 or len(xs) != 7:
        return "expected 21 enemies in 7 columns, got %d in %d" % (len(en), len(xs))
    for cx in xs:
        if sum(1 for x in _xs(en) if abs(x - cx) < 0.01) != 3:
            return "column %.3f does not have 3 enemies" % cx
    ship_x = t.end("ship")[0]
    if min(abs(cx - ship_x) for cx in xs) < 45 - 1:
        return "a column near the ship (x=%.2f) survived: %r" % (ship_x, xs)
    return True


def _check_no_overlap(t):
    ships = dict(_series(t, "ship"))
    alive = dict(_series(t, "alive"))
    en = dict(_series(t, "enemies"))
    es = dict(_series(t, "eshots"))
    for (f, shots) in _series(t, "shots"):
        for (x, y) in shots:
            for (ex, ey) in en[f]:
                if abs(x - ex) < 3 and abs(y - ey) < 12:
                    return "frame %d: live shot (%.1f,%.1f) sits on enemy (%.1f,%.1f)" % (f, x, y, ex, ey)
        if alive[f]:
            sx, sy = ships[f]
            for (x, y) in es[f]:
                if abs(x - sx) < 3 and abs(y - sy) < 12:
                    return "frame %d: live red laser (%.1f,%.1f) sits on the ship" % (f, x, y)
    return True


def _check_after_death(t):
    d = _death_frame(t)
    if d is None:
        return True
    ships = _series(t, "ship")
    at_d = dict(ships)[d]
    for (f, s) in ships:
        if f >= d and (abs(s[0] - at_d[0]) > EPS or abs(s[1] - at_d[1]) > EPS):
            return "frame %d: dead ship moved to %r" % (f, s)
    for (f, a) in _series(t, "alive"):
        if f >= d and a:
            return "frame %d: ship alive again" % f
    for f in _shot_spawn_frames(t):
        if f > d:
            return "frame %d: player shot spawned after ship death (frame %d)" % (f, d)
    return True


def _check_fleet_frozen(t):
    c = t.input_frame("cell", 0)
    if c is None:
        return "cell write not delivered"
    en = _series(t, "enemies")
    vel = _series(t, "vel")
    base = None
    for (f, v) in vel:
        if f >= c and v != 0:
            return "frame %d: velocidade %r after being set to 0" % (f, v)
    for (f, e) in en:
        if f > c:
            xs = set(round(x, 6) for x in _xs(e))
            if base is None:
                base = xs
            elif not xs <= base:
                return "frame %d: frozen fleet moved" % f
    return True


def _check_fleet_continues_after_death(t):
    d = _death_frame(t)
    if d is None:
        return True
    en = _series(t, "enemies")
    after = [min(_xs(e)) for (f, e) in en if f >= d]
    if len(after) > 2 and abs(after[-1] - after[0]) < EPS:
        return "fleet stopped after the ship died"
    return True


# ---------------------------------------------------------------- expectations

G = "docs/pt/guide/index.html"
T = "docs/pt/tutorial/05-naves.html"

EXPECT = [
    # --- startup
    Expect(id="E1", level="L0", cite=T + " (passo: 24 naves, três linhas de oito)",
           text="The fleet starts with 24 enemies (no hit is possible on frame 1).",
           check=at(1, "n_enemies", lambda v: v == 24), scenarios=("*",)),
    Expect(id="E2", level="L1", cite=T + " (A posição; frota anda 80 px/s)",
           text="After frame 1 the enemies sit on the 8x3 grid x=185+90c, y=720-70r, shifted right by 80/60.",
           check=at(1, "enemies", lambda v: close(
               v, tuple(sorted((185 + 90 * c + FLEET_V, 720.0 - 70 * r)
                               for r in range(3) for c in range(8))), 1e-6)),
           scenarios=("idle",)),
    Expect(id="E3", level="L0", cite=T + " (A posição: y 720, 650, 580; frota só anda em x)",
           text="Enemy centres keep y in {580, 650, 720} for the whole run (the pulse scales about the centre).",
           check=always("enemies", lambda v: all(any(abs(y - r) < 1e-6 for r in ROWS_Y) for (_x, y) in v)),
           scenarios=("*",)),
    Expect(id="E4", level="L1", cite=T + " (A nave nasce em center=(500, 70))",
           text="With no key pressed on frame 1, the ship is at (500, 70).",
           check=at(1, "ship", lambda v: close(v, (500.0, 70.0), 1e-6)),
           scenarios=("idle", "shoot_gap")),
    Expect(id="E5", level="L1", cite=G + "#spr-hit-medir (sprite.width / height: o tamanho que você deu)",
           text="The ship's height reads 45, the height= it was given.",
           check=always("ship_height", lambda v: abs(v - 45.0) < 1e-6), scenarios=("*",)),
    Expect(id="E6", level="L0", cite=T + " (glow liga o brilho)",
           text="nave.glow reads True.", check=always("glow", lambda v: bool(v)), scenarios=("idle",)),
    Expect(id="E7", level="L0", cite=T + " (O placar: st.pontos, texto ligado com @=)",
           text="On frame 1 the score is 0 and the HUD reads 'Pontos 0'.",
           check=all_of(at(1, "pontos", lambda v: v == 0), at(1, "placar", lambda v: v == "Pontos 0")),
           scenarios=("*",)),
    Expect(id="E8", level="L0", cite=T + " (o texto ligado com @= acompanha sozinho); design/Scena Design.md#frame-order (flush before sample)",
           text="Every sampled frame the HUD text equals 'Pontos {st.pontos}'.",
           check=custom(lambda t: all(v == "Pontos %d" % int(p) for (v, p) in
                                      zip(t.values("placar"), t.values("pontos")))
                        or "HUD text lags or differs from st.pontos"),
           scenarios=("*",)),
    Expect(id="E9", level="L1", cite=G + "#desenhar-text (top_left= prende esse ponto da caixa)",
           text="The HUD stays pinned at top_left=(20, 780) while its text changes.",
           check=always("placar_tl", lambda v: close(v, (20.0, 780.0), 1e-6)), scenarios=("*",)),
    # --- score / fleet bookkeeping
    Expect(id="E10", level="L0", cite=T + " (Um tiro, um inimigo; st.pontos += 1 no acerto)",
           text="pontos + enemies alive == 24 on every frame: only hits remove enemies and each hit scores 1.",
           check=custom(lambda t: all(int(p) + int(n) == 24 for (p, n) in
                                      zip(t.values("pontos"), t.values("n_enemies")))
                        or "pontos + inimigos != 24"),
           scenarios=("*",)),
    Expect(id="E11", level="L0", cite=T + " (só você atira; sem espaço não há tiro)",
           text="With nothing pressed: no player shot ever exists, the score stays 0, all 24 enemies survive, the ship never moves.",
           check=all_of(always("shots", lambda v: len(v) == 0), always("pontos", lambda v: v == 0),
                        always("n_enemies", lambda v: v == 24),
                        always("ship", lambda v: close(v, (500.0, 70.0), 1e-6))),
           scenarios=("idle",)),
    Expect(id="E12", level="L1", cite=T + " (velocidade em st.velocidade; No quadro seguinte, o grupo inteiro anda)",
           text="Each frame the fleet moves by (previous frame's st.velocidade) * dt in x, starting at +80/60.",
           check=custom(_check_fleet_step), scenarios=("idle",)),
    Expect(id="E13", level="L0", cite=T + " (A pergunta: >960 -> -80, <40 -> 80; dizer o lado)",
           text="st.velocidade is -80 on any frame where some enemy x > 960, 80 where some x < 40, otherwise unchanged.",
           check=custom(_check_bounce_rule), scenarios=("idle",)),
    Expect(id="E14", level="L1", cite=T + " (ponta direita começa em x 815; passa de 960 em menos de dois segundos)",
           text="In the idle run the fleet reverses at frame 109 (815+80t > 960) and again at frame 327 (min x < 40), +-1.",
           check=custom(_check_reversal_frames), scenarios=("idle",)),
    Expect(id="E15", level="L2", cite=T + " (os mesmos limites da nave, 40 e 960)",
           text="Enemy centres stay in [40 - 80/60, 960 + 80/60]: one frame of overshoot is the only slop.",
           check=always("enemies", lambda v: all(40 - FLEET_V - 1e-6 <= x <= 960 + FLEET_V + 1e-6 for x in _xs(v))),
           scenarios=("*",)),
    Expect(id="E16", level="L0", cite=T + " (velocidade vai para st.velocidade; muda só além de 40 / 960)",
           text="After st.velocidade is set to 0 it stays 0 and the fleet's x positions never change again.",
           check=custom(_check_fleet_frozen), scenarios=FROZEN),
    # --- pulse
    Expect(id="E17", level="L2", cite=G + "#mover-pose (scale_to: fator absoluto) + suite-yoyo",
           text="Every enemy's scale stays within [1, 1.08] (yoyo between 1 and 1.08).",
           check=always("scales", lambda v: all(1 - 1e-6 <= s <= 1.08 + 1e-6 for s in v)), scenarios=("*",)),
    Expect(id="E18", level="L1", cite=T + " (cresce em 0.45 s, encolhe, ida e volta 0.9 s; frota respira junta)",
           text="Every enemy's scale = 1 + 0.08*triangle(clock.time/0.45) (linear legs), all in phase, tol 0.006.",
           check=custom(_check_scale_phase), scenarios=("idle", "hit_column"), guess=True),
    # --- enemy fire
    Expect(id="E19", level="L1", cite=G + "#agendar-timers (@every no módulo: o timer começa já; primeiro dt desde run())",
           text="The first red laser appears at frame 24 (t = 0.4 s), +-1 frame.",
           check=custom(_check_first_eshot), scenarios=("idle",)),
    Expect(id="E20", level="L1", cite=T + " (a cada 0.4 s, uma nave sorteada solta um laser)",
           text="Red lasers spawn one at a time, every 24 frames (+-1), while enemies remain.",
           check=custom(_check_eshot_cadence), scenarios=("idle", "death")),
    Expect(id="E21", level="L1", cite=T + " (Nasce 20 pixels abaixo da nave sorteada); design/Scena Design.md#frame-order (timers after update)",
           text="Each new red laser is at (enemy x, enemy y - 20) of a live enemy in that frame, not yet moved.",
           check=custom(_check_eshot_spawn_pos), scenarios=("*",)),
    Expect(id="E22", level="L1", cite=T + " (desce 400 px/s; leave_playfield apaga) + " + G + "#reagir-bounds",
           text="Red lasers fall 400/60 per frame and vanish only below y=-200 or on the frame they destroy the ship.",
           check=custom(_check_eshot_motion), scenarios=("*",)),
    Expect(id="E23", level="L0", cite=T + " (rotate_to(180) dá meia volta)",
           text="Every red laser's angle is 180 (mod 360).",
           check=always("eshot_angles", lambda v: all(abs(((a % 360.0) - 180.0)) < 1e-6 for a in v)),
           scenarios=("*",)),
    Expect(id="E24", level="L2", cite=G + "#reagir-bounds (pad 0.25 -> y -200..1000)",
           text="Red lasers never sit below y=-200 and at most 7 exist at once (lifetime <= 2.25 s at one per 0.4 s).",
           check=always("eshots", lambda v: len(v) <= 7 and all(y >= PF_BOTTOM - 1e-6 for (_x, y) in v)),
           scenarios=("*",)),
    # --- ship movement
    Expect(id="E25", level="L1", cite=T + " (340 * dt são 340 pixels por segundo)",
           text="RIGHT held 30 frames moves the ship to x=500+30*340/60=670 (31 if the release lands a frame later), y stays 70.",
           check=custom(_check_move_short), scenarios=("move_short",)),
    Expect(id="E26", level="L1", cite=T + " (move_by por frame, depois confine)",
           text="Per frame the ship's x changes by 0 or exactly 340/60, unless it lands on a fence edge (40 or 960).",
           check=custom(_check_ship_steps), scenarios=("*",)),
    Expect(id="E27", level="L2", cite=G + "#mover-confine; " + T + " (x vai de 40 a 960)",
           text="The ship's centre stays within x in [40, 960] and y == 70 on every frame.",
           check=always("ship", lambda v: 40 - 1e-6 <= v[0] <= 960 + 1e-6 and abs(v[1] - 70) < 1e-6),
           scenarios=("*",)),
    Expect(id="E28", level="L1", cite=T + " (Segure uma seta: a nave para na borda)",
           text="Holding RIGHT pins the ship at x=960 (reached ~82 frames in) and it stays there.",
           check=all_of(eventually("ship", lambda v: abs(v[0] - 960) < 1e-6, within=90),
                        at_end("ship", lambda v: abs(v[0] - 960) < 1e-6)),
           scenarios=("right_wall",)),
    Expect(id="E29", level="L1", cite=T + " (Segure uma seta: a nave para na borda)",
           text="Holding LEFT pins the ship at x=40 (reached ~82 frames in) and it stays there.",
           check=all_of(eventually("ship", lambda v: abs(v[0] - 40) < 1e-6, within=90),
                        at_end("ship", lambda v: abs(v[0] - 40) < 1e-6)),
           scenarios=("left_wall",)),
    # --- player fire
    Expect(id="E30", level="L1", cite=T + " (laser 28 px acima do centro; grupo tiros sobe 640 px/s); design/Scena Design.md#frame-order",
           text="Player shots spawn at (ship x, 98) and are moved in the same update, so read y=98+640/60; then rise 640/60 per frame; each vanishing below y=1000 is a hit and hits == pontos.",
           check=custom(_check_shots), scenarios=("*",)),
    Expect(id="E31", level="L0", cite=G + "#agendar-ready (A primeira chamada já devolve True; no máximo uma vez por intervalo)",
           text="The first shot fires on the frame SPACE arrives; later shots are 12 or 13 frames apart (0.2 s).",
           check=custom(_check_cadence), scenarios=("shoot_gap",)),
    Expect(id="E32", level="L1", cite=T + " (no máximo cinco tiros por segundo)",
           text="Holding SPACE for 61 frames fires 5 or 6 shots.",
           check=custom(_check_shot_count), scenarios=("shoot_gap",)),
    Expect(id="E33", level="L2", cite=G + "#reagir-bounds; " + T + " (O laser some 200 pixels acima da borda)",
           text="No player shot is ever above y=1000 (top of the playfield).",
           check=always("shots", lambda v: all(y <= PF_TOP + 1e-6 for (_x, y) in v)), scenarios=("*",)),
    Expect(id="E34", level="L0", cite=T + " (A posição: colunas 90 px apart)",
           text="Shots from x=500 pass between columns 455 and 545 (frozen fleet): the score stays 0. Assumes enemy art narrower than ~80 px at height 40.",
           check=always("pontos", lambda v: v == 0), scenarios=("shoot_gap",), guess=True),
    Expect(id="E35", level="L0", cite=T + " (Um tiro, um inimigo; destruir o tiro impede os outros)",
           text="Firing ~4 shots under column 545 clears exactly that column: score 3, 21 enemies in 7 full columns, and it stays so.",
           check=all_of(eventually("pontos", lambda v: v == 3, within=200),
                        at_end("pontos", lambda v: v == 3), custom(_check_column_cleared)),
           scenarios=("hit_column",)),
    Expect(id="E36", level="L2", cite=G + "#colisao-collide (enter no primeiro frame de sobreposição; objeto rápido)",
           text="After collisions run, no live blue shot sits on an enemy centre and no red laser sits on the live ship (|dx|<3, |dy|<12; centres of solid art).",
           check=custom(_check_no_overlap), scenarios=("*",)),
    # --- ship death
    Expect(id="E37", level="L0", cite=T + " (Depois do destroy: if nave; tiros e frota ficam fora) + " + G + " is_alive row",
           text="Once the ship is destroyed it stays destroyed, its centre no longer changes, and no new player shot appears.",
           check=custom(_check_after_death), scenarios=("*",)),
    Expect(id="E38", level="L0", cite=T + " (o jogo continua sem você)",
           text="After the ship dies the fleet keeps moving (idle run, if a death happens).",
           check=custom(_check_fleet_continues_after_death), scenarios=("idle",)),
    Expect(id="E39", level="L0", cite=T + " (o laser inimigo precisa derrubar a nave)",
           text="Parked under column 545 for ~9 s (about 22 red lasers, 3 of 24 enemies above the ship), the ship gets hit. Assumes the seeded draws pick that column at least once (~95%).",
           check=eventually("alive", lambda v: not v), scenarios=("death",), guess=True),
]
