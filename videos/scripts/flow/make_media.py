"""Media of the flow teaser (flow_teaser.py): the music.

  python videos/scripts/flow/make_media.py

Music: "Space (orchestral)" by lasercheese (CC BY 3.0), from its entrance at
39.85 s (the swell after the quiet middle) to its own ending (81.7 s): 41.9 s.
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kit"))
from paths import MUSIC, work     # noqa: E402

MUSIC_IN = os.path.join(MUSIC, "space.ogg")
MUSIC_OUT = os.path.join(work("flow"), "space_cut.wav")
START = 39.85


def music():
    graph = f"atrim={START},asetpts=PTS-STARTPTS,afade=t=in:d=0.08"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", MUSIC_IN, "-af", graph, "-ar", "44100",
                    MUSIC_OUT], check=True)


if __name__ == "__main__":
    music()
