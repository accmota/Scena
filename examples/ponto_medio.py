"""Ponto médio com compasso — tutorial 03.

Dois Anchors definem um segmento. Dois círculos (centro numa ponta,
raio na outra) se cruzam; a corda entre as interseções corta o
segmento no meio. Arraste as pontas — tudo acompanha.

Controles
---------
  Arraste os Anchors nas pontas do segmento.

Uso
---
    python examples/ponto_medio.py
"""

from scena import *

init(width=1000, height=700, title="Ponto médio")
Wallpaper("dark navy")

ponta1 = Anchor(420, 320)
ponta2 = Anchor(580, 380)

segmento = Line(p1=lambda: ponta1.center, p2=lambda: ponta2.center, color="white")
segmento.line_width = 3

# Compasso: centro numa ponta, raio até a outra
circulo1 = Circle(
    center=lambda: ponta1.center,
    perimeter_point=lambda: ponta2.center,
    color="deep sky blue",
)
circulo1.fill = None
circulo1.line_width = 2

circulo2 = Circle(
    center=lambda: ponta2.center,
    perimeter_point=lambda: ponta1.center,
    color="orchid",
)
circulo2.fill = None
circulo2.line_width = 2

# Os dois cruzamentos (visíveis antes da corda)
cruzamento1 = Point(lambda: intersection(circulo1, circulo2, 0))
cruzamento1.visible = True
cruzamento1.color = "white"

cruzamento2 = Point(lambda: intersection(circulo1, circulo2, 1))
cruzamento2.visible = True
cruzamento2.color = "white"

# Corda entre os cruzamentos (mediatriz)
corda = Line(p1=lambda: cruzamento1, p2=lambda: cruzamento2, color="gold")
corda.line_width = 2
corda.dash = "dash"  # ou "dot", "dot-dash", "solid"

# Ponto médio = interseção da corda com o segmento
meio = Circle(
    center=lambda: intersection(corda, segmento, 0),
    radius=8,
    color="gold",
)
meio.glow = True

run()
