"""Starry sky — tutorial 11, Script 3.

The mouse on the canvas, with no object at all: the fixed-name functions
at the top level of the file (on_mouse_click, on_mouse_double_click,
on_mouse_drag, on_mouse_scroll).

Controls
--------
  click          lights a star
  drag           scatters stardust
  wheel          changes the size of the next star
  double click   clears the sky

Usage
-----
    python examples/starry_sky.py
"""

from scena import *

init(width=1000, height=700, title="Starry sky")
Wallpaper("black")

st.radius_value = 6
brush = Circle(center=lambda: mouse, radius=lambda: st.radius_value, color="white")
brush.fill = None


def on_mouse_click(x, y, button):
    star = Circle(center=(x, y), radius=st.radius_value, color="white", group="stars")
    star.glow = True


def on_mouse_double_click(x, y, button):
    group["stars"].destroy()


def on_mouse_drag(x, y, button):
    Circle(center=(x, y), radius=2, color="light steel blue", group="stars")


def on_mouse_scroll(xoffset, yoffset):
    st.radius_value = max(2, st.radius_value + yoffset)


run()
