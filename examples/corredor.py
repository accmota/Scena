"""Corredor infinito — tutorial 29.

Um robô corre sozinho por uma pista que nunca acaba, cada vez mais rápido.
A pista é montada vaga por vaga por um Endless à frente da câmera e destruída
atrás dela: chão de terra com textura (colunas de quatro cantos), buracos,
moedas, caixas, enfeites e plataformas de madeira e de pedra (textura mais
um visual, de mão única). A altura do chão é uma função do x, para as vagas
emendarem sem degrau; o que fica dentro de cada vaga sai do sorteio dela
(slot.rng). A área de jogo (playfield) anda com a câmera, a corrida acaba
num buraco ou numa caixa, e o ato recomeça. Ao fundo, duas faixas de
silhuetas em camadas que andam menos que o mundo (pan_response).

Controles
---------
  CIMA     pular (só com os pés no chão)
  ESPAÇO   recomeçar, depois do fim da corrida

Uso
---
    python examples/corredor.py
"""

from math import sin
from scena import *

init(width=960, height=540, title="Corredor")
Wallpaper(Gradient("#3d97d6", "#9fd4f0", angle=90))
collision.floor = True

folha = Sheet(anchor="bottom", pixel_size=0.16)
folha.strip("correndo", "robot/Run (*).png", fps=14)
folha.strip("pulando", "robot/Jump (*).png", fps=14)
folha.strip("caindo", "robot/Dead (*).png", fps=20)
cenario = Sheet("backgrounds/kn/bgElements_spritesheet.png", atlas="backgrounds/kn/bgElements_spritesheet.xml")

TERRA = Texture("k-textures/floor_ground_dirt.png", fit="tile", tile_size=64)
MADEIRA = Texture("textures/236.jpg", fit="tile", tile_size=64)
PEDRA = Texture("k-textures/wall_stone.png", fit="tile", tile_size=40)
MOITAS = ["tilesets/Object/Bush (1).png", "tilesets/Object/Bush (3).png", "tilesets/Object/Mushroom_1.png",
          "tilesets/Object/Mushroom_2.png", "tilesets/Object/Sign_2.png"]
SILHUETAS = ["castle.png", "tower.png", "tree01.png", "tree08.png", "tree11.png", "tree12.png", "house_side_tall.png"]


def altura(x):
    return 130 + 55 * sin(x / 400) + 25 * sin(x / 150)


def coluna(x):
    chao = Polygon(points=[(x, 0), (x + 64, 0), (x + 64, altura(x + 64)), (x, altura(x))], group="chao")
    chao.fill = TERRA
    chao.line = TERRA
    chao.mass = STATIC
    grama = Line(p1=(x, altura(x) - 4), p2=(x + 64, altura(x + 64) - 4), color="#6fa124", line_width=16)
    broto = Line(p1=(x, altura(x)), p2=(x + 64, altura(x + 64)), color="#b3d02a", line_width=8)
    return [chao, grama, broto]


def moedas(x, y):
    fila = []
    for k in range(3):
        fila.append(Circle(center=(x - 36 + 36 * k, y), radius=11, visual=Sphere("orange"), group="moeda"))
    return fila


def plataforma(slot, x, y):
    tabua = Rect(center=(x, y), width=128, height=24, group="tabua")
    tabua.mass = STATIC
    if slot.chance(0.5):
        tabua.fill = MADEIRA
        tabua.visual = Extrude(depth=20, angle=270)
    else:
        tabua.fill = PEDRA
        tabua.visual = Ink()
    return tabua


def trecho(slot):
    colunas = 6
    if slot.i > 1 and slot.chance(0.4):
        colunas = 3
    pecas = []
    for k in range(colunas):
        pecas += coluna(slot.left + 64 * k)
    if colunas == 3 and slot.chance(0.6):
        meio = slot.left + 288
        pecas.append(plataforma(slot, meio, altura(meio) + 100))
        pecas += moedas(meio, altura(meio) + 150)
    x = slot.rng.uniform(slot.left + 40, slot.left + 64 * colunas - 40)
    if slot.chance(0.4):
        pecas += moedas(x, altura(x) + 120)
    elif slot.i > 2 and slot.chance(0.5):
        pecas.append(Sprite("tilesets/Object/Crate.png", height=50, center=(x, altura(x) + 22), group="caixa"))
    else:
        pecas.append(Sprite(slot.rng.choice(MOITAS), height=40, center=(x, altura(x) + 16)))
    return pecas


def longe(slot):
    serra = Sprite(cenario, frame="pointy_mountains.png", width=1400, center=(slot.left + 700, 170))
    serra.set_alpha(0.6)
    nuvem = Sprite(cenario, frame=f"cloud{slot.rng.randint(1, 9)}.png", height=slot.rng.uniform(50, 80),
                   center=(slot.rng.uniform(slot.left, slot.right), slot.rng.uniform(400, 480)))
    return [serra, nuvem]


def colinas(slot):
    pecas = []
    for k in range(3):
        x = slot.rng.uniform(slot.left, slot.right)
        alto = slot.rng.uniform(120, 200)
        pecas.append(Sprite(cenario, frame=slot.rng.choice(SILHUETAS), height=alto, center=(x, 110 + alto / 2)))
    pecas.append(Sprite(cenario, frame="hills1.png", width=1000, center=(slot.left + 500, 64)))
    return pecas


st.recorde = 0


class Robo(Sprite, source=folha, hitbox_shape="rect", hitbox_anchor="bottom"):
    def setup(self):
        self.vel = Vec2(0, 0)
        self.tilt = "ground"
        resolve(self, "chao", bounce=0)
        resolve(self, "tabua", bounce=0, only="bottom")

    def on_update(self, dt):
        no_chao = "bottom" in self.touching_sides
        if keyp.once("UP") and no_chao:
            self.vel.y = 900
            play_sound("synth/jump.wav")
        self.vel.y -= 2200 * dt
        if not st.correndo:
            if not self.showing("caindo"):
                self.play("caindo", loops=1)
        elif no_chao:
            self.play("correndo")
        else:
            self.play("pulando")
        self.move_by(st.velocidade * dt, self.vel.y * dt)

    @collide_with("moeda")
    def pegou(self, moeda):
        moeda.destroy()
        st.moedas += 1
        play_sound("synth/coin.wav")

    @collide_with("caixa")
    def bateu(self, caixa):
        if st.correndo:
            st.correndo = False
            st.velocidade = 0
            canvas.shake(6)
            play_sound("audio/impactPlank_medium_002.ogg")

    @leave_playfield
    def caiu(self):
        st.correndo = False
        st.velocidade = 0


class Corrida(Act):
    def setup(self):
        st.velocidade = 320
        st.correndo = True
        st.moedas = 0
        st.metros = 0
        canvas.layers.create("longe", pan_response=0.1, below="default")
        canvas.layers.create("colinas", pan_response=0.3, below="default")
        canvas.layers.create("pista", below="default")
        Endless("longe", longe, step=1400)
        Endless("colinas", colinas, step=1000)
        Endless("pista", trecho, step=384)
        self.robo = Robo(center=(200, 300))
        placar = Text(text="", top_left=(16, 524), font_size=20, color="navy")
        placar["text"] @= lambda: f"{st.metros} m   Moedas {st.moedas}   Recorde {st.recorde} m"
        self.aviso = Text(text="", center=(480, 400), font_size=32, color="navy", layer="ui")

    def on_update(self, dt):
        canvas.pan_to(self.robo.center.x + 250, 270)
        canvas.playfield.set(canvas.game_view.outset(100))
        if st.correndo:
            st.velocidade += 6 * dt
            st.metros = int(self.robo.center.x / 64)
        elif keyp.once("SPACE"):
            change_act(Corrida)

    @when(lambda self: not st.correndo)
    def acabou(self):
        st.recorde = max(st.recorde, st.metros)
        self.aviso.text = "Aperte espaço"


run(Corrida)
