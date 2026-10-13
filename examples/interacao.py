"""Interação — tutorial 11.

Uma bancada para o mouse, sem jogo. Três peças para arrastar, uma lixeira
e uma grade de 4 por 3. Soltar uma peça numa casa a encaixa no centro dela;
soltar na lixeira a apaga, e a lixeira fica vermelha enquanto uma peça passa
sobre ela. A casa embaixo do mouse ganha uma moldura branca.

Controles
---------
  MOUSE (arrastar)     levar uma peça até uma casa ou até a lixeira

Uso
---
    python examples/interacao.py
"""

from scena import *

init(width=1000, height=700, title="Interação")
Wallpaper("dark navy")

zona = Box(center=(520, 380), width=400, height=300)
grade = zona.grid(4, 3, gap=8)
for casa in grade:
    Rect(box=casa, color="#33406a")

luz = Rect(box=grade.cell(0, 0), color="white")
luz.fill = None
luz.line_width = 4
luz.visible = False

lixeira = Rect(center=(860, 130), width=160, height=110, color="gray")
Text("lixeira", center=(860, 130))

Square(center=(120, 560), length=70, color="coral", group="pecas")
Square(center=(120, 440), length=70, color="gold", group="pecas")
Square(center=(120, 320), length=70, color="orchid", group="pecas")
group["pecas"].draggable = True


@drop_by(lixeira)
def jogou(peca, alvo, pos):
    peca.destroy()
    lixeira.color = "gray"


@drag_over(group["pecas"])
def passando(peca, alvo, pos):
    if alvo is lixeira:
        lixeira.color = "red"
    else:
        lixeira.color = "gray"


@drag_to(group["pecas"])
def soltou(peca, alvo, pos):
    casa = grade.cell_at(pos)
    if casa is not None:
        peca.center = casa.center


def update(dt):
    casa = grade.cell_at(mouse)
    if casa is None:
        luz.visible = False
    else:
        luz.visible = True
        luz.center = casa.center


run()
