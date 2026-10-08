"""Spec A for examples/cadeia_de_bolas.py (tutorial 04, "Cadeia de bolas").

Written from the documentation only (Guia, tutorial 04, the program itself).
"""

from program_support import (Scenario, Expect, wait, wait_s, click_widget, click,
    key, key_down, key_up, move, scroll, set_cell, always, never, at, at_end,
    eventually, steady, all_of, custom, close)
import math
import weakref

from program_support import serial as _serial  # per-run identity (revised: SPEC-LOGIC, id reuse)


def _look(v):
    # Revised (SPEC-ERROR / INTUITION): an exported look may be built by a
    # subclass (Halo(style="pulse") is a HaloPulse); the author-level fact is
    # isinstance, so name the first exported class in the look's MRO.
    import scena
    for c in type(v).__mro__:
        if getattr(scena, c.__name__, None) is c:
            return c.__name__
    return type(v).__name__

FILES_READ = [
    "examples/cadeia_de_bolas.py",
    "docs/pt/tutorial/04-ui-widgets.html",
    "docs/pt/guide/index.html#util-chase",
    "docs/pt/guide/index.html#frame-mouse",
    "docs/pt/guide/index.html#frame-clock",
    "docs/pt/guide/index.html#frame-teclado",
    "docs/pt/guide/index.html#mundo-grupos",
    "docs/pt/guide/index.html#ui-widgets",
    "docs/pt/guide/index.html#ui-button",
    "docs/pt/guide/index.html#ui-slider",
    "docs/pt/guide/index.html#ui-checkbox",
    "docs/pt/guide/index.html#ui-dropdown",
    "docs/pt/guide/index.html#ui-menu",
    "docs/pt/guide/index.html (Fórmulas nos construtores: callable liga, resto copia, ~l.1839)",
    "docs/pt/guide/index.html (Line .p1/.p2 ~l.2526; .blend ~l.2182; Color.darker ~l.4617)",
]

CENTER = (500.0, 350.0)       # canvas.game_view.center for init(1000, 700)
RATE = 8.0
EPS = 1e-3


def _k(dt):
    """chase factor: lerp(current, target, 1 - exp(-rate*dt))  (Guia #util-chase)."""
    return 1.0 - math.exp(-RATE * dt)


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


# ---------------------------------------------------------------- probes ---
def _centers(p):
    return tuple((b.center.x, b.center.y) for b in p.group["bolas"])


def _lines(p):
    return tuple(((l.p1.x, l.p1.y), (l.p2.x, l.p2.y)) for l in p.group["linhas"])


PROBES = {
    "n": lambda p: p.group["bolas"].count,
    "nl": lambda p: p.group["linhas"].count,
    "centers": _centers,
    "head": lambda p: p.group["bolas"][0].center,
    "tail": lambda p: p.group["bolas"][-1].center,
    # Revised (SPEC-LOGIC): id() is not stable across runs (replay / twin
    # oracles compare it) and is reused after a free; a per-object serial is both.
    "gen": lambda p: float(_serial(p.group["bolas"][0])),
    "mouse": lambda p: (p.mouse.x, p.mouse.y),
    "time": lambda p: p.clock.time,
    "paused": lambda p: bool(p.clock.paused),
    "st_n": lambda p: p.st.n_bolas,
    # Revised (SPEC-ERROR / DOC-AMBIG): st.n_bolas reads the cell (Attribute);
    # the Guia contradicted itself ("lê o valor" vs "Lê o Attribute"), fixed in PM4.
    "st_n_is_int": lambda p: isinstance(p.st.n_bolas.value, int),
    "st_linhas": lambda p: bool(p.st.linhas),
    "st_efeito": lambda p: str(p.st.efeito),
    "visuals": lambda p: tuple(_look(b.visual) for b in p.group["bolas"]),
    "radii": lambda p: tuple(b.radius for b in p.group["bolas"]),
    "lines": _lines,
    "blends": lambda p: tuple(str(l.blend) for l in p.group["linhas"]),
}


# ------------------------------------------------------------- scenarios ---
SCENARIOS = {
    # nothing pressed, mouse never moved by the harness
    "idle": Scenario(seed=0, steps=[wait(120)]),
    # pointer parked up-right of the centre; the chain stretches and settles
    "mouse": Scenario(seed=0, steps=[move(800, 600), wait(540)]),
    # slider value written as a cell, then the Rodar button rebuilds the chain
    "rebuild_10": Scenario(seed=0, steps=[
        move(800, 600), wait(60),
        set_cell("st.n_bolas", 10), wait(5),
        click_widget("Rodar"), wait(30),
    ]),
    # the CheckBox widget, then Rodar
    "no_lines": Scenario(seed=0, steps=[
        wait(10), click_widget("Linhas"), wait(10),
        click_widget("Rodar"), wait(20),
    ]),
    # DropDown has no label to click: write its cell, then Rodar
    "flame": Scenario(seed=0, steps=[
        wait(10), set_cell("st.efeito", "Flame"), wait(10),
        click_widget("Rodar"), wait(20),
    ]),
    # the Slider widget itself, then Rodar
    "slider": Scenario(seed=0, steps=[
        wait(10), click_widget("Bolas"), wait(10),
        click_widget("Rodar"), wait(20),
    ]),
    # ESC opens the pause Menu; a second ESC while it is open does nothing
    "pause": Scenario(seed=0, steps=[
        move(800, 600), wait(30),
        key("ESC"), wait(30),
        key("ESC"), wait(30),
    ]),
    "menu_recomecar": Scenario(seed=0, steps=[
        move(800, 600), wait(60),
        key("ESC"), wait(10),
        click_widget("Recomeçar"), wait(30),
    ]),
    "menu_continuar": Scenario(seed=0, steps=[
        move(800, 600), wait(60),
        key("ESC"), wait(10),
        click_widget("Continuar"), wait(30),
    ]),
}


# ------------------------------------------------------- custom checks ---
def _aligned(t, *names):
    """[(frame, time, {name: value})] for each sample."""
    cols = [t.series(n) for n in names]
    out = []
    for row in zip(*cols):
        f, tm = row[0][0], row[0][1]
        out.append((f, tm, {n: r[2] for n, r in zip(names, row)}))
    return out


def _chain_recurrence(t):
    """Head chases the mouse, ball i chases ball i-1 (already moved this frame)."""
    rows = _aligned(t, "centers", "mouse", "time", "gen", "paused")
    checked = 0
    for (f0, _, a), (f1, _, b) in zip(rows, rows[1:]):
        if a["gen"] != b["gen"] or len(a["centers"]) != len(b["centers"]):
            continue                      # chain rebuilt between these samples
        if a["paused"] != b["paused"]:
            continue                      # pause edge: which dt applies is unsettled
        k = _k(b["time"] - a["time"])
        prev, new, m = a["centers"], b["centers"], b["mouse"]
        target = m
        for i, (old, got) in enumerate(zip(prev, new)):
            want = (old[0] + (target[0] - old[0]) * k, old[1] + (target[1] - old[1]) * k)
            if _dist(want, got) > EPS:
                return "frame %d ball %d: expected %r got %r" % (f1, i, want, got)
            target = got
        checked += 1
    return True if checked else "no frame pairs checked"


def _lines_follow(t):
    rows = _aligned(t, "centers", "lines")
    for f, _, v in rows:
        c, ls = v["centers"], v["lines"]
        if not ls:
            continue
        if len(ls) != len(c) - 1:
            return "frame %d: %d lines for %d balls" % (f, len(ls), len(c))
        for j, (p1, p2) in enumerate(ls):
            if _dist(p1, c[j]) > EPS or _dist(p2, c[j + 1]) > EPS:
                return "frame %d line %d: %r,%r vs %r,%r" % (f, j, p1, p2, c[j], c[j + 1])
    return True


def _clock_tracks_frames(t):
    for f, tm, _ in t.series("time"):
        if abs(tm - f / 60.0) > 1e-6:
            return "frame %d time %r" % (f, tm)
    return True


def _monotone_chain(t):
    """Mouse up-right of a chain born at the centre: every ball stays between the
    centre and the ball ahead, never past the mouse (chase never overshoots)."""
    f0 = t.input_frame("move", 0)
    for f, _, c in t.series("centers"):
        if f < f0:
            continue
        ahead = (800.0, 600.0)
        for i, (x, y) in enumerate(c):
            if not (CENTER[0] - EPS <= x <= ahead[0] + EPS
                    and CENTER[1] - EPS <= y <= ahead[1] + EPS):
                return "frame %d ball %d at %r (ahead %r)" % (f, i, (x, y), ahead)
            ahead = (x, y)
    return True


def _esc(t):
    return t.input_frame("key", 0)


def _frozen_after_esc(probe):
    def fn(t):
        f0 = _esc(t) + 1
        ser = [(f, v) for f, _, v in t.series(probe) if f >= f0]
        ref = ser[0][1]
        for f, v in ser:
            if v != ref and not (isinstance(v, float) and abs(v - ref) < 1e-9):
                return "%s changed at frame %d while paused" % (probe, f)
        return True
    return fn


def _choice_release(t):
    return t.input_frame("button", 1)


def _gen_changes_after_release(t):
    r = _choice_release(t)
    before = t.at_frame(_esc(t), "gen")
    after = t.at_frame(r + 1, "gen")
    return True if before != after else "chain was not rebuilt"


def _gen_constant(t):
    vals = set(t.values("gen"))
    return True if len(vals) == 1 else "chain rebuilt %d times" % (len(vals) - 1)


def _time_resumes(t):
    r = _choice_release(t)
    return True if t.end("time") > t.at_frame(r + 1, "time") else "clock did not resume"


def _paused_between_esc_and_choice(t):
    a, b = _esc(t) + 1, t.input_frame("button", 0)
    for f, _, v in t.series("paused"):
        if a <= f < b and not v:
            return "not paused at frame %d" % f
    return True


def _slider_rebuild(t):
    n = t.end("st_n")
    if not (5 <= n <= 60):
        return "st.n_bolas %r out of range" % n
    return True if t.end("n") == n else "count %r != st.n_bolas %r" % (t.end("n"), n)


def _rodar_press(t):
    """Rodar is the last click_widget of each panel scenario (press, release)."""
    n = 0
    while n < 20:
        try:
            nxt = t.input_frame("button", n + 2)
        except Exception:
            break
        if nxt is None:
            break
        n += 2
    return t.input_frame("button", n)


def _rodar_release(t):
    return _rodar_press(t) + 1


def _rodar_rebuilds(t):
    before = t.at_frame(_rodar_press(t) - 1, "gen")
    after = t.at_frame(_rodar_release(t) + 2, "gen")
    return True if before != after else "not rebuilt"


def _after_move_mouse_fixed(t):
    f0 = t.input_frame("move", 0)
    for f, _, v in t.series("mouse"):
        if f >= f0 and not close(v, (800.0, 600.0), 1e-6):
            return "frame %d mouse %r" % (f, v)
    return True


def _paused_after_esc(t):
    f0 = _esc(t) + 1
    for f, _, v in t.series("paused"):
        if f >= f0 and v is not True:
            return "not paused at frame %d" % f
    return True


# ----------------------------------------------------------- expectations ---
TUT = "docs/pt/tutorial/04-ui-widgets.html"
G = "docs/pt/guide/index.html"

EXPECT = [
    # --- startup ---------------------------------------------------------
    Expect(id="E1", level="L0", cite=TUT + " (A cadeia: criar faz trinta círculos)",
           text="Startup creates 30 balls in group 'bolas'.",
           check=at(1, "n", lambda v: v == 30), scenarios=("idle",)),
    Expect(id="E2", level="L0", cite=TUT + " (Linhas: trinta bolas, vinte e nove linhas)",
           text="Startup creates 29 lines in group 'linhas'.",
           check=at(1, "nl", lambda v: v == 29), scenarios=("idle",)),
    Expect(id="E3", level="L0", cite=G + "#ui-widgets (widget sem initial= não grava)",
           text="Panel cells keep the script's values: n_bolas 30, linhas True, efeito 'Halo'.",
           check=all_of(at(1, "st_n", lambda v: v == 30),
                        at(1, "st_linhas", lambda v: v is True),
                        at(1, "st_efeito", lambda v: v == "Halo")),
           scenarios=("idle",)),
    Expect(id="E4", revised="INTUITION: compared the look's class name; HaloPulse is a Halo (isinstance)", level="L0", cite=TUT + " (DropDown: se nenhum bater, devolve o Halo)",
           text="Every ball's visual is a Halo at startup.",
           check=at(1, "visuals", lambda v: len(v) == 30 and all(x == "Halo" for x in v)),
           scenarios=("idle",)),
    Expect(id="E5", level="L0", cite="examples/cadeia_de_bolas.py (Circle radius=16)",
           text="Every ball has radius 16 and keeps it.",
           check=always("radii", lambda v: all(abs(r - 16) < 1e-9 for r in v)),
           scenarios=("*",)),
    Expect(id="E6", level="L0", cite=G + " (.blend ~l.2182) + " + TUT + " (Linhas: blend = 'add')",
           text="Every line uses blend 'add'.",
           check=always("blends", lambda v: all(b == "add" for b in v)),
           scenarios=("idle", "mouse", "pause")),
    Expect(id="E7", level="L0", cite=G + "#mundo-grupos (contar)",
           text="With no input the ball count stays 30 and line count 29 every frame.",
           check=all_of(always("n", lambda v: v == 30), always("nl", lambda v: v == 29)),
           scenarios=("idle", "mouse", "pause")),
    Expect(id="E8", level="L1", cite=TUT + " (A cadeia: centro da vista) + " + G + " (callable liga, resto copia)",
           text="Balls are born at the view centre (500, 350); at frame 1 the tail has not "
                "measurably moved (tail displacement is k^30 of the head's).",
           check=at(1, "tail", lambda v: close(v, CENTER, 1e-3)),
           scenarios=("idle", "mouse", "pause")),
    Expect(id="E9", level="L0", cite=G + "#frame-clock",
           text="clock.time advances by dt=1/60 per frame when nothing pauses it.",
           check=custom(_clock_tracks_frames), scenarios=("idle", "mouse")),
    Expect(id="E10", level="L0", cite=G + "#frame-clock",
           text="The clock is never paused when ESC is not pressed.",
           check=always("paused", lambda v: v is False),
           scenarios=("idle", "mouse", "rebuild_10", "no_lines", "flame", "slider")),

    # --- motion ----------------------------------------------------------
    Expect(id="E11", level="L1", cite=G + "#util-chase (lerp(current, target, 1-exp(-rate*dt)))",
           text="Each frame the head moves to lerp(head, mouse, 1-exp(-8 dt)) per axis and ball i "
                "to lerp(ball_i, ball_{i-1} as already moved this frame, same k); tol 1e-3.",
           check=custom(_chain_recurrence), scenarios=("*",)),
    Expect(id="E12", level="L1", cite=G + "#frame-mouse + harness",
           text="After move(800, 600) the probed mouse reads (800, 600) for the rest of the run.",
           check=custom(_after_move_mouse_fixed),
           scenarios=("mouse",)),
    Expect(id="E13", level="L1", cite=G + "#util-chase (rate=6: ~95% em 0,5 s)",
           text="The head reaches within 1 unit of a fixed mouse at (800, 600) within 60 frames "
                "(distance 360 * exp(-8 t) < 1 for t > 0.74 s; allowance 1 s).",
           check=eventually("head", lambda v: _dist(v, (800, 600)) < 1.0, within=60),
           scenarios=("mouse",)),
    Expect(id="E14", level="L1", cite=G + "#util-chase + " + TUT + " (atraso em fila)",
           text="After ~9 s the whole chain (30 cascaded lags, rate 8) sits within 1 unit of the mouse.",
           check=at_end("tail", lambda v: _dist(v, (800, 600)) < 1.0),
           scenarios=("mouse",)),
    Expect(id="E15", level="L2", cite=G + "#util-chase (sem passar do alvo)",
           text="With the chain born at the centre and the mouse fixed up-right, every ball stays "
                "between the centre and the ball ahead of it (no overshoot, order preserved); slop 1e-3.",
           check=custom(_monotone_chain), scenarios=("mouse",)),
    Expect(id="E16", level="L1", cite=TUT + " (Linhas: as pontas andam junto) + " + G + " (line['p1'] @= rect.top_left)",
           text="Each line j's p1/p2 equal the centres of balls j and j+1 at every frame; tol 1e-3.",
           check=custom(_lines_follow), scenarios=("*",)),

    # --- panel: slider cell + Rodar --------------------------------------
    Expect(id="E17", level="L0", cite=TUT + " (Neste script, slider, lista e caixa só gravam valores em st)",
           text="Writing st.n_bolas does not change the chain until Rodar is clicked.",
           check=at(lambda t: t.input_frame("button", 0), "n", lambda v: v == 30),
           scenarios=("rebuild_10",)),
    Expect(id="E18", level="L0", cite=TUT + " (Botão Rodar: a cadeia renasce no centro, com dez bolas)",
           text="After Rodar with n_bolas=10 there are exactly 10 balls and 9 lines (old ones destroyed).",
           check=all_of(at_end("n", lambda v: v == 10), at_end("nl", lambda v: v == 9)),
           scenarios=("rebuild_10",)),
    Expect(id="E19", level="L0", cite=G + "#ui-button (no soltar) + " + G + "#mundo-grupos (destroy sai na hora)",
           text="Rodar rebuilds the chain: the first ball after the Rodar release is a new object.",
           check=custom(_rodar_rebuilds), scenarios=("rebuild_10", "no_lines", "flame", "slider")),
    Expect(id="E20", level="L1", cite=TUT + " (Botão Rodar: a cadeia renasce no centro)",
           text="Two frames after the Rodar release the new tail is still within 5 units of the centre.",
           check=at(lambda t: _rodar_release(t) + 2, "tail",
                    lambda v: _dist(v, CENTER) < 5.0),
           scenarios=("rebuild_10", "no_lines", "flame")),

    # --- CheckBox ----------------------------------------------------------
    Expect(id="E21", level="L0", cite=G + "#ui-checkbox (clicar inverte o valor)",
           text="Clicking the 'Linhas' CheckBox sets st.linhas to False; lines remain until Rodar.",
           check=all_of(at(lambda t: t.input_frame("button", 1) + 1, "st_linhas", lambda v: v is False),
                        at(lambda t: t.input_frame("button", 2), "nl", lambda v: v == 29)),
           scenarios=("no_lines",)),
    Expect(id="E22", level="L0", cite=TUT + " (CheckBox: a cadeia renasce sem linhas)",
           text="After Rodar with linhas False: 30 balls and 0 lines.",
           check=all_of(at_end("n", lambda v: v == 30), at_end("nl", lambda v: v == 0)),
           scenarios=("no_lines",)),

    # --- DropDown ----------------------------------------------------------
    Expect(id="E23", revised="INTUITION: compared the look's class name; HaloPulse is a Halo (isinstance)", level="L0", cite=TUT + " (DropDown: a lista só grava o valor)",
           text="Writing st.efeito='Flame' leaves the balls' visuals as Halo until Rodar.",
           check=at(lambda t: t.input_frame("button", 0), "visuals",
                    lambda v: all(x == "Halo" for x in v)),
           scenarios=("flame",)),
    Expect(id="E24", level="L0", cite=TUT + " (DropDown: Escolha Flame e aperte Rodar)",
           text="After Rodar every ball's visual is a Flame.",
           check=at_end("visuals", lambda v: len(v) == 30 and all(x == "Flame" for x in v)),
           scenarios=("flame",)),

    # --- Slider widget -----------------------------------------------------
    Expect(id="E25", revised="DOC-AMBIG: st.n reads the cell; the Guia said both 'lê o valor' and 'Lê o Attribute' (PM4)", level="L0", cite=G + "#ui-slider (only_int: de inteiro em inteiro)",
           text="Clicking the 'Bolas' slider writes an int within [5, 60]; Rodar then builds that many balls "
                "(assumed: a click on the bar sets the value at the click point).",
           check=all_of(at_end("st_n_is_int", lambda v: v is True), custom(_slider_rebuild)),
           scenarios=("slider",), guess=True),

    # --- pause menu ----------------------------------------------------------
    Expect(id="E26", level="L0", cite=G + "#ui-menu (pause=True pausa o jogo (clock.paused))",
           text="From the frame after ESC is delivered the clock is paused until the end "
                "(a second ESC while the modal menu is open neither closes it nor raises).",
           check=custom(_paused_after_esc),
           scenarios=("pause",)),
    Expect(id="E27", level="L1", cite=G + "#frame-clock (pausado, dt é 0)",
           text="While paused clock.time does not advance.",
           check=custom(_frozen_after_esc("time")), scenarios=("pause",)),
    Expect(id="E28", level="L1", cite=TUT + " (Menu de pausa: as bolas congelam) + " + G + "#util-chase (dt == 0 devolve current)",
           text="While paused every ball stays exactly where it was.",
           check=custom(_frozen_after_esc("centers")), scenarios=("pause",)),
    Expect(id="E29", level="L0", cite=G + "#ui-menu (Teclas: com modal, keyp lê falso)",
           text="The chain is not rebuilt and keeps 30 balls while the menu is open.",
           check=all_of(custom(_gen_constant), always("n", lambda v: v == 30)),
           scenarios=("pause",)),
    Expect(id="E30", level="L0", cite=G + "#ui-menu",
           text="Between ESC and the click on an option the clock stays paused.",
           check=custom(_paused_between_esc_and_choice),
           scenarios=("menu_recomecar", "menu_continuar")),
    Expect(id="E31", level="L0", cite=G + "#ui-menu (Ao escolher: fecha, devolve a pausa)",
           text="After choosing an option the clock is unpaused (assumed: click_widget reaches Menu options).",
           check=at_end("paused", lambda v: v is False),
           scenarios=("menu_recomecar", "menu_continuar"), guess=True),
    Expect(id="E32", level="L0", cite=TUT + " (Menu de pausa: escolher trata Recomeçar chamando criar)",
           text="Choosing 'Recomeçar' rebuilds the chain (new first ball) with 30 balls and 29 lines.",
           check=all_of(custom(_gen_changes_after_release),
                        at_end("n", lambda v: v == 30), at_end("nl", lambda v: v == 29)),
           scenarios=("menu_recomecar",), guess=True),
    Expect(id="E33", level="L1", cite=TUT + " (a cadeia nasce de novo, inteira) + " + G + "#ui-menu",
           text="Two frames after choosing 'Recomeçar' the new tail is within 5 units of the centre.",
           check=at(lambda t: t.input_frame("button", 1) + 2, "tail",
                    lambda v: _dist(v, CENTER) < 5.0),
           scenarios=("menu_recomecar",), guess=True),
    Expect(id="E34", level="L0", cite=TUT + " (Continuar não precisa de nada: fechar já é continuar)",
           text="Choosing 'Continuar' keeps the same chain (never rebuilt) and the clock resumes.",
           check=all_of(custom(_gen_constant), custom(_time_resumes)),
           scenarios=("menu_continuar",), guess=True),
]
