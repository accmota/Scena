# harness: cwd=examples/media
"""Corrida — a benchmark game (scripts/bench/games/). Not an example, not a tutorial.

An endless runner, written the way an author writes Scena, to measure a world
that is built and torn down all the time: an ``Endless`` builder lays the
track slot by slot ahead of the camera (ground tiles, gaps, a floating
platform, crates, coins, a patrolling robot, now and then a turret that
shoots) and releases slots far behind; three parallax ``Endless`` bands scroll
behind it. The hero runs on its own at ``speed`` and jumps gaps and crates.
After a few minutes the world coordinates are large (x ≈ 10⁵ … 10⁶).

Stresses: spawn / destroy churn (build cost, collider enroll and release,
partner caches, the registry's holes), ``refill_after_tick``, parallax draw,
large coordinates, and drift over a long run. Time it with
``python scripts/bench/game_bench.py scripts/bench/games/corrida.py``.

PARAMS: speed (world units per second, default 600), seed, auto (autopilot,
default True; UP jumps).
"""
import random

from scena import *

PARAMS = globals().get("PARAMS", {})
SPEED = float(PARAMS.get("speed", 600))
AUTO = bool(PARAMS.get("auto", True))
SEED = int(PARAMS.get("seed", 5))
random.seed(SEED)

W, H = 1000, 600
T = 64
SLOT = 10 * T
GRAVIDADE = 2400
PULO = 980

init(width=W, height=H, title="Corrida")
SkyGradient("day")

NINJA = Sheet(anchor="bottom", pixel_size=0.2)
NINJA.strip("correndo", "ninja/Run__*.png", fps=14)
NINJA.strip("pulando", "ninja/Jump__*.png", fps=10)
ROBO = Sheet(anchor="bottom", pixel_size=0.14)
ROBO.strip("andando", "robot/Run (*).png", fps=12)

st.moedas = 0
st.golpes = 0
st.metros = 0

placar = Text("", top_left=(16, H - 12), font_size=22, color="navy", layer="ui")
placar["text"] @= lambda: f"{st.metros} m   Moedas {st.moedas}   Golpes {st.golpes}"


class Moeda(Sprite, source="k-rolling-ball/star.png", height=28, group="moeda"):
    pass


class Robo(Sprite, source=ROBO, group="robo", hitbox_shape="rect", hitbox_anchor="bottom"):
    def setup(self):
        self.vel = Vec2(-60, 0)
        self.play("andando")

    def on_update(self, dt):
        if not self.floor_below(dx=24 if self.vel.x > 0 else -24, group="chao"):
            self.vel.x = -self.vel.x
        self.flip_x = self.vel.x < 0
        self.move_by(self.vel.x * dt, 0)


class Bala(Sprite, source="space/laserRed01.png", height=22, art_angle=90, group="bala"):
    def setup(self):
        self.angle = 180

    def on_update(self, dt):
        self.move_by(-420 * dt, 0)


class Torre(Sprite, source="space/spaceBuilding_003.png", height=70, group="torre"):
    def setup(self):
        self.every(1.2, self.atirar)

    def atirar(self):
        Bala(center=(self.center.x - 30, self.center.y + 10), layer="pista")


def fatia(slot):
    """One slot of track: everything here is a function of ``slot``."""
    r = slot.rng
    pecas = []
    buraco = slot.i > 2 and r.random() < 0.35
    inicio_buraco = r.randint(3, 6) if buraco else 99
    largura_buraco = r.choice((2, 3))
    for k in range(10):
        if inicio_buraco <= k < inicio_buraco + largura_buraco:
            continue
        x = slot.left + k * T + T / 2
        for j, arte in ((0, "tilesets/Tiles/5.png"), (1, "tilesets/Tiles/2.png")):
            p = Sprite(arte, size=T, center=(x, j * T + T / 2), group="chao")
            p.mass = STATIC
            pecas.append(p)
    if r.random() < 0.5:
        k0 = r.randint(1, 5)
        for k in range(3):
            p = Sprite("tilesets/Tiles/14.png", size=T, center=(slot.left + (k0 + k) * T + T / 2, 4 * T),
                       group="plataforma")
            p.mass = STATIC
            pecas.append(p)
            pecas.append(Moeda(center=(slot.left + (k0 + k) * T + T / 2, 5 * T)))
    for k in range(r.randint(2, 6)):
        pecas.append(Moeda(center=(slot.left + r.uniform(20, SLOT - 20), 2 * T + 40)))
    if slot.i > 2 and not buraco and r.random() < 0.4:
        c = Sprite("tilesets/Object/Crate.png", size=T * 0.8,
                   center=(slot.left + r.randint(1, 8) * T + T / 2, 2 * T + T * 0.4), group="chao")
        c.mass = STATIC
        pecas.append(c)
    if slot.i > 2 and r.random() < 0.5:
        pecas.append(Robo(center=(slot.left + T * (1 if buraco and inicio_buraco > 4 else 8), 2 * T + 2)))
    if slot.i > 3 and slot.i % 3 == 0:
        pecas.append(Torre(center=(slot.left + 9 * T, 2 * T + 35)))
    return pecas


class Heroi(Sprite, source=NINJA, group="heroi", hitbox_shape="rect", hitbox_anchor="bottom"):
    def setup(self):
        self.vel = Vec2(SPEED, 0)
        self.play("correndo")

    def on_update(self, dt):
        no_chao = "bottom" in self.touching_sides
        pular = keyp.once("UP")
        if AUTO:
            olhar = max(48.0, SPEED * 0.08)
            sem_chao = not self.floor_below(dx=olhar, group=["chao", "plataforma"])
            pular = pular or (no_chao and (sem_chao or "right" in self.touching_sides))
        if pular and no_chao:
            self.vel.y = PULO
        self.vel.x = SPEED
        self.vel.y -= GRAVIDADE * dt
        self.move_by(self.vel.x * dt, self.vel.y * dt)
        if no_chao and self.vel.y < 0:
            self.vel.y = 0
        if self.center.y < -150:
            self.center = (self.center.x + 3 * T, 5 * T)
            self.vel.y = 0
        self.play("correndo" if no_chao else "pulando")
        st.metros = int(self.center.x / 100)


@collide("heroi", "moeda")
def pegou(h, moeda, info):
    moeda.destroy()
    st.moedas += 1


@collide("heroi", "robo")
@collide("heroi", "bala")
def bateu(h, outro, info):
    if h.ready("golpe", 0.6):
        st.golpes += 1
        h.blink(0.4)


@leave_playfield("bala")
def saiu(b):
    b.destroy()


heroi = None


class Pista(Act):
    def setup(self):
        global heroi
        canvas.layers.create("montes", pan_response=0.2, below="default")
        canvas.layers.create("morros", pan_response=0.45, below="default")
        canvas.layers.create("mato", pan_response=0.7, below="default")
        canvas.layers.create("pista", below="default")
        Endless("montes", "backgrounds/mountains/mountains2.png", height=360, bottom=40)
        Endless("morros", "backgrounds/mountains/mountains3.png", height=300, bottom=20)
        Endless("mato", "backgrounds/mountains/mountains4.png", height=180, bottom=0)
        Endless("pista", fatia, step=SLOT, start=0, seed=SEED)
        heroi = Heroi(center=(2 * T, 2 * T + 4))
        resolve("heroi", "chao")
        resolve("heroi", "plataforma", only=lambda c: c.side == "bottom")
        resolve("robo", "chao")

    def on_update(self, dt):
        if heroi is None:
            return
        canvas.pan_to(heroi.center.x + 250, H / 2)
        canvas.playfield.set(canvas.game_view.outset(250))


run(Pista)
