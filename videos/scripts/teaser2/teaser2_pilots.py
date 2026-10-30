"""Pilots of the second teaser's own programs (teaser2_ui.py).

The timetable is shared: the teaser shows each line of code at the time the
pilot does what it says.

    python tools/video/record_game.py videos/scripts/teaser2/teaser2_ui.py \\
        --pilot videos/scripts/teaser2/teaser2_pilots.py:ui_tour --seconds 14.5 \\
        --size 2560x1440 --out $PWD/videos/recordings/teaser2_ui/tour.mp4
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "kit"))
from paths import REPO     # noqa: E402
sys.path.insert(0, os.path.join(REPO, "tools", "video"))
from pilots import tour     # noqa: E402

# (time, what the pilot does, the line the teaser shows then)
UI_STEPS = (
    (1.4, ("click", 1.4, "@star"), "@click(star)"),
    (2.6, ("drag", "Speed", 40, 260, 2.6, 4.0), 'Slider(st["speed"], label="Speed", …)'),
    (5.2, ("click", 5.2, "dropdown"), 'DropDown(st["look"], options=list(LOOKS))'),
    (6.0, ("click", 6.0, "option:Flame"), None),
    (7.2, ("click", 7.2, "Trail"), 'CheckBox(st["trail"], label="Trail")'),
    (8.2, ("path", 8.2, 9.4, "orbit", (614, 120, 200, 28, 0.8)), '@hover(group["cards"])'),
    (10.0, ("carry", 10.0, 10.8, (420, 120), (700, 300)), '@drag_to(group["cards"])'),
    (11.5, ("carry", 11.5, 12.3, (680, 120), (940, 300)), None),
    (13.3, ("click", 13.3, "Deal"), 'Button(label="Deal", on_click=deal)'),
)
UI_SECONDS = 14.5


def ui_tour(game, t):
    tour(game, t, script=[step for _, step, _ in UI_STEPS], end=UI_SECONDS)
