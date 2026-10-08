"""Light scene for frame-pacing runs (``scripts/bench/longrun.md``, Windows Pacing
Verification): a few shapes, one sprite, work p50 ~3 ms, holds 60 Hz.

Not a tutorial and not an example: keep the scene unchanged, so runs stay
comparable with the earlier ``app_first`` results (R1L, R2L, R5L, R6L).
Formerly ``examples/app_first.py``.
"""
from random import choice
from scena import *

init(width=1000, height=700, title="Mouse e teclado")
Wallpaper("dark navy")

# --- formas já na tela; clique muda a cor -----------------------------------
quadrado = Rect(center=(160, 480), width=90, height=70, color="coral")
quadrado.visual = Halo("blue")

circulo = Circle(center=(300, 480), radius=40, color="#FF83FA")
circulo.glow = True
circulo.color = "green"

triangulo = EquilateralTriangle(center=(440, 480), radius=48, angle=90, color="gold")  # 90: em pé
triangulo.visual = Neon()


CORES = ["red", "orange", "gold", "lime", "deep sky blue", "orchid", "white"]
@click(quadrado, circulo, triangulo)
def mudou_cor(forma):
    forma.color = choice(CORES)



@when(lambda: keyp("D"))
def soltar_circulo():
    Circle(center=mouse, radius=20, color=choice(CORES))


estrela = Sprite("../../examples/media/space/star_gold.png", size=48, center=(780, 200))


def update(dt):
    VELOCIDADE = 400
    if keyp("LEFT"):
        estrela.move_by(-VELOCIDADE * dt, 0)
    if keyp("RIGHT"):
        estrela.move_by(VELOCIDADE * dt, 0)
    if keyp("UP"):
        estrela.move_by(0, VELOCIDADE * dt)
    if keyp("DOWN"):
        estrela.move_by(0, -VELOCIDADE * dt)


run()
