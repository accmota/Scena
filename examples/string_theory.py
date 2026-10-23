"""String Theory.

Hundreds of straight lines and a few curves. Each follows one simple rule,
and together they draw patterns nobody drew by hand (~85 s, loops):

  I    Times table   point i joins point k·i on a circle; k climbs 2 → 99
  II   Fans          two fans of lines cross: ghost curves (moiré) come and go
  III  Lissajous     strings whose two ends ride sines with drifting ratios
  IV   Curves        rings, petals and a harmonograph that draws itself

Rings of shapes frame each pattern, and a wave runs round them when it changes.
Flashing lights and pulsing patterns: a card says so first (SPACE skips it).

Use:  python examples/string_theory.py
"""

from math import sin, cos, pi, exp
from scena import *

init(width=1280, height=800, title="String Theory")

CX, CY = 640, 400
R = 280             # the circle the strings live on
N = 160             # points on the circle (part I)
NODES = 16
TABLES = [3, 4, 5, 7, 10, 21, 34, 51, 99]     # the stops of k in part I
Bloom(intensity=0.9)
st.a = 1            # the two ratios of the Lissajous curve (part III)
st.b = 2

# four quarter-pipes round off the corners of the window
for x, y, scoop in ((60, 60, "top_right"), (1220, 60, "top_left"),
                    (60, 740, "bottom_right"), (1220, 740, "bottom_left")):
    Concave(center=(x, y), width=120, height=120, scoop=scoop, color="#191536", layer="ui")
nodes = []          # the 16 shapes round the ring of the current part


def strike(s, color, hit=False):
    """A wave round the ring from node s; a hit adds a spark there and a ripple far off."""
    for i in range(NODES):
        steps = min((i - s) % NODES, (s - i) % NODES)    # the nearer, the sooner
        nodes[i].after(steps * 0.06, lambda n=nodes[i]: n.pop(0.35, scale=2.2))
    if hit:
        canvas.zap_at(nodes[s], radius=70, color=color, style="fork")
        after(0.5, lambda: canvas.ripple_at(nodes[(s + NODES // 2) % NODES], amount=0.5))


class Part(Act):
    """A blank act: change_act(Part) clears the last part (lines, lights, post)."""


def new_part(name):
    """Start a part: a clean act, a dark sky and the caption."""
    change_act(Part)
    canvas.background = "#05040c"
    Text(name, top_left=(28, 784), font_size=16, color="gray", layer="ui").fade_in(1)


def build_ring(palette, look, lights, count):
    """A dodecagon in a still star, and 16 circles and triangles in turn round the strings
    (the triangles point at the middle). Two opposite circles wear the part's look."""
    RegularPolygon(n=12, center=(CX, CY), radius=R + 45, color="slate blue",
                   angle=lambda: clock.time * 5).fill = None
    for tip in (90, -90):     # the star: two big triangles, one upside down
        RegularPolygon(n=3, center=(CX, CY), radius=R + 95, angle=tip,
                       color="midnight blue").fill = None
    colors = Colormap.from_colors(*palette)
    nodes.clear()
    for i in range(NODES):
        place = (CX + (R + 45) * cos(i * 2 * pi / NODES), CY + (R + 45) * sin(i * 2 * pi / NODES))
        color = colors.get_color(abs(i - NODES / 2) / (NODES / 2))     # mirrored, like the ring
        if i % 2:
            node = Triangle(center=place, radius=lambda: 13 - 3 * sin(clock.time * 2),
                            angle=i * 360 / NODES + 180, color=color)
        else:
            node = Circle(center=place, radius=12, color=color)
            if i % 8 == 0:
                node.visual = look
        nodes.append(node)
    for i in range(0, NODES, NODES // count):
        lights(center=nodes[i].center, radius=34, color=nodes[i].color)


async def times_table():
    new_part("I  TIMES TABLE   i → k·i")
    st.k = 2        # the times table
    Text(lambda: f"k = {round(st.k)}", center=(CX, 770), font_size=22, color="white", layer="ui")
    # four thin rings round the figure, breathing gently one after the other
    for k, color in enumerate(("aquamarine", "deep sky blue", "medium purple", "orchid")):
        Track.circle(center=(CX, CY), color=color, line_width=1.5,
                     radius=lambda k=k: R + 6 + 16 * k + 3 * sin(clock.time * 1.5 - k))
    for i in range(N):
        line = Line(p1=(CX + R * cos(2 * pi * i / N), CY + R * sin(2 * pi * i / N)),
                    p2=lambda i=i: (CX + R * cos(2 * pi * st.k * i / N),
                                    CY + R * sin(2 * pi * st.k * i / N)),
                    color=Color.from_hsv(i / N, 0.7, 1).with_alpha(0.6))
        line.blend = "add"      # where strings cross, their light adds up
    canvas.zoom_to(1.25, time=20, ease="ease_in_out")
    canvas.rotate_by(-60, time=22, ease="ease_in_out")
    for stop in TABLES:
        await tween(st["k"], stop, time=1.8, ease="ease_in_out")
        if stop in (3, 21, 99):
            canvas.ripple_at(CX, CY, amount=0.5)
        if stop == 21:     # the rosettes begin: the colours split for a while
            after(5, Prism(amount=0.004).remove)
        await wait(0.8)
    await canvas.reset_view(time=1.5, ease="ease_in_out")


async def fans():
    new_part("II  FANS   moiré")
    build_ring(("deep sky blue", "violet", "hot pink"), Shield(style="nebula"), GlowSpot, 4)
    ColorSweep(colors=("deep sky blue", "violet", "hot pink"), amount=0.4)
    st.gap, st.fan = 0, 1       # how far apart the pivots are; how long the fans are
    for side, color in ((-1, "deep sky blue"), (1, "hot pink")):
        pivot = lambda side=side: (CX + side * st.gap, CY)
        for j in range(72):
            ray = Line(center=pivot, length=lambda: 2 * R * st.fan, angle=j * 2.5,
                       color=lambda color=color: Color(color).with_alpha(0.5 * st.fan))
            if side > 0:    # only the pink fan turns (the camera turns both)
                ray["angle"] @= lambda j=j: j * 2.5 + clock.time * 6
            ray.blend = "add"
        # a dark hub on each pivot, so the 72 lines do not burn a white spot there
        RegularPolygon(n=6, center=pivot, radius=lambda: 26 * st.fan, color="#05040c")
    for gap in (60, 140, 20, 200, 90):
        await parallel(tween(st["gap"], gap, time=2.2, ease="ease_in_out"),
                       canvas.rotate_by(30, time=2.2, ease="ease_in_out"))
        strike(gap // 20 % NODES, "violet", hit=gap == 200)
        if gap == 200:      # the widest moment: the colours split for a while
            after(3, Chroma(amount=3).remove)
        await wait(0.8)
    await parallel(tween(st["fan"], 0.01, time=2.5, ease="ease_in"),
                   canvas.reset_view(time=2.5, ease="ease_in_out"))


def lissajous(u):
    """The point at u on the Lissajous curve now (its ratios drift with st)."""
    return (CX + R * sin(st.a * u + clock.time * 0.4), CY + R * sin(st.b * u))


async def strings():
    new_part("III  LISSAJOUS STRINGS")
    build_ring(("orchid", "medium purple", "light sky blue"), Laser("orchid"), Orb, 8)
    ColorWash("magenta", "cyan", "gold", amount=0.6)
    # each string joins a point of the curve to a point a bit further on
    for j in range(96):
        string = Line(p1=lambda j=j: lissajous(j * pi / 48),
                      p2=lambda j=j: lissajous(j * pi / 48 + 0.8),
                      color=Color.from_hsv(0.5 + j / 192, 0.6, 1).with_alpha(0.6))
        string.blend = "add"
    for a, b in ((2, 3), (3, 4), (3, 5), (1, 3)):
        await parallel(tween(st["a"], a, time=4, ease="ease_in_out"),
                       tween(st["b"], b, time=4, ease="ease_in_out"))
        strike(a * 4 % NODES, "orchid", hit=b == 5)
        await canvas.zoom_to(1.15 if a % 2 else 1, time=1, ease="ease_out")


async def curves():
    new_part("IV  CURVES")
    build_ring(("deep sky blue", "aquamarine", "white"), DashRing("deep sky blue"), GlowSpot, 16)
    # rings that breathe one after the other, from the middle out
    for k in range(6):
        Track.circle(center=(CX, CY), line_width=2, color=Color.from_hsv(k / 6, 0.65, 1),
                     radius=lambda k=k: 50 + 32 * k + 12 * sin(clock.time * 3 - k * 0.7))
    # six petals opening and closing, each a moment after the last
    for k in range(6):
        petal = Ellipse(center=(CX, CY), width=lambda k=k: 330 + 170 * sin(clock.time - k * 0.5),
                        height=70, angle=k * 30, color="hot pink")
        petal.fill = None
    # a harmonograph: two pendulums move the pen; they slow down as it draws
    swing = [(CX + 160 * exp(-t / 30) * (sin(t * 2.01) + sin(t * 3 + 0.6)),
              CY + 160 * exp(-t / 30) * (sin(t * 3.005 + 1.6) + sin(t * 2 + 0.2)))
             for t in [n * 0.08 for n in range(600)]]
    pen = Track(points=swing, smooth=0, color="white", line_width=1.5, end=0)
    await tween(pen["end"], 1, time=12, ease="ease_in_out")
    # the finale: mirrors, more of them on every strike
    mirrors = Kaleidoscope(segments=6, spin=0.05)
    for n in range(4):
        mirrors.segments = 6 + 2 * n
        strike(n * 4, "deep sky blue", hit=n == 3)
        await wait(2)
    canvas.fade_out(1.5)
    await wait(1.5)


async def show():
    card = Text("This piece contains flashing lights and pulsing patterns.",
                center=(CX, CY), font_size=20, color="white", layer="ui")
    await race(wait(3.5), until(lambda: keyp.once("space")))
    card.destroy()
    while True:
        canvas.fade_in(0.8)
        await times_table()
        await fans()
        await strings()
        await curves()


run_task(show)
run(Part)
