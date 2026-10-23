"""Movement — tutorial 12.

A ship that goes wherever you click: move_to with speed=, ease= and face=,
a target that disappears on arrival (on_done=), the trip's handle (cancel)
to change destination or stop, and chasing the mouse every frame
with approach.

Controls
--------
  click            the ship travels to the point
  Space            stops the ship
  right button     held, the ship chases the mouse

Usage
-----
    python examples/movement.py
"""

from scena import *

init(width=1000, height=700, title="Movement")
Wallpaper("#0b1020")
Stars()

target = Circle(center=(500, 350), radius=24, color="gold")
target.fill = None
target.dash = "dash"
target.visible = False

ship = Sprite("space/playerShip1_red.png", width=60, center=(500, 350), art_angle=90)
ship.trip = None


def landed():
    ship.trip = None
    target.visible = False


def halt():
    if ship.trip:
        ship.trip.cancel()
        ship.trip = None
    target.visible = False


def on_mouse_click(x, y, button):
    halt()
    target.center = (x, y)
    target.visible = True
    ship.trip = ship.move_to(x, y, speed=400, ease="ease_in_out", face=True, on_done=landed)


def update(dt):
    if keyp.once("SPACE"):
        halt()
    if mouse.press(Mouse.BTN_RIGHT):
        halt()
        ship.move_to(approach(ship.center, mouse, 300), face=True)


run()
