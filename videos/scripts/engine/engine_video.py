"""Scena: watch the engine work (the code video's companion, ~3:35).

Teaser 2 shows what code says; this shows the engine running it. Each part
types a short program (a real file, parts/<part>.py, shown
whole) beside a stage, runs it statement by statement as it is typed, and
then lets it play. Two lights, both the truth of the run (nothing is
scripted): orange, the line Python runs now (a line tracer on that file),
held a moment and eased so a line run often glows steadily instead of
flashing; blue, a line whose work is still going (the Handle it returned is
alive: a motion, a wait, an until, a pending after, an every, a process). A
rule lights when its moment comes, a formula when it is read again, a timer's
line when it fires.

  0:00  title                 Watch the engine work
  0:08  objects               say what is there and what it does; the engine carries it on
  0:34  formulas              a point is dragged: the lines that depend on it light
  1:02  events                clicks run a rule; @when checks every frame, runs once
  1:29  collisions            resolve keeps balls on pegs; @collide counts the hits
  1:56  time                  every, after, a process line by line (until)
  2:26  groups                one name for many: one line moves them, a rule covers them
  2:54  acts                  Garden, Card, Garden: each setup makes its world (it comes
                              in), close plays the exits, change_act sweeps the rest
  3:28  100% made with Scena  (the music has ended)

The pace is slow on purpose: typed at 110 characters a second, a pause after
each statement, events spaced; a viewer reads the code as it runs.

Music: "Vampire's Piano" by TAD (CC0): its 89.4 s loop played to 208 s,
faded over the last 3 s (make_media.py -> piano_cut.wav).
The end card credits it.

Use
---
    python videos/scripts/engine/make_media.py
    python tools/video/record_game.py videos/scripts/engine/engine_video.py \\
        --pilot videos/scripts/engine/engine_video_pilots.py:show --seconds 214.5 \\
        --size 2560x1440 --crf 14 --out $PWD/videos/recordings/engine/scena_engine.mp4
    python videos/scripts/kit/finish.py videos/recordings/engine/scena_engine.mp4 promo/scena_engine

    TEASER_START=24 python videos/scripts/engine/engine_video.py      # start at a part (no music)
"""

import ast
import os
import sys
from functools import partial, wraps
from random import choice, uniform, seed
from types import SimpleNamespace

import scena
from scena import *

init(width=1280, height=720, title="Scena")
seed(3)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "kit"))
from paths import REPO, work               # noqa: E402
from promo_kit import *                      # noqa: E402,F403
from promo_kit import kit                    # noqa: E402
from scena.canvas import ScenaCanvas         # noqa: E402  (counts for the act part)
from scena.process import get_scheduler      # noqa: E402,F401

PARTS = os.path.join(HERE, "parts")
MUSIC = os.path.join(work("engine"), "piano_cut.wav")
MUSIC_SECONDS = 208.0
CUES = os.path.join(work("engine"), "cues.json")
START = float(os.environ.get("TEASER_START", "0"))
kit.setup(cues=CUES, start=START)

canvas.background = NIGHT
light = Bloom(intensity=0.5)
Vignette(amount=0.6)

st.mode = None
my = SimpleNamespace(act_made=set(), caption=None, panel=None, path=None, made=set(), handles=[], spans=[], ns=None,
                     switched=False, parked={}, timers=[], deco=set(), acts_seen=0, counts=None)
TYPE_SPEED = 110            # characters a second: time to read


def now():
    """Seconds into the video (here: a formula follows only this file's functions)."""
    return clock.time - st.t0


# ---- the tracer: a line lights up when Python runs it ----

def _local(frame, event, arg):
    if event == "return":
        my.parked[frame] = frame.f_lineno       # a yield (or the end): where it waits
    elif event == "line" and my.panel is not None:
        if my.parked.pop(frame, None) == frame.f_lineno:
            return _local       # resumed on the line it awaits: not run again (blue says it)
        my.panel.hit(frame.f_lineno)
    return _local


def _global(frame, event, arg):
    if my.path is not None and frame.f_code.co_filename == my.path:
        if event == "call" and my.panel is not None and my.panel.live:
            my.panel.hit(frame.f_lineno)
        return _local
    return None


sys.settrace(_global)


def span(handle, frame):
    """A line of the fragment started something that goes on (its Handle):
    the line stays blue while it is alive."""
    if my.path is not None and frame.f_code.co_filename == my.path \
            and hasattr(handle, "_alive"):
        my.spans.append((frame.f_lineno, handle))


def _spanning(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        handle = method(self, *args, **kwargs)
        frame = sys._getframe(1)
        for _ in range(3):          # a group's broadcast calls from its own frame
            if frame is None or frame.f_code.co_filename == my.path:
                break
            frame = frame.f_back
        if frame is not None:
            span(handle, frame)
        return handle
    return wrapped


# the motions, wherever they are defined (Shape and Graphic both have some)
for _name in ("move_to", "move_by", "move_along", "rotate_by", "rotate_to", "scale_to"):
    for _owner in {c for cls in (Circle, Sprite, Rect, Line) for c in cls.__mro__
                   if _name in c.__dict__}:
        setattr(_owner, _name, _spanning(_owner.__dict__[_name]))


# ---- the panel: the program, its lights and its counts ----

class Panel:
    LEFT, TOP, SIZE, GAP, WIDTH = 46, 600, 14, 1.42, 568
    HOLD = 0.25                 # a line run stays lit this long, then eases off

    def __init__(self, part, size=None, typed=False, top=None, gap=None):
        self.path = os.path.join(PARTS, f"{part}.py")
        with open(self.path) as f:
            self.source = f.read()
        self.lines = self.source.rstrip("\n").split("\n")
        size = size or self.SIZE
        self.code = Code(self.LEFT, top or self.TOP, size, gap or self.GAP)
        step = self.code.step
        self.back = Rect(center=(self.LEFT - 16 + self.WIDTH / 2, 352), width=self.WIDTH + 12,
                         height=578, corner_radius=12, color=PANEL)
        self.back.line = DEEP.with_alpha(0.6)
        self.back.line_width = 1.5
        if not typed:
            self.back.fade_in(0.3)
        self.going, self.marks, self.bands = [], [], []
        for row in range(len(self.lines)):
            y = self.code.row_y(row) - size * 0.55
            middle = (self.LEFT - 16 + self.WIDTH / 2, y)
            for kind, out in ((ICE, self.going), (EMBER, self.bands)):
                band = Rect(center=middle, width=self.WIDTH, height=step,
                            color=kind.with_alpha(0.0), corner_radius=4)
                band.line = None
                out.append(band)
            mark = Rect(center=(self.LEFT - 19, y), width=4, height=step - 4,
                        color=ICE.with_alpha(0.0), corner_radius=2)
            self.marks.append(mark)
        self.last = [-9.0] * len(self.lines)
        self.run_level = [0.0] * len(self.lines)
        self.going_level = [0.0] * len(self.lines)
        self.live = typed           # typed and run: function calls light their def line
        self.legend = self.make_legend()
        if typed:
            self.code.show(self.lines, fade=0)
        my.path = self.path

    def make_legend(self):
        y = 352 - 289 + 16
        parts = []
        x = self.LEFT
        for color, text in ((EMBER, "runs now"), (ICE, "still going: a motion, a wait, a timer")):
            parts.append(Rect(center=(x + 6, y), width=12, height=12, corner_radius=3,
                              color=color.with_alpha(0.7)))
            words = Text(text, center=(0, y), font=MONO, font_size=11, color=CAPTION)
            words.center = (x + 18 + words.box.width / 2, y)
            parts.append(words)
            x += 40 + words.box.width
        return parts

    def hit(self, lineno):
        row = lineno - 1
        if 0 <= row < len(self.lines):
            self.last[row] = clock.time

    def tick(self, dt):
        going = [0] * len(self.lines)
        my.spans = [(line, h) for line, h in my.spans if going_handle(h)]
        for line, _ in my.spans:
            if 0 <= line - 1 < len(going):
                going[line - 1] = 1
        up, down = 1 - pow(2.718, -dt * 16), 1 - pow(2.718, -dt * 3.0)
        for row, band in enumerate(self.bands):
            if not band.is_alive:           # the part is leaving
                return
            target = 1.0 if clock.time - self.last[row] < self.HOLD else 0.0
            h = self.run_level[row]
            h += (target - h) * (up if target > h else down)
            self.run_level[row] = h
            band.color = EMBER.with_alpha(0.34 * h)
            g = self.going_level[row]
            g += (going[row] - g) * (up / 2 if going[row] > g else down)
            self.going_level[row] = g
            self.going[row].color = ICE.with_alpha(0.16 * g)
            self.marks[row].color = ICE.with_alpha(0.9 * g)

    async def type_only(self, speed=TYPE_SPEED):
        for row, line in enumerate(self.lines):
            if line.strip():
                await self.code.say(line, row=row, speed=speed)
            else:
                self.code.rows.append([])

    async def type_and_run(self, speed=TYPE_SPEED):
        """Type the program a statement at a time; run each statement once typed."""
        tree = ast.parse(self.source, self.path)
        typed = 0
        for stmt in tree.body:
            while typed < stmt.end_lineno:
                line = self.lines[typed]
                if line.strip():
                    await self.code.say(line, row=typed, speed=speed)
                else:
                    self.code.rows.append([])
                typed += 1
            before = set(live_ids())
            exec(compile(ast.Module(body=[stmt], type_ignores=[]), self.path, "exec"), my.ns)
            my.made |= set(live_ids()) - before
            await wait(0.35)
        self.live = True

    def parts(self):
        return [self.code.rows, self.bands, self.going, self.marks, self.back, self.legend]

    def leave(self, time=0.4):
        leave(self.parts(), time=time)
        my.panel = None
        my.path = None
        my.spans = []
        my.parked = {}
        st.mode = None
        # the parts run from the video's own task (script scope): their timers
        # would outlive the act, so the video stops them (an act's own would go)
        for handle in my.handles:
            handle.cancel()
        my.handles = []


def live_ids():
    return [id(o) for o in ScenaCanvas.get_current().registry.live_objects()]


def going_handle(handle):
    return getattr(handle, "_alive", False) and not getattr(handle, "_done", False)


def fragment_namespace():
    """What a fragment sees: Scena's names (its import line is not shown) and
    the random uniform and choice. The calls that start something lasting are wrapped:
    their line stays blue while it goes on; a timer's line lights when it fires;
    the video keeps the handles to stop them when a part ends; change_act puts
    the panel back in the new act."""
    ns = {name: getattr(scena, name) for name in scena.__all__}
    ns["uniform"] = uniform
    ns["choice"] = choice
    ns["__name__"] = "fragment"

    def lasting(make, timer=False):
        def made(*args, **kwargs):
            frame = sys._getframe(1)
            if timer and len(args) >= 2 and callable(args[1]):
                line, fn = frame.f_lineno, args[1]

                @wraps(fn)
                def fire(*a, **k):
                    if my.panel is not None and frame.f_code.co_filename == my.path:
                        my.panel.hit(line)
                    return fn(*a, **k)
                args = (args[0], fire) + args[2:]
            handle = make(*args, **kwargs)
            my.handles.append(handle)
            if timer:
                my.timers.append(handle)
            span(handle, frame)
            return handle
        return made

    for name in ("every", "after"):
        ns[name] = lasting(getattr(scena, name), timer=True)
    for name in ("run_task", "wait", "until"):
        ns[name] = lasting(getattr(scena, name))

    def act_change(act):
        before = set(live_ids())
        change_act(act)             # immediate: the new act's setup has run
        my.act_made = set(live_ids()) - before
        my.switched = True          # update() dresses the new act on its first frame
    ns["change_act"] = act_change
    return ns


def stage_frame():
    frame = Rect(center=(944, 352), width=620, height=578, corner_radius=12)
    frame.color = Color("black").with_alpha(0.0)
    frame.line = DEEP.with_alpha(0.45)
    frame.line_width = 1.5
    frame.fade_in(0.3)
    return frame


def part_title(number, text):
    words = [Text(f"{number}", center=(60, 676), font=MONO, font_size=22, color=EMBER),
             Text(text, center=(0, 676), font=TITLE_FONT, font_size=28, color="white")]
    words[1].center = (84 + words[1].box.width / 2, 676)
    for w in words:
        w.fade_in(0.4)
    return words


def caption_below(text, size=21):
    return note(text, (640, 30), size=size)


# ---- 0:00  title ----

async def title(t):
    Stars(color=FROST, density=0.3, twinkle=0.4)
    row = arrive("SCENA", (640, 470), size=120)
    for letter in row:
        letter.fill = Gradient("white", FROST, ICE, angle=-90)
    await at(t + 1.0)
    sub = [rise("Watch the engine work", (640, 345), size=40, color="white")]
    await at(t + 2.2)
    sub.append(note("Real code, run as it is typed.", (640, 270), size=26))
    await at(t + 3.0)
    sub.append(note("Orange: the line Python runs now. Blue: what it started, still going.",
                    (640, 228), size=24))
    await at(t + 7.4)
    leave(row, sub, time=0.5)


# ---- the parts ----

async def run_part(t, number, part, heading, length, notes=(), after_typed=None, size=None):
    """One part: its title, the program typed and run, then played; notes:
    (seconds, text) captions under the stage."""
    words = part_title(number, heading)
    frame = stage_frame()
    my.ns = fragment_namespace()
    panel = Panel(part, size=size)
    my.panel = panel
    st.mode = "panel"
    await at(t + 0.5)
    await panel.type_and_run()
    print(f"[engine] {part} typed at +{now() - t:.1f} s")
    if after_typed:
        after_typed(panel)
    shown = []
    for when, text in notes:
        await at(t + when)
        leave(shown, style="fade", time=0.3)
        shown = [caption_below(text)]
    await at(t + length - 0.6)
    return words + [frame] + shown, panel


async def objects(t):
    Stars(color=FROST, density=0.2, twinkle=0.3)
    gone, panel = await run_part(t, 1, "objects", "Say what is there", 26.0, notes=(
        (8.5, "Each line ran once. Now no line runs, and still it all moves:"),
        (15.5, "the blue lines started motions, and the engine carries them on."),
    ))
    leave(gone, time=0.4)
    panel.leave()


async def formulas(t):
    gone, panel = await run_part(t, 2, "formulas", "Formulas", 28.0, notes=(
        (7.6, "A hand drags b. Watch which lines light up."),
        (14.4, "Still: dark. A formula runs again only when what it reads changes."),
    ))
    leave(gone, time=0.4)
    panel.leave()


async def events(t):
    gone, panel = await run_part(t, 3, "events", "Events", 27.0, notes=(
        (7.0, "A click runs the rule of the lamp it hits."),
        (17.6, "@when asks every frame; it runs its function once, when the answer turns True."),
    ))
    leave(gone, time=0.4)
    panel.leave()


async def collisions(t):
    gone, panel = await run_part(t, 4, "collisions", "Collisions", 27.0, size=13, notes=(
        (10.5, "on_update runs every frame, for every ball."),
        (18.0, "resolve keeps them out of the pegs; @collide runs when two meet."),
    ))
    leave(gone, time=0.4)
    panel.leave()


async def timing(t):
    gone, panel = await run_part(t, 5, "timing", "Time", 30.0, notes=(
        (9.0, "A process runs line by line, and waits where it says."),
        (18.0, "every and after call back on time; until waits for a condition."),
    ))
    leave(gone, time=0.4)
    panel.leave()


# ---- part 6: groups ----

async def groups(t):
    gone, panel = await run_part(t, 6, "groups", "Groups", 28.0, notes=(
        (9.0, "group= gives 24 rocks one name: one line moves them all."),
        (17.5, "nearest picks from the group; @collide names groups, not objects."),
    ))
    leave(gone, time=0.4)
    panel.leave()


# ---- part 7: two acts of the fragment take turns ----

ACTS_SIZE, ACTS_TOP, ACTS_GAP = 12, 630, 1.3     # 35 lines: closer, from higher up
CAPTIONS = (
    "Garden's setup makes its world: ground, sun, flowers, a bee, two timers.",
    "change_act(Card): all Garden made is gone, timers too. Card's setup runs.",
    "change_act(Garden): its setup runs again, and its world is made anew.",
)
LAST_WORD = "No cleanup to write: an act takes away what it made."


def dress_act():
    """The video's frame round the fragment's act, made in that act: the
    title, the stage, the panel (whole), the counts, the caption. change_act
    sweeps it with the rest; update() calls this again in the new act."""
    before = set(live_ids())
    Stars(color=FROST, density=0.2, twinkle=0.3)
    things = part_title(7, "Acts") + [stage_frame()]
    my.panel = Panel("acts", size=ACTS_SIZE, typed=True, top=ACTS_TOP, gap=ACTS_GAP)
    things += my.panel.parts()
    my.counts = Text("", center=(944, 622), font=MONO, font_size=14, color=FROST)
    caption = caption_below(CAPTIONS[min(my.acts_seen, len(CAPTIONS) - 1)])
    my.caption = caption
    things += [my.counts, caption]
    my.acts_seen += 1
    my.deco = set(live_ids()) - before
    my.dressed = things
    st.mode = "arena"


def count_text():
    """What the fragment's act holds now: the shapes, sprites and texts its
    setup made (the live registry also holds Points, the act itself and the
    video's frame), its running timers."""
    objects = sum(1 for o in ScenaCanvas.get_current().registry.live_objects()
                  if id(o) in my.act_made and isinstance(o, (Shape, Sprite, Text))
                  and not isinstance(o, Point) and o.is_alive)
    timers = sum(1 for h in my.timers if going_handle(h))
    return f"on stage: {objects}   timers: {timers}"


async def acts(t):
    my.made = set()
    my.ns = fragment_namespace()
    my.acts_seen, my.deco, my.dressed, my.timers = 0, set(), [], []
    words = part_title(7, "Acts")
    frame = stage_frame()
    panel = Panel("acts", size=ACTS_SIZE, top=ACTS_TOP, gap=ACTS_GAP)
    my.panel = panel
    st.mode = "panel"
    my.dressed = words + [frame] + panel.parts()
    await at(t + 0.5)
    await panel.type_and_run(speed=170)     # its last line, change_act(Garden), starts it
    await at(t + 29.0)
    leave([my.caption], style="fade", time=0.3)
    before = set(live_ids())
    my.dressed.append(caption_below(LAST_WORD))
    my.deco |= set(live_ids()) - before       # the video's, not the act's
    await at(t + 33.2)
    st.mode = None
    for handle in my.handles:
        handle.cancel()
    my.handles, my.spans = [], []
    my.panel, my.path = None, None
    leave(my.dressed, time=0.4)


async def finale(t):
    my.panel = None
    await made_with_scena(note_line="a 33-chapter tutorial · the whole API Guide",
                          music='"Vampire\'s Piano" by TAD (CC0)')


SECTIONS = [
    (0.0, title, False),
    (8.0, objects, False),
    (34.0, formulas, False),
    (62.0, events, False),
    (89.0, collisions, False),
    (116.0, timing, False),
    (146.0, groups, False),
    (174.0, acts, False),
    (MUSIC_SECONDS, finale, False),
    (MUSIC_SECONDS + 6.0, None, False),
]


def update(dt):
    st.frame += 1
    if my.switched and my.path is not None and not my.panel.back.is_alive:
        my.switched = False         # the fragment changed act: dress the new one
        dress_act()
    if st.mode in ("panel", "arena") and my.panel is not None:
        my.panel.tick(dt)
    if st.mode == "arena":
        text = count_text()
        if my.counts.text != text:
            my.counts.text = text


async def show():
    await run_sections(SECTIONS, music=MUSIC, label="engine")


run_task(show)
run(Card)
