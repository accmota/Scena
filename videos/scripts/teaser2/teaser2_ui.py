"""Widgets: the UI scene of the second teaser.

A star that turns, the widgets that drive it, and cards to pick up and drop
in two slots. Played by teaser2_pilots.py (ui_tour), which clicks,
drags and hovers like a person; the teaser shows the lines that do each part.

Controls
--------
  MOUSE          click the star; hover and drag the cards; the widgets on the left
"""

from math import cos, sin
from scena import *

init(width=1280, height=720, title="Widgets")
Nebula(color="dark cyan", color2="midnight blue", alpha=0.5)
Bloom(intensity=0.5)

st.speed = 40
st.look = "Neon"
st.trail = False
LOOKS = {"Neon": lambda: Neon("gold"), "Flame": Flame, "Metal": Metal,
         "ElectricField": ElectricField}

star = RegularPolygon(n=5, radius=95, color="gold")
star["center"] @= lambda: (820 + 70 * cos(clock.time * 1.3), 520 + 40 * sin(clock.time * 1.3))
star.shown_look = None


@click(star)
def poke(star):
    star.pop(scale=1.3)
    canvas.zap_at(star, radius=90, color="gold")


# the cards, and the two slots they can be dropped in
slots = [Rect(center=(700 + 240 * k, 300), width=110, height=150, corner_radius=12,
              color="#0b1d24", group="slots") for k in range(2)]
for slot in slots:
    slot.line = "light cyan"
    slot.line_width = 2
cards = []
for k, color in enumerate(("coral", "turquoise", "gold", "orchid")):
    card = Rect(center=(420 + 130 * k, 120), width=96, height=136, corner_radius=12,
                color=color, group="cards", layer="top")
    card.home = (card.center.x, card.center.y)     # a snapshot: center is live
    card.draggable = True
    cards.append(card)


@hover(group["cards"])
def lift(card):
    card.scale_to(1.12, time=0.12)


@hover_exit(group["cards"])
def settle(card):
    card.scale_to(1.0, time=0.12)


@drag_to(group["cards"])
def dropped(card, target, pos):
    slot = min(slots, key=lambda s: distance(s.center, pos))
    if distance(slot.center, pos) < 90:
        card.move_to(slot.center, time=0.25, ease="ease_out")
        canvas.hit_at(slot, color="light cyan")
    else:
        card.move_to(card.home, time=0.3)


def deal():
    for k, card in enumerate(cards):
        card.move_to(card.home, time=0.4 + 0.08 * k, ease="ease_in_out")


ui.scale = 1.5
Slider(st["speed"], label="Speed", min_value=0, max_value=300)
DropDown(st["look"], options=list(LOOKS))
CheckBox(st["trail"], label="Trail")
Button(label="Deal", on_click=deal)


def update(dt):
    star.angle += st.speed * dt
    if star.shown_look != st.look:
        star.shown_look = st.look
        star.visual = LOOKS[st.look]()
    if st.trail and star.tail is None:
        star.tail = Tail(color="gold", size=6)
    elif not st.trail and star.tail is not None:
        star.tail = None


run()
