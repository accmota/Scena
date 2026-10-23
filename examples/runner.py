"""Endless Runner — tutorial 29.

A robot runs on its own along a track that never ends, faster and faster.
The track is built slot by slot by an Endless ahead of the camera and
destroyed behind it: textured dirt ground (four-cornered columns), holes,
coins, crates, decorations, and wood and stone platforms (a texture plus a
visual, one-way). The height of the ground is a function of x, so the slots
join without a step; what stays inside each slot comes from its own draw
(slot.rng). The play area (playfield) moves with the camera, the race ends
in a hole or on a crate, and the act starts over. In the background, two
strips of silhouettes on layers that move less than the world
(pan_response).

Controls
--------
  UP       jump (only with the feet on the ground)
  SPACE    start over, after the race ends

Usage
-----
    python examples/runner.py
"""

from math import sin
from scena import *

init(width=960, height=540, title="Runner")
Wallpaper(Gradient("#3d97d6", "#9fd4f0", angle=90))
collision.floor = True

sheet = Sheet(anchor="bottom", pixel_size=0.16)
sheet.strip("running", "robot/Run (*).png", fps=14)
sheet.strip("jumping", "robot/Jump (*).png", fps=14)
sheet.strip("falling", "robot/Dead (*).png", fps=20)
scenery = Sheet("backgrounds/kn/bgElements_spritesheet.png", atlas="backgrounds/kn/bgElements_spritesheet.xml")

DIRT = Texture("k-textures/floor_ground_dirt.png", fit="tile", tile_size=64)
WOOD = Texture("textures/236.jpg", fit="tile", tile_size=64)
STONE = Texture("k-textures/wall_stone.png", fit="tile", tile_size=40)
BUSHES = ["tilesets/Object/Bush (1).png", "tilesets/Object/Bush (3).png", "tilesets/Object/Mushroom_1.png",
          "tilesets/Object/Mushroom_2.png", "tilesets/Object/Sign_2.png"]
SILHOUETTES = ["castle.png", "tower.png", "tree01.png", "tree08.png", "tree11.png", "tree12.png", "house_side_tall.png"]


def ground_height(x):
    return 130 + 55 * sin(x / 400) + 25 * sin(x / 150)


def column(x):
    floor = Polygon(points=[(x, 0), (x + 64, 0), (x + 64, ground_height(x + 64)), (x, ground_height(x))], group="floor")
    floor.fill = DIRT
    floor.line = DIRT
    floor.mass = STATIC
    grass = Line(p1=(x, ground_height(x) - 4), p2=(x + 64, ground_height(x + 64) - 4), color="#6fa124", line_width=16)
    sprout = Line(p1=(x, ground_height(x)), p2=(x + 64, ground_height(x + 64)), color="#b3d02a", line_width=8)
    return [floor, grass, sprout]


def coins(x, y):
    row = []
    for k in range(3):
        row.append(Circle(center=(x - 36 + 36 * k, y), radius=11, visual=Sphere("orange"), group="coin"))
    return row


def platform(slot, x, y):
    plank = Rect(center=(x, y), width=128, height=24, group="plank")
    plank.mass = STATIC
    if slot.chance(0.5):
        plank.fill = WOOD
        plank.visual = Extrude(depth=20, angle=270)
    else:
        plank.fill = STONE
        plank.visual = Ink()
    return plank


def stretch(slot):
    columns = 6
    if slot.i > 1 and slot.chance(0.4):
        columns = 3
    pieces = []
    for k in range(columns):
        pieces += column(slot.left + 64 * k)
    if columns == 3 and slot.chance(0.6):
        mid = slot.left + 288
        pieces.append(platform(slot, mid, ground_height(mid) + 100))
        pieces += coins(mid, ground_height(mid) + 150)
    x = slot.rng.uniform(slot.left + 40, slot.left + 64 * columns - 40)
    if slot.chance(0.4):
        pieces += coins(x, ground_height(x) + 120)
    elif slot.i > 2 and slot.chance(0.5):
        pieces.append(Sprite("tilesets/Object/Crate.png", height=50, center=(x, ground_height(x) + 22), group="crate"))
    else:
        pieces.append(Sprite(slot.rng.choice(BUSHES), height=40, center=(x, ground_height(x) + 16)))
    return pieces


def far(slot):
    ridge = Sprite(scenery, frame="pointy_mountains.png", width=1400, center=(slot.left + 700, 170))
    ridge.set_alpha(0.6)
    cloud = Sprite(scenery, frame=f"cloud{slot.rng.randint(1, 9)}.png", height=slot.rng.uniform(50, 80),
                   center=(slot.rng.uniform(slot.left, slot.right), slot.rng.uniform(400, 480)))
    return [ridge, cloud]


def hills(slot):
    pieces = []
    for k in range(3):
        x = slot.rng.uniform(slot.left, slot.right)
        tall = slot.rng.uniform(120, 200)
        pieces.append(Sprite(scenery, frame=slot.rng.choice(SILHOUETTES), height=tall, center=(x, 110 + tall / 2)))
    pieces.append(Sprite(scenery, frame="hills1.png", width=1000, center=(slot.left + 500, 64)))
    return pieces


st.record = 0


class Robot(Sprite, source=sheet, hitbox_shape="rect", hitbox_anchor="bottom"):
    def setup(self):
        self.vel = Vec2(0, 0)
        self.tilt = "ground"
        resolve(self, "floor", bounce=0)
        resolve(self, "plank", bounce=0, only="bottom")

    def on_update(self, dt):
        on_ground = "bottom" in self.touching_sides
        if keyp.once("UP") and on_ground:
            self.vel.y = 900
            play_sound("synth/jump.wav")
        self.vel.y -= 2200 * dt
        if not st.running:
            if not self.showing("falling"):
                self.play("falling", loops=1)
        elif on_ground:
            self.play("running")
        else:
            self.play("jumping")
        self.move_by(st.pace * dt, self.vel.y * dt)

    @collide_with("coin")
    def caught(self, coin):
        coin.destroy()
        st.coins += 1
        play_sound("synth/coin.wav")

    @collide_with("crate")
    def crashed(self, crate):
        if st.running:
            st.running = False
            st.pace = 0
            canvas.shake(6)
            play_sound("audio/impactPlank_medium_002.ogg")

    @leave_playfield
    def fell(self):
        st.running = False
        st.pace = 0


class Race(Act):
    def setup(self):
        st.pace = 320
        st.running = True
        st.coins = 0
        st.meters = 0
        canvas.layers.create("far", pan_response=0.1, below="default")
        canvas.layers.create("hills", pan_response=0.3, below="default")
        canvas.layers.create("track", below="default")
        Endless("far", far, step=1400)
        Endless("hills", hills, step=1000)
        Endless("track", stretch, step=384)
        self.robot = Robot(center=(200, 300))
        scoreboard = Text(text="", top_left=(16, 524), font_size=20, color="navy")
        scoreboard["text"] @= lambda: f"{st.meters} m   Coins {st.coins}   High score {st.record} m"
        self.notice = Text(text="", center=(480, 400), font_size=32, color="navy", layer="ui")

    def on_update(self, dt):
        canvas.pan_to(self.robot.center.x + 250, 270)
        canvas.playfield.set(canvas.game_view.outset(100))
        if st.running:
            st.pace += 6 * dt
            st.meters = int(self.robot.center.x / 64)
        elif keyp.once("SPACE"):
            change_act(Race)

    @when(lambda self: not st.running)
    def ended(self):
        st.record = max(st.record, st.meters)
        self.notice.text = "press SPACE"


run(Race)
