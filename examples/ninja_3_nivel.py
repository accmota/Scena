"""Ninja III · O nível — tutorial 26.

O ninja do tutorial 19 numa fase quatro vezes mais larga que a tela,
desenhada no editor de fases (media/levels/ninja.json): o código lê a fase
(Level), cria as peças de cada grupo (make) e decide o que elas são. A
câmera segue o ninja com folga e atraso (deadzone e chase), o HUD fica
preso à janela (layer="ui"), o fundo e uma fileira de árvores andam mais
devagar que o chão (pan_response), e o jogo começa mostrando a fase
inteira (frame_to).

Controles
---------
  ESQUERDA / DIREITA   andar
  CIMA                 pular
  ESPAÇO               jogar uma kunai

Para ver ou mudar a fase: python -m scena_editor media/levels/ninja.json

Uso
---
    python examples/ninja_3_nivel.py
"""

from scena import *

init(width=1000, height=750, title="Ninja")
Wallpaper("tilesets/BG/BG.png", fit="tile", tile_size=(1000, 750), tile_mode="mirror", pan_response=0.1)
canvas.layers.create("longe", pan_response=0.5, below="default")
for x in range(100, 2600, 300):
    Sprite("tilesets/Object/Tree_3.png", height=130, center=(x, 140), layer="longe")

fase = Level("levels/ninja.json")
canvas.playfield.set(fase.box)

for enfeite in fase.group("enfeite"):
    enfeite.make()
for peca in fase.group("chao"):
    peca.make()
for lugar in fase.group("parede"):
    parede = lugar.make(group="chao")
    parede.visible = False
group["chao"].mass = STATIC

st.estrelas = 0
st.vidas = 3

placar = Text(text="", top_left=(20, 735), font_size=24, color="dark green")
placar["text"] @= lambda: f"Estrelas {st.estrelas}"
Sprite("ninja/Idle__000.png", height=40, center=(890, 715), layer="ui")
vidas = Text(text="", top_left=(915, 735), font_size=24, color="dark green")
vidas["text"] @= lambda: f"x {st.vidas}"
aviso = Text(text="", center=(500, 680), font_size=36, color="dark green", layer="ui")

ninja = Sheet(anchor="bottom", pixel_size=0.2)
ninja.strip("parado", "ninja/Idle__*.png", fps=8)
ninja.strip("correndo", "ninja/Run__*.png", fps=12)
ninja.strip("pulando", "ninja/Jump__*.png", fps=10)
ninja.strip("jogando", "ninja/Throw__*.png", fps=24)
ninja.strip("morto", "ninja/Dead__*.png", fps=12, offset=(0, -19))

robo = Sheet(anchor="bottom", pixel_size=0.16)
robo.strip("andando", "robot/Run (*).png", fps=12, offset=(0, -12))
robo.strip("quebrado", "robot/Dead (*).png", fps=12, offset=(0, -23))


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
        play_sound("audio/explosion02.ogg")
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
        if st.estrelas == len(fase.group("estrela")):
            aviso.text = "Todas as estrelas!"
            play_sound("audio/Victory.mp3")

    @collide_with("robo")
    def bateu(self, robo):
        self.perder()

    @when(lambda self: self.center.y < 30)
    def caiu(self):
        self.perder()

    def perder(self):
        if st.vidas == 0:
            return
        st.vidas -= 1
        canvas.shake(6)
        if st.vidas > 0:
            play_sound("audio/sfx-hit-2.ogg")
            self.center = fase["inicio"].center
            self.vel = Vec2(0, 0)
            self.blink(1)
        else:
            play_sound("audio/gameover.ogg")
            aviso.text = "Fim de jogo"


collision.floor = True
resolve("heroi", "chao", bounce=0)

heroi = Heroi(center=fase["inicio"].center)

for lugar in fase.group("estrela"):
    estrela = Sprite("k-rolling-ball/star.png", height=36, center=lugar.center, group="estrela")
    estrela.scale_to(1.2, time=0.5, loops="forever", yoyo=True)

for lugar in fase.group("robo"):
    Robo(center=lugar.center)

for agua in fase.group("agua"):
    agua.make()


st.seguir = False
canvas.frame_to(fase.box)


@after(2)
def comecar():
    canvas.zoom_to(1, time=1)
    st.seguir = True


def update(dt):
    if not st.seguir:
        return
    olhar = (canvas.pan_x, canvas.pan_y)
    x, y = deadzone(olhar, heroi.center, size=200)
    x = max(x, 500)
    x = min(x, 3500)
    canvas.pan_to(chase(olhar, (x, 375), rate=5))


@leave_playfield("kunai")
def saiu(kunai):
    kunai.destroy()


run()
