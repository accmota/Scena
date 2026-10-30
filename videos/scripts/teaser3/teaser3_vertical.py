"""Scena: the third teaser, cut for a phone (720 x 1280 design, 46 s, a Short).

Not the landscape teaser squeezed: its own cut of the same ideas, laid out
upright. A Short is judged in its first second, so it opens on a game in
motion (no black, no slow title); text stays in the middle band (the
Shorts buttons cover the right edge and the bottom fifth).

  0:00  a game, at once       Light Guardian's wave 5, the name over it
  0:06  a vocabulary          a chain-reaction machine that runs downhill
  0:17  effects               knobs under a pointer; then layers, one on another
  0:29  the level editor      select, move, draw, resize, turn
  0:36  games                 six games made with Scena
  0:41  pip install scena     100% made with Scena (the music ends at 46.1 s)

Music: "Adventure Theme" by Cleyton Kauffman (CC0), its first 46.08 s (a
phrase ends there), faded over the last 0.8 s (make_media.py -> hero_short.flac).

Use
---
    python videos/scripts/teaser3/make_media.py --music
    python tools/video/record_game.py videos/scripts/teaser3/teaser3_vertical.py \\
        --pilot videos/scripts/teaser3/teaser3_pilots.py:show_vertical --seconds 46.1 \\
        --size 1080x1920 --prores --out $PWD/videos/recordings/masters.nosync/teaser3_vertical.mov
    python videos/scripts/kit/promo_composite.py \\
        videos/recordings/masters.nosync/teaser3_vertical.mov \\
        videos/recordings/teaser3_vertical/scena_teaser3_vertical.mp4 \\
        videos/recordings/teaser3_vertical/cues.json \\
        --design 720x1280 --start 0.3          # the video starts when the music does
    python videos/scripts/kit/finish.py \\
        videos/recordings/teaser3_vertical/scena_teaser3_vertical.mp4 promo/scena_teaser3_vertical

    TEASER_START=6 python videos/scripts/teaser3/teaser3_vertical.py     # start at a section (no music)
"""

import os
import sys
from functools import partial
from types import SimpleNamespace

from scena import *

init(width=720, height=1280, title="Scena")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "kit"))
from paths import REPO, work               # noqa: E402
from promo_kit import *                      # noqa: E402,F403
from promo_kit import kit                    # noqa: E402

MUSIC = os.path.join(work("teaser3_vertical"), "hero_short.flac")
MUSIC_SECONDS = 46.08
CUES = os.path.join(work("teaser3_vertical"), "cues.json")
START = float(os.environ.get("TEASER_START", "0"))
kit.setup(cues=CUES, width=720, height=1280, start=START)

canvas.background = NIGHT
light = Bloom(intensity=0.6)
Vignette(amount=0.55)

st.mode = None
my = SimpleNamespace()
MID = 360           # the middle of the screen, across


def now():
    """Seconds into the video (here: a formula follows only this file's functions)."""
    return clock.time - st.t0


# A square from the middle of a 2560 x 1440 recording of a 16:9 game.
SQUARE = [560, 0, 1440, 1440]


def open_now(window):
    """A window already open on the first frame (a Short starts in motion)."""
    window.border.end = 1
    window.pane.visible = True
    window.pane.height = window.height


# ---- 0:00  a game at once, the name over it ----

async def hook(t):
    Stars(color=FROST, density=0.35, twinkle=0.4)
    window = Window((MID, 662), 640, 640, color=EMBER, comets=False)   # under the name
    open_now(window)
    window.play("guardian/waves", seconds=6.0, start=63.0, crop=SQUARE)
    row = letters("SCENA", (MID, 1135), size=120)
    for letter in row:
        letter.fill = Gradient("white", FROST, ICE, angle=-90)
    words = [Text("a Python game engine", center=(MID, 1045), font=SMALL_FONT, font_size=34,
                  color=FROST)]
    await at(t + 1.4)
    words.append(note("built for learning", (MID, 292), size=36))
    await at(t + 5.6)
    leave(row, words, time=0.3)
    await window.close(time=0.35)


# ---- 0:06  a machine that runs downhill: each part one word ----

LABELS = []


def label(text, x, y):
    parts = tag(text, (x, y), size=19, box=True)
    parts[0].pop(scale=1.3)
    LABELS.append(parts)
    return parts


async def machine(t):
    LABELS.clear()
    Stars(color=FROST, density=0.2, twinkle=0.3)
    collision.floor = True
    parts = []

    def show(thing, delay=0.0):
        thing.visible = False

        def appear():
            if thing.is_alive:
                thing.visible = True
                thing.fade_in(0.4)

        after(delay, appear)
        parts.append(thing)
        return thing

    path_points = [(60, 1170), (130, 1140), (210, 1080), (270, 1040), (322, 1031)]
    path = Track(points=path_points)
    path.visible = False
    show(Track(points=[(x, y - 15) for x, y in path_points], color=FROST, line_width=3))
    ball = show(Circle(center=path_points[0], radius=14, color=EMBER, group="ball"))
    ball.glow = True
    ball.vel = Vec2(0, 0)
    show(Rect(center=(470, 1011), width=330, height=10, color=FROST.with_alpha(0.8),
              corner_radius=3, group="floor"), 0.1)
    dominoes = []
    for k in range(5):
        d = show(Rect(center=(370 + 42 * k, 1049), width=12, height=66, corner_radius=2,
                      color=ICE, group="dom_a" if k % 2 == 0 else "dom_b"), 0.2 + 0.05 * k)
        d.index, d.falling, d.lean, d.spin, d.limit = k, False, 0.0, 0.0, 34.0
        d.pivot = (370 + 42 * k + 6, 1016)
        dominoes.append(d)
    dominoes[-1].limit = 84.0
    crate = show(Rect(center=(612, 1033), width=34, height=34, corner_radius=4, color=FLARE,
                      group="crate"), 0.4)
    crate.vel = Vec2(0, 0)
    crate.free = False
    show(Rect(center=(560, 650), width=300, height=12, color=FROST.with_alpha(0.8),
              corner_radius=3, group="floor"), 0.4)
    # a wall at the shelf's end: the crate hits it and drops to the floor below
    show(Rect(center=(706, 860), width=8, height=400, color=FROST.with_alpha(0.5),
              corner_radius=3, group="floor"), 0.4)
    plate = show(Rect(center=(PLATE_X, 658), width=70, height=5, color=DEEP, corner_radius=2),
                 0.5)
    group["floor"].mass = STATIC
    dial = show(Circle(center=(560, 820), radius=26, color=PANEL), 0.5)
    dial.line = DEEP
    dial.line_width = 3
    face = Circle(center=(560, 820), radius=26)
    face.visible = False
    hand = Track(face, color=EMBER, line_width=4)
    hand.end = 0
    lamps = [show(Circle(center=(430 + 48 * k, 560), radius=9, color=DEEP), 0.6 + 0.05 * k)
             for k in range(5)]
    for lamp in lamps:
        lamp.glow = True
    # the lift on the left, its weight on a formula
    for x in (98, 202):
        show(Line(p1=(x, 380), p2=(x, 930), color=DEEP.with_alpha(0.7), line_width=2), 0.7)
    lift = show(Rect(center=(150, 400), width=96, height=10, color=FROST, corner_radius=3), 0.8)
    rider = show(Circle(center=lambda: lift.center + (0, 20), radius=15, color=ICE), 0.8)
    rider.glow = True
    weight = show(Rect(center=(40, 900), width=30, height=50, corner_radius=4, color=DEEP), 0.9)
    weight["center"] @= lambda: (40, 1300 - lift.center.y)
    show(Line(p1=(40, 960), p2=lambda: weight.center + (0, 25),
              color=FROST.with_alpha(0.5)), 0.9)
    show(Line(p1=(150, 960), p2=lambda: lift.center + (0, 5), color=FROST.with_alpha(0.5)), 0.9)
    wheel = show(Circle(center=(95, 960), radius=55, color=PANEL), 0.9)
    wheel.line = FROST.with_alpha(0.6)
    wheel.line_width = 2
    my.dominoes, my.crate, my.ball = dominoes, crate, ball
    st.mode = "machine"

    @collide("ball", ["dom_a", "dom_b"])
    def knock(b, d):
        b.vel = Vec2(-60, 0)
        if not d.falling and d.lean == 0:
            label("@collide", 455, 1125)
            d.falling, d.spin = True, 70.0

    @collide("dom_a", "dom_b")
    def topple(a, b):
        first, second = (a, b) if a.index < b.index else (b, a)
        if first.falling and not second.falling and second.lean == 0:
            first.falling = False
            second.falling, second.spin = True, 80.0

    @collide(["dom_a", "dom_b"], "crate")
    def push(d, c):
        if not c.free:
            c.free = True
            c.vel = Vec2(190, 200)       # off the shelf, into the wall

    resolve("crate", "floor", bounce=0.3)

    @when(lambda: crate.free and crate.center.y < 700 and "bottom" in crate.touching_sides)
    def landed():
        label("resolve", 470, 715)

    @when(lambda: crate.free and crate.center.y < 700
          and abs(crate.center.x - plate.center.x) < 40
          and abs(crate.vel.x) < 25 and "bottom" in crate.touching_sides)
    def pressed():
        plate.color = EMBER
        label("@when", 560, 615)
        canvas.hit_at(plate, color=EMBER, radius=40)
        label("after(1.5, …)", 560, 875)
        tween(hand["end"], 1, time=1.5)
        after(1.5, release)
        my.lit = 0

        def blink():
            lamps[my.lit].color = "gold"
            lamps[my.lit].pop(scale=1.5)
            my.lit += 1
            if my.lit == len(lamps):
                my.lamps.cancel()

        my.lamps = every(0.28, blink)
        label("every(0.28, …)", 525, 515)

    def release():
        canvas.zap_at(dial, color=EMBER, radius=60)
        run_task(ride)
        for part in label("@=", 40, weight.center.y):
            off = Vec2(part.center.x - weight.center.x, part.center.y - weight.center.y)
            part["center"] @= lambda off=off: weight.center + off

    async def ride():
        lift.move_to(150, 900, time=1.6, ease="ease_in_out")
        label("until(…)", 250, 400)
        await until(lambda: lift.center.y >= 899)
        canvas.zap_at(rider, color=ICE, radius=60)
        for k, (x, y) in enumerate(((360, 1150), (200, 1080), (540, 1180))):
            after(0.22 * k, lambda x=x, y=y, k=k: canvas.fireworks_at(
                x, y, color=EMBER if k % 2 else ICE, color2=FROST, radius=120, amount=1.2))

    await at(t + 0.7)
    label("move_along", 150, 1060)
    await ball.move_along(path, time=1.0, ease="ease_in")
    ball.vel = Vec2(420, 0)
    await at(t + 8.4)
    words = [rise("Events · collisions · timers", (MID, 330), size=30, color="white"),
             rise("processes · formulas", (MID, 288), size=30, color="white")]
    for parts_ in LABELS:
        parts_[0].pop(scale=1.35)
        parts_[0].line = FROST
        await wait(0.12)
    await at(t + 10.6)
    st.mode = None
    leave(words, LABELS, parts, hand, time=0.4)


PLATE_X = 621       # where the crate comes to rest, after the wall (the plate is put there)


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
        if "right" in crate.touching_sides and crate.vel.x > 0:
            crate.vel = Vec2(-0.15 * crate.vel.x, crate.vel.y)
        crate.move_by(crate.vel.x * dt, crate.vel.y * dt)
        if os.environ.get("CRATE"):
            print(f"[crate] {now():.2f} x={crate.center.x:.1f} y={crate.center.y:.1f} vx={crate.vel.x:.1f}")


# ---- 0:17  effects: knobs, then layers ----

KNOBS = (("amount", 0.2, 3.0, 1.0), ("width", 1, 12, 3), ("flicker", 0, 1, 0))
STACK = ("Flame", "Portal", "Stardust", "Borealis", "GodRays", "fireworks_at")


async def effects(t):
    words = headline("Every effect has parameters", y=1215, size=30)
    star = RegularPolygon(n=5, center=(MID, 640), radius=110, color="gold")
    star.fade_in(0.4)
    star.rotate_by(360, time=24, loops="forever")
    my.star = star
    st.neon_shown = None
    for param, low, high, start in KNOBS:
        setattr(st, param, start)
    ui.scale = 1.5
    # under the headline, across the middle (the HUD column would hide the headline)
    sliders = [Slider(st[param], label=param, min_value=low, max_value=high,
                      top_left=(150, 1110 - 56 * k))
               for k, (param, low, high, start) in enumerate(KNOBS)]
    name = rise("Neon", (MID, 400), size=44, color="white")
    count = note(f"a look · {len(params_of('Neon'))} parameters", (MID, 350), size=24)
    st.mode = "knobs"
    await at(t + 5.0)
    st.mode = None
    leave(name, count, words, time=0.25)
    for s in sliders:
        s.destroy()
    words = headline("…and they compose", y=1215, size=30)
    on, shown = [], []
    for k, layer in enumerate(STACK):
        await at(t + 5.4 + 1.05 * k)
        if layer == "Flame":
            star.visual = Flame(amount=1.3)
        elif layer == "Portal":
            on.append(Portal(center=(MID, 640), radius=200, color=ICE, color2=EMBER))
        elif layer == "Stardust":
            on.append(Stardust(color=DEEP, color2=EMBER))
        elif layer == "Borealis":
            on.append(Borealis(color=ICE, alpha=0.7))
        elif layer == "GodRays":
            on.append(GodRays(weight=0.045, target=star))
        else:
            for n, (x, y) in enumerate(((220, 860), (520, 880), (360, 420))):
                after(0.2 * n, lambda x=x, y=y: canvas.fireworks_at(
                    x, y, color=EMBER, color2=FROST, radius=120, amount=1.2))
        leave(shown, style="fade", time=0.2)
        shown = [Text(f"+ {layer}", center=(MID, 380), font=TITLE_FONT, font_size=40,
                      color="white")]
        shown[0].pop(scale=1.2)
        shown.append(note(f"{k + 1} layer{'s' if k else ''}", (MID, 330), size=22))
        star.pop(scale=1.08)
    await at(t + 11.6)
    leave(words, shown, star, time=0.3)
    await wait(0.35)
    for thing in on:
        if isinstance(thing, Portal):
            thing.destroy()         # a thing in the world, not a screen effect
        else:
            thing.remove()


def knob_motion(dt):
    shown = (round(st.amount, 2), round(st.width, 1), round(st.flicker, 2))
    if shown != st.neon_shown:
        st.neon_shown = shown
        my.star.visual = Neon(ICE, amount=shown[0], width=shown[1], flicker=shown[2])


# ---- 0:29  the level editor ----

async def editor(t):
    Stars(color=FROST, density=0.25, twinkle=0.3)
    window = Window((MID, 680), 640, 640, color=FROST)
    await window.open(time=0.5)
    # the toolbar, the tool column and the left of the canvas: where the tour
    # draws (from the top edge, so the toolbar shows; the status line is cut)
    window.play("scena-editor/tour", seconds=6.4, start=1.6, crop=[128, 0, 1270, 1270])
    words = [rise("A level editor", (MID, 1110), size=40, color="white"),
             note("made with Scena itself", (MID, 300), size=30)]
    await at(t + 6.5)
    leave(words, time=0.3)
    await window.close(time=0.4)


# ---- 0:36  games ----

GAMES = (("race/serpentine", 14.0), ("ninja_5_espada/full", 21.0), ("duel/match", 3.0),
         ("connect_four/red_row", 2.0), ("naves_6_atos/victory", 6.0),
         ("aviao_paisagem/flights", 20.0))


async def games(t):
    Stars(color=FROST, density=0.3, twinkle=0.3)
    words = rise("Games made with Scena", (MID, 1150), size=36, color="white")
    windows = []
    for k in range(6):
        x, y = 190 + (k % 2) * 340, 900 - (k // 2) * 250
        window = Window((x, y), 320, 225, color=[ICE, FROST, EMBER][k % 3], comets=False)
        windows.append(window)
        run_task(partial(window.open, time=0.5))
        await wait(0.06)
    await wait(0.5)
    for window, (take, start) in zip(windows, GAMES):
        # 320 x 225: a slice of the 16:9 frame, a little taller
        window.play(take, seconds=4.0, start=start, crop=[256, 0, 2048, 1440])
    await at(t + 4.7)
    leave(words, time=0.25)
    for window in windows:
        run_task(partial(window.close, time=0.3))


# ---- 0:41  the end ----

async def finale(t):
    await made_with_scena(center=(MID, 720), size=76, lines=("pip install scena",),
                          note_line="a free tutorial · English and Portuguese",
                          music='"Adventure Theme" by Cleyton Kauffman (CC0)',
                          music_at=(MID, 420))


SECTIONS = [
    (0.0, hook, False),
    (6.0, machine, False),
    (17.0, effects, False),
    (29.0, editor, False),
    (36.0, games, False),
    (41.0, finale, False),
    (46.1, None, False),
]


def update(dt):
    st.frame += 1
    if st.mode == "machine":
        machine_motion(dt)
    elif st.mode == "knobs":
        knob_motion(dt)


async def show():
    # no fade into the first act: the Short starts on a moving picture
    await run_sections(SECTIONS, music=MUSIC, fade=0.3, label="teaser3v")


run_task(show)
run(Card)
