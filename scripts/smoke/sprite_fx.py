"""Sprite FX gallery — every look / filter legal on Sprite.

Overlay looks (Glow, CheapGlow, Shadow, Halo*, Tail, Beat, Rim), pixel FX
(HueShift, Recolor, Aura, EmissiveBloom), path shells (DashRing, GearShell, Laser, Ink,
InkBleed), body/outline Recipes (Metal, Flame, Swell, Aurora, Wave, Extrude,
MultiBorder, OrganicOutline, Tracer), ElectricField / ElectricBolt /
Shield styles, fill filters, and clickable transient hits.
Also a compact flip / class-defaults pose strip, plus an ``Svg`` cell that
alternates ``sonnenschirm.svg`` / inline markup.
Gallery art (A/S) is ``_media.HITBOX_SINGLES`` (``examples/media``), one grid
strip (``Sheet(..., cols=10)``, first frame) and ``sonnenschirm.svg``
(rasterized once via ``Svg``, then shared as a ``Sheet`` so gallery cells stay
``Sprite``). The alternating cell is a live ``Svg``.

Controls
--------
  SPACE   pause / resume motion
  E       cycle FX quality
  A / S   cycle gallery sprite art
  F / G   fighter attack / run clips
  H       toggle fighter flip_x
  C       show colliders
  1 / 2 / 3   meteor hitbox rect / ellipse / auto
  Slider  amount multiplier for gallery looks
  CheckBox  pass color / sample sprite art
  Click   flash + pop + knock + spark on that sprite

Usage
-----
    python scripts/smoke/sprite_fx.py
"""
from __future__ import annotations

import math
import os

import skia

from scena import *
import sys as _sys
_sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from _hud import SmokeHud, SAFE_BOTTOM
import _media

W, H = 1480, 960
init(width=W, height=H, window_scale=0.78, title="Smoke — sprite FX")
hud = SmokeHud(
    title="Sprite FX",
    expect="Looks + pixel FX; A/S = hitbox art + SVG; Svg file/markup alt; amount + pass-color; F/G fighter; click",
    keys="SPACE pause  ·  E quality  ·  A/S art  ·  F/G clips  ·  H flip  ·  C colliders  ·  1/2/3 hitbox  ·  click",
    status="",
)
canvas.fx_quality = "high"
canvas.batch_shared_filters = True

SkyGradient("night")
Stars(pan_response=0.0, density=0.75, amount=0.85, scroll=(0.0, -12.0))
canvas.effects.add(Vignette(amount=0.28))
canvas.effects.add(Bloom(intensity=0.35))

space = Sheet("../../examples/media/shooter/sheet.xml")

CELLS: list[dict] = []
GALLERY: list[Sprite] = []
FX: list[dict] = []  # {spr, apply(spr, mul)}
_paused = False

st.fx_amount = 1.0
st.pass_color = True

# A/S gallery art = the shared hitbox singles (scripts/smoke/_media.py), one
# grid strip (first frame) and the smoke SVG.
_SVG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sonnenschirm.svg")


def _collect_arts() -> list[dict]:
    """Hitbox PNGs plus ``sonnenschirm.svg`` for A/S gallery cycling."""
    arts: list[dict] = [
        {"file": _media.path(rel), "frame": 0, "height": 72, "label": rel}
        for rel in _media.HITBOX_SINGLES
    ]
    strip = "pixel_adv/Checkpoint (Flag Idle)(64x64).png"
    arts.append({"file": _media.path(strip), "frame": 0, "height": 72,
                 "label": strip, "cols": _media.STRIPS[strip]})
    arts.append({"svg": _SVG_FILE, "height": 72, "label": "sonnenschirm.svg"})
    return arts


_ARTS: list[dict] = _collect_arts()
_art_i = 0
_FILE_SHEETS: dict[tuple, Sheet] = {}


def _sheet_for_art(art: dict) -> Sheet:
    """Catalog for a hitbox PNG. Layout (``cols`` / ``rows``) lives on Sheet."""
    key = (art["file"], art.get("cols"), art.get("rows"))
    hit = _FILE_SHEETS.get(key)
    if hit is not None:
        return hit
    layout = {}
    if art.get("cols") is not None:
        layout["cols"] = art["cols"]
    if art.get("rows") is not None:
        layout["rows"] = art["rows"]
    sheet = Sheet(art["file"], **layout) if layout else Sheet(art["file"])
    _FILE_SHEETS[key] = sheet
    return sheet


def _sheet_for_svg(art: dict) -> Sheet:
    """Rasterize an SVG once and reuse that catalog for every gallery cell.

    ``.hue`` and other pixel looks accept ``Sprite`` only (not the ``Svg``
    subclass). ``Svg(...).sheet`` is the public raster; the alternating cell
    is the live ``Svg``.
    """
    key = ("svg", art["svg"], float(art.get("height", 72)))
    hit = _FILE_SHEETS.get(key)
    if hit is not None:
        return hit
    holder = Svg(art["svg"], height=float(art.get("height", 72)), layer=None)
    sheet = holder.sheet
    holder.destroy()
    _FILE_SHEETS[key] = sheet
    return sheet


def _spawn_art(art: dict | None, x: float, y: float, **kw) -> Sprite:
    """One gallery actor: still file, grid ``Sheet``, or SVG catalog."""
    if not art:
        return Sprite(center=(x, y), height=72, group="fx", **kw)
    if art.get("svg"):
        return Sprite(
            _sheet_for_svg(art),
            height=float(art.get("height", 72)),
            center=(x, y),
            group="fx",
            **kw,
        )
    size_kw: dict = {}
    if "height" in art:
        size_kw["height"] = float(art["height"])
    elif "width" in art:
        size_kw["width"] = float(art["width"])
    else:
        size_kw["size"] = float(art.get("size", 72))
    return Sprite(
        _sheet_for_art(art),
        frame=art.get("frame", 0),
        center=(x, y),
        group="fx",
        **size_kw,
        **kw,
    )


def _art_label() -> str:
    if not _ARTS:
        return "(no hitbox arts)"
    art = _ARTS[_art_i]
    return str(art.get("label") or art.get("file") or art.get("svg"))


def _sample_sprite_color(spr: Sprite) -> Color:
    """Mean opaque RGB of the current frame (atlas cell or whole file)."""
    from scena.style import _image_mean_opaque_color

    idx = int(spr.frame)
    img = spr.sheet._image_for_frame(idx)
    src = spr.sheet._src_rect(idx)
    irect = skia.IRect.MakeXYWH(
        int(src.left()), int(src.top()),
        max(1, int(src.width())), max(1, int(src.height())),
    )
    sub = img.makeSubset(irect)
    return _image_mean_opaque_color(sub if sub is not None else img)


def _tint(spr: Sprite, authored):
    """Authored color when checkbox on; else mean color of the sprite frame."""
    if bool(st.pass_color):
        return authored
    return _sample_sprite_color(spr)


def _apply_all_fx() -> None:
    mul = max(0.0, float(st.fx_amount))
    for entry in FX:
        spr = entry["spr"]
        if not spr.is_alive:
            continue
        entry["apply"](spr, mul)


def _retarget_gallery(old: Sprite, new: Sprite) -> None:
    for cell in CELLS:
        if cell["spr"] is old:
            cell["spr"] = new
            break
    for entry in FX:
        if entry["spr"] is old:
            entry["spr"] = new
            break
    for i, spr in enumerate(GALLERY):
        if spr is old:
            GALLERY[i] = new
            break


def _apply_gallery_art() -> None:
    """A/S: new actors from the public constructors (Sprite has no sheet swap)."""
    if not _ARTS:
        _hud()
        return
    art = _ARTS[_art_i]
    for old in list(GALLERY):
        if not old.is_alive:
            continue
        home = next(c for c in CELLS if c["spr"] is old)
        new = _spawn_art(art, home["ox"], home["oy"])
        new.clickable = True
        new.on_click = _hit
        _retarget_gallery(old, new)
        old.destroy()
    _apply_all_fx()
    _hud()


def _section(title: str, x: float, y: float) -> None:
    Text(
        text=title,
        top_left=(x, y + 21), font_size=18,
        color=Color(0.72, 0.8, 0.95, 1),
    )


def _hit(spr: Sprite) -> None:
    spr.flash(0.14)
    spr.pop(0.16, scale=1.18)
    spr.knock(distance=10, angle=35)
    spr.spark_burst()


def _cell(
    label: str,
    x: float,
    y: float,
    *,
    spr: Sprite,
    spin: float = 0.0,
    bob: float = 0.0,
    drift: float = 0.0,
    gallery: bool = False,
) -> Sprite:
    spr.clickable = True
    spr.on_click = _hit
    Text(
        text=label,
        top_left=(x - 70, y - 37), font_size=13,
        color=Color(0.62, 0.7, 0.82, 1),
    )
    CELLS.append({
        "spr": spr,
        "ox": x,
        "oy": y,
        "spin": spin,
        "bob": bob,
        "drift": drift,
        "phase": (x * 0.017 + y * 0.011) % math.tau,
    })
    if gallery:
        GALLERY.append(spr)
    return spr


def _gal(x, y, **kw) -> Sprite:
    """Shared gallery art (cycled with A/S from hitbox PNGs + camera SVG)."""
    art = _ARTS[_art_i] if _ARTS else None
    return _spawn_art(art, x, y, **kw)


def _clear_look(spr: Sprite) -> None:
    spr.visual = None
    spr.glow = None
    spr.shadow = None
    spr.hue = None
    spr.tail = None
    spr.fill_filter = None


def _fx(label: str, x: float, y: float, apply, **cell_kw) -> Sprite:
    """Gallery cell whose look rebuilds from amount / pass-color controls."""
    spr = _gal(x, y)
    _cell(label, x, y, spr=spr, gallery=True, **cell_kw)

    def _wrap(s, mul, _apply=apply):
        _clear_look(s)
        _apply(s, mul)

    FX.append({"spr": spr, "apply": _wrap})
    _wrap(spr, max(0.0, float(st.fx_amount)))
    return spr


# --- Param panel (view space; above FPS strip) -------------------------------
Slider(
    st.fx_amount,
    label="amount ×",
    show_value=True,
    min_value=0.0,
    max_value=2.5,
    top_left=(24, SAFE_BOTTOM + 56),
    width=260,
)
CheckBox(
    st.pass_color,
    label="pass color (off = sample sprite)",
    top_left=(300, SAFE_BOTTOM + 48),
)


@on_change(st.fx_amount)
def _on_amount(_v) -> None:
    _apply_all_fx()
    _hud()


@on_change(st.pass_color)
def _on_pass_color(_v) -> None:
    _apply_all_fx()
    _hud()


# --- Overlay looks -----------------------------------------------------------
_section("Overlay looks", 28, 900)

_fx("none", 90, 820, lambda spr, mul: _clear_look(spr), bob=6)

_fx(
    "Glow", 230, 820, bob=6,
    apply=lambda spr, mul: setattr(
        spr, "glow",
        Glow(_tint(spr, "skyblue"), radius=16, sigma=8, amount=1.2 * mul),
    ),
)

_fx(
    "Shadow", 370, 820, bob=5,
    apply=lambda spr, mul: setattr(
        spr, "shadow",
        Shadow(offset=10, sigma=6, color=_tint(spr, None) if not st.pass_color else None),
    ),
)

# Shared tint for Halo (hollow/fill/soft) vs Aura comparison.
_COMPARE_TINT = "cyan"

_fx(
    "Halo", 510, 820, spin=18,
    apply=lambda spr, mul: setattr(
        spr, "visual", Halo(_tint(spr, _COMPARE_TINT), amount=1.15 * mul),
    ),
)

_fx(
    "Halo fill", 650, 820, spin=-16,
    apply=lambda spr, mul: setattr(
        spr, "visual",
        Halo(_tint(spr, _COMPARE_TINT), style="fill", amount=1.1 * mul),
    ),
)

_fx(
    "Halo soft", 790, 820, bob=7,
    apply=lambda spr, mul: setattr(
        spr, "visual",
        Halo(_tint(spr, _COMPARE_TINT), style="soft", amount=1.2 * mul),
    ),
)

_fx(
    "Halo line", 930, 820, spin=22,
    apply=lambda spr, mul: setattr(
        spr, "visual",
        Halo(_tint(spr, "lime"), style="line", amount=1.25 * mul),
    ),
)

_fx(
    "Tail", 1070, 820, drift=70,
    apply=lambda spr, mul: setattr(
        spr, "tail",
        Tail(_tint(spr, None), angle=0, size=1.5, amount=1.15 * mul),
    ),
)

_fx(
    "Beat", 1210, 820,
    apply=lambda spr, mul: setattr(
        spr, "visual", Beat(amount=0.14 * mul, speed=1.4),
    ),
)

_fx(
    "Rim", 1350, 820, spin=10,
    apply=lambda spr, mul: setattr(
        spr, "visual",
        Rim(_tint(spr, "white"), amount=1.1 * mul, width=3.5),
    ),
)


def _apply_tail_glow(spr, mul):
    c = _tint(spr, "orange")
    spr.tail = Tail(c, angle=90, size=1.6, amount=1.2 * mul)
    if isinstance(c, Color):
        rgba = (float(c.rgb[0]), float(c.rgb[1]), float(c.rgb[2]), 1.0)
    else:
        rgba = (1.0, 0.55, 0.15, 1.0)
    spr.fill_filter = GlowFilter(
        radius=10, sigma=5, intensity=1.1 * mul, color=rgba,
    )


_fx("Tail + GlowFilter", 90, 680, _apply_tail_glow, bob=18)

_fx(
    "CheapGlow", 230, 680, bob=4, spin=-8,
    apply=lambda spr, mul: setattr(
        spr, "glow",
        CheapGlow(_tint(spr, "gold"), radius=12, sigma=6, amount=1.1 * mul),
    ),
)

def _apply_halo_glow(spr, mul):
    spr.visual = Halo(_tint(spr, _COMPARE_TINT), amount=1.15 * mul)
    spr.glow = Glow(_tint(spr, "skyblue"), radius=14, sigma=7, amount=1.1 * mul)


_fx("Halo + Glow", 370, 680, _apply_halo_glow, bob=6, spin=12)

# --- Pixel FX + path shells --------------------------------------------------
_section("Pixel FX + path shells (silhouette)", 28, 620)

_fx(
    "HueShift", 90, 540, bob=5,
    apply=lambda spr, mul: setattr(spr, "hue", HueShift(amount=0.33 * mul)),
)

_fx(
    "Recolor green→red", 230, 540, bob=5,
    apply=lambda spr, mul: setattr(
        spr, "visual", Recolor(key="lime", to="tomato", range=0.14),
    ),
)

_fx(
    "Aura", 370, 540, bob=6,
    apply=lambda spr, mul: setattr(
        spr, "visual",
        Aura(_tint(spr, _COMPARE_TINT), amount=1.1 * mul),
    ),
)

_fx(
    "EmissiveBloom", 510, 540, bob=10,
    apply=lambda spr, mul: setattr(
        spr, "visual", EmissiveBloom(intensity=1.5 * mul, sigma=11),
    ),
)

_fx(
    "DashRing", 650, 540, spin=14,
    apply=lambda spr, mul: setattr(
        spr, "visual",
        DashRing(_tint(spr, "cyan"), speed=1.1, width=2.2 * mul),
    ),
)

_fx(
    "GearShell", 790, 540, spin=-12,
    apply=lambda spr, mul: setattr(
        spr, "visual",
        GearShell(_tint(spr, "orchid"), speed=1.2, amount=1.05 * mul),
    ),
)

_fx(
    "Laser", 930, 540, bob=6,
    apply=lambda spr, mul: setattr(
        spr, "visual",
        Laser(_tint(spr, "tomato"), amount=1.15 * mul),
    ),
)

_fx(
    "Ink", 1070, 540, spin=8,
    apply=lambda spr, mul: setattr(
        spr, "visual",
        Ink(_tint(spr, "black"), amount=1.6 * mul, speed=0.7),
    ),
)

_fx(
    "InkBleed", 1210, 540, bob=5,
    apply=lambda spr, mul: setattr(
        spr, "visual",
        InkBleed(_tint(spr, "navy"), amount=1.1 * mul),
    ),
)

# --- Body / outline Recipes (silhouette) ------------------------------------
_section("Body / outline Recipes (path)", 28, 480)

_fx(
    "Metal", 90, 400, spin=10,
    apply=lambda spr, mul: setattr(
        spr, "visual", Metal(_tint(spr, "gray"), amount=1.0 * mul, speed=1.0),
    ),
)

_fx(
    "Flame", 230, 400, bob=8,
    apply=lambda spr, mul: setattr(
        spr, "visual", Flame(amount=1.1 * mul, speed=1.2),
    ),
)

_fx(
    "Swell", 370, 400, bob=6,
    apply=lambda spr, mul: setattr(
        spr, "visual", Swell(amount=1.0 * mul, speed=1.0),
    ),
)

_fx(
    "Aurora", 510, 400, spin=-8,
    apply=lambda spr, mul: setattr(
        spr, "visual", Aurora(_tint(spr, "lime"), amount=1.05 * mul, speed=0.9),
    ),
)

_fx(
    "Wave", 650, 400, bob=7,
    apply=lambda spr, mul: setattr(
        spr, "visual", Wave(_tint(spr, "deepskyblue"), amount=1.05 * mul, speed=1.0),
    ),
)

_fx(
    "Extrude", 790, 400, spin=6,
    apply=lambda spr, mul: setattr(
        spr, "visual",
        Extrude(_tint(spr, "steelblue"), depth=40, layers=5, angle=225),
    ),
)

_fx(
    "MultiBorder", 930, 400, bob=5,
    apply=lambda spr, mul: setattr(
        spr, "visual",
        MultiBorder(_tint(spr, "cyan"), layers=3, spread=0.35 * mul),
    ),
)

_fx(
    "OrganicOutline", 1070, 400, spin=12,
    apply=lambda spr, mul: setattr(
        spr, "visual",
        OrganicOutline(_tint(spr, "white"), amount=2.2 * mul, speed=1.0),
    ),
)

_fx(
    "Tracer", 1210, 400, spin=-14,
    apply=lambda spr, mul: setattr(
        spr, "visual",
        Tracer(_tint(spr, "gold"), speed=1.2, gap=10, width=2.4 * mul),
    ),
)

# --- Electric / Shield -------------------------------------------------------
_section("Electric* / Shield (Electric=silhouette; Shield=envelope ×shield_scale)", 28, 340)

_fx(
    "ElectricField", 90, 280, spin=14,
    apply=lambda spr, mul: setattr(
        spr, "visual",
        ElectricField(_tint(spr, None), amount=6 * mul, speed=16 / 14.0),
    ),
)

_fx(
    "ElectricBolt", 230, 280, spin=-12,
    apply=lambda spr, mul: setattr(
        spr, "visual",
        ElectricBolt(_tint(spr, "gold"), amount=6 * mul, speed=1.0),
    ),
)

_fx(
    "Shield bubble", 370, 280, bob=5,
    apply=lambda spr, mul: setattr(
        spr, "visual",
        Shield(_tint(spr, None), style="bubble", amount=1.05 * mul),
    ),
)

_fx(
    "Shield nebula", 510, 280, bob=5,
    apply=lambda spr, mul: setattr(
        spr, "visual",
        Shield(_tint(spr, None), style="nebula", amount=1.05 * mul),
    ),
)

_fx(
    "nebula ember", 650, 280, bob=5,
    apply=lambda spr, mul: setattr(
        spr, "visual",
        Shield(_tint(spr, None), style="ember", amount=1.05 * mul),
    ),
)

_fx(
    "nebula void", 790, 280, bob=5,
    apply=lambda spr, mul: setattr(
        spr, "visual",
        Shield(_tint(spr, None), style="void", amount=1.05 * mul),
    ),
)

_fx(
    "Shield molten", 930, 280, spin=10,
    apply=lambda spr, mul: setattr(
        spr, "visual",
        Shield(_tint(spr, None), style="molten", amount=1.1 * mul, speed=1.15),
    ),
)

_fx(
    "Shield bands", 1070, 280, spin=-8,
    apply=lambda spr, mul: setattr(
        spr, "visual",
        Shield(_tint(spr, "teal"), style="bands", amount=1.05 * mul, speed=0.4),
    ),
)

_fx(
    "Shield vortex", 1210, 280, spin=20,
    apply=lambda spr, mul: setattr(
        spr, "visual",
        Shield(_tint(spr, "orchid"), style="vortex", amount=1.1 * mul),
    ),
)

_fx(
    "Shield plasma", 1350, 280, bob=6,
    apply=lambda spr, mul: setattr(
        spr, "visual",
        Shield(_tint(spr, None), style="plasma", amount=1.1 * mul),
    ),
)

_fx(
    "cracks magma", 90, 160, spin=8,
    apply=lambda spr, mul: setattr(
        spr, "visual",
        Shield(_tint(spr, None), style="cracks", amount=1.1 * mul),
    ),
)

_fx(
    "cracks frost", 230, 160, spin=-8,
    apply=lambda spr, mul: setattr(
        spr, "visual",
        Shield(_tint(spr, None), style="frost", amount=1.1 * mul),
    ),
)

# --- Filters -----------------------------------------------------------------
_section("Filters", 400, 200)


def _apply_glow_filter(spr, mul):
    c = _tint(spr, Color(0.35, 0.8, 1.0, 1.0))
    if isinstance(c, Color):
        rgba = (float(c.rgb[0]), float(c.rgb[1]), float(c.rgb[2]), 1.0)
    else:
        rgba = (0.35, 0.8, 1.0, 1.0)
    spr.visual = None
    spr.fill_filter = GlowFilter(
        radius=16, sigma=9, intensity=1.35 * mul, color=rgba,
    )


_fx("GlowFilter", 480, 160, _apply_glow_filter, bob=5)


def _apply_blur(spr, mul):
    spr.visual = None
    spr.fill_filter = Blur(sigma=max(0.5, 2.8 * mul))


_fx("Blur", 620, 160, _apply_blur, bob=5)


def _apply_drop_shadow(spr, mul):
    c = _tint(spr, Color(0.0, 0.0, 0.0, 0.7))
    if isinstance(c, Color):
        rgba = (
            float(c.rgb[0]), float(c.rgb[1]), float(c.rgb[2]),
            float(c.rgb[3]) if len(c.rgb) > 3 else 0.7,
        )
    else:
        rgba = (0.0, 0.0, 0.0, 0.7)
    spr.visual = None
    spr.fill_filter = DropShadow(offset=12, sigma=6, color=rgba)


_fx("DropShadow", 760, 160, _apply_drop_shadow, bob=7)

# --- Atlas / clips / hitbox strip (kept separate from A/S gallery art) -------
Text(
    text='Atlas clips: F/G fighter  ·  C colliders  ·  1/2/3 meteor hitbox  ·  A/S gallery art',
    top_left=(24, 137), font_size=14, color=Color(0.7, 0.78, 0.9, 1),
)
fighter_sheet = Sheet("../../examples/media/pixel_adv/Start (Moving) (64x64).png", cols=17, fps=12, name="run")
fighter_sheet.strip("attack", "../../examples/media/pixel_adv/Checkpoint (Flag Idle)(64x64).png", cols=10, fps=8)
fighter = Sprite(
    fighter_sheet,
    height=72, center=(180, 80), group="fx",
)
fighter.play("run")
_cell("fighter strip", 180, 80, spr=fighter, drift=30)

meteor = Sprite(
    space, frame="meteorBrown_big1.png", size=56, center=(360, 80),
    group="fx", hitbox_shape="auto",
)
meteor.collidable = True
_cell("meteor hitbox", 360, 80, spr=meteor, spin=25)
st.meteor_mode = "auto"

# --- Flip / class defaults (kept separate) ----------------------------------
_section("Flip / class defaults", 520, 160)


def _plane(x, y, **kw) -> Sprite:
    """Asymmetric art + auto hitbox so flip of the collider is visible (C)."""
    spr = Sprite(
        "../../examples/media/plane/Fly1.png", height=56, center=(x, y), group="fx",
        hitbox_shape="auto", **kw,
    )
    spr.collidable = True
    return spr


_cell("normal", 560, 80, spr=_plane(560, 80), bob=4)
_cell("flip_x", 700, 80, spr=_plane(700, 80, flip_x=True), bob=4)
_cell("flip_y", 840, 80, spr=_plane(840, 80, flip_y=True), bob=4)
_cell("both", 980, 80, spr=_plane(980, 80, flip_x=True, flip_y=True), bob=4)
_cell("flip_x + spin", 1120, 80, spr=_plane(1120, 80, flip_x=True), spin=40)

st.show_col = True
collision.show_colliders(True)


class DemoShip(Sprite, source=space, frame="playerShip1_blue.png", height=52):
    pass


_cell(
    "DemoShip class", 1260, 80,
    spr=DemoShip(center=(1260, 80), group="fx"), bob=5,
)

# A file and inline markup (Svg takes either): the swap reloads the body.
_ALT_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
    '<circle cx="50" cy="50" r="44" fill="orange" stroke="black" stroke-width="6"/>'
    '<path d="M50 14 L60 50 L50 86 L40 50 Z" fill="crimson"/></svg>'
)
_SVG_ALTERNATES = ("sonnenschirm.svg", _ALT_SVG)
svg_alt = Svg(
    _SVG_ALTERNATES[0], height=56, center=(1400, 80), group="fx", hitbox_shape="auto",
)
svg_alt.collidable = True
_cell("Svg alt", 1400, 80, spr=svg_alt, bob=5)
st.svg_alt_i = 0
st.svg_alt_t = 0.0


def _hud() -> None:
    q = canvas.fx_quality
    qn = q.value if q is not None else "?"
    mode = "pass color" if bool(st.pass_color) else "sample sprite"
    alt = ("sonnenschirm.svg", "inline markup")[int(st.svg_alt_i) % len(_SVG_ALTERNATES)]
    hud.status = (
        f"{len(CELLS)} cells  ·  art={_art_i + 1}/{len(_ARTS)} {_art_label()}  ·  "
        f"svg={alt}  ·  amount×={float(st.fx_amount):.2f}  ·  {mode}  ·  Q={qn}  ·  "
        f"fighter.flip_x={fighter.flip_x}"
    )


_hud()


def update(dt: float) -> None:
    if _paused:
        return
    t = clock.time
    st.svg_alt_t = float(st.svg_alt_t) + dt
    if float(st.svg_alt_t) >= 1.5:
        st.svg_alt_t = 0.0
        st.svg_alt_i = (int(st.svg_alt_i) + 1) % len(_SVG_ALTERNATES)
        svg_alt.svg = _SVG_ALTERNATES[int(st.svg_alt_i)]
        _hud()
    for c in CELLS:
        spr = c["spr"]
        if not spr.is_alive:
            continue
        ph = c["phase"]
        x = c["ox"]
        y = c["oy"]
        if c["bob"]:
            y = c["oy"] + math.sin(t * 1.7 + ph) * c["bob"]
        if c["drift"]:
            x = c["ox"] + math.sin(t * 0.9 + ph) * c["drift"] * 0.35
        spr.center = (x, y)
        if c["spin"]:
            spr.rotate_by(c["spin"] * dt)


def on_key_down(key: str) -> None:
    global _paused, _art_i
    if key == "SPACE":
        _paused = not _paused
        clock.paused = _paused
    elif key in ("E", "e"):
        from _hud import cycle_quality
        cycle_quality()
        _hud()
    elif key in ("A", "a"):
        if _ARTS:
            _art_i = (_art_i - 1) % len(_ARTS)
            _apply_gallery_art()
    elif key in ("S", "s"):
        if _ARTS:
            _art_i = (_art_i + 1) % len(_ARTS)
            _apply_gallery_art()
    elif key == "F":
        fighter.play("attack", loops=1, next="run")
    elif key == "G":
        fighter.play("run")
    elif key in ("H", "h"):
        fighter.flip_x = not fighter.flip_x
    elif key == "C":
        st.show_col = not bool(getattr(st, "show_col", False))
        collision.show_colliders(bool(st.show_col))
    elif key == "1":
        meteor.hitbox.shape = "rect"
        st.meteor_mode = "rect"
    elif key == "2":
        meteor.hitbox.shape = "ellipse"
        st.meteor_mode = "ellipse"
    elif key == "3":
        meteor.hitbox.shape = "auto"
        st.meteor_mode = "auto"


run()
