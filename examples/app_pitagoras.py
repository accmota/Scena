"""Teorema de Pitágoras — rearranjo visual (v3).

Igual à v2, mas no final as duas figuras ficam lado a lado:
à esquerda a² e b²; à direita a pose inicial com c².

Controles
---------
  arraste   move um triângulo
  roda      gira o triângulo (segure e role)
  painel    Demonstrar / Reiniciar

Uso
---
    python examples/app_pitagoras.py
"""
from math import atan2, degrees, sqrt

from scena import *

W, H = 1100, 720
init(width=W, height=H, title="Pitágoras")
Wallpaper("dark navy")

a = 130
b = 200
lado = a + b
c = sqrt(a * a + b * b)
ox = (W - lado) / 2
oy = (H - lado) / 2 + 10
cx = ox + lado / 2
cy = oy + lado / 2

shift = lado / 2 + 50

cor_area = "#666e7a8c"
cor_efeito = "#dbe0eb"
cor_rotulo = "#bfcce0bf"
cor_texto = "#ebf0f5"

paleta = Palette("especiarias", steps=4)
ang_c = degrees(atan2(a, b))

st.ocupado = False
st.deslocou = False


def criar_figura(x, y, grupo, grupo_tri, com_c2=False):
    """Moldura + 4 triângulos na pose inicial. Se com_c2, inclui c² e rótulos c."""
    mx = x + lado / 2
    my = y + lado / 2

    moldura = Square(center=(mx, my), length=lado, color="#242d42", group=grupo)
    moldura.line = "#8c9eb7d9"
    moldura.line_width = 2.5
    moldura.layer = -2

    t1 = Polygon(points=[(x, y), (x + a, y), (x, y + b)], group=[grupo_tri, grupo])
    t1.set_color(paleta[0])
    t2 = Polygon(points=[(x + lado, y), (x + lado, y + a), (x + a, y)], group=[grupo_tri, grupo])
    t2.set_color(paleta[1])
    t3 = Polygon(points=[(x + lado, y + lado), (x + b, y + lado), (x + lado, y + a)], group=[grupo_tri, grupo])
    t3.set_color(paleta[2])
    t4 = Polygon(points=[(x, y + lado), (x, y + b), (x + b, y + lado)], group=[grupo_tri, grupo])
    t4.set_color(paleta[3])

    group[grupo_tri].set_alpha(0.9)
    group[grupo_tri].line = "#ffffff59"
    group[grupo_tri].line_width = 1.5

    if com_c2:
        Square(center=(mx, my), length=c, angle=ang_c, color=cor_area,
               group=[grupo, "areas"])
        Text(text="c²", center=(mx, my), font_size=max(18, int(c * 0.28)),
             color=cor_texto, group=grupo)
        Text(text="c", center=(x + a / 2 - 8, y + b / 2 - 8), font_size=18,
             color=cor_texto, group=grupo)
        Text(text="c", center=(x + a + b / 2 + 8, y + a / 2 - 8), font_size=18,
             color=cor_texto, group=grupo)
        Text(text="c", center=(x + a / 2 + b + 8, y + a + b / 2 + 8), font_size=18,
             color=cor_texto, group=grupo)
        Text(text="c", center=(x + b / 2 - 8, y + a / 2 + b + 8), font_size=18,
             color=cor_texto, group=grupo)

    return t1, t2, t3, t4


# --- cena inicial (esquerda / interativa) ------------------------------------

dica = Text(
    text="Arraste os triângulos · segure e role para girar",
    center=(cx, 28),
    font_size=15,
    color="#a6b2c7b2",
)

t1, t2, t3, t4 = criar_figura(ox, oy, "cena", "triangulos")
group["triangulos"].draggable = True
group["triangulos"].wheel_rotate = True

t1_x0 = t1.center.x
t1_y0 = t1.center.y
t1_x1 = ox + a / 3
t1_y1 = oy + a + b / 3

t2_x0 = t2.center.x
t2_y0 = t2.center.y
t2_x1 = t2_x0
t2_y1 = t2_y0

t3_x0 = t3.center.x
t3_y0 = t3.center.y
t3_x1 = (ox + a + ox + ox + a) / 3
t3_y1 = (oy + lado + oy + lado + oy + a) / 3

t4_x0 = t4.center.x
t4_y0 = t4.center.y
t4_x1 = (ox + a + ox + a + ox + lado) / 3
t4_y1 = (oy + a + oy + oy + a) / 3

# marcas a|b
Line(p1=(ox + a, oy - 7), p2=(ox + a, oy + 7), color="#e5ebf28c", group=["marcas", "cena"])
Line(p1=(ox + lado - 7, oy + a), p2=(ox + lado + 7, oy + a), color="#e5ebf28c", group=["marcas", "cena"])
Line(p1=(ox + b, oy + lado - 7), p2=(ox + b, oy + lado + 7), color="#e5ebf28c", group=["marcas", "cena"])
Line(p1=(ox - 7, oy + b), p2=(ox + 7, oy + b), color="#e5ebf28c", group=["marcas", "cena"])
group["marcas"].line_width = 2

# rótulos a e b
Text(text="a", center=(ox + a / 2, oy - 22), font_size=18, color=cor_rotulo, group="cena")
Text(text="b", center=(ox + b / 2, oy + lado + 22), font_size=18, color=cor_rotulo, group="cena")
Text(text="a", center=(ox + b + a / 2, oy + lado + 22), font_size=18, color=cor_rotulo, group="cena")
Text(text="a", center=(ox - 22, oy + b + a / 2), font_size=18, color=cor_rotulo, group="cena")
Text(text="b", center=(ox - 22, oy + b / 2), font_size=18, color=cor_rotulo, group="cena")
Text(text="b", center=(ox + lado + 22, oy + a + b / 2), font_size=18, color=cor_rotulo, group="cena")

rotulo_a = Text(text="a", center=(ox + lado + 22, oy + a / 2), font_size=18, color=cor_rotulo, group="cena")
rotulo_b = Text(text="b", center=(ox + a + b / 2, oy - 22), font_size=18, color=cor_rotulo, group="cena")
rotulo_a_x0 = rotulo_a.center.x
rotulo_a_y0 = rotulo_a.center.y
rotulo_b_x0 = rotulo_b.center.x
rotulo_b_y0 = rotulo_b.center.y
rotulo_a_x1 = ox + a - 22
rotulo_a_y1 = oy + a / 2
rotulo_b_x1 = ox + a + b / 2
rotulo_b_y1 = oy + a + 22


class Guia(Entity):
     @on_mode
     async def prova(self):
          st.ocupado = True
          dica.visible = False
          group["triangulos"].draggable = False
          group["triangulos"].wheel_rotate = False

          group["destaque"].destroy()
          group["areas"].destroy()
          group["equacao"].destroy()
          group["direita"].destroy()

          if st.deslocou:
               group["cena"].move_by(shift, 0)
               st.deslocou = False

          # (a) pose inicial
          t1.move_to(t1_x0, t1_y0)
          t2.move_to(t2_x0, t2_y0)
          t3.move_to(t3_x0, t3_y0)
          t4.move_to(t4_x0, t4_y0)
          group["triangulos"].rotate_to(0)
          rotulo_a.center = (rotulo_a_x0, rotulo_a_y0)
          rotulo_b.center = (rotulo_b_x0, rotulo_b_y0)
          await wait(0.45)

          # (b) rótulos c, depois c²
          Text(text="c", center=(ox + a / 2 - 8, oy + b / 2 - 8), font_size=20,
               color=cor_texto, group=["destaque", "cena"])
          Text(text="c", center=(ox + a + b / 2 + 8, oy + a / 2 - 8), font_size=20,
               color=cor_texto, group=["destaque", "cena"])
          Text(text="c", center=(ox + a / 2 + b + 8, oy + a + b / 2 + 8), font_size=20,
               color=cor_texto, group=["destaque", "cena"])
          Text(text="c", center=(ox + b / 2 - 8, oy + a / 2 + b + 8), font_size=20,
               color=cor_texto, group=["destaque", "cena"])
          group["destaque"].fade_in(0.7)
          await wait(2)

          Square(center=(cx, cy), length=c, angle=ang_c, color=cor_area,
                    group=["destaque", "areas", "cena"])
          Text(text="c²", center=(cx, cy), font_size=max(18, int(c * 0.28)),
               color=cor_texto, group=["destaque", "cena"])
          group["areas"].line = "#b8bfcc59"
          group["areas"].line_width = 1.5
          group["areas"].visual = Halo(cor_efeito, style="pulse")
          group["areas"].layer = -1
          await wait(6)

          group["destaque"].destroy()
          group["areas"].destroy()
          await wait(0.75)

          # (c) destaca os triângulos
          group["triangulos"].pulse_outline(color="#fffffff2", duration=0.7)
          await wait(0.85)

          # (d) rearranjo
          t1.move_to(t1_x1, t1_y1, time=4.0, ease="ease_in_out")
          t2.move_to(t2_x1, t2_y1, time=4.0, ease="ease_in_out")
          t3.move_to(t3_x1, t3_y1, time=4.0, ease="ease_in_out")
          t4.move_to(t4_x1, t4_y1, time=4.0, ease="ease_in_out")
          group["triangulos"].rotate_to(0, time=4.0, ease="ease_in_out")
          await wait(4.0)
          await wait(0.3)

          rotulo_a.tween(rotulo_a.center, (rotulo_a_x1, rotulo_a_y1), time=3.0, ease="ease_in_out")
          rotulo_b.tween(rotulo_b.center, (rotulo_b_x1, rotulo_b_y1), time=3.0, ease="ease_in_out")
          await wait(3.0)
          await wait(0.25)

          # (e) a² e b²
          Square(center=(ox + a / 2, oy + a / 2), length=a, color=cor_area,
                    group=["destaque", "areas", "cena"])
          Text(text="a²", center=(ox + a / 2, oy + a / 2), font_size=max(18, int(a * 0.28)),
               color=cor_texto, group=["destaque", "cena"])
          Square(center=(ox + a + b / 2, oy + a + b / 2), length=b, color=cor_area,
                    group=["destaque", "areas", "cena"])
          Text(text="b²", center=(ox + a + b / 2, oy + a + b / 2), font_size=max(18, int(b * 0.28)),
               color=cor_texto, group=["destaque", "cena"])
          group["areas"].line = "#b8bfcc59"
          group["areas"].line_width = 1.5
          group["areas"].visual = Halo(cor_efeito, style="pulse")
          group["areas"].layer = -1
          await wait(2.6)

          # desliza a prova; à direita entra a figura inicial com c²
          group["cena"].move_by(-shift, 0, time=1.0, ease="ease_in_out")
          await wait(1.0)
          st.deslocou = True

          criar_figura(ox + shift, oy, "direita", "direita_tri", com_c2=True)
          # Ajusta os rótulos "a" e "b" para ficarem próximos ao triângulo inferior direito da figura da direita
          Text(text="a", center=(220 + ox + lado + 22, oy + a / 2), font_size=18, color=cor_rotulo, group="direita")
          Text(text="b", center=(220 + ox + a + b / 2, oy - 22), font_size=18, color=cor_rotulo, group="direita")


          group["areas"].line = "#b8bfcc59"
          group["areas"].line_width = 1.5
          group["areas"].layer = -1
          group["areas"].visual = Halo(cor_efeito, style="pulse")
          group["direita"].fade_in(1)

          Text(
          text="a² + b² = c²",
          center=(cx, H - 100),
          font_size=36,
          color="#fff2bf",
          glow=True,
          group="equacao",
          ).fade_in(1)

          await wait(4)

          group["areas"].visual = None
          group["areas"].fill = cor_area

          dica.visible = True
          st.ocupado = False
          self.mode = None


guia = Guia()


def demonstrar():
    if st.ocupado:
        return
    guia.goto_mode(guia.prova)


def reiniciar():
    guia.mode = None
    guia.cancel_process()
    group["destaque"].destroy()
    group["areas"].destroy()
    group["equacao"].destroy()
    group["direita"].destroy()

    if st.deslocou:
        group["cena"].move_by(shift, 0)
        st.deslocou = False

    t1.move_to(t1_x0, t1_y0)
    t2.move_to(t2_x0, t2_y0)
    t3.move_to(t3_x0, t3_y0)
    t4.move_to(t4_x0, t4_y0)
    group["triangulos"].rotate_to(0)

    rotulo_a.center = (rotulo_a_x0, rotulo_a_y0)
    rotulo_b.center = (rotulo_b_x0, rotulo_b_y0)

    dica.visible = True
    group["triangulos"].draggable = True
    group["triangulos"].wheel_rotate = True
    st.ocupado = False


ui.scale = 0.9
Button(label="Demonstrar", on_click=demonstrar)
Button(label="Reiniciar", on_click=reiniciar)

run()
