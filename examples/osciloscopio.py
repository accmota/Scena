"""Osciloscópio — uma ponta gira em volta da bola e deixa rastro. Tutorial 04.

A ponta é um Point com fórmula: um círculo de raio 200 em volta da bola,
mais um círculo menor (x1, y1) que dá tx1 / ty1 voltas a cada volta grande.
O painel grava em st; a fórmula lê st a cada frame. O clique na bola liga
o feixe e o rastro.

Controles
---------
  clique    na bola: liga o feixe e o rastro
  painel    n (velocidade), x1 / y1 (tamanho do giro pequeno),
            tx1 / ty1 (voltas do giro pequeno)

Uso
---
    python examples/osciloscopio.py
"""

from scena import *
from math import cos, sin

W, H = 1000, 720
init(width=W, height=H, title="Osciloscópio")

ui.scale = 0.9

st.n = 4
st.x1 = 50
st.tx1 = 2
st.y1 = 50
st.ty1 = 2
st.ligado = False
Slider(st["n"], label="n", min_value=1, max_value=6)
Slider(st["x1"], label="x1", min_value=-100, max_value=100)
Slider(st["tx1"], label="tx1", min_value=-10, max_value=10, only_int=True)
Slider(st["y1"], label="y1", min_value=-100, max_value=100)
Slider(st["ty1"], label="ty1", min_value=-10, max_value=10, only_int=True)


bola = Circle(center=(W * 0.6, H * 0.5), radius=20)
bola.visual = "red"
bola.visual = Beat()

st.tempo = 0


def update(dt):
    st.tempo += dt * st.n


ponta = Point()
ponta @= lambda: (
    bola.center.x + 200 * cos(st.tempo) + st.x1 * cos(st.tempo * st.tx1),
    bola.center.y + 200 * sin(st.tempo) + st.y1 * sin(st.tempo * st.ty1),
)

feixe = Line(p1=lambda: bola.center, p2=lambda: ponta)
feixe.visual = ElectricField("yellow")
feixe.visible = False

rastro = Contrail(
    duration=6.28 / 4,
    fade=True,
    ease="ease_out",
    visual=Neon("red"),
    line_width=2.5,
    smooth=True,
)

@click(bola)
def ligar():
    if st.ligado:
        return
    st.ligado = True
    feixe.visible = True
    bola.visual = "red"
    every(6.28 / (st.n * 100), lambda: rastro.snapshot(ponta))


run()
