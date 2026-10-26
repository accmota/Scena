"""
shape_fx.py — smoke: shape looks, fill/line filters, canvas post FX, and cover.

Controls
  A / S        cycle canvas-wide post effects (incl. cover fade / wipe / iris)
  Q / W        cycle shape visuals
  Space        both none (baseline); also drops a held cover
  Click        hit feedback (ripple / wave / explosion / burst / fireworks / zap /
               hit_at / debris_at / …); hit_at with "stream" on: hold to fire
               cover modes: fade_out / fade_in toggle (iris center = click)
  E            cycle FX quality
  Ctrl+Shift+3 quality profiles

Usage
-----
    python scripts/smoke/shape_fx.py
    python scripts/smoke/shape_fx.py --visual rim --canvas none
    python scripts/smoke/shape_fx.py --canvas cover_wipe
"""
from __future__ import annotations

import argparse
import math
import os
import random
import time
import sys

from scena import *
from scena.orchestration import ScenaFramework


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--start", default="none", help="legacy: initial canvas mode")
parser.add_argument("--canvas", default=None, help="initial canvas mode name")
parser.add_argument(
    "--visual", default="none", dest="visual",
    help="initial shape visual mode",
)
parser.add_argument(
    "--look", dest="visual",
    help="alias of --visual (deprecated)",
)
parser.add_argument(
    "--quality", default="high",
    choices=("low", "medium", "high", "max"),
)
parser.add_argument("--n", type=int, default=48, help="shape count")
args, _ = parser.parse_known_args()
# Live smoke: never bench (historical --bench lives under scripts/bench/historical/).
args.bench = False
args.duration = 2.0
args.warmup = 0.4

W, H = 1200, 800
BG2 = "../../examples/media/images/bg3.jpg"
TEX2 = "../../examples/media/k-textures/floor_wood_planks.png"
TEX_SPRITE = Texture(TEX2, fit="cover")
TEX_TILE = Texture(TEX2, fit="tile", tile_size=40)

init(width=W, height=H, window_scale=0.75, title="Smoke — shape FX")
collision.floor = True   # gravity: bodies stand on floors (ramps, lifts, seams)
canvas.fx_quality = args.quality
canvas.batch_shared_filters = True
Wallpaper(BG2, fit="cover")
# Optional dust extras behind looks (commented — enable to preview):
#Stars(density=0.55, twinkle=0.25, amount=0.75, alpha=0.85, pan_response=0.0)
#Stardust(alpha=0.32, pan_response=0.0)
#Chromadust(alpha=0.32, pan_response=0.0)
#Nebuladust(alpha=0.32, pan_response=0.0)
# Shared 2½D vanishing point for Extrude (top-center of design space).
set_extrude_focus(W * 0.5, H * 0.06)

import sys as _sys
_sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from _hud import SmokeHud
hud = SmokeHud(
    title="Shape FX",
    expect="Cycle canvas post (A/S) and shape looks (Q/W) — SPACE clears both",
    keys="A/S canvas  ·  Q/W visual  ·  SPACE none  ·  corner_radius slider  ·  click hit / cover  ·  E quality",
    status="",
)


# --------------------------------------------------------------------------- 
# Scene: diverse movers (geometry + alpha + some pure Lines)
# ---------------------------------------------------------------------------
COLORS = (
    "cyan", "magenta", "gold", "lime", "orange",
    "dodger blue", "orchid", "white", "tomato", "green",
)

# Colorful fill / stroke ramps: presets + custom multi-stops, varied gradient kinds.
_FILL_GRAD_RECIPES = (
    (("plasma",), "radial", 0.0),
    (("rainbow",), "sweep", 40.0),
    (("sunset",), "linear", 90.0),
    (("vrds",), "linear", 35.0),
    (("coolwarm",), "linear", 0.0),
    (("ocean",), "radial", 0.0),
    (("ember",), "radial", 0.0),
    (("ice",), "linear", 120.0),
    (("toxic",), "linear", 55.0),
    (("magenta", "cyan", "gold"), "linear", 25.0),
    (("lime", "dodger blue", "orchid"), "radial", 0.0),
    (("tomato", "gold", "orange"), "linear", 70.0),
    (("navy", "cyan", "white"), "radial", 0.0),
    (("crimson", "magenta", "violet"), "sweep", 15.0),
    (("green", "lime", "gold"), "linear", 140.0),
    (("heat",), "radial", 0.0),
    (("forest",), "linear", 80.0),
    (("underwater",), "radial", 0.0),
    (("cyan", "dodger blue", "navy"), "linear", 45.0),
    (("gold", "orange", "crimson"), "radial", 0.0),
)
_LINE_GRAD_RECIPES = (
    (("magenta", "cyan"), "linear", 0.0),
    (("gold", "orange", "tomato"), "linear", 90.0),
    (("lime", "dodger blue"), "linear", 45.0),
    (("rainbow",), "linear", 30.0),
    (("plasma",), "linear", 120.0),
    (("white", "cyan", "magenta"), "linear", 60.0),
)


def _make_grad(colors, gtype, size, angle=0.0):
    return Gradient(*colors, type=gtype, size=size, angle=angle)


movers = []
random.seed(42)
# ~1/4 pure Lines for stroke/look previews; rest filled shapes
_line_count = max(4, args.n // 4)
_filled_count = max(0, args.n - _line_count)
_n_grad_fills = min(20, _filled_count)
_grad_fill_ids = set(range(_n_grad_fills))  # first ~20 filled shapes
_n_tex_sprite = min(4, _filled_count)
_n_tex_tile = min(4, max(0, _filled_count - _n_tex_sprite))

for i in range(_filled_count):
    kind = i % 6
    x = random.uniform(80, W - 80)
    y = random.uniform(80, H - 80)
    size = random.uniform(12, 55)
    ang = random.uniform(0, 360)
    if kind == 0:
        shp = Circle(center=(x, y), radius=size * 0.5)
    elif kind == 1:
        shp = Square(center=(x, y), length=size, angle=ang)
    elif kind == 2:
        shp = Rect(center=(x, y), width=size * 1.4, height=size * 0.7, angle=ang)
    elif kind == 3:
        shp = Triangle(center=(x, y), radius=size * 0.55, angle=ang)
    elif kind == 4:
        shp = RegularPolygon(n=5 + (i % 3), center=(x, y), radius=size * 0.5, angle=ang)
    else:
        shp = Ellipse(center=(x, y), width=size * 1.2, height=size * 0.55, angle=ang)

    color = COLORS[i % len(COLORS)]
    shp.set_color(color); shp.line_width = 1.5
    shp.line_width = random.uniform(1.5, 2.5)
    textured = False
    if i < _n_tex_sprite:
        shp.fill = TEX_SPRITE
        textured = True
    elif i < _n_tex_sprite + _n_tex_tile:
        shp.fill = TEX_TILE
        textured = True
    elif i in _grad_fill_ids:
        colors, gtype, gangle = _FILL_GRAD_RECIPES[i % len(_FILL_GRAD_RECIPES)]
        shp.fill = _make_grad(colors, gtype, size=max(18.0, size * 0.85), angle=gangle + ang * 0.25)
    if not textured:
        if i % 2 == 0:
            alpha = 1.0
        else:
            alpha = (0.15, 0.30, 0.45, 0.55, 0.70, 0.85)[i % 6]
            shp.set_alpha(alpha)

    movers.append({
        "shape": shp,
        "ox": x, "oy": y,
        "base_color": color,
        "base_fill": shp.fill,
        "base_line": shp.line,
        "base_line_width": shp.line_width,
        "amp": 20 + (i % 5) * 12,
        "freq": 0.4 + (i % 7) * 0.12,
        "phase": i * 0.37,
        "spin": (i % 9 - 4) * 25.0,
    })

for i in range(_line_count):
    cx = random.uniform(100, W - 100)
    cy = random.uniform(100, H - 100)
    length = random.uniform(40, 120)
    ang = random.uniform(0, 360)
    rad = math.radians(ang)
    hx, hy = math.cos(rad) * length * 0.5, math.sin(rad) * length * 0.5
    color = COLORS[(i + 3) % len(COLORS)]
    shp = Line(p1=(cx - hx, cy - hy), p2=(cx + hx, cy + hy))
    shp.set_color(color)  # Line: stroke primary; fill cleared
    shp.line_width = random.uniform(1.5, 2.5)
    if i % 2 == 0:  # half of the Lines get gradient strokes
        colors, gtype, gangle = _LINE_GRAD_RECIPES[i % len(_LINE_GRAD_RECIPES)]
        shp.set_color(_make_grad(colors, gtype, size=max(24.0, length * 0.55), angle=gangle + ang))
    if i % 3 == 0:
        shp.set_alpha((0.45, 0.65, 0.85)[i % 3])
    movers.append({
        "shape": shp,
        "ox": cx, "oy": cy,
        "base_color": color,
        "base_fill": None,
        "base_line": shp.line,
        "base_line_width": shp.line_width,
        "amp": 16 + (i % 4) * 10,
        "freq": 0.35 + (i % 5) * 0.1,
        "phase": i * 0.51,
        "spin": (i % 7 - 3) * 18.0,
    })

canvas.layers["top"].post_fx = False

# Param panel under HUD band (clear of bottom FPS).
# Pitch tracks ui.scale: widget height + stack gap (same proportion as auto-stack).
N_SLIDERS = 6
N_CHECKS = 4
PANEL_X = 16
PANEL_TOP = H - 130
_theme = ScenaFramework.get_instance().widget_manager.widget_theme
_theme._ensure()
ROW = max(_theme.row_height, 2 * _theme.slider_handle_radius) + _theme.stack_gap

_panel_sliders: list[Slider] = []
_panel_checks: list[CheckBox] = []
for i in range(N_SLIDERS):
    s = Slider(
        label="—",
        top_left=(PANEL_X, PANEL_TOP - i * ROW + 28),
        #width=290,
        min_value=0.0,
        max_value=100.0,
        initial=50.0,
        show_value=True,
    )
    s.visible = False
    _panel_sliders.append(s)
for i in range(N_CHECKS):
    c = CheckBox(
        label="—",
        top_left=(PANEL_X, PANEL_TOP - (N_SLIDERS + i) * ROW + 20),
        initial=False,
    )
    c.visible = False
    _panel_checks.append(c)

# Always-on corner_radius (not in the Q/W FX panel pool — that pool is rebound).
st.corner_radius = 0.0
Slider(
    st["corner_radius"],
    label="corner_radius",
    show_value=True,
    min_value=0.0,
    max_value=40.0,
    top_left=(PANEL_X + 320, PANEL_TOP + 28),
    width=280,
)

# Live effect handle + optional shape-filter rebuild callable.
# `_live` is whichever object the current panel is bound to (look or post FX).
# `_canvas_live` is always the canvas post effect, so cycling looks cannot
# steal it and leftover sliders cannot setattr onto Prism / Bloom / …
_live = None
_canvas_live = None
_rebuild = None  # callable(**params) -> FilterEffect | None
_param_map: list[tuple] = []  # (widget, key, kind) kind: float|int|bool
# True while the panel shows the shape visual's sliders. Only then does
# `_rebuild` read the panel; a canvas panel never feeds the look.
_panel_is_look = False
_last_shape_key = None
_pyro_labels = []
_pyro_acc = 0.0
_bench_auto_acc = 0.0
_PYRO_ZONES = (
    # (u, v, kind) — u,v in 0..1 design space
    (0.35, 0.55, "explosion"),
    (0.65, 0.55, "burst"),
)
_FW_SWATCHES = ("gold", "cyan", "magenta", "lime", "white", "tomato")
_ZAP_SWATCHES = ("cyan", "gold", "magenta", "lime", "white", "tomato")
_ZAP_STYLES = ("spark", "fork", "corona")
# Swatch 0 is None: the verb's own default (warm white hit / stone debris).
_HIT_SWATCHES = (None, "cyan", "gold", "magenta", "lime", "tomato")
_DEBRIS_SWATCHES = (None, "peru", "dim gray", "olive", "white", "firebrick")
_stream_acc = 0.0


def _fire_hit(p: dict, x: float, y: float) -> None:
    """``canvas.hit_at`` from the hit_at panel (``aim`` off → all around;
    ``disc`` on → ``style="disc"``, which takes no angle / count)."""
    n_sw = len(_HIT_SWATCHES)
    c0 = max(0, min(n_sw - 1, int(p.get("color", 0))))
    common = dict(
        color=_HIT_SWATCHES[c0],
        radius=float(p.get("radius", 16.0)),
        amount=float(p.get("amount", 1.0)),
    )
    if p.get("disc", False):
        canvas.hit_at(x, y, style="disc", **common)
        return
    canvas.hit_at(
        x, y,
        angle=float(p.get("angle", 90.0)) if p.get("aim", True) else None,
        count=int(p.get("count", 8)),
        **common,
    )


def _fire_debris(p: dict, x: float, y: float) -> None:
    """``canvas.debris_at`` from the debris panel, optionally chained."""
    n_sw = len(_DEBRIS_SWATCHES)
    c0 = max(0, min(n_sw - 1, int(p.get("color", 0))))
    radius = float(p.get("radius", 40.0))
    canvas.debris_at(
        x, y,
        color=_DEBRIS_SWATCHES[c0],
        radius=radius,
        amount=float(p.get("amount", 1.0)),
        count=int(p.get("count", 14)),
        fall=float(p.get("fall", 0.0)),
        dust=bool(p.get("dust", True)),
    )
    if p.get("with_hit", False):
        canvas.hit_at(x, y, radius=radius * 0.6)
    if p.get("with_burst", False):
        canvas.burst_at(x, y, radius=radius)


def _fire_pyro_grid(amount: float = 1.0, rings: bool = False):
    """Fire explosion + burst demos."""
    canvas.effects._hit_feedback()
    for u, v, kind in _PYRO_ZONES:
        x, y = W * u, H * v
        if kind == "explosion":
            canvas.explosion_at(
                x, y, amount=amount, shock=False, flash=False, shake=False,
                rings=rings,
            )
        else:
            canvas.burst_at(x, y, radius=48.0, amount=amount, rings=rings)


def _fire_pyro_zone(x: float, y: float, amount: float = 1.0, rings: bool = False):
    """Pick nearest zone and fire that pyro type."""
    best = None
    best_d = 1e18
    for u, v, kind in _PYRO_ZONES:
        zx, zy = W * u, H * v
        d = (x - zx) ** 2 + (y - zy) ** 2
        if d < best_d:
            best_d = d
            best = (zx, zy, kind)
    if best is None:
        return
    zx, zy, kind = best
    if kind == "explosion":
        canvas.explosion_at(
            zx, zy, amount=amount, shock=False, flash=False, shake=False,
            rings=rings,
        )
    else:
        canvas.burst_at(zx, zy, radius=48.0, amount=amount, rings=rings)


def _hide_pyro_labels():
    for lb in _pyro_labels:
        try:
            lb.visible = False
        except Exception:
            pass


def _show_pyro_labels():
    for lb in _pyro_labels:
        try:
            lb.visible = True
        except Exception:
            pass


def _setup_slider(s: Slider, label: str, lo: float, hi: float, val: float, only_int: bool = False):
    s.min_value = float(lo)
    s.max_value = float(hi)
    s.only_int = only_int
    s.label = label
    label_space = max(s._theme.default_font.measureText(str(label)) + 10, 72)
    s._label_space = label_space
    s._slider_length = (
        s.width
        - s._value_space
        - label_space
        - (2 * s._internal_margin)
        - (2 * s._handle_radius)
    )
    s._slider_x = s._x1 + s._handle_radius + label_space
    s.data.value = float(int(round(val)) if only_int else val)
    s.visible = True


def _setup_check(c: CheckBox, label: str, val: bool):
    c.label = label
    c.data.value = bool(val)
    c._text_width = c._theme.default_font.measureText(c.label) if c.label else 0
    c._total_width = c.size + 5 + c._text_width
    c._x2 = c._x1 + c._total_width
    c.visible = True


def _configure_panel(specs: list):
    """Show/hide and rebind the shared slider/checkbox pool for this mode."""
    global _param_map, _last_shape_key
    _param_map = []
    _last_shape_key = None
    si = ci = 0
    for spec in specs:
        if len(spec) == 3 and spec[1] == "bool":
            name, _, default = spec
            if ci >= N_CHECKS:
                break
            c = _panel_checks[ci]
            ci += 1
            _setup_check(c, name, bool(default))
            _param_map.append((c, name, "bool"))
        else:
            name, lo, hi, default, *rest = spec
            only_int = bool(rest[0]) if rest else False
            if si >= N_SLIDERS:
                break
            s = _panel_sliders[si]
            si += 1
            _setup_slider(s, name, lo, hi, default, only_int)
            _param_map.append((s, name, "int" if only_int else "float"))
    for s in _panel_sliders[si:]:
        s.visible = False
    for c in _panel_checks[ci:]:
        c.visible = False


def _read_params() -> dict:
    out = {}
    for w, key, kind in _param_map:
        if kind == "bool":
            out[key] = bool(w.value)
        elif kind == "int":
            out[key] = int(round(float(w.value)))
        else:
            out[key] = float(w.value)
    return out


def _restore_base_paint(m, *, restore_width: bool = True):
    """Restore host fill/line (and optionally width) after visuals/filters."""
    shp = m["shape"]
    try:
        if restore_width:
            bw = m.get("base_line_width")
            if bw is not None:
                shp.line_width = float(bw)
        if "base_fill" in m or "base_line" in m:
            fill = m.get("base_fill")
            line = m.get("base_line")
            if fill is None:
                shp.fill = None
            else:
                shp.fill = fill
            if line is None:
                shp.line = None
            else:
                shp.line = line
            return
        bc = m.get("base_color")
        if bc is not None:
            shp.set_color(bc)
    except Exception:
        pass


# Costumes that install their own standard outline — do not wipe width after apply.
_OWN_OUTLINE_VISUALS = frozenset({
    "GearShell", "_OrbHalo", "DashRing", "Shield",
    "Swell", "Flame", "Metal", "Bolt", "Gel", "Wave",
    "Aurora", "InsetRim", "ElectricField",
})


def _visual_owns_outline(look) -> bool:
    return type(look).__name__ in _OWN_OUTLINE_VISUALS


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
    else:
        raise TypeError(f"not a stamp look: {name}")


def _clear_shape_fx():
    for m in movers:
        # visual=None resets package filters; clear filters before host color restore.
        m["shape"].visual = None
        m["shape"].fill_filter = None
        m["shape"].line_filter = None
        _clear_stamps(m["shape"])
        try:
            m["shape"].clear_transients()
        except Exception:
            pass
        _restore_base_paint(m)
    _hide_water_pool()


def _clear_cover():
    from scena.cover import reset_cover
    reset_cover()


def _is_cover_mode(name: str) -> bool:
    return str(name).startswith("cover")


# Canvas modes that read their own sliders when the user clicks.
_CLICK_PANEL_MODES = frozenset({
    "hit", "wave", "explosion", "burst", "pyro", "fireworks",
    "zap_spark", "zap_fork", "zap_corona", "hit_at", "debris", "bubbles",
})


def _click_owns_panel(name: str) -> bool:
    """A click mode keeps its own panel even while a shape visual runs:
    with the visual's sliders shown, the click read the visual's
    ``radius`` / ``amount`` and the click's own knobs were unreachable."""
    return name in _CLICK_PANEL_MODES or _is_cover_mode(name)


def _clear_post():
    """Drop canvas post FX only — never the active shape-look rebuild."""
    global _live, _canvas_live
    canvas.effects.clear()
    _canvas_live = None
    if _rebuild is None:
        _live = None


def _is_recipe_visual(look) -> bool:
    """True only for multipass :class:`~scena.recipes.Recipe` costumes.

    Do **not** use ``look.is_multipass``: Glow/_OrbHalo toggle that for LOD,
    and post-assign ``set_color`` would clobber their ProceduralFill packages.
    """
    try:
        from scena.recipes import Recipe
        return isinstance(look, Recipe)
    except Exception:
        return False


def _apply_shared_fill(fx):
    """ImageFilter on fill. Clear visual *before* setting filter (reset clears filters)."""
    for m in movers:
        m["shape"].visual = None
        m["shape"].line_filter = None
        _clear_stamps(m["shape"])
        m["shape"].fill_filter = fx
        _restore_base_paint(m)


def _apply_shared_look(look):
    """Apply visual/stamp to all movers; restore host fill/line (incl. gradients).

    Host-preserving looks (Glow, Shadow, Tail, Beat, MultiBorder, …) must not
    be preceded by ``set_color(base_color)`` — that wipes gradient materials.
    After a *multipass* Recipe assign, restore again so a shared recipe with
    ``color=`` seed does not flatten every mover to one solid. Compiled GlowRim
    highs (ElectricField, Bolt) rewrite fill/line/filters — restoring
    host paint after ``apply`` wipes the halo package. Costumes that own a
    standard outline keep the width installed by ``apply``.
    """
    from scena.stamps import is_stamp_visual
    stamp = is_stamp_visual(look)
    owns_outline = False if stamp else _visual_owns_outline(look)
    restore_host = (
        (not stamp)
        and _is_recipe_visual(look)
        and bool(getattr(look, "_is_multipass", True))
    )
    for m in movers:
        shp = m["shape"]
        shp.fill_filter = None
        shp.line_filter = None
        _clear_stamps(shp)
        _restore_base_paint(m)
        if stamp:
            shp.visual = None
            _assign_stamp(shp, look)
        else:
            shp.visual = look
            if restore_host:
                _restore_base_paint(m, restore_width=not owns_outline)


def _apply_shared_procedural_fill(fill):
    """Assign the same ProceduralFill recipe color-tweaked per shape when possible."""
    for m in movers:
        shp = m["shape"]
        # visual=None resets to module defaults (often white line) — restore
        # host color before swapping fill so borders keep contrast_tone.
        shp.visual = None
        shp.fill_filter = None
        shp.line_filter = None
        _clear_stamps(shp)
        bc = m.get("base_color")
        if bc is not None:
            try:
                shp.set_color(bc)
            except Exception:
                pass
        # Skip pure lines (no fill body)
        if type(shp).__name__ == "Line":
            continue
        try:
            kind = getattr(fill, "kind", None)
            amount = getattr(fill, "_amount", 1.0)
            speed = getattr(fill, "_speed", 1.0)
            color = bc
            from scena.style import WaveFill, AuroraFill
            if kind == "wave":
                shp.fill = WaveFill(color=color, amount=amount, speed=speed)
            elif kind == "aurora":
                shp.fill = AuroraFill(color=color, amount=amount, speed=speed)
            else:
                shp.fill = fill
        except Exception:
            shp.fill = fill
        # Half border line_width for raw fill demos
        try:
            th = float(getattr(shp, "line_width", 1.5) or 1.5)
            shp.line_width = max(0.5, th * 0.5)
        except Exception:
            pass


def _apply_field_shell_look(look):
    """Field/shell looks on all movers (specialized + best-effort geometry)."""
    _apply_shared_look(look)


def _apply_shield_orb_look(look):
    """Shield on all movers — Circle/Ellipse specialized; best-effort elsewhere."""
    _apply_shared_look(look)


# Dedicated non-rotating platform for Water demo
_water_pool = Rect(center=(W * 0.5, H * 0.28), width=280, height=110).set_color("dodger blue").set_alpha(0.9)
_water_pool.angle = 0.0
_water_pool.visible = False
for m in movers:
    if m["shape"] is _water_pool:
        m["spin"] = 0.0


def _apply_water_look(look):
    """Water visual only on a large non-rotating pool Rect."""
    for m in movers:
        m["shape"].visual = None
        m["shape"].fill_filter = None
        m["shape"].line_filter = None
        _clear_stamps(m["shape"])
        _restore_base_paint(m)
    _water_pool.visible = True
    _water_pool.visual = look
    _water_pool.angle = 0.0


def _hide_water_pool():
    _water_pool.visible = False
    _water_pool.visual = None
    _clear_stamps(_water_pool)


def _dispatch_look(fx):
    """Apply a visual / stamp / filter / procedural fill to the scene the right way."""
    if fx is None:
        return
    from scena.style import ProceduralFill
    from scena.visuals import Visual
    from scena.stamps import is_stamp_visual
    if isinstance(fx, ProceduralFill):
        _hide_water_pool()
        _apply_shared_procedural_fill(fx)
        return
    if is_stamp_visual(fx):
        _hide_water_pool()
        _apply_shared_look(fx)
        return
    if isinstance(fx, Visual):
        name = type(fx).__name__
        if name == "Water":
            _apply_water_look(fx)
        else:
            _hide_water_pool()
            if name in (
                "DashRing", "Halo", "HaloFill", "HaloSoft", "HaloLine", "HaloPulse", "Rim", "GearShell",
                "ElectricField",
            ):
                _apply_field_shell_look(fx)
            elif name in ("Shield", "_OrbHalo"):
                _apply_shield_orb_look(fx)
            else:
                _apply_shared_look(fx)
        return
    _hide_water_pool()
    _apply_shared_fill(fx)


def _sync_live_params():
    """Push panel values into the live effect (mutate post / rebuild shape)."""
    global _live, _last_shape_key
    if not _param_map:
        return
    if _rebuild is not None and not _panel_is_look:
        return  # the panel is the canvas mode's; the look keeps its last build
    params = _read_params()
    if _rebuild is not None:
        key = tuple(sorted(params.items()))
        if key == _last_shape_key:
            return
        _last_shape_key = key
        fx = _rebuild(**params)
        _live = fx
        _dispatch_look(fx)
        return
    # Panel belongs to the shape look while a visual is selected. Never
    # setattr leftover intensity / width / amount onto the canvas post FX
    # (Prism.amount default is 0.004; bubbles leftover amount=1.0 blows
    # the RGB split across the screen).
    look_name = VISUAL_MODES[_l_idx][0] if VISUAL_MODES else "none"
    if look_name != "none":
        return
    if _live is None:
        return
    for k, v in params.items():
        if hasattr(_live, k):
            setattr(_live, k, v)


# Param ranges (sensible lab spans around zero-arg defaults)
_P = {
    "glow": [
        ("radius", 0.0, 48.0, 12.0),
        ("sigma", 0.0, 40.0, 10.0),
        ("amount", 0.0, 2.5, 1.0),
    ],
    "cheapglow": [
        ("radius", 0.0, 48.0, 8.0),
        ("sigma", 0.0, 40.0, 0.0),
        ("amount", 0.0, 2.5, 1.0),
    ],
    "shadow": [("offset", 0.0, 40.0, 8.0), ("sigma", 0.0, 30.0, 5.0)],
    "blur": [("sigma", 0.0, 30.0, 4.0)],
    "dilate": [("radius", 0.0, 20.0, 4.0)],
    "erode": [("radius", 0.0, 12.0, 2.5)],
    "neon": [("amount", 0.2, 2.5, 1.0), ("width", 1.0, 10.0, 3.0), ("flicker", 0.0, 1.5, 0.6)],
    "multiborder": [("layers", 1, 4, 3, True), ("spread", 0.02, 0.5, 0.3)],
    "longshadow": [
        ("depth", 8.0, 80.0, 36.0),
        ("layers", 3, 7, 5, True),
        ("darken", 0.0, 1.0, 0.42),
    ],
    "shieldring": [("speed", 0.1, 4.0, 1.0), ("width", 1.0, 6.0, 2.0)],
    "aura": [("amount", 0.2, 2.5, 1.0)],
    "aura_fill": [("amount", 0.2, 2.5, 1.0)],
    "phantom": [("amount", 0.2, 2.5, 1.0)],
    "aura_pulse": [("amount", 0.2, 2.5, 1.0), ("rings", 1, 6, 3, True), ("speed", 0.1, 4.0, 1.0)],
    "plasmafield": [("speed", 0.2, 3.0, 1.2)],
    "electricfield": [("amount", 1.0, 16.0, 5.0), ("speed", 0.1, 3.0, 1.0)],
    "shield_bubble": [("amount", 0.3, 2.0, 1.0), ("speed", 0.1, 3.0, 1.0)],
    "shield_nebula": [("amount", 0.3, 2.0, 1.0), ("speed", 0.1, 3.0, 1.0)],
    "shield_nebula_ember": [("amount", 0.3, 2.0, 1.0), ("speed", 0.1, 3.0, 1.0)],
    "shield_nebula_void": [("amount", 0.3, 2.0, 1.0), ("speed", 0.1, 3.0, 1.0)],
    "shield_molten": [("amount", 0.3, 2.0, 1.0), ("speed", 0.2, 3.0, 1.15)],
    "shield_bands": [("amount", 0.3, 2.0, 1.0), ("speed", 0.0, 2.0, 0.35)],
    "shield_vortex": [("amount", 0.3, 2.0, 1.0), ("speed", 0.2, 3.0, 1.0)],
    "shield_cracks": [("amount", 0.3, 2.0, 1.0), ("speed", 0.1, 2.5, 0.7)],
    "shield_cracks_frost": [("amount", 0.3, 2.0, 1.0), ("speed", 0.1, 2.5, 0.7)],
    "shield_plasma": [("amount", 0.3, 2.0, 1.0), ("speed", 0.1, 3.0, 1.0)],
    "organic": [("amount", 0.5, 10.0, 2.5), ("speed", 0.1, 4.0, 1.0)],
    "tracer": [("speed", 0.1, 4.0, 1.0), ("gap", 4.0, 40.0, 12.0), ("width", 1.0, 10.0, 2.4)],
    "electricbolt": [("amount", 1.0, 16.0, 5.0), ("speed", 0.1, 3.0, 1.0)],
    "swell": [("amount", 0.2, 2.0, 1.0), ("speed", 0.1, 3.0, 1.0)],
    "water": [("amount", 0.2, 2.0, 1.0), ("speed", 0.1, 3.0, 1.0)],
    "flame": [("amount", 0.2, 2.0, 1.0), ("speed", 0.2, 3.0, 1.2), ("border", "bool", False)],
    "metal": [("amount", 0.2, 2.0, 1.0)],
    "liquify": [("amount", 0.5, 12.0, 3.5), ("speed", 0.1, 3.0, 1.0)],
    "bolt": [
        ("amount", 0.5, 10.0, 3.0),
        ("speed", 0.2, 3.0, 1.2),
        ("intensity", 0.3, 2.0, 1.0),
    ],
    "bolt_filaments": [
        ("amount", 0.5, 10.0, 3.0),
        ("speed", 0.2, 3.0, 1.2),
        ("intensity", 0.3, 2.0, 0.6),
    ],
    "bolt_tesla": [
        ("amount", 0.5, 10.0, 3.0),
        ("speed", 0.2, 3.0, 1.2),
        ("intensity", 0.3, 2.0, 1.0),
    ],
    "laser": [("amount", 0.2, 2.5, 1.0), ("width", 1.0, 8.0, 2.5)],
    "ink": [("amount", 0.5, 6.0, 1.8), ("speed", 0.0, 2.0, 0.6)],
    "ink_bleed": [("amount", 0.3, 4.0, 1.0)],
    "sphere": [("amount", 0.2, 2.0, 1.0), ("speed", 0.0, 2.0, 0.5)],
    "rim": [("amount", 0.2, 2.5, 1.0), ("width", 1.0, 12.0, 4.0), ("darken", 0.0, 0.8, 0.35)],
    "lineglow": [("amount", 0.2, 2.5, 1.0)],
    "gel": [("amount", 0.2, 2.5, 1.0)],
    "wave": [("amount", 0.2, 2.0, 1.0), ("speed", 0.1, 3.0, 1.0)],
    "aurora": [("amount", 0.2, 2.0, 1.0), ("speed", 0.1, 3.0, 0.9)],
    "tail": [
        ("angle", 0.0, 360.0, 210.0),
        ("size", 0.2, 3.0, 1.0),
        ("amount", 0.2, 2.5, 1.0),
    ],
    "beat": [("amount", 0.02, 0.35, 0.08), ("speed", 0.2, 3.0, 1.0)],
    "insetrim": [
        ("fill_scale", 0.5, 1.0, 0.8),
        ("amount", 0.2, 2.5, 0.3),
        ("width", 0.0, 12.0, 6.0),
    ],
    "bubbles": [
        ("count", 8.0, 48.0, 20.0, True),
        ("height", 40.0, 320.0, 140.0),
        ("amount", 0.3, 2.0, 1.0),
        ("wide", 0.0, 1.0, 0.0, True),
    ],
    "vignette": [("amount", 0.0, 1.5, 1.0)],
    "grain": [("amount", 0.0, 0.35, 0.07)],
    "bloom": [("intensity", 0.0, 2.0, 0.6), ("sigma", 1.0, 40.0, 10.0)],
    "grade": [
        ("brightness", -0.5, 0.5, 0.0),
        ("contrast", 0.2, 2.5, 1.0),
        ("saturation", 0.0, 2.5, 1.0),
    ],
    "chroma": [("amount", 0.0, 24.0, 4.0)],
    "pixelate": [("cell", 1.0, 40.0, 5.0)],
    "haze": [("amount", 0.0, 24.0, 6.0), ("speed", 0.0, 4.0, 1.0), ("bias", 0.0, 2.0, 1.0)],
    "haze_heat": [("amount", 0.0, 24.0, 10.0), ("speed", 0.0, 4.0, 1.4), ("bias", 0.0, 2.0, 1.35)],
    "haze_uw": [("amount", 0.0, 24.0, 8.0), ("speed", 0.0, 4.0, 0.55), ("bias", 0.0, 2.0, 0.45)],
    "scanlines": [("amount", 0.0, 2.0, 1.0)],
    "screenblur": [("sigma", 0.0, 20.0, 2.5)],
    "crt": [("amount", 0.0, 2.0, 1.0), ("chroma", 0.0, 3.0, 1.0), ("scan", 0.0, 2.0, 1.0)],
    "glitch": [("amount", 0.0, 2.0, 0.35)],
    "vortex": [("amount", 0.0, 3.0, 1.0), ("spin", 0.0, 4.0, 1.0)],
    "zoomblur": [("amount", 0.0, 2.0, 0.5)],
    "fog": [("amount", 0.0, 1.5, 0.45), ("height", 0.1, 1.0, 0.55)],
    "hit": [
        ("amount", 0.0, 2.5, 1.0),
        ("radius", 0.0, 500.0, 0.0),
        ("shock", "bool", True),
        ("flash", "bool", False),
        ("shake", "bool", True),
    ],
    "wave": [
        ("amount", 0.0, 2.5, 1.0),
        ("angle", 0.0, 360.0, 0.0),
        ("shock", "bool", True),
        ("flash", "bool", False),
        ("shake", "bool", True),
    ],
    "explosion": [
        ("amount", 0.0, 2.5, 1.2),
        ("shock", "bool", True),
        ("flash", "bool", False),
        ("shake", "bool", True),
        ("rings", "bool", True),
    ],
    "pyro": [
        ("amount", 0.0, 2.5, 1.0),
        ("rings", "bool", False),
    ],
    "burst": [
        ("radius", 10.0, 140.0, 42.0),
        ("amount", 0.0, 2.5, 1.2),
        ("count", 1, 8, 5, True),
        ("spread", 0.0, 160.0, 22.0),
        ("rings", "bool", False),
    ],
    "fireworks": [
        ("radius", 24.0, 180.0, 64.0),
        ("count", 8.0, 48.0, 28.0, True),
        ("fall", 0.0, 1.5, 0.0),
        ("trail", 0.0, 1.0, 0.35),
        ("color", 0, 5, 0, True),
        ("color2", 0, 5, 1, True),
    ],
    # Shared panel for zap_spark / zap_fork / zap_corona (style fixed per mode).
    "zap": [
        ("radius", 8.0, 120.0, 24.0),
        ("amount", 0.0, 2.5, 1.0),
        ("count", 4, 36, 14, True),
        ("color", 0, 5, 0, True),
        ("flash", "bool", False),
    ],
    "hit_at": [
        ("radius", 6.0, 80.0, 16.0),
        ("amount", 0.0, 2.5, 1.0),
        ("count", 0, 24, 8, True),
        ("aim", "bool", True),
        ("disc", "bool", False),
        ("angle", 0.0, 360.0, 90.0),
        ("color", 0, 5, 0, True),
        ("stream", "bool", False),
    ],
    "debris": [
        ("radius", 10.0, 160.0, 40.0),
        ("amount", 0.0, 2.5, 1.0),
        ("count", 4, 40, 14, True),
        ("fall", 0.0, 1.5, 0.0),
        ("color", 0, 5, 0, True),
        ("dust", "bool", True),
        ("with_hit", "bool", False),
        ("with_burst", "bool", False),
    ],
    "rays": [
        ("weight", 0.0, 1.0, 0.35),
        ("decay", 0.5, 0.99, 0.86),
        ("exposure", 0.2, 4.0, 1.8),
    ],
    "trails": [("fade", 0.5, 0.99, 0.90), ("opacity", 0.0, 1.0, 1.0)],
    "shake": [("amount", 0.0, 40.0, 5.0), ("speed", 1.0, 80.0, 28.0)],
    "flash": [("intensity", 0.0, 1.0, 0.0), ("decay", 0.5, 10.0, 3.2)],
    "cover": [
        ("duration", 0.05, 2.0, 0.5),
        ("angle", 0.0, 360.0, 90.0),
    ],
    "kaleido": [
        ("segments", 2, 24, 8, True),
        ("zoom", 0.3, 3.0, 1.0),
        ("spin", -2.0, 2.0, 0.15),
    ],
    "prism": [("amount", 0.0, 0.03, 0.004)],
    "perspective": [("amount", 0.0, 1.5, 0.55)],
    "colorsweep": [
        ("amount", 0.0, 1.4, 0.55),
        ("speed", 0.0, 2.0, 1.0),
        ("saturation", 0.0, 1.5, 0.45),
        ("axis", 0, 2, 0, True),
    ],
    "colorsweep_h": [
        ("amount", 0.0, 1.4, 0.55),
        ("speed", 0.0, 2.0, 1.0),
        ("saturation", 0.0, 1.5, 0.45),
    ],
    "colorsweep_v": [
        ("amount", 0.0, 1.4, 0.55),
        ("speed", 0.0, 2.0, 1.0),
        ("saturation", 0.0, 1.5, 0.45),
    ],
    "plasmawash": [
        ("amount", 0.0, 1.4, 0.55),
        ("speed", 0.0, 2.0, 0.55),
        ("saturation", 0.0, 1.5, 0.4),
    ],
    "nebulabloom": [
        ("amount", 0.0, 1.4, 1.0),
        ("bloom", 0.0, 1.8, 0.7),
        ("speed", 0.0, 2.0, 1.2),
        ("saturation", 0.0, 1.5, 0.35),
    ],
    "lamp": [
        ("intensity", 0.0, 3.0, 1.15),
        ("ambient", 0.0, 1.0, 0.16),
        ("specular", 0.0, 2.0, 0.6),
    ],
    "distant": [
        ("intensity", 0.0, 2.5, 0.95),
        ("ambient", 0.0, 1.0, 0.28),
        ("specular", 0.0, 2.0, 0.35),
        ("angle", 0.0, 360.0, 234.0),
    ],
    "spotlight": [
        ("intensity", 0.0, 3.0, 1.45),
        ("ambient", 0.0, 1.0, 0.1),
        ("cone_angle", 5.0, 70.0, 34.0),
        ("softness", 1.0, 40.0, 14.0),
        ("range", 80.0, 900.0, 440.0),
    ],
}
_P["cover_fade"] = _P["cover_wipe"] = _P["cover_iris"] = _P["cover"]
_P["zap_spark"] = _P["zap_fork"] = _P["zap_corona"] = _P["zap"]


# ---------------------------------------------------------------------------
# Canvas modes (post only — do not clear looks)
# ---------------------------------------------------------------------------
CANVAS_MODES = []


def _cmode(name, label):
    def deco(fn):
        CANVAS_MODES.append((name, label, fn))
        return fn
    return deco


@_cmode("none", "none")
def _c_none():
    global _live, _canvas_live
    canvas.effects.clear()
    _clear_cover()
    _canvas_live = None
    # Do not clear `_rebuild`: canvas none is independent of the shape look.
    # Wiping it made leftover sliders setattr onto the next post FX (Prism).
    if _rebuild is None:
        _live = None
    _hide_pyro_labels()


def _add_post_only(fx, name: str):
    global _live, _canvas_live
    canvas.effects.clear()
    _hide_pyro_labels()
    _canvas_live = canvas.effects.add(fx)
    if _rebuild is None:
        _live = _canvas_live
    return _canvas_live


@_cmode("vignette", "Vignette (edge strips)")
def _c_vignette():
    _add_post_only(Vignette(), "vignette")


@_cmode("grain", "Grain")
def _c_grain():
    _add_post_only(Grain(), "grain")


@_cmode("bloom", "Bloom")
def _c_bloom():
    _add_post_only(Bloom(), "bloom")


@_cmode("grade", "Grade")
def _c_grade():
    _add_post_only(Grade(), "grade")


@_cmode("chroma", "Chroma")
def _c_chroma():
    _add_post_only(Chroma(), "chroma")


@_cmode("pixelate", "Pixelate")
def _c_pixelate():
    _add_post_only(Pixelate(), "pixelate")


@_cmode("haze", "Haze")
def _c_haze():
    _add_post_only(Haze(), "haze")


@_cmode("crt", "Crt")
def _c_crt():
    _add_post_only(Crt(), "crt")


@_cmode("glitch", "glitch (click)")
def _c_glitch():
    _c_none()
    canvas.effects._hit_feedback()


@_cmode("fog", "Fog")
def _c_fog():
    _add_post_only(Fog(), "fog")


@_cmode("scanlines", "Scanlines")
def _c_scanlines():
    _add_post_only(Scanlines(), "scanlines")


@_cmode("screenblur", "ScreenBlur")
def _c_screenblur():
    _add_post_only(ScreenBlur(), "screenblur")


@_cmode("hit", "ripple_at (click)")
def _c_hit():
    _c_none()
    canvas.effects._hit_feedback()


@_cmode("wave", "wave_at (click)")
def _c_wave():
    _c_none()
    canvas.effects._hit_feedback()


@_cmode("explosion", "explosion_at (click)")
def _c_explosion():
    _c_none()
    canvas.effects._hit_feedback()


@_cmode("burst", "burst_at (click)")
def _c_burst():
    _c_none()
    canvas.effects._hit_feedback()


@_cmode("fireworks", "fireworks_at (click)")
def _c_fireworks():
    _c_none()
    canvas.effects._hit_feedback()


@_cmode("zap_spark", "zap_at spark (click)")
def _c_zap_spark():
    _c_none()
    canvas.effects._hit_feedback()


@_cmode("zap_fork", "zap_at fork (click)")
def _c_zap_fork():
    _c_none()
    canvas.effects._hit_feedback()


@_cmode("zap_corona", "zap_at corona (click)")
def _c_zap_corona():
    _c_none()
    canvas.effects._hit_feedback()


@_cmode("hit_at", "hit_at (click)")
def _c_hit_at():
    _c_none()
    canvas.effects._hit_feedback()


@_cmode("debris", "debris_at (click)")
def _c_debris():
    _c_none()
    canvas.effects._hit_feedback()


@_cmode("bench_explosion", "BENCH explosion (auto)")
def _c_bench_ex():
    _c_none()
    canvas.effects._hit_feedback()


@_cmode("bench_burst", "BENCH burst (auto)")
def _c_bench_bu():
    _c_none()
    canvas.effects._hit_feedback()


@_cmode("bubbles", "bubbles_at (click)")
def _c_bubbles():
    _c_none()
    canvas.effects._hit_feedback()
    # Panel is bound in `_apply_canvas` only when no shape look is active.
    # Configuring here while Neon is on replaced look sliders with
    # amount=1.0, which then leaked into Prism.


@_cmode("lamp", "Lamp")
def _c_lamp():
    _add_post_only(Lamp(), "lamp")


@_cmode("distant", "DistantLight")
def _c_distant():
    _add_post_only(DistantLight(), "distant")

@_cmode("spotlight", "Spotlight")
def _c_spotlight():
    _add_post_only(Spotlight(), "spotlight")


@_cmode("rays", "GodRays")
def _c_rays():
    _add_post_only(GodRays(), "rays")


@_cmode("trails", "MotionTrail")
def _c_trails():
    _add_post_only(MotionTrail(), "trails")


@_cmode("prism", "Prism")
def _c_prism():
    _add_post_only(Prism(), "prism")


@_cmode("kaleido", "Kaleidoscope")
def _c_kaleido():
    _add_post_only(Kaleidoscope(), "kaleido")


@_cmode("wash", "Wash")
def _c_wash():
    _add_post_only(Wash(), "wash")


@_cmode("flash", "flash (click)")
def _c_flash():
    _c_none()
    canvas.effects._hit_feedback()


def _c_cover_enter():
    # Isolate cover from post; start uncovered so the first click is fade_out.
    _c_none()


@_cmode("cover_fade", "cover fade (click out/in)")
def _c_cover_fade():
    _c_cover_enter()


@_cmode("cover_wipe", "cover wipe (click out/in)")
def _c_cover_wipe():
    _c_cover_enter()


@_cmode("cover_iris", "cover iris (click out/in)")
def _c_cover_iris():
    _c_cover_enter()


@_cmode("shake", "shake (click)")
def _c_shake():
    _c_none()
    canvas.effects._hit_feedback()


@_cmode("colorsweep", "ColorSweep (radial)")
def _c_colorsweep():
    _add_post_only(ColorSweep(axis="radial"), "colorsweep")


@_cmode("colorsweep_h", "ColorSweep (left→right)")
def _c_colorsweep_h():
    _add_post_only(
        ColorSweep(axis="horizontal", colors=("tomato", "gold", "navy")),
        "colorsweep_h",
    )


@_cmode("colorsweep_v", "ColorSweep (top→bottom)")
def _c_colorsweep_v():
    _add_post_only(
        ColorSweep(axis="vertical", colors=("navy", "cyan", "lime", "gold")),
        "colorsweep_v",
    )


@_cmode("plasmawash", "ColorWash")
def _c_plasmawash():
    _add_post_only(ColorWash(), "plasmawash")


@_cmode("nebulabloom", "CosmicBloom")
def _c_nebulabloom():
    _add_post_only(CosmicBloom(), "nebulabloom")


@_cmode("vortex", "Vortex")
def _c_vortex():
    _add_post_only(Vortex(), "vortex")


@_cmode("zoomblur", "ZoomBlur")
def _c_zoomblur():
    _add_post_only(ZoomBlur(), "zoomblur")


# ---------------------------------------------------------------------------
# Visual modes (shape only — do not clear canvas post)
# ---------------------------------------------------------------------------
VISUAL_MODES = []


def _lmode(name, label):
    def deco(fn):
        VISUAL_MODES.append((name, label, fn))
        return fn
    return deco


@_lmode("none", "none")
def _l_none():
    global _rebuild, _live
    _rebuild = None
    _hide_water_pool()
    _clear_shape_fx()
    _live = _canvas_live
    # Show canvas params if any when no visual active
    cn = CANVAS_MODES[_c_idx][0] if CANVAS_MODES else "none"
    _configure_panel(_P.get(cn, []))

@_lmode("plasmafield", "GearShell")
def _l_plasmafield():
    global _rebuild
    _rebuild = lambda **kw: GearShell(speed=kw.get("speed", 1.2))
    _configure_panel(_P["plasmafield"])
    _sync_live_params()


@_lmode("laser", "Laser (halo+mid+white core)")
def _l_laser():
    global _rebuild
    _rebuild = lambda **kw: Laser(amount=kw.get("amount", 1.0))
    _configure_panel(_P["laser"])
    _sync_live_params()


@_lmode("glow", "Glow")
def _l_glow():
    global _rebuild
    # color=None keeps each mover's host paint; shared GlowFilter under the stamp.
    _rebuild = lambda **kw: Glow(
        radius=kw.get("radius", 12.0),
        sigma=kw.get("sigma", 10.0),
        amount=kw.get("amount", 1.0),
    )
    _configure_panel(_P["glow"])
    _sync_live_params()


@_lmode("cheapglow", "CheapGlow")
def _l_cheapglow():
    global _rebuild
    _rebuild = lambda **kw: CheapGlow(
        radius=kw.get("radius", 8.0),
        sigma=kw.get("sigma", 0.0),
        amount=kw.get("amount", 1.0),
    )
    _configure_panel(_P["cheapglow"])
    _sync_live_params()


@_lmode("shadow", "Shadow")
def _l_shadow():
    global _rebuild
    # color=None keeps each mover's host paint; installs shared DropShadow filter.
    _rebuild = lambda **kw: Shadow(
        offset=kw.get("offset", 8.0),
        sigma=kw.get("sigma", 5.0),
    )
    _configure_panel(_P["shadow"])
    _sync_live_params()


@_lmode("neon", "Neon look")
def _l_neon():
    global _rebuild
    _rebuild = lambda **kw: Neon(
        amount=kw.get("amount", 1.0),
        width=kw.get("width", 3.0),
        flicker=kw.get("flicker", 0.6),
    )
    _configure_panel(_P["neon"])
    _sync_live_params()


@_lmode("multiborder", "MultiBorder")
def _l_mb():
    global _rebuild
    _rebuild = lambda **kw: MultiBorder(layers=int(kw.get("layers", 3)), spread=kw.get("spread", 0.3))
    _configure_panel(_P["multiborder"])
    _sync_live_params()


@_lmode("longshadow", "Extrude (depth)")
def _l_ls():
    global _rebuild
    _rebuild = lambda **kw: Extrude(
        depth=kw.get("depth", 36),
        layers=int(kw.get("layers", 5)),
        edges=False,
        darken=kw.get("darken", 0.42),
    )
    _configure_panel(_P["longshadow"])
    _sync_live_params()


@_lmode("shieldring", "DashRing (all shapes)")
def _l_shieldring():
    global _rebuild
    _rebuild = lambda **kw: DashRing(speed=kw.get("speed", 1), width=kw.get("width", 2.0))
    _configure_panel(_P["shieldring"])
    _sync_live_params()


@_lmode("electricfield", "ElectricField")
def _l_electricfield():
    global _rebuild
    _rebuild = lambda **kw: ElectricField(
        amount=kw.get("amount", 5), speed=kw.get("speed", 1.0),
    )
    _configure_panel(_P["electricfield"])
    _sync_live_params()

@_lmode("electricbolt", "ElectricBolt")
def _l_electricbolt():
    global _rebuild
    _rebuild = lambda **kw: ElectricBolt(amount=kw.get("amount", 5), speed=kw.get("speed", 1.0))
    _configure_panel(_P["electricbolt"])
    _sync_live_params()


@_lmode("shield_bubble", "Shield bubble (orb)")
def _l_sh_bubble():
    global _rebuild
    _rebuild = lambda **kw: Shield(
        style="bubble", amount=kw.get("amount", 1.0), speed=kw.get("speed", 1.0),
    )
    _configure_panel(_P["shield_bubble"])
    _sync_live_params()


@_lmode("shield_nebula", "Shield nebula classic (orb)")
def _l_sh_nebula():
    global _rebuild
    _rebuild = lambda **kw: Shield(
        style="nebula", amount=kw.get("amount", 1.0), speed=kw.get("speed", 1.0),
    )
    _configure_panel(_P["shield_nebula"])
    _sync_live_params()


@_lmode("shield_nebula_ember", "Shield nebula ember (orb)")
def _l_sh_nebula_ember():
    global _rebuild
    _rebuild = lambda **kw: Shield(
        style="ember", amount=kw.get("amount", 1.0), speed=kw.get("speed", 1.0),
    )
    _configure_panel(_P["shield_nebula_ember"])
    _sync_live_params()


@_lmode("shield_nebula_void", "Shield nebula void (orb)")
def _l_sh_nebula_void():
    global _rebuild
    _rebuild = lambda **kw: Shield(
        style="void", amount=kw.get("amount", 1.0), speed=kw.get("speed", 1.0),
    )
    _configure_panel(_P["shield_nebula_void"])
    _sync_live_params()


@_lmode("shield_molten", "Shield molten (orb)")
def _l_sh_molten():
    global _rebuild
    _rebuild = lambda **kw: Shield(
        style="molten", amount=kw.get("amount", 1.0), speed=kw.get("speed", 1.15),
    )
    _configure_panel(_P["shield_molten"])
    _sync_live_params()


@_lmode("shield_bands", "Shield bands (orb, live host color)")
def _l_sh_bands():
    global _rebuild
    # color=None → samples each orb host fill as primary tint
    _rebuild = lambda **kw: Shield(
        style="bands", amount=kw.get("amount", 1.0), speed=kw.get("speed", 0.35),
    )
    _configure_panel(_P["shield_bands"])
    _sync_live_params()


@_lmode("shield_plasma", "Shield plasma (plasma + blur rim)")
def _l_sh_plasma():
    global _rebuild
    _rebuild = lambda **kw: Shield(
        style="plasma",
        amount=kw.get("amount", 1.0),
        speed=kw.get("speed", 1.0),
    )
    _configure_panel(_P["shield_plasma"])
    _sync_live_params()

@_lmode("shield_vortex", "Shield vortex (orb, live host color)")
def _l_sh_vortex():
    global _rebuild
    _rebuild = lambda **kw: Shield(
        style="vortex", amount=kw.get("amount", 1.0), speed=kw.get("speed", 1.0),
    )
    _configure_panel(_P["shield_vortex"])
    _sync_live_params()


@_lmode("shield_cracks", "Shield cracks magma (orb)")
def _l_sh_cracks():
    global _rebuild
    _rebuild = lambda **kw: Shield(
        style="cracks", amount=kw.get("amount", 1.0), speed=kw.get("speed", 0.7),
    )
    _configure_panel(_P["shield_cracks"])
    _sync_live_params()


@_lmode("shield_cracks_frost", "Shield cracks frost (orb)")
def _l_sh_cracks_frost():
    global _rebuild
    _rebuild = lambda **kw: Shield(
        style="frost", amount=kw.get("amount", 1.0), speed=kw.get("speed", 0.7),
    )
    _configure_panel(_P["shield_cracks_frost"])
    _sync_live_params()


@_lmode("organic", "OrganicOutline")
def _l_or():
    global _rebuild
    _rebuild = lambda **kw: OrganicOutline(amount=kw.get("amount", 3), speed=kw.get("speed", 1))
    _configure_panel(_P["organic"])
    _sync_live_params()


@_lmode("tracer", "Tracer")
def _l_tr():
    global _rebuild
    _rebuild = lambda **kw: Tracer(speed=kw.get("speed", 1), gap=kw.get("gap", 12), width=kw.get("width", 2.4))
    _configure_panel(_P["tracer"])
    _sync_live_params()


@_lmode("swell", "Swell")
def _l_sw():
    global _rebuild
    _rebuild = lambda **kw: Swell(amount=kw.get("amount", 1), speed=kw.get("speed", 1))
    _configure_panel(_P["swell"])
    _sync_live_params()


@_lmode("water", "Water (side view)")
def _l_wa():
    global _rebuild
    _rebuild = lambda **kw: Water(amount=kw.get("amount", 1), speed=kw.get("speed", 1))
    _configure_panel(_P["water"])
    _sync_live_params()


@_lmode("flame", "Flame")
def _l_fi():
    global _rebuild
    _rebuild = lambda **kw: Flame(
        amount=kw.get("amount", 1),
        speed=kw.get("speed", 1.2),
        border=bool(kw.get("border", False)),
    )
    _configure_panel(_P["flame"])
    _sync_live_params()


@_lmode("metal", "Metal")
def _l_me():
    global _rebuild
    _rebuild = lambda **kw: Metal(amount=kw.get("amount", 1))
    _configure_panel(_P["metal"])
    _sync_live_params()


@_lmode("liquify", "Liquify")
def _l_lq():
    global _rebuild
    _rebuild = lambda **kw: Liquify(amount=kw.get("amount", 3.5), speed=kw.get("speed", 1))
    _configure_panel(_P["liquify"])
    _sync_live_params()


@_lmode("bolt", "Bolt (core classic)")
def _l_ps():
    global _rebuild
    _rebuild = lambda **kw: Bolt(
        amount=kw.get("amount", 3.0),
        speed=kw.get("speed", 1.2),
        intensity=kw.get("intensity", 1.0),
        style="core",
    )
    _configure_panel(_P["bolt"])
    _sync_live_params()


@_lmode("bolt_filaments", "Bolt (filaments)")
def _l_psf():
    global _rebuild
    _rebuild = lambda **kw: Bolt(
        amount=kw.get("amount", 3.0),
        speed=kw.get("speed", 1.2),
        intensity=kw.get("intensity", 0.6),
        style="filaments",
    )
    _configure_panel(_P["bolt_filaments"])
    _sync_live_params()


@_lmode("bolt_tesla", "Bolt (tesla)")
def _l_pst():
    global _rebuild
    _rebuild = lambda **kw: Bolt(
        amount=kw.get("amount", 3.0),
        speed=kw.get("speed", 1.2),
        intensity=kw.get("intensity", 1.0),
        style="tesla",
    )
    _configure_panel(_P["bolt_tesla"])
    _sync_live_params()


@_lmode("ink", "Ink (pen)")
def _l_ink():
    global _rebuild
    _rebuild = lambda **kw: Ink(amount=kw.get("amount", 1.8), speed=kw.get("speed", 0.6))
    _configure_panel(_P["ink"])
    _sync_live_params()


@_lmode("ink_bleed", "Ink (bleed)")
def _l_ink_bleed():
    global _rebuild
    _rebuild = lambda **kw: InkBleed(amount=kw.get("amount", 1.0))
    _configure_panel(_P["ink_bleed"])
    _sync_live_params()


@_lmode("sphere", "Sphere")
def _l_sphere():
    global _rebuild
    _rebuild = lambda **kw: Sphere(amount=kw.get("amount", 1.0), speed=kw.get("speed", 0.5))
    _configure_panel(_P["sphere"])
    _sync_live_params()


@_lmode("rim", "Rim")
def _l_rim():
    global _rebuild
    _rebuild = lambda **kw: Rim(
        amount=kw.get("amount", 1.0),
        width=kw.get("width", 4.0),
        darken=kw.get("darken", 0.35),
    )
    _configure_panel(_P["rim"])
    _sync_live_params()


@_lmode("gel", "Gel")
def _l_gel():
    global _rebuild
    _rebuild = lambda **kw: Gel(amount=kw.get("amount", 1.0))
    _configure_panel(_P["gel"])
    _sync_live_params()


@_lmode("wave", "Wave")
def _l_wave():
    global _rebuild
    _rebuild = lambda **kw: Wave(amount=kw.get("amount", 1.0), speed=kw.get("speed", 1.0))
    _configure_panel(_P["wave"])
    _sync_live_params()


@_lmode("aurora", "Aurora")
def _l_aurora():
    global _rebuild
    _rebuild = lambda **kw: Aurora(amount=kw.get("amount", 1.0), speed=kw.get("speed", 0.9))
    _configure_panel(_P["aurora"])
    _sync_live_params()


@_lmode("tail", "Tail")
def _l_tail():
    global _rebuild
    _rebuild = lambda **kw: Tail(
        angle=kw.get("angle", 210.0),
        size=kw.get("size", 1.0),
        amount=kw.get("amount", 1.0),
    )
    _configure_panel(_P["tail"])
    _sync_live_params()


@_lmode("beat", "Beat")
def _l_pulsescale():
    global _rebuild
    _rebuild = lambda **kw: Beat(
        amount=kw.get("amount", 0.08), speed=kw.get("speed", 1.0),
    )
    _configure_panel(_P["beat"])
    _sync_live_params()


@_lmode("insetrim", "InsetRim")
def _l_insetrim():
    global _rebuild
    def _mk(**kw):
        bw = float(kw.get("width", 6.0) or 0.0)
        return InsetRim(
            fill_scale=kw.get("fill_scale", 0.8),
            width=None if bw < 0.5 else bw,
            amount=kw.get("amount", 0.3),
        )
    _rebuild = _mk
    _configure_panel(_P["insetrim"])
    _sync_live_params()


@_lmode("aura", "Halo")
def _l_aura():
    global _rebuild
    _rebuild = lambda **kw: Halo(amount=kw.get("amount", 1.0))
    _configure_panel(_P["aura"])
    _sync_live_params()


@_lmode("aura_fill", "Halo fill (Halo + solid fill)")
def _l_aura_fill():
    global _rebuild
    _rebuild = lambda **kw: Halo(style="fill", amount=kw.get("amount", 1.0))
    _configure_panel(_P["aura_fill"])
    _sync_live_params()


@_lmode("phantom", "Halo soft (batched glow fill)")
def _l_phantom():
    global _rebuild
    _rebuild = lambda **kw: Halo(style="soft", amount=kw.get("amount", 1.0))
    _configure_panel(_P["phantom"])
    _sync_live_params()


@_lmode("lineglow", "Halo line (outline glow, no fill)")
def _l_lineglow():
    global _rebuild
    _rebuild = lambda **kw: Halo(style="line", amount=kw.get("amount", 1.0))
    _configure_panel(_P["lineglow"])
    _sync_live_params()


@_lmode("aura_pulse", "Halo pulse (concentric rings)")
def _l_aura_pulse():
    global _rebuild
    _rebuild = lambda **kw: Halo(
        style="pulse",
        amount=kw.get("amount", 1.0),
        rings=int(kw.get("rings", 3)),
        speed=kw.get("speed", 1.0),
    )
    _configure_panel(_P["aura_pulse"])
    _sync_live_params()

# Evaluation cluster first, then the rest of the catalog.
_EVAL_VISUALS = (
    "aura",
    "aura_fill",
    "phantom",
    "lineglow",
    "aura_pulse",
    "rim",
    "neon",
    "laser",
    "electricfield",
    "plasmafield",
    "shield_plasma",
    "electricbolt",
)
_by_name = {m[0]: m for m in VISUAL_MODES}
_front = ["none"] + [n for n in _EVAL_VISUALS if n in _by_name]
_seen = set(_front)
VISUAL_MODES[:] = [_by_name[n] for n in _front] + [m for m in VISUAL_MODES if m[0] not in _seen]

_canvas_names = [m[0] for m in CANVAS_MODES]
_visual_names = [m[0] for m in VISUAL_MODES]
_c_idx = 0
_l_idx = 0

if args.canvas and args.canvas in _canvas_names:
    _c_idx = _canvas_names.index(args.canvas)
elif args.start in _canvas_names:
    _c_idx = _canvas_names.index(args.start)
if args.visual == "ringfield":
    args.visual = "shieldring"
if args.visual in ("edgeglow",):
    args.visual = "rim"
if args.visual in ("halo_line",):
    args.visual = "lineglow"
if args.visual in _visual_names:
    _l_idx = _visual_names.index(args.visual)


def _hud():
    cn, cl, _ = CANVAS_MODES[_c_idx]
    ln, ll, _ = VISUAL_MODES[_l_idx]
    q = canvas.fx_quality
    qn = q.value if q is not None else "?"
    hud.title = f"Shape FX — canvas:{cl}"
    if _is_cover_mode(cn):
        hud.expect = (
            "click fade_out / click fade_in — covers HUD (A/S/SPACE still work)  ·  "
            f"covered={canvas.covered:.2f}"
        )
        hud.status = f"Q={qn}  visual: {ll}"
    elif cn == "fireworks":
        hud.expect = (
            "click to burst  ·  color/color2  0 gold  1 cyan  2 magenta  "
            "3 lime  4 white  5 tomato"
        )
        hud.status = f"Q={qn}"
    elif cn.startswith("zap_"):
        style = cn.split("_", 1)[-1]
        hud.expect = (
            f"click zap style={style}  ·  color  0 cyan  1 gold  2 magenta  "
            "3 lime  4 white  5 tomato  ·  A/S cycle spark|fork|corona"
        )
        hud.status = f"Q={qn}"
    elif cn == "hit_at":
        hud.expect = (
            "click = hit_at  ·  aim off = all around  ·  count 0 = no sparks  ·  "
            "disc = style=\"disc\"  ·  stream on = hold to fire  ·  "
            "color  0 default  1 cyan  2 gold  3 magenta  4 lime  5 tomato"
        )
        hud.status = f"Q={qn}"
    elif cn == "debris":
        hud.expect = (
            "click = debris_at  ·  fall 0 drift / ~1 arc  ·  with_hit / with_burst chain  ·  "
            "color  0 stone  1 peru  2 dim gray  3 olive  4 white  5 firebrick"
        )
        hud.status = f"Q={qn}"
    else:
        hud.expect = f"visual: {ll}"
        hud.status = f"Q={qn}"


def _apply_canvas(i: int):
    global _c_idx, _last_shape_key, _panel_is_look
    prev = CANVAS_MODES[_c_idx][0]
    _c_idx = i % len(CANVAS_MODES)
    name, label, fn = CANVAS_MODES[_c_idx]
    fn()
    if not _is_cover_mode(name):
        _clear_cover()
    # Prefer shape-look params when a visual is active — do not clobber user
    # sliders — except for click modes, which read their own on every click.
    look_name = VISUAL_MODES[_l_idx][0]
    if look_name == "none" or look_name not in _P or _click_owns_panel(name):
        _configure_panel(_P.get(name, []))
        _panel_is_look = False
        _last_shape_key = None
        _sync_live_params()
    elif _click_owns_panel(prev):
        # A click mode had the panel: give it back to the look.
        _panel_is_look = True
        VISUAL_MODES[_l_idx][2]()
    _hud()


def _apply_visual(i: int):
    global _l_idx, _last_shape_key, _rebuild, _live, _panel_is_look
    _l_idx = i % len(VISUAL_MODES)
    name, label, fn = VISUAL_MODES[_l_idx]
    _last_shape_key = None
    cn = CANVAS_MODES[_c_idx][0]
    if name == "none":
        _rebuild = None
        _hide_water_pool()
        _clear_shape_fx()
        _live = _canvas_live
        _configure_panel(_P.get(cn, []))
        _panel_is_look = False
        _sync_live_params()
    else:
        _panel_is_look = True
        fn()  # configures visual panel + rebuild + applies
        if _click_owns_panel(cn):
            # The look is built from its defaults; the panel stays the click's.
            _configure_panel(_P.get(cn, []))
            _panel_is_look = False
    _hud()


_apply_canvas(_c_idx)
_apply_visual(_l_idx)

_mouse_was_down = False
_bench_t0 = None
_bench_frames = []
_bench_warm = False


def _over_ui() -> bool:
    wm = ScenaFramework.get_instance().widget_manager
    return wm.get_widget_at(mouse.x, mouse.y) is not None


def _sync_distant():
    fx = _canvas_live if _canvas_live is not None else _live
    if fx is None or not isinstance(fx, DistantLight):
        return
    p = _read_params()
    ang = math.radians(p.get("angle", 234.0))
    fx.direction = (math.cos(ang), math.sin(ang))
    fx.intensity = p.get("intensity", fx.intensity)
    fx.ambient = p.get("ambient", fx.ambient)
    fx.specular = p.get("specular", fx.specular)


def update(dt):
    global _c_idx, _l_idx, _mouse_was_down, _bench_t0, _bench_warm
    global _pyro_acc, _bench_auto_acc, _stream_acc
    t = clock.time

    if keyp.once("O"):
        canvas.cull_offscreen = not canvas.cull_offscreen

    for m in movers:
        shp = m["shape"]
        nx = m["ox"] + math.sin(t * m["freq"] + m["phase"]) * m["amp"]
        ny = m["oy"] + math.cos(t * m["freq"] * 0.85 + m["phase"]) * m["amp"] * 0.7
        shp.move_to(nx, ny)
        if m["spin"]:
            shp.rotate_by(m["spin"] * dt)
        if isinstance(shp, (Rect, Square)):
            shp.corner_radius = st.corner_radius

    # Pin water pool (no spin, fixed bar)
    if _water_pool.visible:
        _water_pool.angle = 0.0
        _water_pool.move_to(W * 0.5, H * 0.28)
        _water_pool.corner_radius = st.corner_radius

    # Extrude vanishing point follows the mouse (global set_extrude_focus API).
    # Skip while over UI sliders so scrubbing still works cleanly.
    if VISUAL_MODES[_l_idx][0] == "longshadow" and not _over_ui():
        set_extrude_focus(mouse.x, mouse.y)

    if not args.bench:
        if keyp.once("A"):
            _apply_canvas(_c_idx - 1)
        if keyp.once("S"):
            _apply_canvas(_c_idx + 1)
        if keyp.once("Q"):
            _apply_visual(_l_idx - 1)
        if keyp.once("W"):
            _apply_visual(_l_idx + 1)
        if keyp.once("SPACE"):
            _apply_canvas(_canvas_names.index("none"))
            _apply_visual(_visual_names.index("none"))
        if keyp.once("E"):
            from _hud import cycle_quality
            hud.status = f"quality={cycle_quality()}"

    cname = CANVAS_MODES[_c_idx][0]
    lname = VISUAL_MODES[_l_idx][0]
    if _is_cover_mode(cname):
        _hud()
    # Prefer shape-look sliders; canvas post params only when visual is none.
    if lname != "none" and _rebuild is not None:
        _sync_live_params()
    elif cname == "distant":
        _sync_distant()
    else:
        _sync_live_params()

    # Pyro demo grid: re-fire explosion + burst so they stay visible
    if cname == "pyro":
        p = _read_params()
        amount = float(p.get("amount", 1.0)) if p else 1.0
        _pyro_acc += dt
        if _pyro_acc >= 0.55:
            _pyro_acc = 0.0
            _fire_pyro_grid(amount, rings=bool(p.get("rings", False)))

    # Isolated recipe benches (auto-fire) — use with --bench --canvas bench_explosion etc.
    if cname.startswith("bench_"):
        _bench_auto_acc += dt
        if _bench_auto_acc >= 0.12:
            _bench_auto_acc = 0.0
            canvas.effects._hit_feedback()
            cx, cy = W * 0.5, H * 0.5
            if cname == "bench_explosion":
                canvas.explosion_at(cx, cy, amount=1.0, shock=False, flash=False, shake=False)
            elif cname == "bench_burst":
                canvas.burst_at(cx, cy, radius=48.0, amount=1.0)

    down = mouse.press(0)
    if down and not _mouse_was_down and not args.bench and (
        _is_cover_mode(cname) or not _over_ui()
    ):
        p = _read_params()
        if cname == "hit":
            r = float(p.get("radius", 0.0))
            canvas.ripple_at(
                mouse.x, mouse.y,
                amount=p.get("amount", 1.0),
                radius=(r if r > 0.0 else None),
                shock=p.get("shock", True),
                flash=p.get("flash", False),
                shake=p.get("shake", True),
            )
        elif cname == "wave":
            canvas.wave_at(
                mouse.x, mouse.y, angle=p.get("angle", 0.0),
                amount=p.get("amount", 1.0),
                shock=p.get("shock", True), flash=p.get("flash", False),
                shake=p.get("shake", True),
            )
        elif cname == "explosion":
            canvas.explosion_at(
                mouse.x, mouse.y, amount=p.get("amount", 1.2),
                shock=p.get("shock", True), flash=p.get("flash", False),
                shake=p.get("shake", True), rings=p.get("rings", True),
            )
        elif cname == "burst":
            n = max(1, int(p.get("count", 5)))
            radius = float(p.get("radius", 42.0))
            amount = float(p.get("amount", 1.2))
            spread = float(p.get("spread", 22.0))
            rings = bool(p.get("rings", False))
            for i in range(n):
                if i == 0:
                    bx, by = mouse.x, mouse.y
                else:
                    ang = random.random() * math.tau
                    d = random.uniform(0.0, spread)
                    bx = mouse.x + math.cos(ang) * d
                    by = mouse.y + math.sin(ang) * d
                r = radius * random.uniform(0.75, 1.15) if n > 1 else radius
                canvas.burst_at(bx, by, radius=r, amount=amount, rings=rings)
        elif cname == "fireworks":
            n_sw = len(_FW_SWATCHES)
            c0 = max(0, min(n_sw - 1, int(p.get("color", 0))))
            c1 = max(0, min(n_sw - 1, int(p.get("color2", 1))))
            canvas.fireworks_at(
                mouse.x, mouse.y,
                color=_FW_SWATCHES[c0],
                color2=_FW_SWATCHES[c1],
                radius=float(p.get("radius", 64.0)),
                count=int(p.get("count", 28)),
                fall=float(p.get("fall", 0.0)),
                trail=float(p.get("trail", 0.35)),
            )
        elif cname.startswith("zap_"):
            style = cname.split("_", 1)[-1]
            if style not in _ZAP_STYLES:
                style = "spark"
            n_sw = len(_ZAP_SWATCHES)
            c0 = max(0, min(n_sw - 1, int(p.get("color", 0))))
            canvas.zap_at(
                mouse.x, mouse.y,
                color=_ZAP_SWATCHES[c0],
                radius=float(p.get("radius", 24.0)),
                amount=float(p.get("amount", 1.0)),
                count=int(p.get("count", 14)),
                style=style,
                flash=bool(p.get("flash", False)),
            )
        elif cname == "hit_at":
            _fire_hit(p, mouse.x, mouse.y)
            _stream_acc = 0.0
        elif cname == "debris":
            _fire_debris(p, mouse.x, mouse.y)
        elif cname == "pyro":
            _fire_pyro_zone(
                mouse.x, mouse.y,
                amount=float(p.get("amount", 1.0)),
                rings=bool(p.get("rings", False)),
            )
        elif cname == "bubbles":
            cnt = max(4, int(p.get("count", 20)))
            height = float(p.get("height", 140.0))
            amount = float(p.get("amount", 1.0))
            if p.get("wide", 0) >= 0.5:
                canvas.bubbles(color="cyan", count=cnt, height=height, amount=amount)
            else:
                canvas.bubbles_at(
                    mouse.x, mouse.y, color="cyan",
                    count=cnt, height=height, amount=amount,
                )
        elif cname == "flash":
            canvas.flash(0.9)
        elif cname == "shake":
            canvas.shake(18)
        elif cname == "glitch":
            canvas.glitch(1.2)
        elif _is_cover_mode(cname):
            p = _read_params()
            dur = float(p.get("duration", 0.5))
            angle = float(p.get("angle", 90.0))
            style = cname.split("_", 1)[-1]  # fade | wipe | iris
            if canvas.covered > 0.01:
                canvas.fade_in(dur, style=style, angle=angle)
            else:
                canvas.fade_out(
                    dur, style=style, angle=angle,
                    center=(mouse.x, mouse.y),
                )
            _hud()
    # hit_at stream: a boss under a stream of shots (~14 hits/s while held).
    if cname == "hit_at" and down and _mouse_was_down and not _over_ui():
        p = _read_params()
        if p.get("stream", False):
            _stream_acc += dt
            while _stream_acc >= 0.07:
                _stream_acc -= 0.07
                _fire_hit(
                    p,
                    mouse.x + random.uniform(-10.0, 10.0),
                    mouse.y + random.uniform(-10.0, 10.0),
                )
    _mouse_was_down = down

    if args.bench:
        now = time.perf_counter()
        if _bench_t0 is None:
            _bench_t0 = now
            return
        elapsed = now - _bench_t0
        if not _bench_warm:
            if elapsed >= args.warmup:
                _bench_warm = True
                _bench_t0 = now
                _bench_frames.clear()
            return
        _bench_frames.append(dt if dt > 0 else 1e-3)
        if elapsed >= args.duration:
            if _bench_frames:
                avg = sum(_bench_frames) / len(_bench_frames)
                fps = 1.0 / avg if avg > 0 else 0.0
            else:
                fps = 0.0
            print(
                f"app_fx_lab bench canvas={CANVAS_MODES[_c_idx][0]} "
                f"visual={VISUAL_MODES[_l_idx][0]} n={args.n} Q={args.quality} "
                f"FPS: {fps:.2f}",
                flush=True,
            )
            try:
                import glfw
                fw = ScenaFramework.get_instance()
                glfw.set_window_should_close(fw._window, True)
            except Exception:
                sys.exit(0)

canvas.framerate = "max"
run()
