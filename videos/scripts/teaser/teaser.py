"""Scena: the teaser.

A 90-second trailer for the engine, made with the engine. Every frame is
drawn by this program; the gameplay clips go into the windows it opens
(each window writes its cue to teaser_cues.json: when it is open, and
where, so the clips can be laid in frame-exact).

  0:00  SCENA                 the letters fly in from the stars
  0:07  philosophy            one petal leaves copies: a rosette grows
  0:17  looks                 the rosette changes clothes on every beat
  0:24  sprites               the ninja and its hitboxes, then the Ninja clip
  0:34  lines                 tracks draw themselves, comets run on them
  0:41  creative graphics     Oscilloscope and Constellation, and the manifesto
  0:54  effects               the Mandala listens; effects appear, a warp bends them
  1:00  events                a storm lights the kinds of events and processes
  1:05  games                 Ships and Plane, then the level editor
  1:25  this video was 100% made with Scena (it ends on the text, no fade)

Music: "The Field Of Dreams" by pauliuw (CC0), opengameart.org.

Use
---
    python videos/scripts/teaser/teaser.py
    python tools/video/record_game.py videos/scripts/teaser/teaser.py --seconds 93.5 \\
        --size 2560x1440 --prores --out $PWD/videos/recordings/masters.nosync/teaser.mov
    python videos/scripts/kit/teaser_composite.py videos/recordings/masters.nosync/teaser.mov \\
        videos/recordings/teaser/scena_teaser.mp4
    python videos/scripts/kit/finish.py videos/recordings/teaser/scena_teaser.mp4 promo/scena_teaser

    TEASER_START=34 python videos/scripts/teaser/teaser.py      # start at a section (no music)
"""

import io
import json
import os
import sys
import tokenize
from math import sin, cos, radians
from random import uniform, choice, randint, seed
from scena import *
from scena.collision import (CollisionSystem, _prims_from_collision_specs,
                             _snapshot_shape_uncached)

init(width=1280, height=720, title="Scena")
seed(7)

TITLE_FONT = "fonts/Quantico-Bold.ttf"
NOTE_FONT = "fonts/Quantico-Italic.ttf"
SMALL_FONT = "fonts/Quantico-Regular.ttf"
MUSIC = "music/the_field_of_dreams.ogg"
CENTER = (640, 360)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "kit"))
from paths import REPO, work               # noqa: E402
CUES = os.path.join(work("teaser"), "cues.json")
START = float(os.environ.get("TEASER_START", "0"))

# ---- the palette: ember and ice ----

NIGHT = "#071318"
DEEP = Color("dark cyan")
ICE = Color("turquoise")
FROST = Color("light cyan")
EMBER = Color("coral")
FLARE = Color("tomato")
ICE_RAMP = Colormap.from_colors("dark cyan", "turquoise", "light cyan")
EMBER_RAMP = Colormap.from_colors("tomato", "coral", "peach puff")
CAPTION = FROST.with_alpha(0.7)


def code_lines(path):
    """Lines of code in a file, the README way: no blank lines, comments or docstrings."""
    with open(path) as f:
        source = f.read()
    lines = set()
    before = None
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
                        tokenize.DEDENT, tokenize.ENDMARKER):
            continue
        alone = before is None or before.type in (tokenize.NEWLINE, tokenize.INDENT,
                                                   tokenize.DEDENT, tokenize.NL)
        before = tok
        if tok.type == tokenize.STRING and alone:
            continue
        lines.update(range(tok.start[0], tok.end[0] + 1))
    return len(lines)


def lines_of(example):
    return code_lines(os.path.join(REPO, "examples", example + ".py"))


# ---- the stage: stays for the whole teaser ----

canvas.background = NIGHT
light = Bloom(intensity=0.7)
Vignette(amount=0.7)
audio.level_tau = 0.06      # quicker meters: the Mandala jumps on the kick

st.t0 = 0           # clock.time when the teaser starts (minus START)
st.light = 0.7      # the Bloom's strength (a Post is not linked: update copies it)
st.frame = 0        # frames drawn: the cue sheet records it
st.cues = []


class Card(Act):
    """A blank act. change_act(Card) sweeps the last section away."""


def now():
    """Seconds into the teaser."""
    return clock.time - st.t0


async def at(t):
    """Wait until t seconds into the teaser."""
    await wait(max(0.0, t - now()))


def cue(kind, **data):
    """One line of the cue sheet: written at once, so a stopped run keeps it.
    video_time is the time in the recording (this frame is video frame st.frame - 1)."""
    st.cues.append(dict(kind=kind, time=round(now(), 3),
                        video_time=round((st.frame - 1) / 60, 4), **data))
    with open(CUES, "w") as f:
        json.dump(st.cues, f, indent=1)


# ---- words ----

def rise(text, center, font=TITLE_FONT, size=40, color="white", layer="default", time=0.9):
    """A line that is born a little low and rises into place as it fades in."""
    x, y = center
    line = Text(text, center=(x, y - 22), font=font, font_size=size, color=color, layer=layer)
    line.move_by(0, 22, time=time, ease="ease_out")
    line.fade_in(time)
    return line


def letters(text, center, font=TITLE_FONT, size=40, color="white", layer="default", gap=0):
    """One Text per letter (or per word, given a list), set side by side and centred:
    each can move on its own."""
    row = [Text(ch, center=center, font=font, font_size=size, color=color, layer=layer)
           for ch in text]
    width = sum(t.box.width for t in row) + gap * (len(row) - 1)
    x = center[0] - width / 2
    for t in row:
        t.home = (x + t.box.width / 2, center[1])
        t.center = t.home
        x += t.box.width + gap
    return row


def underline(text, color=EMBER, gap=8, width=2.5, time=1.0):
    """A line under a Text that grows out from its middle."""
    box = text.box
    y = box.bottom - gap
    under = Track(points=[(box.left, y), (box.right, y)], smooth=0, color=color,
                  line_width=width)
    under.begin = 0.5
    under.end = 0.5
    tween(under["begin"], 0, time=time, ease="ease_out")
    tween(under["end"], 1, time=time, ease="ease_out")
    return under


def arrive(text, center, size=40, color="white", font=TITLE_FONT, step=0.045, drop=18):
    """Letters that arrive one after another, each settling from a little above."""
    row = letters(text, center, font, size, color)
    for i, t in enumerate(row):
        t.visible = False
        t.center = (t.home[0], t.home[1] + drop)

        def show(t=t):
            t.visible = True
            t.fade_in(0.5)
            t.move_to(t.home, time=0.6, ease="ease_out")

        after(i * step, show)
    return row


def comet_reveal(text, center, size=40, color="white", font=TITLE_FONT, time=1.4,
                 tint=EMBER):
    """A comet crosses the line; each letter lights as the comet passes it."""
    row = letters(text, center, font, size, color)
    left = row[0].home[0] - 60
    right = row[-1].home[0] + 60
    for t in row:
        t.visible = False
        after(time * (t.home[0] - left) / (right - left), lambda t=t: (
            setattr(t, "visible", True), t.fade_in(0.35)))
    head = Circle(center=(left, center[1] - 4), radius=4, color="white")
    head.tail = Tail(color=tint, size=3)
    head.move_to((right, center[1] - 4), time=time, ease="linear",
                 on_done=lambda: head.fade_out(0.4, on_done=head.destroy))
    return row


def ghost_trail(text, place, size=44, ramp=ICE_RAMP, font=TITLE_FONT):
    """A line that drifts and leaves fading copies of itself, each a step along
    the ramp (old_school's copper logo, without the bounce)."""
    line = Text(text, center=place, font=font, font_size=size, color="white")
    line.ghosts = History(max_points=8)

    def drop():
        tint = ramp.get_color(clock.time * 0.5 % 1).with_alpha(0.4)
        ghost = line.ghosts.add(Text(text, center=line.center, font=font, font_size=size,
                                     color=tint))
        ghost.fade_out(0.5)

    line.every(0.07, drop)
    return line


def leave(*things, style="noise", time=0.8):
    for thing in things:
        if isinstance(thing, list):
            leave(*thing, style=style, time=time)
        elif thing is not None and thing.is_alive:
            thing.dissolve_out(time, style=style)


# ---- the windows the clips play in ----

class Window:
    """A frame that draws itself, opens on a black pane and holds a clip.

    The pane is plain black: the clip is laid over exactly that rectangle
    (the cue sheet has it in design units, from the top left)."""

    def __init__(self, center, width, height, color=FROST):
        self.center = center
        self.width = width
        self.height = height
        self.frame = Rect(center=center, width=width + 18, height=height + 18,
                          corner_radius=12)
        self.frame.visible = False
        self.border = Track(self.frame, color=color.with_alpha(0.55), line_width=2)
        self.border.end = 0
        self.pane = Rect(center=center, width=width, height=2, color="black")
        self.pane.line = None
        self.pane.visible = False
        self.comets = []

    async def open(self, time=0.8):
        tween(self.border["end"], 1, time=time * 0.6, ease="ease_in_out")
        await wait(time * 0.45)
        self.pane.visible = True
        await tween(self.pane["height"], self.height, time=time * 0.55, ease="ease_out")
        # a comet runs round the frame: three windows of the outline, one head
        for length, alpha, width in ((0.14, 0.25, 2), (0.06, 0.6, 3), (0.012, 1, 4)):
            comet = Track(self.frame, color=self.border.color.with_alpha(alpha),
                          line_width=width)
            comet["end"] @= lambda: clock.time * 0.12 % 1
            comet["begin"] @= lambda length=length: (clock.time * 0.12 - length) % 1
            self.comets.append(comet)

    def recolor(self, color):
        self.border.color = color.with_alpha(0.55)
        for comet, alpha in zip(self.comets, (0.25, 0.6, 1)):
            comet.color = color.with_alpha(alpha)
        canvas.hit_at(self.frame.top_center, style="disc", radius=50, color=color)

    def play(self, name, seconds=6.0):
        """From now the pane holds a clip for seconds: its cue goes on the sheet."""
        x, y = self.center
        cue("clip", clip=name, seconds=seconds,
            rect=[x - self.width / 2, 720 - y - self.height / 2, self.width, self.height])

    async def close(self, time=0.6):
        for comet in self.comets:
            comet.fade_out(time * 0.5)
        tween(self.pane["height"], 2, time=time * 0.6, ease="ease_in")
        await tween(self.border["begin"], 1, time=time, ease="ease_in_out")
        self.pane.visible = False


def caption(window, title, note, color=FROST):
    """The game's name under its window, and how long its program is."""
    x, y = window.center
    y -= window.height / 2 + 36
    name = Text(title, center=(x, y), font=TITLE_FONT, font_size=26, color=color)
    lines = Text(note, center=(x, y), font=NOTE_FONT, font_size=18, color=CAPTION)
    gap = 18
    left = x - (name.box.width + gap + lines.box.width) / 2
    name.center = (left + name.box.width / 2, y)
    lines.center = (left + name.box.width + gap + lines.box.width / 2, y - 1)
    for line in (name, lines):
        line.center = (line.center.x, line.center.y - 16)
        line.move_by(0, 16, time=0.7, ease="ease_out")
        line.fade_in(0.7)
    return [name, lines]


# ---- 0:00  the title ----

async def title(t):
    stars = StarFly(color=FROST, speed=0.3, density=1.2)
    canvas.set_fly(stars)
    await at(t + 0.6)
    # the letters fly in from all sides and land in a row, each with a spark
    row = letters("SCENA", (640, 400), size=150)
    for i, letter in enumerate(row):
        letter.fill = Gradient("white", FROST, ICE, angle=-90)
        home = letter.home
        letter.center = (uniform(-300, 1580), choice([-200, 920]))
        letter.move_to(home, time=1.1, ease="elastic",
                       on_done=lambda l=letter, i=i: canvas.zap_at(
                           l, radius=60, amount=0.7, color=EMBER if i % 2 else ICE))
        await wait(0.21)
    await at(t + 2.75)
    canvas.flash(0.4)
    canvas.ripple_at(640, 400, amount=0.5, radius=500, shake=False)
    stars.speed = 2.2
    # an underline of light grows from the middle; two lights run round a frame
    rule = Track(points=[(330, 312), (950, 312)], smooth=0, color=EMBER, line_width=3)
    rule.begin = 0.5
    rule.end = 0.5
    tween(rule["begin"], 0, time=1.2, ease="ease_out")
    tween(rule["end"], 1, time=1.2, ease="ease_out")
    frame = Rect(center=(640, 370), width=1000, height=330, corner_radius=24)
    frame.visible = False
    for start, color in ((0, ICE), (0.5, EMBER)):
        run = Track(frame, color=color, line_width=3)
        run["begin"] @= lambda s=start: (s + now() * 0.22) % 1
        run["end"] @= lambda s=start: (s + 0.16 + now() * 0.22) % 1
        run.fade_in(1.2)
    await at(t + 3.4)
    tagline = arrive("2D games and creative graphics in Python", (640, 262), size=30,
                     color=FROST, font=SMALL_FONT, step=0.03)
    await at(t + 5.7)
    stars.speed = 6
    await parallel(canvas.zoom_to(3.5, time=1.0, ease="ease_in"),
                   canvas.rotate_by(18, time=1.0, ease="ease_in"),
                   tween(st["light"], 1.6, time=1.0, ease="ease_in"))
    canvas.flash(0.3)
    canvas.reset_view()
    st.light = 0.7
    canvas.set_fly(None)


# ---- 0:07  one petal becomes a rosette ----

PETALS = 36
st.grow = 0         # how many petals are out (0 … PETALS, fractional while one leaves)
st.twist = 0        # degrees each ring turns past the one inside it
st.open = 1         # 1 the rosette as built · 0 all petals in the middle


def petal_born(i):
    """How far petal i has come out: 0 not yet … 1 in its place (eased)."""
    born = min(1, max(0, st.grow - i))
    return born * born * (3 - 2 * born)


def petal_turn(i):
    """Where petal i points: its place round its ring, and the ring's spin and twist."""
    ring, k = divmod(i, 12)
    turn = k * 30 + ring * 15 + clock.time * (9 - 4 * ring) + st.twist * ring
    return turn * petal_born(i)


def petal_spot(i, center):
    """Where petal i sits: it leaves the middle along its turn, out to its ring."""
    reach = (60 + 72 * (i // 12)) * petal_born(i) * st.open
    turn = radians(petal_turn(i))
    return (center[0] + reach * cos(turn), center[1] + reach * sin(turn))


def rosette(center, layer="default"):
    petals = []
    for i in range(PETALS):
        ring = i // 12
        petal = Ellipse(center=center, width=150 - 22 * ring, height=40 - 6 * ring,
                        layer=layer)
        petal["center"] @= lambda i=i: petal_spot(i, center)
        petal["angle"] @= lambda i=i: petal_turn(i)
        base = (ICE_RAMP if ring != 1 else EMBER_RAMP).get_color(0.25 + 0.3 * (i % 3))
        petal.fill = base.with_alpha(0.42)
        petal.line = base.with_alpha(0.8)
        petal.line_width = 1.2
        petal.blend = "add"
        petal["visible"] @= lambda i=i: st.grow > i
        petals.append(petal)
    return petals


async def philosophy(t):
    Nebula(color="dark cyan", color2="midnight blue", alpha=0.35)
    Stars(color=FROST, density=0.35, twinkle=0.4)
    st.grow, st.twist, st.open = 0.0, 0.0, 1.0
    st.petals = rosette((640, 410))
    # the first petal appears alone, then leaves copy after copy
    await tween(st["grow"], 1, time=0.8, ease="ease_out")
    built = rise("Built for learning", (640, 92), size=42)
    rule = underline(built, gap=10)
    tween(st["grow"], PETALS, time=7.5, ease="ease_in_out")
    await at(t + 3.7)
    leave(built, style="noise", time=0.6)
    tween(rule["begin"], 0.5, time=0.5, ease="ease_in")
    tween(rule["end"], 0.5, time=0.5, ease="ease_in")
    await at(t + 4.2)
    grow = arrive("Easy to begin. Room to grow.", (640, 92), size=42)
    await at(t + 7.2)
    leave(grow, style="vortex", time=0.7)
    tween(st["twist"], 75, time=4, ease="ease_in_out")
    await at(t + 7.7)
    simple = Text("Simple things are simple.", center=(640, 92), font=TITLE_FONT,
                  font_size=42, color="white")
    simple.dissolve_in(1.0, style="wipe")
    await at(t + 10.3)
    leave(simple, style="fade", time=0.5)


# ---- 0:17  looks ----

# each look, and whether the plane can wear it too (a look that replaces the
# body would hide a sprite's image: those stay on the shapes)
LOOKS = [(lambda: Halo(FROST), True), (lambda: ElectricField(ICE), True),
         (lambda: Shield(EMBER), True), (lambda: Metal(), True), (lambda: Flame(), True),
         (lambda: GearShell(FLARE), False), (lambda: Swell(), False), (lambda: Sphere(EMBER), False)]


async def looks(t):
    phrase = ghost_trail("Over 100 looks, effects and backgrounds", (640, 92), size=40)
    phrase["center"] @= lambda: (640 + 40 * sin(now() * 0.9), 92 + 6 * sin(now() * 1.7))
    phrase.fade_in(0.6)
    backs = [Borealis(color=ICE, alpha=0.5), Stardust(color=EMBER, color2=DEEP, alpha=0.5),
             Plasma(color=DEEP, alpha=0.35, speed=0.4), Nebula(color=FLARE, color2=DEEP,
                                                                alpha=0.45)]
    for back in backs:
        back.enabled = False
    plane = Sprite(Sheet("plane/Fly*.png", fps=10), height=90, center=(-120, 560))
    plane.move_to((1400, 520), time=6.5, ease="linear")
    beat = 0.833
    for n, (look, on_sprite) in enumerate(LOOKS):
        await at(t + n * beat)
        for petal in st.petals:
            petal.visual = look()
        if on_sprite:
            plane.visual = look()
        for k, back in enumerate(backs):
            back.enabled = k == n // 2
        if n:
            canvas.ripple_at(640, 410, amount=0.25, radius=380, shake=False)
    await at(t + 6.2)
    leave(phrase, style="wipe", time=0.4)


# ---- 0:24  sprites and hitboxes ----

NINJA = Sheet(anchor="bottom", pixel_size=0.62)
NINJA.strip("idle", "ninja/Idle__*.png", fps=8)
NINJA.strip("running", "ninja/Run__*.png", fps=14)
NINJA.strip("sword", "ninja/Attack__*.png", fps=20, offset=(50, -42))
FLOOR = 170
SWING = 5           # the sword clip's widest cell (Attack__005)
BLADE = Color("gold")


def pointer(label, tip, spot, color=FROST):
    """A small label with a thin line to what it names (the line draws itself)."""
    lead = Track(points=[spot, tip], smooth=0, color=color.with_alpha(0.6), line_width=1.5)
    lead.end = 0
    tween(lead["end"], 1, time=0.4, ease="ease_out")
    dot = Circle(center=tip, radius=3, color=color)
    dot.pop(scale=1.8)
    text = rise(label, (spot[0], spot[1] + 16), font=SMALL_FONT, size=24, color=color,
                time=0.5)
    return [lead, dot, text]


OUTLINES = []       # the hitbox outlines that follow their hitbox (update moves them)


def prim_outlines(prims):
    """The outlines of collision prims (no public call gives a hitbox's outline:
    this is the private one show_colliders draws)."""
    outlines = (CollisionSystem._debug_outline_verts(p) for p in prims)
    return [v for v in outlines if v]


def box_outline(box):
    return [[(box.left, box.bottom), (box.right, box.bottom), (box.right, box.top),
             (box.left, box.top)]]


class Outline:
    """Outlines drawn bold, copied every frame from shapes() (a list of vertex lists):
    a hitbox as the engine sees it (show_colliders draws one pixel, lost in a
    video), or a sprite's cell. Shown while shown() is true."""

    def __init__(self, shapes, color, shown=lambda: True, width=3):
        self.shapes = shapes
        self.color = color
        self.shown = shown
        self.width = width
        self.polys = []
        OUTLINES.append(self)
        self.follow()

    def verts(self):
        return self.shapes()

    def follow(self):
        if any(not poly.is_alive for poly in self.polys):
            OUTLINES.remove(self)       # the act changed under it
            return
        shapes = self.verts()
        if [len(v) for v in shapes] != [len(poly.points) for poly in self.polys]:
            for poly in self.polys:
                poly.destroy()
            self.polys = []
            for verts in shapes:
                poly = Polygon(points=verts, color=self.color)
                poly.fill = self.color.with_alpha(0.12)
                poly.line_width = self.width
                self.polys.append(poly)
        else:
            for poly, verts in zip(self.polys, shapes):
                for point, (x, y) in zip(poly.points, verts):
                    point.x, point.y = x, y
        for poly in self.polys:
            poly.visible = self.shown()

    def fade_in(self, time):
        for poly in self.polys:
            poly.fade_in(time)

    def leave(self, time=0.5):
        """Stop following (follow would show it again) and fade out."""
        OUTLINES.remove(self)
        for poly in self.polys:
            poly.dissolve_out(time, style="fade", on_done=poly.destroy)


async def sprites(t):
    SkyGradient(top=NIGHT, middle="#0b2530", bottom="#12333d", horizon=0.25)
    Stars(color=FROST, density=0.4, twinkle=0.5)
    ground = Rect(p1=(-50, -50), p2=(1330, FLOOR), color="#08161c")
    ground.line = None
    edge = Track(points=[(-50, FLOOR), (1330, FLOOR)], smooth=0, color=ICE.with_alpha(0.7),
                 line_width=2)
    edge.end = 0
    tween(edge["end"], 1, time=0.8, ease="ease_out")
    GlowSpot(center=(640, FLOOR), radius=380, color=DEEP, amount=0.6)
    # each cell gets its own hull ("each"): the hitbox follows the art as it runs
    hero = Sprite(NINJA, center=(-120, FLOOR), hitbox_shape="hull", hitbox_source="each",
                  hitbox_anchor="bottom")
    hero.collidable = True
    st.hold_sword = False       # writing hero.frame stops the clip: showing() turns off
    sword = hero.add_hitbox(group="sword", px_rect=(400, 60, 136, 375))
    sword["active"] @= lambda: hero.showing("sword") or st.hold_sword
    OUTLINES.clear()
    cell_line = Outline(lambda: box_outline(hero.box), FROST, width=2)
    body_line = Outline(lambda: prim_outlines(_snapshot_shape_uncached(hero, include_off=True)),
                        EMBER)
    sword_line = Outline(lambda: prim_outlines(_prims_from_collision_specs(
        sword._collision_specs())), BLADE, shown=lambda: sword.active)
    cell_line.fade_in(0.6)
    body_line.fade_in(0.6)
    hero.play("running")
    await hero.move_to((560, FLOOR), time=1.2, ease="ease_out")
    hero.play("idle")
    top = (hero.box.center.x, hero.box.top)
    left = min((v for verts in body_line.verts() for v in verts), key=lambda v: v[0])
    notes = [pointer("sprite sheet", top, (280, FLOOR + 400)),
             pointer("hitbox from the art", left, (300, FLOOR + 120), EMBER)]
    await at(t + 2.0)
    # the swing stops on its widest cell for two seconds, then the clip comes in
    hero.play("sword")
    first = hero.frame
    await until(lambda: hero.frame >= first + SWING)
    hero.frame = first + SWING
    st.hold_sword = True
    box = sword.box
    canvas.zap_at(box.center, style="fork", color=BLADE, radius=90)
    notes.append(pointer("one more, on the sword", (box.right, box.center.y),
                         (1010, FLOOR + 330), BLADE))
    await wait(2.0)
    # the ninja stays on that cell as it goes: the outlines fade where they are
    window = Window((640, 360), 896, 504)
    for note in notes:
        leave(note, style="fade", time=0.5)
    cell_line.leave()
    body_line.leave()
    sword_line.leave()
    hero.dissolve_out(0.8, style="vortex")
    await window.open()
    words = caption(window, "Ninja", f"{lines_of('ninja_5_sword')} lines of Python")
    window.play("ninja_5_espada", seconds=t + 10.0 - now())   # what the hold left
    await at(t + 10.0)
    leave(words, style="wipe", time=0.4)
    await window.close()


# ---- 0:34  lines ----

st.head = 0         # the comets' heads, in laps of their lines
st.span = 0.999     # how much of each line its comet lights (0.999: all of it)


def ring_line(n, track):
    """Line n of the set: ice and ember in turn, drawn from nothing."""
    ramp = ICE_RAMP if n % 2 == 0 else EMBER_RAMP
    track.color = ramp.get_color(0.35 + 0.1 * (n // 2))
    track.line_width = 2.5
    track.end = 0
    track.visible = True
    track.ramp = ramp
    return track


def light_up(track, n, points, radius):
    """A bright twin of the line: a lit window runs round it, a head leads it."""
    speed = (1 if n % 2 == 0 else -1) * (0.9 - 0.08 * n)
    twin = Track.star(points=points, radius=radius, inner=radius * 0.62, center=CENTER,
                      color=track.ramp.get_color(0.9), line_width=3.5)
    twin["angle"] @= lambda: track.angle
    twin.blend = "add"
    lag = n * 0.37
    twin["end"] @= lambda: (st.head * speed + lag) % 1
    twin["begin"] @= lambda: (st.head * speed + lag - st.span) % 1
    head = Circle(center=lambda: twin.at((st.head * speed + lag) % 1), radius=4,
                  color=track.ramp.get_color(1))
    head.fade_in(0.5)


async def lines(t):
    Stars(color=FROST, density=0.15)
    st.head = 0
    st.span = 0.999
    rings = []
    for n in range(7):
        track = ring_line(n, Track.circle(center=CENTER, radius=40 + 42 * n))
        if n % 2:
            track = ring_line(n, track.reversed())
        tween(track["end"], 1, time=1.4, ease="ease_in_out")
        rings.append(track)
        await wait(0.12)
    st.lines = rings
    await at(t + 1.9)
    canvas.ripple_at(CENTER, amount=0.35, radius=420, shake=False)
    # the circles sharpen into stars, each turning against its neighbours
    stars = []
    for n, old in enumerate(rings):
        star = ring_line(n, Track.star(points=5 + n, radius=60 + 42 * n,
                                       inner=(60 + 42 * n) * 0.62, center=CENTER))
        star.line_width = 1.6
        star["angle"] @= lambda n=n: clock.time * (14 - 3 * n) * (1 if n % 2 else -1)
        old.fade_out(1.2, on_done=old.destroy)
        tween(star["end"], 1, time=1.2, ease="ease_in_out")
        stars.append(star)
    st.lines = stars
    await at(t + 3.3)
    for n, star in enumerate(stars):
        star.color = star.ramp.get_color(0.35).with_alpha(0.55)
        light_up(star, n, 5 + n, 60 + 42 * n)
    st.span = 0.02
    tween(st["span"], 0.3, time=1.5, ease="ease_in_out")
    words = comet_reveal("Creative graphics", (640, 655), size=44)
    await at(t + 6.2)
    leave(words, style="vortex", time=0.6)


def machinery():
    """The words of the machinery, orbiting before they go."""
    ring = Track.circle(center=(1000, 300), radius=95)
    words = []
    for i, word in enumerate(("the loop", "the drawing", "the timers", "the cleanup")):
        w = Text(word, center=(1000, 300), font=SMALL_FONT, font_size=20,
                 color=(EMBER if i % 2 else FROST))
        w.move_along(ring, time=7, loops="forever", phase=i / 4)
        w.fade_in(0.6)
        words.append(w)
    return words


async def creative(t):
    # the lines go on behind, dimmed
    veil = Rect(p1=(0, 0), p2=(1280, 720), color=Color(NIGHT).with_alpha(0.72))
    veil.line = None
    veil.fade_in(0.8)
    window = Window((420, 380), 704, 396, color=ICE)
    await window.open()
    window.play("osciloscopio")
    words = caption(window, "Oscilloscope", f"{lines_of('oscilloscope')} lines of Python", ICE)
    you = rise("You write the game.", (1000, 520), size=38)
    rule = underline(you, color=EMBER, gap=10)
    await wait(3.0)
    handles = arrive("Scena handles the machinery,", (1000, 440), size=28, color=FROST)
    gears = machinery()
    await at(t + 6.8)
    leave(words, style="wipe", time=0.3)
    window.recolor(EMBER)
    words = caption(window, "Constellation", f"{lines_of('constelacao')} lines of Python",
                    EMBER)
    window.play("constelacao")
    for i, w in enumerate(gears):
        after(i * 0.35, lambda w=w: w.dissolve_out(0.6, style="vortex"))
    await at(t + 8.9)
    never = comet_reveal("never the decisions.", (1000, 300), size=38, tint=EMBER)
    await at(t + 12.4)
    leave(words, style="wipe", time=0.3)
    leave(you, handles, never, style="noise", time=0.6)
    tween(rule["begin"], 0.5, time=0.4)
    tween(rule["end"], 0.5, time=0.4)


# ---- 0:54  sound and space ----

BANDS = 32
LIFT = [0.5 * 1.13 ** b for b in range(BANDS)]     # the highs are softer: each band a lift
KICK = 0.05         # how far over the usual the low strings jump on an accent
MANDALA = (370, 320)
st.listening = False
PEAKS = [0] * BANDS    # TEASER_DEBUG: the loudest each band got
st.bass = 0
st.usual = 0
st.kicks = 0
st.last_kick = 0


def hear(b):
    """How loud band b is now: 0 (quiet) … about 0.6 (loud). Band 0 is the deepest."""
    return amp_db(audio.spectrum(BANDS)[b] * LIFT[b], floor=-42)


@when(lambda: st.listening and st.bass > st.usual + KICK and clock.time > st.last_kick + 0.3)
def kick():
    st.kicks += 1
    st.last_kick = clock.time


def mandala():
    """pulse.py's Mandala, smaller and to the left: a ring of bars, one per band."""
    cx, cy = MANDALA
    colors = Colormap.from_colors("dark cyan", "turquoise", "light cyan", "coral", "tomato")
    for i in range(64):
        k = i % 16
        if i // 16 % 2:
            k = 15 - k
        b = 1 + 2 * k
        angle = 90 + (i + 0.5) * 360 / 64
        Line(p1=(cx + 105 * cos(radians(angle)), cy + 105 * sin(radians(angle))),
             angle=angle, length=lambda b=b: 6 + 320 * max(0, hear(b) - 0.22),
             color=colors.get_color(k / 15), line_width=5)
    for k in range(16):
        a = radians(k * 360 / 16)
        dot = Circle(center=(cx + 80 * cos(a), cy + 80 * sin(a)),
                     radius=lambda k=k: 2 + 22 * max(0, hear(14 + k) - 0.2), color="white")
        dot.visual = Rim()
    for turn, color in ((25, EMBER), (-25, ICE)):
        star = Triangle(center=MANDALA, radius=lambda: 30 + 160 * max(0, st.bass - 0.2),
                        angle=lambda turn=turn: clock.time * turn, color=color)
        star.fill = None
        star.line_width = 3
    heart = Circle(center=MANDALA, radius=24, color="white")
    heart.visual = Beat(FLARE, amount=0.12, speed=1.4)
    return heart


def spatial(label, x, y, fx):
    """An effect in space, with its name under it."""
    canvas.hit_at(x, y, style="disc", radius=40, color="white")
    name = rise(label, (x, y - 92), font=SMALL_FONT, size=22, color=CAPTION, time=0.5)
    return fx, name


async def sound(t):
    Stars(color=FROST, density=0.5, twinkle=0.6)
    canvas.flash(0.4)
    heart = mandala()
    rings = History(max_points=6)
    st.listening = True

    @on_change(lambda: st.kicks)
    def ring_out():
        heart.pop(scale=1.4)
        ring = rings.add(Circle(center=MANDALA, radius=105, color=choice([EMBER, ICE, FROST])))
        ring.fill = None
        ring.line_width = 3
        ring.scale_to(2.4, time=1.4, ease="ease_out")
        ring.fade_out(1.4)

    note = rise("Lots of effects, parametrizable and composable", (640, 625), size=36)
    await at(t + 0.4)
    row = [("Fire", lambda x, y: Fire(center=(x, y - 40), style="tongues", width=80)),
           ("Portal", lambda x, y: Portal(center=(x, y), radius=58, color=ICE, color2=EMBER)),
           ("Orb", lambda x, y: Orb(center=(x, y), radius=46, color=FROST)),
           ("Sunburst", lambda x, y: Sunburst(center=(x, y), radius=60, color=EMBER)),
           ("Sparks", lambda x, y: Sparks(center=(x, y), radius=44, rate=60, color=FROST)),
           ("Starburst", lambda x, y: Starburst(center=(x, y), radius=56, points=6,
                                                color=FLARE))]
    shown = []
    for n, (label, make) in enumerate(row):
        x = 830 + (n % 3) * 175
        y = 430 if n < 3 else 185
        shown.append(spatial(label, x, y, make(x, y)))
        await wait(0.42)
    # a warp drifts over the row and bends what it passes
    await at(t + 3.6)
    warp = Warp(center=(700, 310), radius=150, color=ICE, color2=EMBER, amount=0.9)
    tween(warp["center"], (1300, 310), time=2.4, ease="ease_in_out")
    await at(t + 5.6)
    if os.environ.get("TEASER_DEBUG"):
        print("[teaser] band peaks", [round(v, 2) for v in PEAKS], "kicks", st.kicks,
              "bass usual", round(st.usual, 2))
    st.listening = False
    leave(note, style="fade", time=0.4)


# ---- 1:00  events and processes: the storm (tesla.py, the peak of its night) ----

GROUND = 70
CLOUD = 820
LIT = (1, 0.78, 0.42)
COPPER = (0.72, 0.40, 0.20)
SPARK = (0.55, 0.80, 1)


def coil(x, width, height):
    """A Tesla coil: a dark column, a copper winding, a metal ring and its field."""
    body = Rect(center=(x, GROUND + 70 + height / 2), width=width, height=height,
                color=(0.10, 0.10, 0.14))
    body.line = None
    base = Polygon(points=[(x - 60, GROUND), (x + 60, GROUND), (x + 36, GROUND + 26),
                           (x - 36, GROUND + 26)], color=(0.16, 0.16, 0.21))
    base.line = None
    for i in range(3):
        Concave(center=(x, GROUND + 34 + i * 13), width=44 - i * 6, height=12,
                scoop="top_center", color=(0.45, 0.5, 0.6))
    winding = Track(points=[(x, body.bottom_center.y + 10), body.top_center + (0, -6)],
                    smooth=0, color=COPPER, line_width=2)
    winding.zigzag(amount=width / 2 + 5, waves=height / 7)
    ring = Ellipse(center=body.top_center + (0, 16), width=width * 3.4, height=width * 0.9,
                   color=(0.75, 0.78, 0.85))
    ring.visual = Metal()
    field = Circle(center=ring.center, radius=width * 2.1, color=(0.2, 0.35, 0.65))
    field.visual = ElectricField(amount=4, speed=0.8)
    field.blend = "add"
    x, y = ring.center
    return (x, y)


def house(p1, p2):
    """A small house with its windows lit and the light spilling on the street."""
    body = Rect(p1=p1, p2=p2, color=(0.09, 0.09, 0.13))
    body.line = None
    left, right = body.top_left, body.top_right
    roof = Polygon(points=[(left.x - 10, left.y), (right.x + 10, right.y),
                           (body.center.x, left.y + 46)], color=(0.15, 0.11, 0.14))
    roof.line = None
    for dx in (-0.25, 0.25):
        for dy in (-0.15, 0.2):
            Rect(center=body.center + (dx * body.width, dy * body.height), width=15,
                 height=17, color=LIT)
    GlowSpot(center=body.bottom_center, radius=body.width * 0.9, color=(1, 0.65, 0.3),
             amount=0.7)
    return (body.center.x, left.y + 46)


def sag(p, q, depth):
    return ((p[0] + q[0]) / 2, min(p[1], q[1]) - depth)


def cable(points):
    """A dim wire, and a spark riding it with a tail of light."""
    wire = Track(points=points, color=(0.22, 0.24, 0.32), line_width=2)
    rider = Circle(radius=2.5, color="white")
    rider.tail = Tail(color=(0.4, 0.7, 1), size=1.6)
    rider.move_along(wire, speed=uniform(70, 130), loops="forever", yoyo=True,
                     phase=uniform(0, 1))


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


def word_row(label, words, y):
    """A label and its words in a row, the words dim until a strike lights them."""
    row = letters([label + ":"] + list(words), (640, y), font=SMALL_FONT, size=22,
                  color=Color(SPARK).with_alpha(0.4), gap=22)
    row[0].color = CAPTION
    for t in row:
        t.fade_in(0.6)
    return row


def afterimage(line):
    line.blend = "normal"
    line.line_width = 2
    line.color = (0.35, 0.48, 0.95, 0.5)


async def storm(t):
    canvas.cull_offscreen = False
    SkyGradient(top=(0.01, 0.01, 0.04), middle=(0.03, 0.04, 0.10), bottom=(0.08, 0.07, 0.16))
    Stars(density=0.6, twinkle=0.5)
    ChurningClouds(color=(0.20, 0.22, 0.42), color2=(0.45, 0.30, 0.55), speed=0.4)
    x = -150
    while x < 1430:
        w = uniform(50, 110)
        h = uniform(90, 250)
        block = Rect(p1=(x, GROUND), p2=(x + w, GROUND + h), color=(0.07, 0.07, 0.12, 0.9))
        block.line = None
        for i in range(int(h // 90)):
            if randint(0, 2):
                Rect(center=(x + uniform(10, w - 10), GROUND + 35 + i * 80), width=5,
                     height=8, color=LIT)
        x += w + uniform(4, 30)
    street = Rect(p1=(-150, -300), p2=(1430, GROUND), color=(0.025, 0.03, 0.05))
    street.line = None
    Rect(p1=(-150, GROUND - 3), p2=(1430, GROUND), color=(0.25, 0.3, 0.45))
    big = coil(150, 34, 260)
    small = coil(640, 26, 170)
    roofs = [house((880, GROUND), (980, GROUND + 86)),
             house((1012, GROUND), (1100, GROUND + 108)),
             house((1132, GROUND), (1240, GROUND + 78))]
    cable([big, sag(big, small, 90), small])
    for roof in roofs:
        cable([small, sag(small, roof, 40), roof])
    rods = []
    for rx in (380, 820):
        Rect(center=(rx, GROUND + 145), width=6, height=290, color=(0.55, 0.58, 0.66))
        ball = Circle(center=(rx, GROUND + 290), radius=6, color=(0.85, 0.9, 1))
        ball.glow = CheapGlow(SPARK, radius=8)
        rods.append((rx, GROUND + 290))
    path = Track(points=[(150, 440), (400, 430), (640, 360)])
    path.orbit(radius=24, laps=5)
    carrier = Point(0, 0)
    carrier.move_along(path, time=8, loops="forever", yoyo=True)
    orb = Orb(center=(0, 0), radius=22, color=(0.6, 0.8, 1), glow=1.2)
    orb["center"] @= lambda: carrier
    Rain(p1=(-40, GROUND - 10), p2=(1340, 740), amount=0.9, color=(0.65, 0.75, 0.95))
    afterimages = History(max_points=2, duration=3, on_leave=lambda b: b.dissolve_out(0.8))
    tips = [big, small] + rods + roofs

    rule = letters("Events and processes", (640, 650), size=36)
    for i, letter in enumerate(rule):
        letter.visible = False
        after(0.3 + i * 0.04, lambda l=letter: (setattr(l, "visible", True), l.fade_in(0.3)))
    events = word_row("events", ("when", "click", "key", "collide", "change"), 604)
    processes = word_row("processes", ("after", "every", "wait", "until", "parallel"), 572)
    words = [w for pair in zip(events[1:], processes[1:]) for w in pair]
    st.lit = 0

    def strike():
        x = uniform(0, 1280)
        near = [p for p in tips if abs(p[0] - x) < 240] or tips
        tip = max(near, key=lambda p: p[1])
        line = bolt((x + uniform(-80, 80), CLOUD), tip)
        line.after(0.12, lambda: afterimage(line))
        afterimages.add(line)
        canvas.zap_at(tip, style="fork", radius=70, color=(0.7, 0.85, 1))
        sparks = Sparks(center=tip, radius=30, rate=50, color=(0.8, 0.9, 1))
        sparks.after(0.5, sparks.destroy)
        # each strike lights the next word; once all are lit, any of them
        lit = words[st.lit] if st.lit < len(words) else choice(words)
        st.lit += 1
        lit.color = "white"
        canvas.zap_at(lit, radius=40, amount=0.6, color=SPARK)
        lit.pop(scale=1.3)

    await at(t + 0.5)
    while now() < t + 4.7:
        strike()
        await wait(choice([0.3, 0.42, 0.55]))
    await at(t + 5.0)
    leave(rule, events, processes, style="noise", time=0.4)


# ---- 1:05  games, and the editor ----

async def games(t):
    Borealis(color=DEEP, alpha=0.35)
    Stars(color=FROST, density=0.5, twinkle=0.4)
    window = Window((640, 392), 960, 540, color=ICE)
    await window.open()
    window.play("naves_6_atos")
    words = caption(window, "Ships", f"{lines_of('ships_6_acts')} lines of Python", ICE)
    for k in range(5):
        await wait(1.1)
        side = 70 if k % 2 == 0 else 1210
        canvas.fireworks_at(side, uniform(200, 600), color=choice([ICE, EMBER, FROST]),
                            radius=60)
    await at(t + 6.8)
    leave(words, style="wipe", time=0.3)
    window.recolor(EMBER)
    window.play("aviao_paisagem")
    words = caption(window, "Plane", f"{lines_of('plane_landscape')} lines of Python", EMBER)
    for k in range(5):
        await wait(1.1)
        side = 70 if k % 2 else 1210
        canvas.explosion_at(side, uniform(200, 600), amount=0.6)
    await at(t + 12.8)
    leave(words, style="wipe", time=0.3)
    window.recolor(FROST)
    window.play("scena-editor")
    words = caption(window, "Even its level editor", "is made with Scena", FROST)
    await at(t + 18.8)
    leave(words, style="wipe", time=0.3)
    await window.close()


# ---- 1:25  100% made with Scena ----

async def finale(t):
    Nebula(color="dark cyan", color2="midnight blue", alpha=0.3)
    Stars(color=FROST, density=0.4, twinkle=0.5)
    st.grow, st.twist, st.open = 0.0, 30.0, 1.0
    st.petals = rosette((640, 380))
    await tween(st["grow"], PETALS, time=1.6, ease="ease_out")
    await wait(0.4)
    await tween(st["open"], 0, time=0.7, ease="ease_in")
    for petal in st.petals:
        petal.destroy()
    canvas.explosion_at(640, 380, amount=1.3)
    canvas.flash(0.6)
    rise("this video was", (640, 478), font=NOTE_FONT, size=34, color=FROST, time=0.7)
    row = letters("100% made with Scena", (640, 400), size=84)
    for i, letter in enumerate(row):
        letter.fill = Gradient("white", FROST, ICE, angle=-90) if i < 15 else \
            Gradient("white", "peach puff", EMBER, angle=-90)
        home = letter.home
        letter.center = (640, 380)
        letter.move_to(home, time=0.9, ease="elastic")
    await wait(1.0)
    line = Track(points=[(row[0].box.left, 352), (row[-1].box.right, 352)], smooth=0,
                 color=EMBER, line_width=3)
    line.begin = 0.5
    line.end = 0.5
    tween(line["begin"], 0, time=1.0, ease="ease_out")
    tween(line["end"], 1, time=1.0, ease="ease_out")
    await wait(0.6)
    rise("pip install scena", (640, 290), font=SMALL_FONT, size=30, color=FROST)
    await wait(0.4)
    rise("github.com/accmota/Scena", (640, 248), font=SMALL_FONT, size=22, color=CAPTION)
    await wait(0.6)
    rise(f"its whole program: {code_lines(__file__)} lines of Python",
         (640, 120), font=NOTE_FONT, size=18, color=CAPTION)


# ---- the running order ----

SECTIONS = [
    (0.0, title, False),
    (6.7, philosophy, False),
    (17.5, looks, True),        # True: the same act goes on (the rosette stays)
    (24.0, sprites, False),
    (34.6, lines, False),
    (41.0, creative, True),
    (53.8, sound, False),
    (59.9, storm, False),
    (65.2, games, False),
    (84.6, finale, False),
    (93.0, None, False),
]


async def show():
    await wait(0.3)         # change_act needs the game running
    st.t0 = clock.time - START
    if START == 0:
        play_sound(MUSIC, volume=0.9)
    for n, (begin, scene, keep) in enumerate(SECTIONS):
        end = SECTIONS[n + 1][0] if n + 1 < len(SECTIONS) else begin
        if scene is None:
            break
        if end <= START:
            continue
        if not keep or begin < START:
            change_act(Card)
        await at(begin)
        await scene(begin)
        if now() > end + 0.05:
            print(f"[teaser] {scene.__name__} ran {now() - end:.2f} s past {end}")
    # no fade: the video ends on the text, so the install line can be read


def update(dt):
    st.frame += 1
    for line in OUTLINES[:]:
        line.follow()
    st.head += 0.3 * dt
    if st.listening:
        st.bass = hear(5)
        st.usual = chase(st.usual, st.bass, rate=3)
        st.light = 0.5 + 2.5 * max(0, st.bass - 0.2)
        if os.environ.get("TEASER_DEBUG"):
            PEAKS[:] = [max(p, hear(b)) for b, p in enumerate(PEAKS)]
    light.intensity = st.light


run_task(show)
run(Card)
