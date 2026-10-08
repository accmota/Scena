"""Spec A for examples/pegar_estrelas.py, written from the docs only.

Frozen before the engine runs. Disagreements with spec B (or the engine) are findings.
"""

from program_support import (Scenario, Expect, wait, wait_s, click_widget, click,
    key, key_down, key_up, move, scroll, set_cell, always, never, at, at_end,
    eventually, steady, all_of, custom, close)
import math

FILES_READ = [
    "examples/pegar_estrelas.py",
    "docs/pt/tutorial/02-pegar-estrelas.html",
    "design/Scena Design.md#frame-order",
    "docs/pt/guide/index.html#agendar-timers",
    "docs/pt/guide/index.html#frame-clock",
    "docs/pt/guide/index.html#frame-teclado",
    "docs/pt/guide/index.html#colisao-collide",
    "docs/pt/guide/index.html#colisao-rapido",
    "docs/pt/guide/index.html#mundo-grupos",
    "docs/pt/guide/index.html#grp-entrar",
    "docs/pt/guide/index.html#grp-ler",
    "docs/pt/guide/index.html#desenhar-sprite (constructor table: size= / width=)",
    "docs/pt/guide/index.html#spr-size",
    "docs/pt/guide/index.html#spr-hit",
    "docs/pt/guide/index.html#aparencia-transientes",
]

DT = 1.0 / 60.0
FALL = 220.0 * DT          # star drop per frame
RUN = 380.0 * DT           # bar step per frame while an arrow is held
SPAWN_Y = 780.0
LOST_Y = 40.0
BAR0 = (500.0, 80.0)
EPS = 1e-6


# ---------------------------------------------------------------- probes

PROBES = {
    "t": lambda p: p.clock.time,
    "pontos": lambda p: p.st.pontos,
    "perdidas": lambda p: p.st.perdidas,
    "n_estrelas": lambda p: len(p.group["estrelas"]),
    "estrelas": lambda p: tuple((float(e.center.x), float(e.center.y))
                                for e in p.group["estrelas"]),
    "tam_estrelas": lambda p: tuple((float(e.width), float(e.height))
                                    for e in p.group["estrelas"]),
    "barra": lambda p: p.barra.center,
    "barra_w": lambda p: p.barra.width,
    "barra_h": lambda p: p.barra.height,
    "barra_hit_w": lambda p: p.barra.hitbox.box.width,
    "heroi_n": lambda p: len(p.group["heroi"]),
    "barra_no_heroi": lambda p: p.barra in p.group["heroi"],
    "placar": lambda p: p.placar.text,
}


# ---------------------------------------------------------------- scenarios

SCENARIOS = {
    # nothing pressed: ~10 stars spawn; the bar never moves.
    "parado": Scenario(params={}, seed=0, steps=[wait(590)]),
    # LEFT held 30 frames, then idle.
    "esquerda": Scenario(params={}, seed=0, steps=[key("LEFT", frames=30), wait(60)]),
    # RIGHT held 46 frames: bar from x=500 to ~791, under the first seed-0 star (~789).
    "direita": Scenario(params={}, seed=0, steps=[key("RIGHT", frames=46), wait(320)]),
    # seed 50: first star at x ~498 falls onto the idle bar (if the engine draws no
    # other numbers from the global random before the first spawn).
    "centro": Scenario(params={}, seed=50, steps=[wait(330)]),
    # both arrows: they cancel while both are held.
    "ambas": Scenario(params={}, seed=0, steps=[key_down("LEFT"), key_down("RIGHT"), wait(20),
                                                key_up("LEFT"), key_up("RIGHT"), wait(5)]),
    # LEFT held long: nothing confines the bar.
    "longe": Scenario(params={}, seed=0, steps=[key("LEFT", frames=90), wait(10)]),
}

MOVE_SCEN = ("esquerda", "direita", "ambas", "longe")


# ---------------------------------------------------------------- helpers

def _series(t, name):
    return t.series(name)


def _frames(t):
    """List of (frame, time, stars dict x->y, pontos, perdidas, bar(x,y), bar_h)."""
    out = []
    est = _series(t, "estrelas")
    pon = _series(t, "pontos")
    per = _series(t, "perdidas")
    bar = _series(t, "barra")
    bh = _series(t, "barra_h")
    for i in range(len(est)):
        f, tm, v = est[i]
        out.append((f, tm, {float(x): float(y) for (x, y) in v},
                    pon[i][2], per[i][2], bar[i][2], bh[i][2]))
    return out


def _departures(t):
    """Per frame: (frame, lost list, caught list, d_pontos, d_perdidas, bar, bar_h).

    A star that leaves the group is 'lost' when its next y (prev y - FALL) is < 40
    (perdeu untags it in update), otherwise 'caught' (pegou destroys it).
    """
    fr = _frames(t)
    res = []
    prev_stars, prev_p, prev_l = {}, 0.0, 0.0
    for (f, tm, stars, p, l, bar, bh) in fr:
        gone = [(x, y) for x, y in prev_stars.items() if x not in stars]
        lost = [(x, y) for x, y in gone if y - FALL < LOST_Y - EPS]
        caught = [(x, y) for x, y in gone if not (y - FALL < LOST_Y - EPS)]
        res.append((f, lost, caught, p - prev_p, l - prev_l, bar, bh))
        prev_stars, prev_p, prev_l = stars, p, l
    return res


def _placar_ok(t):
    pl = _series(t, "placar")
    pon = _series(t, "pontos")
    per = _series(t, "perdidas")
    for i, (f, _, txt) in enumerate(pl):
        want = "Estrelas %d   Perdidas %d" % (int(pon[i][2]), int(per[i][2]))
        if txt != want:
            return "frame %d: placar %r, expected %r" % (f, txt, want)
    return True


def _spawn_count_ok(t):
    n = _series(t, "n_estrelas")
    pon = _series(t, "pontos")
    per = _series(t, "perdidas")
    for i, (f, tm, v) in enumerate(n):
        k = v + pon[i][2] + per[i][2]
        lo = math.floor(tm / 0.9 - 1e-6)
        hi = math.floor(tm / 0.9 + 1e-6)
        if not (lo <= k <= hi):
            return "frame %d (t=%.4f): %d stars spawned so far, expected %d..%d" % (f, tm, k, lo, hi)
    return True


def _first_spawn_ok(t):
    for f, tm, v in _series(t, "n_estrelas"):
        if v > 0:
            if f in (54, 55):
                return True
            return "first star seen at frame %d (expected 54, t=0.9 s)" % f
    return "no star ever spawned"


def _spawn_y_ok(t):
    seen = set()
    for f, tm, stars, *_ in _frames(t):
        for x, y in stars.items():
            if x not in seen:
                seen.add(x)
                if abs(y - SPAWN_Y) > EPS:
                    return "frame %d: new star at x=%.2f first seen at y=%.4f" % (f, x, y)
                if not (80.0 - EPS <= x <= 920.0 + EPS):
                    return "frame %d: star spawned at x=%.2f outside [80, 920]" % (f, x)
    return True if seen else "no star seen"


def _fall_ok(t):
    prev = {}
    for f, tm, stars, *_ in _frames(t):
        for x, y in stars.items():
            if x in prev and abs((prev[x] - y) - FALL) > 1e-6:
                return "frame %d: star x=%.2f fell %.5f (expected %.5f)" % (f, x, prev[x] - y, FALL)
        prev = stars
    return True


def _newest_last_ok(t):
    seen = set()
    for f, tm, v in _series(t, "estrelas"):
        xs = [x for x, _ in v]
        new = [x for x in xs if x not in seen]
        if new and xs[-len(new):] != new:
            return "frame %d: new star not at the end of group order" % f
        seen.update(xs)
    return True


def _accounting_ok(t):
    for (f, lost, caught, dp, dl, bar, bh) in _departures(t):
        if dl != len(lost):
            return "frame %d: %d stars crossed y<40 but perdidas rose by %s" % (f, len(lost), dl)
        if dp != len(caught):
            return "frame %d: %d stars left the group above y=40 but pontos rose by %s" % (f, len(caught), dp)
    return True


def _lost_after_202_ok(t):
    first = {}
    for f, tm, stars, *_ in _frames(t):
        for x in stars:
            first.setdefault(x, f)
    for (f, lost, caught, *_r) in _departures(t):
        for x, y in lost:
            life = f - first[x]
            if life != 202:
                return "frame %d: star x=%.2f lost %d frames after spawn (expected 202)" % (f, x, life)
    return True


def _caught_near_bar_ok(t):
    # Hitbox "auto" errs inward, so contact needs the drawn boxes to overlap:
    # |dx| <= 40 + 16; star bottom <= bar top, with one frame of fall as slop.
    for (f, lost, caught, dp, dl, bar, bh) in _departures(t):
        for x, y in caught:
            ny = y - FALL
            if abs(x - bar[0]) > 40.0 + 16.0 + 0.5:
                return "frame %d: star x=%.2f caught with bar at x=%.2f" % (f, x, bar[0])
            if not (LOST_Y - EPS <= ny <= bar[1] + bh / 2.0 + 16.0 + 0.5):
                return "frame %d: star caught at y=%.2f, bar h=%.2f" % (f, ny, bh)
    return True


def _centre_star_caught_ok(t):
    # A star whose x stays within 10 of the bar centre must not be lost:
    # it falls straight through the bar centre at <= 3.7 px/frame (< half its 32 size).
    bar_x = {}
    for f, tm, stars, p, l, bar, bh in _frames(t):
        bar_x[f] = bar[0]
    for (f, lost, caught, *_r) in _departures(t):
        for x, y in lost:
            # bar position over the star's last ~25 frames (from y~ 80+h to 40)
            window = [bar_x[g] for g in range(max(1, f - 25), f + 1) if g in bar_x]
            if window and all(abs(x - bx) < 10.0 for bx in window):
                return "frame %d: star x=%.2f passed the bar centre and was lost" % (f, x)
    return True


def _group_y_ok(t):
    for f, tm, stars, *_ in _frames(t):
        for x, y in stars.items():
            if y < LOST_Y - EPS:
                return "frame %d: star in group at y=%.3f < 40" % (f, y)
    return True


def _held_disp_ok(t):
    """Bar x = 500 + RUN * (frames RIGHT-only - frames LEFT-only), from key input frames."""
    bar = _series(t, "barra")
    last = bar[-1]
    # Count held frames by the per-frame bar steps instead: every step is 0 or +-RUN.
    prev = BAR0[0]
    for f, tm, (x, y) in bar:
        d = x - prev
        if not (abs(d) < 1e-6 or abs(abs(d) - RUN) < 1e-6):
            return "frame %d: bar moved %.5f (expected 0 or +-%.5f)" % (f, d, RUN)
        prev = x
    return True


def _left_steps_ok(t):
    try:
        f_press = t.input_frame("key", 0)
        f_rel = t.input_frame("key", 1)
    except Exception as e:  # noqa
        return "no key input frames: %r" % (e,)
    held = f_rel - f_press
    x_end = t.end("barra")[0]
    want = BAR0[0] - RUN * held
    if abs(x_end - want) > 1e-6:
        return "bar ended at x=%.4f; LEFT held %d frames -> %.4f" % (x_end, held, want)
    x_first = t.at_frame(f_press, "barra")[0]
    if abs(x_first - (BAR0[0] - RUN)) > 1e-6:
        return "bar x=%.4f on the press frame (expected first step there)" % x_first
    return True


def _both_ok(t):
    try:
        f0 = t.input_frame("key", 0)
        f1 = t.input_frame("key", 1)
        f2 = t.input_frame("key", 2)
        f3 = t.input_frame("key", 3)
    except Exception as e:  # noqa
        return "missing key input frames: %r" % (e,)
    xs = {f: v[0] for f, _, v in t.series("barra")}
    want_end = BAR0[0] - RUN * (f1 - f0) + RUN * (f3 - f2)
    if abs(xs[max(xs)] - want_end) > 1e-6:
        return "end x=%.4f expected %.4f" % (xs[max(xs)], want_end)
    for g in range(f1, f2):
        if g in xs and g - 1 in xs and abs(xs[g] - xs[g - 1]) > 1e-6:
            return "frame %d: bar moved while both arrows were held" % g
    return True


def _monotone(name):
    def chk(t):
        prev = -1.0
        for f, _, v in t.series(name):
            if v < prev:
                return "frame %d: %s went down %s -> %s" % (f, name, prev, v)
            prev = v
        return True
    return chk


def _star_size_ok(t):
    for f, _, v in t.series("tam_estrelas"):
        for (w, h) in v:
            if abs(max(w, h) - 32.0) > 0.01:
                return "frame %d: star size %.3f x %.3f, larger side should be 32" % (f, w, h)
    return True


def _pontos_frame_with_star_near(t):
    # every point scored happens on a frame where a star left the group above y=40
    for (f, lost, caught, dp, dl, bar, bh) in _departures(t):
        if dp > 0 and not caught:
            return "frame %d: pontos rose with no star caught" % f
    return True


# ---------------------------------------------------------------- expectations

T02 = "docs/pt/tutorial/02-pegar-estrelas.html"

EXPECT = [
    # --- startup / state ----------------------------------------------------
    Expect(id="E1", level="L0", cite="docs/pt/guide/index.html#reativo-state; " + T02 + " (Placar)",
           text="At the first frame st.pontos and st.perdidas are both 0.",
           check=all_of(at(1, "pontos", lambda v: v == 0), at(1, "perdidas", lambda v: v == 0)),
           scenarios=("*",)),
    Expect(id="E2", level="L0", cite=T02 + " (Placar: placar[\"text\"] @= ...)",
           text="The score text reads 'Estrelas 0   Perdidas 0' on the first frame.",
           check=at(1, "placar", lambda v: v == "Estrelas 0   Perdidas 0"),
           scenarios=("*",)),
    Expect(id="E3", level="L0", cite="design/Scena Design.md#frame-order (step 6 flush after update/timers/collision); " + T02 + " (Placar)",
           text="Every sample, the score text equals the formula of the current st.pontos / st.perdidas (the @= link is flushed in the same frame).",
           check=custom(_placar_ok), scenarios=("*",)),
    Expect(id="E4", level="L0", cite="docs/pt/guide/index.html#grp-entrar",
           text="The bar is the single member of group 'heroi' for the whole run (pop never removes it).",
           check=all_of(always("heroi_n", lambda v: v == 1), always("barra_no_heroi", lambda v: bool(v))),
           scenarios=("*",)),
    Expect(id="E5", level="L1", cite="docs/pt/guide/index.html#desenhar-sprite (width= in design units)",
           text="The bar is 80 design units wide and stays 80 (pop is drawing only).",
           check=always("barra_w", lambda v: abs(v - 80.0) < 1e-6), scenarios=("*",)),
    Expect(id="E6", level="L1", cite="docs/pt/guide/index.html#desenhar-sprite (size = larger side)",
           text="Every star has its larger side equal to 32 design units.",
           check=custom(_star_size_ok), scenarios=("parado", "centro")),
    Expect(id="E7", level="L0", cite="docs/pt/guide/index.html#agendar-timers (@every in module starts now; time is game time)",
           text="No star exists before t = 0.9 s (frames 1..53).",
           check=always("n_estrelas", lambda v: v == 0, until=53), scenarios=("*",)),
    Expect(id="E8", level="L0", cite="docs/pt/guide/index.html#agendar-timers",
           text="The first star appears at t = 0.9 s, i.e. frame 54 (frame 55 tolerated for float rounding of 54/60).",
           check=custom(_first_spawn_ok), scenarios=("parado", "centro", "direita")),
    Expect(id="E9", level="L0", cite="docs/pt/guide/index.html#agendar-timers (every repeats each interval)",
           text="Stars spawned so far (in group + caught + lost) equals floor(t / 0.9) at every sample (both values allowed at exact multiples).",
           check=custom(_spawn_count_ok), scenarios=("*",)),
    Expect(id="E10", level="L1", cite="design/Scena Design.md#frame-order (timers run after update); " + T02 + " (De tempos em tempos)",
           text="A new star is first sampled at y = 780 exactly (spawned after update, not yet moved) with x in [80, 920].",
           check=custom(_spawn_y_ok), scenarios=("parado", "centro", "direita")),
    Expect(id="E11", level="L0", cite="docs/pt/guide/index.html#grp-ler (order = entry order)",
           text="A newly spawned star is the last member of group['estrelas'].",
           check=custom(_newest_last_ok), scenarios=("parado", "centro")),
    Expect(id="E12", level="L1", cite=T02 + " (Uma estrela caindo: move_by(0, -220*dt)); docs/pt/guide/index.html#frame-clock",
           text="Each star in the group falls exactly 220/60 units per frame and keeps its x.",
           check=custom(_fall_ok), scenarios=("parado", "centro", "direita")),
    # --- losing ---------------------------------------------------------------
    Expect(id="E13", level="L0", cite=T02 + " (Efeitos: untag tira do grupo; o if não chama perdeu de novo)",
           text="No star in group 'estrelas' is ever sampled below y = 40 (perdeu untags it in the same update).",
           check=custom(_group_y_ok), scenarios=("*",)),
    Expect(id="E14", level="L0", cite=T02 + " (Efeitos)",
           text="perdidas rises exactly by the number of stars that left the group by crossing y < 40 that frame, and pontos by the number that left above it.",
           check=custom(_accounting_ok), scenarios=("*",)),
    Expect(id="E15", level="L1", cite=T02 + " (Efeitos: y < 40); arithmetic (780 - 202*220/60 = 39.33 < 40 <= 43.0)",
           text="An uncaught star is counted lost exactly 202 frames after the frame it was first sampled.",
           check=custom(_lost_after_202_ok), scenarios=("parado", "centro")),
    Expect(id="E16", level="L0", cite=T02 + " (Efeitos: o if não dispara de novo)",
           text="st.perdidas never decreases (a lost star is untagged, so it is never re-counted; the exact count is E14).",
           check=custom(_monotone("perdidas")), scenarios=("*",)),
    Expect(id="E17", level="L0", cite=T02 + " (Colisão / Placar)",
           text="st.pontos never decreases.",
           check=custom(_monotone("pontos")), scenarios=("*",)),
    Expect(id="E18", level="L0", cite="arithmetic from E8/E15; " + T02,
           text="With nothing pressed (seed 0), the first star (x far from the bar per seed) is lost: perdidas >= 1 by frame 258.",
           check=at(258, "perdidas", lambda v: v >= 1),
           scenarios=("parado",), guess=True),
    # --- catching -------------------------------------------------------------
    Expect(id="E19", level="L2", cite="docs/pt/guide/index.html#spr-hit (auto errs inward); #colisao-collide (enter = first overlap frame)",
           text="A caught star is within |dx| <= 56.5 of the bar centre and its y is between 40 and bar top + 16 + 0.5 (overlap of drawn boxes, one frame of fall as slop).",
           check=custom(_caught_near_bar_ok), scenarios=("*",)),
    Expect(id="E20", level="L2", cite="docs/pt/guide/index.html#colisao-collide, #colisao-rapido (3.7 px/frame < half thickness, no tunnelling)",
           text="A star that falls with x within 10 of the bar centre during its last 25 frames is never lost (it overlaps the bar centre first).",
           check=custom(_centre_star_caught_ok), scenarios=("*",)),
    Expect(id="E21", level="L0", cite=T02 + " (Colisão: pegou roda uma vez, no começo do toque; destroy tira do grupo)",
           text="Every point is scored on a frame where a star left the group above y = 40 (pontos only rises on a catch).",
           check=custom(_pontos_frame_with_star_near), scenarios=("*",)),
    Expect(id="E22", level="L0", cite=T02 + " (Colisão); seed arithmetic",
           text="Seed 50: the first star (x ~ 497.9) lands on the idle bar: pontos == 1 by frame 260 and perdidas is still 0 then.",
           check=all_of(at(260, "pontos", lambda v: v == 1),
                        at(260, "perdidas", lambda v: v == 0)),
           scenarios=("centro",), guess=True),
    Expect(id="E23", level="L0", cite=T02 + " (Colisão); seed arithmetic",
           text="Seed 0 with RIGHT held 46 frames: the bar ends near x 791 under the first star (x ~ 789): pontos >= 1 by frame 260.",
           check=at(260, "pontos", lambda v: v >= 1),
           scenarios=("direita",), guess=True),
    Expect(id="E24", level="L1", cite=T02 + " (Efeitos: pop é só desenho; a barra não muda de tamanho para a colisão); #aparencia-transientes",
           text="The bar's hitbox width stays constant through the run, including frames after a catch (pop).",
           check=steady("barra_hit_w", tol=1e-6), scenarios=("centro", "direita", "parado")),
    # --- bar movement ---------------------------------------------------------
    Expect(id="E25", level="L0", cite=T02 + " (A barra)",
           text="With nothing pressed the bar stays at (500, 80).",
           check=always("barra", lambda v: close(v, BAR0, 1e-6)),
           scenarios=("parado", "centro")),
    Expect(id="E26", level="L0", cite=T02 + " (A barra: só anda de lado)",
           text="The bar's y stays 80 in every scenario.",
           check=always("barra", lambda v: abs(v[1] - 80.0) < 1e-6), scenarios=("*",)),
    Expect(id="E27", level="L1", cite="docs/pt/guide/index.html#frame-teclado; " + T02 + " (A barra: 380 por segundo)",
           text="Each frame the bar moves 0 or exactly 380/60 units in x.",
           check=custom(_held_disp_ok), scenarios=MOVE_SCEN),
    Expect(id="E28", level="L1", cite="design/Scena Design.md#frame-order (input then update); docs/pt/guide/index.html#frame-teclado",
           text="LEFT: the bar takes its first step on the press-delivery frame and ends at 500 - 380/60 * (release frame - press frame).",
           check=custom(_left_steps_ok), scenarios=("esquerda", "longe")),
    Expect(id="E29", level="L1", cite="harness key(frames=30); " + T02 + " (A barra)",
           text="After LEFT held 30 frames the bar rests at x = 310.",
           check=at_end("barra", lambda v: close(v, (310.0, 80.0), 1e-6)), scenarios=("esquerda",)),
    Expect(id="E30", level="L1", cite="harness key(frames=46); " + T02 + " (A barra)",
           text="After RIGHT held 46 frames the bar rests at x = 500 + 46*380/60 ~ 791.33.",
           check=at_end("barra", lambda v: close(v, (500.0 + 46 * RUN, 80.0), 1e-6)), scenarios=("direita",)),
    Expect(id="E31", level="L1", cite="docs/pt/guide/index.html#frame-teclado (keyp: held, no modifiers); program update()",
           text="With LEFT and RIGHT both held the steps cancel; the end x is 500 - RUN*(LEFT-only frames) + RUN*(RIGHT-only frames).",
           check=custom(_both_ok), scenarios=("ambas",)),
    Expect(id="E32", level="L0", cite="examples/pegar_estrelas.py (no confine / clamp on the bar); " + T02 + " (A barra)",
           text="Nothing confines the bar: LEFT held 90 frames takes it to x = -70, off the window.",
           check=at_end("barra", lambda v: close(v, (500.0 - 90 * RUN, 80.0), 1e-6)), scenarios=("longe",)),
]
