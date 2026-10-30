"""The pilot of engine_video.py: a hand drags b (formulas) and clicks
the lamps (events), on the video's own clock (now(): seconds into it).

    python tools/video/record_game.py videos/scripts/engine/engine_video.py \\
        --pilot videos/scripts/engine/engine_video_pilots.py:show --seconds 214.5 \\
        --size 2560x1440 --crf 14 --out $PWD/videos/recordings/engine/scena_engine.mp4
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "kit"))
from paths import REPO     # noqa: E402
sys.path.insert(0, os.path.join(REPO, "tools", "video"))
from pilots import tour     # noqa: E402

FORMULAS = 34.0
EVENTS = 62.0
LAMP = [(720 + 110 * k, 330) for k in range(5)]

SCRIPT = (
    ("carry", FORMULAS + 8.6, FORMULAS + 10.8, (1060, 420), (1020, 520)),
    ("carry", FORMULAS + 11.8, FORMULAS + 13.6, (1020, 520), (850, 460)),
    ("carry", FORMULAS + 18.6, FORMULAS + 21.0, (850, 460), (1090, 270)),
    ("glide", FORMULAS + 21.6, FORMULAS + 22.6, (1210, 110)),
    ("click", EVENTS + 8.0, LAMP[0]),
    ("click", EVENTS + 9.6, LAMP[1]),
    ("click", EVENTS + 11.2, LAMP[2]),
    ("click", EVENTS + 12.8, LAMP[2]),
    ("click", EVENTS + 14.4, LAMP[2]),
    ("click", EVENTS + 16.0, LAMP[3]),
    ("click", EVENTS + 17.6, LAMP[4]),
    ("glide", EVENTS + 18.2, EVENTS + 19.2, (1210, 110)),
)
SHOWN = ((FORMULAS + 7.6, FORMULAS + 22.8), (EVENTS + 7.0, EVENTS + 19.4))


def show(game, t):
    now = game.ns["now"]()
    tour(game, now, script=SCRIPT, end=1e9)
    game.cursor = any(a <= now < b for a, b in SHOWN)
