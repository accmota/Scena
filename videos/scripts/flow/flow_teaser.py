"""Scena: flow (a ~42 s teaser). No features, no code: the idea in five lines,
and a geometry game that plays itself, in light.

One act, no cuts. The name is born in a ring of light and settles in the
top left corner. A glass grid flies into place (as in life.py) and the Game
of Life blooms on it; then a chain of light (cadeia_de_bolas.py) snakes
through a drifting constellation (constelacao.py) while comets hunt; the
ring opens and geometric foes spiral out of it, the hunters shatter them;
it all ends in a chain reaction that falls into the heart. Every change
lands on an accent of the music (video seconds).

  0:00    a point of light, the name in the ring, the name to the corner
  0:03                                    "Just Python."
  0:04    the grid flies in; a hexagon of glass with a comet on its outline
  0:06                                    "Simple things stay simple."
  0:08    the Game of Life on the grid
  0:11                                    "No complications."
  0:16    the chain, the constellation, the comets
  0:19                                    "Real code. Nothing hidden."
  0:23    the ring opens: foes spiral out, the hunters shatter them
  0:26                                    "Every line says what happens."
  0:29    chain reaction, fireworks, everything falls into the heart
  0:35.6  100% made with Scena (over the music's last bars)

Music: "Space (orchestral)" by lasercheese (CC BY 3.0), from 39.85 s to its
end (make_media.py -> space_cut.wav).

Use
---
    python videos/scripts/flow/make_media.py
    python tools/video/record_game.py videos/scripts/flow/flow_teaser.py --seconds 42.5 \\
        --size 2560x1440 --crf 14 --out $PWD/videos/recordings/flow/scena_flow.mp4
    python videos/scripts/kit/finish.py videos/recordings/flow/scena_flow.mp4 promo/scena_flow
"""

import os
import sys
from math import sin, cos, pi, tau
from random import Random

from scena import *

init(width=1280, height=720, title="Scena")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "kit"))
from paths import REPO, work               # noqa: E402
from promo_kit import *                      # noqa: E402,F403
from promo_kit import kit                    # noqa: E402

MUSIC = os.path.join(work("flow"), "space_cut.wav")
CUES = os.path.join(work("flow"), "cues.json")
kit.setup(cues=CUES)

W, H = 1280, 720
C = Vec2(640, 380)          # the heart of the picture: the ring
CARD = 35.6                 # the end card (the music's last bars)
WHITE = Color("white")
PEARL = Color("peach puff")
rng = Random(7)             # the same video every time

# the colours: life's ages (pale aquamarine to violet), the constellation's sweep
AGE = Colormap.from_colors("aquamarine", "turquoise", "deep sky blue", "royal blue",
                           "medium purple")
SWEEP = Colormap.from_colors("cyan", "medium purple", "hot pink", "orange")
STEPS = 10
SHADES = [Gradient(AGE.get_color(i / (STEPS - 1)).lighter(0.2),
                   AGE.get_color(i / (STEPS - 1)).darker(0.25), type="radial")
          for i in range(STEPS)]

Wallpaper(Gradient("#03050c", "#0c0f24", angle=90))
light = Bloom(intensity=0.7)
Vignette(amount=0.7)

# the ring's colours through the video: (second, colour, second colour)
RING = ((0, FROST, ICE), (8, Color("aquamarine"), Color("royal blue")),
        (16, Color("medium purple"), Color("hot pink")), (23, ICE, Color("orange")),
        (29, Color("hot pink"), Color("gold")), (33, WHITE, PEARL))

st.ring = None
st.skies = []
st.gather = None            # when everything starts falling into the heart
st.loud = 0.0               # the music's level, smoothed (0..1)
st.life = False             # the Game of Life ticks
st.chain = False            # the chain moves
st.coil = None              # when the chain's head leaves its path for a circle round the ring


def now():
    """Seconds into the video (a formula follows only this file's functions)."""
    return clock.time - st.t0


def smooth(u):
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


def ring_colors(t):
    for (t0, a0, b0), (t1, a1, b1) in zip(RING, RING[1:]):
        if t < t1:
            u = smooth((t - t0) / min(2.5, t1 - t0))
            return a0.lerp(a1, u), b0.lerp(b1, u)
    return RING[-1][1], RING[-1][2]


# ---- the sky: one background crossfades into the next ----

def sky(*makers, time=2.0):
    old = st.skies
    st.skies = []
    for make in makers:
        layer = make()
        target = layer.alpha
        layer.alpha = 0.0
        knob_to(layer, "alpha", target, time=time)
        st.skies.append(layer)
    for layer in old:
        knob_to(layer, "alpha", 0.0, time=time)
        after(time + 0.1, layer.remove)


# ---- words: letters set wide, coming in one after another ----

def say(text, hold=2.6, y=96, size=34, tracking=0.32):
    """A line of words on a black plate: letters set wide, coming in one after another."""
    row = [Text(ch, center=(0, y), font=SMALL_FONT, font_size=size, color=WHITE, layer="ui")
           for ch in text]
    gap = size * tracking
    width = sum(t.box.width for t in row) + gap * (len(row) - 1)
    plate = Rect(center=(640, y - size * 0.2), width=width + size * 1.6, height=size * 2.3,
                 corner_radius=size * 0.25, color="black", layer="ui")
    plate.line = None
    plate.move_to_back()
    plate.fade_in(0.4)
    x = 640 - width / 2
    for k, t in enumerate(row):
        t.center = (x + t.box.width / 2, y)
        t.move_to_front()
        x += t.box.width + gap
        t.visible = False
        after(0.15 + k * 0.025, lambda t=t: (setattr(t, "visible", True), t.fade_in(0.6)))
    under = Track(points=[(640 - width / 2, y - size * 0.75), (640 + width / 2, y - size * 0.75)],
                  smooth=0, color=EMBER.with_alpha(0.85), line_width=1.4, layer="ui")
    under.begin = 0.5
    under.end = 0.5
    tween(under["begin"], 0, time=1.4, ease="ease_out")
    tween(under["end"], 1, time=1.4, ease="ease_out")

    def go():
        leave(row, style="fade", time=0.6)
        tween(under["begin"], 0.5, time=0.6, ease="ease_in")
        tween(under["end"], 0.5, time=0.6, ease="ease_in", on_done=under.destroy)
        after(0.4, lambda: leave(plate, style="fade", time=0.5))

    after(hold, go)


# ---- lines that draw themselves; light on outlines ----

def draw_on(track, time, ease="ease_in_out", delay=0.0):
    track.begin = 0
    track.end = 0
    if delay:
        after(delay, lambda: tween(track["end"], 1, time=time, ease=ease))
    else:
        tween(track["end"], 1, time=time, ease=ease)
    return track


def draw_off(track, time, delay=0.0, ease="ease_in_out"):
    track.unlink_all()
    after(delay, lambda: tween(track["begin"], 1, time=time, ease=ease) if track.is_alive
          else None)


def comet(shape, speed, phase=0.0, color=WHITE, length=0.09):
    """One light that runs round a shape's outline: a soft tail and a bright head."""
    runs = []
    for part, alpha, width in ((length, 0.25, 2.0), (length * 0.35, 0.6, 2.8),
                               (0.008, 1.0, 3.6)):
        run = Track(shape, color=color.with_alpha(alpha), line_width=width, layer="top")
        run["end"] @= lambda: (now() * speed + phase) % 1
        run["begin"] @= lambda part=part: (now() * speed + phase - part) % 1
        runs.append(run)
    shape.runs = getattr(shape, "runs", []) + runs
    return runs


# ---- 0:00  a point of light, the name in the ring; the name to the corner ----

def title():
    name = Text("SCENA", center=(C.x, C.y), font=TITLE_FONT, font_size=78, color=WHITE,
                layer="ui")
    name.fill = Gradient("white", FROST, ICE, angle=-90)
    name.visible = False
    after(0.25, lambda: (setattr(name, "visible", True), name.fade_in(1.0)))
    name.scale = 1.08
    name.scale_to(1.0, time=2.2, ease="ease_out")
    tag = Text("a Python game engine – for beginners", center=(C.x, C.y - 66), font=SMALL_FONT,
               font_size=24, color="white", layer="ui")
    # no plate: white over the cyan ring, in a dark halo where it crosses it
    tag.fill_filter = DropShadow(offset=0, sigma=8, color=(0, 0, 0, 1))
    tag.visible = False
    after(0.9, lambda: (setattr(tag, "visible", True), tag.fade_in(1.0)))
    small, tag_small = 0.3, 0.55
    w, h = name.box.width * small, name.box.height * small
    corner = (34 + w / 2, H - 30 - h / 2)
    tw, th = tag.box.width * tag_small, tag.box.height * tag_small
    tag_corner = (34 + tw / 2, corner[1] - h / 2 - 6 - th / 2)

    def settle():
        name.scale_to(small, time=1.3, ease="ease_in_out")
        name.move_to(corner, time=1.3, ease="ease_in_out")
        tag.scale_to(tag_small, time=1.3, ease="ease_in_out")
        tag.move_to(tag_corner, time=1.3, ease="ease_in_out")

    after(2.45, settle)
    st.logo = name
    st.tagline = tag


async def opening(t):
    sky(lambda: Nebuladust(color="midnight blue", color2="dark slate blue", color3="teal",
                           alpha=0.3),
        lambda: Stars(color=FROST, density=0.25, twinkle=0.4), time=2.5)
    canvas.zoom_to(1.3, about=(C.x, C.y))
    canvas.zoom_to(1.0, about=(C.x, C.y), time=7.0, ease="ease_in_out")
    await at(t + 0.15)
    canvas.zap_at(C.x, C.y, color=ICE, radius=220, amount=0.8)
    title()
    ring = Portal(center=C, radius=10, color=FROST, color2=ICE, thickness=0.12, chaos=0.45,
                  glow=0.7)
    tween(ring["radius"], 140, time=1.8, ease="ease_out")
    st.ring = ring
    st.circles = []
    for k, (r, time) in enumerate(((176, 1.6), (194, 2.2))):
        circle = Track.circle(radius=r, center=C, angle=90 + 180 * k,
                              color=FROST.with_alpha(0.45 - 0.15 * k), line_width=1.2)
        st.circles.append(draw_on(circle, time, ease="ease_out"))
    await at(t + 3.0)
    say("Python game programming.", hold=2.4)


# ---- 0:04  the grid flies in (each end on its own clock); a hexagon of glass ----

CELL = 40
COLS, ROWS = W // CELL, H // CELL
GRID = Gradient("deep sky blue", "white", "medium orchid")


def place(r, c):
    return ((c + 0.5) * CELL, (r + 0.5) * CELL)


async def grid(t):
    st.grid = []
    count = max(ROWS, COLS) + 1
    for i in range(count):
        if i <= ROWS:
            line = Line(p1=(0, 0), p2=(0, 0), color=GRID, line_width=1.4)
            line.layer = -1
            tween(line["p1"], (0, i * CELL), time=1.6, ease="ease_in_out")
            tween(line["p2"], (W, i * CELL), time=2.2, ease="ease_in_out")
            st.grid.append(line)
        if i <= COLS:
            line = Line(p1=(0, 0), p2=(0, 0), color=GRID, line_width=1.4)
            line.layer = -1
            tween(line["p1"], (i * CELL, 0), time=2.2, ease="ease_in_out")
            tween(line["p2"], (i * CELL, H), time=1.6, ease="ease_in_out")
            st.grid.append(line)
        if i == 4:
            hexagon = RegularPolygon(n=6, center=C, radius=236, angle=90,
                                     color=ICE.with_alpha(0.05))
            hexagon.line = None
            hexagon.rotate_by(360, time=60, loops="forever")
            hexagon.skin = draw_on(Track(hexagon, color=FROST.with_alpha(0.7), line_width=1.6),
                                   1.8)
            hexagon.fade_in(2.0)
            after(1.8, lambda: comet(hexagon, 0.12))
            after(1.8, lambda: comet(hexagon, 0.12, phase=0.5, color=PEARL))
            st.hexagon = hexagon
        await wait(1.6 / count)
    await at(t + 2.1)
    say("Code that’s short and to the point.", hold=2.8, size=30, tracking=0.24)
    await at(t + 3.2)
    for line in st.grid:          # the light settles
        tween(line["line_width"], 0.8, time=1.0, ease="ease_in_out")


# ---- 0:08  the Game of Life, in glass, on the grid ----

alive = [[False] * COLS for r in range(ROWS)]
age = [[0] * COLS for r in range(ROWS)]
cells = []
SIZE = CELL * 0.78
PERIOD = 0.13


def make_cells():
    for r in range(ROWS):
        row = []
        for c in range(COLS):
            cell = Square(center=place(r, c), length=SIZE, corner_radius=CELL / 4)
            cell.line = None
            cell.visible = False
            row.append(cell)
        cells.append(row)


def born(r, c):
    alive[r][c] = True
    age[r][c] = 0
    cell = cells[r][c]
    cell.fill = SHADES[0]
    cell.visible = True
    cell.length, cell.angle = 0.4 * SIZE, -90
    cell.tween(cell["length"], SIZE, time=4 * PERIOD, ease="ease_in_out", name="size")
    cell.tween(cell["angle"], 0, time=4 * PERIOD, ease="ease_out", name="turn")


def die(r, c, time=2 * PERIOD):
    alive[r][c] = False
    cell = cells[r][c]
    cell.tween(cell["angle"], 90, time=time, ease="ease_in", name="turn")
    cell.tween(cell["length"], 0, time=time, ease="ease_in", name="size",
               on_done=lambda: setattr(cell, "visible", False))


def tick():
    counts = [[sum(alive[(r + dr) % ROWS][(c + dc) % COLS]
                   for dr in (-1, 0, 1) for dc in (-1, 0, 1) if dr or dc)
               for c in range(COLS)] for r in range(ROWS)]
    for r in range(ROWS):
        for c in range(COLS):
            n = counts[r][c]
            if alive[r][c] and n not in (2, 3):
                die(r, c)
            elif not alive[r][c] and n == 3:
                born(r, c)
            elif alive[r][c]:
                age[r][c] += 1
                cells[r][c].fill = SHADES[min(age[r][c] // 3, STEPS - 1)]


async def life(t):
    sky(lambda: Nebuladust(color="midnight blue", color2="dark slate blue", color3="teal",
                           alpha=0.45),
        lambda: Plasma(color="royal blue", speed=0.15, alpha=0.18), time=2.0)
    canvas.ripple_at(C.x, C.y, amount=0.5, radius=360, shake=False)
    knob_to(light, "intensity", 1.2, time=1.5)
    # the ring steps back while the board plays (its two thin circles with it)
    tween(st.ring["amount"], 0.0, time=1.0, ease="ease_in_out")
    for circle in st.circles:
        circle.fade_out(1.0)
    mid_r, mid_c = ROWS // 2, COLS // 2
    for ring in range(max(ROWS, COLS) // 2 + 1):        # a soup from the middle out
        for r in range(ROWS):
            for c in range(COLS):
                if max(abs(r - mid_r), abs(c - mid_c) * ROWS / COLS * 0.9) // 1 == ring:
                    if rng.random() < 0.32:
                        born(r, c)
        await wait(0.035)
    st.life = True
    await at(t + 3.0)
    say("No boilerplate, no ceremony.", hold=2.8)
    await at(t + 6.2)                                    # the board clears from the middle out
    st.life = False
    for ring in range(max(ROWS, COLS)):
        for r in range(ROWS):
            for c in range(COLS):
                if alive[r][c] and max(abs(r - mid_r), abs(c - mid_c)) == ring:
                    die(r, c, time=0.35)
        if ring == 4:                                   # the board empties: the ring returns
            tween(st.ring["amount"], 1.0, time=1.2, ease="ease_in_out")
            for circle in st.circles:
                circle.fade_in(1.2)
            for line in st.grid:                        # and the grid is gone for good
                line.fade_out(1.2)
                after(1.3, line.destroy)
            st.grid = []
        await wait(0.03)
    knob_to(light, "intensity", 0.8, time=1.0)


# ---- 0:16  the chain, the constellation, the comets ----

FIBER = 190                 # a thread longer than this fades away


class Star(Circle, radius=4, group="star"):
    def setup(self):
        self.vel = vec_from_angle(rng.uniform(0, 360), 40)
        self.hunter = None
        self.color = SWEEP.get_color(self.center.x / W)
        tween(self["radius"], rng.uniform(5, 7), time=rng.uniform(0.8, 2), ease="ease_in_out",
              loops="forever", yoyo=True)
        self.fiber = Line(p1=lambda: self.center, p2=self.center)
        self.fiber.blend = "add"

    def on_update(self, dt):
        if st.gather is not None:           # the end: the stars fall into the heart
            self.vel = chase(self.vel, vec_from_angle(heading(self, C), 520), rate=3)
        else:
            danger = group["comet"].nearest(self, within=160)
            if danger:
                self.vel += vec_from_angle(heading(danger, self), 650 * dt)
            self.vel = chase(self.vel, vec_from_angle(self.vel.angle, 40), rate=1.5)
        self.move_by(self.vel.x * dt, self.vel.y * dt)
        if st.gather is None:
            self.confine(canvas.game_view, by="overlap", action="wrap")
        elif distance(self, C) < 30:
            self.fiber.destroy()
            self.destroy()
            return
        other = group["star"].nearest(self, where=lambda o: o is not self)
        near = 1 - distance(self, other) / FIBER if other else 0
        self.fiber.visible = near > 0
        if near > 0:
            self.fiber.p2 = other.center
            self.fiber.color = SWEEP.get_color((self.center.x + other.center.x) / 2 / W) \
                .with_alpha(near)
            self.fiber.line_width = 1 + 2 * near

    def reborn(self):
        self.move_to(rng.uniform(40, W - 40), rng.uniform(40, H - 40))
        self.vel = vec_from_angle(rng.uniform(0, 360), 40)
        self.color = SWEEP.get_color(self.center.x / W)
        self.dissolve_in(0.8)
        self.fiber.dissolve_in(0.8)


class Comet(Circle, radius=10, group="comet"):
    def setup(self):
        self.vel = vec_from_angle(rng.uniform(0, 360), 330)
        self.visual = Neon()
        self.prey = None
        self.leash = Line(p1=lambda: self.center, p2=self.center)
        self.leash.dash = "dash"
        self.trail = Contrail(max_points=40, fade=True, line_width=5)
        self.every(0.02, lambda: self.trail.snapshot(self))
        self.paint(self.color)

    def paint(self, color):
        self.set_color(color)
        self.leash.color = color.with_alpha(0.6)
        self.trail.color = color

    def on_update(self, dt):
        if st.gather is not None:
            self.vel = chase(self.vel, vec_from_angle(heading(self, C), 600), rate=4)
            self.move_by(self.vel.x * dt, self.vel.y * dt)
            self.leash.visible = False
            if distance(self, C) < 60:
                canvas.hit_at(self.center.x, self.center.y, color=self.color, radius=40)
                self.leash.destroy()
                self.trail.destroy()
                self.destroy()
            return
        if self.prey is not None and getattr(self.prey, "hunter", None) is self:
            self.prey.hunter = None
        foes = group["foe"]
        pool = foes if foes.count else group["star"]
        self.prey = pool.nearest(self, where=lambda p: getattr(p, "hunter", None) is None)
        if self.prey is None:
            self.leash.visible = False
            return
        self.prey.hunter = self
        aim = vec_from_angle(heading(self, self.prey), 360)
        self.vel = chase(self.vel, aim, rate=2.6)
        self.move_by(self.vel.x * dt, self.vel.y * dt)
        self.confine(canvas.game_view, action="bounce")
        self.leash.visible = True
        self.leash.p2 = self.prey.center
        self.leash.visual = ElectricBolt() if distance(self, self.prey) < 140 else None

    @collide_with("star")
    def caught(self, star, info):
        canvas.zap_at(star, style="spark", color=star.color)
        self.paint(star.color)
        self.pop(scale=1.6)
        star.reborn()

    @collide_with("foe")
    def shatter(self, foe, info):
        self.pop(scale=1.8)
        self.paint(foe.tint)
        foe.shatter()


BEADS = 26


def make_chain():
    st.beads = []
    head_color, tail_color = EMBER, Color("medium purple")
    before = None
    for i in range(BEADS):
        u = i / (BEADS - 1)
        bead = Circle(center=C, radius=13 - 6 * u, color=head_color.lerp(tail_color, u))
        bead.visual = Halo(style="pulse")
        bead.layer = "top"
        bead.scale = 0
        bead.after(i * 0.03, lambda b=bead: b.scale_to(1, time=0.4, ease="ease_out"))
        if before is not None:
            link = Line(p1=C, p2=C, color=head_color.lerp(tail_color, u).with_alpha(0.35),
                        line_width=2)
            link["p1"] @= before.center
            link["p2"] @= bead.center
            link.blend = "add"
            link.layer = -1
        before = bead
        st.beads.append(bead)


def head_target():
    """Where the chain's head goes: a Lissajous through the arena, then a coil round the ring."""
    a = now()
    x = C.x + 470 * sin(a * 0.83)
    y = C.y + 230 * sin(a * 1.31 + 0.6)
    if st.coil is not None:
        u = smooth((now() - st.coil) / 1.6)
        r = 210 * (1 - smooth((now() - st.coil - 2.4) / 1.2))
        x = x * (1 - u) + (C.x + r * cos(a * 3.2)) * u
        y = y * (1 - u) + (C.y + r * sin(a * 3.2)) * u
    return x, y


def move_chain(dt):
    head = st.beads[0]
    tx, ty = head_target()
    head.move_to(chase(head.center.x, tx, rate=6, dt=dt), chase(head.center.y, ty, rate=6, dt=dt))
    for i in range(1, len(st.beads)):
        bead, ahead = st.beads[i], st.beads[i - 1]
        bead.move_to(chase(bead.center.x, ahead.center.x, rate=14, dt=dt),
                     chase(bead.center.y, ahead.center.y, rate=14, dt=dt))
    # the head eats the stars it meets
    star = group["star"].nearest(head, within=22)
    if star is not None and st.gather is None:
        canvas.hit_at(star.center.x, star.center.y, color=star.color, radius=26)
        head.pop(scale=1.5)
        star.reborn()


async def chain(t):
    sky(lambda: StarFly(color=FROST, speed=0.3, density=0.5, alpha=0.5, center=(C.x, C.y)),
        lambda: Nebuladust(color="dark slate blue", color2="medium violet red",
                           color3="midnight blue", alpha=0.35), time=1.4)
    for line in st.grid:
        line.set_alpha(0.45)
    canvas.zap_at(C.x, C.y, color=Color("hot pink"), radius=260, amount=0.9)
    make_chain()
    st.chain = True
    for k in range(42):
        star = Star(center=(rng.uniform(40, W - 40), rng.uniform(40, H - 40)))
        star.dissolve_in(0.6)
    for k, color in enumerate((WHITE, Color("gold"), Color("aquamarine"))):
        await wait(0.35)
        comet_ = Comet(center=(C.x, C.y), color=color)
        comet_.pop(scale=2.0)
    ring = st.ring
    tween(ring["tilt"], 64, time=2.4, ease="ease_in_out")
    tween(ring["angle"], -25, time=5.0, ease="ease_in_out")
    await at(t + 2.9)
    say("Real code. Nothing hidden.", hold=3.0)
    await at(t + 4.6)
    tween(ring["tilt"], 0, time=2.0, ease="ease_in_out")


# ---- 0:23  the ring opens: foes spiral out; the hunters shatter them ----

FOE_COLORS = (Color("hot pink"), Color("orange"), Color("aquamarine"), Color("medium purple"),
              Color("gold"), ICE)


class Foe(RegularPolygon, group="foe"):
    def setup(self):
        self.hunter = None
        self.spin = rng.choice((-1, 1)) * rng.uniform(90, 200)
        self.born = now()
        self.way = rng.uniform(0, 360)

    def dress(self, color):
        self.tint = color
        self.color = color.with_alpha(0.12)
        self.line = None
        self.skin = Track(self, color=color, line_width=2.2)
        self.skin.visual = Neon(color, width=2.2, amount=0.8)
        self.scale = 0
        self.scale_to(1, time=0.35, ease="ease_out")

    def on_update(self, dt):
        if st.gather is not None:
            return
        age_ = now() - self.born
        r = 140 + 95 * age_
        a = self.way + 55 * age_
        self.move_to(C.x + r * cos(a * pi / 180), C.y + r * sin(a * pi / 180) * 0.78)
        self.rotate_by(self.spin * dt)
        if r > 760:
            self.skin.destroy()
            self.destroy()

    def shatter(self):
        x, y = self.center.x, self.center.y
        canvas.debris_at(x, y, color=self.tint, radius=46, amount=1.1, count=16, dust=True)
        canvas.hit_at(x, y, color=self.tint, radius=38, amount=1.2, style="star")
        self.skin.destroy()
        self.burn_out(0.4)


def spawn_foe(n=None):
    n = n or rng.choice((3, 4, 4, 5, 6))
    foe = Foe(n=n, radius=rng.uniform(15, 22), center=C)
    foe.dress(rng.choice(FOE_COLORS))
    return foe


async def foes(t):
    sky(lambda: Borealis(color=ICE, alpha=0.35, speed=0.5),
        lambda: Stars(color=FROST, density=0.3, twinkle=0.5), time=1.4)
    for line in st.grid:
        line.set_alpha(0.8)
    ring = st.ring
    tween(ring["radius"], 120, time=0.8, ease="ease_out")
    canvas.explosion_at(C.x, C.y, amount=0.9, flash=False, shake=False)
    st.spawning = True
    k = 0
    while now() < t + 5.6:
        spawn_foe()
        if k % 2 == 0:
            spawn_foe()
        if abs(now() - (t + 3.5)) < 0.2 and not getattr(st, "said", False):
            st.said = True
            say("Built for learning: from a few lines to real games.", hold=3.4, size=26, tracking=0.16)
        k += 1
        await wait(0.28)


# ---- 0:29  chain reaction, fireworks; everything falls into the heart ----

async def finale_run(t):
    sky(lambda: Nebula(color="indigo", color2="midnight blue", alpha=0.5, speed=0.1),
        lambda: Stars(color=PEARL, density=0.3, twinkle=0.5), time=1.2)
    canvas.zoom_to(1.08, about=(C.x, C.y), time=3.3, ease="ease_in_out")
    # one last swarm, then a chain reaction from the heart out
    for k in range(10):
        spawn_foe(n=3 + k % 4)
    await wait(0.9)
    alive_ = sorted(list(group["foe"]), key=lambda f: distance(f, C))
    for k, foe in enumerate(alive_):
        if foe.is_alive:
            after(0.045 * k, lambda f=foe: f.shatter() if f.is_alive else None)
    for k in range(3):
        await at(t + 1.2 + k * 0.7)
        x, y = C.x + (-400, 400, 0)[k], C.y + (130, 130, 240)[k]
        canvas.fireworks_at(x, y, color=SWEEP.get_color(k / 2), color2=FROST, radius=170,
                            amount=1.2)
    st.coil = now()
    await at(t + 3.38)                  # the last accent: it all falls into the heart
    st.gather = now()
    canvas.zoom_to(1.0, about=(C.x, C.y), time=2.6, ease="ease_in")
    knob_to(light, "intensity", 1.3, time=2.4)
    for line in st.grid:
        tween(line["line_width"], 0.0, time=2.4, ease="ease_in")
    for circle in st.circles + [st.hexagon.skin]:
        draw_off(circle, 1.6)
    for run in st.hexagon.runs:
        run.fade_out(1.0)
    st.hexagon.fade_out(1.2)
    st.logo.fade_out(1.5)
    st.tagline.fade_out(1.5)
    await wait(1.1)
    tween(st.ring["radius"], 0, time=1.3, ease="ease_in")
    await wait(1.0)
    for bead in st.beads:
        bead.fade_out(0.4)
    spark = GlowSpot(center=C, radius=0, color=WHITE)
    tween(spark["radius"], 90, time=0.5, ease="ease_in")


async def finale(t):
    canvas.reset_view()
    await made_with_scena(music='"Space (orchestral)" by lasercheese (CC BY 3.0)')


def update(dt):
    st.frame += 1
    st.loud += (amp_db(audio.level, floor=-30) - st.loud) * min(1.0, dt * 6)
    if st.ring is not None and st.ring.is_alive:
        st.ring.color, st.ring.color2 = ring_colors(now())
        st.ring.glow = 0.5 + 0.5 * st.loud
    if st.life:
        st.timer = getattr(st, "timer", 0) + dt
        if st.timer >= PERIOD:
            st.timer = 0
            tick()
    if st.chain and st.beads and st.beads[0].is_alive:
        move_chain(dt)


async def show():
    await wait(0.3)         # change_act needs the game running
    st.t0 = clock.time
    make_cells()
    play_sound(MUSIC, volume=0.9)
    for begin, scene in ((0.0, opening), (4.35, grid), (8.54, life), (16.12, chain),
                         (23.19, foes), (29.02, finale_run)):
        await at(begin)
        await scene(begin)
    await at(CARD)
    st.chain = False
    st.ring = None
    st.skies = []
    change_act(Card)
    await finale(CARD)


run_task(show)
run(Card)
