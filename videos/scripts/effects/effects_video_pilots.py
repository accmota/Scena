"""The pilot of effects_video.py: the screen effects that follow the
mouse (Vortex, Lamp, Spotlight …) follow a slow circle; no pointer is drawn."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "kit"))
from paths import REPO     # noqa: E402
sys.path.insert(0, os.path.join(REPO, "tools", "video"))
from pilots import _path     # noqa: E402


def pilot(game, t):
    k = game.ns["now"]()
    game.mouse(*_path("orbit", (640, 360, 260, 130, 0.25), k, 0.0))
    game.cursor = False
