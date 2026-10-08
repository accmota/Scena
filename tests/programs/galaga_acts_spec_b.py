"""Spec B for tests/programs/galaga_acts.py, written from the docs alone.

Acts: Titulo -> Fase (st.fase 1: fleet; st.fase 2: boss) -> FimDeJogo -> Titulo.
The act in force is read from groups (only Fase has a "heroi"); there is no
Act.current (design/Act Design.md, "Finding each other").

Derived numbers used below (from the program + docs):
- AREA = canvas.game_view.inset(40) -> x in [40, 960]; confine(by="center") by
  default, so the hero's CENTER is clamped to [40, 960].
- Fleet grid: Box(center=(500, 590), 760 x 170).grid(8, 3, gap=16): cell
  81 x 46; column centres 160.5 + 97*i; row 0 is the top -> y 652, 590, 528.
- Hero speed 340/60 = 5.667 px per frame; Tiro 560/60 = 9.333 px per frame.
- ready(..., 0.15) -> one shot per 9 frames; the first call is True.
- Enemy fire: every(uniform(2.5, 4.0)) entered at formacao (fleet built at
  +1.5 s, arrives at +2.5 s) -> no enemy bullet before Fase start + 5.0 s;
  the earliest dive is at +2.5 + 4.0 = +6.5 s.
- Boss: spawned at +2.5 s, move_to (500, 600) over 2.0 s (arrives +4.5 s),
  then an anchored Track.eight(560 x 90) centred at (500, 600), rotate_by 360
  per 3 s (default ease "linear"), every(1.6) a 5-bullet volley.
"""
from program_support import (Scenario, Expect, wait, wait_s, click_widget, click,
    key, key_down, key_up, move, scroll, set_cell, always, never, at, at_end,
    eventually, steady, all_of, custom, close)
import math


FILES_READ = [
    "tests/programs/galaga_acts.py",
    "design/Act Design.md#concepts",
    "design/Act Design.md#lifetime-the-game-and-the-act",
    "design/Act Design.md#act-rules-watch-changes-not-states",
    "design/Act Design.md#change_act",
    "design/Act Design.md#restrictions-and-error-messages",
    "docs/pt/guide/index.html#atos",
    "docs/pt/guide/index.html#atos-trocar",
    "docs/pt/guide/index.html#frame-teclado",
    "docs/pt/guide/index.html#agendar-ready",
    "docs/pt/guide/index.html#agendar-timers",
    "docs/pt/guide/index.html#mode-async",
    "docs/pt/guide/index.html#mundo-grupos",
    "docs/pt/guide/index.html#colocar-grid",
    "docs/pt/guide/index.html#colocar-pais",
    "docs/pt/guide/index.html#mover-confine",
    "docs/pt/guide/index.html#mover-tween",
    "docs/pt/guide/index.html#reagir-when",
    "docs/pt/guide/index.html#reagir-bounds",
    "docs/pt/guide/index.html#ui-sprite-button",
    "docs/pt/guide/index.html (Track section, anchored vs floating)",
]


# --------------------------------------------------------------------- probes

def _first(p, name):
    g = p.group[name]
    return g.first if g.count else None


def _hx(p):
    h = _first(p, "heroi")
    return None if h is None else float(h.center.x)


def _hy(p):
    h = _first(p, "heroi")
    return None if h is None else float(h.center.y)


def _chefe_center(p):
    c = _first(p, "chefe")
    return None if c is None else (float(c.center.x), float(c.center.y))


def _chefe_vida(p):
    c = _first(p, "chefe")
    return None if c is None else float(c.vida)


def _chefe_angle(p):
    c = _first(p, "chefe")
    return None if c is None else float(c.angle)


def _inimigo_centers(p):
    return tuple(sorted((round(float(e.center.x), 3), round(float(e.center.y), 3))
                        for e in p.group["inimigo"]))


def _tiro_max_y(p):
    ys = [float(t.center.y) for t in p.group["tiro"]]
    return max(ys) if ys else None


PROBES = {
    "pontos": lambda p: p.st.pontos,
    "vidas": lambda p: p.st.vidas,
    "fase": lambda p: p.st.fase,
    "venceu": lambda p: bool(p.st.venceu),
    "recorde": lambda p: p.st.recorde,
    "n_heroi": lambda p: p.group["heroi"].count,
    "n_inimigo": lambda p: p.group["inimigo"].count,
    "n_chefe": lambda p: p.group["chefe"].count,
    "n_tiro": lambda p: p.group["tiro"].count,
    "n_tiro_inimigo": lambda p: p.group["tiro_inimigo"].count,
    "heroi_x": _hx,
    "heroi_y": _hy,
    "inimigo_centers": _inimigo_centers,
    "tiro_max_y": _tiro_max_y,
    "chefe_center": _chefe_center,
    "chefe_vida": _chefe_vida,
    "chefe_angle": _chefe_angle,
}


# -------------------------------------------------------------------- helpers

DT = 1.0 / 60.0
HERO_STEP = 340.0 / 60.0
TIRO_STEP = 560.0 / 60.0
COLS_X = [160.5 + 97.0 * i for i in range(8)]
ROWS_Y = [652.0, 590.0, 528.0]
GRID = sorted((x, y) for x in COLS_X for y in ROWS_Y)


def _ser(t, name):
    return t.series(name)


def _first_where(t, name, pred, after_frame=0):
    for f, tm, v in t.series(name):
        if f > after_frame and pred(v):
            return f, tm
    return None, None


def _fase_start(t):
    """Frame/time the first Fase was built (the hero appears)."""
    return _first_where(t, "n_heroi", lambda v: v is not None and v >= 1)


def _between(t, name, t0, t1):
    return [(f, tm, v) for f, tm, v in t.series(name) if t0 <= tm <= t1]


def _value_at_time(t, name, when):
    best = None
    for f, tm, v in t.series(name):
        if tm <= when + 1e-9:
            best = v
        else:
            break
    return best


def _restart_frame(t, after_frame):
    """First frame where the hero is back at x=500 after having been left of 400."""
    prev = None
    for f, tm, v in t.series("heroi_x"):
        if f > after_frame and prev is not None and v is not None \
                and prev < 400 and abs(v - 500) < 1.0:
            return f, tm
        prev = v
    return None, None


def _time_of(t, frame):
    for f, tm, v in t.series("n_heroi"):
        if f == frame:
            return tm
    return None


# ---- idle / title ----------------------------------------------------------

def _chk_title_empty(t):
    for name in ("n_heroi", "n_inimigo", "n_chefe", "n_tiro", "n_tiro_inimigo"):
        for f, tm, v in t.series(name):
            if v != 0:
                return f"{name}={v} at frame {f} while on the title"
    return True


def _chk_title_st(t):
    for f, tm, v in t.series("pontos"):
        if v != 0:
            return f"pontos={v} at frame {f}"
    for f, tm, v in t.series("vidas"):
        if v != 3:
            return f"vidas={v} at frame {f}"
    for f, tm, v in t.series("fase"):
        if v != 1:
            return f"fase={v} at frame {f}"
    for f, tm, v in t.series("recorde"):
        if v != 0:
            return f"recorde={v} at frame {f}"
    for f, tm, v in t.series("venceu"):
        if v:
            return f"venceu true at frame {f}"
    return True


# ---- start ------------------------------------------------------------------

def _chk_space_starts(t):
    fk = t.input_frame("key", 0)
    f0, _ = _fase_start(t)
    if f0 is None:
        return "SPACE on the title never built Fase (no hero)"
    if not (fk <= f0 <= fk + 2):
        return f"hero appeared at frame {f0}, SPACE delivered at {fk}"
    return True


def _chk_hero_spawn(t):
    f0, _ = _fase_start(t)
    if f0 is None:
        return "no hero"
    x = t.at_frame(f0, "heroi_x")
    y = t.at_frame(f0, "heroi_y")
    if not (close(x, 500, 0.5) and close(y, 70, 0.5)):
        return f"hero spawned at ({x}, {y}), expected (500, 70)"
    return True


def _chk_one_hero(t):
    f0, _ = _fase_start(t)
    if f0 is None:
        return "no hero"
    for f, tm, v in t.series("n_heroi"):
        if f >= f0 and v != 1:
            return f"n_heroi={v} at frame {f}"
    return True


def _chk_fleet_timing(t):
    f0, t0 = _fase_start(t)
    if f0 is None:
        return "no hero"
    for f, tm, v in t.series("n_inimigo"):
        if tm < t0 + 1.45 and v != 0:
            return f"{v} enemies at t-t0={tm - t0:.3f}, before the 1.5 s banner"
        if tm > t0 + 1.55 and v != 24:
            return f"{v} enemies at t-t0={tm - t0:.3f}, expected 24"
    return True


def _chk_fleet_grid(t):
    f0, t0 = _fase_start(t)
    if f0 is None:
        return "no hero"
    for dt_ in (3.0, 6.0):
        centers = _value_at_time(t, "inimigo_centers", t0 + dt_)
        if centers is None or len(centers) != 24:
            return f"at +{dt_}s: {None if centers is None else len(centers)} enemies"
        got = sorted(centers)
        for (gx, gy), (ex, ey) in zip(got, GRID):
            if abs(gx - ex) > 1.0 or abs(gy - ey) > 1.0:
                return f"at +{dt_}s enemy at ({gx}, {gy}), expected grid cell ({ex}, {ey})"
    return True


def _chk_fleet_arrives_from_above(t):
    f0, t0 = _fase_start(t)
    if f0 is None:
        return "no hero"
    for f, tm, v in t.series("inimigo_centers"):
        if t0 + 1.55 <= tm <= t0 + 2.4 and v:
            for x, y in v:
                if y < 528.0 - 1.0:
                    return f"enemy below its slot (y={y}) while arriving at frame {f}"
    return True


def _chk_no_enemy_fire_early(t):
    f0, t0 = _fase_start(t)
    if f0 is None:
        return "no hero"
    for f, tm, v in t.series("n_tiro_inimigo"):
        if tm < t0 + 4.9 and v != 0:
            return f"{v} enemy bullets at t-t0={tm - t0:.3f}"
    return True


def _vidas_full_until(limit):
    def chk(t):
        f0, t0 = _fase_start(t)
        if f0 is None:
            return "no hero"
        for f, tm, v in t.series("vidas"):
            if tm < t0 + limit and v != 3:
                return f"vidas={v} at t-t0={tm - t0:.3f}"
        return True
    return chk


def _chk_hero_still(t):
    f0, _ = _fase_start(t)
    if f0 is None:
        return "no hero"
    for f, tm, v in t.series("heroi_x"):
        if f >= f0 and not close(v, 500, 1e-6):
            return f"hero moved to x={v} at frame {f} with no input"
    return True


def _chk_vidas_monotone_and_ferido(t):
    """Within one Fase lives never rise, and drop at most once per 0.8 s."""
    last_drop = None
    prev = None
    for f, tm, v in t.series("vidas"):
        if prev is not None:
            if v > prev:
                return f"vidas rose {prev}->{v} at frame {f}"
            if v < prev:
                if prev - v > 1:
                    return f"vidas dropped by {prev - v} in one frame at {f}"
                if last_drop is not None and tm - last_drop < 0.8 - 2 * DT:
                    return f"two hits {tm - last_drop:.3f}s apart (ferido is 0.8 s)"
                last_drop = tm
        prev = v
    return True


# ---- movement ---------------------------------------------------------------

def _chk_left_30(t):
    f0, _ = _fase_start(t)
    if f0 is None:
        return "no hero"
    # the first 60 frames after the start cover LEFT x30 and the pause before RIGHT
    xs = [(f, v) for f, tm, v in t.series("heroi_x") if f > f0 and v is not None]
    mn = min(v for f, v in xs[:60]) if xs else None
    if mn is None:
        return "no hero x"
    if not close(mn, 500 - 30 * HERO_STEP, HERO_STEP + 0.1):
        return f"after LEFT x30 the hero is at {mn}, expected ~{500 - 30 * HERO_STEP:.1f}"
    return True


def _chk_step_bound(t):
    prev = None
    for f, tm, v in t.series("heroi_x"):
        if prev is not None and v is not None and abs(v - prev) > HERO_STEP + 0.01:
            return f"hero moved {abs(v - prev):.3f} px in one frame at {f}"
        prev = v
    return True


def _chk_hero_y(t):
    for f, tm, v in t.series("heroi_y"):
        if v is not None and not close(v, 70, 1e-6):
            return f"hero y={v} at frame {f}"
    return True


def _chk_clamp(t):
    xs = [v for f, tm, v in t.series("heroi_x") if v is not None]
    if not xs:
        return "no hero"
    if min(xs) < 40 - 0.01 or max(xs) > 960 + 0.01:
        return f"hero centre left AREA: min {min(xs)}, max {max(xs)}"
    if not close(min(xs), 40, 0.01):
        return f"hero never reached the left edge 40 (min {min(xs)})"
    if not close(max(xs), 960, 0.01):
        return f"hero never reached the right edge 960 (max {max(xs)})"
    return True


# ---- shooting ---------------------------------------------------------------

def _shot_start(t):
    f0, t0 = _fase_start(t)
    if f0 is None:
        return None, None
    # first bullet after the hero moved under a column (well after the start press)
    return _first_where(t, "n_tiro", lambda v: v >= 1, after_frame=f0 + 150)


def _chk_fire_rate(t):
    f1, _ = _shot_start(t)
    if f1 is None:
        return "holding SPACE never spawned a Tiro"
    n = t.at_frame(f1 + 22, "n_tiro")
    if n != 3:
        return f"{n} bullets 22 frames after the first shot, expected 3 (ready 0.15 s)"
    return True


def _chk_bullet_speed(t):
    f1, _ = _shot_start(t)
    if f1 is None:
        return "no shot"
    y0 = t.at_frame(f1, "tiro_max_y")
    for k in range(1, 6):
        y = t.at_frame(f1 + k, "tiro_max_y")
        if y is None or not close(y - y0, k * TIRO_STEP, 0.05):
            return f"bullet rose {None if y is None else y - y0} in {k} frames, expected {k * TIRO_STEP:.3f}"
    return True


def _chk_bullet_origin(t):
    f1, _ = _shot_start(t)
    if f1 is None:
        return "no shot"
    y0 = t.at_frame(f1, "tiro_max_y")
    hy = t.at_frame(f1, "heroi_y")
    if not (hy + 28 - 0.5 <= y0 <= hy + 28 + TIRO_STEP + 0.5):
        return f"first bullet at y={y0}, expected hero y + 28 (plus at most one step)"
    return True


def _chk_points_shape(t):
    for f, tm, v in t.series("pontos"):
        if v % 100 != 0 or v < 0 or v > 300:
            return f"pontos={v} at frame {f} (fleet only, one column of 3 under fire)"
    end = t.end("pontos")
    if end < 100:
        return f"no enemy was killed (pontos={end})"
    return True


def _chk_points_match_kills(t):
    p = t.end("pontos")
    n = t.end("n_inimigo")
    if p != 100 * (24 - n):
        return f"pontos={p} but {24 - n} enemies were destroyed"
    return True


def _chk_dissolve_delay(t):
    fp, tp = _first_where(t, "pontos", lambda v: v >= 100)
    if fp is None:
        return "no kill"
    if t.at_frame(fp, "n_inimigo") != 24:
        return "the dying enemy left the group at once (it should dissolve 0.3 s first)"
    later = _value_at_time(t, "n_inimigo", tp + 0.3 + 0.1)
    if later is None or later > 23:
        return f"0.4 s after the kill there are still {later} enemies"
    return True


def _chk_tiros_bounded(t):
    # Revised (SPEC-LOGIC): (1000 - 98) / 560 = 1.61 s of flight at one shot per
    # 0.15 s is ceil(10.7) = 11 alive at most, not 8.
    for f, tm, v in t.series("n_tiro"):
        if v > 11:
            return f"{v} hero bullets alive at frame {f}"
    return True


# ---- restart ----------------------------------------------------------------

def _chk_restart_hero(t):
    f0, _ = _fase_start(t)
    fr, _ = _restart_frame(t, f0 or 0)
    if fr is None:
        return "R never rebuilt the hero at x=500"
    if t.at_frame(fr, "n_heroi") != 1:
        return f"n_heroi={t.at_frame(fr, 'n_heroi')} after restart"
    return True


def _chk_restart_clears_fleet(t):
    f0, _ = _fase_start(t)
    fr, tr = _restart_frame(t, f0 or 0)
    if fr is None:
        return "no restart"
    if t.at_frame(fr - 1, "n_inimigo") != 24:
        return f"{t.at_frame(fr - 1, 'n_inimigo')} enemies before R (expected 24)"
    if t.at_frame(fr, "n_inimigo") != 0:
        return f"{t.at_frame(fr, 'n_inimigo')} enemies right after R"
    for f, tm, v in t.series("n_inimigo"):
        if f >= fr and tm < tr + 1.45 and v != 0:
            return f"{v} enemies {tm - tr:.3f}s after the restart"
        if v > 24:
            return f"{v} enemies at frame {f}"
    if t.end("n_inimigo") != 24:
        return f"{t.end('n_inimigo')} enemies after the new banner"
    return True


def _chk_restart_keeps_st(t):
    for name, want in (("pontos", 0), ("vidas", 3), ("fase", 1), ("recorde", 0)):
        for f, tm, v in t.series(name):
            if v != want:
                return f"{name}={v} at frame {f}"
    return True


# ---- lose / game over / title -----------------------------------------------

def _vidas0_frame(t):
    return t.input_frame("cell", 1)


def _gameover_frame(t):
    fv = _vidas0_frame(t)
    return _first_where(t, "n_heroi", lambda v: v == 0, after_frame=fv)


def _chk_dead_hero_ignores_input(t):
    fv = _vidas0_frame(t)
    fg, _ = _gameover_frame(t)
    if fg is None:
        return "never left Fase"
    x0 = t.at_frame(fv, "heroi_x")
    for f, tm, v in t.series("heroi_x"):
        if fv <= f < fg and not close(v, x0, 1e-6):
            return f"hero moved/restarted (x {x0} -> {v}) at frame {f} with vidas 0"
    if not (x0 < 400):
        return f"setup error: hero was not moved left before vidas 0 (x={x0})"
    return True


def _chk_gameover_delay(t):
    fv = _vidas0_frame(t)
    tv = _time_of(t, fv)
    fg, tg = _gameover_frame(t)
    if fg is None:
        return "Fase never ended after vidas = 0"
    if not (1.5 - 3 * DT <= tg - tv <= 1.5 + 3 * DT):
        return f"FimDeJogo came {tg - tv:.3f}s after vidas = 0, expected 1.5 s"
    if t.at_frame(fg, "n_inimigo") != 0:
        return "enemies survived the change to FimDeJogo"
    return True


def _chk_gameover_st(t):
    fg, _ = _gameover_frame(t)
    if fg is None:
        return "no game over"
    if t.at_frame(fg, "recorde") != 700:
        return f"recorde={t.at_frame(fg, 'recorde')} in FimDeJogo, expected max(0, 700)"
    if t.at_frame(fg, "venceu"):
        return "venceu is true after losing"
    return True


def _chk_space_no_carry(t):
    fg, _ = _gameover_frame(t)
    if fg is None:
        return "no game over"
    fh, _ = _first_where(t, "n_heroi", lambda v: v >= 1, after_frame=fg)
    if fh is None:
        return "Fase never started again"
    if fh - fg < 60:
        return f"the hero came back {fh - fg} frames after FimDeJogo: one SPACE skipped the title"
    return True


def _chk_recorde_cleared(t):
    fg, _ = _gameover_frame(t)
    if fg is None:
        return "no game over"
    seen_700_after = False
    for f, tm, v in t.series("recorde"):
        if f >= fg and v == 700:
            seen_700_after = True
        if f >= fg and v == 0 and not seen_700_after:
            return "recorde went to 0 before being shown"
    if not seen_700_after:
        return "recorde never 700"
    if t.end("recorde") != 0:
        return f"zerar recorde click left recorde={t.end('recorde')}"
    # it was 700 for a while on the title (crossed the act change)
    n700 = sum(1 for f, tm, v in t.series("recorde") if f >= fg + 40 and v == 700)
    if n700 < 1:
        return "recorde did not survive into Titulo"
    return True


def _chk_new_game(t):
    if t.end("n_heroi") != 1:
        return f"n_heroi={t.end('n_heroi')} at end: second SPACE did not start Fase"
    for name, want in (("pontos", 0), ("vidas", 3), ("fase", 1)):
        if t.end(name) != want:
            return f"{name}={t.end(name)} after a new game, expected {want}"
    return True


def _chk_pontos_survive_title(t):
    fg, _ = _gameover_frame(t)
    if fg is None:
        return "no game over"
    fh, _ = _first_where(t, "n_heroi", lambda v: v >= 1, after_frame=fg)
    if fh is None:
        return "no new game"
    if t.at_frame(fh - 1, "pontos") != 700:
        return f"pontos={t.at_frame(fh - 1, 'pontos')} on the title (st is never cleared by an act change)"
    return True


# ---- buttons ----------------------------------------------------------------

def _chk_buttons(t):
    for f, tm, v in t.series("n_heroi"):
        if f <= 17 and v != 0:
            return f"Fase started at frame {f}: the disabled 'zerar recorde' click started a game"
    if t.end("n_heroi") != 1:
        return "clicking JOGAR did not start Fase"
    for f, tm, v in t.series("recorde"):
        if v != 0:
            return f"recorde={v}"
    return True


# ---- auto return ------------------------------------------------------------

def _chk_auto_title(t):
    fv = t.input_frame("cell", 0)
    fg, tg = _first_where(t, "n_heroi", lambda v: v == 0, after_frame=fv)
    if fg is None:
        return "Fase never ended"
    # The only later SPACE comes ~10.5 s after FimDeJogo: if FimDeJogo had not
    # gone back to Titulo by itself, that SPACE would go to Titulo, not Fase.
    if t.end("n_heroi") != 1:
        return "after 10 s FimDeJogo did not return to Titulo by itself"
    return True


# ---- boss -------------------------------------------------------------------

def _boss_t1(t):
    f0, _ = _fase_start(t)
    return _restart_frame(t, f0 or 0)


def _chk_boss_no_fleet(t):
    f1, _ = _boss_t1(t)
    if f1 is None:
        return "R never restarted"
    for f, tm, v in t.series("n_inimigo"):
        if f >= f1 and v != 0:
            return f"{v} fleet enemies in fase 2 at frame {f}"
    return True


def _chk_boss_spawn_time(t):
    f1, t1 = _boss_t1(t)
    if f1 is None:
        return "no restart"
    for f, tm, v in t.series("n_chefe"):
        if f < f1:
            continue
        if tm < t1 + 2.45 and v != 0:
            return f"boss present {tm - t1:.3f}s into fase 2 (warning is 2.5 s)"
        if tm > t1 + 2.55 and v != 1:
            return f"n_chefe={v} at {tm - t1:.3f}s"
    return True


def _chk_boss_entry_path(t):
    f1, t1 = _boss_t1(t)
    if f1 is None:
        return "no restart"
    for f, tm, v in _between(t, "chefe_center", t1 + 2.55, t1 + 4.45):
        if v is None:
            return f"no boss at {tm - t1:.3f}s"
        if not close(v[0], 500, 0.5) or not (600 - 0.5 <= v[1] <= 900 + 0.5):
            return f"boss at {v} while arriving (straight down x=500, y 900->600)"
    v = _value_at_time(t, "chefe_center", t1 + 4.45)
    if v is None or not close(v, (500, 600), 3.0):
        return f"boss at {v} at the end of chegando, expected (500, 600)"
    return True


def _chk_boss_invulnerable_arriving(t):
    f1, t1 = _boss_t1(t)
    if f1 is None:
        return "no restart"
    for f, tm, v in _between(t, "chefe_vida", t1 + 2.55, t1 + 4.4):
        if v != 30:
            return f"boss vida={v} while arriving (hits only count in lutando)"
    return True


def _chk_boss_vida_monotone(t):
    prev = None
    for f, tm, v in t.series("chefe_vida"):
        if v is None:
            prev = None
            continue
        if prev is not None and v > prev:
            return f"boss vida rose {prev}->{v} at frame {f}"
        if v < 0:
            return f"boss vida {v}"
        prev = v
    return True


def _chk_boss_hit(t):
    f1, t1 = _boss_t1(t)
    if f1 is None:
        return "no restart"
    v = t.end("chefe_vida")
    if v is None or v >= 30:
        return f"boss vida {v} at end: the stream of shots at x=500 never hit while it flew the eight"
    return True


def _chk_boss_volley(t):
    f1, t1 = _boss_t1(t)
    if f1 is None:
        return "no restart"
    for f, tm, v in t.series("n_tiro_inimigo"):
        if f >= f1 and tm < t1 + 4.5 + 1.6 - 0.1 and v != 0:
            return f"enemy bullet at {tm - t1:.3f}s, before the first volley"
    got = [v for f, tm, v in _between(t, "n_tiro_inimigo", t1 + 6.0, t1 + 6.4)]
    if not got or max(got) < 5:
        return f"first volley not seen (max {max(got) if got else None} enemy bullets)"
    return True


def _chk_boss_eight_bounds(t):
    f1, t1 = _boss_t1(t)
    if f1 is None:
        return "no restart"
    for f, tm, v in t.series("chefe_center"):
        if f < f1 or tm < t1 + 4.6 or v is None:
            continue
        x, y = v
        if not (220 - 2 <= x <= 780 + 2 and 555 - 2 <= y <= 645 + 2):
            return f"boss at ({x:.1f}, {y:.1f}) outside the 560x90 eight around (500, 600)"
    return True


def _chk_boss_moves(t):
    f1, t1 = _boss_t1(t)
    if f1 is None:
        return "no restart"
    pts = [v for f, tm, v in _between(t, "chefe_center", t1 + 5.0, t1 + 7.5) if v is not None]
    if not pts:
        return "no boss"
    xs = [p[0] for p in pts]
    if max(xs) - min(xs) < 100:
        return f"boss x span {max(xs) - min(xs):.1f} in 2.5 s of the eight"
    return True


def _chk_boss_spin(t):
    f1, t1 = _boss_t1(t)
    if f1 is None:
        return "no restart"
    a = _value_at_time(t, "chefe_angle", t1 + 5.0)
    b = _value_at_time(t, "chefe_angle", t1 + 5.5)
    c = _value_at_time(t, "chefe_angle", t1 + 7.5)
    if None in (a, b, c):
        return "no boss angle"
    d1 = (b - a) % 360.0
    d2 = (c - a) % 360.0
    if not close(d1, 60.0, 2.5):
        return f"boss turned {d1:.2f} deg in 0.5 s, expected 60 (360 per 3 s, linear)"
    if not close(d2, 300.0, 2.5):
        return f"boss turned {d2:.2f} deg (mod 360) in 2.5 s, expected 300"
    return True


def _chk_fase2_kept(t):
    f1, _ = _boss_t1(t)
    if f1 is None:
        return "no restart"
    if t.at_frame(f1, "fase") != 2:
        return "st.fase not 2 in the restarted Fase"
    return True


# ----------------------------------------------------------------- scenarios

SCENARIOS = {
    # nothing pressed: the title stays
    "idle": Scenario(params={}, seed=0, steps=[wait(240)]),
    # keys the title does not read
    "title_other_keys": Scenario(params={}, seed=0, steps=[
        wait(5), key("R"), wait(5), key("LEFT", frames=10), wait(5),
        key("RIGHT", frames=10), wait(20),
    ]),
    # SPACE starts; then nothing (fleet arrives and sits)
    "start_idle": Scenario(params={}, seed=0, steps=[
        wait(5), key("SPACE"), wait(380),
    ]),
    # movement and the AREA clamp
    "move": Scenario(params={}, seed=0, steps=[
        wait(5), key("SPACE"), wait(10),
        key("LEFT", frames=30), wait(5),
        key("RIGHT", frames=30), wait(5),
        key("LEFT", frames=120), wait(5),
        key("RIGHT", frames=170), wait(10),
    ]),
    # move under column x=451.5 (9 frames LEFT -> x~449), hold SPACE 1 s
    "shoot": Scenario(params={}, seed=0, steps=[
        wait(5), key("SPACE"), wait(180),
        key("LEFT", frames=9), wait(3),
        key("SPACE", frames=60), wait(130),
    ]),
    # R restarts Fase with a fresh hero and fleet, st kept
    "restart": Scenario(params={}, seed=0, steps=[
        wait(5), key("SPACE"), wait(10),
        key("LEFT", frames=30), wait(90),
        key("R"), wait(130),
    ]),
    # lose (vidas := 0) -> FimDeJogo -> SPACE -> Titulo -> zerar recorde -> SPACE -> Fase
    "lose_cycle": Scenario(params={}, seed=0, steps=[
        wait(2), key("SPACE"), wait(10),
        key("LEFT", frames=30), wait(5),
        set_cell("st.pontos", 700), set_cell("st.vidas", 0),
        wait(5), key("R"), wait(5), key("LEFT", frames=10),
        wait(100),
        key("SPACE"), wait(30),
        click(500, 240), wait(10),
        key("SPACE"), wait(20),
    ]),
    # title buttons: zerar (disabled, recorde 0) then JOGAR
    "buttons": Scenario(params={}, seed=0, steps=[
        wait(5), click(500, 240), wait(10), click(500, 320), wait(20),
    ]),
    # FimDeJogo goes back to Titulo after 10 s by itself (coarse dt keeps it short)
    "auto_title": Scenario(params={}, seed=0, dt=1.0 / 20.0, steps=[
        wait(2), key("SPACE"), wait(4),
        set_cell("st.vidas", 0),
        wait(240),
        key("SPACE"), wait(10),
    ]),
    # fase 2: boss
    "boss": Scenario(params={}, seed=0, steps=[
        wait(2), key("SPACE"), wait(10),
        key("LEFT", frames=30), wait(5),
        set_cell("st.fase", 2), wait(2),
        key("R"), wait(10),
        key("SPACE", frames=440), wait(20),
    ]),
}


# --------------------------------------------------------------- expectations

ACT = "design/Act Design.md"
GUIA = "docs/pt/guide/index.html"

EXPECT = [
    # ---- startup / title
    Expect(id="E1", level="L0", cite=f"{ACT}#starting-runtitulo",
           text="With no input the game stays in Titulo: no hero, enemies, boss or bullets exist.",
           check=custom(_chk_title_empty), scenarios=("idle", "title_other_keys")),
    Expect(id="E2", level="L0", cite=f"{ACT}#game-data-st-is-the-one-channel",
           text="At startup st holds jogo_novo() values (pontos 0, vidas 3, fase 1, venceu False) and recorde 0; the title changes none of them.",
           check=custom(_chk_title_st), scenarios=("idle", "title_other_keys")),
    Expect(id="E3", level="L0", cite=f"{GUIA}#atos-trocar",
           text="SPACE on the title (keyp.once) calls comecar -> change_act(Fase): the hero exists within 2 frames of the press.",
           check=custom(_chk_space_starts), scenarios=("start_idle", "move", "shoot", "restart")),
    Expect(id="E4", level="L1", cite=f"{GUIA}#atos",
           text="Fase.setup builds the hero at (500, 70) (tol 0.5).",
           check=custom(_chk_hero_spawn), scenarios=("start_idle", "move", "shoot")),
    Expect(id="E5", level="L0", cite=f"{ACT}#change_act",
           text="Exactly one hero exists while Fase runs (teardown before build; a restart leaves one).",
           check=custom(_chk_one_hero), scenarios=("start_idle", "move", "shoot", "restart")),
    # ---- fleet
    Expect(id="E6", level="L0", cite=f"{GUIA}#mode-async",
           text="No enemy exists during the 1.5 s FASE 1 banner; after it there are exactly 24 (8x3) for the rest of an un-shot run.",
           check=custom(_chk_fleet_timing), scenarios=("start_idle",)),
    Expect(id="E7", level="L1", cite=f"{GUIA}#colocar-grid",
           text="At +3 s and +6 s (after the 1 s arrival, before any dive at >= +6.5 s) the enemies sit on the 8x3 grid cell centres (x 160.5+97i, y 652/590/528), tol 1.",
           check=custom(_chk_fleet_grid), scenarios=("start_idle",)),
    Expect(id="E8", level="L2", cite=f"{GUIA}#mover-tween",
           text="While arriving (move_to from y=H+60 with ease_out) no enemy is below the lowest slot (y >= 527).",
           check=custom(_chk_fleet_arrives_from_above), scenarios=("start_idle",)),
    Expect(id="E9", level="L0", cite=f"{GUIA}#agendar-timers",
           text="No enemy bullet exists before Fase start + 4.9 s: every(uniform(2.5, 4)) starts at formacao (+2.5 s) and first fires after one interval.",
           check=custom(_chk_no_enemy_fire_early), scenarios=("start_idle", "shoot"), guess=True),
    Expect(id="E10", level="L0", cite=f"{GUIA}#agendar-timers",
           text="The hero keeps 3 lives for the first 5.8 s of Fase (no enemy bullet can exist or reach it earlier; enemy bodies do not hurt).",
           check=custom(_vidas_full_until(5.8)), scenarios=("start_idle", "shoot", "move"), guess=True),
    Expect(id="E11", level="L1", cite=f"{GUIA}#frame-teclado",
           text="With no arrow held the hero stays at x=500.",
           check=custom(_chk_hero_still), scenarios=("start_idle",)),
    Expect(id="E12", level="L0", cite=f"{GUIA}#reagir-when",
           text="Within one Fase lives never rise and drop by one at most once per 0.8 s (the 'ferido' window).",
           check=custom(_chk_vidas_monotone_and_ferido), scenarios=("start_idle", "shoot", "boss")),
    # ---- movement
    Expect(id="E13", level="L1", cite=f"{GUIA}#frame-teclado",
           text="Holding LEFT for 30 frames moves the hero 30*340/60 = 170 px left (tol one frame step).",
           check=custom(_chk_left_30), scenarios=("move",)),
    Expect(id="E14", level="L2", cite=f"{GUIA}#frame-teclado",
           text="The hero never moves more than 340/60 px in one frame (an act change aside, it is only moved by move_by(dx) and confine).",
           check=custom(_chk_step_bound), scenarios=("move", "start_idle")),
    Expect(id="E15", level="L1", cite=f"{GUIA}#mover-confine",
           text="The hero stays on y=70 (move_by(dx, 0) only).",
           check=custom(_chk_hero_y), scenarios=("move", "shoot", "start_idle")),
    Expect(id="E16", level="L1", cite=f"{GUIA}#mover-confine",
           text="confine(AREA) with by='center' clamps the hero centre to x in [40, 960] and both edges are reached by long holds.",
           check=custom(_chk_clamp), scenarios=("move",)),
    # ---- shooting
    Expect(id="E17", level="L0", cite=f"{GUIA}#agendar-ready",
           text="Holding SPACE spawns a Tiro at once and then one every 0.15 s: 3 bullets 22 frames after the first.",
           check=custom(_chk_fire_rate), scenarios=("shoot",)),
    Expect(id="E18", level="L1", cite=f"{GUIA}#mover-tween",
           text="A hero bullet rises 560/60 px per frame (tol 0.05).",
           check=custom(_chk_bullet_speed), scenarios=("shoot",)),
    Expect(id="E19", level="L1", cite="tests/programs/galaga_acts.py (Tiro center=hero+(0,28))",
           text="The first bullet appears at hero y + 28 (plus at most one frame of travel).",
           check=custom(_chk_bullet_origin), scenarios=("shoot",), guess=True),
    Expect(id="E20", level="L0", cite=f"{GUIA}#mode-async",
           text="Each kill gives exactly 100 points once (a dying enemy absorbs bullets without scoring): pontos is a multiple of 100, 100..300 for one column.",
           check=custom(_chk_points_shape), scenarios=("shoot",)),
    Expect(id="E21", level="L0", cite=f"{GUIA}#mundo-grupos",
           text="After the dissolves end, pontos == 100 * (24 - enemies left).",
           check=custom(_chk_points_match_kills), scenarios=("shoot",)),
    Expect(id="E22", level="L0", cite=f"{GUIA}#mover-tween",
           text="A killed enemy stays in its group during the 0.3 s dissolve and is gone by 0.4 s.",
           check=custom(_chk_dissolve_delay), scenarios=("shoot",)),
    Expect(id="E23", level="L0", cite=f"{GUIA}#reagir-bounds",
           text="Bullets that leave the playfield (pad 0.25 -> top y=1000) are destroyed: none remain 2 s after SPACE is released.",
           check=at_end("n_tiro", lambda v: v == 0), scenarios=("shoot",)),
    Expect(id="E24", revised="SPEC-LOGIC: 1.61 s / 0.15 s allows 11 alive; the bound said 8", level="L2", cite=f"{GUIA}#agendar-ready",
           text="At most 11 hero bullets live at once (0.15 s cadence, 1.61 s to leave).",
           check=custom(_chk_tiros_bounded), scenarios=("shoot", "boss")),
    # ---- restart
    Expect(id="E25", level="L0", cite=f"{ACT}#switching-change_actfase",
           text="R in Fase (vidas > 0) builds a new Fase: the hero is back at x=500, still one hero.",
           check=custom(_chk_restart_hero), scenarios=("restart",)),
    Expect(id="E26", level="L0", cite=f"{ACT}#lifetime-the-game-and-the-act",
           text="The restart removes the 24 enemies at once; the new Fase has none for 1.5 s, then 24 again (never more).",
           check=custom(_chk_restart_clears_fleet), scenarios=("restart",)),
    Expect(id="E27", level="L0", cite=f"{ACT}#game-data-st-is-the-one-channel",
           text="st is not cleared by the restart (pontos 0, vidas 3, fase 1, recorde 0 throughout).",
           check=custom(_chk_restart_keeps_st), scenarios=("restart",)),
    # ---- lose / FimDeJogo / Titulo
    Expect(id="E28", level="L0", cite=f"{ACT}#act-rules-watch-changes-not-states",
           text="With vidas 0 the hero ignores arrows and R does not restart (guard st.vidas > 0): its x stays put until FimDeJogo.",
           check=custom(_chk_dead_hero_ignores_input), scenarios=("lose_cycle",)),
    Expect(id="E29", level="L0", cite=f"{GUIA}#reagir-when",
           text="@when(st.vidas == 0) fires on the edge; 1.5 s later FimDeJogo replaces Fase (hero and enemies gone).",
           check=custom(_chk_gameover_delay), scenarios=("lose_cycle",)),
    Expect(id="E30", level="L0", cite=f"{ACT}#game-data-st-is-the-one-channel",
           text="FimDeJogo.setup sets recorde = max(recorde, pontos) = 700 and venceu stays False.",
           check=custom(_chk_gameover_st), scenarios=("lose_cycle",)),
    Expect(id="E31", level="L0", cite=f"{ACT}#change_act",
           text="SPACE in FimDeJogo goes to Titulo and the same press does not also start Fase (hero returns only after the later SPACE).",
           check=custom(_chk_space_no_carry), scenarios=("lose_cycle",)),
    Expect(id="E32", level="L0", cite=f"{GUIA}#ui-sprite-button",
           text="recorde survives into Titulo; clicking the enabled 'zerar recorde' SpriteButton sets it to 0.",
           check=custom(_chk_recorde_cleared), scenarios=("lose_cycle",)),
    Expect(id="E33", level="L0", cite=f"{ACT}#game-data-st-is-the-one-channel",
           text="pontos (700) is kept through FimDeJogo and Titulo (st never cleared by a change).",
           check=custom(_chk_pontos_survive_title), scenarios=("lose_cycle",)),
    Expect(id="E34", level="L0", cite=f"{GUIA}#atos",
           text="SPACE on the title starts a new game: jogo_novo() resets pontos 0, vidas 3, fase 1 and one hero exists.",
           check=custom(_chk_new_game), scenarios=("lose_cycle",)),
    Expect(id="E35", level="L0", cite=f"{GUIA}#ui-sprite-button",
           text="The disabled 'zerar recorde' (recorde 0) does not click; clicking JOGAR starts Fase; recorde stays 0.",
           check=custom(_chk_buttons), scenarios=("buttons",)),
    Expect(id="E36", level="L0", cite=f"{GUIA}#atos",
           text="FimDeJogo returns to Titulo by itself after 10 s (a SPACE 10.5 s later starts Fase).",
           check=custom(_chk_auto_title), scenarios=("auto_title",)),
    # ---- boss
    Expect(id="E37", level="L0", cite=f"{ACT}#game-data-st-is-the-one-channel",
           text="With st.fase = 2, R restarts Fase in boss mode: fase stays 2.",
           check=custom(_chk_fase2_kept), scenarios=("boss",)),
    Expect(id="E38", level="L0", cite=f"{ACT}#acts-and-modes",
           text="In fase 2 no fleet enemy ever appears.",
           check=custom(_chk_boss_no_fleet), scenarios=("boss",)),
    Expect(id="E39", level="L0", cite=f"{GUIA}#mode-async",
           text="The boss appears 2.5 s into fase 2 (after the warning) and is alone (count 1) after that.",
           check=custom(_chk_boss_spawn_time), scenarios=("boss",)),
    Expect(id="E40", level="L1", cite=f"{GUIA}#mover-tween",
           text="The boss flies straight down x=500 from y=900 to (500, 600) over 2 s (tol 3 at the end).",
           check=custom(_chk_boss_entry_path), scenarios=("boss",)),
    Expect(id="E41", level="L0", cite="tests/programs/galaga_acts.py (Chefe.atingido guard)",
           text="Hits while the boss arrives do not count: vida stays 30 until lutando.",
           check=custom(_chk_boss_invulnerable_arriving), scenarios=("boss",)),
    Expect(id="E42", level="L0", cite="tests/programs/galaga_acts.py (Chefe.atingido)",
           text="Boss vida never rises and never goes below 0.",
           check=custom(_chk_boss_vida_monotone), scenarios=("boss",)),
    Expect(id="E43", level="L0", cite=f"{GUIA}#agendar-timers",
           text="No enemy bullet before lutando + 1.6 s; the first volley puts at least 5 enemy bullets up by then.",
           check=custom(_chk_boss_volley), scenarios=("boss",), guess=True),
    Expect(id="E44", level="L2", cite=f"{GUIA} (Track: anchored, center=)",
           text="In lutando the boss stays inside the anchored 560x90 eight's box around (500, 600) (slop 2).",
           check=custom(_chk_boss_eight_bounds), scenarios=("boss",), guess=True),
    Expect(id="E45", level="L2", cite=f"{GUIA} (Track, move_along)",
           text="In lutando the boss actually travels the eight (x spans >= 100 px within 2.5 s).",
           check=custom(_chk_boss_moves), scenarios=("boss",)),
    Expect(id="E46", level="L1", cite=f"{GUIA}#mover-tween",
           text="rotate_by(360, time=3, loops='forever') with default linear ease turns the boss 60 deg per 0.5 s (tol 2.5, mod 360).",
           check=custom(_chk_boss_spin), scenarios=("boss",)),
    Expect(id="E47", level="L0", cite=f"{GUIA}#mover-tween",
           text="A constant stream of shots at x=500 hits the boss at least once while it flies the eight through x=500.",
           check=custom(_chk_boss_hit), scenarios=("boss",), guess=True),
]
