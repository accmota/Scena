"""
endless.py — smoke: Endless fills what the camera sees (Canvas Design, Endless fill).

Question: does the view stay full, seam-free and stable on revisit, in the
three models? A/S cycle modes:

1. Runner (camera moves): parallax image strips + a gameplay terrain builder
   with variable widths; the camera auto-pans, the playfield follows the view.
2. Fixed camera: a scrolling decoration layer (axis="y"); Q/W change
   ``layer.scroll`` live (P3), SPACE stops / restarts it.
3. Grid (axis="xy"): arrows pan freely, Shift+↑/↓ zoom (watch the cap).
"""
import math
import sys as _sys

from scena import *

_sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from _hud import SmokeHud, apply_camera  # noqa: E402
from _media import MEDIA  # noqa: E402

init(width=1200, height=800, window_scale=0.8, title="Smoke — endless")
hud = SmokeHud(
    title="Endless",
    expect="",
    keys="A/S mode  ·  SPACE stop/go  ·  Q/W speed −/+  ·  arrows pan  ·  Shift+↑/↓ zoom  ·  R reset",
    status="",
    show_aux=True,
)

BUILDING = str(MEDIA / "space" / "spaceBuilding_003.png")
METEOR = str(MEDIA / "space" / "meteorBrown_big3.png")
PLANETS = [str(MEDIA / "planets" / f"planet0{k}.png") for k in range(4)]

_fills = []          # the Endless of the current mode
_mode_i = 0
_speed = 160.0
_going = True
_scroll_layer = None


def _clear():
    global _scroll_layer
    for e in _fills:
        e.destroy()
    _fills.clear()
    _scroll_layer = None
    canvas.background.clear()
    for name in list(canvas.layers):
        if name not in ("default", "top", "ui"):
            canvas.layers[name].delete(destroy_shapes=True)
    canvas.reset_view()
    canvas.playfield.pad = 0.25


def _altura(x):
    # A function of world x: neighbouring slots agree at the seam.
    return 150 + 60 * math.sin(x * 0.004) + 22 * math.sin(x * 0.019)


def _terreno(slot):
    pecas, passo = [], 40
    x = slot.left
    while x < slot.right - 1e-9:
        x2 = min(x + passo, slot.right)
        cor = "olive" if slot.i % 2 else "forest green"     # seams visible
        pecas.append(Polygon(points=[(x, 0), (x2, 0), (x2, _altura(x2)), (x, _altura(x))],
                             color=cor, group="chao"))
        x = x2
    if slot.chance(0.35):                                            # local decision
        x = slot.left + slot.rng.uniform(20, slot.right - slot.left - 20)
        pecas.append(Circle(center=(x, _altura(x) + 30), radius=14, color="gold", group="moeda"))
    return pecas


def _m_runner():
    canvas.background.base = SkyGradient("day")
    canvas.layers.create("planetas", pan_response=0.1)
    canvas.layers.create("predios", pan_response=0.4)
    canvas.layers.create("pista", below="default")
    _fills.append(Endless("planetas", PLANETS, bottom=480, gap=(200, 700), seed=1))
    _fills.append(Endless("predios", BUILDING, bottom=120, gap=(30, 220), seed=2))
    _fills.append(Endless("pista", _terreno, step=lambda s: s.rng.choice([160, 240, 400]), seed=3))
    hud.expect = "1 Runner: camera moves; strips lag (parallax); terrain seams line up"


def _meteoro(slot):
    v = canvas.layers["ceu"].view
    x = slot.rng.uniform(v.left + 40, v.right - 40)
    return Sprite(METEOR, center=(x, slot.bottom), size=slot.rng.uniform(40, 110))


def _m_fixed():
    global _scroll_layer
    canvas.background.base = SkyGradient("night")
    canvas.background.add(Stars(scroll=(0, -40)))
    _scroll_layer = canvas.layers.create("ceu", scroll=(0, -180))
    _fills.append(Endless("ceu", _meteoro, axis="y", step=170, seed=4))
    hud.expect = "2 Fixed camera: meteors roll down forever; Q/W change layer.scroll live"


def _setor(slot):
    if slot.chance(0.35):
        return Sprite(slot.rng.choice(PLANETS), center=slot.box.center,
                      size=slot.rng.uniform(60, 150))
    return Rect(center=slot.box.center, width=6, height=6, color=Color(1, 1, 1, 0.25))


def _m_grid():
    canvas.background = (0.03, 0.03, 0.07)
    canvas.layers.create("espaco", below="default")
    _fills.append(Endless("espaco", _setor, axis="xy", step=(300, 300), seed=5))
    hud.expect = "3 Grid (xy): pan anywhere; zoom out to see the margins and the cap"


MODES = [_m_runner, _m_fixed, _m_grid]


def _apply():
    _clear()
    hud.title = f"Endless — [{_mode_i + 1}/{len(MODES)}]"
    MODES[_mode_i]()


def setup(canvas):
    _apply()


def update(dt):
    global _mode_i, _speed, _going
    if keyp.once("A"):
        _mode_i = (_mode_i - 1) % len(MODES)
        _apply()
    if keyp.once("S"):
        _mode_i = (_mode_i + 1) % len(MODES)
        _apply()
    if keyp.once("R"):
        _apply()
    if keyp.once("SPACE"):
        _going = not _going
    if keyp.once("Q"):
        _speed = max(0.0, _speed - 60.0)
    if keyp.once("W"):
        _speed += 60.0

    if _mode_i == 0:
        if _going:
            canvas.pan_to(canvas.pan_x + _speed * dt, canvas.pan_y)
        apply_camera(dt)
        canvas.playfield.set(canvas.game_view.outset(200))
    elif _mode_i == 1 and _scroll_layer is not None:
        target = (0.0, -_speed * 1.1) if _going else (0.0, 0.0)
        _scroll_layer.scroll = chase(_scroll_layer.scroll, target, 3)
    else:
        apply_camera(dt, pan_speed=400.0)

    live = " · ".join(f"{e._layer_key}: {len(e._live)}" for e in _fills if e)
    if _fills:
        e = _fills[-1]
        v = canvas.layers[e._layer_key].view
        under = e.index_at((v.center.x, v.center.y)) if e._axis == "xy" else (
            e.index_at(v.center.x if e._axis == "x" else v.center.y))
        hud.status = f"live slots — {live}  ·  slot under view center: {under}"
    hud.aux = f"speed {_speed:g}  ·  {'going' if _going else 'stopped'}"


run()
