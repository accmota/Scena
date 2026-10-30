"""Media of the salvo teaser (salvo_teaser.py): the music.

  python videos/scripts/salvo/make_media.py

Music: "Battle in the Winter" by Johan Brodd (CC BY 3.0). Bars are 3.2045 s
(the first downbeat after the intro at 6.41 s). The cut keeps the opening up
to the phrase that starts at 19.23 s and joins the phrase at 240.00 s (bar
chroma 0.92, both phrase starts), so the piece's own last chord (256.02 s)
lands at 35.25 s of the video: 0:00-19.23 + 240.00-258.0 = 37.2 s.
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kit"))
from paths import MUSIC, work     # noqa: E402

MUSIC_IN = os.path.join(MUSIC, "battle_in_the_winter.ogg")
MUSIC_OUT = os.path.join(work("salvo"), "winter_cut.wav")
CUT = 19.23           # the opening's phrase start (video seconds)
JOIN = 240.00         # the ending's phrase start (track seconds)
END = 258.0           # after the last chord has rung
XFADE = 0.06


def music():
    h = XFADE / 2
    graph = (f"[0:a]atrim=0:{CUT + h},asetpts=PTS-STARTPTS[a];"
             f"[0:a]atrim={JOIN - h}:{END},asetpts=PTS-STARTPTS[b];"
             f"[a][b]acrossfade=d={XFADE}:c1=tri:c2=tri,afade=t=out:st={CUT + END - JOIN - 1.2}:d=1.2[out]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", MUSIC_IN, "-filter_complex", graph,
                    "-map", "[out]", "-ar", "44100", MUSIC_OUT], check=True)


if __name__ == "__main__":
    music()
