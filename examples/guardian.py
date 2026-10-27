"""Ring Guardian.

Controls
--------
  SPACE          starts; then shoots (an enemy almost in front, inside AIM,
                 pulls the shot)
  LEFT / RIGHT   the ship flies around the ring
  R              plays again, after the end

Run
---
    python examples/guardian.py
"""

from math import sin
from random import choice, uniform
from scena import *

init(width=1280, height=800, title="Ring Guardian")

CENTER = Vec2(640, 400)
RADIUS = 115        # the middle of the ring
BAND = 16           # the width of the ring
ORBIT = RADIUS + 26 # the ship flies outside the ring, just above its edge
GATE = 600          # how far from the center enemies come out, from many sides
FAR_GATE = 1000     # the farthest a portal opens, from one side
CROSSING = 360      # how far from the center the mines cross the screen
SHIP_LIFE = 16
RING_LIFE = 25
TURN = 160          # degrees per second
SPREAD = 24         # degrees between the ship and each light
COOLDOWN = 0.2      # seconds between two shots
DURATION = 12       # seconds a power lasts
GIFT_DURATION = 25  # seconds a power left at the end of a wave lasts
AIM = 9             # the width of each shot's radar, in degrees
FAN = 5             # degrees between the ship's shot and each light's (TRIPLE)
BLAST = 208         # the radius of a mine's blast
MINE_DAMAGE = 5     # the lives a diving mine takes from the ring or the ship
SHIELD_HITS = 4     # the shots or enemies the shield stops before it breaks
PILL_CHANCE = 0.15  # the chance that a destroyed enemy drops a pill...
PILL_GAP = 20       # ...if the last such pill fell at least this many seconds ago
CLUSTER = 5         # enemies around one side before the next side (many sides)
TITLE_FONT = "fonts/Bungee-Regular.ttf"  # the title, the waves, the end
TEXT_FONT = "fonts/Play-Regular.ttf"     # the story: plain letters read best
HUD_FONT = "fonts/Play-Bold.ttf"         # the numbers on the screen
MUSIC = 0.25         # the music's volume, under the effects (a loud track)

# The sky: clouds that churn slowly and filaments on top. Both turn with
# the camera, like the rest of the world.
ChurningClouds(color="royal blue", color2="dark magenta", alpha=0.7,
               speed=0.25, rotation_response=1)
FilamentField(color="teal", alpha=0.45, rotation_response=1)
bloom = Bloom(intensity=0.6)
Vignette()


# The ring: a disc with the colors of the wheel, a black disc on top (the
# hole) and two edges of light.
ring = Circle(center=CENTER, radius=RADIUS + BAND / 2, group="ring")
ring.fill = Gradient("deep sky blue", "medium purple", "magenta",
                     "deep sky blue", type="sweep")
ring.rotate_by(360, time=40, loops="forever")   # the color wheel turns
Circle(center=CENTER, radius=RADIUS - BAND / 2, color="black")
for r in (RADIUS - BAND / 2, RADIUS + BAND / 2):
    Circle(center=CENTER, radius=r, visual=Halo("cyan", style="line"))


# Fixed marks around, like the hours of a clock: when the camera turns,
# they turn with it and show where.
for hour in range(12):
    size = 6 if hour % 3 == 0 else 3
    Circle(center=CENTER + vec_from_angle(30 * hour, 330), radius=size,
           color=Color("white").with_alpha(0.35))


# The core: the four lights of Arria dance in figure eights that cross in
# the center. Where they meet, the colors add up and the light turns white.
COLORS = ["magenta", "cyan", "gold", "lime"]
LIGHTS = []
for i in range(4):
    eight = Track.eight(width=130, height=45, center=CENTER, angle=45 * i)
    guide = Point(CENTER.x, CENTER.y)
    guide.move_along(eight, time=4 + 1.3 * i, loops="forever")
    LIGHTS.append(GlowSpot(center=lambda guide=guide: guide.center, radius=32,
                           color=COLORS[i]))
core = Orb(center=CENTER, radius=10, color="white", glow=1.4)
tween(core["radius"], 12, time=3, loops="forever", yoyo=True, ease="ease_in_out")


# The core shows the ring's life: the lights dim and the center turns red.
def paint_core():
    strength = st.ring_life / RING_LIFE
    for light in LIGHTS:
        light.amount = 0.2 + 0.8 * strength
    core.color = lerp(Color("white"), Color("orange red"), 1 - strength)


def hurt_ring(damage=1):
    if st.ring_life <= 0:
        return
    st.ring_life = max(0, st.ring_life - damage)
    paint_core()
    ring.flash()
    canvas.shake(2 + 3 * damage)
    # the ring rings: a deeper, louder bell for a heavy blow
    play_sound("audio/impact_bell_heavy_000.ogg", volume=0.4 + 0.12 * damage,
               pitch=1.1 - 0.1 * damage, name="ring")


def new_game():
    st.ship_life = SHIP_LIFE
    st.ring_life = RING_LIFE
    st.score = 0
    st.glow = 0.5       # the glow of the screen that the wave asks for
    st.pill_wait = 0    # seconds before a destroyed enemy may drop a pill
    st.pace = 1         # how fast the enemies of this wave move (1.5 = 50 % faster)
    paint_core()

new_game()


# A point of the ring. The angle never goes back to 0: after three laps it
# is 1080, and everything still works. So the lights that follow the ship
# never take the long way round when it passes from 359 to 360.
def on_ring(angle, r=ORBIT):
    return CENTER + vec_from_angle(angle, r)


# The play area is what the camera shows, plus a margin: a shot that leaves
# the screen goes at once (Game.on_update moves it with the camera). Only
# what has been on the screen leaves it: a portal or a mine that starts
# off the screen comes in safely.
MARGIN = 100

@leave_playfield("shots", "bullets", "pills", "mines")
def gone(thing):
    thing.destroy()


class Shot(Sprite, source="space/laserBlue03.png", height=36, art_angle=90,
           group="shots"):
    def setup(self):
        self.glow = CheapGlow("deep sky blue", radius=8)
        # a shot fired off the screen (the ship below the edge, wave 6)
        # never enters it, so it never leaves it either: it ends in time
        self.after(1.5, self.destroy)
        self.damage = 1
        self.pierce = False

    def make_heavy(self):
        self.damage = 2
        self.pierce = True          # goes through the enemy and on
        self.scale_to(1.5)
        self.glow = CheapGlow("gold", radius=14)

    def on_update(self, dt):
        self.move_by(distance=800 * dt)    # forward, where it points


# The power pills: each color gives a power.
PILLS = {
    "triple": "space/pill_blue.png",
    "rapid": "space/pill_green.png",
    "heavy": "space/pill_yellow.png",
    "shield": "space/pill_red.png",
}

class Pill(Sprite, height=30, group="pills"):
    def setup(self):
        self.glow = CheapGlow("white", radius=10)
        self.move_to(CENTER, speed=50)          # drifts slowly to the ring
        self.rotate_by(360, time=2, loops="forever")


def drop_pill(place, power=None, lasting=DURATION):
    if power is None:
        power = choice(list(PILLS))
    pill = Pill(PILLS[power], center=place)
    pill.power = power
    pill.lasting = lasting


@collide("pills", "ship")
def picked(pill, ship):
    pill.destroy()
    ship.gain(pill.power, pill.lasting)


@collide("pills", "ring")
def missed(pill, ring):
    pill.destroy()              # nobody took it: lost


# The ship is two triangles of the same hue: a long one and a wide, low
# one, half transparent. Hurt, the ship heats up: the hue goes from blue to
# orange through purple and red (the hue wraps: 1.05 is 0.05).
def ship_color(saturation, alpha=1):
    damage = 1 - st.ship_life / SHIP_LIFE
    return Color.from_hsv(0.56 + 0.49 * damage, saturation, 1, alpha)

class Ship(Triangle, group="ship"):
    def setup(self):
        self.bearing = 90       # where the ship is on the ring (and where it points)
        self.reload = 0
        self["color"] @= lambda: ship_color(0.85)
        self.glow = True
        self.wing = Triangle(center=lambda: self, angle=lambda: self.angle,
                             radius=16, base_ratio=1.35)
        self.wing["color"] @= lambda: ship_color(0.45, alpha=0.6)
        # the two lights follow the ship, one on each side, a little late
        self.light_a = self.light_b = self.bearing
        self.lights = [GlowSpot(radius=18, color="aqua"),
                       GlowSpot(radius=18, color="aqua")]
        self.sparks = None
        # the seconds left before each power ends (0 = off)
        self.powers = {"triple": 0, "rapid": 0, "heavy": 0, "shield": 0}
        self.shield = None
        self.shield_hits = 0

    def on_update(self, dt):
        if keyp("LEFT"):
            self.bearing += TURN * dt
        if keyp("RIGHT"):
            self.bearing -= TURN * dt
        self.center = on_ring(self.bearing)
        self.angle = self.bearing
        self.light_a = chase(self.light_a, self.bearing + SPREAD, rate=5)
        self.light_b = chase(self.light_b, self.bearing - SPREAD, rate=5)
        self.lights[0].center = on_ring(self.light_a)
        self.lights[1].center = on_ring(self.light_b)

        for power in self.powers:
            self.powers[power] = max(0, self.powers[power] - dt)
        if self.shield and self.powers["shield"] == 0:
            self.drop_shield()

        self.reload -= dt
        if keyp("SPACE") and self.reload <= 0:
            self.shoot(on_ring(self.bearing, ORBIT + 34), self.bearing)
            if self.powers["triple"] > 0:
                # the lights shoot almost parallel to the ship, a little apart
                self.shoot(on_ring(self.light_a), self.bearing + FAN)
                self.shoot(on_ring(self.light_b), self.bearing - FAN)
            if self.powers["rapid"] > 0:
                self.reload = COOLDOWN / 2
            else:
                self.reload = COOLDOWN
            # one sound a volley; a new one cuts the last (name=)
            if self.powers["heavy"] > 0:
                play_sound("audio/laser-big.ogg", volume=0.3, pitch=1.8, name="shot")
            else:
                play_sound("audio/laser7.ogg", volume=0.3, name="shot")

    def shoot(self, start, angle):
        # the aim helps: a narrow radar in front of the shot (4.5 degrees to
        # each side); if it finds an enemy, the shot goes right at the nearest
        targets = collision.query_sector(start, angle=angle, radius=800,
                                         spread=AIM, group="enemies")
        if targets:
            target = min(targets, key=lambda enemy: distance(start, enemy))
            angle = heading(start, target)
        shot = Shot(center=start, angle=angle)
        if self.powers["heavy"] > 0:
            shot.make_heavy()

    def gain(self, power, lasting=DURATION):
        self.powers[power] = lasting
        self.pop(scale=1.4)
        play_sound("audio/coin.ogg", volume=0.6)
        if power == "shield":
            # the shield is a portal around the ring and the ship
            self.shield_hits = SHIELD_HITS
            if self.shield is None:
                self.shield = Portal(center=CENTER, radius=ORBIT + 55,
                                     color="orange red", group="shield")
            self.shield.amount = 1.2

    # Each hit on the shield dims it; the last one breaks it.
    def shield_hit(self, hits=1):
        self.shield_hits -= hits
        if self.shield_hits > 0:
            self.shield.amount = 1.2 * self.shield_hits / SHIELD_HITS
            play_sound("audio/impact_generic_light_003.ogg", volume=0.6, pitch=0.7)
            return
        canvas.ripple_at(CENTER, amount=0.4, radius=ORBIT + 120)
        play_sound("audio/projectile-hit.ogg", volume=0.8, pitch=0.6)
        self.powers["shield"] = 0
        self.drop_shield()

    def drop_shield(self):
        self.shield.destroy()
        self.shield = None

    def hurt(self, damage=1):
        if st.ship_life <= 0:
            return
        st.ship_life = max(0, st.ship_life - damage)
        self.blink(0.3)
        canvas.shake(5 + 3 * damage)
        play_sound("audio/impact_punch_heavy_001.ogg", volume=0.4 + 0.12 * damage)

    @when(lambda self: st.ship_life <= 3)
    def damaged(self):
        self.sparks = Sparks(center=lambda: self.center, radius=18, rate=60,
                             amount=1.5, color="orange")

    @when(lambda self: st.ship_life <= 0)
    def destroyed(self):
        canvas.explosion_at(self, amount=1.4)
        play_sound("audio/explosion09.ogg")
        self.destroy()

    def on_destroy(self):
        self.wing.destroy()
        for light in self.lights:
            light.destroy()
        if self.sparks:
            self.sparks.destroy()
        if self.shield:
            self.shield.destroy()


# The enemy shots ("bullets"). Each enemy shoots its own way.
class Bullet(Sprite, source="space/laserRed01.png", height=26, art_angle=90,
             group="bullets"):
    def setup(self):
        self.after(8, self.destroy)         # as the Shot: one fired off the screen

    def on_update(self, dt):
        self.move_by(distance=210 * dt)


class Bolt(Sprite, source="space/laserGreen02.png", height=34, art_angle=90,
           group="bullets"):
    def setup(self):
        self.after(8, self.destroy)

    def on_update(self, dt):
        self.move_by(distance=310 * dt)


@collide("bullets", "ship")
def bullet_on_ship(bullet, ship):
    bullet.destroy()
    canvas.hit_at(bullet, color="orange")
    ship.hurt()


@collide("bullets", "ring")
def bullet_on_ring(bullet, ring):
    bullet.destroy()
    canvas.zap_at(bullet, color="cyan", radius=18)
    hurt_ring()


# A shot that meets an enemy shot: both go, in a zap (a HEAVY shot goes on).
@collide("shots", "bullets")
def zapped(shot, bullet):
    bullet.destroy()
    if not shot.pierce:
        shot.destroy()
    canvas.zap_at(bullet, color="white", radius=30)
    play_sound("audio/projectile-hit.ogg", volume=0.4, pitch=2, name="zap")


# The rules of every enemy. Each enemy has its own life, its own worth (points) and
# its own way to blow up (blow_up); the rest is the same for all.
@collide("shots", ["enemies", "mines"])
def hit(shot, enemy):
    if not shot.pierce:
        shot.destroy()
    enemy.life -= shot.damage
    if enemy.life <= 0:
        shoot_down(enemy)
    else:
        canvas.hit_at(shot, color="white")
        play_sound("audio/sfx-hit-2.ogg", volume=0.4, name="hit")
        enemy.flash()
        enemy.scale_by(0.92)        # each shot shrinks it a little


def shoot_down(enemy):
    st.score += enemy.worth
    bloom.intensity += 0.25         # each explosion lights up the screen a moment
    if st.pill_wait <= 0 and chance(PILL_CHANCE):
        drop_pill(enemy.center)
        st.pill_wait = PILL_GAP
    enemy.blow_up()


# The shield stops SHIELD_HITS shots or enemies, then breaks. A diving
# mine breaks it at once.
@collide("bullets", "shield")
def bullet_on_shield(bullet, shield):
    bullet.destroy()
    canvas.hit_at(bullet, style="disc", color="orange")
    group["ship"].nearest(shield).shield_hit()


@collide("enemies", "shield")
def enemy_on_shield(enemy, shield):
    shoot_down(enemy)
    group["ship"].nearest(shield).shield_hit()


@collide("mines", "shield")
def mine_on_shield(mine, shield):
    mine.blow_up()
    group["ship"].nearest(shield).shield_hit(SHIELD_HITS)


@collide("enemies", "ring")
def invaded(enemy, ring):
    hurt_ring()
    enemy.blow_up()


@collide("enemies", "ship")
def rammed(enemy, ship):
    ship.hurt()
    enemy.blow_up()


@collide("mines", "ring")
def mine_on_ring(mine, ring):
    mine.blow_up()
    hurt_ring(MINE_DAMAGE)


@collide("mines", "ship")
def mine_on_ship(mine, ship):
    mine.blow_up()
    ship.hurt(MINE_DAMAGE)


# Arrow: three translucent triangles in orange and red. The middle one is
# the body; the other two turn out to each side of it, the same on both, and
# the angle between them breathes. It flies straight at the ring, shoots once
# on the way and throws itself on the ring.
class Arrow(Triangle, radius=24, base_ratio=0.6, group="enemies"):
    life = 1
    worth = 10

    def setup(self):
        self.angle = heading(self, CENTER)
        self.pace = st.pace
        self.color = Color("orange red").with_alpha(0.8)
        self.line = None
        self.beat = uniform(0, 6.3)          # each arrow breathes on its own beat
        self.wings = []
        for side in (1, -1):
            # behind the body and to one side, turned out by spread()
            wing = Triangle(center=lambda side=side: self.center + vec_from_angle(
                                self.angle + side * 150, 12),
                            angle=lambda side=side: self.angle + side * self.spread(),
                            radius=20, base_ratio=0.6)
            wing.color = Color("dark orange").with_alpha(0.6)
            wing.line = None
            self.wings.append(wing)
        if chance(0.7):                  # not every arrow shoots
            self.after(uniform(1.2, 2), self.shoot)

    # the angle between the body and each wing: 28 degrees, give or take 10
    def spread(self):
        return 28 + 10 * sin(4 * clock.time + self.beat)

    def on_update(self, dt):
        self.move_by(distance=110 * self.pace * dt)

    def shoot(self):
        Bullet(center=self.center, angle=self.angle)
        play_sound("audio/sfx_laser2.ogg", volume=0.15, name="enemy shot")

    def blow_up(self):
        canvas.burst_at(self, radius=30)
        play_sound("audio/explosion07.ogg", volume=0.35, pitch=1.5, name="pop")
        self.destroy()

    def on_destroy(self):
        for wing in self.wings:
            wing.destroy()


# Mandala: two half transparent pentagons, turning against each other, with
# a light behind. It stops away from the ring and shoots five bullets around.
class Mandala(RegularPolygon, n=5, radius=30, group="enemies"):
    life = 3
    worth = 30

    def setup(self):
        self.color = Color("orchid").with_alpha(0.4)
        self.pair = RegularPolygon(n=5, radius=30, center=lambda: self,
                                   angle=lambda: 36 - self.angle)
        self.pair.color = Color("deep sky blue").with_alpha(0.4)
        self.light = GlowSpot(center=lambda: self.center, radius=46,
                              color="medium purple", amount=0.4)
        side = heading(CENTER, self) + uniform(-30, 30)   # each in its own place
        self.pace = st.pace
        self.move_to(on_ring(side, 420), time=3 / self.pace, ease="ease_out")
        self.every(2.4, self.shoot)
        self.after(12, lambda: self.move_to(CENTER, speed=40 * self.pace))   # then it comes down

    def on_update(self, dt):
        self.rotate_by(50 * dt)

    def shoot(self):
        for i in range(5):
            Bullet(center=self.center, angle=self.angle + 72 * i)
        play_sound("audio/sfx_laser2.ogg", volume=0.25, pitch=0.7, name="enemy shot")

    def blow_up(self):
        canvas.burst_at(self, radius=60, amount=6)
        canvas.fireworks_at(self, color="violet", radius=80)
        play_sound("audio/explosion02.ogg", volume=0.6)
        self.destroy()

    def on_destroy(self):
        self.pair.destroy()
        self.light.destroy()


# Crystal: a jelly hexagon with a triangle inside. Slow and tough, and it
# aims at the ship.
class Crystal(RegularPolygon, n=6, radius=30, group="enemies"):
    life = 5
    worth = 50

    def setup(self):
        self.visual = Gel("turquoise")
        self.inside = Triangle(center=lambda: self, angle=lambda: -self.angle,
                               radius=13, color="aquamarine")
        self.move_to(CENTER, speed=36 * st.pace)
        self.every(2.0, self.shoot)

    def on_update(self, dt):
        self.rotate_by(30 * dt)

    def shoot(self):
        ship = group["ship"].nearest(self)
        if ship:
            Bolt(center=self.center, angle=heading(self, ship))
            play_sound("audio/sfx_laser1.ogg", volume=0.25, name="enemy shot")

    def blow_up(self):
        canvas.debris_at(self, color="turquoise", radius=60)
        canvas.burst_at(self, radius=60, amount=6)
        play_sound("audio/explosion03.ogg", volume=0.6, pitch=1.3)
        self.destroy()

    def on_destroy(self):
        self.inside.destroy()


# Mine: a circle with rings that pulse slowly. A shot in it makes a big blast
# that destroys the enemies around; the other mines near it blow up too, in a
# chain. It is in the "mines" group, not in "enemies": the wave does not wait
# for it.
class Mine(Circle, radius=20, color="dark red", group="mines"):
    life = 1
    worth = 20

    def setup(self):
        self.visual = Halo("orange red", style="pulse", rings=2, speed=0.5)

    def blow_up(self):
        place = (self.center.x, self.center.y)
        self.destroy()      # gone first, so the chain does not come back to it
        canvas.burst_at(place, radius=BLAST, amount=6)
        canvas.ripple_at(place, amount=0.6, radius=2 * BLAST)
        # one deep boom for a whole chain (name=)
        play_sound("audio/explosion01.ogg", pitch=0.7, name="blast")
        for neighbour in collision.query_circle(place, radius=BLAST, group="enemies"):
            if neighbour.active:        # a mine of the chain may have taken it
                st.score += neighbour.worth
                canvas.debris_at(neighbour, color="silver", radius=50)
                neighbour.destroy()
        for mine in collision.query_circle(place, radius=BLAST, group="mines"):
            if mine.active:
                st.score += mine.worth
                mine.blow_up()


# A diving mine: darker, with a fast pulse, and it heads for the ring.
class DivingMine(Mine):
    worth = 40

    def setup(self):
        self.color = "maroon"
        self.visual = Halo("red", style="pulse", rings=3, speed=1.6)
        self.move_to(CENTER, speed=45)


# The side of the attack: a wave says one angle, a list of angles, or None
# (any side).
def pick_side(side):
    if side is None:
        return uniform(0, 360)
    if isinstance(side, list):
        return choice(side)
    return side


# A mine crosses the screen from one end to the other, CROSSING from the
# center, facing the side of the attack: it passes in front of the ring, far
# from the group that comes. With a time, it is right in front of the ring
# that many seconds later (it flies faster or slower to get there).
def cross_mine(side, time=None):
    side = pick_side(side)
    way = choice([90, -90])
    front = on_ring(side, CROSSING)
    speed = 85 if time is None else 900 / time
    mine = Mine(center=front + vec_from_angle(side + way, 900))
    mine.move_to(front + vec_from_angle(side - way, 900), speed=speed,
                 on_done=mine.destroy)


def dive_mine(side, gate):
    DivingMine(center=on_ring(pick_side(side) + uniform(-20, 20), 0.9 * gate))


# The side of each cluster of a wave. One side: always that one. A list: one
# side after the other. None: anywhere, but away from the last cluster.
def next_side(side, cluster, last):
    if side is None:
        return last + uniform(100, 260)
    if isinstance(side, list):
        return side[cluster % len(side)]
    return side


def arrive(kind, side, gate, spread):
    kind(center=on_ring(side + uniform(-spread, spread), gate))


# How close the camera shows the ring in each wave (the zoom): far to see
# every side, close for a big ring.
VIEWS = {"far": 0.55, "normal": 0.75, "close": 1.05}

# The waves, one after the other.
#   side     where they come from (an angle on the ring); a list of angles;
#            None = from anywhere (in clusters, see CLUSTER)
#   kinds    the enemies, drawn one by one (repeat a kind to make it commoner)
#   count    how many enemies; every: the seconds between one and the next
#   cluster  (if any) how many come around each side, when there are many
#   view     far, normal or close (VIEWS)
#   ring     (if any) "edge": from one side, only the top half of the ring
#            shows on the screen
#   glow     the strength of the Bloom
#   end      "clear" waits for every enemy to die; a number waits that many
#            seconds (or for all to die)
#   turn     (if any) the camera turns the side of the attack up
#   mines    (if any) how many mines cross the screen during the wave
#   ambush   (if any) a mine crosses right in front of the ring this many
#            seconds after the first enemy comes out, in the wave's way
#   divers   (if any) how many mines dive at the ring
#   pace     (if any) how fast the enemies move: 1.5 is 50 % faster
#   gifts    (if any) the pills left at the end, for the next wave (they
#            last GIFT_DURATION)
#   party    (if any) gold embers when the wave is won
WAVES = [
    dict(name="Arrows from the north", side=90, kinds=[Arrow], count=16,
         every=0.45, view="close", glow=0.5, end="clear"),
    dict(name="Mandalas", side=210, kinds=[Mandala], count=8, every=0.9,
         pace=1.5, view="normal", glow=0.9, end=10, mines=2),
    dict(name="Southern mix", side=270, kinds=[Arrow, Arrow, Crystal], count=18,
         every=0.45, view="normal", glow=0.6, end="clear",
         gifts=["triple", "shield"]),
    dict(name="Siege", side=None, kinds=[Arrow], count=30, every=0.45,
         view="far", glow=0.8, end="clear", mines=3, divers=1,
         gifts=["heavy", "triple"]),
    dict(name="Polygons", side=[45, 165, 285], kinds=[Mandala, Crystal],
         count=20, every=0.6, cluster=2, pace=1.5, view="far", glow=0.7,
         end="clear", divers=1),
    dict(name="Swarm", side=330, kinds=[Arrow], count=50, every=0.12,
         view="normal", ring="edge", glow=1.0, end="clear", turn=True, mines=1,
         ambush=8, gifts=["rapid", "heavy"], party=True),
    dict(name="Crown", side=None, kinds=[Mandala, Crystal], count=10, every=0.7,
         cluster=3, view="far", glow=1.0, end=12, mines=3, divers=1),
    dict(name="East", side=0, kinds=[Arrow, Arrow, Mandala, Crystal], count=20,
         every=0.45, view="close", glow=1.2, end="clear", turn=True, divers=1,
         gifts=["triple", "shield"]),
    dict(name="Storm", side=None, kinds=[Arrow, Arrow, Arrow, Mandala, Crystal],
         count=45, every=0.35, view="far", glow=1.2, end="clear", mines=4,
         divers=2),
]


# The lettering: the game's font, letters in a gradient with the colors of
# the ring and a dark outline.
def lettering(letters, color="cyan", color2="magenta"):
    letters.fill = Gradient(color, color2, angle=-90)
    letters.line = "black"
    return letters


def announce(text):
    sign = lettering(Text(text, center=(640, 720), font=TITLE_FONT, font_size=36,
                          layer="ui"))
    sign.after(2, lambda: sign.fade_out(1, on_done=sign.destroy))
    play_sound("audio/fx2.ogg", volume=0.5)


# The victory: the four lights of Arria flare into a four-point star. Ten
# small hexagons, in the colors of the aurora, open over the ring, each turned
# a little more than the one inside it; then they fly away up and to the
# right of the screen, faster and faster, each one a moment behind the one inside it, so
# the bundle stretches into a tail. Two lights run around the ring (a window
# of a circle track, from begin to end, that moves).
AURORA = Colormap.from_preset("aurora")

def celebrate():
    start = clock.time
    away = 55 - canvas.rotation          # up and to the right on the screen

    def since():                         # seconds since the ring was saved
        return clock.time - start

    def flown(t):                        # how far the bundle is, t seconds in
        return 0 if t < 2 else 280 * (t - 2) ** 2

    star = Starburst(center=CENTER, radius=10, points=4, color="gold", amount=0.6)
    tween(star["radius"], 170, time=2.5, ease="ease_out")
    for i in range(10):
        hexagon = RegularPolygon(n=6, line_width=3)
        hexagon.fill = None
        hexagon.line = AURORA.get_color(i / 9)
        hexagon["radius"] @= lambda i=i: (40 + 14 * i) * min(1, since() / 1.5)
        hexagon["angle"] @= lambda i=i: 40 * since() + 9 * i
        hexagon["center"] @= lambda i=i: CENTER + vec_from_angle(
            away, flown(since() - 0.08 * i))
    for color, offset in (("gold", 0), ("dark orange", 0.5)):
        glint = Track.circle(center=CENTER, radius=ORBIT + 45, color=color, line_width=5)
        glint.glow = CheapGlow(color, radius=12)
        glint["begin"] @= lambda offset=offset: (offset + 0.4 * since()) % 1
        glint["end"] @= lambda offset=offset: (offset + 0.4 * since() + 0.2) % 1


# The defeat: a fireball swells in the ring, with sparks in its heart; the
# ring burns where the ship was and on two sides, the flames leaning out (the
# two sides come closer to the ship when the ring is half off the screen).
def burn(bearing, edge):
    ball = Sunburst(center=CENTER, radius=20, color="orange red")
    tween(ball["radius"], RADIUS, time=1.5, ease="ease_out")
    Sparks(center=CENTER, radius=90, rate=90, amount=1.5, color="gold")
    spread = 65 if edge else 120
    for side in (0, -spread, spread):
        Fire(center=on_ring(bearing + side, RADIUS), style="blaze", width=60,
             length=140, angle=bearing + side)


# The portal a cluster comes out of, facing the ring.
def open_portal(side, gate):
    return Portal(center=on_ring(side, gate), radius=120, tilt=60,
                  angle=side + 90, color="magenta", amount=0.8)


# The pills a wave leaves behind: they come down on both sides of the ship.
def leave_gifts(powers, bearing):
    for i, power in enumerate(powers):
        offset = 30 * (2 * i - len(powers) + 1)
        drop_pill(on_ring(bearing + offset, 320), power, GIFT_DURATION)


STORY = """You are Captain Arcos, leader of Arr's starfleet.
The forces of the evil General Zorg are attacking
from the Delta dimension. Your ship is the guardian
of the four lights of Arria. They must be protected
at all costs, because they are lights that shine
and your ship is in front of them.
Your mission is clear: shoot everything that moves."""

LETTERS = 45        # letters a second, as the story is typed


# Before the first game: the story, typed under the title, with the four
# lights of Arria low on the screen. Two sparks of light run around the
# frame (a window of the track, from begin to end, that moves).
class Intro(Act):
    def setup(self):
        canvas.zoom_to(0.9)
        canvas.pan_to(CENTER + Vec2(0, 290))     # the ring low on the screen
        play_sound("music/battle_theme_b.ogg", volume=0.35, loops="forever", name="music")
        StarFly(color="light cyan", speed=0.4, density=0.6, alpha=0.6)
        title = Text("RING GUARDIAN", center=(640, 728), font=TITLE_FONT, font_size=60,
                     layer="ui")
        lettering(title, "gold", "orange red")
        title.line_width = 3
        title.glow = Glow("orange red")
        title.dissolve_in(2)
        # plain white: an outline thickens small letters and fills their
        # holes, and the title already wears the gradient
        self.story = Text("", top_left=(345, 655), font=TEXT_FONT, font_size=26,
                          color="white")
        self.letters = 0
        for color, start in (("gold", 0), ("dark orange", 0.5)):
            frame = Track(points=[(200, 680), (1080, 680), (1080, 425), (200, 425)],
                          closed=True, smooth=0, layer="ui", color=color, line_width=3)
            frame.glow = CheapGlow(color, radius=10)
            frame["begin"] @= lambda start=start: (start + clock.time * 0.12) % 1
            frame["end"] @= lambda start=start: (start + clock.time * 0.12 + 0.15) % 1
        self.prompt = Text("Press SPACE to start. Then keep pressing SPACE\n"
                           "to shoot everything that moves.", center=(640, 370),
                           font=TEXT_FONT, font_size=22, align="center", layer="ui",
                           color="gold")
        # it blinks, once the story is all typed
        self.prompt["visible"] @= lambda: (self.letters == len(STORY)
                                           and clock.time % 1.2 < 0.85)

    def on_update(self, dt):
        self.letters = min(len(STORY), self.letters + LETTERS * dt)
        shown = STORY[:int(self.letters)]
        if self.story.text != shown:
            self.story.text = shown
        if keyp.once("SPACE"):
            change_act(Game)


class Game(Act):
    def setup(self):
        canvas.zoom_to(0.75)
        self.turn = 0           # the camera's turn, once its tween is over
        self.ship = Ship(radius=28, base_ratio=0.55)
        self.board = lettering(Text("", top_left=(24, 784), font=HUD_FONT,
                                    font_size=24))
        self.board["text"] @= lambda: (
            f"SHIP {st.ship_life}     RING {st.ring_life}     SCORE {st.score}")
        self.panel = lettering(Text("", top_right=(1256, 784), font=HUD_FONT,
                                    font_size=24), "gold", "orange red")
        self.over = False
        self.edge = False       # the ring half off the screen
        self.music = play_sound("music/battle_theme_a.ogg", volume=MUSIC,
                                loops="forever", crossfade=1.5, name="music")
        self.waves = self.run_task(self.director)

    # The camera for a wave. From one side, the ring goes toward the far side
    # of the screen, all of it in view (or only its top half, on an "edge"
    # wave), and the portal to the near edge. Otherwise the ring stays in the
    # middle. Returns how far from the center the enemies come out.
    def frame(self, wave):
        zoom = VIEWS[wave["view"]]
        side = wave["side"]
        canvas.zoom_to(zoom, time=2, ease="ease_in_out")
        if side is None or isinstance(side, list):
            canvas.pan_to(CENTER, time=2, ease="ease_in_out")
            return GATE
        # on the screen, the side's angle includes the camera's turn
        way = vec_from_angle(side + self.turn, 1)
        edge = min(640 / max(abs(way.x), 0.01), 400 / max(abs(way.y), 0.01))
        if wave.get("ring") == "edge":
            shift = edge
        else:
            shift = min(0.6 * edge, edge - (ORBIT + 50) * zoom)
        canvas.pan_to(on_ring(side, shift / zoom), time=2, ease="ease_in_out")
        return min((edge + shift) / zoom - 60, FAR_GATE)

    # The director: tells the story of the game, one wave after the other.
    async def director(self):
        await wait(1.5)
        for number, wave in enumerate(WAVES):
            side = wave["side"]
            one_side = not (side is None or isinstance(side, list))
            announce(f"WAVE {number + 1}   {wave['name']}")
            st.glow = wave["glow"]
            st.pace = wave.get("pace", 1)
            self.edge = wave.get("ring") == "edge"
            if wave.get("turn"):
                self.turn = 90 - side
                canvas.rotate_to(self.turn, time=2, ease="ease_in_out")
            gate = self.frame(wave)
            if wave.get("ambush"):
                # the enemies start in 2 seconds: the mine is in front ambush later
                cross_mine(side, 2 + wave["ambush"])
            await wait(2)

            if one_side:
                # a wind blows from the side of the attack to the ring (on the
                # screen, the angle includes the camera's turn)
                wind = WindStreaks(angle=side + 180 + self.turn,
                                   density=0.9, alpha=0.6)
                self.after(2.5, wind.remove)
            for i in range(wave.get("mines", 0)):
                self.after(1 + 3 * i, lambda: cross_mine(side))
            for i in range(wave.get("divers", 0)):
                self.after(4 + 6 * i, lambda: dive_mine(side, gate))
            # from one side, the whole wave is one cluster
            cluster = wave["count"] if one_side else wave.get("cluster", CLUSTER)
            aim = uniform(0, 360)
            portal = None
            for i in range(wave["count"]):
                if i % cluster == 0:        # a new cluster: a new side, a new portal
                    aim = next_side(side, i // cluster, aim)
                    if portal:
                        self.after(1, portal.destroy)
                    portal = open_portal(aim, gate)
                arrive(choice(wave["kinds"]), aim, gate, 15 if one_side else 30)
                await wait(wave["every"])
            self.after(1, portal.destroy)

            if wave["end"] == "clear":
                await until_empty("enemies")
                await wait(1.5)
            else:
                await race(wait(wave["end"]), until_empty("enemies"))
            if wave.get("party"):
                embers = Embers(color="gold", density=1.2)    # a big wave won
                self.after(3, embers.remove)
            if wave.get("gifts"):
                leave_gifts(wave["gifts"], self.ship.bearing)
                await wait(2)
        await until_empty("enemies")
        canvas.fireworks_at(CENTER, color="cyan", radius=160)
        celebrate()
        self.music.fade_out(1.5)
        play_sound("audio/victory.mp3")
        self.finish("THE RING IS SAFE")

    def on_update(self, dt):
        canvas.playfield.set(canvas.game_view.outset(MARGIN))
        # the glow of the screen goes slowly back to what the wave asks for
        bloom.intensity = chase(bloom.intensity, st.glow, rate=1.5)
        st.pill_wait = max(0, st.pill_wait - dt)
        # the powers that are on, in the corner of the screen
        on = [power.upper() for power, time_left in self.ship.powers.items()
              if time_left > 0 and st.ship_life > 0]
        self.panel.text = "   ".join(on)
        if self.over and keyp.once("R"):
            new_game()
            change_act(Game)        # straight to the game: the story was told

    @when(lambda self: st.ring_life <= 0)
    def ring_fell(self):
        canvas.explosion_at(CENTER, amount=2.5, flash=True)
        play_sound("audio/explosion01.ogg", pitch=0.5)

    @when(lambda self: st.ship_life <= 0 or st.ring_life <= 0)
    def lost(self):
        self.waves.cancel()
        burn(self.ship.bearing, self.edge)
        self.music.fade_out(3)
        self.finish("GAME OVER")

    def finish(self, title):
        self.over = True
        self.after(1.5, lambda: lettering(Text(title + "\nPress R to play again",
                                               center=(640, 660), font=TITLE_FONT,
                                               font_size=44, layer="ui")))

run(Intro)
