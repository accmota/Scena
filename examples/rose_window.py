"""Rose Window.

An endless dive into a stained-glass rose window.

The window is made of rings, and each ring is the one inside it grown by
the golden ratio (phi = 1.618...). That is why the fall never ends: when
every ring has grown by phi, the picture is the same as before, so the
outermost ring leaves the view and a new one is born in the heart. The
rings live in a History: the queue of rings IS the dive, and the oldest
ring leaves in a vortex.

Every ring turns its own way (neighbours turn against each other, and the
lead lines make moire). The petals breathe. Light runs along the lead. Two
lights walk a great star polygon {7/3} round the heart, one close behind
the other, edge by edge like a turtle, and their trails draw the star.
Every 8 seconds a bell rings from the heart, and the third bell closes
the movement.

Four movements, about 24 seconds each:
  1 Glass    the window as it is
  2 Mirror   the window in a kaleidoscope, swaying
  3 Dawn     light pours out of the heart; the grand bell
  4 Eclipse  a moon crosses the window and turns its colours inside out

Things to try
-------------
  Move the mouse    a lamp of gold over the glass
  Click the glass   strikes the nearest piece
  Press SPACE       the fall stops, the window keeps turning

Keys
----
  MOUSE      a lamp
  CLICK      strike the nearest piece of glass
  SPACE      hold / resume the dive
  1 2 3 4    jump to a movement

Usage
-----
    python examples/rose_window.py
"""

from scena import *

init(width=1280, height=800, title="Rose Window")
canvas.set_origin("center")     # (0, 0) is the heart of the window

PHI = (1 + 5 ** 0.5) / 2
HEART = 65          # the radius of a ring when it is born
RINGS = 4           # rings in the window; a new one pushes the oldest out
RING_TIME = 6       # seconds for every ring to grow by PHI
BELL = 8            # seconds between bells
PANES = 8           # pieces of glass around each ring; the window has 8-fold symmetry
LEAD = Color(0.05, 0.03, 0.02)

# the glass: deep jewel colours, mostly blue and red, as in the old windows
COBALT = Color(0.08, 0.22, 0.85)
AZURE = Color(0.15, 0.55, 1.0)
RUBY = Color(0.78, 0.04, 0.16)
AMBER = Color(1.0, 0.6, 0.08)
EMERALD = Color(0.0, 0.62, 0.38)
VIOLET = Color(0.48, 0.16, 0.82)
# each ring: the colour of its band, then the two colours of its pieces
GLASS = [
    (COBALT, RUBY, AMBER),
    (RUBY, AZURE, COBALT),
    (VIOLET, AMBER, EMERALD),
    (COBALT, EMERALD, AZURE),
    (RUBY, AMBER, VIOLET),
    (COBALT, AZURE, RUBY),
]
MOVEMENTS = ["Glass", "Mirror", "Dawn", "Eclipse"]

st.depth = 0        # how far we have fallen, in rings
st.born = 1 - RINGS # the first rings are born already grown: the window starts full
st.breath = 0       # 0 … 1: the petals breathe with it
st.diving = True
st.movement = 0
st.bells = 0

# --- the night behind the glass, and the light on top of it -----------------

# a night sky that is a little bluer behind the window
Wallpaper(Gradient(Color(0.07, 0.06, 0.22), Color(0.01, 0.01, 0.04), type="radial", size=760))

Bloom(intensity=0.55)
Vignette(amount=0.9)
# the colour of the light changes slowly from the heart to the rim, and each
# movement has its own light
SWEEPS = [("gold", "royal blue", "crimson"), ("orchid", "cyan", "gold"),
          ("gold", "orange", "crimson"), ("cyan", "dark violet", "crimson")]
sweep = ColorSweep(axis="radial", colors=SWEEPS[0], amount=0.2, speed=0.3)
# each movement switches on its own lens
mirror = Kaleidoscope(segments=8, spin=0.04)
dawn = Grade("warm", saturation=1.3)     # morning light: warmer, the glass still deep
chroma = Chroma(amount=3)
prism = Prism(amount=0.006)    # only for an instant, on each bell
for lens in (mirror, dawn, chroma, prism):
    lens.enabled = False

# the window (glass, lead, tracery) lives on a layer behind the riders' trails
canvas.layers.create("window", below="default")

# the heart of the window: the light at the end of the fall
heart = Orb(center=(0, 0), radius=44, color="light yellow", glow=1.4, soft_edge=0.35)
# the stone tracery: spokes from the heart. Lines through the centre look
# the same at every zoom, so they belong to every ring at once.
for i in range(PANES):
    a = (i + 0.5) * 360 / PANES       # between two panes
    Line(p1=vec_from_angle(a, 60), p2=vec_from_angle(a, 900),
         color=LEAD, line_width=4, layer="window")
# the mouse is a lamp
lamp = GlowSpot(center=(0, 0), radius=80, color="gold", amount=0.7)
lamp["center"] @= mouse

tween(st["breath"], 1, time=3, loops="forever", yoyo=True, ease="ease_in_out")


# --- the rings ----------------------------------------------------------------

def on_ring(ring, angle, f):
    """A point on the ring: at this angle (turning with the ring), f of its radius out."""
    return vec_from_angle(angle + ring.angle, ring.radius * f)


def glass(ring, color, piece):
    """A piece of coloured glass in lead, owned by its ring."""
    piece.layer = "window"
    piece.fill = color
    piece.line = LEAD
    piece.line_width = 3
    piece.tag("glass")
    ring.pieces.append(piece)


def petals(ring, colors):
    """Pointed petals that breathe."""
    for i in range(PANES):
        a = i * 360 / PANES
        glass(ring, colors[i % 2], Triangle(
            center=lambda r=ring, a=a: on_ring(r, a, 1),
            radius=lambda r=ring: r.radius * r.glass * (0.2 + 0.04 * st.breath),
            base_ratio=lambda: 0.5 + 0.35 * st.breath,
            angle=lambda r=ring, a=a: a + r.angle))


def lattice(ring, colors):
    """Hexagons, like the cells of a honeycomb, each spinning in place."""
    for i in range(PANES):
        a = i * 360 / PANES
        color = colors[i % 2]
        cell = RegularPolygon(
            n=6,
            center=lambda r=ring, a=a: on_ring(r, a, 1),
            radius=lambda r=ring: r.radius * r.glass * 0.17,
            angle=lambda r=ring: -2 * r.angle)
        glass(ring, color, cell)
        # light through thick glass: brightest in the middle, deeper at the lead
        cell.fill = Gradient(color.lighter(0.3), color, color.darker(0.15), type="radial")


def lace(ring, colors):
    """Gothic arches: boxes with a half-moon scooped out, facing the heart."""
    for i in range(PANES):
        a = i * 360 / PANES
        glass(ring, colors[i % 2], Concave(
            center=lambda r=ring, a=a: on_ring(r, a, 1),
            width=lambda r=ring: r.radius * r.glass * 0.3,
            height=lambda r=ring: r.radius * r.glass * (0.13 + 0.04 * st.breath),
            angle=lambda r=ring, a=a: a + r.angle - 90,
            scoop="bottom_center"))


def leaves(ring, colors):
    """Leaves slanted like the blades of a turbine."""
    for i in range(PANES):
        a = i * 360 / PANES
        glass(ring, colors[i % 2], Ellipse(
            center=lambda r=ring, a=a: on_ring(r, a, 1),
            width=lambda r=ring: r.radius * r.glass * 0.38,
            height=lambda r=ring: r.radius * r.glass * 0.13,
            angle=lambda r=ring, a=a: a + r.angle + 50))


KINDS = [petals, lattice, lace, leaves]
def lead(ring):
    """The lead came between this ring and the next one out."""
    came = Circle(center=(0, 0), radius=lambda r=ring: r.radius * 1.26, line_width=5,
                  layer="window")
    came.fill = None
    came.line = Color(0.12, 0.09, 0.07)
    ring.pieces.append(came)
    return came


def light(ring, came, color):
    """Light running along the lead: the came's circle again, but only a
    short window of it, and the window travels."""
    run = Track.circle(center=(0, 0), radius=came.radius, color=color, line_width=4,
                       layer="window")
    run["scale"] @= lambda r=ring, r0=ring.radius: r.radius / r0
    run.blend = "add"
    speed = 0.03 if ring.spin > 0 else -0.03
    run["begin"] @= lambda: (clock.time * speed) % 1
    run["end"] @= lambda: (clock.time * speed + 0.15) % 1
    ring.pieces.append(run)


def new_ring():
    """The newest ring, born in the heart; it grows by PHI every RING_TIME."""
    n = st.born
    st.born += 1
    band, a, b = GLASS[n % len(GLASS)]
    # the ring is a wide band of tinted glass; its pieces come later
    ring = Circle(center=(0, 0), radius=lambda: HEART * PHI ** (st.depth - n),
                  line_width=lambda: HEART * PHI ** (st.depth - n) * 0.36, layer="window")
    ring.fill = None
    # the band's colour changes around the circle, as hand-made glass does
    ring.line = Gradient(band, band.lighter(0.15), band.darker(0.15), band.lighter(0.1), band,
                         type="sweep")
    ring.line.set_alpha(0.35)
    ring.blend = "screen"       # glass over glass gets lighter: the heart glows
    # neighbours turn against each other, each at its own pace
    ring.spin = (4 + 3 * (n % 3)) * (1 if n % 2 else -1)
    ring["angle"] @= lambda: ring.spin * clock.time
    ring.kind = n % len(KINDS)
    ring.colors = (a, b)
    ring.pieces = []
    ring.glass = 0              # 0 … 1: how far its glass has grown in
    came = lead(ring)
    if n % 2:
        light(ring, came, a)    # every other ring has light running on its lead
    return ring


def glaze(ring):
    """Put the glass into a ring that has come out of the light: it grows in."""
    KINDS[ring.kind](ring, ring.colors)
    tween(ring["glass"], 1, time=2, ease="ease_out")


def let_go(ring):
    """The oldest ring leaves in a vortex; its glass shrinks away with it."""
    ring.dissolve_out(1.2, style="vortex")
    tween(ring["glass"], 0, time=1, ease="ease_in")
    for piece in ring.pieces:
        piece.after(1, piece.destroy)


def dive_on():
    """A new ring in the heart; the one before it is big enough for its glass."""
    if len(dive):
        glaze(dive.last)
    dive.add(new_ring())


dive = History(max_points=RINGS, on_leave=let_go)
for i in range(RINGS):
    dive_on()


# --- the riders -----------------------------------------------------------------

def star_polygon(corners, step, radius):
    """The star polygon {corners/step}, drawn the way a turtle draws it: from
    each corner, a straight line to the corner `step` places further round."""
    points = []
    for i in range(corners):
        points.append(vec_from_angle(90 + i * step * 360 / corners, radius))
    return Track(points=points, smooth=0, closed=True)


def rider(path, color, lap, phase):
    """A light that walks a figure round the heart, slow and steady, and draws it."""
    spark = Circle(radius=4, color="white")
    spark.visual = Neon(color)          # a little star of neon
    spark.glow = CheapGlow(color, radius=14)
    spark.tail = Tail(color=color, size=2, amount=1.5)
    spark.move_along(path, time=lap, phase=phase, loops="forever")
    # the trail keeps the last ~24 seconds of the walk: the figure appears
    trail = Contrail(max_points=160, fade=True, color=color.with_alpha(0.95),
                     line_width=3.5, smooth=0)
    spark.every(0.15, lambda: trail.snapshot(spark))


# one great star {7/3} across the whole window; it turns very slowly, so the
# trails drift into a rosette
star = star_polygon(7, 3, 360)
star["angle"] @= lambda: clock.time * 0.5
# two lights walk it together, the coral one a few steps behind the gold one
rider(star, Color("gold"), 60, 0.03)
rider(star, Color("coral"), 60, 0)


# --- the bell and the movements -------------------------------------------------

def quiet_prism():
    prism.enabled = False


def bell():
    """Every BELL seconds the heart rings; the third bell ends the movement."""
    st.bells += 1
    strong = st.bells % 3 == 0
    burst = Sunburst(center=(0, 0), radius=90, color="gold", amount=1.2)
    burst.after(1.5, burst.destroy)
    canvas.ripple_at(0, 0, amount=0.5, shake=False)
    for piece in group["glass"]:
        piece.pop(scale=1.3)
    prism.enabled = True
    after(0.5, quiet_prism)
    if strong:
        canvas.flash(0.4)
        canvas.shake(6)
        outer = dive.first
        for a in range(0, 360, 60):
            canvas.zap_at(on_ring(outer, a, 0.8), style="fork", color="gold", radius=70)
        if st.movement == 2:
            canvas.explosion_at(0, 0, amount=1.5, shake=False)   # the grand bell of Dawn
        after(1.2, next_movement)


def eclipse():
    """A pale moon crosses the window. It is a disc of "difference": where it
    lies, every colour turns to its opposite and the light of the heart goes black."""
    moon = Circle(center=(-760, 120), radius=170)
    moon.fill = Color(0.8, 0.77, 0.7)
    moon.line = None
    moon.blend = "difference"
    moon.tag("passing")
    moon.move_to(760, -120, time=3 * BELL)
    moon.fade_in(2)
    # its shadow on the glass: "multiply" darkens whatever it lies on
    shadow = Circle(center=(-760, 120), radius=210, layer="window")
    shadow.fill = Color(0.45, 0.42, 0.62)
    shadow.line = None
    shadow.blend = "multiply"
    shadow.tag("passing")
    shadow.move_to(760, -120, time=3 * BELL)      # it travels with the moon
    shadow.fade_in(2)


def sunrise():
    """Dawn: a sun of rays rises in the heart and stays for the movement."""
    sun = Sunburst(center=(0, 0), radius=110, color="orange", amount=0.8)
    sun.tag("passing")


def begin_movement(m):
    st.movement = m
    show_title()
    mirror.enabled = m == 1
    dawn.enabled = m == 2
    chroma.enabled = m == 3
    for t in group["passing"]:
        t.destroy()     # the sun of the dawn, the moon of the eclipse
    if m == 2:
        sunrise()
    if m == 3:
        eclipse()
    sweep.colors = SWEEPS[m]
    heart.glow = 2.2 if m == 2 else 1.4      # dawn: the heart blazes
    # the camera: further back for the dawn, closer for the eclipse
    canvas.zoom_to([1, 1, 0.9, 1.08][m], time=4, ease="ease_in_out")
    if m != 1:
        canvas.pan_to(0, 0)     # only the mirror sways; the others look at the heart
    canvas.fade_in(0.9, style="iris")


def next_movement(m=None):
    if m is None:
        if canvas.covered > 0:
            return      # a key already started another movement
        m = (st.movement + 1) % len(MOVEMENTS)
    st.bells = 0
    canvas.fade_out(0.9, style="iris", on_done=lambda: begin_movement(m))


every(BELL, bell)

hud = Text("", top_left=(20, 30), color=Color("white").with_alpha(0.35), font_size=13, layer="ui")


def show_title():
    """The small line at the bottom: where we are, and the keys."""
    held = "" if st.diving else "   (held)"
    hud.text = f"{st.movement + 1}  {MOVEMENTS[st.movement]}{held}        1-4 movements   SPACE hold   CLICK strike"


show_title()


def update(dt):
    if st.diving:
        st.depth += dt / RING_TIME
    if st.depth > st.born:
        dive_on()
    canvas.rotate_by(2 * dt)        # the whole window turns, slowly
    if st.movement == 1:
        # the mirror sways: the kaleidoscope folds a different part of the window
        canvas.pan_to(vec_from_angle(clock.time * 20, 90))
    if keyp.once("SPACE"):
        st.diving = not st.diving
        show_title()
    for k in range(4):
        if keyp.once(str(k + 1)):
            next_movement(k)


def on_mouse_click(x, y, button):
    piece = group["glass"].nearest((x, y))
    if piece:
        canvas.zap_at(piece, style="spark", color="light yellow", radius=40)
        piece.spark_burst(amount=1.2)
        piece.pop(scale=1.5)


run()
