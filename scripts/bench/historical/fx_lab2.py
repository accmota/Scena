"""FROZEN historical benchmark — do not add features.

app_fx_lab.py — visual lab: canvas post FX and shape visuals (independent).

Background: examples/media/backgrounds/bg3.jpg
Shapes: mixed kinds/sizes/motion, half opaque + half varying alphas;
~20 colorful gradient fills and gradient strokes on half the Lines.

Controls
  LEFT/RIGHT   cycle canvas-wide post effects
  , / .        cycle shape visuals
  Space        both none (baseline)
  Click        hit feedback (ripple / wave / explosion / burst / flash / shake / glitch)
  Ctrl+Shift+3 quality profiles

Usage
-----x
    python scripts/app_fx_lab.py
    python scripts/app_fx_lab.py --visual flame --canvas none
    python scripts/app_fx_lab.py --bench --canvas none --visual none --duration 2
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
parser.add_argument("--bench", action="store_true", help="uncapped FPS then exit")
parser.add_argument("--duration", type=float, default=2.0, help="bench seconds")
parser.add_argument("--warmup", type=float, default=0.4, help="bench warmup")
args, _ = parser.parse_known_args()

W, H = 1200, 800
_MEDIA_NOTE = "cwd-relative examples/media/backgrounds/bg3.jpg, examples/media/k-textures/floor_wood_planks.png"
BG2 = "examples/media/backgrounds/bg3.jpg"
TEX2 = "examples/media/k-textures/floor_wood_planks.png"
TEX_SPRITE = Texture(TEX2, fit="cover")
TEX_TILE = Texture(TEX2, fit="tile", tile_size=40)

init(width=W, height=H, window_scale=0.75, title="Scena FX lab")
canvas.fx_quality = args.quality
canvas.batch_shared_filters = True
Wallpaper(BG2, fit="cover")
# Shared 2½D vanishing point for Extrude (top-center of design space).
set_extrude_focus(W * 0.5, H * 0.06)

# --------------------------------------------------------------------------- 
# Scene: diverse movers (geometry + alpha + some pure Lines)
# ---------------------------------------------------------------------------
COLORS = (
    "cyan", "magenta", "gold", "lime", "orange",
    "dodger blue", "orchid", "white", "tomato", "green",
)

# Colorful fill / stroke ramps: presets + custom multi-stops, varied GradientType kinds.
_FILL_GRAD_RECIPES = (
    (("plasma",), GradientType.RADIAL, 0.0),
    (("rainbow",), GradientType.SWEEP, 40.0),
    (("sunset",), GradientType.LINEAR, 90.0),
    (("viridis",), GradientType.LINEAR, 35.0),
    (("coolwarm",), GradientType.LINEAR, 0.0),
    (("ocean",), GradientType.RADIAL, 0.0),
    (("ember",), GradientType.RADIAL, 0.0),
    (("ice",), GradientType.LINEAR, 120.0),
    (("toxic",), GradientType.LINEAR, 55.0),
    (("magenta", "cyan", "gold"), GradientType.LINEAR, 25.0),
    (("lime", "dodger blue", "orchid"), GradientType.RADIAL, 0.0),
    (("tomato", "gold", "orange"), GradientType.LINEAR, 70.0),
    (("navy", "cyan", "white"), GradientType.RADIAL, 0.0),
    (("crimson", "magenta", "violet"), GradientType.SWEEP, 15.0),
    (("green", "lime", "gold"), GradientType.LINEAR, 140.0),
    (("heat",), GradientType.RADIAL, 0.0),
    (("forest",), GradientType.LINEAR, 80.0),
    (("underwater",), GradientType.RADIAL, 0.0),
    (("cyan", "dodger blue", "navy"), GradientType.LINEAR, 45.0),
    (("gold", "orange", "crimson"), GradientType.RADIAL, 0.0),
)
_LINE_GRAD_RECIPES = (
    (("magenta", "cyan"), GradientType.LINEAR, 0.0),
    (("gold", "orange", "tomato"), GradientType.LINEAR, 90.0),
    (("lime", "dodger blue"), GradientType.LINEAR, 45.0),
    (("rainbow",), GradientType.LINEAR, 30.0),
    (("plasma",), GradientType.LINEAR, 120.0),
    (("white", "cyan", "magenta"), GradientType.LINEAR, 60.0),
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
        shp = EquilateralTriangle(center=(x, y), radius=size * 0.55, angle=ang)
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

hud = Label(
    text="",
    x1=320, y1=H - 28,
    font_size=18,
    color=Color(0.95, 0.97, 1.0, 0.95),
)
hint = Label(
    text="←/→ canvas · ,/. visual · Space both none · click: hit/wave/explosion/burst",
    x1=320, y1=H - 52,
    font_size=14,
    color=Color(0.8, 0.85, 0.95, 0.85),
)
canvas.layers.set_post_fx("top", False)

# ---------------------------------------------------------------------------
# Param panel — remappable Slider ranges (min/max mutable after create)
# Spec entries:
#   ("name", lo, hi, default)            → float slider
#   ("name", lo, hi, default, True)      → int slider
#   ("name", "bool", default)            → checkbox
# ---------------------------------------------------------------------------
N_SLIDERS = 6
N_CHECKS = 4
PANEL_X = 16
PANEL_TOP = H - 88
ROW = 34

_panel_sliders: list[Slider] = []
_panel_checks: list[CheckBox] = []
for i in range(N_SLIDERS):
    s = Slider(
        label="—",
        x1=PANEL_X,
        y1=PANEL_TOP - i * ROW,
        width=290,
        min_value=0.0,
        max_value=100.0,
        initial=50.0,
        show_value=True,
    )
    s.enabled = False
    _panel_sliders.append(s)
for i in range(N_CHECKS):
    c = CheckBox(
        label="—",
        x1=PANEL_X,
        y1=PANEL_TOP - (N_SLIDERS + i) * ROW,
        size=22,
        initial=False,
    )
    c.enabled = False
    _panel_checks.append(c)

# Live effect handle + optional shape-filter rebuild callable.
# `_live` is whichever object the current panel is bound to (look or post FX).
# `_canvas_live` is always the canvas post effect, so cycling looks cannot
# steal it and leftover sliders cannot setattr onto Prism / Bloom / …
_live = None
_canvas_live = None
_rebuild = None  # callable(**params) -> FilterEffect | None
_param_map: list[tuple] = []  # (widget, key, kind) kind: float|int|bool
_last_shape_key = None
_pyro_labels = []
_pyro_acc = 0.0
_bench_auto_acc = 0.0
_PYRO_ZONES = (
    # (u, v, kind) — u,v in 0..1 design space
    (0.35, 0.55, "explosion"),
    (0.65, 0.55, "burst"),
)


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
    s._slider_x = s.x1 + s._handle_radius + label_space
    s.data.value = float(int(round(val)) if only_int else val)
    s.enabled = True


def _setup_check(c: CheckBox, label: str, val: bool):
    c.label = label
    c.data.value = bool(val)
    c._text_width = c._theme.default_font.measureText(c.label) if c.label else 0
    c._total_width = c.size + 5 + c._text_width
    c.x2 = c.x1 + c._total_width
    c.enabled = True


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
        s.enabled = False
    for c in _panel_checks[ci:]:
        c.enabled = False


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


def _clear_shape_fx():
    for m in movers:
        # visual=None resets package filters; clear filters before host color restore.
        m["shape"].visual = None
        m["shape"].fill_filter = None
        m["shape"].line_filter = None
        try:
            m["shape"].clear_transients()
        except Exception:
            pass
        _restore_base_paint(m)
    _hide_water_pool()


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
        m["shape"].fill_filter = fx
        _restore_base_paint(m)


def _apply_shared_look(look):
    """Apply visual to all movers; restore host fill/line (incl. gradients).

    Host-preserving looks (Glow, Shadow, Tail, Beat, MultiBorder, …) must not
    be preceded by ``set_color(base_color)`` — that wipes gradient materials.
    After a *multipass* Recipe assign, restore again so a shared recipe with
    ``color=`` seed does not flatten every mover to one solid. Compiled GlowRim
    highs (ElectricField, Bolt) rewrite fill/line/filters — restoring
    host paint after ``apply`` wipes the halo package. Costumes that own a
    standard outline keep the width installed by ``apply``.
    """
    owns_outline = _visual_owns_outline(look)
    restore_host = _is_recipe_visual(look) and bool(getattr(look, "_is_multipass", True))
    for m in movers:
        shp = m["shape"]
        shp.fill_filter = None
        shp.line_filter = None
        _restore_base_paint(m)
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
        _restore_base_paint(m)
    _water_pool.visible = True
    _water_pool.visual = look
    _water_pool.angle = 0.0


def _hide_water_pool():
    _water_pool.visible = False
    _water_pool.visual = None


def _dispatch_look(fx):
    """Apply a visual / filter / procedural fill to the scene the right way."""
    if fx is None:
        return
    from scena.style import ProceduralFill
    from scena.visuals import Visual
    if isinstance(fx, ProceduralFill):
        _hide_water_pool()
        _apply_shared_procedural_fill(fx)
        return
    if isinstance(fx, Visual):
        name = type(fx).__name__
        if name == "Water":
            _apply_water_look(fx)
        else:
            _hide_water_pool()
            if name in (
                "DashRing", "Halo", "HaloFill", "HaloSoft", "HaloLine", "GearShell",
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
        ("intensity", 0.0, 2.5, 1.0),
    ],
    "cheapglow": [
        ("radius", 0.0, 48.0, 12.0),
        ("sigma", 0.0, 40.0, 6.0),
        ("intensity", 0.0, 2.5, 1.0),
    ],
    "shadow": [("offset", 0.0, 40.0, 8.0), ("sigma", 0.0, 30.0, 5.0)],
    "blur": [("sigma", 0.0, 30.0, 4.0)],
    "dilate": [("radius", 0.0, 20.0, 4.0)],
    "erode": [("radius", 0.0, 12.0, 2.5)],
    "neon": [("intensity", 0.2, 2.5, 1.0), ("width", 1.0, 10.0, 3.0)],
    "multiborder": [("layers", 1, 4, 3, True), ("spread", 0.02, 0.5, 0.3)],
    "longshadow": [
        ("depth", 8.0, 80.0, 36.0),
        ("steps", 3, 7, 5, True),
        ("darken", 0.0, 1.0, 0.42),
    ],
    "shieldring": [("speed", 0.1, 4.0, 1.0), ("width", 1.0, 6.0, 2.0)],
    "aura": [("intensity", 0.2, 2.5, 1.0)],
    "aura_fill": [("intensity", 0.2, 2.5, 1.0)],
    "phantom": [("intensity", 0.2, 2.5, 1.0)],
    "plasmafield": [("speed", 0.2, 3.0, 1.2)],
    "electricfield": [("amount", 1.0, 16.0, 5.0), ("seed_rate", 1.0, 30.0, 14.0)],
    "shield_bubble": [("intensity", 0.3, 2.0, 1.0), ("speed", 0.1, 3.0, 1.0)],
    "shield_nebula": [("intensity", 0.3, 2.0, 1.0), ("speed", 0.1, 3.0, 1.0)],
    "shield_nebula_ember": [("intensity", 0.3, 2.0, 1.0), ("speed", 0.1, 3.0, 1.0)],
    "shield_nebula_void": [("intensity", 0.3, 2.0, 1.0), ("speed", 0.1, 3.0, 1.0)],
    "shield_molten": [("intensity", 0.3, 2.0, 1.0), ("speed", 0.2, 3.0, 1.15)],
    "shield_bands": [("intensity", 0.3, 2.0, 1.0), ("speed", 0.0, 2.0, 0.35)],
    "shield_vortex": [("intensity", 0.3, 2.0, 1.0), ("speed", 0.2, 3.0, 1.0)],
    "shield_cracks": [("intensity", 0.3, 2.0, 1.0), ("speed", 0.1, 2.5, 0.7)],
    "shield_cracks_frost": [("intensity", 0.3, 2.0, 1.0), ("speed", 0.1, 2.5, 0.7)],
    "organic": [("amount", 0.5, 10.0, 2.5), ("speed", 0.1, 4.0, 1.0)],
    "tracer": [("speed", 0.1, 4.0, 1.0), ("gap", 4.0, 40.0, 12.0), ("width", 1.0, 10.0, 2.4)],
    "electricbolt": [("amount", 1.0, 16.0, 5.0), ("seed_rate", 1.0, 30.0, 14.0)],
    "swell": [("amount", 0.2, 2.0, 1.0), ("speed", 0.1, 3.0, 1.0)],
    "water": [("amount", 0.2, 2.0, 1.0), ("speed", 0.1, 3.0, 1.0)],
    "flame": [("amount", 0.2, 2.0, 1.0), ("speed", 0.2, 3.0, 1.2), ("border", "bool", False)],
    "metal": [("intensity", 0.2, 2.0, 1.0)],
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
    "laser": [("intensity", 0.2, 2.5, 1.0), ("width", 1.0, 8.0, 2.5)],
    "ink": [("amount", 0.5, 6.0, 1.8), ("speed", 0.0, 2.0, 0.6)],
    "ink_bleed": [("amount", 0.3, 4.0, 1.0)],
    "sphere": [("intensity", 0.2, 2.0, 1.0), ("speed", 0.0, 2.0, 0.5)],
    "edgeglow": [("intensity", 0.2, 2.5, 1.0), ("width", 1.0, 12.0, 4.0), ("darken", 0.0, 0.8, 0.35)],
    "gel": [("intensity", 0.2, 2.5, 1.0)],
    "wave": [("amount", 0.2, 2.0, 1.0), ("speed", 0.1, 3.0, 1.0)],
    "aurora": [("amount", 0.2, 2.0, 1.0), ("speed", 0.1, 3.0, 0.9)],
    "tail": [
        ("angle", 0.0, 360.0, 210.0),
        ("velocity", 0.2, 3.0, 1.0),
        ("intensity", 0.2, 2.5, 1.0),
    ],
    "beat": [("amount", 0.02, 0.35, 0.08), ("speed", 0.2, 3.0, 1.0)],
    "insetrim": [
        ("fill_scale", 0.5, 1.0, 0.8),
        ("intensity", 0.2, 2.5, 0.3),
        ("border_width", 0.0, 12.0, 6.0),
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
    "rays": [
        ("weight", 0.0, 1.0, 0.35),
        ("decay", 0.5, 0.99, 0.86),
        ("exposure", 0.2, 4.0, 1.8),
    ],
    "trails": [("fade", 0.5, 0.99, 0.90), ("opacity", 0.0, 1.0, 1.0)],
    "shake": [("amount", 0.0, 40.0, 5.0), ("speed", 1.0, 80.0, 28.0)],
    "flash": [("intensity", 0.0, 1.0, 0.0), ("decay", 0.5, 10.0, 3.2)],
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
    _rebuild = lambda **kw: Laser(intensity=kw.get("intensity", 1.0))
    _configure_panel(_P["laser"])
    _sync_live_params()


@_lmode("glow", "Glow")
def _l_glow():
    global _rebuild
    # color=None keeps each mover's host paint; shared GlowFilter under the visual.
    _rebuild = lambda **kw: Glow(
        radius=kw.get("radius", 12.0),
        sigma=kw.get("sigma", 10.0),
        intensity=kw.get("intensity", 1.0),
    )
    _configure_panel(_P["glow"])
    _sync_live_params()


@_lmode("cheapglow", "CheapGlow")
def _l_cheapglow():
    global _rebuild
    _rebuild = lambda **kw: CheapGlow(
        radius=kw.get("radius", 12.0),
        sigma=kw.get("sigma", 6.0),
        intensity=kw.get("intensity", 1.0),
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
    _rebuild = lambda **kw: Neon(intensity=kw.get("intensity", 1.0), width=kw.get("width", 3.0))
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
        steps=int(kw.get("steps", 5)),
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
        amount=kw.get("amount", 5), seed_rate=kw.get("seed_rate", 14),
    )
    _configure_panel(_P["electricfield"])
    _sync_live_params()

@_lmode("electricbolt", "ElectricBolt")
def _l_electricbolt():
    global _rebuild
    _rebuild = lambda **kw: ElectricBolt(amount=kw.get("amount", 5), seed_rate=kw.get("seed_rate", 14))
    _configure_panel(_P["electricbolt"])
    _sync_live_params()


@_lmode("shield_bubble", "Shield bubble (orb)")
def _l_sh_bubble():
    global _rebuild
    _rebuild = lambda **kw: Shield(
        style="bubble", intensity=kw.get("intensity", 1.0), speed=kw.get("speed", 1.0),
    )
    _configure_panel(_P["shield_bubble"])
    _sync_live_params()


@_lmode("shield_nebula", "Shield nebula classic (orb)")
def _l_sh_nebula():
    global _rebuild
    _rebuild = lambda **kw: Shield(
        style="nebula", intensity=kw.get("intensity", 1.0), speed=kw.get("speed", 1.0),
        palette="classic",
    )
    _configure_panel(_P["shield_nebula"])
    _sync_live_params()


@_lmode("shield_nebula_ember", "Shield nebula ember (orb)")
def _l_sh_nebula_ember():
    global _rebuild
    _rebuild = lambda **kw: Shield(
        style="nebula", intensity=kw.get("intensity", 1.0), speed=kw.get("speed", 1.0),
        palette="ember",
    )
    _configure_panel(_P["shield_nebula_ember"])
    _sync_live_params()


@_lmode("shield_nebula_void", "Shield nebula void (orb)")
def _l_sh_nebula_void():
    global _rebuild
    _rebuild = lambda **kw: Shield(
        style="nebula", intensity=kw.get("intensity", 1.0), speed=kw.get("speed", 1.0),
        palette="void",
    )
    _configure_panel(_P["shield_nebula_void"])
    _sync_live_params()


@_lmode("shield_molten", "Shield molten (orb)")
def _l_sh_molten():
    global _rebuild
    _rebuild = lambda **kw: Shield(
        style="molten", intensity=kw.get("intensity", 1.0), speed=kw.get("speed", 1.15),
    )
    _configure_panel(_P["shield_molten"])
    _sync_live_params()


@_lmode("shield_bands", "Shield bands (orb, live host color)")
def _l_sh_bands():
    global _rebuild
    # color=None → samples each orb host fill as primary tint
    _rebuild = lambda **kw: Shield(
        style="bands", intensity=kw.get("intensity", 1.0), speed=kw.get("speed", 0.35),
    )
    _configure_panel(_P["shield_bands"])
    _sync_live_params()


@_lmode("shield_halo", "Shield halo (plasma + blur rim)")
def _l_sh_halo():
    global _rebuild
    _rebuild = lambda **kw: Shield(
        style="halo",
        intensity=kw.get("intensity", 1.0),
        speed=kw.get("speed", 1.0),
    )
    _configure_panel(_P.get("shield_bubble") or _P.get("glow") or {})
    _sync_live_params()

@_lmode("shield_vortex", "Shield vortex (orb, live host color)")
def _l_sh_vortex():
    global _rebuild
    _rebuild = lambda **kw: Shield(
        style="vortex", intensity=kw.get("intensity", 1.0), speed=kw.get("speed", 1.0),
    )
    _configure_panel(_P["shield_vortex"])
    _sync_live_params()


@_lmode("shield_cracks", "Shield cracks magma (orb)")
def _l_sh_cracks():
    global _rebuild
    _rebuild = lambda **kw: Shield(
        style="cracks", intensity=kw.get("intensity", 1.0), speed=kw.get("speed", 0.7),
        palette="magma",
    )
    _configure_panel(_P["shield_cracks"])
    _sync_live_params()


@_lmode("shield_cracks_frost", "Shield cracks frost (orb)")
def _l_sh_cracks_frost():
    global _rebuild
    _rebuild = lambda **kw: Shield(
        style="cracks", intensity=kw.get("intensity", 1.0), speed=kw.get("speed", 0.7),
        palette="frost",
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
    _rebuild = lambda **kw: Metal(intensity=kw.get("intensity", 1))
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
    _rebuild = lambda **kw: Sphere(intensity=kw.get("intensity", 1.0), speed=kw.get("speed", 0.5))
    _configure_panel(_P["sphere"])
    _sync_live_params()


@_lmode("edgeglow", "Rim")
def _l_edge():
    global _rebuild
    _rebuild = lambda **kw: Rim(
        intensity=kw.get("intensity", 1.0),
        width=kw.get("width", 4.0),
        darken=kw.get("darken", 0.35),
    )
    _configure_panel(_P["edgeglow"])
    _sync_live_params()


@_lmode("gel", "Gel")
def _l_gel():
    global _rebuild
    _rebuild = lambda **kw: Gel(intensity=kw.get("intensity", 1.0))
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
        velocity=kw.get("velocity", 1.0),
        intensity=kw.get("intensity", 1.0),
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
        bw = float(kw.get("border_width", 6.0) or 0.0)
        return InsetRim(
            fill_scale=kw.get("fill_scale", 0.8),
            border_width=None if bw < 0.5 else bw,
            intensity=kw.get("intensity", 0.3),
        )
    _rebuild = _mk
    _configure_panel(_P["insetrim"])
    _sync_live_params()


@_lmode("aura", "Halo")
def _l_aura():
    global _rebuild
    _rebuild = lambda **kw: Halo(intensity=kw.get("intensity", 1.0))
    _configure_panel(_P["aura"])
    _sync_live_params()


@_lmode("aura_fill", "Halo fill (Halo + solid fill)")
def _l_aura_fill():
    global _rebuild
    _rebuild = lambda **kw: Halo(style="fill", intensity=kw.get("intensity", 1.0))
    _configure_panel(_P["aura_fill"])
    _sync_live_params()


@_lmode("phantom", "Halo soft (batched glow fill)")
def _l_phantom():
    global _rebuild
    _rebuild = lambda **kw: Halo(style="soft", intensity=kw.get("intensity", 1.0))
    _configure_panel(_P["phantom"])
    _sync_live_params()

# Evaluation cluster first, then the rest of the catalog.
_EVAL_VISUALS = (
    "aura",
    "aura_fill",
    "phantom",
    "neon",
    "laser",
    "electricfield",
    "plasmafield",
    "shield_halo",
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
if args.visual in _visual_names:
    _l_idx = _visual_names.index(args.visual)


def _hud():
    cn, cl, _ = CANVAS_MODES[_c_idx]
    ln, ll, _ = VISUAL_MODES[_l_idx]
    q = canvas.fx_quality
    qn = q.value if q is not None else "?"
    hud.text = f"canvas: {cl}  |  visual: {ll}   Q={qn}"


def _apply_canvas(i: int):
    global _c_idx, _last_shape_key
    _c_idx = i % len(CANVAS_MODES)
    name, label, fn = CANVAS_MODES[_c_idx]
    fn()
    # Prefer shape-look params when a visual is active — do not clobber user sliders.
    look_name = VISUAL_MODES[_l_idx][0]
    if look_name == "none" or look_name not in _P:
        _configure_panel(_P.get(name, []))
        _last_shape_key = None
        _sync_live_params()
    _hud()


def _apply_visual(i: int):
    global _l_idx, _last_shape_key, _rebuild, _live
    _l_idx = i % len(VISUAL_MODES)
    name, label, fn = VISUAL_MODES[_l_idx]
    _last_shape_key = None
    if name == "none":
        _rebuild = None
        _hide_water_pool()
        _clear_shape_fx()
        _live = _canvas_live
        cn = CANVAS_MODES[_c_idx][0]
        _configure_panel(_P.get(cn, []))
        _sync_live_params()
    else:
        fn()  # configures visual panel + rebuild + applies
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
    global _pyro_acc, _bench_auto_acc
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

    # Pin water pool (no spin, fixed bar)
    if _water_pool.visible:
        _water_pool.angle = 0.0
        _water_pool.move_to(W * 0.5, H * 0.28)

    # Extrude vanishing point follows the mouse (global set_extrude_focus API).
    # Skip while over UI sliders so scrubbing still works cleanly.
    if VISUAL_MODES[_l_idx][0] == "longshadow" and not _over_ui():
        set_extrude_focus(mouse.x, mouse.y)

    if not args.bench:
        if keyp.once("LEFT") or keyp.once("["):
            _apply_canvas(_c_idx - 1)
        if keyp.once("RIGHT") or keyp.once("]"):
            _apply_canvas(_c_idx + 1)
        if keyp.once("Z") or keyp.once("-"):
            _apply_visual(_l_idx - 1)
        if keyp.once("X") or keyp.once("="):
            _apply_visual(_l_idx + 1)
        if keyp.once("SPACE"):
            _apply_canvas(_canvas_names.index("none"))
            _apply_visual(_visual_names.index("none"))

    cname = CANVAS_MODES[_c_idx][0]
    lname = VISUAL_MODES[_l_idx][0]
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
    if down and not _mouse_was_down and not _over_ui() and not args.bench:
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

set_framerate(FrameRateControl.NONE)
run()
