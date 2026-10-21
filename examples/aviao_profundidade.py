"""Avião II · Profundidade — tutorial 16.

O avião do tutorial 15 com profundidade: três faixas de cenário (nuvens,
montes, mato), cada uma numa camada que anda uma fração da velocidade do
voo, cheias sem fim pelo Endless. Na batida, tudo freia junto, o avião cai
pegando fogo e a música abaixa.

Controles
---------
  CIMA / BAIXO         levantar / abaixar o nariz
  ESPAÇO               recomeçar, depois da batida

Uso
---
    python examples/aviao_profundidade.py
"""

from random import uniform
from scena import *

init(width=640, height=360, title="Avião")
Wallpaper("backgrounds/mountains/mountains1.png")

nuvens = canvas.layers.create("nuvens", scroll=(-12, 0), below="default")
montes = canvas.layers.create("montes", scroll=(-36, 0), below="default")
mato = canvas.layers.create("mato", scroll=(-84, 0), below="default")
Endless("nuvens", "backgrounds/mountains/mountains2.png", height=360)
Endless("montes", "backgrounds/mountains/mountains3.png", height=360)
Endless("mato", "backgrounds/mountains/mountains4.png", height=360)

folha = Sheet("plane/Fly1.png", "plane/Fly2.png", "plane/Dead.png")
folha.clip("voando", [0, 1], fps=12)
folha.clip("caindo", [2])
pecas = Sheet("k-rolling-ball/rollingBall_sheet@2.png", atlas="k-rolling-ball/rollingBall_sheet@2.xml")

st.pontos = 0
st.voando = True
st.velocidade = 120

musica = play_sound("audio/SuperHero_original_no_Intro.ogg", loops="forever", volume=0.5)

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
        play_sound("audio/fx2.wav")

    @collide_with("pilar")
    def bateu(self, pilar):
        if st.voando:
            self.cair()

    def cair(self):
        st.voando = False
        self.play("caindo")
        canvas.shake(6)
        play_sound("audio/explosion02.wav")
        self.move_to_front()
        self.fogo = Fire(center=lambda: self.center + Vec2(-20, 8).rotate(self.angle), width=12, style="tongues")
        aviso.text = "Aperte espaço"
        musica.fade_to(0.1, time=1)


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
    st.velocidade = 120
    aviso.text = ""
    aviao.center = (120, 200)
    aviao.rotate_to(0)
    aviao.play("voando")
    aviao.fogo.destroy()
    musica.fade_to(0.5, time=1)


def update(dt):
    if not st.voando:
        st.velocidade = chase(st.velocidade, 0, rate=2)
        if keyp("SPACE"):
            recomecar()
    group["pilar"].move_by(-st.velocidade * dt, 0)
    group["porta"].move_by(-st.velocidade * dt, 0)
    nuvens.scroll = (-st.velocidade * 0.1, 0)
    montes.scroll = (-st.velocidade * 0.3, 0)
    mato.scroll = (-st.velocidade * 0.7, 0)


@leave_playfield("pilar", "porta")
def saiu(coisa):
    coisa.destroy()


run()
