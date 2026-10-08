"""Primeiro script — tutorial 01.

Formas, cor, visual, um sprite nas setas, clique e @when.

Controles
---------
  setas     movem a estrela
  clique    pinta a forma
  D         solta um círculo no mouse

Uso
---
    python examples/primeiro_script.py
"""

from scena import *

init(width=1000, height=700, title="Mouse e teclado")
Wallpaper("dark navy")

retangulo = Rect(center=(160, 480), width=90, height=70)
retangulo.color = "coral"
retangulo.visual = Halo("blue")

circulo = Circle(center=(300, 480), radius=40)
circulo.color = "#FF83FA"
circulo.glow = True

triangulo = EquilateralTriangle(center=(440, 480), radius=48, angle=90)
triangulo.color = "gold"
triangulo.visual = Neon()

estrela = Sprite("space/star_gold.png", size=48, center=(500, 200))


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


@click(retangulo, circulo, triangulo)
def clicou(forma):
    forma.color = Color.random()


@when(lambda: keyp("D"))
def soltar_circulo():
    Circle(center=(mouse.x, mouse.y), radius=20, color=Color.random())


@when(lambda: estrela.center.x > 800)
def chegou():
    triangulo.color = "white"
    circulo.radius = 60


run()
