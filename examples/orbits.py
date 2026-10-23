"""Orbits — tutorial 14.

A solar system: planets with a radial gradient and Halo(style="fill") on
circular orbits, a moon on an orbit that moves with the Earth and leaves
a trail of little dots (History), a ring that
spins forever (rotate_by) and a sun that pulses (tween); the orbits draw
themselves at the start. A probe travels a figure eight, points (heading)
at the nearest planet (nearest) and stays connected to it by a line, which
becomes an electric bolt (ElectricBolt) when the distance drops below 120.

Usage
-----
    python examples/orbits.py
"""

from scena import *

init(width=1000, height=700, title="Orbits")
Wallpaper("#0b1020")
Stars()

sun = Circle(center=(500, 350), radius=44)
sun.fill = Gradient("light yellow", "orange", type="radial")
sun.visual = Halo(style="fill")
tween(sun["radius"], 52, time=1.5, ease="ease_in_out", loops="forever", yoyo=True)


def planet(orbit_radius, lap_time, size, inner_color, outer_color):
    orbit = Track.circle(center=sun.center, radius=orbit_radius, color="#2c3654")
    orbit.end = 0
    tween(orbit["end"], 1, time=2, ease="ease_out")
    ball = Circle(radius=size, group="planet")
    ball.fill = Gradient(inner_color, outer_color, type="radial")
    ball.visual = Halo(style="fill")
    ball.move_along(orbit, time=lap_time, loops="forever")
    return ball


planet(110, 5, 12, "white", "tomato")
earth = planet(190, 9, 18, "light cyan", "royal blue")
giant = planet(300, 16, 26, "khaki", "chocolate")

moon_orbit = Track.circle(center=lambda: earth.center, radius=40)
moon = Circle(radius=7, group="planet")
moon.fill = Gradient("white", "gray", type="radial")
moon.move_along(moon_orbit, time=2, loops="forever")

trail = History(max_points=80, on_leave=lambda dot: dot.dissolve_out(0.4))


def drop_dot():
    trail.add(Circle(center=moon.center, radius=2, color="light gray"))


every(0.05, drop_dot)

ring = Circle(center=lambda: giant.center, radius=40, color="khaki")
ring.fill = None
ring.line_width = 2
ring.dash = "dash"
ring.rotate_by(360, time=1.0, loops="forever")

route = Track.eight(width=820, height=520, center=(500, 350))
probe = Triangle(radius=14, color="white")
probe.move_along(route, time=14, loops="forever")

line = Line(p1=lambda: probe.center, p2=sun.center, color="light cyan")


def update(dt):
    target = group["planet"].nearest(probe)
    line.p2 = target.center
    probe.angle = heading(probe, target)
    if distance(probe, target) < 120:
        line.visual = ElectricBolt()
    else:
        line.visual = None


run()
