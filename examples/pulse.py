"""Pulse.

A music video that draws itself. The song plays, and every shape on the
screen listens to it: the deep sounds (the bass, the kick drum) move the big,
slow things; the high sounds (cymbals, hi-hats) move the small, fast ones.

Each kick of the drum is a beat. On a beat something happens (a ring flies
out, a light jumps, fireworks go off), every 8 beats the camera moves, and
after 28 beats (about 20 seconds) the video cuts to the next scene:

  I    Mandala     a ring of bars, one per band of sound, around a beating heart
  II   Runners     lights race along neon stars; the bass sets their speed
  III  Bloom       a flower of outlines from many shapes, fireworks on the kicks

How it listens
--------------
  audio.spectrum(bins=32) splits the sound into 32 bands, from the deepest to
  the highest; amp_db turns each one into the scale the ear hears. hear(b)
  below does both, and the shapes link to it with @= (or a lambda in the
  constructor), so they follow the music on their own, frame by frame.

Things to try
-------------
  Press M near a speaker   the room's sound drives the picture (VJ mode)
  Change KICK              smaller: more beats; bigger: only the strong kicks
  Change SCENE_BEATS       how many beats each scene lasts

Controls
--------
  M        listen to the microphone / back to the music
  1 to 3   jump to a scene

Use
---
    python examples/pulse.py
"""

from math import cos, sin, radians
from random import uniform, choice
from scena import *

init(width=1280, height=800, title="Pulse")

MUSIC = "music/super_hero_original_no_intro.ogg"
FONT = "fonts/Quantico-Bold.ttf"
TITLE_FONT = "fonts/kenvector_future.ttf"
CENTER = (640, 400)

BANDS = 32
# The high bands are much softer than the low ones: each band gets a lift,
# a little more for each step up, so all of them can move a shape.
LIFT = [0.5 * 1.13 ** b for b in range(BANDS)]
KICK = 0.1          # how far above the usual the bass must jump to be a beat
SCENE_BEATS = 28    # beats per scene (the song kicks about every 0.72 s)
MIC_GAIN = 4        # a microphone hears the room much softer than the file


# ---- the stage: lasts for the whole video ----

light = Bloom(intensity=0.6)
audio.level_tau = 0.06      # quicker meters: the shapes jump on the kick
play_sound(MUSIC, loops="forever")

st.ear = audio      # what the picture listens to: the music, or the mic (M)
st.gain = 1
st.mic = None
st.mic_opened = 0   # when M switched to the mic (clock.time)
st.source = "music"
st.bass = 0         # the deep sounds now (0 … about 0.6)
st.highs = 0        # the high sounds now
st.usual = 0        # the bass lately: a beat is a jump above it
st.beats = 0
st.last_beat = 0    # when the last beat was (clock.time)
st.scene = 0
st.title = ""
st.run = 0          # how far the neon lights have run (scene II)


def hear(b):
    """How loud band b is now: 0 (quiet) … about 0.6 (loud). Band 0 is the deepest."""
    return amp_db(st.ear.spectrum(BANDS)[b] * LIFT[b] * st.gain, floor=-24)


# the HUD: what plays, what listens, and the beats
Text(lambda: f"{st.title}      listening to the {st.source}      [M] mic / music      [1-3] scenes",
     top_left=(24, 34), layer="ui", font=FONT, font_size=14,
     color=Color("white").with_alpha(0.6))
# 16 steps, like a drum machine: each beat lights the next step, as big as
# the kick was loud, so the last 16 kicks stay written on the strip
steps = []
for k in range(16):
    steps.append(Circle(center=(926 + k * 22, 28), radius=2,
                        color=Color("white").with_alpha(0.7), layer="ui"))


# a quick double bump of the same kick must not count twice: 0.3 s apart at least
@when(lambda: st.bass > st.usual + KICK and clock.time > st.last_beat + 0.3)
def beat():
    st.beats += 1
    st.last_beat = clock.time
    step = steps[st.beats % 16]
    step.radius = 2 + 7 * st.bass
    step.pop(scale=1.8)


def enter(number, title):
    """The start of every scene: its number, its title and a flash."""
    st.scene = number
    st.title = title
    canvas.flash(0.5)
    big = Text(title, center=(640, 720), layer="ui", font=TITLE_FONT, font_size=34,
               color="white")
    big.fade_in(0.3)
    big.after(2.5, lambda: big.fade_out(1))


def next_scene():
    change_act(SCENES[(st.scene + 1) % len(SCENES)])


def ramp_colors(colors, n):
    """n colors spread evenly along a ramp through the given colors."""
    ramp = Colormap.from_colors(*colors)
    return [ramp.get_color(k / (n - 1)) for k in range(n)]


# ---- I  mandala ----

class Mandala(Act):
    def setup(self):
        enter(0, "I  MANDALA")
        canvas.background = "#06020f"
        Stars(color="lavender", density=0.6, twinkle=0.6)
        self.beats = 0

        # 64 bars in four mirrored quarters: band 1 by the axes, band 31 between
        colors = ramp_colors(["deep pink", "orchid", "cyan", "pale turquoise"], 16)
        for i in range(64):
            k = i % 16
            if i // 16 % 2:
                k = 15 - k
            b = 1 + 2 * k
            angle = 90 + (i + 0.5) * 360 / 64
            Line(p1=(640 + 150 * cos(radians(angle)), 400 + 150 * sin(radians(angle))),
                 angle=angle, length=lambda b=b: 12 + 320 * hear(b),
                 color=colors[k], line_width=6)

        # the highs: small dots on an inner ring
        for k in range(16):
            a = radians(k * 360 / 16)
            c = Circle(center=(640 + 118 * cos(a), 400 + 118 * sin(a)),
                       radius=lambda k=k: 2 + 18 * hear(14 + k), color="white")
            c.visual = Rim()

        # the heart: two triangles turning against each other, breathing with the bass
        for turn, color in ((25, "deep pink"), (-25, "cyan")):
            star = Triangle(center=CENTER, radius=lambda: 50 + 120 * st.bass,
                            angle=lambda turn=turn: clock.time * turn, color=color)
            star.fill = None
            star.line_width = 4
        self.heart = Circle(center=CENTER, radius=34, color="white")
        self.heart.visual = Beat("hot pink", amount=0.12, speed=1.4)
        self.rings = History(max_points=6)

        title = Text("PULSE", center=(640, 400), layer="ui", font=TITLE_FONT, font_size=120,
                     color="white")
        title.fade_in(1)
        title.after(4, lambda: title.fade_out(1.5))

    @on_change(lambda self: st.beats)
    def beat(self):
        self.beats += 1
        self.heart.pop(scale=1.4)
        # a ring flies out of the heart; the History keeps the last few
        ring = self.rings.add(Circle(center=CENTER, radius=150,
                                     color=choice(["hot pink", "cyan", "orchid"])))
        ring.fill = None
        ring.line_width = 3
        ring.scale_to(3.2, time=1.6, ease="ease_out")
        ring.fade_out(1.6)
        if self.beats % 8 == 0:
            canvas.rotate_by(45, time=1.2, ease="ease_in_out")
            canvas.ripple_at(CENTER, amount=0.5)
        if self.beats >= SCENE_BEATS:
            next_scene()

    def on_update(self, dt):
        light.intensity = 0.5 + 1.6 * st.bass


# ---- II  runners ----

class Runners(Act):
    def setup(self):
        enter(1, "II  RUNNERS")
        canvas.background = "#020610"
        Lattice(fold="hex", color="dark slate blue", alpha=0.3)
        self.beats = 0

        # five neon stars inside each other; a dim one shows the road, a
        # bright window runs along it (begin / end follow st.run)
        colors = ["cyan", "deep sky blue", "medium orchid", "hot pink", "gold"]
        self.stars = []
        for k in range(5):
            size = lambda k=k: 1 + 0.5 * hear(2 + 6 * k)
            road = Track.star(points=5 + k, radius=70 + 62 * k, center=CENTER,
                              color=Color(colors[k]).with_alpha(0.2), line_width=2)
            road["scale"] @= size
            runner = Track.star(points=5 + k, radius=70 + 62 * k, center=CENTER,
                                color=colors[k], line_width=4)
            runner["scale"] @= size
            direction = 1 if k % 2 else -1
            runner["begin"] @= lambda k=k, d=direction: (d * st.run + k * 0.2) % 1
            # the window grows with the highs: a long streak on a loud cymbal
            runner["end"] @= lambda k=k, d=direction: (d * st.run + k * 0.2 + 0.05
                                                       + 0.5 * st.highs) % 1
            self.stars.append(runner)
            # a comet rides each road the other way round
            comet = Circle(radius=5, color="white")
            comet.glow = CheapGlow(colors[k], radius=10)
            comet.move_along(road, time=6 + k, loops="forever", phase=k * 0.3)

        # two oscilloscope lines; on each beat they get a new zigzag
        self.scopes = []
        for y, color in ((120, "aquamarine"), (680, "hot pink")):
            scope = Track.wave(length=1280, amplitude=6, waves=5, start=(0, y),
                               color=Color(color).with_alpha(0.45), line_width=2)
            self.scopes.append(scope)

    @on_change(lambda self: st.beats)
    def beat(self):
        self.beats += 1
        # the lights leap forward on the kick
        st.run += 0.06
        for scope in self.scopes:
            scope.zigzag(amount=4 + 50 * st.bass, waves=choice([16, 32, 64]))
        runner = choice(self.stars)
        canvas.zap_at(runner.at(runner.begin), radius=50, color="white")
        if self.beats % 8 == 0:
            canvas.zoom_to(1.15 if self.beats % 16 else 1, time=0.6, ease="ease_out")
        if self.beats >= SCENE_BEATS:
            next_scene()

    def on_update(self, dt):
        # the bass sets the pace of the lights
        st.run += dt * (0.05 + 0.6 * st.bass)
        light.intensity = 0.6 + 1.2 * st.bass


# ---- III  bloom ----

class Flower(Act):
    def setup(self):
        enter(2, "III  BLOOM")
        canvas.background = "#0c0418"
        self.prism = Prism(amount=0.003)
        credit = Text("music: SuperHero (opengameart.org)   ·   pictures: scena",
                      center=(640, 60), layer="ui", font=FONT, font_size=16,
                      color=Color("white").with_alpha(0.7))
        credit.fade_in(3)
        self.beats = 0
        colors = ramp_colors(["gold", "hot pink", "medium purple", "cyan"], 12)
        # twelve petals, each a thin ellipse; the lows open them
        for k in range(12):
            petal = Ellipse(center=CENTER, width=lambda k=k: 300 + 800 * hear(1 + k),
                            height=110, angle=lambda k=k: k * 15 + clock.time * 10,
                            color=colors[k])
            petal.fill = None
            petal.line_width = 2
        # inside, a ring of polygons from 3 to 8 sides, turning at their own pace
        for n in range(3, 9):
            shape = RegularPolygon(n=n, center=CENTER,
                                   radius=lambda n=n: 60 + 22 * n + 160 * hear(3 * n + 6),
                                   angle=lambda n=n: clock.time * (40 - 7 * n),
                                   color=colors[2 * n - 6])
            shape.fill = None
            shape.line_width = 3
        # four scoops make a square with a round hole: the core
        for dx, dy, scoop in ((-1, 1, "bottom_right"), (1, 1, "bottom_left"),
                              (-1, -1, "top_right"), (1, -1, "top_left")):
            piece = Concave(center=(640 + 40 * dx, 400 + 40 * dy), width=80, height=80,
                            scoop=scoop, color="gold")
            piece.fill = Color("dark orange").with_alpha(0.35)

    @on_change(lambda self: st.beats)
    def beat(self):
        self.beats += 1
        canvas.fireworks_at(uniform(200, 1080), uniform(150, 650),
                            color=choice(["gold", "hot pink", "cyan"]), radius=80)
        if self.beats % 8 == 0:
            # a punch in, then a slow way back
            canvas.zoom_to(1.25, time=0.3, ease="ease_out",
                           on_done=lambda: canvas.zoom_to(1, time=1.5, ease="ease_in_out"))
        if self.beats >= SCENE_BEATS:
            next_scene()

    def on_update(self, dt):
        self.prism.amount = 0.001 + 0.008 * st.highs
        light.intensity = 0.5 + 1.2 * st.bass


SCENES = [Mandala, Runners, Flower]


# ---- listening ----

def listen_to_mic():
    if st.mic is None:
        st.mic = Microphone()
    st.ear = st.mic
    st.gain = MIC_GAIN
    st.mic_opened = clock.time
    st.source = "microphone"


def listen_to_music(note):
    st.ear = audio
    st.gain = 1
    st.source = note


def update(dt):
    st.bass = hear(2)
    st.highs = hear(24)
    st.usual = chase(st.usual, st.bass, rate=3)

    if keyp.once("M"):
        if st.ear is audio:
            listen_to_mic()
        else:
            listen_to_music("music")
    # A mic that reads exactly 0 for a whole second is no mic at all (none
    # plugged in, or no permission): even a quiet room makes a little noise.
    if st.ear is st.mic and clock.time > st.mic_opened + 1 and st.mic.level == 0:
        listen_to_music("music (no microphone found)")
    for n in range(len(SCENES)):
        if keyp.once(str(n + 1)):
            change_act(SCENES[n])


run(Mandala)
