"""Shared art for the hitbox / look galleries: tracked files in ``examples/media/``.

Not a smoke script (``_`` prefix: ``tests/test_scripts_run.py`` skips it).
Paths are absolute, so the same file never loses to a basename elsewhere.
"""
from __future__ import annotations

from pathlib import Path

MEDIA = Path(__file__).resolve().parents[2] / "examples" / "media"

# Single PNGs: varied silhouettes for auto-hitbox picks (tall, wide, round,
# star, thin bar, sparse).
HITBOX_SINGLES = (
    "ninja/Attack__002.png",
    "ninja/Climb_003.png",
    "ninja/Dead__006.png",
    "ninja/Glide_004.png",
    "ninja/Idle__003.png",
    "ninja/Slide__003.png",
    "plane/Fly1.png",
    "plane/Fly2.png",
    "robot/Idle (1).png",
    "space/star_gold.png",
    "space/enemyBlue2.png",
    "space/playerShip1_red.png",
    "space/laserRed03.png",
    "space/laserBlue03.png",
    "k-rolling-ball/star.png",
)

# (png, xml) packed atlases.
HITBOX_ATLASES = (
    ("shooter/sheet.png", "shooter/sheet.xml"),
    ("k-rolling-ball/rollingBall_sheet.png", "k-rolling-ball/rollingBall_sheet.xml"),
)

# Horizontal strips with their column counts (grid-sheet art).
STRIPS = {
    "pixel_adv/Start (Moving) (64x64).png": 17,
    "pixel_adv/Checkpoint (Flag Idle)(64x64).png": 10,
    "pixel_adv/End (Idle).png": 1,
}


def path(rel: str) -> str:
    """Absolute path of ``examples/media/<rel>``."""
    return str(MEDIA / rel)
