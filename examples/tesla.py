"""Tesla.

An electric garden at night, in the rain. Two Tesla coils feed a small
street of houses through sagging cables. A storm comes, builds, peaks
and goes away at dawn; then the night starts again.

What you are looking at:
  - power runs along the cables as a buzzing light; when it reaches a
    house, the house lights up;
  - the city behind lights one more window for each bit of charge in the
    grid, and the fields around the coils grow brighter;
  - lightning strikes the tallest thing near where it falls: a coil, a
    lightning rod or a house. A coil or a rod feeds the grid; a house
    burns out and stays dark for a while;
  - the last strikes linger as afterimages before they dissolve.

Things to try
-------------
  Drag a rod next to a house   the strikes go to the rod: the house is safe
  Drag both rods away          watch the houses burn
  Click anywhere               the nearest coil discharges there
  Press C                      the control room: the same night on an old monitor

Controls
--------
  DRAG        the lightning rods (they slide along the ground)
  CLICK       a discharge from the nearest coil
  C           control-room view on / off
  SPACE       skip to the next part of the night

Use
---
    python examples/tesla.py
"""

from random import uniform, randint, choice
from scena import *

init(width=1280, height=720, title="Tesla")

GROUND = 70             # the top of the ground
LEFT = -120             # the garden is a little wider than the window:
RIGHT = 1420            # the camera leans in and turns over it
CLOUD = 820             # where lightning starts (above the window)
LIT = (1, 0.78, 0.42)   # the warm light of a window
COPPER = (0.72, 0.40, 0.20)
SPARK = (0.55, 0.80, 1)

# the parts of the night, and how long each one lasts
PARTS = {"calm": 14, "storm": 14, "peak": 11, "dawn": 13}

st.charge = 0.3         # the grid: 0 empty … 1 full
st.level = 6            # the charge in steps of 5%: the city and the HUD follow it
st.storm = 0            # 0 clear sky … 1 the worst of the storm
st.dawn = 0             # 0 night … 1 morning
st.part = "calm"
st.left = PARTS["calm"]     # seconds until the next part
st.zoom = 1             # the camera's zoom for this part (strikes punch it and come back)
st.lit = 0              # how many houses have light
st.punching = False     # a big strike is shaking the camera

# ---------------------------------------------------------------- the sky

# Almost everything is on screen all the time, so skip the per-object
# "is it visible?" test the engine would do every frame.
canvas.cull_offscreen = False

SkyGradient(top=(0.01, 0.01, 0.04), middle=(0.03, 0.04, 0.10), bottom=(0.08, 0.07, 0.16))
stars = Stars(density=0.6, twinkle=0.5)
clouds = ChurningClouds(color=(0.20, 0.22, 0.42), color2=(0.45, 0.30, 0.55), speed=0.25)

# the glow of the morning: a warm band over the horizon, screened on the sky
morning = Rect(p1=(LEFT - 300, GROUND), p2=(RIGHT + 300, 760),
               color=Gradient((1, 0.55, 0.30), (0.35, 0.20, 0.45), (0.02, 0.02, 0.06), angle=90))
morning.blend = "screen"
morning.line = None
morning.set_alpha(0)

# the sun of the dawn waits below the ground all night
sun = Circle(center=(1050, -120), radius=40, color=(1, 0.82, 0.55))
sun_glow = GlowSpot(center=(1050, -120), radius=160, color=(1, 0.6, 0.3), amount=0.9)
sun_glow["center"] @= lambda: sun.center

# ---------------------------------------------------------------- the city

# The far city: dark blocks, a little see-through so the storm shows
# behind them. Their windows light one by one as the grid charges.
city_windows = []
x = LEFT - 300
while x < RIGHT + 300:
    w = uniform(50, 110)
    h = uniform(90, 250)
    block = Rect(p1=(x, GROUND), p2=(x + w, GROUND + h), color=(0.07, 0.07, 0.12, 0.9))
    block.line = None
    for i in range(int(h // 90)):
        city_windows.append((x + uniform(10, w - 10), GROUND + 35 + i * 80))
    x += w + uniform(4, 30)
# each window needs a little more charge than the last to light
step = 0
for spot in city_windows:
    step = step % 20 + 1 + randint(0, 3)
    win = Rect(center=spot, width=5, height=8, color=LIT)
    win["visible"] @= lambda n=step: st.level >= n

street = Rect(p1=(LEFT - 300, -300), p2=(RIGHT + 300, GROUND), color=(0.025, 0.03, 0.05))
street.line = None
# at dawn the wet street catches the warm sky
street["color"] @= lambda: (0.025 + 0.3 * st.dawn, 0.03 + 0.16 * st.dawn, 0.05 + 0.1 * st.dawn)
# a wet shine along the street
Rect(p1=(LEFT - 300, GROUND - 3), p2=(RIGHT + 300, GROUND), color=(0.25, 0.3, 0.45))

# ---------------------------------------------------------------- morning shadows

shadows = []


def cast_shadow(thing, half):
    """A long shadow on the street, away from the rising sun.

    Multiplied, it darkens whatever street colour is under it; it is
    white (no change) at night and grows dark as the dawn comes."""
    shade = Polygon(points=[
        lambda: (thing.center.x - half, GROUND),
        lambda: (thing.center.x + half, GROUND),
        lambda: (thing.center.x + half - thing.height * 160 / (sun.center.y + 260), GROUND - 50),
        lambda: (thing.center.x - half - thing.height * 160 / (sun.center.y + 260), GROUND - 50)])
    shade.line = None
    shade["fill"] @= lambda: (1 - 0.7 * st.dawn, 1 - 0.75 * st.dawn, 1 - 0.65 * st.dawn)
    shade.blend = "multiply"
    shade.visible = False
    shadows.append(shade)


# ---------------------------------------------------------------- the coils


class Coil(Rect):
    """A Tesla coil: copper wound up a column, under a metal ring."""

    def setup(self):
        self.color = (0.10, 0.10, 0.14)
        self.line = None
        bottom = self.bottom_center
        base = Polygon(points=[(bottom.x - 60, GROUND), (bottom.x + 60, GROUND),
                        (bottom.x + 36, GROUND + 26), (bottom.x - 36, GROUND + 26)],
                       color=(0.16, 0.16, 0.21))
        base.line = None
        # insulator cups, one on top of the other
        for i in range(3):
            Concave(center=(bottom.x, GROUND + 34 + i * 13), width=44 - i * 6, height=12,
                    scoop="top_center", color=(0.45, 0.5, 0.6))
        # the winding: one copper wire zigzagging up the column
        winding = Track(points=[(bottom.x, bottom.y + 10), self.top_center + (0, -6)],
                        smooth=0, color=COPPER, line_width=2)
        winding.zigzag(amount=self.width / 2 + 5, waves=self.height / 7)
        self.ring = Ellipse(center=self.top_center + (0, 16), width=self.width * 3.4,
                            height=self.width * 0.9, color=(0.75, 0.78, 0.85))
        self.ring.visual = Metal()
        # the field around the ring: brighter when the grid is full
        field = Circle(center=self.ring.center, radius=self.width * 2.1, color=SPARK)
        field.visual = ElectricField(amount=4, speed=0.8)
        field.blend = "add"
        field["color"] @= lambda: (0.05 + 0.15 * st.level / 20,
                                   0.10 + 0.25 * st.level / 20,
                                   0.25 + 0.40 * st.level / 20)
        cast_shadow(self, 24)

    def tip(self):
        x, y = self.ring.center     # a plain (x, y): a Point would link the cables to it
        return (x, y)


big = Coil(center=(150, GROUND + 70 + 130), width=34, height=260)
small = Coil(center=(640, GROUND + 70 + 85), width=26, height=170)
coils = [big, small]

# ---------------------------------------------------------------- the houses


class House(Rect):
    """A small house; its windows light when power reaches it."""

    def setup(self):
        self.color = (0.09, 0.09, 0.13)
        self.line = None
        self.dark = False       # burned by lightning: no light for a while
        self.lit = False
        left = self.top_left
        right = self.top_right
        self.roof = Polygon(points=[(left.x - 10, left.y), (right.x + 10, right.y),
                                    (self.center.x, left.y + 46)], color=(0.15, 0.11, 0.14))
        self.roof.line = None
        self.windows = []
        for dx in (-0.25, 0.25):
            for dy in (-0.15, 0.2):
                win = Rect(center=self.center + (dx * self.width, dy * self.height),
                           width=15, height=17, color=LIT)
                win.visible = False
                self.windows.append(win)
        # the light that spills onto the wet street
        self.spill = GlowSpot(center=self.bottom_center, radius=self.width * 0.9,
                              color=(1, 0.65, 0.3), amount=0)

    def tip(self):
        x, y = self.roof.points[2]
        return (x, y)

    def light_up(self):
        if self.dark or self.lit:
            return
        self.lit = True
        st.lit += 1
        for win in self.windows:
            win.fade_in(0.5)
        self.spill.amount = 0.7

    def burn(self):
        canvas.explosion_at(self.tip(), amount=1.1)
        canvas.debris_at(self.tip(), color=(0.45, 0.32, 0.3), radius=60, fall=1)
        if self.lit:
            st.lit -= 1
            for win in self.windows:
                win.burn_out(0.9)
        self.lit = False
        self.dark = True
        self.spill.amount = 0
        self.after(9, self.repair)

    def repair(self):
        self.dark = False


houses = [House(p1=(880, GROUND), p2=(980, GROUND + 86)),
          House(p1=(1012, GROUND), p2=(1100, GROUND + 108)),
          House(p1=(1132, GROUND), p2=(1240, GROUND + 78))]

# ---------------------------------------------------------------- the cables

light_tracks = []


def sag(p, q, depth):
    """The low point of a cable hung from p to q."""
    px, py = p
    qx, qy = q
    return ((px + qx) / 2, min(py, qy) - depth)


def cable(points, house=None):
    """A dim cable, a twin of light for the pulses and, on the long ones, a spark riding it."""
    wire = Track(points=points, color=(0.22, 0.24, 0.32), line_width=2)
    # the twin buzzes around the wire; only a short window of it shows
    light = Track(points=points, color=SPARK, line_width=2.5)
    light.zigzag(amount=3, waves=24)
    light.wander(amount=2, seed=randint(0, 999))     # an uneven buzz
    light.blend = "add"
    # the lit stretch follows light.pulse: a pulse is light.pulse going 0 → 1
    light.pulse = 0
    light["end"] @= lambda: min(1, light.pulse * 1.3)
    light["begin"] @= lambda: max(0, light.pulse * 1.3 - 0.3)
    light.visible = False       # idle: not drawn at all
    light.house = house
    light_tracks.append(light)
    if house is None:       # the short house lines carry only the pulses
        rider = Circle(radius=2.5, color="white")
        rider.tail = Tail(color=(0.4, 0.7, 1), size=1.6)
        rider.move_along(wire, speed=uniform(50, 110), loops="forever", yoyo=True,
                         phase=uniform(0, 1))
    return light


cable([big.tip(), sag(big.tip(), small.tip(), 90), small.tip()])
for house in houses:
    cable([small.tip(), sag(small.tip(), house.tip(), 40), house.tip()], house)

# ---------------------------------------------------------------- the rods


class Rod(Rect, width=6, height=290, color=(0.55, 0.58, 0.66)):
    """A lightning rod, wired to the small coil. Drag it along the ground."""

    def setup(self):
        cast_shadow(self, 4)
        self.ball = Circle(center=lambda: self.top_center, radius=6, color=(0.85, 0.9, 1))
        self.ball.glow = CheapGlow(SPARK, radius=8)     # the tips you can grab
        # the cable is hung from the rod: drag the rod and the cable follows
        self.light = cable([lambda: self.ball.center,
                            lambda: sag(self.ball.center, small.ring.center, 70),
                            small.tip()])

    def tip(self):
        x, y = self.ball.center
        return (x, y)


rods = [Rod(center=(380, GROUND + 145)), Rod(center=(820, GROUND + 145))]

# The rods are moved by hand, not with draggable: a dragged shape stays under
# the pointer, up and down too, and a rod must only slide along the ground.
held = None     # the rod in your hand


def on_mouse_down(x, y, button):
    global held
    held = None
    for rod in rods:
        if rod.contains_point(x, y) or rod.ball.contains_point(x, y):
            held = rod


def on_mouse_drag(x, y, button):
    if held is not None:
        held.center = (x, GROUND + held.height / 2)     # only sideways


def on_mouse_up(x, y, button):
    global held
    held = None

# ---------------------------------------------------------------- power


def send_power(light):
    """A pulse of light runs along a cable; at its end, a house lights up."""
    if light.visible:
        return      # the last pulse is still on its way
    light.pulse = 0
    light.visible = True
    tween(light["pulse"], 1, time=1.4, ease="ease_in", on_done=lambda: arrive(light))


def arrive(light):
    light.visible = False
    if light.house is not None and st.charge > 0.12:
        light.house.light_up()


def power_tick():
    """The coils push power out while the grid has charge."""
    if st.charge < 0.08:
        return
    for light in light_tracks:
        send_power(light)


every(2.5, power_tick)

# ---------------------------------------------------------------- ball lightning

# in the storm, a ball of light loops its way along the top of the main cable
path = Track(points=[(150, 440), (400, 430), (640, 360)])
path.orbit(radius=24, laps=5)
carrier = Point(0, 0)
carrier.move_along(path, time=16, loops="forever", yoyo=True)
ball = Orb(center=(0, 0), radius=22, color=(0.6, 0.8, 1), glow=1.2)
ball["center"] @= lambda: carrier

# ---------------------------------------------------------------- lightning

# the last strikes stay on as afterimages, then dissolve
afterimages = History(max_points=2, duration=3, on_leave=lambda b: b.dissolve_out(0.8))


def bolt(start, end, width=3):
    """A jagged line of light from start to end."""
    sx, sy = start
    ex, ey = end
    points = [start]
    for i in range(1, 6):
        k = i / 6
        points.append((sx + (ex - sx) * k + uniform(-45, 45), sy + (ey - sy) * k))
    points.append(end)
    line = Track(points=points, smooth=0, color=(0.88, 0.94, 1), line_width=width)
    line.blend = "add"
    return line


def afterimage(line):
    """The flash passes; a thin dim blue line stays on the eye.

    Drawn plainly (not added) it is much cheaper while it lingers."""
    line.blend = "normal"
    line.line_width = 2
    line.color = (0.35, 0.48, 0.95, 0.5)


def strike(x):
    """Lightning falls near x and hits the tallest thing around it."""
    near = [t for t in coils + rods + houses if abs(t.tip()[0] - x) < 240]
    if not near:
        return
    target = max(near, key=lambda t: t.tip()[1])
    tip = target.tip()
    line = bolt((x + uniform(-80, 80), CLOUD), tip)
    line.after(0.12, lambda: afterimage(line))
    afterimages.add(line)
    canvas.zap_at(tip, style="fork", radius=70, color=(0.7, 0.85, 1), flash=True)
    canvas.shake(6)
    sparks = Sparks(center=tip, radius=30, rate=50, color=(0.8, 0.9, 1))
    sparks.after(0.5, sparks.destroy)
    if target in houses:
        target.burn()
    else:
        st.charge = min(1, st.charge + 0.25)
        if target in rods:
            send_power(target.light)    # the rod sends the strike down its cable
    if st.part == "peak" and chance(0.25):
        big_strike(tip)


def big_strike(tip):
    """The biggest strikes punch the camera, jolt it askew and blur toward the hit."""
    if st.punching:
        return      # one punch at a time: a new zoom would cut the last one short
    st.punching = True
    blur = ZoomBlur(center=tip, amount=0.35)
    after(0.3, blur.remove)
    canvas.glitch(0.6)
    canvas.zoom_to(st.zoom * 1.08, time=0.06, on_done=punch_back)
    canvas.rotate_to(choice([-2.5, 2.5]), time=0.06, on_done=straighten)


def punch_back():
    canvas.zoom_to(st.zoom, time=0.7, ease="ease_out",
                   on_done=lambda: setattr(st, "punching", False))


def straighten():
    # back straight soon: a turned view makes every curved cable dearer to draw
    canvas.rotate_to(0, time=0.5, ease="ease_out")


def storm_tick():
    odds = {"calm": 0, "storm": 0.1, "peak": 0.22}.get(st.part, 0)
    if chance(odds):
        strike(uniform(LEFT + 150, RIGHT - 150))


every(0.4, storm_tick)

# ---------------------------------------------------------------- weather and screen

# rain only where the camera looks: each drop costs, even off screen
rain = Rain(p1=(-40, GROUND - 10), p2=(1340, 740), amount=0, color=(0.65, 0.75, 0.95))

# Posts cost a pass over the whole screen each, so only Bloom stays on;
# the others come in for their part of the night.
Bloom(intensity=0.6, sigma=10)
# gentle rays: stronger ones leave ghost copies of every bright shape
rays = GodRays(weight=0.03, decay=0.9, exposure=0.5, target=sun)
rays.enabled = False
crt = Crt(amount=0.9)
crt.enabled = False
# the dark edges of the picture: a soft frame that stays on the window
Rect(p1=(0, 0), p2=(1280, 720), layer="ui",
     color=Gradient((0, 0, 0, 0), (0, 0, 0, 0.75), type="radial", size=820))


# in steps of 1%: nobody sees a smaller change, and each change costs a little
@on_change(lambda: (round(st.storm, 2), round(st.dawn, 2)))
def weather():
    """The sky, the rain and the light follow the storm and the dawn."""
    stars.alpha = (1 - st.storm) * (1 - st.dawn)
    clouds.alpha = 0.15 + 0.6 * st.storm
    clouds.speed = 0.2 + 0.9 * st.storm
    rain.amount = 0.1 + 0.22 * st.storm - 0.1 * st.dawn
    ball.amount = st.storm
    morning.set_alpha(0.6 * st.dawn)
    morning.visible = st.dawn > 0
    for shade in shadows:
        shade.visible = st.dawn > 0.02


weather()

Text(lambda: f"GRID {st.level * 5:3d}%     HOUSES LIT {st.lit}/3     {st.part.upper()}",
     top_left=(24, 36), color=(0.6, 0.7, 0.85), font_size=14, layer="ui")

# ---------------------------------------------------------------- the night


# The camera moves between the parts of the night and then holds still:
# a still camera keeps the long curved cables cheap to draw.


def calm():
    tween(st["storm"], 0, time=4, name="storm")
    tween(st["dawn"], 0, time=2, name="dawn")
    rays.enabled = False
    sun.center = (1050, -120)
    st.zoom = 1
    st.punching = False
    canvas.reset_view()


def storm():
    tween(st["storm"], 0.7, time=8, name="storm")
    # lean in toward the street, where the strikes will matter
    st.zoom = 1.07
    canvas.zoom_to(st.zoom, time=5, ease="ease_in_out")
    canvas.pan_to(660, 350, time=5, ease="ease_in_out")


def peak():
    tween(st["storm"], 1, time=2, name="storm")


def dawn():
    tween(st["storm"], 0, time=6, name="storm")
    tween(st["dawn"], 1, time=8, name="dawn")
    # step back and turn toward the rising sun (a second later: a last
    # zoom punch may still be on its way back)
    st.zoom = 1
    after(1, morning_camera)
    rays.enabled = True
    sun.move_to(1050, 300, time=12, ease="ease_out")


def morning_camera():
    canvas.zoom_to(1, time=6, ease="ease_in_out")
    canvas.pan_to(720, 360, time=6, ease="ease_in_out")


def back_to_calm():
    begin("calm")
    canvas.fade_in(1.5)


def begin(part):
    st.part = part
    st.left = PARTS[part]
    {"calm": calm, "storm": storm, "peak": peak, "dawn": dawn}[part]()


def next_part():
    if st.part == "nightfall":
        return              # the fade brings the night back by itself
    if st.part == "dawn":
        st.part = "nightfall"
        st.left = 99
        canvas.fade_out(1.2, on_done=back_to_calm)
    else:
        begin({"calm": "storm", "storm": "peak", "peak": "dawn"}[st.part])


begin("calm")


def update(dt):
    st.left -= dt
    if st.left <= 0 or keyp.once("SPACE"):
        next_part()
    # the grid slowly leaks; the city and the HUD read it in steps
    st.charge = max(0, st.charge - 0.012 * dt)
    level = round(st.charge * 20)
    if level != st.level:
        st.level = level
    if keyp.once("C"):
        crt.enabled = not crt.enabled


def on_mouse_click(x, y, button):
    coil = min(coils, key=lambda c: abs(c.tip()[0] - x))
    line = bolt(coil.tip(), (x, y), width=2)
    line.dissolve_out(0.5, on_done=line.destroy)
    canvas.zap_at(x, y, style="spark", radius=40, color=(0.7, 0.85, 1))


run()
