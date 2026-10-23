"""Plane III · Endless Landscape — tutorial 17.

The plane from tutorial 16 with a landscape that never repeats: the strips of
clouds and fields pick a random image for each slot (Endless with a list),
loose trees, houses and towers are built by a function (Endless with
slot.rng and slot.chance), and the bushes pass in front of the plane, on a
layer faster than the game.

Controls
--------
  UP / DOWN            raise / lower the nose
  SPACE                start over, after a crash

Usage
-----
    python examples/plane_landscape.py
"""

from random import uniform
from scena import *

init(width=640, height=360, title="Plane")
Wallpaper("backgrounds/mountains/mountains1.png")

CLOUDS = ["backgrounds/mountains/clouds.png",
          "backgrounds/mountains/clouds-low.png",
          "backgrounds/mountains/clouds-bank.png"]
FIELDS = ["backgrounds/mountains/vegetation_a.png",
          "backgrounds/mountains/vegetation_b.png"]

clouds = canvas.layers.create("clouds", scroll=(-12, 0), below="default")
bank = canvas.layers.create("bank", scroll=(-24, 0), below="default")
hills = canvas.layers.create("hills", scroll=(-36, 0), below="default")
field = canvas.layers.create("field", scroll=(-60, 0), below="default")
decorations = canvas.layers.create("decorations", scroll=(-60, 0), below="default")
bushes = canvas.layers.create("bushes", scroll=(-168, 0), above="default")
Endless("clouds", "backgrounds/mountains/mountains2.png", height=360)
Endless("bank", CLOUDS, height=360)
Endless("hills", "backgrounds/mountains/mountains3.png", height=360)
Endless("field", FIELDS, height=360)
Endless("bushes", "backgrounds/mountains/mountains4.png", height=200)

scenery = Sheet("backgrounds/kn/bgElements_spritesheet.png", atlas="backgrounds/kn/bgElements_spritesheet.xml")
TREES = ["tree02.png", "tree05.png", "tree10.png", "tree20.png", "tree27.png", "tree31.png", "tree34.png"]
HOUSES = ["house_beige_front.png", "house_beige_side.png", "house_grey_side.png", "tower_beige.png", "castle_grey.png"]


def decor(slot):
    x = slot.rng.uniform(slot.left + 20, slot.right - 20)
    if slot.chance(0.2):
        return Sprite(scenery, frame=slot.rng.choice(HOUSES), height=50, center=(x, 75))
    if slot.chance(0.3):
        return []
    height = slot.rng.uniform(50, 90)
    return Sprite(scenery, frame=slot.rng.choice(TREES), height=height, center=(x, 50 + height / 2))


Endless("decorations", decor, step=110)

sheet = Sheet("plane/Fly1.png", "plane/Fly2.png", "plane/Dead.png")
sheet.clip("flying", [0, 1], fps=12)
sheet.clip("falling", [2])
pieces = Sheet("k-rolling-ball/rollingBall_sheet@2.png", atlas="k-rolling-ball/rollingBall_sheet@2.xml")

st.score = 0
st.flying = True
st.pace = 120

music = play_sound("audio/SuperHero_original_no_Intro.ogg", loops="forever", volume=0.5)

scoreboard = Text(text="", top_left=(16, 346), font_size=18, color="navy")
scoreboard["text"] @= lambda: f"Score {st.score}"
notice = Text(text="", center=(320, 200), font_size=24, color="navy")


class Plane(Sprite, source=sheet, height=40):
    def setup(self):
        self.play("flying")

    def on_update(self, dt):
        if st.flying:
            goal = 0
            if keyp("UP"):
                goal = 30
            if keyp("DOWN"):
                goal = -30
            self.rotate_to(chase(self.angle, goal, rate=4))
            arrow = vec_from_angle(self.angle, length=220)
            self.move_by(0, arrow.y * dt)
            self.confine(canvas.game_view)
            if self.center.y < 30:
                self.fall()
        elif self.center.y > 30:
            self.rotate_to(chase(self.angle, -60, rate=3))
            self.move_by(0, -160 * dt)

    @collide_with("door")
    def passed(self, door):
        door.destroy()
        st.score += 1
        play_sound("audio/fx2.wav")

    @collide_with("pillar")
    def crashed(self, pillar):
        if st.flying:
            self.fall()

    def fall(self):
        st.flying = False
        self.play("falling")
        canvas.shake(6)
        play_sound("audio/explosion02.wav")
        self.move_to_front()
        self.fire = Fire(center=lambda: self.center + Vec2(-20, 8).rotate(self.angle), width=12, style="tongues")
        notice.text = "press SPACE"
        music.fade_to(0.1, time=1)


plane = Plane(center=(120, 200))


def new_pair():
    mid = uniform(110, 250)
    Sprite(pieces, frame="block_narrow.png", height=260, center=(680, mid + 190), group="pillar")
    Sprite(pieces, frame="block_narrow.png", height=260, center=(680, mid - 190), group="pillar")
    door = Rect(center=(690, mid), width=10, height=120, group="door")
    door.visible = False


@every(2)
def more_pillars():
    if st.flying:
        new_pair()


def restart():
    group["pillar"].destroy()
    group["door"].destroy()
    st.score = 0
    st.flying = True
    st.pace = 120
    notice.text = ""
    plane.center = (120, 200)
    plane.rotate_to(0)
    plane.play("flying")
    plane.fire.destroy()
    music.fade_to(0.5, time=1)


def update(dt):
    if not st.flying:
        st.pace = chase(st.pace, 0, rate=2)
        if keyp("SPACE"):
            restart()
    group["pillar"].move_by(-st.pace * dt, 0)
    group["door"].move_by(-st.pace * dt, 0)
    clouds.scroll = (-st.pace * 0.1, 0)
    bank.scroll = (-st.pace * 0.2, 0)
    hills.scroll = (-st.pace * 0.3, 0)
    field.scroll = (-st.pace * 0.5, 0)
    decorations.scroll = (-st.pace * 0.5, 0)
    bushes.scroll = (-st.pace * 1.4, 0)


@leave_playfield("pillar", "door")
def gone(thing):
    thing.destroy()


run()
