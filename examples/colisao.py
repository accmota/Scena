"""Colisão — tutorial 20.

Um laboratório de colisão, sem jogo: uma poça com as três fases de um
toque (@collide, @collide_stay, @collide_exit), um clique que pergunta
quem está no ponto (collision.query_point), um estouro em área
(collision.query_circle com group=) e um vigia que vê o herói quando
nenhuma caixa tampa a linha (collision.raycast).

Controles
---------
  setas            movem o herói
  clique           pisca o que está embaixo
  botão direito    estoura as caixas em volta

Uso
---
    python examples/colisao.py
"""
from scena import *

init(width=1000, height=700, title="Colisão")
Wallpaper("#1b2330")

poca = Rect(center=(250, 200), width=260, height=180, color="#2a6f97", group="agua")

for x, y in [(520, 420), (600, 420), (680, 300), (420, 180), (760, 560)]:
    Rect(center=(x, y), width=70, height=70, color="peru", group="caixa")

heroi = Circle(center=(120, 560), radius=22, color="coral", group="heroi")
heroi.velocidade = 260
resolve("heroi", "caixa")

st.ar = 100
Text(lambda: f"Ar: {round(st.ar)}", top_left=(20, 680))


def update(dt):
    passo = heroi.velocidade * dt
    if keyp("LEFT"):
        heroi.move_by(-passo, 0)
    if keyp("RIGHT"):
        heroi.move_by(passo, 0)
    if keyp("UP"):
        heroi.move_by(0, passo)
    if keyp("DOWN"):
        heroi.move_by(0, -passo)
    if st.ar < 100:
        st.ar = min(100, st.ar + 10 * dt)
    olhar()


@collide("heroi", "agua")
def entrou(heroi, agua, info):
    heroi.velocidade = 110
    heroi.color = "light sky blue"


@collide_stay("heroi", "agua")
def mergulhado(heroi, agua, info):
    st.ar = max(0, st.ar - 30 * clock.dt)


@collide_exit("heroi", "agua")
def saiu(heroi, agua, info):
    heroi.velocidade = 260
    heroi.color = "coral"


def on_mouse_click(x, y, button):
    if button == Mouse.BTN_RIGHT:
        canvas.burst_at((x, y), radius=90)
        for caixa in collision.query_circle(x, y, radius=90, group="caixa"):
            caixa.destroy()
    else:
        for coisa in collision.query_point(x, y):
            coisa.flash(0.3)


vigia = Triangle(center=(900, 620), radius=24, color="gold")
visao = Line(p1=vigia.center, p2=heroi.center, color="gold")


def olhar():
    vigia.rotate_to(heading(vigia.center, heroi.center))
    batida = collision.raycast(vigia, p2=heroi, group=["heroi", "caixa"])
    if batida:
        coisa, t, ponto = batida
        visao.p2 = ponto
        if coisa is heroi:
            visao.color = "red"
        else:
            visao.color = "gray"


run()
