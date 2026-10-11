"""Cadeia de bolas — tutorial 04.

A ponta segue o mouse; cada bola segue a da frente. O painel recria
a cadeia: número de bolas, visual e linhas. Esc abre o menu de pausa.

Controles
---------
  mouse     a ponta persegue
  painel    Bolas, Linhas, Visual, Rodar
  ESC       menu: Continuar / Recomeçar

Uso
---
    python examples/cadeia_de_bolas.py
"""

from scena import *

init(width=1000, height=700, title="Mouse e teclado")
Wallpaper(Gradient("navy", "cyan"))
Plasma(speed=0.2)

st.n_bolas = 30
st.linhas = True
st.efeito = "Halo"


def visual_da_bola():
    if st.efeito == "Flame":
        return Flame()
    if st.efeito == "Sphere":
        return Sphere()
    if st.efeito == "Shield":
        return Shield()
    if st.efeito == "Metal":
        return Metal()
    if st.efeito == "Aurora":
        return Aurora()
    if st.efeito == "Gel":
        return Gel()
    return Halo(style="pulse")


# --- cadeia: a ponta segue o mouse; cada bola segue a anterior -------------
def criar():
    group["bolas"].destroy()
    group["linhas"].destroy()

    cor = Color("tomato")
    centro = canvas.game_view.center
    anterior = None
    for i in range(st.n_bolas):
        bola = Circle(center=centro, radius=16, color=cor, group="bolas")
        bola.visual = visual_da_bola()
        cor = cor.darker(0.02)

        if st.linhas and anterior is not None:
            linha = Line(p1=centro, p2=centro, color="tomato", group="linhas", layer=-1)
            linha["p1"] @= anterior.center
            linha["p2"] @= bola.center
            linha.color = Gradient("red", "orange")
            linha.set_alpha(0.3)
            linha.blend = "add"

        anterior = bola


Slider(st["n_bolas"], label="Bolas", min_value=5, max_value=60, only_int=True)
CheckBox(st["linhas"], label="Linhas")
DropDown(st["efeito"], options=["Halo", "Flame", "Sphere", "Shield", "Metal", "Aurora", "Gel"])
ui.gap()
Button(label="Rodar", on_click=criar)

criar()


def escolher(opcao):
    if opcao == "Recomeçar":
        criar()


def update(dt):
    if keyp.once("ESC"):
        Menu(
            options=["Continuar", "Recomeçar"],
            title="Pausa",
            pause=True,
            on_choose=escolher,
        )

    bolas = group["bolas"]

    # a primeira segue o mouse
    ponta = bolas[0]
    x = chase(ponta.center.x, mouse.x, rate=8)
    y = chase(ponta.center.y, mouse.y, rate=8)
    ponta.move_to(x, y)

    # as outras seguem a da frente
    for i in range(1, bolas.count):
        bola = bolas[i]
        da_frente = bolas[i - 1]
        x = chase(bola.center.x, da_frente.center.x, rate=8)
        y = chase(bola.center.y, da_frente.center.y, rate=8)
        bola.move_to(x, y)


run()
