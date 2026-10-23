"""Bubbles — tutorial 06, Script 1.

Bubbles of many sizes rise from the bottom of the sea; the big ones rise
faster. When one goes past the top, it comes back from the bottom. A click
pops the bubble into a foam of tiny bubbles. Shows a class (the mold),
each object's fields, setup, on_update and on_click.

Controls
--------
  Click a bubble to pop it.

Usage
-----
    python examples/bubbles.py
"""

from random import uniform
from scena import *

init(width=1000, height=700, title="Bubbles")
Wallpaper(Gradient("dark navy", "teal", angle=90))


class Bubble(Circle, radius=30, visual=Halo("sky blue")):
    def setup(self):
        self.pace = self.radius * 4

    def on_update(self, dt):
        self.move_by(0, self.pace * dt)
        if self.center.y > 760:
            self.move_by(0, -820)

    def on_click(self):
        canvas.bubbles_at(self, color="sky blue")
        self.destroy()


for column in range(9):
    Bubble(center=(100 + column * 100, -50), radius=uniform(15, 45))

run()
