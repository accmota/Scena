"""Avião — tutorial 15.

Um avião voa entre pilares. Ele não anda para a frente: o mundo anda, e o
manche sobe e desce o nariz, com inércia (chase). Cada par de pilares
atravessado vale um ponto (uma porta invisível no vão). Batendo num pilar
ou no chão, o avião cai; espaço recomeça.

Controles
---------
  CIMA / BAIXO         levantar / abaixar o nariz
  ESPAÇO               recomeçar, depois da batida

Uso
---
    python examples/aviao.py
"""

from random import uniform
from scena import *

init(width=640, height=360, title="Avião")
Wallpaper("backgrounds/mountains/mountains1.png")

folha = Sheet("plane/Fly1.png", "plane/Fly2.png", "plane/Dead.png")
folha.clip("voando", [0, 1], fps=12)
folha.clip("caindo", [2])
pecas = Sheet("k-rolling-ball/rollingBall_sheet@2.png", atlas="k-rolling-ball/rollingBall_sheet@2.xml")

st.pontos = 0
st.voando = True

placar = Text(text="", top_left=(16, 346), font_size=18, color="navy")
placar["text"] @= lambda: f"Pontos {st.pontos}"
aviso = Text(text="", center=(320, 200), font_size=24, color="navy")


class Aviao(Sprite, source=folha, height=40):
    def setup(self):
        self.play("voando")

    def on_update(self, dt):
        if st.voando:
            alvo = 0
            if keyp("UP"):
                alvo = 30
            if keyp("DOWN"):
                alvo = -30
            self.rotate_to(chase(self.angle, alvo, rate=4))
            seta = vec_from_angle(self.angle, length=220)
            self.move_by(0, seta.y * dt)
            self.confine(canvas.game_view)
            if self.center.y < 30:
                self.cair()
        elif self.center.y > 30:
            self.rotate_to(chase(self.angle, -60, rate=3))
            self.move_by(0, -160 * dt)

    @collide_with("porta")
    def passou(self, porta):
        porta.destroy()
        st.pontos += 1
        play_sound("audio/fx2.ogg")

    @collide_with("pilar")
    def bateu(self, pilar):
        if st.voando:
            self.cair()

    def cair(self):
        st.voando = False
        self.play("caindo")
        canvas.shake(6)
        play_sound("audio/explosion02.ogg")
        aviso.text = "Aperte espaço"


aviao = Aviao(center=(120, 200))


def novo_par():
    meio = uniform(110, 250)
    Sprite(pecas, frame="block_narrow.png", height=260, center=(680, meio + 190), group="pilar")
    Sprite(pecas, frame="block_narrow.png", height=260, center=(680, meio - 190), group="pilar")
    porta = Rect(center=(690, meio), width=10, height=120, group="porta")
    porta.visible = False


@every(2)
def mais_pilares():
    if st.voando:
        novo_par()


def recomecar():
    group["pilar"].destroy()
    group["porta"].destroy()
    st.pontos = 0
    st.voando = True
    aviso.text = ""
    aviao.center = (120, 200)
    aviao.rotate_to(0)
    aviao.play("voando")


def update(dt):
    if st.voando:
        group["pilar"].move_by(-120 * dt, 0)
        group["porta"].move_by(-120 * dt, 0)
    elif keyp("SPACE"):
        recomecar()


@leave_playfield("pilar", "porta")
def saiu(coisa):
    coisa.destroy()


run()
