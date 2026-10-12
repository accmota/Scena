# harness: cwd=examples/media
"""Horda — a benchmark game (scripts/bench/games/). Not an example, not a tutorial.

A top-down arena survival shooter, written the way an author writes Scena, to
measure a crowd: hundreds of animated enemies that steer at the hero in
``on_update``, push each other apart (``resolve("inimigo", "inimigo")``) and
against stone pillars, bullets with ``@collide``, gems that fly to the hero,
a spawner that keeps the crowd full (spawn / destroy churn) and a per-enemy
``after`` that re-arms. The camera chases the hero over an arena larger than
the window.

Stresses: broad-phase pools, resolve, proxy refresh, narrow phase, the
process tick per actor, spawn cost. Time it with
``python scripts/bench/game_bench.py scripts/bench/games/horda.py``.

PARAMS: n (enemies kept alive, default 150), seed, auto (autopilot, default
True; the arrows and SPACE take over).
"""
import math
import random

from scena import *

PARAMS = globals().get("PARAMS", {})
N = int(PARAMS.get("n", 150))
AUTO = bool(PARAMS.get("auto", True))
random.seed(int(PARAMS.get("seed", 7)))

W, H = 1000, 750
ARENA_W, ARENA_H = 2600, 1900
init(width=W, height=H, title="Horda")
Wallpaper("k-textures/floor_stone_pattern.png", fit="tile", tile_size=(256, 256), pan_response=1.0)
canvas.playfield.set(Box(center=(ARENA_W / 2, ARENA_H / 2), width=ARENA_W, height=ARENA_H))

ROBO = Sheet(anchor="bottom", pixel_size=0.09)
ROBO.strip("andando", "robot/Run (*).png", fps=12)

st.pontos = 0
st.gemas = 0
st.vida = 100
st.inimigos = 0

placar = Text("", top_left=(16, H - 12), font_size=22, color="white", layer="ui")
placar["text"] @= lambda: f"Pontos {st.pontos}   Gemas {st.gemas}   Vida {st.vida}"
contagem = Text("", top_right=(W - 16, H - 12), font_size=18, color="light gray", layer="ui")
contagem["text"] @= lambda: f"inimigos {st.inimigos}"


def borda_aleatoria():
    """A spawn point on the arena's rim, away from the hero."""
    lado = random.randrange(4)
    if lado == 0:
        return (random.uniform(60, ARENA_W - 60), 60)
    if lado == 1:
        return (random.uniform(60, ARENA_W - 60), ARENA_H - 60)
    if lado == 2:
        return (60, random.uniform(60, ARENA_H - 60))
    return (ARENA_W - 60, random.uniform(60, ARENA_H - 60))


class Tiro(Sprite, source="space/laserBlue03.png", height=26, art_angle=90, group="tiro"):
    def on_update(self, dt):
        self.move_by(angle=self.angle, distance=900 * dt)


class Gema(Sprite, source="space/pill_green.png", height=18, group="gema", hitbox_shape="circle"):
    def on_update(self, dt):
        if distance(self, heroi) < 160:
            self.move_by(angle=heading(self, heroi), distance=420 * dt)


class Inimigo(Sprite, source=ROBO, group="inimigo", hitbox_shape="circle"):
    def setup(self):
        self.vida = 2
        self.velocidade = random.uniform(70, 110)
        self.play("andando")
        self.after(random.uniform(1.0, 3.0), self.mudar_passo)

    def mudar_passo(self):
        self.velocidade = random.uniform(60, 150)
        self.after(random.uniform(1.0, 3.0), self.mudar_passo)

    def on_update(self, dt):
        rumo = heading(self, heroi)
        self.move_by(angle=rumo, distance=self.velocidade * dt)
        self.flip_x = heroi.center.x < self.center.x

    def atingido(self):
        self.vida -= 1
        if self.vida > 0:
            self.flash()
            return
        st.pontos += 10
        canvas.hit_at(self, style="disc")
        if chance(0.4):
            Gema(center=self.center)
        self.destroy()


class Heroi(Sprite, source="space/playerShip1_red.png", height=46, art_angle=90, group="heroi",
            hitbox_shape="circle"):
    def setup(self):
        self.t = 0.0

    def on_update(self, dt):
        self.t += dt
        vx = keyp("RIGHT") - keyp("LEFT")
        vy = keyp("UP") - keyp("DOWN")
        if AUTO and not (vx or vy):
            # Autopilot: a slow Lissajous loop around the arena's middle.
            alvo = (ARENA_W / 2 + 700 * math.sin(self.t * 0.31),
                    ARENA_H / 2 + 500 * math.sin(self.t * 0.47))
            d = distance(self, alvo)
            if d > 4:
                self.move_by(angle=heading(self, alvo), distance=min(d, 300 * dt))
        else:
            self.move_by(vx * 320 * dt, vy * 320 * dt)
        atirar = keyp("SPACE") or AUTO
        if atirar and ready("tiro", 0.07):
            alvo = group["inimigo"].nearest(self, within=650)
            if alvo is not None:
                rumo = heading(self, alvo)
                self.angle = rumo
                t = Tiro(center=self.center)
                t.angle = rumo


heroi = None


def repor():
    """Keep the crowd at N: a few new enemies on the rim each tick."""
    falta = N - group["inimigo"].count
    for _ in range(min(falta, max(4, N // 30))):
        Inimigo(center=borda_aleatoria())


@collide("tiro", "inimigo")
def acertou(tiro, inimigo, info):
    tiro.destroy()
    inimigo.atingido()


@collide("tiro", "pilar")
def bateu(tiro, pilar, info):
    tiro.destroy()


@collide("heroi", "gema")
def pegou(h, gema, info):
    gema.destroy()
    st.gemas += 1


@collide("inimigo", "heroi")
def mordeu(inimigo, h, info):
    if h.ready("dano", 0.5):
        st.vida = max(0, st.vida - 1)
        h.blink(0.3)


@leave_playfield("tiro", "gema")
def saiu(obj):
    obj.destroy()


class Arena(Act):
    def setup(self):
        global heroi
        # Pillars: a loose grid of stone blocks, plus the four walls.
        for i in range(6):
            for j in range(4):
                x = 300 + i * 400 + random.uniform(-60, 60)
                y = 280 + j * 440 + random.uniform(-60, 60)
                Rect(center=(x, y), width=random.choice((60, 90, 120)), height=random.choice((60, 90)),
                     color="gray", group="pilar")
        for (cx, cy, w, h) in ((ARENA_W / 2, -20, ARENA_W, 40), (ARENA_W / 2, ARENA_H + 20, ARENA_W, 40),
                               (-20, ARENA_H / 2, 40, ARENA_H), (ARENA_W + 20, ARENA_H / 2, 40, ARENA_H)):
            Rect(center=(cx, cy), width=w, height=h, color="dim gray", group="pilar")
        group["pilar"].mass = STATIC
        heroi = Heroi(center=(ARENA_W / 2, ARENA_H / 2))
        resolve("inimigo", "inimigo")
        resolve("inimigo", "pilar")
        resolve("heroi", "pilar")
        while group["inimigo"].count < N:
            Inimigo(center=(random.uniform(80, ARENA_W - 80), random.uniform(80, ARENA_H - 80)))
        every(0.1, repor)
        canvas.pan_to(heroi.center)

    def on_update(self, dt):
        st.inimigos = group["inimigo"].count
        if heroi is None:
            return
        olhar = (canvas.pan_x, canvas.pan_y)
        x = min(max(heroi.center.x, W / 2), ARENA_W - W / 2)
        y = min(max(heroi.center.y, H / 2), ARENA_H - H / 2)
        canvas.pan_to(chase(olhar, (x, y), rate=6))


run(Arena)
