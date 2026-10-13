"""Naves III — tutorial 07.

O jogo de naves do tutorial 06 com as figuras numa folha (atlas), três
tipos de inimigo, uma explosão em quadros, som e três vidas. Na última vida, a nave
explode e o jogo acaba (para jogar de novo, rode outra vez).

Controles
---------
  ESQUERDA / DIREITA   mover
  ESPAÇO               atirar

Uso
---
    python examples/naves_vidas.py
"""

from random import choice
from scena import *

init(width=1000, height=800, title="Naves")
Wallpaper(Gradient("dark dark blue", "black", angle=90))
Stars(pan_response=0.0, scroll=(0.0, -38.0))
Grain()
Bloom()
Scanlines()

folha = Sheet("shooter/sheet.png", atlas="shooter/sheet.xml")
explosao = Sheet("misc/exp4.png", cols=12)
explosao.clip("explode", range(12), fps=24)

st.pontos = 0
st.vidas = 3
st.velocidade = 80

placar = Text(text="", top_left=(20, 780), font_size=20)
placar["text"] @= lambda: f"Pontos {st.pontos}"

Sprite(folha, frame="playerLife1_red.png", height=24, center=(900, 768))
vidas = Text(text="", top_left=(920, 780), font_size=20)
vidas["text"] @= lambda: f"x {st.vidas}"


class Explosao(Sprite, source=explosao, height=90):
    def setup(self):
        self.play("explode", loops=1)
        play_sound("audio/explosion01.wav")
        self.after(0.5, self.destroy)


class Tiro(Sprite, source=folha, frame="laserBlue03.png", height=28, group="tiros"):
    def on_update(self, dt):
        self.move_by(0, 640 * dt)


class TiroInimigo(Sprite, source=folha, frame="laserRed01.png", height=28, group="tiros_inimigos"):
    def setup(self):
        self.rotate_to(180)

    def on_update(self, dt):
        self.move_by(0, -400 * dt)


class Inimigo(Sprite, source=folha, height=40, group="inimigos"):
    def setup(self):
        self.scale_to(1.08, time=0.45, loops="forever", yoyo=True)

    @collide_with("tiros")
    def atingido(self, tiro):
        Explosao(center=self.center)
        tiro.destroy()
        self.destroy()
        st.pontos += 1


class Heroi(Sprite, source=folha, frame="playerShip1_red.png", height=45):
    def setup(self):
        self.glow = True
        self.propulsor = Jet(origin=lambda: (self.center.x, self.center.y - 22),
                             angle=270, length=40, width=16, amount=2)

    def on_update(self, dt):
        if keyp("LEFT"):
            self.move_by(-340 * dt, 0)
        if keyp("RIGHT"):
            self.move_by(340 * dt, 0)
        self.confine(canvas.game_view.inset(40))

        if keyp("SPACE") and ready("tiro", 0.2):
            Tiro(center=(self.center.x, self.center.y + 28))
            play_sound("audio/laser4.wav")

    @collide_with("tiros_inimigos")
    def atingido(self, tiro):
        tiro.destroy()
        if not ready("dano", 1.5):
            return
        st.vidas -= 1
        canvas.shake(8)
        if st.vidas > 0:
            self.blink(1.5)
            play_sound("audio/sfx-hit-2.wav")
        else:
            canvas.flash(0.4)
            canvas.explosion_at(self, amount=1.2)
            Fire(center=self.center, radius=30)
            Text(text="FIM DE JOGO", center=(500, 400), font_size=48)
            play_sound("audio/gameover.wav")
            self.destroy()

    def on_destroy(self):
        self.propulsor.destroy()


nave = Heroi(center=(500, 70))

FROTA = ["enemyBlack1.png", "enemyBlue3.png", "enemyGreen4.png"]
for linha in range(3):
    for coluna in range(8):
        inimigo = Inimigo(frame=FROTA[linha], center=(185 + coluna * 90, 720 - linha * 70))
        inimigo.hue = coluna / 8


@every(0.4)
def frota_atira():
    if group["inimigos"].count == 0:
        return
    inimigo = choice(group["inimigos"])
    TiroInimigo(center=(inimigo.center.x, inimigo.center.y - 20))


def update(dt):
    group["inimigos"].move_by(st.velocidade * dt, 0)

    for inimigo in group["inimigos"]:
        if inimigo.center.x > 960:
            st.velocidade = -80
        if inimigo.center.x < 40:
            st.velocidade = 80


@leave_playfield("tiros", "tiros_inimigos")
def saiu(tiro):
    tiro.destroy()


run()
