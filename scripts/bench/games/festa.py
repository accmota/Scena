# harness: cwd=examples/media
"""Festa — a benchmark game (scripts/bench/games/). Not an example, not a tutorial.

A bullet-hell boss fight, written the way an author writes Scena, to measure
what is drawn and what is linked: the boss sweeps a figure-eight and fires
rings and spirals of glowing shapes (``Neon`` and ``.glow`` looks), every shot
grows in with a tween, asteroids spin and pulse, a HUD of about forty
``@=`` labels reads State cells, ``@when`` raises the level, the scene goes
through Bloom and a Vignette over stars and a nebula, the boss burns with
``Fire`` and an ``Orb`` circles the hero, and hits shake the camera.

Stresses: draw per object kind, look batching, the flush and the reactive
graph, the scheduler (tweens, ``every``), posts. Time it with
``python scripts/bench/game_bench.py scripts/bench/games/festa.py``.

PARAMS: n (shots alive, about; default 300), seed, auto (autopilot, default
True; the arrows and SPACE take over).
"""
import math
import random

from scena import *

PARAMS = globals().get("PARAMS", {})
N = int(PARAMS.get("n", 300))
AUTO = bool(PARAMS.get("auto", True))
random.seed(int(PARAMS.get("seed", 3)))

W, H = 1000, 750
VIDA_TIRO = 3.0                      # seconds a shot lives (it leaves the screen)
init(width=W, height=H, title="Festa")
SkyGradient("night")
Stars(pan_response=0.0, scroll=(0.0, -30.0))
Bloom(intensity=0.35)
Vignette(amount=0.5)

CORES = ("cyan", "magenta", "gold", "lime", "orange")
st.nivel = 1
st.acertos = 0
st.danos = 0
st.disparos = 0
CONTADORES = []
for k in range(36):
    c = State(name=f"c{k}")
    c.n = 0
    CONTADORES.append(c)

# A HUD of about forty linked labels: a grid of counters plus the header.
cabecalho = Text("", top_left=(16, H - 10), font_size=22, color="white", layer="ui")
cabecalho["text"] @= lambda: f"Nível {st.nivel}   Acertos {st.acertos}   Danos {st.danos}"
disparos = Text("", top_right=(W - 16, H - 10), font_size=18, color="light gray", layer="ui")
disparos["text"] @= lambda: f"disparos {st.disparos}"
for k in range(36):
    col, lin = k % 12, k // 12
    t = Text("", top_left=(16 + col * 80, 70 - lin * 20), font_size=13, color="gray", layer="ui")
    t["text"] @= lambda k=k, c=CONTADORES[k]: f"c{k}: {c.n}"


@when(lambda: st.acertos >= 40 * st.nivel)
def subir_nivel():
    st.nivel += 1
    canvas.flash()


class Disparo(Circle):
    def setup(self):
        self.idade = 0.0
        self.scale_to(1.0, time=0.25)

    def on_update(self, dt):
        self.idade += dt
        self.move_by(angle=self.rumo, distance=self.rapidez * dt)
        if self.idade > VIDA_TIRO:
            self.destroy()


def disparar(x, y, rumo, vel, cor, neon):
    d = Disparo(center=(x, y), radius=7, color=cor, group="disparo")
    d.rumo = rumo
    d.rapidez = vel
    d.scale = 0.3
    if neon:
        d.visual = Neon(cor)
    else:
        d.glow = cor
    st.disparos += 1
    return d


class Chefe(Sprite, source="space/ufoYellow.png", height=110, group="chefe"):
    def setup(self):
        self.giro = 0.0
        self.move_along(Track.eight(width=560, height=120), time=8.0, loops="forever")
        self.fogo = Fire(center=lambda: self.center - (0, 50), width=30, style="plume")
        cadencia = VIDA_TIRO / max(1.0, N / 24.0)
        self.every(cadencia, self.anel)
        self.every(cadencia / 3.0, self.espiral)

    def anel(self):
        cor = random.choice(CORES)
        for k in range(16):
            disparar(self.center.x, self.center.y, k * 22.5 + self.giro, 210, cor, neon=k % 2 == 0)

    def espiral(self):
        self.giro += 13
        for k in range(3):
            disparar(self.center.x, self.center.y, self.giro + k * 120, 260, "white", neon=False)

    def on_update(self, dt):
        self.rotate_by(40 * dt)


class Heroi(Sprite, source="space/playerShip1_red.png", height=44, art_angle=90, group="heroi",
            hitbox_shape="circle"):
    def setup(self):
        self.t = 0.0
        self.dor = self.add_hitbox(group="dor", scale=0.4)
        Orb(center=lambda: self.center + vec_from_angle(clock.time * 180, length=46), radius=10)

    def on_update(self, dt):
        self.t += dt
        vx = keyp("RIGHT") - keyp("LEFT")
        if AUTO and not vx:
            alvo = W / 2 + 380 * math.sin(self.t * 0.9) * math.cos(self.t * 0.23)
            self.move_by(max(-360 * dt, min(360 * dt, alvo - self.center.x)), 0)
        else:
            self.move_by(vx * 360 * dt, 0)
        if (keyp("SPACE") or AUTO) and ready("laser", 0.09):
            Laserzinho(center=(self.center.x, self.center.y + 30))


class Laserzinho(Rect):
    def __init__(self, **kw):
        super().__init__(width=4, height=22, color="cyan", group="laser", **kw)

    def setup(self):
        self.glow = "cyan"

    def on_update(self, dt):
        self.move_by(0, 700 * dt)
        if self.center.y > H + 40:
            self.destroy()


class Asteroide(Sprite, source="space/meteorBrown_big3.png", group="asteroide"):
    def setup(self):
        self.giro = random.uniform(-90, 90)
        self.scale_to(random.uniform(1.1, 1.4), time=random.uniform(0.8, 1.6), loops="forever",
                      yoyo=True)

    def on_update(self, dt):
        self.rotate_by(self.giro * dt)


@collide("laser", "chefe")
def acertou(laser, chefe, info):
    laser.destroy()
    st.acertos += 1
    CONTADORES[st.acertos % 36].n += 1
    canvas.hit_at(info, style="disc")


@collide("disparo", "dor")
def ferido(disparo, heroi, info):
    disparo.destroy()
    if heroi.ready("dano", 0.4):
        st.danos += 1
        heroi.blink(0.3)
        canvas.shake(3)


class Arena(Act):
    def setup(self):
        Chefe(center=(W / 2, H - 170))
        Heroi(center=(W / 2, 90))
        for k in range(40):
            Asteroide(height=random.uniform(24, 60),
                      center=(random.uniform(40, W - 40), random.uniform(160, H - 60)))


run(Arena)
