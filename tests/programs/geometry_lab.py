# harness: cwd=examples/media
"""Geometry lab: shapes that move, measured and connected live.

Program-model test program (tests/program_support.py). PARAMS: speed, pins, slack.

Controls
--------
  drag the two Anchors       the segment, its middle point and the readouts follow
  LEFT / RIGHT (held)        nudge the right Anchor
  SPACE                      pin the orbiting triangle's position (History, last N)
  P                          pause / resume the clock
  mouse                      a dot sits at the polygon point closest to the pointer
  click                      sets the target the gold follower chases (deadzone)
"""
from math import cos, sin
from scena import *

PARAMS = globals().get("PARAMS", {})

W, H = 1000, 700
CX, CY = W * 0.5, H * 0.5

init(width=W, height=H, title="Geometry lab")
Wallpaper("dark navy")

st.speed = PARAMS.get("speed", 0.8)       # orbit speed, radians per second
st.pins_max = PARAMS.get("pins", 5)
st.slack = PARAMS.get("slack", 120)       # deadzone box size of the follower

# --- a measured segment between two draggable ends -----------------------
a = Anchor(200, 560)
b = Anchor(520, 620, color="lime")
segment = Line(p1=lambda: a.center, p2=lambda: b.center, color="white")
mid = Circle(center=lambda: middle_point(a, b), radius=6, color="gold")
quarter = Circle(center=lambda: lerp(a.center, b.center, 0.25), radius=4, color="orange")

# --- the fixed stage: an ellipse and a free polygon -----------------------
oval = Ellipse(center=(CX, CY), width=360, height=200, color="steel blue")
oval.fill = None
oval.line_width = 2

poly = Polygon(points=[(90, 120), (260, 100), (300, 240), (130, 280)], color="coral",
               group="shape")
probe = Circle(center=lambda: closest_point(poly, (mouse.x, mouse.y)), radius=5, color="white")

# --- movers ---------------------------------------------------------------
# A Square slides between two stops; remap turns sin(time) into the lerp weight.
slider = Square(center=(CX - 220, CY), length=70, group="shape")
slider.fill = Texture("k-textures/floor_ground_dirt.png", fit="tile", tile_size=35)

# A triangle orbits the ellipse centre, nose along its path; a Contrail follows it.
tri = Triangle(center=(CX + 230, CY), radius=26, color="cyan", group="shape")
tri["center"] @= lambda: (CX + 230 * cos(clock.time * st.speed),
                          CY + 150 * sin(clock.time * st.speed))
trail = Contrail(max_points=40, duration=1.5, fade=True, color="cyan", line_width=3)
tri.every(0.05, lambda: trail.snapshot(tri))

# A hexagon spins in place; it crosses the ellipse outline.
hexa = RegularPolygon(n=6, center=(CX + 170, CY + 60), radius=60, color="orchid",
                      group="shape")
hexa.fill = None

# Where the hexagon edges cross the ellipse: two live markers + a count.
cross0 = Circle(center=lambda: intersection(oval, hexa, 0), radius=4, color="red")
cross1 = Circle(center=lambda: intersection(oval, hexa, 1), radius=4, color="red")

# An Svg badge (inline markup) — a Sprite, so it has a measured hitbox.
badge = Svg('<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40">'
            '<circle cx="20" cy="20" r="18" fill="gold"/></svg>',
            height=40, center=(W - 80, H - 160), group="shape")

# The follower: chases the last click, but only once the target leaves its slack box.
target = Point(W - 150, 150, color="yellow")
follower = Circle(center=(W - 150, 150), radius=12, color="gold")

# History of pins dropped with SPACE (each pin a small circle; the oldest leaves).
pins = History(max_points=int(st.pins_max))

# --- readouts -------------------------------------------------------------
st.dist = 0.0
st.heading = 0.0
st.hits = 0
st.nearest = ""
st.pins = 0
st.oval_hitbox = oval.hitbox.shape
st.badge_hitbox_w = 0.0

hud = Text("", top_right=(W - 20, H - 20), align=XPos.RIGHT, font_size=16)
hud["text"] @= lambda: (f"d = {st.dist:.1f}\nheading = {st.heading:.1f}\n"
                        f"crossings = {st.hits}\nnearest = {st.nearest}\npins = {st.pins}")
caption = Text("", center=(CX, 40), layer="default", font_size=14)
caption["text"] @= lambda: f"t = {clock.time:.2f}s" + ("  (paused)" if clock.paused else "")


def name_of(shape):
    for name, obj in (("poly", poly), ("square", slider), ("triangle", tri),
                      ("hexagon", hexa), ("badge", badge)):
        if obj is shape:
            return name
    return "?"


def update(dt):
    # Square: sin -> [0, 1] -> position between two stops.
    w = remap(sin(clock.time * 1.3), -1, 1, 0, 1)
    slider.center = lerp((CX - 300, CY - 40), (CX - 140, CY + 40), w)

    hexa.rotate_by(25 * dt)

    if keyp("RIGHT"):
        b.x = b.x + 150 * dt
    if keyp("LEFT"):
        b.x = b.x - 150 * dt

    follower.center << deadzone(follower, target, size=st.slack)  # st.slack reads the value

    st.dist = distance(a, b)
    st.heading = heading(a, b)
    mid.radius = remap(st.dist, 0, 800, 4, 14)
    st.hits = len(intersections(oval, hexa))
    st.nearest = name_of(nearest((mouse.x, mouse.y), group["shape"]))
    st.pins = len(pins)
    box = badge.hitbox.box
    st.badge_hitbox_w = box.width if box is not None else 0.0


def on_key_down(key):
    if key == "SPACE":
        pins.add(Circle(center=tri.center, radius=5, color="white"))
    elif key == "P":
        clock.paused = not clock.paused


def on_mouse_click(x, y, button):
    target.x, target.y = x, y


run()
