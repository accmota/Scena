"""Scena: salvo (a ~37 s teaser). No features, no code: the idea in a few
lines, and a shooter played as a demo, in three colours (ice for the ship,
amber for the foes, violet for the void) on deep night.

One act, no cuts. The name opens the video, then shrinks to the top of the
screen and stays there. A ship launches; foes pour out of a ring of light
along paths that draw themselves and undraw behind them; the sky changes on
the music's phrases; the ring swallows the screen and a boss of glass waits
inside a tunnel, light running on its outlines, bullets blooming from it in
rings; it falls on the downbeat, and the quiet ending gets a slow loop of
light. Each line at the bottom comes in with its own effect (a beam, sparks,
a shockwave, lightning, a comet frame, a bloom), in glow and shadow.
Everything lands on the music's bars (3.2 s) and beats (0.8 s).

  0:00    SCENA / a Python game engine
  0:06.4  the name to the top; the ship launches; the ring opens; wave 1
  0:09.6  violet filaments; spiral waves                "Just Python"
  0:12.8  over a planet; the ring's crown; a power-up   "Easy to begin, room to grow"
  0:16.0  the lattice; the V squadron; into the ring    "Simple yet powerful"
  0:19.2  the tunnel; the boss                          "Real code. Nothing hidden"
  0:22.4  the boss fight, rings of bullets              "Built for learning. Full tutorial"
  0:25.6  the boss falls; aurora, quiet
  0:28.8  a loop of light                               "Make something beautiful"
  0:32.0  100% made with Scena, the music's credit (the final chord at 35.25)

Music: "Battle in the Winter" by Johan Brodd (CC BY 3.0): its opening to
19.23 s, then from 240.00 s to its end (make_media.py).

Use
---
    python videos/scripts/salvo/make_media.py
    python tools/video/record_game.py videos/scripts/salvo/salvo_teaser.py --seconds 37.6 \\
        --size 2560x1440 --crf 14 --out $PWD/videos/recordings/salvo/scena_salvo.mp4
    python videos/scripts/kit/finish.py videos/recordings/salvo/scena_salvo.mp4 promo/scena_salvo

(The program waits 0.3 s before the music starts, so video time = scene time + 0.3.)
"""

import os
import sys
from math import sin, cos, pi
from random import Random

from scena import *

init(width=1280, height=720, title="Scena")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "kit"))
from paths import work     # noqa: E402
MUSIC = os.path.join(work("salvo"), "winter_cut.wav")

TITLE_FONT = "fonts/Quantico-Bold.ttf"
NOTE_FONT = "fonts/Quantico-Italic.ttf"
SMALL_FONT = "fonts/Quantico-Regular.ttf"

W, H = 1280, 720
BAR = 3.2045
BEAT = BAR / 4
BARS = [0.0, BAR] + [round(6.41 + BAR * k, 3) for k in range(10)]   # 6.41, 9.61, ... 35.25
CARD = BARS[10]             # 32.05: the end card
FINAL = BARS[11]            # 35.25: the piece's last chord
GATE = Vec2(1070, 380)      # the ring the foes come out of
LAIR = Vec2(930, 380)       # where the boss waits, in the tunnel's eye
rng = Random(11)            # the same video every time

# ---- the palette: ice (the ship), amber (the foes), violet (the void) ----

ICE = Color("#8fe6ff")
FROST = Color("#e8fbff")
AMBER = Color("#ffbf66")
PEACH = Color("#ffdcb0")
EMBER = Color("#ff8c5a")
VIOLET = Color("#8d7cff")
DUSK = Color("#3b2f8f")
WHITE = Color("white")

Wallpaper(Gradient("#02030a", "#080b1e", angle=90))
light = Bloom(intensity=0.6)
Vignette(amount=0.65)

st.t0 = 0
st.frame = 0
st.skies = []
st.ship = None
st.firing = False
st.double = False
st.shots = []
st.foes = []
st.bullets = []
st.ring = None
st.boss = None
st.lanterns = []
st.loud = 0.0
st.shot_tick = -1
st.gather = None
st.ship_loop = False
st.dims = []
st.tilt = 0.0


class Pilot:
    """Where the ship steers: a function of nothing, or None for its own weave
    (a plain class: a shape's fields and st hold values, not functions)."""
    aim = None


pilot = Pilot()


class Card(Act):
    """The one act. change_act(Card) sweeps the picture for the end card."""


def now():
    """Seconds into the video (a formula follows only this file's functions)."""
    return clock.time - st.t0


async def at(t):
    await wait(max(0.0, t - now()))


def smooth(u):
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


def knob_to(thing, name, value, time=0.5):
    """Turn thing.name to value over time (a smoothstep): posts and skies are set, not tweened."""
    async def turn():
        start = getattr(thing, name)
        frames = max(1, int(time * 60))
        for n in range(1, frames + 1):
            u = n / frames
            setattr(thing, name, start + (value - start) * u * u * (3 - 2 * u))
            await wait(1 / 60)
    return run_task(turn)


def palette_at(stops, t):
    """A colour that moves through (second, colour) stops, easing between them."""
    for (t0, a), (t1, b) in zip(stops, stops[1:]):
        if t < t1:
            return a.lerp(b, smooth((t - t0) / min(1.6, t1 - t0)))
    return stops[-1][1]


def fx_out(fx, time):
    """A spatial effect has no fade_out: its amount goes to nothing, then it goes."""
    tween(fx["amount"], 0.0, time=time, ease="ease_in", on_done=fx.destroy)


# ---- the sky: one background crossfades into the next ----

def sky(*makers, time=1.6):
    old = list(st.skies)    # a copy: st.skies = [] on an empty list keeps the same list
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


def punch(amount=1.035, about=None, time=0.5):
    """A small zoom on a downbeat, eased back."""
    about = about or (W / 2, H / 2)
    canvas.zoom_to(amount, about=about)
    canvas.zoom_to(1.0, about=about, time=time, ease="ease_out")


def flare(x, y, color, width=900, time=0.9, layer="ui", spot=True):
    """A lens streak: a hairline that opens sideways from a point and fades."""
    streak = Line(p1=(x, y), p2=(x, y), color=color, line_width=2, layer=layer)
    streak.glow = CheapGlow(color, radius=10)
    tween(streak["p1"], (x - width / 2, y), time=time, ease="ease_out")
    tween(streak["p2"], (x + width / 2, y), time=time, ease="ease_out")
    streak.fade_out(time, on_done=streak.destroy)
    if spot:
        fx_out(GlowSpot(center=(x, y), radius=120, color=color, amount=0.9), time)


# ---- lines that draw themselves and undraw ----

def draw_on(track, time, ease="ease_in_out"):
    track.begin = 0
    track.end = 0
    tween(track["end"], 1, time=time, ease=ease)
    return track


DIM_TIME = 1.1


def tend_dims():
    """Lines that sink to a dim after they are drawn: the line and its glow together."""
    keep = []
    for path, color, t0, dim in st.dims:
        if not path.is_alive:
            continue
        u = smooth((now() - t0) / DIM_TIME)
        alpha = 0.6 + (dim - 0.6) * u
        path.color = color.with_alpha(alpha)
        path.glow = CheapGlow(color, radius=6, alpha=round(alpha / 0.6 * 20) / 20)
        keep.append((path, color, t0, dim))
    st.dims = keep


def draw_off(track, time, delay=0.0, ease="ease_in_out"):
    def go():
        if track.is_alive:
            tween(track["begin"], 1, time=time, ease=ease, on_done=track.destroy)
    after(delay, go)


def comet(shape, speed, phase=0.0, color=WHITE, length=0.12, width=1.0, layer="top"):
    """A light that runs round a shape's outline: a soft tail and a bright head."""
    runs = []
    for part, alpha, w in ((length, 0.3, 2.4), (length * 0.35, 0.7, 3.2), (0.012, 1.0, 4.4)):
        run = Track(shape, color=color.with_alpha(alpha), line_width=w * width)
        run.layer = layer
        run["end"] @= lambda: (now() * speed + phase) % 1
        run["begin"] @= lambda part=part: (now() * speed + phase - part) % 1
        runs.append(run)
    return runs


# ---- words at the bottom: letters set wide, each line with its own entrance ----

TEXT_Y = 78


def letters(text, color, y=TEXT_Y, size=44, tracking=0.13):
    row = [Text(ch, center=(0, y), font=TITLE_FONT, font_size=size, color=FROST, layer="ui")
           for ch in text]
    gap = size * tracking
    width = sum(t.box.width for t in row) + gap * (len(row) - 1)
    x = W / 2 - width / 2
    for t in row:
        t.home = Vec2(x + t.box.width / 2, y)
        t.center = t.home
        x += t.box.width + gap
        # solid ink: a Gradient-filled Text draws its glyph from the box's
        # top-left corner, which breaks a row of single letters
        t.color = FROST.lerp(color, 0.15)
        t.glow = Glow(color, radius=16, amount=0.9)
        t.fill_filter = DropShadow(offset=5, sigma=5)
        t.visible = False
    return row


def span(row):
    return row[0].box.left, row[-1].box.right


def show(t, time=0.25):
    if t.is_alive:
        t.visible = True
        t.fade_in(time)


def enter_beam(row, color):
    """A beam of light sweeps across; each letter lights as it passes."""
    left, right = span(row)
    sweep = 0.8
    beam = Line(p1=(left - 40, TEXT_Y - 40), p2=(left - 40, TEXT_Y + 40), color=WHITE,
                line_width=4, layer="ui")
    beam.glow = CheapGlow(color, radius=16)
    beam.move_by(right - left + 80, 0, time=sweep, ease="ease_in_out")
    halo = GlowSpot(center=lambda: beam.center, radius=90, color=color, amount=1.0)
    after(sweep, lambda: (beam.fade_out(0.3, on_done=beam.destroy), fx_out(halo, 0.3)))
    for t in row:
        u = (t.home.x - left + 40) / (right - left + 80)
        # the beam's x follows ease_in_out: find when it reaches the letter
        lo, hi = 0.0, 1.0
        for _ in range(20):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if smooth(mid) < u else (lo, mid)
        after(sweep * lo, lambda t=t: (show(t, 0.12), t.pop(scale=1.3)))
    return []


def enter_sparks(row, color):
    """Letters drop in one after another; each lands with a spark."""
    for i, t in enumerate(row):
        t.center = (t.home.x, t.home.y + 50)

        def land(t=t):
            if not t.is_alive:
                return
            show(t, 0.2)
            t.move_to(t.home, time=0.26, ease="ease_in")
            if t.text.strip():
                after(0.26, lambda: canvas.zap_at(t.home.x, t.home.y - 18, color=color,
                                                  radius=30, amount=0.7, count=6))
        after(i * 0.045, land)
    return []


def enter_shock(row, color):
    """The line arrives at once; a shockwave and two rings go out from it."""
    left, right = span(row)
    cx = (left + right) / 2
    for t in row:
        t.scale = 1.8
        show(t, 0.18)
        t.scale_to(1.0, time=0.45, ease="ease_out")
    canvas.ripple_at(cx, TEXT_Y, amount=0.8, radius=340, shake=False)
    for k, (r, time) in enumerate(((420, 1.0), (300, 0.8))):
        ring = Track.circle(radius=24, center=(cx, TEXT_Y), color=color, line_width=2.5 - k)
        ring.layer = "ui"
        ring.glow = CheapGlow(color, radius=8)
        tween(ring["radius"], r, time=time, ease="ease_out")
        ring.fade_out(time, on_done=ring.destroy)
    return []


def enter_lightning(row, color):
    """Lightning runs along a line under the words and wakes them, left to right."""
    left, right = span(row)
    under = Track(points=[(left - 14, TEXT_Y - 32), (right + 14, TEXT_Y - 32)], smooth=0,
                  color=color, line_width=3, layer="ui")
    under.visual = ElectricBolt(color)
    draw_on(under, 0.6, ease="ease_out")
    canvas.zap_at(left - 14, TEXT_Y - 32, color=color, radius=40, amount=0.8, count=8)
    after(0.6, lambda: canvas.zap_at(right + 14, TEXT_Y - 32, color=color, radius=40,
                                     amount=0.8, count=8))
    for i, t in enumerate(row):
        after(0.6 * (t.home.x - left) / (right - left), lambda t=t: show(t, 0.12))
        after(0.75 + 0.04 * i, lambda t=t: t.pulse_outline(0.3, color=color)
              if t.is_alive else None)
    return [under]


def enter_frame(row, color):
    """A frame draws round the line; two comets run on it."""
    left, right = span(row)
    for i, t in enumerate(row):
        after(0.02 * i, lambda t=t: show(t, 0.5))
    frame = Rect(center=((left + right) / 2, TEXT_Y + 2), width=right - left + 70, height=74,
                 corner_radius=37, layer="ui")
    frame.color = color.with_alpha(0.06)
    frame.line = None
    skin = Track(frame, color=color.with_alpha(0.4), line_width=1.4, layer="ui")
    draw_on(skin, 0.8)
    runs = []
    for phase in (0.0, 0.5):
        runs += comet(frame, 0.4, phase=phase, color=color, length=0.2, width=0.8, layer="ui")
    return [frame, skin] + runs


def enter_bloom(row, color):
    """Letters bloom from the middle out, large and soft, then settle."""
    mid = (len(row) - 1) / 2
    for i, t in enumerate(row):
        t.scale = 2.4

        def bloom(t=t):
            if t.is_alive:
                show(t, 0.6)
                t.scale_to(1.0, time=0.9, ease="ease_out")
        after(abs(i - mid) * 0.05, bloom)
    left, right = span(row)
    spot = GlowSpot(center=((left + right) / 2, TEXT_Y), radius=40, color=color, amount=0.3)
    tween(spot["radius"], 240, time=1.4, ease="ease_out")
    after(0.6, lambda: fx_out(spot, 1.2))
    return []


def say(text, enter, color, hold, leave="noise", size=44, tracking=0.13):
    row = letters(text, color, size=size, tracking=tracking)
    extras = enter(row, color)

    def go():
        for t in row:
            if not t.is_alive:
                continue
            if leave == "fall":
                t.move_by(0, -40, time=0.5, ease="ease_in")
                t.fade_out(0.5, on_done=t.destroy)
            elif leave == "burn":
                t.burn_out(0.6, on_done=t.destroy)
            elif leave == "fade":
                t.fade_out(0.6, on_done=t.destroy)
            else:
                t.dissolve_out(0.6, style=leave, on_done=t.destroy)
        for thing in extras:
            if thing.is_alive:
                thing.fade_out(0.5, on_done=thing.destroy)

    after(hold, go)
    return row


# ---- the ship: glass, a neon skin, a light running round it, a jet ----

SHIP = [(46, 0), (14, 8), (-4, 26), (-18, 25), (-10, 9), (-22, 0), (-10, -9), (-18, -25),
        (-4, -26), (14, -8)]


class Ship(Polygon):
    def setup(self):
        self.color = ICE.with_alpha(0.2)
        self.line = None
        self.skin = Track(self, color=ICE, line_width=2.2)
        self.skin.visual = Neon(ICE, width=2.2, amount=1.0)
        self.runs = comet(self, 0.8, color=WHITE, length=0.18, width=0.8)
        self.jet = Jet(origin=lambda: self.rear(), angle=180, length=70, width=16, color=ICE)
        self.jet["angle"] @= lambda: self.angle + 180
        self.trail = Contrail(max_points=40, fade=True, line_width=5, color=ICE.with_alpha(0.5))
        self.every(0.02, lambda: self.trail.snapshot(self.rear()))
        self.vy = 0.0

    def nose(self):
        return self.center + vec_from_angle(self.angle, 42)

    def rear(self):
        return self.center - vec_from_angle(self.angle, 24)

    def steer(self, dt):
        t = now()
        if pilot.aim is not None:
            tx, ty = pilot.aim()
        else:
            tx = 300 + 80 * sin(t * 0.61)
            ty = 380 + 160 * sin(t * 0.93) * (0.7 + 0.3 * sin(t * 0.37))
        x = chase(self.center.x, tx, rate=3.0, dt=dt)
        y = chase(self.center.y, ty, rate=3.0, dt=dt)
        self.vy = (y - self.center.y) / max(dt, 1e-6)
        self.move_to(x, y)


def ship_at(x, y):
    return Ship(points=[(x + px, y + py) for px, py in SHIP])


# ---- the foes: glass polygons with a skin of light ----

class Foe(RegularPolygon):
    def dress(self, color, look="neon", hp=1):
        self.tint = color
        self.hp = hp
        self.color = color.with_alpha(0.2)
        self.line = None
        self.skin = Track(self, color=color, line_width=2.4)
        if look == "tracer":
            self.skin.visual = Tracer(color, speed=1.4)
        else:
            self.skin.visual = Neon(color, width=2.4, amount=0.9)
        self.spin = rng.choice((-1, 1)) * rng.uniform(120, 240)
        self.scale = 0
        self.scale_to(1, time=0.3, ease="ease_out")
        st.foes.append(self)
        return self

    def on_update(self, dt):
        self.rotate_by(self.spin * dt)

    def hit(self, power=1):
        self.hp -= power
        if self.hp <= 0:
            self.explode()
        else:
            self.pop(scale=1.25)
            canvas.hit_at(self.center.x, self.center.y, color=FROST, radius=20)

    def explode(self):
        if self in st.foes:
            st.foes.remove(self)
        x, y = self.center.x, self.center.y
        kind = rng.random()
        if kind < 0.45:
            canvas.debris_at(x, y, color=self.tint, radius=46, amount=1.0, count=12, dust=True)
            canvas.hit_at(x, y, color=PEACH, radius=30)
        elif kind < 0.8:
            canvas.burst_at(x, y, radius=54, amount=0.9, rings=True)
            canvas.hit_at(x, y, color=self.tint, radius=38)
        else:
            canvas.zap_at(x, y, color=self.tint, radius=56, amount=0.9, count=10)
        self.skin.destroy()
        self.burn_out(0.35, on_done=self.destroy)

    def leave(self):
        if self in st.foes:
            st.foes.remove(self)
        self.skin.destroy()
        self.destroy()


def wave_along(pts, count, color, n=4, radius=22, gap=0.28, time=2.6, look="neon",
               draw=0.7, smooth_=1, linger=0.55, dim=None):
    """count foes ride a path that draws itself first and undraws behind the last.

    dim: the alpha the line sinks to once it is drawn (None keeps it bright).
    """
    start = pts[0]
    path = Track(points=pts, smooth=smooth_, color=color.with_alpha(0.6), line_width=1.6)
    path.glow = CheapGlow(color, radius=6)
    draw_on(path, draw, ease="ease_out")
    if dim is not None:
        st.dims.append((path, color, now() + draw, dim))

    def launch(k):
        foe = Foe(n=n, radius=radius, center=start).dress(color, look)
        foe.move_along(path, time=time, ease="linear",
                       on_done=lambda: foe.leave() if foe.is_alive and foe in st.foes else None)

    for k in range(count):
        after(draw * 0.5 + k * gap, lambda k=k: launch(k))
    draw_off(path, 0.9, delay=draw * 0.5 + (count - 1) * gap + time * linger)
    return path


# ---- shots: short beams that fly to a foe; bullets the foes send back ----

def fire():
    ship = st.ship
    targets = [f for f in st.foes if f.is_alive and f.center.x > ship.center.x + 40]
    if st.boss is not None and st.boss.is_alive and st.boss.open:
        targets.append(st.boss)
    if not targets:
        return
    nose = ship.nose()
    target = min(targets, key=lambda f: (f.center.x - nose.x) ** 2 + 2 * (f.center.y - nose.y) ** 2)
    for dy in ((-11, 11) if st.double else (0,)):
        shot = Line(p1=(nose.x - 34, nose.y + dy), p2=(nose.x, nose.y + dy), color=FROST,
                    line_width=3.5)
        shot.glow = CheapGlow(ICE, radius=9)
        shot.target = target
        shot.vel = Vec2(1700, 0)
        st.shots.append(shot)


def fly_shots(dt):
    for shot in list(st.shots):
        if not shot.is_alive:
            st.shots.remove(shot)
            continue
        head = shot.p2
        target = shot.target
        if target is not None and target.is_alive:
            want = vec_from_angle(heading(head, target.center), 1700)
            shot.vel = Vec2(chase(shot.vel.x, want.x, rate=14, dt=dt),
                            chase(shot.vel.y, want.y, rate=14, dt=dt))
            if distance(head, target.center) < getattr(target, "reach", 22):
                st.shots.remove(shot)
                shot.destroy()
                target.hit()
                continue
        shot.p2 = Vec2(head.x + shot.vel.x * dt, head.y + shot.vel.y * dt)
        back = vec_from_angle(shot.vel.angle, 34)
        shot.p1 = Vec2(shot.p2.x - back.x, shot.p2.y - back.y)
        if not (-60 < head.x < W + 60 and -60 < head.y < H + 60):
            st.shots.remove(shot)
            shot.destroy()


def bullet(x, y, angle, speed, color):
    b = Circle(center=(x, y), radius=5, color=color.lerp(WHITE, 0.5))
    b.line = None
    b.glow = CheapGlow(color, radius=10)
    b.vel = vec_from_angle(angle, speed)
    st.bullets.append(b)


def fly_bullets(dt):
    for b in list(st.bullets):
        if not b.is_alive:
            st.bullets.remove(b)
            continue
        b.move_by(b.vel.x * dt, b.vel.y * dt)
        if not (-40 < b.center.x < W + 40 and -40 < b.center.y < H + 40):
            st.bullets.remove(b)
            b.destroy()


def foe_fires():
    """On a beat, one foe ahead of the ship sends a bullet its way."""
    ship = st.ship
    shooters = [f for f in st.foes if f.is_alive and f.center.x > ship.center.x + 260]
    if shooters and ship is not None:
        f = rng.choice(shooters)
        angle = heading(f.center, ship.center) + rng.uniform(-14, 14)
        bullet(f.center.x, f.center.y, angle, 330, AMBER)


# ---- lanterns: small lights afloat, changing colour; and the ring ----

RING_COLORS = ((0, VIOLET, ICE), (9.6, ICE, VIOLET), (12.8, AMBER, VIOLET), (16.0, VIOLET, PEACH),
               (18.4, FROST, VIOLET))
LANTERN_COLORS = ((0, VIOLET), (9.6, ICE), (12.8, AMBER), (16.0, VIOLET), (19.2, ICE),
                  (22.4, AMBER), (25.6, ICE), (28.8, PEACH))


def make_lanterns():
    for k in range(4):
        x0 = 200 + k * 280 + rng.uniform(-40, 40)
        y0 = rng.choice((205, 560)) + rng.uniform(-20, 20)
        ph = rng.uniform(0, 6.28)

        def where(x0=x0, y0=y0, ph=ph, k=k):
            t = now()
            x, y = x0 + 70 * sin(t * 0.23 + ph), y0 + 30 * sin(t * 0.41 + ph)
            if st.gather is not None:           # the quiet end: they come round the loop
                u = smooth((t - st.gather) / 3.0)
                a = ph + t * 0.5 + k * pi / 2
                gx, gy = 800 + 230 * cos(a), 380 + 140 * sin(a)
                x, y = x + (gx - x) * u, y + (gy - y) * u
            return x, y

        halo = GlowSpot(center=where, radius=0, color=VIOLET, amount=0.45)
        core = Orb(center=where, radius=6, color=VIOLET, glow=2.4, amount=1.0)
        core.layer = -1
        halo.layer = -1
        tween(halo["radius"], 60, time=1.4, ease="ease_out")
        st.lanterns.append((halo, core, k * 0.7))


def tend_lanterns():
    t = now()
    for halo, core, lag in st.lanterns:
        if halo.is_alive:
            color = palette_at(LANTERN_COLORS, t - lag)
            halo.color = color
            core.color = color.lerp(WHITE, 0.4)
            halo.amount = 0.35 + 0.5 * st.loud


def ring_colors(t):
    for (t0, a0, b0), (t1, a1, b1) in zip(RING_COLORS, RING_COLORS[1:]):
        if t < t1:
            u = smooth((t - t0) / min(1.6, t1 - t0))
            return a0.lerp(a1, u), b0.lerp(b1, u)
    return RING_COLORS[-1][1], RING_COLORS[-1][2]


# ---- 0:00  the name ----

async def title(t):
    sky(lambda: Nebuladust(color="midnight blue", color2=DUSK, color3="#0b3a4a", alpha=0.55),
        lambda: Stars(color=FROST, density=0.3, twinkle=0.5), time=1.2)
    logo = Text("SCENA", center=(W / 2, 410), font=TITLE_FONT, font_size=132, color=WHITE,
                layer="ui")
    logo.fill = Gradient(WHITE, FROST, ICE, angle=-90)
    logo.glow = Glow(ICE, radius=22, amount=0.8)
    logo.fill_filter = DropShadow(offset=7, sigma=8)
    logo.visible = False
    logo.scale = 1.12
    after(0.05, lambda: (setattr(logo, "visible", True), logo.fade_in(1.2)))
    logo.scale_to(1.0, time=3.0, ease="ease_out")
    st.logo = logo
    flare(W / 2, 410, ICE, width=1100, time=1.4)
    box = logo.box
    y = box.bottom - 14
    under = Track(points=[(box.left, y), (box.right, y)], smooth=0, color=AMBER, line_width=2,
                  layer="ui")
    under.glow = CheapGlow(AMBER, radius=6)
    under.begin = 0.5
    under.end = 0.5
    after(0.6, lambda: (tween(under["begin"], 0, time=1.2, ease="ease_out"),
                        tween(under["end"], 1, time=1.2, ease="ease_out")))
    st.under = under
    await at(t + 1.5)
    sub = Text("a Python game engine", center=(W / 2, 286), font=NOTE_FONT, font_size=38,
               color=FROST, layer="ui")
    sub.glow = Glow(VIOLET, radius=14, amount=0.8)
    sub.fill_filter = DropShadow(offset=4, sigma=4)
    sub.fade_in(0.9)
    sub.move_to((W / 2, 300), time=0.9, ease="ease_out")
    st.sub = sub
    await at(BARS[1])
    flare(W / 2, y, AMBER, width=800, time=1.2)
    spot = GlowSpot(center=(W / 2, 410), radius=0, color=DUSK, amount=0.8)
    tween(spot["radius"], 440, time=3.0, ease="ease_in_out")
    st.title_spot = spot


# ---- 0:06.4  the name to the top; launch; the ring; wave 1 ----

def settle_logo():
    logo = st.logo
    logo.scale_to(0.34, time=0.9, ease="ease_in_out")
    logo.move_to((W / 2, H - 38), time=0.9, ease="ease_in_out")
    st.sub.dissolve_out(0.5, style="noise", on_done=st.sub.destroy)
    tween(st.under["begin"], 0.5, time=0.5, ease="ease_in")
    tween(st.under["end"], 0.5, time=0.5, ease="ease_in", on_done=st.under.destroy)
    fx_out(st.title_spot, 0.8)
    tag = Text("Python game engine", center=(W / 2, H - 70),
               font=NOTE_FONT, font_size=17, color=FROST.lerp(ICE, 0.3), layer="ui")
    tag.glow = Glow(VIOLET, radius=8, amount=0.6)
    tag.fill_filter = DropShadow(offset=2, sigma=2)
    tag.visible = False
    after(0.7, lambda: (setattr(tag, "visible", True), tag.fade_in(0.8)))
    st.tag = tag


def open_ring():
    ring = Portal(center=GATE, radius=4, color=VIOLET, color2=ICE, thickness=0.18, chaos=0.5,
                  tilt=52, angle=0, glow=0.9)
    tween(ring["radius"], 96, time=0.9, ease="ease_out")
    canvas.zap_at(GATE.x, GATE.y, color=VIOLET, radius=180, amount=0.9)
    st.ring = ring


async def launch(t):
    settle_logo()
    punch(1.05, time=0.7)
    sky(lambda: StarFly(color=FROST, speed=0.6, density=0.6, alpha=0.7, center=(GATE.x, GATE.y)),
        lambda: Nebuladust(color="midnight blue", color2=DUSK, color3="#0b3a4a", alpha=0.35),
        lambda: WindStreaks(color=ICE, density=0.35, length=0.6, angle=180, speed=1.4,
                            alpha=0.35), time=0.9)
    ship = ship_at(-90, 380)
    st.ship = ship
    ship.move_to(270, 380, time=0.7, ease="ease_out")
    after(0.7, lambda: flare(330, 380, ICE, width=500, time=0.6, layer="default"))
    await at(t + 0.5)
    open_ring()
    make_lanterns()
    await at(t + 0.85)
    st.firing = True
    pts = [(GATE.x, GATE.y), (900, 560), (640, 600), (430, 470), (560, 260), (860, 170),
           (1060, 300), (1340, 420)]
    wave_along(pts, 7, AMBER, n=4, radius=21, gap=0.24, time=3.0, linger=0.3, dim=0.22)


# ---- 0:09.6  violet filaments; spirals ----

async def spirals(t):
    punch()
    say("Just Python", enter_beam, ICE, hold=2.7, leave="noise")
    sky(lambda: FilamentField(color=VIOLET, amount=0.9, speed=0.3, alpha=0.5),
        lambda: StarFly(color=FROST, speed=0.6, density=0.5, alpha=0.6, center=(GATE.x, GATE.y)),
        time=1.4)
    moon = Orb(center=(1010, 600), radius=30, color=FROST, glow=0.6, phase=0.62, amount=0.7)
    moon.layer = -1
    tween(moon["center"], (760, 616), time=16, ease="linear")
    for k, sign in enumerate((1, -1)):
        pts = []
        for i in range(40):
            u = i / 39
            a = sign * (u * 1.6 * 360) + (0 if sign > 0 else 180)
            r = 30 + 330 * u
            pts.append((GATE.x - u * 520 + r * cos(a * pi / 180) * 0.8,
                        GATE.y + r * sin(a * pi / 180) * 0.6))
        pts.append((-80, GATE.y + sign * 140))
        after(k * 0.4, lambda pts=pts, k=k: wave_along(
            pts, 5, PEACH if k else AMBER, n=6, radius=19, gap=0.26,
            time=3.4, look="tracer", draw=0.9, linger=0.3, dim=0.22))


# ---- 0:12.8  over a planet; the ring's crown; the ship powers up ----

async def swarm(t):
    punch(1.04)
    sky(lambda: PlanetFly(color="#6fb8d8", space="#04060d", speed=0.5, bright=1.4, relief=1.2,
                          fog=0.3, alpha=0.9),
        lambda: Stars(color=FROST, density=0.25, twinkle=0.4),
        lambda: WindStreaks(color=ICE, density=0.3, length=0.7, angle=180, speed=1.8,
                            alpha=0.3), time=1.4)
    say("Easy to begin, room to grow", enter_sparks, AMBER, hold=2.7, leave="burn")
    crown = []
    for k in range(10):
        a = k * 36
        foe = Foe(n=3, radius=17, center=(GATE.x + 150 * cos(a * pi / 180),
                                         GATE.y + 105 * sin(a * pi / 180))).dress(EMBER)
        foe.a0 = a
        crown.append(foe)
    st.crown = crown
    st.crown_t = now()
    st.crown_peel = None
    t_core = now()

    def drift():
        u = smooth((now() - t_core) / 1.2)
        return 900 - 340 * u, 220 + 80 * u

    core = GlowSpot(center=drift, radius=44, color=ICE, amount=1.0)
    gem = Orb(center=drift, radius=8, color=FROST, glow=2.0)
    await at(t + 1.2)
    pilot.aim = lambda: (core.center.x - 40, core.center.y)
    await at(t + 1.7)
    pilot.aim = None
    canvas.zap_at(core.center.x, core.center.y, color=ICE, radius=140, amount=1.0, count=14)
    core.destroy()
    gem.destroy()
    st.ship.pop(scale=1.4)
    halo = Track.circle(radius=24, center=st.ship.center, color=ICE, line_width=3)
    halo.glow = CheapGlow(ICE, radius=8)
    tween(halo["radius"], 190, time=0.7, ease="ease_out")
    halo.fade_out(0.7, on_done=halo.destroy)
    st.double = True
    st.ship.skin.visual = ElectricBolt(ICE)
    await at(t + 2.0)
    st.crown_peel = now()


def tend_crown(dt):
    crown = getattr(st, "crown", None)
    if not crown:
        return
    t = now() - st.crown_t
    for i, foe in enumerate(crown):
        if not foe.is_alive or foe not in st.foes:
            continue
        a = (foe.a0 + 80 * t) * pi / 180
        x, y = GATE.x + 150 * cos(a), GATE.y + 105 * sin(a)
        if st.crown_peel is not None:
            u = smooth((now() - st.crown_peel - i * 0.08) / 1.6)
            x = x * (1 - u) + (st.ship.center.x + 220 + 40 * i) * u
            y = y * (1 - u) + (st.ship.center.y + 70 * sin(i)) * u
        foe.move_to(chase(foe.center.x, x, rate=8, dt=dt), chase(foe.center.y, y, rate=8, dt=dt))


# ---- 0:16.0  the lattice; the V squadron; into the ring ----

async def squadron(t):
    punch()
    say("Simple yet powerful", enter_shock, VIOLET, hold=2.5, leave="fall")
    sky(lambda: Lattice(color=ICE, alpha=0.45),
        lambda: Nebuladust(color="midnight blue", color2=DUSK, color3="#0b3a4a", alpha=0.4),
        lambda: StarFly(color=FROST, speed=0.9, density=0.6, alpha=0.6, center=(GATE.x, GATE.y)),
        time=1.2)
    for k in range(7):
        row = k - 3
        y = 380 + row * 56
        start = (1340 + abs(row) * 70, y)
        pts = [start, (1000 - abs(row) * 40, y), (520 - abs(row) * 30, y + row * 26),
               (-80, y + row * 70)]
        after(0.15 * abs(row), lambda pts=pts: wave_along(
            pts, 1, AMBER, n=4, radius=21, gap=0.2, time=2.4, draw=0.5, linger=0.15))
    await at(t + 2.2)
    # the ring opens until it swallows the screen
    st.firing = False
    pilot.aim = lambda: (520, 380)
    ring = st.ring
    tween(ring["tilt"], 0, time=1.0, ease="ease_in_out")
    tween(ring["center"], (W / 2, H / 2), time=1.0, ease="ease_in_out")
    tween(ring["radius"], 900, time=1.0, ease="ease_in")
    knob_to(light, "intensity", 1.3, time=1.0)


# ---- 0:19.2  the tunnel; the boss ----

class Boss(RegularPolygon):
    def setup(self):
        self.tint = VIOLET
        self.open = False
        self.reach = 90
        self.color = VIOLET.with_alpha(0.14)
        self.line = None
        self.skin = Track(self, color=VIOLET, line_width=2.8)
        self.skin.visual = Neon(VIOLET, width=2.8, amount=1.0)
        self.runs = comet(self, 0.45, color=FROST, length=0.16, width=1.2) + \
            comet(self, 0.45, phase=0.5, color=AMBER, length=0.16, width=1.2)
        # an outer hexagon of running dashes turns the other way
        self.shell = RegularPolygon(n=6, center=self.center, radius=self.radius * 1.32, angle=0)
        self.shell.color = VIOLET.with_alpha(0.0)
        self.shell.line = None
        self.shell_skin = Track(self.shell, color=ICE, line_width=1.6)
        self.shell_skin.visual = Tracer(ICE, speed=1.0)
        self.heart = Triangle(center=self.center, radius=48, angle=90)
        self.heart.color = AMBER.with_alpha(0.18)
        self.heart.line = None
        self.heart_skin = Track(self.heart, color=AMBER, line_width=2.2)
        self.heart_skin.visual = Neon(AMBER, width=2.2, amount=0.9)
        self.core = Sparks(center=lambda: self.center, radius=24, rate=50, color=AMBER)
        self.rotate_by(360, time=14, loops="forever")
        self.shell.rotate_by(-360, time=20, loops="forever")
        self.heart.rotate_by(-360, time=6, loops="forever")
        self.looks = 0

    def on_update(self, dt):
        if self.heart:
            self.heart.center = self.center
        if self.shell:
            self.shell.center = self.center

    def hit(self, power=1):
        canvas.hit_at(self.center.x - 80, self.center.y + rng.uniform(-50, 50), color=FROST,
                      radius=28)

    def next_look(self):
        self.looks += 1
        self.skin.visual = (Neon(VIOLET, width=2.8, amount=1.0), ElectricBolt(VIOLET),
                            Neon(PEACH, width=2.8, amount=0.9), Bolt(VIOLET))[self.looks % 4]

    def bloom(self, k):
        """A ring of bullets, turned a little more each time."""
        x, y = self.center.x, self.center.y
        color = AMBER if k % 2 else VIOLET.lerp(WHITE, 0.25)
        for i in range(12):
            bullet(x, y, k * 11 + i * 30, 250, color)
        ring = Track.circle(radius=self.radius * 1.05, center=self.center, color=color,
                            line_width=2.2)
        ring.glow = CheapGlow(color, radius=8)
        tween(ring["radius"], 300, time=0.8, ease="ease_out")
        ring.fade_out(0.8, on_done=ring.destroy)

    def fall(self):
        x, y = self.center.x, self.center.y
        canvas.explosion_at(x, y, amount=0.9, flash=False, shake=False)
        canvas.flash(0.25)
        canvas.debris_at(x, y, color=AMBER, radius=170, amount=1.3, count=40, dust=True)
        canvas.debris_at(x, y, color=VIOLET, radius=130, amount=1.0, count=24)
        sun = Sunburst(center=(x, y), radius=10, color=AMBER, amount=1.0)
        tween(sun["radius"], 110, time=0.4, ease="ease_out")
        after(0.4, lambda: fx_out(sun, 0.6))
        star = Starburst(center=(x, y), radius=40, points=8, color=FROST, amount=0.45)
        tween(star["radius"], 300, time=0.8, ease="ease_out")
        fx_out(star, 0.8)
        after(0.35, lambda: canvas.fireworks_at(x - 210, y + 120, color=AMBER, color2=PEACH,
                                                radius=150, amount=0.8))
        after(0.75, lambda: canvas.fireworks_at(x + 120, y - 150, color=ICE, color2=FROST,
                                                radius=140, amount=0.8))
        for thing in self.runs + [self.skin, self.heart_skin, self.shell_skin, self.core]:
            thing.destroy()
        self.heart.burn_out(0.6, on_done=self.heart.destroy)
        self.shell.destroy()
        self.burn_out(0.8, on_done=self.destroy)


async def boss(t):
    st.ring.destroy()
    st.ring = None
    canvas.flash(0.25)
    canvas.zap_at(W / 2, H / 2, color=FROST, radius=420, amount=1.0, count=16)
    knob_to(light, "intensity", 0.7, time=1.2)
    for layer in st.skies:
        layer.remove()
    st.skies = []
    sky(lambda: Tunnel(color=VIOLET, amount=1.8, speed=1.4, density=1.5, streak=1.3,
                       center=(LAIR.x, LAIR.y), alpha=0.9),
        lambda: Nebuladust(color="#120a33", color2=DUSK, color3="#071a33", alpha=0.4), time=0.3)
    pilot.aim = None
    st.firing = True
    say("Real code. Nothing hidden", enter_lightning, ICE, hold=2.7, leave="vortex")
    b = Boss(n=6, radius=110, center=(1500, LAIR.y), angle=90)
    st.boss = b
    b.move_to((LAIR.x, LAIR.y), time=1.6, ease="ease_out")
    run_task(boss_rhythm)


async def boss_rhythm():
    """The boss on the beat: a pulse and a ring of bullets; a new skin every other beat."""
    b = st.boss
    await at(BARS[6] + 1.6)
    b.open = True
    k = 0
    while now() < BARS[8] - 0.3 and b.is_alive:
        b.bloom(k)
        if k % 2 == 1:
            b.next_look()
        b.scale = 1.06
        b.scale_to(1.0, time=0.3, ease="ease_out")
        k += 1
        await wait(BEAT / 2)


def boss_path():
    t = now()
    return 330 + 120 * sin(t * 0.8), 380 + 200 * sin(t * 1.3)


async def fight(t):
    punch(1.03)
    say("Built for learning. Full tutorial", enter_frame, AMBER, hold=2.6, leave="noise",
        size=36, tracking=0.1)
    pilot.aim = boss_path
    b = st.boss
    b.move_to((960, 450), time=1.6, ease="ease_in_out")
    after(1.6, lambda: b.move_to((940, 320), time=1.6, ease="ease_in_out") if b.is_alive else None)
    st.escorts = []
    for k in range(6):
        foe = Foe(n=4, radius=15, center=(LAIR.x, LAIR.y)).dress(PEACH, "tracer", hp=4)
        foe.orbit = k * 60
        st.escorts.append(foe)


def tend_escorts(dt):
    for foe in getattr(st, "escorts", []):
        if foe.is_alive and foe in st.foes and st.boss is not None and st.boss.is_alive:
            a = (foe.orbit + now() * 110) * pi / 180
            foe.move_to(st.boss.center.x + 190 * cos(a), st.boss.center.y + 190 * sin(a))


# ---- 0:25.6  the fall; quiet; a loop of light ----

async def fall(t):
    st.firing = False
    b = st.boss
    b.open = False
    for foe in list(st.foes):
        foe.explode()
    for blt in st.bullets:
        if blt.is_alive:
            blt.fade_out(0.5)
    b.fall()
    punch(1.06, about=(b.center.x, b.center.y), time=1.2)
    knob_to(light, "intensity", 0.95, time=0.3)
    sky(lambda: Borealis(color=ICE, alpha=0.45, speed=0.35),
        lambda: Nebuladust(color="midnight blue", color2=DUSK, color3="#0b3a4a", alpha=0.4),
        lambda: Stars(color=FROST, density=0.35, twinkle=0.6), time=2.4)
    await at(t + 0.4)
    knob_to(light, "intensity", 0.7, time=2.0)
    canvas.zoom_to(1.07, about=(W / 2, 380), time=3.2, ease="ease_in_out")
    await at(t + 1.2)
    st.gather = now()
    pilot.aim = lambda: (380 + 30 * sin(now() * 0.5), 360)
    embers = Embers(color=AMBER, density=0.4, rise=0.4, alpha=0.5)
    embers.alpha = 0.0
    knob_to(embers, "alpha", 0.5, time=1.5)
    st.skies.append(embers)


async def loop_of_light(t):
    say("Make something beautiful", enter_bloom, PEACH, hold=2.6, leave="fade")
    ship = st.ship
    pts = [(ship.center.x, ship.center.y), (700, 470), (980, 420), (1030, 300), (860, 220),
           (600, 300), (560, 430), (760, 520), (1400, 560)]
    st.ship_loop = True
    ship.move_along(Track(points=pts), time=3.4, ease="ease_in_out", face=True)
    shine = Track(points=pts, color=ICE.with_alpha(0.7), line_width=2.4)
    shine.visual = Neon(ICE, width=2.2, amount=0.7)
    draw_on(shine, 3.4)
    draw_off(shine, 2.6, delay=1.4)
    canvas.zoom_to(1.0, about=(W / 2, 380), time=3.0, ease="ease_in_out")


# ---- 0:32.0  the end card ----

async def made_with_scena():
    cx, cy = W / 2, H / 2 + 40
    Nebuladust(color="midnight blue", color2=DUSK, color3="#0b3a4a", alpha=0.35)
    Stars(color=FROST, density=0.4, twinkle=0.5)
    canvas.explosion_at(cx, cy, amount=1.0, flash=False, shake=False)
    size = 84
    row = [Text(ch, center=(cx, cy), font=TITLE_FONT, font_size=size, color=WHITE)
           for ch in "100% made with Scena"]
    width = sum(t.box.width for t in row)
    x = cx - width / 2
    for i, t in enumerate(row):
        t.home = Vec2(x + t.box.width / 2, cy)
        x += t.box.width
        warm = i >= len(row) - 5
        t.color = PEACH if warm else FROST
        t.glow = Glow(AMBER if warm else ICE, radius=12, amount=0.5)
        t.fill_filter = DropShadow(offset=5, sigma=5)
        t.center = (cx, cy - 20)
        t.move_to(t.home, time=0.9, ease="elastic")
    st.card_row = row
    top = max(t.box.top for t in row)
    over = Text("this video was", center=(cx, top + size * 0.3 - 20), font=NOTE_FONT,
                font_size=size * 0.4, color=FROST)
    over.move_by(0, 20, time=0.7, ease="ease_out")
    over.fade_in(0.7)
    await wait(1.0)
    bottom = min(t.box.bottom for t in row) - 14
    st.card_line_y = bottom
    line = Track(points=[(min(t.box.left for t in row), bottom),
                         (max(t.box.right for t in row), bottom)], smooth=0, color=AMBER,
                 line_width=3)
    line.begin = 0.5
    line.end = 0.5
    tween(line["begin"], 0, time=1.0, ease="ease_out")
    tween(line["end"], 1, time=1.0, ease="ease_out")
    await wait(0.5)
    y = bottom - 50
    for k, words in enumerate(("pip install scena", "github.com/accmota/Scena")):
        t = Text(words, center=(cx, y - 20), font=SMALL_FONT, font_size=30 if k == 0 else 22,
                 color=FROST if k == 0 else FROST.with_alpha(0.7))
        t.move_by(0, 20, time=0.8, ease="ease_out")
        t.fade_in(0.8)
        y -= 46
        await wait(0.4)
    await wait(0.4)             # the music's credit (CC BY), small at the bottom, as on every card
    credit = Text('Music: "Battle in the Winter" by Johan Brodd (CC BY 3.0)', center=(cx, 24),
                  font=SMALL_FONT, font_size=17, color=FROST.with_alpha(0.7))
    credit.move_by(0, 20, time=0.8, ease="ease_out")
    credit.fade_in(0.8)


async def final_chord():
    """The piece's last chord: a ripple of light runs through the words."""
    for i, t in enumerate(st.card_row):
        after(0.025 * i, lambda t=t: t.pop(scale=1.18) if t.is_alive else None)
    flare(W / 2, st.card_line_y, AMBER, width=1100, time=1.4, layer="default", spot=False)


# ---- the running order ----

def update(dt):
    st.frame += 1
    st.loud += (amp_db(audio.level, floor=-30) - st.loud) * min(1.0, dt * 6)
    ship = st.ship
    if ship is not None and ship.is_alive:
        if not st.ship_loop and now() > BARS[2] + 0.7:
            ship.steer(dt)
            tilt = max(-16.0, min(16.0, ship.vy * 0.05))
            ship.rotate_by(tilt - st.tilt)
            st.tilt = tilt
        if st.firing:
            tick = int(now() / (BEAT / 4))
            if tick != st.shot_tick:
                st.shot_tick = tick
                fire()
                if tick % 4 == 0 and st.boss is None:
                    foe_fires()
    fly_shots(dt)
    fly_bullets(dt)
    if st.ring is not None and st.ring.is_alive:
        st.ring.color, st.ring.color2 = ring_colors(now())
        st.ring.glow = 0.6 + 0.5 * st.loud
    tend_lanterns()
    tend_dims()
    tend_crown(dt)
    tend_escorts(dt)


async def main():
    await wait(0.3)         # change_act needs the game running
    st.t0 = clock.time
    play_sound(MUSIC, volume=0.95)
    for begin, scene in ((BARS[0], title), (BARS[2], launch), (BARS[3], spirals),
                         (BARS[4], swarm), (BARS[5], squadron), (BARS[6], boss),
                         (BARS[7], fight), (BARS[8], fall), (BARS[9], loop_of_light)):
        await at(begin)
        await scene(begin)
    await at(CARD - 0.6)
    st.logo.fade_out(0.6)
    st.tag.fade_out(0.6)
    await at(CARD)
    st.ship = None
    st.ring = None
    st.boss = None
    st.lanterns = []
    st.shots = []
    st.bullets = []
    st.foes = []
    st.crown = []
    st.escorts = []
    st.skies = []
    st.firing = False
    canvas.reset_view()
    change_act(Card)
    run_task(made_with_scena)
    await at(FINAL)
    await final_chord()


run_task(main)
run(Card)
