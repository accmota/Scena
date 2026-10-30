"""Scena: the third teaser. Why Scena (no code).

Teaser 1 shows what Scena makes, teaser 2 how it reads; this one what it is
for, shown, not told: each idea is a picture. Words of the engine appear only
as labels on the things they move (the machine), never as code to read
(the X-ray shows real code, as a texture with fragments you can read).

  0:00  SCENA                 a neon sign switches on over a road at dusk
  0:09  built for learning    a ninja climbs a staircase of tutorial chapters
  0:24  simple, yet powerful  one dot doubles into hundreds, a flock, a ring
  0:37  nothing hidden        an X-ray: behind the game, the code of the game
  0:53  a vocabulary          a chain-reaction machine, each part one word
  1:16  interfaces            widgets and the mouse drive a flower
  1:31  the level editor      select, move, draw, resize, turn, copy, undo, pan, fit
  1:50  effects               every effect has parameters; and they compose
  2:15  games                 a wall of games made with Scena
  2:25  this video was 100% made with Scena (the music has ended)

Music: "The Adventure Begins" by Bart Kelsey (CC BY 3.0), up to the end of
its second climax (make_media.py -> adventure_cut.flac).

Use
---
    python videos/scripts/teaser3/make_media.py        # music and the stairs' stills
    python videos/scripts/teaser3/teaser3.py           # live (no pointer: the widgets stay put)
    python tools/video/record_game.py videos/scripts/teaser3/teaser3.py \\
        --pilot videos/scripts/teaser3/teaser3_pilots.py:show --seconds 151.3 --size 2560x1440 \\
        --prores --out $PWD/videos/recordings/masters.nosync/teaser3.mov
    python videos/scripts/kit/promo_composite.py videos/recordings/masters.nosync/teaser3.mov \\
        videos/recordings/teaser3/scena_teaser3.mp4 videos/recordings/teaser3/cues.json
    python videos/scripts/kit/finish.py videos/recordings/teaser3/scena_teaser3.mp4 promo/scena_teaser3

    TEASER_START=53 python videos/scripts/teaser3/teaser3.py      # start at a section (no music)
"""

import os
import sys
from types import SimpleNamespace
from math import sin, cos, pi, atan2, hypot
from random import uniform, seed

from scena import *

init(width=1280, height=720, title="Scena")
seed(7)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "kit"))
from paths import REPO, work               # noqa: E402
from promo_kit import *                      # noqa: E402,F403
from promo_kit import kit                    # noqa: E402

MEDIA = work("teaser3")
MUSIC = os.path.join(MEDIA, "adventure_cut.flac")
MUSIC_SECONDS = 145.6       # the end of the second climax (the file fades 1.2 s after)
CUES = os.path.join(MEDIA, "cues.json")
START = float(os.environ.get("TEASER_START", "0"))
kit.setup(cues=CUES, start=START)

canvas.background = NIGHT
light = Bloom(intensity=0.6)
Vignette(amount=0.65)

st.mode = None      # what update() moves this frame (a section's own motion)
my = SimpleNamespace()  # the things a section's motion moves (st keeps values only)


def now():
    """Seconds into the teaser (here, not imported: a formula follows only this
    file's functions)."""
    return clock.time - st.t0


def reset_camera():
    canvas.zoom_to(1)
    canvas.pan_to(640, 360)


# ---- 0:00  the title: a neon sign switches on over a road at dusk ----

DUSK = Color("#2a0f2e")
PINK = Color("#ff3fa4")
AMBER = Color("#ffb347")


async def title(t):
    road = Road(PINK, sky=DUSK, speed=0.5, fog=0.75)
    canvas.set_fly(road)
    # a striped sun on the horizon; its stripes slide down
    sun = Circle(center=(640, 518), radius=164)
    sun.fill = Gradient(AMBER, PINK, angle=-90)
    sun.glow = True
    sun.fade_in(1.6)
    stripes = []
    for k in range(6):
        band = Rect(center=(640, 400), width=350, height=4, color=DUSK)
        band["center"] @= lambda k=k: (640, 488 - (k * 22 + now() * 12) % 132)
        band["height"] @= lambda k=k: 2 + (132 - (k * 22 + now() * 12) % 132) * 0.1
        stripes.append(band)
    # the letters: dark glass with a neon edge, lit one by one
    row = letters("SCENA", (640, 470), size=150)
    for letter in row:
        letter.fill = DUSK.with_alpha(0.85)
        letter.line = ICE
        letter.line_width = 4
        letter.glow = True
        letter.visible = False
    await at(t + 1.0)
    for i, letter in enumerate(row):
        for k, on in enumerate((True, False, True, False, True)):
            after(0.07 * k + uniform(0, 0.03), lambda l=letter, on=on: setattr(l, "visible", on))
        after(0.32, lambda l=letter, i=i: canvas.zap_at(
            l, radius=70, amount=0.6, color=PINK if i % 2 else ICE))
        await wait(0.3)
    await at(t + 2.9)
    canvas.ripple_at(640, 470, radius=520, amount=0.4, shake=False)
    knob_to(light, "intensity", 1.3, time=0.4, back=True)
    tagline = arrive("2D games and creative graphics in Python", (640, 318), size=30,
                     color=FROST, font=SMALL_FONT, step=0.03)
    await at(t + 6.6)
    knob_to(road, "alpha", 0.0, time=1.4)        # a plain fade: the sign, the sun, the road
    for thing in row + tagline + stripes + [sun]:
        thing.fade_out(1.2)
    after(2.3, lambda: canvas.set_fly(None))     # the screen is black by then


# ---- 0:09  built for learning: a staircase of chapters ----

STEPS = (("01", "First script"), ("02", "Catch the stars"), ("05", "Ships"), ("10", "Balls"),
         ("12", "Movement"), ("15", "Plane"), ("18", "Ninja"), ("21", "Connect Four"),
         ("29", "Endless runner"), ("30", "Spins"), ("31", "Duel"), ("32", "Race"),
         ("33", "A hundred lines"))
STEP_W, STEP_H = 240, 150           # each step: a slab, its riser a chapter's game
CARD_W, CARD_H = 232, 130.5
CAM_OFF = Vec2(200, 130)            # the ninja low and left: the headline's corner stays clear


def step_top(k):
    """The middle of step k's slab, on top (where the ninja lands)."""
    return Vec2(k * STEP_W + STEP_W / 2, k * STEP_H)


async def stairs(t):
    Stars(color=FROST, density=0.35, twinkle=0.4)
    canvas.zoom_to(1)
    canvas.pan_to(step_top(0) + CAM_OFF - (60, 0))
    sheet = Sheet(anchor="bottom", pixel_size=0.2)
    sheet.strip("idle", "ninja/Idle__*.png", fps=8)
    sheet.strip("running", "ninja/Run__*.png", fps=14)
    sheet.strip("jumping", "ninja/Jump__*.png", fps=10)

    class Ninja(Sprite, source=sheet):
        pass

    shown = []

    def build(k):
        """Step k comes in: its slab draws itself, its chapter fades up."""
        top = step_top(k)
        card = Sprite(os.path.join(MEDIA, "steps", f"chapter_{STEPS[k][0]}_still.jpg"), width=CARD_W,
                      center=(top.x, top.y - 10 - CARD_H / 2))
        card.alpha = 0.45
        card.fade_in(0.5)
        slab = Rect(center=(top.x, top.y - 4), width=STEP_W, height=8, corner_radius=3,
                    color=ICE.with_alpha(0.9))
        slab.glow = True
        slab.fade_in(0.4)
        # a position in the call: a Text made without one is a HUD caption
        number = Text(STEPS[k][0], center=top, font=MONO, font_size=20, color=EMBER)
        right = top.x + STEP_W / 2 - 8
        number.center = (right - number.box.width / 2, top.y + 20)
        name = Text(STEPS[k][1], center=top, font=SMALL_FONT, font_size=17, color=FROST)
        name.center = (number.box.left - 8 - name.box.width / 2, top.y + 20)
        for thing in (number, name):
            thing.visible = False
        shown.append((card, number, name))

    def light_up(k):
        card, number, name = shown[k]
        tween(card["alpha"], 1.0, time=0.3)
        for thing in (number, name):
            thing.visible = True
            thing.fade_in(0.3)
        card.pulse_outline(0.6, color=EMBER)

    words = headline("Built for learning", size=36, layer="ui",
                     sub="a complete tutorial, one chapter on each step")
    for k in range(3):
        build(k)
    ninja = Ninja(center=step_top(0) - (60, 0))
    ninja.play("idle")
    my.ninja = ninja
    my.cam = step_top(0) + CAM_OFF - (60, 0)
    st.mode = "stairs"
    await at(t + 1.5)               # the ninja waits a moment before the run
    light_up(0)
    for k in range(len(STEPS) - 1):
        if k + 3 < len(STEPS):
            build(k + 3)
        # a short run to the edge, then a jump to the next step
        ninja.play("running")
        await ninja.move_to(step_top(k) + (55, 0), time=0.22)
        ninja.play("jumping")
        a, b = step_top(k) + (55, 0), step_top(k + 1) - (40, 0)
        steps = 30
        for n in range(1, steps + 1):
            s = n / steps
            ninja.center = (a.x + (b.x - a.x) * s,
                            a.y + (b.y - a.y) * s + 120 * 4 * s * (1 - s))
            await wait(1 / 60)
        canvas.hit_at(ninja.center.x, ninja.center.y, color=FROST, radius=30)
        light_up(k + 1)
        ninja.play("running")
        await ninja.move_to(step_top(k + 1) - (10, 0), time=0.12)
    ninja.play("idle")
    # the whole staircase, from far
    st.mode = None
    far = step_top(len(STEPS) // 2) + (0, -60)
    canvas.zoom_to(0.32, time=1.6, ease="ease_in_out")
    canvas.pan_to(far, time=1.6, ease="ease_in_out")
    await at(t + 12.0)
    # the empty corner under the stairs
    lines = [note("A complete tutorial for beginners:", (960, 210), size=28, layer="ui")]
    await wait(0.6)
    lines.append(note("33 chapters, from a first script", (960, 168), size=28, layer="ui"))
    lines.append(note("to real games.", (960, 126), size=28, layer="ui"))
    await at(t + 14.4)
    leave(words, lines, time=0.4)


# ---- 0:24  simple, yet powerful: one dot becomes a flock ----

async def simple(t):
    reset_camera()
    Stars(color=FROST, density=0.25, twinkle=0.3)
    first = Circle(center=(640, 290), radius=7, color=FROST)   # under the words
    first.glow = True
    first.fade_in(0.6)
    word = rise("Simple.", (640, 560), size=64, color="white")
    dots = [first]
    await at(t + 1.8)
    # it doubles: 1, 2, 4 … 256
    for generation in range(8):
        reach = 70 * 0.86 ** generation
        born = []
        for k, dot in enumerate(dots):
            a = uniform(0, 2 * pi)
            twin = Circle(center=dot.center, radius=dot.radius, color=dot.color)
            twin.glow = True
            dot.move_by(reach * cos(a), reach * sin(a), time=0.32, ease="ease_out")
            twin.move_by(-reach * cos(a), -reach * sin(a), time=0.32, ease="ease_out")
            born.append(twin)
        dots += born
        if generation in (0, 1, 2):
            for dot in dots:
                dot.pop(scale=1.5)
        await wait(0.45)
    # each dot takes a colour, and the field takes them away
    for k, dot in enumerate(dots):
        dot.color = lerp(ICE, EMBER, (k % 64) / 63)
        dot.radius = 4
        dot.phase = uniform(0, 2 * pi)
    my.flock = dots
    st.gather = 0.0
    st.mode = "flock"
    trail = MotionTrail()
    leave(word, time=0.5)
    await at(t + 7.0)
    word = rise("Yet powerful.", (640, 600), size=64, color="white")
    await at(t + 8.4)
    await tween(st["gather"], 1.0, time=1.8, ease="ease_in_out")    # into a turning ring
    knob_to(light, "intensity", 1.4, time=0.5, back=True)
    canvas.ripple_at(640, 285, radius=320, amount=0.5, shake=False)
    await at(t + 12.8)
    leave(word, dots, time=0.5)
    after(0.5, trail.remove)
    st.mode = None


def flock(dt):
    k = now()
    for n, dot in enumerate(my.flock):
        x, y = dot.center.x, dot.center.y
        # a field that turns slowly: each dot goes where the field points
        a = sin(x * 0.006 + k * 0.7) * 2.2 + cos(y * 0.007 - k * 0.5) * 2.2 + dot.phase * 0.2
        free = Vec2(x + cos(a) * 170 * dt, y + sin(a) * 170 * dt)
        if free.x < -20:
            free = Vec2(free.x + 1320, free.y)
        elif free.x > 1300:
            free = Vec2(free.x - 1320, free.y)
        if free.y < -20:                # the field wraps above the fading edge, unseen
            free = Vec2(free.x, free.y + 565)
        elif free.y > 545:
            free = Vec2(free.x, free.y - 565)
        g = st.gather
        if g > 0:
            turn = n / len(my.flock) * 2 * pi + k * 0.9
            ring = Vec2(640 + 210 * cos(turn), 285 + 210 * sin(turn))
            free = free + (ring - free) * min(1.0, g * 6 * dt + g * g * 0.5)
        dot.center = free
        # under the words the dots fade out over a soft edge that waves and drifts:
        # a straight cut drew a line of dots there (the dots the field holds against
        # the wrap, seen there every other frame); the ring, once gathered, shows whole
        edge = 498 + 22 * sin(free.x * 0.011 + k * 0.9) + 14 * sin(free.x * 0.004 - k * 0.6)
        u = max(0.0, min(1.0, (edge - free.y) / 80))
        u = u * u * (3 - 2 * u)
        dot.set_alpha(round(u + (1 - u) * max(0.0, min(1.0, g * 2 - 1)), 2))


# ---- 0:37  nothing hidden: an X-ray of a game ----

XRAY_IN = 40.0          # into videos/recordings/guardian/waves.mp4
# the scanner: (seconds from the clip's start, share of the pane behind it)
SCAN = ((0.0, 0.0), (1.6, 0.0), (3.6, 0.5), (6.2, 0.5), (7.6, 1.0), (9.8, 1.0), (11.9, 0.0))
EXCERPT = (201, 226)    # lines of examples/guardian.py: the ship, as an editor shows it


def smooth_at(keys, s):
    """A value from (time, value) keys, smoothstep between two keys (the
    composite draws the clip's edge with the same curve)."""
    if s <= keys[0][0]:
        return keys[0][1]
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if s <= t1:
            u = (s - t0) / (t1 - t0)
            return v0 + (v1 - v0) * u * u * (3 - 2 * u)
    return keys[-1][1]


async def xray(t):
    reset_camera()
    Stars(color=FROST, density=0.2, twinkle=0.3)
    window = Window((640, 350), 960, 540, color=ICE)
    await window.open()
    left = 640 - 480
    clip_start = video_time()
    window.play("guardian/waves", seconds=12.6, start=XRAY_IN, mask=[list(k) for k in SCAN])
    words = headline("Nothing hidden behind a wizard", y=678, size=32)
    # the code under the game: one stretch of examples/guardian.py, line numbers
    # in a gutter, as an editor shows it
    first, last = EXCERPT
    with open(os.path.join(REPO, "examples", "guardian.py")) as f:
        lines = f.read().split("\n")[first - 1:last]
    block = Code(232, 604, size=14, gap=1.4)
    block.show(lines, fade=0)
    code = [p for row in block.rows for p in row]
    for k in range(len(lines)):
        number = Text(str(first + k), center=(0, 0), font=MONO, font_size=14,
                      color=Color("slate gray"))
        number.center = (212 - number.box.width / 2, block.row_y(k) - 7)
        code.append(number)
    code.append(Text("guardian.py", center=(1062, 600), font=MONO, font_size=13,
                     color=CAPTION))
    # the scanner: a bright edge with a glow behind it, where the clip begins
    edge = Line(p1=(left, 80), p2=(left, 620), color=EMBER, line_width=3)
    edge.glow = True
    haze = Rect(center=(left - 30, 350), width=60, height=540)
    haze.fill = Gradient(EMBER.with_alpha(0), EMBER.with_alpha(0.25), angle=0)
    haze.line = None

    def place():
        x = left + 960 * smooth_at(SCAN, video_time() - clip_start)
        edge.p1 = (x, 80)
        edge.p2 = (x, 620)
        haze.center = (x - 30, 350)
        on = 0.0 < x - left < 959.0
        edge.visible = haze.visible = on

    my.place = place
    st.mode = "xray"
    await at(t + 0.8 + 6.4)
    words2 = note("The game is the code you write.", (640, 40), size=26)
    await at(t + 0.8 + 12.4)
    st.mode = None
    leave(words, words2, code, edge, haze, time=0.4)
    await window.close(time=0.5)


# ---- 0:53  a vocabulary: a machine, each part one word ----

LABELS = []


def label(text, x, y):
    parts = tag(text, (x, y), size=17, box=True)
    parts[0].pop(scale=1.3)
    LABELS.append(parts)
    return parts


async def machine(t):
    reset_camera()
    LABELS.clear()
    Stars(color=FROST, density=0.2, twinkle=0.3)
    words = headline("A vocabulary for games", y=684, size=32)
    collision.floor = True
    parts = []

    def show(thing, delay=0.0):
        thing.visible = False

        def appear():
            if thing.is_alive:
                thing.visible = True
                thing.fade_in(0.5)

        after(delay, appear)
        parts.append(thing)
        return thing

    # the ramp: a path for the ball, a rail under it
    path_points = [(60, 640), (140, 612), (230, 548), (310, 492), (372, 470)]
    path = Track(points=path_points)
    path.visible = False
    rail = show(Track(points=[(x, y - 15) for x, y in path_points], color=FROST,
                      line_width=3))
    ball = show(Circle(center=path_points[0], radius=14, color=EMBER, group="ball"))
    ball.glow = True
    ball.vel = Vec2(0, 0)
    # a shelf with dominoes, a crate at its end
    shelf = show(Rect(center=(530, 451), width=340, height=10, color=FROST.with_alpha(0.8),
                      corner_radius=3, group="floor"), 0.2)
    dominoes = []
    for k in range(6):
        d = show(Rect(center=(420 + 42 * k, 489), width=12, height=66, corner_radius=2,
                      color=ICE, group="dom_a" if k % 2 == 0 else "dom_b"), 0.3 + 0.05 * k)
        d.index, d.falling, d.lean, d.spin, d.limit = k, False, 0.0, 0.0, 34.0
        d.pivot = (420 + 42 * k + 6, 456)
        dominoes.append(d)
    dominoes[-1].limit = 84.0
    crate = show(Rect(center=(686, 473), width=34, height=34, corner_radius=4, color=FLARE,
                      group="crate"), 0.6)
    crate.vel = Vec2(0, 0)
    crate.free = False
    # the floor below, a plate on it; a timer, a row of lamps, a lift
    floor = show(Rect(center=(875, 250), width=350, height=12, color=FROST.with_alpha(0.8),
                      corner_radius=3, group="floor"), 0.5)
    plate = show(Rect(center=(970, 258), width=80, height=5, color=DEEP, corner_radius=2), 0.6)
    group["floor"].mass = STATIC
    dial = show(Circle(center=(970, 380), radius=24, color=PANEL), 0.7)
    dial.line = DEEP
    dial.line_width = 3
    face = Circle(center=(970, 380), radius=24)
    face.visible = False
    hand = Track(face, color=EMBER, line_width=4)
    hand.end = 0
    lamps = [show(Circle(center=(770 + 50 * k, 150), radius=9, color=DEEP), 0.8 + 0.05 * k)
             for k in range(6)]
    for lamp in lamps:
        lamp.glow = True
    fuse = show(Line(p1=(770, 150), p2=(1020, 150), color=DEEP.with_alpha(0.6), line_width=2),
                0.8)
    shaft = [show(Line(p1=(x, 120), p2=(x, 600), color=DEEP.with_alpha(0.7), line_width=2), 0.9)
             for x in (1078, 1182)]
    lift = show(Rect(center=(1130, 150), width=100, height=10, color=FROST, corner_radius=3),
                1.0)
    rider = show(Circle(center=lambda: lift.center + (0, 20), radius=15, color=ICE), 1.0)
    rider.glow = True
    wheel = show(Circle(center=(1185, 660), radius=55, color=PANEL), 1.1)
    wheel.line = FROST.with_alpha(0.6)
    wheel.line_width = 2
    weight = show(Rect(center=(1240, 600), width=34, height=54, corner_radius=4, color=DEEP),
                  1.2)
    weight["center"] @= lambda: (1240, 750 - lift.center.y)
    ropes = [show(Line(p1=(1130, 660), p2=lambda: lift.center + (0, 5),
                       color=FROST.with_alpha(0.5)), 1.1),
             show(Line(p1=(1240, 660), p2=lambda: weight.center + (0, 27),
                       color=FROST.with_alpha(0.5)), 1.2)]
    top_points = [(1112, 590), (1020, 586), (920, 572), (820, 556)]
    top_rail = show(Track(points=[(x, y - 16) for x, y in top_points], color=FROST,
                          line_width=3), 1.2)
    cup = show(Polygon(points=[(784, 560), (790, 528), (830, 528), (836, 560), (828, 560),
                               (824, 536), (796, 536), (792, 560)], color=EMBER), 1.3)
    my.dominoes, my.crate, my.ball = dominoes, crate, ball
    st.mode = "machine"

    # ---- the rules of the machine, each with its word ----

    @collide("ball", ["dom_a", "dom_b"])
    def knock(b, d):
        b.vel = Vec2(-60, 0)
        if not d.falling and d.lean == 0:
            label("@collide", 525, 575)
            d.falling, d.spin = True, 70.0

    @collide("dom_a", "dom_b")
    def topple(a, b):
        first, second = (a, b) if a.index < b.index else (b, a)
        if first.falling and not second.falling and second.lean == 0:
            first.falling = False           # it leans on the next one
            second.falling, second.spin = True, 80.0

    @collide(["dom_a", "dom_b"], "crate")
    def push(d, c):
        if not c.free:
            c.free = True
            c.vel = Vec2(240, 170)

    resolve("crate", "floor", bounce=0.3)

    @when(lambda: crate.free and crate.center.y < 300 and "bottom" in crate.touching_sides)
    def landed():
        label("resolve", 760, 330)

    @when(lambda: crate.free and crate.center.y < 300
          and abs(crate.center.x - plate.center.x) < 45
          and abs(crate.vel.x) < 25 and "bottom" in crate.touching_sides)
    def pressed():
        plate.color = EMBER
        plate.move_by(0, -2, time=0.1)
        label("@when", 970, 215)
        canvas.hit_at(plate, color=EMBER, radius=40)
        after(0.2, start_timer)

    def start_timer():
        label("after(2, …)", 970, 428)
        tween(hand["end"], 1, time=2.0)
        after(2.0, release)
        my.lit = 0

        def blink():
            lamps[my.lit].color = "gold"
            lamps[my.lit].pop(scale=1.5)
            my.lit += 1
            if my.lit == len(lamps):
                my.lamps.cancel()

        my.lamps = every(0.33, blink)
        label("every(0.33, …)", 895, 102)

    def release():
        canvas.zap_at(dial, color=EMBER, radius=60)
        run_task(lift_up)
        run_task(ride)
        # the formula's word rides on the weight it moves
        for part in label("@=", 1240, weight.center.y):
            off = Vec2(part.center.x - weight.center.x, part.center.y - weight.center.y)
            part["center"] @= lambda off=off: weight.center + off

    async def lift_up():
        await lift.move_to(1130, 560, time=2.4, ease="ease_in_out")

    async def ride():
        label("until(…)", 990, 640)
        await until(lambda: lift.center.y >= 559)
        LABELS[-1][0].pop(scale=1.3)
        rider.visible = False
        runner = Circle(center=rider.center, radius=15, color=ICE)
        runner.glow = True
        roll = Track(points=top_points)
        roll.visible = False
        await runner.move_along(roll, time=1.1, ease="ease_in")
        await runner.move_to(810, 548, time=0.15)
        runner.destroy()
        canvas.zap_at(cup, color=EMBER, radius=70)
        for k, (x, y) in enumerate(((640, 610), (470, 560), (820, 650), (300, 620))):
            after(0.25 * k, lambda x=x, y=y: canvas.fireworks_at(
                x, y, color=EMBER if k % 2 else ICE, color2=FROST, radius=120, amount=1.2))
        label("fireworks_at", 600, 370)

    await at(t + 2.0)
    leave(words, time=0.5)
    await at(t + 2.4)
    label("move_along", 180, 545)
    await ball.move_along(path, time=1.3, ease="ease_in")
    ball.vel = Vec2(420, 0)
    # the reprise: every word lights up again, in order
    await at(t + 14.6)
    for parts in LABELS:
        parts[0].pop(scale=1.35)
        parts[0].line = FROST
        await wait(0.3)
    words = [rise("Events, collisions, timers, processes, formulas.", (640, 690), size=30,
                  color="white")]
    await wait(1.0)
    words.append(note("All simple.", (640, 40), size=30))
    await at(t + 22.2)
    st.mode = None
    leave(words, LABELS, parts, hand, time=0.5)


def machine_motion(dt):
    for d in my.dominoes:
        if d.falling and d.lean < d.limit:
            d.spin += 520 * dt
            turn = min(d.spin * dt, d.limit - d.lean)
            d.rotate_by(-turn, about=d.pivot)
            d.lean += turn
    ball = my.ball
    if ball.vel.x:
        ball.move_by(ball.vel.x * dt, 0)
        if ball.vel.x < 0:
            ball.vel = Vec2(min(0, ball.vel.x + 150 * dt), 0)
    crate = my.crate
    if crate.free:
        crate.vel = Vec2(crate.vel.x, crate.vel.y - 1500 * dt)
        if "bottom" in crate.touching_sides:
            crate.vel = Vec2(crate.vel.x * (1 - 3.2 * dt), crate.vel.y)
        crate.move_by(crate.vel.x * dt, crate.vel.y * dt)


# ---- 1:16  interfaces: widgets and the mouse ----

FLOWER = Vec2(860, 360)
LOOKS = {"Neon": lambda: Neon("gold"), "Flame": Flame, "Metal": Metal,
         "ElectricField": lambda: ElectricField("gold")}


async def interface(t):
    reset_camera()
    Nebula(color="dark cyan", color2="midnight blue", alpha=0.45)
    words = headline("Buttons, sliders, menus · click, drag, hover", y=650, size=28, x=860)
    st.petals, st.spin, st.look, st.trail = 6, 30, "Neon", False
    core = Circle(center=FLOWER, radius=34, color="gold", group="core")
    core.glow = True
    core.draggable = True
    core.fade_in(0.4)
    my.core = core
    my.flower = []
    my.shown = (None, None, None)
    ui.scale = 1.45
    widgets = [Slider(st["petals"], label="Petals", min_value=3, max_value=14),
               Slider(st["spin"], label="Spin", min_value=0, max_value=200),
               DropDown(st["look"], options=list(LOOKS)),
               CheckBox(st["trail"], label="Trail"),
               Button(label="Bloom", on_click=lambda: bloom_out(core))]
    my.widgets = widgets
    my.turn = 0.0
    shown_tags = []

    my.said = (None, -9.0)

    def say(text, at_):
        last, when = my.said
        if text == "@hover" and (last == "@hover" or now() - when < 1.2):
            return              # one hover tag; a click's or a drag's stays to be read
        my.said = (text, now())
        leave(shown_tags, style="fade", time=0.25)
        shown_tags[:] = tag(text, at_, size=18, box=True)

    @hover(group["petals"])
    def lift_petal(p):
        p.scale_to(1.3, time=0.12)
        if t + 7.0 < now() < t + 9.2:       # while the pointer goes round the flower
            say("@hover", (p.center.x, p.center.y + 70))

    @hover_exit(group["petals"])
    def settle(p):
        p.scale_to(1.0, time=0.12)

    @click(core)
    def poke(c):
        c.pop(scale=1.4)
        canvas.zap_at(c, radius=110, color="gold")
        say("@click", (c.center.x, c.center.y - 80))

    st.mode = "flower"
    # the pilot (teaser3_pilots.py) plays the widgets; captions follow the clock
    # (the widget column at ui.scale 1.45: a tag to the right of each widget)
    for when, text, where in ((1.2, "Slider", (470, 661)), (3.0, "Slider", (470, 603)),
                              (4.6, "DropDown", (470, 545)), (6.4, "CheckBox", (470, 494)),
                              (10.4, "draggable", None), (11.8, "Button", (470, 440))):
        await at(t + when)
        if where is None:
            where = (core.center.x, core.center.y - 80)
        say(text, where)
    await at(t + 14.2)
    st.mode = None
    leave(words, shown_tags, my.flower, core, time=0.4)
    await wait(0.4)
    for w in widgets:
        w.destroy()


def bloom_out(core):
    for k, p in enumerate(my.flower):
        canvas.fireworks_at(p.center.x, p.center.y, color=p.color, color2=FROST, radius=60,
                            amount=0.6)
    canvas.ripple_at(core, radius=300, amount=0.6, shake=False)
    knob_to(light, "intensity", 1.3, time=0.3, back=True)


def flower_motion(dt):
    n = int(round(st.petals))
    shown = (n, st.look, st.trail)
    if shown != my.shown:
        for p in my.flower:
            p.destroy()
        my.flower = []
        for k in range(n):
            p = Ellipse(width=34, height=110, color=lerp(EMBER, Color("gold"), k / max(1, n - 1)),
                        group="petals")
            p.visual = LOOKS[st.look]()
            p.k = k
            if st.trail:
                p.tail = Tail(color="gold", size=5)
            my.flower.append(p)
        my.shown = shown
    my.turn += st.spin * dt
    c = my.core.center
    for p in my.flower:
        a = my.turn + p.k * 360 / n
        p.center = (c.x + 95 * cos(a * pi / 180), c.y + 95 * sin(a * pi / 180))
        p.angle = a - 90


# ---- 1:31  the level editor ----

EDITOR_SECONDS = 17.2


async def editor(t):
    reset_camera()
    Stars(color=FROST, density=0.25, twinkle=0.3)
    window = Window((640, 342), 960, 600, color=FROST)
    await window.open()
    # the editor runs at 1280 x 800 (16:10): its picture is the middle of the recording
    window.play("scena-editor/tour", seconds=EDITOR_SECONDS, start=0.0,
                crop=[128, 0, 2304, 1440])
    words = headline("A level editor", y=680, size=30)
    await at(t + 9.0)
    leave(words, time=0.3)
    words = headline("…made with Scena itself", y=680, size=30)
    await at(t + 0.8 + EDITOR_SECONDS)
    leave(words, time=0.3)
    await window.close(time=0.5)


# ---- 1:50  effects: every one has its knobs; and they compose ----

KNOBS = (
    # (name, kind, sliders: (param, low, high, start))
    ("Neon", "a look", (("amount", 0.2, 3.0, 1.0), ("width", 1, 12, 3), ("flicker", 0, 1, 0))),
    ("Borealis", "a background", (("amount", 0.2, 2.0, 1.0), ("speed", 0, 4, 0.9),
                                  ("height", 0.2, 1.0, 0.5))),
    ("GodRays", "a screen effect", (("weight", 0.0, 0.25, 0.04), ("decay", 0.8, 0.99, 0.9),
                                    ("exposure", 0.2, 1.6, 0.8))),
)
STACK = (("look", "Flame"), ("in the world", "Portal"), ("background", "Stardust"),
         ("background", "Borealis"), ("screen", "GodRays"), ("screen", "Chroma"),
         ("impact", "fireworks_at"))


async def effects(t):
    reset_camera()
    words = headline("Every effect has parameters, changed live", y=650, size=30,
                     x=800)          # clear of the slider column
    star = RegularPolygon(n=5, center=(840, 360), radius=100, color="gold")
    star.fade_in(0.4)
    star.rotate_by(360, time=24, loops="forever")
    my.star = star
    my.neon_shown = None
    ui.scale = 1.45
    for k, (name, kind, knobs) in enumerate(KNOBS):
        begin = t + 0.6 + 4.1 * k
        await at(begin)
        for param, low, high, start in knobs:
            setattr(st, param, start)
        sliders = [Slider(st[param], label=param, min_value=low, max_value=high)
                   for param, low, high, start in knobs]
        title_ = rise(name, (250, 420), size=40, color="white")
        count = note(f"{kind} · {len(params_of(name))} parameters", (250, 372), size=20)
        if name == "Neon":
            my.effect = ("Neon", None)
        elif name == "Borealis":
            my.effect = ("Borealis", Borealis(color=ICE, amount=1.0, height=0.5))
        else:
            my.effect = ("GodRays", GodRays(weight=0.04, target=star))
        st.mode = "knobs"
        await at(begin + 3.9)
        st.mode = None
        leave(title_, count, time=0.25)
        for s in sliders:
            s.destroy()
        kind_, handle = my.effect
        if name == "Neon":
            star.visual = None
        elif handle is not None:
            handle.remove()
    # the stack: one layer after another, on the same star
    leave(words, time=0.3)
    words = headline("…and they compose", y=650, size=30)
    chips = []
    on = []
    for k, (layer, name) in enumerate(STACK):
        await at(t + 13.2 + 1.15 * k)
        if name == "Flame":
            star.visual = Flame(amount=1.3)
        elif name == "Portal":
            on.append(Portal(center=(840, 360), radius=190, color=ICE, color2=EMBER))
        elif name == "Stardust":
            on.append(Stardust(color=DEEP, color2=EMBER))
        elif name == "Borealis":
            on.append(Borealis(color=ICE, alpha=0.7))
        elif name == "GodRays":
            on.append(GodRays(weight=0.07, target=star))
        elif name == "Chroma":
            on.append(Chroma(3))
        else:
            for n, (x, y) in enumerate(((700, 560), (980, 540), (860, 180))):
                after(0.2 * n, lambda x=x, y=y: canvas.fireworks_at(
                    x, y, color=EMBER, color2=FROST, radius=120, amount=1.2))
        y = 560 - 62 * k
        chip = [Text(layer, top_left=(90, y + 22), font=NOTE_FONT, font_size=17,
                     color=CAPTION),
                Text(name, top_left=(90, y), font=SMALL_FONT, font_size=26, color="white")]
        plus = Text("+", top_left=(60, y), font=TITLE_FONT, font_size=26, color=EMBER)
        for c in chip + [plus]:
            c.fade_in(0.3)
        chips += chip + [plus]
        if k:
            star.pop(scale=1.08)
    await at(t + 22.0)
    leave(words, time=0.3)
    words = headline("Parametrizable. Composable.", y=650, size=32)
    await at(t + 23.4)
    leave(words, chips, star, time=0.4)
    await wait(0.4)
    for thing in on:
        if isinstance(thing, Portal):
            thing.destroy()         # a thing in the world, not a screen effect
        else:
            thing.remove()


def knob_motion(dt):
    name, handle = my.effect
    if name == "Neon":
        shown = (round(st.amount, 2), round(st.width, 1), round(st.flicker, 2))
        if shown != my.neon_shown:
            my.neon_shown = shown
            my.star.visual = Neon(ICE, amount=shown[0], width=shown[1], flicker=shown[2])
    elif name == "Borealis":
        handle.amount, handle.speed, handle.height = st.amount, st.speed, st.height
    elif name == "GodRays":
        handle.weight, handle.decay, handle.exposure = st.weight, st.decay, st.exposure


# ---- 2:14  games made with Scena ----

WALL = (("race/serpentine", 14.0), ("guardian/waves", 65.5), ("duel/match", 3.0),
        ("ninja_5_espada/full", 21.0), ("connect_four/red_row", 2.0),
        ("naves_6_atos/victory", 6.0), ("aviao_paisagem/flights", 20.0),
        ("corredor/runs_a", 4.0), ("pegar_estrelas/careful", 6.0))


async def games(t):
    reset_camera()
    Stars(color=FROST, density=0.3, twinkle=0.3)
    words = headline("Games made with Scena", y=690, size=28)
    windows = []
    for k in range(9):
        x, y = 240 + (k % 3) * 400, 563 - (k // 3) * 222
        window = Window((x, y), 352, 198, color=[ICE, FROST, EMBER][(k + k // 3) % 3])
        windows.append(window)
        run_task(window.open)
        await wait(0.07)
    await wait(0.85)
    for window, (take, start) in zip(windows, WALL):
        window.play(take, seconds=8.0, start=start)
    await at(t + 9.4)
    leave(words, time=0.3)
    for window in windows[:-1]:
        run_task(window.close)
    await windows[-1].close()


# ---- 2:23  100% made with Scena ----

async def finale(t):
    reset_camera()
    await made_with_scena(note_line="a 33-chapter tutorial · the whole API Guide",
                          music='"The Adventure Begins" by Bart Kelsey (CC BY 3.0)')


# ---- the running order ----

SECTIONS = [
    (0.0, title, False),
    (9.0, stairs, False),
    (24.0, simple, False),
    (37.5, xray, False),
    (53.0, machine, False),
    (76.0, interface, False),
    (91.0, editor, False),
    (110.0, effects, False),
    (135.0, games, False),
    (MUSIC_SECONDS, finale, False),     # the music has just ended: the card is silent
    (MUSIC_SECONDS + 5.5, None, False),
]


def update(dt):
    st.frame += 1
    mode = st.mode
    if mode == "stairs":
        target = Vec2(my.ninja.center.x + CAM_OFF.x, my.ninja.center.y + CAM_OFF.y)
        my.cam = my.cam + (target - my.cam) * min(1.0, 4 * dt)
        canvas.pan_to(my.cam)
    elif mode == "flock":
        flock(dt)
    elif mode == "xray":
        my.place()
    elif mode == "machine":
        machine_motion(dt)
    elif mode == "flower":
        flower_motion(dt)
    elif mode == "knobs":
        knob_motion(dt)


async def show():
    await run_sections(SECTIONS, music=MUSIC, label="teaser3")


run_task(show)
run(Card)
