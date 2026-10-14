"""Fórmulas — tutorial 09.

Uma pequena máquina de formas ligadas por fórmulas, como as células de
uma planilha. Um slider escreve no raio do sol; a lua, o fio, os textos
e o ponteiro que gira leem o sol, e tudo acompanha. A cor do sol muda
num @on_change; passar de raio 100 dispara um estouro (@when). A lua
pode ser solta (unlink) e arrastada, e presa de novo (@=). Cinco contas
no fio, feitas num for, guardam cada uma o seu i (lambda i=i:).

Controles
---------
  Slider "Raio": muda o raio do sol (passe de 100 para o estouro).
  Botão "Soltar a lua": solta a lua; arraste-a com o mouse.
  Botão "Prender a lua": liga a lua de novo ao sol.

Uso
---
    python examples/formulas.py
"""

from scena import *

init(width=1000, height=700, title="Fórmulas")
Wallpaper("dark navy")

st.raio = 40
Slider(st["raio"], label="Raio", min_value=20, max_value=120, only_int=True)

sol = Circle(center=(400, 330), radius=lambda: st.raio, color="gold")

def lugar_da_lua():
    return (sol.center.x + sol.radius * 3, sol.center.y)

lua = Circle(
    center=lugar_da_lua,
    radius=lambda: sol.radius / 3,
    color="light steel blue",
)
fio = Line(p1=lambda: sol.center, p2=lambda: lua.center, color="white")

for i in range(1, 6):
    Circle(center=lambda i=i: lerp(sol.center, lua.center, i / 6), radius=4, color="white")

Text(st["raio"])
Text(lambda: f"Sol {st.raio}   Lua {round(lua.radius)}")

ponteiro = Line(p1=lambda: lua.center, length=lambda: lua.radius * 2, angle=0, color="coral")
ponteiro["angle"] @= lambda: clock.time * 90
faisca = Circle(center=lambda: ponteiro.p2, radius=5, color="coral")
faisca.glow = True

@on_change(st["raio"])
def colorir(valor):
    sol.color = Color.from_hsv(valor / 200, 0.8, 1)

@when(lambda: sol.radius > 100)
def grande():
    canvas.burst_at(sol, radius=150, rings=True)

def soltar():
    lua["center"].unlink()
    lua.draggable = True

def prender():
    if lua.draggable:
        lua.draggable = False
        lua["center"] @= lugar_da_lua

Button(label="Soltar a lua", on_click=soltar)
Button(label="Prender a lua", on_click=prender)

run()
