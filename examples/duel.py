"""Duel — tutorial 31.

Two players on the same keyboard, a closed arena read from a level file
(levels/duel.json). Each ship moves held to a curved rail, up and down,
and turns like a steering wheel to aim; the step and the turn build up
gradually (chase). The lasers bounce off the walls up to three times and
curve near the Warp in the middle, which pulls only the shots, with a
force that falls with the cube of the distance. Two barriers of crates
protect the ships at the start; asteroids drift and split in two; two
pairs of balls go around an upright figure eight and, when they pass
close, an electric bolt links them and burns the lasers. Every now and
then a star crosses the arena: a shot breaks it, and it drops a power-up
(energy or shield) that curves to where the ship that fired was. At the
opening, each player picks a ship (it only changes the picture).

Controls
--------
  Left (blue)         W / S move along the rail · A / D turn · TAB fires
  Right (red)         UP / DOWN move along the rail · LEFT / RIGHT turn · ENTER fires
  At the choice       A / D and LEFT / RIGHT choose · TAB and ENTER confirm
  After a victory     SPACE goes back to the choice

Usage
-----
    python examples/duel.py
"""

from random import choice, uniform
from scena import *

init(width=1280, height=720, title="Duel")
Stardust(color="violet", color2="teal")
ColorWash("navy", "teal", "purple", amount=0.25)

sheet = Sheet("shooter/sheet.png", atlas="shooter/sheet.xml")
level = Level("levels/duel.json")
HOLE = level["hole"].center
EDGE = 60      # the Warp's radius
PULL = 400     # the pull at the Warp's edge: how much speed a shot there gains per second

LEFT_KEYS = {"up": "W", "down": "S", "left": "A", "right": "D", "shot": "TAB"}
RIGHT_KEYS = {"up": "UP", "down": "DOWN", "left": "LEFT", "right": "RIGHT", "shot": "ENTER"}

st.blue_variant = 1
st.red_variant = 1
st.winner = ""


class Shot(Sprite, source=sheet, height=26, art_angle=90, hitbox_shape="circle", group="shots"):
    def setup(self):
        self.vel = Vec2(0, 0)
        self.bounces = 0
        # "add" adds the laser's light to the background: it glows, at no cost.
        self.blend = "add"

    def on_update(self, dt):
        # near is 1 at the Warp's edge, 1/2 at twice the distance, 1/3 at
        # three times. Cubed, the pull falls fast: 1/8 at twice, 1/27 at three times.
        # Inside the edge it grows no more; beyond 300 it is not worth the math.
        d = distance(self, HOLE)
        if d < 300:
            near = EDGE / max(d, EDGE)
            self.vel += vec_from_angle(heading(self, HOLE), PULL * near ** 3 * dt)
        self.angle = self.vel.angle
        self.move_by(self.vel.x * dt, self.vel.y * dt)

    @collide_with("wall")
    def crashed(self, wall, info):
        self.bounces += 1
        if self.bounces > 3:
            canvas.hit_at(info, style="disc", radius=10)
            self.destroy()


class ShieldBubble(Circle, radius=44, visual=Shield(style="plasma")):
    def setup(self):
        self.charges = 0

    @collide_with("shots")
    def absorbed(self, shot, info):
        shot.destroy()
        canvas.zap_at(info, color="sky blue")
        play_sound("audio/sfx-hit-2.ogg", pitch=1.6)
        self.spend()

    # The shield shatters the whole asteroid: two pieces born
    # touching it would use up the other charges at once.
    @collide_with("asteroids")
    def deflected(self, asteroid, info):
        canvas.zap_at(info, color="sky blue")
        canvas.debris_at(asteroid, color="sienna", radius=asteroid.height)
        play_sound("audio/impactPunch_heavy_001.ogg", volume=0.6)
        asteroid.destroy()
        self.spend()

    def spend(self):
        self.charges -= 1
        if self.charges == 0:
            canvas.burst_at(self, radius=70, rings=True)
            play_sound("audio/impactBell_heavy_000.ogg")
            self.active = False


class Ship(Sprite, source=sheet, height=50, art_angle=90, group="ships"):
    def setup(self):
        # Held to its rail, the ship does not give way: an asteroid bounces off it.
        self.mass = STATIC
        self.turn = 0
        self.step = 0
        self.u = 0.5
        self.energy = 100
        self.jet = Jet(origin=self.center, length=40, width=14, amount=0)
        self.fire = Fire(center=lambda: self.center - vec_from_angle(self.angle, 22), angle=lambda: self.angle + 180, width=16, length=40, style="plume")
        self.fire.active = False
        self.shield = ShieldBubble(center=lambda: self.center)
        self.shield.active = False

    def on_update(self, dt):
        # The steering wheel: the turn builds up slowly and dies down slowly.
        goal = 0
        if keyp(self.controls["left"]):
            goal = 200
        if keyp(self.controls["right"]):
            goal = -200
        self.turn = chase(self.turn, goal, 5)
        self.rotate_by(self.turn * dt)

        # u is the place on the rail: 0 at one end, 1 at the other.
        goal = 0
        if keyp(self.controls["up"]):
            goal = 260
        if keyp(self.controls["down"]):
            goal = -260
        self.step = chase(self.step, goal, 5)
        self.u += self.step * dt / self.rail.length
        if self.u > 1:
            self.u = 1
            self.step = 0
        if self.u < 0:
            self.u = 0
            self.step = 0
        self.center = self.rail.at(self.u)

        # The jet comes out behind the movement, along the rail, and
        # grows with the speed.
        direction = self.rail.angle_at(self.u)
        if self.step < 0:
            direction += 180
        self.jet.origin = self.center - vec_from_angle(direction, 22)
        self.jet.angle = direction + 180
        self.jet.amount = abs(self.step) / 160

        if keyp(self.controls["shot"]) and self.ready("shot", 0.3):
            self.shoot()

    def shoot(self):
        shot = Shot(frame=self.laser, center=self.center + vec_from_angle(self.angle, 52))
        shot.vel = vec_from_angle(self.angle, 700)
        shot.shooter = self
        play_sound("space/sfx_laser1.ogg", volume=0.6)

    @when(lambda self: self.energy < 30)
    def caught_fire(self):
        self.fire.active = True

    @when(lambda self: self.energy >= 30)
    def faded(self):
        self.fire.active = False

    def on_destroy(self):
        self.jet.destroy()
        self.fire.destroy()
        self.shield.destroy()
        self.bar.destroy()


class Asteroid(Sprite, source=sheet, frame="meteorBrown_big1.png", height=64,
                hitbox_shape="circle", group="asteroids"):
    def setup(self):
        self.vel = vec_from_angle(uniform(0, 360), uniform(40, 90))
        self.turn = uniform(-60, 60)

    def on_update(self, dt):
        self.rotate_by(self.turn * dt)
        self.move_by(self.vel.x * dt, self.vel.y * dt)

    @collide_with("shots")
    def was_hit(self, shot, info):
        canvas.debris_at(self, color="sienna", radius=self.height)
        play_sound("audio/impactPunch_heavy_001.ogg", volume=0.6)
        # The big one splits in two small ones, which fly off to the sides of the shot.
        if self.height > 40:
            for side in [90, -90]:
                chunk = Asteroid(frame="meteorBrown_small1.png", height=30,
                                   center=self.center + vec_from_angle(shot.vel.angle + side, 18))
                chunk.vel = vec_from_angle(shot.vel.angle + side, 110)
        shot.destroy()
        self.destroy()


class PowerUp(Sprite, source=sheet, height=30, group="powers"):
    def setup(self):
        self.variant = "energy"


def drop_power(start, end):
    # start and end are (x, y) copies taken at the moment of the shot: the star
    # vanishes and the ship keeps moving. The power-up curves to where the ship was,
    # with a wave on top, and goes straight on until it leaves the screen.
    # The frame goes in the constructor: Scena takes the hitbox and the size from it.
    if chance(0.5):
        power = PowerUp(frame="powerupGreen_shield.png", center=start)
        power.variant = "shield"
    else:
        power = PowerUp(frame="pill_green.png", center=start)
    direction = heading(start, end)
    mx, my = middle_point(start, end)
    detour = vec_from_angle(direction + choice([90, -90]), 100)
    far = vec_from_angle(direction, 1500)
    x, y = end
    track = Track(points=[start, (mx + detour.x, my + detour.y), end, (x + far.x, y + far.y)])
    track.zigzag(amount=16, waves=6)
    power.move_along(track, speed=120)


class Target(Circle, radius=16, visual=Sphere("gold"), group="target"):
    def setup(self):
        self.gold_star = Starburst(center=lambda: self.center, radius=34, color="gold")

    @collide_with("shots")
    def was_hit(self, shot, info):
        canvas.debris_at(self, color="gold", radius=60)
        play_sound("audio/explosion02.ogg", volume=0.6)
        if shot.shooter:
            drop_power(tuple(self.center), tuple(shot.shooter.center))
        shot.destroy()
        self.destroy()

    def on_destroy(self):
        self.gold_star.destroy()


def make_bolt(center):
    # Two balls on the same (upright) figure eight, almost half a lap apart:
    # in the middle of the eight they pass close, at the ends they are far apart.
    track = Track.eight(width=160, height=50, center=center, angle=90)
    ball1 = Circle(center=center, radius=10, group="wall", visual=Metal("gold"))
    ball2 = Circle(center=center, radius=10, group="wall", visual=Metal("gold"))
    ball1.move_along(track, time=6, loops="forever")
    ball2.move_along(track, time=6, loops="forever", phase=0.45)
    bolt = Line(p1=lambda: ball1.center, p2=lambda: ball2.center, line_width=8,
                visual=ElectricBolt("cyan"), group="bolt")
    bolt.ball1 = ball1
    bolt.ball2 = ball2
    return bolt


resolve("shots", "wall", bounce=1.0)
resolve("asteroids", ["wall", "crate", "ships"], bounce=1.0)
resolve("asteroids", "asteroids", bounce=1.0)


@collide("ships", "shots")
def struck(ship, shot, info):
    shot.destroy()
    canvas.hit_at(info, color="orange")
    play_sound("audio/sfx-hit-2.ogg")
    ship.flash(0.1)
    ship.energy -= 10


@collide("ships", "asteroids")
def crashed(ship, asteroid, info):
    canvas.hit_at(info, style="disc", radius=14)
    play_sound("audio/impactPlank_medium_002.ogg", volume=0.5)
    ship.energy -= 2


@collide("shots", "bolt")
def burned(shot, bolt, info):
    canvas.zap_at(info, color="cyan")
    play_sound("audio/fx2.ogg", volume=0.5)
    shot.destroy()


@collide("shots", "crate")
def smashed(shot, crate):
    canvas.burst_at(crate, radius=24)
    canvas.debris_at(crate, color="peru", radius=24)
    play_sound("audio/explosion01.ogg", volume=0.4)
    shot.destroy()
    crate.destroy()


@collide("ships", "powers")
def caught(ship, power):
    if power.variant == "shield":
        ship.shield.charges = 3
        ship.shield.active = True
    else:
        ship.energy = min(100, ship.energy + 40)
    ship.pop()
    play_sound("audio/fx1.ogg")
    power.destroy()


@leave_playfield("shots", "powers")
def gone(thing):
    thing.destroy()


class Choice(Act):
    def setup(self):
        st.blue_ready = False
        st.red_ready = False
        Text(text="DUEL", center=(640, 600), font_size=80)
        self.blues = [Sprite(sheet, frame="playerShip1_blue.png", height=80, center=(230, 360)),
                      Sprite(sheet, frame="playerShip2_blue.png", height=80, center=(430, 360))]
        self.reds = [Sprite(sheet, frame="playerShip1_red.png", height=80, center=(850, 360)),
                          Sprite(sheet, frame="playerShip2_red.png", height=80, center=(1050, 360))]
        Text(text="I", center=(230, 270), font_size=28)
        Text(text="II", center=(430, 270), font_size=28)
        Text(text="I", center=(850, 270), font_size=28)
        Text(text="II", center=(1050, 270), font_size=28)
        Text(text="A / D choose · TAB confirm", center=(330, 180), font_size=20)
        Text(text="LEFT / RIGHT choose · ENTER confirm", center=(950, 180), font_size=20)
        self.blue_notice = Text(text="", center=(330, 130), font_size=24, color="deep sky blue")
        self.red_notice = Text(text="", center=(950, 130), font_size=24, color="tomato")

    def on_update(self, dt):
        if keyp.once("A"):
            st.blue_variant = 1
        if keyp.once("D"):
            st.blue_variant = 2
        if keyp.once("LEFT"):
            st.red_variant = 1
        if keyp.once("RIGHT"):
            st.red_variant = 2
        if keyp.once("TAB"):
            st.blue_ready = True
            self.blue_notice.text = "READY"
        if keyp.once("ENTER"):
            st.red_ready = True
            self.red_notice.text = "READY"

        for i in range(2):
            self.blues[i].alpha = 0.25
            self.reds[i].alpha = 0.25
        self.blues[st.blue_variant - 1].alpha = 1
        self.reds[st.red_variant - 1].alpha = 1

        if st.blue_ready and st.red_ready:
            change_act(Duel)


def make_ship(variant, color, spot, angle):
    # The two types only change the picture: playerShip1 or playerShip2.
    ship = Ship(frame=f"playerShip{variant}_{color}.png", center=spot)
    ship.angle = angle
    return ship


def make_asteroids():
    for item in level.group("asteroid"):
        Asteroid(center=item.center)


class Duel(Act):
    def setup(self):
        for item in level.group("wall"):
            item.make(color="#2b3a55")
        for item in level.group("rock"):
            rock = item.make(group="wall", color="#3d5a80", line_width=6)
            rock.fill = "#1d2d44"
        for item in level.group("bar"):
            bar = item.make(group="wall", visual=Metal())
            bar.rotate_by(360, time=4, loops="forever")
        for item in level.group("crate"):
            item.make(color="peru")
        self.bolts = []
        for item in level.group("bolt"):
            self.bolts.append(make_bolt(item.center))
        group["wall"].mass = STATIC
        group["crate"].mass = STATIC
        make_asteroids()
        Warp(center=HOLE, radius=EDGE, color="violet", spin=0.5)

        self.blue = make_ship(st.blue_variant, "blue", level["blue_start"].center, 0)
        self.blue.rail = level["blue_rail"].make()
        self.blue.controls = LEFT_KEYS
        self.blue.laser = "laserBlue01.png"
        self.red = make_ship(st.red_variant, "red", level["red_start"].center, 180)
        self.red.rail = level["red_rail"].make()
        self.red.controls = RIGHT_KEYS
        self.red.laser = "laserRed01.png"

        self.blue.bar = Rect(top_left=(40, 714), width=300, height=8, color="deep sky blue")
        self.blue.bar["width"] @= lambda: max(self.blue.energy, 0) * 3
        self.red.bar = Rect(top_left=(940, 714), width=300, height=8, color="tomato")
        self.red.bar["width"] @= lambda: max(self.red.energy, 0) * 3

    def on_update(self, dt):
        # The bolt only exists while the two balls are close.
        for bolt in self.bolts:
            bolt.active = distance(bolt.ball1, bolt.ball2) < 90

    @every(8)
    def send_star(self):
        if group["target"].empty:
            y = choice([760, -40])
            entry = (uniform(420, 860), y)
            mid = (uniform(300, 980), 360)
            finish = (uniform(420, 860), 720 - y)
            gold_star = Target(center=entry)
            gold_star.move_along(Track(points=[entry, mid, finish]), speed=60, on_done=gold_star.destroy)

    @every(15)
    def more_asteroids(self):
        if group["asteroids"].empty:
            make_asteroids()

    @when(lambda self: self.blue.energy <= 0 or self.red.energy <= 0)
    def finish(self):
        if self.blue.energy <= 0:
            lost = self.blue
            st.winner = "RED"
        else:
            lost = self.red
            st.winner = "BLUE"
        canvas.explosion_at(lost, amount=1.6)
        canvas.debris_at(lost, color="gray", radius=70)
        canvas.shake(14)
        play_sound("audio/explosion04.ogg")
        lost.destroy()
        self.after(3, lambda: change_act(Victory))


class Victory(Act):
    def setup(self):
        Text(text=f"{st.winner} WINS", center=(640, 420), font_size=64, color="gold")
        Text(text="press SPACE", center=(640, 320), font_size=22)

    def on_update(self, dt):
        if keyp.once("SPACE"):
            change_act(Choice)


run(Choice)
