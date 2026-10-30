"""The pilot of the third teaser (teaser3.py): a person at the mouse.

It plays the widgets of the interfaces act and the effects' sliders, on the
teaser's own clock (now(), seconds into the teaser): the times are the
teaser's. The pointer shows only while it works.

    python tools/video/record_game.py videos/scripts/teaser3/teaser3.py \\
        --pilot videos/scripts/teaser3/teaser3_pilots.py:show --seconds 153.3 --size 2560x1440 \\
        --prores --out $PWD/videos/recordings/masters.nosync/teaser3.mov
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "kit"))
from paths import REPO     # noqa: E402
sys.path.insert(0, os.path.join(REPO, "tools", "video"))
from pilots import tour     # noqa: E402

LOOP = 1.9675       # the bar the music plays twice, in the stairs (teaser3.py)
UI = 76.0 + LOOP    # the interfaces act
FX = 110.0 + LOOP   # the effects act

SCRIPT = (
    ("drag", "Petals", 6, 12, UI + 1.2, UI + 2.4),
    ("drag", "Spin", 30, 160, UI + 3.0, UI + 4.0),
    ("click", UI + 4.6, "dropdown"),
    ("click", UI + 5.4, "option:Flame"),
    ("click", UI + 6.4, "Trail"),
    ("path", UI + 7.4, UI + 9.3, "orbit", (860, 360, 95, 95, 0.7)),
    ("click", UI + 9.9, (860, 360)),
    ("carry", UI + 10.9, UI + 11.8, (860, 360), (760, 300)),
    ("click", UI + 12.3, "Bloom"),
    ("glide", UI + 12.9, UI + 13.6, (1180, 120)),
    # every effect has its knobs (an effect's sliders live 3.9 s from FX + 0.6 + 4.1 k)
    ("drag", "amount", 1.0, 3.0, FX + 1.5, FX + 2.4),
    ("drag", "width", 3, 11, FX + 2.9, FX + 4.0),
    ("drag", "height", 0.5, 1.0, FX + 5.6, FX + 6.6),
    ("drag", "speed", 0.9, 3.5, FX + 7.1, FX + 8.2),
    ("drag", "weight", 0.04, 0.12, FX + 9.7, FX + 10.7),
    ("drag", "decay", 0.9, 0.97, FX + 11.2, FX + 12.3),
    ("glide", FX + 12.4, FX + 13.0, (1180, 120)),
)
SHOWN = ((UI + 0.2, UI + 14.0), (FX + 0.7, FX + 12.9))     # the pointer is in view


def show(game, t):
    now = game.ns["now"]()
    tour(game, now, script=SCRIPT, end=1e9)
    game.cursor = any(a <= now < b for a, b in SHOWN)


# The vertical cut (teaser3_vertical.py): the Neon knobs, from 17 s.
V_FX = 17.0
V_SCRIPT = (
    ("drag", "amount", 1.0, 3.0, V_FX + 0.9, V_FX + 1.8),
    ("drag", "width", 3, 11, V_FX + 2.2, V_FX + 3.2),
    ("drag", "flicker", 0, 0.6, V_FX + 3.5, V_FX + 4.3),
)
V_SHOWN = ((V_FX + 0.1, V_FX + 4.8),)


def show_vertical(game, t):
    now = game.ns["now"]()
    tour(game, now, script=V_SCRIPT, end=1e9)
    game.cursor = any(a <= now < b for a, b in V_SHOWN)
