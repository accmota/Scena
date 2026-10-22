"""Banner — tutorial 04.

Type a phrase in the box (TextInput) and press Enter: it becomes the
banner, with font, gradient and glow, which wanders around the screen in
a figure eight (Track.eight + move_along).

Controls
--------
  keyboard  type in the box; Enter changes the banner
  Esc       lets go of the box; a click on it gives the keyboard back

Usage
-----
    python examples/banner.py
"""

from scena import *

init(width=1000, height=700, title="Banner")
Wallpaper(Gradient("black", "navy", angle=90))

banner = Text("Hello!", center=(500, 350), font_size=80, font="fonts/kenvector_future.ttf")
banner.fill = Gradient("sunset", angle=90)
banner.glow = "orange"

track = Track.eight(width=600, height=250)
banner.move_along(track, time=8, loops="forever")


def show(caption):
    banner.text = caption
    field.text = ""
    field.focus()


field = TextInput(placeholder="Type and press Enter", width=400, on_submit=show)
field.focus()

run()
