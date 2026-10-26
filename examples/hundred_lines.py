"""100 Lines: a size-limited intro, in the spirit of the demoscene's 4k intros.

A whole piece in at most 100 lines of plain code. No shader, no pixel loop:
everything that moves is a formula of the clock (@=), a light on a Track, or an effect.

  I    Bloom    nested hexagons open out of a point
  II   Vortex   they twist into a spiral; a ring of petals springs out round the comet
  III  Tunnel   the centres trail round into a tunnel; a dive, a burst, and again
Try: change the number of hexagons, the colour wheel, or how far st.twist goes. No keys: it loops.
"""
from scena import *

init(width=1280, height=800, title="100 Lines")
canvas.set_origin("center")         # (0, 0) in the middle keeps the formulas short
Nebula(color="indigo", color2="teal", alpha=0.6)
light = Bloom(intensity=0.8)
play_sound("music/super_hero_original_no_intro.ogg", loops="forever", volume=0.8)
wheel = Colormap.from_colors("deep pink", "orange", "gold", "lime", "deep sky blue", "violet", "deep pink")
st.open = 0         # 0: shut in a point · 1: wide open
st.twist = 0        # degrees each hexagon turns past the one inside it
st.bend = 0         # 0: one centre · 1: each centre trails the one inside it (a tunnel)
st.petals = 0       # how far out the ring of petals is
st.spin = 1         # how fast everything turns
st.pulse = 0        # 1 on a kick drum, then it fades (see update)
st.beat = 1         # how much the strokes follow the music: only under the title

def wheel_color(i):
    # int(): the colours step round the wheel, four steps a second
    step = int(clock.time * 4 + i) % 24
    return wheel.get_color(step / 24)

# ---- the core: nested hexagons whose size, turn, place and colour are formulas ----
for i in range(19):
    hexagon = RegularPolygon(n=6, angle=lambda i=i: clock.time * 20 * st.spin + i * st.twist)
    hexagon["radius"] @= lambda i=i: st.open * (14 + 17 * i)
    hexagon["center"] @= lambda i=i: vec_from_angle(clock.time * 70 - i * 12, st.bend * (220 - 11 * i))
    hexagon.fill = None
    hexagon["line_width"] @= lambda: 3 + 4 * st.pulse
    hexagon["line"] @= lambda i=i: wheel_color(i)

# ---- a ring of petals, each one riding it with its tip ahead ----
def on_ring(k):
    return k * 15 + clock.time * 15 * st.spin       # where petal k is on the ring, in degrees

for k in range(24):
    petal = Triangle(radius=20, base_ratio=0.5, angle=lambda k=k: on_ring(k) + 90)
    petal["center"] @= lambda k=k: vec_from_angle(on_ring(k), st.petals * st.open * 340)
    petal["color"] @= lambda k=k: wheel_color(k)

# ---- light on tracks: a zigzag crown, lit only along a window that runs round it ----
glint = Track.circle(center=(0, 0), radius=390, color="white", line_width=4).zigzag(amount=8, waves=72)
glint["begin"] @= lambda: clock.time * 0.25 % 1
glint["end"] @= lambda: (clock.time * 0.25 + 0.12) % 1
# a comet riding a long, smooth loop that wanders round the screen
roam = Track(points=[(-520, 250), (-60, 320), (470, 260), (540, -150), (120, -320),
                     (-330, -250), (-560, -20)], smooth=1, closed=True)
comet = Circle(radius=9, color="white")
comet.tail = Tail(color="gold", size=4)
comet.move_along(roam, time=18, loops="forever")

async def show():
    await wait(0.5)
    while True:
        # I  Bloom: the title, and the hexagons open out of a point
        canvas.fade_in(1.5)
        title = Text("100 LINES OF SCENA", center=(0, 0), font_size=80, font="fonts/VastShadow-Regular.ttf")
        title.dissolve_in(2.5)
        await tween(st["open"], 1, time=8, ease="ease_out")
        canvas.ripple_at(0, 0)
        title.dissolve_out(1.5, style="vortex", on_done=title.destroy)
        tween(st["beat"], 0, time=1.5)         # the strokes settle to a calm width
        # II  Vortex: the hexagons twist into a spiral, the petals spring out
        canvas.zoom_to(1.2, time=4, ease="ease_in_out")
        tween(st["petals"], 1, time=3, ease="elastic")
        await tween(st["twist"], 8, time=5, ease="ease_in_out")
        for bang in range(16):
            canvas.burst_at(comet, radius=50)
            await wait(0.75)
        # III  Tunnel: the centres trail round; it spins up, falls into a point and bursts
        prism = Prism(amount=0.006)
        await tween(st["bend"], 1, time=5, ease="ease_in_out")
        prism.remove()
        canvas.rotate_by(-360, time=8.5, ease="ease_in")
        canvas.zoom_to(1, time=7, ease="ease_in_out")
        await tween(st["spin"], 8, time=7, ease="ease_in")
        await tween(st["open"], 0, time=1.5, ease="ease_in")
        canvas.explosion_at(0, 0)
        canvas.fade_out(1.5)
        await wait(2)
        st.open, st.twist, st.bend, st.petals, st.spin, st.beat = 0, 0, 0, 0, 1, 1

def update(dt):
    bass = amp_db(audio.spectrum(4)[0])      # about 0.62 in this song, 0.1 more on a kick drum
    kick = 8 * st.beat * (bass - 0.62)
    st.pulse = max(0, st.pulse - 2 * dt, kick)       # it jumps on a kick, then fades
    light.intensity = 0.9 + 0.8 * st.pulse

run_task(show)
run()
