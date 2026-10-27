"""Bolas — tutorial 10.

Vinte bolas quicam nas paredes e umas nas outras: duas regras de
resolve, uma para bola com parede e outra para bola com bola. Cada batida
na parede toca um som e acende um clarão onde a bola tocou. Uma bola
sorteada é dourada e deixa dois rastros (Tail e Contrail). Uma barra no
alto mostra a velocidade dela: o comprimento e a cor (uma rampa de
Colormap) estão ligados à sua vel com @=.

Controles
---------
  RODA DO MOUSE        aproximar / afastar

Uso
---
    python examples/bolas.py
"""

from random import uniform, choice
from scena import *

init(width=1000, height=720, title="Bolas")
SkyGradient("night")

Rect(center=(500, 16), width=1000, height=32, group="parede")
Rect(center=(500, 704), width=1000, height=32, group="parede")
Rect(center=(16, 360), width=32, height=720, group="parede")
Rect(center=(984, 360), width=32, height=720, group="parede")
group["parede"].visual = Metal()
group["parede"].mass = STATIC


class Bola(Circle, radius=14, color="tomato", group="bola"):
    def setup(self):
        self.vel = vec_from_angle(uniform(0, 360), length=uniform(180, 340))

    def on_update(self, dt):
        self.move_by(self.vel.x * dt, self.vel.y * dt)

    @collide_with("parede")
    def bateu(self, parede, info):
        canvas.hit_at(info, radius=10, style="disc")
        play_sound("audio/impact_generic_light_003.ogg", volume=0.5)


resolve("bola", "parede", bounce=1)
resolve("bola", "bola", bounce=1)

for i in range(20):
    Bola(center=(uniform(80, 920), uniform(80, 640)))

escolhida = choice(group["bola"])
escolhida.color = "gold"
escolhida.tail = Tail(color="gold", size=1.4, amount=1.2)

rastro = Contrail(duration=8, fade=True, color="gold", line_width=3)
escolhida.every(0.05, lambda: rastro.snapshot(escolhida))

rampa = Colormap.from_colors("lime", "gold", "red")

Rect(top_left=(40, 710), width=300, height=12, color="#262B55", layer="ui")
barra = Rect(top_left=(40, 710), width=0, height=12, layer="ui")
barra["width"] @= lambda: 300 * min(escolhida.vel.length / 500, 1)
barra["color"] @= lambda: rampa.get_color(escolhida.vel.length / 500)


def on_mouse_scroll(xoffset, yoffset):
    if yoffset > 0:
        canvas.zoom_by(1.1, about=mouse)
    else:
        canvas.zoom_by(1 / 1.1, about=mouse)


run()
