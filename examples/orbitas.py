"""Órbitas — tutorial 14.

Um sistema solar: planetas com degradê radial e Halo(style="fill") em
órbitas circulares, uma lua numa órbita que anda com a Terra e deixa um
rastro de bolinhas (History), um anel que
gira para sempre (rotate_by) e um sol que pulsa (tween); as órbitas se
desenham ao começar. Uma sonda percorre um oito, aponta (heading) para o
planeta mais perto (nearest) e fica ligada a ele por uma linha, que vira
um raio elétrico (ElectricBolt) quando a distância cai abaixo de 120.

Uso
---
    python examples/orbitas.py
"""
from scena import *

init(width=1000, height=700, title="Órbitas")
Wallpaper("#0b1020")
Stars()

sol = Circle(center=(500, 350), radius=44)
sol.fill = Gradient("light yellow", "orange", type="radial")
sol.visual = Halo(style="fill")
tween(sol["radius"], 52, time=1.5, ease="ease_in_out", loops="forever", yoyo=True)


def planeta(distancia, tempo, tamanho, cor_dentro, cor_fora):
    orbita = Track.circle(center=sol.center, radius=distancia, color="#2c3654")
    orbita.end = 0
    tween(orbita["end"], 1, time=2, ease="ease_out")
    bola = Circle(radius=tamanho, group="planeta")
    bola.fill = Gradient(cor_dentro, cor_fora, type="radial")
    bola.visual = Halo(style="fill")
    bola.move_along(orbita, time=tempo, loops="forever")
    return bola


planeta(110, 5, 12, "white", "tomato")
terra = planeta(190, 9, 18, "light cyan", "royal blue")
gigante = planeta(300, 16, 26, "khaki", "chocolate")

orbita_lua = Track.circle(center=lambda: terra.center, radius=40)
lua = Circle(radius=7, group="planeta")
lua.fill = Gradient("white", "gray", type="radial")
lua.move_along(orbita_lua, time=2, loops="forever")

rastro = History(max_points=80, on_leave=lambda bolinha: bolinha.dissolve_out(0.4))


def soltar_bolinha():
    rastro.add(Circle(center=lua.center, radius=2, color="light gray"))


every(0.05, soltar_bolinha)

anel = Circle(center=lambda: gigante.center, radius=40, color="khaki")
anel.fill = None
anel.line_width = 2
anel.dash = "dash"
anel.rotate_by(360, time=1.0, loops="forever")

passeio = Track.eight(width=820, height=520, center=(500, 350))
sonda = Triangle(radius=14, color="white")
sonda.move_along(passeio, time=14, loops="forever")

linha = Line(p1=lambda: sonda.center, p2=sol.center, color="light cyan")


def update(dt):
    alvo = group["planeta"].nearest(sonda)
    linha.p2 = alvo.center
    sonda.angle = heading(sonda, alvo)
    if distance(sonda, alvo) < 120:
        linha.visual = ElectricBolt()
    else:
        linha.visual = None


run()
