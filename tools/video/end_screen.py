"""The end screen of the build-up videos: five seconds of the name, what it
is, how to install it and where it lives, in the teasers' ember-and-ice.

The text arrives in the first second and a half and then holds still to the
last frame (no fade: the install line is readable to the end); an underline
grows out from the middle of the name, and a white spark with a tomato tail
goes once round the card. ``buildup.py`` records it (``render_end_screen``) as
``examples/end_screen.py``, so its fonts resolve from ``examples/media``.

  python tools/video/buildup.py --end-screen    # videos/recordings/buildup/end_screen/end_screen.mp4
"""
from math import cos, sin, tau
from scena import *

init(width=1280, height=720, title="Scena")

TITLE_FONT = "fonts/Quantico-Bold.ttf"
SMALL_FONT = "fonts/Quantico-Regular.ttf"
MONO = "fonts/JetBrainsMonoNLNerdFontMono-Regular.ttf"
NIGHT = "#071318"
ICE = Color("turquoise")
FROST = Color("light cyan")
EMBER = Color("coral")
FLARE = Color("tomato")
SECONDS = 5.0           # the spark goes round once in this long

canvas.background = NIGHT
Stars(color=FROST, density=0.3, twinkle=0.4)


def rise(text, center, font, size, color, delay, time=0.7):
    """A line that is born a little low and rises into place as it fades in."""
    x, y = center
    line = Text(text, center=(x, y - 16), font=font, font_size=size, color=color)
    line.visible = False

    def show():
        line.visible = True
        line.fade_in(time)
        line.move_by(0, 16, time=time, ease="ease_out")

    after(delay, show)
    return line


name = rise("SCENA", (640, 470), TITLE_FONT, 150, "white", 0.0, time=0.8)
name.fill = Gradient("white", FROST, ICE, angle=-90)

# an underline of light grows out from the middle of the name (where it will rest)
y = name.box.bottom + 16 - 12
rule = Track(points=[(name.box.left, y), (name.box.right, y)], smooth=0, color=EMBER,
             line_width=3)
rule.begin = 0.5
rule.end = 0.5


def grow():
    tween(rule["begin"], 0, time=1.0, ease="ease_out")
    tween(rule["end"], 1, time=1.0, ease="ease_out")


after(0.3, grow)

rise("2D games and creative coding in Python", (640, 330), SMALL_FONT, 32, FROST, 0.4)
rise("pip install scena", (640, 244), MONO, 30, FROST, 0.7)
rise("github.com/accmota/Scena", (640, 196), SMALL_FONT, 24, FROST.with_alpha(0.7), 0.9)

# a spark goes once round the card, well clear of the text
spark = Circle(radius=6, color="white")
spark.glow = True
spark["center"] @= lambda: (640 + 560 * cos(tau * clock.time / SECONDS + 1.2),
                            360 + 265 * sin(tau * clock.time / SECONDS + 1.2))
spark.tail = Tail(color=FLARE, size=3)

run()
