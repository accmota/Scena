"""Duelo — tutorial 30.

Dois jogadores no mesmo teclado, uma arena fechada lida de um arquivo de
fase (levels/duelo.json). Cada nave anda presa a um trilho curvo, para
cima e para baixo, e gira como um volante para mirar; o passo e o giro
chegam aos poucos (chase). Os lasers quicam nas paredes até três vezes e
fazem curva perto do Warp do meio, que puxa só os tiros, com uma força que
cai com o cubo da distância. Duas barreiras de caixas protegem as naves no
começo; asteroides vagam e se dividem em dois; dois pares de bolas dão
voltas num oito em pé e, quando passam perto, um raio elétrico as liga e
queima os lasers. De tempos em tempos uma estrela atravessa a arena: um
tiro a quebra, e ela solta um poder (energia ou escudo) que voa em curva
até onde estava a nave que atirou. Na abertura, cada jogador escolhe a
sua nave (só muda o desenho).

Controles
---------
  Esquerda (azul)     W / S andam no trilho · A / D giram · TAB atira
  Direita (vermelha)  CIMA / BAIXO andam no trilho · ESQ / DIR giram · ENTER atira
  Na escolha          A / D e ESQ / DIR escolhem · TAB e ENTER confirmam
  Na vitória          ESPAÇO volta à escolha

Uso
---
    python examples/duelo.py
"""

from random import choice, uniform
from scena import *

init(width=1280, height=720, title="Duelo")
Stardust(color="violet", color2="teal")
ColorWash("navy", "teal", "purple", amount=0.25)

folha = Sheet("shooter/sheet.png", atlas="shooter/sheet.xml")
fase = Level("levels/duelo.json")
BURACO = fase["buraco"].center
BORDA = 60      # o raio do Warp
PUXAO = 400     # o puxão na borda do Warp: quanto um tiro ali ganha de velocidade por segundo

TECLAS_ESQUERDA = {"cima": "W", "baixo": "S", "esquerda": "A", "direita": "D", "tiro": "TAB"}
TECLAS_DIREITA = {"cima": "UP", "baixo": "DOWN", "esquerda": "LEFT", "direita": "RIGHT", "tiro": "ENTER"}

st.tipo_azul = 1
st.tipo_vermelha = 1
st.vencedor = ""


class Tiro(Sprite, source=folha, height=26, art_angle=90, hitbox_shape="circle", group="tiros"):
    def setup(self):
        self.vel = Vec2(0, 0)
        self.batidas = 0
        # "add" soma a luz do laser ao fundo: o laser brilha, e não custa nada.
        self.blend = "add"

    def on_update(self, dt):
        # perto vale 1 na borda do Warp, 1/2 no dobro da distância, 1/3 no
        # triplo. Ao cubo, o puxão cai depressa: 1/8 no dobro, 1/27 no triplo.
        # Dentro da borda ele não cresce mais; além de 300 nem vale a conta.
        d = distance(self, BURACO)
        if d < 300:
            perto = BORDA / max(d, BORDA)
            self.vel += vec_from_angle(heading(self, BURACO), PUXAO * perto ** 3 * dt)
        self.angle = self.vel.angle
        self.move_by(self.vel.x * dt, self.vel.y * dt)

    @collide_with("parede")
    def bateu(self, parede, info):
        self.batidas += 1
        if self.batidas > 3:
            canvas.hit_at(info, style="disc", radius=10)
            self.destroy()


class Escudo(Circle, radius=44, visual=Shield(style="plasma")):
    def setup(self):
        self.cargas = 0

    @collide_with("tiros")
    def segurou(self, tiro, info):
        tiro.destroy()
        canvas.zap_at(info, color="sky blue")
        play_sound("audio/sfx-hit-2.wav", pitch=1.6)
        self.gastar()

    # O escudo despedaça o asteroide inteiro: dois pedaços nascendo
    # encostados nele gastariam as outras cargas na hora.
    @collide_with("asteroides")
    def rebateu(self, asteroide, info):
        canvas.zap_at(info, color="sky blue")
        canvas.debris_at(asteroide, color="sienna", radius=asteroide.height)
        play_sound("audio/impactPunch_heavy_001.ogg", volume=0.6)
        asteroide.destroy()
        self.gastar()

    def gastar(self):
        self.cargas -= 1
        if self.cargas == 0:
            canvas.burst_at(self, radius=70, rings=True)
            play_sound("audio/impactBell_heavy_000.ogg")
            self.active = False


class Nave(Sprite, source=folha, height=50, art_angle=90, group="naves"):
    def setup(self):
        # Presa ao trilho, a nave não cede: um asteroide quica nela.
        self.mass = STATIC
        self.giro = 0
        self.passo = 0
        self.u = 0.5
        self.energia = 100
        self.jato = Jet(origin=self.center, length=40, width=14, amount=0)
        self.fogo = Fire(center=lambda: self.center - vec_from_angle(self.angle, 22), angle=lambda: self.angle + 180, width=16, length=40, style="plume")
        self.fogo.active = False
        self.escudo = Escudo(center=lambda: self.center)
        self.escudo.active = False

    def on_update(self, dt):
        # O volante: o giro chega aos poucos e volta aos poucos.
        alvo = 0
        if keyp(self.teclas["esquerda"]):
            alvo = 200
        if keyp(self.teclas["direita"]):
            alvo = -200
        self.giro = chase(self.giro, alvo, 5)
        self.rotate_by(self.giro * dt)

        # u é o lugar no trilho: 0 numa ponta, 1 na outra.
        alvo = 0
        if keyp(self.teclas["cima"]):
            alvo = 260
        if keyp(self.teclas["baixo"]):
            alvo = -260
        self.passo = chase(self.passo, alvo, 5)
        self.u += self.passo * dt / self.trilho.length
        if self.u > 1:
            self.u = 1
            self.passo = 0
        if self.u < 0:
            self.u = 0
            self.passo = 0
        self.center = self.trilho.at(self.u)

        # O jato sai do lado de trás do movimento, na linha do trilho, e
        # cresce com a velocidade.
        rumo = self.trilho.angle_at(self.u)
        if self.passo < 0:
            rumo += 180
        self.jato.origin = self.center - vec_from_angle(rumo, 22)
        self.jato.angle = rumo + 180
        self.jato.amount = abs(self.passo) / 160

        if keyp(self.teclas["tiro"]) and self.ready("tiro", 0.3):
            self.atirar()

    def atirar(self):
        tiro = Tiro(frame=self.laser, center=self.center + vec_from_angle(self.angle, 52))
        tiro.vel = vec_from_angle(self.angle, 700)
        tiro.dono = self
        play_sound("space/sfx_laser1.ogg", volume=0.6)

    @when(lambda self: self.energia < 30)
    def pegou_fogo(self):
        self.fogo.active = True

    @when(lambda self: self.energia >= 30)
    def apagou(self):
        self.fogo.active = False

    def on_destroy(self):
        self.jato.destroy()
        self.fogo.destroy()
        self.escudo.destroy()
        self.barra.destroy()


class Asteroide(Sprite, source=folha, frame="meteorBrown_big1.png", height=64,
                hitbox_shape="circle", group="asteroides"):
    def setup(self):
        self.vel = vec_from_angle(uniform(0, 360), uniform(40, 90))
        self.giro = uniform(-60, 60)

    def on_update(self, dt):
        self.rotate_by(self.giro * dt)
        self.move_by(self.vel.x * dt, self.vel.y * dt)

    @collide_with("tiros")
    def atingido(self, tiro, info):
        canvas.debris_at(self, color="sienna", radius=self.height)
        play_sound("audio/impactPunch_heavy_001.ogg", volume=0.6)
        # O grande se divide em dois pequenos, que saem para os lados do tiro.
        if self.height > 40:
            for lado in [90, -90]:
                pedaco = Asteroide(frame="meteorBrown_small1.png", height=30,
                                   center=self.center + vec_from_angle(tiro.vel.angle + lado, 18))
                pedaco.vel = vec_from_angle(tiro.vel.angle + lado, 110)
        tiro.destroy()
        self.destroy()


class Poder(Sprite, source=folha, height=30, group="poderes"):
    def setup(self):
        self.tipo = "energia"


def soltar_poder(de, para):
    # de e para são cópias (x, y) tiradas na hora do tiro: a estrela some, e
    # a nave continua andando. O poder faz uma curva até onde a nave estava,
    # com uma onda por cima, e segue reto até sair da tela.
    # O quadro vai no construtor: é dele que o Scena tira a hitbox e o tamanho.
    if chance(0.5):
        poder = Poder(frame="powerupGreen_shield.png", center=de)
        poder.tipo = "escudo"
    else:
        poder = Poder(frame="pill_green.png", center=de)
    rumo = heading(de, para)
    mx, my = middle_point(de, para)
    desvio = vec_from_angle(rumo + choice([90, -90]), 100)
    longe = vec_from_angle(rumo, 1500)
    x, y = para
    trilha = Track(points=[de, (mx + desvio.x, my + desvio.y), para, (x + longe.x, y + longe.y)])
    trilha.zigzag(amount=16, waves=6)
    poder.move_along(trilha, speed=120)


class Alvo(Circle, radius=16, visual=Sphere("gold"), group="alvo"):
    def setup(self):
        self.estrela = Starburst(center=lambda: self.center, radius=34, color="gold")

    @collide_with("tiros")
    def atingido(self, tiro, info):
        canvas.debris_at(self, color="gold", radius=60)
        play_sound("audio/explosion02.wav", volume=0.6)
        if tiro.dono:
            soltar_poder(tuple(self.center), tuple(tiro.dono.center))
        tiro.destroy()
        self.destroy()

    def on_destroy(self):
        self.estrela.destroy()


def criar_raio(centro):
    # Duas bolas no mesmo oito (em pé), quase meia volta uma atrás da outra:
    # no meio do oito elas passam perto, nas pontas ficam longe.
    trilha = Track.eight(width=160, height=50, center=centro, angle=90)
    bola1 = Circle(center=centro, radius=10, group="parede", visual=Metal("gold"))
    bola2 = Circle(center=centro, radius=10, group="parede", visual=Metal("gold"))
    bola1.move_along(trilha, time=6, loops="forever")
    bola2.move_along(trilha, time=6, loops="forever", phase=0.45)
    raio = Line(p1=lambda: bola1.center, p2=lambda: bola2.center, line_width=8,
                visual=ElectricBolt("cyan"), group="raio")
    raio.bola1 = bola1
    raio.bola2 = bola2
    return raio


resolve("tiros", "parede", bounce=1.0)
resolve("asteroides", ["parede", "caixa", "naves"], bounce=1.0)
resolve("asteroides", "asteroides", bounce=1.0)


@collide("naves", "tiros")
def acertou(nave, tiro, info):
    tiro.destroy()
    canvas.hit_at(info, color="orange")
    play_sound("audio/sfx-hit-2.wav")
    nave.flash(0.1)
    nave.energia -= 10


@collide("naves", "asteroides")
def bateu(nave, asteroide, info):
    canvas.hit_at(info, style="disc", radius=14)
    play_sound("audio/impactPlank_medium_002.ogg", volume=0.5)
    nave.energia -= 2


@collide("tiros", "raio")
def queimou(tiro, raio, info):
    canvas.zap_at(info, color="cyan")
    play_sound("audio/fx2.wav", volume=0.5)
    tiro.destroy()


@collide("tiros", "caixa")
def estourou(tiro, caixa):
    canvas.burst_at(caixa, radius=24)
    canvas.debris_at(caixa, color="peru", radius=24)
    play_sound("audio/explosion01.wav", volume=0.4)
    tiro.destroy()
    caixa.destroy()


@collide("naves", "poderes")
def pegou(nave, poder):
    if poder.tipo == "escudo":
        nave.escudo.cargas = 3
        nave.escudo.active = True
    else:
        nave.energia = min(100, nave.energia + 40)
    nave.pop()
    play_sound("audio/fx1.wav")
    poder.destroy()


@leave_playfield("tiros", "poderes")
def saiu(coisa):
    coisa.destroy()


class Escolha(Act):
    def setup(self):
        st.pronto_azul = False
        st.pronto_vermelha = False
        Text(text="DUELO", center=(640, 600), font_size=80)
        self.azuis = [Sprite(folha, frame="playerShip1_blue.png", height=80, center=(230, 360)),
                      Sprite(folha, frame="playerShip2_blue.png", height=80, center=(430, 360))]
        self.vermelhas = [Sprite(folha, frame="playerShip1_red.png", height=80, center=(850, 360)),
                          Sprite(folha, frame="playerShip2_red.png", height=80, center=(1050, 360))]
        Text(text="I", center=(230, 270), font_size=28)
        Text(text="II", center=(430, 270), font_size=28)
        Text(text="I", center=(850, 270), font_size=28)
        Text(text="II", center=(1050, 270), font_size=28)
        Text(text="A / D escolhe · TAB confirma", center=(330, 180), font_size=20)
        Text(text="ESQ / DIR escolhe · ENTER confirma", center=(950, 180), font_size=20)
        self.aviso_azul = Text(text="", center=(330, 130), font_size=24, color="deep sky blue")
        self.aviso_vermelha = Text(text="", center=(950, 130), font_size=24, color="tomato")

    def on_update(self, dt):
        if keyp.once("A"):
            st.tipo_azul = 1
        if keyp.once("D"):
            st.tipo_azul = 2
        if keyp.once("LEFT"):
            st.tipo_vermelha = 1
        if keyp.once("RIGHT"):
            st.tipo_vermelha = 2
        if keyp.once("TAB"):
            st.pronto_azul = True
            self.aviso_azul.text = "PRONTO"
        if keyp.once("ENTER"):
            st.pronto_vermelha = True
            self.aviso_vermelha.text = "PRONTO"

        for i in range(2):
            self.azuis[i].alpha = 0.25
            self.vermelhas[i].alpha = 0.25
        self.azuis[st.tipo_azul - 1].alpha = 1
        self.vermelhas[st.tipo_vermelha - 1].alpha = 1

        if st.pronto_azul and st.pronto_vermelha:
            change_act(Duelo)


def criar_nave(tipo, cor, lugar, angulo):
    # Os dois tipos só mudam o desenho: playerShip1 ou playerShip2.
    nave = Nave(frame=f"playerShip{tipo}_{cor}.png", center=lugar)
    nave.angle = angulo
    return nave


def criar_asteroides():
    for item in fase.group("asteroide"):
        Asteroide(center=item.center)


class Duelo(Act):
    def setup(self):
        for item in fase.group("parede"):
            item.make(color="#2b3a55")
        for item in fase.group("pedra"):
            pedra = item.make(group="parede", color="#3d5a80", line_width=6)
            pedra.fill = "#1d2d44"
        for item in fase.group("barra"):
            barra = item.make(group="parede", visual=Metal())
            barra.rotate_by(360, time=4, loops="forever")
        for item in fase.group("caixa"):
            item.make(color="peru")
        self.raios = []
        for item in fase.group("raio"):
            self.raios.append(criar_raio(item.center))
        group["parede"].mass = STATIC
        group["caixa"].mass = STATIC
        criar_asteroides()
        Warp(center=BURACO, radius=BORDA, color="violet", spin=0.5)

        self.azul = criar_nave(st.tipo_azul, "blue", fase["azul"].center, 0)
        self.azul.trilho = fase["trilho_azul"].make()
        self.azul.teclas = TECLAS_ESQUERDA
        self.azul.laser = "laserBlue01.png"
        self.vermelha = criar_nave(st.tipo_vermelha, "red", fase["vermelha"].center, 180)
        self.vermelha.trilho = fase["trilho_vermelho"].make()
        self.vermelha.teclas = TECLAS_DIREITA
        self.vermelha.laser = "laserRed01.png"

        self.azul.barra = Rect(top_left=(40, 714), width=300, height=8, color="deep sky blue")
        self.azul.barra["width"] @= lambda: max(self.azul.energia, 0) * 3
        self.vermelha.barra = Rect(top_left=(940, 714), width=300, height=8, color="tomato")
        self.vermelha.barra["width"] @= lambda: max(self.vermelha.energia, 0) * 3

    def on_update(self, dt):
        # O raio só existe quando as duas bolas estão perto.
        for raio in self.raios:
            raio.active = distance(raio.bola1, raio.bola2) < 90

    @every(8)
    def mandar_estrela(self):
        if group["alvo"].empty:
            y = choice([760, -40])
            inicio = (uniform(420, 860), y)
            meio = (uniform(300, 980), 360)
            fim = (uniform(420, 860), 720 - y)
            estrela = Alvo(center=inicio)
            estrela.move_along(Track(points=[inicio, meio, fim]), speed=60, on_done=estrela.destroy)

    @every(15)
    def mais_asteroides(self):
        if group["asteroides"].empty:
            criar_asteroides()

    @when(lambda self: self.azul.energia <= 0 or self.vermelha.energia <= 0)
    def fim(self):
        if self.azul.energia <= 0:
            perdeu = self.azul
            st.vencedor = "VERMELHO"
        else:
            perdeu = self.vermelha
            st.vencedor = "AZUL"
        canvas.explosion_at(perdeu, amount=1.6)
        canvas.debris_at(perdeu, color="gray", radius=70)
        canvas.shake(14)
        play_sound("audio/explosion04.wav")
        perdeu.destroy()
        self.after(3, lambda: change_act(Vitoria))


class Vitoria(Act):
    def setup(self):
        Text(text=f"{st.vencedor} VENCEU", center=(640, 420), font_size=64, color="gold")
        Text(text="aperte ESPAÇO", center=(640, 320), font_size=22)

    def on_update(self, dt):
        if keyp.once("SPACE"):
            change_act(Escolha)


run(Escolha)
