"""Bolhas — tutorial 06, Script 1.

Bolhas de vários tamanhos sobem do fundo do mar; as grandes sobem mais
rápido. Quando uma passa do alto, volta pelo fundo. Um clique estoura a
bolha numa espuma de bolhinhas. Mostra uma classe (o molde), os campos
de cada objeto, setup, on_update e on_click.

Controles
---------
  Clique numa bolha para estourá-la.

Uso
---
    python examples/bolhas.py
"""

from random import uniform
from scena import *

init(width=1000, height=700, title="Bolhas")
Wallpaper(Gradient("teal", "dark navy", angle=90))


class Bolha(Circle, radius=30, visual=Halo("sky blue")):
    def setup(self):
        self.velocidade = self.radius * 4

    def on_update(self, dt):
        self.move_by(0, self.velocidade * dt)
        if self.center.y > 760:
            self.move_by(0, -820)

    def on_click(self):
        canvas.bubbles_at(self, color="sky blue")
        self.destroy()


for coluna in range(9):
    Bolha(center=(100 + coluna * 100, -50), radius=uniform(15, 45))

run()
