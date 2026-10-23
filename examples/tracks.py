"""Tracks — tutorial 13.

A showcase of tracks (Track) and of ways to travel them with
move_along: a circle, a figure eight with a triangle that points along
the path (face=True), a star, a shuttle, an open path traveled there
and back (yoyo=True), a pendulum with ease="ease_in_out" and a train of
eight wagons spaced with phase=.

Controls
--------
  CTRL+SHIFT+7         shows the tracks in magenta

Usage
-----
    python examples/tracks.py
"""

from scena import *

init(width=1000, height=700, title="Tracks")
Wallpaper("#141b2d")

wheel = Track.circle(center=(170, 520), radius=110, color="dim gray")
ball = Circle(radius=14, color="coral")
ball.move_along(wheel, time=4, loops="forever")

figure8 = Track.eight(width=300, height=120, center=(500, 540), color="dim gray")
car = Triangle(radius=16, color="gold")
car.move_along(figure8, time=6, loops="forever", face=True)

star = Track.star(points=5, radius=110, center=(830, 520), color="dim gray")
comet = Circle(radius=12, color="turquoise")
comet.move_along(star, time=8, loops="forever")

seesaw = Track.shuttle(length=300, center=(500, 380), color="dim gray")
piston = Circle(radius=12, color="orchid")
piston.move_along(seesaw, time=3, loops="forever")

path = Track(points=[(60, 100), (160, 290), (260, 120), (380, 240)], color="dim gray")
ant = Circle(radius=12, color="light green")
ant.move_along(path, time=3, loops="forever", yoyo=True)

swing = Track.arc(center=(560, 330), radius=200, from_angle=225, to_angle=315, color="dim gray")
bob = Circle(radius=18, color="sky blue")
bob.move_along(swing, time=1.2, loops="forever", yoyo=True, ease="ease_in_out")
wire = Line(p1=(560, 330), p2=lambda: bob.center, color="white")

ring = Track(points=[(760, 80), (940, 120), (900, 300), (720, 260)], closed=True, color="dim gray")
for i in range(8):
    wagon = Circle(radius=8, color="gold")
    wagon.move_along(ring, time=8, loops="forever", phase=i / 8)

run()
