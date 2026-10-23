"""Ninja II · The world — tutorial 19.

The ninja from tutorial 18 in a world to live in: a hole with water in
the middle of the ground, some slack for jumping at the edge (recently,
coyote time), five stars to catch, two patrolling robots, kunais that
break them (a clip that plays once and goes back) and three lives.
Falling into the water or touching a robot costs a life; with no lives
left, the game is over (to play again, run it again).

Controls
--------
  LEFT / RIGHT         walk
  UP                   jump
  SPACE                throw a kunai

Usage
-----
    python examples/ninja_2_world.py
"""

from scena import *

init(width=1000, height=750, title="Ninja")
Wallpaper("tilesets/BG/BG.png")

Sprite("tilesets/Object/Tree_2.png", height=230, center=(130, 195))
Sprite("tilesets/Object/Bush (1).png", height=50, center=(300, 105))
Sprite("tilesets/Object/Sign_2.png", height=60, center=(410, 110))
Sprite("tilesets/Object/Mushroom_1.png", height=30, center=(770, 95))
Sprite("tilesets/Object/Bush (3).png", height=40, center=(960, 100))

for i in range(5):
    Sprite("tilesets/Tiles/2.png", height=80, center=(40 + i * 80, 40), group="floor")
Sprite("tilesets/Tiles/3.png", height=80, center=(440, 40), group="floor")
Sprite("tilesets/Tiles/1.png", height=80, center=(680, 40), group="floor")
for i in range(9, 13):
    Sprite("tilesets/Tiles/2.png", height=80, center=(40 + i * 80, 40), group="floor")


def platform(x, y):
    Sprite("tilesets/Tiles/13.png", width=80, center=(x - 80, y), group="floor")
    Sprite("tilesets/Tiles/14.png", width=80, center=(x, y), group="floor")
    Sprite("tilesets/Tiles/15.png", width=80, center=(x + 80, y), group="floor")


platform(360, 220)
platform(720, 390)
platform(420, 560)
Rect(center=(-20, 375), width=40, height=750, group="floor")
Rect(center=(1020, 375), width=40, height=750, group="floor")
group["floor"].mass = STATIC

st.stars = 0
st.lives = 3

scoreboard = Text(text="", top_left=(20, 735), font_size=24, color="dark green")
scoreboard["text"] @= lambda: f"Stars {st.stars}"
Sprite("ninja/Idle__000.png", height=40, center=(890, 715))
lives = Text(text="", top_left=(915, 735), font_size=24, color="dark green")
lives["text"] @= lambda: f"x {st.lives}"
notice = Text(text="", center=(500, 680), font_size=36, color="dark green")

ninja = Sheet(anchor="bottom", pixel_size=0.2)
ninja.strip("idle", "ninja/Idle__*.png", fps=8)
ninja.strip("running", "ninja/Run__*.png", fps=12)
ninja.strip("jumping", "ninja/Jump__*.png", fps=10)
ninja.strip("playing", "ninja/Throw__*.png", fps=24)
ninja.strip("dead", "ninja/Dead__*.png", fps=12, offset=(0, -19))

robot = Sheet(anchor="bottom", pixel_size=0.16)
robot.strip("walking", "robot/Run (*).png", fps=12, offset=(0, -12))
robot.strip("broken", "robot/Dead (*).png", fps=12, offset=(0, -23))


class Kunai(Sprite, source="ninja/Kunai.png", height=44, art_angle=90, group="kunai"):
    def on_update(self, dt):
        arrow = vec_from_angle(self.angle, length=700)
        self.move_by(arrow.x * dt, 0)


class Robot(Sprite, source=robot, group="robot", hitbox_shape="rect"):
    def setup(self):
        self.mid = self.center.x
        self.vel = Vec2(90, 0)
        self.play("walking")

    def on_update(self, dt):
        if self.center.x > self.mid + 90:
            self.vel.x = -90
            self.flip_x = True
        if self.center.x < self.mid - 90:
            self.vel.x = 90
            self.flip_x = False
        self.move_by(self.vel.x * dt, 0)

    @collide_with("kunai")
    def was_hit(self, kunai):
        if self.showing("broken"):
            return
        kunai.destroy()
        self.untag("robot")
        self.vel.x = 0
        self.play("broken", loops=1)
        play_sound("audio/explosion02.wav")
        self.after(2, self.destroy)


class Hero(Sprite, source=ninja, group="hero", hitbox_shape="rect"):
    def setup(self):
        self.vel = Vec2(0, 0)

    def on_update(self, dt):
        if st.lives == 0:
            self.vel.y -= 2200 * dt
            self.move_by(0, self.vel.y * dt)
            if "bottom" in self.touching_sides and not self.showing("dead"):
                self.play("dead", loops=1)
            return

        if keyp("LEFT"):
            self.vel.x = -280
            self.flip_x = True
        elif keyp("RIGHT"):
            self.vel.x = 280
            self.flip_x = False
        else:
            self.vel.x = 0

        on_ground = "bottom" in self.touching_sides
        can_jump = recently("on_ground", on_ground, hold=0.12)
        if keyp.once("UP") and can_jump:
            self.vel.y = 900
            recently.reset("on_ground")
            play_sound("synth/jump.wav")

        if keyp("SPACE") and ready("kunai", 0.4):
            self.play("playing", loops=1, next="idle")
            kunai = Kunai(center=(self.center.x, self.center.y + 50))
            kunai.rotate_to(self.angle)
            play_sound("synth/throw.wav")

        self.vel.y -= 2200 * dt
        self.move_by(self.vel.x * dt, self.vel.y * dt)

        if self.showing("playing"):
            return
        if not on_ground:
            self.play("jumping")
        elif self.vel.x != 0:
            self.play("running")
        else:
            self.play("idle")

    @collide_with("star")
    def caught(self, star):
        star.destroy()
        st.stars += 1
        play_sound("synth/coin.wav")
        if st.stars == 5:
            notice.text = "All the stars!"
            play_sound("audio/Victory.mp3")

    @collide_with("robot")
    def crashed(self, robot):
        self.lose()

    @when(lambda self: self.center.y < 30)
    def fell(self):
        self.lose()

    def lose(self):
        if st.lives == 0:
            return
        st.lives -= 1
        canvas.shake(6)
        if st.lives > 0:
            play_sound("audio/sfx-hit-2.wav")
            self.center = (100, 400)
            self.vel = Vec2(0, 0)
            self.blink(1)
        else:
            play_sound("audio/gameover.wav")
            notice.text = "GAME OVER"


collision.floor = True
resolve("hero", "floor", bounce=0)

hero = Hero(center=(100, 400))

for x, y in [(360, 300), (560, 220), (720, 470), (420, 640), (960, 150)]:
    star = Sprite("k-rolling-ball/star.png", height=36, center=(x, y), group="star")
    star.scale_to(1.2, time=0.5, loops="forever", yoyo=True)

Robot(center=(840, 80))
Robot(center=(720, 419))

Sprite("tilesets/Tiles/17.png", width=80, center=(520, 31))
Sprite("tilesets/Tiles/17.png", width=80, center=(600, 31))


@leave_playfield("kunai")
def gone(kunai):
    kunai.destroy()


run()
