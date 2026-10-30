"""Scena: the second teaser. Say what you mean.

The first teaser shows what Scena makes; this one, how it reads. Code comes
in as one-line captions, folded with "…", and the thing each line says
happens beside it. Every frame is drawn by this program; the gameplay clips
go into the windows it opens (each writes its cue to the cue sheet, with
its recording and in-point, for kit/teaser_composite.py).

  0:00  SCENA                 the letters lean toward a spark (formulas), the motto; it fades
  0:08  formulas              a compass construction; a hand drags a point, all of it follows
  0:25  labels and links      a distance label, a health bar, dots that warm up
  0:38  a vocabulary          Connect Four plays; each line appears as it happens, then is read
  0:56  movement, collision   four easings, a track, rocks that fall on a ledge and are shot
  1:14  processes             two scripts at once, a playhead on each: wait, until, after
  1:31  click, drag, widgets  a demo of its own (teaser2_ui.py) played by a hand
  1:47  debug mode            the runner: overlays, pause, zoom out, ¼ speed, one step at a time
  2:04  the catalogue         backgrounds, screen effects, impacts, looks and a knob
  2:27  games made with Scena Race and Light Guardian, then a wall of nine more
  2:42  this video was 100% made with Scena: the music has ended; the card is silent

Every act comes in from black and leaves to black (FADE), but one that goes
on from the last (labels, screen effects).

Music: "Battle Theme A" by cynicmusic (CC0), opengameart.org, played to its
end with two repeats, each cut on the beat (30 ms crossfade): the theme
repeats a section 52.6 s apart (jump back from 88.18 s to 35.58 s), and a
32-beat phrase 13.16 s apart (then from 115.55 s to 102.39 s); 95.8 s ->
161.55 s (MUSIC_SECONDS), written by make_media.py as battle_long.flac.

Use
---
    python videos/scripts/teaser2/make_media.py
    python videos/scripts/teaser2/teaser2.py
    python tools/video/record_game.py --take runner/debug --take connect_four/red_row ...
    python tools/video/record_game.py videos/scripts/teaser2/teaser2_ui.py \\
        --pilot videos/scripts/teaser2/teaser2_pilots.py:ui_tour --seconds 14.5 \\
        --size 2560x1440 --out $PWD/videos/recordings/teaser2_ui/tour.mp4
    python tools/video/record_game.py videos/scripts/teaser2/teaser2.py --seconds 167.1 \\
        --size 2560x1440 --prores --out $PWD/videos/recordings/masters.nosync/teaser2.mov
    python videos/scripts/kit/teaser_composite.py videos/recordings/masters.nosync/teaser2.mov \\
        videos/recordings/teaser2/scena_teaser2.mp4 videos/recordings/teaser2/cues.json
    python videos/scripts/kit/finish.py videos/recordings/teaser2/scena_teaser2.mp4 promo/scena_teaser2

    TEASER_START=74.1 python videos/scripts/teaser2/teaser2.py      # start at a section (no music)
"""

import io
import json
import keyword
import os
import sys
import tokenize
from math import sin, cos
from random import uniform, seed
from scena import *

init(width=1280, height=720, title="Scena")
seed(7)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "kit"))
from paths import REPO, work               # noqa: E402
sys.path.insert(0, os.path.join(REPO, "tools", "video"))
from takes import TAKES, TEASER2_DEBUG_CHORDS      # noqa: E402  (the keycaps' times)
sys.path.insert(0, HERE)
from teaser2_pilots import UI_STEPS, UI_SECONDS    # noqa: E402  (the UI captions' times)

TITLE_FONT = "fonts/Quantico-Bold.ttf"
NOTE_FONT = "fonts/Quantico-Italic.ttf"
SMALL_FONT = "fonts/Quantico-Regular.ttf"
MONO = "fonts/JetBrainsMonoNLNerdFontMono-Regular.ttf"
MUSIC = os.path.join(work("teaser2"), "battle_long.flac")   # battle_theme_a, looped (below)
MUSIC_SECONDS = 161.55
CUES = os.path.join(work("teaser2"), "cues.json")
START = float(os.environ.get("TEASER_START", "0"))

# ---- the palette: ember and ice, as in the first teaser ----

NIGHT = "#071318"
PANEL = "#0b1d24"
DEEP = Color("dark cyan")
ICE = Color("turquoise")
FROST = Color("light cyan")
EMBER = Color("coral")
FLARE = Color("tomato")
ICE_RAMP = Colormap.from_colors("dark cyan", "turquoise", "light cyan")
CAPTION = FROST.with_alpha(0.7)
SYNTAX = {"keyword": EMBER, "string": Color("peach puff"), "number": FLARE,
          "comment": Color("slate gray"), "decorator": ICE, "call": Color("aquamarine"),
          "op": Color("light steel blue"), "name": FROST, "fold": EMBER}


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
    return code_lines(os.path.join(REPO, "examples", f"{example}.py"))


# ---- the stage: stays for the whole teaser ----

canvas.background = NIGHT
light = Bloom(intensity=0.6)
Vignette(amount=0.65)

st.t0 = 0           # clock.time when the teaser starts (minus START)
st.frame = 0        # frames drawn: the cue sheet records it
st.cues = []
st.falling = False  # the rocks of the movement act fall (update)


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

def rise(text, center, font=TITLE_FONT, size=40, color="white", time=0.8):
    """A line that is born a little low and rises into place as it fades in."""
    x, y = center
    line = Text(text, center=(x, y - 20), font=font, font_size=size, color=color)
    line.move_by(0, 20, time=time, ease="ease_out")
    line.fade_in(time)
    return line


def letters(text, center, font=TITLE_FONT, size=40, color="white"):
    """One Text per letter, set side by side and centred: each can move on its own."""
    row = [Text(ch, center=center, font=font, font_size=size, color=color) for ch in text]
    width = sum(t.box.width for t in row)
    x = center[0] - width / 2
    for t in row:
        t.home = Vec2(x + t.box.width / 2, center[1])
        t.center = t.home
        x += t.box.width
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


def headline(text, y=664, size=34, color="white"):
    """A section's name at the top, underlined in ember."""
    line = rise(text, (640, y), size=size, color=color)
    return [line, underline(line)]


def leave(*things, style="noise", time=0.6):
    for thing in things:
        if isinstance(thing, (list, tuple)):
            leave(*thing, style=style, time=time)
        elif thing is not None and thing.is_alive:
            thing.dissolve_out(time, style=style)


# ---- code captions: one line at a time, typed ----

def pieces(line):
    """(column, text, kind) of each token of one line of code: its colours.
    "…" folds what the caption leaves out (tokenized as "..." and drawn as one
    character, in ember)."""
    src = line.replace("…", "...")
    out = []
    toks = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src + "\n").readline):
            toks.append(tok)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass                    # an open bracket: the tokens before it are enough
    shift = 0                   # "..." is three columns in src, one on screen
    for n, tok in enumerate(toks):
        col = tok.start[1] - shift
        if tok.type == tokenize.NAME:
            after = toks[n + 1].string if n + 1 < len(toks) else ""
            before = toks[n - 1].string if n else ""
            kind = ("keyword" if keyword.iskeyword(tok.string) else
                    "decorator" if before == "@" else
                    "call" if after == "(" else "name")
        elif tok.type == tokenize.STRING or tok.type in FSTRING:
            kind = "string"
        elif tok.type == tokenize.NUMBER:
            kind = "number"
        elif tok.type == tokenize.COMMENT:
            kind = "comment"
        elif tok.type in (tokenize.OP, tokenize.ERRORTOKEN):
            if tok.string == "...":
                out.append((col, "…", "fold"))
                shift += 2
                continue
            kind = "decorator" if tok.string == "@" else "op"
        else:
            continue
        out.append((col, tok.string, kind))
    return out


FSTRING = {getattr(tokenize, n) for n in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END")
           if hasattr(tokenize, n)}


class Code:
    """Lines of code at a place on the screen, each typed in when it is said.
    A line is Texts, one per token, in the editor colours of the code video."""

    def __init__(self, left, top, size=20, gap=1.5):
        self.left, self.top, self.size = left, top, size
        self.step = size * gap
        probe = Text("M" * 20, top_left=(0, -400), font=MONO, font_size=size)
        self.cell = probe.box.width / 20
        probe.destroy()
        self.rows = []

    async def say(self, line, row=None, speed=90):
        """Type line at row (the next one by default); returns its Texts."""
        row = len(self.rows) if row is None else row
        y = self.top - row * self.step
        parts = []
        for col, text, kind in pieces(line):
            t = Text("", top_left=(self.left + col * self.cell, y), font=MONO,
                     font_size=self.size, color=SYNTAX[kind])
            t.whole = text
            parts.append(t)
        self.rows.append(parts)
        typed = 0.0
        for t in parts:
            while len(t.text) < len(t.whole):
                typed += speed / 60
                n = int(typed)
                if n:
                    typed -= n
                    t.text = t.whole[:len(t.text) + n]
                await wait(1 / 60)
        return parts

    def clear(self, style="fade", time=0.4):
        leave(self.rows, style=style, time=time)
        self.rows = []


def caption(window, title, note, color=FROST):
    """The game's name under its window, and how long its program is."""
    x, y = window.center
    y -= window.height / 2 + 34
    name = Text(title, center=(x, y), font=TITLE_FONT, font_size=24, color=color)
    lines = Text(note, center=(x, y), font=NOTE_FONT, font_size=17, color=CAPTION)
    gap = 16
    left = x - (name.box.width + gap + lines.box.width) / 2
    name.center = (left + name.box.width / 2, y)
    lines.center = (left + name.box.width + gap + lines.box.width / 2, y - 1)
    for line in (name, lines):
        line.center = (line.center.x, line.center.y - 14)
        line.move_by(0, 14, time=0.7, ease="ease_out")
        line.fade_in(0.7)
    return [name, lines]


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

    def play(self, take, seconds, start=0.0):
        """From now the pane holds a take of takes.py for seconds, from start
        seconds into its recording: its cue goes on the sheet."""
        x, y = self.center
        cue("clip", clip=take, recording=f"{take}.mp4", start=start,
            seconds=seconds,
            rect=[x - self.width / 2, 720 - y - self.height / 2, self.width, self.height])

    async def close(self, time=0.6):
        for comet in self.comets:
            comet.fade_out(time * 0.5)
        tween(self.pane["height"], 2, time=time * 0.6, ease="ease_in")
        await tween(self.border["begin"], 1, time=time, ease="ease_in_out")
        if self.pane.is_alive:          # a close still running when the next act sweeps
            self.pane.visible = False


# ---- 0:00  the title: letters that lean toward a spark ----

def arrive(text, center, size=40, color="white", font=TITLE_FONT, step=0.045, drop=18):
    """Letters that arrive one after another, each settling from a little above."""
    row = letters(text, center, font, size, color)
    for i, t in enumerate(row):
        t.visible = False
        t.center = (t.home.x, t.home.y + drop)

        def show(t=t):
            t.visible = True
            t.fade_in(0.5)
            t.move_to(t.home, time=0.6, ease="ease_out")

        after(i * step, show)
    return row


async def title(t):
    Stars(color=FROST, density=0.3, twinkle=0.4)
    spark = Circle(radius=6, color="white")
    spark.glow = True
    spark["center"] @= lambda: (640 + 420 * sin(now() * 0.8), 380 + 150 * sin(now() * 1.6))
    spark.tail = Tail(color=EMBER, size=3)
    row = letters("SCENA", (640, 400), size=150)
    threads = []
    for letter in row:
        home = letter.home
        letter.fill = Gradient("white", FROST, ICE, angle=-90)
        # each letter leans a little toward the spark, and turns to it
        letter["center"] @= lambda home=home: (
            home + (Vec2(spark.center.x, spark.center.y) - home) * 0.07)
        letter["angle"] @= lambda home=home: (spark.center.x - home.x) * -0.012
        thread = Line(p1=lambda: spark.center, p2=lambda letter=letter: letter.center,
                      color=ICE.with_alpha(0.22), line_width=1.2)
        threads.append(thread)
        letter.fade_in(0.9)
        thread.fade_in(1.6)
    await at(t + 1.9)
    # the motto of the first teaser
    tagline = arrive("2D games and creative graphics in Python", (640, 262), size=30,
                     color=FROST, font=SMALL_FONT, step=0.03)
    await at(t + 5.8)
    for thing in row + threads + tagline + [spark]:
        thing.fade_out(1.2)


# ---- 0:08  formulas: a construction that stays true, even by hand ----

def pointer():
    """A mouse pointer (an arrow), its tip at its first point."""
    arrow = Polygon(points=[(0, 0), (0, -26), (7, -19), (12, -30), (16, -28), (11, -17),
                            (20, -17)], color="white")
    arrow.line = "black"
    arrow.line_width = 1.5
    arrow.layer = "top"
    arrow.to_tip = Vec2(0, 0) - Vec2(arrow.center.x, arrow.center.y)   # center -> tip
    return arrow


def tip(arrow):
    """Where the arrow points (its first point, wherever it has moved)."""
    return Vec2(arrow.center.x, arrow.center.y) + arrow.to_tip


def point_to(arrow, x, y, **move):
    """Move the arrow so that its tip lands on (x, y)."""
    return arrow.move_to(x - arrow.to_tip.x, y - arrow.to_tip.y, **move)


def anchor_point(x, y, ax, ay, fx, fy, phase=0.0, hand=None):
    """A point that drifts by itself; held by the hand, it follows the hand's tip.
    Its center is a formula either way."""
    p = Circle(radius=7, color=EMBER)
    p.glow = True
    st.swing = 1.0
    st.held = False
    p["center"] @= lambda: (tip(hand) if st.held and hand is not None else
                            (x + ax * st.swing * sin(now() * fx + phase),
                             y + ay * st.swing * cos(now() * fy + phase)))
    return p


async def formulas(t):
    Stars(color=FROST, density=0.25, twinkle=0.3)
    top = headline("Formulas")
    st.parts = []           # what the next sections keep on screen
    code = Code(70, 150, size=20)
    st.code = code
    hand = pointer()
    hand.visible = False
    a = anchor_point(560, 400, 70, 45, 0.7, 1.1)
    b = anchor_point(720, 390, 60, 55, 0.9, 0.8, phase=1.3, hand=hand)
    for p in (a, b):
        canvas.zap_at(p, radius=40, amount=0.5, color=ICE)
    segment = Line(p1=lambda: a.center, p2=lambda: b.center, color=FROST.with_alpha(0.5),
                   line_width=1.5)
    segment.fade_in(0.6)
    # each line is typed, its shape appears and pulses once, and both stay to be read
    await at(t + 0.8)
    await code.say("c1 = Circle(center=lambda: a.center, perimeter_point=lambda: b.center)",
                   speed=CODE_SPEED)
    c1 = Circle(center=lambda: a.center, perimeter_point=lambda: b.center)
    c1.visual = Stroke(ICE, width=2)
    c1.fade_in(0.6)
    c1.pulse_outline(0.7, color=EMBER)
    await at(t + 3.8)
    await code.say("c2 = Circle(center=lambda: b.center, …)", speed=CODE_SPEED)
    c2 = Circle(center=lambda: b.center, perimeter_point=lambda: a.center)
    c2.visual = Stroke(ICE, width=2)
    c2.fade_in(0.6)
    c2.pulse_outline(0.7, color=EMBER)
    await at(t + 6.6)
    await code.say("bisector = Line(p1=lambda: intersection(c1, c2, 0), …)", speed=CODE_SPEED)
    bisector = Line(p1=lambda: intersection(c1, c2, 0), p2=lambda: intersection(c1, c2, 1),
                    color=EMBER, line_width=2.5)
    bisector.fade_in(0.5)
    crossings = []
    for i in (0, 1):
        dot = Circle(center=lambda i=i: intersection(c1, c2, i), radius=5, color=FROST)
        dot.fade_in(0.5)
        dot.pop(scale=1.8)
        crossings.append(dot)
    await at(t + 9.4)
    await code.say("mid = Circle(center=lambda: middle_point(a, b))", speed=CODE_SPEED)
    mid = Circle(center=lambda: middle_point(a, b), radius=6, color="white")
    mid.glow = True
    canvas.ripple_at(mid, radius=120, amount=0.3, shake=False)
    # a hand takes one point and drags it: everything built on it follows
    await at(t + 11.4)
    start = b.center
    point_to(hand, start.x + 260, start.y - 120)
    hand.visible = True
    hand.fade_in(0.3)
    await point_to(hand, start.x, start.y, time=0.7, ease="ease_out")
    st.held = True
    b.pop(scale=1.6)
    note = rise("Drag a point: everything built on it follows.", (640, 572),
                font=NOTE_FONT, size=24, color=FROST)
    for x, y in ((730, 490), (700, 300), (630, 290), (740, 410)):    # the circles stay on screen
        await point_to(hand, x, y, time=0.95, ease="ease_in_out")
    st.held = False
    st.swing = 1.0
    leave(note, time=0.4)
    hand.fade_out(0.4)
    st.parts = [top, a, b, segment, c1, c2, bisector, crossings, mid]
    st.a, st.b = a, b


# ---- 0:25  labels, bars, colours: anything can be a formula ----

async def labels(t):
    code = st.code
    a, b = st.a, st.b
    code.clear()
    size = Text("", font=SMALL_FONT, font_size=20, color=FROST)
    size["text"] @= lambda: f"{distance(a, b):.0f} px"
    size["center"] @= lambda: Vec2(middle_point(a, b)) + (0, -26)
    size.fade_in(0.5)
    await code.say('size["text"] @= lambda: f"{distance(a, b):.0f} px"', speed=CODE_SPEED)
    await at(t + 3.0)
    # a ship flies in, a bar rides above it
    st.life = 100
    hero = Sprite("space/playerShip1_red.png", height=46)
    hero["center"] @= lambda: (1010 + 150 * sin(now() * 1.1), 410 + 120 * sin(now() * 2.2))
    hero["angle"] @= lambda: 25 * cos(now() * 1.1)
    hero.fade_in(0.5)
    bar = Rect(width=60, height=7, color="lime green", corner_radius=3)
    bar["center"] @= lambda: hero.center + (0, 40)
    bar["width"] @= lambda: 60 * st.life / 100
    bar["color"] @= lambda: "lime green" if st.life > 35 else FLARE
    code.clear()
    await code.say('bar["center"] @= lambda: hero.center + (0, 40)', speed=CODE_SPEED)
    await code.say('bar["width"] @= lambda: 60 * st.life / 100', speed=CODE_SPEED)

    def hit():
        st.life = max(10, st.life - 9)
        canvas.zap_at(hero, radius=34, amount=0.5, color=EMBER)

    hits = every(0.6, hit)
    await at(t + 6.6)
    # a field of dots: each one's colour is a formula of the ship
    dots = []
    for i in range(9):
        for j in range(7):
            dot = Circle(center=(840 + i * 42, 270 + j * 42), radius=5)
            dot["color"] @= lambda c=dot.center: EMBER if distance(c, hero.center) < 90 else DEEP
            dot.fade_in(0.4 + 0.03 * (i + j))
            dots.append(dot)
    hero.layer = "top"
    bar.layer = "top"
    code.clear()
    await code.say('dot["color"] @= lambda: EMBER if distance(dot.center, hero.center) < 90 else DEEP',
                   speed=CODE_SPEED)
    await at(t + 10.6)          # the dots' line stays to be read
    hits.cancel()
    leave(st.parts[0], time=0.4)
    words = headline("State it once. It stays true.", size=36)
    await at(t + 12.4)
    leave(words, st.parts[1:], size, hero, bar, dots, code.rows, time=0.5)


# ---- 0:37  a vocabulary: each line says what happens ----

async def rules(t):
    Stars(color=FROST, density=0.25, twinkle=0.3)
    Embers(color=EMBER, density=0.25, alpha=0.35)
    window = Window((946, 392), 576, 324, color=ICE)
    code = Code(52, 560, size=17, gap=1.7)
    await window.open()
    clip = t + 0.8                  # the game's clock: each line comes as it happens
    window.play("connect_four/red_row", seconds=15.0)
    words = caption(window, "Connect Four", f"{lines_of('connect_four')} lines of Python")
    for when, line in ((0.2, "board = zone.grid(7, 6)"),
                       (1.4, "next_ball.draggable = True"),
                       (2.6, ""), (2.6, "@drag_to(next_ball)"),
                       (2.6, "def dropped(ball, goal, pos): …"),
                       (4.4, '    new_ball.move_to(…, ease="bounce", on_done=landed)'),
                       (5.8, ""), (5.8, 'notice["text"] @= message'),
                       (7.2, 'ball.glow = "gold"'),
                       (8.8, 'Button(label="New game", on_click=new_game)')):
        await at(clip + when)
        if line:
            await code.say(line, speed=CODE_SPEED)
        else:
            code.rows.append([])
    await at(clip + 10.2)
    note = rise("Each line says what happens.", (330, 150), font=NOTE_FONT, size=28,
                color=FROST)
    # a soft light runs down the lines, one at a time: time to read them again
    for parts in code.rows:
        if not parts:
            continue
        left, right = parts[0].box.left, parts[-1].box.right
        y = parts[0].center.y
        band = Rect(center=((left + right) / 2, y), width=right - left + 16, height=26,
                    color=EMBER.with_alpha(0.16), corner_radius=6)
        band.line = None
        band.fade_in(0.15)
        await wait(0.42)
        band.fade_out(0.35)
    await at(clip + 15.0)
    leave(words, code.rows, note, time=0.5)
    await window.close(time=0.6)


# ---- 0:55  movement and collision ----

EASES = ("linear", "ease_in_out", "bounce", "elastic")


def meteor(x):
    rock = Sprite("space/meteorBrown_big3.png", height=uniform(34, 50), center=(x, 760),
                  group="rocks")
    rock.angle = uniform(0, 360)
    return rock


async def movement(t):
    Stars(color=FROST, density=0.3, twinkle=0.3)
    words = headline("Movement and collision", size=32)
    code = Code(70, 150, size=20)
    # one move, four ways of getting there
    row = []
    for i, ease in enumerate(EASES):
        y = 540 - i * 72
        name = Text(ease, center=(170, y), font=MONO, font_size=18, color=CAPTION)
        dot = Circle(center=(300, y), radius=12, color=ICE if i % 2 else EMBER)
        dot.glow = True
        dot.move_to(980, y, time=1.8, ease=ease, loops="forever", yoyo=True)
        rail = Line(p1=(300, y), p2=(980, y), color=DEEP.with_alpha(0.6), line_width=1)
        row += [name, dot, rail]
    await code.say('dot.move_to(980, y, time=1.8, ease="bounce", loops="forever", yoyo=True)',
                   speed=CODE_SPEED)
    await at(t + 5.0)
    leave(row, time=0.4)
    code.clear()
    # along a track, facing the way it goes
    orbit = Track(points=[(640 + 380 * cos(k * 0.785), 430 + 170 * sin(k * 0.785))
                          for k in range(8)], closed=True, color=DEEP, line_width=2)
    orbit.fade_in(0.5)
    ship = Sprite("space/playerShip1_red.png", height=44)
    ship.tail = Tail(color=EMBER, size=4)
    ship.move_along(orbit, time=4, loops="forever", face=True)
    await code.say('ship.move_along(orbit, time=4, loops="forever", face=True)',
                   speed=CODE_SPEED)
    await at(t + 9.0)
    code.clear()
    # rocks fall; a ledge holds them; the ship shoots them
    ledge = Rect(center=(640, 300), width=460, height=14, color=FROST.with_alpha(0.8),
                 corner_radius=6, group="ledge")
    ledge.mass = STATIC
    ledge.fade_in(0.3)
    leave(words, time=0.4)          # the rocks fall from the top: the headline makes room
    st.falling = True
    rain = every(0.32, lambda: meteor(uniform(380, 900)))
    await code.say('group["rocks"].move_by(0, -90 * dt)', speed=CODE_SPEED)
    await at(t + 10.8)
    resolve("rocks", "ledge")
    await code.say('ledge.mass = STATIC', speed=CODE_SPEED)
    await code.say('resolve("rocks", "ledge")', speed=CODE_SPEED)

    def hit(shot, rock):
        canvas.burst_at(rock, radius=50)
        shot.destroy()
        rock.destroy()

    await at(t + 12.8)
    collide("shots", "rocks")(hit)

    def fire():
        rocks = list(group["rocks"])
        if rocks:
            target = min(rocks, key=lambda r: distance(r.center, ship.center))
            shot = Sprite("space/laserBlue03.png", height=26, center=ship.center,
                          group="shots")
            shot.angle = heading(ship, target) - 90
            shot.move_to(target.center, speed=900, on_done=shot.destroy)

    guns = every(0.22, fire)
    await code.say('@collide("shots", "rocks")', speed=CODE_SPEED)
    await code.say("def hit(shot, rock): …", speed=CODE_SPEED)
    await at(t + 17.0)          # the rocks' lines stay to be read
    rain.cancel()
    guns.cancel()
    st.falling = False
    leave(code.rows, orbit, ship, ledge, list(group["rocks"]), time=0.4)


# ---- 1:14  processes: it reads like a script ----

BOSS_CODE = ("async def boss():",
             '    await ufo.move_to(640, 490, time=2, ease="ease_out")',
             "    await wait(0.5)",
             "    ufo.pop(scale=1.4)",
             "    await until(lambda: st.gate_open)",
             '    await ufo.move_to(640, 820, time=1.2, ease="ease_in")')
LAMPS_CODE = ("async def lamps():",
              "    for lamp in row:",
              '        lamp.color = "gold"',
              "        await wait(0.6)",
              "    after(1.0, open_gate)")


class Script:
    """A script shown as code, with a playhead: an ember band on the line that
    runs now (mark(n) moves it; mark(None) takes it away)."""

    def __init__(self, lines, left, top, size=17, gap=1.75):
        self.code = Code(left, top, size=size, gap=gap)
        self.lines = lines
        self.left, self.top, self.step = left, top, size * gap
        self.width = max(len(line) for line in lines) * self.code.cell + 24
        self.band = Rect(width=self.width, height=self.step, corner_radius=6,
                         color=EMBER.with_alpha(0.22),
                         center=(left + self.width / 2 - 12, top - size * 0.6))
        self.band.line = None
        self.band.visible = False

    async def show(self):
        for line in self.lines:
            await self.code.say(line, speed=140)

    def mark(self, n):
        if n is None:
            self.band.fade_out(0.3)
            return
        y = self.top - n * self.step - self.code.size * 0.6     # the middle of line n
        self.band.visible = True
        self.band.move_to(self.left + self.width / 2 - 12, y, time=0.12, ease="ease_out")


async def processes(t):
    Stars(color=FROST, density=0.3, twinkle=0.3)
    words = headline("When it happens", y=690, size=30)
    # the stage: a row of lamps, a gate at the top, a ship that will come in
    st.gate_open = False
    row = [Circle(center=(420 + k * 63, 572), radius=11, color=DEEP) for k in range(8)]
    for lamp in row:
        lamp.glow = True
        lamp.fade_in(0.4)
    gate = [Rect(center=(640 + side * 52, 622), width=100, height=16, corner_radius=5,
                 color=FROST.with_alpha(0.85)) for side in (-1, 1)]
    ufo = Sprite("space/ufoYellow.png", height=60, center=(-80, 520))
    ufo.tail = Tail(color=ICE, size=4)
    left = Script(BOSS_CODE, 40, 330)
    right = Script(LAMPS_CODE, 700, 330)
    runs = Code(40, 395, size=19)
    await left.show()
    await right.show()
    await runs.say("run_task(boss)", speed=CODE_SPEED)
    runs.left += 300
    await runs.say("run_task(lamps)", speed=CODE_SPEED, row=0)
    await at(t + 3.0)

    def open_gate():
        for part, side in zip(gate, (-1, 1)):
            part.move_by(side * 90, 0, time=0.5, ease="ease_out")
        canvas.hit_at(640, 622, color=FROST)
        st.gate_open = True

    async def boss():
        left.mark(1)
        await ufo.move_to(640, 490, time=2, ease="ease_out")
        left.mark(2)
        await wait(0.5)
        left.mark(3)
        ufo.pop(scale=1.4)
        left.mark(4)
        await until(lambda: st.gate_open)
        left.mark(5)
        await ufo.move_to(640, 820, time=1.2, ease="ease_in")
        left.mark(None)

    async def lamps():
        right.mark(1)
        await wait(0.15)
        for lamp in row:
            right.mark(2)
            lamp.color = "gold"
            await wait(0.12)
            right.mark(3)
            await wait(0.6 - 0.12)
        right.mark(4)
        after(1.0, open_gate)
        await wait(0.6)
        right.mark(None)

    run_task(boss)
    run_task(lamps)
    await at(t + 11.4)
    note = rise("It reads like a script: what happens, when it happens.", (640, 460),
                font=NOTE_FONT, size=26, color=FROST)
    await at(t + 16.1)
    leave(words, note, left.code.rows, right.code.rows, runs.rows, row, gate, time=0.4)


# ---- 1:12  click, drag, widgets ----

async def interface(t):
    Stars(color=FROST, density=0.25, twinkle=0.3)
    words = headline("Click, drag, widgets", y=690, size=30)
    window = Window((900, 380), 640, 360, color=ICE)
    code = Code(40, 540, size=17, gap=1.9)
    await window.open()
    clip = t + 0.8
    window.play("teaser2_ui/tour", seconds=UI_SECONDS - 0.5)
    for when, _, line in UI_STEPS:
        if not line:
            continue
        await at(clip + when - 0.3)         # the line just before the hand does it
        await code.say(line, speed=CODE_SPEED)
    await at(clip + UI_SECONDS - 0.6)
    leave(words, code.rows, time=0.4)
    await window.close(time=0.4)


# ---- 0:44  debug mode, in the hush of the music ----

class Keycap:
    """Ctrl + Shift + a key, drawn as keys, and what it does."""

    def __init__(self, key, what, center):
        x, y = center
        self.parts = []
        left = x
        for label in ("Ctrl", "Shift", key):
            text = Text(label, font=SMALL_FONT, font_size=18, color=FROST)
            width = max(34, text.box.width + 20)
            cap = Rect(center=(left + width / 2, y), width=width, height=34, corner_radius=7,
                       color=PANEL)
            cap.line = ICE.with_alpha(0.8) if label == key else DEEP
            cap.line_width = 1.5
            text.center = cap.center
            self.parts += [cap, text]
            left += width + 8
        note = Text(what, font=NOTE_FONT, font_size=20, color=FROST)
        note.center = (left + 12 + note.box.width / 2, y)
        self.parts.append(note)
        # the row is centred on center: shift it all by half its width
        shift = (note.box.right - x) / 2
        for p in self.parts:
            p.center = (p.center.x - shift, p.center.y)
            p.fade_in(0.25)
        self.parts[-3].pop(scale=1.15)     # the key itself

    def leave(self):
        leave(self.parts, style="fade", time=0.12)     # quick: the next keycap takes its place


KEYS = {"7": "hitboxes and overlays"}
TIME = ["pause", "¼ speed", "running again"]       # P cycles through them
ZOOM = ["zoom out: the world past the screen", "back to 100 %", None]   # 50 %, 25 %, 100 %


async def debug(t):
    Stars(color=FROST, density=0.25, twinkle=0.3)
    words = headline("Debug Mode", y=690, size=30)
    window = Window((640, 396), 864, 486, color=FROST)
    await window.open()
    lead = t + 0.8                          # the clip starts here: chords from it
    await at(lead)
    take = TAKES["runner/debug"]
    window.play("runner/debug", seconds=take["seconds"] - 0.6)
    shown = None
    presses = {"P": 0, "8": 0}
    for when, key in TEASER2_DEBUG_CHORDS:
        await at(lead + when)
        if key in presses:
            what = (TIME if key == "P" else ZOOM)[presses[key] % 3]
            presses[key] += 1
        else:
            what = KEYS[key]
        if what is None:                    # 25 % on the way back: no keycap of its own
            continue
        if shown:
            shown.leave()
        shown = Keycap(key, what, (640, 112))
    await at(lead + take["seconds"] - 0.6)
    leave(words, time=0.4)
    if shown:
        shown.leave()
    await window.close(time=0.5)


# ---- 0:56  the catalogue: backgrounds, screen effects, impacts, looks ----

def catalog(section):
    """How many entries the API Guide's catalogue has in a section ("Background",
    "Post", "Impacts", "Visual")."""
    with open(os.path.join(REPO, "docs", "en", "guide", "symbols.json")) as f:
        symbols = json.load(f)["symbols"]
    return sum(1 for s in symbols if s.get("catalog") and s["sectionTitle"] == section)


def tag(text, center, size=24):
    """A short piece of code under or over something, in the editor colours."""
    x, y = center
    probe = Text("M" * 20, top_left=(0, -400), font=MONO, font_size=size)
    cell = probe.box.width / 20
    probe.destroy()
    left = x - len(text) * cell / 2
    parts = []
    for col, piece, kind in pieces(text):
        t = Text(piece, top_left=(left + col * cell, y + size * 0.6), font=MONO,
                 font_size=size, color=SYNTAX[kind])
        t.fade_in(0.2)
        parts.append(t)
    return parts


def stage():
    """The scene the backgrounds and screen effects play behind and over: a ship
    on a figure eight, a ring of shapes in different looks going round it."""
    looks = [Neon(ICE), Metal(), Gel(EMBER), Rim(FROST), Sphere(ICE), Aura(EMBER)]
    things = []
    for k, look in enumerate(looks):
        shape = RegularPolygon(n=3 + k % 4, radius=30, color=[ICE, EMBER, FROST][k % 3])
        shape.visual = look
        shape["center"] @= lambda k=k: (640 + 250 * cos(now() * 0.6 + k * 1.047),
                                        370 + 130 * sin(now() * 0.6 + k * 1.047))
        shape["angle"] @= lambda k=k: now() * 40 + k * 30
        shape.fade_in(0.5)
        things.append(shape)
    ship = Sprite("space/playerShip1_red.png", height=56)
    ship["center"] @= lambda: (640 + 120 * sin(now() * 1.2), 370 + 60 * sin(now() * 2.4))
    ship["angle"] @= lambda: 20 * cos(now() * 1.2)
    ship.tail = Tail(color=EMBER, size=4)
    ship.fade_in(0.5)
    return things + [ship]


async def backgrounds(t):
    st.host = stage()
    words = headline(f"{catalog('Background')} backgrounds", size=32)
    st.words = words
    shown, label = None, []
    for name, make in (("Stardust()", lambda: Stardust(color=DEEP, color2=EMBER)),
                       ("Borealis()", lambda: Borealis(color=ICE)),
                       ("Plasma()", lambda: Plasma(color=DEEP)),
                       ("ChurningClouds()", lambda: ChurningClouds(color=DEEP, color2=EMBER)),
                       ("FilamentField()", lambda: FilamentField(color=ICE)),
                       ("Floor()", lambda: Floor(color=ICE)),
                       ("Tunnel()", lambda: Tunnel(color=ICE)),
                       ("Nebula()", lambda: Nebula(color="dark cyan",
                                                   color2="midnight blue"))):
        if shown:
            shown.remove()
        leave(label, style="fade", time=0.15)
        shown = make()
        label = tag(name, (640, 120))
        await wait(0.69)
    st.label = label


POSTS = (("Crt()", lambda: [Crt()]),
         ("Pixelate(cell=8)", lambda: [Pixelate(cell=8)]),
         ("GodRays()", lambda: [GodRays()]),
         ("MotionTrail()", lambda: [MotionTrail()]),
         ("Haze()", lambda: [Haze()]),
         ("Vortex()", lambda: [Vortex()]),
         ("Grain()", lambda: [Grain()]),
         ("Scanlines() + Haze() + Grain()", lambda: [Scanlines(), Haze(), Grain()]))


async def screen_effects(t):
    leave(st.words, time=0.3)
    words = headline(f"{catalog('Post')} screen effects", size=32)
    label = st.label
    on = []
    for name, make in POSTS:
        for post in on:
            post.remove()
        leave(label, style="fade", time=0.15)
        on = make()
        label = tag(name, (640, 120))
        await wait(1.3 if "+" in name else 0.62)
    for post in on:
        post.remove()
    leave(words, label, st.host, time=0.5)


IMPACTS = (("explosion_at", lambda x, y: canvas.explosion_at(x, y, amount=1.6, flash=False,
                                                              shake=False)),
           ("fireworks_at", lambda x, y: canvas.fireworks_at(x, y, color=EMBER, color2=FROST,
                                                              radius=130, amount=1.4)),
           ("zap_at", lambda x, y: canvas.zap_at(x, y, color=ICE, radius=120, amount=1.4)),
           ("ripple_at", lambda x, y: canvas.ripple_at(x, y, radius=240, amount=0.8,
                                                        shake=False)),
           ("bubbles_at", lambda x, y: canvas.bubbles_at(x, y, color=ICE, count=40,
                                                          amount=1.5)),
           ("debris_at", lambda x, y: canvas.debris_at(x, y, color=FROST, radius=110,
                                                        amount=1.5)),
           ("burst_at", lambda x, y: canvas.burst_at(x, y, radius=100, amount=1.5)),
           ("hit_at", lambda x, y: canvas.hit_at(x, y, color=FROST, radius=100, amount=1.5)))


async def impacts(t):
    Stars(color=FROST, density=0.3, twinkle=0.3)
    words = headline(f"{catalog('Impacts')} impacts", size=32)
    labels_ = []
    for k, (name, boom) in enumerate(IMPACTS):
        x, y = 205 + (k % 4) * 290, 470 if k < 4 else 230
        boom(x, y)
        labels_.append(tag(f"canvas.{name}(…)", (x, y - 110), size=17))
        await wait(0.55)
    await at(t + 4.4)
    leave(words, labels_, time=0.4)


LOOKS = ("ElectricField", "Flame", "Rim", "Metal", "Halo")     # looks a sprite takes too


async def looks(t):
    Nebula(color="dark cyan", color2="midnight blue", alpha=0.6)
    words = headline(f"{catalog('Visual')} looks, on any shape or sprite", size=32)
    ball = Circle(center=(300, 400), radius=70, color="royal blue")
    star = RegularPolygon(n=5, center=(640, 400), radius=85, color="gold")
    plane = Sprite("plane/Fly1.png", height=110, center=(980, 400))
    hosts = (ball, star, plane)
    for thing in hosts:
        thing.fade_in(0.4)
    label = []
    for name in LOOKS:
        for thing in hosts:
            thing.visual = globals()[name]()
        leave(label, style="fade", time=0.15)
        label = tag(f"thing.visual = {name}()", (640, 210), size=22)
        await wait(0.62)
    # every look takes its knobs: a slider turns one, the look follows
    st.heat = 0.2
    slider = Slider(st["heat"], label="amount", min_value=0, max_value=1, top_left=(500, 160))
    leave(label, style="fade", time=0.15)
    label = tag("thing.visual = Flame(amount=st.heat)", (640, 210), size=22)
    st.shown_heat = None

    def follow():
        heat = round(st.heat, 1)        # a look is shared: build one per step of the knob
        if heat != st.shown_heat:
            st.shown_heat = heat
            for thing in hosts:
                thing.visual = Flame(amount=heat)

    knob = every(1 / 30, follow)
    await tween(st["heat"], 1.0, time=1.0, ease="ease_in_out")
    await tween(st["heat"], 0.7, time=0.55, ease="ease_in_out")
    knob.cancel()
    leave(words, label, hosts, time=0.5)
    after(0.4, slider.destroy)      # a widget has no dissolve


# ---- 1:18  games, and many more ----

async def games(t):
    Borealis(color=DEEP, alpha=0.35)
    Stars(color=FROST, density=0.4, twinkle=0.4)
    words = headline("Games made with Scena", y=640, size=32)
    left = Window((340, 380), 560, 315, color=ICE)
    right = Window((940, 380), 560, 315, color=EMBER)
    run_task(left.open)
    await right.open()
    left.play("race/serpentine", seconds=5.5, start=RACE_IN)
    right.play("guardian/waves", seconds=5.5, start=GUARDIAN_IN)
    notes = (caption(left, "Race", f"{lines_of('race')} lines of Python", ICE)
             + caption(right, "Light Guardian", f"{lines_of('guardian')} lines of Python",
                       EMBER))
    await at(t + 6.3)
    leave(words, notes, time=0.4)
    run_task(left.close)
    await right.close()


async def many_more(t):
    Stars(color=FROST, density=0.3, twinkle=0.3)
    words = headline("And many more", y=690, size=28)
    windows = []
    for k, (take, start) in enumerate(WALL):
        x, y = 240 + (k % 3) * 400, 563 - (k // 3) * 222
        window = Window((x, y), 352, 198, color=[ICE, FROST, EMBER][(k + k // 3) % 3])
        windows.append(window)
        run_task(window.open)
        await wait(0.07)
    await wait(0.85)
    for window, (take, start) in zip(windows, WALL):
        window.play(take, seconds=4.5, start=start)
    await at(t + 5.9)
    leave(words, time=0.3)
    for window in windows[:-1]:
        run_task(window.close)
    await windows[-1].close()


# The clips' in-points (seconds into their recordings).
RACE_IN = 14.0
GUARDIAN_IN = 65.5     # wave 5, up to its big explosion
HUNDRED_IN = 25.0      # the spiral becomes the tunnel
WALL = (("string_theory/wall", 2.0), ("canopy/wall", 2.0), ("life/wall", 4.5),
        ("pendulums/wall", 2.0), ("duel/match", 3.0), ("rose_window/wall", 2.0),
        ("loom/wall", 2.0), ("hundred_lines/wall", HUNDRED_IN), ("revoada/wall", 2.0))


# ---- 1:31  100% made with Scena ----

async def finale(t):
    Nebula(color="dark cyan", color2="midnight blue", alpha=0.3)
    Stars(color=FROST, density=0.4, twinkle=0.5)
    canvas.explosion_at(640, 400, amount=1.0, flash=False, shake=False)
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
    await wait(0.5)
    rise("pip install scena", (640, 290), font=SMALL_FONT, size=30, color=FROST)
    await wait(0.4)
    rise("github.com/accmota/Scena", (640, 248), font=SMALL_FONT, size=22, color=CAPTION)
    await wait(0.5)
    rise("a 33-chapter tutorial · the whole API Guide", (640, 196), font=NOTE_FONT, size=20,
         color=FROST)


# ---- the running order ----

CODE_SPEED = 55     # characters a second: a caption is typed, then read

SECTIONS = [
    (0.0, title, False),
    (8.0, formulas, False),
    (25.0, labels, True),       # True: the same act goes on (the construction stays)
    (38.5, rules, False),
    (56.1, movement, False),
    (74.1, processes, False),
    (91.1, interface, False),
    (106.7, debug, False),
    (124.3, backgrounds, False),
    (130.1, screen_effects, True),
    (136.5, impacts, False),
    (141.5, looks, False),
    (146.9, games, False),
    (154.4, many_more, False),
    (MUSIC_SECONDS, finale, False),     # the music has just ended: the card is silent
    (MUSIC_SECONDS + 5.5, None, False),
]
FADE = 0.45         # the screen fades to black and back between two acts


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
            if begin > START:
                canvas.fade_in(FADE)
        await at(begin)
        await scene(begin)
        if now() > end - (FADE if not SECTIONS[n + 1][2] else 0) + 0.05:
            print(f"[teaser2] {scene.__name__} ran {now() - end:.2f} s past its end, {end}")
        # the next act comes in from black (one that goes on from this one does not)
        if SECTIONS[n + 1][1] is not None and not SECTIONS[n + 1][2]:
            await at(end - FADE)
            canvas.fade_out(FADE)
    # no fade at the end: the video ends on the text, so the install line can be read


def update(dt):
    st.frame += 1
    if st.falling:
        group["rocks"].move_by(0, -90 * dt)
        group["rocks"].filter(lambda rock: rock.center.y < -60).destroy()


run_task(show)
run(Card)
