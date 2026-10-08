"""Spec A for tests/programs/galaga_acts.py, written from the docs alone.

Geometry used below (W, H = 1000, 800):
  hero born at (500, 70); AREA = game_view.inset(40) -> x in [40, 960];
  fleet Box center (500, 590), 760 x 170, grid(8, 3, gap=16): cell 81 x 46,
  column centres 160.5 + 97 * i, row centres (row 0 on top) 652, 590, 528;
  default playfield = design rect with pad 0.25 -> top edge y = 1000.
"""
from program_support import (Scenario, Expect, wait, wait_s, click_widget, click,
    key, key_down, key_up, move, scroll, set_cell, always, never, at, at_end,
    eventually, steady, all_of, custom, close)
import math

FILES_READ = [
    "tests/programs/galaga_acts.py",
    "design/Act Design.md#concepts",
    "design/Act Design.md#lifetime-the-game-and-the-act",
    "design/Act Design.md#acts-and-modes",
    "design/Act Design.md#change_act",
    "design/Box Design.md (grid gap lines 120-160)",
    "design/Tracks Design.md (construction, centered presets)",
    "docs/pt/guide/index.html#atos",
    "docs/pt/guide/index.html#frame-teclado",
    "docs/pt/guide/index.html#agendar-ready",
    "docs/pt/guide/index.html#ag-call",
    "docs/pt/guide/index.html#colocar-grid",
    "docs/pt/guide/index.html#mover-confine",
    "docs/pt/guide/index.html#mover-move-along",
    "docs/pt/guide/index.html#suite-then",
    "docs/pt/guide/index.html#grp-esperar",
    "docs/pt/guide/index.html#ui-sprite-button",
    "docs/pt/guide/index.html#reagir-bounds",
]

JOGAR = (500, 320)      # SpriteButton center=(W/2, H*0.40)
ZERAR = (500, 240)      # SpriteButton center=(W/2, H*0.30)

COLS = [160.5 + 97 * i for i in range(8)]
ROWS = [652.0, 590.0, 528.0]
FLEET = tuple(sorted((x, y) for x in COLS for y in ROWS))


# --- probes ------------------------------------------------------------------

def _members(p, name):
    return list(p.group[name])


def _first_member(p, name):
    m = _members(p, name)
    return m[0] if m else None


def _xy(e):
    return None if e is None else (float(e.center.x), float(e.center.y))


PROBES = {
    "heroi_n": lambda p: p.group["heroi"].count,
    "inimigo_n": lambda p: p.group["inimigo"].count,
    "tiro_n": lambda p: p.group["tiro"].count,
    "tiro_inimigo_n": lambda p: p.group["tiro_inimigo"].count,
    "chefe_n": lambda p: p.group["chefe"].count,
    "ferido_n": lambda p: p.group["ferido"].count,
    "hero_xy": lambda p: _xy(_first_member(p, "heroi")),
    "tiro_xs": lambda p: tuple(sorted(float(t.center.x) for t in p.group["tiro"])),
    "tiro_ys": lambda p: tuple(sorted(float(t.center.y) for t in p.group["tiro"])),
    "inimigo_xy": lambda p: tuple(sorted((float(e.center.x), float(e.center.y))
                                         for e in p.group["inimigo"])),
    "chefe_xy": lambda p: _xy(_first_member(p, "chefe")),
    "chefe_angle": lambda p: (None if _first_member(p, "chefe") is None
                              else float(_first_member(p, "chefe").angle)),
    "chefe_vida": lambda p: (None if _first_member(p, "chefe") is None
                             else _first_member(p, "chefe").vida),
    "pontos": lambda p: p.st.pontos,
    "vidas": lambda p: p.st.vidas,
    "fase": lambda p: p.st.fase,
    "venceu": lambda p: bool(p.st.venceu),
    "recorde": lambda p: p.st.recorde,
}


# --- scenarios -----------------------------------------------------------------

SCENARIOS = {
    # nothing pressed: the title stays
    "idle": Scenario(params={}, seed=0, steps=[wait(300)]),
    # SPACE on the title starts the game
    "start_space": Scenario(params={}, seed=0, steps=[
        wait(30), key("SPACE"), wait(200)]),
    # the JOGAR SpriteButton starts the game
    "start_click": Scenario(params={}, seed=0, steps=[
        wait(20), click(*JOGAR), wait(60)]),
    # LEFT then RIGHT (clamps at 960) then LEFT (clamps at 40)
    "move": Scenario(params={}, seed=0, steps=[
        click(*JOGAR), wait(10), key("LEFT", frames=30), wait(10),
        key("RIGHT", frames=150), wait(10), key("LEFT", frames=180), wait(10)]),
    # hold SPACE one second before the fleet exists
    "fire": Scenario(params={}, seed=0, steps=[
        click(*JOGAR), wait(5), key("SPACE", frames=60), wait(150)]),
    # move under fleet column 3 (x = 451.5) and shoot it out
    "kill_column": Scenario(params={}, seed=0, steps=[
        click(*JOGAR), wait(5), key("LEFT", frames=9), wait(150),
        key("SPACE", frames=150), wait(60)]),
    # move, shoot, then R: a fresh Fase
    "restart": Scenario(params={}, seed=0, steps=[
        click(*JOGAR), wait(5), key("LEFT", frames=20), wait(180),
        key("SPACE", frames=20), key("R"), wait(120)]),
    # phase 2 via st.fase + R; nobody shoots
    "boss": Scenario(params={}, seed=0, steps=[
        click(*JOGAR), wait(10), set_cell("st.fase", 2), key("R"), wait(560)]),
    # phase 2 while holding SPACE
    "boss_fire": Scenario(params={}, seed=0, steps=[
        click(*JOGAR), wait(10), set_cell("st.fase", 2), key("R"),
        key("SPACE", frames=540), wait(5)]),
    # lose (vidas = 0), R is refused, FimDeJogo, its 10 s timer back to Titulo,
    # then SPACE starts a new game (dt = 1/30 keeps it under 600 frames)
    "lose_wait": Scenario(params={}, seed=0, dt=1 / 30, steps=[
        click(*JOGAR), wait(90), set_cell("st.pontos", 1200),
        set_cell("st.vidas", 0), key("LEFT", frames=20), key("R"), wait(340),
        key("SPACE"), wait(20)]),
    # lose, SPACE skips FimDeJogo, zerar recorde, JOGAR again
    "lose_skip": Scenario(params={}, seed=0, steps=[
        click(*JOGAR), wait(20), set_cell("st.pontos", 700),
        set_cell("st.vidas", 0), wait(120), key("SPACE"), wait(40),
        click(*ZERAR), wait(20), click(*JOGAR), wait(30)]),
}

PLAY_SCENARIOS = ("start_space", "start_click", "move", "fire", "kill_column",
                  "restart", "boss", "boss_fire")
NO_LOSE = ("idle",) + PLAY_SCENARIOS


# --- trace helpers -------------------------------------------------------------

def _dt(t):
    s = t.samples
    return (s[1].time - s[0].time) if len(s) > 1 else 1 / 60


def _frames(t, seconds):
    return int(round(seconds / _dt(t)))


def _first(t, probe, pred, after=0):
    for f, _tm, v in t.series(probe):
        if f >= after and pred(v):
            return f
    return None


def _val(t, frame, probe):
    return t.at_frame(frame, probe)


def _start(t):
    """First frame of the first Fase (the hero exists)."""
    return _first(t, "heroi_n", lambda v: v == 1)


def _close_xy(a, b, tol):
    return a is not None and abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def _need(cond, msg):
    return True if cond else msg


# --- checks --------------------------------------------------------------------

def _start_on_input(prefix, within):
    def fn(t):
        fi = t.input_frame(prefix)
        if fi is None:
            return "no %s input recorded" % prefix
        for f, _tm, v in t.series("heroi_n"):
            if f < fi and v != 0:
                return "hero exists at frame %d, before the %s input (%d)" % (f, prefix, fi)
        f1 = _first(t, "heroi_n", lambda v: v == 1, after=fi)
        if f1 is None or f1 - fi > within:
            return "Fase not built within %d frames of the %s input %d (got %r)" % (
                within, prefix, fi, f1)
        return True
    return fn


def _one_hero_after_start(t):
    f0 = _start(t)
    if f0 is None:
        return "Fase never started"
    for f, _tm, v in t.series("heroi_n"):
        if f >= f0 and v != 1:
            return "heroi count %r at frame %d (expected exactly 1)" % (v, f)
    return True


def _hero_born(t):
    f0 = _start(t)
    if f0 is None:
        return "Fase never started"
    xy = _val(t, f0, "hero_xy")
    return _need(_close_xy(xy, (500, 70), 0.01), "hero born at %r, expected (500, 70)" % (xy,))


def _fleet_timing(t):
    f0 = _start(t)
    a = _val(t, f0 + _frames(t, 1.4), "inimigo_n")
    b = _val(t, f0 + _frames(t, 1.6), "inimigo_n")
    return _need(a == 0 and b == 24, "fleet count %r at +1.4 s, %r at +1.6 s (expected 0, 24)" % (a, b))


def _fleet_grid(t):
    f0 = _start(t)
    got = _val(t, f0 + _frames(t, 3.0), "inimigo_xy")
    if got is None or len(got) != 24:
        return "fleet at +3.0 s has %r members" % (None if got is None else len(got))
    for g, e in zip(got, FLEET):
        if abs(g[0] - e[0]) > 0.5 or abs(g[1] - e[1]) > 0.5:
            return "fleet slot %r, expected %r" % (g, e)
    return True


def _hero_y_70(t):
    for f, _tm, v in t.series("hero_xy"):
        if v is not None and abs(v[1] - 70) > 1e-6:
            return "hero y %r at frame %d" % (v[1], f)
    return True


def _plateaus(t):
    xs = [v[0] for _f, _tm, v in t.series("hero_xy") if v is not None]
    runs, i = [], 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[j + 1] == xs[i]:
            j += 1
        if j - i + 1 >= 5 and (not runs or runs[-1] != xs[i]):
            runs.append(xs[i])
        i = j + 1
    return runs


def _move_left_speed(t):
    r = _plateaus(t)
    if len(r) < 2:
        return "plateaus %r" % (r,)
    return _need(abs(r[0] - 500) < 1e-6 and abs(r[1] - (500 - 340 * 30 / 60)) <= 6.0,
                 "first plateaus %r, expected 500 then 330 +- 6" % (r[:2],))


def _move_clamps(t):
    r = _plateaus(t)
    if len(r) < 4:
        return "plateaus %r (expected 500, ~330, 960, 40)" % (r,)
    return _need(abs(r[2] - 960) < 1e-6 and abs(r[3] - 40) < 1e-6,
                 "clamp plateaus %r, expected 960 then 40" % (r[2:4],))


def _hero_inside_area(t):
    for f, _tm, v in t.series("hero_xy"):
        if v is not None and not (40 - 1e-6 <= v[0] <= 960 + 1e-6):
            return "hero x %r outside [40, 960] at frame %d" % (v[0], f)
    return True


def _max_shots(t):
    m = max(t.values("tiro_n"))
    return _need(m in (6, 7), "max live hero shots %r, expected 6 or 7" % m)


def _shots_x(t):
    for f, _tm, xs in t.series("tiro_xs"):
        for x in xs:
            if abs(x - 500) > 1e-6:
                return "shot x %r at frame %d (hero at 500)" % (x, f)
    return True


def _shot_speed(t):
    s = t.series("tiro_ys")
    pairs = 0
    for (f1, _a, y1), (f2, _b, y2) in zip(s, s[1:]):
        if len(y1) == 1 and len(y2) == 1 and f2 == f1 + 1:
            d = y2[0] - y1[0]
            if abs(d - 560 * _dt(t)) > 0.01:
                return "shot moved %r in one frame (expected %r)" % (d, 560 * _dt(t))
            pairs += 1
    return _need(pairs >= 3, "only %d single-shot frame pairs" % pairs)


def _shot_spawn(t):
    f = _first(t, "tiro_n", lambda v: v == 1)
    if f is None:
        return "no shot"
    y = _val(t, f, "tiro_ys")[0]
    return _need(98 - 0.01 <= y <= 98 + 560 * _dt(t) + 0.01, "first shot y %r, expected 98..107.4" % y)


def _shots_leave_top(t):
    seen = False
    for f, _tm, ys in t.series("tiro_ys"):
        for y in ys:
            if y > 1000 + 560 * _dt(t) + 0.01:
                return "shot alive at y %r (playfield top 1000)" % y
            if y > 900:
                seen = True
    if not seen:
        return "no shot ever passed y 900 (playfield extends to 1000)"
    return _need(t.end("tiro_n") == 0, "shots left at end: %r" % t.end("tiro_n"))


def _pontos_steps(t):
    prev = None
    for f, _tm, v in t.series("pontos"):
        if v % 100 != 0:
            return "pontos %r not a multiple of 100" % v
        if prev is not None and v < prev:
            return "pontos fell from %r to %r at frame %d" % (prev, v, f)
        prev = v
    return True


def _restart_frame(t):
    s = t.series("inimigo_n")
    for (f1, _a, a), (f2, _b, b) in zip(s, s[1:]):
        if a == 24 and b == 0:
            return f2
    return None


def _restart_fresh(t):
    fr = _restart_frame(t)
    if fr is None:
        return "fleet never dropped 24 -> 0 (no restart seen)"
    xy = _val(t, fr, "hero_xy")
    return _need(_close_xy(xy, (500, 70), 0.01) and _val(t, fr, "tiro_n") == 0
                 and _val(t, fr, "heroi_n") == 1,
                 "after R: hero %r, shots %r, heroes %r" % (
                     xy, _val(t, fr, "tiro_n"), _val(t, fr, "heroi_n")))


def _restart_keeps_st(t):
    fr = _restart_frame(t)
    if fr is None:
        return "no restart seen"
    for k in ("pontos", "vidas", "fase"):
        if _val(t, fr - 1, k) != _val(t, fr, k):
            return "%s changed across the restart: %r -> %r" % (k, _val(t, fr - 1, k), _val(t, fr, k))
    return True


def _restart_fleet_again(t):
    fr = _restart_frame(t)
    if fr is None:
        return "no restart seen"
    a = _val(t, fr + _frames(t, 1.4), "inimigo_n")
    b = _val(t, fr + _frames(t, 1.6), "inimigo_n")
    return _need(a == 0 and b == 24, "after R fleet %r at +1.4 s, %r at +1.6 s" % (a, b))


def _boss_spawn(t):
    return _first(t, "chefe_n", lambda v: v == 1)


def _boss_delay(t):
    r = t.input_frame("key")
    s = _boss_spawn(t)
    if r is None or s is None:
        return "R input %r, boss spawn %r" % (r, s)
    return _need(abs((s - r) - _frames(t, 2.5)) <= 3,
                 "boss came %d frames after R (expected ~%d)" % (s - r, _frames(t, 2.5)))


def _boss_arrival(t):
    s = _boss_spawn(t)
    if s is None:
        return "no boss"
    p0 = _val(t, s, "chefe_xy")
    if not (abs(p0[0] - 500) < 1e-6 and abs(p0[1] - 900) <= 12):
        return "boss at spawn %r, expected (500, 900)" % (p0,)
    end = s + _frames(t, 1.9)
    for f, _tm, v in t.series("chefe_xy"):
        if s <= f <= end and (v is None or abs(v[0] - 500) > 1e-6):
            return "boss x %r during arrival (frame %d)" % (v, f)
    p1 = _val(t, end, "chefe_xy")
    return _need(_close_xy(p1, (500, 600), 3.0), "boss at +1.9 s %r, expected (500, 600)" % (p1,))


def _boss_eight_bounds(t):
    s = _boss_spawn(t)
    if s is None:
        return "no boss"
    for f, _tm, v in t.series("chefe_xy"):
        if f >= s + _frames(t, 2.1) and v is not None:
            if not (215 <= v[0] <= 785 and 550 <= v[1] <= 650):
                return "boss at %r outside the eight box at frame %d" % (v, f)
    return True


def _boss_rotation(t):
    s = _boss_spawn(t)
    if s is None:
        return "no boss"
    before = [v for f, _tm, v in t.series("chefe_angle") if s <= f <= s + _frames(t, 1.9)]
    after = [v for f, _tm, v in t.series("chefe_angle") if f >= s + _frames(t, 2.2) and v is not None]
    if any(abs(a) > 1e-6 for a in before):
        return "boss rotated during arrival: %r" % (before[:5],)
    return _need(len(set(after)) > 10, "boss angle does not change while fighting")


def _boss_volleys(t):
    s = _boss_spawn(t)
    if s is None:
        return "no boss"
    lut = s + _frames(t, 2.0)
    for f, _tm, v in t.series("tiro_inimigo_n"):
        if f < lut + _frames(t, 1.5) and v != 0:
            return "enemy shot before the first volley (frame %d, %r)" % (f, v)
    f5 = _first(t, "tiro_inimigo_n", lambda v: v >= 5, after=lut)
    return _need(f5 is not None and f5 <= lut + _frames(t, 1.75),
                 "first volley at frame %r, expected by %d" % (f5, lut + _frames(t, 1.75)))


def _volley_of_five(t):
    vs = t.values("tiro_inimigo_n")
    for a, b in zip(vs, vs[1:]):
        if b > a and b - a != 5:
            return "enemy shots rose by %r in one frame (expected 5)" % (b - a)
    return _need(max(vs) >= 5, "no volley seen")


def _vida_untouched(t):
    for f, _tm, v in t.series("chefe_vida"):
        if v is not None and v != 30:
            return "boss vida %r at frame %d with no hero shots" % (v, f)
    return True


def _vida_only_while_fighting(t):
    s = _boss_spawn(t)
    if s is None:
        return "no boss"
    prev = None
    for f, _tm, v in t.series("chefe_vida"):
        if v is None:
            continue
        if f <= s + _frames(t, 1.95) and v != 30:
            return "boss lost vida (%r) before fighting, frame %d" % (v, f)
        if v < 0 or (prev is not None and v > prev):
            return "boss vida went %r -> %r" % (prev, v)
        prev = v
    return True


def _vida_drops(t):
    vs = [v for v in t.values("chefe_vida") if v is not None]
    return _need(vs and min(vs) < 30, "boss never lost vida while hero held SPACE under it")


def _lives_invariant(t):
    s = t.series("vidas")
    last_drop = None
    dt = _dt(t)
    for (f1, tm1, a), (f2, tm2, b) in zip(s, s[1:]):
        if b == a:
            continue
        if b != a - 1:
            return "vidas %r -> %r at frame %d" % (a, b, f2)
        if last_drop is not None and tm2 - last_drop < 0.75:
            return "two hits %.3f s apart (ferido lasts 0.8 s)" % (tm2 - last_drop)
        last_drop = tm2
        if b > 0:
            fer = [_val(t, f, "ferido_n") for f in (f2, f2 + 1)]
            if 1 not in fer:
                return "hero not tagged ferido after the hit at frame %d" % f2
            back = _first(t, "ferido_n", lambda v: v == 0, after=f2 + 1)
            if back is not None and back - f2 > _frames(t, 0.9):
                return "ferido lasted %d frames" % (back - f2)
    return True


def _lose_frames(t):
    return t.input_frame("cell", nth=1)          # st.vidas = 0


def _frozen_hero(t):
    v = _lose_frames(t)
    for f, _tm, xy in t.series("hero_xy"):
        if f >= v and xy is not None and abs(xy[0] - 500) > 1e-6:
            return "hero moved with 0 lives: %r at frame %d" % (xy, f)
    return True


def _r_refused(t):
    # Revised (SPEC-LOGIC): "still in Fase" ends at the first frame the hero is
    # gone; a later hero belongs to the next game, whose fleet is not built yet.
    v = _lose_frames(t)
    for f, _tm, n in t.series("heroi_n"):
        if f >= v and n == 0:
            break
        if f >= v and n == 1 and _val(t, f, "inimigo_n") != 24:
            return "fleet %r while still in Fase after 0 lives (R must not restart)" % (
                _val(t, f, "inimigo_n"),)
    return True


def _lose_change(t):
    v = _lose_frames(t)
    a = _val(t, v + _frames(t, 1.4), "heroi_n")
    b = _val(t, v + _frames(t, 1.6), "heroi_n")
    e = _val(t, v + _frames(t, 1.6), "inimigo_n")
    return _need(a == 1 and b == 0 and e == 0,
                 "heroes %r at +1.4 s, %r at +1.6 s, fleet %r (expected 1, 0, 0)" % (a, b, e))


def _gameover_data(rec):
    def fn(t):
        v = _lose_frames(t)
        f = v + _frames(t, 1.8)
        r, w = _val(t, f, "recorde"), _val(t, f, "venceu")
        return _need(r == rec and not w, "after FimDeJogo recorde %r venceu %r" % (r, w))
    return fn


def _key_frames(t):
    """Every recorded key input frame (press and, if recorded, release)."""
    out, n = [], 0
    while n < 50:
        try:
            f = t.input_frame("key", nth=n)
        except Exception:
            break
        if f is None:
            break
        out.append(f)
        n += 1
    return out


def _auto_title(t):
    v = _lose_frames(t)
    late = v + _frames(t, 1.5 + 10.0)
    f1 = _first(t, "heroi_n", lambda n: n == 1, after=v + _frames(t, 1.6))
    if f1 is None:
        return "SPACE after 10 s did not start a game (FimDeJogo never went back to Titulo)"
    if f1 < late:
        return "a new Fase began at frame %d, before FimDeJogo's 10 s ran out (%d)" % (f1, late)
    if not any(k >= late and 0 <= f1 - k <= 2 for k in _key_frames(t)):
        return "new Fase at frame %d is not 0-2 frames after the final SPACE" % f1
    return True


def _new_game_state(rec):
    def fn(t):
        got = tuple(t.end(k) for k in ("heroi_n", "pontos", "vidas", "fase", "recorde"))
        return _need(got == (1, 0, 3, 1, rec),
                     "end (heroes, pontos, vidas, fase, recorde) = %r, expected %r" % (
                         got, (1, 0, 3, 1, rec)))
    return fn


def _skip_to_title(t):
    sp = t.input_frame("key")
    if sp is None:
        return "no SPACE"
    if _val(t, sp - 1, "heroi_n") != 0:
        return "still in Fase when SPACE was pressed"
    for f in range(sp, sp + 40):
        if _val(t, f, "heroi_n") != 0:
            return "the FimDeJogo SPACE also started a game (frame %d)" % f
    return True


def _zerar(t):
    sp = t.input_frame("key")
    a = _val(t, sp + 30, "recorde")
    if a != 700:
        return "recorde on the title %r, expected 700" % a
    z = _first(t, "recorde", lambda r: r == 0, after=sp)
    if z is None:
        return "zerar recorde click did not reset it"
    for f in range(z, z + 15):
        if _val(t, f, "heroi_n") != 0:
            return "zerar click started a game"
    return True


def _st_initial(t):
    for k, want in (("pontos", 0), ("vidas", 3), ("fase", 1), ("recorde", 0)):
        for f, _tm, v in t.series(k):
            if v != want:
                return "st.%s %r at frame %d" % (k, v, f)
    return _need(not any(t.values("venceu")), "venceu True on the title")


# --- expectations --------------------------------------------------------------

AD = "design/Act Design.md"
GUIA = "docs/pt/guide/index.html"

EXPECT = [
    Expect(id="E1", level="L0", cite=AD + "#starting-runtitulo",
           text="With no input the game stays on Titulo: no hero, no fleet, no shots.",
           check=all_of(always("heroi_n", lambda v: v == 0),
                        always("inimigo_n", lambda v: v == 0),
                        always("tiro_n", lambda v: v == 0)),
           scenarios=("idle",)),
    Expect(id="E2", level="L0", cite=AD + "#game-data-st-is-the-one-channel",
           text="Top-level jogo_novo() and st.recorde=0 hold on the title: pontos 0, vidas 3, fase 1, venceu False, recorde 0.",
           check=custom(_st_initial), scenarios=("idle",)),
    Expect(id="E3", level="L0", cite=GUIA + "#atos (change_act troca na hora)",
           text="SPACE on Titulo builds Fase immediately: no hero before the press, exactly one within 2 frames of it.",
           check=custom(_start_on_input("key", 2)), scenarios=("start_space",)),
    Expect(id="E4", level="L0", cite=GUIA + "#ui-sprite-button (clica ao soltar em cima)",
           text="Clicking the JOGAR SpriteButton at (500, 320) starts Fase on release (within 3 frames of the press).",
           check=custom(_start_on_input("button", 3)), scenarios=("start_click",)),
    Expect(id="E5", level="L0", cite=AD + "#change_act (teardown before build: exactly one group['heroi'])",
           text="Once Fase starts there is exactly one hero in every frame, including across an R restart.",
           check=custom(_one_hero_after_start), scenarios=PLAY_SCENARIOS),
    Expect(id="E6", level="L1", cite="tests/programs/galaga_acts.py Fase.setup; " + GUIA + "#atos",
           text="The hero is born at (500, 70) (tol 0.01).",
           check=custom(_hero_born), scenarios=("start_space", "start_click")),
    Expect(id="E7", level="L0", cite=GUIA + "#grp-esperar / " + AD + "#acts-and-modes (async mode, await wait)",
           text="The fleet appears 1.5 s into Fase: 0 enemies at +1.4 s, 24 at +1.6 s.",
           check=custom(_fleet_timing), scenarios=("start_space",)),
    Expect(id="E8", level="L1", cite=GUIA + "#colocar-grid; design/Box Design.md grid (gap between cells, row 0 on top)",
           text="At +3.0 s (arrived, 1 s ease_out, no dive possible before ~6.5 s) the 24 enemies sit on the 8x3 grid centres (tol 0.5).",
           check=custom(_fleet_grid), scenarios=("start_space",)),
    Expect(id="E9", level="L0", cite=GUIA + "#frame-teclado",
           text="The hero only moves horizontally: its y stays 70.",
           check=custom(_hero_y_70), scenarios=PLAY_SCENARIOS),
    Expect(id="E10", level="L1", cite=GUIA + "#frame-teclado (keyp held)",
           text="Holding LEFT 30 frames moves the hero 340 px/s * 0.5 s: rests at 330 (tol 6, one frame of press/release ambiguity).",
           check=custom(_move_left_speed), scenarios=("move",)),
    Expect(id="E11", level="L0", cite=GUIA + "#mover-confine (by='center', action='clamp')",
           text="confine(AREA) clamps the hero centre at exactly x=960 holding RIGHT and x=40 holding LEFT.",
           check=custom(_move_clamps), scenarios=("move",)),
    Expect(id="E12", level="L2", cite=GUIA + "#mover-confine",
           text="The hero centre x never leaves [40, 960] at frame end (slop 1e-6: confine runs right after the move).",
           check=custom(_hero_inside_area), scenarios=PLAY_SCENARIOS),
    Expect(id="E13", level="L0", cite=GUIA + "#agendar-ready (primeira chamada True, no maximo uma vez por intervalo)",
           text="Holding SPACE 60 frames with self.ready('atirar', 0.15) fires 6 or 7 shots (first immediately), all still alive.",
           check=custom(_max_shots), scenarios=("fire",)),
    Expect(id="E14", level="L0", cite="tests/programs/galaga_acts.py Heroi.on_update",
           text="Every hero shot travels straight up at the hero's x (500).",
           check=custom(_shots_x), scenarios=("fire",)),
    Expect(id="E15", level="L1", cite=GUIA + "#pose-move-by",
           text="A hero shot rises 560*dt per frame (tol 0.01).",
           check=custom(_shot_speed), scenarios=("fire",)),
    Expect(id="E16", level="L1", cite="tests/programs/galaga_acts.py Tiro(center=self.center + (0, 28))",
           text="The first shot appears at y 98 (at most one frame of motion later, tol 0.01).",
           check=custom(_shot_spawn), scenarios=("fire",)),
    Expect(id="E17", level="L2", cite=GUIA + "#reagir-bounds (playfield default pad 0.25 -> top 1000)",
           text="Shots live past the screen top (y>900) and are destroyed on leaving the playfield (never beyond 1000 + one frame step); none remain at the end.",
           check=custom(_shots_leave_top), scenarios=("fire",)),
    Expect(id="E18", level="L0", cite="tests/programs/galaga_acts.py geometry",
           text="Shots at x=500 pass between fleet columns 3 and 4 (451.5, 548.5): no points. Assumed enemy art ~44 px wide at height 40.",
           check=always("pontos", lambda v: v == 0), scenarios=("fire",), guess=True),
    Expect(id="E19", level="L0", cite="tests/programs/galaga_acts.py Inimigo.morrendo (valor 100)",
           text="Points only grow and stay multiples of 100 in phase 1 (a dying enemy scores once).",
           check=custom(_pontos_steps), scenarios=("kill_column", "move", "restart", "fire")),
    Expect(id="E20", level="L0", cite="tests/programs/galaga_acts.py; " + GUIA + "#mode",
           text="Standing under column 3 and firing 2.5 s kills exactly that column: pontos 300, 21 enemies left (assumes hitboxes ~art width, no dive before 6.5 s).",
           check=all_of(at_end("pontos", lambda v: v == 300),
                        at_end("inimigo_n", lambda v: v == 21)),
           scenarios=("kill_column",), guess=True),
    Expect(id="E21", level="L0", cite=AD + "#switching-change_actfase; #removed",
           text="R restarts Fase: in the frame the fleet vanishes the hero is back at (500, 70), alone, and all shots are gone.",
           check=custom(_restart_fresh), scenarios=("restart",)),
    Expect(id="E22", level="L0", cite=AD + "#game-data-st-is-the-one-channel (st never cleared by an act change)",
           text="A restart keeps st: pontos, vidas and fase are equal just before and after it.",
           check=custom(_restart_keeps_st), scenarios=("restart",)),
    Expect(id="E23", level="L0", cite=AD + "#switching-change_actfase (always a fresh instance)",
           text="The restarted Fase rebuilds its fleet: 0 at +1.4 s, 24 at +1.6 s after the restart.",
           check=custom(_restart_fleet_again), scenarios=("restart",)),
    Expect(id="E24", level="L0", cite=AD + "#game-data-st-is-the-one-channel (Fase with st.fase)",
           text="With st.fase=2, R builds the boss phase: no fleet ever, fase stays 2.",
           check=all_of(always("inimigo_n", lambda v: v == 0),
                        at_end("fase", lambda v: v == 2),
                        at_end("chefe_n", lambda v: v == 1)),
           scenarios=("boss", "boss_fire")),
    Expect(id="E25", level="L1", cite=GUIA + "#mode-async",
           text="The boss appears 2.5 s after R (tol 3 frames).",
           check=custom(_boss_delay), scenarios=("boss", "boss_fire")),
    Expect(id="E26", level="L1", cite=GUIA + "#pose-move-to; #suite-then",
           text="The boss spawns at (500, 900) (tol 12: one tween step) and slides straight down to (500, 600) in 2 s (x exact, tol 3 at +1.9 s).",
           check=custom(_boss_arrival), scenarios=("boss", "boss_fire")),
    Expect(id="E27", level="L2", cite=GUIA + "#mover-move-along; design/Tracks Design.md (centered presets)",
           text="While fighting the boss centre stays inside the eight's box around (500, 600): x 220..780, y 555..645, slop 5.",
           check=custom(_boss_eight_bounds), scenarios=("boss", "boss_fire")),
    Expect(id="E28", level="L0", cite=GUIA + "#pose-rotate-by; #suite-loops",
           text="The boss does not rotate while arriving (angle 0) and keeps rotating while fighting.",
           check=custom(_boss_rotation), scenarios=("boss",)),
    Expect(id="E29", level="L0", cite=GUIA + "#ag-call (every repete)",
           text="No enemy shot exists until the first volley 1.6 s into the fight; by +1.75 s there are 5. Assumes every() first fires after one interval.",
           check=custom(_boss_volleys), scenarios=("boss",), guess=True),
    Expect(id="E30", level="L0", cite="tests/programs/galaga_acts.py Chefe.rajada",
           text="Enemy shots in the boss phase appear five at a time.",
           check=custom(_volley_of_five), scenarios=("boss",)),
    Expect(id="E31", level="L0", cite=GUIA + "#atos",
           text="With no hero shots the boss keeps vida 30.",
           check=custom(_vida_untouched), scenarios=("boss",)),
    Expect(id="E32", level="L0", cite=GUIA + "#mode (self.mode compare)",
           text="Hits during the arrival do not count; vida never rises nor goes below 0.",
           check=custom(_vida_only_while_fighting), scenarios=("boss_fire",)),
    Expect(id="E33", level="L0", cite="tests/programs/galaga_acts.py Chefe",
           text="Holding SPACE under the eight's crossing point eventually hits the fighting boss (vida < 30); points are 0 or 5000.",
           check=all_of(custom(_vida_drops), always("pontos", lambda v: v in (0, 5000))),
           scenarios=("boss_fire",), guess=True),
    Expect(id="E34", level="L0", cite=GUIA + "#agendar (after), #grp-ler (tagged)",
           text="Lives drop one at a time, at least 0.75 s apart; each non-fatal hit tags the hero 'ferido' for about 0.8 s.",
           check=custom(_lives_invariant), scenarios=NO_LOSE),
    Expect(id="E35", level="L0", cite="tests/programs/galaga_acts.py Heroi.on_update",
           text="With 0 lives the hero ignores LEFT: x stays 500.",
           check=custom(_frozen_hero), scenarios=("lose_wait",)),
    Expect(id="E36", revised="SPEC-LOGIC: heroi_n == 1 also matched the next game; stop at the first frame the hero is gone", level="L0", cite=AD + "#act-rules-watch-changes-not-states",
           text="R with 0 lives does not restart: the 24-enemy fleet stays until the act changes.",
           check=custom(_r_refused), scenarios=("lose_wait",)),
    Expect(id="E37", level="L0", cite=AD + "#acts-and-modes (self.after(..., change_act)); @when rising edge",
           text="Setting vidas to 0 fires perdeu; 1.5 s later FimDeJogo replaces Fase (hero 1 at +1.4 s, 0 at +1.6 s, fleet gone).",
           check=custom(_lose_change), scenarios=("lose_wait", "lose_skip")),
    Expect(id="E38", level="L0", cite=AD + "#game-data-st-is-the-one-channel",
           text="FimDeJogo sets recorde = max(recorde, pontos) and venceu is False.",
           check=custom(_gameover_data(1200)), scenarios=("lose_wait",)),
    Expect(id="E39", level="L0", cite=GUIA + "#atos (FimDeJogo self.after(10, ...))",
           text="FimDeJogo returns to Titulo by itself after 10 s: a SPACE then starts a new game within 2 frames.",
           check=custom(_auto_title), scenarios=("lose_wait",)),
    Expect(id="E40", level="L0", cite=AD + "#game-data-st-is-the-one-channel (jogo_novo; recorde spans games)",
           text="A new game resets pontos 0, vidas 3, fase 1 but keeps recorde.",
           check=custom(_new_game_state(1200)), scenarios=("lose_wait",)),
    Expect(id="E41", level="L0", cite=AD + "#change_act (the same key press does not carry into the new act)",
           text="SPACE in FimDeJogo goes to Titulo, and that press does not also start a game.",
           check=custom(_skip_to_title), scenarios=("lose_skip",)),
    Expect(id="E42", level="L0", cite=GUIA + "#ui-sprite-button (enabled @=)",
           text="On the title recorde is still 700; the enabled 'zerar recorde' button sets it to 0 without starting a game.",
           check=custom(_zerar), scenarios=("lose_skip",)),
    Expect(id="E43", level="L0", cite=GUIA + "#ui-sprite-button; " + AD + "#game-data-st-is-the-one-channel",
           text="JOGAR after zerar starts a new game with recorde 0.",
           check=custom(_new_game_state(0)), scenarios=("lose_skip",)),
]
