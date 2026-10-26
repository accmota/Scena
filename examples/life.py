"""Life: Conway's Game of Life, in glass.

The grid builds itself: every line starts in the bottom-left corner, and
one after another they fly to their places (each end on its own clock, so
the lines open like a fan), then the light settles. A soup of cells grows
from the middle and the game runs.

When the board stops changing, an R-pentomino falls on it and the game
blossoms again. The rules, on every tick: a live cell with two or three live neighbours
stays; a dead cell with exactly three is born; every other cell dies. The
board wraps round: a glider that leaves on the right comes back on the left.

A newborn cell grows slowly, with a quarter turn: it reaches full size
only after a few ticks, so a busy board breathes instead of flashing. A
cell dies shrinking away. Its colour is its age: young cells are pale, old
ones deepen to violet (a Colormap, read in steps).

Controls
--------
  click / drag     flip cells (a drag paints what the first cell became)
  SPACE            run / pause
  RIGHT            one tick (when paused)
  UP / DOWN        faster / slower
  R                a new random soup
  C                clear

Things to try
-------------
  Change COLS                 a finer or coarser board (try 40 or 120)
  Change BORN, GROW           how big a newborn starts, how many ticks it takes to grow
  Change AGE                  other colours for the ages
  Change born() and die()     other ways to appear and go
"""
from random import random, randint
from scena import *

init(width=1280, height=800, title="Life")
Wallpaper(Gradient("#03050c", "#0c0f24", angle=90))
Nebuladust(color="midnight blue", color2="dark slate blue", color3="teal", alpha=0.25)
light = Bloom(intensity=1.6)
Vignette(amount=0.8)

COLS = 60                               # columns: the rest follows (square cells that fill the board)
CELL = 1120 / COLS                      # the board fits in 1120 x 672, from (80, 64)
ROWS = int(672 / CELL)
LEFT, BOTTOM = 80, 64 + (672 - ROWS * CELL) / 2      # the board's corner (centred up and down)
SIZE = CELL * 0.8                       # a grown cell
BORN = 0.4                              # a newborn's size, of a grown cell (0: from nothing · 1: full at once)
GROW = 5                                # ticks a newborn takes to reach full size
AGE = Colormap.from_colors("aquamarine", "turquoise", "deep sky blue", "royal blue", "medium purple")
STEPS = 12                              # how many shades of age
SHADES = [Gradient(AGE.get_color(i / (STEPS - 1)).lighter(0.2), AGE.get_color(i / (STEPS - 1)).darker(0.25), type="radial")
          for i in range(STEPS)]

st.running = False
st.period = 0.14        # seconds between ticks
st.timer = 0
st.ticks = 0
st.population = 0
st.quiet = 0            # ticks in a row with the same number of live cells
st.glow = 1.6           # the Bloom (a screen effect does not link: update writes it)
st.paint = True         # what a drag paints: live (True) or dead cells
st.ready = False        # the grid is in place: the board takes clicks

alive = [[False] * COLS for r in range(ROWS)]
age = [[0] * COLS for r in range(ROWS)]


def place(r, c):
    """The middle of cell (row r, column c)."""
    return (LEFT + (c + 0.5) * CELL, BOTTOM + (r + 0.5) * CELL)


# ---- the cells: all made now, hidden; birth and death only show and hide them ----
cells = []
for r in range(ROWS):
    row = []
    for c in range(COLS):
        cell = Square(center=place(r, c), length=SIZE, corner_radius=CELL / 4)
        cell.line = None
        cell.visible = False
        row.append(cell)
    cells.append(row)


def born(r, c):
    alive[r][c] = True
    age[r][c] = 0
    cell = cells[r][c]
    cell.fill = SHADES[0]
    cell.visible = True
    cell.length, cell.angle = BORN * SIZE, -90
    # it grows for GROW ticks, smoothly: full size only after a few rounds
    # (the cell's own named tweens: born again while it was dying, the new ones replace the old)
    cell.tween(cell["length"], SIZE, time=GROW * st.period, ease="ease_in_out", name="size")
    cell.tween(cell["angle"], 0, time=GROW * st.period, ease="ease_out", name="turn")


def die(r, c):
    alive[r][c] = False
    cell = cells[r][c]
    cell.tween(cell["angle"], 90, time=2 * st.period, ease="ease_in", name="turn")
    cell.tween(cell["length"], 0, time=2 * st.period, ease="ease_in", name="size", on_done=lambda: hide(cell))


def hide(cell):
    # (born again while it was going, the new "size" tween replaced this one: no hide)
    cell.visible = False


def flip(r, c, live):
    if live and not alive[r][c]:
        born(r, c)
    elif not live and alive[r][c]:
        die(r, c)


def neighbours(r, c):
    count = 0
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if (dr or dc) and alive[(r + dr) % ROWS][(c + dc) % COLS]:
                count += 1
    return count


def tick():
    counts = [[neighbours(r, c) for c in range(COLS)] for r in range(ROWS)]
    before = st.population
    for r in range(ROWS):
        for c in range(COLS):
            n = counts[r][c]
            if alive[r][c] and n not in (2, 3):
                die(r, c)
            elif not alive[r][c] and n == 3:
                born(r, c)
            elif alive[r][c]:
                age[r][c] += 1
                cells[r][c].fill = SHADES[min(age[r][c] // 3, STEPS - 1)]
    st.ticks += 1
    # a board that stopped changing (still lifes, blinkers) gets a seed that blossoms
    st.population = sum(row.count(True) for row in alive)
    st.quiet = st.quiet + 1 if st.population == before else 0
    if st.quiet > 40:
        st.quiet = 0
        seed(randint(3, ROWS - 4), randint(3, COLS - 4))


R_PENTOMINO = [(0, 0), (0, 1), (1, -1), (1, 0), (2, 0)]


def seed(r, c):
    """An R-pentomino: five cells that grow for a thousand ticks."""
    for dr, dc in R_PENTOMINO:
        flip((r + dr) % ROWS, (c + dc) % COLS, True)


# ---- the grid: every line starts in the corner and flies to its place ----
GRID = Gradient("deep sky blue", "white", "medium orchid")
rows = [Line(p1=(LEFT, BOTTOM), p2=(LEFT, BOTTOM), color=GRID, line_width=1.6) for i in range(ROWS + 1)]
columns = [Line(p1=(LEFT, BOTTOM), p2=(LEFT, BOTTOM), color=GRID, line_width=1.6) for i in range(COLS + 1)]


async def build_grid():
    canvas.fade_in(1.5)
    await wait(1)
    right, top = LEFT + COLS * CELL, BOTTOM + ROWS * CELL
    count = max(len(rows), len(columns))
    for i in range(count):
        # each end on its own clock: the lines open like a fan
        if i < len(rows):
            y = BOTTOM + i * CELL
            tween(rows[i]["p1"], (LEFT, y), time=2.4, ease="ease_in_out")
            tween(rows[i]["p2"], (right, y), time=3.2, ease="ease_in_out")
        if i < len(columns):
            x = LEFT + i * CELL
            tween(columns[i]["p1"], (x, BOTTOM), time=3.2, ease="ease_in_out")
            tween(columns[i]["p2"], (x, top), time=2.4, ease="ease_in_out")
        await wait(4 / count)           # the same few seconds on any board
    await wait(2.0)
    # the light settles
    tween(st["glow"], 0.6, time=1.0, ease="ease_in_out")
    for line in rows + columns:
        tween(line["line_width"], CELL / 35, time=1.0, ease="ease_in_out")     # thinner on a finer board
    await wait(0.4)
    st.ready = True
    await soup()
    st.running = True


async def soup():
    """A random board, popping up from the middle out."""
    for ring in range(max(ROWS, COLS)):
        for r in range(ROWS):
            for c in range(COLS):
                d = max(abs(r - ROWS // 2), abs(c - COLS // 2))
                if d == ring:
                    flip(r, c, random() < 0.3)
        await wait(0.03)


def cell_at(x, y):
    """(row, column) under the point, or None off the board."""
    c = int((x - LEFT) // CELL)
    r = int((y - BOTTOM) // CELL)
    if 0 <= r < ROWS and 0 <= c < COLS:
        return r, c
    return None


def on_mouse_down(x, y):
    spot = cell_at(x, y)
    if st.ready and spot is not None:
        st.paint = not alive[spot[0]][spot[1]]
        flip(spot[0], spot[1], st.paint)


def update(dt):
    light.intensity = st.glow
    if st.ready and mouse.press():
        spot = cell_at(mouse.x, mouse.y)
        if spot is not None:
            flip(spot[0], spot[1], st.paint)
    if st.running:
        st.timer += dt
        if st.timer >= st.period:
            st.timer = 0
            tick()
    if not st.ready:
        return
    if keyp.once("SPACE"):
        st.running = not st.running
    if keyp.once("RIGHT") and not st.running:
        tick()
    if keyp.once("UP"):
        st.period = max(0.04, st.period * 0.7)
    if keyp.once("DOWN"):
        st.period = min(1, st.period / 0.7)
    if keyp.once("C"):
        for r in range(ROWS):
            for c in range(COLS):
                flip(r, c, False)
    if keyp.once("R"):
        run_task(soup)


hint = Text("click: flip · SPACE: run / pause · R: soup · C: clear",
            center=(640, 32), font_size=15, color=Color("light steel blue").with_alpha(0.6))

run_task(build_grid)
run()
