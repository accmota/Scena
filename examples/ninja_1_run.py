"""Ninja — tutorial 18.

A ninja in a platform game: gravity written by hand (a velocity that grows
downward every frame), the floor and platforms that hold him up (resolve
with bounce=0), the jump only with his feet on the ground (touching_sides)
and three animations from files of different sizes (strip with *,
pixel_size and anchor="bottom").

Controls
--------
  LEFT / RIGHT         walk
  UP                   jump

Usage
-----
    python examples/ninja_1_run.py
"""

from scena import *

init(width=1000, height=750, title="Ninja")
Wallpaper("tilesets/BG/BG.png")

for i in range(13):
    Sprite("tilesets/Tiles/2.png", height=80, center=(40 + i * 80, 40), group="floor")


def platform(x, y):
    Sprite("tilesets/Tiles/13.png", width=80, center=(x - 80, y), group="floor")
    Sprite("tilesets/Tiles/14.png", width=80, center=(x, y), group="floor")
    Sprite("tilesets/Tiles/15.png", width=80, center=(x + 80, y), group="floor")


platform(360, 220)
platform(720, 390)
Rect(center=(-20, 375), width=40, height=750, group="floor")
Rect(center=(1020, 375), width=40, height=750, group="floor")
group["floor"].mass = STATIC

ninja = Sheet(anchor="bottom", pixel_size=0.2)
ninja.strip("idle", "ninja/Idle__*.png", fps=8)
ninja.strip("running", "ninja/Run__*.png", fps=12)
ninja.strip("jumping", "ninja/Jump__*.png", fps=10)


class Hero(Sprite, source=ninja, group="hero", hitbox_shape="rect"):
    def setup(self):
        self.vel = Vec2(0, 0)

    def on_update(self, dt):
        if keyp("LEFT"):
            self.vel.x = -280
            self.flip_x = True
        elif keyp("RIGHT"):
            self.vel.x = 280
            self.flip_x = False
        else:
            self.vel.x = 0

        on_ground = "bottom" in self.touching_sides
        if keyp.once("UP") and on_ground:
            self.vel.y = 900
            play_sound("synth/jump.wav")

        self.vel.y -= 2200 * dt
        self.move_by(self.vel.x * dt, self.vel.y * dt)

        if not on_ground:
            self.play("jumping")
        elif self.vel.x != 0:
            self.play("running")
        else:
            self.play("idle")


collision.floor = True
resolve("hero", "floor", bounce=0)

hero = Hero(center=(100, 400))


run()
