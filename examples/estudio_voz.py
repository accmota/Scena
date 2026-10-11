"""Estúdio II · Voz — tutorial 18.

O piano do tutorial 17 com a sua voz: R abre o microfone (na primeira
vez, o sistema pede licença) e grava dois segundos; depois as teclas
tocam a gravação em oito alturas. Um medidor mostra quão alto você fala
(st.voz, ligado ao microfone com @=), uma estrela percorre um oito (Track +
move_along) com uma luz que cresce com a voz, e uma palma solta um sol.

Controles
---------
  A S D F G H J K   tocam as oito notas (clique numa tecla também)
  R                 grava dois segundos de voz
  palma             um sol onde está a estrela

Uso
---
    python examples/estudio_voz.py
"""

from scena import *

init(width=1000, height=600, title="Estúdio")
Wallpaper("dark navy")

LETRAS = ["A", "S", "D", "F", "G", "H", "J", "K"]
NOTAS = [1, 1.12, 1.26, 1.33, 1.5, 1.68, 1.89, 2]

st.voz = 0


class Tecla(Rect, width=110, height=300, color="#F2EFE6", group="teclas"):
    def on_update(self, dt):
        if keyp.once(self.letra):
            self.tocar()

    def tocar(self):
        play_sound(gravador.som, pitch=self.nota, on_done=self.apagar)
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


aviso = Text(text="R grava a sua voz", top_left=(20, 585), font_size=20, color="silver")


class Gravador(Circle, radius=10, color="dim gray"):
    def setup(self):
        self.mic = None
        self.som = "audio/nota.wav"

    def on_update(self, dt):
        if keyp.once("R"):
            self.gravar()

    def gravar(self):
        if not self.mic:
            self.mic = Microphone()
            st["voz"] @= lambda: amp_db(self.mic.level)
        if self.mic.recording:
            return
        self.gravacao = self.mic.record(seconds=2, on_done=self.gravou)
        self.color = "red"
        aviso.text = "Fale!"

    def gravou(self):
        self.som = self.gravacao
        self.color = "dim gray"
        aviso.text = "As teclas tocam a sua voz. R grava de novo"


gravador = Gravador(center=(975, 575))


Rect(top_left=(20, 550), width=300, height=10, color="#262B55")
barra = Rect(top_left=(20, 550), width=0, height=10, color="lime")
barra["width"] @= lambda: 300 * st.voz


trilha = Track.eight(width=760, height=140, center=(500, 470))
estrela = Sprite("space/star_gold.png", size=32)
estrela.move_along(trilha, time=8, loops="forever")
luz = GlowSpot(center=lambda: estrela.center, color="gold")
luz["radius"] @= lambda: 30 + 120 * st.voz
luz["amount"] @= lambda: 0.3 + st.voz


@when(lambda: st.voz > 0.75)
def palma():
    sol = Sunburst(center=estrela.center, radius=100)
    sol.after(0.8, sol.destroy)


run()
