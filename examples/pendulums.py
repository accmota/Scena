"""Pendulums: a pendulum wave that sings.

Twenty-four pendulums hang in a row. In one cycle the first swings 5
times, the next 6, the next 7 … the last 28. Let go together, they drift
apart one swing at a time: a snake, then two rows, three, four, a scatter of
light, and at the end of the cycle they all meet again. Nothing steers
them: each one only keeps its own beat.

Each bob plays a note of a pentatonic scale as it crosses the middle, so the
picture is also a tune: a chord when they meet, a ripple when they snake, a
shower of notes in between. A smooth Track runs through every bob and shows
the wave.

Halfway, the row curls into a ring: the same wave now draws flowers with
two, three, four petals as the bobs fall in and out of step.

Things to try
-------------
  Change COUNT, FIRST     more pendulums, more swings per cycle
  Change CYCLE            the seconds until they all meet again
  Change SCALE            other notes (semitones above the sample)

No keys: it loops (close the window to stop).
"""
from math import sin, pi
from scena import *

init(width=1280, height=800, title="Pendulums")
canvas.set_origin("center")
canvas.background = "#04050b"
ChurningClouds(color="#1D2876", color2="#4b1a68", alpha=0.85, speed=1.0)
Bloom(intensity=0.9)
ColorSweep(["deep sky blue", "hot pink"], amount=0.25, speed=0.2)
Vignette(amount=0.8)

COUNT = 24
FIRST = 5              # swings of the first pendulum in one cycle
CYCLE = 80              # seconds until they all meet again
SCALE = [0, 2, 4, 7, 9]     # a pentatonic scale, in semitones
HUES = Colormap.from_colors("deep sky blue", "medium purple", "hot pink", "orange", "gold")

st.time = 0         # the pendulums' clock (it starts when they are let go)
st.swing = 0        # how far they swing
st.bend = 0         # 0: a row · 1: a ring
st.notes = False    # they sing only once they are let go


def rest(k):
    """Where pendulum k hangs at rest: on a row, or on a ring."""
    row = Vec2(-560 + 1120 * k / (COUNT - 1), 0)
    ring = vec_from_angle(90 - k * 360 / COUNT, 270)
    return lerp(row, ring, st.bend)


def out(k):
    """The way pendulum k swings: up and down on the row, in and out on the ring."""
    return lerp(Vec2(0, 1), vec_from_angle(90 - k * 360 / COUNT, 1), st.bend)


def swing(k):
    """How far out pendulum k is now (-1 … 1): it swings FIRST + k times per cycle."""
    return sin(2 * pi * (FIRST + k) * st.time / CYCLE)


def bob_place(k):
    # on the ring the swing is smaller: the bobs would cross the middle
    return rest(k) + out(k) * st.swing * (1 - 0.45 * st.bend) * swing(k)


bobs = []
for k in range(COUNT):
    color = HUES.get_color(k / (COUNT - 1))
    stem = Line(p1=lambda k=k: rest(k), p2=lambda k=k: bob_place(k),
                color=color.with_alpha(0.25), line_width=1.5, group="line_bars")
    bob = Circle(center=lambda k=k: bob_place(k), radius=9, color=color)
    bob.visual = Halo(style="fill")
    bob.tail = Tail(color=color, size=4)
    bob.visible = False
    bobs.append(bob)

# the wave: one smooth line through all the bobs
wave = Track(points=[lambda b=b: b.center for b in bobs], smooth=1, line_width=2)
wave.color = Color("white").with_alpha(0.35)     # the bobs carry the colours
wave["end"] @= lambda: min(1, st.swing / 40)
# on the ring, the last bob joins the first
seam = Line(p1=lambda: bobs[-1].center, p2=lambda: bobs[0].center, line_width=2)
seam["color"] @= lambda: Color("white").with_alpha(0.45 * st.bend ** 3)

last = [0] * COUNT      # the sign of each swing on the frame before


def update(dt):
    st.time += dt
    for k in range(COUNT):
        now = 1 if swing(k) > 0 else -1
        if st.notes and now > 0 and last[k] < 0:      # crossed the middle, going out
            note = SCALE[k % 5] + 12 * (k // 5) - 12
            play_sound("audio/nota.wav", pitch=2 ** (note / 12), volume=0.08, pan=bobs[k].center.x / 700)
            bobs[k].pop(scale=1.8)
        last[k] = now


async def show():
    while True:
        canvas.fade_in(1.5)
        for bob in bobs:
            bob.dissolve_in(0.6, style="vortex")
            await wait(0.08)
        await wait(1)
        # let go: all together, so they start in step
        st.time = 0
        st.notes = True
        group["line_bars"].visible = True      # hidden for the ring of the loop before
        group["line_bars"].visual = Rim()
        await tween(st["swing"], 150, time=3, ease="ease_out")
        await wait(CYCLE - 3)
        # they meet again: curl the row into a ring, and play a second cycle
        group["line_bars"].visual = None
        group["line_bars"].visible = False
        canvas.flash(0.3)
        await tween(st["bend"], 1, time=6, ease="ease_in_out")
        await wait(CYCLE - 6)
        canvas.flash(0.3)
        await tween(st["bend"], 0, time=6, ease="ease_in_out")
        await tween(st["swing"], 0, time=4, ease="ease_in")
        st.notes = False
        for bob in bobs:
            bob.dissolve_out(0.6, style="vortex")
            await wait(0.05)
        canvas.fade_out(1.5)
        await wait(1.5)


run_task(show)
run()
