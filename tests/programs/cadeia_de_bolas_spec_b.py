"""Spec B for examples/cadeia_de_bolas.py (tutorial 04), written from the docs only."""

from program_support import (Scenario, Expect, wait, wait_s, click_widget, click,
    key, key_down, key_up, move, scroll, set_cell, always, never, at, at_end,
    eventually, steady, all_of, custom, close)
import math


def _look(v):
    # Revised (SPEC-ERROR / INTUITION): an exported look may be built by a
    # subclass (Halo(style="pulse") is a HaloPulse); the author-level fact is
    # isinstance, so name the first exported class in the look's MRO.
    import scena
    for c in type(v).__mro__:
        if getattr(scena, c.__name__, None) is c:
            return c.__name__
    return type(v).__name__


import weakref
from program_support import serial as _serial  # per-run identity (revised: SPEC-LOGIC, id reuse)

FILES_READ = [
    "examples/cadeia_de_bolas.py",
    "docs/pt/tutorial/04-ui-widgets.html",
    "docs/pt/guide/index.html#util-chase",
    "docs/pt/guide/index.html#ui-button",
    "docs/pt/guide/index.html#ui-slider",
    "docs/pt/guide/index.html#ui-checkbox",
    "docs/pt/guide/index.html#ui-dropdown",
    "docs/pt/guide/index.html#ui-menu",
    "docs/pt/guide/index.html#shape-line",
    "docs/pt/guide/index.html (Neste Shape: .blend, .layer)",
    "docs/pt/guide/index.html (Grupos: order, destroy, count)",
    "docs/pt/guide/index.html (clock: dt, time, paused)",
    "docs/pt/guide/index.html#frame-mouse",
    "docs/pt/guide/index.html (Neste Color: .hsl, darker)",
    "docs/pt/guide/index.html (canvas.game_view)",
]

RATE = 8.0
CENTER = (500.0, 350.0)   # game_view.center of init(width=1000, height=700)
TOL = 1e-4


def _bolas(p):
    return p.group["bolas"]


def _linhas(p):
    return p.group["linhas"]


PROBES = {
    "n_cell": lambda p: p.st.n_bolas,
    "linhas_cell": lambda p: p.st.linhas,
    "efeito_cell": lambda p: p.st.efeito,
    "n_bolas": lambda p: _bolas(p).count,
    "n_linhas": lambda p: _linhas(p).count,
    "pos": lambda p: tuple(b.center for b in _bolas(p)),
    "ids": lambda p: tuple(_serial(b) for b in _bolas(p)),
    "radii": lambda p: tuple(b.radius for b in _bolas(p)),
    "visuals": lambda p: tuple(_look(b.visual) for b in _bolas(p)),
    "light": lambda p: tuple(b.color.hsl[2] for b in _bolas(p)),
    "line_ends": lambda p: tuple((l.p1, l.p2) for l in _linhas(p)),
    "line_layers": lambda p: tuple(l.layer for l in _linhas(p)),
    "line_blends": lambda p: tuple(l.blend for l in _linhas(p)),
    "mouse": lambda p: (p.mouse.x, p.mouse.y),
    "paused": lambda p: p.clock.paused,
    "time": lambda p: p.clock.time,
    "view_center": lambda p: p.canvas.game_view.center,
}


SCENARIOS = {
    "idle": Scenario(params={}, seed=0, steps=[wait(120)]),
    "follow": Scenario(params={}, seed=0, steps=[
        move(800, 500), wait(150), move(200, 150), wait(150)]),
    "rebuild_n": Scenario(params={}, seed=0, steps=[
        move(700, 400), wait(20), set_cell("st.n_bolas", 10), wait(5),
        click_widget("Rodar"), wait(60)]),
    "linhas_off": Scenario(params={}, seed=0, steps=[
        wait(10), click_widget("Linhas"), wait(5), click_widget("Rodar"), wait(30)]),
    "efeito": Scenario(params={}, seed=0, steps=[
        set_cell("st.efeito", "Flame"), wait(3), click_widget("Rodar"), wait(10),
        set_cell("st.efeito", "Gel"), click_widget("Rodar"), wait(10)]),
    "pause": Scenario(params={}, seed=0, steps=[
        move(800, 500), wait(30), key("ESC"), wait(30), key("ESC"), wait(20),
        click_widget("Continuar"), wait(30)]),
    "restart": Scenario(params={}, seed=0, steps=[
        move(800, 500), wait(60), key("ESC"), wait(10),
        click_widget("Recomeçar"), wait(30)]),
    "slider_click": Scenario(params={}, seed=0, steps=[
        wait(5), click_widget("Bolas"), wait(5), click_widget("Rodar"), wait(10)]),
    "out_of_range": Scenario(params={}, seed=0, steps=[
        set_cell("st.n_bolas", 3), wait(2), click_widget("Rodar"), wait(20)]),
}

LINE_SCENARIOS = ("idle", "follow", "rebuild_n", "efeito", "pause", "restart",
                  "slider_click", "out_of_range")


# ---------------------------------------------------------------- helpers
def _d(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _rows(t, *names):
    """[(frame, time, {name: value})] for the given probes."""
    cols = {n: t.series(n) for n in names}
    out = []
    for i, (frame, tm, _) in enumerate(cols[names[0]]):
        out.append((frame, tm, {n: cols[n][i][2] for n in names}))
    return out


def _chain_step(prev, mouse, dt):
    """One update(): head chases the mouse, each ball chases the (already moved) one ahead."""
    k = 1.0 - math.exp(-RATE * dt)
    new = []
    for i, (x, y) in enumerate(prev):
        tx, ty = mouse if i == 0 else new[i - 1]
        new.append((x + (tx - x) * k, y + (ty - y) * k))
    return new


def _recurrence(t):
    rows = _rows(t, "pos", "ids", "mouse")
    for (f0, t0, a), (f1, t1, b) in zip(rows, rows[1:]):
        if a["ids"] != b["ids"]:
            continue            # chain rebuilt this frame
        exp = _chain_step(a["pos"], b["mouse"], t1 - t0)
        for i, (e, g) in enumerate(zip(exp, b["pos"])):
            if _d(e, g) > TOL * max(1.0, _d(a["pos"][i], b["mouse"])):
                return "frame %d ball %d: expected %r got %r" % (f1, i, e, g)
    return True


def _frame1_from_center(t):
    f, tm, v = _rows(t, "pos", "mouse")[0]
    exp = _chain_step([CENTER] * len(v["pos"]), v["mouse"], tm)
    for i, (e, g) in enumerate(zip(exp, v["pos"])):
        if _d(e, g) > 1e-3:
            return "frame %d ball %d: expected %r got %r" % (f, i, e, g)
    return True


def _lines_track(t):
    for f, tm, v in _rows(t, "pos", "line_ends", "linhas_cell"):
        pos, ends = v["pos"], v["line_ends"]
        if len(ends) == 0:
            continue
        if len(ends) != len(pos) - 1:
            return "frame %d: %d lines for %d balls" % (f, len(ends), len(pos))
        for j, (p1, p2) in enumerate(ends):
            if _d(p1, pos[j]) > TOL or _d(p2, pos[j + 1]) > TOL:
                return "frame %d line %d ends %r,%r vs balls %r,%r" % (
                    f, j, p1, p2, pos[j], pos[j + 1])
    return True


def _bbox(t):
    pts = [CENTER] + [m for m in t.values("mouse")]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    lo_x, hi_x, lo_y, hi_y = min(xs) - 1e-6, max(xs) + 1e-6, min(ys) - 1e-6, max(ys) + 1e-6
    for f, _, pos in t.series("pos"):
        for i, (x, y) in enumerate(pos):
            if not (lo_x <= x <= hi_x and lo_y <= y <= hi_y):
                return "frame %d ball %d at %r outside hull box" % (f, i, (x, y))
    return True


def _first_rebuild_frame(t):
    first = t.series("ids")[0][2]
    for f, _, ids in t.series("ids"):
        if ids != first:
            return f
    return None


def _tail_at_center_on_rebuild(t):
    f = _first_rebuild_frame(t)
    if f is None:
        return "chain was never rebuilt"
    tail = t.at_frame(f, "pos")[-1]
    if _d(tail, CENTER) > 1.0:
        return "tail at %r on rebuild frame %d, expected near %r" % (tail, f, CENTER)
    return True


def _all_new_ids(t):
    first = set(t.series("ids")[0][2])
    end = set(t.end("ids"))
    return True if not (first & end) else "some balls survived the rebuild"


def _val_before(t, probe, prefix, nth):
    return t.at_frame(t.input_frame(prefix, nth) - 1, probe)


def _rebuild_n_before(t):
    f = t.input_frame("button", 0)
    for fr, _, n in t.series("n_bolas"):
        if fr < f and n != 30:
            return "frame %d: %r balls before Rodar (slider alone must not rebuild)" % (fr, n)
    return True


def _linhas_off(t):
    f_rodar = t.input_frame("button", 2)
    before = t.at_frame(f_rodar - 1, "n_linhas")
    cell = t.at_frame(f_rodar - 1, "linhas_cell")
    if cell != False:
        return "st.linhas after clicking the CheckBox is %r" % (cell,)
    if before != 29:
        return "lines changed before Rodar: %r" % (before,)
    return True


def _efeito_first(t):
    vis = _val_before(t, "visuals", "cell", 1)
    return True if vis and all(v == "Flame" for v in vis) else "visuals %r" % (vis,)


def _paused_window(t):
    f_esc = t.input_frame("key", 0)
    f_btn = t.input_frame("button", 0)
    for f, _, v in t.series("paused"):
        if f < f_esc and v:
            return "paused before ESC at frame %d" % f
        if f_esc <= f < f_btn and not v:
            return "not paused at frame %d (menu should be open)" % f
    return True


def _frozen_while_paused(t):
    f_esc = t.input_frame("key", 0)
    f_btn = t.input_frame("button", 0)
    ref = t.at_frame(f_esc, "pos")
    for f, _, pos in t.series("pos"):
        if f_esc < f < f_btn:
            for a, b in zip(ref, pos):
                if _d(a, b) > 1e-9:
                    return "ball moved while paused at frame %d" % f
    return True


def _time_frozen(t):
    f_esc = t.input_frame("key", 0)
    f_btn = t.input_frame("button", 0)
    ref = t.at_frame(f_esc, "time")
    for f, _, tm in t.series("time"):
        if f_esc < f < f_btn and abs(tm - ref) > 1e-9:
            return "clock.time advanced while paused at frame %d" % f
    return True


def _continue_keeps_chain(t):
    if t.end("ids") != t.series("ids")[0][2]:
        return "Continuar rebuilt the chain"
    return True


def _moves_after_continue(t):
    f_btn = t.input_frame("button", 1)
    a = t.at_frame(f_btn, "pos")[0]
    b = t.end("pos")[0]
    return True if _d(a, b) > 1e-6 else "head did not move after the menu closed"


def _light_steps(t):
    # Revised (DOC-SILENT, PM5): .color reads the colour a look paints now; a
    # Halo washes the body, so the chain's colour steps show under a look that
    # keeps the set colour (Gel, the last Rodar of "efeito"), not under Halo.
    light = t.end("light")
    for i in range(len(light) - 1):
        if abs((light[i] - light[i + 1]) - 0.02) > 1e-3:
            return "lightness step %d is %r" % (i, light[i] - light[i + 1])
    return True


def _slider_click(t):
    n = t.end("n_cell")
    if not (5 <= n <= 60 and float(n) == int(n)):
        return "st.n_bolas after click = %r" % (n,)
    if t.end("n_bolas") != n:
        return "Rodar built %r balls for st.n_bolas = %r" % (t.end("n_bolas"), n)
    return True


def _head_near(point, before_prefix=None, nth=None):
    def chk(t):
        if before_prefix is None:
            head = t.end("pos")[0]
        else:
            head = _val_before(t, "pos", before_prefix, nth)[0]
        return True if _d(head, point) < 0.5 else "head at %r, mouse at %r" % (head, point)
    return chk


# ---------------------------------------------------------------- expectations
TUT = "docs/pt/tutorial/04-ui-widgets.html"
G = "docs/pt/guide/index.html"

EXPECT = [
    # ---- startup
    Expect(id="E1", level="L0", cite=TUT + " (A cadeia; Slider)",
           text="criar() runs at startup with st.n_bolas = 30: group 'bolas' has 30 balls on frame 1.",
           check=at(1, "n_bolas", lambda v: v == 30), scenarios=("*",)),
    Expect(id="E2", level="L0", cite=TUT + " (Linhas)",
           text="With linhas on, the first ball has no predecessor: 30 balls give 29 lines.",
           check=at(1, "n_linhas", lambda v: v == 29), scenarios=("*",)),
    Expect(id="E3", level="L0", cite=TUT + " (CheckBox: 'a caixa nasce marcada'); " + G + "#ui-slider, #ui-dropdown",
           text="Widgets without initial= do not overwrite the cells: st.n_bolas=30, st.linhas=True, st.efeito='Halo'.",
           check=all_of(at(1, "n_cell", lambda v: v == 30),
                        at(1, "linhas_cell", lambda v: v == True),
                        at(1, "efeito_cell", lambda v: v == "Halo")),
           scenarios=("idle", "follow", "pause")),
    Expect(id="E4", revised="INTUITION: compared the look's class name; HaloPulse is a Halo (isinstance)", level="L0", cite=TUT + " (DropDown: visual_da_bola)",
           text="Every ball starts with a Halo visual (st.efeito = 'Halo').",
           check=at(1, "visuals", lambda v: len(v) == 30 and all(x == "Halo" for x in v)),
           scenarios=("*",)),
    Expect(id="E5", level="L0", cite="examples/cadeia_de_bolas.py; " + G + " (Circle radius)",
           text="Every ball has radius 16.",
           check=always("radii", lambda v: all(r == 16 for r in v)), scenarios=("*",)),
    Expect(id="E6", level="L0", cite=G + " (Neste Shape .layer / .blend; Blend)",
           text="Every line sits on layer -1 and blends with 'add'.",
           check=all_of(at(1, "line_layers", lambda v: len(v) == 29 and all(x == -1 for x in v)),
                        at(1, "line_blends", lambda v: all(x == "add" for x in v))),
           scenarios=("idle",)),
    Expect(id="E7", level="L0", cite=TUT + " ('centro da vista (canvas.game_view.center)'); " + G + " (canvas.game_view)",
           text="Assumed: with init(width=1000, height=700) and no camera move, game_view.center is (500, 350).",
           check=always("view_center", lambda v: close(v, CENTER, 1e-6)),
           scenarios=("idle",), guess=True),
    Expect(id="E8", level="L1", cite=TUT + " (A cadeia); " + G + "#util-chase",
           text="Balls are born at the view centre; after frame 1 the tail has moved by ~k^30 of the gap, i.e. it is still at the centre.",
           check=at(1, "pos", lambda v: _d(v[-1], CENTER) < 1e-3), scenarios=("idle", "follow")),
    Expect(id="E9", level="L1", cite=G + "#util-chase ('lerp(current, target, 1 - exp(-rate * dt))')",
           text="Frame 1 positions equal one chained chase step (rate 8, dt = clock.time after frame 1) from all balls at the centre.",
           check=custom(_frame1_from_center), scenarios=("idle", "follow")),
    # ---- motion model
    Expect(id="E10", level="L1", cite=G + "#util-chase; " + G + " (clock.dt; Mouse); " + TUT + " (A cadeia)",
           text="Every frame (chain not rebuilt): head = chase(head, mouse, 8); ball i = chase(ball i, already-moved ball i-1, 8), with dt = time step (0 when paused); rel. tol 1e-4.",
           check=custom(_recurrence), scenarios=("*",)),
    Expect(id="E11", level="L2", cite=G + "#util-chase ('sem passar do alvo')",
           text="chase never overshoots: every ball stays inside the bounding box of the view centre and all mouse positions (slop 1e-6, float rounding).",
           check=custom(_bbox), scenarios=("*",)),
    Expect(id="E12", level="L1", cite=G + "#util-chase (rate=6 -> 95% in 0.5 s); " + G + "#frame-mouse",
           text="With the mouse held at (800, 500) for 2.5 s the head is within 0.5 of it (remaining gap e^-20).",
           check=custom(_head_near((800, 500), "move", 1)), scenarios=("follow",)),
    Expect(id="E13", level="L1", cite=G + "#util-chase",
           text="After the mouse moves to (200, 150) and 2.5 s pass, the head is within 0.5 of it.",
           check=custom(_head_near((200, 150))), scenarios=("follow",)),
    Expect(id="E14", level="L1", cite=TUT + " (Linhas: '@= ... as pontas andam junto'); " + G + "#shape-line",
           text="Line j's p1/p2 always coincide with balls j and j+1 (links follow every move).",
           check=custom(_lines_track), scenarios=LINE_SCENARIOS),
    Expect(id="E15", level="L0", cite=TUT + " (A cadeia)",
           text="With no input the chain is never rebuilt: 30 balls and 29 lines on every frame.",
           check=all_of(always("n_bolas", lambda v: v == 30), always("n_linhas", lambda v: v == 29),
                        steady("ids")),
           scenarios=("idle", "follow")),
    Expect(id="E16", level="L0", cite=G + "#ui-menu (pause=True); " + TUT + " (Menu de pausa)",
           text="Without ESC no Menu opens, so the clock is never paused.",
           check=never("paused", lambda v: v), scenarios=("idle", "follow", "rebuild_n", "efeito")),
    # ---- slider + Rodar
    Expect(id="E17", level="L0", cite=TUT + " (Slider: 'as bolas não ... criar não roda de novo sozinha')",
           text="Changing st.n_bolas alone does not rebuild: 30 balls until Rodar is clicked.",
           check=custom(_rebuild_n_before), scenarios=("rebuild_n",)),
    Expect(id="E18", level="L0", cite=TUT + " (Botão Rodar); " + G + "#ui-button",
           text="After Rodar with st.n_bolas = 10: 10 balls, 9 lines, the cell keeps 10.",
           check=all_of(at_end("n_bolas", lambda v: v == 10), at_end("n_linhas", lambda v: v == 9),
                        at_end("n_cell", lambda v: v == 10)),
           scenarios=("rebuild_n",)),
    Expect(id="E19", revised="SPEC-LOGIC: id() reused after a free; probe now uses a per-object serial", level="L0", cite=TUT + " (Botão Rodar: destroy limpa); " + G + " (Grupos: destruído sai na hora)",
           text="Rodar destroys the old balls: none of the original balls remain in the group.",
           check=custom(_all_new_ids), scenarios=("rebuild_n", "linhas_off", "efeito", "restart")),
    Expect(id="E20", level="L1", cite=TUT + " (Botão Rodar: 'a cadeia renasce no centro')",
           text="On the frame the chain is rebuilt, the new tail is at the view centre (within 1 unit).",
           check=custom(_tail_at_center_on_rebuild), scenarios=("rebuild_n", "linhas_off", "restart")),
    Expect(id="E21", level="L0", cite=G + "#ui-slider ('O Slider não corrige o Attribute')",
           text="st.n_bolas = 3 (below min_value) is not clamped; Rodar builds 3 balls and 2 lines.",
           check=all_of(at_end("n_cell", lambda v: v == 3), at_end("n_bolas", lambda v: v == 3),
                        at_end("n_linhas", lambda v: v == 2)),
           scenarios=("out_of_range",)),
    Expect(id="E22", level="L0", cite=G + "#ui-slider ('sempre dentro da faixa', only_int)",
           text="Clicking the Bolas slider writes an integer in [5, 60]; the next Rodar builds that many balls.",
           check=custom(_slider_click), scenarios=("slider_click",)),
    # ---- checkbox
    Expect(id="E23", level="L0", cite=G + "#ui-checkbox ('Clicar inverte o valor'); " + TUT + " (CheckBox)",
           text="Clicking Linhas sets st.linhas False; the existing 29 lines remain until Rodar.",
           check=custom(_linhas_off), scenarios=("linhas_off",)),
    Expect(id="E24", level="L0", cite=TUT + " (CheckBox: 'a cadeia renasce sem linhas')",
           text="After Rodar with linhas off: 30 balls and 0 lines.",
           check=all_of(at_end("n_bolas", lambda v: v == 30), at_end("n_linhas", lambda v: v == 0),
                        at_end("linhas_cell", lambda v: v == False)),
           scenarios=("linhas_off",)),
    # ---- dropdown cell
    Expect(id="E25", level="L0", cite=TUT + " (DropDown: 'Escolha Flame e aperte Rodar')",
           text="With st.efeito = 'Flame', Rodar gives every ball a Flame visual.",
           check=custom(_efeito_first), scenarios=("efeito",)),
    Expect(id="E26", level="L0", cite=TUT + " (DropDown)",
           text="With st.efeito = 'Gel', the second Rodar gives 30 balls all with a Gel visual.",
           check=all_of(at_end("visuals", lambda v: len(v) == 30 and all(x == "Gel" for x in v)),
                        at_end("n_linhas", lambda v: v == 29)),
           scenarios=("efeito",)),
    # ---- menu / pause
    Expect(id="E27", level="L0", cite=G + "#ui-menu (pause=True; Teclas: keyp lê falso com modal)",
           text="ESC opens the pause Menu: clock.paused is True from the ESC frame until an option is clicked; a second ESC while it is open neither closes it nor opens another (assumed: Esc does not dismiss a Menu).",
           check=custom(_paused_window), scenarios=("pause", "restart"), guess=True),
    Expect(id="E28", level="L1", cite=G + " (clock: 'pausado, [dt] é 0'); " + G + "#util-chase (dt == 0 devolve current)",
           text="While the menu is open every ball keeps its position exactly.",
           check=custom(_frozen_while_paused), scenarios=("pause", "restart")),
    Expect(id="E29", level="L1", cite=G + " (clock: time is game time, 0 dt when paused)",
           text="clock.time does not advance while the pause menu is open.",
           check=custom(_time_frozen), scenarios=("pause",)),
    Expect(id="E30", level="L0", cite=G + "#ui-menu ('ao fechar, clock.paused volta'); " + TUT + " (Menu de pausa: Continuar)",
           text="Continuar closes the menu, unpauses, and keeps the same chain (no rebuild).",
           check=all_of(at_end("paused", lambda v: v == False), custom(_continue_keeps_chain),
                        at_end("n_bolas", lambda v: v == 30)),
           scenarios=("pause",)),
    Expect(id="E31", level="L0", cite=TUT + " (Menu de pausa: 'fechar o menu já é continuar')",
           text="After Continuar the head moves again.",
           check=custom(_moves_after_continue), scenarios=("pause",)),
    Expect(id="E32", level="L0", cite=G + "#ui-menu (Ao escolher: ... depois chama on_choose); " + TUT + " (Menu de pausa)",
           text="Recomeçar unpauses and rebuilds a fresh chain of 30 balls with 29 lines.",
           check=all_of(at_end("paused", lambda v: v == False), at_end("n_bolas", lambda v: v == 30),
                        at_end("n_linhas", lambda v: v == 29)),
           scenarios=("restart",)),
    # ---- colours
    Expect(id="E33", revised="DOC-SILENT: .color is the colour the look paints now (Halo washes it); check under Gel (PM5)", level="L1", cite=G + " (Color.darker / Gradient.darker: HSL lightness); " + TUT + " (A cadeia)",
           text="Under Gel (which paints the set colour) each ball's .color is 0.02 HSL-lightness darker than the one before (tol 1e-3).",
           check=custom(_light_steps), scenarios=("efeito",), guess=True),
]
