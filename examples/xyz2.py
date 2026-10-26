"""XYZ 2: a ring of light and a vortex of glass.

Two effects, each a few lines:

  Ring     a big circle draws itself. Two lights run round it, just inside
           and just outside: together, then against each other, then out
           of step. A light is a circle that shows only its lit part, from
           begin to end.
  Vortex   squares of see-through glass, each a little smaller than the one
           before and turned a little more. Where they overlap the glass
           adds up and gets brighter, so the turn draws a spiral that no
           square has. Then each square takes its own colour from a
           Colormap, and the colours slide along the squares.

Everything that moves is a formula of a few numbers in st (@=); the
storyboard at the bottom only changes those numbers.

Things to try
-------------
  Change SQUARES, STEP    more squares, a bigger step between them
  Change st.twist         how much each square turns from the one before it
  Change WHEEL            other colours for the glass
  Use Triangle or RegularPolygon(n=5) for the glass

No keys: it loops (close the window to stop).
"""
from scena import *

init(width=1280, height=800, title="XYZ 2")
canvas.set_origin("center")         # (0, 0) in the middle: everything turns around it
canvas.background = "#05060d"
Bloom(intensity=0.8)
Vignette(amount=0.7)

R = 360             # the big circle
SQUARES = 24        # pieces of glass in the vortex
STEP = 10           # each square is this much smaller than the one before
BLUE = Color("deep sky blue")
# the last colour is the first again: the colours can slide round without a jump
WHEEL = Colormap.from_colors("deep sky blue", "medium purple", "hot pink", "orange", "gold", "deep sky blue")

st.lap1 = 0         # where the inner light is on the circle, in laps
st.lap2 = 0         # where the outer light is
st.speed1 = 0       # laps per second of each light
st.speed2 = 0
st.arc = 0.1        # how much of the circle each light covers
st.open = 0         # 0: the vortex shut in a point · 1: open
st.twist = 0        # degrees each square turns from the one before it
st.spin = 0         # degrees the whole vortex has turned
st.tint = 0         # 0: all blue · 1: every square its own colour
st.slide = 0        # how far the colours have slid along the squares


def update(dt):
    st.lap1 += st.speed1 * dt
    st.lap2 += st.speed2 * dt
    st.spin += 10 * dt
    st.slide += 0.05 * dt


# ---- the ring and its two lights ----
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

# ---- the vortex: each square smaller, and turned a little more ----
for k in range(SQUARES):
    glass = Square(center=(0, 0), length=300 - STEP * k)
    glass.line = Color("white").with_alpha(0.25)
    glass.line_width = 1
    glass["angle"] @= lambda k=k: st.spin + k * st.twist
    glass["scale"] @= lambda: st.open
    # from blue to its own colour on the WHEEL, always see-through
    glass["fill"] @= lambda k=k: lerp(BLUE, WHEEL.get_color((k / SQUARES + st.slide) % 1), st.tint).with_alpha(0.08)


async def show():
    while True:
        # the ring draws itself; the lights run together, against, out of step
        canvas.fade_in(1)
        await tween(ring["end"], 1, time=1, ease="ease_in_out")
        st.speed1 = st.speed2 = 0.15
        await wait(5)
        await tween(st["speed2"], -0.15, time=1.5, ease="ease_in_out")
        await wait(5)
        await tween(st["speed2"], 0.3, time=1.5, ease="ease_in_out")
        tween(st["arc"], 0.25, time=4)
        # the vortex opens: squares one inside another, then they twist
        await tween(st["open"], 1, time=2, ease="elastic")
        await wait(1)
        await tween(st["twist"], 7.5, time=8, ease="ease_in_out")
        await wait(2.5)
        # it twists further: the spiral turns into a star
        await tween(st["twist"], 30, time=10, ease="ease_in_out")
        await wait(5)
        # every square takes its own colour, and the colours slide
        await tween(st["tint"], 1, time=5, ease="ease_in_out")
        await wait(10)
        await tween(st["twist"], 0, time=3, ease="ease_in_out")
        await tween(st["open"], 0, time=3, ease="ease_in")
        # back to the start, in the dark
        canvas.fade_out(2)
        await wait(2)
        ring.end = 0
        st.speed1 = st.speed2 = st.lap1 = st.lap2 = st.tint = 0
        st.arc = 0.1


run_task(show)
run()
