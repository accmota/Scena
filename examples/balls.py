"""Balls — tutorial 10.

Twenty balls bounce off the walls and off each other: two resolve
rules, one for ball and wall and another for ball and ball. Every hit
on a wall plays a sound and lights a flash where the ball touched. One
randomly chosen ball is gold and leaves two trails (Tail and Contrail).
A bar at the top shows its speed: the length and the color (a Colormap
ramp) are linked to its vel with @=.

Controls
--------
  MOUSE WHEEL          zoom in / out

Usage
-----
    python examples/balls.py
"""

from random import uniform, choice
from scena import *

init(width=1000, height=720, title="Balls")
SkyGradient("night")

Rect(center=(500, 16), width=1000, height=32, group="wall")
Rect(center=(500, 704), width=1000, height=32, group="wall")
Rect(center=(16, 360), width=32, height=720, group="wall")
Rect(center=(984, 360), width=32, height=720, group="wall")
group["wall"].visual = Metal()
group["wall"].mass = STATIC


class Ball(Circle, radius=14, color="tomato", group="ball"):
    def setup(self):
        self.vel = vec_from_angle(uniform(0, 360), length=uniform(180, 340))

    def on_update(self, dt):
        self.move_by(self.vel.x * dt, self.vel.y * dt)

    @collide_with("wall")
    def crashed(self, wall, info):
        canvas.hit_at(info, radius=10, style="disc")
        play_sound("audio/impactGeneric_light_003.ogg", volume=0.5)


resolve("ball", "wall", bounce=1)
resolve("ball", "ball", bounce=1)

for i in range(20):
    Ball(center=(uniform(80, 920), uniform(80, 640)))

chosen = choice(group["ball"])
chosen.color = "gold"
chosen.tail = Tail(color="gold", size=1.4, amount=1.2)

trail = Contrail(duration=8, fade=True, color="gold", line_width=3)
chosen.every(0.05, lambda: trail.snapshot(chosen))

ramp = Colormap.from_colors("lime", "gold", "red")

Rect(top_left=(40, 710), width=300, height=12, color="#262B55", layer="ui")
bar = Rect(top_left=(40, 710), width=0, height=12, layer="ui")
bar["width"] @= lambda: 300 * min(chosen.vel.length / 500, 1)
bar["color"] @= lambda: ramp.get_color(chosen.vel.length / 500)


def on_mouse_scroll(xoffset, yoffset):
    if yoffset > 0:
        canvas.zoom_by(1.1, about=mouse)
    else:
        canvas.zoom_by(1 / 1.1, about=mouse)


run()
