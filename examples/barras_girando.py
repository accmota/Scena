"""Barras girando — retângulos recursivos. Tutorial 04.

Uma função cria uma barra e chama a si mesma para criar duas menores,
uma em cada ponta (left_square_center / right_square_center): o centro
da filha é uma fórmula sobre a mãe. Cada nível gira 1,5 vez mais rápido,
no sentido contrário. Cinco níveis abaixo da primeira: 63 barras.

Controles
---------
  painel    Velocidade, Giro
  M         liga / desliga o rastro

Uso
---
    python examples/barras_girando.py
"""

from scena import *

W, H = 1000, 700
init(width=W, height=H, title="Barras girando")

Wallpaper(Gradient("ocean", type="radial", size=1000))
Grain()
mt = MotionTrail()

RECURSOES = 5
PROPORCAO = 1 / 15  # altura / comprimento
FATOR_TAMANHO = 2
COMPRIMENTO = W * 0.5

st.velocidade = 26
st.fator_giro = -1.5

PALETA = Palette("lisboa")

Slider(st.velocidade, label="Velocidade", min_value=0, max_value=80)
Slider(st.fator_giro, label="Giro", min_value=-3, max_value=3)


@when(lambda: keyp("M"))
def muda_rastro():
    mt.enabled = not mt.enabled


def criar_barra(nivel, centro):
    comprimento = COMPRIMENTO / (FATOR_TAMANHO ** nivel)
    altura = comprimento * PROPORCAO

    barra = Rect(
        center=centro,
        width=comprimento,
        height=altura,
        color=PALETA[nivel],
    )

    barra.visual = Aurora()
    barra["angle"] @= lambda: (clock.time * st.velocidade * (st.fator_giro ** nivel)) % 360

    if nivel < RECURSOES:
        criar_barra(nivel + 1, lambda: barra.left_square_center)
        criar_barra(nivel + 1, lambda: barra.right_square_center)


criar_barra(0, (W / 2, H / 2))
run()
