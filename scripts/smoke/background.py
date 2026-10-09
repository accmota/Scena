"""
background.py — smoke: every wallpaper / ambient / fly field.

A/S cycle modes. Arrows pan; Shift+←/→ rotate; Shift+↑/↓ zoom.
Warp mode: SpatialFx gallery on one screen; sliders tune the live vortex.
Tunnel / StarFly: click sets vanishing point; P toggles pan_response bank.
"""
from scena import *
import sys as _sys
_sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from _hud import SmokeHud, apply_camera

init(width=1400, height=900, window_scale=0.8, title="Smoke — background")
canvas.set_origin("center")

BG1 = "../../examples/media/images/bg1.jpeg"

# Scene markers so pan/zoom relation is obvious.
Circle(center=(0, 0), radius=28).set_color("cyan")
Circle(center=(280, 120), radius=40).set_color("gold")
Rect(center=(-220, -80), width=120, height=70, angle=12).set_color("magenta")

hud = SmokeHud(
    title="Background fields",
    expect="A/S cycles every wallpaper / ambient / fly field",
    keys="A/S mode  ·  Warp: sliders  ·  fly: click VP · P bank  ·  arrows pan  ·  Shift+←/→ rotate  ·  Shift+↑/↓ zoom  ·  R reset  ·  C clear  ·  B base",
    status="",
)

# Warp SpatialFx gallery (one mode): sliders tune the live vortex.
_WARP_SLIDER_SPEC = [
    ("radius", 20.0, 220.0, 88.0),
    ("amount", 0.0, 2.0, 1.0),
    ("speed", 0.0, 3.0, 1.1),
    ("twist", 0.0, 2.0, 0.45),
    ("spokes", 3.0, 24.0, 8.0),
    ("core", 0.0, 1.5, 1.0),
    ("spin", -2.0, 2.0, 0.0),
    ("glow", 0.0, 2.0, 0.8),
]
_warp_items = []
_warp_live = None
_warp_sliders = []
_warp_into = None
_fly_live = None
_mouse_was_down = False
_PANEL_X = -680
_PANEL_TOP = -40

from scena.orchestration import ScenaFramework
_theme = ScenaFramework.get_instance().widget_manager.widget_theme
_theme._ensure()
_ROW = max(_theme.row_height, 2 * _theme.slider_handle_radius) + _theme.stack_gap

for i, (name, lo, hi, default) in enumerate(_WARP_SLIDER_SPEC):
    s = Slider(
        label=name,
        top_left=(_PANEL_X, _PANEL_TOP - i * _ROW + 28),
        width=260,
        min_value=lo,
        max_value=hi,
        initial=default,
        show_value=True,
    )
    s.visible = False
    _warp_sliders.append(s)

_warp_into = CheckBox(
    label="into",
    top_left=(_PANEL_X, _PANEL_TOP - len(_WARP_SLIDER_SPEC) * _ROW + 20),
    initial=True,
)
_warp_into.visible = False

MODES = []

_DAY = (0.12, 0.28, 0.48)
_NIGHT = (0.02, 0.03, 0.06)
_DARK = (0.04, 0.04, 0.05)
_WARM = (0.08, 0.04, 0.02)
_SPACE = (0.01, 0.02, 0.05)


def _mode(label):
    def deco(fn):
        MODES.append((label, fn))
        return fn

    return deco


def _clear_extras():
    canvas.background.clear()


def _solo(rgb, make_field):
    """One ambient field alone on a flat solid base."""
    _clear_extras()
    canvas.background = rgb
    make_field()


def _destroy_warp_gallery():
    global _warp_live
    for obj in _warp_items:
        try:
            obj.destroy()
        except Exception:
            pass
    _warp_items.clear()
    _warp_live = None
    for s in _warp_sliders:
        s.visible = False
    _warp_into.visible = False


def _show_warp_sliders():
    for s in _warp_sliders:
        s.visible = True
    _warp_into.visible = True


def _read_warp_sliders():
    params = {}
    for s, (name, _, _, _) in zip(_warp_sliders, _WARP_SLIDER_SPEC):
        params[name] = float(s.value)
    params["into"] = bool(_warp_into.value)
    return params


def _apply_warp_sliders(fx, params):
    fx.radius = params["radius"]
    fx.amount = params["amount"]
    fx.speed = params["speed"]
    fx.twist = params["twist"]
    fx.spokes = params["spokes"]
    fx.core = params["core"]
    fx.spin = params["spin"]
    fx.glow = params["glow"]
    fx.into = params["into"]


def _radial_fly():
    """Live Tunnel / StarFly, or None."""
    return _fly_live if isinstance(_fly_live, (Tunnel, StarFly)) else None


def _fly(make_field):
    global _fly_live
    canvas.background = (0.0, 0.0, 0.02)
    _fly_live = make_field()
    canvas.set_fly(_fly_live)


# --- base / wallpaper sugar (simplest first) ---------------------------------

@_mode("Solid RGB  canvas.background = (0.05, 0.07, 0.12)")
def _m_rgb():
    _clear_extras()
    canvas.background = (0.05, 0.07, 0.12, 1)


@_mode("Solid Color  canvas.background = Color('navy')")
def _m_color():
    _clear_extras()
    canvas.background = Color("navy")


@_mode("Gradient base")
def _m_grad_helper():
    _clear_extras()
    canvas.background = Gradient(
        (0.05, 0.08, 0.18), (0.12, 0.04, 0.2), (0.02, 0.02, 0.56),
        angle=90,
    )


@_mode("SkyGradient('day') base only")
def _m_skygrad():
    _clear_extras()
    SkyGradient("day")


@_mode("Image cover + parallax")
def _m_img_cover():
    _clear_extras()
    Wallpaper(BG1, fit="cover", pan_response=0.2, zoom_response=0.4)


@_mode("Image tile base")
def _m_img_tile():
    _clear_extras()
    Wallpaper(
        BG1, fit="tile", tile_size=1400 // 4, tile_mode="mirror",
        zoom_response=0.5,
        pan_response=0.5,
    )


# --- ambient extras (one at a time) ------------------------------------------

@_mode("Clouds")
def _m_clouds():
    _solo(_DAY, lambda: Clouds(amount=0.55))


@_mode("Stars")
def _m_stars():
    _solo(_NIGHT, lambda: Stars(density=0.95, twinkle=0.4))


@_mode("Stardust")
def _m_stardust():
    _solo(_NIGHT, lambda: Stardust(alpha=0.7))


@_mode("Chromadust rainbow")
def _m_chromadust():
    _solo(_NIGHT, lambda: Chromadust(alpha=0.75, hue_speed=0.35))


@_mode("Chromadust red→blue")
def _m_chromadust_plasma():
    _solo(_NIGHT, lambda: Chromadust(Gradient("red", "blue"), alpha=0.75, hue_speed=0.3))


@_mode("Nebuladust")
def _m_nebuladust():
    _solo(_NIGHT, lambda: Nebuladust(alpha=0.75, color="light blue", color2="white", pan_response=1.0))


@_mode("Borealis")
def _m_borealis():
    _solo(_NIGHT, lambda: Borealis(height=0.65, alpha=0.9))


@_mode("Plasma")
def _m_plasma():
    _solo(_DARK, lambda: Plasma(color="orchid", speed=0.5, alpha=0.65))


@_mode("Mist")
def _m_mist():
    _solo(_DAY, lambda: Mist(amount=0.85, band=0.4, alpha=0.75))


@_mode("Debris")
def _m_debris():
    _solo(_NIGHT, lambda: Debris(density=0.85, pan_response=0.4))


@_mode("Embers")
def _m_embers():
    _solo(_WARM, lambda: Embers(density=0.9, rise=0.85))


@_mode("WindStreaks")
def _m_wind():
    _solo(_DARK, lambda: WindStreaks(density=0.85, length=1.5, angle=0.0, speed=1.5, glow=1.1))


@_mode("Ground")
def _m_ground():
    _clear_extras()
    canvas.background = (0.45, 0.65, 0.85)
    Ground(color="blue", horizon=0.42, pan_response=0.9)
    


@_mode("Lattice")
def _m_lattice():
    _solo(_NIGHT, lambda: Lattice(fold="hex", layers=2, alpha=0.55))


@_mode("Nebula")
def _m_nebula():
    _solo(_NIGHT, lambda: Nebula(alpha=0.65))


@_mode("ChurningClouds")
def _m_churning():
    _solo(_SPACE, lambda: ChurningClouds())


@_mode("FilamentField")
def _m_filament():
    _solo(_DARK, lambda: FilamentField())


# --- Warp SpatialFx gallery + tunnels ---------------------------------------

@_mode("Warp gallery (SpatialFx)")
def _m_warp():
    _clear_extras()
    canvas.background = _SPACE
    recipes = (
        ("default", (-450, 140), dict(radius=70)),
        ("hyperspace", (0, 160), dict(
            radius=80, color="cyan", spokes=8, speed=1.4, twist=0.2, core=1.2,
        )),
        ("sink", (450, 140), dict(
            radius=78, color="navy", color2="black", core=0.0,
            twist=1.3, into=False, glow=0.35,
        )),
        ("portal", (-450, -180), dict(
            radius=72, color="orchid", color2="gold",
            spin=0.7, twist=0.9, core=0.15, glow=1.0,
        )),
    )
    for label, pos, kw in recipes:
        fx = Warp(center=pos, **kw)
        cap = Text(
            text=label,
            center=(pos[0], pos[1] - 95),
            font_size=14,
            color=Color(0.7, 0.75, 0.85, 1),
        )
        _warp_items.extend((fx, cap))
    live = Warp(
        center=(280, -180),
        radius=88,
        color="cyan",
        spokes=8,
        speed=1.1,
        twist=0.45,
    )
    live_cap = Text(
        text="live (sliders)",
        center=(280, -180 - 110),
        font_size=14,
        color=Color(1.0, 0.85, 0.35, 1),
    )
    _warp_items.extend((live, live_cap))
    global _warp_live
    _warp_live = live
    for s, (name, lo, hi, default) in zip(_warp_sliders, _WARP_SLIDER_SPEC):
        s.min_value = lo
        s.max_value = hi
        s.data.value = default
        s.label = name
    _warp_into.data.value = True
    _show_warp_sliders()


@_mode("Floor")
def _m_floor():
    _fly(lambda: Floor(speed=1.0))


@_mode("Road")
def _m_road():
    _fly(lambda: Road(speed=1.2, grid=1.85))


@_mode("Tunnel")
def _m_startunnel():
    _fly(lambda: Tunnel(speed=1.2, density=1.2))


@_mode("StarFly")
def _m_starfield():
    _fly(lambda: StarFly(speed=1.5, density=1.4))


@_mode("PlanetFly")
def _m_planetfly():
    _fly(lambda: PlanetFly(speed=1.0, relief=1.0, fog=0.5, size=0.55, bright=1.35))


# --- composed stacks (exactly three) -----------------------------------------

@_mode("Stack  Day — sky + clouds + mist")
def _m_stack_day():
    _clear_extras()
    SkyGradient("day")
    Clouds(pan_response=0.1, amount=0.5)
    Mist(band=0.35, pan_response=0.2)


@_mode("Stack  Night — stars + borealis")
def _m_stack_night():
    _clear_extras()
    SkyGradient("night")
    Stars(density=0.9, twinkle=0.35, pan_response=0.02)
    Borealis(height=0.55, pan_response=0.1, alpha=0.8)


@_mode("Stack  Space — stars + churning clouds + filaments")
def _m_stack_space():
    _clear_extras()
    SkyGradient("space")
    Stars(density=0.85, pan_response=0.02)
    ChurningClouds(alpha=0.55, pan_response=0.06)
    FilamentField(alpha=0.4, pan_response=0.18)


_mode_i = 0


def _apply():
    global _mode_i, _fly_live
    _destroy_warp_gallery()
    _fly_live = None
    label, fn = MODES[_mode_i]
    fn()
    hud.title = f"Background — [{_mode_i + 1}/{len(MODES)}]"
    hud.expect = label
    extra = ""
    if _warp_live is not None:
        extra = "  ·  sliders tune live Warp"
        hud.keys = (
            "A/S mode  ·  Warp: sliders  ·  arrows pan  ·  Shift+←/→ rotate  ·  "
            "Shift+↑/↓ zoom  ·  R reset  ·  C clear  ·  B base"
        )
    elif _radial_fly() is not None:
        extra = "  ·  click vanishing point  ·  P pan_response bank"
        hud.keys = (
            "A/S mode  ·  click VP  ·  P bank  ·  arrows pan  ·  "
            "Shift+←/→ rotate  ·  Shift+↑/↓ zoom  ·  R reset  ·  C clear  ·  B base"
        )
    else:
        hud.keys = (
            "A/S mode  ·  arrows pan  ·  Shift+←/→ rotate  ·  "
            "Shift+↑/↓ zoom  ·  R reset  ·  C clear  ·  B base"
        )
    hud.status = f"mode {_mode_i + 1}/{len(MODES)}{extra}"


def setup(canvas):
    _apply()


def update(dt):
    global _mode_i, _mouse_was_down, _fly_live
    if _warp_live is not None:
        _apply_warp_sliders(_warp_live, _read_warp_sliders())
    if keyp.once("A"):
        _mode_i = (_mode_i - 1) % len(MODES)
        _apply()
    if keyp.once("S"):
        _mode_i = (_mode_i + 1) % len(MODES)
        _apply()
    if keyp.once("C"):
        canvas.background.clear()
        _fly_live = None
        hud.status = "cleared extras (base kept)"
    if keyp.once("B"):
        canvas.background.reset_base()
        hud.status = "reset_base() → black"
    fly = _radial_fly()
    if keyp.once("R"):
        canvas.reset_view()
        canvas.set_origin("center")
        if fly is not None:
            fly.center = None
            fly.pan_response = 0.0
            hud.status = "view reset · center=None · pan_response=0"
        else:
            hud.status = "view reset"
    if fly is not None and keyp.once("P"):
        fly.pan_response = 0.0 if fly.pan_response > 0.05 else 0.85
        hud.status = f"pan_response={fly.pan_response:.2f} (opt-in bank of center)"

    down = mouse.press(0)
    if fly is not None and down and not _mouse_was_down:
        z = max(float(canvas.zoom), 1e-6)
        cx = float(canvas.pan_rest_x) + z * (float(mouse.x) - float(canvas.pan_x))
        cy = float(canvas.pan_rest_y) + z * (float(mouse.y) - float(canvas.pan_y))
        fly.center = (cx, cy)
        hud.status = (
            f"center=({cx:.0f}, {cy:.0f})  pan_response={fly.pan_response:.2f}"
        )
    _mouse_was_down = down

    apply_camera(dt, about=(0, 0))


run()
