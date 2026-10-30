"""Media of the second teaser (teaser2.py): the music.

  python videos/scripts/teaser2/make_media.py

Music: "Battle Theme A" by cynicmusic (CC0), played to its end with two
repeats, each cut on the beat (30 ms crossfade): the theme repeats a section
52.6 s apart (jump back from 88.18 s to 35.58 s), and a 32-beat phrase
13.16 s apart (then, 115.55 s into the cut, back to 102.39 s); 95.8 s ->
161.55 s (MUSIC_SECONDS in teaser2.py). The jumps are the measured ones
(52.603 s and 13.162 s, the beat's own): the 2026-10-27 cut, sample for sample
outside its two crossfades.
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kit"))
from paths import MUSIC, work     # noqa: E402

MUSIC_IN = os.path.join(MUSIC, "battle_theme_a.ogg")
MUSIC_OUT = os.path.join(work("teaser2"), "battle_long.flac")
SECTION = (88.18, 35.57703)              # the first jump: from, to (seconds of the theme)
PHRASE = 13.16234                        # the second jump goes back a phrase ...
PHRASE_AT = 115.55                       # ... this far into the cut
FADE = 0.03


def music(out=MUSIC_OUT):
    end, back = SECTION
    second = back + PHRASE_AT - (end - FADE)    # the theme's time when the cut reaches PHRASE_AT
    rate = 44100                          # cut on samples: atrim in seconds lands a few ms off
    cut = lambda a, b=None: (f"atrim=start_sample={round(a * rate)}"
                             + (f":end_sample={round(b * rate)}" if b is not None else ""))
    parts = [cut(0, end), cut(back, second), cut(second - PHRASE)]
    graph = ";".join(["[0:a]asplit=3[s0][s1][s2]"]
                     + [f"[s{k}]{trim},asetpts=PTS-STARTPTS[p{k}]" for k, trim in enumerate(parts)]
                     + [f"[p0][p1]acrossfade=d={FADE}:c1=qsin:c2=qsin[x]",
                        f"[x][p2]acrossfade=d={FADE}:c1=qsin:c2=qsin"])
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", MUSIC_IN, "-filter_complex", graph, out],
                   check=True)


if __name__ == "__main__":
    music(sys.argv[1] if len(sys.argv) > 1 else MUSIC_OUT)
