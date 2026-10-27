"""Ligue 4 — tutorial 21.

Um jogo de tabuleiro para dois jogadores, vermelho e azul. Cada um, na sua
vez, arrasta a bola do lado do tabuleiro e a solta numa coluna; a bola cai
até a casa livre mais baixa. Quatro bolas da mesma cor em linha, deitadas,
em pé ou na diagonal, ganham o jogo e acendem. As regras ficam numa lista
por coluna.

Controles
---------
  MOUSE (arrastar)     levar a bola até uma coluna e soltar
  Novo jogo            limpa o tabuleiro

Uso
---
    python examples/ligue4.py
"""

from scena import *

init(width=1000, height=760, title="Ligue 4")
Wallpaper("#2b3550")

pecas = Sheet("k-rolling-ball/rollingBall_sheet@2.png", atlas="k-rolling-ball/rollingBall_sheet@2.xml")

zona = Box(center=(500, 340), width=560, height=480)
Rect(box=zona.outset(14), color="#d8dce4", corner_radius=24)
grade = zona.grid(7, 6)
for casa in grade:
    Sprite(pecas, frame="hole_large.png", box=casa)

INICIO = (110, 520)
proxima = Sprite(pecas, frame="ball_red_large.png", height=64, center=INICIO, layer="top")
proxima.draggable = True

colunas = [[], [], [], [], [], [], []]
st.vez = "vermelho"
st.fim = False


def mensagem():
    if st.fim:
        return f"O {st.vez} venceu!"
    return f"Vez do {st.vez}"


aviso = Text(text="", center=(500, 712), font_size=36, color="white")
aviso["text"] @= mensagem


@drag_to(proxima)
def soltou(bola, alvo, pos):
    casa = grade.cell_at(pos)
    if st.fim or casa is None or len(colunas[casa.col_index]) == 6:
        bola.move_to(INICIO, time=0.3)
        return
    coluna = colunas[casa.col_index]
    destino = grade.cell(casa.col_index, 5 - len(coluna))
    nova = Sprite(pecas, frame=bola.frame, height=64, center=(destino.center.x, 630), group="jogadas")
    nova.dono = st.vez
    nova.move_to(destino.center, time=0.5, ease="bounce", on_done=pousou)
    coluna.append(nova)
    bola.visible = False
    bola.center = INICIO


def pousou():
    play_sound("audio/impact_plank_medium_002.ogg")
    conferir()
    if st.fim:
        play_sound("audio/victory.mp3")
    else:
        trocar_vez()
    proxima.visible = True


def trocar_vez():
    if st.vez == "vermelho":
        st.vez = "azul"
        proxima.frame = "ball_blue_large.png"
    else:
        st.vez = "vermelho"
        proxima.frame = "ball_red_large.png"


def quatro(x, y, dx, dy):
    bolas = []
    for passo in range(4):
        c = x + passo * dx
        l = y + passo * dy
        if c > 6 or l < 0 or l >= len(colunas[c]) or colunas[c][l].dono != st.vez:
            return False
        bolas.append(colunas[c][l])
    for bola in bolas:
        bola.glow = "gold"
    return True


def conferir():
    for x in range(7):
        for y in range(6):
            if quatro(x, y, 1, 0) or quatro(x, y, 0, 1):
                st.fim = True
            if quatro(x, y, 1, 1) or quatro(x, y, 1, -1):
                st.fim = True


def novo_jogo():
    group["jogadas"].destroy()
    for coluna in colunas:
        coluna.clear()
    st.vez = "vermelho"
    st.fim = False
    proxima.frame = "ball_red_large.png"
    proxima.visible = True


Button(label="Novo jogo", on_click=novo_jogo)

run()
