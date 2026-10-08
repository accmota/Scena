"""Spec B for examples/pegar_estrelas.py (tutorial 02, last step).

Written from the docs only (tutorial 02, the Guia, Scena Design), before the
engine ever ran this program.
"""

from program_support import (Scenario, Expect, wait, wait_s, click_widget, click,
    key, key_down, key_up, move, scroll, set_cell, always, never, at, at_end,
    eventually, steady, all_of, custom, close)
import math

FILES_READ = [
    "examples/pegar_estrelas.py",
    "docs/pt/tutorial/02-pegar-estrelas.html",
    "design/Scena Design.md#frame-order",
    "design/Scena Design.md#datapath",
    "docs/pt/guide/index.html#agendar-timers",
    "docs/pt/guide/index.html#frame-clock",
    "docs/pt/guide/index.html#frame-teclado",
    "docs/pt/guide/index.html#colisao-collide",
    "docs/pt/guide/index.html#mundo-grupos",
    "docs/pt/guide/index.html#desenhar-drawable",
    "docs/pt/guide/index.html#desenhar-text",
    "docs/pt/guide/index.html#aparencia-transientes",
    "docs/pt/guide/index.html#spr-hit-medir",
    "docs/pt/guide/index.html#spr-size",
]

DT = 1.0 / 60.0
BAR_STEP = 380.0 * DT          # bar displacement per held frame
FALL_STEP = 220.0 * DT         # star displacement per frame
SPAWN_EVERY = 0.9
EPS = 1e-6

# --------------------------------------------------------------------------
# Probes
# --------------------------------------------------------------------------

_TRACK = {}


def _stars(p):
    """Every star ever seen in group["estrelas"], in order of first sighting.

    Returns ((index, in_group, alive, x, y), ...). The registry keeps a
    reference to the run's barra so a new run (new barra) starts fresh.
    """
    key_ = id(p.barra)
    reg = _TRACK.get(key_)
    if reg is None or reg["barra"] is not p.barra:
        reg = {"barra": p.barra, "stars": [], "ids": set()}
        _TRACK.clear()
        _TRACK[key_] = reg
    for e in p.group["estrelas"]:
        if id(e) not in reg["ids"]:
            reg["ids"].add(id(e))
            reg["stars"].append(e)
    out = []
    for i, s in enumerate(reg["stars"]):
        alive = bool(s.is_alive)
        in_group = bool(alive and s.tagged("estrelas"))
        c = s.center
        out.append((i, in_group, alive, float(c.x), float(c.y)))
    return tuple(out)


def _xy(pt):
    if hasattr(pt, "x"):
        return (float(pt.x), float(pt.y))
    return (float(pt[0]), float(pt[1]))


PROBES = {
    "stars": _stars,
    "barra": lambda p: (p.barra.center.x, p.barra.center.y),
    "barra_w": lambda p: p.barra.width,
    "heroi": lambda p: (len(p.group["heroi"]), p.barra in p.group["heroi"]),
    "n_estrelas": lambda p: len(p.group["estrelas"]),
    "pontos": lambda p: p.st.pontos,
    "perdidas": lambda p: p.st.perdidas,
    "texto": lambda p: p.placar.text,
    "camada": lambda p: p.placar.layer,
    "placar_tl": lambda p: _xy(p.placar.top_left),
}

# --------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------

SCENARIOS = {
    # nothing pressed: the bar never moves, stars fall and are caught or lost
    "parado": Scenario(params={}, seed=0, steps=[wait(600)]),
    # hold RIGHT 46 frames: 500 + 46*380/60 = 791.3, under the first star
    # (seed 0 -> uniform(80, 920) = 789.3 if nothing else draws first)
    "pega": Scenario(params={}, seed=0, steps=[key("RIGHT", frames=46), wait(400)]),
    # hold LEFT 120 frames: 500 - 760 = -260 (no clamp in the program)
    "esquerda": Scenario(params={}, seed=3, steps=[key("LEFT", frames=120), wait(380)]),
    # both arrows held: the two move_by cancel
    "ambas": Scenario(params={}, seed=1, steps=[
        key_down("LEFT"), key_down("RIGHT"), wait(60),
        key_up("LEFT"), key_up("RIGHT"), wait(200)]),
}

# --------------------------------------------------------------------------
# Trace helpers (plain Python over the frozen samples)
# --------------------------------------------------------------------------


def _star_hist(t):
    """index -> list of (frame, in_group, alive, x, y), ordered by frame."""
    hist = {}
    for frame, _time, val in t.series("stars"):
        if not isinstance(val, tuple):
            continue
        for rec in val:
            i = int(rec[0])
            hist.setdefault(i, []).append(
                (frame, bool(rec[1]), bool(rec[2]), float(rec[3]), float(rec[4])))
    return hist


def _first_out(rows):
    """First row where the star is no longer in the group, or None."""
    for r in rows:
        if not r[1]:
            return r
    return None


def _frame_value(t, probe):
    return {f: v for f, _tm, v in t.series(probe)}


# --- checks ---------------------------------------------------------------


def _check_first_spawn(t):
    for frame, _tm, n in t.series("n_estrelas"):
        if n >= 1:
            if frame in (54, 55):
                return True
            return "first star appeared at frame %s, expected 54 or 55 (t = 0.9 s)" % frame
    return "no star ever appeared"


def _check_spawn_count(t):
    seen = {f: len(v) for f, _tm, v in t.series("stars") if isinstance(v, tuple)}
    for frame, tm, _v in t.series("stars"):
        q = tm / SPAWN_EVERY
        frac = q - math.floor(q)
        margin = 1.5 * DT / SPAWN_EVERY
        if frac < margin or frac > 1 - margin:
            continue  # within a frame of a firing instant: timing slop
        expected = int(math.floor(q))
        if seen.get(frame) != expected:
            return "frame %d (t=%.4f): %s stars spawned, expected %d" % (
                frame, tm, seen.get(frame), expected)
    return True


def _check_spawn_y(t):
    for i, rows in _star_hist(t).items():
        f, ing, alive, x, y = rows[0]
        if abs(y - 780.0) > EPS:
            return "star %d first seen at y=%.4f (frame %d), expected 780" % (i, y, f)
    return True


def _check_spawn_x(t):
    for i, rows in _star_hist(t).items():
        x = rows[0][3]
        if not (80.0 - EPS <= x <= 920.0 + EPS):
            return "star %d spawned at x=%.3f, outside [80, 920]" % (i, x)
    return True


def _check_fall(t):
    for i, rows in _star_hist(t).items():
        for a, b in zip(rows, rows[1:]):
            if b[0] != a[0] + 1:
                continue
            if a[1] and b[1]:  # in group on both samples
                if abs((a[4] - b[4]) - FALL_STEP) > 1e-6:
                    return "star %d fell %.5f between frames %d and %d, expected %.5f" % (
                        i, a[4] - b[4], a[0], b[0], FALL_STEP)
                if abs(a[3] - b[3]) > 1e-6:
                    return "star %d moved in x between frames %d and %d" % (i, a[0], b[0])
    return True


def _check_group_band(t):
    for frame, _tm, val in t.series("stars"):
        for rec in val:
            if rec[1] and not (40.0 - EPS <= rec[4] <= 780.0 + EPS):
                return "frame %d: star %d in group at y=%.3f, outside [40, 780]" % (
                    frame, rec[0], rec[4])
    return True


def _check_conservation(t):
    pts = _frame_value(t, "pontos")
    lost = _frame_value(t, "perdidas")
    for frame, _tm, val in t.series("stars"):
        in_group = sum(1 for r in val if r[1])
        total = len(val)
        s = int(pts[frame]) + int(lost[frame]) + in_group
        if s != total:
            return "frame %d: pontos %s + perdidas %s + in group %d != %d spawned" % (
                frame, pts[frame], lost[frame], in_group, total)
    return True


def _transitions(t):
    """frame -> (caught, lost): stars leaving the group that frame,
    destroyed (caught) or still alive (lost)."""
    out = {}
    for i, rows in _star_hist(t).items():
        for a, b in zip(rows, rows[1:]):
            if a[1] and not b[1]:
                c, l = out.get(b[0], (0, 0))
                if b[2]:
                    l += 1
                else:
                    c += 1
                out[b[0]] = (c, l)
    return out


def _check_delta(probe, which):
    def fn(t):
        tr = _transitions(t)
        series = t.series(probe)
        for (fa, _ta, va), (fb, _tb, vb) in zip(series, series[1:]):
            want = tr.get(fb, (0, 0))[which]
            if int(vb) - int(va) != want:
                return "frame %d: %s went %s -> %s, expected +%d" % (fb, probe, va, vb, want)
        return True
    return fn


def _check_never_back(t):
    for i, rows in _star_hist(t).items():
        out = False
        for r in rows:
            if out and r[1]:
                return "star %d re-entered the group at frame %d" % (i, r[0])
            if not r[1]:
                out = True
    return True


def _check_lost_threshold(t):
    for i, rows in _star_hist(t).items():
        r = _first_out(rows)
        if r is None or not r[2]:
            continue  # still falling, or caught
        if not (40.0 - FALL_STEP - 1e-6 <= r[4] < 40.0):
            return "lost star %d left the group at y=%.4f, expected in [%.3f, 40)" % (
                i, r[4], 40.0 - FALL_STEP)
    return True


def _check_lost_frozen(t):
    for i, rows in _star_hist(t).items():
        r = _first_out(rows)
        if r is None or not r[2]:
            continue
        for q in rows:
            if q[0] > r[0] and q[2]:
                if abs(q[3] - r[3]) > 1e-6 or abs(q[4] - r[4]) > 1e-6:
                    return "lost star %d moved after leaving the group (frame %d)" % (i, q[0])
    return True


def _check_lost_destroy_delay(t):
    last_frame = t.samples[-1].frame if t.samples else 0
    for i, rows in _star_hist(t).items():
        r = _first_out(rows)
        if r is None or not r[2]:
            continue
        dead = next((q for q in rows if not q[2]), None)
        if dead is None:
            if last_frame - r[0] > 13:
                return "lost star %d still alive %d frames after leaving" % (i, last_frame - r[0])
            continue
        gap = dead[0] - r[0]
        if not (11 <= gap <= 13):
            return "lost star %d destroyed %d frames after it left the group, expected ~12" % (i, gap)
    return True


def _check_catch_geometry(t):
    bar = _frame_value(t, "barra")
    for i, rows in _star_hist(t).items():
        r = _first_out(rows)
        if r is None:
            continue
        bx = bar[r[0]][0]
        dx = abs(r[3] - bx)
        if not r[2] and dx > 60.0:
            return "star %d caught with |dx| = %.2f from the bar (frame %d)" % (i, dx, r[0])
        if r[2] and dx < 20.0:
            return "star %d lost though it fell right over the bar (|dx| = %.2f)" % (i, dx)
    return True


def _check_text(t):
    pts = _frame_value(t, "pontos")
    lost = _frame_value(t, "perdidas")
    for frame, _tm, txt in t.series("texto"):
        want = "Estrelas %d   Perdidas %d" % (int(pts[frame]), int(lost[frame]))
        if txt != want:
            return "frame %d: placar %r, expected %r" % (frame, txt, want)
    return True


def _check_bar_steps(t):
    s = t.series("barra")
    for (fa, _ta, a), (fb, _tb, b) in zip(s, s[1:]):
        dx = b[0] - a[0]
        if not (abs(dx) < 1e-6 or abs(abs(dx) - BAR_STEP) < 1e-6):
            return "bar moved %.5f between frames %d and %d (allowed 0 or +-%.5f)" % (
                dx, fa, fb, BAR_STEP)
        if abs(b[1] - 80.0) > 1e-6:
            return "bar left y = 80 at frame %d" % fb
    return True


def _check_hold_rate(sign, first, last):
    def fn(t):
        s = t.series("barra")
        for (fa, _ta, a), (fb, _tb, b) in zip(s, s[1:]):
            if first <= fb <= last:
                if abs((b[0] - a[0]) - sign * BAR_STEP) > 1e-6:
                    return "frame %d: bar dx %.5f, expected %.5f while held" % (
                        fb, b[0] - a[0], sign * BAR_STEP)
        return True
    return fn


def _check_both_held(t):
    s = t.series("barra")
    moving = 0
    for (fa, _ta, a), (fb, _tb, b) in zip(s, s[1:]):
        if abs(b[0] - a[0]) > 1e-6:
            moving += 1
    if moving > 2:
        return "bar moved on %d frames while both arrows were held" % moving
    if abs(s[-1][2][0] - 500.0) > 2 * BAR_STEP + 1e-6:
        return "bar ended at x=%.3f, expected ~500" % s[-1][2][0]
    return True


def _check_first_star_caught(t):
    rows = _star_hist(t).get(0)
    if not rows:
        return "no star 0"
    r = _first_out(rows)
    if r is None:
        return "star 0 never left the group"
    if r[2]:
        return "star 0 was lost (x=%.2f), expected caught" % r[3]
    return True


# --------------------------------------------------------------------------
# Expectations
# --------------------------------------------------------------------------

T02 = "docs/pt/tutorial/02-pegar-estrelas.html"

EXPECT = [
    # ---- startup ----
    Expect(id="E1", level="L0", cite=T02 + "#Placar",
           text="On the first frame both counters are 0 and the scoreboard reads 'Estrelas 0   Perdidas 0'.",
           check=all_of(at(1, "pontos", lambda v: v == 0),
                        at(1, "perdidas", lambda v: v == 0),
                        at(1, "texto", lambda v: v == "Estrelas 0   Perdidas 0")),
           scenarios=("*",)),
    Expect(id="E2", level="L0", cite="docs/pt/guide/index.html#desenhar-text",
           text="The scoreboard Text has no layer= and a top_left= point, so it lives on the ui layer.",
           check=always("camada", lambda v: v == "ui"),
           scenarios=("parado",)),
    Expect(id="E3", level="L0", cite="docs/pt/guide/index.html#desenhar-text",
           text="The scoreboard's top-left anchor stays at (20, 780) as the text changes (assumes Text exposes .top_left as a point).",
           check=always("placar_tl", lambda v: close(v, (20.0, 780.0), 1e-6)),
           scenarios=("parado",), guess=True),
    Expect(id="E4", level="L0", cite=T02 + "#A barra; docs/pt/guide/index.html#spr-hit-medir",
           text="The bar keeps width 80 (the size given), even after pop() when it catches a star.",
           check=always("barra_w", lambda v: close(v, 80.0, 1e-6)),
           scenarios=("*",)),
    Expect(id="E5", level="L0", cite=T02 + "#Colisão; docs/pt/guide/index.html#mundo-grupos",
           text="group['heroi'] holds exactly the bar for the whole run.",
           check=always("heroi", lambda v: int(v[0]) == 1 and bool(v[1])),
           scenarios=("*",)),

    # ---- the bar and the arrows ----
    Expect(id="E6", level="L0", cite=T02 + "#A barra",
           text="With no key pressed the bar stays at (500, 80).",
           check=always("barra", lambda v: close(v, (500.0, 80.0), 1e-6)),
           scenarios=("parado",)),
    Expect(id="E7", level="L1", cite=T02 + "#A barra; docs/pt/guide/index.html#frame-teclado",
           text="Every frame the bar moves 0 or exactly 380*dt horizontally and never leaves y = 80.",
           check=custom(_check_bar_steps),
           scenarios=("*",)),
    Expect(id="E8", level="L1", cite=T02 + "#A barra",
           text="While RIGHT is held (frames 2..45, inside the hold) the bar advances +380/60 per frame.",
           check=custom(_check_hold_rate(+1, 2, 45)),
           scenarios=("pega",)),
    Expect(id="E9", level="L1", cite=T02 + "#A barra",
           text="After a 46-frame RIGHT hold the bar rests at x = 500 + 46*380/60 = 791.33 (tol one frame step).",
           check=at_end("barra", lambda v: abs(v[0] - (500.0 + 46 * BAR_STEP)) <= BAR_STEP + 1e-6),
           scenarios=("pega",)),
    Expect(id="E10", level="L1", cite=T02 + "#A barra",
           text="While LEFT is held (frames 2..119) the bar moves -380/60 per frame.",
           check=custom(_check_hold_rate(-1, 2, 119)),
           scenarios=("esquerda",)),
    Expect(id="E11", level="L1", cite=T02 + "#A barra",
           text="A 120-frame LEFT hold takes the bar to x = -260 (tol one step): the program never confines it (assumes no default playfield clamp).",
           check=at_end("barra", lambda v: abs(v[0] - (500.0 - 120 * BAR_STEP)) <= BAR_STEP + 1e-6),
           scenarios=("esquerda",), guess=True),
    Expect(id="E12", level="L1", cite="docs/pt/guide/index.html#frame-teclado",
           text="With both arrows held the two move_by cancel: at most 2 frames of motion (press/release skew) and the bar ends within 2 steps of x = 500.",
           check=custom(_check_both_held),
           scenarios=("ambas",)),

    # ---- the spawner ----
    Expect(id="E13", level="L0", cite="docs/pt/guide/index.html#agendar-timers; " + T02 + "#Uma lista",
           text="No star exists before 0.9 s; the first appears at the frame where clock.time reaches 0.9 (frame 54, or 55 for float slop).",
           check=custom(_check_first_spawn),
           scenarios=("*",)),
    Expect(id="E14", level="L0", cite="docs/pt/guide/index.html#agendar-timers",
           text="@every(0.9) fires once per 0.9 s: away from firing instants the number of stars ever spawned is floor(t / 0.9).",
           check=custom(_check_spawn_count),
           scenarios=("*",)),
    Expect(id="E15", level="L0", cite="design/Scena Design.md#frame-order",
           text="A new star is first sampled at y = 780 exactly: the timer runs in the process tick after update, so it has not fallen yet.",
           check=custom(_check_spawn_y),
           scenarios=("*",)),
    Expect(id="E16", level="L1", cite=T02 + "#De tempos em tempos",
           text="Every star spawns with x in [80, 920] (uniform(80, 920)).",
           check=custom(_check_spawn_x),
           scenarios=("*",)),

    # ---- falling ----
    Expect(id="E17", level="L1", cite=T02 + "#Uma estrela caindo",
           text="A star in the group falls exactly 220/60 per frame and keeps its x (tol 1e-6).",
           check=custom(_check_fall),
           scenarios=("*",)),
    Expect(id="E18", level="L2", cite=T02 + "#Efeitos",
           text="Every star still in group['estrelas'] at sample time has 40 <= y <= 780 (below 40 it was untagged in update).",
           check=custom(_check_group_band),
           scenarios=("*",)),

    # ---- lost stars ----
    Expect(id="E19", level="L1", cite=T02 + "#Efeitos",
           text="A lost star leaves the group on the frame its y first drops below 40, so its y is in [40 - 220/60, 40).",
           check=custom(_check_lost_threshold),
           scenarios=("*",)),
    Expect(id="E20", level="L1", cite=T02 + "#Efeitos",
           text="Once untagged, a lost star stops falling: its center is frozen until it is destroyed.",
           check=custom(_check_lost_frozen),
           scenarios=("*",)),
    Expect(id="E21", level="L1", cite=T02 + "#Efeitos; docs/pt/guide/index.html#agendar-timers",
           text="A lost star stays alive (flashing) and is destroyed by after(0.2) about 12 frames later (11..13 for timer slop).",
           check=custom(_check_lost_destroy_delay),
           scenarios=("*",)),
    Expect(id="E22", level="L0", cite=T02 + "#Efeitos",
           text="A star that left the group never re-enters it (untag happens once, the if cannot fire again).",
           check=custom(_check_never_back),
           scenarios=("*",)),
    Expect(id="E23", level="L0", cite=T02 + "#Efeitos",
           text="st.perdidas rises on a frame by exactly the number of stars that left the group still alive that frame.",
           check=custom(_check_delta("perdidas", 1)),
           scenarios=("*",)),

    # ---- caught stars ----
    Expect(id="E24", level="L0", cite=T02 + "#Colisão; docs/pt/guide/index.html#colisao-collide",
           text="st.pontos rises on a frame by exactly the number of stars destroyed straight out of the group that frame (@collide enter fires once per star).",
           check=custom(_check_delta("pontos", 0)),
           scenarios=("*",)),
    Expect(id="E25", level="L0", cite=T02 + "#Grupo; " + T02 + "#Placar",
           text="Conservation: pontos + perdidas + stars in group == stars spawned, on every frame.",
           check=custom(_check_conservation),
           scenarios=("*",)),
    Expect(id="E26", level="L2", cite=T02 + "#Colisão",
           text="Catches are geometric: a caught star was within 60 of the bar in x (40 half-bar + 16 half-star + 4 slop); a star falling within 20 of a still bar is never lost.",
           check=custom(_check_catch_geometry),
           scenarios=("*",)),
    Expect(id="E27", level="L0", cite=T02 + "#Placar",
           text="The scoreboard always reads f'Estrelas {pontos}   Perdidas {perdidas}' for the current values (formula linked with @=).",
           check=custom(_check_text),
           scenarios=("*",)),
    Expect(id="E28", level="L0", cite=T02 + "#Placar",
           text="Neither counter ever decreases.",
           check=all_of(custom(lambda t: all(b >= a for a, b in zip(t.values("pontos"), t.values("pontos")[1:])) or "pontos decreased"),
                        custom(lambda t: all(b >= a for a, b in zip(t.values("perdidas"), t.values("perdidas")[1:])) or "perdidas decreased")),
           scenarios=("*",)),

    # ---- seeded outcomes (depend on random being consumed only by the script) ----
    Expect(id="E29", level="L0", cite="harness: random seeded; " + T02 + "#De tempos em tempos",
           text="Seed 0, idle 10 s: star 5 (x=509.5) is caught and stars 1-4, 6, 7 are lost: pontos 1, perdidas 6 at the end (assumes only the script draws from random).",
           check=all_of(at_end("pontos", lambda v: v == 1), at_end("perdidas", lambda v: v == 6)),
           scenarios=("parado",), guess=True),
    Expect(id="E30", level="L0", cite="harness: random seeded; " + T02 + "#Colisão",
           text="Seed 0: the first star spawns at x=789.3, right over the bar parked at 791.3, and is caught (assumes only the script draws from random).",
           check=custom(_check_first_star_caught),
           scenarios=("pega",), guess=True),
    Expect(id="E31", level="L0", cite=T02 + "#Colisão",
           text="With the bar parked at x=-260, no star can be caught: pontos stays 0.",
           check=always("pontos", lambda v: v == 0),
           scenarios=("esquerda",)),
    Expect(id="E32", level="L0", cite=T02 + "#Efeitos",
           text="In 500 frames with nothing caught, the first lost star is counted by ~frame 54+202 and perdidas ends >= 1.",
           check=at_end("perdidas", lambda v: v >= 1),
           scenarios=("esquerda",)),
]
