"""Pegar estrelas — tutorial 02.

A barra pega as estrelas que caem. Sem vidas, sem reinício.

Controles
---------
  ESQUERDA / DIREITA   mover

Uso
---
    python examples/pegar_estrelas.py
"""

from random import uniform
from scena import *

init(width=1000, height=800, title="Pegar estrelas")
Wallpaper("dark navy")

st.pontos = 0
st.perdidas = 0

placar = Text(text="", top_left=(20, 780), font_size=20)
placar["text"] @= lambda: f"Estrelas {st.pontos}   Perdidas {st.perdidas}"

barra = Sprite("k-rolling-ball/button_blue.png", width=80, center=(500, 80), group="heroi")


@every(0.9)
def soltar_estrela():
    x = uniform(80, 920)
    Sprite("k-rolling-ball/star.png", size=32, center=(x, 780), group="estrelas")


def update(dt):
    if keyp("LEFT"):
        barra.move_by(-380 * dt, 0)
    if keyp("RIGHT"):
        barra.move_by(380 * dt, 0)

    for estrela in group["estrelas"]:
        estrela.move_by(0, -220 * dt)
        if estrela.center.y < 40:
            perdeu(estrela)


@collide("heroi", "estrelas")
def pegou(barra, estrela):
    estrela.destroy()
    st.pontos += 1
    barra.pop(scale=1.25)


def perdeu(estrela):
    estrela.untag("estrelas")  # o if não dispara de novo
    estrela.flash(0.2)
    estrela.after(0.2, estrela.destroy)
    st.perdidas += 1


run()
