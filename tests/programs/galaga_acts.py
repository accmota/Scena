# harness: cwd=examples/media
"""Galaga com atos — Titulo → Fase (fase 1: frota, fase 2: chefe) → FimDeJogo → Titulo.

Cada elemento do jogo é sua própria classe: Heroi, Tiro, TiroInimigo,
Inimigo, Chefe. Os atos decidem o fluxo (o que existe, quando seguir); as
entidades carregam o comportamento (teclas, vidas, mergulhos, rajadas). Os
dados do jogo ficam em st. Nenhuma entidade menciona atos, e não há código
de limpeza: o que um ato cria sai com ele (design/Act Design.md).

Controles
---------
  ESQUERDA / DIREITA   mover
  ESPAÇO               atirar / começar (ou o botão JOGAR no título)
  R                    recomeçar a fase

Uso
---
    python examples/app_galaga_acts.py
"""
from random import uniform

from scena import *

W, H = 1000, 800
init(width=W, height=H, title="Galaga — atos")


# --- o palco: criado antes de run(), vale o jogo todo ------------------------

SkyGradient("night")
Stars(pan_response=0.0, density=0.9, scroll=(0.0, -28.0))
Vignette(amount=0.35)
Bloom(intensity=0.45)

space = Sheet("shooter/sheet.xml")
AREA = canvas.game_view.inset(40)

VEL_HEROI = 340
VEL_TIRO = 560
VEL_TIRO_INIMIGO = 380
VIDA_CHEFE = 30
# O mergulho para esta distância acima do herói: só os tiros acertam.
FOLGA_MERGULHO = 230
FROTA = ("enemyGreen1.png", "enemyRed1.png", "enemyBlue1.png")

def jogo_novo():
    """Os dados de um jogo que começa (topo e Titulo usam o mesmo)."""
    st.pontos = 0
    st.vidas = 3
    st.fase = 1
    st.venceu = False


st.recorde = 0      # vale entre jogos: fora de jogo_novo()
jogo_novo()         # run(Fase) direto, durante o desenvolvimento, também funciona


@leave_playfield("tiro", "tiro_inimigo")
def saiu(tiro):
    tiro.destroy()


# --- tiros -------------------------------------------------------------------

class Tiro(Sprite, source=space, frame="laserBlue01.png", height=28, group="tiro"):
    def on_update(self, dt):
        self.move_by(0, VEL_TIRO * dt)


class TiroInimigo(Sprite, source=space, frame="laserRed01.png", height=26,
                  group="tiro_inimigo", art_angle=90):
    def setup(self):
        self.mirar(-90)

    def mirar(self, angulo):
        self.rumo = angulo
        self.angle = angulo

    def on_update(self, dt):
        self.move_by(angle=self.rumo, distance=VEL_TIRO_INIMIGO * dt)


# --- herói -------------------------------------------------------------------

class Heroi(Sprite, source=space, frame="playerShip1_blue.png", height=45, group="heroi"):
    def setup(self):
        self.glow = Glow(color="skyblue", radius=14, sigma=7)

    def on_update(self, dt):
        if st.vidas == 0:
            return
        dx = 0
        if keyp("LEFT"):
            dx -= VEL_HEROI * dt
        if keyp("RIGHT"):
            dx += VEL_HEROI * dt
        self.move_by(dx, 0)
        self.confine(AREA)
        if keyp("SPACE") and self.ready("atirar", 0.15):
            Tiro(center=self.center + (0, 28))

    @collide_with("tiro_inimigo")
    def atingido(self, tiro):
        tiro.destroy()
        if st.vidas == 0 or self.tagged("ferido"):
            return
        canvas.hit_at(tiro, angle=90)   # faíscas voltam para cima, para quem atirou
        st.vidas -= 1
        canvas.shake(8)
        if st.vidas == 0:
            canvas.explosion_at(self)
            self.dissolve_out(0.5, on_done=self.estacionar)
        else:
            self.tag("ferido")
            self.blink(0.8)
            self.after(0.8, lambda: self.untag("ferido"))

    def estacionar(self):
        self.active = False


# --- inimigos ----------------------------------------------------------------

class Inimigo(Sprite, source=space, height=40, group="inimigo", art_angle=270):
    valor = 100

    def entrar_na_frota(self, vaga):
        self.vaga_x, self.vaga_y = vaga.x, vaga.y
        self.mode = self.chegando

    @on_mode
    def chegando(self):
        self.center = (self.vaga_x, H + 60)
        self.fade_in(0.35)
        self.move_to(self.vaga_x, self.vaga_y, time=1.0, ease="ease_out",
                     then=self.formacao)

    @on_mode
    async def formacao(self):
        every(uniform(2.5, 4.0), self.atirar)
        while True:
            await wait(uniform(4.0, 9.0))
            if chance(0.4):
                self.mode = self.mergulho
                return

    @on_mode
    async def mergulho(self):
        heroi = group["heroi"].nearest(self)
        if not heroi:
            self.mode = self.formacao
            return
        self.pulse_outline(color="tomato", duration=0.3)
        await self.move_to(heroi.center.x, heroi.center.y + FOLGA_MERGULHO,
                           time=1.1, ease="ease_in", face=True)
        self.atirar()
        await self.move_to(self.vaga_x, self.vaga_y, time=1.0, ease="ease_out",
                           face=True)
        self.reset_rotation()
        self.mode = self.formacao

    def atirar(self):
        TiroInimigo(center=self.center + (0, -20))

    @collide_with("tiro")
    def atingido(self, tiro):
        tiro.destroy()
        if self.mode != self.morrendo:
            self.mode = self.morrendo

    @on_mode
    def morrendo(self):
        st.pontos += self.valor
        canvas.burst_at(self, radius=40)
        self.dissolve_out(0.3, on_done=self.destroy)


class Chefe(Sprite, source=space, frame="ufoRed.png", height=120, group="chefe"):
    def setup(self):
        self.vida = VIDA_CHEFE
        self.mode = self.chegando

    @on_mode
    def chegando(self):
        self.move_to(W / 2, 600, time=2.0, ease="ease_out", then=self.lutando)

    @on_mode
    def lutando(self):
        self.move_along(Track.eight(width=560, height=90, center=self.center),
                        time=6.0, loops="forever")
        self.rotate_by(360, time=3.0, loops="forever")
        every(1.6, self.rajada)

    def rajada(self):
        for angulo in (-130, -110, -90, -70, -50):
            TiroInimigo(center=self.center).mirar(angulo)

    @collide_with("tiro")
    def atingido(self, tiro):
        tiro.destroy()
        if self.mode != self.lutando:
            return
        canvas.hit_at(tiro, angle=-90)  # o tiro vem de baixo: faíscas para baixo
        self.vida -= 1
        self.flash(0.08)
        if self.vida == 0:
            self.mode = self.morrendo

    @on_mode
    async def morrendo(self):
        st.pontos += 5000
        for _ in range(6):
            canvas.explosion_at(self.center + (uniform(-50, 50), uniform(-40, 40)),
                                amount=0.7)
            await wait(0.2)
        self.dissolve_out(0.6, on_done=self.destroy)


def montar_frota():
    grade = Box(center=(W / 2, 590), width=760, height=170).grid(8, 3, gap=16)
    for linha, celulas in enumerate(grade.rows):
        for celula in celulas:
            Inimigo(frame=FROTA[linha]).entrar_na_frota(celula.center)


# --- atos ---------------------------------------------------------------------

def comecar():
    jogo_novo()
    change_act(Fase)


def zerar_recorde():
    st.recorde = 0


class Titulo(Act):
    def setup(self):
        Text("GALAGA", center=(W / 2, H * 0.68), font_size=72, color="gold")
        for i, quadro in enumerate(FROTA):
            nave = Sprite(space, frame=quadro, height=40,
                          center=(W / 2 + (i - 1) * 90, H * 0.56))
            nave.scale_to(1.1, time=0.5, loops="forever", yoyo=True)

        # Botões de jogo feitos da arte do kit (cresce no hover, afunda no clique).
        SpriteButton("k-rolling-ball/button_yellow.png", center=(W / 2, H * 0.40),
                     width=150, label="JOGAR", label_color="sienna",
                     label_inset=(0, 0, 0, 8), breathe=True, on_click=comecar)
        zerar = SpriteButton("k-rolling-ball/button_blue.png", center=(W / 2, H * 0.30),
                             width=150, label="zerar recorde", label_inset=(0, 0, 0, 8),
                             on_click=zerar_recorde)
        zerar["enabled"] @= lambda: st.recorde > 0    # cinza enquanto não há recorde
        Text("ou aperte ESPAÇO", center=(W / 2, H * 0.21), font_size=18)

        play_sound("audio/Victory.mp3")

    def on_update(self, dt):
        if keyp.once("SPACE"):
            comecar()


class Fase(Act):
    def setup(self):
        Heroi(center=(W / 2, 70))
        placar = Text("", top_left=(20, H - 12), font_size=20)
        placar["text"] @= lambda: (
            f"Fase  {st.fase}      Pontos  {st.pontos}      Vidas  {st.vidas}"
        )
        if st.fase == 1:
            self.mode = self.frota
        else:
            self.mode = self.batalha_do_chefe

    def on_update(self, dt):
        # Uma Fase nova com 0 vidas nunca veria a mudança para 0: "perdeu" não dispararia.
        if keyp.once("R") and st.vidas > 0:
            change_act(Fase)

    @when(lambda self: st.vidas == 0)
    def perdeu(self):
        st.venceu = False
        self.after(1.5, lambda: change_act(FimDeJogo))

    @on_mode
    async def frota(self):
        faixa = Text("FASE 1", center=(W / 2, H / 2), font_size=48)
        await wait(1.5)
        faixa.dissolve_out(0.4, on_done=faixa.destroy)
        montar_frota()
        await until_empty("inimigo")
        await wait(1.0)
        st.fase = 2
        change_act(Fase)

    @on_mode
    async def batalha_do_chefe(self):
        aviso = Text("CUIDADO — CHEFE CHEGANDO", center=(W / 2, H / 2),
                     font_size=36, color="tomato")
        aviso.blink(2.5)
        await wait(2.5)
        aviso.destroy()
        Chefe(center=(W / 2, H + 100))
        await until_empty("chefe")
        await wait(1.5)
        st.venceu = True
        change_act(FimDeJogo)


class FimDeJogo(Act):
    def setup(self):
        st.recorde = max(st.recorde, st.pontos)
        if st.venceu:
            Text("VOCÊ VENCEU!", center=(W / 2, H * 0.6), font_size=64, color="gold")
            canvas.fireworks_at((W / 2, H * 0.6))
        else:
            Text("FIM DE JOGO", center=(W / 2, H * 0.6), font_size=64, color="tomato")
        Text(f"Pontos  {st.pontos}      Recorde  {st.recorde}",
             center=(W / 2, H * 0.48), font_size=26)
        Text("aperte ESPAÇO", center=(W / 2, H * 0.36), font_size=20)
        self.after(10, lambda: change_act(Titulo))

    def on_update(self, dt):
        if keyp.once("SPACE"):
            change_act(Titulo)


run(Titulo)
