"""Ninja IV · Hazards — tutorial 27.

The level from tutorial 26 with hazards (media/levels/ninja_hazards.json):
one-way platforms (resolve with only=), which you pass through from below
and drop off with the down arrow; a tilted board, where the ninja's
drawing leans around his feet (tilt, hitbox_anchor);
robots that turn at the edge
(floor_below); a second hitbox just for getting hurt (add_hitbox),
with a time of feeling nothing after each hit (untag / tag); electric
bolts that switch on and off (ElectricField, active); a golden elevator
that goes up and down forever (level_map["elevator"], Metal, move_by
with loops and yoyo) to a high star; and a restart with an act (Act,
change_act, new_game). With no lives left, the ninja falls to the floor
before the "dead" clip.

Controls
--------
  LEFT / RIGHT         walk
  UP                   jump
  DOWN                 drop off a platform
  SPACE                throw a kunai
  R                    restart

Usage
-----
    python examples/ninja_4_hazards.py
"""

from scena import *

init(width=1000, height=750, title="Ninja")
Wallpaper("tilesets/BG/BG.png", fit="tile", tile_size=(1000, 750), tile_mode="mirror", pan_response=0.1)
canvas.layers.create("far", pan_response=0.5, below="default")
for x in range(100, 2600, 300):
    Sprite("tilesets/Object/Tree_3.png", height=130, center=(x, 140), layer="far")

level_map = Level("levels/ninja_hazards.json")
canvas.playfield.set(level_map.box)



def new_game():
    st.stars = 0
    st.lives = 3
    st.drop = False
    st.notice = ""


new_game()

scoreboard = Text(text="", top_left=(20, 735), font_size=24, color="dark green")
scoreboard["text"] @= lambda: f"Stars {st.stars}"
Sprite("ninja/Idle__000.png", height=40, center=(890, 715), layer="ui")
lives = Text(text="", top_left=(915, 735), font_size=24, color="dark green")
lives["text"] @= lambda: f"x {st.lives}"
notice = Text(text="", center=(500, 680), font_size=36, color="dark green", layer="ui")
notice["text"] @= lambda: st.notice

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
        self.vel = Vec2(90, 0)
        self.play("walking")

    def on_update(self, dt):
        if self.vel.x > 0 and not self.floor_below(dx=40, group=["floor", "platform"]):
            self.vel.x = -90
            self.flip_x = True
        if self.vel.x < 0 and not self.floor_below(dx=-40, group=["floor", "platform"]):
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


class Hero(Sprite, source=ninja, group="hero", hitbox_shape="rect", hitbox_anchor="bottom"):
    def setup(self):
        self.vel = Vec2(0, 0)
        self.tilt = "ground"
        self.add_hitbox(group="hurt")
        self.prepare_fx(ElectricField)

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

        st.drop = recently("drop", keyp.once("DOWN"), hold=0.2)

        on_ground = "bottom" in self.touching_sides
        can_jump = recently("on_ground", on_ground, hold=0.12)
        if keyp.once("UP") and can_jump:
            self.vel.y = 900
            recently.reset("on_ground")
            play_sound("audio/jump.ogg")

        if keyp("SPACE") and ready("kunai", 0.4):
            self.play("playing", loops=1, next="idle")
            kunai = Kunai(center=(self.center.x, self.center.y + 50))
            kunai.rotate_to(self.angle)
            play_sound("audio/throw.ogg")

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
        play_sound("audio/coin.ogg")
        if st.stars == len(level_map.group("star")):
            st.notice = "All the stars!"
            play_sound("audio/victory.mp3")

    @when(lambda self: self.center.y < 30)
    def fell(self):
        self.lose()
        if st.lives > 0:
            self.center = level_map["spawn"].center
            self.vel = Vec2(0, 0)

    def lose(self):
        if st.lives == 0:
            return
        st.lives -= 1
        canvas.shake(6)
        if st.lives > 0:
            play_sound("audio/sfx-hit-2.ogg")
            self.blink(1.5)
            self.untag("hurt")
            self.after(1.5, lambda: self.tag("hurt"))
        else:
            play_sound("audio/gameover.ogg")
            st.notice = "GAME OVER · R restarts"


collision.floor = True
resolve("hero", "floor", bounce=0)
resolve("hero", "platform", bounce=0, only=lambda c: c.side == "bottom" and not st.drop)

@collide("robot", "hurt")
def touched(robot, hero, info):
    hero.lose()


@collide("bolt", "hurt")
def shock(bolt, hero, info):
    hero.lose()
    hero.save_visual()
    hero.visual = ElectricField("cyan")
    hero.glow = "light blue"
    hero.after(2.5, hero.restore_visual, name="shock")


@leave_playfield("kunai")
def gone(kunai):
    kunai.destroy()



class Play(Act):
    def setup(self):
        for decor in level_map.group("decor"):
            decor.make()
        for crate in level_map.group("crate"):
            crate.make()
        for piece in level_map.group("floor"):
            piece.make()
        for piece in level_map.group("platform"):
            piece.make()
        elevator = level_map["elevator"].make(group="platform", visual=Metal("gold"))
        elevator.move_by(0, 360, time=3, ease="ease_in_out", loops="forever", yoyo=True)
        for spot in level_map.group("wall"):
            wall = spot.make(group="floor")
            wall.visible = False
        group["floor"].mass = STATIC
        group["platform"].mass = STATIC

        self.hero = Hero(center=level_map["spawn"].center)

        for spot in level_map.group("star"):
            star = Sprite("k-rolling-ball/star.png", height=36, center=spot.center, group="star")
            star.scale_to(1.2, time=0.5, loops="forever", yoyo=True)

        for spot in level_map.group("robot"):
            Robot(center=spot.center)

        for water in level_map.group("water"):
            water.make()

        for spot in level_map.group("bolt"):
            spot.make(visual=ElectricField("cyan", amount=10))

        self.follow = False
        canvas.frame_to(level_map.box)
        self.after(2, self.start_round)

    def start_round(self):
        canvas.zoom_to(1, time=1)
        self.follow = True

    @every(1.5)
    def flicker(self):
        for bolt in group["bolt"]:
            bolt.active = not bolt.active

    def on_update(self, dt):
        if keyp.once("R"):
            new_game()
            change_act(Play)
            return
        if not self.follow:
            return
        face = (canvas.pan_x, canvas.pan_y)
        x, y = deadzone(face, self.hero.center, size=200)
        x = max(x, 500)
        x = min(x, 3500)
        canvas.pan_to(chase(face, (x, 375), rate=5))


run(Play)
