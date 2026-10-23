"""Plane — tutorial 15.

A plane flies between pillars. It does not move forward: the world moves, and
the stick raises and lowers the nose, with inertia (chase). Each pair of
pillars it gets through is worth a point (an invisible door in the gap). If it
hits a pillar or the ground, the plane falls; space restarts.

Controls
--------
  UP / DOWN            raise / lower the nose
  SPACE                restart, after the crash

Usage
-----
    python examples/plane.py
"""

from random import uniform
from scena import *

init(width=640, height=360, title="Plane")
Wallpaper("backgrounds/mountains/mountains1.png")

sheet = Sheet("plane/Fly1.png", "plane/Fly2.png", "plane/Dead.png")
sheet.clip("flying", [0, 1], fps=12)
sheet.clip("falling", [2])
pieces = Sheet("k-rolling-ball/rollingBall_sheet@2.png", atlas="k-rolling-ball/rollingBall_sheet@2.xml")

st.score = 0
st.flying = True

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
        notice.text = "press SPACE"


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
    notice.text = ""
    plane.center = (120, 200)
    plane.rotate_to(0)
    plane.play("flying")


def update(dt):
    if st.flying:
        group["pillar"].move_by(-120 * dt, 0)
        group["door"].move_by(-120 * dt, 0)
    elif keyp("SPACE"):
        restart()


@leave_playfield("pillar", "door")
def gone(thing):
    thing.destroy()


run()
