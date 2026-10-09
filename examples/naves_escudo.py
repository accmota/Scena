"""Naves IV — tutorial 08.

O Galaga do tutorial 07 com um escudo: às vezes um inimigo destruído deixa
cair um presente; pegá-lo enche a energia e liga o escudo. Cada laser que o
escudo segura estoura onde bateu e gasta energia; sem energia, o escudo
quebra e a nave volta a perder vidas.

Controles
---------
  ESQUERDA / DIREITA   mover
  ESPAÇO               atirar

Uso
---
    python examples/naves_escudo.py
"""

from random import choice, random
from scena import *

init(width=1000, height=800, title="Naves")
Wallpaper(Gradient("black", "dark dark blue", angle=90))
Stars(pan_response=0.0, scroll=(0.0, -38.0))
Grain()
Bloom()
Scanlines()

folha = Sheet("shooter/sheet.png", atlas="shooter/sheet.xml")
explosao = Sheet("misc/exp4.png", cols=12)
explosao.clip("explode", range(12), fps=24)

st.pontos = 0
st.vidas = 3
st.energia = 0
st.velocidade = 80

placar = Text(text="", top_left=(20, 780), font_size=20)
placar["text"] @= lambda: f"Pontos {st.pontos}"

Sprite(folha, frame="playerLife1_red.png", height=24, center=(900, 768))
vidas = Text(text="", top_left=(920, 780), font_size=20)
vidas["text"] @= lambda: f"x {st.vidas}"

barra = Rect(top_left=(20, 745), width=200, height=8, color="cyan")
barra["width"] @= lambda: st.energia * 2


class Explosao(Sprite, source=explosao, height=90):
    def setup(self):
        self.play("explode", loops=1)
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
        play_sound("audio/explosion01.wav")
        if random() < 0.2:
            Poder(center=self.center)
        tiro.destroy()
        self.destroy()
        st.pontos += 1


class Poder(Sprite, source=folha, frame="powerupBlue_shield.png", height=30, group="poderes"):
    def on_update(self, dt):
        self.move_by(0, -150 * dt)


class Escudo(Sprite, source=folha, frame="shield2.png", height=80, hitbox_shape="circle"):
    def setup(self):
        self.glow = "cyan"

    @collide_with("tiros_inimigos")
    def bloqueou(self, tiro, info):
        canvas.zap_at(info, color="cyan")
        play_sound("audio/sfx-hit-2.wav", pitch=1.6)
        tiro.destroy()
        st.energia -= 20


class Heroi(Sprite, source=folha, frame="playerShip1_red.png", height=45):
    def setup(self):
        self.glow = True
        self.propulsor = Jet(origin=lambda: (self.center.x, self.center.y - 22),
                             angle=270, length=40, width=16, amount=2)
        self.escudo = Escudo(center=lambda: self.center)
        self.escudo.active = False

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

    @collide_with("poderes")
    def pegou(self, poder):
        poder.destroy()
        self.pop()
        play_sound("audio/fx1.wav")
        st.energia = 100

    @on_change(lambda self: st.energia)
    def energia_mudou(self):
        self.escudo.active = st.energia > 0
        if st.energia == 0:
            canvas.burst_at(self, radius=70, rings=True)
            play_sound("audio/impactBell_heavy_000.ogg")

    def on_destroy(self):
        self.propulsor.destroy()
        self.escudo.destroy()


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


@leave_playfield("tiros", "tiros_inimigos", "poderes")
def saiu(tiro):
    tiro.destroy()


run()
