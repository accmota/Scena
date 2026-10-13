"""Letreiro — tutorial 04.

Escreva uma frase no campo (TextInput) e aperte Enter: ela vira o
letreiro, com fonte, degradê e brilho, que passeia pela tela num oito
(Track.eight + move_along).

Controles
---------
  teclado   escreva no campo; Enter troca o letreiro
  Esc       solta o campo; um clique nele devolve o teclado

Uso
---
    python examples/letreiro.py
"""

from scena import *

init(width=1000, height=700, title="Letreiro")
Wallpaper(Gradient("black", "navy", angle=90))

letreiro = Text("Olá!", center=(500, 350), font_size=80, font="fonts/kenvector_future.ttf")
letreiro.fill = Gradient("sunset", angle=90)
letreiro.glow = "orange"

trilha = Track.eight(width=600, height=250)
letreiro.move_along(trilha, time=8, loops="forever")


def mostrar(texto):
    letreiro.text = texto
    campo.text = ""
    campo.focus()


campo = TextInput(placeholder="Escreva e aperte Enter", width=400, on_submit=mostrar)
campo.focus()

run()
