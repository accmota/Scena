"""
GlowSpot SpatialFx playground — many additive radial fades, dancing.

Each blob is a solid-color gradient/alpha wash (Plus blend). Overlaps mix.

Keys
----
  SPACE   pause / resume motion
  E       cycle FX quality
  Q / W   fewer / more spots
  R       reshuffle orbits
"""
import math
import random
from scena import *

W, H = 1280, 800
init(width=W, height=H, window_scale=0.75, title="Scena — GlowSpot")
canvas.background = (0.02, 0.025, 0.04, 1)
canvas.fx_quality = "high"

COLORS = (
    "cyan", "magenta", "gold", "lime", "orange", "tomato",
    "dodger blue", "orchid", "coral", "deep sky blue", "hot pink",
    "turquoise", "violet", "yellow", "salmon", "aqua",
)

_spots = []
_paused = False
_n = 16


def _orbit(i, n):
    rng = random.Random(i * 17 + n * 3)
    return {
        "ox": rng.uniform(90, W - 90),
        "oy": rng.uniform(90, H - 90),
        "ax": rng.uniform(40, 160),
        "ay": rng.uniform(30, 130),
        "freq": rng.uniform(0.25, 0.95),
        "fy": rng.uniform(0.22, 0.85),
        "ph": rng.uniform(0, math.tau),
        "r0": rng.uniform(100, 300),
        "rp": rng.uniform(0.06, 0.18),
        "rf": rng.uniform(0.6, 1.6),
        "amount": rng.uniform(0.75, 1.15),
    }


def _rebuild(n=None):
    global _spots, _n
    if n is not None:
        _n = max(4, min(36, int(n)))
    for s in list(_spots):
        try:
            s["spot"].destroy()
        except Exception:
            pass
    _spots = []
    for i in range(_n):
        spec = _orbit(i, _n)
        color = COLORS[i % len(COLORS)]
        fx = GlowSpot(
            center=(spec["ox"], spec["oy"]),
            radius=spec["r0"],
            color=color,
            amount=spec["amount"],
        )
        spec["spot"] = fx
        spec["color"] = color
        _spots.append(spec)


hud = Text(
    text="",
    top_left=(20, H - 17), font_size=16,
    color=Color(0.9, 0.93, 0.98, 1),
)
hint = Text(
    text="SPACE pause  ·  E quality  ·  Q / W count  ·  R reshuffle",
    top_left=(20, H - 45), font_size=14,
    color=Color(0.55, 0.62, 0.75, 1),
)


def _hud():
    q = canvas.fx_quality
    qn = q.value if q is not None else "?"
    hud.text = f"GlowSpot × {_n}   quality={qn}   additive radial fades"


def setup(canvas):
    _hud()


def update(dt):
    global _paused, _n
    if keyp.once("SPACE"):
        _paused = not _paused
    if keyp.once("E"):
        ladder = ("low", "medium", "high", "max")
        name = canvas.fx_quality.value if canvas.fx_quality is not None else "high"
        i = ladder.index(name) if name in ladder else 2
        canvas.fx_quality = ladder[(i + 1) % len(ladder)]
        _hud()
    if keyp.once("Q"):
        _rebuild(_n - 2)
        _hud()
    if keyp.once("W"):
        _rebuild(_n + 2)
        _hud()
    if keyp.once("R"):
        _rebuild(_n)
        _hud()
    if _paused:
        return
    t = float(clock.time)
    for spec in _spots:
        fx = spec["spot"]
        x = spec["ox"] + spec["ax"] * math.sin(t * spec["freq"] + spec["ph"])
        y = spec["oy"] + spec["ay"] * math.cos(t * spec["fy"] + spec["ph"] * 1.3)
        fx.center = (x, y)
        r = spec["r0"] * (1.0 + spec["rp"] * math.sin(t * spec["rf"] + spec["ph"]))
        fx.radius = r


_rebuild(_n)
_hud()
canvas.framerate = "max"
run()
