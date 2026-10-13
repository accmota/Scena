"""Trilhas — tutorial 12, script 1.

Um mostruário de trilhas (Track) e de jeitos de percorrê-las com
move_along: um círculo, um oito com um triângulo que aponta o caminho
(face=True), uma estrela, um vaivém, um caminho aberto em ida e volta
(yoyo=True), um pêndulo com ease="ease_in_out" e um trem de oito vagões
espaçados com phase=.

Controles
---------
  CTRL+SHIFT+7         mostra as trilhas em magenta

Uso
---
    python examples/trilhas.py
"""
from scena import *

init(width=1000, height=700, title="Trilhas")
Wallpaper("#141b2d")

roda = Track.circle(center=(170, 520), radius=110, color="dim gray")
bola = Circle(radius=14, color="coral")
bola.move_along(roda, time=4, loops="forever")

oito = Track.eight(width=300, height=120, center=(500, 540), color="dim gray")
carro = EquilateralTriangle(radius=16, color="gold")
carro.move_along(oito, time=6, loops="forever", face=True)

estrela = Track.star(points=5, radius=110, center=(830, 520), color="dim gray")
cometa = Circle(radius=12, color="turquoise")
cometa.move_along(estrela, time=8, loops="forever")

vaivem = Track.shuttle(length=300, center=(500, 380), color="dim gray")
pistao = Circle(radius=12, color="orchid")
pistao.move_along(vaivem, time=3, loops="forever")

caminho = Track(points=[(60, 100), (160, 290), (260, 120), (380, 240)], color="dim gray")
formiga = Circle(radius=12, color="light green")
formiga.move_along(caminho, time=3, loops="forever", yoyo=True)

arco = Track.arc(center=(560, 330), radius=200, from_angle=225, to_angle=315, color="dim gray")
peso = Circle(radius=18, color="sky blue")
peso.move_along(arco, time=1.2, loops="forever", yoyo=True, ease="ease_in_out")
fio = Line(p1=(560, 330), p2=lambda: peso.center, color="white")

anel = Track(points=[(760, 80), (940, 120), (900, 300), (720, 260)], closed=True, color="dim gray")
for i in range(8):
    vagao = Circle(radius=8, color="gold")
    vagao.move_along(anel, time=8, loops="forever", phase=i / 8)

run()
