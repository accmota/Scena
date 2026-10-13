"""Entropia.

Bolas azuis começam à esquerda e vermelhas à direita, separadas por uma
parede. Tire a parede e elas se misturam sozinhas — e não se separam de
novo. A cada 5 segundos um retângulo invisível de cada lado conta quantas
bolas de cada cor estão ali (collides_with), e o painel mostra a pressão,
a temperatura e o quanto as cores estão misturadas.

Coisas para experimentar
------------------------
  Parede no meio          tire, espere misturar, ponha de volta
  Gravidade               as bolas se juntam embaixo, como o ar
  Paredes de fora móveis  nada segura as paredes: a pressão as empurra e a
                          caixa explode (Recomeçar põe tudo de volta)
  Parede do meio móvel    um pistão: anda até as pressões ficarem iguais
  Temperatura             um lado quente e outro frio, com o pistão solto

Controles
---------
  RODA DO MOUSE        aproximar / afastar

Uso
---
    python examples/entropia.py
"""

from math import log2
from random import uniform
from scena import *

init(width=1280, height=800, title="Entropia")
SkyGradient("night")

# A caixa: o lado de dentro vai de ESQ a DIR e de BAIXO a CIMA.
ESQ, DIR, BAIXO, CIMA = 380, 1180, 100, 640
MEIO = (ESQ + DIR) / 2
ALTURA_MEIO = (BAIXO + CIMA) / 2
GROSSURA = 40
GRAVIDADE = 120
PESO_PAREDE = 50       # uma parede móvel pesa como 50 bolas
RAPIDEZ = 90           # rapidez de uma bola na temperatura 1

st.bolas = 80
st.temp_azuis = 5
st.temp_vermelhas = 5
st.parede_no_meio = True
st.gravidade = False
st.paredes_moveis = False
st.meio_movel = False


class Parede(Rect, group="parede"):
    def setup(self):
        self.visual = Metal()
        self.mass = STATIC
        self.casa = (self.center.x, self.center.y)
        self.forca = 0       # soma das batidas desde a última contagem

    def on_update(self, dt):
        # parede solta: só anda com o que as batidas lhe deram
        if self.mass != STATIC:
            self.move_by(self.vel.x * dt, self.vel.y * dt)

    def volta_para_casa(self):
        self.move_to(*self.casa)
        if self.vel is not None:
            self.vel = Vec2(0, 0)


class Bola(Circle, radius=7):
    def on_update(self, dt):
        if st.gravidade:
            self.vel.y -= GRAVIDADE * dt
        self.move_by(self.vel.x * dt, self.vel.y * dt)

    @collide_with("parede")
    def bateu(self, parede, info):
        # bola rápida bate mais forte: é isso que a pressão mede
        parede.forca += self.vel.length


@leave_playfield("bola")
def escapou(bola):
    bola.destroy()


# A parede do meio nasce antes das outras para ficar por baixo delas:
# as pontas entram nas paredes de cima e de baixo, sem fresta.
meio = Rect(center=(MEIO, ALTURA_MEIO), width=16, height=CIMA - BAIXO + 2 * GROSSURA,
            group="divisoria")
meio.visual = Metal("light steel blue")
meio.mass = STATIC

largura = DIR - ESQ + 2 * GROSSURA
altura = CIMA - BAIXO + 2 * GROSSURA
Parede(center=(MEIO, CIMA + GROSSURA / 2), width=largura, height=GROSSURA)
Parede(center=(MEIO, BAIXO - GROSSURA / 2), width=largura, height=GROSSURA)
parede_esq = Parede(center=(ESQ - GROSSURA / 2, (BAIXO + CIMA) / 2), width=GROSSURA,
                    height=altura, group=("parede", "lateral"))
parede_dir = Parede(center=(DIR + GROSSURA / 2, (BAIXO + CIMA) / 2), width=GROSSURA,
                    height=altura, group=("parede", "lateral"))

resolve("bola", "parede", bounce=1)
resolve("bola", "bola", bounce=1)
resolve("bola", "divisoria", bounce=1)
resolve("divisoria", "lateral", bounce=1)


def divisa():
    """Onde termina o lado esquerdo: na parede do meio, se ela estiver lá."""
    if meio.active:
        return meio.center.x
    return MEIO


# Os dois lados: retângulos invisíveis que só servem para contar.
lado_esq = Rect(p1=(0, 0), p2=lambda: (divisa(), 800))
lado_dir = Rect(p1=lambda: (divisa(), 0), p2=(1280, 800))
lado_esq.visible = False
lado_dir.visible = False


# ----- contagem -----

def mistura(azuis, vermelhas):
    """0 quando o lado tem uma cor só, 1 quando tem metade de cada."""
    total = azuis + vermelhas
    if azuis == 0 or vermelhas == 0:
        return 0
    p = azuis / total
    return -(p * log2(p) + (1 - p) * log2(1 - p))


def temperatura(bolas):
    """A energia média de movimento: na mesma escala do slider."""
    if not bolas:
        return 0
    soma = 0
    for bola in bolas:
        soma += bola.vel.length ** 2
    return soma / len(bolas) / RAPIDEZ ** 2


def descreve(lado, parede):
    azuis = len(lado.collides_with(group="azul"))
    vermelhas = len(lado.collides_with(group="vermelha"))
    pressao = parede.forca / 5 / 100
    parede.forca = 0
    quente = temperatura(lado.collides_with(group="bola"))
    texto = (f"azuis {azuis}   vermelhas {vermelhas}\n"
             f"pressão {pressao:.1f}   temperatura {quente:.1f}")
    return texto, azuis, vermelhas


def energia():
    soma = 0
    for bola in group["bola"]:
        soma += bola.vel.length ** 2 / 2
        if st.gravidade:
            soma += GRAVIDADE * (bola.center.y - BAIXO)
    return soma


def contar():
    texto, az_esq, verm_esq = descreve(lado_esq, parede_esq)
    texto_esq.text = "ESQUERDA\n" + texto
    texto, az_dir, verm_dir = descreve(lado_dir, parede_dir)
    texto_dir.text = "DIREITA\n" + texto

    # entropia de mistura: média dos dois lados, pesada pelo número de bolas
    total = az_esq + verm_esq + az_dir + verm_dir
    if total:
        s = (mistura(az_esq, verm_esq) * (az_esq + verm_esq)
             + mistura(az_dir, verm_dir) * (az_dir + verm_dir)) / total
    else:
        s = 0
    painel.text = (f"Mistura (entropia)  {s * 100:.0f}%\n"
                   f"Energia das bolas  {energia() / 1000:.0f}\n"
                   f"(conta a cada 5 segundos)")


# ----- começar -----

def soltar(quantas, x0, x1, cor, tag, quente):
    # Todas começam com a mesma rapidez; as batidas espalham as rapidezes.
    # Temperatura é energia de movimento, que cresce com a rapidez ao quadrado.
    rapidez = RAPIDEZ * quente ** 0.5
    for i in range(quantas):
        bola = Bola(center=(uniform(x0, x1), uniform(BAIXO + 20, CIMA - 20)),
                    color=cor, group=("bola", tag))
        bola.vel = vec_from_angle(uniform(0, 360), length=rapidez)


def recomecar():
    group["bola"].destroy()
    for parede in group["parede"]:
        parede.volta_para_casa()
    st.parede_no_meio = True
    meio.move_to(MEIO, ALTURA_MEIO)
    if meio.vel is not None:
        meio.vel = Vec2(0, 0)
    metade = st.bolas // 2
    soltar(metade, ESQ + 20, MEIO - 20, "dodger blue", "azul", st.temp_azuis)
    soltar(st.bolas - metade, MEIO + 20, DIR - 20, "tomato", "vermelha", st.temp_vermelhas)
    after(0.1, contar)


# ----- painel -----

Slider(st["bolas"], label="Bolas", min_value=10, max_value=160, only_int=True)
Slider(st["temp_azuis"], label="Temperatura azuis", min_value=1, max_value=10, only_int=True)
Slider(st["temp_vermelhas"], label="Temperatura vermelhas", min_value=1, max_value=10,
       only_int=True)
Button(label="Recomeçar", on_click=recomecar)
ui.gap()
CheckBox(st["parede_no_meio"], label="Parede no meio")
CheckBox(st["gravidade"], label="Gravidade")
CheckBox(st["paredes_moveis"], label="Paredes de fora móveis")
CheckBox(st["meio_movel"], label="Parede do meio móvel")
ui.gap()
painel = Text("contando…\n\n", font_size=16)

texto_esq = Text("", top_center=((ESQ + MEIO) / 2, 785), font_size=16, stack=False)
texto_dir = Text("", top_center=((MEIO + DIR) / 2, 785), font_size=16, stack=False)


@on_change(st["parede_no_meio"])
def liga_parede(ligada):
    meio.active = ligada
    if ligada:
        # volta para o meio; as bolas que estiverem lá são empurradas para um lado
        meio.move_to(MEIO, ALTURA_MEIO)
        if meio.vel is not None:
            meio.vel = Vec2(0, 0)


@on_change(st["paredes_moveis"])
def solta_paredes(moveis):
    for parede in group["parede"]:
        if moveis:
            parede.mass = PESO_PAREDE
            parede.vel = Vec2(0, 0)
        else:
            parede.mass = STATIC
            parede.volta_para_casa()


@on_change(st["meio_movel"])
def solta_meio(movel):
    if movel:
        meio.mass = PESO_PAREDE
        meio.vel = Vec2(0, 0)
    else:
        meio.mass = STATIC


def update(dt):
    # o pistão só anda para os lados; as batidas não o tiram da altura
    if meio.mass != STATIC:
        meio.vel.y = 0
        meio.move_by(meio.vel.x * dt, ALTURA_MEIO - meio.center.y)


every(5, contar)
recomecar()


def on_mouse_scroll(xoffset, yoffset):
    if yoffset > 0:
        canvas.zoom_by(1.1, about=mouse)
    else:
        canvas.zoom_by(1 / 1.1, about=mouse)


run()
