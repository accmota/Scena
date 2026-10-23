"""Demo 100: dancing triangles.

A small demo in about 120 lines. Rings of triangles dance in slow waves:
every triangle is placed by a formula of the clock (@=), so nothing in the
file moves them by hand. The storyboard at the bottom tells the three parts:

  I    Open    the rings open out of a point, around a beating heart
  II   Dance   the rings sway in slow waves, and jump on every bar
  III  Storm   they spin faster and faster, lightning strikes, and they burst

Things to try
-------------
  Change RINGS          more rings, more dancers
  Change reach()        how the rings wave in and out
  Change the sin()s     two waves, two speeds: the dance never quite repeats

No keys: sit back, it loops (close the window to stop).
"""

from math import sin
from scena import *

init(width=1280, height=800, title="Demo 100")
canvas.set_origin("center")         # (0, 0) in the middle: the rings turn around it

# ---- the stage: the sky, the light and the music ----
Borealis(color="dark turquoise", height=0.6, alpha=0.6)
Stars(density=0.6)
Bloom(intensity=0.9)
play_sound("music/super_hero_original_no_intro.ogg", loops="forever", volume=0.8)

# ---- what the storyboard changes ----
st.open = 0         # 0: the rings shut in a point · 1: wide open
st.sway = 0         # how much the rings wave in and out
st.spin = 1         # how fast the rings turn

RINGS = 5
COLORS = ["deep pink", "orange", "gold", "spring green", "deep sky blue"]


def turn(ring, k):
    """Where triangle k sits round its ring (of 8 + 8 * ring), in degrees.
    Each ring turns its own way, at its own speed."""
    count = 8 + 8 * ring
    return k * 360 / count + clock.time * (12 - 5 * ring) * st.spin


def reach(ring):
    """How far a ring is from the middle: it opens, and sways in and out.
    Two waves of different speeds and sizes, added: a gentle sway that never quite repeats."""
    wave = 22 * sin(clock.time * 1.3 - ring * 0.8) + 9 * sin(clock.time * 3.1 + ring)
    return st.open * (70 + 55 * ring + st.sway * wave)


async def make_rings():
    """The dancers: rings of triangles, each placed and turned by a formula.
    One ring at a time, with a short wait between them: a task that builds
    everything in one step can run past the watchdog on a slow machine."""
    for ring in range(RINGS):
        for k in range(8 + 8 * ring):
            dancer = Triangle(radius=12 + 4 * ring, base_ratio=0.6, color=COLORS[ring], group="dancer")
            dancer.line = None
            dancer["center"] @= lambda ring=ring, k=k: vec_from_angle(turn(ring, k), reach(ring))
            # the tip points along the ring and rocks from side to side, a ring at a time
            dancer["angle"] @= lambda ring=ring, k=k: turn(ring, k) + 90 + 35 * sin(clock.time * 2 - ring)
            dancer.dissolve_in(1.5, style="vortex")
        await wait(0.1)


# ---- the heart: an orb of energy in the middle that breathes slowly ----
heart = Circle(center=(0, 0), radius=40, color="deep pink")
heart.visual = Bolt(style="core")
heart["radius"] @= lambda: st.open * (35 + 5 * sin(clock.time * 2))


async def show():
    await wait(0.5)
    while True:
        # I  Open: the rings open out of a point, the title appears
        canvas.fade_in(1.5)
        title = Text("DEMO 100", center=(0, 0), font_size=110, font="fonts/VastShadow-Regular.ttf")
        title.dissolve_in(2)
        await make_rings()
        await tween(st["open"], 1, time=6, ease="elastic")
        title.dissolve_out(1.5, style="vortex", on_done=title.destroy)
        await wait(2)

        # II  Dance: the rings sway in waves; every bar, a ripple and all the dancers jump
        tween(st["sway"], 1, time=3, ease="ease_in_out")
        canvas.zoom_to(1.15, time=4, ease="ease_in_out")
        for bar in range(8):
            if bar % 2 == 0:
                canvas.ripple_at(0, 0, amount=0.5)
            heart.pop(scale=1.5)
            group["dancer"].pop(0.3, scale=1.5)
            await wait(2)

        # III  Storm: faster and faster, lightning all round, then a burst
        tween(st["spin"], 6, time=8, ease="ease_in")
        canvas.rotate_by(-90, time=9, ease="ease_in")
        for strike in range(16):
            canvas.zap_at(vec_from_angle(strike * 137, 260), style="fork", color="cyan", radius=40)
            await wait(0.5)
        group["dancer"].implode(1)
        await tween(st["open"], 0, time=1, ease="ease_in")
        canvas.explosion_at(0, 0)
        canvas.fade_out(1.5)
        await wait(2)

        # back to the start, in the dark
        group["dancer"].destroy()     # implode() only hid them: the next part I makes new ones
        canvas.zoom_to(1)
        canvas.rotate_to(0)
        st.sway = 0
        st.spin = 1


run_task(show)
run()
