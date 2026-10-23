"""Loom.

A Jacquard loom of light. In 1804 Joseph-Marie Jacquard built a loom that
read its pattern from punched cards: a hole lifts a thread, no hole leaves
it down. It is one of the ancestors of the computer. Here it weaves light.

How it weaves, row by row:
  - the card is read: the threads under its holes are lifted (a light runs
    down each lifted thread, and the shed opens);
  - the shuttle flies across and lays a new weft thread behind it. Where a
    thread is lifted, the weft passes under it (the dark ground); where it
    is not, the weft floats over it, bright. The floats draw the picture;
  - the reed beats the new row into the cloth, and the cloth moves on.

The card is read from its bottom row up, so the cloth shows its picture
the right way up. The finished cloth winds onto the beam at the bottom.

When a card has been woven twice, the camera steps back to show the
tapestry, and the next card goes in.

Things to try
-------------
  Edit CARDS       each string is one row of the card: X is a hole. Draw
                   your own picture with X and . and weave it.
  Click the card   punch a hole, or fill one: the cloth changes from the
                   next row on
  Speed it up      the cloth flows; slow it down to watch a single row

Controls
--------
  CLICK the card   punch / fill a hole
  UP / DOWN        faster / slower
  N                finish this card now

Usage
-----
    python examples/loom.py
"""

from random import randint
from scena import *

init(width=1280, height=800, title="Loom")

# The punch cards. Each string is one row of the card, read left to right:
# "X" is a hole: the thread is lifted and the weft passes under it (the dark
# ground). "." is no hole: the weft floats over the thread (the bright picture).
# Each card has a name, the colours of its first and last rows, and the
# colour of its ground.
CARDS = [
    ["Diamond", "gold", "orange red", (0.34, 0.07, 0.09), [
        "XXXXX..XXXXX",
        "XXXX....XXXX",
        "XXX..XX..XXX",
        "XX..XXXX..XX",
        "X..XX..XX..X",
        "..XX.XX.XX..",
        "..XX.XX.XX..",
        "X..XX..XX..X",
        "XX..XXXX..XX",
        "XXX..XX..XXX",
        "XXXX....XXXX",
        "XXXXX..XXXXX",
    ]],
    ["Chevron", "turquoise", "royal blue", (0.05, 0.11, 0.27), [
        "...XXXXXX...",
        "X...XXXX...X",
        "XX...XX...XX",
        "XXX......XXX",
        ".XXX....XXX.",
        "..XXX..XXX..",
        "...XXXXXX...",
        "X...XXXX...X",
        "XX...XX...XX",
        "XXX......XXX",
        ".XXX....XXX.",
        "..XXX..XXX..",
    ]],
    ["Star", "hot pink", "medium purple", (0.2, 0.04, 0.17), [
        "XXXXX..XXXXX",
        "X.XXX..XXX.X",
        "XX.XX..XX.XX",
        "XXX.X..X.XXX",
        "XXXX.XX.XXXX",
        "....XXXX....",
        "....XXXX....",
        "XXXX.XX.XXXX",
        "XXX.X..X.XXX",
        "XX.XX..XX.XX",
        "X.XXX..XXX.X",
        "XXXXX..XXXXX",
    ]],
]

REPEAT = 2              # the card repeats this many times across the cloth
WARPS = 12 * REPEAT     # one warp thread per hole, for each repeat
GAP = 20                # distance between two warp threads
ROW = 20                # height of one woven row
MIDDLE = 590            # the middle of the cloth
LEFT = MIDDLE - (WARPS - 1) * GAP / 2
RIGHT = MIDDLE + (WARPS - 1) * GAP / 2
TIMES = 2               # each card is woven this many times

# The loom, from the bottom up:
FELL = 360              # the edge of the cloth, where each new row is beaten in
SHED = FELL + 42        # where the shuttle flies
REED = FELL + 92        # where the reed waits between two beats
HEDDLE = FELL + 200     # the heddles that lift the threads
BEAM = FELL + 370       # the beam the warp comes from

PASS = 0.85             # seconds for one flight of the shuttle
KEEP = 16               # rows of cloth between the fell and the cloth beam

st.card = 0
st.card_name = CARDS[0][0]
st.pick = 11            # the card row being woven (from the bottom up)
st.picks = 0            # rows woven with this card
st.right = True         # which way the shuttle flies next
st.speed = 1.0
st.reed = REED
st.open = 0             # how open the shed is: 0 closed, 1 open
st.pulse = 0            # 0 → 1: the light running down the lifted threads
st.finish = False       # N pressed: finish the card after this row
st.bloom = 0            # the glow of the tapestry when it is shown
st.top = FELL           # where the newest row sits, on the cloth

# ---- the room ---------------------------------------------------------------

Wallpaper(Gradient((0.1, 0.06, 0.04), (0.025, 0.015, 0.012), angle=-90))
Grain(amount=0.06)              # a woven texture over everything
Vignette(amount=0.9)
bloom = Bloom(intensity=0)      # only when the tapestry is shown
bloom.enabled = False

# The cloth lives on two layers that move down together as it grows (the
# take-up): the ground under the warp threads, the floats over them.
canvas.layers.create("ground", below="default", scroll=(0, -1))
canvas.layers.create("floats", z=1, scroll=(0, -1))
canvas.layers["ground"].scroll = (0, 0)
canvas.layers["floats"].scroll = (0, 0)


def on_cloth(y):
    """A height on the loom, in the cloth's own terms (the cloth has moved down)."""
    return y + canvas.layers["ground"].view.bottom - canvas.game_view.bottom


def take_up(time):
    """Move the cloth down until its newest row is at the fell, in `time` seconds.

    It measures what is left to go, so a late frame (the cloth went a little
    too far) is made up on the next row instead of leaving a gap.
    """
    distance = st.top - on_cloth(FELL)
    for name in ("ground", "floats"):
        canvas.layers[name].scroll = (0, -distance / time)
    after(time, stop_cloth)


def stop_cloth():
    for name in ("ground", "floats"):
        canvas.layers[name].scroll = (0, 0)


def card():
    return CARDS[st.card]


# ---- the shuttle ------------------------------------------------------------

shuttle = Ellipse(center=(LEFT - 75, SHED), width=58, height=12, color="ivory", layer=6)
shuttle.glow = Glow("gold", radius=16)
shuttle.tail = Tail(color="orange", size=1.8)
Ellipse(center=lambda: shuttle.center, width=24, height=5, color="saddle brown", layer=7)
# its shadow on the threads: a shadow multiplies the colours under it (darker,
# but still their own colour)
shadow = Ellipse(center=lambda: (shuttle.center.x + 8, shuttle.center.y - 14), width=64,
                 height=16, color=(0.45, 0.35, 0.3), layer=5)
shadow.blend = "multiply"

# The shed: the shuttle's path between the two ends of the loom. It arcs up
# as the lifted threads open the shed, and rocks a little over each thread.
shed = Track(points=[(LEFT - 75, SHED),
                     lambda: (MIDDLE, SHED + 10 * st.open),
                     (RIGHT + 75, SHED)])
shed.zigzag(amount=1.5, waves=WARPS / 2)

# a warm light that travels with the shuttle
GlowSpot(center=lambda: shuttle.center, radius=120, color="orange", amount=0.5, layer=-3)
# while it weaves, the shuttle is the lamp of the room
lamp = Lamp(target=shuttle, ambient=0.55, intensity=1.1)


def progress():
    """How far the shuttle is across the cloth: 0 at the left, 1 at the right."""
    return max(0, min(1, (shuttle.center.x - LEFT) / (RIGHT - LEFT)))


# ---- the warp: one thread per hole ------------------------------------------

heddles = []        # the wires that lift each thread
lights = []         # a light that runs down each thread when it is lifted

for i in range(WARPS):
    x = LEFT + i * GAP
    # from the beam, through its heddle, down through the cloth
    Line(p1=(x, BEAM), p2=(x, FELL - KEEP * ROW - 10), color=(0.85, 0.72, 0.5, 0.45),
         line_width=1.5)
    # a heddle: a short wire with the thread through its eye; it shows when it
    # lifts its thread, and rises as the shed opens
    heddle = Line(center=(x, HEDDLE), length=18, angle=90, color="gold", line_width=2.5,
                  layer=2)
    heddle["center"] @= lambda x=x: (x, HEDDLE + 9 * st.open)
    heddle.visible = False
    heddles.append(heddle)
    # the light: a twin of the thread, drawn only between begin and end
    light = Track(points=[(x, BEAM), (x, FELL)], smooth=0, color="light yellow", line_width=2.5)
    light.blend = "add"         # light adds up: it brightens what is under it
    light["begin"] @= lambda: st.pulse - 0.35
    light["end"] @= lambda: st.pulse
    light.visible = False
    lights.append(light)


# ---- the loom ---------------------------------------------------------------

WOOD = (0.32, 0.19, 0.1)
DARK_WOOD = (0.2, 0.11, 0.06)
POST = (RIGHT - LEFT) / 2 + 85

# the beam on top, and the two posts
Rect(center=(MIDDLE, BEAM + 14), width=2 * POST + 20, height=20, corner_radius=6,
     color=WOOD, layer=3)
for side in (-1, 1):
    x = MIDDLE + side * POST
    Rect(center=(x, (BEAM + FELL - 60) / 2), width=16, height=BEAM - FELL + 60,
         color=DARK_WOOD, layer=3)
    # a curved bracket where the post meets the beam
    Concave(center=(x - side * 26, BEAM - 18), width=36, height=36,
            scoop="bottom_left" if side < 0 else "bottom_right", color=DARK_WOOD, layer=3)
    # a pulley on each end: it turns with the shuttle, as the cords pull the heddles
    Circle(center=(x, BEAM + 14), radius=24, color=DARK_WOOD, layer=4)
    wheel = RegularPolygon(n=6, center=(x, BEAM + 14), radius=19, color=WOOD, layer=4)
    wheel["angle"] @= lambda side=side: side * shuttle.center.x * 1.5
    Circle(center=(x, BEAM + 14), radius=4, color="burlywood", layer=4)
    # a finial on top
    Triangle(center=(x, BEAM + 46), radius=12, angle=90, base_ratio=0.7, color=WOOD, layer=3)

# the harness: two bars that carry the heddles
for dy in (-14, 14):
    Rect(center=(MIDDLE, HEDDLE + dy), width=RIGHT - LEFT + 40, height=3,
         color=(0.45, 0.33, 0.2), layer=2)

# the cloth beam at the bottom: the finished cloth winds onto it
Rect(center=(MIDDLE, FELL - KEEP * ROW - ROW / 2 - 11), width=RIGHT - LEFT + 70, height=22,
     corner_radius=11, color=WOOD, layer=3)

# the reed: the comb that beats each new row into the cloth
reed = Rect(center=lambda: (MIDDLE, st.reed), width=RIGHT - LEFT + 60, height=7,
            corner_radius=3, color="burlywood", layer=5)
reed.visual = Metal("goldenrod")


# ---- the punch card ---------------------------------------------------------

CARD_X = 1085           # the middle of the card
CARD_Y = 470
HOLE = 13


def hole_place(pick, column):
    return (CARD_X - 5.5 * HOLE + column * HOLE, CARD_Y + 5.5 * HOLE - pick * HOLE)


Rect(center=(CARD_X, CARD_Y), width=12 * HOLE + 26, height=12 * HOLE + 40,
     corner_radius=8, color=(0.42, 0.33, 0.22), layer=3)
# the row being read
Rect(center=lambda: (CARD_X, CARD_Y + 5.5 * HOLE - st.pick * HOLE), width=12 * HOLE + 14,
     height=HOLE, corner_radius=4, color=(1, 0.85, 0.5, 0.15), layer=4)
# a light runs along that row as the shuttle crosses each repeat of the card
reader = Track(points=[lambda: hole_place(st.pick, 0), lambda: hole_place(st.pick, 11)],
               smooth=0, color="light yellow", line_width=5, layer=5)
reader.blend = "add"
reader["end"] @= lambda: (progress() * REPEAT) % 1
reader["begin"] @= lambda: (progress() * REPEAT) % 1 - 0.25

# one circle per place on the card; only the punched ones show
holes = []
for pick in range(12):
    row = []
    for column in range(12):
        row.append(Circle(center=hole_place(pick, column), radius=4.5,
                          color=(0.05, 0.025, 0.02), layer=3))
    holes.append(row)

Text(st["card_name"], center=(CARD_X, CARD_Y + 6.5 * HOLE + 34), color="wheat",
     font_size=22, layer=3)
Text(lambda: f"row {min(st.picks + 1, 12 * TIMES)} of {12 * TIMES}    speed {st.speed:g}x",
     center=(CARD_X, CARD_Y - 6.5 * HOLE - 34), color=(0.75, 0.65, 0.5), font_size=14,
     layer=3)
Text("click the card to punch a hole    UP / DOWN speed    N next card",
     center=(CARD_X, 40), color=(0.55, 0.47, 0.37), font_size=12, layer="ui")


def paint_card():
    for pick in range(12):
        for column in range(12):
            holes[pick][column].visible = card()[4][pick][column] == "X"


def on_mouse_click(x, y, button):
    """Punch a hole in the card, or fill it: the cloth follows from the next row."""
    column = round((x - (CARD_X - 5.5 * HOLE)) / HOLE)
    pick = round((CARD_Y + 5.5 * HOLE - y) / HOLE)
    if not (0 <= column < 12 and 0 <= pick < 12):
        return
    rows = card()[4]
    old = rows[pick]
    letter = "." if old[column] == "X" else "X"
    rows[pick] = old[:column] + letter + old[column + 1:]
    paint_card()
    holes[pick][column].pop(scale=1.8)
    # the hooks of that column jump: one thread for each repeat of the card
    for r in range(REPEAT):
        canvas.zap_at(LEFT + (r * 12 + column) * GAP, HEDDLE, color="gold", radius=18)


# ---- weaving ----------------------------------------------------------------

def unravel(row):
    """The oldest row winds onto the cloth beam, wiped away along its length."""
    for thread in row.floats:
        thread.dissolve_out(1.0, style="wipe", on_done=thread.destroy)
    row.dissolve_out(1.0, style="wipe")


cloth = History(max_points=KEEP, on_leave=unravel)


def lights_out():
    """Hide the lights when their run is over (a hidden object costs nothing)."""
    for light in lights:
        light.visible = False


def read_card():
    """Read the next row of the card: lift the threads under its holes."""
    lifted = card()[4][st.pick] * REPEAT     # one letter per thread
    for i in range(WARPS):
        up = lifted[i] == "X"
        heddles[i].visible = up
        lights[i].visible = up
    st.pulse = 0
    tween(st["pulse"], 1.35, time=0.7 / st.speed, ease="ease_in", on_done=lights_out)
    tween(st["open"], 1, time=0.3 / st.speed, ease="ease_out")
    for column in range(12):
        if card()[4][st.pick][column] == "X":
            holes[st.pick][column].pop(scale=1.5)
    after(0.4 / st.speed, throw)


def weave_row(y, chosen, pick):
    """One row of cloth at height y: the dyed weft, and its floats on top."""
    name, first, last, ground, rows = chosen
    # the weft: a dyed thread, a little uneven
    row = Track(points=[(LEFT - 8, y), (RIGHT + 8, y)], smooth=0, color=ground,
                line_width=ROW - 1, layer="ground")
    row.wander(amount=1.0, seed=randint(0, 999))
    # the floats: where no thread is lifted, the weft passes over and shows;
    # their colour goes from the card's first colour to its last, row by row
    colour = Color.interpolate(Color(first), Color(last), pick / (len(rows) - 1))
    lifted = rows[pick] * REPEAT
    row.floats = []
    i = 0
    while i < WARPS:
        if lifted[i] == "X":
            i += 1
            continue
        start = i
        while i < WARPS and lifted[i] != "X":
            i += 1
        x0 = LEFT + start * GAP - GAP / 2 + 1
        x1 = LEFT + (i - 1) * GAP + GAP / 2 - 1
        thread = Line(p1=(x0, y), p2=(x1, y), color=colour, line_width=ROW - 2, layer="floats")
        thread.line_cap = "square"
        row.floats.append(thread)
    return row


def throw():
    """The shuttle flies across, laying a new weft thread behind it."""
    time = PASS / st.speed
    row = weave_row(on_cloth(SHED), card(), st.pick)
    # the weft is laid exactly behind the shuttle
    if st.right:
        row["end"] @= lambda: progress()
    else:
        row["begin"] @= lambda: progress()
    # each float shows once the shuttle has crossed it
    for thread in row.floats:
        thread.visible = False
        if st.right:
            crossed = (thread.p2.x - LEFT) / (RIGHT - LEFT)
        else:
            crossed = (RIGHT - thread.p1.x) / (RIGHT - LEFT)
        thread.after(time * crossed, lambda thread=thread: thread.fade_in(0.15))
    span = (0, 1) if st.right else (1, 0)
    shuttle.move_along(shed, time=time, span=span, ease="ease_in_out",
                       on_done=lambda: beat(row))


def beat(row):
    """The reed beats the new row into the cloth, and the cloth moves on."""
    # the shuttle hits the end of the loom
    end = RIGHT + 75 if st.right else LEFT - 75
    spark = Sparks(center=(end, SHED), radius=16, rate=60, color="gold")
    spark.after(0.35, spark.destroy)
    shuttle.spark_burst(0.3, amount=0.8)
    st.right = not st.right
    row["begin"].unlink()
    row["end"].unlink()
    time = 0.18 / st.speed
    tween(st["reed"], FELL + 6, time=time, ease="ease_in")
    tween(st["open"], 0, time=time)
    # the row goes down onto the cloth, right above the last row, as the
    # cloth moves down one row
    st.top += ROW
    drop = st.top - on_cloth(SHED)
    row.move_by(0, drop, time=time, ease="ease_in")
    for thread in row.floats:
        thread.move_by(0, drop, time=time, ease="ease_in")
    take_up(time)
    after(time, lambda: packed(row))


def packed(row):
    """The row is in: the cloth shudders, and the next row (or the end of the card)."""
    reed.knock(distance=3, angle=-90)
    canvas.wave_at(MIDDLE, FELL, angle=-90, amount=0.12, shock=False, shake=False)
    cloth.add(row)
    tween(st["reed"], REED, time=0.35 / st.speed, ease="ease_out")
    st.picks += 1
    st.pick = (st.pick - 1) % 12
    if st.picks >= 12 * TIMES or st.finish:
        after(0.4, reveal)
    else:
        after(0.2 / st.speed, read_card)


# ---- between two cards: look at the tapestry --------------------------------

def reveal():
    """Step back and look at the whole tapestry."""
    lamp.enabled = False
    bloom.enabled = True
    tween(st["bloom"], 0.7, time=3)
    # frame the cloth that is left, with a little of the loom above it
    woven = len(cloth) * ROW
    canvas.pan_to(MIDDLE + 60, FELL - woven / 2 + 150, time=4, ease="ease_in_out")
    canvas.zoom_to(min(0.85, 800 / (woven + 520)), time=4, ease="ease_in_out")
    canvas.rotate_to(-4, time=5, ease="ease_in_out")
    name, first, last, ground, rows = card()
    # the last row goes in with a burst of colour
    canvas.explosion_at(MIDDLE, FELL, amount=0.5, shake=False)
    bottom = FELL - woven
    after(2.6, lambda: canvas.fireworks_at(LEFT - 150, FELL - 40, color=first, radius=150))
    after(3.2, lambda: canvas.fireworks_at(RIGHT + 160, (FELL + bottom) / 2, color=last,
                                           radius=170))
    after(3.9, lambda: canvas.fireworks_at(LEFT - 120, bottom + 60, color=last, radius=130,
                                           fall=0.8))
    after(8, lambda: canvas.fade_out(1.0, on_done=next_card))


def next_card():
    """Behind the dark cover: put the next card in and go back to weaving."""
    st.card = (st.card + 1) % len(CARDS)
    st.card_name = card()[0]
    st.pick = 11
    st.picks = 0
    st.finish = False
    paint_card()
    canvas.reset_view()
    st.bloom = 0
    bloom.enabled = False
    lamp.enabled = True
    canvas.fade_in(1.2)
    after(0.8, read_card)


def update(dt):
    if bloom.enabled and bloom.intensity != st.bloom:
        bloom.intensity = st.bloom      # a post cannot be tweened: follow st.bloom
    if keyp.once("UP"):
        st.speed = min(2, st.speed * 2)
    if keyp.once("DOWN"):
        st.speed = max(0.25, st.speed / 2)
    if keyp.once("N"):
        st.finish = True


# The loom has been at work before you came: the last card is already woven.
for k in range(KEEP):
    cloth.add(weave_row(FELL - (KEEP - 1 - k) * ROW, CARDS[-1], 11 - k % 12))
paint_card()
canvas.fade_in(1.5)
after(0.6, read_card)

run()
