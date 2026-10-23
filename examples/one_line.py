"""One Line.

A demo made of a single line of light on black. The line is a Track: it
draws itself, closes into a circle, sharpens into a star, winds out as a
spiral and back in, loops into a figure eight, ripples into a wave and
comes home as a circle again. Everything else on the screen is read from
the line: the comet of light that runs around it, the pearls that ride it,
the dim echo that turns behind it, the rings left where the comet passed.

  I    Birth     the line draws itself and closes; a comet runs around it
  II   Star      it sharpens; a zigzag, then a coil, play on the theme
  III  Eight     a spiral winds out and in, then loops; two processions cross
  IV   Wave      the kaleidoscope: the line breathes in every colour
  V    Home      back to a circle, which closes to a point

One async script at the bottom, show(), is the storyboard: it reads like
the running order of the demo and loops forever.

Things to try
-------------
  Change SIZE              the whole demo grows or shrinks with the line
  Change the variations    the zigzag / orbit sizes tweened in star()
  Swap the colour ramps    each part has its own Colormap

Controls
--------
  none: sit back, it loops forever (close the window to stop)

Use
---
    python examples/one_line.py
"""

from math import sin
from scena import *

init(width=1280, height=800, title="One Line")

CENTER = (640, 400)
SIZE = 250          # the radius of the line's shapes

# one colour family per part, dark → light
ICE = Colormap.from_colors("midnight blue", "deep sky blue", "white")
GOLD = Colormap.from_colors("dark red", "orange", "light yellow")
VIOLET = Colormap.from_colors("indigo", "magenta", "misty rose")
SPECTRUM = Colormap.from_preset("rainbow")
HOME = Colormap.from_colors("slate gray", "white")

st.head = 0         # where the comet's head is on the line (in laps)
st.speed = 0        # comet speed, laps per second
st.span = 0.999     # how much of the line the comet lights (0.999: all of it)
st.wiggle = 0       # zigzag on the line \
st.coil = 0         # orbit on the line   } tweened; reshape() writes them on the line
st.drift = 0        # wander on the line  /
st.glow = 0.8       # Bloom intensity (posts do not link: update writes it)
st.marks = 0        # rings left by the comet: how many places per lap
st.mark = 0         # the last place that got a ring
st.line = None      # the line on stage now
st.ramp = ICE       # and its colours
st.light = None     # this round's Bloom
st.spark = None     # the comet's head
st.ghosts = None    # the rings the comet left


class Loop(Act):
    """A blank act: change_act(Loop) clears everything for the next round."""


def backdrop():
    """Black, a few far stars, and the light: the same every round."""
    st.line = None
    st.spark = None
    st.marks = 0
    st.glow = 0.8
    canvas.background = "black"
    Stars(density=0.12, color="light steel blue")
    st.light = Bloom(intensity=st.glow)
    Vignette(amount=0.9)
    # a ring lives a moment and goes; at most a handful at once
    st.ghosts = History(max_points=6)


def new_line(track, ramp):
    """Make a Track the line on stage: lit in its ramp, not drawn yet."""
    track.color = ramp.get_color(0.75)
    track.line_width = 3
    track.end = 0
    track.visible = True    # a Track with no style yet is motion-only
    st.line = track
    st.ramp = ramp
    return track


def comet(line, ramp):
    """The lit window runs around the loop: head at st.head, tail st.span behind."""
    line["end"] @= lambda: st.head % 1
    line["begin"] @= lambda: (st.head - st.span) % 1
    st.spark = Circle(center=lambda: line.at(st.head % 1), radius=4,
                      color=ramp.get_color(1))


def stop_comet(line):
    """Freeze the lit window where it is, and take the comet's head away."""
    line["begin"].unlink()
    line["end"].unlink()
    if st.spark is not None:
        st.spark.destroy()      # it rides this line
        st.spark = None


def echo(line, ramp, turn, size):
    """A dim copy of the line, another size, turning slowly behind it."""
    shadow = line.clone()
    shadow.color = ramp.get_color(0.45).with_alpha(0.35)
    shadow.line_width = 1.5
    shadow.begin = 0
    shadow.end = 1
    shadow["scale"] @= lambda: size + 0.04 * sin(clock.time * 1.3)
    shadow["angle"] @= lambda: clock.time * turn
    shadow.fade_in(2)
    return shadow


def pearls(line, count, lap, ramp):
    """A string of pearls riding the line. Each one swells as the comet passes."""
    for i in range(count):
        p = Circle(radius=3, color=ramp.get_color(0.9), group="pearl")
        p.move_along(line, time=lap, phase=i / count, loops="forever")
        p["radius"] @= lambda p=p: 2 + 6 * max(0, 1 - distance(p.center, line.at(st.head % 1)) / 140)
        # a thread from the centre to each pearl: string art
        thread = Line(p1=CENTER, p2=lambda p=p: p.center, group="thread",
                      color=ramp.get_color(0.6).with_alpha(0.3))
        thread.blend = "add"
        p.fade_in(1)
        thread.fade_in(1)


def procession(track, count, lap, ramp):
    """Little arrows marching along the track, coloured by how far out they are."""
    for i in range(count):
        a = Triangle(radius=9, base_ratio=0.5, group="pearl")
        a.line = None
        a.move_along(track, time=lap, phase=i / count, loops="forever", face=True)
        a["fill"] @= lambda a=a: ramp.get_color(min(1, distance(a.center, CENTER) / 420))
        a.fade_in(1)


def drop_pearls():
    # the threads go first: each one reads its pearl
    for t in group["thread"]:
        t.fade_out(0.6, on_done=t.destroy)
    for p in group["pearl"]:
        p.fade_out(1, on_done=p.destroy)


def ghost(place, ramp):
    """A ring of light left where the comet passed; it widens and fades."""
    ring = st.ghosts.add(Circle(center=place, radius=6, line_width=2))
    ring.fill = None
    ring.line = ramp.get_color(0.8)
    tween(ring["radius"], 70, time=1.4, ease="ease_out")
    ring.fade_out(1.4)


async def morph(old, new, time=2.5):
    """The new shape draws itself while the old one fades: one line, changing."""
    old.fade_out(time, on_done=old.destroy)
    await tween(new["end"], 1, time=time, ease="ease_in_out")


# ---- I  birth ----

async def birth():
    line = new_line(Track.circle(center=CENTER, radius=SIZE), ICE)
    # the pen: a bright point at the tip of the stroke
    pen = Circle(center=lambda: line.at(line.end), radius=5, color="white")
    title = Text("one line", center=(640, 90), font="fonts/Quantico-Regular.ttf",
                 font_size=22, color=ICE.get_color(0.55))
    title.fade_in(3)
    # a circle is cheap to draw under a moving camera: let it drift
    canvas.zoom_to(1.12, time=14, ease="ease_in_out")
    canvas.rotate_by(-25, time=14, ease="ease_in_out")
    await tween(line["end"], 1, time=5, ease="ease_in_out")

    # the line closes: a wave goes out from where it met itself
    canvas.ripple_at(line.at(0), amount=0.5, radius=420, shake=False)
    pen.fade_out(0.5, on_done=pen.destroy)
    title.fade_out(3)

    # a comet: the lit part shrinks and starts to run
    comet(line, ICE)
    tween(st["speed"], 0.35, time=3, ease="ease_in")
    await tween(st["span"], 0.18, time=3, ease="ease_in_out")
    pearls(line, 18, 9, ICE)
    await wait(6)
    drop_pearls()
    tween(st["span"], 0.999, time=2, ease="ease_in_out")
    await canvas.reset_view(time=2, ease="ease_in_out")


# ---- II  star ----

async def star():
    old = st.line
    stop_comet(old)
    line = new_line(Track.star(points=5, radius=SIZE, inner=SIZE * 0.42,
                               center=CENTER), GOLD)
    canvas.zap_at(line.at(0), style="fork", color="gold", radius=90)
    await morph(old, line)
    shadow = echo(line, GOLD, 6, 1.18)
    comet(line, GOLD)
    st.marks = 5            # a ring at each tip as the comet goes round it
    tween(st["span"], 0.3, time=2, ease="ease_in_out")
    pearls(line, 10, 12, GOLD)

    # variations on the theme: a zigzag grows, then gives way to a coil
    await tween(st["wiggle"], 10, time=3, ease="ease_in_out")
    await wait(3)
    await tween(st["wiggle"], 0, time=2, ease="ease_in_out")
    await tween(st["coil"], 9, time=3, ease="ease_in_out")
    await wait(3)
    drop_pearls()
    st.marks = 0
    tween(st["coil"], 0, time=2, ease="ease_in_out")
    shadow.fade_out(2, on_done=shadow.destroy)
    await tween(st["span"], 0.999, time=2, ease="ease_in_out")


# ---- III  spiral and eight ----

async def eight():
    old = st.line
    stop_comet(old)
    # the spiral starts at the centre, so the line winds out from there...
    line = new_line(Track.spiral(turns=4, radius=SIZE, center=CENTER), VIOLET)
    await morph(old, line, time=3)
    canvas.ripple_at(line.at(1), amount=0.4, radius=300, shake=False)
    await wait(1)
    # ...and back in, to where the eight will start: at its crossing
    await tween(line["end"], 0, time=2.5, ease="ease_in_out")
    line.destroy()

    line = new_line(Track.eight(width=820, height=150, center=CENTER), VIOLET)
    await tween(line["end"], 1, time=3, ease="ease_in_out")
    shadow = echo(line, VIOLET, -8, 0.6)
    comet(line, VIOLET)
    st.marks = 2            # a ring at the crossing, twice a lap
    tween(st["span"], 0.35, time=2, ease="ease_in_out")
    # two processions: one along the line, its mirror along the reversed view
    procession(line, 9, 10, VIOLET)
    procession(line.reversed(), 7, 10, VIOLET)
    await wait(4)
    await tween(st["coil"], 16, time=3, ease="ease_in_out")
    await wait(4)
    drop_pearls()
    st.marks = 0
    tween(st["coil"], 0, time=2, ease="ease_in_out")
    shadow.fade_out(2, on_done=shadow.destroy)
    await tween(st["span"], 0.999, time=2, ease="ease_in_out")


# ---- IV  wave ----

async def wave():
    old = st.line
    stop_comet(old)
    line = new_line(Track.wave(length=1000, amplitude=110, waves=4, start=(140, 400)),
                    SPECTRUM)
    # the colour runs through the whole spectrum
    line["color"] @= lambda: SPECTRUM.get_color(clock.time * 0.15 % 1)
    line.line_width = 4
    await morph(old, line)
    canvas.flash(0.6)
    canvas.ripple_at(CENTER, amount=0.6, shake=False)
    mirrors = Kaleidoscope(segments=8, spin=0.12)
    split = Prism(amount=0.004)
    tween(st["glow"], 1.4, time=3, ease="ease_in_out")
    # the lit part slides back and forth on the open line
    line["begin"] @= lambda: 0.6 * abs(st.head % 2 - 1)
    line["end"] @= lambda: 0.6 * abs(st.head % 2 - 1) + 0.4
    # and the line breathes: a slow wander, a zigzag that comes and goes
    tween(st["drift"], 45, time=6, ease="ease_in_out")
    await tween(st["wiggle"], 22, time=2, ease="ease_in_out", loops=6, yoyo=True)
    await tween(st["drift"], 0, time=2, ease="ease_in_out")
    canvas.flash(0.8)
    mirrors.remove()
    split.remove()
    st.glow = 0.8


# ---- V  home ----

async def home():
    old = st.line
    old["color"].unlink()
    line = new_line(Track.circle(center=CENTER, radius=SIZE), HOME)
    old.fade_out(1.2, on_done=old.destroy)
    await tween(line["end"], 1, time=3, ease="ease_in_out")
    canvas.ripple_at(line.at(0), amount=0.4, radius=400, shake=False)
    # a circle again: cheap, so the camera may come close
    canvas.zoom_to(1.25, time=5, ease="ease_in_out")
    await wait(3)
    # the line closes to a point, and the point goes out
    await tween(line["scale"], 0.01, time=2, ease="ease_in")
    canvas.zap_at(CENTER, style="spark", color="white", radius=60)
    canvas.ripple_at(CENTER, amount=0.8, radius=500, shake=False)
    line.destroy()
    st.line = None
    await wait(1.5)


@on_change(lambda: (st.wiggle, st.coil, st.drift))
def reshape():
    """The variations: the modifiers are rewritten while a tween plays them."""
    if st.line is not None:
        st.line.zigzag(amount=st.wiggle, waves=30)
        st.line.orbit(radius=st.coil, laps=20)
        st.line.wander(amount=st.drift, seed=7)


def update(dt):
    st.head += st.speed * dt
    if st.line is None:
        return
    st.light.intensity = st.glow
    # a ring each time the comet's head reaches the next mark
    if st.marks and int(st.head * st.marks) != st.mark:
        st.mark = int(st.head * st.marks)
        ghost(st.line.at((st.mark / st.marks) % 1), st.ramp)


# ---- the storyboard ----

async def show():
    await wait(0.5)         # change_act needs the game running
    while True:
        change_act(Loop)
        backdrop()
        canvas.fade_in(1.5)
        await birth()
        await star()
        await eight()
        await wave()
        await home()
        canvas.fade_out(1.5)
        await wait(2)


run_task(show)
run(Loop)
