"""Ninja — tutorial 14.

Um ninja num jogo de plataforma: a gravidade escrita à mão (uma velocidade
que cresce para baixo a cada quadro), o chão e as plataformas que seguram
(resolve com bounce=0), o pulo só com os pés no chão (touching_sides) e
três animações de arquivos de tamanhos diferentes (strip com *, pixel_size
e anchor="bottom").

Controles
---------
  ESQUERDA / DIREITA   andar
  CIMA                 pular

Uso
---
    python examples/ninja.py
"""

from scena import *

init(width=1000, height=750, title="Ninja")
Wallpaper("tilesets/BG/BG.png")

for i in range(13):
    Sprite("tilesets/Tiles/2.png", height=80, center=(40 + i * 80, 40), group="chao")


def plataforma(x, y):
    Sprite("tilesets/Tiles/13.png", width=80, center=(x - 80, y), group="chao")
    Sprite("tilesets/Tiles/14.png", width=80, center=(x, y), group="chao")
    Sprite("tilesets/Tiles/15.png", width=80, center=(x + 80, y), group="chao")


plataforma(360, 220)
plataforma(720, 390)
Rect(center=(-20, 375), width=40, height=750, group="chao")
Rect(center=(1020, 375), width=40, height=750, group="chao")
group["chao"].mass = STATIC

ninja = Sheet(anchor="bottom", pixel_size=0.2)
ninja.strip("parado", "ninja/Idle__*.png", fps=8)
ninja.strip("correndo", "ninja/Run__*.png", fps=12)
ninja.strip("pulando", "ninja/Jump__*.png", fps=10)


class Heroi(Sprite, source=ninja, group="heroi", hitbox_shape="rect"):
    def setup(self):
        self.vel = Vec2(0, 0)

    def on_update(self, dt):
        if keyp("LEFT"):
            self.vel.x = -280
            self.flip_x = True
        elif keyp("RIGHT"):
            self.vel.x = 280
            self.flip_x = False
        else:
            self.vel.x = 0

        no_chao = "bottom" in self.touching_sides
        if keyp.once("UP") and no_chao:
            self.vel.y = 900
            play_sound("synth/jump.wav")

        self.vel.y -= 2200 * dt
        self.move_by(self.vel.x * dt, self.vel.y * dt)

        if not no_chao:
            self.play("pulando")
        elif self.vel.x != 0:
            self.play("correndo")
        else:
            self.play("parado")


resolve("heroi", "chao", bounce=0)

heroi = Heroi(center=(100, 400))


run()
