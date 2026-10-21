"""Constelação.

Pontos de luz vagueiam pela tela, e cada um estica um fio até o vizinho
mais perto (nearest). Como todos andam, os vizinhos trocam a todo instante:
as constelações se desfazem e se refazem sozinhas. Quanto mais perto o
vizinho, mais forte o fio.

Os cometas caçam. Cada um persegue o ponto livre mais perto dele (um ponto
que outro cometa já persegue não serve), preso a ele por uma linha que vira
raio quando a presa está perto; os pontos fogem dos cometas. Um ponto pego
estoura e renasce em outro lugar, e o cometa fica com a cor dele.

A cor de cada ponto vem da sua posição numa Colormap, refeita a cada
quarto de segundo (every); os fios somam luz (blend = "add"); os cometas
são Neon com um Contrail atrás; Bloom (que também faz os pontos
brilharem), Vignette e Nebuladust fazem o céu.

Controles
---------
  SEGURAR O MOUSE   os pontos caem para o mouse
  SOLTAR            uma onda os empurra para longe
  ESPAÇO            mais um cometa (até 6), onde está o mouse
  T                 liga e desliga o rastro de tudo

Uso
---
    python examples/constelacao.py
"""
from random import choice, uniform
from scena import *

LARGURA, ALTURA = 1280, 800
init(width=LARGURA, height=ALTURA, title="Constelação")
Wallpaper(Gradient("#04050d", "#140b2b", angle=90))
Nebuladust(alpha=0.35)
Bloom(intensity=0.7)
Vignette()
rastro = MotionTrail(fade=0.88)
rastro.enabled = False

TELA = canvas.game_view
# a cor de um ponto vem de onde ele está: da esquerda (ciano) à direita (laranja)
CORES = Colormap.from_colors("cyan", "medium purple", "hot pink", "orange")
CORES_COMETA = ["white", "gold", "aquamarine", "deep pink", "lime", "orange"]

PONTOS = 55
CALMA = 40          # rapidez de um ponto que vagueia
MEDO = 170          # um cometa mais perto que isso assusta o ponto
FUGA = 700          # o quanto o susto acelera
PUXAO = 300         # o quanto o mouse apertado atrai
FIO_MAXIMO = 200    # um fio mais comprido que isso some
CACADA = 340        # rapidez de um cometa
RAIO = 140          # presa mais perto que isso: a linha vira raio
ONDA = 320          # alcance da onda ao soltar o mouse
EMPURRAO = 500      # força da onda bem no centro dela


class Ponto(Circle, radius=4, group="ponto"):
    def setup(self):
        self.vel = vec_from_angle(uniform(0, 360), CALMA)
        self.cacador = None     # o cometa que está atrás deste ponto
        # um ponto anda devagar: trocar a cor 4 vezes por segundo basta
        self.recolorir()
        self.every(0.25, self.recolorir)
        # cada ponto respira no seu próprio ritmo
        tween(self["radius"], uniform(5, 7), time=uniform(0.8, 2),
              ease="ease_in_out", loops="forever", yoyo=True)
        self.fio = Line(p1=lambda: self.center, p2=self.center)
        self.fio.blend = "add"

    def on_update(self, dt):
        perigo = group["cometa"].nearest(self, within=MEDO)
        if perigo:
            self.vel += vec_from_angle(heading(perigo, self), FUGA * dt)
        if mouse.press():
            self.vel += vec_from_angle(heading(self, mouse), PUXAO * dt)
        # passado o susto, volta devagar ao passo calmo
        self.vel = chase(self.vel, vec_from_angle(self.vel.angle, CALMA), rate=1.5)
        self.move_by(self.vel.x * dt, self.vel.y * dt)
        # quem foge por uma borda volta pela outra: ninguém fica preso num canto
        self.confine(TELA, by="overlap", action="wrap")

        vizinho = group["ponto"].nearest(self, where=lambda outro: outro is not self)
        perto = 1 - distance(self, vizinho) / FIO_MAXIMO
        self.fio.visible = perto > 0
        if perto > 0:
            self.fio.p2 = vizinho.center
            meio = (self.center.x + vizinho.center.x) / 2
            self.fio.color = CORES.get_color(meio / LARGURA).with_alpha(perto)
            self.fio.line_width = 1 + 2 * perto

    def recolorir(self):
        self.color = CORES.get_color(self.center.x / LARGURA)

    def renascer(self):
        self.move_to(uniform(40, LARGURA - 40), uniform(40, ALTURA - 40))
        self.vel = vec_from_angle(uniform(0, 360), CALMA)
        self.recolorir()
        self.dissolve_in(0.8)
        self.fio.dissolve_in(0.8)


class Cometa(Circle, radius=14, group="cometa"):
    def setup(self):
        self.vel = vec_from_angle(uniform(0, 360), CACADA)
        self.visual = Neon()
        self.presa = None
        self.laco = Line(p1=lambda: self.center, p2=self.center)
        self.laco.dash = "dash"
        self.cauda = Contrail(max_points=40, fade=True, line_width=5)
        self.every(0.02, lambda: self.cauda.snapshot(self))
        self.pintar(self.color)

    def pintar(self, cor):
        self.set_color(cor)
        self.laco.color = cor
        self.cauda.color = cor

    def on_update(self, dt):
        # a cada frame, solta a presa (se ainda é dele) e escolhe o ponto livre mais perto
        if self.presa and self.presa.cacador is self:
            self.presa.cacador = None
        self.presa = group["ponto"].nearest(self, where=lambda p: p.cacador is None)
        self.presa.cacador = self
        # vira aos poucos para a presa: o cometa faz curvas, não linhas retas
        rumo = vec_from_angle(heading(self, self.presa), CACADA)
        self.vel = chase(self.vel, rumo, rate=2.5)
        self.move_by(self.vel.x * dt, self.vel.y * dt)
        self.confine(TELA, action="bounce")

        self.laco.p2 = self.presa.center
        if distance(self, self.presa) < RAIO:
            if not self.laco.visual:
                self.laco.visual = ElectricBolt()
        else:
            self.laco.visual = None

    @collide_with("ponto")
    def pegou(self, ponto, info):
        canvas.zap_at(ponto, style="spark")
        self.pintar(ponto.color)
        self.pop(scale=1.6)
        ponto.renascer()


for i in range(PONTOS):
    Ponto(center=(uniform(40, LARGURA - 40), uniform(40, ALTURA - 40)))

for cor in CORES_COMETA[:3]:
    Cometa(center=(uniform(100, LARGURA - 100), uniform(100, ALTURA - 100)), color=cor)


def on_mouse_up(x, y, button):
    canvas.ripple_at(x, y, radius=ONDA, amount=0.6, shake=False)
    for ponto in group["ponto"]:
        forca = 1 - distance(ponto, (x, y)) / ONDA
        if forca > 0:
            ponto.vel += vec_from_angle(heading((x, y), ponto), EMPURRAO * forca)


def update(dt):
    if keyp.once("SPACE") and len(group["cometa"]) < 6:
        Cometa(center=(mouse.x, mouse.y), color=choice(CORES_COMETA))
    if keyp.once("T"):
        rastro.enabled = not rastro.enabled


run()
