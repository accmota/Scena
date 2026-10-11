"""
mix.py — smoke: common author path, many features, ordinary Scena code.

Widgets, shapes, sprites, camera, a few backgrounds / post FX / SpatialFx /
transients, pointer interaction, and @= links. Written like a typical script
(not a catalog, no private helpers).

Controls
--------
  A / S              previous / next shape or sprite
  arrows             move the selection
  Shift+← / →        rotate canvas
  Shift+↑ / ↓        zoom canvas
  Q / W              ui.scale − / +
  B                  cycle background (small set)
  F                  cycle canvas post FX (small set)
  E                  cycle FX quality
  SPACE              flash + pop + spark on the selection
  R                  reset camera
  click              save_visual overlay (Halo 1.2s → restore Glow) + flash/pop
  drag orange token onto the gray zone
  Heading slider     absolute angle (ship + ninja)
  Orbit slider       rotate_to about an external hub (square + corners)
  Ninja flip_x       checkbox — mirror; angle 0° → 180° at rest
  Reset heading      button — reset_rotation() on ship and ninja
"""
from scena import *

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud

W, H = 1400, 900
init(width=W, height=H, window_scale=0.75, title="Smoke — common mix")
canvas.fx_quality = "high"


hud = SmokeHud(
    title="Common mix",
    expect="Click ship/planet: Halo overlay ~1.2s then Glow returns (save_visual). SPACE = transients only. Coral plate: add_ship (blend=add, brighter) vs ghost (alpha=0.45, see-through).",
    keys="A/S select  ·  arrows move  ·  Shift+arrows camera  ·  Q/W scale  ·  B bg  ·  F post  ·  E quality  ·  SPACE fx  ·  click look  ·  R reset  ·  heading / orbit / flip",
    status="ready",
    show_aux=True,
)

# --- widgets (auto-stack under the HUD) --------------------------------------
st.radius = 52.0
st.rect_w = 130.0
st.color = "cyan"
st.show_hex = True
st.hue = 0.33
st.heading = 90.0
st.orbit = 0.0
st.flip_ninja = False
_applied_heading = 90.0  # last heading pushed from slider → actors

ui.gap()
ui.gap()
Slider(st["radius"], label="Radius", show_value=True, min_value=24.0, max_value=90.0)
Slider(st["hue"], label="Hue shift", show_value=True, min_value=0.0, max_value=1.0)
Slider(st["heading"], label="Heading °", show_value=True, min_value=0.0, max_value=360.0)
Slider(st["orbit"], label="Orbit ° (about hub)", show_value=True, min_value=0.0, max_value=360.0)
TextInput(st["rect_w"], placeholder="rect width")
DropDown(st["color"], options=["cyan", "magenta", "gold", "lime", "orange"])
CheckBox(st["show_hex"], label="Show hex")
CheckBox(st["flip_ninja"], label="Ninja flip_x")


def ping():
    planet.flash()
    planet.pop()
    planet.knock(distance=10, angle=30)
    canvas.shake(8)
    hud.status = "ping"


def reset_heading():
    global _applied_heading
    ship.reset_rotation()
    ninja.reset_rotation()
    # Keep slider where it is; mark it applied so @on_change won't rewrite ninja.
    _applied_heading = float(st.heading)
    hud.status = (
        f"reset_rotation  ship→{ship.angle:.0f}  "
        f"ninja→{ninja.angle:.0f}  (rest {ninja.rest_heading:.0f})"
    )


Button(label="Ping planet", on_click=ping)
Button(label="Reset heading", on_click=reset_heading)

# --- background + post (small selections, cycled later) ----------------------
bg_i = 0
fx_i = 0


def set_background(i):
    canvas.background.clear()
    if i == 0:
        SkyGradient("night")
        Stars(density=0.8, twinkle=0.3)
    elif i == 1:
        SkyGradient("day")
        Clouds(amount=0.4)
    elif i == 2:
        SkyGradient("space")
        Stars(density=0.85)
        Stardust()
    else:
        canvas.background = (0.08, 0.09, 0.12)


def set_post(i):
    canvas.effects.clear()
    if i == 0:
        Vignette(amount=0.32)
        Bloom(intensity=0.4)
    elif i == 1:
        Grade("warm")
    elif i == 2:
        Crt()


set_background(0)
set_post(0)

# --- shapes ------------------------------------------------------------------
planet = Circle(center=(520, 480), radius=52).set_color("cyan")
planet["radius"] @= st["radius"]
planet.glow = Glow("cyan", radius=14, sigma=7)

moon = Circle(center=(600, 480), radius=18).set_color("silver")
moon.center["x"] @= lambda: planet.center.x + 90
moon.center["y"] @= lambda: planet.center.y
tether = Line(p1=lambda: planet.center, p2=lambda: moon.center).set_color("white")
tether.line_width = 1

panel = Rect(center=(720, 480), width=130, height=80).set_color("cyan")
panel["width"] @= st["rect_w"]

square = Square(center=(880, 480), length=70, angle=12).set_color("gold")
oval = Ellipse(center=(520, 340), width=110, height=56, angle=-18).set_color("magenta")
hexagon = RegularPolygon(n=6, center=(680, 340), radius=44).set_color("lime")
triangle = EquilateralTriangle(center=(840, 340), radius=48).set_color("orange")
poly = Polygon(
    points=[(960, 310), (1040, 330), (1020, 390), (940, 380)],
).set_color("violet")
rod = Line(p1=(500, 240), p2=(640, 280)).set_color("sky blue")
rod.line_width = 6
hexagon.wheel_rotate = True

# rotate_to(..., about=hub): square orbits a point that is not its center
hub = Circle(center=(480, 640), radius=10).set_color("white")
rotor = Square(center=(580, 640), length=48).set_color("hot pink")
rotor.show_points()
spoke = Line(p1=lambda: hub.center, p2=lambda: rotor.center).set_color("white")
spoke.line_width = 1

# textured fills: shift= (HueShift / Recolor) composes with looks
wood = Rect(center=(980, 340), width=110, height=56)
wood.fill = Texture("../../examples/media/k-textures/floor_wood_planks.png", shift=HueShift(amount=st.hue))
wood.glow = CheapGlow("gold", radius=10, sigma=6)
flag = Rect(center=(1120, 250), width=90, height=70)
flag.fill = Texture(
    "../../examples/media/k-textures/floor_wood_planks.png", fit="tile", tile_size=28,
    shift=Recolor(key="blue", to="green"),
)

# click / drag
zone = Rect(center=(560, 140), width=150, height=80).set_color("gray")
token = Circle(center=(400, 140), radius=26).set_color("orange")
click_a = Circle(center=(760, 140), radius=32).set_color("tomato")
click_b = Square(center=(860, 140), length=54).set_color("gold")

# --- sprites -----------------------------------------------------------------
space = Sheet("../../examples/media/shooter/sheet.xml")
space.clip("ufo", ["ufoBlue.png", "ufoGreen.png", "ufoRed.png", "ufoYellow.png"], fps=5)

beacon = Circle(center=(1120, 520), radius=16).set_color("deep sky blue")
escort = Sprite(space, frame="ufoGreen.png", size=48, center=(1170, 520))
escort.center["x"] @= lambda: beacon.center.x + 55
escort.center["y"] @= lambda: beacon.center.y
leash = Line(p1=lambda: beacon.center, p2=lambda: escort.center).set_color("white")
leash.line_width = 1

ship = Sprite(
    space, frame="playerShip1_blue.png", height=52, center=(1120, 380), art_angle=90,
)
ship.glow = Glow("skyblue", radius=14, sigma=7)
ship.angle = float(st.heading)
ninja = Sprite("../../examples/media/ninja/Idle__003.png", height=64, center=(1000, 455), art_angle=0)
ninja.angle = float(st.heading)
nose = Line(p1=lambda: ship.center, angle=90, length=52).set_color("gold")
nose.line_width = 3
nose["angle"] @= st["heading"]
ufo = Sprite(space, frame="ufoBlue.png", size=50, center=(1240, 380))
ufo.play("ufo")
meteor = Sprite(space, frame="meteorBrown_big1.png", size=56, center=(1180, 250))
box = Sprite(center=(1280, 250), size=48)

# Body blit knobs: ADD vs sticky alpha (same art, coral dest so both read).
plate = Rect(center=(380, 560), width=200, height=96).set_color("coral")
add_ship = Sprite(
    space, frame="playerShip1_blue.png", height=48, center=(330, 560), art_angle=90,
)
add_ship.blend = "add"
ghost = Sprite(
    space, frame="playerShip1_blue.png", height=48, center=(430, 560), art_angle=90,
)
ghost.alpha = 0.45

# --- spatialFx (a few) -------------------------------------------------------
Fire(center=(980, 160), radius=22, style="camp")
Sparks(center=(1080, 160), radius=20, rate=28)
GlowSpot(center=(1120, 380), radius=46, color="cyan", amount=0.7)
Orb(center=(860, 200), radius=24)
Rain(center=(1280, 560), width=160, height=200, amount=0.45)
Jet(origin=(400, 240), angle=90, length=70, width=10)

# --- selection ---------------------------------------------------------------
actors = [
    planet, panel, square, oval, hexagon, triangle, poly, rod, wood, flag,
    token, click_a, click_b, beacon, ship, ninja, ufo, meteor, box,
    add_ship, ghost, hub, rotor,
]
index = 0

mark = Circle(center=(520, 480), radius=64, layer="top")
mark.fill = None
mark.line = Color(1.0, 0.85, 0.3, 1)
mark.line_width = 2


def select(step):
    global index
    index = (index + step) % len(actors)
    who = actors[index]
    who.pulse_outline(color="gold", duration=0.3)
    hud.status = f"selected {who}"


@on_change(st["color"])
def recolor(name):
    planet.set_color(str(name))
    panel.set_color(str(name))
    hud.status = f"color → {name}"


@on_change(st["hue"])
def on_hue(turns):
    # Texture(shift=) is construct-time; rebuild fill (decode stays shared).
    wood.fill = Texture("../../examples/media/k-textures/floor_wood_planks.png", shift=HueShift(amount=float(turns)))
    hud.status = f"hue → {float(turns):.2f}"


@on_change(st["show_hex"])
def toggle_hex(show):
    hexagon.visible = bool(show)
    hud.status = f"hex visible → {bool(show)}"


@on_change(st["orbit"])
def on_orbit(deg):
    a = float(deg)
    rotor.rotate_to(a, about=hub.center)
    hud.status = (
        f"orbit → {a:.0f}°  about=hub  "
        f"rotor=({rotor.center.x:.0f},{rotor.center.y:.0f})  "
        f"rot={rotor.angle:.0f}"
    )


@on_change(st["heading"])
def on_heading(deg):
    global _applied_heading
    a = float(deg)
    if a == _applied_heading:
        return
    _applied_heading = a
    ship.angle = a
    ninja.angle = a
    hud.status = (
        f"heading → {a:.0f}°  "
        f"ship.rot={ship.angle:.0f}  ninja.rot={ninja.angle:.0f}"
    )


@on_change(st["flip_ninja"])
def on_flip(v):
    ninja.flip_x = bool(v)
    hud.status = (
        f"ninja flip_x → {bool(v)}  "
        f"rot={ninja.angle:.0f}  rest={ninja.rest_heading:.0f}"
    )


@click(planet, click_a, click_b, ship, ninja)
def on_click(shape):
    global index
    if shape in actors:
        index = actors.index(shape)
    shape.save_visual()
    shape.visual = Halo("gold")
    after(1.2, shape.restore_visual, name="click_look")
    shape.flash()
    shape.pop()
    shape.knock(distance=10, angle=35)
    hud.status = f"clicked {shape} → Halo 1.2s (then restore)"


@drag_over(token)
def on_drag_over(from_shape, to_shape, pos):
    if to_shape is zone:
        zone.set_color("yellow")
        hud.status = f"drag over {to_shape}"
    else:
        zone.set_color("gray")


@drop_by(zone)
def on_drop(from_shape, to_shape, pos):
    from_shape.set_color("lime")
    to_shape.set_color("sea green")
    hud.status = f"dropped {from_shape} on {to_shape}"


def update(dt):
    who = actors[index]
    mark.center = (who.center.x, who.center.y)
    hud.aux = (
        f"sel={who}  heading={float(st.heading):.0f}  "
        f"ship.rot={ship.angle:.0f}  ship.rest={ship.rest_heading:.0f}  "
        f"ninja.rot={ninja.angle:.0f}  ninja.rest={ninja.rest_heading:.0f}  "
        f"ninja.flip_x={ninja.flip_x}  "
        f"orbit={float(st.orbit):.0f}  rotor=({rotor.center.x:.0f},{rotor.center.y:.0f})"
    )

    if keyp("SHIFT+LEFT"):
        canvas.rotate_by(40 * dt)
    if keyp("SHIFT+RIGHT"):
        canvas.rotate_by(-40 * dt)
    if keyp("SHIFT+UP"):
        canvas.zoom_by(1.0 + 0.6 * dt)
    if keyp("SHIFT+DOWN"):
        canvas.zoom_by(1.0 / (1.0 + 0.6 * dt))
    speed = 260 * dt
    if keyp("LEFT"):
        who.move_by(-speed, 0)
    if keyp("RIGHT"):
        who.move_by(speed, 0)
    if keyp("UP"):
        who.move_by(0, speed)
    if keyp("DOWN"):
        who.move_by(0, -speed)


def on_key_down(key):
    global bg_i, fx_i
    if key == "A":
        select(-1)
    elif key == "S":
        select(1)
    elif key == "Q":
        ui.scale = max(0.5, round(ui.scale - 0.1, 2))
        hud.status = f"ui.scale → {ui.scale:.2f}"
    elif key == "W":
        ui.scale = min(2.0, round(ui.scale + 0.1, 2))
        hud.status = f"ui.scale → {ui.scale:.2f}"
    elif key == "B":
        bg_i = (bg_i + 1) % 4
        set_background(bg_i)
        hud.status = f"background {bg_i + 1}/4"
    elif key == "F":
        fx_i = (fx_i + 1) % 4
        set_post(fx_i)
        hud.status = f"post {fx_i + 1}/4"
    elif key == "E":
        ladder = ("low", "medium", "high", "max")
        name = canvas.fx_quality.value if canvas.fx_quality is not None else "high"
        i = ladder.index(name) if name in ladder else 2
        nxt = ladder[(i + 1) % 4]
        canvas.fx_quality = nxt
        hud.status = f"quality={nxt}"
    elif key == "SPACE":
        who = actors[index]
        who.flash()
        who.pop()
        who.knock(distance=12, angle=40)
        who.spark_burst()
        hud.status = f"transient on {who}"
    elif key == "R":
        canvas.reset_view()
        hud.status = "view reset"


run()
