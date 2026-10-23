"""Ships — tutorial 05.

A simple ship game: the ship shoots, the fleet breathes, goes back and forth and fires back.
No lives, no restart.

Controls
--------
  LEFT / RIGHT   move
  SPACE          shoot

Usage
-----
    python examples/ships_1.py
"""

from random import choice
from scena import *

init(width=1000, height=800, title="Ships")
Wallpaper(Gradient("dark dark blue", "black", angle=90))
Stars(pan_response=0.0, scroll=(0.0, -38.0))
Grain()
Bloom()
Scanlines()

st.score = 0
st.pace = 80

scoreboard = Text(text="", top_left=(20, 780), font_size=20)
scoreboard["text"] @= lambda: f"Score {st.score}"

ship = Sprite("space/playerShip1_red.png", height=45, center=(500, 70))
ship.glow = True

FLEET = ["space/enemyGreen1.png", "space/enemyBlue2.png"]
for row in range(3):
    for column in range(8):
        enemy = Sprite(
            FLEET[row % 2],
            height=40,
            center=(185 + column * 90, 720 - row * 70),
            group="enemies",
        )
        enemy.hue = column / 8
        enemy.scale_to(1.08, time=0.45, loops="forever", yoyo=True)


@every(0.4)
def fleet_fires():
    if group["enemies"].count == 0:
        return
    enemy = choice(group["enemies"])
    s = Sprite("space/laserRed01.png", height=28,
           center=(enemy.center.x, enemy.center.y - 20), group="enemy_shots")
    s.rotate_to(180)

def update(dt):
    if ship:
        if keyp("LEFT"):
            ship.move_by(-340 * dt, 0)
        if keyp("RIGHT"):
            ship.move_by(340 * dt, 0)
        ship.confine(canvas.game_view.inset(40))

        if keyp("SPACE") and ready("shot", 0.2):
            Sprite("space/laserBlue03.png", height=28, center=(ship.center.x, ship.center.y + 28), group="shots")

    group["shots"].move_by(0, 640 * dt)
    group["enemy_shots"].move_by(0, -400 * dt)

    group["enemies"].move_by(st.pace * dt, 0)

    for enemy in group["enemies"]:
        if enemy.center.x > 960:
            st.pace = -80
        if enemy.center.x < 40:
            st.pace = 80


@leave_playfield("shots", "enemy_shots")
def gone(shot):
    shot.destroy()


@collide("shots", "enemies")
def struck(shot, enemy):
    canvas.burst_at(enemy, radius=40)
    shot.destroy()
    enemy.destroy()
    st.score += 1


@collide("enemy_shots", ship)
def hit(shot, ship):
    shot.destroy()
    canvas.flash(0.4)
    canvas.explosion_at(ship, amount=1.2)
    ship.destroy()


run()
