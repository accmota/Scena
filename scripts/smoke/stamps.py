"""stamps.py — smoke: costume + appearance stamps (glow / shadow / hue / tail).

One Shape and one Sprite keep moving so Tail follow-angle is visible. A/S
cycles costumes on both (sprite skips looks that are Shape-only). DropDowns
pick stamp sugar forms (True, color string, constructor, …).

Controls
--------
  A / S     previous / next costume
  SPACE     pause / resume motion
  E         cycle FX quality
  R         clear all stamps (dropdowns → off)
  slider    tail size when locked (not follow)

Usage
-----
    python scripts/smoke/stamps.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from scena import *

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud, cycle_quality

W, H = 1280, 820
init(width=W, height=H, window_scale=0.78, title="Smoke — stamps")
canvas.fx_quality = "high"
canvas.batch_shared_filters = True
canvas.background = (0.07, 0.08, 0.11)
SkyGradient("Blue")
Stars(density=0.55, twinkle=0.2)
canvas.effects.add(Vignette(amount=0.28))

hud = SmokeHud(
    title="Appearance stamps",
    expect="Costume on .visual; stamps via dropdowns. Moving hosts → Tail follow (True / Tail()).",
    keys="A/S costume  ·  SPACE pause  ·  E quality  ·  R clear  ·  slider = locked tail size",
    status="ready",
    show_aux=True,
)

# --- UI ----------------------------------------------------------------------
st.glow_form = "glow: off"
st.shadow_form = "shadow: off"
st.hue_form = "hue: off"
st.tail_form = "tail: off"
st.tail_size = 1.6  # catalog default when size= is omitted

ui.gap()
ui.gap()
ui.gap()
ui.gap()
ui.gap()
ui.gap()
DropDown(
    st.glow_form,
    options=[
        "glow: off",
        "glow: True",
        'glow: "gold"',
        "glow: Glow()",
        "glow: CheapGlow()",
    ],
)
DropDown(
    st.shadow_form,
    options=[
        "shadow: off",
        "shadow: True",
        'shadow: "navy"',
        "shadow: Shadow()",
    ],
)
DropDown(
    st.hue_form,
    options=[
        "hue: off",
        "hue: True",
        "hue: 0.5",
        "hue: HueShift(1/3)",
    ],
)
DropDown(
    st.tail_form,
    options=[
        "tail: off",
        "tail: True (follow)",
        "tail: 270 (locked)",
        'tail: "tomato"',
        "tail: Tail()",
        "tail: Tail(angle=λ)",
    ],
)
_tail_size_slider = Slider(
    st.tail_size,
    label="tail size (locked)",
    show_value=True,
    min_value=0.2,
    max_value=3.0,
)
_tail_size_slider.visible = False

# --- hosts -------------------------------------------------------------------
ball = Circle(center=(W * 0.35, H * 0.45), radius=36).set_color("cyan")
ship = Sprite(
    Sheet("../../examples/media/shooter/sheet.xml"),
    frame="playerShip1_blue.png",
    height=56,
    center=(W * 0.65, H * 0.45),
    art_angle=90,
)

_cap_ball = Text(
    text="shape",
    top_left=(40, H - 143),
    font_size=14,
    color=Color(0.75, 0.8, 0.9, 1),
)
_cap_ship = Text(
    text="sprite",
    top_left=(40, H - 168),
    font_size=14,
    color=Color(0.75, 0.8, 0.9, 1),
)

# Costumes (not stamps). Sprite applies only when allows_sprite.
COSTUMES: list[tuple[str, object]] = [
    ("none", lambda: None),
    ("Neon", lambda: Neon("cyan", amount=1.1, width=3.0)),
    ("Halo", lambda: Halo("gold", amount=1.15)),
    ("Halo fill", lambda: Halo("cyan", style="fill", amount=1.1)),
    ("Halo soft", lambda: Halo("magenta", style="soft", amount=1.15)),
    ("Rim", lambda: Rim("white", amount=1.05, width=3.2)),
    ("Beat", lambda: Beat(amount=0.12, speed=1.3)),
    ("DashRing", lambda: DashRing("cyan", speed=1.1, width=2.0)),
    ("Laser", lambda: Laser("tomato", amount=1.1)),
    ("Ink", lambda: Ink("black", amount=1.5, speed=0.7)),
    ("Metal", lambda: Metal("gray", amount=1.0)),
    ("Flame", lambda: Flame(amount=1.1, speed=1.2)),
    ("Aurora", lambda: Aurora("lime", amount=1.05, speed=0.9)),
    ("Wave", lambda: Wave("dodger blue", amount=1.05, speed=1.0)),
    ("Shield bubble", lambda: Shield(style="bubble", amount=1.05)),
    ("ElectricField", lambda: ElectricField(amount=5, speed=1.0)),
    ("Tracer", lambda: Tracer("gold", speed=1.2, gap=10, width=2.4)),
]

_costume_i = 0
_paused = False
_t = 0.0
_cx, _cy = W * 0.5, H * 0.42


def _look_allows_sprite(look) -> bool:
    if look is None:
        return True
    return bool(getattr(look, "_allows_sprite", False))


def _apply_costume() -> None:
    name, factory = COSTUMES[_costume_i]
    look = factory()
    ball.visual = look
    if _look_allows_sprite(look):
        ship.visual = factory()
        spr_note = name
    else:
        ship.visual = None
        spr_note = f"(skip {name})"
    hud.status = f"costume → {name}  shape={name}  sprite={spr_note}"
    _refresh_caps()


def _type_name(v) -> str:
    return "None" if v is None else type(v).__name__


def _refresh_caps() -> None:
    cname = COSTUMES[_costume_i][0]
    _cap_ball.text = (
        f"ball  costume={cname}  "
        f"glow={_type_name(ball.glow)}  shadow={_type_name(ball.shadow)}  "
        f"tail={_type_name(ball.tail)}"
    )
    _cap_ship.text = (
        f"ship  costume={cname if _look_allows_sprite(ball.visual) else 'none'}  "
        f"glow={_type_name(ship.glow)}  shadow={_type_name(ship.shadow)}  "
        f"hue={_type_name(ship.hue)}  tail={_type_name(ship.tail)}"
    )


def _form_key(v: str) -> str:
    """Strip ``glow: `` / ``shadow: `` / … prefix from dropdown text."""
    s = str(v)
    if ": " in s:
        return s.split(": ", 1)[1]
    return s


def _apply_glow(form: str) -> None:
    form = _form_key(form)
    if form == "off":
        ball.glow = None
        ship.glow = None
    elif form == "True":
        ball.glow = True
        ship.glow = True
    elif form == '"gold"':
        ball.glow = "gold"
        ship.glow = "gold"
    elif form == "Glow()":
        look = Glow("cyan", radius=14, sigma=7, amount=1.15)
        ball.glow = look
        ship.glow = look
    elif form == "CheapGlow()":
        look = CheapGlow("tomato", radius=10, sigma=6, amount=1.1)
        ball.glow = look
        ship.glow = look
    hud.status = f"glow → {form}  read={_type_name(ball.glow)}"
    _refresh_caps()


def _apply_shadow(form: str) -> None:
    form = _form_key(form)
    if form == "off":
        ball.shadow = None
        ship.shadow = None
    elif form == "True":
        ball.shadow = True
        ship.shadow = True
    elif form == '"navy"':
        ball.shadow = "navy"
        ship.shadow = "navy"
    elif form == "Shadow()":
        look = Shadow("black", offset=12, sigma=6)
        ball.shadow = look
        ship.shadow = look
    hud.status = f"shadow → {form}  read={_type_name(ball.shadow)}"
    _refresh_caps()


def _apply_hue(form: str) -> None:
    # Sprite-only stamp; Shape raises (Texture(shift=) is the bitmap path).
    form = _form_key(form)
    if form == "off":
        ship.hue = None
    elif form == "True":
        ship.hue = True
    elif form == "0.5":
        ship.hue = 0.5
    elif form == "HueShift(1/3)":
        ship.hue = HueShift(1.0 / 3.0)
    hud.status = f"hue → {form}  ship.read={_type_name(ship.hue)}  (shape: Texture shift)"
    _refresh_caps()


_LOCKED_TAIL_FORMS = ("270 (locked)", "Tail(angle=λ)")


def _tail_is_locked(form: str | None = None) -> bool:
    return _form_key(form if form is not None else str(st.tail_form)) in _LOCKED_TAIL_FORMS


def _sync_locked_tail_size() -> None:
    """Write slider size onto locked tails; hide the slider in follow / off."""
    locked = _tail_is_locked()
    _tail_size_slider.visible = locked
    if not locked:
        return
    sz = max(0.15, float(st.tail_size))
    if ball.tail is not None:
        ball._tail_size = sz
    if ship.tail is not None:
        ship._tail_size = sz


def _apply_tail(form: str) -> None:
    form = _form_key(form)
    if form == "off":
        ball.tail = None
        ship.tail = None
    elif form == "True (follow)":
        ball.tail = True
        ship.tail = True
    elif form == "270 (locked)":
        ball.tail = 270
        ship.tail = 270
    elif form == '"tomato"':
        ball.tail = "tomato"
        ship.tail = "tomato"
    elif form == "Tail()":
        look = Tail("orange", size=1.4, amount=0.55)
        ball.tail = look
        ship.tail = look
    elif form == "Tail(angle=λ)":
        ball.tail = Tail(
            "gold",
            angle=lambda: ball.angle + 180.0,
            amount=1.15,
        )
        ship.tail = Tail(
            "gold",
            angle=lambda: ship.angle + 180.0,
            amount=1.15,
        )
    _sync_locked_tail_size()
    hud.status = f"tail → {form}  read={_type_name(ball.tail)}"
    _refresh_caps()


@on_change(st.glow_form)
def on_glow(v):
    _apply_glow(str(v))


@on_change(st.shadow_form)
def on_shadow(v):
    _apply_shadow(str(v))


@on_change(st.hue_form)
def on_hue(v):
    _apply_hue(str(v))


@on_change(st.tail_form)
def on_tail(v):
    _apply_tail(str(v))


@on_change(st.tail_size)
def on_tail_size(v):
    _sync_locked_tail_size()
    if _tail_is_locked():
        hud.status = f"tail size → {float(v):.2f}"
        _refresh_caps()


def _clear_stamps() -> None:
    st.glow_form = "glow: off"
    st.shadow_form = "shadow: off"
    st.hue_form = "hue: off"
    st.tail_form = "tail: off"
    st.tail_size = 1.6
    _tail_size_slider.visible = False
    hud.status = "stamps cleared"


def update(dt):
    global _t
    if not _paused:
        _t += dt
    # Opposing ellipses so follow-tail swings through many headings.
    a = _t * 0.85
    b = _t * 1.05 + math.pi
    ball.center = (_cx + 220.0 * math.cos(a), _cy + 120.0 * math.sin(a))
    ball.angle = math.degrees(a) + 90.0
    ship.center = (_cx + 220.0 * math.cos(b), _cy + 120.0 * math.sin(b * 0.9))
    ship.angle = math.degrees(b) + 90.0
    hud.aux = (
        f"t={_t:.1f}  costume={COSTUMES[_costume_i][0]}  "
        f"glow={st.glow_form}  shadow={st.shadow_form}  "
        f"hue={st.hue_form}  tail={st.tail_form}  "
        f"{'size=' + f'{float(st.tail_size):.2f}' if _tail_is_locked() else 'size=follow'}  "
        f"{'PAUSED' if _paused else 'moving'}"
    )


def on_key_down(key):
    global _costume_i, _paused
    if key == "A":
        _costume_i = (_costume_i - 1) % len(COSTUMES)
        _apply_costume()
    elif key == "S":
        _costume_i = (_costume_i + 1) % len(COSTUMES)
        _apply_costume()
    elif key == "SPACE":
        _paused = not _paused
        hud.status = "paused" if _paused else "moving"
    elif key == "E":
        hud.status = f"quality={cycle_quality()}"
    elif key == "R":
        _clear_stamps()


_apply_costume()
_refresh_caps()
run()
