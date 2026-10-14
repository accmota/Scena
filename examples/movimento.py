"""Movimento — tutorial 12.

Uma nave que vai aonde você clica: move_to com speed=, ease= e face=,
um alvo que some ao chegar (on_done=), o controle da viagem (cancel)
para trocar de destino ou parar, e a perseguição do mouse a cada quadro
com approach.

Controles
---------
  clique           a nave viaja até o ponto
  Espaço           para a nave
  botão direito    segurado, a nave persegue o mouse

Uso
---
    python examples/movimento.py
"""
from scena import *

init(width=1000, height=700, title="Movimento")
Wallpaper("#0b1020")
Stars()

alvo = Circle(center=(500, 350), radius=24, color="gold")
alvo.fill = None
alvo.dash = "dash"
alvo.visible = False

nave = Sprite("space/playerShip1_red.png", width=60, center=(500, 350), art_angle=90)
nave.viagem = None


def pousou():
    alvo.visible = False


def parar():
    if nave.viagem:
        nave.viagem.cancel()
        nave.viagem = None
    alvo.visible = False


def on_mouse_click(x, y, button):
    parar()
    alvo.center = (x, y)
    alvo.visible = True
    nave.viagem = nave.move_to(x, y, speed=400, ease="ease_in_out", face=True, on_done=pousou)


def update(dt):
    if keyp.once("SPACE"):
        parar()
    if mouse.press(Mouse.BTN_RIGHT):
        parar()
        nave.move_to(approach(nave.center, mouse, 300), face=True)


run()
