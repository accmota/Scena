"""Revoada.

Um bando de pássaros sem chefe. Cada pássaro enxerga só os vizinhos perto
dele e segue três regras (as de Craig Reynolds, 1986):

  separar   não chegar perto demais de ninguém
  alinhar   voar para o mesmo lado que os vizinhos
  juntar    ir para o meio dos vizinhos

Ninguém manda no bando, e mesmo assim ele aparece: grupos que se formam,
se partem e se juntam de novo.

A aparência mostra o estado de cada pássaro:
  - o rumo vira cor: quem voa junto fica da mesma cor, e dois bandos que
    se encontram vão trocando de cor até combinar;
  - o medo clareia: perto do falcão (o mouse) o pássaro foge, fica branco,
    brilha e se estica, e o susto passa para os vizinhos — uma onda de
    medo atravessa o bando e vai sumindo;
  - o céu acende quando o bando entra em ordem (todos para o mesmo lado);
    a barra embaixo mostra essa ordem.

Coisas para experimentar
------------------------
  Desligue alinhar   cada um voa para um lado: o céu apaga
  Desligue juntar    os bandos se desfazem em pássaros soltos
  Desligue separar   o bando se amontoa
  Clique no bando    ele explode e se refaz, muitas vezes de outra cor

Controles
---------
  MOUSE        o falcão
  CLIQUE       um estouro: assusta quem está perto
  S / A / J    liga e desliga separar, alinhar, juntar

Uso
---
    python examples/revoada.py
"""

from random import uniform
from scena import *

init(width=1280, height=800, title="Revoada")
SkyGradient("dusk")
luz = Bloom(intensity=0.4)

PASSAROS = 120
VISAO = 90          # até onde um pássaro enxerga os vizinhos
PERTO = 24          # mais perto que isso, ele se afasta
RAPIDEZ = 150       # rapidez de quem voa calmo
MARGEM = 120        # perto da borda, o pássaro faz a curva de volta
SUSTO = 150         # a esta distância do falcão, o pássaro se assusta
FAIXAS = 12         # quantas cores de rumo
VENTO = 120         # um empurrão ao acaso, para ninguém voar reto demais

st.separar = True
st.alinhar = True
st.juntar = True
st.ordem = 0        # 0: cada um para um lado · 1: todos para o mesmo


class Passaro(Triangle, radius=9, base_ratio=0.5, group="passaro"):
    def setup(self):
        self.vel = vec_from_angle(uniform(-180, 180), RAPIDEZ)
        self.medo = 0
        self.tom = None
        self.line = None        # só o miolo, sem contorno

    def on_update(self, dt):
        # face=True: a ponta vira para onde ele anda
        self.move_by(self.vel.x * dt, self.vel.y * dt, face=True)
        self.pinta()

    def pinta(self):
        """A cor vem do rumo; o medo clareia (o Bloom faz brilhar) e estica."""
        faixa = round(self.angle / 360 * FAIXAS) % FAIXAS
        susto = round(self.medo * 3)        # 0 calmo … 3 em pânico
        if (faixa, susto) == self.tom:
            return      # só repinta quando muda de faixa
        self.tom = (faixa, susto)
        calmo = Color.from_hsv(faixa / FAIXAS, 0.6, 1)
        self.fill = Color.interpolate(calmo, Color("white"), susto / 4)
        self.base_ratio = 0.6 - 0.1 * susto     # quem foge fica mais fino


class Falcao(Triangle, radius=20, base_ratio=0.45, color="dark red"):
    def setup(self):
        self.glow = "red"
        self.tail = Tail(color="dark yellow")

    def on_update(self, dt):
        # segue o mouse com um pouco de atraso, de ponta para a frente
        if distance(self, mouse) > 4:
            self.angle = heading(self, mouse)
        self.move_to(chase(self.center, mouse, rate=4))


falcao = Falcao(center=(640, 400))

for i in range(PASSAROS):
    Passaro(center=(uniform(MARGEM, 1280 - MARGEM), uniform(MARGEM, 800 - MARGEM)))

Text(lambda: (f"[S] separar {'sim' if st.separar else 'não'}    "
              f"[A] alinhar {'sim' if st.alinhar else 'não'}    "
              f"[J] juntar {'sim' if st.juntar else 'não'}    ordem"),
     top_left=(20, 70), color="white", font_size=16)
# a barra da ordem: cheia quando todos voam para o mesmo lado
Rect(p1=(520, 22), p2=lambda: (520 + 300 * st.ordem, 30), color="white")


def quadra(x, y):
    """A quadra do céu onde fica o ponto: quadrados do tamanho da VISAO."""
    return (int(x // VISAO), int(y // VISAO))


def voar(dt):
    """As três regras, o falcão e as bordas: muda o vel de cada pássaro."""
    bando = list(group["passaro"])
    # Uma foto de todos antes de alguém mudar: cada um decide olhando o
    # mesmo instante. Números soltos são rápidos de comparar.
    foto = []
    # O céu em quadras: quem está a mais de uma quadra de distância está
    # longe demais para ser visto, então cada pássaro só olha a sua quadra
    # e as oito em volta (e não o bando inteiro).
    quadras = {}
    for p in bando:
        x, y = p.center.x, p.center.y
        retrato = (x, y, p.vel.x, p.vel.y, p.medo)
        foto.append(retrato)
        if quadra(x, y) not in quadras:
            quadras[quadra(x, y)] = []
        quadras[quadra(x, y)].append(retrato)

    fx, fy = falcao.center.x, falcao.center.y
    # a força de cada regra (0: desligada)
    juntar = 0.7 if st.juntar else 0
    alinhar = 2.5 if st.alinhar else 0
    separar = 3000 if st.separar else 0
    soma_x = soma_y = soma_rapidez = 0

    for i in range(len(bando)):
        x, y, vx, vy, medo_antes = foto[i]
        vizinhos = 0
        meio_x = meio_y = 0         # para onde fica o meio dos vizinhos
        rumo_x = rumo_y = 0         # o vel somado dos vizinhos
        longe_x = longe_y = 0       # para longe de quem está perto demais
        medo_vizinho = 0
        qx, qy = quadra(x, y)
        em_volta = []
        for cx in (qx - 1, qx, qx + 1):
            for cy in (qy - 1, qy, qy + 1):
                em_volta += quadras.get((cx, cy), [])
        for ox, oy, ovx, ovy, omedo in em_volta:
            dx = ox - x
            dy = oy - y
            d2 = dx * dx + dy * dy
            if d2 == 0 or d2 > VISAO * VISAO:
                continue
            vizinhos += 1
            meio_x += dx
            meio_y += dy
            rumo_x += ovx
            rumo_y += ovy
            if d2 < PERTO * PERTO:
                longe_x -= dx / d2
                longe_y -= dy / d2
            if omedo > medo_vizinho:
                medo_vizinho = omedo

        # a aceleração deste pássaro; começa com um pouco de vento
        ax = uniform(-VENTO, VENTO) + longe_x * separar
        ay = uniform(-VENTO, VENTO) + longe_y * separar
        if vizinhos:
            ax += meio_x / vizinhos * juntar + (rumo_x / vizinhos - vx) * alinhar
            ay += meio_y / vizinhos * juntar + (rumo_y / vizinhos - vy) * alinhar

        # o falcão: quem o vê foge dele e leva um susto inteiro
        medo = medo_antes
        dx = x - fx
        dy = y - fy
        d2 = dx * dx + dy * dy
        if d2 < SUSTO * SUSTO:
            medo = 1
            ax += dx / (d2 ** 0.5 + 1) * 900
            ay += dy / (d2 ** 0.5 + 1) * 900

        # o susto passa com o tempo, mas pega dos vizinhos (um pouco menor)
        medo = max(0, medo - 0.6 * dt)
        if medo_vizinho * 0.85 > medo:
            medo += (medo_vizinho * 0.85 - medo) * 6 * dt
        if medo < 0.05:
            medo = 0    # sem isso, dois vizinhos se assustam um ao outro para sempre

        # perto da borda, vira de volta (mais forte quanto mais perto)
        if x < MARGEM:
            ax += (MARGEM - x) * 6
        if x > 1280 - MARGEM:
            ax -= (x - 1280 + MARGEM) * 6
        if y < MARGEM:
            ay += (MARGEM - y) * 6
        if y > 800 - MARGEM:
            ay -= (y - 800 + MARGEM) * 6

        # a rapidez fica entre um mínimo e um máximo (o medo acelera)
        vx += ax * dt
        vy += ay * dt
        rapidez = (vx * vx + vy * vy) ** 0.5
        nova = min(max(rapidez, RAPIDEZ * 0.6), RAPIDEZ * (1.3 + 1.2 * medo))
        vx = vx * nova / rapidez
        vy = vy * nova / rapidez

        p = bando[i]
        p.vel.x = vx
        p.vel.y = vy
        if medo != medo_antes:      # quase todos estão calmos: medo fica 0
            p.medo = medo
        soma_x += vx
        soma_y += vy
        soma_rapidez += nova

    if soma_rapidez:
        st.ordem = (soma_x * soma_x + soma_y * soma_y) ** 0.5 / soma_rapidez


def update(dt):
    voar(dt)
    # o céu acende quando o bando entra em ordem
    luz.intensity = chase(luz.intensity, 0.2 + 1.2 * st.ordem ** 3, rate=2)
    if keyp.once("S"):
        st.separar = not st.separar
    if keyp.once("A"):
        st.alinhar = not st.alinhar
    if keyp.once("J"):
        st.juntar = not st.juntar


def on_mouse_click(x, y, button):
    canvas.ripple_at(x, y)
    for p in group["passaro"]:
        if distance(p, (x, y)) < 220:
            p.medo = 1
            p.vel += vec_from_angle(heading((x, y), p), 250)


run()
