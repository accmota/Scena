"""XYZ: circles, turtles and light.

A showcase written to be built up step by step: one scene, one page of code.
Everything that moves is a formula of a few numbers in st (@=), and the
storyboard at the bottom only changes those numbers.

  I    Ring      a big circle draws itself; two lights run round it together,
                 then against each other, then out of step
  II   Rosette   rings of squares, triangles and pentagons, glass over glass
  III  Turtles   two turtle walks, three times each, draw themselves round the rosette
  IV   Rings     rings inside the ring light up: in step (a beam), out of phase
                 (a spiral), at different speeds (waves), then in colour

Things to try
-------------
  Change WALKS          other turtle walks: the sizes, the turn, how many times
  Change RINGS          more or fewer rings inside the big one
  Change the storyboard each part is a few tweens of st

No keys: it loops (close the window to stop).
"""
from scena import *

init(width=1280, height=800, title="XYZ")
canvas.set_origin("center")         # (0, 0) in the middle: everything turns around it
canvas.background = "#05060d"
Bloom(intensity=0.8)
Vignette(amount=0.7)

R = 360                             # the big circle
RINGS = 22                          # rings inside it
WHEEL = Colormap.from_colors("deep sky blue", "medium purple", "hot pink", "orange", "gold")

st.lap1 = 0         # where the inner light is on the big circle, in laps
st.lap2 = 0         # where the outer light is
st.speed1 = 0       # laps per second of each light
st.speed2 = 0
st.arc = 0.1        # how much of the circle each light covers
st.bloom = 0        # 0: the rosette shut in a point · 1: open
st.twist = 0        # degrees each piece of the rosette turns away from the middle
st.lap = 0          # where the inner rings' lights are, in laps
st.phase = 0        # how far each ring is behind the one outside it (in laps)
st.spread = 0       # how much faster each ring turns than the one outside it
st.ring_arc = 0     # how much of each inner ring is lit
st.tint = 0         # 0: white rings · 1: every ring its own colour


def update(dt):
    st.lap1 += st.speed1 * dt
    st.lap2 += st.speed2 * dt
    st.lap += 0.1 * dt


# ---- I  the big circle and its two lights ----
ring = Track.circle(center=(0, 0), radius=R, color=Color("light steel blue").with_alpha(0.35), line_width=1.5)
ring.end = 0


def light(radius):
    """A circle round the middle that shows only its lit part, begin to end."""
    track = Track.circle(center=(0, 0), radius=radius, color="white", line_width=3)
    track.visual = Halo("deep sky blue", style="line")
    return track


inner = light(R - 7)
inner["begin"] @= lambda: st.lap1 % 1
inner["end"] @= lambda: (st.lap1 + st.arc) % 1
outer = light(R + 7)
outer["begin"] @= lambda: st.lap2 % 1
outer["end"] @= lambda: (st.lap2 + st.arc) % 1

# ---- II  the rosette: rings of glass, each piece laid over the one before ----

def glass(piece, k, count, reach, turn):
    """Piece k of a ring of count pieces round the middle, reach away from it."""
    piece.line = Color("white").with_alpha(0.35)
    piece.line_width = 1
    piece["center"] @= lambda: vec_from_angle(k * 360 / count + clock.time * turn, st.bloom * reach)
    piece["angle"] @= lambda: k * 360 / count + clock.time * turn + st.twist
    piece["scale"] @= lambda: st.bloom


for k in range(12):
    glass(Square(length=110, color=Color("deep sky blue").with_alpha(0.07)), k, 12, 95, 6)
    glass(Triangle(radius=62, color=Color("hot pink").with_alpha(0.08)), k, 12, 55, -9)
    glass(RegularPolygon(n=5, radius=30, color=Color("gold").with_alpha(0.1)), k, 12, 28, 14)

# ---- III  turtle walks: go forward, turn, again ----
# a walk closes when one round of sizes does not turn a whole circle (4 x 90 would drift away)
WALKS = [
    ([10, 20, 30, 40, 50], 60, 7),     # sizes, turn, times: a square spiral
    ([30, 60, 90, 30], 120, 3),        # a triangle that folds into itself
]


def turtle(sizes, turn, times):
    """The steps of a turtle that goes each size forward and turns after each one."""
    steps = []
    heading = 90
    for t in range(times):
        for size in sizes:
            steps.append(vec_from_angle(heading, size))
            heading += turn
    return steps


walks = []
for k in range(6):
    walk = Track(vectors=turtle(*WALKS[k % 2]), start=(0, 0), smooth=0, line_width=2)   # the two walks take turns
    walk.center = vec_from_angle(90 + k * 60, 265)
    walk.color = Gradient(WHEEL.get_color(k / 6), "white", WHEEL.get_color(k / 6 + 0.3), type="sweep")
    walk.visual = Halo(style="line", amount=0.5)
    walk.end = 0
    walk["angle"] @= lambda k=k: clock.time * (12 if k % 2 else -12)
    walks.append(walk)

# ---- IV  rings inside the ring: each light a little behind, or faster, than the one outside ----
for k in range(RINGS):
    circle = Track.circle(center=(0, 0), radius=R - 30 - 14 * k, line_width=3)
    circle["begin"] @= lambda k=k: (st.lap * (1 + st.spread * k) - st.phase * k) % 1
    circle["end"] @= lambda k=k: (st.lap * (1 + st.spread * k) - st.phase * k + st.ring_arc) % 1
    circle["color"] @= lambda k=k: lerp(Color("white"), WHEEL.get_color(k / RINGS), st.tint)


async def show():
    while True:
        # I  Ring: it draws itself; the lights run together, against, out of step
        canvas.fade_in(1)
        await tween(ring["end"], 1, time=3, ease="ease_in_out")
        st.speed1 = st.speed2 = 0.15
        await wait(5)
        await tween(st["speed2"], -0.15, time=3, ease="ease_in_out")
        await wait(6)
        await tween(st["speed2"], 0.3, time=3, ease="ease_in_out")
        tween(st["arc"], 0.25, time=4)
        await wait(4)
        # II  Rosette: the glass opens and twists
        tween(st["bloom"], 1, time=5, ease="elastic")
        await tween(st["twist"], 90, time=10, ease="ease_in_out")
        # III  Turtles: six walks draw themselves, one after another
        for walk in walks:
            tween(walk["end"], 1, time=4, ease="ease_in_out")
            await wait(1)
        await wait(8)
        tween(st["twist"], 225, time=8, ease="ease_in_out")
        for walk in walks:
            tween(walk["begin"], 1, time=3, ease="ease_in")
            await wait(0.4)
        await tween(st["bloom"], 0.4, time=3, ease="ease_in_out")
        # IV  Rings: a beam, a spiral, waves, colours
        await tween(st["ring_arc"], 0.15, time=3, ease="ease_out")
        await wait(4)
        await tween(st["phase"], 0.02, time=6, ease="ease_in_out")
        await wait(4)
        await tween(st["spread"], 0.08, time=6, ease="ease_in_out")
        tween(st["tint"], 1, time=6)
        await wait(14)
        # back to the start, in the dark
        canvas.fade_out(2)
        await wait(2)
        ring.end = 0
        for walk in walks:
            walk.begin, walk.end = 0, 0
        st.speed1 = st.speed2 = st.bloom = st.twist = st.phase = st.spread = st.ring_arc = st.tint = 0
        st.lap1 = st.lap2 = st.lap = 0
        st.arc = 0.1


run_task(show)
run()
