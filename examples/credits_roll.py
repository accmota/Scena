"""Credits Roll.

The end credits of the engine. Every name on the list is a part of Scena,
and while its name is on screen, that part performs itself: History keeps
a trail and lets the oldest dot go, the camera turns to look at its own
name, dissolve_out leaves letter by letter. Like film credits: one name at
a time, a calm and steady roll, and at the end it starts again.

  Track begin / end      its frame and its underline draw themselves
  History                a trail of dots that forgets the oldest
  Triangle's base_ratio  a frieze of triangles, from needle to roof
  Concave                four boxes carve a hole, and a ball fills it
  blend = "difference"   two discs cross the name and turn it inside out
  move_along             a little procession walks the eight
  the impacts            zap, ripple, explosion, fireworks: each on its name
  @=                     nine squares, each one following the one before
  Kaleidoscope           a few gems, seen eight times
  the spatial effects    Fire, Portal, Orb and Sunburst under their names
  the camera             it tilts and zooms to read its own name
  the looks              Neon, Metal and Gel dress up three plates
  ColorSweep             a sunflower grows, and the sweep paints it
  Bloom                  a marquee of bulbs, and the light turned up
  dissolve_out           its letters leave, each one in its own style
  and to you             the whole cast comes back for a bow

One async script at the bottom of the file, roll(), is the running order.
Each greet is a small async function: it puts up its name, builds its
performer, waits, and leaves.

Things to try
-------------
  Reorder GREETS        the roll follows the list
  Add your own greet    a credit(...), a performer, await wait, await leave
  Change HOLD           a slower or faster roll

Controls
--------
  none: sit back, the roll loops forever (close the window to stop)

Use
---
    python examples/credits_roll.py
"""

from math import sin, cos, pi
from scena import *

init(width=1280, height=800, title="Credits Roll")

NAME_FONT = "fonts/Quantico-Bold.ttf"
NOTE_FONT = "fonts/Quantico-Italic.ttf"
SMALL_FONT = "fonts/Quantico-Regular.ttf"

CAPTION = Color("light steel blue").with_alpha(0.75)   # "greetings to"
NOTE = Color("wheat").with_alpha(0.8)                   # the note under a name
HOLD = 3.0          # seconds a name stays on screen after it rises

# ---- the stage: stays for the whole roll ----

SkyGradient(top="black", middle="midnight blue", bottom="black")
Stars(density=0.7, twinkle=0.5)
light = Bloom(intensity=0.6)
Vignette(amount=0.8)

st.light = 0.6      # the Bloom's strength: the Bloom greet turns it up
st.number = 0       # which greet is on screen (0: none)
st.rim = 0          # Concave: the solid left at the ends of its curve
st.ring = 1         # finale: 1 the cast in a ring · 0 all in the middle


class Card(Act):
    """A blank act. change_act(Card) sweeps the last greet away: its shapes,
    effects, posts and camera moves all leave together."""


def rise(text, center, font, size, color, layer="default"):
    """One line of the credits: born a little low, it rises into place
    as it fades in."""
    x, y = center
    line = Text(text, center=(x, y - 26), font=font, font_size=size, color=color, layer=layer)
    line.move_by(0, 26, time=0.9, ease="ease_out")
    line.fade_in(0.9)
    return line


def credit(name, note, center=(640, 440), size=72, layer="default"):
    """A credit: 'greetings to', the name, and a note under it. The name
    keeps the other lines in .others, so they leave together."""
    x, y = center
    gap = size * 0.9
    title = rise(name, (x, y), NAME_FONT, size, "white", layer)
    title.others = [rise("greetings to", (x, y + gap), SMALL_FONT, 20, CAPTION, layer),
                    rise(note, (x, y - gap), NOTE_FONT, 22, NOTE, layer)]
    return title


async def leave(title):
    """The lines rise on and fade, while the curtain closes on the rest."""
    for line in [title] + title.others:
        line.move_by(0, 26, time=0.8, ease="ease_in")
        line.fade_out(0.8)
    canvas.fade_out(1.0)
    await wait(1.1)     # fade_out is not awaitable: wait for it


# ---- the greets, in the order they roll ----

async def track_window():
    title = credit("Track  begin / end", "for drawing every line by halves")
    await wait(0.7)
    # a frame around the credit; hidden, it only lends its outline
    frame = Rect(center=(640, 440), width=title.box.width + 140, height=230, corner_radius=22)
    frame.visible = False
    border = Track(frame, color=Color("light steel blue").with_alpha(0.3), line_width=1.5)
    border.end = 0
    tween(border["end"], 1, time=1.6, ease="ease_in_out")
    # the underline grows from the middle: begin goes left, end goes right
    half = title.box.width / 2
    under = Track(points=[(640 - half, 394), (640 + half, 394)], smooth=0,
                  color="goldenrod", line_width=3)
    under.begin = 0.5
    under.end = 0.5
    tween(under["begin"], 0, time=1.2, ease="ease_out")
    tween(under["end"], 1, time=1.2, ease="ease_out")
    await wait(1.0)
    # a comet runs round the frame: three windows that end at the same head
    for length, color, width in ((0.16, Color("cyan").with_alpha(0.25), 2),
                                 (0.07, Color("cyan").with_alpha(0.6), 3),
                                 (0.015, "white", 4)):
        comet = Track(frame, color=color, line_width=width)
        comet["end"] @= lambda: clock.time * 0.3 % 1
        comet["begin"] @= lambda length=length: (clock.time * 0.3 - length) % 1
    await wait(HOLD - 0.8)
    await leave(title)


def drop_dot(mover, trail):
    """A dot where the mover is now; its colour walks round the wheel."""
    dot = trail.add(Circle(center=mover.center, radius=6,
                           color=Color.from_hsv(clock.time * 0.2 % 1, 0.55, 1)))
    dot.line = None
    tween(dot["radius"], 2, time=2.4)


async def history():
    title = credit("History", "for keeping the newest forty, and letting the oldest go")
    # the History holds the last 40 dots; the oldest one leaves dissolving
    trail = History(max_points=40, on_leave=lambda dot: dot.dissolve_out(0.5))
    mover = Circle(center=(640, 230), radius=8, color="white")
    mover.move_along(Track.eight(center=(640, 230), width=620, height=70),
                     time=4, loops="forever")
    mover.every(0.06, lambda: drop_dot(mover, trail))
    await wait(HOLD + 0.8)
    await leave(title)


async def base_ratio():
    title = credit("Triangle's base_ratio", "for every triangle between a needle and a roof")
    # a frieze: one up, one down; each breathes a little after its neighbour
    for i in range(19):
        up = i % 2 == 0
        tri = Triangle(center=(640 + (i - 9) * 50, 215 if up else 243),
                       radius=56, angle=90 if up else -90)
        tri["base_ratio"] @= lambda i=i: 0.7 + 0.55 * sin(clock.time * 2.2 - i * 0.4)
        tri.fill = Color.from_hsv(0.48 + i * 0.014, 0.6, 1).with_alpha(0.85)
        tri.line = None
    await wait(HOLD + 0.8)
    await leave(title)


async def concave():
    title = credit("Concave", "for the hole in the middle")
    # four boxes, each scooped at the corner that touches the middle
    st.rim = 106
    for scoop, dx, dy in (("bottom_right", -1, 1), ("bottom_left", 1, 1),
                          ("top_right", -1, -1), ("top_left", 1, -1)):
        piece = Concave(center=(640 + dx * 55, 230 + dy * 55), width=110, height=110,
                        scoop=scoop)
        piece.rim @= lambda: st.rim
        piece.fill = Gradient("medium slate blue", "midnight blue", angle=-90)
        piece.line = None
    await wait(0.8)
    await tween(st["rim"], 4, time=1.6, ease="ease_in_out")
    # something to put in it, and the hole breathes around it
    ball = Circle(center=(640, 230), radius=2)
    ball.visual = Sphere("orange")
    await tween(ball["radius"], 66, time=0.9, ease="elastic")
    breath = tween(st["rim"], 34, time=0.8, ease="ease_in_out", loops="forever", yoyo=True)
    await wait(HOLD - 2.6)
    # st outlives the act: stop the breath, or it runs on into the next roll
    breath.cancel()
    await leave(title)


async def difference():
    title = credit('blend = "difference"', "for seeing everything the other way round")
    # where a disc covers something, it shows its opposite
    across = Circle(center=(250, 440), radius=120, color="white")
    across.blend = "difference"
    across.move_to((1030, 440), time=2.2, ease="ease_in_out", loops="forever", yoyo=True)
    down = Circle(center=(640, 640), radius=80, color="deep sky blue")
    down.blend = "difference"
    down.move_to((640, 220), time=1.6, ease="ease_in_out", loops="forever", yoyo=True)
    await wait(HOLD + 0.8)
    await leave(title)


async def procession():
    title = credit("move_along", "for walking the eight, again and again")
    path = Track.eight(center=(640, 225), width=640, height=75,
                       color=Color("white").with_alpha(0.12), line_width=1.5)
    # a little parade, one step apart (phase), each facing where it walks
    for i in range(16):
        if i % 3 == 0:
            walker = Circle(radius=10)
        elif i % 3 == 1:
            walker = Square(length=17)
        else:
            walker = Triangle(radius=13)
        walker.fill = Color.from_hsv(i / 16, 0.6, 1)
        walker.line = None
        walker.move_along(path, time=10, loops="forever", phase=0.5 - i * 0.03, face=True)
    await wait(HOLD + 0.8)
    await leave(title)


async def impacts():
    title = credit("the impacts", "each one fired on its own name", center=(640, 580), size=56)
    # zap_at: sparks run along the letters
    zap = rise("zap_at", (400, 400), NAME_FONT, 46, "light cyan")
    title.others.append(zap)
    await wait(1.0)
    for k in range(4):
        canvas.zap_at(400 - 75 + k * 50, 400, style="fork", color="cyan", radius=50)
        await wait(0.1)
    await wait(0.4)
    # ripple_at: the picture warps from the name
    ripple = rise("ripple_at", (880, 400), NAME_FONT, 46, "light sky blue")
    title.others.append(ripple)
    await wait(0.9)
    canvas.ripple_at(880, 400, amount=0.9, radius=320)
    await wait(0.6)
    # explosion_at: the name blows up (but stays, it is a credit)
    boom = rise("explosion_at", (400, 230), NAME_FONT, 46, "orange")
    title.others.append(boom)
    await wait(0.9)
    canvas.explosion_at(400, 230, amount=1.0)
    await wait(0.6)
    # fireworks_at: a celebration over the name
    fireworks = rise("fireworks_at", (880, 230), NAME_FONT, 46, "plum")
    title.others.append(fireworks)
    await wait(0.9)
    for dx, dy, color in ((-110, 70, "gold"), (0, 100, "magenta"), (110, 70, "cyan")):
        canvas.fireworks_at(880 + dx, 230 + dy, color=color, radius=70)
        await wait(0.25)
    await wait(1.0)
    await leave(title)


async def links():
    title = credit("@=", "for letting one thing follow another", size=84)
    # the leader turns and breathes; each square copies the one before it,
    # a little more turned and a little smaller
    leader = Square(center=(640, 225), length=170, angle=0)
    leader.fill = None
    leader.line = "gold"
    leader.line_width = 2.5
    leader.rotate_by(360, time=9, loops="forever")
    tween(leader["length"], 120, time=1.6, ease="ease_in_out", loops="forever", yoyo=True)
    before = leader
    for i in range(1, 10):
        square = Square(center=(640, 225), length=170)
        square["angle"] @= lambda before=before: before.angle + 10
        square["length"] @= lambda before=before: before.length * 0.86
        square.fill = None
        square.line = Color.from_hsv(0.13 - i * 0.025, 0.7, 1)
        square.line_width = 2.5
        before = square
    title.others.append(rise("square.angle @= lambda: before.angle + 10",
                             (640, 92), SMALL_FONT, 18, CAPTION))
    await wait(HOLD + 0.8)
    await leave(title)


async def kaleidoscope():
    # on the ui layer the words are drawn after the posts: the mirrors leave them alone
    title = credit("Kaleidoscope", "for seeing everything eight times", layer="ui")
    Kaleidoscope(segments=8, spin=0.15)
    # a few gems on circles of their own; the mirrors make a mandala of them
    for i in range(12):
        if i % 2:
            gem = Triangle(radius=14 + i * 1.5)
        else:
            gem = Square(length=12 + i * 1.5)
        gem.fill = Color.from_hsv(i / 12, 0.7, 1)
        gem.line = None
        gem.move_along(Track.circle(center=(640, 400), radius=50 + i * 28),
                       time=4 + i * 0.5, loops="forever", phase=i * 0.37, face=True)
    await wait(HOLD + 0.8)
    await leave(title)


def under_name(title, label, x):
    """One of a row of names; it joins the credit's other lines."""
    title.others.append(rise(label, (x, 420), NAME_FONT, 40, "white"))
    canvas.hit_at(x, 270, style="disc", radius=46, color="white")


async def spatial():
    title = credit("the spatial effects", "each one under its own name", center=(640, 600), size=56)
    await wait(0.6)
    under_name(title, "Fire", 250)
    Fire(center=(250, 215), width=70, style="tongues")
    await wait(0.6)
    under_name(title, "Portal", 510)
    Portal(center=(510, 280), radius=60, color="magenta")
    await wait(0.6)
    under_name(title, "Orb", 770)
    Orb(center=(770, 280), radius=50)
    await wait(0.6)
    under_name(title, "Sunburst", 1030)
    Sunburst(center=(1030, 280), radius=60)
    await wait(HOLD - 0.4)
    await leave(title)


async def camera():
    title = credit("the camera", "for looking wherever it is told", center=(1010, 620), size=44)
    # a viewfinder round the name: four corner brackets and a REC light
    for sx in (-1, 1):
        for sy in (-1, 1):
            corner = (1010 + sx * 190, 620 + sy * 90)
            Line(p1=corner, p2=(corner[0] - sx * 30, corner[1]), color="white", line_width=2)
            Line(p1=corner, p2=(corner[0], corner[1] - sy * 30), color="white", line_width=2)
    rec = Circle(center=(840, 690), radius=6, color="red")
    rec["visible"] @= lambda: clock.time % 1 < 0.6
    Text("REC", center=(870, 690), font=SMALL_FONT, font_size=14, color="white")
    await wait(1.4)
    await parallel(canvas.pan_to(1010, 620, time=1.8, ease="ease_in_out"),
                   canvas.zoom_to(2.2, time=1.8, ease="ease_in_out"),
                   canvas.rotate_to(-8, time=1.8, ease="ease_in_out"))
    await canvas.rotate_to(0, time=0.8, ease="ease_in_out")
    await wait(1.0)
    await canvas.reset_view(time=1.2, ease="ease_in_out")
    await leave(title)


async def looks():
    title = credit("the looks", "who dress up a plate", center=(640, 580), size=56)
    await wait(0.6)
    for label, look, ink, x in (("Neon", Neon("deep pink"), "white", 330),
                                ("Metal", Metal(), "black", 640),
                                ("Gel", Gel("deep sky blue"), "white", 950)):
        plate = Rect(center=(x, 320), width=230, height=84, corner_radius=26)
        plate.visual = look
        plate.pop(scale=1.15)
        title.others.append(rise(label, (x, 320), NAME_FONT, 40, ink))
        await wait(0.6)
    await wait(HOLD - 0.6)
    await leave(title)


async def color_sweep():
    title = credit("ColorSweep", "for painting everything at once")
    ColorSweep(axis="radial", colors=["magenta", "gold", "cyan", "lime"], amount=1,
               saturation=1, speed=1.5)
    # a sunflower of white seeds for it to paint: each seed turned by the
    # golden angle from the one before, and a little further out
    seeds = []
    for n in range(170):
        r = 8.6 * n ** 0.5
        a = n * 2.39996
        seed = Circle(center=(640 + r * cos(a), 225 + r * sin(a)), radius=2 + n / 60,
                      color="white")
        seed.line = None
        seed.visible = False
        seeds.append(seed)
    # it grows from the middle out
    for seed in seeds:
        seed.visible = True
        await wait(0.008)
    await wait(HOLD - 0.4)
    await leave(title)


async def bloom():
    title = credit("Bloom", "for making everything a little brighter than it is")
    # a theatre marquee: bulbs round a frame, the light chasing round them
    frame = Rect(center=(640, 440), width=620, height=270, corner_radius=30)
    frame.visible = False
    edge = Track(frame)
    for i in range(60):
        bulb = Circle(center=edge.at(i / 60), radius=6)
        bulb.line = None
        bulb["fill"] @= lambda i=i: "white" if (int(clock.time * 9) + i) % 4 == 0 else "dim gray"
    await wait(1.0)
    await tween(st["light"], 2.6, time=1.4, ease="ease_in_out")
    await tween(st["light"], 0.6, time=1.4, ease="ease_in_out")
    await wait(HOLD - 2.6)
    await leave(title)


async def dissolve():
    # one Text per letter, so that each one can leave on its own
    letters = []
    width = 0
    for ch in "dissolve_out":
        letter = Text(ch, center=(640, 414), font=NAME_FONT, font_size=72)
        letters.append(letter)
        width += letter.box.width
    x = 640 - width / 2
    for letter in letters:
        letter.center = (x + letter.box.width / 2, 414)
        x += letter.box.width
        letter.move_by(0, 26, time=0.9, ease="ease_out")
        letter.fade_in(0.9)
    hello = rise("greetings to", (640, 505), SMALL_FONT, 20, CAPTION)
    note = rise("for knowing how to leave", (640, 375), NOTE_FONT, 22, NOTE)
    await wait(HOLD - 1.2)
    # they leave from the last one, each floating up in a different style
    styles = ["vortex", "noise", "wipe", "fade"]
    for i in range(len(letters)):
        letter = letters[len(letters) - 1 - i]
        letter.move_by(0, 40, time=1.2, ease="ease_in")
        letter.dissolve_out(1.2, style=styles[i % 4])
        await wait(0.22)
    await wait(0.8)
    hello.others = [note]
    await leave(hello)


GREETS = [track_window, history, base_ratio, concave, difference, procession, impacts,
          links, kaleidoscope, spatial, camera, looks, color_sweep, bloom, dissolve]


# ---- the opening and the finale ----

async def opening():
    title = rise("SCENA", (640, 480), NAME_FONT, 150, "white")
    title.fill = Gradient("white", "goldenrod", angle=-90)
    rule = Rect(center=(640, 385), width=4, height=2, color="goldenrod")
    tween(rule["width"], 620, time=1.6, ease="ease_in_out")
    title.others = [rise("the end credits", (640, 340), SMALL_FONT, 28, CAPTION),
                    rise("in which the engine thanks its parts", (640, 296), NOTE_FONT, 22, NOTE)]
    await wait(3.8)
    await leave(title)


def ring_place(i, count, below=0):
    """Where member i of the cast stands: on a slowly turning ring that
    shrinks to the middle as st.ring goes to 0. below= is for its name tag."""
    a = 2 * pi * i / count + clock.time * 0.3
    return (640 + 420 * st.ring * cos(a), 430 + 270 * st.ring * sin(a) - below)


async def finale():
    title = credit("and to you", "for watching to the very end", size=84)
    st.ring = 1
    # the cast comes back for a bow, small, each one with its name tag
    breathing = Triangle(radius=24, angle=90, color="turquoise")
    breathing["base_ratio"] @= lambda: 0.95 + 0.8 * sin(clock.time * 2.2)
    scooped = Concave(width=44, height=44, scoop="top_right", color="medium slate blue")
    follower = Square(length=34)
    follower.fill = None
    follower.line = "goldenrod"
    follower["angle"] @= lambda: clock.time * 60
    inverted = Circle(radius=24, color="white")
    inverted.blend = "difference"
    neon = Rect(width=64, height=26, corner_radius=10)
    neon.visual = Neon("deep pink")
    metal = Rect(width=64, height=26, corner_radius=10)
    metal.visual = Metal()
    gel = Rect(width=64, height=26, corner_radius=10)
    gel.visual = Gel("deep sky blue")
    cast = [(breathing, "base_ratio"), (Fire(width=26, style="tongues"), "Fire"), (scooped, "Concave"),
            (Portal(radius=26, color="magenta"), "Portal"), (follower, "@="),
            (neon, "Neon"), (Orb(radius=22), "Orb"), (inverted, "difference"),
            (metal, "Metal"), (Sunburst(radius=28), "Sunburst"), (gel, "Gel"),
            (Circle(radius=8, color="white"), "History")]
    tags = []
    for i in range(len(cast)):
        member, name = cast[i]
        member["center"] @= lambda i=i: ring_place(i, len(cast))
        tags.append(Text(name, center=lambda i=i: ring_place(i, len(cast), below=42),
                         font=SMALL_FONT, font_size=14, color=CAPTION))
    await wait(4.0)
    # they all run to the middle, and the show ends with a bang
    await tween(st["ring"], 0, time=1.0, ease="ease_in")
    for member, name in cast:
        member.destroy()
    for tag in tags:
        tag.destroy()
    canvas.explosion_at(640, 430, amount=1.6)
    canvas.flash(0.7)
    for x, y, color in ((380, 600, "gold"), (900, 620, "magenta"), (640, 680, "cyan"),
                        (300, 250, "violet"), (980, 240, "lime")):
        await wait(0.3)
        canvas.fireworks_at(x, y, color=color, radius=90)
    await wait(2.0)
    await leave(title)


# ---- the running order ----

async def roll():
    await wait(0.5)         # change_act needs the game running
    while True:
        st.number = 0
        change_act(Card)
        canvas.fade_in(1.0)
        await opening()
        for greet in GREETS:
            change_act(Card)
            st.number += 1
            canvas.fade_in(0.6)
            await greet()
        st.number = 0
        change_act(Card)
        canvas.fade_in(0.6)
        await finale()


# the footer: a thin rule, the show's name, and which greet this is
Line(p1=(80, 64), p2=(1200, 64), color=Color("light steel blue").with_alpha(0.2), layer="ui")
Text("SCENA  ·  END CREDITS", top_left=(80, 54), font=SMALL_FONT, font_size=13,
     color=CAPTION, stack=False)
Text(lambda: f"{st.number:02d} / {len(GREETS)}" if st.number else "", top_right=(1200, 54),
     font=SMALL_FONT, font_size=13, color=CAPTION, stack=False)


def update(dt):
    # a Post cannot be linked or tweened: copy the Bloom's strength from st
    light.intensity = st.light


run_task(roll)
run(Card)
