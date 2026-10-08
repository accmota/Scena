"""Osciloscópio v2 — Contrail + History recipes.

Substitui o last_point + Line + after(destroy) do v1 por:
  - Contrail com fade (traço contínuo)
  - Segments (History): um Line por amostra
  - Dots (History): círculos que dissolve_out e destroy ao sair

Controles
---------
  clique na bola   liga / reinicia a amostragem
  painel           n, harmônicos, modo do rastro

Uso
---
    python examples/osciloscopio.py
"""
from scena import *
from math import cos, sin


W, H = 1000, 720
init(width=W, height=H, title="Osciloscópio v2")
canvas.background = (0.06, 0.07, 0.1)
Stars(density=0.4, twinkle=0.15)

ui.scale = 0.9

st.n = 4
st.x1=50
st.tx1 = 2
st.y1 = 50
st.ty1 = 2
st.modo = "Contrail fade"
Slider(st.n, label="n", min_value=1, max_value=6)
Slider(st.x1, label="x1", min_value=-100, max_value=100)
Slider(st.tx1, label="tx1", min_value=-10, max_value=10, only_int=True)
Slider(st.y1, label="y1", min_value=-100, max_value=100)
Slider(st.ty1, label="ty1", min_value=-10, max_value=10, only_int=True)
DropDown(
    st.modo,
    options=["Contrail fade", "Contrail flat", "Segments", "Dots"],
)

bola = Circle(center=(W * 0.55, H * 0.5), radius=18)
bola.visual = Halo("red", style="fill")

st.new_time = 0
st["new_time"] @= lambda: clock.time * st.n
dst = Point()
dst @= lambda: (
    bola.center.x + 200 * cos(st.new_time) + st.x1 * cos(st.new_time * st.tx1),
    bola.center.y + 200 * sin(st.new_time) + st.y1 * sin(st.new_time * st.ty1),
)

beam = Line(p1=lambda: bola.center, p2=lambda: dst)
beam.visual = ElectricField("yellow")
beam.visible = False

# --- trail recipes ----------------------------------------------------------

contrail_fade = Contrail(
    max_points=120, duration=6.0 / 4.0, fade=True, ease="ease_out",
    visual=Laser("red"), line_width=2.5,
)
contrail_flat = Contrail(
    max_points=120, duration=6.0 / 4.0, fade=False,
    color=Color("orange").with_alpha(0.85), line_width=2.0,
)


segments = History(max_points=80, duration=1.5)
dots = History(max_points=50, duration=1.2, on_leave=lambda dot: dot.dissolve_out(0.25))

_all_trails = (contrail_fade, contrail_flat, segments, dots)


def _active():
    m = st.modo
    if m == "Contrail fade":
        return contrail_fade
    if m == "Contrail flat":
        return contrail_flat
    if m == "Segments":
        return segments
    return dots


def _clear_others(keep):
    for t in _all_trails:
        if t is keep:
            continue
        t.clear()


def sample():
    trail = _active()
    # Sync duration with n (shorter trail when faster).
    trail.duration = max(0.4, 6.0 / max(1.0, float(st.n)))
    if trail is segments:
        start = segments.last.p2 if segments else dst
        segment = segments.add(Line(p1=start, p2=dst))
        segment.visual = Laser("tomato")
    elif trail is dots:
        dot = dots.add(Circle(center=dst, radius=3.5))
        dot.visual = Halo("cyan")
    else:
        trail.snapshot(dst)


_sampler = None


@click(bola)
def arm():
    global _sampler
    beam.visible = True
    keep = _active()
    _clear_others(keep)
    if _sampler is not None:
        _sampler.cancel()
    interval = 6.28 / (st.n * 100)
    _sampler = every(interval, sample, name="osc_sample")


Text("clique na bola · troque o modo no painel", top_left=(20, H - 17), font_size=16)

run()
