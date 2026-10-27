"""Ninja III · The level — tutorial 26.

The ninja from tutorial 19 in a level four times wider than the screen,
drawn in the level editor (media/levels/ninja_world.json): the code reads
the level (Level), creates the pieces of each group (make) and decides what
they are. The camera follows the ninja with slack and lag (deadzone and
chase), the HUD stays fixed to the window (layer="ui"), the background and a
row of trees move more slowly than the ground (pan_response), and the game
starts by showing the whole level (frame_to).

Controls
--------
  LEFT / RIGHT   walk
  UP             jump
  SPACE          throw a kunai

To see or change the level: python -m scena_editor media/levels/ninja_world.json

Usage
-----
    python examples/ninja_3_level.py
"""

from scena import *

init(width=1000, height=750, title="Ninja")
Wallpaper("tilesets/BG/BG.png", fit="tile", tile_size=(1000, 750), tile_mode="mirror", pan_response=0.1)
canvas.layers.create("far", pan_response=0.5, below="default")
for x in range(100, 2600, 300):
    Sprite("tilesets/Object/Tree_3.png", height=130, center=(x, 140), layer="far")

level_map = Level("levels/ninja_world.json")
canvas.playfield.set(level_map.box)

for decor in level_map.group("decor"):
    decor.make()
for piece in level_map.group("floor"):
    piece.make()
for spot in level_map.group("wall"):
    wall = spot.make(group="floor")
    wall.visible = False
group["floor"].mass = STATIC

st.stars = 0
st.lives = 3

scoreboard = Text(text="", top_left=(20, 735), font_size=24, color="dark green")
scoreboard["text"] @= lambda: f"Stars {st.stars}"
Sprite("ninja/Idle__000.png", height=40, center=(890, 715), layer="ui")
lives = Text(text="", top_left=(915, 735), font_size=24, color="dark green")
lives["text"] @= lambda: f"x {st.lives}"
notice = Text(text="", center=(500, 680), font_size=36, color="dark green", layer="ui")

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
        play_sound("audio/explosion02.ogg")
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
        if st.stars == len(level_map.group("star")):
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
            play_sound("audio/sfx-hit-2.ogg")
            self.center = level_map["spawn"].center
            self.vel = Vec2(0, 0)
            self.blink(1)
        else:
            play_sound("audio/gameover.ogg")
            notice.text = "GAME OVER"


collision.floor = True
resolve("hero", "floor", bounce=0)

hero = Hero(center=level_map["spawn"].center)

for spot in level_map.group("star"):
    star = Sprite("k-rolling-ball/star.png", height=36, center=spot.center, group="star")
    star.scale_to(1.2, time=0.5, loops="forever", yoyo=True)

for spot in level_map.group("robot"):
    Robot(center=spot.center)

for water in level_map.group("water"):
    water.make()


st.follow = False
canvas.frame_to(level_map.box)


@after(2)
def start_round():
    canvas.zoom_to(1, time=1)
    st.follow = True


def update(dt):
    if not st.follow:
        return
    face = (canvas.pan_x, canvas.pan_y)
    x, y = deadzone(face, hero.center, size=200)
    x = max(x, 500)
    x = min(x, 3500)
    canvas.pan_to(chase(face, (x, 375), rate=5))


@leave_playfield("kunai")
def gone(kunai):
    kunai.destroy()


run()
