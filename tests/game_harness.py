"""Driver side of the game system tests: run a game, pilot it, judge what it recorded.

Not a test module. The games live in ``tests/games/`` and record into a
``game_support.Ledger`` (``G``); this module runs them through
``program_support.ProgramRun`` (headless real frames, input through the real
GLFW handlers), reads ``G.report()`` before ``close()``, and checks:

* no failure the game recorded (except ``KNOWN``, shrink-only, with reasons);
* every reach minimum of the scenario met (the run did what it claims);
* every check name the game has was evaluated (a check that never ran proves
  nothing) — per scenario, ``CHECKS`` lists the names that must have run;
* no probe error, no unexpected SCENA warning, no leftovers, no zombies.

Strategy and rules: design/Testing Design.md, "Game system tests".
"""
from __future__ import annotations

import os
import sys
import warnings
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from program_support import (FRAME, ProgramRun, Scenario, click, drive, key, wait)  # noqa: E402
from system_support import zombies  # noqa: E402

GAMES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "games")


def game_path(name: str) -> str:
    return os.path.join(GAMES_DIR, name + ".py")


# ---------------------------------------------------------------------------
# Known failures: (game, check name) -> "finding: reason". Shrink-only: an
# entry that no longer fails makes the run fail (remove it).
# ---------------------------------------------------------------------------

KNOWN: Dict[Tuple[str, str], str] = {}

# SCENA warnings a game may raise on purpose, with the reason.
WARN_OK: Dict[str, str] = {}


# ---------------------------------------------------------------------------
# Pilot helpers
# ---------------------------------------------------------------------------

class Pilot:
    """Base pilot: holds keys, clicks in two frames, counts its own frames.

    Deterministic: reads only the program's state and its own counters.
    """

    def __init__(self) -> None:
        self.held: set = set()
        self.t = 0                  # frames this pilot ran
        self._release_at: Optional[int] = None
        self.done: List[str] = []   # what it managed to do (debug)

    # -- keys -----------------------------------------------------------
    def hold(self, run: ProgramRun, name: str, on: bool) -> None:
        if on and name not in self.held:
            run.key_down(name)
            self.held.add(name)
        elif not on and name in self.held:
            run.key_up(name)
            self.held.discard(name)

    def tap(self, run: ProgramRun, name: str) -> None:
        """Press now; ``__call__`` releases it next frame."""
        run.key_down(name)
        self.held.add(name)
        self._tapped = name

    # -- mouse ----------------------------------------------------------
    def click(self, run: ProgramRun, x: float, y: float) -> None:
        run.press(x, y)
        self._release_at = self.t + 1

    def __call__(self, run: ProgramRun) -> None:
        tapped = getattr(self, "_tapped", None)
        if tapped is not None:
            self.hold(run, tapped, False)
            self._tapped = None
        if self._release_at is not None and self.t >= self._release_at:
            run.release()
            self._release_at = None
        else:
            self.act(run)
        self.t += 1

    def act(self, run: ProgramRun) -> None:      # pragma: no cover - overridden
        pass


def widget_center(w) -> Tuple[float, float]:
    return ((w._x1 + w._x2) / 2.0, (w._y1 + w._y2) / 2.0)


def dropdown_option_center(w, index: int) -> Tuple[float, float]:
    """Centre of option ``index`` of an open DropDown (its own row layout)."""
    top = w._list_span()[1]
    y = top - w._list_padding - w._option_height * (index + 0.5)
    return ((w._x1 + w._x2) / 2.0, y)


def slider_x_for(w, value: float) -> Tuple[float, float]:
    """Where on the Slider's track ``value`` sits (its own track layout)."""
    t = (value - w.min_value) / (w.max_value - w.min_value)
    return (w._slider_x + t * w._slider_length, w._slider_y)


# ---------------------------------------------------------------------------
# Armada pilot
# ---------------------------------------------------------------------------

class ArmadaPilot(Pilot):
    """Plays Armada: title button, hangar widgets, a fighting run with one pause.

    ``rounds``: how many times to go through Titulo (the campaign ends at the
    second title); ``pause_at``: frame of each Setor to pause (None: never).
    """

    def __init__(self, *, rounds: int = 1, pause_at: Optional[int] = 150,
                 desistir: bool = False, dodge: bool = True) -> None:
        super().__init__()
        self.dodge = dodge
        self.rounds = rounds
        self.pause_at = pause_at
        self.desistir = desistir
        self.act_name = None
        self.act_t = 0
        self.titles = 0
        self.step_i = 0
        self.paused_in = set()
        self.wait_until = 0

    def act(self, run: ProgramRun) -> None:
        v = run.view
        name = v.ATO["nome"]
        if name != self.act_name:
            self.act_name = name
            self.act_t = 0
            self.step_i = 0
            self.hold(run, "LEFT", False)
            self.hold(run, "RIGHT", False)
            self.hold(run, "SPACE", False)
            if name == "Titulo":
                self.titles += 1
        self.act_t += 1
        if v.TROCA["pendente"] is not None or self.t < self.wait_until:
            return
        getattr(self, "act_" + (name or "none"), lambda r, v: None)(run, v)

    def act_Titulo(self, run, v):
        if self.titles > self.rounds:
            return
        if self.act_t == 20:
            b = v.BOTOES["jogar"]
            self.click(run, b.center.x, b.center.y)
            self.done.append("jogar")

    def act_Hangar(self, run, v):
        w = v.WIDGETS
        if self.act_t < 15:
            return
        i = self.step_i
        if i == 0:
            self.click(run, *widget_center(w["nave"]))           # open the list
        elif i == 1:
            self.click(run, *dropdown_option_center(w["nave"], 1))
        elif i == 2:
            self.click(run, *widget_center(w["crt"]))
        elif i == 3:
            x0, y0 = slider_x_for(w["volume"], w["volume"].value)
            run.press(x0, y0)
            self._drag = (x0, y0, slider_x_for(w["volume"], 0.5)[0])
        elif 4 <= i <= 8:
            x0, y0, x1 = self._drag
            run.move(x0 + (x1 - x0) * (i - 3) / 5.0, y0)
        elif i == 9:
            run.release()
        elif i == 10:
            x, y = slider_x_for(w["volume"], w["volume"].value)
            run.move(x, y)
        elif i == 11:
            run.scroll(0.0, 1.0)
        elif i == 12:
            self.click(run, *widget_center(w["lancar"]))
            self.done.append("lancar")
        else:
            return
        self.step_i += 1
        self.wait_until = self.t + 3

    def _fight(self, run, v):
        g = v.group
        heroes = list(g["heroi"])
        if not heroes:
            return
        hx, hy = heroes[0].center.x, heroes[0].center.y
        alvo = g["alvos"].nearest((hx, hy + 400))
        tx = alvo.center.x if alvo is not None else 500.0
        # an orb falling low: go and take it (the shield tween)
        if v.st.escudo <= 0:
            for o in g["energia"]:
                if o.center.y < 360:
                    tx = o.center.x
                    break
        # dodge: an enemy shot close above pushes the target away
        if self.dodge:
            for s in g["tiro_inimigo"]:
                sx, sy = s.center.x, s.center.y
                if 0 < sy - hy < 160 and abs(sx - hx) < 45:
                    tx = hx + (90 if sx <= hx else -90)
                    break
        self.hold(run, "LEFT", tx < hx - 10)
        self.hold(run, "RIGHT", tx > hx + 10)
        burst = (self.act_t // 60) % 4 != 3          # release SPACE one second in four
        self.hold(run, "SPACE", burst)

    def act_Setor(self, run, v):
        if self.pause_at is not None and self.act_t == self.pause_at and "Setor" not in self.paused_in:
            self.paused_in.add("Setor")
            self.hold(run, "SPACE", False)
            self.tap(run, "P")
            self._menu_at = self.t + 20
            return
        if getattr(self, "_menu_at", None) is not None:
            if self.t >= self._menu_at:
                try:
                    x, y = run.widget_center("Desistir" if self.desistir else "Continuar")
                except AssertionError:
                    return
                self.click(run, x, y)
                self._menu_at = None
                self.done.append("menu")
            return
        self._fight(run, v)

    def act_Chefe(self, run, v):
        self._fight(run, v)


# ---------------------------------------------------------------------------
# Caverna pilot
# ---------------------------------------------------------------------------

class CavernaPilot(Pilot):
    """Runs the level with knowledge of its layout (caverna.json): falls into
    the first gap once (death, iris, respawn at the checkpoint), then a late
    (coyote) jump past that edge and a buffered jump just before landing,
    attacks robots, jumps off the high platform, walks into the lift's pit
    once (respawn far behind: Endless slots come back), then rides the lift to
    the exit. Deaths are read from ``st.mortes``."""

    def __init__(self, *, fall_gap: bool = True, fall_pit: bool = True,
                 coyote: bool = True) -> None:
        super().__init__()
        self.fall_gap = fall_gap
        self.fall_pit = fall_pit
        self.coyote = coyote
        self.jumped_gap = False
        self.buffered = False
        self.riding = False

    def act(self, run: ProgramRun) -> None:
        v = run.view
        P = v.PILOTO
        if "x" not in P or v.ATO["nome"] != "Fase":
            self.hold(run, "RIGHT", False)
            return
        x, y, vy, chao = P["x"], P["y"], P["vy"], P["chao"]
        mortes = v.st.mortes
        if P["morrendo"]:
            self.hold(run, "RIGHT", False)
            self.jumped_gap = self.buffered = self.riding = self.boarding = False
            return
        right = True
        gap_first = self.fall_gap and mortes == 0
        # first gap (edge 900): fall the first time; then jump late (coyote)
        if not gap_first and not self.jumped_gap:
            if self.coyote and 912 < x < 926 and not chao:
                self.tap(run, "UP")
                self.jumped_gap = True
            elif not self.coyote and 860 < x < 890 and chao:
                self.tap(run, "UP")
                self.jumped_gap = True
        # buffered: UP while falling, a few frames before landing past the gap
        elif self.jumped_gap and not self.buffered and not chao and vy < 0 and 1000 < x < 1175 \
                and 84 < y < 104:
            self.tap(run, "UP")
            self.buffered = True
        # the rock (1180-1250)
        if chao and 1110 < x < 1150:
            self.tap(run, "UP")
        # robots: attack one close ahead
        left = False
        for r in v.group["robo"]:
            if r.morto or abs(r.center.y - y) >= 70:
                continue
            dx = r.center.x - x
            if 0 < dx < 110:
                if self.t % 4 == 0:
                    self.tap(run, "X")
                break
            if -120 < dx <= 0 and chao:          # passed it: turn (the sword flips) and strike
                right, left = False, True
                if self.t % 4 == 0:
                    self.tap(run, "X")
                break
        # off the high platform (ends at 2348)
        if chao and 2300 < x < 2335 and y > 150:
            self.tap(run, "UP")
        # the lift (pit 3260-3500)
        ex = P["elevador_x"]
        pit_first = self.fall_pit and mortes <= (1 if self.fall_gap else 0)
        if 3200 < x < 3262 and chao and not self.riding and not getattr(self, "boarding", False):
            if pit_first:
                right = ex > 3400           # walk in while the lift is away
            elif ex > 3328:
                right = False               # wait for the near end (3325)
            else:
                self.boarding = True
        if getattr(self, "boarding", False):
            right = x < ex - 15              # walk until over the lift, then stand
            if not right:
                self.boarding, self.riding = False, True
        elif self.riding and x < 3500:
            right = ex > 3430                # step off at the far end
        self.hold(run, "RIGHT", right)
        self.hold(run, "LEFT", left and not right)


# ---------------------------------------------------------------------------
# Oficina pilot
# ---------------------------------------------------------------------------

def screen_pixel(run: ProgramRun):
    """``px(x, y)`` for the frame just drawn: world point -> (r, g, b)."""
    import numpy as np
    import skia
    a = np.asarray(run.world.surface.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType))

    def px(x, y):
        sx, sy = run._to_screen(x, y)
        r, g, b, _a = a[int(round(sy)), int(round(sx))]
        return (int(r), int(g), int(b))
    return px


class OficinaPilot(Pilot):
    """A scripted session (a generator, one step per frame): drags, widgets,
    pixel checkpoints, hovers, the trash, typing, the reset menu."""

    def __init__(self, *, rounds: int = 2, materials=("fill", "stroke", "gradiente", "paint",
                                                      "textura")) -> None:
        super().__init__()
        self.rounds = rounds
        self.materials = materials
        self.script = None

    def act(self, run: ProgramRun) -> None:
        if self.script is None:
            self.script = self.plan(run)
        try:
            next(self.script)
        except StopIteration:
            pass

    # helpers (each yields one frame per step) ---------------------------
    def wait(self, n):
        for _ in range(n):
            yield

    def click_at(self, run, x, y):
        run.press(x, y)
        yield
        run.release()
        yield

    def drag(self, run, p0, p1, frames=8):
        run.press(*p0)
        yield
        for i in range(1, frames + 1):
            f = i / frames
            run.move(p0[0] + (p1[0] - p0[0]) * f, p0[1] + (p1[1] - p0[1]) * f)
            yield
        run.release()
        yield

    def checkpoint(self, run):
        run.step(1, dt=0.0, draw=True)
        run.view.conferir_pixels(screen_pixel(run))

    def plan(self, run):
        v = run.view
        for rodada in range(self.rounds):
            yield from self.wait(10)
            P = v.PECAS
            cel = lambda c, r: (v.GRADE.cell(c, r).center.x, v.GRADE.cell(c, r).center.y)
            # generators into column 0 (a gap first: the piece goes home)
            gb = P["gb"]
            yield from self.drag(run, (gb.center.x, gb.center.y), (v.TABULEIRO.left + 131, 400))
            yield from self.wait(3)
            yield from self.drag(run, (gb.center.x, gb.center.y), cel(0, 2))
            yield from self.wait(3)
            # tension up with the slider; gain with the wheel
            w = run.widget("Tensao")
            x0, y0 = slider_x_for(w, w.value)
            yield from self.drag(run, (x0, y0), slider_x_for(w, 9.0), frames=6)
            g = run.widget("Ganho A")
            run.move(*slider_x_for(g, g.value))
            yield
            for _ in range(3):
                run.scroll(0.0, 1.0)
                yield
            yield from self.wait(5)
            # freeze, then unfreeze the lamp
            yield from self.click_at(run, *run.widget_center("Congelar"))
            yield from self.wait(20)
            yield from self.click_at(run, *run.widget_center("Congelar"))
            yield from self.wait(5)
            # materials, each with a drawn checkpoint
            dd = P["dd"]
            for mat in self.materials:
                i = v.MATERIAIS.index(mat)
                yield from self.click_at(run, *widget_center(dd))
                yield from self.wait(2)
                yield from self.click_at(run, *dropdown_option_center(dd, i))
                yield from self.wait(2)
                self.checkpoint(run)
                yield
            # the laser target sweeps across the board
            alvo = P["alvo"]
            for dest in ((320, 520), (470, 330), (620, 260), (300, 200), (860, 560)):
                yield from self.drag(run, (alvo.center.x, alvo.center.y), dest, frames=10)
                yield from self.wait(4)
            # hover over each piece, click the lamp
            for k in ("ga", "gb", "lampada", "prisma"):
                p = P[k]
                run.move(p.center.x, p.center.y)
                yield from self.wait(3)
            run.move(960, 400)
            yield from self.wait(3)
            lamp = P["lampada"]
            # the lamp onto a generator's cell: the compound body touches it
            home = (lamp.center.x, lamp.center.y)
            yield from self.drag(run, home, cel(0, 0))
            yield from self.wait(4)
            yield from self.drag(run, (lamp.center.x, lamp.center.y), home)
            yield from self.wait(3)
            yield from self.click_at(run, lamp.center.x, lamp.center.y)
            yield from self.wait(3)
            yield from self.click_at(run, lamp.center.x, lamp.center.y)
            # mute for a while
            yield from self.click_at(run, *run.widget_center("Mudo"))
            yield from self.wait(80)
            yield from self.click_at(run, *run.widget_center("Mudo"))
            # type into the seed box: 42 Enter (keyp sees no digit meanwhile); 9 Esc
            ti = P["ti"]
            field = ((ti._x1 + ti._x2) / 2.0 + (ti._x2 - ti._x1) / 4.0, (ti._y1 + ti._y2) / 2.0)
            yield from self.click_at(run, *field)
            for k in ("BACKSPACE", "BACKSPACE", "4", "4", "2"):
                run.key_down(k)
                yield
                yield
                run.key_up(k)
                yield
            run.key_down("ENTER")
            yield
            run.key_up("ENTER")
            yield from self.wait(3)
            yield from self.click_at(run, *field)
            for k in ("9", "ESC"):
                run.key_down(k)
                yield
                run.key_up(k)
                yield
            yield from self.wait(3)
            # an R hotkey outside the box turns the prism
            run.key_down("R")
            yield
            run.key_up("R")
            yield from self.wait(3)
            # hide the prism (H): the background comes back
            run.key_down("H")
            yield
            run.key_up("H")
            yield
            self.checkpoint(run)
            yield
            run.key_down("H")
            yield
            run.key_up("H")
            yield
            # a generator into the trash
            gb = P["gb"]
            yield from self.drag(run, (gb.center.x, gb.center.y), (920, 80))
            yield from self.wait(10)
            if rodada + 1 < self.rounds:
                yield from self.click_at(run, *run.widget_center("Reset"))
                yield from self.wait(3)
                yield from self.click_at(run, *run.widget_center("Sim"))
                yield from self.wait(5)
        while True:
            yield


# ---------------------------------------------------------------------------
# Canteiro pilot
# ---------------------------------------------------------------------------

class CanteiroPilot(Pilot):
    """Plays Canteiro by the clock of the act (seconds, so every pacing plays
    the same session): the HUD first (the Zoom slider, the crate icon onto the
    plot, two stakes, a crate into the trash, the Jato held until it breaks,
    hover in and out of the window, Enter held with repeats in the Nome box),
    then the walk: through the spikes (a stop on them), up the ramp (a stop on
    it), Shift + SPACE, onto the pit lift (a few steps on it), onto the shaft
    lift for a full cycle, to the door with RIGHT held (released in the shed).
    While walking it wanders the cursor over the moving world and clicks.

    It writes ``CURSOR`` in the game (where the cursor is, in view units, and
    what owns the press): the truth of the game's pointer models."""

    WANDER = ((420.0, 330.0), (610.0, 260.0), (300.0, 380.0), (720.0, 420.0), (520.0, 210.0))

    def __init__(self, *, hud: bool = True, shift: bool = True, wander: bool = True) -> None:
        super().__init__()
        self.hud = hud
        self.shift = shift
        self.wander = wander
        self.script = None

    def act(self, run: ProgramRun) -> None:
        if self.script is None:
            self.script = self.plan(run)
        try:
            next(self.script)
        except StopIteration:
            pass

    # cursor and buttons, told to the game -----------------------------------
    def _cur(self, run, x, y, **kw):
        c = run.view.CURSOR
        c["view"] = (float(x), float(y))
        c.update(kw)

    def move_to(self, run, x, y):
        run.move(x, y)
        self._cur(run, x, y)

    def place(self, run, x, y):
        run.place(x, y)
        self._cur(run, x, y)

    def down(self, run, x, y, dono):
        run.press(x, y)
        self._cur(run, x, y, botao=True, dono=dono)

    def up(self, run):
        run.release()
        run.view.CURSOR["botao"] = False

    # time ------------------------------------------------------------------
    def now(self, run):
        return float(run.view.clock.time)

    def wait_s(self, run, s):
        end = self.now(run) + s
        while self.now(run) < end - 1e-9:
            yield

    def click(self, run, x, y, dono):
        self.down(run, x, y, dono)
        yield
        self.up(run)
        yield

    def drag(self, run, p0, p1, dono, frames=8):
        self.down(run, *p0, dono)
        yield
        for i in range(1, frames + 1):
            f = i / frames
            p = p1() if callable(p1) else p1
            self.move_to(run, p0[0] + (p[0] - p0[0]) * f, p0[1] + (p[1] - p0[1]) * f)
            yield
        self.up(run)
        yield

    def tap_key(self, run, name, frames=1):
        run.key_down(name)
        for _ in range(frames):
            yield
        run.key_up(name)
        yield

    def to_view(self, run, x, y):
        return run.world.fw.world_to_view_coords(x, y)

    # the session -------------------------------------------------------------
    def plan(self, run):
        v = run.view
        rodada = 0
        while True:
            while v.PILOTO.get("ato") != "Patio" or "x" not in v.PILOTO:
                yield
            rodada += 1
            yield from self.wait_s(run, 0.3)
            if self.hud and rodada == 1:
                yield from self.hud_phase(run)
            yield from self.walk(run)
            # the shed: RIGHT is still held across the act change; let go there
            yield from self.wait_s(run, 0.3)
            for k in sorted(self.held):
                self.hold(run, k, False)
            yield

    def hud_phase(self, run):
        v = run.view
        w = run.widget("Zoom")
        yield from self.drag(run, slider_x_for(w, w.value), slider_x_for(w, 0.85), "widget", frames=6)
        yield from self.wait_s(run, 0.1)
        icone = v.CENA["icone"]
        casa = (icone.center.x, icone.center.y)
        yield from self.drag(run, casa, lambda: self.to_view(run, 250.0, 130.0), "ui")
        self.done.append("icone")
        yield from self.wait_s(run, 0.7)
        for p in ((520.0, 330.0), (700.0, 380.0)):
            yield from self.click(run, *p, "mundo")
            yield from self.wait_s(run, 0.1)
        caixotes = [c for c in v.group["caixote"] if c.visible]
        if caixotes:
            c = caixotes[-1]
            p0 = self.to_view(run, c.center.x, c.center.y)
            yield from self.drag(run, p0, (940.0, 60.0), "mundo")
            self.done.append("lixeira")
        yield from self.wait_s(run, 0.2)
        jx, jy = run.widget_center("Jato")
        self.down(run, jx, jy, "widget")
        yield from self.wait_s(run, 0.6)
        self.up(run)
        yield
        self.done.append("jato")
        yield from self.wait_s(run, 1.2)
        for off in ((500.0, 680.0), (-60.0, 300.0)):
            jx, jy = run.widget_center("Jato")
            self.move_to(run, jx, jy)
            yield from self.wait_s(run, 0.15)
            self.place(run, *off)
            yield from self.wait_s(run, 0.15)
        self.move_to(run, 500.0, 300.0)
        yield
        nome = run.widget("Nome")
        yield from self.click(run, *widget_center(nome), "widget")
        for k in ("A", "B"):
            yield from self.tap_key(run, k)
        run.key_down("ENTER")
        yield
        for _ in range(3):
            run.key_repeat("ENTER")
            yield
        run.key_up("ENTER")
        yield
        yield from self.tap_key(run, "ESC")
        self.done.append("caixas")
        yield from self.wait_s(run, 0.1)

    def walk(self, run):
        v = run.view
        P = v.PILOTO
        stage, mark, fases, jumped, walked = "espinho", 0.0, [], False, False
        last_wander, wi = self.now(run), 0
        while P.get("ato") == "Patio" and "x" in P:
            x, chao, t = P["x"], P["chao"], P["t"]
            right, shift = False, False
            if stage == "espinho":
                right = True
                if x >= 455:
                    stage, mark = "espinho_parado", t
            elif stage == "espinho_parado":
                if t - mark >= 0.8:
                    stage = "rampa"
            elif stage == "rampa":
                right, shift = True, self.shift
                if not jumped and 520 < x < 560 and chao:
                    self.tap(run, "SPACE")           # with Shift held (PD6)
                    jumped = True
                if 700 <= x <= 760 and chao:
                    stage, mark = "rampa_parado", t
            elif stage == "rampa_parado":
                if t - mark >= 1.0:
                    stage = "fosso"
            elif stage == "fosso":
                lado = P["lado_x"]
                if x > 875 and not chao:
                    right = False                     # off the ramp's end: fall straight
                elif x < 925:
                    right = True
                elif lado <= 1030:
                    right, shift = True, True
                    stage = "embarca_lado"
            elif stage == "embarca_lado":
                right, shift = True, True
                if x >= P["lado_x"] - 20:
                    stage, mark = "carona_lado", t
            elif stage == "carona_lado":
                if not walked and t - mark >= 0.5:
                    right = x < P["lado_x"] + 30
                    if t - mark >= 0.75:
                        walked = True
                if P["lado_x"] >= 1270.0 and P["lado_dir"] > 0:
                    stage = "beiral"                  # step off as it reaches the far end
            elif stage == "beiral":
                right, shift = x < 1415, True
                if not right and P["sobe_fase"] == "baixo" and P["sobe_t"] < 0.5:
                    stage = "embarca_sobe"
            elif stage == "embarca_sobe":
                right, shift = x < 1515, True
                if not right:
                    stage, fases = "carona_sobe", [P["sobe_fase"]]
            elif stage == "carona_sobe":
                if P["sobe_fase"] != fases[-1]:
                    fases.append(P["sobe_fase"])
                if fases.count("cima") >= 2:
                    stage = "alto"
            elif stage == "alto":
                right, shift = True, self.shift
            self.hold(run, "LEFT_SHIFT", shift and right)
            self.hold(run, "RIGHT", right)
            # the cursor wanders over the moving world; a click now and then
            if self.wander and self.now(run) - last_wander >= 0.4 and self._release_at is None:
                last_wander = self.now(run)
                p = self.WANDER[wi % len(self.WANDER)]
                wi += 1
                if wi % 4 == 0:
                    self.down(run, *p, "mundo")
                    self._release_at = self.t + 1
                    self._wander_up = True
                else:
                    self.move_to(run, *p)
            yield

    def __call__(self, run: ProgramRun) -> None:
        if getattr(self, "_wander_up", False) and self._release_at is not None \
                and self.t >= self._release_at:
            run.view.CURSOR["botao"] = False
            self._wander_up = False
        super().__call__(run)


# ---------------------------------------------------------------------------
# Game registry
# ---------------------------------------------------------------------------

@dataclass
class GameSpec:
    name: str
    scenarios: Dict[str, Scenario]
    probes: Dict[str, Callable]
    reach: Dict[str, Dict[str, int]] = field(default_factory=dict)
    checks: Dict[str, Sequence[str]] = field(default_factory=dict)
    claims: Sequence[str] = ()
    os_level: bool = False      # GameRun with a window and OS key / button state

    def spec_ns(self) -> Dict[str, Any]:
        """What ``program_oracles`` reads (``SCENARIOS`` and ``PROBES``)."""
        return {"SCENARIOS": self.scenarios, "PROBES": self.probes}


def _armada() -> GameSpec:
    curta = Scenario(
        params={"waves": 1, "cols": 4, "rows": 1, "boss_hp": 8, "god": True},
        steps=[drive(lambda: ArmadaPilot(rounds=1, pause_at=150), 2600)],
        seed=3,
    )
    campanha = Scenario(
        params={"waves": 2, "cols": 5, "rows": 2, "boss_hp": 14, "god": True,
                "vel_tiro": 6000, "mergulho": 0.8},
        steps=[drive(lambda: ArmadaPilot(rounds=1, pause_at=200), 4800)],
        seed=11,
    )
    derrota = Scenario(
        params={"waves": 2, "cols": 5, "rows": 2, "lives": 2, "mergulho": 0.8},
        steps=[drive(lambda: ArmadaPilot(rounds=1, pause_at=None, dodge=False), 2400)],
        seed=5,
    )
    desiste = Scenario(
        params={"waves": 1, "cols": 3, "rows": 1, "god": True},
        steps=[drive(lambda: ArmadaPilot(rounds=1, pause_at=90, desistir=True), 700)],
        seed=2,
    )
    # A static script (no pilot): what dt_split can re-time.
    parado = Scenario(
        params={"waves": 1, "cols": 3, "rows": 1, "god": True, "music": False},
        steps=[wait(25), click(500, 300), wait(40), ("click_widget", "LANCAR"), wait(60),
               key("SPACE", 90), wait(30), key("RIGHT", 20), key("SPACE", 60), wait(20)],
        seed=1,
    )
    probes = {
        "ledger": lambda p: p.G.digest(),
        "act": lambda p: p.ATO["nome"],
        "pontos": lambda p: p.st.pontos,
        "vidas": lambda p: p.st.vidas,
        "covered": lambda p: p.canvas.covered,
        "heroi_x": lambda p: (p.group["heroi"].first.center.x if p.group["heroi"].count else None),
    }
    reach = {
        "curta": {"act": 6, "onda": 1, "died.inimigo": 4, "chefe.morrendo": 1, "pausa": 1,
                  "menu.Continuar": 1, "timer.fired": 8, "cover.done": 8, "widget.nave": 1,
                  "widget.crt": 1, "widget.volume": 2, "widget.lancar": 1, "spritebutton.click": 1,
                  "race": 1, "parallel": 1, "collider.hit": 1, "chefe.fraco": 1,
                  "history.add": 4, "zona.enter": 1, "zona.exit": 1, "fim.voltou": 1,
                  "change.pontos": 3, "clip.last_frame": 1, "tiro.disparado": 30},
        "campanha": {"act": 6, "onda": 2, "died.inimigo": 20, "chefe.morrendo": 1, "pausa": 1,
                     "sound.crossfade": 1, "history.leave": 10, "race": 6, "race.0": 1, "race.1": 1,
                     "mode.mergulho": 5, "exit_mode.formacao": 5, "orb.pego": 1,
                     "tween.done": 1, "sparks": 1, "collide.swept": 1, "post.crt": 1},
        "derrota": {"dano": 2, "when.perdeu": 1, "act": 4},
        "desiste": {"menu.Desistir": 1, "when.perdeu": 1},
        "parado": {"act": 3, "tiro.disparado": 5},
    }
    checks = {
        "curta": ("timer.fire_frame", "cover.done_value", "pop.tiro", "pop.inimigo", "hud.fresh",
                  "score.model", "act.objects_removed", "act.effects_restored", "act.camera_restored",
                  "grid.cell_center", "race.winner", "door.test_collision", "collide.geometry",
                  "playfield.edges", "leave.outside", "ready.cadence", "ready.reopen", "handle.pause_holds",
                  "boss.hp_model", "clip.monotone", "hitbox.weak_point_answers",
                  "change.pontos.fires", "collider.me_is_body",
                  "time_scale.on_update_dt", "sound.effects_stack", "dropdown.index"),
        "derrota": ("when.perdeu.edges",),
        "desiste": ("when.perdeu.edges", "menu.unpauses"),
    }
    claims = ("Act", "change_act", "Sheet", "Sprite", "SpriteButton", "Text", "DropDown", "CheckBox",
              "Slider", "Button", "Menu", "collide", "collide_stay", "collide_exit", "leave_playfield",
              "test_collision", "Collider", "when", "on_change", "on_mode", "exit_mode", "after",
              "every", "tween", "wait", "until_empty", "race", "parallel", "Track", "History",
              "Contrail", "Box", "Grid", "Jet", "Orb", "Portal", "Sparks", "Fire", "Bloom", "Vignette",
              "Chroma", "Wash", "Crt", "Pixelate", "Stars", "SkyGradient", "play_sound", "Sound",
              "Distortion", "Wavefold", "Echo", "Reverb", "LowPass", "heading", "chance", "Color")
    return GameSpec("armada", {"curta": curta, "campanha": campanha, "derrota": derrota,
                               "desiste": desiste, "parado": parado}, probes, reach, checks, claims)


def _caverna() -> GameSpec:
    volta = Scenario(params={}, seed=1, steps=[drive(lambda: CavernaPilot(), 2400)])
    seco = Scenario(params={"camera": "deadzone"}, seed=2,
                    steps=[drive(lambda: CavernaPilot(fall_gap=False, fall_pit=False), 2400)])
    parado = Scenario(params={}, seed=3,
                      steps=[wait(20), key("RIGHT", 150), key("UP", 2), key("RIGHT", 60), wait(40),
                             key("LEFT", 80), key("X", 2), wait(30)])
    probes = {
        "ledger": lambda p: p.G.digest(),
        "x": lambda p: p.PILOTO.get("x"),
        "y": lambda p: p.PILOTO.get("y"),
        "frutas": lambda p: p.st.frutas,
        "covered": lambda p: p.canvas.covered,
        "pan_x": lambda p: p.canvas.pan_x,
    }
    reach = {
        "volta": {"act": 2, "morte": 2, "respawn": 2, "pulo.coyote": 1, "pulo.buffer": 1,
                  "fruta.pega": 8, "checkpoint": 4, "history.leave": 1, "robo.abatido": 2,
                  "golpe": 2, "endless.revisit": 1, "elevador.carona": 20, "chao.rampa": 10,
                  "fim": 1, "level.checked": 1, "robo.borda": 1},
        "seco": {"act": 2, "fim": 1, "pulo.coyote": 1, "elevador.carona": 20},
        "parado": {"level.checked": 1},
    }
    checks = {
        "volta": ("level.box", "level.make_rect", "level.rect_corners", "level.image_path",
                  "ground.foot_on_top", "ground.vel_y_zero", "ground.slope_angle", "recently.coyote_twin",
                  "recently.buffer_twin", "camera.pan_to_holds", "chase.formula", "deadzone.formula",
                  "parallax.view", "endless.same_slot_same_piece", "endless.slot_left",
                  "endless.view_covered", "handle.velocity_is_motion", "move_along.on_track",
                  "clip.frame_at_age", "history.model", "respawn.at_checkpoint",
                  "hitbox.active_only_on_strike", "robo.stays_on_ground", "grid.cell",
                  "act.objects_removed", "act.layers_removed", "cover.done_value"),
    }
    claims = ("Level", "Sheet", "Sprite", "resolve", "STATIC", "recently", "ready", "keyp", "Endless",
              "History", "Contrail", "Fire", "Rain", "Box", "Grid", "deadzone", "chase", "Track",
              "AUTO_GROUND", "Vignette", "Act", "change_act", "leave_playfield", "collide")
    return GameSpec("caverna", {"volta": volta, "seco": seco, "parado": parado}, probes, reach,
                    checks, claims)


def _oficina() -> GameSpec:
    sessao = Scenario(params={}, seed=1, steps=[drive(lambda: OficinaPilot(rounds=2), 1000)])
    curta = Scenario(params={}, seed=2, steps=[drive(
        lambda: OficinaPilot(rounds=1, materials=("fill", "stroke", "gradiente")), 520)])
    parado = Scenario(params={}, seed=3, steps=[wait(30), ("move", 470.0, 330.0), wait(10),
                                                ("drag", 860.0, 560.0, 320.0, 520.0, 10, "left"),
                                                wait(20)])
    probes = {
        "ledger": lambda p: p.G.digest(),
        "potencia": lambda p: p.OFICINA.potencia,
        "raio": lambda p: (p.PECAS["lampada"].radius if p.PECAS.get("lampada") else None),
        "alvo": lambda p: (p.PECAS["alvo"].center if p.PECAS.get("alvo") else None),
        "material": lambda p: p.st.material,
    }
    reach = {
        "sessao": {"act": 2, "drop.snap": 2, "drop.home": 1, "drop.trash": 2, "hover.enter": 6,
                   "hover.exit": 6, "click.lampada": 4, "link.unlink": 2, "link.relink": 2,
                   "when.sobrecarga": 1, "change.potencia": 6, "change.semente": 1,
                   "laser.hits0": 1, "laser.hits2": 1, "laser.chord": 1, "raycast.hit": 1,
                   "collider.hit": 1, "pixel.fill": 2, "pixel.stroke": 2, "pixel.gradiente": 2,
                   "pixel.paint": 2, "pixel.textura": 2, "pixel.hidden": 2, "hotkey.R": 2,
                   "audio.mudo_medido": 10, "mic.clip": 2, "mic.closed": 1, "widget.reset": 1,
                   "menu.Sim": 1, "sound.fx_op": 4, "timer.fired": 20},
        "curta": {"act": 1, "drop.snap": 1, "pixel.fill": 1, "pixel.stroke": 1, "pixel.gradiente": 1,
                  "when.sobrecarga": 1, "hover.enter": 4, "hover.exit": 4, "change.semente": 1,
                  "drop.trash": 1},
        "parado": {"twin.read": 50},
    }
    checks = {
        "sessao": ("link.generator_a", "link.state_power", "link.constructor_formula",
                   "link.unlink_freezes", "group.formula_live", "hud.fresh", "geom.intersections",
                   "geom.intersection_chord", "geom.closest_point_circle", "geom.distance",
                   "geom.heading", "geom.middle_point", "geom.nearest", "query.raycast_first",
                   "query.point", "collider.test_collision_hit", "move_along.on_track",
                   "audio.amp_db_closed_form", "audio.muted_silences", "mic.null_level",
                   "grid.cell_at_matches", "hover.alternates", "hover.pointer_inside",
                   "pixel.fill_colour", "pixel.stroke_leaves_inside", "pixel.stroke_on_edge",
                   "pixel.gradient_runs", "pixel.hidden_is_background", "textinput.swallows_keys",
                   "act.column_restored", "remap.linear", "dropdown.index", "bake.tail_kept",
                   "when.sobrecarga.edges", "change.potencia.fires", "sound.effects_stack"),
    }
    claims = ("State", "Attribute", "when", "on_change", "Slider", "CheckBox", "DropDown",
              "TextInput", "Button", "Menu", "click", "drop_by", "Box", "Grid", "Collider",
              "test_collision", "intersections", "intersection", "closest_point", "distance",
              "heading", "nearest", "middle_point", "Track", "Anchor", "Line", "RegularPolygon",
              "Fill", "Stroke", "Paint", "Gradient", "Texture", "Sound", "play_sound", "LowPass",
              "HighPass", "Echo", "Reverb", "Distortion", "Wavefold", "amp_db", "audio",
              "Microphone", "remap", "Wallpaper", "ui")
    return GameSpec("oficina", {"sessao": sessao, "curta": curta, "parado": parado}, probes,
                    reach, checks, claims)


CANTEIRO_S = 32.0     # one Patio round, HUD included, plus the shed (seconds of game time)


def canteiro_scenario(hz: float = 60.0, *, rounds: int = 1, seconds: float = CANTEIRO_S,
                      seed: int = 1, params: Optional[Dict[str, Any]] = None, **pilot) -> Scenario:
    """The pilot's session at ``hz`` frames per second: the same game time at
    every pacing (Testing Design, "What the game-behaviour probes taught", 3)."""
    p = {"rounds": rounds}
    p.update(params or {})
    return Scenario(params=p, seed=seed, dt=1.0 / hz,
                    steps=[drive(lambda: CanteiroPilot(**pilot), int(round(seconds * rounds * hz)))])


def _canteiro() -> GameSpec:
    curta = canteiro_scenario(60.0)
    parado = Scenario(params={}, seed=3,
                      steps=[wait(30), key("RIGHT", 90), wait(20), click(520, 330), wait(40),
                             key("SPACE", 2), wait(60)])
    probes = {
        "ledger": lambda p: p.G.digest(),
        "x": lambda p: p.PILOTO.get("x"),
        "y": lambda p: p.PILOTO.get("y"),
        "pontos": lambda p: p.st.pontos,
        "pan_x": lambda p: p.canvas.pan_x,
    }
    walk = {"act": 2, "fim": 1, "espinho.enter": 1, "espinho.untag": 1, "espinho.exit": 1,
            "rampa.parado": 20, "carona.lado": 30, "carona.sobe": 60, "carona.descendo": 20,
            "elevador.stay": 60, "tecla.space_com_shift": 1, "tecla.correndo": 10,
            "tecla.up_no_ato_novo": 1, "estaca": 2}
    stations = {"bolha.estourou": 10, "bolha.separou": 10, "tijolo.quebrado": 5,
                "tijolo.quique": 5, "torre.disparo": 20, "balanca.contou": 20, "pesos.soltos": 5,
                "carga.medida": 100, "ponteiro.medido": 200, "pedra.medida": 20, "bate.volta": 5,
                "bate.medido": 100}
    hud = {"drop.caixote": 1, "drop.lixeira": 1, "jato.quebrou_segurado": 1, "jato.hover_exit": 2,
           "jato.consertado": 1, "jato.fora_medido": 2, "nome.enviado": 1, "nota.medida": 10,
           "widget.aperto_medido": 10}
    reach = {"curta": {**walk, **stations, **hud},
             "parado": {"bolha.estourou": 1, "torre.disparo": 3}}
    checks = {
        "curta": ("rider.carried_x", "lift.contact_open", "lift.foot_on_top", "ramp.idle_no_creep",
                  "static.shelf_holds", "static.thin_wall_holds", "settle.pair_keeps_sides",
                  "settle.pair_separates", "settle.ball_in_a_wall_leaves_into_the_room",
                  "breakout.bounce_off_destroyed", "breakout.ball_inside", "spikes.exit_on_untag",
                  "exit.every_rule_runs", "collide.every_enter_rule_runs", "closure.owned_by_actor",
                  "button.destroyed_writes_off", "mouse.widget_press_hidden",
                  "textinput.repeat_stays_with_its_press", "hover.alternates",
                  "hover.leaves_with_the_cursor", "drop.world_pos",
                  "drop.ui_pos", "clone.center_places", "paint.at_pointer", "paint.only_on_world",
                  "mouse.world_under_camera", "mouse.sampled_once", "keys.keyp_twin",
                  "keys.once_twin", "timer.fire_frame", "act.objects_removed", "act.camera_restored",
                  "change.pontos.fires", "hud.fresh"),
    }
    claims = ("Act", "change_act", "Rect", "Circle", "Text", "Slider", "Button", "TextInput",
              "resolve", "STATIC", "collide", "collide_stay", "collide_exit", "collide_with",
              "keyp", "mouse", "Mouse", "chase", "on_change", "after", "every", "Vec2", "Color")
    return GameSpec("canteiro", {"curta": curta, "parado": parado}, probes, reach, checks, claims,
                    os_level=True)


GAMES: Dict[str, Callable[[], GameSpec]] = {"armada": _armada, "caverna": _caverna,
                                            "oficina": _oficina, "canteiro": _canteiro}


def spec(game: str) -> GameSpec:
    return GAMES[game]()


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

@dataclass
class GameResult:
    game: str
    scenario: str
    report: Dict[str, Any]
    trace: Any
    leftovers: Dict[str, Any]
    zombies: List[Any]
    warnings: List[str]
    pilot_done: List[str]


class GameRun(ProgramRun):
    """``ProgramRun`` plus the game-only steps (a click on a SpriteButton the
    game names in ``BOTOES``) and, with ``os_level``, the OS side of input as a
    real window has it (``tests/input_driver.py`` does the same for system
    tests): a window, so the framework samples the cursor every frame (a
    camera that moves under a still cursor moves ``mouse``; a cursor that
    leaves with no motion event ends widget hover); ``glfw.get_key`` /
    ``get_mouse_button`` report what is held; a key goes in with the modifier
    bits of the modifiers held (Shift held: ``MOD_SHIFT``); ``key_repeat``
    sends an OS auto-repeat; ``place`` puts the cursor somewhere with no
    motion callback."""

    os_level = False
    _MODS = {"LEFT_SHIFT": 0x0001, "RIGHT_SHIFT": 0x0001, "LEFT_CONTROL": 0x0002,
             "RIGHT_CONTROL": 0x0002, "LEFT_ALT": 0x0004, "RIGHT_ALT": 0x0004,
             "LEFT_SUPER": 0x0008, "RIGHT_SUPER": 0x0008}

    def start(self) -> None:
        super().start()
        if not self.os_level:
            return
        import glfw
        from unittest import mock
        import scena.orchestration as orch
        self._held_keys: set = set()
        self._held_buttons: set = set()
        for attr, fn in (("get_key", lambda _w, k: glfw.PRESS if k in self._held_keys else glfw.RELEASE),
                         ("get_mouse_button",
                          lambda _w, b: glfw.PRESS if b in self._held_buttons else glfw.RELEASE)):
            p = mock.patch.object(orch.glfw, attr, new=fn)
            p.start()
            self._patches.append(p)
        fw = self.world.fw
        self._window_before = fw._window
        fw._window = object()

    def close(self, strict: bool = True) -> None:
        if self.os_level and self.world is not None and hasattr(self, "_window_before"):
            self.world.fw._window = self._window_before
            del self._window_before
        super().close(strict=strict)

    def key_repeat(self, name: str) -> None:
        import glfw
        self._pending.append(("key", (name.upper() if len(name) == 1 else name, glfw.REPEAT)))

    def place(self, x: float, y: float) -> None:
        self._pending.append(("place", (x, y)))

    def _deliver(self, *a) -> None:
        if not self.os_level:
            return super()._deliver(*a)
        import glfw
        from program_support import _KEY_CODES
        pending, self._pending = self._pending, []
        fw = self.world.fw
        for kind, args in pending:
            if kind == "key":
                self.trace.inputs.append((self.frames + 1, f"{kind} {args}"))
                name, action = args
                code = _KEY_CODES[name]
                if action == glfw.PRESS:
                    self._held_keys.add(code)
                elif action == glfw.RELEASE:
                    self._held_keys.discard(code)
                mods = 0
                for held_name, bit in self._MODS.items():
                    if _KEY_CODES.get(held_name) in self._held_keys:
                        mods |= bit
                fw._handle_key(fw._window, code, 0, action, mods)
                if action == glfw.PRESS and len(name) == 1 and name.isalnum():
                    fw._handle_char(fw._window, ord(name.lower()))
            elif kind == "place":
                self.trace.inputs.append((self.frames + 1, f"{kind} {args}"))
                self._cursor[:] = list(self._to_screen(*args))
            else:
                if kind == "button":
                    button, action = args
                    if action == glfw.PRESS:
                        self._held_buttons.add(button)
                    else:
                        self._held_buttons.discard(button)
                self._pending = [(kind, args)]
                super()._deliver(*a)
        self._pending = []

    def play(self, steps):
        rest = []
        for st in steps:
            if st[0] == "click_sprite":
                b = self.view.BOTOES[st[1]]
                self.press(b.center.x, b.center.y)
                self._pstep(1)
                self.release()
                self._pstep(1)
                continue
            super().play([st])


def run_game(game: str, scenario: str, *, params: Optional[Dict[str, Any]] = None,
             dt: Optional[float] = None, probes: Optional[Dict[str, Callable]] = None,
             before_start: Optional[Callable[[ProgramRun], None]] = None,
             scenario_obj: Optional[Scenario] = None) -> GameResult:
    """Run one scenario (``scenario_obj``: an ad-hoc one, named ``scenario``)."""
    sp = spec(game)
    sc = scenario_obj if scenario_obj is not None else sp.scenarios[scenario]
    p = dict(sc.params)
    if params:
        p.update(params)
    run = GameRun(game_path(game), p, probes=sp.probes if probes is None else probes,
                  seed=sc.seed, dt=sc.dt if dt is None else dt)
    run.os_level = sp.os_level
    if before_start is not None:
        before_start(run)
    caught: List[str] = []
    pilots: List[Any] = []
    done: List[str] = []
    report: Dict[str, Any] = {}
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        run.start()
        ok = False
        try:
            run.trace.scenario = scenario
            steps = []
            for st in sc.steps:
                if st[0] == "drive":
                    factory = st[1]

                    def keep(factory=factory):
                        pl = factory()
                        pilots.append(pl)
                        return pl
                    st = ("drive", keep, st[2])
                steps.append(st)
            run.play(steps)
            G = run.ns["G"]
            G.finish()
            report = G.report()
            del G             # nothing of the program may outlive close()
            ok = True
        finally:
            # A pilot (a suspended generator above all) holds the program's
            # objects: drop it before close() takes the census.
            done = list(pilots[0].done) if pilots else []
            for pl in pilots:
                script = getattr(pl, "script", None)
                if script is not None:
                    script.close()
                    pl.script = None
            pilots.clear()
            run.close(strict=ok)
        scena_dir = os.path.join(os.path.dirname(GAMES_DIR), "..", "scena")
        scena_dir = os.path.normcase(os.path.abspath(scena_dir))
        caught = [f"{x.category.__name__}: {x.message}" for x in w
                  if "SCENA" in str(x.message)
                  or os.path.normcase(os.path.abspath(x.filename)).startswith(scena_dir)]
    return GameResult(game, scenario, report, run.trace, run.leftovers(), zombies(),
                      caught, done)


def _warning_unexpected(msg: str) -> bool:
    """Every warning the engine raised (from scena/, or a SCENA WARNING) is
    unexpected unless ``WARN_OK`` names it with a reason."""
    return not any(k in msg for k in WARN_OK)


def problems(result: GameResult, *, reach: Optional[Dict[str, int]] = None,
             checks: Sequence[str] = ()) -> List[str]:
    """Everything wrong with a run, as lines (empty = clean)."""
    out: List[str] = []
    rep = result.report
    known = {name: why for (g, name), why in KNOWN.items() if g == result.game}
    for f in rep.get("failures", []):
        if f["name"] in known:
            continue
        out.append(f"FAIL {f['name']} @frame {f['frame']} t={f['t']} [{f['scope']}] {f['msg']} {f['ctx'] or ''}")
        if len(out) >= 12:
            out.append(f"... {rep['n_failures']} failures in all: {rep['fails']}")
            break
    for name, need in (reach or {}).items():
        got = rep.get("reach", {}).get(name, 0)
        if got < need:
            out.append(f"REACH {name}: {got} < {need}")
    evals = rep.get("evals", {})
    for name in checks:
        if not evals.get(name):
            out.append(f"VACUOUS check {name!r} never ran")
    for frame, probe, err in result.trace.errors()[:5]:
        out.append(f"PROBE {probe} @frame {frame}: {err}")
    if result.leftovers:
        out.append(f"LEFTOVERS {result.leftovers}")
    if result.zombies:
        out.append(f"ZOMBIES {[(h, type(o).__name__) for h, o in result.zombies[:5]]}")
    bad = [m for m in result.warnings if _warning_unexpected(m)]
    if bad:
        out.append(f"WARNINGS {bad[:3]}")
    return out


def assert_game_clean(tc, result: GameResult) -> None:
    sp = spec(result.game)
    msgs = problems(result, reach=sp.reach.get(result.scenario), checks=sp.checks.get(result.scenario, ()))
    if msgs:
        tc.fail(f"{result.game}/{result.scenario} ({result.report.get('frames')} frames, pilot "
                f"{result.pilot_done}):\n  " + "\n  ".join(msgs))


def known_still_fail(game: str, results: Sequence[GameResult]) -> List[str]:
    """KNOWN entries of ``game`` that no run in ``results`` hit any more."""
    seen = {f["name"] for r in results for f in r.report.get("failures", [])}
    return [name for (g, name) in KNOWN if g == game and name not in seen]


# ---------------------------------------------------------------------------
# Canaries: put a known bug back and require the game's models to see it
# ---------------------------------------------------------------------------

def run_patched(game: str, scenario: str, patches: Sequence[Tuple[Any, str, Any]]) -> GameResult:
    """``run_game`` with ``mock.patch.object(target, attr, new)`` for each patch,
    on empty look intern caches (``hypothesis_support.fresh_interns``)."""
    import contextlib
    from unittest import mock
    from hypothesis_support import fresh_interns
    with contextlib.ExitStack() as stack:
        stack.enter_context(fresh_interns())
        for target, attr, new in patches:
            stack.enter_context(mock.patch.object(target, attr, new))
        return run_game(game, scenario)


def assert_canary(tc, game: str, scenario: str, patches, expect: Sequence[str]) -> None:
    """The planted bug must make one of ``expect`` fail (a check name, or
    ``reach:<name>`` for a reach minimum that the bug starves)."""
    r = run_patched(game, scenario, patches)
    failed = set(r.report.get("fails", {}))
    sp = spec(game)
    starved = {f"reach:{k}" for k, need in (sp.reach.get(scenario) or {}).items()
               if r.report.get("reach", {}).get(k, 0) < need}
    hit = (failed | starved) & set(expect)
    tc.assertTrue(hit, f"canary not caught: expected one of {sorted(expect)}; the run failed "
                       f"{sorted(failed)[:10]} and starved {sorted(starved)[:10]}")
