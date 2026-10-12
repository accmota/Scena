# harness: cwd=examples/media
"""Mundo — a benchmark game (scripts/bench/games/). Not an example, not a tutorial.

A long tile platformer, written the way an author writes Scena, to measure a
big static world: a generated level of tile Sprites (STATIC ground and
one-way platforms with ``only=``), robots that patrol with ``floor_below``,
lifts on ``move_along``, coins that pulse with a tween, turrets that watch
the hero with ``raycast``, bombs that look around with ``query_circle``, a
parallax layer, and a camera that follows the hero across the whole level.
Almost all of the world is off screen at any time.

Stresses: the draw walk with most objects off screen, ``cull_offscreen``,
static proxies, queries, resolve against many static partners. Time it with
``python scripts/bench/game_bench.py scripts/bench/games/mundo.py``.

PARAMS: tiles (about how many tiles the level has, default 1500), robots
(default 20), seed, auto (autopilot, default True; the arrows take over).
"""
import math
import random

from scena import *

PARAMS = globals().get("PARAMS", {})
TILES = int(PARAMS.get("tiles", 1500))
ROBOTS = int(PARAMS.get("robots", 20))
AUTO = bool(PARAMS.get("auto", True))
random.seed(int(PARAMS.get("seed", 11)))

W, H = 1000, 750
T = 64                      # tile size (world units)
GRAVIDADE = 2200
init(width=W, height=H, title="Mundo")
Wallpaper("tilesets/BG/BG.png", fit="tile", tile_size=(1000, 750), tile_mode="mirror", pan_response=0.1)
canvas.layers.create("longe", pan_response=0.5, below="default")

NINJA = Sheet(anchor="bottom", pixel_size=0.2)
NINJA.strip("parado", "ninja/Idle__*.png", fps=8)
NINJA.strip("correndo", "ninja/Run__*.png", fps=12)
NINJA.strip("pulando", "ninja/Jump__*.png", fps=10)
ROBO = Sheet(anchor="bottom", pixel_size=0.16)
ROBO.strip("andando", "robot/Run (*).png", fps=12)

st.moedas = 0
st.alertas = 0
st.descer = False

placar = Text("", top_left=(16, H - 12), font_size=22, color="dark green", layer="ui")
placar["text"] @= lambda: f"Moedas {st.moedas}   Alertas {st.alertas}"


# --- the level: columns of ground with gaps, platforms above ---------------

def gerar():
    """Plan the level as plain data: ground columns, platform runs, spots."""
    colunas = []            # (x index, height in tiles) — 0 means a gap
    plataformas = []        # (x index, y index, length)
    # Ground: 2-3 tiles per column; every tile of a column is a Sprite.
    n_colunas = max(40, int(TILES / 2.6))
    altura = 2
    i = 0
    while i < n_colunas:
        if i > 8 and random.random() < 0.07:
            for _ in range(random.choice((2, 3))):
                colunas.append((i, 0))
                i += 1
            continue
        if random.random() < 0.12:
            altura = max(1, min(4, altura + random.choice((-1, 1))))
        colunas.append((i, altura))
        i += 1
    for k in range(0, n_colunas - 8, 7):
        if random.random() < 0.75:
            plataformas.append((k + random.randint(0, 3), random.randint(4, 6), random.randint(3, 5)))
    return colunas, plataformas


COLUNAS, PLATAFORMAS = gerar()
LARGURA = (len(COLUNAS) + 1) * T


def topo(i):
    """World y of the ground top at column i (None in a gap)."""
    if i < 0 or i >= len(COLUNAS):
        return None
    h = COLUNAS[i][1]
    return h * T if h else None


class Moeda(Sprite, source="k-rolling-ball/star.png", height=30, group="moeda"):
    pass


class Robo(Sprite, source=ROBO, group="robo", hitbox_shape="rect", hitbox_anchor="bottom"):
    def setup(self):
        self.vel = Vec2(70 if random.random() < 0.5 else -70, 0)
        self.play("andando")

    def on_update(self, dt):
        if self.vel.x > 0 and not self.floor_below(dx=30, group=["chao", "plataforma"]):
            self.vel.x = -70
        elif self.vel.x < 0 and not self.floor_below(dx=-30, group=["chao", "plataforma"]):
            self.vel.x = 70
        self.flip_x = self.vel.x < 0
        self.vel.y -= GRAVIDADE * dt
        self.move_by(self.vel.x * dt, self.vel.y * dt)
        if "bottom" in self.touching_sides:
            self.vel.y = 0


class Torre(Sprite, source="space/spaceBuilding_003.png", height=60, group="torre"):
    def on_update(self, dt):
        if not self.ready("olhar", 0.1):
            return
        if distance(self, heroi) > 600:
            return
        hit = collision.raycast(self, p2=heroi.center, group=["chao", "heroi"])
        if hit is not None and hit[0] is heroi:
            st.alertas += 1


class Bomba(Sprite, source="space/meteorBrown_big3.png", height=34, group="bomba"):
    def setup(self):
        self.after(random.uniform(1.5, 4.0), self.explodir)

    def explodir(self):
        for alvo in collision.query_circle(self.center, radius=180, group="robo"):
            alvo.flash()
        canvas.hit_at(self, style="disc")
        self.after(random.uniform(1.5, 4.0), self.explodir)


class Heroi(Sprite, source=NINJA, group="heroi", hitbox_shape="rect", hitbox_anchor="bottom"):
    def setup(self):
        self.vel = Vec2(0, 0)
        self.inicio = (self.center.x, self.center.y)

    def on_update(self, dt):
        no_chao = "bottom" in self.touching_sides
        vx = keyp("RIGHT") - keyp("LEFT")
        pular = keyp.once("UP")
        if AUTO and not vx:
            vx = 1
            frente = self.floor_below(dx=48, group=["chao", "plataforma"])
            parede = "right" in self.touching_sides
            pular = pular or (no_chao and (not frente or parede))
        self.vel.x = 300 * vx
        if vx:
            self.flip_x = vx < 0
        if pular and no_chao:
            self.vel.y = 950
        self.vel.y -= GRAVIDADE * dt
        self.move_by(self.vel.x * dt, self.vel.y * dt)
        if no_chao and self.vel.y < 0:
            self.vel.y = 0
        if self.center.x > LARGURA - 3 * T:
            self.center = self.inicio
            self.vel = Vec2(0, 0)
        elif self.center.y < -200:
            # A forgiving fall: drop back in on the next solid ground ahead.
            i = int(self.center.x // T)
            while i < len(COLUNAS) - 2 and not (topo(i) and topo(i + 1)):
                i += 1
            self.center = (i * T + T / 2, (topo(i) or T) + 150)
            self.vel = Vec2(0, 0)
        if not no_chao:
            self.play("pulando")
        elif self.vel.x:
            self.play("correndo")
        else:
            self.play("parado")


@collide("heroi", "moeda")
def pegou(h, moeda, info):
    moeda.destroy()
    st.moedas += 1


heroi = None


class Fase(Act):
    def setup(self):
        global heroi
        for i, h in COLUNAS:
            for j in range(h):
                arte = "tilesets/Tiles/2.png" if j == h - 1 else "tilesets/Tiles/5.png"
                Sprite(arte, size=T, center=(i * T + T / 2, j * T + T / 2), group="chao")
        for (i, j, n) in PLATAFORMAS:
            for k in range(n):
                arte = "tilesets/Tiles/14.png" if 0 < k < n - 1 else (
                    "tilesets/Tiles/13.png" if k == 0 else "tilesets/Tiles/15.png")
                Sprite(arte, size=T, center=((i + k) * T + T / 2, j * T + T / 4),
                       group="plataforma")
        group["chao"].mass = STATIC
        group["plataforma"].mass = STATIC
        for x in range(200, int(LARGURA), 420):
            Sprite("tilesets/Object/Tree_3.png", height=150, center=(x * 0.5 + 100, 260), layer="longe")
        # Coins: a pulse each (one tween per coin).
        n_moedas = 0
        for (i, j, n) in PLATAFORMAS:
            for k in range(n):
                m = Moeda(center=((i + k) * T + T / 2, j * T + T + 30))
                m.scale_to(1.2, time=0.6, loops="forever", yoyo=True)
                n_moedas += 1
        # Lifts: a few rect platforms riding a vertical track.
        for i in range(12, len(COLUNAS) - 4, 37):
            y0 = (topo(i) or T) + 40
            elev = Rect(center=(i * T, y0), width=120, height=18, color="peru", group="plataforma")
            elev.mass = STATIC
            trilho = Track(points=[(i * T, y0), (i * T, y0 + 220)], visible=False)
            elev.move_along(trilho, time=2.5, loops="forever", yoyo=True)
        # Robots and turrets on solid ground, bombs scattered.
        chao_firme = [i for i, h in COLUNAS if h and 2 <= i < len(COLUNAS) - 2
                      and topo(i - 1) == topo(i) == topo(i + 1)]
        random.shuffle(chao_firme)
        for i in chao_firme[:ROBOTS]:
            Robo(center=(i * T + T / 2, topo(i) + 2))
        for i in chao_firme[ROBOTS:ROBOTS + max(4, ROBOTS // 2)]:
            Torre(center=(i * T + T / 2, topo(i) + 30))
        for i in chao_firme[ROBOTS + ROBOTS // 2:ROBOTS + ROBOTS // 2 + max(4, ROBOTS // 2)]:
            Bomba(center=(i * T + T / 2, topo(i) + 17))
        resolve("robo", "chao")
        resolve("robo", "plataforma", only=lambda c: c.side == "bottom")
        heroi = Heroi(center=(3 * T, (topo(3) or 2 * T) + 4))
        resolve("heroi", "chao")
        resolve("heroi", "plataforma", only=lambda c: c.side == "bottom" and not st.descer)
        canvas.playfield.set(Box(center=(LARGURA / 2, H / 2), width=LARGURA, height=3 * H))
        canvas.pan_to(W / 2, H / 2)

    def on_update(self, dt):
        if heroi is None:
            return
        olhar = (canvas.pan_x, canvas.pan_y)
        x, y = deadzone(olhar, heroi.center, size=200)
        x = min(max(x, W / 2), LARGURA - W / 2)
        canvas.pan_to(chase(olhar, (x, max(y, H / 2)), rate=5))


run(Fase)
