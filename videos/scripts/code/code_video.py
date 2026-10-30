"""Scena: what the code looks like.

The second video. Each scene types a program into an editor-like panel
and, beside it, a window shows that program running. The code on the
panel is read from the fragment files in this folder, and the window
holds the recording of that very file (record_fragments.py); each window
writes its cue to code_video_cues.json, and the composite script lays the
recordings in, frame-exact.

  the question
  01 three lines                 grow_1
  02 room to grow                grow_2 … grow_4
  03 a whole game                stars_1 … stars_5
  04 formulas                    formulas
  05 geometry                    geometry
  06 groups                      groups
  07 rules and time              boss
  08 looks                       the README's electric hosts (electric_hosts)
  09 mistakes explain themselves oops, then grow_2
  your turn

Music: "The Adventure Begins" by Bart Kelsey (CC-BY 3.0), opengameart.org.

Use
---
    python videos/scripts/code/code_video.py
    python videos/scripts/code/record_fragments.py
    python tools/video/record_game.py videos/scripts/code/code_video.py --seconds 190 \\
        --size 2560x1440 --prores --out $PWD/videos/recordings/masters.nosync/code.mov
    python videos/scripts/kit/teaser_composite.py videos/recordings/masters.nosync/code.mov \\
        videos/recordings/code/scena_code.mp4 videos/recordings/code/cues.json
    python videos/scripts/kit/finish.py videos/recordings/code/scena_code.mp4 promo/scena_code

    CODE_SCENE=formulas python videos/scripts/code/code_video.py    # start at a scene (no music)
"""

import difflib
import io
import json
import keyword
import os
import sys
import textwrap
import tokenize
from scena import *

init(width=1280, height=720, title="Scena: the code")

TITLE_FONT = "fonts/Quantico-Bold.ttf"
NOTE_FONT = "fonts/Quantico-Italic.ttf"
SMALL_FONT = "fonts/Quantico-Regular.ttf"
MONO = "fonts/JetBrainsMonoNLNerdFontMono-Regular.ttf"
MUSIC = "music/little_town_orchestral.ogg"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "kit"))
from paths import work     # noqa: E402
CUES = os.path.join(work("code"), "cues.json")

# ---- the palette: ember and ice, as in the teaser ----

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
          "op": Color("light steel blue"), "name": FROST}

canvas.background = NIGHT
light = Bloom(intensity=0.5)
Vignette(amount=0.6)
Stars(color=FROST, density=0.25, twinkle=0.3)

st.t0 = 0
st.frame = 0
st.cues = []
st.mark = False         # the corner mark, in every scene but the first and the last


class Card(Act):
    """A blank act: change_act(Card) sweeps the last scene away (the corner
    mark, made again at once, stays put)."""

    def setup(self):
        if st.mark:
            corner_mark()


def corner_mark():
    """SCENA and "Python game engine", small, top right (as the other videos keep their name)."""
    name = Text("SCENA", center=(1176, 690), font=TITLE_FONT, font_size=30, color="white")
    name.fill = Gradient("white", FROST, ICE, angle=-90)
    Text("Python game engine", center=(1176, 664), font=NOTE_FONT, font_size=14, color=CAPTION)


def now():
    return clock.time - st.t0


async def at(t):
    await wait(max(0.0, t - now()))


def cue(kind, **data):
    st.cues.append(dict(kind=kind, time=round(now(), 3), **data))
    with open(CUES, "w") as f:
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


# ---- words ----

def rise(text, center, font=TITLE_FONT, size=40, color="white", time=0.8, layer="default"):
    x, y = center
    line = Text(text, center=(x, y - 20), font=font, font_size=size, color=color, layer=layer)
    line.move_by(0, 20, time=time, ease="ease_out")
    line.fade_in(time)
    return line


def leave(*things, style="noise", time=0.6):
    for thing in things:
        if isinstance(thing, list):
            leave(*thing, style=style, time=time)
        elif thing is not None and thing.is_alive:
            thing.dissolve_out(time, style=style)


def chapter(number, title):
    """The scene's name, top left: its number in ember, its title in frost."""
    num = rise(f"{number:02d}", (58, 680), size=26, color=EMBER, time=0.6)
    name = Text(title, top_left=(92, 694), font=TITLE_FONT, font_size=26, color=FROST)
    name.fade_in(0.6)
    return [num, name]


def note(text):
    """A short line under the window."""
    return rise(text, (1006, 180), font=NOTE_FONT, size=22, color=CAPTION, time=0.7)


# ---- the code panel ----

def display(source):
    """The lines shown for a file: blank runs become one blank line."""
    out = []
    for line in source.rstrip("\n").split("\n"):
        if line.strip() or (out and out[-1].strip()):
            out.append(line)
    return out


FSTRING = {getattr(tokenize, n) for n in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END")
           if hasattr(tokenize, n)}
SETUP = ("from ", "import ", "init(", "Wallpaper(", "run()")     # shown at once, not typed


def tokens(lines):
    """(row, col, text, kind) of each token: what colour each piece of the code gets."""
    out = []
    toks = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO("\n".join(lines) + "\n").readline):
            toks.append(tok)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    for n, tok in enumerate(toks):
        row, col = tok.start
        if tok.type == tokenize.NAME:
            after_tok = toks[n + 1].string if n + 1 < len(toks) else ""
            before = toks[n - 1].string if n else ""
            kind = ("keyword" if keyword.iskeyword(tok.string) else
                    "decorator" if before == "@" else
                    "call" if after_tok == "(" else "name")
        elif tok.type == tokenize.STRING or tok.type in FSTRING:
            kind = "string"
        elif tok.type == tokenize.NUMBER:
            kind = "number"
        elif tok.type == tokenize.COMMENT:
            kind = "comment"
        elif tok.type in (tokenize.OP, tokenize.ERRORTOKEN):
            kind = "decorator" if tok.string == "@" else "op"
        else:
            continue
        if tok.start[0] != tok.end[0]:
            continue
        out.append((row - 1, col, tok.string, kind))
    return out


class CodePanel:
    """An editor window that types code in: the lines a step adds are typed
    and marked, the lines it keeps slide to their new places, the ones it
    drops fade; it scrolls to keep the new lines in view."""

    SIZE = 22
    LINE = 31
    ROWS = 17

    def __init__(self, filename, left=24, top=652, width=716, height=600):
        self.left = left
        self.top = top
        self.box = Rect(top_left=(left, top), width=width, height=height, color=PANEL,
                        corner_radius=14)
        self.box.line = DEEP.with_alpha(0.6)
        self.box.line_width = 1.5
        self.box.fade_in(0.5)
        self.chrome = [self.box]
        for i, color in enumerate((FLARE, Color("goldenrod"), ICE)):
            dot = Circle(center=(left + 24 + i * 20, top - 20), radius=6, color=color)
            dot.line = None
            dot.fade_in(0.5)
            self.chrome.append(dot)
        self.name = Text(filename, top_left=(left + 92, top - 10), font=MONO, font_size=16,
                         color=CAPTION)
        self.count = Text("", top_right=(left + width - 18, top - 10), font=SMALL_FONT,
                          font_size=16, color=CAPTION)
        self.chrome += [self.name, self.count]
        probe = Text("M" * 20, top_left=(0, -400), font=MONO, font_size=self.SIZE)
        self.cell = probe.box.width / 20
        probe.destroy()
        self.x0 = left + 26
        self.y0 = top - 52
        self.lines = []         # what is shown: text, and its token Texts
        self.marks = []
        self.scroll = 0
        self.cursor = Rect(width=self.cell * 0.9, height=self.SIZE * 1.1, color=FROST)
        self.cursor.line = None
        self.cursor["visible"] @= lambda: clock.time % 0.9 < 0.55
        self.cursor.set_alpha(0)

    def place(self, row, col=0):
        """The top left of a character cell, for row (of the file) and column."""
        return (self.x0 + col * self.cell, self.y0 - (row - self.scroll) * self.LINE)

    def caret(self, row, col):
        """The cursor at a character cell."""
        x, y = self.place(row, col)
        self.cursor.center = (x + self.cell * 0.5, y - self.SIZE * 0.6)

    def follow(self, row):
        """Scroll down a line at a time while row is below the view (an editor following
        the cursor)."""
        moved = False
        while row >= self.scroll + self.ROWS - 1:
            self.scroll += 1
            moved = True
        if moved:
            for n, line in enumerate(self.lines):
                for p in line["parts"]:
                    self.slide(p, n, p.col, 0.12)
                    p.visible = self.shown(n)
            for mark in self.marks:
                self.slide(mark, mark.row, None, 0.12)
                mark.visible = self.shown(mark.row)

    def slide(self, thing, row, col, time):
        """Move a token Text (col) or a line mark (col None) to its place for row:
        an absolute move, so a newer move replaces an older one without drift."""
        if col is None:
            x, y = self.left + 4, self.place(row)[1] + 6
        else:
            x, y = self.place(row, col)
        thing.move_to(x, y, about=thing.top_left, time=time, ease="ease_out")

    def shown(self, row):
        return self.scroll <= row < self.scroll + self.ROWS

    def _build(self, row, text, colors):
        parts = []
        for col, piece, kind in colors:
            t = Text(piece, top_left=self.place(row, col), font=MONO, font_size=self.SIZE,
                     color=SYNTAX.get(kind, FROST))
            t.col = col
            parts.append(t)
        return dict(text=text, parts=parts)

    async def show(self, path, speed=75, title=None):
        """Bring the panel to the file at path: type what is new, mark it."""
        with open(path) as f:
            source = f.read()
        if title:
            self.name.text = title
        self.count.text = f"{code_lines(path)} lines of Python"
        new = display(source)
        by_row = {}
        for row, col, text, kind in tokens(new):
            by_row.setdefault(row, []).append((col, text, kind))
        for mark in self.marks:
            mark.fade_out(0.4, on_done=mark.destroy)
        self.marks = []
        old = self.lines
        match = difflib.SequenceMatcher(a=[l["text"] for l in old], b=new, autojunk=False)
        kept = {}
        added = []
        for tag, a1, a2, b1, b2 in match.get_opcodes():
            if tag == "equal":
                for k in range(a2 - a1):
                    kept[b1 + k] = old[a1 + k]
            else:
                for line in old[a1:a2]:
                    for p in line["parts"]:
                        p.fade_out(0.35, on_done=p.destroy)
                added += range(b1, b2)
        # scroll so that the new lines are in view, the first of them high up
        if added:
            first, last = added[0], added[-1]
            self.scroll = max(0, min(first - 3, last - self.ROWS + 2, len(new) - self.ROWS))
        self.lines = []
        for row in range(len(new)):
            if row in kept:
                line = kept[row]
                for p in line["parts"]:
                    self.slide(p, row, p.col, 0.45)
                    p.visible = self.shown(row)
                self.lines.append(line)
            else:
                self.lines.append(dict(text=new[row], parts=[]))
        await wait(0.45 if kept else 0.1)
        # type the new lines in, one character after another
        self.cursor.set_alpha(1)
        for row in added:
            if new[row].startswith(SETUP) or not new[row].strip():
                self.follow(row)
                self.lines[row] = self._build(row, new[row], by_row.get(row, []))
                for p in self.lines[row]["parts"]:
                    p.fade_in(0.25)
                continue
            self.follow(row)
            band = Rect(top_left=(self.left + 4, self.place(row)[1] + 6),
                        width=708, height=self.LINE, color=EMBER.with_alpha(0.09))
            band.line = None
            bar = Rect(top_left=(self.left + 4, self.place(row)[1] + 6), width=4,
                       height=self.LINE, color=EMBER)
            bar.line = None
            band.row = bar.row = row
            self.marks += [band, bar]
            line = self._build(row, new[row], by_row.get(row, []))
            for p in line["parts"]:
                p.full = p.text
                p.text = ""
            self.lines[row] = line
            typed = 0.0
            for p in line["parts"]:
                while len(p.text) < len(p.full):
                    typed += speed / 60
                    n = int(typed)
                    if n:
                        typed -= n
                        p.text = p.full[:len(p.text) + n]
                        self.caret(row, p.col + len(p.text))
                    await wait(1 / 60)
            self.caret(row, len(new[row]))
            await wait(0.05)
        self.cursor.set_alpha(0)

    def clear(self, style="wipe"):
        for line in self.lines:
            leave(line["parts"], style="fade", time=0.4)
        leave(self.marks, style="fade", time=0.4)
        leave(self.chrome, style=style, time=0.5)
        self.cursor.destroy()


# ---- the windows the programs play in ----

class Window:
    """A frame that draws itself, opens on a black pane and holds a recording.
    The pane is plain black: the composite lays the recording over it."""

    def __init__(self, center=(1006, 400), width=456, height=342, color=FROST):
        self.center = center
        self.width = width
        self.height = height
        self.frame = Rect(center=center, width=width + 16, height=height + 16,
                          corner_radius=10)
        self.frame.visible = False
        self.border = Track(self.frame, color=color.with_alpha(0.55), line_width=2)
        self.border.end = 0
        self.pane = Rect(center=center, width=width, height=2, color="black")
        self.pane.line = None
        self.pane.visible = False
        self.comets = []
        self.playing = None

    async def open(self, time=0.8):
        tween(self.border["end"], 1, time=time * 0.6, ease="ease_in_out")
        await wait(time * 0.45)
        self.pane.visible = True
        await tween(self.pane["height"], self.height, time=time * 0.55, ease="ease_out")
        for length, alpha, width in ((0.14, 0.25, 2), (0.06, 0.6, 3), (0.012, 1, 4)):
            comet = Track(self.frame, color=self.border.color.with_alpha(alpha),
                          line_width=width)
            comet["end"] @= lambda: clock.time * 0.12 % 1
            comet["begin"] @= lambda length=length: (clock.time * 0.12 - length) % 1
            self.comets.append(comet)

    def play(self, name):
        """From now the pane shows the recording of name (until the next play or stop)."""
        self.stop()
        x, y = self.center
        self.playing = dict(clip=name, start=now(), video_time=round((st.frame - 1) / 60, 4),
                            rect=[x - self.width / 2, 720 - y - self.height / 2,
                                  self.width, self.height])
        canvas.hit_at(self.frame.top_center, style="disc", radius=36, color=FROST)

    def stop(self):
        if self.playing is not None:
            p = self.playing
            cue("clip", clip=p["clip"], video_time=p["video_time"], rect=p["rect"],
                seconds=round(now() - p["start"], 4))
            self.playing = None

    async def close(self, time=0.6):
        self.stop()
        for comet in self.comets:
            comet.fade_out(time * 0.5)
        tween(self.pane["height"], 2, time=time * 0.6, ease="ease_in")
        await tween(self.border["begin"], 1, time=time, ease="ease_in_out")
        self.pane.visible = False


def fragment(name):
    return os.path.join(HERE, name + ".py")


async def steps(panel, window, names, hold, notes=()):
    """Type each fragment in turn and play its recording; hold seconds after each."""
    words = None
    for i, name in enumerate(names):
        await panel.show(fragment(name))
        window.play(name)
        if i < len(notes) and notes[i]:
            leave(words, style="fade", time=0.3)
            words = note(notes[i])
        await wait(hold[i] if isinstance(hold, (list, tuple)) else hold)
    return words


# ---- the scenes ----

async def opening(t):
    q = Text("What does a game look like in", center=(640, 420), font=TITLE_FONT,
             font_size=40, color="white")
    q.dissolve_in(1.0, style="wipe")
    await wait(1.0)
    name = rise("Scena?", (640, 340), size=96, color=FROST)
    name.fill = Gradient("white", FROST, ICE, angle=-90)
    rule = Track(points=[(470, 290), (810, 290)], smooth=0, color=EMBER, line_width=3)
    rule.begin = 0.5
    rule.end = 0.5
    tween(rule["begin"], 0, time=1.0, ease="ease_out")
    tween(rule["end"], 1, time=1.0, ease="ease_out")
    await wait(3.5)
    sub = rise("Short pieces of real code, and what each one does.", (640, 230),
               font=NOTE_FONT, size=24, color=CAPTION)
    await wait(1.8)
    leave(q, name, sub, style="vortex", time=0.6)
    tween(rule["begin"], 0.5, time=0.5)
    tween(rule["end"], 0.5, time=0.5)


async def three_lines(t):
    words = chapter(1, "Three lines")
    panel = CodePanel("first.py")
    window = Window()
    await window.open()
    await panel.show(fragment("grow_1"))
    window.play("grow_1")
    caption = note("A circle in the middle of the window.")
    await wait(6.0)
    return panel, window, words, caption


async def room_to_grow(t, carried):
    panel, window, words, caption = carried
    leave(words, caption, style="fade", time=0.3)
    words = chapter(2, "Room to grow")
    caption = await steps(panel, window, ["grow_2", "grow_3", "grow_4"], hold=[5.0, 5.0, 7.0],
                          notes=["Say more when you want more.", "One of over 100 looks.",
                                 "Movement in one line."])
    await window.close()
    leave(caption, style="fade", time=0.3)
    panel.clear()
    leave(words, style="fade", time=0.4)


async def whole_game(t):
    words = chapter(3, "A whole game, one screen")
    panel = CodePanel("catch_the_stars.py")
    window = Window(color=ICE)
    await window.open()
    caption = await steps(panel, window, ["stars_1", "stars_2", "stars_3", "stars_4", "stars_5"],
                          hold=[5.0, 6.0, 7.0, 7.0, 9.5],
                          notes=["A paddle.", "It moves: no game loop to write.",
                                 "A star every half second.",
                                 "A rule: when the paddle touches a star.",
                                 "A score that keeps itself up to date."])
    await window.close()
    leave(caption, style="fade", time=0.3)
    panel.clear()
    leave(words, style="fade", time=0.4)


async def single(number, title, name, filename, hold, text, window_kw=None, speed=75):
    """A scene with one fragment: type it, play it, hold."""
    words = chapter(number, title)
    panel = CodePanel(filename)
    window = Window(**(window_kw or {}))
    await window.open()
    await panel.show(fragment(name) if os.sep not in name else name, speed=speed)
    window.play(os.path.splitext(os.path.basename(name))[0])
    caption = note(text)
    await wait(hold)
    await window.close()
    leave(caption, style="fade", time=0.3)
    panel.clear()
    leave(words, style="fade", time=0.4)


async def formulas(t):
    await single(4, "Formulas", "formulas", "health_bar.py", 9.5,
                 "Say it once with @=, and it stays true.", speed=90)


async def geometry(t):
    await single(5, "Geometry", "geometry", "bisector.py", 11.0,
                 "Drag a point: the construction follows.", speed=90)


async def groups(t):
    await single(6, "Groups", "groups", "wasps.py", 9.5,
                 "Act on the whole group at once.", speed=90)


async def rules_and_time(t):
    await single(7, "Rules and time", "boss", "boss.py", 10.5,
                 "A boss that reads top to bottom.", speed=100)


async def looks(t):
    await single(8, "Looks", os.path.join(HERE, "electric_hosts.py"), "one_look.py", 7.5,
                 "One look, on a circle, a star and a sprite.",
                 window_kw=dict(center=(1006, 400), width=480, height=160), speed=90)


async def mistakes(t):
    words = chapter(9, "Mistakes explain themselves")
    panel = CodePanel("oops.py")
    window = Window()
    await window.open()
    await panel.show(os.path.join(HERE, "oops.py"), speed=80)
    # the real message, from the real call
    try:
        Circle(radius=40, colour="coral")
        message = "(no error?)"
    except Exception as e:
        message = f"{type(e).__name__}: {e}"
    shown = message.split(" Valid:")[0]
    box = Rect(top_left=(60, 150), width=620, height=96, color="#2a1210", corner_radius=10)
    box.line = FLARE.with_alpha(0.7)
    box.fade_in(0.3)
    err = []
    for i, part in enumerate(textwrap.wrap(shown, 56)):
        line = Text("", top_left=(78, 136 - i * 24), font=MONO, font_size=17,
                    color="peach puff")
        err.append(line)
        for k in range(0, len(part) + 1, 2):
            line.text = part[:k]
            await wait(1 / 60)
    await wait(3.5)
    leave(box, err, style="wipe", time=0.4)
    await panel.show(fragment("grow_2"), speed=80)
    window.play("grow_2")
    caption = note("It names the mistake, and the right word.")
    await wait(5.0)
    await window.close()
    leave(caption, style="fade", time=0.3)
    panel.clear()
    leave(words, style="fade", time=0.4)


async def your_turn(t):
    title = rise("Your turn.", (640, 470), size=84, color="white")
    title.fill = Gradient("white", FROST, ICE, angle=-90)
    await wait(0.8)
    rise("pip install scena", (640, 370), font=MONO, size=30, color=FROST)
    await wait(0.4)
    rise("Tutorial: 33 chapters, English and Português  ·  API Guide", (640, 310),
         font=SMALL_FONT, size=22, color=CAPTION)
    await wait(0.3)
    rise("github.com/accmota/Scena", (640, 270), font=SMALL_FONT, size=22, color=CAPTION)
    await wait(0.6)
    rise("Music: \"The Adventure Begins\" by Bart Kelsey (CC-BY 3.0)", (640, 70),
         font=NOTE_FONT, size=15, color=CAPTION.with_alpha(0.5))
    rise("100% made with Scena", (640, 110), font=TITLE_FONT, size=20, color=EMBER)


# ---- the running order ----

SCENES = [opening, three_lines, room_to_grow, whole_game, formulas, geometry, groups,
          rules_and_time, looks, mistakes, your_turn]
FROM = os.environ.get("CODE_SCENE")     # start at a scene (no music): CODE_SCENE=formulas


async def show():
    await wait(0.3)
    st.t0 = clock.time
    music = play_sound(MUSIC, volume=0.5) if FROM is None else None
    carried = None
    names = [scene.__name__ for scene in SCENES]
    first = names.index(FROM) if FROM else 0
    for scene in SCENES[first:]:
        print(f"[code video] {scene.__name__} at {now():.2f}")
        st.mark = scene not in (opening, your_turn)        # Card.setup reads it
        if scene is room_to_grow and carried is not None:
            await scene(now(), carried)
            continue
        change_act(Card)
        if scene is room_to_grow:
            carried = await three_lines(now())
            await scene(now(), carried)
            continue
        carried = await scene(now())
        await wait(0.3)
    print(f"[code video] end at {now():.2f}")
    await wait(8)
    if music is not None:
        music.fade_out(2.5)
    canvas.fade_out(2.5)


def update(dt):
    st.frame += 1


run_task(show)
run(Card)
