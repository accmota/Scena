"""Céu estrelado — tutorial 11, Script 3.

O mouse no canvas, sem objeto nenhum: as funções com nome fixo do topo
do arquivo (on_mouse_click, on_mouse_double_click, on_mouse_drag,
on_mouse_scroll).

Controles
---------
  clique         acende uma estrela
  arrastar       espalha poeira de estrelas
  roda           muda o tamanho da próxima estrela
  clique duplo   apaga o céu

Uso
---
    python examples/ceu_estrelado.py
"""

from scena import *

init(width=1000, height=700, title="Céu estrelado")
Wallpaper("black")

st.raio = 6
pincel = Circle(center=lambda: mouse, radius=lambda: st.raio, color="white")
pincel.fill = None


def on_mouse_click(x, y, button):
    estrela = Circle(center=(x, y), radius=st.raio, color="white", group="estrelas")
    estrela.glow = True


def on_mouse_double_click(x, y, button):
    group["estrelas"].destroy()


def on_mouse_drag(x, y, button):
    Circle(center=(x, y), radius=2, color="light steel blue", group="estrelas")


def on_mouse_scroll(xoffset, yoffset):
    st.raio = max(2, st.raio + yoffset)


run()
