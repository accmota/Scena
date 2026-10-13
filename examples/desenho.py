"""Desenho — tutorial 04.

Um programa de desenho com o mouse. Segure o botão e arraste: o caminho
vira um traço de luz (Contrail), com uma cor sorteada por traço. Cada
traço se apaga sozinho cinco segundos depois.

Controles
---------
  mouse     segure o botão e arraste para desenhar

Uso
---
    python examples/desenho.py
"""

from scena import *

init(width=1000, height=700, title="Desenho")

marcador = Circle(center=lambda: mouse, radius=10)
marcador.visual = Neon("cyan")
marcador.visible = False


def on_mouse_down():
    marcador.visible = True

    rastro = Contrail(
        duration=5,
        fade=True,
        line_width=4,
        visual=Rim(Color.random()),
    )
    marcador.caneta = every(0.03, lambda: rastro.snapshot(mouse))


def on_mouse_up():
    marcador.caneta.cancel()
    marcador.visible = False


run()
