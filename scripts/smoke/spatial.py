"""
spatial.py — smoke: every SpatialFx kind + live param sliders + probe.

All emitters on screen. A/S focuses one; sliders tune the focused emitter.
Drag the white probe — turns yellow on hit.

Kinds: Fire (camp/soft/plume/tongues/embers/blaze), Sparks, GlowSpot, Orb,
       Sunburst, Starburst, Warp, Portal, Rain, Jet.
E cycles quality: Fire blaze draws the plume look at medium / low.
"""
from __future__ import annotations

import sys
from pathlib import Path

from scena import *
from scena.orchestration import ScenaFramework

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud, cycle_quality

W, H = 1280, 800
init(width=W, height=H, window_scale=0.75, title="Smoke — SpatialFx")
canvas.background = (0.06, 0.07, 0.1, 1)
canvas.fx_quality = "high"

hud = SmokeHud(
    title="SpatialFx",
    expect="All kinds visible; A/S focus; sliders tune focus; drag probe — yellow on hit",
    keys="A/S focus  ·  SPACE colliders  ·  E quality",
    status="",
)

ground = Rect(center=(W * 0.5, 60), width=W - 80, height=36)
ground.set_color(0.16, 0.18, 0.2)
ground.line = None

# (label, factory(center) -> SpatialFx, param_spec)
# param_spec: ("name", lo, hi, default) or ("name", "bool", default)
_CATALOG = [
    ("Fire camp", lambda c: Fire(center=c, radius=28, style="camp"),
     [("radius", 0.0, 200.0, 28.0), ("amount", 0.2, 2.0, 1.0), ("speed", 0.2, 3.0, 1.0)]),
    ("Fire soft", lambda c: Fire(center=c, radius=28, style="soft"),
     [("radius", 0.0, 200.0, 28.0), ("amount", 0.2, 2.0, 1.0)]),
    ("Fire plume", lambda c: Fire(center=c, width=26, style="plume"),
     [("width", 0.0, 200.0, 26.0), ("amount", 0.2, 2.0, 1.0), ("rate", 10.0, 120.0, 70.0),
      ("angle", 0.0, 360.0, 90.0), ("length", 0.0, 200.0, 57.0)]),
    ("Fire tongues", lambda c: Fire(center=c, width=26, style="tongues"),
     [("width", 0.0, 200.0, 26.0), ("length", 0.0, 200.0, 68.0),
      ("amount", 0.2, 2.0, 1.0), ("angle", 0.0, 360.0, 90.0)]),
    ("Fire embers", lambda c: Fire(center=c, width=24, style="embers"),
     [("width", 0.0, 200.0, 24.0), ("length", 0.0, 200.0, 58.0),
      ("amount", 0.2, 2.0, 1.0), ("rate", 5.0, 80.0, 35.0),
      ("angle", 0.0, 360.0, 90.0)]),
    ("Fire blaze", lambda c: Fire(center=(c[0], c[1] - 50), width=34, style="blaze"),
     [("width", 0.0, 200.0, 34.0), ("length", 0.0, 200.0, 82.0),
      ("amount", 0.2, 2.0, 1.0), ("speed", 0.0, 3.0, 1.2),
      ("angle", 0.0, 360.0, 90.0)]),
    ("Sparks", lambda c: Sparks(center=c, radius=28, rate=36),
     [("radius", 0.0, 200.0, 28.0), ("rate", 5.0, 100.0, 36.0), ("amount", 0.2, 2.0, 1.0)]),
    ("Sparks large", lambda c: Sparks(center=c, radius=60, rate=50),
     [("radius", 0.0, 200.0, 60.0), ("rate", 5.0, 120.0, 50.0), ("amount", 0.2, 2.0, 1.0)]),
    ("GlowSpot", lambda c: GlowSpot(center=c, radius=48, color="cyan", amount=0.75),
     [("radius", 0.0, 200.0, 48.0), ("intensity", 0.1, 1.5, 0.75)]),
    ("Orb (sun-like)", lambda c: Orb(center=c, radius=28),
     [("radius", 0.0, 200.0, 28.0), ("amount", 0.2, 2.0, 1.0), ("glow", 0.0, 2.0, 1.0)]),
    ("Orb (moon-like)", lambda c: Orb(
        center=c, radius=26, color=(0.82, 0.88, 1.0),
        glow=1.15, phase=0.15, soft_edge=0.1,
    ),
     [("radius", 0.0, 200.0, 26.0), ("amount", 0.2, 2.0, 1.0),
      ("glow", 0.0, 2.0, 1.15), ("phase", 0.0, 1.0, 0.15)]),
    ("Sunburst", lambda c: Sunburst(center=c, radius=30),
     [("radius", 0.0, 200.0, 30.0), ("amount", 0.2, 2.0, 1.0), ("speed", 0.2, 3.0, 1.0)]),
    ("Starburst", lambda c: Starburst(center=c, radius=26, color="green"),
     [("radius", 0.0, 200.0, 26.0), ("amount", 0.2, 2.0, 1.0), ("speed", 0.2, 3.0, 1.0)]),
    ("Warp", lambda c: Warp(center=c, radius=48, color="cyan"),
     [("radius", 0.0, 200.0, 48.0), ("amount", 0.2, 2.0, 1.0), ("speed", 0.2, 3.0, 1.0),
      ("twist", 0.0, 2.0, 0.35), ("spokes", 3.0, 24.0, 6.0), ("core", 0.0, 1.5, 1.0)]),
    ("Warp sink", lambda c: Warp(
        center=c, radius=48, color="navy", color2="black",
        core=0.0, twist=1.2, into=False, glow=0.35,
    ),
     [("radius", 0.0, 200.0, 48.0), ("amount", 0.2, 2.0, 1.0), ("twist", 0.0, 2.0, 1.2),
      ("core", 0.0, 1.5, 0.0), ("spin", -2.0, 2.0, 0.0)]),
    ("Portal", lambda c: Portal(center=c, radius=36),
     [("radius", 0.0, 200.0, 36.0), ("thickness", 0.05, 1.0, 0.25), ("chaos", 0.0, 2.0, 1.0),
      ("amount", 0.2, 2.0, 1.0), ("speed", 0.0, 3.0, 1.0), ("glow", 0.0, 2.0, 0.8)]),
    ("Portal tilted", lambda c: Portal(center=c, radius=40, tilt=62, angle=15, color="magenta"),
     [("tilt", -85.0, 85.0, 62.0), ("angle", -180.0, 180.0, 15.0), ("chaos", 0.0, 2.0, 1.0),
      ("thickness", 0.05, 1.0, 0.25), ("radius", 0.0, 200.0, 40.0)]),
    ("Rain", lambda c: Rain(center=c, width=160, height=200, amount=0.55),
     [("density", 0.05, 1.5, 0.55), ("width", 0.0, 200.0, 160.0), ("height", 0.0, 200.0, 200.0)]),
    ("Jet", lambda c: Jet(origin=(c[0] - 40, c[1]), angle=0, length=120, width=14),
     [("length", 0.0, 200.0, 120.0), ("width", 0.0, 200.0, 14.0), ("amount", 0.2, 2.0, 1.0),
      ("angle", -180.0, 180.0, 0.0)]),
]

_COLS = 7
_CELL_W = 172
_CELL_H = 180
_ORIGIN_X = 95
_ORIGIN_Y = 540

_emitters = []
_focus = 0
_show_col = False

_focus_ring = Circle(center=(0, 0), radius=58)
_focus_ring.fill = None
_focus_ring.line = Color(1.0, 0.85, 0.3, 1)
_focus_ring.line_width = 3


def _cell_center(i: int):
    col = i % _COLS
    row = i // _COLS
    return (_ORIGIN_X + col * _CELL_W, _ORIGIN_Y - row * _CELL_H)


for i, (label, factory, _) in enumerate(_CATALOG):
    cx, cy = _cell_center(i)
    fx = factory((cx, cy))
    fx.collidable = True
    fx.tag("sfx")
    _emitters.append(fx)
    Text(
        text=label,
        top_left=(cx - 48, cy + 86),
        font_size=12,
        color=Color(0.65, 0.7, 0.8, 1),
    )

# ---------------------------------------------------------------------------
# Param panel (shape_fx-style remappable sliders)
# ---------------------------------------------------------------------------
N_SLIDERS = 6
PANEL_X = 16
PANEL_TOP = H - 140
_theme = ScenaFramework.get_instance().widget_manager.widget_theme
_theme._ensure()
ROW = max(_theme.row_height, 2 * _theme.slider_handle_radius) + _theme.stack_gap
_panel_sliders: list[Slider] = []
_param_map: list[tuple] = []

for i in range(N_SLIDERS):
    s = Slider(
        label="—",
        top_left=(PANEL_X, PANEL_TOP - i * ROW + 28),
        width=280,
        min_value=0.0,
        max_value=100.0,
        initial=50.0,
        show_value=True,
    )
    s.visible = False
    _panel_sliders.append(s)


def _setup_slider(s: Slider, label: str, lo: float, hi: float, val: float) -> None:
    s.min_value = float(lo)
    s.max_value = float(hi)
    s.only_int = False
    s.label = label
    label_space = max(s._theme.default_font.measureText(str(label)) + 10, 72)
    s._update_track_layout(label_space)
    s.data.value = float(val)
    s.visible = True


def _configure_panel(spec: list) -> None:
    global _param_map
    _param_map = []
    si = 0
    for entry in spec:
        name, lo, hi, default = entry
        s = _panel_sliders[si]
        _setup_slider(s, name, lo, hi, default)
        _param_map.append((s, name))
        si += 1
    for s in _panel_sliders[si:]:
        s.visible = False
        s.label = "—"


def _read_params() -> dict:
    return {name: float(w.value) for w, name in _param_map}


def _apply_params_to(fx, params: dict) -> None:
    for key, val in params.items():
        try:
            if key == "radius":
                fx.radius = val
            elif key in ("width", "height", "length", "angle"):
                setattr(fx, key, val)
            elif key == "intensity":
                fx.intensity = val
            elif key == "density":
                fx.density = val
            elif key == "rate":
                fx.rate = val
            elif key == "amount":
                fx.amount = val
                fill = getattr(fx, "_fill", None)
                if fill is not None and hasattr(fill, "amount"):
                    try:
                        fill.amount = val
                    except Exception:
                        pass
            elif key in ("glow", "phase"):
                setattr(fx, key, val)
            elif key == "speed":
                fx.speed = val
                fill = getattr(fx, "_fill", None)
                if fill is not None and hasattr(fill, "speed"):
                    try:
                        fill.speed = val
                    except Exception:
                        pass
            elif key == "spokes":
                fx.spokes = val
            elif key == "into":
                fx.into = bool(val >= 0.5)
            else:
                setattr(fx, key, val)
        except Exception:
            pass


def _set_focus(i: int):
    global _focus
    n = len(_emitters)
    _focus = i % n
    label, _, spec = _CATALOG[_focus]
    cx, cy = _cell_center(_focus)
    _focus_ring.center = (cx, cy)
    hud.title = f"SpatialFx — {label}"
    hud.expect = f"[{_focus + 1}/{n}] drag probe into any emitter; sliders tune focus"
    hud.status = f"focus={label}"
    _configure_panel(spec)


_set_focus(0)

probe = Circle(center=(W - 90, 180), radius=22, group="probe").set_color("white")
probe.draggable = True


@collide("probe", "sfx")
def _on_hit(me, other, info):
    me.set_color("yellow")
    hud.status = f"hit {type(other).__name__}"


@collide_exit("probe", "sfx")
def _on_exit(me, other, info):
    me.set_color("white")


def update(dt):
    fx = _emitters[_focus]
    if fx is not None:
        _apply_params_to(fx, _read_params())


def on_key_down(key):
    global _show_col
    if key == "A":
        _set_focus(_focus - 1)
    elif key == "S":
        _set_focus(_focus + 1)
    elif key == "SPACE":
        _show_col = not _show_col
        collision.show_colliders(_show_col)
        hud.status = f"colliders={'on' if _show_col else 'off'}"
    elif key == "E":
        hud.status = f"quality={cycle_quality()}"


run()
