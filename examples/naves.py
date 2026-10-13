"""Naves — tutorial 05.

Jogo de naves simples: a nave atira, a frota respira, vai e volta e devolve tiro.
Sem vidas, sem reinício.

Controles
---------
  ESQUERDA / DIREITA   mover
  ESPAÇO               atirar

Uso
---
    python examples/naves.py
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

nave = Sprite("space/playerShip1_red.png", height=45, center=(500, 70))
nave.glow = True

FROTA = ["space/enemyGreen1.png", "space/enemyBlue2.png"]
for linha in range(3):
    for coluna in range(8):
        inimigo = Sprite(
            FROTA[linha % 2],
            height=40,
            center=(185 + coluna * 90, 720 - linha * 70),
            group="inimigos",
        )
        inimigo.hue = coluna / 8
        inimigo.scale_to(1.08, time=0.45, loops="forever", yoyo=True)


@every(0.4)
def frota_atira():
    if group["inimigos"].count == 0:
        return
    inimigo = choice(group["inimigos"])
    s = Sprite("space/laserRed01.png", height=28,
           center=(inimigo.center.x, inimigo.center.y - 20), group="tiros_inimigos")
    s.rotate_to(180)

def update(dt):
    if nave:
        if keyp("LEFT"):
            nave.move_by(-340 * dt, 0)
        if keyp("RIGHT"):
            nave.move_by(340 * dt, 0)
        nave.confine(canvas.game_view.inset(40))

        if keyp("SPACE") and ready("tiro", 0.2):
            Sprite("space/laserBlue03.png", height=28, center=(nave.center.x, nave.center.y + 28), group="tiros")

    group["tiros"].move_by(0, 640 * dt)
    group["tiros_inimigos"].move_by(0, -400 * dt)

    group["inimigos"].move_by(st.velocidade * dt, 0)

    for inimigo in group["inimigos"]:
        if inimigo.center.x > 960:
            st.velocidade = -80
        if inimigo.center.x < 40:
            st.velocidade = 80


@leave_playfield("tiros", "tiros_inimigos")
def saiu(tiro):
    tiro.destroy()


@collide("tiros", "inimigos")
def acertou(tiro, inimigo):
    canvas.burst_at(inimigo, radius=40)
    tiro.destroy()
    inimigo.destroy()
    st.pontos += 1


@collide("tiros_inimigos", nave)
def atingiu(tiro, nave):
    tiro.destroy()
    canvas.flash(0.4)
    canvas.explosion_at(nave, amount=1.2)
    nave.destroy()


run()
