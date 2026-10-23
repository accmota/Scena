"""Guardião do Anel.

Um anel de luz flutua no espaço, com uma luz viva no meio. A nave do
guardião voa em volta do anel e atira para fora; ondas de inimigos
geométricos saem de portais. Duas vezes no jogo a câmera vira para o lado
do ataque; as marcas em volta, como num relógio, mostram para onde ela virou.

Duas vidas: a da nave e a do anel. Se uma delas acaba, o jogo acaba.

Os ataques vêm em ondas, escritas numa tabela (ONDAS): de que lado vem,
que inimigos, quantos, como a câmera mostra o anel (longe, normal, perto),
o brilho da tela, quando a próxima onda começa, se a câmera vira e
quantas minas cruzam a tela. Para inventar uma onda, escreva mais uma.

A mina não ataca: só cruza a tela na frente do anel. Um tiro nela faz uma
grande explosão que destrói os inimigos em volta, e outras minas explodem
em cadeia.

Às vezes um inimigo destruído solta uma pílula. Ela desce para o anel;
passe com a nave por cima dela para pegar um poder por alguns segundos:

  azul       DUPLO    as duas luzes atiram junto com a nave
  verde      RÁPIDO   tiros duas vezes mais seguidos
  amarela    FORTE    tiros maiores, que tiram 2 de vida e atravessam
  vermelha   ESCUDO   um portal em volta do anel destrói o que encostar

Coisas para experimentar
------------------------
  Uma onda nova      mais um dict em ONDAS (20 cristais de todos os lados?)
  As duas luzes      mude AFASTAMENTO e o rate do chase: coladas na nave,
                     ou uma cauda comprida quando ela anda
  Um poder novo      uma pílula que devolve vida à nave (st.vida += 3)
  Um inimigo novo    uma classe com vida, pontos e explodir(), no grupo
                     "inimigos". Duas ideias:
                     Constelação: três estrelas (Circle) ligadas por Line,
                     girando, que descem em espiral, soltam minas e
                     explodem num raio (canvas.zap_at, style="fork");
                     Orbitante: uma bolinha com Halo que entra em órbita,
                     atira para dentro, depois mergulha e implode
                     (implode e canvas.ripple_at)

Controles
---------
  ESQUERDA / DIREITA   a nave gira em volta do anel
  ESPAÇO               atira; um inimigo quase na frente (MIRA) puxa o tiro
  R                    recomeça, depois do fim

Uso
---
    python examples/guardiao.py
"""

from random import choice, uniform
from scena import *

init(width=1280, height=800, title="Guardião do Anel")

CENTRO = Vec2(640, 400)
RAIO = 115          # o meio do anel
LARGURA = 16        # a largura do anel
ORBITA = RAIO + 26  # a nave voa por fora do anel, logo acima da borda
PORTA = 600         # a distância do centro de onde os inimigos saem
TRAVESSIA = 360     # a distância do centro por onde as minas cruzam a tela
VIDA_NAVE = 12
VIDA_ANEL = 30
GIRO = 160          # graus por segundo
AFASTAMENTO = 24    # graus entre a nave e cada luz
CADENCIA = 0.2      # segundos entre dois tiros
DURACAO = 12        # segundos que um poder dura
MIRA = 5            # a abertura do radar de cada tiro, em graus
ESTOURO = 130       # o raio da explosão de uma mina

# O céu: nuvens que giram devagar e filamentos por cima. Os dois viram com
# a câmera, como o resto do mundo.
ChurningClouds(color="royal blue", color2="dark magenta", alpha=0.7,
               speed=0.25, rotation_response=1)
FilamentField(color="teal", alpha=0.45, rotation_response=1)
brilho = Bloom(intensity=0.6)
Vignette()


# O anel: um disco com as cores da roda, um disco preto por cima (o furo)
# e duas bordas de luz.
anel = Circle(center=CENTRO, radius=RAIO + LARGURA / 2, group="anel")
anel.fill = Gradient("deep sky blue", "medium purple", "magenta",
                     "deep sky blue", type="sweep")
anel.rotate_by(360, time=40, loops="forever")   # a roda de cores gira
Circle(center=CENTRO, radius=RAIO - LARGURA / 2, color="black")
for r in (RAIO - LARGURA / 2, RAIO + LARGURA / 2):
    Circle(center=CENTRO, radius=r, visual=Halo("cyan", style="line"))


# Marcas fixas em volta, como as horas de um relógio: quando a câmera vira,
# elas viram junto e mostram para onde.
for hora in range(12):
    tamanho = 6 if hora % 3 == 0 else 3
    Circle(center=CENTRO + vec_from_angle(30 * hora, 330), radius=tamanho,
           color=Color("white").with_alpha(0.35))


# O núcleo: quatro luzes dançam em oitos que se cruzam no centro. Onde
# elas se encontram, as cores somam e a luz fica branca.
CORES = ["magenta", "cyan", "gold", "lime"]
LUZES = []
for i in range(4):
    oito = Track.eight(width=130, height=45, center=CENTRO, angle=45 * i)
    guia = Point(CENTRO.x, CENTRO.y)
    guia.move_along(oito, time=4 + 1.3 * i, loops="forever")
    LUZES.append(GlowSpot(center=lambda guia=guia: guia.center, radius=32,
                          color=CORES[i]))
nucleo = Orb(center=CENTRO, radius=10, color="white", glow=1.4)
tween(nucleo["radius"], 12, time=3, loops="forever", yoyo=True, ease="ease_in_out")


# O núcleo mostra a vida do anel: as luzes apagam e o centro avermelha.
def pintar_nucleo():
    forca = st.anel / VIDA_ANEL
    for luz in LUZES:
        luz.amount = 0.2 + 0.8 * forca
    nucleo.color = lerp(Color("white"), Color("orange red"), 1 - forca)


def ferir_anel():
    if st.anel <= 0:
        return
    st.anel -= 1
    pintar_nucleo()
    anel.flash()
    canvas.shake(5)


def novo_jogo():
    st.vida = VIDA_NAVE
    st.anel = VIDA_ANEL
    st.pontos = 0
    st.brilho = 0.5     # o brilho da tela que a onda pede
    pintar_nucleo()

novo_jogo()


# Um ponto do anel. O ângulo nunca volta a 0: depois de três voltas ele
# vale 1080, e tudo continua certo. Assim as luzes que seguem a nave
# nunca dão a volta errada quando ela passa de 359 para 360.
def no_anel(angulo, r=ORBITA):
    return CENTRO + vec_from_angle(angulo, r)


# A área do jogo fica fixa em volta do anel, mesmo com a câmera girando.
canvas.playfield.set(left=-700, bottom=-900, right=1980, top=1700)

@leave_playfield("tiros", "balas", "pilulas", "minas")
def saiu(coisa):
    coisa.destroy()


class Tiro(Sprite, source="space/laserBlue03.png", height=36, art_angle=90,
           group="tiros"):
    def setup(self):
        self.glow = CheapGlow("deep sky blue", radius=8)
        self.dano = 1
        self.atravessa = False

    def fortalecer(self):
        self.dano = 2
        self.atravessa = True       # passa pelo inimigo e segue em frente
        self.scale_to(1.5)
        self.glow = CheapGlow("gold", radius=14)

    def on_update(self, dt):
        self.move_by(distance=800 * dt)    # para a frente, para onde aponta


# As pílulas de poder: cada cor dá um poder.
PILULAS = {
    "duplo": "space/pill_blue.png",
    "rapido": "space/pill_green.png",
    "forte": "space/pill_yellow.png",
    "escudo": "space/pill_red.png",
}

class Pilula(Sprite, height=30, group="pilulas"):
    def setup(self):
        self.glow = CheapGlow("white", radius=10)
        self.move_to(CENTRO, speed=60)          # desce devagar para o anel
        self.rotate_by(360, time=2, loops="forever")


def soltar_pilula(lugar):
    poder = choice(list(PILULAS))
    pilula = Pilula(PILULAS[poder], center=lugar)
    pilula.poder = poder


@collide("pilulas", "nave")
def pegou(pilula, nave):
    pilula.destroy()
    nave.ganhar(pilula.poder)


@collide("pilulas", "anel")
def caiu_no_anel(pilula, anel):
    pilula.destroy()            # ninguém pegou: perdida


# A nave são dois triângulos do mesmo tom: um comprido e um largo e baixo,
# meio transparente. Ferida, a nave esquenta: o tom vai do azul ao laranja
# passando pelo roxo e pelo vermelho (o matiz dá a volta: 1.05 é 0.05).
def cor_da_nave(saturacao, alpha=1):
    dano = 1 - st.vida / VIDA_NAVE
    return Color.from_hsv(0.56 + 0.49 * dano, saturacao, 1, alpha)

class Nave(Triangle, group="nave"):
    def setup(self):
        self.angulo = 90        # onde a nave está no anel (e para onde aponta)
        self.recarga = 0
        self["color"] @= lambda: cor_da_nave(0.85)
        self.glow = True
        self.asa = Triangle(center=lambda: self, angle=lambda: self.angle,
                            radius=16, base_ratio=1.35)
        self.asa["color"] @= lambda: cor_da_nave(0.45, alpha=0.6)
        # as duas luzes seguem a nave, uma de cada lado, com atraso
        self.luz_a = self.luz_b = self.angulo
        self.luzes = [GlowSpot(radius=18, color="aqua"),
                      GlowSpot(radius=18, color="aqua")]
        self.faiscas = None
        # quantos segundos falta para cada poder acabar (0 = desligado)
        self.poderes = {"duplo": 0, "rapido": 0, "forte": 0, "escudo": 0}
        self.escudo = None

    def on_update(self, dt):
        if keyp("LEFT"):
            self.angulo += GIRO * dt
        if keyp("RIGHT"):
            self.angulo -= GIRO * dt
        self.center = no_anel(self.angulo)
        self.angle = self.angulo
        self.luz_a = chase(self.luz_a, self.angulo + AFASTAMENTO, rate=5)
        self.luz_b = chase(self.luz_b, self.angulo - AFASTAMENTO, rate=5)
        self.luzes[0].center = no_anel(self.luz_a)
        self.luzes[1].center = no_anel(self.luz_b)

        for poder in self.poderes:
            self.poderes[poder] = max(0, self.poderes[poder] - dt)
        if self.escudo and self.poderes["escudo"] == 0:
            self.escudo.destroy()
            self.escudo = None

        self.recarga -= dt
        if keyp("SPACE") and self.recarga <= 0:
            self.atirar(self.angulo)
            if self.poderes["duplo"] > 0:
                self.atirar(self.luz_a)
                self.atirar(self.luz_b)
            if self.poderes["rapido"] > 0:
                self.recarga = CADENCIA / 2
            else:
                self.recarga = CADENCIA

    def atirar(self, angulo):
        origem = no_anel(angulo, ORBITA + 34)
        # a mira ajuda: um radar estreito na frente do tiro (2,5 graus para
        # cada lado); se pega um inimigo, o tiro vai no mais perto
        alvos = collision.query_sector(origem, angle=angulo, radius=800,
                                       spread=MIRA, group="inimigos")
        if alvos:
            alvo = min(alvos, key=lambda inimigo: distance(origem, inimigo))
            angulo = heading(origem, alvo)
        tiro = Tiro(center=origem, angle=angulo)
        if self.poderes["forte"] > 0:
            tiro.fortalecer()

    def ganhar(self, poder):
        self.poderes[poder] = DURACAO
        self.pop(scale=1.4)
        if poder == "escudo" and self.escudo is None:
            # o escudo é um portal em volta do anel e da nave
            self.escudo = Portal(center=CENTRO, radius=ORBITA + 55,
                                 color="orange red", amount=1.2, group="escudo")

    def ferir(self):
        if st.vida <= 0:
            return
        st.vida -= 1
        self.blink(0.3)
        canvas.shake(8)

    @when(lambda self: st.vida <= 3)
    def avariada(self):
        self.faiscas = Sparks(center=lambda: self.center, radius=18, rate=60,
                              amount=1.5, color="orange")

    @when(lambda self: st.vida <= 0)
    def destruida(self):
        canvas.explosion_at(self, amount=1.4)
        self.destroy()

    def on_destroy(self):
        self.asa.destroy()
        for luz in self.luzes:
            luz.destroy()
        if self.faiscas:
            self.faiscas.destroy()
        if self.escudo:
            self.escudo.destroy()


# Os tiros dos inimigos ("balas"). Cada inimigo atira do seu jeito.
class Bala(Sprite, source="space/laserRed01.png", height=26, art_angle=90,
           group="balas"):
    def on_update(self, dt):
        self.move_by(distance=210 * dt)


class Raio(Sprite, source="space/laserGreen02.png", height=34, art_angle=90,
           group="balas"):
    def on_update(self, dt):
        self.move_by(distance=310 * dt)


@collide("balas", "nave")
def bala_na_nave(bala, nave):
    bala.destroy()
    canvas.hit_at(bala, color="orange")
    nave.ferir()


@collide("balas", "anel")
def bala_no_anel(bala, anel):
    bala.destroy()
    canvas.hit_at(bala, style="disc", color="magenta")
    ferir_anel()


# As regras de todos os inimigos. Cada inimigo tem a sua vida, os seus
# pontos e o seu jeito de explodir (explodir); o resto é igual para todos.
@collide("tiros", ["inimigos", "minas"])
def acertou(tiro, inimigo):
    if not tiro.atravessa:
        tiro.destroy()
    inimigo.vida -= tiro.dano
    if inimigo.vida <= 0:
        destruir(inimigo)
    else:
        canvas.hit_at(tiro, color="white")
        inimigo.flash()
        inimigo.scale_by(0.92)      # cada tiro encolhe um pouco


def destruir(inimigo):
    st.pontos += inimigo.pontos
    brilho.intensity += 0.25        # cada explosão acende a tela um instante
    if chance(0.25):
        soltar_pilula(inimigo.center)
    inimigo.explodir()


# O escudo destrói tudo o que encosta nele.
@collide("balas", "escudo")
def bala_no_escudo(bala, escudo):
    bala.destroy()
    canvas.hit_at(bala, style="disc", color="orange")


@collide("inimigos", "escudo")
def inimigo_no_escudo(inimigo, escudo):
    destruir(inimigo)


@collide("inimigos", "anel")
def invadiu(inimigo, anel):
    ferir_anel()
    inimigo.explodir()


@collide("inimigos", "nave")
def trombou(inimigo, nave):
    nave.ferir()
    inimigo.explodir()


# Seta: um triângulo fino com outro dentro, ao contrário. Voa reto para o
# anel, atira uma vez no caminho e se joga no anel.
class Seta(Triangle, radius=26, base_ratio=0.8, color="tomato",
           group="inimigos"):
    vida = 1
    pontos = 10

    def setup(self):
        self.angle = heading(self, CENTRO)
        self.miolo = Triangle(center=lambda: self, angle=lambda: self.angle + 180,
                              radius=10, color="gold")
        if chance(0.7):                  # nem toda seta atira
            self.after(uniform(1.2, 2), self.atirar)

    def on_update(self, dt):
        self.move_by(distance=140 * dt)

    def atirar(self):
        Bala(center=self.center, angle=self.angle)

    def explodir(self):
        canvas.burst_at(self, radius=30)
        self.destroy()

    def on_destroy(self):
        self.miolo.destroy()


# Mandala: dois pentágonos meio transparentes, girando um contra o outro,
# com uma luz atrás. Para longe do anel e atira cinco balas em roda.
class Mandala(RegularPolygon, n=5, radius=30, group="inimigos"):
    vida = 3
    pontos = 30

    def setup(self):
        self.color = Color("orchid").with_alpha(0.4)
        self.par = RegularPolygon(n=5, radius=30, center=lambda: self,
                                  angle=lambda: 36 - self.angle)
        self.par.color = Color("deep sky blue").with_alpha(0.4)
        self.luz = GlowSpot(center=lambda: self.center, radius=46,
                            color="medium purple", amount=0.4)
        lado = heading(CENTRO, self) + uniform(-30, 30)   # cada uma num lugar
        self.move_to(no_anel(lado, 420), time=3, ease="ease_out")
        self.every(2.4, self.atirar)
        self.after(12, lambda: self.move_to(CENTRO, speed=40))   # depois, desce

    def on_update(self, dt):
        self.rotate_by(50 * dt)

    def atirar(self):
        for i in range(5):
            Bala(center=self.center, angle=self.angle + 72 * i)

    def explodir(self):
        canvas.burst_at(self, radius=60, amount=6)
        canvas.fireworks_at(self, color="violet", radius=80)
        self.destroy()

    def on_destroy(self):
        self.par.destroy()
        self.luz.destroy()


# Cristal: um hexágono de gelatina com um triângulo dentro. Lento e duro,
# e mira na nave.
class Cristal(RegularPolygon, n=6, radius=30, group="inimigos"):
    vida = 5
    pontos = 50

    def setup(self):
        self.visual = Gel("turquoise")
        self.miolo = Triangle(center=lambda: self, angle=lambda: -self.angle,
                              radius=13, color="aquamarine")
        self.move_to(CENTRO, speed=30)
        self.every(2.0, self.atirar)

    def on_update(self, dt):
        self.rotate_by(30 * dt)

    def atirar(self):
        nave = group["nave"].nearest(self)
        if nave:
            Raio(center=self.center, angle=heading(self, nave))

    def explodir(self):
        canvas.debris_at(self, color="turquoise", radius=60)
        canvas.burst_at(self, radius=60, amount=6)
        self.destroy()

    def on_destroy(self):
        self.miolo.destroy()


# Mina: um círculo com anéis que pulsam devagar. Não ataca: só cruza a tela
# na frente do anel. Um tiro nela faz uma grande explosão que destrói os
# inimigos em volta; as outras minas perto explodem também, em cadeia.
# Ela fica no grupo "minas", e não em "inimigos": a onda não espera por ela.
class Mina(Circle, radius=20, color="dark red", group="minas"):
    vida = 1
    pontos = 20

    def setup(self):
        self.visual = Halo("orange red", style="pulse", rings=2, speed=0.5)

    def explodir(self):
        onde = (self.center.x, self.center.y)
        self.destroy()      # sai antes, para a explosão em cadeia não voltar nela
        canvas.burst_at(onde, radius=ESTOURO, amount=6)
        canvas.ripple_at(onde, amount=0.6, radius=2 * ESTOURO)
        for vizinho in collision.query_circle(onde, radius=ESTOURO, group="inimigos"):
            if vizinho.active:          # uma mina da cadeia pode já ter levado
                st.pontos += vizinho.pontos
                canvas.debris_at(vizinho, color="silver", radius=50)
                vizinho.destroy()
        for mina in collision.query_circle(onde, radius=ESTOURO, group="minas"):
            if mina.active:
                st.pontos += mina.pontos
                mina.explodir()


# Uma mina cruza a tela de um lado ao outro, a TRAVESSIA do centro, de frente
# para o lado do ataque: passa na frente do anel, longe do grupo que chega.
def cruzar_mina(lado):
    if lado is None:
        lado = uniform(0, 360)
    sentido = choice([90, -90])
    frente = no_anel(lado, TRAVESSIA)
    mina = Mina(center=frente + vec_from_angle(lado + sentido, 650))
    mina.move_to(frente + vec_from_angle(lado - sentido, 650), speed=70,
                 on_done=mina.destroy)


# Como a câmera mostra o anel em cada onda: (zoom, quanto ela anda para o
# lado do ataque). longe: o anel fica pequeno, para ver todos os lados.
# perto: o anel fica grande e embaixo, com espaço em cima para o ataque (por
# isso a onda perto vem sempre do lado que está para cima na tela).
VISTAS = {"longe": (0.55, 0), "normal": (0.75, 100), "perto": (1.05, 240)}

# As ondas, uma depois da outra.
#   lado       de onde vêm (o ângulo no anel); None = de todos os lados
#   tipos      os inimigos, sorteados um a um (repetir um tipo o faz mais comum)
#   quantos    quantos inimigos; cada: segundos entre um e outro
#   vista      longe, normal ou perto (VISTAS)
#   claridade  a força do Bloom
#   fim        "limpar" espera todos morrerem; um número espera esses
#              segundos (ou todos morrerem)
#   virar      (se houver) a câmera vira o lado do ataque para cima
#   minas      (se houver) quantas minas cruzam a tela durante a onda
ONDAS = [
    dict(nome="Setas do norte", lado=90, tipos=[Seta], quantos=16, cada=0.4,
         vista="perto", claridade=0.5, fim="limpar"),
    dict(nome="Mandalas", lado=210, tipos=[Mandala], quantos=5, cada=1.2,
         vista="normal", claridade=0.9, fim=10, minas=2),
    dict(nome="Mistura do sul", lado=270, tipos=[Seta, Seta, Cristal], quantos=18,
         cada=0.4, vista="normal", claridade=0.6, fim="limpar"),
    dict(nome="Cerco", lado=None, tipos=[Seta], quantos=30, cada=0.3,
         vista="longe", claridade=0.8, fim="limpar", minas=3),
    dict(nome="Cristais", lado=330, tipos=[Cristal], quantos=6, cada=1.5,
         vista="perto", claridade=0.7, fim="limpar", virar=True),
    dict(nome="Enxame", lado=330, tipos=[Seta], quantos=50, cada=0.12,
         vista="normal", claridade=1.0, fim="limpar", minas=2),
    dict(nome="Coroa", lado=None, tipos=[Mandala, Cristal], quantos=10, cada=0.7,
         vista="longe", claridade=1.0, fim=12, minas=3),
    dict(nome="Leste", lado=0, tipos=[Seta, Seta, Mandala, Cristal], quantos=20,
         cada=0.4, vista="perto", claridade=1.2, fim="limpar", virar=True),
    dict(nome="Tempestade", lado=None, tipos=[Seta, Seta, Seta, Mandala, Cristal],
         quantos=45, cada=0.3, vista="longe", claridade=1.2, fim="limpar", minas=4),
]


def chegar(tipo, lado):
    if lado is None:
        lado = uniform(0, 360)
    tipo(center=no_anel(lado + uniform(-15, 15), PORTA))


def anunciar(texto):
    aviso = Text(texto, center=(640, 70), font_size=40, color="white", layer="ui")
    aviso.after(2, lambda: aviso.fade_out(1, on_done=aviso.destroy))


# Os portais por onde a onda entra. De um lado: um portal de frente para o
# anel. De todos os lados: um portal enorme em volta de tudo.
def abrir_portal(lado):
    if lado is None:
        return Portal(center=CENTRO, radius=PORTA, color="medium purple", amount=0.7)
    return Portal(center=no_anel(lado, PORTA), radius=120, tilt=60, angle=lado + 90,
                  color="magenta")


class Jogo(Act):
    def setup(self):
        canvas.zoom_to(0.75)
        self.nave = Nave(radius=28, base_ratio=0.55)
        self.placar = Text("", top_left=(24, 780), color="white")
        self.placar["text"] @= lambda: (
            f"NAVE {st.vida}     ANEL {st.anel}     PONTOS {st.pontos}")
        self.painel = Text("", top_right=(1256, 780), color="gold")
        self.acabou = False
        self.ondas = self.run_task(self.diretor)

    # O diretor: conta a história do jogo, uma onda depois da outra.
    async def diretor(self):
        await wait(1.5)
        for numero, onda in enumerate(ONDAS):
            lado = onda["lado"]
            anunciar(f"ONDA {numero + 1}   {onda['nome']}")
            st.brilho = onda["claridade"]
            # a câmera aproxima ou afasta, e anda para o lado do ataque
            zoom, avanco = VISTAS[onda["vista"]]
            canvas.zoom_to(zoom, time=2, ease="ease_in_out")
            if lado is None:
                canvas.pan_to(CENTRO, time=2, ease="ease_in_out")
            else:
                canvas.pan_to(no_anel(lado, avanco), time=2, ease="ease_in_out")
            if onda.get("virar"):
                canvas.rotate_to(90 - lado, time=2, ease="ease_in_out")
            await wait(2)

            # um vento sopra do lado do ataque para o anel (na tela, o ângulo
            # inclui o giro da câmera)
            if lado is not None:
                vento = WindStreaks(angle=lado + 180 + canvas.rotation,
                                    density=0.9, alpha=0.6)
                self.after(2.5, vento.remove)
            for i in range(onda.get("minas", 0)):
                self.after(1 + 3 * i, lambda: cruzar_mina(lado))
            portal = abrir_portal(lado)
            for i in range(onda["quantos"]):
                chegar(choice(onda["tipos"]), lado)
                await wait(onda["cada"])
            self.after(1, portal.destroy)

            fim = onda["fim"]
            if fim == "limpar":
                await until_empty("inimigos")
                brasas = Embers(color="gold", density=1.2)    # onda vencida
                self.after(3, brasas.remove)
                await wait(1.5)
            else:
                await race(wait(fim), until_empty("inimigos"))
        await until_empty("inimigos")
        canvas.fireworks_at(CENTRO, color="cyan", radius=160)
        Embers(color="gold", density=1.5)
        self.terminar("O ANEL ESTÁ SALVO")

    def on_update(self, dt):
        # o brilho da tela volta devagar ao que a onda pede
        brilho.intensity = chase(brilho.intensity, st.brilho, rate=1.5)
        # os poderes ligados, no canto da tela
        ligados = [poder.upper() for poder, falta in self.nave.poderes.items()
                   if falta > 0 and st.vida > 0]
        self.painel.text = "   ".join(ligados)
        if self.acabou and keyp.once("R"):
            novo_jogo()
            change_act(Jogo)

    @when(lambda self: st.anel <= 0)
    def anel_caiu(self):
        canvas.explosion_at(CENTRO, amount=2.5, flash=True)

    @when(lambda self: st.vida <= 0 or st.anel <= 0)
    def perdeu(self):
        self.ondas.cancel()
        self.terminar("FIM")

    def terminar(self, titulo):
        self.acabou = True
        self.after(1.5, lambda: Text(titulo + "\nR para recomeçar", center=CENTRO,
                                     font_size=44, color="white", layer="ui"))

run(Jogo)
