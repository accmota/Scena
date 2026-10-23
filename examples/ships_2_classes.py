"""Ships II — tutorial 06.

The space shooter from tutorial 05, reorganized into classes: the shot
rises by itself, the enemy pulses and explodes, the ship reads the arrows
and carries a thruster. No lives, no restart.

Controls
--------
  LEFT / RIGHT   move
  SPACE          fire

Usage
-----
    python examples/ships_2_classes.py
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


class Shot(Sprite, source="space/laserBlue03.png", height=28, group="shots"):
    def on_update(self, dt):
        self.move_by(0, 640 * dt)


class EnemyShot(Sprite, source="space/laserRed01.png", height=28, group="enemy_shots"):
    def setup(self):
        self.rotate_to(180)

    def on_update(self, dt):
        self.move_by(0, -400 * dt)


class Enemy(Sprite, height=40, group="enemies"):
    def setup(self):
        self.scale_to(1.08, time=0.45, loops="forever", yoyo=True)

    @collide_with("shots")
    def was_hit(self, shot):
        canvas.burst_at(self, radius=40)
        shot.destroy()
        self.destroy()
        st.score += 1


class Hero(Sprite, source="space/playerShip1_red.png", height=45):
    def setup(self):
        self.glow = True
        self.thruster = Jet(origin=lambda: (self.center.x, self.center.y - 22),
                             angle=270, length=40, width=16, amount=2)

    def on_update(self, dt):
        if keyp("LEFT"):
            self.move_by(-340 * dt, 0)
        if keyp("RIGHT"):
            self.move_by(340 * dt, 0)
        self.confine(canvas.game_view.inset(40))

        if keyp("SPACE") and ready("shot", 0.2):
            Shot(center=(self.center.x, self.center.y + 28))

    @collide_with("enemy_shots")
    def was_hit(self, shot):
        shot.destroy()
        canvas.flash(0.4)
        canvas.explosion_at(self, amount=1.2)
        self.destroy()

    def on_destroy(self):
        self.thruster.destroy()


ship = Hero(center=(500, 70))

FLEET = ["space/enemyGreen1.png", "space/enemyBlue2.png"]
for row in range(3):
    for column in range(8):
        enemy = Enemy(FLEET[row % 2], center=(185 + column * 90, 720 - row * 70))
        enemy.hue = column / 8


@every(0.4)
def fleet_fires():
    if group["enemies"].count == 0:
        return
    enemy = choice(group["enemies"])
    EnemyShot(center=(enemy.center.x, enemy.center.y - 20))


def update(dt):
    group["enemies"].move_by(st.pace * dt, 0)

    for enemy in group["enemies"]:
        if enemy.center.x > 960:
            st.pace = -80
        if enemy.center.x < 40:
            st.pace = 80


@leave_playfield("shots", "enemy_shots")
def gone(shot):
    shot.destroy()


run()
