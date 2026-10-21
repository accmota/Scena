"""Spec A for examples/naves_1.py (tutorial 05), written from the docs only.

Frame model used throughout (design/Scena Design.md "Frame order"):
  1 clock tick + input, 2 update(dt), 3 process tick (tweens, timers -> @every),
  4 collision, 5 @leave_playfield, ... then the harness samples.
So: a player shot is created in update and moved by the same update (first
sample at y = 98 + 640/60); an enemy laser is created by @every in step 3 and is
first sampled at its spawn y (enemy y - 20), moved from the next frame on.
"""

from program_support import (Scenario, Expect, wait, wait_s, click_widget, click,
    key, key_down, key_up, move, scroll, set_cell, always, never, at, at_end,
    eventually, steady, all_of, custom, close)
import math

FILES_READ = [
    "examples/naves_1.py",
    "docs/pt/tutorial/05-naves.html",
    "design/Scena Design.md#frame-order",
    "docs/pt/guide/index.html#frame-clock",
    "docs/pt/guide/index.html#frame-teclado",
    "docs/pt/guide/index.html#agendar-timers",
    "docs/pt/guide/index.html#agendar-ready",
    "docs/pt/guide/index.html#mover-confine",
    "docs/pt/guide/index.html#mover-pose (scale_to, .angle/.scale)",
    "docs/pt/guide/index.html#suite-loops / #suite-yoyo",
    "docs/pt/guide/index.html#mundo-grupos",
    "docs/pt/guide/index.html#colocar-pais (game_view, playfield)",
    "docs/pt/guide/index.html#reagir-bounds",
    "docs/pt/guide/index.html#colisao-collide (+ #colisao-rapido)",
    "docs/pt/guide/index.html#desenhar-sprite (Sprite height=)",
    "docs/pt/guide/index.html line ~2114 (destroy: `if nave:` false, .center still reads)",
]

DT = 1.0 / 60.0
SHIP_STEP = 340.0 * DT          # 5.6667 per frame
SHOT_STEP = 640.0 * DT          # 10.6667 per frame
LASER_STEP = 400.0 * DT         # 6.6667 per frame
FLEET_STEP = 80.0 * DT          # 1.3333 per frame
BASE_X = [185.0 + c * 90.0 for c in range(8)]
ROWS_Y = (720.0, 650.0, 580.0)
LASER_SPAWN_Y = tuple(y - 20.0 for y in ROWS_Y)   # 700, 630, 560
SHOT_FIRST_Y = 70.0 + 28.0 + SHOT_STEP            # 108.667


# --------------------------------------------------------------------- probes

PROBES = {
    "pontos": lambda p: p.st.pontos,
    "velocidade": lambda p: p.st.velocidade,
    "placar": lambda p: p.placar.text,
    "placar_tl": lambda p: p.placar.top_left,
    "n_inimigos": lambda p: p.group["inimigos"].count,
    "inimigos_x": lambda p: tuple(sorted(float(e.center.x) for e in p.group["inimigos"])),
    "inimigos_y": lambda p: tuple(sorted(float(e.center.y) for e in p.group["inimigos"])),
    # Revised (DOC-SILENT, PM6): .height is the size given; the drawn size is .box.
    "inimigos_h": lambda p: tuple(float(e.box.height) for e in p.group["inimigos"]),
    "n_tiros": lambda p: p.group["tiros"].count,
    "tiros": lambda p: tuple((float(s.center.x), float(s.center.y)) for s in p.group["tiros"]),
    "n_tiros_inimigos": lambda p: p.group["tiros_inimigos"].count,
    "tiros_inimigos": lambda p: tuple((float(s.center.x), float(s.center.y))
                                      for s in p.group["tiros_inimigos"]),
    "tiros_inimigos_ang": lambda p: tuple(float(s.angle) for s in p.group["tiros_inimigos"]),
    "nave_vivo": lambda p: bool(p.nave),
    "nave_x": lambda p: p.nave.center.x,
    "nave_y": lambda p: p.nave.center.y,
    "nave_h": lambda p: p.nave.height,
    "nave_glow": lambda p: p.nave.glow,
    "tempo": lambda p: p.clock.time,
}


# ------------------------------------------------------------------ scenarios

SCENARIOS = {
    # nothing pressed: fleet goes right, turns at frame 109, turns again at 327
    "parado": Scenario(params={}, seed=0, steps=[wait(400)]),
    # LEFT held 30 frames, ship cannot have been hit yet (first laser contact >= ~frame 68)
    "esquerda": Scenario(params={}, seed=0, steps=[wait(5), key("LEFT", frames=30), wait(10)]),
    # RIGHT held long enough to reach the fence at x = 960
    "direita_borda": Scenario(params={}, seed=0, steps=[wait(2), key("RIGHT", frames=85), wait(3)]),
    # SPACE held 60 frames at a standing ship (x = 500)
    "atira": Scenario(params={}, seed=0, steps=[wait(2), key("SPACE", frames=60), wait(100)]),
    # fleet frozen with column 3 right above the ship; then keys after (probable) death
    "congelada": Scenario(params={}, seed=0, steps=[
        wait(34), set_cell("st.velocidade", 0), wait(480),
        key("LEFT", frames=30), key("SPACE", frames=20), wait(5)]),
}

ALL = ("*",)
MOVING = ("parado", "esquerda", "direita_borda", "atira")


# -------------------------------------------------------------------- helpers

def _vals(t, probe):
    return [v for (_f, _tm, v) in t.series(probe)]


def _frames(t, probe):
    return [(f, v) for (f, _tm, v) in t.series(probe)]


def _death_frame(t):
    for f, v in _frames(t, "nave_vivo"):
        if not v:
            return f
    return None


def _new_items(prev, curr, step, tol=1e-3):
    """Items of curr that are not a prev item moved by (0, step)."""
    pool = list(prev)
    fresh = []
    for (x, y) in curr:
        hit = None
        for i, (px, py) in enumerate(pool):
            if abs(px - x) < tol and abs((py + step) - y) < tol:
                hit = i
                break
        if hit is None:
            fresh.append((x, y))
        else:
            pool.pop(hit)
    return fresh


def _fleet_model(n_frames):
    """Tutorial 'Vai e volta' rule, frame by frame: offset of the fleet."""
    off, v, out = 0.0, 80.0, []
    for _ in range(n_frames):
        off += v * DT
        if max(BASE_X) + off > 960:
            v = -80.0
        if min(BASE_X) + off < 40:
            v = 80.0
        out.append((off, v))
    return out


# ---- custom checks

def chk_fleet_x_frame1(t):
    xs = t.at_frame(1, "inimigos_x")
    want = sorted(b + FLEET_STEP for b in BASE_X for _ in range(3))
    if len(xs) != 24:
        return "expected 24 xs, got %d" % len(xs)
    for a, b in zip(xs, want):
        if abs(a - b) > 1e-3:
            return "fleet x at frame 1 %r != %r" % (a, b)
    return True


def chk_rows(t):
    ys = t.at_frame(1, "inimigos_y")
    for row in ROWS_Y:
        n = sum(1 for y in ys if abs(y - row) < 1e-6)
        if n != 8:
            return "row y=%s has %d enemies, expected 8" % (row, n)
    return True


def chk_rows_constant(t):
    for f, ys in _frames(t, "inimigos_y"):
        for y in ys:
            if min(abs(y - r) for r in ROWS_Y) > 1e-6:
                return "frame %d: enemy y %r is not one of the rows" % (f, y)
    return True


def chk_fleet_model(t):
    series = _frames(t, "inimigos_x")
    model = _fleet_model(len(series))
    for (f, xs), (off, _v) in zip(series, model):
        want = sorted(b + off for b in BASE_X for _ in range(3))
        if len(xs) != 24:
            return "frame %d: %d enemies (none should die here)" % (f, len(xs))
        for a, b in zip(xs, want):
            if abs(a - b) > 1e-3:
                return "frame %d: fleet x %r, model %r" % (f, a, b)
    return True


def chk_breath(t):
    # tween starts in the script body; process tick k advances k/60 s
    for frame, h_want in ((13, 40.0 * (1 + 0.08 * 13 / 27.0)), (27, 43.2), (54, 40.0)):
        hs = t.at_frame(frame, "inimigos_h")
        for h in hs:
            if abs(h - h_want) > 0.25:
                return "frame %d: enemy height %r, expected ~%r" % (frame, h, h_want)
    return True


def chk_same_breath(t):
    for f, hs in _frames(t, "inimigos_h"):
        if hs and max(hs) - min(hs) > 1e-6:
            return "frame %d: enemies breathe out of step %r..%r" % (f, min(hs), max(hs))
    return True


def chk_heights_band(t):
    for f, hs in _frames(t, "inimigos_h"):
        for h in hs:
            if not (40.0 - 0.01 <= h <= 43.2 + 0.01):
                return "frame %d: enemy height %r outside [40, 43.2]" % (f, h)
    return True


def chk_lasers_spawn_and_move(t):
    lasers = _frames(t, "tiros_inimigos")
    xs_by_frame = dict(_frames(t, "inimigos_x"))
    prev = ()
    for f, curr in lasers:
        fresh = _new_items(prev, curr, -LASER_STEP)
        if len(fresh) > 1:
            return "frame %d: %d enemy lasers appeared at once" % (f, len(fresh))
        for (x, y) in fresh:
            if min(abs(y - s) for s in LASER_SPAWN_Y) > 1e-6:
                return "frame %d: new enemy laser at y=%r, expected one of %r" % (f, y, LASER_SPAWN_Y)
            exs = xs_by_frame.get(f, ())
            if not exs or min(abs(x - e) for e in exs) > 1e-6:
                return "frame %d: new enemy laser x=%r is not an enemy's x" % (f, x)
        prev = curr
    return True


def chk_laser_angle(t):
    for f, angs in _frames(t, "tiros_inimigos_ang"):
        for a in angs:
            d = (a - 180.0) % 360.0
            if min(d, 360.0 - d) > 1e-6:
                return "frame %d: enemy laser angle %r, expected 180" % (f, a)
    return True


def chk_lasers_bounded(t):
    for f, ls in _frames(t, "tiros_inimigos"):
        if len(ls) > 7:
            return "frame %d: %d enemy lasers alive (leak?)" % (f, len(ls))
        for (_x, y) in ls:
            if y < -200.0 - 1e-6:
                return "frame %d: enemy laser at y=%r below playfield" % (f, y)
    return True


def chk_esquerda(t):
    xs = _frames(t, "nave_x")
    prev = 500.0
    moved = 0
    for f, x in xs:
        d = x - prev
        if abs(d + SHIP_STEP) < 1e-6:
            moved += 1
        elif abs(d) > 1e-6:
            return "frame %d: ship moved %r (expected 0 or -%r)" % (f, d, SHIP_STEP)
        prev = x
    if moved != 30:
        return "ship moved on %d frames, expected 30 (LEFT held 30 frames)" % moved
    if abs(prev - 330.0) > 0.01:
        return "final ship x %r, expected 330" % prev
    return True


def chk_direita_borda(t):
    press = t.input_frame("key", 0)
    for f, x in _frames(t, "nave_x"):
        if f >= press + 82 and t.at_frame(f, "nave_vivo"):
            if abs(x - 960.0) > 1e-6:
                return "frame %d: ship x %r, expected clamped at 960" % (f, x)
    return True


def _shot_spawns(t):
    out = []
    prev = ()
    for f, curr in _frames(t, "tiros"):
        for (x, y) in _new_items(prev, curr, SHOT_STEP):
            out.append((f, x, y))
        prev = curr
    return out


def chk_shot_count(t):
    sp = _shot_spawns(t)
    if len(sp) != 5:
        return "%d shots created while SPACE held 60 frames, expected 5" % len(sp)
    frames = [f for (f, _x, _y) in sp]
    if frames[0] != t.input_frame("key", 0):
        return "first shot at frame %d, press at %d" % (frames[0], t.input_frame("key", 0))
    for a, b in zip(frames, frames[1:]):
        if not (12 <= b - a <= 13):
            return "shots at frames %d and %d: gap must be 12 (0.2 s) or 13" % (a, b)
    return True


def chk_shot_spawn_place(t):
    for (f, x, y) in _shot_spawns(t):
        if abs(x - 500.0) > 1e-6 or abs(y - SHOT_FIRST_Y) > 1e-3:
            return "frame %d: new shot at (%r, %r), expected (500, %r)" % (f, x, y, SHOT_FIRST_Y)
    return True


def chk_shots_below_top(t):
    for f, ss in _frames(t, "tiros"):
        for (_x, y) in ss:
            if y > 1000.0 + 1e-6:
                return "frame %d: shot at y=%r above playfield top 1000" % (f, y)
    return True


def chk_one_shot_one_enemy(t):
    ne = _frames(t, "n_inimigos")
    nt = dict(_frames(t, "n_tiros"))
    for (f0, e0), (f1, e1) in zip(ne, ne[1:]):
        killed = e0 - e1
        shots_gone = nt[f0] + 1 - nt[f1]     # at most one shot created per frame
        if killed > max(shots_gone, 0):
            return "frame %d: %d enemies died but at most %d shots vanished" % (f1, killed, shots_gone)
    return True


def chk_placar(t):
    pts = dict(_frames(t, "pontos"))
    for f, txt in _frames(t, "placar"):
        want = "Pontos %d" % int(pts[f])
        if txt != want:
            return "frame %d: placar %r, expected %r" % (f, txt, want)
    return True


def chk_points_vs_fleet(t):
    pts = dict(_frames(t, "pontos"))
    for f, n in _frames(t, "n_inimigos"):
        if int(pts[f]) != 24 - int(n):
            return "frame %d: pontos %r but %r enemies left" % (f, pts[f], n)
    return True


def chk_points_monotone(t):
    v = _vals(t, "pontos")
    for a, b in zip(v, v[1:]):
        if b < a:
            return "pontos went down %r -> %r" % (a, b)
    return True


def chk_no_ghost_hit(t):
    alive = dict(_frames(t, "nave_vivo"))
    nx = dict(_frames(t, "nave_x"))
    for f, ls in _frames(t, "tiros_inimigos"):
        if not alive[f]:
            continue
        for (x, y) in ls:
            if abs(x - nx[f]) < 3.0 and 40.0 < y < 100.0:
                return "frame %d: enemy laser (%r, %r) overlaps the live ship" % (f, x, y)
    return True


def chk_no_revive(t):
    d = _death_frame(t)
    if d is None:
        return True
    for f, v in _frames(t, "nave_vivo"):
        if f >= d and v:
            return "ship alive again at frame %d after dying at %d" % (f, d)
    return True


def chk_death_cause(t):
    d = _death_frame(t)
    if d is None or d == 1:
        return True
    ls = t.at_frame(d - 1, "tiros_inimigos")
    x = t.at_frame(d - 1, "nave_x")
    for (lx, ly) in ls:
        if abs(lx - x) < 40.0 and 0.0 < ly < 140.0:
            return True
    return "ship died at frame %d with no enemy laser near it the frame before" % d


def chk_frozen(t):
    c = t.input_frame("cell", 0)
    for f, v in _frames(t, "velocidade"):
        if f > c and v != 0:
            return "frame %d: velocidade %r after set to 0" % (f, v)
    return True


def chk_frozen_xs(t):
    c = t.input_frame("cell", 0)
    ref = None
    for f, xs in _frames(t, "inimigos_x"):
        if f <= c:
            continue
        if ref is None:
            ref = xs
        elif len(xs) != len(ref) or any(abs(a - b) > 1e-9 for a, b in zip(xs, ref)):
            return "frame %d: frozen fleet moved" % f
    return True


def chk_after_death(t):
    d = _death_frame(t)
    if d is None:
        return True
    k = t.input_frame("key", 0)
    if k is None or d >= k:
        return True                      # death not before the keys: nothing to say
    x0 = t.at_frame(d, "nave_x")
    for f, x in _frames(t, "nave_x"):
        if f >= d and abs(x - x0) > 1e-9:
            return "frame %d: dead ship moved to %r" % (f, x)
    nt = _frames(t, "n_tiros")
    for (f0, a), (f1, b) in zip(nt, nt[1:]):
        if f1 > d and b > a:
            return "frame %d: a shot was fired after the ship died" % f1
    return True


def chk_world_goes_on(t):
    d = _death_frame(t)
    if d is None:
        return True
    last = t.samples[-1].frame
    if last - d < 30:
        return True
    prev = t.at_frame(d, "tiros_inimigos")
    for f, curr in _frames(t, "tiros_inimigos"):
        if f > d:
            if _new_items(prev, curr, -LASER_STEP):
                return True
            prev = curr
    return "no enemy laser fired after the ship died (game should go on)"


# ------------------------------------------------------------------ expectations

TUT = "docs/pt/tutorial/05-naves.html"

EXPECT = [
    Expect(id="E1", level="L0", cite=TUT + "#A frota",
           text="The fleet starts with 24 enemies in group 'inimigos'.",
           check=at(1, "n_inimigos", lambda v: v == 24), scenarios=ALL),
    Expect(id="E2", level="L0", cite=TUT + "#A frota",
           text="Three rows of eight at y = 720, 650, 580.",
           check=custom(chk_rows), scenarios=ALL),
    Expect(id="E3", level="L1", cite=TUT + "#A frota / #A frota anda",
           text="At frame 1 the columns are at 185 + 90k plus one frame of 80 px/s (tol 1e-3).",
           check=custom(chk_fleet_x_frame1), scenarios=("parado",)),
    Expect(id="E4", level="L0", cite=TUT + "#A nave",
           text="The ship starts at x = 500 and stays at y = 70 forever (only LEFT/RIGHT move it).",
           check=all_of(at(1, "nave_x", lambda v: close(v, 500.0, 1e-6)),
                        always("nave_y", lambda v: close(v, 70.0, 1e-6))),
           scenarios=("parado", "atira", "congelada")),
    Expect(id="E5", level="L0", cite="docs/pt/guide/index.html#desenhar-sprite; " + TUT + "#A nave",
           text="The ship is 45 design units tall and has glow on.",
           check=all_of(at(1, "nave_h", lambda v: close(v, 45.0, 1e-6)),
                        at(1, "nave_glow", lambda v: bool(v))),
           scenarios=("parado",)),
    Expect(id="E6", level="L0", cite=TUT + "#O acerto; docs/pt/guide/index.html#reativo-state",
           text="The score text always reads 'Pontos N' for the current st.pontos (starts 'Pontos 0').",
           check=all_of(at(1, "placar", lambda v: v == "Pontos 0"), custom(chk_placar)),
           scenarios=ALL),
    Expect(id="E7", level="L0", cite=TUT + "#Colisão / #O acerto",
           text="Every point is one destroyed enemy: pontos == 24 - remaining enemies.",
           check=custom(chk_points_vs_fleet), scenarios=ALL),
    Expect(id="E8", level="L0", cite=TUT + "#O acerto",
           text="pontos never decreases.",
           check=custom(chk_points_monotone), scenarios=ALL),
    Expect(id="E9", level="L0", cite=TUT + "#Vai e volta",
           text="st.velocidade is only ever 80 or -80 (said the side, never flipped).",
           check=always("velocidade", lambda v: v in (80, -80)), scenarios=MOVING),
    Expect(id="E10", level="L0", cite=TUT + "#Vai e volta",
           text="Idle: the rightmost enemy passes 960 at frame 109 (815 + 109*80/60 = 960.33), so velocidade turns -80 there.",
           check=all_of(at(108, "velocidade", lambda v: v == 80),
                        at(109, "velocidade", lambda v: v == -80)),
           scenarios=("parado",)),
    Expect(id="E11", level="L0", cite=TUT + "#Vai e volta",
           text="Idle: the leftmost enemy passes below 40 at frame 327 (39.67), so velocidade turns back to 80.",
           check=all_of(at(326, "velocidade", lambda v: v == -80),
                        at(327, "velocidade", lambda v: v == 80)),
           scenarios=("parado",)),
    Expect(id="E12", level="L1", cite=TUT + "#A frota anda / #Vai e volta; design/Scena Design.md#frame-order",
           text="Idle: the whole fleet translates rigidly by velocidade*dt each frame, following the turn rule (tol 1e-3).",
           check=custom(chk_fleet_model), scenarios=("parado",)),
    Expect(id="E13", level="L2", cite=TUT + "#Vai e volta",
           text="No enemy centre goes past [40, 960] by more than one frame of fleet motion (1.34).",
           check=always("inimigos_x", lambda xs: all(40 - FLEET_STEP - 1e-6 <= x <= 960 + FLEET_STEP + 1e-6
                                                     for x in xs)),
           scenarios=MOVING),
    Expect(id="E14", level="L0", cite=TUT + "#Respiram; docs/pt/guide/index.html#suite-about (scale about the centre)",
           text="Enemies never move vertically: every enemy y is always one of the three rows.",
           check=custom(chk_rows_constant), scenarios=ALL),
    Expect(id="E15", revised="DOC-SILENT: .height is the given size under scale; read .box.height (Guia now says so, PM6)", level="L1", cite=TUT + "#Respiram; docs/pt/guide/index.html#suite-yoyo",
           text="Breathing: height 40 grows linearly to 43.2 in 0.45 s and back by 0.9 s (frames 13/27/54, tol 0.25 = ~2 frames).",
           check=custom(chk_breath), scenarios=("parado",), guess=True),
    Expect(id="E16", level="L0", cite=TUT + "#Respiram",
           text="All enemies breathe in the same rhythm: equal heights at every frame.",
           check=custom(chk_same_breath), scenarios=("parado", "congelada")),
    Expect(id="E17", level="L2", cite=TUT + "#Respiram; docs/pt/guide/index.html#mover-pose (scale_to)",
           text="Enemy height always stays within [40, 43.2] (scale 1..1.08 of the 40-unit sprite).",
           check=custom(chk_heights_band), scenarios=ALL, guess=True),
    Expect(id="E18", level="L0", cite="docs/pt/guide/index.html#agendar-timers",
           text="@every(0.4) first fires after one interval: no enemy laser exists at frame 23 (t = 0.383 s).",
           check=at(23, "n_tiros_inimigos", lambda v: v == 0), scenarios=("parado",), guess=True),
    Expect(id="E19", level="L0", cite="docs/pt/guide/index.html#agendar-timers; " + TUT + "#A frota atira",
           text="Idle: by frame 90 exactly three enemy lasers were fired (0.4/0.8/1.2 s) and none can have left or hit yet.",
           check=at(90, "n_tiros_inimigos", lambda v: v == 3), scenarios=("parado",)),
    Expect(id="E20", level="L1", cite=TUT + "#A frota atira; design/Scena Design.md#frame-order",
           text="Each enemy laser appears at a living enemy's x, 20 below its row (700/630/560), at most one per frame, then falls exactly 400/60 per frame.",
           check=custom(chk_lasers_spawn_and_move), scenarios=("parado",)),
    Expect(id="E21", level="L0", cite=TUT + "#A frota atira; docs/pt/guide/index.html#mover-pose",
           text="Every enemy laser has angle 180 (rotate_to without time= is immediate).",
           check=custom(chk_laser_angle), scenarios=ALL),
    Expect(id="E22", level="L2", cite="docs/pt/guide/index.html#reagir-bounds; " + TUT + "#Fora da tela",
           text="Enemy lasers are destroyed on leaving the playfield (y < -200): never sampled below it, and at most 7 alive (lifetime <= 135 frames / one per 24).",
           check=custom(chk_lasers_bounded), scenarios=ALL),
    Expect(id="E23", level="L1", cite=TUT + "#A nave; docs/pt/guide/index.html#frame-teclado",
           text="Holding LEFT 30 frames moves the ship exactly 340/60 per held frame, 0 otherwise: ends at x = 330.",
           check=custom(chk_esquerda), scenarios=("esquerda",)),
    Expect(id="E24", level="L2", cite=TUT + "#Limites; docs/pt/guide/index.html#mover-confine",
           text="The ship centre is always within [40, 960] (confine to game_view.inset(40)).",
           check=always("nave_x", lambda x: 40.0 - 1e-6 <= x <= 960.0 + 1e-6), scenarios=ALL),
    Expect(id="E25", level="L1", cite=TUT + "#Limites; docs/pt/guide/index.html#mover-confine",
           text="Holding RIGHT, a live ship reaches the fence and sits exactly at x = 960 (clamp).",
           check=custom(chk_direita_borda), scenarios=("direita_borda",)),
    Expect(id="E26", level="L0", cite="docs/pt/guide/index.html#agendar-ready; " + TUT + "#Atirar",
           text="SPACE held 60 frames gives exactly 5 shots: first on the press frame (ready is True on first call), then every 12 (or 13) frames.",
           check=custom(chk_shot_count), scenarios=("atira",)),
    Expect(id="E27", level="L1", cite=TUT + "#Atirar / #Os tiros sobem; design/Scena Design.md#frame-order",
           text="A new shot is created at (ship x, 98) and moved by the same update: first sampled at (500, 98 + 640/60); later moves exactly +640/60 per frame.",
           check=custom(chk_shot_spawn_place), scenarios=("atira",)),
    Expect(id="E28", level="L0", cite="docs/pt/guide/index.html#reagir-bounds; " + TUT + "#Fora da tela",
           text="Player shots are destroyed once their centre passes y = 1000: never sampled above it, and all gone 100 frames after release.",
           check=all_of(custom(chk_shots_below_top), at_end("n_tiros", lambda v: v == 0)),
           scenarios=("atira",)),
    Expect(id="E29", level="L0", cite=TUT + "#Colisão",
           text="One shot, one enemy: enemies lost in a frame never exceed shots that vanished in that frame.",
           check=custom(chk_one_shot_one_enemy), scenarios=ALL),
    Expect(id="E30", level="L0", cite=TUT + "#Colisão; docs/pt/guide/index.html#colisao-rapido",
           text="Firing straight up at x = 500 into the advancing fleet scores at least one hit (assumes the auto hitbox covers the art near the centre).",
           check=eventually("pontos", lambda v: v >= 1), scenarios=("atira",), guess=True),
    Expect(id="E31", level="L0", cite=TUT + "#A frota atira (first laser cannot reach y~106 before ~frame 92)",
           text="The ship is alive for the first 60 frames in every scenario.",
           check=always("nave_vivo", lambda v: bool(v), until=60), scenarios=ALL),
    Expect(id="E32", level="L0", cite="docs/pt/guide/index.html (destroy: `if nave:` false)",
           text="Once destroyed the ship never comes back.",
           check=custom(chk_no_revive), scenarios=ALL),
    Expect(id="E33", level="L2", cite=TUT + "#A nave explode; docs/pt/guide/index.html#colisao-rapido",
           text="No enemy laser is ever sampled overlapping the live ship (|dx| < 3, 40 < y < 100): the hit destroys both in the same frame.",
           check=custom(chk_no_ghost_hit), scenarios=ALL),
    Expect(id="E34", level="L2", cite=TUT + "#A nave explode",
           text="The ship only dies when an enemy laser was right next to it the frame before (|dx| < 40, 0 < y < 140).",
           check=custom(chk_death_cause), scenarios=ALL),
    Expect(id="E35", level="L0", cite=TUT + "#Vai e volta (st holds what changes)",
           text="Setting st.velocidade = 0 freezes the fleet: velocidade stays 0 and enemy xs stop changing.",
           check=all_of(custom(chk_frozen), custom(chk_frozen_xs)),
           scenarios=("congelada",)),
    Expect(id="E36", level="L0", cite=TUT + "#A frota atira (random choice)",
           text="With the fleet frozen and column 3 at x~500 over the ship, a laser eventually kills it (assumes seed 0 picks that column within ~20 shots).",
           check=eventually("nave_vivo", lambda v: not v), scenarios=("congelada",), guess=True),
    Expect(id="E37", level="L0", cite=TUT + "#A nave explode (Depois do destroy)",
           text="After death the arrows and SPACE do nothing: the ship's position is frozen and no player shot is created.",
           check=custom(chk_after_death), scenarios=("congelada",)),
    Expect(id="E38", level="L0", cite=TUT + "#A nave explode (o jogo continua sem você)",
           text="After the ship dies the fleet keeps firing (a new enemy laser appears later).",
           check=custom(chk_world_goes_on), scenarios=("congelada", "parado")),
    Expect(id="E39", level="L1", cite="docs/pt/guide/index.html#frame-clock",
           text="clock.time after frame 60 is 1.0 s with fixed dt 1/60.",
           check=at(60, "tempo", lambda v: close(v, 1.0, 1e-6)), scenarios=("parado",)),
    Expect(id="E40", level="L0", cite="docs/pt/guide/index.html#mover-pose (.angle/.scale: Text positioned by anchor)",
           text="The score text keeps its top_left at (20, 780) as its text changes.",
           check=always("placar_tl", lambda v: close(v, (20.0, 780.0), 1e-6)),
           scenarios=("parado", "atira"), guess=True),
]
