"""What the promo videos share: the palette, words, typed code, clip windows,
the cue sheet and the running order. From teaser 2 (teaser2/teaser2.py), made
to work at any design size (the vertical cut is 720 x 1280).

    from promo_kit import *
    kit.setup(cues=os.path.join(work("x"), "cues.json"), width=1280, height=720)

Every frame is drawn by the program; a clip goes into a Window: the window
leaves a black pane and writes its cue (when, where, which recording) for
promo_composite.py.
"""

import io
import json
import keyword
import os
import tokenize
from math import sin, cos
from scena import *

from paths import REPO

TITLE_FONT = "fonts/Quantico-Bold.ttf"
NOTE_FONT = "fonts/Quantico-Italic.ttf"
SMALL_FONT = "fonts/Quantico-Regular.ttf"
MONO = "fonts/JetBrainsMonoNLNerdFontMono-Regular.ttf"

# ---- the palette: ember and ice, as in the first teasers ----

NIGHT = "#071318"
PANEL = "#0b1d24"
DEEP = Color("dark cyan")
ICE = Color("turquoise")
FROST = Color("light cyan")
EMBER = Color("coral")
FLARE = Color("tomato")
CAPTION = FROST.with_alpha(0.7)
SYNTAX = {"keyword": EMBER, "string": Color("peach puff"), "number": FLARE,
          "comment": Color("slate gray"), "decorator": ICE, "call": Color("aquamarine"),
          "op": Color("light steel blue"), "name": FROST, "fold": EMBER}


class _Kit:
    W = 1280
    H = 720
    cues = None

    def setup(self, cues, width=1280, height=720, start=0.0):
        self.W, self.H, self.cues = width, height, cues
        self.start = start
        st.t0 = 0           # clock.time when the video starts (minus start)
        st.frame = 0        # frames drawn: the cue sheet records it
        st.cues = []


kit = _Kit()


class Card(Act):
    """A blank act. change_act(Card) sweeps the last section away."""


def now():
    """Seconds into the video."""
    return clock.time - st.t0


async def at(t):
    """Wait until t seconds into the video."""
    await wait(max(0.0, t - now()))


def video_time():
    """The time of this frame in the recording (frame st.frame - 1 at 60 fps)."""
    return (st.frame - 1) / 60


def cue(kind, **data):
    """One line of the cue sheet: written at once, so a stopped run keeps it."""
    st.cues.append(dict(kind=kind, time=round(now(), 3), video_time=round(video_time(), 4),
                        **data))
    with open(kit.cues, "w") as f:
        json.dump(st.cues, f, indent=1)


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


def guide_symbols():
    with open(os.path.join(REPO, "docs", "en", "guide", "symbols.json")) as f:
        return json.load(f)["symbols"]


def catalog(section):
    """How many entries the API Guide's catalogue has in a section."""
    return sum(1 for s in guide_symbols() if s.get("catalog") and s["sectionTitle"] == section)


def params_of(name):
    """The parameters the API Guide lists for a catalogue entry."""
    for s in guide_symbols():
        if s.get("catalog") and s["name"] == name:
            return [p["name"] for p in s.get("params", [])]
    return []


# ---- words ----

def rise(text, center, font=TITLE_FONT, size=40, color="white", time=0.8, layer=None):
    """A line that is born a little low and rises into place as it fades in."""
    x, y = center
    line = Text(text, center=(x, y - 20), font=font, font_size=size, color=color)
    if layer:
        line.layer = layer
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


def arrive(text, center, size=40, color="white", font=TITLE_FONT, step=0.045, drop=18):
    """Letters that arrive one after another, each settling from a little above."""
    row = letters(text, center, font, size, color)
    for i, t in enumerate(row):
        t.visible = False
        t.center = (t.home.x, t.home.y + drop)

        def show(t=t):
            if not t.is_alive:          # the act ended before this letter's turn
                return
            t.visible = True
            t.fade_in(0.5)
            t.move_to(t.home, time=0.6, ease="ease_out")

        after(i * step, show)
    return row


def underline(text, color=EMBER, gap=8, width=2.5, time=1.0, layer=None, rise_by=0):
    """A line under a Text that grows out from its middle. rise_by: how far the
    text is still to rise (a rise() line is born 20 lower)."""
    box = text.box
    y = box.bottom + rise_by - gap
    under = Track(points=[(box.left, y), (box.right, y)], smooth=0, color=color,
                  line_width=width)
    if layer:
        under.layer = layer
    under.begin = 0.5
    under.end = 0.5
    tween(under["begin"], 0, time=time, ease="ease_out")
    tween(under["end"], 1, time=time, ease="ease_out")
    return under


def headline(text, y=None, size=34, color="white", x=None, layer=None, sub=None, rule=True):
    """A section's name, underlined in ember (at the top by default). sub: a
    smaller line under the name, above the underline; rule=False: no underline
    (content right under it)."""
    y = kit.H - 56 if y is None else y
    x = kit.W / 2 if x is None else x
    line = rise(text, (x, y), size=size, color=color, layer=layer)
    if sub is None:
        return [line, underline(line, layer=layer)]
    second = note(sub, (x, line.box.bottom + 2), size=round(size * 0.6), layer=layer)
    if not rule:
        return [line, second]
    return [line, second, underline(second, layer=layer, rise_by=20)]


def note(text, center, size=26, color=FROST, layer=None):
    return rise(text, center, font=NOTE_FONT, size=size, color=color, layer=layer)


def leave(*things, style="noise", time=0.6):
    for thing in things:
        if isinstance(thing, (list, tuple)):
            leave(*thing, style=style, time=time)
        elif thing is not None and thing.is_alive:
            thing.dissolve_out(time, style=style)


# ---- code: tokens in the editor colours ----

FSTRING = {getattr(tokenize, n) for n in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END")
           if hasattr(tokenize, n)}


def pieces(line):
    """(column, text, kind) of each token of one line of code: its colours.
    "…" folds what the line leaves out (drawn as one character, in ember)."""
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
            after_ = toks[n + 1].string if n + 1 < len(toks) else ""
            before = toks[n - 1].string if n else ""
            kind = ("keyword" if keyword.iskeyword(tok.string) else
                    "decorator" if before == "@" else
                    "call" if after_ == "(" else "name")
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


def mono_cell(size):
    probe = Text("M" * 20, top_left=(0, -4000), font=MONO, font_size=size)
    cell = probe.box.width / 20
    probe.destroy()
    return cell


class Code:
    """Lines of code at a place on the screen, each typed in when it is said.
    A line is Texts, one per token, in the editor colours."""

    def __init__(self, left, top, size=20, gap=1.5, layer=None):
        self.left, self.top, self.size = left, top, size
        self.step = size * gap
        self.cell = mono_cell(size)
        self.layer = layer
        self.rows = []

    def row_y(self, row):
        return self.top - row * self.step

    def _parts(self, line, row):
        y = self.row_y(row)
        parts = []
        for col, text, kind in pieces(line):
            t = Text("", top_left=(self.left + col * self.cell, y), font=MONO,
                     font_size=self.size, color=SYNTAX[kind])
            if self.layer:
                t.layer = self.layer
            t.whole = text
            parts.append(t)
        return parts

    async def say(self, line, row=None, speed=90):
        """Type line at row (the next one by default); returns its Texts."""
        row = len(self.rows) if row is None else row
        parts = self._parts(line, row)
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

    def show(self, lines, fade=0.3):
        """All lines at once (no typing), fading in."""
        for line in lines:
            parts = self._parts(line, len(self.rows))
            for t in parts:
                t.text = t.whole
                if fade:
                    t.fade_in(fade)
            self.rows.append(parts)
        return self.rows

    def width(self):
        return max((p[-1].box.right - self.left for p in self.rows if p), default=0)

    def clear(self, style="fade", time=0.4):
        leave(self.rows, style=style, time=time)
        self.rows = []


def tag(text, center, size=24, box=False, color=EMBER, layer=None):
    """A short piece of code centred at a point, in the editor colours; with
    box=True it sits on a small panel (a label on the machine)."""
    x, y = center
    cell = mono_cell(size)
    left = x - len(text) * cell / 2
    parts = []
    if box:
        plate = Rect(center=(x, y), width=len(text) * cell + size * 1.2, height=size * 1.7,
                     corner_radius=size * 0.4, color=PANEL)
        plate.line = color
        plate.line_width = 1.5
        if layer:
            plate.layer = layer
        plate.fade_in(0.2)
        parts.append(plate)
    for col, piece, kind in pieces(text):
        t = Text(piece, top_left=(left + col * cell, y + size * 0.62), font=MONO,
                 font_size=size, color=SYNTAX[kind])
        if layer:
            t.layer = layer
        t.fade_in(0.2)
        parts.append(t)
    return parts


# ---- knobs: a post effect or background is assigned, not tweened ----

def knob_to(thing, name, value, time=0.5, back=False):
    """Turn thing.name to value over time (a smoothstep), each frame; with
    back=True it goes back to where it was, over the same time."""
    async def turn():
        start = getattr(thing, name)
        legs = ((start, value), (value, start)) if back else ((start, value),)
        for a, b in legs:
            frames = max(1, int(time * 60))
            for n in range(1, frames + 1):
                u = n / frames
                setattr(thing, name, a + (b - a) * u * u * (3 - 2 * u))
                await wait(1 / 60)
    return run_task(turn)


# ---- the windows the clips play in ----

def caption(window, title, text, color=FROST):
    """The game's name under its window, and a note beside it."""
    x, y = window.center
    y -= window.height / 2 + 34
    name = Text(title, center=(x, y), font=TITLE_FONT, font_size=24, color=color)
    lines = Text(text, center=(x, y), font=NOTE_FONT, font_size=17, color=CAPTION)
    gap = 16
    left = x - (name.box.width + gap + lines.box.width) / 2
    name.center = (left + name.box.width / 2, y)
    lines.center = (left + name.box.width + gap + lines.box.width / 2, y - 1)
    for line in (name, lines):
        line.center = (line.center.x, line.center.y - 14)
        line.move_by(0, 14, time=0.7, ease="ease_out")
        line.fade_in(0.7)
    return [name, lines]


class Window:
    """A frame that draws itself, opens on a black pane and holds a clip.

    The pane is plain black: the clip is laid over exactly that rectangle
    (the cue sheet has it in design units, from the top left)."""

    def __init__(self, center, width, height, color=FROST, comets=True):
        self.center = center
        self.width = width
        self.height = height
        self.with_comets = comets
        self.frame = Rect(center=center, width=width + 18, height=height + 18,
                          corner_radius=12)
        self.frame.visible = False
        self.border = Track(self.frame, color=color.with_alpha(0.55), line_width=2)
        self.border.end = 0
        self.pane = Rect(center=center, width=width, height=2, color="black")
        self.pane.line = None
        self.pane.visible = False
        self.comets = []

    def rect(self):
        x, y = self.center
        return [x - self.width / 2, kit.H - y - self.height / 2, self.width, self.height]

    async def open(self, time=0.8):
        tween(self.border["end"], 1, time=time * 0.6, ease="ease_in_out")
        await wait(time * 0.45)
        self.pane.visible = True
        await tween(self.pane["height"], self.height, time=time * 0.55, ease="ease_out")
        if not self.with_comets:
            return
        # a comet runs round the frame: three windows of the outline, one head
        for length, alpha, width in ((0.14, 0.25, 2), (0.06, 0.6, 3), (0.012, 1, 4)):
            comet = Track(self.frame, color=self.border.color.with_alpha(alpha),
                          line_width=width)
            comet["end"] @= lambda: clock.time * 0.12 % 1
            comet["begin"] @= lambda length=length: (clock.time * 0.12 - length) % 1
            self.comets.append(comet)

    def play(self, recording, seconds, start=0.0, crop=None, **extra):
        """From now the pane holds a recording (videos/recordings/<recording>.mp4) for
        seconds, from start seconds into it. crop: [x, y, w, h] of the source
        (its pixels) to fill the pane with; extra goes on the cue (a mask)."""
        cue("clip", clip=recording, recording=f"{recording}.mp4", start=start,
            seconds=seconds, rect=self.rect(), **({"crop": crop} if crop else {}), **extra)

    async def close(self, time=0.6):
        for comet in self.comets:
            comet.fade_out(time * 0.5)
        tween(self.pane["height"], 2, time=time * 0.6, ease="ease_in")
        await tween(self.border["begin"], 1, time=time, ease="ease_in_out")
        if self.pane.is_alive:          # a close still running when the next act sweeps
            self.pane.visible = False


# ---- a drawn mouse pointer ----

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
    return Vec2(arrow.center.x, arrow.center.y) + arrow.to_tip


def point_to(arrow, x, y, **move):
    return arrow.move_to(x - arrow.to_tip.x, y - arrow.to_tip.y, **move)


# ---- the end card ----

async def made_with_scena(lines=("pip install scena", "github.com/accmota/Scena"),
                          center=None, size=84, note_line=None, music=None,
                          music_at=None):
    """this video was / 100% made with Scena, and the lines under it; music:
    its credit ('"Title" by Author (licence)'), small at the bottom (music_at:
    elsewhere, as on a Short, whose bottom the player covers)."""
    cx, cy = center or (kit.W / 2, kit.H / 2 + 40)
    Nebula(color="dark cyan", color2="midnight blue", alpha=0.3)
    Stars(color=FROST, density=0.4, twinkle=0.5)
    canvas.explosion_at(cx, cy, amount=1.0, flash=False, shake=False)
    row = letters("100% made with Scena", (cx, cy), size=size)
    if row[-1].box.right - row[0].box.left > kit.W - 60:      # the vertical cut: two lines
        for t in row:
            t.destroy()
        row = letters("100% made", (cx, cy + size * 0.55), size=size) + \
            letters("with Scena", (cx, cy - size * 0.55), size=size)
    top = max(t.box.top for t in row)
    rise("this video was", (cx, top + size * 0.3), font=NOTE_FONT, size=size * 0.4,
         color=FROST, time=0.7)
    for i, letter in enumerate(row):
        letter.fill = Gradient("white", FROST, ICE, angle=-90) if i < len(row) - 5 else \
            Gradient("white", "peach puff", EMBER, angle=-90)
        home = letter.home
        letter.center = (cx, cy - 20)
        letter.move_to(home, time=0.9, ease="elastic")
    await wait(1.0)
    bottom = min(t.box.bottom for t in row) - 14
    line = Track(points=[(min(t.box.left for t in row), bottom),
                         (max(t.box.right for t in row), bottom)], smooth=0, color=EMBER,
                 line_width=3)
    line.begin = 0.5
    line.end = 0.5
    tween(line["begin"], 0, time=1.0, ease="ease_out")
    tween(line["end"], 1, time=1.0, ease="ease_out")
    await wait(0.5)
    y = bottom - 50
    for k, text in enumerate(lines):
        rise(text, (cx, y), font=SMALL_FONT, size=30 if k == 0 else 22,
             color=FROST if k == 0 else CAPTION)
        y -= 46 if k == 0 else 40
        await wait(0.4)
    if note_line:
        rise(note_line, (cx, y - 10), font=NOTE_FONT, size=20, color=FROST)
    if music:
        await wait(0.4)
        rise(f"Music: {music}", music_at or (cx, 44), font=SMALL_FONT, size=17, color=CAPTION)


# ---- the running order ----

async def run_sections(sections, music=None, fade=0.45, volume=0.9, label="video"):
    """sections: (begin, scene, keep) each, the last (end, None, False). An act
    comes in from black and leaves to black, but one that keeps the last act
    on (keep=True)."""
    await wait(0.3)         # change_act needs the game running
    start = kit.start
    st.t0 = clock.time - start
    if start == 0 and music:
        play_sound(music, volume=volume)
    for n, (begin, scene, keep) in enumerate(sections):
        end = sections[n + 1][0] if n + 1 < len(sections) else begin
        if scene is None:
            break
        if end <= start:
            continue
        if not keep or begin < start:
            change_act(Card)
            if begin > start and fade:
                canvas.fade_in(fade)
        await at(begin)
        await scene(begin)
        nxt = sections[n + 1]
        if now() > end - (fade if not nxt[2] else 0) + 0.05:
            print(f"[{label}] {scene.__name__} ran {now() - end:.2f} s past its end, {end}")
        if nxt[1] is not None and not nxt[2] and fade:
            await at(end - fade)
            canvas.fade_out(fade)
