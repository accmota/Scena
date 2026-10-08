"""look_fx.py — smoke: looks shared by Shape and Sprite (no filters / canvas post).

Two body modes (same look catalog):
  1 / G     filled shapes only (no Lines) — like shape_fx minus strokes
  2 / T     sprites (hitbox arts)

Controls
--------
  Q / W     cycle shared looks
  SPACE     clear look (baseline)
  1 / G     shapes mode
  2 / T     sprites mode
  E         cycle FX quality
  Click     flash + pop on nearest graphic

Usage
-----
    python scripts/smoke/look_fx.py
    python scripts/smoke/look_fx.py --mode sprites --look halo --n 40
"""
from __future__ import annotations

import argparse
import math
import os
import random

from scena import *
from scena.orchestration import ScenaFramework

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--mode", default="shapes", choices=("shapes", "sprites"),
    help="initial body mode",
)
parser.add_argument("--look", default="none", help="initial look name")
parser.add_argument(
    "--quality", default="high",
    choices=("low", "medium", "high", "max"),
)
parser.add_argument("--n", type=int, default=40, help="graphic count")
args, _ = parser.parse_known_args()

W, H = 1200, 800
init(width=W, height=H, window_scale=0.75, title="Smoke — look FX (shape ↔ sprite)")
canvas.fx_quality = args.quality
canvas.batch_shared_filters = True
canvas.background = (0.07, 0.08, 0.11)
canvas.effects.clear()
set_extrude_focus(W * 0.5, H * 0.08)

import sys as _sys
_sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from _hud import SmokeHud, cycle_quality
import _media

hud = SmokeHud(
    title="Look FX",
    expect="Shared Shape/Sprite looks only — no filters / canvas post",
    keys="1/G shapes  ·  2/T sprites  ·  Q/W look  ·  SPACE none  ·  E quality  ·  click",
    status="",
)

COLORS = (
    "cyan", "magenta", "gold", "lime", "orange",
    "dodger blue", "orchid", "white", "tomato", "green",
)

# ---------------------------------------------------------------------------
# Shared look catalog (allows_sprite ∩ Shape-legal)
# ---------------------------------------------------------------------------

LOOKS: list[tuple[str, str, object]] = [
    ("none", "none", lambda: None),
    ("glow", "Glow", lambda: Glow(radius=12, sigma=8, amount=1.15)),
    ("cheapglow", "CheapGlow", lambda: CheapGlow(radius=10, sigma=6, amount=1.1)),
    ("shadow", "Shadow", lambda: Shadow(offset=10, sigma=6)),
    ("halo", "Halo", lambda: Halo("cyan", amount=1.15)),
    ("halo_fill", "Halo fill", lambda: Halo("cyan", style="fill", amount=1.1)),
    ("halo_soft", "Halo soft", lambda: Halo("cyan", style="soft", amount=1.15)),
    ("halo_line", "Halo line", lambda: Halo("lime", style="line", amount=1.2)),
    ("tail", "Tail", lambda: Tail("orange", angle=90, size=1.5, amount=1.15)),
    ("beat", "Beat", lambda: Beat(amount=0.12, speed=1.3)),
    ("rim", "Rim", lambda: Rim("white", amount=1.05, width=3.2)),
    ("dashring", "DashRing", lambda: DashRing("cyan", speed=1.1, width=2.0)),
    ("gearshell", "GearShell", lambda: GearShell("orchid", speed=1.2, amount=1.05)),
    ("laser", "Laser", lambda: Laser("tomato", amount=1.1)),
    ("ink", "Ink", lambda: Ink("black", amount=1.5, speed=0.7)),
    ("inkbleed", "InkBleed", lambda: InkBleed("navy", amount=1.05)),
    ("electricfield", "ElectricField", lambda: ElectricField(amount=5, speed=1.0)),
    ("electricbolt", "ElectricBolt", lambda: ElectricBolt("gold", amount=5, speed=1.0)),
    ("shield_bubble", "Shield bubble", lambda: Shield(style="bubble", amount=1.05)),
    ("shield_nebula", "Shield nebula", lambda: Shield(style="nebula", amount=1.05)),
    ("shield_ember", "Shield ember", lambda: Shield(style="ember", amount=1.05)),
    ("shield_void", "Shield void", lambda: Shield(style="void", amount=1.05)),
    ("shield_molten", "Shield molten", lambda: Shield(style="molten", amount=1.1, speed=1.15)),
    ("shield_bands", "Shield bands", lambda: Shield("teal", style="bands", amount=1.05, speed=0.4)),
    ("shield_vortex", "Shield vortex", lambda: Shield("orchid", style="vortex", amount=1.1)),
    ("shield_plasma", "Shield plasma", lambda: Shield(style="plasma", amount=1.1)),
    ("shield_cracks", "Shield cracks", lambda: Shield(style="cracks", amount=1.1)),
    ("shield_frost", "Shield frost", lambda: Shield(style="frost", amount=1.1)),
    ("metal", "Metal", lambda: Metal("gray", amount=1.0, speed=1.0)),
    ("flame", "Flame", lambda: Flame(amount=1.1, speed=1.2)),
    ("swell", "Swell", lambda: Swell(amount=1.0, speed=1.0)),
    ("aurora", "Aurora", lambda: Aurora("lime", amount=1.05, speed=0.9)),
    ("wave", "Wave", lambda: Wave("dodger blue", amount=1.05, speed=1.0)),
    ("extrude", "Extrude", lambda: Extrude("steelblue", depth=40, layers=5, angle=225)),
    ("multiborder", "MultiBorder", lambda: MultiBorder("cyan", layers=3, spread=0.32)),
    ("organic", "OrganicOutline", lambda: OrganicOutline("white", amount=2.2, speed=1.0)),
    ("tracer", "Tracer", lambda: Tracer("gold", speed=1.2, gap=10, width=2.4)),
]

_look_names = [m[0] for m in LOOKS]
_l_idx = _look_names.index(args.look) if args.look in _look_names else 0
_mode = "sprites" if args.mode == "sprites" else "shapes"

# Set False to feel the hitch when first assigning a silhouette / SDF look.
PREPARE_FX = True

movers: list[dict] = []

def _sprite_arts() -> list[str]:
    """The shared hitbox singles (``scripts/smoke/_media.py``)."""
    return [_media.path(rel) for rel in _media.HITBOX_SINGLES]


_ARTS = _sprite_arts()


def _clear_movers() -> None:
    for m in list(movers):
        g = m.get("shape")
        if g is not None and getattr(g, "is_alive", True):
            try:
                g.destroy()
            except Exception:
                pass
    movers.clear()


def _spawn_shapes() -> None:
    _clear_movers()
    random.seed(42)
    for i in range(args.n):
        kind = i % 6
        x = random.uniform(80, W - 80)
        y = random.uniform(80, H - 80)
        size = random.uniform(14, 52)
        ang = random.uniform(0, 360)
        if kind == 0:
            shp = Circle(center=(x, y), radius=size * 0.5)
        elif kind == 1:
            shp = Square(center=(x, y), length=size, angle=ang)
        elif kind == 2:
            shp = Rect(center=(x, y), width=size * 1.4, height=size * 0.7, angle=ang)
        elif kind == 3:
            shp = EquilateralTriangle(center=(x, y), radius=size * 0.55, angle=ang)
        elif kind == 4:
            shp = RegularPolygon(n=5 + (i % 3), center=(x, y), radius=size * 0.5, angle=ang)
        else:
            shp = Ellipse(center=(x, y), width=size * 1.2, height=size * 0.55, angle=ang)
        color = COLORS[i % len(COLORS)]
        shp.set_color(color)
        shp.line_width = random.uniform(1.5, 2.4)
        if i % 2:
            shp.set_alpha((0.35, 0.5, 0.65, 0.8, 0.9)[i % 5])
        movers.append({
            "shape": shp,
            "ox": x, "oy": y,
            "base_color": color,
            "base_fill": shp.fill,
            "base_line": shp.line,
            "base_line_width": shp.line_width,
            "amp": 18 + (i % 5) * 11,
            "freq": 0.4 + (i % 7) * 0.11,
            "phase": i * 0.37,
            "spin": (i % 9 - 4) * 22.0,
        })


def _spawn_sprites() -> None:
    _clear_movers()
    random.seed(42)
    for i in range(args.n):
        x = random.uniform(80, W - 80)
        y = random.uniform(80, H - 80)
        path = _ARTS[i % len(_ARTS)]
        kw = {"height": 48, "center": (x, y), "group": "look"}
        spr = Sprite(path, **kw)
        movers.append({
            "shape": spr,
            "ox": x, "oy": y,
            "base_color": None,
            "base_fill": None,
            "base_line": None,
            "base_line_width": getattr(spr, "line_width", 1.5),
            "amp": 16 + (i % 5) * 10,
            "freq": 0.38 + (i % 6) * 0.1,
            "phase": i * 0.41,
            "spin": (i % 8 - 3.5) * 20.0,
        })


def _restore_base(m: dict) -> None:
    shp = m["shape"]
    try:
        if type(shp).__name__ == "Sprite":
            shp.visual = None
            shp.glow = None
            shp.shadow = None
            shp.hue = None
            shp.tail = None
            shp.fill_filter = None
            shp.line_filter = None
            return
        if m.get("base_fill") is not None or m.get("base_line") is not None:
            fill = m.get("base_fill")
            line = m.get("base_line")
            shp.fill = fill
            shp.line = line
            if m.get("base_line_width") is not None:
                shp.line_width = m["base_line_width"]
            return
        bc = m.get("base_color")
        if bc is not None:
            shp.set_color(bc)
    except Exception:
        pass


def _clear_stamps(shp) -> None:
    shp.glow = None
    shp.shadow = None
    shp.tail = None
    try:
        shp.hue = None
    except Exception:
        pass


def _assign_stamp(shp, look) -> None:
    name = type(look).__name__
    if name in ("Glow", "CheapGlow"):
        shp.glow = look
    elif name == "Shadow":
        shp.shadow = look
    elif name == "Tail":
        shp.tail = look
    elif name == "HueShift":
        shp.hue = look


def _apply_look(i: int) -> None:
    global _l_idx
    from scena.stamps import is_stamp_visual
    n = len(LOOKS)
    _l_idx = i % n
    name, label, factory = LOOKS[_l_idx]
    for m in movers:
        shp = m["shape"]
        shp.visual = None
        shp.fill_filter = None
        shp.line_filter = None
        _clear_stamps(shp)
        _restore_base(m)
        look = factory()
        if look is not None:
            if is_stamp_visual(look):
                _assign_stamp(shp, look)
            else:
                shp.visual = look
    hud.expect = f"mode={_mode}  look: {label}"
    hud.status = f"look={name}  n={len(movers)}  Q={canvas.fx_quality}"


def _maybe_prepare_fx() -> None:
    """Warm FrameFx for catalog looks that need path / SDF (Shape = no-op)."""
    if not PREPARE_FX:
        return
    for m in movers:
        m["shape"].prepare_fx(
            Halo, Aura, Rim, DashRing, GearShell, Laser, Ink, InkBleed,
            ElectricField, ElectricBolt, Metal, Flame, Swell, Aurora, Wave,
            Extrude, MultiBorder, OrganicOutline, Tracer,
        )


def _set_mode(mode: str) -> None:
    global _mode
    _mode = mode
    if mode == "sprites":
        _spawn_sprites()
    else:
        _spawn_shapes()
    _maybe_prepare_fx()
    _apply_look(_l_idx)


_set_mode(_mode)

_mouse_was_down = False


def update(dt):
    global _mouse_was_down
    t = clock.time

    for m in movers:
        shp = m["shape"]
        if not getattr(shp, "is_alive", True):
            continue
        nx = m["ox"] + math.sin(t * m["freq"] + m["phase"]) * m["amp"]
        ny = m["oy"] + math.cos(t * m["freq"] * 0.85 + m["phase"]) * m["amp"] * 0.7
        shp.move_to(nx, ny)
        if m["spin"]:
            shp.rotate_by(m["spin"] * dt)

    if keyp.once("1") or keyp.once("G"):
        _set_mode("shapes")
    if keyp.once("2") or keyp.once("T"):
        _set_mode("sprites")
    if keyp.once("Q"):
        _apply_look(_l_idx - 1)
    if keyp.once("W"):
        _apply_look(_l_idx + 1)
    if keyp.once("SPACE"):
        _apply_look(_look_names.index("none"))
    if keyp.once("E"):
        hud.status = f"quality={cycle_quality()}  look={LOOKS[_l_idx][0]}"

    if LOOKS[_l_idx][0] == "extrude":
        wm = ScenaFramework.get_instance().widget_manager
        if wm.get_widget_at(mouse.x, mouse.y) is None:
            set_extrude_focus(mouse.x, mouse.y)

    down = mouse.press(0)
    if down and not _mouse_was_down:
        best = None
        best_d = 1e18
        for m in movers:
            shp = m["shape"]
            if not getattr(shp, "is_alive", True):
                continue
            try:
                cx, cy = float(shp.center.x), float(shp.center.y)
            except Exception:
                continue
            d = (mouse.x - cx) ** 2 + (mouse.y - cy) ** 2
            if d < best_d:
                best_d = d
                best = shp
        if best is not None and best_d < 80 * 80:
            try:
                best.flash(0.2)
                best.pop(0.25)
            except Exception:
                pass
    _mouse_was_down = down


run()
