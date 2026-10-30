"""Scena: the YouTube channel's art, drawn by Scena (the teasers' look).

One program, one picture per run, picked by CHANNEL_ART:

  avatar     800 x 800    the S, a spark on an orbit (YouTube shows it as a circle)
  banner     2560 x 1440  SCENA and the motto inside the 1546 x 423 middle every
                          device shows; on a wide screen, the spark (BANNER_BG: backdrop)
  thumb      1280 x 720   a video's thumbnail: its title on the left, a still of
                          the video on the right (THUMB_IMAGE, THUMB_TITLE, ...);
                          THUMB_PLAY adds a play mark (the README's video poster)
  thumb_tall 720 x 1280   a Short's cover (drawn at 1080 x 1920): the title on top,
                          the still below, full width (the same THUMB_* settings)

Ember-and-ice palette and Quantico, as in teaser.py and teaser2.py.

Use (frames: the last PNG is the picture; the scene is still)
---
    CHANNEL_ART=avatar python tools/video/record_game.py videos/scripts/channel/channel_art.py \\
        --seconds 0.5 --size 800x800 --supersample 2 --frames-dir /tmp/avatar
    CHANNEL_ART=banner python tools/video/record_game.py videos/scripts/channel/channel_art.py \\
        --seconds 0.5 --size 2560x1440 --frames-dir /tmp/banner
    videos/scripts/channel/make_art.sh does all of them.
"""

import os
from math import cos, sin, radians
from random import seed, uniform
from scena import *

ART = os.environ.get("CHANNEL_ART", "banner")
if ART == "avatar":
    init(width=800, height=800, title="Scena avatar")
elif ART == "thumb_tall":
    init(width=720, height=1280, title="Scena thumb_tall")
else:
    init(width=1280, height=720, title="Scena " + ART)
seed(11)

TITLE_FONT = "fonts/Quantico-Bold.ttf"
NOTE_FONT = "fonts/Quantico-Italic.ttf"
SMALL_FONT = "fonts/Quantico-Regular.ttf"

NIGHT = "#071318"
DEEP = Color("dark cyan")
ICE = Color("turquoise")
FROST = Color("light cyan")
EMBER = Color("coral")
ICE_FILL = Gradient("white", FROST, ICE, angle=-90)

canvas.background = NIGHT


def word(text, center, size, font=TITLE_FONT, fill=None, color="white"):
    """One Text; fill is a Gradient (the title's ice) or None."""
    line = Text(text, center=center, font=font, font_size=size, color=color)
    if fill is not None:
        line.fill = fill
    return line


def flush_left(text, x):
    """Move a Text so its box starts at x (a box is read-only: move the center)."""
    text.center = (text.center.x + x - text.box.left, text.center.y)
    return text


def rule(p1, p2, color=EMBER, width=3):
    return Line(p1=p1, p2=p2, color=color, line_width=width)


def spark(center, radius=6, tail_to=None):
    """The teaser 2 spark: a white glowing dot, a short ember trail behind it."""
    dot = Circle(center=center, radius=radius, color="white")
    dot.glow = True
    if tail_to is not None:
        (x0, y0), (x1, y1) = tail_to, center
        for i in range(1, 6):
            k = i / 6
            Circle(center=(x0 + (x1 - x0) * k, y0 + (y1 - y0) * k),
                   radius=radius * (0.35 + 0.45 * k), color=EMBER.with_alpha(0.15 + 0.6 * k))
    return dot


# ---- avatar: the S inside an orbit, a spark riding it ----

def avatar():
    Stars(color=FROST, density=0.25)
    Bloom(intensity=0.55)
    c = (400, 400)
    # the orbit: a ring of ice, an ember arc on it, the spark at the arc's head
    ring = Track(center=c, radius=290, color=ICE.with_alpha(0.28), line_width=5)
    # the ember arc is the spark's trail: it brightens toward the spark
    start, end, pieces = 0.04, 0.30, 12
    for i in range(pieces):
        arc = Track(center=c, radius=290, line_width=4 + 6 * i / pieces,
                    color=EMBER.with_alpha(0.12 + 0.88 * (i + 1) / pieces))
        arc.begin = start + (end - start) * i / pieces
        arc.end = start + (end - start) * (i + 1) / pieces + 0.002
    dot = Circle(center=ring.at(end), radius=17, color="white")
    dot.glow = True
    word("S", (400, 392), 470, fill=ICE_FILL)


# ---- banner: the title in the middle every device shows ----

# a still: no stars (they read as noise), no lines that only make sense moving;
# a discreet background in the title's colours (BANNER_BG picks one)
BACKDROPS = {
    "borealis": lambda: Borealis(DEEP, amount=0.8, speed=0, height=0.75, alpha=0.5),
    "clouds": lambda: ChurningClouds(DEEP, color2="#0b2a3a", speed=0, contrast=0.8, alpha=0.45),
    "plasma": lambda: Plasma(DEEP, alpha=0.22),
    "stardust": lambda: Stardust(DEEP, color2="#123a4a", speed=0, alpha=0.5),
}


def banner():
    BACKDROPS[os.environ.get("BANNER_BG", "borealis")]()
    Bloom(intensity=0.6)
    Vignette(amount=0.45)
    # the safe middle (1546 x 423 of 2560 x 1440): x 253..1027, y 254..466 here
    # set side by side by their advance, then filled: a shader fill makes a
    # Text's box its tight ink (Effect System Design), which would close the gaps
    row = [word(ch, (640, 384), 118) for ch in "SCENA"]
    x = 640 - sum(t.box.width for t in row) / 2
    for t in row:
        t.center = (x + t.box.width / 2, 384)
        x += t.box.width
    for t in row:
        t.fill = ICE_FILL
    word("2D games and creative graphics in Python", (640, 300), 28,
         font=SMALL_FONT, color=FROST)
    rule((372, 334), (908, 334), EMBER, 3)
    # wider than the safe middle (desktop and TV): the teaser 2 spark, on the right
    if os.environ.get("BANNER_SPARK", "up") == "up":
        spark((1085, 404), 7, tail_to=(1035, 364))      # rising, its trail below
    else:
        spark((1085, 372), 7, tail_to=(1035, 412))      # falling


# ---- thumbnail: a title on the left, a still on the right ----

def title_size(lines, room):
    """The biggest size at which every line fits in room px (measured before the fill)."""
    size = 104
    while True:
        probes = [word(line, (300, 360), size) for line in lines]
        widest = max(p.box.width for p in probes)
        for p in probes:
            p.destroy()
        if widest <= room or size <= 56:
            return size
        size -= 4


def thumb():
    image = os.environ["THUMB_IMAGE"]
    lines = os.environ["THUMB_TITLE"].split("|")
    # "SCENA|Python game engine": the kicker, and under it what Scena is
    kicker, _, tagline = os.environ.get("THUMB_KICKER", "").partition("|")
    footer = os.environ.get("THUMB_FOOTER", "")
    sub = os.environ.get("THUMB_SUB", "")         # a line under the title's underline
    note = os.environ.get("THUMB_NOTE", "")        # "x,y,size:text", over the still
    play = os.environ.get("THUMB_PLAY", "")        # "x,y": a play mark there (the README's poster)
    # no Bloom: it hazes a bright still (Ninja, Race) and the fade over it
    # the still covers the right side, full height, flush with the right edge
    still = Sprite(image, height=720)
    still.center = (1280 - still.box.width / 2, 360)
    # the left side is night, fading into the still
    Rect(p1=(0, 0), p2=(560, 720), color=NIGHT, line_width=0)
    fade = Rect(p1=(559, 0), p2=(800, 720), line_width=0)
    night = Color(NIGHT)
    fade.fill = Gradient((0, night), (0.3, night.with_alpha(0.8)), (0.65, night.with_alpha(0.3)),
                         (1, night.with_alpha(0)), angle=0)     # eased: no edge where it starts
    if kicker:
        top = 632 if tagline else 610
        flush_left(word(kicker, (300, top), 34, font=SMALL_FONT, color=EMBER), 44)
    if tagline:
        flush_left(word(tagline, (300, 592), 30, font=SMALL_FONT, color=FROST), 44)
    size = title_size(lines, 500)
    y = 360 + (len(lines) - 1) * size * 0.52 + (20 if tagline else 40)    # clear of the tagline
    for line in lines:
        t = flush_left(word(line, (300, y), size), 40)
        t.fill = ICE_FILL
        y -= size * 1.04
    under = y + size * 1.04 - size * 0.62
    rule((44, under), (44 + 220, under), EMBER, 6)
    if sub:
        flush_left(word(sub, (300, under - 52), 38, font=SMALL_FONT, color=FROST), 44)
    if footer:
        flush_left(word(footer, (300, 70), 30, font=SMALL_FONT, color=FROST), 44)
    if note:
        # in the videos' caption style (Quantico Italic, frost at 0.7), where the
        # still's own caption was erased (make_art.sh, erase)
        where, _, text = note.partition(":")
        x, y, size = (float(v) for v in where.split(","))
        word(text, (x, y), size, font=NOTE_FONT, color=FROST.with_alpha(0.7))
    if play:
        # on GitHub the poster is a still image: the mark says a click plays it
        x, y = (float(v) for v in play.split(","))
        disc = Circle(center=(x, y), radius=58, line_width=4)
        disc.fill = Color(NIGHT).with_alpha(0.75)
        disc.line = ICE
        Polygon(points=[(x - 18, y + 28), (x - 18, y - 28), (x + 30, y)], color=FROST)


# ---- a Short's cover: the title on top, the still below ----

def thumb_tall():
    image = os.environ["THUMB_IMAGE"]
    lines = os.environ["THUMB_TITLE"].split("|")
    kicker = os.environ.get("THUMB_KICKER", "")
    sub = os.environ.get("THUMB_SUB", "")
    # the still covers the bottom, full width; above it, night fading into it
    still = Sprite(image, width=720)
    still.center = (360, still.box.height / 2)
    top = still.box.height
    Rect(p1=(0, top), p2=(720, 1280), color=NIGHT, line_width=0)
    fade = Rect(p1=(0, top - 220), p2=(720, top + 1), line_width=0)
    night = Color(NIGHT)
    fade.fill = Gradient((0, night), (0.3, night.with_alpha(0.8)), (0.65, night.with_alpha(0.3)),
                         (1, night.with_alpha(0)), angle=-90)
    # the text in the middle band, left of the Shorts buttons on the right edge
    if kicker:
        flush_left(word(kicker, (300, 1150), 38, font=SMALL_FONT, color=EMBER), 48)
    size = title_size(lines, 600)
    y = 1150 - 40 - size * 0.6
    for line in lines:
        t = flush_left(word(line, (300, y), size), 44)
        t.fill = ICE_FILL
        y -= size * 1.04
    under = y + size * 1.04 - size * 0.62
    rule((48, under), (48 + 220, under), EMBER, 6)
    if sub:
        flush_left(word(sub, (300, under - 52), 38, font=SMALL_FONT, color=FROST), 48)


{"avatar": avatar, "banner": banner, "thumb": thumb, "thumb_tall": thumb_tall}[ART]()
run()
