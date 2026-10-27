"""Ninja V · Espada — tutorial 28.

A fase do tutorial 27 (media/levels/ninja_perigos.json): as caixas, que lá
são enfeite, aqui só a espada quebra. Ao lado de uma caixa, ESPAÇO é um
golpe de espada; longe, continua sendo uma kunai. A espada é uma segunda
caixa de colisão posta à mão nos pixels do golpe (add_hitbox com px_rect)
e ligada só nos quadros em que a lâmina está para fora (espada["active"]
@= lambda: self.showing(GOLPE)). A caixa quebrada vira cacos (debris_at) e
deixa uma luz (Orb); quem pega a luz fica invencível por alguns segundos,
com uma Aura dourada que pisca no fim (run_task, wait).

Controles
---------
  ESQUERDA / DIREITA   andar
  CIMA                 pular
  BAIXO                descer de uma plataforma
  ESPAÇO               golpe de espada (perto de uma caixa) ou kunai
  R                    recomeçar

Uso
---
    python examples/ninja_5_espada.py
"""

from scena import *

init(width=1000, height=750, title="Ninja")
Wallpaper("tilesets/BG/BG.png", fit="tile", tile_size=(1000, 750), tile_mode="mirror", pan_response=0.1)
canvas.layers.create("longe", pan_response=0.5, below="default")
for x in range(100, 2600, 300):
    Sprite("tilesets/Object/Tree_3.png", height=130, center=(x, 140), layer="longe")

fase = Level("levels/ninja_perigos.json")
canvas.playfield.set(fase.box)

GOLPE = ("Attack__004", "Attack__005", "Attack__006")


def jogo_novo():
    st.estrelas = 0
    st.vidas = 3
    st.descer = False
    st.aviso = ""


jogo_novo()

placar = Text(text="", top_left=(20, 735), font_size=24, color="dark green")
placar["text"] @= lambda: f"Estrelas {st.estrelas}"
Sprite("ninja/Idle__000.png", height=40, center=(890, 715), layer="ui")
vidas = Text(text="", top_left=(915, 735), font_size=24, color="dark green")
vidas["text"] @= lambda: f"x {st.vidas}"
aviso = Text(text="", center=(500, 680), font_size=36, color="dark green", layer="ui")
aviso["text"] @= lambda: st.aviso

ninja = Sheet(anchor="bottom", pixel_size=0.2)
ninja.strip("parado", "ninja/Idle__*.png", fps=8)
ninja.strip("correndo", "ninja/Run__*.png", fps=12)
ninja.strip("pulando", "ninja/Jump__*.png", fps=10)
ninja.strip("jogando", "ninja/Throw__*.png", fps=24)
ninja.strip("espada", "ninja/Attack__*.png", fps=20, offset=(50, -42))
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
        self.vel = Vec2(90, 0)
        self.play("andando")

    def on_update(self, dt):
        if self.vel.x > 0 and not self.floor_below(dx=40, group=["chao", "plataforma"]):
            self.vel.x = -90
            self.flip_x = True
        if self.vel.x < 0 and not self.floor_below(dx=-40, group=["chao", "plataforma"]):
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


class Heroi(Sprite, source=ninja, group="heroi", hitbox_shape="rect", hitbox_anchor="bottom"):
    def setup(self):
        self.vel = Vec2(0, 0)
        self.tilt = "ground"
        self.invencivel = False
        self.add_hitbox(group="dor")
        self.prepare_fx(ElectricField, Aura)
        espada = self.add_hitbox(group="espada", px_rect=(400, 60, 136, 375))
        espada["active"] @= lambda: self.showing(GOLPE)

    def on_update(self, dt):
        if st.vidas == 0:
            self.vel.y -= 2200 * dt
            self.move_by(0, self.vel.y * dt)
            if "bottom" in self.touching_sides and not self.showing("morto"):
                self.play("morto", loops=1)
            return

        if self.showing("espada"):
            self.vel.x = 0
        elif keyp("LEFT"):
            self.vel.x = -280
            self.flip_x = True
        elif keyp("RIGHT"):
            self.vel.x = 280
            self.flip_x = False
        else:
            self.vel.x = 0

        st.descer = recently("descer", keyp.once("DOWN"), hold=0.2)

        no_chao = "bottom" in self.touching_sides
        pode_pular = recently("no_chao", no_chao, hold=0.12)
        if keyp.once("UP") and pode_pular:
            self.vel.y = 900
            recently.reset("no_chao")
            play_sound("synth/jump.wav")

        if keyp("SPACE") and not self.showing("espada"):
            caixa = group["caixa"].nearest(self, within=75)
            if caixa:
                self.flip_x = caixa.center.x < self.center.x
                self.play("espada", loops=1, next="parado")
                play_sound("synth/throw.wav")
            elif ready("kunai", 0.4):
                self.play("jogando", loops=1, next="parado")
                kunai = Kunai(center=(self.center.x, self.center.y + 50))
                kunai.rotate_to(self.angle)
                play_sound("synth/throw.wav")

        self.vel.y -= 2200 * dt
        self.move_by(self.vel.x * dt, self.vel.y * dt)

        if self.showing(("jogando", "espada")):
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
            st.aviso = "Todas as estrelas!"
            play_sound("audio/Victory.mp3")

    @collide_with("luz")
    def pegou_luz(self, luz):
        luz.destroy()
        play_sound("audio/impactBell_heavy_000.ogg")
        self.run_task(self.brilhar, name="invencivel")

    async def brilhar(self):
        self.invencivel = True
        self.restore_visual()
        self.visual = Aura("gold")
        await wait(4)
        for vez in range(10):
            self.visual = None
            await wait(0.1)
            self.visual = Aura("gold")
            await wait(0.1)
        self.visual = None
        self.invencivel = False

    @when(lambda self: self.center.y < 30)
    def caiu(self):
        self.perder()
        if st.vidas > 0:
            self.center = fase["inicio"].center
            self.vel = Vec2(0, 0)

    def perder(self):
        if st.vidas == 0 or self.invencivel:
            return
        st.vidas -= 1
        canvas.shake(6)
        if st.vidas > 0:
            play_sound("audio/sfx-hit-2.ogg")
            self.blink(1.5)
            self.untag("dor")
            self.after(1.5, lambda: self.tag("dor"))
        else:
            play_sound("audio/gameover.ogg")
            st.aviso = "Fim de jogo · R recomeça"


collision.floor = True
resolve("heroi", "chao", bounce=0)
resolve("heroi", "caixa", bounce=0)
resolve("heroi", "plataforma", bounce=0, only=lambda c: c.side == "bottom" and not st.descer)

@collide("robo", "dor")
def encostou(robo, heroi, info):
    heroi.perder()


@collide("raio", "dor")
def choque(raio, heroi, info):
    if heroi.invencivel:
        return
    heroi.perder()
    heroi.save_visual()
    heroi.visual = ElectricField("cyan")
    heroi.glow = "light blue"
    heroi.after(2.5, heroi.restore_visual, name="choque")


@collide("espada", "caixa")
def quebrou(heroi, caixa, info):
    canvas.debris_at(caixa, color="peru", fall=1)
    play_sound("audio/impactPlank_medium_002.ogg")
    Orb(center=caixa.center, radius=14, color="gold", group="luz")
    caixa.destroy()


@collide("kunai", "caixa")
def cravou(kunai, caixa, info):
    kunai.destroy()


@leave_playfield("kunai")
def saiu(kunai):
    kunai.destroy()



class Fase(Act):
    def setup(self):
        for enfeite in fase.group("enfeite"):
            enfeite.make()
        for caixa in fase.group("caixa"):
            caixa.make()
        for peca in fase.group("chao"):
            peca.make()
        for peca in fase.group("plataforma"):
            peca.make()
        elevador = fase["elevador"].make(group="plataforma", visual=Metal("gold"))
        elevador.move_by(0, 360, time=3, ease="ease_in_out", loops="forever", yoyo=True)
        for lugar in fase.group("parede"):
            parede = lugar.make(group="chao")
            parede.visible = False
        group["chao"].mass = STATIC
        group["plataforma"].mass = STATIC
        group["caixa"].mass = STATIC

        self.heroi = Heroi(center=fase["inicio"].center)

        for lugar in fase.group("estrela"):
            estrela = Sprite("k-rolling-ball/star.png", height=36, center=lugar.center, group="estrela")
            estrela.scale_to(1.2, time=0.5, loops="forever", yoyo=True)

        for lugar in fase.group("robo"):
            Robo(center=lugar.center)

        for agua in fase.group("agua"):
            agua.make()

        for lugar in fase.group("raio"):
            lugar.make(visual=ElectricField("cyan", amount=10))

        self.seguir = False
        canvas.frame_to(fase.box)
        self.after(2, self.comecar)

    def comecar(self):
        canvas.zoom_to(1, time=1)
        self.seguir = True

    @every(1.5)
    def piscar(self):
        for raio in group["raio"]:
            raio.active = not raio.active

    def on_update(self, dt):
        if keyp.once("R"):
            jogo_novo()
            change_act(Fase)
            return
        if not self.seguir:
            return
        olhar = (canvas.pan_x, canvas.pan_y)
        x, y = deadzone(olhar, self.heroi.center, size=200)
        x = max(x, 500)
        x = min(x, 3500)
        canvas.pan_to(chase(olhar, (x, 375), rate=5))


run(Fase)
