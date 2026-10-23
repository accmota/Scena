"""Polygon Ballet.

Twenty-eight regular polygons dance three movements, looping (about 60 s):
I Polygons, II Rosettes, III Lines (string art that closes into a ring of light,
falls into the centre and bursts into new polygons). A wave is domino(): one
action on every polygon, later the farther it is from where the wave starts.
"""

from math import sin, cos, radians, pi
from scena import *

init(width=1280, height=800, title="Polygon Ballet")
SkyGradient("night")
Bloom(intensity=0.6)

CENTER = (640, 400)
PACE = 0.0028       # seconds of delay per unit of distance: the speed of a wave
STRANDS = 98        # lines in movement III: 14 big heptagons, 7 edges each
# movement I: where each wave starts, the look it carries, the hit on its front
WAVES = [("lights", Gel, canvas.hit_at), ("diagonal", Aurora, canvas.burst_at),
         ("spiral", Swell, canvas.zap_at), ("lights", Aurora, canvas.hit_at)]
ROSETTES = [(330, 590), (950, 590), (330, 210), (950, 210)]
# movement II, around each rosette: kind, how many, distance, turn, spin, size
PIECES = [(Concave, 4, 42, -45, 40, dict(width=60, height=60, scoop="top_right")),
          (Triangle, 7, 185, 0, -25, dict(radius=24, base_ratio=0.45)),
          (Ellipse, 7, 150, 0, 20, dict(width=44, height=14))]

st.breath, st.even = 1, 0   # every polygon breathes · II: 1 makes them all one size
st.look, st.bloom = Gel, 0  # a new polygon's look · II: how open the rosettes are
st.loose, st.lock = 0, 0    # III: lines apart · locked on the circle
st.mult, st.skip = 1, 40    # III: line j joins point j to point j × mult + skip
st.turn, st.ring = 0, 1     # III: the circle's turn, in degrees · its size
tween(st["breath"], 1.15, time=0.9, ease="ease_in_out", loops="forever", yoyo=True)
caption = Text("", top_left=(28, 784), font_size=16, color="light gray", layer="ui")

# the floor: 7 × 4 spots in offset rows, big and small like a checkerboard
spots, big, dancers = [], [], {}        # dancers[i] is the polygon on spots[i]
for row in range(4):
    for col in range(7):
        spots.append(Point(640 + (col - 3.25) * 170 + row % 2 * 85, 400 + (row - 1.5) * 165))
        big.append((row + col) % 2 == 0)
homes = [(s.x, s.y) for s in spots]

def around(cx, cy, r, a):
    return (cx + r * cos(radians(a)), cy + r * sin(radians(a)))

def reach(i, n):
    """Polygon i's radius: big or small on the floor; in the rosettes a triangle and a
    heptagon read as siblings (half-way between the same radius and the same area)."""
    floor = 62 if big[i] else 34
    even = 30 * (2.74 / (n / 2 * sin(2 * pi / n))) ** 0.25  # 2.74: a heptagon's area / r²
    size = floor + (even - floor) * st.even
    # all breathe together, and a swell runs along the rows on top of it
    return size * (st.breath + 0.1 * sin(clock.time * 3 - homes[i][0] / 100))

def dance(i, n):
    """Put an n-sided polygon on spot i, coloured by its number of sides."""
    if i in dancers:
        dancers[i].destroy()
    spin = 45 if big[i] else -80    # big and small turn in counter-time
    p = RegularPolygon(n=n, center=lambda s=spots[i]: s, angle=lambda w=spin: w * clock.time,
                       radius=lambda: reach(i, n), line_width=2,
                       color=Color.from_hsv((n - 3) / 6, 0.6, 1))
    p.visual = st.look()
    p.pop(scale=1.5)
    dancers[i] = p

def step(i, change, hit):
    """Big polygons gain sides, small ones lose as many: the total stays the same."""
    sides = len(dancers[i].points)
    dance(i, sides + change if big[i] else sides - change)
    if big[i]:
        hit(spots[i])

def light_up(kind, cells, **style):
    """The lights (SpatialFx) move onto these spots: the next waves start from them."""
    group["light"].destroy()
    for i in cells:
        kind(center=lambda s=spots[i]: s, group="light", **style)

def domino(start, action):
    """action(i) on every spot, later the farther the spot is from the start."""
    for i in range(len(spots)):
        s = spots[i]
        if start == "lights":
            d = min(distance(s, fx.center) for fx in group["light"])
        elif start == "diagonal":
            d = (s.x + s.y - 300) * 0.5
        else:       # a spiral: around the centre, then outward
            d = heading(CENTER, s) % 360 * 1.5 + distance(s, CENTER) * 0.5
        after(max(0, d) * PACE, lambda i=i: action(i))

async def polygons():
    domino("spiral", lambda i: dance(i, 3 if big[i] else 7))
    await wait(2.5)
    light_up(GlowSpot, [8, 12, 15, 19], radius=90, color="white", amount=0.6)
    for k in range(len(WAVES)):
        start, st.look, hit = WAVES[k]
        canvas.ripple_at(CENTER, amount=0.4)
        domino(start, lambda i, hit=hit: step(i, 1, hit))
        if k == 2:      # close in on one polygon while the waves go on
            await parallel(canvas.pan_to(spots[15], time=2.5, ease="ease_in_out"),
                           canvas.zoom_to(2.6, time=2.5, ease="ease_in_out"),
                           canvas.rotate_to(30, time=2.5, ease="ease_in_out"))
            await canvas.reset_view(time=3, ease="ease_in_out")
        await wait(3.5)

def orbiter(kind, cx, cy, dist, a, turn, spin, size):
    """A piece of a rosette: it circles the centre, as far out as the rosette is open."""
    piece = kind(center=lambda: around(cx, cy, dist * st.bloom, a + spin * clock.time),
                 angle=lambda: a + turn + spin * clock.time, color=Color.from_hsv(a / 360, 0.5, 1),
                 group="piece", **size)
    piece.line = None       # fill only: an outline on each piece would double its drawing

async def rosettes():
    for cx, cy in ROSETTES:
        for kind, count, dist, turn, spin, size in PIECES:
            for j in range(count):
                orbiter(kind, cx, cy, dist, j * 360 / count, turn, spin, size)
    st.look = Metal
    domino("spiral", lambda i: step(i, 0, canvas.hit_at))
    tween(st["even"], 1, time=2.5, ease="ease_in_out")
    for i in range(28):     # seven polygons in a ring around each rosette
        cx, cy = ROSETTES[i % 4]
        tween(spots[i], around(cx, cy, 100, i // 4 * 360 / 7), time=2.5, ease="ease_in_out")
    await wait(2.5)
    light_up(Orb, [0, 1, 2, 3, 12, 13, 14, 15], radius=12, glow=1.4, color="white")
    await tween(st["bloom"], 1, time=3, ease="elastic")
    for cx, cy in ROSETTES:
        canvas.fireworks_at(cx, cy, color="gold", radius=120)
    domino("lights", lambda i: dancers[i].knock(distance=25, angle=heading(CENTER, spots[i])))
    await wait(6)
    await tween(st["bloom"], 0, time=1.5, ease="ease_in")
    group["piece"].destroy()

def strand_end(j, home, k):
    """End k of line j: loose around its old edge, or locked on the big circle."""
    hx = home[0] + st.loose * 70 * sin(clock.time * 1.3 + j)
    hy = home[1] + st.loose * 70 * cos(clock.time * 1.1 + j * 0.7)
    slot = j if k == 0 else j * st.mult + st.skip
    cx, cy = around(640, 400, 360 * st.ring, slot * 360 / STRANDS + st.turn)
    return (hx + (cx - hx) * st.lock, hy + (cy - hy) * st.lock)

def come_apart(i):
    """Small polygons shatter; big ones come apart into their edges."""
    p = dancers[i]
    if not big[i]:
        canvas.debris_at(spots[i], color=p.color, radius=50)
    else:
        corners = [(c.x, c.y) for c in p.points]
        for k in range(len(corners)):
            j = len(group["strand"])
            Line(p1=lambda j=j, h=corners[k]: strand_end(j, h, 0), group="strand",
                 p2=lambda j=j, h=corners[k - 1]: strand_end(j, h, 1),
                 color=Color.from_hsv(j / STRANDS, 0.6, 1), line_width=2)
        canvas.burst_at(spots[i], radius=60)
    p.destroy()

async def lines():
    light_up(GlowSpot, range(16), radius=60, color="white", amount=0.6)
    domino("lights", come_apart)
    await tween(st["loose"], 1, time=4.5, ease="ease_out")
    await tween(st["lock"], 1, time=3.5, ease="ease_in_out")
    canvas.wave_at(0, 0, angle=32, amount=0.6)
    group["light"].destroy()    # lights out: the circle is the light now
    await parallel(tween(st["skip"], 30, time=4, ease="ease_in_out"),
                   canvas.rotate_by(-60, time=4, ease="ease_in_out"))
    prism = Prism(amount=0.006)     # five seconds of split light while the star melts
    await parallel(tween(st["mult"], 2, time=5, ease="ease_in_out"),
                   tween(st["skip"], 0, time=5, ease="ease_in_out"),
                   tween(st["turn"], 90, time=5, ease="ease_in_out"))
    prism.remove()
    await tween(st["mult"], 3, time=6, ease="ease_in_out")
    # the ending: each line joins its neighbour (a ring), the ring falls in and bursts
    await parallel(tween(st["mult"], 1, time=2.5, ease="ease_in_out"),
                   tween(st["skip"], 1, time=2.5, ease="ease_in_out"),
                   canvas.reset_view(time=2.5, ease="ease_in_out"))
    await wait(1)
    await tween(st["ring"], 0.02, time=1.2, ease="ease_in")
    canvas.explosion_at(CENTER, amount=1.5, flash=True)
    canvas.bubbles_at(CENTER, color="cyan", count=40, height=300)
    group["strand"].destroy()
    for k in range(28):     # back home, to be born again as polygons
        tween(spots[k], homes[k], time=1, ease="ease_out")
    st.loose, st.lock, st.turn, st.skip, st.ring, st.even, st.look = 0, 0, 0, 40, 1, 0, Gel

MOVEMENTS = [("I   POLYGONS", ColorSweep, polygons), ("II   ROSETTES", ColorWash, rosettes),
             ("III   LINES", Vignette, lines)]

async def ballet():
    while True:
        for title, post, movement in MOVEMENTS:
            caption.text = title
            screen = post()     # each movement colours the screen its own way
            await movement()
            screen.remove()

run_task(ballet)
run()
