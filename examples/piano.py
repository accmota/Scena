"""Estúdio · Piano — tutorial 20.

Um piano de oito teclas: uma nota só (audio/nota.wav) tocada em oito
alturas com pitch=; a tecla acende enquanto a nota soa (on_done=).

Controles
---------
  A S D F G H J K   tocam as oito notas, do dó ao dó seguinte
  clique            numa tecla também toca

Uso
---
    python examples/piano.py
"""

from scena import *

init(width=1000, height=600, title="Piano")
Wallpaper("dark navy")

LETRAS = ["A", "S", "D", "F", "G", "H", "J", "K"]
NOTAS = [1, 1.12, 1.26, 1.33, 1.5, 1.68, 1.89, 2]


class Tecla(Rect, width=110, height=300, color="#F2EFE6", group="teclas"):
    def on_update(self, dt):
        if keyp.once(self.letra):
            self.tocar()

    def tocar(self):
        play_sound("audio/nota.wav", pitch=self.nota, on_done=self.apagar)
        self.color = "gold"

    def apagar(self):
        self.color = "#F2EFE6"


for i in range(8):
    tecla = Tecla(center=(94 + i * 116, 190))
    tecla.letra = LETRAS[i]
    tecla.nota = NOTAS[i]
    Text(text=LETRAS[i], center=(94 + i * 116, 70), font_size=28, color="dim gray")


@click(group["teclas"])
def clicou(tecla):
    tecla.tocar()


run()
