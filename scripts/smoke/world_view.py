"""
world_view.py — smoke: camera + parallax layers + cull.

Separate from background.py (field catalog). Here: depth planes, pan/zoom/rotate,
cull_offscreen. A/S cycle scene modes; arrows pan; Shift+arrows rotate/zoom; IJKL move player.
"""
from scena import *
import sys as _sys
_sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from _hud import SmokeHud

init(width=1400, height=900, window_scale=0.8, title="Smoke — world view")
hud = SmokeHud(
    title="World view",
    expect="Parallax layers lag camera; O toggles cull; HUD stays screen-fixed",
    keys="A/S mode  ·  arrows pan  ·  Shift+←/→ rotate  ·  Shift+↑/↓ zoom  ·  IJKL player  ·  O cull  ·  R reset",
    status="",
)
canvas.background = (0.05, 0.06, 0.09)
canvas.set_origin("center")
canvas.cull_offscreen = True

_owned = []
_player = None
_mode_i = 0


def _track(obj):
    _owned.append(obj)
    return obj


def _clear_scene():
    """Remove demo objects and custom layers; keep default + top clean."""
    global _player
    for o in list(_owned):
        try:
            o.destroy()
        except Exception:
            pass
    _owned.clear()
    _player = None
    canvas.background.clear()
    # Soft-clear default (grid/markers rebuilt by modes that need them).
    for name in list(canvas.layers):
        if name in ("default", "top"):
            canvas.layers[name].clear(hard=True)
        else:
            try:
                canvas.layers[name].delete(destroy_shapes=True)
            except Exception:
                pass
    hud.status = ""


def _world_grid():
    grid_c = Color(1, 1, 1, 0.10)
    for x in range(-800, 801, 100):
        _track(Line(p1=(x, -500), p2=(x, 500)).set_color(grid_c)).line_width = 1
    for y in range(-500, 501, 100):
        _track(Line(p1=(-800, y), p2=(800, y)).set_color(grid_c)).line_width = 1
    _track(Circle(center=(0, 0), radius=18).set_color("cyan"))


MODES = []


def _mode(label):
    def deco(fn):
        MODES.append((label, fn))
        return fn

    return deco


@_mode("1 Depth stack  SkyGradient + mountains/trees + player")
def _m_depth():
    canvas.background.base = SkyGradient("day")
    canvas.background.add(Clouds(pan_response=0.08, amount=0.35))
    canvas.layers.create("far", below="default", pan_response=0.15, zoom_response=0.1)
    canvas.layers.create("mid", below="default", pan_response=0.45, zoom_response=0.35)
    canvas.layers.create("near", below="default", pan_response=0.75, zoom_response=0.6)

    # Far mountains
    _track(
        Polygon(
            points=[(-700, -50), (-400, 180), (-100, -20), (200, 220), (500, -40), (700, -80)],
            layer="far",
        ).set_color(Color(0.15, 0.22, 0.38))
    )
    # Mid trees (circles)
    for i, x in enumerate(range(-500, 501, 120)):
        h = 40 + (i % 3) * 18
        _track(
            Circle(center=(x, 20 + h * 0.3), radius=h * 0.45, layer="mid").set_color(
                Color(0.12, 0.45 - i * 0.02, 0.18)
            )
        )
        _track(
            Rect(
                center=(x, -10),
                width=14,
                height=h * 0.5,
                layer="mid",
            ).set_color(Color(0.25, 0.15, 0.08))
        )
    # Near bushes
    for x in (-280, -80, 140, 320):
        _track(
            RegularPolygon(
                center=(x, -40),
                radius=38,
                n=6,
                layer="near",
            ).set_color(Color(0.1, 0.55, 0.22))
        )

    global _player
    _player = _track(Circle(center=(0, -120), radius=28).set_color("gold"))
    hud.status = "Move player with IJKL · pan camera with arrows"


@_mode("2 Scroll-only  fixed cam, invaders-style drift")
def _m_scroll():
    canvas.background.base = SkyGradient("night")
    canvas.background.add(Stars(pan_response=0.0, density=0.85, scroll=(0.0, -30.0)))
    canvas.layers.create(
        "scroll_bg",
        below="default",
        pan_response=1.0,
        zoom_response=1.0,
        rotation_response=1.0,
        scroll=(0.0, -55.0),
    )
    for i in range(12):
        y = 200 - i * 70
        for x in (-300, 0, 300):
            _track(
                Circle(
                    center=(x + (i % 2) * 40, y),
                    radius=18,
                    layer="scroll_bg",
                ).set_color(Color(0.7, 0.85, 1.0, 0.85))
            )
    hud.status = "Camera fixed — layer scroll rolls author content (and Stars background)"


@_mode("3 Foreground parallax  pan_response>1 above default")
def _m_foreground():
    _world_grid()
    canvas.layers.create("fg", above="default", pan_response=1.4, zoom_response=1.1)
    for x in (-400, -150, 120, 380):
        _track(
            Rect(
                center=(x, -220),
                width=90,
                height=260,
                layer="fg",
            ).set_color(Color(0.05, 0.05, 0.08, 0.75))
        )
    _track(Circle(center=(0, 0), radius=40).set_color("orchid"))
    hud.status = "Dark pillars over-scroll with pan (pan_response=1.4)"


@_mode("4 Rotation response  Q/E rotate camera")
def _m_rotation():
    _world_grid()
    canvas.layers.create(
        "half_rot",
        below="default",
        pan_response=1.0,
        zoom_response=1.0,
        rotation_response=0.5,
    )
    canvas.layers.create(
        "full_rot",
        above="default",
        pan_response=1.0,
        zoom_response=1.0,
        rotation_response=1.0,
    )
    _track(
        Rect(center=(-180, 0), width=120, height=80, layer="half_rot").set_color("coral")
    )
    _track(
        Rect(center=(180, 0), width=120, height=80, layer="full_rot").set_color("lime")
    )
    _track(Circle(center=(0, 0), radius=36).set_color("cyan"))
    hud.status = "Coral = half rotation_response · lime = full · cyan = default"


@_mode("5 SpatialFx in parallax layer  Rain")
def _m_spatial():
    canvas.background = (0.04, 0.05, 0.1)
    canvas.layers.create("weather", below="default", pan_response=0.25, zoom_response=0.2)
    _track(Rain(center=(0, 120), width=900, height=700, amount=0.7, layer="weather"))
    _track(Circle(center=(0, -80), radius=50).set_color("gold"))
    hud.status = "Rain shares Entity layer machinery; pans slower than player circle"


@_mode("6 All shape kinds in one non-neutral layer")
def _m_kinds():
    canvas.layers.create("kinds", below="default", pan_response=0.35, zoom_response=0.3)
    _track(Circle(center=(-320, 80), radius=40, layer="kinds").set_color("cyan"))
    _track(Rect(center=(-180, 80), width=90, height=55, layer="kinds").set_color("gold"))
    _track(Square(center=(-40, 80), length=60, layer="kinds").set_color("orchid"))
    _track(Ellipse(center=(120, 80), width=100, height=50, layer="kinds").set_color("lime"))
    _track(
        Polygon(
            points=[(220, 40), (280, 120), (200, 110)],
            layer="kinds",
        ).set_color("coral")
    )
    _track(
        RegularPolygon(center=(360, 80), radius=45, n=5, layer="kinds").set_color(
            "magenta"
        )
    )
    _track(Line(p1=(-320, -40), p2=(360, -40), layer="kinds").set_color("white"))
    p = _track(Point(0, -100, layer="kinds"))
    p.visible = True
    p.set_color("yellow")
    hud.status = "Circle Rect Square Ellipse Polygon RegularPolygon Line Point under CTM swap"


@_mode("7 Misuse demo  guards fire with clear messages")
def _m_misuse():
    canvas.layers.create("trees", below="default", pan_response=0.4)
    tree = _track(Circle(center=(-120, 0), radius=40, layer="trees").set_color("green"))
    player = _track(Circle(center=(120, 0), radius=40).set_color("gold"))
    msgs = []

    try:
        tree.clickable = True
    except ParallaxLayerError as e:
        msgs.append(f"clickable: {e}")
    try:
        tree.collidable = True
    except ParallaxLayerError as e:
        msgs.append(f"collidable: {e}")
    try:
        player.layer = "trees"
        player.clickable = True  # won't reach if layer move fails first
    except ParallaxLayerError as e:
        msgs.append(f"move+flags: {e}")
    try:
        player.clickable = True
        player.layer = "trees"
    except ParallaxLayerError as e:
        msgs.append(f"interactive→parallax: {e}")
    try:

        @collide(tree, player)
        def _on_hit(me, other, info):
            pass

    except ParallaxLayerError as e:
        msgs.append(f"@collide: {e}")

    hud.status = " | ".join(msgs)[:180] if msgs else "no errors (unexpected)"
    hud.expect = "Misuse demo — ParallaxLayerError messages in status"


@_mode("8 Cross-layer formula link  Line default↔parallax")
def _m_crosslink():
    canvas.layers.create("trees", below="default", pan_response=0.35)
    tree = _track(Circle(center=(-200, 80), radius=36, layer="trees").set_color("green"))
    player = _track(Circle(center=(200, -40), radius=36).set_color("gold"))
    # Link line endpoints in world space — visual divergence under pan is expected.
    _track(Line(p1=lambda: tree.center, p2=lambda: player.center).set_color(Color(1, 1, 1, 0.7)))
    hud.status = (
        "Line links tree.center (parallax) to player (default) in world space — "
        "apparent angles shift under pan (expected)"
    )


def _apply():
    global _mode_i
    _clear_scene()
    label, fn = MODES[_mode_i]
    hud.title = f"World view — [{_mode_i + 1}/{len(MODES)}]"
    hud.expect = label
    hud.status = ""
    fn()


def setup(canvas):
    _apply()


def update(dt):
    global _mode_i, _player
    if keyp.once("A"):
        _mode_i = (_mode_i - 1) % len(MODES)
        _apply()
    if keyp.once("S"):
        _mode_i = (_mode_i + 1) % len(MODES)
        _apply()
    if keyp.once("C"):
        _clear_scene()
        hud.status = "cleared custom layers / objects"
    if keyp.once("R"):
        canvas.reset_view()
        canvas.set_origin("center")
        hud.status = "view reset"
    if keyp.once("O"):
        canvas.cull_offscreen = not canvas.cull_offscreen
        hud.status = f"cull_offscreen = {canvas.cull_offscreen}"

    # Camera: bare arrows pan; Shift+arrows rotate / zoom (explicit chords).
    about = (0, 0)
    if keyp("SHIFT+LEFT"):
        canvas.rotate_by(40 * dt, about=about)
    if keyp("SHIFT+RIGHT"):
        canvas.rotate_by(-40 * dt, about=about)
    if keyp("SHIFT+UP"):
        canvas.zoom_by(1.0 + 0.6 * dt, about=about)
    if keyp("SHIFT+DOWN"):
        canvas.zoom_by(1.0 / (1.0 + 0.6 * dt), about=about)
    if keyp("LEFT"):
        canvas.pan_by(-280 * dt, 0)
    if keyp("RIGHT"):
        canvas.pan_by(280 * dt, 0)
    if keyp("UP"):
        canvas.pan_by(0, 280 * dt)
    if keyp("DOWN"):
        canvas.pan_by(0, -280 * dt)

    # held: IJKL still move the player while Shift is down for the camera.
    if _player is not None:
        ps = 220 * dt
        if keyp.held("J"):
            _player.move_by(-ps, 0)
        if keyp.held("L"):
            _player.move_by(ps, 0)
        if keyp.held("I"):
            _player.move_by(0, ps)
        if keyp.held("K"):
            _player.move_by(0, -ps)


run()
