"""Naves II — tutorial 06.

O jogo de naves do tutorial 05, reorganizado em classes: o tiro sobe
sozinho, o inimigo pulsa e explode, a nave lê as setas e leva um
propulsor. Sem vidas, sem reinício.

Controles
---------
  ESQUERDA / DIREITA   mover
  ESPAÇO               atirar

Uso
---
    python examples/naves_2_classes.py
"""

from random import choice
from scena import *

init(width=1000, height=800, title="Naves")
Wallpaper(Gradient("dark dark blue", "black", angle=90))
Stars(pan_response=0.0, scroll=(0.0, -38.0))
Grain()
Bloom()
Scanlines()

st.pontos = 0
st.velocidade = 80

placar = Text(text="", top_left=(20, 780), font_size=20)
placar["text"] @= lambda: f"Pontos {st.pontos}"


class Tiro(Sprite, source="space/laserBlue03.png", height=28, group="tiros"):
    def on_update(self, dt):
        self.move_by(0, 640 * dt)


class TiroInimigo(Sprite, source="space/laserRed01.png", height=28, group="tiros_inimigos"):
    def setup(self):
        self.rotate_to(180)

    def on_update(self, dt):
        self.move_by(0, -400 * dt)


class Inimigo(Sprite, height=40, group="inimigos"):
    def setup(self):
        self.scale_to(1.08, time=0.45, loops="forever", yoyo=True)

    @collide_with("tiros")
    def atingido(self, tiro):
        canvas.burst_at(self, radius=40)
        tiro.destroy()
        self.destroy()
        st.pontos += 1


class Heroi(Sprite, source="space/playerShip1_red.png", height=45):
    def setup(self):
        self.glow = True
        self.propulsor = Jet(origin=lambda: (self.center.x, self.center.y - 22),
                             angle=270, length=40, width=16, amount=2)

    def on_update(self, dt):
        if keyp("LEFT"):
            self.move_by(-340 * dt, 0)
        if keyp("RIGHT"):
            self.move_by(340 * dt, 0)
        self.confine(canvas.game_view.inset(40))

        if keyp("SPACE") and ready("tiro", 0.2):
            Tiro(center=(self.center.x, self.center.y + 28))

    @collide_with("tiros_inimigos")
    def atingido(self, tiro):
        tiro.destroy()
        canvas.flash(0.4)
        canvas.explosion_at(self, amount=1.2)
        self.destroy()

    def on_destroy(self):
        self.propulsor.destroy()


nave = Heroi(center=(500, 70))

FROTA = ["space/enemyGreen1.png", "space/enemyBlue2.png"]
for linha in range(3):
    for coluna in range(8):
        inimigo = Inimigo(FROTA[linha % 2], center=(185 + coluna * 90, 720 - linha * 70))
        inimigo.hue = coluna / 8


@every(0.4)
def frota_atira():
    if group["inimigos"].count == 0:
        return
    inimigo = choice(group["inimigos"])
    TiroInimigo(center=(inimigo.center.x, inimigo.center.y - 20))


def update(dt):
    group["inimigos"].move_by(st.velocidade * dt, 0)

    for inimigo in group["inimigos"]:
        if inimigo.center.x > 960:
            st.velocidade = -80
        if inimigo.center.x < 40:
            st.velocidade = 80


@leave_playfield("tiros", "tiros_inimigos")
def saiu(tiro):
    tiro.destroy()


run()
