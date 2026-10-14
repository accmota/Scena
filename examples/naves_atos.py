"""Naves VI · Atos — tutorial 25.

O jogo de naves do tutorial 24 dividido em atos: um título com um botão
JOGAR, a fase e o fim de jogo. Recomeçar é trocar de ato, sem código de
limpeza; os pontos, as vidas e o recorde ficam no st, que atravessa os
atos. A fase tem dois capítulos (modos async): a frota, até o grupo
esvaziar, e a batalha do chefe, que termina na vitória.

Controles
---------
  clique em JOGAR      começar
  ESQUERDA / DIREITA   mover
  ESPAÇO               atirar; no fim de jogo, voltar ao título
  R                    recomeçar

Uso
---
    python examples/naves_atos.py
"""

from random import uniform
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



def jogo_novo():
    st.pontos = 0
    st.vidas = 3
    st.energia = 0
    st.velocidade = 80
    st.venceu = False


st.recorde = 0
jogo_novo()

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
        self.jato = Jet(origin=lambda: (self.center.x, self.center.y + 20),
                        angle=90, length=30, width=12, amount=2)
        self.jato.active = False

    @on_mode
    async def chegando(self):
        await wait(self.espera)
        await self.move_by(0, -500, time=1.2, ease="ease_out")
        await wait(0.3)
        self.pop(scale=1.3)
        play_sound("audio/impactGeneric_light_003.ogg")
        self.mode = self.formacao

    @on_mode
    def formacao(self):
        every(uniform(5, 12), self.atirar)
        after(uniform(3, 12), then=self.mergulho)

    @on_mode
    def mergulho(self):
        alvo = self.center.x
        heroi = group["heroi"].nearest(self)
        if heroi:
            alvo = heroi.center.x
        self.jato.active = True
        self.move_to(alvo, 220, time=0.9, ease="ease_in_out",
                     loops=2, yoyo=True, then=self.formacao)
        after(0.9, self.atirar)

    @exit_mode(mergulho)
    def fim_do_mergulho(self):
        self.jato.active = False

    def atirar(self):
        TiroInimigo(center=(self.center.x, self.center.y - 20))

    @collide_with("tiros")
    def atingido(self, tiro):
        Explosao(center=self.center)
        if chance(0.2):
            Poder(center=self.center)
        tiro.destroy()
        self.destroy()
        st.pontos += 1

    def on_destroy(self):
        self.jato.destroy()


class Chefe(Sprite, source=folha, frame="ufoRed.png", height=110, group="chefe"):
    def setup(self):
        self.vida = 0
        self.barra = Rect(top_left=(300, 775), width=0, height=10, color="tomato")
        self.barra["width"] @= lambda: self.vida * 20
        self.mode = self.chegando

    @on_mode
    async def chegando(self):
        aviso = Text(text="CUIDADO: O CHEFE", center=(500, 400), font_size=40, color="tomato")
        aviso.blink(2)
        play_sound("audio/laser-big.wav", pitch=0.5)
        await wait(2)
        aviso.destroy()
        await self.move_to(750, 600, time=2, ease="ease_out")
        for vez in range(20):
            self.vida += 1
            play_sound("audio/impactGeneric_light_003.ogg")
            await wait(0.05)
        self.mode = self.lutando

    @on_mode
    def lutando(self):
        self.move_by(-500, 0, time=3, ease="ease_in_out", loops="forever", yoyo=True)
        every(1.0, self.rajada)

    def rajada(self):
        for dx in [-40, 0, 40]:
            TiroInimigo(center=(self.center.x + dx, self.center.y - 50))
        play_sound("audio/laser7.wav")

    @collide_with("tiros")
    def atingido(self, tiro, info):
        tiro.destroy()
        if self.mode != self.lutando:
            return
        canvas.hit_at(info)
        self.flash(0.08)
        self.vida -= 1
        if self.vida == 0:
            self.mode = self.morrendo

    @on_mode
    async def morrendo(self):
        for vez in range(5):
            canvas.explosion_at(self.center + (uniform(-50, 50), uniform(-30, 30)), amount=0.6)
            play_sound("audio/explosion02.wav")
            await wait(0.3)
        canvas.shake(14)
        Explosao(center=self.center)
        st.pontos += 20
        Starburst(center=self.center, radius=110)
        self.destroy()

    def on_destroy(self):
        self.barra.destroy()


class Poder(Sprite, source=folha, frame="powerupBlue_shield.png", height=30, group="poderes"):
    def on_update(self, dt):
        self.move_by(0, -150 * dt)


class Escudo(Circle, radius=38, visual=Shield(style="plasma")):
    @collide_with("tiros_inimigos")
    def bloqueou(self, tiro, info):
        canvas.zap_at(info, color="sky blue")
        play_sound("audio/sfx-hit-2.wav", pitch=1.6)
        tiro.destroy()
        st.energia -= 20


class Heroi(Sprite, source=folha, frame="playerShip1_red.png", height=45, group="heroi"):
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


FROTA = ["enemyBlack1.png", "enemyBlue3.png", "enemyGreen4.png"]


def comecar():
    jogo_novo()
    change_act(Fase)


class Titulo(Act):
    def setup(self):
        Text(text="NAVES", center=(500, 520), font_size=80)
        Text(text=f"Recorde {st.recorde}", center=(500, 430), font_size=24)
        SpriteButton("k-rolling-ball/button_blue.png", center=(500, 330), width=180,
                     label="JOGAR", label_inset=(0, 0, 0, 8), on_click=comecar)


class Fase(Act):
    def setup(self):
        placar = Text(text="", top_left=(20, 780), font_size=20)
        placar["text"] @= lambda: f"Pontos {st.pontos}"

        Sprite(folha, frame="playerLife1_red.png", height=24, center=(900, 768))
        vidas = Text(text="", top_left=(920, 780), font_size=20)
        vidas["text"] @= lambda: f"x {st.vidas}"

        barra = Rect(top_left=(20, 745), width=200, height=8, color="sky blue")
        barra["width"] @= lambda: st.energia * 2

        Heroi(center=(500, 70))
        self.mode = self.batalha

    @on_mode
    async def batalha(self):
        for linha in range(3):
            for coluna in range(8):
                inimigo = Inimigo(frame=FROTA[linha], center=(185 + coluna * 90, 1220 - linha * 70))
                inimigo.hue = coluna / 8
                inimigo.espera = (2 - linha) * 0.6 + coluna * 0.08
                inimigo.mode = inimigo.chegando
        await until_empty("inimigos")
        await wait(1)
        Chefe(center=(750, 1000))
        await until_empty("chefe")
        await wait(2)
        st.venceu = True
        change_act(FimDeJogo)

    def on_update(self, dt):
        group["inimigos"].move_by(st.velocidade * dt, 0)

        for inimigo in group["inimigos"]:
            if inimigo.center.x > 960:
                st.velocidade = -80
            if inimigo.center.x < 40:
                st.velocidade = 80

        if keyp.once("R"):
            comecar()

    @when(lambda self: st.vidas == 0)
    def perdeu(self):
        self.after(2, lambda: change_act(FimDeJogo))


class FimDeJogo(Act):
    def setup(self):
        st.recorde = max(st.recorde, st.pontos)
        if st.venceu:
            Text(text="VOCÊ VENCEU", center=(500, 480), font_size=56, color="gold")
        else:
            Text(text="FIM DE JOGO", center=(500, 480), font_size=56, color="tomato")
        Text(text=f"Pontos {st.pontos}   Recorde {st.recorde}", center=(500, 400), font_size=24)
        Text(text="aperte ESPAÇO", center=(500, 330), font_size=18)
        self.after(10, lambda: change_act(Titulo))

    def on_update(self, dt):
        if keyp.once("SPACE"):
            change_act(Titulo)


@leave_playfield("tiros", "tiros_inimigos", "poderes")
def saiu(tiro):
    tiro.destroy()


run(Titulo)
