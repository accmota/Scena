"""Old School.

A tribute megademo. The classic effects of the demoscene, each one rebuilt
from plain Scena parts (text, rects, circles, formulas) instead of pixel
code:

  I     Starfield      stars fly at you; the title flies in, letter by letter
  II    Sine scroller  the greetings ride a sine wave over a checker floor
  III   Copper bars    bars of light cross and mix; a logo bounces through
  IV    Twister        a square column of bars twisting like taffy
  V     Rotozoomer     the whole world tiles, turns and zooms
  VI    Plasma         a plasma sky, then a dive into a tunnel
  VII   Vector balls   shiny balls shaped as a cube, a sphere, a ring
  VIII  Power off      an old TV switches off down to a white dot

One async script at the bottom of the file, show(), is the storyboard: it
reads like the running order of the demo, part by part, and loops forever.

Things to try
-------------
  Read show()           every part is a few lines: build, wait, cut
  Change the timings    each part says how long it lasts (await wait(…))
  Turn the music off    the bloom stops breathing with the beat

Controls
--------
  none: sit back, it loops forever (close the window to stop)

Use
---
    python examples/old_school.py
"""

from math import sin, cos, pi
from random import uniform, choice
from scena import *

init(width=1280, height=800, title="Old School")

TITLE_FONT = "fonts/VastShadow-Regular.ttf"
FONT = "fonts/Quantico-Bold.ttf"

# ---- the stage: lasts for the whole demo ----

# the light breathes with the music (update reads audio.level)
light = Bloom(intensity=0.5)
play_sound("music/super_hero_original_no_intro.ogg", loops="forever", volume=0.8)

st.t0 = 0           # when the current part started (clock.time)
st.morph = 0        # vector balls: 0 cube · 1 sphere · 2 ring


class Part(Act):
    """A blank act. change_act(Part) clears the last part: its objects,
    background, posts and camera all leave together."""


def new_part(name):
    """Start a fresh part with a small caption in the corner."""
    change_act(Part)
    st.t0 = clock.time
    label = Text(name, top_left=(28, 784), font=FONT, font_size=16,
                 color=Color("white").with_alpha(0.55))
    label.fade_in(1.0)


def cut():
    """The classic hard cut between parts: a glitch and a flash."""
    canvas.glitch(1.2)
    canvas.flash(0.5)


# ---- I  starfield ----

async def starfield():
    new_part("I  STARFIELD")
    stars = StarFly(speed=0.3, density=1.4)
    canvas.set_fly(stars)
    await wait(1.0)

    # the letters fly in from all sides and land in a row, with a spark
    word = "OLD SCHOOL"
    for i in range(len(word)):
        if word[i] == " ":
            continue
        home = (640 - 4.5 * 104 + i * 104, 440)
        letter = Text(word[i], center=(uniform(-300, 1580), choice([-200, 1000])),
                      font=TITLE_FONT, font_size=110,
                      color=Color.from_hsv(i / len(word), 0.55, 1))
        letter.move_to(home, time=1.1, ease="elastic",
                       on_done=lambda l=letter: canvas.zap_at(l, radius=50, amount=0.7,
                                                              color=l.fill))
        await wait(0.22)
    await wait(1.0)
    canvas.flash(0.4)
    canvas.ripple_at(640, 440)
    stars.speed = 2.5

    # a frame around the title, with two lights running around it
    frame = Rect(center=(640, 420), width=1120, height=300)
    frame.visible = False
    for start, color in ((0, "cyan"), (0.5, "magenta")):
        # no .glow: the Bloom already lights the stroke, and costs nothing more
        light_run = Track(frame, color=color, line_width=5)
        light_run["begin"] @= lambda s=start: (s + (clock.time - st.t0) * 0.25) % 1
        light_run["end"] @= lambda s=start: (s + 0.18 + (clock.time - st.t0) * 0.25) % 1

    sub = Text("a tribute megademo  ·  made of plain scena parts", center=(640, 320),
               font=FONT, font_size=24, color="light gray")
    sub.fade_in(1.5)
    await wait(5)

    # dive into the title
    stars.speed = 6
    await parallel(canvas.zoom_to(5, time=1.6, ease="ease_in"),
                   canvas.rotate_by(25, time=1.6, ease="ease_in"))
    cut()


# ---- II  sine scroller ----

MESSAGE = ("HELLO SCENERS!   THIS IS OLD SCHOOL   *   NO PIXEL CODE HERE, "
           "ONLY LETTERS AND FORMULAS   *   GREETINGS TO ALL!")
SPACING = 52        # one letter every SPACING units
SCROLL = 340        # units per second, right to left


def scroll_place(i):
    """Where letter i of the message is now: sliding left on a sine wave."""
    x = 1320 + i * SPACING - SCROLL * (clock.time - st.t0)
    y = 470 + 110 * sin(x * 0.006 + clock.time * 2.6)
    return (x, y)


async def scroller():
    new_part("II  SINE SCROLLER")
    canvas.set_fly(Floor(color="dark magenta", sky="black", speed=1.6, grid=0.9, fog=0.7))
    Stars()

    for i in range(len(MESSAGE)):
        if MESSAGE[i] == " ":
            continue
        letter = Text(MESSAGE[i], center=lambda i=i: scroll_place(i),
                      font=TITLE_FONT, font_size=64)
        # no .glow here: on a Gradient letter it costs about 1 ms each; the
        # Bloom already makes the white middle shine
        letter.fill = Gradient("gold", "white", "orange red", angle=-90)

    # a VU meter on top: one bar per band of the music
    for band in range(16):
        x = 400 + band * 32
        bar = Rect(p1=(x - 12, 700),
                   p2=(x + 12, lambda b=band: 704 + 70 * amp_db(audio.spectrum(16)[b])))
        bar.fill = Gradient("cyan", "magenta", angle=90)
        bar.visual = Halo(style="soft")

    await wait(16)
    cut()


# ---- III  copper bars ----

COPPER = ["red", "orange", "gold", "lime", "cyan", "dodger blue", "blue violet", "magenta"]


def drop_ghost(logo):
    """One ghost of the logo, left behind where it is now."""
    # each ghost a little further round the colour wheel: a rainbow trail
    tint = Color.from_hsv(clock.time * 0.6 % 1, 0.8, 1).with_alpha(0.45)
    ghost = logo.ghosts.add(Text("SCENA", center=logo.center, font=TITLE_FONT, font_size=150,
                                 color=tint))
    ghost.fade_out(0.5)


async def copper_bars():
    new_part("III  COPPER BARS")
    canvas.background = "black"

    # horizontal bars, each on its own sine; light adds where they cross
    for i in range(len(COPPER)):
        bar = Rect(center=(640, lambda i=i: 400 + 300 * sin(clock.time * 1.3 + i * 0.55)),
                   width=1280, height=44)
        bar.fill = Gradient("black", COPPER[i], "white", COPPER[i], "black", angle=90)
        bar.line = None
        bar.blend = "add"
    # and a few standing bars that sweep sideways through them
    for i in range(5):
        bar = Rect(center=(lambda i=i: 640 + 560 * sin(clock.time * 0.8 + i * 0.4), 400),
                   width=28, height=800)
        bar.fill = Gradient("black", COPPER[i + 3], "white", COPPER[i + 3], "black")
        bar.line = None
        bar.set_alpha(0.6)
        bar.blend = "add"

    # the logo bounces in front, leaving ghosts behind (the History keeps
    # the last 8 and destroys the older ones)
    logo = Text("SCENA", center=(lambda: (640 + 220 * sin(clock.time * 0.9),
                                          230 + 330 * abs(sin(clock.time * 2.2)))),
                font=TITLE_FONT, font_size=150, color="white")
    logo.glow = Glow("cyan", radius=16)
    logo.ghosts = History(max_points=8)
    logo.every(0.07, lambda: drop_ghost(logo))

    await wait(12)
    cut()


# ---- IV  twister ----

FACES = ["deep pink", "gold", "deep sky blue", "lime green"]
ROWS = 100
RADIUS = 110
STEPS = 32          # shades per face, from dark (0) to fully lit (STEPS)
LIGHT = 0.7         # the light comes from a little to the left (radians)


def face_paint(face, step):
    """One face at one shade: dark when it turns away, and a touch of white
    shine when it faces the light full on."""
    lit = Color.interpolate(Color("black"), Color(face), 0.1 + 0.9 * step / STEPS)
    return Color.interpolate(lit, Color("white"), 0.2 * (step / STEPS) ** 3)


# every face at every shade, made once: the rows only pick one. (A plain
# colour, not a Gradient: a Gradient on a shape whose width changes every
# frame is rebuilt every frame, and 200 of them cost ~10 ms.)
PAINTS = [[face_paint(face, step) for step in range(STEPS + 1)] for face in FACES]


class Row(Rect):
    """One row of the twister: a slice of a turning square column. We see two
    of its four faces at a time; this Rect paints the left one and its partner
    the right one."""

    def setup(self):
        self.line = None
        self.partner = Rect(center=self.center, width=10, height=self.height)
        self.partner.line = None
        self.paints = [None, None]

    def on_update(self, dt):
        t = clock.time - st.t0
        # the twist travels along the column: each row turns a bit later
        turn = t * 1.4 + 2.2 * sin(t * 0.7 + self.row * 0.025)
        sway = 90 * sin(t * 1.1 + self.row * 0.017)
        slabs = [self, self.partner]
        seen = 0
        for face in range(4):
            a = turn + face * pi / 2        # where this face starts on the circle
            x1 = RADIUS * sin(a)
            x2 = RADIUS * sin(a + pi / 2)
            if x2 > x1 and seen < 2:        # it faces us: we see it
                slab = slabs[seen]
                slab.center = (640 + sway + (x1 + x2) / 2, slab.center.y)
                # 2 units narrower than the face: the dark background shows
                # between two faces, a thin seam along the corner
                slab.width = max(x2 - x1 - 2, 1)
                # brightness: how much the face turns to us, and to the light
                to_us = cos(a + pi / 4)
                to_light = max(0, cos(a + pi / 4 + LIGHT))
                step = round(STEPS * (0.55 * to_us + 0.45 * to_light))
                paint = PAINTS[face][step]
                if paint is not self.paints[seen]:     # repaint only on a new step
                    self.paints[seen] = paint
                    slab.fill = paint
                seen += 1


async def twister():
    new_part("IV  TWISTER")
    Wallpaper(Gradient("midnight blue", "black", "midnight blue", angle=90))
    Lattice(fold="square", color="dark slate blue", alpha=0.25)
    for row in range(ROWS):
        # a hair taller than the gap between rows: no seams between them
        twist_row = Row(center=(640, 800 * (row + 0.5) / ROWS), width=10, height=800 / ROWS + 0.6)
        twist_row.row = row
    await wait(4)
    await canvas.zoom_to(1.35, time=3, ease="ease_in_out")
    await canvas.zoom_to(1, time=3, ease="ease_in_out")
    await wait(1.5)
    cut()


# ---- V  rotozoomer ----

async def rotozoomer():
    new_part("V  ROTOZOOMER")
    Wallpaper("images/bg5.jpeg", fit="tile", tile_size=260, tile_mode="mirror",
              zoom_response=1, rotation_response=1)
    Vignette(amount=0.8)
    canvas.rotate_by(360, time=9, loops="forever")
    canvas.zoom_to(3.5, time=3, loops="forever", yoyo=True, ease="ease_in_out")
    await wait(12)
    cut()


# ---- VI  plasma and tunnel ----

async def plasma():
    new_part("VI  PLASMA")
    Plasma(color="dark violet", amount=1.0, speed=1.2, alpha=1)
    wash = ColorWash("magenta", "cyan", "gold", amount=0.7, saturation=1)
    mirrors = Kaleidoscope(segments=8, spin=0.12)
    # on the ui layer, the word is drawn after the posts: the mirrors leave it alone
    big = Text("PLASMA", center=(640, 400), layer="ui", font=TITLE_FONT, font_size=170,
               color="black")
    big.glow = Glow("white", radius=20)
    big.fade_in(1)
    await wait(6)

    # through the floor and into the tunnel
    canvas.flash(0.8)
    big.destroy()
    wash.remove()
    mirrors.remove()
    canvas.set_fly(Tunnel(color="cyan", amount=2.5, speed=2, density=2, streak=1.5))
    Warp(center=(640, 400), radius=110, color="violet", amount=1.5, speed=1.5)
    # words fly out of the tunnel at you, with lightning around them
    for word in ["INTO", "THE", "TUNNEL", "AND", "OUT", "AGAIN"]:
        flyer = Text(word, center=(640, 400), font=TITLE_FONT, font_size=60, color="lavender")
        flyer.scale = 0.1
        flyer.scale_to(5, time=1.1, ease="ease_in")
        flyer.fade_out(1.1)
        for i in range(3):
            canvas.zap_at(uniform(250, 1030), uniform(150, 650), style=choice(["fork", "spark"]),
                          color=choice(["cyan", "magenta", "gold"]), radius=60)
            await wait(0.37)
    cut()


# ---- VII  vector balls ----

BALLS = 64
BALL_COLORS = ["tomato", "gold", "deep sky blue", "orchid"]


def cube_point(n):
    """Ball n on a 4×4×4 cube, from -0.75 to 0.75 (its corners reach about 1.3)."""
    return ((n % 4) / 2 - 0.75, (n // 4 % 4) / 2 - 0.75, (n // 16) / 2 - 0.75)


def sphere_point(n):
    """Ball n spread evenly over a sphere (the golden-angle spiral)."""
    y = 1 - 2 * (n + 0.5) / BALLS
    r = (1 - y * y) ** 0.5
    a = n * 2.39996
    return (r * cos(a), y, r * sin(a))


def ring_point(n):
    """Ball n on a torus: 16 around the ring, 4 around the tube."""
    a = (n % 16) * 2 * pi / 16
    b = (n // 16) * 2 * pi / 4
    r = 1 + 0.35 * cos(b)
    return (r * cos(a), 0.35 * sin(b), r * sin(a))


def blend3(a, b, k):
    """The 3D point k of the way from a to b (k from 0 to 1)."""
    return (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k)


class Ball(Circle):
    """One vector ball. It knows its place on each shape and turns with the
    others; nearer balls are bigger and drawn in front."""

    def on_update(self, dt):
        m = st.morph
        if m < 1:
            x, y, z = blend3(self.cube, self.sphere, m)
        else:
            x, y, z = blend3(self.sphere, self.ring, m - 1)
        t = clock.time
        # turn about y, then about x
        x, z = x * cos(t * 0.9) - z * sin(t * 0.9), x * sin(t * 0.9) + z * cos(t * 0.9)
        y, z = y * cos(t * 0.6) - z * sin(t * 0.6), y * sin(t * 0.6) + z * cos(t * 0.6)
        near = 4 / (4 + z)          # perspective: z below 0 is near, above 0 far
        self.center = (640 + 210 * x * near, 400 + 210 * y * near)
        self.radius = 18 * near
        # nearer balls on higher layers; only move it when the layer changes
        layer = 10 + round((1 - z) * 4)
        if layer != self.depth:
            self.depth = layer
            self.layer = layer


async def vector_balls():
    new_part("VII  VECTOR BALLS")
    canvas.set_fly(Floor(color="navy", sky="black", speed=0.5, grid=1, fog=0.6))
    st.morph = 0
    for n in range(BALLS):
        # one colour per slice of the cube (and per ring of the torus)
        ball = Ball(center=(640, 400), radius=10, color=BALL_COLORS[n // 16])
        ball.visual = Sphere()
        ball.cube = cube_point(n)
        ball.sphere = sphere_point(n)
        ball.ring = ring_point(n)
        ball.depth = None
        ball.fade_in(0.6)
    await wait(4)
    await tween(st["morph"], 1, time=2, ease="ease_in_out")
    canvas.ripple_at(640, 400, amount=0.6)
    await wait(3)
    await tween(st["morph"], 2, time=2, ease="ease_in_out")
    canvas.ripple_at(640, 400, amount=0.6)
    await canvas.zoom_to(1.4, time=2.5, ease="ease_in_out")
    await canvas.zoom_to(1, time=1.5, ease="ease_in_out")
    cut()


# ---- VIII  power off ----

async def power_off():
    new_part("VIII  POWER OFF")
    canvas.set_fly(StarFly(speed=0.6))
    Crt(amount=1, chroma=1.2, scan=1)
    Scanlines(amount=0.6)
    thanks = Text("THANKS FOR WATCHING", center=(640, 470), font=TITLE_FONT, font_size=58)
    thanks.fill = Gradient("cyan", "white", "magenta", angle=-90)
    credit = Text("music: SuperHero (opengameart)  ·  code: scena", center=(640, 360),
                  font=FONT, font_size=22, color="light gray")
    thanks.fade_in(1)
    credit.fade_in(2)
    for color in ["gold", "cyan", "magenta", "white"]:
        await wait(1.2)
        canvas.fireworks_at(uniform(200, 1080), uniform(560, 700), color=color, radius=90)
    await wait(0.8)

    # the old TV switches off: the picture squeezes into a line, then a dot
    top = Rect(p1=(0, 800), p2=(1280, 1200), color="black", layer="top")
    bottom = Rect(p1=(0, -400), p2=(1280, 0), color="black", layer="top")
    await parallel(top.move_by(0, -400, time=0.25, ease="ease_in"),
                   bottom.move_by(0, 400, time=0.25, ease="ease_in"))
    canvas.flash(0.4)
    beam = Rect(center=(640, 400), width=1280, height=4, color="white", layer="top")
    beam.glow = Glow("light cyan", radius=24, amount=2)
    await tween(beam["width"], 8, time=0.3, ease="ease_in")
    beam.destroy()
    dot = Circle(center=(640, 400), radius=8, color="white", layer="top")
    dot.glow = Glow("light cyan", radius=30, amount=2)
    await wait(0.5)
    # the iris closes on the dot, the last light on the screen
    canvas.fade_out(1.0, style="iris")
    await tween(dot["radius"], 2, time=1.0, ease="ease_in")
    await wait(0.6)


# ---- the storyboard ----

async def show():
    await wait(0.5)         # a beat of black, like an old demo loading
    while True:
        canvas.fade_in(0.6)
        await starfield()
        await scroller()
        await copper_bars()
        await twister()
        await rotozoomer()
        await plasma()
        await vector_balls()
        await power_off()


def update(dt):
    # the bloom breathes with the music
    light.intensity = 0.3 + 0.6 * amp_db(audio.level)


run_task(show)
run(Part)
