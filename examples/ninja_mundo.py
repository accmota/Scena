"""Ninja II · O mundo — tutorial 18.

O ninja do tutorial 17 num mundo para viver: um buraco com água no meio
do chão, uma folga para pular na beirada (recently, o tempo do coiote),
cinco estrelas para pegar, dois robôs que patrulham, kunais que os
quebram (um clip que toca uma vez e volta) e três vidas. Cair na água ou
encostar num robô custa uma vida; sem vidas, o jogo acaba (para jogar de
novo, rode outra vez).

Controles
---------
  ESQUERDA / DIREITA   andar
  CIMA                 pular
  ESPAÇO               jogar uma kunai

Uso
---
    python examples/ninja_mundo.py
"""

from scena import *

init(width=1000, height=750, title="Ninja")
Wallpaper("tilesets/BG/BG.png")

Sprite("tilesets/Object/Tree_2.png", height=230, center=(130, 195))
Sprite("tilesets/Object/Bush (1).png", height=50, center=(300, 105))
Sprite("tilesets/Object/Sign_2.png", height=60, center=(410, 110))
Sprite("tilesets/Object/Mushroom_1.png", height=30, center=(770, 95))
Sprite("tilesets/Object/Bush (3).png", height=40, center=(960, 100))

for i in range(5):
    Sprite("tilesets/Tiles/2.png", height=80, center=(40 + i * 80, 40), group="chao")
Sprite("tilesets/Tiles/3.png", height=80, center=(440, 40), group="chao")
Sprite("tilesets/Tiles/1.png", height=80, center=(680, 40), group="chao")
for i in range(9, 13):
    Sprite("tilesets/Tiles/2.png", height=80, center=(40 + i * 80, 40), group="chao")


def plataforma(x, y):
    Sprite("tilesets/Tiles/13.png", width=80, center=(x - 80, y), group="chao")
    Sprite("tilesets/Tiles/14.png", width=80, center=(x, y), group="chao")
    Sprite("tilesets/Tiles/15.png", width=80, center=(x + 80, y), group="chao")


plataforma(360, 220)
plataforma(720, 390)
plataforma(420, 560)
Rect(center=(-20, 375), width=40, height=750, group="chao")
Rect(center=(1020, 375), width=40, height=750, group="chao")
group["chao"].mass = STATIC

st.estrelas = 0
st.vidas = 3

placar = Text(text="", top_left=(20, 735), font_size=24, color="dark green")
placar["text"] @= lambda: f"Estrelas {st.estrelas}"
Sprite("ninja/Idle__000.png", height=40, center=(890, 715))
vidas = Text(text="", top_left=(915, 735), font_size=24, color="dark green")
vidas["text"] @= lambda: f"x {st.vidas}"
aviso = Text(text="", center=(500, 680), font_size=36, color="dark green")

ninja = Sheet(anchor="bottom", pixel_size=0.2)
ninja.strip("parado", "ninja/Idle__*.png", fps=8)
ninja.strip("correndo", "ninja/Run__*.png", fps=12)
ninja.strip("pulando", "ninja/Jump__*.png", fps=10)
ninja.strip("jogando", "ninja/Throw__*.png", fps=24)
ninja.strip("morto", "ninja/Dead__*.png", fps=12)

robo = Sheet(anchor="bottom", pixel_size=0.16)
robo.strip("andando", "robot/Run (*).png", fps=12)
robo.strip("quebrado", "robot/Dead (*).png", fps=12)


class Kunai(Sprite, source="ninja/Kunai.png", height=44, art_angle=90, group="kunai"):
    def on_update(self, dt):
        seta = vec_from_angle(self.angle, length=700)
        self.move_by(seta.x * dt, 0)


class Robo(Sprite, source=robo, group="robo", hitbox_shape="rect"):
    def setup(self):
        self.meio = self.center.x
        self.vel = Vec2(90, 0)
        self.play("andando")

    def on_update(self, dt):
        if self.center.x > self.meio + 90:
            self.vel.x = -90
            self.flip_x = True
        if self.center.x < self.meio - 90:
            self.vel.x = 90
            self.flip_x = False
        self.move_by(self.vel.x * dt, 0)

    @collide_with("kunai")
    def atingido(self, kunai):
        if self.showing("quebrado"):
            return
        kunai.destroy()
        self.untag("robo")
        self.vel.x = 0
        self.play("quebrado", loops=1)
        play_sound("audio/explosion02.wav")
        self.after(2, self.destroy)


class Heroi(Sprite, source=ninja, group="heroi", hitbox_shape="rect"):
    def setup(self):
        self.vel = Vec2(0, 0)

    def on_update(self, dt):
        if st.vidas == 0:
            self.vel.y -= 2200 * dt
            self.move_by(0, self.vel.y * dt)
            if "bottom" in self.touching_sides and not self.showing("morto"):
                self.play("morto", loops=1)
            return

        if keyp("LEFT"):
            self.vel.x = -280
            self.flip_x = True
        elif keyp("RIGHT"):
            self.vel.x = 280
            self.flip_x = False
        else:
            self.vel.x = 0

        no_chao = "bottom" in self.touching_sides
        pode_pular = recently("no_chao", no_chao, hold=0.12)
        if keyp.once("UP") and pode_pular:
            self.vel.y = 900
            recently.reset("no_chao")
            play_sound("synth/jump.wav")

        if keyp("SPACE") and ready("kunai", 0.4):
            self.play("jogando", loops=1, next="parado")
            kunai = Kunai(center=(self.center.x, self.center.y + 50))
            kunai.rotate_to(self.angle)
            play_sound("synth/throw.wav")

        self.vel.y -= 2200 * dt
        self.move_by(self.vel.x * dt, self.vel.y * dt)
        if self.center.y < 30:
            self.perder()

        if self.showing("jogando"):
            return
        if not no_chao:
            self.play("pulando")
        elif self.vel.x != 0:
            self.play("correndo")
        else:
            self.play("parado")

    @collide_with("estrela")
    def pegou(self, estrela):
        estrela.destroy()
        st.estrelas += 1
        play_sound("synth/coin.wav")
        if st.estrelas == 5:
            aviso.text = "Todas as estrelas!"
            play_sound("audio/Victory.mp3")

    @collide_with("robo")
    def bateu(self, robo):
        self.perder()

    def perder(self):
        if st.vidas == 0:
            return
        st.vidas -= 1
        canvas.shake(6)
        if st.vidas > 0:
            play_sound("audio/sfx-hit-2.wav")
            self.center = (100, 400)
            self.vel = Vec2(0, 0)
            self.blink(1)
        else:
            play_sound("audio/gameover.wav")
            aviso.text = "Fim de jogo"


resolve("heroi", "chao", bounce=0)

heroi = Heroi(center=(100, 400))

for x, y in [(360, 300), (560, 220), (720, 470), (420, 640), (960, 150)]:
    estrela = Sprite("k-rolling-ball/star.png", height=36, center=(x, y), group="estrela")
    estrela.scale_to(1.2, time=0.5, loops="forever", yoyo=True)

Robo(center=(840, 80))
Robo(center=(720, 419))

Sprite("tilesets/Tiles/17.png", width=80, center=(520, 31))
Sprite("tilesets/Tiles/17.png", width=80, center=(600, 31))


@leave_playfield("kunai")
def saiu(kunai):
    kunai.destroy()


run()
