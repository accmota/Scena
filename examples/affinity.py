"""Afinidade.

Um mundo de átomos inventados num prato de laboratório. Lembra água e óleo,
mas não é química de verdade: são poucas regras, escolhidas para dar um
movimento bonito.

Os átomos
---------
Cada cor é um elemento. Dois números dizem o que ele faz:

  valência   quantas ligações fortes ele aceita
  avidez     o quanto ele puxa a carga para si (de 0 a 1)

  branco     pequeno, valência 1, avidez baixa
  vermelho   valência 2, avidez alta
  âmbar      valência 2, avidez baixa (quase a do branco)
  verde      íon: não faz ligação forte, tem carga + fixa
  violeta    íon: não faz ligação forte, tem carga - fixa

Duas ligações
-------------
  forte   (linha cheia) junta átomos de elementos diferentes numa molécula.
          Só acontece num choque rápido o bastante, e não se desfaz sozinha.
  fraca   (linha tracejada) junta uma ponta + a uma ponta - de moléculas
          diferentes. O branco segura uma só, o vermelho duas, um íon
          várias. Ela puxa como um fio, mais forte quanto mais perto;
          esticada demais, arrebenta; e o calor a desfaz e refaz o tempo todo.

A carga vem das ligações: um átomo solto é neutro. Ligado a um vizinho mais
ávido, ele fica + (brilho azul) e o vizinho fica - (brilho rosa). Cargas
iguais se empurram, opostas se puxam. Por isso o branco preso ao vermelho
fica carregado e faz ligações fracas, e o branco preso ao âmbar fica quase
neutro e não faz: as duas moléculas não se misturam.

Ninguém se amontoa: dois átomos sem ligação forte se empurram quando chegam
perto (uma casca macia em volta de cada um), e cada vez mais forte se
encostam (o núcleo duro). A casca vence as outras forças, então até uma
ligação fraca deixa uma folga entre as duas moléculas.

Coisas para experimentar
------------------------
  1   Nascente: brancos e vermelhos soltos reagem e viram moléculas
  2   Coroas: cada íon junta moléculas vermelhas em volta de si
  3   Ilhas: as moléculas de vermelho e as de âmbar se separam sozinhas
  R   Acaso: valência e avidez ao acaso para as mesmas cores
  Esfrie tudo: a rede de ligações fracas para de se mexer (um gelo).
  Esquente: as ligações fracas não duram, e uma faísca desfaz as fortes.

Controles
---------
  CIMA / BAIXO       esquenta / esfria
  ARRASTAR O MOUSE   mexe o líquido
  ESPAÇO             uma faísca onde está o mouse: quebra as ligações perto
  1 2 3 R            as receitas acima
  T                  liga e desliga o rastro

Uso
---
    python examples/affinity.py
"""
from math import cos, sin, radians
from random import random, shuffle, uniform
from scena import *

LARGURA, ALTURA = 1280, 800
init(width=LARGURA, height=ALTURA, title="Affinity")
Wallpaper(Gradient("#03060c", "#0b1424", angle=90))
Bloom(intensity=0.6)
Vignette()
rastro = MotionTrail(fade=0.85)
rastro.enabled = False

CX, CY = 640, 400   # o centro do prato
PRATO = 330         # o raio do prato

# cor, tamanho, valência, avidez, quantas ligações fracas, carga fixa (íons)
ELEMENTOS = {
    "branco":   dict(cor="#dff1ff", raio=8, valencia=1, avidez=0.2, fracas=1, carga=0),
    "vermelho": dict(cor="#ff5b4f", raio=13, valencia=2, avidez=0.9, fracas=2, carga=0),
    "ambar":    dict(cor="#ffb02e", raio=13, valencia=2, avidez=0.25, fracas=2, carga=0),
    "verde":    dict(cor="#5cf08a", raio=12, valencia=0, avidez=0.5, fracas=5, carga=1),
    "violeta":  dict(cor="#b07cff", raio=14, valencia=0, avidez=0.5, fracas=5, carga=-1),
}
ORIGINAIS = {nome: dict(e) for nome, e in ELEMENTOS.items()}

ALCANCE = 80        # mais longe que isso, dois átomos não se veem
FORMA = 46          # mais perto que isso, uma ligação fraca pode nascer
ROMPE = 70          # mais esticada que isso, a ligação fraca arrebenta
ATIVACAO = 90       # rapidez mínima de um choque que faz ligação forte
ANGULO = 105        # o ângulo entre as duas ligações de um átomo de valência 2
CASCA = 2000        # o empurrão de quem chega perto (casca macia)...
FIM_CASCA = 1.5     # ...até 1,5 vezes a distância em que se encostam
DURO = 20000        # o núcleo duro: cresce depressa quando se encostam
MOLA = 600          # a rigidez da ligação forte
MOLA_ANGULO = 150   # a rigidez do ângulo
FIO = 1500          # o puxão da ligação fraca
CARGA = 120         # cargas iguais se empurram, opostas se puxam
COLA = 80           # moléculas logo fora da casca se puxam um pouco
BOLA = 0.6          # a bola desenhada é menor que o átomo: sobra lugar para a haste
ARRASTO = 2.5       # o líquido freia quem anda
AGITO = 420         # o quanto o calor sacode
QUEBRA = 20         # o quanto o calor desfaz as ligações fracas
FAISCA = 90         # o alcance da faísca
POLO = 0.15         # menos carga que isso: o átomo não faz ligação fraca (nem brilha)

st.calor = 0.4      # 0: gelado · 1: fervendo
st.receita = "Nascente"

atomos = []
fortes = []         # [a, b, linha]
fracas = []         # [a, b, linha, força]
angulos = []        # [b, c, distância]: dois vizinhos do mesmo átomo
linhas_livres = []
# os tons da ligação fraca: quanto mais forte, mais visível
TONS_FIO = [Color("aquamarine").with_alpha(0.3 + 0.7 * k / 8) for k in range(9)]
st.mudou = True     # alguma ligação forte nasceu ou morreu


class Atomo:
    """Os números de um átomo, num objeto Python comum.

    O Circle só desenha. Ler um campo de um Circle passa pelo Scena (que
    vigia cada mudança para as fórmulas), e o passo do mundo lê dezenas de
    milhares de números por frame: em números soltos ele fica muitas vezes
    mais rápido.
    """

    def __init__(self, nome, x, y):
        e = ELEMENTOS[nome]
        self.nome = nome
        self.x, self.y = x, y
        self.vx = self.vy = 0
        self.raio = e["raio"]
        self.valencia = e["valencia"]
        self.avidez = e["avidez"]
        self.max_fracas = e["fracas"]
        self.carga_fixa = e["carga"]
        self.carga = self.carga_fixa
        self.vizinhos = []      # ligações fortes
        self.pontes = []        # ligações fracas
        self.molecula = self    # um átomo da molécula, o mesmo para todos
        self.bola = Circle(center=(x, y), radius=e["raio"] * BOLA, color=e["cor"])
        self.brilho = None
        atomos.append(self)


def nova_linha():
    if linhas_livres:
        linha = linhas_livres.pop()
        linha.visible = True
        return linha
    linha = Line(p1=(0, 0), p2=(0, 0))
    linha.blend = "add"
    return linha


def guarda_linha(linha):
    linha.visible = False
    linhas_livres.append(linha)


def liga_forte(a, b):
    linha = nova_linha()
    linha.dash = "solid"
    linha.line_width = 3
    linha.color = Color.interpolate(a.bola.color, b.bola.color, 0.5).with_alpha(0.9)
    fortes.append([a, b, linha])
    a.vizinhos.append(b)
    b.vizinhos.append(a)
    st.mudou = True


def liga_fraca(a, b):
    linha = nova_linha()
    linha.dash = "dash"
    linha.line_width = 2.5
    fracas.append([a, b, linha, 1])
    a.pontes.append(b)
    b.pontes.append(a)


def solta(lista, ligacao):
    a, b, linha = ligacao[:3]
    lista.remove(ligacao)
    guarda_linha(linha)
    if lista is fortes:
        a.vizinhos.remove(b)
        b.vizinhos.remove(a)
        st.mudou = True
    else:
        a.pontes.remove(b)
        b.pontes.remove(a)


def entende_moleculas():
    """Quem está em que molécula, a carga de cada átomo, os ângulos."""
    for a in atomos:
        a.molecula = None
    for a in atomos:
        if a.molecula is None:
            # todos os que se alcançam por ligações fortes são uma molécula
            a.molecula = a
            fila = [a]
            while fila:
                b = fila.pop()
                for c in b.vizinhos:
                    if c.molecula is None:
                        c.molecula = a
                        fila.append(c)
    for a in atomos:
        # cada vizinho mais ávido puxa um pouco de carga deste átomo
        a.carga = a.carga_fixa
        for b in a.vizinhos:
            a.carga += b.avidez - a.avidez
        # o brilho mostra a carga: azul +, rosa -, nada se é quase neutro
        if a.carga > POLO:
            brilho = "deep sky blue"
        elif a.carga < -POLO:
            brilho = "hot pink"
        else:
            brilho = None
        if brilho != a.brilho:
            a.brilho = brilho
            a.bola.glow = CheapGlow(brilho, radius=8) if brilho else None
    # uma ligação fraca dentro da mesma molécula não faz sentido
    for ligacao in list(fracas):
        if ligacao[0].molecula is ligacao[1].molecula:
            solta(fracas, ligacao)
    # dois vizinhos do mesmo átomo ficam num ângulo certo um do outro
    angulos.clear()
    for a in atomos:
        for i in range(len(a.vizinhos)):
            for j in range(i + 1, len(a.vizinhos)):
                b, c = a.vizinhos[i], a.vizinhos[j]
                lado_b = (a.raio + b.raio) * 1.1
                lado_c = (a.raio + c.raio) * 1.1
                # a lei dos cossenos: a distância entre b e c
                d2 = lado_b ** 2 + lado_c ** 2 - 2 * lado_b * lado_c * cos(radians(ANGULO))
                angulos.append([b, c, d2 ** 0.5])
    st.mudou = False


def puxa(a, b, forca, ax, ay):
    """Uma força entre a e b: positiva aproxima, negativa afasta."""
    dx = b.x - a.x
    dy = b.y - a.y
    d = (dx * dx + dy * dy) ** 0.5 or 1
    fx = forca * dx / d
    fy = forca * dy / d
    ax[a.i] += fx
    ay[a.i] += fy
    ax[b.i] -= fx
    ay[b.i] -= fy


def agitar(dt):
    """Um passo do mundo: forças, ligações que nascem e morrem, movimento."""
    dt = min(dt, 1 / 30)
    calor = st.calor
    if st.mudou:
        entende_moleculas()
    n = len(atomos)
    ax = [0.0] * n
    ay = [0.0] * n
    for i in range(n):
        atomos[i].i = i

    # o prato em quadras do tamanho do ALCANCE: cada átomo só olha a sua
    # quadra e as vizinhas
    quadras = {}
    for a in atomos:
        chave = (int(a.x // ALCANCE), int(a.y // ALCANCE))
        if chave not in quadras:
            quadras[chave] = []
        quadras[chave].append(a)

    candidatas = []     # ligações fracas que podem nascer
    choques = []        # ligações fortes que podem nascer
    for (qx, qy), aqui in quadras.items():
        # metade das quadras vizinhas: assim cada par aparece uma vez só
        ao_lado = []
        for chave in ((qx + 1, qy), (qx - 1, qy + 1), (qx, qy + 1), (qx + 1, qy + 1)):
            ao_lado += quadras.get(chave, [])
        for k in range(len(aqui)):
            a = aqui[k]
            for b in aqui[k + 1:] + ao_lado:
                dx = b.x - a.x
                dy = b.y - a.y
                d2 = dx * dx + dy * dy
                if d2 >= ALCANCE * ALCANCE or d2 == 0:
                    continue
                d = d2 ** 0.5
                encosta = a.raio + b.raio
                casca = encosta * FIM_CASCA
                forca = 0
                # ninguém se amontoa: a casca empurra quem chega perto, e o
                # núcleo, cada vez mais, quem se encosta (a mola da ligação
                # forte é quem cuida dos vizinhos)
                if d < casca and b not in a.vizinhos:
                    if d < encosta:
                        # reto e íngreme: mais duro que isso (ou uma curva
                        # como 1/d²), um passo de 1/60 s passa do ponto e o
                        # par ganha velocidade em vez de perder
                        forca -= CASCA + DURO * (encosta - d) / encosta
                    else:
                        forca -= CASCA * (casca - d) / (casca - encosta)
                if a.molecula is not b.molecula:
                    qq = a.carga * b.carga
                    perto = 1 - d / ALCANCE
                    forca -= CARGA * qq * perto
                    if d < casca + 10:
                        forca += COLA
                    if (qq < 0 and d < FORMA and abs(a.carga) > POLO
                            and abs(b.carga) > POLO and b not in a.pontes):
                        candidatas.append((-qq * (1 - d / ROMPE), a, b))
                    if d < casca and a.nome != b.nome:
                        # um choque de frente, rápido o bastante; medido na
                        # entrada da casca: dentro dela os dois já frearam
                        rapidez = -((b.vx - a.vx) * dx + (b.vy - a.vy) * dy) / d
                        if rapidez > ATIVACAO:
                            choques.append((a, b))
                if forca:
                    fx = forca * dx / d
                    fy = forca * dy / d
                    ax[a.i] += fx
                    ay[a.i] += fy
                    ax[b.i] -= fx
                    ay[b.i] -= fy

    # ligações fortes novas: só quem tem valência sobrando
    for a, b in choques:
        if (len(a.vizinhos) < a.valencia and len(b.vizinhos) < b.valencia
                and a.molecula is not b.molecula):
            liga_forte(a, b)
            # agora são uma molécula só
            antiga = b.molecula
            for c in atomos:
                if c.molecula is antiga:
                    c.molecula = a.molecula
            canvas.zap_at(a.x, a.y, Color.interpolate(a.bola.color, b.bola.color, 0.5),
                          radius=16, count=6)

    # ligações fracas novas: as mais fortes primeiro
    candidatas.sort(key=lambda c: c[0], reverse=True)
    for forca, a, b in candidatas:
        if (len(a.pontes) < a.max_fracas and len(b.pontes) < b.max_fracas
                and b not in a.pontes and a.molecula is not b.molecula):
            liga_fraca(a, b)

    # a ligação forte é uma mola: puxa ou empurra até o tamanho certo
    for a, b, linha in fortes:
        d = ((b.x - a.x) ** 2 + (b.y - a.y) ** 2) ** 0.5
        puxa(a, b, MOLA * (d - (a.raio + b.raio) * 1.1), ax, ay)
    for b, c, certa in angulos:
        d = ((c.x - b.x) ** 2 + (c.y - b.y) ** 2) ** 0.5
        puxa(b, c, MOLA_ANGULO * (d - certa), ax, ay)

    # a ligação fraca é um fio: só puxa, mais forte quanto mais perto
    for ligacao in list(fracas):
        a, b = ligacao[0], ligacao[1]
        d = ((b.x - a.x) ** 2 + (b.y - a.y) ** 2) ** 0.5
        forca = 1 - d / ROMPE
        # o calor desfaz as ligações fracas; as de carga alta duram mais
        quebra = QUEBRA * calor ** 2 / (abs(a.carga * b.carga) + 0.1)
        if forca <= 0 or random() < quebra * dt:
            solta(fracas, ligacao)
            continue
        ligacao[3] = forca
        # perto demais, a casca empurra mais do que o fio puxa: sobra uma folga
        puxa(a, b, FIO * abs(a.carga * b.carga) * forca, ax, ay)

    # o movimento: forças, o freio do líquido, a sacudida do calor
    # (a sacudida cresce com a raiz do passo: assim o calor não depende dos fps)
    agito = AGITO * (calor / dt) ** 0.5
    mexendo = mouse.press() and (mouse.dx or mouse.dy)
    mx, my = mouse.x, mouse.y
    for a in atomos:
        a.vx += (ax[a.i] + uniform(-agito, agito)) * dt
        a.vy += (ay[a.i] + uniform(-agito, agito)) * dt
        a.vx -= a.vx * ARRASTO * dt
        a.vy -= a.vy * ARRASTO * dt
        if mexendo:
            perto = 1 - distance((a.x, a.y), (mx, my)) / 120
            if perto > 0:
                a.vx += (mouse.dx / dt - a.vx) * perto * 0.3
                a.vy += (mouse.dy / dt - a.vy) * perto * 0.3
        a.x += a.vx * dt
        a.y += a.vy * dt
        # a parede do prato devolve quem sai
        dx = a.x - CX
        dy = a.y - CY
        r = (dx * dx + dy * dy) ** 0.5
        fora = r - (PRATO - a.raio)
        if fora > 0:
            a.x -= dx / r * fora
            a.y -= dy / r * fora
            para_fora = (a.vx * dx + a.vy * dy) / r
            if para_fora > 0:
                a.vx -= 2 * para_fora * dx / r
                a.vy -= 2 * para_fora * dy / r
        a.bola.move_to(a.x, a.y)

    # as linhas
    for a, b, linha in fortes:
        linha.p1 = (a.x, a.y)
        linha.p2 = (b.x, b.y)
    for a, b, linha, forca in fracas:
        linha.p1 = (a.x, a.y)
        linha.p2 = (b.x, b.y)
        # poucos tons: a linha só repinta quando muda de tom
        linha.color = TONS_FIO[round(forca * 8)]


def faisca(x, y):
    """Quebra as ligações perto de (x, y) e sacode os átomos."""
    canvas.zap_at(x, y, "white", radius=FAISCA, style="spark", flash=True)
    for a in atomos:
        perto = 1 - distance((a.x, a.y), (x, y)) / FAISCA
        if perto > 0:
            for ligacao in [f for f in fortes if a in f[:2]]:
                solta(fortes, ligacao)
            for ligacao in [f for f in fracas if a in f[:2]]:
                solta(fracas, ligacao)
            a.vx += uniform(-1, 1) * 400 * perto
            a.vy += uniform(-1, 1) * 400 * perto


def esvazia():
    for ligacao in fortes + fracas:
        guarda_linha(ligacao[2])
    fortes.clear()
    fracas.clear()
    for a in atomos:
        a.bola.destroy()
    atomos.clear()
    st.mudou = True


def lugares(espaco):
    """Pontos de uma grade de favo dentro do prato, embaralhados.

    Cada átomo (ou molécula) nasce num ponto: ninguém nasce em cima de
    ninguém (o núcleo duro o jogaria longe) e não é preciso procurar lugar
    (procurar ao acaso num prato quase cheio chegava a levar segundos).
    """
    pontos = []
    linha = 0
    y = CY - PRATO
    while y < CY + PRATO:
        x = CX - PRATO + (espaco / 2 if linha % 2 else 0)
        while x < CX + PRATO:
            if distance((x, y), (CX, CY)) < PRATO - 24:
                pontos.append((x, y))
            x += espaco
        y += espaco * 0.866     # as linhas de um favo ficam mais juntas
        linha += 1
    shuffle(pontos)
    return pontos


def molecula(centro, lados, x, y):
    """Um átomo central com um branco em cada um dos lados (ângulo ANGULO)."""
    a = Atomo(centro, x, y)
    d = (a.raio + ELEMENTOS["branco"]["raio"]) * 1.1
    virada = uniform(0, 360)
    for k in range(lados):
        rumo = radians(virada + k * ANGULO)
        liga_forte(a, Atomo("branco", x + d * cos(rumo), y + d * sin(rumo)))


def receita(nome):
    esvazia()
    for elemento, valores in ORIGINAIS.items():
        ELEMENTOS[elemento].update(valores)
    st.receita = nome
    mostra_elementos()
    if nome == "Nascente":
        lugar = lugares(34)
        for k in range(70):
            Atomo("vermelho", *lugar.pop())
        for k in range(140):
            Atomo("branco", *lugar.pop())
    elif nome == "Coroas":
        lugar = lugares(58)     # uma molécula precisa de mais lugar
        for k in range(70):
            molecula("vermelho", 2, *lugar.pop())
        for k in range(10):
            Atomo("verde", *lugar.pop())
            Atomo("violeta", *lugar.pop())
    elif nome == "Ilhas":
        lugar = lugares(58)
        for k in range(50):
            molecula("vermelho", 2, *lugar.pop())
        for k in range(40):
            molecula("ambar", 2, *lugar.pop())


def elementos_novos():
    """As mesmas cores, regras novas: valência e avidez ao acaso."""
    esvazia()
    st.receita = "Acaso"
    for nome in ("branco", "vermelho", "ambar"):
        ELEMENTOS[nome]["valencia"] = int(uniform(1, 4))
        ELEMENTOS[nome]["avidez"] = round(uniform(0, 1), 2)
    mostra_elementos()
    lugar = lugares(34)
    for nome, quantos in (("vermelho", 50), ("branco", 100), ("ambar", 40)):
        for k in range(quantos):
            Atomo(nome, *lugar.pop())


# o líquido muda de cor com o calor: azul gelado, roxo morno, vermelho fervendo
TONS = Colormap.from_colors("#0a2a4a", "#24154a", "#4a1420")
liquido = Circle(center=(CX, CY), radius=PRATO, color="#36506e", line_width=2)
liquido["fill"] @= lambda: TONS.get_color(round(st.calor * 20) / 20).with_alpha(0.35)

# a tabela dos elementos, à direita; muda quando R sorteia regras novas
legenda = {}
for k, nome in enumerate(ELEMENTOS):
    y = ALTURA - 120 - 34 * k
    Circle(center=(LARGURA - 250, y), radius=ELEMENTOS[nome]["raio"] * BOLA,
           color=ELEMENTOS[nome]["cor"])
    legenda[nome] = Text("", top_left=(LARGURA - 232, y + 8), color="#c8d6e5", font_size=14)


def mostra_elementos():
    for nome, texto in legenda.items():
        e = ELEMENTOS[nome]
        if e["carga"]:
            texto.text = f"{nome.replace('ambar', 'âmbar')}  íon {'+' if e['carga'] > 0 else '-'}"
        else:
            texto.text = (f"{nome.replace('ambar', 'âmbar')}  valência {e['valencia']}"
                          f"  avidez {e['avidez']:.2f}")

Text(lambda: f"{st.receita}    calor {round(st.calor * 100)}%",
     top_left=(20, ALTURA - 20), color="white", font_size=18)
Text("CIMA/BAIXO calor   ARRASTAR mexe   ESPAÇO faísca   1 2 3 R receitas   T rastro",
     top_left=(20, 36), color="#8aa0b8", font_size=14)

receita("Nascente")


def update(dt):
    agitar(dt)
    if keyp("UP"):
        st.calor = min(1, st.calor + 0.3 * dt)
    if keyp("DOWN"):
        st.calor = max(0, st.calor - 0.3 * dt)
    if keyp.once("SPACE"):
        faisca(mouse.x, mouse.y)
    if keyp.once("1"):
        receita("Nascente")
    if keyp.once("2"):
        receita("Coroas")
    if keyp.once("3"):
        receita("Ilhas")
    if keyp.once("R"):
        elementos_novos()
    if keyp.once("T"):
        rastro.enabled = not rastro.enabled


run()
